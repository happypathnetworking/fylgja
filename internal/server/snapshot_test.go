package server

import (
	"bytes"
	"context"
	"os"
	"path/filepath"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/snapshot"
)

// fixtureSnapshotID is the fixture CTM's snapshot id (testdata/snapshot/three-node.json).
const fixtureSnapshotID = "6a8a77fc65bdf47b9bb3a753d7709875671df20e32838344f29cfba46a13f6d6"

// loadCTM is a fixture CTM under testdata/ctm/, as a read returns one, observed at
// observedAt.
func loadCTM(t *testing.T, name, observedAt string) *ctm.CTM {
	t.Helper()
	c, err := ctm.Load(repoPath("testdata", "ctm", name))
	if err != nil {
		t.Fatal(err)
	}
	c.Envelope.ObservedAt = observedAt
	return c
}

// A take is filed under its id in the state root's snapshots/, in its stored form, and the
// path the server names is that entry (data-model §4).
func TestTakeSnapshotFilesUnderItsID(t *testing.T) {
	paths := useStateRoot(t)
	s, path, list, err := takeSnapshot(context.Background(), paths, findings.StepRead, loadCTM(t, "three-node.json", "2026-10-27T09:00:00.000000Z"))
	if err != nil || len(list) != 0 {
		t.Fatalf("takeSnapshot = %v, %v; want it filed", list, err)
	}
	if s.ID != fixtureSnapshotID || path != filepath.Join(paths.Snapshots, fixtureSnapshotID+".json") {
		t.Errorf("took %s at %s; want %s under %s", s.ID, path, fixtureSnapshotID, paths.Snapshots)
	}
	stored, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	want, err := snapshot.Marshal(s)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(stored, want) {
		t.Errorf("the entry is not the take's stored form:\n%s", stored)
	}
	if got := snapshotStoredLine(s.ID, path); got != "snapshot_id "+fixtureSnapshotID+"  stored: "+path {
		t.Errorf("the stored line reads %q", got)
	}
	if got := bundleStoredLine(fixtureBundleID, "/b"); got != "bundle_id "+fixtureBundleID+"  stored: /b" {
		t.Errorf("the bundle's stored line reads %q", got)
	}
}

// A second take of the same intent, read later, has the same id and leaves the entry as the
// first take filed it: the store never overwrites, so the first take's observed_at is kept.
func TestASecondTakeLeavesTheEntry(t *testing.T) {
	paths := useStateRoot(t)
	ctx := context.Background()
	_, path, _, err := takeSnapshot(ctx, paths, findings.StepRead, loadCTM(t, "three-node.json", "2026-10-27T09:00:00.000000Z"))
	if err != nil {
		t.Fatal(err)
	}
	first, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	s, again, list, err := takeSnapshot(ctx, paths, findings.StepRead, loadCTM(t, "three-node.json", "2026-10-27T10:30:00.000000Z"))
	if err != nil || len(list) != 0 || s.ID != fixtureSnapshotID || again != path {
		t.Fatalf("the second take = %v at %s, %v, %v; want %s at %s", s, again, list, err, fixtureSnapshotID, path)
	}
	if second, err := os.ReadFile(path); err != nil || !bytes.Equal(second, first) {
		t.Errorf("the second take changed the entry (%v):\n%s", err, second)
	}
	if entries, err := os.ReadDir(paths.Snapshots); err != nil || len(entries) != 1 {
		t.Errorf("snapshots/ holds %v (%v); want the one entry", entries, err)
	}
}

// An entry under the take's id that hashes to another is snapshot.id.mismatch at the step the
// caller gives, naming the store path and both ids, and nothing is filed over it.
func TestACorruptEntryIsSnapshotIDMismatch(t *testing.T) {
	paths := useStateRoot(t)
	ctx := context.Background()
	other, _, _, err := takeSnapshot(ctx, paths, findings.StepRead, loadCTM(t, "lossy.json", "2026-10-27T09:00:00.000000Z"))
	if err != nil {
		t.Fatal(err)
	}
	corrupt, err := snapshot.Marshal(other)
	if err != nil {
		t.Fatal(err)
	}
	entry := filepath.Join(paths.Snapshots, fixtureSnapshotID+".json")
	if err := os.WriteFile(entry, corrupt, 0o644); err != nil {
		t.Fatal(err)
	}

	s, path, list, err := takeSnapshot(ctx, paths, findings.StepCompile, loadCTM(t, "three-node.json", "2026-10-27T09:00:00.000000Z"))
	if err != nil || s != nil || path != "" {
		t.Fatalf("takeSnapshot = %v at %q, %v; want no snapshot and the refusal", s, path, err)
	}
	want := "store entry " + entry + " hashes to " + other.ID + ", not " + fixtureSnapshotID + ", so snapshot " + fixtureSnapshotID +
		" cannot be filed"
	if len(list) != 1 || list[0].Rule != findings.RuleSnapshotIDMismatch || list[0].Severity != findings.Rejection ||
		list[0].Step != findings.StepCompile || list[0].Object != entry || list[0].Message != want {
		t.Errorf("findings %+v; want one %s at step compile naming %s: %s", list, findings.RuleSnapshotIDMismatch, entry, want)
	}
	if stored, err := os.ReadFile(entry); err != nil || !bytes.Equal(stored, corrupt) {
		t.Errorf("the corrupt entry was rewritten (%v)", err)
	}
}
