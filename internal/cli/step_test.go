package cli

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/provision"
)

// Every finding twin create, twin provision, twin destroy and twin step (M11) make
// themselves, rather than receive from a run, names the step it belongs to, as the run's own
// findings do (contracts/findings.schema.json, where only M1's operations carry
// no step). A failure met while following a run names the step the run had reached.
func TestM2CommandFindingsNameTheirStep(t *testing.T) {
	ctx := context.Background()
	jsonOut := &options{asJSON: true}
	boom := errors.New("the workflow service answered with an internal error")
	event := func(workflowID, step, findingStep string) provision.Event {
		return provision.Event{Step: step, WorkflowID: workflowID, FindingStep: findingStep}
	}

	for _, c := range []struct {
		name string
		step string
		rule string
		// run drives the command and returns the object the finding must name, or "" when
		// the object is not what the case is about.
		run func(t *testing.T) (object string, err error)
	}{
		{"create dry run, the read cannot run", findings.StepRead, findings.RuleOperationFailed,
			func(t *testing.T) (string, error) {
				useStateRoot(t)
				useService(t, nil)
				dryRunEnv(t)
				useClab(t, "inspect-empty.json")
				t.Setenv(intent.EnvAddress, unreachable)
				t.Setenv(intent.EnvToken, "any-token")
				return "branch fylgja-fixture", runCreate(ctx, jsonOut, &createFlags{branch: "fylgja-fixture", dryRun: true})
			}},
		{"create, an invalid override package", findings.StepRead, findings.RulePSPReadinessEncoding,
			func(t *testing.T) (string, error) {
				useService(t, nil)
				usePSPDir(t, invalidOverrideDir(t))
				return "", runCreate(ctx, &options{asJSON: true}, &createFlags{branch: "fylgja-fixture"})
			}},
		{"provision dry run, the host check cannot run", findings.StepHostCheck, findings.RuleOperationFailed,
			func(t *testing.T) (string, error) {
				useStateRoot(t)
				useService(t, nil)
				dryRunEnv(t)
				saved := dryRunRunner
				t.Cleanup(func() { dryRunRunner = saved })
				dryRunRunner = &fakeClab{stdout: []byte("not json")}
				return findings.StepHostCheck, runTwinProvision(ctx, jsonOut, &provisionFlags{dryRun: true}, copyGoldenBundle(t, "b"))
			}},
		{"provision, a missing directory", findings.StepVerify, findings.RuleOperationFailed,
			func(t *testing.T) (string, error) {
				useStateRoot(t)
				useService(t, nil)
				dir := filepath.Join(t.TempDir(), "absent")
				return dir, runTwinProvision(ctx, jsonOut, &provisionFlags{}, dir)
			}},
		{"provision, an invalid override package", findings.StepVerify, findings.RulePSPReadinessEncoding,
			func(t *testing.T) (string, error) {
				useStateRoot(t)
				useService(t, nil)
				usePSPDir(t, invalidOverrideDir(t))
				return "", runTwinProvision(ctx, &options{asJSON: true}, &provisionFlags{}, copyGoldenBundle(t, "b"))
			}},
		{"create, the start fails", findings.StepStart, findings.RuleOperationFailed,
			func(t *testing.T) (string, error) {
				useInterrupts(t)
				useService(t, &fakeService{startErr: boom})
				return findings.StepStart, runCreate(ctx, jsonOut, &createFlags{branch: "fylgja-fixture"})
			}},
		{"create, waiting for the run fails during deploy", findings.StepDeploy, findings.RuleOperationFailed,
			func(t *testing.T) (string, error) {
				useInterrupts(t)
				useService(t, &fakeService{runID: "run-1", resultErr: boom,
					events: []provision.Event{event(provision.WorkflowProvision, "deploy", findings.StepDeploy)}})
				return findings.StepDeploy, runCreate(ctx, jsonOut, &createFlags{branch: "fylgja-fixture"})
			}},
		{"create, a second interrupt during readiness", findings.StepReadiness, findings.RuleRunCancelled,
			func(t *testing.T) (string, error) {
				interrupts := useInterrupts(t)
				svc := &fakeService{runID: "run-1", release: make(chan struct{}),
					events: []provision.Event{event(provision.WorkflowProvision, "readiness n1", findings.StepReadiness)}}
				svc.afterFollow = func() { interrupts <- os.Interrupt; interrupts <- os.Interrupt }
				useService(t, svc)
				return "run-1", runCreate(ctx, jsonOut, &createFlags{branch: "fylgja-fixture"})
			}},
		{"destroy, the start fails", findings.StepStart, findings.RuleOperationFailed,
			func(t *testing.T) (string, error) {
				useService(t, &fakeService{destroyErr: boom})
				return findings.StepStart, runDestroy(ctx, jsonOut)
			}},
		{"destroy, waiting for the provisioning run it cancelled fails", findings.StepStart, findings.RuleOperationFailed,
			func(t *testing.T) (string, error) {
				useService(t, &fakeService{destroyErr: boom,
					destroyEvents: []provision.Event{event(provision.WorkflowProvision, "cleanup teardown", findings.StepTeardown)}})
				return findings.StepStart, runDestroy(ctx, jsonOut)
			}},
		{"destroy, waiting for the destroy run fails during teardown", findings.StepTeardown, findings.RuleOperationFailed,
			func(t *testing.T) (string, error) {
				useService(t, &fakeService{destroyErr: boom, destroyEvents: []provision.Event{
					{Notice: "run fylgja-destroy run-d"},
					event(provision.WorkflowDestroy, "teardown", findings.StepTeardown),
				}})
				return findings.StepTeardown, runDestroy(ctx, jsonOut)
			}},
		// twin step's own findings, before any run.
		{"step, an invalid override package", findings.StepRead, findings.RulePSPReadinessEncoding,
			func(t *testing.T) (string, error) {
				stepHost(t, "plan-link-added.json", nil)
				usePSPDir(t, invalidOverrideDir(t))
				return "", runTwinStep(ctx, &options{asJSON: true}, &stepFlags{})
			}},
		{"step, the host cannot be inspected", findings.StepResolve, findings.RuleOperationFailed,
			func(t *testing.T) (string, error) {
				h := stepHost(t, "plan-link-added.json", nil)
				h.clab.inspect = []byte("not json")
				return "lab fylgja", runTwinStep(ctx, jsonOut, &stepFlags{})
			}},
		{"step, Infrahub cannot be reached", findings.StepResolve, findings.RuleOperationFailed,
			func(t *testing.T) (string, error) {
				stepHost(t, "plan-link-added.json", nil)
				t.Setenv(intent.EnvAddress, unreachable)
				return findings.OpTwinStep, runTwinStep(ctx, jsonOut, &stepFlags{})
			}},
		{"step, the target's read cannot run", findings.StepRead, findings.RuleOperationFailed,
			func(t *testing.T) (string, error) {
				h := stepHost(t, "plan-link-added.json", nil)
				delete(h.infra.branches, "mixed-step")
				return "steps/2", runTwinStep(ctx, jsonOut, &stepFlags{})
			}},
		{"step, containerlab's plan cannot be read", findings.StepCompare, findings.RuleOperationFailed,
			func(t *testing.T) (string, error) {
				h := stepHost(t, "plan-link-added.json", nil)
				b, err := os.ReadFile(repoPath("internal", "lab", "testdata", "plan-no-lab.json"))
				if err != nil {
					t.Fatal(err)
				}
				h.clab.plan = b
				return "lab fylgja", runTwinStep(ctx, jsonOut, &stepFlags{})
			}},
		{"step, the start fails", findings.StepStart, findings.RuleOperationFailed,
			func(t *testing.T) (string, error) {
				stepHost(t, "plan-link-added.json", nil)
				useInterrupts(t)
				useService(t, &fakeService{startErr: boom})
				return findings.StepStart, runTwinStep(ctx, jsonOut, &stepFlags{allowRestart: true})
			}},
		{"step, waiting for the run fails during readiness", findings.StepReadiness, findings.RuleOperationFailed,
			func(t *testing.T) (string, error) {
				stepHost(t, "plan-link-added.json", nil)
				useInterrupts(t)
				useService(t, &fakeService{runID: "run-s", resultErr: boom,
					events: []provision.Event{event(provision.WorkflowStep, "readiness e1", findings.StepReadiness)}})
				return findings.StepReadiness, runTwinStep(ctx, jsonOut, &stepFlags{allowRestart: true})
			}},
	} {
		t.Run(c.name, func(t *testing.T) {
			object, err := c.run(t)
			_, doc := exitOf(t, err)
			if !carriesRule(doc.Findings, c.rule) {
				t.Fatalf("findings %+v, want %s", doc.Findings, c.rule)
			}
			for _, f := range doc.Findings {
				if f.Step == "" {
					t.Errorf("finding %+v names no step", f)
				}
				if f.Rule == c.rule && (f.Step != c.step || (object != "" && f.Object != object)) {
					t.Errorf("finding %+v, want step %s and object %q", f, c.step, object)
				}
			}
			// twin step is M11's operation, which M2's contract does not name.
			if doc.Operation == findings.OpTwinStep {
				validateM10Document(t, doc)
			} else {
				validateM2Document(t, doc)
			}
		})
	}
}
