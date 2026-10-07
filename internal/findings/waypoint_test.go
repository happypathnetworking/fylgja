package findings

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/santhosh-tekuri/jsonschema/v6"
)

// currentContract is the feature argument that names the module root's contracts/, which
// holds the current contract. Any other names an older feature's frozen copy, under this
// package's testdata/contracts/<feature>/.
const currentContract = ""

// contractPath is where feature's copy of the contract file name is read.
func contractPath(feature, name string) string {
	if feature == currentContract {
		return filepath.Join("..", "..", "contracts", name)
	}
	return filepath.Join("testdata", "contracts", feature, name)
}

// compileFeatureFindingsSchema loads one feature's copy of the findings contract with the
// blocks it references added under their own $ids: show.schema.json from M4,
// waypoints.schema.json from M10, step.schema.json from M11 and verify.schema.json from
// M12. A feature's findings contract that refers to a block
// cannot compile without it, so a caller names every block its feature's copy refers to.
func compileFeatureFindingsSchema(t *testing.T, feature string, resources ...string) *jsonschema.Schema {
	t.Helper()
	load := func(name string) any {
		f, err := os.Open(contractPath(feature, name))
		if err != nil {
			t.Fatal(err)
		}
		defer func() { _ = f.Close() }()
		doc, err := jsonschema.UnmarshalJSON(f)
		if err != nil {
			t.Fatalf("parsing %s: %v", contractPath(feature, name), err)
		}
		return doc
	}
	c := jsonschema.NewCompiler()
	for _, name := range resources {
		if err := c.AddResource("https://fylgja.dev/schemas/"+name, load(name)); err != nil {
			t.Fatal(err)
		}
	}
	id := feature + "-findings.schema.json"
	if err := c.AddResource(id, load("findings.schema.json")); err != nil {
		t.Fatal(err)
	}
	s, err := c.Compile(id)
	if err != nil {
		t.Fatalf("compiling %s (a consumer could not load it): %v", contractPath(feature, "findings.schema.json"), err)
	}
	return s
}

// demoBlock is contracts/cli.md's example waypoint, resolved.
func demoBlock() *WaypointBlock {
	return &WaypointBlock{Series: "demo", Sequence: 2, Branch: "change-1",
		At: "2026-09-28T15:20:44.000000+00:00", AtSource: "written", Description: "after the first cut-over"}
}

// m10Documents are the document shapes M10 adds to the operations M1–M7 already had: a
// create, its dry run and a read given --waypoint, each carrying subject.waypoint and the
// waypoint block; a resolution refused, which carries subject.waypoint and no block; and
// twin show of a version 3 record naming its waypoint.
func m10Documents() []labelledDocument {
	id := strings.Repeat("9c", 32)
	observed := "2026-09-28T15:31:02.118842Z"
	subject := func() *Subject {
		return &Subject{Branch: "change-1", At: "2026-09-28T15:20:44.000000+00:00", Waypoint: "demo/2", RunID: "run-1"}
	}

	created := NewDocument(OpTwinCreate, subject(), nil)
	created.BundleID = id
	created.Waypoint = demoBlock()
	created.Twin = &TwinBlock{Lab: "fylgja", Dir: "/abs/twin", RunID: "run-1", ObservedAt: &observed,
		Nodes: []TwinNode{{Name: "n1", MgmtIPv4: "172.20.20.2", ReadyAfterS: 0.9,
			Artifact: &ShowArtifact{Name: "device-config", Checksum: m5Checksum}, PushedInS: 0.71}}}

	budget := 4096
	dry := NewDocument(OpTwinCreate, &Subject{Branch: "change-1", At: "2026-09-28T15:20:44.000000+00:00", Waypoint: "demo/2"}, nil)
	dry.BundleID = id
	dry.Waypoint = demoBlock()
	dry.DryRun = &DryRunBlock{
		Nodes: []DryRunNode{{Name: "n1", Image: "ghcr.io/nokia/srlinux:24.7.1", PSP: "nokia_srlinux", MemoryMB: 2048,
			Artifact: &DryRunArtifact{Name: "device-config", ContentType: "text/plain", Checksum: m5Checksum, Size: 861}}},
		MemorySumMB: 2048, HostBudgetMB: &budget, Verdict: VerdictClear,
		Follow: &DryRunFollow{Reason: FollowReasonWaypoint},
	}

	read := NewDocument(OpIntentRead, &Subject{Branch: "change-1", At: "2026-09-28T15:20:44.000000+00:00", Waypoint: "demo/2", Out: "ctm.json"}, nil)
	read.Waypoint = demoBlock()

	var unknown List
	unknown.AddStep(Rejection, StepResolve, RuleWaypointUnknown, "demo/7", "series demo has no waypoint 7; its sequences are 1, 2, 5")
	refused := NewDocument(OpTwinCreate, &Subject{Waypoint: "demo/7"}, unknown)

	shown := NewDocument(OpTwinShow, nil, nil)
	shown.Show = &ShowBlock{Kind: ShowKindPinned, Service: ShowServiceOK,
		Host: ShowHost{LabPresent: true, TwinDirPresent: true, Phrase: "the twin of branch change-1 at 2026-09-28T15:20:44.000000+00:00",
			Nodes: []ShowNode{{Name: "n1", Container: "clab-fylgja-n1", State: "running", MgmtIPv4: "172.20.20.2",
				Artifact: &ShowArtifact{Name: "device-config", Checksum: m5Checksum}}}},
		Record: &ShowRecord{Branch: "change-1", At: "2026-09-28T15:20:44.000000+00:00", BundleID: id, SchemaHash: "fe9eca98",
			ContractVersion: "0.2", ObservedAt: &observed, Source: "intent",
			Run:           ShowRef{WorkflowID: "fylgja-provision", RunID: "run-1"},
			WorkerVersion: "0.1.0-dev", RecordedAt: "2026-09-28T15:32:00Z", Nodes: 1,
			Waypoint: &ShowWaypoint{Series: "demo", Sequence: 2, Description: "after the first cut-over", AtSource: "written"}},
		Notes: []string{"pinned at 2026-09-28T15:20:44.000000+00:00, waypoint demo/2; not following"}}

	return []labelledDocument{
		{"create from a waypoint", created},
		{"dry run from a waypoint", dry},
		{"intent read from a waypoint", read},
		{"resolution refused", refused},
		{"show of a record naming its waypoint", shown},
	}
}

// M10's documents satisfy M10's contract, and each carries the keys it is for: the
// subject names the waypoint as given, and the block the reference it resolved to.
//
// It stays on M10's copy when the newest contract moves on: it proves the shapes M10
// shipped still satisfy the contract they were written
// against, which a newer, wider copy cannot prove.
func TestM10DocumentsSatisfySchema(t *testing.T) {
	schema := compileFeatureFindingsSchema(t, "008-waypoints", "show.schema.json", "waypoints.schema.json")
	for _, c := range m10Documents() {
		t.Run(c.label, func(t *testing.T) {
			mustValidate(t, schema, c.doc, c.label)
			mustCarryNoContent(t, c.doc, c.label)
			b, err := json.Marshal(c.doc)
			if err != nil {
				t.Fatal(err)
			}
			for _, key := range m10Keys(c.doc) {
				if !strings.Contains(string(b), key) {
					t.Errorf("%s does not carry %s: %s", c.label, key, b)
				}
			}
		})
	}

	// The keys are the contract's, so a document with the block misshapen is refused: the
	// test would pass a struct that marshalled nothing the schema checks.
	bad := m10Documents()[0].doc
	bad.Waypoint.AtSource = "guessed"
	if err := schema.Validate(mustAny(t, mustMarshal(t, bad))); err == nil {
		t.Error("a waypoint block with at_source guessed satisfied M10's findings.schema.json")
	}
}

// m10Keys are the serialised keys a document of m10Documents is there to show.
func m10Keys(doc *Document) []string {
	var keys []string
	if doc.Subject != nil && doc.Subject.Waypoint != "" {
		keys = append(keys, `"subject":{`, `"waypoint":"`+doc.Subject.Waypoint+`"`)
	}
	if doc.Waypoint != nil {
		keys = append(keys, `"waypoint":{"series":"demo","sequence":2,"branch":"change-1","at":"2026-09-28T15:20:44.000000+00:00","at_source":"written","description":"after the first cut-over"}`)
	}
	if doc.Show != nil && doc.Show.Record != nil && doc.Show.Record.Waypoint != nil {
		keys = append(keys, `"waypoint":{"series":"demo","sequence":2,"description":"after the first cut-over","at_source":"written"}`)
	}
	return keys
}

// A document with no waypoint is M7's, key for key: every new field is omitted when
// empty, so M7's own contract, which forbids additional properties, still accepts every
// shape M5 and M7 build, and so does M10's.
//
// Both copies stay their milestones' when the newest contract moves on: the claim is that
// the older contracts still accept these documents.
func TestAnM7DocumentIsUnchanged(t *testing.T) {
	m7 := compileFeatureFindingsSchema(t, "007-eos-platform", "show.schema.json")
	m10 := compileFeatureFindingsSchema(t, "008-waypoints", "show.schema.json", "waypoints.schema.json")
	for _, c := range m5Documents() {
		t.Run(c.label, func(t *testing.T) {
			b := mustMarshal(t, c.doc)
			if strings.Contains(string(b), "waypoint") {
				t.Errorf("a document with no waypoint names one: %s", b)
			}
			mustValidateBytes(t, m7, b, c.label+" against M7's contract")
			mustValidateBytes(t, m10, b, c.label+" against M10's contract")
		})
	}
}

func mustMarshal(t *testing.T, doc *Document) []byte {
	t.Helper()
	b, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

// The one line printed wherever a reference resolves is contracts/cli.md's, word for
// word; a waypoint with no description reads "", and a description with a quote or a
// line break in it stays on the one line.
func TestWaypointLine(t *testing.T) {
	for _, c := range []struct {
		block WaypointBlock
		want  string
	}{
		{*demoBlock(), `waypoint demo/2: branch change-1 at 2026-09-28T15:20:44.000000+00:00 (written), "after the first cut-over"`},
		{WaypointBlock{Series: "demo", Sequence: 3, Branch: "change-1", At: "2026-09-28T16:00:00Z", AtSource: "given"},
			`waypoint demo/3: branch change-1 at 2026-09-28T16:00:00Z (given), ""`},
		{WaypointBlock{Series: "demo", Sequence: 4, Branch: "main", At: "2026-09-28T16:00:00Z", AtSource: "given", Description: "the \"big\" one\nsecond line"},
			`waypoint demo/4: branch main at 2026-09-28T16:00:00Z (given), "the \"big\" one\nsecond line"`},
	} {
		if got := c.block.Line(); got != c.want {
			t.Errorf("Line() =\n  %s\nwant\n  %s", got, c.want)
		}
	}
}

// listAndPlanDocuments are the document shapes waypoint list and waypoint plan produce:
// a whole listing with no record, a filtered one marking the record's
// row beside its warning, an empty one; a plan whose middle waypoint was refused at
// resolution, one whose waypoint read but did not compile, one with a computed step, and a
// plan of one waypoint with no step.
func listAndPlanDocuments() []labelledDocument {
	demo := "demo"
	row := func(seq int, at, source, desc string, twin bool) WaypointRow {
		return WaypointRow{WaypointBlock: WaypointBlock{Series: "demo", Sequence: seq, Branch: "change-1", At: at,
			AtSource: source, Description: desc}, Twin: twin}
	}

	var reversed List
	reversed.Add(Warning, RuleWaypointTimeReversed, "demo/3",
		"waypoint demo/3 resolves to at 2026-09-27T09:00:00Z, earlier than demo/2's 2026-09-28T15:20:44.000000+00:00; the order is the operator's and nothing is refused")
	all := NewDocument(OpWaypointList, nil, reversed)
	all.Waypoints = &WaypointsBlock{Waypoints: []WaypointRow{
		row(1, "2026-09-28T15:00:01.123456+00:00", "written", "before the change", false),
		row(2, "2026-09-28T15:20:44.000000+00:00", "written", "after the first cut-over", false),
		row(3, "2026-09-27T09:00:00Z", "given", "", false),
	}}

	var moved List
	moved.Add(Warning, RuleWaypointTwinMoved, "demo/2",
		"the twin was built from waypoint demo/2 at branch change-1, at 2026-09-28T15:20:44.000000+00:00 (written); demo/2 no longer exists; the twin is pinned to what it was built from")
	filtered := NewDocument(OpWaypointList, nil, moved)
	filtered.Waypoints = &WaypointsBlock{Series: &demo,
		Waypoints: []WaypointRow{row(1, "2026-09-28T15:00:01.123456+00:00", "written", "before the change", false)},
		Record:    &WaypointRecord{Series: "demo", Sequence: 2, Branch: "change-1", At: "2026-09-28T15:20:44.000000+00:00", AtSource: "written"}}

	empty := NewDocument(OpWaypointList, nil, nil)
	empty.Waypoints = &WaypointsBlock{}

	idOf := func(s string) *string { id := strings.Repeat(s, 32); return &id }
	counts := &ReadCounts{Devices: 3, Interfaces: 12, Links: 3, Artifacts: 3}
	compiled := func(seq int, at, id string) PlanWaypoint {
		return PlanWaypoint{Series: "demo", Sequence: seq, Branch: "change-1", At: at, AtSource: "written",
			Description: "after the first cut-over", BundleID: idOf(id), Read: counts}
	}

	var future List
	future.AddStep(Rejection, StepResolve, RuleWaypointAtUnresolved, "demo/2",
		"waypoint demo/2 has at 2099-01-01T00:00:00Z (given), later than the current time 2026-09-28T16:10:00.000000Z: it seals nothing yet, and a twin from it could differ between two creates")
	refused := NewDocument(OpWaypointPlan, nil, future)
	refused.Plan = &PlanBlock{Series: "demo",
		Waypoints: []PlanWaypoint{
			compiled(1, "2026-09-28T15:00:01.123456+00:00", "35"),
			{Series: "demo", Sequence: 2, Description: "not yet", Findings: future},
			compiled(3, "2026-09-28T16:00:00Z", "51"),
		},
		Steps: []json.RawMessage{
			json.RawMessage(`{"from":"demo/1","to":"demo/2","from_bundle_id":"` + *idOf("35") + `","to_bundle_id":null,"computed":false,"not_computed":"demo/2 was refused"}`),
			json.RawMessage(`{"from":"demo/2","to":"demo/3","from_bundle_id":null,"to_bundle_id":"` + *idOf("51") + `","computed":false,"not_computed":"demo/2 was refused"}`),
		}}

	var notReady List
	notReady.AddStep(Rejection, StepRead, RuleArtifactNotReady, "n1", "artifact device-config of n1 on branch change-1 is Pending, not Ready")
	unbuilt := NewDocument(OpWaypointPlan, nil, notReady)
	unbuilt.Plan = &PlanBlock{Series: "demo", Waypoints: []PlanWaypoint{{Series: "demo", Sequence: 1, Branch: "change-1",
		At: "2026-09-28T15:00:01.123456+00:00", AtSource: "written", Description: "", Read: counts, Findings: notReady}}}

	stepped := NewDocument(OpWaypointPlan, nil, nil)
	stepped.Plan = &PlanBlock{Series: "demo",
		Waypoints: []PlanWaypoint{compiled(1, "2026-09-28T15:00:01.123456+00:00", "35"), compiled(2, "2026-09-28T15:20:44.000000+00:00", "9c")},
		Steps: []json.RawMessage{json.RawMessage(`{"from":"demo/1","to":"demo/2","from_bundle_id":"` + *idOf("35") +
			`","to_bundle_id":"` + *idOf("9c") + `","computed":true,"unchanged":false,` +
			`"nodes":{"added":["n4"],"removed":[],"changed":[{"node":"n1","reasons":["bootstrap","mapping"]}]},` +
			`"links":{"added":[{"id":"n1:ethernet-1/3|n4:ethernet-1/1","a":{"node":"n1","port":"e1-3"},"b":{"node":"n4","port":"e1-1"}}],"removed":[]},` +
			`"artifacts":{"changed":[{"node":"n1","name":"device-config","from":"43e8fd0c2de5f4646f74a51d34742824","to":"9a0177b2e8c1d4f5a6b7c8d9e0f1a2b3"}]}}`)}}

	one := NewDocument(OpWaypointPlan, nil, nil)
	one.Plan = &PlanBlock{Series: "demo", Waypoints: []PlanWaypoint{compiled(1, "2026-09-28T15:00:01.123456+00:00", "35")}}

	return []labelledDocument{
		{"list, every series", all},
		{"list, one series, the record's waypoint gone", filtered},
		{"list, no waypoints", empty},
		{"plan, the middle waypoint refused", refused},
		{"plan, a waypoint read but not compiled", unbuilt},
		{"plan, a computed step", stepped},
		{"plan, one waypoint", one},
	}
}

// waypoint list's and waypoint plan's documents satisfy the newest contract, with every
// list and every nullable key the contract requires written even when empty. The newest
// is the module root's contracts/, M11's extended additively;
// M11's list record gained state and towards, so the documents this build writes are read
// against the newest.
func TestWaypointListAndPlanSatisfySchema(t *testing.T) {
	schema := compileFeatureFindingsSchema(t, currentContract, "show.schema.json", "waypoints.schema.json", "step.schema.json", "verify.schema.json")
	for _, c := range listAndPlanDocuments() {
		t.Run(c.label, func(t *testing.T) {
			mustValidate(t, schema, c.doc, c.label)
			mustCarryNoContent(t, c.doc, c.label)
		})
	}
	docs := listAndPlanDocuments()
	for _, c := range []struct {
		doc  *Document
		keys []string
	}{
		{docs[0].doc, []string{`"waypoints":{"series":null,`, `"record":null`, `"twin":false`}},
		{docs[1].doc, []string{`"series":"demo"`, `"record":{"series":"demo","sequence":2,"branch":"change-1",`}},
		{docs[2].doc, []string{`"waypoints":{"series":null,"waypoints":[],"record":null}`}},
		{docs[3].doc, []string{`{"series":"demo","sequence":2,"description":"not yet","bundle_id":null,"read":null,"findings":[{`}},
		{docs[4].doc, []string{`"bundle_id":null,"read":{"devices":3,`}},
		{docs[6].doc, []string{`"steps":[]`, `"findings":[]`}},
	} {
		if b := string(mustMarshal(t, c.doc)); !containsAll(b, c.keys) {
			t.Errorf("%s does not carry every one of %q: %s", c.doc.Operation, c.keys, b)
		}
	}

	// The blocks are the contract's, so a misshapen one is refused: a step list with a
	// computed step missing its parts, and a plan waypoint with no findings key.
	bad := listAndPlanDocuments()[5].doc
	bad.Plan.Steps[0] = json.RawMessage(`{"from":"demo/1","to":"demo/2","from_bundle_id":null,"to_bundle_id":null,"computed":true}`)
	if err := schema.Validate(mustAny(t, mustMarshal(t, bad))); err == nil {
		t.Error("a computed step with no parts satisfied M10's findings.schema.json")
	}
}

func containsAll(s string, subs []string) bool {
	for _, sub := range subs {
		if !strings.Contains(s, sub) {
			return false
		}
	}
	return true
}
