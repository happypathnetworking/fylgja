package server

import (
	"bytes"
	"context"
	"encoding/json"
	"log/slog"
	"net/http/httptest"
	"os"
	"slices"
	"strings"
	"sync"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/bundle"
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
			return provision.DestroyDocument(subject(), provision.DestroyResult{Cleanup: clean, Findings: findings.List{}})
		}, findings.ExitOK, findings.StatusOK},
		{"destroy, something remains", func() *findings.Document {
			return provision.DestroyDocument(subject(), provision.DestroyResult{Cleanup: unclean,
				Findings: finding(findings.StepTeardown, findings.RuleCleanupIncomplete)})
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
			&findings.Subject{Branch: "fylgja-fixture", RunID: "run-1"}, res)
		if !asResult(err, &out) {
			t.Fatalf("provisionReport returned %v, want a findings result", err)
		}
		return out.doc
	}
}

// The run ids detachService starts, by workflow.
var detachedRunIDs = map[string]string{
	provision.WorkflowProvision: "01a10000-0000-7000-8000-000000000dp1",
	provision.WorkflowStep:      "01a10000-0000-7000-8000-000000000ds1",
	provision.WorkflowDestroy:   "01a10000-0000-7000-8000-000000000dd1",
}

// detachService is a workflow service whose runs start and are never followed: a detached
// answer reads no event and no result, so Follow, Result, ResultOfStep and the followed
// StartDestroy fail the test. Its destroy cancels a provisioning run first, as a destroy
// beside one does, which the detached destroy still waits for. Every other method is the nil
// interface's, and panics.
type detachService struct {
	provision.Service
	t  *testing.T
	mu sync.Mutex
	// started are the inputs of the runs it started, by workflow.
	provisioned []provision.ProvisionInput
	stepped     []provision.StepInput
	destroys    int
}

func (s *detachService) StartProvision(_ context.Context, in provision.ProvisionInput) (string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.provisioned = append(s.provisioned, in)
	return detachedRunIDs[provision.WorkflowProvision], nil
}

func (s *detachService) StartStep(_ context.Context, in provision.StepInput) (string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.stepped = append(s.stepped, in)
	return detachedRunIDs[provision.WorkflowStep], nil
}

func (s *detachService) StartDestroyDetached(_ context.Context, onEvent func(provision.Event)) (provision.DestroyRun, error) {
	s.mu.Lock()
	s.destroys++
	s.mu.Unlock()
	onEvent(provision.Event{Notice: "cancelling provisioning run p1; waiting for its cleanup"})
	onEvent(provision.Event{WorkflowID: provision.WorkflowProvision, Step: "teardown", FindingStep: findings.StepTeardown})
	onEvent(provision.Event{Notice: "provisioning run p1 closed: cancelled"})
	id := detachedRunIDs[provision.WorkflowDestroy]
	onEvent(provision.Event{Notice: "run " + provision.WorkflowDestroy + " " + id})
	return provision.DestroyRun{RunID: id}, nil
}

func (s *detachService) StartDestroy(context.Context, func(provision.Event)) (provision.DestroyRun, error) {
	s.t.Error("a detached destroy followed its run")
	return provision.DestroyRun{}, context.Canceled
}

func (s *detachService) Follow(context.Context, string, string, func(provision.Event)) error {
	s.t.Error("a detached run was followed")
	return nil
}

func (s *detachService) Result(context.Context, string, string) (provision.ProvisionResult, error) {
	s.t.Error("a detached run's result was read")
	return provision.ProvisionResult{}, context.Canceled
}

func (s *detachService) ResultOfStep(context.Context, string) (provision.StepResult, error) {
	s.t.Error("a detached step's result was read")
	return provision.StepResult{}, context.Canceled
}

func (s *detachService) Close() {}

// detachedStepWarning is the finding the step's command found before its start, which a
// detached step's document carries before run.detached as a followed one's carries it.
var detachedStepWarning = findings.Finding{Severity: findings.Warning, Step: findings.StepCompare,
	Rule: findings.RuleOperationFailed, Object: "n1", Message: "found before the start"}

// detachServer serves each operation's own handler over svc, but twin.step, whose guards
// need a twin, a store and a host: its handler is runStep under the request's detach, with
// the command's findings detachedStepWarning.
func detachServer(t *testing.T, svc provision.Service) *httptest.Server {
	t.Helper()
	s, srv, _, _ := testServer(t, func(c *call) error {
		if c.op == findings.OpTwinStep {
			return runStep(c.ctx, c.detachable(args(c.req.Args)), c.op, &findings.Subject{}, provision.StepInput{},
				findings.List{detachedStepWarning})
		}
		return handlers[c.op](c)
	})
	s.Dial = func(context.Context, *slog.Logger) (provision.Service, error) { return svc, nil }
	return srv
}

// detachedRequest is a request to op under detach, rendered as text, carrying what op needs
// to reach its start: the fixture's snapshot for a create, the golden bundle for a
// provision.
func detachedRequest(t *testing.T, op string) string {
	t.Helper()
	req := api.Request{Render: api.RenderText, Args: map[string]json.RawMessage{"detach": json.RawMessage("true")}}
	switch op {
	case findings.OpTwinCreate:
		req.Args["snapshot"] = json.RawMessage(`"snap.json"`)
		req.Files = fixtureFile(t, nil)
	case findings.OpTwinProvision:
		req.Args["bundle"] = json.RawMessage(`"` + fixtureBundleID + `"`)
		req.Files = goldenFiles(t)
	}
	body, err := api.EncodeRequest(req)
	if err != nil {
		t.Fatal(err)
	}
	return string(body)
}

// goldenFiles are the three-node golden bundle's files, as a client sends them.
func goldenFiles(t *testing.T) []api.File {
	t.Helper()
	m, err := bundle.LoadFiles(repoPath("testdata", "golden", "three-node"))
	if err != nil {
		t.Fatal(err)
	}
	var files []api.File
	for path, data := range m {
		files = append(files, api.File{Path: path, Data: data})
	}
	return files
}

// detachedRuns are the four runs detach applies to, by operation, with their workflow.
var detachedRuns = []struct{ op, workflowID string }{
	{findings.OpTwinCreate, provision.WorkflowProvision},
	{findings.OpTwinProvision, provision.WorkflowProvision},
	{findings.OpTwinStep, provision.WorkflowStep},
	{findings.OpTwinDestroy, provision.WorkflowDestroy},
}

// detachedAnswer sends op's detached request over a fresh detachServer and returns the
// answer's lines and frames, and the service.
func detachedAnswer(t *testing.T, op string) ([][]byte, []api.Frame, *detachService) {
	t.Helper()
	svc := &detachService{t: t}
	lines, frames := askByIdentity(t, detachServer(t, svc), op, detachedRequest(t, op))
	return lines, frames, svc
}

// Every answer ends with its document but a running run.read's (contracts/api.md, R-04), and
// under detach (020, R-03; US4 scenarios 1 and 6) a run's is its start, its run and that
// document, with no event of its own: status ok, exit 0, run.detached at step start naming
// the run, last among its findings. Each frame satisfies the contract's frame, and the
// document the current findings contract. The run goes on: nothing follows it or reads its
// result. A destroy's detached answer writes the run frame its stream never wrote.
func TestADetachedAnswerIsItsStartItsRunAndItsDocument(t *testing.T) {
	useStateRoot(t)
	frame := apiSchema(t, "frame")
	for _, r := range detachedRuns {
		t.Run(r.op, func(t *testing.T) {
			lines, frames, _ := detachedAnswer(t, r.op)
			var kinds []string
			for i, f := range frames {
				satisfies(t, frame, lines[i], r.op+"'s frame "+f.Kind())
				switch f.Kind() {
				case api.KindOut, api.KindErr:
					continue
				case api.KindEvent:
					// A destroy's events are the runs it cancelled first, never its own.
					if f.Event.WorkflowID == r.workflowID {
						t.Errorf("an event of the detached run: %s", lines[i])
					}
					continue
				}
				kinds = append(kinds, f.Kind())
			}
			if want := []string{api.KindStart, api.KindRun, api.KindDocument}; !slices.Equal(kinds, want) {
				t.Fatalf("frames %v, want %v", kinds, want)
			}
			id := detachedRunIDs[r.workflowID]
			var start, run *api.RunRef
			for _, f := range frames {
				if f.Start != nil {
					start = f.Start
				}
				if f.Run != nil {
					run = f.Run
				}
			}
			if *start != (api.RunRef{WorkflowID: r.workflowID}) || *run != (api.RunRef{WorkflowID: r.workflowID, RunID: id}) {
				t.Errorf("start %+v, run %+v; want %s's run %s", start, run, r.workflowID, id)
			}
			if frames[len(frames)-1].Kind() != api.KindDocument {
				t.Fatalf("the last frame is %s, want the document", lines[len(lines)-1])
			}
			var doc findings.Document
			if err := json.Unmarshal(frames[len(frames)-1].Document, &doc); err != nil {
				t.Fatal(err)
			}
			if doc.Status != findings.StatusOK || doc.Status.ExitCode() != findings.ExitOK || doc.Subject.RunID != id {
				t.Errorf("status %s, exit %d, run %q; want ok, 0, %s", doc.Status, doc.Status.ExitCode(), doc.Subject.RunID, id)
			}
			want := findings.Finding{Severity: findings.Info, Step: findings.StepStart, Rule: findings.RuleRunDetached,
				Object: r.workflowID + " " + id, Message: "run " + r.workflowID + " " + id + " started; read it with fylgja run read"}
			if n := len(doc.Findings); n == 0 || doc.Findings[n-1] != want {
				t.Errorf("findings %+v, want %+v last", doc.Findings, want)
			}
			validateWithShow(t, currentContract, "020", &doc)
		})
	}
}

// wantDetachConflict holds op's answer to detach beside dry_run, and nothing else op's
// transport does not require, to
// run.flags.conflict, exit 1, at step start on dry_run, the one finding, with nothing
// dialled, run or filed: it comes before every guard, each of which the request would
// otherwise meet (020).
func wantDetachConflict(t *testing.T, op string) {
	t.Helper()
	paths := useStateRoot(t)
	a := map[string]json.RawMessage{"dry_run": json.RawMessage("true"), "detach": json.RawMessage("true")}
	if op == findings.OpTwinProvision {
		// The transport's own requirement; no file is sent, which the verify would refuse.
		a["bundle"] = json.RawMessage(`"` + fixtureBundleID + `"`)
	}
	_, doc := handled(t, handlerServer(t), op, api.Request{Args: a})
	want := findings.Finding{Severity: findings.Rejection, Step: findings.StepStart, Rule: findings.RuleRunFlagsConflict,
		Object: "dry_run", Message: "--detach is meaningless with --dry-run: a dry run starts no run to detach from"}
	if doc.Status.ExitCode() != findings.ExitRejected || len(doc.Findings) != 1 || doc.Findings[0] != want {
		t.Errorf("%s: exit %d, findings %+v; want exit 1 and %+v", op, doc.Status.ExitCode(), doc.Findings, want)
	}
	for _, dir := range []string{paths.Bundles, paths.Snapshots} {
		if entries, err := os.ReadDir(dir); err == nil && len(entries) > 0 {
			t.Errorf("%s: the refusal filed %d entries under %s", op, len(entries), dir)
		}
	}
	validateWithShow(t, currentContract, "020", doc)
}

// detachedOf is a detached answer's out text and its document.
func detachedOf(t *testing.T, frames []api.Frame) (string, *findings.Document) {
	t.Helper()
	var out strings.Builder
	for _, f := range frames {
		out.WriteString(f.Out)
	}
	var doc findings.Document
	if err := json.Unmarshal(frames[len(frames)-1].Document, &doc); err != nil {
		t.Fatal(err)
	}
	return out.String(), &doc
}
