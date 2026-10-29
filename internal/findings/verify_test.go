package findings

import (
	"encoding/json"
	"reflect"
	"strings"
	"testing"
)

// probedVerifyDocument is twin verify's document for a probed twin (016): a device, the
// probe's first host with its burst failed and its second host, each host with psp null,
// its probe named, no host_name and ports [], the counts' burst, and verify.burst's finding.
func probedVerifyDocument() *Document {
	str := func(s string) *string { return &s }
	num := func(n int) *int { return &n }
	probe := func(endpoint string) *VerifyProbe {
		return &VerifyProbe{Name: "n1-loop", Endpoint: endpoint, Format: "ping", Package: DryRunPackage{ID: "ping", Source: "embedded"}}
	}
	var l List
	l.AddStep(Rejection, StepObserve, RuleVerifyBurst, "n1-loop", "probe n1-loop: 4 of 5 replies from n1-loop-b at 10.1.11.2")
	doc := NewDocument(OpTwinVerify, nil, l)
	doc.Status = StatusNonconforming
	doc.BundleID = stepToID
	doc.Verify = &VerifyBlock{
		Twin:   VerifyTwin{BundleID: stepToID, State: "ready", Source: "intent", Nodes: 3},
		ReadAt: "2026-10-29T12:00:00Z",
		Nodes: []VerifyNode{
			{Node: "n1", PSP: str("nokia_srlinux"), Addr: str("172.20.20.2:57400"), Read: true,
				HostName: &VerifyAssertion{Path: "/system/name/host-name", Expected: "n1", Outcome: "held", Read: str("n1")},
				Ports: []VerifyPort{{Port: "ethernet-1/10", NodeName: "ethernet-1/10", Path: "/interface[name=ethernet-1/10]/admin-state",
					Expected: "enable", Outcome: "held", Read: str("enable")}}},
			{Node: "n1-loop-a", Probe: probe("a"), Addr: str("172.20.20.5"), Read: true,
				Bursts: []VerifyBurst{{Probe: "n1-loop", From: "n1-loop-a", To: "n1-loop-b", FarAddress: "10.1.11.2",
					Expected: "5 replies", Outcome: "failed", Read: str("4 replies")}}},
			{Node: "n1-loop-b", Probe: probe("b"), Addr: str("172.20.20.6"), Read: true},
		},
		Record: []VerifyClaim{{Node: "n1", Holds: str(stepToID), Staged: stepToID, Outcome: "held"}},
		Skipped: []VerifySkip{{Node: "n1-loop-a", Port: "eth1", Link: str("n1-loop-a:eth1|n1:ethernet-1/10"),
			Reason: "link n1-loop-a:eth1|n1:ethernet-1/10 is synthesized: n1-loop-a speaks no discovery protocol"}},
		Counts: VerifyCounts{HostName: VerifyCount{Held: 1, Unread: num(0)}, PortEnabled: VerifyCount{Held: 1, Skipped: num(0), Unread: num(0)},
			Neighbor: VerifyCount{Skipped: num(2), Unread: num(0)}, Burst: VerifyCount{Failed: 1, Unread: num(0)}, Record: VerifyCount{Held: 1}},
		Service: ShowServiceOK,
	}
	return doc
}

// The verify block of a probed twin (016, formats.md's verify row): the current contract
// accepts it as built, a host's bursts written [] when it sends none and a device carrying
// no bursts key, and it reads back as it was written; 019's contract refuses it, since a
// host and a counted burst are 016's alone; and the contract refuses a host that names a
// host name or a package, and a device that bursts or names no package.
func TestVerifyBlockOfAProbedTwin(t *testing.T) {
	current := compileCurrentFindingsSchema(t)
	doc := probedVerifyDocument()
	b := mustMarshal(t, doc)
	mustValidateBytes(t, current, b, "a probed twin's verify")

	text := string(b)
	for _, want := range []string{`"node":"n1-loop-b","psp":null,`, `"ports":[],"bursts":[]}`, `"burst":{"held":0,"failed":1,"unread":0}`} {
		if !strings.Contains(text, want) {
			t.Errorf("the document does not carry %s:\n%s", want, text)
		}
	}
	if strings.Count(text, `"bursts":`) != 2 {
		t.Errorf("bursts on other than the two hosts:\n%s", text)
	}
	var back Document
	if err := json.Unmarshal(b, &back); err != nil {
		t.Fatal(err)
	}
	if again := mustMarshal(t, &back); string(again) != text || back.Verify.Nodes[0].Bursts != nil ||
		!reflect.DeepEqual(back.Verify.Nodes[1].Bursts, doc.Verify.Nodes[1].Bursts) {
		t.Errorf("read back as\n%s\nwant\n%s", again, text)
	}

	v019 := compileFeatureFindingsSchema(t, contract019, currentResources...)
	if err := v019.Validate(mustAny(t, mutated(t, doc, drop016NullLoss))); err == nil {
		t.Error("019's contract accepts a verify block with hosts and a counted burst")
	}

	for _, c := range []struct {
		name   string
		change func(map[string]any)
	}{
		{"a host with a host name", func(d map[string]any) {
			node(d, 1)["host_name"] = map[string]any{"path": "", "expected": "n1-loop-a", "outcome": "skipped"}
		}},
		{"a host with a package", func(d map[string]any) { node(d, 1)["psp"] = "nokia_srlinux" }},
		{"a host with no bursts", func(d map[string]any) { delete(node(d, 2), "bursts") }},
		{"a device with bursts", func(d map[string]any) { node(d, 0)["bursts"] = []any{} }},
		{"a device with no package", func(d map[string]any) { node(d, 0)["psp"] = nil }},
		{"no burst count", func(d map[string]any) {
			delete(d["verify"].(map[string]any)["counts"].(map[string]any), "burst")
		}},
		{"a burst skipped", func(d map[string]any) {
			node(d, 1)["bursts"].([]any)[0].(map[string]any)["outcome"] = "skipped"
		}},
	} {
		if err := current.Validate(mustAny(t, mutated(t, doc, c.change))); err == nil {
			t.Errorf("the contract accepts %s", c.name)
		}
	}
}

// node is the i-th node of a decoded document's verify block.
func node(doc map[string]any, i int) map[string]any {
	return doc["verify"].(map[string]any)["nodes"].([]any)[i].(map[string]any)
}
