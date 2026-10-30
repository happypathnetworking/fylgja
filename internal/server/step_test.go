package server

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
	"github.com/happypathnetworking/fylgja/internal/snapshot"
)

// Only the step's wait reads a timeout as a wait that could not complete: any other step's
// timeout keeps M2's line, and so does a wait the service cancelled before any worker took
// it, which never began.
func TestPrintEventTimeoutsOutsideTheWaitKeepM2sLine(t *testing.T) {
	for _, c := range []struct {
		event provision.Event
		want  string
	}{
		{provision.Event{Step: "reconcile", End: true, Outcome: provision.EventTimedOut, Duration: 150 * time.Second,
			Message: "activity ScheduleToClose timeout"}, "step reconcile: timed out after 150.0s: activity ScheduleToClose timeout\n"},
		{provision.Event{Step: "readiness e1", End: true, Outcome: provision.EventTimedOut, Duration: 75 * time.Second,
			Message: "activity ScheduleToClose timeout"}, "step readiness e1: timed out after 75.0s: activity ScheduleToClose timeout\n"},
		{provision.Event{Step: "observe", End: true, Outcome: provision.EventCancelled},
			"step observe: cancelled after 0.0s\n"},
	} {
		if got := captureStdout(t, func() { printEvent(testOptions(t, false), c.event) }); got != c.want {
			t.Errorf("%+v printed %q, want %q", c.event, got, c.want)
		}
	}
}

// The closing line is M11's byte for byte, each side named by its Name() since twin.json 12
// names no stage (020, research R-06), the wait's clause after it when the wait ran,
// whatever the step's outcome: each of the wait's four clauses on a diverged result, as on
// a stepped one, and none when the wait did not run.
func TestStepClosingCarriesTheWaitOnEveryOutcome(t *testing.T) {
	const (
		fromID = "348fd9340000000000000000000000000000000000000000000000000000abcd"
		toID   = "ee291b0f0000000000000000000000000000000000000000000000000000abcd"
	)
	in := provision.StepInput{
		From: wire.StepSide{SnapshotID: strings.Repeat("576933ec", 8), BundleID: fromID},
		To:   wire.StepSide{SnapshotID: strings.Repeat("9c2d01e7", 8), BundleID: toID},
	}
	took := 2.4
	results := map[string]provision.StepResult{
		"stepped": {Outcome: provision.StepStepped, Timings: wire.StepTimings{WholeS: 71.2, Push: map[string]float64{"s1": 2.4}},
			PushPlan: []wire.StepPush{{Node: "s1", Outcome: wire.PushLanded, TookS: &took}}},
		"unchanged": {Outcome: provision.StepUnchanged, Timings: wire.StepTimings{WholeS: 1.8}},
		"diverged": {Outcome: provision.StepDiverged, Phase: findings.StepPush,
			PushPlan: []wire.StepPush{{Node: "s1", Outcome: wire.PushLanded, TookS: &took},
				{Node: "e1", Outcome: wire.PushRefused, Rule: findings.RulePushRefused}}},
	}
	m11 := map[string]string{
		"stepped":   "stepped to snapshot 9c2d01e7… (bundle ee291b0f…) in 71.2s: push s1 2.4s",
		"unchanged": "unchanged; the record moves to snapshot 9c2d01e7… (bundle ee291b0f…) in 1.8s",
		"diverged": "diverged towards snapshot 9c2d01e7… (bundle ee291b0f…) at phase push: landed s1; not landed e1 (push.refused); " +
			"the twin is up at snapshot 576933ec… (bundle 348fd934…); fylgja twin destroy clears it",
	}
	failing := []wire.StepFinding{{Rule: findings.RuleVerifyNeighbor, Object: "s1:ethernet-1/3"},
		{Rule: findings.RuleVerifyNeighbor, Object: "e1:Ethernet3"}}
	clauses := []struct {
		wait   *wire.StepWait
		clause string
	}{
		{nil, ""},
		{&wire.StepWait{Outcome: wire.WaitSettled, AfterS: 1.9}, "; settled after 1.9s"},
		{&wire.StepWait{Outcome: wire.WaitExpired, AfterS: 120, Failing: failing}, "; wait expired after 120.0s with 2 assertions failing"},
		{&wire.StepWait{Outcome: wire.WaitCancelled, AfterS: 12.4}, "; wait cancelled after 12.4s"},
		{&wire.StepWait{Outcome: wire.WaitIncomplete, AfterS: 120.3, Failing: failing}, "; wait could not complete"},
	}
	for _, outcome := range []string{"stepped", "unchanged", "diverged"} {
		for _, c := range clauses {
			res := results[outcome]
			res.Wait = c.wait
			if got, want := stepClosing(in, res), m11[outcome]+c.clause; got != want {
				t.Errorf("%s with the wait %+v:\n got %q\nwant %q", outcome, c.wait, got, want)
			}
		}
	}
}

// The closing line names each side by its Name() (019, research R-05): a step towards a
// snapshot says so where a stage step names its stage, and a twin that names no stage is up
// at its snapshot.
func TestStepClosingNamesASnapshotSide(t *testing.T) {
	const (
		fromID = "348fd9340000000000000000000000000000000000000000000000000000abcd"
		toID   = "ee291b0f0000000000000000000000000000000000000000000000000000abcd"
	)
	in := provision.StepInput{
		From: wire.StepSide{SnapshotID: strings.Repeat("576933ec", 8), BundleID: fromID},
		To:   wire.StepSide{SnapshotID: strings.Repeat("9c2d01e7", 8), BundleID: toID},
	}
	took := 2.4
	for _, c := range []struct {
		res  provision.StepResult
		want string
	}{
		{provision.StepResult{Outcome: provision.StepStepped, Timings: wire.StepTimings{WholeS: 41, Push: map[string]float64{"s1": 2.4}},
			PushPlan: []wire.StepPush{{Node: "s1", Outcome: wire.PushLanded, TookS: &took}}},
			"stepped to snapshot 9c2d01e7… (bundle ee291b0f…) in 41.0s: push s1 2.4s"},
		{provision.StepResult{Outcome: provision.StepUnchanged, Timings: wire.StepTimings{WholeS: 1.8}},
			"unchanged; the record moves to snapshot 9c2d01e7… (bundle ee291b0f…) in 1.8s"},
		{provision.StepResult{Outcome: provision.StepDiverged, Phase: findings.StepPush,
			PushPlan: []wire.StepPush{{Node: "s1", Outcome: wire.PushRefused, Rule: findings.RulePushRefused}}},
			"diverged towards snapshot 9c2d01e7… (bundle ee291b0f…) at phase push: landed none; not landed s1 (push.refused); " +
				"the twin is up at snapshot 576933ec… (bundle 348fd934…); fylgja twin destroy clears it"},
	} {
		if got := stepClosing(in, c.res); got != c.want {
			t.Errorf("%s:\n got %q\nwant %q", c.res.Outcome, got, c.want)
		}
	}
}

// rehearsingService is a workflow service with a rehearsal in flight: a destroy follows the
// rehearsal's own destroy, a fylgja-destroy run of the rehearsal's, to its end before its
// own, and a create or a step is refused naming the rehearsal.
type rehearsingService struct {
	provision.Service
	// own is whether the destroy's own run reports progress before the start fails.
	own bool
}

func (s *rehearsingService) StartDestroy(_ context.Context, onEvent func(provision.Event)) (provision.DestroyRun, error) {
	onEvent(provision.Event{Notice: "cancelling rehearsal run r1; waiting for its destroy"})
	onEvent(provision.Event{Notice: "run fylgja-destroy d1"})
	onEvent(provision.Event{WorkflowID: provision.WorkflowDestroy, Step: "teardown", FindingStep: findings.StepTeardown,
		Of: provision.WorkflowRehearse})
	onEvent(provision.Event{Notice: "rehearsal run r1 closed: cancelled"})
	if s.own {
		onEvent(provision.Event{WorkflowID: provision.WorkflowDestroy, Step: "unstage", FindingStep: findings.StepUnstage})
	}
	return provision.DestroyRun{}, errors.New("the destroy run could not be followed")
}

func (s *rehearsingService) StartProvision(context.Context, provision.ProvisionInput) (string, error) {
	return "", provision.InFlightRefusal(provision.WorkflowRehearse, "r1")
}

func (s *rehearsingService) StartStep(context.Context, provision.StepInput) (string, error) {
	return "", provision.InFlightRefusal(provision.WorkflowRehearse, "r1")
}

func (s *rehearsingService) Close() {}

// twin destroy during a rehearsal (015; contracts/rehearse-command.md): it prints the
// cancel notice and follows the rehearsal's own destroy before its own, and that destroy's
// progress is not its own: a failure after it alone is a failure to start, and one after
// the destroy's own progress names the step it reached.
func TestDestroyFollowsARehearsalsDestroyFirst(t *testing.T) {
	for _, c := range []struct {
		own  bool
		step string
	}{{false, findings.StepStart}, {true, findings.StepUnstage}} {
		useService(t, &rehearsingService{own: c.own})
		var err error
		out := captureStdout(t, func() { err = runDestroy(context.Background(), testOptions(t, false)) })
		_, doc := exitOf(t, err)
		if len(doc.Findings) != 1 || doc.Findings[0].Step != c.step {
			t.Errorf("own progress %v: %+v, want a failure at %s", c.own, doc.Findings, c.step)
		}
		if !strings.HasPrefix(out, "cancelling rehearsal run r1; waiting for its destroy\nrun fylgja-destroy d1\nstep teardown: begins\n"+
			"rehearsal run r1 closed: cancelled\n") {
			t.Errorf("own progress %v: printed\n%s", c.own, out)
		}
	}
}

// A create and a step beside a rehearsal are run.in_flight naming it, exit 1, through the
// service's refusal (015).
func TestACreateAndAStepBesideARehearsalNameIt(t *testing.T) {
	useService(t, &rehearsingService{})
	opts := testOptions(t, true)
	for name, err := range map[string]error{
		"create": runProvision(context.Background(), opts, findings.OpTwinCreate, &findings.Subject{},
			provision.ProvisionInput{Source: wire.SourceIntent, Branch: "change-1"}),
		"step": runStep(context.Background(), opts, findings.OpTwinStep, &findings.Subject{}, provision.StepInput{}, nil),
	} {
		code, doc := exitOf(t, err)
		if code != findings.ExitRejected || len(doc.Findings) != 1 {
			t.Fatalf("%s: exit %d, %+v", name, code, doc)
		}
		f := doc.Findings[0]
		if f.Rule != findings.RuleRunInFlight || f.Object != provision.WorkflowRehearse || !strings.HasPrefix(f.Message, "rehearsal run r1 ") {
			t.Errorf("%s: %+v", name, f)
		}
	}
}

// Only a twin whose record names a snapshot steps (019, research R-03): a bundle twin, a
// record of 8 and a 9, a 10 or a 12 naming none are each refused by stepUnsourced naming
// why, step.twin.unsteppable at resolve, its object the record's bundle, the bundle twin
// first whatever its version; a 9, a 10 or a 12 naming one passes, whatever it was created
// from. A record of 11 or earlier never reaches it in a step, which stepScopeUnknown refuses
// first by its version (020, research R-06; TestStepRefusesARecordOfAnEarlierVersion).
func TestStepRefusesARecordThatNamesNoSnapshot(t *testing.T) {
	const bundleID = "5c6c1d96aaaabbbbccccddddeeeeffff00001111222233334444555566667777"
	const only = "; only a twin whose record names a snapshot steps; fylgja twin destroy clears it"
	id := strings.Repeat("6a", 32)
	for _, c := range []struct {
		name string
		rec  wire.TwinRecord
		want string
	}{
		{"a bundle twin", wire.TwinRecord{TwinVersion: "12", Source: wire.SourceBundle},
			"the twin was provisioned from a bundle, which names no snapshot" + only},
		{"a bundle twin of 8", wire.TwinRecord{TwinVersion: "8", Source: wire.SourceBundle},
			"the twin was provisioned from a bundle, which names no snapshot" + only},
		{"an intent twin of 8", wire.TwinRecord{TwinVersion: "8", Source: wire.SourceIntent},
			"the twin was created from a record version that names no snapshot (twin.json 8)" + only},
		{"an intent twin of 9 naming none", wire.TwinRecord{TwinVersion: "9", Source: wire.SourceIntent},
			"the twin's record names no snapshot (an earlier build's rebuild made it)" + only},
		{"a branch twin of 10 naming none", wire.TwinRecord{TwinVersion: "10", Source: wire.SourceIntent},
			"the twin's record names no snapshot (an earlier build's rebuild made it)" + only},
		{"a branch twin of 12 naming none", wire.TwinRecord{TwinVersion: "12", Source: wire.SourceIntent},
			"the twin's record names no snapshot (an earlier build's rebuild made it)" + only},
	} {
		c.rec.BundleID = bundleID
		want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepTwinUnsteppable, Object: bundleID,
			Step: findings.StepResolve, Message: c.want}
		if f := stepUnsourced(&c.rec); f == nil || *f != want {
			t.Errorf("%s: refused %+v, want %+v", c.name, f, want)
		}
	}
	for _, c := range []struct {
		name string
		rec  wire.TwinRecord
	}{
		{"an intent twin of 9", wire.TwinRecord{TwinVersion: "9", Source: wire.SourceIntent, SnapshotID: &id}},
		{"a branch twin of 10", wire.TwinRecord{TwinVersion: "10", Source: wire.SourceIntent, SnapshotID: &id,
			Provenance: wire.Provenance{Branch: "change-1"}}},
		{"a branch twin of 12", wire.TwinRecord{TwinVersion: "12", Source: wire.SourceIntent, SnapshotID: &id,
			Provenance: wire.Provenance{Branch: "change-1"}}},
		{"a snapshot twin of 12", wire.TwinRecord{TwinVersion: "12", Source: wire.SourceSnapshot, SnapshotID: &id,
			Provenance: wire.Provenance{Branch: "change-1", At: "2026-10-28T09:00:00Z"}}},
	} {
		c.rec.BundleID = bundleID
		if f := stepUnsourced(&c.rec); f != nil {
			t.Errorf("%s: refused %+v, want it to pass", c.name, f)
		}
	}
}

// A step always names its target (020, research R-06): twin.json 12 names no stage to take a
// next one from, so a step given no --snapshot is refused by noTargetGiven,
// step.target.unknown at resolve, its object --snapshot, naming the one flag a step's target
// is from 020 (a stage is the orchestrator's, stepped to by its snapshot); --snapshot, given
// with a value or given empty, passes it.
func TestStepRefusesAStepGivenNoTarget(t *testing.T) {
	want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepTargetUnknown, Object: "--snapshot",
		Step: findings.StepResolve, Message: "twin step names its target: give --snapshot <id|file>"}
	if f := noTargetGiven(&stepFlags{}); f == nil || *f != want {
		t.Errorf("no target: refused %+v, want %+v", f, want)
	}
	for name, f := range map[string]*stepFlags{
		"--snapshot=": {snapshotGiven: true},
		"--snapshot":  {snapshot: fixtureSnapshotID},
	} {
		if got := noTargetGiven(f); got != nil {
			t.Errorf("%s: refused %+v, want it to pass", name, got)
		}
	}
}

// A step given no target is refused before anything is read (020, research R-06): neither the
// twin directory, which a state root holding none would report as absent, nor the workflow
// service, which is never dialled.
func TestAStepGivenNoTargetReadsNothing(t *testing.T) {
	useStateRoot(t)
	useService(t, nil)
	code, doc := exitOf(t, runTwinStep(context.Background(), testOptions(t, true), &stepFlags{}, nil))
	want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepTargetUnknown, Object: "--snapshot",
		Step: findings.StepResolve, Message: noTargetMessage}
	if code != findings.ExitRejected || len(doc.Findings) != 1 || doc.Findings[0] != want {
		t.Errorf("exit %d, %+v; want %d and %+v alone", code, doc.Findings, findings.ExitRejected, want)
	}
}

// A twin whose record is of twin.json 11 or earlier is not stepped (020, research R-06; US2
// scenario 8; SC-004): stepScopeUnknown refuses it naming its version and twin destroy,
// step.twin.unsteppable at resolve, its object the record's bundle, before stepUnsourced, so a
// bundle twin of 11 or one naming no snapshot is refused by its version and not by its
// source; a 12 naming a scope and a mapping passes it.
func TestStepRefusesARecordOfAnEarlierVersion(t *testing.T) {
	const bundleID = "5c6c1d96aaaabbbbccccddddeeeeffff00001111222233334444555566667777"
	id := strings.Repeat("6a", 32)
	mapping := wire.Mapping{Reader: ctm.ReaderInfrahubDCIM, Model: ctm.ModelSchemaLibrary, Version: ctm.ModelVersion}
	provenance := wire.Provenance{Branch: "change-1", Scope: "tag:fylgja", Mapping: mapping}
	// first is the refusal a step meets first of the two rules, in runTwinStep's order.
	first := func(rec *wire.TwinRecord) *findings.Finding {
		if f := stepScopeUnknown(rec); f != nil {
			return f
		}
		return stepUnsourced(rec)
	}
	for _, c := range []struct {
		name string
		rec  wire.TwinRecord
	}{
		{"an intent twin of 11", wire.TwinRecord{TwinVersion: "11", Source: wire.SourceIntent, SnapshotID: &id}},
		{"a snapshot twin of 11", wire.TwinRecord{TwinVersion: "11", Source: wire.SourceSnapshot, SnapshotID: &id}},
		{"a bundle twin of 11", wire.TwinRecord{TwinVersion: "11", Source: wire.SourceBundle}},
		{"an intent twin of 11 naming none", wire.TwinRecord{TwinVersion: "11", Source: wire.SourceIntent}},
		{"an intent twin of 10", wire.TwinRecord{TwinVersion: "10", Source: wire.SourceIntent, SnapshotID: &id}},
		{"an intent twin of 8", wire.TwinRecord{TwinVersion: "8", Source: wire.SourceIntent}},
	} {
		c.rec.BundleID, c.rec.Provenance = bundleID, provenance
		want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepTwinUnsteppable, Object: bundleID,
			Step: findings.StepResolve, Message: "the twin was created from a record version this build no longer steps " +
				"(twin.json " + c.rec.TwinVersion + "); fylgja twin destroy clears it"}
		if f := first(&c.rec); f == nil || *f != want {
			t.Errorf("%s: refused %+v, want %+v", c.name, f, want)
		}
	}
	for _, source := range []string{wire.SourceIntent, wire.SourceSnapshot} {
		rec := &wire.TwinRecord{TwinVersion: lab.TwinVersion, Source: source, SnapshotID: &id, BundleID: bundleID, Provenance: provenance}
		if f := first(rec); f != nil {
			t.Errorf("a %s twin of %s: refused %+v, want it to pass", source, lab.TwinVersion, f)
		}
	}
}

// fileTwinSnapshot files the fixture CTM, observed at a fixed time and edited by edit, in the
// snapshot store under paths, as a create or a step files the snapshot a twin is built from,
// and returns its id.
func fileTwinSnapshot(t *testing.T, paths lab.Paths, edit func(e *ctm.Envelope)) string {
	t.Helper()
	c := loadCTM(t, "three-node.json", "2026-10-29T09:00:00.000000Z")
	if edit != nil {
		edit(&c.Envelope)
	}
	id, err := snapshot.NewDirStore(paths.Snapshots).Put(context.Background(), snapshot.Take(c, nil))
	if err != nil {
		t.Fatal(err)
	}
	return id
}

// A twin's scope and mapping are fixed when it is created (019, research R-06), read from the
// two envelopes (020, research R-06; US2 scenario 9): twinEnvelope reads the scope and the
// mapping of the snapshot the twin's record names out of the state root's store, and
// targetUnheld passes a target whose snapshot names both as it does, whatever its branch, and
// refuses one naming another scope or a mapping any field of which differs,
// step.twin.unsteppable at resolve on the target, naming both pairs, the twin's snapshot
// first.
func TestTargetUnheldNamesBoth(t *testing.T) {
	paths := useStateRoot(t)
	ctx := context.Background()
	twinID := fileTwinSnapshot(t, paths, nil)
	rec := &wire.TwinRecord{TwinVersion: lab.TwinVersion, SnapshotID: &twinID,
		Provenance: wire.Provenance{Branch: "fylgja-fixture", Scope: "tag:fylgja", Mapping: dcimMapping}}
	held, refused := twinEnvelope(ctx, paths, rec)
	if refused != nil {
		t.Fatalf("the twin's filed snapshot is refused: %+v", refused)
	}
	if held.id != twinID || held.scope != "tag:fylgja" || held.mapping != dcimMapping {
		t.Errorf("the twin's envelope reads %+v; want snapshot %s, scope tag:fylgja, mapping %+v", held, twinID, dcimMapping)
	}
	// judge files a target of the fixture's CTM, edited, and judges it on its stored envelope,
	// as a step to a snapshot or to a stage's filed snapshot does.
	judge := func(edit func(e *ctm.Envelope)) (string, *findings.Finding) {
		t.Helper()
		id := fileTwinSnapshot(t, paths, edit)
		s, err := snapshot.NewDirStore(paths.Snapshots).Fetch(ctx, id)
		if err != nil {
			t.Fatal(err)
		}
		env := s.CTM.Envelope
		return id, targetUnheld(held, env.Scope, wire.Mapping(env.Mapping), id, wire.StepSide{SnapshotID: id}.Name())
	}
	for name, edit := range map[string]func(e *ctm.Envelope){
		"the twin's own snapshot": nil,
		"another branch":          func(e *ctm.Envelope) { e.Branch, e.At = "change-2", "" },
	} {
		if _, f := judge(edit); f != nil {
			t.Errorf("%s, of the twin's scope and mapping, is refused: %+v", name, f)
		}
	}
	const twinWords = "scope tag:fylgja and mapping infrahub-dcim opsmill/schema-library 26336e9"
	for _, c := range []struct {
		name   string
		edit   func(e *ctm.Envelope)
		target string
	}{
		{"another scope", func(e *ctm.Envelope) { e.Scope = "tag:other" },
			"scope tag:other and mapping infrahub-dcim opsmill/schema-library 26336e9"},
		{"another reader", func(e *ctm.Envelope) { e.Mapping.Reader = "netbox-dcim" },
			"scope tag:fylgja and mapping netbox-dcim opsmill/schema-library 26336e9"},
		{"another model", func(e *ctm.Envelope) { e.Mapping.Model = "opsmill/other" },
			"scope tag:fylgja and mapping infrahub-dcim opsmill/other 26336e9"},
		{"another version", func(e *ctm.Envelope) { e.Mapping.Version = "0f0f0f0" },
			"scope tag:fylgja and mapping infrahub-dcim opsmill/schema-library 0f0f0f0"},
	} {
		id, f := judge(c.edit)
		want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepTwinUnsteppable, Object: id,
			Step: findings.StepResolve, Message: "the twin's snapshot " + shortID(twinID) + " names " + twinWords + "; snapshot " +
				shortID(id) + " names " + c.target + "; a twin's scope and mapping are fixed when it is created; " +
				"fylgja twin destroy and create again to change them"}
		if f == nil || *f != want {
			t.Errorf("%s: refused %+v\nwant %+v", c.name, f, want)
		}
	}
	// A stage target is named by its reference, its object the reference as the command names it.
	m := dcimMapping
	m.Version = "0f0f0f0"
	f := targetUnheld(held, "tag:fylgja", m, "change-2/linked", "stage change-2/linked")
	if f == nil || f.Object != "change-2/linked" || !strings.Contains(f.Message,
		"; stage change-2/linked names scope tag:fylgja and mapping infrahub-dcim opsmill/schema-library 0f0f0f0; ") {
		t.Errorf("a stage of another mapping: %+v; want refused on change-2/linked naming its mapping", f)
	}
}

// A twin whose record names a snapshot the store does not hold cannot have its scope and
// mapping read, so no target can be judged against them (020, research R-06): twinEnvelope
// refuses it, step.twin.unsteppable at resolve, its object the snapshot's id, naming the store
// and twin destroy.
func TestTwinEnvelopeRefusesASnapshotTheStoreLacks(t *testing.T) {
	paths := useStateRoot(t)
	id := strings.Repeat("6a", 32)
	rec := &wire.TwinRecord{TwinVersion: lab.TwinVersion, SnapshotID: &id,
		Provenance: wire.Provenance{Branch: "fylgja-fixture", Scope: "tag:fylgja", Mapping: dcimMapping}}
	_, f := twinEnvelope(context.Background(), paths, rec)
	want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepTwinUnsteppable, Object: id,
		Step: findings.StepResolve, Message: "the twin's record names snapshot " + id + ", which the store under " +
			paths.Snapshots + " does not hold; a step reads the scope and mapping of the snapshot the twin was built from " +
			"or last stepped to; fylgja twin destroy clears it"}
	if f == nil || *f != want {
		t.Errorf("refused %+v\nwant %+v", f, want)
	}
}

// A record of twin.json 12 or later naming a scope and a mapping passes stepScopeUnknown on to
// the step's other checks (017; 020, research R-06); one naming a scope that is not
// tag:<name> is refused naming the value (T097), and one naming a mapping twin.json 8 cannot
// hold is refused naming each field it fails, in twin show's order (T113). A record of 11 or
// earlier, one of 7 or earlier naming no scope among them, is refused naming its version,
// step.twin.unsteppable at resolve, its object the record's bundle.
func TestStepRefusesARecordThatNamesNoScope(t *testing.T) {
	const bundleID = "5c6c1d96aaaabbbbccccddddeeeeffff00001111222233334444555566667777"
	mapping := wire.Mapping{Reader: ctm.ReaderInfrahubDCIM, Model: ctm.ModelSchemaLibrary, Version: ctm.ModelVersion}
	for _, version := range []string{"12", "13"} {
		rec := &wire.TwinRecord{TwinVersion: version, BundleID: bundleID, Provenance: wire.Provenance{Scope: "tag:fylgja", Mapping: mapping}}
		if f := stepScopeUnknown(rec); f != nil {
			t.Errorf("twin.json %s: refused %+v, want it to pass", version, f)
		}
	}
	for _, c := range []struct {
		edit  func(*wire.Mapping)
		named string
	}{
		{func(m *wire.Mapping) { m.Reader = "Infrahub DCIM" }, `reader "Infrahub DCIM"`},
		{func(m *wire.Mapping) { m.Model, m.Version = "", "" }, `model "", version ""`},
		{func(m *wire.Mapping) { m.Reader, m.Model = "-dcim", "" }, `reader "-dcim", model ""`},
		{func(m *wire.Mapping) { *m = wire.Mapping{} }, `reader "", model "", version ""`},
	} {
		m := mapping
		c.edit(&m)
		f := stepScopeUnknown(&wire.TwinRecord{TwinVersion: lab.TwinVersion, BundleID: bundleID, Provenance: wire.Provenance{Scope: "tag:fylgja", Mapping: m}})
		want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepTwinUnsteppable, Object: bundleID,
			Step: findings.StepResolve, Message: "the twin's record names mapping " + c.named + ", which twin.json 8 cannot hold, " +
				"and a step that diverges keeps the record's mapping in the record it writes; fylgja twin destroy clears it"}
		if f == nil || *f != want {
			t.Errorf("mapping %+v: refused %+v, want %+v", m, f, want)
		}
	}
	for _, scope := range []string{"", "fylgja", "tag:", "tag:two words"} {
		f := stepScopeUnknown(&wire.TwinRecord{TwinVersion: lab.TwinVersion, BundleID: bundleID, Provenance: wire.Provenance{Scope: scope}})
		want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepTwinUnsteppable, Object: bundleID,
			Step: findings.StepResolve, Message: `the twin's record names scope "` + scope + `", which is not tag:<name>, ` +
				"and every read a step makes is under the record's scope; fylgja twin destroy clears it"}
		if f == nil || *f != want {
			t.Errorf("scope %q: refused %+v, want %+v", scope, f, want)
		}
	}
	for _, version := range []string{"11", "10", "8", "7", "6", "2", ""} {
		f := stepScopeUnknown(&wire.TwinRecord{TwinVersion: version, BundleID: bundleID,
			Provenance: wire.Provenance{Scope: "tag:fylgja", Mapping: mapping}})
		want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepTwinUnsteppable, Object: bundleID,
			Step: findings.StepResolve, Message: "the twin was created from a record version this build no longer steps (twin.json " +
				version + "); fylgja twin destroy clears it"}
		if f == nil || *f != want {
			t.Errorf("twin.json %q: refused %+v, want %+v", version, f, want)
		}
	}
}

// A step detached (020) answers at its run with what the command found before the start
// leading the document, as a followed step's carries it, then run.detached.
func TestADetachedStepCarriesWhatItFound(t *testing.T) {
	useStateRoot(t)
	_, frames, svc := detachedAnswer(t, findings.OpTwinStep)
	_, doc := detachedOf(t, frames)
	if len(doc.Findings) != 2 || doc.Findings[0] != detachedStepWarning || doc.Findings[1].Rule != findings.RuleRunDetached {
		t.Errorf("findings %+v, want the command's warning, then run.detached", doc.Findings)
	}
	if len(svc.stepped) != 1 {
		t.Errorf("%d step runs started, want 1", len(svc.stepped))
	}
}

// detach beside dry_run is run.flags.conflict before any of the step's guards, the twin's
// record and the rehearsal's among them (020).
func TestAStepRefusesDetachBesideDryRun(t *testing.T) {
	wantDetachConflict(t, findings.OpTwinStep)
}
