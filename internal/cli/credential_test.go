package cli

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// sentinel stands in for a real credential. It is deliberately unmistakable: any test
// here that fails prints the output that carried it, and a reader has to be able to
// see at a glance that the string is the token and not a coincidence.
const sentinel = "fylgja-secret-sentinel-4f2a9c"

// unreachable is an address where nothing listens, so the failure is a transport
// error carrying a request dump — the shape most likely to quote a header back
// (internal/intent/errors.go, redact).
const unreachable = "http://127.0.0.1:1"

// shown collects every byte a command would put in front of an operator: the JSON
// document, the text rendering, and the error string itself. All three are asserted
// together because all three are printed, logged, and pasted into issues.
func shown(t *testing.T, err error) string {
	t.Helper()
	var buf bytes.Buffer
	var res *result
	if asResult(err, &res) {
		if werr := res.doc.WriteJSON(&buf); werr != nil {
			t.Fatal(werr)
		}
		if werr := res.doc.WriteText(&buf); werr != nil {
			t.Fatal(werr)
		}
	}
	if err != nil {
		buf.WriteString(err.Error())
	}
	return buf.String()
}

// echoingServer answers every request with the given status and a body quoting the
// credential back, the way a badly behaved proxy or a debug-mode server would. If
// anything Fylgja prints were built from a response body, the sentinel would surface
// through it — which is what makes these cases evidence rather than decoration.
func echoingServer(t *testing.T, status int) string {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(status)
		_, _ = w.Write([]byte(`{"errors":["rejected key ` + r.Header.Get("X-INFRAHUB-KEY") + `"]}`))
	}))
	t.Cleanup(srv.Close)
	return srv.URL
}

// The credential must appear in no finding and no error message — including when the
// credential itself is what failed (Constitution X). A token that
// leaks into an error is a token that ends up in a log, a ticket, and a pasted stack
// trace.
func TestCredentialNeverReachesOutput(t *testing.T) {
	// A mode with no address gets an echoing server, built per subtest so each gets
	// a fresh one; status 0 means "reach nothing at all".
	for _, mode := range []struct {
		name    string
		address string
		status  int
	}{
		{name: "unreachable address", address: unreachable},
		{name: "rejected credential", status: http.StatusUnauthorized},
		{name: "server error quoting the credential", status: http.StatusInternalServerError},
	} {
		for _, op := range []struct {
			name string
			run  func(t *testing.T, out string) error
		}{
			{"intent read", func(t *testing.T, out string) error {
				return runRead(t.Context(), &options{}, &readFlags{branch: "any-branch", out: out})
			}},
			{"schema check", func(t *testing.T, _ string) error {
				return runCheck(t.Context(), &options{}, &checkFlags{branch: "any-branch"})
			}},
			// A dry run reads in the CLI's own process, with the CLI's own token.
			{"twin create --dry-run", func(t *testing.T, _ string) error {
				paths := useStateRoot(t)
				useService(t, nil)
				dryRunEnv(t)
				useClab(t, "inspect-empty.json")
				err := runCreate(t.Context(), &options{}, &createFlags{branch: "any-branch", dryRun: true})
				if got := entriesOf(t, paths.Bundles); len(got) != 0 {
					t.Errorf("a dry run whose read failed filed %v", got)
				}
				return err
			}},
		} {
			t.Run(mode.name+"/"+op.name, func(t *testing.T) {
				address := mode.address
				if address == "" {
					address = echoingServer(t, mode.status)
				}
				t.Setenv(intent.EnvAddress, address)
				t.Setenv(intent.EnvToken, sentinel)
				served := markServed()

				out := filepath.Join(t.TempDir(), "never.json")
				var err error
				stdout := captureStdout(t, func() { err = op.run(t, out) })
				noSecretServed(t, served, sentinel)
				if err == nil {
					t.Fatal("expected the operation to fail")
				}
				if text := stdout + shown(t, err); strings.Contains(text, sentinel) {
					t.Errorf("the credential appeared in output:\n%s", text)
				}
				var res *result
				if asResult(err, &res) && res.doc.Status.ExitCode() != findings.ExitError {
					t.Errorf("exit %d, want %d", res.doc.Status.ExitCode(), findings.ExitError)
				}
				if _, statErr := os.Stat(out); !os.IsNotExist(statErr) {
					t.Errorf("a failed %s left a file at %s", op.name, out)
				}
			})
		}
	}
}

// probeSentinel stands in for the readiness probe's password, as sentinel stands in for the
// Infrahub token.
const probeSentinel = "fylgja-probe-password-sentinel-7c1d0e"

// The probe password is held by the worker, not the CLI, and read for its presence
// by the host check and the worker's start-up report. None of what an operator sees from
// those, or from a run whose probe never logged in, may carry it (Constitution X). The
// probe itself is covered in internal/lab
// (TestProbePasswordNeverReachesOutput); these are the paths above it.
func TestProbeLoginNeverReachesOutput(t *testing.T) {
	t.Setenv("FYLGJA_SRLINUX_USERNAME", "admin")
	t.Setenv("FYLGJA_SRLINUX_PASSWORD", probeSentinel)

	t.Run("create reporting a readiness timeout", func(t *testing.T) {
		result, events := readinessTimeoutRun()
		useService(t, &fakeService{runID: "run-1", events: events, result: result})
		useInterrupts(t)
		served := markServed()

		var err error
		stdout := captureStdout(t, func() {
			err = runCreate(context.Background(), &options{}, &createFlags{branch: "fylgja-fixture"})
		})
		noSecretServed(t, served, probeSentinel)
		code, doc := exitOf(t, err)
		if code != findings.ExitFailed || len(doc.Findings) != 3 || doc.Findings[0].Rule != findings.RuleReadinessTimeout {
			t.Fatalf("exit %d, findings %+v; want 3 with readiness.timeout on three nodes", code, doc.Findings)
		}
		if !strings.Contains(stdout, "step readiness n1: failed readiness.timeout") {
			t.Fatalf("stdout does not report the failed probe, so the case proves nothing:\n%s", stdout)
		}
		if text := stdout + shown(t, err); strings.Contains(text, probeSentinel) {
			t.Errorf("the probe password appeared in output:\n%s", text)
		}
	})

	t.Run("dry run host check", func(t *testing.T) {
		useStateRoot(t)
		useService(t, nil)
		useClab(t, "inspect-empty.json")
		t.Setenv(lab.EnvHostMemoryMB, "")
		dir := copyGoldenBundle(t, "b")
		served := markServed()

		var err error
		stdout := captureStdout(t, func() {
			err = runTwinProvision(context.Background(), &options{}, &provisionFlags{dryRun: true}, dir)
		})
		noSecretServed(t, served, probeSentinel)
		if code, doc := exitOf(t, err); code != findings.ExitOK {
			t.Fatalf("exit %d, findings %+v; want 0: the login is set", code, doc.Findings)
		}
		if text := stdout + shown(t, err); strings.Contains(text, probeSentinel) {
			t.Errorf("the probe password appeared in output:\n%s", text)
		}
	})

	// twin verify reads each node over its probe's login, looked up at the moment of the
	// read: the reader is handed the password, and a node that refuses it is
	// reported without it.
	t.Run("twin verify, a node refusing its login", func(t *testing.T) {
		h := verifyHost(t, "three-node", nil, nil)
		t.Setenv("FYLGJA_SRLINUX_PASSWORD", probeSentinel)
		refused := errors.New(`gNMI Get /system/name/host-name at 172.20.20.3:57400: code=Unauthenticated msg="authentication failed"`)
		var handed []string
		var mu sync.Mutex
		served := markServed()
		defer noSecretServed(t, served, probeSentinel)
		out := runVerify(t, h.paths.Root, func() *fakeNodes {
			f := h.healthy(t)
			f.unreachableNode("n2", refused)
			f.onGet = func(probe wire.Probe, getenv func(string) (string, bool)) {
				v, _ := getenv(probe.PasswordEnv)
				mu.Lock()
				handed = append(handed, v)
				mu.Unlock()
			}
			return f
		})
		if out.code != findings.ExitError || !strings.Contains(out.stdout, "n2 (172.20.20.3:57400, nokia_srlinux): not read: ") {
			t.Fatalf("exit %d, stdout:\n%s\nwant n2 unread, exit 2, or the case proves nothing", out.code, out.stdout)
		}
		if len(handed) == 0 || slices.ContainsFunc(handed, func(v string) bool { return v != probeSentinel }) {
			t.Errorf("the reader was handed %q, want the probe password at every read", handed)
		}
		b, err := json.Marshal(out.doc)
		if err != nil {
			t.Fatal(err)
		}
		if text := out.stdout + out.stderr + string(b); strings.Contains(text, probeSentinel) {
			t.Errorf("the probe password appeared in output:\n%s", text)
		}
	})

	t.Run("worker start-up report", func(t *testing.T) {
		reg, err := psp.Load("")
		if err != nil {
			t.Fatal(err)
		}
		inspect, err := os.ReadFile(repoPath("internal", "lab", "testdata", "inspect-empty.json"))
		if err != nil {
			t.Fatal(err)
		}
		var logs bytes.Buffer
		logger := slog.New(slog.NewTextHandler(&logs, &slog.HandlerOptions{Level: slog.LevelDebug}))
		paths := lab.PathsAt(t.TempDir())
		acts := &lab.Activities{
			Clab:     &lab.Clab{Runner: &fakeClab{stdout: inspect}, Log: logger},
			Store:    bundle.NewDirStore(paths.Bundles),
			Paths:    paths,
			Registry: reg,
			Getenv:   os.LookupEnv,
			Version:  version,
			Log:      logger,
		}

		report := strings.Join(provision.StartupReport(context.Background(), acts, "localhost:7233", "default"), "\n")
		if !strings.Contains(report, "FYLGJA_SRLINUX_PASSWORD set") {
			t.Fatalf("the report does not say the password is set, so the case proves nothing:\n%s", report)
		}
		if text := report + logs.String(); strings.Contains(text, probeSentinel) {
			t.Errorf("the probe password appeared in the start-up report or its log:\n%s", text)
		}
	})
}

// readinessTimeoutRun is a provisioning run whose probe never logged in on any node: the
// result and the history the CLI reports it from, worded as internal/lab words them.
func readinessTimeoutRun() (provision.ProvisionResult, []provision.Event) {
	list := findings.List{}
	var events []provision.Event
	for i, node := range []string{"n1", "n2", "n3"} {
		msg := fmt.Sprintf("%s did not answer gnmi_get /system/information at 172.20.20.%d:57400 within 60s; "+
			"last error: rpc error: code = Unauthenticated desc = authentication failed", node, i+2)
		list.AddStep(findings.Rejection, findings.StepReadiness, findings.RuleReadinessTimeout, node, msg)
		events = append(events,
			provision.Event{Step: "readiness " + node},
			provision.Event{Step: "readiness " + node, End: true, Outcome: provision.EventFailed,
				Rule: findings.RuleReadinessTimeout, Message: msg, Duration: 60 * time.Second})
	}
	events = append(events,
		provision.Event{Step: "cleanup teardown"},
		provision.Event{Step: "cleanup teardown", End: true, Outcome: provision.EventDone, Duration: 2 * time.Second},
		provision.Event{Step: "cleanup unstage"},
		provision.Event{Step: "cleanup unstage", End: true, Outcome: provision.EventDone})
	return provision.ProvisionResult{
		Outcome:  provision.OutcomeFailed,
		BundleID: fixtureBundleID,
		Step:     findings.StepReadiness,
		Findings: list,
		Cleanup:  provision.CleanupResult{Teardown: provision.CleanupDone, Unstage: provision.CleanupDone},
	}, events
}

// A bundle is diffed, shared and committed. Nothing in one may carry the credential —
// and neither may the command's own output, even though `twin compile` never reads
// the network and never needs a token.
func TestBundleCarriesNoCredential(t *testing.T) {
	t.Setenv(intent.EnvAddress, unreachable)
	t.Setenv(intent.EnvToken, sentinel)

	out := filepath.Join(t.TempDir(), "bundle")
	served := markServed()
	defer noSecretServed(t, served, sentinel)
	err := runCompile(&options{}, &compileFlags{
		ctmPath: repoPath("testdata", "ctm", "three-node.json"),
		out:     out,
	})
	var res *result
	if !asResult(err, &res) {
		t.Fatalf("runCompile returned %v, want a findings result", err)
	}
	if res.doc.Status != findings.StatusOK {
		t.Fatalf("compile failed: %+v", res.doc.Findings)
	}
	if text := shown(t, err); strings.Contains(text, sentinel) {
		t.Errorf("the credential appeared in output:\n%s", text)
	}

	walkErr := filepath.Walk(out, func(p string, info os.FileInfo, err error) error {
		if err != nil || info.IsDir() {
			return err
		}
		data, readErr := os.ReadFile(p)
		if readErr != nil {
			return readErr
		}
		if bytes.Contains(data, []byte(sentinel)) {
			t.Errorf("%s contains the credential", p)
		}
		return nil
	})
	if walkErr != nil {
		t.Fatal(walkErr)
	}
}

// An unset credential is refused before the first request, not after one is rejected:
// sending an unauthenticated read would put a request in Infrahub's log for an
// operation that was never going to work, and the operator would read the answer as
// "the token is wrong" rather than "there is no token".
func TestMissingCredentialSendsNoRequest(t *testing.T) {
	for _, op := range []struct {
		name string
		run  func(t *testing.T, out string) error
	}{
		{"intent read", func(t *testing.T, out string) error {
			return runRead(t.Context(), &options{}, &readFlags{branch: "fylgja-fixture", out: out})
		}},
		{"schema check", func(t *testing.T, _ string) error {
			return runCheck(t.Context(), &options{}, &checkFlags{branch: "fylgja-fixture"})
		}},
	} {
		t.Run(op.name, func(t *testing.T) {
			requests := 0
			srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
				requests++
				w.WriteHeader(http.StatusOK)
			}))
			defer srv.Close()

			t.Setenv(intent.EnvAddress, srv.URL)
			t.Setenv(intent.EnvToken, "")
			served := markServed()

			out := filepath.Join(t.TempDir(), "never.json")
			err := op.run(t, out)
			noSecretServed(t, served)

			var res *result
			if !asResult(err, &res) {
				t.Fatalf("returned %v, want a findings result", err)
			}
			if code := res.doc.Status.ExitCode(); code != findings.ExitError {
				t.Errorf("exit %d, want %d", code, findings.ExitError)
			}
			if len(res.doc.Findings) != 1 || res.doc.Findings[0].Rule != findings.RuleOperationFailed {
				t.Fatalf("want one %s finding, got %+v", findings.RuleOperationFailed, res.doc.Findings)
			}
			if msg := res.doc.Findings[0].Message; !strings.Contains(msg, intent.EnvToken) {
				t.Errorf("message does not name the variable to set: %s", msg)
			}
			if requests != 0 {
				t.Errorf("%d request(s) reached Infrahub with no credential set", requests)
			}
			if _, statErr := os.Stat(out); !os.IsNotExist(statErr) {
				t.Error("a failed operation left a file behind")
			}
		})
	}
}
