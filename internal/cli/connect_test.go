package cli

import (
	"context"
	"encoding/json"
	"errors"
	"net"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/provision"
)

// Every refusal M2–M12 make "before any connection" is the server's, made before it connects
// to Infrahub or the workflow service, in M12's words: neither is ever dialled. Like
// answer_test.go, these live beside the harness, whose
// fakes are this package's test code.

// countDials makes the server's dial count its calls and fail, as a workflow service that
// does not answer fails.
func countDials(t *testing.T) *atomic.Int32 {
	t.Helper()
	var n atomic.Int32
	saved := dialService
	t.Cleanup(func() { dialService = saved })
	dialService = func(context.Context) (provision.Service, error) {
		n.Add(1)
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
	root.AddCommand(newTwinCmd(opts), newIntentCmd(opts), newWaypointCmd(opts), newSchemaCmd(opts), newPSPCmd(opts))
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
// server: one document, M12's finding word for word, exit 2 or 1 as at M12, and neither the
// workflow service dialled nor Infrahub asked. The server logged the request, so the refusal
// is the server's and not the client's.
func TestRefusalsBeforeAnyConnectionAreTheServers(t *testing.T) {
	const notARef = `is not a waypoint reference: expected <series>/<sequence>, a series with no "/" and no whitespace and a positive integer`
	const tooPrecise = "2026-09-15T14:22:12.1234567Z"
	refusal := func(rule, step, object, message string) findings.Finding {
		return findings.Finding{Severity: findings.Rejection, Rule: rule, Step: step, Object: object, Message: message}
	}
	for _, c := range []struct {
		name string
		args []string
		// step, when set, builds the waypoint twin of steps/1 for twin step's cases.
		step bool
		want findings.Finding
		code int
		// asked is whether Infrahub is asked before the refusal: a target refused before the
		// workflow service, by what Infrahub names.
		asked bool
	}{
		// twin create (M1, M4, M10).
		{name: "create with neither --branch nor --waypoint", args: []string{"twin", "create"},
			want: refusal(findings.RuleOperationFailed, "", findings.OpTwinCreate, "--branch or --waypoint is required")},
		{name: "create with an at finer than microseconds", args: []string{"twin", "create", "--branch", "fylgja-fixture", "--at", tooPrecise},
			want: refusal(findings.RuleAtPrecision, "", tooPrecise, "at "+tooPrecise+" carries 7 fractional digits; "+
				"Infrahub honours at most 6 (microseconds). Re-run with a coarser --at.")},
		{name: "create with --interval=", args: []string{"twin", "create", "--branch", "fylgja-fixture", "--interval="},
			want: refusal(findings.RuleFollowIntervalInvalid, findings.StepStart, "", `--interval  is not a duration: time: invalid duration ""`)},
		{name: "create with --interval below the floor", args: []string{"twin", "create", "--branch", "fylgja-fixture", "--interval", "5s"},
			want: refusal(findings.RuleFollowIntervalInvalid, findings.StepStart, "5s", "--interval 5s is below the floor 10s")},
		{name: "create with --interval and --at", args: []string{"twin", "create", "--branch", "fylgja-fixture", "--at", "2026-09-16T14:00:00Z", "--interval", "1m"},
			want: refusal(findings.RuleFollowFlagsConflict, findings.StepStart, "--interval", "--interval is meaningless with --at: a pinned twin never follows")},
		{name: "create with --interval and --no-follow", args: []string{"twin", "create", "--branch", "fylgja-fixture", "--no-follow", "--interval", "1m"},
			want: refusal(findings.RuleFollowFlagsConflict, findings.StepStart, "--interval", "--interval is meaningless with --no-follow: the twin will not follow")},
		{name: "create with an invalid waypoint reference", args: []string{"twin", "create", "--waypoint", "demo"},
			want: refusal(findings.RuleWaypointRefInvalid, findings.StepStart, "demo", `--waypoint "demo" `+notARef)},
		{name: "create with --waypoint=", args: []string{"twin", "create", "--waypoint="},
			want: refusal(findings.RuleWaypointRefInvalid, findings.StepStart, "", `--waypoint "" `+notARef)},
		{name: "create --dry-run with --waypoint= beside --branch", args: []string{"twin", "create", "--branch", "fylgja-fixture", "--waypoint=", "--dry-run"},
			want: refusal(findings.RuleWaypointRefInvalid, findings.StepStart, "", `--waypoint "" `+notARef)},
		{name: "create with --waypoint and --branch", args: []string{"twin", "create", "--waypoint", "demo/2", "--branch", "change-1"},
			want: refusal(findings.RuleWaypointFlagsConflict, findings.StepStart, "--branch",
				"--branch is meaningless with --waypoint: a waypoint is a whole pinned reference (branch and at)")},

		// intent read and schema check (M1, M10).
		{name: "read with neither --branch nor --waypoint", args: []string{"intent", "read", "--out", "x.json"},
			want: refusal(findings.RuleOperationFailed, "", findings.OpIntentRead, "--branch or --waypoint is required")},
		{name: "read with --waypoint=", args: []string{"intent", "read", "--waypoint=", "--out", "x.json"},
			want: refusal(findings.RuleWaypointRefInvalid, "", "", `--waypoint "" `+notARef)},
		{name: "check with no --branch", args: []string{"schema", "check"},
			want: refusal(findings.RuleOperationFailed, "", findings.OpSchemaCheck, "--branch is required")},

		// waypoint list and plan (M10).
		{name: "list with a series holding a slash", args: []string{"waypoint", "list", "--series=a/b"},
			want: refusal(findings.RuleWaypointRefInvalid, findings.StepStart, "a/b", `--series "a/b" is not a waypoint series: expected a series with no "/" and no whitespace`)},
		{name: "plan with --series=", args: []string{"waypoint", "plan", "--series="},
			want: refusal(findings.RuleWaypointRefInvalid, findings.StepStart, "", `--series "" is not a waypoint series: expected a series with no "/" and no whitespace`)},
		{name: "plan with no --series", args: []string{"waypoint", "plan"},
			want: refusal(findings.RuleOperationFailed, "", findings.OpWaypointPlan, "--series is required")},

		// twin step (M11, M12).
		{name: "step with --wait=", args: []string{"twin", "step", "--allow-restart", "--wait="}, step: true,
			want: refusal(findings.RuleVerifyWaitInvalid, findings.StepStart, "--wait",
				"--wait= is empty; give a duration such as --wait=2m, or leave --wait out for the default 2m0s")},
		{name: "step --dry-run with --wait banana", args: []string{"twin", "step", "--allow-restart", "--wait", "banana", "--dry-run"}, step: true,
			want: refusal(findings.RuleVerifyWaitInvalid, findings.StepStart, "--wait", `--wait=banana is not a duration: time: invalid duration "banana"`)},
		{name: "step with --waypoint=", args: []string{"twin", "step", "--waypoint="}, step: true,
			want: refusal(findings.RuleWaypointRefInvalid, findings.StepStart, "", `--waypoint "" `+notARef)},
		{name: "step to a sequence the series lacks", args: []string{"twin", "step", "--waypoint", "steps/7"}, step: true,
			code: findings.ExitRejected, asked: true,
			want: refusal(findings.RuleStepTargetUnknown, findings.StepResolve, "steps/7", "series steps has no waypoint 7; its sequences are 1, 2, 3, 4, 5, 6")},
		{name: "step to the current waypoint", args: []string{"twin", "step", "--waypoint", "steps/1"}, step: true,
			code: findings.ExitRejected, asked: true,
			want: refusal(findings.RuleStepTargetCurrent, findings.StepResolve, "steps/1", "the twin is already at waypoint steps/1; series steps's sequences are 1, 2, 3, 4, 5, 6")},

		// twin verify (M12).
		{name: "verify with --wait=", args: []string{"twin", "verify", "--wait="},
			want: refusal(findings.RuleVerifyWaitInvalid, findings.StepStart, "--wait",
				"--wait= is empty; give a duration such as --wait=2m, or --wait alone for the default 2m0s")},
		{name: "verify with a negative --wait", args: []string{"twin", "verify", "--wait=-5s"},
			want: refusal(findings.RuleVerifyWaitInvalid, findings.StepStart, "--wait", "--wait=-5s is not a duration: a budget cannot be negative")},
	} {
		t.Run(c.name, func(t *testing.T) {
			var infra *fakeInfrahub
			before := 0
			if c.step {
				h := stepHost(t, "plan-link-added.json", nil)
				infra, before = h.infra, h.before
			} else {
				useStateRoot(t)
				infra = seriesInfrahub(t)
				infra.start()
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
				t.Errorf("the workflow service was dialled %d times before the refusal", n)
			}
			if asked := len(infra.requests()) > before; asked != c.asked {
				t.Errorf("Infrahub asked before the refusal: %v, want %v (%+v)", asked, c.asked, infra.requests()[before:])
			}
			awaitIdle(t)
			if got := servedRequests(op, string(status)) - served; got != 1 {
				t.Errorf("the server logged %d requests of %s ending %s, want 1: the refusal is the server's", got, op, status)
			}
			validateM10Document(t, doc)
			mustCarryNoToken(t, op, raw)
		})
	}
}

// What each command needed at M12 it still needs, with the server in the CLI's place:
// twin show answers for the host and the record with the workflow service
// unreachable, inside its budget, exit 0; twin verify reads the twin with it unreachable,
// exit 0 with M12's warning; waypoint list and plan answer without dialling it at all; and
// psp validate and twin compile answer with neither it nor Infrahub reachable.
func TestEachCommandNeedsWhatItNeededAtM12(t *testing.T) {
	refused := &provision.UnreachableError{Address: "localhost:7233", Err: errors.New("connection refused")}
	unreachableDial := func(t *testing.T) {
		saved := dialService
		t.Cleanup(func() { dialService = saved })
		dialService = func(context.Context) (provision.Service, error) { return nil, refused }
	}
	// closedInfrahub points Infrahub's variables at a port nothing listens on.
	closedInfrahub := func(t *testing.T) {
		ln, err := net.Listen("tcp", "127.0.0.1:0")
		if err != nil {
			t.Fatal(err)
		}
		addr := ln.Addr().String()
		_ = ln.Close()
		t.Setenv(intent.EnvAddress, "http://"+addr)
		t.Setenv(intent.EnvToken, fakeToken)
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
	for _, args := range [][]string{{"waypoint", "list"}, {"waypoint", "plan", "--series", "demo"}} {
		t.Run(strings.Join(args, " "), func(t *testing.T) {
			useStateRoot(t)
			useService(t, nil)
			seriesInfrahub(t).start()
			code, doc, raw := executeClient(t, args...)
			if code != findings.ExitOK || findings.List(doc.Findings).Rejected() {
				t.Errorf("exit %d, %s; want 0", code, raw)
			}
		})
	}
	t.Run("psp validate", func(t *testing.T) {
		useService(t, nil)
		closedInfrahub(t)
		code, doc, raw := executeClient(t, "psp", "validate", repoPath("psp", "nokia_srlinux.yaml"), repoPath("psp", "arista_eos.yaml"))
		if code != findings.ExitOK || len(doc.Findings) != 0 {
			t.Errorf("exit %d, %s; want 0 with no finding", code, raw)
		}
	})
	t.Run("twin compile", func(t *testing.T) {
		useService(t, nil)
		closedInfrahub(t)
		out := filepath.Join(t.TempDir(), "b")
		code, doc, raw := executeClient(t, "twin", "compile", "--ctm", repoPath("testdata", "ctm", "three-node.json"), "--out", out)
		if code != findings.ExitOK || doc.BundleID != fixtureBundleID {
			t.Errorf("exit %d, %s; want 0 and bundle_id %s", code, raw, fixtureBundleID)
		}
	})
}
