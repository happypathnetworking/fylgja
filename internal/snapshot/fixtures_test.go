package snapshot

import (
	"bytes"
	"flag"
	"os"
	"path/filepath"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/probe"
)

var update = flag.Bool("update", false, "rewrite the wrapped fixtures under testdata/snapshot")

// The wrapped fixtures and their ids: research §1.3's candidates, which the shipped code
// confirmed (T012). An id moves only with its CTM fixture or with the hashed bytes'
// encoding, and the encoding moving moves every stored snapshot's id, so a moved id is
// reviewed by hand, as a golden's bundle id is.
var wrappedFixtures = []struct{ name, id string }{
	{"three-node", "6a8a77fc65bdf47b9bb3a753d7709875671df20e32838344f29cfba46a13f6d6"},
	{"lossy", "91f06cd67de31f6c986bc47019e79870b02403a2970d50b6b4497df64c17f10c"},
	{"mixed", "37d7378a36568e870eb1eb43dbcd580207fb5cae847fb979b54f50eef8800ebf"},
}

// wrappedPath is a wrapped fixture under the module root's testdata/snapshot/.
func wrappedPath(name string) string {
	return filepath.Join("..", "..", "testdata", "snapshot", name+".json")
}

// testdata/snapshot/ holds the three fixture CTMs wrapped, or is rewritten under -update
// (R-15; FR-021). Each file is a fresh take of its testdata/ctm/ file, byte for byte, as
// 018 wrote it, a 1: the files stay 1 until the fixtures follow the seed's probe-ready
// ports, which moves two of the ids anyway, and a 1 reads as a 2 with no probes and the
// same id (R-05). It loads strictly; its inner CTM is that file as ctm.Marshal writes it;
// and its snapshot_id is its body's hash. internal/stage compiles each to its golden.
func TestWrappedFixtures(t *testing.T) {
	for _, f := range wrappedFixtures {
		t.Run(f.name, func(t *testing.T) {
			stored, err := Marshal(Take(fixture(t, f.name), nil))
			if err != nil {
				t.Fatal(err)
			}
			want := asVersion1(t, stored)
			path := wrappedPath(f.name)

			if *update {
				if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
					t.Fatal(err)
				}
				if err := os.WriteFile(path, want, 0o644); err != nil {
					t.Fatal(err)
				}
				t.Logf("%s rewritten", path)
				return
			}

			got, err := os.ReadFile(path)
			if err != nil {
				t.Fatalf("reading %s: %v (run: go test ./internal/snapshot -run TestWrappedFixtures -update)", path, err)
			}
			if !bytes.Equal(got, want) {
				t.Errorf("%s is not a fresh take of testdata/ctm/%s.json (run with -update and review the diff)", path, f.name)
			}

			s, err := Load(path)
			if err != nil {
				t.Fatalf("loading %s: %v", path, err)
			}
			inner, err := ctm.Marshal(s.CTM)
			if err != nil {
				t.Fatal(err)
			}
			bare, err := ctm.Marshal(fixture(t, f.name))
			if err != nil {
				t.Fatal(err)
			}
			if !bytes.Equal(inner, bare) {
				t.Errorf("%s's ctm is not testdata/ctm/%s.json as ctm.Marshal writes it", path, f.name)
			}

			id, err := ID(s)
			if err != nil {
				t.Fatal(err)
			}
			if s.ID != id {
				t.Errorf("%s declares snapshot_id %s, but its body hashes to %s", path, s.ID, id)
			}
			if s.ID != f.id {
				t.Errorf("%s's snapshot_id is %s, want %s", path, s.ID, f.id)
			}
			t.Logf("%s: %s", f.name, s.ID)
		})
	}
}

// The probed wrapped fixture and its id: the fourth golden's input (T016). It is
// testdata/ctm/three-node.json with two probe-ready ports on each device, wrapped as a 2
// with testdata/probes/n1-loop.json's probe. The ports are written here by hand until the
// fixture's seed writes them and testdata/ctm/three-node.json follows it (T035).
const probedFixtureID = "907970d9a03c30caa303837f4c9e2ba021de4196f9f5f29253e367f63e90ae7d"

// probePorts are the two probe-ready ports the fixture's seed will give each device
// (research R-19).
var probePorts = []string{"ethernet-1/10", "ethernet-1/11"}

// probedFixture is testdata/ctm/three-node.json with probePorts on each device, uncabled,
// each with its device's ethernet-1/1's role and status, normalised.
func probedFixture(t *testing.T) *ctm.CTM {
	t.Helper()
	c := fixture(t, "three-node")
	for i := range c.Devices {
		d := &c.Devices[i]
		first := d.Interface("ethernet-1/1")
		if first == nil {
			t.Fatalf("three-node's %s has no ethernet-1/1 to copy", d.Name)
		}
		mgmtOnly, enabled := first.MgmtOnly, first.IsEnabled()
		for _, name := range probePorts {
			d.Interfaces = append(d.Interfaces, ctm.Interface{Name: name, MgmtOnly: mgmtOnly, Enabled: &enabled})
		}
	}
	ctm.Normalize(c)
	return c
}

// testdata/snapshot/three-node-probed.json is a fresh take of probedFixture with
// n1-loop's probe, byte for byte, a 2, or is rewritten under -update. It loads strictly
// and satisfies contracts/snapshot.schema.json; its probe is the file's, and its
// snapshot_id is its body's hash.
func TestProbedFixture(t *testing.T) {
	path := filepath.Join("..", "..", "testdata", "probes", "n1-loop.json")
	b, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	decl, list := probe.Parse(b, path)
	if list.Rejected() {
		t.Fatalf("%s: %v", path, list)
	}
	want, err := Marshal(Take(probedFixture(t), decl.Probes))
	if err != nil {
		t.Fatal(err)
	}
	wrapped := wrappedPath("three-node-probed")

	if *update {
		if err := os.WriteFile(wrapped, want, 0o644); err != nil {
			t.Fatal(err)
		}
		t.Logf("%s rewritten", wrapped)
		return
	}

	got, err := os.ReadFile(wrapped)
	if err != nil {
		t.Fatalf("reading %s: %v (run: go test ./internal/snapshot -run TestProbedFixture -update)", wrapped, err)
	}
	if !bytes.Equal(got, want) {
		t.Errorf("%s is not a fresh take of three-node with the probe-ready ports and n1-loop (run with -update and review the diff)", wrapped)
	}
	if err := validate(t, snapshotSchema(t), got); err != nil {
		t.Errorf("%s does not satisfy contracts/snapshot.schema.json:\n%v", wrapped, err)
	}

	s, err := Load(wrapped)
	if err != nil {
		t.Fatalf("loading %s: %v", wrapped, err)
	}
	if s.Version != Version || len(s.Probes) != 1 || s.Probes[0] != decl.Probes[0] {
		t.Errorf("%s is version %s with probes %+v, want a %s with n1-loop alone", wrapped, s.Version, s.Probes, Version)
	}
	id, err := ID(s)
	if err != nil {
		t.Fatal(err)
	}
	if s.ID != id {
		t.Errorf("%s declares snapshot_id %s, but its body hashes to %s", wrapped, s.ID, id)
	}
	if s.ID != probedFixtureID {
		t.Errorf("%s's snapshot_id is %s, want %s", wrapped, s.ID, probedFixtureID)
	}
	t.Logf("three-node-probed: %s", s.ID)
}
