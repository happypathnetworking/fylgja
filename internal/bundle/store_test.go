package bundle

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// storeFixture writes a small bundle to a fresh directory and returns it with its id.
func storeFixture(t *testing.T) (dir, id string) {
	t.Helper()
	files := map[string][]byte{
		"manifest.json":     []byte(`{"bundle_version":"1"}` + "\n"),
		"topology.clab.yml": []byte("name: fylgja\n"),
		"configs/n1.cli":    []byte("set / system name host-name n1\n"),
	}
	dir = filepath.Join(t.TempDir(), "b")
	if err := Write(files, dir); err != nil {
		t.Fatal(err)
	}
	return dir, ID(files)
}

func entries(t *testing.T, dir string) []string {
	t.Helper()
	list, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	var names []string
	for _, e := range list {
		names = append(names, e.Name())
	}
	return names
}

// Filing the same bundle twice keeps one entry and copies nothing the second time:
// the store is content-addressed, so a second copy could only be a duplicate.
func TestStoreReusesExistingEntry(t *testing.T) {
	ctx := context.Background()
	src, want := storeFixture(t)
	root := filepath.Join(t.TempDir(), "bundles")
	s := NewDirStore(root)

	id, err := s.Put(ctx, src)
	if err != nil {
		t.Fatal(err)
	}
	if id != want {
		t.Fatalf("Put = %s, want %s", id, want)
	}
	before, err := os.Stat(filepath.Join(s.Path(id), "manifest.json"))
	if err != nil {
		t.Fatal(err)
	}
	dirBefore, err := os.Stat(s.Path(id))
	if err != nil {
		t.Fatal(err)
	}

	again, err := s.Put(ctx, src)
	if err != nil || again != id {
		t.Fatalf("second Put = %s, %v; want %s", again, err, id)
	}
	after, _ := os.Stat(filepath.Join(s.Path(id), "manifest.json"))
	dirAfter, _ := os.Stat(s.Path(id))
	if !after.ModTime().Equal(before.ModTime()) || !dirAfter.ModTime().Equal(dirBefore.ModTime()) {
		t.Error("the second Put rewrote the entry; it must reuse it")
	}
	if got := entries(t, root); len(got) != 1 || got[0] != id {
		t.Errorf("store holds %v, want exactly [%s]", got, id)
	}
	// Filing from the store's own path is the same no-op.
	if again, err := s.Put(ctx, s.Path(id)); err != nil || again != id {
		t.Errorf("Put of the entry itself = %s, %v", again, err)
	}
	if has, err := s.Has(ctx, id); err != nil || !has {
		t.Errorf("Has = %v, %v; want true", has, err)
	}
}

func TestFetchVerifiesCopy(t *testing.T) {
	ctx := context.Background()
	src, _ := storeFixture(t)
	s := NewDirStore(filepath.Join(t.TempDir(), "bundles"))
	id, err := s.Put(ctx, src)
	if err != nil {
		t.Fatal(err)
	}

	dst := filepath.Join(t.TempDir(), "twin", "bundle")
	if err := s.Fetch(ctx, id, dst); err != nil {
		t.Fatal(err)
	}
	if got, err := IDOfDir(dst); err != nil || got != id {
		t.Errorf("fetched copy hashes to %s (%v), want %s", got, err, id)
	}
	if got := entries(t, filepath.Dir(dst)); len(got) != 1 {
		t.Errorf("fetch left %v beside the copy, want the copy alone", got)
	}

	if err := s.Fetch(ctx, id, dst); err == nil {
		t.Error("Fetch into a non-empty directory must refuse rather than merge")
	}
	missing := "0000000000000000000000000000000000000000000000000000000000000000"
	if err := s.Fetch(ctx, missing, filepath.Join(t.TempDir(), "x")); err == nil {
		t.Error("Fetch of an id the store does not hold must fail")
	}
}

// A store entry whose bytes no longer hash to its name is refused everywhere, naming
// the entry, so a corrupt bundle is never staged or silently re-filed (D-024).
func TestCorruptEntryRefused(t *testing.T) {
	ctx := context.Background()
	src, _ := storeFixture(t)
	s := NewDirStore(filepath.Join(t.TempDir(), "bundles"))
	id, err := s.Put(ctx, src)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(s.Path(id), "configs", "n1.cli"), []byte("tampered\n"), 0o644); err != nil {
		t.Fatal(err)
	}

	if has, err := s.Has(ctx, id); err != nil || has {
		t.Errorf("Has on a corrupt entry = %v, %v; want false, nil", has, err)
	}
	var mismatch *ErrIDMismatch
	err = s.Fetch(ctx, id, filepath.Join(t.TempDir(), "bundle"))
	if !errors.As(err, &mismatch) || mismatch.Path != s.Path(id) {
		t.Errorf("Fetch = %v; want *ErrIDMismatch naming %s", err, s.Path(id))
	}
	_, err = s.Put(ctx, src)
	if !errors.As(err, &mismatch) || mismatch.Path != s.Path(id) || mismatch.Want != id {
		t.Errorf("Put over a corrupt entry = %v; want *ErrIDMismatch naming %s", err, s.Path(id))
	}
}

func TestPutCTMOverwrites(t *testing.T) {
	ctx := context.Background()
	root := filepath.Join(t.TempDir(), "bundles")
	s := NewDirStore(root)
	id := strings.Repeat("ab", 32)
	for _, content := range []string{"first read\n", "second read\n"} {
		ctm := filepath.Join(t.TempDir(), "read.ctm.json")
		if err := os.WriteFile(ctm, []byte(content), 0o644); err != nil {
			t.Fatal(err)
		}
		if err := s.PutCTM(ctx, id, ctm); err != nil {
			t.Fatal(err)
		}
		got, err := os.ReadFile(filepath.Join(root, id+".ctm.json"))
		if err != nil || string(got) != content {
			t.Errorf("stored CTM = %q (%v), want %q", got, err, content)
		}
	}
	if got := entries(t, root); len(got) != 1 {
		t.Errorf("PutCTM left %v, want the one sidecar", got)
	}
}

// The CTM sidecar and a read's transient CTM live beside entries, never inside one, so
// neither can move an id.
func TestSidecarsDoNotAffectEntries(t *testing.T) {
	ctx := context.Background()
	src, want := storeFixture(t)
	root := filepath.Join(t.TempDir(), "bundles")
	s := NewDirStore(root)
	id, err := s.Put(ctx, src)
	if err != nil {
		t.Fatal(err)
	}
	ctm := filepath.Join(t.TempDir(), "c.json")
	if err := os.WriteFile(ctm, []byte("{}\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := s.PutCTM(ctx, id, ctm); err != nil {
		t.Fatal(err)
	}
	if err := os.MkdirAll(filepath.Join(root, ".reads"), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(root, ".reads", "run-1.ctm.json"), []byte("{}\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if got, err := IDOfDir(s.Path(id)); err != nil || got != want {
		t.Errorf("entry hashes to %s (%v) with sidecars present, want %s", got, err, want)
	}
	if has, err := s.Has(ctx, id); err != nil || !has {
		t.Errorf("Has = %v, %v with sidecars present", has, err)
	}
}
