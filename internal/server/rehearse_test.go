package server

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/rehearsal"
	"github.com/happypathnetworking/fylgja/internal/stages"
	"github.com/happypathnetworking/fylgja/internal/step"
	"github.com/happypathnetworking/fylgja/internal/verify"
)

// twin rehearse's guards (015) refuse before any connection, as stage plan's do: --branch
// absent is --branch is required, operation.failed, and --branch= is stage.ref.invalid at
// start, each exit 2. The options here carry no request, no Infrahub and no service, so a
// guard that let either through would reach for them.
func TestRehearseGuardsBeforeAnyConnection(t *testing.T) {
	for _, c := range []struct {
		name       string
		f          rehearseFlags
		rule, step string
		message    string
	}{
		{"--branch absent", rehearseFlags{}, findings.RuleOperationFailed, "", "--branch is required"},
		{"--branch=", rehearseFlags{branchGiven: true}, findings.RuleStageRefInvalid, findings.StepStart, ""},
	} {
		code, doc := exitOf(t, runTwinRehearse(context.Background(), &options{}, &c.f))
		if code != findings.ExitError || doc.Operation != findings.OpTwinRehearse || len(doc.Findings) != 1 {
			t.Fatalf("%s: exit %d, %+v", c.name, code, doc)
		}
		f := doc.Findings[0]
		if f.Rule != c.rule || f.Step != c.step || c.message != "" && f.Message != c.message {
			t.Errorf("%s: %+v, want %s at %q", c.name, f, c.rule, c.step)
		}
	}
}

const rehearseBranch = "change-1"

var rehearseChange = stages.ProposedChange{ID: "18df0000-0000-7000-8000-000000000001", Name: "third link",
	Branch: rehearseBranch, Destination: "main", Draft: true}

// goldenBundle is testdata/golden/<golden> as a compiled stage holds it.
func goldenBundle(t *testing.T, golden string) step.Bundle {
	t.Helper()
	dir := repoPath("testdata", "golden", golden)
	id, err := bundle.IDOfDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	files, err := bundle.LoadFiles(dir)
	if err != nil {
		t.Fatal(err)
	}
	return step.Bundle{ID: id, Files: files}
}

// snapshotOf is a stage's snapshot id as the tests name it: 64 hex characters of the label's,
// as a take of each stage's read files one (018).
func snapshotOf(label string) string {
	sum := sha256.Sum256([]byte("the snapshot of " + label))
	return hex.EncodeToString(sum[:])
}

// compiledStage is change-1's stage label, resolved at at from atSource, read at observed,
// taken as snapshotOf(label) and compiled to b.
func compiledStage(label, atSource, at, observed string, b step.Bundle) stages.PlanStage {
	ref := stages.Ref{Branch: rehearseBranch, Label: label}
	description := ""
	if atSource == stages.AtGiven || atSource == stages.AtWritten {
		description = "the " + label + " mark"
	}
	return stages.PlanStage{Ref: ref, Label: label, Description: description, AtSource: atSource,
		Resolved: &stages.Resolved{Ref: ref, Branch: rehearseBranch, Label: label, ProposedChange: rehearseChange, At: at,
			AtSource: atSource, Description: description},
		SnapshotID: snapshotOf(label), Bundle: &b, ObservedAt: observed, Findings: findings.List{}, Status: stages.PlanCompiled}
}

// branchPoint is change-1's branch point, resolved on main and refused at read with list,
// beside step 9's warning, as on a default branch that holds no network.
func branchPoint(list ...findings.Finding) stages.PlanStage {
	ref := stages.Ref{Branch: rehearseBranch, Label: stages.LabelBranchPoint}
	st := stages.PlanStage{Ref: ref, Label: ref.Label, AtSource: stages.AtBranchPoint,
		Resolved: &stages.Resolved{Ref: ref, Branch: "main", Label: ref.Label, ProposedChange: rehearseChange,
			At: "2026-10-16T17:20:19.944651+00:00", AtSource: stages.AtBranchPoint},
		Status: stages.PlanRefused}
	st.Findings.AddStep(findings.Warning, findings.StepResolve, findings.RuleStageMainMoved, "main", "main moved")
	st.Findings = append(st.Findings, list...)
	for _, f := range list {
		if f.Severity == findings.Rejection {
			st.Rule = f.Rule
			break
		}
	}
	return st
}

// rejectionAt is one rejection at step.
func rejectionAt(step, rule, object string) findings.Finding {
	return findings.Finding{Severity: findings.Rejection, Step: step, Rule: rule, Object: object, Message: rule + " on " + object}
}

// rehearsePlan is the development host's case (research R-04): the branch point refused
// scope.empty alone, two marks and the head compiled, the head's bundle the second
// mark's, and the plan's steps between them.
func rehearsePlan(t *testing.T) *stages.PlanResult {
	t.Helper()
	seeded, third := goldenBundle(t, "three-node"), goldenBundle(t, "mixed")
	plan := &stages.PlanResult{Branch: rehearseBranch, ProposedChange: &rehearseChange, Stages: []stages.PlanStage{
		branchPoint(rejectionAt(findings.StepRead, findings.RuleScopeEmpty, "tag:fylgja")),
		compiledStage("seeded", stages.AtWritten, "2026-10-16T17:25:30.118244+00:00", "2026-10-19T10:00:01.000000Z", seeded),
		compiledStage("third-link", stages.AtGiven, "2026-10-16T17:30:00.000000+00:00", "2026-10-19T10:00:02.000000Z", third),
		compiledStage(stages.LabelHead, stages.AtHead, "2026-10-16T17:30:11.884302+00:00", "2026-10-19T10:00:03.000000Z", third),
	}}
	for i := 1; i < len(plan.Stages); i++ {
		a, b := plan.Stages[i-1], plan.Stages[i]
		if a.Bundle == nil {
			plan.Steps = append(plan.Steps, step.NotComputed(a.Ref.String(), b.Ref.String(), "", b.BundleID(), a.Ref.String()+" was refused"))
			continue
		}
		s, err := step.Diff(*a.Bundle, *b.Bundle)
		if err != nil {
			t.Fatal(err)
		}
		plan.Steps = append(plan.Steps, step.Between(a.Ref.String(), b.Ref.String(), s))
	}
	for _, st := range plan.Stages {
		plan.Findings = append(plan.Findings, st.Findings...)
	}
	return plan
}

// The baseline rule (research R-03): the branch point refused scope.empty at read
// alone is a refused row passed over, carrying its one rejection; the first compiled stage
// is the baseline and each after it is rehearsed. A branch point that compiled is the
// baseline. Any other refusal refuses the rehearsal with the plan's findings, every stage
// still a row, the refused ones refused: a stale mark, a branch point refused beside
// scope.empty or for it at another step, and a mark refused scope.empty,
// which only the branch point is passed over for. One compiled stage alone is the baseline,
// with rehearsal.steps.none.
func TestRehearsalStagesTakeTheBaselineRule(t *testing.T) {
	roles := func(rows []rehearsalRow) []string {
		var out []string
		for _, r := range rows {
			out = append(out, r.role)
		}
		return out
	}
	refused, baseline, rehearsed := rehearsal.RoleRefused, rehearsal.RoleBaseline, rehearsal.RoleRehearsed

	plan := rehearsePlan(t)
	b, rows, refusal := rehearsalStages(plan)
	if b != 1 || refusal != nil || !slices.Equal(roles(rows), []string{refused, baseline, rehearsed, rehearsed}) {
		t.Fatalf("baseline %d, roles %v, refusal %v", b, roles(rows), refusal)
	}
	if r := rows[0].refused; r == nil || r.Rule != findings.RuleScopeEmpty || r.Message != "scope.empty on tag:fylgja" {
		t.Errorf("the branch point passed over carries %+v", r)
	}
	if !slices.Equal(rows[0].findings, plan.Stages[0].Findings) || carriesRule(findings.List(rows[1].findings), findings.RuleRehearsalStepsNone) {
		t.Errorf("rows' findings %+v", rows)
	}

	// The read of the library's DCIM refuses a main holding no tagged device scope.empty at
	// read, as the generics' read refused one holding no contract instance there: passed over
	// alike.
	emptyScope := rehearsePlan(t)
	emptyScope.Stages[0] = branchPoint(rejectionAt(findings.StepRead, findings.RuleScopeEmpty, "tag:fylgja"))
	if b, rows, refusal := rehearsalStages(emptyScope); b != 1 || refusal != nil || rows[0].refused == nil ||
		rows[0].refused.Rule != findings.RuleScopeEmpty || !slices.Equal(roles(rows), []string{refused, baseline, rehearsed, rehearsed}) {
		t.Errorf("a branch point refused scope.empty: baseline %d, roles %v, refusal %v", b, roles(rows), refusal)
	}

	compiledBP := rehearsePlan(t)
	compiledBP.Stages[0] = compiledStage(stages.LabelBranchPoint, stages.AtBranchPoint, "2026-10-16T17:20:19.944651+00:00", "",
		*compiledBP.Stages[1].Bundle)
	if b, rows, refusal := rehearsalStages(compiledBP); b != 0 || refusal != nil ||
		!slices.Equal(roles(rows), []string{baseline, rehearsed, rehearsed, rehearsed}) {
		t.Errorf("a compiled branch point: baseline %d, roles %v, refusal %v", b, roles(rows), refusal)
	}

	for _, c := range []struct {
		name   string
		change func(*stages.PlanResult)
		status findings.Status
	}{
		{"a stale mark", func(p *stages.PlanResult) {
			p.Stages[2] = stages.PlanStage{Ref: p.Stages[2].Ref, Label: "third-link", AtSource: stages.AtGiven,
				Findings: findings.List{rejectionAt(findings.StepResolve, findings.RuleStageArtifactStale, "n1")},
				Status:   stages.PlanRefused, Rule: findings.RuleStageArtifactStale}
		}, findings.StatusRejected},
		{"the branch point refused beside scope.empty", func(p *stages.PlanResult) {
			p.Stages[0] = branchPoint(rejectionAt(findings.StepRead, findings.RuleScopeEmpty, "tag:fylgja"),
				rejectionAt(findings.StepRead, findings.RulePlatformMissing, "n1"))
		}, findings.StatusRejected},
		{"the branch point refused scope.empty at resolve", func(p *stages.PlanResult) {
			p.Stages[0] = branchPoint(rejectionAt(findings.StepResolve, findings.RuleScopeEmpty, "tag:fylgja"))
		}, findings.StatusRejected},
		{"the branch point refused scope.empty at compile", func(p *stages.PlanResult) {
			p.Stages[0] = branchPoint(rejectionAt(findings.StepCompile, findings.RuleScopeEmpty, "tag:fylgja"))
		}, findings.StatusRejected},
		{"a mark refused scope.empty", func(p *stages.PlanResult) {
			st := p.Stages[1]
			st.Bundle, st.Status, st.Rule = nil, stages.PlanRefused, findings.RuleScopeEmpty
			st.Findings = findings.List{rejectionAt(findings.StepRead, findings.RuleScopeEmpty, rehearseBranch)}
			p.Stages[1] = st
		}, findings.StatusRejected},
		{"a stage that could not be read", func(p *stages.PlanResult) {
			st := p.Stages[3]
			st.Bundle, st.Status, st.Rule = nil, stages.PlanFailed, findings.RuleOperationFailed
			st.Findings = findings.List{rejectionAt(findings.StepRead, findings.RuleOperationFailed, st.Ref.String())}
			p.Stages[3] = st
		}, findings.StatusError},
		{"a mark's at over M1's precision", func(p *stages.PlanResult) {
			st := p.Stages[2]
			st.Bundle, st.Status, st.Rule = nil, stages.PlanRefused, findings.RuleAtPrecision
			st.Findings = findings.List{rejectionAt(findings.StepResolve, findings.RuleAtPrecision, "2026")}
			p.Stages[2] = st
		}, findings.StatusError},
	} {
		plan := rehearsePlan(t)
		c.change(plan)
		plan.Findings = nil
		for _, st := range plan.Stages {
			plan.Findings = append(plan.Findings, st.Findings...)
		}
		b, rows, refusal := rehearsalStages(plan)
		if b != -1 || refusal == nil || !slices.Equal(*refusal, plan.Findings) || len(rows) != 4 {
			t.Errorf("%s: baseline %d, %d rows, refusal %v", c.name, b, len(rows), refusal)
			continue
		}
		for i, st := range plan.Stages {
			if st.Status != stages.PlanCompiled && rows[i].role != refused {
				t.Errorf("%s: stage %s refused takes the role %s", c.name, st.Ref, rows[i].role)
			}
		}
		if got := refusalStatus(plan); got != c.status {
			t.Errorf("%s: status %s, want %s", c.name, got, c.status)
		}
	}

	alone := rehearsePlan(t)
	alone.Stages = []stages.PlanStage{alone.Stages[0], alone.Stages[3]}
	b, rows, refusal = rehearsalStages(alone)
	if b != 1 || refusal != nil || !slices.Equal(roles(rows), []string{refused, baseline}) {
		t.Fatalf("one compiled stage: baseline %d, roles %v, refusal %v", b, roles(rows), refusal)
	}
	if f := rows[1].findings; len(f) != 1 || f[0].Rule != findings.RuleRehearsalStepsNone || f[0].Severity != findings.Warning ||
		f[0].Step != findings.StepResolve || f[0].Object != "change-1/head" {
		t.Errorf("one compiled stage's findings %+v", f)
	}
}

// The step chain (research R-05): every stage of the plan in order with its role; the
// branch point passed over with its refusal and no child; the baseline's provision, already
// compiled, with its stage, its read and the store's copy; and each rehearsed stage's step
// from the compiled stage before it, as twin step builds one but reading no twin: From the
// previous stage's side and To the target's, the plan's step as its diff, the push plan before
// any lifecycle, what only containerlab's lifecycle applies, restarts allowed, every target
// node's declared link change from the registry, the default wait, and an empty plan. An
// unchanged step pushes nobody.
func TestRehearseStagesAreTheStepChain(t *testing.T) {
	plan := rehearsePlan(t)
	b, rows, _ := rehearsalStages(plan)
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	store := fileGoldens(t, "three-node", "mixed")
	nodes := map[string][]wire.NodePlan{}
	for _, st := range plan.Stages[1:] {
		if nodes[st.Ref.String()], err = lab.NodePlans(filepath.Join(store, st.Bundle.ID), reg); err != nil {
			t.Fatal(err)
		}
	}
	path := func(id string) string { return filepath.Join(store, id) }
	got, err := rehearseStages(rows, b, plan.Steps, nodes, reg, path, "tag:fylgja", "0.2.0-test")
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 4 {
		t.Fatalf("%d stages", len(got))
	}
	waitS := int(verify.DefaultBudget / time.Second)

	bp := got[0]
	if bp.Ref != "change-1/branch-point" || bp.Role != rehearsal.RoleRefused || bp.Refused == nil || bp.Provision != nil ||
		bp.Step != nil || bp.SnapshotID != "" || bp.BundleID != "" || bp.Branch != "main" || bp.At != "2026-10-16T17:20:19.944651+00:00" {
		t.Errorf("the branch point %+v", bp)
	}

	// Every compiled stage names its snapshot beside its bundle, the baseline's provision and
	// each step's two sides included (018; R-13).
	seeded, third := plan.Stages[1], plan.Stages[2]
	base := got[1]
	want := &provision.ProvisionInput{Source: wire.SourceIntent, Branch: rehearseBranch, At: seeded.Resolved.At,
		BundlePath: path(seeded.Bundle.ID), BundleID: seeded.Bundle.ID, ObservedAt: seeded.ObservedAt,
		SnapshotID: snapshotOf("seeded"), Stage: seeded.Resolved.StageRef(), Version: "0.2.0-test", Scope: "tag:fylgja"}
	if base.Role != rehearsal.RoleBaseline || base.Step != nil || base.Diff != nil || base.WaitS != waitS ||
		base.BundlePath != path(seeded.Bundle.ID) || base.Description != "the seeded mark" || base.SnapshotID != snapshotOf("seeded") {
		t.Errorf("the baseline %+v", base)
	}
	if p := base.Provision; p == nil || p.Source != want.Source || p.Branch != want.Branch || p.At != want.At ||
		p.BundlePath != want.BundlePath || p.BundleID != want.BundleID || p.ObservedAt != want.ObservedAt || p.SnapshotID != want.SnapshotID ||
		*p.Stage != *want.Stage || p.Version != want.Version || p.Scope != want.Scope || p.Rehearsal != nil ||
		p.Follow != nil {
		t.Errorf("the baseline's provision %+v, want %+v", base.Provision, want)
	}

	for i, c := range []struct {
		from, to stages.PlanStage
		pair     step.Pair
	}{{seeded, third, plan.Steps[1]}, {third, plan.Stages[3], plan.Steps[2]}} {
		got := got[i+2]
		in := got.Step
		if got.Role != rehearsal.RoleRehearsed || got.Provision != nil || in == nil {
			t.Fatalf("stage %s: %+v", got.Ref, got)
		}
		diff, _ := json.Marshal(c.pair)
		if string(got.Diff) != string(diff) || string(in.Diff) != string(diff) {
			t.Errorf("stage %s: diff %s, want the plan's %s", got.Ref, in.Diff, diff)
		}
		if *in.From.Stage != *c.from.Resolved.StageRef() || in.From.BundleID != c.from.Bundle.ID || in.From.At != c.from.Resolved.At ||
			in.From.Branch != "" || in.From.SnapshotID != c.from.SnapshotID {
			t.Errorf("stage %s: from %+v", got.Ref, in.From)
		}
		if *in.To.Stage != *c.to.Resolved.StageRef() || in.To.BundleID != c.to.Bundle.ID || in.To.At != c.to.Resolved.At ||
			in.To.Branch != rehearseBranch || in.To.SnapshotID != c.to.SnapshotID || got.SnapshotID != c.to.SnapshotID {
			t.Errorf("stage %s: to %+v, the stage's snapshot %s", got.Ref, in.To, got.SnapshotID)
		}
		s := *c.pair.Step
		wantPush := []step.NodePush{}
		if !s.Unchanged {
			wantPush = step.PushPlan(s, step.Lifecycle{})
		}
		if in.ObservedAt != c.to.ObservedAt || in.ToBundlePath != path(c.to.Bundle.ID) || in.Unchanged != s.Unchanged ||
			!in.AllowRestart || in.WaitS != waitS || got.WaitS != waitS || !in.Plan.Empty() || in.Version != "0.2.0-test" ||
			!jsonEqual(t, in.PushPlan, wantPush) || !jsonEqual(t, in.Changed, provision.ChangesOf(s)) {
			t.Errorf("stage %s: step %+v", got.Ref, in)
		}
		if len(in.Declared) != 3 {
			t.Errorf("stage %s: declared %v", got.Ref, in.Declared)
		}
		for _, n := range nodes[got.Ref] {
			p, _ := reg.LookupID(n.PSPID)
			if in.Declared[n.Name] != p.Fidelity.LinkChange || p.Fidelity.LinkChange == "" {
				t.Errorf("stage %s: node %s declares %q, its package %q", got.Ref, n.Name, in.Declared[n.Name], p.Fidelity.LinkChange)
			}
		}
	}
	if s := got[2].Step; s.Unchanged || len(s.PushPlan) == 0 || len(s.Changed) == 0 {
		t.Errorf("the step to the mixed bundle %+v", s)
	}
	if s := got[3].Step; !s.Unchanged || len(s.PushPlan) != 0 || s.PushPlan == nil {
		t.Errorf("the unchanged step to the head pushes %v", s.PushPlan)
	}
}

// fileGoldens is a store holding each golden bundle under its id, as the plan files them.
func fileGoldens(t *testing.T, goldens ...string) string {
	t.Helper()
	store := filepath.Join(t.TempDir(), "bundles")
	if err := os.MkdirAll(store, 0o755); err != nil {
		t.Fatal(err)
	}
	for _, g := range goldens {
		id := goldenBundle(t, g).ID
		if err := os.Rename(copyGoldenBundleOf(t, g, id), filepath.Join(store, id)); err != nil {
			t.Fatal(err)
		}
	}
	return store
}

func jsonEqual(t *testing.T, a, b any) bool {
	t.Helper()
	x, err := json.Marshal(a)
	if err != nil {
		t.Fatal(err)
	}
	y, err := json.Marshal(b)
	if err != nil {
		t.Fatal(err)
	}
	return string(x) == string(y)
}

// The deadline is summed from each compiled stage's node plans as the host check plans them
// from the store's copy, and never from the host: the fixture's case, the branch point
// refused and three SR Linux stages, is 1,980 s (research R-09), and the node plans are
// lab.CheckHost's own.
func TestRehearsalDeadlineFromTheStore(t *testing.T) {
	plan := rehearsePlan(t)
	three := goldenBundle(t, "three-node")
	for i := 1; i < len(plan.Stages); i++ {
		b := three
		plan.Stages[i].Bundle = &b
	}
	_, rows, _ := rehearsalStages(plan)
	paths := lab.PathsAt(t.TempDir())
	paths.Bundles = fileGoldens(t, "three-node")
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	r := &rehearsing{rows: rows, planned: plannedStages{res: plan, reg: reg, paths: paths}}
	deadline, nodes, err := r.deadline()
	if err != nil {
		t.Fatal(err)
	}
	if deadline != 1980*time.Second || len(nodes) != 3 {
		t.Errorf("deadline %s over %d stages, want 33m0s over 3", deadline, len(nodes))
	}
	t.Setenv("FYLGJA_SRLINUX_USERNAME", "admin")
	t.Setenv("FYLGJA_SRLINUX_PASSWORD", "not-the-real-one")
	acts := &lab.Activities{Clab: &lab.Clab{Runner: &fakeClab{stdout: []byte(`{}`)}}, Paths: paths, Registry: reg,
		Images: lab.DockerImages{Runner: &fakeClab{}}, Getenv: os.LookupEnv}
	checked, err := lab.CheckHost(context.Background(), acts,
		wire.CheckHostInput{BundlePath: filepath.Join(paths.Bundles, three.ID), BundleID: three.ID})
	if err != nil {
		t.Fatal(err)
	}
	if !jsonEqual(t, nodes["change-1/seeded"], checked.Nodes) {
		t.Errorf("the deadline's node plans differ from the host check's:\n%+v\n%+v", nodes["change-1/seeded"], checked.Nodes)
	}
}

// The status of a rehearsal that ran (research R-08): unclean whatever the stages did when
// the destroy left something or did not report; else by the run's outcome.
func TestRehearsalStatusIsR08s(t *testing.T) {
	clean := &provision.DestroyResult{Cleanup: provision.CleanupResult{Teardown: provision.CleanupDone, Unstage: provision.CleanupDone}}
	left := &provision.DestroyResult{Cleanup: provision.CleanupResult{Teardown: provision.CleanupFailed, Remaining: []string{"lab fylgja"}}}
	for _, c := range []struct {
		outcome string
		destroy *provision.DestroyResult
		want    findings.Status
	}{
		{rehearsal.OutcomeOK, clean, findings.StatusOK},
		{rehearsal.OutcomeStageFailed, clean, findings.StatusNonconforming},
		{rehearsal.OutcomeBaselineFailed, clean, findings.StatusFailed},
		{rehearsal.OutcomeStageError, clean, findings.StatusError},
		{rehearsal.OutcomeCut, clean, findings.StatusError},
		{rehearsal.OutcomeCancelled, clean, findings.StatusError},
		{rehearsal.OutcomeOK, left, findings.StatusUnclean},
		{rehearsal.OutcomeStageFailed, left, findings.StatusUnclean},
		{rehearsal.OutcomeOK, nil, findings.StatusUnclean},
		{rehearsal.OutcomeRejected, nil, findings.StatusRejected},
	} {
		if got := rehearsalStatus(provision.RehearseResult{Outcome: c.outcome, Destroy: c.destroy}); got != c.want {
			t.Errorf("%s with destroy %+v: %s, want %s", c.outcome, c.destroy, got, c.want)
		}
	}
}

// The run's result as the report reads it: each stage's child by its run, the step's plan's
// lifecycle and pushes, a provision's cleanup only when it did not end ready, each child's
// own findings, and the destroy's cleanup.
func TestResultOfTheRunIsTheReportsResult(t *testing.T) {
	took := 2.5
	res := provision.RehearseResult{Outcome: rehearsal.OutcomeStageFailed, UsedS: 118.4,
		Destroy: &provision.DestroyResult{Cleanup: provision.CleanupResult{Teardown: provision.CleanupDone,
			Unstage: provision.CleanupDone, Removed: []string{"lab fylgja (3 containers)"}}},
		Stages: []provision.RehearsedStage{
			{Ref: "change-1/branch-point", Verdict: rehearsal.VerdictRefused},
			{Ref: "change-1/seeded", Verdict: rehearsal.VerdictBaseline, Run: &wire.RunRef{WorkflowID: provision.WorkflowProvision, RunID: "p1"},
				Provision: &provision.ProvisionResult{Outcome: provision.OutcomeReady, Findings: findings.List{{Severity: findings.Warning,
					Rule: findings.RuleHostMemoryUnbudgeted, Object: "host"}}},
				Wait: &wire.StepWait{Outcome: wire.WaitSettled, Reads: 2, AfterS: 3.2}, TookS: 70},
			{Ref: "change-1/third-link", Verdict: rehearsal.VerdictFailed, Run: &wire.RunRef{WorkflowID: provision.WorkflowStep, RunID: "s1"},
				Step: &provision.StepResult{Outcome: provision.StepDiverged, Phase: findings.StepPush,
					Plan:     &wire.ReconcilePlan{Restarted: []string{"n1"}, Recreated: []string{"n2"}, Added: []string{"n4"}},
					PushPlan: []wire.StepPush{{Node: "n1", Outcome: wire.PushRefused, Rule: findings.RulePushRefused}, {Node: "n3", Outcome: wire.PushLanded, TookS: &took}},
					Findings: findings.List{{Severity: findings.Rejection, Rule: findings.RulePushRefused, Object: "n1", Step: findings.StepPush}},
					Timings:  wire.StepTimings{WholeS: 4.5}},
				TookS: 12},
			{Ref: "change-1/head", Verdict: rehearsal.VerdictNotReached},
		}}
	got := resultOf("r1", res)
	if got.Outcome != res.Outcome || got.UsedS != 118.4 || *got.Run != (findings.ShowRef{WorkflowID: provision.WorkflowRehearse, RunID: "r1"}) ||
		got.Destroy == nil || got.Destroy.Teardown != provision.CleanupDone || len(got.Stages) != 4 {
		t.Fatalf("%+v", got)
	}
	base := got.Stages[1]
	if p := base.Provision; p == nil || p.Outcome != provision.OutcomeReady || p.RunID != "p1" || p.Cleanup != nil ||
		len(base.Findings) != 1 || base.Wait.Reads != 2 || base.TookS != 70 {
		t.Errorf("the baseline %+v", base)
	}
	st := got.Stages[2].Step
	if st == nil || st.RunID != "s1" || st.Phase != findings.StepPush || !slices.Equal(st.Restarted, []string{"n1"}) ||
		!slices.Equal(st.Recreated, []string{"n2"}) || !slices.Equal(st.Created, []string{"n4"}) || len(st.Pushed) != 2 ||
		st.Timings.WholeS != 4.5 || len(got.Stages[2].Findings) != 1 {
		t.Errorf("the failed stage's step %+v", st)
	}

	notReady := provision.RehearseResult{Stages: []provision.RehearsedStage{{Ref: "change-1/seeded", Verdict: rehearsal.VerdictError,
		Provision: &provision.ProvisionResult{Outcome: provision.OutcomeFailed, Step: findings.StepDeploy,
			Cleanup: provision.CleanupResult{Teardown: provision.CleanupDone, Unstage: provision.CleanupDone}}}}}
	if c := resultOf("r1", notReady).Stages[0].Provision.Cleanup; c == nil || c.Teardown != provision.CleanupDone {
		t.Errorf("a baseline not built carries its cleanup %+v", c)
	}
}

// The runs that hold the host against a rehearsal (contracts/rehearse-command.md, step 4):
// a rehearsal, a provisioning, step or destroy run, an operator's or a check's child; a
// check at its own step holds nothing the host check does not refuse.
func TestHoldingRunNamesTheFourAndAChecksChild(t *testing.T) {
	check := provision.RunInFlight{WorkflowID: provision.WorkflowReconcile + "-2026-10-19T10:00:00Z", RunID: "c1", Step: "inspect"}
	for _, c := range []struct {
		runs []provision.RunInFlight
		want string
	}{
		{nil, ""},
		{[]provision.RunInFlight{check}, ""},
		{[]provision.RunInFlight{{WorkflowID: provision.WorkflowRehearse, RunID: "r1"}}, "r1"},
		{[]provision.RunInFlight{{WorkflowID: provision.WorkflowProvision, RunID: "p1"}}, "p1"},
		{[]provision.RunInFlight{{WorkflowID: provision.WorkflowStep, RunID: "s1"}}, "s1"},
		{[]provision.RunInFlight{{WorkflowID: provision.WorkflowDestroy, RunID: "d1"}}, "d1"},
		{[]provision.RunInFlight{{WorkflowID: check.WorkflowID, RunID: "c1", Step: "destroy",
			Child: &provision.RunInFlight{WorkflowID: provision.WorkflowDestroy, RunID: "d2"}}}, "d2"},
	} {
		got := holdingRun(c.runs)
		if c.want == "" && got != nil || c.want != "" && (got == nil || got.RunID != c.want) {
			t.Errorf("%+v: %+v, want %q", c.runs, got, c.want)
		}
	}
}

// After the run (contracts/rehearse-command.md, step 7): a stage the rehearsal built or
// stepped to, the head included, that resolves elsewhere or is gone is
// rehearsal.stage.moved, a warning naming it; the passed-over and the not reached are not
// compared; and no row of the proposed change is rehearsal.change.closed alone.
func TestMovedOrClosedAfterTheRun(t *testing.T) {
	block := findings.RehearsalBlock{ProposedChange: findings.StageChange{ID: rehearseChange.ID, Name: rehearseChange.Name,
		Branch: rehearseBranch}, ResolvedAt: "2026-10-19T10:00:00Z", Stages: []findings.RehearsalStage{
		{Ref: "change-1/branch-point", Role: rehearsal.RoleRefused, Branch: "main", At: "a0"},
		{Ref: "change-1/seeded", Role: rehearsal.RoleBaseline, Branch: rehearseBranch, At: "a1"},
		{Ref: "change-1/third-link", Role: rehearsal.RoleRehearsed, Branch: rehearseBranch, At: "a2"},
		{Ref: "change-1/later", Role: rehearsal.RoleRehearsed, Branch: rehearseBranch, At: "a3"},
		{Ref: "change-1/head", Role: rehearsal.RoleRehearsed, Branch: rehearseBranch, At: "a4"},
		{Ref: "change-1/after", Role: rehearsal.RoleNotReached, Branch: rehearseBranch, At: "a5"},
	}}
	row := func(label, branch, at string) stages.Row {
		return stages.Row{Resolved: stages.Resolved{Ref: stages.Ref{Branch: rehearseBranch, Label: label}, Branch: branch, At: at,
			ProposedChange: rehearseChange}}
	}
	rows := []stages.Row{row("branch-point", "main", "moved"), row("seeded", rehearseBranch, "a1"),
		row("third-link", rehearseBranch, "a2-moved"), row("head", rehearseBranch, "a4-moved"), row("after", rehearseBranch, "moved")}
	got := movedOrClosed(rehearseBranch, block, rows)
	var objects []string
	for _, f := range got {
		if f.Rule != findings.RuleRehearsalStageMoved || f.Severity != findings.Warning || f.Step != findings.StepResolve {
			t.Errorf("%+v", f)
		}
		objects = append(objects, f.Object)
	}
	if !slices.Equal(objects, []string{"change-1/third-link", "change-1/later", "change-1/head"}) ||
		!strings.Contains(got[1].Message, "is gone") || !strings.Contains(got[2].Message, "now resolves to branch change-1 at a4-moved") {
		t.Errorf("moved %v:\n%+v", objects, got)
	}

	other := rows[0]
	other.ProposedChange.ID = "another"
	closed := movedOrClosed(rehearseBranch, block, []stages.Row{other})
	if len(closed) != 1 || closed[0].Rule != findings.RuleRehearsalChangeClosed || closed[0].Object != rehearseBranch ||
		closed[0].Severity != findings.Warning {
		t.Errorf("closed %+v", closed)
	}
}

// The rehearsal's progress (contracts/rehearse-command.md, "The text"): each child it starts
// announced by the line naming its stage, in the input's order, before the child's own
// notice and lines; the baseline's wait as that stage's verify; a child's close said by its
// own lines; and the step its children reached kept for the run's cancellation to name.
func TestRehearsalPrinterNamesEachChildsStage(t *testing.T) {
	in := provision.RehearseInput{Stages: []provision.RehearseStage{
		{Ref: "change-1/branch-point", Role: rehearsal.RoleRefused}, {Ref: "change-1/seeded", Role: rehearsal.RoleBaseline},
		{Ref: "change-1/third-link", Role: rehearsal.RoleRehearsed}, {Ref: "change-1/head", Role: rehearsal.RoleRehearsed}}}
	opts := testOptions(t, false)
	p := newRehearsalPrinter(opts, in)
	own := func(step string, end bool, outcome, detail string) provision.Event {
		return provision.Event{WorkflowID: provision.WorkflowRehearse, Step: step, End: end, Outcome: outcome, Detail: detail}
	}
	child := func(workflowID, step, findingStep string) provision.Event {
		return provision.Event{WorkflowID: workflowID, Step: step, FindingStep: findingStep, Of: provision.WorkflowRehearse}
	}
	out := captureStdout(t, func() {
		for _, e := range []provision.Event{
			own(rehearseProvision, false, "", ""),
			{Notice: "run fylgja-provision p1"},
			child(provision.WorkflowProvision, "deploy", findings.StepDeploy),
			own(rehearseProvision, true, provision.EventDone, ""),
			own(stepObserve, false, "", ""),
			own(stepObserve, true, provision.EventDone, "settled after 3.2s (2 reads)"),
			own(rehearseStep, false, "", ""),
			{Notice: "run fylgja-step s1"},
			child(provision.WorkflowStep, "push n1", findings.StepPush),
			own(rehearseStep, true, provision.EventDone, ""),
			own(rehearseStep, false, "", ""),
			own(rehearseStep, true, provision.EventCancelled, ""),
			own(rehearseDestroy, false, "", ""),
			{Notice: "run fylgja-destroy d1"},
			child(provision.WorkflowDestroy, "teardown", findings.StepTeardown),
		} {
			p.print(e)
		}
	})
	want := strings.Join([]string{
		"stage change-1/seeded: creating the twin",
		"run fylgja-provision p1",
		"step deploy: begins",
		"stage change-1/seeded: verify: settled after 3.2s (2 reads)",
		"stage change-1/third-link: stepping",
		"run fylgja-step s1",
		"step push n1: begins",
		"stage change-1/head: stepping",
		"step step: cancelled after 0.0s",
		"destroying the twin",
		"run fylgja-destroy d1",
		"step teardown: begins",
	}, "\n") + "\n"
	if out != want {
		t.Errorf("printed:\n%s\nwant:\n%s", out, want)
	}
	// The destroy, which runs last whatever stopped the run, is not where it was reached.
	if got := p.followed.get(); got != findings.StepPush {
		t.Errorf("the step reached is %q, want push", got)
	}
}

// unreadStages is a stage reader Infrahub does not answer: the stages cannot be read again
// after the run.
type unreadStages struct{ stages.Reader }

func (unreadStages) Check(context.Context) error { return errors.New("no answer from Infrahub") }

// reportedOf is the document a rehearsal of the development host's plan ends with once its
// run closed with res, and the text it printed.
func reportedOf(t *testing.T, res provision.RehearseResult) (*findings.Document, string) {
	t.Helper()
	plan := rehearsePlan(t)
	_, rows, _ := rehearsalStages(plan)
	r := &rehearsing{opts: testOptions(t, false), op: findings.OpTwinRehearse, subject: &findings.Subject{Branch: rehearseBranch,
		Scope: "tag:fylgja", RunID: "r1"}, planned: plannedStages{res: plan, reader: unreadStages{}, scope: "tag:fylgja",
		now: time.Date(2026, 10, 19, 10, 0, 0, 0, time.UTC)}, rows: rows, ceiling: rehearsal.Ceiling, deadlineS: 1980}
	var err error
	out := captureStdout(t, func() { err = r.reported(context.Background(), "r1", res, findings.StepPush) })
	_, doc := exitOf(t, err)
	validateM10Document(t, doc)
	return doc, out
}

// rehearsedResult is a run of the development host's plan to its destroy: the baseline
// built and settled, then each rehearsed stage as steps gives it, the destroy clean.
func rehearsedResult(outcome string, steps ...provision.RehearsedStage) provision.RehearseResult {
	took := 2.5
	res := provision.RehearseResult{Outcome: outcome, UsedS: 118.4, Findings: findings.List{},
		Destroy: &provision.DestroyResult{Cleanup: provision.CleanupResult{Teardown: provision.CleanupDone, Unstage: provision.CleanupDone,
			Removed: []string{"lab fylgja (3 containers)", "twin directory /srv/twin"}}, Findings: findings.List{}},
		Stages: []provision.RehearsedStage{
			{Ref: "change-1/branch-point", Verdict: rehearsal.VerdictRefused},
			{Ref: "change-1/seeded", Verdict: rehearsal.VerdictBaseline, Run: &wire.RunRef{WorkflowID: provision.WorkflowProvision, RunID: "p1"},
				Provision: &provision.ProvisionResult{Outcome: provision.OutcomeReady, Findings: findings.List{}},
				Wait:      &wire.StepWait{Outcome: wire.WaitSettled, BudgetS: 120, Reads: 2, AfterS: 3.2}, TookS: 70},
		}}
	for _, s := range steps {
		if s.Step != nil && s.Step.PushPlan == nil {
			s.Step.PushPlan = []wire.StepPush{{Node: "n1", Outcome: wire.PushLanded, TookS: &took}}
		}
		res.Stages = append(res.Stages, s)
	}
	return res
}

func steppedTo(ref, outcome string, wait *wire.StepWait, verdict rehearsal.Verdict) provision.RehearsedStage {
	return provision.RehearsedStage{Ref: ref, Verdict: verdict, Run: &wire.RunRef{WorkflowID: provision.WorkflowStep, RunID: "s-" + ref},
		Step: &provision.StepResult{Outcome: outcome, Findings: findings.List{}, Timings: wire.StepTimings{WholeS: 4.5}}, Wait: wait, TookS: 12}
}

// The report once the run closed (research R-08, R-10): the block through rehearsal.Build,
// the status by the run's outcome and the destroy, the stage lines and the closing line, and
// a document the findings contract accepts. Stages that cannot be read again are a
// warning, never a failure; an interrupt's cancellation is run.cancelled at the step the
// run's children reached; a destroy that left something is unclean whatever the stages did.
func TestRehearsalReportedOnceTheRunCloses(t *testing.T) {
	settled := &wire.StepWait{Outcome: wire.WaitSettled, BudgetS: 120, Reads: 4, AfterS: 6.1}
	ok := rehearsedResult(rehearsal.OutcomeOK, steppedTo("change-1/third-link", provision.StepStepped, settled, rehearsal.VerdictPassed),
		steppedTo("change-1/head", provision.StepUnchanged, settled, rehearsal.VerdictPassed))
	doc, out := reportedOf(t, ok)
	if doc.Status != findings.StatusOK || doc.Rehearsal == nil || doc.Rehearsal.Run.RunID != "r1" || doc.Subject.RunID != "r1" ||
		doc.Rehearsal.DeadlineS != 1980 || doc.Rehearsal.CeilingS != 3600 || doc.Rehearsal.ResolvedAt != "2026-10-19T10:00:00Z" {
		t.Fatalf("ok: %s %+v", doc.Status, doc.Rehearsal)
	}
	// The branch point passed over keeps its one rejection under its stage, and the status
	// is the run's.
	var rejections []string
	for _, f := range doc.Findings {
		if f.Severity == findings.Rejection {
			rejections = append(rejections, f.Rule)
		}
	}
	if !carriesRule(doc.Findings, findings.RuleRehearsalStageMoved) || !slices.Equal(rejections, []string{findings.RuleScopeEmpty}) {
		t.Errorf("ok: findings %+v", doc.Findings)
	}
	for _, want := range []string{
		"stage change-1/branch-point: refused (scope.empty)\n",
		"stage change-1/seeded: created; settled after 3.2s (2 reads); baseline\n",
		"stage change-1/third-link: stepped in 4.5s (push n1 2.5s); settled after 6.1s (4 reads); passed\n",
		"stage change-1/head: unchanged in 4.5s; settled after 6.1s (4 reads); passed\n",
		"rehearsal ok: 3 stages rehearsed, every one passed; the twin is destroyed; 118.4s of the 1980s deadline\n",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("ok: the text lacks %q:\n%s", want, out)
		}
	}

	diverged := steppedTo("change-1/third-link", provision.StepDiverged, settled, rehearsal.VerdictFailed)
	diverged.Step.Phase = findings.StepPush
	diverged.Step.PushPlan = []wire.StepPush{{Node: "n1", Outcome: wire.PushRefused, Rule: findings.RulePushRefused}}
	failed := rehearsedResult(rehearsal.OutcomeStageFailed, diverged,
		provision.RehearsedStage{Ref: "change-1/head", Verdict: rehearsal.VerdictNotReached})
	doc, out = reportedOf(t, failed)
	if doc.Status != findings.StatusNonconforming || doc.Status.ExitCode() != 5 || !carriesRule(doc.Findings, findings.RuleRehearsalStageFailed) ||
		len(doc.Rehearsal.Reproduce) != 4 {
		t.Errorf("failed: %s %+v %v", doc.Status, doc.Findings, doc.Rehearsal.Reproduce)
	}
	if !strings.Contains(out, "rehearsal nonconforming: stage change-1/third-link failed at phase push; the twin is destroyed; "+
		"reproduce it by hand:\n  fylgja twin create --stage change-1/seeded --scope tag:fylgja\n") || !strings.Contains(out, "stage change-1/head: not reached\n") {
		t.Errorf("failed: the text:\n%s", out)
	}

	cancelled := rehearsedResult(rehearsal.OutcomeCancelled,
		steppedTo("change-1/third-link", provision.OutcomeCancelled, nil, rehearsal.VerdictError),
		provision.RehearsedStage{Ref: "change-1/head", Verdict: rehearsal.VerdictNotReached})
	cancelled.Reached = "change-1/third-link"
	doc, _ = reportedOf(t, cancelled)
	var cancel *findings.Finding
	for i, f := range doc.Findings {
		if f.Rule == findings.RuleRunCancelled {
			cancel = &doc.Findings[i]
		}
	}
	if doc.Status != findings.StatusError || cancel == nil || cancel.Object != "r1" || cancel.Step != findings.StepPush ||
		!strings.Contains(cancel.Message, "at stage change-1/third-link") {
		t.Errorf("cancelled: %s %+v", doc.Status, cancel)
	}

	notBuilt := rehearsedResult(rehearsal.OutcomeBaselineFailed)
	notBuilt.Stages[1] = provision.RehearsedStage{Ref: "change-1/seeded", Verdict: rehearsal.VerdictError,
		Run: &wire.RunRef{WorkflowID: provision.WorkflowProvision, RunID: "p1"},
		Provision: &provision.ProvisionResult{Outcome: provision.OutcomeFailed, Step: findings.StepDeploy,
			Findings: findings.List{rejectionAt(findings.StepDeploy, findings.RuleOperationFailed, "lab fylgja")},
			Cleanup:  provision.CleanupResult{Teardown: provision.CleanupDone, Unstage: provision.CleanupDone}}}
	notBuilt.Stages = append(notBuilt.Stages, provision.RehearsedStage{Ref: "change-1/third-link", Verdict: rehearsal.VerdictNotReached},
		provision.RehearsedStage{Ref: "change-1/head", Verdict: rehearsal.VerdictNotReached})
	doc, _ = reportedOf(t, notBuilt)
	if doc.Status != findings.StatusFailed || !carriesRule(doc.Findings, findings.RuleRehearsalBaselineFailed) ||
		!carriesRule(doc.Findings, findings.RuleOperationFailed) {
		t.Errorf("not built: %s %+v", doc.Status, doc.Findings)
	}

	// Refused at its baseline's start, another run holding the provision's id: rejected,
	// exit 1, with the run's run.in_flight, and no destroy needed, so no cleanup.incomplete
	// (T078).
	held := provision.RehearseResult{Outcome: rehearsal.OutcomeRejected, UsedS: 0.1, Reached: "change-1/seeded",
		Stages: []provision.RehearsedStage{{Ref: "change-1/branch-point", Verdict: rehearsal.VerdictRefused},
			{Ref: "change-1/seeded", Verdict: rehearsal.VerdictNotReached},
			{Ref: "change-1/third-link", Verdict: rehearsal.VerdictNotReached}, {Ref: "change-1/head", Verdict: rehearsal.VerdictNotReached}}}
	held.Findings.AddStep(findings.Rejection, findings.StepProvision, findings.RuleRunInFlight, provision.WorkflowProvision,
		"the rehearsal's fylgja-provision could not start: a run is already in flight under its id")
	doc, out = reportedOf(t, held)
	if doc.Status != findings.StatusRejected || doc.Status.ExitCode() != 1 || !carriesRule(doc.Findings, findings.RuleRunInFlight) ||
		carriesRule(doc.Findings, findings.RuleCleanupIncomplete) || doc.Rehearsal.Destroy != nil || doc.Rehearsal.Run == nil {
		t.Errorf("held: %s %+v %+v", doc.Status, doc.Findings, doc.Rehearsal)
	}
	if !strings.Contains(out, "stage change-1/seeded: not reached\n") || !strings.Contains(out,
		"rehearsal rejected: the run touched nothing, since a run already holds the id of its baseline's provision; no destroy was needed\n") {
		t.Errorf("held: the text:\n%s", out)
	}

	unclean := ok
	unclean.Destroy = &provision.DestroyResult{Cleanup: provision.CleanupResult{Teardown: provision.CleanupFailed,
		Unstage: provision.CleanupDone, Remaining: []string{"lab fylgja"}},
		Findings: findings.List{rejectionAt(findings.StepTeardown, findings.RuleCleanupIncomplete, "lab fylgja")}}
	doc, out = reportedOf(t, unclean)
	if doc.Status != findings.StatusUnclean || !carriesRule(doc.Findings, findings.RuleCleanupIncomplete) ||
		!strings.Contains(out, "the destroy left lab fylgja; twin destroy clears it") {
		t.Errorf("unclean: %s %+v\n%s", doc.Status, doc.Findings, out)
	}
}

// The run's input (data-model §6): the proposed change as the block names it, when the
// stages were resolved, the deadline and the ceiling in seconds, the server's build, and
// the step chain over the store's copies.
func TestRehearseInputIsWhatTheServerDecided(t *testing.T) {
	plan := rehearsePlan(t)
	b, rows, _ := rehearsalStages(plan)
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	paths := lab.PathsAt(t.TempDir())
	paths.Bundles = fileGoldens(t, "three-node", "mixed")
	r := &rehearsing{opts: testOptions(t, false), rows: rows, ceiling: 40 * time.Minute, deadlineS: 1980,
		planned: plannedStages{res: plan, reg: reg, paths: paths, now: time.Date(2026, 10, 19, 10, 0, 0, 123, time.UTC)}}
	_, nodes, err := r.deadline()
	if err != nil {
		t.Fatal(err)
	}
	in, err := r.input(b, nodes)
	if err != nil {
		t.Fatal(err)
	}
	if in.ProposedChange != (findings.StageChange{ID: rehearseChange.ID, Name: "third link", Branch: rehearseBranch, Draft: true}) ||
		in.ResolvedAt != "2026-10-19T10:00:00Z" || in.DeadlineS != 1980 || in.CeilingS != 2400 ||
		in.Version != helperServer.Build || len(in.Stages) != 4 || in.Stages[1].BundlePath != filepath.Join(paths.Bundles, in.Stages[1].BundleID) {
		t.Errorf("%+v", in)
	}
}

// The report names each compiled stage's snapshot beside its bundle, and a refused stage
// neither (018; R-13): the branch point refused at its read, and a stage whose compile was
// refused after its snapshot was filed, which stage plan names but the rehearsal, refused,
// does not. The block validates against rehearsal.schema.json through the findings contract,
// and the markdown's table carries the column before the bundle's (T021).
func TestRehearsalReportNamesEachStagesSnapshot(t *testing.T) {
	plan := rehearsePlan(t)
	_, rows, refusal := rehearsalStages(plan)
	if refusal != nil {
		t.Fatalf("the plan is refused: %+v", *refusal)
	}
	when := time.Date(2026, 10, 19, 10, 0, 0, 0, time.UTC)
	r := &rehearsing{rows: rows, ceiling: 40 * time.Minute, deadlineS: 1980,
		planned: plannedStages{res: plan, scope: "tag:fylgja", now: when}}
	block := rehearsal.Build(r.report(), rehearsal.Result{})
	var named []string
	for _, s := range block.Stages {
		id := "null"
		if s.SnapshotID != nil {
			id = *s.SnapshotID
		}
		named = append(named, s.Ref+" "+id)
	}
	if want := []string{"change-1/branch-point null", "change-1/seeded " + snapshotOf("seeded"),
		"change-1/third-link " + snapshotOf("third-link"), "change-1/head " + snapshotOf("head")}; !slices.Equal(named, want) {
		t.Errorf("the block's snapshots %v\nwant %v", named, want)
	}
	doc := findings.NewDocument(findings.OpTwinRehearse, &findings.Subject{Branch: rehearseBranch, Scope: "tag:fylgja"},
		rehearsal.Findings(block))
	doc.Status = findings.StatusRejected
	doc.Rehearsal = &block
	validateM10Document(t, doc)
	md := rehearsal.Markdown(doc, plan.Steps)
	seeded := plan.Stages[1]
	for _, want := range []string{
		"\n| stage | at | snapshot | bundle | step | wait | verify | new verification failures | verdict |\n",
		" | " + shortID(snapshotOf("seeded")) + " | " + shortID(seeded.Bundle.ID) + " | ",
	} {
		if !strings.Contains(md, want) {
			t.Errorf("the markdown lacks %q:\n%s", want, md)
		}
	}

	// third-link's compile refused once its snapshot was filed: the plan names the snapshot,
	// and the refused rehearsal's row names none.
	third := &plan.Stages[2]
	third.Bundle, third.Status, third.Rule = nil, stages.PlanRefused, findings.RulePlatformUnsupported
	third.Findings = findings.List{rejectionAt(findings.StepCompile, findings.RulePlatformUnsupported, "n1")}
	if third.Block().SnapshotID == nil {
		t.Fatal("the plan's third-link names no snapshot; a compile refused after the take leaves it named")
	}
	_, rows, refusal = rehearsalStages(plan)
	if refusal == nil {
		t.Fatal("a stage refused at its compile did not refuse the rehearsal")
	}
	r.rows = rows
	block = rehearsal.Build(r.report(), rehearsal.Result{})
	if s := block.Stages[2]; s.Ref != "change-1/third-link" || s.SnapshotID != nil || s.BundleID != nil {
		t.Errorf("the refused stage %s names snapshot %v and bundle %v; want null for each", s.Ref, s.SnapshotID, s.BundleID)
	}
}
