package cli

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"regexp"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
)

const sendToken = "the-api-token-of-the-send-tests-0b7e"

// apiFake is an API that answers each operation with the frames its answer function gives,
// as fylgja serve writes them, and records what it was sent.
type apiFake struct {
	srv    *httptest.Server
	answer func(w *fakeAnswer, op string, req api.Request)

	mu         sync.Mutex
	requests   []fakeRequestSeen
	interrupts []string
	interrupt  chan string
}

type fakeRequestSeen struct {
	op     string
	stream string
	body   []byte
	req    api.Request
}

// fakeAnswer writes an answer's frames, each flushed as written.
type fakeAnswer struct {
	t *testing.T
	w http.ResponseWriter
}

func (a *fakeAnswer) frame(f api.Frame) {
	a.t.Helper()
	b, err := json.Marshal(f)
	if err != nil {
		a.t.Fatal(err)
	}
	_, _ = a.w.Write(append(b, '\n'))
	a.w.(http.Flusher).Flush()
}

// document writes the document frame as the server does: WriteJSON's bytes, and text when
// one is given.
func (a *fakeAnswer) document(doc *findings.Document, text string) {
	a.t.Helper()
	var b bytes.Buffer
	if err := doc.WriteJSON(&b); err != nil {
		a.t.Fatal(err)
	}
	a.frame(api.Frame{Document: b.Bytes(), Text: text})
}

func newAPIFake(t *testing.T, answer func(w *fakeAnswer, op string, req api.Request)) *apiFake {
	t.Helper()
	f := &apiFake{answer: answer, interrupt: make(chan string, 4)}
	mux := http.NewServeMux()
	mux.HandleFunc("POST /v1/streams/{stream}/interrupt", func(w http.ResponseWriter, r *http.Request) {
		f.mu.Lock()
		f.interrupts = append(f.interrupts, r.PathValue("stream"))
		f.mu.Unlock()
		f.interrupt <- r.PathValue("stream")
		w.WriteHeader(http.StatusNoContent)
	})
	mux.HandleFunc("POST /v1/{noun}/{verb}", func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer "+sendToken {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		body, _ := io.ReadAll(r.Body)
		req, err := api.DecodeRequest(bytes.NewReader(body))
		if err != nil {
			t.Errorf("the client sent a request the server cannot read: %v", err)
		}
		op := r.PathValue("noun") + "." + r.PathValue("verb")
		f.mu.Lock()
		f.requests = append(f.requests, fakeRequestSeen{op: op, stream: r.Header.Get(api.HeaderStream), body: body, req: req})
		f.mu.Unlock()
		w.Header().Set(api.HeaderVersion, api.Version)
		// The client's own build: a different one is TestSendSaysTheServerIsAnotherBuild's.
		w.Header().Set(api.HeaderBuild, build)
		w.Header().Set("Content-Type", "application/x-ndjson")
		w.WriteHeader(http.StatusOK)
		f.answer(&fakeAnswer{t: t, w: w}, op, req)
	})
	f.srv = httptest.NewServer(mux)
	t.Cleanup(f.srv.Close)
	useAPIAt(t, strings.TrimPrefix(f.srv.URL, "http://"), sendToken)
	return f
}

func (f *apiFake) seen() []fakeRequestSeen {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]fakeRequestSeen(nil), f.requests...)
}

// useAPIAt gives the client an environment of the API's two variables alone.
func useAPIAt(t *testing.T, address, token string) {
	t.Helper()
	old := getenv
	getenv = func(name string) (string, bool) {
		switch name {
		case api.EnvAddress:
			return address, true
		case api.EnvToken:
			return token, token != ""
		}
		t.Errorf("the client asked its environment for %s", name)
		return "", false
	}
	t.Cleanup(func() { getenv = old })
}

// printedBy runs fn with stdout and stderr each a pipe, and returns what it printed there.
func printedBy(t *testing.T, fn func()) (stdout, stderr string) {
	t.Helper()
	oldOut, oldErr := os.Stdout, os.Stderr
	outR, outW, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	errR, errW, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	os.Stdout, os.Stderr = outW, errW
	var wg sync.WaitGroup
	var outB, errB bytes.Buffer
	wg.Add(2)
	go func() { defer wg.Done(); _, _ = io.Copy(&outB, outR) }()
	go func() { defer wg.Done(); _, _ = io.Copy(&errB, errR) }()
	defer func() {
		os.Stdout, os.Stderr = oldOut, oldErr
	}()
	fn()
	_ = outW.Close()
	_ = errW.Close()
	wg.Wait()
	return outB.String(), errB.String()
}

// sentDocument is the document a command's result carries, as send returns it.
func sentDocument(t *testing.T, err error) *findings.Document {
	t.Helper()
	var res *result
	if !errors.As(err, &res) {
		t.Fatalf("send returned %T %v, not a document", err, err)
	}
	return res.doc
}

func okDocument(op string) *findings.Document {
	return findings.NewDocument(op, &findings.Subject{Branch: "fylgja-fixture"}, nil)
}

// The rendering asked for is the one --json selects: text without it, which carries M12's
// lines, and json with it, which carries only what M12 wrote to stderr.
func TestSendAsksForTheRenderingJSONSelects(t *testing.T) {
	fake := newAPIFake(t, func(w *fakeAnswer, op string, _ api.Request) { w.document(okDocument(op), "") })
	for _, asJSON := range []bool{false, true} {
		printedBy(t, func() {
			_ = send(context.Background(), &options{asJSON: asJSON}, findings.OpTwinShow, nil, nil, handlers{})
		})
	}
	seen := fake.seen()
	if len(seen) != 2 || seen[0].req.Render != api.RenderText || seen[1].req.Render != api.RenderJSON {
		t.Errorf("renderings %+v", seen)
	}
}

// args carry the flags given and nothing else, each at its value as given: an empty
// --interval= is present as "", a flag not given is absent, and a command with none sends
// no args at all.
func TestSendCarriesTheGivenFlagsAlone(t *testing.T) {
	fake := newAPIFake(t, func(w *fakeAnswer, op string, _ api.Request) { w.document(okDocument(op), "") })
	printedBy(t, func() {
		_ = send(context.Background(), &options{}, findings.OpTwinCreate,
			map[string]any{"branch": "fylgja-fixture", "interval": "", "no_follow": true}, nil, handlers{})
		_ = send(context.Background(), &options{}, findings.OpTwinShow, nil, nil, handlers{})
	})
	seen := fake.seen()
	args := seen[0].req.Args
	if len(args) != 3 || string(args["branch"]) != `"fylgja-fixture"` || string(args["interval"]) != `""` ||
		string(args["no_follow"]) != `true` {
		t.Errorf("args %s", seen[0].body)
	}
	if _, ok := args["at"]; ok {
		t.Error("a flag not given was sent")
	}
	if bytes.Contains(seen[1].body, []byte(`"args"`)) {
		t.Errorf("a command with no flags sent args: %s", seen[1].body)
	}
}

// Each out frame is printed to stdout and each err frame to stderr as it arrives; an event
// and a frame of a kind this build does not know print nothing; the document ends the
// command, and report prints its text on stderr, with the document's exit status.
func TestSendPrintsTheFramesAsReceived(t *testing.T) {
	doc := findings.NewDocument(findings.OpTwinCreate, nil,
		findings.List{{Severity: findings.Rejection, Rule: findings.RuleRunInFlight, Object: "fylgja-provision", Message: "a run is in flight"}})
	var text strings.Builder
	_ = doc.WriteText(&text)
	newAPIFake(t, func(w *fakeAnswer, op string, _ api.Request) {
		w.frame(api.Frame{Out: "a first line\n"})
		w.frame(api.Frame{Err: "fylgja: a line for stderr\n"})
		w.frame(api.Frame{Event: &api.Event{Step: "read", End: false}})
		_, _ = w.w.Write([]byte(`{"progress":{"pct":50}}` + "\n"))
		w.frame(api.Frame{Out: "a second line\n"})
		w.document(doc, text.String())
	})
	var code int
	stdout, stderr := printedBy(t, func() {
		opts := &options{}
		err := send(context.Background(), opts, findings.OpTwinCreate, nil, nil, handlers{})
		code = report(opts, nil, err)
	})
	if stdout != "a first line\na second line\n" {
		t.Errorf("stdout %q", stdout)
	}
	if want := "fylgja: a line for stderr\n" + text.String(); stderr != want {
		t.Errorf("stderr %q, want %q", stderr, want)
	}
	if code != findings.ExitRejected {
		t.Errorf("exit %d, want %d", code, findings.ExitRejected)
	}
}

// Under --json the document is written as WriteJSON writes it, byte for byte, and nothing
// else reaches stdout; every status exits as it did at M12.
func TestReportWritesTheDocumentAsWriteJSON(t *testing.T) {
	for status, code := range map[findings.Status]int{
		findings.StatusOK: 0, findings.StatusRejected: 1, findings.StatusError: 2, findings.StatusFailed: 3,
		findings.StatusUnclean: 4, findings.StatusDiverged: 4, findings.StatusNonconforming: 5,
	} {
		doc := findings.NewDocument(findings.OpTwinVerify, &findings.Subject{Branch: "a <branch> & more"},
			findings.List{{Severity: findings.Warning, Rule: findings.RuleVerifyWaitUnsettled, Object: "twin", Message: "<unsettled>"}})
		doc.Status = status
		newAPIFake(t, func(w *fakeAnswer, op string, _ api.Request) {
			w.frame(api.Frame{Err: "a warning\n"})
			w.document(doc, "")
		})
		var want bytes.Buffer
		if err := doc.WriteJSON(&want); err != nil {
			t.Fatal(err)
		}
		var got int
		stdout, stderr := printedBy(t, func() {
			opts := &options{asJSON: true}
			got = report(opts, nil, send(context.Background(), opts, findings.OpTwinVerify, nil, nil, handlers{}))
		})
		if stdout != want.String() {
			t.Errorf("%s: stdout\n%s\nis not WriteJSON's\n%s", status, stdout, want.String())
		}
		if stderr != "a warning\n" {
			t.Errorf("%s: stderr %q", status, stderr)
		}
		if got != code {
			t.Errorf("%s: exit %d, want %d", status, got, code)
		}
	}
}

// A document the client makes itself is rendered here, as M12's report rendered every one.
func TestReportRendersTheClientsOwnDocument(t *testing.T) {
	for _, asJSON := range []bool{false, true} {
		var code int
		stdout, stderr := printedBy(t, func() {
			code = report(&options{asJSON: asJSON}, nil, fail(findings.OpTwinShow, nil, "a failure of %s", "its own"))
		})
		doc := findings.ErrorDocument(findings.OpTwinShow, nil, "a failure of its own")
		var want bytes.Buffer
		if asJSON {
			_ = doc.WriteJSON(&want)
			if stdout != want.String() || stderr != "" {
				t.Errorf("--json: stdout %q stderr %q", stdout, stderr)
			}
		} else {
			_ = doc.WriteText(&want)
			if stdout != "" || stderr != want.String() {
				t.Errorf("text: stdout %q stderr %q", stdout, stderr)
			}
		}
		if code != findings.ExitError {
			t.Errorf("exit %d", code)
		}
	}
}

// A files frame is handed over before anything after it is printed; a failure to take it
// ends the command with that failure, and nothing after it is printed.
func TestSendHandsTheFilesOverBeforeWhatFollows(t *testing.T) {
	newAPIFake(t, func(w *fakeAnswer, op string, _ api.Request) {
		w.frame(api.Frame{Out: "before\n"})
		w.frame(api.Frame{Files: []api.File{{Path: "ctm.json", Data: []byte(`{"a":1}`)}}})
		w.frame(api.Frame{Out: "after\n"})
		w.document(okDocument(op), "")
	})
	var got []api.File
	stdout, _ := printedBy(t, func() {
		err := send(context.Background(), &options{}, findings.OpIntentRead, nil, nil, handlers{files: func(f []api.File) error {
			got = f
			_, _ = io.WriteString(os.Stdout, "<files taken>\n")
			return nil
		}})
		sentDocument(t, err)
	})
	if stdout != "before\n<files taken>\nafter\n" {
		t.Errorf("stdout %q", stdout)
	}
	if len(got) != 1 || got[0].Path != "ctm.json" || string(got[0].Data) != `{"a":1}` {
		t.Errorf("files %+v", got)
	}

	refused := fail(findings.OpIntentRead, nil, "writing CTM: a disk that is full")
	stdout, _ = printedBy(t, func() {
		err := send(context.Background(), &options{}, findings.OpIntentRead, nil, nil,
			handlers{files: func([]api.File) error { return refused }})
		if err != refused {
			t.Errorf("send returned %v, not the files' failure", err)
		}
	})
	if stdout != "before\n" {
		t.Errorf("stdout after a failed write %q", stdout)
	}
}

var streamRE = regexp.MustCompile(`^[0-9a-f]{32}$`)

// A run's request names a fresh stream, 16 random bytes in hex; a command that starts no
// run the operator can interrupt names none.
func TestSendNamesAStreamForARunAlone(t *testing.T) {
	fake := newAPIFake(t, func(w *fakeAnswer, op string, _ api.Request) { w.document(okDocument(op), "") })
	ops := []string{findings.OpTwinCreate, findings.OpTwinCreate, findings.OpTwinProvision, findings.OpTwinStep,
		findings.OpTwinDestroy, findings.OpTwinShow, findings.OpTwinVerify, findings.OpIntentRead}
	printedBy(t, func() {
		for _, op := range ops {
			_ = send(context.Background(), &options{}, op, nil, nil, handlers{})
		}
	})
	seen := fake.seen()
	streams := map[string]bool{}
	for i, s := range seen {
		if takesInterrupts(s.op) != streamRE.MatchString(s.stream) || (s.stream != "" && !takesInterrupts(s.op)) {
			t.Errorf("%s: stream %q", ops[i], s.stream)
		}
		if s.stream != "" {
			if streams[s.stream] {
				t.Errorf("stream %s named twice", s.stream)
			}
			streams[s.stream] = true
		}
	}
	if len(streams) != 4 {
		t.Errorf("%d streams for four runs", len(streams))
	}
}

// useSignals hands the command a channel of the test's for its interrupts, and counts its
// installs and removals.
func useSignals(t *testing.T, queued int) (installed, stopped *int) {
	t.Helper()
	ch := make(chan os.Signal, 4)
	for range queued {
		ch <- os.Interrupt
	}
	installed, stopped = new(int), new(int)
	old := notifyInterrupt
	notifyInterrupt = func() (<-chan os.Signal, func()) {
		*installed++
		return ch, func() { *stopped++ }
	}
	t.Cleanup(func() { notifyInterrupt = old })
	return installed, stopped
}

// Interrupts are installed at the start frame and not before: one queued before a refusal
// that ends the answer before start reaches no server; after start, each is sent, in
// order, to the stream the request named, and the handler is removed when the command
// ends.
func TestSendArmsTheInterruptsAtTheStart(t *testing.T) {
	var fake *apiFake
	fake = newAPIFake(t, func(w *fakeAnswer, op string, req api.Request) {
		if op == findings.OpTwinShow {
			w.document(okDocument(op), "")
			return
		}
		w.frame(api.Frame{Start: &api.RunRef{WorkflowID: "fylgja-provision"}})
		for range 2 {
			select {
			case <-fake.interrupt:
			case <-time.After(5 * time.Second):
				t.Error("an interrupt queued before the start never reached the server")
			}
		}
		w.document(okDocument(op), "")
	})

	// No start frame: nothing is installed, and the queued interrupt stays the process's.
	installed, stopped := useSignals(t, 1)
	printedBy(t, func() {
		sentDocument(t, send(context.Background(), &options{}, findings.OpTwinShow, nil, nil, handlers{}))
	})
	fake.mu.Lock()
	early := len(fake.interrupts)
	fake.mu.Unlock()
	if *installed != 0 || *stopped != 0 || early != 0 {
		t.Errorf("before any start: %d installs, %d interrupts sent", *installed, early)
	}

	installed, stopped = useSignals(t, 2)
	printedBy(t, func() {
		sentDocument(t, send(context.Background(), &options{}, findings.OpTwinCreate, nil, nil, handlers{}))
	})
	seen := fake.seen()
	stream := seen[len(seen)-1].stream
	fake.mu.Lock()
	got := append([]string(nil), fake.interrupts...)
	fake.mu.Unlock()
	if len(got) != 2 || got[0] != stream || got[1] != stream {
		t.Errorf("interrupts %v, want two for stream %s", got, stream)
	}
	if *installed != 1 || *stopped != 1 {
		t.Errorf("the handler was installed %d and removed %d times", *installed, *stopped)
	}
}

// A failure between the client and the server ends the command with status error, exit 2,
// and nothing on stdout, under the client's own identifier (failures.go; failures_test.go
// words each).
func TestATransportFaultEndsTheCommand(t *testing.T) {
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	closed := l.Addr().String()
	_ = l.Close()
	for _, c := range []struct{ name, address, token, rule string }{
		{"no token", closed, "", findings.RuleAPITokenRefused},
		{"nothing listening", closed, sendToken, findings.RuleAPIUnreachable},
	} {
		useAPIAt(t, c.address, c.token)
		var code int
		stdout, stderr := printedBy(t, func() {
			opts := &options{}
			code = report(opts, nil, send(context.Background(), opts, findings.OpTwinShow, nil, nil, handlers{}))
		})
		if code != findings.ExitError || stdout != "" || !strings.Contains(stderr, c.rule) {
			t.Errorf("%s: exit %d, stdout %q, stderr %q", c.name, code, stdout, stderr)
		}
		if strings.Contains(stderr, sendToken) {
			t.Errorf("%s: the token reached stderr", c.name)
		}
	}
}
