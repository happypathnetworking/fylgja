package rehearsal

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"github.com/santhosh-tekuri/jsonschema/v6"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// The example proposed change of contracts/rehearse-command.md: change-1, its branch point
// refused contract.node.missing on a main that holds no network, the mark seeded, the marks
// third-link and bad-port, and the head.
const (
	change       = "change-1"
	resolvedAt   = "2026-10-17T14:02:11Z"
	rehearseRun  = "01a1b2c3-0000-7000-8000-0000000000aa"
	provisionRun = "01a1b2c3-0000-7000-8000-0000000000b1"
	stepRun      = "01a1b2c3-0000-7000-8000-0000000000c"
)

var (
	seededID = strings.Repeat("5c", 32)
	thirdID  = strings.Repeat("d0", 32)
	badID    = strings.Repeat("ba", 32)
	headID   = strings.Repeat("cc", 32)
)

func branchPoint() Stage {
	var l findings.List
	l.AddStep(findings.Rejection, findings.StepRead, findings.RuleContractNodeMissing, "main",
		"branch defines FylgjaContract but holds no instance of it")
	return Stage{Ref: change + "/branch-point", Label: "branch-point", AtSource: findings.AtSourceBranchPoint,
		Branch: "main", At: "2026-10-16T17:20:19.944651+00:00", Role: RoleRefused, Findings: l}
}

func seeded() Stage {
	return Stage{Ref: change + "/seeded", Label: "seeded", Description: "after the link is cabled",
		AtSource: findings.AtSourceWritten, Branch: change, At: "2026-10-16T17:25:30.118244+00:00", BundleID: seededID,
		Role: RoleBaseline}
}

func thirdLink(role string) Stage {
	return Stage{Ref: change + "/third-link", Label: "third-link", Description: "third link", AtSource: findings.AtSourceGiven,
		Branch: change, At: "2026-10-16T17:30:00.000000+00:00", BundleID: thirdID, Role: role}
}

// badPort's description holds what markdown and Mermaid must escape: quotes, angle
// brackets, a pipe and a newline.
func badPort(role string) Stage {
	return Stage{Ref: change + "/bad-port", Label: "bad-port", Description: "a port <disabled> \"by mistake\" | n1\nsecond line",
		AtSource: findings.AtSourceGiven, Branch: change, At: "2026-10-16T17:30:05.000000+00:00", BundleID: badID, Role: role}
}

func head(role string) Stage {
	return Stage{Ref: change + "/head", Label: "head", AtSource: findings.AtSourceHead, Branch: change,
		At: "2026-10-16T17:30:11.884302+00:00", BundleID: headID, Role: role}
}

func input(deadlineS int, stages ...Stage) Input {
	return Input{ProposedChange: findings.StageChange{ID: "18df5c2e-0000-4000-8000-000000000001", Name: "third link",
		Branch: change, Draft: true}, ResolvedAt: resolvedAt, DeadlineS: deadlineS, CeilingS: 3600, Stages: stages}
}

func zero() *int { return new(int) }

// counts are a three-node twin's last read: a host name per node, ports and neighbours
// each, every one held but failed of the neighbours.
func counts(ports, failed int) *wire.VerifyCounts {
	return &wire.VerifyCounts{
		HostName:    findings.VerifyCount{Held: 3, Unread: zero()},
		PortEnabled: findings.VerifyCount{Held: ports, Skipped: zero(), Unread: zero()},
		Neighbor:    findings.VerifyCount{Held: ports - failed, Failed: failed, Skipped: zero(), Unread: zero()},
		Record:      findings.VerifyCount{Held: 3},
	}
}

func wait(outcome string, afterS float64, reads int, failing ...wire.StepFinding) *wire.StepWait {
	return &wire.StepWait{Outcome: outcome, BudgetS: 120, Reads: reads, AfterS: afterS, From: resolvedAt,
		EndedAt: resolvedAt, Failing: failing}
}

func took(s float64) *float64 { return &s }

func run() *findings.ShowRef {
	return &findings.ShowRef{WorkflowID: wire.RehearseWorkflowID, RunID: rehearseRun}
}

func destroyed() *findings.CleanupBlock {
	return &findings.CleanupBlock{Teardown: "done", Unstage: "done",
		Removed: []string{"lab fylgja (3 containers)", "twin directory /srv/fylgja/local/twin"}}
}

// built is the baseline created, its wait as given.
func built(w *wire.StepWait, c *wire.VerifyCounts, tookS float64) StageResult {
	return StageResult{Ref: change + "/seeded", Verdict: VerdictBaseline,
		Provision: &Provision{Outcome: provisionReady, RunID: provisionRun}, Wait: w, Counts: c, TookS: tookS}
}

// stepTo is a step child into ref, numbered for its run id.
func stepTo(ref string, n int, outcome string, wholeS float64, pushes ...wire.StepPush) *StepRun {
	push := map[string]float64{}
	for _, p := range pushes {
		if p.TookS != nil {
			push[p.Node] = *p.TookS
		}
	}
	if len(push) == 0 {
		push = nil
	}
	return &StepRun{Outcome: outcome, RunID: stepRun + string(rune('0'+n)), Pushed: pushes,
		Timings: wire.StepTimings{Push: push, WholeS: wholeS}}
}

func landed(node string, s float64) wire.StepPush {
	return wire.StepPush{Node: node, Reasons: []string{"artifact"}, Outcome: wire.PushLanded, TookS: took(s)}
}

// The baseline's one finding, which every later wait repeats.
var baselineFinding = wire.StepFinding{Rule: findings.RuleVerifyNeighbor, Object: "n1:ethernet-1/2",
	Message: "node n1 (172.20.20.2): port ethernet-1/2 sees no neighbour at /interface[name=ethernet-1/2]; link l1 names n2 ethernet-1/2 at its far end"}

// A rehearsal's runs, each as its document's block and status.
type example struct {
	name   string
	in     Input
	res    Result
	status findings.Status
}

func passedRun() example {
	return example{"ok, the branch point refused and the head unchanged",
		input(1950, branchPoint(), seeded(), thirdLink(RoleRehearsed), head(RoleRehearsed)),
		Result{Outcome: OutcomeOK, Run: run(), UsedS: 118.4, Destroy: destroyed(), Stages: []StageResult{
			built(wait(wire.WaitSettled, 3.2, 2), counts(6, 0), 52.6),
			{Ref: change + "/third-link", Verdict: VerdictPassed,
				Step: stepTo(change+"/third-link", 1, wire.StepStepped, 4.5, landed("n1", 2.5), landed("n3", 2.6)),
				Wait: wait(wire.WaitSettled, 6.1, 4), Counts: counts(8, 0), TookS: 10.6},
			{Ref: change + "/head", Verdict: VerdictPassed, Step: stepTo(change+"/head", 2, wire.StepUnchanged, 0.9),
				Wait: wait(wire.WaitSettled, 1.0, 1), Counts: counts(8, 0), TookS: 1.9},
		}},
		findings.StatusOK}
}

func failedRun() example {
	badStep := stepTo(change+"/bad-port", 2, wire.StepDiverged, 29.8,
		wire.StepPush{Node: "n1", Reasons: []string{"artifact"}, Outcome: wire.PushRefused, Rule: findings.RulePushRefused, TookS: took(1.1)},
		landed("n3", 2.4))
	badStep.Phase, badStep.Step, badStep.Restarted = findings.StepPush, findings.StepPush, []string{"n3"}
	var refused findings.List
	refused.AddStep(findings.Rejection, findings.StepPush, findings.RulePushRefused, "n1",
		"n1 refused artifact device-config (checksum 9a0177b2e8c1d4f5a6b7c8d9e0f1a2b3) at line 12: invalid port ethernet-1/99")
	return example{"nonconforming, a stage diverged at its push",
		input(2580, branchPoint(), seeded(), thirdLink(RoleRehearsed), badPort(RoleRehearsed), head(RoleRehearsed)),
		Result{Outcome: OutcomeStageFailed, Run: run(), UsedS: 301.6, Destroy: destroyed(), Stages: []StageResult{
			built(wait(wire.WaitExpired, 120, 58, baselineFinding), counts(6, 1), 172.4),
			{Ref: change + "/third-link", Verdict: VerdictPassed,
				Step: stepTo(change+"/third-link", 1, wire.StepStepped, 4.5, landed("n1", 2.5), landed("n3", 2.6)),
				Wait: wait(wire.WaitExpired, 120, 60, baselineFinding), Counts: counts(8, 1), TookS: 124.5},
			{Ref: change + "/bad-port", Verdict: VerdictFailed, Step: badStep,
				Wait: wait(wire.WaitExpired, 120, 58, baselineFinding), Counts: counts(8, 1), Findings: refused, TookS: 149.8},
		}},
		findings.StatusNonconforming}
}

func newFindingRun() example {
	added := wire.StepFinding{Rule: findings.RuleVerifyNeighbor, Object: "n1:ethernet-1/3",
		Message: "node n1 (172.20.20.2): port ethernet-1/3 sees no neighbour"}
	return example{"nonconforming, a finding the baseline did not have",
		input(1950, seeded(), thirdLink(RoleRehearsed), head(RoleRehearsed)),
		Result{Outcome: OutcomeStageFailed, Run: run(), UsedS: 190.2, Destroy: destroyed(), Stages: []StageResult{
			built(wait(wire.WaitSettled, 3.2, 2), counts(6, 0), 52.6),
			{Ref: change + "/third-link", Verdict: VerdictFailed,
				Step: stepTo(change+"/third-link", 1, wire.StepStepped, 4.5, landed("n1", 2.5), landed("n3", 2.6)),
				Wait: wait(wire.WaitExpired, 120, 61, added), Counts: counts(8, 1), NewFindings: []wire.StepFinding{added},
				TookS: 124.5},
		}},
		findings.StatusNonconforming}
}

func cutRun() example {
	cut := stepTo(change+"/third-link", 1, outcomeCancelled, 1861.9)
	cut.Phase, cut.Step = findings.StepReadiness, findings.StepReadiness
	return example{"error, the deadline cut a step",
		input(1950, seeded(), thirdLink(RoleRehearsed), head(RoleRehearsed)),
		Result{Outcome: OutcomeCut, Run: run(), UsedS: 1971.2, Destroy: destroyed(), Stages: []StageResult{
			built(wait(wire.WaitSettled, 3.2, 2), counts(6, 0), 88.1),
			{Ref: change + "/third-link", Verdict: VerdictError, Step: cut, TookS: 1861.9},
		}},
		findings.StatusError}
}

func notBuiltRun() example {
	var timeout findings.List
	timeout.AddStep(findings.Rejection, findings.StepReadiness, findings.RuleReadinessTimeout, "n2", "n2 did not answer its probe within 60s")
	return example{"failed, the baseline not built",
		input(1950, branchPoint(), seeded(), thirdLink(RoleRehearsed)),
		Result{Outcome: OutcomeBaselineFailed, Run: run(), UsedS: 243.0,
			Destroy: &findings.CleanupBlock{Teardown: "nothing", Unstage: "nothing"}, Stages: []StageResult{
				{Ref: change + "/seeded", Verdict: VerdictError, Findings: timeout, TookS: 241.3,
					Provision: &Provision{Outcome: "failed", RunID: provisionRun, Step: findings.StepReadiness,
						Cleanup: &findings.CleanupBlock{Teardown: "done", Unstage: "done", Removed: []string{"lab fylgja (3 containers)"}}}},
			}},
		findings.StatusFailed}
}

func uncleanRun() example {
	e := passedRun()
	e.name, e.status = "unclean, every stage passed and the destroy left the lab", findings.StatusUnclean
	e.res.Destroy = &findings.CleanupBlock{Teardown: "failed", Unstage: "done",
		Removed: []string{"twin directory /srv/fylgja/local/twin"}, Remaining: []string{"lab fylgja (1 container)"}}
	return e
}

func aloneRun() example {
	s := seeded()
	s.Findings.AddStep(findings.Warning, findings.StepResolve, findings.RuleRehearsalStepsNone, s.Ref,
		"one stage compiled: it is built, verified and destroyed, and no step is rehearsed")
	return example{"ok, one stage alone",
		input(690, s),
		Result{Outcome: OutcomeOK, Run: run(), UsedS: 61.2, Destroy: destroyed(), Stages: []StageResult{
			built(wait(wire.WaitSettled, 3.2, 2), counts(6, 0), 55.3),
		}},
		findings.StatusOK}
}

func refusedRun() example {
	e := example{"rejected, the deadline over the ceiling",
		input(3840, seeded(), thirdLink(RoleRehearsed), badPort(RoleRehearsed), head(RoleRehearsed)), Result{},
		findings.StatusRejected}
	return e
}

func examples() []example {
	return []example{passedRun(), failedRun(), newFindingRun(), cutRun(), notBuiltRun(), uncleanRun(), aloneRun(), refusedRun()}
}

// document is the example's findings document as the server would send it: the block, its
// findings, and the refusal's own finding when no run began.
func (e example) document() *findings.Document {
	b := Build(e.in, e.res)
	list := Findings(b)
	subject := &findings.Subject{Branch: change}
	if e.res.Run != nil {
		subject.RunID = e.res.Run.RunID
	} else {
		list.AddStep(findings.Rejection, findings.StepStart, findings.RuleRehearsalDeadlineUnfit, change,
			"the stages need 3840s, over the ceiling of 3600s")
	}
	doc := findings.NewDocument(findings.OpTwinRehearse, subject, list)
	doc.Status = e.status
	doc.Rehearsal = &b
	return doc
}

func contract(name string) string { return filepath.Join("..", "..", "contracts", name) }

// findingsSchema is the current findings contract with the blocks it refers to by $id.
func findingsSchema(t *testing.T) *jsonschema.Schema {
	t.Helper()
	load := func(name string) any {
		f, err := os.Open(contract(name))
		if err != nil {
			t.Fatal(err)
		}
		defer func() { _ = f.Close() }()
		doc, err := jsonschema.UnmarshalJSON(f)
		if err != nil {
			t.Fatalf("parsing %s: %v", name, err)
		}
		return doc
	}
	c := jsonschema.NewCompiler()
	for _, name := range []string{"show.schema.json", "stages.schema.json", "step.schema.json", "verify.schema.json", "rehearsal.schema.json"} {
		if err := c.AddResource("https://fylgja.dev/schemas/"+name, load(name)); err != nil {
			t.Fatal(err)
		}
	}
	if err := c.AddResource("findings.schema.json", load("findings.schema.json")); err != nil {
		t.Fatal(err)
	}
	s, err := c.Compile("findings.schema.json")
	if err != nil {
		t.Fatal(err)
	}
	return s
}

// contentMarkers are strings that would appear in a document only if a byte of artifact
// content or a credential had reached it, as internal/findings' tests name them.
var contentMarkers = []string{
	"FYLGJA-MARKER",
	"set / interface",
	"enter candidate private",
	"commit now",
	"NokiaSrl1!",
	"admin:admin",
}

func carriesNoContent(t *testing.T, label, s string) {
	t.Helper()
	for _, m := range contentMarkers {
		if strings.Contains(s, m) {
			t.Errorf("%s carries %q, which can only have come from configuration content or a credential", label, m)
		}
	}
}

// Every block Build makes, for ok, nonconforming, error by the deadline, a baseline not
// built, unclean, one stage alone and a refusal, is the contract's, in a document that is
// the findings contract's; none carries a configuration line, a device diff, a token or a
// login (FR-012).
func TestBlockValidates(t *testing.T) {
	schema := findingsSchema(t)
	for _, e := range examples() {
		t.Run(e.name, func(t *testing.T) {
			doc := e.document()
			var b bytes.Buffer
			if err := doc.WriteJSON(&b); err != nil {
				t.Fatal(err)
			}
			v, err := jsonschema.UnmarshalJSON(bytes.NewReader(b.Bytes()))
			if err != nil {
				t.Fatal(err)
			}
			if err := schema.Validate(v); err != nil {
				t.Errorf("the document does not satisfy the contract: %v\n%s", err, b.Bytes())
			}
			carriesNoContent(t, e.name, b.String())
			if len(doc.Rehearsal.Stages) != len(e.in.Stages) {
				t.Errorf("%d stages in the block for %d planned", len(doc.Rehearsal.Stages), len(e.in.Stages))
			}
		})
	}

	// The contract is read: a verdict it does not enumerate is refused.
	doc := passedRun().document()
	doc.Rehearsal.Stages[1].Verdict = "skipped"
	raw, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	v, err := jsonschema.UnmarshalJSON(bytes.NewReader(raw))
	if err != nil {
		t.Fatal(err)
	}
	if schema.Validate(v) == nil {
		t.Error("a verdict the contract does not enumerate satisfied it")
	}
}

// The roles and verdicts Build gives: a stage the run did not reach is not reached, in a run
// or a refusal; the refused branch point stays refused; the baseline block is set once the
// baseline was built.
func TestBuildRolesAndVerdicts(t *testing.T) {
	type rv struct{ role, verdict string }
	roles := func(b findings.RehearsalBlock) []rv {
		out := make([]rv, len(b.Stages))
		for i, s := range b.Stages {
			out[i] = rv{s.Role, s.Verdict}
		}
		return out
	}
	for _, c := range []struct {
		e        example
		want     []rv
		baseline bool
	}{
		{passedRun(), []rv{{"refused", "refused"}, {"baseline", "baseline"}, {"rehearsed", "passed"}, {"rehearsed", "passed"}}, true},
		{failedRun(), []rv{{"refused", "refused"}, {"baseline", "baseline"}, {"rehearsed", "passed"}, {"rehearsed", "failed"},
			{"not_reached", "not_reached"}}, true},
		{cutRun(), []rv{{"baseline", "baseline"}, {"rehearsed", "error"}, {"not_reached", "not_reached"}}, true},
		{notBuiltRun(), []rv{{"refused", "refused"}, {"baseline", "error"}, {"not_reached", "not_reached"}}, false},
		{refusedRun(), []rv{{"not_reached", "not_reached"}, {"not_reached", "not_reached"}, {"not_reached", "not_reached"},
			{"not_reached", "not_reached"}}, false},
	} {
		b := Build(c.e.in, c.e.res)
		if got := roles(b); !reflect.DeepEqual(got, c.want) {
			t.Errorf("%s: roles and verdicts %v, want %v", c.e.name, got, c.want)
		}
		if (b.Baseline != nil) != c.baseline {
			t.Errorf("%s: baseline block %+v", c.e.name, b.Baseline)
		}
	}

	// The baseline's findings are its wait's; a later stage's repeat is a warning of its own,
	// prefixed by the stage, and never a new finding.
	b := Build(failedRun().in, failedRun().res)
	if want := []findings.StepWaitFailing{findings.StepWaitFailing(baselineFinding)}; !reflect.DeepEqual(b.Baseline.Findings, want) {
		t.Errorf("the baseline findings are %v", b.Baseline.Findings)
	}
	third := b.Stages[2]
	if len(third.NewFindings) != 0 || !carriesFinding(third.Findings, findings.Warning, findings.RuleVerifyNeighbor,
		change+"/third-link: n1:ethernet-1/2") {
		t.Errorf("third-link's findings %v, new %v", third.Findings, third.NewFindings)
	}
}

func carriesFinding(l findings.List, sev findings.Severity, rule, object string) bool {
	for _, f := range l {
		if f.Severity == sev && f.Rule == rule && f.Object == object {
			return true
		}
	}
	return false
}

// The rehearsal's own findings, each on the stage it is about, worded as the text says it.
func TestBuildFilesTheRehearsalsOwnFindings(t *testing.T) {
	for _, c := range []struct {
		e                   example
		stage               int
		rule, step, message string
	}{
		{failedRun(), 3, findings.RuleRehearsalStageFailed, findings.StepPush,
			"diverged at phase push: landed n3; not landed n1 (push.refused)"},
		{newFindingRun(), 1, findings.RuleRehearsalStageFailed, findings.StepObserve,
			"its wait holds a finding the baseline's did not: verify.neighbor n1:ethernet-1/3"},
		{cutRun(), 1, findings.RuleRehearsalDeadlineCut, findings.StepReadiness,
			"the deadline of 1950s passed at stage change-1/third-link: change-1/seeded took 88.1s"},
		{notBuiltRun(), 1, findings.RuleRehearsalBaselineFailed, findings.StepProvision,
			"the baseline change-1/seeded could not be built: its provision ended failed at readiness"},
	} {
		b := Build(c.e.in, c.e.res)
		var found *findings.Finding
		for i, f := range b.Stages[c.stage].Findings {
			if f.Rule == c.rule {
				found = &b.Stages[c.stage].Findings[i]
			}
		}
		if found == nil || found.Severity != findings.Rejection || found.Step != c.step || found.Message != c.message ||
			found.Object != b.Stages[c.stage].Ref {
			t.Errorf("%s: %s is %+v, want at %s %q", c.e.name, c.rule, found, c.step, c.message)
		}
	}

	// A step that could not run is rehearsal.stage.error at the step it stopped at; a run
	// cancelled by the operator files none of the rehearsal's, the server's run.cancelled
	// saying why.
	rejected := cutRun()
	rejected.res.Outcome = OutcomeStageError
	locked := stepTo(change+"/third-link", 1, outcomeRejected, 0.4)
	locked.Step = findings.StepInspect
	rejected.res.Stages[1].Step = locked
	b := Build(rejected.in, rejected.res)
	if !carriesFinding(b.Stages[1].Findings, findings.Rejection, findings.RuleRehearsalStageError, change+"/third-link") ||
		b.Stages[1].Findings[0].Step != findings.StepInspect {
		t.Errorf("a step rejected by its locks: %+v", b.Stages[1].Findings)
	}
	cancelled := cutRun()
	cancelled.res.Outcome = OutcomeCancelled
	if l := Build(cancelled.in, cancelled.res).Stages[1].Findings; len(l) != 0 {
		t.Errorf("a run the operator cancelled files %v", l)
	}
}

func TestReproduce(t *testing.T) {
	if got := Build(passedRun().in, passedRun().res).Reproduce; got == nil || len(got) != 0 {
		t.Errorf("no stage failed: %#v, want []", got)
	}
	if got := Build(cutRun().in, cutRun().res).Reproduce; len(got) != 0 {
		t.Errorf("a stage the deadline cut taught nothing to reproduce: %v", got)
	}

	// The failure at the first rehearsed stage.
	first := newFindingRun()
	if got, want := Build(first.in, first.res).Reproduce, []string{
		"fylgja twin create --stage change-1/seeded",
		"fylgja twin step --stage change-1/third-link --allow-restart",
		"fylgja twin verify", "fylgja twin destroy",
	}; !reflect.DeepEqual(got, want) {
		t.Errorf("failed at the first rehearsed stage: %q, want %q", got, want)
	}

	// The failure at the third rehearsed stage, after the refused branch point, which no
	// command names.
	third := failedRun()
	third.in.Stages = []Stage{branchPoint(), seeded(), thirdLink(RoleRehearsed), {Ref: change + "/live", Label: "live",
		AtSource: findings.AtSourceGiven, Branch: change, At: "2026-10-16T17:30:02.000000+00:00", BundleID: thirdID,
		Role: RoleRehearsed}, badPort(RoleRehearsed), head(RoleRehearsed)}
	live := third.res.Stages[1]
	live.Ref = change + "/live"
	third.res.Stages = append(third.res.Stages[:2], append([]StageResult{live}, third.res.Stages[2:]...)...)
	if got, want := Build(third.in, third.res).Reproduce, []string{
		"fylgja twin create --stage change-1/seeded",
		"fylgja twin step --stage change-1/third-link --allow-restart",
		"fylgja twin step --stage change-1/live --allow-restart",
		"fylgja twin step --stage change-1/bad-port --allow-restart",
		"fylgja twin verify", "fylgja twin destroy",
	}; !reflect.DeepEqual(got, want) {
		t.Errorf("failed at the third rehearsed stage: %q, want %q", got, want)
	}

	// A label is any characters but a slash and white space: one a shell would read is
	// quoted, so each command runs as given.
	for ref, want := range map[string]string{
		"change-1/seeded": "change-1/seeded", "change-1/it's": `'change-1/it'\''s'`, "change-1/a;b": "'change-1/a;b'",
		"change-1/$HOME": "'change-1/$HOME'", `change-1/"x"`: `'change-1/"x"'`,
	} {
		if got := shellWord(ref); got != want {
			t.Errorf("shellWord(%q) = %s, want %s", ref, got, want)
		}
	}
}

// The text's stage lines and closing line, pinned (contracts/rehearse-command.md, "The
// text").
func TestStageLinesAndClosing(t *testing.T) {
	for _, c := range []struct {
		e       example
		lines   []string
		closing string
	}{
		{passedRun(), []string{
			"stage change-1/branch-point: refused (contract.node.missing)",
			"stage change-1/seeded: created; settled after 3.2s (2 reads); 15 held, 0 failed, 0 skipped; baseline",
			"stage change-1/third-link: stepped in 4.5s (push n1 2.5s, n3 2.6s); settled after 6.1s (4 reads); 19 held, 0 failed, 0 skipped; passed",
			"stage change-1/head: unchanged in 0.9s; settled after 1.0s (1 read); 19 held, 0 failed, 0 skipped; passed",
		}, "rehearsal ok: 3 stages rehearsed, every one passed; the twin is destroyed; 118.4s of the 1950s deadline"},
		{failedRun(), []string{
			"stage change-1/branch-point: refused (contract.node.missing)",
			"stage change-1/seeded: created; expired after 120.0s (58 reads); 14 held, 1 failed, 0 skipped; baseline",
			"stage change-1/third-link: stepped in 4.5s (push n1 2.5s, n3 2.6s); expired after 120.0s (60 reads); 18 held, 1 failed, 0 skipped; passed",
			"stage change-1/bad-port: diverged at phase push: landed n3; not landed n1 (push.refused); expired after 120.0s (58 reads); 18 held, 1 failed, 0 skipped; failed",
			"stage change-1/head: not reached",
		}, "rehearsal nonconforming: stage change-1/bad-port failed at phase push; the twin is destroyed; reproduce it by hand:\n" +
			"  fylgja twin create --stage change-1/seeded\n" +
			"  fylgja twin step --stage change-1/third-link --allow-restart\n" +
			"  fylgja twin step --stage change-1/bad-port --allow-restart\n" +
			"  fylgja twin verify\n" +
			"  fylgja twin destroy"},
		{newFindingRun(), []string{
			"stage change-1/seeded: created; settled after 3.2s (2 reads); 15 held, 0 failed, 0 skipped; baseline",
			"stage change-1/third-link: stepped in 4.5s (push n1 2.5s, n3 2.6s); expired after 120.0s (61 reads); 18 held, 1 failed, 0 skipped; failed: verify.neighbor n1:ethernet-1/3",
			"stage change-1/head: not reached",
		}, "rehearsal nonconforming: stage change-1/third-link failed: verify.neighbor n1:ethernet-1/3; the twin is destroyed; reproduce it by hand:\n" +
			"  fylgja twin create --stage change-1/seeded\n" +
			"  fylgja twin step --stage change-1/third-link --allow-restart\n" +
			"  fylgja twin verify\n" +
			"  fylgja twin destroy"},
		{cutRun(), []string{
			"stage change-1/seeded: created; settled after 3.2s (2 reads); 15 held, 0 failed, 0 skipped; baseline",
			"stage change-1/third-link: cancelled at phase readiness; error: the deadline passed",
			"stage change-1/head: not reached",
		}, "rehearsal error: the deadline of 1950s passed at stage change-1/third-link; the twin is destroyed"},
		{notBuiltRun(), []string{
			"stage change-1/branch-point: refused (contract.node.missing)",
			"stage change-1/seeded: not built: its provision ended failed at readiness",
			"stage change-1/third-link: not reached",
		}, "rehearsal failed: the baseline change-1/seeded could not be built: its provision ended failed at readiness; the twin is destroyed"},
		{uncleanRun(), nil,
			"rehearsal unclean: 3 stages rehearsed, every one passed; the destroy left lab fylgja (1 container); twin destroy clears it"},
		{aloneRun(), []string{
			"stage change-1/seeded: created; settled after 3.2s (2 reads); 15 held, 0 failed, 0 skipped; baseline",
		}, "rehearsal ok: the baseline alone was built and verified, and no step was rehearsed; the twin is destroyed; 61.2s of the 690s deadline"},
		{refusedRun(), []string{
			"stage change-1/seeded: not reached", "stage change-1/third-link: not reached",
			"stage change-1/bad-port: not reached", "stage change-1/head: not reached",
		}, "rehearsal rejected: nothing was started"},
	} {
		b := Build(c.e.in, c.e.res)
		if got := StageLines(b); c.lines != nil && !reflect.DeepEqual(got, c.lines) {
			t.Errorf("%s: stage lines\n%s\nwant\n%s", c.e.name, strings.Join(got, "\n"), strings.Join(c.lines, "\n"))
		}
		if got := Closing(b, c.e.status); got != c.closing {
			t.Errorf("%s: closing\n%s\nwant\n%s", c.e.name, got, c.closing)
		}
	}

	// A step that could not run, and a run the operator cancelled, each say so.
	locked := cutRun()
	locked.res.Outcome = OutcomeStageError
	step := stepTo(change+"/third-link", 1, outcomeRejected, 0.4)
	step.Step = findings.StepInspect
	locked.res.Stages[1].Step = step
	b := Build(locked.in, locked.res)
	if got, want := StageLines(b)[1], "stage change-1/third-link: rejected; error: its step was rejected"; got != want {
		t.Errorf("a step rejected: %s, want %s", got, want)
	}
	if got, want := Closing(b, findings.StatusError),
		"rehearsal error: stage change-1/third-link could not be rehearsed: its step was rejected; the twin is destroyed"; got != want {
		t.Errorf("a step rejected: %s, want %s", got, want)
	}
	cancelled := cutRun()
	cancelled.res.Outcome = OutcomeCancelled
	b = Build(cancelled.in, cancelled.res)
	if got, want := Closing(b, findings.StatusError),
		"rehearsal error: the run was cancelled at stage change-1/third-link; the twin is destroyed"; got != want {
		t.Errorf("a run cancelled: %s, want %s", got, want)
	}
	incomplete := passedRun()
	incomplete.res.Outcome = OutcomeStageError
	incomplete.res.Stages[2].Verdict = VerdictError
	incomplete.res.Stages[2].Wait = wait(wire.WaitIncomplete, 120, 40)
	b = Build(incomplete.in, incomplete.res)
	if got, want := StageLines(b)[3],
		"stage change-1/head: unchanged in 0.9s; incomplete after 120.0s (40 reads); 19 held, 0 failed, 0 skipped; error: its wait ended incomplete after 120.0s"; got != want {
		t.Errorf("a wait incomplete: %s, want %s", got, want)
	}
}

// The block marshals with every list and nullable key the contract requires, its stage
// findings in the document's list once each.
func TestFindingsAreTheStagesInOrder(t *testing.T) {
	b := Build(failedRun().in, failedRun().res)
	var n int
	for _, s := range b.Stages {
		n += len(s.Findings)
	}
	l := Findings(b)
	if len(l) != n || l[0].Rule != findings.RuleContractNodeMissing {
		t.Errorf("Findings = %v", l)
	}
	raw, err := json.Marshal(b)
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{`"reclaimed":null`, `"new_findings":[]`, `"provision":null`} {
		if !bytes.Contains(raw, []byte(want)) {
			t.Errorf("the block does not write %s: %s", want, raw)
		}
	}
}
