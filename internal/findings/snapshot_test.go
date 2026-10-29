package findings

import (
	"encoding/json"
	"strings"
	"testing"

	"github.com/santhosh-tekuri/jsonschema/v6"
)

// 018's blocks (specs/018-snapshots/data-model.md §5.3): a document of a twin with no
// snapshot is the one 017's contract accepts, and a document naming one is the current
// contract's alone.

// snapshotFeature is the directory 017's copies of the five contracts 018 moves are frozen
// under, as git log names the feature that last wrote each.
const snapshotFeature = "017-dcim-reader"

// contract018 is the directory 018's copies of the findings contract and the show block, the
// two 019 moves, are frozen under.
const contract018 = "018-snapshots"

// contract019 is the directory 019's copies of the findings contract and the step, verify and
// rehearsal blocks, the four 016 moves, are frozen under; its show and stages blocks, which
// 016 does not move, are read from contracts/.
const contract019 = "019-following-removed"

// compile017FindingsSchema is 017's findings contract, with the four blocks 018 moves frozen
// beside it and verify.schema.json, which 018 does not move, read from contracts/.
func compile017FindingsSchema(t *testing.T) *jsonschema.Schema {
	t.Helper()
	return compileFeatureFindingsSchema(t, snapshotFeature, currentResources...)
}

// as017 marshals a document as 017's contract is asked to validate it: with the snapshot
// ids 018 writes as null taken out (drop018Snapshots) and the show kind as 017 wrote it
// (restore018Kind), and nothing else, since 017's is the contract that put the record's
// scope and mapping in place of contract_version.
func as017(t *testing.T, doc *Document) []byte {
	t.Helper()
	return mutated(t, doc, func(doc map[string]any) {
		restore018Kind(doc)
		drop018Snapshots(doc)
		drop016NullLoss(doc)
	})
}

// restore018Kind gives a show block of kind snapshot (019) the kind every build before 019
// wrote for the same twin, not following: pinned when its record names an at, and frozen
// otherwise. Every other block is left as it is, so an earlier contract is still asked
// about everything else 019 writes.
func restore018Kind(doc map[string]any) {
	show, ok := doc["show"].(map[string]any)
	if !ok || show["kind"] != ShowKindSnapshot {
		return
	}
	show["kind"] = "frozen"
	if record, ok := show["record"].(map[string]any); ok {
		if at, _ := record["at"].(string); at != "" {
			show["kind"] = "pinned"
		}
	}
}

// mutated is doc marshalled, changed as a generic object by change, and marshalled again.
func mutated(t *testing.T, doc *Document, change func(map[string]any)) []byte {
	t.Helper()
	var generic map[string]any
	if err := json.Unmarshal(mustMarshal(t, doc), &generic); err != nil {
		t.Fatal(err)
	}
	change(generic)
	b, err := json.Marshal(generic)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

// noSnapshotDocuments are every document this package's tests build for a twin, a read, a
// plan, a step or a rehearsal that names no snapshot, each dry run of M2's and M4's given
// the artifacts every dry run has carried since M5 (withDryRunArtifacts).
func noSnapshotDocuments() []labelledDocument {
	var docs []labelledDocument
	for _, set := range [][]labelledDocument{m2Documents(), m4Documents(), m5Documents(), scopedDocuments(),
		stageDocuments(), listAndPlanDocuments(), stepDocuments(), showStepDocuments(), listStepDocuments(),
		rehearsalDocuments(), rehearsalTwinDocuments(), verifyDocuments()} {
		docs = append(docs, set...)
	}
	for i, c := range docs {
		if c.doc.DryRun != nil && len(c.doc.DryRun.Nodes) > 0 && c.doc.DryRun.Nodes[0].Artifact == nil {
			docs[i].doc = withDryRunArtifacts(c.doc, m5Checksum)
		}
	}
	return docs
}

// A document that names no snapshot is 017's, key for key: every key 018 adds is omitted
// when empty or written as null, so 017's contract, which forbids additional properties,
// still accepts every shape once the nulls are taken out, and the current one accepts it as
// built. 017's copies stay as 017 left them when the newest contract moves on: the claim is
// that the older contract still accepts these documents.
func TestA017DocumentIsUnchanged(t *testing.T) {
	v017 := compile017FindingsSchema(t)
	current := compileCurrentFindingsSchema(t)
	for _, c := range noSnapshotDocuments() {
		t.Run(c.label, func(t *testing.T) {
			b := mustMarshal(t, c.doc)
			if strings.Contains(string(b), `"snapshot_id":"`) || strings.Contains(string(b), `"snapshot":"`) {
				t.Errorf("a document with no snapshot names one: %s", b)
			}
			mustValidateBytes(t, v017, as017(t, c.doc), c.label+" against 017's contract")
			mustValidateBytes(t, current, b, c.label+" against the current contract")
		})
	}
	// M4's following blocks, which 019 removed, as 017 wrote them.
	for _, c := range m4FollowingDocuments() {
		t.Run(c.label, func(t *testing.T) {
			mustValidateBytes(t, v017, mutated(t, c.doc, func(doc map[string]any) {
				drop018Snapshots(doc)
				c.restore(doc)
			}), c.label+" against 017's contract")
		})
	}
}

// Every document this package builds is 018's, the ones that name a snapshot and the ones
// that name none, and 018's contract accepts each as built. 018's copies stay as 018 left
// them when 019 moves the findings and show contracts on: the claim is that the older
// contract still accepts these documents. So does it the documents 018 wrote with following
// (followingDocuments), which this build no longer writes.
func TestAn018DocumentIsUnchanged(t *testing.T) {
	v018 := compileFeatureFindingsSchema(t, contract018, currentResources...)
	for _, c := range append(noSnapshotDocuments(), snapshotDocuments()...) {
		t.Run(c.label, func(t *testing.T) {
			mustValidateBytes(t, v018, mutated(t, c.doc, restore018Kind), c.label+" against 018's contract")
		})
	}
	for _, c := range followingDocuments() {
		t.Run(c.label, func(t *testing.T) {
			mustValidateBytes(t, v018, mutated(t, c.doc, c.restore), c.label+" against 018's contract")
		})
	}
}

// Every document this package builds is 019's, its step block's null loss taken out
// (drop016NullLoss): 019's copies stay as 019 left them when 016 moves the findings, step,
// verify and rehearsal contracts on, and the claim is that the older contract still accepts
// these documents. A step document whose loss is set is 016's alone (TestStepLossDocuments).
func TestA019DocumentIsUnchanged(t *testing.T) {
	v019 := compileFeatureFindingsSchema(t, contract019, currentResources...)
	for _, c := range append(noSnapshotDocuments(), snapshotDocuments()...) {
		t.Run(c.label, func(t *testing.T) {
			mustValidateBytes(t, v019, mutated(t, c.doc, drop016NullLoss), c.label+" against 019's contract")
		})
	}
}

// 019 removed the following block and dry_run.follow from the contract (formats.md §2), and
// the show kinds pinned, frozen and following with the show's following and last check
// (§3): the current findings.schema.json refuses every document an earlier build wrote with
// any of them, which 018's copy accepts (TestAn018DocumentIsUnchanged), and accepts each as
// this build writes it in its place.
func TestFollowingLeftTheContract(t *testing.T) {
	current := compileCurrentFindingsSchema(t)
	for _, c := range followingDocuments() {
		t.Run(c.label, func(t *testing.T) {
			b := mutated(t, c.doc, c.restore)
			if err := current.Validate(mustAny(t, b)); err == nil {
				t.Errorf("the current contract accepts a document carrying following: %s", b)
			}
			mustValidateBytes(t, current, mustMarshal(t, c.doc), c.label+" as this build writes it")
		})
	}
}

// followingDocuments are every shape an earlier build wrote with following: M4's
// (m4FollowingDocuments), and the dry runs of the two reasons added after it, a stage's
// (014) and a snapshot's (018).
func followingDocuments() []earlierDocument {
	stage := followingDryRun("dry run of a stage", OpTwinCreate, map[string]any{"enabled": false, "reason": "stage"})
	stage.doc.Subject = &Subject{Branch: "change-1", At: "2026-10-16T17:30:00Z", Stage: "change-1/cabled"}
	fromSnapshot := followingDryRun("dry run of a snapshot", OpTwinCreate, map[string]any{"enabled": false, "reason": "snapshot"})
	fromSnapshot.doc.Subject = &Subject{Snapshot: snapshotID}
	fromSnapshot.doc.SnapshotID = snapshotID
	fromSnapshot.doc.BundleID = strings.Repeat("43", 32)
	return append(m4FollowingDocuments(), stage, fromSnapshot)
}

// snapshotID and stepSnapshotID are two snapshots' ids: the first the fixture's
// (testdata/snapshot/three-node.json), the second any other.
var (
	snapshotID     = "6a8a77fc65bdf47b9bb3a753d7709875671df20e32838344f29cfba46a13f6d6"
	stepSnapshotID = strings.Repeat("5e", 32)
)

// snapshotDocuments are 018's documents, each naming a snapshot where 018 puts one: a
// compile's top level and subject, a create's dry run from --snapshot, a plan's compiled
// stages, a step's two sides and its target, a rehearsal's compiled stages, a show of a
// twin built from a snapshot, and a show of a stepped record naming each side's.
func snapshotDocuments() []labelledDocument {
	compiled := NewDocument(OpCompile, &Subject{Snapshot: "snapshot.json", Out: "/tmp/b"}, nil)
	compiled.SnapshotID = snapshotID
	compiled.BundleID = strings.Repeat("43", 32)

	dry := NewDocument(OpTwinCreate, &Subject{Snapshot: snapshotID}, nil)
	dry.SnapshotID = snapshotID
	dry.BundleID = strings.Repeat("43", 32)
	dry.DryRun = &DryRunBlock{Nodes: []DryRunNode{}, Host: DryRunHost{}, Verdict: VerdictClear}

	planned := listAndPlanDocuments()[7].doc
	for i := range planned.Plan.Stages {
		if planned.Plan.Stages[i].BundleID != nil {
			planned.Plan.Stages[i].SnapshotID = &snapshotID
		}
	}

	stepped := stepDocuments()[1].doc
	stepped.SnapshotID = stepSnapshotID
	stepped.Step.From.SnapshotID = snapshotID
	stepped.Step.To.SnapshotID = stepSnapshotID

	rehearsed := rehearsalDocuments()[0].doc
	for i := range rehearsed.Rehearsal.Stages {
		if rehearsed.Rehearsal.Stages[i].BundleID != nil {
			rehearsed.Rehearsal.Stages[i].SnapshotID = &snapshotID
		}
	}

	frozen := showStepDocuments()[2].doc
	frozen.Show.Record.SnapshotID = &snapshotID
	frozen.Show.Record.Source = "snapshot"
	frozen.Show.Record.Stage = nil

	shownStep := showStepDocuments()[0].doc
	shownStep.Show.Record.SnapshotID = &stepSnapshotID
	shownStep.Show.Record.Step.From.SnapshotID = snapshotID
	shownStep.Show.Record.Step.To.SnapshotID = stepSnapshotID

	return []labelledDocument{
		{"compile of a snapshot", compiled},
		{"create from a snapshot, dry run", dry},
		{"plan naming each compiled stage's snapshot", planned},
		{"step naming each side's snapshot", stepped},
		{"rehearsal naming each compiled stage's snapshot", rehearsed},
		{"show of a twin built from a snapshot", frozen},
		{"show of a step naming each side's snapshot", shownStep},
	}
}

// Every block 018 moves names its snapshot as the contract says, and only the current
// contract accepts it: 017's forbids every key 018 adds, so a document naming a snapshot is
// refused there, as a document of a later feature should be.
func TestSnapshotBlocksSatisfyTheContract(t *testing.T) {
	v017 := compile017FindingsSchema(t)
	current := compileCurrentFindingsSchema(t)
	for _, c := range snapshotDocuments() {
		t.Run(c.label, func(t *testing.T) {
			b := mustMarshal(t, c.doc)
			if !strings.Contains(string(b), `"snapshot_id":"`) && !strings.Contains(string(b), `"snapshot":"`) {
				t.Fatalf("a snapshot document names none: %s", b)
			}
			mustValidateBytes(t, current, b, c.label)
			mustCarryNoContent(t, c.doc, c.label)
			if err := v017.Validate(mustAny(t, as017(t, c.doc))); err == nil {
				t.Errorf("017's contract accepts a document naming a snapshot: %s", b)
			}
		})
	}

	// The keys as the contract names them: the record's, each plan stage's and each rehearsal
	// stage's written as null when the block names none, never left out.
	for _, c := range []struct {
		doc  *Document
		keys []string
	}{
		{showStepDocuments()[2].doc, []string{`"record":{"branch":"change-1","at":"2026-10-16T17:30:00.000000+00:00","snapshot_id":null,"bundle_id":`}},
		{snapshotDocuments()[5].doc, []string{`"snapshot_id":"` + snapshotID + `","bundle_id":`, `"source":"snapshot"`}},
		{snapshotDocuments()[3].doc, []string{`"snapshot_id":"` + stepSnapshotID + `","bundle_id":`,
			`"from":{"stage":{`, `"snapshot_id":"` + snapshotID + `","bundle_id":"` + stepFromID + `"`}},
		{snapshotDocuments()[0].doc, []string{`"subject":{"out":"/tmp/b","snapshot":"snapshot.json"},"snapshot_id":"` + snapshotID + `","bundle_id":`}},
		{snapshotDocuments()[1].doc, []string{`"subject":{"snapshot":"` + snapshotID + `"},"snapshot_id":"` + snapshotID + `","bundle_id":`}},
	} {
		if b := string(mustMarshal(t, c.doc)); !containsAll(b, c.keys) {
			t.Errorf("%s does not carry every one of %q: %s", c.doc.Operation, c.keys, b)
		}
	}

	// What the contract refuses: an id that is not one, at each place; a key the contract
	// requires left out instead of written as null.
	refusals := []struct {
		label  string
		doc    *Document
		change func(map[string]any)
	}{
		{"top level not an id", snapshotDocuments()[0].doc, func(d map[string]any) { d["snapshot_id"] = "ABC" }},
		{"subject.snapshot not a string", snapshotDocuments()[0].doc, func(d map[string]any) {
			d["subject"].(map[string]any)["snapshot"] = 1
		}},
		{"show record not an id", snapshotDocuments()[5].doc, func(d map[string]any) {
			d["show"].(map[string]any)["record"].(map[string]any)["snapshot_id"] = strings.Repeat("A", 64)
		}},
		{"show record without the key", showStepDocuments()[2].doc, func(d map[string]any) {
			delete(d["show"].(map[string]any)["record"].(map[string]any), "snapshot_id")
		}},
		{"show record's step side not an id", snapshotDocuments()[6].doc, func(d map[string]any) {
			step := d["show"].(map[string]any)["record"].(map[string]any)["step"].(map[string]any)
			step["from"].(map[string]any)["snapshot_id"] = nil
		}},
		{"step side not an id", snapshotDocuments()[3].doc, func(d map[string]any) {
			d["step"].(map[string]any)["to"].(map[string]any)["snapshot_id"] = "5e"
		}},
		{"plan stage without the key", listAndPlanDocuments()[7].doc, func(d map[string]any) {
			delete(d["plan"].(map[string]any)["stages"].([]any)[0].(map[string]any), "snapshot_id")
		}},
		{"rehearsal stage without the key", rehearsalDocuments()[0].doc, func(d map[string]any) {
			delete(d["rehearsal"].(map[string]any)["stages"].([]any)[0].(map[string]any), "snapshot_id")
		}},
		{"rehearsal stage not an id", snapshotDocuments()[4].doc, func(d map[string]any) {
			d["rehearsal"].(map[string]any)["stages"].([]any)[0].(map[string]any)["snapshot_id"] = "x"
		}},
	}
	for _, c := range refusals {
		if err := current.Validate(mustAny(t, mutated(t, c.doc, c.change))); err == nil {
			t.Errorf("%s: the current contract accepts it", c.label)
		}
	}
}
