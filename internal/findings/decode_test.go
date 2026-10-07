package findings

import (
	"bytes"
	"encoding/json"
	"testing"
)

// M13's client reads the document out of a frame and decodes it into Document, so every
// document a command writes must come back from a decode as the bytes it went out as. A
// MarshalJSON that writes a nil list as [] is faithful in bytes: the decoded empty list is
// written as [] again. ShowStep's WaitKnown is the one field the encoding alone does not
// carry; its UnmarshalJSON reads it from the wait key.

// decodeDocuments is every document shape this package's tests build, and the shapes M12
// added that no builder covers: a show of a version 5 record with each wait and with wait
// null, a step document with each wait, and a verify block.
func decodeDocuments() []labelledDocument {
	var docs []labelledDocument
	for _, set := range [][]labelledDocument{
		m1Documents(), m2Documents(), m4Documents(), m5Documents(), m10Documents(),
		listAndPlanDocuments(), stepDocuments(), showStepDocuments(), listStepDocuments(),
	} {
		docs = append(docs, set...)
	}

	shown := func(known bool, wait *ShowWait) *Document {
		doc := showStepDocuments()[0].doc
		doc.Show.Record.Step.WaitKnown, doc.Show.Record.Step.Wait = known, wait
		return doc
	}
	for _, c := range []struct {
		label string
		wait  *ShowWait
	}{
		{"settled", &ShowWait{Outcome: "settled", BudgetS: 120, Reads: 2, AfterS: 2.4}},
		{"expired", &ShowWait{Outcome: "expired", BudgetS: 120, Reads: 58, AfterS: 120,
			Failing: []ShowWaitFailing{{Rule: RuleVerifyNeighbor, Object: "s1:ethernet-1/3"}}}},
		{"cancelled", &ShowWait{Outcome: "cancelled", BudgetS: 120, Reads: 7, AfterS: 12.4}},
		{"incomplete", &ShowWait{Outcome: "incomplete", BudgetS: 120,
			Failing: []ShowWaitFailing{{Rule: RuleOperationFailed, Object: "e1"}}}},
		{"null, a version 5 record whose wait has not run", nil},
	} {
		docs = append(docs, labelledDocument{"show of a version 5 record, wait " + c.label, shown(true, c.wait)})
	}
	docs = append(docs, labelledDocument{"show of a version 4 record, no wait key", shown(false, nil)})

	stepWith := func(i int, wait *StepWaitBlock) *Document {
		doc := stepDocuments()[i].doc
		doc.Step.Wait = wait
		return doc
	}
	for _, c := range []struct {
		label string
		doc   *Document
	}{
		{"the budget alone, on the dry run", stepWith(0, &StepWaitBlock{BudgetS: 120})},
		{"settled", stepWith(1, &StepWaitBlock{BudgetS: 120, Outcome: "settled", Reads: 2, AfterS: 2.4})},
		{"expired", stepWith(2, &StepWaitBlock{BudgetS: 120, Outcome: "expired", Reads: 58, AfterS: 120,
			Failing: []StepWaitFailing{{Rule: RuleVerifyNeighbor, Object: "s1:ethernet-1/3",
				Message: "node s1 (172.20.20.4:57400): port ethernet-1/3 sees no neighbour"}}})},
		{"cancelled", stepWith(3, &StepWaitBlock{BudgetS: 30, Outcome: "cancelled", Reads: 7, AfterS: 12.4})},
		{"incomplete", stepWith(1, &StepWaitBlock{BudgetS: 120, Outcome: "incomplete",
			Failing: []StepWaitFailing{{Rule: RuleOperationFailed, Object: "/state/twin/twin.json",
				Message: "reading the twin's record for the step's wait: disk full"}}})},
	} {
		docs = append(docs, labelledDocument{"step document, wait " + c.label, c.doc})
	}

	return append(docs, verifyDocuments()...)
}

// m1Documents are M1's operations as TestEveryOperationRendersAValidDocument builds them,
// with a finding located in a file and a schema check that names the waypoint kind.
func m1Documents() []labelledDocument {
	located := List{{Severity: Warning, Rule: RulePSPResourcesImplausible, Object: "nokia_srlinux",
		Message: "resources look implausible", Location: &Location{File: "psp/x.yaml", Line: 12}}}
	compiled := NewDocument(OpCompile, &Subject{CTM: "ctm.json", Out: "/tmp/bundle"}, nil)
	compiled.BundleID = stepToID
	checked := NewDocument(OpSchemaCheck, &Subject{Branch: "fylgja-fixture"}, nil)
	checked.Verified = &Verified{ContractVersion: "0.2",
		Generics:  []GenericKinds{{Generic: "FylgjaDevice", Kinds: []string{"NetworkDevice"}}},
		Waypoints: &WaypointsVerified{Kind: "FylgjaWaypoint", Present: true, File: "schema/fylgja-waypoint.yaml"}}
	return []labelledDocument{
		{"intent read ok", NewDocument(OpIntentRead, &Subject{Branch: "fylgja-fixture", CTM: "ctm.json"}, nil)},
		{"twin compile ok", compiled},
		{"twin compile error", ErrorDocument(OpCompile, &Subject{Out: "/tmp/b"}, "--out is required")},
		{"schema check ok", checked},
		{"psp validate with location", NewDocument(OpPSPValidate, &Subject{Files: []string{"psp/x.yaml"}}, located)},
	}
}

// verifyDocuments are twin verify's documents: a twin that conforms, read with --wait, and a
// diverged one with a node unread, every nullable key written.
func verifyDocuments() []labelledDocument {
	str := func(s string) *string { return &s }
	num := func(n int) *int { return &n }
	read := "n1"
	enabled := "enable"
	held := NewDocument(OpTwinVerify, nil, nil)
	held.Verify = &VerifyBlock{
		Twin:   VerifyTwin{BundleID: stepToID, Waypoint: demoWaypoint(2, "after the first cut-over"), State: "ready", Source: "intent", Nodes: 2},
		ReadAt: "2026-10-03T12:00:00Z",
		Nodes: []VerifyNode{{Node: "n1", PSP: "nokia_srlinux", Addr: str("172.20.20.2:57400"), Read: true,
			HostName: VerifyAssertion{Path: "/system/name/host-name", Expected: "n1", Outcome: "held", Read: &read},
			Ports: []VerifyPort{{Port: "ethernet-1/1", NodeName: "ethernet-1/1", Path: "/interface[name=ethernet-1/1]/admin-state",
				Expected: "enable", Outcome: "held", Read: &enabled}}}},
		Links: []VerifyLink{{ID: "n1:ethernet-1/1|n2:ethernet-1/1",
			A: VerifyEnd{Node: "n1", Port: "ethernet-1/1", NodeName: "ethernet-1/1", Path: "/system/lldp/interface[name=ethernet-1/1]/neighbor",
				Expected: VerifyNodePort{Node: "n2", Port: "ethernet-1/1"}, Outcome: "held",
				Read: []VerifyNodePort{{Node: "n2", Port: "ethernet-1/1"}}},
			B: VerifyEnd{Node: "n2", Port: "ethernet-1/1", NodeName: "ethernet-1/1", Path: "/system/lldp/interface[name=ethernet-1/1]/neighbor",
				Expected: VerifyNodePort{Node: "n1", Port: "ethernet-1/1"}, Outcome: "held",
				Read: []VerifyNodePort{{Node: "n1", Port: "ethernet-1/1"}}}}},
		Record:  []VerifyClaim{{Node: "n1", Holds: str(stepToID), Staged: stepToID, Outcome: "held"}},
		Skipped: []VerifySkip{{Node: "n1", Port: "ethernet-1/2", Reason: "intent disables it"}},
		Counts: VerifyCounts{HostName: VerifyCount{Held: 1, Unread: num(0)}, PortEnabled: VerifyCount{Held: 1, Skipped: num(1), Unread: num(0)},
			Neighbor: VerifyCount{Held: 2, Unread: num(0)}, Record: VerifyCount{Held: 1}},
		Service: ShowServiceOK,
		Wait:    &VerifyWait{BudgetS: 120, Reads: 2, Outcome: "settled", AfterS: 1.2},
	}

	var unread List
	unread.AddStep(Rejection, StepObserve, RuleOperationFailed, "e1", "node e1 was not read: connection refused")
	diverged := NewDocument(OpTwinVerify, nil, unread)
	diverged.Status = StatusError
	diverged.Verify = &VerifyBlock{
		Twin: VerifyTwin{BundleID: stepFromID, State: "diverged", Source: "intent", Nodes: 1,
			Diverged: &VerifyDiverged{Towards: VerifyTowards{Waypoint: demoWaypoint(3, ""), BundleID: stepToID},
				Run: ShowRef{WorkflowID: "fylgja-step", RunID: stepRunID}, Phase: "readiness"}},
		ReadAt: "2026-10-03T12:00:00Z",
		Nodes: []VerifyNode{{Node: "e1", PSP: "arista_eos", Read: false, Error: "connection refused",
			HostName: VerifyAssertion{Path: "/system/state/hostname", Expected: "e1", Outcome: "unread", Error: "connection refused"}}},
		Record:     []VerifyClaim{{Node: "e1", Staged: stepFromID, Outcome: "failed"}},
		ExtraNodes: []string{"e9"},
		Counts:     VerifyCounts{HostName: VerifyCount{Failed: 1, Unread: num(1)}, Record: VerifyCount{Failed: 1}},
		InFlight:   []ShowRun{{WorkflowID: "fylgja-step", RunID: stepRunID, Step: "readiness"}},
		Service:    ShowServiceUnreachable,
	}
	return []labelledDocument{
		{"verify, held, with --wait", held},
		{"verify, diverged, a node unread", diverged},
	}
}

func TestEveryDocumentDecodesToTheSameBytes(t *testing.T) {
	for _, c := range decodeDocuments() {
		t.Run(c.label, func(t *testing.T) {
			var first bytes.Buffer
			if err := c.doc.WriteJSON(&first); err != nil {
				t.Fatal(err)
			}
			var decoded Document
			if err := json.Unmarshal(first.Bytes(), &decoded); err != nil {
				t.Fatalf("decoding: %v", err)
			}
			var again bytes.Buffer
			if err := decoded.WriteJSON(&again); err != nil {
				t.Fatal(err)
			}
			if !bytes.Equal(first.Bytes(), again.Bytes()) {
				t.Errorf("a decode does not write the same bytes\nwritten:\n%s\ndecoded and written again:\n%s", first.Bytes(), again.Bytes())
			}
		})
	}
}

// The one field the decode reads from a key's presence: a version 5 record's step whose
// wait has not run carries "wait": null, which a version 4 record's step lacks.
func TestShowStepDecodeKnowsTheWaitKey(t *testing.T) {
	for _, c := range []struct {
		raw  string
		want bool
	}{
		{`{"outcome":"stepped","wait":null}`, true},
		{`{"outcome":"stepped","wait":{"outcome":"settled","budget_s":120,"reads":1,"after_s":1,"failing":[]}}`, true},
		{`{"outcome":"stepped"}`, false},
	} {
		var s ShowStep
		if err := json.Unmarshal([]byte(c.raw), &s); err != nil {
			t.Fatalf("%s: %v", c.raw, err)
		}
		if s.WaitKnown != c.want {
			t.Errorf("%s: WaitKnown = %v, want %v", c.raw, s.WaitKnown, c.want)
		}
		if s.Outcome != "stepped" {
			t.Errorf("%s: outcome %q not decoded", c.raw, s.Outcome)
		}
	}
	if err := json.Unmarshal([]byte(`{"outcome":1}`), new(ShowStep)); err == nil {
		t.Error("a step whose outcome is not a string decoded")
	}
}

// A show block is built with no runs in flight and no notes as none, and written with both
// as []; decoded, it has none again, so a document read from the API is the one its command
// built (twin show's service unreachable has in_flight none).
func TestShowBlockDecodesNoRunsAsNone(t *testing.T) {
	b, err := json.Marshal(ShowBlock{Service: ShowServiceUnreachable})
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(b, []byte(`"in_flight":[]`)) || !bytes.Contains(b, []byte(`"notes":[]`)) {
		t.Fatalf("written %s, want in_flight and notes as []", b)
	}
	var got ShowBlock
	if err := json.Unmarshal(b, &got); err != nil {
		t.Fatal(err)
	}
	if got.InFlight != nil || got.Notes != nil {
		t.Errorf("decoded in_flight %#v, notes %#v; want none", got.InFlight, got.Notes)
	}
	runs := ShowBlock{InFlight: []ShowRun{{WorkflowID: "fylgja-provision", RunID: "r", Step: "deploy"}}, Notes: []string{"n"}}
	b, err = json.Marshal(runs)
	if err != nil {
		t.Fatal(err)
	}
	got = ShowBlock{}
	if err := json.Unmarshal(b, &got); err != nil {
		t.Fatal(err)
	}
	if len(got.InFlight) != 1 || got.InFlight[0] != runs.InFlight[0] || len(got.Notes) != 1 {
		t.Errorf("decoded %+v, want %+v", got, runs)
	}
}
