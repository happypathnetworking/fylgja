package provision

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/mock"
	"go.temporal.io/sdk/activity"

	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// A twin of two platforms waits for each node under its own package's timeout, never one
// global value: fastos's n1 has 30s and answers at 10s, slowos's n2 has 300s and never
// answers. The run names n2 as timed out and n1 as ready, and cleans up with the larger
// teardown budget (Constitution II).
func TestHeterogeneousBundleWaitsPerPlatform(t *testing.T) {
	h := newHarness(t)
	h.plan = heterogeneousCheckHost(t)

	var mu sync.Mutex
	readinessBudget := map[string]time.Duration{}
	stepBudget := map[string]time.Duration{}
	var teardownBudget time.Duration
	h.env.OnActivity(wire.ActAwaitReadiness, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, in wire.ReadinessInput) (wire.ReadinessResult, error) {
			info := activity.GetInfo(ctx)
			mu.Lock()
			readinessBudget[in.Node] = info.StartToCloseTimeout
			stepBudget[in.Node] = info.ScheduleToCloseTimeout
			mu.Unlock()
			if in.Node == "n2" {
				return wire.ReadinessResult{}, lab.StepFailure(findings.StepReadiness, findings.RuleReadinessTimeout, "n2",
					"n2 did not answer gnmi_get /system/information json_ietf at 172.20.20.3:57400 within 300s; last error: connection refused")
			}
			return wire.ReadinessResult{Node: in.Node, ReadyAfterS: 10}, nil
		})
	h.env.OnActivity(wire.ActDestroyLab, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, _ wire.DestroyLabInput) (wire.DestroyLabResult, error) {
			mu.Lock()
			teardownBudget = activity.GetInfo(ctx).StartToCloseTimeout
			mu.Unlock()
			return wire.DestroyLabResult{Removed: true, Containers: 2}, nil
		})
	h.mockHappyPath()
	h.mockCleanup()

	res := h.run(ProvisionInput{Source: wire.SourceIntent, Branch: "fylgja-fixture"})

	mu.Lock()
	defer mu.Unlock()
	if got := readinessBudget["n1"]; got != 45*time.Second {
		t.Errorf("n1 (fastos) readiness budget = %v, want 45s", got)
	}
	if got := readinessBudget["n2"]; got != 315*time.Second {
		t.Errorf("n2 (slowos) readiness budget = %v, want 315s", got)
	}
	// The step's budget is the larger node's, and it bounds every node from scheduling.
	for _, node := range []string{"n1", "n2"} {
		if got := stepBudget[node]; got != 315*time.Second {
			t.Errorf("%s readiness schedule-to-close = %v, want the step budget 315s", node, got)
		}
	}

	if res.Outcome != OutcomeFailed || res.Step != findings.StepReadiness {
		t.Fatalf("outcome %q at %q, want failed at readiness", res.Outcome, res.Step)
	}
	var timedOut []findings.Finding
	for _, f := range res.Findings {
		if f.Rule == findings.RuleReadinessTimeout {
			timedOut = append(timedOut, f)
		}
	}
	if len(timedOut) != 1 || timedOut[0].Object != "n2" || !strings.Contains(timedOut[0].Message, "ready: n1 in 10.0s") {
		t.Errorf("readiness findings %+v, want n2 timed out with n1 named ready", timedOut)
	}
	if res.Cleanup.Teardown != CleanupDone || res.Cleanup.Unstage != CleanupDone {
		t.Errorf("cleanup %+v, want both done", res.Cleanup)
	}
	if teardownBudget != 120*time.Second {
		t.Errorf("teardown budget = %v, want slowos's 120s", teardownBudget)
	}
}

// Each node is pushed under its own package's push_timeout_s — fastos 30s, slowos 90s —
// plus the margin, never one global value (Constitution II).
func TestHeterogeneousBundlePushesPerPlatform(t *testing.T) {
	h := newHarness(t)
	h.plan = heterogeneousCheckHost(t)
	var mu sync.Mutex
	budget := map[string]time.Duration{}
	h.env.OnActivity(wire.ActPushConfig, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, in wire.PushInput) (wire.PushResult, error) {
			mu.Lock()
			budget[in.Node] = activity.GetInfo(ctx).StartToCloseTimeout
			mu.Unlock()
			return pushed(ctx, in)
		})
	h.mockHappyPath()

	res := h.run(ProvisionInput{Source: wire.SourceIntent, Branch: "fylgja-fixture"})
	if res.Outcome != OutcomeReady {
		t.Fatalf("outcome %q with %+v, want ready", res.Outcome, res.Findings)
	}
	mu.Lock()
	defer mu.Unlock()
	if budget["n1"] != 45*time.Second || budget["n2"] != 105*time.Second {
		t.Errorf("push budgets %v, want n1 (fastos) 45s and n2 (slowos) 105s", budget)
	}
}

// heterogeneousCheckHost is a clear host check for a two-node twin on the synthetic
// packages: n1 on fastos, n2 on slowos, every budget from the package.
func heterogeneousCheckHost(t *testing.T) wire.CheckHostResult {
	t.Helper()
	reg, err := psp.Load(filepath.Join("..", "..", "testdata", "psp", "heterogeneous"))
	if err != nil {
		t.Fatal(err)
	}
	node := func(name, id string) wire.NodePlan {
		p, ok := reg.LookupID(id)
		if !ok {
			t.Fatalf("no package %s", id)
		}
		r, c := p.Readiness, p.Config
		return wire.NodePlan{
			Name: name, PSPID: id, PSPSource: "override", Image: p.Image.Ref,
			MemoryMB: p.Image.Resources.MemoryMB, TimeoutS: r.TimeoutS,
			DeployTimeoutS: p.Image.DeployTimeoutS, DestroyTimeoutS: p.Image.DestroyTimeoutS,
			Probe: wire.Probe{Transport: r.Probe, Path: r.Path, Encoding: r.Encoding, Port: r.PortOrDefault(),
				UsernameEnv: r.Login.UsernameEnv, PasswordEnv: r.Login.PasswordEnv},
			Push: wire.PushSpec{Delivery: c.Delivery, Mode: c.Mode, Commit: c.Commit, Scheme: c.Push.Scheme, Port: c.Push.Port,
				UsernameEnv: c.Push.Login.UsernameEnv, PasswordEnv: c.Push.Login.PasswordEnv, TimeoutS: c.PushTimeoutS},
			Artifact: &wire.PlanArtifact{File: "configs/" + name + ".device-config", Checksum: fixtureArtifacts[name]},
		}
	}
	nodes := []wire.NodePlan{node("n1", "fastos"), node("n2", "slowos")}
	return wire.CheckHostResult{
		Nodes:       nodes,
		MemorySumMB: nodes[0].MemoryMB + nodes[1].MemoryMB,
		Provenance:  wire.Provenance{Branch: "fylgja-fixture", SchemaHash: "fixture", ContractVersion: "0.2"},
		Findings:    findings.List{},
	}
}

// mixedCheckHost is a clear host check for the mixed golden: every node's plan built from
// the package its manifest entry names, exactly as lab.CheckHost builds it from the staged
// bundle. Nothing is invented here — the nodes, their images, their packages and their
// artifacts are read from testdata/golden/mixed/manifest.json.
func mixedCheckHost(t *testing.T) wire.CheckHostResult {
	t.Helper()
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	b, err := os.ReadFile(filepath.Join("..", "..", "testdata", "golden", "mixed", compiler.ManifestFile))
	if err != nil {
		t.Fatal(err)
	}
	var m compiler.Manifest
	if err := json.Unmarshal(b, &m); err != nil {
		t.Fatal(err)
	}
	if len(m.Nodes) != 3 {
		t.Fatalf("the mixed golden has %d nodes, want three", len(m.Nodes))
	}

	var nodes []wire.NodePlan
	sum := 0
	for _, n := range m.Nodes {
		p, ok := reg.LookupID(n.PSP.ID)
		if !ok {
			t.Fatalf("no shipped package %s, which the mixed bundle names for node %s", n.PSP.ID, n.Name)
		}
		r, c := p.Readiness, p.Config
		tls := true
		if r.TLS != nil {
			tls = *r.TLS
		}
		plan := wire.NodePlan{
			Name: n.Name, PSPID: p.Platform.ID, PSPSource: p.Origin, Image: p.Image.Ref,
			MemoryMB: p.Image.Resources.MemoryMB, TimeoutS: r.TimeoutS,
			DeployTimeoutS: p.Image.DeployTimeoutS, DestroyTimeoutS: p.Image.DestroyTimeoutS,
			Probe: wire.Probe{Transport: r.Probe, Path: r.Path, Encoding: r.Encoding, Port: r.PortOrDefault(),
				UsernameEnv: r.Login.UsernameEnv, PasswordEnv: r.Login.PasswordEnv, TLS: &tls},
			Push: wire.PushSpec{Delivery: c.Delivery, Mode: c.Mode, Commit: c.Commit, Scheme: c.Push.Scheme,
				Port: c.Push.Port, UsernameEnv: c.Push.Login.UsernameEnv, PasswordEnv: c.Push.Login.PasswordEnv,
				TimeoutS: c.PushTimeoutS},
			Artifact:           &wire.PlanArtifact{File: n.Artifact.File, Checksum: n.Artifact.Checksum},
			AwaitPushTransport: r.AwaitPushTransport,
		}
		nodes = append(nodes, plan)
		sum += plan.MemoryMB
	}
	return wire.CheckHostResult{
		Nodes:       nodes,
		MemorySumMB: sum,
		Provenance:  wire.Provenance{Branch: "mixed-fixture", SchemaHash: "fixture", ContractVersion: "0.2"},
		Findings:    findings.List{},
	}
}

// The mixed bundle's run takes every per-node value from that node's own package, and
// every step's budget from the largest over the bundle's packages (Constitution II). One
// bundle, one lab, one ready — and two probes, two transports and
// two logins, because a step that collapsed them into one platform's answer would wait on
// the wrong port or push through the wrong mechanism.
func TestMixedBundleRunsEachNodeUnderItsOwnPackage(t *testing.T) {
	h := newHarness(t)
	h.plan = mixedCheckHost(t)

	var mu sync.Mutex
	probes := map[string]wire.Probe{}
	pushes := map[string]wire.PushSpec{}
	readinessBudget := map[string]time.Duration{}
	pushBudget := map[string]time.Duration{}
	var deployBudget time.Duration
	h.env.OnActivity(wire.ActDeployLab, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, _ wire.DeployInput) (wire.DeployResult, error) {
			mu.Lock()
			deployBudget = activity.GetInfo(ctx).StartToCloseTimeout
			mu.Unlock()
			return wire.DeployResult{Nodes: labNodes(h.plan.Nodes)}, nil
		})
	awaitPush := map[string]string{}
	h.env.OnActivity(wire.ActAwaitReadiness, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, in wire.ReadinessInput) (wire.ReadinessResult, error) {
			mu.Lock()
			probes[in.Node], readinessBudget[in.Node] = in.Probe, activity.GetInfo(ctx).StartToCloseTimeout
			if in.AwaitPushScheme != "" || in.AwaitPushPort != 0 {
				awaitPush[in.Node] = fmt.Sprintf("%s:%d", in.AwaitPushScheme, in.AwaitPushPort)
			}
			mu.Unlock()
			return wire.ReadinessResult{Node: in.Node, ReadyAfterS: 1.2}, nil
		})
	h.env.OnActivity(wire.ActPushConfig, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, in wire.PushInput) (wire.PushResult, error) {
			mu.Lock()
			pushes[in.Node], pushBudget[in.Node] = in.Push, activity.GetInfo(ctx).StartToCloseTimeout
			mu.Unlock()
			return wire.PushResult{Node: in.Node, PushedInS: 0.7, Checksum: in.Checksum}, nil
		})
	h.mockHappyPath()

	res := h.run(ProvisionInput{Source: wire.SourceIntent, Branch: "mixed-fixture"})
	if res.Outcome != OutcomeReady {
		t.Fatalf("outcome %q with %+v, want ready", res.Outcome, res.Findings)
	}
	mu.Lock()
	defer mu.Unlock()

	// Only the nodes whose package asks are told to wait for their push transport, and
	// they are told a scheme and a port and nothing else: no login crosses for it (D-029).
	if want := map[string]string{"e1": "https:443", "e2": "https:443"}; !reflect.DeepEqual(awaitPush, want) {
		t.Errorf("await push transport = %v, want %v: s1's package does not ask", awaitPush, want)
	}

	// Each node was probed on its own package's transport, path, port, encoding and
	// login, one of them plaintext and one TLS.
	plaintext, secure := false, true
	for node, want := range map[string]wire.Probe{
		"e1": {Transport: "gnmi_get", Path: "/system/state/hostname", Encoding: "json_ietf", Port: 6030,
			UsernameEnv: "FYLGJA_EOS_USERNAME", PasswordEnv: "FYLGJA_EOS_PASSWORD", TLS: &plaintext},
		"e2": {Transport: "gnmi_get", Path: "/system/state/hostname", Encoding: "json_ietf", Port: 6030,
			UsernameEnv: "FYLGJA_EOS_USERNAME", PasswordEnv: "FYLGJA_EOS_PASSWORD", TLS: &plaintext},
		"s1": {Transport: "gnmi_get", Path: "/system/information", Encoding: "json_ietf", Port: 57400,
			UsernameEnv: "FYLGJA_SRLINUX_USERNAME", PasswordEnv: "FYLGJA_SRLINUX_PASSWORD", TLS: &secure},
	} {
		if got := probes[node]; !sameProbe(got, want) {
			t.Errorf("%s was probed %+v (tls %v), want %+v (tls %v)", node, got, wire.ProbeTLS(got), want, wire.ProbeTLS(want))
		}
	}

	// And pushed through its own package's mechanism, over its own login.
	for node, want := range map[string]wire.PushSpec{
		"e1": {Delivery: "eapi", Mode: "replace", Commit: "explicit", Scheme: "https", Port: 443,
			UsernameEnv: "FYLGJA_EOS_USERNAME", PasswordEnv: "FYLGJA_EOS_PASSWORD", TimeoutS: 30},
		"s1": {Delivery: "json_rpc", Mode: "replace", Commit: "explicit", Scheme: "https", Port: 443,
			UsernameEnv: "FYLGJA_SRLINUX_USERNAME", PasswordEnv: "FYLGJA_SRLINUX_PASSWORD", TimeoutS: 30},
	} {
		if got := pushes[node]; got != want {
			t.Errorf("%s was pushed under %+v, want %+v", node, got, want)
		}
	}

	// The step budgets: the largest of the bundle's packages for the steps that run once,
	// each node's own for the ones that run per node.
	for _, c := range []struct {
		label string
		got   time.Duration
		want  time.Duration
	}{
		{"deploy", deployBudget, 300 * time.Second}, // arista_eos 300 over nokia_srlinux 180
		// This run ends ready and tears nothing down, so the teardown budget is read from
		// the plan rather than from an activity that never ran. Both packages say 60.
		{"teardown", DestroyOptions(MaxDestroyTimeoutS(h.plan.Nodes)).StartToCloseTimeout, 60 * time.Second},
		{"e1 readiness", readinessBudget["e1"], 105 * time.Second}, // 90 + the margin
		{"s1 readiness", readinessBudget["s1"], 75 * time.Second},  // 60 + the margin
		{"readiness step", ReadinessStepBudget(h.plan.Nodes), 105 * time.Second},
		{"e1 push", pushBudget["e1"], 45 * time.Second},
		{"s1 push", pushBudget["s1"], 45 * time.Second},
		{"push step", PushStepBudget(h.plan.Nodes), 45 * time.Second},
	} {
		if c.got != c.want {
			t.Errorf("%s budget = %s, want %s", c.label, c.got, c.want)
		}
	}
}

// sameProbe compares two probes including the value behind the TLS pointer: a plan carries
// it as a pointer so that an M2-era history with no key decodes as TLS.
func sameProbe(a, b wire.Probe) bool {
	a.TLS, b.TLS = nil, nil
	return a == b && wire.ProbeTLS(a) == wire.ProbeTLS(b)
}
