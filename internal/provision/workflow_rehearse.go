package provision

// Deterministic: a workflow file. No I/O, clock or randomness (Constitution VIII).

import (
	"fmt"
	"time"

	"go.temporal.io/sdk/workflow"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/rehearsal"
)

// Rehearse is the rehearsal run, fylgja-rehearse (015, D-051, research R-01): a proposed
// change's stages rehearsed on one twin, every stage already resolved, read, compiled and
// decided by the server. It runs M2's and M11's runs as its children, each under its own
// fixed id, so each is refused beside any other run and keeps its own locks and cleanup:
//
//  1. deadline: a timer on the run's clock whose firing cancels the children's context;
//  2. baseline: a child fylgja-provision, already compiled, which stops following and whose
//     record names this run, then its wait, VerifyTwin on the children's context, written
//     into no record; the wait's failing assertions are the baseline findings;
//  3. each rehearsed stage in order: a child fylgja-step, whose own wait is its verify,
//     classified by rehearsal.Classify against the baseline findings. The run stops at the
//     first stage whose verdict rehearsal.Stop says stops it, and every later stage is not
//     reached;
//  4. last: a child fylgja-destroy, on a context no cancellation reaches, unless the run
//     touched nothing.
//
// The deadline's firing ends the stage in progress error and the run cut; the run's own
// cancellation, the operator's interrupt or twin destroy, cancels the children the same way
// and ends the run cancelled. Either way a provision cleans up, a step records diverged
// (D-036), and the destroy follows. A baseline that is not built ends the run
// baseline_failed with no stage rehearsed. A baseline whose provision could not start
// because another run holds its id ends the run rejected: nothing was touched, and the
// destroy, which removes whatever lab the host holds, would tear down that run's (FR-007).
// The run branches only on each stage's role, the children's outcomes and the verdicts,
// reads no clock but the workflow's, and starts no activity but VerifyTwin. It returns one
// result in every case, never an error.
func Rehearse(ctx workflow.Context, in RehearseInput) (RehearseResult, error) {
	started := workflow.Now(ctx).UTC()
	res := RehearseResult{Stages: []RehearsedStage{}, Findings: findings.List{}, StartedAt: started.Format(time.RFC3339Nano)}
	r := &rehearsing{ctx: ctx, res: &res}
	r.children, r.cut = workflow.WithCancel(ctx)

	// 1. The deadline. Its timer is cancelled once the stages are done, so it never fires
	// during the destroy, which no deadline cuts.
	timerCtx, stopTimer := workflow.WithCancel(ctx)
	deadline := workflow.NewTimer(timerCtx, deadlineOf(in))
	workflow.Go(timerCtx, func(gctx workflow.Context) {
		if deadline.Get(gctx, nil) == nil {
			res.DeadlineHit = true
			r.cut()
		}
	})

	// 2 and 3.
	r.stages(in.Stages)
	stopTimer()

	// 4. A run refused at its baseline's start touched nothing.
	if res.Outcome != rehearsal.OutcomeRejected {
		r.destroy()
	}

	ended := workflow.Now(ctx).UTC()
	res.EndedAt = ended.Format(time.RFC3339Nano)
	res.UsedS = ended.Sub(started).Seconds()
	return res, nil
}

// rehearsing is one rehearsal run as it goes: its own context, the children's, which the
// deadline and the run's cancellation both cancel, the baseline findings once the baseline's
// wait has read every node, whether the last child refused at its start was refused because
// a run holds its id, and the result it fills.
type rehearsing struct {
	ctx      workflow.Context
	children workflow.Context
	cut      workflow.CancelFunc
	baseline []wire.StepFinding
	held     bool
	res      *RehearseResult
}

// deadlineOf is the run's deadline: the server's, summed from the stages' budgets, or the
// ceiling when it gave none, so no rehearsal runs without one.
func deadlineOf(in RehearseInput) time.Duration {
	switch {
	case in.DeadlineS > 0:
		return seconds(in.DeadlineS)
	case in.CeilingS > 0:
		return seconds(in.CeilingS)
	}
	return rehearsal.Ceiling
}

// interrupted says the deadline or the run's own cancellation has cancelled the children.
func (r *rehearsing) interrupted() bool { return r.res.DeadlineHit || r.ctx.Err() != nil }

// stages runs every stage in order: the refused one passed over, the baseline built and
// waited on, each rehearsed stage stepped to, until one stops the run, and every stage after
// it not reached. The run's outcome is the stopping stage's, or ok.
func (r *rehearsing) stages(stages []RehearseStage) {
	stopped := false
	for _, s := range stages {
		var st RehearsedStage
		switch {
		case s.Role == rehearsal.RoleRefused:
			r.res.Stages = append(r.res.Stages, RehearsedStage{Ref: s.Ref, Verdict: rehearsal.VerdictRefused})
			continue
		case stopped, s.Role != rehearsal.RoleBaseline && s.Role != rehearsal.RoleRehearsed:
			r.res.Stages = append(r.res.Stages, RehearsedStage{Ref: s.Ref, Verdict: rehearsal.VerdictNotReached})
			continue
		case r.children.Err() != nil:
			// Cut or cancelled between two stages: this one is the stage in progress.
			st = RehearsedStage{Ref: s.Ref, Verdict: rehearsal.VerdictError}
		case s.Role == rehearsal.RoleBaseline:
			st = r.baselineStage(s)
		default:
			st = r.rehearsedStage(s)
		}
		r.res.Stages = append(r.res.Stages, st)
		r.res.Reached = s.Ref
		if rehearsal.Stop(st.Verdict) {
			stopped = true
			r.res.Outcome = r.outcome(s, st)
		}
	}
	if r.res.Outcome == "" {
		r.res.Outcome = rehearsal.OutcomeOK
	}
}

// outcome is the run's outcome when stage st stopped it: a baseline whose provision could not
// start because a run holds its id, cut by the deadline, cancelled by the run's own
// cancellation, a baseline whose provision did not end ready, a stage that failed, or one
// that could not be rehearsed.
func (r *rehearsing) outcome(s RehearseStage, st RehearsedStage) string {
	switch {
	case s.Role == rehearsal.RoleBaseline && st.Run == nil && r.held:
		return rehearsal.OutcomeRejected
	case r.res.DeadlineHit:
		return rehearsal.OutcomeCut
	case r.ctx.Err() != nil:
		return rehearsal.OutcomeCancelled
	case s.Role == rehearsal.RoleBaseline && st.Provision != nil && st.Provision.Outcome != OutcomeReady:
		return rehearsal.OutcomeBaselineFailed
	case st.Verdict == rehearsal.VerdictFailed:
		return rehearsal.OutcomeStageFailed
	}
	return rehearsal.OutcomeStageError
}

// baselineStage builds the twin from the baseline, through a child fylgja-provision already
// compiled whose record names this run, then waits on it with VerifyTwin, from the record's
// time and under the stage's wait budget. The wait's run is this run, which the record does
// not name, so the wait is written into no record. A wait that read every node, settled or
// expired, gives the baseline findings and the verdict baseline; anything else is error, since
// no later stage could be compared with it. A provision refused at its start because a run
// holds its id did not reach the stage: not reached, and the run rejected.
func (r *rehearsing) baselineStage(s RehearseStage) RehearsedStage {
	began := workflow.Now(r.ctx)
	st := RehearsedStage{Ref: s.Ref, Verdict: rehearsal.VerdictError}
	if s.Provision == nil {
		r.res.Findings.AddStep(findings.Rejection, findings.StepProvision, findings.RuleOperationFailed, s.Ref,
			"the rehearsal's input gives the baseline "+s.Ref+" no provision")
		return r.took(st, began)
	}
	self := workflow.GetInfo(r.ctx).WorkflowExecution
	in := *s.Provision
	in.Rehearsal = &wire.RehearsalRef{WorkflowID: self.ID, RunID: self.RunID}
	in.StopFollowing = true
	child := workflow.ExecuteChildWorkflow(workflow.WithChildOptions(r.children, ChildOptions(WorkflowProvision)),
		provisionWorkflowType, in)
	if st.Run = r.started(child, WorkflowProvision, findings.StepProvision); st.Run == nil {
		if r.held {
			st.Verdict = rehearsal.VerdictNotReached
		}
		return r.took(st, began)
	}
	var provisioned ProvisionResult
	if err := child.Get(r.children, &provisioned); err != nil {
		r.closedWithout(err, *st.Run, findings.StepProvision)
		return r.took(st, began)
	}
	st.Provision = &provisioned
	if provisioned.Outcome != OutcomeReady || r.interrupted() {
		return r.took(st, began)
	}

	from := began.UTC().Format(time.RFC3339Nano)
	if provisioned.Twin != nil && provisioned.Twin.RecordedAt != "" {
		from = provisioned.Twin.RecordedAt
	}
	var v wire.VerifyResult
	err := execute(r.children, VerifyOptions(s.WaitS), wire.ActVerifyTwin, &v,
		wire.VerifyInput{RunID: self.RunID, From: from, BudgetS: s.WaitS})
	switch {
	case err == nil:
		st.Wait, st.Counts = &v.Wait, v.Counts
	case r.interrupted():
		// Cut before it answered: the wait reads as not run.
	default:
		f := failureFinding(err, findings.StepObserve, findings.RuleOperationFailed, self.RunID)
		st.Wait = &wire.StepWait{Outcome: wire.WaitIncomplete, BudgetS: s.WaitS, From: from,
			Failing: []wire.StepFinding{{Rule: f.Rule, Object: f.Object, Message: f.Message}}}
	}
	if w := st.Wait; w != nil && !r.interrupted() && (w.Outcome == wire.WaitSettled || w.Outcome == wire.WaitExpired) {
		st.Verdict = rehearsal.VerdictBaseline
		r.baseline = w.Failing
	}
	return r.took(st, began)
}

// rehearsedStage steps the twin to s through a child fylgja-step, whose wait after its record
// is the stage's verify, and classifies the stage against the baseline findings. A stage the
// deadline or the run's cancellation cut is error whatever its child says.
func (r *rehearsing) rehearsedStage(s RehearseStage) RehearsedStage {
	began := workflow.Now(r.ctx)
	st := RehearsedStage{Ref: s.Ref, Verdict: rehearsal.VerdictError}
	if s.Step == nil {
		r.res.Findings.AddStep(findings.Rejection, findings.StepStart, findings.RuleOperationFailed, s.Ref,
			"the rehearsal's input gives the stage "+s.Ref+" no step")
		return r.took(st, began)
	}
	child := workflow.ExecuteChildWorkflow(workflow.WithChildOptions(r.children, ChildOptions(WorkflowStep)),
		stepWorkflowType, *s.Step)
	if st.Run = r.started(child, WorkflowStep, findings.StepStart); st.Run == nil {
		return r.took(st, began)
	}
	var stepped StepResult
	if err := child.Get(r.children, &stepped); err != nil {
		r.closedWithout(err, *st.Run, findings.StepStart)
		return r.took(st, began)
	}
	st.Step = &stepped
	st.Wait, st.Counts = stepped.Wait, stepped.WaitCounts
	st.Verdict, st.NewFindings = rehearsal.Classify(
		&rehearsal.StepOutcome{Outcome: stepped.Outcome, Phase: stepped.Phase, Step: stepped.Step},
		stepped.Wait, r.baseline, r.interrupted())
	return r.took(st, began)
}

// took sets the stage's whole time on the run's clock.
func (r *rehearsing) took(st RehearsedStage, began time.Time) RehearsedStage {
	st.TookS = workflow.Now(r.ctx).Sub(began).Seconds()
	return st
}

// started waits for a child to start and returns its run. A child the deadline or the run's
// cancellation stopped before it started files nothing, since the outcome says why; one
// refused because a run holds its id files run.in_flight and sets held, and one refused
// otherwise operation.failed, at step. The baseline's provision is the run's first child, so
// its refusal says the rehearsal touched nothing.
func (r *rehearsing) started(child workflow.ChildWorkflowFuture, workflowID, step string) *wire.RunRef {
	var run workflow.Execution
	err := child.GetChildWorkflowExecution().Get(r.children, &run)
	r.held = false
	switch {
	case err == nil:
		return &wire.RunRef{WorkflowID: workflowID, RunID: run.RunID}
	case r.interrupted():
	case alreadyStarted(err) && workflowID == WorkflowProvision:
		r.held = true
		r.res.Findings.AddStep(findings.Rejection, step, findings.RuleRunInFlight, workflowID, fmt.Sprintf(
			"the rehearsal's %s could not start: a run is already in flight under its id, so the rehearsal touched nothing "+
				"and ran no destroy; wait for that run to finish, or run fylgja twin destroy to cancel it", workflowID))
	case alreadyStarted(err):
		r.held = true
		r.res.Findings.AddStep(findings.Rejection, step, findings.RuleRunInFlight, workflowID,
			fmt.Sprintf("the rehearsal's %s could not start: a run is already in flight under its id", workflowID))
	default:
		r.res.Findings = append(r.res.Findings, failureFinding(err, step, findings.RuleOperationFailed, workflowID))
	}
	return nil
}

// closedWithout files a child that closed without a result, terminated or failed, as
// operation.failed on its run, unless the deadline or the run's cancellation stopped it.
func (r *rehearsing) closedWithout(err error, run wire.RunRef, step string) {
	if r.interrupted() {
		return
	}
	r.res.Findings = append(r.res.Findings, failureFinding(err, step, findings.RuleOperationFailed, run.RunID))
}

// destroy runs the child fylgja-destroy on a context no cancellation reaches, whatever the
// stages did: the destroy is the rehearsal's cleanup. One that could not start or closed
// without a result checked nothing, and its result says so under cleanup.incomplete, so
// the rehearsal ends unclean rather than claiming a host it never looked at.
func (r *rehearsing) destroy() {
	uninterrupted, _ := workflow.NewDisconnectedContext(r.ctx)
	child := workflow.ExecuteChildWorkflow(workflow.WithChildOptions(uninterrupted, ChildOptions(WorkflowDestroy)),
		destroyWorkflowType)
	var run workflow.Execution
	if err := child.GetChildWorkflowExecution().Get(uninterrupted, &run); err != nil {
		r.res.Destroy = destroyNotRun("could not start ("+childStartRefusal(err)+")", WorkflowDestroy)
		return
	}
	var destroyed DestroyResult
	if err := child.Get(uninterrupted, &destroyed); err != nil {
		r.res.Destroy = destroyNotRun("run "+run.RunID+" closed without a result ("+causeMessage(err)+")", run.RunID)
		return
	}
	r.res.Destroy = &destroyed
}

// destroyNotRun is the destroy's result when it checked nothing: neither teardown nor
// unstage attempted, the lab and the twin directory remaining unchecked, under
// cleanup.incomplete naming what happened and the remedy.
func destroyNotRun(what, object string) *DestroyResult {
	res := &DestroyResult{
		Cleanup: CleanupResult{Teardown: CleanupSkipped, Unstage: CleanupSkipped,
			Remaining: []string{"lab " + wire.LabName + " and the twin directory (not checked: the rehearsal's destroy " + what + ")"}},
		Findings: findings.List{},
	}
	res.Findings.AddStep(findings.Rejection, findings.StepDestroy, findings.RuleCleanupIncomplete, object,
		"the rehearsal's destroy "+what+"; what the rehearsal built may remain, and fylgja twin destroy clears it")
	return res
}
