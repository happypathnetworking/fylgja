package stage

import (
	"path/filepath"
	"reflect"
	"sort"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/snapshot"
)

// repoPath is a path under the module root.
func repoPath(elem ...string) string {
	return filepath.Join(append([]string{"..", ".."}, elem...)...)
}

// A wrapped fixture compiles to its golden byte for byte, and to the bundle its bare CTM
// compiles to: wrapping a CTM moves no golden (FR-021, SC-003; R-15). The ids are
// internal/compiler's goldens'. The lossy fixture compiles through the design-case
// package beside the shipped ones, as its golden does (`--psp-dir testdata/psp/lossy`):
// the shipped packages alone have none for its chassis platform.
func TestWrappedFixturesCompileToTheGoldens(t *testing.T) {
	shipped, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	lossy, err := psp.Load(repoPath("testdata", "psp", "lossy"))
	if err != nil {
		t.Fatal(err)
	}
	for _, c := range []struct {
		name, id string
		reg      *psp.Registry
	}{
		{"three-node", "1b352957aa74ff6e6f944a1b5ccb3b678248c895601f7a3aa66a4f9166d3909a", shipped},
		{"lossy", "10099944520a548145d2d8dc45eb9a2ddec950a0ec2c9be48c572bb66fc48c31", lossy},
		{"mixed", "7b994ecf500d86431f82ca5c08eee4e32ac77b1b6625d1c7ad3f582edb8c81b9", shipped},
	} {
		t.Run(c.name, func(t *testing.T) {
			s, err := snapshot.Load(repoPath("testdata", "snapshot", c.name+".json"))
			if err != nil {
				t.Fatal(err)
			}
			files, id, list := Compile(s.CTM, nil, c.reg, nil)
			if list.Rejected() {
				t.Fatalf("the wrapped %s was rejected: %v", c.name, list)
			}
			if id != c.id {
				t.Errorf("the wrapped %s compiles to bundle %s, want %s", c.name, id, c.id)
			}

			golden, err := bundle.LoadFiles(repoPath("testdata", "golden", c.name))
			if err != nil {
				t.Fatal(err)
			}
			for _, name := range union(files, golden) {
				got, inBundle := files[name]
				want, inGolden := golden[name]
				switch {
				case !inGolden:
					t.Errorf("%s: the bundle holds a file its golden does not", name)
				case !inBundle:
					t.Errorf("%s: the golden holds a file the bundle does not", name)
				case string(got) != string(want):
					t.Errorf("%s differs from testdata/golden/%s/%s", name, c.name, name)
				}
			}

			bare, err := ctm.Load(repoPath("testdata", "ctm", c.name+".json"))
			if err != nil {
				t.Fatal(err)
			}
			bareFiles, bareID, list := Compile(bare, nil, c.reg, nil)
			if list.Rejected() {
				t.Fatalf("the bare %s was rejected: %v", c.name, list)
			}
			if bareID != id || !reflect.DeepEqual(bareFiles, files) {
				t.Errorf("the wrapped %s compiles to bundle %s, its bare CTM to %s", c.name, id, bareID)
			}
		})
	}
}

// union is every file name in either bundle, sorted.
func union(a, b map[string][]byte) []string {
	seen := map[string]bool{}
	for name := range a {
		seen[name] = true
	}
	for name := range b {
		seen[name] = true
	}
	names := make([]string, 0, len(seen))
	for name := range seen {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}
