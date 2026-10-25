package stages

import (
	"reflect"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
)

// record is a twin.json 6 record built from one of change-1's stages, at the reference it
// resolved to then.
func record(label, at, source string) RecordView {
	branch := "change-1"
	if source == AtBranchPoint {
		branch = "main"
	}
	return RecordView{ProposedChange: RecordChange{ID: "pc-1", Branch: "change-1"}, Label: label, Branch: branch, At: at,
		AtSource: source, State: "ready"}
}

// targetChange is change-1 with three marks, cabled, live and wired, found as twin step
// finds it.
func targetChange(t *testing.T, pcs ...intent.ProposedChange) *Change {
	t.Helper()
	if pcs == nil {
		pcs = []intent.ProposedChange{change1(append(change1().Stages,
			mark("st-wired", "wired", "2026-10-16T17:30:05.000000+00:00", nil, ""))...), change2()}
	}
	r, s := story(pcs...)
	ch, list, err := Find(t.Context(), r, s, "change-1", testScope)
	if err != nil || list != nil {
		t.Fatalf("%v %+v", err, list)
	}
	return ch
}

// Target by position: the next stage, any stage given, forward or back, the head moved
// since the record; and each refusal in contracts/stage-commands.md's words, with every
// mark a step skips warned of, either way.
func TestTargetByPosition(t *testing.T) {
	const stages = "branch-point, cabled, live, wired, head"
	ref := func(branch, label string) *Ref { return &Ref{Branch: branch, Label: label} }
	skipped := func(object, message string) findings.List {
		return findings.List{{Severity: findings.Warning, Rule: findings.RuleStepStageSkipped, Object: object,
			Message: message, Step: findings.StepResolve}}
	}
	reopened := change1(change1().Stages...)
	reopened.ID = "pc-9"
	for _, c := range []struct {
		name    string
		pcs     []intent.ProposedChange
		rec     RecordView
		given   *Ref
		want    Ref
		skipped []string
		list    findings.List
	}{
		{name: "the next, from the branch point", rec: record("branch-point", branchedFrom, AtBranchPoint), want: Ref{"change-1", "cabled"}},
		{name: "the next, from a mark", rec: record("cabled", cabledAt, AtWritten), want: Ref{"change-1", "live"}},
		{name: "the head, when no mark follows", rec: record("wired", "2026-10-16T17:30:05.000000+00:00", AtWritten),
			want: Ref{"change-1", "head"}},
		{name: "a given one forward", rec: record("cabled", cabledAt, AtWritten), given: ref("change-1", "live"),
			want: Ref{"change-1", "live"}},
		{name: "a given one back", rec: record("live", liveAt, AtGiven), given: ref("change-1", "cabled"),
			want: Ref{"change-1", "cabled"}},
		{name: "the head moved since the record is a target", rec: record("head", "2026-10-16T17:29:00.000001+00:00", AtHead),
			given: ref("change-1", "head"), want: Ref{"change-1", "head"}},
		{name: "a mark whose as_of was edited is a target", rec: record("live", "2026-10-16T17:29:00.000000+00:00", AtGiven),
			given: ref("change-1", "live"), want: Ref{"change-1", "live"}},
		{name: "the branch point to the head, skipping every mark", rec: record("branch-point", branchedFrom, AtBranchPoint),
			given: ref("change-1", "head"), want: Ref{"change-1", "head"}, skipped: []string{"cabled", "live", "wired"},
			list: skipped("change-1/head", "the step from change-1/branch-point to change-1/head skips stages cabled, live, wired; "+
				"the step is between the two bundles either way")},
		{name: "back, skipping one", rec: record("wired", "2026-10-16T17:30:05.000000+00:00", AtWritten),
			given: ref("change-1", "cabled"), want: Ref{"change-1", "cabled"}, skipped: []string{"live"},
			list: skipped("change-1/cabled", "the step from change-1/wired to change-1/cabled skips stage live; "+
				"the step is between the two bundles either way")},
		{name: "another branch", rec: record("cabled", cabledAt, AtWritten), given: ref("change-2", "head"),
			list: findings.List{refusal(findings.RuleStepTargetForeign, "change-2/head",
				"stage change-2/head is not of proposed change pc-1 on branch change-1, the twin's; a step stays inside the "+
					"proposed change the twin was built from, whose stages are: "+stages)}},
		{name: "another proposed change on the same branch", pcs: []intent.ProposedChange{reopened},
			rec: record("cabled", cabledAt, AtWritten), given: ref("change-1", "live"),
			list: findings.List{refusal(findings.RuleStepTargetForeign, "change-1/live",
				"stage change-1/live is not of proposed change pc-1 on branch change-1, the twin's; a step stays inside the "+
					"proposed change the twin was built from, which is no longer open (the open proposed change on change-1 is pc-9)")}},
		{name: "another proposed change on the same branch, none given", pcs: []intent.ProposedChange{reopened},
			rec: record("cabled", cabledAt, AtWritten),
			list: findings.List{refusal(findings.RuleStepTargetUnknown, "change-1/cabled",
				"proposed change pc-1 on branch change-1, the twin's, is no longer open (the open proposed change on change-1 "+
					"is pc-9); a step stays inside the proposed change the twin was built from")}},
		{name: "nothing after the head", rec: record("head", headAt, AtHead),
			list: findings.List{refusal(findings.RuleStepTargetUnknown, "change-1/head",
				"proposed change pc-1 on change-1 has no stage after change-1/head; its stages are: "+stages)}},
		{name: "nothing after the head, which has moved", rec: record("head", "2026-10-16T17:29:00.000001+00:00", AtHead),
			list: findings.List{refusal(findings.RuleStepTargetUnknown, "change-1/head",
				"proposed change pc-1 on change-1 has no stage after change-1/head; its stages are: "+stages+
					"; the head has moved since the twin was built (now at "+headAt+"): --stage change-1/head steps to it")}},
		{name: "the record's label gone", rec: record("deleted", "2026-10-16T17:27:00.000000+00:00", AtWritten),
			list: findings.List{refusal(findings.RuleStepTargetUnknown, "change-1/deleted",
				"the twin's stage change-1/deleted is no longer a stage of proposed change pc-1 on branch change-1; "+
					"its stages are: "+stages)}},
		{name: "the record's label gone, a target given", rec: record("deleted", "2026-10-16T17:27:00.000000+00:00", AtWritten),
			given: ref("change-1", "head"), want: Ref{"change-1", "head"}},
		{name: "a label the proposed change lacks", rec: record("cabled", cabledAt, AtWritten), given: ref("change-1", "nosuch"),
			list: findings.List{refusal(findings.RuleStepTargetUnknown, "change-1/nosuch",
				`proposed change pc-1 on change-1 has no stage "nosuch"; its stages are: `+stages)}},
		{name: "the record's own stage", rec: record("live", liveAt, AtGiven), given: ref("change-1", "live"),
			list: findings.List{refusal(findings.RuleStepTargetCurrent, "change-1/live",
				"the twin is already at stage change-1/live (branch change-1, at "+liveAt+"); the proposed change's stages are: "+stages)}},
		{name: "the record's own head", rec: record("head", headAt, AtHead), given: ref("change-1", "head"),
			list: findings.List{refusal(findings.RuleStepTargetCurrent, "change-1/head",
				"the twin is already at stage change-1/head (branch change-1, at "+headAt+"); the proposed change's stages are: "+stages)}},
		// Current is the resolved reference: another label that resolves to the record's
		// own (branch, at) is current too.
		{name: "another label at the record's reference", rec: record("head", liveAt, AtHead), given: ref("change-1", "live"),
			list: findings.List{refusal(findings.RuleStepTargetCurrent, "change-1/live",
				"the twin is already at stage change-1/live (branch change-1, at "+liveAt+"); the proposed change's stages are: "+stages)}},
		// The next stage is held to the same rule: two marks with one as_of are one
		// reference, so none given from the first is the twin's own.
		{name: "the next at the record's reference", pcs: []intent.ProposedChange{change1(append(change1().Stages,
			mark("st-also", "also", "2026-10-16T17:31:00.000000+00:00", str(liveAt), ""))...)},
			rec: record("also", liveAt, AtGiven),
			list: findings.List{refusal(findings.RuleStepTargetCurrent, "change-1/live",
				"the twin is already at stage change-1/live (branch change-1, at "+liveAt+"); the proposed change's stages are: "+
					"branch-point, cabled, also, live, head")}},
		{name: "the next with no at is no current", pcs: []intent.ProposedChange{change1(append(change1().Stages,
			mark("st-none", "none", "", nil, ""))...)},
			rec: record("live", liveAt, AtGiven), want: Ref{"change-1", "none"}},
	} {
		t.Run(c.name, func(t *testing.T) {
			got, skipped, list := Target(targetChange(t, c.pcs...), c.rec, c.given)
			if got != c.want || !reflect.DeepEqual(skipped, c.skipped) || !reflect.DeepEqual(list, c.list) {
				t.Errorf("Target = %v, skipped %v, findings %+v\nwant %v, %v, %+v", got, skipped, list, c.want, c.skipped, c.list)
			}
			if list.Rejected() && got != (Ref{}) {
				t.Errorf("a refused target still names %v", got)
			}
		})
	}
}

// The chosen target resolves under the reference contract's own refusals: a target whose
// label two marks share is planned by Build and refused stage.duplicate.
func TestTargetResolvesUnderTheReferenceRules(t *testing.T) {
	ch := targetChange(t, change1(append(change1().Stages,
		mark("st-live-0", "live", "2026-10-16T17:31:30.000000+00:00", nil, ""))...))
	target, _, list := Target(ch, record("cabled", cabledAt, AtWritten), nil)
	if list != nil || target != (Ref{"change-1", "live"}) {
		t.Fatalf("Target = %v, %+v", target, list)
	}
	r, s := story()
	built := Build(t.Context(), r, s, registry(t), ch, target, (&fakePipeline{t: t}).pipeline(), now)
	if built.Status != PlanRefused || built.Rule != findings.RuleStageDuplicate {
		t.Errorf("built %s %s %+v", built.Status, built.Rule, built.Findings)
	}
}
