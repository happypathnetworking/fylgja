package provision

// Deterministic: a workflow file. No I/O, clock or randomness (Constitution VIII).

import (
	"fmt"
	"path"
	"sort"
	"strings"
	"time"

	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/step"
)

// Step is the step run, fylgja-step: it takes the running waypoint twin to the target the
// CLI resolved, read, compiled and planned, without a rebuild. Its eight steps, every
// activity by its wire.Act* name:
//
//  1. inspect: InspectTwin; the record must still be the one the CLI planned from.
//  2. host check: CheckHost on the target bundle, the two presence refusals dropped, since
//     the twin is there by design (M4's withoutPresence); the twin after the step must
//     fit the host.
//  3. plan reconcile: PlanReconcile, containerlab's own plan, then the plan rules
//     on it as second locks, so a plan that moved since the CLI read it refuses rather than
//     restarting unasked.
//  4. stage: StageStep swaps the target into the twin directory. From here the host is
//     touched, and every failure and cancellation leaves the twin up and diverged.
//  5. reconcile: ReconcileLab, unless the plan is empty or the bundles' content is equal.
//  6. readiness: AwaitReadiness for every node containerlab restarted, recreated or
//     created, all at once, each under its own package's readiness.
//  7. push: PushConfig for every node of the push plan, all at once, every one awaited, so
//     the record names each node's outcome.
//  8. record: RecordStep, on a context the run's cancellation does not reach, after the
//     stage whatever happened: the step's cleanup is its record.
//  9. observe: VerifyTwin, the wait after the record, under the version marker "verify":
//     twin verify's waiting form,
//     on the run's own context, bounded by StepInput.WaitS. It reads, and writes its outcome
//     into the record; nothing of the step's outcome, phase, findings before it, timings or
//     record depends on what it found, and a cancellation during it adds no run.cancelled.
//
// Up to and including step 3 nothing is touched: a refusal is rejected, a step that could
// not run is error, a cancellation is cancelled, and no record is written. Nothing is ever
// torn down: the run has no teardown, no unstage and no Schedule.
//
// It returns a result in every case, never an error. The device's diff, which each push
// returns, is stripped before the result enters any other input or result: the push
// activity's own result in this run's history is its only home.
func Step(ctx workflow.Context, in StepInput) (StepResult, error) {
	started := workflow.Now(ctx).UTC()
	res := StepResult{Findings: findings.List{}, StartedAt: started.Format(time.RFC3339Nano)}

	// 1. What the host holds, which must be the twin the CLI planned from.
	var host wire.HostReport
	if err := execute(ctx, InspectTwinOptions(), wire.ActInspectTwin, &host); err != nil {
		return stepNotRun(ctx, res, started, findings.StepInspect, err), nil
	}
	if ctx.Err() != nil {
		return stepEnded(ctx, res, started, OutcomeCancelled, findings.StepInspect), nil
	}
	if f := Ineligible(host, findings.StepInspect, ""); f != nil {
		res.Findings = append(res.Findings, *f)
		return stepEnded(ctx, res, started, OutcomeRejected, findings.StepInspect), nil
	}
	if f := notPlannedFrom(host.Twin, in.From); f != nil {
		res.Findings = append(res.Findings, *f)
		return stepEnded(ctx, res, started, OutcomeRejected, findings.StepInspect), nil
	}

	// 2. The host for the target: the twin after the step must fit it.
	var plan wire.CheckHostResult
	if err := execute(ctx, CheckHostOptions(), wire.ActCheckHost, &plan,
		wire.CheckHostInput{BundlePath: in.ToBundlePath, BundleID: in.To.BundleID}); err != nil {
		return stepNotRun(ctx, res, started, findings.StepHostCheck, err), nil
	}
	plan.Findings = withoutPresence(plan.Findings)
	res.Findings = append(res.Findings, plan.Findings...)
	// The host check neither heartbeats nor watches its context.
	if ctx.Err() != nil {
		return stepEnded(ctx, res, started, OutcomeCancelled, findings.StepHostCheck), nil
	}
	if plan.Findings.Rejected() {
		return stepEnded(ctx, res, started, OutcomeRejected, findings.StepHostCheck), nil
	}

	// 3. containerlab's own plan, and the rules on it again.
	var lab wire.ReconcilePlan
	if err := execute(ctx, PlanReconcileOptions(), wire.ActPlanReconcile, &lab,
		wire.PlanReconcileInput{BundlePath: in.ToBundlePath, BundleID: in.To.BundleID}); err != nil {
		return stepNotRun(ctx, res, started, findings.StepCompare, err), nil
	}
	res.Plan = &lab
	if ctx.Err() != nil {
		return stepEnded(ctx, res, started, OutcomeCancelled, findings.StepCompare), nil
	}
	rules := PlanRules{Plan: lab, Target: targetPackages(plan.Nodes, in.Declared), Changed: in.Changed,
		AllowRestart: in.AllowRestart}.Findings()
	res.Findings = append(res.Findings, rules...)
	if rules.Rejected() {
		return stepEnded(ctx, res, started, OutcomeRejected, findings.StepCompare), nil
	}

	// 4–7 touch the host; 8 records whatever they did. Every node of the push plan is not
	// attempted until its push says otherwise.
	pushes := withLifecycle(in.PushPlan, lab)
	if in.Unchanged {
		pushes = nil // nothing differs to push
	}
	res.PushPlan = notAttempted(pushes)
	st := stepState{nodes: host.Nodes}
	phase, stop := stepHost(ctx, in, &res, &st, plan, lab)
	res = recordStep(ctx, in, res, st, lab, started, phase, stop)
	if workflow.GetVersion(ctx, VerifyVersionID, workflow.DefaultVersion, 1) >= 1 {
		res = observeStep(ctx, in, res)
	}
	return res, nil
}

// observeStep is the run's step 9: the wait after
// the record, on every record it follows — stepped, unchanged, diverged at any phase, or one
// that could not be written — save a run whose cancellation arrived before it, whose wait
// stays null while run.cancelled says why. VerifyTwin runs on the run's own context with
// WaitForCancellation, so a twin destroy during the pause ends it cancelled, and the run then
// ends as its record says, with the warning and no run.cancelled. An activity that
// failed outright is the wait incomplete, with its finding. A wait that did not settle adds
// the warning verify.wait.unsettled and nothing else: the outcome, phase, findings before it,
// timings and record are the record step's.
func observeStep(ctx workflow.Context, in StepInput, res StepResult) StepResult {
	if ctx.Err() != nil {
		return res
	}
	runID := workflow.GetInfo(ctx).WorkflowExecution.RunID
	var r wire.VerifyResult
	err := execute(ctx, VerifyOptions(in.WaitS), wire.ActVerifyTwin, &r,
		wire.VerifyInput{RunID: runID, From: res.EndedAt, BudgetS: in.WaitS})
	answered := err == nil
	switch {
	case answered:
		res.Wait = &r.Wait
	case temporal.IsCanceledError(err):
		// The cancellation settled the activity before it answered, so it never started: once
		// started it answers a cancellation with its wait (WaitForCancellation). The wait did
		// not begin, as for a run cancelled before it.
		return res
	default:
		f := failureFinding(err, findings.StepObserve, findings.RuleOperationFailed, runID)
		res.Wait = &wire.StepWait{Outcome: wire.WaitIncomplete, BudgetS: in.WaitS, From: res.EndedAt,
			Failing: []wire.StepFinding{{Rule: f.Rule, Object: f.Object, Message: f.Message}}}
	}
	if res.Wait.Outcome != wire.WaitSettled {
		res.Findings = append(res.Findings, unsettledFinding(runID, waitBundle(in, res), *res.Wait, answered))
	}
	return res
}

// waitBundle names the bundle the wait read the twin against: the staged bundle, which is
// the target once the stage has returned. A step whose stage failed leaves the twin directory
// holding whichever of the two the stage reached, so the sentence does not name one.
func waitBundle(in StepInput, res StepResult) string {
	if res.Step == findings.StepStage {
		return "the bundle the twin directory holds"
	}
	return "bundle " + shortBundle(in.To.BundleID)
}

// unsettledFinding is the warning verify.wait.unsettled (contracts/cli.md, twin step --wait):
// at observe, on the run, beginning with how the wait ended — the words the closing line of
// twin step uses — and naming what still failed at its last read by identifier and object.
// answered says whether the activity gave the wait; one that failed outright wrote nothing,
// so the record's wait is null.
func unsettledFinding(runID, bundle string, w wire.StepWait, answered bool) findings.Finding {
	budget := seconds(w.BudgetS).String()
	// An unread node's operation.failed is said whole where the wait could not complete, and
	// named beside the assertions otherwise.
	var unread, all, assertions []string
	for _, f := range w.Failing {
		all = append(all, f.Rule+" "+f.Object)
		if f.Rule == findings.RuleOperationFailed {
			unread = append(unread, f.Message)
			continue
		}
		assertions = append(assertions, f.Rule+" "+f.Object)
	}
	stillFailing := func(names []string, none string) string {
		if len(names) == 0 {
			return "; " + none
		}
		return "; still failing: " + strings.Join(names, ", ")
	}
	var message string
	switch {
	case w.Outcome == wire.WaitExpired:
		message = fmt.Sprintf("expired after %.1fs (%s, budget %s): the twin does not conform to %s%s",
			w.AfterS, plural(w.Reads, "read"), budget, bundle, stillFailing(all, "nothing was failing at the last read"))
	case w.Outcome == wire.WaitCancelled:
		message = fmt.Sprintf("cancelled after %.1fs (%s, budget %s)%s",
			w.AfterS, plural(w.Reads, "read"), budget, stillFailing(all, "nothing was failing at the last read"))
	case !answered:
		message = fmt.Sprintf("could not complete: %s; the record's wait is null", strings.Join(unread, "; "))
	default:
		message = fmt.Sprintf("could not complete: %s%s", strings.Join(unread, "; "),
			stillFailing(assertions, "nothing else was failing at the last read"))
	}
	return findings.Finding{Severity: findings.Warning, Rule: findings.RuleVerifyWaitUnsettled, Object: runID,
		Step: findings.StepObserve, Message: message}
}

// stepState is what the steps that touch the host left for the record: the twin
// directory, whether containerlab's reconcile was scheduled, and the lab's nodes — the
// reconcile's, or the inspection's when none ran.
type stepState struct {
	twinDir          string
	reconcileStarted bool
	nodes            []wire.LabNode
}

// stepHost stages, reconciles, waits for the nodes containerlab touched and pushes: every
// step of the run that touches the host (steps 4–7). It fills res as it
// goes and, when a step stops it, says how and in which phase: reconcile (the stage or the
// reconcile), readiness or push.
func stepHost(ctx workflow.Context, in StepInput, res *StepResult, st *stepState, plan wire.CheckHostResult,
	lab wire.ReconcilePlan) (string, *stopped) {
	var staged wire.StageResult
	if err := execute(ctx, StageStepOptions(), wire.ActStageStep, &staged, wire.StageStepInput{
		BundlePath: in.ToBundlePath, BundleID: in.To.BundleID, FromBundleID: in.From.BundleID,
	}); err != nil {
		return findings.StepReconcile, stepStopAt(ctx, findings.StepStage, findings.RuleStageFailed, in.ToBundlePath, err)
	}
	st.twinDir = staged.TwinDir
	// StageStep never heartbeats, so a cancellation during it arrives here.
	if ctx.Err() != nil {
		return findings.StepReconcile, &stopped{step: findings.StepStage, cancelled: true}
	}
	if in.Unchanged {
		// The content is equal: the stage makes the twin directory the provenance of what
		// runs (Constitution IX), and nothing is reconciled, awaited or pushed.
		return "", nil
	}

	if !lab.Empty() {
		st.reconcileStarted = true
		var reconciled wire.ReconcileResult
		if err := execute(ctx, ReconcileOptions(plan.Nodes), wire.ActReconcileLab, &reconciled,
			wire.ReconcileInput{TwinDir: staged.TwinDir, Nodes: plan.Nodes, Plan: lab}); err != nil {
			return findings.StepReconcile, stepStopAt(ctx, findings.StepReconcile, findings.RuleDeployFailed, "lab "+wire.LabName, err)
		}
		res.Reconcile = &reconciled
		st.nodes = reconciled.Nodes
		if ctx.Err() != nil {
			return findings.StepReconcile, &stopped{step: findings.StepReconcile, cancelled: true}
		}
	}

	byName := make(map[string]wire.NodePlan, len(plan.Nodes))
	for _, n := range plan.Nodes {
		byName[n.Name] = n
	}
	var awaited []wire.NodePlan
	for _, n := range lab.Nodes() {
		if node, ok := byName[n.Node]; ok && n.Reported != wire.ReportedLive {
			awaited = append(awaited, node)
		}
	}
	if len(awaited) > 0 {
		ready, s := awaitStepReadiness(ctx, awaited, st.nodes)
		res.Ready = ready
		if s != nil {
			return findings.StepReadiness, s
		}
	}

	if len(res.PushPlan) == 0 {
		return "", nil
	}
	landed, pushes, s := pushStep(ctx, staged.TwinDir, res.PushPlan, byName, st.nodes)
	res.Pushed, res.PushPlan = landed, pushes
	if s != nil {
		return findings.StepPush, s
	}
	return "", nil
}

// recordStep is the run's step 8: the record, written whole on a
// context the run's cancellation does not reach, on every path after the stage — the
// step's cleanup, which M2's rule says survives everything. The record's
// own failure is record.failed at phase record, the twin diverged, with the previous record
// left whole. Then the result says how the run ended: stepped or unchanged; diverged naming
// the phase, each node and twin destroy (step.diverged); or cancelled beside it.
func recordStep(ctx workflow.Context, in StepInput, res StepResult, st stepState, lab wire.ReconcilePlan,
	started time.Time, phase string, s *stopped) StepResult {
	runID := workflow.GetInfo(ctx).WorkflowExecution.RunID
	ended := workflow.Now(ctx).UTC()
	res.EndedAt = ended.Format(time.RFC3339Nano)
	res.Timings = stepTimings(res, ended.Sub(started))

	outcome := StepStepped
	if in.Unchanged {
		outcome = StepUnchanged
	}
	// The failure's findings, as the record keeps them: identifiers, objects and messages.
	var failure findings.List
	if s != nil {
		outcome = StepDiverged
		res.Step = s.step
		failure = append(failure, s.findings...)
		if s.cancelled {
			failure = append(failure, cancelledAfterStage(runID, s.step, phase, true))
		}
	}

	uninterrupted, _ := workflow.NewDisconnectedContext(ctx)
	var recorded wire.RecordResult
	err := execute(uninterrupted, RecordStepOptions(), wire.ActRecordStep, &recorded, wire.RecordStepInput{
		TwinDir: st.twinDir, From: in.From, To: in.To, Outcome: outcome, Phase: phase, RunID: runID,
		ObservedAt: in.ObservedAt, ReconcileStarted: st.reconcileStarted, AllowRestart: in.AllowRestart,
		Diff: in.Diff, Plan: lab, Declared: in.Declared, Reconcile: res.Reconcile, Ready: res.Ready,
		Pushed: res.Pushed, PushPlan: res.PushPlan, Findings: failure,
		StartedAt: res.StartedAt, EndedAt: res.EndedAt, Nodes: st.nodes,
	})
	written := err == nil
	if written {
		res.Record = &recorded.Record
	}

	res.Outcome, res.Phase = outcome, phase
	if s != nil {
		res.Findings = append(res.Findings, s.findings...)
		if s.cancelled {
			res.Outcome = OutcomeCancelled
			res.Findings = append(res.Findings, cancelledAfterStage(runID, s.step, phase, written))
		}
	}
	if !written {
		object := "twin.json"
		if st.twinDir != "" {
			object = path.Join(st.twinDir, "twin.json")
		}
		res.Findings = append(res.Findings, failureFinding(err, findings.StepRecord, findings.RuleRecordFailed, object))
		if res.Phase == "" {
			res.Outcome, res.Phase, res.Step = StepDiverged, findings.StepRecord, findings.StepRecord
		}
	}
	if res.Phase != "" {
		res.Findings = append(res.Findings, divergedFinding(runID, in, res.Phase, res.PushPlan, written))
	}
	return res
}

// awaitStepReadiness waits for every node containerlab restarted, recreated or created, all
// at once, each under its own package's readiness — await_push_transport included — and the
// readiness step's budget over the nodes awaited. It awaits every
// one, so the record names the nodes that answered beside those that did not, worded as the
// provisioning run's readiness words them. Nothing is pushed until all have answered.
func awaitStepReadiness(ctx workflow.Context, awaited []wire.NodePlan, lab []wire.LabNode) ([]wire.ReadinessResult, *stopped) {
	addr := make(map[string]string, len(lab))
	for _, n := range lab {
		addr[n.Name] = n.MgmtIPv4
	}
	futures := make([]workflow.Future, len(awaited))
	for i, node := range awaited {
		futures[i] = workflow.ExecuteActivity(workflow.WithActivityOptions(ctx, ReadinessOptions(node, awaited)),
			wire.ActAwaitReadiness, wire.ReadinessInput{
				Node:            node.Name,
				MgmtIPv4:        addr[node.Name],
				Probe:           node.Probe,
				TimeoutS:        node.TimeoutS,
				AwaitPushScheme: awaitPushScheme(node),
				AwaitPushPort:   awaitPushPort(node),
			})
	}

	var ready []wire.ReadinessResult
	s := &stopped{step: findings.StepReadiness}
	for i, f := range futures {
		var r wire.ReadinessResult
		err := f.Get(ctx, &r)
		switch {
		case err == nil:
			ready = append(ready, r)
		case temporal.IsCanceledError(err):
			s.cancelled = true
		default:
			s.findings = append(s.findings,
				failureFinding(err, findings.StepReadiness, findings.RuleReadinessTimeout, awaited[i].Name))
		}
	}
	if ctx.Err() != nil {
		s.cancelled = true
	}
	if !s.cancelled && len(s.findings) == 0 {
		return ready, nil
	}
	answered := answeredNodes(ready)
	for i := range s.findings {
		s.findings[i].Message += "; " + answered
	}
	return ready, s
}

// pushStep pushes every node of the plan at once, each under its own package's
// push_timeout_s and the push step's budget over the nodes pushed.
// It awaits every push and returns each node's outcome — landed, refused or failed, with
// the finding's identifier — beside the pushes that landed, each with its Diff stripped.
// A failure is worded as the provisioning run's push words it.
func pushStep(ctx workflow.Context, twinDir string, plan []wire.StepPush, nodes map[string]wire.NodePlan,
	lab []wire.LabNode) ([]wire.PushResult, []wire.StepPush, *stopped) {
	addr := make(map[string]string, len(lab))
	for _, n := range lab {
		addr[n.Name] = n.MgmtIPv4
	}
	out := append([]wire.StepPush{}, plan...)
	var budgeted []wire.NodePlan
	for _, p := range out {
		if n, ok := nodes[p.Node]; ok {
			budgeted = append(budgeted, n)
		}
	}
	s := &stopped{step: findings.StepPush}
	refuse := func(i int, message string) {
		s.findings = append(s.findings, findings.Finding{Severity: findings.Rejection, Rule: findings.RulePushFailed,
			Object: out[i].Node, Step: findings.StepPush, Message: message})
		out[i].Outcome, out[i].Rule = wire.PushFailed, findings.RulePushFailed
	}
	futures := make([]workflow.Future, len(out))
	for i, p := range out {
		node, ok := nodes[p.Node]
		switch {
		case !ok:
			// The push plan names nodes of the target bundle, which the host check planned; this
			// is the second lock, for a plan that names one it did not.
			refuse(i, "the target bundle's plan names no node "+p.Node)
			continue
		case node.Artifact == nil:
			// As the provisioning run's push: bundle.Verify refuses such a manifest before any run.
			refuse(i, "the bundle's manifest names no artifact for node "+p.Node)
			continue
		}
		futures[i] = workflow.ExecuteActivity(workflow.WithActivityOptions(ctx, PushOptions(node, budgeted)),
			wire.ActPushConfig, wire.PushInput{
				Node:     node.Name,
				MgmtIPv4: addr[node.Name],
				TwinDir:  twinDir,
				Artifact: node.Artifact.File,
				Checksum: node.Artifact.Checksum,
				Push:     node.Push,
			})
	}

	var landed []wire.PushResult
	for i, fut := range futures {
		if fut == nil {
			continue
		}
		var r wire.PushResult
		err := fut.Get(ctx, &r)
		switch {
		case err == nil:
			// The device's diff stays in this activity's result in the run's history, and
			// enters no other input or result.
			r.Diff = ""
			landed = append(landed, r)
			took := r.PushedInS
			out[i].Outcome, out[i].TookS = wire.PushLanded, &took
		case temporal.IsCanceledError(err):
			s.cancelled = true
			out[i].Outcome, out[i].Rule = wire.PushFailed, findings.RuleRunCancelled
		default:
			node := nodes[out[i].Node]
			f := failureFinding(err, findings.StepPush, findings.RulePushFailed, node.Name)
			if !carriesFinding(err) {
				f.Message = fmt.Sprintf("the push of artifact %s (checksum %s) to %s failed: %s",
					planArtifactName(node), node.Artifact.Checksum, node.Name, f.Message)
			}
			s.findings = append(s.findings, f)
			out[i].Outcome, out[i].Rule = wire.PushFailed, f.Rule
			if f.Rule == findings.RulePushRefused {
				out[i].Outcome = wire.PushRefused
			}
		}
	}
	if ctx.Err() != nil {
		s.cancelled = true
	}
	if !s.cancelled && len(s.findings) == 0 {
		return landed, out, nil
	}
	took := pushedNodes(landed)
	for i := range s.findings {
		s.findings[i].Message += "; " + took
	}
	return landed, out, s
}

// stepStopAt reports err from a step that touches the host: a cancellation carries no
// finding of its own (run.cancelled is added beside step.diverged), anything else the
// finding its activity gave or, failing that, rule.
func stepStopAt(ctx workflow.Context, at, rule, object string, err error) *stopped {
	s := &stopped{step: at, cancelled: ctx.Err() != nil}
	if temporal.IsCanceledError(err) {
		s.cancelled = true
		return s
	}
	s.findings = findings.List{failureFinding(err, at, rule, object)}
	return s
}

// stepNotRun ends a run at a step before the stage that could not run: error, under the
// finding its activity gave or operation.failed, or cancelled when that is why.
func stepNotRun(ctx workflow.Context, res StepResult, started time.Time, at string, err error) StepResult {
	if ctx.Err() != nil || temporal.IsCanceledError(err) {
		return stepEnded(ctx, res, started, OutcomeCancelled, at)
	}
	res.Findings = append(res.Findings, failureFinding(err, at, findings.RuleOperationFailed, at))
	return stepEnded(ctx, res, started, OutcomeError, at)
}

// stepEnded ends a run that stopped before its stage, with its findings already in res:
// nothing on the host was touched and no record was written. A cancellation carries
// run.cancelled, naming the run (contracts/cli.md: exit 2, no step.diverged).
func stepEnded(ctx workflow.Context, res StepResult, started time.Time, outcome, at string) StepResult {
	ended := workflow.Now(ctx).UTC()
	res.Outcome, res.Step = outcome, at
	res.EndedAt = ended.Format(time.RFC3339Nano)
	res.Timings = wire.StepTimings{WholeS: ended.Sub(started).Seconds()}
	if outcome == OutcomeCancelled {
		runID := workflow.GetInfo(ctx).WorkflowExecution.RunID
		res.Findings.AddStep(findings.Rejection, at, findings.RuleRunCancelled, runID, fmt.Sprintf(
			"run %s was cancelled at step %s, before the host was touched; nothing on the host was touched and the record is unchanged",
			runID, at))
	}
	return res
}

// cancelledAfterStage is run.cancelled for a step cancelled from its stage on, beside
// step.diverged (contracts/cli.md): at the phase, naming the step it reached and whether
// its record was written.
func cancelledAfterStage(runID, at, phase string, written bool) findings.Finding {
	record := "the record was written diverged"
	if !written {
		record = "the record could not be written"
	}
	return findings.Finding{Severity: findings.Rejection, Rule: findings.RuleRunCancelled, Object: runID, Step: phase,
		Message: fmt.Sprintf("run %s was cancelled at step %s; %s and nothing was torn down", runID, at, record)}
}

// divergedFinding is step.diverged (contracts/cli.md): the run, the target, the phase, the
// nodes that landed and those that did not, where the twin is, and twin destroy as the
// remedy. A record that could not be written still says the twin is ready where it was,
// and the sentence says so rather than claiming the record does.
func divergedFinding(runID string, in StepInput, phase string, pushes []wire.StepPush, written bool) findings.Finding {
	where := fmt.Sprintf("the twin is up and diverged at waypoint %s (bundle %s), ", waypointName(in.From.Waypoint),
		shortBundle(in.From.BundleID))
	if written {
		where += "its record says so, and it accepts only fylgja twin destroy"
	} else {
		where += "but its record could not be written and still says it is ready there; fylgja twin destroy clears it"
	}
	return findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepDiverged, Object: runID, Step: phase,
		Message: fmt.Sprintf("step run %s towards waypoint %s (bundle %s) stopped at phase %s: %s; %s",
			runID, waypointName(in.To.Waypoint), shortBundle(in.To.BundleID), phase, Landed(pushes, " "), where)}
}

// stepTimings is each phase's duration the run reached, and the whole: as the
// record computes them from the same results.
func stepTimings(res StepResult, whole time.Duration) wire.StepTimings {
	t := wire.StepTimings{WholeS: whole.Seconds()}
	if r := res.Reconcile; r != nil {
		took := r.TookS
		t.ReconcileS = &took
	}
	for _, r := range res.Ready {
		if t.Readiness == nil {
			t.Readiness = map[string]float64{}
		}
		t.Readiness[r.Node] = r.ReadyAfterS
	}
	for _, p := range res.PushPlan {
		if p.Outcome != wire.PushLanded || p.TookS == nil {
			continue
		}
		if t.Push == nil {
			t.Push = map[string]float64{}
		}
		t.Push[p.Node] = *p.TookS
	}
	return t
}

// withLifecycle is the CLI's push plan with the run's own plan applied:
// every node containerlab's plan restarts, recreates or creates gains that reason, since it
// runs its baseline until a push lands, and a node it deletes is dropped. On the plan
// the CLI read, it is the CLI's push plan unchanged.
func withLifecycle(plan []step.NodePush, lab wire.ReconcilePlan) []step.NodePush {
	life := step.PushPlan(step.Step{}, step.Lifecycle{Restarted: lab.Restarted, Recreated: lab.Recreated,
		Created: lab.Added, Removed: lab.Deleted})
	deleted := map[string]bool{}
	for _, n := range lab.Deleted {
		deleted[n] = true
	}
	reasons := map[string]map[string]bool{}
	for _, list := range [][]step.NodePush{plan, life} {
		for _, p := range list {
			if deleted[p.Node] {
				continue
			}
			if reasons[p.Node] == nil {
				reasons[p.Node] = map[string]bool{}
			}
			for _, r := range p.Reasons {
				reasons[p.Node][r] = true
			}
		}
	}
	out := make([]step.NodePush, 0, len(reasons))
	for _, node := range sortedSet(reasons) {
		out = append(out, step.NodePush{Node: node, Reasons: sortedSet(reasons[node])})
	}
	return out
}

// notAttempted is the push plan before any push: every node not attempted.
func notAttempted(plan []step.NodePush) []wire.StepPush {
	out := make([]wire.StepPush, len(plan))
	for i, p := range plan {
		out[i] = wire.StepPush{Node: p.Node, Reasons: append([]string{}, p.Reasons...), Outcome: wire.PushNotAttempted}
	}
	return out
}

// targetPackages is the target's nodes as the rules read them: the host check's plan gives
// each node's package and how it pushes, and the CLI each package's link-change declaration.
func targetPackages(nodes []wire.NodePlan, declared map[string]string) []NodePackage {
	out := make([]NodePackage, len(nodes))
	for i, n := range nodes {
		out[i] = NodePackage{Node: n.Name, ID: n.PSPID, Mode: n.Push.Mode, LinkChange: declared[n.Name]}
	}
	return out
}

// sortedSet is a set's members, sorted.
func sortedSet[V any](m map[string]V) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

// Eligibility, the second lock, and the rules on containerlab's plan. Each is worded once,
// here, for the CLI's refusal before any connection and for the run's second lock alike.

// Ineligible is the refusal of a host whose twin cannot step, at step at, or
// nil when its twin can: no twin; an orphan, an unreadable record or a record whose lab is
// gone, in M3's phrase; a twin built from a branch or a bundle, which names no series to
// step along; or a diverged twin, which accepts only twin destroy. twinDir
// is the twin directory's path when the caller knows it, the object of a directory found
// without its lab; the run names it "twin directory".
func Ineligible(host wire.HostReport, at, twinDir string) *findings.Finding {
	refuse := func(rule, object, message string) *findings.Finding {
		return &findings.Finding{Severity: findings.Rejection, Rule: rule, Object: object, Step: at, Message: message}
	}
	lab := "lab " + wire.LabName
	switch {
	case !host.LabPresent && !host.TwinDirPresent:
		return refuse(findings.RuleStepTwinUnsteppable, lab,
			"no twin: no "+lab+" and no twin directory; only a twin built from a waypoint steps (fylgja twin create --waypoint)")
	case host.Twin == nil || !host.LabPresent:
		object := lab
		if !host.LabPresent {
			object = "twin directory"
			if twinDir != "" {
				object = twinDir
			}
		}
		return refuse(findings.RuleStepTwinUnsteppable, object,
			host.Phrase+"; only a twin built from a waypoint steps; fylgja twin destroy clears it")
	case host.Twin.State == wire.StateDiverged:
		return refuse(findings.RuleStepTwinDiverged, host.Twin.BundleID, divergedTwin(host.Twin))
	case host.Twin.Waypoint == nil:
		return refuse(findings.RuleStepTwinUnsteppable, host.Twin.BundleID, "the twin was created "+origin(host.Twin)+
			", not from a waypoint, so it names no series to step along; only a twin built from a waypoint steps")
	}
	return nil
}

// WithoutPresence drops host.lab.present and host.twin.present from a host check's
// findings: a step's host check is of the target bundle beside the running twin, which is
// there by design. The run's step 2 drops them through M4's
// withoutPresence, and twin step's own host check through this, so the two agree.
func WithoutPresence(list findings.List) findings.List { return withoutPresence(list) }

// origin says what a twin that names no waypoint was created from.
func origin(rec *wire.TwinRecord) string {
	switch {
	case rec.Source == wire.SourceBundle:
		return "from a bundle"
	case rec.Provenance.At != "":
		return "from branch " + rec.Provenance.Branch + " at " + rec.Provenance.At
	}
	return "from branch " + rec.Provenance.Branch
}

// divergedTwin is step.twin.diverged's message: the step that left the twin diverged.
func divergedTwin(rec *wire.TwinRecord) string {
	st := rec.Step
	if st == nil {
		return "the twin is diverged; it accepts only fylgja twin destroy"
	}
	phase := ""
	if st.Phase != nil {
		phase = *st.Phase
	}
	return fmt.Sprintf("the twin is diverged: step run %s %s towards waypoint %s stopped at phase %s (%s); it accepts only fylgja twin destroy",
		st.Run.WorkflowID, st.Run.RunID, waypointName(st.To.Waypoint), phase, Landed(st.Pushed, ": "))
}

// notPlannedFrom is the run's second lock at inspect: the host's record
// must still name the bundle and waypoint the CLI planned from. Either moving between the
// CLI's look and the run's means the host changed, and nothing is touched.
func notPlannedFrom(rec *wire.TwinRecord, from wire.StepSide) *findings.Finding {
	if rec.BundleID == from.BundleID && sameWaypoint(rec.Waypoint, from.Waypoint) {
		return nil
	}
	return &findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepTwinUnsteppable, Object: rec.BundleID,
		Step: findings.StepInspect, Message: fmt.Sprintf(
			"the twin is at waypoint %s (bundle %s), not at waypoint %s (bundle %s) the step was planned from: the host changed "+
				"after the command looked; nothing was touched; run fylgja twin step again",
			waypointName(rec.Waypoint), shortBundle(rec.BundleID), waypointName(from.Waypoint), shortBundle(from.BundleID))}
}

// sameWaypoint says whether two references name the same waypoint, nil included.
func sameWaypoint(a, b *wire.WaypointRef) bool {
	if a == nil || b == nil {
		return a == b
	}
	return *a == *b
}

// waypointName is a waypoint as the step's lines name it: series/sequence.
func waypointName(w *wire.WaypointRef) string {
	if w == nil {
		return "none"
	}
	return fmt.Sprintf("%s/%d", w.Series, w.Sequence)
}

// shortBundle is a bundle id's first eight characters and an ellipsis, as the step's lines
// print it.
func shortBundle(id string) string {
	if len(id) <= 8 {
		return id
	}
	return id[:8] + "…"
}

// Landed names a step's pushes that landed and those that did not, each of those with the
// identifier of the finding that says why, "none" for an empty side: "landed s1; not landed
// e1 (push.refused)" (contracts/cli.md). sep follows each word: " " in the run's own lines,
// ": " where a diverged twin is described.
func Landed(pushes []wire.StepPush, sep string) string {
	var landed, not []string
	for _, p := range pushes {
		switch {
		case p.Outcome == wire.PushLanded:
			landed = append(landed, p.Node)
		case p.Rule != "":
			not = append(not, fmt.Sprintf("%s (%s)", p.Node, p.Rule))
		default:
			not = append(not, p.Node)
		}
	}
	orNone := func(l []string) string {
		if len(l) == 0 {
			return "none"
		}
		return strings.Join(l, ", ")
	}
	return "landed" + sep + orNone(landed) + "; not landed" + sep + orNone(not)
}

// What a package declares (psp.LinkChangeRestart, psp.LinkChangeLive) and the push mode a
// step cannot use. Workflow code imports no package loader, so the values are repeated
// here, and a test holds them equal to internal/psp's.
const (
	declaredRestart = "restart"
	declaredLive    = "live"
	pushModeMerge   = "merge"
)

// NodePackage is one node's support package as the plan rules read it: its id,
// how it pushes (config.mode), and what it declares a link change does to the node
// (fidelity.link_change; "" where the caller does not know).
type NodePackage struct {
	Node       string
	ID         string
	Mode       string
	LinkChange string
}

// PlanRules is what the plan rules read: containerlab's plan, the target's nodes
// and the from bundle's (the run knows the target's alone, from its host check), what the
// step changes that only a lifecycle applies, and whether --allow-restart was given.
type PlanRules struct {
	Plan         wire.ReconcilePlan
	Target       []NodePackage
	From         []NodePackage
	Changed      []StepChange
	AllowRestart bool
}

// Findings applies the rules, at step compare, in the contract's order: step.package.merge,
// step.node.unapplied, step.restart.required, and the warning step.restart.undeclared
// (contracts/cli.md). --allow-restart on a plan that restarts nothing changes nothing, and
// a created node needs no flag: it boots and is bootstrapped, and loses nothing.
func (r PlanRules) Findings() findings.List {
	list := findings.List{}
	list = append(list, r.merge()...)
	list = append(list, r.unapplied()...)
	if f := r.restartRequired(); f != nil {
		list = append(list, *f)
	}
	return append(list, r.undeclared()...)
}

// merge is step.package.merge, one per package that pushes by merge, naming its nodes in
// both bundles.
func (r PlanRules) merge() findings.List {
	nodes := map[string]map[string]bool{}
	for _, list := range [][]NodePackage{r.Target, r.From} {
		for _, p := range list {
			if p.Mode != pushModeMerge {
				continue
			}
			if nodes[p.ID] == nil {
				nodes[p.ID] = map[string]bool{}
			}
			nodes[p.ID][p.Node] = true
		}
	}
	list := findings.List{}
	for _, id := range sortedSet(nodes) {
		list.AddStep(findings.Rejection, findings.StepCompare, findings.RuleStepPackageMerge, id, fmt.Sprintf(
			"support package %s pushes by merge, which a step cannot use: a step removes what the previous artifact added, "+
				"and only a replace does that; nodes %s; a create from it is unaffected", id, strings.Join(sortedSet(nodes[id]), ", ")))
	}
	return list
}

// unapplied is step.node.unapplied: a node the step changes in image, platform or psp that
// containerlab's plan does not recreate, or adds and the plan does not create. The running
// node would keep what the step means to change.
func (r PlanRules) unapplied() findings.List {
	recreated, created := setOf(r.Plan.Recreated), setOf(r.Plan.Added)
	touched := map[string]wire.PlanNode{}
	for _, n := range r.Plan.Nodes() {
		touched[n.Node] = n
	}
	itsPlan := func(node string) string {
		n, ok := touched[node]
		switch {
		case !ok:
			return "no change"
		case n.Reason != "":
			return n.Reported + " (" + n.Reason + ")"
		}
		return n.Reported
	}
	list := findings.List{}
	for _, c := range r.Changed {
		var changes, kept []string
		added := false
		for _, ch := range c.Changes {
			switch ch {
			case ChangeAdded:
				added = true
			case step.ReasonImage, step.ReasonPlatform, step.ReasonPSP:
				changes = append(changes, ch)
				kept = append(kept, keptWord(ch))
			}
		}
		if added && !created[c.Node] {
			list.AddStep(findings.Rejection, findings.StepCompare, findings.RuleStepNodeUnapplied, c.Node, fmt.Sprintf(
				"node %s is added by the step, but containerlab's reconcile would not create it (its plan: %s); the lab would not run it; a step cannot apply it",
				c.Node, itsPlan(c.Node)))
		}
		if len(changes) > 0 && !recreated[c.Node] {
			list.AddStep(findings.Rejection, findings.StepCompare, findings.RuleStepNodeUnapplied, c.Node, fmt.Sprintf(
				"node %s changes in %s between the two bundles, but containerlab's reconcile would not recreate it (its plan: %s); "+
					"the running node would keep its %s; a step cannot apply it",
				c.Node, strings.Join(changes, ", "), itsPlan(c.Node), strings.Join(kept, " and ")))
		}
	}
	return list
}

// keptWord is what a running node keeps of a change no recreate applies.
func keptWord(change string) string {
	if change == step.ReasonPSP {
		return "package"
	}
	return change
}

// restartRequired is step.restart.required: containerlab's plan restarts or recreates a
// node, which loses its running state and its push until the step pushes it again, and
// --allow-restart was not given. One finding naming
// every such node, each with containerlab's reason and its package's declaration.
func (r PlanRules) restartRequired() *findings.Finding {
	if r.AllowRestart {
		return nil
	}
	pkg := packagesByNode(r.Target)
	var nodes, parts []string
	for _, n := range r.Plan.Nodes() {
		if n.Reported != wire.ReportedRestart && n.Reported != wire.ReportedRecreate {
			continue
		}
		var why []string
		if n.Reason != "" {
			why = append(why, n.Reason)
		}
		if p, ok := pkg[n.Node]; ok {
			declares := "no link change"
			if p.LinkChange != "" {
				declares = p.LinkChange
			}
			why = append(why, "package "+p.ID+" declares "+declares)
		}
		part := n.Reported + " " + n.Node
		if len(why) > 0 {
			part += " (" + strings.Join(why, "; ") + ")"
		}
		nodes, parts = append(nodes, n.Node), append(parts, part)
	}
	if len(nodes) == 0 {
		return nil
	}
	loses := "it loses"
	if len(nodes) > 1 {
		loses = "each loses"
	}
	return &findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepRestartRequired,
		Object: strings.Join(nodes, ", "), Step: findings.StepCompare, Message: fmt.Sprintf(
			"containerlab would %s: %s its running state and its push until the step pushes it again; "+
				"give --allow-restart to proceed, or --dry-run to see the step", andList(parts), loses)}
}

// undeclared is the warning step.restart.undeclared: containerlab's plan restarts a node
// whose package declares a link change live, or re-cables live one whose package declares
// restart. The step acts on containerlab's plan; the record keeps both.
func (r PlanRules) undeclared() findings.List {
	pkg := packagesByNode(r.Target)
	list := findings.List{}
	for _, n := range r.Plan.Nodes() {
		p, ok := pkg[n.Node]
		if !ok {
			continue
		}
		reason := ""
		if n.Reason != "" {
			reason = " (" + n.Reason + ")"
		}
		var message string
		switch {
		case n.Reported == wire.ReportedRestart && p.LinkChange == declaredLive:
			message = fmt.Sprintf("package %s declares that a link change is live, but containerlab's plan restarts %s%s",
				p.ID, n.Node, reason)
		case n.Reported == wire.ReportedLive && p.LinkChange == declaredRestart:
			message = fmt.Sprintf("package %s declares that a link change restarts the node, but containerlab's plan re-cables %s live%s",
				p.ID, n.Node, reason)
		default:
			continue
		}
		list.AddStep(findings.Warning, findings.StepCompare, findings.RuleStepRestartUndeclared, n.Node,
			message+"; the step acts on containerlab's plan and records both")
	}
	return list
}

// packagesByNode indexes a bundle's nodes by name.
func packagesByNode(list []NodePackage) map[string]NodePackage {
	out := make(map[string]NodePackage, len(list))
	for _, p := range list {
		out[p.Node] = p
	}
	return out
}

// setOf is a list's members as a set.
func setOf(list []string) map[string]bool {
	out := make(map[string]bool, len(list))
	for _, n := range list {
		out[n] = true
	}
	return out
}

// andList joins parts as a sentence does: "a", "a and b", "a, b and c".
func andList(parts []string) string {
	if len(parts) <= 1 {
		return strings.Join(parts, "")
	}
	return strings.Join(parts[:len(parts)-1], ", ") + " and " + parts[len(parts)-1]
}

// ChangesOf is every node s changes in image, platform or psp, and every node it adds, with
// those changes, sorted by node: what step.Unapplied names when containerlab's plan does not
// recreate or create it. The CLI carries it in StepInput.Changed for the run's own lock.
func ChangesOf(s step.Step) []StepChange {
	byNode := map[string][]string{}
	for _, c := range s.NodesChanged {
		for _, r := range c.Reasons {
			if r == step.ReasonImage || r == step.ReasonPlatform || r == step.ReasonPSP {
				byNode[c.Node] = append(byNode[c.Node], r)
			}
		}
	}
	for _, n := range s.NodesAdded {
		byNode[n] = append(byNode[n], ChangeAdded)
	}
	out := make([]StepChange, 0, len(byNode))
	for _, n := range sortedSet(byNode) {
		out = append(out, StepChange{Node: n, Changes: byNode[n]})
	}
	return out
}
