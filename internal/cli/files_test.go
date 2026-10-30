package cli

import (
	"bytes"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/tree"
)

// The files a command sends are read as M12 read them, each failure in M12's words.
func TestTheFilesACommandSends(t *testing.T) {
	dir := t.TempDir()
	missing := filepath.Join(dir, "absent.json")
	if _, err := readSnapshot(missing); err == nil || err.Error() != "reading snapshot: open "+missing+": no such file or directory" {
		t.Errorf("readSnapshot: %v", err)
	}
	snap := filepath.Join(dir, "snapshot.json")
	if err := os.WriteFile(snap, []byte("{}"), 0o644); err != nil {
		t.Fatal(err)
	}
	if f, err := readSnapshot(snap); err != nil || f.Path != snap || string(f.Data) != "{}" {
		t.Errorf("readSnapshot: %+v %v", f, err)
	}

	files, err := readPackages([]string{snap, snap})
	if err != nil || len(files) != 2 || files[1].Path != snap {
		t.Errorf("readPackages: %+v %v", files, err)
	}
	if _, err := readPackages([]string{snap, missing}); err == nil || err.Error() != "open "+missing+": no such file or directory" {
		t.Errorf("readPackages of a missing file: %v", err)
	}
}

// A bundle directory is read as its regular files, in path order, and written back as the
// same files; a target that is not empty is refused in M12's words.
func TestABundleReadAndWrittenIsTheSame(t *testing.T) {
	golden := filepath.Join("..", "..", "testdata", "golden", "three-node")
	files, err := readBundle(golden)
	if err != nil {
		t.Fatal(err)
	}
	for i := 1; i < len(files); i++ {
		if files[i-1].Path >= files[i].Path {
			t.Errorf("%s before %s", files[i-1].Path, files[i].Path)
		}
	}
	out := filepath.Join(t.TempDir(), "bundle")
	if err := writeBundle(files, out); err != nil {
		t.Fatal(err)
	}
	want, _ := tree.Read(golden)
	got, _ := tree.Read(out)
	if len(got) != len(want) {
		t.Fatalf("%d files written for %d read", len(got), len(want))
	}
	for name, b := range want {
		if !bytes.Equal(got[name], b) {
			t.Errorf("%s differs", name)
		}
	}
	var notEmpty *tree.ErrNotEmpty
	if err := writeBundle(files, out); !errors.As(err, &notEmpty) || err.Error() != "output directory "+out+" is not empty" {
		t.Errorf("a non-empty target: %v", err)
	}
	if _, err := readBundle(filepath.Join(t.TempDir(), "absent")); err == nil || !strings.HasPrefix(err.Error(), "reading bundle directory: ") {
		t.Errorf("a missing directory: %v", err)
	}
}
