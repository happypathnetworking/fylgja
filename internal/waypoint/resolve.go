package waypoint

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
)

// Reader is what a resolution asks of Infrahub: the two methods of
// intent.WaypointReader, faked in tier 1.
type Reader interface {
	Check(ctx context.Context) error
	List(ctx context.Context) ([]intent.Waypoint, error)
}

// Where a resolved at came from.
const (
	// AtGiven: the waypoint's as_of was written, and is used verbatim.
	AtGiven = "given"
	// AtWritten: no as_of was written, and the at is the waypoint's branch attribute's
	// updated_at, verbatim as Infrahub returns it.
	AtWritten = "written"
)

// Resolved is a waypoint resolved to the intent reference it names.
type Resolved struct {
	Ref         Ref
	ID          string
	Branch      string
	At          string // verbatim
	AtSource    string // AtGiven | AtWritten
	Description string
}

// kindRemedy follows intent.WaypointKindError's sentence in every waypoint.kind.absent
// finding (contracts/cli.md).
const kindRemedy = ": load " + intent.WaypointSchemaFile + " on it; only --waypoint, waypoint list and waypoint plan need it"

// Resolve resolves one reference to its (branch, at), applying six
// steps in order; the first refusal ends it. The at it returns is never empty. Each refusal is a rejection at step
// resolve with contracts/cli.md's message, and no branch is read: the reader lists the
// waypoints, and the reference's own read is the caller's, after this returns.
//
// now is the CLI's clock, read once by the command and passed in, for the future rule
// alone, which only a given at is held to: it is compared, never sent. A reader that cannot reach Infrahub or is
// refused its credential returns its error as it is, never as one of the six; the
// caller reports it as operation.failed, as a branch read's.
func Resolve(ctx context.Context, r Reader, ref Ref, now time.Time) (Resolved, findings.List, error) {
	// 1. The kind, from the default branch's schema.
	if err := r.Check(ctx); err != nil {
		if list := kindAbsent(err); list != nil {
			return Resolved{}, list, nil
		}
		return Resolved{}, nil, err
	}
	all, err := r.List(ctx)
	if err != nil {
		return Resolved{}, nil, err
	}
	res, list := ResolveFrom(all, ref, now)
	return res, list, nil
}

// ResolveFrom applies steps 2–6 to waypoints already listed: the plan lists a series once and
// resolves each of its waypoints here, where steps 2 and 3 cannot fire, and twin step lists
// once, chooses its target, and resolves that.
func ResolveFrom(all []intent.Waypoint, ref Ref, now time.Time) (Resolved, findings.List) {
	matches, list := find(all, ref)
	if list != nil {
		return Resolved{}, list
	}
	w := matches[0]

	// 5. The at: written on the waypoint, or the moment its branch was named. Infrahub
	// stamps every attribute at creation, so an empty at is a defence, as
	// waypoint.duplicate is against the constraint: without it the reference would be the
	// branch head, unpinned.
	res := resolvedRow(w)
	if res.At == "" {
		return Resolved{}, findings.List{refusal(findings.RuleWaypointAtUnresolved, ref.String(), fmt.Sprintf(
			"waypoint %s has no at: no as_of is written on it and Infrahub returned no updated_at for its "+
				"branch attribute, so it names no point in time", ref))}
	}
	if digits := intent.AtFractionDigits(res.At); digits > intent.MaxAtFractionDigits {
		return Resolved{}, findings.List{refusal(findings.RuleAtPrecision, ref.String(), fmt.Sprintf(
			"waypoint %s: at %s carries %d fractional digits; Infrahub honours at most %d (microseconds). "+
				"Write the waypoint's as_of with at most six.",
			ref, res.At, digits, intent.MaxAtFractionDigits))}
	}

	// 6. The future rule, only for a given at Go can read: a form it cannot makes no claim
	// and is passed verbatim, as M1's --at is. A written at is Infrahub's
	// own stamp of a write it has already made; against the CLI's clock it would test only
	// whether the two clocks agree, which a remote Infrahub need not.
	if t, ok := ParseAt(res.At); ok && res.AtSource == AtGiven && t.After(now) {
		return Resolved{}, findings.List{refusal(findings.RuleWaypointAtUnresolved, ref.String(), fmt.Sprintf(
			"waypoint %s has at %s (%s), later than the current time %s: it seals nothing yet, "+
				"and a twin from it could differ between two creates",
			ref, res.At, res.AtSource, now.UTC().Format(nowLayout)))}
	}
	return res, nil
}

// nowLayout is how the CLI's clock is named in a refusal: UTC, six fractional digits.
const nowLayout = "2006-01-02T15:04:05.000000Z"

// kindAbsent files the reader's WaypointKindError as waypoint.kind.absent, or returns
// nil for any other error, which is the caller's to report.
func kindAbsent(err error) findings.List {
	var kindErr *intent.WaypointKindError
	if !errors.As(err, &kindErr) {
		return nil
	}
	return findings.List{refusal(findings.RuleWaypointKindAbsent, intent.WaypointKind, kindErr.Error()+kindRemedy)}
}

// find applies steps 2–4: the series, the sequence in it, and exactly one object holding
// the pair.
func find(all []intent.Waypoint, ref Ref) ([]intent.Waypoint, findings.List) {
	var inSeries, matches []intent.Waypoint
	for _, w := range all {
		if w.Series != ref.Series {
			continue
		}
		inSeries = append(inSeries, w)
		if w.Sequence == ref.Sequence {
			matches = append(matches, w)
		}
	}
	switch {
	case len(inSeries) == 0:
		return nil, unknownSeries(all, ref.Series)
	case len(matches) == 0:
		return nil, findings.List{refusal(findings.RuleWaypointUnknown, ref.String(),
			fmt.Sprintf("series %s has no waypoint %d; its sequences are %s", ref.Series, ref.Sequence, sequences(inSeries)))}
	case len(matches) > 1:
		ids := make([]string, 0, len(matches))
		for _, w := range matches {
			ids = append(ids, w.ID)
		}
		sort.Strings(ids)
		return nil, findings.List{refusal(findings.RuleWaypointDuplicate, ref.String(), fmt.Sprintf(
			"waypoint %s is held by %d objects (ids %s), which the kind's uniqueness constraint should have refused; none is chosen",
			ref, len(matches), strings.Join(ids, ", ")))}
	}
	return matches, nil
}

// unknownSeries refuses a series no waypoint has, naming the series that exist.
func unknownSeries(all []intent.Waypoint, series string) findings.List {
	exist := "there are no waypoints"
	if names := seriesNames(all); len(names) > 0 {
		exist = "the series are: " + strings.Join(names, ", ")
	}
	return findings.List{refusal(findings.RuleWaypointUnknown, series,
		fmt.Sprintf("no waypoint series %q exists; %s", series, exist))}
}

// resolvedRow is step 5 without its rules: the written as_of verbatim, or else the
// branch attribute's updated_at verbatim. The list shows this for every waypoint, with
// no refusal.
func resolvedRow(w intent.Waypoint) Resolved {
	res := Resolved{Ref: Ref{Series: w.Series, Sequence: w.Sequence}, ID: w.ID, Branch: w.Branch,
		Description: w.Description, At: w.BranchWrittenAt, AtSource: AtWritten}
	if w.At != nil {
		res.At, res.AtSource = *w.At, AtGiven
	}
	return res
}

// seriesNames is every series that exists, sorted, each once.
func seriesNames(all []intent.Waypoint) []string {
	seen := map[string]bool{}
	var out []string
	for _, w := range all {
		if !seen[w.Series] {
			seen[w.Series] = true
			out = append(out, w.Series)
		}
	}
	sort.Strings(out)
	return out
}

// sequences is a series' sequences, ascending, each once.
func sequences(inSeries []intent.Waypoint) string {
	return joinInts(sequenceNumbers(inSeries))
}

// sequenceNumbers is a series' sequences as numbers, ascending, each once.
func sequenceNumbers(inSeries []intent.Waypoint) []int {
	seen := map[int]bool{}
	var nums []int
	for _, w := range inSeries {
		if !seen[w.Sequence] {
			seen[w.Sequence] = true
			nums = append(nums, w.Sequence)
		}
	}
	sort.Ints(nums)
	return nums
}

// joinInts is numbers as a refusal lists them: 1, 2, 5.
func joinInts(nums []int) string {
	out := make([]string, len(nums))
	for i, n := range nums {
		out[i] = strconv.Itoa(n)
	}
	return strings.Join(out, ", ")
}

func refusal(rule, object, message string) findings.Finding {
	return findings.Finding{Severity: findings.Rejection, Rule: rule, Object: object, Message: message, Step: findings.StepResolve}
}

// atLayouts are the forms ParseAt reads, in order: RFC 3339 with any
// fraction and a Z or an offset, the same with a space for the T, the naive forms of
// both, and a date. Every form Infrahub was seen to accept and keep is among them.
var atLayouts = []string{
	time.RFC3339Nano,
	"2006-01-02T15:04:05.999999999",
	"2006-01-02 15:04:05.999999999Z07:00",
	"2006-01-02 15:04:05.999999999",
	"2006-01-02",
}

// ParseAt reads an at for the two comparisons that need an instant: the future rule and
// waypoint.time.reversed. A naive form is read as UTC, which is how Infrahub renders one
// back in its own refusals. A form none of the layouts reads returns
// false, and the caller makes no claim about it. Nothing parsed here is ever sent: a
// query carries the at as written.
func ParseAt(s string) (time.Time, bool) {
	for _, layout := range atLayouts {
		if t, err := time.Parse(layout, s); err == nil {
			return t, true
		}
	}
	return time.Time{}, false
}
