package cli

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
)

// newClient builds the client of the API the environment names. A variable so a test can
// lower the client's frame bound (api.Client.MaxFrameBytes) and keep its case small; nothing
// else changes it.
var newClient = api.NewClient

// handlers are what a command does with the frames that are its own to act on.
type handlers struct {
	// files takes the operator's files an answer carries, the CTM or the bundle, before
	// anything after them is printed. An error ends the command with its own
	// operation.failed, in M12's words, and nothing more of the answer is printed.
	files func([]api.File) error
}

// given are the flags a command was given, by the names the request gives them, at their
// values as given.
type given map[string]any

// string names a string flag given a value; one left empty is a flag M12 read as not given.
func (g given) string(name, value string) {
	if value != "" {
		g[name] = value
	}
}

// bool names a boolean flag that is set.
func (g given) bool(name string, value bool) {
	if value {
		g[name] = true
	}
}

// progress is how far an answer got, which a failure of the transport names.
type progress struct {
	// started is whether the server had begun to start a run: its start frame.
	started bool
	// run is the run's identity, once the server named it.
	run *api.RunRef
	// cancelAsked is whether an interrupt for the run reached the server, which then asked
	// the run to cancel, or abandoned its start.
	cancelAsked bool
}

// send is a command's one request and what it prints. args are the flags
// that were given, at their values as given, so an absent key is a flag not given and
// "interval": "" is --interval=; every guard is the server's. The rendering is the one
// --json selects. Each out frame is printed to stdout and each err frame to stderr as it
// arrives; the document ends the command, as a result report prints.
func send(ctx context.Context, opts *options, op string, args map[string]any, files []api.File, h handlers) error {
	if ctx == nil {
		ctx = context.Background()
	}
	client, err := newClient(getenv, build)
	if err != nil {
		return transportFailure(op, err, progress{})
	}
	req := api.Request{Render: api.RenderText, Files: files}
	if opts.asJSON {
		req.Render = api.RenderJSON
	}
	if len(args) > 0 {
		req.Args = make(map[string]json.RawMessage, len(args))
		for k, v := range args {
			b, err := json.Marshal(v)
			if err != nil {
				return fail(op, nil, "%v", err)
			}
			req.Args[k] = b
		}
	}
	var stream string
	if takesInterrupts(op) {
		if stream, err = newStream(); err != nil {
			return fail(op, nil, "%v", err)
		}
	}

	// The answer is read under its own context, which an interrupt that could not be
	// delivered ends, so the command stops waiting on a server that is gone.
	answerCtx, abandon := context.WithCancel(ctx)
	defer abandon()
	answer, err := client.Do(answerCtx, op, req, stream, func(served string) { buildLine(client, served) })
	if err != nil {
		return transportFailure(op, err, progress{})
	}
	defer func() { _ = answer.Close() }()

	var got progress
	var armed *interrupts
	// written is why a file of the answer could not be written on this machine: the command
	// ends with its own failure, worded as M12's, and the rest of the answer is read to its
	// document, whose subject the failure names, and printed no more.
	var written error
	defer func() {
		if armed != nil {
			armed.stop()
		}
	}()
	for {
		f, err := answer.Next()
		if err != nil {
			if armed != nil {
				got.cancelAsked = armed.deliveredAny()
				if undelivered := armed.failure(); undelivered != nil {
					return transportFailure(op, &interruptUndelivered{address: client.Address(), err: undelivered}, got)
				}
			}
			return transportFailure(op, err, got)
		}
		if written != nil && f.Kind() != api.KindDocument {
			continue
		}
		switch f.Kind() {
		case api.KindOut:
			_, _ = io.WriteString(os.Stdout, f.Out)
		case api.KindErr:
			_, _ = io.WriteString(os.Stderr, f.Err)
		case api.KindFiles:
			if h.files != nil {
				// A failure that is already a document ends the command with it; any other
				// is worded under the subject the server's document names, read below.
				var res *result
				if written = h.files(f.Files); errors.As(written, &res) {
					return written
				}
			}
		case api.KindStart:
			// From here an interrupt is the server's to act on, as M12's handler was
			// installed just before the start.
			got.started = true
			if armed == nil && stream != "" {
				armed = arm(ctx, client, stream, abandon)
			}
		case api.KindRun:
			got.run = f.Run
		case api.KindDocument:
			var doc findings.Document
			if err := json.Unmarshal(f.Document, &doc); err != nil {
				return fail(op, nil, "the API at %s sent a document this client cannot read: %v", client.Address(), err)
			}
			if written != nil {
				return writeFailure(op, &doc, written)
			}
			return &result{doc: &doc, raw: f.Document, text: f.Text}
		}
		// A frame of a kind this build does not know is passed over.
	}
}

// writeFailure is a file of the answer that could not be written on this machine: the
// operation failing in M12's words, under the subject and the waypoint the server's document
// named, which are what M12's command had decided when its write failed.
func writeFailure(op string, served *findings.Document, err error) error {
	res := &result{doc: findings.ErrorDocument(op, served.Subject, err.Error())}
	res.doc.Waypoint = served.Waypoint
	return res
}

// failAt is fail for a command whose findings name the step they belong to and the object
// concerned: twin provision's bundle directory that cannot be read, at step verify, as M12's
// first step refused it.
func failAt(op string, subject *findings.Subject, step, object, format string, args ...any) error {
	doc := findings.ErrorDocument(op, subject, fmt.Sprintf(format, args...))
	doc.Findings[0].Step, doc.Findings[0].Object = step, object
	return &result{doc: doc}
}

// buildLine says, once and before any frame is printed, that the server is another build
// than this client. It is not a finding and is not in the document,
// so the command goes on to its own result whatever the builds are.
func buildLine(client *api.Client, served string) {
	if served == client.Build() {
		return
	}
	_, _ = fmt.Fprintf(os.Stderr, "fylgja: this client is build %s; the API at %s is build %s\n", client.Build(), client.Address(), served)
}

// takesInterrupts is whether an operation starts a run the operator may interrupt, and so
// names a stream for it: twin create, twin provision and twin step. twin destroy
// takes none, as at M12.
func takesInterrupts(op string) bool {
	switch op {
	case findings.OpTwinCreate, findings.OpTwinProvision, findings.OpTwinStep:
		return true
	}
	return false
}

// newStream is a fresh stream identity: api.StreamBytes random bytes in hex.
func newStream() (string, error) {
	b := make([]byte, api.StreamBytes)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return hex.EncodeToString(b), nil
}
