package rehearsal

import (
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// Verdict is what a stage of a rehearsal came to (rehearsal.schema.json, $defs/stage),
// spelled as the schema spells it.
type Verdict string

const (
	// VerdictRefused is a stage the plan refused (RoleRefused).
	VerdictRefused Verdict = "refused"
	// VerdictBaseline is the baseline: built and waited on, its wait's failing assertions the
	// baseline findings, which fail nothing.
	VerdictBaseline Verdict = "baseline"
	// VerdictPassed is a step that ended stepped or unchanged whose wait holds nothing the
	// baseline's did not.
	VerdictPassed Verdict = "passed"
	// VerdictFailed is a step that diverged, at any phase, or whose wait holds a finding the
	// baseline's did not: something was learned about the change (status nonconforming).
	VerdictFailed Verdict = "failed"
	// VerdictError is a step that could not run, was rejected by its locks or cancelled, a
	// wait that could not complete, or a stage the deadline or an interrupt cut: nothing was
	// learned about the change (status error).
	VerdictError Verdict = "error"
	// VerdictNotReached is a stage after one that was not passed.
	VerdictNotReached Verdict = "not_reached"
)

// StepOutcome is a step child's result as the verdict reads it, which the caller fills from
// the step workflow's result so that this package imports no workflow code: the outcome
// (stepped, unchanged, diverged, rejected, error or cancelled), the phase a step that
// touched the host stopped at (set on a diverged step and on one cancelled after its stage,
// so a cancelled step with no phase was cancelled before its stage), and the step the run
// stopped at when it did not end stepped or unchanged.
type StepOutcome struct {
	Outcome string
	Phase   string
	Step    string
}

// CancelledBeforeStage says the step was cancelled before it touched the host.
func (s StepOutcome) CancelledBeforeStage() bool {
	return s.Outcome == outcomeCancelled && s.Phase == ""
}

// The step workflow's outcomes beside wire's three, as it spells them.
const (
	outcomeRejected  = "rejected"
	outcomeError     = "error"
	outcomeCancelled = "cancelled"
)

// Classify is a rehearsed stage's verdict (research R-07; data-model §2), from its step
// child's result, the step's wait, the baseline findings and whether the deadline cut the
// stage, with the wait's failing assertions the baseline's did not have:
//
//   - error when cut, when the step gave no result, ended rejected, error or cancelled, or
//     its wait did not run or ended incomplete or cancelled, so nothing can be compared;
//   - failed when the step diverged, at any phase, with whatever new findings its wait
//     holds, or when its wait holds a finding the baseline's did not;
//   - passed when the step ended stepped or unchanged and its wait holds nothing new.
//
// A divergence is decisive: its wait's findings are reported only when the wait read every
// node (settled or expired).
func Classify(step *StepOutcome, wait *wire.StepWait, baseline []wire.StepFinding, cut bool) (Verdict, []wire.StepFinding) {
	if cut || step == nil {
		return VerdictError, nil
	}
	switch step.Outcome {
	case wire.StepDiverged:
		if !comparable(wait) {
			return VerdictFailed, nil
		}
		return VerdictFailed, NewFindings(baseline, wait.Failing)
	case wire.StepStepped, wire.StepUnchanged:
		if !comparable(wait) {
			return VerdictError, nil
		}
		if added := NewFindings(baseline, wait.Failing); len(added) > 0 {
			return VerdictFailed, added
		}
		return VerdictPassed, nil
	}
	return VerdictError, nil
}

// comparable is a wait that read every node: one that settled, or expired with an assertion
// still failing. An incomplete wait left a node unread and a cancelled one stopped short.
func comparable(wait *wire.StepWait) bool {
	return wait != nil && (wait.Outcome == wire.WaitSettled || wait.Outcome == wire.WaitExpired)
}

// NewFindings are the stage's failing assertions whose rule and object no baseline finding
// has, in the stage's order. The record's claim is never among them: the claims are not
// waited on, and one present is ignored.
func NewFindings(baseline, stage []wire.StepFinding) []wire.StepFinding {
	type key struct{ rule, object string }
	had := make(map[key]bool, len(baseline))
	for _, f := range baseline {
		had[key{f.Rule, f.Object}] = true
	}
	var out []wire.StepFinding
	for _, f := range stage {
		if f.Rule == findings.RuleVerifyRecordHolds || had[key{f.Rule, f.Object}] {
			continue
		}
		out = append(out, f)
	}
	return out
}

// Stop says whether a stage's verdict stops the run: every verdict but passed, the
// baseline's, after which the run goes on to the first rehearsed stage, and the refused
// branch point's, which the run passes over. Every stage after the one that stopped it is
// not reached.
func Stop(v Verdict) bool {
	switch v {
	case VerdictPassed, VerdictBaseline, VerdictRefused:
		return false
	}
	return true
}
