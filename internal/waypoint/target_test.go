package waypoint

import (
	"reflect"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
)

// targetRows is a listing with series demo at sequences 1, 2 and 5 (a gap), series alpha,
// and series empty-free: every shape of is a reference into it.
func targetRows() []intent.Waypoint {
	return []intent.Waypoint{
		row("id-5", "demo", 5, "change-1", "2026-09-28T16:00:00Z", nil, ""),
		row("id-1", "demo", 1, "change-1", "2026-09-28T15:00:01.123456+00:00", nil, ""),
		row("id-a", "alpha", 1, "change-2", "2026-09-28T15:00:00Z", nil, ""),
		row("id-2", "demo", 2, "change-1", "2026-09-28T15:20:44.000000+00:00", nil, ""),
	}
}

// Target applies six steps in order, each refusal at step resolve in
// contracts/cli.md's words, and warns of every sequence a step skips, either way.
func TestTarget(t *testing.T) {
	ref := func(series string, sequence int) *Ref { return &Ref{Series: series, Sequence: sequence} }
	skippedWarning := func(object, message string) findings.List {
		return findings.List{{Severity: findings.Warning, Rule: findings.RuleStepSequenceSkipped, Object: object,
			Message: message, Step: findings.StepResolve}}
	}
	cases := []struct {
		name    string
		rows    []intent.Waypoint
		series  string
		current int
		given   *Ref
		want    Ref
		skipped []int
		list    findings.List
	}{
		{name: "the next, across a gap", series: "demo", current: 2, want: Ref{"demo", 5}},
		{name: "the next, adjacent", series: "demo", current: 1, want: Ref{"demo", 2}},
		{name: "a record's sequence the series no longer holds", series: "demo", current: 3, want: Ref{"demo", 5}},
		{name: "a given one forward", series: "demo", current: 1, given: ref("demo", 2), want: Ref{"demo", 2}},
		{name: "a given one back", series: "demo", current: 2, given: ref("demo", 1), want: Ref{"demo", 1}},
		{name: "a given one forward, skipping", series: "demo", current: 1, given: ref("demo", 5), want: Ref{"demo", 5},
			skipped: []int{2}, list: skippedWarning("demo/5",
				"the step from demo/1 to demo/5 skips waypoint 2; the step is between the two bundles either way")},
		{name: "a given one back, skipping", series: "demo", current: 5, given: ref("demo", 1), want: Ref{"demo", 1},
			skipped: []int{2}, list: skippedWarning("demo/1",
				"the step from demo/5 to demo/1 skips waypoint 2; the step is between the two bundles either way")},
		{name: "a given one skipping several", series: "demo", current: 1,
			rows:  append(targetRows(), row("id-3", "demo", 3, "change-1", "2026-09-28T15:30:00Z", nil, "")),
			given: ref("demo", 5), want: Ref{"demo", 5}, skipped: []int{2, 3}, list: skippedWarning("demo/5",
				"the step from demo/1 to demo/5 skips waypoints 2, 3; the step is between the two bundles either way")},
		{name: "a foreign series", series: "demo", current: 1, given: ref("other", 3),
			list: findings.List{refusal(findings.RuleStepTargetForeign, "other/3",
				"waypoint other/3 is not of series demo, the twin's series, whose sequences are 1, 2, 5; a step stays inside the series the twin was built from")}},
		{name: "a series with no waypoints", series: "gone", current: 1,
			list: findings.List{refusal(findings.RuleStepTargetUnknown, "gone", "series gone has no waypoints; the series are: alpha, demo")}},
		{name: "no series at all", series: "gone", current: 1, rows: []intent.Waypoint{},
			list: findings.List{refusal(findings.RuleStepTargetUnknown, "gone", "series gone has no waypoints; no series exists")}},
		{name: "none after the last", series: "demo", current: 5,
			list: findings.List{refusal(findings.RuleStepTargetUnknown, "demo", "series demo has no waypoint after 5; its sequences are 1, 2, 5")}},
		{name: "a sequence the series lacks", series: "demo", current: 1, given: ref("demo", 7),
			list: findings.List{refusal(findings.RuleStepTargetUnknown, "demo/7", "series demo has no waypoint 7; its sequences are 1, 2, 5")}},
		{name: "the current one", series: "demo", current: 2, given: ref("demo", 2),
			list: findings.List{refusal(findings.RuleStepTargetCurrent, "demo/2", "the twin is already at waypoint demo/2; series demo's sequences are 1, 2, 5")}},
		// Step 1 before step 2: a foreign reference is foreign even when the twin's series is
		// gone; step 4 before step 5: the twin's own sequence is current even when deleted.
		{name: "foreign before an unknown series", series: "gone", current: 1, given: ref("demo", 2),
			list: findings.List{refusal(findings.RuleStepTargetForeign, "demo/2",
				"waypoint demo/2 is not of series gone, the twin's series, which has no waypoints; a step stays inside the series the twin was built from")}},
		{name: "current before a missing sequence", series: "demo", current: 3, given: ref("demo", 3),
			list: findings.List{refusal(findings.RuleStepTargetCurrent, "demo/3", "the twin is already at waypoint demo/3; series demo's sequences are 1, 2, 5")}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			rows := c.rows
			if rows == nil {
				rows = targetRows()
			}
			got, skipped, list := Target(rows, c.series, c.current, c.given)
			if got != c.want || !reflect.DeepEqual(skipped, c.skipped) || !reflect.DeepEqual(list, c.list) {
				t.Errorf("Target = %v, skipped %v, findings %+v\nwant %v, %v, %+v", got, skipped, list, c.want, c.skipped, c.list)
			}
			if list.Rejected() && got != (Ref{}) {
				t.Errorf("a refused target still names %v", got)
			}
		})
	}
}

// ResolveFrom and Build are M10's resolveIn and planOne under their exported names: the
// target resolves with M10's refusals, and the plan, which builds every waypoint
// with Build, is unchanged (TestPlan* in plan_test.go).
func TestResolveFromIsM10s(t *testing.T) {
	rows := targetRows()
	got, list := ResolveFrom(rows, Ref{"demo", 2}, now)
	if list != nil || got.Branch != "change-1" || got.At != "2026-09-28T15:20:44.000000+00:00" || got.AtSource != AtWritten {
		t.Errorf("ResolveFrom = %+v, %+v", got, list)
	}
	_, list = ResolveFrom(rows, Ref{"demo", 7}, now)
	if len(list) != 1 || list[0].Rule != findings.RuleWaypointUnknown ||
		list[0].Message != "series demo has no waypoint 7; its sequences are 1, 2, 5" {
		t.Errorf("an unknown sequence: %+v", list)
	}
}
