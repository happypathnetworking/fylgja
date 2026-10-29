//go:build contract

package server

import (
	"bytes"
	"maps"
	"net/http"
	"net/http/httptest"
	"net/http/httputil"
	"net/url"
	"os"
	"path/filepath"
	"slices"
	"sync/atomic"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
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

// A step's snapshot target is the bundle stage plan compiles from the same read, built with
// no request to Infrahub (019, research R-17; SC-004), against a real Infrahub, never a fake
// (D-017): on a seeded branch with a draft proposed change and one mark, stage plan compiles
// the mark, then intent read --out --stage takes the mark's read on the server's path. The
// step's snapshot target is then built as twin step --snapshot builds it (snapshotTarget: the
// resolve, the scope and mapping check, the compile), for a twin whose record names the
// fixture's scope and the reader's mapping, under a state root of its own: from the file the
// read sent, then from the id it was filed under. Each names the snapshot the plan's stage
// names, compiles to its bundle, and carries the read's branch and at verbatim; the file is
// filed whole, and the id adds nothing. Every request the server sends Infrahub passes a
// counting proxy (countedInfrahub): the plan and the read send some, each target none. No
// twin boots and the workflow service is never dialled. The branch, its proposed change and
// its stage are deleted when the test ends.
//
//	set -a; . local/.env; set +a; go test -count=1 -tags contract ./internal/server -run '^TestStepTargetFromASnapshot$' -v
func TestStepTargetFromASnapshot(t *testing.T) {
	c := contractClient(t)
	useStateRoot(t)
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
	ref := stages.Ref{Branch: branch, Label: label}.String()
	requests := countedInfrahub(t)

	// The plan's stage: the snapshot and the bundle a stage step to it would build.
	code, doc := exitOf(t, runStagePlan(t.Context(), testOptions(t, false),
		&stageFlags{branch: branch, branchGiven: true, scope: fixtureScope, scopeGiven: true}))
	if doc.Plan == nil {
		t.Fatalf("the plan (exit %d) carries no plan block: %+v", code, doc)
	}
	var mark *findings.PlanStage
	for i, st := range doc.Plan.Stages {
		if st.Label == label {
			mark = &doc.Plan.Stages[i]
		}
	}
	if mark == nil || mark.SnapshotID == nil || mark.BundleID == nil {
		t.Fatalf("the plan (exit %d) did not compile %s: %+v", code, ref, doc.Plan)
	}
	sid, bid := *mark.SnapshotID, *mark.BundleID
	planned := requests.Load()
	if planned == 0 {
		t.Fatal("the plan sent no request through the proxy, so its count proves nothing")
	}
	t.Logf("stage plan: %s at %s compiled to snapshot %s, bundle %s; %d request(s) to Infrahub", ref, mark.At, sid, bid, planned)

	// intent read --out of the mark, on the server's path: the file its client writes.
	var frames recordedFrames
	opts := helperServer.newCall(t.Context(), "test", api.Request{Render: api.RenderText}, newFrames(&frames, nil), nil).options()
	code, doc = exitOf(t, runRead(t.Context(), opts,
		&readFlags{stage: ref, stageGiven: true, out: "snap.json", scope: fixtureScope, scopeGiven: true}))
	if code != findings.ExitOK || doc.SnapshotID != sid {
		t.Fatalf("intent read --stage %s: exit %d, snapshot %q, findings %+v; want 0 naming the plan's %s", ref, code,
			doc.SnapshotID, doc.Findings, sid)
	}
	read := requests.Load() - planned
	if read == 0 {
		t.Fatal("the read sent no request through the proxy, so its count proves nothing")
	}
	sent := frames.files()
	if len(sent) != 1 || len(sent[0]) != 1 {
		t.Fatalf("files frames %+v, want one carrying the snapshot alone", sent)
	}
	file := sent[0][0].Data
	s, err := snapshot.Unmarshal(file)
	if err != nil || s.ID != sid {
		t.Fatalf("the file reads as snapshot %v (%v); want %s", s, err, sid)
	}
	if env := s.CTM.Envelope; env.Branch != branch || env.At != mark.At || env.Scope != fixtureScope {
		t.Errorf("the file's envelope names branch %s, at %s, scope %s; want %s, %s, %s", env.Branch, env.At, env.Scope,
			branch, mark.At, fixtureScope)
	}
	t.Logf("intent read --out: snapshot %s observed at %s; %d request(s) to Infrahub", s.ID, s.ObservedAt, read)

	// The twin a create of this read builds: its snapshot's envelope names the fixture's scope
	// and the reader's mapping, which a step's target is held to (020, research R-06).
	held := heldEnvelope{id: sid, scope: fixtureScope,
		mapping: wire.Mapping{Reader: ctm.ReaderInfrahubDCIM, Model: ctm.ModelSchemaLibrary, Version: ctm.ModelVersion}}
	// A state root of its own, whose stores hold nothing, so the file target files the file.
	paths := useStateRoot(t)
	reg := shippedPackages(t)
	entries := func(dir string) []string {
		t.Helper()
		list, err := os.ReadDir(dir)
		if err != nil {
			t.Fatalf("reading %s: %v", dir, err)
		}
		var out []string
		for _, e := range list {
			out = append(out, e.Name())
		}
		return out
	}
	build := func(how, arg string, files []api.File) {
		t.Helper()
		before := requests.Load()
		subject := &findings.Subject{Snapshot: arg, Scope: fixtureScope}
		target, _, err := snapshotTarget(t.Context(), testOptions(t, false), findings.OpTwinStep, subject, reg, paths, held,
			arg, files)
		if n := requests.Load() - before; n != 0 {
			t.Errorf("the target from the %s sent %d request(s) to Infrahub; want none", how, n)
		}
		if err != nil {
			_, doc := exitOf(t, err)
			t.Fatalf("the target from the %s was refused: %+v", how, doc.Findings)
		}
		if target.snapshotID != sid || target.bundle.ID != bid {
			t.Errorf("the target from the %s is snapshot %s, bundle %s; want the plan's %s, %s", how, target.snapshotID,
				target.bundle.ID, sid, bid)
		}
		if name := (wire.StepSide{SnapshotID: sid}).Name(); target.name != name {
			t.Errorf("the target from the %s is named %q; want %q", how, target.name, name)
		}
		if target.branch != branch || target.at != mark.At || target.observedAt != s.ObservedAt {
			t.Errorf("the target from the %s names branch %s, at %s, observed at %s; want %s, %s, %s", how, target.branch,
				target.at, target.observedAt, branch, mark.At, s.ObservedAt)
		}
		if got, want := entries(paths.Snapshots), []string{sid + ".json"}; !slices.Equal(got, want) {
			t.Errorf("after the target from the %s the snapshot store holds %v; want %v", how, got, want)
		} else if stored, err := os.ReadFile(filepath.Join(paths.Snapshots, want[0])); err != nil || !bytes.Equal(stored, file) {
			t.Errorf("after the target from the %s the store's entry is not the file the read sent (%v)", how, err)
		}
		if got, want := entries(paths.Bundles), []string{bid}; !slices.Equal(got, want) {
			t.Errorf("after the target from the %s the bundle store holds %v; want %v", how, got, want)
		}
		t.Logf("the target from the %s: %s, bundle %s, at %s, observed at %s", how, target.name, target.bundle.ID, target.at,
			target.observedAt)
	}
	build("file", "snap.json", []api.File{{Path: "snap.json", Data: file}})
	build("id", sid, nil)
}

// countedInfrahub puts a counting proxy in front of the Infrahub INFRAHUB_ADDRESS names, and
// points INFRAHUB_ADDRESS at it for the rest of the test: every reader and stamper the server
// builds reads the address from the environment when it is built, so each of their requests
// is counted. The test's own client, built before, is not.
func countedInfrahub(t *testing.T) *atomic.Int64 {
	t.Helper()
	target, err := url.Parse(os.Getenv(intent.EnvAddress))
	if err != nil || target.Host == "" {
		t.Fatalf("%s is not an address the proxy can forward to (%v)", intent.EnvAddress, err)
	}
	var n atomic.Int64
	proxy := &httputil.ReverseProxy{Rewrite: func(r *httputil.ProxyRequest) { r.SetURL(target) }}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		n.Add(1)
		proxy.ServeHTTP(w, r)
	}))
	t.Cleanup(srv.Close)
	t.Setenv(intent.EnvAddress, srv.URL)
	return &n
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
