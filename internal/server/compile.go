package server

import (
	"encoding/json"
	"errors"
	"fmt"
	"sort"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/stage"
)

type compileFlags struct {
	ctmPath string
	out     string
}

// runCompile compiles the CTM the client sent under --ctm's path, and answers with the
// bundle in one files frame, which the client writes to --out: the server opens neither
// path.
// The compile is the golden tests' (Constitution V).
func runCompile(opts *options, f *compileFlags, files []api.File) error {
	subject := &findings.Subject{CTM: f.ctmPath, Out: f.out}

	if f.ctmPath == "" {
		return fail(findings.OpCompile, subject, "--ctm is required")
	}
	if f.out == "" {
		return fail(findings.OpCompile, subject, "--out is required")
	}

	// An unreadable or malformed file is an operational failure, not a rejection:
	// nothing was validated, so there is nothing to report findings about. The client read
	// the file, and words its own failure to read it as ctm.Load did.
	if len(files) != 1 {
		return fail(findings.OpCompile, subject, "the request carries %d files where twin compile takes the CTM alone", len(files))
	}
	// The file is the CTM --ctm names, sent under that path, as psp validate's are:
	// one under another path is refused before it is parsed, so no finding or line names
	// --ctm's path for a CTM never sent under it (contracts/api.md, "Files").
	// The CLI never sends one. The sentence names nothing of the file.
	if files[0].Path != f.ctmPath {
		return fail(findings.OpCompile, subject, "the request carries its CTM under another path than --ctm gives, where twin compile takes the CTM alone, under that path")
	}
	c, err := ctm.Unmarshal(files[0].Data)
	// A CTM of another version is refused alone, before any package is loaded, naming the
	// file the operator gave and both versions: every other finding would be about a format
	// this build does not read, and nothing converts one (FR-028). With no step, as M1's
	// operations carry none.
	// A CTM declaring no version is refused alike, as a file of no version this build reads.
	var other *ctm.VersionError
	if errors.As(err, &other) {
		var list findings.List
		list.Add(findings.Rejection, findings.RuleCTMVersionUnsupported, f.ctmPath, ctmVersionMessage(other))
		return finish(findings.OpCompile, subject, list)
	}
	// A file that leaves out a field the contract requires, which Normalize would fill, is
	// named as validation names an empty envelope field: the fidelity list left out would
	// otherwise compile to a manifest saying the reader approximated and omitted nothing.
	var missing *ctm.MissingError
	if errors.As(err, &missing) {
		var list findings.List
		list.Add(findings.Rejection, findings.RuleRequiredMissing, missing.Field, missing.Message)
		return finish(findings.OpCompile, subject, list)
	}
	if err != nil {
		return fail(findings.OpCompile, subject, "%v", err)
	}
	subject.Branch, subject.At = c.Envelope.Branch, c.Envelope.At

	reg, err := psp.Load(opts.pspDir)
	if err != nil {
		return loadFailure(findings.OpCompile, subject, err)
	}

	// Validation, compilation and the identity, on the pipeline a create runs inside its
	// run (internal/stage). Rejections stop everything: a bundle is never written from
	// intent that could not be built faithfully. The id is computed from the
	// bytes before they are written, so what is printed describes what was compiled.
	bundled, id, list := stage.Compile(c, reg)
	if list.Rejected() {
		return finish(findings.OpCompile, subject, list)
	}

	if err := opts.c.files(bundleFiles(bundled)); err != nil {
		return err
	}

	nodes, links := manifestCounts(bundled)
	opts.note("wrote bundle to %s (%d nodes, %d links)", f.out, nodes, links)
	opts.note("bundle_id %s", id)

	doc := findings.NewDocument(findings.OpCompile, subject, list)
	doc.BundleID = id
	return &result{doc: doc}
}

// ctmVersionMessage is ctm.version.unsupported's message for a CTM declaring another version,
// or none, naming both: a bare CTM's and a snapshot's inner one's alike.
func ctmVersionMessage(other *ctm.VersionError) string {
	declares := fmt.Sprintf("declares ctm_version %q", other.Got)
	if other.Got == "" {
		declares = "declares no ctm_version"
	}
	return fmt.Sprintf("the CTM %s; this build reads %q, and nothing converts one", declares, ctm.Version)
}

// manifestCounts reads the node and link counts back out of the manifest the compiler
// just produced, so the success line counts what the bundle actually contains rather
// than what intent asked for — the two differ whenever something was omitted.
func manifestCounts(files map[string][]byte) (nodes, links int) {
	var m compiler.Manifest
	if err := json.Unmarshal(files[compiler.ManifestFile], &m); err != nil {
		return 0, 0
	}
	return len(m.Nodes), len(m.Links)
}

// bundleFiles are a compiled bundle's files as they cross, in path order, the order the
// bundle's identity reads them in.
func bundleFiles(files map[string][]byte) []api.File {
	names := make([]string, 0, len(files))
	for name := range files {
		names = append(names, name)
	}
	sort.Strings(names)
	out := make([]api.File, 0, len(names))
	for _, name := range names {
		out = append(out, api.File{Path: name, Data: files[name]})
	}
	return out
}
