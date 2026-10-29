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

// currentResources are the blocks the current findings contract refers to by their $ids:
// show.schema.json from M4, step.schema.json from M11, verify.schema.json from M12,
// stages.schema.json from 014 and rehearsal.schema.json from 015.
var currentResources = []string{"show.schema.json", "stages.schema.json", "step.schema.json", "verify.schema.json", "rehearsal.schema.json"}

// compileFeatureFindingsSchema loads one feature's copy of the findings contract with the
// blocks it references added under their own $ids. A feature's findings contract that
// refers to a block cannot compile without it, so a caller names every block its
// feature's copy refers to: currentResources for the current contract. A block the
// feature's directory does not hold had not moved since that feature, so the current one
// is read in its place: verify.schema.json beside 017's copy, which 018 does not move, and
// the stages, step, verify and rehearsal blocks beside 018's, which 019 does not freeze.
func compileFeatureFindingsSchema(t *testing.T, feature string, resources ...string) *jsonschema.Schema {
	t.Helper()
	load := func(name string) any {
		path := contractPath(feature, name)
		if _, err := os.Stat(path); err != nil && name != "findings.schema.json" {
			path = contractPath(currentContract, name)
		}
		f, err := os.Open(path)
		if err != nil {
			t.Fatal(err)
		}
		defer func() { _ = f.Close() }()
		doc, err := jsonschema.UnmarshalJSON(f)
		if err != nil {
			t.Fatalf("parsing %s: %v", path, err)
		}
		return doc
	}
	c := jsonschema.NewCompiler()
	for _, name := range resources {
		if err := c.AddResource("https://github.com/happypathnetworking/fylgja/schemas/"+name, load(name)); err != nil {
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

// compileCurrentFindingsSchema is the current findings contract, contracts/, with every
// block it refers to.
func compileCurrentFindingsSchema(t *testing.T) *jsonschema.Schema {
	t.Helper()
	return compileFeatureFindingsSchema(t, currentContract, currentResources...)
}

// stageChange is the commands contract's example proposed change: "third link", a draft,
// on its source branch change-1.
func stageChange() StageChange {
	return StageChange{ID: "pc-1", Name: "third link", Branch: "change-1", Draft: true}
}

// The commands contract's four example stages, resolved: the branch point read on main,
// a mark with no as_of (written), a mark with one (given), and the head.
func branchPointBlock() *StageBlock {
	return &StageBlock{Ref: "change-1/branch-point", Branch: "main", Label: "branch-point", ProposedChange: stageChange(),
		At: "2026-10-16T17:20:19.944651+00:00", AtSource: AtSourceBranchPoint}
}

func cabledBlock() *StageBlock {
	return &StageBlock{Ref: "change-1/cabled", Branch: "change-1", Label: "cabled", ProposedChange: stageChange(),
		At: "2026-10-16T17:25:30.118244+00:00", AtSource: AtSourceWritten, Description: "after the link is cabled"}
}

func liveBlock() *StageBlock {
	return &StageBlock{Ref: "change-1/live", Branch: "change-1", Label: "live", ProposedChange: stageChange(),
		At: "2026-10-16T17:30:00.000000+00:00", AtSource: AtSourceGiven, Description: "after its configuration is live"}
}

func headBlock() *StageBlock {
	return &StageBlock{Ref: "change-1/head", Branch: "change-1", Label: "head", ProposedChange: stageChange(),
		At: "2026-10-16T17:30:11.884302+00:00", AtSource: AtSourceHead}
}

// showStage is a stage as twin.json 6 records it, of the example proposed change.
func showStage(label, description, source string) *ShowStage {
	return &ShowStage{ProposedChange: StageChangeRef{ID: "pc-1", Branch: "change-1"}, Label: label,
		Description: description, AtSource: source}
}

// stageDocuments are the document shapes 014's --stage gives the operations M1–M7 already
// had: a create, its dry run and a read given --stage, each carrying subject.stage and the
// stage block; a create from each derived stage; a resolution refused, which carries
// subject.stage and no block; and twin show of a version 6 record naming its stage, a mark
// and the branch point.
func stageDocuments() []labelledDocument {
	id := strings.Repeat("9c", 32)
	observed := "2026-10-16T17:31:02.118842Z"
	subject := func(b *StageBlock) *Subject {
		return &Subject{Branch: b.Branch, At: b.At, Stage: b.Ref, RunID: "run-1"}
	}
	create := func(b *StageBlock) *Document {
		doc := NewDocument(OpTwinCreate, subject(b), nil)
		doc.BundleID = id
		doc.Stage = b
		doc.Twin = &TwinBlock{Lab: "fylgja", Dir: "/abs/twin", RunID: "run-1", ObservedAt: &observed,
			Nodes: []TwinNode{{Name: "n1", MgmtIPv4: "172.20.20.2", ReadyAfterS: 0.9,
				Artifact: &ShowArtifact{Name: "device-config", Checksum: m5Checksum}, PushedInS: 0.71}}}
		return doc
	}

	budget := 4096
	cabled := cabledBlock()
	dry := NewDocument(OpTwinCreate, &Subject{Branch: cabled.Branch, At: cabled.At, Stage: cabled.Ref}, nil)
	dry.BundleID = id
	dry.Stage = cabledBlock()
	dry.DryRun = &DryRunBlock{
		Nodes: []DryRunNode{{Name: "n1", Image: "ghcr.io/nokia/srlinux:24.7.1", PSP: ptr("nokia_srlinux"), MemoryMB: 2048,
			Artifact: &DryRunArtifact{Name: "device-config", ContentType: "text/plain", Checksum: m5Checksum, Size: 861}}},
		MemorySumMB: 2048, HostBudgetMB: &budget, Verdict: VerdictClear,
	}

	read := NewDocument(OpIntentRead, &Subject{Branch: cabled.Branch, At: cabled.At, Stage: cabled.Ref, Out: "ctm.json"}, nil)
	read.Stage = cabledBlock()

	var unknown List
	unknown.AddStep(Rejection, StepResolve, RuleStageUnknown, "change-1/seven",
		`proposed change third link (pc-1) on branch change-1 has no stage "seven"; its stages are: branch-point, cabled, live, head`)
	refused := NewDocument(OpTwinCreate, &Subject{Stage: "change-1/seven"}, unknown)

	shown := func(branch, at string, stage *ShowStage) *Document {
		doc := NewDocument(OpTwinShow, nil, nil)
		doc.Show = &ShowBlock{Kind: ShowKindSnapshot, Service: ShowServiceOK,
			Host: ShowHost{LabPresent: true, TwinDirPresent: true, Phrase: "the twin of branch " + branch + " at " + at,
				Nodes: []ShowNode{{Name: "n1", Container: "clab-fylgja-n1", State: "running", MgmtIPv4: "172.20.20.2",
					Artifact: &ShowArtifact{Name: "device-config", Checksum: m5Checksum}}}},
			Record: &ShowRecord{Branch: branch, At: at, BundleID: id, SchemaHash: "a8045729",
				Scope: "tag:fylgja", Mapping: dcimMapping, ObservedAt: &observed, Source: "intent",
				Run:           ShowRef{WorkflowID: "fylgja-provision", RunID: "run-1"},
				WorkerVersion: "0.1.0-dev", RecordedAt: "2026-10-16T17:32:00Z", Nodes: 1, State: "ready", Stage: stage},
			Notes: []string{"pinned at " + at + ", stage " + stage.Ref() + "; not following"}}
		return doc
	}
	bp := branchPointBlock()

	return []labelledDocument{
		{"create from a stage", create(cabledBlock())},
		{"create from the branch point", create(branchPointBlock())},
		{"create from the head", create(headBlock())},
		{"create from a given stage", create(liveBlock())},
		{"dry run from a stage", dry},
		{"intent read from a stage", read},
		{"resolution refused", refused},
		{"show of a record naming its stage", shown(cabled.Branch, cabled.At, showStage("cabled", "after the link is cabled", AtSourceWritten))},
		{"show of a record naming the branch point", shown(bp.Branch, bp.At, showStage("branch-point", "", AtSourceBranchPoint))},
	}
}

// 014's documents satisfy the current contract, and each carries the keys it is for: the
// subject names the stage as given, the block the reference it resolved to, and the show
// record the stage twin.json 6 names.
func TestStageDocumentsSatisfySchema(t *testing.T) {
	schema := compileCurrentFindingsSchema(t)
	for _, c := range stageDocuments() {
		t.Run(c.label, func(t *testing.T) {
			mustValidate(t, schema, c.doc, c.label)
			mustCarryNoContent(t, c.doc, c.label)
			b := string(mustMarshal(t, c.doc))
			if keys := stageKeys(c.doc); !containsAll(b, keys) {
				t.Errorf("%s does not carry every one of %q: %s", c.label, keys, b)
			}
		})
	}
	docs := stageDocuments()
	for _, c := range []struct {
		doc  *Document
		keys []string
	}{
		{docs[1].doc, []string{`"branch":"main","label":"branch-point",`, `"at_source":"branch_point","description":""}`}},
		{docs[2].doc, []string{`"label":"head",`, `"at_source":"head","description":""}`}},
		{docs[3].doc, []string{`"at_source":"given","description":"after its configuration is live"}`}},
		{docs[4].doc, []string{`"dry_run":{"nodes":[{"name":"n1",`, `"stage":{"ref":"change-1/cabled","branch":"change-1","label":"cabled",`}},
		{docs[6].doc, []string{`"subject":{"stage":"change-1/seven"}`, `"rule":"stage.unknown"`, `"step":"resolve"`}},
		{docs[8].doc, []string{`"stage":{"proposed_change":{"id":"pc-1","branch":"change-1"},"label":"branch-point","description":"","at_source":"branch_point"}`}},
	} {
		if b := string(mustMarshal(t, c.doc)); !containsAll(b, c.keys) {
			t.Errorf("%s does not carry every one of %q: %s", c.doc.Operation, c.keys, b)
		}
	}
	if b := string(mustMarshal(t, docs[6].doc)); strings.Contains(b, `"stage":{`) {
		t.Errorf("a refused resolution carries a stage block: %s", b)
	}

	// The keys are the contract's, so a document with a block misshapen is refused: the
	// test would pass a struct that marshalled nothing the schema checks.
	for _, c := range []struct {
		label string
		bend  func(doc *Document)
	}{
		{"a stage block with at_source guessed", func(doc *Document) { doc.Stage.AtSource = "guessed" }},
		{"a stage block whose ref has no /", func(doc *Document) { doc.Stage.Ref = "cabled" }},
		{"a stage block whose label has a /", func(doc *Document) { doc.Stage.Label = "change-1/cabled" }},
		{"a stage block with no proposed change id", func(doc *Document) { doc.Stage.ProposedChange.ID = "" }},
		{"subject.stage with no /", func(doc *Document) { doc.Subject.Stage = "cabled" }},
		{"subject.stage with whitespace", func(doc *Document) { doc.Subject.Stage = "change-1/the cabled" }},
	} {
		bad := stageDocuments()[0].doc
		c.bend(bad)
		if err := schema.Validate(mustAny(t, mustMarshal(t, bad))); err == nil {
			t.Errorf("%s satisfied the current findings.schema.json", c.label)
		}
	}
	shown := stageDocuments()[7].doc
	shown.Show.Record.Stage.AtSource = "guessed"
	if err := schema.Validate(mustAny(t, mustMarshal(t, shown))); err == nil {
		t.Error("a show record's stage with at_source guessed satisfied the show schema")
	}
}

// stageKeys are the serialised keys a document of stageDocuments is there to show.
func stageKeys(doc *Document) []string {
	var keys []string
	if doc.Subject != nil && doc.Subject.Stage != "" {
		keys = append(keys, `"subject":{`, `"stage":"`+doc.Subject.Stage+`"`)
	}
	if doc.Stage != nil && doc.Stage.Ref == "change-1/cabled" {
		keys = append(keys, `"stage":{"ref":"change-1/cabled","branch":"change-1","label":"cabled",`+
			`"proposed_change":{"id":"pc-1","name":"third link","branch":"change-1","draft":true},`+
			`"at":"2026-10-16T17:25:30.118244+00:00","at_source":"written","description":"after the link is cabled"}`)
	}
	if doc.Show != nil && doc.Show.Record != nil && doc.Show.Record.Stage != nil && doc.Show.Record.Stage.Label == "cabled" {
		keys = append(keys, `"stage":{"proposed_change":{"id":"pc-1","branch":"change-1"},"label":"cabled","description":"after the link is cabled","at_source":"written"}`)
	}
	return keys
}

// A document with no stage is M7's, key for key but for the show record's provenance:
// every new field is omitted when empty, so M7's own contract, which forbids additional
// properties, still accepts every shape M5 and M7 build once the record's scope and mapping
// are put back as the contract_version M7 wrote (017; drop017ShowProvenance), and the
// current one accepts them as built.
//
// M7's copy stays its milestone's when the newest contract moves on: the claim is that the
// older contract still accepts these documents.
func TestAnM7DocumentIsUnchanged(t *testing.T) {
	m7 := compileFeatureFindingsSchema(t, "007-eos-platform", "show.schema.json")
	current := compileCurrentFindingsSchema(t)
	for _, c := range m5Documents() {
		t.Run(c.label, func(t *testing.T) {
			b := mustMarshal(t, c.doc)
			if strings.Contains(string(b), `"stage":`) || strings.Contains(string(b), `"stages":`) {
				t.Errorf("a document with no stage names one: %s", b)
			}
			mustValidateBytes(t, m7, asEarlier(t, c.doc), c.label+" against M7's contract")
			mustValidateBytes(t, current, b, c.label+" against the current contract")
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

// The one line printed wherever a reference resolves is the commands contract's, word for
// word (specs/014-proposed-change-stages/contracts/stage-commands.md): a mark quotes its
// description, "" when none was written, on one line whatever it holds; a derived stage
// prints none; the branch point names main with no "branch". Resolution is the part after
// the reference, which stage plan prints after each compiled stage's.
func TestStageLine(t *testing.T) {
	for _, c := range []struct {
		block      StageBlock
		line, rest string
	}{
		{*cabledBlock(),
			`stage change-1/cabled: branch change-1 at 2026-10-16T17:25:30.118244+00:00 (written), "after the link is cabled"`,
			`branch change-1 at 2026-10-16T17:25:30.118244+00:00 (written), "after the link is cabled"`},
		{*liveBlock(),
			`stage change-1/live: branch change-1 at 2026-10-16T17:30:00.000000+00:00 (given), "after its configuration is live"`,
			`branch change-1 at 2026-10-16T17:30:00.000000+00:00 (given), "after its configuration is live"`},
		{*branchPointBlock(),
			`stage change-1/branch-point: main at 2026-10-16T17:20:19.944651+00:00 (branch point)`,
			`main at 2026-10-16T17:20:19.944651+00:00 (branch point)`},
		{*headBlock(),
			`stage change-1/head: branch change-1 at 2026-10-16T17:30:11.884302+00:00 (head)`,
			`branch change-1 at 2026-10-16T17:30:11.884302+00:00 (head)`},
		{StageBlock{Ref: "change-1/seeded", Branch: "change-1", Label: "seeded", At: "2026-10-16T16:00:00Z", AtSource: AtSourceGiven},
			`stage change-1/seeded: branch change-1 at 2026-10-16T16:00:00Z (given), ""`,
			`branch change-1 at 2026-10-16T16:00:00Z (given), ""`},
		{StageBlock{Ref: "change-1/big", Branch: "change-1", Label: "big", At: "2026-10-16T16:00:00Z", AtSource: AtSourceWritten,
			Description: "the \"big\" one\nsecond line"},
			`stage change-1/big: branch change-1 at 2026-10-16T16:00:00Z (written), "the \"big\" one\nsecond line"`,
			`branch change-1 at 2026-10-16T16:00:00Z (written), "the \"big\" one\nsecond line"`},
	} {
		if got := c.block.Line(); got != c.line {
			t.Errorf("Line() =\n  %s\nwant\n  %s", got, c.line)
		}
		if got := c.block.Resolution(); got != c.rest {
			t.Errorf("Resolution() =\n  %s\nwant\n  %s", got, c.rest)
		}
	}
	for source, want := range map[string]string{AtSourceGiven: "given", AtSourceWritten: "written",
		AtSourceBranchPoint: "branch point", AtSourceHead: "head"} {
		if got := AtSourceText(source); got != want {
			t.Errorf("AtSourceText(%q) = %q, want %q", source, got, want)
		}
	}
	if got := showStage("cabled", "", AtSourceWritten).Ref(); got != "change-1/cabled" {
		t.Errorf("ShowStage.Ref() = %q, want change-1/cabled", got)
	}
}

// schemaCheckStageDocuments are schema check's documents beside the stage kind on the
// default branch: present with its extension, absent, lacking attributes and the
// relationship, and present with the extension missing.
func schemaCheckStageDocuments() []labelledDocument {
	check := func(v StagesVerified) *Document {
		doc := NewDocument(OpSchemaCheck, &Subject{Branch: "fylgja-fixture"}, nil)
		v.Kind, v.File = "FylgjaStage", "schema/fylgja-stage.yaml"
		doc.Verified = libraryVerified(&v)
		return doc
	}
	return []labelledDocument{
		{"the kind present", check(StagesVerified{Present: true, Extension: true})},
		{"the kind absent", check(StagesVerified{})},
		{"the kind lacking attributes", check(StagesVerified{Missing: []string{"as_of", "proposed_change"}, Extension: true})},
		{"the extension missing", check(StagesVerified{Present: true})},
	}
}

// verified.stages satisfies the current contract in each of its four shapes, missing
// written as [] when nothing is, and a schema check that reports no stage kind carries no
// key: it is information beside the conformance answer, never a finding.
func TestVerifiedStagesSatisfiesSchema(t *testing.T) {
	schema := compileCurrentFindingsSchema(t)
	docs := schemaCheckStageDocuments()
	for _, c := range docs {
		t.Run(c.label, func(t *testing.T) {
			mustValidate(t, schema, c.doc, c.label)
			if c.doc.Status != StatusOK {
				t.Errorf("status %s, want ok: verified.stages is never a finding", c.doc.Status)
			}
		})
	}
	for i, want := range []string{
		`"stages":{"kind":"FylgjaStage","present":true,"missing":[],"extension":true,"file":"schema/fylgja-stage.yaml"}`,
		`"stages":{"kind":"FylgjaStage","present":false,"missing":[],"extension":false,"file":"schema/fylgja-stage.yaml"}`,
		`"stages":{"kind":"FylgjaStage","present":false,"missing":["as_of","proposed_change"],"extension":true,"file":"schema/fylgja-stage.yaml"}`,
		`"stages":{"kind":"FylgjaStage","present":true,"missing":[],"extension":false,"file":"schema/fylgja-stage.yaml"}`,
	} {
		if b := string(mustMarshal(t, docs[i].doc)); !strings.Contains(b, want) {
			t.Errorf("%s does not carry %s: %s", docs[i].label, want, b)
		}
	}
	none := NewDocument(OpSchemaCheck, &Subject{Branch: "fylgja-fixture"}, nil)
	none.Verified = libraryVerified(nil)
	if b := string(mustMarshal(t, none)); strings.Contains(b, `"stages"`) {
		t.Errorf("a schema check with no stage kind read carries the key: %s", b)
	}

	// The block is the contract's: another kind, another file, and a block with no extension
	// key are refused.
	for _, c := range []struct{ label, from, to string }{
		{"verified.stages naming another kind", `"kind":"FylgjaStage"`, `"kind":"CoreProposedChange"`},
		{"verified.stages naming another file", `"file":"schema/fylgja-stage.yaml"`, `"file":"schema/fylgja-stages.yaml"`},
		{"verified.stages with no extension key", `"extension":true,`, ``},
	} {
		raw := strings.Replace(string(mustMarshal(t, schemaCheckStageDocuments()[0].doc)), c.from, c.to, 1)
		if err := schema.Validate(mustAny(t, []byte(raw))); err == nil {
			t.Errorf("%s satisfied the current findings.schema.json", c.label)
		}
	}
}

// stageRow is one listed stage of the example proposed change.
func stageRow(b *StageBlock, twin bool) StageRow { return StageRow{StageBlock: *b, Twin: twin} }

// listAndPlanDocuments are the document shapes stage list and stage plan produce: a whole
// listing with no record beside main's warning, a filtered one whose record's stage is
// gone, one with an orphan, one with a reserved label, an empty one; a plan whose middle
// stage was refused at resolution, one whose branch point was refused at the read, one
// whose head read but did not compile, one with a computed step and the step to the head
// unchanged.
func listAndPlanDocuments() []labelledDocument {
	branch := "change-1"
	every := []StageRow{stageRow(branchPointBlock(), false), stageRow(cabledBlock(), false),
		stageRow(liveBlock(), false), stageRow(headBlock(), false)}

	var mainMoved List
	mainMoved.AddStep(Warning, StepResolve, RuleStageMainMoved, "change-1",
		"main has moved since change-1's branch point: its latest write is 2026-10-16T17:40:00.000000+00:00, the branch point 2026-10-16T17:20:19.944651+00:00; the branch point stage still reads main as it was then, and nothing is refused")
	all := NewDocument(OpStageList, nil, mainMoved)
	all.Stages = &StagesBlock{Rows: every}

	var moved List
	moved.Add(Warning, RuleStageTwinMoved, "change-1/cabled",
		"the twin was built from stage change-1/cabled at branch change-1, at 2026-10-16T17:25:30.118244+00:00 (written); change-1/cabled no longer exists; the twin is pinned to what it was built from")
	filtered := NewDocument(OpStageList, nil, moved)
	filtered.Stages = &StagesBlock{Branch: &branch,
		Rows: []StageRow{stageRow(branchPointBlock(), false), stageRow(headBlock(), false)},
		Record: &StageRecord{Ref: "change-1/cabled", ProposedChange: StageChangeRef{ID: "pc-1", Branch: "change-1"},
			Label: "cabled", Branch: "change-1", At: "2026-10-16T17:25:30.118244+00:00", AtSource: AtSourceWritten, State: "ready"}}

	var orphaned List
	orphaned.Add(Warning, RuleStageOrphaned, "st-9",
		`stage "cabled" (id st-9) names no proposed change: it was removed from its proposed change's fylgja_stages; delete the stage`)
	orphans := NewDocument(OpStageList, nil, orphaned)
	orphans.Stages = &StagesBlock{Orphans: []StageOrphan{{ID: "st-9", Label: "cabled",
		At: "2026-10-16T17:25:30.118244+00:00", AtSource: AtSourceWritten}}}

	var reserved List
	reserved.AddStep(Rejection, StepResolve, RuleStageLabelReserved, "change-1/head",
		`stage change-1/head is a mark labelled "head", which names the derived head of every proposed change and is reserved; relabel it (schema/README.md); the head of change-1 is still its derived stage`)
	relabel := NewDocument(OpStageList, nil, reserved)
	relabel.Stages = &StagesBlock{Rows: []StageRow{stageRow(branchPointBlock(), false), stageRow(headBlock(), false)}}

	empty := NewDocument(OpStageList, nil, nil)
	empty.Stages = &StagesBlock{}

	idOf := func(s string) *string { id := strings.Repeat(s, 32); return &id }
	counts := &ReadCounts{Devices: 3, Interfaces: 12, Links: 3, Artifacts: 3}
	compiled := func(b *StageBlock, id string) PlanStage {
		return PlanStage{Ref: b.Ref, Label: b.Label, Description: b.Description, AtSource: b.AtSource,
			Branch: b.Branch, At: b.At, BundleID: idOf(id), Read: counts}
	}
	notComputed := func(from, to, why string, fromID, toID *string) json.RawMessage {
		quote := func(id *string) string {
			if id == nil {
				return "null"
			}
			return `"` + *id + `"`
		}
		return json.RawMessage(`{"from":"` + from + `","to":"` + to + `","from_bundle_id":` + quote(fromID) +
			`,"to_bundle_id":` + quote(toID) + `,"computed":false,"not_computed":"` + why + `"}`)
	}

	var future List
	future.AddStep(Rejection, StepResolve, RuleStageAtUnresolved, "change-1/live",
		"stage change-1/live has at 2099-01-01T00:00:00Z (given), later than the current time 2026-10-16T17:35:00.000000Z: it seals nothing yet, and a twin from it could differ between two creates")
	refused := NewDocument(OpStagePlan, nil, future)
	refused.Plan = &PlanBlock{Branch: "change-1", ProposedChange: stageChange(),
		Stages: []PlanStage{
			compiled(cabledBlock(), "35"),
			{Ref: "change-1/live", Label: "live", Description: "after its configuration is live", AtSource: AtSourceGiven, Findings: future},
			compiled(headBlock(), "51"),
		},
		Steps: []json.RawMessage{
			notComputed("change-1/cabled", "change-1/live", "change-1/live was refused", idOf("35"), nil),
			notComputed("change-1/live", "change-1/head", "change-1/live was refused", nil, idOf("51")),
		}}

	var noContract List
	noContract.AddStep(Rejection, StepRead, RuleScopeEmpty, "tag:fylgja",
		"scope tag:fylgja selects no device on branch main")
	bare := NewDocument(OpStagePlan, nil, noContract)
	bp := branchPointBlock()
	bare.Plan = &PlanBlock{Branch: "change-1", ProposedChange: stageChange(),
		Stages: []PlanStage{{Ref: bp.Ref, Label: bp.Label, AtSource: bp.AtSource, Branch: bp.Branch, At: bp.At, Findings: noContract},
			compiled(headBlock(), "51")},
		Steps: []json.RawMessage{notComputed("change-1/branch-point", "change-1/head", "change-1/branch-point was refused", nil, idOf("51"))}}

	var notReady List
	notReady.AddStep(Rejection, StepRead, RuleArtifactNotReady, "n1", "artifact device-config of n1 on branch change-1 is Pending, not Ready")
	unbuilt := NewDocument(OpStagePlan, nil, notReady)
	head := headBlock()
	unbuilt.Plan = &PlanBlock{Branch: "change-1", ProposedChange: stageChange(),
		Stages: []PlanStage{compiled(branchPointBlock(), "35"),
			{Ref: head.Ref, Label: head.Label, AtSource: head.AtSource, Branch: head.Branch, At: head.At, Read: counts, Findings: notReady}},
		Steps: []json.RawMessage{notComputed("change-1/branch-point", "change-1/head", "change-1/head was refused", idOf("35"), nil)}}

	stepped := NewDocument(OpStagePlan, nil, nil)
	stepped.Plan = &PlanBlock{Branch: "change-1", ProposedChange: stageChange(),
		Stages: []PlanStage{compiled(branchPointBlock(), "35"), compiled(cabledBlock(), "9c"), compiled(headBlock(), "51")},
		Steps: []json.RawMessage{
			json.RawMessage(`{"from":"change-1/branch-point","to":"change-1/cabled","from_bundle_id":"` + *idOf("35") +
				`","to_bundle_id":"` + *idOf("9c") + `","computed":true,"unchanged":false,` +
				`"nodes":{"added":["n4"],"removed":[],"changed":[{"node":"n1","reasons":["bootstrap","mapping"]}]},` +
				`"links":{"added":[{"id":"n1:ethernet-1/3|n4:ethernet-1/1","a":{"node":"n1","port":"e1-3"},"b":{"node":"n4","port":"e1-1"}}],"removed":[]},` +
				`"artifacts":{"changed":[{"node":"n1","name":"device-config","from":"43e8fd0c2de5f4646f74a51d34742824","to":"9a0177b2e8c1d4f5a6b7c8d9e0f1a2b3"}]}}`),
			json.RawMessage(`{"from":"change-1/cabled","to":"change-1/head","from_bundle_id":"` + *idOf("9c") +
				`","to_bundle_id":"` + *idOf("51") + `","computed":true,"unchanged":true,` +
				`"nodes":{"added":[],"removed":[],"changed":[]},"links":{"added":[],"removed":[]},"artifacts":{"changed":[]}}`),
		}}

	return []labelledDocument{
		{"list, every proposed change, main moved", all},
		{"list, one branch, the record's stage gone", filtered},
		{"list, an orphaned stage", orphans},
		{"list, a reserved label", relabel},
		{"list, no open proposed change", empty},
		{"plan, the middle stage refused", refused},
		{"plan, the branch point refused at the read", bare},
		{"plan, the head read but not compiled", unbuilt},
		{"plan, a computed step and the step to the head unchanged", stepped},
	}
}

// stage list's and stage plan's documents satisfy the current contract, with every list and
// every nullable key the contract requires written even when empty.
func TestStageListAndPlanSatisfySchema(t *testing.T) {
	schema := compileCurrentFindingsSchema(t)
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
		{docs[0].doc, []string{`"stages":{"branch":null,`, `"orphans":[],"record":null`, `"twin":false`, `"rule":"stage.main.moved"`,
			`"at_source":"branch_point"`, `"at_source":"head"`}},
		{docs[1].doc, []string{`"branch":"change-1","rows":[`, `"record":{"ref":"change-1/cabled","proposed_change":{"id":"pc-1","branch":"change-1"},"label":"cabled","branch":"change-1",`,
			`"state":"ready","towards":null}`}},
		{docs[2].doc, []string{`"rows":[],"orphans":[{"id":"st-9","label":"cabled","at":"2026-10-16T17:25:30.118244+00:00","at_source":"written"}]`}},
		{docs[3].doc, []string{`"status":"rejected"`, `"rule":"stage.label.reserved"`}},
		{docs[4].doc, []string{`"stages":{"branch":null,"rows":[],"orphans":[],"record":null}`}},
		{docs[5].doc, []string{`"plan":{"branch":"change-1","proposed_change":{"id":"pc-1","name":"third link","branch":"change-1","draft":true},"stages":[`,
			`{"ref":"change-1/live","label":"live","description":"after its configuration is live","at_source":"given","snapshot_id":null,"bundle_id":null,"read":null,"findings":[{`}},
		{docs[6].doc, []string{`{"ref":"change-1/branch-point","label":"branch-point","description":"","at_source":"branch_point","branch":"main",`,
			`"snapshot_id":null,"bundle_id":null,"read":null,"findings":[{`, `"not_computed":"change-1/branch-point was refused"`}},
		{docs[7].doc, []string{`"snapshot_id":null,"bundle_id":null,"read":{"devices":3,`}},
		{docs[8].doc, []string{`"computed":true,"unchanged":true`, `"findings":[]`}},
	} {
		if b := string(mustMarshal(t, c.doc)); !containsAll(b, c.keys) {
			t.Errorf("%s does not carry every one of %q: %s", c.doc.Operation, c.keys, b)
		}
	}

	// The blocks are the contract's, so a misshapen one is refused: a computed step missing
	// its parts; a plan of one stage and no step, which no proposed change has, since the
	// branch point and the head are always there; a plan stage with no findings key; an
	// orphan whose at is a derived stage's; a row with at_source guessed; a stage block with
	// no proposed change.
	bad := listAndPlanDocuments()[8].doc
	bad.Plan.Steps[0] = json.RawMessage(`{"from":"change-1/branch-point","to":"change-1/cabled","from_bundle_id":null,"to_bundle_id":null,"computed":true}`)
	if err := schema.Validate(mustAny(t, mustMarshal(t, bad))); err == nil {
		t.Error("a computed step with no parts satisfied the stages schema")
	}
	one := listAndPlanDocuments()[8].doc
	one.Plan.Stages, one.Plan.Steps = one.Plan.Stages[:1], nil
	if err := schema.Validate(mustAny(t, mustMarshal(t, one))); err == nil {
		t.Error("a plan of one stage and no step satisfied the stages schema")
	}
	unfound := strings.Replace(string(mustMarshal(t, listAndPlanDocuments()[8].doc)), `,"findings":[]`, ``, 1)
	if err := schema.Validate(mustAny(t, []byte(unfound))); err == nil {
		t.Error("a plan stage with no findings key satisfied the stages schema")
	}
	headOrphan := listAndPlanDocuments()[2].doc
	headOrphan.Stages.Orphans[0].AtSource = AtSourceHead
	if err := schema.Validate(mustAny(t, mustMarshal(t, headOrphan))); err == nil {
		t.Error("an orphan with at_source head satisfied the stages schema")
	}
	guessed := listAndPlanDocuments()[0].doc
	guessed.Stages.Rows[1].AtSource = "guessed"
	if err := schema.Validate(mustAny(t, mustMarshal(t, guessed))); err == nil {
		t.Error("a row with at_source guessed satisfied the stages schema")
	}
	changeless := strings.Replace(string(mustMarshal(t, listAndPlanDocuments()[0].doc)),
		`"proposed_change":{"id":"pc-1","name":"third link","branch":"change-1","draft":true},`, ``, 1)
	if err := schema.Validate(mustAny(t, []byte(changeless))); err == nil {
		t.Error("a row with no proposed change satisfied the stages schema")
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

func ptr(s string) *string { return &s }
