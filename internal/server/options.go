package server

import (
	"context"
	"fmt"
	"io"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/provision"
)

// options are what M12's commands shared beside their own flags, now taken from the request
// each serves. asJSON is a rendering that prints no note, as --json
// printed none: render "json", or none at all. pspDir is the server's override directory.
// c is the request: its console stands where stdout and stderr stood, and its server holds
// what M12's package variables held.
type options struct {
	asJSON bool
	pspDir string
	c      *call
}

// options are the request's, as each M12 command resolved its own.
func (c *call) options() *options {
	return &options{asJSON: c.req.Render != api.RenderText, pspDir: c.s.PSPDir, c: c}
}

// note prints a human-readable progress line: an out frame under render text. Suppressed
// otherwise, where the document is the answer and nothing else is (contracts/cli.md).
func (o *options) note(format string, args ...any) {
	if o.asJSON {
		return
	}
	o.c.console.note(format, args...)
}

// stderr is what M12 wrote to the operator's stderr.
func (o *options) stderr() io.Writer {
	return o.c.console.stderr()
}

// dial connects to the workflow service, its warnings the request's (dialService at M12).
func (o *options) dial(ctx context.Context) (provision.Service, error) {
	return o.c.s.Dial(ctx, o.c.log)
}

// paths is the state root (lab.ResolvePaths at M12).
func (o *options) paths() (lab.Paths, error) {
	return o.c.s.Paths()
}

// getenv reads the host check's and verify's variables (os.LookupEnv at M12).
func (o *options) getenv(name string) (string, bool) {
	return o.c.s.Getenv(name)
}

// version is the server's build, which a run records as the CLI's version did.
func (o *options) version() string {
	return o.c.s.Build
}

// fail wraps a usage or system error as a document, so even failures are machine
// readable under --json.
func fail(op string, subject *findings.Subject, format string, args ...any) error {
	return &result{doc: findings.ErrorDocument(op, subject, fmt.Sprintf(format, args...))}
}

// failAt is fail for twin create, twin provision and twin destroy, whose every finding names
// the step it belongs to and the object concerned. M1's commands have no steps
// and keep fail.
func failAt(op string, subject *findings.Subject, step, object, format string, args ...any) error {
	doc := findings.ErrorDocument(op, subject, fmt.Sprintf(format, args...))
	doc.Findings[0].Step, doc.Findings[0].Object = step, object
	return &result{doc: doc}
}

// finish wraps a completed run's findings. It always returns a result, even on
// success: under --json exactly one document must reach stdout, and a silent success
// would be an empty one.
func finish(op string, subject *findings.Subject, list findings.List) error {
	return &result{doc: findings.NewDocument(op, subject, list)}
}
