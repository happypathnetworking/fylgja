package bundle

import (
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
)

// ID is the bundle's content address: the lowercase-hex SHA-256 of a listing of every
// file in the bundle.
//
// The listing is exactly `sha256sum`'s output format — one `<hex>  <path>\n` line per
// regular file, in byte-wise path order, paths relative to the bundle root — so the id
// is recomputable from a directory with standard tools and no Fylgja binary:
//
//	( cd <bundle> && find . -type f | sed 's|^\./||' | LC_ALL=C sort | xargs sha256sum | sha256sum | cut -d' ' -f1 )
//
// That property is the point. A bundle id nobody can verify without the tool that
// produced it is a claim, not a check. Paths are part of the hash, so moving a
// file makes a different bundle; modes, mtimes, ownership and symlinks are not, so the
// id survives a copy.
//
// The id is never written into the bundle: a file holding it would change it.
func ID(files map[string][]byte) string {
	names := make([]string, 0, len(files))
	for name := range files {
		names = append(names, name)
	}
	sort.Strings(names)

	outer := sha256.New()
	for _, name := range names {
		sum := sha256.Sum256(files[name])
		// hash.Hash.Write never returns an error, so there is nothing to handle.
		_, _ = fmt.Fprintf(outer, "%s  %s\n", hex.EncodeToString(sum[:]), name)
	}
	return hex.EncodeToString(outer.Sum(nil))
}

// IDOfDir computes the same id from a bundle on disk.
//
// Implemented separately from ID on purpose: M2 verifies a staged bundle it did not
// compile, and M4 compares a directory against a fresh compile. A test asserts the two
// agree for every fixture, which is what keeps the second implementation honest.
func IDOfDir(dir string) (string, error) {
	type entry struct {
		path string // relative, slash-separated
		abs  string
	}
	var entries []entry
	err := filepath.WalkDir(dir, func(p string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() {
			return nil
		}
		// Regular files only: a symlink or a device node has no bytes of its own to
		// hash, and a bundle has neither.
		if !d.Type().IsRegular() {
			return nil
		}
		rel, err := filepath.Rel(dir, p)
		if err != nil {
			return err
		}
		entries = append(entries, entry{path: filepath.ToSlash(rel), abs: p})
		return nil
	})
	if err != nil {
		return "", fmt.Errorf("reading bundle directory: %w", err)
	}
	sort.Slice(entries, func(i, j int) bool { return entries[i].path < entries[j].path })

	outer := sha256.New()
	for _, e := range entries {
		sum, err := sha256File(e.abs)
		if err != nil {
			return "", err
		}
		_, _ = fmt.Fprintf(outer, "%s  %s\n", sum, e.path)
	}
	return hex.EncodeToString(outer.Sum(nil)), nil
}

// sha256File hashes one file's bytes, streaming so a large artifact never has to be
// held whole.
func sha256File(path string) (string, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", err
	}
	defer func() { _ = f.Close() }()
	h := sha256.New()
	if _, err := io.Copy(h, f); err != nil {
		return "", err
	}
	return hex.EncodeToString(h.Sum(nil)), nil
}

// IsID reports whether s has the shape of a bundle id: 64 lowercase hex digits.
// Uppercase is rejected rather than folded — two spellings of one id would defeat the
// string comparison every caller does.
func IsID(s string) bool {
	if len(s) != 64 {
		return false
	}
	for _, r := range s {
		digit := r >= '0' && r <= '9'
		lowerHex := r >= 'a' && r <= 'f'
		if !digit && !lowerHex {
			return false
		}
	}
	return true
}
