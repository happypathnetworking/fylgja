package snapshot

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
)

// Store keeps snapshots by identity (D-014, D-061), as bundle.Store keeps bundles. It is
// small enough to be replaced by object storage at M8 (Constitution IX), which is why it
// speaks in ids and paths and nothing about how bytes are kept. Two interfaces of one
// shape rather than one generic: the currencies differ, a directory of files and one
// document, and nothing needs the abstraction before M8 replaces both (R-04).
//
// There is no listing and no deletion: snapshots accumulate, as bundles do.
type Store interface {
	// Put files s under the id its body hashes to, keeping an entry already there after
	// verifying it, and returns the id. It never overwrites: the first take's observed_at
	// is the one kept.
	Put(ctx context.Context, s *Snapshot) (string, error)
	// Has reports whether an entry for id exists and hashes to id. A corrupt entry is not
	// one.
	Has(ctx context.Context, id string) (bool, error)
	// Path is the absolute location of the entry for id: what a line or a record names.
	Path(id string) string
	// Fetch reads the entry for id and verifies that its body hashes to id. An absent
	// entry is an error matching fs.ErrNotExist.
	Fetch(ctx context.Context, id string) (*Snapshot, error)
}

// ErrIDMismatch reports an entry at Path whose body hashes to Got where Want was claimed,
// or, when Declared is set, whose body hashes to Want but which declares snapshot_id
// Declared: a corrupt store entry either way.
type ErrIDMismatch struct {
	Path, Want, Got string
	// Declared is the snapshot_id the entry declares when its body hashes to Want and the
	// entry declares another; empty when the body hashes to another id.
	Declared string
}

func (e *ErrIDMismatch) Error() string {
	if e.Declared != "" {
		return fmt.Sprintf("%s declares snapshot_id %s, but its body hashes to %s", e.Path, e.Declared, e.Got)
	}
	return fmt.Sprintf("%s hashes to %s, not %s", e.Path, e.Got, e.Want)
}

// DirStore is the Store on a local directory: <root>/<id>.json per snapshot, written as
// Marshal writes it.
type DirStore struct {
	root string
}

// NewDirStore returns a store rooted at dir, the state root's snapshots directory. The
// directory is created on first Put.
func NewDirStore(dir string) *DirStore {
	return &DirStore{root: dir}
}

var _ Store = (*DirStore)(nil)

// Path implements Store.
func (s *DirStore) Path(id string) string {
	return filepath.Join(s.root, id+".json")
}

// Put implements Store. A present entry is verified and kept, never rewritten; an absent
// one is written to a temporary sibling and linked into place, so an entry is either
// complete or not there, and a second Put racing the first cannot replace it.
func (s *DirStore) Put(_ context.Context, snap *Snapshot) (string, error) {
	data, err := Marshal(snap)
	if err != nil {
		return "", err
	}
	id := snap.ID
	if _, present, err := s.verifyEntry(id); err != nil || present {
		return id, err
	}
	if err := os.MkdirAll(s.root, 0o755); err != nil {
		return "", fmt.Errorf("preparing the snapshot store: %w", err)
	}
	tmp, err := os.CreateTemp(s.root, ".fylgja-snapshot-*")
	if err != nil {
		return "", fmt.Errorf("storing snapshot %s: %w", id, err)
	}
	defer func() { _ = os.Remove(tmp.Name()) }()
	if err := writeAndClose(tmp, data); err != nil {
		return "", fmt.Errorf("storing snapshot %s: %w", id, err)
	}
	// A link, not a rename: a rename replaces a file already there, and the store never
	// overwrites. Another Put of the same snapshot may have linked its copy first; that is
	// the same entry, not a failure, provided it verifies.
	if err := os.Link(tmp.Name(), s.Path(id)); err != nil {
		if _, present, verr := s.verifyEntry(id); verr == nil && present {
			return id, nil
		}
		return "", fmt.Errorf("storing snapshot %s: %w", id, err)
	}
	return id, nil
}

// Has implements Store. A corrupt entry is not an entry: Has says false and Fetch or Put
// say why.
func (s *DirStore) Has(_ context.Context, id string) (bool, error) {
	_, present, err := s.verifyEntry(id)
	var mismatch *ErrIDMismatch
	var corrupt *entryError
	if errors.As(err, &mismatch) || errors.As(err, &corrupt) {
		return false, nil
	}
	return present, err
}

// Fetch implements Store. The entry is read through Unmarshal and verified, so a corrupt
// one is reported at its store path.
func (s *DirStore) Fetch(_ context.Context, id string) (*Snapshot, error) {
	snap, present, err := s.verifyEntry(id)
	if err != nil {
		return nil, err
	}
	if !present {
		return nil, fmt.Errorf("snapshot %s is not in the store at %s: %w", id, s.root, os.ErrNotExist)
	}
	return snap, nil
}

// verifyEntry reads the entry for id, reporting whether it exists, an *ErrIDMismatch
// naming its path when its body hashes to anything else or declares another id, and an
// *entryError when it is no snapshot at all.
func (s *DirStore) verifyEntry(id string) (*Snapshot, bool, error) {
	// An id is the only name an entry has: anything else is never joined to the root.
	if !IsID(id) {
		return nil, false, fmt.Errorf("%q is not a snapshot id: 64 lowercase hex characters", id)
	}
	path := s.Path(id)
	data, err := os.ReadFile(path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil, false, nil
		}
		return nil, false, fmt.Errorf("inspecting the snapshot store: %w", err)
	}
	snap, err := Unmarshal(data)
	var declared *IDMismatchError
	switch {
	case errors.As(err, &declared) && declared.Computed == id:
		return nil, false, &ErrIDMismatch{Path: path, Want: id, Got: id, Declared: declared.Declared}
	case errors.As(err, &declared):
		return nil, false, &ErrIDMismatch{Path: path, Want: id, Got: declared.Computed}
	case err != nil:
		return nil, false, &entryError{path: path, err: err}
	case snap.ID != id:
		return nil, false, &ErrIDMismatch{Path: path, Want: id, Got: snap.ID}
	}
	return snap, true, nil
}

// entryError is an entry Unmarshal refuses: no snapshot, so it hashes to nothing.
type entryError struct {
	path string
	err  error
}

func (e *entryError) Error() string {
	return fmt.Sprintf("%s is not a snapshot: %v", e.path, e.err)
}

func (e *entryError) Unwrap() error { return e.err }
