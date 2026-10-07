package cli

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/server"
)

// The client's own failures. Each is worded by the code under test, as
// text on stderr and as the --json document, which satisfies this feature's findings
// contract, and none carries a token.

// clientRun is one command's output in one mode.
type clientRun struct {
	code           int
	stdout, stderr string
	doc            *findings.Document
}

// runBothModes runs a client's command in text and then with --json, each through report as
// main does.
func runBothModes(t *testing.T, run func(opts *options) error) (text, asJSON clientRun) {
	t.Helper()
	return oneMode(t, false, run), oneMode(t, true, run)
}

// oneMode runs a client's command in one mode; with --json its document is decoded and
// checked against this feature's findings contract.
func oneMode(t *testing.T, asJSON bool, run func(opts *options) error) clientRun {
	t.Helper()
	var out clientRun
	out.stdout, out.stderr = printedBy(t, func() {
		opts := &options{asJSON: asJSON}
		out.code = report(opts, nil, run(opts))
	})
	if asJSON {
		out.doc = &findings.Document{}
		if err := json.Unmarshal([]byte(out.stdout), out.doc); err != nil {
			t.Fatalf("--json: stdout is not one findings document: %v\n%s", err, out.stdout)
		}
		validateWithShow(t, currentContract, "M13", out.doc)
	}
	return out
}

// wantClientFailure holds both modes to one finding, the command's own operation, status
// error, exit 2 and no step: the text names the rule and says the message on stderr, and
// nothing reaches stdout; the document carries the finding exactly. Neither carries a token.
func wantClientFailure(t *testing.T, op string, text, asJSON clientRun, want findings.Finding) {
	t.Helper()
	if text.code != findings.ExitError || asJSON.code != findings.ExitError {
		t.Errorf("exit %d in text, %d with --json; want 2", text.code, asJSON.code)
	}
	if text.stdout != "" || !strings.Contains(text.stderr, want.Rule) || !strings.Contains(text.stderr, want.Message) {
		t.Errorf("text: stdout %q, stderr %q; want nothing on stdout and %s saying %q on stderr", text.stdout, text.stderr, want.Rule, want.Message)
	}
	doc := asJSON.doc
	if doc.Operation != op || doc.Status != findings.StatusError || len(doc.Findings) != 1 || doc.Findings[0] != want {
		t.Errorf("document: operation %s, status %s, findings %+v\nwant %s, error, %+v alone", doc.Operation, doc.Status, doc.Findings, op, want)
	}
	for _, s := range []string{text.stdout, text.stderr, asJSON.stdout, asJSON.stderr} {
		for _, token := range []string{sendToken, harness.token, wrongToken} {
			if strings.Contains(s, token) {
				t.Errorf("an output carries a token:\n%s", s)
			}
		}
	}
}

const wrongToken = "a-token-the-server-was-not-started-with-77c1"

// stubAPI serves handler at an address of its own and points the client at it with the send
// tests' token. It returns the address as the client names it.
func stubAPI(t *testing.T, handler http.HandlerFunc) string {
	t.Helper()
	srv := httptest.NewServer(handler)
	t.Cleanup(srv.Close)
	address := strings.TrimPrefix(srv.URL, "http://")
	useAPIAt(t, address, sendToken)
	return address
}

// answerHeaders are the API's headers on an answer, written with its status.
func answerHeaders(w http.ResponseWriter) {
	w.Header().Set(api.HeaderVersion, api.Version)
	w.Header().Set(api.HeaderBuild, build)
	w.Header().Set("Content-Type", "application/x-ndjson")
	w.WriteHeader(http.StatusOK)
}

// dropConnection ends an answer as a server that stops does: the connection closed with the
// answer's chunked body unfinished.
func dropConnection(t *testing.T, w http.ResponseWriter) {
	conn, _, err := w.(http.Hijacker).Hijack()
	if err != nil {
		t.Error(err)
		return
	}
	_ = conn.Close()
}

// closedAddress is an address where nothing listens.
func closedAddress(t *testing.T) string {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	address := l.Addr().String()
	_ = l.Close()
	return address
}

func showCmd(opts *options) error { return runShow(context.Background(), opts) }

func createCmd(opts *options) error {
	return runCreate(context.Background(), opts, &createFlags{branch: "fylgja-fixture"})
}

func TestTheClientsOwnFailures(t *testing.T) {
	t.Run("nothing listens at the address", func(t *testing.T) {
		address := closedAddress(t)
		useAPIAt(t, address, sendToken)
		text, asJSON := runBothModes(t, showCmd)
		wantClientFailure(t, findings.OpTwinShow, text, asJSON, findings.Finding{Severity: findings.Rejection,
			Rule: findings.RuleAPIUnreachable, Object: address,
			Message: "the API at " + address + " cannot be reached: dial tcp " + address + ": connect: connection refused; fylgja serve runs on the lab host"})
	})

	t.Run("what answers is not the API", func(t *testing.T) {
		address := stubAPI(t, func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write([]byte("hello\n")) })
		text, asJSON := runBothModes(t, showCmd)
		wantClientFailure(t, findings.OpTwinShow, text, asJSON, findings.Finding{Severity: findings.Rejection,
			Rule: findings.RuleAPIUnreachable, Object: address,
			Message: "the API at " + address + " cannot be reached: what answers there is not the API: its answer names no " +
				api.HeaderVersion + "; fylgja serve runs on the lab host"})
	})

	for _, c := range []struct {
		name   string
		frames []api.Frame
		suffix string
	}{
		{"the answer cut after its headers", nil, ""},
		{"the answer cut after start", []api.Frame{{Start: &api.RunRef{WorkflowID: "fylgja-provision"}}},
			"; a run may have been started and was not cancelled: fylgja twin show names it"},
		{"the answer cut after run", []api.Frame{{Start: &api.RunRef{WorkflowID: "fylgja-provision"}},
			{Run: &api.RunRef{WorkflowID: "fylgja-provision", RunID: "01a1c0de-0000-7000-8000-000000000001"}}},
			"; run fylgja-provision 01a1c0de-0000-7000-8000-000000000001 was not cancelled and goes on: fylgja twin show names it"},
	} {
		t.Run(c.name, func(t *testing.T) {
			useInterrupts(t)
			address := stubAPI(t, func(w http.ResponseWriter, r *http.Request) {
				answerHeaders(w)
				a := &fakeAnswer{t: t, w: w}
				for _, f := range c.frames {
					a.frame(f)
				}
				dropConnection(t, w)
			})
			text, asJSON := runBothModes(t, createCmd)
			wantClientFailure(t, findings.OpTwinCreate, text, asJSON, findings.Finding{Severity: findings.Rejection,
				Rule: findings.RuleAPIUnreachable, Object: address,
				Message: "the API at " + address + " stopped answering before the command ended: unexpected EOF" + c.suffix})
		})
	}

	// A destroy's answer has fylgja-destroy's start and no run frame. Cut after the start, it
	// says a run may have been started and was not cancelled; cut before it, while following
	// stops, it says nothing of a run.
	for _, c := range []struct {
		name   string
		frames []api.Frame
		suffix string
	}{
		{"a destroy's answer cut while following stops", []api.Frame{{Event: &api.Event{Notice: "cancelling check " +
			"fylgja-reconcile-2026-09-16T19:10:00Z; waiting for its cleanup"}}}, ""},
		{"a destroy's answer cut after its start", []api.Frame{{Start: &api.RunRef{WorkflowID: "fylgja-destroy"}},
			{Event: &api.Event{Notice: "run fylgja-destroy run-d"}}},
			"; a run may have been started and was not cancelled: fylgja twin show names it"},
	} {
		t.Run(c.name, func(t *testing.T) {
			address := stubAPI(t, func(w http.ResponseWriter, r *http.Request) {
				answerHeaders(w)
				a := &fakeAnswer{t: t, w: w}
				for _, f := range c.frames {
					a.frame(f)
				}
				dropConnection(t, w)
			})
			text, asJSON := runBothModes(t, func(opts *options) error { return runDestroy(context.Background(), opts) })
			want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleAPIUnreachable, Object: address,
				Message: "the API at " + address + " stopped answering before the command ended: unexpected EOF" + c.suffix}
			wantClientFailure(t, findings.OpTwinDestroy, text, asJSON, want)
		})
	}

	t.Run("an interrupt to a server that has gone", func(t *testing.T) {
		// The server answers start and run, then stops listening, its answer left open: the
		// interrupt that follows finds no one, and the answer is abandoned. Each mode has a
		// server of its own, since the first stops listening.
		gone := func(t *testing.T) (address string, queue func()) {
			var srv *httptest.Server
			ran := make(chan struct{}, 1)
			srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				_ = srv.Listener.Close()
				answerHeaders(w)
				a := &fakeAnswer{t: t, w: w}
				a.frame(api.Frame{Start: &api.RunRef{WorkflowID: "fylgja-provision"}})
				a.frame(api.Frame{Run: &api.RunRef{WorkflowID: "fylgja-provision", RunID: "run-1"}})
				ran <- struct{}{}
				<-r.Context().Done()
			}))
			t.Cleanup(srv.Close)
			address = strings.TrimPrefix(srv.URL, "http://")
			useAPIAt(t, address, sendToken)
			queued := useInterrupts(t)
			return address, func() {
				<-ran
				// The client has read the run frame before the interrupt is made.
				time.Sleep(100 * time.Millisecond)
				queued <- os.Interrupt
			}
		}
		var runs [2]clientRun
		var addresses [2]string
		for i, j := range []bool{false, true} {
			address, queue := gone(t)
			addresses[i] = address
			go queue()
			runs[i] = oneMode(t, j, createCmd)
		}
		for i := range runs {
			want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleAPIUnreachable, Object: addresses[i],
				Message: "the API at " + addresses[i] + " stopped answering before the command ended: dial tcp " + addresses[i] +
					": connect: connection refused; run fylgja-provision run-1 was not cancelled and goes on: fylgja twin show names it"}
			if i == 0 {
				// The text half of wantClientFailure, held against its own server's address.
				wantClientFailure(t, findings.OpTwinCreate, runs[0], clientRun{code: findings.ExitError,
					doc: findings.RuleErrorDocument(findings.OpTwinCreate, nil, want.Rule, want.Object, want.Message)}, want)
				continue
			}
			wantClientFailure(t, findings.OpTwinCreate, clientRun{code: findings.ExitError, stderr: want.Rule + " " + want.Message},
				runs[1], want)
		}
	})

	// Once an interrupt reached the server, the run was asked to cancel, and an answer cut
	// after it says so rather than that the run was not cancelled: the answer dropped after
	// the first interrupt was answered 204, or a second interrupt that finds the server gone.
	t.Run("the answer cut after an interrupt was delivered", func(t *testing.T) {
		const suffix = "; run fylgja-provision run-1 was asked to cancel and goes on to its cleanup: fylgja twin show names it"
		// asked serves start, and run when named, takes one interrupt with 204, then does what
		// then says: drop the answer, or stop listening with the answer left open.
		asked := func(t *testing.T, named bool, then func(srv *httptest.Server, w http.ResponseWriter, r *http.Request)) (
			address string, queued chan os.Signal, queue func()) {
			var srv *httptest.Server
			ran, delivered := make(chan struct{}, 1), make(chan struct{}, 1)
			srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if strings.Contains(r.URL.Path, "/streams/") {
					// Not kept alive, so a later interrupt dials again and finds the server gone.
					w.Header().Set("Connection", "close")
					w.Header().Set(api.HeaderVersion, api.Version)
					w.Header().Set(api.HeaderBuild, build)
					w.WriteHeader(http.StatusNoContent)
					delivered <- struct{}{}
					return
				}
				answerHeaders(w)
				a := &fakeAnswer{t: t, w: w}
				a.frame(api.Frame{Start: &api.RunRef{WorkflowID: "fylgja-provision"}})
				if named {
					a.frame(api.Frame{Run: &api.RunRef{WorkflowID: "fylgja-provision", RunID: "run-1"}})
				}
				ran <- struct{}{}
				select {
				case <-delivered:
				case <-time.After(goneBound):
					t.Error("no interrupt reached the server")
				}
				// The client has read the 204 before the answer ends.
				time.Sleep(100 * time.Millisecond)
				then(srv, w, r)
			}))
			t.Cleanup(srv.Close)
			address = strings.TrimPrefix(srv.URL, "http://")
			useAPIAt(t, address, sendToken)
			queued = useInterrupts(t)
			return address, queued, func() {
				<-ran
				// The client has read the run frame before the interrupt is made.
				time.Sleep(100 * time.Millisecond)
				queued <- os.Interrupt
			}
		}

		t.Run("then the answer dropped", func(t *testing.T) {
			var runs [2]clientRun
			var addresses [2]string
			for i, j := range []bool{false, true} {
				address, _, queue := asked(t, true, func(_ *httptest.Server, w http.ResponseWriter, _ *http.Request) { dropConnection(t, w) })
				addresses[i] = address
				go queue()
				runs[i] = oneMode(t, j, createCmd)
			}
			for i := range runs {
				want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleAPIUnreachable, Object: addresses[i],
					Message: "the API at " + addresses[i] + " stopped answering before the command ended: unexpected EOF" + suffix}
				if i == 0 {
					wantClientFailure(t, findings.OpTwinCreate, runs[0], clientRun{code: findings.ExitError,
						doc: findings.RuleErrorDocument(findings.OpTwinCreate, nil, want.Rule, want.Object, want.Message)}, want)
					continue
				}
				wantClientFailure(t, findings.OpTwinCreate, clientRun{code: findings.ExitError, stderr: want.Rule + " " + want.Message},
					runs[1], want)
			}
		})

		// Before the run was named, the run may have been started, and was asked to cancel, or
		// its start abandoned (contracts/cli.md).
		t.Run("then the answer dropped, before the run was named", func(t *testing.T) {
			var runs [2]clientRun
			var addresses [2]string
			for i, j := range []bool{false, true} {
				address, _, queue := asked(t, false, func(_ *httptest.Server, w http.ResponseWriter, _ *http.Request) { dropConnection(t, w) })
				addresses[i] = address
				go queue()
				runs[i] = oneMode(t, j, createCmd)
			}
			for i := range runs {
				want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleAPIUnreachable, Object: addresses[i],
					Message: "the API at " + addresses[i] + " stopped answering before the command ended: unexpected EOF" +
						"; a run may have been started and was asked to cancel: fylgja twin show names it"}
				if i == 0 {
					wantClientFailure(t, findings.OpTwinCreate, runs[0], clientRun{code: findings.ExitError,
						doc: findings.RuleErrorDocument(findings.OpTwinCreate, nil, want.Rule, want.Object, want.Message)}, want)
					continue
				}
				wantClientFailure(t, findings.OpTwinCreate, clientRun{code: findings.ExitError, stderr: want.Rule + " " + want.Message},
					runs[1], want)
			}
		})

		t.Run("then a second interrupt to a server that has gone", func(t *testing.T) {
			var runs [2]clientRun
			var addresses [2]string
			for i, j := range []bool{false, true} {
				second := make(chan chan os.Signal, 1)
				address, queued, queue := asked(t, true, func(srv *httptest.Server, _ http.ResponseWriter, r *http.Request) {
					_ = srv.Listener.Close()
					(<-second) <- os.Interrupt
					<-r.Context().Done()
				})
				second <- queued
				addresses[i] = address
				go queue()
				runs[i] = oneMode(t, j, createCmd)
			}
			for i := range runs {
				want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleAPIUnreachable, Object: addresses[i],
					Message: "the API at " + addresses[i] + " stopped answering before the command ended: dial tcp " + addresses[i] +
						": connect: connection refused" + suffix}
				if i == 0 {
					wantClientFailure(t, findings.OpTwinCreate, runs[0], clientRun{code: findings.ExitError,
						doc: findings.RuleErrorDocument(findings.OpTwinCreate, nil, want.Rule, want.Object, want.Message)}, want)
					continue
				}
				wantClientFailure(t, findings.OpTwinCreate, clientRun{code: findings.ExitError, stderr: want.Rule + " " + want.Message},
					runs[1], want)
			}
		})
	})

	t.Run("the token unset", func(t *testing.T) {
		l, err := net.Listen("tcp", "127.0.0.1:0")
		if err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { _ = l.Close() })
		var accepted atomic.Int32
		go func() {
			for {
				c, err := l.Accept()
				if err != nil {
					return
				}
				accepted.Add(1)
				_ = c.Close()
			}
		}()
		useAPIAt(t, l.Addr().String(), "")
		text, asJSON := runBothModes(t, showCmd)
		wantClientFailure(t, findings.OpTwinShow, text, asJSON, findings.Finding{Severity: findings.Rejection,
			Rule: findings.RuleAPITokenRefused, Object: api.EnvToken,
			Message: "FYLGJA_API_TOKEN is not set; a client sends the API's token with every request, and nothing was sent"})
		if n := accepted.Load(); n != 0 {
			t.Errorf("the address took %d connections, want none", n)
		}
	})

	// A token no request header can carry, as a local/.env saved with CRLF line endings
	// leaves every value, is refused as an unset one is: api.token.refused naming the
	// variable, nothing dialled, and not api.unreachable, which net/http's refusal of the
	// header had been reported as.
	t.Run("a token no header can carry", func(t *testing.T) {
		l, err := net.Listen("tcp", "127.0.0.1:0")
		if err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { _ = l.Close() })
		var accepted atomic.Int32
		go func() {
			for {
				c, err := l.Accept()
				if err != nil {
					return
				}
				accepted.Add(1)
				_ = c.Close()
			}
		}()
		for _, token := range []string{sendToken + "\r", sendToken + "\n" + sendToken, "\x7f" + sendToken} {
			useAPIAt(t, l.Addr().String(), token)
			text, asJSON := runBothModes(t, showCmd)
			wantClientFailure(t, findings.OpTwinShow, text, asJSON, findings.Finding{Severity: findings.Rejection,
				Rule: findings.RuleAPITokenRefused, Object: api.EnvToken,
				Message: "FYLGJA_API_TOKEN holds a character a request header cannot carry, such as a carriage return; nothing was sent"})
		}
		if n := accepted.Load(); n != 0 {
			t.Errorf("the address took %d connections, want none", n)
		}
	})

	// A token that ends in a space or a tab is refused before sending, naming the variable,
	// where a server started with the very same token refused it: the server's reader trims a
	// header value's trailing whitespace before it compares the token, and the client said
	// the token differed.
	t.Run("a token that ends in a space or a tab", func(t *testing.T) {
		for _, token := range []string{sendToken + " ", sendToken + "\t"} {
			srv := server.New(token)
			srv.Build = build
			var logged syncBuffer
			srv.Log = slog.New(slog.NewTextHandler(&logged, nil))
			handler := srv.Handler()
			var requests atomic.Int32
			httpSrv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				requests.Add(1)
				handler.ServeHTTP(w, r)
			}))
			useAPIAt(t, strings.TrimPrefix(httpSrv.URL, "http://"), token)
			text, asJSON := runBothModes(t, showCmd)
			httpSrv.Close()
			wantClientFailure(t, findings.OpTwinShow, text, asJSON, findings.Finding{Severity: findings.Rejection,
				Rule: findings.RuleAPITokenRefused, Object: api.EnvToken,
				Message: "FYLGJA_API_TOKEN ends in a space or a tab, which a request header cannot carry; nothing was sent"})
			if n := requests.Load(); n != 0 {
				t.Errorf("%q: the server took %d requests, want none", token, n)
			}
			if strings.Contains(logged.String(), sendToken) {
				t.Errorf("%q: the server's log carries the token:\n%s", token, logged.String())
			}
		}
	})

	// The commands that send files read them before the token: with the token unset and a
	// file that cannot be read, each ends on the file, operation.failed, and not
	// api.token.refused. Both are exit 2, and nothing is sent.
	t.Run("the token unset and a file that cannot be read", func(t *testing.T) {
		l, err := net.Listen("tcp", "127.0.0.1:0")
		if err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { _ = l.Close() })
		var accepted atomic.Int32
		go func() {
			for {
				c, err := l.Accept()
				if err != nil {
					return
				}
				accepted.Add(1)
				_ = c.Close()
			}
		}()
		useAPIAt(t, l.Addr().String(), "")
		missing := filepath.Join(t.TempDir(), "missing")
		for _, c := range []struct {
			op, step, message string
			run               func(opts *options) error
		}{
			{findings.OpCompile, "", "reading CTM: open " + missing + ": no such file or directory", func(opts *options) error {
				return runCompile(opts, &compileFlags{ctmPath: missing, out: filepath.Join(t.TempDir(), "out")})
			}},
			{findings.OpTwinProvision, findings.StepVerify, "reading bundle directory: stat " + missing + ": no such file or directory",
				func(opts *options) error {
					return runTwinProvision(context.Background(), opts, &provisionFlags{}, missing)
				}},
			{findings.OpPSPValidate, "", "open " + missing + ": no such file or directory", func(opts *options) error {
				return runPSPValidate(opts, []string{missing})
			}},
		} {
			run := oneMode(t, true, c.run)
			if run.code != findings.ExitError || len(run.doc.Findings) != 1 || run.doc.Findings[0].Rule != findings.RuleOperationFailed ||
				run.doc.Findings[0].Message != c.message || run.doc.Findings[0].Step != c.step {
				t.Errorf("%s: exit %d, findings %+v; want 2 with %s at step %q saying %q", c.op, run.code, run.doc.Findings,
					findings.RuleOperationFailed, c.step, c.message)
			}
		}
		if n := accepted.Load(); n != 0 {
			t.Errorf("the address took %d connections, want none", n)
		}
	})

	t.Run("a token the server was not started with", func(t *testing.T) {
		address := strings.TrimPrefix(harness.http.URL, "http://")
		useAPIAt(t, address, wrongToken)
		before := len(requestOutcomes(findings.OpTwinShow))
		text, asJSON := runBothModes(t, showCmd)
		wantClientFailure(t, findings.OpTwinShow, text, asJSON, findings.Finding{Severity: findings.Rejection,
			Rule: findings.RuleAPITokenRefused, Object: address,
			Message: "the API at " + address + " refused this client's token; FYLGJA_API_TOKEN must be the token fylgja serve was started with"})
		if got := servedAfter(t, findings.OpTwinShow, before); got != "token_refused" {
			t.Errorf("the server logged %s, want token_refused", got)
		}
	})

	t.Run("a server of version 2 alone", func(t *testing.T) {
		var reached atomic.Int32
		address := stubAPI(t, func(w http.ResponseWriter, r *http.Request) {
			if strings.HasPrefix(r.URL.Path, "/v2/") {
				reached.Add(1)
			}
			w.Header().Set(api.HeaderVersions, "2")
			w.WriteHeader(http.StatusNotFound)
		})
		text, asJSON := runBothModes(t, showCmd)
		wantClientFailure(t, findings.OpTwinShow, text, asJSON, findings.Finding{Severity: findings.Rejection,
			Rule: findings.RuleAPIVersionUnknown, Object: address,
			Message: "the API at " + address + " serves version 2; this client speaks version 1"})
		if reached.Load() != 0 {
			t.Error("a version 2 handler was reached")
		}
	})

	// An address that leads under a prefix the server does not have reaches the server's own
	// 404, which names version 1: that is the 404 as it is, under "anything else", and not a
	// version this client does not speak.
	t.Run("an address under a prefix the server does not have", func(t *testing.T) {
		address := harness.http.URL + "/fylgja"
		useAPIAt(t, address, harness.token)
		text, asJSON := runBothModes(t, showCmd)
		wantClientFailure(t, findings.OpTwinShow, text, asJSON, findings.Finding{Severity: findings.Rejection,
			Rule: findings.RuleOperationFailed, Object: findings.OpTwinShow,
			Message: "the API at " + address + " answered 404 Not Found"})
	})

	// A value that is not an address is refused whole, with nothing sent, and no sentence
	// names a URL's user or password.
	for _, c := range []struct{ name, address, shown, cause string }{
		{"an address with no port", "127.0.0.1:", "127.0.0.1:",
			"127.0.0.1: is not host:port: FYLGJA_API_ADDRESS takes host:port or an http:// or https:// URL"},
		{"an address with a path", "127.0.0.1:7650/x", "127.0.0.1:7650/x",
			"127.0.0.1:7650/x is not host:port: FYLGJA_API_ADDRESS takes host:port or an http:// or https:// URL"},
		{"a URL naming a user and password", "https://operator:pw-of-the-url-5e2a@lab-host:7650/", "https://lab-host:7650/",
			"https://lab-host:7650/ names a user or password, which FYLGJA_API_ADDRESS never carries: it takes host:port or an http:// or https:// URL without one"},
	} {
		t.Run(c.name, func(t *testing.T) {
			useAPIAt(t, c.address, sendToken)
			text, asJSON := runBothModes(t, showCmd)
			wantClientFailure(t, findings.OpTwinShow, text, asJSON, findings.Finding{Severity: findings.Rejection,
				Rule: findings.RuleAPIUnreachable, Object: c.shown,
				Message: "the API at " + c.shown + " cannot be reached: " + c.cause + "; fylgja serve runs on the lab host"})
			for _, s := range []string{text.stdout, text.stderr, asJSON.stdout, asJSON.stderr} {
				if strings.Contains(s, "pw-of-the-url-5e2a") || strings.Contains(s, "operator:") {
					t.Errorf("an output names the URL's user or password:\n%s", s)
				}
			}
		})
	}

	// A port that is not a decimal port number from 1 to 65535, and a control character such as
	// the carriage return a local/.env saved with CRLF line endings leaves, are refused as the
	// address's own fault, nothing dialled, where the URL parser's refusal of the request had
	// ended api.unreachable naming an invalid port. An address holding a control character is
	// named as Go quotes a string, in the object and in every sentence, so that none reaches
	// the output.
	t.Run("an address whose port is not a port number, or that holds a control character", func(t *testing.T) {
		l, err := net.Listen("tcp", "127.0.0.1:0")
		if err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { _ = l.Close() })
		var accepted atomic.Int32
		go func() {
			for {
				c, err := l.Accept()
				if err != nil {
					return
				}
				accepted.Add(1)
				_ = c.Close()
			}
		}()
		listening := l.Addr().String()
		const notHostPort = " is not host:port: FYLGJA_API_ADDRESS takes host:port or an http:// or https:// URL"
		const notAURL = " is not a URL of a server: FYLGJA_API_ADDRESS takes host:port or an http:// or https:// URL"
		for _, c := range []struct{ address, shown, cause string }{
			{listening + "x", listening + "x", listening + "x" + notHostPort},
			{"127.0.0.1:http", "127.0.0.1:http", "127.0.0.1:http" + notHostPort},
			{"127.0.0.1:65536", "127.0.0.1:65536", "127.0.0.1:65536" + notHostPort},
			{listening + "\r", `"` + listening + `\r"`, `"` + listening + `\r"` + notHostPort},
			{"http://" + listening + "\r", `"http://` + listening + `\r"`, `"http://` + listening + `\r"` + notAURL},
			{"lab\x1b[2Jhost:7650", `"lab\x1b[2Jhost:7650"`, `"lab\x1b[2Jhost:7650"` + notHostPort},
		} {
			useAPIAt(t, c.address, sendToken)
			text, asJSON := runBothModes(t, showCmd)
			wantClientFailure(t, findings.OpTwinShow, text, asJSON, findings.Finding{Severity: findings.Rejection,
				Rule: findings.RuleAPIUnreachable, Object: c.shown,
				Message: "the API at " + c.shown + " cannot be reached: " + c.cause + "; fylgja serve runs on the lab host"})
			for _, out := range []string{text.stdout, text.stderr, asJSON.stdout, asJSON.stderr} {
				if strings.ContainsAny(out, "\r\x1b") {
					t.Errorf("%q: an output holds a control character of the address:\n%q", c.address, out)
				}
			}
		}
		if n := accepted.Load(); n != 0 {
			t.Errorf("the address took %d connections, want none", n)
		}
	})

	t.Run("a request over the server's bound", func(t *testing.T) {
		// Over the bound once base64 has taken its 3 bytes to 4, and no larger: the request is
		// marshalled whole in each mode.
		big := filepath.Join(t.TempDir(), "big.yaml")
		if err := os.WriteFile(big, bytes.Repeat([]byte("# x\n"), int(api.MaxRequestBytes*3/4/4)+16<<10), 0o644); err != nil {
			t.Fatal(err)
		}
		useAPIAt(t, strings.TrimPrefix(harness.http.URL, "http://"), harness.token)
		before := len(requestOutcomes(findings.OpPSPValidate))
		text, asJSON := runBothModes(t, func(opts *options) error { return runPSPValidate(opts, []string{big}) })
		wantClientFailure(t, findings.OpPSPValidate, text, asJSON, findings.Finding{Severity: findings.Rejection,
			Rule: findings.RuleAPITransferTooLarge, Object: findings.OpPSPValidate,
			Message: "the request is larger than this server's transfer bound of 33554432 bytes (32 MiB); nothing was read or filed"})
		if got := servedAfter(t, findings.OpPSPValidate, before); got != "too_large" {
			t.Errorf("the server logged %s, want too_large", got)
		}
	})

	t.Run("an answer frame over the client's bound", func(t *testing.T) {
		const bound = 1 << 20
		lowerFrameBound(t, bound)
		ctmPath := repoPath("testdata", "ctm", "three-node.json")
		address := stubAPI(t, func(w http.ResponseWriter, r *http.Request) {
			answerHeaders(w)
			a := &fakeAnswer{t: t, w: w}
			a.frame(filesFrameOf(t, bound+1))
			a.document(okDocument(findings.OpCompile), "")
		})
		out := filepath.Join(t.TempDir(), "bundle")
		text, asJSON := runBothModes(t, func(opts *options) error {
			return runCompile(opts, &compileFlags{ctmPath: ctmPath, out: out})
		})
		wantClientFailure(t, findings.OpCompile, text, asJSON, findings.Finding{Severity: findings.Rejection,
			Rule: findings.RuleAPITransferTooLarge, Object: findings.OpCompile,
			Message: "the API at " + address + " sent an answer frame larger than this client's bound of 1048576 bytes (1 MiB); nothing was written on this machine"})
		if _, err := os.Stat(out); !os.IsNotExist(err) {
			t.Errorf("--out %s exists after a frame over the bound: %v", out, err)
		}

		// A frame at the bound is read, and its bundle written.
		stubAPI(t, func(w http.ResponseWriter, r *http.Request) {
			answerHeaders(w)
			a := &fakeAnswer{t: t, w: w}
			a.frame(filesFrameOf(t, bound))
			a.document(okDocument(findings.OpCompile), "")
		})
		printedBy(t, func() {
			sentDocument(t, runCompile(&options{asJSON: true}, &compileFlags{ctmPath: ctmPath, out: out}))
		})
		if got := entriesOf(t, out); len(got) != 1 {
			t.Errorf("a frame at the bound wrote %v, want its one file", got)
		}
	})

	t.Run("a request the server cannot read", func(t *testing.T) {
		address := stubAPI(t, func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusBadRequest)
			_, _ = w.Write([]byte(`{"message":"the request is not one: twin.show takes no argument \"x\""}` + "\n"))
		})
		text, asJSON := runBothModes(t, showCmd)
		wantClientFailure(t, findings.OpTwinShow, text, asJSON, findings.Finding{Severity: findings.Rejection,
			Rule: findings.RuleOperationFailed, Object: findings.OpTwinShow,
			Message: "the API at " + address + ` could not read this request: the request is not one: twin.show takes no argument "x"`})
	})

	// 409 is a stream already open, which a client never asks for, since each of its streams is
	// a random identity of its own: it is the transport saying something else (contracts/cli.md,
	// "Anything else the transport says").
	t.Run("a stream already open", func(t *testing.T) {
		address := stubAPI(t, func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusConflict)
			_, _ = w.Write([]byte(`{"message":"an answer is already open under this stream; nothing was done"}` + "\n"))
		})
		useInterrupts(t)
		text, asJSON := runBothModes(t, createCmd)
		wantClientFailure(t, findings.OpTwinCreate, text, asJSON, findings.Finding{Severity: findings.Rejection,
			Rule: findings.RuleOperationFailed, Object: findings.OpTwinCreate,
			Message: "the API at " + address + " answered 409 Conflict"})
	})

	// A document frame whose document is not a findings document: the transport saying
	// something else, worded by the client (contracts/cli.md, "Anything else the transport
	// says").
	t.Run("a document this client cannot read", func(t *testing.T) {
		address := stubAPI(t, func(w http.ResponseWriter, r *http.Request) {
			answerHeaders(w)
			(&fakeAnswer{t: t, w: w}).frame(api.Frame{Document: json.RawMessage(`"not a document"`)})
		})
		text, asJSON := runBothModes(t, showCmd)
		wantClientFailure(t, findings.OpTwinShow, text, asJSON, findings.Finding{Severity: findings.Rejection,
			Rule: findings.RuleOperationFailed, Object: findings.OpTwinShow,
			Message: "the API at " + address + " sent a document this client cannot read: " +
				"json: cannot unmarshal string into Go value of type findings.Document"})
	})

	// A redirect is a status the API does not answer with, and is not followed: nothing, the
	// token included, is sent to its Location, and what answers there is not read as the API's
	// answer (contracts/cli.md, "Anything else the transport says"; D-042).
	t.Run("a redirect", func(t *testing.T) {
		var reached atomic.Int32
		target := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			reached.Add(1)
			answerHeaders(w)
			(&fakeAnswer{t: t, w: w}).frame(api.Frame{Document: json.RawMessage(`{}`)})
		}))
		t.Cleanup(target.Close)
		for _, c := range []struct {
			status int
			line   string
		}{
			{http.StatusFound, "302 Found"},
			{http.StatusTemporaryRedirect, "307 Temporary Redirect"},
		} {
			address := stubAPI(t, func(w http.ResponseWriter, r *http.Request) {
				http.Redirect(w, r, target.URL+"/elsewhere", c.status)
			})
			text, asJSON := runBothModes(t, showCmd)
			wantClientFailure(t, findings.OpTwinShow, text, asJSON, findings.Finding{Severity: findings.Rejection,
				Rule: findings.RuleOperationFailed, Object: findings.OpTwinShow,
				Message: "the API at " + address + " answered " + c.line})
		}
		if n := reached.Load(); n != 0 {
			t.Errorf("the redirect's target took %d requests, want none", n)
		}
	})

	t.Run("a status the API does not answer with", func(t *testing.T) {
		address := stubAPI(t, func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(http.StatusInternalServerError) })
		text, asJSON := runBothModes(t, showCmd)
		wantClientFailure(t, findings.OpTwinShow, text, asJSON, findings.Finding{Severity: findings.Rejection,
			Rule: findings.RuleOperationFailed, Object: findings.OpTwinShow,
			Message: "the API at " + address + " answered 500 Internal Server Error"})
	})
}

// lowerFrameBound makes the client's frame bound n for the test's length.
func lowerFrameBound(t *testing.T, n int64) {
	t.Helper()
	saved := newClient
	t.Cleanup(func() { newClient = saved })
	newClient = func(getenv func(string) (string, bool), b string) (*api.Client, error) {
		c, err := saved(getenv, b)
		if c != nil {
			c.MaxFrameBytes = n
		}
		return c, err
	}
}

// filesFrameOf is a files frame of one file, f, whose line is exactly n bytes long without its
// newline.
func filesFrameOf(t *testing.T, n int) api.Frame {
	t.Helper()
	empty, err := json.Marshal(api.Frame{Files: []api.File{{Path: "f", Data: []byte{}}}})
	if err != nil {
		t.Fatal(err)
	}
	// base64 takes 3 bytes to 4; fill to a whole number of groups, then pad the path.
	room := n - len(empty)
	data := make([]byte, room/4*3)
	f := api.Frame{Files: []api.File{{Path: "f" + strings.Repeat("f", room%4), Data: data}}}
	b, err := json.Marshal(f)
	if err != nil {
		t.Fatal(err)
	}
	if len(b) != n {
		t.Fatalf("the files frame is %d bytes, want %d", len(b), n)
	}
	return f
}

// A server of another build: one line on stderr, before any frame is printed, in both modes;
// it is not in the document, and the command ends as the document says.
func TestSendSaysTheServerIsAnotherBuild(t *testing.T) {
	doc := findings.NewDocument(findings.OpTwinShow, nil,
		findings.List{{Severity: findings.Warning, Rule: findings.RuleShowServiceUnreachable, Object: "localhost:7233", Message: "unreachable"}})
	var text strings.Builder
	_ = doc.WriteText(&text)
	var docJSON bytes.Buffer
	_ = doc.WriteJSON(&docJSON)
	address := stubAPI(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set(api.HeaderVersion, api.Version)
		w.Header().Set(api.HeaderBuild, "0.2.0")
		w.WriteHeader(http.StatusOK)
		a := &fakeAnswer{t: t, w: w}
		a.frame(api.Frame{Err: "a line for stderr\n"})
		a.document(doc, text.String())
	})
	line := fmt.Sprintf("fylgja: this client is build %s; the API at %s is build 0.2.0\n", build, address)
	for _, j := range []bool{false, true} {
		var code int
		stdout, stderr := printedBy(t, func() {
			opts := &options{asJSON: j}
			code = report(opts, nil, showCmd(opts))
		})
		if !strings.HasPrefix(stderr, line+"a line for stderr\n") || strings.Count(stderr, "this client is build") != 1 {
			t.Errorf("--json %v: stderr %q, want the build line once, before the first frame", j, stderr)
		}
		if code != findings.ExitOK {
			t.Errorf("--json %v: exit %d, want the document's 0", j, code)
		}
		if j && stdout != docJSON.String() {
			t.Errorf("--json: stdout\n%s\nis not the document\n%s", stdout, docJSON.String())
		}
	}

	// The same build says nothing.
	stubAPI(t, func(w http.ResponseWriter, r *http.Request) {
		answerHeaders(w)
		(&fakeAnswer{t: t, w: w}).document(doc, "")
	})
	_, stderr := printedBy(t, func() { _ = showCmd(&options{asJSON: true}) })
	if stderr != "" {
		t.Errorf("a server of the client's own build: stderr %q, want nothing", stderr)
	}
}

// Each identifier of the client's tells its case by itself: the four are distinct from one
// another and from every M1–M12 rule.
func TestTheClientsIdentifiersAreTheirOwn(t *testing.T) {
	src, err := os.ReadFile(repoPath("internal", "findings", "finding.go"))
	if err != nil {
		t.Fatal(err)
	}
	seen := map[string]int{}
	for _, m := range regexp.MustCompile(`(?m)^\s*Rule\w+\s*=\s*"([^"]+)"`).FindAllSubmatch(src, -1) {
		seen[string(m[1])]++
	}
	for _, rule := range []string{findings.RuleAPIUnreachable, findings.RuleAPITokenRefused,
		findings.RuleAPIVersionUnknown, findings.RuleAPITransferTooLarge} {
		if seen[rule] != 1 {
			t.Errorf("%s is declared %d times among the rules, want once", rule, seen[rule])
		}
	}
	if len(seen) < 100 {
		t.Errorf("read %d rules from finding.go; the pattern no longer finds them", len(seen))
	}
}
