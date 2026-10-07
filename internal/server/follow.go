package server

import (
	"context"
	"fmt"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
)

// runProvision starts the provisioning run in, follows it until it closes and reports how
// it ended: everything twin create and twin provision do after their own checks, in one
// place, so the two start, print and exit alike.
//
// Interrupts are listened for from before the start, not only once the run is followed: a
// start can wait for the first-task guard, and an interrupt then must still stop the run
// rather than end the command and leave the run for a worker to take later.
// They are the operator's, delivered to this request from its start frame on.
func runProvision(ctx context.Context, opts *options, op string, subject *findings.Subject, in provision.ProvisionInput) error {
	svc, err := opts.dial(ctx)
	if err != nil {
		return startFailure(op, subject, findings.StepStart, err)
	}
	defer svc.Close()
	// Every run the CLI starts stops any following once its host check has passed, so a
	// twin it builds never inherits another's.
	in.StopFollowing = true

	interrupts, err := opts.c.startFrame(provision.WorkflowProvision)
	if err != nil {
		return goneBeforeStart(op, subject, provision.WorkflowProvision, err)
	}

	runID, interrupted, err := startRun(ctx, provision.WorkflowProvision,
		func(ctx context.Context) (string, error) { return svc.StartProvision(ctx, in) }, interrupts)
	if err != nil {
		return startFailure(op, subject, findings.StepStart, err)
	}
	subject.RunID = runID
	opts.c.runFrame(provision.WorkflowProvision, runID)

	res, err := followRun(ctx, opts, svc, op, subject, provision.WorkflowProvision, runID, interrupts, interrupted,
		func(ctx context.Context) (provision.ProvisionResult, error) {
			return svc.Result(ctx, provision.WorkflowProvision, runID)
		}, "run cancelled; cleanup running")
	if err != nil {
		return err
	}
	return provisionReport(opts, op, subject, in, res)
}

// startRun starts workflowID's run through start and answers an interrupt that arrives
// before the start has returned by abandoning the start. The client then terminates a run it
// had already started, which no worker has taken, so nothing in it runs (run.cancelled); a
// start abandoned before any run existed started nothing. An interrupt that arrives just as a
// start succeeds is reported as interrupted, so the follow takes it as the first interrupt and
// cancels the run. A provisioning run and a step run (M11) start alike.
//
// Only the interrupt abandons a start. It runs on a context the request's end does not reach,
// so a client that goes away, or a server that stops, while the start waits for a worker
// leaves the run for that worker, as M12's killed process left it; the run is then followed,
// if at all, on the request's context.
func startRun(ctx context.Context, workflowID string, start func(context.Context) (string, error),
	interrupts <-chan os.Signal) (runID string, interrupted bool, err error) {
	startCtx, abandon := context.WithCancel(context.WithoutCancel(ctx))
	defer abandon()
	type started struct {
		runID string
		err   error
	}
	done := make(chan started, 1)
	go func() {
		id, err := start(startCtx)
		done <- started{runID: id, err: err}
	}()

	select {
	case s := <-done:
		return s.runID, false, s.err
	case <-interrupts:
		abandon()
		s := <-done
		if s.err == nil {
			return s.runID, true, nil
		}
		if _, refused := provision.AsStartError(s.err); refused {
			return "", false, s.err
		}
		return "", false, &provision.StartError{Status: findings.StatusError, Finding: findings.Finding{
			Severity: findings.Rejection,
			Rule:     findings.RuleRunCancelled,
			Object:   workflowID,
			Step:     findings.StepStart,
			Message:  fmt.Sprintf("interrupted before the %s was started, so nothing was started (%v)", runNoun(workflowID), s.err),
		}}
	}
}

// goneBeforeStart is what a run's request returns when its client went before the server
// began to start the run: nothing was started, and no client reads the document, which the
// answer then never writes.
func goneBeforeStart(op string, subject *findings.Subject, workflowID string, err error) error {
	return failAt(op, subject, findings.StepStart, workflowID,
		"the client went before the %s was started, so nothing was started (%v)", runNoun(workflowID), err)
}

// runNoun names a run as the CLI's sentences do.
func runNoun(workflowID string) string {
	switch workflowID {
	case provision.WorkflowStep:
		return "step run"
	case provision.WorkflowDestroy:
		return "destroy run"
	}
	return "provisioning run"
}

// startFailure reports why a run was not started, or not seen through: under its own
// identifier when the workflow service refused it or could not be reached — run.in_flight,
// run.worker.absent, run.service.unreachable, run.cancelled — and otherwise as the operation
// failing at step, the step the command had followed the run to (contracts/cli.md).
func startFailure(op string, subject *findings.Subject, step string, err error) error {
	if refused, ok := provision.AsStartError(err); ok {
		return &result{doc: refused.Document(op, subject)}
	}
	return failAt(op, subject, step, step, "%v", err)
}

// followedStep is the step of the last progress event a command saw, as findings name
// steps, so a failure the command meets while following a run names the step the run had
// reached; start before any event. The goroutine that follows the run writes it,
// and the one waiting on interrupts reads it.
type followedStep struct {
	mu   sync.Mutex
	step string
}

func (f *followedStep) observe(e provision.Event) {
	if e.FindingStep == "" {
		return
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	f.step = e.FindingStep
}

func (f *followedStep) get() string {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.step == "" {
		return findings.StepStart
	}
	return f.step
}

// provisionReport prints a ready twin's success lines, or what cleanup removed for a run
// that stopped short of ready, and returns the run's document, whose status carries the
// exit code.
//
// Following is reported last: the following the run replaced, before anything else; and on
// a ready twin, the following it began, or that it could not begin (contracts/cli.md).
func provisionReport(opts *options, op string, subject *findings.Subject, in provision.ProvisionInput, res provision.ProvisionResult) error {
	doc := provision.ProvisionDocument(op, subject, res)
	if stopped := res.FollowingStopped; stopped != nil && stopped.Deleted {
		opts.note("following of branch %s stopped", stopped.Branch)
	}
	if doc.Status == findings.StatusOK && res.Twin != nil {
		opts.note("twin ready: bundle_id %s", res.BundleID)
		for _, n := range res.Twin.Nodes {
			opts.note("  %s  %s", n.Name, n.MgmtIPv4)
		}
		opts.note("twin directory %s", res.TwinDir)
		switch {
		case in.Source == wire.SourceBundle:
			opts.note("not following (provisioned from a bundle)")
		case in.Follow == nil && in.At != "":
			opts.note("pinned at %s, not following", in.At)
		case in.Follow == nil:
			opts.note("not following")
		case res.Following != nil:
			opts.note("following branch %s, checked every %s (schedule %s)",
				res.Following.Branch, time.Duration(res.Following.IntervalS)*time.Second, res.Following.ScheduleID)
		case in.Follow != nil && carriesRule(res.Findings, findings.RuleFollowStartFailed):
			opts.note("not following: %s (see findings); destroy and create again", findings.RuleFollowStartFailed)
			doc.Following = &findings.FollowingBlock{Branch: in.Branch, IntervalS: in.Follow.IntervalS, State: findings.FollowingNotStarted}
		}
		return &result{doc: doc}
	}
	// A run stopped after the host check cleared has cleaned up. What that removed is
	// reported beside the failure here, not only in the progress lines, which are best
	// effort. Before the host check cleared nothing was touched, and nothing is said.
	if t := res.Cleanup.Teardown; t != "" && t != provision.CleanupSkipped {
		printCleanup(opts, res.Cleanup)
	}
	return &result{doc: doc}
}

// carriesRule reports whether list holds a finding under rule.
func carriesRule(list findings.List, rule string) bool {
	for _, f := range list {
		if f.Rule == rule {
			return true
		}
	}
	return false
}

// printCleanup says what teardown and unstage removed, one line each, or that there was
// nothing to remove. What remains is named by the cleanup.incomplete findings on stderr.
func printCleanup(opts *options, c provision.CleanupResult) {
	for _, item := range c.Removed {
		opts.note("removed %s", item)
	}
	if len(c.Removed) == 0 && len(c.Remaining) == 0 {
		opts.note("nothing to remove: no lab %s, no twin directory", wire.LabName)
	}
}

// followRun prints workflowID's run's progress as its history grows and blocks until the
// run has closed, which for a failed run is after its cleanup has finished,
// and returns what result says of it.
//
// The first interrupt asks the run to cancel, says cancelling, and keeps waiting: the
// cleanup is what the operator needs to see finish, and the exit
// status is then the run's own — 3 when the cleanup left the host clean, 4 when something
// remains; a step run's cleanup is its record. A second interrupt stops waiting
// and returns run.cancelled; the run carries on without us, and `fylgja twin destroy` waits
// for it (contracts/cli.md, create step 7). interrupted says the first interrupt arrived
// while the run was being started.
func followRun[R any](ctx context.Context, opts *options, svc provision.Service, op string,
	subject *findings.Subject, workflowID, runID string, interrupts <-chan os.Signal, interrupted bool,
	closedAs func(context.Context) (R, error), cancelling string) (R, error) {
	opts.note("run %s %s", workflowID, runID)

	followCtx, stopFollowing := context.WithCancel(ctx)
	defer stopFollowing()

	type closed struct {
		res R
		err error
	}
	done := make(chan closed, 1)
	// Where the run had got to, for a failure met while waiting on it to name.
	followed := &followedStep{}
	go func() {
		// Progress is best effort: a history that cannot be read costs lines, not the
		// result, which is asked for separately.
		_ = svc.Follow(followCtx, workflowID, runID, func(e provision.Event) {
			opts.c.eventFrame(e)
			printEvent(opts, e)
			followed.observe(e)
		})
		res, err := closedAs(followCtx)
		done <- closed{res: res, err: err}
	}()

	cancelRequested := false
	requestCancel := func() {
		cancelRequested = true
		// The operator's interrupt reached this request, so the run is asked to cancel
		// whatever becomes of the client after it: a client that goes away straight after its
		// interrupt was delivered says the run was asked to cancel, as a start it
		// abandoned was (startRun). The call is bounded on its own.
		cancelCtx, cancelled := context.WithTimeout(context.WithoutCancel(ctx), cancelRequestBudget)
		defer cancelled()
		if err := svc.Cancel(cancelCtx, workflowID, runID); err != nil {
			_, _ = fmt.Fprintf(opts.stderr(), "fylgja: requesting cancellation of run %s: %v\n", runID, err)
			return
		}
		opts.note("%s", cancelling)
	}
	if interrupted {
		requestCancel()
	}
	var none R
	for {
		select {
		case c := <-done:
			// The follow ends with the request, so an interrupt delivered just before the
			// client went can be waiting beside it; it is acted on all the same.
			if c.err != nil && ctx.Err() != nil && !cancelRequested {
				select {
				case <-interrupts:
					requestCancel()
				default:
				}
			}
			if c.err != nil {
				step := followed.get()
				return none, failAt(op, subject, step, step, "waiting for run %s: %v", runID, c.err)
			}
			return c.res, nil
		case <-interrupts:
			if !cancelRequested {
				requestCancel()
				continue
			}
			stopFollowing()
			doc := findings.RuleErrorDocument(op, subject, findings.RuleRunCancelled, runID,
				fmt.Sprintf("stopped waiting for run %s; it continues on the workflow service, and fylgja twin destroy will wait for it", runID))
			doc.Findings[0].Step = followed.get()
			return none, &result{doc: doc}
		}
	}
}

// cancelRequestBudget bounds the request that asks a run to cancel, which the client's
// departure does not end: a mechanism constant, as the start's terminate budget is.
const cancelRequestBudget = 10 * time.Second

// stepObserve is the step run's wait after its record, as its progress lines name it.
const stepObserve = "observe"

// printEvent writes one progress line. The lines are not contract (contracts/cli.md).
// Cleanup steps are named without "step": they are what a stopped run does, not a step
// toward the twin.
func printEvent(opts *options, e provision.Event) {
	if e.Notice != "" {
		opts.note("%s", e.Notice)
		return
	}
	label := "step " + e.Step
	if strings.HasPrefix(e.Step, "cleanup ") {
		label = e.Step
	}
	secs := e.Duration.Seconds()
	switch {
	case !e.End:
		opts.note("%s: begins", label)
	case e.Outcome == provision.EventDone && strings.HasPrefix(e.Step, "readiness "):
		opts.note("%s: ready in %.1fs", label, secs)
	// The step's wait says how it ended, not how long the activity ran (M12 contracts/cli.md,
	// twin step --wait); an activity that failed outright, or that the service timed out at
	// the end of its window, is the wait that could not complete.
	case e.Step == stepObserve && e.Outcome == provision.EventDone && e.Detail != "":
		opts.note("%s: %s", label, e.Detail)
	case e.Step == stepObserve && (e.Outcome == provision.EventFailed || e.Outcome == provision.EventTimedOut):
		opts.note("%s: could not complete: %s", label, e.Message)
	case e.Outcome == provision.EventDone && e.Detail != "":
		opts.note("%s: done in %.1fs (%s)", label, secs, e.Detail)
	case e.Outcome == provision.EventDone:
		opts.note("%s: done in %.1fs", label, secs)
	// A failure's type is its rule when an activity reported one; rule identifiers always
	// carry a dot, and Go type names, which the SDK uses otherwise, never do.
	case e.Outcome == provision.EventFailed && strings.Contains(e.Rule, "."):
		opts.note("%s: failed %s: %s", label, e.Rule, e.Message)
	case e.Outcome == provision.EventFailed:
		opts.note("%s: failed: %s", label, e.Message)
	case e.Message != "":
		opts.note("%s: %s after %.1fs: %s", label, e.Outcome, secs, e.Message)
	default:
		opts.note("%s: %s after %.1fs", label, e.Outcome, secs)
	}
}
