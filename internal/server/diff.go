package server

import (
	"context"
	"encoding/json"
	"errors"
	"reflect"
	"slices"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/probe"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/snapshot"
	"github.com/happypathnetworking/fylgja/internal/stage"
	"github.com/happypathnetworking/fylgja/internal/step"
)

// diffFlags are twin.diff's arguments (020, R-05): the two snapshots, each a snapshot id the
// store holds or the path of a snapshot file the request carries.
type diffFlags struct {
	from, to string
}

// diffSide is one side of a diff as far as it got: the flag that named it, the snapshot it
// resolved to and its store path, and the bundle it compiled to.
type diffSide struct {
	flag, arg string
	snapshot  *snapshot.Snapshot
	path      string
	bundle    *step.Bundle
}

// diff is a twin.diff under way: the two sides and what the compiles found, which every
// document it ends with carries.
type diff struct {
	from, to diffSide
	found    findings.List
}

// runTwinDiff is the step between two snapshots, pure (020, R-05; FR-011): each resolved as
// twin create --snapshot resolves one (resolveSnapshot: an id out of the store, or the
// request's file held to the CTM's own rules and filed), each compiled on the goldens' path,
// stage.Compile with the packages and the probe packages, as twin compile compiles, and its
// bundle filed; then the step between the two bundles, step.Diff, named and marshalled as
// twin step's dry run writes its diff. It dials no workflow service, reads no twin and touches
// no lab: it files the two snapshots and their two bundles and nothing else. A refusal at
// either side's resolve or compile is the document, at that step, naming the sides done so
// far; the text answer names each side's filed snapshot and bundle as it is done.
func runTwinDiff(ctx context.Context, opts *options, f *diffFlags, files []api.File) error {
	op := findings.OpTwinDiff
	switch {
	case f.from == "":
		return fail(op, nil, "--from is required")
	case f.to == "":
		return fail(op, nil, "--to is required")
	}
	if err := diffFiles(op, f, files); err != nil {
		return err
	}
	paths, err := opts.paths()
	if err != nil {
		return failAt(op, nil, findings.StepResolve, findings.StepResolve, "%v", err)
	}

	d := &diff{from: diffSide{flag: "from", arg: f.from}, to: diffSide{flag: "to", arg: f.to}}
	for _, side := range []*diffSide{&d.from, &d.to} {
		if err := d.resolve(ctx, opts, paths, side, files); err != nil {
			return err
		}
	}

	reg, err := psp.Load(opts.pspDir)
	if err != nil {
		return d.carried(loadFailureAt(op, nil, findings.StepCompile, err))
	}
	packages, err := opts.probes()
	if err != nil {
		return d.carried(loadFailureAt(op, nil, findings.StepCompile, err))
	}
	for _, side := range []*diffSide{&d.from, &d.to} {
		if err := d.compile(ctx, opts, paths, side, reg, packages); err != nil {
			return err
		}
	}

	// The step, as stage plan and twin step's dry run print it: each side named by its
	// snapshot, since neither is a stage.
	s, err := step.Diff(*d.from.bundle, *d.to.bundle)
	if err != nil {
		// Two bundles the compile just produced always read; one that does not is a defect.
		return d.carried(failAt(op, nil, findings.StepCompare, d.from.bundle.ID, "%v", err))
	}
	pair := step.Between(d.from.name(), d.to.name(), s)
	opts.note("%s", pair.Text())
	raw, err := json.Marshal(pair)
	if err != nil {
		return d.carried(failAt(op, nil, findings.StepCompare, d.from.bundle.ID, "%v", err))
	}
	doc := findings.NewDocument(op, nil, nil)
	doc.Step = findings.DiffBlock(raw)
	return d.carried(&result{doc: doc})
}

// resolve resolves side's argument to the stored snapshot, with resolveSnapshot's refusals at
// resolve, and prints the side's line and the snapshot's stored line.
func (d *diff) resolve(ctx context.Context, opts *options, paths lab.Paths, side *diffSide, files []api.File) error {
	s, path, err := resolveSnapshot(ctx, paths, findings.OpTwinDiff, nil, side.arg, sentUnder(side.arg, files))
	if err != nil {
		return d.carried(err)
	}
	side.snapshot, side.path = s, path
	env := s.CTM.Envelope
	opts.note("%s: snapshot %s (%s)", side.flag, shortID(s.ID), branchRef(env.Branch, env.At, s.ObservedAt))
	opts.note("%s", snapshotStoredLine(s.ID, path))
	return nil
}

// compile compiles side's snapshot on the goldens' path and files its bundle, as
// compiledRead.compileAndFile does a create's, and prints the bundle's stored line. A
// snapshot the other side already compiled is compiled once: the compile is a pure function
// of the snapshot, so the bundle is the same.
func (d *diff) compile(ctx context.Context, opts *options, paths lab.Paths, side *diffSide, reg *psp.Registry,
	packages *probe.Registry) error {
	op := findings.OpTwinDiff
	if side == &d.to && d.to.snapshot.ID == d.from.snapshot.ID {
		side.bundle = d.from.bundle
		opts.note("%s", bundleStoredLine(side.bundle.ID, bundle.NewDirStore(paths.Bundles).Path(side.bundle.ID)))
		return nil
	}
	files, id, compiled := stage.Compile(side.snapshot.CTM, side.snapshot.Probes, reg, packages)
	compiled = compiled.AtStep(findings.StepCompile)
	if compiled.Rejected() {
		return d.carried(finish(op, nil, compiled))
	}
	d.found = withOnce(d.found, compiled)
	store, filed, err := fileCompiled(ctx, paths.Bundles, files, id)
	if err != nil {
		return d.carried(failAt(op, nil, findings.StepCompile, paths.Bundles, "%v", err))
	}
	if filed.Rejected() {
		return d.carried(finish(op, nil, filed))
	}
	side.bundle = &step.Bundle{ID: id, Files: files}
	opts.note("%s", bundleStoredLine(id, store.Path(id)))
	return nil
}

// withOnce is list and then each finding of more it does not already hold: the two sides of
// a diff are often one intent apart, and a warning both compiles give says the same thing of
// the same object twice.
func withOnce(list, more findings.List) findings.List {
	out := append(findings.List{}, list...)
	for _, f := range more {
		if !slices.ContainsFunc(out, func(g findings.Finding) bool { return reflect.DeepEqual(f, g) }) {
			out = append(out, f)
		}
	}
	return out
}

// carried puts the sides done so far, and what the compiles found before it, on the document
// err holds, whatever it reports: each snapshot once resolved, each bundle once filed, and
// the compiles' warnings before the document's own findings. Nothing found is a rejection, so
// the document's status stands.
func (d *diff) carried(err error) error {
	var res *result
	if !errors.As(err, &res) {
		return err
	}
	doc := res.doc
	if s := d.from.snapshot; s != nil {
		doc.SnapshotFrom = s.ID
	}
	if s := d.to.snapshot; s != nil {
		doc.SnapshotTo = s.ID
	}
	if b := d.from.bundle; b != nil {
		doc.BundleFrom = b.ID
	}
	if b := d.to.bundle; b != nil {
		doc.BundleTo = b.ID
	}
	doc.Findings = withOnce(d.found, doc.Findings)
	return err
}

// name is the side as step.Between names a side that is no stage: snapshot <short>….
func (s diffSide) name() string {
	return wire.StepSide{SnapshotID: s.snapshot.ID}.Name()
}

// sentUnder is the request's file under path, alone, which diffFiles has held to be there
// when path is not a snapshot id; none for an id.
func sentUnder(path string, files []api.File) []api.File {
	for _, f := range files {
		if f.Path == path {
			return []api.File{f}
		}
	}
	return nil
}

// diffFiles holds the request's files to the one shape twin.diff takes (020): one snapshot
// file for each of --from and --to that is a path and not a snapshot id, under that path, a
// path both name sent once, and nothing else. Any other is refused before anything is parsed,
// operation.failed, as twin compile's are; no client's command sends another, and the
// sentence names the flags and nothing of a file.
func diffFiles(op string, f *diffFlags, files []api.File) error {
	named := map[string]bool{}
	for _, arg := range []string{f.from, f.to} {
		if !snapshot.IsID(arg) {
			named[arg] = true
		}
	}
	sent := map[string]bool{}
	for _, file := range files {
		if !named[file.Path] || sent[file.Path] {
			return fail(op, nil, "the request carries a file under a path neither --from nor --to gives, or one twice, where "+
				"twin diff takes each snapshot file --from and --to name, once, under that path")
		}
		sent[file.Path] = true
	}
	for _, c := range []struct{ flag, arg string }{{"--from", f.from}, {"--to", f.to}} {
		if named[c.arg] && !sent[c.arg] {
			return fail(op, nil, "the request carries no file for %s, which names a snapshot file; twin diff takes each "+
				"snapshot file --from and --to name, under that path", c.flag)
		}
	}
	return nil
}
