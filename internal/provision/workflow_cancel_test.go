package provision

import (
	"context"
	"errors"
	"slices"
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/mock"
	"go.temporal.io/sdk/activity"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// canceller cancels the run from inside the step under test, then holds that step's
// activity as a running activity is held: until the cancellation reaches it.
type canceller struct {
	h       *harness
	cancel  sync.Once
	reach   sync.Once
	reached chan struct{}
}

func newCanceller(h *harness) *canceller {
	c := &canceller{h: h, reached: make(chan struct{})}
	h.env.SetOnActivityCanceledListener(func(info *activity.Info) {
		h.record("cancelled " + info.ActivityType.Name)
		c.reach.Do(func() { close(c.reached) })
	})
	return c
}

// block is the body of the blocked step's mock.
func (c *canceller) block(ctx context.Context) error {
	c.cancel.Do(c.h.env.CancelWorkflow)
	select {
	case <-c.reached:
	case <-ctx.Done():
	case <-time.After(5 * time.Second):
		return errors.New("the cancellation never reached the activity")
	}
	return context.Canceled
}

// mock makes the activity of step block until cancelled.
func (c *canceller) mock(step string) {
	env := c.h.env
	switch step {
	case findings.StepRead:
		env.OnActivity(wire.ActReadIntent, mock.Anything, mock.Anything).Return(
			func(ctx context.Context, _ ReadIntentInput) (ReadIntentResult, error) {
				return ReadIntentResult{}, c.block(ctx)
			})
	case findings.StepCompile:
		env.OnActivity(wire.ActCompile, mock.Anything, mock.Anything).Return(
			func(ctx context.Context, _ CompileInput) (CompileResult, error) { return CompileResult{}, c.block(ctx) })
	case findings.StepHostCheck:
		env.OnActivity(wire.ActCheckHost, mock.Anything, mock.Anything).Return(
			func(ctx context.Context, _ wire.CheckHostInput) (wire.CheckHostResult, error) {
				return wire.CheckHostResult{}, c.block(ctx)
			})
	case findings.StepStage:
		env.OnActivity(wire.ActStageBundle, mock.Anything, mock.Anything).Return(
			func(ctx context.Context, _ wire.StageInput) (wire.StageResult, error) {
				return wire.StageResult{}, c.block(ctx)
			})
	case findings.StepDeploy:
		env.OnActivity(wire.ActDeployLab, mock.Anything, mock.Anything).Return(
			func(ctx context.Context, _ wire.DeployInput) (wire.DeployResult, error) {
				return wire.DeployResult{}, c.block(ctx)
			})
	case findings.StepReadiness:
		env.OnActivity(wire.ActAwaitReadiness, mock.Anything, mock.Anything).Return(
			func(ctx context.Context, _ wire.ReadinessInput) (wire.ReadinessResult, error) {
				return wire.ReadinessResult{}, c.block(ctx)
			})
	case findings.StepPush:
		env.OnActivity(wire.ActPushConfig, mock.Anything, mock.Anything).Return(
			func(ctx context.Context, _ wire.PushInput) (wire.PushResult, error) {
				return wire.PushResult{}, c.block(ctx)
			})
	case findings.StepRecord:
		env.OnActivity(wire.ActRecordTwin, mock.Anything, mock.Anything).Return(
			func(ctx context.Context, _ wire.RecordInput) (wire.RecordResult, error) {
				return wire.RecordResult{}, c.block(ctx)
			})
	}
}

// A cancellation at each step. At or before the host check nothing was touched: the run is
// cancelled with cleanup skipped and nothing torn down (exit 2). After it, the cancellation
// reaches the running step, and only then are teardown and unstage scheduled, where the
// cancellation does not reach them, and both run to completion (exit 3).
//
// What this cannot show is the cleanup waiting for the cancelled activity to have stopped:
// the SDK's test suite settles a cancelled activity at once whatever WaitForCancellation
// says. That ordering rests on the option, pinned in
// options_test.go, and on a cancelled run against the real service.
func TestProvisionCancelAtEachStepRunsCleanupToCompletion(t *testing.T) {
	for _, c := range []struct {
		step, activity string
		touched        bool
	}{
		{findings.StepRead, wire.ActReadIntent, false},
		{findings.StepCompile, wire.ActCompile, false},
		{findings.StepHostCheck, wire.ActCheckHost, false},
		{findings.StepStage, wire.ActStageBundle, true},
		{findings.StepDeploy, wire.ActDeployLab, true},
		{findings.StepReadiness, wire.ActAwaitReadiness, true},
		{findings.StepPush, wire.ActPushConfig, true},
		{findings.StepRecord, wire.ActRecordTwin, true},
	} {
		t.Run(c.step, func(t *testing.T) {
			h := newHarness(t)
			newCanceller(h).mock(c.step)
			h.mockHappyPath()
			h.mockCleanup()

			res := h.run(ProvisionInput{Source: wire.SourceIntent, Branch: "fylgja-fixture"})

			if res.Outcome != OutcomeCancelled || res.Step != c.step {
				t.Errorf("outcome %q at %q, want cancelled at %q", res.Outcome, res.Step, c.step)
			}
			calls := h.calls()
			reached := slices.Index(calls, "cancelled "+c.activity)
			if reached < 0 {
				t.Fatalf("the cancellation never reached %s: %v", c.activity, calls)
			}
			doc := ProvisionDocument(findings.OpTwinCreate, &findings.Subject{Branch: "fylgja-fixture", RunID: "run-1"}, res)
			if !carries(doc.Findings, findings.RuleRunCancelled, c.step) {
				t.Errorf("findings %+v, want run.cancelled at %s", doc.Findings, c.step)
			}
			if c.step == findings.StepPush {
				mustValidateM5(t, doc, c.step) // step push is M5's
			} else {
				mustValidateM2(t, doc, c.step)
			}

			if !c.touched {
				if h.ran(wire.ActDestroyLab) || h.ran(wire.ActUnstageTwin) {
					t.Errorf("activities %v tore down a host the run had not touched", calls)
				}
				if res.Cleanup.Teardown != CleanupSkipped || res.Cleanup.Unstage != CleanupSkipped {
					t.Errorf("cleanup %+v, want both skipped", res.Cleanup)
				}
				if code := doc.Status.ExitCode(); code != findings.ExitError {
					t.Errorf("exit %d, want %d", code, findings.ExitError)
				}
				return
			}

			teardown, unstage := slices.Index(calls, wire.ActDestroyLab), slices.Index(calls, wire.ActUnstageTwin)
			if teardown < reached || unstage < teardown {
				t.Errorf("order %v: want the cancellation to reach %s, then teardown, then unstage", calls, c.activity)
			}
			if slices.Contains(calls, "cancelled "+wire.ActDestroyLab) || slices.Contains(calls, "cancelled "+wire.ActUnstageTwin) {
				t.Errorf("the cleanup was itself cancelled: %v", calls)
			}
			if res.Cleanup.Teardown != CleanupDone || res.Cleanup.Unstage != CleanupDone || len(res.Cleanup.Remaining) != 0 {
				t.Errorf("cleanup %+v, want both done and nothing remaining", res.Cleanup)
			}
			if code := doc.Status.ExitCode(); code != findings.ExitFailed {
				t.Errorf("exit %d, want %d", code, findings.ExitFailed)
			}
		})
	}
}
