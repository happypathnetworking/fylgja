package provision

import (
	"context"
	"slices"
	"testing"

	"github.com/stretchr/testify/mock"
	commonpb "go.temporal.io/api/common/v1"
	enumspb "go.temporal.io/api/enums/v1"
	historypb "go.temporal.io/api/history/v1"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/converter"
	"go.temporal.io/sdk/mocks"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// scheduledEvent is an activity scheduled in a run's history, with its input.
func scheduledEvent(t *testing.T, id int64, activityType string, input ...any) *historypb.HistoryEvent {
	t.Helper()
	payloads, err := converter.GetDefaultDataConverter().ToPayloads(input...)
	if err != nil {
		t.Fatal(err)
	}
	return &historypb.HistoryEvent{EventId: id, EventType: enumspb.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED,
		Attributes: &historypb.HistoryEvent_ActivityTaskScheduledEventAttributes{
			ActivityTaskScheduledEventAttributes: &historypb.ActivityTaskScheduledEventAttributes{
				ActivityType: &commonpb.ActivityType{Name: activityType}, Input: payloads,
			}}}
}

// failedEvent is the activity scheduled as event scheduledID failing.
func failedEvent(scheduledID int64) *historypb.HistoryEvent {
	return &historypb.HistoryEvent{EventType: enumspb.EVENT_TYPE_ACTIVITY_TASK_FAILED,
		Attributes: &historypb.HistoryEvent_ActivityTaskFailedEventAttributes{
			ActivityTaskFailedEventAttributes: &historypb.ActivityTaskFailedEventAttributes{ScheduledEventId: scheduledID},
		}}
}

// Every step event Follow reports names the run it belongs to and its step as findings name
// it, so a command that fails while following a run can name where the run had got to, and
// a destroy can tell its own steps from those of the provisioning run it waited for.
func TestFollowEventsNameTheirRunAndStep(t *testing.T) {
	type seen struct{ step, workflowID, findingStep string }
	follow := func(workflowID string, events ...*historypb.HistoryEvent) []seen {
		t.Helper()
		mc := &mocks.Client{}
		events = append(events, historyEvent(enumspb.EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED))
		mc.On("GetWorkflowHistory", mock.Anything, workflowID, "run-1", true, enumspb.HISTORY_EVENT_FILTER_TYPE_ALL_EVENT).Return(
			func(ctx context.Context, _, _ string, _ bool, _ enumspb.HistoryEventFilterType) client.HistoryEventIterator {
				return &sliceHistory{ctx: ctx, events: events}
			})
		var got []seen
		err := (&Client{Client: mc}).Follow(context.Background(), workflowID, "run-1", func(e Event) {
			got = append(got, seen{e.Step, e.WorkflowID, e.FindingStep})
		})
		if err != nil {
			t.Fatal(err)
		}
		return got
	}

	provisioning := follow(WorkflowProvision,
		scheduledEvent(t, 5, wire.ActDeployLab, wire.DeployInput{}),
		failedEvent(5),
		scheduledEvent(t, 7, wire.ActAwaitReadiness, wire.ReadinessInput{Node: "n1"}),
		scheduledEvent(t, 8, wire.ActPushConfig, wire.PushInput{Node: "n2"}),
		scheduledEvent(t, 9, wire.ActDestroyLab, wire.DestroyLabInput{}),
	)
	want := []seen{
		{"deploy", WorkflowProvision, findings.StepDeploy},
		{"deploy", WorkflowProvision, findings.StepDeploy},
		{"readiness n1", WorkflowProvision, findings.StepReadiness},
		{"push n2", WorkflowProvision, findings.StepPush}, // M5: one push per node, named by it
		{"cleanup teardown", WorkflowProvision, findings.StepTeardown},
	}
	if !slices.Equal(provisioning, want) {
		t.Errorf("provisioning run events %+v, want %+v", provisioning, want)
	}

	destroying := follow(WorkflowDestroy,
		scheduledEvent(t, 5, wire.ActPlanTeardown),
		scheduledEvent(t, 7, wire.ActUnstageTwin),
	)
	want = []seen{
		{"plan teardown", WorkflowDestroy, findings.StepTeardown},
		{"unstage", WorkflowDestroy, findings.StepUnstage},
	}
	if !slices.Equal(destroying, want) {
		t.Errorf("destroy run events %+v, want %+v", destroying, want)
	}
}

// Every activity a worker registers belongs to a step the findings schema names, so a new
// activity without one fails here rather than reporting a failure with no step.
func TestEveryActivityHasAFindingStep(t *testing.T) {
	schemaSteps := []string{findings.StepVerify, findings.StepStart, findings.StepRead, findings.StepCompile,
		findings.StepHostCheck, findings.StepStage, findings.StepDeploy, findings.StepReadiness, findings.StepRecord,
		findings.StepTeardown, findings.StepUnstage,
		// M4's additions to the step enum.
		findings.StepInspect, findings.StepCompare, findings.StepDestroy, findings.StepProvision, findings.StepFollow,
		// M5's.
		findings.StepPush,
		// M11's.
		findings.StepReconcile,
		// M12's.
		findings.StepObserve}
	var names []string
	for name := range (&ControlActivities{}).Names() {
		names = append(names, name)
	}
	for name := range (&lab.Activities{}).Names() {
		names = append(names, name)
	}
	if len(names) != 20 {
		t.Fatalf("%d activities registered, want M2's ten, M4's four (InspectTwin, RunsInFlight, StartFollowing, StopFollowing), "+
			"M5's push, M11's four (PlanReconcile, StageStep, ReconcileLab, RecordStep) and M12's VerifyTwin",
			len(names))
	}
	for _, name := range names {
		if step := findingStep(name); !slices.Contains(schemaSteps, step) {
			t.Errorf("activity %s belongs to step %q, not one the findings schema names", name, step)
		}
	}
}

// A check's children are steps of the check, and each child's own steps are followed where
// it starts, under its own run: a destroy that cancels a check shows the child's cleanup.
func TestFollowFollowsACheckChild(t *testing.T) {
	const check = "fylgja-reconcile-2026-09-16T19:10:00Z"
	initiated := &historypb.HistoryEvent{EventId: 11, EventType: enumspb.EVENT_TYPE_START_CHILD_WORKFLOW_EXECUTION_INITIATED,
		Attributes: &historypb.HistoryEvent_StartChildWorkflowExecutionInitiatedEventAttributes{
			StartChildWorkflowExecutionInitiatedEventAttributes: &historypb.StartChildWorkflowExecutionInitiatedEventAttributes{
				WorkflowId: WorkflowProvision, WorkflowType: &commonpb.WorkflowType{Name: "Provision"},
			}}}
	started := &historypb.HistoryEvent{EventId: 12, EventType: enumspb.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_STARTED,
		Attributes: &historypb.HistoryEvent_ChildWorkflowExecutionStartedEventAttributes{
			ChildWorkflowExecutionStartedEventAttributes: &historypb.ChildWorkflowExecutionStartedEventAttributes{
				InitiatedEventId:  11,
				WorkflowExecution: &commonpb.WorkflowExecution{WorkflowId: WorkflowProvision, RunId: "run-p"},
			}}}
	cancelled := &historypb.HistoryEvent{EventId: 13, EventType: enumspb.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_CANCELED,
		Attributes: &historypb.HistoryEvent_ChildWorkflowExecutionCanceledEventAttributes{
			ChildWorkflowExecutionCanceledEventAttributes: &historypb.ChildWorkflowExecutionCanceledEventAttributes{InitiatedEventId: 11},
		}}

	mc := &mocks.Client{}
	histories := map[string][]*historypb.HistoryEvent{
		check: {scheduledEvent(t, 5, wire.ActInspectTwin), initiated, started, cancelled,
			historyEvent(enumspb.EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED)},
		WorkflowProvision: {scheduledEvent(t, 5, wire.ActDestroyLab, wire.DestroyLabInput{}),
			historyEvent(enumspb.EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED)},
	}
	mc.On("GetWorkflowHistory", mock.Anything, mock.Anything, mock.Anything, true, enumspb.HISTORY_EVENT_FILTER_TYPE_ALL_EVENT).Return(
		func(ctx context.Context, workflowID, _ string, _ bool, _ enumspb.HistoryEventFilterType) client.HistoryEventIterator {
			return &sliceHistory{ctx: ctx, events: histories[workflowID]}
		})

	type seen struct{ step, workflowID, findingStep, outcome, notice string }
	var got []seen
	err := (&Client{Client: mc}).Follow(context.Background(), check, "run-c", func(e Event) {
		got = append(got, seen{e.Step, e.WorkflowID, e.FindingStep, e.Outcome, e.Notice})
	})
	if err != nil {
		t.Fatal(err)
	}
	want := []seen{
		{"inspect", check, findings.StepInspect, "", ""},
		{"provision", check, findings.StepProvision, "", ""},
		{"", "", "", "", "run fylgja-provision run-p"},
		{"cleanup teardown", WorkflowProvision, findings.StepTeardown, "", ""},
		{"provision", check, findings.StepProvision, EventCancelled, ""},
	}
	if !slices.Equal(got, want) {
		t.Errorf("events\n  %+v\nwant\n  %+v", got, want)
	}
}

// completedWith is the activity scheduled as event scheduledID completing with result.
func completedWith(t *testing.T, scheduledID int64, result any) *historypb.HistoryEvent {
	t.Helper()
	payloads, err := converter.GetDefaultDataConverter().ToPayloads(result)
	if err != nil {
		t.Fatal(err)
	}
	return &historypb.HistoryEvent{EventType: enumspb.EVENT_TYPE_ACTIVITY_TASK_COMPLETED,
		Attributes: &historypb.HistoryEvent_ActivityTaskCompletedEventAttributes{
			ActivityTaskCompletedEventAttributes: &historypb.ActivityTaskCompletedEventAttributes{ScheduledEventId: scheduledID,
				Result: payloads}}}
}

// A step run's progress names its inspection and its four activities as contracts/cli.md
// prints them, each with the step findings name it by, and the plan and the reconcile with
// what they did: "plan reconcile: done (restart e1)", "reconcile: done (3 nodes)".
func TestFollowNamesTheStepsOfAStep(t *testing.T) {
	type seen struct{ step, findingStep, detail string }
	mc := &mocks.Client{}
	events := []*historypb.HistoryEvent{
		scheduledEvent(t, 5, wire.ActInspectTwin),
		scheduledEvent(t, 7, wire.ActPlanReconcile, wire.PlanReconcileInput{}), completedWith(t, 7, stepPlan()),
		scheduledEvent(t, 9, wire.ActStageStep, wire.StageStepInput{}),
		scheduledEvent(t, 11, wire.ActReconcileLab, wire.ReconcileInput{}),
		completedWith(t, 11, wire.ReconcileResult{Nodes: stepLab(), TookS: 3.9}),
		scheduledEvent(t, 13, wire.ActAwaitReadiness, wire.ReadinessInput{Node: "e1"}),
		scheduledEvent(t, 15, wire.ActPushConfig, wire.PushInput{Node: "s1"}),
		scheduledEvent(t, 17, wire.ActRecordStep, wire.RecordStepInput{}),
		historyEvent(enumspb.EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED),
	}
	mc.On("GetWorkflowHistory", mock.Anything, WorkflowStep, "run-s", true, enumspb.HISTORY_EVENT_FILTER_TYPE_ALL_EVENT).Return(
		func(ctx context.Context, _, _ string, _ bool, _ enumspb.HistoryEventFilterType) client.HistoryEventIterator {
			return &sliceHistory{ctx: ctx, events: events}
		})
	var got []seen
	if err := (&Client{Client: mc}).Follow(context.Background(), WorkflowStep, "run-s", func(e Event) {
		got = append(got, seen{e.Step, e.FindingStep, e.Detail})
	}); err != nil {
		t.Fatal(err)
	}
	want := []seen{
		{"inspect", findings.StepInspect, ""},
		{"plan reconcile", findings.StepCompare, ""},
		{"plan reconcile", findings.StepCompare, "restart e1"},
		{"stage", findings.StepStage, ""},
		{"reconcile", findings.StepReconcile, ""},
		{"reconcile", findings.StepReconcile, "3 nodes"},
		{"readiness e1", findings.StepReadiness, ""},
		{"push s1", findings.StepPush, ""},
		{"record", findings.StepRecord, ""},
	}
	if !slices.Equal(got, want) {
		t.Errorf("events\n  %+v\nwant\n  %+v", got, want)
	}
}

// The plan reconcile step's detail names each lifecycle with its nodes, the live nodes when
// there is nothing else, and an empty plan as nothing to apply.
func TestPlanDetail(t *testing.T) {
	for _, c := range []struct {
		plan wire.ReconcilePlan
		want string
	}{
		{wire.ReconcilePlan{}, "nothing to apply"},
		{stepPlan(), "restart e1"},
		{wire.ReconcilePlan{Restarted: []string{"e1"}, Recreated: []string{"s2"}, Added: []string{"s3"}, Deleted: []string{"s4"}},
			"restart e1; recreate s2; create s3; delete s4"},
		{wire.ReconcilePlan{LinksAdded: []string{"s1:e1-3 -- s2:e1-3"}}, "live s1, s2"},
	} {
		if got := planDetail(c.plan); got != c.want {
			t.Errorf("planDetail(%+v) = %q, want %q", c.plan, got, c.want)
		}
	}
}
