package server

import (
	"context"
	"errors"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/probe"
	"github.com/happypathnetworking/fylgja/internal/provision"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

type createFlags struct {
	dryRun bool
	// snapshot is --snapshot as given (018): a snapshot id the store holds, or the path of
	// the file the request carries. snapshotGiven is whether it was given at all, apart from
	// its value: an explicit empty one is refused by the store's rules, not left out.
	snapshot      string
	snapshotGiven bool
}

// fromSnapshot is whether the create names a snapshot: --snapshot given, whatever its value,
// or a value set without the flag, as a caller building the flags sets it.
func (f *createFlags) fromSnapshot() bool {
	return f.snapshotGiven || f.snapshot != ""
}

// runCreate is twin create. files are the request's: a snapshot file beside a --snapshot
// that is a path, and none otherwise. From 020 a create builds from a snapshot alone, which
// the orchestrator's adapter takes from Infrahub (D-065): the server reads no source of
// truth, and --snapshot is required, before the files are held to their shape.
func runCreate(ctx context.Context, opts *options, f *createFlags, files []api.File) error {
	const op = findings.OpTwinCreate
	subject := &findings.Subject{Snapshot: f.snapshot}
	if f.dryRun && opts.detach {
		return detachConflict(op, subject)
	}
	if !f.fromSnapshot() {
		return fail(op, subject, "--snapshot is required")
	}
	if refused := snapshotFiles(op, subject, true, f.snapshot, files); refused != nil {
		return refused
	}
	return runCreateFromSnapshot(ctx, opts, op, subject, f, files)
}

// runCreateFromSnapshot is twin create --snapshot (R-12), once runCreate has run its guards
// and held its files to their shape, before any connection: the snapshot resolved, an id from the store or the request's file read and
// filed; the compile and the bundle's filing, on the create's path; then the run, or the dry
// run's report. No request reaches Infrahub: nothing on this path builds an intent client,
// and the run, handed the bundle compiled, reads nothing.
func runCreateFromSnapshot(ctx context.Context, opts *options, op string, subject *findings.Subject, f *createFlags,
	files []api.File) error {
	if ctx == nil {
		ctx = context.Background()
	}
	// An override package psp validate rejects is refused under its own findings before the
	// snapshot is resolved, at compile, the first step that reads the packages: a create
	// from a snapshot reads no intent.
	reg, err := psp.Load(opts.pspDir)
	if err != nil {
		return loadFailureAt(op, subject, findings.StepCompile, err)
	}
	paths, err := opts.paths()
	if err != nil {
		return failAt(op, subject, findings.StepResolve, findings.StepResolve, "%v", err)
	}
	s, path, err := resolveSnapshot(ctx, paths, op, subject, f.snapshot, files)
	if err != nil {
		return err
	}
	// The document names what the snapshot is of from here on, as a stage's names the
	// reference it resolved to.
	env := s.CTM.Envelope
	subject.Branch, subject.At = env.Branch, env.At

	// The stored document's observed_at, the first take's, is the one the twin records
	// (US3 scenario 8).
	cr := &compiledRead{paths: paths, snapshot: filedSnapshot{id: s.ID, path: path}, observedAt: s.ObservedAt}
	if err := cr.compileAndFile(ctx, opts, op, subject, s.CTM, s.Probes, reg, nil); err != nil {
		return err
	}
	if f.dryRun {
		// No read took place, so the report has no read: line.
		return dryRunReport(ctx, opts, op, subject, reg, paths, &cr.snapshot, cr.bundlePath, cr.bundleID, cr.findings)
	}
	opts.note("%s", snapshotStoredLine(cr.snapshot.id, cr.snapshot.path))
	opts.note("%s", bundleStoredLine(cr.bundleID, cr.bundlePath))

	// Compiled already: the run takes the bundle and the snapshot by id and starts at the
	// host check. The branch, the at and the scope are the envelope's, which the record's
	// provenance reads from the staged manifest as every record's does. No Stage.
	in := provision.ProvisionInput{
		Source:     wire.SourceSnapshot,
		Branch:     env.Branch,
		At:         env.At,
		BundlePath: cr.bundlePath,
		BundleID:   cr.bundleID,
		ObservedAt: cr.observedAt,
		SnapshotID: cr.snapshot.id,
		Version:    opts.version(),
		Scope:      env.Scope,
	}
	return cr.carried(runProvision(ctx, opts, op, subject, in))
}

// filedSnapshot is a snapshot a command filed, as its stored: line names it.
type filedSnapshot struct {
	id, path string
}

// compiledRead is a snapshot once compiled and its bundle filed on the server: what the run
// is started with, and what the dry run reports.
type compiledRead struct {
	paths      lab.Paths
	snapshot   filedSnapshot
	bundleID   string
	bundlePath string
	// files are the bundle's, as the compile produced them: a step's target (019).
	files map[string][]byte
	// observedAt is the snapshot's read time, which the twin records.
	observedAt string
	// findings are the compile's, each at its step: none refuses.
	findings findings.List
}

// compileAndFile compiles c and decls, the CTM and the probes of the snapshot cr names, with
// the probe packages beside reg (016), and files the bundle under the
// state root, after list, the findings before the compile: what a create and a step's target
// share once the snapshot is filed. Each refusal, and each step that
// cannot run, is the command's document at compile, naming the snapshot, which stays filed,
// since its CTM validated and only the output was refused (R-05); the text answer names it
// too, by its stored line.
func (cr *compiledRead) compileAndFile(ctx context.Context, opts *options, op string, subject *findings.Subject, c *ctm.CTM,
	decls []probe.Probe, reg *psp.Registry, list findings.List) error {
	packages, err := opts.probes()
	if err != nil {
		return cr.refused(opts, loadFailureAt(op, subject, findings.StepCompile, err))
	}
	files, id, compiled := Compile(c, decls, reg, packages)
	compiled = compiled.AtStep(findings.StepCompile)
	list = append(list, compiled...)
	if compiled.Rejected() {
		return cr.refused(opts, finish(op, subject, list))
	}

	store, filed, err := fileCompiled(ctx, cr.paths.Bundles, files, id)
	if err != nil {
		return cr.refused(opts, failAt(op, subject, findings.StepCompile, cr.paths.Bundles, "%v", err))
	}
	if filed.Rejected() {
		return cr.refused(opts, finish(op, subject, append(list, filed...)))
	}

	cr.bundleID, cr.bundlePath, cr.files = id, store.Path(id), files
	cr.findings = list
	return nil
}

// refused is carried for a compile, or a bundle's filing, that refused or failed once the
// snapshot was filed: the text answer prints the snapshot's stored line, as the create's
// success prints it above the bundle's, so it names the snapshot the document names and the
// path of its entry, left to inspect (FR-010, FR-014). A snapshot refused at resolve by its
// own rules never reaches here: it leaves none filed. A
// step's snapshot target refused for its scope or mapping does (targetUnheld, 019): it was
// filed before it was judged.
func (cr *compiledRead) refused(opts *options, err error) error {
	opts.note("%s", snapshotStoredLine(cr.snapshot.id, cr.snapshot.path))
	return cr.carried(err)
}

// carried puts what the server resolved and compiled before any run on the document err
// holds, whatever it reports: the snapshot's id, the bundle's once it was filed, and the
// compile's findings before the run's own, which the run, starting at the host check, no
// longer reports.
func (cr *compiledRead) carried(err error) error {
	var res *result
	if !errors.As(err, &res) {
		return err
	}
	res.doc.SnapshotID = cr.snapshot.id
	if res.doc.BundleID == "" && cr.bundleID != "" {
		res.doc.BundleID = cr.bundleID
	}
	if len(cr.findings) > 0 {
		res.doc.Findings = append(append(findings.List{}, cr.findings...), res.doc.Findings...)
	}
	return err
}
