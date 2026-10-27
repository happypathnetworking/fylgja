//go:build contract

package server

import (
	"bytes"
	"maps"
	"os"
	"path/filepath"
	"slices"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/snapshot"
	"github.com/happypathnetworking/fylgja/internal/stages"
)

// One stage taken twice through the server's path has one snapshot (SC-002; R-16), against
// a real Infrahub, never a fake (D-017): on a seeded branch with a draft proposed change and
// one mark, stage plan runs twice on one state root, as the API runs it. Each compiled
// stage names one snapshot_id in both plans. The second plan's takes find their entries
// filed and keep them, bytes and modification time, so the first take's observed_at is the
// one kept, and no entry is added. Neither plan writes a CTM beside a bundle: the sidecar
// is retired (FR-008). The plan dials no workflow service. The branch, its proposed change
// and its stage are deleted when the test ends, as rehearse_contract_test.go deletes them.
//
//	set -a; . local/.env; set +a; go test -count=1 -tags contract ./internal/server -run TestStageTakenTwiceHasOneSnapshot -v
func TestStageTakenTwiceHasOneSnapshot(t *testing.T) {
	c := contractClient(t)
	paths := useStateRoot(t)
	useService(t, nil)
	branch := seededBranch(t, c)
	started := time.Now()
	id, err := c.OpenProposedChange(branch, true)
	if err != nil {
		t.Fatalf("opening a proposed change on %s: %v", branch, err)
	}
	t.Logf("proposed change %s on %s, its pipeline concluded after %.0fs", id, branch, time.Since(started).Seconds())
	const label = "seeded"
	if _, _, err := c.MarkStage(id, label, "", label); err != nil {
		t.Fatalf("marking %s: %v", label, err)
	}

	plan := func(which string) *findings.PlanBlock {
		t.Helper()
		started := time.Now()
		code, doc := exitOf(t, runStagePlan(t.Context(), testOptions(t, false),
			&stageFlags{branch: branch, branchGiven: true, scope: fixtureScope, scopeGiven: true}))
		t.Logf("the %s plan: exit %d in %.1fs", which, code, time.Since(started).Seconds())
		if doc.Plan == nil {
			t.Fatalf("the %s plan carries no plan block: %+v", which, doc)
		}
		return doc.Plan
	}
	// filed are the store's entries, by name: what each holds and when it was written.
	type entry struct {
		data    []byte
		modTime time.Time
	}
	filed := func() map[string]entry {
		t.Helper()
		names, err := os.ReadDir(paths.Snapshots)
		if err != nil {
			t.Fatalf("reading the store: %v", err)
		}
		out := map[string]entry{}
		for _, n := range names {
			info, err := n.Info()
			if err != nil {
				t.Fatal(err)
			}
			data, err := os.ReadFile(filepath.Join(paths.Snapshots, n.Name()))
			if err != nil {
				t.Fatal(err)
			}
			out[n.Name()] = entry{data: data, modTime: info.ModTime()}
		}
		return out
	}
	noSidecar := func(which string) {
		t.Helper()
		left, err := filepath.Glob(filepath.Join(paths.Bundles, "*.ctm.json"))
		if err != nil {
			t.Fatal(err)
		}
		if len(left) != 0 {
			t.Errorf("the %s plan wrote %v beside the bundles; the sidecar is retired", which, left)
		}
	}

	first := plan("first")
	noSidecar("first")
	// The stages that compiled, by label, and the store's entries they name. The mark and the
	// head compile; the branch point reads main, which holds no device, and is refused.
	ids := map[string]string{}
	var named []string
	for _, st := range first.Stages {
		if st.SnapshotID != nil {
			named = append(named, *st.SnapshotID+".json")
		}
		if st.BundleID == nil {
			continue
		}
		if st.SnapshotID == nil {
			t.Errorf("the first plan compiled %s to %s naming no snapshot", st.Ref, *st.BundleID)
			continue
		}
		ids[st.Label] = *st.SnapshotID
		t.Logf("%s: snapshot %s, bundle %s", st.Ref, *st.SnapshotID, *st.BundleID)
	}
	for _, want := range []string{label, stages.LabelHead} {
		if ids[want] == "" {
			t.Fatalf("the first plan compiled %v; want %s and %s among them: %+v", slices.Sorted(maps.Keys(ids)),
				label, stages.LabelHead, first)
		}
	}
	store := snapshot.NewDirStore(paths.Snapshots)
	for ref, sid := range ids {
		if ok, err := store.Has(t.Context(), sid); err != nil || !ok {
			t.Errorf("%s's snapshot %s is not filed whole: %t (%v)", ref, sid, ok, err)
		}
	}
	before := filed()
	if got := slices.Sorted(maps.Keys(before)); !slices.Equal(got, slices.Compact(slices.Sorted(slices.Values(named)))) {
		t.Errorf("the first plan filed %v; want the entries its stages name, %v", got, named)
	}
	// Back-date every entry, so a rewrite within the clock's resolution could not hide.
	old := time.Now().Add(-time.Hour).Truncate(time.Second)
	for name, e := range before {
		if err := os.Chtimes(filepath.Join(paths.Snapshots, name), old, old); err != nil {
			t.Fatal(err)
		}
		e.modTime = old
		before[name] = e
	}

	second := plan("second")
	noSidecar("second")
	firstLabels, secondLabels := labelsOf(first), labelsOf(second)
	if !slices.Equal(firstLabels, secondLabels) {
		t.Fatalf("the plans' stages are %v and %v, want one list", firstLabels, secondLabels)
	}
	for i, st := range second.Stages {
		was := first.Stages[i]
		if got, want := idText(st.SnapshotID), idText(was.SnapshotID); got != want {
			t.Errorf("%s names snapshot %s in the second plan and %s in the first; want one", st.Ref, got, want)
		}
		if got, want := idText(st.BundleID), idText(was.BundleID); got != want {
			t.Errorf("%s compiles to %s in the second plan and %s in the first; want one", st.Ref, got, want)
		}
	}
	after := filed()
	if got, want := slices.Sorted(maps.Keys(after)), slices.Sorted(maps.Keys(before)); !slices.Equal(got, want) {
		t.Errorf("after the second plan the store holds %v; want the first plan's %v alone", got, want)
	}
	for name, e := range before {
		now := after[name]
		if !bytes.Equal(now.data, e.data) {
			t.Errorf("the second plan rewrote %s; the store keeps the first take", name)
		}
		if !now.modTime.Equal(e.modTime) {
			t.Errorf("%s was modified at %s by the second plan; want %s, as the first left it", name, now.modTime, e.modTime)
		}
	}
	t.Logf("%s taken twice: snapshot %s", label, ids[label])
}

// labelsOf are a plan's stage labels, in order.
func labelsOf(p *findings.PlanBlock) []string {
	out := make([]string, 0, len(p.Stages))
	for _, st := range p.Stages {
		out = append(out, st.Label)
	}
	return out
}

// idText is an id a plan names, or null for none.
func idText(id *string) string {
	if id == nil {
		return "null"
	}
	return *id
}
