package provision

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"strings"
	"time"

	commonpb "go.temporal.io/api/common/v1"
	enumspb "go.temporal.io/api/enums/v1"
	"go.temporal.io/api/serviceerror"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/converter"
	tlog "go.temporal.io/sdk/log"
	"go.temporal.io/sdk/temporal"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/snapshot"
)

// Workflow service defaults: the dev server.
const (
	DefaultAddress   = "localhost:7233"
	DefaultNamespace = "default"
)

// DefaultFirstTaskGuard is how long a command waits, after starting a run, for a worker to
// take its first task before terminating the run as run.worker.absent. A worker that
// stopped less than about five minutes ago is still listed as polling, so
// the poller check before a start cannot promise a worker by itself. A mechanism constant
// of the CLI, not a platform budget.
const DefaultFirstTaskGuard = 10 * time.Second

// StartRequestBudget bounds the request that starts a run. An interrupt does not cut that
// request short, so this bound is what keeps it from hanging. A mechanism constant
// of the CLI.
const StartRequestBudget = 10 * time.Second

// Client is the CLI's and the worker's connection to the workflow service.
type Client struct {
	client.Client
	Address   string
	Namespace string
	// FirstTaskGuard overrides DefaultFirstTaskGuard when positive; tests shorten it.
	FirstTaskGuard time.Duration
}

// Service is what cmd/fylgja needs from the workflow service. *Client implements it;
// command tests use a fake, so no command test needs a server. Not to be confused with
// lab.Runner, which executes clab.
type Service interface {
	// StartProvision starts the one provisioning run and returns its run id once a worker
	// has taken it. A run already in flight is a *StartError carrying run.in_flight; no
	// worker to take it is one carrying run.worker.absent, with nothing left running.
	StartProvision(ctx context.Context, in ProvisionInput) (runID string, err error)
	// Follow calls onEvent for each step boundary in the run's history as it happens, and
	// returns when the run has closed.
	Follow(ctx context.Context, workflowID, runID string, onEvent func(Event)) error
	// Result waits for the run to close and returns how it ended.
	Result(ctx context.Context, workflowID, runID string) (ProvisionResult, error)
	// Cancel asks the run to cancel. The run cleans up and then closes.
	Cancel(ctx context.Context, workflowID, runID string) error
	// StartDestroy destroys the twin through the destroy run and returns once that run has
	// closed. A provisioning run in flight is cancelled and waited for first, then a step run
	// in flight; a destroy run in flight is attached to rather than doubled.
	// It stops nothing else: nothing follows a branch (019). onEvent receives every run's
	// progress, and a Notice for each thing done to a run rather than by a step. No worker
	// to take the run is a *StartError carrying run.worker.absent.
	StartDestroy(ctx context.Context, onEvent func(Event)) (DestroyRun, error)
	// StartDestroyDetached is StartDestroy that returns once a worker has taken the destroy
	// run, or once it has attached to one in flight, without following it: its Result is
	// empty, and run.read reads it (020, R-03). What it cancels first it still waits for, as
	// StartDestroy does, since the destroy run starts only once those have closed.
	StartDestroyDetached(ctx context.Context, onEvent func(Event)) (DestroyRun, error)
	// InFlight names the provisioning run, the destroy run and the step run in flight, each
	// with the step its history has reached, and a step run the side it steps towards. It
	// changes nothing and needs no worker; a service that does not answer is an
	// *UnreachableError.
	InFlight(ctx context.Context) ([]RunInFlight, error)
	// StartStep starts the one step run and returns its run id once a worker has taken it
	// (M11). A provisioning, destroy or step run in
	// flight is a *StartError carrying run.in_flight, naming the run; no worker to take it is
	// one carrying run.worker.absent, with nothing left running.
	StartStep(ctx context.Context, in StepInput) (runID string, err error)
	// ResultOfStep waits for the step run to close and returns how it ended.
	ResultOfStep(ctx context.Context, runID string) (StepResult, error)
	// Describe is the run the identity names, the workflow's latest run when runID is "",
	// and its state (020, R-04). An identity the service holds no run under is an
	// *UnknownRunError; a service that does not answer is an *UnreachableError. It changes
	// nothing and needs no worker.
	Describe(ctx context.Context, workflowID, runID string) (RunState, error)
	// History calls onEvent for each step boundary the run's history holds so far, as Follow
	// would have, and returns without waiting for more: run.read of a running run (020).
	History(ctx context.Context, workflowID, runID string, onEvent func(Event)) error
	// InputOfStep is the input the step run was started with, read from its history: what a
	// step's document is built from beside its result (020).
	InputOfStep(ctx context.Context, runID string) (StepInput, error)
	// ResultOfDestroy waits for the destroy run to close and returns how it ended (020).
	ResultOfDestroy(ctx context.Context, runID string) (DestroyResult, error)
	Close()
}

// RunInFlight is a run that has not closed, and the step its history has reached, as
// findings name steps.
type RunInFlight struct {
	WorkflowID string
	RunID      string
	Step       string
	// Towards is the side a fylgja-step run is stepping towards, named by
	// wire.StepSide.Name() from its input (snapshot <short> or bundle <short>); "" for every
	// other run.
	Towards string
}

var _ Service = (*Client)(nil)

// UnreachableError is the workflow service not answering at Address.
type UnreachableError struct {
	Address string
	Err     error
}

func (e *UnreachableError) Error() string {
	return fmt.Sprintf("workflow service unreachable at %s: %v", e.Address, e.Err)
}

func (e *UnreachableError) Unwrap() error { return e.Err }

// UnknownRunError is an identity the workflow service holds no run under (020): run.read
// and run.interrupt refuse it as run.unknown. RunID is "" when the request named the
// workflow alone.
type UnknownRunError struct {
	WorkflowID string
	RunID      string
}

func (e *UnknownRunError) Error() string {
	return "the workflow service holds no run " + e.Identity()
}

// Identity is the run as the request named it: <workflow_id> <run_id>, or the workflow id
// alone.
func (e *UnknownRunError) Identity() string {
	return strings.TrimSpace(e.WorkflowID + " " + e.RunID)
}

// StartError is a run that was not started, under its own identifier: a refusal the
// command reports as a document rather than as a failure to run.
type StartError struct {
	Status  findings.Status
	Finding findings.Finding
}

func (e *StartError) Error() string { return e.Finding.Rule + ": " + e.Finding.Message }

// Document reports the refusal as op's findings document.
func (e *StartError) Document(op string, subject *findings.Subject) *findings.Document {
	doc := findings.NewDocument(op, subject, findings.List{e.Finding})
	doc.Status = e.Status
	return doc
}

// AsStartError reports err as a run that was not started, under its own identifier, when
// it is one: a refusal a start returned (run.in_flight, run.worker.absent), or the workflow
// service not answering the dial (run.service.unreachable, exit 2). Anything else is the
// operation failing and is left to the caller.
func AsStartError(err error) (*StartError, bool) {
	var refused *StartError
	if errors.As(err, &refused) {
		return refused, true
	}
	var unreachable *UnreachableError
	if errors.As(err, &unreachable) {
		return &StartError{Status: findings.StatusError, Finding: findings.Finding{
			Severity: findings.Rejection,
			Rule:     findings.RuleRunServiceUnreachable,
			Object:   unreachable.Address,
			Step:     findings.StepStart,
			Message:  unreachable.Error() + "; nothing was started",
		}}, true
	}
	return nil, false
}

// workerAbsent is run.worker.absent: nothing will take the run, so nothing is left running.
func workerAbsent(message string) *StartError {
	return &StartError{Status: findings.StatusError, Finding: findings.Finding{
		Severity: findings.Rejection,
		Rule:     findings.RuleRunWorkerAbsent,
		Object:   TaskQueue,
		Step:     findings.StepStart,
		Message:  message,
	}}
}

// requireWorker refuses to start anything when no worker polls task queue fylgja: a run no
// worker takes would wait for ever, and the command with it.
func (c *Client) requireWorker(ctx context.Context) error {
	resp, err := c.DescribeTaskQueue(ctx, TaskQueue, enumspb.TASK_QUEUE_TYPE_WORKFLOW)
	if err != nil {
		return fmt.Errorf("asking which workers poll task queue %s: %w", TaskQueue, err)
	}
	if len(resp.GetPollers()) > 0 {
		return nil
	}
	where := ""
	if c.Address != "" {
		where = " at " + c.Address
	}
	return workerAbsent(fmt.Sprintf("no worker is polling task queue %s%s, so nothing was started; start one on the lab host with fylgja worker run",
		TaskQueue, where))
}

// awaitFirstTask waits for a worker to take the run's first workflow task. A worker listed as
// polling may have stopped within the last five minutes; if none takes the
// task within the guard, the run is terminated — nothing in it has executed, so nothing on
// the host was touched — and the start is refused as run.worker.absent.
func (c *Client) awaitFirstTask(ctx context.Context, workflowID, runID string) error {
	guard := c.FirstTaskGuard
	if guard <= 0 {
		guard = DefaultFirstTaskGuard
	}
	wait, cancel := context.WithTimeout(ctx, guard)
	defer cancel()

	iter := c.GetWorkflowHistory(wait, workflowID, runID, true, enumspb.HISTORY_EVENT_FILTER_TYPE_ALL_EVENT)
	for iter.HasNext() {
		ev, err := iter.Next()
		if err != nil {
			if wait.Err() == nil {
				// The history could not be read. That does not say the worker is absent, so the
				// run is left alone.
				return fmt.Errorf("waiting for a worker to take run %s: %w", runID, err)
			}
			break
		}
		switch ev.GetEventType() {
		case enumspb.EVENT_TYPE_WORKFLOW_TASK_STARTED,
			// Closed before a task started (terminated, say): there is nothing to guard, and
			// the run's result says how it ended.
			enumspb.EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED,
			enumspb.EVENT_TYPE_WORKFLOW_EXECUTION_FAILED,
			enumspb.EVENT_TYPE_WORKFLOW_EXECUTION_TIMED_OUT,
			enumspb.EVENT_TYPE_WORKFLOW_EXECUTION_CANCELED,
			enumspb.EVENT_TYPE_WORKFLOW_EXECUTION_TERMINATED:
			return nil
		}
	}
	if ctx.Err() != nil {
		// The command was interrupted while it waited. No worker has taken the run's
		// first task, so nothing in it has run: it is terminated, on a context the interrupt
		// does not reach, rather than left for a worker to take after the command has gone. A
		// worker taking the task in this same instant can have begun at most the read, the
		// compile or the host check, none of which touches a lab.
		const terminateBudget = 10 * time.Second // a mechanism constant
		cancelled := func(msg string) error {
			return &StartError{Status: findings.StatusError, Finding: findings.Finding{
				Severity: findings.Rejection,
				Rule:     findings.RuleRunCancelled,
				Object:   runID,
				Step:     findings.StepStart,
				Message:  msg,
			}}
		}
		stop, cancelStop := context.WithTimeout(context.WithoutCancel(ctx), terminateBudget)
		defer cancelStop()
		if err := c.TerminateWorkflow(stop, workflowID, runID,
			"the command that started it was interrupted before a worker took its first task"); err != nil {
			return cancelled(fmt.Sprintf("interrupted before a worker took run %s, and terminating it failed (%v): fylgja twin destroy cancels it",
				runID, err))
		}
		return cancelled(fmt.Sprintf("interrupted before a worker took run %s, so the run was terminated before anything in it ran", runID))
	}
	if wait.Err() == nil {
		return nil
	}

	reason := fmt.Sprintf("no worker took the run's first task within %s", guard)
	if err := c.TerminateWorkflow(ctx, workflowID, runID, reason); err != nil {
		return fmt.Errorf("terminating run %s, which no worker took within %s: %w", runID, guard, err)
	}
	return workerAbsent(fmt.Sprintf("no worker took the first task of run %s within %s, so the run was terminated before anything in it ran; "+
		"a worker listed on task queue %s may have stopped in the last five minutes: start one on the lab host with fylgja worker run",
		runID, guard, TaskQueue))
}

// Dial connects to the workflow service named by FYLGJA_TEMPORAL_ADDRESS and
// FYLGJA_TEMPORAL_NAMESPACE. The SDK checks connectivity eagerly, so an unreachable
// service fails here, in milliseconds, rather than at the first call.
//
// The SDK logs through log, which must write to stderr: stdout belongs to the success
// lines and the --json document. A nil log logs warnings and errors to stderr.
func Dial(ctx context.Context, log *slog.Logger) (*Client, error) {
	addr := envOr(lab.EnvTemporalAddress, DefaultAddress)
	ns := envOr(lab.EnvTemporalNamespace, DefaultNamespace)
	if log == nil {
		log = slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelWarn}))
	}
	c, err := client.DialContext(ctx, client.Options{
		HostPort:  addr,
		Namespace: ns,
		Logger:    tlog.NewStructuredLogger(log),
	})
	if err != nil {
		return nil, &UnreachableError{Address: addr, Err: err}
	}
	return &Client{Client: c, Address: addr, Namespace: ns}, nil
}

func envOr(name, fallback string) string {
	if v, ok := os.LookupEnv(name); ok && v != "" {
		return v
	}
	return fallback
}

// provisionStartOptions start the one provisioning run. WorkflowExecutionErrorWhenAlreadyStarted
// is what makes a second create refuse rather than attach to the first and report that
// run's result as its own: without it the SDK swallows the server's refusal. Its absence is
// silent, which is why a test pins it.
func provisionStartOptions() client.StartWorkflowOptions {
	return client.StartWorkflowOptions{
		ID:                                       WorkflowProvision,
		TaskQueue:                                TaskQueue,
		WorkflowExecutionErrorWhenAlreadyStarted: true,
	}
}

// stepStartOptions start the one step run.
// WorkflowExecutionErrorWhenAlreadyStarted makes a second step refuse rather than attach to
// the first and report that run's result as its own, as provisionStartOptions does for a
// create. Its absence is silent, which is why a test pins it.
func stepStartOptions() client.StartWorkflowOptions {
	return client.StartWorkflowOptions{
		ID:                                       WorkflowStep,
		TaskQueue:                                TaskQueue,
		WorkflowExecutionErrorWhenAlreadyStarted: true,
	}
}

// destroyStartOptions start the destroy run or, when one is already running, hand back
// that run: USE_EXISTING attaches a second destroy to the first rather than running two
// teardowns against one lab. Once the run has closed, the next destroy
// starts a fresh one. Pinned by a test, like the provisioning options.
func destroyStartOptions() client.StartWorkflowOptions {
	return client.StartWorkflowOptions{
		ID:                       WorkflowDestroy,
		TaskQueue:                TaskQueue,
		WorkflowIDConflictPolicy: enumspb.WORKFLOW_ID_CONFLICT_POLICY_USE_EXISTING,
	}
}

// StartProvision implements Service. Nothing is started while no worker polls the queue,
// and a run no worker takes within the first-task guard is terminated.
func (c *Client) StartProvision(ctx context.Context, in ProvisionInput) (string, error) {
	if err := c.requireWorker(ctx); err != nil {
		return "", err
	}
	// A step run holds the twin a create would refuse beside, so it is refused here, naming
	// the run, before any run starts, rather than started and rejected at its host check by
	// host.lab.present.
	stepping, err := c.runningRun(ctx, WorkflowStep)
	if err != nil {
		return "", err
	}
	if stepping != "" {
		return "", InFlightRefusal(WorkflowStep, stepping)
	}
	// The start request is sent where an interrupt does not reach it. Cut short, it
	// can leave a run the service had already started, with no run id to terminate it by,
	// while the command says nothing was started. Sent to completion, the run id is known, and
	// an interrupt that arrived meanwhile is answered by awaitFirstTask, which terminates the
	// run before any worker takes it. requireWorker starts nothing, so it stays interruptible.
	send, cancelSend := context.WithTimeout(context.WithoutCancel(ctx), StartRequestBudget)
	run, err := c.ExecuteWorkflow(send, provisionStartOptions(), Provision, in)
	cancelSend()
	var started *serviceerror.WorkflowExecutionAlreadyStarted
	if errors.As(err, &started) {
		return "", InFlightRefusal(WorkflowProvision, started.RunId)
	}
	if err != nil {
		return "", fmt.Errorf("starting %s: %w", WorkflowProvision, err)
	}
	if err := c.awaitFirstTask(ctx, WorkflowProvision, run.GetRunID()); err != nil {
		return "", err
	}
	return run.GetRunID(), nil
}

// InFlightRefusal is run.in_flight for a start refused beside workflowID's run in flight, exit
// 1, naming the run (contracts/cli.md; a step reuses M2's identifier).
func InFlightRefusal(workflowID, runID string) *StartError {
	var message string
	switch workflowID {
	case WorkflowProvision:
		message = fmt.Sprintf("provisioning run %s is already in flight; wait for it to finish, or run fylgja twin destroy to cancel it", runID)
	case WorkflowDestroy:
		message = fmt.Sprintf("destroy run %s is already in flight; wait for it to finish", runID)
	default:
		message = fmt.Sprintf("step run %s is already in flight; wait for it to finish, or run fylgja twin destroy to cancel it", runID)
	}
	return &StartError{Status: findings.StatusRejected, Finding: findings.Finding{
		Severity: findings.Rejection,
		Rule:     findings.RuleRunInFlight,
		Object:   workflowID,
		Step:     findings.StepStart,
		Message:  message,
	}}
}

// StartStep implements Service, in StartProvision's shape. A provisioning or destroy run in
// flight refuses it first, naming the run: a step beside either would act on a twin that run
// is building or removing. A step run in flight refuses it through the fixed id, as a second create is refused. Nothing is
// started while no worker polls the queue, and a run no worker takes within the first-task
// guard is terminated before anything in it ran.
func (c *Client) StartStep(ctx context.Context, in StepInput) (string, error) {
	if err := c.requireWorker(ctx); err != nil {
		return "", err
	}
	for _, workflowID := range []string{WorkflowProvision, WorkflowDestroy} {
		runID, err := c.runningRun(ctx, workflowID)
		if err != nil {
			return "", err
		}
		if runID != "" {
			return "", InFlightRefusal(workflowID, runID)
		}
	}
	// Sent where an interrupt does not reach it, as StartProvision's is.
	send, cancelSend := context.WithTimeout(context.WithoutCancel(ctx), StartRequestBudget)
	run, err := c.ExecuteWorkflow(send, stepStartOptions(), Step, in)
	cancelSend()
	var started *serviceerror.WorkflowExecutionAlreadyStarted
	if errors.As(err, &started) {
		return "", InFlightRefusal(WorkflowStep, started.RunId)
	}
	if err != nil {
		return "", fmt.Errorf("starting %s: %w", WorkflowStep, err)
	}
	if err := c.awaitFirstTask(ctx, WorkflowStep, run.GetRunID()); err != nil {
		return "", err
	}
	return run.GetRunID(), nil
}

// ResultOfStep implements Service.
func (c *Client) ResultOfStep(ctx context.Context, runID string) (StepResult, error) {
	var res StepResult
	err := c.GetWorkflow(ctx, WorkflowStep, runID).Get(ctx, &res)
	return res, err
}

// StartDestroy implements Service.
//
// A provisioning run in flight is cancelled and waited for first: its own cleanup removes
// what it made, and the destroy run follows so that nothing it missed remains. A step run in
// flight is cancelled and waited for next, until its record is
// written. No signal: cancellation is the service's own request. Whether a destroy run was
// already in flight is asked before starting, so the attach can be reported. Nothing is cancelled or started while no worker polls the queue, and a
// destroy run no worker takes within the first-task guard is terminated.
func (c *Client) StartDestroy(ctx context.Context, onEvent func(Event)) (DestroyRun, error) {
	return c.startDestroy(ctx, onEvent, true)
}

// StartDestroyDetached implements Service.
func (c *Client) StartDestroyDetached(ctx context.Context, onEvent func(Event)) (DestroyRun, error) {
	return c.startDestroy(ctx, onEvent, false)
}

// startDestroy is StartDestroy, and StartDestroyDetached when follow is false.
func (c *Client) startDestroy(ctx context.Context, onEvent func(Event), follow bool) (DestroyRun, error) {
	if onEvent == nil {
		onEvent = func(Event) {}
	}
	notice := func(format string, args ...any) { onEvent(Event{Notice: fmt.Sprintf(format, args...)}) }

	if err := c.requireWorker(ctx); err != nil {
		return DestroyRun{}, err
	}

	provisioning, err := c.runningRun(ctx, WorkflowProvision)
	if err != nil {
		return DestroyRun{}, err
	}
	if provisioning != "" {
		notice("cancelling provisioning run %s; waiting for its cleanup", provisioning)
		if err := c.CancelWorkflow(ctx, WorkflowProvision, provisioning); err != nil {
			return DestroyRun{}, fmt.Errorf("cancelling provisioning run %s: %w", provisioning, err)
		}
		// Progress is best effort; the close is what destroy waits for.
		_ = c.Follow(ctx, WorkflowProvision, provisioning, onEvent)
		var res ProvisionResult
		err := c.GetWorkflow(ctx, WorkflowProvision, provisioning).Get(ctx, &res)
		var closedWithout *temporal.WorkflowExecutionError
		switch {
		case errors.As(err, &closedWithout):
			// Terminated or timed out: closed without a result, which is all destroy needs.
			notice("provisioning run %s closed without a result: %v", provisioning, err)
		case err != nil:
			return DestroyRun{}, fmt.Errorf("waiting for provisioning run %s to close: %w", provisioning, err)
		default:
			notice("provisioning run %s closed: %s", provisioning, res.Outcome)
		}
	}

	// A step run in flight is cancelled and waited for in the same way: it tears
	// nothing down, but writes its record diverged on a context the cancellation does not
	// reach, and the destroy then removes the lab and that record with the twin directory.
	stepping, err := c.runningRun(ctx, WorkflowStep)
	if err != nil {
		return DestroyRun{}, err
	}
	if stepping != "" {
		notice("cancelling step run %s; waiting for its record", stepping)
		if err := c.CancelWorkflow(ctx, WorkflowStep, stepping); err != nil {
			return DestroyRun{}, fmt.Errorf("cancelling step run %s: %w", stepping, err)
		}
		// Progress is best effort; the close is what destroy waits for.
		_ = c.Follow(ctx, WorkflowStep, stepping, onEvent)
		var res StepResult
		err := c.GetWorkflow(ctx, WorkflowStep, stepping).Get(ctx, &res)
		var closedWithout *temporal.WorkflowExecutionError
		switch {
		case errors.As(err, &closedWithout):
			notice("step run %s closed without a result: %v", stepping, err)
		case err != nil:
			return DestroyRun{}, fmt.Errorf("waiting for step run %s to close: %w", stepping, err)
		default:
			notice("step run %s closed: %s", stepping, StepClosedAs(res))
		}
	}

	return c.destroy(ctx, onEvent, follow)
}

// destroy is StartDestroy once no provisioning or step run is in flight: the destroy run started, or attached to, and followed to its close, or left once a
// worker has taken it when follow is false (020).
func (c *Client) destroy(ctx context.Context, onEvent func(Event), follow bool) (DestroyRun, error) {
	notice := func(format string, args ...any) { onEvent(Event{Notice: fmt.Sprintf(format, args...)}) }

	inFlight, err := c.runningRun(ctx, WorkflowDestroy)
	if err != nil {
		return DestroyRun{}, err
	}
	run, err := c.ExecuteWorkflow(ctx, destroyStartOptions(), Destroy)
	if err != nil {
		return DestroyRun{}, fmt.Errorf("starting %s: %w", WorkflowDestroy, err)
	}
	out := DestroyRun{RunID: run.GetRunID()}
	if err := c.awaitFirstTask(ctx, WorkflowDestroy, out.RunID); err != nil {
		return DestroyRun{}, err
	}
	out.Attached = inFlight != "" && inFlight == out.RunID
	if out.Attached {
		notice("attached to destroy run %s already in flight", out.RunID)
	} else {
		notice("run %s %s", WorkflowDestroy, out.RunID)
	}
	if !follow {
		return out, nil
	}
	_ = c.Follow(ctx, WorkflowDestroy, out.RunID, onEvent)
	if err := run.Get(ctx, &out.Result); err != nil {
		return DestroyRun{}, fmt.Errorf("waiting for destroy run %s: %w", out.RunID, err)
	}
	return out, nil
}

// unreachable reports a read twin show made that the service did not answer. Whatever the
// cause, twin show can say only that the runs in flight are unknown.
func (c *Client) unreachable(err error) error {
	var already *UnreachableError
	if errors.As(err, &already) {
		return err
	}
	return &UnreachableError{Address: c.Address, Err: err}
}

// InFlight implements Service. A step run is named with its target.
func (c *Client) InFlight(ctx context.Context) ([]RunInFlight, error) {
	var runs []RunInFlight
	for _, workflowID := range []string{WorkflowProvision, WorkflowDestroy, WorkflowStep} {
		runID, err := c.runningRun(ctx, workflowID)
		if err != nil {
			return nil, c.unreachable(err)
		}
		if runID == "" {
			continue
		}
		run := RunInFlight{WorkflowID: workflowID, RunID: runID}
		if run.Step, err = c.historyStep(ctx, workflowID, runID); err != nil {
			return nil, err
		}
		if workflowID == WorkflowStep {
			if run.Towards, err = c.towards(ctx, runID); err != nil {
				return nil, err
			}
		}
		runs = append(runs, run)
	}
	return runs, nil
}

// towards is the side the step run runID steps towards, read from the input its history
// starts with and named by wire.StepSide.Name() (snapshot <short>…, or bundle <short>…). ""
// when its input cannot be read.
func (c *Client) towards(ctx context.Context, runID string) (string, error) {
	iter := c.GetWorkflowHistory(ctx, WorkflowStep, runID, false, enumspb.HISTORY_EVENT_FILTER_TYPE_ALL_EVENT)
	if !iter.HasNext() {
		return "", nil
	}
	ev, err := iter.Next()
	if err != nil {
		return "", c.unreachable(err)
	}
	attrs := ev.GetWorkflowExecutionStartedEventAttributes()
	if attrs == nil {
		return "", nil
	}
	var in StepInput
	if converter.GetDefaultDataConverter().FromPayloads(attrs.GetInput(), &in) != nil {
		return "", nil
	}
	return in.To.Name(), nil
}

// historyStep reads a run's history once, without waiting for more, and returns the step
// it has reached: the last activity scheduled and not closed, or else the last scheduled, or
// start when nothing has been.
func (c *Client) historyStep(ctx context.Context, workflowID, runID string) (string, error) {
	var order []int64
	scheduled := map[int64]string{}
	open := map[int64]bool{}
	closeEvent := func(id int64) { delete(open, id) }

	iter := c.GetWorkflowHistory(ctx, workflowID, runID, false, enumspb.HISTORY_EVENT_FILTER_TYPE_ALL_EVENT)
	for iter.HasNext() {
		ev, err := iter.Next()
		if err != nil {
			return "", c.unreachable(err)
		}
		switch ev.GetEventType() {
		case enumspb.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED:
			order = append(order, ev.GetEventId())
			scheduled[ev.GetEventId()] = ev.GetActivityTaskScheduledEventAttributes().GetActivityType().GetName()
			open[ev.GetEventId()] = true
		case enumspb.EVENT_TYPE_ACTIVITY_TASK_COMPLETED:
			closeEvent(ev.GetActivityTaskCompletedEventAttributes().GetScheduledEventId())
		case enumspb.EVENT_TYPE_ACTIVITY_TASK_FAILED:
			closeEvent(ev.GetActivityTaskFailedEventAttributes().GetScheduledEventId())
		case enumspb.EVENT_TYPE_ACTIVITY_TASK_TIMED_OUT:
			closeEvent(ev.GetActivityTaskTimedOutEventAttributes().GetScheduledEventId())
		case enumspb.EVENT_TYPE_ACTIVITY_TASK_CANCELED:
			closeEvent(ev.GetActivityTaskCanceledEventAttributes().GetScheduledEventId())
		}
	}
	if len(order) == 0 {
		return findings.StepStart, nil
	}
	reached := order[len(order)-1]
	for i := len(order) - 1; i >= 0; i-- {
		if open[order[i]] {
			reached = order[i]
			break
		}
	}
	step := findingStep(scheduled[reached])
	if step == "" {
		step = stepName(workflowID, scheduled[reached])
	}
	return step, nil
}

// runningRun is the id of workflowID's run in flight, or "" when none is running.
func (c *Client) runningRun(ctx context.Context, workflowID string) (string, error) {
	desc, err := c.DescribeWorkflowExecution(ctx, workflowID, "")
	var notFound *serviceerror.NotFound
	if errors.As(err, &notFound) {
		return "", nil
	}
	if err != nil {
		return "", fmt.Errorf("describing %s: %w", workflowID, err)
	}
	info := desc.GetWorkflowExecutionInfo()
	if info.GetStatus() != enumspb.WORKFLOW_EXECUTION_STATUS_RUNNING {
		return "", nil
	}
	return info.GetExecution().GetRunId(), nil
}

// How a step ended, on an Event with End set.
const (
	EventDone      = "done"
	EventFailed    = "failed"
	EventTimedOut  = "timed out"
	EventCancelled = "cancelled"
)

// Event is one step boundary in a run's history: a step begins when its activity is
// scheduled and ends when it completes, fails, times out or is cancelled.
type Event struct {
	Step     string        // "read", "compile", "readiness n1", "cleanup teardown", …
	End      bool          // false: the step began
	Outcome  string        // on End: EventDone, EventFailed, EventTimedOut or EventCancelled
	Duration time.Duration // on End: from scheduled to closed
	Detail   string        // on EventDone, when the result says something: "3 nodes", "no lab"
	Rule     string        // on EventFailed: the failure's type, which is its rule identifier
	Message  string        // on EventFailed and EventTimedOut
	// WorkflowID is the run the step belongs to: a destroy follows a provisioning run it
	// cancelled before following its own.
	WorkflowID string
	// FindingStep is the step as findings name it (findings.Step*), so a failure met while
	// following the run names the step the run had reached.
	FindingStep string
	// Notice is a line about a run rather than a step: the run being followed, one being
	// cancelled or attached to. When it is set, the other fields are empty.
	Notice string
}

// findingStep is the step, as findings name it, an activity belongs to. PlanTeardown budgets
// the teardown, so it is part of it.
func findingStep(activityType string) string {
	switch activityType {
	case wire.ActInspectTwin:
		return findings.StepInspect
	case wire.ActCheckHost:
		return findings.StepHostCheck
	case wire.ActStageBundle:
		return findings.StepStage
	case wire.ActDeployLab:
		return findings.StepDeploy
	case wire.ActAwaitReadiness:
		return findings.StepReadiness
	case wire.ActPushConfig:
		return findings.StepPush
	case wire.ActRecordTwin:
		return findings.StepRecord
	case wire.ActPlanTeardown, wire.ActDestroyLab:
		return findings.StepTeardown
	case wire.ActUnstageTwin:
		return findings.StepUnstage
	// M11: the step run's own. Containerlab's plan
	// is the compare step's, as the rules on it are; the stage swap is the stage.
	case wire.ActPlanReconcile:
		return findings.StepCompare
	case wire.ActStageStep:
		return findings.StepStage
	case wire.ActReconcileLab:
		return findings.StepReconcile
	case wire.ActRecordStep:
		return findings.StepRecord
	// M12: the step's wait after its record.
	case wire.ActVerifyTwin:
		return findings.StepObserve
	// 016: the step's flows, started after its stage and read after its wait.
	case wire.ActStartFlows, wire.ActReadFlows:
		return findings.StepFlows
	}
	return ""
}

// Follow implements Service over the run's event history, long-polled, so progress needs
// no query handler, signal or change to workflow code (D-007).
func (c *Client) Follow(ctx context.Context, workflowID, runID string, onEvent func(Event)) error {
	return c.follow(ctx, workflowID, runID, true, onEvent)
}

// History implements Service: Follow's events over the history as it stands, read once
// without waiting for more, so a running run's read ends where its history does (020).
func (c *Client) History(ctx context.Context, workflowID, runID string, onEvent func(Event)) error {
	return c.follow(ctx, workflowID, runID, false, onEvent)
}

// follow is Follow and History: the run's history read event by event, waiting for more
// when wait is set. No workflow the worker serves starts a child (020), so a run's history
// is its activities alone.
func (c *Client) follow(ctx context.Context, workflowID, runID string, wait bool, onEvent func(Event)) error {
	type scheduled struct {
		activityType string
		step         string
		at           time.Time
	}
	open := map[int64]scheduled{}
	ended := func(id int64, at time.Time) (scheduled, time.Duration) {
		s := open[id]
		delete(open, id)
		return s, at.Sub(s.at)
	}
	dc := converter.GetDefaultDataConverter()
	// Every step event names its run and its step as findings name it.
	emit := func(activityType string, e Event) {
		e.WorkflowID, e.FindingStep = workflowID, findingStep(activityType)
		onEvent(e)
	}

	iter := c.GetWorkflowHistory(ctx, workflowID, runID, wait, enumspb.HISTORY_EVENT_FILTER_TYPE_ALL_EVENT)
	for iter.HasNext() {
		ev, err := iter.Next()
		if err != nil {
			return err
		}
		at := ev.GetEventTime().AsTime()
		switch ev.GetEventType() {
		case enumspb.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED:
			a := ev.GetActivityTaskScheduledEventAttributes()
			name := a.GetActivityType().GetName()
			step := stepName(workflowID, name)
			// Readiness and the push are one activity per node, and each is named by its node.
			switch name {
			case wire.ActAwaitReadiness:
				var in wire.ReadinessInput
				if dc.FromPayloads(a.GetInput(), &in) == nil {
					step += " " + in.Node
				}
			case wire.ActPushConfig:
				var in wire.PushInput
				if dc.FromPayloads(a.GetInput(), &in) == nil {
					step += " " + in.Node
				}
			}
			open[ev.GetEventId()] = scheduled{activityType: name, step: step, at: at}
			emit(name, Event{Step: step})
		case enumspb.EVENT_TYPE_ACTIVITY_TASK_COMPLETED:
			a := ev.GetActivityTaskCompletedEventAttributes()
			s, d := ended(a.GetScheduledEventId(), at)
			emit(s.activityType, Event{Step: s.step, End: true, Outcome: EventDone, Duration: d,
				Detail: completedDetail(dc, s.activityType, a.GetResult())})
		case enumspb.EVENT_TYPE_ACTIVITY_TASK_FAILED:
			a := ev.GetActivityTaskFailedEventAttributes()
			s, d := ended(a.GetScheduledEventId(), at)
			emit(s.activityType, Event{Step: s.step, End: true, Outcome: EventFailed, Duration: d,
				Rule: a.GetFailure().GetApplicationFailureInfo().GetType(), Message: a.GetFailure().GetMessage()})
		case enumspb.EVENT_TYPE_ACTIVITY_TASK_TIMED_OUT:
			a := ev.GetActivityTaskTimedOutEventAttributes()
			s, d := ended(a.GetScheduledEventId(), at)
			emit(s.activityType, Event{Step: s.step, End: true, Outcome: EventTimedOut, Duration: d, Message: a.GetFailure().GetMessage()})
		case enumspb.EVENT_TYPE_ACTIVITY_TASK_CANCELED:
			a := ev.GetActivityTaskCanceledEventAttributes()
			s, d := ended(a.GetScheduledEventId(), at)
			emit(s.activityType, Event{Step: s.step, End: true, Outcome: EventCancelled, Duration: d})

		case enumspb.EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED,
			enumspb.EVENT_TYPE_WORKFLOW_EXECUTION_FAILED,
			enumspb.EVENT_TYPE_WORKFLOW_EXECUTION_TIMED_OUT,
			enumspb.EVENT_TYPE_WORKFLOW_EXECUTION_CANCELED,
			enumspb.EVENT_TYPE_WORKFLOW_EXECUTION_TERMINATED,
			enumspb.EVENT_TYPE_WORKFLOW_EXECUTION_CONTINUED_AS_NEW:
			return nil
		}
	}
	return nil
}

// stepName is the step an activity performs, named as contracts/cli.md names it. Teardown and
// unstage are a provisioning run's cleanup, and the whole of a destroy run. A step run names
// its inspection and its four activities (M11).
func stepName(workflowID, activityType string) string {
	if workflowID == WorkflowStep && activityType == wire.ActInspectTwin {
		return "inspect"
	}
	switch activityType {
	// M11: the step run's own (contracts/cli.md, twin step).
	case wire.ActPlanReconcile:
		return "plan reconcile"
	case wire.ActStageStep:
		return "stage"
	case wire.ActReconcileLab:
		return "reconcile"
	case wire.ActRecordStep:
		return "record"
	// M12: the step's wait after its record.
	case wire.ActVerifyTwin:
		return "observe"
	// 016: the step's flows, started as flows and read as the loss they measured
	// (contracts/cli.md, twin step); both are the findings' step flows.
	case wire.ActStartFlows:
		return "flows"
	case wire.ActReadFlows:
		return "loss"
	case wire.ActCheckHost:
		return "host check"
	case wire.ActStageBundle:
		return "stage"
	case wire.ActDeployLab:
		return "deploy"
	case wire.ActAwaitReadiness:
		return "readiness"
	case wire.ActPushConfig:
		return "push"
	case wire.ActRecordTwin:
		return "record"
	case wire.ActPlanTeardown:
		return "plan teardown"
	case wire.ActDestroyLab:
		if workflowID == WorkflowDestroy {
			return "teardown"
		}
		return "cleanup teardown"
	case wire.ActUnstageTwin:
		if workflowID == WorkflowDestroy {
			return "unstage"
		}
		return "cleanup unstage"
	}
	return activityType
}

// completedDetail is what a completed step's result says worth printing.
func completedDetail(dc converter.DataConverter, activityType string, result *commonpb.Payloads) string {
	switch activityType {
	case wire.ActDeployLab:
		var r wire.DeployResult
		if dc.FromPayloads(result, &r) == nil {
			return plural(len(r.Nodes), "node")
		}
	case wire.ActDestroyLab:
		var r wire.DestroyLabResult
		if dc.FromPayloads(result, &r) == nil {
			if r.Removed {
				return plural(r.Containers, "container")
			}
			return "no lab"
		}
	case wire.ActUnstageTwin:
		var r wire.UnstageResult
		if dc.FromPayloads(result, &r) == nil && !r.Removed {
			return "no twin directory"
		}
	case wire.ActPlanReconcile:
		var p wire.ReconcilePlan
		if dc.FromPayloads(result, &p) == nil {
			return planDetail(p)
		}
	case wire.ActReconcileLab:
		var r wire.ReconcileResult
		if dc.FromPayloads(result, &r) == nil {
			return plural(len(r.Nodes), "node")
		}
	case wire.ActVerifyTwin:
		var r wire.VerifyResult
		if dc.FromPayloads(result, &r) == nil {
			return waitDetail(r.Wait)
		}
	case wire.ActStartFlows:
		var r wire.FlowsResult
		if dc.FromPayloads(result, &r) == nil {
			return flowsDetail(r.Flows)
		}
	case wire.ActReadFlows:
		var r wire.ReadFlowsResult
		if dc.FromPayloads(result, &r) == nil {
			return lossDetail(r.Loss)
		}
	}
	return ""
}

// flowsDetail is how each flow's start ended, as the flows step's progress line names it
// (contracts/cli.md, twin step): "n1-loop started; n2-loop not started: <why>".
func flowsDetail(flows []wire.FlowOutcome) string {
	var parts []string
	for _, f := range flows {
		switch {
		case f.Outcome == wire.FlowStarted:
			parts = append(parts, f.Probe+" started")
		case f.Message != "":
			parts = append(parts, f.Probe+" not started: "+f.Message)
		default:
			parts = append(parts, f.Probe+" not started")
		}
	}
	return strings.Join(parts, "; ")
}

// lossDetail is what the step's flows lost, as the loss step's progress line names it
// (contracts/cli.md, twin step): "n1-loop 0/312 lost, longest gap 0.0s (container timing)",
// one part per probe, then the probes the target adds and drops, which no flow measured. A
// figure is the container's, and the line says so.
func lossDetail(l wire.Loss) string {
	var parts []string
	for _, p := range l.Probes {
		figures := fmt.Sprintf("%d/%d lost, longest gap %.1fs", p.Lost, p.Sent, p.LongestGapS)
		switch p.Outcome {
		case wire.FlowMeasured:
			parts = append(parts, p.Probe+" "+figures)
		case wire.FlowInterrupted:
			parts = append(parts, p.Probe+" interrupted, "+figures)
		case wire.FlowNotStarted:
			parts = append(parts, p.Probe+" not started")
		default:
			part := p.Probe + " not read"
			if p.Message != "" {
				part += ": " + p.Message
			}
			parts = append(parts, part)
		}
	}
	if len(l.Added) > 0 {
		parts = append(parts, "added "+strings.Join(l.Added, ", ")+", not measured")
	}
	if len(l.Dropped) > 0 {
		parts = append(parts, "dropped "+strings.Join(l.Dropped, ", ")+", not measured")
	}
	if len(parts) == 0 {
		return "no flow"
	}
	return strings.Join(parts, "; ") + " (container timing)"
}

// waitDetail is how the step's wait ended, as the observe step's progress line names it
// (contracts/cli.md, twin step --wait): "settled
// after 2.4s (2 reads)", "expired after 120.0s (58 reads, 3 failing)", "cancelled after 12.4s
// (7 reads)", or "could not complete: e1 still unread after 120.3s (58 reads, 1 failing)",
// where failing counts the assertions beside the unread nodes.
func waitDetail(w wire.StepWait) string {
	reads := plural(w.Reads, "read")
	var unread []string
	failing := 0
	for _, f := range w.Failing {
		if f.Rule == findings.RuleOperationFailed {
			unread = append(unread, f.Object)
			continue
		}
		failing++
	}
	switch w.Outcome {
	case wire.WaitSettled:
		return fmt.Sprintf("settled after %.1fs (%s)", w.AfterS, reads)
	case wire.WaitExpired:
		return fmt.Sprintf("expired after %.1fs (%s, %d failing)", w.AfterS, reads, failing)
	case wire.WaitCancelled:
		return fmt.Sprintf("cancelled after %.1fs (%s)", w.AfterS, reads)
	}
	if failing > 0 {
		reads += fmt.Sprintf(", %d failing", failing)
	}
	return fmt.Sprintf("could not complete: %s still unread after %.1fs (%s)", strings.Join(unread, ", "), w.AfterS, reads)
}

// planDetail is what containerlab's plan does, as the plan reconcile step's line names
// it:
// each lifecycle with its nodes, "restart e1; create s2"; the nodes it
// re-cables live when it does nothing else; "nothing to apply" for an empty plan.
func planDetail(p wire.ReconcilePlan) string {
	if p.Empty() {
		return "nothing to apply"
	}
	verbs := map[string][]string{}
	for _, n := range p.Nodes() {
		verbs[n.Reported] = append(verbs[n.Reported], n.Node)
	}
	verbs["delete"] = append(verbs["delete"], p.Deleted...)
	var parts []string
	for _, verb := range []string{wire.ReportedRestart, wire.ReportedRecreate, wire.ReportedCreate, "delete"} {
		if nodes := verbs[verb]; len(nodes) > 0 {
			parts = append(parts, verb+" "+strings.Join(nodes, ", "))
		}
	}
	if len(parts) == 0 {
		return "live " + strings.Join(verbs[wire.ReportedLive], ", ")
	}
	return strings.Join(parts, "; ")
}

// Result implements Service.
func (c *Client) Result(ctx context.Context, workflowID, runID string) (ProvisionResult, error) {
	var res ProvisionResult
	err := c.GetWorkflow(ctx, workflowID, runID).Get(ctx, &res)
	return res, err
}

// ResultOfDestroy implements Service.
func (c *Client) ResultOfDestroy(ctx context.Context, runID string) (DestroyResult, error) {
	var res DestroyResult
	err := c.GetWorkflow(ctx, WorkflowDestroy, runID).Get(ctx, &res)
	return res, err
}

// InputOfStep implements Service: the input the step run's history starts with, as towards
// reads it.
func (c *Client) InputOfStep(ctx context.Context, runID string) (StepInput, error) {
	var in StepInput
	iter := c.GetWorkflowHistory(ctx, WorkflowStep, runID, false, enumspb.HISTORY_EVENT_FILTER_TYPE_ALL_EVENT)
	if !iter.HasNext() {
		return in, fmt.Errorf("the history of step run %s is empty", runID)
	}
	ev, err := iter.Next()
	if err != nil {
		return in, c.unreachable(err)
	}
	attrs := ev.GetWorkflowExecutionStartedEventAttributes()
	if attrs == nil {
		return in, fmt.Errorf("the history of step run %s does not begin with its start", runID)
	}
	if err := converter.GetDefaultDataConverter().FromPayloads(attrs.GetInput(), &in); err != nil {
		return in, fmt.Errorf("reading the input of step run %s: %w", runID, err)
	}
	return in, nil
}

// Describe implements Service over DescribeWorkflowExecution, the one call run.read and
// run.interrupt make before anything else (020, R-04). The service answers NotFound for an
// identity it holds no run under, and InvalidArgument ("Invalid RunId.") for a run id that
// is no run's shape (verified on the dev server, Temporal CLI 1.9.1, 2026-10-29): both name
// no run.
func (c *Client) Describe(ctx context.Context, workflowID, runID string) (RunState, error) {
	desc, err := c.DescribeWorkflowExecution(ctx, workflowID, runID)
	var notFound *serviceerror.NotFound
	var invalid *serviceerror.InvalidArgument
	if errors.As(err, &notFound) || errors.As(err, &invalid) {
		return RunState{}, &UnknownRunError{WorkflowID: workflowID, RunID: runID}
	}
	if err != nil {
		return RunState{}, c.unreachable(err)
	}
	info := desc.GetWorkflowExecutionInfo()
	state, ok := runStates[info.GetStatus()]
	if !ok {
		return RunState{}, fmt.Errorf("run %s %s is in state %s, which no run of Fylgja's reaches",
			workflowID, info.GetExecution().GetRunId(), info.GetStatus())
	}
	return RunState{WorkflowID: workflowID, RunID: info.GetExecution().GetRunId(), State: state}, nil
}

// runStates are the workflow service's statuses as run.read names them. A continued-as-new
// run is none: no workflow of Fylgja's continues as new.
var runStates = map[enumspb.WorkflowExecutionStatus]string{
	enumspb.WORKFLOW_EXECUTION_STATUS_RUNNING:    RunRunning,
	enumspb.WORKFLOW_EXECUTION_STATUS_COMPLETED:  RunCompleted,
	enumspb.WORKFLOW_EXECUTION_STATUS_FAILED:     RunFailed,
	enumspb.WORKFLOW_EXECUTION_STATUS_CANCELED:   RunCancelled,
	enumspb.WORKFLOW_EXECUTION_STATUS_TERMINATED: RunTerminated,
	enumspb.WORKFLOW_EXECUTION_STATUS_TIMED_OUT:  RunTimedOut,
}

// Cancel implements Service. No signal: cancellation is the workflow service's own
// request, and the run's cleanup answers it (D-007).
func (c *Client) Cancel(ctx context.Context, workflowID, runID string) error {
	return c.CancelWorkflow(ctx, workflowID, runID)
}

// ProvisionDocument reports how a provisioning run ended as op's findings document. The
// status follows the outcome and, after the host was touched, what cleanup left behind:
// ready → ok; rejected → rejected; error, and a cancellation before the
// host check cleared (cleanup skipped) → error; any other failure or cancellation →
// failed when nothing remains, unclean when something does. A cancelled run carries
// run.cancelled, naming the run.
func ProvisionDocument(op string, subject *findings.Subject, res ProvisionResult) *findings.Document {
	list := res.Findings
	if res.Outcome == OutcomeCancelled {
		list = append(append(findings.List{}, list...), cancelledFinding(subject, res))
	}
	doc := findings.NewDocument(op, subject, list)
	doc.Status = provisionStatus(res)
	if bundle.IsID(res.BundleID) {
		doc.BundleID = res.BundleID
	}
	if res.Outcome == OutcomeReady && res.Twin != nil {
		doc.Twin = twinBlock(res)
		return doc
	}
	doc.Cleanup = CleanupBlockOf(res.Cleanup)
	return doc
}

// DestroyDocument reports a destroy run as twin.destroy's findings document: ok when
// nothing remains on the host, unclean when something does (contracts/cli.md).
func DestroyDocument(subject *findings.Subject, res DestroyResult) *findings.Document {
	doc := findings.NewDocument(findings.OpTwinDestroy, subject, res.Findings)
	doc.Status = findings.StatusOK
	if len(res.Cleanup.Remaining) > 0 {
		doc.Status = findings.StatusUnclean
	}
	doc.Cleanup = CleanupBlockOf(res.Cleanup)
	return doc
}

func provisionStatus(res ProvisionResult) findings.Status {
	switch res.Outcome {
	case OutcomeReady:
		return findings.StatusOK
	case OutcomeRejected:
		return findings.StatusRejected
	case OutcomeFailed, OutcomeCancelled:
		if res.Outcome == OutcomeCancelled && orSkipped(res.Cleanup.Teardown) == CleanupSkipped {
			return findings.StatusError
		}
		if len(res.Cleanup.Remaining) > 0 {
			return findings.StatusUnclean
		}
		return findings.StatusFailed
	default:
		return findings.StatusError
	}
}

// cancelledFinding is run.cancelled for a cancelled run: before the host check cleared
// nothing was touched; after, the cleanup block says what teardown and unstage did.
func cancelledFinding(subject *findings.Subject, res ProvisionResult) findings.Finding {
	runID := ""
	if subject != nil {
		runID = subject.RunID
	}
	msg := fmt.Sprintf("run %s was cancelled at step %s; teardown and unstage then ran", runID, res.Step)
	if orSkipped(res.Cleanup.Teardown) == CleanupSkipped {
		msg = fmt.Sprintf("run %s was cancelled at step %s, before the host check cleared; nothing on the host was touched",
			runID, res.Step)
	}
	return findings.Finding{
		Severity: findings.Rejection,
		Rule:     findings.RuleRunCancelled,
		Object:   runID,
		Step:     res.Step,
		Message:  msg,
	}
}

// CleanupBlockOf is what teardown and unstage did as a document's cleanup block, a step not
// attempted written skipped: a destroy's.
func CleanupBlockOf(c CleanupResult) *findings.CleanupBlock {
	return &findings.CleanupBlock{
		Teardown:  orSkipped(c.Teardown),
		Unstage:   orSkipped(c.Unstage),
		Removed:   c.Removed,
		Remaining: c.Remaining,
	}
}

func orSkipped(status string) string {
	if status == "" {
		return CleanupSkipped
	}
	return status
}

func twinBlock(res ProvisionResult) *findings.TwinBlock {
	rec := res.Twin
	nodes := make([]findings.TwinNode, len(rec.Nodes))
	for i, n := range rec.Nodes {
		nodes[i] = findings.TwinNode{Name: n.Name, MgmtIPv4: n.MgmtIPv4, ReadyAfterS: n.ReadyAfterS, PushedInS: n.PushedInS}
		// The record's four artifact fields, projected to the two the document names an
		// artifact by.
		if a := n.Artifact; a != nil {
			nodes[i].Artifact = &findings.ShowArtifact{Name: a.Name, Checksum: a.Checksum}
		}
	}
	return &findings.TwinBlock{
		Lab:        rec.Lab,
		Dir:        res.TwinDir,
		RunID:      rec.Run.RunID,
		ObservedAt: rec.ObservedAt,
		Nodes:      nodes,
	}
}

// StepClosedAs is how a step run closed, as twin destroy's notice names it (contracts/cli.md):
// diverged when it stopped after its stage, by a failure or a cancellation, since its record
// then says so; its outcome otherwise.
func StepClosedAs(res StepResult) string {
	if res.Phase != "" {
		return StepDiverged
	}
	return res.Outcome
}

// StepDocument reports a step run as twin.step's findings document: the target's snapshot
// and bundle, the step block the command printed, the run's fields added once
// the run closed, and the run's findings. Status: ok for stepped and unchanged; rejected for
// a refusal before the stage, the run's second locks included; error for a step that could
// not run or was cancelled before its stage; diverged, exit 4, for any failure or
// cancellation from the stage on. A step never ends failed or unclean: it tears nothing
// down. No diff is copied: the result carries none.
func StepDocument(subject *findings.Subject, in StepInput, res StepResult) *findings.Document {
	doc := findings.NewDocument(findings.OpTwinStep, subject, res.Findings)
	doc.Status = stepStatus(res)
	if bundle.IsID(in.To.BundleID) {
		doc.BundleID = in.To.BundleID
	}
	// The target's snapshot beside its bundle (018), as the command's dry run names it.
	if snapshot.IsID(in.To.SnapshotID) {
		doc.SnapshotID = in.To.SnapshotID
	}
	plan := in.Plan
	if res.Plan != nil {
		plan = *res.Plan
	}
	block := StepBlockOf(in, plan)
	runID := ""
	if subject != nil {
		runID = subject.RunID
	}
	run := &findings.StepRunBlock{
		Run:       findings.ShowRef{WorkflowID: WorkflowStep, RunID: runID},
		Phase:     res.Phase,
		StartedAt: res.StartedAt,
		EndedAt:   res.EndedAt,
		Timings: findings.StepTimingsBlock{ReconcileS: res.Timings.ReconcileS, Readiness: res.Timings.Readiness,
			Push: res.Timings.Push, WholeS: res.Timings.WholeS},
	}
	staged := res.Phase != "" || res.Outcome == StepStepped || res.Outcome == StepUnchanged
	if staged {
		run.Outcome = res.Outcome
		if res.Phase != "" {
			run.Outcome = StepDiverged
		}
		// The run's push plan is the CLI's with the run's own plan applied.
		block.PushPlan = make([]findings.StepPushPlanEntry, len(res.PushPlan))
		for i, p := range res.PushPlan {
			block.PushPlan[i] = findings.StepPushPlanEntry{Node: p.Node, Reasons: p.Reasons}
			run.Pushed = append(run.Pushed, findings.StepPushedEntry{Node: p.Node, Reasons: p.Reasons, Outcome: p.Outcome,
				Rule: p.Rule, TookS: p.TookS})
		}
		block.Reconcile.Skipped = plan.Empty() || in.Unchanged
		if r := res.Reconcile; r != nil {
			took := r.TookS
			block.Reconcile.TookS = &took
		}
	}
	if res.Record != nil {
		run.State = res.Record.State
	}
	for _, r := range res.Ready {
		run.ReadyAfter = append(run.ReadyAfter, findings.StepReadyAfter{Node: r.Node, ReadyAfterS: r.ReadyAfterS})
	}
	block.StepRunBlock = run
	// The wait, once the run closed: how it ended, or no key when it did not run; its last
	// read's counts beside it, or no key when it made none.
	block.Wait = nil
	if w := res.Wait; w != nil {
		block.Wait = &findings.StepWaitBlock{BudgetS: w.BudgetS, Outcome: w.Outcome, Reads: w.Reads, AfterS: w.AfterS,
			Failing: make([]findings.StepWaitFailing, len(w.Failing))}
		for i, f := range w.Failing {
			block.Wait.Failing[i] = findings.StepWaitFailing{Rule: f.Rule, Object: f.Object, Message: f.Message}
		}
		block.WaitCounts = res.WaitCounts
	}
	// The flows' loss once ReadFlows read it (016), null when the run closed without it.
	block.Loss = LossBlockOf(res.Loss)
	doc.Step = block
	return doc
}

// LossBlockOf is a step's loss as the step document's block carries it
// (contracts/step.schema.json, $defs/loss), or nil for none.
func LossBlockOf(l *wire.Loss) *findings.StepLoss {
	if l == nil {
		return nil
	}
	b := &findings.StepLoss{Basis: l.Basis, Probes: make([]findings.StepProbeLoss, len(l.Probes)),
		Added: append([]string{}, l.Added...), Dropped: append([]string{}, l.Dropped...)}
	for i, p := range l.Probes {
		b.Probes[i] = findings.StepProbeLoss{Probe: p.Probe, From: p.From, To: p.To, Outcome: p.Outcome, Sent: p.Sent,
			Lost: p.Lost, LongestGapS: p.LongestGapS, Rule: p.Rule, Message: p.Message}
	}
	return b
}

// StepBlockOf is the step block of twin.step's document before any run: the two
// sides, M10's step between their bundles, containerlab's plan with each touched node's
// package declaration beside what containerlab reports, the push plan and the flag. The dry
// run carries it as it is; StepDocument adds the run's fields.
func StepBlockOf(in StepInput, plan wire.ReconcilePlan) *findings.StepBlock {
	side := func(s wire.StepSide) findings.StepSideBlock {
		return findings.StepSideBlock{SnapshotID: s.SnapshotID, BundleID: s.BundleID, At: s.At, Branch: s.Branch}
	}
	list := func(l []string) []string { return append([]string{}, l...) }
	block := &findings.StepBlock{
		From: side(in.From),
		To:   side(in.To),
		Diff: in.Diff,
		Reconcile: findings.StepReconcileBlock{
			Added: list(plan.Added), Deleted: list(plan.Deleted), Recreated: list(plan.Recreated), Restarted: list(plan.Restarted),
			LinksAdded: list(plan.LinksAdded), EndpointsDeleted: list(plan.EndpointsDeleted), Nodes: []findings.StepPlanNode{},
		},
		PushPlan:     make([]findings.StepPushPlanEntry, len(in.PushPlan)),
		AllowRestart: in.AllowRestart,
		// The wait's budget, as the dry run reports it.
		Wait: &findings.StepWaitBlock{BudgetS: in.WaitS},
	}
	block.From.Branch = "" // the from side names no branch (step.schema.json)
	for _, n := range plan.Nodes() {
		node := findings.StepPlanNode{Node: n.Node, Reported: n.Reported, Reason: n.Reason}
		// A created node has no declaration: no link change of its is at stake.
		if d, ok := in.Declared[n.Node]; ok && d != "" && n.Reported != wire.ReportedCreate {
			node.Declared = &d
		}
		block.Reconcile.Nodes = append(block.Reconcile.Nodes, node)
	}
	for i, p := range in.PushPlan {
		block.PushPlan[i] = findings.StepPushPlanEntry{Node: p.Node, Reasons: p.Reasons}
	}
	return block
}

// stepStatus is a step run's status, from its outcome.
func stepStatus(res StepResult) findings.Status {
	switch {
	case res.Outcome == StepStepped || res.Outcome == StepUnchanged:
		return findings.StatusOK
	case res.Outcome == OutcomeRejected:
		return findings.StatusRejected
	case res.Outcome == StepDiverged, res.Phase != "":
		return findings.StatusDiverged
	}
	return findings.StatusError
}
