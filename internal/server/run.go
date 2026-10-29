package server

import (
	"context"
	"errors"
	"fmt"
	"slices"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/provision"
)

// readableRuns are the workflows run.read and run.interrupt reach a run of by its identity:
// the operator's three (020, R-04). Any other workflow id names no run of this API's.
var readableRuns = []string{provision.WorkflowProvision, provision.WorkflowStep, provision.WorkflowDestroy}

// errRunning is a run.read of a run that has not closed: its answer ends after its events,
// by EOF, with no document, the one answer the contract lets end without one
// (contracts/api.md, R-04).
var errRunning = errors.New("the run has not closed, so its read ends with no document")

// runReadByIdentity answers run.read: the run the identity names, its state, every event its history
// holds so far and, once it has closed, the document its result makes, the one its stream
// would have carried under operation run.read. Everything is read from the workflow
// service, so the server keeps nothing between two requests (FR-010). An identity no run
// has is run.unknown, after the describe alone; a running run's answer ends by EOF.
func runReadByIdentity(ctx context.Context, opts *options, workflowID, runID string) error {
	const op = findings.OpRunRead
	subject := &findings.Subject{RunID: runID}
	if err := reachable(op, subject, workflowID, runID); err != nil {
		return err
	}
	svc, err := opts.dial(ctx)
	if err != nil {
		return startFailure(op, subject, findings.StepStart, err)
	}
	defer svc.Close()

	state, err := svc.Describe(ctx, workflowID, runID)
	if err != nil {
		return describeFailure(op, subject, err)
	}
	subject.RunID = state.RunID
	opts.c.runStateFrame(state)
	opts.note("run %s %s: %s", workflowID, state.RunID, state.State)

	followed := &followedStep{}
	onEvent := func(e provision.Event) {
		opts.c.eventFrame(e)
		printEvent(opts, e)
		followed.observe(e)
	}
	if state.Running() {
		if err := svc.History(ctx, workflowID, state.RunID, onEvent); err != nil {
			return historyFailure(op, subject, followed, state, err)
		}
		return errRunning
	}
	// The history ends at the run's close, so Follow returns at it without waiting.
	if err := svc.Follow(ctx, workflowID, state.RunID, onEvent); err != nil {
		return historyFailure(op, subject, followed, state, err)
	}
	closedWithout := func(err error) error {
		return failAt(op, subject, followed.get(), identity(workflowID, state.RunID),
			"run %s closed %s without a result: %v", identity(workflowID, state.RunID), state.State, err)
	}
	switch workflowID {
	case provision.WorkflowStep:
		in, err := svc.InputOfStep(ctx, state.RunID)
		if err != nil {
			return closedWithout(err)
		}
		res, err := svc.ResultOfStep(ctx, state.RunID)
		if err != nil {
			return closedWithout(err)
		}
		if line := stepClosing(in, res); line != "" {
			opts.note("%s", line)
		}
		doc := provision.StepDocument(subject, in, res)
		doc.Operation = op
		return &result{doc: doc}
	case provision.WorkflowDestroy:
		res, err := svc.ResultOfDestroy(ctx, state.RunID)
		if err != nil {
			return closedWithout(err)
		}
		printCleanup(opts, res.Cleanup)
		doc := provision.DestroyDocument(subject, res)
		doc.Operation = op
		return &result{doc: doc}
	}
	res, err := svc.Result(ctx, workflowID, state.RunID)
	if err != nil {
		return closedWithout(err)
	}
	return provisionReport(opts, op, subject, res)
}

// runInterruptByIdentity answers run.interrupt: the run the identity names asked to cancel, as a
// stream's first interrupt asks it (followRun), so it cleans up and closes as its stream
// would have said; a run already closed is run.ended, naming its state, and an identity no
// run has is run.unknown. Nothing is waited for: a read of the run says how it closes.
func runInterruptByIdentity(ctx context.Context, opts *options, workflowID, runID string) error {
	const op = findings.OpRunInterrupt
	subject := &findings.Subject{RunID: runID}
	if err := reachable(op, subject, workflowID, runID); err != nil {
		return err
	}
	svc, err := opts.dial(ctx)
	if err != nil {
		return startFailure(op, subject, findings.StepStart, err)
	}
	defer svc.Close()

	state, err := svc.Describe(ctx, workflowID, runID)
	if err != nil {
		return describeFailure(op, subject, err)
	}
	subject.RunID = state.RunID
	id := identity(workflowID, state.RunID)
	var list findings.List
	if !state.Running() {
		list.Add(findings.Rejection, findings.RuleRunEnded, id, fmt.Sprintf("run %s has already closed: %s", id, state.State))
		return finish(op, subject, list)
	}
	// Asked where the client's departure does not reach it, and bounded on its own, as the
	// stream's first interrupt asks.
	cancelCtx, cancelled := context.WithTimeout(context.WithoutCancel(ctx), cancelRequestBudget)
	defer cancelled()
	if err := svc.Cancel(cancelCtx, workflowID, state.RunID); err != nil {
		if refused, ok := provision.AsStartError(err); ok {
			return &result{doc: refused.Document(op, subject)}
		}
		return failAt(op, subject, "", id, "requesting cancellation of run %s: %v", id, err)
	}
	opts.note("run %s: cancellation requested", id)
	list.Add(findings.Info, findings.RuleRunCancelRequested, id,
		fmt.Sprintf("cancellation of run %s was requested; it cleans up and closes, and fylgja run read says how", id))
	return finish(op, subject, list)
}

// reachable refuses a workflow id that names no run run.read or run.interrupt reaches,
// before anything is dialled: run.unknown, naming the identity as the request gave it.
func reachable(op string, subject *findings.Subject, workflowID, runID string) error {
	if slices.Contains(readableRuns, workflowID) {
		return nil
	}
	var list findings.List
	list.Add(findings.Rejection, findings.RuleRunUnknown, identity(workflowID, runID),
		fmt.Sprintf("%q names no run %s reaches: it reads a run of %s, %s or %s", workflowID, op,
			readableRuns[0], readableRuns[1], readableRuns[2]))
	return finish(op, subject, list)
}

// describeFailure is the describe's error as op's document: run.unknown for an identity the
// workflow service holds no run under, run.service.unreachable for a service that did not
// answer, and the operation failing otherwise.
func describeFailure(op string, subject *findings.Subject, err error) error {
	var unknown *provision.UnknownRunError
	if errors.As(err, &unknown) {
		var list findings.List
		list.Add(findings.Rejection, findings.RuleRunUnknown, unknown.Identity(), unknown.Error())
		return finish(op, subject, list)
	}
	if refused, ok := provision.AsStartError(err); ok {
		return &result{doc: refused.Document(op, subject)}
	}
	return failAt(op, subject, "", op, "describing the run: %v", err)
}

// historyFailure is a history the read could not read to its end: the operation failing at
// the step the history had reached.
func historyFailure(op string, subject *findings.Subject, followed *followedStep, state provision.RunState, err error) error {
	if refused, ok := provision.AsStartError(err); ok {
		return &result{doc: refused.Document(op, subject)}
	}
	id := identity(state.WorkflowID, state.RunID)
	return failAt(op, subject, followed.get(), id, "reading the history of run %s: %v", id, err)
}

// identity is a run as the run rules name it: <workflow_id> <run_id>, or the workflow id
// alone when the request named no run.
func identity(workflowID, runID string) string {
	if runID == "" {
		return workflowID
	}
	return workflowID + " " + runID
}
