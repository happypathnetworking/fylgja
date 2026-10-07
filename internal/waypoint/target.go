package waypoint

import (
	"fmt"
	"slices"
	"strings"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
)

// Target chooses the waypoint a twin steps to: the
// one given, or else the next sequence of the record's series after current, in numeric
// order. Its six steps, in order, each a rejection at step resolve with contracts/cli.md's
// sentence, the first ending it:
//
//  1. a given reference of another series is step.target.foreign, naming the twin's
//     series' sequences: a step stays inside the series the twin was built from;
//  2. a series with no waypoints, whose record's series no longer exists, is
//     step.target.unknown, naming the series that exist;
//  3. with none given, the first sequence after current, or step.target.unknown when the
//     series has none;
//  4. a given reference that is the twin's own waypoint is step.target.current, naming
//     the series' sequences;
//  5. a given sequence the series lacks is step.target.unknown, in M10's waypoint.unknown
//     sentence;
//  6. every sequence strictly between current and the target, either direction, is
//     skipped, and when there is any the warning step.sequence.skipped says so: the step
//     is between the two bundles either way.
//
// all is the one listing; the chosen reference is then ResolveFrom's to resolve, under
// M10's own refusals.
func Target(all []intent.Waypoint, series string, current int, given *Ref) (Ref, []int, findings.List) {
	// Every refusal of the four names the series' sequences, so they are read
	// before step 1.
	var inSeries []intent.Waypoint
	for _, w := range all {
		if w.Series == series {
			inSeries = append(inSeries, w)
		}
	}
	seqs := sequenceNumbers(inSeries)
	if given != nil && given.Series != series {
		held := "which has no waypoints"
		if len(seqs) > 0 {
			held = "whose sequences are " + joinInts(seqs)
		}
		return Ref{}, nil, findings.List{refusal(findings.RuleStepTargetForeign, given.String(), fmt.Sprintf(
			"waypoint %s is not of series %s, the twin's series, %s; a step stays inside the series the twin was built from",
			given, series, held))}
	}
	if len(seqs) == 0 {
		exist := "no series exists"
		if names := seriesNames(all); len(names) > 0 {
			exist = "the series are: " + strings.Join(names, ", ")
		}
		return Ref{}, nil, findings.List{refusal(findings.RuleStepTargetUnknown, series,
			fmt.Sprintf("series %s has no waypoints; %s", series, exist))}
	}

	target := Ref{Series: series}
	switch {
	case given == nil:
		i := slices.IndexFunc(seqs, func(n int) bool { return n > current })
		if i < 0 {
			return Ref{}, nil, findings.List{refusal(findings.RuleStepTargetUnknown, series, fmt.Sprintf(
				"series %s has no waypoint after %d; its sequences are %s", series, current, joinInts(seqs)))}
		}
		target.Sequence = seqs[i]
	case given.Sequence == current:
		return Ref{}, nil, findings.List{refusal(findings.RuleStepTargetCurrent, given.String(),
			fmt.Sprintf("the twin is already at waypoint %s; series %s's sequences are %s", given, series, joinInts(seqs)))}
	case !slices.Contains(seqs, given.Sequence):
		return Ref{}, nil, findings.List{refusal(findings.RuleStepTargetUnknown, given.String(), fmt.Sprintf(
			"series %s has no waypoint %d; its sequences are %s", series, given.Sequence, joinInts(seqs)))}
	default:
		target.Sequence = given.Sequence
	}

	lo, hi := min(current, target.Sequence), max(current, target.Sequence)
	var skipped []int
	for _, n := range seqs {
		if n > lo && n < hi {
			skipped = append(skipped, n)
		}
	}
	var list findings.List
	if len(skipped) > 0 {
		noun := "waypoints"
		if len(skipped) == 1 {
			noun = "waypoint"
		}
		list = append(list, findings.Finding{Severity: findings.Warning, Rule: findings.RuleStepSequenceSkipped,
			Object: target.String(), Step: findings.StepResolve, Message: fmt.Sprintf(
				"the step from %s to %s skips %s %s; the step is between the two bundles either way",
				Ref{Series: series, Sequence: current}, target, noun, joinInts(skipped))})
	}
	return target, skipped, list
}
