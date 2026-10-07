package cli

import (
	"context"
	"os"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/provision"
)

// An interrupt that arrives while the start is still waiting for a worker to take the run
// abandons the start, and the command ends run.cancelled, exit 2, with nothing followed or
// cancelled: the client has terminated the run no worker took.
func TestCreateInterruptWhileStartingAbandonsTheStart(t *testing.T) {
	for _, c := range []struct {
		name     string
		startErr error
		want     string
	}{
		{"the client terminated the started run", &provision.StartError{Status: findings.StatusError, Finding: findings.Finding{
			Severity: findings.Rejection, Rule: findings.RuleRunCancelled, Object: "run-1", Step: findings.StepStart,
			Message: "interrupted before a worker took run run-1, so the run was terminated before anything in it ran",
		}}, "terminated"},
		{"no run had been started", context.Canceled, "nothing was started"},
	} {
		t.Run(c.name, func(t *testing.T) {
			interrupts := useInterrupts(t)
			svc := &fakeService{startBlocks: true, startErr: c.startErr}
			useService(t, svc)
			interrupts <- os.Interrupt

			code, doc := exitOf(t, runCreate(context.Background(), &options{asJSON: true}, &createFlags{branch: "fylgja-fixture"}))

			if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleRunCancelled ||
				doc.Findings[0].Step != findings.StepStart || !strings.Contains(doc.Findings[0].Message, c.want) {
				t.Fatalf("exit %d, findings %+v; want 2 with run.cancelled at start saying %q", code, doc.Findings, c.want)
			}
			svc.mu.Lock()
			defer svc.mu.Unlock()
			if !svc.abandoned {
				t.Error("the start was not abandoned")
			}
			if svc.cancels != 0 {
				t.Errorf("Cancel called %d times, want none: no run was followed", svc.cancels)
			}
			validateM2Document(t, doc)
		})
	}
}

// An interrupt that arrives just as a start succeeds is the first interrupt: the run is
// cancelled and the command waits for its cleanup.
func TestCreateInterruptRacingASuccessfulStartCancelsTheRun(t *testing.T) {
	interrupts := useInterrupts(t)
	release := make(chan struct{})
	svc := &fakeService{runID: "run-1", startBlocks: true, release: release, result: provision.ProvisionResult{
		Outcome: provision.OutcomeCancelled, BundleID: fixtureBundleID, Step: findings.StepRead, Findings: findings.List{},
		Cleanup: provision.CleanupResult{Teardown: provision.CleanupSkipped, Unstage: provision.CleanupSkipped},
	}}
	svc.onCancel = func() { close(release) }
	useService(t, svc)
	interrupts <- os.Interrupt

	code, doc := exitOf(t, runCreate(context.Background(), &options{asJSON: true}, &createFlags{branch: "fylgja-fixture"}))

	if svc.cancels != 1 {
		t.Errorf("Cancel called %d times, want once", svc.cancels)
	}
	if code != findings.ExitError || doc.Subject.RunID != "run-1" {
		t.Errorf("exit %d, document %+v; want 2 for a run cancelled before the host check, naming run-1", code, doc)
	}
}
