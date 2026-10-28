package compiler

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"github.com/santhosh-tekuri/jsonschema/v6"
)

// The JSON schemas under contracts/ are what M2 builds against. Describing them is not
// the same as enforcing them: this suite loads each schema as a schema — which is how a
// consumer will use it — and validates real emitted documents against it.
//
// That distinction is not academic: a schema can describe every document correctly and
// still carry an unresolvable $ref, so that nothing can load it.
//
// contractsDir is the module root's contracts/, which holds the current contract: only it
// describes what this build emits. An older copy can forbid what the build now writes by
// additionalProperties (M5's manifest and CTM gained an `artifact` entry, M7's manifest a
// node's `bootstrap` entry, M12's mapping rows a required `enabled`), so a test read
// against one would fail for a format change, not a defect.
func contractsDir() string {
	return filepath.Join("..", "..", "contracts")
}

func compileSchema(t *testing.T, name string) *jsonschema.Schema {
	t.Helper()
	path := filepath.Join(contractsDir(), name)
	f, err := os.Open(path)
	if err != nil {
		t.Fatalf("opening %s: %v", name, err)
	}
	defer func() { _ = f.Close() }()
	doc, err := jsonschema.UnmarshalJSON(f)
	if err != nil {
		t.Fatalf("parsing %s: %v", name, err)
	}
	c := jsonschema.NewCompiler()
	// findings.schema.json refers to show.schema.json (M4), stages.schema.json (014),
	// step.schema.json (M11), verify.schema.json (M12) and rehearsal.schema.json (015) by
	// their published $ids, which no consumer resolves over the network; each is supplied
	// from the same directory, as internal/findings supplies them.
	for _, ref := range []string{"show.schema.json", "stages.schema.json", "step.schema.json", "verify.schema.json", "rehearsal.schema.json"} {
		rf, err := os.Open(filepath.Join(contractsDir(), ref))
		if err != nil {
			t.Fatalf("opening %s: %v", ref, err)
		}
		refDoc, err := jsonschema.UnmarshalJSON(rf)
		_ = rf.Close()
		if err != nil {
			t.Fatalf("parsing %s: %v", ref, err)
		}
		if err := c.AddResource("https://github.com/happypathnetworking/fylgja/schemas/"+ref, refDoc); err != nil {
			t.Fatalf("adding %s: %v", ref, err)
		}
	}
	if err := c.AddResource(name, doc); err != nil {
		t.Fatalf("adding %s: %v", name, err)
	}
	// Compilation is where an unresolvable reference surfaces.
	s, err := c.Compile(name)
	if err != nil {
		t.Fatalf("compiling %s (a consumer could not load this schema): %v", name, err)
	}
	return s
}

// contract019 is the directory 019's copy of manifest.schema.json, the bundle 5 that 016
// moves to 6, is frozen under.
const contract019 = "019-following-removed"

// compileFrozenSchema is feature's copy of the contract name, frozen under
// testdata/contracts/<feature>/. It is read alone: the manifest refers to no other schema.
func compileFrozenSchema(t *testing.T, feature, name string) *jsonschema.Schema {
	t.Helper()
	path := filepath.Join("testdata", "contracts", feature, name)
	f, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = f.Close() }()
	doc, err := jsonschema.UnmarshalJSON(f)
	if err != nil {
		t.Fatalf("parsing %s: %v", path, err)
	}
	c := jsonschema.NewCompiler()
	if err := c.AddResource(path, doc); err != nil {
		t.Fatal(err)
	}
	s, err := c.Compile(path)
	if err != nil {
		t.Fatalf("compiling %s (a consumer could not load this schema): %v", path, err)
	}
	return s
}

// asBundle5 is a probe-less manifest as bundle 5 wrote it: bundle_version "5", and neither
// the probes list nor fidelity.synthesized, the two keys bundle 6 adds (016, formats.md),
// each always written and empty when the CTM declares no probe. A manifest of 5 is returned
// as it is.
func asBundle5(t *testing.T, manifest []byte) []byte {
	t.Helper()
	var m map[string]any
	if err := json.Unmarshal(manifest, &m); err != nil {
		t.Fatal(err)
	}
	m["bundle_version"] = "5"
	delete(m, "probes")
	if fidelity, ok := m["fidelity"].(map[string]any); ok {
		delete(fidelity, "synthesized")
	}
	b, err := json.Marshal(m)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

// 019's copy of the manifest contract, bundle 5, loads and accepts every probe-less manifest
// the compiler writes, as bundle 5 wrote it (asBundle5): a probe-less compile is bundle 5's
// in everything but its version and the two lists 6 adds.
func TestManifest5FrozenCopy(t *testing.T) {
	schema := compileFrozenSchema(t, contract019, "manifest.schema.json")
	root := filepath.Join("..", "..", "testdata", "ctm")
	entries, err := os.ReadDir(root)
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range entries {
		if e.IsDir() || filepath.Ext(e.Name()) != ".json" {
			continue
		}
		t.Run(e.Name(), func(t *testing.T) {
			files := compileLossyFixture(t, "testdata/ctm/"+e.Name())
			mustValidate(t, schema, asBundle5(t, files[ManifestFile]), "manifest from "+e.Name()+" as bundle 5")
		})
	}
}

// asAny round-trips through JSON so the validator sees the same document a consumer
// reading the file would.
func asAny(t *testing.T, b []byte) any {
	t.Helper()
	v, err := jsonschema.UnmarshalJSON(bytes.NewReader(b))
	if err != nil {
		t.Fatalf("re-reading emitted JSON: %v", err)
	}
	return v
}

func mustValidate(t *testing.T, s *jsonschema.Schema, doc []byte, label string) {
	t.Helper()
	if err := s.Validate(asAny(t, doc)); err != nil {
		t.Errorf("%s does not satisfy its contract:\n%v", label, err)
	}
}

// Every schema must load. This is the check that would have caught the broken $ref.
func TestContractsCompile(t *testing.T) {
	for _, name := range []string{"ctm.schema.json", "manifest.schema.json", "findings.schema.json"} {
		t.Run(name, func(t *testing.T) { compileSchema(t, name) })
	}
}

// Every fixture that compiles must produce a manifest a consumer can read, not just
// the reference one: the interesting manifests are the ones with omissions in them.
// The registry carries the design-case package beside the embedded ones, which changes
// nothing for a fixture of embedded platforms alone.
func TestEmittedManifestSatisfiesContract(t *testing.T) {
	schema := compileSchema(t, "manifest.schema.json")
	root := filepath.Join("..", "..", "testdata", "ctm")
	entries, err := os.ReadDir(root)
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range entries {
		if e.IsDir() || filepath.Ext(e.Name()) != ".json" {
			continue
		}
		t.Run(e.Name(), func(t *testing.T) {
			files := compileLossyFixture(t, "testdata/ctm/"+e.Name())
			mustValidate(t, schema, files[ManifestFile], "manifest from "+e.Name())
		})
	}
}

// The committed golden manifest is what a reader inspects when learning the format.
func TestGoldenManifestSatisfiesContract(t *testing.T) {
	schema := compileSchema(t, "manifest.schema.json")
	b, err := os.ReadFile(filepath.Join("..", "..", "testdata", "golden", "three-node", ManifestFile))
	if err != nil {
		t.Fatal(err)
	}
	mustValidate(t, schema, b, "golden manifest")
}

// The lossy golden is the manifest a reader learns M6's two fields from.
func TestLossyGoldenManifestSatisfiesContract(t *testing.T) {
	schema := compileSchema(t, "manifest.schema.json")
	b, err := os.ReadFile(filepath.Join("..", "..", "testdata", "golden", "lossy", ManifestFile))
	if err != nil {
		t.Fatal(err)
	}
	mustValidate(t, schema, b, "lossy golden manifest")
}

// A bundle with nothing lossy in it carries both fields all the same, now that bundle
// "3" has made them unconditional (D-025). M6 emitted them only with content, so
// that such a bundle stayed byte-identical to M5's, and no golden moved and no twin then
// following its branch was rebuilt for the upgrade (following left the core at 019); that exception was written to expire with the next bundle_version
// bump, and this is it. The schema now requires both, so an absence is refused rather
// than read as "none". two-mgmt.json is the fixture with nothing lossy and a row with no
// port, its second management port, since every interface of a CTM "2" is a port and the
// three-node fixture's every row has one. Bundle "5"'s fidelity.read is required alike.
func TestNothingLossyStillCarriesBothFields(t *testing.T) {
	schema := compileSchema(t, "manifest.schema.json")
	files := compileFixture(t, "testdata/ctm/two-mgmt.json")
	manifest := files[ManifestFile]
	for _, field := range []string{`"lossy": []`, `"node_name": null`} {
		if !bytes.Contains(manifest, []byte(field)) {
			t.Errorf("the two-mgmt manifest does not carry %s:\n%s", field, manifest)
		}
	}
	mustValidate(t, schema, manifest, "two-mgmt manifest with an empty lossy record")

	for _, field := range []string{"lossy", "read"} {
		start := bytes.Index(manifest, []byte(`    "`+field+`": [`))
		if start < 0 {
			t.Fatalf("could not find fidelity.%s in the manifest; the test needs updating", field)
		}
		without := removeMember(manifest, start)
		if err := schema.Validate(asAny(t, without)); err == nil {
			t.Errorf("a manifest without fidelity.%s satisfied manifest.schema.json; the contract requires it", field)
		}
	}
}

// removeMember drops the object member starting at start, a key at the manifest's
// fidelity depth, with the comma that separates it from its neighbour.
func removeMember(doc []byte, start int) []byte {
	depth, end := 0, start
	for i := bytes.IndexByte(doc[start:], '[') + start; i < len(doc); i++ {
		switch doc[i] {
		case '[', '{':
			depth++
		case ']', '}':
			depth--
		}
		if depth == 0 {
			end = i + 1
			break
		}
	}
	out := append([]byte{}, doc[:start]...)
	rest := doc[end:]
	if bytes.HasPrefix(rest, []byte(",\n")) {
		rest = rest[2:]
	} else {
		// The last member: drop the comma before it instead.
		out = bytes.TrimRight(out, " \n")
		out = bytes.TrimSuffix(out, []byte(","))
		out = append(out, '\n')
		rest = bytes.TrimLeft(rest, "\n")
	}
	return append(out, rest...)
}

// `basis` is `const: "asserted"` in the schema, so a manifest that does not say
// fidelity is asserted fails its own contract rather than merely disappointing a
// reader (Constitution X; D-022). Asserted here by removing it, so the test fails if
// the schema ever stops requiring it.
func TestManifestWithoutFidelityBasisIsInvalid(t *testing.T) {
	schema := compileSchema(t, "manifest.schema.json")
	files := compileFixture(t, "testdata/ctm/three-node.json")
	stripped := bytes.Replace(files[ManifestFile], []byte("    \"basis\": \"asserted\",\n"), nil, 1)
	if bytes.Equal(stripped, files[ManifestFile]) {
		t.Fatal("could not remove fidelity.basis from the manifest; the test needs updating")
	}
	if err := schema.Validate(asAny(t, stripped)); err == nil {
		t.Error("a manifest with no fidelity.basis satisfied manifest.schema.json; " +
			"the contract no longer requires the bundle to say fidelity is asserted")
	}
}
