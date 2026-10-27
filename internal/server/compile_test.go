package server

import (
	"os"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

// twin compile reads the snapshot by snapshot.Unmarshal's rules, each refusal under its own
// identifier as twin create --snapshot refuses the file, but with no step, as M1's
// operations carry none (R-03; contracts/cli.md, "018: snapshots"). A refused snapshot names
// no snapshot and no bundle, and nothing is filed: the compile reads no state root.
func TestCompileRefusesASnapshotByItsRules(t *testing.T) {
	for _, c := range fileRefusals(t) {
		t.Run(c.name, func(t *testing.T) {
			paths := useStateRoot(t)
			code, doc := exitOf(t, runCompile(testOptions(t, true), &compileFlags{snapshotPath: "snap.json", out: "out"}, c.files))
			if code != c.code || len(doc.Findings) != 1 {
				t.Fatalf("exit %d, findings %+v; want %d with %s alone", code, doc.Findings, c.code, c.rule)
			}
			// An operational failure names the operation, as twin compile's have since M1.
			object := c.object
			if c.rule == findings.RuleOperationFailed {
				object = findings.OpCompile
			}
			f := doc.Findings[0]
			matches := f.Message == c.message || c.messagePrefix && strings.HasPrefix(f.Message, c.message)
			if f.Rule != c.rule || f.Step != "" || f.Object != object || !matches {
				t.Errorf("finding %+v; want %s with no step on %s: %s", f, c.rule, object, c.message)
			}
			if doc.SnapshotID != "" || doc.BundleID != "" || doc.Subject == nil || doc.Subject.Snapshot != "snap.json" ||
				doc.Subject.CTM != "" {
				t.Errorf("document names snapshot %q, bundle %q, subject %+v; want neither id, and snap.json as the snapshot",
					doc.SnapshotID, doc.BundleID, doc.Subject)
			}
			if entries, err := os.ReadDir(paths.Root); err != nil || len(entries) != 0 {
				t.Errorf("the state root holds %v (%v) after a refused compile", entries, err)
			}
			validateWithShow(t, currentContract, "018", doc)
		})
	}
}

// A compile names the snapshot it compiled beside the bundle, in its text and its document,
// files neither and reads no state root: the snapshot is its input and the bundle its output
// (FR-019). The subject names the snapshot as given, and no CTM.
func TestCompileNamesTheSnapshotAndFilesNothing(t *testing.T) {
	paths := useStateRoot(t)
	flags := &compileFlags{snapshotPath: "snap.json", out: "out"}
	var err error
	out := captureStdout(t, func() { err = runCompile(testOptions(t, false), flags, fixtureFile(t, nil)) })
	if code, doc := exitOf(t, err); code != findings.ExitOK {
		t.Fatalf("exit %d, findings %+v; want 0", code, doc.Findings)
	}
	if want := "wrote bundle to out (3 nodes, 3 links)\nsnapshot_id " + fixtureSnapshotID + "\nbundle_id " + fixtureBundleID + "\n"; out != want {
		t.Errorf("stdout:\n%s\nwant:\n%s", out, want)
	}

	// Declaring neither its id nor its observed_at, as a hand-wrapped CTM does, the snapshot
	// is the same one.
	bare := fixtureFile(t, func(d map[string]any) {
		delete(d, "snapshot_id")
		delete(d, "observed_at")
	})
	code, doc := exitOf(t, runCompile(testOptions(t, true), flags, bare))
	if code != findings.ExitOK || doc.SnapshotID != fixtureSnapshotID || doc.BundleID != fixtureBundleID {
		t.Fatalf("exit %d, snapshot %q, bundle %q; want 0, %s and %s", code, doc.SnapshotID, doc.BundleID, fixtureSnapshotID,
			fixtureBundleID)
	}
	if s := doc.Subject; s == nil || s.Snapshot != "snap.json" || s.CTM != "" || s.Out != "out" || s.Branch != "fylgja-fixture" {
		t.Errorf("subject %+v; want the snapshot snap.json, no CTM, out and the envelope's branch", s)
	}
	if entries, err := os.ReadDir(paths.Root); err != nil || len(entries) != 0 {
		t.Errorf("the state root holds %v (%v) after a compile", entries, err)
	}
	validateWithShow(t, currentContract, "018", doc)
}
