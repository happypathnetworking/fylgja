package provision

// Deterministic: imported by workflow code. Durations only, never the clock.

import (
	"time"

	enumspb "go.temporal.io/api/enums/v1"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/rehearsal"
	"github.com/happypathnetworking/fylgja/internal/verify"
)

// Mechanism constants: they bound the machinery, never how long a platform may take.
// Every duration a platform decides (deploy, readiness, teardown) comes from its
// package through the node plan (Constitution II).
const (
	// HeartbeatTimeout is how long a heartbeating activity may go silent before its
	// worker is presumed dead and the attempt is retried.
	HeartbeatTimeout = 30 * time.Second
	// ReadinessMargin is added to a node's readiness timeout for its activity's
	// start-to-close: one probe attempt's 5s deadline plus scheduling.
	ReadinessMargin = 15 * time.Second
	// DefaultDestroyBudget stands in only for a platform no package covers: the one
	// stated default.
	DefaultDestroyBudget = wire.DefaultDestroyTimeoutS * time.Second

	RetryMaximumAttempts    = 3
	RetryInitialInterval    = 2 * time.Second
	RetryBackoffCoefficient = 2.0

	// Fixed bounds of the steps no platform affects.
	CheckHostBudget    = 30 * time.Second
	StageBudget        = 60 * time.Second
	RecordBudget       = 30 * time.Second
	PlanTeardownBudget = 30 * time.Second
	UnstageBudget      = 30 * time.Second

	// PushMargin is added to a node's push_timeout_s for its activity's start-to-close: the
	// request is cut off at the package's budget, and the margin lets the activity say so
	// rather than be timed out itself.
	PushMargin = 15 * time.Second

	// VerifyMargin is added to the step's wait budget for VerifyTwin's start-to-close and
	// schedule-to-close: one read of the largest twin this host runs, plus scheduling (a
	// read of the three-node twin is 15 paths, about 1–2s), so the activity ends its wait
	// and records it rather than being timed out itself.
	VerifyMargin = 30 * time.Second

	// Reads that change nothing.

	// InspectTwinBudget bounds InspectTwin, which only reads.
	InspectTwinBudget = 30 * time.Second
	// ShowServiceBudget bounds twin show's whole conversation with the workflow service;
	// past it the service is reported unreachable.
	ShowServiceBudget = 5 * time.Second
)

// nonRetryableTypes are the error types activities fail with when retrying cannot help:
// a tool that refused, a node that never answered, a path that would not write. They are
// the rule identifiers the failure is reported under. Only worker death (a heartbeat
// timeout) and transport errors are retried.
func nonRetryableTypes() []string {
	return []string{
		findings.RuleOperationFailed,
		findings.RuleStageFailed,
		findings.RuleDeployFailed,
		findings.RuleReadinessTimeout,
		findings.RuleRecordFailed,
		findings.RuleCleanupIncomplete,
		findings.RulePushRefused,
	}
}

func retryPolicy(maxAttempts int32) *temporal.RetryPolicy {
	return &temporal.RetryPolicy{
		InitialInterval:        RetryInitialInterval,
		BackoffCoefficient:     RetryBackoffCoefficient,
		MaximumAttempts:        maxAttempts,
		NonRetryableErrorTypes: nonRetryableTypes(),
	}
}

// hostBoundOptions are for internal/lab's activities. WaitForCancellation is on for
// every one: without it a cancelled activity is reported stopped before it has, and
// cleanup races a clab still acting on the host. Its absence is silent,
// which is why a test pins it.
func hostBoundOptions(startToClose time.Duration, heartbeat bool) workflow.ActivityOptions {
	o := workflow.ActivityOptions{
		StartToCloseTimeout: startToClose,
		WaitForCancellation: true,
		RetryPolicy:         retryPolicy(RetryMaximumAttempts),
	}
	if heartbeat {
		o.HeartbeatTimeout = HeartbeatTimeout
	}
	return o
}

func seconds(s int) time.Duration { return time.Duration(s) * time.Second }

// CheckHostOptions bound CheckHost, which only reads.
func CheckHostOptions() workflow.ActivityOptions { return hostBoundOptions(CheckHostBudget, false) }

// StageOptions bound StageBundle.
func StageOptions() workflow.ActivityOptions { return hostBoundOptions(StageBudget, false) }

// DeployOptions bound DeployLab by the largest deploy_timeout_s among the bundle's
// platforms: nodes start concurrently, so the slowest platform sets the step.
func DeployOptions(nodes []wire.NodePlan) workflow.ActivityOptions {
	longest := 0
	for _, n := range nodes {
		longest = max(longest, n.DeployTimeoutS)
	}
	return hostBoundOptions(seconds(longest), true)
}

// ReadinessOptions bound one node's AwaitReadiness in two ways. Each attempt gets
// its own package's timeout plus the margin, never a global value. Everything from
// scheduling gets the readiness step's budget over the plan, so an activity no worker
// starts, its worker lost before taking it, fails within the step's budget instead of
// waiting without bound. One attempt: the node's timeout is the rule, so a worker that
// dies while waiting fails the run and cleanup follows.
func ReadinessOptions(node wire.NodePlan, plan []wire.NodePlan) workflow.ActivityOptions {
	o := hostBoundOptions(seconds(node.TimeoutS)+ReadinessMargin, true)
	o.ScheduleToCloseTimeout = ReadinessStepBudget(plan)
	o.RetryPolicy.MaximumAttempts = 1
	return o
}

// ReadinessStepBudget is the readiness step's overall budget: the largest per-node
// timeout among the bundle's platforms plus the margin. ReadinessOptions sets it as
// every node's schedule-to-close timeout.
func ReadinessStepBudget(nodes []wire.NodePlan) time.Duration {
	longest := 0
	for _, n := range nodes {
		longest = max(longest, n.TimeoutS)
	}
	return seconds(longest) + ReadinessMargin
}

// PushVersionID is the GetVersion change id under which the provisioning run gained its
// push step: histories recorded before it replay at DefaultVersion and skip the step.
const PushVersionID = "push"

// VerifyVersionID is the GetVersion change id under which the step run gained its wait
// after the record: M11's two step histories replay at DefaultVersion and skip it.
const VerifyVersionID = "verify"

// PushOptions bound one node's PushConfig. Each attempt gets its own package's
// push_timeout_s plus the margin, never a global value; waiting for a worker to take an
// attempt is bounded by the push step's budget, so a push no worker starts fails instead of
// waiting without bound, as readiness's does. Three attempts: a push that could not be made
// is retried, and a retry sends the same bytes, which the node commits to the same state.
// It heartbeats, and WaitForCancellation holds a cancelled run until the push has
// stopped, so cleanup never races a commit.
func PushOptions(node wire.NodePlan, plan []wire.NodePlan) workflow.ActivityOptions {
	o := hostBoundOptions(seconds(node.Push.TimeoutS)+PushMargin, true)
	o.ScheduleToStartTimeout = PushStepBudget(plan)
	return o
}

// PushStepBudget is the push step's budget: the largest push_timeout_s among the bundle's
// platforms plus the margin, as ReadinessStepBudget is readiness's. PushOptions sets it as
// every attempt's schedule-to-start timeout.
func PushStepBudget(nodes []wire.NodePlan) time.Duration {
	longest := 0
	for _, n := range nodes {
		longest = max(longest, n.Push.TimeoutS)
	}
	return seconds(longest) + PushMargin
}

// RecordOptions bound RecordTwin.
func RecordOptions() workflow.ActivityOptions { return hostBoundOptions(RecordBudget, false) }

// MaxDestroyTimeoutS is the largest destroy_timeout_s among the plan's nodes: provision's
// cleanup budget.
func MaxDestroyTimeoutS(nodes []wire.NodePlan) int {
	longest := 0
	for _, n := range nodes {
		longest = max(longest, n.DestroyTimeoutS)
	}
	return longest
}

// PlanTeardownOptions bound PlanTeardown, which only reads.
func PlanTeardownOptions() workflow.ActivityOptions {
	return hostBoundOptions(PlanTeardownBudget, false)
}

// DestroyOptions bound DestroyLab by a teardown budget in seconds: MaxDestroyTimeoutS of
// the plan in provision's cleanup, PlanTeardown's answer in Destroy. Zero means no
// package covered anything, and the stated default stands in.
func DestroyOptions(destroyTimeoutS int) workflow.ActivityOptions {
	budget := seconds(destroyTimeoutS)
	if destroyTimeoutS <= 0 {
		budget = DefaultDestroyBudget
	}
	return hostBoundOptions(budget, true)
}

// UnstageOptions bound UnstageTwin.
func UnstageOptions() workflow.ActivityOptions { return hostBoundOptions(UnstageBudget, false) }

// InspectTwinOptions bound InspectTwin, a step's host-bound read of the twin.
func InspectTwinOptions() workflow.ActivityOptions {
	return hostBoundOptions(InspectTwinBudget, false)
}

// The step run's options. A step adds no
// budget of its own: each of its activities runs under the M2–M5
// option whose work it shares, so every duration a platform decides is still its package's.

// PlanReconcileOptions bound PlanReconcile, which only reads: containerlab's dry run took
// 0.4s, so it runs under the host check's bound.
func PlanReconcileOptions() workflow.ActivityOptions { return CheckHostOptions() }

// StageStepOptions bound StageStep: a copy from the store and two renames, as StageBundle is.
func StageStepOptions() workflow.ActivityOptions { return StageOptions() }

// ReconcileOptions bound ReconcileLab by the largest deploy_timeout_s among the target's
// platforms, heartbeating, as DeployLab is: a reconcile restarts, recreates or creates
// nodes as a deploy starts them, and a node add (31.3s live) and a recreate (20.3s) sit
// inside that budget.
func ReconcileOptions(nodes []wire.NodePlan) workflow.ActivityOptions { return DeployOptions(nodes) }

// RecordStepOptions bound RecordStep, which writes twin.json as RecordTwin does.
func RecordStepOptions() workflow.ActivityOptions { return RecordOptions() }

// VerifyOptions bound VerifyTwin, the step's wait after its record: the operator's budget,
// twin step --wait or verify's one default, plus
// VerifyMargin, as both its start-to-close and its schedule-to-close, so the three attempts
// share one window and a retry cannot extend the budget. It heartbeats for the whole wait,
// and WaitForCancellation holds a cancelled run until the activity has recorded the wait
// cancelled. A budget of 0 reads once.
func VerifyOptions(budgetS int) workflow.ActivityOptions {
	o := hostBoundOptions(seconds(budgetS)+VerifyMargin, true)
	o.ScheduleToCloseTimeout = o.StartToCloseTimeout
	return o
}

// ChildOptions run a rehearsal's provision, steps and destroy as its children, each under
// its fixed id. ABANDON keeps a child running to its own cleanup when the rehearsal is
// terminated; WaitForCancellation makes a cancelled rehearsal wait for the child's cleanup
// before it closes. Their absence is silent, which is why a test pins them.
func ChildOptions(workflowID string) workflow.ChildWorkflowOptions {
	return workflow.ChildWorkflowOptions{
		WorkflowID:          workflowID,
		TaskQueue:           TaskQueue,
		ParentClosePolicy:   enumspb.PARENT_CLOSE_POLICY_ABANDON,
		WaitForCancellation: true,
	}
}

// DeadlineMechanism is the mechanism constants a rehearsal's deadline sums (015, research
// R-09): the bound of each activity its children run that no package decides, the margins
// each package's own budget is given, and verify's one default wait, which every stage of a
// rehearsal waits. internal/rehearsal takes them as a value, so it imports neither this
// package nor verify.
func DeadlineMechanism() rehearsal.Mechanism {
	return rehearsal.Mechanism{
		CheckHost:       CheckHostBudget,
		Stage:           StageBudget,
		Record:          RecordBudget,
		PlanTeardown:    PlanTeardownBudget,
		Unstage:         UnstageBudget,
		InspectTwin:     InspectTwinBudget,
		ReadinessMargin: ReadinessMargin,
		PushMargin:      PushMargin,
		VerifyMargin:    VerifyMargin,
		Wait:            verify.DefaultBudget,
	}
}
