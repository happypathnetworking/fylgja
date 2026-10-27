package snapshot

import (
	"bytes"
	"flag"
	"os"
	"path/filepath"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/ctm"
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
// (R-15; FR-021). Each file is a fresh take of its testdata/ctm/ file, byte for byte; it
// loads strictly; its inner CTM is that file as ctm.Marshal writes it; and its snapshot_id
// is its body's hash. internal/stage compiles each to its golden.
func TestWrappedFixtures(t *testing.T) {
	for _, f := range wrappedFixtures {
		t.Run(f.name, func(t *testing.T) {
			want, err := Marshal(Take(fixture(t, f.name)))
			if err != nil {
				t.Fatal(err)
			}
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
