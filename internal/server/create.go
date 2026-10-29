package server

import (
	"context"
	"errors"
	"time"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/probe"
	"github.com/happypathnetworking/fylgja/internal/provision"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/stage"
	"github.com/happypathnetworking/fylgja/internal/stages"
)

type createFlags struct {
	branch string
	at     string
	// stage is --stage as given, <branch>/<label>: a moment of a proposed change, resolved
	// to a pinned reference in place of --branch and --at (014).
	stage string
	// stageGiven is whether --stage was given at all, apart from its value: an explicit empty
	// one is a reference refused, not one left out (M4's --interval= precedent, a flag twin
	// create had until 019).
	stageGiven bool
	dryRun     bool
	// scope is --scope as given, read only when scopeGiven: not given, the server's default
	// stands (017).
	scope      string
	scopeGiven bool
	// snapshot is --snapshot as given (018): a snapshot id the store holds, or the path of
	// the file the request carries. snapshotGiven is whether it was given at all, as
	// stageGiven is.
	snapshot      string
	snapshotGiven bool
	// probes is --probes as given (016): the probe file every take of the create carries in
	// place of the kind's, refused beside --snapshot.
	probes probesArg
}

// fromStage is whether the create names a stage: --stage given, whatever its value, or a
// value set without the flag, as a caller building the flags sets it.
func (f *createFlags) fromStage() bool {
	return f.stageGiven || f.stage != ""
}

// fromSnapshot is whether the create names a snapshot, as fromStage is whether it names a
// stage.
func (f *createFlags) fromSnapshot() bool {
	return f.snapshotGiven || f.snapshot != ""
}

// runCreate is twin create. files are the request's: a snapshot file beside a --snapshot
// that is a path, and none otherwise. A snapshot's guards come before its files are held to
// that shape, since a client sends no file beside a flag they refuse: the guard's refusal is
// the answer, whatever the file.
func runCreate(ctx context.Context, opts *options, f *createFlags, files []api.File) error {
	const op = findings.OpTwinCreate
	subject := &findings.Subject{Branch: f.branch, At: f.at, Snapshot: f.snapshot}

	if f.fromSnapshot() {
		if refused := snapshotGuards(op, subject, f); refused != nil {
			return refused
		}
	}
	if refused := snapshotFiles(op, subject, f.fromSnapshot(), f.snapshot, files); refused != nil {
		return refused
	}
	if f.branch == "" && !f.fromStage() && !f.fromSnapshot() {
		return fail(op, subject, "--branch or --stage or --snapshot is required")
	}
	if f.fromSnapshot() {
		return runCreateFromSnapshot(ctx, opts, op, subject, f, files)
	}
	var ref stages.Ref
	if f.fromStage() {
		// A stage is a whole pinned reference: its guards stand in for --at's, before any
		// connection.
		var refused error
		ref, refused = stageGuards(op, subject, findings.StepStart, f.stage, []flagConflict{
			{f.branch != "", "--branch", wholeReference},
			{f.at != "", "--at", wholeReference},
		})
		if refused != nil {
			return refused
		}
	} else if msg := intent.CheckAtPrecision(f.at); msg != "" {
		// M1's precision guard, before any connection.
		return &result{doc: findings.RuleErrorDocument(op, subject, findings.RuleAtPrecision, f.at, msg)}
	}
	// The scope, after the reference's guards and before the packages load: the stage's
	// resolution, the read and the run's are made under it.
	scope, err := scopeOf(opts, op, subject, f.scope, f.scopeGiven)
	if err != nil {
		return err
	}
	subject.Scope = scope
	if ctx == nil {
		ctx = context.Background()
	}
	// An override package `psp validate` rejects is refused under its own findings
	// before anything is read or started.
	reg, err := psp.Load(opts.pspDir)
	if err != nil {
		return loadFailureAt(op, subject, findings.StepRead, err)
	}
	// The request's one probe list, before the stage resolves and the branch is read (016).
	probes, err := readProbes(ctx, opts, op, subject, f.probes)
	if err != nil {
		return err
	}

	// A stage resolves here, on the server, before any run starts and before any branch's
	// intent is read; what follows is the pinned create of the reference it names.
	branch, at := f.branch, f.at
	var resolved *resolvedStage
	if f.fromStage() {
		if resolved, err = resolveStage(ctx, op, subject, findings.StepResolve, ref, scope, reg); err != nil {
			return err
		}
		branch, at = resolved.block.Branch, resolved.block.At
		opts.note("%s", resolved.block.Line())
	}
	if f.dryRun {
		return withStage(runCreateDryRun(ctx, opts, op, subject, stage.Read, branch, at, scope, reg, probes), resolved)
	}

	// The server reads, takes the snapshot, compiles and files before any run starts, so
	// the run begins at the host check and reads nothing (R-11): every refusal here is the
	// command's document, and no run starts.
	compiled, err := readTakeCompile(ctx, opts, op, subject, stage.Read, branch, at, scope, reg, probes)
	if err != nil {
		return withStage(err, resolved)
	}
	// The input above the output, before the run's start (R-09).
	opts.note("%s", snapshotStoredLine(compiled.snapshot.id, compiled.snapshot.path))
	opts.note("%s", bundleStoredLine(compiled.bundleID, compiled.bundlePath))

	// Compiled already: the run takes the bundle and the snapshot by id and starts at the
	// host check. It follows nothing, whatever the reference (019).
	in := provision.ProvisionInput{
		Source:     wire.SourceIntent,
		Branch:     branch,
		At:         at,
		BundlePath: compiled.bundlePath,
		BundleID:   compiled.bundleID,
		ObservedAt: compiled.observedAt,
		SnapshotID: compiled.snapshot.id,
		Version:    opts.version(),
		Scope:      scope,
	}
	// The run records the stage as data, and branches on nothing of it.
	if resolved != nil {
		in.Stage = resolved.record
	}
	return withStage(compiled.carried(runProvision(ctx, opts, op, subject, in)), resolved)
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
		return dryRunReport(ctx, opts, op, subject, reg, paths, &cr.snapshot, cr.bundlePath, cr.bundleID, nil, cr.findings)
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

// runCreateDryRun reads, takes the snapshot, compiles and files the bundle in this
// process, as the create does, then reports what a real create would do; it never dials
// the workflow service. Read and compile are the stage commands' own pipelines, so a dry
// run refuses exactly what `intent read` and `twin compile` would, under the same
// identifiers. The snapshot and the bundle are filed as the create files them, so the
// report's snapshot and bundle are there to inspect (FR-014). probes is the request's list,
// which the snapshot carries (016).
func runCreateDryRun(ctx context.Context, opts *options, op string, subject *findings.Subject, read readFunc, branch, at, scope string,
	reg *psp.Registry, probes []probe.Probe) error {
	compiled, err := readTakeCompile(ctx, opts, op, subject, read, branch, at, scope, reg, probes)
	if err != nil {
		return err
	}
	return dryRunReport(ctx, opts, op, subject, reg, compiled.paths, &compiled.snapshot, compiled.bundlePath, compiled.bundleID,
		compiled.read, compiled.findings)
}

// readFunc is stage.Read's shape: what a create reads its intent through. The create
// passes stage.Read; a tier-1 test, which has no Infrahub in this package, passes its own.
type readFunc func(ctx context.Context, branch, at, scope string, reg *psp.Registry, observedAt string) (*ctm.CTM, findings.List, error)

// filedSnapshot is a snapshot a command filed, as its stored: line names it.
type filedSnapshot struct {
	id, path string
}

// compiledRead is a create's read once taken, compiled and filed on the server: what the
// run is started with, and what the dry run reports.
type compiledRead struct {
	paths      lab.Paths
	snapshot   filedSnapshot
	bundleID   string
	bundlePath string
	// files are the bundle's, as the compile produced them: a step's target (019).
	files map[string][]byte
	// observedAt is the read's time, which the twin records.
	observedAt string
	read       *readSummary
	// findings are the read's and the compile's, each at its step: none refuses.
	findings findings.List
}

// readTakeCompile is the create's one path from a reference to a filed bundle (D-011),
// shared by the create and its dry run: the state root; observed_at captured; the read,
// bounded by stage.ReadTimeout; the snapshot taken and filed; the compile; the bundle
// filed (R-11). Each refusal, and each step that cannot run, is the command's document,
// returned as the error, at read or compile as the run's own steps placed them. A refused
// read files nothing. The snapshot carries probes, the request's one list (016). A compile
// refused after a clean read leaves the snapshot filed, and
// its document and its text answer name it, since the input validated and only the output
// was refused (R-05). An Infrahub that fails or times out during the read is
// operation.failed at read, at once: no retry and no heartbeat stand between a create and
// its read (FR-010).
func readTakeCompile(ctx context.Context, opts *options, op string, subject *findings.Subject, read readFunc,
	branch, at, scope string, reg *psp.Registry, probes []probe.Probe) (*compiledRead, error) {
	paths, err := opts.paths()
	if err != nil {
		return nil, failAt(op, subject, findings.StepRead, findings.StepRead, "%v", err)
	}

	// Every finding is placed at its step, and a step that could not run names the object the
	// run's own read and compile name, so the server reports as the run did.
	//
	// Captured before the first request, so observed_at is never later than anything the
	// read could have seen.
	observedAt := time.Now().UTC().Format(stage.ObservedAtFormat)
	c, list, err := read(ctx, branch, at, scope, reg, observedAt)
	if err != nil {
		return nil, failAt(op, subject, findings.StepRead, "branch "+branch, "%v", err)
	}
	list = list.AtStep(findings.StepRead)
	if c == nil {
		return nil, finish(op, subject, list)
	}

	// The input is filed before the output: a refused compile leaves it to inspect. The
	// stores' refusals are the compile step's, a corrupt snapshot entry's as a corrupt
	// bundle entry's (contracts/cli.md, "018: snapshots", Identifiers), where the run's
	// compile step filed the sidecar this replaces.
	snap, snapPath, taken, err := takeSnapshot(ctx, paths, findings.StepCompile, c, probes)
	if err != nil {
		return nil, failAt(op, subject, findings.StepCompile, paths.Snapshots, "%v", err)
	}
	if taken.Rejected() {
		return nil, finish(op, subject, append(list, taken...))
	}
	cr := &compiledRead{paths: paths, snapshot: filedSnapshot{id: snap.ID, path: snapPath}, observedAt: observedAt}
	if err := cr.compileAndFile(ctx, opts, op, subject, c, snap.Probes, reg, list); err != nil {
		return nil, err
	}
	cr.read = &readSummary{counts: intent.Summarize(c), packages: intent.DevicesByPackage(c, reg), envelope: c.Envelope}
	return cr, nil
}

// compileAndFile compiles c and decls, the CTM and the probes of the snapshot cr names, with
// the probe packages beside reg (016), and files the bundle under the
// state root, after list, the findings before the compile: what a create from a read and a
// create from a snapshot share once the snapshot is filed. Each refusal, and each step that
// cannot run, is the command's document at compile, naming the snapshot, which stays filed,
// since its CTM validated and only the output was refused (R-05); the text answer names it
// too, by its stored line.
func (cr *compiledRead) compileAndFile(ctx context.Context, opts *options, op string, subject *findings.Subject, c *ctm.CTM,
	decls []probe.Probe, reg *psp.Registry, list findings.List) error {
	packages, err := opts.probes()
	if err != nil {
		return cr.refused(opts, loadFailureAt(op, subject, findings.StepCompile, err))
	}
	files, id, compiled := stage.Compile(c, decls, reg, packages)
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
// path of its entry, left to inspect (FR-010, FR-014). A refused read, a refused take and a
// snapshot refused at resolve by its own rules never reach here: none leaves one filed. A
// step's snapshot target refused for its scope or mapping does (targetUnheld, 019): it was
// filed before it was judged.
func (cr *compiledRead) refused(opts *options, err error) error {
	opts.note("%s", snapshotStoredLine(cr.snapshot.id, cr.snapshot.path))
	return cr.carried(err)
}

// carried puts what the server took and compiled before any run on the document err
// holds, whatever it reports: the snapshot's id once the take completed, the bundle's once
// it was filed, and the read's and the compile's findings before the run's own, which the
// run, starting at the host check, no longer reports.
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
