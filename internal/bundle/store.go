package bundle

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
)

// Store keeps compiled bundles by identity (D-014, D-024). It is small
// enough to be replaced by object storage at M8 (Constitution IX), which is why it
// speaks in ids and paths and nothing about how bytes are kept.
//
// There is no listing and no deletion: nothing at M2 needs either, and bundles
// accumulate (architecture §3).
type Store interface {
	// Put files the bundle in srcDir under the id its bytes hash to, reusing an entry
	// already there after verifying it, and returns the id.
	Put(ctx context.Context, srcDir string) (string, error)
	// Has reports whether an entry for id exists and hashes to id.
	Has(ctx context.Context, id string) (bool, error)
	// Path is the absolute location of the entry for id: what crosses the task queue.
	Path(id string) string
	// Fetch copies the entry for id to dstDir and verifies the copy hashes to id.
	Fetch(ctx context.Context, id, dstDir string) error
	// PutCTM keeps the CTM a read produced beside its bundle, overwriting any earlier one.
	PutCTM(ctx context.Context, id, ctmPath string) error
}

// ErrIDMismatch reports bytes at Path that hash to Got where Want was claimed: a
// corrupt store entry, or a copy that did not survive the copy.
type ErrIDMismatch struct {
	Path, Want, Got string
}

func (e *ErrIDMismatch) Error() string {
	return fmt.Sprintf("%s hashes to %s, not %s", e.Path, e.Got, e.Want)
}

// DirStore is the Store on a local directory: <root>/<id>/ per bundle and
// <root>/<id>.ctm.json beside it. The sidecar sits outside the hashed directory, so
// keeping a CTM never changes an entry's id.
type DirStore struct {
	root string
}

// NewDirStore returns a store rooted at dir, the state root's bundles directory. The
// directory is created on first Put.
func NewDirStore(dir string) *DirStore {
	return &DirStore{root: dir}
}

var _ Store = (*DirStore)(nil)

// Path implements Store.
func (s *DirStore) Path(id string) string {
	return filepath.Join(s.root, id)
}

// Put implements Store. A present entry is verified and reused, never duplicated or
// overwritten; an absent one is copied to a temporary sibling and renamed into place, so
// an entry is either complete or not there.
func (s *DirStore) Put(ctx context.Context, srcDir string) (string, error) {
	id, err := IDOfDir(srcDir)
	if err != nil {
		return "", err
	}
	dst := s.Path(id)
	if present, err := s.verifyEntry(id); err != nil || present {
		return id, err
	}
	if err := os.MkdirAll(s.root, 0o755); err != nil {
		return "", fmt.Errorf("preparing the bundle store: %w", err)
	}
	if err := copyDirAtomic(ctx, srcDir, dst, id); err != nil {
		// Another Put of the same bundle may have renamed its copy into place first.
		// That is the same end state, not a failure, provided the entry verifies.
		if present, verr := s.verifyEntry(id); verr == nil && present {
			return id, nil
		}
		return "", err
	}
	return id, nil
}

// PutFiles writes a compiled bundle's files into a temporary directory under scratch and
// files that directory in s, so a compile inside a run and a dry run file bundles the one
// way. The temporary copy is removed whatever happens. The id returned is what the
// written bytes hash to; a caller holding the compiler's id compares the two.
func PutFiles(ctx context.Context, s Store, files map[string][]byte, scratch string) (string, error) {
	if err := os.MkdirAll(scratch, 0o755); err != nil {
		return "", fmt.Errorf("preparing %s: %w", scratch, err)
	}
	written, err := os.MkdirTemp(scratch, ".fylgja-compile-*")
	if err != nil {
		return "", fmt.Errorf("preparing %s: %w", scratch, err)
	}
	defer func() { _ = os.RemoveAll(written) }()
	if err := Write(files, written); err != nil {
		return "", err
	}
	return s.Put(ctx, written)
}

// Has implements Store. A corrupt entry is not an entry: Has says false and Fetch or
// Put say why.
func (s *DirStore) Has(_ context.Context, id string) (bool, error) {
	present, err := s.verifyEntry(id)
	var mismatch *ErrIDMismatch
	if errors.As(err, &mismatch) {
		return false, nil
	}
	return present, err
}

// Fetch implements Store. The entry is verified before it is copied, so a corrupt one
// is reported at its store path, and the copy is verified before it is renamed into
// place, so dstDir either does not exist or hashes to id.
func (s *DirStore) Fetch(ctx context.Context, id, dstDir string) error {
	present, err := s.verifyEntry(id)
	if err != nil {
		return err
	}
	if !present {
		return fmt.Errorf("bundle %s is not in the store at %s", id, s.root)
	}
	if err := checkTarget(dstDir); err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(dstDir), 0o755); err != nil {
		return fmt.Errorf("preparing %s: %w", dstDir, err)
	}
	return copyDirAtomic(ctx, s.Path(id), dstDir, id)
}

// PutCTM implements Store: the latest read of an intent replaces an earlier one, which
// is the more useful record.
func (s *DirStore) PutCTM(_ context.Context, id, ctmPath string) error {
	if err := os.MkdirAll(s.root, 0o755); err != nil {
		return fmt.Errorf("preparing the bundle store: %w", err)
	}
	dst := filepath.Join(s.root, id+".ctm.json")
	tmp, err := os.CreateTemp(s.root, ".fylgja-ctm-*")
	if err != nil {
		return fmt.Errorf("storing CTM: %w", err)
	}
	defer func() { _ = os.Remove(tmp.Name()) }()
	if err := copyFileTo(ctmPath, tmp); err != nil {
		_ = tmp.Close()
		return fmt.Errorf("storing CTM: %w", err)
	}
	if err := tmp.Close(); err != nil {
		return fmt.Errorf("storing CTM: %w", err)
	}
	if err := os.Chmod(tmp.Name(), 0o644); err != nil {
		return fmt.Errorf("storing CTM: %w", err)
	}
	if err := os.Rename(tmp.Name(), dst); err != nil {
		return fmt.Errorf("storing CTM: %w", err)
	}
	return nil
}

// verifyEntry reports whether the entry for id exists, and an *ErrIDMismatch naming its
// path when it exists and hashes to anything else.
func (s *DirStore) verifyEntry(id string) (bool, error) {
	dir := s.Path(id)
	if _, err := os.Stat(dir); err != nil {
		if os.IsNotExist(err) {
			return false, nil
		}
		return false, fmt.Errorf("inspecting the bundle store: %w", err)
	}
	got, err := IDOfDir(dir)
	if err != nil {
		return false, err
	}
	if got != id {
		return false, &ErrIDMismatch{Path: dir, Want: id, Got: got}
	}
	return true, nil
}

// copyDirAtomic copies the regular files under src into a temporary sibling of dst,
// verifies the copy hashes to id, and renames it to dst. Regular files only, because
// only regular files are part of a bundle's identity (IDOfDir).
func copyDirAtomic(ctx context.Context, src, dst, id string) error {
	staging, err := os.MkdirTemp(filepath.Dir(dst), ".fylgja-copy-*")
	if err != nil {
		return fmt.Errorf("copying bundle %s: %w", id, err)
	}
	defer func() { _ = os.RemoveAll(staging) }()

	err = filepath.WalkDir(src, func(p string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if err := ctx.Err(); err != nil {
			return err
		}
		rel, err := filepath.Rel(src, p)
		if err != nil {
			return err
		}
		target := filepath.Join(staging, rel)
		switch {
		case d.IsDir():
			return os.MkdirAll(target, 0o755)
		case d.Type().IsRegular():
			return copyFile(p, target)
		default:
			return nil
		}
	})
	if err != nil {
		return fmt.Errorf("copying bundle %s: %w", id, err)
	}
	got, err := IDOfDir(staging)
	if err != nil {
		return err
	}
	if got != id {
		return &ErrIDMismatch{Path: dst, Want: id, Got: got}
	}
	if err := os.Chmod(staging, 0o755); err != nil {
		return fmt.Errorf("copying bundle %s: %w", id, err)
	}
	if err := os.Rename(staging, dst); err != nil {
		return fmt.Errorf("moving bundle %s into place: %w", id, err)
	}
	return nil
}

func copyFile(src, dst string) error {
	out, err := os.OpenFile(dst, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o644)
	if err != nil {
		return err
	}
	if err := copyFileTo(src, out); err != nil {
		_ = out.Close()
		return err
	}
	return out.Close()
}

func copyFileTo(src string, w io.Writer) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer func() { _ = in.Close() }()
	_, err = io.Copy(w, in)
	return err
}
