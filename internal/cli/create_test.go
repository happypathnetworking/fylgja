package cli

import (
	"bytes"
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/santhosh-tekuri/jsonschema/v6"
	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
)

const fixtureBundleID = "1b352957aa74ff6e6f944a1b5ccb3b678248c895601f7a3aa66a4f9166d3909a"

// fixtureSnapshotID is the fixture CTM's snapshot id (testdata/snapshot/three-node.json):
// what a create of the fake Infrahub's fixture branch takes and files before its run (018).
const fixtureSnapshotID = "6a8a77fc65bdf47b9bb3a753d7709875671df20e32838344f29cfba46a13f6d6"

// useFixtureRead serves the fixture branch from a fake Infrahub and points the state root
// at a fresh directory: a create reads, takes, compiles and files on the server before it
// starts its run (018), so every create that starts one reads something.
func useFixtureRead(t *testing.T) lab.Paths {
	t.Helper()
	newFakeInfrahub(t).start()
	return useStateRoot(t)
}

// headSnapshotID and headBundleID are what an unpinned read of the fake Infrahub's fixture
// branch takes and compiles to: the fixture's intent, its envelope naming no at.
const (
	headSnapshotID = "856af9ad8f6e5d13d2d99e3af7d21d86c2cc9645c45d548a2df0494a11aad617"
	headBundleID   = "dd9b53b7c560ab586bd9a25bc9b55dfa6777fff5bb65d6e3004122bb70438506"
)

// storedLines are the two lines a create prints before its run's start, the snapshot's
// above the bundle's, under the state root of paths (018, R-09).
func storedLines(paths lab.Paths, snapshotID, bundleID string) []string {
	return []string{
		"snapshot_id " + snapshotID + "  stored: " + filepath.Join(paths.Snapshots, snapshotID+".json"),
		"bundle_id " + bundleID + "  stored: " + filepath.Join(paths.Bundles, bundleID),
	}
}

// fixtureArtifacts are the fixture bundle's artifact checksums, by node: what 017's
// template renders for the fylgja-fixture branch, 707 bytes each, predicted at T016
// (research §5.1) and checked against a render at T060.
var fixtureArtifacts = map[string]string{
	"n1": "597f6263eb7e0b539679b3956270876f",
	"n2": "5ac21560015ad6bb1e881358115d0b7a",
	"n3": "e93df96400ddbada7daa1a0777d9d3e3",
}

// fakeService stands in for the workflow service: it starts nothing and answers with a
// canned history and result.
type fakeService struct {
	runID    string
	startErr error
	events   []provision.Event
	result   provision.ProvisionResult
	// release, when set, holds Result, and ResultOfStep (M11), until it is closed or the
	// caller stops waiting.
	release  chan struct{}
	onCancel func()
	// startBlocks holds StartProvision, and StartStep (M11), until the command abandons the
	// start, as a start waiting for a worker to take the run does; it then answers runID and
	// startErr.
	startBlocks bool
	// destroyRun, destroyErr and destroyEvents answer StartDestroy, and StartReclaim.
	destroyRun    provision.DestroyRun
	destroyErr    error
	destroyEvents []provision.Event
	// resultErr answers Result beside result. afterFollow runs once Follow has delivered
	// every event, where the run's history ends.
	resultErr   error
	afterFollow func()
	// inFlight answers twin show's one read, with readErr beside it; readBlocks holds the
	// read until its context is done, as a service that never answers.
	inFlight   []provision.RunInFlight
	readErr    error
	readBlocks bool
	// failRead, when set, names the read that fails with failReadErr, whatever it would
	// have answered.
	failRead    string
	failReadErr error
	// readOnly, when set, fails the test it names if a method that changes something is
	// called: twin show only reads.
	readOnly testing.TB
	// stepResult answers ResultOfStep beside resultErr (M11).
	stepResult provision.StepResult
	// rehearseRun answers StartRehearse beside startErr, rehearseEvents answer Follow of the
	// rehearsal's run, its children's events among them, and rehearseResult answers
	// ResultOfRehearse beside resultErr (015).
	rehearseRun    string
	rehearseEvents []provision.Event
	rehearseResult provision.RehearseResult

	mu sync.Mutex
	// calls logs each method that starts a run, in the order they came.
	calls     []string
	reads     []string
	started   []provision.ProvisionInput
	stepped   []provision.StepInput
	rehearsed []provision.RehearseInput
	abandoned bool
	cancels   int
	destroys  int
	closed    bool
}

// mutating fails a read-only test: name changes something.
func (f *fakeService) mutating(name string) {
	if f.readOnly != nil {
		f.readOnly.Errorf("%s called on a read-only service", name)
	}
}

// read records a read and answers it as failRead and readErr say, or blocks until ctx is done.
func (f *fakeService) read(ctx context.Context, name string) error {
	f.mu.Lock()
	f.reads = append(f.reads, name)
	f.mu.Unlock()
	if f.readBlocks {
		<-ctx.Done()
		return ctx.Err()
	}
	if f.failRead == name {
		return f.failReadErr
	}
	return f.readErr
}

func (f *fakeService) InFlight(ctx context.Context) ([]provision.RunInFlight, error) {
	if err := f.read(ctx, "InFlight"); err != nil {
		return nil, err
	}
	return f.inFlight, nil
}

func (f *fakeService) StartProvision(ctx context.Context, in provision.ProvisionInput) (string, error) {
	f.mutating("StartProvision")
	f.mu.Lock()
	f.calls = append(f.calls, "StartProvision")
	f.started = append(f.started, in)
	blocks, runID, err := f.startBlocks, f.runID, f.startErr
	f.mu.Unlock()
	if blocks {
		<-ctx.Done()
		f.mu.Lock()
		f.abandoned = true
		f.mu.Unlock()
	}
	return runID, err
}

func (f *fakeService) Follow(_ context.Context, workflowID, _ string, onEvent func(provision.Event)) error {
	events := f.events
	if workflowID == provision.WorkflowRehearse {
		events = f.rehearseEvents
	}
	for _, e := range events {
		onEvent(e)
	}
	if f.afterFollow != nil {
		f.afterFollow()
	}
	return nil
}

func (f *fakeService) Result(ctx context.Context, _, _ string) (provision.ProvisionResult, error) {
	if f.release != nil {
		select {
		case <-f.release:
		case <-ctx.Done():
			return provision.ProvisionResult{}, ctx.Err()
		}
	}
	return f.result, f.resultErr
}

func (f *fakeService) Cancel(context.Context, string, string) error {
	f.mutating("Cancel")
	f.mu.Lock()
	f.cancels++
	onCancel := f.onCancel
	f.mu.Unlock()
	if onCancel != nil {
		onCancel()
	}
	return nil
}

func (f *fakeService) StartDestroy(_ context.Context, onEvent func(provision.Event)) (provision.DestroyRun, error) {
	f.mutating("StartDestroy")
	f.mu.Lock()
	f.calls = append(f.calls, "StartDestroy")
	f.destroys++
	f.mu.Unlock()
	for _, e := range f.destroyEvents {
		onEvent(e)
	}
	return f.destroyRun, f.destroyErr
}

// StartReclaim answers as StartDestroy does, under its own name in calls: the rehearsal's
// reclaim (015, T091). A test that has it refuse sets destroyErr to the refusal.
func (f *fakeService) StartReclaim(_ context.Context, onEvent func(provision.Event)) (provision.DestroyRun, error) {
	f.mutating("StartReclaim")
	f.mu.Lock()
	f.calls = append(f.calls, "StartReclaim")
	f.destroys++
	f.mu.Unlock()
	for _, e := range f.destroyEvents {
		onEvent(e)
	}
	return f.destroyRun, f.destroyErr
}

// StartStep and ResultOfStep answer with runID and startErr, and with stepResult and
// resultErr: twin step's own tests give the fake its step answers (M11). Each holds as
// StartProvision and Result do, under startBlocks and release.
func (f *fakeService) StartStep(ctx context.Context, in provision.StepInput) (string, error) {
	f.mutating("StartStep")
	f.mu.Lock()
	f.calls = append(f.calls, "StartStep")
	f.stepped = append(f.stepped, in)
	blocks, runID, err := f.startBlocks, f.runID, f.startErr
	f.mu.Unlock()
	if blocks {
		<-ctx.Done()
		f.mu.Lock()
		f.abandoned = true
		f.mu.Unlock()
	}
	return runID, err
}

func (f *fakeService) ResultOfStep(ctx context.Context, _ string) (provision.StepResult, error) {
	if f.release != nil {
		select {
		case <-f.release:
		case <-ctx.Done():
			return provision.StepResult{}, ctx.Err()
		}
	}
	return f.stepResult, f.resultErr
}

// StartRehearse and ResultOfRehearse answer with rehearseRun and startErr, and with
// rehearseResult and resultErr (015). Each holds as StartProvision and Result do, under
// startBlocks and release.
func (f *fakeService) StartRehearse(ctx context.Context, in provision.RehearseInput) (string, error) {
	f.mutating("StartRehearse")
	f.mu.Lock()
	f.calls = append(f.calls, "StartRehearse")
	f.rehearsed = append(f.rehearsed, in)
	blocks, runID, err := f.startBlocks, f.rehearseRun, f.startErr
	f.mu.Unlock()
	if blocks {
		<-ctx.Done()
		f.mu.Lock()
		f.abandoned = true
		f.mu.Unlock()
	}
	return runID, err
}

func (f *fakeService) ResultOfRehearse(ctx context.Context, _ string) (provision.RehearseResult, error) {
	if f.release != nil {
		select {
		case <-f.release:
		case <-ctx.Done():
			return provision.RehearseResult{}, ctx.Err()
		}
	}
	return f.rehearseResult, f.resultErr
}

func (f *fakeService) Close() {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.closed = true
}

// useService makes svc what the commands dial; nil makes dialling fail the test.
func useService(t *testing.T, svc provision.Service) {
	t.Helper()
	saved := dialService
	t.Cleanup(func() { dialService = saved })
	dialService = func(context.Context) (provision.Service, error) {
		if svc == nil {
			t.Error("the command dialled the workflow service")
			return nil, context.Canceled
		}
		return svc, nil
	}
}

// useInterrupts returns a channel the test sends interrupts on, in place of SIGINT.
func useInterrupts(t *testing.T) chan os.Signal {
	t.Helper()
	ch := make(chan os.Signal, 2)
	saved := notifyInterrupt
	t.Cleanup(func() { notifyInterrupt = saved })
	notifyInterrupt = func() (<-chan os.Signal, func()) { return ch, func() {} }
	return ch
}

func readyResult() provision.ProvisionResult {
	observed := "2026-09-15T14:22:12.000000Z"
	var nodes []wire.TwinNode
	for i, name := range []string{"n1", "n2", "n3"} {
		nodes = append(nodes, wire.TwinNode{
			Name: name, Container: "clab-fylgja-" + name, Image: "ghcr.io/nokia/srlinux:24.7.1",
			PSP:      &wire.PSPRef{ID: "nokia_srlinux", Source: "embedded"},
			MgmtIPv4: "172.20.20." + string(rune('2'+i)), ReadyAfterS: 0.9,
			Artifact:  &wire.TwinArtifact{Name: "device-config", ContentType: "text/plain", Checksum: fixtureArtifacts[name], Size: 707},
			PushedInS: 0.7,
		})
	}
	return provision.ProvisionResult{
		Outcome:    provision.OutcomeReady,
		BundleID:   fixtureBundleID,
		ObservedAt: observed,
		TwinDir:    "/abs/local/twin",
		Findings:   findings.List{},
		Twin: &wire.TwinRecord{
			TwinVersion: "10", Lab: "fylgja", BundleID: fixtureBundleID,
			Provenance: wire.Provenance{Branch: "fylgja-fixture", SchemaHash: "abc", Scope: "tag:fylgja", Mapping: dcimMapping},
			ObservedAt: &observed, Source: wire.SourceIntent,
			Run:           wire.RunRef{WorkflowID: provision.WorkflowProvision, RunID: "run-1"},
			ProvisionedBy: wire.ProvisionedBy{Version: "0.1.0-dev"},
			RecordedAt:    "2026-09-15T14:22:53Z",
			Nodes:         nodes,
		},
		Cleanup: provision.CleanupResult{Teardown: provision.CleanupSkipped, Unstage: provision.CleanupSkipped},
	}
}

func exitOf(t *testing.T, err error) (int, *findings.Document) {
	t.Helper()
	var res *result
	if !asResult(err, &res) {
		t.Fatalf("command returned %v, want a findings result", err)
	}
	return res.doc.Status.ExitCode(), res.doc
}

func TestCreateReadyPrintsTheTwin(t *testing.T) {
	paths := useFixtureRead(t)
	svc := &fakeService{runID: "run-1", result: readyResult(), events: []provision.Event{
		{Step: "read"},
		{Step: "read", End: true, Outcome: provision.EventDone, Duration: 2100 * time.Millisecond},
		{Step: "compile"},
		{Step: "compile", End: true, Outcome: provision.EventDone, Duration: 100 * time.Millisecond, Detail: "bundle_id " + fixtureBundleID},
		{Step: "readiness n1", End: true, Outcome: provision.EventDone, Duration: 9800 * time.Millisecond},
		// M5: one push per node, between readiness and the record (contracts/cli.md).
		{Step: "push n1"},
		{Step: "push n1", End: true, Outcome: provision.EventDone, Duration: 700 * time.Millisecond},
		{Step: "record"},
		{Step: "record", End: true, Outcome: provision.EventDone, Duration: 20 * time.Millisecond},
	}}
	useService(t, svc)
	useInterrupts(t)

	var err error
	out := captureStdout(t, func() {
		err = runCreate(context.Background(), &options{}, &createFlags{branch: "fylgja-fixture"})
	})
	if code, doc := exitOf(t, err); code != findings.ExitOK {
		t.Fatalf("exit %d, findings %+v; want 0", code, doc.Findings)
	}
	// The server's read, take, compile and filing print first, before the run's start (018).
	want := strings.Join(append(storedLines(paths, headSnapshotID, headBundleID),
		"run fylgja-provision run-1",
		"step read: begins",
		"step read: done in 2.1s",
		"step compile: begins",
		"step compile: done in 0.1s (bundle_id "+fixtureBundleID+")",
		"step readiness n1: ready in 9.8s",
		"step push n1: begins",
		"step push n1: done in 0.7s",
		"step record: begins",
		"step record: done in 0.0s",
		"twin ready: bundle_id "+fixtureBundleID,
		"  n1  172.20.20.2",
		"  n2  172.20.20.3",
		"  n3  172.20.20.4",
		// The record's line, as twin show prints it (017): the scope and the mapping the read
		// was made under.
		"record: branch fylgja-fixture, snapshot none, bundle_id "+fixtureBundleID+", schema abc, "+showRead,
		"twin directory /abs/local/twin",
	), "\n") + "\n"
	if out != want {
		t.Errorf("stdout:\n%s\nwant:\n%s", out, want)
	}
	if len(svc.started) != 1 || svc.started[0].Source != wire.SourceIntent || svc.started[0].Branch != "fylgja-fixture" {
		t.Errorf("started %+v, want one intent run for fylgja-fixture", svc.started)
	}
	if !svc.closed {
		t.Error("the connection to the workflow service was not closed")
	}
}

func TestCreateJSONDocumentCarriesTheTwin(t *testing.T) {
	useFixtureRead(t)
	useService(t, &fakeService{runID: "run-1", result: readyResult()})
	useInterrupts(t)

	var err error
	out := captureStdout(t, func() {
		err = runCreate(context.Background(), &options{asJSON: true}, &createFlags{branch: "fylgja-fixture"})
	})
	if out != "" {
		t.Errorf("--json printed progress on stdout:\n%s", out)
	}
	code, doc := exitOf(t, err)
	if code != findings.ExitOK || doc.Twin == nil || len(doc.Twin.Nodes) != 3 || doc.Subject.RunID != "run-1" {
		t.Fatalf("exit %d, document %+v; want 0 with a three-node twin block and the run id", code, doc)
	}
	// Each node names what it was pushed, projected from twin.json's four artifact fields to
	// name and checksum, and how long the push took.
	for _, n := range doc.Twin.Nodes {
		want := findings.ShowArtifact{Name: "device-config", Checksum: fixtureArtifacts[n.Name]}
		if n.Artifact == nil || *n.Artifact != want || n.PushedInS != 0.7 {
			t.Errorf("twin node %s: artifact %+v, pushed in %v; want %+v in 0.7s", n.Name, n.Artifact, n.PushedInS, want)
		}
	}
	// The snapshot the server took names the document beside the run's bundle (018).
	if doc.SnapshotID != headSnapshotID {
		t.Errorf("snapshot_id %q, want the take's %s", doc.SnapshotID, headSnapshotID)
	}
	validateM10Document(t, doc)
}

func TestCreateRefusesBeforeDialling(t *testing.T) {
	useService(t, nil)

	t.Run("at finer than microseconds", func(t *testing.T) {
		err := runCreate(context.Background(), &options{asJSON: true},
			&createFlags{branch: "fylgja-fixture", at: "2026-09-15T14:22:12.1234567Z"})
		code, doc := exitOf(t, err)
		if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleAtPrecision {
			t.Errorf("exit %d, findings %+v; want 2 with %s", code, doc.Findings, findings.RuleAtPrecision)
		}
	})
	t.Run("branch missing", func(t *testing.T) {
		code, doc := exitOf(t, runCreate(context.Background(), &options{asJSON: true}, &createFlags{}))
		if code != findings.ExitError || !strings.Contains(doc.Findings[0].Message, "--branch") {
			t.Errorf("exit %d, findings %+v; want 2 naming --branch", code, doc.Findings)
		}
	})
}

// No service and no worker are exit 2 under their own identifiers, not a wait.
func TestCreateStartRefusals(t *testing.T) {
	useFixtureRead(t)
	for _, c := range startRefusals() {
		t.Run(c.name, func(t *testing.T) {
			c.use(t)
			wantStartRefusal(t, runCreate(context.Background(), &options{asJSON: true}, &createFlags{branch: "fylgja-fixture"}), c.rule)
		})
	}
}

// The first interrupt cancels the run and keeps waiting for its cleanup; the exit status
// is then the run's.
func TestCreateFirstInterruptCancelsAndWaits(t *testing.T) {
	useFixtureRead(t)
	interrupts := useInterrupts(t)
	release := make(chan struct{})
	svc := &fakeService{runID: "run-1", release: release, result: provision.ProvisionResult{
		Outcome: provision.OutcomeCancelled, BundleID: fixtureBundleID, Step: findings.StepDeploy, Findings: findings.List{},
		Cleanup: provision.CleanupResult{Teardown: provision.CleanupDone, Unstage: provision.CleanupDone},
	}}
	svc.onCancel = func() { close(release) }
	useService(t, svc)
	interrupts <- os.Interrupt

	code, doc := exitOf(t, runCreate(context.Background(), &options{asJSON: true}, &createFlags{branch: "fylgja-fixture"}))
	if svc.cancels != 1 {
		t.Errorf("Cancel called %d times, want once", svc.cancels)
	}
	if code != findings.ExitFailed || doc.Cleanup == nil {
		t.Errorf("exit %d, document %+v; want 3 with the cleanup the run reported", code, doc)
	}
}

// A second interrupt stops waiting: exit 2, run.cancelled, and the run is left to finish
// on the service.
func TestCreateSecondInterruptStopsWaiting(t *testing.T) {
	useFixtureRead(t)
	interrupts := useInterrupts(t)
	svc := &fakeService{runID: "run-1", release: make(chan struct{})}
	useService(t, svc)
	interrupts <- os.Interrupt
	interrupts <- os.Interrupt

	code, doc := exitOf(t, runCreate(context.Background(), &options{asJSON: true}, &createFlags{branch: "fylgja-fixture"}))
	if svc.cancels != 1 {
		t.Errorf("Cancel called %d times, want once", svc.cancels)
	}
	if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleRunCancelled {
		t.Fatalf("exit %d, findings %+v; want 2 with %s", code, doc.Findings, findings.RuleRunCancelled)
	}
	if msg := doc.Findings[0].Message; !strings.Contains(msg, "fylgja twin destroy") || doc.Findings[0].Object != "run-1" {
		t.Errorf("finding %+v, want the run id and fylgja twin destroy named", doc.Findings[0])
	}
	validateM10Document(t, doc)
}

// A run that stopped short of ready after the host check cleared says, in text, what its
// cleanup removed, whether or not its progress lines arrived; one cancelled before the host
// check touched nothing and says nothing of cleanup.
func TestCreateStoppedShortReportsWhatCleanupRemoved(t *testing.T) {
	paths := useFixtureRead(t)
	deployFailed := findings.List{{Severity: findings.Rejection, Rule: findings.RuleDeployFailed, Object: "lab fylgja",
		Step: findings.StepDeploy, Message: "clab deploy exited 1"}}
	for _, c := range []struct {
		name     string
		result   provision.ProvisionResult
		wantCode int
		want     []string
	}{
		{"failed after deploy began", provision.ProvisionResult{
			Outcome: provision.OutcomeFailed, BundleID: fixtureBundleID, Step: findings.StepDeploy, Findings: deployFailed,
			Cleanup: provision.CleanupResult{Teardown: provision.CleanupDone, Unstage: provision.CleanupDone,
				Removed: []string{"lab fylgja (3 containers)", "twin directory /abs/local/twin"}},
		}, findings.ExitFailed, []string{"removed lab fylgja (3 containers)", "removed twin directory /abs/local/twin"}},
		{"failed with nothing on the host", provision.ProvisionResult{
			Outcome: provision.OutcomeFailed, BundleID: fixtureBundleID, Step: findings.StepDeploy, Findings: deployFailed,
			Cleanup: provision.CleanupResult{Teardown: provision.CleanupNothing, Unstage: provision.CleanupNothing},
		}, findings.ExitFailed, []string{"nothing to remove: no lab fylgja, no twin directory"}},
		{"cancelled before the host check", provision.ProvisionResult{
			Outcome: provision.OutcomeCancelled, Step: findings.StepRead, Findings: findings.List{},
			Cleanup: provision.CleanupResult{Teardown: provision.CleanupSkipped, Unstage: provision.CleanupSkipped},
		}, findings.ExitError, nil},
	} {
		t.Run(c.name, func(t *testing.T) {
			useService(t, &fakeService{runID: "run-1", result: c.result})
			useInterrupts(t)

			var err error
			out := captureStdout(t, func() {
				err = runCreate(context.Background(), &options{}, &createFlags{branch: "fylgja-fixture"})
			})
			if code, doc := exitOf(t, err); code != c.wantCode {
				t.Fatalf("exit %d, findings %+v; want %d", code, doc.Findings, c.wantCode)
			}
			want := strings.Join(append(append(storedLines(paths, headSnapshotID, headBundleID), "run fylgja-provision run-1"), c.want...), "\n") + "\n"
			if out != want {
				t.Errorf("stdout:\n%s\nwant:\n%s", out, want)
			}

			err = nil
			out = captureStdout(t, func() {
				err = runCreate(context.Background(), &options{asJSON: true}, &createFlags{branch: "fylgja-fixture"})
			})
			if out != "" {
				t.Errorf("--json printed on stdout:\n%s", out)
			}
			_, doc := exitOf(t, err)
			validateM10Document(t, doc)
		})
	}
}

// validateM2Document validates a document against M2's findings contract.
func validateM2Document(t *testing.T, doc *findings.Document) {
	t.Helper()
	validateDocument(t, contractPath("002-provision-destroy", "findings.schema.json"), doc)
}

// validateDocument validates a document against the findings schema at schemaPath, an
// older contract than the current one: what 017 changed is held to the current contract and
// put back as the older one reads it (asEarlierContract).
func validateDocument(t *testing.T, schemaPath string, doc *findings.Document) {
	t.Helper()
	b := asEarlierContract(t, doc)
	f, err := os.Open(schemaPath)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = f.Close() }()
	schemaDoc, err := jsonschema.UnmarshalJSON(f)
	if err != nil {
		t.Fatal(err)
	}
	c := jsonschema.NewCompiler()
	if err := c.AddResource("findings.schema.json", schemaDoc); err != nil {
		t.Fatal(err)
	}
	schema, err := c.Compile("findings.schema.json")
	if err != nil {
		t.Fatal(err)
	}
	v, err := jsonschema.UnmarshalJSON(bytes.NewReader(b))
	if err != nil {
		t.Fatal(err)
	}
	if err := schema.Validate(v); err != nil {
		t.Errorf("document does not satisfy %s:\n%v\n%s", schemaPath, err, b)
	}
}

// asEarlierContract is doc as a contract older than 017's reads it, marshalled: a document
// naming what 017 added, a subject's scope or a show record's scope and mapping, is
// validated whole against the current contract; then the subject's scope is left out,
// which is every older contract's subject, and a show record's provenance is put back as
// the contract version every older contract requires in its place (017; contracts/
// formats.md, "The findings blocks"). The snapshot ids 018 writes as null are taken out
// first (dropNullSnapshots).
func asEarlierContract(t *testing.T, doc *findings.Document) []byte {
	t.Helper()
	scoped := doc.Subject != nil && doc.Subject.Scope != ""
	recorded := doc.Show != nil && doc.Show.Record != nil
	if scoped || (recorded && doc.Show.Record.Scope != "") {
		validateWithShow(t, currentContract, "017", doc)
	}
	b, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	var generic map[string]any
	if err := json.Unmarshal(b, &generic); err != nil {
		t.Fatal(err)
	}
	dropNullSnapshots(generic)
	restore018Kind(generic)
	if subject, ok := generic["subject"].(map[string]any); ok {
		delete(subject, "scope")
	}
	if show, ok := generic["show"].(map[string]any); ok {
		if record, ok := show["record"].(map[string]any); ok {
			delete(record, "scope")
			delete(record, "mapping")
			record["contract_version"] = "0.2"
		}
	}
	if b, err = json.Marshal(generic); err != nil {
		t.Fatal(err)
	}
	return b
}

// validateM4Document validates a document against M4's findings contract, with the show
// block's schema added under its $id.
func validateM4Document(t *testing.T, doc *findings.Document) {
	t.Helper()
	validateWithShow(t, "004-walking", "M4", doc)
}

// validateM5Document validates a document against M5's findings contract, the same way: a
// document naming an artifact or step push is M5's.
func validateM5Document(t *testing.T, doc *findings.Document) {
	t.Helper()
	validateWithShow(t, "005-configuration", "M5", doc)
}

// validateM6Document validates a document against M6's findings contract: a dry run
// always carries dry_run.lossy_mappings and shared_ports, which M5's forbids.
func validateM6Document(t *testing.T, doc *findings.Document) {
	t.Helper()
	validateWithShow(t, "006-psp-lossy-mapping", "M6", doc)
}

// validateM7Document validates a document against M7's findings contract: a show node
// always carries psp, the package id twin.json records for it, which M6's forbids.
func validateM7Document(t *testing.T, doc *findings.Document) {
	t.Helper()
	validateWithShow(t, "007-eos-platform", "M7", doc)
}

// validateM10Document validates a document against the newest findings contract, with
// the show block's, the stage blocks', the step block's, the verify block's and the
// rehearsal block's schemas added under their $ids. A document naming a stage is 014's; the
// newest contract, under the module root's contracts/,
// extends M11's additively and accepts it, so the documents this build writes are read
// against that.
//
// 018 is additive: a document that names no snapshot is 017's too, so it is also validated
// against 017's frozen copy, the null snapshot ids taken out (as017Contract).
//
// 019 removes following and puts kind snapshot in place of pinned and frozen: a document of
// this build is 018's too, its kind as 018 wrote it (as018Contract), so it is also validated
// against 018's frozen copy.
//
// 016 moves the step, verify, rehearsal and findings contracts on: a document of this build
// is 019's as built, so it is also validated against 019's frozen copy.
func validateM10Document(t *testing.T, doc *findings.Document) {
	t.Helper()
	validateWithShow(t, currentContract, "M13", doc)
	validateWithShow(t, contract019, "019", doc)
	validateWithShow(t, contract018, "018", doc)
	if !namesSnapshot(t, doc) {
		validateWithShow(t, contract017, "017", doc)
	}
}

// contract017 is the feature argument that names 017's copies of the findings contract and
// the four blocks 018 moves, frozen under testdata/contracts/017-dcim-reader/.
const contract017 = "017-dcim-reader"

// contract018 is the feature argument that names 018's copies of the findings contract and
// the show block, the two 019 moves, frozen under testdata/contracts/018-snapshots/.
const contract018 = "018-snapshots"

// contract019 is the feature argument that names 019's copies of the findings contract and
// the step, verify and rehearsal blocks, the four 016 moves, frozen under
// testdata/contracts/019-following-removed/.
const contract019 = "019-following-removed"

// namesSnapshot says whether doc names a snapshot anywhere 018 puts one: such a document is
// 018's, which no earlier contract accepts.
func namesSnapshot(t *testing.T, doc *findings.Document) bool {
	t.Helper()
	b, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	return strings.Contains(string(b), `"snapshot_id":"`) || strings.Contains(string(b), `"snapshot":"`)
}

// dropNullSnapshots removes the snapshot ids 018 writes as null where a block names none:
// the show record's, each plan stage's and each rehearsal stage's. Every contract before
// 018's forbids the key, and from 018 each is always written. An id that is set is left, so
// an earlier contract still refuses a document naming a snapshot.
func dropNullSnapshots(generic map[string]any) {
	dropNull := func(m any) {
		if o, ok := m.(map[string]any); ok {
			if v, ok := o["snapshot_id"]; ok && v == nil {
				delete(o, "snapshot_id")
			}
		}
	}
	if show, ok := generic["show"].(map[string]any); ok {
		dropNull(show["record"])
	}
	for _, block := range []string{"plan", "rehearsal"} {
		if b, ok := generic[block].(map[string]any); ok {
			stages, _ := b["stages"].([]any)
			for _, st := range stages {
				dropNull(st)
			}
		}
	}
}

// restore018Kind gives a show block of kind snapshot (019) the kind every build before 019
// wrote for the same twin, not following: pinned when its record names an at, and frozen
// otherwise. Every other block is left as it is, so an earlier contract is still asked about
// everything else 019 writes.
func restore018Kind(generic map[string]any) {
	show, ok := generic["show"].(map[string]any)
	if !ok || show["kind"] != findings.ShowKindSnapshot {
		return
	}
	show["kind"] = "frozen"
	if record, ok := show["record"].(map[string]any); ok {
		if at, _ := record["at"].(string); at != "" {
			show["kind"] = "pinned"
		}
	}
}

// as018Contract is doc as 018's contract reads it, marshalled: the show kind as 018 wrote it
// (restore018Kind), and nothing else.
func as018Contract(t *testing.T, doc *findings.Document) []byte {
	t.Helper()
	b, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	var generic map[string]any
	if err := json.Unmarshal(b, &generic); err != nil {
		t.Fatal(err)
	}
	restore018Kind(generic)
	if b, err = json.Marshal(generic); err != nil {
		t.Fatal(err)
	}
	return b
}

// as017Contract is doc as 017's contract reads it, marshalled: the null snapshot ids taken
// out and the show kind as 017 wrote it, and nothing else.
func as017Contract(t *testing.T, doc *findings.Document) []byte {
	t.Helper()
	b, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	var generic map[string]any
	if err := json.Unmarshal(b, &generic); err != nil {
		t.Fatal(err)
	}
	dropNullSnapshots(generic)
	restore018Kind(generic)
	if b, err = json.Marshal(generic); err != nil {
		t.Fatal(err)
	}
	return b
}

// validateWithShow validates doc against feature's findings contract, with the show
// block's schema added under its $id, from 014 the stage blocks', from M11 the step
// block's, from M12 the verify block's and from 015 the rehearsal block's under theirs.
func validateWithShow(t *testing.T, feature, milestone string, doc *findings.Document) {
	t.Helper()
	var b []byte
	switch feature {
	case contract017:
		b = as017Contract(t, doc)
	case contract018:
		b = as018Contract(t, doc)
	case currentContract, contract019:
		var err error
		if b, err = json.Marshal(doc); err != nil {
			t.Fatal(err)
		}
	default:
		b = asEarlierContract(t, doc)
	}
	if err := validateAgainst(findingsContract(t, feature), b); err != nil {
		t.Errorf("document does not satisfy %s's findings contract:\n%v\n%s", milestone, err, b)
	}
}

// findingsContracts holds each feature's findings contract once compiled, by feature
// directory. Compiling one took most of this package's test time when every document
// compiled its own; a contract that does not load is not
// kept, so each caller fails on it.
var findingsContracts = struct {
	sync.Mutex
	byFeature map[string]*jsonschema.Schema
}{byFeature: map[string]*jsonschema.Schema{}}

// currentContract is the feature argument that names the module root's contracts/, which
// holds the current contract. Any other names an older feature's frozen copy, under this
// package's testdata/contracts/<feature>/.
const currentContract = ""

// contractPath is where feature's copy of the contract file name is read.
func contractPath(feature, name string) string {
	if feature == currentContract {
		return repoPath("contracts", name)
	}
	return filepath.Join("testdata", "contracts", feature, name)
}

// findingsContract returns feature's findings contract, compiled with the schemas
// validateWithShow names, compiling it on the first call for the feature.
func findingsContract(t *testing.T, feature string) *jsonschema.Schema {
	t.Helper()
	findingsContracts.Lock()
	defer findingsContracts.Unlock()
	if schema, ok := findingsContracts.byFeature[feature]; ok {
		return schema
	}
	load := func(path string) any {
		f, err := os.Open(path)
		if err != nil {
			t.Fatal(err)
		}
		defer func() { _ = f.Close() }()
		v, err := jsonschema.UnmarshalJSON(f)
		if err != nil {
			t.Fatal(err)
		}
		return v
	}
	refers, err := os.ReadFile(contractPath(feature, "findings.schema.json"))
	if err != nil {
		t.Fatal(err)
	}
	c := jsonschema.NewCompiler()
	for _, name := range []string{"show.schema.json", "stages.schema.json", "step.schema.json", "verify.schema.json", "rehearsal.schema.json"} {
		path := contractPath(feature, name)
		if _, err := os.Stat(path); err != nil {
			// A block the feature's contract refers to but its directory does not hold had not
			// moved since the feature: 017's verify.schema.json, which 018 does not move, and
			// 018's stages, step, verify and rehearsal blocks, which 019 does not freeze, and
			// 019's show and stages blocks, which 016 does not move.
			if feature == currentContract || !strings.Contains(string(refers), "/schemas/"+name) {
				continue
			}
			path = contractPath(currentContract, name)
		}
		if err := c.AddResource("https://github.com/happypathnetworking/fylgja/schemas/"+name, load(path)); err != nil {
			t.Fatal(err)
		}
	}
	if err := c.AddResource("findings.schema.json", load(contractPath(feature, "findings.schema.json"))); err != nil {
		t.Fatal(err)
	}
	schema, err := c.Compile("findings.schema.json")
	if err != nil {
		t.Fatal(err)
	}
	findingsContracts.byFeature[feature] = schema
	return schema
}

// validateAgainst validates the JSON document b against schema.
func validateAgainst(schema *jsonschema.Schema, b []byte) error {
	v, err := jsonschema.UnmarshalJSON(bytes.NewReader(b))
	if err != nil {
		return err
	}
	return schema.Validate(v)
}

// The cached contract still validates: a document it accepts is refused once one field is
// broken, by the contract a second call takes from the cache.
func TestFindingsContractCachedStillValidates(t *testing.T) {
	first := findingsContract(t, currentContract)
	cached := findingsContract(t, currentContract)
	if cached != first {
		t.Fatal("the second call compiled the contract again; want the cached one")
	}
	b, err := json.Marshal(findings.NewDocument("twin.show", nil, nil))
	if err != nil {
		t.Fatal(err)
	}
	if err := validateAgainst(cached, b); err != nil {
		t.Fatalf("an unbroken document is refused: %v\n%s", err, b)
	}
	broken := bytes.Replace(b, []byte(`"status":"ok"`), []byte(`"status":"banana"`), 1)
	if bytes.Equal(broken, b) {
		t.Fatalf("no status to break in %s", b)
	}
	if err := validateAgainst(cached, broken); err == nil {
		t.Errorf("a document whose status is banana passed the cached contract:\n%s", broken)
	}
}

// The scope a create names is its run's and its document's, over the server's default; with
// none, the default is (017).
func TestCreateCarriesItsScope(t *testing.T) {
	for _, c := range []struct {
		name  string
		flags createFlags
		want  string
	}{
		{"given", createFlags{branch: "fylgja-fixture", scope: "tag:lab-b", scopeGiven: true}, "tag:lab-b"},
		{"the default", createFlags{branch: "fylgja-fixture"}, defaultScope},
	} {
		t.Run(c.name, func(t *testing.T) {
			// The server reads under the scope before the run (018): the fake tags the
			// fixture's devices with the scope's tag, so either reads the fixture.
			f := newFakeInfrahub(t)
			f.tag = strings.TrimPrefix(c.want, "tag:")
			f.start()
			useStateRoot(t)
			svc := &fakeService{runID: "run-1", result: readyResult()}
			useService(t, svc)
			useInterrupts(t)
			var err error
			captureStdout(t, func() { err = runCreate(context.Background(), &options{asJSON: true}, &c.flags) })
			code, doc := exitOf(t, err)
			if code != findings.ExitOK || len(svc.started) != 1 {
				t.Fatalf("exit %d, started %+v; want 0 and one run", code, svc.started)
			}
			if svc.started[0].Scope != c.want || doc.Subject == nil || doc.Subject.Scope != c.want {
				t.Errorf("the run's scope %q, the subject %+v; want %s in both", svc.started[0].Scope, doc.Subject, c.want)
			}
			validateM10Document(t, doc)
		})
	}
}

// --interval and --no-follow are no flags of any command (019, FR-003): through the command
// line, as an operator would type them, each is cobra's unknown flag, exit 2, refused before
// any request, so the harness's server logs none. twin create is asked from the branch head,
// where the flags meant something; every other command of the client's tree beside it.
func TestNoCommandTakesTheFollowingFlags(t *testing.T) {
	root := &cobra.Command{Use: "fylgja"}
	AddCommands(root, build)
	var commands [][]string
	var walk func(cmd *cobra.Command)
	walk = func(cmd *cobra.Command) {
		if cmd.Runnable() && cmd != root {
			commands = append(commands, strings.Fields(cmd.CommandPath())[1:])
		}
		for _, sub := range cmd.Commands() {
			walk(sub)
		}
	}
	walk(root)
	var ops []string
	for _, path := range commands {
		ops = append(ops, strings.Join(path, "."))
	}
	if !slices.Equal(slices.Sorted(slices.Values(ops)), slices.Sorted(slices.Values(api.Operations))) {
		t.Fatalf("the walk found %v; want the API's operations %v", ops, api.Operations)
	}

	for _, path := range commands {
		for _, flag := range [][]string{{"--interval", "30s"}, {"--no-follow"}} {
			args := append(append([]string{}, path...), flag...)
			if strings.Join(path, " ") == "twin create" {
				args = append([]string{"twin", "create", "--branch", "b"}, flag...)
			}
			t.Run(strings.Join(args, " "), func(t *testing.T) {
				awaitIdle(t)
				before := requestsLogged()
				opts := &options{}
				root := &cobra.Command{Use: "fylgja", SilenceUsage: true, SilenceErrors: true}
				root.PersistentFlags().BoolVar(&opts.asJSON, "json", false, "")
				for _, cmd := range []*cobra.Command{newIntentCmd(opts), newTwinCmd(opts), newStageCmd(opts),
					newSchemaCmd(opts), newPSPCmd(opts)} {
					root.AddCommand(cmd)
				}
				// --json comes first: cobra stops reading flags at the unknown one.
				root.SetArgs(append([]string{"--json"}, args...))
				var code int
				out := captureStdout(t, func() {
					cmd, err := root.ExecuteC()
					code = report(opts, cmd, err)
				})
				var doc findings.Document
				if err := json.Unmarshal([]byte(out), &doc); err != nil {
					t.Fatalf("stdout is not one findings document: %v\n%s", err, out)
				}
				if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0].Message != "unknown flag: "+flag[0] {
					t.Errorf("exit %d, findings %+v; want 2, cobra's unknown flag %s", code, doc.Findings, flag[0])
				}
				awaitIdle(t)
				if got := requestsLogged(); got != before {
					t.Errorf("the server logged %d requests, want none", got-before)
				}
			})
		}
	}
}

// A create from the branch head follows nothing (019; US1 scenario 1): its run's input is
// M3's for the same flags, compiled on the server, with no follow; its text ends at the twin
// directory; and its document carries no following key.
func TestCreateFollowsNothing(t *testing.T) {
	paths := useFixtureRead(t)
	svc := &fakeService{runID: "run-1", result: readyResult()}
	useService(t, svc)
	useInterrupts(t)

	var err error
	out := captureStdout(t, func() {
		err = runCreate(context.Background(), &options{}, &createFlags{branch: "fylgja-fixture"})
	})
	if code, doc := exitOf(t, err); code != findings.ExitOK {
		t.Fatalf("exit %d, findings %+v; want 0", code, doc.Findings)
	}
	if len(svc.started) != 1 {
		t.Fatalf("started %+v, want one run", svc.started)
	}
	b, err := json.Marshal(svc.started[0])
	if err != nil {
		t.Fatal(err)
	}
	// Compiled on the server (018): the bundle and the snapshot by id, and the read's time.
	want := `{"source":"intent","branch":"fylgja-fixture","at":"","bundle_path":"` + filepath.Join(paths.Bundles, headBundleID) +
		`","bundle_id":"` + headBundleID + `","version":"` + version + `","observed_at":"` + svc.started[0].ObservedAt +
		`","scope":"tag:fylgja","snapshot_id":"` + headSnapshotID + `"}`
	if string(b) != want || svc.started[0].ObservedAt == "" {
		t.Errorf("input\n  %s\nwant M3's with 017's scope, the server's default, and 018's compiled input\n  %s", b, want)
	}
	if want := "\ntwin directory /abs/local/twin\n"; !strings.HasSuffix(out, want) || strings.Contains(out, "follow") {
		t.Errorf("stdout:\n%s\nwant it to end at the twin directory, naming no following", out)
	}

	err = nil
	captureStdout(t, func() {
		err = runCreate(context.Background(), &options{asJSON: true}, &createFlags{branch: "fylgja-fixture"})
	})
	_, doc := exitOf(t, err)
	if raw, err := json.Marshal(doc); err != nil || bytes.Contains(raw, []byte(`"following"`)) {
		t.Errorf("the document carries a following key (%v): %s", err, raw)
	}
	validateM10Document(t, doc)
}
