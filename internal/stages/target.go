package stages

import (
	"fmt"
	"slices"
	"strings"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

// Target chooses the stage a twin steps to (FR-018; research R-16): the one given, or else
// the next stage after the record's in the proposed change's order, the record's place
// found by its label. ch is the open proposed change on the record's source branch, as
// Find read it, the head's at included. Its rules, in order, each a rejection at step
// resolve with contracts/stage-commands.md's sentence, the first ending it:
//
//  1. a given reference of another branch is step.target.foreign: a step stays inside
//     the proposed change the twin was built from;
//  2. the branch's open proposed change is not the record's (closed, and another opened
//     on the branch): a given reference is step.target.foreign, and with none given it is
//     step.target.unknown, since the twin's place is gone with it;
//  3. with none given, the stage after the record's, or step.target.unknown when the
//     record's label is gone or nothing follows it, saying so and, when the record is at
//     a head that has moved since, that --stage <branch>/head steps to it;
//  4. a given label the proposed change lacks is step.target.unknown, naming its stages;
//  5. a given stage that resolves to the record's own (branch, at) is
//     step.target.current; a moved head, or a mark whose as_of was edited, is a target;
//  6. every mark strictly between the record's place and the target's, either direction,
//     is skipped, and when there is any the warning step.stage.skipped says so: the step is
//     between the two bundles either way.
//
// The chosen reference is then ResolveFrom's or Build's to resolve, under the reference
// contract's own refusals. Target reads nothing.
func Target(ch *Change, rec RecordView, given *Ref) (Ref, []string, findings.List) {
	pc, branch := ch.ProposedChange, rec.ProposedChange.Branch
	labels := ch.Labels()
	stages := strings.Join(labels, ", ")
	same := pc.ID == rec.ProposedChange.ID

	if given != nil && (given.Branch != branch || !same) {
		held := "whose stages are: " + stages
		if !same {
			held = fmt.Sprintf("which is no longer open (the open proposed change on %s is %s)", branch, pc.ID)
		}
		return Ref{}, nil, findings.List{refusal(findings.RuleStepTargetForeign, given.String(), fmt.Sprintf(
			"stage %s is not of proposed change %s on branch %s, the twin's; a step stays inside the proposed change "+
				"the twin was built from, %s", given, rec.ProposedChange.ID, branch, held))}
	}
	if !same {
		return Ref{}, nil, findings.List{refusal(findings.RuleStepTargetUnknown, rec.Ref().String(), fmt.Sprintf(
			"proposed change %s on branch %s, the twin's, is no longer open (the open proposed change on %s is %s); "+
				"a step stays inside the proposed change the twin was built from", rec.ProposedChange.ID, branch, branch, pc.ID))}
	}

	current := slices.Index(labels, rec.Label)
	target := Ref{Branch: branch}
	if given == nil {
		switch {
		case current < 0:
			return Ref{}, nil, findings.List{refusal(findings.RuleStepTargetUnknown, rec.Ref().String(), fmt.Sprintf(
				"the twin's stage %s is no longer a stage of proposed change %s on branch %s; its stages are: %s",
				rec.Ref(), pc.ID, branch, stages))}
		case current == len(labels)-1:
			message := fmt.Sprintf("proposed change %s on %s has no stage after %s; its stages are: %s",
				pc.ID, branch, rec.Ref(), stages)
			if head, ok := ch.first(LabelHead); ok && rec.AtSource == AtHead && head.At != "" && head.At != rec.At {
				message += fmt.Sprintf("; the head has moved since the twin was built (now at %s): --stage %s steps to it",
					head.At, head.Ref)
			}
			return Ref{}, nil, findings.List{refusal(findings.RuleStepTargetUnknown, rec.Ref().String(), message)}
		}
		target.Label = labels[current+1]
	} else {
		if !slices.Contains(labels, given.Label) {
			return Ref{}, nil, findings.List{refusal(findings.RuleStepTargetUnknown, given.String(), fmt.Sprintf(
				"proposed change %s on %s has no stage %q; its stages are: %s", pc.ID, branch, given.Label, stages))}
		}
		if st, _ := ch.first(given.Label); st.At != "" && st.Branch == rec.Branch && st.At == rec.At {
			return Ref{}, nil, findings.List{refusal(findings.RuleStepTargetCurrent, given.String(), fmt.Sprintf(
				"the twin is already at stage %s (branch %s, at %s); the proposed change's stages are: %s",
				given, st.Branch, st.At, stages))}
		}
		target.Label = given.Label
	}

	if current < 0 {
		return target, nil, nil
	}
	to := slices.Index(labels, target.Label)
	lo, hi := min(current, to), max(current, to)
	skipped := slices.Clone(labels[lo+1 : max(lo+1, hi)])
	if len(skipped) == 0 {
		return target, nil, nil
	}
	noun := "stages"
	if len(skipped) == 1 {
		noun = "stage"
	}
	return target, skipped, findings.List{{Severity: findings.Warning, Rule: findings.RuleStepStageSkipped,
		Object: target.String(), Step: findings.StepResolve, Message: fmt.Sprintf(
			"the step from %s to %s skips %s %s; the step is between the two bundles either way",
			rec.Ref(), target, noun, strings.Join(skipped, ", "))}}
}
