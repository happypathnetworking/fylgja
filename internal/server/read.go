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
	"github.com/happypathnetworking/fylgja/internal/stages"
)

// observedAtFormat is the envelope's observed_at, shared with the read a provisioning
// run performs so the two stamp it identically.
const observedAtFormat = stage.ObservedAtFormat

type readFlags struct {
	branch string
	at     string
	// stage is --stage as given, <branch>/<label>: a moment of a proposed change, resolved
	// to a pinned reference in place of --branch and --at (014).
	stage string
	// stageGiven is whether --stage was given at all, apart from its value: an explicit
	// empty one is a reference refused, not one left out (M4's --interval= precedent).
	stageGiven bool
	out        string
}

// fromStage is whether the read names a stage: --stage given, whatever its value, or a
// value set without the flag, as a caller building the flags sets it.
func (f *readFlags) fromStage() bool {
	return f.stageGiven || f.stage != ""
}

func runRead(ctx context.Context, opts *options, f *readFlags) error {
	subject := &findings.Subject{Branch: f.branch, At: f.at, Out: f.out}

	if f.branch == "" && !f.fromStage() {
		return fail(findings.OpIntentRead, subject, "--branch or --stage is required")
	}
	if f.out == "" {
		return fail(findings.OpIntentRead, subject, "--out is required")
	}

	var ref stages.Ref
	if f.fromStage() {
		// A stage is a whole pinned reference, refused beside the flags it stands for
		// before any connection; with no step, as M1's operations carry none.
		var refused error
		ref, refused = stageGuards(findings.OpIntentRead, subject, "", f.stage, []flagConflict{
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
	// A stage resolves to the pinned reference it names, and the read is that reference's:
	// the CTM is the one --branch and --at would write, naming nothing of the stage. The
	// resolved line comes first, and every document after it names the stage.
	branch, at := f.branch, f.at
	var resolved *resolvedStage
	if f.fromStage() {
		if resolved, err = resolveStage(ctx, findings.OpIntentRead, subject, "", ref, reg); err != nil {
			return err
		}
		branch, at = resolved.block.Branch, resolved.block.At
		opts.note("%s", resolved.block.Line())
	}
	var block *findings.StageBlock
	if resolved != nil {
		block = &resolved.block
	}
	return withStage(read(ctx, opts, subject, branch, at, f.out, reg, observedAt, block), resolved)
}

// read is intent read's read and write of one reference, pinned or not.
func read(ctx context.Context, opts *options, subject *findings.Subject, branch, at, out string, reg *psp.Registry,
	observedAt string, resolved *findings.StageBlock) error {
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
		named = fmt.Sprintf("stage %s: %s", resolved.Ref, named)
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
// from 014 the stage it was resolved from and then the reference.
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
