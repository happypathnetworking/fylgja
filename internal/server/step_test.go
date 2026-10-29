package server

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
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

// The closing line is M11's byte for byte, the wait's clause after it when the wait ran,
// whatever the step's outcome: each of the wait's four clauses on a diverged result, as on
// a stepped one, and none when the wait did not run.
func TestStepClosingCarriesTheWaitOnEveryOutcome(t *testing.T) {
	const (
		fromID = "348fd9340000000000000000000000000000000000000000000000000000abcd"
		toID   = "ee291b0f0000000000000000000000000000000000000000000000000000abcd"
	)
	change := wire.StageChange{ID: "pc-1", Branch: "change-1"}
	in := provision.StepInput{
		From: wire.StepSide{Stage: &wire.StageRef{ProposedChange: change, Label: "cabled"}, BundleID: fromID},
		To:   wire.StepSide{Stage: &wire.StageRef{ProposedChange: change, Label: "live"}, BundleID: toID},
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
		"stepped":   "stepped to stage change-1/live (bundle ee291b0f…) in 71.2s: push s1 2.4s",
		"unchanged": "unchanged; the record moves to stage change-1/live (bundle ee291b0f…) in 1.8s",
		"diverged": "diverged towards stage change-1/live (bundle ee291b0f…) at phase push: landed s1; not landed e1 (push.refused); " +
			"the twin is up at stage change-1/cabled (bundle 348fd934…); fylgja twin destroy clears it",
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
// record of 8 and a 9 or a 10 naming none are each refused naming why, step.twin.unsteppable
// at resolve, its object the record's bundle, the bundle twin first whatever its version; a 9
// or a 10 naming one passes, whatever it was created from. Given no target, a twin naming a
// snapshot and no stage is then refused by noTarget, step.target.unknown, since it has no
// next stage (research R-08); a stage twin passes it.
func TestStepRefusesARecordThatNamesNoSnapshot(t *testing.T) {
	const bundleID = "5c6c1d96aaaabbbbccccddddeeeeffff00001111222233334444555566667777"
	const only = "; only a twin whose record names a snapshot steps; fylgja twin destroy clears it"
	id := strings.Repeat("6a", 32)
	stage := &wire.StageRef{ProposedChange: wire.StageChange{ID: "pc-1", Branch: "change-1"}, Label: "cabled"}
	for _, c := range []struct {
		name string
		rec  wire.TwinRecord
		want string
	}{
		{"a bundle twin", wire.TwinRecord{TwinVersion: "10", Source: wire.SourceBundle},
			"the twin was provisioned from a bundle, which names no snapshot" + only},
		{"a bundle twin of 8", wire.TwinRecord{TwinVersion: "8", Source: wire.SourceBundle},
			"the twin was provisioned from a bundle, which names no snapshot" + only},
		{"a stage twin of 8", wire.TwinRecord{TwinVersion: "8", Source: wire.SourceIntent, Stage: stage},
			"the twin was created from a record version that names no snapshot (twin.json 8)" + only},
		{"a stage twin of 9 naming none", wire.TwinRecord{TwinVersion: "9", Source: wire.SourceIntent, Stage: stage},
			"the twin's record names no snapshot (an earlier build's rebuild made it)" + only},
		{"a branch twin of 10 naming none", wire.TwinRecord{TwinVersion: "10", Source: wire.SourceIntent},
			"the twin's record names no snapshot (an earlier build's rebuild made it)" + only},
	} {
		c.rec.BundleID = bundleID
		want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepTwinUnsteppable, Object: bundleID,
			Step: findings.StepResolve, Message: c.want}
		if f := stepUnsourced(&c.rec); f == nil || *f != want {
			t.Errorf("%s: refused %+v, want %+v", c.name, f, want)
		}
	}
	noTargetGiven := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepTargetUnknown, Object: bundleID,
		Step: findings.StepResolve, Message: "the twin names no stage, so there is no next stage to step to; " +
			"give --stage <branch>/<label> or --snapshot <id|file>"}
	for _, c := range []struct {
		name string
		rec  wire.TwinRecord
		// stageless is whether noTarget refuses it.
		stageless bool
	}{
		{"a stage twin of 9", wire.TwinRecord{TwinVersion: "9", Source: wire.SourceIntent, Stage: stage, SnapshotID: &id}, false},
		{"a stage twin of 10", wire.TwinRecord{TwinVersion: "10", Source: wire.SourceIntent, Stage: stage, SnapshotID: &id}, false},
		{"a branch twin of 10", wire.TwinRecord{TwinVersion: "10", Source: wire.SourceIntent, SnapshotID: &id,
			Provenance: wire.Provenance{Branch: "change-1"}}, true},
		{"a snapshot twin of 10", wire.TwinRecord{TwinVersion: "10", Source: wire.SourceSnapshot, SnapshotID: &id,
			Provenance: wire.Provenance{Branch: "change-1", At: "2026-10-28T09:00:00Z"}}, true},
	} {
		c.rec.BundleID = bundleID
		if f := stepUnsourced(&c.rec); f != nil {
			t.Errorf("%s: refused %+v, want it to pass", c.name, f)
		}
		f := noTarget(&c.rec)
		switch {
		case !c.stageless && f != nil:
			t.Errorf("%s: noTarget refused %+v, want it to pass", c.name, f)
		case c.stageless && (f == nil || *f != noTargetGiven):
			t.Errorf("%s: noTarget refused %+v, want %+v", c.name, f, noTargetGiven)
		}
	}
}

// A twin's scope and mapping are fixed when it is created (019, research R-06): targetUnheld
// passes a target naming both as the record does, whatever its branch, and refuses one
// naming another scope or a mapping any field of which differs, step.twin.unsteppable at
// resolve on the target, naming both in R-06's words.
func TestTargetUnheldNamesBoth(t *testing.T) {
	const snapshotID = "576933ec51da1866cdb7344a1f60ec2468c7d04aafbee42eacd171e352bd7482"
	dcim := wire.Mapping{Reader: "infrahub-dcim", Model: "opsmill/schema-library", Version: "26336e9"}
	rec := &wire.TwinRecord{TwinVersion: "10", Provenance: wire.Provenance{Branch: "change-1", Scope: "tag:fylgja", Mapping: dcim}}
	name := wire.StepSide{SnapshotID: snapshotID}.Name()
	if f := targetUnheld(rec, "tag:fylgja", dcim, snapshotID, name); f != nil {
		t.Errorf("a target of the record's scope and mapping is refused: %+v", f)
	}
	want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepTwinUnsteppable, Object: snapshotID,
		Step: findings.StepResolve, Message: "the twin's record names scope tag:fylgja and mapping infrahub-dcim " +
			"opsmill/schema-library 26336e9; snapshot 576933ec… names scope tag:other and mapping infrahub-dcim " +
			"opsmill/schema-library 26336e9; a twin's scope and mapping are fixed when it is created; fylgja twin destroy " +
			"and create again to change them"}
	if f := targetUnheld(rec, "tag:other", dcim, snapshotID, name); f == nil || *f != want {
		t.Errorf("another scope: %+v\nwant %+v", f, want)
	}
	for _, c := range []struct {
		field string
		edit  func(m *wire.Mapping)
		words string
	}{
		{"reader", func(m *wire.Mapping) { m.Reader = "netbox-dcim" }, "netbox-dcim opsmill/schema-library 26336e9"},
		{"model", func(m *wire.Mapping) { m.Model = "opsmill/other" }, "infrahub-dcim opsmill/other 26336e9"},
		{"version", func(m *wire.Mapping) { m.Version = "0f0f0f0" }, "infrahub-dcim opsmill/schema-library 0f0f0f0"},
	} {
		m := dcim
		c.edit(&m)
		f := targetUnheld(rec, "tag:fylgja", m, "change-2/linked", "stage change-2/linked")
		if f == nil || f.Object != "change-2/linked" || !strings.Contains(f.Message,
			"; stage change-2/linked names scope tag:fylgja and mapping "+c.words+"; ") {
			t.Errorf("another %s: %+v; want refused on change-2/linked naming mapping %s", c.field, f, c.words)
		}
	}
}

// A stage twin whose record is of twin.json 7 or earlier names no scope, so twin step refuses
// it naming the version, step.twin.unsteppable at resolve, its object the record's bundle
// (017); a record of 8 or later naming a scope and a mapping passes on to the step's other
// checks, one naming a scope that is not tag:<name> is refused naming the value (T097), and
// one naming a mapping twin.json 8 cannot hold is refused naming each field it fails, in
// twin show's order (T113).
func TestStepRefusesARecordThatNamesNoScope(t *testing.T) {
	const bundleID = "5c6c1d96aaaabbbbccccddddeeeeffff00001111222233334444555566667777"
	mapping := wire.Mapping{Reader: ctm.ReaderInfrahubDCIM, Model: ctm.ModelSchemaLibrary, Version: ctm.ModelVersion}
	for _, version := range []string{"8", "9", "10"} {
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
		f := stepScopeUnknown(&wire.TwinRecord{TwinVersion: "8", BundleID: bundleID, Provenance: wire.Provenance{Scope: "tag:fylgja", Mapping: m}})
		want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepTwinUnsteppable, Object: bundleID,
			Step: findings.StepResolve, Message: "the twin's record names mapping " + c.named + ", which twin.json 8 cannot hold, " +
				"and a step that diverges keeps the record's mapping in the record it writes; fylgja twin destroy clears it"}
		if f == nil || *f != want {
			t.Errorf("mapping %+v: refused %+v, want %+v", m, f, want)
		}
	}
	for _, scope := range []string{"", "fylgja", "tag:", "tag:two words"} {
		f := stepScopeUnknown(&wire.TwinRecord{TwinVersion: "8", BundleID: bundleID, Provenance: wire.Provenance{Scope: scope}})
		want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepTwinUnsteppable, Object: bundleID,
			Step: findings.StepResolve, Message: `the twin's record names scope "` + scope + `", which is not tag:<name>, ` +
				"and every read a step makes is under the record's scope; fylgja twin destroy clears it"}
		if f == nil || *f != want {
			t.Errorf("scope %q: refused %+v, want %+v", scope, f, want)
		}
	}
	for _, version := range []string{"7", "6", "2", ""} {
		f := stepScopeUnknown(&wire.TwinRecord{TwinVersion: version, BundleID: bundleID})
		want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepTwinUnsteppable, Object: bundleID,
			Step: findings.StepResolve, Message: "the twin was created from a record version this build no longer reads (twin.json " +
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
