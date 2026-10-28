package stages

import (
	"fmt"
	"slices"
	"strings"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

// Target chooses the stage a twin steps to (FR-018; research R-16; 019, research R-07):
// the one given, or else the next stage after the record's in the proposed change's order,
// the record's place found by its label. ch is the open proposed change Find read on the
// given reference's branch, or on the record's stage's branch when none is given, the
// head's at included. view is the record's stage, nil for a record that names none (a twin
// built from a branch or a snapshot, or stepped to a snapshot); recordBranch and recordAt
// are the record's provenance, the reference the twin was built from or last stepped to,
// stage or not. Let same be whether view names a stage of ch. Its rules, in order, each a
// rejection at step resolve with contracts/stage-commands.md's sentence, the first ending
// it:
//
//  1. with none given, a record naming no stage is step.target.unknown: it has no next
//     stage, so a target is required (the server refuses it first, before any connection,
//     naming the record's bundle; research R-08);
//  2. with none given, the branch's open proposed change is not the record's (closed, and
//     another opened on the branch): step.target.unknown, since the twin's place is gone
//     with it;
//  3. with none given, the stage after the record's, or step.target.unknown when the
//     record's label is gone or nothing follows it, saying so and, when the record is at
//     a head that has moved since, that --stage <branch>/head steps to it;
//  4. a given label the proposed change lacks is step.target.unknown, naming its stages,
//     whether or not it is the record's: a given reference names a stage of any proposed
//     change (019);
//  5. the target, given or next, that resolves to the record's own (branch, at) is
//     step.target.current, whether or not the record names a stage; a moved head, or a mark
//     whose as_of was edited, is a target;
//  6. when same, every mark strictly between the record's place and the target's, either
//     direction, is skipped, and when there is any the warning step.stage.skipped says so:
//     the step is between the two bundles either way. Between two proposed changes' stages
//     the marks are no order, and nothing is skipped.
//
// 019 retired step.target.foreign: a stage of another branch, or of another proposed
// change opened on the record's, is a target. The chosen reference is then ResolveFrom's
// or Build's to resolve, under the reference contract's own refusals. Target reads
// nothing.
func Target(ch *Change, view *RecordView, recordBranch, recordAt string, given *Ref) (Ref, []string, findings.List) {
	pc := ch.ProposedChange
	labels := ch.Labels()
	stages := strings.Join(labels, ", ")
	same := view != nil && pc.ID == view.ProposedChange.ID

	current := -1
	target := Ref{Branch: pc.Branch}
	switch {
	case given != nil:
		if !slices.Contains(labels, given.Label) {
			return Ref{}, nil, findings.List{refusal(findings.RuleStepTargetUnknown, given.String(), fmt.Sprintf(
				"proposed change %s on %s has no stage %q; its stages are: %s", pc.ID, pc.Branch, given.Label, stages))}
		}
		target = *given
		if same {
			current = slices.Index(labels, view.Label)
		}
	case view == nil:
		return Ref{}, nil, findings.List{refusal(findings.RuleStepTargetUnknown, recordBranch, NoTargetMessage)}
	case !same:
		branch := view.ProposedChange.Branch
		return Ref{}, nil, findings.List{refusal(findings.RuleStepTargetUnknown, view.Ref().String(), fmt.Sprintf(
			"proposed change %s on branch %s, the twin's, is no longer open (the open proposed change on %s is %s), so "+
				"the twin has no next stage; give --stage <branch>/<label> or --snapshot <id|file>",
			view.ProposedChange.ID, branch, branch, pc.ID))}
	default:
		current = slices.Index(labels, view.Label)
		switch {
		case current < 0:
			return Ref{}, nil, findings.List{refusal(findings.RuleStepTargetUnknown, view.Ref().String(), fmt.Sprintf(
				"the twin's stage %s is no longer a stage of proposed change %s on branch %s; its stages are: %s",
				view.Ref(), pc.ID, pc.Branch, stages))}
		case current == len(labels)-1:
			message := fmt.Sprintf("proposed change %s on %s has no stage after %s; its stages are: %s",
				pc.ID, pc.Branch, view.Ref(), stages)
			if head, ok := ch.first(LabelHead); ok && view.AtSource == AtHead && head.At != "" && head.At != view.At {
				message += fmt.Sprintf("; the head has moved since the twin was built (now at %s): --stage %s steps to it",
					head.At, head.Ref)
			}
			return Ref{}, nil, findings.List{refusal(findings.RuleStepTargetUnknown, view.Ref().String(), message)}
		}
		target.Label = labels[current+1]
	}
	// The next stage is held to it as a given one is, and a stage of any proposed change as
	// one of the record's: a mark sharing the record's at is the twin's own reference under
	// another label.
	if st, _ := ch.first(target.Label); st.At != "" && st.Branch == recordBranch && st.At == recordAt {
		return Ref{}, nil, findings.List{refusal(findings.RuleStepTargetCurrent, target.String(), fmt.Sprintf(
			"the twin is already at stage %s (branch %s, at %s); the proposed change's stages are: %s",
			target, st.Branch, st.At, stages))}
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
			view.Ref(), target, noun, strings.Join(skipped, ", "))}}
}

// NoTargetMessage is step.target.unknown's message for a step given no target, of a twin
// whose record names no stage (019, research R-08): the server's refusal before any
// connection, and Target's rule 1.
const NoTargetMessage = "the twin names no stage, so there is no next stage to step to; " +
	"give --stage <branch>/<label> or --snapshot <id|file>"
