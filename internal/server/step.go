package server

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"path/filepath"
	"strings"
	"time"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/stages"
	"github.com/happypathnetworking/fylgja/internal/step"
	"github.com/happypathnetworking/fylgja/internal/verify"
)

type stepFlags struct {
	// stage is --stage as given, <branch>/<label>: the target, in place of the next stage
	// of the twin's proposed change.
	stage string
	// stageGiven is whether --stage was given at all, apart from its value: an explicit empty
	// one is a reference refused, not one left out (M4's --interval= precedent, a flag twin
	// create had until 019).
	stageGiven bool
	// snapshot is --snapshot as given (019): the target, a snapshot id the store holds, or the
	// path of the file the request carries. snapshotGiven is whether it was given at all, as
	// stageGiven is.
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
	// probes is --probes as given (016): the probe file a stage target's take carries in
	// place of the kind's, refused beside --snapshot.
	probes probesArg
}

// fromStage is whether the step names a stage: --stage given, whatever its value, or a value
// set without the flag, as a caller building the flags sets it.
func (f *stepFlags) fromStage() bool {
	return f.stageGiven || f.stage != ""
}

// fromSnapshot is whether the step names a snapshot, as fromStage is whether it names a
// stage.
func (f *stepFlags) fromSnapshot() bool {
	return f.snapshotGiven || f.snapshot != ""
}

// runTwinStep steps the running twin. files are the request's: a snapshot file beside a
// --snapshot that is a path, and none otherwise. Everything up to the run is decided here,
// each refusal ending the command with its document: --stage beside --snapshot, then the
// files' shape, before any connection; --stage as given; the packages; no target for a
// twin whose record names no stage, read from the twin directory before any connection,
// after the refusals that record alone decides (019, research R-08 as amended); a
// rehearsal in flight, asked of the workflow service before
// anything else is read, since the twin and the host are its own (015; T080); the host,
// whose twin must name a snapshot and not be diverged. Then the target: --snapshot's,
// resolved, compiled and filed as twin create --snapshot builds one, with no request to
// Infrahub (019, research R-04); or a stage of any proposed change, found on the given
// reference's branch, or with none given the next stage of the record's own (014: research
// R-16; 019, research R-07), with stage list's stage.twin.moved beside it when the record's
// stage of that proposed change has moved, and the target's resolution, read, compile and
// filing on stage plan's path. Either target names the record's scope and mapping, or is
// refused before any run (targetUnheld). Then the from bundle out of the store; the step
// between the two; the host check on the target and containerlab's plan for the lab, both in
// this process as a dry run reads them; and the rules on that plan. Then the dry run reports,
// or the run starts. Once the target is chosen, every document the command ends with carries
// what it had found by then, a failure's included.
func runTwinStep(ctx context.Context, opts *options, f *stepFlags, files []api.File) error {
	const op = findings.OpTwinStep
	subject := &findings.Subject{Snapshot: f.snapshot}

	// A snapshot is the target, so --stage beside it is meaningless: the server's refusal at
	// start, exit 2, as create's snapshot guards are (019, research R-04), and before the
	// files' shape, since a client sends no file beside it.
	if f.fromSnapshot() && f.fromStage() {
		return snapshotConflict(op, subject, "--stage", "--stage is meaningless with --snapshot: the snapshot is the target")
	}
	if f.fromSnapshot() && f.probes.given {
		return probesConflict(op, subject)
	}
	if refused := snapshotFiles(op, subject, f.fromSnapshot(), f.snapshot, files); refused != nil {
		return refused
	}
	var given *stages.Ref
	if f.fromStage() {
		ref, refused := stageGuards(op, subject, findings.StepStart, f.stage, nil)
		if refused != nil {
			return refused
		}
		given = &ref
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
	// anything is read, as a create refuses it: at read, or at compile for a snapshot, whose
	// step reads no intent, as twin create --snapshot places it.
	reg, err := psp.Load(opts.pspDir)
	if err != nil {
		at := findings.StepRead
		if f.fromSnapshot() {
			at = findings.StepCompile
		}
		return loadFailureAt(op, subject, at, err)
	}
	paths, err := opts.paths()
	if err != nil {
		return failAt(op, subject, findings.StepResolve, findings.StepResolve, "%v", err)
	}
	if refused := stepNoTarget(f, paths); refused != nil {
		return finish(op, subject, findings.List{*refused})
	}
	if f.dryRun {
		opts.note("dry run: no lab, container, twin directory or run is changed")
	} else if refused := rehearsalHolds(ctx, opts, op, subject); refused != nil {
		return refused
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
	// The record as inspected is held to the rule the file read first was: one written
	// between the two names no stage either, and has no next stage.
	if given == nil && !f.fromSnapshot() {
		if refused := noTarget(rec); refused != nil {
			return finish(op, subject, findings.List{*refused})
		}
	}
	// Every read the step makes is under the scope the twin records, never the server's
	// default (017; FR-020): the target's resolution, its staleness and its read, each of
	// which the proposed change found under it carries. A snapshot's is read nowhere.
	scope := rec.Provenance.Scope
	subject.Scope = scope
	opts.note("%s", stepTwinLine(rec))
	if f.fromSnapshot() {
		return stepToSnapshot(ctx, opts, f, op, subject, reg, paths, acts, rec, files)
	}

	// The request's one probe list, which the target's take carries (016): read before the
	// target's proposed change is found, and only for a stage, since a snapshot carries its
	// own.
	probes, err := readProbes(ctx, opts, op, subject, f.probes)
	if err != nil {
		return err
	}

	// The target's proposed change, found once by the given reference's source branch, or by
	// the record's stage's when none is given (steps 1–3 and the head's at; 019, research
	// R-07), and the target chosen among its stages; then the target resolved (steps 4–9),
	// read, compiled and filed as stage plan builds a stage.
	reader, err := intent.StageReaderFromEnv()
	if err != nil {
		return failAt(op, subject, findings.StepResolve, op, "%v", err)
	}
	// One stamper for the whole step, so each branch's conformance is checked once.
	stamper := newIntentStamper()
	branch := ""
	if given != nil {
		branch = given.Branch
	} else {
		branch = rec.Stage.ProposedChange.Branch
	}
	ch, list, err := stages.Find(ctx, reader, stamper, branch, scope)
	if err != nil {
		return failAt(op, subject, findings.StepResolve, op, "%v", err)
	}
	if list.Rejected() {
		return finish(op, subject, list)
	}
	view := recordView(rec)
	target, _, list := stages.Target(ch, view, rec.Provenance.Branch, rec.Provenance.At, given)
	if list.Rejected() {
		return finish(op, subject, list)
	}
	// The record's stage moved under the twin is stage list's warning, beside the target's
	// findings: the step goes from the bundle the record holds whatever its stage now
	// resolves to, so it refuses nothing. Moved says nothing when the target is in another
	// proposed change than the record's stage, and a record naming no stage has no view.
	if view != nil {
		list = append(list, stages.Moved(ch, *view)...)
	}
	subject.Stage = target.String()

	packages, err := opts.probes()
	if err != nil {
		return loadFailureAt(op, subject, findings.StepCompile, err)
	}
	built := stages.Build(ctx, reader, stamper, reg, ch, target, stagePipeline(paths, probes, packages), time.Now().UTC())
	list = append(list, built.Findings...)
	var resolved *resolvedStage
	if r := built.Resolved; r != nil {
		resolved = &resolvedStage{block: r.Block(), record: r.StageRef()}
		subject.Branch, subject.At = r.Branch, r.At
		opts.note("%s", resolved.block.Line())
	}
	if built.Status != stages.PlanCompiled {
		doc := findings.NewDocument(op, subject, list)
		// An Infrahub that cannot be reached and M1's precision rule keep M10's exit 2.
		if built.Status == stages.PlanFailed || carriesRule(built.Findings, findings.RuleAtPrecision) {
			doc.Status = findings.StatusError
		}
		if resolved != nil {
			doc.Stage = &resolved.block
		}
		return &result{doc: doc}
	}
	// The stage's scope and mapping are its bundle's, its snapshot's envelope copied into the
	// manifest: resolved and read under the record's scope, it differs only by a mapping that
	// moved since the twin was created (a build whose reader moved).
	var m compiler.Manifest
	if err := json.Unmarshal(built.Bundle.Files[compiler.ManifestFile], &m); err != nil {
		return withStage(withFound(failAt(op, subject, findings.StepResolve, built.Bundle.ID,
			"reading bundle %s's manifest: %v", built.Bundle.ID, err), list), resolved)
	}
	if refused := targetUnheld(rec, m.Provenance.Scope, wire.Mapping(m.Provenance.Mapping), target.String(),
		"stage "+target.String()); refused != nil {
		return withStage(finish(op, subject, append(list, *refused)), resolved)
	}
	return withStage(stepTo(ctx, opts, f, op, subject, reg, paths, acts, rec, stageTarget(built), list), resolved)
}

// targetUnheld is the refusal of a step whose target names another scope than the record's
// provenance, or a mapping any field of which differs from the record's, or nil (019,
// research R-06; FR-015): a twin's scope and mapping are fixed when it is created, since a
// step that diverges keeps the record's provenance in the record it writes, and a target read
// under another would leave a twin whose nodes no read of its record's could give.
// step.twin.unsteppable, rejection at resolve, its object the target as the command names
// it, the snapshot's id or the stage's reference; name is the target's side name, snapshot
// <short>… or stage <branch>/<label>. Both are named, the record's first, each mapping as
// reader, model and version. A snapshot target's is judged on its envelope before its
// compile, so its bundle is never filed; a stage target's on its bundle's manifest, after
// stages.Build and before the host check. The branch is not the twin's for life: a target
// of any branch steps (FR-016).
func targetUnheld(rec *wire.TwinRecord, scope string, mapping wire.Mapping, object, name string) *findings.Finding {
	held := rec.Provenance
	if scope == held.Scope && mapping == held.Mapping {
		return nil
	}
	words := func(m wire.Mapping) string { return m.Reader + " " + m.Model + " " + m.Version }
	return &findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepTwinUnsteppable, Object: object,
		Step: findings.StepResolve, Message: fmt.Sprintf("the twin's record names scope %s and mapping %s; %s names scope %s "+
			"and mapping %s; a twin's scope and mapping are fixed when it is created; fylgja twin destroy and create again "+
			"to change them", held.Scope, words(held.Mapping), name, scope, words(mapping))}
}

// stepTarget is what a step goes to, however it was chosen (019, research R-04;
// data-model §2): the side's name as step.Between names it (R-05), the stage, nil for a
// snapshot, the snapshot, the compiled and filed bundle, the branch and the at it was read
// at, verbatim, "" when unpinned, and when its intent was observed. stepTo and stepInput
// read it alone, so the run, the record and the document are one code whatever the target.
type stepTarget struct {
	name       string
	stage      *wire.StageRef
	snapshotID string
	bundle     step.Bundle
	at, branch string
	observedAt string
}

// stepToSnapshot is the step to the snapshot --snapshot names (019, research R-04;
// data-model §2), once the twin is judged and its line printed: its target built
// (snapshotTarget), then the step, as a stage's.
func stepToSnapshot(ctx context.Context, opts *options, f *stepFlags, op string, subject *findings.Subject, reg *psp.Registry,
	paths lab.Paths, acts *lab.Activities, rec *wire.TwinRecord, files []api.File) error {
	target, list, err := snapshotTarget(ctx, opts, op, subject, reg, paths, rec, f.snapshot, files)
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
// error. No request reaches Infrahub: nothing here builds an intent client, and a snapshot of
// any branch is a target, but of the record's scope and mapping alone (targetUnheld), judged
// before the compile.
func snapshotTarget(ctx context.Context, opts *options, op string, subject *findings.Subject, reg *psp.Registry,
	paths lab.Paths, rec *wire.TwinRecord, arg string, files []api.File) (stepTarget, findings.List, error) {
	s, path, err := resolveSnapshot(ctx, paths, op, subject, arg, files)
	if err != nil {
		return stepTarget{}, nil, err
	}
	// The document names what the snapshot is of from here on, as a stage step's names the
	// reference its target resolved to.
	env := s.CTM.Envelope
	subject.Branch, subject.At = env.Branch, env.At
	opts.note("target: snapshot %s (%s)", shortID(s.ID), branchRef(env.Branch, env.At, s.ObservedAt))

	cr := &compiledRead{paths: paths, snapshot: filedSnapshot{id: s.ID, path: path}, observedAt: s.ObservedAt}
	// Its scope and mapping, on the envelope before the compile: a refused target's bundle is
	// never filed. The snapshot stays filed, named as a refused compile names it.
	name := wire.StepSide{SnapshotID: s.ID}.Name()
	if refused := targetUnheld(rec, env.Scope, wire.Mapping(env.Mapping), s.ID, name); refused != nil {
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
// 019, research R-05): a stage twin by its stage, pinned at its at, as since 014; a twin that
// names no stage by its snapshot, its branch and its at, or the time it was read when it has
// none, as twin show's kind line names it.
//
//	twin: stage change-1/sealed (snapshot 576933ec…, bundle f764e1fa…), pinned at …; 3 nodes
//	twin: snapshot 576933ec… (bundle f764e1fa…), branch fylgja-test-readme, read at …; 3 nodes
func stepTwinLine(rec *wire.TwinRecord) string {
	nodes := plural(len(rec.Nodes), "node")
	if rec.Stage != nil {
		return fmt.Sprintf("twin: stage %s (snapshot %s, bundle %s), pinned at %s; %s", rec.Stage.Name(), shortSnapshot(rec),
			shortID(rec.BundleID), rec.Provenance.At, nodes)
	}
	observed := ""
	if rec.ObservedAt != nil {
		observed = *rec.ObservedAt
	}
	return fmt.Sprintf("twin: snapshot %s (bundle %s), %s; %s", shortSnapshot(rec), shortID(rec.BundleID),
		branchRef(rec.Provenance.Branch, rec.Provenance.At, observed), nodes)
}

// stageTarget is the target a stage step goes to, from stage plan's build of the stage,
// compiled and filed, and its resolution: named by its reference, <branch>/<label>, as stage
// plan names it.
func stageTarget(built stages.PlanStage) stepTarget {
	r := built.Resolved
	return stepTarget{name: built.Ref.String(), stage: r.StageRef(), snapshotID: built.SnapshotID, bundle: *built.Bundle,
		at: r.At, branch: r.Branch, observedAt: built.ObservedAt}
}

// recordSide is the step's from side, the record's own: its stage, its snapshot, none when
// the record names none, its bundle and its at.
func recordSide(rec *wire.TwinRecord) wire.StepSide {
	return wire.StepSide{Stage: rec.Stage, SnapshotID: recordSnapshot(rec), BundleID: rec.BundleID, At: rec.Provenance.At}
}

// betweenName is a side as step.Between names it (R-05): a stage by its reference alone,
// <branch>/<label>, as stage plan names it, and any other side by its Name(), snapshot
// <short>….
func betweenName(s wire.StepSide) string {
	if s.Stage != nil {
		return s.Stage.Name()
	}
	return s.Name()
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

// stepScopeUnknown is the refusal of a stage twin whose record is of twin.json 7 or earlier,
// or of 8 or later naming a scope that is not tag:<name> or a mapping twin.json 8 cannot
// hold, or nil for one naming a scope and a mapping (017): every read a step makes is under
// the record's scope, so a record naming none cannot step, as a record of 5 or earlier
// naming M10's waypoint cannot (provision.Ineligible). No build of this tree writes a record
// of 8 or later with another scope or such a mapping (NewRecord and NewStepRecord refuse
// one), so such a record was edited by hand; read under it, the stage's resolution and
// read would filter by a tag no scope names and fail at read, and a step that diverges
// keeps the record's provenance in the record it writes, which NewStepRecord refuses,
// failing the record activity with the nodes changed and twin.json still ready at the from
// stage. Each field of the mapping it fails is named, in twin show's order (mappingUnheld).
// It is the command's refusal alone, before any Infrahub read and any run: the run's second
// lock reads records of 4 and 5 in its recorded histories, which must replay unchanged, and
// a worker of this build writes 10.
func stepScopeUnknown(rec *wire.TwinRecord) *findings.Finding {
	refuse := func(message string) *findings.Finding {
		return &findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepTwinUnsteppable, Object: rec.BundleID,
			Step: findings.StepResolve, Message: message}
	}
	if !scopeRecorded(rec) {
		return refuse("the twin was created from a record version this build no longer reads " +
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
// 7 or earlier is refused naming its version, while a bundle twin, whose record carries its
// manifest's scope and mapping, passes those and is refused here. It is the command's
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

// stepNoTarget is the refusal of a step given no target, --stage and --snapshot both left
// out, of a twin whose record names no stage, or nil (019, research R-08): a twin built from
// a branch or a snapshot, or stepped to a snapshot, has no next stage, so a target is
// required. The record is read from the twin directory, a file read, before rehearsalHolds
// dials the workflow service and before the host is inspected, so the refusal reaches
// nothing (FR-014). A record no target can step is refused for itself first, in the order
// the step gives its refusals once the host is inspected (R-08 as amended; FR-012):
// Ineligible's two record cases (a diverged twin, a record naming M10's waypoint), then
// stepScopeUnknown, then stepUnsourced. A twin whose lab is gone still meets the no-target
// refusal first, since finding that needs the host's inspection. An absent or unreadable
// record, an orphan's, or one naming a stage, is nil, and the step goes on as before 019: a
// rehearsal's host, holding no record during its baseline's provision and a staged record
// after, still meets run.in_flight first, since a rehearsal's records always name a stage.
func stepNoTarget(f *stepFlags, paths lab.Paths) *findings.Finding {
	if f.fromStage() || f.fromSnapshot() {
		return nil
	}
	rec, err := lab.ReadRecord(paths.TwinJSON)
	if err != nil || rec.Stage != nil {
		return nil
	}
	// Ineligible over a host whose lab and twin directory are both present gives its record
	// cases alone, in its own words.
	present := wire.HostReport{LabPresent: true, TwinDirPresent: true, Twin: &rec}
	if refused := provision.Ineligible(present, findings.StepResolve, paths.Twin); refused != nil {
		return refused
	}
	if refused := stepScopeUnknown(&rec); refused != nil {
		return refused
	}
	if refused := stepUnsourced(&rec); refused != nil {
		return refused
	}
	return noTarget(&rec)
}

// noTarget is step.target.unknown for a record naming no stage, rejection at resolve, its
// object the record's bundle (stages.NoTargetMessage); nil for one naming a stage.
func noTarget(rec *wire.TwinRecord) *findings.Finding {
	if rec.Stage != nil {
		return nil
	}
	return &findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepTargetUnknown, Object: rec.BundleID,
		Step: findings.StepResolve, Message: stages.NoTargetMessage}
}

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

	// The step, as stage plan prints it.
	s, err := step.Diff(from, target.bundle)
	if err != nil {
		return failed(failAt(op, subject, findings.StepCompare, rec.BundleID, "%v", err))
	}
	pair := step.Between(betweenName(recordSide(rec)), target.name, s)
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

// rehearsalHolds refuses a step beside a rehearsal in flight, run.in_flight naming it, before
// the host or Infrahub is read: during the baseline's provision the host holds a lab and no
// record, and after a diverged stage a diverged twin, each of which the step would otherwise
// refuse under a rule that calls the rehearsal's twin an orphan or diverged
// (contracts/rehearse-command.md; FR-007, FR-008). The workflow service is asked as the
// rehearsal's own holdingRun asks it; a dry run dials none, as twin create --dry-run does
// not, and StartStep refuses a provisioning or destroy run as before. nil when no rehearsal
// is running.
func rehearsalHolds(ctx context.Context, opts *options, op string, subject *findings.Subject) error {
	svc, err := opts.dial(ctx)
	if err != nil {
		return startFailure(op, subject, findings.StepStart, err)
	}
	defer svc.Close()
	runs, err := svc.InFlight(ctx)
	if err != nil {
		return startFailure(op, subject, findings.StepStart, err)
	}
	for _, r := range runs {
		if r.WorkflowID == provision.WorkflowRehearse {
			return &result{doc: provision.InFlightRefusal(r.WorkflowID, r.RunID).Document(op, subject)}
		}
	}
	return nil
}

// withFound carries list, what the command had found before it failed, onto the document
// err holds, first, as withStage carries a resolution's warnings onto a create's: a
// failure's document is built fresh (failAt's, startFailure's, followRun's), so without it
// a step that fails once its target is chosen would drop step.stage.skipped,
// stage.twin.moved and stage.main.moved. Only a failure passes through it, never a document
// built from list, so each finding is carried once.
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
// the run copies both into the record it writes. The to side names the target's stage, none
// for a snapshot (019).
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
	var m compiler.Manifest
	if err := json.Unmarshal(from.Files[compiler.ManifestFile], &m); err != nil {
		return provision.StepInput{}, packages, fmt.Errorf("reading bundle %s's manifest: %w", rec.BundleID, err)
	}
	for _, n := range m.Nodes {
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
		From: recordSide(rec),
		To: wire.StepSide{Stage: target.stage, SnapshotID: target.snapshotID, BundleID: target.bundle.ID, At: target.at,
			Branch: target.branch},
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
	}, packages, nil
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
// They lead a start's failure and a failure met while following too.
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
	if line == "" || res.Wait == nil {
		return line
	}
	return line + "; " + waitClause(*res.Wait)
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
// (019, research R-05): stage <branch>/<label> as M11 named it, else snapshot <short>….
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
