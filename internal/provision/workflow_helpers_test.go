package provision

import (
	"context"
	"errors"
	"fmt"
	"sync"
	"testing"

	"github.com/stretchr/testify/mock"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/converter"
	"go.temporal.io/sdk/testsuite"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// testBundleID is the fixture bundle's identity.
const testBundleID = "23f86a2678a49a324a04ae458703be8252e2e30d6712d6b6094ce1ccd5c2988e"

var errUnmocked = errors.New("activity called without a mock")

// harness is a workflow test environment with both workflows and every activity
// registered by name, as the worker registers them, answered by mocks; and a record of the
// order activities started in. No server, no host.
type harness struct {
	t    *testing.T
	env  *testsuite.TestWorkflowEnvironment
	plan wire.CheckHostResult

	mu      sync.Mutex
	started []string
}

func newHarness(t *testing.T) *harness {
	t.Helper()
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestWorkflowEnvironment()
	h := &harness{t: t, env: env, plan: srlinuxCheckHost(t)}

	env.RegisterWorkflow(Provision)
	env.RegisterWorkflow(Destroy)
	stubs := map[string]any{
		wire.ActReadIntent: func(context.Context, ReadIntentInput) (ReadIntentResult, error) {
			return ReadIntentResult{}, errUnmocked
		},
		wire.ActCompile: func(context.Context, CompileInput) (CompileResult, error) {
			return CompileResult{}, errUnmocked
		},
		wire.ActCheckHost: func(context.Context, wire.CheckHostInput) (wire.CheckHostResult, error) {
			return wire.CheckHostResult{}, errUnmocked
		},
		wire.ActStageBundle: func(context.Context, wire.StageInput) (wire.StageResult, error) {
			return wire.StageResult{}, errUnmocked
		},
		wire.ActDeployLab: func(context.Context, wire.DeployInput) (wire.DeployResult, error) {
			return wire.DeployResult{}, errUnmocked
		},
		wire.ActAwaitReadiness: func(context.Context, wire.ReadinessInput) (wire.ReadinessResult, error) {
			return wire.ReadinessResult{}, errUnmocked
		},
		wire.ActPushConfig: func(context.Context, wire.PushInput) (wire.PushResult, error) {
			return wire.PushResult{}, errUnmocked
		},
		wire.ActRecordTwin: func(context.Context, wire.RecordInput) (wire.RecordResult, error) {
			return wire.RecordResult{}, errUnmocked
		},
		wire.ActPlanTeardown: func(context.Context) (wire.PlanTeardownResult, error) {
			return wire.PlanTeardownResult{}, errUnmocked
		},
		wire.ActDestroyLab: func(context.Context, wire.DestroyLabInput) (wire.DestroyLabResult, error) {
			return wire.DestroyLabResult{}, errUnmocked
		},
		wire.ActUnstageTwin: func(context.Context) (wire.UnstageResult, error) {
			return wire.UnstageResult{}, errUnmocked
		},
		ActStartFollowing: func(context.Context, StartFollowingInput) (FollowingResult, error) {
			return FollowingResult{}, errUnmocked
		},
		ActStopFollowing: func(context.Context) (StopFollowingResult, error) {
			return StopFollowingResult{}, errUnmocked
		},
	}
	for name, fn := range stubs {
		env.RegisterActivityWithOptions(fn, activity.RegisterOptions{Name: name})
	}
	env.SetOnActivityStartedListener(func(info *activity.Info, _ context.Context, _ converter.EncodedValues) {
		h.record(info.ActivityType.Name)
	})
	return h
}

// record appends an entry to the order of events the test observes.
func (h *harness) record(entry string) {
	h.mu.Lock()
	defer h.mu.Unlock()
	h.started = append(h.started, entry)
}

// mockHappyPath answers every provisioning activity as a clean three-node SR Linux create
// does. Call it after a test's own mocks: the first matching expectation answers.
func (h *harness) mockHappyPath() {
	env := h.env
	env.OnActivity(wire.ActReadIntent, mock.Anything, mock.Anything).Return(ReadIntentResult{
		CTMPath:    "/state/bundles/.reads/run.ctm.json",
		ObservedAt: "2026-09-15T14:22:12.000000Z",
		Findings:   findings.List{},
	}, nil)
	env.OnActivity(wire.ActCompile, mock.Anything, mock.Anything).Return(CompileResult{
		BundleID:   testBundleID,
		BundlePath: "/state/bundles/" + testBundleID,
		Findings:   findings.List{},
	}, nil)
	env.OnActivity(wire.ActCheckHost, mock.Anything, mock.Anything).Return(h.plan, nil)
	env.OnActivity(wire.ActStageBundle, mock.Anything, mock.Anything).Return(wire.StageResult{TwinDir: "/state/twin"}, nil)
	env.OnActivity(wire.ActDeployLab, mock.Anything, mock.Anything).Return(wire.DeployResult{Nodes: labNodes(h.plan.Nodes)}, nil)
	env.OnActivity(wire.ActAwaitReadiness, mock.Anything, mock.Anything).Return(
		func(_ context.Context, in wire.ReadinessInput) (wire.ReadinessResult, error) {
			return wire.ReadinessResult{Node: in.Node, ReadyAfterS: 0.9}, nil
		})
	env.OnActivity(wire.ActPushConfig, mock.Anything, mock.Anything).Return(pushed)
	env.OnActivity(wire.ActRecordTwin, mock.Anything, mock.Anything).Return(
		func(_ context.Context, in wire.RecordInput) (wire.RecordResult, error) {
			return wire.RecordResult{Path: in.TwinDir + "/twin.json", Record: recordFor(in)}, nil
		})
}

// pushed answers a push as a node that commits its artifact in 0.7s does.
func pushed(_ context.Context, in wire.PushInput) (wire.PushResult, error) {
	return wire.PushResult{Node: in.Node, PushedInS: 0.7, Checksum: in.Checksum, Size: fixtureArtifactSize}, nil
}

// fixtureArtifacts are the fixture bundle's artifact checksums, by node: the ones the
// re-created fylgja-fixture branch rendered.
var fixtureArtifacts = map[string]string{
	"n1": "43e8fd0c2de5f4646f74a51d34742824",
	"n2": "ecb03029ea805a09c54d2cd6a0e59ac9",
	"n3": "ae0c3a87085839354cbb2ca10f71e487",
}

// fixtureArtifactSize is each fixture artifact's size in bytes.
const fixtureArtifactSize = 861

// mockCleanup answers teardown and unstage as a host holding a three-node lab and a twin
// directory does: both removed. Call it after a test's own mocks.
func (h *harness) mockCleanup() {
	h.env.OnActivity(wire.ActDestroyLab, mock.Anything, mock.Anything).Return(
		wire.DestroyLabResult{Removed: true, Containers: 3}, nil)
	h.env.OnActivity(wire.ActUnstageTwin, mock.Anything).Return(
		wire.UnstageResult{Removed: true, Path: "/state/twin"}, nil)
}

// run executes Provision to completion and returns its result. A provisioning run returns
// a result in every case, so a workflow error fails the test.
func (h *harness) run(in ProvisionInput) ProvisionResult {
	h.t.Helper()
	h.env.ExecuteWorkflow(Provision, in)
	if !h.env.IsWorkflowCompleted() {
		h.t.Fatal("the workflow did not complete")
	}
	if err := h.env.GetWorkflowError(); err != nil {
		h.t.Fatalf("the workflow failed: %v", err)
	}
	var res ProvisionResult
	if err := h.env.GetWorkflowResult(&res); err != nil {
		h.t.Fatal(err)
	}
	return res
}

// runDestroy executes Destroy to completion and returns its result; like a provisioning
// run, it returns a result in every case.
func (h *harness) runDestroy() DestroyResult {
	h.t.Helper()
	h.env.ExecuteWorkflow(Destroy)
	if !h.env.IsWorkflowCompleted() {
		h.t.Fatal("the workflow did not complete")
	}
	if err := h.env.GetWorkflowError(); err != nil {
		h.t.Fatalf("the workflow failed: %v", err)
	}
	var res DestroyResult
	if err := h.env.GetWorkflowResult(&res); err != nil {
		h.t.Fatal(err)
	}
	return res
}

// calls is the order activities started in, by name.
func (h *harness) calls() []string {
	h.mu.Lock()
	defer h.mu.Unlock()
	return append([]string(nil), h.started...)
}

// ran reports whether an activity named name started.
func (h *harness) ran(name string) bool {
	for _, c := range h.calls() {
		if c == name {
			return true
		}
	}
	return false
}

// carries reports whether list holds a finding under rule at step.
func carries(list findings.List, rule, step string) bool {
	for _, f := range list {
		if f.Rule == rule && f.Step == step {
			return true
		}
	}
	return false
}

// srlinuxCheckHost is a clear host check for the three-node fixture bundle, every budget
// from the shipped SR Linux package.
func srlinuxCheckHost(t *testing.T) wire.CheckHostResult {
	t.Helper()
	nodes := srlinuxPlan(t)
	sum := 0
	for i := range nodes {
		nodes[i].Probe = wire.Probe{
			Transport: "gnmi_get", Path: "/system/information", Encoding: "json_ietf", Port: 57400,
			UsernameEnv: "FYLGJA_SRLINUX_USERNAME", PasswordEnv: "FYLGJA_SRLINUX_PASSWORD",
		}
		nodes[i].Push.Scheme, nodes[i].Push.Port = "https", 443
		nodes[i].Push.UsernameEnv, nodes[i].Push.PasswordEnv = "FYLGJA_SRLINUX_USERNAME", "FYLGJA_SRLINUX_PASSWORD"
		nodes[i].Artifact = &wire.PlanArtifact{File: "configs/" + nodes[i].Name + ".device-config", Checksum: fixtureArtifacts[nodes[i].Name]}
		sum += nodes[i].MemoryMB
	}
	return wire.CheckHostResult{
		Nodes:       nodes,
		MemorySumMB: sum,
		Provenance:  wire.Provenance{Branch: "fylgja-fixture", SchemaHash: "fixture", ContractVersion: "0.2"},
		Findings:    findings.List{},
	}
}

// labNodes is what containerlab reports after deploying the plan's nodes.
func labNodes(plan []wire.NodePlan) []wire.LabNode {
	nodes := make([]wire.LabNode, len(plan))
	for i, n := range plan {
		nodes[i] = wire.LabNode{
			Name:      n.Name,
			Container: "clab-fylgja-" + n.Name,
			Kind:      "nokia_srlinux",
			Image:     n.Image,
			State:     "running",
			MgmtIPv4:  fmt.Sprintf("172.20.20.%d", i+2),
		}
	}
	return nodes
}

// recordFor is the record RecordTwin would write for in.
func recordFor(in wire.RecordInput) wire.TwinRecord {
	ready := map[string]float64{}
	for _, r := range in.ReadyAfter {
		ready[r.Node] = r.ReadyAfterS
	}
	pushedIn := map[string]float64{}
	for _, p := range in.Pushed {
		pushedIn[p.Node] = p.PushedInS
	}
	nodes := make([]wire.TwinNode, len(in.Nodes))
	for i, n := range in.Nodes {
		nodes[i] = wire.TwinNode{
			Name: n.Name, Container: n.Container, Image: n.Image,
			PSP:      wire.PSPRef{ID: "nokia_srlinux", Source: "embedded"},
			MgmtIPv4: n.MgmtIPv4, ReadyAfterS: ready[n.Name],
			Artifact: &wire.TwinArtifact{Name: "device-config", ContentType: "text/plain",
				Checksum: fixtureArtifacts[n.Name], Size: fixtureArtifactSize},
			PushedInS: pushedIn[n.Name],
		}
	}
	return wire.TwinRecord{
		TwinVersion:   "2",
		Lab:           "fylgja",
		BundleID:      in.BundleID,
		Provenance:    in.Provenance,
		ObservedAt:    in.ObservedAt,
		Source:        in.Source,
		Run:           wire.RunRef{WorkflowID: WorkflowProvision, RunID: in.RunID},
		ProvisionedBy: wire.ProvisionedBy{Version: "0.1.0-test"},
		RecordedAt:    "2026-09-15T14:22:53.39Z",
		Nodes:         nodes,
	}
}
