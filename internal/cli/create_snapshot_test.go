package cli

import (
	"bytes"
	"context"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
)

// 018, US1: every create the server starts is compiled first. The server resolves and files
// the snapshot, compiles and files the bundle, then starts the provision run with both ids,
// so the run begins at the host check and the worker reads nothing for a create. From 020 a
// create builds from a snapshot alone (D-065): the take is the orchestrator's adapter's.

// startWatcher is a fakeService that notes, as the run is started, which of the files its
// input names the state root already holds.
type startWatcher struct {
	*fakeService
	paths   lab.Paths
	atStart []string
}

func (s *startWatcher) StartProvision(ctx context.Context, in provision.ProvisionInput) (string, error) {
	for _, p := range []string{filepath.Join(s.paths.Snapshots, in.SnapshotID+".json"), in.BundlePath} {
		if _, err := os.Stat(p); err == nil {
			s.atStart = append(s.atStart, p)
		}
	}
	return s.fakeService.StartProvision(ctx, in)
}

// filedSnapshots is what snapshots/ holds.
func filedSnapshots(t *testing.T, paths lab.Paths) []string {
	t.Helper()
	entries, err := os.ReadDir(paths.Snapshots)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		t.Fatal(err)
	}
	var names []string
	for _, e := range entries {
		names = append(names, e.Name())
	}
	return names
}

// US1 scenario 1 and SC-001's command half: a create from a snapshot has the snapshot and its
// bundle filed before the run's start, and the input the service is started with carries both
// ids and a BundleID, so the run reads nothing; the two stored lines print before the run's.
func TestCreateFilesTheBundleBeforeTheRun(t *testing.T) {
	paths := useFixtureSnapshot(t)
	useInterrupts(t)
	svc := &startWatcher{fakeService: &fakeService{runID: "run-1", result: readyResult()}, paths: paths}
	useService(t, svc)

	var err error
	out := captureStdout(t, func() {
		err = runCreate(context.Background(), &options{}, &createFlags{snapshot: headSnapshotID})
	})
	if code, doc := exitOf(t, err); code != findings.ExitOK {
		t.Fatalf("exit %d, findings %+v; want 0", code, doc.Findings)
	}
	if want := strings.Join(append(storedLines(paths, headSnapshotID, headBundleID), "run fylgja-provision run-1"), "\n") + "\n"; !strings.HasPrefix(out, want) {
		t.Errorf("stdout:\n%s\nwant it to begin:\n%s", out, want)
	}
	if len(svc.started) != 1 {
		t.Fatalf("started %+v, want one run", svc.started)
	}
	in := svc.started[0]
	if in.Source != wire.SourceSnapshot || in.Branch != "fylgja-fixture" || in.SnapshotID != headSnapshotID ||
		in.BundleID != headBundleID || in.BundlePath != filepath.Join(paths.Bundles, headBundleID) || in.ObservedAt == "" {
		t.Errorf("the run was started with %+v; want the snapshot %s and its bundle %s, compiled", in, headSnapshotID, headBundleID)
	}
	if len(svc.atStart) != 2 {
		t.Errorf("at the run's start the state root held %v; want the snapshot and the bundle both filed", svc.atStart)
	}
	if got := filedSnapshots(t, paths); len(got) != 1 || got[0] != headSnapshotID+".json" {
		t.Errorf("snapshots/ holds %v, want the one snapshot", got)
	}
	if got := storedBundles(t, paths.Bundles); len(got) != 1 || got[0] != headBundleID {
		t.Errorf("bundles/ holds %v, want the one bundle", got)
	}

	_, doc := exitOf(t, runCreate(context.Background(), &options{asJSON: true}, &createFlags{snapshot: headSnapshotID}))
	if doc.SnapshotID != headSnapshotID {
		t.Errorf("the document names snapshot %q, want %s", doc.SnapshotID, headSnapshotID)
	}
	validateM10Document(t, doc)
}

// FR-010 and FR-014: a create from a stored snapshot, its dry run and a create from a snapshot
// file, each refused at compile once the snapshot is filed, name it in the text answer as the
// --json document names it: the snapshot's stored line, once and alone on stdout, naming the
// filed entry's path, with the refusal on stderr; no run is started. The stored snapshot's
// filing meets a corrupt entry under the id it compiles to (bundle.id.mismatch); the file's
// CTM names a package this server lacks (platform.unsupported). A snapshot refused at
// resolve, which files nothing, prints nothing on stdout.
func TestARefusedCompileNamesTheSnapshotInText(t *testing.T) {
	corruptEntry := func(t *testing.T, paths lab.Paths) {
		entry := filepath.Join(paths.Bundles, headBundleID)
		if err := os.MkdirAll(entry, 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(filepath.Join(entry, "manifest.json"), []byte("{}"), 0o644); err != nil {
			t.Fatal(err)
		}
	}
	unknownPackage := func(d map[string]any) {
		delete(d, "snapshot_id")
		device := d["ctm"].(map[string]any)["devices"].([]any)[0].(map[string]any)
		device["platform"].(map[string]any)["package"] = "nosuch"
	}
	for _, c := range []struct {
		name string
		// args readies the state root and returns the arguments after twin create.
		args func(t *testing.T, paths lab.Paths) []string
		rule string
		step string
	}{
		{"--snapshot <id>", func(t *testing.T, paths lab.Paths) []string {
			corruptEntry(t, paths)
			return []string{"--snapshot", headSnapshotID}
		}, findings.RuleBundleIDMismatch, findings.StepCompile},
		{"--snapshot <id> --dry-run", func(t *testing.T, paths lab.Paths) []string {
			corruptEntry(t, paths)
			return []string{"--snapshot", headSnapshotID, "--dry-run"}
		}, findings.RuleBundleIDMismatch, findings.StepCompile},
		{"--snapshot <file>", func(t *testing.T, _ lab.Paths) []string {
			return []string{"--snapshot", snapshotFile(t, unknownPackage)}
		}, findings.RulePlatformUnsupported, findings.StepCompile},
		{"--snapshot <unknown id>", func(*testing.T, lab.Paths) []string {
			return []string{"--snapshot", fixtureSnapshotID}
		}, findings.RuleSnapshotUnknown, findings.StepResolve},
	} {
		t.Run(c.name, func(t *testing.T) {
			paths := useFixtureSnapshot(t)
			dials := countDials(t)
			args := append([]string{"twin", "create"}, c.args(t, paths)...)

			code, stdout, stderr := runRoot(t, args...)
			jsonCode, doc := executeTwin(t, args...)
			refused := slices.ContainsFunc(doc.Findings, func(f findings.Finding) bool { return f.Rule == c.rule && f.Step == c.step })
			if code != findings.ExitRejected || jsonCode != code || !refused || doc.BundleID != "" {
				t.Fatalf("exit %d (--json %d), document %+v; want 1 with %s at %s, naming no bundle", code, jsonCode, doc, c.rule, c.step)
			}
			if !strings.Contains(stderr, "rejection "+c.rule) {
				t.Errorf("stderr:\n%s\nwant the %s refusal", stderr, c.rule)
			}
			if n := dials.Load(); n != 0 {
				t.Errorf("the workflow service was dialled %d times", n)
			}
			if c.step == findings.StepResolve {
				if stdout != "" || doc.SnapshotID != "" {
					t.Errorf("stdout %q, snapshot %q; want nothing printed and no snapshot named", stdout, doc.SnapshotID)
				}
				return
			}
			if got := filedSnapshots(t, paths); !slices.Contains(got, doc.SnapshotID+".json") {
				t.Fatalf("snapshots/ holds %v; want the snapshot the document names, %s", got, doc.SnapshotID)
			}
			want := "snapshot_id " + doc.SnapshotID + "  stored: " + filepath.Join(paths.Snapshots, doc.SnapshotID+".json") + "\n"
			if stdout != want {
				t.Errorf("stdout:\n%s\nwant the snapshot's stored line alone:\n%s", stdout, want)
			}
			validateM10Document(t, doc)
		})
	}
}

// FR-014 and FR-010: a create's dry run whose host check cannot run has filed the snapshot
// and the bundle, and its answer names both, as a run that fails at the host check does:
// their stored lines alone on stdout, in the success's order, with the failure on stderr,
// and both ids on the --json document. A host budget that is no number fails the host check
// before it looks at the host; no workflow service is dialled.
func TestADryRunWhoseHostCheckCannotRunNamesWhatItFiled(t *testing.T) {
	paths := useFixtureSnapshot(t)
	dials := countDials(t)
	dryRunEnv(t)
	t.Setenv(lab.EnvHostMemoryMB, "lots")
	args := []string{"twin", "create", "--snapshot", headSnapshotID, "--dry-run"}

	code, stdout, stderr := runRoot(t, args...)
	jsonCode, doc := executeTwin(t, args...)
	failed := slices.ContainsFunc(doc.Findings, func(f findings.Finding) bool {
		return f.Rule == findings.RuleOperationFailed && f.Step == findings.StepHostCheck
	})
	if code != findings.ExitError || jsonCode != code || !failed {
		t.Fatalf("exit %d (--json %d), findings %+v; want 2 with operation.failed at host_check", code, jsonCode, doc.Findings)
	}
	if !strings.Contains(stderr, "rejection "+findings.RuleOperationFailed) {
		t.Errorf("stderr:\n%s\nwant the host check's failure", stderr)
	}
	if want := lines(storedLines(paths, headSnapshotID, headBundleID)...); stdout != want {
		t.Errorf("stdout:\n%s\nwant both stored lines alone:\n%s", stdout, want)
	}
	if got := filedSnapshots(t, paths); len(got) != 1 || got[0] != headSnapshotID+".json" {
		t.Errorf("snapshots/ holds %v; want %s alone", got, headSnapshotID)
	}
	if _, err := os.Stat(filepath.Join(paths.Bundles, headBundleID)); err != nil {
		t.Errorf("the bundle the line names is not filed: %v", err)
	}
	if doc.SnapshotID != headSnapshotID || doc.BundleID != headBundleID {
		t.Errorf("document names snapshot %q and bundle %q; want %s and %s", doc.SnapshotID, doc.BundleID, headSnapshotID, headBundleID)
	}
	if n := dials.Load(); n != 0 {
		t.Errorf("the workflow service was dialled %d times", n)
	}
	validateM10Document(t, doc)
}

// The same snapshot created from twice is one entry: the second create finds it and leaves it
// as it was, and each run is started with its observed_at, the first take's.
func TestCreateTwiceFilesOneSnapshot(t *testing.T) {
	paths := useFixtureSnapshot(t)
	useInterrupts(t)
	svc := &fakeService{runID: "run-1", result: readyResult()}
	useService(t, svc)
	entry := filepath.Join(paths.Snapshots, headSnapshotID+".json")

	var first []byte
	for i := range 2 {
		if code, doc := exitOf(t, runCreate(context.Background(), &options{asJSON: true}, &createFlags{snapshot: headSnapshotID})); code != findings.ExitOK {
			t.Fatalf("create %d: exit %d, findings %+v", i+1, code, doc.Findings)
		}
		b, err := os.ReadFile(entry)
		if err != nil {
			t.Fatal(err)
		}
		if i == 0 {
			first = b
		} else if !bytes.Equal(b, first) {
			t.Errorf("the second create rewrote the entry:\n%s", b)
		}
	}
	if got := filedSnapshots(t, paths); len(got) != 1 {
		t.Errorf("snapshots/ holds %v, want the one entry", got)
	}
	if len(svc.started) != 2 || svc.started[0].SnapshotID != headSnapshotID || svc.started[1].SnapshotID != headSnapshotID ||
		svc.started[1].ObservedAt != svc.started[0].ObservedAt || svc.started[0].ObservedAt == "" {
		t.Errorf("started %+v; want two runs of snapshot %s, each with its observed_at", svc.started, headSnapshotID)
	}
}
