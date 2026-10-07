package bundle

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// LoadFiles reads a bundle directory into the map ID hashes: every regular file, keyed by
// its slash-separated path relative to dir. It is the reader beside IDOfDir that a step
// needs: the step is computed from the
// bundle the twin was built from, read out of the store into a step.Bundle, whose Files
// is this map.
//
// It walks as IDOfDir walks, regular files under dir with paths relative to it, so
// ID(LoadFiles(dir)) is IDOfDir(dir); a test holds the two equal for every golden, as
// ID and IDOfDir are held equal. Where IDOfDir skips an entry with no bytes of its own,
// LoadFiles refuses it, naming it: a bundle holds regular files only, and a map that
// quietly lacked a symlink would be a different bundle from the directory it was read
// from. A path that leads out of the bundle is refused the same way.
func LoadFiles(dir string) (map[string][]byte, error) {
	info, err := os.Lstat(dir)
	if err != nil {
		return nil, fmt.Errorf("reading bundle directory: %w", err)
	}
	if !info.IsDir() {
		return nil, fmt.Errorf("reading bundle directory: %s is not a directory", dir)
	}
	files := map[string][]byte{}
	err = filepath.WalkDir(dir, func(p string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() {
			return nil
		}
		rel, err := insideBundle(dir, p)
		if err != nil {
			return err
		}
		// WalkDir does not follow a symbolic link, so a link to a directory arrives here
		// too, as a link.
		if d.Type()&os.ModeSymlink != 0 {
			return fmt.Errorf("%s is a symbolic link; a bundle holds regular files only", rel)
		}
		if !d.Type().IsRegular() {
			return fmt.Errorf("%s is not a regular file (%s); a bundle holds regular files only", rel, d.Type())
		}
		b, err := os.ReadFile(p)
		if err != nil {
			return err
		}
		files[rel] = b
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("reading bundle directory %s: %w", dir, err)
	}
	return files, nil
}

// insideBundle gives p's path relative to the bundle root, slash-separated, as ID keys
// it, or refuses one that leads out of the bundle.
func insideBundle(dir, p string) (string, error) {
	rel, err := filepath.Rel(dir, p)
	if err != nil {
		return "", err
	}
	rel = filepath.ToSlash(rel)
	if rel == ".." || strings.HasPrefix(rel, "../") {
		return "", fmt.Errorf("%s leads out of the bundle", rel)
	}
	return rel, nil
}
