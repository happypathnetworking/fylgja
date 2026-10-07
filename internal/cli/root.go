// Package cli is the client's commands: every command of the binary but fylgja serve and
// fylgja worker run. Each does its work by one request to the API and prints what comes
// back, as M12's command printed it (D-040).
//
// It imports cobra, internal/api, internal/findings and internal/tree, and nothing else of
// the module: no flag and no variable can make a client's command run the core, because
// this package does not link it (Constitution XI). internal/compiler's
// TestClientReachesTheCoreThroughTheAPIAlone holds it so.
package cli

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"strings"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

// getenv is the client's environment, from which it reads FYLGJA_API_ADDRESS and
// FYLGJA_API_TOKEN and nothing else. A variable so tests give the client a server
// of their own.
var getenv = os.LookupEnv

// build is the binary's --version, which main hands over and the client compares with the
// server's.
var build string

// result carries a findings document out of a command so main can render it once and exit
// with the right code. Commands never render or exit themselves — that keeps output format
// and exit codes in one place, which is what makes them a contract.
//
// A document the server sent keeps the frame's bytes, written as they came under --json,
// and the findings' text the server rendered; one the client made itself has neither, and
// is rendered here.
type result struct {
	doc  *findings.Document
	raw  json.RawMessage
	text string
}

func (r *result) Error() string { return string(r.doc.Status) }

// options are the flags every client's command shares: --json alone. The override
// directory of support packages is the server's.
type options struct {
	asJSON bool
}

// rootOptions are the root command's, which AddCommands binds and Report reads.
var rootOptions = &options{}

// AddCommands gives root the persistent --json flag every client's command shares, and the
// client's commands; b is the binary's --version.
func AddCommands(root *cobra.Command, b string) {
	build = b
	root.PersistentFlags().BoolVar(&rootOptions.asJSON, "json", false,
		"emit one findings document on stdout and nothing else there")
	root.AddCommand(newIntentCmd(rootOptions))
	root.AddCommand(newTwinCmd(rootOptions))
	root.AddCommand(newWaypointCmd(rootOptions))
	root.AddCommand(newSchemaCmd(rootOptions))
	root.AddCommand(newPSPCmd(rootOptions))
}

// Report renders whatever a client's command produced and returns the process exit code.
func Report(cmd *cobra.Command, err error) int {
	return report(rootOptions, cmd, err)
}

// operationOf names the command a failure came from, in the form the findings
// contract uses: `fylgja intent read` is `intent.read`. Taking it from cobra rather
// than a second hand-kept table means the document's `operation` cannot drift from
// the command that produced it.
//
// It is empty when the failure is the root command's own — `fylgja --nope`, before
// any operation was named.
func operationOf(cmd *cobra.Command) string {
	if cmd == nil {
		return ""
	}
	parts := strings.Fields(cmd.CommandPath())
	if len(parts) < 2 {
		return ""
	}
	return strings.Join(parts[1:], ".")
}

// report renders whatever a command produced and returns the process exit code. A document
// the server sent is printed as it came: under --json its bytes re-indented, which is
// WriteJSON's output byte for byte, and otherwise the findings' text the server
// rendered, on stderr where M12's report wrote WriteText's. The exit status is the
// document's.
func report(opts *options, cmd *cobra.Command, err error) int {
	var res *result
	switch {
	case err == nil:
		return findings.ExitOK
	case errors.As(err, &res) && res.raw != nil:
		if opts.asJSON {
			var b bytes.Buffer
			if err := json.Indent(&b, res.raw, "", "  "); err != nil {
				_, _ = fmt.Fprintln(os.Stderr, "fylgja:", err)
				return findings.ExitError
			}
			b.WriteByte('\n')
			if _, err := os.Stdout.Write(b.Bytes()); err != nil {
				_, _ = fmt.Fprintln(os.Stderr, "fylgja:", err)
				return findings.ExitError
			}
		} else if _, err := os.Stderr.WriteString(res.text); err != nil {
			return findings.ExitError
		}
		return res.doc.Status.ExitCode()
	case errors.As(err, &res):
		return findings.Render(res.doc, os.Stdout, os.Stderr, opts.asJSON)
	default:
		// A usage or system failure: the operation could not run, as distinct from
		// running and rejecting its input.
		op := operationOf(cmd)
		if op == "" {
			// No operation was named, so there is no document to write: every
			// findings document identifies the operation it reports on, and an
			// invented one would be a lie in a machine-readable field. Say it in
			// text and exit 2.
			_, _ = fmt.Fprintln(os.Stderr, "fylgja:", err)
			return findings.ExitError
		}
		return findings.Render(findings.ErrorDocument(op, nil, err.Error()),
			os.Stdout, os.Stderr, opts.asJSON)
	}
}

// fail wraps a usage or system error as a document, so even failures are machine
// readable under --json.
func fail(op string, subject *findings.Subject, format string, args ...any) error {
	return &result{doc: findings.ErrorDocument(op, subject, fmt.Sprintf(format, args...))}
}
