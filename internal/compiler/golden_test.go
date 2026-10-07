package compiler

import (
	"bytes"
	"encoding/json"
	"flag"
	"os"
	"path/filepath"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

var update = flag.Bool("update", false, "rewrite golden files")

func loadFixture(t *testing.T, path string) *ctm.CTM {
	t.Helper()
	c, err := ctm.Load(filepath.Join("..", "..", path))
	if err != nil {
		t.Fatal(err)
	}
	return c
}

// The goldens' bundle ids. The three-node one is M5's and must never move: a platform
// that names its ports as production gains nothing from the profile.
// The lossy one is the design case's, baselined once and reviewed. The mixed
// one is M7's two shipped platforms in one bundle, baselined once likewise.
// A bundle format moves all three, once and reviewed: M7's "3", and M12's "4", which
// wrote enabled on every mapping row.
const (
	goldenThreeNodeID = "23f86a2678a49a324a04ae458703be8252e2e30d6712d6b6094ce1ccd5c2988e"
	goldenLossyID     = "5773b6bba1107076b2cde8283f92494d42b3eab89c5f297ea25f81134fd529f7"
	goldenMixedID     = "391bcb96c39e7e878fa6ba78ac869742b04f517fa914e2fce51c3ea4944dd3cb"
)

// compileFixture compiles a fixture and fails on any rejection: the fixtures under
// testdata/ctm/ are the ones that are supposed to build. The registry is the embedded
// packages alone, as `twin compile` without --psp-dir has it.
func compileFixture(t *testing.T, path string) map[string][]byte {
	t.Helper()
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	return compileFixtureWith(t, path, reg)
}

// compileLossyFixture compiles a fixture with the design-case package beside the
// embedded ones, as `--psp-dir testdata/psp/lossy` gives them. An override directory
// adds packages without replacing the embedded ones it does not name, so an SR Linux
// fixture compiles through this registry to the bytes it compiles to without it.
func compileLossyFixture(t *testing.T, path string) map[string][]byte {
	t.Helper()
	return compileFixtureWith(t, path, lossyRegistry(t))
}

func lossyRegistry(t *testing.T) *psp.Registry {
	t.Helper()
	reg, err := psp.Load(filepath.Join("..", "..", "testdata", "psp", "lossy"))
	if err != nil {
		t.Fatal(err)
	}
	return reg
}

func compileFixtureWith(t *testing.T, path string, reg *psp.Registry) map[string][]byte {
	t.Helper()
	files, list := Compile(loadFixture(t, path), reg)
	if list.Rejected() {
		t.Fatalf("%s was rejected by the compiler: %v", path, list)
	}
	return files
}

func TestGoldenThreeNode(t *testing.T) {
	files := compileFixture(t, "testdata/ctm/three-node.json")
	if !checkGolden(t, "three-node", files) {
		return
	}
	if id := bundle.ID(files); id != goldenThreeNodeID {
		t.Errorf("bundle_id = %s, want %s: the three-node golden never moves", id, goldenThreeNodeID)
	}
	checkInvariants(t, "testdata/ctm/three-node.json", files)

	// The lab name is fixed and the topology declares no management network of its
	// own: both are requirements, not accidents.
	t.Run("topology", func(t *testing.T) {
		topo := string(files[TopologyFile])
		if !bytes.Contains([]byte(topo), []byte("\nname: "+LabName+"\n")) {
			t.Errorf("topology does not name the lab %q:\n%s", LabName, topo)
		}
		if bytes.Contains([]byte(topo), []byte("mgmt:")) {
			t.Errorf("topology declares a management network; containerlab's default is the contract:\n%s", topo)
		}
	})
}

// TestGoldenLossy is the design case: two platforms, one naming its
// ports as a modular chassis does through a lossy profile, one SR Linux, in one bundle.
// lossy_test.go asserts what it holds by name; this holds its bytes.
func TestGoldenLossy(t *testing.T) {
	files := compileLossyFixture(t, "testdata/ctm/lossy.json")
	if !checkGolden(t, "lossy", files) {
		return
	}
	if id := bundle.ID(files); id != goldenLossyID {
		t.Errorf("bundle_id = %s, want %s", id, goldenLossyID)
	}
	checkInvariants(t, "testdata/ctm/lossy.json", files)
}

// checkGolden compares a compile with testdata/golden/<name>/, file by file and in both
// directions, or rewrites the golden under -update and reports false. A golden is
// rewritten only to be reviewed by hand: the three-node golden never is.
func checkGolden(t *testing.T, name string, files map[string][]byte) bool {
	t.Helper()
	dir := filepath.Join("..", "..", "testdata", "golden", name)

	if *update {
		if err := os.RemoveAll(dir); err != nil {
			t.Fatal(err)
		}
		for name, content := range files {
			p := filepath.Join(dir, filepath.FromSlash(name))
			if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(p, content, 0o644); err != nil {
				t.Fatal(err)
			}
		}
		t.Log("golden files rewritten")
		return false
	}

	for name, got := range files {
		want, err := os.ReadFile(filepath.Join(dir, filepath.FromSlash(name)))
		if err != nil {
			t.Fatalf("reading golden %s: %v (run: go test ./internal/compiler -update)", name, err)
		}
		if !bytes.Equal(got, want) {
			t.Errorf("%s differs from golden:\n--- got\n%s\n--- want\n%s", name, got, want)
		}
	}

	// A golden that gained a file, or lost one, is as much a change as a byte that
	// moved — and comparing only the files the compiler produced would not notice.
	var onDisk []string
	err := filepath.WalkDir(dir, func(p string, d os.DirEntry, err error) error {
		if err != nil || d.IsDir() {
			return err
		}
		rel, err := filepath.Rel(dir, p)
		if err != nil {
			return err
		}
		onDisk = append(onDisk, filepath.ToSlash(rel))
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	for _, name := range onDisk {
		if _, ok := files[name]; !ok {
			t.Errorf("golden holds %s, which the compiler no longer emits", name)
		}
	}
	return true
}

// checkInvariants holds a compile to what must be true whatever its golden contains: a
// golden file that regenerates alongside a bug hides the bug.
func checkInvariants(t *testing.T, fixture string, files map[string][]byte) {
	t.Helper()
	t.Run("invariants", func(t *testing.T) {
		c := loadFixture(t, fixture)
		var m Manifest
		if err := json.Unmarshal(files[ManifestFile], &m); err != nil {
			t.Fatal(err)
		}

		// Every interface in intent appears exactly once in the mapping table.
		seen := map[string]int{}
		rows := map[string]MappingRow{}
		for _, r := range m.Mapping {
			seen[r.Device+":"+r.Interface]++
			rows[r.Device+":"+r.Interface] = r
		}
		total := 0
		for _, d := range c.Devices {
			for _, in := range d.Interfaces {
				total++
				key := d.Name + ":" + in.Name
				if seen[key] != 1 {
					t.Errorf("interface %s appears %d times in the mapping table, want 1", key, seen[key])
				}
				// From bundle "4" every row says what intent says of the interface's
				// admin state, written whether true or false.
				if r, ok := rows[key]; ok && (r.Enabled == nil || *r.Enabled != in.IsEnabled()) {
					t.Errorf("row %s carries enabled %v; intent says %t", key, r.Enabled, in.IsEnabled())
				}
			}
		}
		if len(m.Mapping) != total {
			t.Errorf("mapping has %d rows for %d interfaces in intent", len(m.Mapping), total)
		}

		// Nothing is dropped without being recorded.
		omitted := map[string]bool{}
		for _, o := range m.Omissions {
			omitted[o.Object] = true
		}
		for _, r := range m.Mapping {
			if r.Disposition == DispOmitted && !omitted[r.Device+":"+r.Interface] {
				t.Errorf("interface %s:%s is omitted with no entry in omissions[]", r.Device, r.Interface)
			}
			if r.Disposition == DispOmitted && r.Port != nil {
				t.Errorf("interface %s:%s is omitted but carries a port", r.Device, r.Interface)
			}
			if r.Disposition != DispOmitted && r.Disposition != DispConfiguredNotCabled && r.Port == nil {
				t.Errorf("interface %s:%s is %s with no port", r.Device, r.Interface, r.Disposition)
			}
		}

		// Every intended link between mappable physical ports is cabled.
		if len(m.Links) != len(c.Links) {
			t.Errorf("cabled %d links, intent has %d", len(m.Links), len(c.Links))
		}

		// The fidelity manifest always states how production forwards, and always
		// says the answer is asserted rather than measured (Constitution X).
		if m.Fidelity.Basis != FidelityAsserted {
			t.Errorf("fidelity basis = %q, want %q", m.Fidelity.Basis, FidelityAsserted)
		}
		// One entry per support package in the bundle, never a single claim over
		// nodes of two platforms (bundle "3"; D-025).
		if len(m.Fidelity.ProductionForwarding) == 0 {
			t.Error("fidelity manifest does not state production forwarding")
		}
		for id, f := range m.Fidelity.ProductionForwarding {
			if f != psp.ForwardingHardware && f != psp.ForwardingSoftware {
				t.Errorf("production_forwarding[%s] = %q, want hardware or software", id, f)
			}
		}
		if len(m.Fidelity.Approximations) == 0 {
			t.Error("fidelity manifest lists no approximations")
		}

		// The provenance block is the intent's address and nothing else: no build
		// stamp, no source, and above all no observed_at (D-023).
		if m.Provenance.Branch != c.Envelope.Branch || m.Provenance.At != c.Envelope.At ||
			m.Provenance.SchemaHash != c.Envelope.SchemaHash ||
			m.Provenance.ContractVersion != c.Envelope.ContractVersion {
			t.Errorf("provenance %+v does not match the CTM envelope %+v", m.Provenance, c.Envelope)
		}

		// From bundle "3" a node name is written on every row with a port — equal to
		// the production name where the platform keeps it — and is null on every row
		// without one (D-025; M6's conditional shape expired with the bump).
		for _, r := range m.Mapping {
			switch {
			case r.Port != nil && r.NodeName == nil:
				t.Errorf("row %s:%s has port %q and no node_name", r.Device, r.Interface, *r.Port)
			case r.Port == nil && r.NodeName != nil:
				t.Errorf("row %s:%s has no port and node_name %q", r.Device, r.Interface, *r.NodeName)
			}
		}
	})
}

// Whatever the manifest says, the bundle must not carry a build or a read identity —
// anywhere, in any file. `fylgja_version` would make every release a
// different bundle; `observed_at` would make every read one (D-023).
func TestBundleCarriesNoBuildOrReadIdentity(t *testing.T) {
	files := compileFixture(t, "testdata/ctm/three-node.json")
	for name, content := range files {
		for _, banned := range []string{"fylgja_version", "observed_at"} {
			if bytes.Contains(content, []byte(banned)) {
				t.Errorf("%s contains %q:\n%s", name, banned, content)
			}
		}
	}

	// `source` is checked in the provenance block rather than across the file:
	// nodes[].psp.source still records whether a support package was the shipped one,
	// and that is a different question from where a CTM file came from.
	var m struct {
		Provenance map[string]any `json:"provenance"`
	}
	if err := json.Unmarshal(files[ManifestFile], &m); err != nil {
		t.Fatal(err)
	}
	for _, key := range []string{"source", "observed_at", "schema_version"} {
		if _, ok := m.Provenance[key]; ok {
			t.Errorf("provenance block still carries %q: %v", key, m.Provenance)
		}
	}
	for _, key := range []string{"branch", "at", "schema_hash", "contract_version"} {
		if _, ok := m.Provenance[key]; !ok {
			t.Errorf("provenance block is missing %q: %v", key, m.Provenance)
		}
	}
}
