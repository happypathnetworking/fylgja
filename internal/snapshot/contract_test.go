package snapshot

import (
	"bytes"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/santhosh-tekuri/jsonschema/v6"
)

// contract019 is the directory 019's copy of snapshot.schema.json, the snapshot 1 that 016
// moves to 2, is frozen under.
const contract019 = "019-following-removed"

// snapshotSchema compiles the current contract, contracts/snapshot.schema.json, with CTM
// 2's contract and the probe declaration's registered under their $ids for the snapshot's
// ctm and probes $refs.
func snapshotSchema(t *testing.T) *jsonschema.Schema {
	t.Helper()
	return snapshotSchemaOf(t, "")
}

// snapshotSchemaOf is feature's copy of snapshot.schema.json: "" is the current contract, and
// an earlier feature's is its frozen copy under testdata/contracts/<feature>/. CTM 2's
// contract, which no feature since 017 moves, and the probe declaration's, which 016 adds
// and 019's copy does not reference, are read from contracts/ for either.
func snapshotSchemaOf(t *testing.T, feature string) *jsonschema.Schema {
	t.Helper()
	c := jsonschema.NewCompiler()
	var snapshotID string
	for _, name := range []string{"ctm.schema.json", "probes.schema.json", "snapshot.schema.json"} {
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

// Every snapshot Fylgja writes is a document of the contract, a 2, with no probes and with
// some, and the contract refuses what Unmarshal refuses for its shape: an element that is
// not the declaration's probe, and another version, 1 among them, which is read and never
// written.
func TestSnapshotSatisfiesTheContract(t *testing.T) {
	schema := snapshotSchema(t)
	for _, tc := range []struct {
		name  string
		decls []string
	}{
		{"three-node", nil},
		{"lossy", nil},
		{"mixed", nil},
		{"three-node", []string{"n1-loop", "n2-loop"}},
		{"mixed", []string{"e1-loop"}},
	} {
		name := tc.name
		t.Run(strings.Join(append([]string{name}, tc.decls...), "+"), func(t *testing.T) {
			stored, err := Marshal(Take(fixture(t, name), declared(t, tc.decls...)))
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
		{"an empty probe", func(m map[string]any) { m["probes"] = []any{map[string]any{}} }},
		{"a probe with an unknown key", func(m map[string]any) { element(m, 0)["comment"] = "a note" }},
		{"a probe with one endpoint", func(m map[string]any) {
			element(m, 0)["endpoints"] = element(m, 0)["endpoints"].([]any)[:1]
		}},
		{"an address with no prefix length", func(m map[string]any) { endpoint(m, 1, 0)["address"] = "10.2.10.2" }},
		{"snapshot_version 1", func(m map[string]any) { m["snapshot_version"] = "1" }},
		{"snapshot_version 3", func(m map[string]any) { m["snapshot_version"] = "3" }},
	} {
		t.Run(tc.name, func(t *testing.T) {
			m := probed(t)
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
// the snapshots filed as 1 under the module root's testdata/snapshot/ and a take's stored
// form as 018 wrote it, and refuses a probe and another version, 2 among them, as it did
// when 019 left it: a 1 is read as a 2 (R-05), and its contract is unmoved.
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
			stored, err := Marshal(Take(fixture(t, name), nil))
			if err != nil {
				t.Fatal(err)
			}
			if err := validate(t, schema, asVersion1(t, stored)); err != nil {
				t.Errorf("%s's take as a 1 does not satisfy 019's snapshot.schema.json:\n%v", name, err)
			}
		})
	}
	for _, change := range []func(m map[string]any){
		func(m map[string]any) { m["probes"] = []any{map[string]any{}} },
		func(m map[string]any) { m["snapshot_version"] = "2" },
	} {
		m := document(t)
		m["snapshot_version"] = "1"
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

// acrossFields are the declaration's rules that read across fields, which a JSON Schema
// cannot say: the contract accepts their elements and the reader refuses them.
var acrossFields = map[string]bool{
	"probe.name.duplicate":    true,
	"probe.gateway.outside":   true,
	"probe.family.mixed":      true,
	"probe.address.duplicate": true,
}

// A 2 whose element is not the declaration's probe is snapshot.invalid at the element's
// field (FR-004), and the contract refuses it too unless the rule reads across fields: each
// of the declaration's invalid files under testdata/probes/invalid/, its list wrapped as a
// 2's. Two are not the element's: probes.version.unsupported is the declaration file's
// version, which a snapshot does not carry, and probe.format.unknown names the formats a
// registry loaded, which the snapshot does not hold; the server does, before it files.
func TestANonContractElementIsRefused(t *testing.T) {
	schema := snapshotSchema(t)
	paths, err := filepath.Glob(filepath.Join("..", "..", "testdata", "probes", "invalid", "*.json"))
	if err != nil {
		t.Fatal(err)
	}
	var checked int
	for _, path := range paths {
		rule := strings.TrimSuffix(filepath.Base(path), ".json")
		if rule == "probes.version.unsupported" || rule == "probe.format.unknown" {
			continue
		}
		checked++
		t.Run(rule, func(t *testing.T) {
			b, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			var decl struct {
				Probes []any `json:"probes"`
			}
			if err := json.Unmarshal(b, &decl); err != nil {
				t.Fatal(err)
			}
			m := document(t)
			m["probes"] = decl.Probes
			delete(m, "snapshot_id")
			doc := encode(t, m)

			_, err = Unmarshal(doc)
			var invalid *InvalidError
			if !errors.As(err, &invalid) || !strings.HasPrefix(invalid.Field, "probes[") {
				t.Fatalf("Unmarshal = %T %v; want snapshot.invalid at an element's field", err, err)
			}
			t.Logf("%s: %s: %s", rule, invalid.Field, invalid.Message)

			schemaErr := validate(t, schema, doc)
			switch {
			case acrossFields[rule] && schemaErr != nil:
				t.Errorf("snapshot.schema.json refuses it, a rule across fields the reader alone holds:\n%v", schemaErr)
			case !acrossFields[rule] && schemaErr == nil:
				t.Error("snapshot.schema.json accepts it, which the reader refuses")
			}
		})
	}
	if checked != 8 {
		t.Errorf("%d invalid declarations wrapped, want 8 of %d: %v", checked, len(paths), paths)
	}
}
