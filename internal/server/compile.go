package server

import (
	"encoding/json"
	"fmt"
	"sort"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/snapshot"
	"github.com/happypathnetworking/fylgja/internal/stage"
)

type compileFlags struct {
	// snapshotPath is --snapshot as given, the path the snapshot file crosses under (018: in
	// place of --ctm, which is retired).
	snapshotPath string
	out          string
}

// runCompile compiles the CTM of the snapshot the client sent under --snapshot's path, and
// answers with the bundle in one files frame, which the client writes to --out: the server
// opens neither path. Nothing is filed and no state root is read: the snapshot is the
// compile's input and the bundle its output, as the golden tests' (018, FR-019).
// The compile is the golden tests' (Constitution V).
func runCompile(opts *options, f *compileFlags, files []api.File) error {
	subject := &findings.Subject{Snapshot: f.snapshotPath, Out: f.out}

	if f.snapshotPath == "" {
		return fail(findings.OpCompile, subject, "--snapshot is required")
	}
	if f.out == "" {
		return fail(findings.OpCompile, subject, "--out is required")
	}

	// An unreadable or malformed file is an operational failure, not a rejection:
	// nothing was validated, so there is nothing to report findings about. The client read
	// the file, and words its own failure to read it as snapshot.Load does.
	if len(files) != 1 {
		return fail(findings.OpCompile, subject, "the request carries %d files where twin compile takes the snapshot alone", len(files))
	}
	// The file is the snapshot --snapshot names, sent under that path, as psp validate's
	// are: one under another path is refused before it is parsed, so no finding or line
	// names --snapshot's path for a snapshot never sent under it (contracts/api.md, "Files").
	// The CLI never sends one. The sentence names nothing of the file.
	if files[0].Path != f.snapshotPath {
		return fail(findings.OpCompile, subject, "the request carries its snapshot under another path than --snapshot gives, "+
			"where twin compile takes the snapshot alone, under that path")
	}
	// The snapshot is read by its own rules, each refusal under its identifier with no step,
	// as M1's operations carry none (R-03): a snapshot of another version, or a bare CTM,
	// which declares none, is refused alone, before any package is loaded, since every other
	// finding would be about a format this build does not read; the inner CTM's version and
	// required fields as a bare CTM's were, the version at the file and a missing field at its
	// name prefixed ctm.
	s, err := snapshot.Unmarshal(files[0].Data)
	if err != nil {
		if list, ok := snapshotRefusal(f.snapshotPath, err); ok {
			return finish(findings.OpCompile, subject, list)
		}
		return fail(findings.OpCompile, subject, "%v", err)
	}
	c := s.CTM
	subject.Branch, subject.At = c.Envelope.Branch, c.Envelope.At

	reg, err := psp.Load(opts.pspDir)
	if err != nil {
		return loadFailure(findings.OpCompile, subject, err)
	}

	// Validation, compilation and the identity, on the pipeline a create runs before its
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
	opts.note("snapshot_id %s", s.ID)
	opts.note("bundle_id %s", id)

	doc := findings.NewDocument(findings.OpCompile, subject, list)
	doc.SnapshotID = s.ID
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
