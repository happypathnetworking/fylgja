package cli

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/provision"
)

func destroyedRun(c provision.CleanupResult, list findings.List) provision.DestroyRun {
	if list == nil {
		list = findings.List{}
	}
	return provision.DestroyRun{RunID: "run-d", Result: provision.DestroyResult{Cleanup: c, Findings: list}}
}

// Destroy says what it removed, one line each, or that there was nothing; exit 0 either
// way.
func TestDestroyPrintsWhatItRemoved(t *testing.T) {
	const twinDir = "twin directory /abs/local/twin"
	for _, c := range []struct {
		name    string
		cleanup provision.CleanupResult
		want    []string
	}{
		{"lab and twin directory", provision.CleanupResult{Teardown: provision.CleanupDone, Unstage: provision.CleanupDone,
			Removed: []string{"lab fylgja (3 containers)", twinDir}},
			[]string{"removed lab fylgja (3 containers)", "removed " + twinDir}},
		{"an orphan lab", provision.CleanupResult{Teardown: provision.CleanupDone, Unstage: provision.CleanupNothing,
			Removed: []string{"lab fylgja (3 containers)"}},
			[]string{"removed lab fylgja (3 containers)"}},
		{"a twin directory without a lab", provision.CleanupResult{Teardown: provision.CleanupNothing, Unstage: provision.CleanupDone,
			Removed: []string{twinDir}},
			[]string{"removed " + twinDir}},
		{"nothing", provision.CleanupResult{Teardown: provision.CleanupNothing, Unstage: provision.CleanupNothing},
			[]string{"nothing to remove: no lab fylgja, no twin directory"}},
	} {
		t.Run(c.name, func(t *testing.T) {
			svc := &fakeService{destroyRun: destroyedRun(c.cleanup, nil),
				destroyEvents: []provision.Event{{Notice: "run fylgja-destroy run-d"}}}
			useService(t, svc)

			var err error
			out := captureStdout(t, func() { err = runDestroy(context.Background(), &options{}) })
			code, doc := exitOf(t, err)
			if code != findings.ExitOK || doc.Operation != findings.OpTwinDestroy {
				t.Fatalf("exit %d, document %+v; want 0 from twin.destroy", code, doc)
			}
			want := "run fylgja-destroy run-d\n" + strings.Join(c.want, "\n") + "\n"
			if out != want {
				t.Errorf("stdout:\n%s\nwant:\n%s", out, want)
			}
			if svc.destroys != 1 || !svc.closed {
				t.Errorf("destroys %d, closed %v; want one destroy and the connection closed", svc.destroys, svc.closed)
			}
		})
	}
}

// Something left on the host is exit 4, with cleanup.incomplete naming what remains and
// the command that clears it.
func TestDestroyUncleanExitsFour(t *testing.T) {
	msg := "lab fylgja is still present after clab destroy (exited 0): n1 running; clear it with: clab destroy --name fylgja --cleanup"
	list := findings.List{{Severity: findings.Rejection, Rule: findings.RuleCleanupIncomplete, Object: "lab fylgja",
		Step: findings.StepTeardown, Message: msg}}
	useService(t, &fakeService{destroyRun: destroyedRun(provision.CleanupResult{
		Teardown: provision.CleanupFailed, Unstage: provision.CleanupDone,
		Removed: []string{"twin directory /abs/local/twin"}, Remaining: []string{"lab fylgja"},
	}, list)})

	var err error
	out := captureStdout(t, func() { err = runDestroy(context.Background(), &options{}) })
	code, doc := exitOf(t, err)
	if code != findings.ExitUnclean || doc.Status != findings.StatusUnclean {
		t.Fatalf("exit %d, status %s; want 4, unclean", code, doc.Status)
	}
	if len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleCleanupIncomplete ||
		!strings.Contains(doc.Findings[0].Message, "clab destroy --name fylgja --cleanup") {
		t.Errorf("findings %+v, want cleanup.incomplete with the clearing command", doc.Findings)
	}
	if doc.Cleanup == nil || len(doc.Cleanup.Remaining) != 1 || doc.Cleanup.Remaining[0] != "lab fylgja" {
		t.Errorf("cleanup block %+v, want lab fylgja remaining", doc.Cleanup)
	}
	if out != "removed twin directory /abs/local/twin\n" {
		t.Errorf("stdout %q, want what was removed even though something remains", out)
	}
	validateM2Document(t, doc)
}

// No service and no worker are exit 2 under their own identifiers, not a wait.
func TestDestroyStartRefusals(t *testing.T) {
	for _, c := range startRefusals() {
		t.Run(c.name, func(t *testing.T) {
			c.use(t)
			var err error
			out := captureStdout(t, func() { err = runDestroy(context.Background(), &options{asJSON: true}) })
			if out != "" {
				t.Errorf("--json printed lines on stdout:\n%s", out)
			}
			wantStartRefusal(t, err, c.rule)
		})
	}
}

// There is one twin, so destroy takes no argument: exit 2, and nothing is dialled.
func TestDestroyRefusesAnArgument(t *testing.T) {
	useService(t, nil)
	opts := &options{asJSON: true}
	root := &cobra.Command{Use: "fylgja", SilenceUsage: true, SilenceErrors: true}
	root.AddCommand(newTwinCmd(opts))
	root.SetArgs([]string{"twin", "destroy", "fylgja"})

	var code int
	out := captureStdout(t, func() {
		cmd, err := root.ExecuteC()
		code = report(opts, cmd, err)
	})
	if code != findings.ExitError {
		t.Errorf("exit %d, want 2", code)
	}
	var doc findings.Document
	if err := json.Unmarshal([]byte(out), &doc); err != nil {
		t.Fatalf("stdout is not one findings document: %v\n%s", err, out)
	}
	if doc.Operation != findings.OpTwinDestroy || doc.Status != findings.StatusError {
		t.Errorf("document %+v, want twin.destroy with status error", doc)
	}
}

func TestDestroyJSONDocumentCarriesTheCleanup(t *testing.T) {
	useService(t, &fakeService{destroyRun: destroyedRun(provision.CleanupResult{
		Teardown: provision.CleanupDone, Unstage: provision.CleanupDone,
		Removed: []string{"lab fylgja (3 containers)", "twin directory /abs/local/twin"},
	}, nil)})

	var err error
	out := captureStdout(t, func() { err = runDestroy(context.Background(), &options{asJSON: true}) })
	if out != "" {
		t.Errorf("--json printed lines on stdout:\n%s", out)
	}
	code, doc := exitOf(t, err)
	if code != findings.ExitOK || doc.Cleanup == nil || doc.Cleanup.Teardown != "done" || doc.Subject.RunID != "run-d" {
		t.Fatalf("exit %d, document %+v; want 0 with the cleanup block and the run id", code, doc)
	}
	validateM2Document(t, doc)
}

// Destroy stops following before it starts its run, says so before M2's lines, and reports
// the following it stopped (contracts/cli.md, step 1a).
func TestDestroyStopsFollowing(t *testing.T) {
	cleanup := provision.CleanupResult{Teardown: provision.CleanupDone, Unstage: provision.CleanupDone,
		Removed: []string{"lab fylgja (3 containers)", "twin directory /abs/local/twin"}}
	stop := provision.FollowStop{Stopped: true, Branch: "fylgja-fixture"}

	t.Run("text", func(t *testing.T) {
		svc := &fakeService{destroyRun: destroyedRun(cleanup, nil), stopResult: stop}
		useService(t, svc)
		var err error
		out := captureStdout(t, func() { err = runDestroy(context.Background(), &options{}) })
		if code, _ := exitOf(t, err); code != findings.ExitOK {
			t.Fatalf("exit %d, want 0", code)
		}
		if want := []string{"StopFollowing", "StartDestroy"}; !slices.Equal(svc.calls, want) {
			t.Errorf("calls %v, want %v", svc.calls, want)
		}
		want := "following of branch fylgja-fixture stopped\nremoved lab fylgja (3 containers)\nremoved twin directory /abs/local/twin\n"
		if out != want {
			t.Errorf("stdout:\n%s\nwant:\n%s", out, want)
		}
	})

	t.Run("json", func(t *testing.T) {
		useService(t, &fakeService{destroyRun: destroyedRun(cleanup, nil), stopResult: stop})
		var err error
		out := captureStdout(t, func() { err = runDestroy(context.Background(), &options{asJSON: true}) })
		if out != "" {
			t.Errorf("--json printed lines on stdout:\n%s", out)
		}
		code, doc := exitOf(t, err)
		if code != findings.ExitOK || doc.Following == nil || !doc.Following.Stopped || doc.Following.Branch != "fylgja-fixture" {
			t.Fatalf("exit %d, following %+v; want 0 with following of fylgja-fixture stopped", code, doc.Following)
		}
		validateM4Document(t, doc)
	})
}

// With no following, destroy says nothing about it and its document carries no block.
func TestDestroyNoFollowing(t *testing.T) {
	cleanup := provision.CleanupResult{Teardown: provision.CleanupNothing, Unstage: provision.CleanupNothing}
	for _, asJSON := range []bool{false, true} {
		svc := &fakeService{destroyRun: destroyedRun(cleanup, nil)}
		useService(t, svc)
		var err error
		out := captureStdout(t, func() { err = runDestroy(context.Background(), &options{asJSON: asJSON}) })
		code, doc := exitOf(t, err)
		if code != findings.ExitOK || doc.Following != nil {
			t.Errorf("json %v: exit %d, following %+v; want 0 and no following block", asJSON, code, doc.Following)
		}
		if strings.Contains(out, "following") {
			t.Errorf("json %v: stdout mentions following:\n%s", asJSON, out)
		}
		if want := []string{"StopFollowing", "StartDestroy"}; !slices.Equal(svc.calls, want) {
			t.Errorf("json %v: calls %v, want %v", asJSON, svc.calls, want)
		}
	}
}

// A check in flight is cancelled and its cleanup waited for; its notice and its child's
// cleanup lines are printed as they come, before the destroy's own.
func TestDestroyCancelsCheck(t *testing.T) {
	const check = "fylgja-reconcile-2026-09-16T19:10:00Z"
	svc := &fakeService{
		destroyRun: destroyedRun(provision.CleanupResult{Teardown: provision.CleanupNothing, Unstage: provision.CleanupNothing}, nil),
		stopResult: provision.FollowStop{Stopped: true, Branch: "fylgja-fixture", CheckCancelled: check},
		stopEvents: []provision.Event{
			{Notice: "cancelling check " + check + "; waiting for its cleanup"},
			{Notice: "run fylgja-provision run-p"},
			{Step: "cleanup teardown", End: true, Outcome: provision.EventDone, Duration: 2 * time.Second},
			{Step: "cleanup unstage", End: true, Outcome: provision.EventDone, Duration: time.Second},
			{Notice: "check " + check + " closed: cancelled"},
		},
	}
	useService(t, svc)

	var err error
	out := captureStdout(t, func() { err = runDestroy(context.Background(), &options{}) })
	if code, _ := exitOf(t, err); code != findings.ExitOK {
		t.Fatalf("exit %d, want 0", code)
	}
	want := "cancelling check " + check + "; waiting for its cleanup\n" +
		"run fylgja-provision run-p\n" +
		"cleanup teardown: done in 2.0s\n" +
		"cleanup unstage: done in 1.0s\n" +
		"check " + check + " closed: cancelled\n" +
		"following of branch fylgja-fixture stopped\n" +
		"nothing to remove: no lab fylgja, no twin directory\n"
	if out != want {
		t.Errorf("stdout:\n%s\nwant:\n%s", out, want)
	}
}

// A Schedule that cannot be deleted refuses the destroy: exit 2, follow.stop.failed saying
// nothing was removed, and no destroy run started.
func TestDestroyFollowStopFailed(t *testing.T) {
	refusal := &provision.StartError{Status: findings.StatusError, Finding: findings.Finding{
		Severity: findings.Rejection, Rule: findings.RuleFollowStopFailed, Object: provision.FollowScheduleID,
		Step:    findings.StepFollow,
		Message: provision.FollowStopFailedMessage(errors.New("connection refused"), "removed"),
	}}
	svc := &fakeService{stopErr: refusal}
	useService(t, svc)

	var err error
	out := captureStdout(t, func() { err = runDestroy(context.Background(), &options{asJSON: true}) })
	if out != "" {
		t.Errorf("--json printed lines on stdout:\n%s", out)
	}
	code, doc := exitOf(t, err)
	if code != findings.ExitError || doc.Operation != findings.OpTwinDestroy {
		t.Fatalf("exit %d, document %+v; want 2 from twin.destroy", code, doc)
	}
	if len(doc.Findings) != 1 {
		t.Fatalf("findings %+v, want follow.stop.failed alone", doc.Findings)
	}
	f := doc.Findings[0]
	wantMsg := "deleting schedule fylgja-follow failed (connection refused); nothing was removed, because a check could otherwise rebuild the twin"
	if f.Rule != findings.RuleFollowStopFailed || f.Step != findings.StepFollow || f.Object != provision.FollowScheduleID || f.Message != wantMsg {
		t.Errorf("finding %+v\nwant follow.stop.failed at follow on fylgja-follow: %q", f, wantMsg)
	}
	if svc.destroys != 0 || slices.Contains(svc.calls, "StartDestroy") {
		t.Errorf("calls %v, want no destroy run", svc.calls)
	}
	validateM4Document(t, doc)
}

// Following that stopped before a later part of the stop failed is still reported: the
// Schedule is gone, so a second destroy would have none to name. The destroy is not
// started, and the failure is operation.failed at step follow, exit 2.
func TestDestroyStopThenFails(t *testing.T) {
	stop := provision.FollowStop{Stopped: true, Branch: "fylgja-fixture"}
	stopErr := errors.New("listing checks in flight: connection refused")
	wantFailure := func(t *testing.T, err error, svc *fakeService) *findings.Document {
		t.Helper()
		code, doc := exitOf(t, err)
		if code != findings.ExitError || doc.Operation != findings.OpTwinDestroy || len(doc.Findings) != 1 {
			t.Fatalf("exit %d, document %+v; want 2 from twin.destroy with one finding", code, doc)
		}
		if f := doc.Findings[0]; f.Rule != findings.RuleOperationFailed || f.Step != findings.StepFollow ||
			!strings.Contains(f.Message, "connection refused") {
			t.Errorf("finding %+v, want operation.failed at follow naming the error", f)
		}
		if want := []string{"StopFollowing"}; !slices.Equal(svc.calls, want) {
			t.Errorf("calls %v, want %v: no destroy run", svc.calls, want)
		}
		return doc
	}

	t.Run("text", func(t *testing.T) {
		svc := &fakeService{stopResult: stop, stopErr: stopErr}
		useService(t, svc)
		var err error
		out := captureStdout(t, func() { err = runDestroy(context.Background(), &options{}) })
		wantFailure(t, err, svc)
		if want := "following of branch fylgja-fixture stopped\n"; out != want {
			t.Errorf("stdout:\n%s\nwant:\n%s", out, want)
		}
	})

	t.Run("json", func(t *testing.T) {
		svc := &fakeService{stopResult: stop, stopErr: stopErr}
		useService(t, svc)
		var err error
		out := captureStdout(t, func() { err = runDestroy(context.Background(), &options{asJSON: true}) })
		if out != "" {
			t.Errorf("--json printed lines on stdout:\n%s", out)
		}
		doc := wantFailure(t, err, svc)
		if doc.Following == nil || !doc.Following.Stopped || doc.Following.Branch != "fylgja-fixture" {
			t.Errorf("following %+v, want following of fylgja-fixture stopped", doc.Following)
		}
		validateM4Document(t, doc)
	})
}

// Following that a create began after destroy's first stop is stopped by the second, once no
// provisioning run is in flight: its line is printed once, as it comes and before the destroy
// run's, and the document's following block names it, the later branch when both stopped one
// (contracts/cli.md, step 2a).
func TestDestroyStopsFollowingAgain(t *testing.T) {
	cleanup := provision.CleanupResult{Teardown: provision.CleanupDone, Unstage: provision.CleanupDone,
		Removed: []string{"lab fylgja (3 containers)", "twin directory /abs/local/twin"}}
	secondStop := func(branch string) *fakeService {
		run := destroyedRun(cleanup, nil)
		run.FollowingStopped = provision.FollowStop{Stopped: true, Branch: branch}
		return &fakeService{destroyRun: run, destroyEvents: []provision.Event{
			{Notice: "following of branch " + branch + " stopped"},
			{Notice: "run fylgja-destroy run-d"},
		}}
	}

	t.Run("text", func(t *testing.T) {
		svc := secondStop("fylgja-fixture")
		useService(t, svc)
		var err error
		out := captureStdout(t, func() { err = runDestroy(context.Background(), &options{}) })
		if code, _ := exitOf(t, err); code != findings.ExitOK {
			t.Fatalf("exit %d, want 0", code)
		}
		if want := []string{"StopFollowing", "StartDestroy"}; !slices.Equal(svc.calls, want) {
			t.Errorf("calls %v, want %v", svc.calls, want)
		}
		if n := strings.Count(out, "following of branch fylgja-fixture stopped"); n != 1 {
			t.Errorf("the stop is printed %d times, want once:\n%s", n, out)
		}
		want := "following of branch fylgja-fixture stopped\nrun fylgja-destroy run-d\n" +
			"removed lab fylgja (3 containers)\nremoved twin directory /abs/local/twin\n"
		if out != want {
			t.Errorf("stdout:\n%s\nwant:\n%s", out, want)
		}
	})

	t.Run("json", func(t *testing.T) {
		for _, c := range []struct {
			name  string
			first provision.FollowStop
		}{
			{"the second stop alone", provision.FollowStop{}},
			{"both stops", provision.FollowStop{Stopped: true, Branch: "fylgja-old"}},
		} {
			t.Run(c.name, func(t *testing.T) {
				svc := secondStop("fylgja-fixture")
				svc.stopResult = c.first
				useService(t, svc)
				var err error
				out := captureStdout(t, func() { err = runDestroy(context.Background(), &options{asJSON: true}) })
				if out != "" {
					t.Errorf("--json printed lines on stdout:\n%s", out)
				}
				code, doc := exitOf(t, err)
				if code != findings.ExitOK || doc.Following == nil || !doc.Following.Stopped || doc.Following.Branch != "fylgja-fixture" {
					t.Fatalf("exit %d, following %+v; want 0 with following of fylgja-fixture stopped", code, doc.Following)
				}
				validateM4Document(t, doc)
			})
		}
	})
}

// A second stop that fails is a failure at step follow with no destroy run, as the first
// stop's is: a Schedule it cannot delete is follow.stop.failed, and a failure after it deleted
// one still names that following. A Schedule the first stop deleted is named beside any later
// failure to start, since a second destroy would find none.
func TestDestroySecondStopFails(t *testing.T) {
	stopped := provision.FollowStop{Stopped: true, Branch: "fylgja-fixture"}

	t.Run("a Schedule that cannot be deleted", func(t *testing.T) {
		refusal := &provision.StartError{Status: findings.StatusError, Finding: findings.Finding{
			Severity: findings.Rejection, Rule: findings.RuleFollowStopFailed, Object: provision.FollowScheduleID,
			Step:    findings.StepFollow,
			Message: provision.FollowStopFailedMessage(errors.New("connection refused"), "removed"),
		}}
		useService(t, &fakeService{destroyErr: &provision.FollowStopError{Err: refusal}})
		var err error
		out := captureStdout(t, func() { err = runDestroy(context.Background(), &options{asJSON: true}) })
		if out != "" {
			t.Errorf("--json printed lines on stdout:\n%s", out)
		}
		code, doc := exitOf(t, err)
		if code != findings.ExitError || len(doc.Findings) != 1 {
			t.Fatalf("exit %d, findings %+v; want 2 with follow.stop.failed alone", code, doc.Findings)
		}
		wantMsg := "deleting schedule fylgja-follow failed (connection refused); nothing was removed, because a check could otherwise rebuild the twin"
		if f := doc.Findings[0]; f.Rule != findings.RuleFollowStopFailed || f.Step != findings.StepFollow || f.Message != wantMsg {
			t.Errorf("finding %+v\nwant follow.stop.failed at follow: %q", f, wantMsg)
		}
		if doc.Following != nil {
			t.Errorf("following %+v, want none: nothing was stopped", doc.Following)
		}
		validateM4Document(t, doc)
	})

	for _, c := range []struct {
		name     string
		first    provision.FollowStop
		second   provision.FollowStop
		events   []provision.Event
		err      error
		wantStep string
		wantOut  string
	}{
		{"a failure after the second stop deleted one", provision.FollowStop{}, stopped,
			[]provision.Event{{Notice: "following of branch fylgja-fixture stopped"}},
			&provision.FollowStopError{Err: errors.New("listing checks in flight: connection refused")},
			findings.StepFollow, "following of branch fylgja-fixture stopped\n"},
		{"a failure to start after the first stop deleted one", stopped, provision.FollowStop{}, nil,
			errors.New("cancelling provisioning run run-p: connection refused"),
			findings.StepStart, "following of branch fylgja-fixture stopped\n"},
	} {
		t.Run(c.name, func(t *testing.T) {
			svc := &fakeService{stopResult: c.first, destroyRun: provision.DestroyRun{FollowingStopped: c.second},
				destroyEvents: c.events, destroyErr: c.err}
			useService(t, svc)
			var err error
			out := captureStdout(t, func() { err = runDestroy(context.Background(), &options{}) })
			if out != c.wantOut {
				t.Errorf("stdout:\n%s\nwant:\n%s", out, c.wantOut)
			}
			code, doc := exitOf(t, err)
			if code != findings.ExitError || len(doc.Findings) != 1 {
				t.Fatalf("exit %d, findings %+v; want 2 with one finding", code, doc.Findings)
			}
			if f := doc.Findings[0]; f.Rule != findings.RuleOperationFailed || f.Step != c.wantStep ||
				!strings.Contains(f.Message, "connection refused") {
				t.Errorf("finding %+v, want operation.failed at %s naming the error", f, c.wantStep)
			}
			if doc.Following == nil || !doc.Following.Stopped || doc.Following.Branch != "fylgja-fixture" {
				t.Errorf("following %+v, want following of fylgja-fixture stopped", doc.Following)
			}
			validateM4Document(t, doc)
		})
	}
}

// A step run in flight is cancelled after any provisioning run, and the destroy waits for its
// record: twin destroy prints both notices and the step run's own progress as they come, then
// proceeds as M3's, its document the destroy run's. A failure while waiting for the step run
// is a failure to start, not a step of the destroy's (contracts/cli.md).
func TestDestroyCancelsAStepRun(t *testing.T) {
	const step = "01a4c0de-0000-7000-8000-000000000004"
	events := []provision.Event{
		{Notice: "cancelling step run " + step + "; waiting for its record"},
		{WorkflowID: provision.WorkflowStep, Step: "readiness e1", End: true, Outcome: provision.EventCancelled,
			Duration: 12 * time.Second, FindingStep: findings.StepReadiness},
		{WorkflowID: provision.WorkflowStep, Step: "record", End: true, Outcome: provision.EventDone,
			Duration: 100 * time.Millisecond, FindingStep: findings.StepRecord},
		{Notice: "step run " + step + " closed: diverged"},
	}
	t.Run("proceeds", func(t *testing.T) {
		svc := &fakeService{destroyRun: destroyedRun(provision.CleanupResult{Teardown: provision.CleanupDone, Unstage: provision.CleanupDone,
			Removed: []string{"lab fylgja (3 containers)", "twin directory /abs/local/twin"}}, nil),
			destroyEvents: append(append([]provision.Event{}, events...), provision.Event{Notice: "run fylgja-destroy run-d"})}
		useService(t, svc)
		var err error
		out := captureStdout(t, func() { err = runDestroy(context.Background(), &options{}) })
		code, doc := exitOf(t, err)
		if code != findings.ExitOK || doc.Subject.RunID != "run-d" {
			t.Fatalf("exit %d, document %+v; want 0 from the destroy run", code, doc)
		}
		want := strings.Join([]string{
			"cancelling step run " + step + "; waiting for its record",
			"step readiness e1: cancelled after 12.0s",
			"step record: done in 0.1s",
			"step run " + step + " closed: diverged",
			"run fylgja-destroy run-d",
			"removed lab fylgja (3 containers)",
			"removed twin directory /abs/local/twin",
		}, "\n") + "\n"
		if out != want {
			t.Errorf("stdout:\n%s\nwant:\n%s", out, want)
		}
		validateM2Document(t, doc)
	})
	t.Run("waiting for it fails", func(t *testing.T) {
		boom := errors.New("waiting for step run " + step + ": the workflow service answered with an internal error")
		useService(t, &fakeService{destroyErr: boom, destroyEvents: events[:2]})
		code, doc := exitOf(t, runDestroy(context.Background(), &options{asJSON: true}))
		if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0].Step != findings.StepStart ||
			doc.Findings[0].Rule != findings.RuleOperationFailed {
			t.Errorf("exit %d, findings %+v; want 2, operation.failed at step start", code, doc.Findings)
		}
	})
}

// destroyCancellingACreate is what the workflow service's client gives twin destroy's
// follow when a provisioning run is in flight: its notices, the run's cleanup, then the
// destroy run's own steps (internal/provision/client.go).
func destroyCancellingACreate() []provision.Event {
	return []provision.Event{
		{Notice: "cancelling provisioning run run-p; waiting for its cleanup"},
		{WorkflowID: provision.WorkflowProvision, Step: "cleanup teardown", End: true, Outcome: provision.EventDone,
			Duration: 2 * time.Second, FindingStep: findings.StepTeardown},
		{Notice: "provisioning run run-p closed: cancelled"},
		{Notice: "run fylgja-destroy run-d"},
		{WorkflowID: provision.WorkflowDestroy, Step: "plan teardown", End: true, Outcome: provision.EventDone,
			Duration: 100 * time.Millisecond, FindingStep: findings.StepTeardown},
		{WorkflowID: provision.WorkflowDestroy, Step: "unstage", End: true, Outcome: provision.EventDone,
			Duration: 100 * time.Millisecond, FindingStep: findings.StepUnstage},
	}
}

// twin destroy through the API: one request, followed to the destroy run's
// end, which takes no interrupt. The
// client names no stream for it and arms nothing, even beside a start frame, so an
// interrupt queued while it runs is never sent and stays the process's; a create in flight
// that the destroy cancels is announced in M12's words, and the document names the destroy
// run.
func TestDestroyThroughTheAPI(t *testing.T) {
	t.Run("the client names no stream and sends no interrupt", func(t *testing.T) {
		fake := newAPIFake(t, func(w *fakeAnswer, op string, _ api.Request) {
			// The server writes a destroy's start frame too, and the client
			// arms nothing for a request that named no stream, whatever comes back.
			w.frame(api.Frame{Start: &api.RunRef{WorkflowID: provision.WorkflowDestroy}})
			time.Sleep(50 * time.Millisecond)
			w.document(okDocument(op), "")
		})
		queued := useInterrupts(t)
		queued <- os.Interrupt

		printedBy(t, func() { sentDocument(t, runDestroy(context.Background(), &options{})) })

		seen := fake.seen()
		if len(seen) != 1 || seen[0].op != findings.OpTwinDestroy || seen[0].stream != "" {
			t.Errorf("requests %+v; want one twin.destroy naming no stream", seen)
		}
		fake.mu.Lock()
		defer fake.mu.Unlock()
		if len(fake.interrupts) != 0 || len(queued) != 1 {
			t.Errorf("%d interrupts sent, %d left queued; want none sent and the one queued left", len(fake.interrupts), len(queued))
		}
	})

	t.Run("cancelling a create in flight", func(t *testing.T) {
		svc := &fakeService{destroyRun: destroyedRun(provision.CleanupResult{Teardown: provision.CleanupDone,
			Unstage: provision.CleanupDone, Removed: []string{"lab fylgja (3 containers)", "twin directory /abs/local/twin"}}, nil),
			destroyEvents: destroyCancellingACreate()}
		useService(t, svc)
		queued := useInterrupts(t)
		queued <- os.Interrupt
		before := len(requestOutcomes("interrupt"))

		var err error
		out := captureStdout(t, func() { err = runDestroy(context.Background(), &options{}) })

		code, doc := exitOf(t, err)
		if code != findings.ExitOK || doc.Subject == nil || doc.Subject.RunID != "run-d" {
			t.Fatalf("exit %d, document %+v; want 0 naming the destroy run run-d", code, doc)
		}
		want := strings.Join([]string{
			"cancelling provisioning run run-p; waiting for its cleanup",
			"cleanup teardown: done in 2.0s",
			"provisioning run run-p closed: cancelled",
			"run fylgja-destroy run-d",
			"step plan teardown: done in 0.1s",
			"step unstage: done in 0.1s",
			"removed lab fylgja (3 containers)",
			"removed twin directory /abs/local/twin",
		}, "\n") + "\n"
		if out != want {
			t.Errorf("stdout:\n%s\nwant:\n%s", out, want)
		}
		if len(queued) != 1 || len(requestOutcomes("interrupt")) != before {
			t.Errorf("%d left queued, %d interrupts logged; want the queued one left and none sent",
				len(queued), len(requestOutcomes("interrupt"))-before)
		}
		if svc.cancels != 0 || svc.destroys != 1 {
			t.Errorf("Cancel called %d times, destroys %d; want the destroy's own cancel alone", svc.cancels, svc.destroys)
		}
		validateM2Document(t, doc)
	})
}
