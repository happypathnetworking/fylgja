package provision

import (
	"context"
	"errors"
	"reflect"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"

	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/converter"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/testsuite"
	"go.temporal.io/sdk/workflow"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/rehearsal"
)

// The rehearsal's fixture: proposed change pc-1 on branch change-1, whose branch point the
// plan refused contract.node.missing, as on the development host, and whose marks and head
// compiled; the baseline's record time.
const (
	rehearsalBranch     = "change-1"
	rehearsalRecordedAt = "2026-10-17T14:03:00.000000Z"
)

// rehearseHarness is a workflow test environment for Rehearse, in workflow_reconcile_test.go's
// style: the three children registered as stubs under the type names the worker registers
// Provision, Step and Destroy by, so a rehearsal runs no real run, and VerifyTwin registered
// by name and answered by the harness. It records, in order, each child started by its
// workflow id and each VerifyTwin, and what each was given.
type rehearseHarness struct {
	t   *testing.T
	env *testsuite.TestWorkflowEnvironment

	// The children's bodies and the baseline's wait; the defaults end ready, stepped and
	// settled, and clean.
	provision func(ctx workflow.Context, in ProvisionInput) (ProvisionResult, error)
	step      func(ctx workflow.Context, in StepInput) (StepResult, error)
	destroy   func(ctx workflow.Context) (DestroyResult, error)
	verify    func(ctx context.Context, in wire.VerifyInput) (wire.VerifyResult, error)

	mu         sync.Mutex
	events     []string
	provisions []ProvisionInput
	steps      []StepInput
	verifies   []wire.VerifyInput
	parentRuns []string // each child's parent run, the rehearsal's
	// destroyCut is set when the destroy child saw its context cancelled.
	destroyCut bool
}

func newRehearseHarness(t *testing.T) *rehearseHarness {
	t.Helper()
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	h := &rehearseHarness{t: t, env: env}
	h.provision = func(_ workflow.Context, in ProvisionInput) (ProvisionResult, error) { return built(in), nil }
	h.step = func(_ workflow.Context, in StepInput) (StepResult, error) { return steppedTo(in, settled()), nil }
	h.destroy = func(workflow.Context) (DestroyResult, error) { return destroyedClean(), nil }
	h.verify = func(_ context.Context, in wire.VerifyInput) (wire.VerifyResult, error) {
		counts := settledCounts()
		w := settled()
		w.From = in.From
		return wire.VerifyResult{Wait: w, Counts: &counts}, nil
	}

	env.RegisterWorkflow(Rehearse)
	env.RegisterWorkflowWithOptions(func(ctx workflow.Context, in ProvisionInput) (ProvisionResult, error) {
		h.mu.Lock()
		h.provisions = append(h.provisions, in)
		h.mu.Unlock()
		return h.provision(ctx, in)
	}, workflow.RegisterOptions{Name: provisionWorkflowType})
	env.RegisterWorkflowWithOptions(func(ctx workflow.Context, in StepInput) (StepResult, error) {
		h.mu.Lock()
		h.steps = append(h.steps, in)
		h.mu.Unlock()
		return h.step(ctx, in)
	}, workflow.RegisterOptions{Name: stepWorkflowType})
	env.RegisterWorkflowWithOptions(func(ctx workflow.Context) (DestroyResult, error) {
		res, err := h.destroy(ctx)
		if ctx.Err() != nil {
			h.mu.Lock()
			h.destroyCut = true
			h.mu.Unlock()
		}
		return res, err
	}, workflow.RegisterOptions{Name: destroyWorkflowType})
	env.RegisterActivityWithOptions(func(ctx context.Context, in wire.VerifyInput) (wire.VerifyResult, error) {
		h.mu.Lock()
		h.verifies = append(h.verifies, in)
		h.mu.Unlock()
		return h.verify(ctx, in)
	}, activity.RegisterOptions{Name: wire.ActVerifyTwin})

	env.SetOnActivityStartedListener(func(info *activity.Info, _ context.Context, _ converter.EncodedValues) {
		h.record(info.ActivityType.Name)
	})
	env.SetOnChildWorkflowStartedListener(func(info *workflow.Info, _ workflow.Context, _ converter.EncodedValues) {
		h.mu.Lock()
		if p := info.ParentWorkflowExecution; p != nil {
			h.parentRuns = append(h.parentRuns, p.RunID)
		}
		h.mu.Unlock()
		h.record("child " + info.WorkflowExecution.ID)
	})
	// The rehearsal runs under its fixed id, as the client starts it.
	env.SetStartWorkflowOptions(client.StartWorkflowOptions{ID: WorkflowRehearse})
	return h
}

func (h *rehearseHarness) record(entry string) {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.events = append(h.events, entry)
}

func (h *rehearseHarness) calls() []string {
	h.mu.Lock()
	defer h.mu.Unlock()
	return append([]string(nil), h.events...)
}

// run executes a rehearsal to completion. A rehearsal returns a result in every case, so a
// workflow error fails the test.
func (h *rehearseHarness) run(in RehearseInput) RehearseResult {
	h.t.Helper()
	h.env.ExecuteWorkflow(Rehearse, in)
	if !h.env.IsWorkflowCompleted() {
		h.t.Fatal("the rehearsal did not complete")
	}
	if err := h.env.GetWorkflowError(); err != nil {
		h.t.Fatalf("the rehearsal failed: %v", err)
	}
	var res RehearseResult
	if err := h.env.GetWorkflowResult(&res); err != nil {
		h.t.Fatal(err)
	}
	return res
}

// rehearsalOf is a rehearsal's input over stages, under the fixture's 1,980 s deadline.
func rehearsalOf(stages ...RehearseStage) RehearseInput {
	return RehearseInput{
		ProposedChange: findings.StageChange{ID: "pc-1", Name: "third link", Branch: rehearsalBranch},
		ResolvedAt:     "2026-10-17T14:02:11.000000Z",
		DeadlineS:      1980,
		CeilingS:       3600,
		Stages:         stages,
		Version:        "0.1.0-test",
	}
}

// stageRef is a stage of pc-1 as the record names it.
func stageRef(label string) *wire.StageRef {
	return &wire.StageRef{ProposedChange: wire.StageChange{ID: "pc-1", Branch: rehearsalBranch}, Label: label, AtSource: "written"}
}

// branchPoint is the branch point the plan refused contract.node.missing, passed over.
func branchPoint() RehearseStage {
	return RehearseStage{Ref: rehearsalBranch + "/branch-point", Label: "branch-point", AtSource: "branch_point",
		Role: rehearsal.RoleRefused, Refused: &RehearseRefusal{Rule: findings.RuleContractNodeMissing,
			Message: "branch defines FylgjaContract but holds no instance of it"}}
}

// baselineStage is the first compiled stage, the baseline, with its provision already
// compiled.
func baselineStage(label string) RehearseStage {
	id := bundleOf(label)
	return RehearseStage{Ref: rehearsalBranch + "/" + label, Label: label, AtSource: "written", Branch: rehearsalBranch,
		At: "2026-10-16T17:25:30.118244+00:00", BundleID: id, BundlePath: "/state/bundles/" + id, Role: rehearsal.RoleBaseline,
		Provision: &ProvisionInput{Source: wire.SourceIntent, Branch: rehearsalBranch, At: "2026-10-16T17:25:30.118244+00:00",
			BundlePath: "/state/bundles/" + id, BundleID: id, ObservedAt: "2026-10-17T14:02:10.000000Z",
			Stage: stageRef(label), Version: "0.1.0-test"},
		WaitS: 120}
}

// rehearsedStage is a compiled stage after the baseline, stepped to from the stage before it.
func rehearsedStage(from, label string) RehearseStage {
	id := bundleOf(label)
	return RehearseStage{Ref: rehearsalBranch + "/" + label, Label: label, AtSource: "written", Branch: rehearsalBranch,
		At: "2026-10-16T17:30:00.000000+00:00", BundleID: id, BundlePath: "/state/bundles/" + id, Role: rehearsal.RoleRehearsed,
		Step: &StepInput{From: wire.StepSide{Stage: stageRef(from), BundleID: bundleOf(from)},
			To:         wire.StepSide{Stage: stageRef(label), BundleID: id, Branch: rehearsalBranch, At: "2026-10-16T17:30:00.000000+00:00"},
			ObservedAt: "2026-10-17T14:02:10.000000Z", ToBundlePath: "/state/bundles/" + id, AllowRestart: true,
			Declared: map[string]string{"n1": "live", "n2": "live", "n3": "live"}, WaitS: 120, Version: "0.1.0-test"},
		WaitS: 120}
}

// bundleOf is a stage's bundle id: one per label, so a mix-up shows.
func bundleOf(label string) string {
	id := []byte(label + "0000000000000000000000000000000000000000000000000000000000000000")[:64]
	for i, b := range id {
		if b < '0' || b > 'f' || (b > '9' && b < 'a') {
			id[i] = 'a'
		}
	}
	return string(id)
}

// The fixture's rehearsal: the branch point refused, the baseline, two marks rehearsed.
func fixtureRehearsal() RehearseInput {
	return rehearsalOf(branchPoint(), baselineStage("seeded"), rehearsedStage("seeded", "third-link"),
		rehearsedStage("third-link", "head"))
}

// built is the baseline's provision ending ready, its record written.
func built(in ProvisionInput) ProvisionResult {
	return ProvisionResult{Outcome: OutcomeReady, BundleID: in.BundleID, ObservedAt: in.ObservedAt, Findings: findings.List{},
		Twin: &wire.TwinRecord{Lab: wire.LabName, BundleID: in.BundleID, RecordedAt: rehearsalRecordedAt, Stage: in.Stage,
			Rehearsal: in.Rehearsal},
		Cleanup: CleanupResult{Teardown: CleanupSkipped, Unstage: CleanupSkipped}}
}

// settled is a wait that settled with nothing failing.
func settled() wire.StepWait {
	return wire.StepWait{Outcome: wire.WaitSettled, BudgetS: 120, Reads: 2, AfterS: 3.2, Failing: []wire.StepFinding{}}
}

// expired is a wait whose budget ran out with failing still failing.
func expired(failing ...wire.StepFinding) wire.StepWait {
	return wire.StepWait{Outcome: wire.WaitExpired, BudgetS: 120, Reads: 58, AfterS: 120.0, Failing: failing}
}

// steppedTo is a step to in's target that ended stepped, with its wait and its counts.
func steppedTo(in StepInput, wait wire.StepWait) StepResult {
	counts := settledCounts()
	return StepResult{Outcome: StepStepped, Findings: findings.List{}, Wait: &wait, WaitCounts: &counts,
		PushPlan: []wire.StepPush{{Node: "n1", Outcome: wire.PushLanded}}}
}

// destroyedClean is the destroy child removing the twin.
func destroyedClean() DestroyResult {
	return DestroyResult{Findings: findings.List{}, Cleanup: CleanupResult{Teardown: CleanupDone, Unstage: CleanupDone,
		Removed: []string{"lab fylgja (3 containers)", "twin directory /state/twin"}}}
}

// neighbor is verify's neighbor finding on n1's ethernet-1/3.
func neighbor(message string) wire.StepFinding {
	return wire.StepFinding{Rule: findings.RuleVerifyNeighbor, Object: "n1:ethernet-1/3", Message: message}
}

// verdicts are the result's stages as "<ref> <verdict>", in order.
func verdicts(res RehearseResult) []string {
	out := make([]string, len(res.Stages))
	for i, s := range res.Stages {
		out[i] = s.Ref + " " + string(s.Verdict)
	}
	return out
}

// wantRehearsal checks the run's outcome, its stages' verdicts in order and the calls it
// made, and that it ended in its destroy, which no cancellation reached.
func wantRehearsal(t *testing.T, h *rehearseHarness, res RehearseResult, outcome string, stages, calls []string) {
	t.Helper()
	if res.Outcome != outcome {
		t.Errorf("outcome %q, want %q", res.Outcome, outcome)
	}
	if got := verdicts(res); !slices.Equal(got, stages) {
		t.Errorf("stages %v\nwant %v", got, stages)
	}
	if got := h.calls(); !slices.Equal(got, calls) {
		t.Errorf("started %v\nwant %v", got, calls)
	}
	if res.Destroy == nil {
		t.Error("no destroy result: the rehearsal must end in its destroy")
	}
	h.mu.Lock()
	cut := h.destroyCut
	h.mu.Unlock()
	if cut {
		t.Error("the destroy child saw its context cancelled; it runs where no cancellation reaches")
	}
	if res.StartedAt == "" || res.EndedAt == "" || res.UsedS < 0 {
		t.Errorf("times %q to %q, %.1fs; want both stamped and the time used", res.StartedAt, res.EndedAt, res.UsedS)
	}
}

const (
	childProvision = "child " + WorkflowProvision
	childStep      = "child " + WorkflowStep
	childDestroy   = "child " + WorkflowDestroy
	verifyTwin     = wire.ActVerifyTwin
)

// Every stage passes: the refused branch point is passed over, the baseline built and waited
// on, the two marks stepped to in order, each with the step the server built, then the twin
// destroyed (FR-001; quickstart §1).
func TestRehearseEveryStagePasses(t *testing.T) {
	h := newRehearseHarness(t)
	in := fixtureRehearsal()

	res := h.run(in)

	wantRehearsal(t, h, res, rehearsal.OutcomeOK,
		[]string{"change-1/branch-point refused", "change-1/seeded baseline", "change-1/third-link passed", "change-1/head passed"},
		[]string{childProvision, verifyTwin, childStep, childStep, childDestroy})
	if res.Reached != "change-1/head" || res.DeadlineHit || len(res.Findings) != 0 {
		t.Errorf("reached %q, deadline hit %v, findings %+v; want the head, no deadline and no findings of the run's own",
			res.Reached, res.DeadlineHit, res.Findings)
	}
	h.mu.Lock()
	steps := slices.Clone(h.steps)
	h.mu.Unlock()
	if len(steps) != 2 || !sameOnTheWire(t, steps[0], *in.Stages[2].Step) || !sameOnTheWire(t, steps[1], *in.Stages[3].Step) {
		t.Errorf("steps given %+v\nwant the server's two, in order", steps)
	}
	if !reflect.DeepEqual(res.Destroy, &DestroyResult{Findings: findings.List{}, Cleanup: destroyedClean().Cleanup}) {
		t.Errorf("destroy %+v, want the child's result", res.Destroy)
	}
	base := res.Stages[1]
	if base.Run == nil || base.Run.WorkflowID != WorkflowProvision || base.Provision == nil || base.Provision.Outcome != OutcomeReady ||
		base.Wait == nil || base.Wait.Outcome != wire.WaitSettled || base.Counts == nil || base.Step != nil {
		t.Errorf("baseline %+v, want its provision run, ready, its settled wait and counts, and no step", base)
	}
	for _, st := range res.Stages[2:] {
		if st.Run == nil || st.Run.WorkflowID != WorkflowStep || st.Step == nil || st.Step.Outcome != StepStepped ||
			st.Wait == nil || st.Counts == nil || len(st.NewFindings) != 0 || st.Provision != nil {
			t.Errorf("stage %s: %+v, want its step run, stepped, its wait and counts, nothing new", st.Ref, st)
		}
	}
	if refused := res.Stages[0]; refused.Run != nil || refused.Step != nil || refused.Provision != nil || refused.Wait != nil {
		t.Errorf("the refused branch point %+v, want nothing run", refused)
	}
}

// A stage that diverges at push fails, the stage after it is not reached and its step never
// started, and the twin is destroyed (FR-002).
func TestRehearseStopsAtAFailedStage(t *testing.T) {
	h := newRehearseHarness(t)
	h.step = func(_ workflow.Context, in StepInput) (StepResult, error) {
		res := steppedTo(in, settled())
		res.Outcome, res.Phase, res.Step = StepDiverged, findings.StepPush, findings.StepPush
		res.PushPlan = []wire.StepPush{{Node: "n3", Outcome: wire.PushLanded}, {Node: "n1", Outcome: wire.PushRefused, Rule: findings.RulePushRefused}}
		return res, nil
	}

	res := h.run(fixtureRehearsal())

	wantRehearsal(t, h, res, rehearsal.OutcomeStageFailed,
		[]string{"change-1/branch-point refused", "change-1/seeded baseline", "change-1/third-link failed", "change-1/head not_reached"},
		[]string{childProvision, verifyTwin, childStep, childDestroy})
	if res.Reached != "change-1/third-link" {
		t.Errorf("reached %q, want the failed stage", res.Reached)
	}
	if st := res.Stages[2]; st.Step == nil || st.Step.Phase != findings.StepPush || len(st.Step.PushPlan) != 2 {
		t.Errorf("failed stage %+v, want the step's diverged result whole", st)
	}
	if st := res.Stages[3]; st.Run != nil || st.Step != nil || st.TookS != 0 {
		t.Errorf("the stage not reached %+v, want nothing run", st)
	}
}

// A finding the baseline's wait did not have fails the stage, naming it (FR-002).
func TestRehearseNewFindingFails(t *testing.T) {
	h := newRehearseHarness(t)
	fresh := neighbor("n1:ethernet-1/3 sees no neighbor; want n3:ethernet-1/3")
	h.step = func(_ workflow.Context, in StepInput) (StepResult, error) { return steppedTo(in, expired(fresh)), nil }

	res := h.run(fixtureRehearsal())

	wantRehearsal(t, h, res, rehearsal.OutcomeStageFailed,
		[]string{"change-1/branch-point refused", "change-1/seeded baseline", "change-1/third-link failed", "change-1/head not_reached"},
		[]string{childProvision, verifyTwin, childStep, childDestroy})
	if st := res.Stages[2]; !slices.Equal(st.NewFindings, []wire.StepFinding{fresh}) || st.Wait == nil || st.Wait.Outcome != wire.WaitExpired {
		t.Errorf("failed stage %+v, want the new finding named and its wait carried", st)
	}
}

// A finding the baseline's wait had, by rule and object, fails nothing when a later stage
// has it again, whatever its message says now; the baseline carries it (FR-002, SC-004).
func TestRehearseBaselineFindingsFailNothing(t *testing.T) {
	h := newRehearseHarness(t)
	had := neighbor("n1:ethernet-1/3 sees no neighbor")
	h.verify = func(_ context.Context, in wire.VerifyInput) (wire.VerifyResult, error) {
		return wire.VerifyResult{Wait: expired(had)}, nil
	}
	h.step = func(_ workflow.Context, in StepInput) (StepResult, error) {
		return steppedTo(in, expired(neighbor("n1:ethernet-1/3 sees n2:ethernet-1/1; want n3:ethernet-1/3"))), nil
	}

	res := h.run(fixtureRehearsal())

	wantRehearsal(t, h, res, rehearsal.OutcomeOK,
		[]string{"change-1/branch-point refused", "change-1/seeded baseline", "change-1/third-link passed", "change-1/head passed"},
		[]string{childProvision, verifyTwin, childStep, childStep, childDestroy})
	if base := res.Stages[1]; base.Wait == nil || !slices.Equal(base.Wait.Failing, []wire.StepFinding{had}) {
		t.Errorf("baseline %+v, want its wait's finding carried as the baseline's", base)
	}
	for _, st := range res.Stages[2:] {
		if len(st.NewFindings) != 0 {
			t.Errorf("stage %s: new %+v, want none", st.Ref, st.NewFindings)
		}
	}
}

// A baseline that is not built ends the rehearsal baseline_failed: no wait and no step, every
// later stage not reached, and the destroy still runs (FR-005; the spec's edge case).
func TestRehearseBaselineNotBuilt(t *testing.T) {
	h := newRehearseHarness(t)
	h.provision = func(_ workflow.Context, in ProvisionInput) (ProvisionResult, error) {
		return ProvisionResult{Outcome: OutcomeFailed, BundleID: in.BundleID, Step: findings.StepReadiness,
			Findings: findings.List{{Severity: findings.Rejection, Rule: findings.RuleReadinessTimeout, Step: findings.StepReadiness,
				Object: "n1", Message: "n1 did not answer within 60s"}},
			Cleanup: CleanupResult{Teardown: CleanupDone, Unstage: CleanupDone, Removed: []string{"lab fylgja (3 containers)"}}}, nil
	}
	h.destroy = func(workflow.Context) (DestroyResult, error) {
		return DestroyResult{Findings: findings.List{}, Cleanup: CleanupResult{Teardown: CleanupNothing, Unstage: CleanupNothing}}, nil
	}

	res := h.run(fixtureRehearsal())

	wantRehearsal(t, h, res, rehearsal.OutcomeBaselineFailed,
		[]string{"change-1/branch-point refused", "change-1/seeded error", "change-1/third-link not_reached", "change-1/head not_reached"},
		[]string{childProvision, childDestroy})
	if base := res.Stages[1]; base.Provision == nil || base.Provision.Outcome != OutcomeFailed || len(base.Provision.Findings) != 1 ||
		base.Wait != nil {
		t.Errorf("baseline %+v, want the provision's failed result with its finding, and no wait", base)
	}
	if res.Destroy == nil || res.Destroy.Cleanup.Teardown != CleanupNothing {
		t.Errorf("destroy %+v, want the destroy run, finding nothing", res.Destroy)
	}
}

// A baseline whose provision ended other than failed did not try to build it and clean up:
// a step that could not run (error), a refusal before the host was touched (rejected), or a
// cancellation the run did not ask for. Each is stage_error, which the server makes error,
// exit 2, and never baseline_failed, which FR-009 keeps for a build that cleaned up (T081).
// The destroy still runs.
func TestRehearseBaselineEndedOtherwiseIsError(t *testing.T) {
	for _, outcome := range []string{OutcomeError, OutcomeRejected, OutcomeCancelled} {
		t.Run(outcome, func(t *testing.T) {
			h := newRehearseHarness(t)
			h.provision = func(_ workflow.Context, in ProvisionInput) (ProvisionResult, error) {
				return ProvisionResult{Outcome: outcome, BundleID: in.BundleID, Step: findings.StepHostCheck,
					Findings: findings.List{{Severity: findings.Rejection, Rule: findings.RuleOperationFailed, Step: findings.StepHostCheck,
						Object: "lab fylgja", Message: "the host check could not run"}},
					Cleanup: CleanupResult{Teardown: CleanupSkipped, Unstage: CleanupSkipped}}, nil
			}

			res := h.run(fixtureRehearsal())

			wantRehearsal(t, h, res, rehearsal.OutcomeStageError,
				[]string{"change-1/branch-point refused", "change-1/seeded error", "change-1/third-link not_reached", "change-1/head not_reached"},
				[]string{childProvision, childDestroy})
			if base := res.Stages[1]; base.Provision == nil || base.Provision.Outcome != outcome || base.Wait != nil {
				t.Errorf("baseline %+v, want the provision's %s result and no wait", base, outcome)
			}
		})
	}
}

// A step its own locks reject is error, not a verdict on the change: the rehearsal stops
// there and ends stage_error after its destroy (FR-002).
func TestRehearseStepRejectedIsError(t *testing.T) {
	h := newRehearseHarness(t)
	h.step = func(workflow.Context, StepInput) (StepResult, error) {
		return StepResult{Outcome: OutcomeRejected, Step: findings.StepCompare, Findings: findings.List{{Severity: findings.Rejection,
			Rule: findings.RuleStepNodeUnapplied, Step: findings.StepCompare, Object: "n1", Message: "the plan does not recreate n1"}}}, nil
	}

	res := h.run(fixtureRehearsal())

	wantRehearsal(t, h, res, rehearsal.OutcomeStageError,
		[]string{"change-1/branch-point refused", "change-1/seeded baseline", "change-1/third-link error", "change-1/head not_reached"},
		[]string{childProvision, verifyTwin, childStep, childDestroy})
	if st := res.Stages[2]; st.Step == nil || st.Step.Outcome != OutcomeRejected || len(st.Step.Findings) != 1 {
		t.Errorf("stage %+v, want the step's rejection carried", st)
	}
}

// A wait that could not read every node is error: nothing can be compared (FR-002). The
// baseline's own wait incomplete is error too, since no later stage could be compared with
// it, and the run stops at the baseline.
func TestRehearseWaitIncompleteIsError(t *testing.T) {
	unread := wire.StepFinding{Rule: findings.RuleOperationFailed, Object: "n2", Message: "n2 could not be read"}
	incomplete := wire.StepWait{Outcome: wire.WaitIncomplete, BudgetS: 120, Reads: 58, AfterS: 120.3, Failing: []wire.StepFinding{unread}}

	t.Run("a rehearsed stage's", func(t *testing.T) {
		h := newRehearseHarness(t)
		h.step = func(_ workflow.Context, in StepInput) (StepResult, error) { return steppedTo(in, incomplete), nil }

		res := h.run(fixtureRehearsal())

		wantRehearsal(t, h, res, rehearsal.OutcomeStageError,
			[]string{"change-1/branch-point refused", "change-1/seeded baseline", "change-1/third-link error", "change-1/head not_reached"},
			[]string{childProvision, verifyTwin, childStep, childDestroy})
	})

	t.Run("the baseline's", func(t *testing.T) {
		h := newRehearseHarness(t)
		h.verify = func(context.Context, wire.VerifyInput) (wire.VerifyResult, error) {
			return wire.VerifyResult{Wait: incomplete}, nil
		}

		res := h.run(fixtureRehearsal())

		wantRehearsal(t, h, res, rehearsal.OutcomeStageError,
			[]string{"change-1/branch-point refused", "change-1/seeded error", "change-1/third-link not_reached", "change-1/head not_reached"},
			[]string{childProvision, verifyTwin, childDestroy})
		if base := res.Stages[1]; base.Wait == nil || base.Wait.Outcome != wire.WaitIncomplete || base.Provision == nil {
			t.Errorf("baseline %+v, want its ready provision and its incomplete wait", base)
		}
	})

	t.Run("the baseline's failing outright", func(t *testing.T) {
		h := newRehearseHarness(t)
		h.verify = func(context.Context, wire.VerifyInput) (wire.VerifyResult, error) {
			return wire.VerifyResult{}, temporal.NewNonRetryableApplicationError("the twin directory could not be read",
				findings.RuleOperationFailed, nil)
		}

		res := h.run(fixtureRehearsal())

		wantRehearsal(t, h, res, rehearsal.OutcomeStageError,
			[]string{"change-1/branch-point refused", "change-1/seeded error", "change-1/third-link not_reached", "change-1/head not_reached"},
			[]string{childProvision, verifyTwin, childDestroy})
		base := res.Stages[1]
		if base.Wait == nil || base.Wait.Outcome != wire.WaitIncomplete || len(base.Wait.Failing) != 1 ||
			base.Wait.Failing[0].Rule != findings.RuleOperationFailed || base.Wait.From != rehearsalRecordedAt {
			t.Errorf("baseline wait %+v, want incomplete from the record's time with the failure's operation.failed", base.Wait)
		}
	})
}

// The deadline passing mid-step cancels the step child, which records diverged, ends the
// stage error and the run cut, and the destroy follows; the stage after it is not reached
// (FR-006; the spec's edge case).
func TestRehearseDeadlineCutsAStepAndDestroys(t *testing.T) {
	h := newRehearseHarness(t)
	var cutAt time.Duration
	h.step = func(ctx workflow.Context, in StepInput) (StepResult, error) {
		began := workflow.Now(ctx)
		_ = workflow.Sleep(ctx, time.Hour)
		if ctx.Err() == nil {
			return StepResult{}, errors.New("the deadline never reached the step child")
		}
		cutAt = workflow.Now(ctx).Sub(began)
		return StepResult{Outcome: OutcomeCancelled, Phase: findings.StepPush, Step: findings.StepPush, Findings: findings.List{}}, nil
	}

	res := h.run(fixtureRehearsal())

	wantRehearsal(t, h, res, rehearsal.OutcomeCut,
		[]string{"change-1/branch-point refused", "change-1/seeded baseline", "change-1/third-link error", "change-1/head not_reached"},
		[]string{childProvision, verifyTwin, childStep, childDestroy})
	if !res.DeadlineHit || res.Reached != "change-1/third-link" {
		t.Errorf("deadline hit %v at %q, want hit at the stage in progress", res.DeadlineHit, res.Reached)
	}
	if cutAt <= 0 || cutAt >= time.Hour || res.UsedS < 1980 || res.UsedS > 1981 {
		t.Errorf("the step was cut after %s and the run used %.1fs; want the step cut before its hour and the run ending at its 1980s deadline",
			cutAt, res.UsedS)
	}
	if st := res.Stages[2]; st.Step == nil || st.Step.Phase != findings.StepPush || st.TookS <= 0 {
		t.Errorf("cut stage %+v, want the step's diverged result and its time", st)
	}
}

// A stage the deadline cut is error whatever its child says: a step that finished stepped and
// settled although its cancellation had arrived is still the stage in progress when the
// deadline passed, and the run is cut there (FR-002).
func TestRehearseDeadlineCutsAStepThatFinishedAnyway(t *testing.T) {
	h := newRehearseHarness(t)
	h.step = func(ctx workflow.Context, in StepInput) (StepResult, error) {
		_ = workflow.Sleep(ctx, time.Hour)
		return steppedTo(in, settled()), nil
	}

	res := h.run(fixtureRehearsal())

	wantRehearsal(t, h, res, rehearsal.OutcomeCut,
		[]string{"change-1/branch-point refused", "change-1/seeded baseline", "change-1/third-link error", "change-1/head not_reached"},
		[]string{childProvision, verifyTwin, childStep, childDestroy})
	if st := res.Stages[2]; st.Step == nil || st.Step.Outcome != StepStepped || st.Wait == nil || st.Wait.Outcome != wire.WaitSettled {
		t.Errorf("cut stage %+v, want the step's own result carried beside the verdict", st)
	}
}

// The deadline passing while the baseline is built cancels its provision, which cleans up;
// no wait and no step run, and the destroy follows.
func TestRehearseDeadlineDuringTheBaseline(t *testing.T) {
	h := newRehearseHarness(t)
	h.provision = func(ctx workflow.Context, in ProvisionInput) (ProvisionResult, error) {
		_ = workflow.Sleep(ctx, time.Hour)
		if ctx.Err() == nil {
			return ProvisionResult{}, errors.New("the deadline never reached the provision child")
		}
		return ProvisionResult{Outcome: OutcomeCancelled, BundleID: in.BundleID, Step: findings.StepDeploy, Findings: findings.List{},
			Cleanup: CleanupResult{Teardown: CleanupDone, Unstage: CleanupDone}}, nil
	}

	res := h.run(fixtureRehearsal())

	wantRehearsal(t, h, res, rehearsal.OutcomeCut,
		[]string{"change-1/branch-point refused", "change-1/seeded error", "change-1/third-link not_reached", "change-1/head not_reached"},
		[]string{childProvision, childDestroy})
	if !res.DeadlineHit {
		t.Error("the deadline was not hit")
	}
	if base := res.Stages[1]; base.Provision == nil || base.Provision.Outcome != OutcomeCancelled || base.Wait != nil {
		t.Errorf("baseline %+v, want its provision's cancelled result and no wait", base)
	}
}

// The deadline passing during a wait ends the stage error and the run cut, and the destroy
// follows: the baseline's own wait, the one activity the rehearsal runs, cancelled where it
// waits; and a rehearsed stage's, inside its step child, whose wait ends cancelled.
func TestRehearseDeadlineDuringAWait(t *testing.T) {
	t.Run("the baseline's", func(t *testing.T) {
		h := newRehearseHarness(t)
		// The suite moves a timer only on the wall clock while an activity runs, so this
		// deadline is a second.
		in := fixtureRehearsal()
		in.DeadlineS = 1
		reached := make(chan struct{})
		var once sync.Once
		h.env.SetOnActivityCanceledListener(func(*activity.Info) { once.Do(func() { close(reached) }) })
		h.verify = func(ctx context.Context, _ wire.VerifyInput) (wire.VerifyResult, error) {
			select {
			case <-reached:
			case <-ctx.Done():
			case <-time.After(10 * time.Second):
				return wire.VerifyResult{}, errors.New("the deadline never cut the wait")
			}
			return wire.VerifyResult{}, context.Canceled
		}

		res := h.run(in)

		wantRehearsal(t, h, res, rehearsal.OutcomeCut,
			[]string{"change-1/branch-point refused", "change-1/seeded error", "change-1/third-link not_reached", "change-1/head not_reached"},
			[]string{childProvision, verifyTwin, childDestroy})
		if !res.DeadlineHit {
			t.Error("the deadline was not hit")
		}
		if base := res.Stages[1]; base.Provision == nil || base.Provision.Outcome != OutcomeReady || base.Wait != nil || len(res.Findings) != 0 {
			t.Errorf("baseline %+v, findings %+v; want its ready provision, no wait and no finding of the run's own", base, res.Findings)
		}
	})

	t.Run("a rehearsed stage's", func(t *testing.T) {
		h := newRehearseHarness(t)
		h.step = func(ctx workflow.Context, in StepInput) (StepResult, error) {
			_ = workflow.Sleep(ctx, time.Hour)
			if ctx.Err() == nil {
				return StepResult{}, errors.New("the deadline never reached the step child")
			}
			// The record is written; the wait after it ends cancelled.
			res := steppedTo(in, wire.StepWait{Outcome: wire.WaitCancelled, BudgetS: 120, Reads: 7, AfterS: 12.4, Failing: []wire.StepFinding{}})
			res.WaitCounts = nil
			return res, nil
		}

		res := h.run(fixtureRehearsal())

		wantRehearsal(t, h, res, rehearsal.OutcomeCut,
			[]string{"change-1/branch-point refused", "change-1/seeded baseline", "change-1/third-link error", "change-1/head not_reached"},
			[]string{childProvision, verifyTwin, childStep, childDestroy})
		if st := res.Stages[2]; !res.DeadlineHit || st.Wait == nil || st.Wait.Outcome != wire.WaitCancelled {
			t.Errorf("deadline hit %v, stage %+v; want hit and the cancelled wait carried", res.DeadlineHit, st)
		}
	})
}

// The run's own cancellation, the operator's interrupt or twin destroy, cancels the step child
// in progress as the deadline does, ends the run cancelled rather than cut, and the destroy
// still runs to its end.
func TestRehearseCancelledDestroys(t *testing.T) {
	h := newRehearseHarness(t)
	h.step = func(ctx workflow.Context, in StepInput) (StepResult, error) {
		_ = workflow.Sleep(ctx, time.Hour)
		if ctx.Err() == nil {
			return StepResult{}, errors.New("the cancellation never reached the step child")
		}
		return StepResult{Outcome: OutcomeCancelled, Phase: findings.StepReconcile, Step: findings.StepReconcile, Findings: findings.List{}}, nil
	}
	h.destroy = func(ctx workflow.Context) (DestroyResult, error) {
		// As M2's Destroy, which honours a cancel between its teardown and its unstage: a
		// cancellation that reached it would leave the twin directory unchecked.
		_ = workflow.Sleep(ctx, time.Minute)
		if ctx.Err() != nil {
			return DestroyResult{Findings: findings.List{}, Cleanup: CleanupResult{Teardown: CleanupDone, Unstage: CleanupSkipped,
				Remaining: []string{"twin directory (not checked: the destroy run was cancelled)"}}}, nil
		}
		return destroyedClean(), nil
	}
	h.env.RegisterDelayedCallback(h.env.CancelWorkflow, time.Minute)

	res := h.run(fixtureRehearsal())

	wantRehearsal(t, h, res, rehearsal.OutcomeCancelled,
		[]string{"change-1/branch-point refused", "change-1/seeded baseline", "change-1/third-link error", "change-1/head not_reached"},
		[]string{childProvision, verifyTwin, childStep, childDestroy})
	if res.DeadlineHit {
		t.Error("the deadline was hit; the run's own cancellation is not the deadline")
	}
	if res.Destroy == nil || len(res.Destroy.Cleanup.Remaining) != 0 || res.Destroy.Cleanup.Unstage != CleanupDone {
		t.Errorf("destroy %+v, want it run to its end, nothing remaining", res.Destroy)
	}
}

// The destroy leaving something does not change how the stages went: the outcome stands, and
// the destroy's result carries what remains (FR-005; status unclean is the server's).
func TestRehearseDestroyUnclean(t *testing.T) {
	h := newRehearseHarness(t)
	left := DestroyResult{Findings: findings.List{{Severity: findings.Rejection, Rule: findings.RuleCleanupIncomplete,
		Step: findings.StepTeardown, Object: "lab fylgja", Message: "clab destroy exited 1"}},
		Cleanup: CleanupResult{Teardown: CleanupFailed, Unstage: CleanupDone, Remaining: []string{"lab fylgja (3 containers)"}}}
	h.destroy = func(workflow.Context) (DestroyResult, error) { return left, nil }

	res := h.run(fixtureRehearsal())

	wantRehearsal(t, h, res, rehearsal.OutcomeOK,
		[]string{"change-1/branch-point refused", "change-1/seeded baseline", "change-1/third-link passed", "change-1/head passed"},
		[]string{childProvision, verifyTwin, childStep, childStep, childDestroy})
	if !reflect.DeepEqual(res.Destroy, &left) {
		t.Errorf("destroy %+v, want the child's result whole: %+v", res.Destroy, left)
	}
}

// One stage alone compiled: it is the baseline, built, verified and destroyed, and the run
// is ok when its wait is (FR-003's last sentence).
func TestRehearseOneStage(t *testing.T) {
	h := newRehearseHarness(t)

	res := h.run(rehearsalOf(branchPoint(), baselineStage("head")))

	wantRehearsal(t, h, res, rehearsal.OutcomeOK,
		[]string{"change-1/branch-point refused", "change-1/head baseline"},
		[]string{childProvision, verifyTwin, childDestroy})
	if res.Reached != "change-1/head" {
		t.Errorf("reached %q, want the baseline", res.Reached)
	}
}

// The baseline's provision child is the server's input, already compiled, with this run
// named as its rehearsal and following stopped, so its record names the run (twin.json 7);
// its wait reads from the record's time, under the stage's budget, as this run, which the
// record does not name, so the wait is written into no record (R-07).
func TestRehearseRecordNamesTheRun(t *testing.T) {
	h := newRehearseHarness(t)
	in := fixtureRehearsal()

	h.run(in)

	h.mu.Lock()
	defer h.mu.Unlock()
	if len(h.provisions) != 1 || len(h.parentRuns) == 0 || len(h.verifies) != 1 {
		t.Fatalf("provisions %+v, parents %v, waits %+v; want one of each", h.provisions, h.parentRuns, h.verifies)
	}
	self := h.parentRuns[0]
	want := *in.Stages[1].Provision
	want.Rehearsal = &wire.RehearsalRef{WorkflowID: WorkflowRehearse, RunID: self}
	want.StopFollowing = true
	if got := h.provisions[0]; !reflect.DeepEqual(got, want) {
		t.Errorf("the provision child was given %+v\nwant the server's input naming this run: %+v", got, want)
	}
	if in.Stages[1].Provision.Rehearsal != nil {
		t.Error("the input's own provision was changed")
	}
	if v := h.verifies[0]; v != (wire.VerifyInput{RunID: self, From: rehearsalRecordedAt, BudgetS: 120}) {
		t.Errorf("the baseline's wait %+v, want this run's, from the record's time, for 120s", v)
	}
	for _, p := range h.parentRuns {
		if p != self {
			t.Errorf("children of runs %v, want every one this run's", h.parentRuns)
			break
		}
	}
}

// A child refused because a run holds its id is error, filing run.in_flight naming it, and
// the rehearsal still destroys. The suite refuses a child whose id a running workflow holds,
// so the rehearsal itself runs under fylgja-step here.
func TestRehearseChildRefusedIsError(t *testing.T) {
	h := newRehearseHarness(t)
	h.env.SetStartWorkflowOptions(client.StartWorkflowOptions{ID: WorkflowStep})

	res := h.run(fixtureRehearsal())

	wantRehearsal(t, h, res, rehearsal.OutcomeStageError,
		[]string{"change-1/branch-point refused", "change-1/seeded baseline", "change-1/third-link error", "change-1/head not_reached"},
		[]string{childProvision, verifyTwin, childDestroy})
	wantRules(t, res.Findings, [2]string{findings.RuleRunInFlight, findings.StepStart})
	if f := res.Findings[0]; f.Object != WorkflowStep || f.Severity != findings.Rejection {
		t.Errorf("run.in_flight = %+v, want a rejection naming fylgja-step", f)
	}
	if st := res.Stages[2]; st.Run != nil || st.Step != nil {
		t.Errorf("stage %+v, want no run", st)
	}
}

// A baseline whose provision cannot start because another run holds its id touched nothing:
// the rehearsal is rejected, filing run.in_flight naming the held id, every stage after the
// passed-over branch point not reached, and it starts no destroy, which would tear down the
// other run's lab (FR-007, FR-009; T078). The rehearsal runs under fylgja-provision here, for
// the suite to refuse the child.
func TestRehearseBaselineHeldTouchesNothing(t *testing.T) {
	h := newRehearseHarness(t)
	h.env.SetStartWorkflowOptions(client.StartWorkflowOptions{ID: WorkflowProvision})

	res := h.run(fixtureRehearsal())

	if res.Outcome != rehearsal.OutcomeRejected {
		t.Errorf("outcome %q, want %q", res.Outcome, rehearsal.OutcomeRejected)
	}
	if got, want := verdicts(res), []string{"change-1/branch-point refused", "change-1/seeded not_reached",
		"change-1/third-link not_reached", "change-1/head not_reached"}; !slices.Equal(got, want) {
		t.Errorf("stages %v\nwant %v", got, want)
	}
	if got := h.calls(); len(got) != 0 {
		t.Errorf("started %v, want nothing: no child ran, and no destroy", got)
	}
	if res.Destroy != nil {
		t.Errorf("destroy %+v, want none: the run touched nothing", res.Destroy)
	}
	wantRules(t, res.Findings, [2]string{findings.RuleRunInFlight, findings.StepProvision})
	if f := res.Findings[0]; f.Object != WorkflowProvision || f.Severity != findings.Rejection ||
		!strings.Contains(f.Message, "touched nothing and ran no destroy") {
		t.Errorf("run.in_flight = %+v, want a rejection naming fylgja-provision and saying nothing was touched", f)
	}
	if res.DeadlineHit || res.StartedAt == "" || res.EndedAt == "" {
		t.Errorf("deadline hit %v, times %q to %q", res.DeadlineHit, res.StartedAt, res.EndedAt)
	}
}

// A destroy that cannot start checks nothing, and says so under cleanup.incomplete, with the
// lab and the twin directory remaining unchecked: the rehearsal never claims a host it did not
// look at. The rehearsal runs under fylgja-destroy here, for the suite to refuse the child.
func TestRehearseDestroyNotStartedIsUnclean(t *testing.T) {
	h := newRehearseHarness(t)
	h.env.SetStartWorkflowOptions(client.StartWorkflowOptions{ID: WorkflowDestroy})

	res := h.run(rehearsalOf(branchPoint(), baselineStage("head")))

	if res.Outcome != rehearsal.OutcomeOK || res.Destroy == nil || len(res.Destroy.Cleanup.Remaining) != 1 ||
		res.Destroy.Cleanup.Teardown != CleanupSkipped || res.Destroy.Cleanup.Unstage != CleanupSkipped {
		t.Fatalf("outcome %q, destroy %+v; want ok, and the destroy checking nothing, its remaining named", res.Outcome, res.Destroy)
	}
	wantRules(t, res.Destroy.Findings, [2]string{findings.RuleCleanupIncomplete, findings.StepDestroy})
	if got := h.calls(); slices.Contains(got, childDestroy) {
		t.Errorf("started %v, want no destroy child", got)
	}
}

// The deadline is the server's; one it did not give falls back to the ceiling, then to
// Fylgja's own, so no rehearsal runs without one.
func TestRehearseDeadlineOf(t *testing.T) {
	for _, c := range []struct {
		deadlineS, ceilingS int
		want                time.Duration
	}{
		{1980, 3600, 1980 * time.Second},
		{0, 3000, 3000 * time.Second},
		{0, 0, rehearsal.Ceiling},
	} {
		if got := deadlineOf(RehearseInput{DeadlineS: c.deadlineS, CeilingS: c.ceilingS}); got != c.want {
			t.Errorf("deadline %d, ceiling %d: %s, want %s", c.deadlineS, c.ceilingS, got, c.want)
		}
	}
}

// A child that closed without a result, failed or terminated, is operation.failed on its run
// and its stage error, the run stage_error, and the destroy still runs (FR-028; T086): the
// baseline's provision and a rehearsed stage's step alike.
func TestRehearseChildClosedWithoutAResult(t *testing.T) {
	failure := temporal.NewNonRetryableApplicationError("the child's history could not be replayed", "panic", nil)
	for _, c := range []struct {
		name   string
		set    func(h *rehearseHarness)
		stages []string
		calls  []string
		step   string
		at     int
	}{
		{"the baseline's provision", func(h *rehearseHarness) {
			h.provision = func(workflow.Context, ProvisionInput) (ProvisionResult, error) { return ProvisionResult{}, failure }
		}, []string{"change-1/branch-point refused", "change-1/seeded error", "change-1/third-link not_reached", "change-1/head not_reached"},
			[]string{childProvision, childDestroy}, findings.StepProvision, 1},
		{"a rehearsed stage's step", func(h *rehearseHarness) {
			h.step = func(workflow.Context, StepInput) (StepResult, error) { return StepResult{}, failure }
		}, []string{"change-1/branch-point refused", "change-1/seeded baseline", "change-1/third-link error", "change-1/head not_reached"},
			[]string{childProvision, verifyTwin, childStep, childDestroy}, findings.StepStart, 2},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := newRehearseHarness(t)
			c.set(h)

			res := h.run(fixtureRehearsal())

			wantRehearsal(t, h, res, rehearsal.OutcomeStageError, c.stages, c.calls)
			wantRules(t, res.Findings, [2]string{findings.RuleOperationFailed, c.step})
			st := res.Stages[c.at]
			if st.Run == nil || res.Findings[0].Object != st.Run.RunID || st.Provision != nil || st.Step != nil {
				t.Errorf("stage %+v, finding %+v; want the child's run named, and no result", st, res.Findings[0])
			}
		})
	}
}

// A destroy that started and closed without a result checked nothing it can vouch for: its
// result says so under cleanup.incomplete naming its run, the lab and the twin directory
// remaining unchecked, and the stages' outcome stands (T086).
func TestRehearseDestroyClosedWithoutAResultIsUnclean(t *testing.T) {
	h := newRehearseHarness(t)
	h.destroy = func(workflow.Context) (DestroyResult, error) {
		return DestroyResult{}, temporal.NewNonRetryableApplicationError("terminated", "terminated", nil)
	}

	res := h.run(fixtureRehearsal())

	if res.Outcome != rehearsal.OutcomeOK || res.Destroy == nil || len(res.Destroy.Cleanup.Remaining) != 1 ||
		res.Destroy.Cleanup.Teardown != CleanupSkipped || res.Destroy.Cleanup.Unstage != CleanupSkipped {
		t.Fatalf("outcome %q, destroy %+v; want ok, and the destroy checking nothing, its remaining named", res.Outcome, res.Destroy)
	}
	wantRules(t, res.Destroy.Findings, [2]string{findings.RuleCleanupIncomplete, findings.StepDestroy})
	if f := res.Destroy.Findings[0]; f.Object == WorkflowDestroy || !strings.Contains(f.Message, "run "+f.Object+" closed without a result") {
		t.Errorf("cleanup.incomplete = %+v, want it naming the destroy's run", f)
	}
	if got := h.calls(); !slices.Contains(got, childDestroy) {
		t.Errorf("started %v, want the destroy child", got)
	}
}

// The run's own cancellation during the baseline's provision, during the baseline's wait, and
// before its first child started each end the run cancelled, the baseline error, every later
// stage not reached and nothing of the run's own filed, and the destroy runs where no
// cancellation reaches it (FR-005, FR-028; T086).
func TestRehearseCancelledBeforeTheBaselineIsBuilt(t *testing.T) {
	notBuilt := []string{"change-1/branch-point refused", "change-1/seeded error", "change-1/third-link not_reached", "change-1/head not_reached"}
	t.Run("during the baseline's provision", func(t *testing.T) {
		h := newRehearseHarness(t)
		h.provision = func(ctx workflow.Context, in ProvisionInput) (ProvisionResult, error) {
			_ = workflow.Sleep(ctx, time.Hour)
			if ctx.Err() == nil {
				return ProvisionResult{}, errors.New("the cancellation never reached the provision child")
			}
			return ProvisionResult{Outcome: OutcomeCancelled, BundleID: in.BundleID, Step: findings.StepDeploy, Findings: findings.List{},
				Cleanup: CleanupResult{Teardown: CleanupDone, Unstage: CleanupDone}}, nil
		}
		h.env.RegisterDelayedCallback(h.env.CancelWorkflow, time.Minute)

		res := h.run(fixtureRehearsal())

		wantRehearsal(t, h, res, rehearsal.OutcomeCancelled, notBuilt, []string{childProvision, childDestroy})
		if base := res.Stages[1]; base.Provision == nil || base.Provision.Outcome != OutcomeCancelled || base.Wait != nil ||
			len(res.Findings) != 0 || res.DeadlineHit {
			t.Errorf("baseline %+v, findings %+v; want its cancelled provision, no wait and nothing filed", base, res.Findings)
		}
	})

	t.Run("during the baseline's wait", func(t *testing.T) {
		h := newRehearseHarness(t)
		reached := make(chan struct{})
		var once sync.Once
		h.env.SetOnActivityCanceledListener(func(*activity.Info) { once.Do(func() { close(reached) }) })
		h.verify = func(ctx context.Context, _ wire.VerifyInput) (wire.VerifyResult, error) {
			select {
			case <-reached:
			case <-ctx.Done():
			case <-time.After(10 * time.Second):
				return wire.VerifyResult{}, errors.New("the cancellation never reached the wait")
			}
			return wire.VerifyResult{}, context.Canceled
		}
		// The suite moves a timer only on the wall clock while an activity runs.
		h.env.RegisterDelayedCallback(h.env.CancelWorkflow, time.Second)

		res := h.run(fixtureRehearsal())

		wantRehearsal(t, h, res, rehearsal.OutcomeCancelled, notBuilt, []string{childProvision, verifyTwin, childDestroy})
		if base := res.Stages[1]; base.Provision == nil || base.Provision.Outcome != OutcomeReady || base.Wait != nil ||
			len(res.Findings) != 0 || res.DeadlineHit {
			t.Errorf("baseline %+v, findings %+v; want its ready provision, no wait and nothing filed", base, res.Findings)
		}
	})

	t.Run("before the first child started", func(t *testing.T) {
		h := newRehearseHarness(t)
		h.env.RegisterDelayedCallback(h.env.CancelWorkflow, 0)

		res := h.run(fixtureRehearsal())

		wantRehearsal(t, h, res, rehearsal.OutcomeCancelled, notBuilt, []string{childDestroy})
		if base := res.Stages[1]; base.Run != nil || base.Provision != nil || len(res.Findings) != 0 {
			t.Errorf("baseline %+v, findings %+v; want no child and nothing filed", base, res.Findings)
		}
	})
}

// A child the deadline cut that then closes without a result files nothing of the run's own:
// the outcome, cut, says why, the stage is error and the destroy follows (T086).
func TestRehearseCutChildClosedWithoutAResultFilesNothing(t *testing.T) {
	h := newRehearseHarness(t)
	h.step = func(ctx workflow.Context, in StepInput) (StepResult, error) {
		_ = workflow.Sleep(ctx, time.Hour)
		return StepResult{}, temporal.NewCanceledError("the step child was cancelled")
	}

	res := h.run(fixtureRehearsal())

	wantRehearsal(t, h, res, rehearsal.OutcomeCut,
		[]string{"change-1/branch-point refused", "change-1/seeded baseline", "change-1/third-link error", "change-1/head not_reached"},
		[]string{childProvision, verifyTwin, childStep, childDestroy})
	if st := res.Stages[2]; st.Run == nil || st.Step != nil || len(res.Findings) != 0 || !res.DeadlineHit {
		t.Errorf("stage %+v, findings %+v; want its run, no result and nothing filed", st, res.Findings)
	}
}
