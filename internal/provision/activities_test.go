package provision

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/mock"
	enumspb "go.temporal.io/api/enums/v1"
	"go.temporal.io/api/serviceerror"
	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/client"
	"go.temporal.io/sdk/converter"
	"go.temporal.io/sdk/mocks"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/testsuite"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/stage"
)

// fixtureBundleID is what testdata/ctm/three-node.json compiles to.
const fixtureBundleID = "23f86a2678a49a324a04ae458703be8252e2e30d6712d6b6094ce1ccd5c2988e"

func repoPath(parts ...string) string {
	return filepath.Join(append([]string{"..", ".."}, parts...)...)
}

// newControl is the control activities over a fresh state root and the embedded packages.
func newControl(t *testing.T) *ControlActivities {
	t.Helper()
	paths := lab.PathsAt(t.TempDir())
	return &ControlActivities{Store: bundle.NewDirStore(paths.Bundles), Paths: paths}
}

// stageRead leaves a copy of the CTM at src where ReadIntent leaves a read's CTM,
// bundles/.reads/<run id>.ctm.json, and returns its path.
func stageRead(t *testing.T, c *ControlActivities, src, runID string) string {
	t.Helper()
	b, err := os.ReadFile(src)
	if err != nil {
		t.Fatal(err)
	}
	dir := filepath.Join(c.Paths.Bundles, ".reads")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, runID+".ctm.json")
	if err := os.WriteFile(path, b, 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}

// entriesOf lists a directory's entries by name.
func entriesOf(t *testing.T, dir string) []string {
	t.Helper()
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	names := make([]string, 0, len(entries))
	for _, e := range entries {
		names = append(names, e.Name())
	}
	return names
}

// mustNotExist fails when anything is at path.
func mustNotExist(t *testing.T, path, what string) {
	t.Helper()
	if _, err := os.Stat(path); !os.IsNotExist(err) {
		t.Errorf("%s is still at %s (%v)", what, path, err)
	}
}

// The compile step files the read's bundle as the run needs it filed:
// in the store under its identity, reused rather than duplicated, with the read's CTM
// kept beside it and the read's transient copy removed; and a corrupt store entry that
// blocks the filing is bundle.id.mismatch at step compile, from the activity itself
// (contracts/cli.md: every identifier has a tier-1 test that produces it). Run as the
// worker runs it, from a CTM where ReadIntent leaves one.
func TestCompileActivity(t *testing.T) {
	ctx := context.Background()
	fixture := repoPath("testdata", "ctm", "three-node.json")

	t.Run("files a clean read's bundle", func(t *testing.T) {
		c := newControl(t)
		path := stageRead(t, c, fixture, "run-1")

		res, err := c.Compile(ctx, CompileInput{CTMPath: path})
		if err != nil {
			t.Fatal(err)
		}
		if res.Findings.Rejected() {
			t.Fatalf("a clean read was rejected: %+v", res.Findings)
		}
		if res.BundleID != fixtureBundleID {
			t.Errorf("bundle_id = %s, want %s", res.BundleID, fixtureBundleID)
		}
		if want := c.Store.Path(fixtureBundleID); res.BundlePath != want || !filepath.IsAbs(res.BundlePath) {
			t.Errorf("bundle path = %q, want the store's absolute %q", res.BundlePath, want)
		}
		if got, err := bundle.IDOfDir(res.BundlePath); err != nil || got != fixtureBundleID {
			t.Errorf("the store entry hashes to %q (%v), want %s", got, err, fixtureBundleID)
		}

		// The read's CTM is kept beside its bundle, byte for byte, and its transient copy is gone.
		sidecar := filepath.Join(c.Paths.Bundles, fixtureBundleID+".ctm.json")
		read, err := os.ReadFile(fixture)
		if err != nil {
			t.Fatal(err)
		}
		kept, err := os.ReadFile(sidecar)
		if err != nil {
			t.Fatalf("the read's CTM was not kept beside the bundle: %v", err)
		}
		if !bytes.Equal(kept, read) {
			t.Error("the CTM kept beside the bundle differs from the read's")
		}
		mustNotExist(t, path, "the read's transient CTM")

		// Nothing else is left in the store: no temporary directory from the compile.
		want := []string{".reads", fixtureBundleID, fixtureBundleID + ".ctm.json"}
		if got := entriesOf(t, c.Paths.Bundles); !slices.Equal(got, want) {
			t.Errorf("the store holds %v, want %v", got, want)
		}

		t.Run("a second compile of the same read reuses the entry", func(t *testing.T) {
			entryBefore, err := os.Stat(res.BundlePath)
			if err != nil {
				t.Fatal(err)
			}
			sidecarBefore, err := os.Stat(sidecar)
			if err != nil {
				t.Fatal(err)
			}
			again, err := c.Compile(ctx, CompileInput{CTMPath: stageRead(t, c, fixture, "run-2")})
			if err != nil {
				t.Fatal(err)
			}
			if again.BundleID != fixtureBundleID || again.BundlePath != res.BundlePath {
				t.Errorf("second compile = %+v, want the same bundle at the same path", again)
			}
			entryAfter, err := os.Stat(res.BundlePath)
			if err != nil {
				t.Fatal(err)
			}
			if !entryAfter.ModTime().Equal(entryBefore.ModTime()) {
				t.Error("a present entry was rewritten; it is reused, never duplicated")
			}
			sidecarAfter, err := os.Stat(sidecar)
			if err != nil {
				t.Fatal(err)
			}
			if os.SameFile(sidecarBefore, sidecarAfter) && sidecarAfter.ModTime().Equal(sidecarBefore.ModTime()) {
				t.Error("the CTM beside the bundle was not overwritten by the later read")
			}
			if got := entriesOf(t, c.Paths.Bundles); !slices.Equal(got, want) {
				t.Errorf("the store holds %v after a second compile, want %v", got, want)
			}
		})
	})

	t.Run("a CTM given from outside .reads/ is left where it was", func(t *testing.T) {
		c := newControl(t)
		elsewhere := filepath.Join(t.TempDir(), "read.ctm.json")
		b, err := os.ReadFile(fixture)
		if err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(elsewhere, b, 0o644); err != nil {
			t.Fatal(err)
		}
		if _, err := c.Compile(ctx, CompileInput{CTMPath: elsewhere}); err != nil {
			t.Fatal(err)
		}
		if _, err := os.Stat(elsewhere); err != nil {
			t.Errorf("a CTM outside .reads/ was removed: %v", err)
		}
	})

	t.Run("a corrupt store entry is bundle.id.mismatch at step compile", func(t *testing.T) {
		c := newControl(t)
		id, err := c.Store.Put(ctx, repoPath("testdata", "golden", "three-node"))
		if err != nil || id != fixtureBundleID {
			t.Fatalf("filing the golden bundle: %s, %v", id, err)
		}
		entry := c.Store.Path(id)
		if err := os.WriteFile(filepath.Join(entry, "configs", "n1.cli"), []byte("corrupted in the store\n"), 0o644); err != nil {
			t.Fatal(err)
		}

		res, err := c.Compile(ctx, CompileInput{CTMPath: stageRead(t, c, fixture, "run-3")})
		if err != nil {
			t.Fatalf("Compile returned an error, want a result carrying the rejection: %v", err)
		}
		i := slices.IndexFunc(res.Findings, func(f findings.Finding) bool { return f.Rule == findings.RuleBundleIDMismatch })
		if i < 0 {
			t.Fatalf("findings %+v, want %s", res.Findings, findings.RuleBundleIDMismatch)
		}
		if f := res.Findings[i]; f.Severity != findings.Rejection || f.Step != findings.StepCompile || f.Object != entry ||
			!strings.Contains(f.Message, fixtureBundleID) {
			t.Errorf("finding %+v, want a rejection at step compile naming the store entry %s and bundle %s", f, entry, fixtureBundleID)
		}
		if res.BundleID != fixtureBundleID {
			t.Errorf("bundle_id = %q, want %s: the compile named the bundle even though it could not file it", res.BundleID, fixtureBundleID)
		}
		mustNotExist(t, filepath.Join(c.Paths.Bundles, fixtureBundleID+".ctm.json"), "a CTM beside a bundle that was not filed")
		// The read's transient copy has no use once the run has ended here.
		if left := entriesOf(t, filepath.Join(c.Paths.Bundles, ".reads")); len(left) != 0 {
			t.Errorf("bundles/.reads/ still holds %v after the compile ended without filing; the copy is transient", left)
		}
	})

	t.Run("a rejected read's copy is removed", func(t *testing.T) {
		c := newControl(t)
		defect := repoPath("testdata", "ctm", "defects", "iftype-unimplemented.json")
		res, err := c.Compile(ctx, CompileInput{CTMPath: stageRead(t, c, defect, "run-4")})
		if err != nil {
			t.Fatal(err)
		}
		if !res.Findings.Rejected() {
			t.Fatalf("a defect CTM compiled: %+v", res)
		}
		if got := entriesOf(t, c.Paths.Bundles); !slices.Equal(got, []string{".reads"}) {
			t.Errorf("the store holds %v after a rejection, want nothing filed", got)
		}
		if left := entriesOf(t, filepath.Join(c.Paths.Bundles, ".reads")); len(left) != 0 {
			t.Errorf("bundles/.reads/ still holds %v after a rejection; the copy is transient", left)
		}
	})
}

// readFailure asserts err is a non-retryable step failure of type rule and returns the
// finding it carries, as internal/lab's stepFailure does for the host-bound activities.
func readFailure(t *testing.T, err error, rule string) findings.Finding {
	t.Helper()
	var appErr *temporal.ApplicationError
	if !errors.As(err, &appErr) || appErr.Type() != rule {
		t.Fatalf("error = %v, want an application error of type %s", err, rule)
	}
	if !appErr.NonRetryable() {
		t.Errorf("%s is retryable; retrying cannot change it", rule)
	}
	var f findings.Finding
	if err := appErr.Details(&f); err != nil {
		t.Fatal(err)
	}
	if f.Rule != rule {
		t.Errorf("finding rule = %q, want %q", f.Rule, rule)
	}
	return f
}

// The read step's own outcomes, from the ReadIntent activity itself (contracts/cli.md:
// operation.failed is "raised inside the run by ReadIntent or Compile"):
// an override package `psp validate` rejects is refused under its own psp.* findings before
// any request is sent; a read that could not run at all is operation.failed at step read,
// naming the branch and never the credential; and a conformance rejection is a
// result, not an error, with M1's findings placed at step read and nothing written under
// bundles/.reads/. Run as the worker runs it, through the activity test environment, with
// the credential a sentinel as cmd/fylgja/credential_test.go uses.
//
// The path that writes bundles/.reads/<run id>.ctm.json needs a full read: the contract
// node, then the Devices and Links queries. No response recorded from Infrahub exists in
// the repository to can those answers from, and hand-written answers would be a fake
// Infrahub standing in for the integration the contract tier exists to exercise, so that
// path stays verified by the live run and the contract tier.
func TestReadIntentActivity(t *testing.T) {
	// sentinel stands in for the credential: unmistakable, so any output carrying it fails.
	const sentinel = "fylgja-secret-sentinel-4f2a9c"
	const branch = "fylgja-fixture"

	read := func(t *testing.T, c *ControlActivities) (ReadIntentResult, error) {
		t.Helper()
		var suite testsuite.WorkflowTestSuite
		env := suite.NewTestActivityEnvironment()
		env.RegisterActivityWithOptions(c.ReadIntent, activity.RegisterOptions{Name: wire.ActReadIntent})
		val, err := env.ExecuteActivity(wire.ActReadIntent, ReadIntentInput{Branch: branch})
		if err != nil {
			return ReadIntentResult{}, err
		}
		var res ReadIntentResult
		if err := val.Get(&res); err != nil {
			t.Fatal(err)
		}
		return res, nil
	}
	// nothingRead fails when anything is under bundles/.reads/: a read that ended before
	// its CTM writes nothing.
	nothingRead := func(t *testing.T, c *ControlActivities) {
		t.Helper()
		dir := filepath.Join(c.Paths.Bundles, ".reads")
		entries, err := os.ReadDir(dir)
		if err != nil && !os.IsNotExist(err) {
			t.Fatal(err)
		}
		if len(entries) != 0 {
			t.Errorf("%s holds %v after a read that ended before its CTM", dir, entries)
		}
	}
	atStep := func(t *testing.T, list findings.List, step string) {
		t.Helper()
		for _, f := range list {
			if f.Step != step {
				t.Errorf("finding %+v is at step %q, want %q", f, f.Step, step)
			}
		}
	}
	rules := func(list findings.List) []string {
		out := make([]string, 0, len(list))
		for _, f := range list {
			out = append(out, f.Rule)
		}
		return out
	}

	t.Run("an invalid override package is refused before any request", func(t *testing.T) {
		src, err := os.ReadFile(repoPath("testdata", "psp", "defects", "no-encoding.yaml"))
		if err != nil {
			t.Fatal(err)
		}
		override := t.TempDir()
		if err := os.WriteFile(filepath.Join(override, "nokia_srlinux.yaml"), src, 0o644); err != nil {
			t.Fatal(err)
		}
		var requests atomic.Int32
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			requests.Add(1)
			http.Error(w, "unexpected", http.StatusTeapot)
		}))
		defer srv.Close()
		t.Setenv(intent.EnvAddress, srv.URL)
		t.Setenv(intent.EnvToken, sentinel)

		c := newControl(t)
		c.PSPDir = override
		res, err := read(t, c)
		if err != nil {
			t.Fatalf("ReadIntent returned an error, want a result carrying the refusal: %v", err)
		}
		if !res.Findings.Rejected() || !slices.Contains(rules(res.Findings), findings.RulePSPReadinessEncoding) {
			t.Errorf("findings %+v, want a rejection carrying %s", res.Findings, findings.RulePSPReadinessEncoding)
		}
		atStep(t, res.Findings, findings.StepRead)
		if res.CTMPath != "" {
			t.Errorf("ctm_path = %q, want none: nothing was read", res.CTMPath)
		}
		if n := requests.Load(); n != 0 {
			t.Errorf("Infrahub received %d request(s) before the package was refused", n)
		}
		nothingRead(t, c)
	})

	t.Run("a read that could not run is operation.failed naming the branch, not the credential", func(t *testing.T) {
		for _, tc := range []struct{ name, address string }{
			{"address unset", ""},
			{"nothing listening", "http://127.0.0.1:1"},
		} {
			t.Run(tc.name, func(t *testing.T) {
				t.Setenv(intent.EnvAddress, tc.address)
				t.Setenv(intent.EnvToken, sentinel)

				c := newControl(t)
				_, err := read(t, c)
				f := readFailure(t, err, findings.RuleOperationFailed)
				if f.Step != findings.StepRead || f.Object != "branch "+branch {
					t.Errorf("finding %+v, want step read on object %q", f, "branch "+branch)
				}
				for what, text := range map[string]string{"the error": err.Error(), "the finding's message": f.Message, "the finding's object": f.Object} {
					if strings.Contains(text, sentinel) {
						t.Errorf("%s carries the credential: %s", what, text)
					}
				}
				nothingRead(t, c)
			})
		}
	})

	// Infrahub 1.11.2 answers a deleted branch as one never created. The finding
	// is operation.failed's, as a create reports it; only the type differs, which is
	// what Reconcile ends rejected on.
	t.Run("a branch that does not exist is operation.failed under BranchNotFoundType", func(t *testing.T) {
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
			w.WriteHeader(http.StatusBadRequest)
			_, _ = w.Write([]byte(`{"data":null,"errors":[{"message":"Branch: ` + branch + ` not found.","extensions":{"code":400}}]}`))
		}))
		defer srv.Close()
		t.Setenv(intent.EnvAddress, srv.URL)
		t.Setenv(intent.EnvToken, sentinel)

		c := newControl(t)
		_, err := read(t, c)
		var appErr *temporal.ApplicationError
		if !errors.As(err, &appErr) || appErr.Type() != BranchNotFoundType || !appErr.NonRetryable() {
			t.Fatalf("error = %v, want a non-retryable application error of type %s", err, BranchNotFoundType)
		}
		var f findings.Finding
		if err := appErr.Details(&f); err != nil {
			t.Fatal(err)
		}
		want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleOperationFailed, Step: findings.StepRead,
			Object: "branch " + branch, Message: "reading the schema (branch " + branch + "): HTTP 400: Branch: " + branch + " not found."}
		if f != want {
			t.Errorf("finding %+v, want %+v", f, want)
		}
		nothingRead(t, c)
	})

	t.Run("a conformance rejection is a result at step read with nothing written", func(t *testing.T) {
		var requests atomic.Int32
		var answered atomic.Int64 // the handler's clock, UnixMicro, when it answered
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			requests.Add(1)
			answered.Store(time.Now().UnixMicro())
			if r.Method != http.MethodGet || r.URL.Path != "/api/schema" {
				t.Errorf("a conformance read sent %s %s; want only GET /api/schema", r.Method, r.URL.Path)
				http.Error(w, "unexpected", http.StatusTeapot)
				return
			}
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"main":"h","generics":[],"nodes":[]}`))
		}))
		defer srv.Close()
		t.Setenv(intent.EnvAddress, srv.URL)
		t.Setenv(intent.EnvToken, sentinel)

		c := newControl(t)
		res, err := read(t, c)
		if err != nil {
			t.Fatalf("ReadIntent returned an error, want a result carrying the rejection: %v", err)
		}
		if res.CTMPath != "" {
			t.Errorf("ctm_path = %q, want none: a rejected read writes no CTM", res.CTMPath)
		}
		observed, err := time.Parse(stage.ObservedAtFormat, res.ObservedAt)
		if err != nil {
			t.Fatalf("observed_at %q does not parse under %s: %v", res.ObservedAt, stage.ObservedAtFormat, err)
		}
		if clock := time.UnixMicro(answered.Load()); observed.After(clock) {
			t.Errorf("observed_at %s is later than the first request was answered (%s); it is stamped before the first request", observed, clock.UTC())
		}
		if n := requests.Load(); n != 1 {
			t.Errorf("Infrahub received %d request(s); want the schema read alone, as no contract node was declared", n)
		}

		want := []string{findings.RuleContractNodeMissing}
		for range ctm.RequiredGenerics {
			want = append(want, findings.RuleGenericUnimplemented)
		}
		if !res.Findings.Rejected() || !slices.Equal(rules(res.Findings), want) {
			t.Errorf("findings %+v, want rules %v", res.Findings, want)
		}
		for i, f := range res.Findings {
			switch {
			case i == 0 && f.Object != branch:
				t.Errorf("%s names %q, want the branch %q", f.Rule, f.Object, branch)
			case i > 0 && i-1 < len(ctm.RequiredGenerics) && f.Object != ctm.RequiredGenerics[i-1]:
				t.Errorf("%s names %q, want the generic %q", f.Rule, f.Object, ctm.RequiredGenerics[i-1])
			}
		}
		atStep(t, res.Findings, findings.StepRead)
		nothingRead(t, c)
	})
}

// scheduleNotFound is the workflow service's answer for a Schedule that does not exist.
func scheduleNotFound() error { return serviceerror.NewNotFound("schedule not found") }

// describedSchedule is Describe's answer for Schedule fylgja-follow checking branch every
// interval, with the action's args as the service returns them: payloads.
func describedSchedule(t *testing.T, branch string, interval time.Duration) *client.ScheduleDescription {
	t.Helper()
	arg, err := converter.GetDefaultDataConverter().ToPayload(ReconcileInput{Branch: branch, Version: "0.1.0-dev"})
	if err != nil {
		t.Fatal(err)
	}
	return &client.ScheduleDescription{Schedule: client.Schedule{
		Spec:   &client.ScheduleSpec{Intervals: []client.ScheduleIntervalSpec{{Every: interval}}},
		Action: &client.ScheduleWorkflowAction{ID: WorkflowReconcile, Workflow: "Reconcile", Args: []any{arg}, TaskQueue: TaskQueue},
	}}
}

// scheduleService is a mocks.Client whose ScheduleClient hands back one handle for
// fylgja-follow, recording in order the calls that change something.
type scheduleService struct {
	mc      *mocks.Client
	sc      *mocks.ScheduleClient
	handle  *mocks.ScheduleHandle
	seq     []string
	created *client.ScheduleOptions
}

func newScheduleService() *scheduleService {
	s := &scheduleService{mc: &mocks.Client{}, sc: &mocks.ScheduleClient{}, handle: &mocks.ScheduleHandle{}}
	s.mc.On("ScheduleClient").Return(s.sc)
	s.sc.On("GetHandle", mock.Anything, FollowScheduleID).Return(s.handle)
	return s
}

func (s *scheduleService) describes(desc *client.ScheduleDescription, err error) {
	s.handle.On("Describe", mock.Anything).Run(func(mock.Arguments) { s.seq = append(s.seq, "describe") }).Return(desc, err)
}

func (s *scheduleService) deletes(err error) {
	s.handle.On("Delete", mock.Anything).Run(func(mock.Arguments) { s.seq = append(s.seq, "delete") }).Return(err)
}

func (s *scheduleService) creates(err error) {
	s.sc.On("Create", mock.Anything, mock.Anything).Run(func(args mock.Arguments) {
		o := args.Get(1).(client.ScheduleOptions)
		s.created = &o
		s.seq = append(s.seq, "create")
	}).Return(s.handle, err)
}

// noCredentialField fails the test when v, marshalled, has a field name that could hold a
// credential.
func noCredentialField(t *testing.T, label string, v any) {
	t.Helper()
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	var walk func(any)
	walk = func(x any) {
		switch x := x.(type) {
		case map[string]any:
			for k, v := range x {
				lower := strings.ToLower(k)
				for _, bad := range []string{"token", "password", "secret"} {
					if strings.Contains(lower, bad) {
						t.Errorf("%s carries field %q", label, k)
					}
				}
				walk(v)
			}
		case []any:
			for _, v := range x {
				walk(v)
			}
		}
	}
	var decoded any
	if err := json.Unmarshal(b, &decoded); err != nil {
		t.Fatal(err)
	}
	walk(decoded)
}

func TestRunsInFlightActivity(t *testing.T) {
	notFound := serviceerror.NewNotFound("workflow execution not found")
	closed := running(WorkflowProvision, "run-old")
	closed.WorkflowExecutionInfo.Status = enumspb.WORKFLOW_EXECUTION_STATUS_COMPLETED

	for _, c := range []struct {
		label              string
		provision, destroy any // a describe response or an error
		want               RunsInFlightResult
		wantErr            bool
	}{
		{"none running", notFound, notFound, RunsInFlightResult{}, false},
		{"provision running", running(WorkflowProvision, "run-p"), notFound, RunsInFlightResult{Provision: "run-p"}, false},
		{"destroy running", notFound, running(WorkflowDestroy, "run-d"), RunsInFlightResult{Destroy: "run-d"}, false},
		{"a closed run", closed, notFound, RunsInFlightResult{}, false},
		{"a service error", errors.New("connection refused"), notFound, RunsInFlightResult{}, true},
	} {
		t.Run(c.label, func(t *testing.T) {
			mc := &mocks.Client{}
			for id, answer := range map[string]any{WorkflowProvision: c.provision, WorkflowDestroy: c.destroy} {
				call := mc.On("DescribeWorkflowExecution", mock.Anything, id, "")
				if err, ok := answer.(error); ok {
					call.Return(nil, err)
				} else {
					call.Return(answer, nil)
				}
			}
			got, err := (&ControlActivities{Client: mc}).RunsInFlight(context.Background())
			if c.wantErr {
				if err == nil || !strings.Contains(err.Error(), "connection refused") {
					t.Errorf("error = %v, want the service error returned as it is", err)
				}
				var appErr *temporal.ApplicationError
				if errors.As(err, &appErr) && appErr.NonRetryable() {
					t.Error("a service error must stay retryable")
				}
				return
			}
			if err != nil || got != c.want {
				t.Errorf("RunsInFlight = %+v, %v; want %+v", got, err, c.want)
			}
		})
	}
}

func TestStartFollowingActivity(t *testing.T) {
	in := StartFollowingInput{Branch: "fylgja-fixture", IntervalS: 300, Version: "0.1.0-dev"}

	t.Run("options, field by field", func(t *testing.T) {
		s := newScheduleService()
		s.deletes(scheduleNotFound())
		s.creates(nil)
		got, err := (&ControlActivities{Client: s.mc}).StartFollowing(context.Background(), in)
		if err != nil {
			t.Fatal(err)
		}
		if want := (FollowingResult{Branch: "fylgja-fixture", IntervalS: 300, ScheduleID: "fylgja-follow"}); got != want {
			t.Errorf("result %+v, want %+v", got, want)
		}
		o := s.created
		if o == nil {
			t.Fatal("no schedule was created")
		}
		if o.ID != "fylgja-follow" || len(o.Spec.Intervals) != 1 || o.Spec.Intervals[0].Every != 5*time.Minute ||
			o.Spec.Intervals[0].Offset != 0 || o.Spec.Jitter != 0 {
			t.Errorf("id %q, spec %+v; want fylgja-follow every 5m, no offset, no jitter", o.ID, o.Spec)
		}
		if o.Overlap != enumspb.SCHEDULE_OVERLAP_POLICY_SKIP || o.CatchupWindow != time.Minute {
			t.Errorf("overlap %v, catch-up %s; want SKIP and 1m", o.Overlap, o.CatchupWindow)
		}
		if o.Memo != nil || o.TypedSearchAttributes.Size() != 0 || o.Paused || o.TriggerImmediately || o.PauseOnFailure {
			t.Errorf("options %+v carry more than the interval and the branch", o)
		}
		action, ok := o.Action.(*client.ScheduleWorkflowAction)
		if !ok {
			t.Fatalf("action %T, want a workflow action", o.Action)
		}
		if action.ID != "fylgja-reconcile" || action.Workflow != "Reconcile" || action.TaskQueue != "fylgja" ||
			action.Memo != nil {
			t.Errorf("action {ID:%q Workflow:%v TaskQueue:%q Memo:%v}, want fylgja-reconcile, Reconcile, fylgja, none",
				action.ID, action.Workflow, action.TaskQueue, action.Memo)
		}
		if want := []any{ReconcileInput{Branch: "fylgja-fixture", Version: "0.1.0-dev"}}; !slices.Equal(action.Args, want) {
			t.Errorf("args %+v, want %+v", action.Args, want)
		}
		noCredentialField(t, "the check's input", action.Args)
		noCredentialField(t, "StartFollowing's input", in)
		noCredentialField(t, "StartFollowing's result", got)
	})

	t.Run("an existing schedule is deleted first", func(t *testing.T) {
		s := newScheduleService()
		s.deletes(nil)
		s.creates(nil)
		if _, err := (&ControlActivities{Client: s.mc}).StartFollowing(context.Background(), in); err != nil {
			t.Fatal(err)
		}
		if want := []string{"delete", "create"}; !slices.Equal(s.seq, want) {
			t.Errorf("calls %v, want %v", s.seq, want)
		}
	})

	t.Run("a create error is returned", func(t *testing.T) {
		s := newScheduleService()
		s.deletes(scheduleNotFound())
		s.creates(errors.New("namespace unavailable"))
		_, err := (&ControlActivities{Client: s.mc}).StartFollowing(context.Background(), in)
		if err == nil || !strings.Contains(err.Error(), "namespace unavailable") {
			t.Errorf("error = %v, want the create error", err)
		}
	})

	t.Run("a delete error is returned before any create", func(t *testing.T) {
		s := newScheduleService()
		s.deletes(errors.New("deadline exceeded"))
		s.creates(nil)
		_, err := (&ControlActivities{Client: s.mc}).StartFollowing(context.Background(), in)
		if err == nil || slices.Contains(s.seq, "create") {
			t.Errorf("error = %v, calls %v; want the delete error and no create", err, s.seq)
		}
	})
}

func TestStopFollowingActivity(t *testing.T) {
	t.Run("deletes, naming the branch", func(t *testing.T) {
		s := newScheduleService()
		s.describes(describedSchedule(t, "fylgja-fixture", 5*time.Minute), nil)
		s.deletes(nil)
		got, err := (&ControlActivities{Client: s.mc}).StopFollowing(context.Background())
		if err != nil {
			t.Fatal(err)
		}
		if want := (StopFollowingResult{Deleted: true, Branch: "fylgja-fixture"}); got != want {
			t.Errorf("result %+v, want %+v", got, want)
		}
		if want := []string{"describe", "delete"}; !slices.Equal(s.seq, want) {
			t.Errorf("calls %v, want %v", s.seq, want)
		}
		noCredentialField(t, "StopFollowing's result", got)
	})

	t.Run("absent is not deleted, and not an error", func(t *testing.T) {
		s := newScheduleService()
		s.describes(nil, scheduleNotFound())
		s.deletes(nil)
		got, err := (&ControlActivities{Client: s.mc}).StopFollowing(context.Background())
		if err != nil || got.Deleted {
			t.Errorf("StopFollowing = %+v, %v; want Deleted false and no error", got, err)
		}
		if slices.Contains(s.seq, "delete") {
			t.Error("an absent schedule was deleted")
		}
	})

	t.Run("a delete error is returned", func(t *testing.T) {
		s := newScheduleService()
		s.describes(describedSchedule(t, "fylgja-fixture", 5*time.Minute), nil)
		s.deletes(errors.New("permission denied"))
		_, err := (&ControlActivities{Client: s.mc}).StopFollowing(context.Background())
		if err == nil || !strings.Contains(err.Error(), "permission denied") {
			t.Errorf("error = %v, want the delete error", err)
		}
	})
}
