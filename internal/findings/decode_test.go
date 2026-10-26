package findings

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"

	"github.com/santhosh-tekuri/jsonschema/v6"
)

// M13's client reads the document out of a frame and decodes it into Document, so every
// document a command writes must come back from a decode as the bytes it went out as. A
// MarshalJSON that writes a nil list as [] is faithful in bytes: the decoded empty list is
// written as [] again. ShowStep's WaitKnown is the one field the encoding alone does not
// carry; its UnmarshalJSON reads it from the wait key.

// decodeDocuments is every document shape this package's tests build, and the shapes M12
// added that no builder covers: a show of a version 5 record with each wait and with wait
// null, a step document with each wait, and a verify block; and 015's rehearsal documents
// and a rehearsal's twin shown and verified.
func decodeDocuments() []labelledDocument {
	var docs []labelledDocument
	for _, set := range [][]labelledDocument{
		m1Documents(), m2Documents(), m4Documents(), m5Documents(), stageDocuments(), schemaCheckStageDocuments(),
		listAndPlanDocuments(), stepDocuments(), showStepDocuments(), listStepDocuments(),
		rehearsalDocuments(), rehearsalTwinDocuments(), scopedDocuments(),
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
// with a finding located in a file and a schema check that names the stage kind.
func m1Documents() []labelledDocument {
	located := List{{Severity: Warning, Rule: RulePSPResourcesImplausible, Object: "nokia_srlinux",
		Message: "resources look implausible", Location: &Location{File: "psp/x.yaml", Line: 12}}}
	compiled := NewDocument(OpCompile, &Subject{CTM: "ctm.json", Out: "/tmp/bundle"}, nil)
	compiled.BundleID = stepToID
	checked := NewDocument(OpSchemaCheck, &Subject{Branch: "fylgja-fixture"}, nil)
	checked.Verified = &Verified{ContractVersion: "0.2",
		Generics: []GenericKinds{{Generic: "FylgjaDevice", Kinds: []string{"NetworkDevice"}}},
		Stages:   &StagesVerified{Kind: "FylgjaStage", Present: true, Extension: true, File: "schema/fylgja-stage.yaml"}}
	return []labelledDocument{
		{"intent read ok", NewDocument(OpIntentRead, &Subject{Branch: "fylgja-fixture", CTM: "ctm.json"}, nil)},
		{"twin compile ok", compiled},
		{"twin compile error", ErrorDocument(OpCompile, &Subject{Out: "/tmp/b"}, "--out is required")},
		{"schema check ok", checked},
		{"psp validate with location", NewDocument(OpPSPValidate, &Subject{Files: []string{"psp/x.yaml"}}, located)},
	}
}

// scopedDocuments are 017's subjects: a read made under a scope, a stage's read under one,
// and a refusal that names the scope it refused.
func scopedDocuments() []labelledDocument {
	var refused List
	refused.AddStep(Rejection, StepStart, RuleScopeInvalid, "fylgja",
		`--scope fylgja is not tag:<name>`)
	refusedDoc := NewDocument(OpTwinCreate, &Subject{Branch: "b"}, refused)
	refusedDoc.Status = StatusError
	return []labelledDocument{
		{"intent read under a scope", NewDocument(OpIntentRead,
			&Subject{Branch: "fylgja-fixture", CTM: "ctm.json", Scope: "tag:fylgja"}, nil)},
		{"intent read of a stage under a scope", NewDocument(OpIntentRead,
			&Subject{Branch: "change-1", At: "2026-10-16T17:25:30.118244+00:00", Stage: "change-1/seeded", CTM: "ctm.json",
				Scope: "tag:lab-a"}, nil)},
		{"twin create refused, no scope read", refusedDoc},
	}
}

// A subject's scope is the contract's tag:<name>, and nothing else the schema accepts.
func TestSubjectScopeSatisfiesTheContract(t *testing.T) {
	schema := compileCurrentFindingsSchema(t)
	for _, c := range scopedDocuments() {
		mustValidate(t, schema, c.doc, c.label)
	}
	for _, scope := range []string{"fylgja", "tag:", "tag:a b", "group:x", "Tag:fylgja"} {
		b, err := json.Marshal(NewDocument(OpIntentRead, &Subject{Branch: "b", Scope: scope}, nil))
		if err != nil {
			t.Fatal(err)
		}
		v, err := jsonschema.UnmarshalJSON(bytes.NewReader(b))
		if err != nil {
			t.Fatal(err)
		}
		if err := schema.Validate(v); err == nil {
			t.Errorf("subject.scope %q satisfies findings.schema.json; only tag:<name> may", scope)
		}
	}
}

// The show record carries the record's provenance (017): an 8 record's scope and mapping,
// or neither for a 7 or earlier record, which names none. The contract refuses the one
// without the other, a scope that is not tag:<name>, and the contract_version 017 removed.
func TestShowRecordCarriesTheRecordsProvenance(t *testing.T) {
	schema := compileCurrentFindingsSchema(t)
	observed := "2026-10-25T09:00:00.000000Z"
	shown := func(change func(r *ShowRecord)) *Document {
		r := &ShowRecord{Branch: "fylgja-fixture", BundleID: strings.Repeat("b5", 32), SchemaHash: "908871c3",
			Scope: "tag:fylgja", Mapping: dcimMapping, ObservedAt: &observed, Source: "intent",
			Run: ShowRef{WorkflowID: "fylgja-provision", RunID: "run-1"}, WorkerVersion: "0.1.0-dev",
			RecordedAt: "2026-10-25T09:01:02Z", Nodes: 3, State: "ready"}
		change(r)
		doc := NewDocument(OpTwinShow, nil, nil)
		doc.Show = &ShowBlock{Kind: ShowKindFrozen, Service: ShowServiceOK, Record: r,
			Host: ShowHost{LabPresent: true, TwinDirPresent: true, Phrase: "the twin of branch fylgja-fixture"}}
		return doc
	}
	mustValidate(t, schema, shown(func(*ShowRecord) {}), "an 8 record")
	b := mustMarshal(t, shown(func(*ShowRecord) {}))
	if want := `"scope":"tag:fylgja","mapping":{"reader":"infrahub-dcim","model":"opsmill/schema-library","version":"26336e9"}`; !strings.Contains(string(b), want) {
		t.Errorf("an 8 record's show block does not carry %s: %s", want, b)
	}
	older := shown(func(r *ShowRecord) { r.Scope, r.Mapping = "", nil })
	mustValidate(t, schema, older, "a 7 record")
	if b := mustMarshal(t, older); strings.Contains(string(b), `"scope"`) || strings.Contains(string(b), `"mapping"`) {
		t.Errorf("a 7 record's show block names a scope or a mapping: %s", b)
	}

	for label, change := range map[string]func(g map[string]any){
		"a scope with no mapping": func(g map[string]any) { delete(g, "mapping") },
		"a mapping with no scope": func(g map[string]any) { delete(g, "scope") },
		"a scope not tag:<name>":  func(g map[string]any) { g["scope"] = "fylgja" },
		"a mapping with no model": func(g map[string]any) { delete(g["mapping"].(map[string]any), "model") },
		"contract_version":        func(g map[string]any) { g["contract_version"] = "0.2" },
	} {
		var generic map[string]any
		if err := json.Unmarshal(mustMarshal(t, shown(func(*ShowRecord) {})), &generic); err != nil {
			t.Fatal(err)
		}
		change(generic["show"].(map[string]any)["record"].(map[string]any))
		b, err := json.Marshal(generic)
		if err != nil {
			t.Fatal(err)
		}
		if err := schema.Validate(mustAny(t, b)); err == nil {
			t.Errorf("%s: show.schema.json's record accepts it", label)
		}
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
		Twin: VerifyTwin{BundleID: stepToID, Stage: showStage("live", "after its configuration is live", AtSourceGiven), State: "ready",
			Source: "intent", Nodes: 2},
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
			Diverged: &VerifyDiverged{Towards: VerifyTowards{Stage: showStage("head", "", AtSourceHead), BundleID: stepToID},
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
