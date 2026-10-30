package server

import (
	"bytes"
	"context"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// shippedPackages is the server's registry with no override.
func shippedPackages(t *testing.T) *psp.Registry {
	t.Helper()
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	return reg
}

// A create needs a snapshot (020; D-065): with no --snapshot it is refused at once, exit 2,
// before any file is looked at, anything is filed or the workflow service is dialled.
func TestACreateNeedsASnapshot(t *testing.T) {
	paths := useStateRoot(t)
	useService(t, nil)
	code, doc := exitOf(t, runCreate(context.Background(), testOptions(t, true), &createFlags{dryRun: true}, nil))
	if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleOperationFailed ||
		doc.Findings[0].Message != "--snapshot is required" {
		t.Errorf("exit %d, findings %+v; want 2 with operation.failed: --snapshot is required", code, doc.Findings)
	}
	for _, dir := range []string{paths.Snapshots, paths.Bundles} {
		if _, err := os.Stat(dir); !os.IsNotExist(err) {
			t.Errorf("%s exists after a refused create (%v)", dir, err)
		}
	}
}

// The create's dry run from a snapshot file files it, compiles on the create's own path, then
// reports: the snapshot's stored line above the bundle's, with no read: line, since nothing
// was read (020), and the document names both, valid against the current contract with
// snapshot_id present (T026; R-09).
func TestCreateDryRunFilesTheSnapshot(t *testing.T) {
	paths := useStateRoot(t)
	useService(t, nil)
	dryRunEnv(t)
	useClab(t, "inspect-empty.json")
	flags := func() *createFlags { return &createFlags{snapshot: "snap.json", snapshotGiven: true, dryRun: true} }

	var err error
	out := captureStdout(t, func() {
		err = runCreate(context.Background(), testOptions(t, false), flags(), fixtureFile(t, nil))
	})
	if code, doc := exitOf(t, err); code != findings.ExitOK {
		t.Fatalf("exit %d, findings %+v; want 0", code, doc.Findings)
	}
	lines := strings.Split(out, "\n")
	want := []string{
		"dry run: no lab, container, twin directory or run is created",
		"snapshot_id " + fixtureSnapshotID + "  stored: " + filepath.Join(paths.Snapshots, fixtureSnapshotID+".json"),
		"bundle_id " + fixtureBundleID + "  stored: " + filepath.Join(paths.Bundles, fixtureBundleID),
		"nodes:",
	}
	for i, line := range want {
		if i >= len(lines) || lines[i] != line {
			t.Errorf("stdout line %d is not %q:\n%s", i+1, line, out)
		}
	}
	if strings.Contains(out, "\nread: ") {
		t.Errorf("a dry run from a snapshot printed a read: line:\n%s", out)
	}

	_, doc := exitOf(t, runCreate(context.Background(), testOptions(t, true), flags(), fixtureFile(t, nil)))
	if doc.SnapshotID != fixtureSnapshotID || doc.BundleID != fixtureBundleID || doc.DryRun == nil {
		t.Errorf("document names snapshot %q, bundle %q, dry_run %+v; want %s, %s and the report", doc.SnapshotID, doc.BundleID,
			doc.DryRun, fixtureSnapshotID, fixtureBundleID)
	}
	validateWithShow(t, currentContract, "018", doc)
}

// A dry run's filing writes no CTM beside the bundle (FR-008): the sidecar is retired. One an
// earlier build left, placed by hand before the filing, is neither read nor removed.
func TestNoSidecarIsWritten(t *testing.T) {
	paths := useStateRoot(t)
	useService(t, nil)
	dryRunEnv(t)
	useClab(t, "inspect-empty.json")
	left := []byte("{\"left\": \"by an earlier build\"}\n")
	sidecar := filepath.Join(paths.Bundles, fixtureBundleID+".ctm.json")
	if err := os.MkdirAll(paths.Bundles, 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(sidecar, left, 0o644); err != nil {
		t.Fatal(err)
	}
	err := runCreate(context.Background(), testOptions(t, true), &createFlags{snapshot: "snap.json", snapshotGiven: true, dryRun: true},
		fixtureFile(t, nil))
	if code, doc := exitOf(t, err); code != findings.ExitOK || doc.BundleID != fixtureBundleID {
		t.Fatalf("exit %d, document %+v; want 0 filing the fixture's bundle", code, doc)
	}

	if got, err := os.ReadFile(sidecar); err != nil || !bytes.Equal(got, left) {
		t.Errorf("the sidecar left by an earlier build reads %q (%v); want it untouched", got, err)
	}
	entries, err := os.ReadDir(paths.Bundles)
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range entries {
		if strings.HasSuffix(e.Name(), ".ctm.json") && e.Name() != filepath.Base(sidecar) {
			t.Errorf("the dry run's filing wrote %s beside the bundle", e.Name())
		}
	}
}

// A compile, or the bundle's filing, that refuses or fails once the snapshot is filed names
// the snapshot in the text answer as the document names it: its stored line, once, on
// stdout, naming the filed entry's path, and no bundle's; the snapshot stays filed, since its
// CTM validated and only the output was refused (US1 scenario 4; R-05; FR-010, FR-014).
func TestARefusedCompileNamesTheSnapshotInText(t *testing.T) {
	unknownPackage := func(c *ctm.CTM) { c.Devices[0].Platform.Package = "nosuch" }
	for _, c := range []struct {
		name string
		// edit is the stored snapshot's CTM's.
		edit func(*ctm.CTM)
		// before readies the state root: the bundle's entry, or the store's directory.
		before func(t *testing.T, paths lab.Paths)
		code   int
		rule   string
	}{
		{name: "the compile refused", edit: unknownPackage, code: findings.ExitRejected, rule: findings.RulePlatformUnsupported},
		// A corrupt entry under the id the fixture compiles to.
		{name: "the bundle's filing refused", before: func(t *testing.T, paths lab.Paths) {
			entry := filepath.Join(paths.Bundles, fixtureBundleID)
			if err := os.MkdirAll(entry, 0o755); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(filepath.Join(entry, "manifest.json"), []byte("{}"), 0o644); err != nil {
				t.Fatal(err)
			}
		}, code: findings.ExitRejected, rule: findings.RuleBundleIDMismatch},
		// The store's directory is a file, under which no bundle can be filed.
		{name: "the bundle's filing failed", before: func(t *testing.T, paths lab.Paths) {
			if err := os.WriteFile(paths.Bundles, nil, 0o644); err != nil {
				t.Fatal(err)
			}
		}, code: findings.ExitError, rule: findings.RuleOperationFailed},
	} {
		t.Run(c.name, func(t *testing.T) {
			paths := useStateRoot(t)
			useService(t, nil)
			if c.before != nil {
				c.before(t, paths)
			}
			snap := loadCTM(t, "three-node.json", "2026-10-27T09:00:00.000000Z")
			if c.edit != nil {
				c.edit(snap)
			}
			s, entry, _, err := takeSnapshot(context.Background(), paths, findings.StepCompile, snap, nil)
			if err != nil {
				t.Fatal(err)
			}

			out := captureStdout(t, func() {
				err = runCreate(context.Background(), testOptions(t, false), &createFlags{snapshot: s.ID, snapshotGiven: true}, nil)
			})
			code, doc := exitOf(t, err)
			if code != c.code || !hasRule(doc.Findings, c.rule) || doc.SnapshotID != s.ID || doc.BundleID != "" {
				t.Fatalf("exit %d, document %+v; want %d with %s, naming snapshot %s and no bundle", code, doc, c.code, c.rule, s.ID)
			}
			if want := snapshotStoredLine(s.ID, entry) + "\n"; out != want {
				t.Errorf("stdout:\n%s\nwant the snapshot's stored line alone:\n%s", out, want)
			}
			if _, err := os.Stat(entry); err != nil {
				t.Errorf("the snapshot the line names is not filed: %v", err)
			}
			if c.code == findings.ExitRejected {
				validateWithShow(t, currentContract, "018", doc)
			}
		})
	}
}

// A dry run whose host check cannot run has filed the snapshot and the bundle, so its answer
// names both, as a create's run that fails at the host check names them (FR-014, FR-010): in
// text, the snapshot's stored line, then the bundle's, alone on stdout, each naming the one
// entry its store holds; in --json, operation.failed at host_check, naming both ids. A host
// budget that is no number fails the host check before it looks at the host. twin
// provision's, which files no snapshot, prints and names its bundle alone.
func TestADryRunWhoseHostCheckCannotRunNamesWhatItFiled(t *testing.T) {
	t.Run("--snapshot <file> --dry-run", func(t *testing.T) {
		paths := useStateRoot(t)
		useService(t, nil)
		dryRunEnv(t)
		t.Setenv(lab.EnvHostMemoryMB, "lots")
		run := func(opts *options) error {
			return runCreate(context.Background(), opts, &createFlags{snapshot: "snap.json", snapshotGiven: true, dryRun: true},
				fixtureFile(t, nil))
		}

		var err error
		out := captureStdout(t, func() { err = run(testOptions(t, false)) })
		if code, doc := exitOf(t, err); code != findings.ExitError {
			t.Fatalf("exit %d, findings %+v; want 2", code, doc.Findings)
		}
		snapshotID := strings.TrimSuffix(onlyEntry(t, paths.Snapshots), ".json")
		bundleID := onlyEntry(t, paths.Bundles)
		want := snapshotStoredLine(snapshotID, filepath.Join(paths.Snapshots, snapshotID+".json")) + "\n" +
			bundleStoredLine(bundleID, filepath.Join(paths.Bundles, bundleID)) + "\n"
		if out != want {
			t.Errorf("stdout:\n%s\nwant both stored lines alone:\n%s", out, want)
		}

		code, doc := exitOf(t, run(testOptions(t, true)))
		last := doc.Findings[len(doc.Findings)-1]
		if code != findings.ExitError || last.Rule != findings.RuleOperationFailed || last.Step != findings.StepHostCheck ||
			len(doc.Findings) != 1 {
			t.Fatalf("exit %d, findings %+v; want 2, operation.failed at host_check alone", code, doc.Findings)
		}
		if doc.SnapshotID != snapshotID || doc.BundleID != bundleID {
			t.Errorf("document names snapshot %q and bundle %q; want %s and %s", doc.SnapshotID, doc.BundleID, snapshotID, bundleID)
		}
		validateWithShow(t, currentContract, "018", doc)
	})

	t.Run("twin provision --dry-run", func(t *testing.T) {
		paths := useStateRoot(t)
		useService(t, nil)
		dryRunEnv(t)
		t.Setenv(lab.EnvHostMemoryMB, "lots")
		dir := copyGoldenBundle(t, fixtureBundleID)
		report := func(opts *options) error {
			return dryRunReport(context.Background(), opts, findings.OpTwinProvision, &findings.Subject{Bundle: "bundle"},
				shippedPackages(t), paths, nil, dir, fixtureBundleID, nil)
		}

		var err error
		out := captureStdout(t, func() { err = report(testOptions(t, false)) })
		if code, _ := exitOf(t, err); code != findings.ExitError || out != bundleStoredLine(fixtureBundleID, dir)+"\n" {
			t.Errorf("exit %d, stdout:\n%s\nwant 2 and the bundle's stored line alone", code, out)
		}
		code, doc := exitOf(t, report(testOptions(t, true)))
		if code != findings.ExitError || doc.BundleID != fixtureBundleID || doc.SnapshotID != "" || len(doc.Findings) != 1 {
			t.Errorf("exit %d, document %+v; want 2 naming bundle %s, no snapshot, and the failure alone", code, doc, fixtureBundleID)
		}
		validateWithShow(t, currentContract, "018", doc)
	})
}

// onlyEntry is the name of the one entry dir holds.
func onlyEntry(t *testing.T, dir string) string {
	t.Helper()
	entries, err := os.ReadDir(dir)
	if err != nil || len(entries) != 1 {
		t.Fatalf("%s holds %v (%v); want one entry", dir, entries, err)
	}
	return entries[0].Name()
}

// hasRule is whether list holds a finding under rule.
func hasRule(list findings.List, rule string) bool {
	return slices.ContainsFunc(list, func(f findings.Finding) bool { return f.Rule == rule })
}

// A create detached from a snapshot (020; US4 scenario 1) files the snapshot and the bundle
// and starts the run with them, as a followed create does, then answers at the run: the
// stored lines are printed, the document names the snapshot, the bundle and the run, and its
// text the run.detached line the CLI prints.
func TestADetachedCreateNamesWhatItFiled(t *testing.T) {
	paths := useStateRoot(t)
	_, frames, svc := detachedAnswer(t, findings.OpTwinCreate)
	out, doc := detachedOf(t, frames)
	for _, line := range []string{
		"snapshot_id " + fixtureSnapshotID + "  stored: " + filepath.Join(paths.Snapshots, fixtureSnapshotID+".json") + "\n",
		"bundle_id " + fixtureBundleID + "  stored: " + filepath.Join(paths.Bundles, fixtureBundleID) + "\n",
	} {
		if !strings.Contains(out, line) {
			t.Errorf("printed\n%s\nwant the line %q", out, line)
		}
	}
	if doc.SnapshotID != fixtureSnapshotID || doc.BundleID != fixtureBundleID {
		t.Errorf("document names snapshot %q and bundle %q, want %s and %s", doc.SnapshotID, doc.BundleID, fixtureSnapshotID, fixtureBundleID)
	}
	if text := frames[len(frames)-1].Text; !strings.Contains(text, findings.RuleRunDetached) ||
		!strings.Contains(text, "started; read it with fylgja run read") {
		t.Errorf("the document's text is\n%s\nwant its run.detached line", text)
	}
	if len(svc.provisioned) != 1 || svc.provisioned[0].SnapshotID != fixtureSnapshotID || svc.provisioned[0].BundleID != fixtureBundleID {
		t.Errorf("started %+v, want one run of snapshot %s and bundle %s", svc.provisioned, fixtureSnapshotID, fixtureBundleID)
	}
}

// detach beside dry_run is run.flags.conflict before any of the create's guards (020).
func TestACreateRefusesDetachBesideDryRun(t *testing.T) {
	wantDetachConflict(t, findings.OpTwinCreate)
}
