package waypoint

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"github.com/santhosh-tekuri/jsonschema/v6"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/stage"
	"github.com/happypathnetworking/fylgja/internal/step"
)

// fakeStages is Infrahub's branches under the stage read, and a store, with the real pure
// compile between them: each branch reads as the fixture CTM at the at asked for, except
// the branches a case names, and every read and filing is recorded.
type fakeStages struct {
	t     *testing.T
	reads []string // branch@at, in order
	filed []string // bundle ids, in order
	// Per branch: a read that could not run, a read refused, a CTM with the last link
	// removed, a CTM of a platform no package covers.
	readErr      map[string]error
	readRefused  map[string]findings.List
	readWarnings map[string]findings.List
	lessLink     map[string]bool
	unsupported  map[string]bool
	fileErr      error
	fileRefusals findings.List
}

func (f *fakeStages) stages() Stages {
	return Stages{
		Read: func(_ context.Context, branch, at string, _ *psp.Registry, observedAt string) (*ctm.CTM, findings.List, error) {
			f.reads = append(f.reads, branch+"@"+at)
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
			if f.lessLink[branch] {
				c.Links = c.Links[:len(c.Links)-1]
			}
			if f.unsupported[branch] {
				c.Devices[0].Platform.NOS = "nosuch"
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

func registry(t *testing.T) *psp.Registry {
	t.Helper()
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	return reg
}

// planned runs Plan and records the order of its callbacks.
func planned(t *testing.T, r Reader, series string, f *fakeStages) (*PlanResult, []string) {
	t.Helper()
	var order []string
	res, err := Plan(context.Background(), r, series, registry(t), f.stages(), now,
		func(n int) { order = append(order, fmt.Sprintf("series of %d", n)) },
		func(w PlanWaypoint) { order = append(order, w.Ref.String()) },
		func(p step.Pair) { order = append(order, p.From+" → "+p.To) })
	if err != nil {
		t.Fatal(err)
	}
	return res, order
}

// contracts/cli.md's series: demo/1 and demo/2 seal one branch at two times, demo/3 another
// branch, whose read has one link fewer.
func demoSeries() []intent.Waypoint {
	return []intent.Waypoint{
		row("id-3", "demo", 3, "change-1", "2026-09-28T15:40:00.000000+00:00", nil, "after the second"),
		row("id-1", "demo", 1, "main", "2026-09-28T15:00:01.123456+00:00", nil, "before the change"),
		row("id-2", "demo", 2, "main", "2026-09-28T15:20:44.000000+00:00", str("2026-09-28T15:20:44Z"), "after the first cut-over"),
		row("id-o", "other", 1, "main", "2026-09-28T15:00:00.000000+00:00", nil, ""),
	}
}

// Three waypoints, each read at its own reference and compiled, filed and diffed; the step
// between two times of one intent is unchanged though the ids differ, and the step to the
// other branch names its removed link. The callbacks put each step between its waypoints.
func TestPlanSeries(t *testing.T) {
	f := &fakeStages{t: t, lessLink: map[string]bool{"change-1": true}}
	res, order := planned(t, &fakeReader{rows: demoSeries()}, "demo", f)

	if want := []string{"series of 3", "demo/1", "demo/1 → demo/2", "demo/2", "demo/2 → demo/3", "demo/3"}; !reflect.DeepEqual(order, want) {
		t.Errorf("callbacks %v, want %v", order, want)
	}
	if want := []string{"main@2026-09-28T15:00:01.123456+00:00", "main@2026-09-28T15:20:44Z",
		"change-1@2026-09-28T15:40:00.000000+00:00"}; !reflect.DeepEqual(f.reads, want) {
		t.Errorf("reads %v, want each waypoint's own reference, verbatim: %v", f.reads, want)
	}
	if len(res.Waypoints) != 3 || len(res.Steps) != 2 || res.Findings.Rejected() {
		t.Fatalf("plan: %d waypoints, %d steps, findings %v", len(res.Waypoints), len(res.Steps), res.Findings)
	}
	var ids []string
	for _, w := range res.Waypoints {
		if w.Status != PlanCompiled || w.Bundle == nil || w.Read == nil || w.Resolved == nil {
			t.Fatalf("%s: %+v", w.Ref, w)
		}
		ids = append(ids, w.Bundle.ID)
	}
	if !reflect.DeepEqual(f.filed, ids) {
		t.Errorf("filed %v, want one bundle per waypoint compiled: %v", f.filed, ids)
	}
	if ids[0] == ids[1] || ids[1] == ids[2] {
		t.Errorf("ids %v: two ats of one intent must differ by provenance", ids)
	}
	if s := res.Steps[0]; s.Step == nil || !s.Step.Unchanged || s.FromID != ids[0] || s.ToID != ids[1] {
		t.Errorf("demo/1 → demo/2: %+v; want unchanged between the two ids", s)
	}
	if s := res.Steps[1]; s.Step == nil || s.Step.Unchanged || len(s.Step.LinksRemoved) != 1 || len(s.Step.LinksAdded) != 0 {
		t.Errorf("demo/2 → demo/3: %+v; want the one link removed", s.Step)
	}
	if w := res.Waypoints[1]; w.Description != "after the first cut-over" || w.Resolved.AtSource != AtGiven ||
		w.Read.Counts != (intent.Counts{Devices: 3, Interfaces: 12, Links: 3, Artifacts: 3}) {
		t.Errorf("demo/2: %+v, read %+v", w, w.Read)
	}
	id := ids[1]
	if got, want := res.Waypoints[1].Block(), (findings.PlanWaypoint{Series: "demo", Sequence: 2, Branch: "main",
		At: "2026-09-28T15:20:44Z", AtSource: AtGiven, Description: "after the first cut-over", BundleID: &id,
		Read: &findings.ReadCounts{Devices: 3, Interfaces: 12, Links: 3, Artifacts: 3}}); !reflect.DeepEqual(got, want) {
		t.Errorf("demo/2's block:\n%+v\nwant\n%+v", got, want)
	}
	mustSatisfyPlanContract(t, res)
}

// A read's warnings stay with its waypoint, at step read, and refuse nothing; two refused
// waypoints side by side are both named by the step between them.
func TestPlanKeepsWarningsAndNamesBothRefused(t *testing.T) {
	unrepresented := findings.List{{Severity: findings.Warning, Rule: findings.RuleArtifactInterfaceUnrepresented, Object: "n1",
		Message: "the artifact names an interface the twin does not have"}}
	rows := demoSeries()
	rows[0].Branch = "gone" // demo/3
	f := &fakeStages{t: t, readWarnings: map[string]findings.List{"main": unrepresented},
		readErr: map[string]error{"gone": errors.New("Branch: gone not found.")}}
	rows[2].At = str("2026-09-28T15:20:44.123456789Z") // demo/2, nine digits
	res, _ := planned(t, &fakeReader{rows: rows}, "demo", f)

	one := res.Waypoints[0]
	if one.Status != PlanCompiled || len(one.Findings) != 1 || one.Findings[0].Rule != findings.RuleArtifactInterfaceUnrepresented ||
		one.Findings[0].Step != findings.StepRead {
		t.Errorf("demo/1: %+v", one)
	}
	if got, want := res.Steps[1].Text(), "step demo/2 → demo/3 (— → —): not computed (demo/2 and demo/3 were refused)"; got != want {
		t.Errorf("step: %s\nwant %s", got, want)
	}
	if three := res.Waypoints[2]; three.Status != PlanFailed || three.Rule != findings.RuleOperationFailed {
		t.Errorf("demo/3: %+v", three)
	}
	mustSatisfyPlanContract(t, res)
}

// A waypoint refused at resolution is reported, both steps touching it are not computed,
// and the plan goes on; the document is rejected (exit 1, even for M1's precision rule,
// whose exit is 2 where it ends a command).
func TestPlanRefusedInTheMiddle(t *testing.T) {
	rows := demoSeries()
	rows[2].At = str("2026-09-28T15:20:44.123456789Z") // demo/2, nine digits
	f := &fakeStages{t: t}
	res, order := planned(t, &fakeReader{rows: rows}, "demo", f)

	if want := []string{"series of 3", "demo/1", "demo/1 → demo/2", "demo/2", "demo/2 → demo/3", "demo/3"}; !reflect.DeepEqual(order, want) {
		t.Errorf("callbacks %v, want %v", order, want)
	}
	if len(f.reads) != 2 {
		t.Errorf("reads %v: a waypoint refused at resolution is never read", f.reads)
	}
	w := res.Waypoints[1]
	if w.Status != PlanRefused || w.Rule != findings.RuleAtPrecision || w.Resolved != nil || w.Bundle != nil ||
		len(w.Findings) != 1 || w.Findings[0].Step != findings.StepResolve || w.Description != "after the first cut-over" {
		t.Errorf("demo/2: %+v", w)
	}
	for i, want := range []string{
		"step demo/1 → demo/2 (" + res.Waypoints[0].Bundle.ID[:8] + "… → —): not computed (demo/2 was refused)",
		"step demo/2 → demo/3 (— → " + res.Waypoints[2].Bundle.ID[:8] + "…): not computed (demo/2 was refused)",
	} {
		if got := res.Steps[i].Text(); got != want {
			t.Errorf("step %d: %s\nwant %s", i, got, want)
		}
	}
	if !res.Findings.Rejected() || !reflect.DeepEqual(res.Findings, w.Findings) {
		t.Errorf("document findings %v; want demo/2's refusal alone", res.Findings)
	}
	mustSatisfyPlanContract(t, res)
}

// A waypoint with no at at all, its as_of unwritten and its branch attribute's updated_at
// null, is refused at resolution and never read: the head of its branch is not its intent.
// Both steps touching it are not computed and the plan exits 1.
func TestPlanWaypointWithNoAt(t *testing.T) {
	rows := demoSeries()
	rows[1].BranchWrittenAt = "" // demo/1, as_of unwritten
	f := &fakeStages{t: t}
	res, _ := planned(t, &fakeReader{rows: rows}, "demo", f)

	w := res.Waypoints[0]
	if w.Status != PlanRefused || w.Rule != findings.RuleWaypointAtUnresolved || w.Resolved != nil || w.Bundle != nil ||
		len(w.Findings) != 1 || w.Findings[0].Step != findings.StepResolve || w.Findings[0].Object != "demo/1" {
		t.Errorf("demo/1: %+v", w)
	}
	if want := []string{"main@2026-09-28T15:20:44Z", "change-1@2026-09-28T15:40:00.000000+00:00"}; !reflect.DeepEqual(f.reads, want) {
		t.Errorf("reads %v, want demo/2's and demo/3's alone (no main@, the head): %v", f.reads, want)
	}
	if got, want := res.Steps[0].Text(), "step demo/1 → demo/2 (— → "+res.Waypoints[1].Bundle.ID[:8]+"…): not computed (demo/1 was refused)"; got != want {
		t.Errorf("step: %s\nwant %s", got, want)
	}
	if st := findings.NewDocument(findings.OpWaypointPlan, nil, res.Findings).Status; st.ExitCode() != findings.ExitRejected {
		t.Errorf("document findings %v, status %s; want a rejection, exit 1", res.Findings, st)
	}
	mustSatisfyPlanContract(t, res)
}

// A waypoint written after the CLI's clock, as one is when Infrahub's clock runs ahead of
// it, is planned: its written at is read verbatim, compiled and filed, and nothing is
// refused.
func TestPlanWrittenAtAfterTheClock(t *testing.T) {
	ahead := []intent.Waypoint{row("id-1", "demo", 1, "main", "2026-09-28T16:10:05.000000+00:00", nil, "just written")}
	f := &fakeStages{t: t}
	res, _ := planned(t, &fakeReader{rows: ahead}, "demo", f)
	w := res.Waypoints[0]
	if w.Status != PlanCompiled || w.Bundle == nil || len(w.Findings) != 0 || res.Findings.Rejected() {
		t.Fatalf("demo/1: %+v; findings %v", w, res.Findings)
	}
	if w.Resolved.AtSource != AtWritten || w.Resolved.At != "2026-09-28T16:10:05.000000+00:00" {
		t.Errorf("resolved %+v; want the written at, verbatim", w.Resolved)
	}
	if want := []string{"main@2026-09-28T16:10:05.000000+00:00"}; !reflect.DeepEqual(f.reads, want) {
		t.Errorf("reads %v, want %v", f.reads, want)
	}
	if !reflect.DeepEqual(f.filed, []string{w.Bundle.ID}) {
		t.Errorf("filed %v, want %s", f.filed, w.Bundle.ID)
	}
	mustSatisfyPlanContract(t, res)
}

// A read refused, a read that cannot run, a compile refused, a filing refused and a filing
// that cannot run: each named at its step, the first two as the text will print them.
func TestPlanPerWaypointOutcomes(t *testing.T) {
	notReady := findings.List{{Severity: findings.Rejection, Rule: findings.RuleArtifactNotReady, Object: "n1",
		Message: "artifact device-config of n1 on branch main is Pending, not Ready"}}
	one := []intent.Waypoint{row("id-1", "demo", 1, "main", "2026-09-28T15:00:01.123456+00:00", nil, "")}
	mismatch := findings.List{{Severity: findings.Rejection, Rule: findings.RuleBundleIDMismatch, Object: "/store/x",
		Message: "the store's entry hashes otherwise", Step: findings.StepCompile}}
	gone := errors.Join(intent.ErrBranchNotFound, errors.New("Branch: main not found."))

	for _, c := range []struct {
		name   string
		f      *fakeStages
		status string
		rule   string
		step   string
		object string
		read   bool
	}{
		{"read refused", &fakeStages{readRefused: map[string]findings.List{"main": notReady}},
			PlanRefused, findings.RuleArtifactNotReady, findings.StepRead, "n1", false},
		{"branch gone", &fakeStages{readErr: map[string]error{"main": gone}},
			PlanFailed, findings.RuleOperationFailed, findings.StepRead, "demo/1", false},
		{"compile refused", &fakeStages{unsupported: map[string]bool{"main": true}},
			PlanRefused, findings.RulePlatformUnsupported, findings.StepCompile, "n1", true},
		{"filing refused", &fakeStages{fileRefusals: mismatch},
			PlanRefused, findings.RuleBundleIDMismatch, findings.StepCompile, "/store/x", true},
		{"filing could not run", &fakeStages{fileErr: errors.New("disk full")},
			PlanFailed, findings.RuleOperationFailed, findings.StepCompile, "demo/1", true},
	} {
		t.Run(c.name, func(t *testing.T) {
			c.f.t = t
			res, _ := planned(t, &fakeReader{rows: one}, "demo", c.f)
			w := res.Waypoints[0]
			if w.Status != c.status || w.Rule != c.rule || w.Bundle != nil || (w.Read != nil) != c.read {
				t.Errorf("%s: status %s, rule %s, read %v, bundle %v", c.name, w.Status, w.Rule, w.Read != nil, w.Bundle)
			}
			var f *findings.Finding
			for i := range w.Findings {
				if w.Findings[i].Rule == c.rule {
					f = &w.Findings[i]
				}
			}
			if f == nil || f.Step != c.step || f.Object != c.object {
				t.Errorf("%s: finding %+v; want %s at step %s on %s", c.name, f, c.rule, c.step, c.object)
			}
			if !res.Findings.Rejected() || len(c.f.filed) != 0 || len(res.Steps) != 0 {
				t.Errorf("%s: findings %v, filed %v, steps %v", c.name, res.Findings, c.f.filed, res.Steps)
			}
			mustSatisfyPlanContract(t, res)
		})
	}
}

// Refusals of the whole plan end it before anything is read: the kind absent, and a series
// no waypoint has, naming those that exist. A reader that cannot list is an error.
func TestPlanRefusedWhole(t *testing.T) {
	for _, c := range []struct {
		name    string
		reader  *fakeReader
		rule    string
		message string
	}{
		{"kind absent", &fakeReader{checkErr: &intent.WaypointKindError{}}, findings.RuleWaypointKindAbsent, ""},
		{"unknown series", &fakeReader{rows: demoSeries()}, findings.RuleWaypointUnknown,
			`no waypoint series "nosuch" exists; the series are: demo, other`},
	} {
		t.Run(c.name, func(t *testing.T) {
			f := &fakeStages{t: t}
			res, order := planned(t, c.reader, "nosuch", f)
			if len(res.Findings) != 1 || res.Findings[0].Rule != c.rule || res.Findings[0].Step != findings.StepResolve ||
				(c.message != "" && res.Findings[0].Message != c.message) {
				t.Errorf("findings %+v", res.Findings)
			}
			if len(f.reads) != 0 || len(order) != 0 || len(res.Waypoints) != 0 {
				t.Errorf("read %v, reported %v: nothing is planned", f.reads, order)
			}
			if b, err := res.Block(); b != nil || err != nil {
				t.Errorf("a plan refused whole has the block %+v, %v", b, err)
			}
		})
	}
	unreachable := errors.New("Infrahub is unreachable")
	if _, err := Plan(context.Background(), &fakeReader{listErr: unreachable}, "demo", registry(t), (&fakeStages{t: t}).stages(),
		now, nil, nil, nil); !errors.Is(err, unreachable) {
		t.Errorf("reader error: %v", err)
	}
}

// A reversed pair warns with the later waypoint and refuses nothing; a sequence two objects
// hold is planned once and refused as waypoint.duplicate.
func TestPlanReversedAndDuplicate(t *testing.T) {
	rows := []intent.Waypoint{
		row("id-1", "demo", 1, "main", "2026-09-28T15:00:01.123456+00:00", nil, ""),
		row("id-2", "demo", 2, "main", "", str("2026-09-27T09:00:00Z"), ""),
		row("id-3b", "demo", 3, "main", "2026-09-28T15:40:00.000000+00:00", nil, "second"),
		row("id-3a", "demo", 3, "main", "2026-09-28T15:40:00.000000+00:00", nil, "first"),
	}
	f := &fakeStages{t: t}
	res, order := planned(t, &fakeReader{rows: rows}, "demo", f)
	if want := []string{"series of 3", "demo/1", "demo/1 → demo/2", "demo/2", "demo/2 → demo/3", "demo/3"}; !reflect.DeepEqual(order, want) {
		t.Errorf("callbacks %v, want each sequence once: %v", order, want)
	}
	two := res.Waypoints[1]
	if two.Status != PlanCompiled || len(two.Findings) != 1 || two.Findings[0].Rule != findings.RuleWaypointTimeReversed ||
		two.Findings[0].Severity != findings.Warning {
		t.Errorf("demo/2: %+v", two)
	}
	three := res.Waypoints[2]
	if three.Status != PlanRefused || three.Rule != findings.RuleWaypointDuplicate || three.Description != "first" ||
		!strings.Contains(three.Findings[0].Message, "ids id-3a, id-3b") {
		t.Errorf("demo/3: %+v", three)
	}
	mustSatisfyPlanContract(t, res)
}

// Two compiled waypoints whose step does not read end the plan with an error naming the pair,
// the side and the file, which waypoint plan reports as operation.failed: a bundle the compile
// just produced always reads, so one that does not is a defect, never a pair reported as not
// computed. Here demo/2's compile returns its bundle without
// manifest.json.
func TestPlanStepThatDoesNotReadIsAnError(t *testing.T) {
	f := &fakeStages{t: t}
	stages := f.stages()
	compiles := 0
	stages.Compile = func(c *ctm.CTM, reg *psp.Registry) (map[string][]byte, string, findings.List) {
		files, id, list := stage.Compile(c, reg)
		if compiles++; compiles == 2 {
			delete(files, "manifest.json")
		}
		return files, id, list
	}
	var steps []string
	res, err := Plan(context.Background(), &fakeReader{rows: demoSeries()}, "demo", registry(t), stages, now,
		nil, nil, func(p step.Pair) { steps = append(steps, p.From+" → "+p.To) })
	if err == nil {
		t.Fatalf("no error; the plan reported %+v", res.Steps)
	}
	for _, want := range []string{"the step demo/1 → demo/2: ", "the to bundle ", "manifest.json: not in the bundle"} {
		if !strings.Contains(err.Error(), want) {
			t.Errorf("error %q does not name %q", err, want)
		}
	}
	if res != nil || len(steps) != 0 {
		t.Errorf("result %+v, steps reported %v: the pair is no step", res, steps)
	}
	if len(f.reads) != 2 {
		t.Errorf("reads %v: the plan ends at the step, before demo/3", f.reads)
	}
}

// mustSatisfyPlanContract validates the plan as waypoint plan's document carries it against
// the newest findings.schema.json (under contracts/, which refers to the show, waypoint,
// step and verify blocks by their $ids), and holds every waypoint's findings to the
// document's own list.
func mustSatisfyPlanContract(t *testing.T, res *PlanResult) {
	t.Helper()
	block, err := res.Block()
	if err != nil {
		t.Fatal(err)
	}
	doc := findings.NewDocument(findings.OpWaypointPlan, nil, res.Findings)
	doc.Plan = block
	raw, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	load := func(name string) any {
		f, err := os.Open(filepath.Join("..", "..", "contracts", name))
		if err != nil {
			t.Fatal(err)
		}
		defer func() { _ = f.Close() }()
		v, err := jsonschema.UnmarshalJSON(f)
		if err != nil {
			t.Fatal(err)
		}
		return v
	}
	c := jsonschema.NewCompiler()
	for _, name := range []string{"show.schema.json", "waypoints.schema.json", "step.schema.json", "verify.schema.json"} {
		if err := c.AddResource("https://fylgja.dev/schemas/"+name, load(name)); err != nil {
			t.Fatal(err)
		}
	}
	if err := c.AddResource("findings.schema.json", load("findings.schema.json")); err != nil {
		t.Fatal(err)
	}
	schema, err := c.Compile("findings.schema.json")
	if err != nil {
		t.Fatal(err)
	}
	v, err := jsonschema.UnmarshalJSON(strings.NewReader(string(raw)))
	if err != nil {
		t.Fatal(err)
	}
	if err := schema.Validate(v); err != nil {
		t.Errorf("the plan's document does not satisfy the contract: %v\n%s", err, raw)
	}
	var all findings.List
	for _, w := range res.Waypoints {
		all = append(all, w.Findings...)
	}
	if (len(all) != 0 || len(res.Findings) != 0) && !reflect.DeepEqual(all, res.Findings) {
		t.Errorf("the document's findings %v are not the waypoints' %v", res.Findings, all)
	}
}
