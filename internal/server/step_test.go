package server

import (
	"testing"
	"time"

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
	in := provision.StepInput{
		From: wire.StepSide{Waypoint: &wire.WaypointRef{Series: "demo", Sequence: 1}, BundleID: fromID},
		To:   wire.StepSide{Waypoint: &wire.WaypointRef{Series: "demo", Sequence: 2}, BundleID: toID},
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
		"stepped":   "stepped to waypoint demo/2 (bundle ee291b0f…) in 71.2s: push s1 2.4s",
		"unchanged": "unchanged; the record moves to waypoint demo/2 (bundle ee291b0f…) in 1.8s",
		"diverged": "diverged towards waypoint demo/2 (bundle ee291b0f…) at phase push: landed s1; not landed e1 (push.refused); " +
			"the twin is up at waypoint demo/1 (bundle 348fd934…); fylgja twin destroy clears it",
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
