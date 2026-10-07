package lab

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"go.temporal.io/api/serviceerror"
	"go.temporal.io/sdk/temporal"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// blockingRunner answers inspect with what it is given and holds every other containerlab
// command until its context ends, as a clab the runner kills on cancellation does.
type blockingRunner struct{ inspect []byte }

func (b blockingRunner) Run(ctx context.Context, _ []string, args ...string) ([]byte, []byte, int, error) {
	if len(args) > 1 && args[1] == "inspect" {
		return b.inspect, nil, 0, nil
	}
	<-ctx.Done()
	return nil, nil, -1, ctx.Err()
}

// blockingProber waits for its context to end, as a probe against a silent node does.
type blockingProber struct{}

func (blockingProber) Probe(ctx context.Context, _ string, _ wire.Probe, _ func(string) (string, bool)) error {
	<-ctx.Done()
	return ctx.Err()
}

// A step whose context the SDK ended because a heartbeat did not reach the workflow service
// names that cause under the step's own rule and stays retryable; a cancellation the
// workflow asked for is still a cancellation.
func TestAHostBoundStepNamesALostHeartbeat(t *testing.T) {
	steps := []struct {
		name, step, rule, object string
		run                      func(context.Context, *Activities) error
	}{
		{"deploy", findings.StepDeploy, findings.RuleDeployFailed, "lab fylgja", func(ctx context.Context, a *Activities) error {
			_, err := a.DeployLab(ctx, wire.DeployInput{TwinDir: a.Paths.Twin, Nodes: threeNodePlan()})
			return err
		}},
		{"reconcile", findings.StepReconcile, findings.RuleDeployFailed, "lab fylgja", func(ctx context.Context, a *Activities) error {
			_, err := a.ReconcileLab(ctx, wire.ReconcileInput{TwinDir: a.Paths.Twin, Nodes: threeNodePlan(),
				Plan: wire.ReconcilePlan{Restarted: []string{"n1"}}})
			return err
		}},
		{"readiness", findings.StepReadiness, findings.RuleReadinessTimeout, "n1", func(ctx context.Context, a *Activities) error {
			_, err := a.AwaitReadiness(ctx, wire.ReadinessInput{Node: "n1", MgmtIPv4: "172.20.20.2", Probe: srlinuxProbe(), TimeoutS: 60})
			return err
		}},
		{"teardown", findings.StepTeardown, findings.RuleCleanupIncomplete, "lab fylgja", func(ctx context.Context, a *Activities) error {
			_, err := a.DestroyLab(ctx, wire.DestroyLabInput{DestroyTimeoutS: 60})
			return err
		}},
	}
	causes := []struct {
		name  string
		cause error
		lost  bool
	}{
		// What SDK v1.49.0 cancelled the activity with when its heartbeat could not reach
		// the dev server.
		{"a heartbeat that did not reach the service", serviceerror.NewDeadlineExceeded("context deadline exceeded"), true},
		{"a cancellation the workflow asked for", temporal.NewCanceledError(), false},
		{"a cancellation with no cause", nil, false},
	}
	for _, s := range steps {
		for _, c := range causes {
			t.Run(s.name+"/"+c.name, func(t *testing.T) {
				a := testActivities(t, blockingRunner{inspect: recorded(t, "inspect-three.json")})
				a.Prober = blockingProber{}
				ctx, cancel := context.WithCancelCause(context.Background())
				time.AfterFunc(20*time.Millisecond, func() { cancel(c.cause) })

				err := s.run(ctx, a)

				var appErr *temporal.ApplicationError
				if !c.lost {
					if !errors.Is(err, context.Canceled) || errors.As(err, &appErr) {
						t.Errorf("error %v, want the cancellation itself", err)
					}
					return
				}
				if !errors.As(err, &appErr) || appErr.Type() != HeartbeatLostType {
					t.Fatalf("error %v, want an application error of type %s", err, HeartbeatLostType)
				}
				if appErr.NonRetryable() {
					t.Error("a step cut short by a lost heartbeat is non-retryable; retrying is how a deploy converges")
				}
				var f findings.Finding
				if err := appErr.Details(&f); err != nil {
					t.Fatal(err)
				}
				if f.Rule != s.rule || f.Step != s.step || f.Object != s.object {
					t.Errorf("finding %+v, want %s at %s on %s", f, s.rule, s.step, s.object)
				}
				for _, want := range []string{"heartbeat", "did not reach the workflow service", "context deadline exceeded"} {
					if !strings.Contains(f.Message, want) {
						t.Errorf("message %q does not say %q", f.Message, want)
					}
				}
			})
		}
	}
}
