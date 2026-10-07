package server

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"os"
	"strings"
	"sync"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/provision"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/verify"
)

// call is one request to an operation: what its handler reads and writes in place of the
// process M12's command ran in.
type call struct {
	s  *Server
	op string
	// ctx is the request's: it ends when the client goes away, which stops the request's
	// work, and never cancels a run already started.
	ctx context.Context
	req api.Request
	// frames is the answer, one JSON object a line, flushed as written.
	frames *frames
	// console stands where options.note and os.Stderr stood.
	console *console
	// log is the dependencies' logger: the containerlab driver's, the node reader's and the
	// workflow SDK's warnings, which M12 wrote to the operator's stderr.
	log *slog.Logger
	// interrupts are the operator's, delivered to this request by the interrupt call from
	// its start frame on; a request without a stream gets a channel no one writes to.
	interrupts <-chan os.Signal
}

func (s *Server) newCall(ctx context.Context, op string, req api.Request, f *frames, interrupts <-chan os.Signal) *call {
	c := &call{s: s, op: op, ctx: ctx, req: req, frames: f, interrupts: interrupts,
		console: newConsole(req.Render, f)}
	if req.Render != "" {
		// Where M12 wrote them, in either mode: the operator's stderr, now err frames.
		c.log = slog.New(slog.NewTextHandler(c.console.stderr(), &slog.HandlerOptions{Level: slog.LevelWarn}))
	} else {
		// No one reads the request's stderr, so the warnings go where the operator of the
		// server reads them.
		c.log = slog.New(atLeast{Handler: s.Log.Handler(), min: slog.LevelWarn}).With("operation", op)
	}
	return c
}

// document writes the answer's last frame: the document as findings.WriteJSON marshals it,
// and under render text its findings as WriteText renders them, which M12's report printed
// on stderr once the command had returned. A document with no findings has
// no text.
func (c *call) document(doc *findings.Document) error {
	c.console.flush()
	var raw bytes.Buffer
	if err := doc.WriteJSON(&raw); err != nil {
		return err
	}
	f := api.Frame{Document: json.RawMessage(raw.Bytes())}
	if c.req.Render == api.RenderText {
		var text strings.Builder
		if err := doc.WriteText(&text); err != nil {
			return err
		}
		f.Text = text.String()
	}
	return c.frames.writeLast(f)
}

// startFrame says the server begins to start workflowID's run, and returns the channel the
// operator's interrupts arrive on, which M12's command began to listen to here.
// A request that has ended, or whose start frame cannot be written, has no client to begin
// a run for: the error says so, and nothing is started (contracts/cli.md, "Runs": an
// interrupt before the start leaves nothing started).
func (c *call) startFrame(workflowID string) (<-chan os.Signal, error) {
	if err := c.ctx.Err(); err != nil {
		return nil, err
	}
	if err := c.frames.write(api.Frame{Start: &api.RunRef{WorkflowID: workflowID}}); err != nil {
		return nil, err
	}
	return c.interrupts, nil
}

// runFrame names the run once it is started.
func (c *call) runFrame(workflowID, runID string) {
	_ = c.frames.write(api.Frame{Run: &api.RunRef{WorkflowID: workflowID, RunID: runID}})
}

// eventFrame is one progress event of a run, as the run's history gave it to the
// follow.
// It is sent whatever the rendering: with none, a run's answer is its run, its
// events and its document.
func (c *call) eventFrame(e provision.Event) {
	_ = c.frames.write(api.Frame{Event: &api.Event{WorkflowID: e.WorkflowID, Step: e.Step, FindingStep: e.FindingStep,
		End: e.End, Outcome: e.Outcome, DurationS: e.Duration.Seconds(), Detail: e.Detail, Rule: e.Rule,
		Message: e.Message, Notice: e.Notice}})
}

// files sends the operator's files an answer carries, the CTM or the bundle, in one
// frame.
// An answer whose client has gone is not written to.
func (c *call) files(files []api.File) error {
	return c.frames.write(api.Frame{Files: files})
}

// packages loads the support packages as each M12 command loaded them: the embedded ones,
// overridden from the server's directory, at each request, so an override edited between
// two commands is seen by the second.
func (c *call) packages() (*psp.Registry, error) {
	return psp.Load(c.s.PSPDir)
}

// activities are the lab host's activities as a request calls them, in the server's own
// process: the host check and containerlab's plan through the server's runner, never the
// workflow service, as M12's dry run built them (dryRunActivities; D-041).
func (c *call) activities(reg *psp.Registry, paths lab.Paths) *lab.Activities {
	return &lab.Activities{
		// containerlab's invocations are logged as a worker logs them, but only when they
		// fail: the request's text is the report.
		Clab:     &lab.Clab{Runner: c.s.Runner, Log: c.log},
		Store:    bundle.NewDirStore(paths.Bundles),
		Paths:    paths,
		Registry: reg,
		// Presence is asked of the host's own runtime, through the same runner, so a dry
		// run's refusal for an image the host does not hold is the run's.
		Images:  lab.DockerImages{Runner: c.s.Runner},
		Getenv:  c.s.Getenv,
		Version: c.s.Build,
	}
}

// reader is the server's node reader, logging to the request's logger when it has none of
// its own.
func (c *call) reader() verify.Reader {
	if r, ok := c.s.Reader.(lab.GNMIReader); ok && r.Log == nil {
		r.Log = c.log
		return r
	}
	return c.s.Reader
}

// frames writes an answer: each frame one line, flushed before the next is written, so a
// client sees each as it happens. The run's follow and the handler write from two
// goroutines, so a frame is written whole. Once a write fails, the client has gone, and
// nothing more is written.
//
// An answer ends at its document, or when its handler returns without one. From then on a
// frame is dropped without the writer being touched: a run's follow, or the workflow
// service's read under twin show's budget, can outlive the request, and the document is
// always the last line (contracts/api.md, "The answer"), written to a ResponseWriter that is
// still the request's.
type frames struct {
	mu    sync.Mutex
	w     io.Writer
	rc    *http.ResponseController
	err   error
	ended bool
}

// errAnswerEnded is what a frame written after its answer ended is told.
var errAnswerEnded = errors.New("the answer has ended")

func newFrames(w io.Writer, rc *http.ResponseController) *frames {
	return &frames{w: w, rc: rc}
}

func (f *frames) write(fr api.Frame) error {
	return f.writeFrame(fr, false)
}

// writeLast writes the answer's last frame, the document, and ends the answer, under one
// hold of the lock, so no frame can follow it.
func (f *frames) writeLast(fr api.Frame) error {
	return f.writeFrame(fr, true)
}

// end ends the answer without a frame: its handler has returned.
func (f *frames) end() {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.ended = true
}

func (f *frames) writeFrame(fr api.Frame, last bool) error {
	b, err := json.Marshal(fr)
	if err != nil {
		return err
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.ended {
		return errAnswerEnded
	}
	if last {
		f.ended = true
	}
	if f.err != nil {
		return f.err
	}
	if _, err := f.w.Write(append(b, '\n')); err != nil {
		f.err = err
		return err
	}
	if f.rc != nil {
		if err := f.rc.Flush(); err != nil {
			f.err = err
			return err
		}
	}
	return nil
}

// atLeast passes on the records of its handler's that are at min or above: the server's log
// takes a dependency's warnings, as M12's stderr did, and not its chatter.
type atLeast struct {
	slog.Handler
	min slog.Level
}

func (h atLeast) Enabled(ctx context.Context, l slog.Level) bool {
	return l >= h.min && h.Handler.Enabled(ctx, l)
}

func (h atLeast) WithAttrs(attrs []slog.Attr) slog.Handler {
	return atLeast{Handler: h.Handler.WithAttrs(attrs), min: h.min}
}

func (h atLeast) WithGroup(name string) slog.Handler {
	return atLeast{Handler: h.Handler.WithGroup(name), min: h.min}
}
