package provision

// Deterministic: a workflow file. No I/O, clock or randomness (Constitution VIII).

import (
	"errors"
	"fmt"
	"strings"

	"go.temporal.io/api/serviceerror"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// Reconcile is a check: Schedule fylgja-follow starts one every interval, and nothing else
// may. It looks at what the host holds, reads the
// followed branch at its head, compiles it and compares the bundle with the twin's. An
// unchanged twin is left alone. A changed one is rebuilt through M2's runs as children —
// the destroy under fylgja-destroy, then the provision under fylgja-provision, already
// compiled — so a rebuild is serialised with the operator's runs by their fixed ids.
//
// Nothing on the host is touched before the destroy: a check that is skipped, refused or
// could not run leaves the twin as it was, and the next check tries again.
// A rebuild that fails stops following, on a context the check's cancellation does not
// reach, so a twin that cannot be rebuilt is not destroyed again every interval.
//
// It returns a result in every case, never an error, so twin show reads one shape.
func Reconcile(ctx workflow.Context, in ReconcileInput) (ReconcileResult, error) {
	res := ReconcileResult{Branch: in.Branch, Findings: findings.List{}}

	// 1. What the host holds.
	var host wire.HostReport
	if err := execute(ctx, InspectTwinOptions(), wire.ActInspectTwin, &host); err != nil {
		return checkNotRun(ctx, res, findings.StepInspect, err), nil
	}
	if ctx.Err() != nil {
		return checkCancelled(ctx, res, findings.StepInspect), nil
	}
	if object, message := nothingToCompare(host, in.Branch); message != "" {
		return checkSkipped(res, object, message), nil
	}
	res.TwinBundleID = host.Twin.BundleID

	// 2. The operator's runs: a rebuild beside one would be refused, so the check skips.
	if ended, ok := operatorRuns(ctx, res); !ok {
		return ended, nil
	}

	// 3. The branch at its head. No at: a following twin is never pinned. A branch that no
	// longer exists is refused, not a read that could not run.
	var read ReadIntentResult
	if err := execute(ctx, ReadOptions(), wire.ActReadIntent, &read, ReadIntentInput{Branch: in.Branch}); err != nil {
		if ctx.Err() == nil && isBranchNotFound(err) {
			res.Findings = append(res.Findings, failureFinding(err, findings.StepRead, findings.RuleOperationFailed, findings.StepRead))
			return checkEnded(res, CheckRejected, findings.StepRead), nil
		}
		return checkNotRun(ctx, res, findings.StepRead, err), nil
	}
	res.ObservedAt = read.ObservedAt
	res.Findings = append(res.Findings, read.Findings...)
	if ctx.Err() != nil {
		return checkCancelled(ctx, res, findings.StepRead), nil
	}
	if read.Findings.Rejected() {
		return checkEnded(res, CheckRejected, findings.StepRead), nil
	}

	// 4. Compile and file the bundle.
	var compiled CompileResult
	if err := execute(ctx, CompileOptions(), wire.ActCompile, &compiled, CompileInput{CTMPath: read.CTMPath}); err != nil {
		return checkNotRun(ctx, res, findings.StepCompile, err), nil
	}
	res.Findings = append(res.Findings, compiled.Findings...)
	if ctx.Err() != nil {
		return checkCancelled(ctx, res, findings.StepCompile), nil
	}
	if compiled.Findings.Rejected() {
		return checkEnded(res, CheckRejected, findings.StepCompile), nil
	}
	res.BundleID = compiled.BundleID

	// 5. Compare.
	if compiled.BundleID == res.TwinBundleID {
		res.Outcome = CheckUnchanged
		return res, nil
	}

	// 6. Check the host for the new bundle, before anything is destroyed. The running twin is
	// what host.lab.present and host.twin.present name, so they are dropped here; the
	// provision child applies them again once the destroy has cleared the host.
	var plan wire.CheckHostResult
	if err := execute(ctx, CheckHostOptions(), wire.ActCheckHost, &plan,
		wire.CheckHostInput{BundlePath: compiled.BundlePath, BundleID: compiled.BundleID}); err != nil {
		return checkNotRun(ctx, res, findings.StepHostCheck, err), nil
	}
	plan.Findings = withoutPresence(plan.Findings)
	res.Findings = append(res.Findings, plan.Findings...)
	if ctx.Err() != nil {
		return checkCancelled(ctx, res, findings.StepHostCheck), nil
	}
	if plan.Findings.Rejected() {
		return checkEnded(res, CheckRejected, findings.StepHostCheck), nil
	}

	// 6a. The operator's runs again. One begun while steps 3–6 ran holds fylgja-provision, not
	// the destroy child's id, so nothing would refuse the destroy beside it. The child
	// starts in the workflow task that receives this answer.
	if ended, ok := operatorRuns(ctx, res); !ok {
		return ended, nil
	}

	// 7. Destroy the twin, on a context the check's cancellation does not reach. M2's Destroy
	// honours a cancel between its teardown and its unstage, which would leave the twin
	// directory unchecked beside a check that says the destroy ran to completion. A destroy
	// that cancels the check still cancels a provision child, which step 8 starts on ctx. No
	// cancelled check starts this child: step 6's ctx.Err() check and the start share a
	// workflow task.
	uninterrupted, _ := workflow.NewDisconnectedContext(ctx)
	destroyChild := workflow.ExecuteChildWorkflow(workflow.WithChildOptions(uninterrupted, ChildOptions(WorkflowDestroy)), destroyWorkflowType)
	var destroyRun workflow.Execution
	if err := destroyChild.GetChildWorkflowExecution().Get(uninterrupted, &destroyRun); err != nil {
		return childNotStarted(ctx, res, WorkflowDestroy, err), nil
	}
	var destroyed DestroyResult
	destroyErr := destroyChild.Get(uninterrupted, &destroyed)
	if destroyErr == nil {
		res.Destroy = &destroyed
		res.Findings = append(res.Findings, destroyed.Findings...)
	}
	// The destroy ran to completion whatever the check was asked; a cancellation that arrived
	// meanwhile provisions nothing.
	if ctx.Err() != nil || temporal.IsCanceledError(destroyErr) {
		return checkCancelled(ctx, res, findings.StepDestroy), nil
	}
	switch {
	case destroyErr != nil:
		res.Findings = append(res.Findings, failureFinding(destroyErr, findings.StepDestroy, findings.RuleOperationFailed, destroyRun.RunID))
		return rebuildFailed(ctx, res, findings.StepDestroy, destroyRun.RunID,
			rebuildEnded("destroy", destroyRun.RunID, OutcomeFailed, findings.StepDestroy, CleanupResult{})), nil
	case len(destroyed.Cleanup.Remaining) > 0:
		step := findings.StepUnstage
		if destroyed.Cleanup.Teardown == CleanupFailed {
			step = findings.StepTeardown
		}
		return rebuildFailed(ctx, res, findings.StepDestroy, destroyRun.RunID,
			rebuildEnded("destroy", destroyRun.RunID, string(findings.StatusUnclean), step, destroyed.Cleanup)), nil
	}

	// 8. Provision the new twin, already compiled, recording this check's read. It neither
	// begins following (the Schedule that started this check is still there) nor stops it.
	provisionChild := workflow.ExecuteChildWorkflow(workflow.WithChildOptions(ctx, ChildOptions(WorkflowProvision)), provisionWorkflowType,
		ProvisionInput{
			Source:     wire.SourceIntent,
			Branch:     in.Branch,
			BundlePath: compiled.BundlePath,
			BundleID:   compiled.BundleID,
			ObservedAt: read.ObservedAt,
			Version:    in.Version,
		})
	var provisionRun workflow.Execution
	if err := provisionChild.GetChildWorkflowExecution().Get(ctx, &provisionRun); err != nil {
		if ctx.Err() != nil || temporal.IsCanceledError(err) {
			return checkCancelled(ctx, res, findings.StepProvision), nil
		}
		// The destroy has run, so this is no longer a skip: the host is as the destroy left it.
		return rebuildFailed(ctx, res, findings.StepProvision, WorkflowProvision, fmt.Sprintf(
			"the rebuild's provision %s could not start (%s); the host is as destroy %s left it",
			WorkflowProvision, childStartRefusal(err), destroyRun.RunID)), nil
	}
	var provisioned ProvisionResult
	if err := provisionChild.Get(ctx, &provisioned); err != nil {
		if ctx.Err() != nil || temporal.IsCanceledError(err) {
			return checkCancelled(ctx, res, findings.StepProvision), nil
		}
		res.Findings = append(res.Findings, failureFinding(err, findings.StepProvision, findings.RuleOperationFailed, provisionRun.RunID))
		return rebuildFailed(ctx, res, findings.StepProvision, provisionRun.RunID,
			rebuildEnded("provision", provisionRun.RunID, OutcomeFailed, findings.StepProvision, CleanupResult{})), nil
	}
	res.Provision = &provisioned
	res.Findings = append(res.Findings, withoutRepeatedHostCheck(provisioned.Findings, res.Findings)...)
	switch provisioned.Outcome {
	case OutcomeReady:
		res.Outcome = CheckRebuilt
		return res, nil
	case OutcomeCancelled:
		return checkCancelled(ctx, res, findings.StepProvision), nil
	}
	return rebuildFailed(ctx, res, findings.StepProvision, provisionRun.RunID,
		rebuildEnded("provision", provisionRun.RunID, provisioned.Outcome, provisioned.Step, provisioned.Cleanup)), nil
}

// nothingToCompare says why a check has no twin to compare against, as check.skipped's
// object and message (contracts/cli.md), or "" when it has one: a readable record of a twin
// of the followed branch that follows, whose lab containerlab has. A record whose lab is
// absent is no twin (D-014): a check never provisions a twin where there was none.
func nothingToCompare(host wire.HostReport, branch string) (object, message string) {
	lab := "lab " + wire.LabName
	switch {
	case !host.LabPresent && !host.TwinDirPresent:
		return lab, "nothing to compare against: no " + lab + " and no twin directory; a check never provisions a twin where there was none"
	case host.Twin == nil, !host.LabPresent:
		return host.Phrase, "nothing to compare against: " + host.Phrase + "; fylgja twin destroy clears it"
	case host.Twin.Provenance.Branch != branch:
		return "branch " + host.Twin.Provenance.Branch, fmt.Sprintf(
			"the twin is of branch %s, but the following is of branch %s; nothing is touched", host.Twin.Provenance.Branch, branch)
	case host.Twin.Provenance.At != "":
		// A create's run can record a pinned or bundle twin in front of a check that started
		// before that run's stop step.
		return host.Twin.BundleID, "the twin does not follow (pinned at " + host.Twin.Provenance.At + "); nothing is touched"
	case host.Twin.Source == wire.SourceBundle:
		return host.Twin.BundleID, "the twin does not follow (provisioned from a bundle); nothing is touched"
	}
	return "", ""
}

// operatorRuns asks RunsInFlight whether an operator's run is in flight. It returns false with
// the check ended at inspect when one is, when the service did not answer, or when the check
// was cancelled; nothing has been touched in any of them.
func operatorRuns(ctx workflow.Context, res ReconcileResult) (ReconcileResult, bool) {
	var runs RunsInFlightResult
	if err := execute(ctx, RunsInFlightOptions(), ActRunsInFlight, &runs); err != nil {
		return checkNotRun(ctx, res, findings.StepInspect, err), false
	}
	if ctx.Err() != nil {
		return checkCancelled(ctx, res, findings.StepInspect), false
	}
	if workflowID, runID := runInFlight(runs); runID != "" {
		return checkSkipped(res, runID, inFlightMessage(workflowID, runID)), false
	}
	return res, true
}

// runInFlight is the operator's run in flight, provision first, or "" when none is.
func runInFlight(runs RunsInFlightResult) (workflowID, runID string) {
	switch {
	case runs.Provision != "":
		return WorkflowProvision, runs.Provision
	case runs.Destroy != "":
		return WorkflowDestroy, runs.Destroy
	}
	return "", ""
}

// inFlightMessage is check.skipped's message for a run in flight.
func inFlightMessage(workflowID, runID string) string {
	return workflowID + " " + runID + " is in flight; the check is skipped"
}

// isBranchNotFound reports a read refused because the branch does not exist, by its error
// type (BranchNotFoundType), never by its text.
func isBranchNotFound(err error) bool {
	var appErr *temporal.ApplicationError
	return errors.As(err, &appErr) && appErr.Type() == BranchNotFoundType
}

// withoutRepeatedHostCheck drops from a child's findings each host_check finding identical in
// rule, object and message to one the check's own host check already recorded: the child
// checks the same bundle on the same host, and a warning read twice is one warning.
// The child's result keeps its findings whole.
func withoutRepeatedHostCheck(child, recorded findings.List) findings.List {
	type key struct{ rule, object, message string }
	seen := map[key]bool{}
	for _, f := range recorded {
		if f.Step == findings.StepHostCheck {
			seen[key{f.Rule, f.Object, f.Message}] = true
		}
	}
	out := findings.List{}
	for _, f := range child {
		if f.Step == findings.StepHostCheck && seen[key{f.Rule, f.Object, f.Message}] {
			continue
		}
		out = append(out, f)
	}
	return out
}

// withoutPresence drops the two refusals that name the running twin itself.
func withoutPresence(list findings.List) findings.List {
	out := findings.List{}
	for _, f := range list {
		if f.Rule != findings.RuleHostLabPresent && f.Rule != findings.RuleHostTwinPresent {
			out = append(out, f)
		}
	}
	return out
}

// checkEnded ends the check with outcome at step, its findings already in res.
func checkEnded(res ReconcileResult, outcome, step string) ReconcileResult {
	res.Outcome, res.Step = outcome, step
	return res
}

// checkSkipped ends the check at inspect with check.skipped: nothing was touched.
func checkSkipped(res ReconcileResult, object, message string) ReconcileResult {
	res.Findings.AddStep(findings.Warning, findings.StepInspect, findings.RuleCheckSkipped, object, message)
	return checkEnded(res, CheckSkipped, findings.StepInspect)
}

// checkNotRun ends the check at a step before the destroy that could not run: error, under
// the finding its activity gave or operation.failed, or cancelled when that is why.
func checkNotRun(ctx workflow.Context, res ReconcileResult, step string, err error) ReconcileResult {
	if ctx.Err() != nil || temporal.IsCanceledError(err) {
		return checkCancelled(ctx, res, step)
	}
	res.Findings = append(res.Findings, failureFinding(err, step, findings.RuleOperationFailed, step))
	return checkEnded(res, CheckError, step)
}

// checkCancelled ends the check at step as cancelled, with run.cancelled naming the check.
// Following is not stopped here: the destroy that cancelled the check has stopped it.
func checkCancelled(ctx workflow.Context, res ReconcileResult, step string) ReconcileResult {
	id := workflow.GetInfo(ctx).WorkflowExecution.ID
	var what string
	switch step {
	case findings.StepDestroy:
		what = "the rebuild's destroy ran to completion and nothing was provisioned"
	case findings.StepProvision:
		what = "the rebuild's provision cleaned up after itself"
	default:
		what = "nothing on the host was touched"
	}
	res.Findings.AddStep(findings.Rejection, step, findings.RuleRunCancelled, id,
		"check "+id+" was cancelled at step "+step+"; "+what)
	return checkEnded(res, CheckCancelled, step)
}

// childNotStarted ends a check whose rebuild's destroy was refused: a run holds the id, which
// RunsInFlight did not see. Nothing has been touched, so the check skips, naming the run.
func childNotStarted(ctx workflow.Context, res ReconcileResult, workflowID string, err error) ReconcileResult {
	if ctx.Err() != nil || temporal.IsCanceledError(err) {
		return checkCancelled(ctx, res, findings.StepDestroy)
	}
	if !alreadyStarted(err) {
		return checkNotRun(ctx, res, findings.StepDestroy, err)
	}
	// The refusal carries no run id; ask for it, so the finding names the run as a skip
	// found by RunsInFlight does.
	runID := "(run id unknown)"
	var runs RunsInFlightResult
	if execute(ctx, RunsInFlightOptions(), ActRunsInFlight, &runs) == nil {
		if id, run := runInFlight(runs); id == workflowID && run != "" {
			runID = run
		}
	}
	return checkSkipped(res, runID, inFlightMessage(workflowID, runID))
}

// alreadyStarted reports a child refused because a run holds its id. The workflow service
// says so with a ChildWorkflowExecutionAlreadyStartedError; the SDK's test suite passes on
// the service error itself, so both are recognised.
func alreadyStarted(err error) bool {
	var already *temporal.ChildWorkflowExecutionAlreadyStartedError
	var duplicate *serviceerror.WorkflowExecutionAlreadyStarted
	return errors.As(err, &already) || errors.As(err, &duplicate)
}

// childStartRefusal says why a child did not start.
func childStartRefusal(err error) string {
	if alreadyStarted(err) {
		return "a run is already in flight under its id"
	}
	return causeMessage(err)
}

// rebuildEnded is rebuild.failed's message up to its last clause (contracts/cli.md).
func rebuildEnded(child, runID, outcome, step string, c CleanupResult) string {
	msg := fmt.Sprintf("the rebuild's %s %s ended %s at step %s; cleanup teardown %s, unstage %s",
		child, runID, outcome, step, orSkipped(c.Teardown), orSkipped(c.Unstage))
	if len(c.Remaining) > 0 {
		msg += "; remaining: " + strings.Join(c.Remaining, ", ")
	}
	return msg
}

// rebuildFailed ends a check whose rebuild failed at step, in the child run object, and stops following on a context
// the check's cancellation does not reach. The child's own findings are already in
// res; rebuild.failed follows them, then what the stop did.
func rebuildFailed(ctx workflow.Context, res ReconcileResult, step, object, ended string) ReconcileResult {
	res = checkEnded(res, CheckRebuildFailed, step)

	uninterrupted, _ := workflow.NewDisconnectedContext(ctx)
	var stopped StopFollowingResult
	stopErr := execute(uninterrupted, FollowOptions(), ActStopFollowing, &stopped)
	if stopErr != nil {
		res.Findings.AddStep(findings.Rejection, step, findings.RuleRebuildFailed, object, ended+"; following could not be stopped")
		res.Findings.AddStep(findings.Warning, findings.StepFollow, findings.RuleFollowStopFailed, FollowScheduleID,
			"deleting schedule "+FollowScheduleID+" failed ("+causeMessage(stopErr)+
				") after a failed rebuild; following continues, and the next check may rebuild again; fylgja twin destroy stops it")
		return res
	}
	res.Findings.AddStep(findings.Rejection, step, findings.RuleRebuildFailed, object, ended+"; following stopped")
	res.Findings.AddStep(findings.Warning, findings.StepFollow, findings.RuleFollowStopped, FollowScheduleID,
		"following of branch "+res.Branch+" stopped after a failed rebuild; fylgja twin create starts again")
	res.FollowingStopped = true
	return res
}
