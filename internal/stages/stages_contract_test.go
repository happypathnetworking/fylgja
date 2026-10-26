//go:build contract

package stages

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
	"github.com/happypathnetworking/fylgja/internal/stage"
	"github.com/happypathnetworking/fylgja/internal/testsupport"
)

// Contract tests run against a real Infrahub, never a fake (D-017). The stage kind and its
// extension must be on the default branch (prerequisites; contracts/stage-kind.md). Each
// test proposes from a throwaway branch of its own and deletes, when it ends, the stages,
// the proposed changes and the branch, in that order (research §2.3). Boot no twin while
// they run.
//
//	set -a; . local/.env; set +a; go test -count=1 -tags contract ./internal/stages/ -v

// harness returns a write-capable client, skipping when no Infrahub is configured.
func harness(t *testing.T) *testsupport.Client {
	t.Helper()
	c, err := testsupport.NewClient()
	if err != nil {
		t.Skipf("contract tests need a running Infrahub: %v", err)
	}
	return c
}

// testBranch makes a branch fylgja-test-st-<ts>-<n>. When the test ends, each stage of
// each proposed change whose source it is goes, then those proposed changes, then the
// branch: Infrahub refuses a proposed change's delete while a stage names it, and a
// branch deleted first cancels its open proposed change. Then nothing the test made may
// be left: the branch, its proposed changes, and each stage collected before the deletion
// by id, so the check is of the test's own objects, the package's tests sharing Infrahub
// (SC-006). The durable fylgja-fixture branch is never written.
func testBranch(t *testing.T, c *testsupport.Client) string {
	t.Helper()
	name := fmt.Sprintf("%sst-%d-%d", testsupport.TestBranchPrefix, time.Now().Unix(), rand.Intn(9999))
	if err := c.CreateBranch(name); err != nil {
		t.Fatalf("creating branch: %v", err)
	}
	t.Cleanup(func() {
		var made []string
		if pcs, err := c.ProposedChangesOf(name); err != nil {
			t.Errorf("listing the proposed changes on %s before deleting them: %v", name, err)
		} else {
			for _, p := range pcs {
				rows, err := c.StagesOf(p.ID)
				if err != nil {
					t.Errorf("listing proposed change %s's stages before deleting them: %v", p.ID, err)
				}
				for _, r := range rows {
					made = append(made, r.ID)
				}
			}
		}
		// The reads that check the deletion see what is there before it, so their
		// silence after it is the deletion's.
		if exists, err := c.BranchExists(name); err != nil || !exists {
			t.Errorf("before the deletion branch %s exists: %t (%v)", name, exists, err)
		}
		if present, err := c.StagesPresent(made); err != nil || len(present) != len(made) {
			t.Errorf("before the deletion %d of the %d stages made on %s read (%v)", len(present), len(made), name, err)
		}
		stages, proposed, err := c.DeleteTestBranchCounting(name)
		if err != nil {
			t.Errorf("could not delete branch %s and what hangs on it (%d stage(s), %d proposed change(s) deleted): %v",
				name, stages, proposed, err)
			return
		}
		t.Logf("deleted %d stage(s), %d proposed change(s), branch %s", stages, proposed, name)
		if exists, err := c.BranchExists(name); err != nil || exists {
			t.Errorf("after the deletion branch %s exists: %t (%v)", name, exists, err)
		}
		if left, err := c.ProposedChangesOf(name); err != nil || len(left) != 0 {
			t.Errorf("after the deletion the proposed changes on %s are %+v (%v); want none", name, left, err)
		}
		if left, err := c.StagesPresent(made); err != nil || len(left) != 0 {
			t.Errorf("after the deletion the stages %v of the %d made on %s are still read (%v); want none", left, len(made), name, err)
		}
	})
	return name
}

// throwaway is testBranch with the schema loaded, and the three-node fixture seeded when
// seeded is set.
func throwaway(t *testing.T, c *testsupport.Client, seeded bool) string {
	t.Helper()
	name := testBranch(t, c)
	if err := c.LoadSchema(name, filepath.Join("..", "..", "schema")); err != nil {
		t.Fatalf("loading schema: %v", err)
	}
	if seeded {
		if err := c.SeedThreeNode(name); err != nil {
			t.Fatalf("seeding: %v", err)
		}
	}
	return name
}

// propose opens a draft proposed change from branch into main and waits for its pipeline,
// which renders the branch's artifacts (research §2.4).
func propose(t *testing.T, c *testsupport.Client, branch string) string {
	t.Helper()
	started := time.Now()
	id, err := c.OpenProposedChange(branch, true)
	if err != nil {
		t.Fatalf("opening a proposed change on %s: %v", branch, err)
	}
	t.Logf("proposed change %s on %s, its pipeline concluded after %.0fs", id, branch, time.Since(started).Seconds())
	return id
}

// markStage writes a stage on the default branch's GraphQL and returns its label's
// updated_at, the harness's own read of its write stamp.
func markStage(t *testing.T, c *testsupport.Client, id, label, at, description string) string {
	t.Helper()
	_, stamp, err := c.MarkStage(id, label, at, description)
	if err != nil {
		t.Fatalf("marking %s: %v", label, err)
	}
	return stamp
}

// liveStamper is the Stamper the server builds: an intent client per (branch, at), on the
// address and credential of the process environment.
type liveStamper struct{}

func (liveStamper) Stamps(ctx context.Context, branch, at, scope string) (intent.Stamps, error) {
	cfg, err := intent.FromEnv(branch, at)
	if err != nil {
		return intent.Stamps{}, err
	}
	cfg.Scope = intent.ScopeTag(scope)
	return intent.New(cfg).Stamps(ctx)
}

// stageReader is the product's reader, on the unnamed default-branch endpoints.
func stageReader(t *testing.T) *intent.StageReader {
	t.Helper()
	r, err := intent.StageReaderFromEnv()
	if err != nil {
		t.Fatal(err)
	}
	return r
}

// filing is the plan's pipeline, filing each bundle in a store under the test's temporary
// directory, as the dry run files them; it keeps each filed bundle's CTM by id.
func filing(t *testing.T) (Pipeline, map[string]*ctm.CTM) {
	t.Helper()
	store := bundle.NewDirStore(filepath.Join(t.TempDir(), "bundles"))
	scratch := t.TempDir()
	filed := map[string]*ctm.CTM{}
	return NewPipeline(func(ctx context.Context, files map[string][]byte, id string, snapshot *ctm.CTM) (findings.List, error) {
		stored, err := bundle.PutFiles(ctx, store, files, scratch)
		if err == nil && stored != id {
			err = fmt.Errorf("bundle %s was stored as %s", id, stored)
		}
		filed[id] = snapshot
		return nil, err
	}), filed
}

// planOf plans branch's proposed change through the product's reader and the live stamper.
func planOf(t *testing.T, branch string, p Pipeline) *PlanResult {
	t.Helper()
	started := time.Now()
	res, err := Plan(t.Context(), stageReader(t), liveStamper{}, branch, testScope, registry(t), p, time.Now().UTC(), nil, nil, nil)
	if err != nil {
		t.Fatalf("planning %s: %v", branch, err)
	}
	t.Logf("planned %s in %.1fs: %d stage(s), %d step(s)", branch, time.Since(started).Seconds(), len(res.Stages), len(res.Steps))
	return res
}

// outcome is one planned stage as far as it got: its label, status and first rejection.
type outcome struct{ label, status, rule string }

func outcomes(res *PlanResult) []outcome {
	out := make([]outcome, len(res.Stages))
	for i, st := range res.Stages {
		out[i] = outcome{st.Label, st.Status, st.Rule}
	}
	return out
}

// refused asserts list's rejections are each of rule at step resolve, on exactly objects in
// that order, and returns their messages.
func refused(t *testing.T, what string, list findings.List, rule string, objects ...string) []string {
	t.Helper()
	var got, messages []string
	for _, f := range list {
		if f.Severity != findings.Rejection {
			continue
		}
		if f.Rule != rule || f.Step != findings.StepResolve {
			t.Errorf("%s: %s at step %q on %s (%s); want %s at %s", what, f.Rule, f.Step, f.Object, f.Message, rule, findings.StepResolve)
			continue
		}
		got = append(got, f.Object)
		messages = append(messages, f.Message)
	}
	if !slices.Equal(got, objects) {
		t.Errorf("%s: %s names %v, want %v", what, rule, got, objects)
	}
	return messages
}

// The kind is on the default branch with its three attributes, its relationship and the
// extension, the waypoint kind it replaced is not (D-045), and the product's reader
// accepts it. With the kind and the schema library there (017 R-14), the seed's schema
// load on a throwaway branch is an empty diff. A stage the harness marks through the
// default branch's GraphQL is read by the product's reader with its proposed change; a
// second of its label on the same proposed change, written through the throwaway branch's
// GraphQL, is refused by Infrahub naming the uniqueness constraint, and a label holding a
// '/' by the regex. Deleting the stages leaves none the product can see.
func TestStageKindLoads(t *testing.T) {
	c := harness(t)
	reader := stageReader(t)
	if err := reader.Check(t.Context()); err != nil {
		t.Fatalf("the product's reader refuses the default branch's schema: %v", err)
	}

	var schema struct {
		Nodes []struct {
			Kind       string `json:"kind"`
			Branch     string `json:"branch"`
			Attributes []struct {
				Name     string `json:"name"`
				Kind     string `json:"kind"`
				Optional bool   `json:"optional"`
				Regex    string `json:"regex"`
			} `json:"attributes"`
			Relationships []struct {
				Name        string `json:"name"`
				Peer        string `json:"peer"`
				Cardinality string `json:"cardinality"`
				Optional    bool   `json:"optional"`
			} `json:"relationships"`
			UniquenessConstraints [][]string `json:"uniqueness_constraints"`
		} `json:"nodes"`
	}
	getJSON(t, c, "/api/schema?branch=main", &schema)
	var stageFound, extensionFound bool
	for _, n := range schema.Nodes {
		switch n.Kind {
		case intent.StageKind:
			stageFound = true
			if n.Branch != "agnostic" || !slices.EqualFunc(n.UniquenessConstraints, [][]string{{"proposed_change", "label__value"}}, slices.Equal) {
				t.Errorf("%s on main: branch %q, uniqueness %v; want agnostic, [[proposed_change label__value]]",
					n.Kind, n.Branch, n.UniquenessConstraints)
			}
			attrs := map[string]string{}
			for _, a := range n.Attributes {
				attrs[a.Name] = fmt.Sprintf("%s optional=%t regex=%q", a.Kind, a.Optional, a.Regex)
			}
			want := map[string]string{
				"label":       fmt.Sprintf("Text optional=false regex=%q", LabelPattern),
				"as_of":       `DateTime optional=true regex=""`,
				"description": `Text optional=true regex=""`,
			}
			if !maps.Equal(attrs, want) {
				t.Errorf("%s's attributes on main are %v, want %v", n.Kind, attrs, want)
			}
			var rels []string
			for _, r := range n.Relationships {
				if r.Name == intent.StageRelationship {
					rels = append(rels, fmt.Sprintf("%s %s optional=%t", r.Peer, r.Cardinality, r.Optional))
				}
			}
			if !slices.Equal(rels, []string{intent.ProposedChangeKind + " one optional=false"}) {
				t.Errorf("%s's %s on main is %v, want one required %s", n.Kind, intent.StageRelationship, rels, intent.ProposedChangeKind)
			}
		case "FylgjaWaypoint":
			t.Errorf("main's schema still lists %s; 014 removes it (specs/014-proposed-change-stages/migration/fylgja-waypoint-absent.yaml)", n.Kind)
		case intent.ProposedChangeKind:
			for _, r := range n.Relationships {
				if r.Name == intent.StageExtension {
					extensionFound = true
					if r.Peer != intent.StageKind || r.Cardinality != "many" {
						t.Errorf("%s.%s on main: peer %s, cardinality %s; want %s, many", n.Kind, r.Name, r.Peer, r.Cardinality, intent.StageKind)
					}
				}
			}
		}
	}
	if !stageFound || !extensionFound {
		t.Fatalf("main's schema lists %s %t, %s.%s %t; want both", intent.StageKind, stageFound,
			intent.ProposedChangeKind, intent.StageExtension, extensionFound)
	}

	// The schema load on a branch made from main moves nothing: the library and the kind are
	// main's.
	name := testBranch(t, c)
	before := schemaHash(t, c, name)
	if err := c.LoadSchema(name, filepath.Join("..", "..", "schema")); err != nil {
		t.Fatalf("loading schema: %v", err)
	}
	if after := schemaHash(t, c, name); after != before {
		t.Errorf("loading schema/ on %s moved its schema hash %s → %s; with the library and the kind on the default branch the load is an empty diff",
			name, before, after)
	}
	t.Logf("branch %s, schema hash %s (the default branch's %s)", name, before, schemaHash(t, c, ""))

	id := propose(t, c, name)
	stamp := markStage(t, c, id, "seeded", "", "from the harness")

	mine := func(branch string) []intent.ProposedChange {
		t.Helper()
		all, err := reader.ProposedChanges(t.Context(), branch)
		if err != nil {
			t.Fatalf("the product's reader: %v", err)
		}
		var out []intent.ProposedChange
		for _, pc := range all {
			if pc.Branch == name {
				out = append(out, pc)
			}
		}
		return out
	}
	pcs := mine(name)
	if len(pcs) != 1 || pcs[0].ID != id || pcs[0].Name != name || pcs[0].Destination != "main" || pcs[0].State != "open" || !pcs[0].Draft {
		t.Fatalf("the product reads %+v on %s; want the one open draft proposed change %s into main", pcs, name, id)
	}
	if st := pcs[0].Stages; len(st) != 1 || st[0].Label != "seeded" || st[0].LabelWrittenAt != stamp || st[0].At != nil ||
		st[0].Description != "from the harness" {
		t.Errorf("the product reads the stages %+v; want seeded, written at %s, no as_of", st, stamp)
	}
	// An empty filter is no filter (research §8.5): every open proposed change, this one among them.
	if every := mine(""); len(every) != 1 || every[0].ID != id {
		t.Errorf("listing every open proposed change, the product reads %+v of %s; want %s", every, name, id)
	}
	branchedFrom, createdAt := branchOrigin(t, c, name)
	if info, err := reader.Branch(t.Context(), name); err != nil || info == nil || info.BranchedFrom != branchedFrom || info.CreatedAt != createdAt {
		t.Errorf("the product reads branch %s as %+v (%v); want branched_from %s, created_at %s", name, info, err, branchedFrom, createdAt)
	}
	absent := name + "-absent"
	if info, err := reader.Branch(t.Context(), absent); err != nil || info != nil {
		t.Errorf("the product reads the absent branch %s as %+v (%v); want nothing", absent, info, err)
	}

	// One label per proposed change, across branches: the same label again, through the
	// throwaway branch's GraphQL, is refused at the write.
	_, err := c.GraphQL(name, fmt.Sprintf(`mutation { FylgjaStageCreate(data: {label: {value: "seeded"}, `+
		`proposed_change: {id: %q}}) { ok object { id } } }`, id))
	if err == nil || !strings.Contains(err.Error(), "uniqueness constraint") {
		t.Errorf("a second stage seeded on %s through /graphql/%s was not refused naming the uniqueness constraint: %v", id, name, err)
	}
	if _, _, err := c.MarkStage(id, "a/b", "", ""); err == nil || !strings.Contains(err.Error(), "regex") {
		t.Errorf("a stage labelled a/b was not refused naming the regex: %v", err)
	}
	if got := mine(name); len(got) != 1 || len(got[0].Stages) != 1 {
		t.Errorf("after the refused writes the product reads %+v; want the one stage", got)
	}

	n, err := c.DeleteStagesOf(id)
	if err != nil || n != 1 {
		t.Fatalf("deleting the stages of %s: %d, %v", id, n, err)
	}
	if got := mine(name); len(got) != 1 || len(got[0].Stages) != 0 {
		t.Errorf("after its stages were deleted the product reads %+v", got)
	}
	orphans, err := reader.Orphans(t.Context())
	if err != nil || len(orphans) != 0 {
		t.Errorf("after the stages were deleted the product reads the orphans %+v (%v); want none", orphans, err)
	}
}

// A proposed change with two marks lists and plans as four stages in order: the branch
// point, each mark at its own write stamp verbatim, and the head one microsecond after the
// branch's latest stamp. On this install's main, which holds no tagged device, the branch
// point is refused scope.empty and its step is not computed (017 R-20); the marks
// and the head compile to three ids, the step between the marks is the link added with n1
// and n3 changed, and the step to the head is unchanged. The mark's CTM is the read of
// --branch at its at, but for observed_at, and compiles to the same id (SC-002). Then the
// first mark is edited three times: a description edit leaves its at, and a twin built from
// it unmoved; a relabel leaves the old reference unknown and the new one at the relabel's
// write; an as_of of its first at gives that at back, given.
func TestStagesListAndPlan(t *testing.T) {
	c := harness(t)
	name := throwaway(t, c, true)
	id := propose(t, c, name)
	// Each mark written last, after the writes it seals and after their generate: the one
	// rule of schema/README.md.
	seededAt := markStage(t, c, id, "seeded", "", "seeded")
	before := checksums(t, c, name)
	if err := c.SeedThirdLink(name); err != nil {
		t.Fatalf("adding the third link: %v", err)
	}
	// A generate returns before an intent change's rewrite lands: the second mark is
	// written only once n1's and n3's artifacts have moved, as tier 3 awaits them.
	awaitMoved(t, c, name, before, "n1", "n3")
	thirdAt := markStage(t, c, id, "third-link", "", "third link")
	latest, err := c.ArtifactsReadyAt(name)
	if err != nil {
		t.Fatal(err)
	}
	branchedFrom, _ := branchOrigin(t, c, name)

	type row struct{ label, branch, at, source string }
	want := []row{
		{LabelBranchPoint, "main", branchedFrom, AtBranchPoint},
		{"seeded", name, seededAt, AtWritten},
		{"third-link", name, thirdAt, AtWritten},
		{LabelHead, name, "", AtHead},
	}
	// The head's at is computed: the instant after the branch's latest stamp, the
	// regeneration's checksum, compared as an instant.
	head := func(what, at string) {
		t.Helper()
		got, ok := ParseAt(at)
		if !ok || !got.Equal(latest.Add(time.Microsecond)) {
			t.Errorf("%s: the head's at is %s; want one microsecond after the latest checksum stamp %s", what,
				at, latest.Format(time.RFC3339Nano))
		}
	}

	listed, list, err := List(t.Context(), stageReader(t), liveStamper{}, name, testScope, nil)
	if err != nil {
		t.Fatalf("listing %s: %v", name, err)
	}
	if len(list) != 0 {
		t.Errorf("listing %s: findings %v; want none", name, list)
	}
	var rows []row
	for _, r := range listed.Rows {
		rows = append(rows, row{r.Label, r.Branch, r.At, r.AtSource})
		if r.ProposedChange.ID != id || r.Ref.Branch != name || r.Twin {
			t.Errorf("row %s: proposed change %s, ref %s, twin %t; want %s, %s/…, no twin", r.Label, r.ProposedChange.ID, r.Ref, r.Twin, id, name)
		}
	}
	if len(rows) == 4 {
		head("the list", rows[3].at)
		want[3].at = rows[3].at
	}
	if !slices.Equal(rows, want) {
		t.Fatalf("stage list %s:\n got %v\nwant %v", name, rows, want)
	}

	p, filed := filing(t)
	res := planOf(t, name, p)
	if got, wantOutcomes := outcomes(res), []outcome{
		{LabelBranchPoint, PlanRefused, findings.RuleScopeEmpty},
		{"seeded", PlanCompiled, ""},
		{"third-link", PlanCompiled, ""},
		{LabelHead, PlanCompiled, ""},
	}; !slices.Equal(got, wantOutcomes) {
		t.Fatalf("stage plan %s: %v, want %v (findings %v)", name, got, wantOutcomes, res.Findings)
	}
	if res.ProposedChange == nil || res.ProposedChange.ID != id || !res.ProposedChange.Draft {
		t.Errorf("the plan names the proposed change %+v, want the draft %s", res.ProposedChange, id)
	}
	var ids []string
	for i, st := range res.Stages[1:] {
		r := st.Resolved
		if r == nil || r.Branch != want[i+1].branch || r.At != want[i+1].at || r.AtSource != want[i+1].source {
			t.Errorf("%s planned at %+v; want what the list resolved, %v", st.Ref, r, want[i+1])
		}
		if len(st.Findings) != 0 {
			t.Errorf("%s compiled with findings %v; want none", st.Ref, st.Findings)
		}
		ids = append(ids, st.BundleID())
	}
	if distinct := slices.Compact(slices.Sorted(slices.Values(ids))); len(distinct) != 3 {
		t.Errorf("the three compiled stages have ids %v; want three distinct, the provenance differing", ids)
	}

	if len(res.Steps) != 3 {
		t.Fatalf("stage plan %s: %d steps, want 3", name, len(res.Steps))
	}
	if s := res.Steps[0]; s.Step != nil || !strings.Contains(s.Why, name+"/"+LabelBranchPoint) {
		t.Errorf("the step from the branch point is %+v; want not computed, naming it refused", s)
	}
	s := res.Steps[1].Step
	if s == nil || s.Unchanged {
		t.Fatalf("the step seeded → third-link is %+v; want the change", res.Steps[1])
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
	if last := res.Steps[2].Step; last == nil || !last.Unchanged {
		t.Errorf("the step third-link → head is %+v; want unchanged, the ids differing by provenance alone", res.Steps[2])
	}
	for _, pair := range res.Steps {
		t.Log(pair.Text())
	}

	// SC-002: the mark's reference reads the CTM --branch reads at its at, and compiles to
	// the id the plan printed.
	seeded := res.Stages[1]
	planned := filed[seeded.BundleID()]
	if planned == nil {
		t.Fatalf("%s's CTM was not filed", seeded.Ref)
	}
	byAt, list, err := stage.Read(t.Context(), name, seededAt, testScope, registry(t), time.Now().UTC().Format(stage.ObservedAtFormat))
	if err != nil || list.Rejected() {
		t.Fatalf("reading %s at %s: %v %v", name, seededAt, err, list)
	}
	if byAt.Envelope.At != seededAt || planned.Envelope.At != seededAt {
		t.Errorf("the envelopes' at are %q and %q; want %s verbatim", byAt.Envelope.At, planned.Envelope.At, seededAt)
	}
	same := *byAt
	same.Envelope.ObservedAt = planned.Envelope.ObservedAt
	a, _ := json.Marshal(planned)
	b, _ := json.Marshal(&same)
	if !bytes.Equal(a, b) {
		t.Errorf("the CTM %s plans from differs from --branch %s --at %s's but for observed_at", seeded.Ref, name, seededAt)
	}
	if _, byAtID, list := stage.Compile(byAt, registry(t)); list.Rejected() || byAtID != seeded.BundleID() {
		t.Errorf("--branch %s --at %s compiles to %s (%v); %s planned to %s", name, seededAt, byAtID, list, seeded.Ref, seeded.BundleID())
	}
	t.Logf("%s: at %s (written), bundle_id %s", seeded.Ref, seededAt, seeded.BundleID())

	// Editing the mark, the proposed change found again after each edit: a description edit
	// alone moves nothing a twin built from it holds, a relabel names its own write, and an
	// as_of written to the first at gives that at back.
	reader := stageReader(t)
	first := *seeded.Resolved
	record := RecordView{ProposedChange: RecordChange{ID: id, Branch: name}, Label: first.Label,
		Branch: first.Branch, At: first.At, AtSource: first.AtSource}
	edit := func(what string, fields map[string]any) *Change {
		t.Helper()
		if err := c.UpdateStage(first.ID, fields); err != nil {
			t.Fatalf("%s: %v", what, err)
		}
		ch, list, err := Find(t.Context(), reader, liveStamper{}, name, testScope)
		if err != nil || list != nil {
			t.Fatalf("finding %s's proposed change after %s: %v %v", name, what, err, list)
		}
		return ch
	}
	markOf := func(what string, ch *Change, label string) Stage {
		t.Helper()
		for _, st := range ch.Stages {
			if st.Mark != nil && st.ID == first.ID {
				if st.Label != label {
					t.Fatalf("after %s the mark %s is labelled %q; want %q", what, first.ID, st.Label, label)
				}
				t.Logf("after %s: %s at %s (%s), its label written at %s", what, st.Ref, st.At, st.AtSource, st.Mark.LabelWrittenAt)
				return st
			}
		}
		t.Fatalf("after %s the mark %s is not among %s's stages", what, first.ID, name)
		return Stage{}
	}

	ch := edit("a description edit", map[string]any{"description": "seeded, described again"})
	if st := markOf("a description edit", ch, "seeded"); st.At != first.At || st.AtSource != AtWritten ||
		st.Description != "seeded, described again" {
		t.Errorf("after a description edit %s is at %s (%s), described %q; want at %s (written) as before, described anew",
			st.Ref, st.At, st.AtSource, st.Description, first.At)
	}
	if moved := Moved(ch, record); len(moved) != 0 {
		t.Errorf("after a description edit the record's stage reads as moved: %v", moved)
	}

	ch = edit("a relabel", map[string]any{"label": "relabelled"})
	relabelled := markOf("a relabel", ch, "relabelled")
	if later, err := laterThan(relabelled.At, first.At); err != nil || !later || relabelled.AtSource != AtWritten {
		t.Errorf("after a relabel %s is at %s (%s); want written, later than %s (%v)", relabelled.Ref, relabelled.At,
			relabelled.AtSource, first.At, err)
	}
	if _, list, err := Resolve(t.Context(), reader, liveStamper{}, registry(t), first.Ref, testScope, time.Now().UTC()); err != nil {
		t.Fatalf("resolving %s after a relabel: %v", first.Ref, err)
	} else {
		refused(t, "the old reference after a relabel", list, findings.RuleStageUnknown, first.Ref.String())
	}
	moved := Moved(ch, record)
	if len(moved) != 1 || moved[0].Rule != findings.RuleStageTwinMoved || moved[0].Severity != findings.Warning ||
		!strings.Contains(moved[0].Message, first.Ref.String()+" no longer exists") {
		t.Errorf("after a relabel Moved files %v; want one stage.twin.moved warning saying %s no longer exists", moved, first.Ref)
	}

	ch = edit("an as_of edit", map[string]any{"as_of": first.At})
	if st := markOf("an as_of edit", ch, "relabelled"); st.At != first.At || st.AtSource != AtGiven {
		t.Errorf("after as_of was written %s, %s is at %s (%s); want %s (given)", first.At, st.Ref, st.At, st.AtSource, first.At)
	}
}

// The refusals tier 2 can make, on one proposed change in the order its story makes them.
// An intent change with no regenerate makes the mark after it stale on every device it
// moved, and a generate then a fresh mark plans; an edit the template does not render (the
// serial number, 017 R-15) leaves the mark stale through a generate that moves no checksum,
// and the proposed change's checks clear it (D-046). A rebase moves the branch point past every mark, each
// refused naming the rebase while the derived stages are still planned. A mark labelled
// head is refused as reserved, a given as_of in the future as unresolved; once the
// proposed change is closed its branch names no stage, nor does a branch that does not
// exist.
func TestStageRefusals(t *testing.T) {
	c := harness(t)
	name := throwaway(t, c, true)
	id := propose(t, c, name)
	reader := stageReader(t)
	devices := []string{"n1", "n2", "n3"}
	resolve := func(ref Ref) (Resolved, findings.List) {
		t.Helper()
		res, list, err := Resolve(t.Context(), reader, liveStamper{}, registry(t), ref, testScope, time.Now().UTC())
		if err != nil {
			t.Fatalf("resolving %s: %v", ref, err)
		}
		return res, list
	}
	fresh := func(label string) Resolved {
		t.Helper()
		res, list := resolve(Ref{Branch: name, Label: label})
		if len(list) != 0 {
			t.Fatalf("%s/%s: %v; want it resolved with no finding", name, label, list)
		}
		return res
	}
	stale := func(label string) {
		t.Helper()
		_, list := resolve(Ref{Branch: name, Label: label})
		for _, m := range refused(t, name+"/"+label, list, findings.RuleStageArtifactStale, devices...) {
			if !strings.Contains(m, remedy) {
				t.Errorf("%s/%s: %q names not both remedies", name, label, m)
			}
		}
	}

	// An intent change the artifact renders, with no generate: stale on each device.
	for _, d := range devices {
		if err := c.SetDeviceDescription(name, d, "stale-description"); err != nil {
			t.Fatal(err)
		}
	}
	markStage(t, c, id, "description-stale", "", "the description, not rendered")
	stale("description-stale")
	before := checksums(t, c, name)
	if err := c.GenerateArtifacts(name); err != nil {
		t.Fatal(err)
	}
	awaitMoved(t, c, name, before, devices...)
	markStage(t, c, id, "description-fresh", "", "the description, rendered")
	fresh("description-fresh")

	// The serial number, which the template does not print: a generate rewrites nothing,
	// so the checksums stay older than the edit, and only the proposed change's checks
	// clear it.
	for _, d := range devices {
		if err := c.SetDeviceSerial(name, d, "stale-serial"); err != nil {
			t.Fatal(err)
		}
	}
	markStage(t, c, id, "serial-stale", "", "")
	stale("serial-stale")
	before = checksums(t, c, name)
	if err := c.GenerateArtifacts(name); err != nil {
		t.Fatal(err)
	}
	if after := checksums(t, c, name); !maps.Equal(after, before) {
		t.Errorf("a generate after the serial number's edit moved the checksums %v → %v; the serial number renders nothing", before, after)
	}
	markStage(t, c, id, "serial-generated", "", "")
	stale("serial-generated")
	started := time.Now()
	completed, err := c.RunCheck(id, 180*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	t.Logf("the run-check's artifact validator completed at %s, %.0fs after the call", completed, time.Since(started).Seconds())
	if after := checksums(t, c, name); !maps.Equal(after, before) {
		t.Errorf("the run-check moved the checksums %v → %v; the bytes are identical", before, after)
	}
	markStage(t, c, id, "serial-checked", "", "")
	checked := fresh("serial-checked")
	if got, err := reader.Validations(t.Context(), id, checked.At); err != nil || got != completed {
		t.Errorf("the product reads the validation pinned at %s as %q (%v); want the run-check's %s", checked.At, got, err, completed)
	}

	p, _ := filing(t)
	res := planOf(t, name, p)
	if got, want := outcomes(res), []outcome{
		{LabelBranchPoint, PlanRefused, findings.RuleScopeEmpty},
		{"description-stale", PlanRefused, findings.RuleStageArtifactStale},
		{"description-fresh", PlanCompiled, ""},
		{"serial-stale", PlanRefused, findings.RuleStageArtifactStale},
		{"serial-generated", PlanRefused, findings.RuleStageArtifactStale},
		{"serial-checked", PlanCompiled, ""},
		{LabelHead, PlanCompiled, ""},
	}; !slices.Equal(got, want) {
		t.Errorf("stage plan %s before the rebase: %v, want %v", name, got, want)
	}
	for i, pair := range res.Steps {
		if computed := pair.Step != nil; computed != (res.Stages[i].Bundle != nil && res.Stages[i+1].Bundle != nil) {
			t.Errorf("%s computed %t; want a step only between two compiled stages", pair.Text(), computed)
		}
	}

	// A rebase moves branched_from to its own moment and leaves created_at: every mark
	// falls before the branch point, and the refusal says a rebase did it.
	marks := []string{"description-stale", "description-fresh", "serial-stale", "serial-generated", "serial-checked"}
	_, createdBefore := branchOrigin(t, c, name)
	started = time.Now()
	if err := c.Rebase(name); err != nil {
		t.Fatal(err)
	}
	branchedFrom, createdAt := branchOrigin(t, c, name)
	t.Logf("rebased %s in %.0fs: branched_from %s, created_at %s", name, time.Since(started).Seconds(), branchedFrom, createdAt)
	if createdAt != createdBefore {
		t.Errorf("the rebase moved created_at %s → %s", createdBefore, createdAt)
	}
	res = planOf(t, name, p)
	want := []outcome{{LabelBranchPoint, PlanRefused, findings.RuleScopeEmpty}}
	for _, m := range marks {
		want = append(want, outcome{m, PlanRefused, findings.RuleStageAtBeforeBranchPoint})
	}
	want = append(want, outcome{LabelHead, PlanCompiled, ""})
	if got := outcomes(res); !slices.Equal(got, want) {
		t.Errorf("stage plan %s after the rebase: %v, want %v", name, got, want)
	}
	for _, st := range res.Stages {
		if st.Rule != findings.RuleStageAtBeforeBranchPoint {
			continue
		}
		for _, m := range refused(t, st.Ref.String(), st.Findings, findings.RuleStageAtBeforeBranchPoint, st.Ref.String()) {
			if !strings.Contains(m, "a rebase at "+branchedFrom) || !strings.Contains(m, "(the branch was created at "+createdAt+")") {
				t.Errorf("%s: %q does not name the rebase at %s", st.Ref, m, branchedFrom)
			}
		}
	}

	// A mark labelled like a derived stage: Infrahub takes it, Fylgja refuses it.
	markStage(t, c, id, LabelHead, "", "")
	_, list := resolve(Ref{Branch: name, Label: LabelHead})
	refused(t, name+"/head", list, findings.RuleStageLabelReserved, name+"/"+LabelHead)

	// A given as_of later than the server's clock seals nothing yet.
	future := time.Now().Add(time.Hour).UTC().Format(nowLayout)
	markStage(t, c, id, "future", future, "")
	_, list = resolve(Ref{Branch: name, Label: "future"})
	for _, m := range refused(t, name+"/future", list, findings.RuleStageAtUnresolved, name+"/future") {
		if !strings.Contains(m, "later than the current time") {
			t.Errorf("%s/future: %q does not say it is in the future", name, m)
		}
	}

	// A label the open proposed change lacks names no stage of it; the refusal names its
	// stages in order: the branch point, the marks by their at (the one labelled head
	// shares the derived head's place), and the head.
	_, list = resolve(Ref{Branch: name, Label: "nosuch"})
	order := append(append([]string{LabelBranchPoint}, marks...), "future", LabelHead)
	for _, m := range refused(t, name+"/nosuch", list, findings.RuleStageUnknown, name+"/nosuch") {
		if want := fmt.Sprintf(`proposed change %q (%s) on branch %s has no stage "nosuch"; its stages are: %s`,
			name, id, name, strings.Join(order, ", ")); m != want {
			t.Errorf("%s/nosuch: %q\nwant %q", name, m, want)
		}
	}

	// Closed, the proposed change keeps its stages but its branch names none.
	if err := c.CloseProposedChange(id); err != nil {
		t.Fatal(err)
	}
	_, list = resolve(Ref{Branch: name, Label: "serial-checked"})
	for _, m := range refused(t, "after the close", list, findings.RuleStageUnknown, name) {
		if !strings.Contains(m, "no open proposed change has source branch "+name) {
			t.Errorf("after the close: %q", m)
		}
	}
	if res := planOf(t, name, p); len(res.Stages) != 0 || res.ProposedChange != nil {
		t.Errorf("stage plan %s after the close: %v; want refused whole", name, outcomes(res))
	} else {
		refused(t, "the plan after the close", res.Findings, findings.RuleStageUnknown, name)
	}

	absent := fmt.Sprintf("%sst-absent-%d", testsupport.TestBranchPrefix, time.Now().UnixNano())
	_, list = resolve(Ref{Branch: absent, Label: "seeded"})
	refused(t, "an unknown branch", list, findings.RuleStageUnknown, absent)
}

// SC-009 against the real Infrahub (017 research R-10, §5.8): after a fresh mark, each write
// on what a tagged device owns or reaches makes the next mark stale on every tagged device
// that reaches it, and on no other. The platform's description and the manufacturer's reach
// the three devices on them; the cable on n1:ethernet-1/1 re-ended to n1's port alone reaches
// n1 and n2, by the cable's event and its former port's, since no stamp moves; a virtual
// interface added to n1 reaches n1 alone. A write of cs1's own, an untagged device on the
// same platform, makes no mark stale. Only the re-ending renders differently, so the
// proposed change's checks clear each write before the next (D-046), and a mark after them
// is fresh. The virtual interface goes last: the template's query reads every interface, and
// the first generation to read a node moves its stamp (§5.8).
func TestStagesSeeEveryWriteOfADevice(t *testing.T) {
	c := harness(t)
	name := throwaway(t, c, true)
	// cs1 is outside the scope. Its creation on the platform moves the platform's stamp, and
	// so every tagged device's (§5.8): it is written before the proposed change, whose
	// pipeline's artifact validator completes after it.
	if _, err := c.AddDevice(name, testsupport.Device{Name: "cs1", Manufacturer: "Nokia", Platform: "SR Linux",
		Ports: []string{"mgmt0", "ethernet-1/1"}, Management: "mgmt0"}); err != nil {
		t.Fatal(err)
	}
	id := propose(t, c, name)
	reader := stageReader(t)
	resolve := func(label string) findings.List {
		t.Helper()
		_, list, err := Resolve(t.Context(), reader, liveStamper{}, registry(t), Ref{Branch: name, Label: label}, testScope, time.Now().UTC())
		if err != nil {
			t.Fatalf("resolving %s/%s: %v", name, label, err)
		}
		return list
	}
	fresh := func(label string) {
		t.Helper()
		if list := resolve(label); len(list) != 0 {
			t.Errorf("%s/%s: %v; want it fresh, with no finding", name, label, list)
		}
	}
	stale := func(label string, devices ...string) []string {
		t.Helper()
		messages := refused(t, name+"/"+label, resolve(label), findings.RuleStageArtifactStale, devices...)
		for _, m := range messages {
			if !strings.Contains(m, remedy) {
				t.Errorf("%s/%s: %q names not both remedies", name, label, m)
			}
		}
		return messages
	}
	// mark writes a mark after a write and judges it; then, when the write is not the last,
	// the proposed change's checks complete its artifact validator anew and a second mark
	// after them is fresh, so that the next write's mark is stale by that write alone.
	mark := func(label, what string, last bool, devices ...string) []string {
		t.Helper()
		markStage(t, c, id, label, "", what)
		messages := stale(label, devices...)
		if !last {
			started := time.Now()
			completed, err := c.RunCheck(id, 180*time.Second)
			if err != nil {
				t.Fatal(err)
			}
			t.Logf("after %s, the run-check's artifact validator completed at %s, %.0fs after the call", what, completed,
				time.Since(started).Seconds())
			markStage(t, c, id, label+"-checked", "", what+", checked")
			fresh(label + "-checked")
		}
		return messages
	}

	markStage(t, c, id, "seeded", "", "seeded")
	fresh("seeded")

	// cs1's own write: its node is no tagged device's, nor in any one's ids.
	if err := c.SetDeviceDescription(name, "cs1", "untagged-description"); err != nil {
		t.Fatal(err)
	}
	markStage(t, c, id, "untagged", "", "cs1 described")
	fresh("untagged")

	// The seed's platform and its manufacturer, which every device stands on.
	if err := c.SetPlatformDescription(name, "SR Linux", "described"); err != nil {
		t.Fatal(err)
	}
	mark("platform", "the platform described", false, "n1", "n2", "n3")
	if err := c.SetManufacturerDescription(name, "Nokia", "described"); err != nil {
		t.Fatal(err)
	}
	mark("manufacturer", "the manufacturer described", false, "n1", "n2", "n3")

	// The re-ending moves no stamp: the cable's event, and its former port's, land in the log
	// a few seconds after the write (§5.8), and the head passes the write by them alone. The
	// mark is written once it has, so that its at is after them.
	headOf := func() string {
		t.Helper()
		ch, list, err := Find(t.Context(), reader, liveStamper{}, name, testScope)
		if err != nil || list != nil {
			t.Fatalf("finding %s: %v %v", name, err, list)
		}
		head, _ := ch.first(LabelHead)
		return head.At
	}
	sent := time.Now().UTC()
	if err := c.ReEndCable(name, "n1", "ethernet-1/1", "n1:ethernet-1/1"); err != nil {
		t.Fatal(err)
	}
	for deadline := time.Now().Add(30 * time.Second); ; time.Sleep(250 * time.Millisecond) {
		if at, ok := ParseAt(headOf()); ok && at.After(sent) {
			t.Logf("the head passed the re-ending %.1fs after it was sent", time.Since(sent).Seconds())
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("the head has not passed the re-ending sent at %s 30 s after it; want it moved by the re-ending's events",
				sent.Format(time.RFC3339Nano))
		}
	}
	messages := mark("cable", "the cable re-ended", false, "n1", "n2")
	// n2 reaches the cable no more: its former port's id, which the events name, is how.
	if len(messages) == 2 && !strings.Contains(messages[1], "(Infrahub's event log: infrahub.node.") {
		t.Errorf("%s/cable: n2 is stale by %q; want the re-ending's event named", name, messages[1])
	}

	if err := c.AddVirtualInterface(name, "n1", "lo0"); err != nil {
		t.Fatal(err)
	}
	mark("virtual", "a virtual interface added to n1", true, "n1")
}

// D-048 against the real Infrahub: the cable n1:ethernet-1/1 — n2:ethernet-1/1 deleted, by
// DcimCableDelete, as the branch's latest write. Unlike NetworkLink's delete (014 research
// §8.17) and unlike a cable's re-ending (017 §5.8), it stamps its two end ports at its own
// write (017 §5.11), so n1's and n2's intent stamps and the branch's latest move to it and
// n3's does not. This test asserted D-048's premise, that the delete moves no stamp, until
// CI's contract job on c006bf9 found the ports stamped (017 T057); the premise check went,
// and the event read stays, since a re-ending is still stamped nowhere. The delete's events
// land after its stamp, so the head moves past the stamps' head by them. A stage marked
// after the delete, and the head, are refused stale for n1 and n2, naming the events, and
// for no other; a mark before it, after the query groups' churn that follows every
// generation, is fresh. A regenerate then clears the head, which reads two links, and
// leaves the mark after the delete stale: its artifacts are the ones it read.
func TestStagesSeeARemoval(t *testing.T) {
	c := harness(t)
	name := throwaway(t, c, true)
	id := propose(t, c, name)
	r := stageReader(t)
	headOf := func(what string) string {
		t.Helper()
		ch, list, err := Find(t.Context(), r, liveStamper{}, name, testScope)
		if err != nil || list != nil {
			t.Fatalf("%s: finding %s: %v %v", what, name, err, list)
		}
		head, _ := ch.first(LabelHead)
		return head.At
	}
	stamps := func() intent.Stamps {
		t.Helper()
		s, err := liveStamper{}.Stamps(t.Context(), name, "", testScope)
		if err != nil {
			t.Fatal(err)
		}
		return s
	}

	seededAt := markStage(t, c, id, "seeded", "", "before the delete")
	before, headBefore := stamps(), headOf("before the delete")
	sent := time.Now().UTC()
	returned, err := c.DeleteLink(name, "n1", "ethernet-1/1")
	if err != nil {
		t.Fatal(err)
	}
	t.Logf("seeded marked at %s; the delete sent at %s and returned at %s", seededAt,
		sent.Format(time.RFC3339Nano), returned.Format(time.RFC3339Nano))
	after := stamps()
	// The delete's own stamp, on its two end ports (017 §5.11): the branch's latest, and
	// n1's and n2's intent, move to it; n3 reaches neither port.
	latestBefore, errBefore := time.Parse(time.RFC3339Nano, before.Latest)
	latestAfter, errAfter := time.Parse(time.RFC3339Nano, after.Latest)
	if errBefore != nil || errAfter != nil || !latestAfter.After(latestBefore) {
		t.Errorf("the delete left the branch's latest stamp at %s (before it %s); want it moved to the delete's", after.Latest, before.Latest)
	}
	for _, d := range []string{"n1", "n2"} {
		if got := after.Devices[d].Intent; got != after.Latest {
			t.Errorf("after the delete %s's intent stamp is %s (before it %s); want the delete's, the branch's latest %s",
				d, got, before.Devices[d].Intent, after.Latest)
		}
	}
	if after.Devices["n3"].Intent != before.Devices["n3"].Intent {
		t.Errorf("the delete moved n3's intent stamp from %s to %s", before.Devices["n3"].Intent, after.Devices["n3"].Intent)
	}
	t.Logf("the delete stamped n1's and n2's ports at %s; the branch's latest was %s", after.Latest, before.Latest)
	// The delete's events are stamped about when it returns, later than its own stamp, and
	// land in the log after it, in under half a second on an idle host and over a second
	// under the tier's load (014 research §8.19): until they land the head is the stamps',
	// at the delete's stamp. Wait for the head to pass the stamps' head by the events and
	// settle, two reads a second apart agreeing.
	stampsHead, _ := HeadAt(after.Latest)
	stampsAt, _ := ParseAt(stampsHead)
	headAfter, deadline := headOf("after the delete"), time.Now().Add(30*time.Second)
	var passed time.Time
	for {
		if at, ok := ParseAt(headAfter); ok && at.After(sent) && at.After(stampsAt) {
			if passed.IsZero() {
				passed = time.Now()
				t.Logf("the head passed the delete at %s, %.1fs after it returned", headAfter, passed.Sub(returned).Seconds())
			}
			time.Sleep(time.Second)
			if again := headOf("again"); again == headAfter {
				break
			} else {
				headAfter = again
			}
		} else if time.Now().After(deadline) {
			t.Fatalf("the head is %s 30 s after the delete; want it past the stamps' head %s and the delete's send %s, "+
				"by the delete's events", headAfter, stampsHead, sent.Format(time.RFC3339Nano))
		} else {
			time.Sleep(250 * time.Millisecond)
			headAfter = headOf("after the delete")
		}
	}
	t.Logf("the head moved from %s past the delete to %s, %.1fs after it returned", headBefore, headAfter,
		time.Since(returned).Seconds())
	removedAt := markStage(t, c, id, "removed", "", "after the delete")
	t.Logf("removed marked at %s", removedAt)

	p, _ := filing(t)
	res := planOf(t, name, p)
	if got, want := outcomes(res), []outcome{
		{LabelBranchPoint, PlanRefused, findings.RuleScopeEmpty},
		{"seeded", PlanCompiled, ""},
		{"removed", PlanRefused, findings.RuleStageArtifactStale},
		{LabelHead, PlanRefused, findings.RuleStageArtifactStale},
	}; !slices.Equal(got, want) {
		t.Fatalf("stage plan %s: %v, want %v (findings %v)", name, got, want, res.Findings)
	}
	if links := res.Stages[1].Read.Counts.Links; links != 3 {
		t.Errorf("seeded read %d links, want 3", links)
	}
	for _, st := range res.Stages[2:] {
		for _, m := range refused(t, st.Label, st.Findings, findings.RuleStageArtifactStale, "n1", "n2") {
			if !strings.Contains(m, "(Infrahub's event log: infrahub.node.") {
				t.Errorf("%s: %s; want the event named", st.Label, m)
			}
			t.Log(m)
		}
	}

	checksumsBefore := checksums(t, c, name)
	if err := c.GenerateArtifacts(name); err != nil {
		t.Fatal(err)
	}
	awaitMoved(t, c, name, checksumsBefore, "n1", "n2")
	regenerated := stamps()
	if want, _ := HeadAt(regenerated.Latest); headOf("after the regenerate") != want {
		t.Errorf("after the regenerate the head is not the stamps' %s", want)
	}
	res = planOf(t, name, p)
	if got, want := outcomes(res), []outcome{
		{LabelBranchPoint, PlanRefused, findings.RuleScopeEmpty},
		{"seeded", PlanCompiled, ""},
		{"removed", PlanRefused, findings.RuleStageArtifactStale},
		{LabelHead, PlanCompiled, ""},
	}; !slices.Equal(got, want) {
		t.Fatalf("stage plan %s after the regenerate: %v, want %v (findings %v)", name, got, want, res.Findings)
	}
	refused(t, "removed after the regenerate", res.Stages[2].Findings, findings.RuleStageArtifactStale, "n1", "n2")
	if links := res.Stages[3].Read.Counts.Links; links != 2 {
		t.Errorf("the head read %d links after the regenerate, want 2", links)
	}
}

// branchOrigin is the harness's own read of a branch's branched_from and created_at, on the
// default branch's GraphQL, verbatim.
func branchOrigin(t *testing.T, c *testsupport.Client, branch string) (branchedFrom, createdAt string) {
	t.Helper()
	raw, err := c.GraphQL("main", fmt.Sprintf(`{ Branch(name: %q) { branched_from created_at } }`, branch))
	if err != nil {
		t.Fatalf("reading branch %s: %v", branch, err)
	}
	var r struct {
		Branch []struct {
			BranchedFrom string `json:"branched_from"`
			CreatedAt    string `json:"created_at"`
		} `json:"Branch"`
	}
	if err := json.Unmarshal(raw, &r); err != nil || len(r.Branch) != 1 {
		t.Fatalf("reading branch %s: %v (%s)", branch, err, raw)
	}
	return r.Branch[0].BranchedFrom, r.Branch[0].CreatedAt
}

// schemaHash is a branch's schema hash as GET /api/schema/summary gives it, under the key
// main whatever the branch (verified 2026-09-14); "" is the default branch.
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
	raw, err := c.GraphQL(branch, `{ DcimDevice { edges { node { name { value }
		... on CoreArtifactTarget { artifacts { edges { node { status { value } checksum { value }
			definition { node { ... on CoreArtifactDefinition { artifact_name { value } } } } } } } } } } } }`)
	if err != nil {
		t.Fatalf("asking Infrahub for the artifacts on %s: %v", branch, err)
	}
	type value struct {
		Value string `json:"value"`
	}
	var data struct {
		DcimDevice struct {
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
		} `json:"DcimDevice"`
	}
	if err := json.Unmarshal(raw, &data); err != nil {
		t.Fatal(err)
	}
	out := map[string]string{}
	for _, d := range data.DcimDevice.Edges {
		for _, a := range d.Node.Artifacts.Edges {
			if a.Node.Definition.Node.ArtifactName.Value == testsupport.ArtifactName && a.Node.Status.Value == intent.StatusReady {
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
