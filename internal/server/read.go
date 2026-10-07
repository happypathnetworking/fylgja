package server

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/stage"
	"github.com/happypathnetworking/fylgja/internal/waypoint"
)

// observedAtFormat is the envelope's observed_at, shared with the read a provisioning
// run performs so the two stamp it identically.
const observedAtFormat = stage.ObservedAtFormat

type readFlags struct {
	branch string
	at     string
	// waypoint is --waypoint as given, <series>/<sequence>: a pinned reference named in
	// Infrahub, in place of --branch and --at (M10).
	waypoint string
	// waypointGiven is whether --waypoint was given at all, apart from its value: an explicit
	// empty one is a reference refused, not one left out (M4's --interval= precedent).
	waypointGiven bool
	out           string
}

// fromWaypoint is whether the read names a waypoint: --waypoint given, whatever its value,
// or a value set without the flag, as a caller building the flags sets it.
func (f *readFlags) fromWaypoint() bool {
	return f.waypointGiven || f.waypoint != ""
}

func runRead(ctx context.Context, opts *options, f *readFlags) error {
	subject := &findings.Subject{Branch: f.branch, At: f.at, Out: f.out}

	if f.branch == "" && !f.fromWaypoint() {
		return fail(findings.OpIntentRead, subject, "--branch or --waypoint is required")
	}
	if f.out == "" {
		return fail(findings.OpIntentRead, subject, "--out is required")
	}

	var ref waypoint.Ref
	if f.fromWaypoint() {
		// A waypoint is a whole pinned reference, refused beside the flags it stands for
		// before any connection; with no step, as M1's operations carry none (M10
		// contracts/cli.md).
		var refused error
		ref, refused = waypointGuards(findings.OpIntentRead, subject, "", f.waypoint, []flagConflict{
			{f.branch != "", "--branch", wholeReference},
			{f.at != "", "--at", wholeReference},
		})
		if refused != nil {
			return refused
		}
	} else if msg := intent.CheckAtPrecision(f.at); msg != "" {
		// The precision guard runs before any query: an `at` Infrahub would silently
		// truncate must not be sent, because the envelope records it verbatim and would
		// then name an instant nothing answered for.
		return &result{doc: findings.RuleErrorDocument(
			findings.OpIntentRead, subject, findings.RuleAtPrecision, f.at, msg)}
	}

	// Support packages are loaded before anything is dialled: an override package that
	// `psp validate` rejects is refused with its own findings, and no request is sent.
	reg, err := psp.Load(opts.pspDir)
	if err != nil {
		return loadFailure(findings.OpIntentRead, subject, err)
	}

	// Captured before the first request, so observed_at is never later than anything
	// the read could have seen.
	observedAt := time.Now().UTC().Format(observedAtFormat)

	if ctx == nil {
		ctx = context.Background()
	}
	// A waypoint resolves to the pinned reference it names, and the read is that
	// reference's: the CTM is the one --branch and --at would write, naming nothing of the
	// waypoint. Every document after it names the waypoint.
	branch, at := f.branch, f.at
	var resolved *findings.WaypointBlock
	if f.fromWaypoint() {
		if resolved, err = resolveWaypoint(ctx, findings.OpIntentRead, subject, "", ref); err != nil {
			return err
		}
		branch, at = resolved.Branch, resolved.At
	}
	return withWaypoint(read(ctx, opts, subject, branch, at, f.out, reg, observedAt, resolved), resolved)
}

// read is intent read's read and write of one reference, pinned or not.
func read(ctx context.Context, opts *options, subject *findings.Subject, branch, at, out string, reg *psp.Registry,
	observedAt string, resolved *findings.WaypointBlock) error {
	// Conformance, fetch and validation, reported together in one pass: the
	// same pipeline a create runs inside its run (internal/stage).
	snapshot, list, err := stage.Read(ctx, branch, at, reg, observedAt)
	if err != nil {
		return fail(findings.OpIntentRead, subject, "%v", err)
	}
	if snapshot == nil {
		return finish(findings.OpIntentRead, subject, list)
	}

	// The CTM goes to the client whole, before the summary line, and the client writes it
	// to --out atomically, as writeCTM did here: what the server holds of
	// the operator's machine is the path, for wording alone.
	b, err := ctm.Marshal(snapshot)
	if err != nil {
		return fail(findings.OpIntentRead, subject, "%v", err)
	}
	if err := opts.c.files([]api.File{{Path: ctmFile, Data: b}}); err != nil {
		return err
	}

	named := readSubject(snapshot.Envelope)
	if resolved != nil {
		named = fmt.Sprintf("waypoint %s/%d: %s", resolved.Series, resolved.Sequence, named)
	}
	opts.note("%s", summaryLine(out, snapshot, reg, named))
	return finish(findings.OpIntentRead, subject, list)
}

// readSummaryLine is intent read's success line: what the CTM holds, and what the
// support packages' profiles make of it, counted by the survey the compiler runs, so the
// numbers are the ones the bundle's fidelity.lossy will carry.
func readSummaryLine(out string, c *ctm.CTM, reg *psp.Registry) string {
	return summaryLine(out, c, reg, readSubject(c.Envelope))
}

// summaryLine is readSummaryLine naming what was read as named says: the reference, or
// from M10 the waypoint it was resolved from and then the reference (contracts/cli.md).
func summaryLine(out string, c *ctm.CTM, reg *psp.Registry, named string) string {
	return fmt.Sprintf("wrote %s: %s (%s)", out,
		readCounts(intent.Summarize(c), intent.DevicesByPackage(c, reg), compiler.Survey(c, reg)), named)
}

// readSubject describes the intent the CTM addresses, for the success line. `at` is
// named only when the operator supplied one — the envelope is the authority on
// whether the read was pinned.
func readSubject(e ctm.Envelope) string {
	s := "branch " + e.Branch
	if e.At != "" {
		s += ", at " + e.At
	}
	return s + ", schema " + e.SchemaHash
}

// ctmFile is the name intent read's CTM crosses under.
const ctmFile = "ctm.json"

// writeCTM writes the snapshot atomically: a reader either sees the whole CTM or no
// file at all. A half-written CTM would be worse than none, because it looks like intent.
func writeCTM(c *ctm.CTM, path string) error {
	b, err := ctm.Marshal(c)
	if err != nil {
		return err
	}
	dir := filepath.Dir(path)
	tmp, err := os.CreateTemp(dir, ".fylgja-ctm-*")
	if err != nil {
		return fmt.Errorf("writing CTM: %w", err)
	}
	defer func() { _ = os.Remove(tmp.Name()) }()
	if _, err := tmp.Write(b); err != nil {
		_ = tmp.Close()
		return fmt.Errorf("writing CTM: %w", err)
	}
	if err := tmp.Close(); err != nil {
		return fmt.Errorf("writing CTM: %w", err)
	}
	if err := os.Chmod(tmp.Name(), 0o644); err != nil {
		return fmt.Errorf("writing CTM: %w", err)
	}
	if err := os.Rename(tmp.Name(), path); err != nil {
		return fmt.Errorf("writing CTM: %w", err)
	}
	return nil
}
