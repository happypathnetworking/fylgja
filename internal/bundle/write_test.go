package bundle

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
)

func sample() map[string][]byte {
	return map[string][]byte{
		"topology.clab.yml": []byte("name: fylgja\n"),
		"manifest.json":     []byte("{}\n"),
		"configs/n1.cli":    []byte("set / system name host-name n1\n"),
	}
}

func TestWriteCreatesLayout(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "out")
	if err := Write(sample(), dir); err != nil {
		t.Fatal(err)
	}
	for name := range sample() {
		if _, err := os.Stat(filepath.Join(dir, filepath.FromSlash(name))); err != nil {
			t.Errorf("missing %s: %v", name, err)
		}
	}
}

// The bundle on disk must be exactly the map, byte for byte: it is what M2 deploys and
// what IDOfDir hashes.
func TestWriteRoundTripsBytes(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "out")
	files := sample()
	if err := Write(files, dir); err != nil {
		t.Fatal(err)
	}
	for name, want := range files {
		got, err := os.ReadFile(filepath.Join(dir, filepath.FromSlash(name)))
		if err != nil {
			t.Fatal(err)
		}
		if string(got) != string(want) {
			t.Errorf("%s: wrote %q, want %q", name, got, want)
		}
	}
}

func TestWriteAcceptsExistingEmptyDirectory(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "out")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := Write(sample(), dir); err != nil {
		t.Fatalf("an empty directory should be usable: %v", err)
	}
}

func TestWriteRefusesNonEmptyDirectory(t *testing.T) {
	dir := filepath.Join(t.TempDir(), "out")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	existing := filepath.Join(dir, "keep.txt")
	if err := os.WriteFile(existing, []byte("mine\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	err := Write(sample(), dir)
	var notEmpty *ErrNotEmpty
	if !errors.As(err, &notEmpty) {
		t.Fatalf("expected ErrNotEmpty, got %v", err)
	}
	// Refusing must not disturb what is already there.
	if _, err := os.Stat(existing); err != nil {
		t.Errorf("refusal removed an existing file: %v", err)
	}
	if entries, _ := os.ReadDir(dir); len(entries) != 1 {
		t.Errorf("refusal left %d entries, want the original 1", len(entries))
	}
}

// A failure part-way through must leave no partial bundle. Staging inside an
// unwritable parent fails after the bundle is otherwise ready to move.
func TestWriteLeavesNothingOnFailure(t *testing.T) {
	root := t.TempDir()
	parent := filepath.Join(root, "locked")
	if err := os.MkdirAll(parent, 0o500); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chmod(parent, 0o755) })

	dir := filepath.Join(parent, "out")
	if err := Write(sample(), dir); err == nil {
		t.Fatal("expected a failure writing into an unwritable parent")
	}
	if _, err := os.Stat(dir); !os.IsNotExist(err) {
		t.Errorf("a failed write left something at %s", dir)
	}
}

func TestWriteIsAtomicAgainstStaleStaging(t *testing.T) {
	root := t.TempDir()
	dir := filepath.Join(root, "out")
	if err := Write(sample(), dir); err != nil {
		t.Fatal(err)
	}
	// No staging directories may survive a successful write.
	entries, err := os.ReadDir(root)
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range entries {
		if e.Name() != "out" {
			t.Errorf("staging directory %s left behind", e.Name())
		}
	}
}

// The compiler builds every path in the map, so none of these can arrive today. The
// check exists because "the only caller is trusted" is how a path traversal gets in
// later, and a bundle write runs wherever the operator points --out.
func TestWriteRefusesPathsOutsideTheBundle(t *testing.T) {
	for _, name := range []string{
		"../escape.txt",
		"/absolute.txt",
		"./leading.txt",
		"configs/../../escape.txt",
		"",
	} {
		t.Run(name, func(t *testing.T) {
			root := t.TempDir()
			dir := filepath.Join(root, "out")
			if err := Write(map[string][]byte{name: []byte("x")}, dir); err == nil {
				t.Errorf("Write accepted the path %q", name)
			}
			if _, err := os.Stat(dir); !os.IsNotExist(err) {
				t.Errorf("a refused write left something at %s", dir)
			}
		})
	}
}
