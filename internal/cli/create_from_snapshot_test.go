package cli

import (
	"bytes"
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
	// Named apart from this package's test helper snapshot (refusal_test.go).
	snap "github.com/happypathnetworking/fylgja/internal/snapshot"
)

// 018, US3: twin create --snapshot <id|file> builds a twin from a snapshot alone. The server
// fetches a stored one or files the one sent, compiles it and starts the provision run with
// both ids; no request reaches Infrahub, and the twin is frozen by rule.

// fixtureObservedAt is the wrapped fixture's observed_at: its CTM's, the first take's.
const fixtureObservedAt = "2026-09-08T12:00:00.000000Z"

// storeFixtureSnapshot files testdata/snapshot/three-node.json in the state root's store,
// as an earlier create on this server would have, and returns it.
func storeFixtureSnapshot(t *testing.T, paths lab.Paths) *snap.Snapshot {
	t.Helper()
	s, err := snap.Load(repoPath("testdata", "snapshot", "three-node.json"))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := snap.NewDirStore(paths.Snapshots).Put(context.Background(), s); err != nil {
		t.Fatal(err)
	}
	return s
}

// snapshotFile writes testdata/snapshot/three-node.json, edited by edit, to a file of the
// test's own, and returns its path: the file an operator holds.
func snapshotFile(t *testing.T, edit func(doc map[string]any)) string {
	t.Helper()
	raw, err := os.ReadFile(repoPath("testdata", "snapshot", "three-node.json"))
	if err != nil {
		t.Fatal(err)
	}
	var doc map[string]any
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}
	if edit != nil {
		edit(doc)
	}
	b, err := json.MarshalIndent(doc, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(t.TempDir(), "snap.json")
	if err := os.WriteFile(path, b, 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}

// wantSnapshotRun holds in to the input a create from the fixture's snapshot starts its run with: the
// envelope's branch, at and scope, the stored document's observed_at and both ids.
func wantSnapshotRun(t *testing.T, paths lab.Paths, in provision.ProvisionInput, observedAt string) {
	t.Helper()
	if in.Source != wire.SourceSnapshot || in.SnapshotID != fixtureSnapshotID || in.BundleID != fixtureBundleID ||
		in.BundlePath != filepath.Join(paths.Bundles, fixtureBundleID) || in.Branch != "fylgja-fixture" || in.At != fixtureAt ||
		in.Scope != "tag:fylgja" || in.ObservedAt != observedAt {
		t.Errorf("the run was started with %+v; want source snapshot, snapshot %s, bundle %s, branch fylgja-fixture at %s, "+
			"scope tag:fylgja, observed at %s", in, fixtureSnapshotID, fixtureBundleID, fixtureAt, observedAt)
	}
}

// US3 scenario 1 and FR-015: a stored snapshot's id builds the twin with no read. The server
// compiles the stored snapshot, files the bundle and starts the provision run with both ids,
// printing the two stored lines before it, and the run's record names the snapshot, its
// source snapshot, at the envelope's at.
func TestCreateFromAStoredSnapshot(t *testing.T) {
	paths := useStateRoot(t)
	useInterrupts(t)
	svc := &fakeService{runID: "run-1", result: readyResult()}
	useService(t, svc)
	storeFixtureSnapshot(t, paths)

	var err error
	out := captureStdout(t, func() {
		err = runCreate(context.Background(), &options{}, &createFlags{snapshot: fixtureSnapshotID, snapshotGiven: true})
	})
	if code, doc := exitOf(t, err); code != findings.ExitOK {
		t.Fatalf("exit %d, findings %+v; want 0", code, doc.Findings)
	}
	if want := strings.Join(append(storedLines(paths, fixtureSnapshotID, fixtureBundleID), "run fylgja-provision run-1"), "\n") + "\n"; !strings.HasPrefix(out, want) {
		t.Errorf("stdout:\n%s\nwant it to begin:\n%s", out, want)
	}

	code, doc := executeTwin(t, "twin", "create", "--snapshot", fixtureSnapshotID)
	if code != findings.ExitOK || doc.SnapshotID != fixtureSnapshotID || doc.Subject.Snapshot != fixtureSnapshotID ||
		doc.Subject.Branch != "fylgja-fixture" || doc.Subject.At != fixtureAt {
		t.Errorf("exit %d, document %+v (subject %+v); want 0 naming snapshot %s, as given, of fylgja-fixture at %s", code, doc,
			doc.Subject, fixtureSnapshotID, fixtureAt)
	}
	validateM10Document(t, doc)
	if len(svc.started) != 2 {
		t.Fatalf("started %+v, want two runs", svc.started)
	}
	// No Follow: the run makes no Schedule, whatever the envelope's at says.
	wantSnapshotRun(t, paths, svc.started[0], fixtureObservedAt)

	_, record := provisionOnSuite(t, paths, svc.started[0])
	validateTwinJSON(t, record)
	w := decodeRecord(t, record)
	if w.Source != wire.SourceSnapshot || w.SnapshotID == nil || *w.SnapshotID != fixtureSnapshotID || w.BundleID != fixtureBundleID ||
		w.Provenance.Branch != "fylgja-fixture" || w.Provenance.At != fixtureAt {
		t.Errorf("the run recorded\n%s\nwant source snapshot, snapshot %s and bundle %s of fylgja-fixture at %s", record,
			fixtureSnapshotID, fixtureBundleID, fixtureAt)
	}
}

// US3 scenario 2: an id the store does not hold is snapshot.unknown at resolve, exit 1,
// naming the id and the store's directory, before any run: nothing is dialled and nothing is
// filed.
func TestCreateFromAnUnknownSnapshot(t *testing.T) {
	paths := useStateRoot(t)
	dials := countDials(t)

	code, doc := executeTwin(t, "twin", "create", "--snapshot", fixtureSnapshotID)
	want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleSnapshotUnknown, Step: findings.StepResolve,
		Object: fixtureSnapshotID, Message: "the store under " + paths.Snapshots + " holds no snapshot " + fixtureSnapshotID +
			"; a snapshot id names one this server filed when a create, a step, a dry run or a twin diff sent it its file"}
	if code != findings.ExitRejected || len(doc.Findings) != 1 || doc.Findings[0] != want {
		t.Errorf("exit %d, findings %+v; want 1 with %+v", code, doc.Findings, want)
	}
	if n := dials.Load(); n != 0 {
		t.Errorf("dialled %d times; want none", n)
	}
	if got := storedBundles(t, paths.Bundles); len(got) != 0 {
		t.Errorf("bundles/ holds %v", got)
	}
	validateM10Document(t, doc)
}

// US3 scenario 3: a file declaring a snapshot_id its body does not hash to is
// snapshot.id.mismatch at resolve, naming the file and both ids; nothing is filed or started.
func TestCreateFromAMismatchedFile(t *testing.T) {
	paths := useStateRoot(t)
	dials := countDials(t)
	declared := strings.Repeat("1", 64)
	file := snapshotFile(t, func(d map[string]any) { d["snapshot_id"] = declared })

	code, doc := executeTwin(t, "twin", "create", "--snapshot", file)
	want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleSnapshotIDMismatch, Step: findings.StepResolve,
		Object: file, Message: file + " declares snapshot_id " + declared + ", but its body hashes to " + fixtureSnapshotID +
			"; leave snapshot_id out to have it computed"}
	if code != findings.ExitRejected || len(doc.Findings) != 1 || doc.Findings[0] != want || doc.Subject.Snapshot != file {
		t.Errorf("exit %d, findings %+v, subject %+v; want 1 with %+v", code, doc.Findings, doc.Subject, want)
	}
	if got := filedSnapshots(t, paths); len(got) != 0 || dials.Load() != 0 {
		t.Errorf("snapshots/ holds %v and the service was dialled %d times; want neither", got, dials.Load())
	}
	validateM10Document(t, doc)
}

// US3 scenario 4: a file with no snapshot_id and no observed_at has both computed from its
// body, is filed under its id, and builds the twin.
func TestCreateFromAFileWithNoID(t *testing.T) {
	paths := useStateRoot(t)
	useInterrupts(t)
	svc := &fakeService{runID: "run-1", result: readyResult()}
	useService(t, svc)
	file := snapshotFile(t, func(d map[string]any) {
		delete(d, "snapshot_id")
		delete(d, "observed_at")
	})

	code, doc := executeTwin(t, "twin", "create", "--snapshot", file)
	if code != findings.ExitOK || doc.SnapshotID != fixtureSnapshotID || len(svc.started) != 1 {
		t.Fatalf("exit %d, document %+v, started %+v; want 0, snapshot %s, one run", code, doc, svc.started, fixtureSnapshotID)
	}
	wantSnapshotRun(t, paths, svc.started[0], fixtureObservedAt)
	if got := filedSnapshots(t, paths); len(got) != 1 || got[0] != fixtureSnapshotID+".json" {
		t.Errorf("snapshots/ holds %v, want the file's snapshot under its id", got)
	}
	validateM10Document(t, doc)
}

// US3 scenario 8: a file of a snapshot the store holds, taken later, leaves the entry as the
// first take filed it, and the twin records the stored document's observed_at.
func TestCreateFromAFileOfAStoredSnapshotKeepsTheFirstTake(t *testing.T) {
	paths := useStateRoot(t)
	useInterrupts(t)
	svc := &fakeService{runID: "run-1", result: readyResult()}
	useService(t, svc)
	storeFixtureSnapshot(t, paths)
	entry := filepath.Join(paths.Snapshots, fixtureSnapshotID+".json")
	first, err := os.ReadFile(entry)
	if err != nil {
		t.Fatal(err)
	}
	const later = "2026-10-27T10:30:00.000000Z"
	file := snapshotFile(t, func(d map[string]any) {
		d["observed_at"] = later
		d["ctm"].(map[string]any)["envelope"].(map[string]any)["observed_at"] = later
	})

	if code, doc := executeTwin(t, "twin", "create", "--snapshot", file); code != findings.ExitOK || len(svc.started) != 1 {
		t.Fatalf("exit %d, findings %+v, started %+v; want 0 and one run", code, doc.Findings, svc.started)
	}
	wantSnapshotRun(t, paths, svc.started[0], fixtureObservedAt)
	if b, err := os.ReadFile(entry); err != nil || !bytes.Equal(b, first) {
		t.Errorf("the entry changed (%v):\n%s", err, b)
	}
}

// A dry run from a snapshot reads nothing: it files the bundle, reports as a create's dry
// run does, with the snapshot's stored line above the bundle's and no read: line, and says
// nothing of following (019).
func TestCreateDryRunFromASnapshot(t *testing.T) {
	for _, args := range [][]string{{"--dry-run"}} {
		t.Run(strings.Join(args, " "), func(t *testing.T) {
			paths := useStateRoot(t)
			useService(t, nil)
			dryRunEnv(t)
			useClab(t, "inspect-empty.json")
			storeFixtureSnapshot(t, paths)

			var err error
			f := &createFlags{snapshot: fixtureSnapshotID, snapshotGiven: true, dryRun: true}
			out := captureStdout(t, func() { err = runCreate(context.Background(), &options{}, f) })
			if code, doc := exitOf(t, err); code != findings.ExitOK {
				t.Fatalf("exit %d, findings %+v; want 0", code, doc.Findings)
			}
			want := lines(append(append([]string{"dry run: no lab, container, twin directory or run is created"},
				storedLines(paths, fixtureSnapshotID, fixtureBundleID)...), "nodes:")...)
			if !strings.HasPrefix(out, want) {
				t.Errorf("stdout:\n%s\nwant it to begin:\n%s", out, want)
			}
			if strings.Contains(out, "\nfollow:") {
				t.Errorf("stdout:\n%s\nwant no follow: line", out)
			}

			code, doc := executeTwin(t, append([]string{"twin", "create", "--snapshot", fixtureSnapshotID}, args...)...)
			if code != findings.ExitOK || doc.SnapshotID != fixtureSnapshotID || doc.BundleID != fixtureBundleID || doc.DryRun == nil {
				t.Errorf("exit %d, document %+v; want 0 naming both ids", code, doc)
			}
			validateM10Document(t, doc)
		})
	}
}

// R-07: a snapshot file the client cannot read is the client's own operation.failed, exit 2,
// worded as snapshot.Load words it, and no request reaches the server.
func TestUnreadableSnapshotFileIsTheClients(t *testing.T) {
	useStateRoot(t)
	dials := countDials(t)
	missing := filepath.Join(t.TempDir(), "absent.json")
	awaitIdle(t)
	before := strings.Count(harness.log.String(), "operation="+findings.OpTwinCreate+" ")

	code, doc, _ := executeClient(t, "twin", "create", "--snapshot", missing)
	want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleOperationFailed, Object: findings.OpTwinCreate,
		Message: "reading snapshot: open " + missing + ": no such file or directory"}
	if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0] != want || doc.Subject.Snapshot != missing {
		t.Errorf("exit %d, findings %+v, subject %+v; want 2 with %+v", code, doc.Findings, doc.Subject, want)
	}
	awaitIdle(t)
	if after := strings.Count(harness.log.String(), "operation="+findings.OpTwinCreate+" "); after != before || dials.Load() != 0 {
		t.Errorf("the server logged %d creates and the service was dialled %d times; want none", after-before, dials.Load())
	}
	validateM10Document(t, doc)
}

// The Edge Case's "neither a readable file nor an id", given empty: an explicit --snapshot=
// with no flag beside it the guards refuse names no file, and is the client's own
// operation.failed, exit 2, naming --snapshot, before any connection (T078).
func TestEmptySnapshotIsTheClients(t *testing.T) {
	useStateRoot(t)
	dials := countDials(t)
	awaitIdle(t)
	before := strings.Count(harness.log.String(), "operation="+findings.OpTwinCreate+" ")

	code, doc, _ := executeClient(t, "twin", "create", "--snapshot=", "--dry-run")
	want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleOperationFailed, Object: findings.OpTwinCreate,
		Message: "--snapshot= is empty; give a snapshot id or the path of a snapshot file"}
	if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0] != want {
		t.Errorf("exit %d, findings %+v; want 2 with %+v", code, doc.Findings, want)
	}
	awaitIdle(t)
	if after := strings.Count(harness.log.String(), "operation="+findings.OpTwinCreate+" "); after != before || dials.Load() != 0 {
		t.Errorf("the server logged %d creates and the service was dialled %d times; want none", after-before, dials.Load())
	}
	validateM10Document(t, doc)
}

// US3 scenario 6 and FR-017: twin show describes a twin built from a snapshot by its
// envelope, as any twin of a snapshot (019): kind snapshot, its line naming the snapshot and
// its branch at its at, or its read time; the record line names it in full, and its source
// is snapshot.
func TestShowSnapshotTwin(t *testing.T) {
	const at = "2026-09-08T12:00:00Z"
	id := fixtureSnapshotID
	provisioned := "  provisioned by run fylgja-provision " + showRunID + " (source snapshot), worker 0.1.0-dev, recorded 2026-09-16T19:01:02Z, 3 nodes\n"
	record := func(at string) string {
		ref := "fylgja-fixture"
		if at != "" {
			ref += " at " + at
		}
		return "record: branch " + ref + ", snapshot " + id + ", bundle_id " + showBundleID + ", schema 41349c3a9c582e5dd44e55d6771f79c2, " +
			showRead + "\n"
	}
	for _, c := range []struct {
		name   string
		at     string
		stdout string
		kind   string
		notes  []string
	}{
		{"with an at", at, threeNodes + record(at) + "  intent read at " + showObserved + "\n" + provisioned +
			lines("kind: snapshot b9db37f8… (branch fylgja-fixture at "+at+")", "in flight: none"),
			findings.ShowKindSnapshot, nil},
		{"without", "", threeNodes + record("") +
			"  intent read at " + showObserved + "; reproducing it with --at that instant is best-effort\n" + provisioned +
			lines("kind: snapshot b9db37f8… (branch fylgja-fixture, read at "+showObserved+")", "in flight: none"),
			findings.ShowKindSnapshot, []string{bestEffortNote}},
	} {
		t.Run(c.name, func(t *testing.T) {
			paths := useStateRoot(t)
			writeTwin(t, paths, twinOf(t, func(f *lab.RecordFields) {
				f.Source, f.SnapshotID, f.Provenance.At = wire.SourceSnapshot, id, c.at
			}))
			out := showWith(t, paths, "inspect-three.json", &fakeService{})
			wantShow(t, out, c.stdout, c.kind, c.notes...)
			if r := out.doc.Show.Record; r == nil || r.Source != wire.SourceSnapshot || r.SnapshotID == nil || *r.SnapshotID != id {
				t.Errorf("record %+v; want source snapshot naming %s", r, id)
			}
		})
	}
}

// US3 scenario 7, reversed by 019 (US2 scenario 3): a twin built from a snapshot names no
// stage and steps to a snapshot all the same, the guard that only a twin built from a stage
// steps gone. Its dry run goes from the snapshot the record names. TestStepToASnapshot steps
// it by id and by file.
func TestStepFromSnapshotTwin(t *testing.T) {
	h := stepHost(t, "plan-link-added.json", func(f *lab.RecordFields) { f.Source = wire.SourceSnapshot })
	target, toID := targetSnapshot(t, h, "linked")
	out := runStepCmd(t, "--snapshot", target.ID, "--dry-run", "--allow-restart")
	if out.code != findings.ExitOK || out.doc.Step == nil || out.doc.Step.From.Stage != nil || out.doc.Step.To.BundleID != toID {
		t.Errorf("exit %d, step %+v, findings %+v; want 0 from the record's snapshot to %s", out.code, out.doc.Step, out.doc.Findings, toID)
	}
}

// The client tells an id from a file by the core's own shape: snapshot.IsID, which the client
// does not link, written as isSnapshotID (R-07).
func TestSnapshotIDShapeIsTheCoresOwn(t *testing.T) {
	for _, s := range []string{fixtureSnapshotID, strings.ToUpper(fixtureSnapshotID), fixtureSnapshotID[:63], fixtureSnapshotID + "0",
		strings.Repeat("g", 64), "snap.json", "", "./" + fixtureSnapshotID[:62]} {
		if got, want := isSnapshotID(s), snap.IsID(s); got != want {
			t.Errorf("isSnapshotID(%q) = %v, snapshot.IsID says %v", s, got, want)
		}
	}
}

// FR-009, FR-015: twin create's help says what the server does before the run, as twin
// compile's says it takes a snapshot (TestCompileTakesNoCTM): it builds from --snapshot, files
// a file sent and compiles it, with no read, and the run begins at the host check; a branch or
// a stage is fylgja-cli's (020, FR-003). The help's line breaks are not pinned.
func TestCreateHelpNamesTheServersTake(t *testing.T) {
	help := &cobra.Command{Use: "fylgja"}
	help.AddCommand(newTwinCmd(&options{}))
	help.SetArgs([]string{"twin", "create", "--help"})
	text := strings.Join(strings.Fields(captureStdout(t, func() {
		if err := help.Execute(); err != nil {
			t.Error(err)
		}
	})), " ")
	for _, want := range []string{
		"Provision one twin from a snapshot: --snapshot <id|file> names one the API's server's store holds by its id, " +
			"or a snapshot file sent from here, which the server files.",
		"The server compiles it and files the bundle, before any run; no source of truth is read.",
		"one run with the fixed identity fylgja-provision, from the host check on,",
		"A twin of a branch or a stage is fylgja-cli twin create's, the orchestrator's,",
		"--snapshot string",
		"file a snapshot file sent, compile and file the bundle, and check the host; start no run",
	} {
		if !strings.Contains(text, want) {
			t.Errorf("the help does not say %q:\n%s", want, text)
		}
	}
	for _, gone := range []string{"--branch", "--at", "--stage", "--scope", "--probes"} {
		if strings.Contains(text, gone+" ") {
			t.Errorf("the help still names %s:\n%s", gone, text)
		}
	}
	if strings.Contains(text, "Read an Infrahub branch, compile it") {
		t.Errorf("the help still says the run reads and compiles:\n%s", text)
	}
}
