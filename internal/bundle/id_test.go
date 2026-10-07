package bundle

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

func TestIDIsLowercaseHex(t *testing.T) {
	id := ID(sample())
	if len(id) != 64 {
		t.Errorf("id is %d characters, want 64: %q", len(id), id)
	}
	if strings.ToLower(id) != id {
		t.Errorf("id is not lowercase: %q", id)
	}
	if !IsID(id) {
		t.Errorf("IsID rejects an id this package produced: %q", id)
	}
	for _, bad := range []string{"", "abc", strings.Repeat("A", 64), strings.Repeat("g", 64), strings.Repeat("a", 63)} {
		if IsID(bad) {
			t.Errorf("IsID accepted %q", bad)
		}
	}
}

// The two implementations exist for different callers — the compiler's bytes, and a
// directory M2 did not compile — so the only thing keeping the second honest is that
// it agrees with the first.
func TestBundleIDMatchesDirectory(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "out")
	files := sample()
	if err := Write(files, dir); err != nil {
		t.Fatal(err)
	}
	fromDir, err := IDOfDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	if got := ID(files); got != fromDir {
		t.Errorf("ID(files) = %s, IDOfDir(dir) = %s", got, fromDir)
	}
}

// Paths are part of the id: a bundle with the same bytes under a different name is a
// different bundle, because it deploys differently.
func TestRenamingAFileChangesTheID(t *testing.T) {
	before := sample()
	after := sample()
	after["configs/n2.cli"] = after["configs/n1.cli"]
	delete(after, "configs/n1.cli")
	if ID(before) == ID(after) {
		t.Error("renaming a file did not change the bundle id")
	}
}

func TestChangingAByteChangesTheID(t *testing.T) {
	before := sample()
	after := sample()
	after["manifest.json"] = []byte("{ }\n")
	if ID(before) == ID(after) {
		t.Error("changing a file's bytes did not change the bundle id")
	}
}

// The id would change itself if it were stored, so it never is.
func TestIDIsNotStoredInTheBundle(t *testing.T) {
	files := sample()
	id := ID(files)
	for name, content := range files {
		if strings.Contains(string(content), id) {
			t.Errorf("%s carries the bundle id", name)
		}
	}
}

// Modes and mtimes are excluded on purpose: an id that changed when a bundle was
// copied would be useless to M2, which stages a bundle before deploying it.
func TestIDIgnoresModeAndMtime(t *testing.T) {
	root := t.TempDir()
	a := filepath.Join(root, "a")
	b := filepath.Join(root, "b")
	if err := Write(sample(), a); err != nil {
		t.Fatal(err)
	}
	if err := Write(sample(), b); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(filepath.Join(b, "manifest.json"), 0o600); err != nil {
		t.Fatal(err)
	}
	idA, err := IDOfDir(a)
	if err != nil {
		t.Fatal(err)
	}
	idB, err := IDOfDir(b)
	if err != nil {
		t.Fatal(err)
	}
	if idA != idB {
		t.Errorf("a mode change altered the bundle id: %s vs %s", idA, idB)
	}
}

// The reason for choosing the sha256sum listing format was that a reviewer can
// recompute the id without Fylgja. If that ever stops being true, the
// id has quietly become a claim instead of a check — so the shell recipe is the test.
func TestIDMatchesTheShellRecipe(t *testing.T) {
	if _, err := exec.LookPath("sha256sum"); err != nil {
		t.Skip("sha256sum not available")
	}
	dir := filepath.Join(t.TempDir(), "out")
	files := sample()
	if err := Write(files, dir); err != nil {
		t.Fatal(err)
	}
	const recipe = `find . -type f | sed 's|^\./||' | LC_ALL=C sort | xargs sha256sum | sha256sum | cut -d' ' -f1`
	cmd := exec.Command("sh", "-c", recipe)
	cmd.Dir = dir
	out, err := cmd.Output()
	if err != nil {
		t.Fatalf("running the quickstart recipe: %v", err)
	}
	want := strings.TrimSpace(string(out))
	if got := ID(files); got != want {
		t.Errorf("ID(files) = %s, the shell recipe gives %s", got, want)
	}
}

// Every fixture that compiles, not just a hand-made map: the two implementations have
// to agree on real bundles, including the ones with a configs/ subdirectory and the
// ones where something was omitted. The design-case package is loaded beside
// the embedded ones, as `--psp-dir testdata/psp/lossy` gives it, for the lossy fixture
// (M6); a fixture of embedded platforms alone compiles through it unchanged.
func TestIDMatchesDirectoryForEveryFixture(t *testing.T) {
	reg, err := psp.Load(filepath.Join("..", "..", "testdata", "psp", "lossy"))
	if err != nil {
		t.Fatal(err)
	}
	root := filepath.Join("..", "..", "testdata", "ctm")
	entries, err := os.ReadDir(root)
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".json") {
			continue
		}
		t.Run(e.Name(), func(t *testing.T) {
			c, err := ctm.Load(filepath.Join(root, e.Name()))
			if err != nil {
				t.Fatal(err)
			}
			files, list := compiler.Compile(c, reg)
			if list.Rejected() {
				t.Fatalf("%s was rejected: %v", e.Name(), list)
			}
			dir := filepath.Join(t.TempDir(), "out")
			if err := Write(files, dir); err != nil {
				t.Fatal(err)
			}
			fromDir, err := IDOfDir(dir)
			if err != nil {
				t.Fatal(err)
			}
			id := ID(files)
			if id != fromDir {
				t.Errorf("ID(files) = %s, IDOfDir(dir) = %s", id, fromDir)
			}
			if !IsID(id) {
				t.Errorf("id is not 64 lowercase hex: %q", id)
			}
			for name, content := range files {
				if strings.Contains(string(content), id) {
					t.Errorf("%s carries the bundle id", name)
				}
			}
		})
	}
}
