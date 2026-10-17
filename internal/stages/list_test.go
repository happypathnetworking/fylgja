package stages

import (
	"context"
	"errors"
	"reflect"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
)

func rowRefs(rows []Row) []string {
	var out []string
	for _, r := range rows {
		out = append(out, r.Ref.String()+" "+r.AtSource)
	}
	return out
}

// Every open proposed change's stages, sorted by branch then order whatever the server's
// order, each with the at it resolves to and its source; the --branch filter; nothing
// refused or warned of.
func TestListSortsAndFilters(t *testing.T) {
	r, s := story(change2(), change1())
	res, list, err := List(context.Background(), r, s, "", nil)
	if err != nil || list != nil {
		t.Fatalf("List: %v, %v", list, err)
	}
	want := []string{"change-1/branch-point branch_point", "change-1/cabled written", "change-1/live given", "change-1/head head",
		"change-2/branch-point branch_point", "change-2/head head"}
	if got := rowRefs(res.Rows); !reflect.DeepEqual(got, want) {
		t.Errorf("rows %v\nwant %v", got, want)
	}
	if got := res.Rows[2].Resolved; !reflect.DeepEqual(got, Resolved{Ref: Ref{"change-1", "live"}, Branch: "change-1", Label: "live",
		ProposedChange: pc1, At: liveAt, AtSource: AtGiven, Description: "after its configuration is live", ID: "st-live"}) {
		t.Errorf("live resolves to %+v", got)
	}
	if bp, head := res.Rows[0], res.Rows[3]; bp.Branch != "main" || bp.At != branchedFrom || head.At != headAt {
		t.Errorf("branch point %+v, head %+v", bp.Resolved, head.Resolved)
	}
	if res.Branch != "" || res.Record != nil || len(res.Orphans) != 0 {
		t.Errorf("a listing with no filter, record or orphan: %+v", res)
	}

	res, _, err = List(context.Background(), r, s, "change-2", nil)
	if err != nil {
		t.Fatal(err)
	}
	if got := rowRefs(res.Rows); !reflect.DeepEqual(got, want[4:]) || res.Branch != "change-2" {
		t.Errorf("--branch change-2 lists %v, want %v", got, want[4:])
	}

	r, s = story()
	r.pcs = nil
	res, list, err = List(context.Background(), r, s, "change-1", nil)
	if err != nil || list != nil || len(res.Rows) != 0 {
		t.Errorf("no open proposed change: rows %v, findings %v, error %v; want none", res.Rows, list, err)
	}
}

// A listing resolves nothing for a run: a nine-digit, a future, a pre-branch-point at and
// a stale stage are shown with their source and refused nowhere.
func TestListRefusesNoAt(t *testing.T) {
	r, s := story(change1(
		mark("st-1", "nine", cabledAt, str("2026-10-16T17:30:00.123456789Z"), ""),
		mark("st-2", "future", cabledAt, str("2099-01-01T00:00:00Z"), ""),
		mark("st-3", "old", cabledAt, str("2026-10-16T17:00:00Z"), ""),
	))
	stale := freshStamps(headLatest)
	stale.Devices["n1"] = device("2026-10-16T17:29:00.000000+00:00", "2026-10-16T17:22:00.000000+00:00")
	s.byBranch["change-1"] = stale
	res, list, err := List(context.Background(), r, s, "", nil)
	if err != nil || list != nil {
		t.Fatalf("List refused: %v, %v", list, err)
	}
	if got, want := rowRefs(res.Rows), []string{"change-1/branch-point branch_point", "change-1/old given", "change-1/nine given",
		"change-1/future given", "change-1/head head"}; !reflect.DeepEqual(got, want) {
		t.Errorf("rows %v, want %v", got, want)
	}
	for _, c := range r.calls {
		if c != "Check" && c != "ProposedChanges " && c != "Branch change-1" && c != "Orphans" {
			t.Errorf("a listing asked %s", c)
		}
	}
}

// The kind absent is the one refusal of the whole listing; any other reader error is
// returned as it is.
func TestListKindAbsentAndReaderErrors(t *testing.T) {
	r, s := story()
	r.checkErr = &intent.StageKindError{Missing: []string{"description"}}
	_, list, err := List(context.Background(), r, s, "", nil)
	if err != nil || len(list) != 1 {
		t.Fatalf("kind absent: %v, %v", list, err)
	}
	if f := list[0]; f.Rule != findings.RuleStageKindAbsent || f.Object != intent.StageKind || f.Step != findings.StepResolve ||
		f.Severity != findings.Rejection {
		t.Errorf("kind absent: %+v", f)
	}
	unreachable := errors.New("Infrahub at http://infrahub.invalid is unreachable")
	for name, edit := range map[string]func(r *fakeReader, s *fakeStamper){
		"Check":           func(r *fakeReader, _ *fakeStamper) { r.checkErr = unreachable },
		"ProposedChanges": func(r *fakeReader, _ *fakeStamper) { r.pcErr = unreachable },
		"Branch":          func(r *fakeReader, _ *fakeStamper) { r.branchErr = unreachable },
		"Orphans":         func(r *fakeReader, _ *fakeStamper) { r.orphanErr = unreachable },
		"Stamps":          func(_ *fakeReader, s *fakeStamper) { s.err = unreachable },
	} {
		r, s := story()
		edit(r, s)
		if _, list, err := List(context.Background(), r, s, "", nil); !errors.Is(err, unreachable) || list != nil {
			t.Errorf("%s: %v, %v; want the error as it is", name, list, err)
		}
	}
}

// severities is each finding as its severity, rule and object.
func severities(list findings.List) []string {
	var out []string
	for _, f := range list {
		out = append(out, string(f.Severity)+" "+f.Rule+" "+f.Object)
	}
	return out
}

// A mark labelled like a derived stage is a rejection beside its row, every row still
// listed, the derived stage of that name with it.
func TestListReserved(t *testing.T) {
	r, s := story(change1(append(change1().Stages, mark("st-head", "head", "2026-10-16T17:27:00.000000+00:00", nil, ""))...), change2())
	res, list, err := List(context.Background(), r, s, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"change-1/branch-point branch_point", "change-1/cabled written", "change-1/head written", "change-1/live given",
		"change-1/head head", "change-2/branch-point branch_point", "change-2/head head"}
	if got := rowRefs(res.Rows); !reflect.DeepEqual(got, want) {
		t.Errorf("rows %v\nwant %v", got, want)
	}
	if got, want := severities(list), []string{"rejection stage.label.reserved change-1/head"}; !reflect.DeepEqual(got, want) {
		t.Errorf("findings %v, want %v", got, want)
	}
	if st := findings.NewDocument(findings.OpStageList, nil, list).Status; st.ExitCode() != findings.ExitRejected {
		t.Errorf("status %s; want rejected, exit 1", st)
	}
}

// Every stage has its row: one nothing names an at for — the head of a branch that holds
// nothing stamped, a mark Infrahub returned no stamp for — is listed with no at and warned
// of, stage.at.unresolved in the resolution's words, and the listing exits 0.
func TestListUnresolved(t *testing.T) {
	r, s := story(change1(mark("st-cabled", "cabled", "", nil, "after the link is cabled")), change2())
	s.byBranch["change-2"] = intent.Stamps{}
	res, list, err := List(context.Background(), r, s, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"change-1/branch-point branch_point", "change-1/cabled written", "change-1/head head",
		"change-2/branch-point branch_point", "change-2/head head"}
	if got := rowRefs(res.Rows); !reflect.DeepEqual(got, want) {
		t.Errorf("rows %v\nwant %v", got, want)
	}
	if cabled, head := res.Rows[1], res.Rows[4]; cabled.At != "" || head.At != "" || res.Rows[3].At == "" {
		t.Errorf("cabled at %q, change-2's head at %q; want neither, and change-2's branch point at its branched_from", cabled.At, head.At)
	}
	wantList := findings.List{
		{Severity: findings.Warning, Rule: findings.RuleStageAtUnresolved, Object: "change-1/cabled", Step: findings.StepResolve,
			Message: "stage change-1/cabled has no at: no as_of is written on it and Infrahub returned no updated_at for its label, " +
				"so it names no point in time"},
		{Severity: findings.Warning, Rule: findings.RuleStageAtUnresolved, Object: "change-2/head", Step: findings.StepResolve,
			Message: "stage change-2/head has no at: branch change-2 holds no stamped device, interface, link or artifact, " +
				"so it names no point in time"},
	}
	if !reflect.DeepEqual(list, wantList) {
		t.Errorf("findings:\n%+v\nwant\n%+v", list, wantList)
	}
	if st := findings.NewDocument(findings.OpStageList, nil, list).Status; st.ExitCode() != findings.ExitOK {
		t.Errorf("status %s; want exit 0", st)
	}
}

// A source branch deleted under its open proposed change: until Infrahub cancels it, its
// marks list at their own ats and its two derived stages with none, one stage.unknown
// warning saying why; no stamp of the missing branch is read, main is not read for it, and
// every other proposed change lists as usual. The listing exits 0.
func TestListBranchGone(t *testing.T) {
	r, s := story()
	delete(r.branches, "change-1")
	res, list, err := List(context.Background(), r, s, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"change-1/branch-point branch_point", "change-1/cabled written", "change-1/live given", "change-1/head head",
		"change-2/branch-point branch_point", "change-2/head head"}
	if got := rowRefs(res.Rows); !reflect.DeepEqual(got, want) {
		t.Errorf("rows %v\nwant %v", got, want)
	}
	var ats []string
	for _, row := range res.Rows {
		ats = append(ats, row.At)
	}
	if want := []string{"", cabledAt, liveAt, "", "2026-10-16T17:40:00.000000Z", "2026-10-16T17:41:00.000001+00:00"}; !reflect.DeepEqual(ats, want) {
		t.Errorf("ats %q\nwant %q", ats, want)
	}
	wantList := findings.List{{Severity: findings.Warning, Rule: findings.RuleStageUnknown, Object: "change-1", Step: findings.StepResolve,
		Message: "branch change-1 does not exist; the open proposed change pc-1 still names it " +
			"(Infrahub cancels it about sixteen seconds after a branch is deleted); until then its branch point and head have no at"}}
	if !reflect.DeepEqual(list, wantList) {
		t.Errorf("findings:\n%+v\nwant\n%+v", list, wantList)
	}
	if want := []string{"change-2@", "main@"}; !reflect.DeepEqual(s.calls, want) {
		t.Errorf("stamps read %v, want %v", s.calls, want)
	}
	if st := findings.NewDocument(findings.OpStageList, nil, list).Status; st.ExitCode() != findings.ExitOK {
		t.Errorf("status %s; want exit 0", st)
	}
}

// Each orphan is listed after the proposed changes, with its at and source, and warned of.
func TestListOrphans(t *testing.T) {
	r, s := story()
	r.orphans = []intent.Stage{
		mark("st-o1", "cabled", cabledAt, nil, ""),
		mark("st-o2", "live", cabledAt, str(liveAt), ""),
	}
	res, list, err := List(context.Background(), r, s, "change-2", nil)
	if err != nil || list.Rejected() {
		t.Fatal(err, list)
	}
	if want := []Orphan{{ID: "st-o1", Label: "cabled", At: cabledAt, AtSource: AtWritten},
		{ID: "st-o2", Label: "live", At: liveAt, AtSource: AtGiven}}; !reflect.DeepEqual(res.Orphans, want) {
		t.Errorf("orphans %+v, want %+v", res.Orphans, want)
	}
	want := findings.List{
		{Severity: findings.Warning, Rule: findings.RuleStageOrphaned, Object: "st-o1",
			Message: `stage "cabled" (id st-o1) names no proposed change: it was removed from its proposed change's fylgja_stages; delete the stage`},
		{Severity: findings.Warning, Rule: findings.RuleStageOrphaned, Object: "st-o2",
			Message: `stage "live" (id st-o2) names no proposed change: it was removed from its proposed change's fylgja_stages; delete the stage`},
	}
	if !reflect.DeepEqual(list, want) {
		t.Errorf("findings:\n%+v\nwant\n%+v", list, want)
	}
}

// main written since a proposed change's branch point warns once for it, main read once.
func TestListMainMoved(t *testing.T) {
	r, s := story()
	s.byBranch["main"] = intent.Stamps{Latest: "2026-10-16T17:30:00.000000+00:00"} // after change-1's branch point, before change-2's
	_, list, err := List(context.Background(), r, s, "", nil)
	if err != nil {
		t.Fatal(err)
	}
	if len(list) != 1 || list[0].Rule != findings.RuleStageMainMoved || list[0].Object != "change-1" || list.Rejected() {
		t.Errorf("findings %+v", list)
	}
	mains := 0
	for _, c := range s.calls {
		if c == "main@" {
			mains++
		}
	}
	if mains != 1 {
		t.Errorf("main's stamps read %d times (%v), want once", mains, s.calls)
	}
}

// The record's row is marked, by proposed change, label and kind; stage.twin.moved names
// what changed under it: its as_of edited, the mark deleted, the head moved, a rebase, the
// proposed change closed. A description edit changes nothing the twin was built from, and
// a listing of another branch says nothing of the record.
func TestListMarksTheRecord(t *testing.T) {
	cabled := record("cabled", cabledAt, AtWritten)
	const suffix = "; the twin is pinned to what it was built from"
	built := func(rec RecordView) string {
		return "the twin was built from stage " + rec.Ref().String() + " at branch " + rec.Branch + ", at " + rec.At +
			" (" + rec.AtSource + "); "
	}
	withMarks := func(marks ...intent.Stage) []intent.ProposedChange {
		return []intent.ProposedChange{change1(marks...), change2()}
	}
	live := change1().Stages[0]
	for _, c := range []struct {
		name    string
		pcs     []intent.ProposedChange
		edit    func(r *fakeReader, s *fakeStamper)
		record  RecordView
		branch  string
		marked  []string
		message string // the one stage.twin.moved expected, or none
	}{
		{name: "unchanged", record: cabled, marked: []string{"change-1/cabled"}},
		{name: "its description edited", record: cabled, marked: []string{"change-1/cabled"},
			pcs: withMarks(live, mark("st-cabled", "cabled", cabledAt, nil, "renamed"))},
		{name: "an as_of written on it", record: cabled, marked: []string{"change-1/cabled"},
			pcs:     withMarks(live, mark("st-cabled", "cabled", cabledAt, str("2026-10-16T17:26:00.000000+00:00"), "")),
			message: built(cabled) + "change-1/cabled now resolves to branch change-1, at 2026-10-16T17:26:00.000000+00:00 (given)" + suffix},
		{name: "the mark deleted", record: cabled, pcs: withMarks(live),
			message: built(cabled) + "change-1/cabled no longer exists" + suffix},
		{name: "the mark deleted, listing its branch", record: cabled, branch: "change-1", pcs: withMarks(live),
			message: built(cabled) + "change-1/cabled no longer exists" + suffix},
		{name: "the mark deleted, listing another branch", record: cabled, branch: "change-2", pcs: withMarks(live)},
		{name: "the head unmoved", record: record("head", headAt, AtHead), marked: []string{"change-1/head"}},
		{name: "the head moved", record: record("head", "2026-10-16T17:29:00.000001+00:00", AtHead), marked: []string{"change-1/head"},
			message: built(record("head", "2026-10-16T17:29:00.000001+00:00", AtHead)) +
				"change-1/head now resolves to branch change-1, at " + headAt + " (head)" + suffix},
		{name: "a rebase", record: record("branch-point", branchedFrom, AtBranchPoint), marked: []string{"change-1/branch-point"},
			edit: func(r *fakeReader, _ *fakeStamper) {
				r.branches["change-1"].BranchedFrom = "2026-10-16T17:37:22.940060Z"
			},
			message: built(record("branch-point", branchedFrom, AtBranchPoint)) +
				"change-1/branch-point now resolves to branch main, at 2026-10-16T17:37:22.940060Z (branch_point)" + suffix},
		{name: "the proposed change closed", record: cabled, pcs: []intent.ProposedChange{change2()},
			message: built(cabled) + "proposed change pc-1 is no longer open, so change-1/cabled is gone" + suffix},
		{name: "a mark labelled head is not the record's derived head", record: record("head", headAt, AtHead),
			pcs:    withMarks(live, mark("st-cabled", "cabled", cabledAt, nil, ""), mark("st-head", "head", "2026-10-16T17:27:00.000000+00:00", nil, "")),
			marked: []string{"change-1/head"}},
	} {
		t.Run(c.name, func(t *testing.T) {
			r, s := story(c.pcs...)
			if c.edit != nil {
				c.edit(r, s)
			}
			rec := c.record
			res, list, err := List(context.Background(), r, s, c.branch, &rec)
			if err != nil {
				t.Fatal(err)
			}
			var marked []string
			for _, row := range res.Rows {
				if row.Twin {
					marked = append(marked, row.Ref.String())
					if (row.ID == "") != rec.derived() {
						t.Errorf("marked %+v for a record from %s", row.Resolved, rec.AtSource)
					}
				}
			}
			if !reflect.DeepEqual(marked, c.marked) {
				t.Errorf("marked %v, want %v", marked, c.marked)
			}
			var moved findings.List
			for _, f := range list {
				if f.Rule == findings.RuleStageTwinMoved {
					moved = append(moved, f)
				}
			}
			var want findings.List
			if c.message != "" {
				want = findings.List{{Severity: findings.Warning, Rule: findings.RuleStageTwinMoved, Object: rec.Ref().String(),
					Message: c.message}}
			}
			if !reflect.DeepEqual(moved, want) {
				t.Errorf("findings:\n%+v\nwant\n%+v", moved, want)
			}
			if res.Record == nil || *res.Record != rec {
				t.Errorf("record %+v, want %+v", res.Record, rec)
			}
		})
	}
}

// Moved over the proposed change as Find reads it, as twin step files it beside its target's
// findings: nothing for a record whose stage still resolves to the record's (branch, at),
// and stage.twin.moved, in the listing's words and object, for a head written since, a
// mark's as_of edited, a mark deleted and a proposed change no longer open.
func TestMovedOfTheFoundChange(t *testing.T) {
	const suffix = "; the twin is pinned to what it was built from"
	built := func(rec RecordView) string {
		return "the twin was built from stage " + rec.Ref().String() + " at branch " + rec.Branch + ", at " + rec.At +
			" (" + rec.AtSource + "); "
	}
	live := change1().Stages[0]
	reopened := change1(change1().Stages...)
	reopened.ID = "pc-9"
	cabled := record("cabled", cabledAt, AtWritten)
	movedHead := record("head", "2026-10-16T17:29:00.000001+00:00", AtHead)
	for _, c := range []struct {
		name    string
		pcs     []intent.ProposedChange
		none    bool // no open proposed change was read: the caller passes nil
		record  RecordView
		message string // the one stage.twin.moved expected, or none
	}{
		{name: "a mark unmoved", record: cabled},
		{name: "a given mark unmoved", record: record("live", liveAt, AtGiven)},
		{name: "the branch point unmoved", record: record("branch-point", branchedFrom, AtBranchPoint)},
		{name: "the head unmoved", record: record("head", headAt, AtHead)},
		{name: "the head moved", record: movedHead,
			message: built(movedHead) + "change-1/head now resolves to branch change-1, at " + headAt + " (head)" + suffix},
		{name: "a mark's as_of edited", record: cabled,
			pcs: []intent.ProposedChange{change1(live, mark("st-cabled", "cabled", cabledAt,
				str("2026-10-16T17:26:00.000000+00:00"), ""))},
			message: built(cabled) + "change-1/cabled now resolves to branch change-1, at 2026-10-16T17:26:00.000000+00:00 (given)" + suffix},
		{name: "the mark deleted", record: cabled, pcs: []intent.ProposedChange{change1(live)},
			message: built(cabled) + "change-1/cabled no longer exists" + suffix},
		{name: "another proposed change opened on the branch", record: cabled, pcs: []intent.ProposedChange{reopened},
			message: built(cabled) + "proposed change pc-1 is no longer open, so change-1/cabled is gone" + suffix},
		{name: "no open proposed change", record: cabled, none: true,
			message: built(cabled) + "proposed change pc-1 is no longer open, so change-1/cabled is gone" + suffix},
	} {
		t.Run(c.name, func(t *testing.T) {
			var ch *Change
			if !c.none {
				ch = targetChange(t, c.pcs...)
			}
			var want findings.List
			if c.message != "" {
				want = findings.List{{Severity: findings.Warning, Rule: findings.RuleStageTwinMoved, Object: c.record.Ref().String(),
					Message: c.message}}
			}
			if got := Moved(ch, c.record); !reflect.DeepEqual(got, want) {
				t.Errorf("Moved = %+v\nwant %+v", got, want)
			}
		})
	}
}

// Two runs over one input give equal results: the listing is sorted whatever order the
// server returned, and maps never reach it unsorted (FR-016).
func TestListIsStable(t *testing.T) {
	rec := record("cabled", "2026-10-16T17:00:00.000000+00:00", AtWritten)
	run := func() (ListResult, findings.List) {
		r, s := story(change2(), change1(append(change1().Stages, mark("st-head", "head", cabledAt, nil, ""))...))
		r.orphans = []intent.Stage{mark("st-o", "o", cabledAt, nil, "")}
		s.byBranch["main"] = intent.Stamps{Latest: "2026-10-16T17:50:00.000000+00:00"}
		res, list, err := List(context.Background(), r, s, "", &rec)
		if err != nil {
			t.Fatal(err)
		}
		return res, list
	}
	a, la := run()
	for range 5 {
		b, lb := run()
		if !reflect.DeepEqual(a, b) || !reflect.DeepEqual(la, lb) {
			t.Fatalf("two runs differ:\n%+v %+v\n%+v %+v", a, la, b, lb)
		}
	}
}
