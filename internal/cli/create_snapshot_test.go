package cli

import (
	"bytes"
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
)

// 018, US1: every create the server starts is compiled first. The server reads, takes and
// files the snapshot, compiles and files the bundle, then starts the provision run with both
// ids, so the run begins at the host check and the worker reads nothing for a create.

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

// US1 scenario 1 and SC-001's command half: a --branch create files one snapshot and one
// bundle before the run's start, and the input the service is started with carries both ids
// and a BundleID, so the run reads nothing; the two stored lines print before the run's.
func TestCreateTakesTheSnapshotBeforeTheRun(t *testing.T) {
	paths := useFixtureRead(t)
	useInterrupts(t)
	svc := &startWatcher{fakeService: &fakeService{runID: "run-1", result: readyResult()}, paths: paths}
	useService(t, svc)

	var err error
	out := captureStdout(t, func() {
		err = runCreate(context.Background(), &options{}, &createFlags{branch: "fylgja-fixture", noFollow: true})
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
	if in.Source != wire.SourceIntent || in.Branch != "fylgja-fixture" || in.SnapshotID != headSnapshotID ||
		in.BundleID != headBundleID || in.BundlePath != filepath.Join(paths.Bundles, headBundleID) || in.ObservedAt == "" {
		t.Errorf("the run was started with %+v; want the intent's snapshot %s and its bundle %s, compiled", in, headSnapshotID, headBundleID)
	}
	if len(svc.atStart) != 2 {
		t.Errorf("at the run's start the state root held %v; want the snapshot and the bundle both filed", svc.atStart)
	}
	if got := filedSnapshots(t, paths); len(got) != 1 || got[0] != headSnapshotID+".json" {
		t.Errorf("snapshots/ holds %v, want the one take", got)
	}
	if got := storedBundles(t, paths.Bundles); len(got) != 1 || got[0] != headBundleID {
		t.Errorf("bundles/ holds %v, want the one bundle", got)
	}

	_, doc := exitOf(t, runCreate(context.Background(), &options{asJSON: true}, &createFlags{branch: "fylgja-fixture", noFollow: true}))
	if doc.SnapshotID != headSnapshotID {
		t.Errorf("the document names snapshot %q, want %s", doc.SnapshotID, headSnapshotID)
	}
	validateM10Document(t, doc)
}

// US1 scenario 3: a create from a stage takes the stage's pinned read, and its run records
// the stage, the snapshot and the bundle, the fixture's own at the fixture's at.
func TestCreateFromAStageTakesItsPinnedRead(t *testing.T) {
	paths := useStateRoot(t)
	dryRunEnv(t)
	useClab(t, "inspect-empty.json")
	useInterrupts(t)
	svc := &fakeService{runID: "run-1", result: readyResult()}
	useService(t, svc)
	f := demoInfrahub(t)
	f.start()

	code, doc := executeTwin(t, "twin", "create", "--stage", "fylgja-fixture/sealed")
	if code != findings.ExitOK || len(svc.started) != 1 {
		t.Fatalf("exit %d, started %+v, findings %+v; want 0 and one run", code, svc.started, doc.Findings)
	}
	readsAtAlone(t, "the stage's read", f, fixtureAt)
	in := svc.started[0]
	if in.SnapshotID != fixtureSnapshotID || in.BundleID != fixtureBundleID || in.Stage == nil || in.Stage.Label != "sealed" {
		t.Fatalf("the run was started with %+v; want the fixture's snapshot and bundle and the stage", in)
	}

	_, record := provisionOnSuite(t, paths, in)
	validateTwinJSON(t, record)
	w := decodeRecord(t, record)
	if w.SnapshotID == nil || *w.SnapshotID != fixtureSnapshotID || w.BundleID != fixtureBundleID || w.Stage == nil ||
		w.Stage.Label != "sealed" || w.Provenance.At != fixtureAt {
		t.Errorf("the run recorded\n%s\nwant the stage sealed, snapshot %s and bundle %s at %s", record, fixtureSnapshotID,
			fixtureBundleID, fixtureAt)
	}
}

// US1 scenario 5 and FR-010: a read the server refuses ends the create rejected at read,
// starts no run and files nothing: no snapshot, no bundle.
func TestRefusedReadStartsNothingAndFilesNothing(t *testing.T) {
	paths := useStateRoot(t)
	useService(t, nil)
	f := newFakeInfrahub(t)
	f.untagged = map[string]bool{"fylgja-fixture": true}
	f.start()

	code, doc := exitOf(t, runCreate(context.Background(), &options{asJSON: true}, &createFlags{branch: "fylgja-fixture"}))
	if code != findings.ExitRejected || len(doc.Findings) == 0 || doc.Findings[0].Rule != findings.RuleScopeEmpty ||
		doc.Findings[0].Step != findings.StepRead || doc.SnapshotID != "" || doc.BundleID != "" {
		t.Errorf("exit %d, document %+v; want 1 with %s at read, naming no snapshot and no bundle", code, doc, findings.RuleScopeEmpty)
	}
	if got := filedSnapshots(t, paths); len(got) != 0 {
		t.Errorf("snapshots/ holds %v after a refused read", got)
	}
	if got := storedBundles(t, paths.Bundles); len(got) != 0 {
		t.Errorf("bundles/ holds %v after a refused read", got)
	}
	validateM10Document(t, doc)
}

// FR-010: an Infrahub that cannot be reached fails the create at read at once, exit 2,
// naming the branch; no workflow service is dialled and nothing is filed. The worker's
// retries no longer stand between a create and its read.
func TestUnreachableInfrahubFailsTheCreateAtRead(t *testing.T) {
	paths := useStateRoot(t)
	useService(t, nil)
	t.Setenv(intent.EnvAddress, unreachable)
	t.Setenv(intent.EnvToken, "any-token")

	code, doc := exitOf(t, runCreate(context.Background(), &options{asJSON: true}, &createFlags{branch: "fylgja-fixture"}))
	if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleOperationFailed ||
		doc.Findings[0].Step != findings.StepRead || doc.Findings[0].Object != "branch fylgja-fixture" {
		t.Errorf("exit %d, findings %+v; want 2 with %s at read naming the branch", code, doc.Findings, findings.RuleOperationFailed)
	}
	if got := filedSnapshots(t, paths); len(got) != 0 {
		t.Errorf("snapshots/ holds %v after a read that could not run", got)
	}
	mustCarryNoToken(t, "the unreachable read", doc)
	validateM10Document(t, doc)
}

// The same intent created twice is one snapshot: the second take finds the first's entry
// and leaves it as it was, its observed_at the first take's, while each run is started with
// its own read's time.
func TestCreateTwiceFilesOneSnapshot(t *testing.T) {
	paths := useFixtureRead(t)
	useInterrupts(t)
	svc := &fakeService{runID: "run-1", result: readyResult()}
	useService(t, svc)
	entry := filepath.Join(paths.Snapshots, headSnapshotID+".json")

	var first []byte
	for i := range 2 {
		if code, doc := exitOf(t, runCreate(context.Background(), &options{asJSON: true}, &createFlags{branch: "fylgja-fixture", noFollow: true})); code != findings.ExitOK {
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
		svc.started[1].ObservedAt < svc.started[0].ObservedAt {
		t.Errorf("started %+v; want two runs of snapshot %s, each with its own read's time", svc.started, headSnapshotID)
	}
}
