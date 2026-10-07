package api

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
	"unicode"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

// The token the client tests send, which must appear in nothing a client returns.
const clientToken = "the-client-token-of-this-test-91c4"

// env is a client's environment: the API's two variables, and what was asked of it.
type env struct {
	mu    sync.Mutex
	vars  map[string]string
	asked []string
}

func (e *env) getenv(name string) (string, bool) {
	e.mu.Lock()
	defer e.mu.Unlock()
	e.asked = append(e.asked, name)
	v, ok := e.vars[name]
	return v, ok
}

func envFor(address string) *env {
	return &env{vars: map[string]string{EnvAddress: address, EnvToken: clientToken}}
}

func clientFor(t *testing.T, address string) *Client {
	t.Helper()
	c, err := NewClient(envFor(address).getenv, "0.0.0-client")
	if err != nil {
		t.Fatal(err)
	}
	return c
}

// served is a server answering with handler, its address as a client takes it.
func served(t *testing.T, handler http.HandlerFunc) string {
	t.Helper()
	srv := httptest.NewServer(handler)
	t.Cleanup(srv.Close)
	return strings.TrimPrefix(srv.URL, "http://")
}

// apiAnswer starts an answer as the server does: 200, NDJSON, the version and the build.
func apiAnswer(w http.ResponseWriter) {
	w.Header().Set(HeaderVersion, Version)
	w.Header().Set(HeaderBuild, "0.0.0-server")
	w.Header().Set("Content-Type", "application/x-ndjson")
	w.WriteHeader(http.StatusOK)
}

func frameLine(t *testing.T, f Frame) string {
	t.Helper()
	b, err := json.Marshal(f)
	if err != nil {
		t.Fatal(err)
	}
	return string(b) + "\n"
}

func documentFrame(t *testing.T) Frame {
	t.Helper()
	return Frame{Document: documentBytes(t, findings.NewDocument(findings.OpTwinShow, nil, nil))}
}

// noToken fails when an error says or holds the token.
func noToken(t *testing.T, err error) {
	t.Helper()
	if err == nil {
		return
	}
	for _, s := range []string{err.Error(), fmt.Sprintf("%+v", err), fmt.Sprintf("%#v", err)} {
		if strings.Contains(s, clientToken) {
			t.Errorf("an error carries the token: %s", s)
		}
	}
}

// Each status the API's transport answers with is its own error, carrying what the client's
// sentence needs, and none carries the token.
func TestEachFaultIsItsOwnError(t *testing.T) {
	for _, c := range []struct {
		name    string
		handler http.HandlerFunc
		check   func(t *testing.T, address string, err error)
	}{
		{"401", func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("WWW-Authenticate", "Bearer")
			w.WriteHeader(http.StatusUnauthorized)
		}, func(t *testing.T, address string, err error) {
			var e *TokenRefused
			if !errors.As(err, &e) || e.Address != address {
				t.Errorf("%T %v", err, err)
			}
		}},
		{"404 naming versions", func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set(HeaderVersions, "2,3")
			w.WriteHeader(http.StatusNotFound)
		}, func(t *testing.T, address string, err error) {
			var e *VersionUnknown
			if !errors.As(err, &e) || e.Address != address || e.Served != "2,3" {
				t.Errorf("%T %v", err, err)
			}
			if got := err.Error(); got != "the API at "+address+" serves version 2,3; this client speaks version 1" {
				t.Errorf("message %q", got)
			}
		}},
		// The server that answers is version 1 and has no such path: the address leads under a
		// prefix the server does not have. That is the 404 as it is, not a version this client
		// does not speak.
		{"404 naming this client's version", func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set(HeaderVersions, Version)
			w.WriteHeader(http.StatusNotFound)
		}, func(t *testing.T, address string, err error) {
			var e *Unexpected
			if !errors.As(err, &e) || e.Status != "404 Not Found" {
				t.Errorf("%T %v", err, err)
			}
			if got := err.Error(); got != "the API at "+address+" answered 404 Not Found" {
				t.Errorf("message %q", got)
			}
		}},
		{"404 naming versions, this client's among them", func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set(HeaderVersions, "2, "+Version)
			w.WriteHeader(http.StatusNotFound)
		}, func(t *testing.T, address string, err error) {
			var e *Unexpected
			if !errors.As(err, &e) || e.Status != "404 Not Found" {
				t.Errorf("%T %v", err, err)
			}
		}},
		{"404 naming none", func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(http.StatusNotFound)
		}, func(t *testing.T, address string, err error) {
			var e *Unexpected
			if !errors.As(err, &e) || e.Status != "404 Not Found" {
				t.Errorf("%T %v", err, err)
			}
		}},
		{"413", func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(http.StatusRequestEntityTooLarge)
			_ = json.NewEncoder(w).Encode(Problem{Message: "the server's sentence", LimitBytes: MaxRequestBytes})
		}, func(t *testing.T, address string, err error) {
			var e *TooLarge
			if !errors.As(err, &e) || e.Message != "the server's sentence" {
				t.Errorf("%T %v", err, err)
			}
		}},
		{"400", func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(http.StatusBadRequest)
			_ = json.NewEncoder(w).Encode(Problem{Message: "the request is not one: json: unknown field"})
		}, func(t *testing.T, address string, err error) {
			var e *Unreadable
			if !errors.As(err, &e) || e.Address != address || e.Message != "the request is not one: json: unknown field" {
				t.Errorf("%T %v", err, err)
			}
		}},
		{"500", func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(http.StatusInternalServerError)
		}, func(t *testing.T, address string, err error) {
			var e *Unexpected
			if !errors.As(err, &e) || e.Address != address || e.Status != "500 Internal Server Error" {
				t.Errorf("%T %v", err, err)
			}
			if got := err.Error(); got != "the API at "+address+" answered 500 Internal Server Error" {
				t.Errorf("message %q", got)
			}
		}},
		{"200 that is not the API's", func(w http.ResponseWriter, r *http.Request) {
			_, _ = io.WriteString(w, "<html>a web server</html>\n")
		}, func(t *testing.T, address string, err error) {
			var e *Unreachable
			if !errors.As(err, &e) || e.Address != address || !strings.Contains(err.Error(), "is not the API") {
				t.Errorf("%T %v", err, err)
			}
		}},
	} {
		t.Run(c.name, func(t *testing.T) {
			address := served(t, c.handler)
			_, err := clientFor(t, address).Do(context.Background(), findings.OpTwinShow, Request{}, "", nil)
			c.check(t, address, err)
			noToken(t, err)
		})
	}
}

// A redirect is not followed, from the command's request or from an interrupt: the API never
// redirects, so a 3xx is something else at the address, and it is *Unexpected, naming the
// status. Nothing is sent to its Location, where net/http would have sent the request again,
// its body with a 307 and the token with either (contracts/cli.md, "Anything else the
// transport says"; D-042).
func TestARedirectIsNotFollowed(t *testing.T) {
	var reached atomic.Int32
	target := served(t, func(w http.ResponseWriter, r *http.Request) {
		reached.Add(1)
		if r.Header.Get("Authorization") != "" {
			t.Errorf("the redirect's target was sent the token on %s %s", r.Method, r.URL.Path)
		}
		apiAnswer(w)
		_, _ = io.WriteString(w, frameLine(t, documentFrame(t)))
	})
	for _, c := range []struct {
		status int
		line   string
	}{
		{http.StatusFound, "302 Found"},
		{http.StatusTemporaryRedirect, "307 Temporary Redirect"},
	} {
		t.Run(c.line, func(t *testing.T) {
			address := served(t, func(w http.ResponseWriter, r *http.Request) {
				http.Redirect(w, r, "http://"+target+"/elsewhere", c.status)
			})
			client := clientFor(t, address)
			_, err := client.Do(context.Background(), findings.OpTwinShow, Request{}, "", nil)
			var e *Unexpected
			if !errors.As(err, &e) || e.Address != address || e.Status != c.line {
				t.Errorf("request: %T %v, want *Unexpected answering %s", err, err, c.line)
			} else if got, want := err.Error(), "the API at "+address+" answered "+c.line; got != want {
				t.Errorf("request: %q, want %q", got, want)
			}
			noToken(t, err)
			err = client.Interrupt(context.Background(), "open")
			if !errors.As(err, &e) || e.Address != address || e.Status != c.line {
				t.Errorf("interrupt: %T %v, want *Unexpected answering %s", err, err, c.line)
			}
			noToken(t, err)
		})
	}
	if n := reached.Load(); n != 0 {
		t.Errorf("the redirect's target took %d requests, want none", n)
	}
}

// Nothing answering is Unreachable, its cause the network's sentence without the request's
// URL.
func TestNothingAnsweringIsUnreachable(t *testing.T) {
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	address := l.Addr().String()
	_ = l.Close()
	_, err = clientFor(t, address).Do(context.Background(), findings.OpTwinShow, Request{}, "", nil)
	var e *Unreachable
	if !errors.As(err, &e) || e.Address != address {
		t.Fatalf("%T %v", err, err)
	}
	want := "dial tcp " + address + ": connect: connection refused"
	if got := e.Cause.Error(); got != want {
		t.Errorf("cause %q, want %q", got, want)
	}
	if strings.Contains(err.Error(), "http://") || strings.Contains(err.Error(), "/v1/") {
		t.Errorf("the error names the request's URL: %v", err)
	}
	noToken(t, err)
}

// What the client sends: the token as a bearer credential, the request as JSON, the stream
// when it is given, Expect: 100-continue only with files; and the build reaches onHeaders
// before the first frame is read.
func TestTheRequestCarriesWhatTheServerReads(t *testing.T) {
	type seen struct {
		auth, stream, expect, contentType, path string
		req                                     Request
	}
	got := make(chan seen, 1)
	address := served(t, func(w http.ResponseWriter, r *http.Request) {
		req, err := DecodeRequest(r.Body)
		if err != nil {
			t.Errorf("the server could not read the request: %v", err)
		}
		got <- seen{r.Header.Get("Authorization"), r.Header.Get(HeaderStream), r.Header.Get("Expect"),
			r.Header.Get("Content-Type"), r.URL.Path, req}
		apiAnswer(w)
		_, _ = io.WriteString(w, frameLine(t, Frame{Out: "a line\n"}))
		_, _ = io.WriteString(w, frameLine(t, documentFrame(t)))
	})
	c := clientFor(t, address)

	var build string
	ans, err := c.Do(context.Background(), findings.OpTwinCreate,
		Request{Render: RenderText, Args: map[string]json.RawMessage{"interval": json.RawMessage(`""`)}},
		"00112233445566778899aabbccddeeff", func(b string) { build = b })
	if err != nil {
		t.Fatal(err)
	}
	if build != "0.0.0-server" {
		t.Errorf("onHeaders was given %q before the first frame", build)
	}
	s := <-got
	if s.auth != "Bearer "+clientToken {
		t.Errorf("Authorization %q", strings.ReplaceAll(s.auth, clientToken, "<token>"))
	}
	if s.path != "/v1/twin/create" || s.contentType != "application/json" {
		t.Errorf("path %q, Content-Type %q", s.path, s.contentType)
	}
	if s.stream != "00112233445566778899aabbccddeeff" || s.expect != "" {
		t.Errorf("stream %q, Expect %q", s.stream, s.expect)
	}
	if s.req.Render != RenderText || string(s.req.Args["interval"]) != `""` || len(s.req.Args) != 1 {
		t.Errorf("request %+v", s.req)
	}
	for _, want := range []string{KindOut, KindDocument} {
		f, err := ans.Next()
		if err != nil || f.Kind() != want {
			t.Fatalf("frame %+v (%v), want %s", f, err, want)
		}
	}
	if _, err := ans.Next(); !errors.Is(err, io.EOF) {
		t.Errorf("after the document: %v, want io.EOF", err)
	}

	// With files, and no stream.
	ans, err = c.Do(context.Background(), findings.OpTwinProvision,
		Request{Files: []File{{Path: "manifest.json", Data: []byte("{}")}}}, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	_ = ans.Close()
	s = <-got
	if s.expect != "100-continue" || s.stream != "" || len(s.req.Files) != 1 || string(s.req.Files[0].Data) != "{}" {
		t.Errorf("Expect %q, stream %q, files %+v", s.expect, s.stream, s.req.Files)
	}
}

// An answer that ends without its document is Cut: cleanly after a frame, and with the
// connection closed under it, after the headers, a start or a run.
func TestAnAnswerEndedBeforeItsDocumentIsCut(t *testing.T) {
	for _, c := range []struct {
		name   string
		frames []Frame
		hijack bool
	}{
		{"a clean end after a frame", []Frame{{Out: "a line\n"}}, false},
		{"closed after the headers", nil, true},
		{"closed after start", []Frame{{Start: &RunRef{WorkflowID: "fylgja-provision"}}}, true},
		{"closed after run", []Frame{{Start: &RunRef{WorkflowID: "fylgja-step"}}, {Run: &RunRef{WorkflowID: "fylgja-step", RunID: "01a1"}}}, true},
		{"a partial line", []Frame{{Out: "a line\n"}}, true},
	} {
		t.Run(c.name, func(t *testing.T) {
			address := served(t, func(w http.ResponseWriter, r *http.Request) {
				apiAnswer(w)
				for _, f := range c.frames {
					_, _ = io.WriteString(w, frameLine(t, f))
				}
				if c.name == "a partial line" {
					_, _ = io.WriteString(w, `{"out":"half`)
				}
				w.(http.Flusher).Flush()
				if c.hijack {
					conn, _, err := http.NewResponseController(w).Hijack()
					if err != nil {
						t.Error(err)
						return
					}
					_ = conn.Close()
				}
			})
			ans, err := clientFor(t, address).Do(context.Background(), findings.OpTwinCreate, Request{}, "", nil)
			if err != nil {
				t.Fatal(err)
			}
			for range c.frames {
				if _, err := ans.Next(); err != nil {
					t.Fatalf("a frame before the cut: %v", err)
				}
			}
			_, err = ans.Next()
			var cut *Cut
			if !errors.As(err, &cut) || cut.Address != address {
				t.Fatalf("%T %v, want *Cut", err, err)
			}
			if !strings.HasPrefix(err.Error(), "the API at "+address+" stopped answering before the command ended: ") {
				t.Errorf("message %q", err)
			}
			noToken(t, err)
			if _, again := ans.Next(); again == nil {
				t.Error("a cut answer gave another frame")
			}
		})
	}
	// A line that is not a frame is a cut too.
	address := served(t, func(w http.ResponseWriter, r *http.Request) {
		apiAnswer(w)
		_, _ = io.WriteString(w, "not a frame\n")
	})
	ans, err := clientFor(t, address).Do(context.Background(), findings.OpTwinShow, Request{}, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	var cut *Cut
	if _, err := ans.Next(); !errors.As(err, &cut) || !strings.Contains(err.Error(), "is not a frame") {
		t.Errorf("%T %v", err, err)
	}
}

// A frame at the client's bound is read; one byte over it is FrameTooLarge naming the
// bound, and the rest of the answer is not read.
func TestAFrameOverTheClientsBoundIsRefused(t *testing.T) {
	const bound = 256
	at := Frame{Out: strings.Repeat("x", bound-len(`{"out":""}`))}
	if n := len(frameLine(t, at)) - 1; n != bound {
		t.Fatalf("the frame at the bound is %d bytes", n)
	}
	over := Frame{Out: at.Out + "y"}
	var rest atomic.Bool
	address := served(t, func(w http.ResponseWriter, r *http.Request) {
		apiAnswer(w)
		_, _ = io.WriteString(w, frameLine(t, at))
		_, _ = io.WriteString(w, frameLine(t, over))
		if _, err := io.WriteString(w, frameLine(t, documentFrame(t))); err == nil {
			rest.Store(true)
		}
	})
	c := clientFor(t, address)
	if c.MaxFrameBytes != MaxFrameBytes {
		t.Errorf("a new client's bound is %d", c.MaxFrameBytes)
	}
	c.MaxFrameBytes = bound
	ans, err := c.Do(context.Background(), findings.OpCompile, Request{}, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	if f, err := ans.Next(); err != nil || f.Out != at.Out {
		t.Fatalf("the frame at the bound: %v", err)
	}
	_, err = ans.Next()
	var e *FrameTooLarge
	if !errors.As(err, &e) || e.LimitBytes != bound || e.Address != address {
		t.Fatalf("%T %v, want *FrameTooLarge", err, err)
	}
	if _, err := ans.Next(); err == nil {
		t.Error("the answer was read on past a frame over the bound")
	}
	noToken(t, err)
}

// A frame of a kind this build does not know is returned with no kind, for the caller to
// pass over.
func TestAFrameOfAnUnknownKindIsPassedOn(t *testing.T) {
	address := served(t, func(w http.ResponseWriter, r *http.Request) {
		apiAnswer(w)
		_, _ = io.WriteString(w, `{"progress":{"pct":50}}`+"\n")
		_, _ = io.WriteString(w, frameLine(t, documentFrame(t)))
	})
	ans, err := clientFor(t, address).Do(context.Background(), findings.OpTwinShow, Request{}, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	if f, err := ans.Next(); err != nil || f.Kind() != "" {
		t.Errorf("%+v %v", f, err)
	}
	if f, err := ans.Next(); err != nil || f.Kind() != KindDocument {
		t.Errorf("%+v %v", f, err)
	}
}

// An interrupt delivered is nil; one for an answer that has ended is ErrStreamEnded; a
// refused token is TokenRefused.
func TestInterrupt(t *testing.T) {
	var paths []string
	var mu sync.Mutex
	address := served(t, func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		paths = append(paths, r.URL.Path)
		mu.Unlock()
		switch {
		case r.Header.Get("Authorization") != "Bearer "+clientToken:
			w.WriteHeader(http.StatusUnauthorized)
		case strings.Contains(r.URL.Path, "/open/"):
			w.WriteHeader(http.StatusNoContent)
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	})
	c := clientFor(t, address)
	if err := c.Interrupt(context.Background(), "open"); err != nil {
		t.Errorf("delivered: %v", err)
	}
	if err := c.Interrupt(context.Background(), "ended"); !errors.Is(err, ErrStreamEnded) {
		t.Errorf("ended: %v", err)
	}
	if paths[0] != "/v1/streams/open/interrupt" {
		t.Errorf("path %q", paths[0])
	}
	e := envFor(address)
	e.vars[EnvToken] = "another"
	other, err := NewClient(e.getenv, "")
	if err != nil {
		t.Fatal(err)
	}
	var refused *TokenRefused
	if err := other.Interrupt(context.Background(), "open"); !errors.As(err, &refused) {
		t.Errorf("refused: %T %v", err, err)
	}
}

// The client's environment: the API's two variables and no other; an unset or empty token
// is ErrTokenUnset and dials nothing; the address as host:port, as a URL, or the default.
func TestTheClientsEnvironment(t *testing.T) {
	var dialled atomic.Int32
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = l.Close() }()
	go func() {
		for {
			conn, err := l.Accept()
			if err != nil {
				return
			}
			dialled.Add(1)
			_ = conn.Close()
		}
	}()
	for _, token := range []*string{nil, new(string)} {
		e := &env{vars: map[string]string{EnvAddress: l.Addr().String()}}
		if token != nil {
			e.vars[EnvToken] = *token
		}
		if _, err := NewClient(e.getenv, ""); !errors.Is(err, ErrTokenUnset) {
			t.Errorf("token %v: %v, want ErrTokenUnset", token, err)
		}
	}
	if n := dialled.Load(); n != 0 {
		t.Errorf("a client with no token dialled %d times", n)
	}

	for _, c := range []struct{ address, url string }{
		{"", "http://127.0.0.1:7650/v1/twin/show"},
		{"127.0.0.1:7651", "http://127.0.0.1:7651/v1/twin/show"},
		{"lab-host:7650", "http://lab-host:7650/v1/twin/show"},
		{"http://127.0.0.1:7651", "http://127.0.0.1:7651/v1/twin/show"},
		{"https://proxy.example/fylgja/", "https://proxy.example/fylgja/v1/twin/show"},
	} {
		e := &env{vars: map[string]string{EnvToken: clientToken}}
		if c.address != "" {
			e.vars[EnvAddress] = c.address
		}
		client, err := NewClient(e.getenv, "")
		if err != nil {
			t.Errorf("%q: %v", c.address, err)
			continue
		}
		if got := client.url(Path(findings.OpTwinShow)); got != c.url {
			t.Errorf("%q: %s, want %s", c.address, got, c.url)
		}
		want := c.address
		if want == "" {
			want = DefaultAddress
		}
		if client.Address() != want {
			t.Errorf("%q: Address %q", c.address, client.Address())
		}
		for _, name := range e.asked {
			if name != EnvAddress && name != EnvToken {
				t.Errorf("the client asked for %s", name)
			}
		}
		for _, s := range []string{fmt.Sprintf("%+v", client), fmt.Sprintf("%#v", client)} {
			if strings.Contains(s, clientToken) {
				t.Errorf("a client prints its token: %s", s)
			}
		}
	}
	// A value that is not an address is refused whole, before anything is dialled: a host:port
	// with no port, which would dial port 80, or with a path, which would fail only once
	// dialled; and a URL that names a user or password, which no sentence repeats.
	for _, c := range []struct{ bad, shown, cause string }{
		{"no-port", "no-port", "no-port is not host:port: " + EnvAddress + " takes host:port or an http:// or https:// URL"},
		{"http://", "http://", "http:// is not a URL of a server: " + EnvAddress + " takes host:port or an http:// or https:// URL"},
		{"ftp://host:1", "ftp://host:1", "ftp://host:1 is not host:port: " + EnvAddress + " takes host:port or an http:// or https:// URL"},
		{"127.0.0.1:", "127.0.0.1:", "127.0.0.1: is not host:port: " + EnvAddress + " takes host:port or an http:// or https:// URL"},
		{"host:7650/x", "host:7650/x", "host:7650/x is not host:port: " + EnvAddress + " takes host:port or an http:// or https:// URL"},
		{"https://user:pw-91c4@host/", "https://host/", "https://host/ names a user or password, which " + EnvAddress +
			" never carries: it takes host:port or an http:// or https:// URL without one"},
		{"http://user:pw-91c4@host:bad/", "http://host:bad/", "http://host:bad/ names a user or password, which " + EnvAddress +
			" never carries: it takes host:port or an http:// or https:// URL without one"},
		{"user:pw-91c4@host:7650", "host:7650", "host:7650 names a user or password, which " + EnvAddress +
			" never carries: it takes host:port or an http:// or https:// URL without one"},
	} {
		e := &env{vars: map[string]string{EnvToken: clientToken, EnvAddress: c.bad}}
		var u *Unreachable
		_, err := NewClient(e.getenv, "")
		if !errors.As(err, &u) || u.Address != c.shown || u.Cause.Error() != c.cause {
			t.Errorf("%q: %T %v\nwant *Unreachable at %s: %s", c.bad, err, err, c.shown, c.cause)
			continue
		}
		for _, s := range []string{err.Error(), fmt.Sprintf("%+v", err), fmt.Sprintf("%#v", err)} {
			if strings.Contains(s, "pw-91c4") || strings.Contains(s, "user:") {
				t.Errorf("%q: the refusal names the user or password: %s", c.bad, s)
			}
		}
	}
	if n := dialled.Load(); n != 0 {
		t.Errorf("a refused address dialled %d times", n)
	}

	// A port that is not a decimal port number from 1 to 65535, in either form, and any control
	// character are refused the same way, before anything is dialled: net.SplitHostPort checks
	// nothing of the port, and the URL parser had refused the rest only once a request was
	// built, reported as the server unreachable. An address holding a control character is
	// named as Go quotes a string, so that none reaches a sentence.
	listening := l.Addr().String()
	notHostPort := func(shown string) string {
		return shown + " is not host:port: " + EnvAddress + " takes host:port or an http:// or https:// URL"
	}
	notAURL := func(shown string) string {
		return shown + " is not a URL of a server: " + EnvAddress + " takes host:port or an http:// or https:// URL"
	}
	for _, c := range []struct{ bad, shown, cause string }{
		{listening + "x", listening + "x", notHostPort(listening + "x")},
		{"127.0.0.1:http", "127.0.0.1:http", notHostPort("127.0.0.1:http")},
		{"127.0.0.1:0", "127.0.0.1:0", notHostPort("127.0.0.1:0")},
		{"127.0.0.1:65536", "127.0.0.1:65536", notHostPort("127.0.0.1:65536")},
		{"127.0.0.1:+7650", "127.0.0.1:+7650", notHostPort("127.0.0.1:+7650")},
		{"127.0.0.1:99999999999999999999", "127.0.0.1:99999999999999999999", notHostPort("127.0.0.1:99999999999999999999")},
		{"http://127.0.0.1:65536", "http://127.0.0.1:65536", notAURL("http://127.0.0.1:65536")},
		{"https://lab-host:0/", "https://lab-host:0/", notAURL("https://lab-host:0/")},
		{listening + "\r", `"` + listening + `\r"`, notHostPort(`"` + listening + `\r"`)},
		{"http://" + listening + "\r", `"http://` + listening + `\r"`, notAURL(`"http://` + listening + `\r"`)},
		{"lab\x1bhost:7650", `"lab\x1bhost:7650"`, notHostPort(`"lab\x1bhost:7650"`)},
		{"lab\u009bhost:7650", `"lab\u009bhost:7650"`, notHostPort(`"lab\u009bhost:7650"`)},
		{"https://lab-host/fylgja\n", `"https://lab-host/fylgja\n"`, notAURL(`"https://lab-host/fylgja\n"`)},
		{"https://user:pw-91c4@lab\thost/", `"https://lab\thost/"`, `"https://lab\thost/" names a user or password, which ` + EnvAddress +
			" never carries: it takes host:port or an http:// or https:// URL without one"},
	} {
		e := &env{vars: map[string]string{EnvToken: clientToken, EnvAddress: c.bad}}
		var u *Unreachable
		_, err := NewClient(e.getenv, "")
		if !errors.As(err, &u) || u.Address != c.shown || u.Cause.Error() != c.cause {
			t.Errorf("%q: %T %v\nwant *Unreachable at %s: %s", c.bad, err, err, c.shown, c.cause)
			continue
		}
		if i := strings.IndexFunc(u.Address+err.Error(), unicode.IsControl); i >= 0 {
			t.Errorf("%q: the refusal holds a control character: %q", c.bad, err)
		}
	}
	if n := dialled.Load(); n != 0 {
		t.Errorf("a refused address dialled %d times", n)
	}
	// A port number written in digits alone is taken, leading zeros and the bounds included.
	for _, address := range []string{"127.0.0.1:1", "127.0.0.1:65535", "127.0.0.1:07650", "[::1]:7650", "http://[::1]:7650", "https://lab-host:443/"} {
		e := &env{vars: map[string]string{EnvToken: clientToken, EnvAddress: address}}
		if _, err := NewClient(e.getenv, ""); err != nil {
			t.Errorf("%q: %v, want a client", address, err)
		}
	}
}

// A token holding a byte no request header can carry is refused before anything is sent, as
// an unset one is, rather than reported as the server unreachable once net/http refuses the
// header. The rule is net/http's own, byte for byte: each of the 256
// is refused by NewClient exactly when the transport refuses it, and the refusal carries no
// part of the token.
func TestATokenNoHeaderCanCarryIsRefused(t *testing.T) {
	var dialled atomic.Int32
	transport := &http.Transport{DialContext: func(context.Context, string, string) (net.Conn, error) {
		dialled.Add(1)
		return nil, errors.New("dialled")
	}}
	for b := 0; b < 256; b++ {
		token := clientToken + string([]byte{byte(b)}) + "-tail"
		req, err := http.NewRequest(http.MethodPost, "http://127.0.0.1:1/v1/twin/show", nil)
		if err != nil {
			t.Fatal(err)
		}
		req.Header.Set("Authorization", "Bearer "+token)
		resp, err := transport.RoundTrip(req)
		if resp != nil {
			_ = resp.Body.Close()
		}
		netHTTPRefuses := err != nil && strings.Contains(err.Error(), "invalid header field value")

		e := &env{vars: map[string]string{EnvToken: token}}
		_, err = NewClient(e.getenv, "")
		if refused := errors.Is(err, ErrTokenUnsendable); refused != netHTTPRefuses {
			t.Errorf("byte %#02x: NewClient %v; net/http refuses the header: %v", b, err, netHTTPRefuses)
		}
		if err != nil && (strings.Contains(err.Error(), clientToken) || strings.Contains(fmt.Sprintf("%#v", err), clientToken)) {
			t.Errorf("byte %#02x: the refusal carries the token: %v", b, err)
		}
	}
	if n := dialled.Load(); n != 256-32 {
		t.Errorf("net/http sent %d of the 256 headers, want the 224 that are not a control byte, or are a tab", n)
	}
	// The carriage return a local/.env saved with CRLF line endings leaves is refused before
	// the address is read; a tab inside the token is a header's own whitespace, so the
	// address is read next. A trailing tab has its own case below.
	for _, c := range []struct {
		token   string
		refused bool
	}{
		{clientToken + "\r", true},
		{clientToken + "\n", true},
		{"\x00", true},
		{clientToken[:4] + "\t" + clientToken[4:], false},
	} {
		e := &env{vars: map[string]string{EnvToken: c.token, EnvAddress: "not an address"}}
		_, err := NewClient(e.getenv, "")
		var u *Unreachable
		if c.refused && !errors.Is(err, ErrTokenUnsendable) || !c.refused && !errors.As(err, &u) {
			t.Errorf("%q: %v; refused as unsendable: %v", c.token, err, c.refused)
		}
	}
	if ErrTokenUnsendable.Error() != EnvToken+" holds a character a request header cannot carry" {
		t.Errorf("ErrTokenUnsendable says %q", ErrTokenUnsendable)
	}
}

// A token that ends in a space or a tab is refused before anything is sent, under its own
// sentence, rather than sent and refused by a server holding the same token: a server's
// reader trims a header value's trailing whitespace before the token is compared, and the
// client would report a token that differs. A leading blank, and one
// inside the token, reach a server whole, and are not refused. The refusal carries no part of
// the token.
func TestATokenEndingInABlankIsRefused(t *testing.T) {
	// What a net/http server reads of each Authorization header net/http sends.
	got := make(chan string, 1)
	srv := httptest.NewServer(http.HandlerFunc(func(_ http.ResponseWriter, r *http.Request) {
		got <- r.Header.Get("Authorization")
	}))
	defer srv.Close()
	for _, c := range []struct{ token, read string }{
		{clientToken + " ", clientToken},
		{clientToken + "\t", clientToken},
		{clientToken + " \t ", clientToken},
		{" " + clientToken, " " + clientToken},
		{clientToken[:4] + " \t" + clientToken[4:], clientToken[:4] + " \t" + clientToken[4:]},
	} {
		req, err := http.NewRequest(http.MethodPost, srv.URL, nil)
		if err != nil {
			t.Fatal(err)
		}
		req.Header.Set("Authorization", "Bearer "+c.token)
		resp, err := srv.Client().Do(req)
		if err != nil {
			t.Fatalf("%q: %v", c.token, err)
		}
		_ = resp.Body.Close()
		if read := <-got; read != "Bearer "+c.read {
			t.Errorf("%q: the server read %q, want %q", c.token, read, "Bearer "+c.read)
		}
	}

	var dialled atomic.Int32
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = l.Close() }()
	go func() {
		for {
			conn, err := l.Accept()
			if err != nil {
				return
			}
			dialled.Add(1)
			_ = conn.Close()
		}
	}()
	for _, token := range []string{clientToken + " ", clientToken + "\t", clientToken + " \t ", " ", "\t"} {
		e := &env{vars: map[string]string{EnvToken: token, EnvAddress: l.Addr().String()}}
		_, err := NewClient(e.getenv, "")
		if !errors.Is(err, ErrTokenTrailingBlank) {
			t.Errorf("%q: %v, want ErrTokenTrailingBlank", token, err)
		}
		if err != nil && (strings.Contains(err.Error(), clientToken) || strings.Contains(fmt.Sprintf("%#v", err), clientToken)) {
			t.Errorf("%q: the refusal carries the token: %v", token, err)
		}
	}
	if n := dialled.Load(); n != 0 {
		t.Errorf("a refused token dialled %d times", n)
	}
	for _, token := range []string{" " + clientToken, "\t" + clientToken, clientToken[:4] + " \t" + clientToken[4:]} {
		e := &env{vars: map[string]string{EnvToken: token, EnvAddress: l.Addr().String()}}
		if _, err := NewClient(e.getenv, ""); err != nil {
			t.Errorf("%q: %v, want a client", token, err)
		}
	}
	if ErrTokenTrailingBlank.Error() != EnvToken+" ends in a space or a tab, which a request header cannot carry" {
		t.Errorf("ErrTokenTrailingBlank says %q", ErrTokenTrailingBlank)
	}
}

// The transport's bounds are named mechanism constants, their values those M13 shipped
// unnamed, and the client's transport waits for 100 Continue by its own (Constitution
// II).
func TestTheTransportsBoundsAreNamed(t *testing.T) {
	if ExpectContinueTimeout != time.Second || MaxProblemBytes != 64<<10 || StreamBytes != 16 || MaxStreamLength != 128 {
		t.Errorf("bounds %v, %d, %d, %d; want 1s, 64 KiB, 16 and 128", ExpectContinueTimeout, MaxProblemBytes, StreamBytes, MaxStreamLength)
	}
	// A stream identity in hex fits the bound the server holds it to.
	if 2*StreamBytes > MaxStreamLength {
		t.Errorf("a stream identity is %d characters, over the server's %d", 2*StreamBytes, MaxStreamLength)
	}
	c := clientFor(t, "127.0.0.1:1")
	if tr, ok := c.http.Transport.(*http.Transport); !ok || tr.ExpectContinueTimeout != ExpectContinueTimeout {
		t.Errorf("the client's transport is %#v", c.http.Transport)
	}
}
