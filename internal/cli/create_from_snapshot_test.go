package cli

import (
	"bytes"
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

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
// envelope's branch, at and scope, the stored document's observed_at, both ids, and no
// following or stage.
func wantSnapshotRun(t *testing.T, paths lab.Paths, in provision.ProvisionInput, observedAt string) {
	t.Helper()
	if in.Source != wire.SourceSnapshot || in.SnapshotID != fixtureSnapshotID || in.BundleID != fixtureBundleID ||
		in.BundlePath != filepath.Join(paths.Bundles, fixtureBundleID) || in.Branch != "fylgja-fixture" || in.At != fixtureAt ||
		in.Scope != "tag:fylgja" || in.ObservedAt != observedAt || in.Follow != nil || in.Stage != nil {
		t.Errorf("the run was started with %+v; want source snapshot, snapshot %s, bundle %s, branch fylgja-fixture at %s, "+
			"scope tag:fylgja, observed at %s, no follow and no stage", in, fixtureSnapshotID, fixtureBundleID, fixtureAt, observedAt)
	}
}

// US3 scenario 1 and FR-015: a stored snapshot's id builds the twin with no read. The server
// compiles the stored snapshot, files the bundle and starts the provision run with both ids,
// printing the two stored lines before it; the fake Infrahub is asked nothing, and the run's
// record names the snapshot, its source snapshot, at the envelope's at.
func TestCreateFromAStoredSnapshot(t *testing.T) {
	paths := useStateRoot(t)
	useInterrupts(t)
	svc := &fakeService{runID: "run-1", result: readyResult()}
	useService(t, svc)
	infra := newFakeInfrahub(t)
	infra.start()
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
	if n := len(infra.requests()); n != 0 {
		t.Errorf("Infrahub was asked %d requests: %+v", n, infra.requests())
	}
	if len(svc.started) != 2 {
		t.Fatalf("started %+v, want two runs", svc.started)
	}
	// No Follow: the run makes no Schedule, whatever the envelope's at says.
	wantSnapshotRun(t, paths, svc.started[0], fixtureObservedAt)

	_, record := provisionOnSuite(t, paths, svc.started[0])
	validateTwinJSON(t, record)
	w := decodeRecord(t, record)
	if w.Source != wire.SourceSnapshot || w.SnapshotID == nil || *w.SnapshotID != fixtureSnapshotID || w.BundleID != fixtureBundleID ||
		w.Provenance.Branch != "fylgja-fixture" || w.Provenance.At != fixtureAt || w.Stage != nil {
		t.Errorf("the run recorded\n%s\nwant source snapshot, snapshot %s and bundle %s of fylgja-fixture at %s", record,
			fixtureSnapshotID, fixtureBundleID, fixtureAt)
	}
}

// US3 scenario 2: an id the store does not hold is snapshot.unknown at resolve, exit 1,
// naming the id and the store's directory, before any run: nothing is dialled, Infrahub is
// asked nothing, and nothing is filed.
func TestCreateFromAnUnknownSnapshot(t *testing.T) {
	paths := useStateRoot(t)
	dials := countDials(t)
	infra := newFakeInfrahub(t)
	infra.start()

	code, doc := executeTwin(t, "twin", "create", "--snapshot", fixtureSnapshotID)
	want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleSnapshotUnknown, Step: findings.StepResolve,
		Object: fixtureSnapshotID, Message: "the store under " + paths.Snapshots + " holds no snapshot " + fixtureSnapshotID +
			"; a snapshot id comes from a create, a dry run, a plan or intent read --out on this server"}
	if code != findings.ExitRejected || len(doc.Findings) != 1 || doc.Findings[0] != want {
		t.Errorf("exit %d, findings %+v; want 1 with %+v", code, doc.Findings, want)
	}
	if n := dials.Load(); n != 0 || len(infra.requests()) != 0 {
		t.Errorf("dialled %d times and asked Infrahub %+v; want neither", n, infra.requests())
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
// the twin would not follow; --no-follow beside it is accepted and changes nothing.
func TestCreateDryRunFromASnapshot(t *testing.T) {
	for _, args := range [][]string{{"--dry-run"}, {"--dry-run", "--no-follow"}} {
		t.Run(strings.Join(args, " "), func(t *testing.T) {
			paths := useStateRoot(t)
			useService(t, nil)
			dryRunEnv(t)
			useClab(t, "inspect-empty.json")
			infra := newFakeInfrahub(t)
			infra.start()
			storeFixtureSnapshot(t, paths)

			var err error
			f := &createFlags{snapshot: fixtureSnapshotID, snapshotGiven: true, dryRun: true, noFollow: len(args) > 1}
			out := captureStdout(t, func() { err = runCreate(context.Background(), &options{}, f) })
			if code, doc := exitOf(t, err); code != findings.ExitOK {
				t.Fatalf("exit %d, findings %+v; want 0", code, doc.Findings)
			}
			want := lines(append(append([]string{"dry run: no lab, container, twin directory or run is created"},
				storedLines(paths, fixtureSnapshotID, fixtureBundleID)...), "nodes:")...)
			if !strings.HasPrefix(out, want) {
				t.Errorf("stdout:\n%s\nwant it to begin:\n%s", out, want)
			}
			if line := "follow: would not follow (--snapshot given: a twin built from a snapshot never follows)\n"; !strings.Contains(out, line) {
				t.Errorf("stdout:\n%s\nwant %q", out, line)
			}

			code, doc := executeTwin(t, append([]string{"twin", "create", "--snapshot", fixtureSnapshotID}, args...)...)
			if code != findings.ExitOK || doc.SnapshotID != fixtureSnapshotID || doc.BundleID != fixtureBundleID || doc.DryRun == nil ||
				doc.DryRun.Follow == nil || doc.DryRun.Follow.Reason != findings.FollowReasonSnapshot {
				t.Errorf("exit %d, document %+v; want 0 naming both ids and follow reason snapshot", code, doc)
			}
			validateM10Document(t, doc)
			if n := len(infra.requests()); n != 0 {
				t.Errorf("Infrahub was asked %d requests", n)
			}
		})
	}
}

// US3 scenario 5 and FR-016, FR-018: --snapshot beside --branch, --stage, --at or --scope is
// snapshot.flags.conflict naming the first found in that order, and --interval beside it is
// follow.flags.conflict, each exit 2 at start, the server's refusal before any connection:
// neither the workflow service dialled nor Infrahub asked, whether --snapshot is an id or a
// file.
func TestSnapshotFlagConflicts(t *testing.T) {
	const conflict = " is meaningless with --snapshot: a snapshot carries its own branch, at and scope"
	refusal := func(rule, object, message string) findings.Finding {
		return findings.Finding{Severity: findings.Rejection, Rule: rule, Step: findings.StepStart, Object: object, Message: message}
	}
	file := snapshotFile(t, nil)
	for _, c := range []struct {
		name string
		args []string
		want findings.Finding
	}{
		{"--branch", []string{"--branch", "fylgja-fixture"}, refusal(findings.RuleSnapshotFlagsConflict, "--branch", "--branch"+conflict)},
		{"--stage", []string{"--stage", "change-1/cabled"}, refusal(findings.RuleSnapshotFlagsConflict, "--stage", "--stage"+conflict)},
		{"--stage=", []string{"--stage="}, refusal(findings.RuleSnapshotFlagsConflict, "--stage", "--stage"+conflict)},
		{"--at", []string{"--at", "2026-09-16T14:00:00Z"}, refusal(findings.RuleSnapshotFlagsConflict, "--at", "--at"+conflict)},
		{"--scope", []string{"--scope", "tag:fylgja"}, refusal(findings.RuleSnapshotFlagsConflict, "--scope", "--scope"+conflict)},
		{"--scope and --at", []string{"--scope", "tag:fylgja", "--at", "2026-09-16T14:00:00Z"},
			refusal(findings.RuleSnapshotFlagsConflict, "--at", "--at"+conflict)},
		{"--stage and --branch", []string{"--stage", "change-1/cabled", "--branch", "change-1"},
			refusal(findings.RuleSnapshotFlagsConflict, "--branch", "--branch"+conflict)},
		{"--interval", []string{"--interval", "1m"},
			refusal(findings.RuleFollowFlagsConflict, "--interval", "--interval is meaningless with --snapshot: a twin built from a snapshot never follows")},
		{"--interval and --no-follow", []string{"--interval", "1m", "--no-follow"},
			refusal(findings.RuleFollowFlagsConflict, "--interval", "--interval is meaningless with --snapshot: a twin built from a snapshot never follows")},
		{"--interval and --branch", []string{"--interval", "1m", "--branch", "fylgja-fixture"},
			refusal(findings.RuleSnapshotFlagsConflict, "--branch", "--branch"+conflict)},
	} {
		for _, given := range []string{fixtureSnapshotID, file} {
			t.Run(c.name+" beside "+filepath.Base(given), func(t *testing.T) {
				paths := useStateRoot(t)
				dials := countDials(t)
				infra := newFakeInfrahub(t)
				infra.start()
				awaitIdle(t)
				served := servedRequests(findings.OpTwinCreate, string(findings.StatusError))

				code, doc, raw := executeClient(t, append([]string{"twin", "create", "--snapshot", given}, c.args...)...)
				if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0] != c.want || doc.Subject.Snapshot != given {
					t.Errorf("exit %d, findings %+v, subject %+v; want 2 with %+v alone", code, doc.Findings, doc.Subject, c.want)
				}
				if n := dials.Load(); n != 0 || len(infra.requests()) != 0 {
					t.Errorf("dialled %d times and asked Infrahub %+v before the refusal", n, infra.requests())
				}
				awaitIdle(t)
				if got := servedRequests(findings.OpTwinCreate, string(findings.StatusError)) - served; got != 1 {
					t.Errorf("the server logged %d refused creates, want 1: the refusal is the server's", got)
				}
				if got := filedSnapshots(t, paths); len(got) != 0 {
					t.Errorf("snapshots/ holds %v after a refusal before any connection", got)
				}
				validateM10Document(t, doc)
				mustCarryNoToken(t, c.name, raw)
			})
		}
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

// US3 scenario 6 and FR-017: twin show describes a twin built from a snapshot by its
// envelope, pinned at its at or frozen, never following, whatever Schedule exists, with the
// note naming the snapshot in full; the record line names it, and its source is snapshot.
func TestShowSnapshotTwin(t *testing.T) {
	const at = "2026-09-08T12:00:00Z"
	id := fixtureSnapshotID
	built := "built from snapshot " + id
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
			lines("kind: pinned at "+at+"; not following; built from snapshot 6a8a77fc…", "in flight: none"),
			findings.ShowKindPinned, []string{"pinned at " + at + "; not following", built}},
		{"without", "", threeNodes + record("") +
			"  intent read at " + showObserved + "; reproducing it with --at that instant is best-effort\n" + provisioned +
			lines("kind: frozen; not following; built from snapshot 6a8a77fc…", "in flight: none"),
			findings.ShowKindFrozen, []string{"not following", bestEffortNote, built}},
	} {
		t.Run(c.name, func(t *testing.T) {
			paths := useStateRoot(t)
			writeTwin(t, paths, twinOf(t, func(f *lab.RecordFields) {
				f.Source, f.SnapshotID, f.Provenance.At = wire.SourceSnapshot, id, c.at
			}))
			// A Schedule of the twin's own branch, which a following twin would be read by.
			out := showWith(t, paths, "inspect-three.json", &fakeService{following: followingState("fylgja-fixture")})
			wantShow(t, out, c.stdout, c.kind, c.notes...)
			if r := out.doc.Show.Record; r == nil || r.Source != wire.SourceSnapshot || r.SnapshotID == nil || *r.SnapshotID != id {
				t.Errorf("record %+v; want source snapshot naming %s", r, id)
			}
		})
	}
}

// US3 scenario 7: a twin built from a snapshot names no stage, so twin step refuses it by the
// existing guard, step.twin.unsteppable at resolve, naming the record's branch as for a twin
// of a branch, before Infrahub is asked.
func TestStepFromSnapshotTwinIsUnsteppable(t *testing.T) {
	h := stepHost(t, "plan-link-added.json", func(f *lab.RecordFields) {
		f.Stage, f.Source, f.SnapshotID = nil, wire.SourceSnapshot, fixtureSnapshotID
	})
	out := runStepCmd(t)
	want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepTwinUnsteppable, Step: findings.StepResolve,
		Object: h.fromID, Message: "the twin was created from branch change-1 at " + stepMixedAt + ", not from a stage, so it names " +
			"no proposed change to step along; only a twin built from a stage steps (fylgja twin create --stage)"}
	if got := refusalOf(t, out.doc); out.code != findings.ExitRejected || got != want {
		t.Errorf("exit %d, refusal %+v; want 1 with %+v", out.code, got, want)
	}
	if len(h.infra.requests()) != h.before {
		t.Errorf("Infrahub was asked %+v after the host was built", h.infra.requests()[h.before:])
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
