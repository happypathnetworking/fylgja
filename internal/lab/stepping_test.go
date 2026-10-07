package lab

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// The step's four activities against a scratch twin directory, the
// three-node golden as the bundle the twin was built from, and a copy of it pinned at
// another at as the target.

const (
	stepTargetAt = "2026-09-09T12:00:00Z"
	stepRunID    = "01a1b2c3-0000-7000-8000-00000000000a"
)

// targetBundle is a copy of the three-node golden pinned at stepTargetAt, in a directory of
// its own, and the id it hashes to: the target of a step from the golden.
func targetBundle(t *testing.T) (string, string) {
	t.Helper()
	return goldenPinnedAt(t, stepTargetAt)
}

// goldenPinnedAt is a copy of the three-node golden pinned at at, in a directory of its own,
// and the id it hashes to.
func goldenPinnedAt(t *testing.T, at string) (string, string) {
	t.Helper()
	dir := filepath.Join(t.TempDir(), "target")
	copyTree(t, goldenBundle(), dir)
	path := filepath.Join(dir, compiler.ManifestFile)
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var m map[string]any
	if err := json.Unmarshal(raw, &m); err != nil {
		t.Fatal(err)
	}
	m["provenance"].(map[string]any)["at"] = at
	if raw, err = json.MarshalIndent(m, "", "  "); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, raw, 0o644); err != nil {
		t.Fatal(err)
	}
	id, err := bundle.IDOfDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	if id == goldenID {
		t.Fatal("the target hashes to the golden's id")
	}
	return dir, id
}

// steppingTwin is the activities with the golden staged as a create stages it, and a file
// in clab-fylgja/ standing for the nodes' state, which no step activity may touch.
func steppingTwin(t *testing.T, r Runner) (*Activities, string) {
	t.Helper()
	a := testActivities(t, r)
	if _, err := a.StageBundle(context.Background(), wire.StageInput{BundlePath: goldenBundle(), BundleID: goldenID}); err != nil {
		t.Fatal(err)
	}
	state := filepath.Join(a.Paths.Twin, "clab-fylgja", ".state.clab.yaml")
	if err := os.MkdirAll(filepath.Dir(state), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(state, []byte("name: fylgja\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	return a, state
}

// twinListing is every path under the twin directory, for asserting what an activity left.
func twinListing(t *testing.T, a *Activities) []string {
	t.Helper()
	var out []string
	err := filepath.WalkDir(a.Paths.Twin, func(p string, d os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, _ := filepath.Rel(a.Paths.Twin, p)
		if strings.Count(rel, string(filepath.Separator)) < 1 {
			out = append(out, rel)
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	return out
}

// StageStep swaps the target in for the bundle the step started from, accepts a retry that
// finds its work done, retries one cut after its fetch, finishes one cut between its two
// renames, and refuses a twin directory holding what the step did not start from;
// containerlab's state is never touched.
func TestStageStep(t *testing.T) {
	ctx := context.Background()
	target, targetID := targetBundle(t)
	in := wire.StageStepInput{BundlePath: target, BundleID: targetID, FromBundleID: goldenID}
	staged := func(t *testing.T, a *Activities) string {
		t.Helper()
		id, err := bundle.IDOfDir(a.Paths.TwinBundle)
		if err != nil {
			t.Fatal(err)
		}
		return id
	}
	wantSwapped := func(t *testing.T, a *Activities, state string) {
		t.Helper()
		if id := staged(t, a); id != targetID {
			t.Errorf("twin/bundle holds %s, want the target %s", id, targetID)
		}
		if got, want := twinListing(t, a), []string{".", "bundle", "clab-fylgja"}; !slices.Equal(got, want) {
			t.Errorf("the twin directory holds %v, want %v and no scratch directory", got, want)
		}
		if b, err := os.ReadFile(state); err != nil || string(b) != "name: fylgja\n" {
			t.Errorf("containerlab's state changed: %q, %v", b, err)
		}
	}

	t.Run("swaps the target in", func(t *testing.T) {
		a, state := steppingTwin(t, &fakeRunner{})
		before, err := os.Stat(state)
		if err != nil {
			t.Fatal(err)
		}
		res, err := a.StageStep(ctx, in)
		if err != nil {
			t.Fatal(err)
		}
		if res.TwinDir != a.Paths.Twin {
			t.Errorf("twin dir %s, want %s", res.TwinDir, a.Paths.Twin)
		}
		wantSwapped(t, a, state)
		if after, err := os.Stat(state); err != nil || !after.ModTime().Equal(before.ModTime()) {
			t.Errorf("containerlab's state was rewritten")
		}
		if ok, err := a.Store.Has(ctx, targetID); err != nil || !ok {
			t.Errorf("the worker's store does not hold the target: %v, %v", ok, err)
		}

		// A retry finds its work done.
		if _, err := a.StageStep(ctx, in); err != nil {
			t.Fatalf("a retry: %v", err)
		}
		wantSwapped(t, a, state)
	})

	// A worker cut after the fetch and before the first rename leaves a whole .bundle.next
	// beside a twin/bundle that still holds the from bundle. The retry clears it and stages
	// again, rather than failing on a scratch directory that is not empty.
	t.Run("retries a stage cut after its fetch", func(t *testing.T) {
		a, state := steppingTwin(t, &fakeRunner{})
		copyTree(t, target, filepath.Join(a.Paths.Twin, stepNextDir))
		if staged(t, a) != goldenID {
			t.Fatal("twin/bundle does not hold the from bundle")
		}
		if _, err := a.StageStep(ctx, in); err != nil {
			t.Fatal(err)
		}
		wantSwapped(t, a, state)
	})

	t.Run("finishes a swap cut between its renames", func(t *testing.T) {
		a, state := steppingTwin(t, &fakeRunner{})
		next := filepath.Join(a.Paths.Twin, stepNextDir)
		copyTree(t, target, next)
		if err := os.Rename(a.Paths.TwinBundle, filepath.Join(a.Paths.Twin, stepPrevDir)); err != nil {
			t.Fatal(err)
		}
		if _, err := a.StageStep(ctx, in); err != nil {
			t.Fatal(err)
		}
		wantSwapped(t, a, state)
	})

	for _, c := range []struct {
		name   string
		in     wire.StageStepInput
		before func(a *Activities)
		want   string
	}{
		{name: "a twin directory holding another bundle", in: wire.StageStepInput{BundlePath: target, BundleID: targetID,
			FromBundleID: strings.Repeat("51f0aa93", 8)},
			want: "holds bundle " + goldenID + ", not bundle " + strings.Repeat("51f0aa93", 8) + " the step started from"},
		{name: "a target that does not hash to its id", in: wire.StageStepInput{BundlePath: goldenBundle(), BundleID: targetID,
			FromBundleID: goldenID}, want: "hashes to " + goldenID + ", but the step was given " + targetID},
		{name: "a twin directory with no bundle", in: in, before: func(a *Activities) { _ = os.RemoveAll(a.Paths.TwinBundle) },
			want: "holds no bundle"},
	} {
		t.Run(c.name, func(t *testing.T) {
			a, state := steppingTwin(t, &fakeRunner{})
			if c.before != nil {
				c.before(a)
			}
			_, err := a.StageStep(ctx, c.in)
			f := stepFailure(t, err, findings.RuleStageFailed)
			if f.Step != findings.StepStage || !strings.Contains(f.Message, c.want) {
				t.Errorf("finding %+v, want step stage and a message saying %q", f, c.want)
			}
			if b, err := os.ReadFile(state); err != nil || string(b) != "name: fylgja\n" {
				t.Errorf("containerlab's state changed: %q, %v", b, err)
			}
			if c.before == nil && staged(t, a) != goldenID {
				t.Errorf("a refused stage moved twin/bundle")
			}
		})
	}
}

// PlanReconcile reads containerlab's plan for the target against the running lab, with the
// twin directory as the lab directory base, and refuses a bundle that does not hash to its
// id or a plan containerlab cannot give, as operation.failed at compare.
func TestPlanReconcile(t *testing.T) {
	ctx := context.Background()
	target, targetID := targetBundle(t)
	f := &fakeRunner{replies: map[string][]reply{"deploy": {{stdout: recorded(t, "plan-link-added.json")}}}}
	a, _ := steppingTwin(t, f)
	before := twinListing(t, a)
	plan, err := a.PlanReconcile(ctx, wire.PlanReconcileInput{BundlePath: target, BundleID: targetID})
	if err != nil {
		t.Fatal(err)
	}
	if !slices.Equal(plan.Restarted, []string{"e1"}) || plan.Reasons["e1"] != "added link" {
		t.Errorf("plan %+v", plan)
	}
	want := []string{"clab", "deploy", "--dry-run", "--topo", filepath.Join(target, compiler.TopologyFile), "--format", "json"}
	if len(f.calls) != 1 || !reflect.DeepEqual(f.calls[0].args, want) ||
		!reflect.DeepEqual(f.calls[0].env, []string{"CLAB_LABDIR_BASE=" + a.Paths.Twin}) {
		t.Errorf("calls %+v, want %v with the twin directory as the lab directory base", f.calls, want)
	}
	if after := twinListing(t, a); !slices.Equal(before, after) {
		t.Errorf("the plan changed the twin directory: %v to %v", before, after)
	}

	for _, c := range []struct {
		name string
		in   wire.PlanReconcileInput
		r    reply
		want string
	}{
		{"a bundle that does not hash to its id", wire.PlanReconcileInput{BundlePath: goldenBundle(), BundleID: targetID},
			reply{stdout: recorded(t, "plan-nothing.json")}, "hashes to " + goldenID + ", but the step was given " + targetID},
		{"containerlab refuses the topology", wire.PlanReconcileInput{BundlePath: target, BundleID: targetID},
			reply{stderr: []byte(`Arista cEOS node "s1" has an interface named "e1-1" which doesn't match the required pattern`), exit: 1},
			`reading containerlab's plan for bundle ` + targetID + ` against the running lab: clab deploy --dry-run`},
		{"no running lab", wire.PlanReconcileInput{BundlePath: target, BundleID: targetID},
			reply{stdout: recorded(t, "plan-no-lab.json")}, "finds no running lab to reconcile under"},
	} {
		t.Run(c.name, func(t *testing.T) {
			a, _ := steppingTwin(t, &fakeRunner{replies: map[string][]reply{"deploy": {c.r}}})
			_, err := a.PlanReconcile(ctx, c.in)
			f := stepFailure(t, err, findings.RuleOperationFailed)
			if f.Step != findings.StepCompare || !strings.Contains(f.Message, c.want) {
				t.Errorf("finding %+v, want step compare and a message saying %q", f, c.want)
			}
		})
	}
}

// ReconcileLab applies the staged target with containerlab's own plan, never with
// --reconfigure, reports how long it took, and refuses a node not running afterwards as
// deploy.failed at reconcile.
func TestReconcileLab(t *testing.T) {
	run := func(t *testing.T, r reply, nodes ...string) (*fakeRunner, *Activities, wire.ReconcileResult, error) {
		t.Helper()
		f := &fakeRunner{replies: map[string][]reply{"deploy": {r}}}
		a, _ := steppingTwin(t, f)
		in := wire.ReconcileInput{TwinDir: a.Paths.Twin, Plan: wire.ReconcilePlan{Restarted: []string{"n1"}}}
		for _, n := range nodes {
			in.Nodes = append(in.Nodes, wire.NodePlan{Name: n, DeployTimeoutS: 120})
		}
		val, err := activityEnv(a.ReconcileLab, wire.ActReconcileLab).ExecuteActivity(wire.ActReconcileLab, in)
		var res wire.ReconcileResult
		if err == nil {
			if err := val.Get(&res); err != nil {
				t.Fatal(err)
			}
		}
		return f, a, res, err
	}

	f, a, res, err := run(t, reply{stdout: recorded(t, "deploy-one.json")}, "n1")
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"clab", "deploy", "--topo", filepath.Join(a.Paths.TwinBundle, compiler.TopologyFile), "--format", "json"}
	var deploys [][]string
	for _, c := range f.calls {
		deploys = append(deploys, c.args)
	}
	if len(deploys) != 1 || !reflect.DeepEqual(deploys[0], want) {
		t.Errorf("containerlab saw %v, want %v alone", deploys, want)
	}
	// containerlab decides a recreate from the running lab's .state.clab.yaml, so the
	// apply runs with the twin directory as its lab directory base, as the plan did.
	if len(f.calls) == 1 && !reflect.DeepEqual(f.calls[0].env, []string{"CLAB_LABDIR_BASE=" + a.Paths.Twin}) {
		t.Errorf("the apply's environment override is %v, want the twin directory %s as the lab directory base",
			f.calls[0].env, a.Paths.Twin)
	}
	if len(res.Nodes) != 1 || res.Nodes[0].Name != "n1" || res.TookS < 0 {
		t.Errorf("result %+v", res)
	}

	for _, c := range []struct {
		name  string
		r     reply
		nodes []string
		want  string
	}{
		{"a node not running", reply{stdout: recorded(t, "deploy-one.json")}, []string{"n1", "n2"},
			"clab deploy exited 0, but not every node is running: n2 absent"},
		{"containerlab failed", reply{stderr: recorded(t, "deploy-failed.stderr"), exit: 1}, []string{"n1"},
			"Failed to parse value 'e1-1'"},
	} {
		t.Run(c.name, func(t *testing.T) {
			_, _, _, err := run(t, c.r, c.nodes...)
			f := stepFailure(t, err, findings.RuleDeployFailed)
			if f.Step != findings.StepReconcile || !strings.Contains(f.Message, c.want) {
				t.Errorf("finding %+v, want step reconcile and a message saying %q", f, c.want)
			}
		})
	}
}

// RecordStep writes the record a step leaves from the record it started from, the staged
// target and what crossed as data, on a stepped and on a diverged outcome, against
// twin.schema.json 4; and refuses as record.failed a record that names another bundle,
// leaving it whole.
func TestRecordStep(t *testing.T) {
	ctx := context.Background()
	target, targetID := targetBundle(t)
	golden := manifestNodes(t, goldenBundle())
	demo1 := &wire.WaypointRef{Series: "demo", Sequence: 1, Description: "before", AtSource: "given"}
	demo2 := &wire.WaypointRef{Series: "demo", Sequence: 2, Description: "after", AtSource: "given"}
	const goldenAt = "2026-09-08T12:00:00Z"

	// prepared is the twin as a create of demo/1 left it, the target staged when stage says so.
	prepared := func(t *testing.T, stage bool) *Activities {
		t.Helper()
		a, _ := steppingTwin(t, &fakeRunner{})
		observed := "2026-09-08T12:01:00.000000Z"
		f := RecordFields{BundleID: goldenID, ObservedAt: &observed, Source: wire.SourceIntent, Waypoint: demo1,
			Provenance: wire.Provenance{Branch: "fylgja-fixture", At: goldenAt, SchemaHash: "fixture", ContractVersion: "0.2"},
			RunID:      "01a0e9e3-0000-7000-8000-000000000001", Version: "0.1.0-dev", RecordedAt: time.Now()}
		for _, n := range golden {
			f.Nodes = append(f.Nodes, wire.TwinNode{Name: n.Name, Container: "clab-fylgja-" + n.Name, Image: n.Image,
				PSP: wire.PSPRef{ID: n.PSP.ID, Source: n.PSP.Source}, MgmtIPv4: "172.20.20.2", ReadyAfterS: 1,
				Artifact: &wire.TwinArtifact{Name: n.Artifact.Name, ContentType: n.Artifact.ContentType,
					Checksum: n.Artifact.Checksum, Size: n.Artifact.Size}, PushedInS: 0.7})
		}
		rec, err := NewRecord(f)
		if err != nil {
			t.Fatal(err)
		}
		if err := WriteRecord(a.Paths.TwinJSON, rec); err != nil {
			t.Fatal(err)
		}
		if stage {
			if _, err := a.StageStep(ctx, wire.StageStepInput{BundlePath: target, BundleID: targetID, FromBundleID: goldenID}); err != nil {
				t.Fatal(err)
			}
		}
		return a
	}
	input := func(a *Activities) wire.RecordStepInput {
		var nodes []wire.LabNode
		for _, n := range golden {
			nodes = append(nodes, wire.LabNode{Name: n.Name, Container: "clab-fylgja-" + n.Name, Image: n.Image, State: "running",
				MgmtIPv4: "172.20.20.2"})
		}
		return wire.RecordStepInput{TwinDir: a.Paths.Twin, RunID: stepRunID, Outcome: wire.StepStepped,
			From:       wire.StepSide{Waypoint: demo1, BundleID: goldenID, At: goldenAt},
			To:         wire.StepSide{Waypoint: demo2, BundleID: targetID, At: stepTargetAt, Branch: "fylgja-fixture"},
			ObservedAt: "2026-09-09T12:01:00.000000Z", ReconcileStarted: true,
			Plan:      wire.ReconcilePlan{Restarted: []string{"n1"}, LinksAdded: []string{"n1:e1-3 -- n2:e1-3"}},
			Declared:  map[string]string{"n1": "live", "n2": "live", "n3": "live"},
			Reconcile: &wire.ReconcileResult{Nodes: nodes, TookS: 3.9},
			Ready:     []wire.ReadinessResult{{Node: "n1", ReadyAfterS: 11.2}},
			Pushed:    []wire.PushResult{{Node: "n1", PushedInS: 1.2}, {Node: "n2", PushedInS: 0.9}},
			PushPlan: []wire.StepPush{{Node: "n1", Reasons: []string{"restarted"}, Outcome: wire.PushLanded},
				{Node: "n2", Reasons: []string{"artifact"}, Outcome: wire.PushLanded}},
			StartedAt: "2026-10-02T09:14:30Z", EndedAt: "2026-10-02T09:15:00Z", Nodes: nodes}
	}
	record := func(t *testing.T, a *Activities, in wire.RecordStepInput) (wire.RecordResult, error) {
		t.Helper()
		val, err := activityEnv(a.RecordStep, wire.ActRecordStep).ExecuteActivity(wire.ActRecordStep, in)
		if err != nil {
			return wire.RecordResult{}, err
		}
		var res wire.RecordResult
		if err := val.Get(&res); err != nil {
			t.Fatal(err)
		}
		return res, nil
	}
	// divergedAtStage is a step stopped at its stage: no reconcile, no push.
	divergedAtStage := func(a *Activities) wire.RecordStepInput {
		in := input(a)
		var l findings.List
		l.AddStep(findings.Rejection, findings.StepStage, findings.RuleStageFailed, a.Paths.TwinBundle, "the stage failed")
		in.Outcome, in.Phase, in.Findings, in.ReconcileStarted, in.Reconcile, in.Ready = wire.StepDiverged, findings.StepReconcile, l, false, nil, nil
		for i := range in.PushPlan {
			in.PushPlan[i].Outcome = wire.PushNotAttempted
		}
		in.Pushed = nil
		return in
	}
	schema := twinSchema(t)

	t.Run("stepped", func(t *testing.T) {
		a := prepared(t, true)
		in := input(a)
		in.AllowRestart = true
		before := time.Now()
		res, err := record(t, a, in)
		after := time.Now()
		if err != nil {
			t.Fatal(err)
		}
		written, err := ReadRecord(a.Paths.TwinJSON)
		if err != nil {
			t.Fatal(err)
		}
		if !reflect.DeepEqual(written, res.Record) {
			t.Errorf("the record returned differs from the one written")
		}
		validateRecord(t, schema, written)
		if written.BundleID != targetID || written.Provenance.At != stepTargetAt || written.State != wire.StateReady ||
			written.Step == nil || written.Step.Outcome != wire.StepStepped || written.Step.WorkerVersion != a.Version {
			t.Errorf("record %+v", written)
		}
		for _, n := range written.Nodes {
			if n.Holds == nil || *n.Holds != targetID {
				t.Errorf("node %s holds %v, want the target", n.Name, n.Holds)
			}
		}
		if n1 := written.Nodes[0]; n1.PushedInS != 1.2 || n1.ReadyAfterS != 11.2 {
			t.Errorf("n1 pushed in %v, ready after %v; want this step's 1.2 and 11.2", n1.PushedInS, n1.ReadyAfterS)
		}
		if took := written.Step.Reconcile.TookS; took == nil || *took != 3.9 {
			t.Errorf("the reconcile took %v, want 3.9", took)
		}
		if calls := a.Clab.Runner.(*fakeRunner).calls; len(calls) != 0 {
			t.Errorf("containerlab saw %v: the lab a reconcile reported is not read again", calls)
		}

		// What the record carries from its input and the staged manifest: the target read's
		// observed_at, each touched node's
		// declaration beside what containerlab reported, the flag the step was given, the
		// time of the write, and each node's package and artifact as the target names them.
		if written.ObservedAt == nil || *written.ObservedAt != in.ObservedAt {
			t.Errorf("observed_at = %v, want the target read's %s", written.ObservedAt, in.ObservedAt)
		}
		if len(written.Step.Reconcile.Nodes) == 0 {
			t.Errorf("the reconcile names no touched node; the plan touches n1 and n2")
		}
		for _, n := range written.Step.Reconcile.Nodes {
			if d := in.Declared[n.Node]; n.Declared == nil || *n.Declared != d {
				t.Errorf("node %s is declared %v, want the input's %q", n.Node, n.Declared, d)
			}
		}
		if !written.Step.AllowRestart {
			t.Errorf("allow_restart is false, want the input's true")
		}
		if at, err := time.Parse(time.RFC3339Nano, written.RecordedAt); err != nil || at.Before(before) || at.After(after) {
			t.Errorf("recorded_at = %s (%v), want a time between %s and %s", written.RecordedAt, err,
				before.UTC().Format(time.RFC3339Nano), after.UTC().Format(time.RFC3339Nano))
		}
		staged := map[string]compiler.ManifestNode{}
		for _, n := range manifestNodes(t, a.Paths.TwinBundle) {
			staged[n.Name] = n
		}
		for _, n := range written.Nodes {
			m := staged[n.Name]
			if want := (wire.PSPRef{ID: m.PSP.ID, Source: m.PSP.Source}); n.PSP != want {
				t.Errorf("node %s's package is %+v, want the staged manifest's %+v", n.Name, n.PSP, want)
			}
			want := wire.TwinArtifact{Name: m.Artifact.Name, ContentType: m.Artifact.ContentType,
				Checksum: m.Artifact.Checksum, Size: m.Artifact.Size}
			if n.Artifact == nil || *n.Artifact != want {
				t.Errorf("node %s's artifact is %+v, want the staged manifest's %+v", n.Name, n.Artifact, want)
			}
		}
	})

	t.Run("diverged at its stage", func(t *testing.T) {
		a := prepared(t, false)
		res, err := record(t, a, divergedAtStage(a))
		if err != nil {
			t.Fatal(err)
		}
		validateRecord(t, schema, res.Record)
		if r := res.Record; r.BundleID != goldenID || r.State != wire.StateDiverged || r.Step.Phase == nil ||
			*r.Step.Phase != findings.StepReconcile || len(r.Step.Findings) != 1 {
			t.Errorf("record %+v", r)
		}
		for _, n := range res.Record.Nodes {
			if n.Holds == nil || *n.Holds != goldenID {
				t.Errorf("node %s holds %v, want the bundle it was built from: the reconcile never ran", n.Name, n.Holds)
			}
		}
		if calls := a.Clab.Runner.(*fakeRunner).calls; len(calls) != 0 {
			t.Errorf("containerlab saw %v: a lab no reconcile touched is not read again", calls)
		}
	})

	t.Run("diverged at its push", func(t *testing.T) {
		a := prepared(t, true)
		in := input(a)
		in.Outcome, in.Phase = wire.StepDiverged, findings.StepPush
		in.PushPlan[0].Outcome, in.PushPlan[0].Rule = wire.PushRefused, findings.RulePushRefused
		in.Pushed = in.Pushed[1:]
		res, err := record(t, a, in)
		if err != nil {
			t.Fatal(err)
		}
		validateRecord(t, schema, res.Record)
		holds := map[string]string{}
		for _, n := range res.Record.Nodes {
			holds[n.Name] = "null"
			if n.Holds != nil {
				holds[n.Name] = *n.Holds
			}
		}
		if want := map[string]string{"n1": "null", "n2": targetID, "n3": goldenID}; !reflect.DeepEqual(holds, want) {
			t.Errorf("holds %v, want %v", holds, want)
		}
	})

	// A reconcile that ran and returned no report may have created or deleted nodes before
	// it failed: the record's nodes are the lab as containerlab reports it when the record is
	// written, read again, and the inspection before the stage only when that read fails.
	failedReconcile := func(a *Activities, plan wire.ReconcilePlan, inspected []wire.LabNode) wire.RecordStepInput {
		in := input(a)
		var l findings.List
		l.AddStep(findings.Rejection, findings.StepReconcile, findings.RuleDeployFailed, "lab "+LabName,
			"clab deploy exited 1: post-deploy failed")
		in.Outcome, in.Phase, in.Findings, in.Plan, in.Nodes = wire.StepDiverged, findings.StepReconcile, l, plan, inspected
		in.Reconcile, in.Ready, in.Pushed = nil, nil, nil
		for i := range in.PushPlan {
			in.PushPlan[i].Outcome = wire.PushNotAttempted
		}
		return in
	}
	lab3 := func(t *testing.T) []wire.LabNode {
		t.Helper()
		state, err := parseLabs(recorded(t, "inspect-three.json"))
		if err != nil {
			t.Fatal(err)
		}
		return state.Nodes
	}
	inspectedOnce := func(t *testing.T, a *Activities) {
		t.Helper()
		want := []string{"clab", "inspect", "--all", "--format", "json"}
		var got [][]string
		for _, c := range a.Clab.Runner.(*fakeRunner).calls {
			got = append(got, c.args)
		}
		if len(got) != 1 || !reflect.DeepEqual(got[0], want) {
			t.Errorf("containerlab saw %v, want %v alone: the lab is read again after a reconcile with no report", got, want)
		}
	}
	for _, c := range []struct {
		name string
		// fromLacksN3 is a twin built without n3, which the step's plan creates.
		fromLacksN3 bool
		plan        wire.ReconcilePlan
		inspect     reply
		holds       map[string]string
	}{
		{name: "a created node is present, holding nothing", fromLacksN3: true,
			plan:    wire.ReconcilePlan{Added: []string{"n3"}},
			inspect: reply{stdout: recorded(t, "inspect-three.json")},
			holds:   map[string]string{"n1": goldenID, "n2": goldenID, "n3": "null"}},
		{name: "a deleted node is gone",
			plan:    wire.ReconcilePlan{Deleted: []string{"n3"}},
			inspect: reply{stdout: inspectWithout(t, "n3")},
			holds:   map[string]string{"n1": goldenID, "n2": goldenID}},
		{name: "a lab that cannot be read keeps the inspection before the stage",
			plan:    wire.ReconcilePlan{Deleted: []string{"n3"}},
			inspect: reply{stderr: []byte("permission denied"), exit: 1},
			holds:   map[string]string{"n1": goldenID, "n2": goldenID, "n3": goldenID}},
	} {
		t.Run("diverged at a failed reconcile: "+c.name, func(t *testing.T) {
			a := prepared(t, true)
			inspected := lab3(t)
			if c.fromLacksN3 {
				prev, err := ReadRecord(a.Paths.TwinJSON)
				if err != nil {
					t.Fatal(err)
				}
				prev.Nodes, inspected = prev.Nodes[:2], inspected[:2]
				if err := WriteRecord(a.Paths.TwinJSON, prev); err != nil {
					t.Fatal(err)
				}
			}
			a.Clab.Runner.(*fakeRunner).replies = map[string][]reply{"inspect": {c.inspect}}
			res, err := record(t, a, failedReconcile(a, c.plan, inspected))
			if err != nil {
				t.Fatal(err)
			}
			validateRecord(t, schema, res.Record)
			inspectedOnce(t, a)
			holds := map[string]string{}
			for _, n := range res.Record.Nodes {
				holds[n.Name] = "null"
				if n.Holds != nil {
					holds[n.Name] = *n.Holds
				}
			}
			if !reflect.DeepEqual(holds, c.holds) {
				t.Errorf("holds %v, want %v", holds, c.holds)
			}
			if r := res.Record; r.BundleID != goldenID || r.State != wire.StateDiverged || r.Step.Phase == nil ||
				*r.Step.Phase != findings.StepReconcile {
				t.Errorf("record %+v, want diverged at reconcile from the golden", r)
			}
		})
	}

	// A retry whose first attempt wrote twin.json and never answered (a killed
	// worker) finds this run's record: it returns it as written and writes nothing.
	// Another run's step record is no retry, and keeps NewStepRecord's refusals.
	for _, c := range []struct {
		name  string
		stage bool
		in    func(a *Activities) wire.RecordStepInput
		other string // the refusal a second run's record draws
	}{
		{name: "stepped", stage: true, in: input,
			other: "the record names bundle " + targetID + ", not bundle " + goldenID + " the step started from"},
		{name: "diverged", in: divergedAtStage,
			other: "the record is diverged; no step starts from a diverged twin"},
	} {
		t.Run("a retry of a "+c.name+" record", func(t *testing.T) {
			a := prepared(t, c.stage)
			first, err := record(t, a, c.in(a))
			if err != nil {
				t.Fatal(err)
			}
			written, _ := os.ReadFile(a.Paths.TwinJSON)
			again, err := record(t, a, c.in(a))
			if err != nil {
				t.Fatalf("the retry of the run that wrote the record was refused: %v", err)
			}
			if !reflect.DeepEqual(again, first) {
				t.Errorf("the retry returned %+v, want the first attempt's %+v", again, first)
			}
			if after, _ := os.ReadFile(a.Paths.TwinJSON); !slices.Equal(written, after) {
				t.Errorf("the retry wrote twin.json again")
			}
		})
		t.Run("another run over a "+c.name+" record", func(t *testing.T) {
			a := prepared(t, c.stage)
			if _, err := record(t, a, c.in(a)); err != nil {
				t.Fatal(err)
			}
			written, _ := os.ReadFile(a.Paths.TwinJSON)
			in := c.in(a)
			in.RunID = "01a1b2c3-0000-7000-8000-00000000000b"
			_, err := record(t, a, in)
			f := stepFailure(t, err, findings.RuleRecordFailed)
			if f.Step != findings.StepRecord || !strings.Contains(f.Message, c.other) {
				t.Errorf("finding %+v, want step record and a message saying %q", f, c.other)
			}
			if after, _ := os.ReadFile(a.Paths.TwinJSON); !slices.Equal(written, after) {
				t.Errorf("a refused record changed twin.json")
			}
		})
	}

	// A second step over a stepped record, demo/2 → demo/3 by another run, writes its own
	// record: the top level is the new target's, the step block the second run's alone, run
	// stays the create's, and a node the second step left alone keeps the times the first
	// gave it. This is the success beside the refusal above.
	t.Run("a second step over a stepped record", func(t *testing.T) {
		const (
			thirdAt = "2026-09-10T12:00:00Z"
			runB    = "01a1b2c3-0000-7000-8000-00000000000c"
		)
		demo3 := &wire.WaypointRef{Series: "demo", Sequence: 3, Description: "later", AtSource: "given"}
		a := prepared(t, true)
		first, err := record(t, a, input(a))
		if err != nil {
			t.Fatal(err)
		}
		third, thirdID := goldenPinnedAt(t, thirdAt)
		if _, err := a.StageStep(ctx, wire.StageStepInput{BundlePath: third, BundleID: thirdID, FromBundleID: targetID}); err != nil {
			t.Fatal(err)
		}
		in := input(a)
		in.RunID = runB
		in.From = wire.StepSide{Waypoint: demo2, BundleID: targetID, At: stepTargetAt}
		in.To = wire.StepSide{Waypoint: demo3, BundleID: thirdID, At: thirdAt, Branch: "fylgja-fixture"}
		in.ObservedAt = "2026-09-10T12:01:00.000000Z"
		in.Plan = wire.ReconcilePlan{Restarted: []string{"n2"}, LinksAdded: []string{"n2:e1-4 -- n3:e1-4"}}
		in.Reconcile = &wire.ReconcileResult{Nodes: in.Nodes, TookS: 4.2}
		in.Ready = []wire.ReadinessResult{{Node: "n2", ReadyAfterS: 12.5}}
		in.Pushed = []wire.PushResult{{Node: "n2", PushedInS: 0.8}, {Node: "n3", PushedInS: 0.6}}
		in.PushPlan = []wire.StepPush{{Node: "n2", Reasons: []string{"restarted"}, Outcome: wire.PushLanded},
			{Node: "n3", Reasons: []string{"artifact"}, Outcome: wire.PushLanded}}
		in.StartedAt, in.EndedAt = "2026-10-02T09:25:00Z", "2026-10-02T09:25:40Z"

		res, err := record(t, a, in)
		if err != nil {
			t.Fatal(err)
		}
		written, err := ReadRecord(a.Paths.TwinJSON)
		if err != nil {
			t.Fatal(err)
		}
		if !reflect.DeepEqual(written, res.Record) {
			t.Errorf("the record returned differs from the one written")
		}
		validateRecord(t, schema, written)
		if written.BundleID != thirdID || written.Provenance.At != thirdAt || !reflect.DeepEqual(written.Waypoint, demo3) ||
			written.State != wire.StateReady || written.Run != first.Record.Run {
			t.Errorf("record %+v; want demo/3's top level, ready, and the create's run %+v", written, first.Record.Run)
		}
		if st := written.Step; st == nil || st.Run.RunID != runB || st.From.BundleID != targetID ||
			!reflect.DeepEqual(st.From.Waypoint, demo2) || st.To.BundleID != thirdID || st.StartedAt != in.StartedAt ||
			st.EndedAt != in.EndedAt || !slices.Equal(st.Reconcile.Restarted, []string{"n2"}) {
			t.Errorf("step block %+v; want the second run's, from demo/2", st)
		}
		times := map[string][2]float64{"n1": {11.2, 1.2}, "n2": {12.5, 0.8}, "n3": {1, 0.6}}
		for _, n := range written.Nodes {
			if n.Holds == nil || *n.Holds != thirdID {
				t.Errorf("node %s holds %v, want demo/3's bundle", n.Name, n.Holds)
			}
			if got := [2]float64{n.ReadyAfterS, n.PushedInS}; got != times[n.Name] {
				t.Errorf("node %s: ready after %v, pushed in %v; want %v", n.Name, got[0], got[1], times[n.Name])
			}
		}
	})

	for _, c := range []struct {
		name     string
		unstaged bool
		change   func(a *Activities, in *wire.RecordStepInput)
		want     string
	}{
		{name: "a record naming another bundle", change: func(_ *Activities, in *wire.RecordStepInput) { in.From.BundleID = strings.Repeat("51f0aa93", 8) },
			want: "the record names bundle " + goldenID + ", not bundle " + strings.Repeat("51f0aa93", 8) + " the step started from"},
		{name: "no record", change: func(a *Activities, _ *wire.RecordStepInput) { _ = os.Remove(a.Paths.TwinJSON) },
			want: "reading the record the step started from"},
		// The bundle the step started from is no staged target: a stepped record over it
		// would name what does not run.
		{name: "a stepped record with the target not staged", unstaged: true, change: func(*Activities, *wire.RecordStepInput) {},
			want: "moves the record to bundle " + targetID + ", but the twin directory does not hold it"},
	} {
		t.Run(c.name, func(t *testing.T) {
			a := prepared(t, !c.unstaged)
			in := input(a)
			c.change(a, &in)
			before, _ := os.ReadFile(a.Paths.TwinJSON)
			_, err := record(t, a, in)
			f := stepFailure(t, err, findings.RuleRecordFailed)
			if f.Step != findings.StepRecord || !strings.Contains(f.Message, c.want) {
				t.Errorf("finding %+v, want step record and a message saying %q", f, c.want)
			}
			if after, _ := os.ReadFile(a.Paths.TwinJSON); !slices.Equal(before, after) {
				t.Errorf("a refused record changed twin.json")
			}
		})
	}
}

// inspectWithout is the recorded three-node inspect document without node's container: the
// lab after containerlab deleted it.
func inspectWithout(t *testing.T, node string) []byte {
	t.Helper()
	var labs map[string][]map[string]any
	if err := json.Unmarshal(recorded(t, "inspect-three.json"), &labs); err != nil {
		t.Fatal(err)
	}
	labs[LabName] = slices.DeleteFunc(labs[LabName], func(c map[string]any) bool { return c["name"] == containerPrefix+node })
	if len(labs[LabName]) != 2 {
		t.Fatalf("the recorded document has no container for %s", node)
	}
	b, err := json.Marshal(labs)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

// manifestNodes is the nodes of the bundle at dir's manifest.
func manifestNodes(t *testing.T, dir string) []compiler.ManifestNode {
	t.Helper()
	m, err := readManifest(dir)
	if err != nil {
		t.Fatal(err)
	}
	return m.Nodes
}
