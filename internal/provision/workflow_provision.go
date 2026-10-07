package provision

// Deterministic: a workflow file. No I/O, clock or randomness (Constitution VIII).

import (
	"errors"
	"fmt"
	"path"
	"strings"

	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/workflow"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// Provision is the provisioning run: read, compile, check the host, stage, deploy, wait
// for every node, push each its configuration, record. Activities are scheduled by name
// with the options their budgets give them, and
// everything the run needs to know about the host arrives in activity results, never from
// disk.
//
// It returns a result in every case, never an error, so the CLI reads one shape. Up to and
// including the host check nothing on the host has been touched: a refusal
// is rejected, a step that could not run is error, a cancellation is cancelled, and there
// is nothing to clean up. Once the host check has cleared, every way the run can stop
// short of ready — a failure or a cancellation at any step — runs teardown and unstage to
// completion first.
//
// A run from a stored bundle (twin provision) has no read and no compile: it starts at the
// host check with the bundle it was given, and records that no read took place. A rebuild's
// provision is already compiled: from intent with BundleID set, it
// starts at the host check too, and records the check's read.
//
// Following (M4) adds two steps, each taken only when the input asks, so M2's inputs run
// and replay as they did. With StopFollowing, once the host check has cleared and before
// anything is staged, any following is stopped: a refused run leaves following as it was,
// and a stop that fails ends the run with the host untouched. With Follow, once the twin is
// recorded, following of the branch begins; a failure to begin is a warning on a ready run.
func Provision(ctx workflow.Context, in ProvisionInput) (ProvisionResult, error) {
	res := ProvisionResult{
		Findings: findings.List{},
		Cleanup:  CleanupResult{Teardown: CleanupSkipped, Unstage: CleanupSkipped},
	}

	compiled := CompileResult{BundleID: in.BundleID, BundlePath: in.BundlePath}
	var observedAt *string
	switch {
	case in.Source == wire.SourceBundle:
	case in.BundleID != "":
		// Already compiled: the read that produced the bundle was the check's.
		res.ObservedAt = in.ObservedAt
		observedAt = &in.ObservedAt
	default:
		read, ok := readAndCompile(ctx, in, &res, &compiled)
		if !ok {
			return res, nil
		}
		observedAt = &read.ObservedAt
	}
	res.BundleID = compiled.BundleID

	var plan wire.CheckHostResult
	if err := execute(ctx, CheckHostOptions(), wire.ActCheckHost, &plan,
		wire.CheckHostInput{BundlePath: compiled.BundlePath, BundleID: compiled.BundleID}); err != nil {
		return untouched(ctx, res, findings.StepHostCheck, err), nil
	}
	res.Findings = append(res.Findings, plan.Findings...)
	// The host check neither heartbeats nor watches its context, so a cancellation that
	// arrives while it runs does not stop it: its plan comes back with no error. Nothing on
	// the host has been touched, so the run ends here as cancelled, whatever
	// the plan says, rather than going on to a cleanup it has no need of.
	if ctx.Err() != nil {
		return untouched(ctx, res, findings.StepHostCheck, nil), nil
	}
	if plan.Findings.Rejected() {
		return rejected(res, findings.StepHostCheck), nil
	}
	if in.StopFollowing {
		if ended, ok := stopFollowingBeforeStage(ctx, &res); !ok {
			return ended, nil
		}
	}

	if s := provisionHost(ctx, in, &res, observedAt, compiled, plan); s != nil {
		return cleanUp(ctx, res, plan, s), nil
	}
	return res, nil
}

// stopFollowingBeforeStage is the run's stop step: it deletes any following, so no check
// can rebuild over the twin this run is about to build. The host check found no lab and no
// twin directory, so a check still in flight has nothing to compare against and needs no
// cancelling. It reports false when the run ends here, with the result
// that says how: nothing on the host has been touched.
func stopFollowingBeforeStage(ctx workflow.Context, res *ProvisionResult) (ProvisionResult, bool) {
	var stopped StopFollowingResult
	if err := execute(ctx, FollowOptions(), ActStopFollowing, &stopped); err != nil {
		if ctx.Err() != nil || temporal.IsCanceledError(err) {
			return untouched(ctx, *res, findings.StepFollow, err), false
		}
		out := *res
		out.Outcome, out.Step = OutcomeError, findings.StepFollow
		out.Findings = append(out.Findings, findings.Finding{
			Severity: findings.Rejection,
			Rule:     findings.RuleFollowStopFailed,
			Object:   FollowScheduleID,
			Step:     findings.StepFollow,
			Message:  FollowStopFailedMessage(errors.New(causeMessage(err)), "staged"),
		})
		return out, false
	}
	if stopped.Deleted {
		res.FollowingStopped = &stopped
	}
	// StopFollowing never heartbeats, so a cancellation during it arrives here.
	if ctx.Err() != nil {
		return untouched(ctx, *res, findings.StepFollow, nil), false
	}
	return *res, true
}

// readAndCompile reads the branch and compiles it, filling res with their findings and
// compiled with the stored bundle. It reports false when the run ends here, with res
// already saying how: nothing on the host has been touched yet.
func readAndCompile(ctx workflow.Context, in ProvisionInput, res *ProvisionResult, compiled *CompileResult) (ReadIntentResult, bool) {
	var read ReadIntentResult
	if err := execute(ctx, ReadOptions(), wire.ActReadIntent, &read,
		ReadIntentInput{Branch: in.Branch, At: in.At}); err != nil {
		*res = untouched(ctx, *res, findings.StepRead, err)
		return read, false
	}
	res.ObservedAt = read.ObservedAt
	res.Findings = append(res.Findings, read.Findings...)
	if read.Findings.Rejected() {
		*res = rejected(*res, findings.StepRead)
		return read, false
	}

	if err := execute(ctx, CompileOptions(), wire.ActCompile, compiled,
		CompileInput{CTMPath: read.CTMPath}); err != nil {
		*res = untouched(ctx, *res, findings.StepCompile, err)
		return read, false
	}
	res.BundleID = compiled.BundleID
	res.Findings = append(res.Findings, compiled.Findings...)
	if compiled.Findings.Rejected() {
		*res = rejected(*res, findings.StepCompile)
		return read, false
	}
	return read, true
}

// provisionHost stages, deploys, waits for every node and records the twin: every step
// that touches the host. It fills res as it goes and, if a step stops it, says how.
// observedAt is nil when no read took place.
func provisionHost(ctx workflow.Context, in ProvisionInput, res *ProvisionResult,
	observedAt *string, compiled CompileResult, plan wire.CheckHostResult) *stopped {
	var staged wire.StageResult
	if err := execute(ctx, StageOptions(), wire.ActStageBundle, &staged,
		wire.StageInput{BundlePath: compiled.BundlePath, BundleID: compiled.BundleID}); err != nil {
		return stopAt(ctx, findings.StepStage, compiled.BundlePath, err)
	}
	res.TwinDir = staged.TwinDir
	if s := cancelledAfter(ctx, findings.StepStage); s != nil {
		return s
	}

	var deployed wire.DeployResult
	if err := execute(ctx, DeployOptions(plan.Nodes), wire.ActDeployLab, &deployed,
		wire.DeployInput{TwinDir: staged.TwinDir, Nodes: plan.Nodes}); err != nil {
		return stopAt(ctx, findings.StepDeploy, "lab "+wire.LabName, err)
	}
	if s := cancelledAfter(ctx, findings.StepDeploy); s != nil {
		return s
	}

	ready, s := awaitReadiness(ctx, plan.Nodes, deployed.Nodes)
	if s != nil {
		return s
	}

	// The push step (M5). A history recorded before it carries no version marker, replays
	// at DefaultVersion and skips the step; every run this build starts records the marker
	// and pushes. The DefaultVersion branch exists for those histories alone.
	var pushed []wire.PushResult
	if workflow.GetVersion(ctx, PushVersionID, workflow.DefaultVersion, 1) >= 1 {
		pushed, s = pushConfigs(ctx, staged.TwinDir, plan.Nodes, deployed.Nodes)
		if s != nil {
			return s
		}
		if s := cancelledAfter(ctx, findings.StepPush); s != nil {
			return s
		}
	}

	var recorded wire.RecordResult
	if err := execute(ctx, RecordOptions(), wire.ActRecordTwin, &recorded, wire.RecordInput{
		TwinDir:    staged.TwinDir,
		BundleID:   compiled.BundleID,
		Provenance: plan.Provenance,
		ObservedAt: observedAt,
		Source:     in.Source,
		RunID:      workflow.GetInfo(ctx).WorkflowExecution.RunID,
		Nodes:      deployed.Nodes,
		ReadyAfter: ready,
		Pushed:     pushed,
		Waypoint:   in.Waypoint,
	}); err != nil {
		return stopAt(ctx, findings.StepRecord, staged.TwinDir, err)
	}
	if s := cancelledAfter(ctx, findings.StepRecord); s != nil {
		return s
	}

	if in.Follow != nil {
		if s := startFollowing(ctx, in, res); s != nil {
			return s
		}
	}
	res.Outcome = OutcomeReady
	res.Twin = &recorded.Record
	return nil
}

// startFollowing is the run's follow step: the twin is ready and recorded, and following of
// its branch begins. A failure to begin leaves a ready twin that is frozen, with the warning
// follow.start.failed (contracts/cli.md). A cancellation that arrived meanwhile ends the run
// cancelled with cleanup, as one during the record step does; a following that began in the
// meantime is stopped again first, so the cleanup leaves no Schedule checking a twin that
// is gone.
func startFollowing(ctx workflow.Context, in ProvisionInput, res *ProvisionResult) *stopped {
	var following FollowingResult
	err := execute(ctx, FollowOptions(), ActStartFollowing, &following,
		StartFollowingInput{Branch: in.Branch, IntervalS: in.Follow.IntervalS, Version: in.Version})
	switch {
	case err == nil:
		res.Following = &following
	case ctx.Err() == nil && !temporal.IsCanceledError(err):
		res.Findings.AddStep(findings.Warning, findings.StepFollow, findings.RuleFollowStartFailed, FollowScheduleID,
			FollowStartFailedMessage(causeMessage(err)))
	}
	if ctx.Err() == nil {
		return nil
	}
	s := &stopped{step: findings.StepFollow, cancelled: true}
	if res.Following != nil {
		uninterrupted, _ := workflow.NewDisconnectedContext(ctx)
		if err := execute(uninterrupted, FollowOptions(), ActStopFollowing, nil); err != nil {
			s.findings = findings.List{{Severity: findings.Warning, Rule: findings.RuleFollowStopFailed, Object: FollowScheduleID,
				Step: findings.StepFollow, Message: "deleting schedule " + FollowScheduleID + " failed (" + causeMessage(err) +
					") after the run was cancelled; its checks find nothing to compare against; fylgja twin destroy stops it"}}
		}
		res.Following = nil
	}
	return s
}

// FollowStartFailedMessage is follow.start.failed's message (contracts/cli.md).
func FollowStartFailedMessage(cause string) string {
	return "the twin is ready but following could not begin: creating schedule " + FollowScheduleID +
		" failed (" + cause + "); the twin is frozen; fylgja twin destroy and create again to follow"
}

// cancelledAfter stops the run at step when a cancellation arrived while step's activity
// ran. WaitForCancellation lets a started activity finish, and one that does not see the
// cancellation — the record step never heartbeats; a deploy may finish before its next
// heartbeat — returns its result with no error, as though no cancellation had come.
// Unchecked, a cancellation during the record step ended the run ready with nothing
// cleaned up, and one during stage or deploy was reported at the step after.
func cancelledAfter(ctx workflow.Context, step string) *stopped {
	if ctx.Err() == nil {
		return nil
	}
	return &stopped{step: step, cancelled: true}
}

// awaitReadiness waits for every node at once, each under its own package's timeout,
// scheduled in the plan's name order. It awaits every one before answering, so
// a failure names both the nodes that did not answer and the ones that did.
func awaitReadiness(ctx workflow.Context, plan []wire.NodePlan, deployed []wire.LabNode) ([]wire.ReadinessResult, *stopped) {
	addr := make(map[string]string, len(deployed))
	for _, n := range deployed {
		addr[n.Name] = n.MgmtIPv4
	}
	futures := make([]workflow.Future, len(plan))
	for i, node := range plan {
		futures[i] = workflow.ExecuteActivity(workflow.WithActivityOptions(ctx, ReadinessOptions(node, plan)),
			wire.ActAwaitReadiness, wire.ReadinessInput{
				Node:     node.Name,
				MgmtIPv4: addr[node.Name],
				Probe:    node.Probe,
				TimeoutS: node.TimeoutS,
				// Only for a node whose package asks, and only the scheme and the port:
				// the wait opens a connection and closes it, so no login crosses (D-029).
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
				failureFinding(err, findings.StepReadiness, findings.RuleReadinessTimeout, plan[i].Name))
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
	return nil, s
}

// answeredNodes names the nodes that answered their probe, and when.
func answeredNodes(ready []wire.ReadinessResult) string {
	if len(ready) == 0 {
		return "no node answered"
	}
	parts := make([]string, len(ready))
	for i, r := range ready {
		parts[i] = fmt.Sprintf("%s in %.1fs", r.Node, r.ReadyAfterS)
	}
	return "ready: " + strings.Join(parts, ", ")
}

// pushConfigs pushes every node its artifact at once, each under its own package's
// push_timeout_s, scheduled in the plan's name order, once every node is ready. It awaits
// every push before answering, so a failure names both the
// nodes that did not take their configuration and the ones that did. The twin is
// ready only when every push succeeded.
func pushConfigs(ctx workflow.Context, twinDir string, plan []wire.NodePlan, deployed []wire.LabNode) ([]wire.PushResult, *stopped) {
	addr := make(map[string]string, len(deployed))
	for _, n := range deployed {
		addr[n.Name] = n.MgmtIPv4
	}
	s := &stopped{step: findings.StepPush}
	futures := make([]workflow.Future, len(plan))
	for i, node := range plan {
		if node.Artifact == nil {
			// A bundle this build writes names one for every node, and bundle.Verify refuses a
			// manifest that does not before any run starts; this is the second lock, for a
			// bundle that reached the host by another road.
			s.findings = append(s.findings, findings.Finding{Severity: findings.Rejection, Rule: findings.RulePushFailed,
				Object: node.Name, Step: findings.StepPush, Message: "the bundle's manifest names no artifact for node " + node.Name})
			continue
		}
		futures[i] = workflow.ExecuteActivity(workflow.WithActivityOptions(ctx, PushOptions(node, plan)),
			wire.ActPushConfig, wire.PushInput{
				Node:     node.Name,
				MgmtIPv4: addr[node.Name],
				TwinDir:  twinDir,
				Artifact: node.Artifact.File,
				Checksum: node.Artifact.Checksum,
				Push:     node.Push,
			})
	}

	var pushed []wire.PushResult
	for i, f := range futures {
		if f == nil {
			continue
		}
		var r wire.PushResult
		err := f.Get(ctx, &r)
		switch {
		case err == nil:
			// The device's diff stays in this activity's result in the run's history, and
			// enters no other input or result.
			r.Diff = ""
			pushed = append(pushed, r)
		case temporal.IsCanceledError(err):
			s.cancelled = true
		default:
			f := failureFinding(err, findings.StepPush, findings.RulePushFailed, plan[i].Name)
			if !carriesFinding(err) {
				// A failure the activity never worded, a heartbeat or schedule-to-start
				// timeout in Temporal's text or M2's, names the node alone. Every push.failed
				// names what the node was taking, so the plan supplies it.
				f.Message = fmt.Sprintf("the push of artifact %s (checksum %s) to %s failed: %s",
					planArtifactName(plan[i]), plan[i].Artifact.Checksum, plan[i].Name, f.Message)
			}
			s.findings = append(s.findings, f)
		}
	}
	if ctx.Err() != nil {
		s.cancelled = true
	}
	if !s.cancelled && len(s.findings) == 0 {
		return pushed, nil
	}
	took := pushedNodes(pushed)
	for i := range s.findings {
		s.findings[i].Message += "; " + took
	}
	return nil, s
}

// carriesFinding reports whether an activity's failure carries the finding the activity
// worded, as failureFinding reads it: every failure PushConfig returns does, and a timeout
// the service raised does not.
func carriesFinding(err error) bool {
	var appErr *temporal.ApplicationError
	var f findings.Finding
	return errors.As(err, &appErr) && appErr.HasDetails() && appErr.Details(&f) == nil && f.Rule != ""
}

// planArtifactName is the node's artifact's name as the manifest's file gives it: the
// compiler writes configs/<node>.<artifact_name>, as the push reads it.
func planArtifactName(node wire.NodePlan) string {
	return strings.TrimPrefix(path.Base(node.Artifact.File), node.Name+".")
}

// pushedNodes names the nodes that took their configuration, and how long each took.
func pushedNodes(pushed []wire.PushResult) string {
	if len(pushed) == 0 {
		return "no node was pushed"
	}
	parts := make([]string, len(pushed))
	for i, r := range pushed {
		parts[i] = fmt.Sprintf("%s in %.1fs", r.Node, r.PushedInS)
	}
	return "pushed: " + strings.Join(parts, ", ")
}

// stopped is how a run that may have touched the host stopped short of ready: at which
// step, whether by cancellation, and the findings of the failure.
type stopped struct {
	step      string
	cancelled bool
	findings  findings.List
}

// stopAt reports err from step. A cancellation carries no finding of its own (the document
// adds run.cancelled); anything else is reported under the finding its activity gave or,
// failing that, the step's own rule.
func stopAt(ctx workflow.Context, step, object string, err error) *stopped {
	s := &stopped{step: step, cancelled: ctx.Err() != nil}
	if temporal.IsCanceledError(err) {
		s.cancelled = true
		return s
	}
	s.findings = findings.List{failureFinding(err, step, stepRule(step), object)}
	return s
}

// stepRule is the rule a failure at a step that touches the host is reported under when
// its activity gave no finding.
func stepRule(step string) string {
	switch step {
	case findings.StepStage:
		return findings.RuleStageFailed
	case findings.StepDeploy:
		return findings.RuleDeployFailed
	case findings.StepReadiness:
		return findings.RuleReadinessTimeout
	case findings.StepRecord:
		return findings.RuleRecordFailed
	case findings.StepPush:
		return findings.RulePushFailed
	}
	return findings.RuleOperationFailed
}

// untouched ends a run stopped at or before the host check. Nothing on the host was
// touched, so there is nothing to clean up: a cancellation is cancelled (exit 2), and a
// failure is a step that could not run, error (exit 2). Refusals never arrive here; they
// are findings in a result.
func untouched(ctx workflow.Context, res ProvisionResult, step string, err error) ProvisionResult {
	res.Step = step
	if ctx.Err() != nil || temporal.IsCanceledError(err) {
		res.Outcome = OutcomeCancelled
		return res
	}
	res.Outcome = OutcomeError
	res.Findings = append(res.Findings, failureFinding(err, step, findings.RuleOperationFailed, step))
	return res
}

// cleanUp ends a run that stopped after the host check cleared: teardown, then unstage,
// each awaited, on a context the cancellation does not reach, so a cancelled run still
// leaves the host as it found it. WaitForCancellation on every
// host-bound activity means a cancelled step has stopped before the teardown begins.
// Teardown is budgeted by the plan's largest destroy_timeout_s (Constitution II).
func cleanUp(ctx workflow.Context, res ProvisionResult, plan wire.CheckHostResult, s *stopped) ProvisionResult {
	res.Step = s.step
	res.Outcome = OutcomeFailed
	if s.cancelled {
		res.Outcome = OutcomeCancelled
	}
	res.Findings = append(res.Findings, s.findings...)
	res.Cleanup = CleanupResult{}

	uninterrupted, _ := workflow.NewDisconnectedContext(ctx)
	teardown(uninterrupted, MaxDestroyTimeoutS(plan.Nodes), &res.Cleanup, &res.Findings)
	unstage(uninterrupted, res.TwinDir, &res.Cleanup, &res.Findings)
	return res
}

// execute schedules one activity by name under opts and waits for its result.
func execute(ctx workflow.Context, opts workflow.ActivityOptions, name string, out any, in ...any) error {
	return workflow.ExecuteActivity(workflow.WithActivityOptions(ctx, opts), name, in...).Get(ctx, out)
}

// rejected ends the run at step with the refusal already in its findings. Nothing on the
// host was touched, so there is nothing to clean up.
func rejected(res ProvisionResult, step string) ProvisionResult {
	res.Outcome = OutcomeRejected
	res.Step = step
	return res
}

// awaitPushScheme and awaitPushPort are the push transport readiness waits for, for a node
// whose package asks and whose push declares an address; empty and zero otherwise, which is
// what every node planned before D-029 carries.
func awaitPushScheme(n wire.NodePlan) string {
	if !n.AwaitPushTransport {
		return ""
	}
	return n.Push.Scheme
}

func awaitPushPort(n wire.NodePlan) int {
	if !n.AwaitPushTransport {
		return 0
	}
	return n.Push.Port
}
