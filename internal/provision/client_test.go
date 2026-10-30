package provision

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"maps"
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/santhosh-tekuri/jsonschema/v6"
	"github.com/stretchr/testify/mock"
	commonpb "go.temporal.io/api/common/v1"
	enumspb "go.temporal.io/api/enums/v1"
	historypb "go.temporal.io/api/history/v1"
	"go.temporal.io/api/serviceerror"
	taskqueuepb "go.temporal.io/api/taskqueue/v1"
	workflowpb "go.temporal.io/api/workflow/v1"
	"go.temporal.io/api/workflowservice/v1"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/converter"
	"go.temporal.io/sdk/mocks"
	"go.temporal.io/sdk/temporal"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// sliceHistory is a run's history as the long-poll iterator yields it: the events, then,
// when wait is set, nothing more until ctx is done — a run no worker takes — and otherwise
// the end.
type sliceHistory struct {
	ctx    context.Context
	events []*historypb.HistoryEvent
	wait   bool
	err    error
}

func (h *sliceHistory) HasNext() bool {
	if len(h.events) > 0 || h.err != nil {
		return true
	}
	if h.wait {
		h.wait = false
		<-h.ctx.Done()
		h.err = h.ctx.Err()
		return true
	}
	return false
}

func (h *sliceHistory) Next() (*historypb.HistoryEvent, error) {
	if len(h.events) > 0 {
		ev := h.events[0]
		h.events = h.events[1:]
		return ev, nil
	}
	err := h.err
	h.err = nil
	return nil, err
}

func historyEvent(t enumspb.EventType) *historypb.HistoryEvent {
	return &historypb.HistoryEvent{EventType: t}
}

// withWorker answers the poller check as a service one worker polls.
func withWorker(mc *mocks.Client) {
	mc.On("DescribeTaskQueue", mock.Anything, TaskQueue, enumspb.TASK_QUEUE_TYPE_WORKFLOW).Return(
		&workflowservice.DescribeTaskQueueResponse{Pollers: []*taskqueuepb.PollerInfo{{Identity: "worker@lab"}}}, nil)
}

// noStepRun answers that no step run is in flight: a create asks before it starts, and
// InFlight lists one.
func noStepRun(mc *mocks.Client) {
	mc.On("DescribeWorkflowExecution", mock.Anything, WorkflowStep, "").
		Return(nil, serviceerror.NewNotFound("workflow execution not found"))
}

// firstTaskTaken answers every history read with a run whose first task a worker took.
func firstTaskTaken(mc *mocks.Client) {
	mc.On("GetWorkflowHistory", mock.Anything, mock.Anything, mock.Anything, true, enumspb.HISTORY_EVENT_FILTER_TYPE_ALL_EVENT).Return(
		func(ctx context.Context, _, _ string, _ bool, _ enumspb.HistoryEventFilterType) client.HistoryEventIterator {
			return &sliceHistory{ctx: ctx, events: []*historypb.HistoryEvent{
				historyEvent(enumspb.EVENT_TYPE_WORKFLOW_EXECUTION_STARTED),
				historyEvent(enumspb.EVENT_TYPE_WORKFLOW_TASK_SCHEDULED),
				historyEvent(enumspb.EVENT_TYPE_WORKFLOW_TASK_STARTED),
			}}
		})
}

// called lists the methods a mock client saw, in order.
func called(mc *mocks.Client) []string {
	var names []string
	for _, c := range mc.Calls {
		names = append(names, c.Method)
	}
	return names
}

// The start options are pinned because their absence is silent: without
// WorkflowExecutionErrorWhenAlreadyStarted a second create attaches to the first and
// reports its result as its own.
func TestProvisionStartOptionsPinned(t *testing.T) {
	mc := &mocks.Client{}
	withWorker(mc)
	noStepRun(mc)
	firstTaskTaken(mc)
	run := &mocks.WorkflowRun{}
	run.On("GetRunID").Return("run-1")
	var captured client.StartWorkflowOptions
	mc.On("ExecuteWorkflow", mock.Anything, mock.Anything, mock.Anything, mock.Anything).
		Run(func(args mock.Arguments) { captured = args.Get(1).(client.StartWorkflowOptions) }).
		Return(run, nil)

	c := &Client{Client: mc}
	runID, err := c.StartProvision(context.Background(), ProvisionInput{Source: wire.SourceIntent, Branch: "fylgja-fixture"})
	if err != nil {
		t.Fatal(err)
	}
	if runID != "run-1" {
		t.Errorf("run id = %q, want the started run's", runID)
	}
	if captured.ID != "fylgja-provision" || captured.TaskQueue != "fylgja" || !captured.WorkflowExecutionErrorWhenAlreadyStarted {
		t.Errorf("start options = {ID:%q TaskQueue:%q WorkflowExecutionErrorWhenAlreadyStarted:%v}, want fylgja-provision, fylgja, true",
			captured.ID, captured.TaskQueue, captured.WorkflowExecutionErrorWhenAlreadyStarted)
	}
	mc.AssertExpectations(t)
	if slices.Contains(called(mc), "TerminateWorkflow") {
		t.Error("a run a worker took was terminated")
	}
}

// A second create while one runs is refused, exit 1, naming the run in flight.
func TestAlreadyStartedIsRunInFlight(t *testing.T) {
	mc := &mocks.Client{}
	withWorker(mc)
	noStepRun(mc)
	mc.On("ExecuteWorkflow", mock.Anything, mock.Anything, mock.Anything, mock.Anything).
		Return(nil, serviceerror.NewWorkflowExecutionAlreadyStarted(
			"Workflow execution is already running. WorkflowId: fylgja-provision, RunId: run-0.", "request-1", "run-0"))

	_, err := (&Client{Client: mc}).StartProvision(context.Background(), ProvisionInput{Source: wire.SourceIntent})
	var refused *StartError
	if !errors.As(err, &refused) {
		t.Fatalf("error = %v, want a *StartError", err)
	}
	doc := refused.Document(findings.OpTwinCreate, &findings.Subject{Branch: "fylgja-fixture"})
	if code := doc.Status.ExitCode(); code != findings.ExitRejected {
		t.Errorf("exit = %d, want %d", code, findings.ExitRejected)
	}
	if len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleRunInFlight {
		t.Fatalf("findings = %+v, want one %s", doc.Findings, findings.RuleRunInFlight)
	}
	if f := doc.Findings[0]; !strings.Contains(f.Message, "run-0") || f.Object != WorkflowProvision || f.Step != findings.StepStart {
		t.Errorf("finding = %+v, want object %s, step start and the run id in the message", f, WorkflowProvision)
	}
	mustValidateM2(t, doc, "run.in_flight")
}

// Every outcome maps to its status, with the block that status
// carries, and every document satisfies the contract. A cancelled run names itself under
// run.cancelled. A ready twin's nodes carry what each was pushed, projected from the
// record's four artifact fields to name and checksum, and how long the push took, so the
// documents are M5's to validate.
func TestProvisionDocumentMapping(t *testing.T) {
	observed := "2026-09-15T14:22:12.000000Z"
	record := recordFor(wire.RecordInput{
		BundleID: testBundleID, ObservedAt: &observed, Source: wire.SourceIntent, RunID: "run-1",
		Provenance: wire.Provenance{Branch: "fylgja-fixture", SchemaHash: "fixture", Scope: "tag:fylgja", Mapping: dcimMapping},
		Nodes:      labNodes(srlinuxPlan(t)),
		Pushed:     []wire.PushResult{{Node: "n1", PushedInS: 0.7}, {Node: "n2", PushedInS: 0.62}, {Node: "n3", PushedInS: 0.65}},
	})
	finding := func(step, rule string) findings.List {
		var l findings.List
		l.AddStep(findings.Rejection, step, rule, "object", "message")
		return l
	}
	skipped := CleanupResult{Teardown: CleanupSkipped, Unstage: CleanupSkipped}
	clean := CleanupResult{Teardown: CleanupDone, Unstage: CleanupDone,
		Removed: []string{"lab fylgja (3 containers)", "twin directory /state/twin"}}
	leftover := CleanupResult{Teardown: CleanupFailed, Unstage: CleanupDone, Remaining: []string{"lab fylgja"}}

	for _, c := range []struct {
		name      string
		res       ProvisionResult
		status    findings.Status
		twin      bool
		cleanup   bool
		cancelled bool
	}{
		{"ready", ProvisionResult{Outcome: OutcomeReady, BundleID: testBundleID, ObservedAt: observed, TwinDir: "/state/twin",
			Twin: &record, Cleanup: skipped}, findings.StatusOK, true, false, false},
		{"rejected at the host check", ProvisionResult{Outcome: OutcomeRejected, BundleID: testBundleID, Step: findings.StepHostCheck,
			Findings: finding(findings.StepHostCheck, findings.RuleHostLabPresent), Cleanup: skipped}, findings.StatusRejected, false, true, false},
		{"error at read", ProvisionResult{Outcome: OutcomeError, Step: findings.StepRead,
			Findings: finding(findings.StepRead, findings.RuleOperationFailed), Cleanup: skipped}, findings.StatusError, false, true, false},
		{"cancelled before the host check", ProvisionResult{Outcome: OutcomeCancelled, Step: findings.StepCompile,
			Cleanup: skipped}, findings.StatusError, false, true, true},
		{"cancelled after the host check, clean", ProvisionResult{Outcome: OutcomeCancelled, BundleID: testBundleID, Step: findings.StepDeploy,
			Cleanup: clean}, findings.StatusFailed, false, true, true},
		{"failed, clean", ProvisionResult{Outcome: OutcomeFailed, BundleID: testBundleID, Step: findings.StepDeploy,
			Findings: finding(findings.StepDeploy, findings.RuleDeployFailed), Cleanup: clean}, findings.StatusFailed, false, true, false},
		{"failed, something remains", ProvisionResult{Outcome: OutcomeFailed, BundleID: testBundleID, Step: findings.StepReadiness,
			Findings: append(finding(findings.StepReadiness, findings.RuleReadinessTimeout), finding(findings.StepTeardown, findings.RuleCleanupIncomplete)...),
			Cleanup:  leftover}, findings.StatusUnclean, false, true, false},
	} {
		t.Run(c.name, func(t *testing.T) {
			doc := ProvisionDocument(findings.OpTwinCreate, &findings.Subject{Branch: "fylgja-fixture", RunID: "run-1"}, c.res)
			if doc.Status != c.status {
				t.Errorf("status = %q, want %q", doc.Status, c.status)
			}
			if (doc.Twin != nil) != c.twin || (doc.Cleanup != nil) != c.cleanup {
				t.Errorf("twin block %v, cleanup block %v; want %v, %v", doc.Twin != nil, doc.Cleanup != nil, c.twin, c.cleanup)
			}
			if c.twin && (doc.Twin.Dir != "/state/twin" || len(doc.Twin.Nodes) != 3 || doc.Twin.RunID != "run-1") {
				t.Errorf("twin block = %+v, want the worker's directory, three nodes and the run", doc.Twin)
			}
			if c.twin {
				n1 := doc.Twin.Nodes[0]
				want := findings.ShowArtifact{Name: "device-config", Checksum: fixtureArtifacts["n1"]}
				if n1.Name != "n1" || n1.Artifact == nil || *n1.Artifact != want || n1.PushedInS != 0.7 {
					t.Errorf("twin node %+v (artifact %+v), want n1 pushed %+v in 0.7s", n1, n1.Artifact, want)
				}
			}
			if c.res.BundleID != "" && doc.BundleID != c.res.BundleID {
				t.Errorf("bundle_id = %q, want %q", doc.BundleID, c.res.BundleID)
			}
			var named bool
			for _, f := range doc.Findings {
				if f.Rule == findings.RuleRunCancelled {
					named = f.Object == "run-1" && f.Step == c.res.Step
				}
			}
			if named != c.cancelled {
				t.Errorf("findings %+v: run.cancelled naming run-1 at %q is %v, want %v", doc.Findings, c.res.Step, named, c.cancelled)
			}
			mustValidateM5(t, doc, c.name)
		})
	}
}

// running is DescribeWorkflowExecution's answer for a run in flight.
func running(workflowID, runID string) *workflowservice.DescribeWorkflowExecutionResponse {
	return &workflowservice.DescribeWorkflowExecutionResponse{WorkflowExecutionInfo: &workflowpb.WorkflowExecutionInfo{
		Execution: &commonpb.WorkflowExecution{WorkflowId: workflowID, RunId: runID},
		Status:    enumspb.WORKFLOW_EXECUTION_STATUS_RUNNING,
	}}
}

// destroyScript is a mocks.Client wired for one twin destroy, recording the order of the
// calls that must happen in order.
type destroyScript struct {
	mc      *mocks.Client
	mu      sync.Mutex
	seq     []string
	options client.StartWorkflowOptions
	// runs answers each describe of a workflow id; an id it lacks has never run.
	runs map[string]*workflowservice.DescribeWorkflowExecutionResponse
}

func (s *destroyScript) note(entry string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.seq = append(s.seq, entry)
}

// scriptDestroy answers as a service where provisionRun and destroyRun are in flight when
// not empty, starting the destroy run returns startedRunID, and that run ends with res.
// It answers nothing of a Schedule or a listing: a destroy stops nothing first (019).
func scriptDestroy(provisionRun, destroyRun, startedRunID string, res DestroyResult) *destroyScript {
	s := &destroyScript{mc: &mocks.Client{}, runs: map[string]*workflowservice.DescribeWorkflowExecutionResponse{}}
	withWorker(s.mc)
	for workflowID, runID := range map[string]string{WorkflowProvision: provisionRun, WorkflowDestroy: destroyRun} {
		if runID != "" {
			s.runs[workflowID] = running(workflowID, runID)
		}
	}
	s.mc.On("DescribeWorkflowExecution", mock.Anything, mock.Anything, "").Return(
		func(_ context.Context, workflowID, _ string) (*workflowservice.DescribeWorkflowExecutionResponse, error) {
			s.mu.Lock()
			defer s.mu.Unlock()
			if desc, ok := s.runs[workflowID]; ok {
				return desc, nil
			}
			return nil, serviceerror.NewNotFound("workflow execution not found")
		})

	firstTaskTaken(s.mc)

	if provisionRun != "" {
		s.mc.On("CancelWorkflow", mock.Anything, WorkflowProvision, provisionRun).
			Run(func(mock.Arguments) { s.note("cancel provision") }).Return(nil)
		provisioning := &mocks.WorkflowRun{}
		provisioning.On("Get", mock.Anything, mock.Anything).Run(func(args mock.Arguments) {
			*args.Get(1).(*ProvisionResult) = ProvisionResult{Outcome: OutcomeCancelled}
			s.note("provision closed")
		}).Return(nil)
		s.mc.On("GetWorkflow", mock.Anything, WorkflowProvision, provisionRun).Return(provisioning)
	}

	destroying := &mocks.WorkflowRun{}
	destroying.On("GetRunID").Return(startedRunID)
	destroying.On("Get", mock.Anything, mock.Anything).
		Run(func(args mock.Arguments) { *args.Get(1).(*DestroyResult) = res }).Return(nil)
	s.mc.On("ExecuteWorkflow", mock.Anything, mock.Anything, mock.Anything).Run(func(args mock.Arguments) {
		s.mu.Lock()
		s.options = args.Get(1).(client.StartWorkflowOptions)
		s.mu.Unlock()
		s.note("start destroy")
	}).Return(destroying, nil)
	return s
}

func nothingToRemove() DestroyResult {
	return DestroyResult{Cleanup: CleanupResult{Teardown: CleanupNothing, Unstage: CleanupNothing}, Findings: findings.List{}}
}

// The destroy start options are pinned: USE_EXISTING attaches a second destroy to the
// first, and WorkflowExecutionErrorWhenAlreadyStarted would turn that
// attach into a refusal.
func TestDestroyStartOptionsPinned(t *testing.T) {
	s := scriptDestroy("", "", "run-d", nothingToRemove())

	run, err := (&Client{Client: s.mc}).StartDestroy(context.Background(), nil)
	if err != nil {
		t.Fatal(err)
	}
	o := s.options
	if o.ID != "fylgja-destroy" || o.TaskQueue != "fylgja" ||
		o.WorkflowIDConflictPolicy != enumspb.WORKFLOW_ID_CONFLICT_POLICY_USE_EXISTING || o.WorkflowExecutionErrorWhenAlreadyStarted {
		t.Errorf("start options = {ID:%q TaskQueue:%q WorkflowIDConflictPolicy:%v WorkflowExecutionErrorWhenAlreadyStarted:%v}, want fylgja-destroy, fylgja, USE_EXISTING, false",
			o.ID, o.TaskQueue, o.WorkflowIDConflictPolicy, o.WorkflowExecutionErrorWhenAlreadyStarted)
	}
	if run.RunID != "run-d" || run.Attached || run.Result.Cleanup.Teardown != CleanupNothing {
		t.Errorf("run = %+v, want a fresh run-d that found nothing", run)
	}
	s.mc.AssertNotCalled(t, "CancelWorkflow", mock.Anything, mock.Anything, mock.Anything)
}

// A destroy started while another is in flight attaches to it, says so, and reports that
// run's result as its own.
func TestSecondDestroyAttaches(t *testing.T) {
	s := scriptDestroy("", "run-d", "run-d", nothingToRemove())
	var notices []string

	run, err := (&Client{Client: s.mc}).StartDestroy(context.Background(), func(e Event) {
		if e.Notice != "" {
			notices = append(notices, e.Notice)
		}
	})
	if err != nil {
		t.Fatal(err)
	}
	if !run.Attached || run.RunID != "run-d" {
		t.Errorf("run = %+v, want attached to run-d", run)
	}
	if !slices.Contains(notices, "attached to destroy run run-d already in flight") {
		t.Errorf("notices %v, want the attach reported", notices)
	}
}

// A provisioning run in flight is cancelled and its close awaited before the destroy run
// starts, so teardown never races a deploy.
func TestDestroyCancelsInFlightProvision(t *testing.T) {
	s := scriptDestroy("run-p", "", "run-d", nothingToRemove())

	if _, err := (&Client{Client: s.mc}).StartDestroy(context.Background(), nil); err != nil {
		t.Fatal(err)
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if want := []string{"cancel provision", "provision closed", "start destroy"}; !slices.Equal(s.seq, want) {
		t.Errorf("calls in order %v, want %v", s.seq, want)
	}
	// It stops nothing else first (019): no Schedule is looked at, and no check is listed.
	s.mc.AssertNotCalled(t, "ScheduleClient")
	s.mc.AssertNotCalled(t, "ListWorkflow", mock.Anything, mock.Anything)
}

// A detached destroy (020, R-03) cancels and awaits a provisioning run in flight as the
// followed one does, then returns once a worker has taken its run, with no result read: the
// run's result is run.read's to read.
func TestADetachedDestroyReadsNoResult(t *testing.T) {
	s := scriptDestroy("run-p", "", "run-d", nothingToRemove())

	run, err := (&Client{Client: s.mc}).StartDestroyDetached(context.Background(), nil)
	if err != nil {
		t.Fatal(err)
	}
	if run.RunID != "run-d" || run.Attached || run.Result.Cleanup.Teardown != "" {
		t.Errorf("run = %+v, want run-d with no result read", run)
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if want := []string{"cancel provision", "provision closed", "start destroy"}; !slices.Equal(s.seq, want) {
		t.Errorf("calls in order %v, want %v", s.seq, want)
	}
}

// wantWorkerAbsent checks err is run.worker.absent: exit 2, at step start, on the queue.
func wantWorkerAbsent(t *testing.T, err error, says ...string) {
	t.Helper()
	refused, ok := AsStartError(err)
	if !ok {
		t.Fatalf("error = %v, want a refusal to start", err)
	}
	doc := refused.Document(findings.OpTwinCreate, &findings.Subject{Branch: "fylgja-fixture"})
	f := refused.Finding
	if doc.Status.ExitCode() != findings.ExitError || f.Rule != findings.RuleRunWorkerAbsent ||
		f.Object != TaskQueue || f.Step != findings.StepStart {
		t.Errorf("exit %d, finding %+v; want 2 with %s on %s at step start", doc.Status.ExitCode(), f, findings.RuleRunWorkerAbsent, TaskQueue)
	}
	for _, s := range says {
		if !strings.Contains(f.Message, s) {
			t.Errorf("message %q does not say %q", f.Message, s)
		}
	}
	mustValidateM2(t, doc, "run.worker.absent")
}

// With no worker polling the queue, nothing is started, cancelled or attached to: the
// command says so rather than waiting for ever.
func TestNoPollersStartsNothing(t *testing.T) {
	noWorker := func() *mocks.Client {
		mc := &mocks.Client{}
		mc.On("DescribeTaskQueue", mock.Anything, TaskQueue, enumspb.TASK_QUEUE_TYPE_WORKFLOW).
			Return(&workflowservice.DescribeTaskQueueResponse{}, nil)
		return mc
	}
	t.Run("provision", func(t *testing.T) {
		mc := noWorker()
		_, err := (&Client{Client: mc, Address: "localhost:7233"}).StartProvision(context.Background(),
			ProvisionInput{Source: wire.SourceIntent, Branch: "fylgja-fixture"})
		wantWorkerAbsent(t, err, "localhost:7233", "fylgja worker run")
		if got := called(mc); !slices.Equal(got, []string{"DescribeTaskQueue"}) {
			t.Errorf("client calls %v, want only the poller check", got)
		}
	})
	t.Run("destroy", func(t *testing.T) {
		mc := noWorker()
		_, err := (&Client{Client: mc, Address: "localhost:7233"}).StartDestroy(context.Background(), nil)
		wantWorkerAbsent(t, err, "localhost:7233")
		if got := called(mc); !slices.Equal(got, []string{"DescribeTaskQueue"}) {
			t.Errorf("client calls %v, want only the poller check: no cancel, no start", got)
		}
	})
	// A step's start is the provisioning run's in this.
	t.Run("step", func(t *testing.T) {
		mc := noWorker()
		_, err := (&Client{Client: mc, Address: "localhost:7233"}).StartStep(context.Background(), stepInput())
		wantWorkerAbsent(t, err, "localhost:7233", "fylgja worker run")
		if got := called(mc); !slices.Equal(got, []string{"DescribeTaskQueue"}) {
			t.Errorf("client calls %v, want only the poller check", got)
		}
	})
}

// A worker that stopped in the last five minutes is still listed as polling. When no
// worker takes the run's first task within the guard, the run is terminated
// before anything in it ran, and the start is refused as run.worker.absent.
func TestFirstTaskGuardTerminates(t *testing.T) {
	for _, c := range []struct {
		name       string
		workflowID string
		start      func(*Client) error
	}{
		{"provision", WorkflowProvision, func(c *Client) error {
			_, err := c.StartProvision(context.Background(), ProvisionInput{Source: wire.SourceIntent, Branch: "fylgja-fixture"})
			return err
		}},
		{"destroy", WorkflowDestroy, func(c *Client) error {
			_, err := c.StartDestroy(context.Background(), nil)
			return err
		}},
		{"step", WorkflowStep, func(c *Client) error {
			_, err := c.StartStep(context.Background(), stepInput())
			return err
		}},
	} {
		t.Run(c.name, func(t *testing.T) {
			mc := &mocks.Client{}
			withWorker(mc)
			mc.On("DescribeWorkflowExecution", mock.Anything, mock.Anything, "").
				Return(nil, serviceerror.NewNotFound("workflow execution not found"))
			run := &mocks.WorkflowRun{}
			run.On("GetRunID").Return("run-1")
			mc.On("ExecuteWorkflow", mock.Anything, mock.Anything, mock.Anything, mock.Anything).Return(run, nil)
			mc.On("ExecuteWorkflow", mock.Anything, mock.Anything, mock.Anything).Return(run, nil)
			// The run was started and its first task scheduled; no worker ever takes it.
			mc.On("GetWorkflowHistory", mock.Anything, c.workflowID, "run-1", true, enumspb.HISTORY_EVENT_FILTER_TYPE_ALL_EVENT).Return(
				func(ctx context.Context, _, _ string, _ bool, _ enumspb.HistoryEventFilterType) client.HistoryEventIterator {
					return &sliceHistory{ctx: ctx, wait: true, events: []*historypb.HistoryEvent{
						historyEvent(enumspb.EVENT_TYPE_WORKFLOW_EXECUTION_STARTED),
						historyEvent(enumspb.EVENT_TYPE_WORKFLOW_TASK_SCHEDULED),
					}}
				})
			mc.On("TerminateWorkflow", mock.Anything, c.workflowID, "run-1", mock.Anything).Return(nil)

			began := time.Now()
			err := c.start(&Client{Client: mc, FirstTaskGuard: 50 * time.Millisecond})
			wantWorkerAbsent(t, err, "run-1", "terminated")
			mc.AssertCalled(t, "TerminateWorkflow", mock.Anything, c.workflowID, "run-1", mock.Anything)
			if elapsed := time.Since(began); elapsed > 5*time.Second {
				t.Errorf("the guard took %s, want about 50ms", elapsed)
			}
		})
	}
}

// A service that does not answer the dial is run.service.unreachable, exit 2, naming the
// address; anything else a start returns is not a refusal.
func TestDialFailureIsServiceUnreachable(t *testing.T) {
	t.Setenv("FYLGJA_TEMPORAL_ADDRESS", "localhost:1")
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	c, err := Dial(ctx, slog.New(slog.NewTextHandler(io.Discard, nil)))
	if err == nil {
		c.Close()
		t.Fatal("dialled localhost:1, where nothing listens")
	}
	refused, ok := AsStartError(err)
	if !ok {
		t.Fatalf("error = %v, want a refusal to start", err)
	}
	doc := refused.Document(findings.OpTwinDestroy, &findings.Subject{})
	f := refused.Finding
	if doc.Status.ExitCode() != findings.ExitError || f.Rule != findings.RuleRunServiceUnreachable ||
		f.Object != "localhost:1" || f.Step != findings.StepStart || !strings.Contains(f.Message, "localhost:1") {
		t.Errorf("exit %d, finding %+v; want 2 with %s naming localhost:1", doc.Status.ExitCode(), f, findings.RuleRunServiceUnreachable)
	}
	mustValidateM2(t, doc, "run.service.unreachable")

	if _, ok := AsStartError(errors.New("describing fylgja-provision: internal error")); ok {
		t.Error("an arbitrary error was reported as a refusal to start")
	}
}

// mustValidateM2 validates a document against M2's findings contract.
func mustValidateM2(t *testing.T, doc *findings.Document, label string) {
	t.Helper()
	path := filepath.Join("testdata", "contracts", "002-provision-destroy", "findings.schema.json")
	f, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = f.Close() }()
	schemaDoc, err := jsonschema.UnmarshalJSON(f)
	if err != nil {
		t.Fatal(err)
	}
	c := jsonschema.NewCompiler()
	if err := c.AddResource("m2-findings.schema.json", schemaDoc); err != nil {
		t.Fatal(err)
	}
	schema, err := c.Compile("m2-findings.schema.json")
	if err != nil {
		t.Fatal(err)
	}
	b, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	v, err := jsonschema.UnmarshalJSON(bytes.NewReader(b))
	if err != nil {
		t.Fatal(err)
	}
	if err := schema.Validate(v); err != nil {
		t.Errorf("%s: document does not satisfy M2's findings.schema.json:\n%v\n%s", label, err, b)
	}
}

// mustValidateM5 checks doc against M5's findings contract, with the show block's schema
// added under its own $id. A document naming an artifact is
// M5's, and M2's contract, which forbids the field, is not its validator.
func mustValidateM5(t *testing.T, doc *findings.Document, label string) {
	t.Helper()
	load := func(name string) any {
		f, err := os.Open(filepath.Join("testdata", "contracts", "005-configuration", name))
		if err != nil {
			t.Fatal(err)
		}
		defer func() { _ = f.Close() }()
		v, err := jsonschema.UnmarshalJSON(f)
		if err != nil {
			t.Fatal(err)
		}
		return v
	}
	c := jsonschema.NewCompiler()
	if err := c.AddResource("https://github.com/happypathnetworking/fylgja/schemas/show.schema.json", load("show.schema.json")); err != nil {
		t.Fatal(err)
	}
	if err := c.AddResource("m5-findings.schema.json", load("findings.schema.json")); err != nil {
		t.Fatal(err)
	}
	schema, err := c.Compile("m5-findings.schema.json")
	if err != nil {
		t.Fatal(err)
	}
	b, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	v, err := jsonschema.UnmarshalJSON(bytes.NewReader(b))
	if err != nil {
		t.Fatal(err)
	}
	if err := schema.Validate(v); err != nil {
		t.Errorf("%s: document does not satisfy M5's findings.schema.json:\n%v\n%s", label, err, b)
	}
}

// A check names its own steps; a provisioning or destroy run's are M2's.
func TestStepNames(t *testing.T) {
	for _, c := range []struct {
		workflowID, activityType, step, findingStep string
	}{
		{WorkflowStep, wire.ActInspectTwin, "inspect", findings.StepInspect},
		{WorkflowProvision, wire.ActCheckHost, "host check", findings.StepHostCheck},
		{WorkflowProvision, wire.ActDestroyLab, "cleanup teardown", findings.StepTeardown},
		{WorkflowDestroy, wire.ActDestroyLab, "teardown", findings.StepTeardown},
		// M5: the push is a step of a provisioning run.
		{WorkflowProvision, wire.ActPushConfig, "push", findings.StepPush},
		// M12: the step's wait after its record.
		{WorkflowStep, wire.ActVerifyTwin, "observe", findings.StepObserve},
		{WorkflowStep, wire.ActRecordStep, "record", findings.StepRecord},
		// 016: the step's flows.
		{WorkflowStep, wire.ActStartFlows, "flows", findings.StepFlows},
		{WorkflowStep, wire.ActReadFlows, "loss", findings.StepFlows},
	} {
		if got := stepName(c.workflowID, c.activityType); got != c.step {
			t.Errorf("stepName(%s, %s) = %q, want %q", c.workflowID, c.activityType, got, c.step)
		}
		if got := findingStep(c.activityType); got != c.findingStep {
			t.Errorf("findingStep(%s) = %q, want %q", c.activityType, got, c.findingStep)
		}
	}
}

// childInitiated, childStarted and childCompleted are a child run in its parent's history, as
// an earlier build's rehearsal left one (015).
func childInitiated(id int64, workflowType string) *historypb.HistoryEvent {
	return &historypb.HistoryEvent{EventId: id, EventType: enumspb.EVENT_TYPE_START_CHILD_WORKFLOW_EXECUTION_INITIATED,
		Attributes: &historypb.HistoryEvent_StartChildWorkflowExecutionInitiatedEventAttributes{
			StartChildWorkflowExecutionInitiatedEventAttributes: &historypb.StartChildWorkflowExecutionInitiatedEventAttributes{
				WorkflowType: &commonpb.WorkflowType{Name: workflowType}}}}
}

func childStarted(initiated int64, workflowID, runID string) *historypb.HistoryEvent {
	return &historypb.HistoryEvent{EventType: enumspb.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_STARTED,
		Attributes: &historypb.HistoryEvent_ChildWorkflowExecutionStartedEventAttributes{
			ChildWorkflowExecutionStartedEventAttributes: &historypb.ChildWorkflowExecutionStartedEventAttributes{
				InitiatedEventId: initiated, WorkflowExecution: &commonpb.WorkflowExecution{WorkflowId: workflowID, RunId: runID}}}}
}

func childCompleted(initiated int64) *historypb.HistoryEvent {
	return &historypb.HistoryEvent{EventType: enumspb.EVENT_TYPE_CHILD_WORKFLOW_EXECUTION_COMPLETED,
		Attributes: &historypb.HistoryEvent_ChildWorkflowExecutionCompletedEventAttributes{
			ChildWorkflowExecutionCompletedEventAttributes: &historypb.ChildWorkflowExecutionCompletedEventAttributes{InitiatedEventId: initiated}}}
}

func completedEvent(scheduledID int64) *historypb.HistoryEvent {
	return &historypb.HistoryEvent{EventType: enumspb.EVENT_TYPE_ACTIVITY_TASK_COMPLETED,
		Attributes: &historypb.HistoryEvent_ActivityTaskCompletedEventAttributes{
			ActivityTaskCompletedEventAttributes: &historypb.ActivityTaskCompletedEventAttributes{ScheduledEventId: scheduledID}}}
}

// history makes one non-waiting history read of workflowID's runID answer events.
func history(mc *mocks.Client, workflowID, runID string, events ...*historypb.HistoryEvent) {
	mc.On("GetWorkflowHistory", mock.Anything, workflowID, runID, false, enumspb.HISTORY_EVENT_FILTER_TYPE_ALL_EVENT).Return(
		func(ctx context.Context, _, _ string, _ bool, _ enumspb.HistoryEventFilterType) client.HistoryEventIterator {
			return &sliceHistory{ctx: ctx, events: slices.Clone(events)}
		})
}

// InFlight names each run in flight at the step its history has reached, the operator's runs
// alone: it lists nothing else and reads no Schedule (019).
func TestInFlightNamesTheSteps(t *testing.T) {
	t.Run("a provision and a destroy", func(t *testing.T) {
		mc := &mocks.Client{}
		mc.On("DescribeWorkflowExecution", mock.Anything, WorkflowProvision, "").Return(running(WorkflowProvision, "r-p"), nil)
		mc.On("DescribeWorkflowExecution", mock.Anything, WorkflowDestroy, "").Return(running(WorkflowDestroy, "r-d"), nil)
		noStepRun(mc)
		history(mc, WorkflowProvision, "r-p",
			scheduledEvent(t, 5, wire.ActCheckHost), completedEvent(5),
			scheduledEvent(t, 7, wire.ActStageBundle), completedEvent(7),
			scheduledEvent(t, 9, wire.ActDeployLab))
		history(mc, WorkflowDestroy, "r-d",
			scheduledEvent(t, 5, wire.ActPlanTeardown), completedEvent(5),
			scheduledEvent(t, 7, wire.ActDestroyLab))

		got, err := (&Client{Client: mc}).InFlight(context.Background())
		if err != nil {
			t.Fatal(err)
		}
		want := []RunInFlight{{WorkflowID: WorkflowProvision, RunID: "r-p", Step: findings.StepDeploy},
			{WorkflowID: WorkflowDestroy, RunID: "r-d", Step: findings.StepTeardown}}
		if len(got) != 2 || got[0] != want[0] || got[1] != want[1] {
			t.Errorf("in flight = %+v, want %+v", got, want)
		}
		mc.AssertNotCalled(t, "ListWorkflow", mock.Anything, mock.Anything)
		mc.AssertNotCalled(t, "ScheduleClient")
	})
}

// A read the service does not answer is the service unreachable, for twin show to report.
func TestShowReadsUnreachable(t *testing.T) {
	mc := &mocks.Client{}
	mc.On("DescribeWorkflowExecution", mock.Anything, mock.Anything, "").Return(nil, serviceerror.NewUnavailable("connection refused"))
	_, err := (&Client{Client: mc, Address: "localhost:7233"}).InFlight(context.Background())
	var unreachable *UnreachableError
	if !errors.As(err, &unreachable) || unreachable.Address != "localhost:7233" {
		t.Errorf("InFlight: error %v, want an *UnreachableError at localhost:7233", err)
	}
}

// A step is refused beside a provisioning, destroy or step run in flight, naming the run,
// exit 1, with nothing started for the first two and the last refused by the fixed id
// (contracts/cli.md, run.in_flight).
func TestStartStepRefusedBesideARunInFlight(t *testing.T) {
	for _, c := range []struct {
		name, workflowID, runID, message string
		byID                             bool
	}{
		{"a provisioning run", WorkflowProvision, "run-p",
			"provisioning run run-p is already in flight; wait for it to finish, or run fylgja twin destroy to cancel it", false},
		{"a destroy run", WorkflowDestroy, "run-d", "destroy run run-d is already in flight; wait for it to finish", false},
		{"a step run", WorkflowStep, "run-s",
			"step run run-s is already in flight; wait for it to finish, or run fylgja twin destroy to cancel it", true},
	} {
		t.Run(c.name, func(t *testing.T) {
			mc := &mocks.Client{}
			withWorker(mc)
			mc.On("DescribeWorkflowExecution", mock.Anything, mock.Anything, "").Return(
				func(_ context.Context, workflowID, _ string) (*workflowservice.DescribeWorkflowExecutionResponse, error) {
					if workflowID == c.workflowID && !c.byID {
						return running(workflowID, c.runID), nil
					}
					return nil, serviceerror.NewNotFound("workflow execution not found")
				})
			if c.byID {
				mc.On("ExecuteWorkflow", mock.Anything, mock.Anything, mock.Anything, mock.Anything).Return(nil,
					serviceerror.NewWorkflowExecutionAlreadyStarted("Workflow execution is already running.", "request-1", c.runID))
			}

			_, err := (&Client{Client: mc}).StartStep(context.Background(), stepInput())
			var refused *StartError
			if !errors.As(err, &refused) {
				t.Fatalf("error = %v, want a *StartError", err)
			}
			f := refused.Finding
			if f.Rule != findings.RuleRunInFlight || f.Object != c.workflowID || f.Step != findings.StepStart || f.Message != c.message {
				t.Errorf("finding %+v\nwant run.in_flight on %s at start: %q", f, c.workflowID, c.message)
			}
			doc := refused.Document(findings.OpTwinStep, &findings.Subject{Stage: "change-1/live"})
			if doc.Status.ExitCode() != findings.ExitRejected {
				t.Errorf("exit %d, want %d", doc.Status.ExitCode(), findings.ExitRejected)
			}
			mustValidateM11(t, doc)
			if !c.byID {
				mc.AssertNotCalled(t, "ExecuteWorkflow", mock.Anything, mock.Anything, mock.Anything, mock.Anything)
			}
		})
	}
}

// StartStep starts the one step run under its pinned options, with the CLI's input, and
// returns once a worker has taken it.
func TestStartStepStarts(t *testing.T) {
	mc := &mocks.Client{}
	withWorker(mc)
	mc.On("DescribeWorkflowExecution", mock.Anything, mock.Anything, "").
		Return(nil, serviceerror.NewNotFound("workflow execution not found"))
	firstTaskTaken(mc)
	run := &mocks.WorkflowRun{}
	run.On("GetRunID").Return("run-s")
	var captured client.StartWorkflowOptions
	var given StepInput
	mc.On("ExecuteWorkflow", mock.Anything, mock.Anything, mock.Anything, mock.Anything).Run(func(args mock.Arguments) {
		captured, given = args.Get(1).(client.StartWorkflowOptions), args.Get(3).(StepInput)
	}).Return(run, nil)

	in := stepInput()
	runID, err := (&Client{Client: mc}).StartStep(context.Background(), in)
	if err != nil {
		t.Fatal(err)
	}
	if runID != "run-s" || captured.ID != WorkflowStep || captured.TaskQueue != TaskQueue || !captured.WorkflowExecutionErrorWhenAlreadyStarted {
		t.Errorf("run %q, options %+v; want run-s under fylgja-step, fylgja, WorkflowExecutionErrorWhenAlreadyStarted", runID, captured)
	}
	if !reflect.DeepEqual(given, in) {
		t.Errorf("started with %+v\nwant the CLI's input %+v", given, in)
	}
}

// A create beside a step is refused before any run starts, naming the step run, where it
// would otherwise have started and been rejected at its host check.
func TestStartProvisionRefusedBesideAStep(t *testing.T) {
	mc := &mocks.Client{}
	withWorker(mc)
	mc.On("DescribeWorkflowExecution", mock.Anything, WorkflowStep, "").Return(running(WorkflowStep, "run-s"), nil)

	_, err := (&Client{Client: mc}).StartProvision(context.Background(), ProvisionInput{Source: wire.SourceIntent, Branch: "b"})
	var refused *StartError
	if !errors.As(err, &refused) {
		t.Fatalf("error = %v, want a *StartError", err)
	}
	want := "step run run-s is already in flight; wait for it to finish, or run fylgja twin destroy to cancel it"
	if f := refused.Finding; f.Rule != findings.RuleRunInFlight || f.Object != WorkflowStep || f.Message != want {
		t.Errorf("finding %+v\nwant run.in_flight on fylgja-step: %q", f, want)
	}
	mc.AssertNotCalled(t, "ExecuteWorkflow", mock.Anything, mock.Anything, mock.Anything, mock.Anything)
}

// twin destroy cancels a step run in flight after any provisioning run, waits for it to
// close with its record written, names both, and only then starts the destroy run
// (contracts/cli.md, twin destroy). A step run terminated rather than closed gives
// no result, and the destroy names it closed without one and goes on.
func TestDestroyCancelsInFlightStep(t *testing.T) {
	// terminated is what the service answers for a run closed without a result: a
	// *temporal.WorkflowExecutionError, whose constructor the SDK keeps internal.
	terminated := &temporal.WorkflowExecutionError{}
	for _, c := range []struct {
		name, provisioning string
		closed             StepResult
		getErr             error
		want               []string
		notice             string
	}{
		{"a step after its stage", "", StepResult{Outcome: OutcomeCancelled, Phase: findings.StepPush}, nil,
			[]string{"cancel step", "step closed", "start destroy"}, "step run run-s closed: diverged"},
		{"a step before its stage", "", StepResult{Outcome: OutcomeCancelled, Step: findings.StepCompare}, nil,
			[]string{"cancel step", "step closed", "start destroy"}, "step run run-s closed: cancelled"},
		{"a provisioning run and a step", "run-p", StepResult{Outcome: OutcomeCancelled, Phase: findings.StepReadiness}, nil,
			[]string{"cancel provision", "provision closed", "cancel step", "step closed", "start destroy"}, "step run run-s closed: diverged"},
		{"a terminated step", "", StepResult{}, terminated,
			[]string{"cancel step", "step closed", "start destroy"}, "step run run-s closed without a result: " + terminated.Error()},
		// M12: a step in its wait after the record (twin destroy during the pause) is cancelled
		// as any step is; its wait ends cancelled, and it closes as its record says, stepped.
		{"a step during its wait", "", StepResult{Outcome: StepStepped, Record: &wire.TwinRecord{State: wire.StateReady},
			Wait: &wire.StepWait{Outcome: wire.WaitCancelled, BudgetS: 120, Reads: 7, AfterS: 12.4},
			Findings: findings.List{{Severity: findings.Warning, Rule: findings.RuleVerifyWaitUnsettled, Object: "run-s",
				Step: findings.StepObserve, Message: "cancelled after 12.4s (7 reads, budget 2m0s); nothing was failing at the last read"}}},
			nil, []string{"cancel step", "step closed", "start destroy"}, "step run run-s closed: stepped"},
	} {
		t.Run(c.name, func(t *testing.T) {
			s := scriptDestroy(c.provisioning, "", "run-d", nothingToRemove())
			s.runs[WorkflowStep] = running(WorkflowStep, "run-s")
			s.mc.On("CancelWorkflow", mock.Anything, WorkflowStep, "run-s").Run(func(mock.Arguments) { s.note("cancel step") }).Return(nil)
			stepping := &mocks.WorkflowRun{}
			stepping.On("Get", mock.Anything, mock.Anything).Run(func(args mock.Arguments) {
				*args.Get(1).(*StepResult) = c.closed
				s.mu.Lock()
				delete(s.runs, WorkflowStep)
				s.mu.Unlock()
				s.note("step closed")
			}).Return(c.getErr)
			s.mc.On("GetWorkflow", mock.Anything, WorkflowStep, "run-s").Return(stepping)

			var notices []string
			if _, err := (&Client{Client: s.mc}).StartDestroy(context.Background(), func(e Event) {
				if e.Notice != "" {
					notices = append(notices, e.Notice)
				}
			}); err != nil {
				t.Fatal(err)
			}
			s.mu.Lock()
			defer s.mu.Unlock()
			if !slices.Equal(s.seq, c.want) {
				t.Errorf("calls in order %v, want %v", s.seq, c.want)
			}
			for _, want := range []string{"cancelling step run run-s; waiting for its record", c.notice} {
				if !slices.Contains(notices, want) {
					t.Errorf("notices %v, want %q", notices, want)
				}
			}
		})
	}
}

// startedEvent is a run's first event, carrying its input.
func startedEvent(t *testing.T, input any) *historypb.HistoryEvent {
	t.Helper()
	payloads, err := converter.GetDefaultDataConverter().ToPayloads(input)
	if err != nil {
		t.Fatal(err)
	}
	return &historypb.HistoryEvent{EventId: 1, EventType: enumspb.EVENT_TYPE_WORKFLOW_EXECUTION_STARTED,
		Attributes: &historypb.HistoryEvent_WorkflowExecutionStartedEventAttributes{
			WorkflowExecutionStartedEventAttributes: &historypb.WorkflowExecutionStartedEventAttributes{Input: payloads}}}
}

// InFlight names a step run at the step its history has reached, and the side its input
// steps towards as wire.StepSide.Name() names it, snapshot <short> (019), or bundle <short>
// for a side naming no snapshot, never a stage (020, research R-06), which twin show's kind
// line reads.
func TestInFlightNamesAStepAndItsTarget(t *testing.T) {
	toBundle := stepInput()
	toBundle.To = wire.StepSide{BundleID: toBundle.To.BundleID, At: toBundle.To.At}
	for _, c := range []struct {
		name    string
		in      StepInput
		towards string
	}{
		{"to a snapshot", stepInput(), "snapshot f3980cc7…"},
		{"to a side naming no snapshot", toBundle, "bundle eeeeeeee…"},
	} {
		t.Run(c.name, func(t *testing.T) {
			mc := &mocks.Client{}
			mc.On("DescribeWorkflowExecution", mock.Anything, WorkflowStep, "").Return(running(WorkflowStep, "run-s"), nil)
			mc.On("DescribeWorkflowExecution", mock.Anything, mock.Anything, "").Return(nil, serviceerror.NewNotFound("not found"))
			history(mc, WorkflowStep, "run-s", startedEvent(t, c.in),
				scheduledEvent(t, 5, wire.ActInspectTwin), completedEvent(5),
				scheduledEvent(t, 7, wire.ActStageStep, wire.StageStepInput{}), completedEvent(7),
				scheduledEvent(t, 9, wire.ActReconcileLab, wire.ReconcileInput{}))

			got, err := (&Client{Client: mc}).InFlight(context.Background())
			if err != nil {
				t.Fatal(err)
			}
			want := RunInFlight{WorkflowID: WorkflowStep, RunID: "run-s", Step: findings.StepReconcile, Towards: c.towards}
			if len(got) != 1 || got[0] != want {
				t.Errorf("in flight = %+v, want %+v", got, want)
			}
		})
	}
}

// The step block before a run: the from side names no branch, a created node no
// declaration, and nothing of a run; containerlab's plan list for list, and the push plan
// with each node's reasons; StepClosedAs names a step stopped
// after its stage diverged (contracts/cli.md, twin destroy).
func TestStepBlockAndClose(t *testing.T) {
	in := stepInput()
	in.From.Branch = "should-not-appear"
	in.Declared["s2"] = "live" // its package declares; a created node's link change is not at stake
	in.Declared["s3"] = "live"
	plan := stepPlan()
	// Every list names a node, so a list written from another, or left empty, shows. A
	// deleted node is gone, not touched, though its endpoint is deleted too.
	plan.Added, plan.Recreated, plan.Deleted, plan.EndpointsDeleted = []string{"s2"}, []string{"s3"}, []string{"e2"}, []string{"e2:eth1"}
	block := StepBlockOf(in, plan)
	if block.From.Branch != "" || block.To.Branch != "change-1" || block.StepRunBlock != nil {
		t.Errorf("from branch %q, to branch %q, run %+v; want none, change-1, none", block.From.Branch, block.To.Branch, block.StepRunBlock)
	}
	// Each side names its snapshot, and its stage is null: a side names no stage from
	// twin.json 12 (020, research R-06).
	if block.From.Stage != nil || block.To.Stage != nil {
		t.Errorf("from stage %+v, to stage %+v; want both null", block.From.Stage, block.To.Stage)
	}
	if block.From.SnapshotID != stepFromSnapshot || block.To.SnapshotID != stepToSnapshot {
		t.Errorf("from snapshot %q, to snapshot %q; want %s and %s", block.From.SnapshotID, block.To.SnapshotID,
			stepFromSnapshot, stepToSnapshot)
	}
	r := block.Reconcile
	for _, l := range []struct {
		name      string
		got, want []string
	}{
		{"added", r.Added, plan.Added}, {"deleted", r.Deleted, plan.Deleted}, {"recreated", r.Recreated, plan.Recreated},
		{"restarted", r.Restarted, plan.Restarted}, {"links_added", r.LinksAdded, plan.LinksAdded},
		{"endpoints_deleted", r.EndpointsDeleted, plan.EndpointsDeleted},
	} {
		if !slices.Equal(l.got, l.want) {
			t.Errorf("reconcile %s %v, want the plan's %v", l.name, l.got, l.want)
		}
	}
	pushPlan := []findings.StepPushPlanEntry{{Node: "e1", Reasons: []string{"artifact", "restarted"}},
		{Node: "s1", Reasons: []string{"artifact", "bootstrap"}}}
	if !reflect.DeepEqual(block.PushPlan, pushPlan) {
		t.Errorf("push plan %+v, want %+v", block.PushPlan, pushPlan)
	}
	declared := map[string]string{}
	for _, n := range block.Reconcile.Nodes {
		d := "null"
		if n.Declared != nil {
			d = *n.Declared
		}
		declared[n.Node+" "+n.Reported] = d
	}
	if want := map[string]string{"e1 restart": "restart", "s1 live": "live", "s2 create": "null", "s3 recreate": "live"}; !maps.Equal(declared, want) {
		t.Errorf("reconcile nodes %v, want %v", declared, want)
	}
	doc := findings.NewDocument(findings.OpTwinStep, &findings.Subject{Stage: "change-1/live"}, nil)
	doc.Step = block
	mustValidateM11(t, doc)

	for _, c := range []struct {
		res  StepResult
		want string
	}{
		{StepResult{Outcome: StepStepped}, "stepped"},
		{StepResult{Outcome: StepDiverged, Phase: findings.StepPush}, "diverged"},
		{StepResult{Outcome: OutcomeCancelled, Phase: findings.StepReconcile}, "diverged"},
		{StepResult{Outcome: OutcomeCancelled, Step: findings.StepInspect}, "cancelled"},
		{StepResult{Outcome: OutcomeRejected, Step: findings.StepCompare}, "rejected"},
	} {
		if got := StepClosedAs(c.res); got != c.want {
			t.Errorf("StepClosedAs(%+v) = %q, want %q", c.res, got, c.want)
		}
	}
}

// The observe step's progress line reads the wait from VerifyTwin's result, word for word
// (contracts/cli.md, twin step --wait).
func TestObserveStepDetail(t *testing.T) {
	unread := wire.StepFinding{Rule: findings.RuleOperationFailed, Object: "e1", Message: "node e1 (172.20.20.2:6030) could not be read: …"}
	neighbor := func(object string) wire.StepFinding {
		return wire.StepFinding{Rule: findings.RuleVerifyNeighbor, Object: object, Message: "sees no neighbour"}
	}
	for _, c := range []struct {
		wait wire.StepWait
		want string
	}{
		{wire.StepWait{Outcome: wire.WaitSettled, Reads: 2, AfterS: 2.4}, "settled after 2.4s (2 reads)"},
		{wire.StepWait{Outcome: wire.WaitSettled, Reads: 1, AfterS: 0.31}, "settled after 0.3s (1 read)"},
		{wire.StepWait{Outcome: wire.WaitExpired, Reads: 58, AfterS: 120,
			Failing: []wire.StepFinding{neighbor("s1:ethernet-1/3"), neighbor("e1:Ethernet3"), neighbor("e2:Ethernet1")}},
			"expired after 120.0s (58 reads, 3 failing)"},
		{wire.StepWait{Outcome: wire.WaitCancelled, Reads: 7, AfterS: 12.4, Failing: []wire.StepFinding{neighbor("e1:Ethernet3")}},
			"cancelled after 12.4s (7 reads)"},
		{wire.StepWait{Outcome: wire.WaitIncomplete, Reads: 58, AfterS: 120.3, Failing: []wire.StepFinding{unread, neighbor("s1:ethernet-1/3")}},
			"could not complete: e1 still unread after 120.3s (58 reads, 1 failing)"},
		{wire.StepWait{Outcome: wire.WaitIncomplete, Reads: 58, AfterS: 120.3, Failing: []wire.StepFinding{unread}},
			"could not complete: e1 still unread after 120.3s (58 reads)"},
	} {
		payloads, err := converter.GetDefaultDataConverter().ToPayloads(wire.VerifyResult{Wait: c.wait, Recorded: true})
		if err != nil {
			t.Fatal(err)
		}
		if got := completedDetail(converter.GetDefaultDataConverter(), wire.ActVerifyTwin, payloads); got != c.want {
			t.Errorf("observe detail for %+v = %q, want %q", c.wait, got, c.want)
		}
	}
}

// The flows step's progress line reads each flow's start from StartFlows' result, and the
// loss step's what each lost from ReadFlows', word for word (016, contracts/cli.md, twin
// step): container timing named once, after every probe.
func TestFlowsStepDetails(t *testing.T) {
	dc := converter.GetDefaultDataConverter()
	detail := func(activityType string, result any) string {
		t.Helper()
		payloads, err := dc.ToPayloads(result)
		if err != nil {
			t.Fatal(err)
		}
		return completedDetail(dc, activityType, payloads)
	}
	for _, c := range []struct {
		flows []wire.FlowOutcome
		want  string
	}{
		{[]wire.FlowOutcome{{Probe: "n1-loop", Outcome: wire.FlowStarted}}, "n1-loop started"},
		{[]wire.FlowOutcome{{Probe: "n1-loop", Outcome: wire.FlowStarted}, {Probe: "n2-loop", Outcome: wire.FlowNotStarted,
			Rule: findings.RuleFlowStartFailed, Message: "docker exec exited 1"}}, "n1-loop started; n2-loop not started: docker exec exited 1"},
	} {
		if got := detail(wire.ActStartFlows, wire.FlowsResult{Flows: c.flows}); got != c.want {
			t.Errorf("flows detail for %+v = %q, want %q", c.flows, got, c.want)
		}
	}
	measured := wire.ProbeLoss{Probe: "n1-loop", From: "clab-fylgja-n1-loop-a", To: "clab-fylgja-n1-loop-b",
		Outcome: wire.FlowMeasured, Sent: 312}
	for _, c := range []struct {
		loss wire.Loss
		want string
	}{
		{wire.Loss{Basis: wire.LossBasisContainer, Probes: []wire.ProbeLoss{measured}},
			"n1-loop 0/312 lost, longest gap 0.0s (container timing)"},
		{wire.Loss{Basis: wire.LossBasisContainer, Probes: []wire.ProbeLoss{
			{Probe: "n1-loop", Outcome: wire.FlowInterrupted, Sent: 300, Lost: 274, LongestGapS: 54.8},
			{Probe: "n2-loop", Outcome: wire.FlowNotStarted, Rule: findings.RuleFlowStartFailed, Message: "docker exec exited 1"},
			{Probe: "n3-loop", Outcome: wire.FlowNotRead, Rule: findings.RuleFlowReadFailed, Message: "no summary"}},
			Added: []string{"n4-loop"}, Dropped: []string{"n5-loop", "n6-loop"}},
			"n1-loop interrupted, 274/300 lost, longest gap 54.8s; n2-loop not started; n3-loop not read: no summary; " +
				"added n4-loop, not measured; dropped n5-loop, n6-loop, not measured (container timing)"},
		{wire.Loss{Basis: wire.LossBasisContainer}, "no flow"},
	} {
		if got := detail(wire.ActReadFlows, wire.ReadFlowsResult{Loss: c.loss, Recorded: true}); got != c.want {
			t.Errorf("loss detail for %+v = %q, want %q", c.loss, got, c.want)
		}
	}
}

// twin step's document carries the loss once its flows were read, and null on the dry run and
// on a run that closed before them (016; step.schema.json's loss). Each document satisfies
// the contracts.
func TestStepDocumentCarriesTheLoss(t *testing.T) {
	in := stepInput()
	doc := findings.NewDocument(findings.OpTwinStep, &findings.Subject{Stage: "change-1/live"}, nil)
	doc.Step = StepBlockOf(in, stepPlan())
	if b := string(mustValidateM11(t, doc)); !strings.Contains(b, `"loss":null`) {
		t.Errorf("the dry run's document carries no null loss: %s", b)
	}
	subject := &findings.Subject{Stage: "change-1/live", RunID: "run-s"}
	loss := &wire.Loss{Basis: wire.LossBasisContainer, Probes: []wire.ProbeLoss{{Probe: "n1-loop", From: "clab-fylgja-n1-loop-a",
		To: "clab-fylgja-n1-loop-b", Outcome: wire.FlowMeasured, Sent: 312, Lost: 5, LongestGapS: 1}}, Added: []string{}, Dropped: []string{}}
	for _, c := range []struct {
		name string
		res  StepResult
		want string
	}{
		{"stepped", StepResult{Outcome: StepStepped, Loss: loss}, `"loss":{"basis":"container","probes":[{"probe":"n1-loop",` +
			`"from":"clab-fylgja-n1-loop-a","to":"clab-fylgja-n1-loop-b","outcome":"measured","sent":312,"lost":5,"longest_gap_s":1}],` +
			`"added":[],"dropped":[]}`},
		{"no probe", StepResult{Outcome: StepStepped, Loss: &wire.Loss{Basis: wire.LossBasisContainer}},
			`"loss":{"basis":"container","probes":[],"added":[],"dropped":[]}`},
		{"diverged at flows", StepResult{Outcome: StepDiverged, Phase: findings.StepFlows}, `"loss":null`},
		{"cancelled before the stage", StepResult{Outcome: OutcomeCancelled}, `"loss":null`},
	} {
		t.Run(c.name, func(t *testing.T) {
			if b := string(mustValidateM11(t, StepDocument(subject, in, c.res))); !strings.Contains(b, c.want) {
				t.Errorf("document %s\nwant it to carry %s", b, c.want)
			}
		})
	}
}

// twin step's document carries the wait once the run closed and the wait ran, and no key
// when it did not; the dry run's block, from StepBlockOf, its budget alone. The step's status
// is M11's whatever the wait found. Each document satisfies the contracts.
func TestStepDocumentCarriesTheWait(t *testing.T) {
	for _, waitS := range []int{0, 30, 120} {
		in := stepInput()
		in.WaitS = waitS
		block := StepBlockOf(in, stepPlan())
		if block.Wait == nil || block.Wait.BudgetS != waitS || block.Wait.Outcome != "" {
			t.Errorf("StepBlockOf's wait with --wait %ds = %+v, want the budget alone", waitS, block.Wait)
		}
		doc := findings.NewDocument(findings.OpTwinStep, &findings.Subject{Stage: "change-1/live"}, nil)
		doc.Step = block
		if b := string(mustValidateM11(t, doc)); !strings.Contains(b, `"wait":{"budget_s":`+strconv.Itoa(waitS)+`}`) {
			t.Errorf("dry run's document %s, want its wait to carry budget_s %d alone", b, waitS)
		}
	}

	in := stepInput()
	in.WaitS = 120
	failing := []wire.StepFinding{{Rule: findings.RuleVerifyNeighbor, Object: "e1:Ethernet3", Message: "node e1 (…): port Ethernet3 sees no neighbour"}}
	subject := &findings.Subject{Stage: "change-1/live", RunID: "run-s"}
	for _, c := range []struct {
		name   string
		res    StepResult
		status findings.Status
		want   string
	}{
		{"stepped, settled", StepResult{Outcome: StepStepped, Wait: &wire.StepWait{Outcome: wire.WaitSettled, BudgetS: 120, Reads: 2,
			AfterS: 2.4, Failing: []wire.StepFinding{}}}, findings.StatusOK,
			`"wait":{"budget_s":120,"outcome":"settled","reads":2,"after_s":2.4,"failing":[]}`},
		{"stepped, expired", StepResult{Outcome: StepStepped, Wait: &wire.StepWait{Outcome: wire.WaitExpired, BudgetS: 120, Reads: 58,
			AfterS: 120, Failing: failing}}, findings.StatusOK,
			`"wait":{"budget_s":120,"outcome":"expired","reads":58,"after_s":120,"failing":[{"rule":"verify.neighbor","object":"e1:Ethernet3","message":"node e1 (…): port Ethernet3 sees no neighbour"}]}`},
		{"stepped, cancelled", StepResult{Outcome: StepStepped, Wait: &wire.StepWait{Outcome: wire.WaitCancelled, BudgetS: 120, Reads: 7,
			AfterS: 12.4}}, findings.StatusOK, `"wait":{"budget_s":120,"outcome":"cancelled","reads":7,"after_s":12.4,"failing":[]}`},
		{"diverged, incomplete", StepResult{Outcome: StepDiverged, Phase: findings.StepPush, Wait: &wire.StepWait{Outcome: wire.WaitIncomplete,
			BudgetS: 120, Failing: []wire.StepFinding{{Rule: findings.RuleOperationFailed, Object: "/state/twin/twin.json", Message: "disk full"}}}},
			findings.StatusDiverged, `"wait":{"budget_s":120,"outcome":"incomplete","reads":0,"after_s":0,"failing":[{"rule":"operation.failed"`},
		{"cancelled before the wait", StepResult{Outcome: OutcomeCancelled, Phase: findings.StepPush}, findings.StatusDiverged, ""},
		{"stepped, the wait not run", StepResult{Outcome: StepStepped}, findings.StatusOK, ""},
	} {
		t.Run(c.name, func(t *testing.T) {
			doc := StepDocument(subject, in, c.res)
			if doc.Status != c.status {
				t.Errorf("status %s, want %s: the wait changes no status", doc.Status, c.status)
			}
			b := string(mustValidateM11(t, doc))
			switch {
			case c.want == "" && strings.Contains(b, `"wait"`):
				t.Errorf("a run whose wait did not run carries the key: %s", b)
			case c.want != "" && !strings.Contains(b, c.want):
				t.Errorf("document %s\nwant it to carry %s", b, c.want)
			}
		})
	}
}

// twin step's document carries the wait's last read counted by kind beside the wait, as twin
// verify counts its block, once the run closed and its wait read; no key on the dry run, on a
// wait that made no read and on a run cancelled before its wait, whatever the result holds
// (015; step.schema.json's wait_counts). The text does not change. Each document satisfies
// the contracts.
func TestStepDocumentCarriesTheWaitCounts(t *testing.T) {
	in := stepInput()
	in.WaitS = 120
	doc := findings.NewDocument(findings.OpTwinStep, &findings.Subject{Stage: "change-1/live"}, nil)
	doc.Step = StepBlockOf(in, stepPlan())
	if b := string(mustValidateM11(t, doc)); strings.Contains(b, `"wait_counts"`) {
		t.Errorf("the dry run's document carries wait_counts: %s", b)
	}

	zero, one := 0, 1
	settled := &wire.VerifyCounts{HostName: findings.VerifyCount{Held: 3, Unread: &zero},
		PortEnabled: findings.VerifyCount{Held: 6, Skipped: &zero, Unread: &zero},
		Neighbor:    findings.VerifyCount{Held: 6, Skipped: &zero, Unread: &zero}, Record: findings.VerifyCount{Held: 3}}
	expired := &wire.VerifyCounts{HostName: findings.VerifyCount{Held: 3, Unread: &zero},
		PortEnabled: findings.VerifyCount{Held: 6, Skipped: &zero, Unread: &zero},
		Neighbor:    findings.VerifyCount{Held: 5, Failed: 1, Skipped: &one, Unread: &zero}, Record: findings.VerifyCount{Held: 3}}
	subject := &findings.Subject{Stage: "change-1/live", RunID: "run-s"}
	for _, c := range []struct {
		name string
		res  StepResult
		want *wire.VerifyCounts
	}{
		{"settled", StepResult{Outcome: StepStepped, Wait: &wire.StepWait{Outcome: wire.WaitSettled, BudgetS: 120, Reads: 2, AfterS: 2.4,
			Failing: []wire.StepFinding{}}, WaitCounts: settled}, settled},
		{"expired", StepResult{Outcome: StepStepped, Wait: &wire.StepWait{Outcome: wire.WaitExpired, BudgetS: 120, Reads: 58, AfterS: 120,
			Failing: []wire.StepFinding{{Rule: findings.RuleVerifyNeighbor, Object: "e1:Ethernet3", Message: "…"}}}, WaitCounts: expired}, expired},
		{"cancelled before its first read", StepResult{Outcome: StepStepped, Wait: &wire.StepWait{Outcome: wire.WaitCancelled, BudgetS: 120}}, nil},
		{"incomplete", StepResult{Outcome: StepStepped, Wait: &wire.StepWait{Outcome: wire.WaitIncomplete, BudgetS: 120,
			Failing: []wire.StepFinding{{Rule: findings.RuleOperationFailed, Object: "/state/twin/twin.json", Message: "disk full"}}}}, nil},
		{"cancelled before the wait", StepResult{Outcome: OutcomeCancelled, Phase: findings.StepPush, WaitCounts: settled}, nil},
	} {
		t.Run(c.name, func(t *testing.T) {
			doc := StepDocument(subject, in, c.res)
			if !reflect.DeepEqual(doc.Step.WaitCounts, c.want) {
				t.Errorf("step.wait_counts %+v, want %+v", doc.Step.WaitCounts, c.want)
			}
			b := string(mustValidateM11(t, doc))
			if c.want == nil {
				if strings.Contains(b, `"wait_counts"`) {
					t.Errorf("document carries wait_counts: %s", b)
				}
				return
			}
			want, err := json.Marshal(c.want)
			if err != nil {
				t.Fatal(err)
			}
			if !strings.Contains(b, `"wait_counts":`+string(want)) {
				t.Errorf("document %s\nwant it to carry wait_counts %s", b, want)
			}
		})
	}
}

// Describe names the run an identity names and its state in run.read's words, the
// workflow's latest run when the request names none; an identity the service holds no run
// under, NotFound or a run id of no run's shape (InvalidArgument, "Invalid RunId."), is an
// *UnknownRunError naming it, and any other failure the service not answering (020).
func TestDescribeNamesTheRunAndItsState(t *testing.T) {
	described := func(status enumspb.WorkflowExecutionStatus, runID string) *workflowservice.DescribeWorkflowExecutionResponse {
		return &workflowservice.DescribeWorkflowExecutionResponse{WorkflowExecutionInfo: &workflowpb.WorkflowExecutionInfo{
			Execution: &commonpb.WorkflowExecution{WorkflowId: WorkflowStep, RunId: runID}, Status: status}}
	}
	for status, want := range map[enumspb.WorkflowExecutionStatus]string{
		enumspb.WORKFLOW_EXECUTION_STATUS_RUNNING:    RunRunning,
		enumspb.WORKFLOW_EXECUTION_STATUS_COMPLETED:  RunCompleted,
		enumspb.WORKFLOW_EXECUTION_STATUS_FAILED:     RunFailed,
		enumspb.WORKFLOW_EXECUTION_STATUS_CANCELED:   RunCancelled,
		enumspb.WORKFLOW_EXECUTION_STATUS_TERMINATED: RunTerminated,
		enumspb.WORKFLOW_EXECUTION_STATUS_TIMED_OUT:  RunTimedOut,
	} {
		mc := &mocks.Client{}
		mc.On("DescribeWorkflowExecution", mock.Anything, WorkflowStep, "r-s").Return(described(status, "r-s"), nil)
		got, err := (&Client{Client: mc}).Describe(context.Background(), WorkflowStep, "r-s")
		if err != nil || got != (RunState{WorkflowID: WorkflowStep, RunID: "r-s", State: want}) {
			t.Errorf("%s: Describe = %+v, %v; want state %s", status, got, err, want)
		}
		if got.Running() != (want == RunRunning) {
			t.Errorf("%s: Running() = %v", status, got.Running())
		}
	}

	t.Run("the latest run", func(t *testing.T) {
		mc := &mocks.Client{}
		mc.On("DescribeWorkflowExecution", mock.Anything, WorkflowStep, "").
			Return(described(enumspb.WORKFLOW_EXECUTION_STATUS_COMPLETED, "r-latest"), nil)
		got, err := (&Client{Client: mc}).Describe(context.Background(), WorkflowStep, "")
		if err != nil || got.RunID != "r-latest" {
			t.Errorf("Describe with no run = %+v, %v; want the latest run, r-latest", got, err)
		}
	})

	for name, c := range map[string]struct {
		runID string
		err   error
		says  string
	}{
		"not found":   {"r-gone", serviceerror.NewNotFound("workflow execution not found"), "fylgja-step r-gone"},
		"no run's id": {"not-a-run", serviceerror.NewInvalidArgument("Invalid RunId."), "fylgja-step not-a-run"},
		"never run":   {"", serviceerror.NewNotFound("workflow not found for ID: fylgja-step"), "fylgja-step"},
	} {
		t.Run(name, func(t *testing.T) {
			mc := &mocks.Client{}
			mc.On("DescribeWorkflowExecution", mock.Anything, WorkflowStep, c.runID).Return(nil, c.err)
			_, err := (&Client{Client: mc}).Describe(context.Background(), WorkflowStep, c.runID)
			var unknown *UnknownRunError
			if !errors.As(err, &unknown) || unknown.Identity() != c.says ||
				err.Error() != "the workflow service holds no run "+c.says {
				t.Errorf("Describe = %v, want an *UnknownRunError naming %q", err, c.says)
			}
		})
	}

	t.Run("unreachable", func(t *testing.T) {
		mc := &mocks.Client{}
		mc.On("DescribeWorkflowExecution", mock.Anything, WorkflowStep, "r-s").
			Return(nil, serviceerror.NewUnavailable("connection refused"))
		_, err := (&Client{Client: mc, Address: "localhost:7233"}).Describe(context.Background(), WorkflowStep, "r-s")
		if _, ok := AsStartError(err); !ok {
			t.Errorf("Describe = %v, want the service unreachable", err)
		}
	})
}

// History reads the history once without waiting, Follow's events over what it holds so
// far; InputOfStep reads the step's input from the history's first event, as the recorded
// step-diverged run was started with it (020).
func TestHistoryAndTheStepsInputAreReadByIdentity(t *testing.T) {
	mc := &mocks.Client{}
	history(mc, WorkflowProvision, "r-p",
		scheduledEvent(t, 5, wire.ActCheckHost), completedEvent(5),
		scheduledEvent(t, 7, wire.ActDeployLab))
	var steps []string
	if err := (&Client{Client: mc}).History(context.Background(), WorkflowProvision, "r-p", func(e Event) {
		steps = append(steps, e.Step+" "+strconv.FormatBool(e.End))
	}); err != nil {
		t.Fatal(err)
	}
	if want := []string{"host check false", "host check true", "deploy false"}; !slices.Equal(steps, want) {
		t.Errorf("History's events = %q, want %q", steps, want)
	}
	mc.AssertNotCalled(t, "GetWorkflowHistory", mock.Anything, mock.Anything, mock.Anything, true, mock.Anything)

	raw, err := os.Open(filepath.Join("testdata", "step-diverged.history.json"))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = raw.Close() }()
	h, err := client.HistoryFromJSON(raw, client.HistoryJSONOptions{})
	if err != nil {
		t.Fatal(err)
	}
	var want StepInput
	if err := converter.GetDefaultDataConverter().FromPayloads(
		h.GetEvents()[0].GetWorkflowExecutionStartedEventAttributes().GetInput(), &want); err != nil {
		t.Fatal(err)
	}
	mc = &mocks.Client{}
	history(mc, WorkflowStep, "r-s", h.GetEvents()...)
	got, err := (&Client{Client: mc}).InputOfStep(context.Background(), "r-s")
	if err != nil || !reflect.DeepEqual(got, want) || got.To.BundleID == "" {
		t.Errorf("InputOfStep = %+v, %v; want the recorded input %+v", got, err, want)
	}
}
