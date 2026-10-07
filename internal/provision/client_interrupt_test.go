package provision

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/mock"
	enumspb "go.temporal.io/api/enums/v1"
	historypb "go.temporal.io/api/history/v1"
	"go.temporal.io/api/serviceerror"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/mocks"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// An interrupt that arrives while the start request is in flight does not cut the request
// short: a run the service accepted needs its run id for the command to terminate it. The
// request completes, and the run is then terminated before any worker takes it, as
// run.cancelled at step start (contracts/cli.md create step 7). A step's start is
// the provisioning run's in this.
func TestInterruptDuringTheStartRequestTerminatesTheRun(t *testing.T) {
	for _, c := range []struct {
		name       string
		workflowID string
		start      func(context.Context, *Client) error
	}{
		{"provision", WorkflowProvision, func(ctx context.Context, c *Client) error {
			_, err := c.StartProvision(ctx, ProvisionInput{Source: wire.SourceIntent, Branch: "fylgja-fixture"})
			return err
		}},
		{"step", WorkflowStep, func(ctx context.Context, c *Client) error {
			_, err := c.StartStep(ctx, stepInput())
			return err
		}},
	} {
		t.Run(c.name, func(t *testing.T) {
			mc := &mocks.Client{}
			withWorker(mc)
			mc.On("DescribeWorkflowExecution", mock.Anything, mock.Anything, "").
				Return(nil, serviceerror.NewNotFound("workflow execution not found"))
			ctx, interrupt := context.WithCancel(context.Background())
			defer interrupt()

			run := &mocks.WorkflowRun{}
			run.On("GetRunID").Return("run-1")
			var sendErr error
			mc.On("ExecuteWorkflow", mock.Anything, mock.Anything, mock.Anything, mock.Anything).
				Run(func(args mock.Arguments) {
					interrupt() // the interrupt lands while the request is in flight
					sendErr = args.Get(0).(context.Context).Err()
				}).
				Return(run, nil)
			mc.On("GetWorkflowHistory", mock.Anything, c.workflowID, "run-1", true, enumspb.HISTORY_EVENT_FILTER_TYPE_ALL_EVENT).Return(
				func(ctx context.Context, _, _ string, _ bool, _ enumspb.HistoryEventFilterType) client.HistoryEventIterator {
					return &sliceHistory{ctx: ctx, wait: true, events: []*historypb.HistoryEvent{
						historyEvent(enumspb.EVENT_TYPE_WORKFLOW_EXECUTION_STARTED),
						historyEvent(enumspb.EVENT_TYPE_WORKFLOW_TASK_SCHEDULED),
					}}
				})
			mc.On("TerminateWorkflow", mock.Anything, c.workflowID, "run-1", mock.Anything).Return(nil)

			err := c.start(ctx, &Client{Client: mc, FirstTaskGuard: time.Minute})

			if sendErr != nil {
				t.Errorf("the start request's context was ended by the interrupt (%v): a run the service accepted would be left with no run id to terminate", sendErr)
			}
			var refused *StartError
			if !errors.As(err, &refused) {
				t.Fatalf("error %v, want a refusal to start", err)
			}
			if f := refused.Finding; refused.Status != findings.StatusError || f.Rule != findings.RuleRunCancelled ||
				f.Object != "run-1" || f.Step != findings.StepStart {
				t.Errorf("refusal %+v, want run.cancelled (exit 2) at start on run-1", refused)
			}
			mc.AssertCalled(t, "TerminateWorkflow", mock.Anything, c.workflowID, "run-1", mock.Anything)
		})
	}
}

// A start interrupted while it waits for a worker to take the run terminates the run, on a
// context the interrupt does not reach, and is refused as run.cancelled: nothing in the run
// ran, and nothing is left for a worker to take later.
func TestInterruptWhileAwaitingTheFirstTaskTerminatesTheRun(t *testing.T) {
	for _, c := range []struct {
		name         string
		terminateErr error
		want         string
	}{
		{"terminated", nil, "terminated before anything in it ran"},
		{"terminating fails", errors.New("service busy"), "fylgja twin destroy"},
	} {
		t.Run(c.name, func(t *testing.T) {
			mc := &mocks.Client{}
			withWorker(mc)
			noStepRun(mc)
			run := &mocks.WorkflowRun{}
			run.On("GetRunID").Return("run-1")
			mc.On("ExecuteWorkflow", mock.Anything, mock.Anything, mock.Anything, mock.Anything).Return(run, nil)
			mc.On("GetWorkflowHistory", mock.Anything, WorkflowProvision, "run-1", true, enumspb.HISTORY_EVENT_FILTER_TYPE_ALL_EVENT).Return(
				func(ctx context.Context, _, _ string, _ bool, _ enumspb.HistoryEventFilterType) client.HistoryEventIterator {
					return &sliceHistory{ctx: ctx, wait: true, events: []*historypb.HistoryEvent{
						historyEvent(enumspb.EVENT_TYPE_WORKFLOW_EXECUTION_STARTED),
						historyEvent(enumspb.EVENT_TYPE_WORKFLOW_TASK_SCHEDULED),
					}}
				})
			var terminateCtxErr error
			mc.On("TerminateWorkflow", mock.Anything, WorkflowProvision, "run-1", mock.Anything).
				Run(func(args mock.Arguments) { terminateCtxErr = args.Get(0).(context.Context).Err() }).
				Return(c.terminateErr)

			ctx, interrupt := context.WithCancel(context.Background())
			defer interrupt()
			time.AfterFunc(50*time.Millisecond, interrupt)
			began := time.Now()

			_, err := (&Client{Client: mc, FirstTaskGuard: time.Minute}).StartProvision(ctx,
				ProvisionInput{Source: wire.SourceIntent, Branch: "fylgja-fixture"})

			var refused *StartError
			if !errors.As(err, &refused) {
				t.Fatalf("error %v, want a refusal to start", err)
			}
			f := refused.Finding
			if refused.Status != findings.StatusError || f.Rule != findings.RuleRunCancelled || f.Object != "run-1" ||
				f.Step != findings.StepStart || !strings.Contains(f.Message, c.want) {
				t.Errorf("refusal %+v, want run.cancelled (exit 2) at start on run-1 saying %q", refused, c.want)
			}
			mc.AssertCalled(t, "TerminateWorkflow", mock.Anything, WorkflowProvision, "run-1", mock.Anything)
			if terminateCtxErr != nil {
				t.Errorf("the run was terminated on a context already ended (%v); the interrupt must not stop the terminate", terminateCtxErr)
			}
			if elapsed := time.Since(began); elapsed > 5*time.Second {
				t.Errorf("the interrupted start took %s, want about 50ms rather than the guard", elapsed)
			}
		})
	}
}
