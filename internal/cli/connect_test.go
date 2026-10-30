package cli

import (
	"context"
	"encoding/json"
	"errors"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/provision"
)

// Every refusal M2–M12 make "before any connection" is the server's, made before it connects
// to the workflow service, in M12's words: it is never dialled. From 020 the server reads no
// source of truth (D-065). Like
// answer_test.go, these live beside the harness, whose
// fakes are this package's test code.

// countDials makes the server's dial count its calls and fail, as a workflow service that
// does not answer fails.
func countDials(t *testing.T) *atomic.Int32 {
	t.Helper()
	return countDialsTo(t, nil)
}

// countDialsTo is countDials answered by svc, or unreachable when svc is nil.
func countDialsTo(t *testing.T, svc provision.Service) *atomic.Int32 {
	t.Helper()
	var n atomic.Int32
	saved := dialService
	t.Cleanup(func() { dialService = saved })
	dialService = func(context.Context) (provision.Service, error) {
		n.Add(1)
		if svc != nil {
			return svc, nil
		}
		return nil, &provision.UnreachableError{Address: "localhost:7233", Err: errors.New("connection refused")}
	}
	return &n
}

// executeClient runs a client's command line with --json through a root holding every
// client's command, and returns its exit status, its document and the document as printed.
func executeClient(t *testing.T, args ...string) (int, *findings.Document, string) {
	t.Helper()
	opts := &options{}
	root := &cobra.Command{Use: "fylgja", SilenceUsage: true, SilenceErrors: true}
	root.PersistentFlags().BoolVar(&opts.asJSON, "json", false, "")
	root.AddCommand(newTwinCmd(opts), newIntentCmd(opts), newStageCmd(opts), newSchemaCmd(opts), newPSPCmd(opts), newRunCmd(opts))
	root.SetArgs(append(args, "--json"))
	var code int
	out := captureStdout(t, func() {
		cmd, err := root.ExecuteC()
		code = report(opts, cmd, err)
	})
	var doc findings.Document
	if err := json.Unmarshal([]byte(out), &doc); err != nil {
		t.Fatalf("%v: stdout is not one findings document: %v\n%s", args, err, out)
	}
	return code, &doc, out
}

// servedRequests counts the requests the harness's server logged for op ending outcome.
func servedRequests(op, outcome string) int {
	return strings.Count(harness.log.String(), "msg=request operation="+op+" outcome="+outcome+" ")
}

// The refusals before any connection, each through the command line to the harness's
// server: one document, M12's finding word for word, exit 2 or 1 as at M12, and the workflow
// service never dialled. The server logged the request, so the refusal is the server's and
// not the client's.
func TestRefusalsBeforeAnyConnectionAreTheServers(t *testing.T) {
	refusal := func(rule, step, object, message string) findings.Finding {
		return findings.Finding{Severity: findings.Rejection, Rule: rule, Step: step, Object: object, Message: message}
	}
	type refusalCase struct {
		name string
		args []string
		// step, when set, builds the snapshot twin for twin step's cases.
		step bool
		want findings.Finding
		code int
	}
	cases := []refusalCase{
		// twin create (M1; 020: a create builds from a snapshot alone, D-065).
		{name: "create with no --snapshot", args: []string{"twin", "create"},
			want: refusal(findings.RuleOperationFailed, "", findings.OpTwinCreate, "--snapshot is required")},

		// twin step (M11, M12; 020: a step names its target).
		{name: "step with --wait=", args: []string{"twin", "step", "--allow-restart", "--wait="}, step: true,
			want: refusal(findings.RuleVerifyWaitInvalid, findings.StepStart, "--wait",
				"--wait= is empty; give a duration such as --wait=2m, or leave --wait out for the default 2m0s")},
		{name: "step --dry-run with --wait banana", args: []string{"twin", "step", "--allow-restart", "--wait", "banana", "--dry-run"}, step: true,
			want: refusal(findings.RuleVerifyWaitInvalid, findings.StepStart, "--wait", `--wait=banana is not a duration: time: invalid duration "banana"`)},
		{name: "step with no --snapshot", args: []string{"twin", "step", "--allow-restart"}, step: true, code: findings.ExitRejected,
			want: refusal(findings.RuleStepTargetUnknown, findings.StepResolve, "--snapshot", noTargetMessage)},

		// twin verify (M12).
		{name: "verify with --wait=", args: []string{"twin", "verify", "--wait="},
			want: refusal(findings.RuleVerifyWaitInvalid, findings.StepStart, "--wait",
				"--wait= is empty; give a duration such as --wait=2m, or --wait alone for the default 2m0s")},
		{name: "verify with a negative --wait", args: []string{"twin", "verify", "--wait=-5s"},
			want: refusal(findings.RuleVerifyWaitInvalid, findings.StepStart, "--wait", "--wait=-5s is not a duration: a budget cannot be negative")},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if c.step {
				stepHost(t, "plan-link-added.json", nil)
			} else {
				useStateRoot(t)
			}
			dials := countDials(t)
			want := c.code
			if want == 0 {
				want = findings.ExitError
			}
			op := strings.Join(c.args[:2], ".")
			status := findings.StatusError
			if want == findings.ExitRejected {
				status = findings.StatusRejected
			}
			awaitIdle(t)
			served := servedRequests(op, string(status))

			code, doc, raw := executeClient(t, c.args...)
			if code != want || doc.Status != status || len(doc.Findings) != 1 || doc.Findings[0] != c.want {
				t.Errorf("exit %d, status %s, findings %+v\nwant exit %d, %s, with %+v alone", code, doc.Status, doc.Findings, want, status, c.want)
			}
			if n := dials.Load(); n != 0 {
				t.Errorf("the workflow service was dialled %d times before the refusal, want none", n)
			}
			awaitIdle(t)
			if got := servedRequests(op, string(status)) - served; got != 1 {
				t.Errorf("the server logged %d requests of %s ending %s, want 1: the refusal is the server's", got, op, status)
			}
			validateM10Document(t, doc)
			if strings.Contains(raw, harness.token) {
				t.Errorf("%s's document carries the API's token", op)
			}
		})
	}
}

// What each command needed at M12 it still needs, with the server in the CLI's place:
// twin show answers for the host and the record with the workflow service
// unreachable, inside its budget, exit 0; twin verify reads the twin with it unreachable,
// exit 0 with M12's warning; and psp validate and twin compile answer with it unreachable.
func TestEachCommandNeedsWhatItNeededAtM12(t *testing.T) {
	refused := &provision.UnreachableError{Address: "localhost:7233", Err: errors.New("connection refused")}
	unreachableDial := func(t *testing.T) {
		saved := dialService
		t.Cleanup(func() { dialService = saved })
		dialService = func(context.Context) (provision.Service, error) { return nil, refused }
	}

	t.Run("twin show", func(t *testing.T) {
		paths := useStateRoot(t)
		writeTwin(t, paths, twinOf(t, nil))
		unreachableDial(t)
		began := time.Now()
		out := showDialled(t, paths, "inspect-three.json")
		if took := time.Since(began); took > 2*showServiceBudget {
			t.Errorf("twin show took %s in text and JSON, past twice its budget of %s", took, showServiceBudget)
		}
		if out.code != findings.ExitOK || out.doc.Show == nil || out.doc.Show.Service != findings.ShowServiceUnreachable ||
			!out.doc.Show.Host.LabPresent || out.doc.Show.Record == nil {
			t.Errorf("exit %d, show %+v; want 0 with the host, the record and the service unreachable", out.code, out.doc.Show)
		}
		if !strings.HasPrefix(out.stdout, threeNodes+recordLine) {
			t.Errorf("stdout:\n%s\nwant the host and the record first", out.stdout)
		}
	})
	t.Run("twin verify", func(t *testing.T) {
		h := verifyHost(t, "three-node", nil, nil)
		unreachableDial(t)
		out := runVerify(t, h.paths.Root, func() *fakeNodes { return h.healthy(t) })
		want := findings.Finding{Severity: findings.Warning, Rule: findings.RuleShowServiceUnreachable, Object: provision.DefaultAddress,
			Message: "workflow service unreachable at " + provision.DefaultAddress + " (connection refused); whether a run is in flight is unknown"}
		if out.code != findings.ExitOK || len(out.doc.Findings) != 1 || out.doc.Findings[0] != want || out.doc.Verify == nil {
			t.Errorf("exit %d, findings %+v; want 0, the verify block, and %+v alone", out.code, out.doc.Findings, want)
		}
	})
	t.Run("psp validate", func(t *testing.T) {
		useService(t, nil)
		code, doc, raw := executeClient(t, "psp", "validate", repoPath("psp", "nokia_srlinux.yaml"), repoPath("psp", "arista_eos.yaml"))
		if code != findings.ExitOK || len(doc.Findings) != 0 {
			t.Errorf("exit %d, %s; want 0 with no finding", code, raw)
		}
	})
	t.Run("twin compile", func(t *testing.T) {
		useService(t, nil)
		out := filepath.Join(t.TempDir(), "b")
		code, doc, raw := executeClient(t, "twin", "compile", "--snapshot", wrappedFixture("three-node"), "--out", out)
		if code != findings.ExitOK || doc.BundleID != fixtureBundleID {
			t.Errorf("exit %d, %s; want 0 and bundle_id %s", code, raw, fixtureBundleID)
		}
	})
}
