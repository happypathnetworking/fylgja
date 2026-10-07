package findings

import (
	"encoding/json"
	"strings"
	"testing"
)

// The step's documents and the two M11 extensions of M10's, as the contracts spell them.

var (
	stepFromID = strings.Repeat("34", 32)
	stepToID   = strings.Repeat("ee", 32)
	stepRunID  = "01a1b2c3-0000-7000-8000-000000000002"
)

func demoWaypoint(sequence int, description string) *ShowWaypoint {
	return &ShowWaypoint{Series: "demo", Sequence: sequence, Description: description, AtSource: "written"}
}

func f64(v float64) *float64 { return &v }

// stepDiff is M10's pair JSON for the example step: e1 and s1 cabled, s1's bootstrap and
// both artifacts moved.
var stepDiff = json.RawMessage(`{"from":"demo/1","to":"demo/2","from_bundle_id":"` + stepFromID +
	`","to_bundle_id":"` + stepToID + `","computed":true,"unchanged":false,` +
	`"nodes":{"added":[],"removed":[],"changed":[{"node":"s1","reasons":["bootstrap","mapping"]}]},` +
	`"links":{"added":[{"id":"e1:Ethernet3|s1:ethernet-1/3","a":{"node":"e1","port":"eth3"},"b":{"node":"s1","port":"e1-3"}}],"removed":[]},` +
	`"artifacts":{"changed":[{"node":"e1","name":"device-config","from":"43e8fd0c2de5f4646f74a51d34742824","to":"9a0177b2e8c1d4f5a6b7c8d9e0f1a2b3"}]}}`)

// stepBlock is the example step's block as the dry run carries it, with no run fields.
func stepBlock() *StepBlock {
	restart, live := "restart", "live"
	return &StepBlock{
		From: StepSideBlock{Waypoint: demoWaypoint(1, "before the change"), BundleID: stepFromID, At: "2026-09-28T15:00:01.123456+00:00"},
		To: StepSideBlock{Waypoint: demoWaypoint(2, "after the first cut-over"), BundleID: stepToID,
			At: "2026-09-28T15:20:44.000000+00:00", Branch: "change-1"},
		Diff: stepDiff,
		Reconcile: StepReconcileBlock{Restarted: []string{"e1"}, LinksAdded: []string{"e1:eth3 -- s1:e1-3"},
			Nodes: []StepPlanNode{{Node: "e1", Declared: &restart, Reported: "restart", Reason: "added link"},
				{Node: "s1", Declared: &live, Reported: "live", Reason: "added link"}}},
		PushPlan: []StepPushPlanEntry{{Node: "e1", Reasons: []string{"artifact", "restarted"}},
			{Node: "s1", Reasons: []string{"artifact", "bootstrap"}}},
	}
}

// stepDocuments are twin step's documents: the dry run refused, a stepped run, a diverged
// one, and an unchanged one whose run pushed and awaited nobody.
func stepDocuments() []labelledDocument {
	subject := func() *Subject {
		return &Subject{Waypoint: "demo/2", Branch: "change-1", At: "2026-09-28T15:20:44.000000+00:00"}
	}
	resolved := &WaypointBlock{Series: "demo", Sequence: 2, Branch: "change-1", At: "2026-09-28T15:20:44.000000+00:00",
		AtSource: "written", Description: "after the first cut-over"}

	var restart List
	restart.AddStep(Rejection, StepCompare, RuleStepRestartRequired, "e1",
		"containerlab would restart e1 (added link; package arista_eos declares restart): it loses its running state and its push until the step pushes it again; give --allow-restart to proceed, or --dry-run to see the step")
	dry := NewDocument(OpTwinStep, subject(), restart)
	dry.BundleID = stepToID
	dry.Waypoint = resolved
	dry.Step = stepBlock()
	dry.DryRun = &DryRunBlock{Nodes: []DryRunNode{{Name: "e1", Image: "ceos:4.32.0.2F", PSP: "arista_eos", MemoryMB: 2048,
		Artifact: &DryRunArtifact{Name: "device-config", ContentType: "text/plain", Checksum: m5Checksum, Size: 900}}},
		MemorySumMB: 2048, Host: DryRunHost{LabPresent: true, TwinDirPresent: true}, Verdict: VerdictRefused}

	ranSubject := subject()
	ranSubject.RunID = stepRunID
	stepped := NewDocument(OpTwinStep, ranSubject, nil)
	stepped.BundleID = stepToID
	stepped.Waypoint = resolved
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
		"step run "+stepRunID+" towards waypoint demo/2 (bundle ee…) stopped at phase push: landed s1; not landed e1 (push.refused); the twin is up and diverged at waypoint demo/1 (bundle 34…), its record says so, and it accepts only fylgja twin destroy")
	diverged := NewDocument(OpTwinStep, ranSubject, stopped)
	diverged.Status = StatusDiverged
	diverged.BundleID = stepToID
	diverged.Waypoint = resolved
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
	unchanged.Waypoint = resolved
	unchanged.Step = &StepBlock{From: stepBlock().From, To: stepBlock().To, Diff: json.RawMessage(`{"from":"demo/1","to":"demo/2","from_bundle_id":"` +
		stepFromID + `","to_bundle_id":"` + stepToID + `","computed":true,"unchanged":true,` +
		`"nodes":{"added":[],"removed":[],"changed":[]},"links":{"added":[],"removed":[]},"artifacts":{"changed":[]}}`),
		StepRunBlock: &StepRunBlock{Run: ShowRef{WorkflowID: "fylgja-step", RunID: stepRunID}, Outcome: "unchanged", State: "ready",
			Timings: StepTimingsBlock{WholeS: 1.8}, StartedAt: "2026-10-02T09:20:00Z", EndedAt: "2026-10-02T09:20:01.8Z"}}
	unchanged.Step.Reconcile.Skipped = true

	return []labelledDocument{
		{"step dry run, refused", dry},
		{"step run, stepped", stepped},
		{"step run, diverged", diverged},
		{"step run, unchanged", unchanged},
	}
}

// showStepDocuments are twin show of a stepped and of a diverged version 4 record.
func showStepDocuments() []labelledDocument {
	observed := "2026-10-02T09:14:01.000000Z"
	record := func(state string, step *ShowStep) *ShowRecord {
		return &ShowRecord{Branch: "change-1", At: "2026-09-28T15:20:44.000000+00:00", BundleID: stepToID, SchemaHash: "4d5b37aa",
			ContractVersion: "0.2", ObservedAt: &observed, Source: "intent", Run: ShowRef{WorkflowID: "fylgja-provision", RunID: "run-1"},
			WorkerVersion: "0.1.0-dev", RecordedAt: "2026-10-02T09:15:41Z", Nodes: 3,
			Waypoint: demoWaypoint(2, "after the first cut-over"), State: state, Step: step}
	}
	side := func(sequence int, id, at string) StepSideBlock {
		return StepSideBlock{Waypoint: demoWaypoint(sequence, ""), BundleID: id, At: at}
	}
	show := func(kind string, rec *ShowRecord) *Document {
		doc := NewDocument(OpTwinShow, nil, nil)
		doc.Show = &ShowBlock{Kind: kind, Service: ShowServiceOK, Record: rec,
			Host:  ShowHost{LabPresent: true, TwinDirPresent: true},
			Notes: []string{"the kind line"}}
		return doc
	}
	stepped := show(ShowKindPinned, record("ready", &ShowStep{Outcome: "stepped",
		From: side(1, stepFromID, "2026-09-28T15:00:01.123456+00:00"), To: side(2, stepToID, "2026-09-28T15:20:44.000000+00:00"),
		Run: ShowRef{WorkflowID: "fylgja-step", RunID: stepRunID}, Restarted: []string{"e1"},
		Pushed: []StepPushedEntry{{Node: "e1", Reasons: []string{"artifact", "restarted"}, Outcome: "landed", TookS: f64(1.6)}},
		Timings: &StepTimingsBlock{ReconcileS: f64(3.9), Readiness: map[string]float64{"e1": 54.8}, Push: map[string]float64{"e1": 1.6},
			WholeS: 71.2},
		StartedAt: "2026-10-02T09:14:30Z", EndedAt: "2026-10-02T09:15:41Z"}))
	diverged := show(ShowKindDiverged, record("diverged", &ShowStep{Outcome: "diverged",
		From: side(2, stepToID, "2026-09-28T15:20:44.000000+00:00"), To: side(3, strings.Repeat("51", 32), "2026-09-29T08:00:00Z"),
		Run: ShowRef{WorkflowID: "fylgja-step", RunID: stepRunID}, Phase: "push",
		Pushed:    []StepPushedEntry{{Node: "e1", Reasons: []string{"artifact"}, Outcome: "refused", Rule: RulePushRefused}},
		StartedAt: "2026-10-02T10:00:00Z", EndedAt: "2026-10-02T10:00:09Z"}))
	unstepped := show(ShowKindPinned, record("ready", nil))
	return []labelledDocument{
		{"show of a stepped record", stepped},
		{"show of a diverged record", diverged},
		{"show of a version 4 record that has not stepped", unstepped},
	}
}

// listStepDocuments are waypoint list beside a diverged record and beside a ready one.
func listStepDocuments() []labelledDocument {
	demo := "demo"
	row := WaypointRow{WaypointBlock: WaypointBlock{Series: "demo", Sequence: 2, Branch: "change-1",
		At: "2026-09-28T15:20:44.000000+00:00", AtSource: "written", Description: "after the first cut-over"}, Twin: true}
	list := func(state string, towards *WaypointTowards) *Document {
		doc := NewDocument(OpWaypointList, nil, nil)
		doc.Waypoints = &WaypointsBlock{Series: &demo, Waypoints: []WaypointRow{row},
			Record: &WaypointRecord{Series: "demo", Sequence: 2, Branch: "change-1", At: "2026-09-28T15:20:44.000000+00:00",
				AtSource: "written", State: state, Towards: towards}}
		return doc
	}
	return []labelledDocument{
		{"list beside a diverged record", list("diverged", &WaypointTowards{Series: "demo", Sequence: 3})},
		{"list beside a ready record", list("ready", nil)},
	}
}

// The step's documents, twin show's of a stepped and a diverged record, and waypoint list's
// beside one satisfy the newest contracts, every nullable key written. The newest are the
// module root's contracts/, M11's extended additively.
// M10's documents stay M10's (TestM10DocumentsSatisfySchema, unchanged).
func TestStepDocumentsSatisfySchema(t *testing.T) {
	schema := compileFeatureFindingsSchema(t, currentContract, "show.schema.json", "waypoints.schema.json", "step.schema.json", "verify.schema.json")
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
		{steps[0].doc, []string{`"step":{"from":{"waypoint":{"series":"demo","sequence":1,`, `"to":{"waypoint":{"series":"demo","sequence":2,`,
			`"branch":"change-1"}`, `"reconcile":{"added":[],"deleted":[],"recreated":[],"restarted":["e1"],`,
			`"declared":"restart","reported":"restart"`, `"push_plan":[{"node":"e1","reasons":["artifact","restarted"]}`,
			`"allow_restart":false`, `"status":"rejected"`}, []string{`"run"`, `"outcome"`, `"pushed"`, `"timings"`}},
		{steps[1].doc, []string{`"run":{"workflow_id":"fylgja-step","run_id":"` + stepRunID + `"}`, `"outcome":"stepped"`,
			`"state":"ready"`, `"ready_after":[{"node":"e1","ready_after_s":54.8}]`, `"whole_s":71.2`}, []string{`"phase"`}},
		{steps[2].doc, []string{`"status":"diverged"`, `"phase":"push"`, `"outcome":"refused","rule":"push.refused"`,
			`{"node":"s2","declared":null,"reported":"create"}`}, nil},
		{steps[3].doc, []string{`"push_plan":[]`, `"pushed":[]`, `"ready_after":[]`, `"nodes":[]`, `"skipped":true`, `"timings":{"whole_s":1.8}`}, nil},
		{shows[0].doc, []string{`"state":"ready"`, `"step":{"outcome":"stepped",`, `"restarted":["e1"]`}, []string{`"phase"`}},
		{shows[1].doc, []string{`"kind":"diverged"`, `"state":"diverged"`, `"phase":"push"`, `"restarted":[]`}, nil},
		{shows[2].doc, []string{`"state":"ready"`}, []string{`"step"`}},
		{lists[0].doc, []string{`"state":"diverged","towards":{"series":"demo","sequence":3}`}, nil},
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
	// reconcile node's declaration, a show step with no restarted list, and a list record
	// whose towards names no sequence.
	bad := stepDocuments()[0].doc
	raw := strings.Replace(string(mustMarshal(t, bad)), `"declared":"restart",`, ``, 1)
	if err := schema.Validate(mustAny(t, []byte(raw))); err == nil {
		t.Error("a plan node with no declared key satisfied the step schema")
	}
	shown := strings.Replace(string(mustMarshal(t, showStepDocuments()[0].doc)), `"restarted":["e1"],`, ``, 1)
	if err := schema.Validate(mustAny(t, []byte(shown))); err == nil {
		t.Error("a show step with no restarted list satisfied the show schema")
	}
	listed := strings.Replace(string(mustMarshal(t, listStepDocuments()[0].doc)), `,"sequence":3`, ``, 1)
	if err := schema.Validate(mustAny(t, []byte(listed))); err == nil {
		t.Error("a towards with no sequence satisfied the waypoints schema")
	}
}

// A version 3 record's list block is M10's, key for key: no state and no towards, so
// M10's own contract, which forbids additional properties, still accepts it.
func TestAVersion3ListRecordIsM10s(t *testing.T) {
	m10 := compileFeatureFindingsSchema(t, "008-waypoints", "show.schema.json", "waypoints.schema.json")
	doc := listStepDocuments()[0].doc
	doc.Waypoints.Record.State, doc.Waypoints.Record.Towards = "", nil
	b := mustMarshal(t, doc)
	if strings.Contains(string(b), "state") || strings.Contains(string(b), "towards") {
		t.Errorf("a version 3 record's list block names state or towards: %s", b)
	}
	mustValidateBytes(t, m10, b, "a version 3 list record against M10's contract")
}

// The step's wait in twin step's document and in twin show's record block: the budget alone on
// the dry run, how it
// ended once the run closed; in show, the wait of a version 5 record, null while it has not
// run, and no key for a version 4 record. Each satisfies the newest contracts, under contracts/.
func TestStepWaitDocumentsSatisfySchema(t *testing.T) {
	schema := compileFeatureFindingsSchema(t, currentContract, "show.schema.json", "waypoints.schema.json", "step.schema.json", "verify.schema.json")
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
