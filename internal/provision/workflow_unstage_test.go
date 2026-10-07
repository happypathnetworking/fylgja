package provision

import (
	"errors"
	"slices"
	"strings"
	"testing"

	"github.com/stretchr/testify/mock"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// An unstage that never answered — timed out, or its worker lost — still says what may
// remain and how to clear it, as a teardown in the same state does.
func TestAnUnstageThatNeverAnsweredSaysHowToClear(t *testing.T) {
	workerLost := errors.New("worker lost")
	clearing := "run fylgja twin destroy again once a worker is serving task queue fylgja"

	t.Run("provisioning cleanup", func(t *testing.T) {
		h := newHarness(t)
		h.env.OnActivity(wire.ActDeployLab, mock.Anything, mock.Anything).Return(
			wire.DeployResult{}, injected(findings.StepDeploy, findings.RuleDeployFailed, "lab fylgja"))
		h.env.OnActivity(wire.ActUnstageTwin, mock.Anything).Return(wire.UnstageResult{}, workerLost)
		h.mockHappyPath()
		h.mockCleanup()

		res := h.run(ProvisionInput{Source: wire.SourceIntent, Branch: "fylgja-fixture"})

		if res.Cleanup.Unstage != CleanupFailed || !slices.Equal(res.Cleanup.Remaining, []string{"twin directory /state/twin"}) {
			t.Errorf("cleanup %+v, want unstage failed and the twin directory's path remaining", res.Cleanup)
		}
		f := unstageFinding(t, res.Findings)
		if f.Object != "/state/twin" || !strings.Contains(f.Message, clearing) || !strings.Contains(f.Message, "worker lost") {
			t.Errorf("finding %+v, want the path, the cause and how to clear it", f)
		}
		doc := ProvisionDocument(findings.OpTwinCreate, &findings.Subject{Branch: "fylgja-fixture", RunID: "run-1"}, res)
		if code := doc.Status.ExitCode(); code != findings.ExitUnclean {
			t.Errorf("exit %d, want %d", code, findings.ExitUnclean)
		}
		mustValidateM2(t, doc, "unstage never answered")
	})

	t.Run("destroy", func(t *testing.T) {
		h := newHarness(t)
		h.env.OnActivity(wire.ActPlanTeardown, mock.Anything).Return(wire.PlanTeardownResult{DestroyTimeoutS: 60, Basis: wire.BasisManifest}, nil)
		h.env.OnActivity(wire.ActDestroyLab, mock.Anything, mock.Anything).Return(wire.DestroyLabResult{Removed: true, Containers: 3}, nil)
		h.env.OnActivity(wire.ActUnstageTwin, mock.Anything).Return(wire.UnstageResult{}, workerLost)

		res := h.runDestroy()

		if res.Cleanup.Unstage != CleanupFailed || !slices.Equal(res.Cleanup.Remaining, []string{"twin directory"}) {
			t.Errorf("cleanup %+v, want unstage failed and the twin directory remaining", res.Cleanup)
		}
		if f := unstageFinding(t, res.Findings); !strings.Contains(f.Message, clearing) {
			t.Errorf("finding %+v, want how to clear it", f)
		}
		doc := DestroyDocument(&findings.Subject{RunID: "run-d"}, res, FollowStop{})
		if code := doc.Status.ExitCode(); code != findings.ExitUnclean {
			t.Errorf("exit %d, want %d", code, findings.ExitUnclean)
		}
		mustValidateM2(t, doc, "destroy unstage never answered")
	})
}

func unstageFinding(t *testing.T, list findings.List) findings.Finding {
	t.Helper()
	for _, f := range list {
		if f.Rule == findings.RuleCleanupIncomplete && f.Step == findings.StepUnstage {
			return f
		}
	}
	t.Fatalf("findings %+v, want cleanup.incomplete at unstage", list)
	return findings.Finding{}
}
