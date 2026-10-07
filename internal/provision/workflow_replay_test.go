package provision

import (
	"io"
	"log/slog"
	"path/filepath"
	"slices"
	"testing"

	"go.temporal.io/sdk/interceptor"
	tlog "go.temporal.io/sdk/log"
	"go.temporal.io/sdk/worker"
	"go.temporal.io/sdk/workflow"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// replayProvision replays a provisioning run's history, recorded from the dev server, through
// the SDK's own event handlers, and returns the result the workflow code reaches from it.
// Replay fails when the code would issue different commands than the recorded run did.
//
// These tests exist where the testsuite departs from the service. The testsuite settles a
// cancelled activity at once, whatever WaitForCancellation says; the service lets a started
// activity finish, and one that does not see the cancellation hands the workflow its result
// with no error. Each history was recorded by a scratch program against the dev server: the
// real Provision, fake activities, the activity under test asking for its own run's cancellation
// and completing two seconds later without heartbeating. The worker's sticky queue name had
// the host's name in it, replaced by r11e-worker; replay does not read it. The follow and stop
// histories were recorded the same way, from intent with BundleID set, and the host's name
// replaced by t063-worker. The push histories were
// recorded the same way, one node, from intent with BundleID set, and the host's name replaced
// by t032-worker.
//
// The four histories recorded before M5 carry no push version marker: they replay at
// DefaultVersion, which skips the push step, and stand unchanged.
func replayProvision(t *testing.T, history string) ProvisionResult {
	t.Helper()
	capture := &resultCapture{}
	r, err := worker.NewWorkflowReplayerWithOptions(worker.WorkflowReplayerOptions{
		Interceptors: []interceptor.WorkerInterceptor{capture},
	})
	if err != nil {
		t.Fatal(err)
	}
	r.RegisterWorkflow(Provision)
	quiet := tlog.NewStructuredLogger(slog.New(slog.NewTextHandler(io.Discard, nil)))
	if err := r.ReplayWorkflowHistoryFromJSONFile(quiet, filepath.Join("testdata", history)); err != nil {
		t.Fatalf("replaying %s: %v", history, err)
	}
	if capture.result == nil {
		t.Fatalf("replaying %s: Provision returned no result (error %v)", history, capture.err)
	}
	return *capture.result
}

// replayStep replays a step run's history, recorded from the dev server during live
// steps, and returns the result Step reaches from it. Unlike the provisioning histories above,
// these are real runs on a real twin:
// the worker's identity and sticky queue named the host, and its activity inputs the state
// root, so both were replaced (step-worker, /var/lib/fylgja), and each push result's device
// diff was replaced by a note of its length, since the diff's one home is the run's own
// history on the workflow service. Replay reads the commands, not those values.
func replayStep(t *testing.T, history string) StepResult {
	t.Helper()
	capture := &resultCapture{}
	r, err := worker.NewWorkflowReplayerWithOptions(worker.WorkflowReplayerOptions{
		Interceptors: []interceptor.WorkerInterceptor{capture},
	})
	if err != nil {
		t.Fatal(err)
	}
	r.RegisterWorkflow(Step)
	quiet := tlog.NewStructuredLogger(slog.New(slog.NewTextHandler(io.Discard, nil)))
	if err := r.ReplayWorkflowHistoryFromJSONFile(quiet, filepath.Join("testdata", history)); err != nil {
		t.Fatalf("replaying %s: %v", history, err)
	}
	if capture.step == nil {
		t.Fatalf("replaying %s: Step returned no result (error %v)", history, capture.err)
	}
	return *capture.step
}

// resultCapture keeps what Provision or Step returns during a replay. The replayer's public
// interface does not hand the result back.
type resultCapture struct {
	interceptor.WorkerInterceptorBase
	result *ProvisionResult
	step   *StepResult
	err    error
}

func (c *resultCapture) InterceptWorkflow(_ workflow.Context, next interceptor.WorkflowInboundInterceptor) interceptor.WorkflowInboundInterceptor {
	return &captureInbound{WorkflowInboundInterceptorBase: interceptor.WorkflowInboundInterceptorBase{Next: next}, capture: c}
}

type captureInbound struct {
	interceptor.WorkflowInboundInterceptorBase
	capture *resultCapture
}

func (i *captureInbound) ExecuteWorkflow(ctx workflow.Context, in *interceptor.ExecuteWorkflowInput) (any, error) {
	out, err := i.Next.ExecuteWorkflow(ctx, in)
	switch res := out.(type) {
	case ProvisionResult:
		i.capture.result = &res
	case StepResult:
		i.capture.step = &res
	}
	i.capture.err = err
	return out, err
}

// A cancellation that arrives while the record step runs: RecordTwin completes after it
// (events 30, 36). The run is still cancelled, teardown and unstage then run, and it exits 3;
// without the run's check of its context after the record, it ended ready, exit 0, with
// nothing cleaned up.
func TestReplayCancelDuringRecordCleansUp(t *testing.T) {
	res := replayProvision(t, "cancel-during-record.history.json")

	if res.Outcome != OutcomeCancelled || res.Step != findings.StepRecord {
		t.Errorf("outcome %q at %q, want cancelled at %q", res.Outcome, res.Step, findings.StepRecord)
	}
	if res.Twin != nil {
		t.Errorf("a cancelled run reported a twin: %+v", res.Twin)
	}
	if res.Cleanup.Teardown != CleanupDone || res.Cleanup.Unstage != CleanupDone || len(res.Cleanup.Remaining) != 0 {
		t.Errorf("cleanup %+v, want teardown and unstage done, nothing remaining", res.Cleanup)
	}
	doc := ProvisionDocument(findings.OpTwinProvision, &findings.Subject{RunID: "run-1"}, res)
	if !carries(doc.Findings, findings.RuleRunCancelled, findings.StepRecord) {
		t.Errorf("findings %+v, want run.cancelled at record", doc.Findings)
	}
	if code := doc.Status.ExitCode(); code != findings.ExitFailed {
		t.Errorf("exit %d, want %d", code, findings.ExitFailed)
	}
}

// A cancellation that arrives while the host check runs: CheckHost completes after it with a
// clear plan (events 6, 12). Nothing on the host was touched, so the run ends cancelled at the
// host check with cleanup skipped, exit 2; without the check it went on to a teardown and
// unstage that found nothing and exited 3 (contracts/cli.md, run.cancelled).
func TestReplayCancelDuringHostCheckTouchesNothing(t *testing.T) {
	res := replayProvision(t, "cancel-during-host-check.history.json")

	if res.Outcome != OutcomeCancelled || res.Step != findings.StepHostCheck {
		t.Errorf("outcome %q at %q, want cancelled at %q", res.Outcome, res.Step, findings.StepHostCheck)
	}
	if res.Cleanup.Teardown != CleanupSkipped || res.Cleanup.Unstage != CleanupSkipped {
		t.Errorf("cleanup %+v, want both skipped", res.Cleanup)
	}
	doc := ProvisionDocument(findings.OpTwinProvision, &findings.Subject{RunID: "run-1"}, res)
	if !carries(doc.Findings, findings.RuleRunCancelled, findings.StepHostCheck) {
		t.Errorf("findings %+v, want run.cancelled at host_check", doc.Findings)
	}
	if code := doc.Status.ExitCode(); code != findings.ExitError {
		t.Errorf("exit %d, want %d", code, findings.ExitError)
	}
}

// A cancellation that arrives while the follow step's StartFollowing runs: it completes after
// it, having created the Schedule (events 36, 42). The run stops the following it began, then
// tears down and unstages (events 46, 52, 58), so it leaves no Schedule checking a twin that is
// gone. Without WaitForCancellation on FollowOptions the future settled at once, DestroyLab was
// scheduled at event 41 and the run ended before the Schedule was created.
func TestReplayCancelDuringFollowStopsTheFollowing(t *testing.T) {
	res := replayProvision(t, "cancel-during-follow.history.json")

	if res.Outcome != OutcomeCancelled || res.Step != findings.StepFollow {
		t.Errorf("outcome %q at %q, want cancelled at %q", res.Outcome, res.Step, findings.StepFollow)
	}
	if res.Twin != nil || res.Following != nil {
		t.Errorf("a cancelled run reported a twin %+v or a following %+v", res.Twin, res.Following)
	}
	if res.Cleanup.Teardown != CleanupDone || res.Cleanup.Unstage != CleanupDone || len(res.Cleanup.Remaining) != 0 {
		t.Errorf("cleanup %+v, want teardown and unstage done, nothing remaining", res.Cleanup)
	}
	if carries(res.Findings, findings.RuleFollowStopFailed, findings.StepFollow) {
		t.Errorf("findings %+v: the stop succeeded", res.Findings)
	}
	doc := ProvisionDocument(findings.OpTwinCreate, &findings.Subject{RunID: "run-1"}, res)
	if !carries(doc.Findings, findings.RuleRunCancelled, findings.StepFollow) {
		t.Errorf("findings %+v, want run.cancelled at follow", doc.Findings)
	}
	if code := doc.Status.ExitCode(); code != findings.ExitFailed {
		t.Errorf("exit %d, want %d", code, findings.ExitFailed)
	}
}

// A cancellation that arrives while the stop step's StopFollowing runs: it completes after it,
// having deleted the Schedule (events 12, 18). The run ends cancelled with the host untouched,
// and its result names the following it stopped, so the CLI says so. Without
// WaitForCancellation on FollowOptions the run ended at event 17, before the delete, with
// FollowingStopped nil (contracts/cli.md step 5a).
func TestReplayCancelDuringStopFollowingNamesTheStop(t *testing.T) {
	res := replayProvision(t, "cancel-during-stop-following.history.json")

	if res.Outcome != OutcomeCancelled || res.Step != findings.StepFollow {
		t.Errorf("outcome %q at %q, want cancelled at %q", res.Outcome, res.Step, findings.StepFollow)
	}
	if res.FollowingStopped == nil || !res.FollowingStopped.Deleted || res.FollowingStopped.Branch != "fylgja-fixture" {
		t.Errorf("following stopped %+v, want deleted, branch fylgja-fixture", res.FollowingStopped)
	}
	if res.Cleanup.Teardown != CleanupSkipped || res.Cleanup.Unstage != CleanupSkipped {
		t.Errorf("cleanup %+v, want both skipped", res.Cleanup)
	}
	doc := ProvisionDocument(findings.OpTwinCreate, &findings.Subject{RunID: "run-1"}, res)
	if !carries(doc.Findings, findings.RuleRunCancelled, findings.StepFollow) {
		t.Errorf("findings %+v, want run.cancelled at follow", doc.Findings)
	}
	// The stop step runs after the host check cleared, so M2's pre-host-check wording would
	// contradict the step it names.
	const want = "run run-1 was cancelled at step follow, after the host check cleared and before anything was staged; " +
		"nothing on the host was touched"
	for _, f := range doc.Findings {
		if f.Rule == findings.RuleRunCancelled && f.Message != want {
			t.Errorf("run.cancelled message %q, want %q", f.Message, want)
		}
	}
	if code := doc.Status.ExitCode(); code != findings.ExitError {
		t.Errorf("exit %d, want %d", code, findings.ExitError)
	}
}

// A cancellation that reaches the push: PushConfig heartbeats, sees it, and returns cancelled
// (events 32, 38). With WaitForCancellation the run waits for that, then tears down and
// unstages (events 42, 48): cancelled at step push, cleanup done, exit 3.
func TestReplayCancelDuringPushCleansUp(t *testing.T) {
	res := replayProvision(t, "cancel-during-push.history.json")
	cancelledAtPushWithCleanup(t, res)
}

// A push that finishes after its run's cancellation: PushConfig never heartbeats after the
// request and completes with a result (events 32, 38), as a push whose request was in flight
// does. The run is still cancelled at step push and cleans up; it never records the twin
// (the run checks ctx.Err() after the step). The SDK testsuite settles a cancelled activity
// at once whatever WaitForCancellation says, so this history is the only tier-1 witness.
func TestReplayPushAfterCancelStillCancels(t *testing.T) {
	res := replayProvision(t, "push-after-cancel.history.json")
	cancelledAtPushWithCleanup(t, res)
}

func cancelledAtPushWithCleanup(t *testing.T, res ProvisionResult) {
	t.Helper()
	if res.Outcome != OutcomeCancelled || res.Step != findings.StepPush {
		t.Errorf("outcome %q at %q, want cancelled at %q", res.Outcome, res.Step, findings.StepPush)
	}
	if res.Twin != nil {
		t.Errorf("a cancelled run reported a twin: %+v", res.Twin)
	}
	if res.Cleanup.Teardown != CleanupDone || res.Cleanup.Unstage != CleanupDone || len(res.Cleanup.Remaining) != 0 {
		t.Errorf("cleanup %+v, want teardown and unstage done, nothing remaining", res.Cleanup)
	}
	doc := ProvisionDocument(findings.OpTwinCreate, &findings.Subject{RunID: "run-1"}, res)
	if !carries(doc.Findings, findings.RuleRunCancelled, findings.StepPush) {
		t.Errorf("findings %+v, want run.cancelled at push", doc.Findings)
	}
	if code := doc.Status.ExitCode(); code != findings.ExitFailed {
		t.Errorf("exit %d, want %d", code, findings.ExitFailed)
	}
}

// A replace one node refused: the step from waypoint /3 to /4 of a mixed series, where /4
// names s1:ethernet-1/99, which SR Linux refuses at its commit, and disables e1:Ethernet2/1,
// which EOS takes (run 01a0fcb8-369b-763b-b760-ad7a970e39b8). Both pushes
// are scheduled together (events 29, 30); e1's completes with its diff (32) and s1's fails
// push.refused (37); the record is written after both (41, 43). The run ends diverged at
// phase push, e1 landed and s1 refused, and the diff the push returned enters no result.
func TestReplayDivergedStepRecordsEachPush(t *testing.T) {
	res := replayStep(t, "step-diverged.history.json")
	noWaitInAnM11History(t, res)

	if res.Outcome != StepDiverged || res.Phase != findings.StepPush || res.Step != findings.StepPush {
		t.Errorf("outcome %q, phase %q, step %q; want diverged at push", res.Outcome, res.Phase, res.Step)
	}
	want := map[string]string{"e1": wire.PushLanded, "s1": wire.PushRefused}
	if len(res.PushPlan) != len(want) {
		t.Errorf("push plan %+v, want e1 and s1", res.PushPlan)
	}
	for _, p := range res.PushPlan {
		if p.Outcome != want[p.Node] {
			t.Errorf("push of %s %q, want %q", p.Node, p.Outcome, want[p.Node])
		}
	}
	if len(res.Pushed) != 1 || res.Pushed[0].Node != "e1" || res.Pushed[0].Diff != "" {
		t.Errorf("pushed %+v, want e1 alone with its diff stripped", res.Pushed)
	}
	if res.Record == nil || res.Record.State != wire.StateDiverged {
		t.Errorf("record %+v, want one written diverged", res.Record)
	}
	if !carries(res.Findings, findings.RulePushRefused, findings.StepPush) ||
		!carries(res.Findings, findings.RuleStepDiverged, findings.StepPush) {
		t.Errorf("findings %+v, want push.refused and step.diverged at push", res.Findings)
	}
	doc := StepDocument(&findings.Subject{RunID: "run-1"}, StepInput{}, res)
	if doc.Status != findings.StatusDiverged || doc.Status.ExitCode() != findings.ExitUnclean {
		t.Errorf("status %q exit %d, want diverged, exit %d", doc.Status, doc.Status.ExitCode(), findings.ExitUnclean)
	}
}

// noWaitInAnM11History holds an M11 step history to what it recorded: it carries no version
// marker, so the run replays at DefaultVersion and never schedules the wait, which a replay
// would refuse as a command the history lacks.
func noWaitInAnM11History(t *testing.T, res StepResult) {
	t.Helper()
	if res.Wait != nil || carries(res.Findings, findings.RuleVerifyWaitUnsettled, findings.StepObserve) {
		t.Errorf("wait %+v, findings %v: an M11 history replays with no wait", res.Wait, res.Findings)
	}
}

// A destroy during a step: the step from waypoint /1 to /3, which restarts e1, cancelled
// by twin destroy while readiness waited for e1 (run
// 01a0fcbc-67e9-7902-98fb-1ef1f4ed996e). The cancellation is requested at event 36,
// readiness is cancelled (42), and the record is still written, on a context the
// cancellation does not reach (46, 48). The run ends cancelled at phase readiness, beside
// step.diverged, with nothing pushed and nothing torn down.
func TestReplayCancelledStepRecordsDiverged(t *testing.T) {
	res := replayStep(t, "step-cancelled.history.json")
	noWaitInAnM11History(t, res)

	if res.Outcome != OutcomeCancelled || res.Phase != findings.StepReadiness || res.Step != findings.StepReadiness {
		t.Errorf("outcome %q, phase %q, step %q; want cancelled at readiness", res.Outcome, res.Phase, res.Step)
	}
	if res.Record == nil || res.Record.State != wire.StateDiverged || res.Record.Step == nil ||
		res.Record.Step.Phase == nil || *res.Record.Step.Phase != findings.StepReadiness {
		t.Errorf("record %+v, want one written diverged at readiness", res.Record)
	}
	for _, p := range res.PushPlan {
		if p.Outcome != wire.PushNotAttempted {
			t.Errorf("push of %s %q, want not_attempted: nothing is pushed until every node is ready", p.Node, p.Outcome)
		}
	}
	if len(res.Pushed) != 0 {
		t.Errorf("pushed %+v, want none", res.Pushed)
	}
	if !carries(res.Findings, findings.RuleRunCancelled, findings.StepReadiness) ||
		!carries(res.Findings, findings.RuleStepDiverged, findings.StepReadiness) {
		t.Errorf("findings %+v, want run.cancelled beside step.diverged at readiness", res.Findings)
	}
	doc := StepDocument(&findings.Subject{RunID: "run-1"}, StepInput{}, res)
	if doc.Status != findings.StatusDiverged || doc.Status.ExitCode() != findings.ExitUnclean {
		t.Errorf("status %q exit %d, want diverged, exit %d", doc.Status, doc.Status.ExitCode(), findings.ExitUnclean)
	}
}

// A destroy during the step's wait (M12, run
// 01a1035f-f65c-76cb-9800-94af24068530): the step from waypoint /1 to /2 of a mixed series,
// which restarts e1, with e2:Ethernet1 shut by hand so the twin could not conform. Both pushes
// landed and the record was written (event 55); the verify marker (59) and VerifyTwin (61)
// followed, and twin destroy's cancellation arrived during the wait (62, 66). The activity,
// started under WaitForCancellation, answered its wait cancelled after two reads (68), and the
// run ended as its record says: stepped, exit 0, with verify.wait.unsettled and no
// run.cancelled. The SDK testsuite settles a cancelled activity at once,
// so only a history from the service holds the activity's own answer.
func TestReplayStepWaitCancelledEndsStepped(t *testing.T) {
	res := replayStep(t, "step-wait-cancelled.history.json")

	if res.Outcome != StepStepped || res.Phase != "" {
		t.Errorf("outcome %q, phase %q; want stepped, with no phase", res.Outcome, res.Phase)
	}
	if res.Record == nil || res.Record.State != wire.StateReady {
		t.Errorf("record %+v, want one written ready", res.Record)
	}
	for _, p := range res.PushPlan {
		if p.Outcome != wire.PushLanded {
			t.Errorf("push of %s %q, want landed", p.Node, p.Outcome)
		}
	}
	w := res.Wait
	if w == nil || w.Outcome != wire.WaitCancelled || w.BudgetS != 120 || w.Reads != 2 || w.From != res.EndedAt {
		t.Fatalf("wait %+v, want cancelled after 2 reads of a 120s budget, from the record's time %s", w, res.EndedAt)
	}
	var failing []string
	for _, f := range w.Failing {
		failing = append(failing, f.Rule+" "+f.Object)
	}
	if want := []string{"verify.neighbor e1:Ethernet2/1", "verify.port.enabled e2:Ethernet1"}; !slices.Equal(failing, want) {
		t.Errorf("still failing %v, want %v", failing, want)
	}
	if !carries(res.Findings, findings.RuleVerifyWaitUnsettled, findings.StepObserve) {
		t.Errorf("findings %+v, want verify.wait.unsettled at observe", res.Findings)
	}
	for _, f := range res.Findings {
		if f.Rule == findings.RuleRunCancelled || f.Rule == findings.RuleStepDiverged {
			t.Errorf("finding %s at %s: a cancellation during the wait leaves the step as its record says", f.Rule, f.Step)
		}
	}
	doc := StepDocument(&findings.Subject{RunID: "run-1"}, StepInput{WaitS: 120}, res)
	if doc.Status != findings.StatusOK || doc.Status.ExitCode() != findings.ExitOK {
		t.Errorf("status %q exit %d, want ok, exit %d", doc.Status, doc.Status.ExitCode(), findings.ExitOK)
	}
	if doc.Step == nil || doc.Step.Wait == nil || doc.Step.Wait.Outcome != wire.WaitCancelled {
		t.Errorf("document's step block %+v, want its wait cancelled", doc.Step)
	}
}
