package provision

import (
	"strings"
	"testing"

	"github.com/stretchr/testify/mock"
	"go.temporal.io/sdk/temporal"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// A heartbeat timeout reported by the service names what it says about the worker, rather
// than "activity Heartbeat timeout".
func TestFailureFindingNamesAHeartbeatTimeout(t *testing.T) {
	f := failureFinding(temporal.NewHeartbeatTimeoutError(), findings.StepDeploy, findings.RuleDeployFailed, "lab fylgja")
	if f.Rule != findings.RuleDeployFailed || f.Step != findings.StepDeploy || f.Object != "lab fylgja" {
		t.Errorf("finding %+v, want deploy.failed at deploy on lab fylgja", f)
	}
	for _, want := range []string{"heartbeat", "presumed lost", "too loaded"} {
		if !strings.Contains(f.Message, want) {
			t.Errorf("message %q does not say %q", f.Message, want)
		}
	}
}

// A deploy cut short by a lost heartbeat is retried, and when every attempt is cut short
// the run fails under deploy.failed with the cause named, and cleans up.
func TestADeployCutShortByALostHeartbeatIsRetriedThenNamed(t *testing.T) {
	const named = "clab deploy was cut short: a heartbeat from this worker did not reach the workflow service (context deadline exceeded)"
	h := newHarness(t)
	h.env.OnActivity(wire.ActDeployLab, mock.Anything, mock.Anything).Return(wire.DeployResult{},
		temporal.NewApplicationError(named, lab.HeartbeatLostType, findings.Finding{
			Severity: findings.Rejection, Rule: findings.RuleDeployFailed, Object: "lab fylgja", Message: named, Step: findings.StepDeploy,
		}))
	h.mockHappyPath()
	h.mockCleanup()

	res := h.run(ProvisionInput{Source: wire.SourceIntent, Branch: "fylgja-fixture"})

	attempts := 0
	for _, c := range h.calls() {
		if c == wire.ActDeployLab {
			attempts++
		}
	}
	if attempts != RetryMaximumAttempts {
		t.Errorf("DeployLab ran %d times, want %d: a lost heartbeat is retried", attempts, RetryMaximumAttempts)
	}
	if res.Outcome != OutcomeFailed || res.Step != findings.StepDeploy {
		t.Fatalf("outcome %q at %q, want failed at deploy", res.Outcome, res.Step)
	}
	found := false
	for _, f := range res.Findings {
		if f.Rule == findings.RuleDeployFailed && f.Message == named {
			found = true
		}
	}
	if !found {
		t.Errorf("findings %+v, want deploy.failed with the named cause", res.Findings)
	}
	if res.Cleanup.Teardown != CleanupDone || res.Cleanup.Unstage != CleanupDone {
		t.Errorf("cleanup %+v, want both done", res.Cleanup)
	}
}
