package cli

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"os"
	"regexp"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
	"github.com/happypathnetworking/fylgja/internal/rehearsal"
	snap "github.com/happypathnetworking/fylgja/internal/snapshot"
)

// US1's acceptance scenarios through the harness (015, T028–T029): `twin rehearse
// --branch` over 014's fake Infrahub and the fake workflow service, one test per scenario.
//
// The proposed change rehearsed is pc-1 on change-1, a draft, as stage plan's tests serve
// it: change-1 holds the fixture less its last link from planLinkless and the whole fixture
// from planLinked. seeded is marked with no as_of before the link (written), third-link with
// an as_of after it (given), so the step into third-link adds the link and the step from it
// to the head changes nothing; main holds no network, as the development host's does, so
// the branch point is refused scope.empty and passed over.
const (
	rehearseRun = "r1"
	seededRef   = lessLink + "/seeded"
	thirdRef    = lessLink + "/third-link"
	headRef     = lessLink + "/head"
	pointRef    = lessLink + "/branch-point"
)

func rehearseMarks() []fakeStage {
	return []fakeStage{
		mark("st-third-link", "third-link", planLiveAt, "third link"),
		{ID: "st-seeded", Label: "seeded", WrittenAt: cabledAt, Description: "after the link is cabled"},
	}
}

// rehearseInfrahub serves pc-1 with seeded and third-link over an empty main, started.
func rehearseInfrahub(t *testing.T) *fakeInfrahub {
	t.Helper()
	f := planInfrahub(t, rehearseMarks()...)
	versioned(t, f)
	emptyMain(f)
	f.start()
	return f
}

// rehearseHost is the host a rehearsal finds empty: a fresh state root, the probe login
// set, and containerlab holding no lab. It returns the fake containerlab, whose calls say
// whether the host was read.
func rehearseHost(t *testing.T) *fakeClab {
	t.Helper()
	useStateRoot(t)
	dryRunEnv(t)
	return useClab(t, "inspect-empty.json")
}

// useRehearsalCeiling lowers the server's ceiling for the test's length.
func useRehearsalCeiling(t *testing.T, d time.Duration) {
	t.Helper()
	saved := rehearsalCeiling
	t.Cleanup(func() { rehearsalCeiling = saved })
	rehearsalCeiling = d
}

// rehearseEvents are a rehearsal's progress as provision.Client.Follow reports it: its own
// steps, each child announced by its notice, and each child's events, Of the rehearsal. The
// baseline is built and settles, each stage in rehearsed is stepped to, and the destroy runs.
func rehearseEvents(rehearsed ...string) []provision.Event {
	own := func(step string, end bool, detail string) provision.Event {
		e := provision.Event{WorkflowID: provision.WorkflowRehearse, Step: step, End: end, Detail: detail}
		if end {
			e.Outcome = provision.EventDone
		}
		return e
	}
	child := func(workflowID, step, findingStep string, d time.Duration) provision.Event {
		return provision.Event{WorkflowID: workflowID, Step: step, FindingStep: findingStep, End: true, Outcome: provision.EventDone,
			Duration: d, Of: provision.WorkflowRehearse}
	}
	events := []provision.Event{
		own("provision", false, ""),
		{Notice: "run fylgja-provision p1"},
		child(provision.WorkflowProvision, "deploy", findings.StepDeploy, 41200*time.Millisecond),
		child(provision.WorkflowProvision, "record", findings.StepRecord, 100*time.Millisecond),
		own("provision", true, ""),
		own("observe", false, ""),
		own("observe", true, "settled after 3.2s (2 reads)"),
	}
	for i := range rehearsed {
		events = append(events,
			own("step", false, ""),
			provision.Event{Notice: "run fylgja-step s" + string(rune('1'+i))},
			child(provision.WorkflowStep, "push n1", findings.StepPush, 2500*time.Millisecond),
			own("step", true, ""))
	}
	return append(events,
		own("destroy", false, ""),
		provision.Event{Notice: "run fylgja-destroy d1"},
		child(provision.WorkflowDestroy, "teardown", findings.StepTeardown, 5200*time.Millisecond),
		own("destroy", true, ""))
}

// counts are a read's counts with held assertions and failed ones, as the fixture's three
// nodes give them.
func counts(held, failed int) *wire.VerifyCounts {
	zero := 0
	return &wire.VerifyCounts{
		HostName:    findings.VerifyCount{Held: 3, Unread: &zero},
		PortEnabled: findings.VerifyCount{Held: held - 3 - 4, Failed: failed, Skipped: &zero, Unread: &zero},
		Neighbor:    findings.VerifyCount{Held: 4, Unread: &zero},
		Record:      findings.VerifyCount{Held: 1},
	}
}

// settledAfter is a wait that settled, holding failing.
func settledAfter(afterS float64, reads int, failing ...wire.StepFinding) *wire.StepWait {
	if failing == nil {
		failing = []wire.StepFinding{}
	}
	return &wire.StepWait{Outcome: wire.WaitSettled, BudgetS: 120, Reads: reads, AfterS: afterS, Failing: failing}
}

// rehearsedRun is a run of pc-1 to its destroy: the branch point passed over, the baseline
// built and settled with baselineFailing, then each stage in steps, the destroy clean.
func rehearsedRun(outcome string, baselineFailing []wire.StepFinding, steps ...provision.RehearsedStage) provision.RehearseResult {
	res := provision.RehearseResult{Outcome: outcome, UsedS: 118.4, Findings: findings.List{},
		StartedAt: "2026-10-19T10:00:05Z", EndedAt: "2026-10-19T10:02:03Z",
		Destroy: &provision.DestroyResult{Cleanup: provision.CleanupResult{Teardown: provision.CleanupDone, Unstage: provision.CleanupDone,
			Removed: []string{"lab fylgja (3 containers)", "twin directory /srv/twin"}}, Findings: findings.List{}},
		Stages: []provision.RehearsedStage{
			{Ref: pointRef, Verdict: rehearsal.VerdictRefused},
			{Ref: seededRef, Verdict: rehearsal.VerdictBaseline, Run: &wire.RunRef{WorkflowID: provision.WorkflowProvision, RunID: "p1"},
				Provision: &provision.ProvisionResult{Outcome: provision.OutcomeReady, Findings: findings.List{}},
				Wait:      settledAfter(3.2, 2, baselineFailing...), Counts: counts(15, len(baselineFailing)), TookS: 70},
		}}
	res.Stages = append(res.Stages, steps...)
	res.Reached = res.Stages[len(res.Stages)-1].Ref
	return res
}

// stepped is a rehearsed stage whose step child, run sN, ended outcome, pushing n1, then
// waited as wait says.
func stepped(ref, runID, outcome string, wait *wire.StepWait, verdict rehearsal.Verdict) provision.RehearsedStage {
	took := 2.5
	s := provision.RehearsedStage{Ref: ref, Verdict: verdict, Run: &wire.RunRef{WorkflowID: provision.WorkflowStep, RunID: runID},
		Step: &provision.StepResult{Outcome: outcome, Findings: findings.List{}, Timings: wire.StepTimings{WholeS: 4.5},
			PushPlan: []wire.StepPush{{Node: "n1", Reasons: []string{"artifact"}, Outcome: wire.PushLanded, TookS: &took}}},
		Wait: wait, TookS: 12}
	if wait != nil {
		s.Counts = counts(19, len(wait.Failing))
	}
	return s
}

// rehearse runs `fylgja twin rehearse <args>` through the command line, as an operator
// would, and returns its exit status and what it wrote on stdout and stderr.
func rehearse(t *testing.T, args ...string) (code int, stdout, stderr string) {
	t.Helper()
	return runRoot(t, append([]string{"twin", "rehearse"}, args...)...)
}

// rehearseDoc is rehearse under --json: the one findings document on stdout, which must
// satisfy the newest contracts, the rehearsal block's among them, and nothing on stderr.
func rehearseDoc(t *testing.T, args ...string) (int, *findings.Document, string) {
	t.Helper()
	code, stdout, stderr := rehearse(t, append(args, "--json")...)
	if stderr != "" {
		t.Errorf("%v --json wrote on stderr: %s", args, stderr)
	}
	var doc findings.Document
	if err := json.Unmarshal([]byte(stdout), &doc); err != nil {
		t.Fatalf("%v: stdout is not one findings document: %v\n%s", args, err, stdout)
	}
	validateM10Document(t, &doc)
	return code, &doc, stdout
}

// rehearsalStages are the block's stages as "ref role verdict", in order.
func rehearsalStages(doc *findings.Document) []string {
	if doc.Rehearsal == nil {
		return nil
	}
	var out []string
	for _, s := range doc.Rehearsal.Stages {
		out = append(out, s.Ref+" "+s.Role+" "+s.Verdict)
	}
	return out
}

// findingOf is the document's one finding under rule; it fails the test unless there is
// exactly one.
func findingOf(t *testing.T, doc *findings.Document, rule string) findings.Finding {
	t.Helper()
	var found []findings.Finding
	for _, f := range doc.Findings {
		if f.Rule == rule {
			found = append(found, f)
		}
	}
	if len(found) != 1 {
		t.Fatalf("the document carries %d findings under %s, want one: %+v", len(found), rule, doc.Findings)
	}
	return found[0]
}

// startedNothing fails when the rehearsal reached the host or the workflow service: no
// containerlab or docker call, and, where svc is given, no start.
func startedNothing(t *testing.T, label string, clab *fakeClab, svc *fakeService) {
	t.Helper()
	if len(clab.calls) != 0 {
		t.Errorf("%s: the host was read: %v", label, clab.calls)
	}
	if svc == nil {
		return
	}
	svc.mu.Lock()
	defer svc.mu.Unlock()
	if len(svc.calls) != 0 || len(svc.rehearsed) != 0 {
		t.Errorf("%s: the service was asked %v; want nothing started", label, svc.calls)
	}
}

// okRun is scenario 1's service: every rehearsed stage passes.
func okRun() *fakeService {
	settled := settledAfter(6.1, 4)
	return &fakeService{rehearseRun: rehearseRun, rehearseEvents: rehearseEvents(thirdRef, headRef),
		rehearseResult: rehearsedRun(rehearsal.OutcomeOK, nil,
			stepped(thirdRef, "s1", provision.StepStepped, settled, rehearsal.VerdictPassed),
			stepped(headRef, "s2", provision.StepUnchanged, settled, rehearsal.VerdictPassed))}
}

// Scenario 1. On the development host's main, which holds no network, the branch point is
// refused scope.empty and passed over, seeded is the baseline, and third-link and
// the head are stepped to with restarts allowed and the default wait: every one passes,
// exit 0. On a main that carries the network, as the spec's scenario has it, the branch
// point is the baseline and the three stages after it are rehearsed.
func TestRehearseEveryStagePasses(t *testing.T) {
	t.Run("an empty main", func(t *testing.T) {
		rehearseHost(t)
		f := rehearseInfrahub(t)
		svc := okRun()
		useService(t, svc)
		useInterrupts(t)

		code, stdout, stderr := rehearse(t, "--branch", lessLink)
		if code != findings.ExitOK {
			t.Fatalf("exit %d, want 0:\n%s%s", code, stdout, stderr)
		}
		if len(svc.rehearsed) != 1 {
			t.Fatalf("%d rehearsals started, want one", len(svc.rehearsed))
		}
		in := svc.rehearsed[0]
		if in.ProposedChange != (findings.StageChange{ID: "pc-1", Name: "change pc-1", Branch: lessLink, Draft: true}) ||
			in.DeadlineS != 1950 || in.CeilingS != 3600 || in.Version != version || in.ResolvedAt == "" {
			t.Errorf("the run's input %+v; want pc-1, a 1950s deadline under the 3600s ceiling, this build", in)
		}
		var roles []string
		for _, s := range in.Stages {
			roles = append(roles, s.Ref+" "+s.Role)
		}
		if want := []string{pointRef + " refused", seededRef + " baseline", thirdRef + " rehearsed", headRef + " rehearsed"}; !slices.Equal(roles, want) {
			t.Fatalf("the run's stages %v, want %v", roles, want)
		}
		point, seeded := in.Stages[0], in.Stages[1]
		if point.Refused == nil || point.Refused.Rule != findings.RuleScopeEmpty || point.Provision != nil || point.Step != nil ||
			point.BundleID != "" || point.SnapshotID != "" {
			t.Errorf("the branch point %+v; want it passed over, refused %s, with no child", point, findings.RuleScopeEmpty)
		}
		// Each compiled stage names its snapshot, taken in the plan before any boot: the
		// baseline's provision, and each step's two sides (018; R-13).
		for _, s := range in.Stages[1:] {
			if !snap.IsID(s.SnapshotID) {
				t.Errorf("%s names snapshot %q; want the one its read was taken as", s.Ref, s.SnapshotID)
			}
		}
		if p := seeded.Provision; p == nil || p.SnapshotID != seeded.SnapshotID {
			t.Errorf("the baseline's provision %+v; want it to name snapshot %s", p, seeded.SnapshotID)
		}
		for i := 2; i < len(in.Stages); i++ {
			s, prev := in.Stages[i], in.Stages[i-1]
			if st := s.Step; st == nil || st.From.SnapshotID != prev.SnapshotID || st.To.SnapshotID != s.SnapshotID {
				t.Errorf("%s's step %+v; want its sides to name %s and %s", s.Ref, st, prev.SnapshotID, s.SnapshotID)
			}
		}
		// Already compiled, as a rebuild's child is: from intent, with the bundle set.
		if p := seeded.Provision; p == nil || p.Source != wire.SourceIntent || p.Branch != lessLink || p.At != cabledAt ||
			p.BundleID != seeded.BundleID || p.BundleID == "" || p.BundlePath != seeded.BundlePath || p.Stage == nil ||
			p.Stage.Label != "seeded" || p.Rehearsal != nil || seeded.Step != nil || seeded.WaitS != 120 {
			t.Errorf("the baseline %+v (provision %+v); want seeded at %s provisioned from its compiled bundle, a 120s wait", seeded, p, cabledAt)
		}
		for i, unchanged := range map[int]bool{2: false, 3: true} {
			s, prev := in.Stages[i], in.Stages[i-1]
			if st := s.Step; st == nil || !st.AllowRestart || st.WaitS != 120 || s.WaitS != 120 || st.From.BundleID != prev.BundleID ||
				st.To.BundleID != s.BundleID || st.ToBundlePath != s.BundlePath || st.Unchanged != unchanged || s.Provision != nil {
				t.Errorf("%s %+v (step %+v); want a step from %s with restarts allowed, the 120s wait, unchanged %v",
					s.Ref, s, st, prev.Ref, unchanged)
			}
		}
		for _, want := range []string{
			"stage " + pointRef + ": refused (scope.empty)\n",
			"stage " + seededRef + ": created; settled after 3.2s (2 reads); 15 held, 0 failed, 0 skipped; baseline\n",
			"stage " + thirdRef + ": stepped in 4.5s (push n1 2.5s); settled after 6.1s (4 reads); 19 held, 0 failed, 0 skipped; passed\n",
			"stage " + headRef + ": unchanged in 4.5s; settled after 6.1s (4 reads); 19 held, 0 failed, 0 skipped; passed\n",
			"rehearsal ok: 3 stages rehearsed, every one passed; the twin is destroyed; 118.4s of the 1950s deadline\n",
		} {
			if !strings.Contains(stdout, want) {
				t.Errorf("the text lacks %q:\n%s", want, stdout)
			}
		}
		if svc.calls[0] != "StartRehearse" || len(svc.calls) != 1 || !slices.Contains(svc.reads, "InFlight") {
			t.Errorf("the service was asked %v and read %v; want the runs in flight read, then the one start", svc.calls, svc.reads)
		}
		mustQuoteNoContent(t, f, stdout, stderr)
	})

	t.Run("main carries the network", func(t *testing.T) {
		rehearseHost(t)
		f := planInfrahub(t, rehearseMarks()...)
		versioned(t, f)
		f.start()
		settled := settledAfter(6.1, 4)
		res := rehearsedRun(rehearsal.OutcomeOK, nil,
			stepped(seededRef, "s1", provision.StepStepped, settled, rehearsal.VerdictPassed),
			stepped(thirdRef, "s2", provision.StepStepped, settled, rehearsal.VerdictPassed),
			stepped(headRef, "s3", provision.StepUnchanged, settled, rehearsal.VerdictPassed))
		res.Stages = slices.Delete(res.Stages, 1, 2)
		res.Stages[0] = provision.RehearsedStage{Ref: pointRef, Verdict: rehearsal.VerdictBaseline,
			Run:       &wire.RunRef{WorkflowID: provision.WorkflowProvision, RunID: "p1"},
			Provision: &provision.ProvisionResult{Outcome: provision.OutcomeReady, Findings: findings.List{}},
			Wait:      settledAfter(3.2, 2), Counts: counts(15, 0), TookS: 70}
		svc := &fakeService{rehearseRun: rehearseRun, rehearseEvents: rehearseEvents(seededRef, thirdRef, headRef), rehearseResult: res}
		useService(t, svc)
		useInterrupts(t)

		code, doc, raw := rehearseDoc(t, "--branch", lessLink)
		if code != findings.ExitOK || doc.Status != findings.StatusOK || len(doc.Findings) != 0 {
			t.Fatalf("exit %d, status %s, findings %v; want 0, ok and none\n%s", code, doc.Status, rulesOf(doc.Findings), raw)
		}
		in := svc.rehearsed[0]
		var roles []string
		for _, s := range in.Stages {
			roles = append(roles, s.Role)
		}
		if !slices.Equal(roles, []string{"baseline", "rehearsed", "rehearsed", "rehearsed"}) || in.DeadlineS != 2580 ||
			in.Stages[0].Provision == nil || in.Stages[0].Branch != "main" || in.Stages[0].At != fakeBranchedFrom {
			t.Errorf("roles %v, deadline %ds, the branch point %+v; want it the baseline, three stages rehearsed, 2580s",
				roles, in.DeadlineS, in.Stages[0])
		}
		if want := []string{pointRef + " baseline baseline", seededRef + " rehearsed passed", thirdRef + " rehearsed passed",
			headRef + " rehearsed passed"}; !slices.Equal(rehearsalStages(doc), want) {
			t.Errorf("the report's stages %v, want %v", rehearsalStages(doc), want)
		}
		// The report names the snapshot each stage was rehearsed from, the one the run's
		// input named, beside its bundle.
		for i, s := range doc.Rehearsal.Stages {
			if s.SnapshotID == nil || *s.SnapshotID != in.Stages[i].SnapshotID || !snap.IsID(*s.SnapshotID) {
				t.Errorf("the report's %s names snapshot %v; want %s", s.Ref, s.SnapshotID, in.Stages[i].SnapshotID)
			}
		}
		mustQuoteNoContent(t, f, raw)
	})
}

// Scenario 2: the step into third-link diverges at its push, n3 landed and n1 refused. The
// stage fails naming the phase and the nodes, the head is not reached and never stepped to,
// the twin is destroyed, the commands that reproduce the failure are printed, exit 5.
func TestRehearseStopsAtADivergedStage(t *testing.T) {
	rehearseHost(t)
	f := rehearseInfrahub(t)
	took := 2.6
	diverged := stepped(thirdRef, "s1", provision.StepDiverged, settledAfter(6.1, 4), rehearsal.VerdictFailed)
	diverged.Step.Phase, diverged.Step.Step = findings.StepPush, findings.StepPush
	diverged.Step.PushPlan = []wire.StepPush{
		{Node: "n1", Reasons: []string{"artifact"}, Outcome: wire.PushRefused, Rule: findings.RulePushRefused},
		{Node: "n3", Reasons: []string{"artifact"}, Outcome: wire.PushLanded, TookS: &took}}
	newSvc := func() *fakeService {
		return &fakeService{rehearseRun: rehearseRun, rehearseEvents: rehearseEvents(thirdRef),
			rehearseResult: rehearsedRun(rehearsal.OutcomeStageFailed, nil, diverged,
				provision.RehearsedStage{Ref: headRef, Verdict: rehearsal.VerdictNotReached})}
	}
	useService(t, newSvc())
	useInterrupts(t)

	code, stdout, stderr := rehearse(t, "--branch", lessLink)
	if code != findings.ExitNonconforming {
		t.Errorf("exit %d, want 5:\n%s%s", code, stdout, stderr)
	}
	for _, want := range []string{
		"stage " + thirdRef + ": diverged at phase push: landed n3; not landed n1 (push.refused); settled after 6.1s (4 reads); " +
			"19 held, 0 failed, 0 skipped; failed\n",
		"stage " + headRef + ": not reached\n",
		"rehearsal nonconforming: stage " + thirdRef + " failed at phase push; the twin is destroyed; reproduce it by hand:\n" +
			"  fylgja twin create --stage " + seededRef + " --scope " + defaultScope + "\n" +
			"  fylgja twin step --stage " + thirdRef + " --allow-restart\n" +
			"  fylgja twin verify\n" +
			"  fylgja twin destroy\n",
	} {
		if !strings.Contains(stdout, want) {
			t.Errorf("the text lacks %q:\n%s", want, stdout)
		}
	}
	if strings.Contains(stdout, "stage "+headRef+": stepping") {
		t.Errorf("the head was stepped to:\n%s", stdout)
	}

	useService(t, newSvc())
	code, doc, raw := rehearseDoc(t, "--branch", lessLink)
	failed := findingOf(t, doc, findings.RuleRehearsalStageFailed)
	if code != findings.ExitNonconforming || doc.Status != findings.StatusNonconforming || failed.Object != thirdRef ||
		failed.Step != findings.StepPush || !strings.Contains(failed.Message, "landed n3; not landed n1 (push.refused)") {
		t.Errorf("exit %d, status %s, %+v; want 5, nonconforming, the stage failed at push naming n1 and n3", code, doc.Status, failed)
	}
	if want := []string{pointRef + " refused refused", seededRef + " baseline baseline", thirdRef + " rehearsed failed",
		headRef + " not_reached not_reached"}; !slices.Equal(rehearsalStages(doc), want) {
		t.Errorf("the report's stages %v, want %v", rehearsalStages(doc), want)
	}
	// Given no --scope, the create names the server's default, which the stages were read
	// under, since the server that reproduces it may hold another (017).
	if want := []string{"fylgja twin create --stage " + seededRef + " --scope " + defaultScope,
		"fylgja twin step --stage " + thirdRef + " --allow-restart",
		"fylgja twin verify", "fylgja twin destroy"}; !slices.Equal(doc.Rehearsal.Reproduce, want) {
		t.Errorf("reproduce %v, want %v", doc.Rehearsal.Reproduce, want)
	}
	mustQuoteNoContent(t, f, stdout, stderr, raw)
}

// US5/AC5 under a scope given (017; FR-017): a rehearsal read under --scope tag:other,
// over devices tagged other alone, that fails a stage reproduces it from a create naming
// tag:other, never the server's default, so the commands read the devices the rehearsal
// read; the steps after it take the record's scope and name none.
func TestRehearseReproducesUnderTheScopeItReadUnder(t *testing.T) {
	const scope = "tag:other"
	rehearseHost(t)
	f := planInfrahub(t, rehearseMarks()...)
	versioned(t, f)
	emptyMain(f)
	f.tag = "other"
	f.start()
	diverged := stepped(thirdRef, "s1", provision.StepDiverged, settledAfter(6.1, 4), rehearsal.VerdictFailed)
	diverged.Step.Phase = findings.StepPush
	diverged.Step.PushPlan = []wire.StepPush{{Node: "n1", Reasons: []string{"artifact"}, Outcome: wire.PushRefused, Rule: findings.RulePushRefused}}
	useService(t, &fakeService{rehearseRun: rehearseRun, rehearseEvents: rehearseEvents(thirdRef),
		rehearseResult: rehearsedRun(rehearsal.OutcomeStageFailed, nil, diverged,
			provision.RehearsedStage{Ref: headRef, Verdict: rehearsal.VerdictNotReached})})
	useInterrupts(t)

	code, doc, raw := rehearseDoc(t, "--branch", lessLink, "--scope", scope)
	if code != findings.ExitNonconforming || doc.Subject == nil || doc.Subject.Scope != scope {
		t.Fatalf("exit %d, subject %+v, findings %v; want 5 under %s\n%s", code, doc.Subject, rulesOf(doc.Findings), scope, raw)
	}
	if want := []string{"fylgja twin create --stage " + seededRef + " --scope " + scope,
		"fylgja twin step --stage " + thirdRef + " --allow-restart",
		"fylgja twin verify", "fylgja twin destroy"}; !slices.Equal(doc.Rehearsal.Reproduce, want) {
		t.Errorf("reproduce %v, want %v", doc.Rehearsal.Reproduce, want)
	}
	mustQuoteNoContent(t, f, raw)
}

// Scenario 3: the step into third-link lands, and its wait holds a finding the baseline's
// did not. The stage fails naming it, the head is not reached, exit 5; the finding is a
// warning under the stage, and the failure is rehearsal.stage.failed at observe.
func TestRehearseNewFindingFails(t *testing.T) {
	rehearseHost(t)
	rehearseInfrahub(t)
	neighbor := wire.StepFinding{Rule: findings.RuleVerifyNeighbor, Object: "n1:ethernet-1/3",
		Message: "n1:ethernet-1/3 sees no neighbor; the intent says n3:ethernet-1/3"}
	failing := stepped(thirdRef, "s1", provision.StepStepped, settledAfter(6.1, 4, neighbor), rehearsal.VerdictFailed)
	failing.NewFindings = []wire.StepFinding{neighbor}
	newSvc := func() *fakeService {
		return &fakeService{rehearseRun: rehearseRun, rehearseEvents: rehearseEvents(thirdRef),
			rehearseResult: rehearsedRun(rehearsal.OutcomeStageFailed, nil, failing,
				provision.RehearsedStage{Ref: headRef, Verdict: rehearsal.VerdictNotReached})}
	}
	useService(t, newSvc())
	useInterrupts(t)

	code, stdout, _ := rehearse(t, "--branch", lessLink)
	if code != findings.ExitNonconforming ||
		!strings.Contains(stdout, "stage "+thirdRef+": stepped in 4.5s (push n1 2.5s); settled after 6.1s (4 reads); 19 held, 1 failed, "+
			"0 skipped; failed: verify.neighbor n1:ethernet-1/3\n") ||
		!strings.Contains(stdout, "rehearsal nonconforming: stage "+thirdRef+" failed: verify.neighbor n1:ethernet-1/3; the twin is destroyed") {
		t.Errorf("exit %d, want 5, the stage failed naming the finding:\n%s", code, stdout)
	}

	useService(t, newSvc())
	code, doc, _ := rehearseDoc(t, "--branch", lessLink)
	failed := findingOf(t, doc, findings.RuleRehearsalStageFailed)
	warned := findingOf(t, doc, findings.RuleVerifyNeighbor)
	if code != findings.ExitNonconforming || failed.Step != findings.StepObserve || failed.Object != thirdRef ||
		!strings.Contains(failed.Message, "verify.neighbor n1:ethernet-1/3") {
		t.Errorf("exit %d, %+v; want 5 and the stage failed at observe naming the finding", code, failed)
	}
	if warned.Severity != findings.Warning || warned.Object != thirdRef+": n1:ethernet-1/3" {
		t.Errorf("the verify finding %+v; want a warning, its object prefixed by the stage", warned)
	}
	if st := doc.Rehearsal.Stages[2]; len(st.NewFindings) != 1 || st.NewFindings[0].Rule != findings.RuleVerifyNeighbor {
		t.Errorf("third-link's new findings %+v, want the neighbor", st.NewFindings)
	}
}

// Scenario 4: the baseline's wait holds a finding, and each later stage's holds that one and
// no other. Every stage passes and the rehearsal exits 0; the finding is reported as the
// baseline's, and as a warning under each stage whose wait held it.
func TestRehearseBaselineFindingsFailNothing(t *testing.T) {
	rehearseHost(t)
	rehearseInfrahub(t)
	port := wire.StepFinding{Rule: findings.RuleVerifyPortEnabled, Object: "n2:ethernet-1/2",
		Message: "n2:ethernet-1/2 is down; the intent says it is enabled"}
	held := settledAfter(6.1, 4, port)
	newSvc := func() *fakeService {
		return &fakeService{rehearseRun: rehearseRun, rehearseEvents: rehearseEvents(thirdRef, headRef),
			rehearseResult: rehearsedRun(rehearsal.OutcomeOK, []wire.StepFinding{port},
				stepped(thirdRef, "s1", provision.StepStepped, held, rehearsal.VerdictPassed),
				stepped(headRef, "s2", provision.StepUnchanged, held, rehearsal.VerdictPassed))}
	}
	useService(t, newSvc())
	useInterrupts(t)

	code, stdout, _ := rehearse(t, "--branch", lessLink)
	if code != findings.ExitOK || !strings.Contains(stdout, "rehearsal ok: 3 stages rehearsed, every one passed") {
		t.Errorf("exit %d, want 0 and every stage passed:\n%s", code, stdout)
	}

	useService(t, newSvc())
	code, doc, _ := rehearseDoc(t, "--branch", lessLink)
	b := doc.Rehearsal.Baseline
	if code != findings.ExitOK || doc.Status != findings.StatusOK || b == nil || b.Ref != seededRef || len(b.Findings) != 1 ||
		b.Findings[0].Rule != findings.RuleVerifyPortEnabled || b.Findings[0].Object != "n2:ethernet-1/2" {
		t.Fatalf("exit %d, status %s, baseline %+v; want 0, ok, and the finding the baseline's", code, doc.Status, b)
	}
	var objects []string
	for _, f := range doc.Findings {
		if f.Rule == findings.RuleVerifyPortEnabled {
			if f.Severity != findings.Warning {
				t.Errorf("%+v; a verify finding is a warning", f)
			}
			objects = append(objects, f.Object)
		}
	}
	if want := []string{seededRef + ": n2:ethernet-1/2", thirdRef + ": n2:ethernet-1/2", headRef + ": n2:ethernet-1/2"}; !slices.Equal(objects, want) {
		t.Errorf("the finding is reported under %v, want %v", objects, want)
	}
	for _, s := range doc.Rehearsal.Stages[2:] {
		if len(s.NewFindings) != 0 || s.Verdict != string(rehearsal.VerdictPassed) {
			t.Errorf("%s: %s with new findings %+v; want passed with none", s.Ref, s.Verdict, s.NewFindings)
		}
	}
}

// staleInfrahub serves pc-1 with seeded, third-link and edited, a mark made after n1 and n2
// were edited and before their artifacts were regenerated, which is stale, as 014's
// scenario 3 makes it; main empty or carrying the network as emptied says.
func staleInfrahub(t *testing.T, emptied bool) *fakeInfrahub {
	t.Helper()
	f := planInfrahub(t, append(rehearseMarks(), mark("st-edited", "edited", "2026-10-16T09:40:00.000000+00:00", "before the checks"))...)
	f.stamps = map[string]fakeDeviceStamps{
		lessLink + "/n1": {Intent: "2026-10-16T09:30:00.000000+00:00", Artifact: fakeWritten},
		lessLink + "/n2": {Intent: "2026-10-16T09:30:00.000000+00:00", Artifact: fakeWritten},
	}
	if emptied {
		emptyMain(f)
	}
	f.start()
	return f
}

// Scenario 5: a stale mark refuses the rehearsal with 014's finding, naming the devices,
// before the host is read or the workflow service dialled, exit 1; and a branch with no
// open proposed change is stage.unknown.
func TestRehearseRefusedBeforeAnyBoot(t *testing.T) {
	t.Run("a stale mark", func(t *testing.T) {
		clab := rehearseHost(t)
		staleInfrahub(t, false)
		useService(t, nil)

		code, doc, raw := rehearseDoc(t, "--branch", lessLink)
		var stale []string
		for _, f := range doc.Findings {
			if f.Rule == findings.RuleStageArtifactStale {
				stale = append(stale, f.Object)
			}
		}
		if code != findings.ExitRejected || doc.Status != findings.StatusRejected || !slices.Contains(stale, "n1") ||
			!slices.Contains(stale, "n2") || slices.Contains(stale, "n3") {
			t.Errorf("exit %d, status %s, stale %v; want 1, rejected, stale for n1 and n2\n%s", code, doc.Status, stale, raw)
		}
		if doc.Rehearsal == nil || doc.Rehearsal.Run != nil {
			t.Errorf("the block %+v; want the stages named and no run", doc.Rehearsal)
		}
		for _, s := range doc.Rehearsal.Stages {
			if s.Verdict != string(rehearsal.VerdictNotReached) && s.Verdict != string(rehearsal.VerdictRefused) {
				t.Errorf("%s reads %s; nothing was rehearsed", s.Ref, s.Verdict)
			}
		}
		startedNothing(t, "a stale mark", clab, nil)
	})

	t.Run("no open proposed change", func(t *testing.T) {
		clab := rehearseHost(t)
		rehearseInfrahub(t)
		useService(t, nil)

		code, doc, raw := rehearseDoc(t, "--branch", "nowhere")
		unknown := findingOf(t, doc, findings.RuleStageUnknown)
		if code != findings.ExitRejected || doc.Status != findings.StatusRejected || doc.Rehearsal != nil || unknown.Object != "nowhere" {
			t.Errorf("exit %d, status %s, %+v; want 1, rejected, stage.unknown naming the branch\n%s", code, doc.Status, unknown, raw)
		}
		startedNothing(t, "no proposed change", clab, nil)
	})
}

// US5 scenario 3 (018): every stage's snapshot is taken in the plan, before the first boot.
// On a main that carries the network, the branch point and seeded compile, each its snapshot
// filed, and third-link reads a branch holding no device from its at on, refused scope.empty
// at its read, as is the head after it: the rehearsal is refused before the host is read or
// the workflow service asked to start anything, exit 1, the two snapshots filed and named in
// the report, the refused stages naming none.
func TestRehearseFilesEachStagesSnapshotBeforeAnyBoot(t *testing.T) {
	clab := rehearseHost(t)
	paths := lab.PathsAt(os.Getenv(lab.EnvStateRoot))
	f := planInfrahub(t, rehearseMarks()...)
	versioned(t, f)
	f.versions[lessLink] = append(f.versions[lessLink], fakeVersion{Since: planLiveAt, CTM: &ctm.CTM{}})
	f.start()
	svc := &fakeService{readOnly: t}
	useService(t, svc)

	code, doc, raw := rehearseDoc(t, "--branch", lessLink)
	if code != findings.ExitRejected || doc.Status != findings.StatusRejected || doc.Rehearsal == nil || doc.Rehearsal.Run != nil {
		t.Fatalf("exit %d, status %s; want 1, rejected, the stages named and no run\n%s", code, doc.Status, raw)
	}
	third := doc.Rehearsal.Stages[2]
	if third.Ref != thirdRef || len(third.Findings) == 0 || !carriesRule(third.Findings, findings.RuleScopeEmpty) {
		t.Errorf("%s's findings %v; want it refused %s at its read", third.Ref, rulesOf(third.Findings), findings.RuleScopeEmpty)
	}
	var named, files []string
	for _, s := range doc.Rehearsal.Stages {
		if s.SnapshotID != nil {
			named = append(named, s.Ref)
			files = append(files, *s.SnapshotID+".json")
		}
	}
	if want := []string{pointRef, seededRef}; !slices.Equal(named, want) {
		t.Errorf("the report names the snapshots of %v; want the two stages that compiled, %v\n%s", named, want, raw)
	}
	if got := filedSnapshots(t, paths); !slices.Equal(got, sortedCopy(files...)) {
		t.Errorf("snapshots/ holds %v; want the two stages' %v, taken before any boot", got, files)
	}
	startedNothing(t, "a stage refused at its read", clab, svc)
}

// Scenario 6: on a main that holds no network the branch point's row reads refused, as the
// plan prints it, and the rest is rehearsed (scenario 1's first case); a stale mark among
// the stages still refuses the whole, the branch point's refusal beside it.
func TestRehearseRefusedBranchPointAndAStaleMark(t *testing.T) {
	clab := rehearseHost(t)
	staleInfrahub(t, true)
	useService(t, nil)

	code, stdout, _ := rehearse(t, "--branch", lessLink)
	for _, want := range []string{
		pointRef + ": refused (scope.empty)\n",
		lessLink + "/edited: refused (stage.artifact.stale)\n",
	} {
		if !strings.Contains(stdout, want) {
			t.Errorf("the plan lacks %q:\n%s", want, stdout)
		}
	}
	if code != findings.ExitRejected || strings.Contains(stdout, "run "+provision.WorkflowRehearse) {
		t.Errorf("exit %d, want 1 and no run:\n%s", code, stdout)
	}

	code, doc, _ := rehearseDoc(t, "--branch", lessLink)
	if code != findings.ExitRejected || !carriesRule(doc.Findings, findings.RuleScopeEmpty) ||
		!carriesRule(doc.Findings, findings.RuleStageArtifactStale) || doc.Rehearsal.Stages[0].Verdict != string(rehearsal.VerdictRefused) {
		t.Errorf("exit %d, findings %v, stages %v; want 1, the branch point's refusal and the stale mark's",
			code, rulesOf(doc.Findings), rehearsalStages(doc))
	}
	startedNothing(t, "a stale mark", clab, nil)
}

// Scenario 7: the operator's interrupt from the start, while third-link's step runs, asks
// the run to cancel and waits for its destroy; the run closes cancelled, and the rehearsal
// ends run.cancelled at the step its children reached, naming the stage, exit 2. The cut
// step's line keeps its phase and names the push that landed (T094).
func TestRehearseInterruptCancelsTheRun(t *testing.T) {
	rehearseHost(t)
	rehearseInfrahub(t)
	interrupts := useInterrupts(t)
	cancelledStep := stepped(thirdRef, "s1", provision.OutcomeCancelled, nil, rehearsal.VerdictError)
	cancelledStep.Step.Phase, cancelledStep.Step.Step = findings.StepPush, findings.StepPush
	res := rehearsedRun(rehearsal.OutcomeCancelled, nil, cancelledStep,
		provision.RehearsedStage{Ref: headRef, Verdict: rehearsal.VerdictNotReached})
	res.Reached = thirdRef
	events := rehearseEvents(thirdRef)
	events = events[:len(events)-5] // up to the step's push; its close and the destroy follow the cancel
	release := make(chan struct{})
	svc := &fakeService{rehearseRun: rehearseRun, rehearseEvents: events, rehearseResult: res, release: release}
	svc.onCancel = func() { close(release) }
	svc.afterFollow = func() { interrupts <- os.Interrupt }
	useService(t, svc)

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	var err error
	stdout := captureStdout(t, func() { err = runTwinRehearse(ctx, &options{}, &rehearseFlags{branch: lessLink}) })
	code, doc := exitOf(t, err)
	validateM10Document(t, doc)
	cancelled := findingOf(t, doc, findings.RuleRunCancelled)
	if svc.cancels != 1 || code != findings.ExitError || doc.Status != findings.StatusError || cancelled.Object != rehearseRun ||
		cancelled.Step != findings.StepPush || !strings.Contains(cancelled.Message, "at stage "+thirdRef) {
		t.Errorf("Cancel called %d times, exit %d, status %s, %+v; want once, 2, error, run.cancelled at push naming the stage",
			svc.cancels, code, doc.Status, cancelled)
	}
	if !strings.Contains(stdout, "\nstep push n1: done in 2.5s\nrun cancelled; waiting for its destroy\n") ||
		!strings.Contains(stdout, "stage "+thirdRef+": cancelled at phase push: landed n1; error: the run was cancelled\n") ||
		!strings.Contains(stdout, "stage "+headRef+": not reached\n") {
		t.Errorf("stdout:\n%s\nwant the cancel's line after the step's, third-link cancelled and the head not reached", stdout)
	}
}

// The answer lost (T079): a run whose result cannot be read, and one whose follow the
// operator's second interrupt stopped, each keep the run in the report. The text's closing
// line, the JSON's block and the markdown name it, say that its end was not read and why and
// that it goes on to its destroy, and none says that no run was started, that every stage
// passed or that the twin is destroyed; no stage line is printed, since the answer learned
// nothing of the stages; exit 2.
func TestRehearseAnswerLost(t *testing.T) {
	rehearseHost(t)
	rehearseInfrahub(t)
	never := []string{"No run was started", "nothing was started", "every one passed", "the twin is destroyed",
		"stage " + seededRef + ": created", ": not reached"}
	const unread = "waiting for run " + rehearseRun + ": the workflow service did not answer"
	const stopped = "stopped waiting for run " + rehearseRun + "; it continues on the workflow service, and fylgja twin destroy will wait for it"
	for _, c := range []struct {
		name, why string
		service   func(interrupts chan os.Signal) *fakeService
	}{
		{"its result unread", unread, func(chan os.Signal) *fakeService {
			svc := okRun()
			svc.resultErr = errors.New("the workflow service did not answer")
			return svc
		}},
		{"a second interrupt", stopped, func(interrupts chan os.Signal) *fakeService {
			svc := okRun()
			svc.release = make(chan struct{})
			svc.afterFollow = func() { interrupts <- os.Interrupt; interrupts <- os.Interrupt }
			return svc
		}},
	} {
		t.Run(c.name, func(t *testing.T) {
			interrupts := useInterrupts(t)
			useService(t, c.service(interrupts))
			code, stdout, _ := rehearse(t, "--branch", lessLink)
			closing := "rehearsal error: run fylgja-rehearse " + rehearseRun + " was started and its end was not read (" + c.why +
				"); it goes on to its destroy, and fylgja twin show says where it is\n"
			if code != findings.ExitError || !strings.HasSuffix(stdout, closing) {
				t.Errorf("exit %d, stdout:\n%s\nwant 2, ending:\n%s", code, stdout, closing)
			}

			interrupts = useInterrupts(t)
			useService(t, c.service(interrupts))
			code, doc, raw := rehearseDoc(t, "--branch", lessLink)
			if code != findings.ExitError || doc.Status != findings.StatusError || doc.Rehearsal == nil || doc.Rehearsal.Run == nil ||
				doc.Rehearsal.Run.RunID != rehearseRun || doc.Rehearsal.Destroy != nil || doc.Subject.RunID != rehearseRun {
				t.Errorf("exit %d, status %s; want 2, error, the block naming the run and no destroy:\n%s", code, doc.Status, raw)
			}
			for _, f := range doc.Findings {
				if strings.HasPrefix(f.Rule, "rehearsal.") || f.Rule == findings.RuleCleanupIncomplete {
					t.Errorf("the document files %s, which the answer did not learn: %+v", f.Rule, f)
				}
			}

			interrupts = useInterrupts(t)
			useService(t, c.service(interrupts))
			code, md, _ := rehearse(t, "--branch", lessLink, "--markdown")
			if want := `## Fylgja started rehearsing proposed change "change pc-1" on change-1, scope tag:fylgja` + "\n\nRun `fylgja-rehearse " +
				rehearseRun + "` was started, and its end was not read: "; code != findings.ExitError || !strings.HasPrefix(md, want) ||
				!strings.Contains(md, "It goes on to its destroy, and `fylgja twin show` says where it is.") {
				t.Errorf("exit %d, the markdown:\n%s\nwant 2, beginning:\n%s", code, md, want)
			}
			for _, out := range []string{stdout, md} {
				for _, n := range never {
					if strings.Contains(out, n) {
						t.Errorf("the report says %q:\n%s", n, out)
					}
				}
			}
		})
	}
}

// Scenario 8: the deadline passes while third-link's step runs. The stage is error, the run
// cut there, and the rehearsal ends rehearsal.deadline.cut naming the stage, each finished
// stage's time and the deadline, exit 2; the twin is still destroyed.
func TestRehearseDeadlineCut(t *testing.T) {
	rehearseHost(t)
	rehearseInfrahub(t)
	cut := stepped(thirdRef, "s1", provision.OutcomeCancelled, nil, rehearsal.VerdictError)
	cut.Step.Phase, cut.Step.Step = findings.StepReadiness, findings.StepReadiness
	res := rehearsedRun(rehearsal.OutcomeCut, nil, cut, provision.RehearsedStage{Ref: headRef, Verdict: rehearsal.VerdictNotReached})
	res.DeadlineHit, res.Reached, res.UsedS = true, thirdRef, 1950.2
	newSvc := func() *fakeService {
		return &fakeService{rehearseRun: rehearseRun, rehearseEvents: rehearseEvents(thirdRef), rehearseResult: res}
	}
	useService(t, newSvc())
	useInterrupts(t)

	code, stdout, _ := rehearse(t, "--branch", lessLink)
	if code != findings.ExitError || !strings.Contains(stdout, "stage "+thirdRef+": ") ||
		!strings.Contains(stdout, "; error: the deadline passed\n") || !strings.Contains(stdout, "destroying the twin\n") {
		t.Errorf("exit %d, want 2, third-link cut by the deadline and the twin destroyed:\n%s", code, stdout)
	}

	useService(t, newSvc())
	code, doc, _ := rehearseDoc(t, "--branch", lessLink)
	f := findingOf(t, doc, findings.RuleRehearsalDeadlineCut)
	if code != findings.ExitError || doc.Status != findings.StatusError || f.Object != thirdRef || f.Step != findings.StepReadiness ||
		!strings.Contains(f.Message, "the deadline of 1950s passed at stage "+thirdRef) || !strings.Contains(f.Message, seededRef+" took 70.0s") {
		t.Errorf("exit %d, status %s, %+v; want 2, error, the cut naming the stage, the baseline's time and the deadline", code, doc.Status, f)
	}
	if doc.Rehearsal.Destroy == nil || doc.Rehearsal.Stages[3].Verdict != string(rehearsal.VerdictNotReached) {
		t.Errorf("destroy %+v, stages %v; want the twin destroyed and the head not reached", doc.Rehearsal.Destroy, rehearsalStages(doc))
	}
}

// Scenario 9: stages whose budgets sum past the ceiling (lowered here, as no flag can) are
// refused rehearsal.deadline.unfit at start, naming the time they need and the ceiling,
// before the host is read or the workflow service dialled, exit 1.
func TestRehearseDeadlineOverTheCeiling(t *testing.T) {
	clab := rehearseHost(t)
	rehearseInfrahub(t)
	useService(t, nil)
	useRehearsalCeiling(t, 30*time.Minute)

	code, doc, raw := rehearseDoc(t, "--branch", lessLink)
	f := findingOf(t, doc, findings.RuleRehearsalDeadlineUnfit)
	if code != findings.ExitRejected || doc.Status != findings.StatusRejected || f.Step != findings.StepStart || f.Object != lessLink ||
		!strings.Contains(f.Message, "32m30s (1950s)") || !strings.Contains(f.Message, "30m0s (1800s)") {
		t.Errorf("exit %d, status %s, %+v; want 1, rejected, unfit at start naming 1950s and the 1800s ceiling\n%s", code, doc.Status, f, raw)
	}
	if doc.Rehearsal == nil || doc.Rehearsal.DeadlineS != 1950 || doc.Rehearsal.CeilingS != 1800 || doc.Rehearsal.Run != nil {
		t.Errorf("the block %+v; want the deadline and the ceiling named, no run", doc.Rehearsal)
	}
	startedNothing(t, "over the ceiling", clab, nil)
}

// Scenario 10: --json is one document on stdout, operation twin.rehearse with the branch
// and the run as its subject, whose block the rehearsal contract accepts (rehearseDoc
// validates it) and carries what the text printed: the deadline, the time used, each
// stage's verdict, its wait and its counts, the destroy; and no configuration content.
func TestRehearseJSON(t *testing.T) {
	rehearseHost(t)
	f := rehearseInfrahub(t)
	useService(t, okRun())
	useInterrupts(t)

	code, doc, raw := rehearseDoc(t, "--branch", lessLink)
	b := doc.Rehearsal
	if code != findings.ExitOK || doc.Operation != findings.OpTwinRehearse || doc.Subject == nil || doc.Subject.Branch != lessLink ||
		doc.Subject.RunID != rehearseRun || b == nil {
		t.Fatalf("exit %d, operation %s, subject %+v; want 0, twin.rehearse on %s, run %s, with a block\n%s",
			code, doc.Operation, doc.Subject, lessLink, rehearseRun, raw)
	}
	if b.DeadlineS != 1950 || b.CeilingS != 3600 || b.UsedS != 118.4 || b.Run == nil || b.Run.RunID != rehearseRun ||
		b.Destroy == nil || len(b.Destroy.Removed) != 2 || len(b.Reproduce) != 0 || b.ProposedChange.ID != "pc-1" {
		t.Errorf("the block %+v; want the deadline, the time used, the run, the destroy and no reproduce", b)
	}
	third := b.Stages[2]
	if third.BundleID == nil || third.Step == nil || third.Step.Outcome != provision.StepStepped || third.Wait == nil ||
		third.Wait.Outcome != wire.WaitSettled || third.Verify == nil || third.Verify.Neighbor.Held != 4 || third.At != planLiveAt ||
		third.AtSource != findings.AtSourceGiven || third.Description != "third link" {
		t.Errorf("third-link %+v; want its bundle, its step, its wait, its counts and its resolution", third)
	}
	mustQuoteNoContent(t, f, raw)
}

// One compiled stage alone, the head on an empty main with nothing marked, is the baseline:
// built, verified and destroyed with no step, the warning rehearsal.steps.none, exit 0.
func TestRehearseOneStage(t *testing.T) {
	rehearseHost(t)
	f := planInfrahub(t)
	versioned(t, f)
	emptyMain(f)
	f.start()
	res := rehearsedRun(rehearsal.OutcomeOK, nil)
	res.Stages[1].Ref = headRef
	svc := &fakeService{rehearseRun: rehearseRun, rehearseEvents: rehearseEvents(), rehearseResult: res}
	useService(t, svc)
	useInterrupts(t)

	code, doc, raw := rehearseDoc(t, "--branch", lessLink)
	none := findingOf(t, doc, findings.RuleRehearsalStepsNone)
	in := svc.rehearsed[0]
	if code != findings.ExitOK || doc.Status != findings.StatusOK || none.Severity != findings.Warning || none.Step != findings.StepResolve ||
		len(in.Stages) != 2 || in.Stages[1].Role != rehearsal.RoleBaseline || in.DeadlineS != 690 {
		t.Errorf("exit %d, status %s, %+v, the run's stages %+v, deadline %ds; want 0, ok, the warning, the head the baseline, 690s\n%s",
			code, doc.Status, none, in.Stages, in.DeadlineS, raw)
	}
}

// The baseline could not be built: the provision failed at its deploy and cleaned up, no
// stage was stepped to, the destroy found nothing. failed, exit 3, with the provision's own
// finding beside rehearsal.baseline.failed.
func TestRehearseBaselineNotBuilt(t *testing.T) {
	rehearseHost(t)
	rehearseInfrahub(t)
	res := rehearsedRun(rehearsal.OutcomeBaselineFailed, nil,
		provision.RehearsedStage{Ref: thirdRef, Verdict: rehearsal.VerdictNotReached},
		provision.RehearsedStage{Ref: headRef, Verdict: rehearsal.VerdictNotReached})
	res.Stages[1] = provision.RehearsedStage{Ref: seededRef, Verdict: rehearsal.VerdictError,
		Run: &wire.RunRef{WorkflowID: provision.WorkflowProvision, RunID: "p1"},
		Provision: &provision.ProvisionResult{Outcome: provision.OutcomeFailed, Step: findings.StepDeploy,
			Findings: findings.List{{Severity: findings.Rejection, Rule: findings.RuleOperationFailed, Object: "lab fylgja",
				Step: findings.StepDeploy, Message: "deploying lab fylgja: exit status 1"}},
			Cleanup: provision.CleanupResult{Teardown: provision.CleanupDone, Unstage: provision.CleanupDone}}, TookS: 50}
	res.Destroy.Cleanup.Removed = nil
	useService(t, &fakeService{rehearseRun: rehearseRun, rehearseEvents: rehearseEvents(), rehearseResult: res})
	useInterrupts(t)

	code, doc, _ := rehearseDoc(t, "--branch", lessLink)
	failed := findingOf(t, doc, findings.RuleRehearsalBaselineFailed)
	if code != findings.ExitFailed || doc.Status != findings.StatusFailed || failed.Object != seededRef ||
		!carriesRule(doc.Findings, findings.RuleOperationFailed) || doc.Rehearsal.Baseline != nil {
		t.Errorf("exit %d, status %s, findings %v, baseline %+v; want 3, failed, the provision's finding beside the baseline's, "+
			"no baseline block", code, doc.Status, rulesOf(doc.Findings), doc.Rehearsal.Baseline)
	}

	// A provision that ended error or rejected tried no build and cleaned nothing up: the
	// rehearsal could not run, error, exit 2, rehearsal.stage.error on the baseline at the
	// step the provision stopped at, its own finding beside it, and never
	// rehearsal.baseline.failed (FR-009; T081).
	for _, outcome := range []string{provision.OutcomeError, provision.OutcomeRejected} {
		res := res
		res.Outcome = rehearsal.OutcomeStageError
		res.Stages = slices.Clone(res.Stages)
		base := res.Stages[1]
		p := *base.Provision
		p.Outcome, p.Step = outcome, findings.StepHostCheck
		p.Findings = findings.List{{Severity: findings.Rejection, Rule: findings.RuleOperationFailed, Object: "lab fylgja",
			Step: findings.StepHostCheck, Message: "host check: the host could not be inspected"}}
		p.Cleanup = provision.CleanupResult{Teardown: provision.CleanupSkipped, Unstage: provision.CleanupSkipped}
		base.Provision = &p
		res.Stages[1] = base
		useService(t, &fakeService{rehearseRun: rehearseRun, rehearseEvents: rehearseEvents(), rehearseResult: res})

		code, doc, _ := rehearseDoc(t, "--branch", lessLink)
		stageErr := findingOf(t, doc, findings.RuleRehearsalStageError)
		if code != findings.ExitError || doc.Status != findings.StatusError || stageErr.Object != seededRef ||
			stageErr.Step != findings.StepHostCheck || carriesRule(doc.Findings, findings.RuleRehearsalBaselineFailed) ||
			!carriesRule(doc.Findings, findings.RuleOperationFailed) {
			t.Errorf("%s: exit %d, status %s, findings %v; want 2, error, rehearsal.stage.error at host_check beside the "+
				"provision's own finding, no rehearsal.baseline.failed", outcome, code, doc.Status, rulesOf(doc.Findings))
		}
	}
}

// The destroy left the lab: unclean, exit 4, through cleanup.incomplete, though every stage
// passed.
func TestRehearseDestroyUnclean(t *testing.T) {
	rehearseHost(t)
	rehearseInfrahub(t)
	svc := okRun()
	svc.rehearseResult.Destroy = &provision.DestroyResult{Cleanup: provision.CleanupResult{Teardown: provision.CleanupFailed,
		Unstage: provision.CleanupDone, Remaining: []string{"lab fylgja"}},
		Findings: findings.List{{Severity: findings.Rejection, Rule: findings.RuleCleanupIncomplete, Object: "lab fylgja",
			Step: findings.StepTeardown, Message: "lab fylgja is still there; fylgja twin destroy clears it"}}}
	useService(t, svc)
	useInterrupts(t)

	code, doc, _ := rehearseDoc(t, "--branch", lessLink)
	if code != findings.ExitUnclean || doc.Status != findings.StatusUnclean || !carriesRule(doc.Findings, findings.RuleCleanupIncomplete) {
		t.Errorf("exit %d, status %s, findings %v; want 4, unclean, cleanup.incomplete", code, doc.Status, rulesOf(doc.Findings))
	}
	for _, s := range doc.Rehearsal.Stages[2:] {
		if s.Verdict != string(rehearsal.VerdictPassed) {
			t.Errorf("%s reads %s; the stages passed", s.Ref, s.Verdict)
		}
	}
}

// After the run the stages are listed again: third-link marked again at another as_of while
// the run ran is rehearsal.stage.moved, and the proposed change merged while it ran is
// rehearsal.change.closed. Both are warnings: what was rehearsed stands, exit 0.
func TestRehearseStagesReadAgainAfterTheRun(t *testing.T) {
	for _, c := range []struct {
		name   string
		change func(f *fakeInfrahub)
		rule   string
		object string
		says   string
	}{
		{"a stage moved", func(f *fakeInfrahub) { f.changes[0].Stages[0].At = "2026-10-16T08:55:00.000000+00:00" },
			findings.RuleRehearsalStageMoved, thirdRef, "now resolves to branch change-1 at 2026-10-16T08:55:00.000000+00:00"},
		{"the proposed change closed", func(f *fakeInfrahub) { f.changes[0].State = "merged" },
			findings.RuleRehearsalChangeClosed, lessLink, "is no longer open on branch change-1"},
	} {
		t.Run(c.name, func(t *testing.T) {
			rehearseHost(t)
			f := rehearseInfrahub(t)
			svc := okRun()
			svc.afterFollow = func() { c.change(f) }
			useService(t, svc)
			useInterrupts(t)

			code, doc, raw := rehearseDoc(t, "--branch", lessLink)
			w := findingOf(t, doc, c.rule)
			if code != findings.ExitOK || doc.Status != findings.StatusOK || w.Severity != findings.Warning || w.Object != c.object ||
				w.Step != findings.StepResolve || !strings.Contains(w.Message, c.says) {
				t.Errorf("exit %d, status %s, %+v; want 0, ok, a warning on %s saying %q\n%s", code, doc.Status, w, c.object, c.says, raw)
			}
		})
	}
}

// The text, line by line (contracts/rehearse-command.md, "The text"): the heading naming the
// proposed change, its branch, the stages and the deadline under the ceiling; each stage's
// resolution, the baseline marked and the refused branch point with its rejection under it;
// the run; each child preceded by the line naming its stage, the baseline's wait as its
// verify, and the destroy; then, once the run has closed, what the destroy removed, as twin
// destroy says it, one line per stage and the closing line. The findings, the branch point's
// refusal among them, are on stderr as every document prints them.
func TestRehearseText(t *testing.T) {
	rehearseHost(t)
	rehearseInfrahub(t)
	useService(t, okRun())
	useInterrupts(t)

	code, stdout, stderr := rehearse(t, "--branch", lessLink)
	missing := "rejection scope.empty [step read] tag:fylgja: scope tag:fylgja selects no device on branch main at " + fakeBranchedFrom
	want := strings.Join([]string{
		`rehearsal of proposed change "change pc-1" (pc-1) on branch change-1, draft: 4 stages; deadline 32m30s (ceiling 1h0m0s), scope tag:fylgja`,
		`change-1/branch-point: refused (scope.empty)`,
		`  ` + missing,
		`change-1/seeded: branch change-1 at 2026-10-16T08:30:00.000000+00:00 (written), "after the link is cabled"; baseline`,
		`change-1/third-link: branch change-1 at 2026-10-16T08:50:00.000000+00:00 (given), "third link"`,
		`change-1/head: branch change-1 at 2026-10-16T08:40:00.000001+00:00 (head)`,
		`run fylgja-rehearse r1`,
		`stage change-1/seeded: creating the twin`,
		`run fylgja-provision p1`,
		`step deploy: done in 41.2s`,
		`step record: done in 0.1s`,
		`stage change-1/seeded: verify: settled after 3.2s (2 reads)`,
		`stage change-1/third-link: stepping`,
		`run fylgja-step s1`,
		`step push n1: done in 2.5s`,
		`stage change-1/head: stepping`,
		`run fylgja-step s2`,
		`step push n1: done in 2.5s`,
		`destroying the twin`,
		`run fylgja-destroy d1`,
		`step teardown: done in 5.2s`,
		`removed lab fylgja (3 containers)`,
		`removed twin directory /srv/twin`,
		`stage change-1/branch-point: refused (scope.empty)`,
		`stage change-1/seeded: created; settled after 3.2s (2 reads); 15 held, 0 failed, 0 skipped; baseline`,
		`stage change-1/third-link: stepped in 4.5s (push n1 2.5s); settled after 6.1s (4 reads); 19 held, 0 failed, 0 skipped; passed`,
		`stage change-1/head: unchanged in 4.5s; settled after 6.1s (4 reads); 19 held, 0 failed, 0 skipped; passed`,
		`rehearsal ok: 3 stages rehearsed, every one passed; the twin is destroyed; 118.4s of the 1950s deadline`,
	}, "\n") + "\n"
	if code != findings.ExitOK || stdout != want {
		t.Errorf("exit %d, stdout:\n%s\nwant 0 and:\n%s", code, stdout, want)
	}
	if want := missing + "\n1 finding(s): 1 rejection, 0 warning, 0 info\n"; stderr != want {
		t.Errorf("stderr:\n%s\nwant the findings as text:\n%s", stderr, want)
	}
}

// --markdown prints the report as the server rendered it (rehearsal.Markdown) on stdout and
// nothing else there, the progress and the findings on stderr, and exits by the document:
// 0 on an ok run, whose markdown gives no commands, and 5 on a failed stage, whose markdown
// gives the commands that reproduce it.
func TestRehearseMarkdown(t *testing.T) {
	rehearseHost(t)
	f := rehearseInfrahub(t)
	useService(t, okRun())
	useInterrupts(t)

	code, stdout, stderr := rehearse(t, "--branch", lessLink, "--markdown")
	served, doc := ask(t, findings.OpTwinRehearse, api.RenderMarkdown, map[string]any{"branch": lessLink}, nil).document(t, "markdown")
	// Each request resolves its stages at its own second, which the run line names.
	resolved := regexp.MustCompile(`stages resolved at [0-9T:Z-]+\.`)
	sameRun := func(md string) string { return resolved.ReplaceAllString(md, "stages resolved at <when>.") }
	if code != findings.ExitOK || stdout == "" || sameRun(stdout) != sameRun(served.Markdown) {
		t.Errorf("exit %d, stdout:\n%s\nwant 0 and the markdown the server renders alone:\n%s", code, stdout, served.Markdown)
	}
	if !strings.HasPrefix(stdout, `## Fylgja rehearsed proposed change `) || !strings.HasSuffix(stdout, rehearsal.Caveat+"\n") {
		t.Errorf("stdout:\n%s\nwant the markdown, from its heading to its caveat", stdout)
	}
	// The comment fylgja-twin posts names the scope every stage was read under, as the
	// document's subject does (017; US5 scenario 4).
	if heading, _, _ := strings.Cut(stdout, "\n"); heading != `## Fylgja rehearsed proposed change "change pc-1" on change-1, scope tag:fylgja` ||
		doc.Subject == nil || doc.Subject.Scope != defaultScope {
		t.Errorf("heading %q, subject %+v; want both naming the scope %s", heading, doc.Subject, defaultScope)
	}
	for _, want := range []string{"\n| stage | at | snapshot | bundle | step | wait | verify | new verification failures | verdict |\n", "\n```mermaid\nflowchart TD\n"} {
		if !strings.Contains(stdout, want) {
			t.Errorf("the markdown lacks %q:\n%s", want, stdout)
		}
	}
	// Each row names its stage's snapshot before its bundle, and the branch point, refused at
	// its read, neither (018; T021's column).
	for _, s := range doc.Rehearsal.Stages {
		cells := " | — | — | "
		if s.SnapshotID != nil && s.BundleID != nil {
			cells = " | " + (*s.SnapshotID)[:8] + "… | " + (*s.BundleID)[:8] + "… | "
		} else if s.Ref != pointRef {
			t.Errorf("%s names snapshot %v and bundle %v; want both", s.Ref, s.SnapshotID, s.BundleID)
		}
		if !strings.Contains(stdout, "\n| "+s.Ref+" | ") || !strings.Contains(stdout, cells) {
			t.Errorf("the markdown's row for %s lacks %q:\n%s", s.Ref, cells, stdout)
		}
	}
	for _, progress := range []string{"run fylgja-rehearse r1\n", "stage " + seededRef + ": creating the twin\n", "rehearsal ok: "} {
		if strings.Contains(stdout, progress) || !strings.Contains(stderr, progress) {
			t.Errorf("the progress line %q is not on stderr alone:\nstdout:\n%s\nstderr:\n%s", progress, stdout, stderr)
		}
	}
	if strings.Contains(stdout, "**Reproduce by hand**") || !strings.Contains(stderr, "1 finding(s): 1 rejection") {
		t.Errorf("stdout:\n%s\nstderr:\n%s\nwant no commands on an ok run, and the findings on stderr", stdout, stderr)
	}
	mustQuoteNoContent(t, f, stdout, stderr)

	diverged := stepped(thirdRef, "s1", provision.StepDiverged, settledAfter(6.1, 4), rehearsal.VerdictFailed)
	diverged.Step.Phase = findings.StepPush
	diverged.Step.PushPlan = []wire.StepPush{{Node: "n1", Reasons: []string{"artifact"}, Outcome: wire.PushRefused, Rule: findings.RulePushRefused}}
	useService(t, &fakeService{rehearseRun: rehearseRun, rehearseEvents: rehearseEvents(thirdRef),
		rehearseResult: rehearsedRun(rehearsal.OutcomeStageFailed, nil, diverged,
			provision.RehearsedStage{Ref: headRef, Verdict: rehearsal.VerdictNotReached})})
	code, stdout, _ = rehearse(t, "--branch", lessLink, "--markdown")
	if code != findings.ExitNonconforming || !strings.Contains(stdout, "**Reproduce by hand**") ||
		!strings.Contains(stdout, "fylgja twin create --stage "+seededRef+" --scope "+defaultScope+"\nfylgja twin step --stage "+thirdRef+
			" --allow-restart\n") {
		t.Errorf("exit %d, stdout:\n%s\nwant 5 and the commands that reproduce the failure", code, stdout)
	}
}

// Before the server is asked anything: --branch left out is the client's own refusal,
// --branch is required, and --markdown beside --json is cobra's, each exit 2 with no request
// sent. An empty --branch= is the server's to refuse, stage.ref.invalid at start, exit 2,
// before it asks Infrahub or dials the workflow service.
func TestRehearseRefusedBeforeAnyConnection(t *testing.T) {
	for _, c := range []struct {
		name     string
		args     []string
		rule     string
		message  string
		requests int
	}{
		{"no --branch", nil, findings.RuleOperationFailed, "--branch is required", 0},
		{"--markdown beside --json", []string{"--branch", lessLink, "--markdown"}, findings.RuleOperationFailed,
			"if any flags in the group [markdown json] are set none of the others can be; [json markdown] were all set", 0},
		{"--branch=", []string{"--branch="}, findings.RuleStageRefInvalid,
			`--branch "" is not a branch: expected a branch with no "/" and no whitespace`, 1},
	} {
		t.Run(c.name, func(t *testing.T) {
			clab := rehearseHost(t)
			useService(t, nil)
			f := planInfrahub(t)
			f.start()
			awaitIdle(t)
			before := requestsLogged()

			code, doc := executeTwin(t, append([]string{"twin", "rehearse"}, c.args...)...)
			if code != findings.ExitError || doc.Status != findings.StatusError || doc.Operation != findings.OpTwinRehearse ||
				len(doc.Findings) != 1 || doc.Findings[0].Rule != c.rule || doc.Findings[0].Message != c.message {
				t.Errorf("exit %d, %s %s, findings %+v; want 2, error, twin.rehearse, %s saying %q",
					code, doc.Status, doc.Operation, doc.Findings, c.rule, c.message)
			}
			if c.rule == findings.RuleStageRefInvalid && doc.Findings[0].Step != findings.StepStart {
				t.Errorf("step %q, want start", doc.Findings[0].Step)
			}
			awaitIdle(t)
			if got := requestsLogged() - before; got != c.requests {
				t.Errorf("the server logged %d requests, want %d", got, c.requests)
			}
			if got := f.requests(); len(got) != 0 {
				t.Errorf("Infrahub was asked %+v", got)
			}
			startedNothing(t, c.name, clab, nil)
			validateM10Document(t, doc)
		})
	}
}

// Every frame of a rehearsal's answer, in each rendering, is api.schema.json's (ask checks
// each line): the start, the run, every event, and the document, which carries the text
// under "text" and "markdown" and the markdown under "markdown" alone; a refusal before the
// start is its document alone, its markdown included. Nothing the server wrote or logged
// carries the API's token, Infrahub's or the node login's password.
func TestRehearseFramesAreTheAPIs(t *testing.T) {
	rehearseHost(t)
	rehearseInfrahub(t)
	svc := okRun()
	useService(t, svc)
	m := markServed()

	for _, render := range []string{"", api.RenderJSON, api.RenderText, api.RenderMarkdown} {
		label := `render "` + render + `"`
		a := ask(t, findings.OpTwinRehearse, render, map[string]any{"branch": lessLink}, nil)
		if a.status != http.StatusOK {
			t.Fatalf("%s: status %d", label, a.status)
		}
		f, doc := a.document(t, label)
		satisfiesContract(t, findingsContract(t, currentContract), f.Document, label+"'s document")
		if got := a.kinds(api.KindOut, api.KindErr); !slices.Equal(got, runKinds(len(svc.rehearseEvents))) || doc.Status != findings.StatusOK {
			t.Errorf("%s: frames %v, status %s; want a run's, ok", label, got, doc.Status)
		}
		textual := render == api.RenderText || render == api.RenderMarkdown
		if (f.Text != "") != textual || (f.Markdown != "") != (render == api.RenderMarkdown) {
			t.Errorf("%s: the document carries text %v and markdown %v", label, f.Text != "", f.Markdown != "")
		}
		if (a.text(api.KindOut) != "") != textual {
			t.Errorf("%s: out frames %q", label, a.text(api.KindOut))
		}
	}

	refused := ask(t, findings.OpTwinRehearse, api.RenderMarkdown, map[string]any{"branch": ""}, nil)
	f, doc := refused.document(t, "the refusal")
	if got := refused.kinds(api.KindOut, api.KindErr); !slices.Equal(got, []string{api.KindDocument}) || f.Markdown == "" ||
		doc.Status != findings.StatusError {
		t.Errorf("the refusal: frames %v, status %s, markdown %q; want its document alone, with its markdown", got, doc.Status, f.Markdown)
	}
	noSecretServed(t, m, fakeToken, "not-the-real-one")
}
