package rehearsal

import (
	"reflect"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

var (
	neighborN1 = wire.StepFinding{Rule: findings.RuleVerifyNeighbor, Object: "n1:ethernet-1/2",
		Message: "node n1 (172.20.20.2): port ethernet-1/2 sees no neighbour"}
	neighborN3 = wire.StepFinding{Rule: findings.RuleVerifyNeighbor, Object: "n3:ethernet-1/3",
		Message: "node n3 (172.20.20.4): port ethernet-1/3 sees no neighbour"}
	portN1 = wire.StepFinding{Rule: findings.RuleVerifyPortEnabled, Object: "n1:ethernet-1/2",
		Message: "node n1 (172.20.20.2): port ethernet-1/2 reads \"disable\""}
	recordN2 = wire.StepFinding{Rule: findings.RuleVerifyRecordHolds, Object: "n2",
		Message: "the record says n2 holds the previous bundle"}
)

func waitOf(outcome string, failing ...wire.StepFinding) *wire.StepWait {
	return &wire.StepWait{Outcome: outcome, BudgetS: 120, Reads: 3, AfterS: 4.2, Failing: failing}
}

func stepped(outcome string) *StepOutcome { return &StepOutcome{Outcome: outcome} }

func TestVerdict(t *testing.T) {
	baseline := []wire.StepFinding{neighborN1}
	for _, c := range []struct {
		name     string
		step     *StepOutcome
		wait     *wire.StepWait
		baseline []wire.StepFinding
		cut      bool
		want     Verdict
		added    []wire.StepFinding
	}{
		{"a finding the baseline had", stepped(wire.StepStepped), waitOf(wire.WaitExpired, neighborN1), baseline, false,
			VerdictPassed, nil},
		{"a finding the baseline did not have", stepped(wire.StepStepped), waitOf(wire.WaitExpired, neighborN1, neighborN3),
			baseline, false, VerdictFailed, []wire.StepFinding{neighborN3}},
		// The same object under another rule is another finding.
		{"another rule on the baseline's object", stepped(wire.StepStepped), waitOf(wire.WaitExpired, portN1), baseline, false,
			VerdictFailed, []wire.StepFinding{portN1}},
		{"a finding the baseline alone had fails nothing", stepped(wire.StepStepped), waitOf(wire.WaitSettled), baseline, false,
			VerdictPassed, nil},
		{"unchanged and settled", stepped(wire.StepUnchanged), waitOf(wire.WaitSettled), nil, false, VerdictPassed, nil},
		{"verify.record.holds is ignored if present", stepped(wire.StepStepped), waitOf(wire.WaitExpired, recordN2), nil, false,
			VerdictPassed, nil},
		{"a wait incomplete", stepped(wire.StepStepped), waitOf(wire.WaitIncomplete, neighborN3), baseline, false, VerdictError, nil},
		{"a wait cancelled", stepped(wire.StepUnchanged), waitOf(wire.WaitCancelled), nil, false, VerdictError, nil},
		{"no wait", stepped(wire.StepStepped), nil, nil, false, VerdictError, nil},
		{"cut mid-step", &StepOutcome{Outcome: outcomeCancelled, Phase: findings.StepReadiness}, nil, baseline, true, VerdictError, nil},
		{"cut after a settled wait", stepped(wire.StepStepped), waitOf(wire.WaitSettled), nil, true, VerdictError, nil},
		{"the step gave no result", nil, nil, nil, false, VerdictError, nil},
		{"rejected by its locks", &StepOutcome{Outcome: outcomeRejected, Step: findings.StepInspect}, nil, nil, false, VerdictError, nil},
		{"could not run", &StepOutcome{Outcome: outcomeError, Step: findings.StepHostCheck}, nil, nil, false, VerdictError, nil},
		{"cancelled before its stage", &StepOutcome{Outcome: outcomeCancelled, Step: findings.StepCompare}, nil, nil, false, VerdictError, nil},
		{"an outcome unknown", stepped("waiting"), waitOf(wire.WaitSettled), nil, false, VerdictError, nil},
	} {
		got, added := Classify(c.step, c.wait, c.baseline, c.cut)
		if got != c.want || !reflect.DeepEqual(added, c.added) {
			t.Errorf("%s: Classify = %s, %v; want %s, %v", c.name, got, added, c.want, c.added)
		}
	}

	// A divergence at each phase fails the stage, whatever its wait; its wait's new findings
	// are reported when it read every node.
	for _, phase := range []string{findings.StepReconcile, findings.StepReadiness, findings.StepPush, findings.StepRecord} {
		diverged := &StepOutcome{Outcome: wire.StepDiverged, Phase: phase, Step: phase}
		if got, added := Classify(diverged, waitOf(wire.WaitExpired, neighborN1, neighborN3), baseline, false); got != VerdictFailed ||
			!reflect.DeepEqual(added, []wire.StepFinding{neighborN3}) {
			t.Errorf("diverged at %s, its wait expired: %s, %v", phase, got, added)
		}
		if got, added := Classify(diverged, waitOf(wire.WaitIncomplete, neighborN3), baseline, false); got != VerdictFailed || added != nil {
			t.Errorf("diverged at %s, its wait incomplete: %s, %v", phase, got, added)
		}
		if got, _ := Classify(diverged, nil, baseline, false); got != VerdictFailed {
			t.Errorf("diverged at %s, no wait: %s", phase, got)
		}
	}

	// A step cancelled before its stage has no phase; one cancelled after it has one.
	if !(StepOutcome{Outcome: outcomeCancelled}).CancelledBeforeStage() ||
		(StepOutcome{Outcome: outcomeCancelled, Phase: findings.StepPush}).CancelledBeforeStage() ||
		(StepOutcome{Outcome: wire.StepDiverged, Phase: findings.StepPush}).CancelledBeforeStage() {
		t.Error("CancelledBeforeStage does not read a cancelled step's phase")
	}
}

// New findings keep the stage's order and drop every one the baseline has, by rule and
// object, whatever the message.
func TestNewFindings(t *testing.T) {
	moved := neighborN1
	moved.Message = "node n1 (172.20.20.2): port ethernet-1/2 sees n4 ethernet-1/1"
	got := NewFindings([]wire.StepFinding{neighborN1}, []wire.StepFinding{neighborN3, recordN2, moved, portN1})
	if want := []wire.StepFinding{neighborN3, portN1}; !reflect.DeepEqual(got, want) {
		t.Errorf("NewFindings = %v, want %v", got, want)
	}
	if got := NewFindings(nil, nil); got != nil {
		t.Errorf("nothing failing gives %v", got)
	}
}

func TestStop(t *testing.T) {
	for v, want := range map[Verdict]bool{
		VerdictPassed: false, VerdictBaseline: false, VerdictRefused: false,
		VerdictFailed: true, VerdictError: true, VerdictNotReached: true,
	} {
		if Stop(v) != want {
			t.Errorf("Stop(%s) = %v, want %v", v, !want, want)
		}
	}
}

// A stage whose wait expired with a probe's burst failed (016, SC-002) is failed by the
// gate's existing rule, a failing finding the baseline did not have, with nothing in
// Classify that knows the burst: alone, beside a finding the baseline had, beside one it did
// not, and on a step that diverged at its flows. Every burst-failed case fails the stage.
func TestABurstFailedFailsTheStage(t *testing.T) {
	burst := wire.StepFinding{Rule: findings.RuleVerifyBurst, Object: "n1-loop",
		Message: "probe n1-loop: 0 of 5 replies from n1-loop-b at 10.1.11.2"}
	baseline := []wire.StepFinding{neighborN1}
	for _, c := range []struct {
		name     string
		step     *StepOutcome
		wait     *wire.StepWait
		baseline []wire.StepFinding
		added    []wire.StepFinding
	}{
		{"the burst alone", stepped(wire.StepStepped), waitOf(wire.WaitExpired, burst), nil, []wire.StepFinding{burst}},
		{"the burst against a baseline that had none", stepped(wire.StepStepped), waitOf(wire.WaitExpired, burst), baseline,
			[]wire.StepFinding{burst}},
		{"beside a finding the baseline had", stepped(wire.StepStepped), waitOf(wire.WaitExpired, neighborN1, burst), baseline,
			[]wire.StepFinding{burst}},
		{"beside a finding the baseline did not have", stepped(wire.StepStepped), waitOf(wire.WaitExpired, neighborN3, burst),
			baseline, []wire.StepFinding{neighborN3, burst}},
		{"on an unchanged step", stepped(wire.StepUnchanged), waitOf(wire.WaitExpired, burst), nil, []wire.StepFinding{burst}},
		{"diverged at its flows", &StepOutcome{Outcome: wire.StepDiverged, Phase: findings.StepFlows, Step: findings.StepFlows},
			waitOf(wire.WaitExpired, burst), nil, []wire.StepFinding{burst}},
	} {
		got, added := Classify(c.step, c.wait, c.baseline, false)
		if got != VerdictFailed || !reflect.DeepEqual(added, c.added) {
			t.Errorf("%s: Classify = %s, %v; want %s, %v", c.name, got, added, VerdictFailed, c.added)
		}
	}
}
