package server

import (
	"bytes"
	"fmt"
	"io"
	"sync"

	"github.com/happypathnetworking/fylgja/internal/api"
)

// console is a request's two writers, where M12's commands had options.note and
// os.Stderr.
// What each writes depends on the rendering the client
// asked for:
//
//	render  note           stderr
//	"text"  out frames     err frames
//	"json"  nothing        err frames   (as --json suppressed every note)
//	absent  nothing        nothing
//
// The moved code writes to it and never to the process's own streams.
type console struct {
	render string
	frames *frames
	errs   *lineFrames
}

func newConsole(render string, f *frames) *console {
	return &console{render: render, frames: f, errs: &lineFrames{frames: f}}
}

// note is one line for stdout, as M12's options.note printed it without --json.
func (c *console) note(format string, args ...any) {
	if c.render != api.RenderText {
		return
	}
	_ = c.frames.write(api.Frame{Out: fmt.Sprintf(format+"\n", args...)})
}

// stderr is what M12 wrote to the operator's stderr, in both modes.
func (c *console) stderr() io.Writer {
	if c.render == "" {
		return io.Discard
	}
	return c.errs
}

// flush sends what stderr holds that does not yet end a line, before the document.
func (c *console) flush() {
	c.errs.flush()
}

// lineFrames turns writes into err frames of whole lines: a write that ends part-way
// through a line holds that part until the line ends, or until the document is written.
type lineFrames struct {
	mu     sync.Mutex
	frames *frames
	held   []byte
}

func (l *lineFrames) Write(p []byte) (int, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.held = append(l.held, p...)
	if i := bytes.LastIndexByte(l.held, '\n'); i >= 0 {
		lines := string(l.held[:i+1])
		l.held = append(l.held[:0], l.held[i+1:]...)
		if err := l.frames.write(api.Frame{Err: lines}); err != nil {
			return 0, err
		}
	}
	return len(p), nil
}

func (l *lineFrames) flush() {
	l.mu.Lock()
	defer l.mu.Unlock()
	if len(l.held) == 0 {
		return
	}
	_ = l.frames.write(api.Frame{Err: string(l.held)})
	l.held = l.held[:0]
}
