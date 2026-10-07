package lab

import (
	"context"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// The stage swap's scratch names under the twin directory: the
// target is fetched beside the staged bundle, then renamed into its place, and the bundle
// it replaced is removed.
const (
	stepNextDir = ".bundle.next"
	stepPrevDir = ".bundle.prev"
)

// PlanReconcile is containerlab's plan for the running lab against the target bundle:
// the bundle at BundlePath is
// verified to hash to BundleID, as StageBundle verifies what it stages, and its topology is
// dry-run with the twin directory as containerlab's lab directory, so the plan sees the
// lab's stored state. It reads only: nothing of the lab or the twin directory changes.
//
// The workflow re-applies the step's rules to this plan as a second lock before anything is
// touched. Every failure, the bundle or containerlab's, is operation.failed
// at step compare, which no retry helps. Budgeted by CheckHostOptions: a read of 0.4s.
func (a *Activities) PlanReconcile(ctx context.Context, in wire.PlanReconcileInput) (wire.ReconcilePlan, error) {
	failed := func(format string, args ...any) (wire.ReconcilePlan, error) {
		return wire.ReconcilePlan{}, StepFailure(findings.StepCompare, findings.RuleOperationFailed, in.BundlePath,
			fmt.Sprintf(format, args...))
	}
	id, err := bundle.IDOfDir(in.BundlePath)
	if err != nil {
		return failed("reading the target bundle at %s: %v", in.BundlePath, err)
	}
	if id != in.BundleID {
		return failed("the bundle at %s hashes to %s, but the step was given %s", in.BundlePath, id, in.BundleID)
	}
	plan, err := a.Clab.DeployPlan(ctx, filepath.Join(in.BundlePath, compiler.TopologyFile), a.Paths.Twin)
	if err != nil {
		return failed("reading containerlab's plan for bundle %s against the running lab: %v", in.BundleID, err)
	}
	return plan, nil
}

// StageStep swaps the target bundle into the twin directory: from here the host is
// touched, and a failure or cancellation leaves the twin diverged. twin/bundle must hold
// FromBundleID, the bundle the
// step started from: anything else is a lab running what this step did not expect. The
// target is filed in this worker's store (a verified no-op when it holds it) and fetched to
// twin/.bundle.next, then twin/bundle is renamed to twin/.bundle.prev, .bundle.next to
// bundle, and .bundle.prev removed. The topology's path does not move, so the containers'
// absLabPath stays true. clab-fylgja/, the nodes' state and containerlab's
// .state.clab.yaml, is never touched.
//
// Idempotent: a twin/bundle already holding BundleID is a retry finding its work done, and
// one cut between the two renames (no twin/bundle, .bundle.next holding BundleID) is
// finished. Every failure is stage.failed at step stage, which no retry helps. Budgeted by
// StageOptions.
func (a *Activities) StageStep(ctx context.Context, in wire.StageStepInput) (wire.StageResult, error) {
	done := wire.StageResult{TwinDir: a.Paths.Twin}
	staged := a.Paths.TwinBundle
	next, prev := filepath.Join(a.Paths.Twin, stepNextDir), filepath.Join(a.Paths.Twin, stepPrevDir)
	failed := func(object, format string, args ...any) (wire.StageResult, error) {
		return wire.StageResult{}, StepFailure(findings.StepStage, findings.RuleStageFailed, object, fmt.Sprintf(format, args...))
	}
	tidy := func() (wire.StageResult, error) {
		for _, dir := range []string{prev, next} {
			if err := os.RemoveAll(dir); err != nil {
				return failed(dir, "removing %s after the stage: %v", dir, err)
			}
		}
		return done, nil
	}

	present, err := exists(staged)
	if err != nil {
		return failed(staged, "inspecting %s: %v", staged, err)
	}
	if !present {
		// Cut between the two renames: the target is beside the slot, whole.
		if id, err := bundle.IDOfDir(next); err == nil && id == in.BundleID {
			if err := os.Rename(next, staged); err != nil {
				return failed(staged, "moving bundle %s into %s: %v", in.BundleID, staged, err)
			}
			return tidy()
		}
		return failed(staged, "%s holds no bundle; the step started from bundle %s, which the lab no longer has beside it",
			staged, in.FromBundleID)
	}
	got, err := bundle.IDOfDir(staged)
	if err != nil {
		return failed(staged, "reading the bundle at %s: %v", staged, err)
	}
	switch got {
	case in.BundleID:
		return tidy()
	case in.FromBundleID:
	default:
		return failed(staged, "%s holds bundle %s, not bundle %s the step started from: the lab runs something this step did not expect",
			staged, got, in.FromBundleID)
	}

	// Checked before anything is filed, so a bundle the step was not given is never staged.
	id, err := bundle.IDOfDir(in.BundlePath)
	if err != nil {
		return failed(in.BundlePath, "reading the target bundle at %s: %v", in.BundlePath, err)
	}
	if id != in.BundleID {
		return failed(in.BundlePath, "the bundle at %s hashes to %s, but the step was given %s", in.BundlePath, id, in.BundleID)
	}
	if _, err := a.Store.Put(ctx, in.BundlePath); err != nil {
		return failed(in.BundlePath, "filing %s in the bundle store: %v", in.BundlePath, err)
	}
	for _, dir := range []string{next, prev} {
		if err := os.RemoveAll(dir); err != nil {
			return failed(dir, "clearing %s before the stage: %v", dir, err)
		}
	}
	if err := a.Store.Fetch(ctx, in.BundleID, next); err != nil {
		return failed(next, "staging bundle %s into %s: %v", in.BundleID, next, err)
	}
	if err := os.Rename(staged, prev); err != nil {
		return failed(staged, "moving bundle %s aside: %v", in.FromBundleID, err)
	}
	if err := os.Rename(next, staged); err != nil {
		return failed(staged, "moving bundle %s into %s: %v", in.BundleID, staged, err)
	}
	return tidy()
}

// ReconcileLab applies the staged target to the running lab: a containerlab still acting on
// the lab with nothing waiting for
// it is stopped first, as DeployLab stops one; then Clab.Reconcile, a `clab
// deploy` without --reconfigure, so containerlab acts on its own plan and leaves every node
// it does not name as it was. It heartbeats while it works, which is also how a
// cancellation reaches it. containerlab's lifecycle lines are logged by Clab.Reconcile. The
// inspect document it prints is read as a deploy's, and every node of the target must be
// running afterwards (M2's notRunning), or the reconcile is deploy.failed at step
// reconcile, which no retry helps.
//
// Idempotent: a reconcile with nothing left to do takes 0.4s and touches no container.
// Budgeted by DeployOptions, the largest deploy_timeout_s of the target's
// platforms, which a node add (31.3s live) and a recreate (20.3s) sit inside.
func (a *Activities) ReconcileLab(ctx context.Context, in wire.ReconcileInput) (wire.ReconcileResult, error) {
	stop := heartbeat(ctx)
	defer stop()
	topo := filepath.Join(a.Paths.TwinBundle, compiler.TopologyFile)
	cutShort := func() error {
		return interrupted(ctx, findings.StepReconcile, findings.RuleDeployFailed, "lab "+LabName, "clab deploy")
	}
	failed := func(format string, args ...any) error {
		return StepFailure(findings.StepReconcile, findings.RuleDeployFailed, "lab "+LabName, fmt.Sprintf(format, args...))
	}

	if _, err := a.Clab.StopStrays(ctx, topo); err != nil {
		if ctx.Err() != nil {
			return wire.ReconcileResult{}, cutShort()
		}
		return wire.ReconcileResult{}, failed("%v; no second deploy of lab %s was started beside it", err, LabName)
	}
	a.logger().Info("reconciling", "lab", LabName, "restart", in.Plan.Restarted, "recreate", in.Plan.Recreated,
		"create", in.Plan.Added, "delete", in.Plan.Deleted)
	start := time.Now()
	state, err := a.Clab.Reconcile(ctx, topo, a.Paths.Twin)
	took := math.Round(time.Since(start).Seconds()*1000) / 1000
	if ctx.Err() != nil {
		return wire.ReconcileResult{}, cutShort()
	}
	if err != nil {
		return wire.ReconcileResult{}, failed("%v", err)
	}
	if down := notRunning(in.Nodes, state.Nodes); len(down) > 0 {
		return wire.ReconcileResult{}, failed("clab deploy exited 0, but not every node is running: %s", strings.Join(down, ", "))
	}
	return wire.ReconcileResult{Nodes: state.Nodes, TookS: took}, nil
}

// RecordStep writes the record a step leaves, whole and atomically, on every outcome after the
// stage. The current twin.json must be the
// one the step started from, naming in.From's bundle; the twin directory's staged bundle,
// when it is the target, gives the target's provenance, each node's package and its
// artifact; the rest crosses as data. NewStepRecord builds the record and refuses one that
// would claim more than the step did. Every failure is record.failed at step record, and
// leaves the previous record whole. Budgeted by RecordOptions.
//
// The record's nodes are the lab's after the step: the reconcile's report, or the
// inspection before the stage when no reconcile ran. A reconcile that ran and returned no
// report, failed or cut short, may have created, deleted or recreated nodes before it
// stopped, so the lab is read again (labAfterReconcile).
//
// Idempotent (Constitution VIII): a record whose step block names this run is a
// retry finding its work done, an earlier attempt whose write landed and whose answer did
// not. It is returned as written and not written again, before NewStepRecord would refuse
// it as no longer the step's from side. A record naming another run's step, or none, keeps
// every check.
func (a *Activities) RecordStep(ctx context.Context, in wire.RecordStepInput) (wire.RecordResult, error) {
	path := a.Paths.TwinJSON
	failed := func(format string, args ...any) (wire.RecordResult, error) {
		return wire.RecordResult{}, StepFailure(findings.StepRecord, findings.RuleRecordFailed, path,
			fmt.Sprintf("writing %s: "+format, append([]any{path}, args...)...))
	}

	prev, err := ReadRecord(path)
	if err != nil {
		return failed("reading the record the step started from: %v", err)
	}
	if s := prev.Step; in.RunID != "" && s != nil && s.Run.WorkflowID == wire.StepWorkflowID && s.Run.RunID == in.RunID {
		return wire.RecordResult{Path: path, Record: prev}, nil
	}
	staged, err := stagedTarget(a.Paths.TwinBundle, in.To.BundleID)
	if err != nil {
		return failed("%v", err)
	}
	nodes := in.Nodes
	if in.ReconcileStarted && in.Reconcile == nil {
		nodes = a.labAfterReconcile(ctx, in.Nodes)
	}

	tookOf := map[string]float64{}
	for _, p := range in.Pushed {
		tookOf[p.Node] = p.PushedInS
	}
	pushed := make([]wire.StepPush, 0, len(in.PushPlan))
	for _, p := range in.PushPlan {
		if t, ok := tookOf[p.Node]; ok && p.TookS == nil && p.Outcome == wire.PushLanded {
			p.TookS = &t
		}
		pushed = append(pushed, p)
	}
	f := StepFields{
		Outcome: in.Outcome, Phase: in.Phase, From: in.From, To: in.To, ObservedAt: in.ObservedAt,
		RunID: in.RunID, Version: a.Version, AllowRestart: in.AllowRestart,
		Plan: in.Plan, Declared: in.Declared, ReconcileStarted: in.ReconcileStarted,
		ReadyAfter: in.Ready, Pushed: pushed, Findings: in.Findings,
		StartedAt: in.StartedAt, EndedAt: in.EndedAt, RecordedAt: time.Now(),
		Nodes: nodes, Staged: staged,
	}
	if r := in.Reconcile; r != nil {
		took := r.TookS
		f.ReconcileTookS = &took
	}
	rec, err := NewStepRecord(prev, f)
	if err != nil {
		return failed("%v", err)
	}
	if err := WriteRecord(path, rec); err != nil {
		return failed("%v", err)
	}
	return wire.RecordResult{Path: path, Record: rec}, nil
}

// labAfterReconcile is the lab as containerlab reports it after a reconcile that returned
// no report:
// containerlab may have created, deleted or recreated nodes before it failed or was cut
// short, and clab inspect is the truth (Constitution IX). A lab containerlab no longer
// reports has no nodes. A cancelled apply's clab can outlive its activity (setuid), so
// this is the lab when the record was written. A read that fails keeps
// inspected, the nodes read before the stage, so the record is still written.
func (a *Activities) labAfterReconcile(ctx context.Context, inspected []wire.LabNode) []wire.LabNode {
	state, err := a.Clab.InspectAll(ctx)
	if err != nil {
		a.logger().Warn("reading the lab after a reconcile that returned no report failed: recording the nodes inspected before the stage",
			"lab", LabName, "error", err)
		return inspected
	}
	return state.Nodes
}

// stagedTarget is the twin directory's staged bundle as the target, when it hashes to
// target, or nil when it holds another bundle or none: a step stopped at its stage.
func stagedTarget(dir, target string) (*StagedTarget, error) {
	id, err := bundle.IDOfDir(dir)
	if err != nil || id != target {
		// Another bundle, or none, is no target: the step stopped at its stage, which is the
		// record's to say, not a failure to write it.
		return nil, nil
	}
	m, err := readManifest(dir)
	if err != nil {
		return nil, fmt.Errorf("the staged target bundle %s: %v", target, err)
	}
	t := &StagedTarget{BundleID: id, Provenance: wire.Provenance(m.Provenance),
		PSP: map[string]wire.PSPRef{}, Artifacts: map[string]*wire.TwinArtifact{}}
	for _, n := range m.Nodes {
		t.PSP[n.Name] = wire.PSPRef{ID: n.PSP.ID, Source: n.PSP.Source}
		if a := n.Artifact; a != nil {
			t.Artifacts[n.Name] = &wire.TwinArtifact{Name: a.Name, ContentType: a.ContentType, Checksum: a.Checksum, Size: a.Size}
		}
	}
	return t, nil
}
