//go:build contract

package waypoint

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"maps"
	"math/rand"
	"net/http"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/stage"
	"github.com/happypathnetworking/fylgja/internal/testsupport"
)

// Contract tests run against a real Infrahub, never a fake (D-017). The waypoint kind must
// be on the default branch (prerequisites).
//
//	set -a; . local/.env; set +a; go test -count=1 -tags contract ./internal/waypoint -run Waypoint -v

// harness returns a write-capable client, skipping when no Infrahub is configured.
func harness(t *testing.T) *testsupport.Client {
	t.Helper()
	c, err := testsupport.NewClient()
	if err != nil {
		t.Skipf("contract tests need a running Infrahub: %v", err)
	}
	return c
}

// seriesBranch makes a throwaway branch and names a test series after it,
// fylgja-test-wp-<ts>-<n> both, each removed when the test ends: the
// series first, then the branch. The durable fylgja-fixture branch is never written, and
// no series outlives its test.
func seriesBranch(t *testing.T) (*testsupport.Client, string) {
	t.Helper()
	c := harness(t)
	name := fmt.Sprintf("%swp-%d-%d", testsupport.TestSeriesPrefix, time.Now().Unix(), rand.Intn(9999))
	if err := c.CreateBranch(name); err != nil {
		t.Fatalf("creating branch: %v", err)
	}
	t.Cleanup(func() {
		if err := c.DeleteBranch(name); err != nil {
			t.Logf("could not delete branch %s: %v", name, err)
		}
	})
	t.Cleanup(func() {
		n, err := c.DeleteWaypointSeries(name)
		if err != nil {
			t.Logf("could not delete series %s: %v", name, err)
			return
		}
		t.Logf("deleted %d waypoint(s) of series %s", n, name)
	})
	return c, name
}

// writtenAt is the harness's own read of a waypoint's branch.updated_at, on the default
// branch's GraphQL, so the product's resolution is checked against Infrahub rather than
// against itself.
func writtenAt(t *testing.T, c *testsupport.Client, series string, sequence int) string {
	t.Helper()
	raw, err := c.GraphQL("main", fmt.Sprintf(
		`{ FylgjaWaypoint(series__value: %q, sequence__value: %d) { edges { node { branch { updated_at } } } } }`, series, sequence))
	if err != nil {
		t.Fatalf("reading %s/%d back: %v", series, sequence, err)
	}
	var r struct {
		W struct {
			Edges []struct {
				Node struct {
					Branch struct {
						UpdatedAt string `json:"updated_at"`
					} `json:"branch"`
				} `json:"node"`
			} `json:"edges"`
		} `json:"FylgjaWaypoint"`
	}
	if err := json.Unmarshal(raw, &r); err != nil || len(r.W.Edges) != 1 {
		t.Fatalf("reading %s/%d back: %v (%s)", series, sequence, err, raw)
	}
	return r.W.Edges[0].Node.Branch.UpdatedAt
}

// compiled is one read and compile of a reference on the stage pipelines twin create runs.
type compiled struct {
	id    string
	files map[string][]byte
}

func readAndCompile(t *testing.T, reg *psp.Registry, what, branch, at string) compiled {
	t.Helper()
	snapshot, list, err := stage.Read(t.Context(), branch, at, reg, time.Now().UTC().Format(stage.ObservedAtFormat))
	if err != nil {
		t.Fatalf("%s: reading %s at %q: %v", what, branch, at, err)
	}
	if list.Rejected() {
		t.Fatalf("%s: reading %s at %q was rejected: %v", what, branch, at, list)
	}
	files, id, list := stage.Compile(snapshot, reg)
	if list.Rejected() {
		t.Fatalf("%s: compiling %s at %q was rejected: %v", what, branch, at, list)
	}
	return compiled{id: id, files: files}
}

// A waypoint resolves like --at: an unwritten at is its branch attribute's updated_at,
// verbatim, and a read and compile of the resolved reference is byte for byte the read and
// compile of --at that value. The chapter is sealed: after a change to the branch the
// waypoint resolves to the same at and the same bundle_id, while the branch head moved.
// The resolution is the product's, through
// intent.WaypointReader on the unnamed default-branch endpoints; the harness wrote the
// waypoint on /graphql/main.
func TestWaypointResolvesLikeAt(t *testing.T) {
	c, name := seriesBranch(t)
	if err := c.LoadSchema(name, filepath.Join("..", "..", "schema")); err != nil {
		t.Fatalf("loading schema: %v", err)
	}
	if err := c.SeedThreeNode(name); err != nil {
		t.Fatalf("seeding: %v", err)
	}
	// Written last, after the seed's writes and its generate: the one rule.
	if _, err := c.WriteWaypoint(name, 1, name, "", "seeded"); err != nil {
		t.Fatalf("writing %s/1: %v", name, err)
	}
	t.Logf("branch and series %s", name)

	reader, err := intent.WaypointReaderFromEnv()
	if err != nil {
		t.Fatal(err)
	}
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	ref := Ref{Series: name, Sequence: 1}
	resolve := func(what string) Resolved {
		t.Helper()
		res, list, err := Resolve(t.Context(), reader, ref, time.Now().UTC())
		if err != nil || len(list) > 0 {
			t.Fatalf("%s: resolving %s: %v %v", what, ref, err, list)
		}
		return res
	}

	first := resolve("the first resolution")
	want := writtenAt(t, c, name, 1)
	if first.Branch != name || first.At != want || first.AtSource != AtWritten || first.Description != "seeded" {
		t.Fatalf("resolved %+v; want branch %s at %s (written), verbatim", first, name, want)
	}
	byWaypoint := readAndCompile(t, reg, "the waypoint", first.Branch, first.At)
	byAt := readAndCompile(t, reg, "--at", name, want)
	if byWaypoint.id != byAt.id || !maps.EqualFunc(byWaypoint.files, byAt.files, bytes.Equal) {
		t.Errorf("the waypoint compiles to %s and --at %s to %s, or their files differ (%v, %v)",
			byWaypoint.id, want, byAt.id, slices.Sorted(maps.Keys(byWaypoint.files)), slices.Sorted(maps.Keys(byAt.files)))
	}

	before := checksums(t, c, name)
	if err := c.SeedThirdLink(name); err != nil {
		t.Fatalf("changing the branch: %v", err)
	}
	// A generate returns before an intent change's rewrite lands: the second
	// waypoint is written only once n1's and n3's artifacts have moved.
	awaitMoved(t, c, name, before, "n1", "n3")
	again := resolve("the resolution after the change")
	if again.At != first.At || again.Branch != first.Branch || again.AtSource != AtWritten {
		t.Errorf("after the change %s resolves to %+v, want %+v: a waypoint's at does not follow its branch", ref, again, first)
	}
	sealed := readAndCompile(t, reg, "the waypoint after the change", again.Branch, again.At)
	if sealed.id != byWaypoint.id {
		t.Errorf("after the change %s compiles to %s, want the sealed %s", ref, sealed.id, byWaypoint.id)
	}
	if head := readAndCompile(t, reg, "the branch head", name, ""); head.id == byWaypoint.id {
		t.Errorf("the branch head compiles to the waypoint's %s: the change did not land, so the proof proved nothing", head.id)
	}

	t.Logf("%s: at %s (written), bundle_id %s", ref, first.At, byWaypoint.id)

	// The plan of the series, once a second waypoint seals the change: two ids, and the one
	// step between them naming the link added and both ends' artifacts and bootstraps; each
	// id the one the waypoint's own reference reads and compiles to.
	t.Run("Plan", func(t *testing.T) {
		if _, err := c.WriteWaypoint(name, 2, name, "", "third link"); err != nil {
			t.Fatalf("writing %s/2: %v", name, err)
		}
		store := bundle.NewDirStore(filepath.Join(t.TempDir(), "bundles"))
		scratch := t.TempDir()
		var filed []string
		file := func(ctx context.Context, files map[string][]byte, id string, _ *ctm.CTM) (findings.List, error) {
			stored, err := bundle.PutFiles(ctx, store, files, scratch)
			if err == nil && stored != id {
				err = fmt.Errorf("bundle %s was stored as %s", id, stored)
			}
			filed = append(filed, id)
			return nil, err
		}
		started := time.Now()
		res, err := Plan(t.Context(), reader, name, reg, NewStages(file), time.Now().UTC(), nil, nil, nil)
		if err != nil {
			t.Fatalf("planning %s: %v", name, err)
		}
		t.Logf("planned %s in %.1fs", name, time.Since(started).Seconds())
		if len(res.Waypoints) != 2 || len(res.Steps) != 1 || len(res.Findings) != 0 {
			t.Fatalf("plan of %s: %d waypoints, %d steps, findings %v", name, len(res.Waypoints), len(res.Steps), res.Findings)
		}
		var ids []string
		for _, w := range res.Waypoints {
			if w.Status != PlanCompiled || w.Resolved == nil || w.Bundle == nil {
				t.Fatalf("%s: %s %s", w.Ref, w.Status, w.Rule)
			}
			if w.Resolved.AtSource != AtWritten || w.Resolved.At != writtenAt(t, c, name, w.Ref.Sequence) {
				t.Errorf("%s resolved to %s (%s), want its branch attribute's updated_at (written)", w.Ref, w.Resolved.At, w.Resolved.AtSource)
			}
			own := readAndCompile(t, reg, w.Ref.String(), w.Resolved.Branch, w.Resolved.At)
			if w.Bundle.ID != own.id || !maps.EqualFunc(w.Bundle.Files, own.files, bytes.Equal) {
				t.Errorf("%s planned to %s; its reference reads and compiles to %s", w.Ref, w.Bundle.ID, own.id)
			}
			ids = append(ids, w.Bundle.ID)
		}
		if ids[0] != byWaypoint.id || ids[0] == ids[1] || !slices.Equal(filed, ids) {
			t.Errorf("ids %v, filed %v; want %s first, a second that differs, each filed", ids, filed, byWaypoint.id)
		}

		s := res.Steps[0].Step
		if s == nil || s.Unchanged {
			t.Fatalf("the step %s/1 → %s/2 is %+v; want the change", name, name, res.Steps[0])
		}
		var changed, artifacts []string
		for _, n := range s.NodesChanged {
			changed = append(changed, n.Node)
			if !slices.Contains(n.Reasons, "bootstrap") {
				t.Errorf("%s changed for %v; want its bootstrap among them", n.Node, n.Reasons)
			}
		}
		for _, a := range s.ArtifactsChanged {
			artifacts = append(artifacts, a.Node)
			if a.From == a.To || a.From != before[a.Node] {
				t.Errorf("%s's artifact %s → %s; want it moved from %s", a.Node, a.From, a.To, before[a.Node])
			}
		}
		if len(s.LinksAdded) != 1 || len(s.LinksRemoved) != 0 || len(s.NodesAdded)+len(s.NodesRemoved) != 0 ||
			!slices.Equal(changed, []string{"n1", "n3"}) || !slices.Equal(artifacts, []string{"n1", "n3"}) {
			t.Errorf("the step is %+v; want one link added, n1 and n3 changed and their artifacts moved, nothing else", s)
		}
		t.Logf("%s/1 → %s/2: %s", name, name, res.Steps[0].Text())
	})
}

// The kind ships, loads and constrains. With the kind on the default branch, the seed's
// schema load on a throwaway branch is an empty diff: the branch's schema hash does not move. That
// branch's schema endpoint reports the kind branch-agnostic with its uniqueness
// constraint. A waypoint the harness writes through the throwaway branch's GraphQL is read
// by the product's reader on the unnamed endpoint, the same object; a second of its
// sequence written through the default branch's is refused by Infrahub naming the
// constraint; and deleting the series leaves none the product can see.
func TestWaypointKindLoads(t *testing.T) {
	c, name := seriesBranch(t)
	before := schemaHash(t, c, name)
	if err := c.LoadSchema(name, filepath.Join("..", "..", "schema")); err != nil {
		t.Fatalf("loading schema: %v", err)
	}
	if after := schemaHash(t, c, name); after != before {
		t.Errorf("loading schema/*.yaml on %s moved its schema hash %s → %s; with the kind on the default branch the load is an empty diff",
			name, before, after)
	}
	t.Logf("branch and series %s, schema hash %s (the default branch's %s)", name, before, schemaHash(t, c, ""))

	var schema struct {
		Nodes []struct {
			Kind                  string     `json:"kind"`
			Branch                string     `json:"branch"`
			UniquenessConstraints [][]string `json:"uniqueness_constraints"`
		} `json:"nodes"`
	}
	getJSON(t, c, "/api/schema?branch="+name, &schema)
	found := false
	for _, n := range schema.Nodes {
		if n.Kind != intent.WaypointKind {
			continue
		}
		found = true
		if n.Branch != "agnostic" || !slices.EqualFunc(n.UniquenessConstraints, [][]string{{"series__value", "sequence__value"}}, slices.Equal) {
			t.Errorf("%s on %s: branch %q, uniqueness %v; want agnostic, [[series__value sequence__value]]",
				n.Kind, name, n.Branch, n.UniquenessConstraints)
		}
	}
	if !found {
		t.Fatalf("%s's schema endpoint lists no %s", name, intent.WaypointKind)
	}

	// Written through the throwaway branch's GraphQL; the product names no branch at all.
	raw, err := c.GraphQL(name, fmt.Sprintf(`mutation { FylgjaWaypointCreate(data: {series: {value: %q}, `+
		`sequence: {value: 2}, branch: {value: %q}, description: {value: "from the branch"}}) { ok object { id } } }`, name, name))
	if err != nil {
		t.Fatalf("writing %s/2 through /graphql/%s: %v", name, name, err)
	}
	var created struct {
		Create struct {
			Object struct {
				ID string `json:"id"`
			} `json:"object"`
		} `json:"FylgjaWaypointCreate"`
	}
	if err := json.Unmarshal(raw, &created); err != nil || created.Create.Object.ID == "" {
		t.Fatalf("writing %s/2: %v (%s)", name, err, raw)
	}
	reader, err := intent.WaypointReaderFromEnv()
	if err != nil {
		t.Fatal(err)
	}
	mine := func() []intent.Waypoint {
		t.Helper()
		all, err := reader.List(t.Context())
		if err != nil {
			t.Fatalf("the product's reader: %v", err)
		}
		var out []intent.Waypoint
		for _, w := range all {
			if w.Series == name {
				out = append(out, w)
			}
		}
		return out
	}
	if got := mine(); len(got) != 1 || got[0].ID != created.Create.Object.ID || got[0].Sequence != 2 ||
		got[0].Branch != name || got[0].Description != "from the branch" {
		t.Errorf("the product reads %+v; want the one waypoint written through %s, id %s", got, name, created.Create.Object.ID)
	}

	// The constraint holds across branches: the same sequence again, through the default
	// branch, is refused and nothing is created.
	if _, err := c.WriteWaypoint(name, 2, name, "", "again"); err == nil || !strings.Contains(err.Error(), "uniqueness constraint") {
		t.Errorf("a second %s/2 was not refused naming the uniqueness constraint: %v", name, err)
	}
	if got := mine(); len(got) != 1 {
		t.Errorf("after the refused write the product reads %d waypoints of %s, want 1", len(got), name)
	}

	n, err := c.DeleteWaypointSeries(name)
	if err != nil || n != 1 {
		t.Fatalf("deleting series %s: %d, %v", name, n, err)
	}
	if got := mine(); len(got) != 0 {
		t.Errorf("after the series was deleted the product still reads %+v", got)
	}
}

// schemaHash is a branch's schema hash as GET /api/schema/summary gives it, under the key
// main whatever the branch (CLAUDE.md, verified 2026-09-14); "" is the default branch.
func schemaHash(t *testing.T, c *testsupport.Client, branch string) string {
	t.Helper()
	path := "/api/schema/summary"
	if branch != "" {
		path += "?branch=" + branch
	}
	var summary struct {
		Main string `json:"main"`
	}
	getJSON(t, c, path, &summary)
	if summary.Main == "" {
		t.Fatalf("%s gave no schema hash", path)
	}
	return summary.Main
}

// getJSON reads one of Infrahub's REST endpoints into v. Nothing of the request is logged:
// it carries the credential.
func getJSON(t *testing.T, c *testsupport.Client, path string, v any) {
	t.Helper()
	req, err := http.NewRequestWithContext(t.Context(), http.MethodGet, c.Address+path, nil)
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("X-INFRAHUB-KEY", c.Token)
	resp, err := c.HTTP.Do(req)
	if err != nil {
		t.Fatalf("GET %s: %v", path, err)
	}
	defer func() { _ = resp.Body.Close() }()
	body, err := io.ReadAll(resp.Body)
	if err != nil || resp.StatusCode != http.StatusOK {
		t.Fatalf("GET %s: HTTP %d, %v", path, resp.StatusCode, err)
	}
	if err := json.Unmarshal(body, v); err != nil {
		t.Fatalf("GET %s: %v", path, err)
	}
}

// checksums is each device's device-config checksum on branch, as Infrahub lists it now.
func checksums(t *testing.T, c *testsupport.Client, branch string) map[string]string {
	t.Helper()
	raw, err := c.GraphQL(branch, `{ FylgjaDevice { edges { node { name { value }
		... on CoreArtifactTarget { artifacts { edges { node { status { value } checksum { value }
			definition { node { ... on CoreArtifactDefinition { artifact_name { value } } } } } } } } } } } }`)
	if err != nil {
		t.Fatalf("asking Infrahub for the artifacts on %s: %v", branch, err)
	}
	type value struct {
		Value string `json:"value"`
	}
	var data struct {
		FylgjaDevice struct {
			Edges []struct {
				Node struct {
					Name      value `json:"name"`
					Artifacts struct {
						Edges []struct {
							Node struct {
								Status     value `json:"status"`
								Checksum   value `json:"checksum"`
								Definition struct {
									Node struct {
										ArtifactName value `json:"artifact_name"`
									} `json:"node"`
								} `json:"definition"`
							} `json:"node"`
						} `json:"edges"`
					} `json:"artifacts"`
				} `json:"node"`
			} `json:"edges"`
		} `json:"FylgjaDevice"`
	}
	if err := json.Unmarshal(raw, &data); err != nil {
		t.Fatal(err)
	}
	out := map[string]string{}
	for _, d := range data.FylgjaDevice.Edges {
		for _, a := range d.Node.Artifacts.Edges {
			if a.Node.Definition.Node.ArtifactName.Value == "device-config" && a.Node.Status.Value == intent.StatusReady {
				out[d.Node.Name.Value] = a.Node.Checksum.Value
			}
		}
	}
	return out
}

// awaitMoved polls until each named device's artifact is Ready with a checksum other than
// before's, as scripts/e2e.sh's await_checksums_moved does.
func awaitMoved(t *testing.T, c *testsupport.Client, branch string, before map[string]string, devices ...string) {
	t.Helper()
	deadline := time.Now().Add(90 * time.Second)
	for {
		now := checksums(t, c, branch)
		moved := true
		for _, d := range devices {
			if now[d] == "" || now[d] == before[d] {
				moved = false
			}
		}
		if moved {
			return
		}
		if time.Now().After(deadline) {
			t.Fatalf("the artifacts of %v on %s did not move from %v: %v", devices, branch, before, now)
		}
		time.Sleep(time.Second)
	}
}
