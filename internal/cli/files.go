package cli

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/tree"
)

// Reading and writing the operator's files is all a client's command does beside sending
// and printing. Each sentence is M12's.

// writeCTM writes the CTM a read answered with to path, atomically: a temporary file beside
// it, then a rename, so a cut answer or a failed write leaves no partial file.
func writeCTM(data []byte, path string) error {
	dir := filepath.Dir(path)
	tmp, err := os.CreateTemp(dir, ".fylgja-ctm-*")
	if err != nil {
		return fmt.Errorf("writing CTM: %w", err)
	}
	defer func() { _ = os.Remove(tmp.Name()) }()
	if _, err := tmp.Write(data); err != nil {
		_ = tmp.Close()
		return fmt.Errorf("writing CTM: %w", err)
	}
	if err := tmp.Close(); err != nil {
		return fmt.Errorf("writing CTM: %w", err)
	}
	if err := os.Chmod(tmp.Name(), 0o644); err != nil {
		return fmt.Errorf("writing CTM: %w", err)
	}
	if err := os.Rename(tmp.Name(), path); err != nil {
		return fmt.Errorf("writing CTM: %w", err)
	}
	return nil
}

// readCTM reads the CTM twin compile sends, under the path given, worded as M12's
// ctm.Load worded a file it could not read.
func readCTM(path string) (api.File, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return api.File{}, fmt.Errorf("reading CTM: %w", err)
	}
	return api.File{Path: path, Data: data}, nil
}

// readPackages reads each package psp validate sends, in order, under the path given; one
// it cannot read is the operating system's sentence, as M12's readable gave it.
func readPackages(paths []string) ([]api.File, error) {
	files := make([]api.File, 0, len(paths))
	for _, p := range paths {
		data, err := os.ReadFile(p)
		if err != nil {
			return nil, err
		}
		files = append(files, api.File{Path: p, Data: data})
	}
	return files, nil
}

// readBundle reads the regular files of the bundle directory twin provision sends, each
// under its slash-separated path inside it, in path order. Its failures are
// tree.Read's, worded as bundle.Verify words them.
func readBundle(dir string) ([]api.File, error) {
	m, err := tree.Read(dir)
	if err != nil {
		return nil, err
	}
	names := make([]string, 0, len(m))
	for name := range m {
		names = append(names, name)
	}
	sort.Strings(names)
	files := make([]api.File, 0, len(names))
	for _, name := range names {
		files = append(files, api.File{Path: name, Data: m[name]})
	}
	return files, nil
}

// writeBundle writes the bundle a compile answered with to dir, as M12's bundle.Write did:
// built beside it and moved into place, and a non-empty dir refused.
func writeBundle(files []api.File, dir string) error {
	m := make(map[string][]byte, len(files))
	for _, f := range files {
		m[f.Path] = f.Data
	}
	return tree.Write(m, dir)
}
