package provision

import (
	"context"
	"sync/atomic"
	"testing"

	"github.com/stretchr/testify/mock"
	"go.temporal.io/sdk/temporal"

	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// A deploy whose first attempt the service gives up on — the worker died part-way, and no
// heartbeat came — is retried, and the run converges on one ready twin with no cleanup.
// The retry finding the half-made lab and recreating it with --reconfigure is
// DeployLab's own, tested in internal/lab (TestDeployLabPresentLabReconfiguresOnce).
func TestDeployRetryAfterPartialAttemptConverges(t *testing.T) {
	h := newHarness(t)
	var attempts atomic.Int32
	h.env.OnActivity(wire.ActDeployLab, mock.Anything, mock.Anything).Return(
		func(_ context.Context, _ wire.DeployInput) (wire.DeployResult, error) {
			if attempts.Add(1) == 1 {
				return wire.DeployResult{}, temporal.NewHeartbeatTimeoutError()
			}
			return wire.DeployResult{Nodes: labNodes(h.plan.Nodes)}, nil
		})
	h.mockHappyPath()

	res := h.run(ProvisionInput{Source: wire.SourceIntent, Branch: "fylgja-fixture"})

	if n := attempts.Load(); n != 2 {
		t.Errorf("deploy attempts = %d, want 2", n)
	}
	if res.Outcome != OutcomeReady {
		t.Fatalf("outcome %q with %+v, want ready", res.Outcome, res.Findings)
	}
	if res.Twin == nil || len(res.Twin.Nodes) != 3 {
		t.Errorf("twin = %+v, want one lab of three nodes", res.Twin)
	}
	if h.ran(wire.ActDestroyLab) || h.ran(wire.ActUnstageTwin) {
		t.Errorf("activities %v cleaned up a run that converged", h.calls())
	}
}
