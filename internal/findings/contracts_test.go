package findings

import (
	"encoding/json"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"

	"github.com/santhosh-tekuri/jsonschema/v6"
)

// The contracts' helpers every test of this package reads its schemas by, and the shapes the
// core's documents still carry of 014's and 015's records: they were stages_test.go's and
// rehearsal_test.go's, which went with the stage list, the plan and the rehearsal at 020
// (T035), whose documents are the orchestrator's, held by its own tests to these contracts.

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

// closeOrder is feature's place in the order the features closed, as a string to compare:
// its directory's name, but for 016's, which closed after 019 (Release 0.3 ran 017, 018,
// 019, then 016), so that its copies are later than 019's though its number is lower.
func closeOrder(feature string) string {
	if feature == contract016 {
		return contract019 + "+"
	}
	return feature
}

// compileFeatureFindingsSchema loads one feature's copy of the findings contract with the
// blocks it references added under their own $ids. A feature's findings contract that
// refers to a block cannot compile without it, so a caller names every block its
// feature's copy refers to: currentResources for the current contract. A block the
// feature's directory does not hold had not moved since that feature, so the current one
// is read in its place: the next later feature's copy that holds it, or the current one when
// none does. So verify.schema.json beside 017's and 018's copies is 019's, which froze it as
// it stood from 017 until 016 moved it, and the stages block beside 018's is the current one.
// "Later" is in the order the features closed (closeOrder), so every block beside 016's copy
// is the current one.
func compileFeatureFindingsSchema(t *testing.T, feature string, resources ...string) *jsonschema.Schema {
	t.Helper()
	dirs, err := os.ReadDir(filepath.Join("testdata", "contracts"))
	if err != nil {
		t.Fatal(err)
	}
	frozen := make([]string, 0, len(dirs))
	for _, d := range dirs {
		frozen = append(frozen, d.Name())
	}
	slices.SortFunc(frozen, func(a, b string) int { return strings.Compare(closeOrder(a), closeOrder(b)) })
	load := func(name string) any {
		path := contractPath(feature, name)
		if _, err := os.Stat(path); err != nil && name != "findings.schema.json" {
			path = contractPath(currentContract, name)
			for _, d := range frozen {
				if later := contractPath(d, name); feature != currentContract && closeOrder(d) > closeOrder(feature) {
					if _, err := os.Stat(later); err == nil {
						path = later
						break
					}
				}
			}
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

// showStage is a stage as twin.json 6 records it, of the example proposed change.
func showStage(label, description, source string) *ShowStage {
	return &ShowStage{ProposedChange: StageChangeRef{ID: "pc-1", Branch: "change-1"}, Label: label,
		Description: description, AtSource: source}
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

func containsAll(s string, subs []string) bool {
	for _, sub := range subs {
		if !strings.Contains(s, sub) {
			return false
		}
	}
	return true
}

func ptr(s string) *string { return &s }

// rehearseRunID is the run a version 7 record names as the rehearsal whose baseline the
// twin is (015): twin show and twin verify still carry it for such a record.
const rehearseRunID = "01a1b2c3-0000-7000-8000-0000000000aa"

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
