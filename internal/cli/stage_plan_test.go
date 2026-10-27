package cli

import (
	"encoding/json"
	"net/url"
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
)

// US1's acceptance scenarios through the harness (014, T033–T034): `stage plan --branch`
// over the fake Infrahub, one test per scenario, then the plan's text, its document and the
// refusals made before anything is asked of Infrahub.
//
// The proposed change planned is pc-1 on change-1, a draft. Where a test versions change-1,
// it held the fixture less its last link from linkless and the whole fixture from linked,
// so the step into a mark made after linked adds the link; its head is one microsecond
// after linked.
const (
	planLinkless = "2026-10-16T08:10:00.000000+00:00"
	planLinked   = "2026-10-16T08:40:00.000000+00:00"
	planLiveAt   = "2026-10-16T08:50:00.000000+00:00"
	planHeadAt   = "2026-10-16T08:40:00.000001+00:00"
)

// planInfrahub serves pc-1 on change-1, a draft holding marks, over the fake's main (the
// fixture, last written before the branch point); change-1 reads as the fixture less its
// last link.
func planInfrahub(t *testing.T, marks ...fakeStage) *fakeInfrahub {
	t.Helper()
	f := newFakeInfrahub(t)
	f.branches[lessLink] = withoutLastLink(t, lessLink)
	f.change("pc-1", lessLink, marks...).Draft = true
	return f
}

// versioned gives change-1 its two intents: the fixture less its last link from
// planLinkless, the whole fixture from planLinked.
func versioned(t *testing.T, f *fakeInfrahub) {
	t.Helper()
	whole, err := ctm.Load(repoPath("testdata", "ctm", "three-node.json"))
	if err != nil {
		t.Fatal(err)
	}
	whole.Envelope.Branch = lessLink
	f.versions = map[string][]fakeVersion{lessLink: {
		{Since: planLinkless, CTM: withoutLastLink(t, lessLink)},
		{Since: planLinked, CTM: whole},
	}}
}

// emptyMain makes main the development host's: no network on it (R-04), so no device
// carries the scope's tag and the read refuses it scope.empty (017).
func emptyMain(f *fakeInfrahub) {
	f.branches["main"] = &ctm.CTM{}
}

// twoMarks are scenario 2's marks, served out of order: live with an as_of (given) after
// the link, and cabled with none (written), marked before it.
func twoMarks() []fakeStage {
	return []fakeStage{
		mark("st-live", "live", planLiveAt, "the leaf live"),
		{ID: "st-cabled", Label: "cabled", WrittenAt: cabledAt, Description: "the leaf cabled"},
	}
}

// planStep is one step of the plan block as stages.schema.json gives it.
type planStep struct {
	From         string  `json:"from"`
	To           string  `json:"to"`
	FromBundleID *string `json:"from_bundle_id"`
	ToBundleID   *string `json:"to_bundle_id"`
	Computed     bool    `json:"computed"`
	NotComputed  string  `json:"not_computed"`
	Unchanged    *bool   `json:"unchanged"`
	Links        *struct {
		Added, Removed []struct {
			ID string `json:"id"`
		}
	} `json:"links"`
}

// planned is the plan block of a stage plan's document: its stages' references, their at
// sources, which compiled, and its steps decoded.
func planned(t *testing.T, doc *findings.Document) (stages []findings.PlanStage, steps []planStep) {
	t.Helper()
	if doc.Plan == nil {
		t.Fatalf("the document carries no plan block: %+v", doc)
	}
	for _, raw := range doc.Plan.Steps {
		var s planStep
		if err := json.Unmarshal(raw, &s); err != nil {
			t.Fatalf("a step does not decode: %v\n%s", err, raw)
		}
		steps = append(steps, s)
	}
	return doc.Plan.Stages, steps
}

// stageRefs is each planned stage's reference, in order.
func stageRefs(stages []findings.PlanStage) []string {
	out := make([]string, len(stages))
	for i, st := range stages {
		out[i] = st.Ref
	}
	return out
}

// compiledRefs is the reference of each planned stage that compiled, in order.
func compiledRefs(stages []findings.PlanStage) []string {
	var out []string
	for _, st := range stages {
		if st.BundleID != nil {
			out = append(out, st.Ref)
		}
	}
	return out
}

// rulesOf is each finding's rule and object, as "rule object".
func rulesOf(list findings.List) []string {
	out := make([]string, len(list))
	for i, f := range list {
		out[i] = f.Rule + " " + f.Object
	}
	return out
}

// readAt reports whether the fake was asked any of a branch's intent (its devices or their
// ports) pinned at at: what only a stage's read asks.
func readAt(f *fakeInfrahub, at string) bool {
	for _, r := range f.requests() {
		q, _ := url.ParseQuery(r.Query)
		if q.Get("at") == at && (r.Operation == "Devices" || r.Operation == "Ports") {
			return true
		}
	}
	return false
}

// Scenario 1: nothing marked is two stages, the branch point (main at the branch's
// branched_from) and the head (the branch one microsecond after its latest stamp), and one
// step. Where main carries the contract and the devices both compile and the step between
// them is the link the branch removed, exit 0; on an empty main, as the development host's
// is, the branch point is refused scope.empty at its read, the step is not
// computed, the head still compiles, and the plan exits 1 (R-04).
func TestStagePlanNothingMarked(t *testing.T) {
	t.Run("main carries the contract", func(t *testing.T) {
		useStateRoot(t)
		useService(t, nil)
		f := planInfrahub(t)
		f.start()

		code, doc, raw := stageDoc(t, "plan", "--branch", lessLink)
		stages, steps := planned(t, doc)
		if code != findings.ExitOK || doc.Status != findings.StatusOK || len(doc.Findings) != 0 {
			t.Errorf("exit %d, status %s, findings %v; want 0, ok and none", code, doc.Status, rulesOf(doc.Findings))
		}
		want := []string{"change-1/branch-point", "change-1/head"}
		if !slices.Equal(stageRefs(stages), want) || !slices.Equal(compiledRefs(stages), want) {
			t.Fatalf("stages %v, compiled %v; want %v both compiled\n%s", stageRefs(stages), compiledRefs(stages), want, raw)
		}
		for i, w := range []struct{ branch, at, source string }{
			{"main", fakeBranchedFrom, findings.AtSourceBranchPoint},
			{lessLink, fakeHeadAt, findings.AtSourceHead},
		} {
			if st := stages[i]; st.Branch != w.branch || st.At != w.at || st.AtSource != w.source {
				t.Errorf("%s: branch %s at %s (%s); want %s at %s (%s)", st.Ref, st.Branch, st.At, st.AtSource, w.branch, w.at, w.source)
			}
		}
		gone := f.fixture.Links[len(f.fixture.Links)-1].ID
		if len(steps) != 1 || !steps[0].Computed || steps[0].Links == nil || len(steps[0].Links.Removed) != 1 ||
			steps[0].Links.Removed[0].ID != gone || len(steps[0].Links.Added) != 0 {
			t.Errorf("steps %+v; want one, removing link %s\n%s", steps, gone, raw)
		}
	})

	t.Run("an empty main", func(t *testing.T) {
		useStateRoot(t)
		useService(t, nil)
		f := planInfrahub(t)
		emptyMain(f)
		f.start()

		code, doc, raw := stageDoc(t, "plan", "--branch", lessLink)
		stages, steps := planned(t, doc)
		if code != findings.ExitRejected || doc.Status != findings.StatusRejected {
			t.Errorf("exit %d, status %s; want 1, rejected", code, doc.Status)
		}
		if !slices.Equal(stageRefs(stages), []string{"change-1/branch-point", "change-1/head"}) ||
			!slices.Equal(compiledRefs(stages), []string{"change-1/head"}) {
			t.Fatalf("stages %v, compiled %v; want the head alone compiled\n%s", stageRefs(stages), compiledRefs(stages), raw)
		}
		bp := stages[0]
		if len(bp.Findings) != 1 || bp.Findings[0].Rule != findings.RuleScopeEmpty || bp.Findings[0].Object != "tag:fylgja" ||
			bp.Findings[0].Step != findings.StepRead || bp.Branch != "main" || bp.At != fakeBranchedFrom || bp.Read != nil {
			t.Errorf("the branch point %+v; want main at the branch point refused %s at its read", bp, findings.RuleScopeEmpty)
		}
		if len(steps) != 1 || steps[0].Computed || steps[0].NotComputed != "change-1/branch-point was refused" ||
			steps[0].FromBundleID != nil || steps[0].ToBundleID == nil || *steps[0].ToBundleID != *stages[1].BundleID {
			t.Errorf("steps %+v; want one not computed, the branch point refused\n%s", steps, raw)
		}
	})
}

// Scenario 2: two marks, the first with no as_of and the second with one, are four stages:
// the branch point, the marks in order of their at whatever order Infrahub returns them in,
// and the head, last though the second mark's at is later than it; three steps. The first
// mark's at is its own write stamp (written) and the second's its as_of (given), and the
// plan says which. The step into the second mark adds the link written between them, and
// the step from it to the head differs in provenance alone.
func TestStagePlanTwoMarks(t *testing.T) {
	useStateRoot(t)
	useService(t, nil)
	f := planInfrahub(t, twoMarks()...)
	versioned(t, f)
	f.start()

	code, stdout, stderr := runStage(t, "plan", "--branch", lessLink)
	for _, want := range []string{
		`change-1/cabled: branch change-1 at ` + cabledAt + ` (written), "the leaf cabled"`,
		`change-1/live: branch change-1 at ` + planLiveAt + ` (given), "the leaf live"`,
		`change-1/head: branch change-1 at ` + planHeadAt + ` (head)`,
	} {
		if !strings.Contains(stdout, want+"\n") {
			t.Errorf("stage plan lacks %q:\n%s%s", want, stdout, stderr)
		}
	}
	if code != findings.ExitOK {
		t.Errorf("exit %d, want 0:\n%s%s", code, stdout, stderr)
	}

	code, doc, raw := stageDoc(t, "plan", "--branch", lessLink)
	stages, steps := planned(t, doc)
	want := []string{"change-1/branch-point", "change-1/cabled", "change-1/live", "change-1/head"}
	if code != findings.ExitOK || !slices.Equal(stageRefs(stages), want) || !slices.Equal(compiledRefs(stages), want) || len(steps) != 3 {
		t.Fatalf("exit %d, stages %v, compiled %v, %d steps; want 0, %v all compiled and 3 steps\n%s",
			code, stageRefs(stages), compiledRefs(stages), len(steps), want, raw)
	}
	for i, w := range []struct{ at, source string }{
		{fakeBranchedFrom, findings.AtSourceBranchPoint},
		{cabledAt, findings.AtSourceWritten},
		{planLiveAt, findings.AtSourceGiven},
		{planHeadAt, findings.AtSourceHead},
	} {
		if st := stages[i]; st.At != w.at || st.AtSource != w.source {
			t.Errorf("%s at %s (%s); want at %s (%s)", st.Ref, st.At, st.AtSource, w.at, w.source)
		}
	}
	link := f.fixture.Links[len(f.fixture.Links)-1].ID
	for i, w := range []struct {
		from, to       string
		removed, added []string
		unchanged      bool
	}{
		{"change-1/branch-point", "change-1/cabled", []string{link}, nil, false},
		{"change-1/cabled", "change-1/live", nil, []string{link}, false},
		{"change-1/live", "change-1/head", nil, nil, true},
	} {
		s := steps[i]
		var removed, added []string
		if s.Links != nil {
			for _, l := range s.Links.Removed {
				removed = append(removed, l.ID)
			}
			for _, l := range s.Links.Added {
				added = append(added, l.ID)
			}
		}
		unchanged := s.Unchanged != nil && *s.Unchanged
		if s.From != w.from || s.To != w.to || !s.Computed || unchanged != w.unchanged ||
			!slices.Equal(removed, w.removed) || !slices.Equal(added, w.added) {
			t.Errorf("step %d %+v; want %s → %s removing %v, adding %v, unchanged %v", i, s, w.from, w.to, w.removed, w.added, w.unchanged)
		}
	}
	mustQuoteNoContent(t, f, stdout, stderr, raw)
}

// D-048: the cable n1:ethernet-1/1 — n2:ethernet-1/1 deleted at 09:30, after the artifacts
// were generated at 09:00, moves no stamp; the event log records it, then each end's port's
// connector removed. The head is listed one microsecond after the last of those events; a
// stage marked after the delete, and the head, are refused stale for n1 and n2, whose ports
// the events name, and never for n3; a mark before it is fresh.
func TestStagePlanRemoval(t *testing.T) {
	const (
		beforeAt  = "2026-10-16T09:20:00.000000+00:00"
		deletedAt = "2026-10-16T09:30:00.031152+00:00"
		n1At      = "2026-10-16T09:30:00.040000+00:00"
		n2At      = "2026-10-16T09:30:00.041000+00:00"
		markedAt  = "2026-10-16T09:40:00.000000+00:00"
	)
	useStateRoot(t)
	useService(t, nil)
	f := planInfrahub(t,
		mark("st-removed", "removed", markedAt, "after the delete"),
		mark("st-before", "before", beforeAt, "before the delete"))
	f.events = map[string][]fakeEvent{lessLink: {
		// The query groups' churn names n3, and is never intent.
		{Name: "infrahub.node.updated", At: "2026-10-16T09:30:03.000000+00:00", Kind: "DcimDevice", ID: fakeDeviceID("n3"),
			Rel: "member_of_groups", Peers: []string{"group-1"}},
		{Name: "infrahub.node.updated", At: n2At, Kind: "InterfacePhysical", ID: "n2:ethernet-1/1", Rel: "connector",
			Peers: []string{"cable-removed"}},
		{Name: "infrahub.node.updated", At: n1At, Kind: "InterfacePhysical", ID: "n1:ethernet-1/1", Rel: "connector",
			Peers: []string{"cable-removed"}},
		{Name: "infrahub.node.updated", At: n1At, Kind: "CoreGraphQLQueryGroup", ID: "group-1", Rel: "members",
			Peers: []string{fakeDeviceID("n3")}},
		{Name: "infrahub.node.deleted", At: deletedAt, Kind: "DcimCable", ID: "cable-removed", Rel: "connected_endpoints",
			Peers: []string{"n1:ethernet-1/1", "n2:ethernet-1/1"}},
	}}
	f.start()

	code, doc, raw := stageDoc(t, "list", "--branch", lessLink)
	if want := "change-1/head change-1 2026-10-16T09:30:00.041001+00:00 head "; code != findings.ExitOK ||
		!slices.Contains(listedRows(doc), want) {
		t.Fatalf("exit %d, rows %q; want 0 with %q\n%s", code, listedRows(doc), want, raw)
	}

	code, doc, raw = stageDoc(t, "plan", "--branch", lessLink)
	stages, _ := planned(t, doc)
	want := []string{"change-1/branch-point", "change-1/before", "change-1/removed", "change-1/head"}
	if code != findings.ExitRejected || !slices.Equal(stageRefs(stages), want) {
		t.Fatalf("exit %d, stages %v; want 1 with %v\n%s", code, stageRefs(stages), want, raw)
	}
	if got := compiledRefs(stages); !slices.Equal(got, []string{"change-1/branch-point", "change-1/before"}) {
		t.Errorf("compiled %v; want the branch point and before", got)
	}
	stale := []string{findings.RuleStageArtifactStale + " n1", findings.RuleStageArtifactStale + " n2"}
	for _, st := range stages[2:] {
		if got := rulesOf(st.Findings); !slices.Equal(got, stale) {
			t.Errorf("%s's findings %v; want stale for n1 and n2 alone", st.Ref, got)
		}
	}
	for i, at := range []string{n1At, n2At} {
		fd := stages[2].Findings[i]
		if has := "its intent on change-1 was written at " + at + " (Infrahub's event log: infrahub.node.updated of a " +
			"InterfacePhysical; its latest stamp " + fakeWritten + "), later than its artifact device-config was generated " +
			"(checksum stamped " + fakeWritten; !strings.Contains(fd.Message, has) {
			t.Errorf("%s's finding lacks %q: %s", fd.Object, has, fd.Message)
		}
	}
	mustQuoteNoContent(t, f, "", "", raw)
}

// Scenario 3: a stage marked after an intent change and before the artifacts were
// regenerated is refused stale, one stage.artifact.stale per device whose intent is newer
// than its artifact, naming exactly those devices and both ways to regenerate before
// marking again; nothing of the branch is read at it. The other stages are still planned,
// and the steps touching the refused stage say it was refused.
//
// n1 and n2 are edited at 09:30, their links untouched, and their artifacts are not
// regenerated (stamped 09:00, as n3's intent and artifact are, though n3 shares a link with
// each); the proposed change's checks then run, completing at 09:50.
// edited, marked at 09:40 between the two, is stale; checked, marked at 09:55, is not, and
// neither is the head, whose validator is read unpinned (D-046).
func TestStagePlanStaleMark(t *testing.T) {
	const (
		editedAt  = "2026-10-16T09:30:00.000000+00:00"
		markedAt  = "2026-10-16T09:40:00.000000+00:00"
		checkedAt = "2026-10-16T09:50:00.000000+00:00"
		laterAt   = "2026-10-16T09:55:00.000000+00:00"
	)
	useStateRoot(t)
	useService(t, nil)
	f := planInfrahub(t,
		mark("st-checked", "checked", laterAt, "after the checks"),
		mark("st-edited", "edited", markedAt, "before the checks"))
	f.changes[0].Validated = []string{checkedAt}
	f.stamps = map[string]fakeDeviceStamps{
		lessLink + "/n1": {Intent: editedAt, Artifact: fakeWritten},
		lessLink + "/n2": {Intent: editedAt, Artifact: fakeWritten},
	}
	f.start()

	code, doc, raw := stageDoc(t, "plan", "--branch", lessLink)
	stages, steps := planned(t, doc)
	want := []string{"change-1/branch-point", "change-1/edited", "change-1/checked", "change-1/head"}
	if code != findings.ExitRejected || !slices.Equal(stageRefs(stages), want) {
		t.Fatalf("exit %d, stages %v; want 1 with %v\n%s", code, stageRefs(stages), want, raw)
	}
	if got := compiledRefs(stages); !slices.Equal(got, []string{"change-1/branch-point", "change-1/checked", "change-1/head"}) {
		t.Errorf("compiled %v; want every stage but edited", got)
	}
	edited := stages[1]
	if got := rulesOf(edited.Findings); !slices.Equal(got, []string{
		findings.RuleStageArtifactStale + " n1", findings.RuleStageArtifactStale + " n2"}) {
		t.Errorf("edited's findings %v; want stale for n1 and n2 alone", got)
	}
	for _, fd := range edited.Findings {
		for _, has := range []string{
			"device " + fd.Object + ": its intent on change-1 was written at " + editedAt,
			"later than its artifact device-config was generated (checksum stamped " + fakeWritten + "; no artifact validator of the proposed change had completed)",
			"stage change-1/edited was marked before the artifacts were regenerated",
			"fylgja-fixture -generate", "POST /api/artifact/generate", "CoreProposedChangeRunCheck", "and mark again",
		} {
			if !strings.Contains(fd.Message, has) {
				t.Errorf("%s's finding lacks %q: %s", fd.Object, has, fd.Message)
			}
		}
		if fd.Severity != findings.Rejection || fd.Step != findings.StepResolve {
			t.Errorf("%+v; want a rejection at resolve", fd)
		}
	}
	if edited.BundleID != nil || edited.Read != nil || edited.At != "" || readAt(f, markedAt) {
		t.Errorf("edited %+v was read or compiled; a stale stage is refused before its read", edited)
	}
	if !slices.Equal(rulesOf(doc.Findings), rulesOf(edited.Findings)) {
		t.Errorf("the document's findings %v; want edited's alone", rulesOf(doc.Findings))
	}
	for i, w := range []struct {
		computed bool
		why      string
	}{{false, "change-1/edited was refused"}, {false, "change-1/edited was refused"}, {true, ""}} {
		if steps[i].Computed != w.computed || steps[i].NotComputed != w.why {
			t.Errorf("step %s → %s computed %v (%s); want %v (%s)", steps[i].From, steps[i].To, steps[i].Computed,
				steps[i].NotComputed, w.computed, w.why)
		}
	}

	_, stdout, _ := runStage(t, "plan", "--branch", lessLink)
	for _, want := range []string{
		"change-1/edited: refused (stage.artifact.stale)\n  rejection stage.artifact.stale [step resolve] n1: device n1: ",
		"\n  rejection stage.artifact.stale [step resolve] n2: device n2: ",
		"step change-1/branch-point → change-1/edited (",
		"): not computed (change-1/edited was refused)\n",
	} {
		if !strings.Contains(stdout, want) {
			t.Errorf("stage plan lacks %q:\n%s", want, stdout)
		}
	}
}

// Scenario 4: an as_of before the branch point and one later than now are each refused,
// saying which, and the rest of the plan goes on.
func TestStagePlanAtOutsideTheBranch(t *testing.T) {
	const (
		earlyAt  = "2026-10-16T07:30:00.000000+00:00"
		futureAt = "2099-01-01T00:00:00.000000+00:00"
	)
	useStateRoot(t)
	useService(t, nil)
	f := planInfrahub(t, mark("st-future", "future", futureAt, ""), mark("st-early", "early", earlyAt, ""))
	f.start()

	code, doc, raw := stageDoc(t, "plan", "--branch", lessLink)
	stages, steps := planned(t, doc)
	want := []string{"change-1/branch-point", "change-1/early", "change-1/future", "change-1/head"}
	if code != findings.ExitRejected || !slices.Equal(stageRefs(stages), want) ||
		!slices.Equal(compiledRefs(stages), []string{"change-1/branch-point", "change-1/head"}) {
		t.Fatalf("exit %d, stages %v, compiled %v; want 1 with %v, the ends compiled\n%s",
			code, stageRefs(stages), compiledRefs(stages), want, raw)
	}
	for i, w := range []struct{ rule, says string }{
		{findings.RuleStageAtBeforeBranchPoint, "stage change-1/early has at " + earlyAt + ", before the branch point " + fakeBranchedFrom +
			" of change-1, and before the branch was created at " + fakeBranchedFrom + "; a stage names a moment on its source branch"},
		{findings.RuleStageAtUnresolved, "stage change-1/future has at " + futureAt + " (given), later than the current time "},
	} {
		st := stages[i+1]
		if len(st.Findings) != 1 || st.Findings[0].Rule != w.rule || st.Findings[0].Object != st.Ref ||
			!strings.HasPrefix(st.Findings[0].Message, w.says) {
			t.Errorf("%s's findings %+v; want %s saying %q", st.Ref, st.Findings, w.rule, w.says)
		}
	}
	if steps[1].NotComputed != "change-1/early and change-1/future were refused" {
		t.Errorf("the step between the two refused %+v; want both named", steps[1])
	}
}

// Scenario 5: a rebase after two marks moves the branch point past both, so both are
// refused at once, each saying a rebase moved the branch point past it; the branch point,
// now main at the rebase, and the head are still planned.
func TestStagePlanAfterARebase(t *testing.T) {
	const (
		secondAt = "2026-10-16T08:45:00.000000+00:00"
		rebaseAt = "2026-10-16T08:55:00.000000+00:00"
	)
	useStateRoot(t)
	useService(t, nil)
	f := planInfrahub(t, mark("st-cabled", "cabled", cabledAt, ""), mark("st-live", "live", secondAt, ""))
	f.changes[0].BranchedFrom = rebaseAt
	f.start()

	code, doc, raw := stageDoc(t, "plan", "--branch", lessLink)
	stages, _ := planned(t, doc)
	if code != findings.ExitRejected || !slices.Equal(compiledRefs(stages), []string{"change-1/branch-point", "change-1/head"}) {
		t.Fatalf("exit %d, compiled %v; want 1 with the ends alone compiled\n%s", code, compiledRefs(stages), raw)
	}
	if bp := stages[0]; bp.Branch != "main" || bp.At != rebaseAt {
		t.Errorf("the branch point is %s at %s; want main at the rebase %s", bp.Branch, bp.At, rebaseAt)
	}
	if got := rulesOf(doc.Findings); !slices.Equal(got, []string{
		findings.RuleStageAtBeforeBranchPoint + " change-1/cabled", findings.RuleStageAtBeforeBranchPoint + " change-1/live"}) {
		t.Errorf("findings %v; want both marks before the branch point", got)
	}
	for _, fd := range doc.Findings {
		if !strings.Contains(fd.Message, ", before the branch point "+rebaseAt+" of change-1: a rebase at "+rebaseAt+
			" moved the branch point past it (the branch was created at "+fakeBranchedFrom+"); mark the stage again, or delete it") {
			t.Errorf("%s does not name the rebase: %s", fd.Object, fd.Message)
		}
	}
}

// Scenario 6: main written since the branch point is the warning stage.main.moved, filed
// once with the branch point, which still reads main as it was then; nothing is refused,
// and the plan exits 0.
func TestStagePlanMainMoved(t *testing.T) {
	const movedAt = "2026-10-16T08:30:00.000000+00:00"
	useStateRoot(t)
	useService(t, nil)
	f := planInfrahub(t, twoMarks()...)
	f.versions = map[string][]fakeVersion{"main": {{Since: movedAt, CTM: f.branches["main"]}}}
	f.start()

	code, doc, raw := stageDoc(t, "plan", "--branch", lessLink)
	stages, _ := planned(t, doc)
	if code != findings.ExitOK || doc.Status != findings.StatusOK || !slices.Equal(compiledRefs(stages), stageRefs(stages)) {
		t.Errorf("exit %d, status %s, compiled %v of %v; want 0, ok and every stage compiled\n%s",
			code, doc.Status, compiledRefs(stages), stageRefs(stages), raw)
	}
	want := "main has moved since change-1's branch point: its latest write is " + movedAt + ", the branch point " +
		fakeBranchedFrom + "; the branch point stage still reads main as it was then, and nothing is refused"
	if len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleStageMainMoved || doc.Findings[0].Severity != findings.Warning ||
		doc.Findings[0].Object != lessLink || doc.Findings[0].Message != want {
		t.Errorf("findings %+v; want the one warning %s saying %q", doc.Findings, findings.RuleStageMainMoved, want)
	}
	if len(stages[0].Findings) != 1 || stages[0].Findings[0].Rule != findings.RuleStageMainMoved {
		t.Errorf("the branch point's findings %+v; want the warning filed with it", stages[0].Findings)
	}

	_, stdout, _ := runStage(t, "plan", "--branch", lessLink)
	if !strings.Contains(stdout, "  read: 3 devices (nokia_srlinux 3), 9 interfaces, 3 links, 3 artifacts, 0 lossy mappings, 0 shared ports\n"+
		"  warning stage.main.moved [step resolve] change-1: "+want+"\n") {
		t.Errorf("the warning is not printed under the branch point:\n%s", stdout)
	}
}

// A stage whose read cannot run is failed rather than refused: operation.failed at its
// read, the plan going on to the other stages and the steps touching it not computed. The
// plan ran and reported every stage, so it exits 1, never the 2 of an operation that did
// not run (contracts/stage-commands.md, "stage plan").
func TestStagePlanStageFailed(t *testing.T) {
	useStateRoot(t)
	useService(t, nil)
	f := planInfrahub(t, twoMarks()...)
	versioned(t, f)
	f.readStatus = map[string]int{"main": 500}
	f.start()

	code, doc, raw := stageDoc(t, "plan", "--branch", lessLink)
	stages, steps := planned(t, doc)
	if code != findings.ExitRejected || doc.Status != findings.StatusRejected {
		t.Errorf("exit %d, status %s; want 1, rejected\n%s", code, doc.Status, raw)
	}
	want := []string{"change-1/branch-point", "change-1/cabled", "change-1/live", "change-1/head"}
	if !slices.Equal(stageRefs(stages), want) || !slices.Equal(compiledRefs(stages), want[1:]) {
		t.Fatalf("stages %v, compiled %v; want %v, all but the branch point compiled\n%s",
			stageRefs(stages), compiledRefs(stages), want, raw)
	}
	bp := stages[0]
	if len(bp.Findings) != 1 || bp.Findings[0].Severity != findings.Rejection || bp.Findings[0].Rule != findings.RuleOperationFailed ||
		bp.Findings[0].Step != findings.StepRead || bp.Findings[0].Object != "change-1/branch-point" || bp.Read != nil {
		t.Errorf("the branch point %+v; want it failed %s at its read, with no read", bp, findings.RuleOperationFailed)
	}
	if len(steps) != 3 || steps[0].Computed || steps[0].NotComputed != "change-1/branch-point was refused" ||
		steps[0].FromBundleID != nil || !steps[1].Computed || !steps[2].Computed {
		t.Errorf("steps %+v; want the first not computed, the branch point failed, and the other two computed\n%s", steps, raw)
	}
	if !slices.Equal(rulesOf(doc.Findings), []string{findings.RuleOperationFailed + " change-1/branch-point"}) {
		t.Errorf("findings %v; want the branch point's operation.failed alone", rulesOf(doc.Findings))
	}

	code, stdout, stderr := runStage(t, "plan", "--branch", lessLink)
	if code != findings.ExitRejected || !strings.Contains(stdout, "change-1/branch-point: failed ("+findings.RuleOperationFailed+")\n") {
		t.Errorf("exit %d, stdout\n%s; want 1 and the branch point printed failed", code, stdout)
	}
	mustQuoteNoContent(t, f, stdout, stderr, raw)
}

// The plan's text, line by line (contracts/stage-commands.md, "stage plan"): the heading
// naming the proposed change, its destination and that it is a draft; each stage as it
// finishes, a compiled one by its resolution, bundle_id and read, a refused one by its rule
// with its findings indented under it in the document's text-line shape, as M10's plan
// printed them; and each step as it is known, between the two stages it joins: not
// computed, the step block by node and port name as the bundles give them, unchanged.
// stderr carries the document's findings, as every command's text does.
func TestStagePlanText(t *testing.T) {
	paths := useStateRoot(t)
	useService(t, nil)
	f := planInfrahub(t, twoMarks()...)
	versioned(t, f)
	emptyMain(f)
	f.start()

	code, stdout, stderr := runStage(t, "plan", "--branch", lessLink)
	_, doc, _ := stageDoc(t, "plan", "--branch", lessLink)
	stages, steps := planned(t, doc)
	if len(stages) != 4 || len(steps) != 3 {
		t.Fatalf("the plan %+v", doc.Plan)
	}
	// Each compiled stage names its snapshot above its bundle (018), filed in the store; the
	// branch point, refused at its read, names neither.
	if stages[0].SnapshotID != nil || stages[0].BundleID != nil {
		t.Errorf("the branch point names snapshot %v and bundle %v; want null for each", stages[0].SnapshotID, stages[0].BundleID)
	}
	var snapshots, files []string
	for _, st := range stages[1:] {
		if st.SnapshotID == nil || st.BundleID == nil {
			t.Fatalf("%s names snapshot %v and bundle %v; want both", st.Ref, st.SnapshotID, st.BundleID)
		}
		snapshots = append(snapshots, *st.SnapshotID)
		files = append(files, *st.SnapshotID+".json")
	}
	if got := filedSnapshots(t, paths); !slices.Equal(got, sortedCopy(files...)) {
		t.Errorf("the store holds %v; want the three stages' snapshots %v", got, files)
	}
	cabled, live, head := *stages[1].BundleID, *stages[2].BundleID, *stages[3].BundleID
	const missing = "rejection scope.empty [step read] tag:fylgja: scope tag:fylgja selects no device on branch main at " + fakeBranchedFrom
	want := strings.Join([]string{
		`proposed change "change pc-1" (pc-1) on branch change-1 → main, draft (4 stages), scope tag:fylgja`,
		`change-1/branch-point: refused (scope.empty)`,
		`  ` + missing,
		`step change-1/branch-point → change-1/cabled (— → ` + cabled[:8] + `…): not computed (change-1/branch-point was refused)`,
		`change-1/cabled: branch change-1 at ` + cabledAt + ` (written), "the leaf cabled"`,
		`  snapshot_id ` + snapshots[0],
		`  bundle_id ` + cabled,
		`  read: 3 devices (nokia_srlinux 3), 9 interfaces, 2 links, 3 artifacts, 0 lossy mappings, 0 shared ports`,
		`step change-1/cabled → change-1/live (` + cabled[:8] + `… → ` + live[:8] + `…):`,
		`  nodes: ~n2 (bootstrap); ~n3 (bootstrap)`,
		`  links: +n2:e1-2 — n3:e1-1`,
		`  artifacts: unchanged`,
		`change-1/live: branch change-1 at ` + planLiveAt + ` (given), "the leaf live"`,
		`  snapshot_id ` + snapshots[1],
		`  bundle_id ` + live,
		`  read: 3 devices (nokia_srlinux 3), 9 interfaces, 3 links, 3 artifacts, 0 lossy mappings, 0 shared ports`,
		`step change-1/live → change-1/head (` + live[:8] + `… → ` + head[:8] + `…): unchanged; the ids differ by provenance alone`,
		`change-1/head: branch change-1 at ` + planHeadAt + ` (head)`,
		`  snapshot_id ` + snapshots[2],
		`  bundle_id ` + head,
		`  read: 3 devices (nokia_srlinux 3), 9 interfaces, 3 links, 3 artifacts, 0 lossy mappings, 0 shared ports`,
	}, "\n") + "\n"
	if stdout != want {
		t.Errorf("stage plan printed\n%s\nwant\n%s", stdout, want)
	}
	if code != findings.ExitRejected || stderr != missing+"\n1 finding(s): 1 rejection, 0 warning, 0 info\n" {
		t.Errorf("exit %d, stderr\n%s; want 1 and the one finding", code, stderr)
	}
	mustQuoteNoContent(t, f, stdout, stderr)
}

// stage plan --scope reads every stage under the scope given, whatever the server's
// default (017; US5 scenario 5): each stage's read and stamps send the tag x, which no
// device of the fake carries, so the branch point and each mark are refused scope.empty
// naming tag:x at their read, and the head, whose at is computed from the branch's stamps
// under the scope, has none and is refused scope.empty naming tag:x at resolve, before any
// read, the stamps having selected no device (R-10; FR-015). The heading and the document
// name the scope.
func TestStagePlanReadsUnderTheScopeGiven(t *testing.T) {
	useStateRoot(t)
	useService(t, nil)
	f := planInfrahub(t, twoMarks()...)
	versioned(t, f)
	f.start()

	code, stdout, _ := runStage(t, "plan", "--branch", lessLink, "--scope", "tag:x")
	_, doc, _ := stageDoc(t, "plan", "--branch", lessLink, "--scope", "tag:x")
	if want := `proposed change "change pc-1" (pc-1) on branch change-1 → main, draft (4 stages), scope tag:x`; code != findings.ExitRejected ||
		lineOf(stdout, 1) != want {
		t.Errorf("exit %d, stdout\n%s\nwant 1, the heading %q", code, stdout, want)
	}
	if doc.Subject == nil || doc.Subject.Scope != "tag:x" {
		t.Errorf("subject %+v; want the scope tag:x", doc.Subject)
	}
	stages, _ := planned(t, doc)
	if want := []string{"change-1/branch-point", "change-1/cabled", "change-1/live", "change-1/head"}; !slices.Equal(stageRefs(stages), want) {
		t.Fatalf("stages %v; want %v", stageRefs(stages), want)
	}
	for _, st := range stages[:3] {
		if len(st.Findings) != 1 || st.Findings[0].Rule != findings.RuleScopeEmpty || st.Findings[0].Object != "tag:x" ||
			st.Findings[0].Step != findings.StepRead {
			t.Errorf("stage %s's findings %+v; want scope.empty naming tag:x alone, at read", st.Ref, st.Findings)
		}
	}
	head := stages[3]
	if len(head.Findings) != 1 || head.Findings[0].Rule != findings.RuleScopeEmpty || head.Findings[0].Object != "tag:x" ||
		head.Findings[0].Step != findings.StepResolve || head.Findings[0].Message != "scope tag:x selects no device on branch change-1" {
		t.Errorf("the head's findings %+v; want scope.empty naming tag:x alone, at resolve", head.Findings)
	}
	reads, stamped := map[string][]any{}, []any{}
	for _, r := range f.requests() {
		switch r.Operation {
		case "Devices":
			reads[r.Path+"?"+r.Query] = append(reads[r.Path+"?"+r.Query], r.Variables["tag"])
		case "IntentStamps":
			stamped = append(stamped, r.Variables["tag"])
		}
	}
	// One read per stage but the head, each at its own at, and each sent twice: once for
	// the text and once for --json.
	if len(reads) != len(stages)-1 {
		t.Errorf("devices were read at %d places, want one per stage's read but the head's (%d): %v", len(reads), len(stages)-1, reads)
	}
	for where, tags := range reads {
		if slices.ContainsFunc(tags, func(tag any) bool { return tag != "x" }) {
			t.Errorf("the devices read at %s sent the tags %v; want x on every one", where, tags)
		}
	}
	if len(stamped) == 0 || slices.ContainsFunc(stamped, func(tag any) bool { return tag != "x" }) {
		t.Errorf("the stamps were read under the tags %v; want x on every one", stamped)
	}
}

// tagsSent are the tags each stamps read and each Devices read sent, by operation: the two
// operations that select devices by the scope's tag (017).
func tagsSent(f *fakeInfrahub) (stamped, read []any) {
	for _, r := range f.requests() {
		switch r.Operation {
		case "IntentStamps":
			stamped = append(stamped, r.Variables["tag"])
		case "Devices":
			read = append(read, r.Variables["tag"])
		}
	}
	return stamped, read
}

// US5 scenario 5 for the three commands it names beside stage plan (017; FR-017): intent
// read --stage, twin create --stage and twin rehearse, each given --scope tag:other over a
// fake whose devices carry other alone, send every stamps read and every stage's Devices
// read with the tag other, never the default's fylgja, and succeed on what they read. A
// create reads no intent before its run, which reads under the scope the run is given; a
// rehearsal's baseline is provisioned under it. stage list, which reads stamps alone, sends
// every one with the tag other too, and its document's subject names the scope.
func TestStageCommandsReadUnderTheScopeGiven(t *testing.T) {
	const scope = "tag:other"
	for _, c := range []struct {
		name  string
		setup func(t *testing.T) (*fakeInfrahub, *fakeService)
		args  func(t *testing.T) []string
		// reads is whether the command reads a stage's devices itself, on the server.
		reads bool
		check func(t *testing.T, svc *fakeService)
	}{
		{"intent read --stage", func(t *testing.T) (*fakeInfrahub, *fakeService) {
			useService(t, nil)
			return demoInfrahub(t), nil
		}, func(t *testing.T) []string {
			return []string{"intent", "read", "--stage", "fylgja-fixture/sealed", "--out", filepath.Join(t.TempDir(), "snapshot.json")}
		}, true, nil},
		{"twin create --stage", func(t *testing.T) (*fakeInfrahub, *fakeService) {
			useInterrupts(t)
			svc := &fakeService{runID: "run-1", result: readyResult()}
			useService(t, svc)
			return demoInfrahub(t), svc
		}, func(*testing.T) []string {
			return []string{"twin", "create", "--stage", "fylgja-fixture/sealed"}
		}, false, func(t *testing.T, svc *fakeService) {
			if len(svc.started) != 1 || svc.started[0].Scope != scope {
				t.Errorf("started %+v; want one run under %s", svc.started, scope)
			}
		}},
		{"twin rehearse", func(t *testing.T) (*fakeInfrahub, *fakeService) {
			rehearseHost(t)
			useInterrupts(t)
			svc := okRun()
			useService(t, svc)
			f := planInfrahub(t, rehearseMarks()...)
			versioned(t, f)
			emptyMain(f)
			return f, svc
		}, func(*testing.T) []string {
			return []string{"twin", "rehearse", "--branch", lessLink}
		}, true, func(t *testing.T, svc *fakeService) {
			if len(svc.rehearsed) != 1 {
				t.Fatalf("%d rehearsals started, want one", len(svc.rehearsed))
			}
			for _, st := range svc.rehearsed[0].Stages {
				if p := st.Provision; p != nil && p.Scope != scope {
					t.Errorf("the baseline %s is provisioned under %q, want %s", st.Ref, p.Scope, scope)
				}
			}
		}},
		{"stage list", func(t *testing.T) (*fakeInfrahub, *fakeService) {
			useService(t, nil)
			return planInfrahub(t, twoMarks()...), nil
		}, func(*testing.T) []string {
			return []string{"stage", "list"}
		}, false, nil},
	} {
		t.Run(c.name, func(t *testing.T) {
			useStateRoot(t)
			f, svc := c.setup(t)
			f.tag = "other"
			f.start()

			code, doc := executeStage(t, append(c.args(t), "--scope", scope)...)
			if code != findings.ExitOK {
				t.Fatalf("exit %d, findings %+v; want 0", code, doc.Findings)
			}
			if doc.Subject == nil || doc.Subject.Scope != scope {
				t.Errorf("subject %+v; want the scope %s", doc.Subject, scope)
			}
			stamped, read := tagsSent(f)
			if len(stamped) == 0 || slices.ContainsFunc(stamped, func(tag any) bool { return tag != "other" }) {
				t.Errorf("the stamps were read under the tags %v; want other on every one", stamped)
			}
			if c.reads && len(read) == 0 || slices.ContainsFunc(read, func(tag any) bool { return tag != "other" }) {
				t.Errorf("the devices were read under the tags %v; want other on every one", read)
			}
			if c.check != nil {
				c.check(t, svc)
			}
		})
	}
}

// --json prints the document alone, the plan block and every stage's findings in order,
// valid against findings.schema.json with stages.schema.json; nothing goes to stderr.
func TestStagePlanJSON(t *testing.T) {
	useStateRoot(t)
	useService(t, nil)
	f := planInfrahub(t, twoMarks()...)
	versioned(t, f)
	emptyMain(f)
	f.start()

	code, stdout, stderr := runStage(t, "plan", "--branch", lessLink, "--json")
	if stderr != "" {
		t.Errorf("--json wrote on stderr: %s", stderr)
	}
	dec := json.NewDecoder(strings.NewReader(stdout))
	var doc findings.Document
	if err := dec.Decode(&doc); err != nil {
		t.Fatalf("stdout is not a findings document: %v\n%s", err, stdout)
	}
	if dec.More() || !strings.HasPrefix(stdout, "{") || !strings.HasSuffix(stdout, "}\n") {
		t.Errorf("stdout holds more than the document:\n%s", stdout)
	}
	validateM10Document(t, &doc)
	if code != findings.ExitRejected || doc.Operation != findings.OpStagePlan || doc.Status != findings.StatusRejected ||
		doc.Plan.Branch != lessLink || doc.Plan.ProposedChange != (findings.StageChange{ID: "pc-1", Name: "change pc-1", Branch: lessLink, Draft: true}) {
		t.Errorf("exit %d, operation %s, status %s, plan %s %+v", code, doc.Operation, doc.Status, doc.Plan.Branch, doc.Plan.ProposedChange)
	}
	var every findings.List
	for _, st := range doc.Plan.Stages {
		every = append(every, st.Findings...)
	}
	if !reflect.DeepEqual(rulesOf(doc.Findings), rulesOf(every)) {
		t.Errorf("the document's findings %v; want every stage's in order, %v", rulesOf(doc.Findings), rulesOf(every))
	}
	if cabled := doc.Plan.Stages[1]; cabled.Read == nil || cabled.Read.Links != 2 || cabled.Label != "cabled" ||
		cabled.Description != "the leaf cabled" {
		t.Errorf("cabled %+v; want its label, description and a read of 2 links", cabled)
	}
	mustQuoteNoContent(t, f, stdout)
}

// Before any connection, stage plan with no --branch is M1's usage failure and a --branch
// that is not a branch is stage.ref.invalid at step start, each exit 2 with Infrahub never
// asked and nothing filed in the store.
func TestStagePlanRefusedBeforeAnyConnection(t *testing.T) {
	const notABranch = `--branch "%s" is not a branch: expected a branch with no "/" and no whitespace`
	for _, c := range []struct {
		name    string
		args    []string
		rule    string
		message string
	}{
		{"no --branch", []string{"stage", "plan"}, findings.RuleOperationFailed, "--branch is required"},
		{"a reference for a branch", []string{"stage", "plan", "--branch", "a/b"}, findings.RuleStageRefInvalid,
			strings.Replace(notABranch, "%s", "a/b", 1)},
		{"a spaced branch", []string{"stage", "plan", "--branch", "a b"}, findings.RuleStageRefInvalid,
			strings.Replace(notABranch, "%s", "a b", 1)},
		{"--branch=", []string{"stage", "plan", "--branch="}, findings.RuleStageRefInvalid, strings.Replace(notABranch, "%s", "", 1)},
	} {
		t.Run(c.name, func(t *testing.T) {
			paths := useStateRoot(t)
			useService(t, nil)
			f := planInfrahub(t)
			f.start()

			code, doc := executeStage(t, c.args...)
			if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0].Rule != c.rule ||
				doc.Findings[0].Message != c.message {
				t.Errorf("exit %d, findings %+v; want 2 with %s saying %q", code, doc.Findings, c.rule, c.message)
			}
			if c.rule == findings.RuleStageRefInvalid && doc.Findings[0].Step != findings.StepStart {
				t.Errorf("step %q, want start", doc.Findings[0].Step)
			}
			if got := f.requests(); len(got) != 0 {
				t.Errorf("Infrahub was asked %+v before the flags were refused", got)
			}
			if got := storedBundles(t, paths.Bundles); len(got) != 0 {
				t.Errorf("the store holds %v", got)
			}
			validateM10Document(t, doc)
		})
	}
}

// Scenario 7: a default branch whose schema lacks the stage kind, its description, its
// relationship to its proposed change or the proposed change's extension refuses stage
// plan, stage list, twin create --stage and intent read --stage as stage.kind.absent, exit
// 1, naming the schema file to load, with nothing listed, read, written or started; and
// schema check says, in its last line and verified.stages, how the default branch stands.
// The kind whole, schema check says so.
func TestStageKindAbsentEverywhere(t *testing.T) {
	const remedy = " (load schema/fylgja-stage.yaml; needed only by --stage, stage list and stage plan)"
	for _, c := range []struct {
		name               string
		edit               func(*fakeInfrahub)
		says, line         string
		present, extension bool
		missing            []string
	}{
		{"no kind", func(f *fakeInfrahub) { f.kind = nil },
			"the default branch's schema has no kind FylgjaStage: load schema/fylgja-stage.yaml on it",
			"stages: FylgjaStage absent from the default branch" + remedy, false, false, []string{}},
		{"description missing", func(f *fakeInfrahub) { f.kind = []string{"label", "as_of"} },
			"kind FylgjaStage on the default branch lacks the attribute description, which this build reads: load schema/fylgja-stage.yaml on it",
			"stages: FylgjaStage on the default branch lacks description" + remedy, false, true, []string{"description"}},
		{"the relationship missing", func(f *fakeInfrahub) { f.noRelationship = true },
			"load schema/fylgja-stage.yaml on it",
			"stages: FylgjaStage on the default branch lacks proposed_change" + remedy, false, true, []string{"proposed_change"}},
		{"the extension missing", func(f *fakeInfrahub) { f.noExtension = true },
			"kind CoreProposedChange on the default branch lacks fylgja_stages, the extension schema/fylgja-stage.yaml adds: load schema/fylgja-stage.yaml on it",
			"stages: FylgjaStage present on the default branch, but CoreProposedChange lacks fylgja_stages" + remedy, true, false, []string{}},
		{"the kind whole", nil, "",
			"stages: FylgjaStage present on the default branch, with its extension", true, true, []string{}},
	} {
		t.Run(c.name, func(t *testing.T) {
			paths := useStateRoot(t)
			useService(t, nil)
			f := stagesInfrahub(t)
			if c.edit != nil {
				c.edit(f)
			}
			f.start()

			if c.edit != nil {
				out := filepath.Join(t.TempDir(), "snapshot.json")
				for _, args := range [][]string{
					{"stage", "plan", "--branch", lessLink},
					{"stage", "list"},
					{"stage", "list", "--branch", lessLink},
					{"twin", "create", "--stage", lessLink + "/cabled"},
					{"intent", "read", "--stage", lessLink + "/cabled", "--out", out},
				} {
					code, doc := executeStage(t, args...)
					if code != findings.ExitRejected || len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleStageKindAbsent ||
						doc.Findings[0].Object != intent.StageKind || !strings.Contains(doc.Findings[0].Message, c.says) {
						t.Errorf("%v: exit %d, findings %+v; want 1 with %s saying %q", args, code, doc.Findings,
							findings.RuleStageKindAbsent, c.says)
					}
					if doc.Stages != nil || doc.Plan != nil || doc.Stage != nil {
						t.Errorf("%v: a refused command carries stages %+v, plan %+v, stage %+v", args, doc.Stages, doc.Plan, doc.Stage)
					}
					validateM10Document(t, doc)
				}
				if _, err := os.Stat(out); !os.IsNotExist(err) {
					t.Errorf("intent read wrote %s: %v", out, err)
				}
				if got := storedBundles(t, paths.Bundles); len(got) != 0 {
					t.Errorf("the store holds %v", got)
				}
				for _, r := range f.requests() {
					if r.Path != "/api/schema" || r.Query != "" {
						t.Errorf("a refused command asked %+v beyond the default branch's schema", r)
					}
				}
			}

			code, stdout, stderr := runRoot(t, "schema", "check", "--branch", "fylgja-fixture")
			lines := strings.Split(strings.TrimSuffix(stdout, "\n"), "\n")
			if code != findings.ExitOK || len(lines) != 2 || lines[1] != c.line {
				t.Errorf("schema check: exit %d, stdout\n%s%s\nwant 0 and the last line\n%s", code, stdout, stderr, c.line)
			}
			code, doc := executeStage(t, "schema", "check", "--branch", "fylgja-fixture")
			got, _ := json.Marshal(doc.Verified.Stages)
			want, _ := json.Marshal(map[string]any{"kind": intent.StageKind, "present": c.present, "missing": c.missing,
				"extension": c.extension, "file": intent.StageSchemaFile})
			var g, w any
			_ = json.Unmarshal(got, &g)
			_ = json.Unmarshal(want, &w)
			if code != findings.ExitOK || len(doc.Findings) != 0 || !reflect.DeepEqual(g, w) {
				t.Errorf("schema check --json: exit %d, findings %+v, verified.stages %s; want 0, none and %s", code, doc.Findings, got, want)
			}
			validateM10Document(t, doc)
		})
	}
}
