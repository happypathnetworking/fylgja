package provision

import (
	"context"
	"errors"
	"slices"
	"strings"
	"testing"

	"github.com/stretchr/testify/mock"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// injected is a failure retrying cannot help, as a host-bound or control activity reports
// one.
func injected(step, rule, object string) error {
	return lab.StepFailure(step, rule, object, rule+" injected at step "+step)
}

func rejection(step, rule string) findings.List {
	var l findings.List
	l.AddStep(findings.Rejection, step, rule, "object", "refused")
	return l
}

// A failure injected at each step: before the host is touched nothing is cleaned up and a
// refusal is rejected while a step that could not run is error; after the host check has
// cleared, teardown then unstage run to completion and the run is failed.
func TestProvisionFailureAtEachStepRunsCleanup(t *testing.T) {
	in := ProvisionInput{Source: wire.SourceIntent, Branch: "fylgja-fixture"}

	t.Run("before the host is touched", func(t *testing.T) {
		for _, c := range []struct {
			name    string
			inject  func(h *harness)
			step    string
			outcome string
			rule    string
		}{
			{"read refused", func(h *harness) {
				h.env.OnActivity(wire.ActReadIntent, mock.Anything, mock.Anything).Return(
					ReadIntentResult{Findings: rejection(findings.StepRead, findings.RuleDevicesEmpty)}, nil)
			}, findings.StepRead, OutcomeRejected, findings.RuleDevicesEmpty},
			{"read could not run", func(h *harness) {
				h.env.OnActivity(wire.ActReadIntent, mock.Anything, mock.Anything).Return(
					ReadIntentResult{}, injected(findings.StepRead, findings.RuleOperationFailed, "branch fylgja-fixture"))
			}, findings.StepRead, OutcomeError, findings.RuleOperationFailed},
			// An unknown branch is M1–M3's operation.failed and error for a create, whatever
			// type ReadIntent gives it for a check.
			{"read of a branch that does not exist", func(h *harness) {
				h.env.OnActivity(wire.ActReadIntent, mock.Anything, mock.Anything).Return(
					ReadIntentResult{}, branchNotFound("branch fylgja-fixture", errors.New("Branch: fylgja-fixture not found.")))
			}, findings.StepRead, OutcomeError, findings.RuleOperationFailed},
			{"compile refused", func(h *harness) {
				h.env.OnActivity(wire.ActCompile, mock.Anything, mock.Anything).Return(
					CompileResult{Findings: rejection(findings.StepCompile, findings.RuleLinkEndpointsCount)}, nil)
			}, findings.StepCompile, OutcomeRejected, findings.RuleLinkEndpointsCount},
			{"compile could not run", func(h *harness) {
				h.env.OnActivity(wire.ActCompile, mock.Anything, mock.Anything).Return(
					CompileResult{}, injected(findings.StepCompile, findings.RuleOperationFailed, "/state/bundles/.reads/run.ctm.json"))
			}, findings.StepCompile, OutcomeError, findings.RuleOperationFailed},
			{"host check refused", func(h *harness) {
				refused := h.plan
				refused.Findings = rejection(findings.StepHostCheck, findings.RuleHostLabPresent)
				h.env.OnActivity(wire.ActCheckHost, mock.Anything, mock.Anything).Return(refused, nil)
			}, findings.StepHostCheck, OutcomeRejected, findings.RuleHostLabPresent},
			{"host check could not run", func(h *harness) {
				h.env.OnActivity(wire.ActCheckHost, mock.Anything, mock.Anything).Return(
					wire.CheckHostResult{}, injected(findings.StepHostCheck, findings.RuleOperationFailed, "/state/bundles/x"))
			}, findings.StepHostCheck, OutcomeError, findings.RuleOperationFailed},
		} {
			t.Run(c.name, func(t *testing.T) {
				h := newHarness(t)
				c.inject(h)
				h.mockHappyPath()
				h.mockCleanup()

				res := h.run(in)

				if res.Outcome != c.outcome || res.Step != c.step {
					t.Errorf("outcome %q at %q, want %q at %q", res.Outcome, res.Step, c.outcome, c.step)
				}
				if !carries(res.Findings, c.rule, c.step) {
					t.Errorf("findings %+v, want %s at %s", res.Findings, c.rule, c.step)
				}
				if res.Cleanup.Teardown != CleanupSkipped || res.Cleanup.Unstage != CleanupSkipped {
					t.Errorf("cleanup %+v, want both skipped: nothing was touched", res.Cleanup)
				}
				if h.ran(wire.ActDestroyLab) || h.ran(wire.ActUnstageTwin) || h.ran(wire.ActStageBundle) {
					t.Errorf("activities %v touched the host", h.calls())
				}
			})
		}
	})

	t.Run("after the host check cleared", func(t *testing.T) {
		for _, c := range []struct {
			name   string
			inject func(h *harness)
			step   string
			rule   string
		}{
			{"stage", func(h *harness) {
				h.env.OnActivity(wire.ActStageBundle, mock.Anything, mock.Anything).Return(
					wire.StageResult{}, injected(findings.StepStage, findings.RuleStageFailed, "/state/twin/bundle"))
			}, findings.StepStage, findings.RuleStageFailed},
			{"deploy", func(h *harness) {
				h.env.OnActivity(wire.ActDeployLab, mock.Anything, mock.Anything).Return(
					wire.DeployResult{}, injected(findings.StepDeploy, findings.RuleDeployFailed, "lab fylgja"))
			}, findings.StepDeploy, findings.RuleDeployFailed},
			{"readiness", func(h *harness) {
				h.env.OnActivity(wire.ActAwaitReadiness, mock.Anything, mock.Anything).Return(
					func(_ context.Context, in wire.ReadinessInput) (wire.ReadinessResult, error) {
						if in.Node == "n2" {
							return wire.ReadinessResult{}, injected(findings.StepReadiness, findings.RuleReadinessTimeout, "n2")
						}
						return wire.ReadinessResult{Node: in.Node, ReadyAfterS: 0.9}, nil
					})
			}, findings.StepReadiness, findings.RuleReadinessTimeout},
			{"record", func(h *harness) {
				h.env.OnActivity(wire.ActRecordTwin, mock.Anything, mock.Anything).Return(
					wire.RecordResult{}, injected(findings.StepRecord, findings.RuleRecordFailed, "/state/twin/twin.json"))
			}, findings.StepRecord, findings.RuleRecordFailed},
		} {
			t.Run(c.name, func(t *testing.T) {
				h := newHarness(t)
				c.inject(h)
				h.mockHappyPath()
				h.mockCleanup()

				res := h.run(in)

				calls := h.calls()
				if n := len(calls); n < 2 || !slices.Equal(calls[n-2:], []string{wire.ActDestroyLab, wire.ActUnstageTwin}) {
					t.Errorf("activities %v, want teardown then unstage last", calls)
				}
				if res.Outcome != OutcomeFailed || res.Step != c.step || !carries(res.Findings, c.rule, c.step) {
					t.Errorf("outcome %q at %q with %+v; want failed at %s with %s", res.Outcome, res.Step, res.Findings, c.step, c.rule)
				}
				if res.Cleanup.Teardown != CleanupDone || res.Cleanup.Unstage != CleanupDone || len(res.Cleanup.Remaining) != 0 {
					t.Errorf("cleanup %+v, want both done and nothing remaining", res.Cleanup)
				}
				if res.Twin != nil {
					t.Error("a failed run carries a twin record")
				}
				doc := ProvisionDocument(findings.OpTwinCreate, &findings.Subject{Branch: "fylgja-fixture", RunID: "run-1"}, res)
				if code := doc.Status.ExitCode(); code != findings.ExitFailed {
					t.Errorf("exit %d, want %d", code, findings.ExitFailed)
				}
				mustValidateM2(t, doc, c.name)
			})
		}
	})

	// Every readiness future is awaited, so the failure names the node that did not answer
	// and the ones that did.
	t.Run("readiness names the nodes that answered", func(t *testing.T) {
		h := newHarness(t)
		h.env.OnActivity(wire.ActAwaitReadiness, mock.Anything, mock.Anything).Return(
			func(_ context.Context, in wire.ReadinessInput) (wire.ReadinessResult, error) {
				if in.Node == "n2" {
					return wire.ReadinessResult{}, injected(findings.StepReadiness, findings.RuleReadinessTimeout, "n2")
				}
				return wire.ReadinessResult{Node: in.Node, ReadyAfterS: 0.9}, nil
			})
		h.mockHappyPath()
		h.mockCleanup()

		res := h.run(in)

		var timedOut []findings.Finding
		for _, f := range res.Findings {
			if f.Rule == findings.RuleReadinessTimeout {
				timedOut = append(timedOut, f)
			}
		}
		if len(timedOut) != 1 || timedOut[0].Object != "n2" ||
			!strings.Contains(timedOut[0].Message, "ready: n1 in 0.9s, n3 in 0.9s") {
			t.Errorf("readiness findings %+v, want one for n2 naming n1 and n3 as ready", timedOut)
		}
	})

	t.Run("a teardown that fails leaves something remaining", func(t *testing.T) {
		h := newHarness(t)
		h.env.OnActivity(wire.ActDeployLab, mock.Anything, mock.Anything).Return(
			wire.DeployResult{}, injected(findings.StepDeploy, findings.RuleDeployFailed, "lab fylgja"))
		h.env.OnActivity(wire.ActDestroyLab, mock.Anything, mock.Anything).Return(wire.DestroyLabResult{},
			lab.StepFailure(findings.StepTeardown, findings.RuleCleanupIncomplete, "lab fylgja",
				"lab fylgja is still present after clab destroy (exited 0): n1 running; clear it with: clab destroy --name fylgja --cleanup"))
		h.mockHappyPath()
		h.mockCleanup()

		res := h.run(in)

		if res.Cleanup.Teardown != CleanupFailed || res.Cleanup.Unstage != CleanupDone || len(res.Cleanup.Remaining) == 0 {
			t.Errorf("cleanup %+v, want teardown failed, unstage done, something remaining", res.Cleanup)
		}
		if !carries(res.Findings, findings.RuleDeployFailed, findings.StepDeploy) ||
			!carries(res.Findings, findings.RuleCleanupIncomplete, findings.StepTeardown) {
			t.Errorf("findings %+v, want the deploy failure and the incomplete teardown", res.Findings)
		}
		doc := ProvisionDocument(findings.OpTwinCreate, &findings.Subject{Branch: "fylgja-fixture", RunID: "run-1"}, res)
		if code := doc.Status.ExitCode(); code != findings.ExitUnclean {
			t.Errorf("exit %d, want %d", code, findings.ExitUnclean)
		}
		mustValidateM2(t, doc, "teardown failed")
	})
}
