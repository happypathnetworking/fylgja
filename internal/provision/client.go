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
	workflowpb "go.temporal.io/api/workflow/v1"
	"go.temporal.io/api/workflowservice/v1"
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
	// closed. A rehearsal in flight is cancelled and followed to its end first, its own
	// destroy included (015); then a provisioning run in flight is cancelled and waited for,
	// and a step run in flight; a destroy run in flight is attached to rather than doubled.
	// It stops nothing else: nothing follows a branch (019). onEvent receives every run's
	// progress, and a Notice for each thing done to a run rather than by a step. No worker
	// to take the run is a *StartError carrying run.worker.absent.
	StartDestroy(ctx context.Context, onEvent func(Event)) (DestroyRun, error)
	// StartReclaim destroys the twin a rehearsal no longer running left, as StartDestroy
	// does, but cancels nothing (015, FR-007): a rehearsal, provisioning or step run in
	// flight is a *StartError carrying run.in_flight, naming the run, with nothing
	// cancelled or started. A destroy run in flight is attached to.
	StartReclaim(ctx context.Context, onEvent func(Event)) (DestroyRun, error)
	// Following describes Schedule fylgja-follow, or returns nil when there is none. twin
	// show's reads (Following, LastCheck, InFlight) change nothing and need no worker; a
	// service that does not answer them is an *UnreachableError.
	Following(ctx context.Context) (*FollowingState, error)
	// LastCheck is the newest closed check: of schedule's recent actions when a Schedule
	// exists, and otherwise the newest the service lists, unless a provisioning or destroy
	// run has started since it closed. nil when there is none.
	LastCheck(ctx context.Context, schedule *FollowingState) (*CheckRecord, error)
	// InFlight names the rehearsal, the provisioning run, the destroy run, the step run and
	// the check in flight, each with the step its history has reached; a rehearsal's or a
	// check's child run is its Child, named once, and a step run, as either kind of run or as
	// a rehearsal's child, names the stage it steps towards.
	InFlight(ctx context.Context) ([]RunInFlight, error)
	// StartStep starts the one step run and returns its run id once a worker has taken it
	// (M11). A rehearsal, provisioning, destroy or step run in
	// flight is a *StartError carrying run.in_flight, naming the run; no worker to take it is
	// one carrying run.worker.absent, with nothing left running.
	StartStep(ctx context.Context, in StepInput) (runID string, err error)
	// ResultOfStep waits for the step run to close and returns how it ended.
	ResultOfStep(ctx context.Context, runID string) (StepResult, error)
	// StartRehearse starts the one rehearsal run and returns its run id once a worker has
	// taken it (015, D-051). A provisioning, destroy, step or rehearsal run in flight is a
	// *StartError carrying run.in_flight, naming the run; no worker to take it is one
	// carrying run.worker.absent, with nothing left running.
	StartRehearse(ctx context.Context, in RehearseInput) (runID string, err error)
	// ResultOfRehearse waits for the rehearsal run to close and returns how it ended.
	ResultOfRehearse(ctx context.Context, runID string) (RehearseResult, error)
	Close()
}

// ScheduledCheck is one check the Schedule started: its identity and when it was due.
type ScheduledCheck struct {
	WorkflowID  string
	RunID       string
	ScheduledAt time.Time
}

// FollowingState is Schedule fylgja-follow as twin show reads it.
type FollowingState struct {
	Branch        string
	IntervalS     int
	NextCheckAt   time.Time        // zero when the service names no next check
	RecentActions []ScheduledCheck // the checks it started recently, newest last
	Running       []ScheduledCheck // the check it started that is still running
}

// CheckRecord is one closed check and its result.
type CheckRecord struct {
	WorkflowID  string
	RunID       string
	ScheduledAt time.Time
	ClosedAt    time.Time
	Result      ReconcileResult
}

// RunInFlight is a run that has not closed, and the step its history has reached, as
// findings name steps. A check's child run in flight is its Child.
type RunInFlight struct {
	WorkflowID string
	RunID      string
	Step       string
	Child      *RunInFlight
	// Towards is the stage a fylgja-step run is stepping towards, <branch>/<label>, from
	// its input, and, for a rehearsal's provisioning child, the baseline it builds (015); ""
	// for every other run.
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

// rehearseStartOptions start the one rehearsal run (015).
// WorkflowExecutionErrorWhenAlreadyStarted makes a second rehearsal refuse rather than
// attach to the first and report that run's result as its own, as provisionStartOptions
// does for a create. Its absence is silent, which is why a test pins it.
func rehearseStartOptions() client.StartWorkflowOptions {
	return client.StartWorkflowOptions{
		ID:                                       WorkflowRehearse,
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
	// A step run holds the twin a create would refuse beside, and a rehearsal holds the host
	// for its own twin (015), so either is refused here, naming the run, before any run
	// starts, rather than started and rejected at its host check by host.lab.present. The
	// rehearsal is asked first: the step may be its child.
	for _, workflowID := range []string{WorkflowRehearse, WorkflowStep} {
		runID, err := c.runningRun(ctx, workflowID)
		if err != nil {
			return "", err
		}
		if runID != "" {
			return "", InFlightRefusal(workflowID, runID)
		}
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
	case WorkflowRehearse:
		message = fmt.Sprintf("rehearsal run %s is already in flight; wait for it to finish, or run fylgja twin destroy to cancel it", runID)
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

// StartStep implements Service, in StartProvision's shape. A rehearsal, provisioning or
// destroy run in flight refuses it first, naming the run: a step beside a provisioning or
// destroy run would act on a twin that run is building or removing, and a rehearsal's twin
// is its own (015). A step run
// in flight refuses it through the fixed id, as a second create is refused. Nothing is
// started while no worker polls the queue, and a run no worker takes within the first-task
// guard is terminated before anything in it ran.
func (c *Client) StartStep(ctx context.Context, in StepInput) (string, error) {
	if err := c.requireWorker(ctx); err != nil {
		return "", err
	}
	for _, workflowID := range []string{WorkflowRehearse, WorkflowProvision, WorkflowDestroy} {
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

// StartRehearse implements Service, in StartStep's shape (015, research R-12). A
// provisioning, destroy or step run in flight refuses it first, naming the run: the
// rehearsal's own children would be refused beside each, and the server refused already
// when it saw one (contracts/rehearse-command.md, step 4), so one here began since. A
// rehearsal in flight refuses it through the fixed id, as a second step is refused. Nothing
// is started while no worker polls the queue, and a run no worker takes within the
// first-task guard is terminated before anything in it ran.
func (c *Client) StartRehearse(ctx context.Context, in RehearseInput) (string, error) {
	if err := c.requireWorker(ctx); err != nil {
		return "", err
	}
	for _, workflowID := range []string{WorkflowProvision, WorkflowDestroy, WorkflowStep} {
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
	run, err := c.ExecuteWorkflow(send, rehearseStartOptions(), Rehearse, in)
	cancelSend()
	var started *serviceerror.WorkflowExecutionAlreadyStarted
	if errors.As(err, &started) {
		return "", InFlightRefusal(WorkflowRehearse, started.RunId)
	}
	if err != nil {
		return "", fmt.Errorf("starting %s: %w", WorkflowRehearse, err)
	}
	if err := c.awaitFirstTask(ctx, WorkflowRehearse, run.GetRunID()); err != nil {
		return "", err
	}
	return run.GetRunID(), nil
}

// ResultOfRehearse implements Service.
func (c *Client) ResultOfRehearse(ctx context.Context, runID string) (RehearseResult, error) {
	var res RehearseResult
	err := c.GetWorkflow(ctx, WorkflowRehearse, runID).Get(ctx, &res)
	return res, err
}

// StartDestroy implements Service.
//
// A rehearsal in flight is cancelled and followed to its end first, its children's progress
// included: its step records diverged, its provision cleans up, and its own destroy runs
// last whatever it was asked, so what it leaves is what that destroy left (015, research
// R-12). A provisioning run in flight is cancelled and waited for next: its own cleanup removes
// what it made, and the destroy run follows so that nothing it missed remains. A step run in
// flight is cancelled and waited for next, until its record is
// written. No signal: cancellation is the service's own request. Whether a destroy run was
// already in flight is asked before starting, so the attach can be reported. Nothing is cancelled or started while no worker polls the queue, and a
// destroy run no worker takes within the first-task guard is terminated.
func (c *Client) StartDestroy(ctx context.Context, onEvent func(Event)) (DestroyRun, error) {
	if onEvent == nil {
		onEvent = func(Event) {}
	}
	notice := func(format string, args ...any) { onEvent(Event{Notice: fmt.Sprintf(format, args...)}) }

	if err := c.requireWorker(ctx); err != nil {
		return DestroyRun{}, err
	}

	rehearsing, err := c.runningRun(ctx, WorkflowRehearse)
	if err != nil {
		return DestroyRun{}, err
	}
	if rehearsing != "" {
		notice("cancelling rehearsal run %s; waiting for its destroy", rehearsing)
		if err := c.CancelWorkflow(ctx, WorkflowRehearse, rehearsing); err != nil {
			return DestroyRun{}, fmt.Errorf("cancelling rehearsal run %s: %w", rehearsing, err)
		}
		// Progress is best effort; the close is what destroy waits for.
		_ = c.Follow(ctx, WorkflowRehearse, rehearsing, onEvent)
		var res RehearseResult
		err := c.GetWorkflow(ctx, WorkflowRehearse, rehearsing).Get(ctx, &res)
		var closedWithout *temporal.WorkflowExecutionError
		switch {
		case errors.As(err, &closedWithout):
			notice("rehearsal run %s closed without a result: %v", rehearsing, err)
		case err != nil:
			return DestroyRun{}, fmt.Errorf("waiting for rehearsal run %s to close: %w", rehearsing, err)
		default:
			notice("rehearsal run %s closed: %s", rehearsing, res.Outcome)
		}
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

	return c.destroy(ctx, onEvent)
}

// StartReclaim implements Service.
//
// The rehearsal is asked first, as StartProvision asks it: the provisioning or step run in
// flight may be its child. Whatever is found is refused, never cancelled, so a run that
// started after the rehearsal's own read of the runs in flight is left to run: an
// operator's twin step on a dead rehearsal's twin, or a second check's rehearsal on the twin
// both found dead.
func (c *Client) StartReclaim(ctx context.Context, onEvent func(Event)) (DestroyRun, error) {
	if onEvent == nil {
		onEvent = func(Event) {}
	}
	if err := c.requireWorker(ctx); err != nil {
		return DestroyRun{}, err
	}
	for _, workflowID := range []string{WorkflowRehearse, WorkflowProvision, WorkflowStep} {
		runID, err := c.runningRun(ctx, workflowID)
		if err != nil {
			return DestroyRun{}, err
		}
		if runID != "" {
			return DestroyRun{}, InFlightRefusal(workflowID, runID)
		}
	}
	return c.destroy(ctx, onEvent)
}

// destroy is StartDestroy and StartReclaim once no rehearsal, provisioning or step run is in
// flight: the destroy run started, or attached to, and followed to its close.
func (c *Client) destroy(ctx context.Context, onEvent func(Event)) (DestroyRun, error) {
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
	_ = c.Follow(ctx, WorkflowDestroy, out.RunID, onEvent)
	if err := run.Get(ctx, &out.Result); err != nil {
		return DestroyRun{}, fmt.Errorf("waiting for destroy run %s: %w", out.RunID, err)
	}
	return out, nil
}

// reconcileWorkflowType is the name an earlier build's worker registered a check's
// workflow under, which its Schedule's action started by. This build registers none, and
// reads it to find a check an earlier build left (019).
const reconcileWorkflowType = "Reconcile"

// followedBranch is the branch a Schedule's action checks, decoded from the action's first
// arg, which Describe returns as a payload. "" when it cannot be
// read.
func followedBranch(desc *client.ScheduleDescription) string {
	action, ok := desc.Schedule.Action.(*client.ScheduleWorkflowAction)
	if !ok || len(action.Args) == 0 {
		return ""
	}
	var in ReconcileInput
	switch arg := action.Args[0].(type) {
	case *commonpb.Payload:
		if converter.GetDefaultDataConverter().FromPayload(arg, &in) != nil {
			return ""
		}
	case ReconcileInput:
		in = arg
	}
	return in.Branch
}

// runningChecksQuery finds a check in flight. No ORDER BY: the dev server's visibility
// store refuses it.
const runningChecksQuery = "WorkflowType = '" + reconcileWorkflowType + "' AND ExecutionStatus = 'Running'"

// unreachable reports a read twin show made that the service did not answer. Whatever the
// cause, twin show can say only that following and runs in flight are unknown.
func (c *Client) unreachable(err error) error {
	var already *UnreachableError
	if errors.As(err, &already) {
		return err
	}
	return &UnreachableError{Address: c.Address, Err: err}
}

// Following implements Service.
func (c *Client) Following(ctx context.Context) (*FollowingState, error) {
	desc, err := c.ScheduleClient().GetHandle(ctx, FollowScheduleID).Describe(ctx)
	var notFound *serviceerror.NotFound
	if errors.As(err, &notFound) {
		return nil, nil
	}
	if err != nil {
		return nil, c.unreachable(err)
	}
	st := &FollowingState{Branch: followedBranch(desc)}
	if spec := desc.Schedule.Spec; spec != nil && len(spec.Intervals) > 0 {
		st.IntervalS = int(spec.Intervals[0].Every / time.Second)
	}
	if next := desc.Info.NextActionTimes; len(next) > 0 {
		st.NextCheckAt = next[0].UTC()
	}
	scheduledAt := map[string]time.Time{}
	for _, a := range desc.Info.RecentActions {
		if w := a.StartWorkflowResult; w != nil {
			st.RecentActions = append(st.RecentActions, ScheduledCheck{WorkflowID: w.WorkflowID, RunID: w.FirstExecutionRunID,
				ScheduledAt: a.ScheduleTime.UTC()})
			scheduledAt[w.WorkflowID] = a.ScheduleTime.UTC()
		}
	}
	for _, w := range desc.Info.RunningWorkflows {
		st.Running = append(st.Running, ScheduledCheck{WorkflowID: w.WorkflowID, RunID: w.FirstExecutionRunID,
			ScheduledAt: scheduledAt[w.WorkflowID]})
	}
	return st, nil
}

// allChecksQuery lists every check the service still holds. No ORDER BY: the dev server's
// visibility store refuses it, so the newest is chosen here.
const allChecksQuery = "WorkflowType = '" + reconcileWorkflowType + "'"

// LastCheck implements Service. A check still running is not the last check: its result is
// not known, and InFlight names it.
func (c *Client) LastCheck(ctx context.Context, schedule *FollowingState) (*CheckRecord, error) {
	if schedule != nil {
		running := map[string]bool{}
		for _, r := range schedule.Running {
			running[r.WorkflowID] = true
		}
		for i := len(schedule.RecentActions) - 1; i >= 0; i-- {
			a := schedule.RecentActions[i]
			if running[a.WorkflowID] {
				continue
			}
			rec, err := c.closedCheck(ctx, a.WorkflowID, a.RunID, a.ScheduledAt)
			if err != nil || rec != nil {
				return rec, err
			}
		}
		return nil, nil
	}

	resp, err := c.ListWorkflow(ctx, &workflowservice.ListWorkflowExecutionsRequest{Namespace: c.Namespace, Query: allChecksQuery})
	if err != nil {
		return nil, c.unreachable(err)
	}
	var newest *workflowpb.WorkflowExecutionInfo
	for _, info := range resp.GetExecutions() {
		if newest == nil || info.GetStartTime().AsTime().After(newest.GetStartTime().AsTime()) {
			newest = info
		}
	}
	if newest == nil || newest.GetStatus() == enumspb.WORKFLOW_EXECUTION_STATUS_RUNNING {
		return nil, nil
	}
	id := newest.GetExecution().GetWorkflowId()
	rec, err := c.closedCheck(ctx, id, newest.GetExecution().GetRunId(), checkScheduledAt(id, newest.GetStartTime().AsTime()))
	if err != nil || rec == nil {
		return nil, err
	}
	// A provisioning or destroy run started after the check closed supersedes it: the failed
	// rebuild is history, and the host is reported as it is. The rebuild's own
	// children started before the check closed.
	for _, workflowID := range []string{WorkflowProvision, WorkflowDestroy} {
		desc, err := c.DescribeWorkflowExecution(ctx, workflowID, "")
		var notFound *serviceerror.NotFound
		if errors.As(err, &notFound) {
			continue
		}
		if err != nil {
			return nil, c.unreachable(err)
		}
		if desc.GetWorkflowExecutionInfo().GetStartTime().AsTime().After(rec.ClosedAt) {
			return nil, nil
		}
	}
	return rec, nil
}

// closedCheck is the check's record when it has closed with a result, and nil when it is
// still running or closed without one (terminated, timed out).
func (c *Client) closedCheck(ctx context.Context, workflowID, runID string, scheduledAt time.Time) (*CheckRecord, error) {
	desc, err := c.DescribeWorkflowExecution(ctx, workflowID, runID)
	if err != nil {
		return nil, c.unreachable(err)
	}
	info := desc.GetWorkflowExecutionInfo()
	if info.GetStatus() == enumspb.WORKFLOW_EXECUTION_STATUS_RUNNING {
		return nil, nil
	}
	rec := &CheckRecord{WorkflowID: workflowID, RunID: runID, ScheduledAt: scheduledAt, ClosedAt: info.GetCloseTime().AsTime().UTC()}
	err = c.GetWorkflow(ctx, workflowID, runID).Get(ctx, &rec.Result)
	var closedWithout *temporal.WorkflowExecutionError
	if errors.As(err, &closedWithout) {
		return nil, nil
	}
	if err != nil {
		return nil, c.unreachable(err)
	}
	return rec, nil
}

// checkScheduledAt is when a check was due: the time the service appended to its
// id,
// or its start when the id carries none.
func checkScheduledAt(workflowID string, started time.Time) time.Time {
	if at, err := time.Parse(time.RFC3339, strings.TrimPrefix(workflowID, WorkflowReconcile+"-")); err == nil {
		return at.UTC()
	}
	return started.UTC()
}

// InFlight implements Service. A rebuild's provision or destroy is named once, as the
// check's child, not again as an operator's run, and a rehearsal's child likewise, as the
// rehearsal's (015). A step run is named with its target, and a rehearsal's provisioning
// child with the baseline it builds.
func (c *Client) InFlight(ctx context.Context) ([]RunInFlight, error) {
	resp, err := c.ListWorkflow(ctx, &workflowservice.ListWorkflowExecutionsRequest{Namespace: c.Namespace, Query: runningChecksQuery})
	if err != nil {
		return nil, c.unreachable(err)
	}
	var checks []RunInFlight
	children := map[string]bool{}
	for _, info := range resp.GetExecutions() {
		run := RunInFlight{WorkflowID: info.GetExecution().GetWorkflowId(), RunID: info.GetExecution().GetRunId()}
		var child *commonpb.WorkflowExecution
		if run.Step, child, err = c.historyStep(ctx, run.WorkflowID, run.RunID); err != nil {
			return nil, err
		}
		if child != nil {
			run.Child = &RunInFlight{WorkflowID: child.GetWorkflowId(), RunID: child.GetRunId()}
			if run.Child.Step, _, err = c.historyStep(ctx, run.Child.WorkflowID, run.Child.RunID); err != nil {
				return nil, err
			}
			children[run.Child.WorkflowID+"/"+run.Child.RunID] = true
		}
		checks = append(checks, run)
	}

	var runs []RunInFlight
	rehearsing, err := c.runningRun(ctx, WorkflowRehearse)
	if err != nil {
		return nil, c.unreachable(err)
	}
	if rehearsing != "" {
		run := RunInFlight{WorkflowID: WorkflowRehearse, RunID: rehearsing}
		var child *commonpb.WorkflowExecution
		if run.Step, child, err = c.historyStep(ctx, WorkflowRehearse, rehearsing); err != nil {
			return nil, err
		}
		if child != nil {
			run.Child = &RunInFlight{WorkflowID: child.GetWorkflowId(), RunID: child.GetRunId()}
			if run.Child.Step, _, err = c.historyStep(ctx, run.Child.WorkflowID, run.Child.RunID); err != nil {
				return nil, err
			}
			if run.Child.Towards, err = c.towards(ctx, run.Child.WorkflowID, run.Child.RunID); err != nil {
				return nil, err
			}
			children[run.Child.WorkflowID+"/"+run.Child.RunID] = true
		}
		runs = append(runs, run)
	}
	for _, workflowID := range []string{WorkflowProvision, WorkflowDestroy, WorkflowStep} {
		runID, err := c.runningRun(ctx, workflowID)
		if err != nil {
			return nil, c.unreachable(err)
		}
		if runID == "" || children[workflowID+"/"+runID] {
			continue
		}
		run := RunInFlight{WorkflowID: workflowID, RunID: runID}
		if run.Step, _, err = c.historyStep(ctx, workflowID, runID); err != nil {
			return nil, err
		}
		if workflowID == WorkflowStep {
			if run.Towards, err = c.towards(ctx, WorkflowStep, runID); err != nil {
				return nil, err
			}
		}
		runs = append(runs, run)
	}
	return append(runs, checks...), nil
}

// towards is the stage a run's input names, <branch>/<label>, read from the input its
// history starts with: the stage a step run steps towards, or the one a provisioning run
// builds (a rehearsal's baseline, 015). "" when that input names none, and for any other
// run.
func (c *Client) towards(ctx context.Context, workflowID, runID string) (string, error) {
	if workflowID != WorkflowStep && workflowID != WorkflowProvision {
		return "", nil
	}
	iter := c.GetWorkflowHistory(ctx, workflowID, runID, false, enumspb.HISTORY_EVENT_FILTER_TYPE_ALL_EVENT)
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
	dc := converter.GetDefaultDataConverter()
	var stage *wire.StageRef
	if workflowID == WorkflowStep {
		var in StepInput
		if dc.FromPayloads(attrs.GetInput(), &in) == nil {
			stage = in.To.Stage
		}
	} else {
		var in ProvisionInput
		if dc.FromPayloads(attrs.GetInput(), &in) == nil {
			stage = in.Stage
		}
	}
	if stage == nil {
		return "", nil
	}
	return stage.Name(), nil
}

// historyStep reads a run's history once, without waiting for more, and returns the step
// it has reached: the last activity or child scheduled and not closed, or else the last
// scheduled, or start when nothing has been. When that step is a child that has started,
// the child is returned too.
func (c *Client) historyStep(ctx context.Context, workflowID, runID string) (string, *commonpb.WorkflowExecution, error) {
	var order []int64
	scheduled := map[int64]string{}
	open := map[int64]bool{}
	started := map[int64]*commonpb.WorkflowExecution{}
	closeEvent := func(id int64) { delete(open, id) }

	iter := c.GetWorkflowHistory(ctx, workflowID, runID, false, enumspb.HISTORY_EVENT_FILTER_TYPE_ALL_EVENT)
	for iter.HasNext() {
		ev, err := iter.Next()
		if err != nil {
			return "", nil, c.unreachable(err)
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
		case enumspb.EVENT_TYPE_START_CHILD_WORKFLOW_EXECUTION_INITIATED:
			order = append(order, ev.GetEventId())
			scheduled[ev.GetEventId()] = ev.GetStartChildWorkflowExecutionInitiatedEventAttributes().GetWorkflowType().GetName()
			open[ev.GetEventId()] = true
		case enumspb.EVENT_TYPE_START_CHILD_WORKFLOW_EXECUTION_FAILED:
			closeEvent(ev.GetStartChildWorkflowExecutionFailedEventAttributes().GetInitiatedEventId())
		case enumspb.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_STARTED:
			a := ev.GetChildWorkflowExecutionStartedEventAttributes()
			started[a.GetInitiatedEventId()] = a.GetWorkflowExecution()
		case enumspb.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_COMPLETED:
			closeEvent(ev.GetChildWorkflowExecutionCompletedEventAttributes().GetInitiatedEventId())
		case enumspb.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_FAILED:
			closeEvent(ev.GetChildWorkflowExecutionFailedEventAttributes().GetInitiatedEventId())
		case enumspb.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_CANCELED:
			closeEvent(ev.GetChildWorkflowExecutionCanceledEventAttributes().GetInitiatedEventId())
		case enumspb.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_TERMINATED:
			closeEvent(ev.GetChildWorkflowExecutionTerminatedEventAttributes().GetInitiatedEventId())
		case enumspb.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_TIMED_OUT:
			closeEvent(ev.GetChildWorkflowExecutionTimedOutEventAttributes().GetInitiatedEventId())
		}
	}
	if len(order) == 0 {
		return findings.StepStart, nil, nil
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
	var child *commonpb.WorkflowExecution
	if open[reached] {
		child = started[reached]
	}
	return step, child, nil
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
	// Of is the run whose child this event's run is, when it was followed as one: a check's
	// rebuild, or a rehearsal's provision, step and destroy (015), so a destroy that follows a
	// rehearsal's own destroy first tells it from its own. "" for a run followed on its own.
	Of string
}

// isCheck reports whether workflowID is a check: the workflow service appends the scheduled
// time to the action id.
func isCheck(workflowID string) bool {
	return strings.HasPrefix(workflowID, WorkflowReconcile+"-")
}

// Workflow type names, as a check's or a rehearsal's history names its children.
const (
	destroyWorkflowType   = "Destroy"
	provisionWorkflowType = "Provision"
	stepWorkflowType      = "Step"
)

// findingStep is the step, as findings name it, an activity or a check's child belongs to.
// PlanTeardown budgets the teardown, so it is part of it; a check's two inspections are its
// inspect step.
func findingStep(activityType string) string {
	switch activityType {
	case wire.ActInspectTwin:
		return findings.StepInspect
	case destroyWorkflowType:
		return findings.StepDestroy
	case provisionWorkflowType:
		return findings.StepProvision
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
	}
	return ""
}

// Follow implements Service over the run's event history, long-polled, so progress needs
// no query handler, signal or change to workflow code (D-007).
func (c *Client) Follow(ctx context.Context, workflowID, runID string, onEvent func(Event)) error {
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

	iter := c.GetWorkflowHistory(ctx, workflowID, runID, true, enumspb.HISTORY_EVENT_FILTER_TYPE_ALL_EVENT)
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

		// A check's children: its rebuild's destroy and provision. Each is a step of the check,
		// and its own steps are followed where it starts, so a destroy that cancels a check
		// shows the child's cleanup too.
		case enumspb.EVENT_TYPE_START_CHILD_WORKFLOW_EXECUTION_INITIATED:
			a := ev.GetStartChildWorkflowExecutionInitiatedEventAttributes()
			name := a.GetWorkflowType().GetName()
			step := stepName(workflowID, name)
			open[ev.GetEventId()] = scheduled{activityType: name, step: step, at: at}
			emit(name, Event{Step: step})
		case enumspb.EVENT_TYPE_START_CHILD_WORKFLOW_EXECUTION_FAILED:
			a := ev.GetStartChildWorkflowExecutionFailedEventAttributes()
			s, d := ended(a.GetInitiatedEventId(), at)
			emit(s.activityType, Event{Step: s.step, End: true, Outcome: EventFailed, Duration: d,
				Message: fmt.Sprintf("run %s is already in flight", a.GetWorkflowId())})
		case enumspb.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_STARTED:
			child := ev.GetChildWorkflowExecutionStartedEventAttributes().GetWorkflowExecution()
			onEvent(Event{Notice: fmt.Sprintf("run %s %s", child.GetWorkflowId(), child.GetRunId())})
			_ = c.Follow(ctx, child.GetWorkflowId(), child.GetRunId(), childEvents(workflowID, onEvent))
		case enumspb.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_COMPLETED:
			s, d := ended(ev.GetChildWorkflowExecutionCompletedEventAttributes().GetInitiatedEventId(), at)
			emit(s.activityType, Event{Step: s.step, End: true, Outcome: EventDone, Duration: d})
		case enumspb.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_FAILED:
			a := ev.GetChildWorkflowExecutionFailedEventAttributes()
			s, d := ended(a.GetInitiatedEventId(), at)
			emit(s.activityType, Event{Step: s.step, End: true, Outcome: EventFailed, Duration: d, Message: a.GetFailure().GetMessage()})
		case enumspb.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_TERMINATED:
			s, d := ended(ev.GetChildWorkflowExecutionTerminatedEventAttributes().GetInitiatedEventId(), at)
			emit(s.activityType, Event{Step: s.step, End: true, Outcome: EventFailed, Duration: d, Message: "terminated"})
		case enumspb.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_TIMED_OUT:
			s, d := ended(ev.GetChildWorkflowExecutionTimedOutEventAttributes().GetInitiatedEventId(), at)
			emit(s.activityType, Event{Step: s.step, End: true, Outcome: EventTimedOut, Duration: d})
		case enumspb.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_CANCELED:
			s, d := ended(ev.GetChildWorkflowExecutionCanceledEventAttributes().GetInitiatedEventId(), at)
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

// childEvents passes a child run's events on as those of parent's child: each names parent
// as the run it is Of, unless a run nearer it already does.
func childEvents(parent string, onEvent func(Event)) func(Event) {
	return func(e Event) {
		if e.Of == "" {
			e.Of = parent
		}
		onEvent(e)
	}
}

// stepName is the step an activity performs, named as contracts/cli.md names it. Teardown and
// unstage are a provisioning run's cleanup, and the whole of a destroy run. A check names
// its two inspections, its stop and its children as its own steps (contracts/cli.md,
// Progress lines), a step run its inspection and its four activities (M11), and a rehearsal
// its three kinds of child (015: "at step step" while a step child runs).
func stepName(workflowID, activityType string) string {
	if workflowID == WorkflowRehearse {
		switch activityType {
		case provisionWorkflowType:
			return "provision"
		case stepWorkflowType:
			return "step"
		case destroyWorkflowType:
			return "destroy"
		}
	}
	if isCheck(workflowID) {
		switch activityType {
		case wire.ActInspectTwin:
			return "inspect"
		case destroyWorkflowType:
			return "destroy"
		case provisionWorkflowType:
			return "provision"
		}
	}
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
	}
	return ""
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
// attempted written skipped: a destroy's, and a rehearsal's reclaim and its destroy (015).
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
	doc.Step = block
	return doc
}

// StepBlockOf is the step block of twin.step's document before any run: the two
// sides, M10's step between their bundles, containerlab's plan with each touched node's
// package declaration beside what containerlab reports, the push plan and the flag. The dry
// run carries it as it is; StepDocument adds the run's fields.
func StepBlockOf(in StepInput, plan wire.ReconcilePlan) *findings.StepBlock {
	side := func(s wire.StepSide) findings.StepSideBlock {
		b := findings.StepSideBlock{SnapshotID: s.SnapshotID, BundleID: s.BundleID, At: s.At, Branch: s.Branch}
		if st := s.Stage; st != nil {
			b.Stage = &findings.ShowStage{ProposedChange: findings.StageChangeRef{ID: st.ProposedChange.ID,
				Branch: st.ProposedChange.Branch}, Label: st.Label, Description: st.Description, AtSource: st.AtSource}
		}
		return b
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
