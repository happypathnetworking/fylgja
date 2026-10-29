package provision

import (
	"context"
	"encoding/json"
	"slices"
	"strings"
	"testing"

	"github.com/stretchr/testify/mock"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// stepFlows are two probes' flows as the server builds them from the two manifests (016,
// data-model §8), each from its a host to its b host.
func stepFlows() []wire.FlowPlan {
	flow := func(far string) wire.FlowSpec {
		return wire.FlowSpec{IntervalS: 0.2, Command: []string{"ping", "-i", "0.2", far}, StartTimeoutS: 30, ReadTimeoutS: 30}
	}
	return []wire.FlowPlan{
		{Probe: "e1-loop", From: "clab-fylgja-e1-loop-a", To: "clab-fylgja-e1-loop-b", Far: "10.1.11.2", Flow: flow("10.1.11.2")},
		{Probe: "s1-loop", From: "clab-fylgja-s1-loop-a", To: "clab-fylgja-s1-loop-b", Far: "10.2.11.2", Flow: flow("10.2.11.2")},
	}
}

// probedStepInput is stepInput with two probes both bundles carry and one the target adds.
func probedStepInput() StepInput {
	in := stepInput()
	in.Flows, in.Added = stepFlows(), []string{"s2-loop"}
	return in
}

// allStarted answers StartFlows as a host whose execs all ran does.
func allStarted(_ context.Context, in wire.FlowsInput) (wire.FlowsResult, error) {
	out := wire.FlowsResult{Flows: []wire.FlowOutcome{}}
	for _, f := range in.Flows {
		out.Flows = append(out.Flows, wire.FlowOutcome{Probe: f.Probe, Outcome: wire.FlowStarted})
	}
	return out, nil
}

// readAs answers ReadFlows as the activity does: each flow started measured, or interrupted
// on a step stopped after its stage, with 312 sent and 3 lost; one not_started carried.
func readAs(_ context.Context, in wire.FlowsInput) (wire.ReadFlowsResult, error) {
	loss := wire.Loss{Basis: wire.LossBasisContainer, Probes: []wire.ProbeLoss{},
		Added: append([]string{}, in.Added...), Dropped: append([]string{}, in.Dropped...)}
	for _, f := range in.Flows {
		p := wire.ProbeLoss{Probe: f.Probe, From: f.From, To: f.To, Outcome: wire.FlowMeasured, Sent: 312, Lost: 3, LongestGapS: 0.6}
		if in.Interrupted {
			p.Outcome = wire.FlowInterrupted
		}
		for _, s := range in.Started {
			if s.Probe == f.Probe && s.Outcome == wire.FlowNotStarted {
				p = wire.ProbeLoss{Probe: f.Probe, From: f.From, To: f.To, Outcome: wire.FlowNotStarted, Rule: s.Rule, Message: s.Message}
			}
		}
		loss.Probes = append(loss.Probes, p)
	}
	return wire.ReadFlowsResult{Loss: loss, Recorded: true}, nil
}

// flowsOf is each probe's outcome in a loss, by probe.
func flowsOf(l *wire.Loss) map[string]string {
	out := map[string]string{}
	if l == nil {
		return out
	}
	for _, p := range l.Probes {
		out[p.Probe] = p.Outcome
	}
	return out
}

// The flows start after the stage and before the reconcile, and are read after the wait, on
// a stepped step; the read is given the run, every start's outcome and the probes the target
// adds, and its loss is the run's (research R-13). Nothing of the outcome moves.
func TestStepFlowsOrder(t *testing.T) {
	h := newStepHarness(t)
	h.mockHappyPath()
	in := probedStepInput()
	res := h.run(in)

	want := []string{wire.ActInspectTwin, wire.ActCheckHost, wire.ActPlanReconcile, wire.ActStageStep, wire.ActStartFlows,
		wire.ActReconcileLab, wire.ActAwaitReadiness, wire.ActPushConfig, wire.ActPushConfig, wire.ActRecordStep,
		wire.ActVerifyTwin, wire.ActReadFlows}
	if got := h.calls(); !slices.Equal(got, want) {
		t.Errorf("activities %v\nwant %v", got, want)
	}
	if res.Outcome != StepStepped || res.Phase != "" || len(res.Findings) != 0 {
		t.Errorf("outcome %q phase %q findings %v, want stepped as without probes", res.Outcome, res.Phase, res.Findings)
	}
	starts := stepInputs[wire.FlowsInput](h, wire.ActStartFlows)
	if len(starts) != 1 || !sameOnTheWire(t, starts[0], wire.FlowsInput{TwinDir: "/state/twin", Flows: in.Flows}) {
		t.Errorf("StartFlows was given %+v, want the twin directory and the flows alone", starts)
	}
	reads := stepInputs[wire.FlowsInput](h, wire.ActReadFlows)
	started, _ := allStarted(context.Background(), wire.FlowsInput{Flows: in.Flows})
	wantRead := wire.FlowsInput{TwinDir: "/state/twin", Flows: in.Flows, RunID: "default-test-run-id", Started: started.Flows,
		Added: []string{"s2-loop"}}
	if len(reads) != 1 || !sameOnTheWire(t, reads[0], wantRead) {
		t.Errorf("ReadFlows was given %+v\nwant %+v", reads, wantRead)
	}
	read, _ := readAs(context.Background(), wantRead)
	if res.Loss == nil || !sameOnTheWire(t, *res.Loss, read.Loss) {
		t.Errorf("the run's loss = %+v, want the read's %+v", res.Loss, read.Loss)
	}
}

// A step with no probes starts nothing and reads nothing, and carries the empty loss (US2
// scenario 3); its activities are M12's, byte for byte.
func TestStepWithNoProbesStartsNoFlow(t *testing.T) {
	h := newStepHarness(t)
	h.mockHappyPath()
	res := h.run(stepInput())
	if h.ran(wire.ActStartFlows) || h.ran(wire.ActReadFlows) {
		t.Errorf("activities %v, want no flow started or read", h.calls())
	}
	b, err := json.Marshal(res.Loss)
	if err != nil {
		t.Fatal(err)
	}
	if want := `{"basis":"container","probes":[],"added":[],"dropped":[]}`; string(b) != want {
		t.Errorf("the run's loss = %s, want %s", b, want)
	}
}

// A step that stops before its stage starts no flow and has no loss.
func TestStepRefusedBeforeItsStageHasNoLoss(t *testing.T) {
	h := newStepHarness(t)
	h.host.Twin.BundleID = "moved"
	h.mockHappyPath()
	res := h.run(probedStepInput())
	if res.Outcome != OutcomeRejected || res.Loss != nil || h.ran(wire.ActStartFlows) || h.ran(wire.ActReadFlows) {
		t.Errorf("outcome %q, loss %+v, activities %v; want rejected with no flow and no loss", res.Outcome, res.Loss, h.calls())
	}
}

// A flow that cannot start is not_started under the warning flow.start.failed, carried to
// the read, and the step goes on to stepped (US2 scenario 5); one the read cannot read adds
// flow.read.failed. Neither moves the outcome.
func TestStepFlowNotStartedOrNotRead(t *testing.T) {
	h := newStepHarness(t)
	why := "probe s1-loop: its flow could not be started in clab-fylgja-s1-loop-a (docker exec exited 1: no such container); " +
		"it is not measured across the step"
	h.env.OnActivity(wire.ActStartFlows, mock.Anything, mock.Anything).Return(wire.FlowsResult{Flows: []wire.FlowOutcome{
		{Probe: "e1-loop", Outcome: wire.FlowStarted},
		{Probe: "s1-loop", Outcome: wire.FlowNotStarted, Rule: findings.RuleFlowStartFailed, Message: why}}}, nil)
	unread := "probe e1-loop: its flow in clab-fylgja-e1-loop-a could not be read (docker exec exited 1: no such file); " +
		"its loss across the step is not known"
	h.env.OnActivity(wire.ActReadFlows, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, in wire.FlowsInput) (wire.ReadFlowsResult, error) {
			r, err := readAs(ctx, in)
			r.Loss.Probes[0] = wire.ProbeLoss{Probe: "e1-loop", From: "clab-fylgja-e1-loop-a", To: "clab-fylgja-e1-loop-b",
				Outcome: wire.FlowNotRead, Rule: findings.RuleFlowReadFailed, Message: unread}
			return r, err
		})
	h.mockHappyPath()
	res := h.run(probedStepInput())

	if res.Outcome != StepStepped || res.Phase != "" {
		t.Errorf("outcome %q phase %q, want stepped", res.Outcome, res.Phase)
	}
	if got := flowsOf(res.Loss); got["s1-loop"] != wire.FlowNotStarted || got["e1-loop"] != wire.FlowNotRead {
		t.Errorf("outcomes %v, want s1-loop not_started carried and e1-loop not_read", got)
	}
	start := onlyFinding(t, res.Findings, findings.RuleFlowStartFailed)
	read := onlyFinding(t, res.Findings, findings.RuleFlowReadFailed)
	for _, c := range []struct {
		f              findings.Finding
		object, string string
	}{{start, "s1-loop", why}, {read, "e1-loop", unread}} {
		if c.f.Severity != findings.Warning || c.f.Step != findings.StepFlows || c.f.Object != c.object || c.f.Message != c.string {
			t.Errorf("finding %+v, want the warning at flows on %s: %s", c.f, c.object, c.string)
		}
	}
	if len(res.Findings) != 2 {
		t.Errorf("findings %v, want the two warnings alone", res.Findings)
	}
	if rec := h.record(); len(rec.Findings) != 0 {
		t.Errorf("the record step was given %v; a warning of the flows is the run's, not a failure", rec.Findings)
	}
}

// StartFlows' own failure stops the step at the phase flows before the first change,
// diverged as every failure after the stage is; the record is written diverged at flows and
// the flows are read interrupted after it, on the record's context.
func TestStepStartFlowsFailed(t *testing.T) {
	h := newStepHarness(t)
	h.env.OnActivity(wire.ActStartFlows, mock.Anything, mock.Anything).Return(wire.FlowsResult{},
		lab.StepFailure(findings.StepFlows, findings.RuleOperationFailed, "flows", "the worker could not start the flows"))
	h.mockHappyPath()
	res := h.run(probedStepInput())

	if res.Outcome != StepDiverged || res.Phase != findings.StepFlows || res.Step != findings.StepFlows {
		t.Errorf("outcome %q phase %q step %q, want diverged at flows", res.Outcome, res.Phase, res.Step)
	}
	want := []string{wire.ActInspectTwin, wire.ActCheckHost, wire.ActPlanReconcile, wire.ActStageStep, wire.ActStartFlows,
		wire.ActRecordStep, wire.ActVerifyTwin, wire.ActReadFlows}
	if got := h.calls(); !slices.Equal(got, want) {
		t.Errorf("activities %v\nwant %v: nothing reconciled or pushed", got, want)
	}
	if rec := h.record(); rec.Phase != findings.StepFlows || rec.Outcome != wire.StepDiverged || rec.ReconcileStarted {
		t.Errorf("record input outcome %q phase %q reconciled %v, want diverged at flows, never reconciled",
			rec.Outcome, rec.Phase, rec.ReconcileStarted)
	}
	failed := onlyFinding(t, res.Findings, findings.RuleOperationFailed)
	if failed.Step != findings.StepFlows || failed.Message != "the worker could not start the flows" {
		t.Errorf("the failure %+v, want the activity's finding at flows", failed)
	}
	if d := onlyFinding(t, res.Findings, findings.RuleStepDiverged); !strings.Contains(d.Message, "stopped at phase flows") {
		t.Errorf("step.diverged %q, want it at phase flows", d.Message)
	}
	reads := stepInputs[wire.FlowsInput](h, wire.ActReadFlows)
	if len(reads) != 1 || !reads[0].Interrupted || reads[0].Started != nil {
		t.Errorf("ReadFlows was given %+v, want every flow read interrupted, no start known", reads)
	}
	if got := flowsOf(res.Loss); got["e1-loop"] != wire.FlowInterrupted || got["s1-loop"] != wire.FlowInterrupted {
		t.Errorf("outcomes %v, want both interrupted", got)
	}
}

// A step cancelled after its stage reads its flows on the record's context, which the
// cancellation does not reach, every one interrupted, so the record says what was lost until
// the cancel (research R-13). Cancelled at StartFlows itself, it stops at the phase flows.
func TestStepCancelledReadsItsFlowsInterrupted(t *testing.T) {
	t.Run("at the reconcile", func(t *testing.T) {
		h := newStepHarness(t)
		mockReconcileCancelled(h, newStepCanceller(h).block)
		h.mockHappyPath()
		res := h.run(probedStepInput())
		if res.Outcome != OutcomeCancelled || res.Phase != findings.StepReconcile {
			t.Errorf("outcome %q phase %q, want cancelled at reconcile", res.Outcome, res.Phase)
		}
		calls := h.calls()
		if !slices.Contains(calls, wire.ActReadFlows) || slices.Contains(calls, "cancelled "+wire.ActReadFlows) ||
			slices.Index(calls, wire.ActReadFlows) < slices.Index(calls, wire.ActRecordStep) {
			t.Errorf("activities %v, want ReadFlows after the record, out of the cancellation's reach", calls)
		}
		if reads := stepInputs[wire.FlowsInput](h, wire.ActReadFlows); len(reads) != 1 || !reads[0].Interrupted {
			t.Errorf("ReadFlows was given %+v, want interrupted", reads)
		}
		if got := flowsOf(res.Loss); got["e1-loop"] != wire.FlowInterrupted || got["s1-loop"] != wire.FlowInterrupted {
			t.Errorf("outcomes %v, want both interrupted", got)
		}
	})

	t.Run("at StartFlows", func(t *testing.T) {
		h := newStepHarness(t)
		c := newStepCanceller(h)
		h.env.OnActivity(wire.ActStartFlows, mock.Anything, mock.Anything).Return(
			func(ctx context.Context, _ wire.FlowsInput) (wire.FlowsResult, error) {
				return wire.FlowsResult{}, c.block(ctx)
			})
		h.mockHappyPath()
		res := h.run(probedStepInput())
		if res.Outcome != OutcomeCancelled || res.Phase != findings.StepFlows || res.Step != findings.StepFlows {
			t.Errorf("outcome %q phase %q step %q, want cancelled at flows", res.Outcome, res.Phase, res.Step)
		}
		if h.ran(wire.ActReconcileLab) {
			t.Errorf("activities %v, want nothing reconciled", h.calls())
		}
		if got := flowsOf(res.Loss); got["e1-loop"] != wire.FlowInterrupted {
			t.Errorf("outcomes %v, want interrupted", got)
		}
	})
}

// A step that fails after its stage, at its push, reads its flows interrupted after the wait.
func TestStepFailedAfterItsStageReadsItsFlowsInterrupted(t *testing.T) {
	h := newStepHarness(t)
	h.env.OnActivity(wire.ActPushConfig, mock.Anything, mock.Anything).Return(wire.PushResult{},
		lab.StepFailure(findings.StepPush, findings.RulePushRefused, "e1", "the device refused the replace"))
	h.mockHappyPath()
	res := h.run(probedStepInput())
	if res.Outcome != StepDiverged || res.Phase != findings.StepPush {
		t.Fatalf("outcome %q phase %q, want diverged at push", res.Outcome, res.Phase)
	}
	calls := h.calls()
	if calls[len(calls)-1] != wire.ActReadFlows || slices.Index(calls, wire.ActVerifyTwin) > slices.Index(calls, wire.ActReadFlows) {
		t.Errorf("activities %v, want ReadFlows last, after the wait", calls)
	}
	if reads := stepInputs[wire.FlowsInput](h, wire.ActReadFlows); len(reads) != 1 || !reads[0].Interrupted {
		t.Errorf("ReadFlows was given %+v, want interrupted", reads)
	}
}

// ReadFlows' own failure on a step that had stepped is the phase flows, diverged: each flow
// is not_read under the activity's message, and step.diverged says the record, written
// before the read, says the twin is ready at the target.
func TestStepReadFlowsFailed(t *testing.T) {
	h := newStepHarness(t)
	h.env.OnActivity(wire.ActReadFlows, mock.Anything, mock.Anything).Return(wire.ReadFlowsResult{},
		lab.StepFailure(findings.StepFlows, findings.RuleOperationFailed, "/state/twin/twin.json",
			"the step's loss is not recorded: permission denied"))
	h.mockHappyPath()
	in := probedStepInput()
	res := h.run(in)

	if res.Outcome != StepDiverged || res.Phase != findings.StepFlows || res.Step != findings.StepFlows {
		t.Errorf("outcome %q phase %q step %q, want diverged at flows", res.Outcome, res.Phase, res.Step)
	}
	if rec := h.record(); rec.Outcome != wire.StepStepped {
		t.Errorf("the record was written %q, want stepped: the read follows it", rec.Outcome)
	}
	for _, p := range res.Loss.Probes {
		if p.Outcome != wire.FlowNotRead || p.Rule != findings.RuleFlowReadFailed || !strings.Contains(p.Message, "permission denied") {
			t.Errorf("probe %+v, want not_read under the activity's message", p)
		}
	}
	if !slices.Equal(res.Loss.Added, []string{"s2-loop"}) || res.Loss.Dropped == nil {
		t.Errorf("added %v dropped %v, want the input's, every list present", res.Loss.Added, res.Loss.Dropped)
	}
	d := onlyFinding(t, res.Findings, findings.RuleStepDiverged)
	want := "step run default-test-run-id towards stage change-1/live (bundle " + shortBundle(stepTo) + ") stopped at phase flows: " +
		"landed e1, s1; not landed none; the twin is up at stage change-1/live (bundle " + shortBundle(stepTo) + ") and its record says " +
		"it is ready there, but the step's flows could not be read and their loss is not recorded; fylgja twin destroy clears it"
	if d.Message != want || d.Step != findings.StepFlows {
		t.Errorf("step.diverged = %q\nwant %q", d.Message, want)
	}
}
