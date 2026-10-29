package server

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	"github.com/stretchr/testify/mock"
	commonpb "go.temporal.io/api/common/v1"
	enumspb "go.temporal.io/api/enums/v1"
	historypb "go.temporal.io/api/history/v1"
	"go.temporal.io/api/serviceerror"
	workflowpb "go.temporal.io/api/workflow/v1"
	"go.temporal.io/api/workflowservice/v1"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/converter"
	"go.temporal.io/sdk/mocks"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/provision"
)

// recordedRuns are the seven histories internal/provision replays, recorded from the dev
// server, by the workflow each is a run of.
var recordedRuns = []struct {
	history, workflowID string
	// status is the document's, as the run's result makes it.
	status findings.Status
}{
	{"cancel-during-host-check.history.json", provision.WorkflowProvision, findings.StatusError},
	{"cancel-during-push.history.json", provision.WorkflowProvision, findings.StatusFailed},
	{"cancel-during-record.history.json", provision.WorkflowProvision, findings.StatusFailed},
	{"push-after-cancel.history.json", provision.WorkflowProvision, findings.StatusFailed},
	{"step-cancelled.history.json", provision.WorkflowStep, findings.StatusDiverged},
	{"step-diverged.history.json", provision.WorkflowStep, findings.StatusDiverged},
	{"step-wait-cancelled.history.json", provision.WorkflowStep, findings.StatusOK}, // stepped; its wait cancelled
}

const recordedRunID = "01a10000-0000-7000-8000-0000000000r7"

// recorded is one recorded history's events.
func recorded(t *testing.T, name string) []*historypb.HistoryEvent {
	t.Helper()
	f, err := os.Open(repoPath("internal", "provision", "testdata", name))
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = f.Close() }()
	h, err := client.HistoryFromJSON(f, client.HistoryJSONOptions{})
	if err != nil {
		t.Fatalf("reading %s: %v", name, err)
	}
	return h.GetEvents()
}

// eventsOf is a history read whole, without waiting.
type eventsOf struct{ events []*historypb.HistoryEvent }

func (h *eventsOf) HasNext() bool { return len(h.events) > 0 }

func (h *eventsOf) Next() (*historypb.HistoryEvent, error) {
	e := h.events[0]
	h.events = h.events[1:]
	return e, nil
}

// replayed is the workflow service holding one run whose history is events: the provision
// client itself over the SDK's mock client, so run.read's describe, its history reads and
// its result are the code that reads the service, answering from a recorded history. A
// running run's history is cut before its close; it is never waited on, and its result is
// never asked for.
func replayed(t *testing.T, workflowID string, events []*historypb.HistoryEvent, status enumspb.WorkflowExecutionStatus) (*provision.Client, *mocks.Client) {
	t.Helper()
	mc := &mocks.Client{}
	mc.On("DescribeWorkflowExecution", mock.Anything, workflowID, mock.Anything).Return(
		&workflowservice.DescribeWorkflowExecutionResponse{WorkflowExecutionInfo: &workflowpb.WorkflowExecutionInfo{
			Execution: &commonpb.WorkflowExecution{WorkflowId: workflowID, RunId: recordedRunID}, Status: status}}, nil)
	running := status == enumspb.WORKFLOW_EXECUTION_STATUS_RUNNING
	mc.On("GetWorkflowHistory", mock.Anything, workflowID, recordedRunID, mock.Anything, enumspb.HISTORY_EVENT_FILTER_TYPE_ALL_EVENT).Return(
		func(_ context.Context, _, _ string, wait bool, _ enumspb.HistoryEventFilterType) client.HistoryEventIterator {
			if wait && running {
				t.Error("the read of a running run waited for its history")
			}
			return &eventsOf{events: append([]*historypb.HistoryEvent(nil), events...)}
		})
	if !running {
		result := events[len(events)-1].GetWorkflowExecutionCompletedEventAttributes().GetResult()
		run := &mocks.WorkflowRun{}
		run.On("Get", mock.Anything, mock.Anything).Return(func(_ context.Context, into any) error {
			return converter.GetDefaultDataConverter().FromPayloads(result, into)
		})
		mc.On("GetWorkflow", mock.Anything, workflowID, recordedRunID).Return(run)
	}
	mc.On("CancelWorkflow", mock.Anything, workflowID, recordedRunID).Return(nil)
	mc.On("Close").Return()
	return &provision.Client{Client: mc, Address: "localhost:7233"}, mc
}

// byIdentity is a server serving run.read and run.interrupt over svc; nil fails the test if
// the workflow service is dialled.
func byIdentity(t *testing.T, svc provision.Service) (*httptest.Server, *syncBuffer) {
	t.Helper()
	s, srv, log, _ := testServer(t, func(c *call) error { return handlers[c.op](c) })
	if svc != nil {
		s.Dial = func(context.Context, *slog.Logger) (provision.Service, error) { return svc, nil }
	}
	return srv, log
}

// askByIdentity is one request to op over srv: its lines and its frames.
func askByIdentity(t *testing.T, srv *httptest.Server, op, body string) ([][]byte, []api.Frame) {
	t.Helper()
	resp, raw := post(t, nil, srv.URL+api.Path(op), testToken, body, nil)
	if resp.StatusCode != 200 {
		t.Fatalf("%s %s: status %d: %s", op, body, resp.StatusCode, raw)
	}
	lines := answerLines(t, raw)
	frames := make([]api.Frame, len(lines))
	for i, l := range lines {
		frames[i] = frameOf(t, l)
	}
	return lines, frames
}

// historyEvents are the event frames a history's events make, as the stream's follow
// writes each: the provision client's own reading of the history, without waiting.
func historyEvents(t *testing.T, workflowID string, events []*historypb.HistoryEvent) []api.Event {
	t.Helper()
	svc, _ := replayed(t, workflowID, events, enumspb.WORKFLOW_EXECUTION_STATUS_RUNNING)
	var out []api.Event
	if err := svc.History(context.Background(), workflowID, recordedRunID, func(e provision.Event) {
		out = append(out, api.Event{WorkflowID: e.WorkflowID, Step: e.Step, FindingStep: e.FindingStep, End: e.End,
			Outcome: e.Outcome, DurationS: e.Duration.Seconds(), Detail: e.Detail, Rule: e.Rule, Message: e.Message,
			Notice: e.Notice})
	}); err != nil {
		t.Fatal(err)
	}
	return out
}

func readBody(workflowID string) string {
	return `{"args":{"workflow_id":"` + workflowID + `","run_id":"` + recordedRunID + `"}}`
}

// run.read replays each of the seven recorded histories by its identity (SC-005): ended, its
// run frame says completed, then every event the history holds, as the stream's follow
// writes them, then the document the run's result makes, the stream's own under operation
// run.read, naming the run; running, cut half-way, the run frame says running, then the
// events so far, and the answer ends there, by EOF, with no document, which the API's client
// reads as the answer's end and not a cut. The out lines name the run and its state first.
// Nothing is dialled but the workflow service, and nothing in it is changed.
func TestRunReadReplaysEachRecordedHistory(t *testing.T) {
	frame := apiSchema(t, "frame")
	for _, r := range recordedRuns {
		t.Run(strings.TrimSuffix(r.history, ".history.json"), func(t *testing.T) {
			events := recorded(t, r.history)
			wantEvents := historyEvents(t, r.workflowID, events)
			if len(wantEvents) == 0 {
				t.Fatalf("the history makes %d events", len(wantEvents))
			}

			t.Run("ended", func(t *testing.T) {
				svc, mc := replayed(t, r.workflowID, events, enumspb.WORKFLOW_EXECUTION_STATUS_COMPLETED)
				srv, log := byIdentity(t, svc)
				lines, frames := askByIdentity(t, srv, findings.OpRunRead, readBody(r.workflowID))
				if got := frames[0].Run; got == nil || *got != (api.RunRef{WorkflowID: r.workflowID, RunID: recordedRunID,
					State: provision.RunCompleted}) {
					t.Fatalf("the first frame is %s, want the run, completed", lines[0])
				}
				var got []api.Event
				for i, f := range frames[1 : len(frames)-1] {
					if f.Event == nil {
						t.Fatalf("frame %d is %s, want an event", i+1, lines[i+1])
					}
					satisfies(t, frame, lines[i+1], "an event frame")
					got = append(got, *f.Event)
				}
				if !equalEvents(got, wantEvents) {
					t.Errorf("the events are\n%+v\nwant the history's\n%+v", got, wantEvents)
				}
				last := lines[len(lines)-1]
				if frames[len(frames)-1].Kind() != api.KindDocument {
					t.Fatalf("the answer ends %s, want the document", last)
				}
				satisfies(t, frame, last, "the document frame")
				var doc findings.Document
				if err := json.Unmarshal(frames[len(frames)-1].Document, &doc); err != nil {
					t.Fatal(err)
				}
				if doc.Operation != findings.OpRunRead || doc.Status != r.status || doc.Subject == nil ||
					doc.Subject.RunID != recordedRunID {
					t.Errorf("the document is %s %s naming %+v; want run.read %s naming run %s", doc.Operation, doc.Status,
						doc.Subject, r.status, recordedRunID)
				}
				if want := streamsDocument(t, r.workflowID, events); !bytes.Equal(frames[len(frames)-1].Document, want) {
					t.Errorf("the document is\n%s\nwant the one the run's stream makes of its result\n%s",
						frames[len(frames)-1].Document, want)
				}
				waitForLog(t, log, "operation=run.read", "outcome="+string(r.status))
				mc.AssertNotCalled(t, "CancelWorkflow", mock.Anything, mock.Anything, mock.Anything)

				_, text := askByIdentity(t, srv, findings.OpRunRead, `{"render":"text","args":{"workflow_id":"`+
					r.workflowID+`","run_id":"`+recordedRunID+`"}}`)
				if text[1].Out != "run "+r.workflowID+" "+recordedRunID+": completed\n" {
					t.Errorf("under text the first line is %q, want the run and its state", text[1].Out)
				}
			})

			t.Run("running", func(t *testing.T) {
				// Half-way, or later where the first half holds no step yet.
				cut := events[:len(events)/2]
				for len(historyEvents(t, r.workflowID, cut)) == 0 {
					cut = events[:len(cut)+1]
				}
				svc, mc := replayed(t, r.workflowID, cut, enumspb.WORKFLOW_EXECUTION_STATUS_RUNNING)
				srv, log := byIdentity(t, svc)
				lines, frames := askByIdentity(t, srv, findings.OpRunRead, readBody(r.workflowID))
				if got := frames[0].Run; got == nil || got.State != provision.RunRunning {
					t.Fatalf("the first frame is %s, want the run, running", lines[0])
				}
				var got []api.Event
				for i, f := range frames[1:] {
					if f.Event == nil {
						t.Fatalf("frame %d is %s, want an event and no document", i+1, lines[i+1])
					}
					got = append(got, *f.Event)
				}
				if want := historyEvents(t, r.workflowID, cut); len(want) == 0 || !equalEvents(got, want) {
					t.Errorf("the events are\n%+v\nwant the history's so far\n%+v", got, want)
				}
				waitForLog(t, log, "operation=run.read", "outcome=running", "level=INFO")
				mc.AssertNotCalled(t, "GetWorkflow", mock.Anything, mock.Anything, mock.Anything)

				// The API's client reads the end as the answer's, not a cut.
				t.Setenv(api.EnvAddress, strings.TrimPrefix(srv.URL, "http://"))
				t.Setenv(api.EnvToken, testToken)
				c, err := api.NewClient(func(k string) (string, bool) { return os.LookupEnv(k) }, testBuild)
				if err != nil {
					t.Fatal(err)
				}
				a, err := c.RunRead(context.Background(), r.workflowID, recordedRunID, "", nil)
				if err != nil {
					t.Fatal(err)
				}
				n := 0
				for {
					f, err := a.Next()
					if errors.Is(err, io.EOF) {
						break
					}
					if err != nil {
						t.Fatalf("after %d frames the client reads %v, want the answer's end", n, err)
					}
					n++
					if f.Kind() == api.KindDocument {
						t.Fatal("the client read a document")
					}
				}
				if n != len(frames) {
					t.Errorf("the client read %d frames of %d", n, len(frames))
				}
			})
		})
	}
}

// streamsDocument is the document the run's stream makes of the recorded run's result,
// under operation run.read: provision.ProvisionDocument's, or StepDocument's of the input
// the history begins with.
func streamsDocument(t *testing.T, workflowID string, events []*historypb.HistoryEvent) []byte {
	t.Helper()
	dc := converter.GetDefaultDataConverter()
	result := events[len(events)-1].GetWorkflowExecutionCompletedEventAttributes().GetResult()
	subject := &findings.Subject{RunID: recordedRunID}
	var doc *findings.Document
	if workflowID == provision.WorkflowStep {
		var in provision.StepInput
		var res provision.StepResult
		if err := dc.FromPayloads(events[0].GetWorkflowExecutionStartedEventAttributes().GetInput(), &in); err != nil {
			t.Fatal(err)
		}
		if err := dc.FromPayloads(result, &res); err != nil {
			t.Fatal(err)
		}
		doc = provision.StepDocument(subject, in, res)
		doc.Operation = findings.OpRunRead
	} else {
		var res provision.ProvisionResult
		if err := dc.FromPayloads(result, &res); err != nil {
			t.Fatal(err)
		}
		doc = provision.ProvisionDocument(findings.OpRunRead, subject, res)
	}
	var b, compact bytes.Buffer
	if err := doc.WriteJSON(&b); err != nil {
		t.Fatal(err)
	}
	if err := json.Compact(&compact, b.Bytes()); err != nil {
		t.Fatal(err)
	}
	return compact.Bytes()
}

func equalEvents(a, b []api.Event) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

// A read of a destroy run by its identity answers the destroy's events and its document,
// its cleanup block and status the destroy's own (US4 scenario 6), under operation
// run.read.
func TestRunReadOfADestroy(t *testing.T) {
	events := []provision.Event{
		{WorkflowID: provision.WorkflowDestroy, Step: "plan teardown", FindingStep: findings.StepTeardown},
		{WorkflowID: provision.WorkflowDestroy, Step: "plan teardown", FindingStep: findings.StepTeardown, End: true,
			Outcome: provision.EventDone},
	}
	svc := &destroyRead{events: events, result: provision.DestroyResult{Findings: findings.List{},
		Cleanup: provision.CleanupResult{Teardown: provision.CleanupDone, Unstage: provision.CleanupDone,
			Removed: []string{"lab fylgja (3 containers)"}, Remaining: []string{"twin directory /abs/local/twin"}}}}
	srv, _ := byIdentity(t, svc)
	lines, frames := askByIdentity(t, srv, findings.OpRunRead, `{"render":"text","args":{"workflow_id":"fylgja-destroy"}}`)
	var kinds, outs []string
	for _, f := range frames {
		if f.Kind() != api.KindOut {
			kinds = append(kinds, f.Kind())
		}
		outs = append(outs, f.Out)
	}
	if got, want := strings.Join(kinds, " "), "run event event document"; got != want {
		t.Errorf("the answer's frames but its out lines are %q, want %q", got, want)
	}
	if frames[0].Run == nil || *frames[0].Run != (api.RunRef{WorkflowID: provision.WorkflowDestroy, RunID: "d1",
		State: provision.RunCompleted}) {
		t.Fatalf("the first frame is %s", lines[0])
	}
	if !strings.Contains(strings.Join(outs, ""), "removed lab fylgja (3 containers)\n") {
		t.Errorf("the out lines %q say nothing of what the destroy removed", outs)
	}
	var doc findings.Document
	if err := json.Unmarshal(frames[len(frames)-1].Document, &doc); err != nil {
		t.Fatal(err)
	}
	if doc.Operation != findings.OpRunRead || doc.Status != findings.StatusUnclean || doc.Cleanup == nil ||
		len(doc.Cleanup.Remaining) != 1 || doc.Subject.RunID != "d1" {
		t.Errorf("the document is %+v, want run.read unclean with the destroy's cleanup, naming d1", doc)
	}
	if svc.waited {
		t.Error("the read of an ended destroy waited on a history the service had closed")
	}
}

// destroyRead is a workflow service holding one ended destroy run, d1, the workflow's
// latest.
type destroyRead struct {
	provision.Service
	events []provision.Event
	result provision.DestroyResult
	waited bool
}

func (s *destroyRead) Describe(_ context.Context, workflowID, runID string) (provision.RunState, error) {
	if workflowID != provision.WorkflowDestroy || runID != "" {
		return provision.RunState{}, &provision.UnknownRunError{WorkflowID: workflowID, RunID: runID}
	}
	return provision.RunState{WorkflowID: workflowID, RunID: "d1", State: provision.RunCompleted}, nil
}

func (s *destroyRead) Follow(_ context.Context, _, runID string, onEvent func(provision.Event)) error {
	if runID != "d1" {
		s.waited = true
	}
	for _, e := range s.events {
		onEvent(e)
	}
	return nil
}

func (s *destroyRead) ResultOfDestroy(context.Context, string) (provision.DestroyResult, error) {
	return s.result, nil
}

func (s *destroyRead) Close() {}

// An identity no run has is run.unknown, naming it, after the describe alone: no history is
// read, nothing is cancelled (US4 scenario 3); a workflow that is none of the three is
// refused before anything is dialled.
func TestARunNoneHasIsUnknown(t *testing.T) {
	for _, op := range []string{findings.OpRunRead, findings.OpRunInterrupt} {
		t.Run(op, func(t *testing.T) {
			mc := &mocks.Client{}
			mc.On("DescribeWorkflowExecution", mock.Anything, provision.WorkflowStep, "r-gone").
				Return(nil, serviceerror.NewNotFound("workflow execution not found"))
			mc.On("Close").Return()
			srv, log := byIdentity(t, &provision.Client{Client: mc})
			_, frames := askByIdentity(t, srv, op, `{"args":{"workflow_id":"fylgja-step","run_id":"r-gone"}}`)
			doc := onlyDocument(t, frames)
			if doc.Status != findings.StatusRejected || len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleRunUnknown ||
				doc.Findings[0].Object != "fylgja-step r-gone" ||
				doc.Findings[0].Message != "the workflow service holds no run fylgja-step r-gone" {
				t.Errorf("the document is %+v, want run.unknown naming fylgja-step r-gone", doc)
			}
			waitForLog(t, log, "operation="+op, "outcome=rejected")
			mc.AssertNotCalled(t, "GetWorkflowHistory", mock.Anything, mock.Anything, mock.Anything, mock.Anything, mock.Anything)
			mc.AssertNotCalled(t, "CancelWorkflow", mock.Anything, mock.Anything, mock.Anything)

			// The rehearsal is no run of the operator's three: refused, nothing dialled.
			srv, _ = byIdentity(t, nil)
			_, frames = askByIdentity(t, srv, op, `{"args":{"workflow_id":"fylgja-rehearse"}}`)
			doc = onlyDocument(t, frames)
			if doc.Status != findings.StatusRejected || doc.Findings[0].Rule != findings.RuleRunUnknown ||
				doc.Findings[0].Object != "fylgja-rehearse" ||
				!strings.Contains(doc.Findings[0].Message, "fylgja-provision, fylgja-step or fylgja-destroy") {
				t.Errorf("the document is %+v, want run.unknown naming the three", doc)
			}
		})
	}
}

// run.interrupt reaches a running run by its identity as the stream's first interrupt does:
// the run is asked to cancel, and the document says so (US4 scenario 4); a run that has
// closed is run.ended, naming its state, with nothing asked of it.
func TestRunInterruptByIdentity(t *testing.T) {
	events := recorded(t, "cancel-during-push.history.json")
	t.Run("running", func(t *testing.T) {
		svc, mc := replayed(t, provision.WorkflowProvision, events[:20], enumspb.WORKFLOW_EXECUTION_STATUS_RUNNING)
		srv, log := byIdentity(t, svc)
		_, frames := askByIdentity(t, srv, findings.OpRunInterrupt, `{"args":{"workflow_id":"fylgja-provision"}}`)
		doc := onlyDocument(t, frames)
		id := "fylgja-provision " + recordedRunID
		if doc.Status != findings.StatusOK || len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleRunCancelRequested ||
			doc.Findings[0].Object != id || doc.Subject.RunID != recordedRunID {
			t.Errorf("the document is %+v, want run.cancel.requested naming %s", doc, id)
		}
		mc.AssertCalled(t, "CancelWorkflow", mock.Anything, provision.WorkflowProvision, recordedRunID)
		mc.AssertNotCalled(t, "GetWorkflowHistory", mock.Anything, mock.Anything, mock.Anything, mock.Anything, mock.Anything)
		waitForLog(t, log, "operation=run.interrupt", "outcome=ok")
	})
	t.Run("ended", func(t *testing.T) {
		svc, mc := replayed(t, provision.WorkflowProvision, events, enumspb.WORKFLOW_EXECUTION_STATUS_COMPLETED)
		srv, _ := byIdentity(t, svc)
		_, frames := askByIdentity(t, srv, findings.OpRunInterrupt, readBody(provision.WorkflowProvision))
		doc := onlyDocument(t, frames)
		if doc.Status != findings.StatusRejected || doc.Findings[0].Rule != findings.RuleRunEnded ||
			doc.Findings[0].Message != "run fylgja-provision "+recordedRunID+" has already closed: completed" {
			t.Errorf("the document is %+v, want run.ended naming its state", doc)
		}
		mc.AssertNotCalled(t, "CancelWorkflow", mock.Anything, mock.Anything, mock.Anything)
	})
}

// onlyDocument is an answer that is its document alone.
func onlyDocument(t *testing.T, frames []api.Frame) findings.Document {
	t.Helper()
	if len(frames) != 1 || frames[0].Kind() != api.KindDocument {
		t.Fatalf("the answer is %d frames, want the document alone: %+v", len(frames), frames)
	}
	var doc findings.Document
	if err := json.Unmarshal(frames[0].Document, &doc); err != nil {
		t.Fatal(err)
	}
	return doc
}
