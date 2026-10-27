package server

import (
	"bytes"
	"context"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// fakeRead is a create's read over no Infrahub: the fixture CTM name as a read returns
// it, observed when the create says, edited by edit when given, with list beside it.
// Every call is counted in reads.
func fakeRead(t *testing.T, name string, edit func(*ctm.CTM), reads *int) readFunc {
	return func(_ context.Context, _, _, _ string, _ *psp.Registry, observedAt string) (*ctm.CTM, findings.List, error) {
		*reads++
		c := loadCTM(t, name, observedAt)
		if edit != nil {
			edit(c)
		}
		return c, nil, nil
	}
}

// shippedPackages is the server's registry with no override.
func shippedPackages(t *testing.T) *psp.Registry {
	t.Helper()
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	return reg
}

// The create's dry run takes the snapshot on the create's own path, then reports: the
// snapshot's stored line above the bundle's, both after the read line, and the document
// names both, valid against the current contract with snapshot_id present (T026; R-09).
func TestCreateDryRunTakesTheSnapshot(t *testing.T) {
	paths := useStateRoot(t)
	useService(t, nil)
	dryRunEnv(t)
	useClab(t, "inspect-empty.json")
	reg := shippedPackages(t)
	follow := findings.DryRunFollow{Reason: findings.FollowReasonPinned}
	reads := 0
	read := fakeRead(t, "three-node.json", nil, &reads)

	var err error
	subject := &findings.Subject{Branch: "fylgja-fixture", At: "2026-09-08T12:00:00Z"}
	out := captureStdout(t, func() {
		err = runCreateDryRun(context.Background(), testOptions(t, false), findings.OpTwinCreate, subject, read,
			subject.Branch, subject.At, "tag:fylgja", reg, follow)
	})
	if code, doc := exitOf(t, err); code != findings.ExitOK {
		t.Fatalf("exit %d, findings %+v; want 0", code, doc.Findings)
	}
	lines := strings.Split(out, "\n")
	want := []string{
		"dry run: no lab, container, twin directory or run is created",
		"read: 3 devices (nokia_srlinux 3), 9 interfaces, 3 links, 3 artifacts, 0 lossy mappings, 0 shared ports " +
			"(branch fylgja-fixture, at 2026-09-08T12:00:00Z, schema fixture)",
		"snapshot_id " + fixtureSnapshotID + "  stored: " + filepath.Join(paths.Snapshots, fixtureSnapshotID+".json"),
		"bundle_id " + fixtureBundleID + "  stored: " + filepath.Join(paths.Bundles, fixtureBundleID),
		"nodes:",
	}
	for i, line := range want {
		if i >= len(lines) || lines[i] != line {
			t.Errorf("stdout line %d is not %q:\n%s", i+1, line, out)
		}
	}

	_, doc := exitOf(t, runCreateDryRun(context.Background(), testOptions(t, true), findings.OpTwinCreate, subject, read,
		subject.Branch, subject.At, "tag:fylgja", reg, follow))
	if doc.SnapshotID != fixtureSnapshotID || doc.BundleID != fixtureBundleID || doc.DryRun == nil {
		t.Errorf("document names snapshot %q, bundle %q, dry_run %+v; want %s, %s and the report", doc.SnapshotID, doc.BundleID,
			doc.DryRun, fixtureSnapshotID, fixtureBundleID)
	}
	validateWithShow(t, currentContract, "018", doc)
}

// A dry run's filing writes no CTM beside the bundle (FR-008): the sidecar is retired. One an
// earlier build left, placed by hand before the filing, is neither read nor removed. The
// Compile activity's half is internal/provision's test of this name.
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
	reads := 0
	subject := &findings.Subject{Branch: "fylgja-fixture", At: "2026-09-08T12:00:00Z"}
	err := runCreateDryRun(context.Background(), testOptions(t, true), findings.OpTwinCreate, subject,
		fakeRead(t, "three-node.json", nil, &reads), subject.Branch, subject.At, "tag:fylgja", shippedPackages(t),
		findings.DryRunFollow{Reason: findings.FollowReasonPinned})
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

// A compile refused after a clean read leaves the snapshot filed and names it in the
// document, since the input validated and only the output was refused; no bundle is filed
// (US1 scenario 4; R-05; FR-010). The read's CTM names a package this server lacks.
func TestRefusedCompileKeepsTheSnapshot(t *testing.T) {
	paths := useStateRoot(t)
	useService(t, nil)
	reads := 0
	read := fakeRead(t, "three-node.json", func(c *ctm.CTM) { c.Devices[0].Platform.Package = "nosuch" }, &reads)

	_, err := readTakeCompile(context.Background(), testOptions(t, true), findings.OpTwinCreate, &findings.Subject{Branch: "b"},
		read, "b", "", "tag:fylgja", shippedPackages(t))
	code, doc := exitOf(t, err)
	if code != findings.ExitRejected || len(doc.Findings) == 0 || doc.Findings[0].Step != findings.StepCompile || doc.BundleID != "" {
		t.Fatalf("exit %d, document %+v; want 1, refused at compile, naming no bundle", code, doc)
	}
	if doc.SnapshotID == "" {
		t.Fatal("the refused compile's document names no snapshot")
	}
	if _, err := os.Stat(filepath.Join(paths.Snapshots, doc.SnapshotID+".json")); err != nil {
		t.Errorf("the snapshot the document names is not filed: %v", err)
	}
	if entries, _ := os.ReadDir(paths.Bundles); len(entries) != 0 {
		t.Errorf("bundles/ holds %v after a refused compile", entries)
	}
	validateWithShow(t, currentContract, "018", doc)
}

// A refused read files nothing and names no snapshot; a read that cannot run is
// operation.failed at read, at once, naming the branch, with nothing filed (FR-010).
func TestARefusedOrFailedReadFilesNothing(t *testing.T) {
	refused := findings.List{{Severity: findings.Rejection, Rule: findings.RuleScopeEmpty, Object: "tag:fylgja",
		Message: "scope tag:fylgja selects no device on branch b"}}
	for _, c := range []struct {
		name string
		read readFunc
		code int
		rule string
	}{
		{"refused", func(context.Context, string, string, string, *psp.Registry, string) (*ctm.CTM, findings.List, error) {
			return nil, refused, nil
		}, findings.ExitRejected, findings.RuleScopeEmpty},
		{"cannot run", func(context.Context, string, string, string, *psp.Registry, string) (*ctm.CTM, findings.List, error) {
			return nil, nil, errors.New(`reading the schema (branch b): dial tcp 127.0.0.1:1: connect: connection refused`)
		}, findings.ExitError, findings.RuleOperationFailed},
	} {
		t.Run(c.name, func(t *testing.T) {
			paths := useStateRoot(t)
			useService(t, nil)
			_, err := readTakeCompile(context.Background(), testOptions(t, true), findings.OpTwinCreate, &findings.Subject{Branch: "b"},
				c.read, "b", "", "tag:fylgja", shippedPackages(t))
			code, doc := exitOf(t, err)
			if code != c.code || len(doc.Findings) != 1 || doc.Findings[0].Rule != c.rule || doc.Findings[0].Step != findings.StepRead ||
				doc.SnapshotID != "" || doc.BundleID != "" {
				t.Errorf("exit %d, document %+v; want %d with %s at read, naming nothing", code, doc, c.code, c.rule)
			}
			if c.rule == findings.RuleOperationFailed && doc.Findings[0].Object != "branch b" {
				t.Errorf("finding %+v; want it naming branch b", doc.Findings[0])
			}
			for _, dir := range []string{paths.Snapshots, paths.Bundles} {
				if _, err := os.Stat(dir); !os.IsNotExist(err) {
					t.Errorf("%s exists after a read that did not complete (%v)", dir, err)
				}
			}
		})
	}
}

// A create whose take meets a corrupt entry under its snapshot's id is refused
// snapshot.id.mismatch at compile, as a corrupt bundle entry is refused bundle.id.mismatch
// there, naming the store path; it compiles nothing, files no bundle and names no snapshot.
func TestACreateOverACorruptSnapshotEntry(t *testing.T) {
	paths := useStateRoot(t)
	useService(t, nil)
	other, _, _, err := takeSnapshot(context.Background(), paths, findings.StepCompile, loadCTM(t, "lossy.json", "2026-10-27T09:00:00.000000Z"))
	if err != nil {
		t.Fatal(err)
	}
	entry := filepath.Join(paths.Snapshots, fixtureSnapshotID+".json")
	if err := os.Rename(filepath.Join(paths.Snapshots, other.ID+".json"), entry); err != nil {
		t.Fatal(err)
	}
	reads := 0
	_, err = readTakeCompile(context.Background(), testOptions(t, true), findings.OpTwinCreate, &findings.Subject{Branch: "b"},
		fakeRead(t, "three-node.json", nil, &reads), "b", "", "tag:fylgja", shippedPackages(t))
	code, doc := exitOf(t, err)
	if code != findings.ExitRejected || len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleSnapshotIDMismatch ||
		doc.Findings[0].Step != findings.StepCompile || doc.Findings[0].Object != entry || doc.SnapshotID != "" || doc.BundleID != "" {
		t.Errorf("exit %d, document %+v; want 1 with %s at compile naming %s, and no ids", code, doc, findings.RuleSnapshotIDMismatch, entry)
	}
	if _, err := os.Stat(paths.Bundles); !os.IsNotExist(err) {
		t.Errorf("bundles/ exists after a refused take (%v)", err)
	}
	validateWithShow(t, currentContract, "018", doc)
}
