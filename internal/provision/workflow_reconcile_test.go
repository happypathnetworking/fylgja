package provision

import (
	"context"
	"errors"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/mock"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/converter"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/testsuite"
	"go.temporal.io/sdk/workflow"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// The two bundle ids a check compares: the twin's, and a changed branch's.
const (
	twinBundleID    = "893b6392da4f1de868e74e418d90f3d5982ecc06ffa1dc39a391d717a81997ad"
	changedBundleID = "c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00c0ffee00"
	checkBranch     = "fylgja-fixture"
	checkObservedAt = "2026-09-16T19:10:00.000000Z"
)

// reconcileHarness is a workflow test environment for Reconcile: every activity registered
// by name and answered by mocks, and the two children registered as stubs under the names
// the worker registers Destroy and Provision by, so a check's rebuild runs no real run. It
// records, in order, each activity started and each child started by its workflow id.
type reconcileHarness struct {
	t   *testing.T
	env *testsuite.TestWorkflowEnvironment

	// destroy and provision are the children's bodies; the defaults end clean and ready.
	destroy   func(ctx workflow.Context) (DestroyResult, error)
	provision func(ctx workflow.Context, in ProvisionInput) (ProvisionResult, error)

	mu        sync.Mutex
	events    []string
	childRuns map[string]string // workflow id → run id
	children  []ProvisionInput  // what each provision child was given
}

func newReconcileHarness(t *testing.T) *reconcileHarness {
	t.Helper()
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	h := &reconcileHarness{t: t, env: env, childRuns: map[string]string{}}
	h.destroy = func(workflow.Context) (DestroyResult, error) {
		return DestroyResult{Findings: findings.List{}, Cleanup: CleanupResult{Teardown: CleanupDone, Unstage: CleanupDone,
			Removed: []string{"lab fylgja (3 containers)", "twin directory /state/twin"}}}, nil
	}
	h.provision = func(_ workflow.Context, in ProvisionInput) (ProvisionResult, error) {
		return ProvisionResult{Outcome: OutcomeReady, BundleID: in.BundleID, ObservedAt: in.ObservedAt, Findings: findings.List{},
			Cleanup: CleanupResult{Teardown: CleanupSkipped, Unstage: CleanupSkipped}}, nil
	}

	env.RegisterWorkflowWithOptions(Reconcile, workflow.RegisterOptions{Name: reconcileWorkflowType})
	env.RegisterWorkflowWithOptions(func(ctx workflow.Context) (DestroyResult, error) { return h.destroy(ctx) },
		workflow.RegisterOptions{Name: destroyWorkflowType})
	env.RegisterWorkflowWithOptions(func(ctx workflow.Context, in ProvisionInput) (ProvisionResult, error) {
		h.mu.Lock()
		h.children = append(h.children, in)
		h.mu.Unlock()
		return h.provision(ctx, in)
	}, workflow.RegisterOptions{Name: provisionWorkflowType})

	stubs := map[string]any{
		wire.ActInspectTwin: func(context.Context) (wire.HostReport, error) { return wire.HostReport{}, errUnmocked },
		ActRunsInFlight:     func(context.Context) (RunsInFlightResult, error) { return RunsInFlightResult{}, errUnmocked },
		wire.ActReadIntent: func(context.Context, ReadIntentInput) (ReadIntentResult, error) {
			return ReadIntentResult{}, errUnmocked
		},
		wire.ActCompile: func(context.Context, CompileInput) (CompileResult, error) { return CompileResult{}, errUnmocked },
		wire.ActCheckHost: func(context.Context, wire.CheckHostInput) (wire.CheckHostResult, error) {
			return wire.CheckHostResult{}, errUnmocked
		},
		ActStopFollowing: func(context.Context) (StopFollowingResult, error) { return StopFollowingResult{}, errUnmocked },
	}
	for name, fn := range stubs {
		env.RegisterActivityWithOptions(fn, activity.RegisterOptions{Name: name})
	}
	env.SetOnActivityStartedListener(func(info *activity.Info, _ context.Context, _ converter.EncodedValues) {
		h.record(info.ActivityType.Name)
	})
	env.SetOnChildWorkflowStartedListener(func(info *workflow.Info, _ workflow.Context, _ converter.EncodedValues) {
		h.mu.Lock()
		h.childRuns[info.WorkflowExecution.ID] = info.WorkflowExecution.RunID
		h.mu.Unlock()
		h.record("child " + info.WorkflowExecution.ID)
	})
	return h
}

func (h *reconcileHarness) record(entry string) {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.events = append(h.events, entry)
}

func (h *reconcileHarness) calls() []string {
	h.mu.Lock()
	defer h.mu.Unlock()
	return append([]string(nil), h.events...)
}

func (h *reconcileHarness) childRun(workflowID string) string {
	h.mu.Lock()
	defer h.mu.Unlock()
	return h.childRuns[workflowID]
}

// followingTwin is the host holding a ready twin of the followed branch, unpinned, from
// intent, with bundle id.
func followingTwin(id string) wire.HostReport {
	observed := "2026-09-16T19:00:00.000000Z"
	return wire.HostReport{
		LabPresent:     true,
		TwinDirPresent: true,
		Nodes:          []wire.LabNode{{Name: "n1"}, {Name: "n2"}, {Name: "n3"}},
		Twin: &wire.TwinRecord{
			TwinVersion: "1", Lab: wire.LabName, BundleID: id,
			Provenance: wire.Provenance{Branch: checkBranch, SchemaHash: "41349c3a", ContractVersion: "0.2"},
			ObservedAt: &observed, Source: wire.SourceIntent,
			Run: wire.RunRef{WorkflowID: WorkflowProvision, RunID: "run-0"},
		},
		Phrase: "the twin of branch " + checkBranch,
	}
}

// mockCheck answers the check's activities up to the compare: the host holds a twin of
// twinID, nothing is in flight, and the branch compiles to compiledID. Every later step
// answers clear, and StopFollowing deletes the Schedule. Call it after a test's own mocks.
func (h *reconcileHarness) mockCheck(twinID, compiledID string) {
	env := h.env
	env.OnActivity(wire.ActInspectTwin, mock.Anything).Return(followingTwin(twinID), nil)
	env.OnActivity(ActRunsInFlight, mock.Anything).Return(RunsInFlightResult{}, nil)
	env.OnActivity(wire.ActReadIntent, mock.Anything, mock.Anything).Return(ReadIntentResult{
		CTMPath: "/state/bundles/.reads/check.ctm.json", ObservedAt: checkObservedAt, Findings: findings.List{},
	}, nil)
	env.OnActivity(wire.ActCompile, mock.Anything, mock.Anything).Return(CompileResult{
		BundleID: compiledID, BundlePath: "/state/bundles/" + compiledID, Findings: findings.List{},
	}, nil)
	env.OnActivity(wire.ActCheckHost, mock.Anything, mock.Anything).Return(wire.CheckHostResult{
		Nodes: srlinuxPlan(h.t), Findings: findings.List{
			{Severity: findings.Rejection, Rule: findings.RuleHostLabPresent, Step: findings.StepHostCheck, Object: "lab fylgja",
				Message: "lab fylgja is present"},
			{Severity: findings.Rejection, Rule: findings.RuleHostTwinPresent, Step: findings.StepHostCheck, Object: "/state/twin",
				Message: "a twin directory is present"},
		},
	}, nil)
	env.OnActivity(ActStopFollowing, mock.Anything).Return(StopFollowingResult{Deleted: true, Branch: checkBranch}, nil)
}

// run executes a check of the followed branch to completion. A check returns a result in
// every case, so a workflow error fails the test.
func (h *reconcileHarness) run() ReconcileResult {
	h.t.Helper()
	h.env.ExecuteWorkflow(reconcileWorkflowType, ReconcileInput{Branch: checkBranch, Version: "0.1.0-test"})
	if !h.env.IsWorkflowCompleted() {
		h.t.Fatal("the check did not complete")
	}
	if err := h.env.GetWorkflowError(); err != nil {
		h.t.Fatalf("the check failed: %v", err)
	}
	var res ReconcileResult
	if err := h.env.GetWorkflowResult(&res); err != nil {
		h.t.Fatal(err)
	}
	return res
}

// wantRules checks the findings' rules, in order, each at its step.
func wantRules(t *testing.T, list findings.List, want ...[2]string) {
	t.Helper()
	got := make([][2]string, len(list))
	for i, f := range list {
		got[i] = [2]string{f.Rule, f.Step}
	}
	if !slices.Equal(got, want) {
		t.Errorf("findings (rule, step) = %v, want %v\n%+v", got, want, list)
	}
}

// finding is the finding under rule, failing the test when there is none.
func finding(t *testing.T, list findings.List, rule string) findings.Finding {
	t.Helper()
	for _, f := range list {
		if f.Rule == rule {
			return f
		}
	}
	t.Fatalf("no %s in %+v", rule, list)
	return findings.Finding{}
}

// failedProvision is the provision child ending failed at deploy, its cleanup done.
func failedProvision(_ workflow.Context, in ProvisionInput) (ProvisionResult, error) {
	return ProvisionResult{Outcome: OutcomeFailed, BundleID: in.BundleID, Step: findings.StepDeploy,
		Findings: findings.List{{Severity: findings.Rejection, Rule: findings.RuleDeployFailed, Step: findings.StepDeploy,
			Object: "lab fylgja", Message: "clab deploy exited 1"}},
		Cleanup: CleanupResult{Teardown: CleanupDone, Unstage: CleanupDone}}, nil
}

// Ids equal: the check touches nothing — no host check, no child, no stop — and says what
// it compared.
func TestReconcileUnchanged(t *testing.T) {
	h := newReconcileHarness(t)
	h.mockCheck(twinBundleID, twinBundleID)

	res := h.run()

	if res.Outcome != CheckUnchanged || res.Step != "" {
		t.Errorf("outcome %q at %q, want unchanged with no step", res.Outcome, res.Step)
	}
	if res.TwinBundleID != twinBundleID || res.BundleID != twinBundleID {
		t.Errorf("compared %q with %q, want both %q", res.TwinBundleID, res.BundleID, twinBundleID)
	}
	if res.ObservedAt != checkObservedAt || res.Branch != checkBranch {
		t.Errorf("result %+v, want the read's observed_at and the followed branch", res)
	}
	want := []string{wire.ActInspectTwin, ActRunsInFlight, wire.ActReadIntent, wire.ActCompile}
	if got := h.calls(); !slices.Equal(got, want) {
		t.Errorf("started %v, want %v and nothing else", got, want)
	}
	if len(res.Findings) != 0 || res.Destroy != nil || res.Provision != nil || res.FollowingStopped {
		t.Errorf("result %+v, want no findings, no children and following untouched", res)
	}
}

// Ids differ: the host is checked for the new bundle, the twin destroyed under fylgja-destroy,
// then provisioned under fylgja-provision, already compiled, recording the check's read,
// neither beginning nor stopping following.
func TestReconcileRebuilt(t *testing.T) {
	h := newReconcileHarness(t)
	// The check's host check and the provision child's warn alike on the same host; the
	// child also names a warning of its own at the same step.
	own := findings.Finding{Severity: findings.Warning, Rule: findings.RuleHostMemoryUnbudgeted, Step: findings.StepHostCheck,
		Object: "host", Message: "sum 3072 MiB (3 × 1024 MiB) differs: the child read another sum"}
	h.mockUnbudgeted()
	h.provision = func(_ workflow.Context, in ProvisionInput) (ProvisionResult, error) {
		return ProvisionResult{Outcome: OutcomeReady, BundleID: in.BundleID, ObservedAt: in.ObservedAt,
			Findings: findings.List{unbudgeted, own},
			Cleanup:  CleanupResult{Teardown: CleanupSkipped, Unstage: CleanupSkipped}}, nil
	}
	h.mockCheck(twinBundleID, changedBundleID)

	res := h.run()

	if res.Outcome != CheckRebuilt || res.Step != "" {
		t.Errorf("outcome %q at %q, want rebuilt with no step", res.Outcome, res.Step)
	}
	want := []string{wire.ActInspectTwin, ActRunsInFlight, wire.ActReadIntent, wire.ActCompile, wire.ActCheckHost, ActRunsInFlight,
		"child " + WorkflowDestroy, "child " + WorkflowProvision}
	if got := h.calls(); !slices.Equal(got, want) {
		t.Errorf("started %v, want %v", got, want)
	}
	if len(h.children) != 1 {
		t.Fatalf("provision children %+v, want one", h.children)
	}
	wantInput := ProvisionInput{Source: wire.SourceIntent, Branch: checkBranch, BundleID: changedBundleID,
		BundlePath: "/state/bundles/" + changedBundleID, ObservedAt: checkObservedAt, Version: "0.1.0-test"}
	if got := h.children[0]; got != wantInput {
		t.Errorf("provision child input %+v\nwant %+v", got, wantInput)
	}
	if res.Destroy == nil || res.Provision == nil || res.Provision.Outcome != OutcomeReady {
		t.Errorf("result %+v, want the destroy and the ready provision reported", res)
	}
	if res.TwinBundleID != twinBundleID || res.BundleID != changedBundleID {
		t.Errorf("compared %q with %q, want %q with %q", res.TwinBundleID, res.BundleID, twinBundleID, changedBundleID)
	}
	// The presence refusals named the twin being replaced; they are not the check's findings.
	// The warning both host checks gave is reported once; the child's result keeps it whole.
	if want := (findings.List{unbudgeted, own}); !slices.Equal(res.Findings, want) {
		t.Errorf("findings %+v\nwant %+v: presence dropped, the shared warning once", res.Findings, want)
	}
	if res.Provision != nil && !slices.Equal(res.Provision.Findings, findings.List{unbudgeted, own}) {
		t.Errorf("provision findings %+v, want the child's whole", res.Provision.Findings)
	}
}

// unbudgeted is the host check's warning with no memory budget set, as both a check's host
// check and its provision child give it on one host.
var unbudgeted = findings.Finding{Severity: findings.Warning, Rule: findings.RuleHostMemoryUnbudgeted, Step: findings.StepHostCheck,
	Object: "host", Message: "sum 3072 MiB (3 × 1024 MiB) is not checked against a host budget: FYLGJA_HOST_MEMORY_MB is unset"}

// mockUnbudgeted makes the check's host check warn unbudgeted beside the presence refusals.
// Called before mockCheck, whose host check it replaces.
func (h *reconcileHarness) mockUnbudgeted() {
	h.env.OnActivity(wire.ActCheckHost, mock.Anything, mock.Anything).Return(wire.CheckHostResult{
		Nodes: srlinuxPlan(h.t), Findings: findings.List{
			{Severity: findings.Rejection, Rule: findings.RuleHostLabPresent, Step: findings.StepHostCheck, Object: "lab fylgja",
				Message: "lab fylgja is present"},
			unbudgeted,
		},
	}, nil)
}

// The provision child did not end ready: its findings, then rebuild.failed naming it with
// its cleanup, then follow.stopped; following is stopped (contracts/cli.md).
func TestReconcileRebuildFailedProvision(t *testing.T) {
	h := newReconcileHarness(t)
	h.provision = failedProvision
	h.mockCheck(twinBundleID, changedBundleID)

	res := h.run()

	if res.Outcome != CheckRebuildFailed || res.Step != findings.StepProvision || !res.FollowingStopped {
		t.Errorf("outcome %q at %q, following stopped %v; want rebuild_failed at provision, stopped", res.Outcome, res.Step, res.FollowingStopped)
	}
	calls := h.calls()
	if !slices.Equal(calls[len(calls)-3:], []string{"child " + WorkflowDestroy, "child " + WorkflowProvision, ActStopFollowing}) {
		t.Errorf("started %v, want the destroy, the provision, then StopFollowing", calls)
	}
	wantRules(t, res.Findings,
		[2]string{findings.RuleDeployFailed, findings.StepDeploy},
		[2]string{findings.RuleRebuildFailed, findings.StepProvision},
		[2]string{findings.RuleFollowStopped, findings.StepFollow})

	run := h.childRun(WorkflowProvision)
	rebuild := finding(t, res.Findings, findings.RuleRebuildFailed)
	wantMsg := "the rebuild's provision " + run + " ended failed at step deploy; cleanup teardown done, unstage done; following stopped"
	if rebuild.Object != run || rebuild.Message != wantMsg || rebuild.Severity != findings.Rejection {
		t.Errorf("rebuild.failed = %+v\nwant object %q, message %q", rebuild, run, wantMsg)
	}
	stopped := finding(t, res.Findings, findings.RuleFollowStopped)
	if want := "following of branch fylgja-fixture stopped after a failed rebuild; fylgja twin create starts again"; stopped.Message != want ||
		stopped.Object != FollowScheduleID || stopped.Severity != findings.Warning {
		t.Errorf("follow.stopped = %+v, want a warning on %s: %q", stopped, FollowScheduleID, want)
	}
	if res.Provision == nil || res.Provision.Outcome != OutcomeFailed {
		t.Errorf("provision %+v, want the child's failed result carried", res.Provision)
	}
}

// The destroy child left something: nothing can be provisioned beside it, so no provision
// child starts, and following stops.
func TestReconcileRebuildFailedDestroy(t *testing.T) {
	h := newReconcileHarness(t)
	h.destroy = func(workflow.Context) (DestroyResult, error) {
		return DestroyResult{
			Findings: findings.List{{Severity: findings.Rejection, Rule: findings.RuleCleanupIncomplete, Step: findings.StepTeardown,
				Object: "lab fylgja", Message: "clab destroy exited 1; clear it with: " + wire.ClearLabCommand}},
			Cleanup: CleanupResult{Teardown: CleanupFailed, Unstage: CleanupDone, Remaining: []string{"lab fylgja"}},
		}, nil
	}
	h.mockCheck(twinBundleID, changedBundleID)

	res := h.run()

	if res.Outcome != CheckRebuildFailed || res.Step != findings.StepDestroy || !res.FollowingStopped {
		t.Errorf("outcome %q at %q, following stopped %v; want rebuild_failed at destroy, stopped", res.Outcome, res.Step, res.FollowingStopped)
	}
	if calls := h.calls(); slices.Contains(calls, "child "+WorkflowProvision) || !slices.Contains(calls, ActStopFollowing) {
		t.Errorf("started %v, want no provision child and StopFollowing", calls)
	}
	wantRules(t, res.Findings,
		[2]string{findings.RuleCleanupIncomplete, findings.StepTeardown},
		[2]string{findings.RuleRebuildFailed, findings.StepDestroy},
		[2]string{findings.RuleFollowStopped, findings.StepFollow})
	run := h.childRun(WorkflowDestroy)
	rebuild := finding(t, res.Findings, findings.RuleRebuildFailed)
	wantMsg := "the rebuild's destroy " + run + " ended unclean at step teardown; cleanup teardown failed, unstage done; " +
		"remaining: lab fylgja; following stopped"
	if rebuild.Object != run || rebuild.Message != wantMsg {
		t.Errorf("rebuild.failed = %+v\nwant object %q, message %q", rebuild, run, wantMsg)
	}
	if res.Destroy == nil || res.Provision != nil {
		t.Errorf("result %+v, want the destroy reported and no provision", res)
	}
}

// Following that cannot be stopped is a warning, and the check does not claim it stopped.
func TestReconcileStopFollowingFails(t *testing.T) {
	h := newReconcileHarness(t)
	h.provision = failedProvision
	h.env.OnActivity(ActStopFollowing, mock.Anything).Return(StopFollowingResult{},
		temporal.NewNonRetryableApplicationError("permission denied", "schedule", nil))
	h.mockCheck(twinBundleID, changedBundleID)

	res := h.run()

	if res.Outcome != CheckRebuildFailed || res.FollowingStopped {
		t.Errorf("outcome %q, following stopped %v; want rebuild_failed, not stopped", res.Outcome, res.FollowingStopped)
	}
	wantRules(t, res.Findings,
		[2]string{findings.RuleDeployFailed, findings.StepDeploy},
		[2]string{findings.RuleRebuildFailed, findings.StepProvision},
		[2]string{findings.RuleFollowStopFailed, findings.StepFollow})
	stop := finding(t, res.Findings, findings.RuleFollowStopFailed)
	if stop.Severity != findings.Warning || stop.Object != FollowScheduleID ||
		!strings.HasPrefix(stop.Message, "deleting schedule fylgja-follow failed (permission denied)") {
		t.Errorf("follow.stop.failed = %+v, want a warning on %s naming the delete and its cause", stop, FollowScheduleID)
	}
	if rebuild := finding(t, res.Findings, findings.RuleRebuildFailed); !strings.HasSuffix(rebuild.Message, "; following could not be stopped") {
		t.Errorf("rebuild.failed message %q claims following stopped", rebuild.Message)
	}
}

// A check cancelled while its provision child ran, whose child still ended failed rather
// than cancelled, stops following all the same: the stop runs on a context the cancellation
// does not reach.
func TestReconcileStopFollowingSurvivesCancellation(t *testing.T) {
	h := newReconcileHarness(t)
	h.provision = func(ctx workflow.Context, in ProvisionInput) (ProvisionResult, error) {
		// Hold the child until the check's cancellation has reached it, then end failed.
		_ = workflow.Sleep(ctx, time.Hour)
		if ctx.Err() == nil {
			return ProvisionResult{}, errors.New("the cancellation never reached the provision child")
		}
		return failedProvision(ctx, in)
	}
	h.mockCheck(twinBundleID, changedBundleID)
	h.env.RegisterDelayedCallback(h.env.CancelWorkflow, time.Minute)

	res := h.run()

	if res.Outcome != CheckRebuildFailed || !res.FollowingStopped {
		t.Errorf("outcome %q, following stopped %v; want rebuild_failed, stopped", res.Outcome, res.FollowingStopped)
	}
	if calls := h.calls(); calls[len(calls)-1] != ActStopFollowing {
		t.Errorf("started %v, want StopFollowing last", calls)
	}
	// deploy.failed comes only from a child the cancellation reached.
	wantRules(t, res.Findings,
		[2]string{findings.RuleDeployFailed, findings.StepDeploy},
		[2]string{findings.RuleRebuildFailed, findings.StepProvision},
		[2]string{findings.RuleFollowStopped, findings.StepFollow})
}

// wantNothingTouched fails the test when the check started a child or stopped following:
// a check that is refused, cannot run or skips leaves the twin and following as they were.
func (h *reconcileHarness) wantNothingTouched() {
	h.t.Helper()
	calls := h.calls()
	for _, c := range calls {
		if strings.HasPrefix(c, "child ") || c == ActStopFollowing {
			h.t.Errorf("started %v, want no child and no StopFollowing", calls)
			return
		}
	}
}

// A refusal before the destroy is rejected at the refusing step, its findings carried as
// given, and nothing touched. At the host check the two presence rules name
// the running twin and are dropped; any other refusal stands.
func TestReconcileRejected(t *testing.T) {
	readRefusal := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleDevicesEmpty, Step: findings.StepRead,
		Object: "branch fylgja-fixture", Message: "the branch holds no devices"}
	compileRefusal := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleBundleIDMismatch, Step: findings.StepCompile,
		Object: changedBundleID, Message: "the filed bundle hashes to another identity"}
	const gone = "reading the schema (branch " + checkBranch + "): HTTP 400: Branch: " + checkBranch + " not found."
	deleted := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleOperationFailed, Step: findings.StepRead,
		Object: "branch " + checkBranch, Message: gone}
	memory := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleHostMemoryExceeded, Step: findings.StepHostCheck,
		Object: "host", Message: "the nodes need 6144 MiB, above FYLGJA_HOST_MEMORY_MB 4096"}

	for _, c := range []struct {
		name  string
		mock  func(h *reconcileHarness)
		step  string
		want  findings.Finding
		calls []string
	}{
		{"read", func(h *reconcileHarness) {
			h.env.OnActivity(wire.ActReadIntent, mock.Anything, mock.Anything).Return(ReadIntentResult{
				ObservedAt: checkObservedAt, Findings: findings.List{readRefusal}}, nil)
		}, findings.StepRead, readRefusal, []string{wire.ActInspectTwin, ActRunsInFlight, wire.ActReadIntent}},
		// The followed branch was deleted: Infrahub's refusal, not a read that could not
		// run.
		// TestReconcileError keeps an unreachable Infrahub error.
		{"deleted branch", func(h *reconcileHarness) {
			h.env.OnActivity(wire.ActReadIntent, mock.Anything, mock.Anything).Return(ReadIntentResult{},
				branchNotFound("branch "+checkBranch, errors.New(gone)))
		}, findings.StepRead, deleted, []string{wire.ActInspectTwin, ActRunsInFlight, wire.ActReadIntent}},
		{"compile", func(h *reconcileHarness) {
			h.env.OnActivity(wire.ActCompile, mock.Anything, mock.Anything).Return(CompileResult{
				Findings: findings.List{compileRefusal}}, nil)
		}, findings.StepCompile, compileRefusal, []string{wire.ActInspectTwin, ActRunsInFlight, wire.ActReadIntent, wire.ActCompile}},
		{"host check", func(h *reconcileHarness) {
			h.env.OnActivity(wire.ActCheckHost, mock.Anything, mock.Anything).Return(wire.CheckHostResult{
				Nodes: srlinuxPlan(h.t), Findings: findings.List{
					{Severity: findings.Rejection, Rule: findings.RuleHostLabPresent, Step: findings.StepHostCheck, Object: "lab fylgja",
						Message: "lab fylgja is present"},
					memory,
					{Severity: findings.Rejection, Rule: findings.RuleHostTwinPresent, Step: findings.StepHostCheck, Object: "/state/twin",
						Message: "a twin directory is present"},
				}}, nil)
		}, findings.StepHostCheck, memory,
			[]string{wire.ActInspectTwin, ActRunsInFlight, wire.ActReadIntent, wire.ActCompile, wire.ActCheckHost}},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := newReconcileHarness(t)
			c.mock(h)
			h.mockCheck(twinBundleID, changedBundleID)

			res := h.run()

			if res.Outcome != CheckRejected || res.Step != c.step {
				t.Errorf("outcome %q at %q, want rejected at %s", res.Outcome, res.Step, c.step)
			}
			if len(res.Findings) != 1 || res.Findings[0] != c.want {
				t.Errorf("findings %+v, want %+v alone", res.Findings, c.want)
			}
			if got := h.calls(); !slices.Equal(got, c.calls) {
				t.Errorf("started %v, want %v", got, c.calls)
			}
			h.wantNothingTouched()
			if res.Destroy != nil || res.Provision != nil || res.FollowingStopped {
				t.Errorf("result %+v, want no rebuild and following untouched", res)
			}
		})
	}
}

// A step before the destroy that could not run is error at that step, under the finding its
// activity gave or operation.failed, and nothing is touched: the next check tries again.
func TestReconcileError(t *testing.T) {
	for _, c := range []struct {
		name    string
		mock    func(h *reconcileHarness)
		step    string
		object  string
		message string
	}{
		{"inspection", func(h *reconcileHarness) {
			h.env.OnActivity(wire.ActInspectTwin, mock.Anything).Return(wire.HostReport{},
				lab.StepFailure(findings.StepInspect, findings.RuleOperationFailed, "lab fylgja", "clab inspect --all exited 1"))
		}, findings.StepInspect, "lab fylgja", "clab inspect --all exited 1"},
		{"runs in flight", func(h *reconcileHarness) {
			h.env.OnActivity(ActRunsInFlight, mock.Anything).Return(RunsInFlightResult{},
				temporal.NewNonRetryableApplicationError("workflow service unavailable", "unavailable", nil))
		}, findings.StepInspect, findings.StepInspect, "workflow service unavailable"},
		{"read", func(h *reconcileHarness) {
			h.env.OnActivity(wire.ActReadIntent, mock.Anything, mock.Anything).Return(ReadIntentResult{},
				operationFailed(findings.StepRead, "branch "+checkBranch, errors.New("infrahub unreachable at http://localhost:8000")))
		}, findings.StepRead, "branch " + checkBranch, "infrahub unreachable at http://localhost:8000"},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := newReconcileHarness(t)
			c.mock(h)
			h.mockCheck(twinBundleID, changedBundleID)

			res := h.run()

			if res.Outcome != CheckError || res.Step != c.step {
				t.Errorf("outcome %q at %q, want error at %s", res.Outcome, res.Step, c.step)
			}
			wantRules(t, res.Findings, [2]string{findings.RuleOperationFailed, c.step})
			if len(res.Findings) == 1 {
				if f := res.Findings[0]; f.Object != c.object || !strings.Contains(f.Message, c.message) {
					t.Errorf("finding %+v, want object %q and a message naming %q", f, c.object, c.message)
				}
			}
			h.wantNothingTouched()
			if slices.Contains(h.calls(), wire.ActCheckHost) {
				t.Errorf("started %v, want nothing after the step that could not run", h.calls())
			}
		})
	}
}

// A check with nothing to compare against, or beside an operator's run, skips at inspect
// with check.skipped naming what it found, and touches nothing.
func TestReconcileSkipped(t *testing.T) {
	const pinnedAt = "2026-09-16T18:00:00.000000Z"
	other := followingTwin(twinBundleID)
	other.Twin.Provenance.Branch = "other"
	pinned := followingTwin(twinBundleID)
	pinned.Twin.Provenance.At = pinnedAt
	fromBundle := followingTwin(twinBundleID)
	fromBundle.Twin.Source, fromBundle.Twin.ObservedAt = wire.SourceBundle, nil
	orphan := wire.HostReport{LabPresent: true, Nodes: []wire.LabNode{{Name: "n1"}},
		TopoPaths: []string{"/home/op/labs/fylgja.clab.yml"},
		Phrase:    "lab fylgja present (1 node); twin directory absent; an orphan: no twin.json records it; deployed from /home/op/labs/fylgja.clab.yml"}
	labGone := followingTwin(twinBundleID) // M3's shape b: the lab removed by hand
	labGone.LabPresent, labGone.Nodes = false, nil
	labGone.Phrase = "the twin of branch " + checkBranch + ", bundle_id " + twinBundleID +
		", provisioned by run fylgja-provision run-0, 3 nodes recorded, but lab fylgja is absent"
	inspection := []string{wire.ActInspectTwin}

	for _, c := range []struct {
		name    string
		host    wire.HostReport
		runs    RunsInFlightResult
		later   RunsInFlightResult // RunsInFlight's answer after its first
		object  string
		message string
		calls   []string
	}{
		{"no lab and no twin directory", wire.HostReport{}, RunsInFlightResult{}, RunsInFlightResult{}, "lab fylgja",
			"nothing to compare against: no lab fylgja and no twin directory; a check never provisions a twin where there was none", inspection},
		{"an orphan", orphan, RunsInFlightResult{}, RunsInFlightResult{}, orphan.Phrase,
			"nothing to compare against: " + orphan.Phrase + "; fylgja twin destroy clears it", inspection},
		{"a record whose lab is absent", labGone, RunsInFlightResult{}, RunsInFlightResult{}, labGone.Phrase,
			"nothing to compare against: " + labGone.Phrase + "; fylgja twin destroy clears it", inspection},
		{"another branch", other, RunsInFlightResult{}, RunsInFlightResult{}, "branch other",
			"the twin is of branch other, but the following is of branch fylgja-fixture; nothing is touched", inspection},
		{"a pinned twin", pinned, RunsInFlightResult{}, RunsInFlightResult{}, twinBundleID,
			"the twin does not follow (pinned at " + pinnedAt + "); nothing is touched", inspection},
		{"a twin from a bundle", fromBundle, RunsInFlightResult{}, RunsInFlightResult{}, twinBundleID,
			"the twin does not follow (provisioned from a bundle); nothing is touched", inspection},
		{"a provision in flight", followingTwin(twinBundleID), RunsInFlightResult{Provision: "run-p"}, RunsInFlightResult{}, "run-p",
			"fylgja-provision run-p is in flight; the check is skipped", []string{wire.ActInspectTwin, ActRunsInFlight}},
		// An operator's create begun while the check read, compiled and checked the host holds
		// no id the destroy child would be refused under: the second look skips before it.
		{"a provision begun after step 2", followingTwin(twinBundleID), RunsInFlightResult{}, RunsInFlightResult{Provision: "run-p"}, "run-p",
			"fylgja-provision run-p is in flight; the check is skipped",
			[]string{wire.ActInspectTwin, ActRunsInFlight, wire.ActReadIntent, wire.ActCompile, wire.ActCheckHost, ActRunsInFlight}},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := newReconcileHarness(t)
			h.env.OnActivity(wire.ActInspectTwin, mock.Anything).Return(c.host, nil)
			h.env.OnActivity(ActRunsInFlight, mock.Anything).Return(c.runs, nil).Once()
			h.env.OnActivity(ActRunsInFlight, mock.Anything).Return(c.later, nil)
			h.mockCheck(twinBundleID, changedBundleID)

			res := h.run()

			if res.Outcome != CheckSkipped || res.Step != findings.StepInspect {
				t.Errorf("outcome %q at %q, want skipped at inspect", res.Outcome, res.Step)
			}
			wantRules(t, res.Findings, [2]string{findings.RuleCheckSkipped, findings.StepInspect})
			if len(res.Findings) == 1 {
				if f := res.Findings[0]; f.Severity != findings.Warning || f.Object != c.object || f.Message != c.message {
					t.Errorf("check.skipped = %+v\nwant a warning on %q: %q", f, c.object, c.message)
				}
			}
			if got := h.calls(); !slices.Equal(got, c.calls) {
				t.Errorf("started %v, want %v: no read, nothing touched", got, c.calls)
			}
			h.wantNothingTouched()
		})
	}
}

// The rebuild's destroy refused because a run holds fylgja-destroy, which neither look of
// RunsInFlight saw: nothing has been touched, so the check skips, naming the run it asks for
// again. The test suite refuses a child whose id a running workflow holds, so the check itself
// runs under fylgja-destroy here.
func TestReconcileSkippedDestroyAlreadyStarted(t *testing.T) {
	h := newReconcileHarness(t)
	h.env.SetStartWorkflowOptions(client.StartWorkflowOptions{ID: WorkflowDestroy})
	h.env.OnActivity(ActRunsInFlight, mock.Anything).Return(RunsInFlightResult{}, nil).Twice()
	h.env.OnActivity(ActRunsInFlight, mock.Anything).Return(RunsInFlightResult{Destroy: "run-d"}, nil)
	h.mockCheck(twinBundleID, changedBundleID)

	res := h.run()

	if res.Outcome != CheckSkipped || res.Step != findings.StepInspect {
		t.Errorf("outcome %q at %q, want skipped at inspect", res.Outcome, res.Step)
	}
	wantRules(t, res.Findings, [2]string{findings.RuleCheckSkipped, findings.StepInspect})
	if f := finding(t, res.Findings, findings.RuleCheckSkipped); f.Object != "run-d" ||
		f.Message != "fylgja-destroy run-d is in flight; the check is skipped" {
		t.Errorf("check.skipped = %+v, want the destroy run named", f)
	}
	want := []string{wire.ActInspectTwin, ActRunsInFlight, wire.ActReadIntent, wire.ActCompile, wire.ActCheckHost, ActRunsInFlight,
		ActRunsInFlight}
	if got := h.calls(); !slices.Equal(got, want) {
		t.Errorf("started %v, want %v", got, want)
	}
	h.wantNothingTouched()
	if res.Destroy != nil || res.Provision != nil {
		t.Errorf("result %+v, want nothing destroyed", res)
	}
}

// A check destroy cancels is cancelled at the step it had reached, with run.cancelled naming
// the check and what the host saw; it is never a failed rebuild, and it never stops
// following itself — the destroy that cancelled it has.
func TestReconcileCancelled(t *testing.T) {
	t.Run("during the read", func(t *testing.T) {
		h := newReconcileHarness(t)
		reached := make(chan struct{})
		var once sync.Once
		h.env.SetOnActivityCanceledListener(func(*activity.Info) { once.Do(func() { close(reached) }) })
		h.env.OnActivity(wire.ActReadIntent, mock.Anything, mock.Anything).Return(
			func(ctx context.Context, _ ReadIntentInput) (ReadIntentResult, error) {
				h.env.CancelWorkflow()
				select {
				case <-reached:
				case <-ctx.Done():
				case <-time.After(5 * time.Second):
					return ReadIntentResult{}, errors.New("the cancellation never reached the read")
				}
				return ReadIntentResult{}, context.Canceled
			})
		h.mockCheck(twinBundleID, changedBundleID)

		res := h.run()

		wantCancelled(t, h, res, findings.StepRead, "nothing on the host was touched")
		h.wantNothingTouched()
	})

	t.Run("during the destroy", func(t *testing.T) {
		h := newReconcileHarness(t)
		h.destroy = func(ctx workflow.Context) (DestroyResult, error) {
			// As M2's Destroy: its teardown runs whatever it is asked, and a cancel that has
			// reached it by then skips the unstage.
			_ = workflow.Sleep(ctx, time.Hour)
			if ctx.Err() != nil {
				runID := workflow.GetInfo(ctx).WorkflowExecution.RunID
				return DestroyResult{
					Findings: findings.List{{Severity: findings.Rejection, Rule: findings.RuleRunCancelled, Step: findings.StepUnstage,
						Object: runID, Message: "destroy run " + runID + " was cancelled after teardown, so the twin directory was not checked; run fylgja twin destroy again"}},
					Cleanup: CleanupResult{Teardown: CleanupDone, Unstage: CleanupSkipped,
						Removed: []string{"lab fylgja (3 containers)"}, Remaining: []string{"twin directory (not checked: the destroy run was cancelled)"}},
				}, nil
			}
			return DestroyResult{Findings: findings.List{}, Cleanup: CleanupResult{Teardown: CleanupDone, Unstage: CleanupDone,
				Removed: []string{"lab fylgja (3 containers)", "twin directory /state/twin"}}}, nil
		}
		h.mockCheck(twinBundleID, changedBundleID)
		h.env.RegisterDelayedCallback(h.env.CancelWorkflow, time.Minute)

		res := h.run()

		wantCancelled(t, h, res, findings.StepDestroy, "the rebuild's destroy ran to completion and nothing was provisioned")
		if calls := h.calls(); !slices.Contains(calls, "child "+WorkflowDestroy) || slices.Contains(calls, "child "+WorkflowProvision) {
			t.Errorf("started %v, want the destroy child and no provision child", calls)
		}
		// The check's cancellation never reached the destroy, so it unstaged and says nothing
		// the check's own run.cancelled contradicts.
		if res.Destroy == nil || res.Destroy.Cleanup.Unstage != CleanupDone || len(res.Destroy.Cleanup.Remaining) != 0 ||
			len(res.Destroy.Findings) != 0 {
			t.Errorf("destroy %+v, want unstage done, nothing remaining and no findings", res.Destroy)
		}
		wantRules(t, res.Findings, [2]string{findings.RuleRunCancelled, findings.StepDestroy})
	})

	t.Run("during the provision", func(t *testing.T) {
		childCancelled := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleRunCancelled, Step: findings.StepDeploy,
			Object: "run-p", Message: "run run-p was cancelled at step deploy; teardown and unstage then ran"}
		h := newReconcileHarness(t)
		h.provision = func(ctx workflow.Context, in ProvisionInput) (ProvisionResult, error) {
			_ = workflow.Sleep(ctx, time.Hour)
			if ctx.Err() == nil {
				return ProvisionResult{}, errors.New("the cancellation never reached the provision child")
			}
			return ProvisionResult{Outcome: OutcomeCancelled, BundleID: in.BundleID, Step: findings.StepDeploy,
				Findings: findings.List{unbudgeted, childCancelled},
				Cleanup:  CleanupResult{Teardown: CleanupDone, Unstage: CleanupDone}}, nil
		}
		h.mockUnbudgeted()
		h.mockCheck(twinBundleID, changedBundleID)
		h.env.RegisterDelayedCallback(h.env.CancelWorkflow, time.Minute)

		res := h.run()

		wantCancelled(t, h, res, findings.StepProvision, "the rebuild's provision cleaned up after itself")
		if res.Provision == nil || res.Provision.Outcome != OutcomeCancelled {
			t.Errorf("provision %+v, want the child's cancelled result carried", res.Provision)
		}
		// The host check's warning once, from the check's own host check.
		wantRules(t, res.Findings,
			[2]string{findings.RuleHostMemoryUnbudgeted, findings.StepHostCheck},
			[2]string{findings.RuleRunCancelled, findings.StepDeploy},
			[2]string{findings.RuleRunCancelled, findings.StepProvision})
		if res.Provision != nil && len(res.Provision.Findings) != 2 {
			t.Errorf("provision findings %+v, want the child's two whole", res.Provision.Findings)
		}
		if calls := h.calls(); !slices.Contains(calls, "child "+WorkflowProvision) {
			t.Errorf("started %v, want the provision child", calls)
		}
	})
}

// wantCancelled checks a cancelled check: the outcome at step, run.cancelled last naming the
// check with what happened, and no StopFollowing.
func wantCancelled(t *testing.T, h *reconcileHarness, res ReconcileResult, step, what string) {
	t.Helper()
	if res.Outcome != CheckCancelled || res.Step != step || res.FollowingStopped {
		t.Errorf("outcome %q at %q, following stopped %v; want cancelled at %s, following untouched",
			res.Outcome, res.Step, res.FollowingStopped, step)
	}
	if n := len(res.Findings); n == 0 || res.Findings[n-1].Rule != findings.RuleRunCancelled {
		t.Fatalf("findings %+v, want run.cancelled last", res.Findings)
	}
	f := res.Findings[len(res.Findings)-1]
	want := "check " + f.Object + " was cancelled at step " + step + "; " + what
	if f.Object == "" || f.Step != step || f.Severity != findings.Rejection || f.Message != want {
		t.Errorf("run.cancelled = %+v\nwant object the check's id, at %s: %q", f, step, want)
	}
	if slices.Contains(h.calls(), ActStopFollowing) || slices.ContainsFunc(res.Findings, func(f findings.Finding) bool {
		return f.Rule == findings.RuleRebuildFailed || f.Rule == findings.RuleFollowStopped
	}) {
		t.Errorf("started %v with findings %+v; want no StopFollowing and no failed rebuild", h.calls(), res.Findings)
	}
}

// The fixture's n1 artifact checksum, and the one a configuration change moved it to.
const (
	twinChecksum    = "43e8fd0c2de5f4646f74a51d34742824"
	changedChecksum = "5d41402abc4b2a76b9719d911017c592"
)

// withArtifacts gives a following twin's record each node's artifact under checksum.
func withArtifacts(report wire.HostReport, checksum string) wire.HostReport {
	report.Twin.TwinVersion = "2"
	for _, n := range report.Nodes {
		report.Twin.Nodes = append(report.Twin.Nodes, wire.TwinNode{Name: n.Name,
			Artifact: &wire.TwinArtifact{Name: "device-config", ContentType: "text/plain", Checksum: checksum, Size: 839}})
	}
	return report
}

// At M5, a configuration change is followed as M4 follows any change, through the same
// read-compile-compare and nothing new (D-026). Reconcile is unchanged by M5, and each
// outcome here is Reconcile's own, from the file's fakes: the artifact is in the bundle, so
// a change to it is a change of bundle_id, and a read Infrahub's artifact state refuses is a
// read refusal like any other.
func TestReconcileConfigurationChange(t *testing.T) {
	// An artifact-only change: the branch compiles to a new id from the same topology — the
	// host check plans the same three nodes — and the check rebuilds it with no operator
	// command. The provision child is given the new bundle, and the record it wrote, which
	// the check carries, names the new checksum.
	t.Run("rebuilt", func(t *testing.T) {
		h := newReconcileHarness(t)
		h.provision = func(_ workflow.Context, in ProvisionInput) (ProvisionResult, error) {
			rec := withArtifacts(followingTwin(in.BundleID), changedChecksum).Twin
			return ProvisionResult{Outcome: OutcomeReady, BundleID: in.BundleID, ObservedAt: in.ObservedAt, Twin: rec,
				Findings: findings.List{}, Cleanup: CleanupResult{Teardown: CleanupSkipped, Unstage: CleanupSkipped}}, nil
		}
		h.env.OnActivity(wire.ActInspectTwin, mock.Anything).Return(withArtifacts(followingTwin(twinBundleID), twinChecksum), nil)
		h.mockCheck(twinBundleID, changedBundleID)

		res := h.run()

		if res.Outcome != CheckRebuilt || res.Step != "" || res.FollowingStopped {
			t.Errorf("outcome %q at %q, following stopped %v; want rebuilt, following on", res.Outcome, res.Step, res.FollowingStopped)
		}
		calls := h.calls()
		if !slices.Equal(calls[len(calls)-2:], []string{"child " + WorkflowDestroy, "child " + WorkflowProvision}) {
			t.Errorf("started %v, want the destroy then the provision child last", calls)
		}
		if len(h.children) != 1 || h.children[0].BundleID != changedBundleID || h.children[0].BundlePath != "/state/bundles/"+changedBundleID {
			t.Fatalf("provision children %+v, want one given bundle %s", h.children, changedBundleID)
		}
		if res.TwinBundleID != twinBundleID || res.BundleID != changedBundleID {
			t.Errorf("compared %q with %q, want %q with %q", res.TwinBundleID, res.BundleID, twinBundleID, changedBundleID)
		}
		if res.Provision == nil || res.Provision.Twin == nil || len(res.Provision.Twin.Nodes) != 3 {
			t.Fatalf("provision %+v, want the new record of three nodes carried", res.Provision)
		}
		for _, n := range res.Provision.Twin.Nodes {
			if n.Artifact == nil || n.Artifact.Checksum != changedChecksum {
				t.Errorf("new record's node %s artifact %+v, want checksum %s", n.Name, n.Artifact, changedChecksum)
			}
		}
	})

	// Infrahub holds a change it has not finished generating: the read refuses it, the
	// check is rejected at read with the refusal as given, the twin is untouched, and
	// following continues — the next check reads again.
	t.Run("not ready", func(t *testing.T) {
		notReady := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleArtifactNotReady, Step: findings.StepRead,
			Object: "n1", Message: "device n1: artifact device-config is Pending, not Ready; fylgja never regenerates an artifact, " +
				"because that is a write to Infrahub"}
		h := newReconcileHarness(t)
		h.env.OnActivity(wire.ActReadIntent, mock.Anything, mock.Anything).Return(ReadIntentResult{
			ObservedAt: checkObservedAt, Findings: findings.List{notReady}}, nil)
		h.mockCheck(twinBundleID, changedBundleID)

		res := h.run()

		if res.Outcome != CheckRejected || res.Step != findings.StepRead || res.FollowingStopped {
			t.Errorf("outcome %q at %q, following stopped %v; want rejected at read, following on", res.Outcome, res.Step, res.FollowingStopped)
		}
		if len(res.Findings) != 1 || res.Findings[0] != notReady {
			t.Errorf("findings %+v, want %+v alone", res.Findings, notReady)
		}
		if got, want := h.calls(), []string{wire.ActInspectTwin, ActRunsInFlight, wire.ActReadIntent}; !slices.Equal(got, want) {
			t.Errorf("started %v, want %v", got, want)
		}
		h.wantNothingTouched()
	})

	// A regeneration to identical bytes compiles to the recorded id: unchanged, nothing
	// started after the compare, so twin.json is not rewritten.
	t.Run("unchanged", func(t *testing.T) {
		h := newReconcileHarness(t)
		h.env.OnActivity(wire.ActInspectTwin, mock.Anything).Return(withArtifacts(followingTwin(twinBundleID), twinChecksum), nil)
		h.mockCheck(twinBundleID, twinBundleID)

		res := h.run()

		if res.Outcome != CheckUnchanged || res.Step != "" || len(res.Findings) != 0 {
			t.Errorf("outcome %q at %q with %+v, want unchanged, no findings", res.Outcome, res.Step, res.Findings)
		}
		if got, want := h.calls(), []string{wire.ActInspectTwin, ActRunsInFlight, wire.ActReadIntent, wire.ActCompile}; !slices.Equal(got, want) {
			t.Errorf("started %v, want %v and nothing that could record", got, want)
		}
		h.wantNothingTouched()
		if res.Destroy != nil || res.Provision != nil {
			t.Errorf("result %+v, want no children", res)
		}
	})

	// The rebuild's provision child fails at the push: rebuild_failed at step provision,
	// the child's push finding first, and following stops, as it does after any failed
	// rebuild — a twin that could not take its configuration is not the branch's twin.
	t.Run("push fails", func(t *testing.T) {
		refused := findings.Finding{Severity: findings.Rejection, Rule: findings.RulePushRefused, Step: findings.StepPush,
			Object: "n2", Message: "node n2 refused artifact device-config (checksum " + changedChecksum + ") at line 3: parse error"}
		h := newReconcileHarness(t)
		h.provision = func(_ workflow.Context, in ProvisionInput) (ProvisionResult, error) {
			return ProvisionResult{Outcome: OutcomeFailed, BundleID: in.BundleID, Step: findings.StepPush,
				Findings: findings.List{refused}, Cleanup: CleanupResult{Teardown: CleanupDone, Unstage: CleanupDone}}, nil
		}
		h.mockCheck(twinBundleID, changedBundleID)

		res := h.run()

		if res.Outcome != CheckRebuildFailed || res.Step != findings.StepProvision || !res.FollowingStopped {
			t.Errorf("outcome %q at %q, following stopped %v; want rebuild_failed at provision, stopped",
				res.Outcome, res.Step, res.FollowingStopped)
		}
		wantRules(t, res.Findings,
			[2]string{findings.RulePushRefused, findings.StepPush},
			[2]string{findings.RuleRebuildFailed, findings.StepProvision},
			[2]string{findings.RuleFollowStopped, findings.StepFollow})
		run := h.childRun(WorkflowProvision)
		want := "the rebuild's provision " + run + " ended failed at step push; cleanup teardown done, unstage done; following stopped"
		if f := finding(t, res.Findings, findings.RuleRebuildFailed); f.Object != run || f.Message != want {
			t.Errorf("rebuild.failed = %+v\nwant object %q, message %q", f, run, want)
		}
		if calls := h.calls(); calls[len(calls)-1] != ActStopFollowing {
			t.Errorf("started %v, want StopFollowing last", calls)
		}
	})
}
