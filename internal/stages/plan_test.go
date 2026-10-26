package stages

import (
	"context"
	"errors"
	"fmt"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/stage"
	"github.com/happypathnetworking/fylgja/internal/step"
)

// fakePipeline is Infrahub's branches under the stage read, and a store, with the real pure
// compile between them: each reference reads as the fixture CTM at the at asked for,
// except those a case names, and every read and filing is recorded.
type fakePipeline struct {
	t      *testing.T
	reads  []string // branch@at, in order
	scopes []string // the scope of each read, in order
	filed  []string // bundle ids, in order
	// Per branch: a read that could not run, a read refused, a read's warnings, a CTM of a
	// platform no package covers. Per branch@at: a CTM with the last link removed.
	readErr      map[string]error
	readRefused  map[string]findings.List
	readWarnings map[string]findings.List
	unsupported  map[string]bool
	lessLink     map[string]bool
	fileErr      error
	fileRefusals findings.List
}

func (f *fakePipeline) pipeline() Pipeline {
	return Pipeline{
		Read: func(_ context.Context, branch, at, scope string, _ *psp.Registry, observedAt string) (*ctm.CTM, findings.List, error) {
			f.reads = append(f.reads, branch+"@"+at)
			f.scopes = append(f.scopes, scope)
			if err := f.readErr[branch]; err != nil {
				return nil, nil, err
			}
			if list := f.readRefused[branch]; list != nil {
				return nil, list, nil
			}
			c, err := ctm.Load(filepath.Join("..", "..", "testdata", "ctm", "three-node.json"))
			if err != nil {
				f.t.Fatal(err)
			}
			c.Envelope.Branch, c.Envelope.At, c.Envelope.ObservedAt = branch, at, observedAt
			if f.lessLink[branch+"@"+at] {
				c.Links = c.Links[:len(c.Links)-1]
			}
			if f.unsupported[branch] {
				c.Devices[0].Platform.Package = "nosuch"
			}
			return c, f.readWarnings[branch], nil
		},
		Compile: stage.Compile,
		File: func(_ context.Context, _ map[string][]byte, id string, _ *ctm.CTM) (findings.List, error) {
			if f.fileErr != nil || f.fileRefusals != nil {
				return f.fileRefusals, f.fileErr
			}
			f.filed = append(f.filed, id)
			return nil, nil
		},
	}
}

// emptyMain is the development host's main: the schema and no FylgjaContract object, so
// every branch point is refused before a device is counted (research §6.1, R-04).
var emptyMain = map[string]findings.List{"main": {{Severity: findings.Rejection, Rule: findings.RuleScopeEmpty,
	Object: "tag:fylgja", Message: "scope tag:fylgja selects no device on branch main"}}}

// planned runs Plan and records the order of its callbacks.
func planned(t *testing.T, r Reader, s Stamper, branch string, f *fakePipeline) (*PlanResult, []string) {
	t.Helper()
	var order []string
	res, err := Plan(context.Background(), r, s, branch, testScope, registry(t), f.pipeline(), now,
		func(pc ProposedChange, n int) { order = append(order, fmt.Sprintf("%s (%d stages)", pc.ID, n)) },
		func(st PlanStage) { order = append(order, st.Ref.String()) },
		func(p step.Pair) { order = append(order, p.From+" → "+p.To) })
	if err != nil {
		t.Fatal(err)
	}
	return res, order
}

// labelsOf is a plan's stages' labels with their statuses.
func labelsOf(res *PlanResult) []string {
	var out []string
	for _, st := range res.Stages {
		out = append(out, st.Label+" "+st.Status)
	}
	return out
}

// Two marks give four stages in order and three steps: the branch point on the empty
// main refused scope.empty and its step not computed; cabled, live and head
// compiled, each read at its own reference verbatim, filed and diffed; the step from
// cabled adding the link, and the step from live to the head unchanged, the two ids
// differing by provenance alone. Each step comes between the stages it joins.
func TestPlanStages(t *testing.T) {
	r, s := story()
	f := &fakePipeline{t: t, readRefused: emptyMain, lessLink: map[string]bool{"change-1@" + cabledAt: true}}
	res, order := planned(t, r, s, "change-1", f)

	want := []string{"pc-1 (4 stages)", "change-1/branch-point", "change-1/branch-point → change-1/cabled", "change-1/cabled",
		"change-1/cabled → change-1/live", "change-1/live", "change-1/live → change-1/head", "change-1/head"}
	if !reflect.DeepEqual(order, want) {
		t.Errorf("callbacks %v\nwant %v", order, want)
	}
	if want := []string{"main@" + branchedFrom, "change-1@" + cabledAt, "change-1@" + liveAt, "change-1@" + headAt}; !reflect.DeepEqual(f.reads, want) {
		t.Errorf("reads %v, want each stage's own reference, verbatim: %v", f.reads, want)
	}
	if res.ProposedChange == nil || *res.ProposedChange != pc1 || res.Branch != "change-1" {
		t.Errorf("the plan's proposed change %+v on %s", res.ProposedChange, res.Branch)
	}
	if got, want := labelsOf(res), []string{"branch-point refused", "cabled compiled", "live compiled", "head compiled"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("stages %v, want %v", got, want)
	}
	bp := res.Stages[0]
	if bp.Rule != findings.RuleScopeEmpty || bp.Resolved == nil || bp.Resolved.Branch != "main" ||
		bp.AtSource != AtBranchPoint || bp.Bundle != nil || len(bp.Findings) != 1 || bp.Findings[0].Step != findings.StepRead {
		t.Errorf("branch-point: %+v", bp)
	}
	var ids []string
	for _, st := range res.Stages[1:] {
		if st.Bundle == nil || st.Read == nil || st.Resolved == nil || st.ObservedAt == "" {
			t.Fatalf("%s: %+v", st.Ref, st)
		}
		ids = append(ids, st.Bundle.ID)
	}
	if !reflect.DeepEqual(f.filed, ids) {
		t.Errorf("filed %v, want one bundle per stage compiled: %v", f.filed, ids)
	}
	if ids[0] == ids[1] || ids[1] == ids[2] {
		t.Errorf("ids %v: two ats of one intent must differ by provenance", ids)
	}
	if got, want := res.Steps[0].Text(), "step change-1/branch-point → change-1/cabled (— → "+ids[0][:8]+"…): not computed (change-1/branch-point was refused)"; got != want {
		t.Errorf("step 1: %s\nwant %s", got, want)
	}
	if s := res.Steps[1]; s.Step == nil || s.Step.Unchanged || len(s.Step.LinksAdded) != 1 || len(s.Step.LinksRemoved) != 0 {
		t.Errorf("cabled → live: %+v; want the one link added", s.Step)
	}
	if s := res.Steps[2]; s.Step == nil || !s.Step.Unchanged || s.FromID != ids[1] || s.ToID != ids[2] {
		t.Errorf("live → head: %+v; want unchanged between the two ids", s)
	}
	if st := res.Stages[2]; st.Description != "after its configuration is live" || st.AtSource != AtGiven ||
		st.Read.Counts != (intent.Counts{Devices: 3, Interfaces: 9, Links: 3, Artifacts: 3}) || st.BundleID() != ids[1] {
		t.Errorf("live: %+v, read %+v", st, st.Read)
	}
	mustHoldTheStagesFindings(t, res)
}

// Nothing marked gives the two derived stages and one step: on a main that carries the
// contract and the devices both compile, and on the empty main the branch point is refused
// and its step not computed, the head still planned (R-04).
func TestPlanNothingMarked(t *testing.T) {
	r, s := story(change1([]intent.Stage{}...), change2())
	res, order := planned(t, r, s, "change-2", &fakePipeline{t: t})
	if want := []string{"pc-2 (2 stages)", "change-2/branch-point", "change-2/branch-point → change-2/head", "change-2/head"}; !reflect.DeepEqual(order, want) {
		t.Errorf("callbacks %v, want %v", order, want)
	}
	if got := labelsOf(res); !reflect.DeepEqual(got, []string{"branch-point compiled", "head compiled"}) || len(res.Steps) != 1 ||
		res.Steps[0].Step == nil {
		t.Errorf("stages %v, steps %+v", got, res.Steps)
	}

	r, s = story(change2())
	res, _ = planned(t, r, s, "change-2", &fakePipeline{t: t, readRefused: emptyMain})
	if got := labelsOf(res); !reflect.DeepEqual(got, []string{"branch-point refused", "head compiled"}) ||
		res.Steps[0].Step != nil || !strings.HasSuffix(res.Steps[0].Text(), "not computed (change-2/branch-point was refused)") {
		t.Errorf("stages %v, step %s", got, res.Steps[0].Text())
	}
	if st := findings.NewDocument(findings.OpTwinCreate, nil, res.Findings).Status; st.ExitCode() != findings.ExitRejected {
		t.Errorf("status %s; want a rejection, exit 1", st)
	}
	mustHoldTheStagesFindings(t, res)
}

// A stage refused at resolution is reported, both steps touching it are not computed,
// and the plan goes on; a refused stage is never read.
func TestPlanRefusedInTheMiddle(t *testing.T) {
	for name, edit := range map[string]func(r *fakeReader, s *fakeStamper){
		"nine digits": func(r *fakeReader, _ *fakeStamper) { r.pcs[0].Stages[0].At = str("2026-10-16T17:30:00.123456789Z") },
		"stale": func(_ *fakeReader, s *fakeStamper) {
			stale := freshStamps(headLatest)
			stale.Devices["n2"] = device("2026-10-16T17:29:00.000000+00:00", "2026-10-16T17:22:00.000000+00:00")
			s.at = map[string]intent.Stamps{"change-1@" + liveAt: stale}
		},
	} {
		t.Run(name, func(t *testing.T) {
			r, s := story()
			edit(r, s)
			f := &fakePipeline{t: t}
			res, _ := planned(t, r, s, "change-1", f)
			if got := labelsOf(res); !reflect.DeepEqual(got, []string{"branch-point compiled", "cabled compiled", "live refused", "head compiled"}) {
				t.Fatalf("stages %v", got)
			}
			if len(f.reads) != 3 {
				t.Errorf("reads %v: a stage refused at resolution is never read", f.reads)
			}
			live := res.Stages[2]
			if live.Resolved != nil || live.Bundle != nil || len(live.Findings) != 1 || live.Findings[0].Step != findings.StepResolve ||
				live.Description != "after its configuration is live" || live.AtSource != AtGiven {
				t.Errorf("live: %+v", live)
			}
			for i, want := range []string{
				"step change-1/cabled → change-1/live (" + res.Stages[1].BundleID()[:8] + "… → —): not computed (change-1/live was refused)",
				"step change-1/live → change-1/head (— → " + res.Stages[3].BundleID()[:8] + "…): not computed (change-1/live was refused)",
			} {
				if got := res.Steps[i+1].Text(); got != want {
					t.Errorf("step %d: %s\nwant %s", i+1, got, want)
				}
			}
			if !res.Findings.Rejected() || !reflect.DeepEqual(res.Findings, live.Findings) {
				t.Errorf("document findings %v; want live's refusal alone", res.Findings)
			}
		})
	}
}

// A mark written after the head's at is planned before it, and the step to the head is
// unchanged: the two read one intent at two instants.
func TestPlanMarkAfterTheHead(t *testing.T) {
	late := "2026-10-16T17:45:00.000000+00:00"
	r, s := story(change1(mark("st-late", "late", late, nil, "")))
	res, _ := planned(t, r, s, "change-1", &fakePipeline{t: t})
	if got := labelsOf(res); !reflect.DeepEqual(got, []string{"branch-point compiled", "late compiled", "head compiled"}) {
		t.Fatalf("stages %v", got)
	}
	if s := res.Steps[1]; s.From != "change-1/late" || s.To != "change-1/head" || s.Step == nil || !s.Step.Unchanged {
		t.Errorf("late → head: %+v", s)
	}
}

// main written since the branch point warns once, with the branch point, and refuses
// nothing.
func TestPlanMainMoved(t *testing.T) {
	r, s := story()
	s.byBranch["main"] = intent.Stamps{Latest: "2026-10-16T17:50:00.000000+00:00"}
	res, _ := planned(t, r, s, "change-1", &fakePipeline{t: t})
	if res.Findings.Rejected() || len(res.Findings) != 1 || res.Findings[0].Rule != findings.RuleStageMainMoved ||
		len(res.Stages[0].Findings) != 1 {
		t.Errorf("findings %+v; want main.moved once, with the branch point", res.Findings)
	}
}

// A branch point refused at resolution keeps the warning: stale on a main that holds the
// network, written since the branch point, it carries its stage.artifact.stale and the one
// main.moved, which no other stage repeats.
func TestPlanMainMovedBesideARefusedBranchPoint(t *testing.T) {
	r, s := story()
	s.byBranch["main"] = intent.Stamps{Latest: "2026-10-16T17:50:00.000000+00:00"}
	s.at = map[string]intent.Stamps{"main@" + branchedFrom: {Latest: "2026-10-16T17:19:00.000000+00:00",
		Devices: map[string]intent.DeviceStamps{
			"n1": device("2026-10-16T17:19:00.000000+00:00", "2026-10-16T17:18:00.000000+00:00"),
			"n2": device("2026-10-16T17:17:00.000000+00:00", "2026-10-16T17:18:00.000000+00:00"),
		}}}
	res, _ := planned(t, r, s, "change-1", &fakePipeline{t: t})
	bp := res.Stages[0]
	var rules []string
	for _, f := range bp.Findings {
		rules = append(rules, string(f.Severity)+" "+f.Rule+" "+f.Object)
	}
	if want := []string{"rejection stage.artifact.stale n1", "warning stage.main.moved change-1"}; bp.Status != PlanRefused ||
		bp.Rule != findings.RuleStageArtifactStale || !reflect.DeepEqual(rules, want) {
		t.Errorf("the branch point: %s (%s), findings %v; want refused stale with %v", bp.Status, bp.Rule, rules, want)
	}
	if want := "device n1: its intent on main was written at 2026-10-16T17:19:00.000000+00:00, later than its artifact " +
		"device-config was generated (checksum stamped 2026-10-16T17:18:00.000000+00:00; no artifact validator of the " +
		"proposed change had completed): stage change-1/branch-point reads main as it was at the branch point, before " +
		"its artifacts were regenerated"; len(bp.Findings) == 0 || bp.Findings[0].Message != want {
		t.Errorf("the branch point's findings %+v; want the first saying\n  %s", bp.Findings, want)
	}
	moved := 0
	for _, f := range res.Findings {
		if f.Rule == findings.RuleStageMainMoved {
			moved++
		}
	}
	if moved != 1 {
		t.Errorf("main.moved filed %d times in %+v; want once, with the branch point", moved, res.Findings)
	}
}

// A label two marks share is planned once and refused stage.duplicate; a mark labelled
// head makes the head refused stage.label.reserved, at the head's place. Neither refused
// stage is read.
func TestPlanDuplicateAndReserved(t *testing.T) {
	r, s := story(change1(append(change1().Stages,
		mark("st-cabled-0", "cabled", "2026-10-16T17:26:00.000000+00:00", nil, "second"),
		mark("st-head", "head", "2026-10-16T17:27:00.000000+00:00", nil, ""))...))
	f := &fakePipeline{t: t}
	res, _ := planned(t, r, s, "change-1", f)
	if got := labelsOf(res); !reflect.DeepEqual(got, []string{"branch-point compiled", "cabled refused", "live compiled", "head refused"}) {
		t.Fatalf("stages %v", got)
	}
	if want := []string{"main@" + branchedFrom, "change-1@" + liveAt}; !reflect.DeepEqual(f.reads, want) {
		t.Errorf("reads %v; want %v: a stage refused at resolution is never read", f.reads, want)
	}
	if st := res.Stages[1]; st.Rule != findings.RuleStageDuplicate || st.Description != "after the link is cabled" ||
		!strings.Contains(st.Findings[0].Message, "ids st-cabled, st-cabled-0") {
		t.Errorf("cabled: %+v", st)
	}
	if st := res.Stages[3]; st.Rule != findings.RuleStageLabelReserved || st.AtSource != AtHead {
		t.Errorf("head: %+v", st)
	}
}

// A mark with no at, no as_of written and no stamp returned for its label, is refused
// stage.at.unresolved and never read; it goes after the marks that have one, both steps
// touching it are not computed, and the other stages are planned.
func TestPlanMarkWithNoAt(t *testing.T) {
	r, s := story(change1(
		mark("st-live", "live", "2026-10-16T17:31:00.000000+00:00", str(liveAt), "after its configuration is live"),
		mark("st-cabled", "cabled", "", nil, "after the link is cabled")))
	f := &fakePipeline{t: t}
	res, _ := planned(t, r, s, "change-1", f)
	if got := labelsOf(res); !reflect.DeepEqual(got, []string{"branch-point compiled", "live compiled", "cabled refused", "head compiled"}) {
		t.Fatalf("stages %v", got)
	}
	if want := []string{"main@" + branchedFrom, "change-1@" + liveAt, "change-1@" + headAt}; !reflect.DeepEqual(f.reads, want) {
		t.Errorf("reads %v; want %v: a stage with no at is never read", f.reads, want)
	}
	cabled := res.Stages[2]
	if cabled.Rule != findings.RuleStageAtUnresolved || cabled.Resolved != nil || cabled.Bundle != nil || len(cabled.Findings) != 1 ||
		cabled.Findings[0].Object != "change-1/cabled" || cabled.Findings[0].Step != findings.StepResolve {
		t.Errorf("cabled: %+v", cabled)
	}
	for i, want := range []string{
		"step change-1/live → change-1/cabled (" + res.Stages[1].BundleID()[:8] + "… → —): not computed (change-1/cabled was refused)",
		"step change-1/cabled → change-1/head (— → " + res.Stages[3].BundleID()[:8] + "…): not computed (change-1/cabled was refused)",
	} {
		if got := res.Steps[i+1].Text(); got != want {
			t.Errorf("step %d: %s\nwant %s", i+1, got, want)
		}
	}
	if got := res.Steps[0].Text(); strings.Contains(got, "not computed") {
		t.Errorf("step 0: %s; want the branch point to live computed", got)
	}
	if !reflect.DeepEqual(res.Findings, cabled.Findings) {
		t.Errorf("document findings %v; want cabled's refusal alone", res.Findings)
	}
}

// A read refused, a read that cannot run, a compile refused, a filing refused and a filing
// that cannot run: each named at its step on the one stage it touched.
func TestPlanPerStageOutcomes(t *testing.T) {
	notReady := findings.List{{Severity: findings.Rejection, Rule: findings.RuleArtifactNotReady, Object: "n1",
		Message: "artifact device-config of n1 on branch change-2 is Pending, not Ready"}}
	mismatch := findings.List{{Severity: findings.Rejection, Rule: findings.RuleBundleIDMismatch, Object: "/store/x",
		Message: "the store's entry hashes otherwise", Step: findings.StepCompile}}
	gone := errors.Join(intent.ErrBranchNotFound, errors.New("Branch: change-2 not found."))

	for _, c := range []struct {
		name   string
		f      *fakePipeline
		status string
		rule   string
		step   string
		object string
		read   bool
	}{
		{"read refused", &fakePipeline{readRefused: map[string]findings.List{"change-2": notReady}},
			PlanRefused, findings.RuleArtifactNotReady, findings.StepRead, "n1", false},
		{"branch gone", &fakePipeline{readErr: map[string]error{"change-2": gone}},
			PlanFailed, findings.RuleOperationFailed, findings.StepRead, "change-2/head", false},
		{"compile refused", &fakePipeline{unsupported: map[string]bool{"change-2": true}},
			PlanRefused, findings.RulePlatformUnsupported, findings.StepCompile, "n1", true},
		{"filing refused", &fakePipeline{fileRefusals: mismatch},
			PlanRefused, findings.RuleBundleIDMismatch, findings.StepCompile, "/store/x", true},
		{"filing could not run", &fakePipeline{fileErr: errors.New("disk full")},
			PlanFailed, findings.RuleOperationFailed, findings.StepCompile, "change-2/head", true},
	} {
		t.Run(c.name, func(t *testing.T) {
			c.f.t = t
			c.f.readRefused = merge(c.f.readRefused, emptyMain)
			r, s := story(change2())
			res, _ := planned(t, r, s, "change-2", c.f)
			st := res.Stages[1]
			if st.Status != c.status || st.Rule != c.rule || st.Bundle != nil || (st.Read != nil) != c.read {
				t.Errorf("status %s, rule %s, read %v, bundle %v", st.Status, st.Rule, st.Read != nil, st.Bundle)
			}
			var f *findings.Finding
			for i := range st.Findings {
				if st.Findings[i].Rule == c.rule {
					f = &st.Findings[i]
				}
			}
			if f == nil || f.Step != c.step || f.Object != c.object {
				t.Errorf("finding %+v; want %s at step %s on %s", f, c.rule, c.step, c.object)
			}
			if !res.Findings.Rejected() || len(c.f.filed) != 0 || res.Steps[0].Step != nil {
				t.Errorf("findings %v, filed %v, steps %v", res.Findings, c.f.filed, res.Steps)
			}
		})
	}
}

func merge(a, b map[string]findings.List) map[string]findings.List {
	out := map[string]findings.List{}
	for k, v := range b {
		out[k] = v
	}
	for k, v := range a {
		out[k] = v
	}
	return out
}

// Refusals of the whole plan end it before anything is read: the kind absent, a branch
// no open proposed change has, naming those that have one, and the branch gone under its
// proposed change. A reader that cannot list is an error.
func TestPlanRefusedWhole(t *testing.T) {
	for _, c := range []struct {
		name    string
		edit    func(r *fakeReader)
		branch  string
		rule    string
		message string
	}{
		{"kind absent", func(r *fakeReader) { r.checkErr = &intent.StageKindError{} }, "change-1", findings.RuleStageKindAbsent, ""},
		{"no open proposed change", nil, "nosuch", findings.RuleStageUnknown,
			"no open proposed change has source branch nosuch; the branches with one are: change-1, change-2"},
		{"the branch gone", func(r *fakeReader) { delete(r.branches, "change-1") }, "change-1", findings.RuleStageUnknown, ""},
	} {
		t.Run(c.name, func(t *testing.T) {
			r, s := story()
			if c.edit != nil {
				c.edit(r)
			}
			f := &fakePipeline{t: t}
			res, order := planned(t, r, s, c.branch, f)
			if len(res.Findings) != 1 || res.Findings[0].Rule != c.rule || res.Findings[0].Step != findings.StepResolve ||
				(c.message != "" && res.Findings[0].Message != c.message) {
				t.Errorf("findings %+v", res.Findings)
			}
			if len(f.reads) != 0 || len(order) != 0 || len(res.Stages) != 0 || res.ProposedChange != nil {
				t.Errorf("read %v, reported %v: nothing is planned", f.reads, order)
			}
		})
	}
	unreachable := errors.New("Infrahub is unreachable")
	r, s := story()
	r.pcErr = unreachable
	if _, err := Plan(context.Background(), r, s, "change-1", testScope, registry(t), (&fakePipeline{t: t}).pipeline(), now,
		nil, nil, nil); !errors.Is(err, unreachable) {
		t.Errorf("reader error: %v", err)
	}
	// A stamps read that cannot run while a stage resolves fails that stage alone.
	r, s = story()
	res, _ := planned(t, r, &failingAt{fakeStamper: s, at: cabledAt}, "change-1", &fakePipeline{t: t})
	if st := res.Stages[1]; st.Status != PlanFailed || st.Rule != findings.RuleOperationFailed ||
		st.Findings[0].Step != findings.StepResolve || st.Findings[0].Object != "change-1/cabled" {
		t.Errorf("cabled: %+v", st)
	}
}

// failingAt is a stamper that cannot read one at.
type failingAt struct {
	*fakeStamper
	at string
}

func (f *failingAt) Stamps(ctx context.Context, branch, at, scope string) (intent.Stamps, error) {
	if at == f.at {
		return intent.Stamps{}, errors.New("Infrahub at http://infrahub.invalid is unreachable")
	}
	return f.fakeStamper.Stamps(ctx, branch, at, scope)
}

// Two compiled stages whose step does not read end the plan with an error naming the
// pair, the side and the file: a bundle the compile just produced always reads, so one
// that does not is a defect, never a pair reported as not computed.
func TestPlanStepThatDoesNotReadIsAnError(t *testing.T) {
	f := &fakePipeline{t: t}
	p := f.pipeline()
	compiles := 0
	p.Compile = func(c *ctm.CTM, reg *psp.Registry) (map[string][]byte, string, findings.List) {
		files, id, list := stage.Compile(c, reg)
		if compiles++; compiles == 2 {
			delete(files, "manifest.json")
		}
		return files, id, list
	}
	var steps []string
	r, s := story()
	res, err := Plan(context.Background(), r, s, "change-1", testScope, registry(t), p, now,
		nil, nil, func(p step.Pair) { steps = append(steps, p.From+" → "+p.To) })
	if err == nil {
		t.Fatalf("no error; the plan reported %+v", res.Steps)
	}
	for _, want := range []string{"the step change-1/branch-point → change-1/cabled: ", "the to bundle ", "manifest.json: not in the bundle"} {
		if !strings.Contains(err.Error(), want) {
			t.Errorf("error %q does not name %q", err, want)
		}
	}
	if res != nil || len(steps) != 0 {
		t.Errorf("result %+v, steps reported %v: the pair is no step", res, steps)
	}
}

// Build is the plan's own path for one stage: twin step's target compiles to the bundle
// stage plan printed for it, and carries step 9's warning.
func TestBuildIsThePlans(t *testing.T) {
	r, s := story()
	s.byBranch["main"] = intent.Stamps{Latest: "2026-10-16T17:50:00.000000+00:00"}
	res, _ := planned(t, r, s, "change-1", &fakePipeline{t: t})
	ch, list, err := Find(t.Context(), r, s, "change-1", testScope)
	if err != nil || list != nil {
		t.Fatal(err, list)
	}
	built := Build(t.Context(), r, s, registry(t), ch, Ref{"change-1", "live"}, (&fakePipeline{t: t}).pipeline(), now)
	if built.Status != PlanCompiled || built.BundleID() != res.Stages[2].BundleID() {
		t.Errorf("built %s %s; the plan's live %s", built.Status, built.BundleID(), res.Stages[2].BundleID())
	}
	if len(built.Findings) != 1 || built.Findings[0].Rule != findings.RuleStageMainMoved {
		t.Errorf("built findings %+v; want main.moved", built.Findings)
	}
}

// mustHoldTheStagesFindings holds the plan's document findings to its stages', in order.
func mustHoldTheStagesFindings(t *testing.T, res *PlanResult) {
	t.Helper()
	var all findings.List
	for _, st := range res.Stages {
		all = append(all, st.Findings...)
	}
	if (len(all) != 0 || len(res.Findings) != 0) && !reflect.DeepEqual(all, res.Findings) {
		t.Errorf("the document's findings %v are not the stages' %v", res.Findings, all)
	}
}

// One scope is every read's (017): a plan, a listing, a resolution and twin step's build of
// its target read each head's, each stage's and the destination's stamps, and each stage,
// under the scope they were given and no other.
func TestEveryReadIsUnderTheScopeGiven(t *testing.T) {
	const scope = "tag:lab-b"
	onlyScope := func(t *testing.T, what string, got []string) {
		t.Helper()
		if len(got) == 0 {
			t.Fatalf("%s: nothing was read", what)
		}
		for i, s := range got {
			if s != scope {
				t.Errorf("%s: read %d of %d under %q, want %q", what, i+1, len(got), s, scope)
			}
		}
	}

	r, s := story()
	f := &fakePipeline{t: t}
	if _, err := Plan(t.Context(), r, s, "change-1", scope, registry(t), f.pipeline(), now, nil, nil, nil); err != nil {
		t.Fatal(err)
	}
	onlyScope(t, "the plan's stamps", s.scopes)
	onlyScope(t, "the plan's stage reads", f.scopes)

	r, s = story()
	if _, _, err := List(t.Context(), r, s, "", scope, nil); err != nil {
		t.Fatal(err)
	}
	onlyScope(t, "the listing's stamps", s.scopes)

	r, s = story()
	if _, _, err := Resolve(t.Context(), r, s, registry(t), Ref{"change-1", "cabled"}, scope, now); err != nil {
		t.Fatal(err)
	}
	onlyScope(t, "the resolution's stamps", s.scopes)

	r, s = story()
	ch, list, err := Find(t.Context(), r, s, "change-1", scope)
	if err != nil || list != nil {
		t.Fatal(err, list)
	}
	if ch.Scope != scope {
		t.Errorf("the proposed change found carries scope %q, want %q", ch.Scope, scope)
	}
	f = &fakePipeline{t: t}
	if built := Build(t.Context(), r, s, registry(t), ch, Ref{"change-1", "live"}, f.pipeline(), now); built.Status != PlanCompiled {
		t.Fatalf("built %s: %+v", built.Status, built.Findings)
	}
	onlyScope(t, "the build's stamps", s.scopes)
	onlyScope(t, "the build's read", f.scopes)
}
