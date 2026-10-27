package snapshot

import (
	"bytes"
	"context"
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func names(t *testing.T, dir string) []string {
	t.Helper()
	list, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	var out []string
	for _, e := range list {
		out = append(out, e.Name())
	}
	return out
}

// The store is made on the first Put, and files a snapshot under its id as Marshal writes
// it, mode 0644, leaving nothing beside it (R-04).
func TestPutFilesUnderTheID(t *testing.T) {
	ctx := context.Background()
	root := filepath.Join(t.TempDir(), "snapshots")
	store := NewDirStore(root)
	s := Take(fixture(t, "three-node"))

	if _, err := os.Stat(root); !errors.Is(err, fs.ErrNotExist) {
		t.Fatalf("the store exists before its first Put: %v", err)
	}
	id, err := store.Put(ctx, s)
	if err != nil {
		t.Fatal(err)
	}
	if id != s.ID {
		t.Fatalf("Put = %s, want %s", id, s.ID)
	}
	if got, want := store.Path(id), filepath.Join(root, id+".json"); got != want {
		t.Errorf("Path = %s, want %s", got, want)
	}
	dir, err := os.Stat(root)
	if err != nil {
		t.Fatal(err)
	}
	if dir.Mode().Perm() != 0o755 {
		t.Errorf("the store's mode is %v, want 0755", dir.Mode().Perm())
	}
	entry, err := os.Stat(store.Path(id))
	if err != nil {
		t.Fatal(err)
	}
	if entry.Mode().Perm() != 0o644 {
		t.Errorf("the entry's mode is %v, want 0644", entry.Mode().Perm())
	}
	data, _ := os.ReadFile(store.Path(id))
	if want, _ := Marshal(s); !bytes.Equal(data, want) {
		t.Error("the entry is not the stored form")
	}
	if got := names(t, root); len(got) != 1 || got[0] != id+".json" {
		t.Errorf("the store holds %v, want exactly [%s.json]", got, id)
	}
	if has, err := store.Has(ctx, id); err != nil || !has {
		t.Errorf("Has = %v, %v; want true", has, err)
	}
	fetched, err := store.Fetch(ctx, id)
	if err != nil {
		t.Fatal(err)
	}
	if fetched.ID != id || fetched.ObservedAt != s.ObservedAt {
		t.Errorf("Fetch = %s at %s, want %s at %s", fetched.ID, fetched.ObservedAt, id, s.ObservedAt)
	}
}

// Two takes of one intent differing only in observed_at are one entry, and the second Put
// writes nothing: the store keeps the first take's (FR-007; the brief's "the first
// take's").
func TestPutKeepsTheFirstTake(t *testing.T) {
	ctx := context.Background()
	root := filepath.Join(t.TempDir(), "snapshots")
	store := NewDirStore(root)
	first, later := Take(fixture(t, "three-node")), Take(fixture(t, "observed-later"))

	id, err := store.Put(ctx, first)
	if err != nil {
		t.Fatal(err)
	}
	// Back-date the entry, so a rewrite within the clock's resolution could not hide.
	old := time.Now().Add(-time.Hour).Truncate(time.Second)
	if err := os.Chtimes(store.Path(id), old, old); err != nil {
		t.Fatal(err)
	}
	before, err := os.ReadFile(store.Path(id))
	if err != nil {
		t.Fatal(err)
	}

	again, err := store.Put(ctx, later)
	if err != nil || again != id {
		t.Fatalf("second Put = %s, %v; want %s", again, err, id)
	}
	after, _ := os.ReadFile(store.Path(id))
	if !bytes.Equal(before, after) {
		t.Error("the second Put rewrote the entry; it must keep the first take")
	}
	info, _ := os.Stat(store.Path(id))
	if !info.ModTime().Equal(old) {
		t.Errorf("the entry's modification time moved to %v; the second Put must write nothing", info.ModTime())
	}
	fetched, err := store.Fetch(ctx, id)
	if err != nil {
		t.Fatal(err)
	}
	if fetched.ObservedAt != first.ObservedAt {
		t.Errorf("the store holds observed_at %s, want the first take's %s", fetched.ObservedAt, first.ObservedAt)
	}
	if got := names(t, root); len(got) != 1 {
		t.Errorf("the store holds %v, want one entry", got)
	}
}

// An entry overwritten by hand is refused, at its path, and kept: Put never overwrites,
// and the server files the refusal as snapshot.id.mismatch naming the path.
func TestPutRefusesACorruptEntry(t *testing.T) {
	ctx := context.Background()
	s, other := Take(fixture(t, "three-node")), Take(fixture(t, "lossy"))

	for _, tc := range []struct {
		name    string
		corrupt func(t *testing.T, path string)
		got     string
	}{
		// Another snapshot's document, whole and valid, under this id's name.
		{"another snapshot", func(t *testing.T, path string) {
			b, err := Marshal(other)
			if err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(path, b, 0o644); err != nil {
				t.Fatal(err)
			}
		}, other.ID},
		// This id's document with its body edited: it declares the id and hashes to another.
		{"an edited body", func(t *testing.T, path string) {
			b, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			b = bytes.Replace(b, []byte(`"branch": "fylgja-fixture"`), []byte(`"branch": "fylgja-edited"`), 1)
			if err := os.WriteFile(path, b, 0o644); err != nil {
				t.Fatal(err)
			}
		}, ""},
	} {
		t.Run(tc.name, func(t *testing.T) {
			store := NewDirStore(filepath.Join(t.TempDir(), "snapshots"))
			id, err := store.Put(ctx, s)
			if err != nil {
				t.Fatal(err)
			}
			tc.corrupt(t, store.Path(id))
			corrupted, _ := os.ReadFile(store.Path(id))

			_, err = store.Put(ctx, s)
			var mismatch *ErrIDMismatch
			if !errors.As(err, &mismatch) {
				t.Fatalf("Put over a corrupt entry = %T %v, want *ErrIDMismatch", err, err)
			}
			if mismatch.Path != store.Path(id) || mismatch.Want != id || mismatch.Got == id || !IsID(mismatch.Got) {
				t.Errorf("ErrIDMismatch{%s, %s, %s}, want the entry's path, %s and another id", mismatch.Path, mismatch.Want, mismatch.Got, id)
			}
			if tc.got != "" && mismatch.Got != tc.got {
				t.Errorf("ErrIDMismatch.Got = %s, want %s", mismatch.Got, tc.got)
			}
			if want := store.Path(id) + " hashes to " + mismatch.Got + ", not " + id; err.Error() != want {
				t.Errorf("message %q, want %q", err, want)
			}
			if after, _ := os.ReadFile(store.Path(id)); !bytes.Equal(after, corrupted) {
				t.Error("Put rewrote the corrupt entry; it must keep it for the operator to read")
			}
			if _, err := store.Fetch(ctx, id); !errors.As(err, &mismatch) {
				t.Errorf("Fetch of a corrupt entry = %v, want *ErrIDMismatch", err)
			}
		})
	}
}

// An id the store does not hold is fs.ErrNotExist, which the server files as
// snapshot.unknown; a store not yet made holds none.
func TestFetchUnknownIsNotExist(t *testing.T) {
	ctx := context.Background()
	store := NewDirStore(filepath.Join(t.TempDir(), "snapshots"))
	id := Take(fixture(t, "three-node")).ID
	if _, err := store.Fetch(ctx, id); !errors.Is(err, fs.ErrNotExist) {
		t.Errorf("Fetch from a store not yet made = %v, want fs.ErrNotExist", err)
	}
	if _, err := store.Put(ctx, Take(fixture(t, "lossy"))); err != nil {
		t.Fatal(err)
	}
	if _, err := store.Fetch(ctx, id); !errors.Is(err, fs.ErrNotExist) {
		t.Errorf("Fetch of an id the store does not hold = %v, want fs.ErrNotExist", err)
	}
	if has, err := store.Has(ctx, id); err != nil || has {
		t.Errorf("Has = %v, %v; want false", has, err)
	}
}

// A corrupt entry is not an entry: Has is false, with no error, whether the entry hashes
// to another id or is no snapshot at all.
func TestHasIsFalseForACorruptEntry(t *testing.T) {
	ctx := context.Background()
	for name, body := range map[string][]byte{
		"another snapshot": func() []byte {
			b, err := Marshal(Take(fixture(t, "mixed")))
			if err != nil {
				t.Fatal(err)
			}
			return b
		}(),
		"no snapshot": []byte("not json\n"),
		"truncated":   []byte(`{"snapshot_version": "1", "ctm": {`),
	} {
		t.Run(name, func(t *testing.T) {
			store := NewDirStore(filepath.Join(t.TempDir(), "snapshots"))
			id, err := store.Put(ctx, Take(fixture(t, "three-node")))
			if err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(store.Path(id), body, 0o644); err != nil {
				t.Fatal(err)
			}
			if has, err := store.Has(ctx, id); err != nil || has {
				t.Errorf("Has = %v, %v; want false, nil", has, err)
			}
			if _, err := store.Put(ctx, Take(fixture(t, "three-node"))); err == nil {
				t.Error("Put kept a corrupt entry as if it were the snapshot")
			}
		})
	}
}

// Only an id names an entry: anything else is never joined to the store's root.
func TestStoreRefusesWhatIsNotAnID(t *testing.T) {
	ctx := context.Background()
	store := NewDirStore(filepath.Join(t.TempDir(), "snapshots"))
	for _, id := range []string{"", "../escape", "ABC", "6A8A77FC65BDF47B9BB3A753D7709875671DF20E32838344F29CFBA46A13F6D6"} {
		if _, err := store.Fetch(ctx, id); err == nil || errors.Is(err, fs.ErrNotExist) {
			t.Errorf("Fetch(%q) = %v, want a refusal of the id", id, err)
		}
		if has, err := store.Has(ctx, id); err == nil || has {
			t.Errorf("Has(%q) = %v, %v, want a refusal of the id", id, has, err)
		}
	}
}
