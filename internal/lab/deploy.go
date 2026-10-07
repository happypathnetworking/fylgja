package lab

import (
	"context"
	"fmt"
	"log/slog"
	"path/filepath"
	"sort"
	"strings"

	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// stateRunning is the state containerlab reports for a node that is up.
const stateRunning = "running"

// DeployLab starts lab fylgja from the staged topology, with containerlab's working
// directory placed beside the bundle copy in the twin directory (CLAB_LABDIR_BASE). It
// heartbeats while it works, which is also how a cancellation reaches
// it; the runner then kills clab's process group and returns only once it has exited.
//
// A containerlab still deploying the lab from an earlier attempt — its worker killed under
// it, since the parent-death signal does not reach a setuid clab — is stopped first, so
// this attempt never deploys beside it. A lab already present can then only be an
// earlier attempt of this run, cut off part-way: the host check refused a present lab
// before anything was staged. A plain deploy over it skips containerlab's post-deploy
// actions and leaves the bootstrap unapplied while the nodes still answer the probe, so it
// is recreated with --reconfigure. containerlab failing, or any planned node not
// running afterwards, is deploy.failed, which no retry helps; the workflow then cleans up.
//
// Budgeted by the largest deploy_timeout_s among the bundle's platforms. SR Linux's
// post-deploy applies the bootstrap and commits before clab returns, so this step is the
// boot wait.
func (a *Activities) DeployLab(ctx context.Context, in wire.DeployInput) (wire.DeployResult, error) {
	stop := heartbeat(ctx)
	defer stop()
	topo := filepath.Join(a.Paths.TwinBundle, compiler.TopologyFile)
	cutShort := func() error {
		return interrupted(ctx, findings.StepDeploy, findings.RuleDeployFailed, "lab "+LabName, "clab deploy")
	}

	if _, err := a.Clab.StopStrays(ctx, topo); err != nil {
		if ctx.Err() != nil {
			return wire.DeployResult{}, cutShort()
		}
		return wire.DeployResult{}, deployFailed("%v; no second deploy of lab %s was started beside it", err, LabName)
	}
	state, err := a.Clab.InspectAll(ctx)
	if err != nil {
		return wire.DeployResult{}, err
	}
	reconfigure := state.Present
	if reconfigure {
		a.logger().Warn("lab already present at deploy: recreating it with --reconfigure",
			"lab", LabName, "nodes", len(state.Nodes))
	}

	deployed, err := a.Clab.Deploy(ctx, topo, a.Paths.Twin, reconfigure)
	if ctx.Err() != nil {
		// Cut short. The runner has killed clab's process group and waited for it, so the
		// cleanup the workflow starts next has nothing still acting on the host.
		return wire.DeployResult{}, cutShort()
	}
	if err != nil {
		return wire.DeployResult{}, deployFailed("%v", err)
	}
	if down := notRunning(in.Nodes, deployed.Nodes); len(down) > 0 {
		return wire.DeployResult{}, deployFailed("clab deploy exited 0, but not every node is running: %s",
			strings.Join(down, ", "))
	}
	return wire.DeployResult{Nodes: deployed.Nodes}, nil
}

func deployFailed(format string, args ...any) error {
	return StepFailure(findings.StepDeploy, findings.RuleDeployFailed, "lab "+LabName, fmt.Sprintf(format, args...))
}

// notRunning names each node containerlab reports in a state other than running, and each
// planned node it does not report at all, sorted.
func notRunning(plan []wire.NodePlan, deployed []wire.LabNode) []string {
	var down []string
	reported := make(map[string]bool, len(deployed))
	for _, n := range deployed {
		reported[n.Name] = true
		switch n.State {
		case stateRunning:
		case "":
			down = append(down, n.Name+" (no state)")
		default:
			down = append(down, n.Name+" "+n.State)
		}
	}
	for _, n := range plan {
		if !reported[n.Name] {
			down = append(down, n.Name+" absent")
		}
	}
	sort.Strings(down)
	return down
}

// PlanTeardown budgets the teardown `twin destroy` runs from the support packages of what
// is there to tear down, never from a constant (Constitution II). It only reads. The staged
// manifest names each node's package; with no manifest — an orphan lab with no twin
// directory — each container's containerlab kind is matched to a package's
// image.clab_kind. A node no package on this worker covers is named in
// Uncovered and budgeted at the one stated default, so it never lowers the budget below it.
//
// It never fails on what it finds: an inspection error yields no budget (DestroyTimeoutS
// 0, which the workflow maps to the default), and DestroyLab, which inspects again,
// reports the error.
func (a *Activities) PlanTeardown(ctx context.Context) (wire.PlanTeardownResult, error) {
	log := a.logger()
	m, err := readManifest(a.Paths.TwinBundle)
	if err == nil {
		plan := wire.PlanTeardownResult{Basis: wire.BasisManifest}
		for _, n := range m.Nodes {
			p, ok := a.Registry.LookupID(n.PSP.ID)
			budgetTeardown(&plan, n.Name, p, ok)
		}
		logTeardownPlan(log, plan)
		return plan, nil
	}
	if present, _ := exists(filepath.Join(a.Paths.TwinBundle, compiler.ManifestFile)); present {
		// An unreadable staged manifest budgets nothing; what containerlab reports still can.
		log.Warn("teardown plan: the staged manifest is unreadable; budgeting from containerlab", "error", err)
	}

	state, err := a.Clab.InspectAll(ctx)
	if err != nil {
		log.Warn("teardown plan: clab inspect failed; the default teardown budget stands in", "error", err)
		return wire.PlanTeardownResult{Basis: wire.BasisInspect}, nil
	}
	if !state.Present {
		return wire.PlanTeardownResult{Basis: wire.BasisNone}, nil
	}
	plan := wire.PlanTeardownResult{Basis: wire.BasisInspect}
	for _, n := range state.Nodes {
		p, ok := a.Registry.LookupKind(n.Kind)
		budgetTeardown(&plan, n.Name, p, ok)
	}
	logTeardownPlan(log, plan)
	return plan, nil
}

// budgetTeardown folds one node into the plan: its package's destroy_timeout_s or, when no
// package covers it, the stated default.
func budgetTeardown(plan *wire.PlanTeardownResult, node string, p *psp.PSP, covered bool) {
	budget := wire.DefaultDestroyTimeoutS
	if covered {
		budget = p.Image.DestroyTimeoutS
	} else {
		plan.Uncovered = append(plan.Uncovered, node)
	}
	plan.DestroyTimeoutS = max(plan.DestroyTimeoutS, budget)
}

func logTeardownPlan(log *slog.Logger, plan wire.PlanTeardownResult) {
	log.Info("teardown plan", "basis", plan.Basis, "destroy_timeout_s", plan.DestroyTimeoutS, "uncovered", plan.Uncovered)
}

// DestroyLab removes lab fylgja, whatever state it is in, and confirms it is gone. By name
// with --cleanup, which converges from a ready, a failed and a killed deploy and leaves
// nothing root-owned in the twin directory. An absent lab is success: there
// was nothing to remove. A containerlab still deploying or destroying the lab, which no
// activity waits for, is stopped first, so the teardown never races it.
//
// Anything short of confirmed gone is cleanup.incomplete, naming what `clab inspect --all`
// still shows and the command that clears it. A cancellation stops clab as DeployLab's
// does, but the workflows run teardown where no cancellation reaches it.
func (a *Activities) DestroyLab(ctx context.Context, in wire.DestroyLabInput) (wire.DestroyLabResult, error) {
	cutShort := func() error {
		return interrupted(ctx, findings.StepTeardown, findings.RuleCleanupIncomplete, "lab "+LabName, "clab destroy")
	}
	if _, err := a.Clab.StopStrays(ctx, filepath.Join(a.Paths.TwinBundle, compiler.TopologyFile)); err != nil {
		if ctx.Err() != nil {
			return wire.DestroyLabResult{}, cutShort()
		}
		return wire.DestroyLabResult{}, teardownIncomplete("%v; lab %s was not torn down beside it", err, LabName)
	}
	before, err := a.Clab.InspectAll(ctx)
	if err != nil {
		return wire.DestroyLabResult{}, teardownIncomplete("lab %s may be present: %v", LabName, err)
	}
	if !before.Present {
		return wire.DestroyLabResult{}, nil
	}
	a.logger().Info("tearing down", "lab", LabName, "nodes", len(before.Nodes), "destroy_timeout_s", in.DestroyTimeoutS)

	stop := heartbeat(ctx)
	destroyErr := a.Clab.Destroy(ctx)
	stop()
	if ctx.Err() != nil {
		return wire.DestroyLabResult{}, cutShort()
	}

	after, err := a.Clab.InspectAll(ctx)
	switch {
	case err != nil:
		return wire.DestroyLabResult{}, teardownIncomplete("lab %s may remain: after clab destroy (%s), %v",
			LabName, exitOf(destroyErr), err)
	case after.Present:
		return wire.DestroyLabResult{}, teardownIncomplete("lab %s is still present after clab destroy (%s): %s",
			LabName, exitOf(destroyErr), describeNodes(after.Nodes))
	case destroyErr != nil:
		return wire.DestroyLabResult{}, teardownIncomplete("%v; clab inspect --all no longer shows lab %s, but its network or host entries may remain",
			destroyErr, LabName)
	}
	return wire.DestroyLabResult{Removed: true, Containers: len(before.Nodes)}, nil
}

func teardownIncomplete(format string, args ...any) error {
	return StepFailure(findings.StepTeardown, findings.RuleCleanupIncomplete, "lab "+LabName,
		fmt.Sprintf(format, args...)+"; clear it with: "+wire.ClearLabCommand)
}

// exitOf says how a containerlab command ended, for a message.
func exitOf(err error) string {
	if err == nil {
		return "exited 0"
	}
	return err.Error()
}

// describeNodes names each node with its state: "n1 running, n2 exited".
func describeNodes(nodes []wire.LabNode) string {
	parts := make([]string, len(nodes))
	for i, n := range nodes {
		parts[i] = n.Name + " " + n.State
	}
	return strings.Join(parts, ", ")
}
