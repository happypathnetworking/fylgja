package server

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/santhosh-tekuri/jsonschema/v6"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
	"github.com/happypathnetworking/fylgja/internal/verify"
)

// The token a test server is started with, and one it is not. Neither may appear in
// anything the server writes.
const (
	testToken  = "the-api-token-of-this-test-7d1f"
	wrongToken = "a-token-the-server-was-not-given"
	testBuild  = "0.0.0-test"
)

// syncBuffer is the server's log, written by its handlers and read by the test.
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

// requestLines are the log's one-line-a-request entries.
func (s *syncBuffer) requestLines() []string {
	var out []string
	for _, l := range strings.Split(s.String(), "\n") {
		if strings.Contains(l, "msg=request ") {
			out = append(out, l)
		}
	}
	return out
}

// waitForLog waits for a request line holding every part; the line is written once the
// handler has returned, which can be after the client has read the whole answer.
func waitForLog(t *testing.T, log *syncBuffer, parts ...string) string {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for {
		for _, l := range log.requestLines() {
			all := true
			for _, p := range parts {
				all = all && strings.Contains(l, p)
			}
			if all {
				return l
			}
		}
		if time.Now().After(deadline) {
			t.Fatalf("no request line with %q in the log:\n%s", parts, log.String())
		}
		time.Sleep(5 * time.Millisecond)
	}
}

// testServer is a server whose every operation is run, whose log is a buffer, and whose
// dependencies fail the test if anything reaches them: nothing in these tests dials the
// workflow service, runs containerlab or reads a node.
func testServer(t *testing.T, run func(*call) error) (*Server, *httptest.Server, *syncBuffer, *atomic.Int32) {
	t.Helper()
	s := New(testToken)
	s.Build = testBuild
	log := &syncBuffer{}
	s.Log = slog.New(slog.NewTextHandler(log, nil))
	s.Dial = func(context.Context, *slog.Logger) (provision.Service, error) {
		t.Error("the workflow service was dialled")
		return nil, errors.New("not in this test")
	}
	s.Runner = failRunner{t}
	s.Reader = failReader{t}
	calls := &atomic.Int32{}
	for i := range s.ops {
		s.ops[i].run = func(c *call) error {
			calls.Add(1)
			return run(c)
		}
	}
	srv := httptest.NewServer(s.Handler())
	t.Cleanup(srv.Close)
	return s, srv, log, calls
}

type failRunner struct{ t *testing.T }

func (r failRunner) Run(context.Context, []string, ...string) ([]byte, []byte, int, error) {
	r.t.Error("containerlab or docker was run")
	return nil, nil, 1, errors.New("not in this test")
}

type failReader struct{ t *testing.T }

func (r failReader) Get(context.Context, string, wire.Probe, string, func(string) (string, bool)) (verify.Answer, error) {
	r.t.Error("a node was read")
	return verify.Answer{}, errors.New("not in this test")
}

// answered is a stub operation's document: its operation, ok, no findings.
func answered(c *call) error {
	return &result{doc: findings.NewDocument(c.op, nil, nil)}
}

// post sends one request and reads its whole answer.
func post(t *testing.T, client *http.Client, url, token, body string, header map[string]string) (*http.Response, []byte) {
	t.Helper()
	req, err := http.NewRequest(http.MethodPost, url, strings.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	if token != "" {
		req.Header.Set("Authorization", "Bearer "+token)
	}
	for k, v := range header {
		req.Header.Set(k, v)
	}
	if client == nil {
		client = http.DefaultClient
	}
	resp, err := client.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = resp.Body.Close() }()
	b, err := io.ReadAll(resp.Body)
	if err != nil {
		t.Fatalf("reading the answer: %v", err)
	}
	return resp, b
}

// answerLines are an answer's frames, one a line.
func answerLines(t *testing.T, body []byte) [][]byte {
	t.Helper()
	var out [][]byte
	sc := bufio.NewScanner(bytes.NewReader(body))
	sc.Buffer(nil, 1<<20)
	for sc.Scan() {
		out = append(out, append([]byte(nil), sc.Bytes()...))
	}
	if err := sc.Err(); err != nil {
		t.Fatal(err)
	}
	return out
}

func frameOf(t *testing.T, line []byte) api.Frame {
	t.Helper()
	var f api.Frame
	if err := json.Unmarshal(line, &f); err != nil {
		t.Fatalf("a line that is not a frame: %v: %s", err, line)
	}
	return f
}

// apiSchema compiles one definition of the contract's api.schema.json, with the findings
// schema and the blocks it refers to added under their $ids.
func apiSchema(t *testing.T, def string) *jsonschema.Schema {
	t.Helper()
	c := jsonschema.NewCompiler()
	for _, name := range []string{"api.schema.json", "findings.schema.json", "show.schema.json",
		"waypoints.schema.json", "step.schema.json", "verify.schema.json"} {
		f, err := os.Open(filepath.Join("..", "..", "contracts", name))
		if err != nil {
			t.Fatal(err)
		}
		doc, err := jsonschema.UnmarshalJSON(f)
		_ = f.Close()
		if err != nil {
			t.Fatalf("parsing %s: %v", name, err)
		}
		if err := c.AddResource(doc.(map[string]any)["$id"].(string), doc); err != nil {
			t.Fatal(err)
		}
	}
	s, err := c.Compile("https://fylgja.dev/schemas/api.schema.json#/$defs/" + def)
	if err != nil {
		t.Fatal(err)
	}
	return s
}

func satisfies(t *testing.T, s *jsonschema.Schema, raw []byte, label string) {
	t.Helper()
	v, err := jsonschema.UnmarshalJSON(bytes.NewReader(raw))
	if err != nil {
		t.Fatalf("%s: %v", label, err)
	}
	if err := s.Validate(v); err != nil {
		t.Errorf("%s does not satisfy the contract: %v\n%s", label, err, raw)
	}
}

// carriesNoToken fails when either token is in what the server wrote.
func carriesNoToken(t *testing.T, label string, parts ...string) {
	t.Helper()
	for _, p := range parts {
		for _, tok := range []string{testToken, wrongToken} {
			if strings.Contains(p, tok) {
				t.Errorf("%s carries a token: %s", label, p)
			}
		}
	}
}

func headerText(h http.Header) string {
	var b strings.Builder
	for k, vs := range h {
		fmt.Fprintf(&b, "%s: %s\n", k, strings.Join(vs, ","))
	}
	return b.String()
}

// routes are every path the API serves: the twelve operations and the interrupt.
func routes() []string {
	out := make([]string, 0, len(api.Operations)+1)
	for _, op := range api.Operations {
		out = append(out, api.Path(op))
	}
	return append(out, api.InterruptPath("5f1c9a"))
}

// A request without the token, or with another, is 401 with the challenge on every route,
// before the route is looked up or anything is run or dialled; the problem body names
// neither token, and the answer carries neither the version nor the build.
func TestATokenNotTheServersIsRefusedOnEveryRoute(t *testing.T) {
	_, srv, log, calls := testServer(t, answered)
	problem := apiSchema(t, "problem")
	for _, path := range routes() {
		for _, token := range []string{"", wrongToken} {
			resp, body := post(t, nil, srv.URL+path, token, `{}`, nil)
			label := fmt.Sprintf("%s with token %q", path, token)
			if resp.StatusCode != http.StatusUnauthorized {
				t.Errorf("%s: status %d, want 401", label, resp.StatusCode)
			}
			if got := resp.Header.Get("WWW-Authenticate"); got != "Bearer" {
				t.Errorf("%s: WWW-Authenticate %q, want Bearer", label, got)
			}
			if resp.Header.Get(api.HeaderVersion) != "" || resp.Header.Get(api.HeaderBuild) != "" {
				t.Errorf("%s: a refused request was told the version or the build:\n%s", label, headerText(resp.Header))
			}
			satisfies(t, problem, body, label+"'s body")
			carriesNoToken(t, label, string(body), headerText(resp.Header))
		}
	}
	// A header that is not a bearer credential, and a scheme with nothing after it.
	for _, h := range []string{"Basic " + testToken, "Bearer ", testToken} {
		req, _ := http.NewRequest(http.MethodPost, srv.URL+api.Path(findings.OpTwinShow), strings.NewReader(`{}`))
		req.Header.Set("Authorization", h)
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		_ = resp.Body.Close()
		if resp.StatusCode != http.StatusUnauthorized {
			t.Errorf("Authorization %q: status %d, want 401", strings.ReplaceAll(h, testToken, "<token>"), resp.StatusCode)
		}
	}
	if n := calls.Load(); n != 0 {
		t.Errorf("an operation ran %d times for a refused request", n)
	}
	want := 2*len(routes()) + 3
	waitForLog(t, log, "outcome=token_refused", "operation=interrupt")
	deadline := time.Now().Add(5 * time.Second)
	for len(log.requestLines()) < want && time.Now().Before(deadline) {
		time.Sleep(5 * time.Millisecond)
	}
	got := log.requestLines()
	if len(got) != want {
		t.Fatalf("%d request lines for %d requests:\n%s", len(got), want, log.String())
	}
	for _, l := range got {
		if !strings.Contains(l, "level=WARN") || !strings.Contains(l, "outcome=token_refused") {
			t.Errorf("a refused request logged %q", l)
		}
	}
	waitForLog(t, log, "operation=twin.show", "outcome=token_refused")
	carriesNoToken(t, "the log", log.String())
}

// filler is the bytes a countingReader serves: base64's alphabet, so a body of it is a
// file's data that never ends.
var filler = bytes.Repeat([]byte("A"), 32<<10)

// countingReader is a body that counts what the server asked of it.
type countingReader struct {
	n, size int64
	read    atomic.Int64
}

func (r *countingReader) Read(p []byte) (int, error) {
	if r.n >= r.size {
		return 0, io.EOF
	}
	k := min(int64(len(p)), r.size-r.n)
	for i := int64(0); i < k; i += int64(len(filler)) {
		copy(p[i:k], filler)
	}
	r.n += k
	r.read.Add(k)
	return int(k), nil
}

// A request that carries files says Expect: 100-continue, and a refused token is answered
// before the body is asked for: the client sends none of it.
func TestARefusedTokenReadsNoneOfTheBody(t *testing.T) {
	_, srv, _, calls := testServer(t, answered)
	body := &countingReader{size: 8 << 20}
	req, err := http.NewRequest(http.MethodPost, srv.URL+api.Path(findings.OpTwinProvision), body)
	if err != nil {
		t.Fatal(err)
	}
	req.ContentLength = body.size
	req.Header.Set("Authorization", "Bearer "+wrongToken)
	req.Header.Set("Expect", "100-continue")
	client := &http.Client{Transport: &http.Transport{ExpectContinueTimeout: 10 * time.Second}}
	resp, err := client.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	_ = resp.Body.Close()
	if resp.StatusCode != http.StatusUnauthorized {
		t.Fatalf("status %d, want 401", resp.StatusCode)
	}
	if n := body.read.Load(); n != 0 {
		t.Errorf("the client sent %d bytes of a body the server refused before reading", n)
	}
	if calls.Load() != 0 {
		t.Error("the operation ran")
	}
}

// leastRequest is the least request op takes: none, but for twin.provision's bundle
// directory, which is required.
func leastRequest(op string) string {
	if op == findings.OpTwinProvision {
		return `{"args":{"bundle":"b"}}`
	}
	return `{}`
}

// The right token answers 200, as NDJSON, with the API's version and the server's build,
// and the operation's document is the last frame.
func TestTheRightTokenIsAnsweredWithTheVersionAndTheBuild(t *testing.T) {
	_, srv, log, calls := testServer(t, answered)
	for _, op := range api.Operations {
		resp, body := post(t, nil, srv.URL+api.Path(op), testToken, leastRequest(op), nil)
		if resp.StatusCode != http.StatusOK {
			t.Fatalf("%s: status %d, want 200: %s", op, resp.StatusCode, body)
		}
		if got := resp.Header.Get(api.HeaderVersion); got != api.Version {
			t.Errorf("%s: %s %q, want %q", op, api.HeaderVersion, got, api.Version)
		}
		if got := resp.Header.Get(api.HeaderBuild); got != testBuild {
			t.Errorf("%s: %s %q, want %q", op, api.HeaderBuild, got, testBuild)
		}
		if got := resp.Header.Get("Content-Type"); got != "application/x-ndjson" {
			t.Errorf("%s: Content-Type %q", op, got)
		}
		ls := answerLines(t, body)
		if len(ls) != 1 || frameOf(t, ls[0]).Kind() != api.KindDocument {
			t.Fatalf("%s: answer %s, want the document alone", op, body)
		}
		var doc findings.Document
		if err := json.Unmarshal(frameOf(t, ls[0]).Document, &doc); err != nil || doc.Operation != op {
			t.Errorf("%s: the document is %+v (%v)", op, doc, err)
		}
		waitForLog(t, log, "operation="+op+" ", "outcome=ok", "level=INFO")
	}
	if n := int(calls.Load()); n != len(api.Operations) {
		t.Errorf("%d operations ran for %d requests", n, len(api.Operations))
	}
	carriesNoToken(t, "the log", log.String())
}

// From the move every operation of the twelve has its handler, M12's command, and the table
// holds no other.
func TestEveryOperationIsServed(t *testing.T) {
	s := New(testToken)
	if len(s.ops) != len(api.Operations) || len(handlers) != len(api.Operations) {
		t.Errorf("%d operations and %d handlers for the %d of the API", len(s.ops), len(handlers), len(api.Operations))
	}
	for _, op := range s.ops {
		if op.run == nil {
			t.Errorf("%s has no handler", op.name)
		}
		if _, ok := operationArgs[op.name]; !ok {
			t.Errorf("%s names no arguments", op.name)
		}
	}
}

// An argument the operation does not take, a value of another kind, and files on an
// operation that takes none are a request the server cannot read: 400 before the answer
// begins, and no operation runs (contracts/api.md, "The request is decoded strictly").
func TestAnArgumentNotTakenIsUnreadable(t *testing.T) {
	_, srv, log, calls := testServer(t, answered)
	for _, c := range []struct{ op, body, says string }{
		{findings.OpTwinShow, `{"args":{"branch":"b"}}`, `twin.show takes no argument "branch"`},
		{findings.OpTwinCreate, `{"args":{"branch":true}}`, `twin.create's argument "branch" is not a string`},
		{findings.OpTwinCreate, `{"args":{"dry_run":"yes"}}`, `twin.create's argument "dry_run" is not a boolean`},
		{findings.OpTwinVerify, `{"args":{"args":"x"}}`, `twin.verify's argument "args" is not an array of strings`},
		{findings.OpPSPValidate, `{"args":{"files":null}}`, `psp.validate's argument "files" is not an array of strings`},
		{findings.OpTwinCreate, `{"args":{"branch":null}}`, `twin.create's argument "branch" is not a string`},
		// A null element is not an empty string.
		{findings.OpPSPValidate, `{"args":{"files":["a.yaml",null]},"files":[{"path":"a.yaml","data":""}]}`,
			`psp.validate's argument "files" is not an array of strings`},
		{findings.OpTwinVerify, `{"args":{"args":[null]}}`, `twin.verify's argument "args" is not an array of strings`},
		// Keys spelled otherwise than the schema spells them, which encoding/json reads
		// whatever their case: the two bodies seen answered 200 and run.
		{findings.OpPSPValidate, `{"ARGS":{"files":["a.yaml"]},"FILES":[{"PATH":"a.yaml","Data":""}]}`, `unknown field "ARGS"`},
		{findings.OpTwinShow, `{"Render":"json"}`, `unknown field "Render"`},
		{findings.OpPSPValidate, `{"args":{"files":["a.yaml"]},"files":[{"PATH":"a.yaml","Data":""}]}`,
			`unknown field "PATH" in files[0]`},
		{findings.OpTwinShow, `{"files":[{"path":"a","data":""}]}`, "twin.show takes no files"},
		// The two requests no client's command builds, whose answers named "" as the
		// directory or ignored the argument, and each answered 200.
		{findings.OpTwinProvision, `{"files":[{"path":"manifest.json","data":""}]}`,
			`twin.provision takes the bundle directory as its argument "bundle"`},
		{findings.OpTwinProvision, `{"args":{"dry_run":true}}`,
			`twin.provision takes the bundle directory as its argument "bundle"`},
		{findings.OpTwinVerify, `{"args":{"args":["x"]}}`, `twin.verify's argument "args" is given without "wait"`},
		{findings.OpTwinVerify, `{"args":{"args":[]}}`, `twin.verify's argument "args" is given without "wait"`},
	} {
		resp, body := post(t, nil, srv.URL+api.Path(c.op), testToken, c.body, nil)
		var p api.Problem
		if err := json.Unmarshal(body, &p); err != nil || resp.StatusCode != http.StatusBadRequest ||
			p.Message != "the request is not one: "+c.says {
			t.Errorf("%s %s: status %d, body %s; want 400 saying %q", c.op, c.body, resp.StatusCode, body, c.says)
		}
	}
	if n := calls.Load(); n != 0 {
		t.Errorf("%d operations ran", n)
	}
	waitForLog(t, log, "operation=twin.show", "outcome=unreadable", "level=WARN")
	// Every operation but twin.provision, whose bundle directory is required, takes a request
	// with no arguments; a bundle given as empty is one given, as M12's cobra took "".
	for _, op := range api.Operations {
		body := `{"args":{}}`
		if op == findings.OpTwinProvision {
			body = `{"args":{"bundle":""}}`
		}
		resp, _ := post(t, nil, srv.URL+api.Path(op), testToken, body, nil)
		if resp.StatusCode != http.StatusOK {
			t.Errorf("%s with %s: status %d", op, body, resp.StatusCode)
		}
	}
	for _, body := range []string{`{"args":{"wait":"","args":["x"]}}`, `{"args":{"wait":"2m0s"}}`} {
		if resp, _ := post(t, nil, srv.URL+api.Path(findings.OpTwinVerify), testToken, body, nil); resp.StatusCode != http.StatusOK {
			t.Errorf("twin.verify with %s: status %d", body, resp.StatusCode)
		}
	}
}

// A path under no version served is 404 naming the versions there are, and nothing is
// read or run for it; a path under version 1 that names no operation is 404 without it,
// since its version is served.
func TestAnUnknownVersionIsNamedAndNothingIsDone(t *testing.T) {
	_, srv, log, calls := testServer(t, answered)
	problem := apiSchema(t, "problem")
	for _, path := range []string{"/v2/twin/show", "/v0/twin/show", "/twin/show", "/"} {
		resp, body := post(t, nil, srv.URL+path, testToken, `{}`, nil)
		if resp.StatusCode != http.StatusNotFound {
			t.Errorf("%s: status %d, want 404", path, resp.StatusCode)
		}
		if got := resp.Header.Get(api.HeaderVersions); got != "1" {
			t.Errorf("%s: %s %q, want 1", path, api.HeaderVersions, got)
		}
		satisfies(t, problem, body, path)
	}
	for _, path := range []string{"/v1/twin/nope", "/v1/streams/x/nope"} {
		resp, body := post(t, nil, srv.URL+path, testToken, `{}`, nil)
		if resp.StatusCode != http.StatusNotFound || resp.Header.Get(api.HeaderVersions) != "" {
			t.Errorf("%s: status %d with %s %q, want 404 without it", path, resp.StatusCode,
				api.HeaderVersions, resp.Header.Get(api.HeaderVersions))
		}
		satisfies(t, problem, body, path)
		wantNoOperation(t, path, body)
	}
	// A served operation asked with another method is no operation of version 1.
	req, _ := http.NewRequest(http.MethodGet, srv.URL+api.Path(findings.OpTwinShow), nil)
	req.Header.Set("Authorization", "Bearer "+testToken)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	_ = resp.Body.Close()
	if resp.StatusCode != http.StatusNotFound {
		t.Errorf("GET %s: status %d, want 404", api.Path(findings.OpTwinShow), resp.StatusCode)
	}
	if calls.Load() != 0 {
		t.Error("an operation ran for an unknown path")
	}
	waitForLog(t, log, "operation=unknown", "outcome=version_unknown", "level=WARN")
	waitForLog(t, log, "operation=unknown", "outcome=not_found", "level=WARN")
	if strings.Contains(log.String(), "/v2/") || strings.Contains(log.String(), "nope") {
		t.Errorf("the log names a path:\n%s", log.String())
	}
}

// wantNoOperation holds a 404's body to the sentence for a path under version 1 that names
// no operation (contracts/api.md, "The transport's statuses").
func wantNoOperation(t *testing.T, label string, body []byte) {
	t.Helper()
	var p api.Problem
	if err := json.Unmarshal(body, &p); err != nil ||
		p.Message != "API version 1 has no operation at this path; nothing was read or done" {
		t.Errorf("%s: body %s, want the sentence for a path that names no operation", label, body)
	}
}

// What ServeMux would redirect, 301 or 307 with no problem body and no log line, is answered
// as the path it cleans to is: 404 with the problem body and one log line. A path under
// version 1 is answered without Fylgja-Api-Versions, and one under no version with it. An
// operation's path asked with another method is logged under that operation (contracts/api.md;
// contracts/cli.md, fylgja serve's log).
func TestAPathTheMuxWouldRedirectIsNotFound(t *testing.T) {
	_, srv, log, calls := testServer(t, answered)
	problem := apiSchema(t, "problem")
	noFollow := &http.Client{CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	for _, c := range []struct {
		path      string
		versioned bool
	}{
		{"/v1", true},
		{"//v1/twin/show", true},
		{"/v1//twin/show", true},
		{"/v1/./twin/show", true},
		{"/v1/twin/../twin/show", true},
		{"//twin/show", false},
		{"/v2/../v2/twin/show", false},
	} {
		before := len(log.requestLines())
		resp, body := post(t, noFollow, srv.URL+c.path, testToken, `{}`, nil)
		if resp.StatusCode != http.StatusNotFound || resp.Header.Get("Location") != "" {
			t.Errorf("%s: status %d, Location %q; want 404 and no redirect", c.path, resp.StatusCode, resp.Header.Get("Location"))
		}
		satisfies(t, problem, body, c.path)
		if versions := resp.Header.Get(api.HeaderVersions); c.versioned && versions != "" || !c.versioned && versions != "1" {
			t.Errorf("%s: %s %q", c.path, api.HeaderVersions, versions)
		}
		outcome := "outcome=version_unknown"
		if c.versioned {
			wantNoOperation(t, c.path, body)
			outcome = "outcome=not_found"
		}
		waitForLog(t, log, "operation=unknown", outcome, "level=WARN")
		deadline := time.Now().Add(5 * time.Second)
		for len(log.requestLines()) == before && time.Now().Before(deadline) {
			time.Sleep(5 * time.Millisecond)
		}
		if lines := log.requestLines()[before:]; len(lines) != 1 || !strings.Contains(lines[0], "operation=unknown "+outcome) {
			t.Errorf("%s: logged %q, want one line, operation=unknown %s", c.path, lines, outcome)
		}
	}

	req, _ := http.NewRequest(http.MethodGet, srv.URL+api.Path(findings.OpTwinShow), nil)
	req.Header.Set("Authorization", "Bearer "+testToken)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	body, _ := io.ReadAll(resp.Body)
	_ = resp.Body.Close()
	if resp.StatusCode != http.StatusNotFound || resp.Header.Get(api.HeaderVersions) != "" {
		t.Errorf("GET %s: status %d with %s %q, want 404 without it", api.Path(findings.OpTwinShow), resp.StatusCode,
			api.HeaderVersions, resp.Header.Get(api.HeaderVersions))
	}
	wantNoOperation(t, "GET "+api.Path(findings.OpTwinShow), body)
	waitForLog(t, log, "operation=twin.show", "outcome=not_found", "level=WARN")
	if calls.Load() != 0 {
		t.Error("an operation ran for a path the mux would redirect")
	}
}

// A body over the bound is 413 naming it, whether its length was declared or only found
// out; the operation never runs.
func TestABodyOverTheBoundIsRefused(t *testing.T) {
	_, srv, log, calls := testServer(t, answered)
	problem := apiSchema(t, "problem")
	check := func(label string, resp *http.Response, body []byte) {
		t.Helper()
		if resp.StatusCode != http.StatusRequestEntityTooLarge {
			t.Fatalf("%s: status %d, want 413: %s", label, resp.StatusCode, body)
		}
		satisfies(t, problem, body, label)
		var p api.Problem
		if err := json.Unmarshal(body, &p); err != nil {
			t.Fatal(err)
		}
		if p.LimitBytes != 33554432 {
			t.Errorf("%s: limit_bytes %d, want 33554432", label, p.LimitBytes)
		}
		if p.Message != "the request is larger than this server's transfer bound of 33554432 bytes (32 MiB); nothing was read or filed" {
			t.Errorf("%s: message %q", label, p.Message)
		}
	}

	// Declared: refused before any of it is asked for.
	declared := &countingReader{size: api.MaxRequestBytes + 1}
	req, _ := http.NewRequest(http.MethodPost, srv.URL+api.Path(findings.OpTwinProvision), declared)
	req.ContentLength = declared.size
	req.Header.Set("Authorization", "Bearer "+testToken)
	req.Header.Set("Expect", "100-continue")
	client := &http.Client{Transport: &http.Transport{ExpectContinueTimeout: 10 * time.Second}}
	resp, err := client.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	body, _ := io.ReadAll(resp.Body)
	_ = resp.Body.Close()
	check("a declared length", resp, body)
	if n := declared.read.Load(); n != 0 {
		t.Errorf("the client sent %d bytes of a body declared over the bound", n)
	}

	// Found out: a request whose one file never ends, sent with no length.
	pr, pw := io.Pipe()
	go func() {
		_, _ = io.WriteString(pw, `{"files":[{"path":"manifest.json","data":"`)
		_, _ = io.Copy(pw, &countingReader{size: api.MaxRequestBytes + 1})
		_ = pw.Close()
	}()
	req, _ = http.NewRequest(http.MethodPost, srv.URL+api.Path(findings.OpTwinProvision), pr)
	req.Header.Set("Authorization", "Bearer "+testToken)
	resp, err = http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	body, _ = io.ReadAll(resp.Body)
	_ = resp.Body.Close()
	_ = pr.Close()
	check("an undeclared length", resp, body)

	if calls.Load() != 0 {
		t.Error("an operation ran for a body over the bound")
	}
	waitForLog(t, log, "operation=twin.provision", "outcome=too_large", "level=WARN")
}

// A body that is not the request is 400, its sentence beginning "the request is not one: ",
// and the operation never runs (contracts/api.md).
func TestABodyThatIsNotTheRequestIsRefused(t *testing.T) {
	_, srv, log, calls := testServer(t, answered)
	problem := apiSchema(t, "problem")
	for _, c := range []struct{ body, says string }{
		{`{"render":"text","nope":1}`, `json: unknown field "nope"`},
		{`{"files":[{"path":"a","data":"","mode":420}]}`, `json: unknown field "mode"`},
		{`{"render":"yaml"}`, `render "yaml" is neither "text" nor "json"`},
		{`{"files":[{"path":"a","data":"%%%"}]}`, "illegal base64 data at input byte 0"},
		{`{"files":[{"data":""}]}`, "files[0] has no path"},
		{`not json`, "invalid character 'o' in literal null (expecting 'u')"},
		{`{} {}`, "more follows the object"},
	} {
		resp, b := post(t, nil, srv.URL+api.Path(findings.OpPSPValidate), testToken, c.body, nil)
		var p api.Problem
		if err := json.Unmarshal(b, &p); err != nil || resp.StatusCode != http.StatusBadRequest ||
			p.Message != "the request is not one: "+c.says {
			t.Errorf("%s: status %d, body %s; want 400 saying %q", c.body, resp.StatusCode, b, c.says)
		}
		satisfies(t, problem, b, c.body)
	}
	// A stream identity is one path segment of at most 128 characters (contracts/api.md, "A
	// run").
	for _, stream := range []string{"a/b", strings.Repeat("a", 129)} {
		resp, b := post(t, nil, srv.URL+api.Path(findings.OpTwinCreate), testToken, `{}`,
			map[string]string{api.HeaderStream: stream})
		var p api.Problem
		if err := json.Unmarshal(b, &p); err != nil || resp.StatusCode != http.StatusBadRequest ||
			p.Message != "the request is not one: Fylgja-Stream is not a stream identity" {
			t.Errorf("a stream identity of %d characters: status %d, body %s; want 400 saying it is not one",
				len(stream), resp.StatusCode, b)
		}
	}
	if calls.Load() != 0 {
		t.Error("an operation ran for a request it could not read")
	}
	if resp, b := post(t, nil, srv.URL+api.Path(findings.OpTwinCreate), testToken, `{}`,
		map[string]string{api.HeaderStream: strings.Repeat("a", 128)}); resp.StatusCode != http.StatusOK {
		t.Errorf("a stream identity of 128 characters: status %d, body %s; want 200", resp.StatusCode, b)
	}
	waitForLog(t, log, "operation=psp.validate", "outcome=unreadable", "level=WARN")
	if strings.Contains(log.String(), "nope") || strings.Contains(log.String(), "yaml") {
		t.Errorf("the log carries the body:\n%s", log.String())
	}
}

// A run's request registers its stream: an interrupt reaches the handler's channel (204),
// a second request under the same identity while it is open is 409, an interrupt for a
// stream that has ended is 404, and a request with no stream, or an operation that takes
// none, is not reached by any interrupt.
func TestTheStreamCarriesTheInterrupt(t *testing.T) {
	release := make(chan struct{})
	got := make(chan os.Signal, 4)
	run := func(c *call) error {
		_ = c.frames.write(api.Frame{Start: &api.RunRef{WorkflowID: provision.WorkflowProvision}})
		select {
		case sig := <-c.interrupts:
			got <- sig
		case <-release:
		case <-time.After(10 * time.Second):
		}
		return answered(c)
	}
	s, srv, log, _ := testServer(t, run)
	const id = "00112233445566778899aabbccddeeff"

	// The first request, held open past its start frame.
	answer := make(chan []byte, 1)
	go func() {
		_, body := post(t, nil, srv.URL+api.Path(findings.OpTwinCreate), testToken, `{}`,
			map[string]string{api.HeaderStream: id})
		answer <- body
	}()
	waitOpen(t, s, id)

	// A second under the same identity.
	resp, body := post(t, nil, srv.URL+api.Path(findings.OpTwinStep), testToken, `{}`,
		map[string]string{api.HeaderStream: id})
	if resp.StatusCode != http.StatusConflict {
		t.Errorf("a second request under an open stream: status %d, want 409", resp.StatusCode)
	}
	satisfies(t, apiSchema(t, "problem"), body, "409")
	waitForLog(t, log, "operation=twin.step", "outcome=stream_open", "level=WARN")

	// The interrupt.
	resp, _ = post(t, nil, srv.URL+api.InterruptPath(id), testToken, ``, nil)
	if resp.StatusCode != http.StatusNoContent {
		t.Fatalf("an interrupt for an open stream: status %d, want 204", resp.StatusCode)
	}
	select {
	case sig := <-got:
		if sig != os.Interrupt {
			t.Errorf("the handler read %v, want os.Interrupt", sig)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("the interrupt never reached the handler")
	}
	frames := answerLines(t, <-answer)
	if k := frameOf(t, frames[len(frames)-1]).Kind(); k != api.KindDocument {
		t.Errorf("the answer ended with a %q frame", k)
	}
	waitForLog(t, log, "operation=interrupt", "outcome=delivered", "level=INFO")

	// Once the request has ended its stream is gone.
	deadline := time.Now().Add(5 * time.Second)
	for {
		resp, body = post(t, nil, srv.URL+api.InterruptPath(id), testToken, ``, nil)
		if resp.StatusCode == http.StatusNotFound || time.Now().After(deadline) {
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	if resp.StatusCode != http.StatusNotFound || resp.Header.Get(api.HeaderVersions) != "" {
		t.Errorf("an interrupt for an ended stream: status %d, want 404 without %s", resp.StatusCode, api.HeaderVersions)
	}
	satisfies(t, apiSchema(t, "problem"), body, "404")
	waitForLog(t, log, "operation=interrupt", "outcome=stream_ended", "level=INFO")

	// Without the header, and on an operation that takes no interrupt, nothing is
	// registered: an interrupt under that identity reaches nothing.
	for _, c := range []struct{ op, stream string }{
		{findings.OpTwinCreate, ""},
		{findings.OpTwinShow, "ffeeddccbbaa99887766554433221100"},
		{findings.OpTwinDestroy, "ffeeddccbbaa99887766554433221100"},
	} {
		done := make(chan struct{})
		go func() {
			defer close(done)
			post(t, nil, srv.URL+api.Path(c.op), testToken, `{}`, map[string]string{api.HeaderStream: c.stream})
		}()
		time.Sleep(50 * time.Millisecond)
		if c.stream != "" {
			if resp, _ := post(t, nil, srv.URL+api.InterruptPath(c.stream), testToken, ``, nil); resp.StatusCode != http.StatusNotFound {
				t.Errorf("%s: an interrupt reached a request that takes none: status %d", c.op, resp.StatusCode)
			}
		}
		s.streams.mu.Lock()
		open := len(s.streams.chans)
		s.streams.mu.Unlock()
		if open != 0 {
			t.Errorf("%s with stream %q registered a stream", c.op, c.stream)
		}
		select {
		case release <- struct{}{}:
		case <-time.After(5 * time.Second):
			t.Errorf("%s with stream %q: the operation ended before it was released", c.op, c.stream)
		}
		<-done
	}
	select {
	case sig := <-got:
		t.Errorf("a request with no stream read an interrupt: %v", sig)
	default:
	}
}

// waitOpen waits for a request to have registered its stream.
func waitOpen(t *testing.T, s *Server, id string) {
	t.Helper()
	deadline := time.Now().Add(5 * time.Second)
	for {
		s.streams.mu.Lock()
		_, open := s.streams.chans[id]
		s.streams.mu.Unlock()
		if open {
			return
		}
		if time.Now().After(deadline) {
			t.Fatalf("stream %s never opened", id)
		}
		time.Sleep(5 * time.Millisecond)
	}
}

// Interrupts past the channel's capacity are dropped without blocking the call that
// delivered them, as a third signal was to M12's channel.
func TestAFullStreamDropsAnInterrupt(t *testing.T) {
	st := newStreams()
	ch, release, ok := st.open("x")
	if !ok {
		t.Fatal("not opened")
	}
	for range 3 {
		if !st.interrupt("x") {
			t.Fatal("not delivered")
		}
	}
	if len(ch) != streamCapacity {
		t.Errorf("%d interrupts held, want %d", len(ch), streamCapacity)
	}
	if _, _, ok := st.open("x"); ok {
		t.Error("an open identity was opened again")
	}
	release()
	if st.interrupt("x") {
		t.Error("an interrupt reached a released stream")
	}
	if _, _, ok := st.open("x"); !ok {
		t.Error("a released identity could not be opened again")
	}
}

// A client that goes away mid-answer ends the call's context, so the request's work stops;
// no document is written, and the log says the client went.
func TestAClientGoneEndsTheCallsContext(t *testing.T) {
	gone := make(chan struct{})
	run := func(c *call) error {
		c.console.note("working")
		select {
		case <-c.ctx.Done():
			close(gone)
		case <-time.After(10 * time.Second):
		}
		return answered(c)
	}
	_, srv, log, _ := testServer(t, run)
	ctx, cancel := context.WithCancel(context.Background())
	req, _ := http.NewRequestWithContext(ctx, http.MethodPost, srv.URL+api.Path(findings.OpTwinShow),
		strings.NewReader(`{"render":"text"}`))
	req.Header.Set("Authorization", "Bearer "+testToken)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	line, err := bufio.NewReader(resp.Body).ReadBytes('\n')
	if err != nil || frameOf(t, line).Out != "working\n" {
		t.Fatalf("first frame %s (%v)", line, err)
	}
	cancel()
	_ = resp.Body.Close()
	select {
	case <-gone:
	case <-time.After(5 * time.Second):
		t.Fatal("the call's context did not end when its client went")
	}
	waitForLog(t, log, "operation=twin.show", "outcome=client_gone", "level=WARN")
}

// A panic in an operation is recovered and logged by its operation alone, and the answer
// ends with no document, which a client reports as not finished.
func TestAPanicEndsTheAnswerWithoutADocument(t *testing.T) {
	run := func(c *call) error {
		c.console.note("before")
		panic("a value that names " + testToken)
	}
	_, srv, log, _ := testServer(t, run)
	req, _ := http.NewRequest(http.MethodPost, srv.URL+api.Path(findings.OpWaypointPlan), strings.NewReader(`{"render":"text"}`))
	req.Header.Set("Authorization", "Bearer "+testToken)
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	body, readErr := io.ReadAll(resp.Body)
	_ = resp.Body.Close()
	if readErr == nil {
		t.Error("the answer ended cleanly after a panic")
	}
	for _, l := range answerLines(t, body) {
		if frameOf(t, l).Kind() == api.KindDocument {
			t.Errorf("a document after a panic: %s", l)
		}
	}
	l := waitForLog(t, log, "operation=waypoint.plan", "outcome=panic", "level=ERROR")
	if strings.Contains(log.String(), "a value that names") {
		t.Errorf("the log carries the panic's value: %s", l)
	}
	carriesNoToken(t, "the log", log.String())
}

// The console's three renderings give the API's frames, each a whole line: under
// text every note as out and every stderr write and dependency warning as err, the document
// last with its findings as text; under json the err frames alone and no text; absent, the
// document alone, the warning in the server's log. Every frame satisfies the contract, and
// a document re-indents to WriteJSON's bytes.
func TestTheConsoleRendersAsAsked(t *testing.T) {
	doc := findings.NewDocument(findings.OpTwinVerify, &findings.Subject{Branch: "b"},
		findings.List{{Severity: findings.Warning, Rule: findings.RuleVerifyWaitUnsettled, Object: "twin", Message: "a warning <of the document>"}})
	run := func(c *call) error {
		c.console.note("a line for stdout %d", 1)
		_, _ = io.WriteString(c.console.stderr(), "a line for stderr\npart of ")
		_, _ = io.WriteString(c.console.stderr(), "a line\n")
		c.log.Info("a dependency's chatter")
		c.log.Warn("a dependency's warning")
		_ = c.frames.write(api.Frame{Start: &api.RunRef{WorkflowID: provision.WorkflowStep}})
		_ = c.frames.write(api.Frame{Run: &api.RunRef{WorkflowID: provision.WorkflowStep, RunID: "01a1"}})
		_ = c.frames.write(api.Frame{Event: &api.Event{WorkflowID: provision.WorkflowStep, Step: "read", End: true, Outcome: "done", DurationS: 2.1}})
		_ = c.frames.write(api.Frame{Event: &api.Event{Notice: "a notice"}})
		_ = c.frames.write(api.Frame{Files: []api.File{{Path: "ctm.json", Data: []byte("{}")}}})
		_, _ = io.WriteString(c.console.stderr(), "no newline")
		return &result{doc: doc}
	}
	_, srv, log, _ := testServer(t, run)
	frame := apiSchema(t, "frame")
	var want bytes.Buffer
	if err := doc.WriteJSON(&want); err != nil {
		t.Fatal(err)
	}
	var wantText strings.Builder
	if err := doc.WriteText(&wantText); err != nil {
		t.Fatal(err)
	}
	other := []string{api.KindStart, api.KindRun, api.KindEvent, api.KindEvent, api.KindFiles}

	for _, c := range []struct {
		render string
		want   []string // the kinds and texts of the out and err frames, in order
		text   string
	}{
		{api.RenderText, []string{"out:a line for stdout 1\n", "err:a line for stderr\n", "err:part of a line\n", "err:WARN"}, wantText.String()},
		{api.RenderJSON, []string{"err:a line for stderr\n", "err:part of a line\n", "err:WARN"}, ""},
		{"", nil, ""},
	} {
		body := `{}`
		if c.render != "" {
			body = `{"render":"` + c.render + `"}`
		}
		_, answer := post(t, nil, srv.URL+api.Path(findings.OpTwinVerify), testToken, body, nil)
		ls := answerLines(t, answer)
		var printed, kinds []string
		for _, l := range ls {
			satisfies(t, frame, l, fmt.Sprintf("render %q's frame", c.render))
			f := frameOf(t, l)
			switch f.Kind() {
			case api.KindOut:
				printed = append(printed, "out:"+f.Out)
			case api.KindErr:
				if strings.Contains(f.Err, "level=WARN") {
					if !strings.Contains(f.Err, `msg="a dependency's warning"`) || !strings.HasSuffix(f.Err, "\n") {
						t.Errorf("render %q: the warning's frame %q", c.render, f.Err)
					}
					printed = append(printed, "err:WARN")
				} else if f.Err != "no newline" {
					printed = append(printed, "err:"+f.Err)
				}
				if strings.Contains(f.Err, "chatter") {
					t.Errorf("render %q: a dependency's info line was sent", c.render)
				}
			default:
				kinds = append(kinds, f.Kind())
			}
		}
		if !slices.Equal(printed, c.want) {
			t.Errorf("render %q: out and err frames %q, want %q", c.render, printed, c.want)
		}
		if want := append(slices.Clone(other), api.KindDocument); !slices.Equal(kinds, want) {
			t.Errorf("render %q: frames %v, want %v", c.render, kinds, want)
		}
		last := frameOf(t, ls[len(ls)-1])
		if last.Kind() != api.KindDocument {
			t.Fatalf("render %q: the last frame is %q", c.render, last.Kind())
		}
		if c.render != "" {
			if prev := frameOf(t, ls[len(ls)-2]); prev.Err != "no newline" {
				t.Errorf("render %q: what stderr held was not sent before the document: %+v", c.render, prev)
			}
		}
		var indented bytes.Buffer
		if err := json.Indent(&indented, last.Document, "", "  "); err != nil {
			t.Fatal(err)
		}
		indented.WriteByte('\n')
		if !bytes.Equal(indented.Bytes(), want.Bytes()) {
			t.Errorf("render %q: the document re-indents to\n%s\nnot WriteJSON's\n%s", c.render, indented.Bytes(), want.Bytes())
		}
		if last.Text != c.text {
			t.Errorf("render %q: text %q, want %q", c.render, last.Text, c.text)
		}
	}
	// Absent, the warning went to the server's log under its operation, and the info line
	// nowhere.
	l := log.String()
	if !strings.Contains(l, `msg="a dependency's warning" operation=twin.verify`) {
		t.Errorf("the server's log does not carry the warning of a request that asked for no rendering:\n%s", l)
	}
	if strings.Contains(l, "chatter") {
		t.Errorf("the server's log carries a dependency's info line:\n%s", l)
	}
}

// A document with no findings has no text, under any rendering.
func TestADocumentWithoutFindingsHasNoText(t *testing.T) {
	_, srv, _, _ := testServer(t, answered)
	_, body := post(t, nil, srv.URL+api.Path(findings.OpTwinShow), testToken, `{"render":"text"}`, nil)
	if f := frameOf(t, answerLines(t, body)[0]); f.Text != "" || !bytes.Contains(body, []byte(`"findings":[]`)) {
		t.Errorf("frame %s", body)
	}
}

// What a request builds for the move's handlers: the packages from the server's directory,
// the host's activities over the server's runner and environment, and the node reader with
// the request's logger.
func TestACallBuildsWhatItsRequestNeeds(t *testing.T) {
	s := New(testToken)
	s.Build = testBuild
	s.Getenv = func(string) (string, bool) { return "", false }
	c := s.newCall(context.Background(), findings.OpTwinVerify, api.Request{Render: api.RenderText},
		newFrames(io.Discard, nil), nil)

	reg, err := c.packages()
	if err != nil || len(reg.Platforms()) == 0 {
		t.Fatalf("the embedded packages: %v", err)
	}
	s.PSPDir = filepath.Join(t.TempDir(), "absent")
	if _, err := c.packages(); err == nil {
		t.Error("an override directory that is not there loaded")
	}

	paths := lab.PathsAt(t.TempDir())
	a := c.activities(reg, paths)
	if a.Clab.Runner != s.Runner || a.Clab.Log != c.log || a.Paths != paths || a.Registry != reg || a.Version != testBuild {
		t.Errorf("activities %+v", a)
	}
	if _, ok := a.Getenv("FYLGJA_HOST_MEMORY_MB"); ok {
		t.Error("the activities do not read the server's environment")
	}
	if r, ok := c.reader().(lab.GNMIReader); !ok || r.Log != c.log {
		t.Errorf("the reader %#v does not log to the request", c.reader())
	}
	own := lab.GNMIReader{Log: s.Log}
	s.Reader = own
	if r := c.reader().(lab.GNMIReader); r.Log != s.Log {
		t.Error("a reader with a logger of its own was given the request's")
	}
	s.Reader = failReader{t}
	if _, ok := c.reader().(failReader); !ok {
		t.Error("a fake reader was replaced")
	}
}

// A server given no token refuses every request, an empty credential included.
func TestAServerWithNoTokenRefusesEveryRequest(t *testing.T) {
	s := New("")
	s.Log = slog.New(slog.NewTextHandler(io.Discard, nil))
	srv := httptest.NewServer(s.Handler())
	defer srv.Close()
	for _, h := range []string{"Bearer ", "Bearer x", ""} {
		req, _ := http.NewRequest(http.MethodPost, srv.URL+api.Path(findings.OpTwinShow), strings.NewReader(`{}`))
		req.Header.Set("Authorization", h)
		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			t.Fatal(err)
		}
		_ = resp.Body.Close()
		if resp.StatusCode != http.StatusUnauthorized {
			t.Errorf("Authorization %q: status %d, want 401", h, resp.StatusCode)
		}
	}
}

// The API's client and this server speak one wire: a run's request named by its stream,
// its start frame, an interrupt delivered and read by the handler, the document; an
// interrupt once the answer has ended; files sent with Expect: 100-continue; and a client
// with another token refused (contracts/api.md).
func TestTheClientSpeaksToTheServer(t *testing.T) {
	interrupted := make(chan struct{}, 1)
	var sent atomic.Int32
	run := func(c *call) error {
		sent.Store(int32(len(c.req.Files)))
		if c.op != findings.OpTwinCreate {
			return answered(c)
		}
		_ = c.frames.write(api.Frame{Start: &api.RunRef{WorkflowID: provision.WorkflowProvision}})
		select {
		case <-c.interrupts:
			interrupted <- struct{}{}
		case <-time.After(5 * time.Second):
		}
		return answered(c)
	}
	_, srv, _, _ := testServer(t, run)
	address := strings.TrimPrefix(srv.URL, "http://")
	getenv := func(token string) func(string) (string, bool) {
		return func(name string) (string, bool) {
			switch name {
			case api.EnvAddress:
				return address, true
			case api.EnvToken:
				return token, true
			}
			return "", false
		}
	}
	client, err := api.NewClient(getenv(testToken), testBuild)
	if err != nil {
		t.Fatal(err)
	}
	const stream = "0123456789abcdef0123456789abcdef"
	var build string
	ans, err := client.Do(context.Background(), findings.OpTwinCreate, api.Request{Render: api.RenderText}, stream,
		func(b string) { build = b })
	if err != nil {
		t.Fatal(err)
	}
	if build != testBuild {
		t.Errorf("the server's build reached the client as %q", build)
	}
	if f, err := ans.Next(); err != nil || f.Kind() != api.KindStart {
		t.Fatalf("first frame %+v (%v)", f, err)
	}
	if err := client.Interrupt(context.Background(), stream); err != nil {
		t.Fatalf("the interrupt: %v", err)
	}
	select {
	case <-interrupted:
	case <-time.After(5 * time.Second):
		t.Fatal("the handler never read the interrupt")
	}
	f, err := ans.Next()
	if err != nil || f.Kind() != api.KindDocument {
		t.Fatalf("last frame %+v (%v)", f, err)
	}
	deadline := time.Now().Add(5 * time.Second)
	for err = client.Interrupt(context.Background(), stream); err == nil && time.Now().Before(deadline); err = client.Interrupt(context.Background(), stream) {
		time.Sleep(5 * time.Millisecond)
	}
	if !errors.Is(err, api.ErrStreamEnded) {
		t.Errorf("an interrupt after the answer: %v, want ErrStreamEnded", err)
	}

	ans, err = client.Do(context.Background(), findings.OpPSPValidate,
		api.Request{Files: []api.File{{Path: "a.yaml", Data: []byte("x: 1\n")}, {Path: "b.yaml"}}}, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	if f, err := ans.Next(); err != nil || f.Kind() != api.KindDocument || sent.Load() != 2 {
		t.Errorf("files: %+v (%v), %d files reached the handler", f, err, sent.Load())
	}

	other, err := api.NewClient(getenv(wrongToken), testBuild)
	if err != nil {
		t.Fatal(err)
	}
	var refused *api.TokenRefused
	if _, err := other.Do(context.Background(), findings.OpPSPValidate,
		api.Request{Files: []api.File{{Path: "a.yaml", Data: []byte("x: 1\n")}}}, "", nil); !errors.As(err, &refused) {
		t.Errorf("another token: %T %v", err, err)
	}
}
