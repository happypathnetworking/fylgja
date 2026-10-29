package provision

import (
	"context"
	"encoding/json"
	"fmt"
	"maps"
	"reflect"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/mock"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/converter"
	"go.temporal.io/sdk/temporal"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// A clean create runs every step once, in order, waits for all three nodes, pushes each its
// artifact once every node is ready and before the record, and never tears
// anything down. Its read and compile were the server's, before the run.
func TestProvisionHappyPath(t *testing.T) {
	h := newHarness(t)
	h.mockHappyPath()

	res := h.run(compiled("fylgja-fixture"))

	calls := h.calls()
	if len(calls) != 10 {
		t.Fatalf("activities started: %v, want host check, stage, deploy, readiness ×3, push ×3, record", calls)
	}
	if want := []string{wire.ActCheckHost, wire.ActStageBundle, wire.ActDeployLab}; !slices.Equal(calls[:3], want) {
		t.Errorf("first three activities = %v, want %v", calls[:3], want)
	}
	// The three readiness activities run concurrently, and so do the three pushes, so only
	// their counts are an order.
	for _, c := range calls[3:6] {
		if c != wire.ActAwaitReadiness {
			t.Errorf("activities 4–6 = %v, want three %s", calls[3:6], wire.ActAwaitReadiness)
			break
		}
	}
	for _, c := range calls[6:9] {
		if c != wire.ActPushConfig {
			t.Errorf("activities 7–9 = %v, want three %s", calls[6:9], wire.ActPushConfig)
			break
		}
	}
	if calls[9] != wire.ActRecordTwin {
		t.Errorf("last activity = %s, want %s", calls[9], wire.ActRecordTwin)
	}
	for _, c := range calls {
		if c == wire.ActDestroyLab || c == wire.ActUnstageTwin {
			t.Errorf("%s ran on a clean create", c)
		}
	}

	if res.Outcome != OutcomeReady {
		t.Errorf("outcome = %q, want %q", res.Outcome, OutcomeReady)
	}
	if res.BundleID != testBundleID {
		t.Errorf("bundle id = %q, want %q", res.BundleID, testBundleID)
	}
	if res.TwinDir != "/state/twin" {
		t.Errorf("twin directory = %q, want the one stage reported", res.TwinDir)
	}
	if res.Twin == nil {
		t.Fatal("a ready run carries no twin record")
	}
	if len(res.Twin.Nodes) != 3 {
		t.Errorf("twin nodes = %+v, want three", res.Twin.Nodes)
	}
	if res.ObservedAt != testObservedAt || res.Twin.ObservedAt == nil || *res.Twin.ObservedAt != testObservedAt {
		t.Errorf("observed_at %q, twin's %v; want the read's %q", res.ObservedAt, res.Twin.ObservedAt, testObservedAt)
	}
	if res.Twin.Source != wire.SourceIntent || res.Twin.BundleID != testBundleID {
		t.Errorf("twin record = %+v, want source intent and the given bundle", res.Twin)
	}
	for _, n := range res.Twin.Nodes {
		if n.Artifact == nil || n.Artifact.Checksum != fixtureArtifacts[n.Name] || n.PushedInS != 0.7 {
			t.Errorf("twin node %s: artifact %+v, pushed in %v; want its artifact, pushed in 0.7s", n.Name, n.Artifact, n.PushedInS)
		}
	}
}

// A create from a stage is M2–M7's pinned create (014): the same activities in the same
// order, with the stage the server resolved copied to the record step as data, and nil
// there when none was given.
func TestProvisionCarriesTheStageToTheRecord(t *testing.T) {
	live := &StageInput{ProposedChange: wire.StageChange{ID: "pc-1", Branch: "change-1"}, Label: "live",
		Description: "after the first cut-over", AtSource: "written"}
	for label, given := range map[string]*StageInput{"with a stage": live, "without": nil} {
		t.Run(label, func(t *testing.T) {
			h := newHarness(t)
			var recorded wire.RecordInput
			h.env.OnActivity(wire.ActRecordTwin, mock.Anything, mock.Anything).Return(
				func(_ context.Context, in wire.RecordInput) (wire.RecordResult, error) {
					recorded = in
					rec := recordFor(in)
					rec.Stage = in.Stage
					return wire.RecordResult{Path: in.TwinDir + "/twin.json", Record: rec}, nil
				})
			h.mockHappyPath()

			in := compiled("change-1")
			in.At, in.Stage = "2026-09-28T15:20:44.000000+00:00", given
			res := h.run(in)

			if res.Outcome != OutcomeReady {
				t.Fatalf("outcome %q, findings %+v; want ready", res.Outcome, res.Findings)
			}
			if !reflect.DeepEqual(recorded.Stage, given) {
				t.Errorf("record input's stage = %+v, want %+v", recorded.Stage, given)
			}
			if res.Twin == nil || !reflect.DeepEqual(res.Twin.Stage, given) {
				t.Errorf("twin = %+v, want the record naming %+v", res.Twin, given)
			}
			if calls := h.calls(); len(calls) != 10 || calls[9] != wire.ActRecordTwin {
				t.Errorf("activities %v, want the pinned create's ten, the record last", calls)
			}
		})
	}
}

// A rehearsal's baseline is a create from a stage (015): the same activities, with the
// rehearsal run copied to the record step as data beside the stage, and nil there when the
// run was not a rehearsal's.
func TestProvisionCarriesTheRehearsalToTheRecord(t *testing.T) {
	seeded := &StageInput{ProposedChange: wire.StageChange{ID: "pc-1", Branch: "change-1"}, Label: "seeded",
		Description: "the devices, no links", AtSource: "given"}
	run := &wire.RehearsalRef{WorkflowID: wire.RehearseWorkflowID, RunID: "01a1b2c3-0000-7000-8000-0000000000a1"}
	for label, given := range map[string]*wire.RehearsalRef{"a rehearsal's baseline": run, "a hand create": nil} {
		t.Run(label, func(t *testing.T) {
			h := newHarness(t)
			var recorded wire.RecordInput
			h.env.OnActivity(wire.ActRecordTwin, mock.Anything, mock.Anything).Return(
				func(_ context.Context, in wire.RecordInput) (wire.RecordResult, error) {
					recorded = in
					rec := recordFor(in)
					rec.Stage, rec.Rehearsal = in.Stage, in.Rehearsal
					return wire.RecordResult{Path: in.TwinDir + "/twin.json", Record: rec}, nil
				})
			h.mockHappyPath()

			in := compiled("change-1")
			in.At, in.Stage, in.Rehearsal = "2026-10-19T09:00:00+00:00", seeded, given
			res := h.run(in)

			if res.Outcome != OutcomeReady {
				t.Fatalf("outcome %q, findings %+v; want ready", res.Outcome, res.Findings)
			}
			if !reflect.DeepEqual(recorded.Rehearsal, given) || !reflect.DeepEqual(recorded.Stage, seeded) {
				t.Errorf("record input's rehearsal = %+v, stage %+v; want %+v and %+v", recorded.Rehearsal, recorded.Stage, given, seeded)
			}
			if res.Twin == nil || !reflect.DeepEqual(res.Twin.Rehearsal, given) {
				t.Errorf("twin = %+v, want the record naming %+v", res.Twin, given)
			}
		})
	}
}

// The fields are omitted when nil or empty, so an M2–M7 input and the record step's input
// for it serialise as they did: the recorded histories' payloads are byte-identical. A
// snapshot id is omitted when empty too (018), on the inputs and on a step's sides.
func TestAnInputWithNoStageSerialisesAsBefore(t *testing.T) {
	for label, v := range map[string]any{
		"ProvisionInput":   ProvisionInput{Source: wire.SourceIntent, Branch: "fylgja-fixture"},
		"wire.RecordInput": wire.RecordInput{Source: wire.SourceIntent},
	} {
		b, err := json.Marshal(v)
		if err != nil {
			t.Fatal(err)
		}
		if strings.Contains(string(b), `"stage"`) || strings.Contains(string(b), `"rehearsal"`) || strings.Contains(string(b), `"snapshot_id"`) {
			t.Errorf("%s with no stage, rehearsal or snapshot serialises its key: %s", label, b)
		}
	}
	for label, v := range map[string]any{
		"StepInput":     StepInput{From: wire.StepSide{BundleID: testBundleID}, To: wire.StepSide{BundleID: testBundleID}},
		"RehearseStage": RehearseStage{Ref: "change-1/seeded", BundleID: testBundleID},
	} {
		b, err := json.Marshal(v)
		if err != nil {
			t.Fatal(err)
		}
		if strings.Contains(string(b), `"snapshot_id"`) {
			t.Errorf("%s with no snapshot serialises its key: %s", label, b)
		}
	}
}

// A provision input that names no bundle is a programming error, since every build starts
// a provision compiled: the run ends error at its first step, operation.failed, with no
// activity scheduled and nothing to clean up (R-01).
func TestProvisionWithNoBundleSchedulesNothing(t *testing.T) {
	for _, in := range []ProvisionInput{
		{Source: wire.SourceIntent, Branch: "fylgja-fixture"},
		{Source: wire.SourceSnapshot, SnapshotID: testSnapshotID},
		{Source: wire.SourceBundle, BundlePath: "/state/bundles/" + testBundleID},
	} {
		t.Run(in.Source, func(t *testing.T) {
			h := newHarness(t)
			h.mockHappyPath()
			h.mockCleanup()

			res := h.run(in)

			if calls := h.calls(); len(calls) != 0 {
				t.Errorf("activities %v, want none scheduled", calls)
			}
			if res.Outcome != OutcomeError || res.Step != findings.StepHostCheck || res.Twin != nil {
				t.Errorf("outcome %q at %q, twin %v; want error at the host check with no twin", res.Outcome, res.Step, res.Twin)
			}
			want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleOperationFailed, Object: findings.StepHostCheck,
				Step: findings.StepHostCheck, Message: NoBundleMessage}
			if len(res.Findings) != 1 || res.Findings[0] != want {
				t.Errorf("findings %+v\nwant [%+v]", res.Findings, want)
			}
			if res.Cleanup.Teardown != CleanupSkipped || res.Cleanup.Unstage != CleanupSkipped {
				t.Errorf("cleanup %+v, want both skipped: nothing was touched", res.Cleanup)
			}
			doc := ProvisionDocument(findings.OpTwinCreate, &findings.Subject{Branch: "fylgja-fixture", RunID: "run-1"}, res)
			if code := doc.Status.ExitCode(); code != findings.ExitError {
				t.Errorf("exit %d, want %d", code, findings.ExitError)
			}
			mustValidateM2(t, doc, in.Source)
		})
	}
}

// Both creates the server starts from 018 are already compiled (SC-001): one from intent,
// read, taken and compiled on the server, and one from a snapshot. Each starts at the host
// check with the bundle it was given, and its record step carries the snapshot the input
// names, the read's observed_at and the input's source, as data.
func TestProvisionCreatesCarryTheirSnapshot(t *testing.T) {
	const observed = "2026-10-27T09:31:02.118842Z"
	const snapshotID = "b9db37f826fc612346974b7f54bc5345513662f21c357a0c51fd2802c9b4de00"
	bundlePath := "/state/bundles/" + testBundleID
	for _, c := range []struct {
		name string
		in   ProvisionInput
	}{
		{"from intent", ProvisionInput{Source: wire.SourceIntent, Branch: "fylgja-fixture", BundleID: testBundleID, BundlePath: bundlePath,
			ObservedAt: observed, SnapshotID: snapshotID}},
		{"from a snapshot", ProvisionInput{Source: wire.SourceSnapshot, BundleID: testBundleID, BundlePath: bundlePath,
			ObservedAt: observed, SnapshotID: snapshotID}},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := newHarness(t)
			var checked wire.CheckHostInput
			var recorded wire.RecordInput
			h.env.OnActivity(wire.ActCheckHost, mock.Anything, mock.Anything).Return(
				func(_ context.Context, in wire.CheckHostInput) (wire.CheckHostResult, error) {
					checked = in
					return h.plan, nil
				})
			h.env.OnActivity(wire.ActRecordTwin, mock.Anything, mock.Anything).Return(
				func(_ context.Context, in wire.RecordInput) (wire.RecordResult, error) {
					recorded = in
					return wire.RecordResult{Path: in.TwinDir + "/twin.json", Record: recordFor(in)}, nil
				})
			h.mockHappyPath()

			res := h.run(c.in)

			if res.Outcome != OutcomeReady || res.BundleID != testBundleID || res.ObservedAt != observed {
				t.Fatalf("result %+v, want ready with the given bundle and read", res)
			}
			if calls := h.calls(); len(calls) == 0 || calls[0] != wire.ActCheckHost {
				t.Errorf("activities %v, want the host check first", calls)
			}
			if checked != (wire.CheckHostInput{BundlePath: bundlePath, BundleID: testBundleID}) {
				t.Errorf("host check got %+v, want the given bundle", checked)
			}
			if recorded.SnapshotID != snapshotID || recorded.Source != c.in.Source || recorded.BundleID != testBundleID ||
				recorded.ObservedAt == nil || *recorded.ObservedAt != observed {
				t.Errorf("record input snapshot %q, source %q, bundle %s, observed_at %v; want %s, %s, %s and %s",
					recorded.SnapshotID, recorded.Source, recorded.BundleID, recorded.ObservedAt, snapshotID, c.in.Source, testBundleID, observed)
			}
		})
	}
}

// Each node is pushed the artifact the host check's plan names, at the address deploy
// reported, with its package's push and under its package's budget: push_timeout_s plus
// the margin per attempt and a heartbeat timeout. The record is given every node's result.
func TestProvisionPushesEachNodeItsArtifact(t *testing.T) {
	h := newHarness(t)
	var mu sync.Mutex
	inputs := map[string]wire.PushInput{}
	infos := map[string]activity.Info{}
	h.env.OnActivity(wire.ActPushConfig, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, in wire.PushInput) (wire.PushResult, error) {
			mu.Lock()
			inputs[in.Node], infos[in.Node] = in, activity.GetInfo(ctx)
			mu.Unlock()
			return pushed(ctx, in)
		})
	var recorded wire.RecordInput
	h.env.OnActivity(wire.ActRecordTwin, mock.Anything, mock.Anything).Return(
		func(_ context.Context, in wire.RecordInput) (wire.RecordResult, error) {
			recorded = in
			return wire.RecordResult{Path: in.TwinDir + "/twin.json", Record: recordFor(in)}, nil
		})
	h.mockHappyPath()

	res := h.run(compiled("fylgja-fixture"))
	if res.Outcome != OutcomeReady {
		t.Fatalf("outcome %q with %+v, want ready", res.Outcome, res.Findings)
	}
	mu.Lock()
	defer mu.Unlock()
	for i, node := range labNodes(h.plan.Nodes) {
		want := wire.PushInput{
			Node: node.Name, MgmtIPv4: node.MgmtIPv4, TwinDir: "/state/twin",
			Artifact: "configs/" + node.Name + ".device-config", Checksum: fixtureArtifacts[node.Name],
			Push: h.plan.Nodes[i].Push,
		}
		if inputs[node.Name] != want {
			t.Errorf("%s pushed %+v, want %+v", node.Name, inputs[node.Name], want)
		}
		info := infos[node.Name]
		// The schedule-to-start bound is not in activity.Info; options_test.go pins it.
		if info.StartToCloseTimeout != 45*time.Second || info.HeartbeatTimeout != 30*time.Second {
			t.Errorf("%s push timeouts: start-to-close %s, heartbeat %s; want 45s, 30s",
				node.Name, info.StartToCloseTimeout, info.HeartbeatTimeout)
		}
	}
	if len(recorded.Pushed) != 3 {
		t.Errorf("the record was given %+v, want every node's push", recorded.Pushed)
	}
}

// A host (016) is awaited by its probe package's exec in its own container, with no gNMI
// probe and no login, and is pushed nothing: containerlab configures it from its topology
// node's exec lines. The devices beside it are awaited and pushed as before, and the twin is
// ready.
func TestProvisionAwaitsAHostByExecAndPushesItNothing(t *testing.T) {
	h := newHarness(t)
	exec := wire.ExecProbe{Command: []string{"ip", "-4", "-o", "addr", "show", "dev", "eth1"}, Expect: "10.1.10.2/24", TimeoutS: 30}
	h.plan.Nodes = append(h.plan.Nodes, wire.NodePlan{Name: "n1-loop-a", Image: "alpine:3.24.2", MemoryMB: 32,
		TimeoutS: 30, DeployTimeoutS: 60, DestroyTimeoutS: 30,
		Host: &wire.ProbePlan{Format: "ping", Package: wire.PSPRef{ID: "ping", Source: "embedded"}, Probe: "n1-loop",
			Endpoint: "a", Readiness: exec}})
	var mu sync.Mutex
	awaited := map[string]wire.ReadinessInput{}
	var pushedTo []string
	h.env.OnActivity(wire.ActAwaitReadiness, mock.Anything, mock.Anything).Return(
		func(_ context.Context, in wire.ReadinessInput) (wire.ReadinessResult, error) {
			mu.Lock()
			awaited[in.Node] = in
			mu.Unlock()
			return wire.ReadinessResult{Node: in.Node, ReadyAfterS: 0.4}, nil
		})
	h.env.OnActivity(wire.ActPushConfig, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, in wire.PushInput) (wire.PushResult, error) {
			mu.Lock()
			pushedTo = append(pushedTo, in.Node)
			mu.Unlock()
			return pushed(ctx, in)
		})
	h.mockHappyPath()

	res := h.run(compiled("fylgja-fixture"))
	if res.Outcome != OutcomeReady {
		t.Fatalf("outcome %q with %+v, want ready", res.Outcome, res.Findings)
	}
	mu.Lock()
	defer mu.Unlock()
	host := awaited["n1-loop-a"]
	want := wire.ReadinessInput{Node: "n1-loop-a", MgmtIPv4: "172.20.20.5", TimeoutS: 30, Exec: &exec,
		Container: "clab-fylgja-n1-loop-a"}
	if !reflect.DeepEqual(host, want) {
		t.Errorf("the host was awaited with %+v, want %+v", host, want)
	}
	for _, n := range []string{"n1", "n2", "n3"} {
		if in := awaited[n]; in.Exec != nil || in.Container != "" || in.Probe.Transport != "gnmi_get" {
			t.Errorf("device %s awaited with %+v, want its gNMI probe as before", n, in)
		}
	}
	slices.Sort(pushedTo)
	if !slices.Equal(pushedTo, []string{"n1", "n2", "n3"}) {
		t.Errorf("pushed %v, want the three devices and never the host", pushedTo)
	}
}

// The push step is M5's, and it carries two mechanisms in one run without knowing either:
// each node is sent its own artifact under its own package's delivery, and the twin is
// ready only when every push of both succeeded. No workflow,
// activity or wire type changed for the second mechanism — the step reads node.Push, which
// the plan filled from each node's package.
func TestProvisionPushesBothMechanismsInOneRun(t *testing.T) {
	h := newHarness(t)
	h.plan = mixedCheckHost(t)
	var mu sync.Mutex
	inputs := map[string]wire.PushInput{}
	h.env.OnActivity(wire.ActPushConfig, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, in wire.PushInput) (wire.PushResult, error) {
			mu.Lock()
			inputs[in.Node] = in
			mu.Unlock()
			return wire.PushResult{Node: in.Node, PushedInS: 0.7, Checksum: in.Checksum}, nil
		})
	var recorded wire.RecordInput
	h.env.OnActivity(wire.ActRecordTwin, mock.Anything, mock.Anything).Return(
		func(_ context.Context, in wire.RecordInput) (wire.RecordResult, error) {
			recorded = in
			return wire.RecordResult{Path: in.TwinDir + "/twin.json", Record: recordFor(in)}, nil
		})
	h.mockHappyPath()

	res := h.run(compiled("mixed-fixture"))
	if res.Outcome != OutcomeReady {
		t.Fatalf("outcome %q with %+v, want ready", res.Outcome, res.Findings)
	}
	mu.Lock()
	defer mu.Unlock()

	deliveries := map[string]bool{}
	for i, node := range labNodes(h.plan.Nodes) {
		plan := h.plan.Nodes[i]
		want := wire.PushInput{
			Node: node.Name, MgmtIPv4: node.MgmtIPv4, TwinDir: "/state/twin",
			Artifact: plan.Artifact.File, Checksum: plan.Artifact.Checksum, Push: plan.Push,
		}
		if inputs[node.Name] != want {
			t.Errorf("%s pushed %+v, want %+v", node.Name, inputs[node.Name], want)
		}
		deliveries[plan.Push.Delivery] = true
	}
	if want := map[string]bool{"eapi": true, "json_rpc": true}; !maps.Equal(deliveries, want) {
		t.Errorf("the run pushed by %v, want both mechanisms", deliveries)
	}
	if len(recorded.Pushed) != 3 {
		t.Errorf("the record was given %+v, want every node's push", recorded.Pushed)
	}
}

// Under a replace each push returns the device's diff, and a create's history holds it once,
// as that push's result: the record is given every node's push with the diff stripped and
// the rest of the result kept. Both shipped packages replace.
func TestACreateGivesTheRecordNoDeviceDiff(t *testing.T) {
	h := newHarness(t)
	h.plan = mixedCheckHost(t)
	for _, n := range h.plan.Nodes {
		if n.Push.Mode != "replace" {
			t.Fatalf("%s pushes by %q; the case needs every node on replace", n.Name, n.Push.Mode)
		}
	}
	const deviceDiff = "insert / interface ethernet-1/3 admin-state enable"
	var mu sync.Mutex
	returned := 0
	h.env.OnActivity(wire.ActPushConfig, mock.Anything, mock.Anything).Return(
		func(_ context.Context, in wire.PushInput) (wire.PushResult, error) {
			mu.Lock()
			returned++
			mu.Unlock()
			return wire.PushResult{Node: in.Node, PushedInS: 0.7, Checksum: in.Checksum, Size: 900, Diff: deviceDiff}, nil
		})
	var recorded wire.RecordInput
	h.env.OnActivity(wire.ActRecordTwin, mock.Anything, mock.Anything).Return(
		func(_ context.Context, in wire.RecordInput) (wire.RecordResult, error) {
			recorded = in
			return wire.RecordResult{Path: in.TwinDir + "/twin.json", Record: recordFor(in)}, nil
		})
	h.mockHappyPath()

	res := h.run(compiled("mixed-fixture"))
	if res.Outcome != OutcomeReady {
		t.Fatalf("outcome %q with %+v, want ready", res.Outcome, res.Findings)
	}
	if returned != 3 || len(recorded.Pushed) != 3 {
		t.Fatalf("%d pushes returned a diff and the record was given %d; want three each", returned, len(recorded.Pushed))
	}
	for i, p := range recorded.Pushed {
		node := h.plan.Nodes[i]
		want := wire.PushResult{Node: node.Name, PushedInS: 0.7, Checksum: node.Artifact.Checksum, Size: 900}
		if p != want {
			t.Errorf("the record was given %+v for %s, want %+v: the push's result without its diff", p, node.Name, want)
		}
	}
	raw, err := json.Marshal(recorded)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(raw), deviceDiff) {
		t.Errorf("RecordTwin's input carries the device's diff: %s", raw)
	}
}

// pushOutcome answers each node's push: refused, failed, or committed as pushed does.
func pushOutcome(outcomes map[string]error) func(context.Context, wire.PushInput) (wire.PushResult, error) {
	return func(ctx context.Context, in wire.PushInput) (wire.PushResult, error) {
		if err := outcomes[in.Node]; err != nil {
			return wire.PushResult{}, err
		}
		return pushed(ctx, in)
	}
}

// A node that refuses its artifact fails the run at step push, after cleanup, with every
// node's outcome: the refusal names the nodes that were pushed. A refusal is not retried;
// a push that could not be made is, and fails the run the same way once its attempts are
// spent. The twin is ready only when every push succeeded.
func TestProvisionPushFailureFailsTheRun(t *testing.T) {
	refused := lab.StepFailure(findings.StepPush, findings.RulePushRefused, "n2",
		"node n2 refused artifact device-config (checksum ecb03029ea805a09c54d2cd6a0e59ac9) at line 10: Failed to parse value 'e1-2'")
	unreachable := temporal.NewApplicationError("node n3 did not take artifact device-config: connection refused",
		findings.RulePushFailed, findings.Finding{Severity: findings.Rejection, Rule: findings.RulePushFailed, Object: "n3",
			Step: findings.StepPush, Message: "node n3 did not take artifact device-config: connection refused"})
	for _, c := range []struct {
		name     string
		outcomes map[string]error
		failed   map[string]string // node → the rule its finding carries
		pushed   string
		attempts map[string]int
		leftover bool
	}{
		{"one node refuses", map[string]error{"n2": refused}, map[string]string{"n2": findings.RulePushRefused},
			"pushed: n1 in 0.7s, n3 in 0.7s", map[string]int{"n1": 1, "n2": 1, "n3": 1}, false},
		{"one refuses and one cannot be reached", map[string]error{"n2": refused, "n3": unreachable},
			map[string]string{"n2": findings.RulePushRefused, "n3": findings.RulePushFailed},
			"pushed: n1 in 0.7s", map[string]int{"n1": 1, "n2": 1, "n3": 3}, false},
		{"one refuses and cleanup leaves the lab", map[string]error{"n2": refused}, map[string]string{"n2": findings.RulePushRefused},
			"pushed: n1 in 0.7s, n3 in 0.7s", map[string]int{"n1": 1, "n2": 1, "n3": 1}, true},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := newHarness(t)
			var mu sync.Mutex
			attempts := map[string]int{}
			answer := pushOutcome(c.outcomes)
			h.env.OnActivity(wire.ActPushConfig, mock.Anything, mock.Anything).Return(
				func(ctx context.Context, in wire.PushInput) (wire.PushResult, error) {
					mu.Lock()
					attempts[in.Node]++
					mu.Unlock()
					return answer(ctx, in)
				})
			if c.leftover {
				h.env.OnActivity(wire.ActDestroyLab, mock.Anything, mock.Anything).Return(
					wire.DestroyLabResult{}, injected(findings.StepTeardown, findings.RuleCleanupIncomplete, "lab fylgja"))
			}
			h.mockHappyPath()
			h.mockCleanup()

			res := h.run(compiled("fylgja-fixture"))

			if res.Outcome != OutcomeFailed || res.Step != findings.StepPush || res.Twin != nil {
				t.Fatalf("outcome %q at %q, twin %v; want failed at push with no twin", res.Outcome, res.Step, res.Twin)
			}
			if h.ran(wire.ActRecordTwin) {
				t.Error("the twin was recorded though a push failed")
			}
			var got []findings.Finding
			for _, f := range res.Findings {
				if f.Step == findings.StepPush {
					got = append(got, f)
				}
			}
			if len(got) != len(c.failed) {
				t.Fatalf("push findings %+v, want one for each of %v", got, c.failed)
			}
			for _, f := range got {
				if c.failed[f.Object] != f.Rule || !strings.HasSuffix(f.Message, "; "+c.pushed) {
					t.Errorf("finding %+v, want %s on %s naming %q", f, c.failed[f.Object], f.Object, c.pushed)
				}
			}
			mu.Lock()
			if !maps.Equal(attempts, c.attempts) {
				t.Errorf("push attempts %v, want %v: a refusal is final, a push that could not be made is retried", attempts, c.attempts)
			}
			mu.Unlock()

			doc := ProvisionDocument(findings.OpTwinCreate, &findings.Subject{Branch: "fylgja-fixture", RunID: "run-1"}, res)
			wantStatus, wantTeardown := findings.StatusFailed, CleanupDone
			if c.leftover {
				wantStatus, wantTeardown = findings.StatusUnclean, CleanupFailed
			}
			if doc.Status != wantStatus || res.Cleanup.Teardown != wantTeardown || res.Cleanup.Unstage != CleanupDone {
				t.Errorf("status %q, cleanup %+v; want %q with teardown %s and unstage done", doc.Status, res.Cleanup, wantStatus, wantTeardown)
			}
			mustValidateM5(t, doc, c.name)
		})
	}
}

// A push that failed without the activity wording it — a heartbeat timeout the service
// raised, the worker gone — names the artifact and checksum the node was taking, from the
// plan, as every push.failed does; a failure the activity worded keeps its own message,
// which names both already.
func TestAPushFailureTheActivityNeverWordedNamesTheArtifact(t *testing.T) {
	const worded = "node n3 did not take artifact device-config (checksum x): connection refused"
	h := newHarness(t)
	h.env.OnActivity(wire.ActPushConfig, mock.Anything, mock.Anything).Return(pushOutcome(map[string]error{
		"n2": temporal.NewHeartbeatTimeoutError(),
		"n3": temporal.NewApplicationError(worded, findings.RulePushFailed, findings.Finding{Severity: findings.Rejection,
			Rule: findings.RulePushFailed, Object: "n3", Step: findings.StepPush, Message: worded}),
	}))
	h.mockHappyPath()
	h.mockCleanup()

	res := h.run(compiled("fylgja-fixture"))

	if res.Outcome != OutcomeFailed || res.Step != findings.StepPush {
		t.Fatalf("outcome %q at %q, want failed at push", res.Outcome, res.Step)
	}
	want := map[string]string{
		"n2": "the push of artifact device-config (checksum " + fixtureArtifacts["n2"] + ") to n2 failed: " +
			"no heartbeat from the worker reached the workflow service within the heartbeat timeout",
		"n3": worded + "; pushed: n1 in 0.7s",
	}
	seen := map[string]bool{}
	for _, f := range res.Findings {
		if f.Step != findings.StepPush {
			continue
		}
		seen[f.Object] = true
		if f.Rule != findings.RulePushFailed || !strings.HasPrefix(f.Message, want[f.Object]) {
			t.Errorf("finding %+v, want push.failed beginning %q", f, want[f.Object])
		}
	}
	if !seen["n2"] || !seen["n3"] {
		t.Errorf("push findings name %v, want n2 and n3", seen)
	}
}

// Every activity input a run schedules names paths and identities, never content
// (Constitution VIII): the workflow reads no disk, so a configuration's bytes could
// reach the queue only if a type carried them. Each input is marshalled as the queue
// carries it and walked whole, so a field added later is walked too: no string in it spans
// a line, as every configuration does and no path, name or checksum can, and no key is
// "content". The push names its file and checksum, as the plan gave them. Both a ready run
// and a run that fails at the push and cleans up are walked.
func TestProvisionSchedulesPathsAndIdentitiesOnly(t *testing.T) {
	for _, refuse := range []bool{false, true} {
		t.Run(map[bool]string{false: "ready", true: "failed at push"}[refuse], func(t *testing.T) {
			h := newHarness(t)
			var mu sync.Mutex
			inputs := map[string][]json.RawMessage{}
			h.env.SetOnActivityStartedListener(func(info *activity.Info, _ context.Context, args converter.EncodedValues) {
				var in json.RawMessage
				if args.HasValues() {
					if err := args.Get(&in); err != nil {
						t.Errorf("decoding %s's input: %v", info.ActivityType.Name, err)
					}
				}
				mu.Lock()
				inputs[info.ActivityType.Name] = append(inputs[info.ActivityType.Name], in)
				mu.Unlock()
			})
			if refuse {
				h.env.OnActivity(wire.ActPushConfig, mock.Anything, mock.Anything).Return(pushOutcome(map[string]error{
					"n2": lab.StepFailure(findings.StepPush, findings.RulePushRefused, "n2", "node n2 refused artifact device-config"),
				}))
			}
			h.mockHappyPath()
			h.mockCleanup()
			h.run(compiled("fylgja-fixture"))

			mu.Lock()
			defer mu.Unlock()
			want := []string{wire.ActCheckHost, wire.ActStageBundle,
				wire.ActDeployLab, wire.ActAwaitReadiness, wire.ActPushConfig}
			if refuse {
				want = append(want, wire.ActDestroyLab)
			} else {
				want = append(want, wire.ActRecordTwin)
			}
			for _, name := range want {
				if len(inputs[name]) == 0 {
					t.Errorf("%s was never scheduled, so its input was not walked", name)
				}
			}
			for name, all := range inputs {
				for _, in := range all {
					if len(in) == 0 {
						continue // an activity that takes only its context
					}
					var v any
					if err := json.Unmarshal(in, &v); err != nil {
						t.Fatalf("%s's input is not JSON: %v", name, err)
					}
					walkInput(t, name, "", v)
				}
			}
			for _, in := range inputs[wire.ActPushConfig] {
				var p wire.PushInput
				if err := json.Unmarshal(in, &p); err != nil {
					t.Fatal(err)
				}
				if p.Artifact != "configs/"+p.Node+".device-config" || p.Checksum != fixtureArtifacts[p.Node] {
					t.Errorf("push input %+v, want %s's file by path and its checksum", p, p.Node)
				}
			}
		})
	}
}

// walkInput fails for a string that spans a line or a key named content, anywhere in v.
func walkInput(t *testing.T, activity, at string, v any) {
	t.Helper()
	switch x := v.(type) {
	case map[string]any:
		for k, e := range x {
			if strings.EqualFold(k, "content") {
				t.Errorf("%s's input carries %s.%s", activity, at, k)
			}
			walkInput(t, activity, at+"."+k, e)
		}
	case []any:
		for i, e := range x {
			walkInput(t, activity, fmt.Sprintf("%s[%d]", at, i), e)
		}
	case string:
		if strings.Contains(x, "\n") {
			t.Errorf("%s's input carries a multi-line string at %s: %q", activity, at, x)
		}
	}
}
