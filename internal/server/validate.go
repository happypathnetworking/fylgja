package server

import (
	"bytes"
	"errors"
	"fmt"
	"io"

	"gopkg.in/yaml.v3"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// runPSPValidate reports every defect in the whole set in one pass.
//
// The set is validated together, not file by file, because `psp.identity.duplicate`
// is a property of the set: two packages each valid alone are a defect side by side.
//
// The client read each file, under the path the operator gave, and refused one it could not
// read; the server refuses one that is not one YAML document, then validates the set as the
// files those paths named, so every finding names the operator's path.
func runPSPValidate(opts *options, paths []string, files []api.File) error {
	subject := &findings.Subject{Files: paths}

	// Each path names the one file sent under it, in order: a request that does not is
	// refused before anything is validated, since "valid" would otherwise name a path whose
	// package was never seen, or another file's verdict (contracts/api.md, "Files"). The CLI
	// never sends one. The sentence gives counts, and nothing of a file.
	if !onePackageEach(paths, files) {
		return fail(findings.OpPSPValidate, subject,
			"the request carries %s for %s where psp validate takes at least one path and one package for each, in order and under that path",
			plural(len(files), "file"), plural(len(paths), "path"))
	}

	// A file that holds more than one YAML document is an operational failure rather than
	// a finding: there is no package to report on, so calling it invalid would be a
	// judgement about content nothing has seen (contracts/cli.md, exit 2).
	set := make([]psp.File, 0, len(files))
	for _, f := range files {
		if err := readable(f.Path, f.Data); err != nil {
			return fail(findings.OpPSPValidate, subject, "%v", err)
		}
		set = append(set, psp.File{Path: f.Path, Data: f.Data})
	}

	list := psp.ValidateFiles(set)
	if !list.Rejected() {
		for _, path := range paths {
			opts.note("%s: valid", path)
		}
	}
	return finish(findings.OpPSPValidate, subject, list)
}

// onePackageEach reports whether files are one for each of paths, at least one, in order and
// each under its path.
func onePackageEach(paths []string, files []api.File) bool {
	if len(paths) == 0 || len(files) != len(paths) {
		return false
	}
	for i, f := range files {
		if f.Path != paths[i] {
			return false
		}
	}
	return true
}

// loadFailure reports a failure to load support packages. An override package that
// `psp validate` rejects is a rejection carrying its psp.* findings (exit 1), so every
// command names the defect as `psp validate` would; anything else is the operation
// failing to run (exit 2).
func loadFailure(op string, subject *findings.Subject, err error) error {
	var invalid *psp.InvalidError
	if errors.As(err, &invalid) {
		return finish(op, subject, invalid.Findings)
	}
	return fail(op, subject, "%v", err)
}

// loadFailureAt is loadFailure for a command whose findings belong to a step: twin create
// loads packages for its read, as the run's read step does, and twin provision for its
// verify.
func loadFailureAt(op string, subject *findings.Subject, step string, err error) error {
	var invalid *psp.InvalidError
	if errors.As(err, &invalid) {
		return finish(op, subject, invalid.Findings.AtStep(step))
	}
	return failAt(op, subject, step, step, "%v", err)
}

// readable reports whether the file at path, as the client read it, is a support package
// Fylgja can even attempt to validate: exactly one YAML document. The message names the
// file, because with several on the command line the operator cannot otherwise tell
// which one failed.
func readable(path string, data []byte) error {
	dec := yaml.NewDecoder(bytes.NewReader(data))
	var doc yaml.Node
	if err := dec.Decode(&doc); err != nil {
		// An unparseable file is a schema finding, not an operational failure:
		// psp.Validate reports it with its location, which is more use than exit 2.
		return nil
	}
	if err := dec.Decode(&doc); !errors.Is(err, io.EOF) {
		// A package file is one document; a second one would be silently ignored,
		// which is the failure mode the format cannot survive.
		return fmt.Errorf("%s: a support package file must hold exactly one YAML document", path)
	}
	return nil
}
