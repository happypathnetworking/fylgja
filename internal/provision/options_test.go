package provision

import (
	"path/filepath"
	"reflect"
	"slices"
	"testing"
	"time"

	enumspb "go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/workflow"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/rehearsal"
	"github.com/happypathnetworking/fylgja/internal/verify"
)

// planFor builds a node plan from a package as the host check does: every budget is
// the package's, which is what these tests are about.
func planFor(t *testing.T, reg *psp.Registry, pspID, node string) wire.NodePlan {
	t.Helper()
	p, ok := reg.LookupID(pspID)
	if !ok {
		t.Fatalf("no package %q", pspID)
	}
	return wire.NodePlan{
		Name:            node,
		PSPID:           p.Platform.ID,
		PSPSource:       p.Origin,
		Image:           p.Image.Ref,
		MemoryMB:        p.Image.Resources.MemoryMB,
		TimeoutS:        p.Readiness.TimeoutS,
		DeployTimeoutS:  p.Image.DeployTimeoutS,
		DestroyTimeoutS: p.Image.DestroyTimeoutS,
		Push:            wire.PushSpec{Delivery: p.Config.Delivery, Mode: p.Config.Mode, Commit: p.Config.Commit, TimeoutS: p.Config.PushTimeoutS},
	}
}

func srlinuxPlan(t *testing.T) []wire.NodePlan {
	t.Helper()
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	return []wire.NodePlan{
		planFor(t, reg, "nokia_srlinux", "n1"),
		planFor(t, reg, "nokia_srlinux", "n2"),
		planFor(t, reg, "nokia_srlinux", "n3"),
	}
}

func heterogeneousPlan(t *testing.T) []wire.NodePlan {
	t.Helper()
	reg, err := psp.Load(filepath.Join("..", "..", "testdata", "psp", "heterogeneous"))
	if err != nil {
		t.Fatal(err)
	}
	return []wire.NodePlan{planFor(t, reg, "fastos", "n1"), planFor(t, reg, "slowos", "n2")}
}

func TestSRLinuxBudgetsComeFromItsPackage(t *testing.T) {
	plan := srlinuxPlan(t)
	for _, c := range []struct {
		label string
		got   time.Duration
		want  time.Duration
	}{
		{"deploy", DeployOptions(plan).StartToCloseTimeout, 180 * time.Second},
		{"readiness per node", ReadinessOptions(plan[0], plan).StartToCloseTimeout, 75 * time.Second},
		{"readiness schedule-to-close", ReadinessOptions(plan[0], plan).ScheduleToCloseTimeout, 75 * time.Second},
		{"readiness step", ReadinessStepBudget(plan), 75 * time.Second},
		{"destroy", DestroyOptions(MaxDestroyTimeoutS(plan)).StartToCloseTimeout, 60 * time.Second},
		{"push per node", PushOptions(plan[0], plan).StartToCloseTimeout, 45 * time.Second},
		{"push schedule-to-start", PushOptions(plan[0], plan).ScheduleToStartTimeout, 45 * time.Second},
		{"push step", PushStepBudget(plan), 45 * time.Second},
	} {
		if c.got != c.want {
			t.Errorf("%s = %s, want %s", c.label, c.got, c.want)
		}
	}
}

// Two platforms, two budgets: each node waits under its own package's timeout and the
// step under the larger, never one global value (Constitution II).
func TestHeterogeneousBudgetsArePerPlatform(t *testing.T) {
	plan := heterogeneousPlan(t)
	fast, slow := plan[0], plan[1]
	for _, c := range []struct {
		label string
		got   time.Duration
		want  time.Duration
	}{
		{"fastos readiness", ReadinessOptions(fast, plan).StartToCloseTimeout, 45 * time.Second},
		{"fastos readiness schedule-to-close", ReadinessOptions(fast, plan).ScheduleToCloseTimeout, 315 * time.Second},
		{"slowos readiness", ReadinessOptions(slow, plan).StartToCloseTimeout, 315 * time.Second},
		{"slowos readiness schedule-to-close", ReadinessOptions(slow, plan).ScheduleToCloseTimeout, 315 * time.Second},
		{"readiness step", ReadinessStepBudget(plan), 315 * time.Second},
		{"deploy", DeployOptions(plan).StartToCloseTimeout, 600 * time.Second},
		{"destroy", DestroyOptions(120).StartToCloseTimeout, 120 * time.Second},
		{"fastos push", PushOptions(fast, plan).StartToCloseTimeout, 45 * time.Second},
		{"slowos push", PushOptions(slow, plan).StartToCloseTimeout, 105 * time.Second},
		{"fastos push schedule-to-start", PushOptions(fast, plan).ScheduleToStartTimeout, 105 * time.Second},
		{"push step", PushStepBudget(plan), 105 * time.Second},
	} {
		if c.got != c.want {
			t.Errorf("%s = %s, want %s", c.label, c.got, c.want)
		}
	}
	if got := MaxDestroyTimeoutS(plan); got != 120 {
		t.Errorf("MaxDestroyTimeoutS = %d, want 120", got)
	}
}

func TestDestroyWithNoBudgetUsesTheStatedDefault(t *testing.T) {
	if got := DestroyOptions(0).StartToCloseTimeout; got != 60*time.Second {
		t.Errorf("DestroyOptions(0) = %s, want the 60s default", got)
	}
}

// WaitForCancellation and the heartbeat timeout change nothing visible when absent,
// until a cancelled deploy races its own teardown. Pinned for that
// reason; do not weaken.
func TestSilentOptionsArePinned(t *testing.T) {
	plan := srlinuxPlan(t)
	hostBound := map[string]workflow.ActivityOptions{
		"check host":    CheckHostOptions(),
		"stage":         StageOptions(),
		"deploy":        DeployOptions(plan),
		"readiness":     ReadinessOptions(plan[0], plan),
		"record":        RecordOptions(),
		"plan teardown": PlanTeardownOptions(),
		"destroy":       DestroyOptions(MaxDestroyTimeoutS(plan)),
		"unstage":       UnstageOptions(),
		"push":          PushOptions(plan[0], plan),
	}
	for name, o := range hostBound {
		if !o.WaitForCancellation {
			t.Errorf("%s: WaitForCancellation is off", name)
		}
		if o.RetryPolicy == nil {
			t.Fatalf("%s: no retry policy", name)
		}
		if !slices.Contains(o.RetryPolicy.NonRetryableErrorTypes, findings.RuleDeployFailed) {
			t.Errorf("%s: a tool's refusal would be retried: %v", name, o.RetryPolicy.NonRetryableErrorTypes)
		}
		wantAttempts := int32(RetryMaximumAttempts)
		if name == "readiness" {
			wantAttempts = 1
		}
		if o.RetryPolicy.MaximumAttempts != wantAttempts {
			t.Errorf("%s: MaximumAttempts = %d, want %d", name, o.RetryPolicy.MaximumAttempts, wantAttempts)
		}
	}
	for _, name := range []string{"deploy", "readiness", "destroy", "push"} {
		if got := hostBound[name].HeartbeatTimeout; got != 30*time.Second {
			t.Errorf("%s: HeartbeatTimeout = %s, want 30s", name, got)
		}
	}
}

// The push's mechanism constants: the budget is
// the package's, the margin, heartbeat and retry are the mechanism's (Constitution II). A
// push that could not be made is retried; a node's refusal is not.
func TestPushConstants(t *testing.T) {
	if PushVersionID != "push" {
		t.Errorf("PushVersionID = %q, want push", PushVersionID)
	}
	if PushMargin != 15*time.Second {
		t.Errorf("PushMargin = %s, want 15s", PushMargin)
	}
	plan := srlinuxPlan(t)
	if plan[0].Push.TimeoutS != 30 {
		t.Fatalf("the shipped package's push_timeout_s = %d, want 30", plan[0].Push.TimeoutS)
	}
	o := PushOptions(plan[0], plan)
	if o.RetryPolicy.MaximumAttempts != 3 {
		t.Errorf("MaximumAttempts = %d, want 3: a retry re-pushes the same bytes", o.RetryPolicy.MaximumAttempts)
	}
	if !slices.Contains(o.RetryPolicy.NonRetryableErrorTypes, findings.RulePushRefused) {
		t.Errorf("a node's refusal would be retried: %v", o.RetryPolicy.NonRetryableErrorTypes)
	}
	if slices.Contains(o.RetryPolicy.NonRetryableErrorTypes, findings.RulePushFailed) {
		t.Errorf("a push that could not be made would not be retried: %v", o.RetryPolicy.NonRetryableErrorTypes)
	}
}

// Following's mechanism constants.
func TestFollowingConstants(t *testing.T) {
	for _, c := range []struct {
		label     string
		got, want time.Duration
	}{
		{"InspectTwinBudget", InspectTwinBudget, 30 * time.Second},
		{"ShowServiceBudget", ShowServiceBudget, 5 * time.Second},
		{"InspectTwinOptions", InspectTwinOptions().StartToCloseTimeout, 30 * time.Second},
	} {
		if c.got != c.want {
			t.Errorf("%s = %s, want %s", c.label, c.got, c.want)
		}
	}
	if FollowScheduleID != "fylgja-follow" || WorkflowReconcile != "fylgja-reconcile" {
		t.Errorf("identities %q, %q; want fylgja-follow, fylgja-reconcile", FollowScheduleID, WorkflowReconcile)
	}
	o := InspectTwinOptions()
	if !o.WaitForCancellation {
		t.Error("InspectTwin is host-bound: WaitForCancellation is off")
	}
	if o.RetryPolicy == nil || o.RetryPolicy.MaximumAttempts != RetryMaximumAttempts {
		t.Errorf("inspect twin: retry policy %+v, want M2's, %d attempts", o.RetryPolicy, RetryMaximumAttempts)
	}
}

// A rehearsal's children: ABANDON and WaitForCancellation change nothing visible until a
// rehearsal is terminated or cancelled while a child runs. Every field is pinned, for the
// destroy and the provision.
func TestChildOptionsPinned(t *testing.T) {
	for _, id := range []string{WorkflowDestroy, WorkflowProvision} {
		want := workflow.ChildWorkflowOptions{
			WorkflowID:          id,
			TaskQueue:           "fylgja",
			ParentClosePolicy:   enumspb.PARENT_CLOSE_POLICY_ABANDON,
			WaitForCancellation: true,
		}
		if got := ChildOptions(id); !reflect.DeepEqual(got, want) {
			t.Errorf("ChildOptions(%s) = %+v\nwant %+v", id, got, want)
		}
	}
}

// The step adds no budget: each
// of its four activities runs under the option of the M2–M5 step whose work it shares, and
// the readiness and push it reuses are M2's and M5's own. Every field is compared, so a
// silent option dropped from one would fail here as TestSilentOptionsArePinned fails.
func TestStepOptionsAreTheirOrigins(t *testing.T) {
	plan := heterogeneousPlan(t)
	for _, c := range []struct {
		label     string
		got, want workflow.ActivityOptions
	}{
		{"plan reconcile = check host", PlanReconcileOptions(), CheckHostOptions()},
		{"stage step = stage", StageStepOptions(), StageOptions()},
		{"reconcile = deploy", ReconcileOptions(plan), DeployOptions(plan)},
		{"record step = record", RecordStepOptions(), RecordOptions()},
	} {
		if !reflect.DeepEqual(c.got, c.want) {
			t.Errorf("%s: %+v\nwant %+v", c.label, c.got, c.want)
		}
	}
	// The reconcile is budgeted by the slowest platform and heartbeats, as a deploy does.
	if got := ReconcileOptions(plan); got.StartToCloseTimeout != 600*time.Second || got.HeartbeatTimeout != HeartbeatTimeout ||
		!got.WaitForCancellation {
		t.Errorf("reconcile: StartToClose %s, HeartbeatTimeout %s, WaitForCancellation %v; want 600s, %s, true",
			got.StartToCloseTimeout, got.HeartbeatTimeout, got.WaitForCancellation, HeartbeatTimeout)
	}
	// The four are host-bound: each waits for a cancelled attempt to stop, which is what lets
	// the record step follow a cancelled stage, reconcile or push without racing it.
	for name, o := range map[string]workflow.ActivityOptions{
		"plan reconcile": PlanReconcileOptions(), "stage step": StageStepOptions(),
		"reconcile": ReconcileOptions(plan), "record step": RecordStepOptions(),
	} {
		if !o.WaitForCancellation {
			t.Errorf("%s: WaitForCancellation is off", name)
		}
	}
}

// The step's wait is bounded by the operator's budget plus the margin, both from its start
// and from its schedule, heartbeats, and holds a cancelled run until it has recorded its
// wait. Every field is compared: a
// silent option dropped or added fails here.
func TestVerifyOptionsPinned(t *testing.T) {
	if VerifyVersionID != "verify" {
		t.Errorf("VerifyVersionID = %q, want verify", VerifyVersionID)
	}
	if VerifyMargin != 30*time.Second {
		t.Errorf("VerifyMargin = %s, want 30s", VerifyMargin)
	}
	for _, budgetS := range []int{0, 30, 120} {
		bound := time.Duration(budgetS)*time.Second + 30*time.Second
		want := workflow.ActivityOptions{
			StartToCloseTimeout:    bound,
			ScheduleToCloseTimeout: bound,
			HeartbeatTimeout:       HeartbeatTimeout,
			WaitForCancellation:    true,
			RetryPolicy:            retryPolicy(RetryMaximumAttempts),
		}
		got := VerifyOptions(budgetS)
		if !reflect.DeepEqual(got, want) {
			t.Errorf("budget %ds: %+v\nwant %+v", budgetS, got, want)
		}
		if got.RetryPolicy.MaximumAttempts != 3 || !slices.Contains(got.RetryPolicy.NonRetryableErrorTypes, findings.RuleOperationFailed) {
			t.Errorf("budget %ds: retry %+v; want three attempts, operation.failed not retried", budgetS, got.RetryPolicy)
		}
	}
}

// A second step refuses rather than attaching to the first: the step's start options carry
// the fixed id and WorkflowExecutionErrorWhenAlreadyStarted, as a create's do
// (docs/development.md: start options are pinned, because their absence is silent).
func TestStepStartOptionsPinned(t *testing.T) {
	o := stepStartOptions()
	if o.ID != "fylgja-step" || o.TaskQueue != "fylgja" || !o.WorkflowExecutionErrorWhenAlreadyStarted ||
		o.WorkflowIDConflictPolicy != enumspb.WORKFLOW_ID_CONFLICT_POLICY_UNSPECIFIED {
		t.Errorf("start options = {ID:%q TaskQueue:%q WorkflowExecutionErrorWhenAlreadyStarted:%v WorkflowIDConflictPolicy:%v}, "+
			"want fylgja-step, fylgja, true, unspecified", o.ID, o.TaskQueue, o.WorkflowExecutionErrorWhenAlreadyStarted,
			o.WorkflowIDConflictPolicy)
	}
	if WorkflowStep != wire.StepWorkflowID {
		t.Errorf("WorkflowStep = %q, want the wire's %q", WorkflowStep, wire.StepWorkflowID)
	}
}

// A second rehearsal refuses rather than attaching to the first, as a second step does
// (015, D-051): the fixed id and WorkflowExecutionErrorWhenAlreadyStarted, whose absence is
// silent.
func TestRehearseStartOptionsPinned(t *testing.T) {
	o := rehearseStartOptions()
	if o.ID != "fylgja-rehearse" || o.TaskQueue != "fylgja" || !o.WorkflowExecutionErrorWhenAlreadyStarted ||
		o.WorkflowIDConflictPolicy != enumspb.WORKFLOW_ID_CONFLICT_POLICY_UNSPECIFIED {
		t.Errorf("start options = {ID:%q TaskQueue:%q WorkflowExecutionErrorWhenAlreadyStarted:%v WorkflowIDConflictPolicy:%v}, "+
			"want fylgja-rehearse, fylgja, true, unspecified", o.ID, o.TaskQueue, o.WorkflowExecutionErrorWhenAlreadyStarted,
			o.WorkflowIDConflictPolicy)
	}
	if WorkflowRehearse != wire.RehearseWorkflowID {
		t.Errorf("WorkflowRehearse = %q, want the wire's %q", WorkflowRehearse, wire.RehearseWorkflowID)
	}
}

// The deadline sums the bounds the children's activities run under, so the mechanism it is
// given must be those constants, each the one its activity's options use, and verify's
// default wait: internal/rehearsal cannot import them, and a constant moved here without
// the deadline would cut a rehearsal its own budgets allow (015, research R-09). With the
// shipped SR Linux package's budgets, the fixture's rehearsal (the branch point refused, two
// marks and the head) is 1,950 s, research §1.7's: the baseline's stop-following bound, 30 s,
// that 015's T082 added is gone with following (019, R-15).
func TestDeadlineMechanismIsTheConstants(t *testing.T) {
	m := DeadlineMechanism()
	for _, c := range []struct {
		field     string
		got, want time.Duration
	}{
		{"CheckHost", m.CheckHost, CheckHostBudget},
		{"Stage", m.Stage, StageBudget},
		{"Record", m.Record, RecordBudget},
		{"PlanTeardown", m.PlanTeardown, PlanTeardownBudget},
		{"Unstage", m.Unstage, UnstageBudget},
		{"InspectTwin", m.InspectTwin, InspectTwinBudget},
		{"ReadinessMargin", m.ReadinessMargin, ReadinessMargin},
		{"PushMargin", m.PushMargin, PushMargin},
		{"VerifyMargin", m.VerifyMargin, VerifyMargin},
		{"Wait", m.Wait, verify.DefaultBudget},
		// The options the children's activities run under, read rather than restated.
		{"CheckHost as CheckHostOptions", m.CheckHost, CheckHostOptions().StartToCloseTimeout},
		{"Stage as StageOptions", m.Stage, StageOptions().StartToCloseTimeout},
		{"Record as RecordOptions", m.Record, RecordOptions().StartToCloseTimeout},
		{"PlanTeardown as PlanTeardownOptions", m.PlanTeardown, PlanTeardownOptions().StartToCloseTimeout},
		{"Unstage as UnstageOptions", m.Unstage, UnstageOptions().StartToCloseTimeout},
		{"InspectTwin as InspectTwinOptions", m.InspectTwin, InspectTwinOptions().StartToCloseTimeout},
		{"Wait and VerifyMargin as VerifyOptions", m.Wait + m.VerifyMargin, VerifyOptions(int(verify.DefaultBudget / time.Second)).StartToCloseTimeout},
	} {
		if c.got != c.want {
			t.Errorf("%s = %s, want %s", c.field, c.got, c.want)
		}
	}
	if v := reflect.ValueOf(m); v.NumField() != 10 {
		t.Errorf("rehearsal.Mechanism has %d fields, want the ten this test compares", v.NumField())
	}

	plan := srlinuxPlan(t)
	stages := []rehearsal.DeadlineStage{{Role: rehearsal.RoleRefused}, {Role: rehearsal.RoleBaseline, Nodes: plan},
		{Role: rehearsal.RoleRehearsed, Nodes: plan}, {Role: rehearsal.RoleRehearsed, Nodes: plan}}
	if got := rehearsal.Deadline(m, stages); got != 1950*time.Second {
		t.Errorf("the fixture's deadline = %s, want 1950s (570 + 630 + 630 + 120)", got)
	}
}
