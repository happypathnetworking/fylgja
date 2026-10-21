package findings

import (
	"slices"
	"sort"
	"strings"
	"testing"
)

// twin rehearse's documents (015) as rehearsal.schema.json spells them, and the rehearsal a
// twin.json 7 names, as twin show and twin verify carry it.

const (
	rehearseRunID   = "01a1b2c3-0000-7000-8000-0000000000aa"
	reclaimedRunID  = "01a1b2c3-0000-7000-8000-000000000099"
	provisionRunID  = "01a1b2c3-0000-7000-8000-0000000000b1"
	rehearsalResAt  = "2026-10-17T14:02:11Z"
	rehearsalChange = "change-1"
)

var (
	seededID  = strings.Repeat("5c", 32)
	badPortID = strings.Repeat("d0", 32)
	headID    = strings.Repeat("cc", 32)
)

func rehearsalRun(workflow, id string) ShowRef { return ShowRef{WorkflowID: workflow, RunID: id} }

// rehearsalStage is one stage of the example proposed change as the plan resolved it, with
// no run fields: a role and a verdict the caller sets.
func rehearsalStage(label, description, source, branch, at string, bundle *string, role, verdict string) RehearsalStage {
	return RehearsalStage{Ref: rehearsalChange + "/" + label, Label: label, Description: description, AtSource: source,
		Branch: branch, At: at, BundleID: bundle, Role: role, Verdict: verdict}
}

// The example proposed change's stages: the branch point refused and passed over, seeded the
// baseline, two marks and the head.
func branchPointStage(verdict string) RehearsalStage {
	return rehearsalStage("branch-point", "", AtSourceBranchPoint, "main", "2026-10-16T17:20:19.944651+00:00", nil,
		"refused", verdict)
}

func seededStage(verdict string) RehearsalStage {
	return rehearsalStage("seeded", "after the link is cabled", AtSourceWritten, rehearsalChange,
		"2026-10-16T17:25:30.118244+00:00", &seededID, "baseline", verdict)
}

func liveStage(role, verdict string) RehearsalStage {
	return rehearsalStage("live", "after its configuration is live", AtSourceGiven, rehearsalChange,
		"2026-10-16T17:30:00.000000+00:00", &stepToID, role, verdict)
}

func badPortStage(role, verdict string) RehearsalStage {
	return rehearsalStage("bad-port", "a port <disabled> \"by mistake\"", AtSourceGiven, rehearsalChange,
		"2026-10-16T17:30:05.000000+00:00", &badPortID, role, verdict)
}

func headStage(role, verdict string) RehearsalStage {
	return rehearsalStage("head", "", AtSourceHead, rehearsalChange, "2026-10-16T17:30:11.884302+00:00", &headID, role, verdict)
}

// heldCount is a kind read from every node with n held and nothing failed.
func heldCount(n int) VerifyCount {
	zero := 0
	return VerifyCount{Held: n, Unread: &zero}
}

// heldSkippedCount is heldCount for a port kind, which counts its skips.
func heldSkippedCount(n int) VerifyCount {
	zero := 0
	return VerifyCount{Held: n, Skipped: &zero, Unread: &zero}
}

// settledCounts are a three-node twin's counts with every assertion held.
func settledCounts(ports, neighbours int) *VerifyCounts {
	return &VerifyCounts{HostName: heldCount(3), PortEnabled: heldSkippedCount(ports), Neighbor: heldSkippedCount(neighbours),
		Record: VerifyCount{Held: 3}}
}

// rehearsalDocuments are twin rehearse's documents: a nonconforming run that reclaimed a dead
// rehearsal's twin first and stopped at a stage diverged at its push, with every role and
// all but one verdict; a run the deadline cut, with the last; a baseline that could not be
// built; and a rehearsal refused before any run, its deadline over the ceiling.
func rehearsalDocuments() []labelledDocument {
	subject := func(run bool) *Subject {
		s := &Subject{Branch: rehearsalChange}
		if run {
			s.RunID = rehearseRunID
		}
		return s
	}
	destroyed := &CleanupBlock{Teardown: "done", Unstage: "done",
		Removed: []string{"lab fylgja (3 containers)", "twin directory /srv/fylgja/local/twin"}}
	baselineFinding := StepWaitFailing{Rule: RuleVerifyNeighbor, Object: "n1:ethernet-1/2",
		Message: "node n1 (172.20.20.2:57400): port ethernet-1/2 sees no neighbour"}

	// The nonconforming run.
	var nonconforming List
	nonconforming.AddStep(Warning, StepDestroy, RuleRehearsalTwinReclaimed, reclaimedRunID,
		"the twin of rehearsal run "+reclaimedRunID+", which is no longer running, was destroyed: lab fylgja (3 containers), twin directory /srv/fylgja/local/twin")
	var refusedBranchPoint List
	refusedBranchPoint.AddStep(Rejection, StepRead, RuleContractNodeMissing, "main",
		"branch defines FylgjaContract but holds no instance of it")
	nonconforming = append(nonconforming, refusedBranchPoint...)
	var seededFindings List
	seededFindings.AddStep(Warning, StepObserve, RuleVerifyNeighbor, "change-1/seeded: n1:ethernet-1/2", baselineFinding.Message)
	nonconforming = append(nonconforming, seededFindings...)
	var badPortFindings List
	badPortFindings.AddStep(Rejection, StepPush, RulePushRefused, "n1",
		"n1 refused artifact device-config (checksum 9a0177b2e8c1d4f5a6b7c8d9e0f1a2b3) at line 12: invalid admin-state")
	badPortFindings.AddStep(Rejection, StepPush, RuleRehearsalStageFailed, "change-1/bad-port",
		"diverged at phase push: landed n3; not landed n1 (push.refused)")
	nonconforming = append(nonconforming, badPortFindings...)

	branchPoint := branchPointStage("refused")
	branchPoint.Findings = refusedBranchPoint
	seeded := seededStage("baseline")
	seeded.Findings = seededFindings
	seeded.Provision = &RehearsalProvision{Outcome: "ready", Run: rehearsalRun("fylgja-provision", provisionRunID)}
	seeded.Wait = &RehearsalWait{Outcome: "expired", BudgetS: 120, Reads: 58, AfterS: 120}
	seeded.Verify = &VerifyCounts{HostName: heldCount(3), PortEnabled: heldSkippedCount(6),
		Neighbor: VerifyCount{Held: 5, Failed: 1, Skipped: new(int), Unread: new(int)}, Record: VerifyCount{Held: 3}}
	seeded.TookS = 92.4
	live := liveStage("rehearsed", "passed")
	live.Step = &RehearsalStep{Outcome: "stepped", Run: rehearsalRun("fylgja-step", stepRunID),
		Pushed:  []RehearsalPush{{Node: "n1", Outcome: "landed", TookS: f64(2.5)}, {Node: "n3", Outcome: "landed", TookS: f64(2.6)}},
		Timings: StepTimingsBlock{ReconcileS: f64(0.4), Push: map[string]float64{"n1": 2.5, "n3": 2.6}, WholeS: 4.5}}
	live.Wait = &RehearsalWait{Outcome: "expired", BudgetS: 120, Reads: 61, AfterS: 120}
	live.Verify = seeded.Verify
	live.TookS = 124.5
	badPort := badPortStage("rehearsed", "failed")
	badPort.Findings = badPortFindings
	badPort.Step = &RehearsalStep{Outcome: "diverged", Run: rehearsalRun("fylgja-step", "01a1b2c3-0000-7000-8000-000000000003"),
		Phase: "push", Restarted: []string{"n3"},
		Pushed: []RehearsalPush{{Node: "n1", Outcome: "refused", Rule: RulePushRefused, TookS: f64(1.1)},
			{Node: "n3", Outcome: "landed", TookS: f64(2.4)}},
		Timings: StepTimingsBlock{ReconcileS: f64(3.9), Readiness: map[string]float64{"n3": 21.7},
			Push: map[string]float64{"n1": 1.1, "n3": 2.4}, WholeS: 29.8}}
	badPort.TookS = 29.8
	failed := NewDocument(OpTwinRehearse, subject(true), nonconforming)
	failed.Status = StatusNonconforming
	failed.Rehearsal = &RehearsalBlock{
		ProposedChange: StageChange{ID: "pc-1", Name: "third link", Branch: rehearsalChange, Draft: true},
		ResolvedAt:     rehearsalResAt, DeadlineS: 2610, CeilingS: 3600, UsedS: 301.6,
		Reclaimed: &RehearsalReclaim{Run: rehearsalRun("fylgja-rehearse", reclaimedRunID), Cleanup: *destroyed},
		Run:       &ShowRef{WorkflowID: "fylgja-rehearse", RunID: rehearseRunID},
		Baseline:  &RehearsalBaseline{Ref: "change-1/seeded", Findings: []StepWaitFailing{baselineFinding}},
		Stages:    []RehearsalStage{branchPoint, seeded, live, badPort, headStage("not_reached", "not_reached")},
		Destroy:   destroyed,
		Reproduce: []string{"fylgja twin create --stage change-1/seeded",
			"fylgja twin step --stage change-1/live --allow-restart",
			"fylgja twin step --stage change-1/bad-port --allow-restart",
			"fylgja twin verify", "fylgja twin destroy"},
	}

	// The run the deadline cut, during the step into change-1/live.
	var cut List
	cut.AddStep(Rejection, StepReadiness, RuleRehearsalDeadlineCut, "change-1/live",
		"the deadline of 1980s passed at stage change-1/live: change-1/seeded took 88.1s")
	cutSeeded := seededStage("baseline")
	cutSeeded.Provision = &RehearsalProvision{Outcome: "ready", Run: rehearsalRun("fylgja-provision", provisionRunID)}
	cutSeeded.Wait = &RehearsalWait{Outcome: "settled", BudgetS: 120, Reads: 2, AfterS: 3.2}
	cutSeeded.Verify = settledCounts(6, 6)
	cutSeeded.TookS = 88.1
	cutLive := liveStage("rehearsed", "error")
	cutLive.Findings = cut
	cutLive.Step = &RehearsalStep{Outcome: "cancelled", Run: rehearsalRun("fylgja-step", stepRunID),
		Timings: StepTimingsBlock{ReconcileS: f64(3.1), WholeS: 1861.9}}
	cutLive.TookS = 1861.9
	errored := NewDocument(OpTwinRehearse, subject(true), cut)
	errored.Status = StatusError
	errored.Rehearsal = &RehearsalBlock{
		ProposedChange: StageChange{ID: "pc-1", Name: "third link", Branch: rehearsalChange},
		ResolvedAt:     rehearsalResAt, DeadlineS: 1980, CeilingS: 3600, UsedS: 2001.2,
		Run:      &ShowRef{WorkflowID: "fylgja-rehearse", RunID: rehearseRunID},
		Baseline: &RehearsalBaseline{Ref: "change-1/seeded"},
		Stages:   []RehearsalStage{cutSeeded, cutLive, headStage("not_reached", "not_reached")},
		Destroy:  destroyed,
	}

	// The baseline that could not be built: its provision failed at readiness and cleaned up,
	// and no stage was rehearsed.
	var notBuilt List
	notBuilt.AddStep(Rejection, StepReadiness, RuleReadinessTimeout, "n2", "n2 did not answer its probe within 60s")
	notBuilt.AddStep(Rejection, StepProvision, RuleRehearsalBaselineFailed, "change-1/seeded",
		"the baseline change-1/seeded could not be built: its provision ended failed at readiness")
	unbuilt := seededStage("baseline")
	unbuilt.Findings = notBuilt
	unbuilt.Provision = &RehearsalProvision{Outcome: "failed", Run: rehearsalRun("fylgja-provision", provisionRunID),
		Step: StepReadiness, Cleanup: &CleanupBlock{Teardown: "done", Unstage: "done", Removed: []string{"lab fylgja (3 containers)"}}}
	unbuilt.TookS = 241.3
	baselineFailed := NewDocument(OpTwinRehearse, subject(true), notBuilt)
	baselineFailed.Status = StatusFailed
	baselineFailed.Rehearsal = &RehearsalBlock{
		ProposedChange: StageChange{ID: "pc-1", Name: "third link", Branch: rehearsalChange},
		ResolvedAt:     rehearsalResAt, DeadlineS: 1980, CeilingS: 3600, UsedS: 243.0,
		Run:     &ShowRef{WorkflowID: "fylgja-rehearse", RunID: rehearseRunID},
		Stages:  []RehearsalStage{unbuilt, liveStage("rehearsed", "not_reached")},
		Destroy: &CleanupBlock{Teardown: "nothing", Unstage: "nothing"},
	}

	// The rehearsal refused before any run: no run, no destroy, nothing used.
	var unfit List
	unfit.AddStep(Rejection, StepStart, RuleRehearsalDeadlineUnfit, rehearsalChange,
		"the stages need 3840s, over the ceiling of 3600s")
	refused := NewDocument(OpTwinRehearse, subject(false), unfit)
	refused.Rehearsal = &RehearsalBlock{
		ProposedChange: StageChange{ID: "pc-1", Name: "third link", Branch: rehearsalChange},
		ResolvedAt:     rehearsalResAt, DeadlineS: 3840, CeilingS: 3600,
		Stages: []RehearsalStage{seededStage("not_reached"), liveStage("rehearsed", "not_reached"),
			badPortStage("rehearsed", "not_reached"), headStage("rehearsed", "not_reached")},
	}

	return []labelledDocument{
		{"rehearse, nonconforming, after a reclaim", failed},
		{"rehearse, error, the deadline cut a stage", errored},
		{"rehearse, failed, the baseline not built", baselineFailed},
		{"rehearse, refused before any run", refused},
	}
}

// rehearsalTwinDocuments are twin show and twin verify of a rehearsal's twin, whose
// version 7 record names the rehearsal run.
func rehearsalTwinDocuments() []labelledDocument {
	run := &ShowRef{WorkflowID: "fylgja-rehearse", RunID: rehearseRunID}
	shown := showStepDocuments()[0].doc
	shown.Show.Record.Rehearsal = run
	verified := verifyDocuments()[0].doc
	verified.Verify.Twin.Rehearsal = run
	return []labelledDocument{
		{"show of a rehearsal's twin", shown},
		{"verify of a rehearsal's twin", verified},
	}
}

func TestRehearsalDocumentsSatisfyTheContract(t *testing.T) {
	schema := compileCurrentFindingsSchema(t)
	for _, c := range append(append(rehearsalDocuments(), rehearsalTwinDocuments()...), verifyDocuments()...) {
		t.Run(c.label, func(t *testing.T) {
			mustValidate(t, schema, c.doc, c.label)
			mustCarryNoContent(t, c.doc, c.label)
		})
	}
}

// The examples hold every role and every verdict the contract enumerates, and every
// outcome of the provision and the step children, so the contract is read for each.
func TestRehearsalDocumentsCoverEveryEnum(t *testing.T) {
	roles, verdicts := map[string]bool{}, map[string]bool{}
	for _, c := range rehearsalDocuments() {
		for _, s := range c.doc.Rehearsal.Stages {
			roles[s.Role], verdicts[s.Verdict] = true, true
		}
	}
	for _, c := range []struct {
		name string
		got  map[string]bool
		path []string
	}{
		{"role", roles, []string{"$defs", "stage", "properties", "role"}},
		{"verdict", verdicts, []string{"$defs", "stage", "properties", "verdict"}},
	} {
		got := make([]string, 0, len(c.got))
		for v := range c.got {
			got = append(got, v)
		}
		sort.Strings(got)
		if want := enumOf(t, "rehearsal.schema.json", c.path...); !slices.Equal(got, want) {
			t.Errorf("the examples' %ss are %v, the contract's %v", c.name, got, want)
		}
	}
}

// Every nullable key of the block is written, as null when it holds nothing, and every list
// as []: a refused rehearsal names no reclaim, no baseline, no destroy and nothing to
// reproduce, and has no run; a stage not reached has no child, no wait and no counts.
func TestRehearsalBlockWritesEveryNullableKey(t *testing.T) {
	docs := rehearsalDocuments()
	refused := string(mustMarshal(t, docs[3].doc))
	for _, want := range []string{`"reclaimed":null`, `"baseline":null`, `"destroy":null`, `"reproduce":[]`, `"used_s":0`,
		`"bundle_id":"` + seededID + `"`, `"provision":null,"step":null,"wait":null,"verify":null,"new_findings":[],"took_s":0`,
		`"findings":[]`} {
		if !strings.Contains(refused, want) {
			t.Errorf("the refused rehearsal does not write %s: %s", want, refused)
		}
	}
	if strings.Contains(refused, `"run":`) {
		t.Errorf("a rehearsal refused before any run names one: %s", refused)
	}
	failed := string(mustMarshal(t, docs[0].doc))
	for _, want := range []string{`"bundle_id":null`, `"restarted":[],"recreated":[],"created":[]`,
		`"baseline":{"ref":"change-1/seeded","findings":[{"rule":"verify.neighbor"`,
		`"reclaimed":{"run":{"workflow_id":"fylgja-rehearse","run_id":"` + reclaimedRunID + `"},"cleanup":{`} {
		if !strings.Contains(failed, want) {
			t.Errorf("the nonconforming rehearsal does not write %s: %s", want, failed)
		}
	}
	errored := string(mustMarshal(t, docs[1].doc))
	if want := `"baseline":{"ref":"change-1/seeded","findings":[]}`; !strings.Contains(errored, want) {
		t.Errorf("a baseline with no finding does not write %s: %s", want, errored)
	}
}

// A twin no rehearsal built carries no rehearsal in twin show's record, as an earlier
// record carries no stage, so M4 to M7's contracts still accept the document; twin verify
// writes it as null, as it writes every nullable key of its twin.
func TestRecordRehearsalIsShownWhenNamed(t *testing.T) {
	plain := string(mustMarshal(t, showStepDocuments()[0].doc))
	if strings.Contains(plain, `"rehearsal"`) {
		t.Errorf("a record naming no rehearsal shows one: %s", plain)
	}
	verified := string(mustMarshal(t, verifyDocuments()[0].doc))
	if !strings.Contains(verified, `"rehearsal":null`) {
		t.Errorf("verify of a twin no rehearsal built does not write rehearsal null: %s", verified)
	}
	want := `"rehearsal":{"workflow_id":"fylgja-rehearse","run_id":"` + rehearseRunID + `"}`
	for _, c := range rehearsalTwinDocuments() {
		if b := string(mustMarshal(t, c.doc)); !strings.Contains(b, want) {
			t.Errorf("%s does not write %s: %s", c.label, want, b)
		}
	}
}
