package cli

import (
	"path/filepath"
	"reflect"
	"slices"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
)

// US3's acceptance scenarios through the harness (014, T038): `stage list` over the fake
// Infrahub, one test per scenario, then the text pinned as the commands contract pads it,
// the record's mark and its moves, and the document's determinism (FR-016). Each listing
// reads stamps and never a branch's intent, and compiles nothing.
//
// The proposed change listed is planInfrahub's: pc-1 on change-1, a draft, holding
// twoMarks (cabled written at cabledAt, live given at planLiveAt), branched from main at
// fakeBranchedFrom, its head one microsecond after fakeWritten.

// listTwin writes twin.json 6 on the host: a twin built from change-1's stage label, read
// from branch at at, as a create or a step records it.
func listTwin(t *testing.T, paths lab.Paths, label, description, atSource, branch, at string) wire.TwinRecord {
	t.Helper()
	rec := stepRecordOf(t, fixtureBundleID, func(f *lab.RecordFields) {
		f.Provenance.Branch, f.Provenance.At = branch, at
		f.Stage = stepStage(label, description, atSource)
	})
	writeTwin(t, paths, rec)
	return rec
}

// listedRows is the listing's rows as "<ref> <branch> <at> <source> <description>", with
// " twin" after the row the record names.
func listedRows(doc *findings.Document) []string {
	var out []string
	if doc.Stages == nil {
		return nil
	}
	for _, r := range doc.Stages.Rows {
		row := strings.Join([]string{r.Ref, r.Branch, r.At, r.AtSource, r.Description}, " ")
		if r.Twin {
			row += " twin"
		}
		out = append(out, row)
	}
	return out
}

// listsNoIntent fails when a listing asked Infrahub anything of a branch's intent or its
// artifacts' content: the listing reads the schema, the proposed changes, the orphans, the
// branches' points of origin and stamps, and nothing else.
func listsNoIntent(t *testing.T, label string, f *fakeInfrahub) {
	t.Helper()
	readsNoIntent(t, label, f)
	for _, r := range f.requests() {
		if r.Operation == "ArtifactValidations" {
			t.Errorf("%s: the listing asked %+v; a listing judges no staleness", label, r)
		}
	}
}

// Scenario 1's empty case: no open proposed change, on every branch or the one asked for,
// is a line saying so, exit 0, with no rows, no orphans and no record in the document, and
// nothing on stderr.
func TestStageListNoOpenProposedChange(t *testing.T) {
	branch := "change-1"
	for _, c := range []struct {
		name   string
		args   []string
		line   string
		branch *string
	}{
		{"every branch", []string{"list"}, "no open proposed change\n", nil},
		{"--branch", []string{"list", "--branch", "change-1"}, "branch change-1: no open proposed change\n", &branch},
	} {
		t.Run(c.name, func(t *testing.T) {
			useStateRoot(t)
			useService(t, nil)
			f := newFakeInfrahub(t)
			f.start()

			code, stdout, stderr := runStage(t, c.args...)
			if code != findings.ExitOK || stdout != c.line || stderr != "" {
				t.Errorf("exit %d, stdout %q, stderr %q; want 0 with %q alone", code, stdout, stderr, c.line)
			}
			code, doc, raw := stageDoc(t, c.args...)
			if code != findings.ExitOK || doc.Status != findings.StatusOK || len(doc.Findings) != 0 || doc.Stages == nil ||
				!reflect.DeepEqual(doc.Stages.Branch, c.branch) || doc.Stages.Record != nil ||
				!strings.Contains(raw, `"rows": []`) || !strings.Contains(raw, `"orphans": []`) {
				t.Errorf("exit %d; want 0, no findings, branch %v, rows [] and orphans [] and no record:\n%s", code, c.branch, raw)
			}
			listsNoIntent(t, c.name, f)
		})
	}
}

// Scenario 1: a proposed change with two marks and no twin lists four stages in order, the
// marks by their at whatever order Infrahub serves them in, each with its branch, its at,
// where the at came from and its description, padded so the ats and descriptions line up,
// and no row marked; --branch leaves out the proposed changes of other branches. No
// branch's intent is read and no workflow service is dialled.
func TestStageListOneProposedChange(t *testing.T) {
	useStateRoot(t)
	useService(t, nil)
	f := planInfrahub(t, twoMarks()...)
	f.change("pc-2", "change-2", mark("st-other", "other", "", ""))
	f.start()

	code, stdout, stderr := runStage(t, "list", "--branch", lessLink)
	want := `proposed change "change pc-1" (pc-1) on branch change-1, draft (4 stages)
  change-1/branch-point  main      at 2026-10-16T08:00:00.000000+00:00 (branch point)  ""
  change-1/cabled        change-1  at 2026-10-16T08:30:00.000000+00:00 (written)       "the leaf cabled"
  change-1/live          change-1  at 2026-10-16T08:50:00.000000+00:00 (given)         "the leaf live"
  change-1/head          change-1  at 2026-10-16T09:00:00.000001+00:00 (head)          ""
`
	if code != findings.ExitOK || stdout != want || stderr != "" {
		t.Errorf("exit %d, stdout:\n%s\nstderr %q; want 0 with:\n%s", code, stdout, stderr, want)
	}

	code, doc, raw := stageDoc(t, "list", "--branch", lessLink)
	rows := []string{
		"change-1/branch-point main " + fakeBranchedFrom + " branch_point ",
		"change-1/cabled change-1 " + cabledAt + " written the leaf cabled",
		"change-1/live change-1 " + planLiveAt + " given the leaf live",
		"change-1/head change-1 " + fakeHeadAt + " head ",
	}
	if code != findings.ExitOK || len(doc.Findings) != 0 || !slices.Equal(listedRows(doc), rows) || doc.Stages.Record != nil {
		t.Errorf("exit %d, rows %q; want 0, no findings, %q and no record\n%s", code, listedRows(doc), rows, raw)
	}
	for _, r := range doc.Stages.Rows {
		if want := (findings.StageChange{ID: "pc-1", Name: "change pc-1", Branch: lessLink, Draft: true}); r.ProposedChange != want {
			t.Errorf("%s names proposed change %+v; want %+v", r.Ref, r.ProposedChange, want)
		}
	}
	listsNoIntent(t, "stage list", f)
	mustQuoteNoContent(t, f, stdout, stderr, raw)
}

// Every open proposed change is listed, sorted by source branch whatever order Infrahub
// serves them in, each under its own heading and padded within itself; an open one that is
// not a draft says nothing of it.
func TestStageListSortsByBranch(t *testing.T) {
	useStateRoot(t)
	useService(t, nil)
	f := newFakeInfrahub(t)
	f.change("pc-1", "change-1", mark("st-cabled", "cabled", cabledAt, "the leaf cabled")).Draft = true
	f.change("pc-2", "alpha")
	f.start()

	code, stdout, stderr := runStage(t, "list")
	want := `proposed change "change pc-2" (pc-2) on branch alpha (2 stages)
  alpha/branch-point  main   at 2026-10-16T08:00:00.000000+00:00 (branch point)  ""
  alpha/head          alpha  at 2026-10-16T09:00:00.000001+00:00 (head)          ""
proposed change "change pc-1" (pc-1) on branch change-1, draft (3 stages)
  change-1/branch-point  main      at 2026-10-16T08:00:00.000000+00:00 (branch point)  ""
  change-1/cabled        change-1  at 2026-10-16T08:30:00.000000+00:00 (given)         "the leaf cabled"
  change-1/head          change-1  at 2026-10-16T09:00:00.000001+00:00 (head)          ""
`
	if code != findings.ExitOK || stdout != want || stderr != "" {
		t.Errorf("exit %d, stdout:\n%s\nstderr %q; want 0 with:\n%s", code, stdout, stderr, want)
	}
	_, doc, raw := stageDoc(t, "list")
	if got := refs(doc); !slices.Equal(got, []string{"alpha/branch-point", "alpha/head", "change-1/branch-point", "change-1/cabled", "change-1/head"}) ||
		doc.Stages.Branch != nil {
		t.Errorf("rows %v, branch %v\n%s", got, doc.Stages.Branch, raw)
	}
}

// Scenario 2: the row the host's twin was built from is marked, in the text and the
// document, with the record's state: ready, or diverged with the stage the failed step was
// going to. The record's stage still resolving to what it holds is no warning.
func TestStageListMarksTheTwin(t *testing.T) {
	for _, c := range []struct {
		name, mark, state string
		towards           *findings.StageTowards
	}{
		{"ready", "  ← twin", wire.StateReady, nil},
		{"diverged", "  ← twin (diverged towards change-1/live)", wire.StateDiverged, &findings.StageTowards{Ref: "change-1/live"}},
	} {
		t.Run(c.name, func(t *testing.T) {
			paths := useStateRoot(t)
			useService(t, nil)
			f := planInfrahub(t, twoMarks()...)
			f.start()
			rec := listTwin(t, paths, "cabled", "the leaf cabled", findings.AtSourceWritten, lessLink, cabledAt)
			if c.state == wire.StateDiverged {
				phase := findings.StepPush
				rec.State = wire.StateDiverged
				rec.Step = &wire.StepRecord{Outcome: wire.StepDiverged, Phase: &phase,
					Run:  wire.RunRef{WorkflowID: provision.WorkflowStep, RunID: stepRunID},
					From: wire.StepSide{Stage: rec.Stage, BundleID: rec.BundleID, At: cabledAt},
					To:   wire.StepSide{Stage: stepStage("live", "the leaf live", findings.AtSourceGiven), BundleID: strings.Repeat("f44ca840", 8), At: planLiveAt}}
				writeTwin(t, paths, rec)
			}

			code, stdout, stderr := runStage(t, "list")
			wantLine := `  change-1/cabled        change-1  at ` + cabledAt + ` (written)       "the leaf cabled"` + c.mark + "\n"
			if code != findings.ExitOK || !strings.Contains(stdout, wantLine) || strings.Count(stdout, "← twin") != 1 || stderr != "" {
				t.Errorf("exit %d, stdout:\n%s\nstderr %q; want 0 with the one row marked:\n%s", code, stdout, stderr, wantLine)
			}

			code, doc, raw := stageDoc(t, "list")
			want := &findings.StageRecord{Ref: "change-1/cabled", ProposedChange: findings.StageChangeRef{ID: "pc-1", Branch: lessLink},
				Label: "cabled", Branch: lessLink, At: cabledAt, AtSource: findings.AtSourceWritten, State: c.state, Towards: c.towards}
			var marked []string
			for _, r := range doc.Stages.Rows {
				if r.Twin {
					marked = append(marked, r.Ref)
				}
			}
			if code != findings.ExitOK || len(doc.Findings) != 0 || !slices.Equal(marked, []string{"change-1/cabled"}) ||
				!reflect.DeepEqual(doc.Stages.Record, want) {
				t.Errorf("exit %d, marked %v, record %+v; want 0, no findings, change-1/cabled marked and %+v\n%s",
					code, marked, doc.Stages.Record, want, raw)
			}
			if c.towards == nil && !strings.Contains(raw, `"towards": null`) {
				t.Errorf("a ready record's towards is not an explicit null:\n%s", raw)
			}
		})
	}
}

// Scenario 3: a stage its proposed change no longer names (D-047) is listed after the
// proposed changes, by label, and warned of, naming it, exit 0; it is no stage of any
// proposed change, so nothing plans it, reads it or creates from it.
func TestStageListOrphans(t *testing.T) {
	const goneAt = "2026-10-16T08:45:00.000000+00:00"
	paths := useStateRoot(t)
	useService(t, nil)
	f := planInfrahub(t)
	f.orphans = []fakeStage{mark("st-old", "old", "", "the leaf before"), mark("st-gone", "gone", goneAt, "")}
	f.start()

	code, stdout, stderr := runStage(t, "list")
	wantOut := `proposed change "change pc-1" (pc-1) on branch change-1, draft (2 stages)
  change-1/branch-point  main      at 2026-10-16T08:00:00.000000+00:00 (branch point)  ""
  change-1/head          change-1  at 2026-10-16T09:00:00.000001+00:00 (head)          ""
orphaned: stage "gone" (st-gone) names no proposed change
orphaned: stage "old" (st-old) names no proposed change
`
	if code != findings.ExitOK || stdout != wantOut {
		t.Errorf("exit %d, stdout:\n%s\nwant 0 with:\n%s", code, stdout, wantOut)
	}
	for _, id := range []string{"st-old", "st-gone"} {
		if !strings.Contains(stderr, findings.RuleStageOrphaned) || !strings.Contains(stderr, id) {
			t.Errorf("stderr does not warn of %s:\n%s", id, stderr)
		}
	}

	code, doc, raw := stageDoc(t, "list")
	warning := func(label, id string) findings.Finding {
		return findings.Finding{Severity: findings.Warning, Rule: findings.RuleStageOrphaned, Object: id,
			Message: `stage "` + label + `" (id ` + id + `) names no proposed change: it was removed from its proposed change's fylgja_stages; delete the stage`}
	}
	wantOrphans := []findings.StageOrphan{{ID: "st-gone", Label: "gone", At: goneAt, AtSource: findings.AtSourceGiven},
		{ID: "st-old", Label: "old", At: fakeMarkedAt, AtSource: findings.AtSourceWritten}}
	if code != findings.ExitOK || doc.Status != findings.StatusOK ||
		!reflect.DeepEqual(doc.Findings, findings.List{warning("gone", "st-gone"), warning("old", "st-old")}) ||
		!reflect.DeepEqual(doc.Stages.Orphans, wantOrphans) || len(doc.Stages.Rows) != 2 {
		t.Errorf("exit %d, findings %+v, orphans %+v; want 0, two warnings and %+v\n%s", code, doc.Findings, doc.Stages.Orphans, wantOrphans, raw)
	}
	listsNoIntent(t, "the orphans", f)

	// Every command that resolves a stage, as stage plan resolves each of its own, finds it
	// among its proposed change's stages, which hold no orphan.
	unknown := `proposed change "change pc-1" (pc-1) on branch change-1 has no stage "old"; its stages are: branch-point, head`
	for _, args := range [][]string{
		{"twin", "create", "--stage", "change-1/old"},
		{"intent", "read", "--stage", "change-1/old", "--out", filepath.Join(paths.Root, "never.json")},
	} {
		code, doc := executeTwin(t, args...)
		if code != findings.ExitRejected || len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleStageUnknown ||
			doc.Findings[0].Message != unknown {
			t.Errorf("%v: exit %d, findings %+v; want 1 with stage.unknown saying %q", args[:2], code, doc.Findings, unknown)
		}
	}
}

// Scenario 4: a proposed change merged, closed or canceled is not listed, and stage plan,
// twin create --stage and intent read --stage naming its branch are refused as unknown,
// saying no open proposed change has that source branch and naming the branches with one,
// each before any branch's intent is read.
func TestStageListClosedProposedChange(t *testing.T) {
	for _, state := range []string{"merged", "closed", "canceled"} {
		t.Run(state, func(t *testing.T) {
			paths := useStateRoot(t)
			useService(t, nil)
			f := planInfrahub(t, twoMarks()...)
			f.changes[0].State = state
			f.change("pc-2", "change-2")
			f.start()

			_, doc, raw := stageDoc(t, "list")
			if got := refs(doc); !slices.Equal(got, []string{"change-2/branch-point", "change-2/head"}) {
				t.Errorf("rows %v; want change-2's alone\n%s", got, raw)
			}
			code, stdout, _ := runStage(t, "list", "--branch", lessLink)
			if code != findings.ExitOK || stdout != "branch change-1: no open proposed change\n" {
				t.Errorf("--branch change-1: exit %d, stdout %q", code, stdout)
			}

			unknown := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStageUnknown, Object: lessLink,
				Message: "no open proposed change has source branch change-1; the branches with one are: change-2"}
			code, plan, raw := stageDoc(t, "plan", "--branch", lessLink)
			if want := withStep(unknown, findings.StepResolve); code != findings.ExitRejected || !reflect.DeepEqual(plan.Findings, findings.List{want}) ||
				plan.Plan != nil {
				t.Errorf("stage plan: exit %d, findings %+v; want 1 with %+v and no plan\n%s", code, plan.Findings, want, raw)
			}
			for _, c := range []struct {
				args []string
				step string
			}{
				{[]string{"twin", "create", "--stage", "change-1/cabled"}, findings.StepResolve},
				{[]string{"intent", "read", "--stage", "change-1/cabled", "--out", filepath.Join(paths.Root, "never.json")}, ""},
			} {
				code, doc := executeTwin(t, c.args...)
				if want := withStep(unknown, c.step); code != findings.ExitRejected || !reflect.DeepEqual(doc.Findings, findings.List{want}) {
					t.Errorf("%v: exit %d, findings %+v; want 1 with %+v", c.args[:2], code, doc.Findings, want)
				}
				validateM10Document(t, doc)
			}
			readsNoIntent(t, state, f)
		})
	}
}

// withStep is f at step.
func withStep(f findings.Finding, step string) findings.Finding {
	f.Step = step
	return f
}

// Scenario 5: a mark labelled head or branch-point is a rejection beside its row, naming
// the reserved label, exit 1, every row still listed and the derived stage of that name
// still the derived one, first or last; stage plan refuses the derived stage it shadows at
// that stage's place and plans no mark of the name.
func TestStageListReservedLabel(t *testing.T) {
	const bpMarkedAt = "2026-10-16T08:20:00.000000+00:00"
	useStateRoot(t)
	useService(t, nil)
	f := planInfrahub(t, mark("st-head", "head", cabledAt, "a head"), mark("st-bp", "branch-point", bpMarkedAt, ""))
	f.start()

	reserved := func(label, what string) findings.Finding {
		return findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStageLabelReserved, Object: "change-1/" + label,
			Step: findings.StepResolve, Message: `stage change-1/` + label + ` is a mark labelled "` + label + `", which names the derived ` +
				what + ` of every proposed change and is reserved; relabel it (schema/README.md); the ` + what +
				` of change-1 is still its derived stage`}
	}
	code, stdout, stderr := runStage(t, "list")
	want := `proposed change "change pc-1" (pc-1) on branch change-1, draft (4 stages)
  change-1/branch-point  main      at 2026-10-16T08:00:00.000000+00:00 (branch point)  ""
  change-1/branch-point  change-1  at 2026-10-16T08:20:00.000000+00:00 (given)         ""
  change-1/head          change-1  at 2026-10-16T08:30:00.000000+00:00 (given)         "a head"
  change-1/head          change-1  at 2026-10-16T09:00:00.000001+00:00 (head)          ""
`
	if code != findings.ExitRejected || stdout != want || !strings.Contains(stderr, findings.RuleStageLabelReserved) {
		t.Errorf("exit %d, stdout:\n%s\nstderr:\n%s\nwant 1 with:\n%s", code, stdout, stderr, want)
	}

	code, doc, raw := stageDoc(t, "list")
	rows := []string{
		"change-1/branch-point main " + fakeBranchedFrom + " branch_point ",
		"change-1/branch-point change-1 " + bpMarkedAt + " given ",
		"change-1/head change-1 " + cabledAt + " given a head",
		"change-1/head change-1 " + fakeHeadAt + " head ",
	}
	wantFindings := findings.List{reserved("branch-point", "branch point"), reserved("head", "head")}
	if code != findings.ExitRejected || doc.Status != findings.StatusRejected || !slices.Equal(listedRows(doc), rows) ||
		!reflect.DeepEqual(doc.Findings, wantFindings) {
		t.Errorf("exit %d, rows %q, findings %+v; want 1 with %q and %+v\n%s", code, listedRows(doc), doc.Findings, rows, wantFindings, raw)
	}

	code, plan, raw := stageDoc(t, "plan", "--branch", lessLink)
	if code != findings.ExitRejected || plan.Plan == nil || len(plan.Plan.Stages) != 2 {
		t.Fatalf("stage plan: exit %d; want 1 with the two derived stages\n%s", code, raw)
	}
	for i, w := range []struct{ label, source string }{{"branch-point", findings.AtSourceBranchPoint}, {"head", findings.AtSourceHead}} {
		st := plan.Plan.Stages[i]
		if st.Label != w.label || st.AtSource != w.source || st.BundleID != nil || !carriesRule(st.Findings, findings.RuleStageLabelReserved) {
			t.Errorf("stage plan's %s: %+v; want the derived stage (%s) refused %s", w.label, st, w.source, findings.RuleStageLabelReserved)
		}
	}
}

// FR-016: the twin's stage moved under it is stage.twin.moved, a warning beside the
// listing, exit 0, saying what the record holds and what the stage is now: its as_of
// edited, the mark deleted, the head moved by a write on the branch, the branch point
// moved by a rebase, and its proposed change closed. The record is reported as recorded,
// since the twin stays what it was built from.
func TestStageListTwinMoved(t *testing.T) {
	const (
		editedAt  = "2026-10-16T08:35:00.000000+00:00"
		oldHead   = "2026-10-16T08:45:00.000001+00:00"
		rebasedAt = "2026-10-16T08:20:00.000000+00:00"
	)
	built := func(ref, branch, at, source string) string {
		return "the twin was built from stage " + ref + " at branch " + branch + ", at " + at + " (" + source + "); "
	}
	const pinned = "; the twin is pinned to what it was built from"
	for _, c := range []struct {
		name                      string
		label, source, branch, at string
		change                    func(f *fakeInfrahub)
		message                   string
		marked                    []string
	}{
		{"as_of edited", "cabled", findings.AtSourceWritten, lessLink, cabledAt,
			func(f *fakeInfrahub) { f.changes[0].Stages[1].At = editedAt },
			built("change-1/cabled", lessLink, cabledAt, "written") + "change-1/cabled now resolves to branch change-1, at " +
				editedAt + " (given)" + pinned, []string{"change-1/cabled"}},
		{"deleted", "cabled", findings.AtSourceWritten, lessLink, cabledAt,
			func(f *fakeInfrahub) { f.changes[0].Stages = f.changes[0].Stages[:1] },
			built("change-1/cabled", lessLink, cabledAt, "written") + "change-1/cabled no longer exists" + pinned, nil},
		{"head moved", "head", findings.AtSourceHead, lessLink, oldHead, nil,
			built("change-1/head", lessLink, oldHead, "head") + "change-1/head now resolves to branch change-1, at " +
				fakeHeadAt + " (head)" + pinned, []string{"change-1/head"}},
		{"rebased", "branch-point", findings.AtSourceBranchPoint, "main", fakeBranchedFrom,
			func(f *fakeInfrahub) { f.changes[0].BranchedFrom = rebasedAt },
			built("change-1/branch-point", "main", fakeBranchedFrom, "branch_point") +
				"change-1/branch-point now resolves to branch main, at " + rebasedAt + " (branch_point)" + pinned,
			[]string{"change-1/branch-point"}},
		{"closed", "cabled", findings.AtSourceWritten, lessLink, cabledAt,
			func(f *fakeInfrahub) { f.changes[0].State = "closed" },
			built("change-1/cabled", lessLink, cabledAt, "written") + "proposed change pc-1 is no longer open, so change-1/cabled is gone" + pinned,
			nil},
	} {
		t.Run(c.name, func(t *testing.T) {
			paths := useStateRoot(t)
			useService(t, nil)
			f := planInfrahub(t, twoMarks()...)
			if c.change != nil {
				c.change(f)
			}
			f.start()
			listTwin(t, paths, c.label, "", c.source, c.branch, c.at)

			want := findings.Finding{Severity: findings.Warning, Rule: findings.RuleStageTwinMoved, Object: "change-1/" + c.label, Message: c.message}
			// Listed whole and for the twin's branch alike, from the first case on: the text
			// warns too, and a listing of another branch says nothing of the record's.
			views := [][]string{{"list"}}
			if c.name == "as_of edited" {
				views = append(views, []string{"list", "--branch", lessLink})
			}
			for _, args := range views {
				code, doc, raw := stageDoc(t, args...)
				var marked []string
				for _, r := range doc.Stages.Rows {
					if r.Twin {
						marked = append(marked, r.Ref)
					}
				}
				if code != findings.ExitOK || doc.Status != findings.StatusOK || !reflect.DeepEqual(doc.Findings, findings.List{want}) ||
					!slices.Equal(marked, c.marked) || doc.Stages.Record == nil || doc.Stages.Record.At != c.at || doc.Stages.Record.Branch != c.branch {
					t.Errorf("%v: exit %d, findings %+v, marked %v, record %+v; want 0 with %+v, %v marked and the record as recorded\n%s",
						args, code, doc.Findings, marked, doc.Stages.Record, want, c.marked, raw)
				}
			}
			if len(views) == 1 {
				return
			}
			if _, _, stderr := runStage(t, "list"); !strings.Contains(stderr, findings.RuleStageTwinMoved) {
				t.Errorf("the text does not warn of the move:\n%s", stderr)
			}
			if _, doc, raw := stageDoc(t, "list", "--branch", "change-2"); carriesRule(doc.Findings, findings.RuleStageTwinMoved) {
				t.Errorf("a listing of another branch warns of the twin's stage:\n%s", raw)
			}
		})
	}
}

// FR-016: the same input gives the same document, byte for byte, whatever order Infrahub
// serves the proposed changes, their marks and the orphans in.
func TestStageListIsDeterministic(t *testing.T) {
	paths := useStateRoot(t)
	useService(t, nil)
	f := planInfrahub(t, twoMarks()...)
	f.change("pc-2", "alpha", mark("st-a", "a", "", "alpha's"))
	f.orphans = []fakeStage{mark("st-old", "old", "", ""), mark("st-older", "older", cabledAt, "")}
	f.start()
	listTwin(t, paths, "live", "the leaf live", findings.AtSourceGiven, lessLink, planLiveAt)

	_, _, first := stageDoc(t, "list")
	_, _, again := stageDoc(t, "list")
	slices.Reverse(f.changes)
	slices.Reverse(f.changes[0].Stages)
	slices.Reverse(f.orphans)
	_, _, reversed := stageDoc(t, "list")
	if first != again {
		t.Errorf("two runs differ:\n%s\n%s", first, again)
	}
	if first != reversed {
		t.Errorf("served in another order, the document differs:\n%s\n%s", first, reversed)
	}
}
