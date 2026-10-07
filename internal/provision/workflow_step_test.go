package provision

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"maps"
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/santhosh-tekuri/jsonschema/v6"
	"github.com/stretchr/testify/mock"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/converter"
	"go.temporal.io/sdk/interceptor"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/testsuite"
	"go.temporal.io/sdk/worker"
	"go.temporal.io/sdk/workflow"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/step"
)

// The step run under the SDK's test suite:
// every outcome produced by Step itself, every activity answered by a mock registered under
// the name the worker registers it by. The example is case 8's step on the mixed twin: e1
// (arista_eos, declares restart) restarted for an added link, s1 (nokia_srlinux, declares
// live) re-cabled live and pushed for its artifact and bootstrap, e2 untouched.

var (
	stepFrom = strings.Repeat("34", 32)
	stepTo   = strings.Repeat("ee", 32)
	demo1    = wire.WaypointRef{Series: "demo", Sequence: 1, Description: "before the change", AtSource: "written"}
	demo2    = wire.WaypointRef{Series: "demo", Sequence: 2, Description: "after the first cut-over", AtSource: "written"}
	// stepStart is when a run starts on the test suite's clock, for a test that sets it, so
	// that its record's times are known exactly. The clock moves only when a mocked activity
	// waits on it (MockCallWrapper.After).
	stepStart = time.Date(2026, 10, 2, 9, 15, 0, 0, time.UTC)
)

const (
	stepFromAt = "2026-09-28T15:00:01.123456+00:00"
	stepToAt   = "2026-09-28T15:20:44.000000+00:00"
	// stepDeviceDiff is what a mocked push returns as the device's diff: it must reach no
	// result, record input, finding or document.
	stepDeviceDiff = "insert / interface ethernet-1/3 admin-state enable"
)

// stepPlan is containerlab's plan for case 8's step: e1 restarted for the
// added link, s1 its live far end.
func stepPlan() wire.ReconcilePlan {
	return wire.ReconcilePlan{Restarted: []string{"e1"}, LinksAdded: []string{"e1:eth3 -- s1:e1-3"},
		Reasons: map[string]string{"e1": "added link", "s1": "added link"}}
}

// stepInput is the CLI's input for case 8's step, given --allow-restart.
func stepInput() StepInput {
	from, to := demo1, demo2
	return StepInput{
		From:         wire.StepSide{Waypoint: &from, BundleID: stepFrom, At: stepFromAt},
		To:           wire.StepSide{Waypoint: &to, BundleID: stepTo, At: stepToAt, Branch: "change-1"},
		ObservedAt:   "2026-10-02T09:14:01.000000Z",
		ToBundlePath: "/state/bundles/" + stepTo,
		Diff: json.RawMessage(`{"from":"demo/1","to":"demo/2","from_bundle_id":"` + stepFrom + `","to_bundle_id":"` + stepTo +
			`","computed":true,"unchanged":false,"nodes":{"added":[],"removed":[],"changed":[{"node":"s1","reasons":["bootstrap","mapping"]}]},` +
			`"links":{"added":[{"id":"e1:Ethernet3|s1:ethernet-1/3","a":{"node":"e1","port":"eth3"},"b":{"node":"s1","port":"e1-3"}}],"removed":[]},` +
			`"artifacts":{"changed":[{"node":"e1","name":"device-config","from":"43e8fd0c2de5f4646f74a51d34742824","to":"9a0177b2e8c1d4f5a6b7c8d9e0f1a2b3"},` +
			`{"node":"s1","name":"device-config","from":"1c0e2b7a2de5f4646f74a51d34742824","to":"7a9b03de2de5f4646f74a51d34742824"}]}}`),
		Plan: stepPlan(),
		PushPlan: []step.NodePush{{Node: "e1", Reasons: []string{step.PushArtifact, step.PushRestarted}},
			{Node: "s1", Reasons: []string{step.PushArtifact, step.PushBootstrap}}},
		Changed:      []StepChange{},
		AllowRestart: true,
		Declared:     map[string]string{"e1": "restart", "e2": "restart", "s1": "live"},
		Version:      "0.1.0-test",
	}
}

// stepCheckHost is a clear host check for the target: the shipped packages' budgets, each
// node's artifact named by the manifest.
func stepCheckHost(t *testing.T) wire.CheckHostResult {
	t.Helper()
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	nodes := []wire.NodePlan{planFor(t, reg, "arista_eos", "e1"), planFor(t, reg, "arista_eos", "e2"),
		planFor(t, reg, "nokia_srlinux", "s1")}
	for i := range nodes {
		nodes[i].Artifact = &wire.PlanArtifact{File: "configs/" + nodes[i].Name + ".device-config",
			Checksum: strings.Repeat(string(rune('a'+i)), 32)}
	}
	return wire.CheckHostResult{Nodes: nodes, MemorySumMB: 6144, LabPresent: true, TwinDirPresent: true,
		Provenance: wire.Provenance{Branch: "change-1", At: stepToAt, SchemaHash: "4d5b37aa", ContractVersion: "0.2"},
		Findings:   findings.List{}}
}

// stepLab is the mixed twin's three containers.
func stepLab() []wire.LabNode {
	return []wire.LabNode{
		{Name: "e1", Container: "clab-fylgja-e1", Kind: "ceos", State: "running", MgmtIPv4: "172.20.20.2"},
		{Name: "e2", Container: "clab-fylgja-e2", Kind: "ceos", State: "running", MgmtIPv4: "172.20.20.3"},
		{Name: "s1", Container: "clab-fylgja-s1", Kind: "nokia_srlinux", State: "running", MgmtIPv4: "172.20.20.4"},
	}
}

// stepTwinHost is the host holding the twin the step was planned from: ready at demo/1.
func stepTwinHost() wire.HostReport {
	w := demo1
	return wire.HostReport{LabPresent: true, TwinDirPresent: true, Nodes: stepLab(),
		Twin: &wire.TwinRecord{TwinVersion: "4", Lab: wire.LabName, BundleID: stepFrom, Waypoint: &w, State: wire.StateReady,
			Provenance: wire.Provenance{Branch: "change-1", At: stepFromAt}, Source: wire.SourceIntent,
			Run: wire.RunRef{WorkflowID: WorkflowProvision, RunID: "run-0"}},
		Phrase: "the twin of branch change-1 at " + stepFromAt + ", waypoint demo/1"}
}

// stepHarness is a workflow test environment for Step: every activity it schedules
// registered by name and answered by mocks, and a record of what started, was cancelled,
// and what the readiness, push and record steps were given.
type stepHarness struct {
	t    *testing.T
	env  *testsuite.TestWorkflowEnvironment
	host wire.HostReport
	plan wire.CheckHostResult
	lab  wire.ReconcilePlan

	mu        sync.Mutex
	events    []string
	awaited   []string
	pushedTo  []string
	recorded  []wire.RecordStepInput
	pushDiffs []string                             // the Diff each mocked push returned
	inputs    map[string][]converter.EncodedValues // each activity's arguments, in the order its attempts started
}

func newStepHarness(t *testing.T) *stepHarness {
	t.Helper()
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	h := &stepHarness{t: t, env: env, host: stepTwinHost(), plan: stepCheckHost(t), lab: stepPlan(),
		inputs: map[string][]converter.EncodedValues{}}
	env.RegisterWorkflow(Step)
	stubs := map[string]any{
		wire.ActInspectTwin: func(context.Context) (wire.HostReport, error) { return wire.HostReport{}, errUnmocked },
		wire.ActCheckHost: func(context.Context, wire.CheckHostInput) (wire.CheckHostResult, error) {
			return wire.CheckHostResult{}, errUnmocked
		},
		wire.ActPlanReconcile: func(context.Context, wire.PlanReconcileInput) (wire.ReconcilePlan, error) {
			return wire.ReconcilePlan{}, errUnmocked
		},
		wire.ActStageStep: func(context.Context, wire.StageStepInput) (wire.StageResult, error) {
			return wire.StageResult{}, errUnmocked
		},
		wire.ActReconcileLab: func(context.Context, wire.ReconcileInput) (wire.ReconcileResult, error) {
			return wire.ReconcileResult{}, errUnmocked
		},
		wire.ActAwaitReadiness: func(context.Context, wire.ReadinessInput) (wire.ReadinessResult, error) {
			return wire.ReadinessResult{}, errUnmocked
		},
		wire.ActPushConfig: func(context.Context, wire.PushInput) (wire.PushResult, error) {
			return wire.PushResult{}, errUnmocked
		},
		wire.ActRecordStep: func(context.Context, wire.RecordStepInput) (wire.RecordResult, error) {
			return wire.RecordResult{}, errUnmocked
		},
		wire.ActVerifyTwin: func(context.Context, wire.VerifyInput) (wire.VerifyResult, error) {
			return wire.VerifyResult{}, errUnmocked
		},
	}
	for name, fn := range stubs {
		env.RegisterActivityWithOptions(fn, activity.RegisterOptions{Name: name})
	}
	env.SetOnActivityStartedListener(func(info *activity.Info, _ context.Context, args converter.EncodedValues) {
		h.note(info.ActivityType.Name)
		h.mu.Lock()
		h.inputs[info.ActivityType.Name] = append(h.inputs[info.ActivityType.Name], args)
		h.mu.Unlock()
	})
	env.SetOnActivityCanceledListener(func(info *activity.Info) { h.note("cancelled " + info.ActivityType.Name) })
	return h
}

func (h *stepHarness) note(entry string) {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.events = append(h.events, entry)
}

// stepInputs is every input the run gave the activity named name, decoded as the worker
// decodes it off the queue, in the order its attempts started.
func stepInputs[T any](h *stepHarness, name string) []T {
	h.t.Helper()
	h.mu.Lock()
	defer h.mu.Unlock()
	out := make([]T, 0, len(h.inputs[name]))
	for _, args := range h.inputs[name] {
		var in T
		if err := args.Get(&in); err != nil {
			h.t.Fatalf("decoding %s's input: %v", name, err)
		}
		out = append(out, in)
	}
	return out
}

// sameOnTheWire says whether two values marshal alike: an input as it crossed the queue
// beside the one expected, so that an omitted empty list is not a difference.
func sameOnTheWire(t *testing.T, a, b any) bool {
	t.Helper()
	x, err := json.Marshal(a)
	if err != nil {
		t.Fatal(err)
	}
	y, err := json.Marshal(b)
	if err != nil {
		t.Fatal(err)
	}
	return bytes.Equal(x, y)
}

func (h *stepHarness) calls() []string {
	h.mu.Lock()
	defer h.mu.Unlock()
	return append([]string(nil), h.events...)
}

func (h *stepHarness) ran(name string) bool { return slices.Contains(h.calls(), name) }

// record is the record step's one input, failing the test when it ran other than once.
func (h *stepHarness) record() wire.RecordStepInput {
	h.t.Helper()
	h.mu.Lock()
	defer h.mu.Unlock()
	if len(h.recorded) != 1 {
		h.t.Fatalf("the record step ran %d times, want once", len(h.recorded))
	}
	return h.recorded[0]
}

// mockHappyPath answers every activity as case 8's step does on a quiet host. Call it after
// a test's own mocks: the first matching expectation answers.
func (h *stepHarness) mockHappyPath() {
	env := h.env
	env.OnActivity(wire.ActInspectTwin, mock.Anything).Return(h.host, nil)
	env.OnActivity(wire.ActCheckHost, mock.Anything, mock.Anything).Return(h.plan, nil)
	env.OnActivity(wire.ActPlanReconcile, mock.Anything, mock.Anything).Return(h.lab, nil)
	env.OnActivity(wire.ActStageStep, mock.Anything, mock.Anything).Return(wire.StageResult{TwinDir: "/state/twin"}, nil)
	env.OnActivity(wire.ActReconcileLab, mock.Anything, mock.Anything).Return(wire.ReconcileResult{Nodes: stepLab(), TookS: 3.9}, nil)
	env.OnActivity(wire.ActAwaitReadiness, mock.Anything, mock.Anything).Return(
		func(_ context.Context, in wire.ReadinessInput) (wire.ReadinessResult, error) {
			h.mu.Lock()
			h.awaited = append(h.awaited, in.Node)
			h.mu.Unlock()
			return wire.ReadinessResult{Node: in.Node, ReadyAfterS: 54.8}, nil
		})
	env.OnActivity(wire.ActPushConfig, mock.Anything, mock.Anything).Return(h.landed)
	env.OnActivity(wire.ActRecordStep, mock.Anything, mock.Anything).Return(h.recordAs)
	env.OnActivity(wire.ActVerifyTwin, mock.Anything, mock.Anything).Return(settledWait)
}

// landed answers a push as a node that commits its replace does, with the device's diff.
func (h *stepHarness) landed(_ context.Context, in wire.PushInput) (wire.PushResult, error) {
	h.mu.Lock()
	h.pushedTo = append(h.pushedTo, in.Node)
	h.pushDiffs = append(h.pushDiffs, stepDeviceDiff)
	h.mu.Unlock()
	took := map[string]float64{"e1": 1.6, "s1": 2.4}[in.Node]
	return wire.PushResult{Node: in.Node, PushedInS: took, Checksum: in.Checksum, Size: 900, Diff: stepDeviceDiff}, nil
}

// settledWait answers the step's wait as VerifyTwin does on a twin that conforms at its
// second read: settled, written into the record.
func settledWait(_ context.Context, in wire.VerifyInput) (wire.VerifyResult, error) {
	return wire.VerifyResult{Wait: wire.StepWait{Outcome: wire.WaitSettled, BudgetS: in.BudgetS, Reads: 2, AfterS: 2.4,
		From: in.From, EndedAt: "2026-10-02T09:16:13.400000Z", Failing: []wire.StepFinding{}}, Recorded: true}, nil
}

// recordAs answers the record step as RecordStep would, in the record's outline: the
// target's on a stepped or unchanged step, the previous one's, diverged, otherwise.
func (h *stepHarness) recordAs(_ context.Context, in wire.RecordStepInput) (wire.RecordResult, error) {
	h.mu.Lock()
	h.recorded = append(h.recorded, in)
	h.mu.Unlock()
	rec := *h.host.Twin
	rec.State = wire.StateDiverged
	if in.Outcome != wire.StepDiverged {
		rec.BundleID, rec.Waypoint, rec.State = in.To.BundleID, in.To.Waypoint, wire.StateReady
	}
	var phase *string
	if in.Phase != "" {
		p := in.Phase
		phase = &p
	}
	rec.Step = &wire.StepRecord{Outcome: in.Outcome, From: in.From, To: in.To, Phase: phase, Pushed: in.PushPlan,
		Run: wire.RunRef{WorkflowID: WorkflowStep, RunID: in.RunID}, StartedAt: in.StartedAt, EndedAt: in.EndedAt}
	return wire.RecordResult{Path: "/state/twin/twin.json", Record: rec}, nil
}

// run executes Step to completion. A step run returns a result in every case, so a
// workflow error fails the test.
func (h *stepHarness) run(in StepInput) StepResult {
	h.t.Helper()
	h.env.ExecuteWorkflow(Step, in)
	if !h.env.IsWorkflowCompleted() {
		h.t.Fatal("the workflow did not complete")
	}
	if err := h.env.GetWorkflowError(); err != nil {
		h.t.Fatalf("the workflow failed: %v", err)
	}
	var res StepResult
	if err := h.env.GetWorkflowResult(&res); err != nil {
		h.t.Fatal(err)
	}
	return res
}

// stepDocument is the run's document as twin step reports it, validated against this
// feature's contracts, with the device's diff in no part of it.
func stepDocument(t *testing.T, in StepInput, res StepResult) *findings.Document {
	t.Helper()
	doc := StepDocument(&findings.Subject{Waypoint: "demo/2", Branch: "change-1", At: stepToAt, RunID: "default-test-run-id"}, in, res)
	b := mustValidateM11(t, doc)
	if bytes.Contains(b, []byte("insert /")) {
		t.Errorf("the document carries the device's diff:\n%s", b)
	}
	return doc
}

// mustValidateM11 validates a findings document against the current contract, under the
// module root's contracts/, with the step, show, waypoints and verify schemas under their
// $ids, and returns its bytes. The current contract extends M11's additively, so an M11
// document still satisfies it.
func mustValidateM11(t *testing.T, doc *findings.Document) []byte {
	t.Helper()
	load := func(name string) any {
		f, err := os.Open(filepath.Join("..", "..", "contracts", name))
		if err != nil {
			t.Fatal(err)
		}
		defer func() { _ = f.Close() }()
		v, err := jsonschema.UnmarshalJSON(f)
		if err != nil {
			t.Fatal(err)
		}
		return v
	}
	c := jsonschema.NewCompiler()
	for _, name := range []string{"show.schema.json", "waypoints.schema.json", "step.schema.json", "verify.schema.json"} {
		if err := c.AddResource("https://fylgja.dev/schemas/"+name, load(name)); err != nil {
			t.Fatal(err)
		}
	}
	if err := c.AddResource("m11-findings.schema.json", load("findings.schema.json")); err != nil {
		t.Fatal(err)
	}
	schema, err := c.Compile("m11-findings.schema.json")
	if err != nil {
		t.Fatal(err)
	}
	b, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	v, err := jsonschema.UnmarshalJSON(bytes.NewReader(b))
	if err != nil {
		t.Fatal(err)
	}
	if err := schema.Validate(v); err != nil {
		t.Errorf("document does not satisfy contracts/findings.schema.json:\n%v\n%s", err, b)
	}
	return b
}

// rules names a list's findings by rule@step, in order.
func rules(list findings.List) []string {
	out := make([]string, len(list))
	for i, f := range list {
		out[i] = f.Rule + "@" + f.Step
	}
	return out
}

// onlyFinding is the one finding under rule, failing the test when there is not exactly one.
func onlyFinding(t *testing.T, list findings.List, rule string) findings.Finding {
	t.Helper()
	var got []findings.Finding
	for _, f := range list {
		if f.Rule == rule {
			got = append(got, f)
		}
	}
	if len(got) != 1 {
		t.Fatalf("%d %s findings in %v, want one", len(got), rule, rules(list))
	}
	return got[0]
}

// A step that lands every push: the eight steps in order, only the restarted node awaited,
// only the push plan's nodes pushed, the record moved to the target, and the device's diff
// in no result, record input or document. Each activity is given the paths and hashes
// it acts on, and the record and the document
// carry the run's clocks and each phase's duration.
func TestStepStepped(t *testing.T) {
	h := newStepHarness(t)
	h.env.SetStartTime(stepStart)
	// The reconcile holds the run's clock for 4s, so the whole is not zero.
	h.env.OnActivity(wire.ActReconcileLab, mock.Anything, mock.Anything).Return(
		wire.ReconcileResult{Nodes: stepLab(), TookS: 3.9}, nil).After(4 * time.Second)
	h.mockHappyPath()
	in := stepInput()
	res := h.run(in)

	if res.Outcome != StepStepped || res.Phase != "" || res.Step != "" {
		t.Errorf("outcome %q, phase %q, step %q; want stepped with no phase or step", res.Outcome, res.Phase, res.Step)
	}
	want := []string{wire.ActInspectTwin, wire.ActCheckHost, wire.ActPlanReconcile, wire.ActStageStep, wire.ActReconcileLab,
		wire.ActAwaitReadiness, wire.ActPushConfig, wire.ActPushConfig, wire.ActRecordStep, wire.ActVerifyTwin}
	if got := h.calls(); !slices.Equal(got, want) {
		t.Errorf("activities %v\nwant %v", got, want)
	}
	if !slices.Equal(h.awaited, []string{"e1"}) {
		t.Errorf("awaited %v, want only e1, which containerlab restarted", h.awaited)
	}
	if pushed := slices.Sorted(slices.Values(h.pushedTo)); !slices.Equal(pushed, []string{"e1", "s1"}) {
		t.Errorf("pushed %v, want e1 and s1; e2 is untouched", pushed)
	}

	rec := h.record()
	if rec.Outcome != wire.StepStepped || rec.Phase != "" || !rec.ReconcileStarted || rec.Reconcile == nil ||
		rec.RunID != "default-test-run-id" || rec.ObservedAt != in.ObservedAt || rec.TwinDir != "/state/twin" {
		t.Errorf("record input %+v, want stepped, reconciled, this run's id, the target's read", rec)
	}
	if !bytes.Equal(rec.Diff, in.Diff) || !reflect.DeepEqual(rec.To, in.To) || !reflect.DeepEqual(rec.From, in.From) ||
		!rec.AllowRestart || len(rec.Findings) != 0 || !reflect.DeepEqual(rec.Declared, in.Declared) {
		t.Errorf("record input sides, diff, flag, declarations or findings differ from the input: %+v", rec)
	}
	if len(rec.Nodes) != 3 || len(rec.Ready) != 1 || rec.Ready[0].Node != "e1" {
		t.Errorf("record input nodes %v, ready %v; want the three the reconcile reported and e1 awaited", rec.Nodes, rec.Ready)
	}
	for _, p := range rec.PushPlan {
		if p.Outcome != wire.PushLanded || p.TookS == nil {
			t.Errorf("record input push %+v, want landed with its time", p)
		}
	}
	// The push results carried the diff; nothing after them does.
	if len(h.pushDiffs) != 2 {
		t.Fatalf("the mocked pushes returned %d diffs, want 2", len(h.pushDiffs))
	}
	for _, p := range append(append([]wire.PushResult{}, res.Pushed...), rec.Pushed...) {
		if p.Diff != "" {
			t.Errorf("push result %+v carries the device's diff past the push activity", p)
		}
	}
	if len(res.Pushed) != 2 || len(rec.Pushed) != 2 {
		t.Errorf("result pushed %d, record input pushed %d; want both pushes in each", len(res.Pushed), len(rec.Pushed))
	}

	tm := res.Timings
	if tm.ReconcileS == nil || *tm.ReconcileS != 3.9 || tm.Readiness["e1"] != 54.8 || tm.Push["e1"] != 1.6 || tm.Push["s1"] != 2.4 ||
		tm.WholeS != 4 {
		t.Errorf("timings %+v, want reconcile 3.9, readiness e1 54.8, push e1 1.6 and s1 2.4, the whole 4", tm)
	}
	if res.Record == nil || res.Record.State != wire.StateReady {
		t.Errorf("record %+v, want the record the step wrote, ready", res.Record)
	}

	// The run's clocks, RFC 3339 in UTC, are the record's: the pause between two steps is read
	// from one record's ended_at to the next's started_at.
	const started, ended = "2026-10-02T09:15:00Z", "2026-10-02T09:15:04Z"
	if res.StartedAt != started || res.EndedAt != ended || rec.StartedAt != res.StartedAt || rec.EndedAt != res.EndedAt {
		t.Errorf("result started %q ended %q, record input started %q ended %q; want %q and %q in both", res.StartedAt, res.EndedAt,
			rec.StartedAt, rec.EndedAt, started, ended)
	}

	// What the run gave each activity: the target's path and id, the from bundle the twin
	// directory must hold, containerlab's plan as the run read it, and each push's twin
	// directory, artifact and checksum from the target's plan.
	toBundle := wire.CheckHostInput{BundlePath: in.ToBundlePath, BundleID: stepTo}
	if got := stepInputs[wire.CheckHostInput](h, wire.ActCheckHost); !slices.Equal(got, []wire.CheckHostInput{toBundle}) {
		t.Errorf("CheckHost was given %+v, want %+v", got, toBundle)
	}
	planned := wire.PlanReconcileInput{BundlePath: in.ToBundlePath, BundleID: stepTo}
	if got := stepInputs[wire.PlanReconcileInput](h, wire.ActPlanReconcile); !slices.Equal(got, []wire.PlanReconcileInput{planned}) {
		t.Errorf("PlanReconcile was given %+v, want %+v", got, planned)
	}
	staged := wire.StageStepInput{BundlePath: in.ToBundlePath, BundleID: stepTo, FromBundleID: stepFrom}
	if got := stepInputs[wire.StageStepInput](h, wire.ActStageStep); !slices.Equal(got, []wire.StageStepInput{staged}) {
		t.Errorf("StageStep was given %+v, want %+v: the twin directory must hold the from bundle", got, staged)
	}
	reconciled := wire.ReconcileInput{TwinDir: "/state/twin", Nodes: h.plan.Nodes, Plan: h.lab}
	if got := stepInputs[wire.ReconcileInput](h, wire.ActReconcileLab); len(got) != 1 || !sameOnTheWire(t, got[0], reconciled) {
		t.Errorf("ReconcileLab was given %+v\nwant %+v", got, reconciled)
	}
	plans, addr := map[string]wire.NodePlan{}, map[string]string{}
	for _, n := range h.plan.Nodes {
		plans[n.Name] = n
	}
	for _, n := range stepLab() {
		addr[n.Name] = n.MgmtIPv4
	}
	e1 := plans["e1"]
	awaitedIn := wire.ReadinessInput{Node: "e1", MgmtIPv4: addr["e1"], Probe: e1.Probe, TimeoutS: e1.TimeoutS}
	if got := stepInputs[wire.ReadinessInput](h, wire.ActAwaitReadiness); len(got) != 1 || !sameOnTheWire(t, got[0], awaitedIn) {
		t.Errorf("AwaitReadiness was given %+v\nwant %+v", got, awaitedIn)
	}
	pushes := stepInputs[wire.PushInput](h, wire.ActPushConfig)
	if len(pushes) != 2 {
		t.Errorf("PushConfig was given %+v, want one input for each of e1 and s1", pushes)
	}
	for _, got := range pushes {
		n := plans[got.Node]
		want := wire.PushInput{Node: n.Name, MgmtIPv4: addr[n.Name], TwinDir: "/state/twin", Artifact: n.Artifact.File,
			Checksum: n.Artifact.Checksum, Push: n.Push}
		if !sameOnTheWire(t, got, want) {
			t.Errorf("PushConfig was given %+v\nwant %+v", got, want)
		}
	}

	doc := stepDocument(t, in, res)
	if doc.Status != findings.StatusOK || doc.Status.ExitCode() != 0 || doc.Step.Outcome != StepStepped || doc.Step.State != "ready" {
		t.Errorf("document status %s, outcome %q, state %q; want ok, exit 0, stepped, ready", doc.Status, doc.Step.Outcome, doc.Step.State)
	}
	// The document carries each phase's duration and the whole, each awaited node's time,
	// the apply's time and each push's.
	reconcileS := 3.9
	timings := findings.StepTimingsBlock{ReconcileS: &reconcileS, Readiness: map[string]float64{"e1": 54.8},
		Push: map[string]float64{"e1": 1.6, "s1": 2.4}, WholeS: 4}
	if !reflect.DeepEqual(doc.Step.Timings, timings) {
		t.Errorf("document timings %+v, want %+v", doc.Step.Timings, timings)
	}
	if want := []findings.StepReadyAfter{{Node: "e1", ReadyAfterS: 54.8}}; !slices.Equal(doc.Step.ReadyAfter, want) {
		t.Errorf("document ready_after %+v, want %+v", doc.Step.ReadyAfter, want)
	}
	if took := doc.Step.Reconcile.TookS; took == nil || *took != 3.9 {
		t.Errorf("document reconcile took_s %v, want 3.9", took)
	}
	tookS := map[string]float64{"e1": 1.6, "s1": 2.4}
	for _, p := range doc.Step.Pushed {
		if p.Outcome != wire.PushLanded || p.Rule != "" || p.TookS == nil || *p.TookS != tookS[p.Node] {
			t.Errorf("document push %+v, want landed in %vs with no rule", p, tookS[p.Node])
		}
	}
	// The push plan and every push say why the node was pushed.
	reasons := map[string][]string{"e1": {"artifact", "restarted"}, "s1": {"artifact", "bootstrap"}}
	if len(doc.Step.PushPlan) != 2 || len(doc.Step.Pushed) != 2 {
		t.Errorf("document push plan %+v, pushed %+v; want e1 and s1 in each", doc.Step.PushPlan, doc.Step.Pushed)
	}
	for _, p := range doc.Step.PushPlan {
		if !slices.Equal(p.Reasons, reasons[p.Node]) {
			t.Errorf("document push plan entry %+v, want reasons %v", p, reasons[p.Node])
		}
	}
	for _, p := range doc.Step.Pushed {
		if !slices.Equal(p.Reasons, reasons[p.Node]) {
			t.Errorf("document push %+v, want reasons %v", p, reasons[p.Node])
		}
	}
	if doc.Step.StartedAt != started || doc.Step.EndedAt != ended {
		t.Errorf("document started %q ended %q, want %q and %q", doc.Step.StartedAt, doc.Step.EndedAt, started, ended)
	}
}

// The run acts on its own plan: the push plan is
// the CLI's with every node containerlab's plan restarts, recreates or creates given that
// reason, since it runs its baseline until a push lands, and every node it
// deletes dropped, though the plan the CLI read said otherwise.
func TestStepPushPlanTakesTheRunsLifecycle(t *testing.T) {
	cli := []step.NodePush{{Node: "e1", Reasons: []string{step.PushArtifact}},
		{Node: "s2", Reasons: []string{step.PushArtifact, step.PushBootstrap}}}
	for _, c := range []struct {
		name string
		lab  wire.ReconcilePlan
		want []step.NodePush
	}{
		{"the plan the CLI read", wire.ReconcilePlan{}, cli},
		{"a node the CLI pushes, restarted", wire.ReconcilePlan{Restarted: []string{"e1"}}, []step.NodePush{
			{Node: "e1", Reasons: []string{step.PushArtifact, step.PushRestarted}}, cli[1]}},
		{"a node the CLI's plan lacks, recreated", wire.ReconcilePlan{Recreated: []string{"s1"}}, []step.NodePush{
			cli[0], {Node: "s1", Reasons: []string{step.PushRecreated}}, cli[1]}},
		{"a node the CLI's plan lacks, created", wire.ReconcilePlan{Added: []string{"s3"}}, []step.NodePush{
			cli[0], cli[1], {Node: "s3", Reasons: []string{step.PushCreated}}}},
		{"a node the CLI pushes, deleted", wire.ReconcilePlan{Deleted: []string{"s2"}}, []step.NodePush{cli[0]}},
	} {
		t.Run(c.name, func(t *testing.T) {
			if got := withLifecycle(cli, c.lab); !reflect.DeepEqual(got, c.want) {
				t.Errorf("push plan %+v\nwant %+v", got, c.want)
			}
		})
	}
}

// An unchanged step stages the target and records it with nothing reconciled, awaited or
// pushed, even where containerlab's plan would act on
// a lab that drifted by hand: the bundles' content is equal, so nothing is pushed.
func TestStepUnchanged(t *testing.T) {
	for _, c := range []struct {
		name string
		lab  wire.ReconcilePlan
	}{
		{"an empty plan", wire.ReconcilePlan{}},
		{"a plan that would restart a node", wire.ReconcilePlan{Restarted: []string{"e1"}}},
	} {
		t.Run(c.name, func(t *testing.T) { stepUnchanged(t, c.lab) })
	}
}

func stepUnchanged(t *testing.T, lab wire.ReconcilePlan) {
	h := newStepHarness(t)
	h.lab = lab
	h.mockHappyPath()
	in := stepInput()
	in.Unchanged, in.Plan, in.PushPlan = true, lab, nil

	res := h.run(in)
	if res.Outcome != StepUnchanged || res.Phase != "" {
		t.Errorf("outcome %q phase %q, want unchanged", res.Outcome, res.Phase)
	}
	want := []string{wire.ActInspectTwin, wire.ActCheckHost, wire.ActPlanReconcile, wire.ActStageStep, wire.ActRecordStep,
		wire.ActVerifyTwin}
	if got := h.calls(); !slices.Equal(got, want) {
		t.Errorf("activities %v, want %v: nothing reconciled, awaited or pushed, and the wait after the record", got, want)
	}
	rec := h.record()
	if rec.Outcome != wire.StepUnchanged || rec.ReconcileStarted || len(rec.PushPlan) != 0 || len(rec.Nodes) != 3 {
		t.Errorf("record input %+v, want unchanged, no reconcile, no push plan, the inspection's three nodes", rec)
	}
	doc := stepDocument(t, in, res)
	if doc.Status != findings.StatusOK || doc.Step.Outcome != StepUnchanged || !doc.Step.Reconcile.Skipped || len(doc.Step.Pushed) != 0 {
		t.Errorf("document status %s outcome %q skipped %v, want ok, unchanged, skipped", doc.Status, doc.Step.Outcome,
			doc.Step.Reconcile.Skipped)
	}
}

// Each of the run's three locks refuses with nothing staged and no record written: the
// record moved since the CLI looked, or is diverged, or the host is empty (inspect); the
// host check refuses the target (host_check, the presence refusals dropped); containerlab's
// own plan breaks a rule (compare), an unchanged step's included, since the plan's rules still
// apply to it (contracts/cli.md). Exit 1, status rejected. The run
// still ends with its clocks: when it ended, and the whole.
func TestStepRejectedAtEachLock(t *testing.T) {
	phase := "push"
	for _, c := range []struct {
		name    string
		arrange func(h *stepHarness, in *StepInput)
		at      string
		rule    string
		message string
	}{
		{"the record names another bundle", func(h *stepHarness, _ *StepInput) {
			h.host.Twin.BundleID = stepTo
		}, findings.StepInspect, findings.RuleStepTwinUnsteppable,
			"the twin is at waypoint demo/1 (bundle eeeeeeee…), not at waypoint demo/1 (bundle 34343434…) the step was planned from: " +
				"the host changed after the command looked; nothing was touched; run fylgja twin step again"},
		{"the record names another waypoint", func(h *stepHarness, _ *StepInput) {
			w := demo2
			h.host.Twin.Waypoint = &w
		}, findings.StepInspect, findings.RuleStepTwinUnsteppable,
			"the twin is at waypoint demo/2 (bundle 34343434…), not at waypoint demo/1 (bundle 34343434…) the step was planned from: " +
				"the host changed after the command looked; nothing was touched; run fylgja twin step again"},
		{"the record is diverged", func(h *stepHarness, _ *StepInput) {
			h.host.Twin.State = wire.StateDiverged
			h.host.Twin.Step = &wire.StepRecord{Outcome: wire.StepDiverged, Phase: &phase,
				Run: wire.RunRef{WorkflowID: WorkflowStep, RunID: "01a1"}, To: wire.StepSide{Waypoint: &demo2},
				Pushed: []wire.StepPush{{Node: "s1", Outcome: wire.PushLanded}, {Node: "e1", Outcome: wire.PushRefused, Rule: findings.RulePushRefused}}}
		}, findings.StepInspect, findings.RuleStepTwinDiverged,
			"the twin is diverged: step run fylgja-step 01a1 towards waypoint demo/2 stopped at phase push " +
				"(landed: s1; not landed: e1 (push.refused)); it accepts only fylgja twin destroy"},
		{"no twin", func(h *stepHarness, _ *StepInput) {
			h.host = wire.HostReport{}
		}, findings.StepInspect, findings.RuleStepTwinUnsteppable,
			"no twin: no lab fylgja and no twin directory; only a twin built from a waypoint steps (fylgja twin create --waypoint)"},
		{"the target does not fit the host", func(h *stepHarness, _ *StepInput) {
			h.plan.Findings = findings.List{
				{Severity: findings.Rejection, Rule: findings.RuleHostLabPresent, Object: "lab fylgja", Step: findings.StepHostCheck, Message: "lab"},
				{Severity: findings.Rejection, Rule: findings.RuleHostTwinPresent, Object: "/state/twin", Step: findings.StepHostCheck, Message: "dir"},
				{Severity: findings.Rejection, Rule: findings.RuleHostMemoryExceeded, Object: "host", Step: findings.StepHostCheck,
					Message: "the nodes need 6144 MiB, over FYLGJA_HOST_MEMORY_MB 4096"},
			}
		}, findings.StepHostCheck, findings.RuleHostMemoryExceeded, "the nodes need 6144 MiB, over FYLGJA_HOST_MEMORY_MB 4096"},
		{"a package pushes by merge", func(h *stepHarness, _ *StepInput) {
			h.plan.Nodes[2].Push.Mode = "merge"
		}, findings.StepCompare, findings.RuleStepPackageMerge,
			"support package nokia_srlinux pushes by merge, which a step cannot use: a step removes what the previous artifact added, " +
				"and only a replace does that; nodes s1; a create from it is unaffected"},
		{"a change the plan does not apply", func(_ *stepHarness, in *StepInput) {
			in.Changed = []StepChange{{Node: "s1", Changes: []string{step.ReasonPSP}}}
		}, findings.StepCompare, findings.RuleStepNodeUnapplied,
			"node s1 changes in psp between the two bundles, but containerlab's reconcile would not recreate it " +
				"(its plan: live (added link)); the running node would keep its package; a step cannot apply it"},
		{"a restart without the flag", func(_ *stepHarness, in *StepInput) {
			in.AllowRestart = false
		}, findings.StepCompare, findings.RuleStepRestartRequired,
			"containerlab would restart e1 (added link; package arista_eos declares restart): it loses its running state and its push " +
				"until the step pushes it again; give --allow-restart to proceed, or --dry-run to see the step"},
		{"an unchanged step's restart without the flag", func(_ *stepHarness, in *StepInput) {
			in.Unchanged, in.PushPlan, in.AllowRestart = true, nil, false
		}, findings.StepCompare, findings.RuleStepRestartRequired,
			"containerlab would restart e1 (added link; package arista_eos declares restart): it loses its running state and its push " +
				"until the step pushes it again; give --allow-restart to proceed, or --dry-run to see the step"},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := newStepHarness(t)
			h.env.SetStartTime(stepStart)
			in := stepInput()
			c.arrange(h, &in)
			// The inspection holds the run's clock for a second, so the whole is not zero.
			h.env.OnActivity(wire.ActInspectTwin, mock.Anything).Return(h.host, nil).After(time.Second)
			h.mockHappyPath()
			res := h.run(in)

			if res.Outcome != OutcomeRejected || res.Step != c.at || res.Phase != "" {
				t.Errorf("outcome %q at %q phase %q, want rejected at %q", res.Outcome, res.Step, res.Phase, c.at)
			}
			if res.StartedAt != "2026-10-02T09:15:00Z" || res.EndedAt != "2026-10-02T09:15:01Z" || res.Timings.WholeS != 1 {
				t.Errorf("started %q ended %q whole %v, want 2026-10-02T09:15:00Z, 2026-10-02T09:15:01Z and 1", res.StartedAt,
					res.EndedAt, res.Timings.WholeS)
			}
			if f := onlyFinding(t, res.Findings, c.rule); f.Step != c.at || f.Message != c.message {
				t.Errorf("%s at %q: %q\nwant at %q: %q", c.rule, f.Step, f.Message, c.at, c.message)
			}
			for _, presence := range []string{findings.RuleHostLabPresent, findings.RuleHostTwinPresent} {
				if carries(res.Findings, presence, findings.StepHostCheck) {
					t.Errorf("findings %v carry %s, which names the twin itself", rules(res.Findings), presence)
				}
			}
			for _, untouched := range []string{wire.ActStageStep, wire.ActReconcileLab, wire.ActPushConfig, wire.ActRecordStep} {
				if h.ran(untouched) {
					t.Errorf("activities %v: %s ran after a refusal", h.calls(), untouched)
				}
			}
			doc := stepDocument(t, in, res)
			if doc.Status != findings.StatusRejected || doc.Status.ExitCode() != findings.ExitRejected || doc.Step.Outcome != "" {
				t.Errorf("document status %s exit %d outcome %q, want rejected, exit 1, no outcome", doc.Status,
					doc.Status.ExitCode(), doc.Step.Outcome)
			}
			if doc.Step.EndedAt != res.EndedAt || doc.Step.Timings.WholeS != 1 {
				t.Errorf("document ended %q whole %v, want the run's %q and 1", doc.Step.EndedAt, doc.Step.Timings.WholeS, res.EndedAt)
			}
		})
	}
}

// A step that could not run before its stage is error, exit 2, under its activity's finding
// or operation.failed at that step, with nothing touched and no record written
// (contracts/cli.md, the run's second locks). An error that names
// nothing is operation.failed on the step itself; one whose details carry a finding, as
// lab.StepFailure's do, keeps it whole.
func TestStepErrorBeforeTheStage(t *testing.T) {
	for _, c := range []struct {
		name, at string
		mock     func(h *stepHarness, err error)
		carried  error // what the activity returns that names its own finding
	}{
		{"inspect", findings.StepInspect, func(h *stepHarness, err error) {
			h.env.OnActivity(wire.ActInspectTwin, mock.Anything).Return(wire.HostReport{}, err)
		}, lab.StepFailure(findings.StepInspect, findings.RuleOperationFailed, "lab fylgja", "clab inspect --all exited 1")},
		{"host_check", findings.StepHostCheck, func(h *stepHarness, err error) {
			h.env.OnActivity(wire.ActCheckHost, mock.Anything, mock.Anything).Return(wire.CheckHostResult{}, err)
		}, lab.StepFailure(findings.StepHostCheck, findings.RuleOperationFailed, "FYLGJA_HOST_MEMORY_MB",
			`FYLGJA_HOST_MEMORY_MB is "lots", not a whole number of MiB`)},
		{"compare", findings.StepCompare, func(h *stepHarness, err error) {
			h.env.OnActivity(wire.ActPlanReconcile, mock.Anything, mock.Anything).Return(wire.ReconcilePlan{}, err)
		}, lab.StepFailure(findings.StepCompare, findings.RuleOperationFailed, "/state/bundles/"+stepTo,
			"clab deploy --dry-run exited 1")},
	} {
		for _, named := range []bool{false, true} {
			name := c.name + ", an error that names nothing"
			err := errors.New("the docker daemon did not answer")
			if named {
				name, err = c.name+", an error that carries its finding", c.carried
			}
			t.Run(name, func(t *testing.T) {
				h := newStepHarness(t)
				c.mock(h, err)
				h.mockHappyPath()
				in := stepInput()
				res := h.run(in)

				if res.Outcome != OutcomeError || res.Step != c.at || res.Phase != "" {
					t.Errorf("outcome %q step %q phase %q, want error at %q", res.Outcome, res.Step, res.Phase, c.at)
				}
				f := onlyFinding(t, res.Findings, findings.RuleOperationFailed)
				switch {
				case named:
					var appErr *temporal.ApplicationError
					var want findings.Finding
					if !errors.As(c.carried, &appErr) || appErr.Details(&want) != nil {
						t.Fatal("the carried error has no finding")
					}
					if f != want {
						t.Errorf("finding %+v\nwant the activity's own %+v", f, want)
					}
				case f.Step != c.at || f.Object != c.at || !strings.Contains(f.Message, "the docker daemon did not answer"):
					t.Errorf("operation.failed %+v, want at %q on %q, carrying the activity's error", f, c.at, c.at)
				}
				if carries(res.Findings, findings.RuleRunCancelled, c.at) {
					t.Errorf("findings %v carry run.cancelled", rules(res.Findings))
				}
				for _, untouched := range []string{wire.ActStageStep, wire.ActReconcileLab, wire.ActPushConfig, wire.ActRecordStep} {
					if h.ran(untouched) {
						t.Errorf("activities %v: %s ran after a step that could not run", h.calls(), untouched)
					}
				}
				doc := stepDocument(t, in, res)
				if doc.Status != findings.StatusError || doc.Status.ExitCode() != findings.ExitError || doc.Step.Outcome != "" ||
					doc.Step.State != "" {
					t.Errorf("document status %s exit %d outcome %q state %q, want error, exit 2, no outcome and no state",
						doc.Status, doc.Status.ExitCode(), doc.Step.Outcome, doc.Step.State)
				}
			})
		}
	}
}

// --allow-restart lets the restart through; containerlab's own plan restarting a node whose
// package declares live is acted on, with the warning, and that node is awaited and pushed
// though the CLI's plan had it live.
func TestStepActsOnItsOwnPlan(t *testing.T) {
	h := newStepHarness(t)
	h.lab.Restarted = []string{"e1", "s1"}
	h.mockHappyPath()
	in := stepInput()
	res := h.run(in)

	if res.Outcome != StepStepped {
		t.Fatalf("outcome %q, want stepped: %v", res.Outcome, rules(res.Findings))
	}
	want := "package nokia_srlinux declares that a link change is live, but containerlab's plan restarts s1 (added link); " +
		"the step acts on containerlab's plan and records both"
	if f := onlyFinding(t, res.Findings, findings.RuleStepRestartUndeclared); f.Severity != findings.Warning || f.Message != want ||
		f.Object != "s1" || f.Step != findings.StepCompare {
		t.Errorf("warning %+v\nwant %q on s1 at compare", f, want)
	}
	if got := slices.Sorted(slices.Values(h.awaited)); !slices.Equal(got, []string{"e1", "s1"}) {
		t.Errorf("awaited %v, want e1 and s1, both restarted by the run's plan", got)
	}
	plan := h.record().PushPlan
	if len(plan) != 2 || plan[1].Node != "s1" || !slices.Equal(plan[1].Reasons, []string{"artifact", "bootstrap", "restarted"}) {
		t.Errorf("push plan %+v, want s1 pushed for its artifact, its bootstrap and its restart", plan)
	}
	// The record carries the plan the run acted on, the one PlanReconcile read, never the
	// CLI's: twin.json's reconcile block must say what containerlab did.
	if got := h.record().Plan; !reflect.DeepEqual(got, h.lab) || reflect.DeepEqual(got, in.Plan) {
		t.Errorf("the record's plan is %+v; want the run's own %+v, not the CLI's %+v", got, h.lab, in.Plan)
	}
	// So does the document, once the run read its own (contracts/cli.md).
	if got := stepDocument(t, in, res).Step.Reconcile.Restarted; !slices.Equal(got, h.lab.Restarted) {
		t.Errorf("the document's reconcile restarts %v; want the run's own plan's %v, not the CLI's %v", got, h.lab.Restarted,
			in.Plan.Restarted)
	}
}

// From the stage on, every failure leaves the twin up and diverged: the record step runs,
// the record names the phase and each push's outcome, step.diverged is added, and the status
// is diverged, exit 4.
func TestStepDivergedAtEachPhase(t *testing.T) {
	failure := func(rule, step, object, message string) error {
		return temporal.NewNonRetryableApplicationError(message, rule, nil,
			findings.Finding{Severity: findings.Rejection, Rule: rule, Object: object, Step: step, Message: message})
	}
	for _, c := range []struct {
		name             string
		arrange          func(h *stepHarness)
		phase, at, rule  string
		reconcileStarted bool
		pushes           map[string]string // node → outcome in the record's push plan
		diverged         string
	}{
		{"the stage", func(h *stepHarness) {
			h.env.OnActivity(wire.ActStageStep, mock.Anything, mock.Anything).Return(wire.StageResult{},
				failure(findings.RuleStageFailed, findings.StepStage, "/state/twin/bundle", "twin/bundle holds bundle 5151…"))
		}, findings.StepReconcile, findings.StepStage, findings.RuleStageFailed, false,
			map[string]string{"e1": wire.PushNotAttempted, "s1": wire.PushNotAttempted},
			"step run default-test-run-id towards waypoint demo/2 (bundle eeeeeeee…) stopped at phase reconcile: landed none; " +
				"not landed e1, s1; the twin is up and diverged at waypoint demo/1 (bundle 34343434…), its record says so, " +
				"and it accepts only fylgja twin destroy"},
		{"the reconcile", func(h *stepHarness) {
			h.env.OnActivity(wire.ActReconcileLab, mock.Anything, mock.Anything).Return(wire.ReconcileResult{},
				failure(findings.RuleDeployFailed, findings.StepReconcile, "lab fylgja", "clab deploy exited 1"))
		}, findings.StepReconcile, findings.StepReconcile, findings.RuleDeployFailed, true,
			map[string]string{"e1": wire.PushNotAttempted, "s1": wire.PushNotAttempted}, ""},
		{"readiness", func(h *stepHarness) {
			h.env.OnActivity(wire.ActAwaitReadiness, mock.Anything, mock.Anything).Return(wire.ReadinessResult{},
				failure(findings.RuleReadinessTimeout, findings.StepReadiness, "e1", "node e1 did not answer within 180s"))
		}, findings.StepReadiness, findings.StepReadiness, findings.RuleReadinessTimeout, true,
			map[string]string{"e1": wire.PushNotAttempted, "s1": wire.PushNotAttempted}, ""},
		{"one push of two", func(h *stepHarness) {
			h.env.OnActivity(wire.ActPushConfig, mock.Anything, mock.MatchedBy(func(in wire.PushInput) bool { return in.Node == "e1" })).
				Return(wire.PushResult{}, failure(findings.RulePushRefused, findings.StepPush, "e1",
					"node e1 refused artifact device-config (checksum aaaa…) at line 7: Invalid input (at token 0: 'bogus')"))
		}, findings.StepPush, findings.StepPush, findings.RulePushRefused, true,
			map[string]string{"e1": wire.PushRefused, "s1": wire.PushLanded},
			"step run default-test-run-id towards waypoint demo/2 (bundle eeeeeeee…) stopped at phase push: landed s1; " +
				"not landed e1 (push.refused); the twin is up and diverged at waypoint demo/1 (bundle 34343434…), its record says so, " +
				"and it accepts only fylgja twin destroy"},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := newStepHarness(t)
			c.arrange(h)
			h.mockHappyPath()
			in := stepInput()
			res := h.run(in)

			if res.Outcome != StepDiverged || res.Phase != c.phase || res.Step != c.at {
				t.Errorf("outcome %q phase %q step %q, want diverged at phase %q, step %q", res.Outcome, res.Phase, res.Step, c.phase, c.at)
			}
			if f := onlyFinding(t, res.Findings, c.rule); f.Step != c.at {
				t.Errorf("%s at %q, want at %q", c.rule, f.Step, c.at)
			}
			d := onlyFinding(t, res.Findings, findings.RuleStepDiverged)
			if d.Step != c.phase || d.Object != "default-test-run-id" || (c.diverged != "" && d.Message != c.diverged) {
				t.Errorf("step.diverged %+v\nwant at %q naming the run: %q", d, c.phase, c.diverged)
			}
			if strings.Contains(d.Message, "insert") || carries(res.Findings, findings.RuleRunCancelled, c.phase) {
				t.Errorf("findings %v carry a diff line or a cancellation", rules(res.Findings))
			}
			rec := h.record()
			if rec.Outcome != wire.StepDiverged || rec.Phase != c.phase || rec.ReconcileStarted != c.reconcileStarted {
				t.Errorf("record input outcome %q phase %q reconcile started %v, want diverged at %q, %v", rec.Outcome, rec.Phase,
					rec.ReconcileStarted, c.phase, c.reconcileStarted)
			}
			for _, p := range rec.PushPlan {
				if p.Outcome != c.pushes[p.Node] {
					t.Errorf("record input push %+v, want outcome %q", p, c.pushes[p.Node])
				}
			}
			if !carries(rec.Findings, c.rule, c.at) || carries(rec.Findings, findings.RuleStepDiverged, c.phase) {
				t.Errorf("record input findings %v, want the failure's and not step.diverged", rules(rec.Findings))
			}
			if c.phase == findings.StepReadiness && h.ran(wire.ActPushConfig) {
				t.Errorf("activities %v: a push ran before every restarted node was ready", h.calls())
			}
			if c.at == findings.StepStage && h.ran(wire.ActReconcileLab) {
				t.Errorf("activities %v: the reconcile ran after the stage failed", h.calls())
			}
			doc := stepDocument(t, in, res)
			if doc.Status != findings.StatusDiverged || doc.Status.ExitCode() != 4 || doc.Step.Outcome != StepDiverged ||
				doc.Step.Phase != c.phase || doc.Step.State != wire.StateDiverged {
				t.Errorf("document status %s exit %d outcome %q phase %q state %q, want diverged, 4, diverged, %q, diverged",
					doc.Status, doc.Status.ExitCode(), doc.Step.Outcome, doc.Step.Phase, doc.Step.State, c.phase)
			}
			// The document's pushes are the run's: each node's outcome, the identifier of the
			// finding that says why it did not land, and the time of one that did.
			if len(doc.Step.Pushed) != len(rec.PushPlan) {
				t.Fatalf("document pushed %+v, want the record input's %+v", doc.Step.Pushed, rec.PushPlan)
			}
			for i, p := range doc.Step.Pushed {
				if want := rec.PushPlan[i]; p.Node != want.Node || p.Outcome != want.Outcome || p.Rule != want.Rule ||
					!reflect.DeepEqual(p.TookS, want.TookS) {
					t.Errorf("document push %+v, want the record input's %+v", p, want)
				}
			}
		})
	}
}

// A readiness that fails for one node of two keeps the node that answered: the result, the
// record's input, the timings and the document name it, and readiness.timeout ends with it,
// as the provisioning run's readiness words it ("the timings reached"). Nothing is pushed.
func TestStepReadinessFailureKeepsTheNodesThatAnswered(t *testing.T) {
	h := newStepHarness(t)
	h.lab.Restarted = []string{"e1", "s1"}
	h.env.OnActivity(wire.ActAwaitReadiness, mock.Anything, mock.Anything).Return(
		func(_ context.Context, in wire.ReadinessInput) (wire.ReadinessResult, error) {
			if in.Node == "e1" {
				return wire.ReadinessResult{}, lab.StepFailure(findings.StepReadiness, findings.RuleReadinessTimeout, "e1",
					"node e1 did not answer within 180s")
			}
			return wire.ReadinessResult{Node: in.Node, ReadyAfterS: 12.3}, nil
		})
	h.mockHappyPath()
	in := stepInput()
	res := h.run(in)

	if res.Outcome != StepDiverged || res.Phase != findings.StepReadiness || res.Step != findings.StepReadiness {
		t.Errorf("outcome %q phase %q step %q, want diverged at readiness", res.Outcome, res.Phase, res.Step)
	}
	answered := []wire.ReadinessResult{{Node: "s1", ReadyAfterS: 12.3}}
	if !reflect.DeepEqual(res.Ready, answered) {
		t.Errorf("result ready %+v, want %+v", res.Ready, answered)
	}
	if rec := h.record(); !reflect.DeepEqual(rec.Ready, answered) {
		t.Errorf("record input ready %+v, want %+v", rec.Ready, answered)
	}
	if got := res.Timings.Readiness; !maps.Equal(got, map[string]float64{"s1": 12.3}) {
		t.Errorf("timings readiness %v, want s1 alone, in 12.3s", got)
	}
	want := "node e1 did not answer within 180s; ready: s1 in 12.3s"
	if f := onlyFinding(t, res.Findings, findings.RuleReadinessTimeout); f.Object != "e1" || f.Message != want {
		t.Errorf("readiness.timeout %+v\nwant on e1: %q", f, want)
	}
	if h.ran(wire.ActPushConfig) {
		t.Errorf("activities %v: a push ran before every restarted node was ready", h.calls())
	}
	doc := stepDocument(t, in, res)
	if want := []findings.StepReadyAfter{{Node: "s1", ReadyAfterS: 12.3}}; !slices.Equal(doc.Step.ReadyAfter, want) {
		t.Errorf("document ready_after %+v, want %+v", doc.Step.ReadyAfter, want)
	}
	if got := doc.Step.Timings.Readiness; !maps.Equal(got, map[string]float64{"s1": 12.3}) {
		t.Errorf("document timings readiness %v, want s1 alone, in 12.3s", got)
	}
}

// A push that failed without the activity wording it — a heartbeat timeout the service
// raised, the worker gone — names the artifact and checksum the node was taking, from the
// plan, as the provisioning run's push words it, and the step is diverged at push: a push
// transport that stalls.
func TestStepPushFailureTheActivityNeverWordedNamesTheArtifact(t *testing.T) {
	h := newStepHarness(t)
	h.env.OnActivity(wire.ActPushConfig, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, in wire.PushInput) (wire.PushResult, error) {
			if in.Node == "e1" {
				return wire.PushResult{}, temporal.NewHeartbeatTimeoutError()
			}
			return h.landed(ctx, in)
		})
	h.mockHappyPath()
	in := stepInput()
	res := h.run(in)

	if res.Outcome != StepDiverged || res.Phase != findings.StepPush || res.Step != findings.StepPush {
		t.Errorf("outcome %q phase %q step %q, want diverged at push", res.Outcome, res.Phase, res.Step)
	}
	want := "the push of artifact device-config (checksum " + h.plan.Nodes[0].Artifact.Checksum + ") to e1 failed: " +
		"no heartbeat from the worker reached the workflow service within the heartbeat timeout"
	if f := onlyFinding(t, res.Findings, findings.RulePushFailed); f.Object != "e1" || f.Step != findings.StepPush ||
		!strings.HasPrefix(f.Message, want) || !strings.HasSuffix(f.Message, "; pushed: s1 in 2.4s") {
		t.Errorf("push.failed %+v\nwant on e1 at push, beginning %q and ending \"; pushed: s1 in 2.4s\"", f, want)
	}
	rec := h.record()
	outcomes := map[string]string{"e1": wire.PushFailed + " " + findings.RulePushFailed, "s1": wire.PushLanded + " "}
	for _, p := range rec.PushPlan {
		if got := p.Outcome + " " + p.Rule; got != outcomes[p.Node] {
			t.Errorf("record input push %+v, want %q", p, outcomes[p.Node])
		}
	}
	if d := onlyFinding(t, res.Findings, findings.RuleStepDiverged); !strings.Contains(d.Message, "landed s1; not landed e1 (push.failed);") {
		t.Errorf("step.diverged %q, want it to name s1 landed and e1 not landed (push.failed)", d.Message)
	}
	stepDocument(t, in, res)
}

// A node containerlab restarted or recreated is awaited and pushed as a create awaits and
// pushes it: under its own package's probe and
// readiness.timeout_s, waiting for its push transport where the package declares
// await_push_transport (D-029), and at the address containerlab reported after the
// reconcile, which for a node it created is the only one there is. The plans are the
// shipped packages', as lab.CheckHost builds them, so a wait a create has and a step lacks
// fails here rather than live, where D-029 was found.
func TestStepAwaitsAndPushesATouchedNodeAsACreateDoes(t *testing.T) {
	h := newStepHarness(t)
	h.plan = mixedCheckHost(t)
	h.lab = wire.ReconcilePlan{Restarted: []string{"e1"}, Recreated: []string{"s1"}, LinksAdded: []string{"e1:eth3 -- s1:e1-3"},
		Reasons: map[string]string{"e1": "added link", "s1": "config drift: Image"}}
	// containerlab reports e1 and s1 at addresses the inspection before the stage did not.
	reconciled := stepLab()
	reconciled[0].MgmtIPv4, reconciled[2].MgmtIPv4 = "172.20.20.12", "172.20.20.14"
	h.env.OnActivity(wire.ActReconcileLab, mock.Anything, mock.Anything).Return(
		wire.ReconcileResult{Nodes: reconciled, TookS: 20.3}, nil)
	var mu sync.Mutex
	awaited := map[string]wire.ReadinessInput{}
	pushed := map[string]wire.PushInput{}
	h.env.OnActivity(wire.ActAwaitReadiness, mock.Anything, mock.Anything).Return(
		func(_ context.Context, in wire.ReadinessInput) (wire.ReadinessResult, error) {
			mu.Lock()
			awaited[in.Node] = in
			mu.Unlock()
			return wire.ReadinessResult{Node: in.Node, ReadyAfterS: 54.2}, nil
		})
	h.env.OnActivity(wire.ActPushConfig, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, in wire.PushInput) (wire.PushResult, error) {
			mu.Lock()
			pushed[in.Node] = in
			mu.Unlock()
			return h.landed(ctx, in)
		})
	h.mockHappyPath()
	res := h.run(stepInput())
	if res.Outcome != StepStepped {
		t.Fatalf("outcome %q with %+v, want stepped", res.Outcome, res.Findings)
	}
	mu.Lock()
	defer mu.Unlock()

	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	pkg := func(id string) *psp.PSP {
		p, ok := reg.LookupID(id)
		if !ok {
			t.Fatalf("no shipped package %s", id)
		}
		return p
	}
	eos, srl := pkg("arista_eos"), pkg("nokia_srlinux")
	if !eos.Readiness.AwaitPushTransport || srl.Readiness.AwaitPushTransport {
		t.Fatal("the shipped packages no longer differ in await_push_transport, which this test relies on")
	}
	plans := map[string]wire.NodePlan{}
	for _, n := range h.plan.Nodes {
		plans[n.Name] = n
	}
	for _, c := range []struct {
		node    string
		timeout int
		scheme  string
		port    int
	}{
		{"e1", eos.Readiness.TimeoutS, eos.Config.Push.Scheme, eos.Config.Push.Port}, // restarted, and its package waits
		{"s1", srl.Readiness.TimeoutS, "", 0},                                        // recreated, and its package does not
	} {
		in, ok := awaited[c.node]
		switch {
		case !ok:
			t.Errorf("%s was not awaited", c.node)
		case in.AwaitPushScheme != c.scheme || in.AwaitPushPort != c.port:
			t.Errorf("%s was awaited with push transport %q:%d, want %q:%d", c.node, in.AwaitPushScheme, in.AwaitPushPort,
				c.scheme, c.port)
		case !sameProbe(in.Probe, plans[c.node].Probe) || in.TimeoutS != c.timeout:
			t.Errorf("%s was probed %+v within %ds, want its package's %+v within %ds", c.node, in.Probe, in.TimeoutS,
				plans[c.node].Probe, c.timeout)
		}
	}
	if _, ok := awaited["e2"]; ok || len(awaited) != 2 {
		t.Errorf("awaited %v, want e1 and s1 alone: containerlab left e2 alone", slices.Sorted(maps.Keys(awaited)))
	}

	// Every address is the one containerlab reported after the reconcile.
	addr := map[string]string{}
	for _, n := range reconciled {
		addr[n.Name] = n.MgmtIPv4
	}
	for node, in := range awaited {
		if in.MgmtIPv4 != addr[node] {
			t.Errorf("%s was awaited at %q, want %q, the address the reconcile reported", node, in.MgmtIPv4, addr[node])
		}
	}
	for node, in := range pushed {
		if in.MgmtIPv4 != addr[node] {
			t.Errorf("%s was pushed at %q, want %q, the address the reconcile reported", node, in.MgmtIPv4, addr[node])
		}
	}
	if len(pushed) != 2 {
		t.Errorf("pushed %v, want e1 and s1", slices.Sorted(maps.Keys(pushed)))
	}
}

// A record that cannot be written is record.failed at phase record, the twin diverged, and
// step.diverged says the record still claims the twin is ready where it was.
func TestStepDivergedAtTheRecord(t *testing.T) {
	h := newStepHarness(t)
	h.env.OnActivity(wire.ActRecordStep, mock.Anything, mock.Anything).Return(wire.RecordResult{},
		temporal.NewNonRetryableApplicationError("writing twin.json: disk full", findings.RuleRecordFailed, nil,
			findings.Finding{Severity: findings.Rejection, Rule: findings.RuleRecordFailed, Object: "/state/twin/twin.json",
				Step: findings.StepRecord, Message: "writing /state/twin/twin.json: disk full"}))
	h.mockHappyPath()
	in := stepInput()
	res := h.run(in)

	if res.Outcome != StepDiverged || res.Phase != findings.StepRecord || res.Step != findings.StepRecord || res.Record != nil {
		t.Errorf("outcome %q phase %q step %q record %v, want diverged at the record with none written", res.Outcome, res.Phase,
			res.Step, res.Record)
	}
	onlyFinding(t, res.Findings, findings.RuleRecordFailed)
	want := "step run default-test-run-id towards waypoint demo/2 (bundle eeeeeeee…) stopped at phase record: landed e1, s1; " +
		"not landed none; the twin is up and diverged at waypoint demo/1 (bundle 34343434…), but its record could not be written " +
		"and still says it is ready there; fylgja twin destroy clears it"
	if d := onlyFinding(t, res.Findings, findings.RuleStepDiverged); d.Message != want || d.Step != findings.StepRecord {
		t.Errorf("step.diverged %+v\nwant %q", d, want)
	}
	doc := stepDocument(t, in, res)
	if doc.Status != findings.StatusDiverged || doc.Step.State != "" {
		t.Errorf("document status %s state %q, want diverged and no state, since no record was written", doc.Status, doc.Step.State)
	}
}

// stepCanceller cancels the run from inside the activity under test, then holds that
// activity as a running one is held, until the cancellation reaches it.
type stepCanceller struct {
	h       *stepHarness
	cancel  sync.Once
	reach   sync.Once
	reached chan struct{}
}

func newStepCanceller(h *stepHarness) *stepCanceller {
	c := &stepCanceller{h: h, reached: make(chan struct{})}
	h.env.SetOnActivityCanceledListener(func(info *activity.Info) {
		h.note("cancelled " + info.ActivityType.Name)
		c.reach.Do(func() { close(c.reached) })
	})
	return c
}

func (c *stepCanceller) block(ctx context.Context) error {
	c.cancel.Do(c.h.env.CancelWorkflow)
	select {
	case <-c.reached:
	case <-ctx.Done():
	case <-time.After(5 * time.Second):
		return errors.New("the cancellation never reached the activity")
	}
	return context.Canceled
}

// A cancellation before the stage touches nothing and writes no record: cancelled, exit 2,
// run.cancelled "before the host was touched". From the stage on, the cancellation reaches
// the running step, and then the record step runs where the cancellation does not reach it,
// writing the record diverged: run.cancelled beside step.diverged, exit 4.
//
// Each step is cancelled as the test suite cancels it, the cancellation reaching the
// activity. InspectTwin, CheckHost, PlanReconcile and StageStep never heartbeat, so against
// the service the cancellation never reaches them: each returns its result, and the run sees
// the cancellation when it next looks. ReconcileLab, AwaitReadiness and
// PushConfig heartbeat, but each can return its result after the cancellation and before its
// next heartbeat, and WaitForCancellation then hands the run that result with no error. Each
// step is cancelled that way too, "never reached", through cancelWatch.
//
// The stage and the reconcile are each also failed with an error of their own after the
// cancellation, as a lost heartbeat or a clab deploy failure racing twin destroy would. The
// run's context alone says the run was cancelled, and the activity's finding is kept before
// run.cancelled. A cancellation that reaches either carries no finding of its own.
func TestStepCancelled(t *testing.T) {
	for _, c := range []struct {
		name                string
		activity, at, phase string
		unheard             bool   // the cancellation never reaches the activity, as against the service
		failed              string // the rule the activity fails under after the cancellation, or none
		mock                func(h *stepHarness, cancel func(context.Context) error)
	}{
		{"inspect", wire.ActInspectTwin, findings.StepInspect, "", false, "", mockInspectCancelled},
		{"inspect, never reached", wire.ActInspectTwin, findings.StepInspect, "", true, "", mockInspectCancelled},
		{"host_check", wire.ActCheckHost, findings.StepHostCheck, "", false, "", mockCheckHostCancelled},
		{"host_check, never reached", wire.ActCheckHost, findings.StepHostCheck, "", true, "", mockCheckHostCancelled},
		{"compare", wire.ActPlanReconcile, findings.StepCompare, "", false, "", mockCompareCancelled},
		{"compare, never reached", wire.ActPlanReconcile, findings.StepCompare, "", true, "", mockCompareCancelled},
		{"stage", wire.ActStageStep, findings.StepStage, findings.StepReconcile, false, "", mockStageCancelled},
		{"stage, never reached", wire.ActStageStep, findings.StepStage, findings.StepReconcile, true, "", mockStageCancelled},
		{"stage, failed after the cancellation", wire.ActStageStep, findings.StepStage, findings.StepReconcile, true,
			findings.RuleStageFailed, mockStageFailedAfterTheCancellation},
		{"reconcile", wire.ActReconcileLab, findings.StepReconcile, findings.StepReconcile, false, "", mockReconcileCancelled},
		{"reconcile, never reached", wire.ActReconcileLab, findings.StepReconcile, findings.StepReconcile, true, "", mockReconcileCancelled},
		{"reconcile, failed after the cancellation", wire.ActReconcileLab, findings.StepReconcile, findings.StepReconcile, true,
			findings.RuleDeployFailed, mockReconcileFailedAfterTheCancellation},
		{"readiness, never reached", wire.ActAwaitReadiness, findings.StepReadiness, findings.StepReadiness, true, "", mockReadinessCancelled},
		{"push", wire.ActPushConfig, findings.StepPush, findings.StepPush, false, "", mockPushCancelled},
		{"push, never reached", wire.ActPushConfig, findings.StepPush, findings.StepPush, true, "", mockPushCancelled},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := newStepHarness(t)
			if c.unheard {
				w := newCancelWatch(h, c.activity)
				c.mock(h, func(context.Context) error { return w.cancel() })
			} else {
				c.mock(h, newStepCanceller(h).block)
			}
			h.mockHappyPath()
			in := stepInput()
			res := h.run(in)

			if res.Outcome != OutcomeCancelled || res.Step != c.at || res.Phase != c.phase {
				t.Errorf("outcome %q step %q phase %q, want cancelled at %q, phase %q", res.Outcome, res.Step, res.Phase, c.at, c.phase)
			}
			calls := h.calls()
			reached := slices.Index(calls, "cancelled "+c.activity)
			switch {
			case c.unheard && reached >= 0:
				t.Fatalf("the cancellation reached %s, which here it must not: %v", c.activity, calls)
			case c.unheard:
				reached = slices.Index(calls, c.activity)
			case reached < 0:
				t.Fatalf("the cancellation never reached %s: %v", c.activity, calls)
			}
			cancelled := onlyFinding(t, res.Findings, findings.RuleRunCancelled)
			doc := stepDocument(t, in, res)
			if c.phase == "" {
				want := "run default-test-run-id was cancelled at step " + c.at + ", before the host was touched; nothing on the host " +
					"was touched and the record is unchanged"
				if cancelled.Message != want || cancelled.Step != c.at {
					t.Errorf("run.cancelled %+v\nwant %q at %q", cancelled, want, c.at)
				}
				if h.ran(wire.ActStageStep) || h.ran(wire.ActRecordStep) || carries(res.Findings, findings.RuleStepDiverged, "") {
					t.Errorf("activities %v, findings %v: a cancellation before the stage touched the host", calls, rules(res.Findings))
				}
				if doc.Status != findings.StatusError || doc.Status.ExitCode() != findings.ExitError {
					t.Errorf("document status %s exit %d, want error, exit 2", doc.Status, doc.Status.ExitCode())
				}
				return
			}
			want := "run default-test-run-id was cancelled at step " + c.at + "; the record was written diverged and nothing was torn down"
			if cancelled.Message != want || cancelled.Step != c.phase {
				t.Errorf("run.cancelled %+v\nwant %q at %q", cancelled, want, c.phase)
			}
			onlyFinding(t, res.Findings, findings.RuleStepDiverged)
			record := slices.Index(calls, wire.ActRecordStep)
			if record < reached || slices.Contains(calls, "cancelled "+wire.ActRecordStep) {
				t.Errorf("order %v: want the cancellation to reach %s, then the record, uncancelled", calls, c.activity)
			}
			rec := h.record()
			if rec.Outcome != wire.StepDiverged || rec.Phase != c.phase || !carries(rec.Findings, findings.RuleRunCancelled, c.phase) {
				t.Errorf("record input %q at %q with %v, want diverged at %q carrying run.cancelled", rec.Outcome, rec.Phase,
					rules(rec.Findings), c.phase)
			}
			if c.at == findings.StepStage || c.at == findings.StepReconcile {
				// The run's context says the run was cancelled, whatever the activity returned. A
				// cancellation adds no finding of its own; an error of the activity's own after it
				// keeps its finding, first (stepStopAt; M2's stopAt).
				var want []string
				if c.failed != "" {
					want = append(want, c.failed+"@"+c.at)
				}
				want = append(want, findings.RuleRunCancelled+"@"+c.phase)
				if got := rules(rec.Findings); !slices.Equal(got, want) {
					t.Errorf("record input findings %v, want %v", got, want)
				}
				want = append(want, findings.RuleStepDiverged+"@"+c.phase)
				if got := rules(res.Findings); !slices.Equal(got, want) {
					t.Errorf("findings %v, want %v", got, want)
				}
			}
			if c.at == findings.StepStage {
				// Cancelled at the stage, nothing was reconciled, awaited or pushed, so the record
				// keeps every node on the bundle it held: the from bundle.
				if h.ran(wire.ActReconcileLab) || h.ran(wire.ActAwaitReadiness) || h.ran(wire.ActPushConfig) {
					t.Errorf("activities %v: a step ran after the stage was cancelled", calls)
				}
				if rec.ReconcileStarted || rec.Reconcile != nil || len(rec.Ready) != 0 || len(rec.Pushed) != 0 {
					t.Errorf("record input %+v, want no reconcile, readiness or push", rec)
				}
				for _, p := range rec.PushPlan {
					if p.Outcome != wire.PushNotAttempted {
						t.Errorf("record input push %+v, want not attempted", p)
					}
				}
			}
			if c.at == findings.StepReconcile && c.unheard {
				// The reconcile returned its result, or failed: the record keeps the result, and
				// nothing was awaited or pushed after it.
				if h.ran(wire.ActAwaitReadiness) || h.ran(wire.ActPushConfig) {
					t.Errorf("activities %v: a step ran after the reconcile saw the cancellation", calls)
				}
				if r := rec.Reconcile; c.failed == "" && (r == nil || r.TookS != 3.9 || !reflect.DeepEqual(r.Nodes, stepLab())) {
					t.Errorf("record input reconcile %+v, want the reconcile's own result", r)
				}
				if c.failed != "" && (!rec.ReconcileStarted || rec.Reconcile != nil) {
					t.Errorf("record input reconcile started %v with %+v, want started with no result", rec.ReconcileStarted, rec.Reconcile)
				}
				wantNotAttempted(t, rec.PushPlan)
			}
			if c.at == findings.StepReadiness {
				// e1 answered: the record keeps its readiness, and nothing was pushed.
				if h.ran(wire.ActPushConfig) {
					t.Errorf("activities %v: a push ran after the readiness saw the cancellation", calls)
				}
				if want := []wire.ReadinessResult{{Node: "e1", ReadyAfterS: 54.8}}; !slices.Equal(rec.Ready, want) {
					t.Errorf("record input ready %+v, want %+v", rec.Ready, want)
				}
				wantNotAttempted(t, rec.PushPlan)
			}
			if c.at == findings.StepPush && c.unheard {
				// Both pushes landed, and the record says so: the cancellation after them still
				// makes the step a failed one.
				for _, p := range rec.PushPlan {
					if p.Outcome != wire.PushLanded || p.Rule != "" || p.TookS == nil {
						t.Errorf("record input push %+v, want landed with its time", p)
					}
				}
				want := "step run default-test-run-id towards waypoint demo/2 (bundle eeeeeeee…) stopped at phase push: landed e1, s1; " +
					"not landed none; the twin is up and diverged at waypoint demo/1 (bundle 34343434…), its record says so, and it " +
					"accepts only fylgja twin destroy"
				if d := onlyFinding(t, res.Findings, findings.RuleStepDiverged); d.Message != want {
					t.Errorf("step.diverged %q\nwant %q", d.Message, want)
				}
			}
			if c.at == findings.StepPush && !c.unheard {
				// The push the cancellation reached did not land, and says why. The test suite
				// settles every activity in flight as cancelled at once, whatever
				// WaitForCancellation says, so s1's push, which
				// returned, may read cancelled here too; against the service it lands.
				if p := rec.PushPlan[0]; p.Node != "e1" || p.Outcome != wire.PushFailed || p.Rule != findings.RuleRunCancelled {
					t.Errorf("record input push %+v, want e1 failed under run.cancelled", p)
				}
			}
			if doc.Status != findings.StatusDiverged || doc.Status.ExitCode() != 4 {
				t.Errorf("document status %s exit %d, want diverged, exit 4", doc.Status, doc.Status.ExitCode())
			}
		})
	}
}

// mockInspectCancelled, mockCheckHostCancelled and mockStageCancelled answer their step as
// a clear one, cancelling the run first: the answer is lost when the cancellation reaches
// the activity, and is the run's when it does not.
func mockInspectCancelled(h *stepHarness, cancel func(context.Context) error) {
	h.env.OnActivity(wire.ActInspectTwin, mock.Anything).Return(func(ctx context.Context) (wire.HostReport, error) {
		return h.host, cancel(ctx)
	})
}

func mockCheckHostCancelled(h *stepHarness, cancel func(context.Context) error) {
	h.env.OnActivity(wire.ActCheckHost, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, _ wire.CheckHostInput) (wire.CheckHostResult, error) {
			return h.plan, cancel(ctx)
		})
}

func mockStageCancelled(h *stepHarness, cancel func(context.Context) error) {
	h.env.OnActivity(wire.ActStageStep, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, _ wire.StageStepInput) (wire.StageResult, error) {
			return wire.StageResult{TwinDir: "/state/twin"}, cancel(ctx)
		})
}

// mockCompareCancelled, mockReconcileCancelled, mockReadinessCancelled and mockPushCancelled
// answer their step as the happy path does, cancelling the run first. e1's push cancels; s1's
// lands.
func mockCompareCancelled(h *stepHarness, cancel func(context.Context) error) {
	h.env.OnActivity(wire.ActPlanReconcile, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, _ wire.PlanReconcileInput) (wire.ReconcilePlan, error) {
			return h.lab, cancel(ctx)
		})
}

func mockReconcileCancelled(h *stepHarness, cancel func(context.Context) error) {
	h.env.OnActivity(wire.ActReconcileLab, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, _ wire.ReconcileInput) (wire.ReconcileResult, error) {
			return wire.ReconcileResult{Nodes: stepLab(), TookS: 3.9}, cancel(ctx)
		})
}

func mockReadinessCancelled(h *stepHarness, cancel func(context.Context) error) {
	h.env.OnActivity(wire.ActAwaitReadiness, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, in wire.ReadinessInput) (wire.ReadinessResult, error) {
			return wire.ReadinessResult{Node: in.Node, ReadyAfterS: 54.8}, cancel(ctx)
		})
}

func mockPushCancelled(h *stepHarness, cancel func(context.Context) error) {
	h.env.OnActivity(wire.ActPushConfig, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, in wire.PushInput) (wire.PushResult, error) {
			if in.Node == "e1" {
				if err := cancel(ctx); err != nil {
					return wire.PushResult{}, err
				}
			}
			return h.landed(ctx, in)
		})
}

// mockStageFailedAfterTheCancellation and mockReconcileFailedAfterTheCancellation cancel the
// run, then fail their step with an error of their own that retrying cannot help.
func mockStageFailedAfterTheCancellation(h *stepHarness, cancel func(context.Context) error) {
	h.env.OnActivity(wire.ActStageStep, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, _ wire.StageStepInput) (wire.StageResult, error) {
			if err := cancel(ctx); err != nil {
				return wire.StageResult{}, err
			}
			return wire.StageResult{}, lab.StepFailure(findings.StepStage, findings.RuleStageFailed, "/state/twin/bundle",
				"twin/bundle holds bundle 5151…")
		})
}

func mockReconcileFailedAfterTheCancellation(h *stepHarness, cancel func(context.Context) error) {
	h.env.OnActivity(wire.ActReconcileLab, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, _ wire.ReconcileInput) (wire.ReconcileResult, error) {
			if err := cancel(ctx); err != nil {
				return wire.ReconcileResult{}, err
			}
			return wire.ReconcileResult{}, lab.StepFailure(findings.StepReconcile, findings.RuleDeployFailed, "lab fylgja",
				"clab deploy exited 1")
		})
}

// wantNotAttempted fails the test for a push of the plan that was attempted.
func wantNotAttempted(t *testing.T, plan []wire.StepPush) {
	t.Helper()
	if len(plan) == 0 {
		t.Error("record input push plan is empty, want every node of it not attempted")
	}
	for _, p := range plan {
		if p.Outcome != wire.PushNotAttempted || p.TookS != nil {
			t.Errorf("record input push %+v, want not attempted", p)
		}
	}
}

// cancelWatch lets a test cancel the run as the service does for an activity that never
// heartbeats: the cancellation never reaches it, WaitForCancellation holds its future until
// it returns, and the run gets its result with no error. The test suite
// settles every activity in flight as cancelled at once instead, so a run's
// look at its context after such an activity returns is never reached there. This worker
// interceptor schedules the activity named unheard on a context the cancellation does not
// reach, and closes seen once the run has seen the cancellation, as replayed histories show
// the provisioning run doing.
type cancelWatch struct {
	interceptor.WorkerInterceptorBase
	env     *testsuite.TestWorkflowEnvironment
	unheard string
	once    sync.Once
	seen    chan struct{}
}

// newCancelWatch installs a cancelWatch on the harness's worker. unheard may be empty, for a
// test that cancels from an activity the run already keeps from its cancellation.
func newCancelWatch(h *stepHarness, unheard string) *cancelWatch {
	w := &cancelWatch{env: h.env, unheard: unheard, seen: make(chan struct{})}
	h.env.SetWorkerOptions(worker.Options{Interceptors: []interceptor.WorkerInterceptor{w}})
	return w
}

// cancel asks for the run's cancellation from inside an activity and returns once the run has
// seen it, so that the activity's answer arrives after the cancellation.
func (w *cancelWatch) cancel() error {
	w.once.Do(w.env.CancelWorkflow)
	select {
	case <-w.seen:
		return nil
	case <-time.After(5 * time.Second):
		return errors.New("the run never saw its cancellation")
	}
}

func (w *cancelWatch) InterceptWorkflow(_ workflow.Context, next interceptor.WorkflowInboundInterceptor) interceptor.WorkflowInboundInterceptor {
	return &cancelWatchInbound{WorkflowInboundInterceptorBase: interceptor.WorkflowInboundInterceptorBase{Next: next}, w: w}
}

type cancelWatchInbound struct {
	interceptor.WorkflowInboundInterceptorBase
	w *cancelWatch
}

func (i *cancelWatchInbound) Init(outbound interceptor.WorkflowOutboundInterceptor) error {
	return i.Next.Init(&cancelWatchOutbound{WorkflowOutboundInterceptorBase: interceptor.WorkflowOutboundInterceptorBase{Next: outbound}, w: i.w})
}

func (i *cancelWatchInbound) ExecuteWorkflow(ctx workflow.Context, in *interceptor.ExecuteWorkflowInput) (any, error) {
	workflow.Go(ctx, func(ctx workflow.Context) {
		ctx.Done().Receive(ctx, nil)
		close(i.w.seen)
	})
	return i.Next.ExecuteWorkflow(ctx, in)
}

type cancelWatchOutbound struct {
	interceptor.WorkflowOutboundInterceptorBase
	w *cancelWatch
}

func (o *cancelWatchOutbound) ExecuteActivity(ctx workflow.Context, name string, args ...any) workflow.Future {
	if name == o.w.unheard {
		ctx, _ = workflow.NewDisconnectedContext(ctx)
	}
	return o.Next.ExecuteActivity(ctx, name, args...)
}

// A cancellation during the record changes nothing: the record runs where the cancellation
// does not reach it and is written whole as what landed says, and the run reports what the
// record says, stepped with both pushes landed, with no run.cancelled and no step.diverged
// (contracts/cli.md's run.cancelled row).
func TestStepCancelledDuringTheRecord(t *testing.T) {
	h := newStepHarness(t)
	w := newCancelWatch(h, "")
	h.env.OnActivity(wire.ActRecordStep, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, in wire.RecordStepInput) (wire.RecordResult, error) {
			if err := w.cancel(); err != nil {
				return wire.RecordResult{}, err
			}
			return h.recordAs(ctx, in)
		})
	h.mockHappyPath()
	in := stepInput()
	res := h.run(in)

	if res.Outcome != StepStepped || res.Phase != "" || res.Step != "" || res.Record == nil {
		t.Errorf("outcome %q phase %q step %q record %v, want stepped with its record", res.Outcome, res.Phase, res.Step, res.Record)
	}
	if carries(res.Findings, findings.RuleRunCancelled, "") || len(res.Findings) != 0 {
		t.Errorf("findings %v, want none: the cancellation came after everything the record says", rules(res.Findings))
	}
	if h.ran("cancelled " + wire.ActRecordStep) {
		t.Errorf("activities %v: the cancellation reached the record", h.calls())
	}
	rec := h.record()
	if rec.Outcome != wire.StepStepped || rec.Phase != "" || len(rec.Findings) != 0 {
		t.Errorf("record input %q at %q with %v, want stepped with no failure", rec.Outcome, rec.Phase, rules(rec.Findings))
	}
	for _, p := range rec.PushPlan {
		if p.Outcome != wire.PushLanded {
			t.Errorf("record input push %+v, want landed", p)
		}
	}
	doc := stepDocument(t, in, res)
	if doc.Status != findings.StatusOK || doc.Status.ExitCode() != 0 || doc.Step.Outcome != StepStepped {
		t.Errorf("document status %s exit %d outcome %q, want ok, 0, stepped", doc.Status, doc.Status.ExitCode(), doc.Step.Outcome)
	}
}

// A step cancelled from its stage on whose record then cannot be written is cancelled and
// diverged, exit 4, and says so: run.cancelled ends "the record could not be written and
// nothing was torn down", beside record.failed and a step.diverged saying the record still
// claims the twin is ready where it was (contracts/cli.md's run.cancelled and step.diverged
// rows).
func TestStepCancelledWhenTheRecordCannotBeWritten(t *testing.T) {
	h := newStepHarness(t)
	cancel := newStepCanceller(h).block
	h.env.OnActivity(wire.ActPushConfig, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, in wire.PushInput) (wire.PushResult, error) {
			if in.Node == "s1" {
				return h.landed(ctx, in)
			}
			return wire.PushResult{}, cancel(ctx)
		})
	h.env.OnActivity(wire.ActRecordStep, mock.Anything, mock.Anything).Return(wire.RecordResult{},
		lab.StepFailure(findings.StepRecord, findings.RuleRecordFailed, "/state/twin/twin.json", "writing /state/twin/twin.json: disk full"))
	h.mockHappyPath()
	in := stepInput()
	res := h.run(in)

	if res.Outcome != OutcomeCancelled || res.Phase != findings.StepPush || res.Step != findings.StepPush || res.Record != nil {
		t.Errorf("outcome %q phase %q step %q record %v, want cancelled at push with no record written", res.Outcome, res.Phase,
			res.Step, res.Record)
	}
	if h.ran("cancelled " + wire.ActRecordStep) {
		t.Errorf("activities %v: the cancellation reached the record", h.calls())
	}
	want := "run default-test-run-id was cancelled at step push; the record could not be written and nothing was torn down"
	if f := onlyFinding(t, res.Findings, findings.RuleRunCancelled); f.Message != want || f.Step != findings.StepPush {
		t.Errorf("run.cancelled %+v\nwant %q at push", f, want)
	}
	if f := onlyFinding(t, res.Findings, findings.RuleRecordFailed); f.Step != findings.StepRecord {
		t.Errorf("record.failed %+v, want at record", f)
	}
	d := onlyFinding(t, res.Findings, findings.RuleStepDiverged)
	prefix := "step run default-test-run-id towards waypoint demo/2 (bundle eeeeeeee…) stopped at phase push: "
	suffix := "; the twin is up and diverged at waypoint demo/1 (bundle 34343434…), but its record could not be written and " +
		"still says it is ready there; fylgja twin destroy clears it"
	if d.Step != findings.StepPush || !strings.HasPrefix(d.Message, prefix) || !strings.HasSuffix(d.Message, suffix) {
		t.Errorf("step.diverged %+v\nwant at push, beginning %q and ending %q", d, prefix, suffix)
	}
	doc := stepDocument(t, in, res)
	if doc.Status != findings.StatusDiverged || doc.Status.ExitCode() != 4 || doc.Step.Outcome != StepDiverged || doc.Step.State != "" {
		t.Errorf("document status %s exit %d outcome %q state %q, want diverged, exit 4, diverged, and no state, since no record "+
			"was written", doc.Status, doc.Status.ExitCode(), doc.Step.Outcome, doc.Step.State)
	}
}

// Every rule on containerlab's plan, worded as contracts/cli.md words it, from PlanRules
// itself, which the CLI asks too.
func TestPlanRulesWording(t *testing.T) {
	target := []NodePackage{{Node: "e1", ID: "arista_eos", Mode: "replace", LinkChange: "restart"},
		{Node: "s1", ID: "nokia_srlinux", Mode: "replace", LinkChange: "live"},
		{Node: "s2", ID: "nokia_srlinux", Mode: "replace", LinkChange: "live"}}
	for _, c := range []struct {
		name  string
		rules PlanRules
		want  []string // rule: message
	}{
		{"a restart and a recreate", PlanRules{Target: target, Plan: wire.ReconcilePlan{Restarted: []string{"e1"}, Recreated: []string{"s2"},
			Reasons: map[string]string{"e1": "added link", "s2": "config drift: Image"}}},
			[]string{findings.RuleStepRestartRequired + ": containerlab would restart e1 (added link; package arista_eos declares restart) " +
				"and recreate s2 (config drift: Image; package nokia_srlinux declares live): each loses its running state and its push " +
				"until the step pushes it again; give --allow-restart to proceed, or --dry-run to see the step"}},
		{"the flag given", PlanRules{Target: target, AllowRestart: true, Plan: wire.ReconcilePlan{Restarted: []string{"e1"}}}, nil},
		{"a created node needs no flag", PlanRules{Target: target, Plan: wire.ReconcilePlan{Added: []string{"s3"}}}, nil},
		{"merge in either bundle", PlanRules{Target: []NodePackage{{Node: "c1", ID: "chassisos", Mode: "merge"}},
			From: []NodePackage{{Node: "c2", ID: "chassisos", Mode: "merge"}, {Node: "c1", ID: "chassisos", Mode: "merge"}}},
			[]string{findings.RuleStepPackageMerge + ": support package chassisos pushes by merge, which a step cannot use: a step " +
				"removes what the previous artifact added, and only a replace does that; nodes c1, c2; a create from it is unaffected"}},
		{"an image and a package the plan leaves", PlanRules{Target: target, Changed: []StepChange{{Node: "s2", Changes: []string{"image", "psp"}}}},
			[]string{findings.RuleStepNodeUnapplied + ": node s2 changes in image, psp between the two bundles, but containerlab's " +
				"reconcile would not recreate it (its plan: no change); the running node would keep its image and package; a step cannot apply it"}},
		{"a recreated image", PlanRules{Target: target, AllowRestart: true, Changed: []StepChange{{Node: "s2", Changes: []string{"image"}}},
			Plan: wire.ReconcilePlan{Recreated: []string{"s2"}}}, nil},
		{"an added node the plan does not create", PlanRules{Target: target, Changed: []StepChange{{Node: "s3", Changes: []string{ChangeAdded}}}},
			[]string{findings.RuleStepNodeUnapplied + ": node s3 is added by the step, but containerlab's reconcile would not create it " +
				"(its plan: no change); the lab would not run it; a step cannot apply it"}},
		{"a live re-cable of a node declaring restart", PlanRules{Target: target, Plan: wire.ReconcilePlan{
			LinksAdded: []string{"e1:eth3 -- s1:e1-3"}, Reasons: map[string]string{"e1": "added link", "s1": "added link"}}},
			[]string{findings.RuleStepRestartUndeclared + ": package arista_eos declares that a link change restarts the node, but " +
				"containerlab's plan re-cables e1 live (added link); the step acts on containerlab's plan and records both"}},
	} {
		t.Run(c.name, func(t *testing.T) {
			var got []string
			for _, f := range c.rules.Findings() {
				if f.Step != findings.StepCompare {
					t.Errorf("%s at %q, want compare", f.Rule, f.Step)
				}
				got = append(got, f.Rule+": "+f.Message)
			}
			if !slices.Equal(got, c.want) {
				t.Errorf("findings\n  %q\nwant\n  %q", got, c.want)
			}
		})
	}
}

// step.node.unapplied as the CLI and the run's second lock apply it, PlanRules over
// ChangesOf, names exactly the nodes step.Unapplied names for the same step and plan:
// a node changed in image, platform or psp that the plan
// does not recreate, and a node added that it does not create. Nothing else.
func TestPlanRulesUnappliedIsStepUnapplied(t *testing.T) {
	changed := func(node string, reasons ...string) step.Step {
		return step.Step{NodesChanged: []step.NodeChange{{Node: node, Reasons: reasons}}}
	}
	steps := []struct {
		name string
		s    step.Step
	}{
		{"an image change", changed("e1", step.ReasonImage)},
		{"a platform change", changed("e1", step.ReasonPlatform)},
		{"a psp change", changed("e1", step.ReasonPSP)},
		{"a mapping change", changed("e1", step.ReasonMapping)},
		{"a bootstrap change", changed("e1", step.ReasonBootstrap)},
		{"a platform change with its bootstrap and mapping",
			changed("e1", step.ReasonBootstrap, step.ReasonMapping, step.ReasonPlatform)},
		{"an image and a psp change", changed("e1", step.ReasonImage, step.ReasonPSP)},
		{"two nodes changed", step.Step{NodesChanged: []step.NodeChange{
			{Node: "e1", Reasons: []string{step.ReasonImage}}, {Node: "s1", Reasons: []string{step.ReasonMapping, step.ReasonPlatform}}}}},
		{"a node added", step.Step{NodesAdded: []string{"e1"}}},
		{"a node added, one changed and one removed", step.Step{NodesAdded: []string{"s3"}, NodesRemoved: []string{"s2"},
			NodesChanged: []step.NodeChange{{Node: "e1", Reasons: []string{step.ReasonPlatform}}}}},
	}
	plans := []struct {
		name string
		plan wire.ReconcilePlan
	}{
		{"no plan", wire.ReconcilePlan{}},
		{"e1 recreated", wire.ReconcilePlan{Recreated: []string{"e1"}}},
		{"e1 restarted", wire.ReconcilePlan{Restarted: []string{"e1"}}},
		{"e1 created", wire.ReconcilePlan{Added: []string{"e1"}}},
		{"s1 recreated", wire.ReconcilePlan{Recreated: []string{"s1"}}},
		{"e1 and s1 recreated", wire.ReconcilePlan{Recreated: []string{"e1", "s1"}}},
		{"s3 created and s2 deleted", wire.ReconcilePlan{Added: []string{"s3"}, Deleted: []string{"s2"}}},
	}
	for _, sc := range steps {
		for _, pc := range plans {
			t.Run(sc.name+"/"+pc.name, func(t *testing.T) {
				rules := PlanRules{Plan: pc.plan, Changed: ChangesOf(sc.s), AllowRestart: true}
				got := []string{}
				for _, f := range rules.Findings() {
					if f.Rule == findings.RuleStepNodeUnapplied {
						got = append(got, f.Object)
					}
				}
				want := step.Unapplied(sc.s, step.Lifecycle{Restarted: pc.plan.Restarted, Recreated: pc.plan.Recreated,
					Created: pc.plan.Added, Removed: pc.plan.Deleted})
				if !slices.Equal(got, want) {
					t.Errorf("step.node.unapplied names %v, step.Unapplied %v", got, want)
				}
			})
		}
	}
}

// Every shape of an ineligible host, worded once for the CLI and the run.
func TestIneligibleWording(t *testing.T) {
	branch := func(at, source string) wire.HostReport {
		h := stepTwinHost()
		h.Twin.Waypoint, h.Twin.Provenance.At, h.Twin.Source = nil, at, source
		return h
	}
	orphan := wire.HostReport{LabPresent: true, Phrase: "an orphan: lab fylgja with no twin directory"}
	gone := stepTwinHost()
	gone.LabPresent = false
	gone.Phrase = "a twin record whose lab is gone"
	leftover := wire.HostReport{TwinDirPresent: true, Phrase: "a leftover twin directory: no twin.json and no lab fylgja"}
	for _, c := range []struct {
		name         string
		host         wire.HostReport
		object, want string
	}{
		{"an orphan", orphan, "lab fylgja", orphan.Phrase + "; only a twin built from a waypoint steps; fylgja twin destroy clears it"},
		{"a record whose lab is gone", gone, "/state/twin", gone.Phrase + "; only a twin built from a waypoint steps; fylgja twin destroy clears it"},
		{"a leftover twin directory", leftover, "/state/twin", leftover.Phrase + "; only a twin built from a waypoint steps; fylgja twin destroy clears it"},
		{"a branch twin", branch("", wire.SourceIntent), stepFrom, "the twin was created from branch change-1, not from a waypoint, " +
			"so it names no series to step along; only a twin built from a waypoint steps"},
		{"a pinned twin", branch(stepFromAt, wire.SourceIntent), stepFrom, "the twin was created from branch change-1 at " + stepFromAt +
			", not from a waypoint, so it names no series to step along; only a twin built from a waypoint steps"},
		{"a bundle twin", branch("", wire.SourceBundle), stepFrom, "the twin was created from a bundle, not from a waypoint, " +
			"so it names no series to step along; only a twin built from a waypoint steps"},
	} {
		t.Run(c.name, func(t *testing.T) {
			f := Ineligible(c.host, findings.StepResolve, "/state/twin")
			if f == nil {
				t.Fatal("eligible, want refused")
			}
			if f.Rule != findings.RuleStepTwinUnsteppable || f.Step != findings.StepResolve || f.Object != c.object || f.Message != c.want {
				t.Errorf("%+v\nwant %s at resolve on %q: %q", *f, findings.RuleStepTwinUnsteppable, c.object, c.want)
			}
		})
	}
	if f := Ineligible(stepTwinHost(), findings.StepResolve, ""); f != nil {
		t.Errorf("a ready waypoint twin refused: %+v", *f)
	}
	// The run's second lock at inspect knows no state root, so a host with no lab names the
	// twin directory by what it is rather than by its path (contracts/cli.md, the run's
	// second locks).
	for _, host := range []wire.HostReport{gone, leftover} {
		f := Ineligible(host, findings.StepInspect, "")
		if f == nil || f.Rule != findings.RuleStepTwinUnsteppable || f.Step != findings.StepInspect || f.Object != "twin directory" ||
			f.Message != host.Phrase+"; only a twin built from a waypoint steps; fylgja twin destroy clears it" {
			t.Errorf("the run's refusal of %q: %+v; want %s at inspect on the twin directory", host.Phrase, f, findings.RuleStepTwinUnsteppable)
		}
	}
}

// ChangesOf names what only a lifecycle applies: an image, platform or psp change, and a
// node added; a bootstrap or mapping change is the push's.
func TestChangesOf(t *testing.T) {
	got := ChangesOf(step.Step{NodesAdded: []string{"s3"}, NodesChanged: []step.NodeChange{
		{Node: "e1", Reasons: []string{step.ReasonBootstrap, step.ReasonMapping}},
		{Node: "s2", Reasons: []string{step.ReasonImage, step.ReasonPSP}}}})
	want := []StepChange{{Node: "s2", Changes: []string{"image", "psp"}}, {Node: "s3", Changes: []string{ChangeAdded}}}
	if len(got) != len(want) || !slices.Equal(got[0].Changes, want[0].Changes) || got[0].Node != "s2" ||
		got[1].Node != "s3" || !slices.Equal(got[1].Changes, want[1].Changes) {
		t.Errorf("ChangesOf = %+v, want %+v", got, want)
	}
}

// Workflow code imports no package loader, so the values it compares packages by are its
// own; they must be internal/psp's.
func TestStepDeclarationValuesAreThePackagesOwn(t *testing.T) {
	if declaredRestart != psp.LinkChangeRestart || declaredLive != psp.LinkChangeLive || pushModeMerge != psp.ModeMerge {
		t.Errorf("restart %q, live %q, merge %q; want internal/psp's %q, %q, %q", declaredRestart, declaredLive, pushModeMerge,
			psp.LinkChangeRestart, psp.LinkChangeLive, psp.ModeMerge)
	}
	// The record activity the workflow schedules is the lab's.
	if _, ok := (&lab.Activities{}).Names()[wire.ActRecordStep]; !ok {
		t.Error("RecordStep is not registered by the lab's activities")
	}
}

// The step's wait after its record. Each run below is held to the same run with the version
// marker at DefaultVersion,
// which never schedules VerifyTwin: what the record step decided — the outcome, phase, step,
// findings, timings, clocks, push plan and record, and the record step's input — is the
// no-wait run's, and the wait adds its result and, when it did not settle, one warning.

// stepWaitCase is a run the wait follows: how it is arranged, and how it ends.
type stepWaitCase struct {
	name    string
	arrange func(h *stepHarness, in *StepInput)
	outcome string
	exit    int
}

// stepWaitCases are the records the wait follows: stepped, unchanged, diverged at push and
// at readiness, and a record that could not be written: the wait follows every record.
func stepWaitCases() []stepWaitCase {
	nonRetryable := func(rule, at, object, message string) error {
		return temporal.NewNonRetryableApplicationError(message, rule, nil,
			findings.Finding{Severity: findings.Rejection, Rule: rule, Object: object, Step: at, Message: message})
	}
	return []stepWaitCase{
		{"stepped", func(*stepHarness, *StepInput) {}, StepStepped, 0},
		{"unchanged", func(h *stepHarness, in *StepInput) {
			h.lab = wire.ReconcilePlan{}
			in.Unchanged, in.Plan, in.PushPlan = true, wire.ReconcilePlan{}, nil
		}, StepUnchanged, 0},
		{"diverged at push", func(h *stepHarness, _ *StepInput) {
			h.env.OnActivity(wire.ActPushConfig, mock.Anything, mock.MatchedBy(func(in wire.PushInput) bool { return in.Node == "e1" })).
				Return(wire.PushResult{}, nonRetryable(findings.RulePushRefused, findings.StepPush, "e1",
					"node e1 refused artifact device-config (checksum aaaa…) at line 7: Invalid input (at token 0: 'bogus')"))
		}, StepDiverged, 4},
		{"diverged at readiness", func(h *stepHarness, _ *StepInput) {
			h.env.OnActivity(wire.ActAwaitReadiness, mock.Anything, mock.Anything).Return(wire.ReadinessResult{},
				nonRetryable(findings.RuleReadinessTimeout, findings.StepReadiness, "e1", "node e1 did not answer within 180s"))
		}, StepDiverged, 4},
		{"a record that could not be written", func(h *stepHarness, _ *StepInput) {
			h.env.OnActivity(wire.ActRecordStep, mock.Anything, mock.Anything).Return(wire.RecordResult{},
				nonRetryable(findings.RuleRecordFailed, findings.StepRecord, "/state/twin/twin.json",
					"writing /state/twin/twin.json: disk full"))
		}, StepDiverged, 4},
	}
}

// stepWaitRun is one run of a case: its result, what the record step and the wait were
// given, and the activities in the order they started.
type stepWaitRun struct {
	res    StepResult
	record []wire.RecordStepInput
	verify []wire.VerifyInput
	calls  []string
}

// runStepWait runs c with VerifyTwin answered by wait, or with the version marker at
// DefaultVersion when wait is nil. The reconcile holds the run's clock for 4s, so the
// record's time is not the start's.
func runStepWait(t *testing.T, c stepWaitCase, waitS int, wait any) stepWaitRun {
	t.Helper()
	h := newStepHarness(t)
	h.env.SetStartTime(stepStart)
	in := stepInput()
	in.WaitS = waitS
	c.arrange(h, &in)
	if wait == nil {
		h.env.OnGetVersion(VerifyVersionID, workflow.DefaultVersion, 1).Return(workflow.DefaultVersion)
	} else {
		h.env.OnActivity(wire.ActVerifyTwin, mock.Anything, mock.Anything).Return(wait)
	}
	h.env.OnActivity(wire.ActReconcileLab, mock.Anything, mock.Anything).Return(
		wire.ReconcileResult{Nodes: stepLab(), TookS: 3.9}, nil).After(4 * time.Second)
	h.mockHappyPath()
	res := h.run(in)
	h.mu.Lock()
	recorded := append([]wire.RecordStepInput(nil), h.recorded...)
	h.mu.Unlock()
	return stepWaitRun{res: res, record: recorded, verify: stepInputs[wire.VerifyInput](h, wire.ActVerifyTwin), calls: h.calls()}
}

// withoutTheWait is a result as the no-wait run reaches it: no wait, and none of the
// warnings the wait adds.
func withoutTheWait(res StepResult) StepResult {
	res.Wait = nil
	res.Findings = slices.DeleteFunc(slices.Clone(res.Findings), func(f findings.Finding) bool {
		return f.Rule == findings.RuleVerifyWaitUnsettled
	})
	return res
}

// sameAsTheNoWaitRun fails the test where got differs from base in anything the record step
// decided, or where the wait was not the last activity, given the run, the record's time and
// the budget.
func sameAsTheNoWaitRun(t *testing.T, base, got stepWaitRun, waitS int) {
	t.Helper()
	if slices.Contains(base.calls, wire.ActVerifyTwin) || base.res.Wait != nil {
		t.Errorf("the run at DefaultVersion scheduled the wait: %v, wait %+v", base.calls, base.res.Wait)
	}
	if want := append(slices.Clone(base.calls), wire.ActVerifyTwin); !slices.Equal(got.calls, want) {
		t.Errorf("activities %v\nwant the no-wait run's, then the wait: %v", got.calls, want)
	}
	if !reflect.DeepEqual(withoutTheWait(got.res), base.res) {
		t.Errorf("result without the wait\n%+v\nwant the no-wait run's\n%+v", withoutTheWait(got.res), base.res)
	}
	if !reflect.DeepEqual(got.record, base.record) {
		t.Errorf("record step input %+v\nwant the no-wait run's %+v", got.record, base.record)
	}
	want := wire.VerifyInput{RunID: "default-test-run-id", From: base.res.EndedAt, BudgetS: waitS}
	if !slices.Equal(got.verify, []wire.VerifyInput{want}) {
		t.Errorf("VerifyTwin was given %+v, want %+v once: the run, the record's time, the budget", got.verify, want)
	}
}

// A wait that settles changes nothing the record step decided, after every record the run
// writes or tries to, and the result carries the wait as the activity gave it; the status and
// exit are the no-wait run's.
func TestStepWaitsAfterEveryRecord(t *testing.T) {
	for _, c := range stepWaitCases() {
		t.Run(c.name, func(t *testing.T) {
			base := runStepWait(t, c, 120, nil)
			got := runStepWait(t, c, 120, settledWait)
			sameAsTheNoWaitRun(t, base, got, 120)
			if got.res.Outcome != c.outcome {
				t.Errorf("outcome %q, want %q", got.res.Outcome, c.outcome)
			}
			want := wire.StepWait{Outcome: wire.WaitSettled, BudgetS: 120, Reads: 2, AfterS: 2.4, From: base.res.EndedAt,
				EndedAt: "2026-10-02T09:16:13.400000Z", Failing: []wire.StepFinding{}}
			if got.res.Wait == nil || !reflect.DeepEqual(*got.res.Wait, want) {
				t.Errorf("wait %+v, want the activity's %+v", got.res.Wait, want)
			}
			if carries(got.res.Findings, findings.RuleVerifyWaitUnsettled, findings.StepObserve) {
				t.Errorf("findings %v: a settled wait adds no warning", rules(got.res.Findings))
			}
			doc := stepDocument(t, stepInput(), got.res)
			if code := doc.Status.ExitCode(); code != c.exit {
				t.Errorf("status %s exit %d, want exit %d", doc.Status, code, c.exit)
			}
		})
	}
}

// A wait that does not settle adds the warning verify.wait.unsettled at observe, on the run,
// and nothing else: the outcome, status and exit are the no-wait run's, stepped 0 and diverged
// 4 (contracts/cli.md's warning row). The activity may answer expired or incomplete,
// or fail outright, which is the wait incomplete with the activity's finding and the record's
// wait left null.
func TestStepWaitUnsettledAddsAWarningAlone(t *testing.T) {
	failing := func(list ...wire.StepFinding) []wire.StepFinding { return list }
	neighbor := func(object string) wire.StepFinding {
		return wire.StepFinding{Rule: findings.RuleVerifyNeighbor, Object: object, Message: "node " + object + " sees no neighbour"}
	}
	unread := wire.StepFinding{Rule: findings.RuleOperationFailed, Object: "e1",
		Message: "node e1 (172.20.20.2:6030) could not be read: rpc error: code = Unavailable (at /system/state/hostname)"}
	answer := func(w wire.StepWait) func(context.Context, wire.VerifyInput) (wire.VerifyResult, error) {
		return func(_ context.Context, in wire.VerifyInput) (wire.VerifyResult, error) {
			w.BudgetS, w.From, w.EndedAt = in.BudgetS, in.From, "2026-10-02T09:17:04Z"
			return wire.VerifyResult{Wait: w, Recorded: true}, nil
		}
	}
	notRead := lab.StepFailure(findings.StepObserve, findings.RuleOperationFailed, "/state/twin/twin.json",
		"reading the twin's record for the step's wait: open /state/twin/twin.json: no such file or directory")
	for _, w := range []struct {
		name    string
		wait    any
		outcome string
		reads   int
		failing []wire.StepFinding
		message string
	}{
		{"expired", answer(wire.StepWait{Outcome: wire.WaitExpired, Reads: 58, AfterS: 120,
			Failing: failing(neighbor("s1:ethernet-1/3"), neighbor("e1:Ethernet3"))}), wire.WaitExpired, 58,
			failing(neighbor("s1:ethernet-1/3"), neighbor("e1:Ethernet3")),
			"expired after 120.0s (58 reads, budget 2m0s): the twin does not conform to bundle eeeeeeee…; " +
				"still failing: verify.neighbor s1:ethernet-1/3, verify.neighbor e1:Ethernet3"},
		{"incomplete, a node unread at expiry", answer(wire.StepWait{Outcome: wire.WaitIncomplete, Reads: 58, AfterS: 120.3,
			Failing: failing(unread, neighbor("s1:ethernet-1/3"))}), wire.WaitIncomplete, 58,
			failing(unread, neighbor("s1:ethernet-1/3")),
			"could not complete: node e1 (172.20.20.2:6030) could not be read: rpc error: code = Unavailable " +
				"(at /system/state/hostname); still failing: verify.neighbor s1:ethernet-1/3"},
		{"incomplete, only the node unread", answer(wire.StepWait{Outcome: wire.WaitIncomplete, Reads: 1, AfterS: 0,
			Failing: failing(unread)}), wire.WaitIncomplete, 1, failing(unread),
			"could not complete: node e1 (172.20.20.2:6030) could not be read: rpc error: code = Unavailable " +
				"(at /system/state/hostname); nothing else was failing at the last read"},
		{"the activity failed outright", func(context.Context, wire.VerifyInput) (wire.VerifyResult, error) {
			return wire.VerifyResult{}, notRead
		}, wire.WaitIncomplete, 0, failing(wire.StepFinding{Rule: findings.RuleOperationFailed, Object: "/state/twin/twin.json",
			Message: "reading the twin's record for the step's wait: open /state/twin/twin.json: no such file or directory"}),
			"could not complete: reading the twin's record for the step's wait: open /state/twin/twin.json: no such file or " +
				"directory; the record's wait is null"},
	} {
		for _, c := range stepWaitCases() {
			if c.name != "stepped" && c.name != "diverged at push" {
				continue
			}
			t.Run(w.name+", "+c.name, func(t *testing.T) {
				base := runStepWait(t, c, 120, nil)
				got := runStepWait(t, c, 120, w.wait)
				sameAsTheNoWaitRun(t, base, got, 120)
				if got.res.Wait == nil || got.res.Wait.Outcome != w.outcome || got.res.Wait.Reads != w.reads ||
					got.res.Wait.BudgetS != 120 || got.res.Wait.From != base.res.EndedAt || !reflect.DeepEqual(got.res.Wait.Failing, w.failing) {
					t.Errorf("wait %+v, want %s after %d reads, budget 120, from the record's time, failing %+v", got.res.Wait,
						w.outcome, w.reads, w.failing)
				}
				warning := findings.Finding{Severity: findings.Warning, Rule: findings.RuleVerifyWaitUnsettled,
					Object: "default-test-run-id", Step: findings.StepObserve, Message: w.message}
				if want := append(slices.Clone(base.res.Findings), warning); !reflect.DeepEqual(got.res.Findings, want) {
					t.Errorf("findings %+v\nwant the no-wait run's, then %+v", got.res.Findings, warning)
				}
				if strings.Contains(w.message, "FYLGJA") || strings.Contains(w.message, "insert /") {
					t.Errorf("the warning carries a credential or a configuration line: %q", w.message)
				}
				doc := stepDocument(t, stepInput(), got.res)
				if code := doc.Status.ExitCode(); code != c.exit || doc.Step.Outcome != c.outcome {
					t.Errorf("status %s exit %d outcome %q, want exit %d, %q: the wait changes neither", doc.Status, code,
						doc.Step.Outcome, c.exit, c.outcome)
				}
			})
		}
	}
}

// The budget the CLI gives reaches the activity as given, 0 included (reads once), and the
// wait runs from the record's time, which is the result's ended_at.
func TestStepWaitTakesItsBudgetAndTheRecordsTime(t *testing.T) {
	for _, waitS := range []int{0, 30, 120} {
		got := runStepWait(t, stepWaitCases()[0], waitS, settledWait)
		want := wire.VerifyInput{RunID: "default-test-run-id", From: "2026-10-02T09:15:04Z", BudgetS: waitS}
		if !slices.Equal(got.verify, []wire.VerifyInput{want}) || got.res.EndedAt != want.From {
			t.Errorf("budget %d: VerifyTwin was given %+v, the run ended %q; want %+v", waitS, got.verify, got.res.EndedAt, want)
		}
	}
}

// A cancellation during the wait (twin destroy during the pause) ends it cancelled, and the
// run ends as its record says, stepped, exit 0, with the warning and no run.cancelled
// (contracts/cli.md: M11's rule for a cancellation during the record phase, extended). The
// cancellation never reaches VerifyTwin's future in the run, as against the service with
// WaitForCancellation (cancelWatch); the activity answers it with its wait.
func TestStepCancelledDuringTheWait(t *testing.T) {
	for _, c := range []struct {
		name    string
		failing []wire.StepFinding
		message string
	}{
		{"nothing failing", []wire.StepFinding{},
			"cancelled after 12.4s (7 reads, budget 2m0s); nothing was failing at the last read"},
		{"a link end failing", []wire.StepFinding{{Rule: findings.RuleVerifyNeighbor, Object: "e1:Ethernet3", Message: "sees no neighbour"}},
			"cancelled after 12.4s (7 reads, budget 2m0s); still failing: verify.neighbor e1:Ethernet3"},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := newStepHarness(t)
			w := newCancelWatch(h, wire.ActVerifyTwin)
			h.env.OnActivity(wire.ActVerifyTwin, mock.Anything, mock.Anything).Return(
				func(_ context.Context, in wire.VerifyInput) (wire.VerifyResult, error) {
					if err := w.cancel(); err != nil {
						return wire.VerifyResult{}, err
					}
					return wire.VerifyResult{Wait: wire.StepWait{Outcome: wire.WaitCancelled, BudgetS: in.BudgetS, Reads: 7, AfterS: 12.4,
						From: in.From, EndedAt: "2026-10-02T09:15:16.400000Z", Failing: c.failing}, Recorded: true}, nil
				})
			h.mockHappyPath()
			in := stepInput()
			in.WaitS = 120
			res := h.run(in)

			if res.Outcome != StepStepped || res.Phase != "" || res.Step != "" || res.Record == nil {
				t.Errorf("outcome %q phase %q step %q record %v, want stepped as its record says", res.Outcome, res.Phase, res.Step,
					res.Record)
			}
			if res.Wait == nil || res.Wait.Outcome != wire.WaitCancelled || res.Wait.Reads != 7 || res.Wait.AfterS != 12.4 {
				t.Errorf("wait %+v, want cancelled after 12.4s and 7 reads, as the activity recorded it", res.Wait)
			}
			want := findings.List{{Severity: findings.Warning, Rule: findings.RuleVerifyWaitUnsettled, Object: "default-test-run-id",
				Step: findings.StepObserve, Message: c.message}}
			if !reflect.DeepEqual(res.Findings, want) {
				t.Errorf("findings %+v\nwant the warning alone, no run.cancelled: %+v", res.Findings, want)
			}
			doc := stepDocument(t, in, res)
			if doc.Status != findings.StatusOK || doc.Status.ExitCode() != 0 || doc.Step.Outcome != StepStepped {
				t.Errorf("document status %s exit %d outcome %q, want ok, 0, stepped", doc.Status, doc.Status.ExitCode(), doc.Step.Outcome)
			}
		})
	}
}

// A cancellation that settles VerifyTwin before it answers — as the service settles an
// activity not yet started, and as the test suite settles every activity in flight — is a wait
// that never began: no wait in the result and no warning, and the run ends as its record says,
// with no run.cancelled.
func TestStepWaitCancelledBeforeTheActivityAnswered(t *testing.T) {
	h := newStepHarness(t)
	cancel := newStepCanceller(h).block
	h.env.OnActivity(wire.ActVerifyTwin, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, _ wire.VerifyInput) (wire.VerifyResult, error) {
			return wire.VerifyResult{}, cancel(ctx)
		})
	h.mockHappyPath()
	res := h.run(stepInput())

	if res.Outcome != StepStepped || res.Wait != nil || len(res.Findings) != 0 {
		t.Errorf("outcome %q wait %+v findings %v, want stepped with no wait and no finding", res.Outcome, res.Wait, rules(res.Findings))
	}
	if !h.ran("cancelled " + wire.ActVerifyTwin) {
		t.Errorf("activities %v: want the wait settled as cancelled", h.calls())
	}
}

// A run already cancelled when it reaches the wait skips it: no VerifyTwin is scheduled and
// the result carries no wait.
// Cancelled during a push, the run is cancelled and M11's run.cancelled says why.
// Cancelled during the record, the run ends as its record says with no finding at all, as M11
// ends it (TestStepCancelledDuringTheRecord): M11 adds no run.cancelled there, and M12 changes
// none of M11's findings.
func TestStepCancelledBeforeTheWait(t *testing.T) {
	t.Run("during the record", func(t *testing.T) {
		h := newStepHarness(t)
		w := newCancelWatch(h, "")
		h.env.OnActivity(wire.ActRecordStep, mock.Anything, mock.Anything).Return(
			func(ctx context.Context, in wire.RecordStepInput) (wire.RecordResult, error) {
				if err := w.cancel(); err != nil {
					return wire.RecordResult{}, err
				}
				return h.recordAs(ctx, in)
			})
		h.mockHappyPath()
		res := h.run(stepInput())
		if h.ran(wire.ActVerifyTwin) || res.Wait != nil {
			t.Errorf("activities %v, wait %+v: want no wait after a cancellation during the record", h.calls(), res.Wait)
		}
		if res.Outcome != StepStepped || len(res.Findings) != 0 {
			t.Errorf("outcome %q findings %v, want stepped with none, as M11", res.Outcome, rules(res.Findings))
		}
	})
	t.Run("during a push", func(t *testing.T) {
		h := newStepHarness(t)
		cancel := newStepCanceller(h).block
		h.env.OnActivity(wire.ActPushConfig, mock.Anything, mock.Anything).Return(
			func(ctx context.Context, in wire.PushInput) (wire.PushResult, error) {
				if in.Node == "s1" {
					return h.landed(ctx, in)
				}
				return wire.PushResult{}, cancel(ctx)
			})
		h.mockHappyPath()
		res := h.run(stepInput())
		if h.ran(wire.ActVerifyTwin) || res.Wait != nil {
			t.Errorf("activities %v, wait %+v: want no wait after a cancellation during the push", h.calls(), res.Wait)
		}
		if res.Outcome != OutcomeCancelled || !carries(res.Findings, findings.RuleRunCancelled, findings.StepPush) ||
			carries(res.Findings, findings.RuleVerifyWaitUnsettled, findings.StepObserve) {
			t.Errorf("outcome %q findings %v, want cancelled with run.cancelled at push and no wait warning", res.Outcome,
				rules(res.Findings))
		}
	})
}

// A step whose stage failed leaves the twin directory holding whichever bundle the stage
// reached, so the warning names none: the wait read the twin against what the directory holds.
func TestStepWaitAfterAFailedStageNamesNoBundle(t *testing.T) {
	c := stepWaitCase{"diverged at the stage", func(h *stepHarness, _ *StepInput) {
		h.env.OnActivity(wire.ActStageStep, mock.Anything, mock.Anything).Return(wire.StageResult{},
			lab.StepFailure(findings.StepStage, findings.RuleStageFailed, "/state/twin/bundle", "twin/bundle holds bundle 5151…"))
	}, StepDiverged, 4}
	expired := func(_ context.Context, in wire.VerifyInput) (wire.VerifyResult, error) {
		return wire.VerifyResult{Wait: wire.StepWait{Outcome: wire.WaitExpired, BudgetS: in.BudgetS, Reads: 3, AfterS: 2.1, From: in.From,
			Failing: []wire.StepFinding{{Rule: findings.RuleVerifyPortEnabled, Object: "s1:ethernet-1/3", Message: "reads disable"}}},
			Recorded: true}, nil
	}
	got := runStepWait(t, c, 2, expired)
	want := "expired after 2.1s (3 reads, budget 2s): the twin does not conform to the bundle the twin directory holds; " +
		"still failing: verify.port.enabled s1:ethernet-1/3"
	if f := onlyFinding(t, got.res.Findings, findings.RuleVerifyWaitUnsettled); f.Message != want {
		t.Errorf("warning %q\nwant %q", f.Message, want)
	}
	if got.res.Outcome != StepDiverged || got.res.Step != findings.StepStage {
		t.Errorf("outcome %q step %q, want diverged at the stage", got.res.Outcome, got.res.Step)
	}
}
