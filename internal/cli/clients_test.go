package cli

import (
	"context"
	"errors"
	"slices"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
)

// Two clients at once. The server holds
// nothing per workflow identity, and adds no lock: two clients are refused by the fixed
// workflow identities alone, which the workflow service enforces, as at M2–M12. The streams
// map is keyed by the stream a client named, and the second client's start reaches the
// service.

// inFlightService is the harness's fake service shared by two clients: the first start is
// held open until released, and a start while it is open is refused as the workflow service
// refuses a second run of the fixed identity (internal/provision/client.go, inFlightRefusal).
type inFlightService struct {
	*fakeService
	entered, release chan struct{}
	open             atomic.Bool
}

func (s *inFlightService) StartProvision(ctx context.Context, in provision.ProvisionInput) (string, error) {
	s.mu.Lock()
	s.calls = append(s.calls, "StartProvision")
	s.mu.Unlock()
	if !s.open.CompareAndSwap(false, true) {
		return "", &provision.StartError{Status: findings.StatusRejected, Finding: findings.Finding{
			Severity: findings.Rejection, Rule: findings.RuleRunInFlight, Object: provision.WorkflowProvision, Step: findings.StepStart,
			Message: "provisioning run " + s.runID + " is already in flight; wait for it to finish, or run fylgja twin destroy to cancel it",
		}}
	}
	close(s.entered)
	select {
	case <-s.release:
		return s.runID, nil
	case <-ctx.Done():
		return "", ctx.Err()
	}
}

// waitFor waits for ch to close, or fails the test.
func waitFor(t *testing.T, ch <-chan struct{}, what string) {
	t.Helper()
	select {
	case <-ch:
	case <-time.After(5 * time.Second):
		t.Fatalf("%s never happened", what)
	}
}

// Two creates at once: while the first's start is open, the second is refused run.in_flight,
// exit 1, in M12's words, by the workflow service and not by the server; the first goes on to
// its own end, unaffected.
func TestTwoCreatesAtOnce(t *testing.T) {
	useStateRoot(t)
	useInterrupts(t)
	svc := &inFlightService{fakeService: &fakeService{runID: "run-1", result: readyResult()},
		entered: make(chan struct{}), release: make(chan struct{})}
	useService(t, svc)
	flags := func() *createFlags { return &createFlags{branch: "fylgja-fixture", noFollow: true} }

	first := make(chan error, 1)
	go func() { first <- runCreate(context.Background(), &options{asJSON: true}, flags()) }()
	waitFor(t, svc.entered, "the first create's start")

	code, doc := exitOf(t, runCreate(context.Background(), &options{asJSON: true}, flags()))
	want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleRunInFlight, Object: provision.WorkflowProvision,
		Step:    findings.StepStart,
		Message: "provisioning run run-1 is already in flight; wait for it to finish, or run fylgja twin destroy to cancel it"}
	if code != findings.ExitRejected || doc.Status != findings.StatusRejected || len(doc.Findings) != 1 || doc.Findings[0] != want {
		t.Errorf("the second create: exit %d, status %s, findings %+v; want 1, rejected, %+v alone", code, doc.Status, doc.Findings, want)
	}
	validateM2Document(t, doc)

	// The first's request is open, under the stream its client named: nothing is open under
	// the workflow's identity.
	client, err := api.NewClient(getenv, build)
	if err != nil {
		t.Fatal(err)
	}
	if err := client.Interrupt(context.Background(), provision.WorkflowProvision); !errors.Is(err, api.ErrStreamEnded) {
		t.Errorf("an interrupt naming %s answered %v, want nothing open under it", provision.WorkflowProvision, err)
	}

	close(svc.release)
	select {
	case err = <-first:
	case <-time.After(5 * time.Second):
		t.Fatal("the first create never ended")
	}
	code, doc = exitOf(t, err)
	if code != findings.ExitOK || doc.Subject == nil || doc.Subject.RunID != "run-1" {
		t.Errorf("the first create: exit %d, document %+v; want 0 naming run-1", code, doc)
	}
	svc.mu.Lock()
	defer svc.mu.Unlock()
	if !slices.Equal(svc.calls, []string{"StartProvision", "StartProvision"}) {
		t.Errorf("the service was asked %v; want both starts to reach it, the server holding nothing per workflow", svc.calls)
	}
	if svc.cancels != 0 {
		t.Errorf("Cancel called %d times, want none", svc.cancels)
	}
}

// destroyDuringAStep is the harness's fake service while one client follows a step run and a
// second runs twin destroy: the destroy cancels the step, as the workflow service's client
// does, by letting the step run close once its record is written, then announces it closed
// and runs the destroy (internal/provision/client.go).
type destroyDuringAStep struct {
	*fakeService
	following, resulted chan struct{}
}

func (s *destroyDuringAStep) ResultOfStep(ctx context.Context, runID string) (provision.StepResult, error) {
	defer close(s.resulted)
	return s.fakeService.ResultOfStep(ctx, runID)
}

func (s *destroyDuringAStep) StartDestroy(ctx context.Context, onEvent func(provision.Event)) (provision.DestroyRun, error) {
	onEvent(provision.Event{Notice: "cancelling step run " + stepRunID + "; waiting for its record"})
	close(s.release)
	select {
	case <-s.resulted:
	case <-time.After(5 * time.Second):
	}
	onEvent(provision.Event{Notice: "step run " + stepRunID + " closed: diverged"})
	return s.fakeService.StartDestroy(ctx, onEvent)
}

// A destroy from a second client while the first follows a step run: the second prints M12's
// notices, and the first's answer ends with the step's own outcome, diverged, which the
// destroy's cancellation made. The first client cancelled nothing.
func TestADestroyFromASecondClientDuringAStep(t *testing.T) {
	stepHost(t, "plan-link-added.json", nil)
	useInterrupts(t)
	cancelled := provision.StepResult{Outcome: provision.OutcomeCancelled, Phase: findings.StepReadiness, Step: findings.StepReadiness,
		PushPlan: []wire.StepPush{{Node: "e1", Reasons: []string{"artifact", "restarted"}, Outcome: wire.PushNotAttempted},
			{Node: "s1", Reasons: []string{"artifact", "bootstrap"}, Outcome: wire.PushNotAttempted}},
		Record: &wire.TwinRecord{State: wire.StateDiverged}, StartedAt: "2026-10-02T09:14:30Z", EndedAt: "2026-10-02T09:15:41Z",
		Findings: findings.List{
			{Severity: findings.Rejection, Rule: findings.RuleRunCancelled, Object: stepRunID, Step: findings.StepReadiness,
				Message: "run " + stepRunID + " was cancelled at step readiness; the record was written diverged and nothing was torn down"},
			{Severity: findings.Rejection, Rule: findings.RuleStepDiverged, Object: stepRunID, Step: findings.StepReadiness,
				Message: "step run " + stepRunID + " towards waypoint steps/2 stopped at phase readiness; …"}}}
	following := make(chan struct{})
	svc := &destroyDuringAStep{fakeService: &fakeService{runID: stepRunID, release: make(chan struct{}), stepResult: cancelled,
		events: []provision.Event{{WorkflowID: provision.WorkflowStep, Step: "readiness e1", FindingStep: findings.StepReadiness}},
		destroyRun: destroyedRun(provision.CleanupResult{Teardown: provision.CleanupDone, Unstage: provision.CleanupDone,
			Removed: []string{"lab fylgja (3 containers)", "twin directory /abs/local/twin"}}, nil),
		destroyEvents: []provision.Event{{Notice: "run fylgja-destroy run-d"}},
		afterFollow:   func() { close(following) }},
		following: following, resulted: make(chan struct{})}
	useService(t, svc)

	first := make(chan error, 1)
	go func() {
		first <- runTwinStep(context.Background(), &options{asJSON: true}, &stepFlags{allowRestart: true})
	}()
	waitFor(t, svc.following, "the first client's follow of the step run")

	var err error
	out := captureStdout(t, func() { err = runDestroy(context.Background(), &options{}) })
	code, doc := exitOf(t, err)
	if code != findings.ExitOK || doc.Subject == nil || doc.Subject.RunID != "run-d" {
		t.Errorf("the destroy: exit %d, document %+v; want 0 naming run-d", code, doc)
	}
	want := strings.Join([]string{
		"cancelling step run " + stepRunID + "; waiting for its record",
		"step run " + stepRunID + " closed: diverged",
		"run fylgja-destroy run-d",
		"removed lab fylgja (3 containers)",
		"removed twin directory /abs/local/twin",
	}, "\n") + "\n"
	if out != want {
		t.Errorf("the destroy's stdout:\n%s\nwant:\n%s", out, want)
	}

	select {
	case err = <-first:
	case <-time.After(5 * time.Second):
		t.Fatal("the first client's step never ended")
	}
	code, doc = exitOf(t, err)
	if code != findings.ExitUnclean || doc.Status != findings.StatusDiverged {
		t.Errorf("the step: exit %d, status %s; want 4, diverged, as the run closed; findings %+v", code, doc.Status, doc.Findings)
	}
	for _, f := range cancelled.Findings {
		if !slices.Contains(doc.Findings, f) {
			t.Errorf("the step's findings %+v lack the run's %+v", doc.Findings, f)
		}
	}
	validateM10Document(t, doc)
	svc.mu.Lock()
	defer svc.mu.Unlock()
	if svc.cancels != 0 || svc.destroys != 1 {
		t.Errorf("Cancel called %d times, destroys %d; want the destroy's own cancellation alone", svc.cancels, svc.destroys)
	}
}
