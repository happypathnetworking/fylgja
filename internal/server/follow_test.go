package server

import (
	"bytes"
	"context"
	"encoding/json"
	"log/slog"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/provision"
)

// lateService is a workflow service whose run is followed until a second interrupt stops
// the follow, and whose Follow then emits one event more, as provision.Client.Follow emits
// the rest of a history page it fetched before its context ended. Every method the run does
// not reach is the nil interface's, and panics.
type lateService struct {
	provision.Service
	following chan struct{} // closed once Follow has emitted its first event
	cancelled chan struct{} // closed when the run is asked to cancel
	// emit is closed once the answer's document is written and before its handler returns;
	// emitted is closed once the late event was handed to the follow.
	emit, emitted chan struct{}
	once          sync.Once
}

const lateRunID = "01a10000-0000-7000-8000-00000000late"

func (s *lateService) StartProvision(context.Context, provision.ProvisionInput) (string, error) {
	return lateRunID, nil
}

func (s *lateService) Follow(ctx context.Context, workflowID, _ string, onEvent func(provision.Event)) error {
	onEvent(provision.Event{WorkflowID: workflowID, Step: "deploy", FindingStep: findings.StepDeploy})
	close(s.following)
	<-ctx.Done()
	select {
	case <-s.emit:
	case <-time.After(5 * time.Second):
	}
	onEvent(provision.Event{WorkflowID: workflowID, Step: "late", FindingStep: findings.StepDeploy, End: true,
		Outcome: provision.EventDone, Duration: time.Second, Detail: "a late event"})
	close(s.emitted)
	return ctx.Err()
}

func (s *lateService) Result(ctx context.Context, _, _ string) (provision.ProvisionResult, error) {
	<-ctx.Done()
	return provision.ProvisionResult{}, ctx.Err()
}

func (s *lateService) Cancel(context.Context, string, string) error {
	s.once.Do(func() { close(s.cancelled) })
	return nil
}

func (s *lateService) Close() {}

// lateLog holds the request's log line until the late event has been emitted: the line is
// the last thing the handler writes, after the document, so the event comes between the
// document and the handler's return.
type lateLog struct {
	buf  *syncBuffer
	svc  *lateService
	once sync.Once
}

func (l *lateLog) Write(p []byte) (int, error) {
	if bytes.Contains(p, []byte("msg=request ")) && bytes.Contains(p, []byte("operation="+findings.OpTwinCreate)) {
		l.once.Do(func() {
			close(l.svc.emit)
			select {
			case <-l.svc.emitted:
			case <-time.After(5 * time.Second):
			}
		})
	}
	return l.buf.Write(p)
}

// A run's follow that outlives its request writes nothing after the document: after a
// second interrupt has stopped the follow, an event the follow still emits is dropped, and
// the answer's frames before its document are unchanged (contracts/api.md, "The answer").
func TestAFollowThatOutlivesItsRequestWritesNothingAfterTheDocument(t *testing.T) {
	run := func(c *call) error {
		return runProvision(c.ctx, c.options(), findings.OpTwinCreate, &findings.Subject{Branch: "b"},
			provision.ProvisionInput{Branch: "b"})
	}
	s, srv, _, _ := testServer(t, run)
	svc := &lateService{following: make(chan struct{}), cancelled: make(chan struct{}),
		emit: make(chan struct{}), emitted: make(chan struct{})}
	s.Dial = func(context.Context, *slog.Logger) (provision.Service, error) { return svc, nil }
	log := &syncBuffer{}
	s.Log = slog.New(slog.NewTextHandler(&lateLog{buf: log, svc: svc}, nil))

	const id = "0123456789abcdef0123456789abcdef"
	answer := make(chan []byte, 1)
	go func() {
		_, body := post(t, nil, srv.URL+api.Path(findings.OpTwinCreate), testToken, `{"render":"text"}`,
			map[string]string{api.HeaderStream: id})
		answer <- body
	}()
	select {
	case <-svc.following:
	case <-time.After(5 * time.Second):
		t.Fatal("the run was never followed")
	}
	post(t, nil, srv.URL+api.InterruptPath(id), testToken, ``, nil)
	select {
	case <-svc.cancelled:
	case <-time.After(5 * time.Second):
		t.Fatal("the first interrupt never asked the run to cancel")
	}
	post(t, nil, srv.URL+api.InterruptPath(id), testToken, ``, nil)

	var body []byte
	select {
	case body = <-answer:
	case <-time.After(10 * time.Second):
		t.Fatal("the answer never ended")
	}
	select {
	case <-svc.emitted:
	default:
		t.Fatal("the late event was never emitted, so its absence proves nothing")
	}

	var kinds []string
	var document api.Frame
	for _, l := range answerLines(t, body) {
		f := frameOf(t, l)
		kinds = append(kinds, f.Kind())
		if f.Kind() == api.KindDocument {
			satisfies(t, apiSchema(t, "frame"), l, "the document frame")
			document = f
		}
	}
	want := []string{api.KindStart, api.KindRun, api.KindOut, api.KindEvent, api.KindOut, api.KindOut, api.KindDocument}
	if strings.Join(kinds, " ") != strings.Join(want, " ") {
		t.Errorf("the answer's frames are %q, want %q:\n%s", kinds, want, body)
	}
	if strings.Contains(string(body), "a late event") || strings.Contains(string(body), `"late"`) {
		t.Errorf("an event the follow emitted after the request ended reached the answer:\n%s", body)
	}
	var doc findings.Document
	if err := json.Unmarshal(document.Document, &doc); err != nil {
		t.Fatal(err)
	}
	if len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleRunCancelled || doc.Findings[0].Step != findings.StepDeploy {
		t.Errorf("the document's findings are %+v, want run.cancelled at deploy", doc.Findings)
	}
	waitForLog(t, log, "operation="+findings.OpTwinCreate, "outcome=error")
	carriesNoToken(t, "the answer and the log", string(body), log.String())
}
