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
