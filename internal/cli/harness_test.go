package cli

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/provision"
	"github.com/happypathnetworking/fylgja/internal/server"
	"github.com/happypathnetworking/fylgja/internal/verify"
)

// The harness. Every command these tests run
// is one request to a server in the test's own process: TestMain starts one httptest server
// over a server.Server, with a token made for the run, and points the client's environment
// at it. The server reads the process environment the tests set (the state root, Infrahub's
// variables, the logins) at each request, as fylgja serve reads its own; its log goes to a
// buffer the tests read, never to the process's stderr, which the tests capture.

// harness is the server every command reaches.
var harness struct {
	srv  *server.Server
	http *httptest.Server
	log  *syncBuffer
	// wire is every byte the server wrote: each answer's status, its headers and its body,
	// frames and problem bodies alike, which the credential and marker proofs search.
	wire  *syncBuffer
	token string
	// serving counts the requests the harness's servers have taken and not yet ended. A
	// request's log line is written before its handler returns, and a client returns at the
	// document frame, before that.
	serving atomic.Int64
}

// The seams M12's command tests swapped as package variables, kept here under their names
// and types, so the moved tests set them as written. The harness hands each to the server's
// field it became at every request: dialService is Dial,
// dryRunRunner Runner, verifyReader Reader, verifySleep and verifyNow Sleep and Now,
// showServiceBudget ServiceBudget, and pspDir, which a test sets through usePSPDir where it
// gave options{pspDir: …}, is PSPDir. notifyInterrupt stays the client's own (interrupt.go).
var (
	dialService = func(ctx context.Context) (provision.Service, error) {
		return provision.Dial(ctx, nil)
	}
	dryRunRunner      lab.Runner    = lab.ExecRunner{}
	verifyReader      verify.Reader = lab.GNMIReader{}
	verifySleep       func(ctx context.Context, d time.Duration) error
	verifyNow         func() time.Time
	showServiceBudget = provision.ShowServiceBudget
	pspDir            string
)

// version is the build of the harness's server and of its client: M12's unstamped version,
// which a run records as the CLI's version was.
var version = "0.1.0-dev"

func TestMain(m *testing.M) {
	b := make([]byte, 24)
	if _, err := rand.Read(b); err != nil {
		panic(err)
	}
	harness.token = hex.EncodeToString(b)
	harness.log = &syncBuffer{}
	harness.wire = &syncBuffer{}
	harness.srv = server.New(harness.token)
	harness.srv.Build, build = version, version
	harness.srv.Log = slog.New(slog.NewTextHandler(harness.log, nil))
	handler := harness.srv.Handler()
	harness.http = httptest.NewServer(serving(func(w http.ResponseWriter, r *http.Request) {
		// An interrupt reaches an answer already open, whose request was handed the seams.
		if !strings.Contains(r.URL.Path, "/streams/") {
			handSeams()
		}
		handler.ServeHTTP(&wireRecorder{ResponseWriter: w, wire: harness.wire}, r)
	}))
	getenv = func(name string) (string, bool) {
		switch name {
		case api.EnvAddress:
			return harness.http.URL, true
		case api.EnvToken:
			return harness.token, true
		}
		return "", false
	}
	code := m.Run()
	harness.http.Close()
	os.Exit(code)
}

// serving is h, counted in harness.serving while it runs.
func serving(h http.HandlerFunc) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		harness.serving.Add(1)
		defer harness.serving.Add(-1)
		h(w, r)
	})
}

// handSeams gives the server what the test has set, for the request about to be served.
// The override directory falls back to FYLGJA_PSP_DIR, as M12's options.resolve did.
func handSeams() {
	s := harness.srv
	dial := dialService
	s.Dial = func(ctx context.Context, _ *slog.Logger) (provision.Service, error) { return dial(ctx) }
	s.Runner = dryRunRunner
	s.Reader = verifyReader
	s.Sleep, s.Now = verifySleep, verifyNow
	s.ServiceBudget = showServiceBudget
	s.PSPDir = pspDir
	if s.PSPDir == "" {
		s.PSPDir = os.Getenv(lab.EnvPSPDir)
	}
}

// wireRecorder writes what the server answers to the client and to the harness's wire
// record. It flushes and unwraps as the writer it wraps, so the server's response
// controller reaches the connection through it.
type wireRecorder struct {
	http.ResponseWriter
	wire   *syncBuffer
	headed bool
}

func (w *wireRecorder) WriteHeader(code int) {
	if !w.headed {
		w.headed = true
		var b bytes.Buffer
		fmt.Fprintf(&b, "HTTP %d\n", code)
		_ = w.Header().Write(&b)
		_, _ = w.wire.Write(b.Bytes())
	}
	w.ResponseWriter.WriteHeader(code)
}

func (w *wireRecorder) Write(p []byte) (int, error) {
	if !w.headed {
		w.WriteHeader(http.StatusOK)
	}
	_, _ = w.wire.Write(p)
	return w.ResponseWriter.Write(p)
}

func (w *wireRecorder) Flush() {
	if f, ok := w.ResponseWriter.(http.Flusher); ok {
		f.Flush()
	}
}

func (w *wireRecorder) Unwrap() http.ResponseWriter { return w.ResponseWriter }

// servedMark is where the harness's server's wire record and log stand at a moment.
type servedMark struct{ wire, log int }

// markServed is where they stand now.
func markServed() servedMark {
	return servedMark{wire: len(harness.wire.String()), log: len(harness.log.String())}
}

// since is what the server wrote to its clients, and what it logged, after m, once every
// request it has taken has ended: a command returns at its answer's document, and the server
// logs the request after it, so a read made at once could miss the line, and any secret in
// it.
func (m servedMark) since(t *testing.T) (wire, log string) {
	t.Helper()
	deadline := time.Now().Add(2 * goneBound)
	for harness.serving.Load() != 0 {
		if time.Now().After(deadline) {
			t.Fatalf("the harness's server still serves %d requests after %s", harness.serving.Load(), 2*goneBound)
		}
		time.Sleep(time.Millisecond)
	}
	return harness.wire.String()[m.wire:], harness.log.String()[m.log:]
}

// noSecretServed fails when anything the harness's server wrote to a client or logged after
// m carries the API's token or one of secrets: the frames of every answer, the problem
// bodies, the headers and the log lines.
func noSecretServed(t *testing.T, m servedMark, secrets ...string) {
	t.Helper()
	wire, log := m.since(t)
	if wire == "" || log == "" {
		t.Errorf("the server wrote %d bytes and logged %d since the mark, so their absence of a secret proves nothing",
			len(wire), len(log))
	}
	for _, secret := range append([]string{harness.token}, secrets...) {
		if strings.Contains(wire, secret) {
			t.Errorf("the server wrote a secret to a client:\n%s", wire)
		}
		if strings.Contains(log, secret) {
			t.Errorf("the server logged a secret:\n%s", log)
		}
	}
}

// usePSPDir makes dir the server's override directory for the test's length, where an M12
// test gave the command options{pspDir: dir}.
func usePSPDir(t *testing.T, dir string) {
	t.Helper()
	saved := pspDir
	t.Cleanup(func() { pspDir = saved })
	pspDir = dir
}

// syncBuffer is a buffer the server's goroutines write and a test reads.
type syncBuffer struct {
	mu sync.Mutex
	b  bytes.Buffer
}

func (s *syncBuffer) Write(p []byte) (int, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.b.Write(p)
}

func (s *syncBuffer) String() string {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.b.String()
}

// carriesRule reports whether list holds a finding under rule: M12's helper, which the
// server keeps for its own use and the tests use to read a document.
func carriesRule(list findings.List, rule string) bool {
	for _, f := range list {
		if f.Rule == rule {
			return true
		}
	}
	return false
}

// stagedManifest reads the manifest of the bundle staged in dir, as the server's verify reads
// it: a test that builds a host reads it the same way.
func stagedManifest(dir string) (compiler.Manifest, error) {
	b, err := os.ReadFile(filepath.Join(dir, compiler.ManifestFile))
	if err != nil {
		return compiler.Manifest{}, err
	}
	var m compiler.Manifest
	if err := json.Unmarshal(b, &m); err != nil {
		return compiler.Manifest{}, err
	}
	return m, nil
}

// fileCompiled files a compiled bundle in the store under dir, and the CTM beside it, as a
// run's compile step and the server's waypoint plan file them: a test that builds a host
// files its bundles the same way.
func fileCompiled(ctx context.Context, dir string, files map[string][]byte, id string, snapshot *ctm.CTM) (bundle.Store, findings.List, error) {
	store := bundle.NewDirStore(dir)
	stored, err := bundle.PutFiles(ctx, store, files, dir)
	if err != nil {
		return store, nil, err
	}
	if stored != id {
		return store, nil, fmt.Errorf("the written bundle hashes to %s, but compiled to %s", stored, id)
	}
	scratch, err := os.MkdirTemp(dir, ".fylgja-ctm-*")
	if err != nil {
		return store, nil, err
	}
	defer func() { _ = os.RemoveAll(scratch) }()
	path := filepath.Join(scratch, "ctm.json")
	if err := ctm.Save(snapshot, path); err != nil {
		return store, nil, err
	}
	return store, nil, store.PutCTM(ctx, id, path)
}

// captureStderr runs fn with os.Stderr redirected and returns what it wrote.
func captureStderr(t *testing.T, fn func()) string {
	t.Helper()
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	saved := os.Stderr
	os.Stderr = w
	done := make(chan string)
	go func() {
		b, _ := io.ReadAll(r)
		done <- string(b)
	}()
	defer func() { os.Stderr = saved }()
	fn()
	_ = w.Close()
	return <-done
}

// startRefusal is a way a run does not start that has its own identifier: the workflow
// service not answering, or no worker to take the run.
type startRefusal struct {
	name string
	rule string
	use  func(t *testing.T)
}

func startRefusals() []startRefusal {
	return []startRefusal{
		{"service unreachable", findings.RuleRunServiceUnreachable, func(t *testing.T) {
			saved := dialService
			t.Cleanup(func() { dialService = saved })
			dialService = func(context.Context) (provision.Service, error) {
				return nil, &provision.UnreachableError{Address: "localhost:1", Err: errors.New("connection refused")}
			}
		}},
		{"no worker", findings.RuleRunWorkerAbsent, func(t *testing.T) {
			absent := &provision.StartError{Status: findings.StatusError, Finding: findings.Finding{
				Severity: findings.Rejection, Rule: findings.RuleRunWorkerAbsent, Object: provision.TaskQueue,
				Step: findings.StepStart, Message: "no worker is polling task queue fylgja, so nothing was started",
			}}
			useService(t, &fakeService{startErr: absent, destroyErr: absent})
		}},
	}
}

// wantStartRefusal checks a command reported a start refusal under rule: exit 2, at step
// start, in M2's contract.
func wantStartRefusal(t *testing.T, err error, rule string) {
	t.Helper()
	code, doc := exitOf(t, err)
	if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0].Rule != rule || doc.Findings[0].Step != findings.StepStart {
		t.Errorf("exit %d, findings %+v; want 2 with %s at step start", code, doc.Findings, rule)
	}
	if doc.Subject != nil && doc.Subject.RunID != "" {
		t.Errorf("subject names run %q, but no run was started", doc.Subject.RunID)
	}
	validateM2Document(t, doc)
}
