package server

import (
	"bytes"
	"encoding/json"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/provision"
)

// Every way a run can end maps to exactly one exit status and status word
// (contracts/cli.md), and every document says so in M2's contract.
func TestExitStatusForEveryOutcome(t *testing.T) {
	skipped := provision.CleanupResult{Teardown: provision.CleanupSkipped, Unstage: provision.CleanupSkipped}
	clean := provision.CleanupResult{Teardown: provision.CleanupDone, Unstage: provision.CleanupDone,
		Removed: []string{"lab fylgja (3 containers)", "twin directory /abs/local/twin"}}
	unclean := provision.CleanupResult{Teardown: provision.CleanupFailed, Unstage: provision.CleanupDone,
		Removed: []string{"twin directory /abs/local/twin"}, Remaining: []string{"lab fylgja"}}
	finding := func(step string, rules ...string) findings.List {
		l := findings.List{}
		for _, rule := range rules {
			l.AddStep(findings.Rejection, step, rule, "object", "message")
		}
		return l
	}
	stopped := func(outcome, step string, c provision.CleanupResult, list findings.List) provision.ProvisionResult {
		return provision.ProvisionResult{Outcome: outcome, BundleID: fixtureBundleID, Step: step, Findings: list, Cleanup: c}
	}
	subject := func() *findings.Subject { return &findings.Subject{Branch: "fylgja-fixture", RunID: "run-1"} }

	for _, c := range []struct {
		name   string
		doc    func() *findings.Document
		code   int
		status findings.Status
	}{
		{"ready", provisionDoc(t, readyResult()), findings.ExitOK, findings.StatusOK},
		{"rejected", provisionDoc(t, stopped(provision.OutcomeRejected, findings.StepHostCheck, skipped,
			finding(findings.StepHostCheck, findings.RuleHostLabPresent))), findings.ExitRejected, findings.StatusRejected},
		{"error", provisionDoc(t, stopped(provision.OutcomeError, findings.StepRead, skipped,
			finding(findings.StepRead, findings.RuleOperationFailed))), findings.ExitError, findings.StatusError},
		{"cancelled before the host check", provisionDoc(t, stopped(provision.OutcomeCancelled, findings.StepCompile, skipped,
			findings.List{})), findings.ExitError, findings.StatusError},
		{"cancelled after the host check, clean", provisionDoc(t, stopped(provision.OutcomeCancelled, findings.StepDeploy, clean,
			findings.List{})), findings.ExitFailed, findings.StatusFailed},
		{"cancelled after the host check, something remains", provisionDoc(t, stopped(provision.OutcomeCancelled, findings.StepDeploy, unclean,
			finding(findings.StepTeardown, findings.RuleCleanupIncomplete))), findings.ExitUnclean, findings.StatusUnclean},
		{"failed, clean", provisionDoc(t, stopped(provision.OutcomeFailed, findings.StepDeploy, clean,
			finding(findings.StepDeploy, findings.RuleDeployFailed))), findings.ExitFailed, findings.StatusFailed},
		{"failed, something remains", provisionDoc(t, stopped(provision.OutcomeFailed, findings.StepReadiness, unclean,
			append(finding(findings.StepReadiness, findings.RuleReadinessTimeout), finding(findings.StepTeardown, findings.RuleCleanupIncomplete)...))),
			findings.ExitUnclean, findings.StatusUnclean},
		{"destroy, nothing remains", func() *findings.Document {
			return provision.DestroyDocument(subject(), provision.DestroyResult{Cleanup: clean, Findings: findings.List{}}, provision.FollowStop{})
		}, findings.ExitOK, findings.StatusOK},
		{"destroy, something remains", func() *findings.Document {
			return provision.DestroyDocument(subject(), provision.DestroyResult{Cleanup: unclean,
				Findings: finding(findings.StepTeardown, findings.RuleCleanupIncomplete)}, provision.FollowStop{})
		}, findings.ExitUnclean, findings.StatusUnclean},
	} {
		t.Run(c.name, func(t *testing.T) {
			doc := c.doc()
			var stdout, stderr bytes.Buffer
			code := findings.Render(doc, &stdout, &stderr, true)
			if code != c.code {
				t.Errorf("exit %d, want %d", code, c.code)
			}
			var rendered struct {
				Status findings.Status `json:"status"`
			}
			if err := json.Unmarshal(stdout.Bytes(), &rendered); err != nil {
				t.Fatalf("--json output is not a document: %v\n%s", err, stdout.Bytes())
			}
			if rendered.Status != c.status {
				t.Errorf("status %q, want %q", rendered.Status, c.status)
			}
			validateM5Document(t, doc) // a ready twin names its artifacts: M5's contract, which is additive over M2's
		})
	}
}

// provisionDoc is the document twin create reports for res, as the command builds it.
func provisionDoc(t *testing.T, res provision.ProvisionResult) func() *findings.Document {
	return func() *findings.Document {
		t.Helper()
		var out *result
		err := provisionReport(testOptions(t, true), findings.OpTwinCreate,
			&findings.Subject{Branch: "fylgja-fixture", RunID: "run-1"}, provision.ProvisionInput{}, res)
		if !asResult(err, &out) {
			t.Fatalf("provisionReport returned %v, want a findings result", err)
		}
		return out.doc
	}
}
