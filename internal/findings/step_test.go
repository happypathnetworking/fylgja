package findings

import (
	"encoding/json"
	"strings"
	"testing"
)

// The step's documents and the two M11 extensions of the stage list's block and the show
// record, as the contracts spell them, on stage sides since 014.

var (
	stepFromID = strings.Repeat("34", 32)
	stepToID   = strings.Repeat("ee", 32)
	stepRunID  = "01a1b2c3-0000-7000-8000-000000000002"
)

func f64(v float64) *float64 { return &v }

// stepDiff is M10's pair JSON for the example step from change-1/cabled to change-1/live:
// e1 and s1 cabled, s1's bootstrap and both artifacts moved.
var stepDiff = json.RawMessage(`{"from":"change-1/cabled","to":"change-1/live","from_bundle_id":"` + stepFromID +
	`","to_bundle_id":"` + stepToID + `","computed":true,"unchanged":false,` +
	`"nodes":{"added":[],"removed":[],"changed":[{"node":"s1","reasons":["bootstrap","mapping"]}]},` +
	`"links":{"added":[{"id":"e1:Ethernet3|s1:ethernet-1/3","a":{"node":"e1","port":"eth3"},"b":{"node":"s1","port":"e1-3"}}],"removed":[]},` +
	`"artifacts":{"changed":[{"node":"e1","name":"device-config","from":"43e8fd0c2de5f4646f74a51d34742824","to":"9a0177b2e8c1d4f5a6b7c8d9e0f1a2b3"}]}}`)

// stepBlock is the example step's block as the dry run carries it, with no run fields.
func stepBlock() *StepBlock {
	restart, live := "restart", "live"
	return &StepBlock{
		From: StepSideBlock{Stage: showStage("cabled", "after the link is cabled", AtSourceWritten), BundleID: stepFromID,
			At: "2026-10-16T17:25:30.118244+00:00"},
		To: StepSideBlock{Stage: showStage("live", "after its configuration is live", AtSourceGiven), BundleID: stepToID,
			At: "2026-10-16T17:30:00.000000+00:00", Branch: "change-1"},
		Diff: stepDiff,
		Reconcile: StepReconcileBlock{Restarted: []string{"e1"}, LinksAdded: []string{"e1:eth3 -- s1:e1-3"},
			Nodes: []StepPlanNode{{Node: "e1", Declared: &restart, Reported: "restart", Reason: "added link"},
				{Node: "s1", Declared: &live, Reported: "live", Reason: "added link"}}},
		PushPlan: []StepPushPlanEntry{{Node: "e1", Reasons: []string{"artifact", "restarted"}},
			{Node: "s1", Reasons: []string{"artifact", "bootstrap"}}},
	}
}

// stepDocuments are twin step's documents: the dry run refused, a stepped run, a diverged
// one, an unchanged one whose run pushed and awaited nobody, and one from the branch point
// to the head that skips the marks between (014's step.stage.skipped).
func stepDocuments() []labelledDocument {
	subject := func() *Subject {
		return &Subject{Stage: "change-1/live", Branch: "change-1", At: "2026-10-16T17:30:00.000000+00:00"}
	}
	resolved := liveBlock()

	var restart List
	restart.AddStep(Rejection, StepCompare, RuleStepRestartRequired, "e1",
		"containerlab would restart e1 (added link; package arista_eos declares restart): it loses its running state and its push until the step pushes it again; give --allow-restart to proceed, or --dry-run to see the step")
	dry := NewDocument(OpTwinStep, subject(), restart)
	dry.BundleID = stepToID
	dry.Stage = resolved
	dry.Step = stepBlock()
	dry.DryRun = &DryRunBlock{Nodes: []DryRunNode{{Name: "e1", Image: "ceos:4.32.0.2F", PSP: ptr("arista_eos"), MemoryMB: 2048,
		Artifact: &DryRunArtifact{Name: "device-config", ContentType: "text/plain", Checksum: m5Checksum, Size: 900}}},
		MemorySumMB: 2048, Host: DryRunHost{LabPresent: true, TwinDirPresent: true}, Verdict: VerdictRefused}

	ranSubject := subject()
	ranSubject.RunID = stepRunID
	stepped := NewDocument(OpTwinStep, ranSubject, nil)
	stepped.BundleID = stepToID
	stepped.Stage = resolved
	stepped.Step = stepBlock()
	stepped.Step.AllowRestart = true
	stepped.Step.StepRunBlock = &StepRunBlock{Run: ShowRef{WorkflowID: "fylgja-step", RunID: stepRunID},
		Outcome: "stepped", State: "ready",
		Pushed: []StepPushedEntry{{Node: "e1", Reasons: []string{"artifact", "restarted"}, Outcome: "landed", TookS: f64(1.6)},
			{Node: "s1", Reasons: []string{"artifact", "bootstrap"}, Outcome: "landed", TookS: f64(2.4)}},
		ReadyAfter: []StepReadyAfter{{Node: "e1", ReadyAfterS: 54.8}},
		Timings: StepTimingsBlock{ReconcileS: f64(3.9), Readiness: map[string]float64{"e1": 54.8},
			Push: map[string]float64{"e1": 1.6, "s1": 2.4}, WholeS: 71.2},
		StartedAt: "2026-10-02T09:14:30Z", EndedAt: "2026-10-02T09:15:41Z"}

	var stopped List
	stopped.AddStep(Rejection, StepPush, RulePushRefused, "e1",
		"node e1 refused artifact device-config (checksum 9a0177b2e8c1d4f5a6b7c8d9e0f1a2b3) at line 7: Invalid input (at token 0: 'bogus')")
	stopped.AddStep(Rejection, StepPush, RuleStepDiverged, stepRunID,
		"step run "+stepRunID+" towards stage change-1/live (bundle ee…) stopped at phase push: landed s1; not landed e1 (push.refused); the twin is up and diverged at stage change-1/cabled (bundle 34…), its record says so, and it accepts only fylgja twin destroy")
	diverged := NewDocument(OpTwinStep, ranSubject, stopped)
	diverged.Status = StatusDiverged
	diverged.BundleID = stepToID
	diverged.Stage = resolved
	diverged.Step = stepBlock()
	diverged.Step.AllowRestart = true
	// A created node, which no package declaration covers.
	diverged.Step.Reconcile.Added = []string{"s2"}
	diverged.Step.Reconcile.Nodes = append(diverged.Step.Reconcile.Nodes, StepPlanNode{Node: "s2", Reported: "create"})
	diverged.Step.StepRunBlock = &StepRunBlock{Run: ShowRef{WorkflowID: "fylgja-step", RunID: stepRunID},
		Outcome: "diverged", Phase: "push", State: "diverged",
		Pushed: []StepPushedEntry{{Node: "e1", Reasons: []string{"artifact", "restarted"}, Outcome: "refused", Rule: RulePushRefused},
			{Node: "s1", Reasons: []string{"artifact", "bootstrap"}, Outcome: "landed", TookS: f64(2.4)}},
		ReadyAfter: []StepReadyAfter{{Node: "e1", ReadyAfterS: 54.8}},
		Timings:    StepTimingsBlock{ReconcileS: f64(3.9), Readiness: map[string]float64{"e1": 54.8}, Push: map[string]float64{"s1": 2.4}, WholeS: 70.1},
		StartedAt:  "2026-10-02T09:14:30Z", EndedAt: "2026-10-02T09:15:40Z"}

	unchanged := NewDocument(OpTwinStep, ranSubject, nil)
	unchanged.BundleID = stepToID
	unchanged.Stage = resolved
	unchanged.Step = &StepBlock{From: stepBlock().From, To: stepBlock().To, Diff: json.RawMessage(`{"from":"change-1/cabled","to":"change-1/live","from_bundle_id":"` +
		stepFromID + `","to_bundle_id":"` + stepToID + `","computed":true,"unchanged":true,` +
		`"nodes":{"added":[],"removed":[],"changed":[]},"links":{"added":[],"removed":[]},"artifacts":{"changed":[]}}`),
		StepRunBlock: &StepRunBlock{Run: ShowRef{WorkflowID: "fylgja-step", RunID: stepRunID}, Outcome: "unchanged", State: "ready",
			Timings: StepTimingsBlock{WholeS: 1.8}, StartedAt: "2026-10-02T09:20:00Z", EndedAt: "2026-10-02T09:20:01.8Z"}}
	unchanged.Step.Reconcile.Skipped = true

	// The step across the marks: from the branch point, read on main, to the head, the two
	// stages derived from the branch, warned that it skips the two marks between.
	var skips List
	skips.AddStep(Warning, StepResolve, RuleStepStageSkipped, "change-1/head",
		"the step from change-1/branch-point to change-1/head skips stages cabled, live; the step is between the two bundles either way")
	head := headBlock()
	skipped := NewDocument(OpTwinStep, &Subject{Stage: head.Ref, Branch: head.Branch, At: head.At, RunID: stepRunID}, skips)
	skipped.BundleID = stepToID
	skipped.Stage = head
	skipped.Step = stepBlock()
	skipped.Step.From = StepSideBlock{Stage: showStage("branch-point", "", AtSourceBranchPoint), BundleID: stepFromID,
		At: "2026-10-16T17:20:19.944651+00:00"}
	skipped.Step.To = StepSideBlock{Stage: showStage("head", "", AtSourceHead), BundleID: stepToID,
		At: head.At, Branch: head.Branch}
	skipped.Step.Diff = json.RawMessage(strings.Replace(string(stepDiff),
		`"from":"change-1/cabled","to":"change-1/live"`, `"from":"change-1/branch-point","to":"change-1/head"`, 1))
	skipped.Step.StepRunBlock = stepped.Step.StepRunBlock

	return []labelledDocument{
		{"step dry run, refused", dry},
		{"step run, stepped", stepped},
		{"step run, diverged", diverged},
		{"step run, unchanged", unchanged},
		{"step run, from the branch point to the head, skipping the marks", skipped},
	}
}

// showStepDocuments are twin show of a stepped and of a diverged version 6 record, and of
// one that has not stepped.
func showStepDocuments() []labelledDocument {
	observed := "2026-10-02T09:14:01.000000Z"
	record := func(state string, step *ShowStep) *ShowRecord {
		return &ShowRecord{Branch: "change-1", At: "2026-10-16T17:30:00.000000+00:00", BundleID: stepToID, SchemaHash: "a8045729",
			Scope: "tag:fylgja", Mapping: dcimMapping, ObservedAt: &observed, Source: "intent", Run: ShowRef{WorkflowID: "fylgja-provision", RunID: "run-1"},
			WorkerVersion: "0.1.0-dev", RecordedAt: "2026-10-02T09:15:41Z", Nodes: 3,
			Stage: showStage("live", "after its configuration is live", AtSourceGiven), State: state, Step: step}
	}
	side := func(stage *ShowStage, id, at string) StepSideBlock {
		return StepSideBlock{Stage: stage, BundleID: id, At: at}
	}
	cabled := showStage("cabled", "after the link is cabled", AtSourceWritten)
	live := showStage("live", "after its configuration is live", AtSourceGiven)
	head := showStage("head", "", AtSourceHead)
	show := func(kind string, rec *ShowRecord) *Document {
		doc := NewDocument(OpTwinShow, nil, nil)
		doc.Show = &ShowBlock{Kind: kind, Service: ShowServiceOK, Record: rec,
			Host:  ShowHost{LabPresent: true, TwinDirPresent: true},
			Notes: []string{"the kind line"}}
		return doc
	}
	stepped := show(ShowKindSnapshot, record("ready", &ShowStep{Outcome: "stepped",
		From: side(cabled, stepFromID, "2026-10-16T17:25:30.118244+00:00"), To: side(live, stepToID, "2026-10-16T17:30:00.000000+00:00"),
		Run: ShowRef{WorkflowID: "fylgja-step", RunID: stepRunID}, Restarted: []string{"e1"},
		Pushed: []StepPushedEntry{{Node: "e1", Reasons: []string{"artifact", "restarted"}, Outcome: "landed", TookS: f64(1.6)}},
		Timings: &StepTimingsBlock{ReconcileS: f64(3.9), Readiness: map[string]float64{"e1": 54.8}, Push: map[string]float64{"e1": 1.6},
			WholeS: 71.2},
		StartedAt: "2026-10-02T09:14:30Z", EndedAt: "2026-10-02T09:15:41Z"}))
	diverged := show(ShowKindDiverged, record("diverged", &ShowStep{Outcome: "diverged",
		From: side(live, stepToID, "2026-10-16T17:30:00.000000+00:00"), To: side(head, strings.Repeat("51", 32), "2026-10-16T17:30:11.884302+00:00"),
		Run: ShowRef{WorkflowID: "fylgja-step", RunID: stepRunID}, Phase: "push",
		Pushed:    []StepPushedEntry{{Node: "e1", Reasons: []string{"artifact"}, Outcome: "refused", Rule: RulePushRefused}},
		StartedAt: "2026-10-02T10:00:00Z", EndedAt: "2026-10-02T10:00:09Z"}))
	unstepped := show(ShowKindSnapshot, record("ready", nil))
	return []labelledDocument{
		{"show of a stepped record", stepped},
		{"show of a diverged record", diverged},
		{"show of a version 6 record that has not stepped", unstepped},
	}
}

// listStepDocuments are stage list beside a diverged record and beside a ready one.
func listStepDocuments() []labelledDocument {
	branch := "change-1"
	cabled := cabledBlock()
	list := func(state string, towards *StageTowards) *Document {
		doc := NewDocument(OpStageList, nil, nil)
		doc.Stages = &StagesBlock{Branch: &branch, Rows: []StageRow{stageRow(cabled, true)},
			Record: &StageRecord{Ref: cabled.Ref, ProposedChange: StageChangeRef{ID: "pc-1", Branch: "change-1"},
				Label: cabled.Label, Branch: cabled.Branch, At: cabled.At, AtSource: cabled.AtSource, State: state, Towards: towards}}
		return doc
	}
	return []labelledDocument{
		{"list beside a diverged record", list("diverged", &StageTowards{Ref: "change-1/live"})},
		{"list beside a ready record", list("ready", nil)},
	}
}

// The step's documents, twin show's of a stepped and a diverged record, and stage list's
// beside one satisfy the newest contracts, every nullable key written. The newest are the
// module root's contracts/: M11's, extended additively by M12, with stage sides since 014.
func TestStepDocumentsSatisfySchema(t *testing.T) {
	schema := compileCurrentFindingsSchema(t)
	var all []labelledDocument
	all = append(all, stepDocuments()...)
	all = append(all, showStepDocuments()...)
	all = append(all, listStepDocuments()...)
	for _, c := range all {
		t.Run(c.label, func(t *testing.T) {
			mustValidate(t, schema, c.doc, c.label)
			mustCarryNoContent(t, c.doc, c.label)
		})
	}

	steps, shows, lists := stepDocuments(), showStepDocuments(), listStepDocuments()
	for _, c := range []struct {
		doc  *Document
		keys []string
		none []string
	}{
		// The dry run's block has no run fields; every list is written, declared null for none.
		{steps[0].doc, []string{`"step":{"from":{"stage":{"proposed_change":{"id":"pc-1","branch":"change-1"},"label":"cabled",`,
			`"to":{"stage":{"proposed_change":{"id":"pc-1","branch":"change-1"},"label":"live",`, `"subject":{"branch":"change-1",`,
			`"stage":{"ref":"change-1/live","branch":"change-1","label":"live",`,
			`"branch":"change-1"}`, `"reconcile":{"added":[],"deleted":[],"recreated":[],"restarted":["e1"],`,
			`"declared":"restart","reported":"restart"`, `"push_plan":[{"node":"e1","reasons":["artifact","restarted"]}`,
			`"allow_restart":false`, `"status":"rejected"`}, []string{`"run"`, `"outcome"`, `"pushed"`, `"timings"`}},
		{steps[1].doc, []string{`"run":{"workflow_id":"fylgja-step","run_id":"` + stepRunID + `"}`, `"outcome":"stepped"`,
			`"state":"ready"`, `"ready_after":[{"node":"e1","ready_after_s":54.8}]`, `"whole_s":71.2`}, []string{`"phase"`}},
		{steps[2].doc, []string{`"status":"diverged"`, `"phase":"push"`, `"outcome":"refused","rule":"push.refused"`,
			`{"node":"s2","declared":null,"reported":"create"}`}, nil},
		{steps[3].doc, []string{`"push_plan":[]`, `"pushed":[]`, `"ready_after":[]`, `"nodes":[]`, `"skipped":true`, `"timings":{"whole_s":1.8}`}, nil},
		{steps[4].doc, []string{`"from":{"stage":{"proposed_change":{"id":"pc-1","branch":"change-1"},"label":"branch-point","description":"","at_source":"branch_point"}`,
			`"to":{"stage":{"proposed_change":{"id":"pc-1","branch":"change-1"},"label":"head","description":"","at_source":"head"}`,
			`"diff":{"from":"change-1/branch-point","to":"change-1/head",`, `"rule":"step.stage.skipped"`, `"status":"ok"`}, nil},
		{shows[0].doc, []string{`"state":"ready"`, `"step":{"outcome":"stepped",`, `"restarted":["e1"]`}, []string{`"phase"`}},
		{shows[1].doc, []string{`"kind":"diverged"`, `"state":"diverged"`, `"phase":"push"`, `"restarted":[]`,
			`"to":{"stage":{"proposed_change":{"id":"pc-1","branch":"change-1"},"label":"head","description":"","at_source":"head"}`}, nil},
		{shows[2].doc, []string{`"state":"ready"`}, []string{`"step"`}},
		{lists[0].doc, []string{`"twin":true`, `"state":"diverged","towards":{"ref":"change-1/live"}`}, nil},
		{lists[1].doc, []string{`"state":"ready","towards":null`}, nil},
	} {
		b := string(mustMarshal(t, c.doc))
		if !containsAll(b, c.keys) {
			t.Errorf("%s does not carry every one of %q: %s", c.doc.Operation, c.keys, b)
		}
		for _, k := range c.none {
			if strings.Contains(b, k) {
				t.Errorf("%s carries %s: %s", c.doc.Operation, k, b)
			}
		}
	}

	// The blocks are the contract's, so a misshapen one is refused: a step block with no
	// reconcile node's declaration, a show step with no restarted list, a list record whose
	// towards names no stage, a list record with no state, and a side's stage with an
	// at_source outside the enum.
	bad := stepDocuments()[0].doc
	raw := strings.Replace(string(mustMarshal(t, bad)), `"declared":"restart",`, ``, 1)
	if err := schema.Validate(mustAny(t, []byte(raw))); err == nil {
		t.Error("a plan node with no declared key satisfied the step schema")
	}
	shown := strings.Replace(string(mustMarshal(t, showStepDocuments()[0].doc)), `"restarted":["e1"],`, ``, 1)
	if err := schema.Validate(mustAny(t, []byte(shown))); err == nil {
		t.Error("a show step with no restarted list satisfied the show schema")
	}
	listed := strings.Replace(string(mustMarshal(t, listStepDocuments()[0].doc)), `{"ref":"change-1/live"}`, `{}`, 1)
	if err := schema.Validate(mustAny(t, []byte(listed))); err == nil {
		t.Error("a towards with no ref satisfied the stages schema")
	}
	stateless := strings.Replace(string(mustMarshal(t, listStepDocuments()[1].doc)), `"state":"ready",`, ``, 1)
	if err := schema.Validate(mustAny(t, []byte(stateless))); err == nil {
		t.Error("a list record with no state satisfied the stages schema")
	}
	guessed := stepDocuments()[0].doc
	guessed.Step.To.Stage.AtSource = "guessed"
	if err := schema.Validate(mustAny(t, mustMarshal(t, guessed))); err == nil {
		t.Error("a step side's stage with at_source guessed satisfied the step schema")
	}
}

// The step's wait in twin step's document and in twin show's record block: the budget alone on
// the dry run, how it
// ended once the run closed; in show, the wait of a version 5 record, null while it has not
// run, and no key for a version 4 record. Each satisfies the newest contracts, under contracts/.
func TestStepWaitDocumentsSatisfySchema(t *testing.T) {
	schema := compileCurrentFindingsSchema(t)
	neighbor := StepWaitFailing{Rule: RuleVerifyNeighbor, Object: "s1:ethernet-1/3",
		Message: "node s1 (172.20.20.4:57400): port ethernet-1/3 sees no neighbour at /system/lldp/interface[name=ethernet-1/3]/neighbor; link e1:Ethernet3|s1:ethernet-1/3 names e1 Ethernet3 at its far end"}
	steps := stepDocuments()
	waits := []struct {
		label string
		doc   *Document
		wait  *StepWaitBlock
		keys  []string
		none  []string
	}{
		{"dry run", steps[0].doc, &StepWaitBlock{BudgetS: 120}, []string{`"wait":{"budget_s":120}`},
			[]string{`"reads"`, `"failing"`}},
		{"settled", steps[1].doc, &StepWaitBlock{BudgetS: 120, Outcome: "settled", Reads: 2, AfterS: 2.4},
			[]string{`"wait":{"budget_s":120,"outcome":"settled","reads":2,"after_s":2.4,"failing":[]}`}, nil},
		{"expired", steps[2].doc, &StepWaitBlock{BudgetS: 120, Outcome: "expired", Reads: 58, AfterS: 120,
			Failing: []StepWaitFailing{neighbor}}, []string{`"outcome":"expired","reads":58,"after_s":120,"failing":[{"rule":"verify.neighbor","object":"s1:ethernet-1/3","message":"node s1`}, nil},
		{"cancelled", steps[3].doc, &StepWaitBlock{BudgetS: 30, Outcome: "cancelled", Reads: 7, AfterS: 12.4},
			[]string{`"wait":{"budget_s":30,"outcome":"cancelled","reads":7,"after_s":12.4,"failing":[]}`}, nil},
		{"incomplete, the activity failed", stepDocuments()[1].doc, &StepWaitBlock{BudgetS: 120, Outcome: "incomplete",
			Failing: []StepWaitFailing{{Rule: RuleOperationFailed, Object: "/state/twin/twin.json", Message: "reading the twin's record for the step's wait: disk full"}}},
			[]string{`"outcome":"incomplete","reads":0,"after_s":0,"failing":[{"rule":"operation.failed"`}, nil},
	}
	for _, c := range waits {
		t.Run("step "+c.label, func(t *testing.T) {
			c.doc.Step.Wait = c.wait
			mustValidate(t, schema, c.doc, c.label)
			mustCarryNoContent(t, c.doc, c.label)
			b := string(mustMarshal(t, c.doc))
			if !containsAll(b, c.keys) {
				t.Errorf("does not carry every one of %q: %s", c.keys, b)
			}
			for _, k := range c.none {
				if strings.Contains(b, k) {
					t.Errorf("carries %s: %s", k, b)
				}
			}
		})
	}
	// A run that closed without its wait carries no wait key, as M11's document.
	if b := string(mustMarshal(t, stepDocuments()[1].doc)); strings.Contains(b, `"wait"`) {
		t.Errorf("a step document with no wait carries the key: %s", b)
	}

	shown := func(known bool, wait *ShowWait) *Document {
		doc := showStepDocuments()[0].doc
		doc.Show.Record.Step.WaitKnown, doc.Show.Record.Step.Wait = known, wait
		return doc
	}
	for _, c := range []struct {
		label string
		doc   *Document
		keys  []string
		none  []string
	}{
		{"settled", shown(true, &ShowWait{Outcome: "settled", BudgetS: 120, Reads: 2, AfterS: 2.4}),
			[]string{`"wait":{"outcome":"settled","budget_s":120,"reads":2,"after_s":2.4,"failing":[]}`}, nil},
		{"expired", shown(true, &ShowWait{Outcome: "expired", BudgetS: 120, Reads: 58, AfterS: 120,
			Failing: []ShowWaitFailing{{Rule: RuleVerifyNeighbor, Object: "s1:ethernet-1/3"}}}),
			[]string{`"failing":[{"rule":"verify.neighbor","object":"s1:ethernet-1/3"}]`}, []string{`"message":"node s1`}},
		{"cancelled", shown(true, &ShowWait{Outcome: "cancelled", BudgetS: 120, Reads: 7, AfterS: 12.4}),
			[]string{`"outcome":"cancelled"`}, nil},
		{"incomplete", shown(true, &ShowWait{Outcome: "incomplete", BudgetS: 120,
			Failing: []ShowWaitFailing{{Rule: RuleOperationFailed, Object: "e1"}}}), []string{`"outcome":"incomplete","budget_s":120,"reads":0`}, nil},
		{"a version 5 record whose wait has not run", shown(true, nil), []string{`"wait":null`}, nil},
		{"a version 4 record", shown(false, nil), []string{`"step":{"outcome":"stepped",`}, []string{`"wait"`}},
	} {
		t.Run("show "+c.label, func(t *testing.T) {
			mustValidate(t, schema, c.doc, c.label)
			b := string(mustMarshal(t, c.doc))
			if !containsAll(b, c.keys) {
				t.Errorf("does not carry every one of %q: %s", c.keys, b)
			}
			for _, k := range c.none {
				if strings.Contains(b, k) {
					t.Errorf("carries %s: %s", k, b)
				}
			}
		})
	}

	// The blocks are the contract's: a step wait's failing entry with no message, and a show
	// wait's entry that carries one, are refused.
	doc := stepDocuments()[2].doc
	doc.Step.Wait = waits[2].wait
	raw := strings.Replace(string(mustMarshal(t, doc)), `,"message":"`+neighbor.Message+`"`, ``, 1)
	if err := schema.Validate(mustAny(t, []byte(raw))); err == nil {
		t.Error("a step wait's failing entry with no message satisfied the step schema")
	}
	withMessage := strings.Replace(string(mustMarshal(t, shown(true, &ShowWait{Outcome: "expired", BudgetS: 120, Reads: 58, AfterS: 120,
		Failing: []ShowWaitFailing{{Rule: RuleVerifyNeighbor, Object: "s1:ethernet-1/3"}}}))),
		`"object":"s1:ethernet-1/3"}`, `"object":"s1:ethernet-1/3","message":"sees no neighbour"}`, 1)
	if err := schema.Validate(mustAny(t, []byte(withMessage))); err == nil {
		t.Error("a show wait's failing entry with a message satisfied the show schema")
	}
}

// stepLoss is the example step's loss (016): n1-loop measured, n2-loop not started, n3-loop
// the target adds and n4-loop it drops.
func stepLoss() *StepLoss {
	return &StepLoss{Basis: "container", Probes: []StepProbeLoss{
		{Probe: "n1-loop", From: "clab-fylgja-n1-loop-a", To: "clab-fylgja-n1-loop-b", Outcome: "measured", Sent: 312, Lost: 5,
			LongestGapS: 1.0},
		{Probe: "n2-loop", From: "clab-fylgja-n2-loop-a", To: "clab-fylgja-n2-loop-b", Outcome: "not_started",
			Rule: RuleFlowStartFailed, Message: "probe n2-loop: the flow did not start in clab-fylgja-n2-loop-a: exit 1"}},
		Added: []string{"n3-loop"}, Dropped: []string{"n4-loop"}}
}

// The step document's loss (016): null on the dry run and on a run that closed without it,
// and once the flows were read their figures per probe, a flow not started, one interrupted
// on a diverged step at the phase flows, and a step with no probe's empty loss. Each
// satisfies the current contract; 019's copy, which has no loss, refuses each that carries
// one, and accepts the null taken out (TestA019DocumentIsUnchanged).
func TestStepLossDocuments(t *testing.T) {
	schema := compileCurrentFindingsSchema(t)
	v019 := compileFeatureFindingsSchema(t, contract019, currentResources...)
	steps := stepDocuments()

	for _, c := range []struct {
		label string
		doc   *Document
		keys  []string
	}{
		{"dry run", steps[0].doc, []string{`"loss":null`}},
		{"run closed without its flows", steps[3].doc, []string{`"loss":null`}},
	} {
		t.Run(c.label, func(t *testing.T) {
			mustValidate(t, schema, c.doc, c.label)
			if b := string(mustMarshal(t, c.doc)); !containsAll(b, c.keys) {
				t.Errorf("does not carry every one of %q: %s", c.keys, b)
			}
		})
	}

	stepped := stepDocuments()[1].doc
	stepped.Step.Loss = stepLoss()

	interrupted := stepDocuments()[2].doc
	interrupted.Step.Phase = "flows"
	interrupted.Step.Loss = &StepLoss{Basis: "container", Probes: []StepProbeLoss{{Probe: "n1-loop",
		From: "clab-fylgja-n1-loop-a", To: "clab-fylgja-n1-loop-b", Outcome: "interrupted", Sent: 40, Lost: 12, LongestGapS: 12.0}}}

	notRead := stepDocuments()[1].doc
	notRead.Step.Loss = &StepLoss{Basis: "container", Probes: []StepProbeLoss{{Probe: "n1-loop",
		From: "clab-fylgja-n1-loop-a", To: "clab-fylgja-n1-loop-b", Outcome: "not_read", Rule: RuleFlowReadFailed,
		Message: "probe n1-loop: the flow could not be read in clab-fylgja-n1-loop-a: exit 1"}}}

	none := stepDocuments()[3].doc
	none.Step.Loss = &StepLoss{Basis: "container"}

	for _, c := range []struct {
		label string
		doc   *Document
		keys  []string
	}{
		{"measured, not started, added and dropped", stepped, []string{`"loss":{"basis":"container","probes":[{"probe":"n1-loop",` +
			`"from":"clab-fylgja-n1-loop-a","to":"clab-fylgja-n1-loop-b","outcome":"measured","sent":312,"lost":5,"longest_gap_s":1}`,
			`"outcome":"not_started","sent":0,"lost":0,"longest_gap_s":0,"rule":"flow.start.failed","message":"probe n2-loop:`,
			`"added":["n3-loop"],"dropped":["n4-loop"]}`}},
		{"interrupted, diverged at flows", interrupted, []string{`"phase":"flows"`, `"outcome":"interrupted","sent":40,"lost":12,"longest_gap_s":12}`}},
		{"not read", notRead, []string{`"outcome":"not_read"`, `"rule":"flow.read.failed"`}},
		{"no probe", none, []string{`"loss":{"basis":"container","probes":[],"added":[],"dropped":[]}`}},
	} {
		t.Run(c.label, func(t *testing.T) {
			mustValidate(t, schema, c.doc, c.label)
			mustCarryNoContent(t, c.doc, c.label)
			b := mustMarshal(t, c.doc)
			if !containsAll(string(b), c.keys) {
				t.Errorf("does not carry every one of %q: %s", c.keys, b)
			}
			if err := v019.Validate(mustAny(t, b)); err == nil {
				t.Errorf("019's contract accepts a step document carrying a loss: %s", b)
			}
		})
	}

	// The loss is the contract's: a basis other than container, an outcome outside the enum, a
	// probe with no longest gap, and a loss with no dropped list are each refused.
	for _, c := range []struct{ label, old, new string }{
		{"basis", `"basis":"container"`, `"basis":"hardware"`},
		{"outcome", `"outcome":"measured"`, `"outcome":"guessed"`},
		{"longest gap", `,"longest_gap_s":1}`, `}`},
		{"dropped", `,"dropped":["n4-loop"]`, ``},
	} {
		raw := strings.Replace(string(mustMarshal(t, stepped)), c.old, c.new, 1)
		if raw == string(mustMarshal(t, stepped)) {
			t.Fatalf("%s: %s is not in the document", c.label, c.old)
		}
		if err := schema.Validate(mustAny(t, []byte(raw))); err == nil {
			t.Errorf("a loss with its %s changed satisfied the step schema: %s", c.label, raw)
		}
	}
}
