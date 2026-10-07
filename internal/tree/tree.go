// Package tree reads a directory of regular files into a map, and writes such a map out
// as a directory. The map is the compiler's file map: a slash-separated path relative to
// the directory, and the file's bytes.
//
// It is shared by the bundle store (internal/bundle's Write is this package's, under its
// old name) and by the API's client, which must not link internal/bundle: the client
// reads a bundle directory to send it and writes the bundle a compile answers with
// (D-040). It imports the standard library alone.
package tree

import (
	"errors"
	"fmt"
	"io/fs"
	"os"
	"path"
	"path/filepath"
	"sort"
	"strings"
)

// ErrNotEmpty reports that the target directory already holds something.
type ErrNotEmpty struct{ Dir string }

func (e *ErrNotEmpty) Error() string {
	return fmt.Sprintf("output directory %s is not empty", e.Dir)
}

// Write materialises a bundle at dir.
//
// The bundle is built in a temporary sibling directory and moved into place, so the
// target either does not exist or is complete. A target that exists and is non-empty is
// refused rather than merged into: bundles are compared and diffed, and a bundle
// carrying files from two different compiles would be a quiet lie. A path CheckPaths
// refuses is refused before anything is written.
func Write(files map[string][]byte, dir string) error {
	if err := CheckTarget(dir); err != nil {
		return err
	}
	names := sortedPaths(files)
	if err := CheckPaths(names); err != nil {
		return err
	}

	parent := filepath.Dir(dir)
	if err := os.MkdirAll(parent, 0o755); err != nil {
		return fmt.Errorf("preparing output directory: %w", err)
	}
	staging, err := os.MkdirTemp(parent, ".fylgja-bundle-*")
	if err != nil {
		return fmt.Errorf("preparing output directory: %w", err)
	}
	// Any failure from here leaves the target untouched.
	defer func() { _ = os.RemoveAll(staging) }()

	// Written in path order so a failure part-way through is reproducible rather than
	// dependent on Go's map iteration.
	for _, name := range names {
		target := filepath.Join(staging, filepath.FromSlash(name))
		if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
			return err
		}
		if err := os.WriteFile(target, files[name], 0o644); err != nil {
			return err
		}
	}

	if err := os.Remove(dir); err != nil && !os.IsNotExist(err) {
		return fmt.Errorf("clearing output directory: %w", err)
	}
	if err := os.Rename(staging, dir); err != nil {
		return fmt.Errorf("moving bundle into place: %w", err)
	}
	return os.Chmod(dir, 0o755)
}

// Read is the slash-separated path of every regular file under dir, to its bytes. It
// skips anything else, a symlink or a device node, as bundle.IDOfDir hashes regular files
// alone, and descends into sub-directories, which are not entries of their own. A
// sub-directory that cannot be listed is skipped too, so what it holds is not in the map:
// M12's verify read a file it could not reach as one not in the bundle.
//
// A symlink given as dir is followed, so the directory it names is read whole: WalkDir
// does not descend a link it starts at. Every sentence still names dir as given.
//
// A missing path, one that is not a directory and a directory that cannot be listed are
// worded as bundle.Verify words them; a file that cannot be read is named by its path in
// the map, the first in path order, whichever file it is.
func Read(dir string) (map[string][]byte, error) {
	info, err := os.Stat(dir)
	if err != nil {
		return nil, fmt.Errorf("reading bundle directory: %w", err)
	}
	if !info.IsDir() {
		return nil, fmt.Errorf("reading bundle directory: %s is not a directory", dir)
	}
	root := dir
	if link, err := os.Lstat(dir); err == nil && link.Mode()&fs.ModeSymlink != 0 {
		if root, err = filepath.EvalSymlinks(dir); err != nil {
			return nil, fmt.Errorf("reading bundle directory: %w", err)
		}
	}

	type entry struct {
		path string // relative, slash-separated
		abs  string
	}
	var entries []entry
	err = filepath.WalkDir(root, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			if p != root && d != nil && d.IsDir() {
				return fs.SkipDir
			}
			var pathErr *fs.PathError
			if errors.As(err, &pathErr) && pathErr.Path == root {
				pathErr.Path = dir
			}
			return err
		}
		if d.IsDir() || !d.Type().IsRegular() {
			return nil
		}
		rel, err := filepath.Rel(root, p)
		if err != nil {
			return err
		}
		entries = append(entries, entry{path: filepath.ToSlash(rel), abs: filepath.Join(dir, rel)})
		return nil
	})
	if err != nil {
		return nil, fmt.Errorf("reading bundle directory: %w", err)
	}
	sort.Slice(entries, func(i, j int) bool { return entries[i].path < entries[j].path })

	files := make(map[string][]byte, len(entries))
	for _, e := range entries {
		b, err := os.ReadFile(e.abs)
		if err != nil {
			return nil, fmt.Errorf("reading %s: %w", e.path, err)
		}
		files[e.path] = b
	}
	return files, nil
}

// CheckTarget allows a missing directory or an empty one, and nothing else: an existing
// one with anything in it is *ErrNotEmpty.
func CheckTarget(dir string) error {
	entries, err := os.ReadDir(dir)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return fmt.Errorf("inspecting output directory: %w", err)
	}
	if len(entries) > 0 {
		return &ErrNotEmpty{Dir: dir}
	}
	return nil
}

// CheckPaths refuses a set of bundle paths that cannot all be files of one bundle: one
// checkPath refuses, one given twice, or one beneath another, which names a file where a
// directory would have to be. Each sentence names the path inside the bundle and nothing
// outside it, and the first refused in path order is the one named. The API's server checks
// the paths a request sent before it writes any of them, so no refusal names its scratch
// copy.
func CheckPaths(names []string) error {
	sorted := append([]string(nil), names...)
	sort.Strings(sorted)
	seen := make(map[string]bool, len(sorted))
	for _, name := range sorted {
		if err := checkPath(name); err != nil {
			return err
		}
		if seen[name] {
			return fmt.Errorf("bundle path %q is given twice", name)
		}
		for dir := path.Dir(name); dir != "."; dir = path.Dir(dir) {
			if seen[dir] {
				return fmt.Errorf("bundle path %q lies beneath %q, which is a file", name, dir)
			}
		}
		seen[name] = true
	}
	return nil
}

// checkPath refuses anything that would write outside the bundle, or onto its root. The
// compiler builds every path in this map, so none of these can happen from it; the check
// is here because "the only caller is trusted" is how a path traversal gets in later, and
// the API's server writes the paths a request sent.
func checkPath(name string) error {
	switch {
	case name == "":
		return fmt.Errorf("bundle holds a file with no name")
	case strings.HasPrefix(name, "/"), strings.HasPrefix(name, "./"):
		return fmt.Errorf("bundle path %q is not relative to the bundle root", name)
	case name != filepath.ToSlash(filepath.Clean(name)):
		return fmt.Errorf("bundle path %q is not in canonical form", name)
	case name == "..", strings.HasPrefix(name, "../"):
		return fmt.Errorf("bundle path %q escapes the bundle root", name)
	case name == ".":
		return fmt.Errorf("bundle path %q is the bundle root, not a file in it", name)
	}
	return nil
}

// sortedPaths orders bundle paths byte-wise, the same order bundle.ID uses.
func sortedPaths(files map[string][]byte) []string {
	names := make([]string, 0, len(files))
	for name := range files {
		names = append(names, name)
	}
	sort.Strings(names)
	return names
}
