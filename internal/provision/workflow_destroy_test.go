package provision

import (
	"context"
	"errors"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/mock"
	"go.temporal.io/sdk/activity"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// Destroy succeeds in every combination of lab and twin directory present or absent,
// planning the teardown first and removing what is there.
func TestDestroyEveryState(t *testing.T) {
	const twinDir = "twin directory /state/twin"
	for _, c := range []struct {
		name              string
		lab, dir          bool
		teardown, unstage string
		removed           []string
	}{
		{"lab and twin directory", true, true, CleanupDone, CleanupDone, []string{"lab fylgja (3 containers)", twinDir}},
		{"an orphan lab", true, false, CleanupDone, CleanupNothing, []string{"lab fylgja (3 containers)"}},
		{"a twin directory without a lab", false, true, CleanupNothing, CleanupDone, []string{twinDir}},
		{"nothing", false, false, CleanupNothing, CleanupNothing, nil},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := newHarness(t)
			basis := wire.BasisNone
			if c.lab {
				basis = wire.BasisInspect
			}
			containers := 0
			if c.lab {
				containers = 3
			}
			h.env.OnActivity(wire.ActPlanTeardown, mock.Anything).Return(wire.PlanTeardownResult{DestroyTimeoutS: 60, Basis: basis}, nil)
			h.env.OnActivity(wire.ActDestroyLab, mock.Anything, mock.Anything).Return(wire.DestroyLabResult{Removed: c.lab, Containers: containers}, nil)
			h.env.OnActivity(wire.ActUnstageTwin, mock.Anything).Return(wire.UnstageResult{Removed: c.dir, Path: "/state/twin"}, nil)

			res := h.runDestroy()

			if want := []string{wire.ActPlanTeardown, wire.ActDestroyLab, wire.ActUnstageTwin}; !slices.Equal(h.calls(), want) {
				t.Errorf("activities = %v, want %v", h.calls(), want)
			}
			if res.Cleanup.Teardown != c.teardown || res.Cleanup.Unstage != c.unstage {
				t.Errorf("teardown %q, unstage %q; want %q, %q", res.Cleanup.Teardown, res.Cleanup.Unstage, c.teardown, c.unstage)
			}
			if !slices.Equal(res.Cleanup.Removed, c.removed) || len(res.Cleanup.Remaining) != 0 {
				t.Errorf("removed %v, remaining %v; want removed %v and nothing remaining", res.Cleanup.Removed, res.Cleanup.Remaining, c.removed)
			}
			doc := DestroyDocument(&findings.Subject{RunID: "run-d"}, res, FollowStop{})
			if doc.Status != findings.StatusOK {
				t.Errorf("status %q, want ok", doc.Status)
			}
			mustValidateM2(t, doc, c.name)
		})
	}
}

// The teardown is budgeted by the plan: the packages' destroy_timeout_s, or the stated
// default when the plan found none (Constitution II).
func TestDestroyBudgetFromPlan(t *testing.T) {
	for _, c := range []struct {
		name    string
		planned int
		want    time.Duration
	}{
		{"from the packages", 120, 120 * time.Second},
		{"no package covered anything", 0, 60 * time.Second},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := newHarness(t)
			var mu sync.Mutex
			var scheduled activity.Info
			var input wire.DestroyLabInput
			h.env.OnActivity(wire.ActPlanTeardown, mock.Anything).Return(wire.PlanTeardownResult{DestroyTimeoutS: c.planned, Basis: wire.BasisInspect}, nil)
			h.env.OnActivity(wire.ActDestroyLab, mock.Anything, mock.Anything).Return(
				func(ctx context.Context, in wire.DestroyLabInput) (wire.DestroyLabResult, error) {
					mu.Lock()
					defer mu.Unlock()
					scheduled, input = activity.GetInfo(ctx), in
					return wire.DestroyLabResult{Removed: true, Containers: 3}, nil
				})
			h.env.OnActivity(wire.ActUnstageTwin, mock.Anything).Return(wire.UnstageResult{Removed: true, Path: "/state/twin"}, nil)

			h.runDestroy()

			mu.Lock()
			defer mu.Unlock()
			if scheduled.StartToCloseTimeout != c.want {
				t.Errorf("DestroyLab start-to-close = %v, want %v", scheduled.StartToCloseTimeout, c.want)
			}
			if scheduled.HeartbeatTimeout != HeartbeatTimeout {
				t.Errorf("DestroyLab heartbeat timeout = %v, want %v", scheduled.HeartbeatTimeout, HeartbeatTimeout)
			}
			if input.DestroyTimeoutS != c.planned {
				t.Errorf("DestroyLab was told its budget is %ds, want %ds", input.DestroyTimeoutS, c.planned)
			}
		})
	}
}

// A teardown that fails leaves the lab in Remaining, reports cleanup.incomplete with the
// clearing command, and the unstage still runs: exit 4.
func TestDestroyCleanupIncomplete(t *testing.T) {
	h := newHarness(t)
	h.env.OnActivity(wire.ActPlanTeardown, mock.Anything).Return(wire.PlanTeardownResult{DestroyTimeoutS: 60, Basis: wire.BasisManifest}, nil)
	h.env.OnActivity(wire.ActDestroyLab, mock.Anything, mock.Anything).Return(wire.DestroyLabResult{},
		lab.StepFailure(findings.StepTeardown, findings.RuleCleanupIncomplete, "lab fylgja",
			"lab fylgja is still present after clab destroy (exited 0): n1 running; clear it with: clab destroy --name fylgja --cleanup"))
	h.env.OnActivity(wire.ActUnstageTwin, mock.Anything).Return(wire.UnstageResult{Removed: true, Path: "/state/twin"}, nil)

	res := h.runDestroy()

	if !h.ran(wire.ActUnstageTwin) {
		t.Error("the unstage did not run after a failed teardown")
	}
	if res.Cleanup.Teardown != CleanupFailed || res.Cleanup.Unstage != CleanupDone ||
		!slices.Equal(res.Cleanup.Remaining, []string{"lab fylgja"}) {
		t.Errorf("cleanup = %+v, want teardown failed, unstage done, lab fylgja remaining", res.Cleanup)
	}
	if !carries(res.Findings, findings.RuleCleanupIncomplete, findings.StepTeardown) {
		t.Errorf("findings %+v, want cleanup.incomplete at teardown", res.Findings)
	}
	doc := DestroyDocument(&findings.Subject{RunID: "run-d"}, res, FollowStop{})
	if code := doc.Status.ExitCode(); code != findings.ExitUnclean {
		t.Errorf("exit %d, want %d", code, findings.ExitUnclean)
	}
	mustValidateM2(t, doc, "cleanup incomplete")
}

// Destroy honours a cancel request only between the teardown and the unstage: the plan and
// the teardown run where the cancellation does not reach, whether it was
// requested before the run started or while the teardown was running. The unstage is then
// never scheduled, the twin directory is reported as not checked, and the run says to
// destroy again: exit 4.
//
// The cancel during the teardown is requested by the DestroyLab mock itself, as the
// provisioning tests' canceller does: a delayed callback fires on the wall clock while an
// activity runs, so it could not be made to land during the teardown for certain. The
// testsuite queues the request ahead of the mock's result, so the run sees it as the
// teardown returns. The cancel before the run starts is a delayed callback with no delay,
// queued before the run's first task.
func TestDestroyCancelIsHonouredOnlyBetweenTeardownAndUnstage(t *testing.T) {
	const notChecked = "twin directory (not checked: the destroy run was cancelled)"
	for _, c := range []struct {
		name           string
		duringTeardown bool
	}{
		{"requested before the run starts", false},
		{"requested while the teardown runs", true},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := newHarness(t)
			h.env.SetOnActivityCanceledListener(func(info *activity.Info) { h.record("cancelled " + info.ActivityType.Name) })
			var mu sync.Mutex
			var runID string
			h.env.OnActivity(wire.ActPlanTeardown, mock.Anything).Return(wire.PlanTeardownResult{DestroyTimeoutS: 60, Basis: wire.BasisManifest}, nil)
			h.env.OnActivity(wire.ActDestroyLab, mock.Anything, mock.Anything).Return(
				func(ctx context.Context, _ wire.DestroyLabInput) (wire.DestroyLabResult, error) {
					mu.Lock()
					runID = activity.GetInfo(ctx).WorkflowExecution.RunID
					mu.Unlock()
					if c.duringTeardown {
						h.env.CancelWorkflow()
					}
					return wire.DestroyLabResult{Removed: true, Containers: 3}, nil
				})
			h.env.OnActivity(wire.ActUnstageTwin, mock.Anything).Return(wire.UnstageResult{Removed: true, Path: "/state/twin"}, nil)
			if !c.duringTeardown {
				h.env.RegisterDelayedCallback(h.env.CancelWorkflow, 0)
			}

			res := h.runDestroy()

			if want := []string{wire.ActPlanTeardown, wire.ActDestroyLab}; !slices.Equal(h.calls(), want) {
				t.Errorf("activities = %v, want %v: the plan and the teardown to completion, nothing cancelled, no unstage", h.calls(), want)
			}
			if res.Cleanup.Teardown != CleanupDone || res.Cleanup.Unstage != CleanupSkipped {
				t.Errorf("teardown %q, unstage %q; want done, skipped", res.Cleanup.Teardown, res.Cleanup.Unstage)
			}
			if !slices.Equal(res.Cleanup.Removed, []string{"lab fylgja (3 containers)"}) || !slices.Equal(res.Cleanup.Remaining, []string{notChecked}) {
				t.Errorf("removed %v, remaining %v; want the lab removed and %q remaining", res.Cleanup.Removed, res.Cleanup.Remaining, notChecked)
			}

			mu.Lock()
			id := runID
			mu.Unlock()
			var cancelled *findings.Finding
			for i := range res.Findings {
				if res.Findings[i].Rule == findings.RuleRunCancelled {
					cancelled = &res.Findings[i]
				}
			}
			switch {
			case cancelled == nil:
				t.Fatalf("findings %+v, want run.cancelled", res.Findings)
			case id == "" || cancelled.Step != findings.StepUnstage || cancelled.Object != id:
				t.Errorf("run.cancelled at %q naming %q, want at unstage naming run %q", cancelled.Step, cancelled.Object, id)
			case !strings.Contains(cancelled.Message, "fylgja twin destroy"):
				t.Errorf("run.cancelled says %q, want it to say to destroy again", cancelled.Message)
			}
			doc := DestroyDocument(&findings.Subject{RunID: id}, res, FollowStop{})
			if doc.Status != findings.StatusUnclean || doc.Status.ExitCode() != findings.ExitUnclean {
				t.Errorf("status %q (exit %d), want unclean (exit %d)", doc.Status, doc.Status.ExitCode(), findings.ExitUnclean)
			}
			mustValidateM2(t, doc, c.name)
		})
	}
}

// A PlanTeardown that fails outright — not one that answers 0, which TestDestroyBudgetFromPlan
// covers — is retried like any activity, then logged, and the stated default budget stands
// in, so the teardown still runs. Nothing about it reaches the document:
// a run whose teardown and unstage both succeed ends ok.
func TestDestroyPlanFailureTakesTheDefaultBudget(t *testing.T) {
	h := newHarness(t)
	var mu sync.Mutex
	var scheduled activity.Info
	var input wire.DestroyLabInput
	h.env.OnActivity(wire.ActPlanTeardown, mock.Anything).Return(wire.PlanTeardownResult{},
		errors.New("listing the host's containers: the docker daemon did not answer"))
	h.env.OnActivity(wire.ActDestroyLab, mock.Anything, mock.Anything).Return(
		func(ctx context.Context, in wire.DestroyLabInput) (wire.DestroyLabResult, error) {
			mu.Lock()
			defer mu.Unlock()
			scheduled, input = activity.GetInfo(ctx), in
			return wire.DestroyLabResult{Removed: true, Containers: 3}, nil
		})
	h.env.OnActivity(wire.ActUnstageTwin, mock.Anything).Return(wire.UnstageResult{Removed: true, Path: "/state/twin"}, nil)

	res := h.runDestroy()

	want := slices.Concat(slices.Repeat([]string{wire.ActPlanTeardown}, RetryMaximumAttempts), []string{wire.ActDestroyLab, wire.ActUnstageTwin})
	if !slices.Equal(h.calls(), want) {
		t.Errorf("activities = %v, want %v: every plan attempt, then the teardown and the unstage", h.calls(), want)
	}
	mu.Lock()
	defer mu.Unlock()
	if scheduled.StartToCloseTimeout != DefaultDestroyBudget {
		t.Errorf("DestroyLab start-to-close = %v, want the default %v", scheduled.StartToCloseTimeout, DefaultDestroyBudget)
	}
	if input.DestroyTimeoutS != 0 {
		t.Errorf("DestroyLab was told its budget is %ds, want 0: no plan answered", input.DestroyTimeoutS)
	}
	if res.Cleanup.Teardown != CleanupDone || res.Cleanup.Unstage != CleanupDone || len(res.Cleanup.Remaining) != 0 {
		t.Errorf("cleanup = %+v, want teardown and unstage done and nothing remaining", res.Cleanup)
	}
	if len(res.Findings) != 0 {
		t.Errorf("findings %+v, want none: the plan's failure is logged, not reported", res.Findings)
	}
	doc := DestroyDocument(&findings.Subject{RunID: "run-d"}, res, FollowStop{})
	if doc.Status != findings.StatusOK {
		t.Errorf("status %q, want ok", doc.Status)
	}
	mustValidateM2(t, doc, "plan failed")
}
