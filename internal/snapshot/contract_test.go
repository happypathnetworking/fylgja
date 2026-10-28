package snapshot

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"github.com/santhosh-tekuri/jsonschema/v6"
)

// contract019 is the directory 019's copy of snapshot.schema.json, the snapshot 1 that 016
// moves to 2, is frozen under.
const contract019 = "019-following-removed"

// snapshotSchema compiles the current contract, contracts/snapshot.schema.json, with CTM
// 2's contract registered under its $id for the snapshot's ctm $ref.
func snapshotSchema(t *testing.T) *jsonschema.Schema {
	t.Helper()
	return snapshotSchemaOf(t, "")
}

// snapshotSchemaOf is feature's copy of snapshot.schema.json: "" is the current contract, and
// an earlier feature's is its frozen copy under testdata/contracts/<feature>/. CTM 2's
// contract, which no feature since 017 moves, is read from contracts/ for either.
func snapshotSchemaOf(t *testing.T, feature string) *jsonschema.Schema {
	t.Helper()
	c := jsonschema.NewCompiler()
	var snapshotID string
	for _, name := range []string{"ctm.schema.json", "snapshot.schema.json"} {
		path := filepath.Join("..", "..", "contracts", name)
		if feature != "" && name == "snapshot.schema.json" {
			path = filepath.Join("testdata", "contracts", feature, name)
		}
		f, err := os.Open(path)
		if err != nil {
			t.Fatal(err)
		}
		doc, err := jsonschema.UnmarshalJSON(f)
		_ = f.Close()
		if err != nil {
			t.Fatalf("parsing %s: %v", path, err)
		}
		id := doc.(map[string]any)["$id"].(string)
		if err := c.AddResource(id, doc); err != nil {
			t.Fatalf("adding %s: %v", path, err)
		}
		snapshotID = id
	}
	s, err := c.Compile(snapshotID)
	if err != nil {
		t.Fatalf("compiling %s's snapshot.schema.json (a consumer could not load this schema): %v", feature, err)
	}
	return s
}

func validate(t *testing.T, s *jsonschema.Schema, b []byte) error {
	t.Helper()
	v, err := jsonschema.UnmarshalJSON(bytes.NewReader(b))
	if err != nil {
		t.Fatalf("re-reading emitted JSON: %v", err)
	}
	return s.Validate(v)
}

// Every snapshot Fylgja writes is a document of the contract, and the contract refuses
// what Unmarshal refuses for its shape: a probe, and another version.
func TestSnapshotSatisfiesTheContract(t *testing.T) {
	schema := snapshotSchema(t)
	for _, name := range []string{"three-node", "lossy", "mixed"} {
		t.Run(name, func(t *testing.T) {
			stored, err := Marshal(Take(fixture(t, name)))
			if err != nil {
				t.Fatal(err)
			}
			if err := validate(t, schema, stored); err != nil {
				t.Errorf("the stored form of %s's take does not satisfy snapshot.schema.json:\n%v", name, err)
			}
		})
	}

	for _, tc := range []struct {
		name   string
		change func(m map[string]any)
	}{
		{"a probe", func(m map[string]any) { m["probes"] = []any{map[string]any{}} }},
		{"snapshot_version 2", func(m map[string]any) { m["snapshot_version"] = "2" }},
	} {
		t.Run(tc.name, func(t *testing.T) {
			m := document(t)
			tc.change(m)
			b, err := json.Marshal(m)
			if err != nil {
				t.Fatal(err)
			}
			if err := validate(t, schema, b); err == nil {
				t.Errorf("snapshot.schema.json accepted %s", tc.name)
			}
		})
	}
}

// 019's copy of the contract, the snapshot 1 every build before 016 wrote, loads and accepts
// the snapshots filed as 1 under the module root's testdata/snapshot/, and refuses a probe
// and another version, as it did when 019 left it.
func TestSnapshot1FrozenCopy(t *testing.T) {
	schema := snapshotSchemaOf(t, contract019)
	for _, name := range []string{"three-node", "lossy", "mixed"} {
		t.Run(name, func(t *testing.T) {
			b, err := os.ReadFile(filepath.Join("..", "..", "testdata", "snapshot", name+".json"))
			if err != nil {
				t.Fatal(err)
			}
			if err := validate(t, schema, b); err != nil {
				t.Errorf("testdata/snapshot/%s.json does not satisfy 019's snapshot.schema.json:\n%v", name, err)
			}
		})
	}
	for _, change := range []func(m map[string]any){
		func(m map[string]any) { m["probes"] = []any{map[string]any{}} },
		func(m map[string]any) { m["snapshot_version"] = "2" },
	} {
		m := document(t)
		change(m)
		b, err := json.Marshal(m)
		if err != nil {
			t.Fatal(err)
		}
		if err := validate(t, schema, b); err == nil {
			t.Errorf("019's snapshot.schema.json accepted %s", b)
		}
	}
}
