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
// anything down.
func TestProvisionHappyPath(t *testing.T) {
	h := newHarness(t)
	h.mockHappyPath()

	res := h.run(ProvisionInput{Source: wire.SourceIntent, Branch: "fylgja-fixture"})

	calls := h.calls()
	if len(calls) != 12 {
		t.Fatalf("activities started: %v, want read, compile, host check, stage, deploy, readiness ×3, push ×3, record", calls)
	}
	if want := []string{wire.ActReadIntent, wire.ActCompile, wire.ActCheckHost, wire.ActStageBundle, wire.ActDeployLab}; !slices.Equal(calls[:5], want) {
		t.Errorf("first five activities = %v, want %v", calls[:5], want)
	}
	// The three readiness activities run concurrently, and so do the three pushes, so only
	// their counts are an order.
	for _, c := range calls[5:8] {
		if c != wire.ActAwaitReadiness {
			t.Errorf("activities 6–8 = %v, want three %s", calls[5:8], wire.ActAwaitReadiness)
			break
		}
	}
	for _, c := range calls[8:11] {
		if c != wire.ActPushConfig {
			t.Errorf("activities 9–11 = %v, want three %s", calls[8:11], wire.ActPushConfig)
			break
		}
	}
	if calls[11] != wire.ActRecordTwin {
		t.Errorf("last activity = %s, want %s", calls[11], wire.ActRecordTwin)
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
	if res.Twin.ObservedAt == nil || *res.Twin.ObservedAt != res.ObservedAt {
		t.Errorf("twin observed_at = %v, want the read's %q", res.Twin.ObservedAt, res.ObservedAt)
	}
	if res.Twin.Source != wire.SourceIntent || res.Twin.BundleID != testBundleID {
		t.Errorf("twin record = %+v, want source intent and the compiled bundle", res.Twin)
	}
	for _, n := range res.Twin.Nodes {
		if n.Artifact == nil || n.Artifact.Checksum != fixtureArtifacts[n.Name] || n.PushedInS != 0.7 {
			t.Errorf("twin node %s: artifact %+v, pushed in %v; want its artifact, pushed in 0.7s", n.Name, n.Artifact, n.PushedInS)
		}
	}
}

// A create from a waypoint is M2–M7's pinned create: the same activities in the same
// order, with the waypoint the CLI resolved copied to the record step as data, and nil
// there when none was given.
func TestProvisionCarriesTheWaypointToTheRecord(t *testing.T) {
	waypoint := &WaypointInput{Series: "demo", Sequence: 2, Description: "after the first cut-over", AtSource: "written"}
	for label, given := range map[string]*WaypointInput{"with a waypoint": waypoint, "without": nil} {
		t.Run(label, func(t *testing.T) {
			h := newHarness(t)
			var recorded wire.RecordInput
			h.env.OnActivity(wire.ActRecordTwin, mock.Anything, mock.Anything).Return(
				func(_ context.Context, in wire.RecordInput) (wire.RecordResult, error) {
					recorded = in
					rec := recordFor(in)
					rec.Waypoint = in.Waypoint
					return wire.RecordResult{Path: in.TwinDir + "/twin.json", Record: rec}, nil
				})
			h.mockHappyPath()

			res := h.run(ProvisionInput{Source: wire.SourceIntent, Branch: "change-1", At: "2026-09-28T15:20:44.000000+00:00", Waypoint: given})

			if res.Outcome != OutcomeReady {
				t.Fatalf("outcome %q, findings %+v; want ready", res.Outcome, res.Findings)
			}
			if !reflect.DeepEqual(recorded.Waypoint, given) {
				t.Errorf("record input's waypoint = %+v, want %+v", recorded.Waypoint, given)
			}
			if res.Twin == nil || !reflect.DeepEqual(res.Twin.Waypoint, given) {
				t.Errorf("twin = %+v, want the record naming %+v", res.Twin, given)
			}
			if calls := h.calls(); len(calls) != 12 || calls[11] != wire.ActRecordTwin {
				t.Errorf("activities %v, want the pinned create's twelve, the record last", calls)
			}
		})
	}
}

// The field is omitted when nil, so an M2–M7 input and the record step's input for it
// serialise as they did: the recorded histories' payloads are byte-identical.
func TestAnInputWithNoWaypointSerialisesAsBefore(t *testing.T) {
	for label, v := range map[string]any{
		"ProvisionInput":   ProvisionInput{Source: wire.SourceIntent, Branch: "fylgja-fixture"},
		"wire.RecordInput": wire.RecordInput{Source: wire.SourceIntent},
	} {
		b, err := json.Marshal(v)
		if err != nil {
			t.Fatal(err)
		}
		if strings.Contains(string(b), "waypoint") {
			t.Errorf("%s with no waypoint serialises a waypoint key: %s", label, b)
		}
	}
}

// followInput is a create from intent that follows its branch every 300s.
func followInput() ProvisionInput {
	return ProvisionInput{Source: wire.SourceIntent, Branch: "fylgja-fixture", Version: "0.1.0-test", Follow: &FollowInput{IntervalS: 300}}
}

// mockStartFollowing answers StartFollowing as a created Schedule does, keeping its input.
func (h *harness) mockStartFollowing(got *StartFollowingInput) {
	h.env.OnActivity(ActStartFollowing, mock.Anything, mock.Anything).Return(
		func(_ context.Context, in StartFollowingInput) (FollowingResult, error) {
			*got = in
			return FollowingResult{Branch: in.Branch, IntervalS: in.IntervalS, ScheduleID: FollowScheduleID}, nil
		})
}

// With Follow, following begins once the twin is recorded, and the result says so.
func TestProvisionFollowBeginsAfterRecord(t *testing.T) {
	h := newHarness(t)
	var got StartFollowingInput
	h.mockStartFollowing(&got)
	h.mockHappyPath()

	res := h.run(followInput())

	calls := h.calls()
	if n := len(calls); n < 2 || calls[n-2] != wire.ActRecordTwin || calls[n-1] != ActStartFollowing {
		t.Errorf("activities %v, want RecordTwin then StartFollowing last", calls)
	}
	if want := (StartFollowingInput{Branch: "fylgja-fixture", IntervalS: 300, Version: "0.1.0-test"}); got != want {
		t.Errorf("StartFollowing input %+v, want %+v", got, want)
	}
	if res.Outcome != OutcomeReady || res.Following == nil ||
		*res.Following != (FollowingResult{Branch: "fylgja-fixture", IntervalS: 300, ScheduleID: FollowScheduleID}) {
		t.Errorf("outcome %q, following %+v; want ready and the following begun", res.Outcome, res.Following)
	}
	if len(res.Findings) != 0 {
		t.Errorf("findings %+v, want none", res.Findings)
	}
}

// Without Follow — M2's inputs, --at, --no-follow, a bundle — nothing about following is
// scheduled.
func TestProvisionFollowNilSchedulesNothing(t *testing.T) {
	for _, in := range []ProvisionInput{
		{Source: wire.SourceIntent, Branch: "fylgja-fixture"},
		{Source: wire.SourceBundle, BundlePath: "/state/bundles/" + testBundleID, BundleID: testBundleID},
	} {
		t.Run(in.Source, func(t *testing.T) {
			h := newHarness(t)
			h.mockHappyPath()
			res := h.run(in)
			if res.Outcome != OutcomeReady || res.Following != nil || res.FollowingStopped != nil {
				t.Errorf("result %+v, want ready with no following", res)
			}
			if h.ran(ActStartFollowing) || h.ran(ActStopFollowing) {
				t.Errorf("activities %v, want no following activity", h.calls())
			}
		})
	}
}

// Following that cannot begin leaves the twin ready and frozen, with the warning
// follow.start.failed at step follow (contracts/cli.md).
func TestProvisionFollowStartFailed(t *testing.T) {
	h := newHarness(t)
	h.env.OnActivity(ActStartFollowing, mock.Anything, mock.Anything).Return(FollowingResult{},
		temporal.NewNonRetryableApplicationError("namespace unavailable", "schedule", nil))
	h.mockHappyPath()

	res := h.run(followInput())

	if res.Outcome != OutcomeReady || res.Following != nil || res.Twin == nil {
		t.Errorf("outcome %q, following %+v; want ready, the twin recorded, no following", res.Outcome, res.Following)
	}
	if len(res.Findings) != 1 {
		t.Fatalf("findings %+v, want follow.start.failed alone", res.Findings)
	}
	want := findings.Finding{Severity: findings.Warning, Rule: findings.RuleFollowStartFailed, Object: FollowScheduleID,
		Step: findings.StepFollow, Message: "the twin is ready but following could not begin: creating schedule fylgja-follow failed " +
			"(namespace unavailable); the twin is frozen; fylgja twin destroy and create again to follow"}
	if res.Findings[0] != want {
		t.Errorf("finding %+v\nwant %+v", res.Findings[0], want)
	}
	if h.ran(wire.ActDestroyLab) || h.ran(wire.ActUnstageTwin) {
		t.Errorf("activities %v cleaned up a ready twin", h.calls())
	}
	doc := ProvisionDocument(findings.OpTwinCreate, &findings.Subject{Branch: "fylgja-fixture", RunID: "run-1"}, res)
	if doc.Status != findings.StatusOK || doc.Following != nil {
		t.Errorf("document status %q, following %+v; want ok, and the block left to the command", doc.Status, doc.Following)
	}
}

// A cancellation that reaches the follow step ends the run cancelled at follow, with teardown
// and unstage run, as a cancellation during the record step does.
func TestProvisionFollowCancelled(t *testing.T) {
	h := newHarness(t)
	c := newCanceller(h)
	h.env.OnActivity(ActStartFollowing, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, _ StartFollowingInput) (FollowingResult, error) {
			return FollowingResult{}, c.block(ctx)
		})
	h.mockHappyPath()
	h.mockCleanup()

	res := h.run(followInput())

	if res.Outcome != OutcomeCancelled || res.Step != findings.StepFollow {
		t.Errorf("outcome %q at %q, want cancelled at follow", res.Outcome, res.Step)
	}
	calls := h.calls()
	reached := slices.Index(calls, "cancelled "+ActStartFollowing)
	teardown, unstage := slices.Index(calls, wire.ActDestroyLab), slices.Index(calls, wire.ActUnstageTwin)
	if reached < 0 || teardown < reached || unstage < teardown {
		t.Errorf("order %v: want the cancellation to reach StartFollowing, then teardown, then unstage", calls)
	}
	if res.Following != nil || h.ran(ActStopFollowing) {
		t.Errorf("following %+v, activities %v; a following that never began needs no stop", res.Following, calls)
	}
	doc := ProvisionDocument(findings.OpTwinCreate, &findings.Subject{Branch: "fylgja-fixture", RunID: "run-1"}, res)
	if !carries(doc.Findings, findings.RuleRunCancelled, findings.StepFollow) || doc.Status.ExitCode() != findings.ExitFailed {
		t.Errorf("document %+v, want run.cancelled at follow, exit 3", doc)
	}
}

// A rebuild's provision is already compiled: no read and no compile, the host check and the
// stage given its bundle, and the record saying intent with the check's read.
func TestProvisionAlreadyCompiled(t *testing.T) {
	h := newHarness(t)
	const observed = "2026-09-16T19:10:00.000000Z"
	bundlePath := "/state/bundles/" + testBundleID
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

	res := h.run(ProvisionInput{Source: wire.SourceIntent, Branch: "fylgja-fixture", BundlePath: bundlePath, BundleID: testBundleID,
		ObservedAt: observed})

	if h.ran(wire.ActReadIntent) || h.ran(wire.ActCompile) {
		t.Errorf("activities %v; an already-compiled run reads and compiles nothing", h.calls())
	}
	if checked != (wire.CheckHostInput{BundlePath: bundlePath, BundleID: testBundleID}) {
		t.Errorf("host check got %+v, want the given bundle", checked)
	}
	if recorded.Source != wire.SourceIntent || recorded.ObservedAt == nil || *recorded.ObservedAt != observed {
		t.Errorf("record input source %q, observed_at %v; want intent and %q", recorded.Source, recorded.ObservedAt, observed)
	}
	if res.Outcome != OutcomeReady || res.ObservedAt != observed || res.BundleID != testBundleID {
		t.Errorf("result %+v, want ready with the given bundle and read", res)
	}
}

// With StopFollowing, following is stopped once the host check has cleared and before
// anything is staged, and the result says what was stopped.
func TestProvisionStopStepBeforeStage(t *testing.T) {
	h := newHarness(t)
	h.env.OnActivity(ActStopFollowing, mock.Anything).Return(StopFollowingResult{Deleted: true, Branch: "other"}, nil)
	h.mockHappyPath()

	in := ProvisionInput{Source: wire.SourceIntent, Branch: "fylgja-fixture", StopFollowing: true}
	res := h.run(in)

	calls := h.calls()
	check, stop, stage := slices.Index(calls, wire.ActCheckHost), slices.Index(calls, ActStopFollowing), slices.Index(calls, wire.ActStageBundle)
	if check < 0 || stop != check+1 || stage != stop+1 {
		t.Errorf("activities %v, want CheckHost, StopFollowing, StageBundle in a row", calls)
	}
	if res.Outcome != OutcomeReady || res.FollowingStopped == nil || *res.FollowingStopped != (StopFollowingResult{Deleted: true, Branch: "other"}) {
		t.Errorf("outcome %q, following stopped %+v; want ready and the stopped following of other", res.Outcome, res.FollowingStopped)
	}

	t.Run("nothing to stop", func(t *testing.T) {
		h := newHarness(t)
		h.env.OnActivity(ActStopFollowing, mock.Anything).Return(StopFollowingResult{}, nil)
		h.mockHappyPath()
		if res := h.run(in); res.Outcome != OutcomeReady || res.FollowingStopped != nil {
			t.Errorf("outcome %q, following stopped %+v; want ready and nothing reported stopped", res.Outcome, res.FollowingStopped)
		}
	})
}

// A run the host check refuses leaves following as it was: the stop step is never reached.
// Without StopFollowing, it is never scheduled.
func TestProvisionStopStepNotScheduled(t *testing.T) {
	t.Run("host check refuses", func(t *testing.T) {
		h := newHarness(t)
		refused := h.plan
		refused.Findings = rejection(findings.StepHostCheck, findings.RuleHostLabPresent)
		h.env.OnActivity(wire.ActCheckHost, mock.Anything, mock.Anything).Return(refused, nil)
		h.mockHappyPath()
		res := h.run(ProvisionInput{Source: wire.SourceIntent, Branch: "fylgja-fixture", StopFollowing: true})
		if res.Outcome != OutcomeRejected || h.ran(ActStopFollowing) {
			t.Errorf("outcome %q, activities %v; want rejected with following untouched", res.Outcome, h.calls())
		}
	})
	t.Run("stop not asked", func(t *testing.T) {
		h := newHarness(t)
		h.mockHappyPath()
		if res := h.run(ProvisionInput{Source: wire.SourceIntent, Branch: "fylgja-fixture"}); res.Outcome != OutcomeReady || h.ran(ActStopFollowing) {
			t.Errorf("outcome %q, activities %v; want ready with no stop", res.Outcome, h.calls())
		}
	})
}

// A following that cannot be stopped ends the run at follow with the host untouched:
// follow.stop.failed, nothing staged, nothing to clean up, exit 2 (contracts/cli.md 5a).
func TestProvisionStopStepFails(t *testing.T) {
	h := newHarness(t)
	h.env.OnActivity(ActStopFollowing, mock.Anything).Return(StopFollowingResult{},
		temporal.NewNonRetryableApplicationError("permission denied", "schedule", nil))
	h.mockHappyPath()

	res := h.run(ProvisionInput{Source: wire.SourceIntent, Branch: "fylgja-fixture", StopFollowing: true})

	if res.Outcome != OutcomeError || res.Step != findings.StepFollow {
		t.Errorf("outcome %q at %q, want error at follow", res.Outcome, res.Step)
	}
	for _, a := range []string{wire.ActStageBundle, wire.ActDestroyLab, wire.ActUnstageTwin} {
		if h.ran(a) {
			t.Errorf("activities %v: %s ran after the stop failed", h.calls(), a)
		}
	}
	want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleFollowStopFailed, Object: FollowScheduleID,
		Step: findings.StepFollow, Message: "deleting schedule fylgja-follow failed (permission denied); nothing was staged, " +
			"because a check could otherwise rebuild the twin"}
	if len(res.Findings) != 1 || res.Findings[0] != want {
		t.Errorf("findings %+v\nwant [%+v]", res.Findings, want)
	}
	doc := ProvisionDocument(findings.OpTwinCreate, &findings.Subject{Branch: "fylgja-fixture", RunID: "run-1"}, res)
	if code := doc.Status.ExitCode(); code != findings.ExitError || doc.Cleanup == nil || doc.Cleanup.Teardown != CleanupSkipped {
		t.Errorf("exit %d, cleanup %+v; want 2 with cleanup skipped", code, doc.Cleanup)
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

	res := h.run(ProvisionInput{Source: wire.SourceIntent, Branch: "fylgja-fixture"})
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

	res := h.run(ProvisionInput{Source: wire.SourceIntent, Branch: "mixed-fixture"})
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

	res := h.run(ProvisionInput{Source: wire.SourceIntent, Branch: "mixed-fixture"})
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

			res := h.run(ProvisionInput{Source: wire.SourceIntent, Branch: "fylgja-fixture"})

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

	res := h.run(ProvisionInput{Source: wire.SourceIntent, Branch: "fylgja-fixture"})

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
			h.run(ProvisionInput{Source: wire.SourceIntent, Branch: "fylgja-fixture"})

			mu.Lock()
			defer mu.Unlock()
			want := []string{wire.ActReadIntent, wire.ActCompile, wire.ActCheckHost, wire.ActStageBundle,
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
