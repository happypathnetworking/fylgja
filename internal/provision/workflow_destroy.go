package provision

// Deterministic: a workflow file. No I/O, clock or randomness (Constitution VIII).

import (
	"go.temporal.io/sdk/workflow"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// Destroy is the destroy run: budget the teardown, tear down lab fylgja, remove the twin
// directory. It succeeds in every combination of lab and twin directory
// present or absent, and never touches the bundle store.
//
// The teardown's budget is PlanTeardown's: the packages of the staged manifest's nodes or,
// for an orphan, of the containers' kinds; the stated default only for what no package
// covers (Constitution II).
//
// Destroy is the cleanup, so it is not cancellable in any useful sense: the plan and the
// teardown run where a cancellation does not reach, and a cancel request is honoured only
// between the teardown and the unstage. It returns a result, never an error.
func Destroy(ctx workflow.Context) (DestroyResult, error) {
	res := DestroyResult{
		Findings: findings.List{},
		Cleanup:  CleanupResult{Teardown: CleanupSkipped, Unstage: CleanupSkipped},
	}
	uninterrupted, _ := workflow.NewDisconnectedContext(ctx)

	// PlanTeardown answers whatever it finds; an error means the activity itself did not
	// run, and the teardown then takes the stated default budget rather than not running.
	var plan wire.PlanTeardownResult
	if err := execute(uninterrupted, PlanTeardownOptions(), wire.ActPlanTeardown, &plan); err != nil {
		workflow.GetLogger(ctx).Warn("teardown plan failed; the default teardown budget stands in", "error", err)
		plan = wire.PlanTeardownResult{}
	}
	teardown(uninterrupted, plan.DestroyTimeoutS, &res.Cleanup, &res.Findings)

	if ctx.Err() != nil {
		runID := workflow.GetInfo(ctx).WorkflowExecution.RunID
		res.Findings.AddStep(findings.Rejection, findings.StepUnstage, findings.RuleRunCancelled, runID,
			"destroy run "+runID+" was cancelled after teardown, so the twin directory was not checked; run fylgja twin destroy again")
		res.Cleanup.Remaining = append(res.Cleanup.Remaining, "twin directory (not checked: the destroy run was cancelled)")
		return res, nil
	}
	unstage(uninterrupted, "", &res.Cleanup, &res.Findings)
	return res, nil
}
