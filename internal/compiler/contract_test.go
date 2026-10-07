package compiler

import (
	"bytes"
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
	// findings.schema.json refers to show.schema.json (M4), waypoints.schema.json (M10),
	// step.schema.json (M11) and verify.schema.json (M12) by their published $ids, which no
	// consumer resolves over the network; each is supplied from the same directory, as
	// internal/findings supplies them.
	for _, ref := range []string{"show.schema.json", "waypoints.schema.json", "step.schema.json", "verify.schema.json"} {
		rf, err := os.Open(filepath.Join(contractsDir(), ref))
		if err != nil {
			t.Fatalf("opening %s: %v", ref, err)
		}
		refDoc, err := jsonschema.UnmarshalJSON(rf)
		_ = rf.Close()
		if err != nil {
			t.Fatalf("parsing %s: %v", ref, err)
		}
		if err := c.AddResource("https://fylgja.dev/schemas/"+ref, refDoc); err != nil {
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
// that such a bundle stayed byte-identical to M5's and no golden or following twin moved
// for the upgrade; that exception was written to expire with the next bundle_version
// bump, and this is it. The schema now requires both, so an absence is refused rather
// than read as "none".
func TestNothingLossyStillCarriesBothFields(t *testing.T) {
	schema := compileSchema(t, "manifest.schema.json")
	files := compileFixture(t, "testdata/ctm/three-node.json")
	manifest := files[ManifestFile]
	for _, field := range []string{`"lossy": []`, `"node_name": null`} {
		if !bytes.Contains(manifest, []byte(field)) {
			t.Errorf("the three-node manifest does not carry %s:\n%s", field, manifest)
		}
	}
	mustValidate(t, schema, manifest, "three-node manifest with an empty lossy record")

	without := bytes.Replace(manifest, []byte(`    "omitted": [],
    "lossy": []
  }`), []byte(`    "omitted": []
  }`), 1)
	if bytes.Equal(without, manifest) {
		t.Fatal("could not remove fidelity.lossy from the manifest; the test needs updating")
	}
	if err := schema.Validate(asAny(t, without)); err == nil {
		t.Error("a manifest without fidelity.lossy satisfied manifest.schema.json; the contract requires it from bundle 3")
	}
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
