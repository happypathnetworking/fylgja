package cli

import (
	"encoding/json"
	"strings"
	"testing"
	"time"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/provision"
)

// runCommandLine runs `fylgja <args>` through a root holding every client's command, as an
// operator would, and returns its exit status, its stdout and its stderr.
func runCommandLine(t *testing.T, args ...string) (int, string, string) {
	t.Helper()
	opts := &options{}
	root := &cobra.Command{Use: "fylgja", SilenceUsage: true, SilenceErrors: true}
	root.PersistentFlags().BoolVar(&opts.asJSON, "json", false, "")
	root.AddCommand(newTwinCmd(opts), newIntentCmd(opts), newStageCmd(opts), newSchemaCmd(opts), newPSPCmd(opts), newRunCmd(opts))
	root.SetArgs(args)
	var code int
	var stdout string
	stderr := captureStderr(t, func() {
		stdout = captureStdout(t, func() {
			cmd, err := root.ExecuteC()
			code = report(opts, cmd, err)
		})
	})
	return code, stdout, stderr
}

// Quickstart §3's five lines (020; US4 scenarios 1–4), through the command line and the
// harness's server: a create from a stored snapshot under --detach ends at its run, exit 0,
// printing what it filed and the run.detached line; fylgja run read of the running run prints
// its state and its steps so far, as the followed create printed them, and exits 0 with no
// document, --json printing nothing; fylgja run interrupt asks it to cancel, exit 0,
// run.cancel.requested; once it has ended, fylgja run read --json prints the document the
// stream would have, under run.read, the run's own status; and a run id the workflow holds
// no run under is run.unknown, exit 1, naming it.
func TestADetachedRunIsReadAndInterruptedByItsIdentity(t *testing.T) {
	paths := useStateRoot(t)
	useInterrupts(t)
	storeFixtureSnapshot(t, paths)
	cancelled := provision.ProvisionResult{Outcome: provision.OutcomeCancelled, BundleID: fixtureBundleID, Step: findings.StepDeploy,
		Findings: findings.List{}, Cleanup: provision.CleanupResult{Teardown: provision.CleanupDone, Unstage: provision.CleanupDone,
			Removed: []string{"lab fylgja (3 containers)", "twin directory /abs/local/twin"}}}
	svc := &fakeService{runID: "run-1", result: cancelled, events: []provision.Event{
		{WorkflowID: provision.WorkflowProvision, Step: "host check", FindingStep: findings.StepHostCheck},
		{WorkflowID: provision.WorkflowProvision, Step: "host check", FindingStep: findings.StepHostCheck, End: true,
			Outcome: provision.EventDone, Duration: 300 * time.Millisecond},
		{WorkflowID: provision.WorkflowProvision, Step: "deploy", FindingStep: findings.StepDeploy},
	}}
	svc.onCancel = func() {
		svc.describe(provision.RunState{WorkflowID: provision.WorkflowProvision, RunID: "run-1", State: provision.RunCompleted})
	}
	useService(t, svc)

	// 1. bin/fylgja twin create --snapshot <id> --detach
	code, stdout, stderr := runCommandLine(t, "twin", "create", "--snapshot", fixtureSnapshotID, "--detach")
	if want := strings.Join(storedLines(paths, fixtureSnapshotID, fixtureBundleID), "\n") + "\n"; code != findings.ExitOK || stdout != want {
		t.Errorf("create --detach: exit %d, stdout\n%s\nwant 0 and\n%s", code, stdout, want)
	}
	if !strings.Contains(stderr, "run fylgja-provision run-1 started; read it with fylgja run read") {
		t.Errorf("create --detach: stderr\n%s\nwant the run.detached line", stderr)
	}
	if len(svc.started) != 1 {
		t.Fatalf("started %+v, want one run", svc.started)
	}

	// 2. bin/fylgja run read --workflow fylgja-provision
	svc.describe(provision.RunState{WorkflowID: provision.WorkflowProvision, RunID: "run-1", State: provision.RunRunning})
	code, stdout, stderr = runCommandLine(t, "run", "read", "--workflow", provision.WorkflowProvision)
	want := "run fylgja-provision run-1: running\nstep host check: begins\nstep host check: done in 0.3s\nstep deploy: begins\n"
	if code != findings.ExitOK || stdout != want || stderr != "" {
		t.Errorf("run read, running: exit %d, stdout\n%s\nstderr\n%s\nwant 0 and\n%s", code, stdout, stderr, want)
	}
	if code, stdout, _ = runCommandLine(t, "run", "read", "--workflow", provision.WorkflowProvision, "--json"); code != findings.ExitOK || stdout != "" {
		t.Errorf("run read --json, running: exit %d, stdout\n%s\nwant 0 and nothing", code, stdout)
	}

	// 3. bin/fylgja run interrupt --workflow fylgja-provision
	code, _, stderr = runCommandLine(t, "run", "interrupt", "--workflow", provision.WorkflowProvision)
	if code != findings.ExitOK || !strings.Contains(stderr, findings.RuleRunCancelRequested) || svc.cancels != 1 {
		t.Errorf("run interrupt: exit %d, %d cancels, stderr\n%s\nwant 0, one cancel and run.cancel.requested", code, svc.cancels, stderr)
	}

	// 4. bin/fylgja run read --workflow fylgja-provision --json, once ended
	code, stdout, _ = runCommandLine(t, "run", "read", "--workflow", provision.WorkflowProvision, "--json")
	var doc findings.Document
	if err := json.Unmarshal([]byte(stdout), &doc); err != nil {
		t.Fatalf("run read --json, ended: stdout is not one document: %v\n%s", err, stdout)
	}
	if code != findings.ExitFailed || doc.Operation != findings.OpRunRead || doc.Status != findings.StatusFailed ||
		doc.Subject.RunID != "run-1" {
		t.Errorf("run read --json, ended: exit %d, document %+v; want 3, run.read, failed, naming run-1", code, doc)
	}
	// run.read is 020's operation, which no frozen contract holds.
	validateWithShow(t, currentContract, "020", &doc)

	// 5. bin/fylgja run read --workflow fylgja-provision --run 00000000-…
	const gone = "00000000-0000-0000-0000-000000000000"
	code, stdout, _ = runCommandLine(t, "run", "read", "--workflow", provision.WorkflowProvision, "--run", gone, "--json")
	doc = findings.Document{}
	if err := json.Unmarshal([]byte(stdout), &doc); err != nil {
		t.Fatalf("run read of no run: stdout is not one document: %v\n%s", err, stdout)
	}
	if code != findings.ExitRejected || len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleRunUnknown ||
		!strings.Contains(doc.Findings[0].Object, gone) {
		t.Errorf("run read of no run: exit %d, findings %+v; want run.unknown naming %s, exit 1", code, doc.Findings, gone)
	}
}
