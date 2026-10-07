package cli

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
)

// A run's stream, as the client keeps its side of it. The interrupts are armed at the
// start frame and not
// before, sent one at a time and in order to the stream the request named, and an
// interrupt for an answer that has just ended is read past to its document. M12's six
// interrupt tests (interrupt_start_test.go's two, TestStepInterrupt's four) hold what the
// server does with them.

// An interrupt queued before a refusal that comes before the start frame reaches no server:
// nothing has taken it from where it was queued, the server logged no interrupt, and the
// command ends with M12's refusal.
func TestInterruptsBeforeTheStartReachNoServer(t *testing.T) {
	for _, c := range []struct {
		name string
		run  func(t *testing.T) error
		want findings.Finding
	}{
		{"twin create --interval=", func(t *testing.T) error {
			useStateRoot(t)
			useService(t, nil)
			return runCreate(context.Background(), &options{asJSON: true},
				&createFlags{branch: "fylgja-fixture", interval: "", intervalGiven: true})
		}, findings.Finding{Severity: findings.Rejection, Rule: findings.RuleFollowIntervalInvalid, Object: "", Step: findings.StepStart,
			Message: `--interval  is not a duration: time: invalid duration ""`}},
		{"twin create, the workflow service unreachable", func(t *testing.T) error {
			useStateRoot(t)
			startRefusals()[0].use(t)
			return runCreate(context.Background(), &options{asJSON: true}, &createFlags{branch: "fylgja-fixture"})
		}, findings.Finding{Rule: findings.RuleRunServiceUnreachable, Step: findings.StepStart}},
		{"twin step --wait=", func(t *testing.T) error {
			stepHost(t, "plan-link-added.json", nil)
			return runTwinStep(context.Background(), &options{asJSON: true}, &stepFlags{allowRestart: true, waitGiven: true})
		}, findings.Finding{Severity: findings.Rejection, Rule: findings.RuleVerifyWaitInvalid, Object: "--wait", Step: findings.StepStart,
			Message: "--wait= is empty; give a duration such as --wait=2m, or leave --wait out for the default 2m0s"}},
	} {
		t.Run(c.name, func(t *testing.T) {
			queued := useInterrupts(t)
			queued <- os.Interrupt
			awaitIdle(t)
			before := len(requestOutcomes("interrupt"))

			code, doc := exitOf(t, c.run(t))

			if code != findings.ExitError || len(doc.Findings) != 1 {
				t.Fatalf("exit %d, findings %+v; want 2 with M12's refusal alone", code, doc.Findings)
			}
			got := doc.Findings[0]
			if c.want.Message == "" {
				// The workflow service's refusal is M2's, worded by its client.
				got = findings.Finding{Rule: got.Rule, Step: got.Step}
			}
			if got != c.want {
				t.Errorf("finding %+v, want %+v", doc.Findings[0], c.want)
			}
			if len(queued) != 1 {
				t.Error("the queued interrupt was taken before any start")
			}
			awaitIdle(t)
			if after := len(requestOutcomes("interrupt")); after != before {
				t.Errorf("the server logged %d interrupts, want none", after-before)
			}
		})
	}
}

// streamStub is an API whose run answers write start, then wait for want interrupts before
// their document. Its interrupt call answers status after holding for hold, and records the
// streams it was asked for, in the order they arrived, and whether two were ever in flight
// at once.
type streamStub struct {
	status int
	hold   time.Duration
	want   int

	mu         sync.Mutex
	streams    []string
	got        []string
	inFlight   int
	overlapped bool
	arrived    chan struct{}
}

func newStreamStub(t *testing.T, status int, hold time.Duration, want int) *streamStub {
	t.Helper()
	s := &streamStub{status: status, hold: hold, want: want, arrived: make(chan struct{}, want)}
	mux := http.NewServeMux()
	mux.HandleFunc("POST /v1/streams/{stream}/interrupt", func(w http.ResponseWriter, r *http.Request) {
		s.mu.Lock()
		s.inFlight++
		s.overlapped = s.overlapped || s.inFlight > 1
		s.got = append(s.got, r.PathValue("stream"))
		s.mu.Unlock()
		time.Sleep(s.hold)
		s.mu.Lock()
		s.inFlight--
		s.mu.Unlock()
		w.WriteHeader(s.status)
		w.(http.Flusher).Flush()
		s.arrived <- struct{}{}
	})
	mux.HandleFunc("POST /v1/{noun}/{verb}", func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		s.mu.Lock()
		s.streams = append(s.streams, r.Header.Get(api.HeaderStream))
		s.mu.Unlock()
		w.Header().Set(api.HeaderVersion, api.Version)
		w.Header().Set(api.HeaderBuild, version)
		w.WriteHeader(http.StatusOK)
		a := &fakeAnswer{t: t, w: w}
		a.frame(api.Frame{Start: &api.RunRef{WorkflowID: "fylgja-provision"}})
		for range s.want {
			select {
			case <-s.arrived:
			case <-time.After(5 * time.Second):
				t.Error("an interrupt queued for the run never reached the server")
			}
		}
		// The client has read the last interrupt's answer before the document arrives.
		time.Sleep(50 * time.Millisecond)
		a.frame(api.Frame{Run: &api.RunRef{WorkflowID: "fylgja-provision", RunID: "run-1"}})
		a.document(okDocument(r.PathValue("noun")+"."+r.PathValue("verb")), "")
	})
	srv := httptest.NewServer(mux)
	t.Cleanup(srv.Close)
	useAPIAt(t, strings.TrimPrefix(srv.URL, "http://"), sendToken)
	return s
}

// Interrupts are sent one at a time and in order, each to the stream the run's request named:
// the next is sent once the server has answered the last.
func TestInterruptsAreSentOneAtATime(t *testing.T) {
	stub := newStreamStub(t, http.StatusNoContent, 30*time.Millisecond, 3)
	queued := useInterrupts(t)
	queued <- os.Interrupt
	queued <- os.Interrupt
	// useInterrupts holds two; the third is queued once the first has been taken.
	go func() { queued <- os.Interrupt }()

	var code int
	printedBy(t, func() {
		code = report(&options{asJSON: true}, nil,
			runCreate(context.Background(), &options{asJSON: true}, &createFlags{branch: "fylgja-fixture"}))
	})

	stub.mu.Lock()
	defer stub.mu.Unlock()
	if code != findings.ExitOK {
		t.Errorf("exit %d, want the run's own 0", code)
	}
	if len(stub.streams) != 1 || !streamRE.MatchString(stub.streams[0]) {
		t.Fatalf("run requests named streams %q", stub.streams)
	}
	if len(stub.got) != 3 {
		t.Fatalf("the server was sent %d interrupts, want the three queued", len(stub.got))
	}
	for _, s := range stub.got {
		if s != stub.streams[0] {
			t.Errorf("an interrupt named stream %s, want the request's %s", s, stub.streams[0])
		}
	}
	if stub.overlapped {
		t.Error("two interrupts were in flight at once")
	}
}

// An interrupt for an answer that has just ended is 404: the client reads past it to the
// document, which ends the command as the run's own did.
func TestAnInterruptForAnEndedStreamIsReadPast(t *testing.T) {
	stub := newStreamStub(t, http.StatusNotFound, 0, 1)
	queued := useInterrupts(t)
	queued <- os.Interrupt

	var err error
	_, stderr := printedBy(t, func() {
		err = runCreate(context.Background(), &options{asJSON: true}, &createFlags{branch: "fylgja-fixture"})
	})

	stub.mu.Lock()
	defer stub.mu.Unlock()
	if len(stub.got) != 1 {
		t.Fatalf("the server was sent %d interrupts, want one", len(stub.got))
	}
	doc := sentDocument(t, err)
	if doc.Status != findings.StatusOK || len(doc.Findings) != 0 {
		t.Errorf("status %s, findings %+v; want the run's own document", doc.Status, doc.Findings)
	}
	if stderr != "" {
		t.Errorf("stderr %q, want nothing", stderr)
	}
}

// Every run request the CLI sends names a stream, a fresh one each: two creates name two, and
// a provision and a step one each of their own. A command that starts no run the operator
// can interrupt names none.
func TestEveryRunRequestNamesAFreshStream(t *testing.T) {
	fake := newAPIFake(t, func(w *fakeAnswer, op string, _ api.Request) { w.document(okDocument(op), "") })
	bundleDir := copyGoldenBundle(t, "bundle")
	runs := []struct {
		op  string
		run func() error
	}{
		{findings.OpTwinCreate, func() error {
			return runCreate(context.Background(), &options{}, &createFlags{branch: "fylgja-fixture"})
		}},
		{findings.OpTwinCreate, func() error {
			return runCreate(context.Background(), &options{}, &createFlags{waypoint: "demo/1", waypointGiven: true})
		}},
		{findings.OpTwinProvision, func() error {
			return runTwinProvision(context.Background(), &options{}, &provisionFlags{}, bundleDir)
		}},
		{findings.OpTwinStep, func() error { return runTwinStep(context.Background(), &options{}, &stepFlags{}) }},
		{findings.OpTwinDestroy, func() error { return runDestroy(context.Background(), &options{}) }},
		{findings.OpTwinShow, func() error { return runShow(context.Background(), &options{}) }},
	}
	printedBy(t, func() {
		for _, r := range runs {
			sentDocument(t, r.run())
		}
	})

	seen := fake.seen()
	if len(seen) != len(runs) {
		t.Fatalf("%d requests for %d commands", len(seen), len(runs))
	}
	// The runs the operator may interrupt, named here and not taken from the code under test.
	isRun := map[string]bool{findings.OpTwinCreate: true, findings.OpTwinProvision: true, findings.OpTwinStep: true}
	named := map[string]bool{}
	for i, s := range seen {
		if s.op != runs[i].op {
			t.Fatalf("request %d is %s, want %s", i, s.op, runs[i].op)
		}
		if !isRun[s.op] {
			if s.stream != "" {
				t.Errorf("%s named stream %q, want none", s.op, s.stream)
			}
			continue
		}
		if !streamRE.MatchString(s.stream) {
			t.Errorf("%s named stream %q, want 16 random bytes in hex", s.op, s.stream)
		}
		if named[s.stream] {
			t.Errorf("%s named stream %s, which an earlier run named", s.op, s.stream)
		}
		named[s.stream] = true
	}
}
