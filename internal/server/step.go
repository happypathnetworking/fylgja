package server

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"math"
	"path/filepath"
	"strings"
	"time"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/snapshot"
	"github.com/happypathnetworking/fylgja/internal/step"
	"github.com/happypathnetworking/fylgja/internal/verify"
)

type stepFlags struct {
	// snapshot is --snapshot as given (019): the target, a snapshot id the store holds, or the
	// path of the file the request carries. snapshotGiven is whether it was given at all,
	// apart from its value.
	snapshot      string
	snapshotGiven bool
	allowRestart  bool
	dryRun        bool
	// wait is --wait as given: the budget of the step's wait after its record.
	wait string
	// waitGiven is whether --wait was given at all, apart from its value: an explicit empty
	// one is refused, not left out (M4's --interval= rule, a flag twin create had until 019).
	waitGiven bool
	// waitS is the budget in seconds, verify.DefaultBudget's when --wait is left out.
	waitS int
}

// fromSnapshot is whether the step names a snapshot: --snapshot given, whatever its value,
// or a value set without the flag, as a caller building the flags sets it.
func (f *stepFlags) fromSnapshot() bool {
	return f.snapshotGiven || f.snapshot != ""
}

// runTwinStep steps the running twin. files are the request's: a snapshot file beside a
// --snapshot that is a path, and none otherwise. Everything up to the run is decided here,
// each refusal ending the command with its document: the files' shape, before any
// connection; --wait; the packages; no target given, before anything is read (020, research
// R-06: a record names no stage to take a next one from); the host, whose twin must be of
// twin.json 12, name a snapshot the store holds and not be diverged. Then the target:
// --snapshot's, resolved, compiled and filed as twin create --snapshot builds one, with no
// request to any source of truth (019, research R-04; 020, D-065: a step to a stage is the
// orchestrator's, which takes the stage's snapshot and steps to it by id). The target's
// snapshot names the scope and mapping the twin's does, read from the two envelopes, or is
// refused before any run (targetUnheld; 020, research R-06). Then the from bundle out of the
// store; the step between the two; the host check on the target and containerlab's plan for
// the lab, both in this process as a dry run reads them; and the rules on that plan. Then the
// dry run reports, or the run starts. Once the target is chosen, every document the command
// ends with carries what it had found by then, a failure's included.
func runTwinStep(ctx context.Context, opts *options, f *stepFlags, files []api.File) error {
	const op = findings.OpTwinStep
	subject := &findings.Subject{Snapshot: f.snapshot}
	if f.dryRun && opts.detach {
		return detachConflict(op, subject)
	}
	if refused := snapshotFiles(op, subject, f.fromSnapshot(), f.snapshot, files); refused != nil {
		return refused
	}
	waitS, refused := stepWait(op, subject, f)
	if refused != nil {
		return refused
	}
	f.waitS = waitS
	if ctx == nil {
		ctx = context.Background()
	}
	// An override package psp validate rejects is refused under its own findings before
	// anything is read, at compile, the first step that reads the packages, as twin create
	// --snapshot places it.
	reg, err := psp.Load(opts.pspDir)
	if err != nil {
		return loadFailureAt(op, subject, findings.StepCompile, err)
	}
	paths, err := opts.paths()
	if err != nil {
		return failAt(op, subject, findings.StepResolve, findings.StepResolve, "%v", err)
	}
	if refused := noTargetGiven(f); refused != nil {
		return finish(op, subject, findings.List{*refused})
	}
	if f.dryRun {
		opts.note("dry run: no lab, container, twin directory or run is changed")
	}

	// The host, read as twin show reads it, changing nothing.
	acts, err := dryRunActivities(opts, reg, paths)
	if err != nil {
		return loadFailureAt(op, subject, findings.StepResolve, err)
	}
	host, err := acts.InspectHost(ctx)
	if err != nil {
		return failAt(op, subject, findings.StepResolve, "lab "+wire.LabName, "inspecting the host: %v", err)
	}
	report := wire.HostReport{LabPresent: host.Lab.Present, Nodes: host.Lab.Nodes, TopoPaths: host.Lab.TopoPaths,
		TwinDirPresent: host.TwinDirPresent, Twin: host.Twin, TwinReadError: host.TwinReadError, Phrase: host.Describe()}
	if refused := provision.Ineligible(report, findings.StepResolve, paths.Twin); refused != nil {
		return finish(op, subject, findings.List{*refused})
	}
	rec := host.Twin
	if refused := stepScopeUnknown(rec); refused != nil {
		return finish(op, subject, findings.List{*refused})
	}
	if refused := stepUnsourced(rec); refused != nil {
		return finish(op, subject, findings.List{*refused})
	}
	held, unread := twinEnvelope(ctx, paths, rec)
	if unread != nil {
		return finish(op, subject, findings.List{*unread})
	}
	subject.Scope = rec.Provenance.Scope
	opts.note("%s", stepTwinLine(rec))
	return stepToSnapshot(ctx, opts, f, op, subject, reg, paths, acts, rec, held, files)
}

// heldEnvelope is what a step's rule reads of the snapshot the twin's record names (020,
// research R-06): its id, and its envelope's scope and mapping.
type heldEnvelope struct {
	id      string
	scope   string
	mapping wire.Mapping
}

// twinEnvelope reads the snapshot the twin's record names from the store,
// snapshots/<snapshot_id>.json, for its envelope's scope and mapping, which a step's target
// must name (020, research R-06; targetUnheld). It runs after stepUnsourced, so the record
// names one. A snapshot the store does not hold, or holds corrupt, is step.twin.unsteppable,
// rejection at resolve, its object the id: the twin's scope and mapping cannot be read, so
// no target can be judged against them.
func twinEnvelope(ctx context.Context, paths lab.Paths, rec *wire.TwinRecord) (heldEnvelope, *findings.Finding) {
	id := *rec.SnapshotID
	s, err := snapshot.NewDirStore(paths.Snapshots).Fetch(ctx, id)
	if err != nil {
		why := fmt.Sprintf("cannot be read from the store under %s (%v)", paths.Snapshots, err)
		if errors.Is(err, fs.ErrNotExist) {
			why = "the store under " + paths.Snapshots + " does not hold"
		}
		return heldEnvelope{}, &findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepTwinUnsteppable,
			Object: id, Step: findings.StepResolve, Message: fmt.Sprintf("the twin's record names snapshot %s, which %s; "+
				"a step reads the scope and mapping of the snapshot the twin was built from or last stepped to; "+
				"fylgja twin destroy clears it", id, why)}
	}
	env := s.CTM.Envelope
	return heldEnvelope{id: id, scope: env.Scope, mapping: wire.Mapping(env.Mapping)}, nil
}

// targetUnheld is the refusal of a step whose target's snapshot names another scope than the
// twin's snapshot, or a mapping any field of which differs from it, or nil (019, research
// R-06; FR-015; 020, research R-06: read from the two envelopes): a twin's scope and mapping
// are fixed when it is created, since a step that diverges keeps the record's provenance in
// the record it writes, and a target read under another would leave a twin whose nodes no
// read of its snapshot's could give. step.twin.unsteppable, rejection at resolve, its object
// the target as the command names it, the snapshot's id; name is the
// target's side name, snapshot <short>…. Both are named, the twin's first, each mapping as
// reader, model and version. A target's is judged on its envelope before its compile, so its
// bundle is never filed. The branch is not the twin's for life: a target of any branch steps
// (FR-016).
func targetUnheld(held heldEnvelope, scope string, mapping wire.Mapping, object, name string) *findings.Finding {
	if scope == held.scope && mapping == held.mapping {
		return nil
	}
	words := func(m wire.Mapping) string { return m.Reader + " " + m.Model + " " + m.Version }
	return &findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepTwinUnsteppable, Object: object,
		Step: findings.StepResolve, Message: fmt.Sprintf("the twin's snapshot %s names scope %s and mapping %s; %s names "+
			"scope %s and mapping %s; a twin's scope and mapping are fixed when it is created; fylgja twin destroy and create "+
			"again to change them", shortID(held.id), held.scope, words(held.mapping), name, scope, words(mapping))}
}

// stepTarget is what a step goes to, however it was chosen (019, research R-04;
// data-model §2): the side's name as step.Between names it (R-05), the snapshot, the compiled and filed bundle, the branch and the at it was read
// at, verbatim, "" when unpinned, and when its intent was observed. stepTo and stepInput
// read it alone, so the run, the record and the document are one code whatever the target.
type stepTarget struct {
	name       string
	snapshotID string
	bundle     step.Bundle
	at, branch string
	observedAt string
}

// stepToSnapshot is the step to the snapshot --snapshot names (019, research R-04;
// data-model §2), once the twin is judged and its line printed: its target built
// (snapshotTarget), then the step.
func stepToSnapshot(ctx context.Context, opts *options, f *stepFlags, op string, subject *findings.Subject, reg *psp.Registry,
	paths lab.Paths, acts *lab.Activities, rec *wire.TwinRecord, held heldEnvelope, files []api.File) error {
	target, list, err := snapshotTarget(ctx, opts, op, subject, reg, paths, held, f.snapshot, files)
	if err != nil {
		return err
	}
	return stepTo(ctx, opts, f, op, subject, reg, paths, acts, rec, target, list)
}

// snapshotTarget is the target of a step to the snapshot arg names, with the compile's
// findings: the snapshot resolved as twin create --snapshot resolves it (resolveSnapshot), an
// id out of the store or the request's file read, held to the CTM's own rules and filed, each
// refusal create's own at resolve; its target line; its CTM compiled and its bundle filed on
// create's path (compileAndFile), each refusal at compile as there; the target named by its
// snapshot and carrying the envelope's branch and at, verbatim, and the stored document's
// observed_at, the first take's. Each refusal is the command's document, returned as the
// error. No request reaches any source of truth, and a snapshot of any branch is a target, but
// of the twin's snapshot's scope and mapping alone (targetUnheld), judged before the compile.
func snapshotTarget(ctx context.Context, opts *options, op string, subject *findings.Subject, reg *psp.Registry,
	paths lab.Paths, held heldEnvelope, arg string, files []api.File) (stepTarget, findings.List, error) {
	s, path, err := resolveSnapshot(ctx, paths, op, subject, arg, files)
	if err != nil {
		return stepTarget{}, nil, err
	}
	// The document names what the snapshot is of from here on.
	env := s.CTM.Envelope
	subject.Branch, subject.At = env.Branch, env.At
	opts.note("target: snapshot %s (%s)", shortID(s.ID), branchRef(env.Branch, env.At, s.ObservedAt))

	cr := &compiledRead{paths: paths, snapshot: filedSnapshot{id: s.ID, path: path}, observedAt: s.ObservedAt}
	// Its scope and mapping, on the envelope before the compile: a refused target's bundle is
	// never filed. The snapshot stays filed, named as a refused compile names it.
	name := wire.StepSide{SnapshotID: s.ID}.Name()
	if refused := targetUnheld(held, env.Scope, wire.Mapping(env.Mapping), s.ID, name); refused != nil {
		return stepTarget{}, nil, cr.refused(opts, finish(op, subject, findings.List{*refused}))
	}
	if err := cr.compileAndFile(ctx, opts, op, subject, s.CTM, s.Probes, reg, nil); err != nil {
		return stepTarget{}, nil, err
	}
	target := stepTarget{name: name, snapshotID: s.ID,
		bundle: step.Bundle{ID: cr.bundleID, Files: cr.files}, at: env.At, branch: env.Branch, observedAt: s.ObservedAt}
	return target, cr.findings, nil
}

// stepTwinLine is the twin a step goes from, the line after the dry run's (contracts/cli.md;
// 019, research R-05): by its snapshot, its branch and its at, or the time it was read when it
// has none, as twin show's kind line names it; a record names no stage from 020.
//
//	twin: snapshot 576933ec… (bundle f764e1fa…), branch fylgja-test-readme, read at …; 3 nodes
func stepTwinLine(rec *wire.TwinRecord) string {
	nodes := plural(len(rec.Nodes), "node")
	observed := ""
	if rec.ObservedAt != nil {
		observed = *rec.ObservedAt
	}
	return fmt.Sprintf("twin: snapshot %s (bundle %s), %s; %s", shortSnapshot(rec), shortID(rec.BundleID),
		branchRef(rec.Provenance.Branch, rec.Provenance.At, observed), nodes)
}

// recordSide is the step's from side, the record's own: its snapshot, none when the record
// names none, its bundle and its at.
func recordSide(rec *wire.TwinRecord) wire.StepSide {
	return wire.StepSide{SnapshotID: recordSnapshot(rec), BundleID: rec.BundleID, At: rec.Provenance.At}
}

// shortSnapshot is the record's snapshot as the step's twin line names it (018; R-09): its
// short id, or none for a record naming none, a record of 8 or earlier among them.
func shortSnapshot(rec *wire.TwinRecord) string {
	if rec.SnapshotID == nil {
		return "none"
	}
	return shortID(*rec.SnapshotID)
}

// recordSnapshot is the snapshot the record names, "" for none: a step's from side.
func recordSnapshot(rec *wire.TwinRecord) string {
	if rec.SnapshotID == nil {
		return ""
	}
	return *rec.SnapshotID
}

// stepScopeUnknown is the refusal of a twin whose record is of a version this build no
// longer steps, any of 11 or earlier (020, research R-06), whose stage and rehearsal blocks
// twin.json 12 drops, or of 12 naming a scope that is not tag:<name> or a mapping twin.json
// cannot hold, or nil for a 12 naming a scope and a mapping (017). No build of this tree
// writes a 12 with another scope or such a mapping (NewRecord and NewStepRecord refuse one),
// so such a record was edited by hand: a step that diverges keeps the record's provenance in
// the record it writes, which NewStepRecord refuses, failing the record activity with the
// nodes changed and twin.json still ready. Each field of the mapping it fails is named, in
// twin show's order (mappingUnheld). It is the command's refusal alone, before the target is
// resolved and before any run: the run's second lock reads records of 1, 4 and 5 in its recorded
// histories, which must replay unchanged. twin show shows such a record naming its version,
// and twin destroy clears it.
func stepScopeUnknown(rec *wire.TwinRecord) *findings.Finding {
	refuse := func(message string) *findings.Finding {
		return &findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepTwinUnsteppable, Object: rec.BundleID,
			Step: findings.StepResolve, Message: message}
	}
	if !recordSteps(rec) {
		return refuse("the twin was created from a record version this build no longer steps " +
			"(twin.json " + rec.TwinVersion + "); fylgja twin destroy clears it")
	}
	if !scopeKnown(rec) {
		return refuse(fmt.Sprintf("the twin's record names scope %q, which is not tag:<name>, and every read a step makes "+
			"is under the record's scope; fylgja twin destroy clears it", rec.Provenance.Scope))
	}
	if named := mappingUnheld(rec.Provenance.Mapping); len(named) > 0 {
		return refuse(fmt.Sprintf("the twin's record names mapping %s, which twin.json 8 cannot hold, and a step that "+
			"diverges keeps the record's mapping in the record it writes; fylgja twin destroy clears it", strings.Join(named, ", ")))
	}
	return nil
}

// stepUnsourced is the refusal of a twin whose record names no snapshot, or nil for one that
// names one (019, research R-03): a step goes from the snapshot the twin was built from or
// last stepped to, so only a twin whose record names a snapshot steps, whatever it was
// created from. A bundle twin's record names none, since twin provision took no snapshot; a
// record of 8 has no key, written before 018; and a 9 or a 10 naming none was made by an
// earlier build's rebuild. Each is refused naming why, step.twin.unsteppable at resolve, its
// object the record's bundle. It runs after Ineligible and stepScopeUnknown, so a record of
// 11 or earlier is refused naming its version (020), while a bundle twin, whose record carries
// its manifest's scope and mapping, passes those and is refused here. It is the command's
// refusal alone, as stepScopeUnknown is: the run's second lock reads the records of its
// recorded histories, which name no snapshot and must replay unchanged.
func stepUnsourced(rec *wire.TwinRecord) *findings.Finding {
	const only = "; only a twin whose record names a snapshot steps; fylgja twin destroy clears it"
	var why string
	switch {
	case rec.Source == wire.SourceBundle:
		why = "the twin was provisioned from a bundle, which names no snapshot"
	case !snapshotRecorded(rec):
		why = "the twin was created from a record version that names no snapshot (twin.json " + rec.TwinVersion + ")"
	case rec.SnapshotID == nil:
		why = "the twin's record names no snapshot (an earlier build's rebuild made it)"
	default:
		return nil
	}
	return &findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepTwinUnsteppable, Object: rec.BundleID,
		Step: findings.StepResolve, Message: why + only}
}

// noTargetGiven is the refusal of a step given no target, --snapshot left out, or nil: a step
// always names its target (020, research R-06), since a twin's record names no stage to take
// a next one from. step.target.unknown, rejection at resolve, its object --snapshot, before
// anything is read: neither the twin directory nor the workflow service nor containerlab.
// The core keeps the id for this case alone (research §5.13); a stage, the orchestrator's,
// is stepped to by its snapshot.
func noTargetGiven(f *stepFlags) *findings.Finding {
	if f.fromSnapshot() {
		return nil
	}
	return &findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepTargetUnknown, Object: "--snapshot",
		Step: findings.StepResolve, Message: noTargetMessage}
}

// noTargetMessage is step.target.unknown's message for a step given no target.
const noTargetMessage = "twin step names its target: give --snapshot <id|file>"

// stepTo is the step once the target is compiled and filed: the from bundle, the step, the
// host check and containerlab's plan, the rules, then the dry run's report or the run. list
// is what the command has found so far, warnings alone until the host check, whose
// refusals a dry run goes on beside. Every document stepTo ends with carries it: those
// built from list (finish's, the dry run's report, the run's) by construction, and a
// failure's, built fresh, through withFound.
func stepTo(ctx context.Context, opts *options, f *stepFlags, op string, subject *findings.Subject, reg *psp.Registry,
	paths lab.Paths, acts *lab.Activities, rec *wire.TwinRecord, target stepTarget, list findings.List) error {
	// list as it stands when the failure is met, not as it was passed.
	failed := func(err error) error { return withFound(err, list) }

	// The bundle the twin was built from, out of the store, never re-resolved.
	store := bundle.NewDirStore(paths.Bundles)
	held, err := store.Has(ctx, rec.BundleID)
	if err != nil {
		return failed(failAt(op, subject, findings.StepResolve, rec.BundleID, "reading bundle %s from the store: %v", rec.BundleID, err))
	}
	if !held {
		list.AddStep(findings.Rejection, findings.StepResolve, findings.RuleStepBundleMissing, rec.BundleID, fmt.Sprintf(
			"the record names bundle %s, which the store under %s does not hold; a step starts from the bundle the twin "+
				"was built from and cannot be computed without it; fylgja twin destroy and create again", rec.BundleID, paths.Bundles))
		return finish(op, subject, list)
	}
	files, err := bundle.LoadFiles(store.Path(rec.BundleID))
	if err != nil {
		return failed(failAt(op, subject, findings.StepResolve, rec.BundleID, "reading bundle %s from the store: %v", rec.BundleID, err))
	}
	from := step.Bundle{ID: rec.BundleID, Files: files}

	// The step, as twin diff prints it.
	s, err := step.Diff(from, target.bundle)
	if err != nil {
		return failed(failAt(op, subject, findings.StepCompare, rec.BundleID, "%v", err))
	}
	pair := step.Between(recordSide(rec).Name(), target.name, s)
	opts.note("%s", pair.Text())
	diff, err := json.Marshal(pair)
	if err != nil {
		return failed(failAt(op, subject, findings.StepCompare, rec.BundleID, "%v", err))
	}

	// The host for the twin after the step, without the two refusals that name the twin
	// itself (M4's withoutPresence), as the run's step 2 checks it.
	toPath := store.Path(target.bundle.ID)
	plan, err := lab.CheckHost(ctx, acts, wire.CheckHostInput{BundlePath: toPath, BundleID: target.bundle.ID})
	if err != nil {
		return failed(failAt(op, subject, findings.StepHostCheck, findings.StepHostCheck, "host check: %s", activityMessage(err)))
	}
	checked := provision.WithoutPresence(plan.Findings)
	list = append(list, checked...)
	if checked.Rejected() && !f.dryRun {
		return finish(op, subject, list)
	}

	// containerlab's own plan for the target, against the twin directory's lab state, from
	// the store's copy: nothing of the twin directory is read but that state.
	lifecycle, err := acts.Clab.DeployPlan(ctx, filepath.Join(toPath, compiler.TopologyFile), paths.Twin)
	if err != nil {
		return failed(failAt(op, subject, findings.StepCompare, "lab "+wire.LabName, "containerlab's plan: %v", err))
	}

	in, packages, err := stepInput(f, rec, from, target, toPath, s, diff, plan, lifecycle, reg, opts.version())
	if err != nil {
		return failed(failAt(op, subject, findings.StepCompare, rec.BundleID, "%v", err))
	}
	rules := provision.PlanRules{Plan: lifecycle, Target: packages.target, From: packages.from, Changed: in.Changed,
		AllowRestart: f.allowRestart}.Findings()
	list = append(list, rules...)
	opts.note("%s", reconcileLine(lifecycle, packages.target))
	opts.note("%s", pushLine(in.PushPlan, plan.Nodes))

	if f.dryRun {
		opts.note("wait: after the record, until the twin conforms, at most %s", time.Duration(in.WaitS)*time.Second)
		return stepDryRun(opts, op, subject, in, lifecycle, plan, toPath, list)
	}
	if rules.Rejected() {
		return finish(op, subject, list)
	}
	return runStep(ctx, opts, op, subject, in, list)
}

// withFound carries list, what the command had found before it failed, onto the document
// err holds, first: a failure's document is built fresh (failAt's, startFailure's,
// followRun's), so without it a step that fails once its target is chosen would drop the
// compile's warnings. Only a failure passes through it, never a document built from list, so
// each finding is carried once.
func withFound(err error, list findings.List) error {
	var res *result
	if len(list) > 0 && errors.As(err, &res) {
		res.doc.Findings = append(append(findings.List{}, list...), res.doc.Findings...)
	}
	return err
}

// stepPackages are the support packages of both bundles' nodes as the step's rules read
// them.
type stepPackages struct {
	target, from []provision.NodePackage
}

// stepInput is the run's input from what the command decided, and both bundles' packages:
// the target's from the host check's plan, which read them from the registry; the from
// bundle's from its manifest, each node's package looked up in the registry by its id, since
// a merge package on either side refuses the step. Declared is each target node's
// package's fidelity.link_change, which the host check's plan does not carry. Each side
// names its snapshot (018; R-13): the from side the record's, and the to side the target's;
// the run copies both into the record it writes. No side names a stage (020). The flows are the probes both bundles carry, and the probes either
// carries alone are named (flowsOf; 016).
func stepInput(f *stepFlags, rec *wire.TwinRecord, from step.Bundle, target stepTarget, toPath string, s step.Step, diff []byte,
	plan wire.CheckHostResult, lifecycle wire.ReconcilePlan, reg *psp.Registry, version string) (provision.StepInput, stepPackages, error) {
	var packages stepPackages
	declared := map[string]string{}
	for _, n := range plan.Nodes {
		linkChange := ""
		if p, ok := reg.LookupID(n.PSPID); ok {
			linkChange = p.Fidelity.LinkChange
		}
		declared[n.Name] = linkChange
		packages.target = append(packages.target, provision.NodePackage{Node: n.Name, ID: n.PSPID, Mode: n.Push.Mode,
			LinkChange: linkChange})
	}
	var m, to compiler.Manifest
	if err := json.Unmarshal(from.Files[compiler.ManifestFile], &m); err != nil {
		return provision.StepInput{}, packages, fmt.Errorf("reading bundle %s's manifest: %w", rec.BundleID, err)
	}
	if err := json.Unmarshal(target.bundle.Files[compiler.ManifestFile], &to); err != nil {
		return provision.StepInput{}, packages, fmt.Errorf("reading bundle %s's manifest: %w", target.bundle.ID, err)
	}
	flows, added, dropped, err := flowsOf(m, to, plan.Nodes)
	if err != nil {
		return provision.StepInput{}, packages, err
	}
	for _, n := range m.Nodes {
		// A host names no support package (016): nothing it carries is pushed.
		if n.PSP == nil {
			continue
		}
		if p, ok := reg.LookupID(n.PSP.ID); ok {
			packages.from = append(packages.from, provision.NodePackage{Node: n.Name, ID: n.PSP.ID, Mode: p.Config.Mode,
				LinkChange: p.Fidelity.LinkChange})
		}
	}

	// An unchanged step pushes nobody, as the run does.
	pushes := []step.NodePush{}
	if !s.Unchanged {
		pushes = step.PushPlan(s, step.Lifecycle{Restarted: lifecycle.Restarted, Recreated: lifecycle.Recreated,
			Created: lifecycle.Added, Removed: lifecycle.Deleted})
	}
	return provision.StepInput{
		From:         recordSide(rec),
		To:           wire.StepSide{SnapshotID: target.snapshotID, BundleID: target.bundle.ID, At: target.at, Branch: target.branch},
		ObservedAt:   target.observedAt,
		ToBundlePath: toPath,
		Diff:         diff,
		Unchanged:    s.Unchanged,
		Plan:         lifecycle,
		PushPlan:     pushes,
		Changed:      provision.ChangesOf(s),
		AllowRestart: f.allowRestart,
		Declared:     declared,
		WaitS:        f.waitS,
		Version:      version,
		Flows:        flows,
		Added:        added,
		Dropped:      dropped,
	}, packages, nil
}

// flowsOf is the step's flows from the two bundles' manifests (016, research R-21): one
// per probe both carry, in name order, run in its a host's container towards its b host's,
// the far address b's without its prefix length, and the flow the host check rendered for
// the a host from the target's probe package; then the probes the target alone carries
// (added: hosts the reconcile creates, with no transient figure) and those the twin's bundle
// alone carries (dropped: hosts the reconcile deletes, with no flow started), each in name
// order. Each is nil when it has none, so a probe-less step's input is the one 019 started.
// A host the host check did not plan is an error: it plans every host of the target.
func flowsOf(from, to compiler.Manifest, nodes []wire.NodePlan) (flows []wire.FlowPlan, added, dropped []string, err error) {
	held := map[string]bool{}
	for _, p := range from.Probes {
		held[p.Name] = true
	}
	hosts := map[string]*wire.ProbePlan{}
	for _, n := range nodes {
		if n.Host != nil {
			hosts[n.Name] = n.Host
		}
	}
	carried := map[string]bool{}
	for _, p := range to.Probes {
		carried[p.Name] = true
		if !held[p.Name] {
			added = append(added, p.Name)
			continue
		}
		a, b := p.Hosts[0], p.Hosts[1]
		host, ok := hosts[a.Node]
		if !ok {
			return nil, nil, nil, fmt.Errorf("probe %s: the host check planned no host %s", p.Name, a.Node)
		}
		far, _, _ := strings.Cut(b.Address, "/")
		flows = append(flows, wire.FlowPlan{Probe: p.Name, From: lab.Container(a.Node), To: lab.Container(b.Node), Far: far,
			Flow: host.Flow})
	}
	for _, p := range from.Probes {
		if !carried[p.Name] {
			dropped = append(dropped, p.Name)
		}
	}
	return flows, added, dropped, nil
}

// stepWait is --wait's budget in seconds, verify.DefaultBudget's when the flag is left out,
// or its refusal as verify.wait.invalid, exit 2, at step start, before any connection: an
// empty value, one that is not a duration, and a
// negative one. A part of a second counts as a whole one, so the budget is never shorter
// than asked; --wait 0 reads once.
func stepWait(op string, subject *findings.Subject, f *stepFlags) (int, error) {
	if !f.waitGiven {
		return int(verify.DefaultBudget / time.Second), nil
	}
	refuse := func(format string, args ...any) error {
		doc := findings.RuleErrorDocument(op, subject, findings.RuleVerifyWaitInvalid, "--wait", fmt.Sprintf(format, args...))
		doc.Findings[0].Step = findings.StepStart
		return &result{doc: doc}
	}
	if f.wait == "" {
		return 0, refuse("--wait= is empty; give a duration such as --wait=2m, or leave --wait out for the default %s",
			verify.DefaultBudget)
	}
	d, err := time.ParseDuration(f.wait)
	switch {
	case err != nil:
		return 0, refuse("--wait=%s is not a duration: %v", f.wait, err)
	case d < 0:
		return 0, refuse("--wait=%s is not a duration: a budget cannot be negative", f.wait)
	}
	return int(math.Ceil(d.Seconds())), nil
}

// stepDryRun is the step's dry run: M2's memory: and host: lines from the host check,
// and the verdict over the host check's refusals and the rules'; the document carries
// dry_run over the target's nodes, and the step block with no run fields.
func stepDryRun(opts *options, op string, subject *findings.Subject, in provision.StepInput, lifecycle wire.ReconcilePlan,
	plan wire.CheckHostResult, toPath string, list findings.List) error {
	artifacts, lossy, err := manifestSummary(toPath)
	if err != nil {
		return withFound(failAt(op, subject, findings.StepHostCheck, findings.StepHostCheck, "host check: %v", err), list)
	}
	block, verdict := dryRunBlock(plan, artifacts, lossy, list)
	printDryRunHost(opts, plan)
	opts.note("verdict: %s", verdict)

	doc := findings.NewDocument(op, subject, list)
	doc.SnapshotID, doc.BundleID = in.To.SnapshotID, in.To.BundleID
	doc.DryRun = block
	doc.Step = provision.StepBlockOf(in, lifecycle)
	return &result{doc: doc}
}

// runStep starts the step run, follows it until it closes and reports how it ended. The run
// is started and followed as a provisioning run is: an interrupt before the start abandons
// it, the first after asks the run to cancel and keeps waiting for its record, and a second
// stops waiting. The command's own warnings lead the document, and the run's
// repeats of them are dropped: the run checks the host and the plan again as second locks.
// They lead a start's failure and a failure met while following too, and a detached
// answer's run.detached (020), as runProvision detaches.
func runStep(ctx context.Context, opts *options, op string, subject *findings.Subject, in provision.StepInput,
	list findings.List) error {
	svc, err := opts.dial(ctx)
	if err != nil {
		return withFound(startFailure(op, subject, findings.StepStart, err), list)
	}
	defer svc.Close()

	interrupts, err := opts.c.startFrame(provision.WorkflowStep)
	if err != nil {
		return withFound(goneBeforeStart(op, subject, provision.WorkflowStep, err), list)
	}

	runID, interrupted, err := startRun(ctx, provision.WorkflowStep,
		func(ctx context.Context) (string, error) { return svc.StartStep(ctx, in) }, interrupts)
	if err != nil {
		return withFound(startFailure(op, subject, findings.StepStart, err), list)
	}
	subject.RunID = runID
	opts.c.runFrame(provision.WorkflowStep, runID)
	if opts.detach && !interrupted {
		return detached(op, subject, provision.WorkflowStep, runID, list)
	}

	res, err := followRun(ctx, opts, svc, op, subject, provision.WorkflowStep, runID, interrupts, interrupted,
		func(ctx context.Context) (provision.StepResult, error) { return svc.ResultOfStep(ctx, runID) },
		"run cancelled; waiting for its record", nil)
	if err != nil {
		return withFound(err, list)
	}
	if line := stepClosing(in, res); line != "" {
		opts.note("%s", line)
	}
	doc := provision.StepDocument(subject, in, res)
	doc.Findings = append(append(findings.List{}, list...), withoutRepeats(res.Findings, list)...)
	return &result{doc: doc}
}

// withoutRepeats is the run's findings without those the command already reported, by
// step, rule, object and message (M4's withoutRepeatedHostCheck, over every step).
func withoutRepeats(run, reported findings.List) findings.List {
	type key struct{ step, rule, object, message string }
	seen := map[key]bool{}
	for _, f := range reported {
		seen[key{f.Step, f.Rule, f.Object, f.Message}] = true
	}
	out := findings.List{}
	for _, f := range run {
		if !seen[key{f.Step, f.Rule, f.Object, f.Message}] {
			out = append(out, f)
		}
	}
	return out
}

// reconcileLine is what containerlab's plan does to each node it touches, with its reason
// and the node's package's declaration beside it, or that it applies nothing
// (contracts/cli.md): "reconcile: restart e1 (added link; <e1's package> declares restart);
// live s1 (added link; <s1's package> declares live)". A created node declares nothing: no link
// change of its is at stake. A deleted node is named last.
func reconcileLine(plan wire.ReconcilePlan, packages []provision.NodePackage) string {
	if plan.Empty() {
		return "reconcile: nothing to apply"
	}
	byNode := map[string]provision.NodePackage{}
	for _, p := range packages {
		byNode[p.Node] = p
	}
	var parts []string
	for _, n := range plan.Nodes() {
		var why []string
		if n.Reason != "" {
			why = append(why, n.Reason)
		}
		if p, ok := byNode[n.Node]; ok && p.LinkChange != "" && n.Reported != wire.ReportedCreate {
			why = append(why, p.ID+" declares "+p.LinkChange)
		}
		part := n.Reported + " " + n.Node
		if len(why) > 0 {
			part += " (" + strings.Join(why, "; ") + ")"
		}
		parts = append(parts, part)
	}
	for _, n := range plan.Deleted {
		parts = append(parts, "delete "+n)
	}
	return "reconcile: " + strings.Join(parts, "; ")
}

// pushLine is who the step pushes and why, and who it leaves untouched (contracts/cli.md):
// "push: e1 (artifact, restarted); s1 (artifact, bootstrap); e2 untouched", or "push:
// nobody".
func pushLine(pushes []step.NodePush, nodes []wire.NodePlan) string {
	if len(pushes) == 0 {
		return "push: nobody"
	}
	pushed := map[string]bool{}
	var parts []string
	for _, p := range pushes {
		pushed[p.Node] = true
		parts = append(parts, fmt.Sprintf("%s (%s)", p.Node, strings.Join(p.Reasons, ", ")))
	}
	var untouched []string
	for _, n := range nodes {
		if !pushed[n.Name] {
			untouched = append(untouched, n.Name)
		}
	}
	line := "push: " + strings.Join(parts, "; ")
	if len(untouched) > 0 {
		line += "; " + strings.Join(untouched, ", ") + " untouched"
	}
	return line
}

// stepClosing is the run's closing line (contracts/cli.md), or "" for a run that ended
// before its stage, whose findings say why: stepped, with the times; unchanged; or diverged,
// naming the phase, each node's push, and the stage the twin is still at. After M11's
// line and its timings comes how the wait after the record ended, when it ran.
func stepClosing(in provision.StepInput, res provision.StepResult) string {
	line := m11Closing(in, res)
	if line == "" {
		return line
	}
	if res.Wait != nil {
		line += "; " + waitClause(*res.Wait)
	}
	if res.Loss != nil && len(res.Loss.Probes) > 0 {
		line += "; " + lossClause(*res.Loss)
	}
	return line
}

// lossClause is what the step's flows lost, on the closing line (016, contracts/cli.md):
// "loss n1-loop 0/312", lost over sent per probe, or how a flow with no figure ended.
func lossClause(l wire.Loss) string {
	var parts []string
	for _, p := range l.Probes {
		switch p.Outcome {
		case wire.FlowMeasured:
			parts = append(parts, fmt.Sprintf("%s %d/%d", p.Probe, p.Lost, p.Sent))
		case wire.FlowInterrupted:
			parts = append(parts, fmt.Sprintf("%s %d/%d interrupted", p.Probe, p.Lost, p.Sent))
		case wire.FlowNotStarted:
			parts = append(parts, p.Probe+" not started")
		default:
			parts = append(parts, p.Probe+" not read")
		}
	}
	return "loss " + strings.Join(parts, ", ")
}

// waitClause is how the step's wait ended, in the words the warning verify.wait.unsettled
// begins with (contracts/cli.md, twin step --wait).
func waitClause(w wire.StepWait) string {
	switch w.Outcome {
	case wire.WaitSettled:
		return "settled after " + seconds(w.AfterS)
	case wire.WaitExpired:
		return fmt.Sprintf("wait expired after %s with %s failing", seconds(w.AfterS), plural(len(w.Failing), "assertion"))
	case wire.WaitCancelled:
		return "wait cancelled after " + seconds(w.AfterS)
	}
	return "wait could not complete"
}

// m11Closing is M11's closing line, unchanged by the wait. Each side is named by its Name()
// (019, research R-05): snapshot <short>…, a side naming no stage from 020.
func m11Closing(in provision.StepInput, res provision.StepResult) string {
	to, from := in.To.Name(), in.From.Name()
	switch {
	case res.Phase != "":
		return fmt.Sprintf("diverged towards %s (bundle %s) at phase %s: %s; the twin is up at %s (bundle %s); "+
			"fylgja twin destroy clears it", to, shortID(in.To.BundleID), res.Phase, provision.Landed(res.PushPlan, " "),
			from, shortID(in.From.BundleID))
	case res.Outcome == provision.StepUnchanged:
		return fmt.Sprintf("unchanged; the record moves to %s (bundle %s) in %s", to, shortID(in.To.BundleID),
			seconds(res.Timings.WholeS))
	case res.Outcome == provision.StepStepped:
		line := fmt.Sprintf("stepped to %s (bundle %s) in %s", to, shortID(in.To.BundleID), seconds(res.Timings.WholeS))
		var parts []string
		if t := res.Timings.ReconcileS; t != nil {
			parts = append(parts, "reconcile "+seconds(*t))
		}
		if s := perNode(res.Timings.Readiness); s != "" {
			parts = append(parts, "readiness "+s)
		}
		if s := perNode(res.Timings.Push); s != "" {
			parts = append(parts, "push "+s)
		}
		if len(parts) > 0 {
			line += ": " + strings.Join(parts, "; ")
		}
		return line
	}
	return ""
}
