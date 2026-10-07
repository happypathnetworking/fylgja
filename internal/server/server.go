// Package server is the API's server: the handlers of fylgja serve, the role that runs on
// the lab host beside the worker and is the only way a user-facing client reaches the core
// (D-040, D-041). M12's command logic lives here from the move: each of the twelve
// operations is the command it is named after, reading and writing a per-request console
// where the command read flags and wrote to stdout and stderr.
//
// The server keeps nothing between two requests (D-014). Packages are loaded, the
// workflow service dialled and Infrahub read by the request that needs them. While a run's
// request is open the server holds the channel that request's interrupts arrive on, and
// nothing once it ends (streams.go).
package server

import (
	"context"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"net/url"
	"os"
	"path"
	"strings"
	"time"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/provision"
	"github.com/happypathnetworking/fylgja/internal/verify"
)

// Server is fylgja serve's handlers and what they are given at start.
// Each field but Build and Log replaces a package variable M12's command tests swapped, so
// a test sets the field for its length where it set the variable.
type Server struct {
	// Dial connects to the workflow service, its warnings logged to log, the request's own
	// logger (dialService at M12). Closed by the request that dialled it.
	Dial func(ctx context.Context, log *slog.Logger) (provision.Service, error)
	// Runner runs containerlab and docker for the requests that read the host in this
	// process: a dry run's host check, twin show and twin step's plan (dryRunRunner).
	Runner lab.Runner
	// Reader reads a booted node for twin verify (verifyReader). A lab.GNMIReader with no
	// logger of its own logs to the request's.
	Reader verify.Reader
	// Sleep and Now are verify's pause between two reads and its clock; nil is verify's
	// own timer and time.Now (verifySleep, verifyNow).
	Sleep func(ctx context.Context, d time.Duration) error
	Now   func() time.Time
	// ServiceBudget bounds twin show's and twin verify's best-effort read of the workflow
	// service (showServiceBudget).
	ServiceBudget time.Duration
	// Paths is the state root: resolved once at start by fylgja serve, and from the
	// process environment at each request in the command tests (lab.ResolvePaths).
	Paths func() (lab.Paths, error)
	// PSPDir is the override directory of support packages, loaded at each request
	// (options.pspDir).
	PSPDir string
	// Getenv reads the host check's and verify's variables: the logins, the memory budget
	// (os.LookupEnv).
	Getenv func(string) (string, bool)
	// Build is the server's --version, sent on every answer as Fylgja-Build.
	Build string
	// Log takes one line a request when it ends, and the dependencies' warnings of a
	// request that asked for no rendering.
	Log *slog.Logger

	// tokenSum is the SHA-256 of the API's token; the token itself is not held, and is never
	// formatted.
	tokenSum [sha256.Size]byte
	// ops are the operations served, one route each.
	ops     []operation
	streams *streams
}

// New is a server whose token is token and whose fields are fylgja serve's: the workflow
// service's own client, containerlab and docker on the host, the nodes' gNMI reader, M4's
// budget, the state root from the environment, the environment, and a log on stderr. A
// caller sets Build, and anything else it gives otherwise.
//
// A server with no token refuses every request: no credential a request can carry is
// empty.
func New(token string) *Server {
	return &Server{
		Dial: func(ctx context.Context, log *slog.Logger) (provision.Service, error) {
			c, err := provision.Dial(ctx, log)
			if err != nil {
				return nil, err
			}
			return c, nil
		},
		Runner:        lab.ExecRunner{},
		Reader:        lab.GNMIReader{},
		ServiceBudget: provision.ShowServiceBudget,
		Paths:         lab.ResolvePaths,
		Getenv:        os.LookupEnv,
		Log:           slog.New(slog.NewTextHandler(os.Stderr, nil)),
		tokenSum:      sha256.Sum256([]byte(token)),
		ops:           operations(),
		streams:       newStreams(),
	}
}

// operation is one of the twelve: its name, as the findings document names it and its path
// spells it; the handler, M12's command; and whether it takes the operator's interrupt
// from its start frame.
type operation struct {
	name        string
	run         func(*call) error
	takesStream bool
}

// operations is the table of the twelve, each with its handler (handlers.go).
func operations() []operation {
	ops := make([]operation, 0, len(api.Operations))
	for _, name := range api.Operations {
		ops = append(ops, operation{name: name, run: handlers[name], takesStream: takesStream(name)})
	}
	return ops
}

// takesStream is whether an operation starts a run the operator may interrupt: twin create,
// twin provision and twin step. twin destroy is followed and takes none, as M12's took
// none.
func takesStream(op string) bool {
	switch op {
	case findings.OpTwinCreate, findings.OpTwinProvision, findings.OpTwinStep:
		return true
	}
	return false
}

// The outcomes the request log names besides a document's status.
const (
	outcomeTokenRefused   = "token_refused"
	outcomeVersionUnknown = "version_unknown"
	outcomeNotFound       = "not_found"
	outcomeTooLarge       = "too_large"
	outcomeUnreadable     = "unreadable"
	outcomeStreamOpen     = "stream_open"
	outcomeClientGone     = "client_gone"
	outcomePanic          = "panic"
	outcomeDelivered      = "delivered"
	outcomeStreamEnded    = "stream_ended"
)

// The names the log gives a request that is not one of the twelve.
const (
	logInterrupt = "interrupt"
	logUnknown   = "unknown"
)

// Handler is the API, version 1 (contracts/api.md). One wrapper round the whole mux
// compares the token before the route is looked up or the body read; every answer to a
// request that carried it names the API's version and the server's build.
func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	for _, op := range s.ops {
		mux.Handle("POST "+api.Path(op.name), s.serveOperation(op))
	}
	mux.HandleFunc("POST "+api.InterruptPath("{stream}"), s.serveInterrupt)
	// A path under version 1 that names nothing served, or names an operation asked with
	// another method, and a path under no version served at all, which names the versions
	// there are. Nothing is read or done for either.
	mux.HandleFunc("/v"+api.Version+"/", func(w http.ResponseWriter, r *http.Request) {
		s.noOperation(w, r.URL.Path)
	})
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		s.noVersion(w)
	})
	return s.authorize(s.unredirected(mux))
}

// versionRoot is version 1's own path, without the slash that begins its operations.
const versionRoot = "/v" + api.Version

// unredirected answers what ServeMux would redirect, 301 or 307 with no problem body and no
// log line: a path not in its clean form, and the version's own path without its slash. It
// is answered as the path it cleans to is, a path under version 1 that names no operation or
// one under no version served (contracts/api.md, "The transport's statuses").
func (s *Server) unredirected(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		p := r.URL.Path
		clean := cleanPath(p)
		switch {
		case p == versionRoot || p != clean && (clean == versionRoot || strings.HasPrefix(clean, versionRoot+"/")):
			s.noOperation(w, p)
		case p != clean:
			s.noVersion(w)
		default:
			next.ServeHTTP(w, r)
		}
	})
}

// cleanPath is the path ServeMux would redirect p to, and p itself when it would not: rooted,
// with no empty, "." or ".." element, and a trailing slash kept.
func cleanPath(p string) string {
	if p == "" {
		return "/"
	}
	if p[0] != '/' {
		p = "/" + p
	}
	clean := path.Clean(p)
	if strings.HasSuffix(p, "/") && clean != "/" {
		clean += "/"
	}
	return clean
}

// noOperation is the 404 for a path under version 1 that names no operation, or one asked
// with another method, logged under the operation the path names, if any.
func (s *Server) noOperation(w http.ResponseWriter, p string) {
	began := time.Now()
	writeProblem(w, http.StatusNotFound, api.Problem{
		Message: "API version " + api.Version + " has no operation at this path; nothing was read or done"})
	s.logRequest(logName(p), outcomeNotFound, began, slog.LevelWarn)
}

// noVersion is the 404 for a path under no version served, naming the versions there are.
func (s *Server) noVersion(w http.ResponseWriter) {
	began := time.Now()
	w.Header().Set(api.HeaderVersions, api.Version)
	writeProblem(w, http.StatusNotFound, api.Problem{
		Message: "this server serves API version " + api.Version + "; nothing was read or done"})
	s.logRequest(logUnknown, outcomeVersionUnknown, began, slog.LevelWarn)
}

// authorize answers 401 to a request without the token, or with another, before anything
// else is looked at. The comparison is of the two SHA-256 digests in
// constant time, so neither the token's length nor its bytes are told by the time taken.
func (s *Server) authorize(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !s.carriesToken(r.Header.Get("Authorization")) {
			began := time.Now()
			w.Header().Set("WWW-Authenticate", "Bearer")
			writeProblem(w, http.StatusUnauthorized, api.Problem{
				Message: "this request does not carry the API's token; nothing was read or done"})
			s.logRequest(logName(r.URL.Path), outcomeTokenRefused, began, slog.LevelWarn)
			return
		}
		w.Header().Set(api.HeaderVersion, api.Version)
		w.Header().Set(api.HeaderBuild, s.Build)
		next.ServeHTTP(w, r)
	})
}

// carriesToken is whether an Authorization header is the bearer credential this server
// was started with.
func (s *Server) carriesToken(header string) bool {
	const scheme = "Bearer "
	if len(header) <= len(scheme) || !strings.EqualFold(header[:len(scheme)], scheme) {
		return false
	}
	got := sha256.Sum256([]byte(header[len(scheme):]))
	return subtle.ConstantTimeCompare(got[:], s.tokenSum[:]) == 1
}

// serveOperation is one operation's route: the bound, the request decoded strictly, the
// stream registered, then the answer's headers, sent before any work (the client's
// api.HeaderTimeout waits for them), then the operation itself, its document the last frame.
func (s *Server) serveOperation(op operation) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		began := time.Now()
		// A body declared over the bound is refused before any of it is asked for; one that
		// only turns out to be is cut by MaxBytesReader.
		if r.ContentLength > api.MaxRequestBytes {
			s.refuseTooLarge(w, op.name, began)
			return
		}
		r.Body = http.MaxBytesReader(w, r.Body, api.MaxRequestBytes)
		req, err := api.DecodeRequest(r.Body)
		if err != nil {
			var tooLarge *http.MaxBytesError
			if errors.As(err, &tooLarge) {
				s.refuseTooLarge(w, op.name, began)
				return
			}
			writeProblem(w, http.StatusBadRequest, api.Problem{Message: err.Error()})
			s.logRequest(op.name, outcomeUnreadable, began, slog.LevelWarn)
			return
		}
		// An argument the operation does not take, or files it takes none of, is a request
		// the server cannot read, refused before any guard (contracts/api.md).
		if err := checkRequest(op.name, req); err != nil {
			writeProblem(w, http.StatusBadRequest, api.Problem{Message: err.Error()})
			s.logRequest(op.name, outcomeUnreadable, began, slog.LevelWarn)
			return
		}

		// A request without a stream runs, and nothing can interrupt it: no one writes to
		// this channel.
		var interrupts <-chan os.Signal = make(chan os.Signal)
		if id := r.Header.Get(api.HeaderStream); op.takesStream && id != "" {
			if !streamIdentity(id) {
				writeProblem(w, http.StatusBadRequest, api.Problem{
					Message: "the request is not one: " + api.HeaderStream + " is not a stream identity"})
				s.logRequest(op.name, outcomeUnreadable, began, slog.LevelWarn)
				return
			}
			ch, release, ok := s.streams.open(id)
			if !ok {
				writeProblem(w, http.StatusConflict, api.Problem{
					Message: "an answer is already open under this stream; nothing was done"})
				s.logRequest(op.name, outcomeStreamOpen, began, slog.LevelWarn)
				return
			}
			defer release()
			interrupts = ch
		}

		w.Header().Set("Content-Type", "application/x-ndjson")
		w.WriteHeader(http.StatusOK)
		rc := http.NewResponseController(w)
		_ = rc.Flush()

		f := newFrames(w, rc)
		// Whatever outlives the request writes nothing to an answer whose handler has
		// returned, with or without its document.
		defer f.end()
		c := s.newCall(r.Context(), op.name, req, f, interrupts)
		outcome, level := s.answer(c, op, began)
		s.logRequest(op.name, outcome, began, level)
	}
}

// answer runs the operation and writes its document, and says how the request ended. A
// client gone before the document is written is not written to. A panic in the operation is
// logged by its operation alone and aborts the answer, which then has no document: the
// client reports it as not finished.
func (s *Server) answer(c *call, op operation, began time.Time) (outcome string, level slog.Level) {
	defer func() {
		if p := recover(); p != nil {
			s.logRequest(op.name, outcomePanic, began, slog.LevelError)
			panic(http.ErrAbortHandler)
		}
	}()
	doc := documentOf(op.name, op.run(c))
	if c.ctx.Err() != nil {
		return outcomeClientGone, slog.LevelWarn
	}
	if err := c.document(doc); err != nil {
		return outcomeClientGone, slog.LevelWarn
	}
	return string(doc.Status), slog.LevelInfo
}

// result carries an operation's findings document out of its handler, as M12's carried a
// command's out to main.
type result struct {
	doc *findings.Document
}

func (r *result) Error() string { return string(r.doc.Status) }

// documentOf is the document an operation's error carries, or, for an error that carries
// none, the operation failing with its text, as M12's report made one (main.go).
func documentOf(op string, err error) *findings.Document {
	var res *result
	switch {
	case err == nil:
		return findings.ErrorDocument(op, nil, fmt.Sprintf("operation %s ended without a document", op))
	case errors.As(err, &res):
		return res.doc
	default:
		return findings.ErrorDocument(op, nil, err.Error())
	}
}

// serveInterrupt delivers the operator's interrupt to the open answer the path names: 204,
// or 404 when no such answer is open.
func (s *Server) serveInterrupt(w http.ResponseWriter, r *http.Request) {
	began := time.Now()
	if s.streams.interrupt(r.PathValue("stream")) {
		w.WriteHeader(http.StatusNoContent)
		s.logRequest(logInterrupt, outcomeDelivered, began, slog.LevelInfo)
		return
	}
	writeProblem(w, http.StatusNotFound, api.Problem{Message: "no answer is open under this stream"})
	s.logRequest(logInterrupt, outcomeStreamEnded, began, slog.LevelInfo)
}

// refuseTooLarge is the 413 for a body over the bound, naming it; nothing was decoded or
// filed.
func (s *Server) refuseTooLarge(w http.ResponseWriter, op string, began time.Time) {
	writeProblem(w, http.StatusRequestEntityTooLarge, api.Problem{
		Message: fmt.Sprintf("the request is larger than this server's transfer bound of %d bytes (%d MiB); nothing was read or filed",
			api.MaxRequestBytes, api.MaxRequestBytes>>20),
		LimitBytes: api.MaxRequestBytes,
	})
	s.logRequest(op, outcomeTooLarge, began, slog.LevelWarn)
}

// logRequest is the one line a request ends with: its operation, its outcome and how long
// it took, and nothing of its arguments, paths, body or token.
func (s *Server) logRequest(op, outcome string, began time.Time, level slog.Level) {
	s.Log.Log(context.Background(), level, "request",
		"operation", op, "outcome", outcome, "duration", time.Since(began).Round(time.Millisecond))
}

// logName is the operation a path names, for the log alone: one of the twelve, the
// interrupt, or unknown. No part of the path itself is logged.
func logName(path string) string {
	for _, op := range api.Operations {
		if path == api.Path(op) {
			return op
		}
	}
	if strings.HasPrefix(path, "/v"+api.Version+"/streams/") && strings.HasSuffix(path, "/interrupt") {
		return logInterrupt
	}
	return logUnknown
}

// streamIdentity is whether a Fylgja-Stream value can be named by the interrupt's path:
// one path segment, unescaped, of at most api.MaxStreamLength characters, as the client's
// api.StreamBytes random bytes in hex are.
func streamIdentity(id string) bool {
	return len(id) <= api.MaxStreamLength && url.PathEscape(id) == id && id != "." && id != ".."
}

// writeProblem answers a transport fault with its JSON body.
func writeProblem(w http.ResponseWriter, status int, p api.Problem) {
	b, err := json.Marshal(p)
	if err != nil {
		b = []byte(`{"message":"the server could not word this fault"}`)
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_, _ = w.Write(append(b, '\n'))
}
