package cli

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/santhosh-tekuri/jsonschema/v6"
	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
)

const fixtureBundleID = "43d917158d2b601cd2cdeb6aafd56d367224d757c4ce3f67fdf3c206e2c5a386"

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
	// stopEvents, stopResult and stopErr answer StopFollowing, which only twin destroy
	// calls; the zero value is no following.
	stopEvents []provision.Event
	stopResult provision.FollowStop
	stopErr    error
	// following, lastCheck and inFlight answer twin show's reads, with readErr beside each;
	// readBlocks holds every read until its context is done, as a service that never answers.
	following  *provision.FollowingState
	lastCheck  *provision.CheckRecord
	inFlight   []provision.RunInFlight
	readErr    error
	readBlocks bool
	// failRead, when set, names the one read that fails with failReadErr; the others answer.
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
	// calls logs StartProvision, StartDestroy and StopFollowing in the order they came.
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

func (f *fakeService) Following(ctx context.Context) (*provision.FollowingState, error) {
	if err := f.read(ctx, "Following"); err != nil {
		return nil, err
	}
	return f.following, nil
}

func (f *fakeService) LastCheck(ctx context.Context, _ *provision.FollowingState) (*provision.CheckRecord, error) {
	if err := f.read(ctx, "LastCheck"); err != nil {
		return nil, err
	}
	return f.lastCheck, nil
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

func (f *fakeService) StopFollowing(_ context.Context, onEvent func(provision.Event)) (provision.FollowStop, error) {
	f.mutating("StopFollowing")
	f.mu.Lock()
	f.calls = append(f.calls, "StopFollowing")
	f.mu.Unlock()
	for _, e := range f.stopEvents {
		onEvent(e)
	}
	return f.stopResult, f.stopErr
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
			PSP:      wire.PSPRef{ID: "nokia_srlinux", Source: "embedded"},
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
			TwinVersion: "8", Lab: "fylgja", BundleID: fixtureBundleID,
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
	want := strings.Join([]string{
		"run fylgja-provision run-1",
		"step read: begins",
		"step read: done in 2.1s",
		"step compile: begins",
		"step compile: done in 0.1s (bundle_id " + fixtureBundleID + ")",
		"step readiness n1: ready in 9.8s",
		"step push n1: begins",
		"step push n1: done in 0.7s",
		"step record: begins",
		"step record: done in 0.0s",
		"twin ready: bundle_id " + fixtureBundleID,
		"  n1  172.20.20.2",
		"  n2  172.20.20.3",
		"  n3  172.20.20.4",
		// The record's line, as twin show prints it (017): the scope and the mapping the read
		// was made under.
		"record: branch fylgja-fixture, bundle_id " + fixtureBundleID + ", schema abc, " + showRead,
		"twin directory /abs/local/twin",
	}, "\n") + "\n"
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
	validateM5Document(t, doc)
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
	validateM2Document(t, doc)
}

// A run that stopped short of ready after the host check cleared says, in text, what its
// cleanup removed, whether or not its progress lines arrived; one cancelled before the host
// check touched nothing and says nothing of cleanup.
func TestCreateStoppedShortReportsWhatCleanupRemoved(t *testing.T) {
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
			want := strings.Join(append([]string{"run fylgja-provision run-1"}, c.want...), "\n") + "\n"
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
			validateM2Document(t, doc)
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
func validateM10Document(t *testing.T, doc *findings.Document) {
	t.Helper()
	validateWithShow(t, currentContract, "M13", doc)
	if !namesSnapshot(t, doc) {
		validateWithShow(t, contract017, "017", doc)
	}
}

// contract017 is the feature argument that names 017's copies of the findings contract and
// the four blocks 018 moves, frozen under testdata/contracts/017-dcim-reader/.
const contract017 = "017-dcim-reader"

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

// as017Contract is doc as 017's contract reads it, marshalled: the null snapshot ids taken
// out, and nothing else.
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
	case currentContract:
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
	if err := c.AddResource("https://github.com/happypathnetworking/fylgja/schemas/show.schema.json", load(contractPath(feature, "show.schema.json"))); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"stages.schema.json", "step.schema.json", "verify.schema.json", "rehearsal.schema.json"} {
		path := contractPath(feature, name)
		if _, err := os.Stat(path); err != nil {
			// A block the feature's contract refers to but its directory does not hold had not
			// moved since the feature: 017's verify.schema.json, which 018 does not move.
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

// followingResult is readyResult with following begun at interval seconds.
func followingResult(intervalS int) provision.ProvisionResult {
	res := readyResult()
	res.Following = &provision.FollowingResult{Branch: "fylgja-fixture", IntervalS: intervalS, ScheduleID: provision.FollowScheduleID}
	return res
}

// --interval that is not a duration, or is below the floor, is refused before anything is
// dialled (contracts/cli.md, create step 1). One given empty is not a duration either, and is
// refused before the conflict guard as any other is.
func TestCreateIntervalRefusals(t *testing.T) {
	for _, c := range []struct {
		args           []string
		value, message string
	}{
		{[]string{"--interval", "banana"}, "banana", `--interval banana is not a duration: time: invalid duration "banana"`},
		{[]string{"--interval", "5s"}, "5s", "--interval 5s is below the floor 10s"},
		{[]string{"--interval="}, "", `--interval  is not a duration: time: invalid duration ""`},
		{[]string{"--at", "2026-09-16T14:00:00Z", "--interval="}, "", `--interval  is not a duration: time: invalid duration ""`},
	} {
		t.Run(strings.Join(c.args, " "), func(t *testing.T) {
			useStateRoot(t)
			useInterrupts(t)
			svc := &fakeService{runID: "run-1", result: readyResult()}
			dialled := false
			saved := dialService
			t.Cleanup(func() { dialService = saved })
			dialService = func(context.Context) (provision.Service, error) { dialled = true; return svc, nil }

			code, doc := executeCreate(t, c.args...)
			want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleFollowIntervalInvalid, Object: c.value,
				Step: findings.StepStart, Message: c.message}
			if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0] != want {
				t.Errorf("exit %d, findings %+v; want 2 with %+v", code, doc.Findings, want)
			}
			if dialled || len(svc.calls) != 0 {
				t.Errorf("dialled %v, calls %v; want nothing", dialled, svc.calls)
			}
			validateM4Document(t, doc)
		})
	}
}

// executeCreate runs `fylgja twin create --branch fylgja-fixture --json` with args through the
// command line, as an operator would, and returns its exit status and findings document.
func executeCreate(t *testing.T, args ...string) (int, *findings.Document) {
	t.Helper()
	opts := &options{asJSON: true}
	root := &cobra.Command{Use: "fylgja", SilenceUsage: true, SilenceErrors: true}
	root.PersistentFlags().BoolVar(&opts.asJSON, "json", false, "")
	root.AddCommand(newTwinCmd(opts))
	root.SetArgs(append([]string{"twin", "create", "--branch", "fylgja-fixture", "--json"}, args...))
	var code int
	out := captureStdout(t, func() {
		cmd, err := root.ExecuteC()
		code = report(opts, cmd, err)
	})
	var doc findings.Document
	if err := json.Unmarshal([]byte(out), &doc); err != nil {
		t.Fatalf("%v: stdout is not one findings document: %v\n%s", args, err, out)
	}
	return code, &doc
}

// A create without --at follows its branch at the interval given, or every five minutes; its
// run stops any following itself, so the command stops none.
func TestCreateFollowsByDefault(t *testing.T) {
	for _, c := range []struct {
		interval  string
		intervalS int
		every     string
	}{{"", 300, "5m0s"}, {"15s", 15, "15s"}} {
		t.Run("interval "+c.every, func(t *testing.T) {
			svc := &fakeService{runID: "run-1", result: followingResult(c.intervalS)}
			useService(t, svc)
			useInterrupts(t)

			var err error
			out := captureStdout(t, func() {
				err = runCreate(context.Background(), &options{}, &createFlags{branch: "fylgja-fixture", interval: c.interval, intervalGiven: c.interval != ""})
			})
			if code, doc := exitOf(t, err); code != findings.ExitOK {
				t.Fatalf("exit %d, findings %+v; want 0", code, doc.Findings)
			}
			if len(svc.started) != 1 {
				t.Fatalf("started %+v, want one run", svc.started)
			}
			in := svc.started[0]
			if in.Follow == nil || in.Follow.IntervalS != c.intervalS || !in.StopFollowing {
				t.Errorf("input follow %+v, stop_following %v; want interval %d and stop_following", in.Follow, in.StopFollowing, c.intervalS)
			}
			if slices.Contains(svc.calls, "StopFollowing") {
				t.Errorf("calls %v: create stopped following itself, which its run does", svc.calls)
			}
			want := "twin directory /abs/local/twin\nfollowing branch fylgja-fixture, checked every " + c.every + " (schedule fylgja-follow)\n"
			if !strings.HasSuffix(out, want) {
				t.Errorf("stdout:\n%s\nwant it to end:\n%s", out, want)
			}

			err = nil
			captureStdout(t, func() {
				err = runCreate(context.Background(), &options{asJSON: true}, &createFlags{branch: "fylgja-fixture", interval: c.interval, intervalGiven: c.interval != ""})
			})
			_, doc := exitOf(t, err)
			wantBlock := findings.FollowingBlock{Branch: "fylgja-fixture", IntervalS: c.intervalS, ScheduleID: provision.FollowScheduleID,
				State: findings.FollowingStarted}
			if doc.Following == nil || *doc.Following != wantBlock {
				t.Errorf("following block %+v, want %+v", doc.Following, wantBlock)
			}
			validateM5Document(t, doc)
		})
	}
}

// A create whose run replaced another following says so before its success lines.
func TestCreateReplacesFollowing(t *testing.T) {
	res := followingResult(300)
	res.FollowingStopped = &provision.StopFollowingResult{Deleted: true, Branch: "other"}
	svc := &fakeService{runID: "run-1", result: res}
	useService(t, svc)
	useInterrupts(t)

	var err error
	out := captureStdout(t, func() {
		err = runCreate(context.Background(), &options{}, &createFlags{branch: "fylgja-fixture"})
	})
	if code, doc := exitOf(t, err); code != findings.ExitOK {
		t.Fatalf("exit %d, findings %+v; want 0", code, doc.Findings)
	}
	notice, ready := strings.Index(out, "following of branch other stopped\n"), strings.Index(out, "twin ready:")
	if notice < 0 || ready < notice {
		t.Errorf("stdout:\n%s\nwant the notice before the success lines", out)
	}
	if slices.Contains(svc.calls, "StopFollowing") {
		t.Errorf("calls %v: the command stopped following itself", svc.calls)
	}
}

// A ready run whose following could not begin: exit 0, the warning, and a not_started block.
func TestCreateFollowStartFailed(t *testing.T) {
	res := readyResult()
	res.Findings = findings.List{{Severity: findings.Warning, Rule: findings.RuleFollowStartFailed, Object: provision.FollowScheduleID,
		Step: findings.StepFollow, Message: provision.FollowStartFailedMessage("namespace unavailable")}}
	useService(t, &fakeService{runID: "run-1", result: res})
	useInterrupts(t)

	var err error
	out := captureStdout(t, func() {
		err = runCreate(context.Background(), &options{}, &createFlags{branch: "fylgja-fixture", interval: "1m", intervalGiven: true})
	})
	if code, doc := exitOf(t, err); code != findings.ExitOK {
		t.Fatalf("exit %d, findings %+v; want 0", code, doc.Findings)
	}
	if want := "twin directory /abs/local/twin\nnot following: follow.start.failed (see findings); destroy and create again\n"; !strings.HasSuffix(out, want) {
		t.Errorf("stdout:\n%s\nwant it to end:\n%s", out, want)
	}

	err = nil
	captureStdout(t, func() {
		err = runCreate(context.Background(), &options{asJSON: true}, &createFlags{branch: "fylgja-fixture", interval: "1m", intervalGiven: true})
	})
	_, doc := exitOf(t, err)
	want := findings.FollowingBlock{Branch: "fylgja-fixture", IntervalS: 60, State: findings.FollowingNotStarted}
	if doc.Following == nil || *doc.Following != want || !carriesRule(doc.Findings, findings.RuleFollowStartFailed) {
		t.Errorf("following %+v, findings %+v; want %+v and the warning", doc.Following, doc.Findings, want)
	}
	validateM5Document(t, doc)
}

// A run that could not stop following ended at step follow with the host untouched: exit 2,
// as any run ended before the host was touched, and the command stopped nothing itself.
func TestCreateFollowStopFailed(t *testing.T) {
	res := provision.ProvisionResult{
		Outcome: provision.OutcomeError, Step: findings.StepFollow, BundleID: fixtureBundleID,
		Findings: findings.List{{Severity: findings.Rejection, Rule: findings.RuleFollowStopFailed, Object: provision.FollowScheduleID,
			Step: findings.StepFollow, Message: provision.FollowStopFailedMessage(errors.New("permission denied"), "staged")}},
		Cleanup: provision.CleanupResult{Teardown: provision.CleanupSkipped, Unstage: provision.CleanupSkipped},
	}
	svc := &fakeService{runID: "run-1", result: res}
	useService(t, svc)
	useInterrupts(t)

	var err error
	out := captureStdout(t, func() {
		err = runCreate(context.Background(), &options{}, &createFlags{branch: "fylgja-fixture"})
	})
	code, doc := exitOf(t, err)
	if code != findings.ExitError || !carriesRule(doc.Findings, findings.RuleFollowStopFailed) {
		t.Errorf("exit %d, findings %+v; want 2 with follow.stop.failed", code, doc.Findings)
	}
	if out != "run fylgja-provision run-1\n" {
		t.Errorf("stdout:\n%s\nwant only the run line: nothing was touched, nothing removed", out)
	}
	if slices.Contains(svc.calls, "StopFollowing") {
		t.Errorf("calls %v: the command stopped following itself", svc.calls)
	}
	validateM4Document(t, doc)
}

// --interval given with --at or with --no-follow is refused before anything is dialled:
// the twin would not follow, so the interval would mean nothing (contracts/cli.md).
func TestCreateFlagsConflict(t *testing.T) {
	for _, c := range []struct {
		name    string
		flags   createFlags
		message string
	}{
		{"with --at", createFlags{branch: "fylgja-fixture", at: "2026-09-16T14:00:00Z", interval: "1m", intervalGiven: true},
			"--interval is meaningless with --at: a pinned twin never follows"},
		{"with --no-follow", createFlags{branch: "fylgja-fixture", noFollow: true, interval: "1m", intervalGiven: true},
			"--interval is meaningless with --no-follow: the twin will not follow"},
	} {
		t.Run(c.name, func(t *testing.T) {
			svc := &fakeService{runID: "run-1", result: readyResult()}
			dialled := false
			saved := dialService
			t.Cleanup(func() { dialService = saved })
			dialService = func(context.Context) (provision.Service, error) { dialled = true; return svc, nil }

			flags := c.flags
			code, doc := exitOf(t, runCreate(context.Background(), &options{asJSON: true}, &flags))
			want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleFollowFlagsConflict, Object: "--interval",
				Step: findings.StepStart, Message: c.message}
			if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0] != want {
				t.Errorf("exit %d, findings %+v; want 2 with %+v", code, doc.Findings, want)
			}
			if dialled || len(svc.calls) != 0 {
				t.Errorf("dialled %v, calls %v; want nothing", dialled, svc.calls)
			}
			validateM4Document(t, doc)
		})
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
		{"given", createFlags{branch: "fylgja-fixture", noFollow: true, scope: "tag:lab-b", scopeGiven: true}, "tag:lab-b"},
		{"the default", createFlags{branch: "fylgja-fixture", noFollow: true}, defaultScope},
	} {
		t.Run(c.name, func(t *testing.T) {
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

// A --no-follow create starts M3's run: its input is M3's for the same flags but for
// stop_following, which every run the CLI starts carries, and nothing follows.
func TestCreateNoFollow(t *testing.T) {
	svc := &fakeService{runID: "run-1", result: readyResult()}
	useService(t, svc)
	useInterrupts(t)

	var err error
	out := captureStdout(t, func() {
		err = runCreate(context.Background(), &options{}, &createFlags{branch: "fylgja-fixture", noFollow: true})
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
	want := `{"source":"intent","branch":"fylgja-fixture","at":"","bundle_path":"","bundle_id":"","version":"` + version +
		`","stop_following":true,"scope":"tag:fylgja"}`
	if string(b) != want {
		t.Errorf("input\n  %s\nwant M3's with stop_following, and 017's scope, the server's default\n  %s", b, want)
	}
	if want := "twin directory /abs/local/twin\nnot following\n"; !strings.HasSuffix(out, want) {
		t.Errorf("stdout:\n%s\nwant it to end:\n%s", out, want)
	}
	if slices.Contains(svc.calls, "StopFollowing") {
		t.Errorf("calls %v: the command stopped following itself", svc.calls)
	}

	err = nil
	captureStdout(t, func() {
		err = runCreate(context.Background(), &options{asJSON: true}, &createFlags{branch: "fylgja-fixture", noFollow: true})
	})
	_, doc := exitOf(t, err)
	if doc.Following != nil {
		t.Errorf("following block %+v, want none", doc.Following)
	}
	validateM5Document(t, doc)
}

// A pinned create never follows, with or without --no-follow, and says it is pinned.
func TestCreatePinnedNotFollowing(t *testing.T) {
	const at = "2026-09-16T14:00:00Z"
	for _, noFollow := range []bool{false, true} {
		t.Run(fmt.Sprintf("no-follow %v", noFollow), func(t *testing.T) {
			res := readyResult()
			res.Twin.Provenance.At = at
			svc := &fakeService{runID: "run-1", result: res}
			useService(t, svc)
			useInterrupts(t)

			var err error
			out := captureStdout(t, func() {
				err = runCreate(context.Background(), &options{}, &createFlags{branch: "fylgja-fixture", at: at, noFollow: noFollow})
			})
			if code, doc := exitOf(t, err); code != findings.ExitOK {
				t.Fatalf("exit %d, findings %+v; want 0", code, doc.Findings)
			}
			if len(svc.started) != 1 || svc.started[0].Follow != nil || !svc.started[0].StopFollowing {
				t.Errorf("started %+v, want one run with no follow and stop_following", svc.started)
			}
			if want := "twin directory /abs/local/twin\npinned at " + at + ", not following\n"; !strings.HasSuffix(out, want) {
				t.Errorf("stdout:\n%s\nwant it to end:\n%s", out, want)
			}
		})
	}
}

// Through the command line, only an --interval the operator gave conflicts: the flag's
// default, shown in the help, does not make --at or --no-follow a conflict.
func TestCreateIntervalDefaultIsNotGiven(t *testing.T) {
	useStateRoot(t)
	useService(t, nil)
	t.Setenv(intent.EnvAddress, unreachable)
	t.Setenv(intent.EnvToken, "any-token")
	for _, c := range []struct {
		args []string
		rule string
	}{
		{[]string{"--at", "2026-09-16T14:00:00Z"}, findings.RuleOperationFailed},
		{[]string{"--no-follow"}, findings.RuleOperationFailed},
		{[]string{"--no-follow", "--interval", "5m0s"}, findings.RuleFollowFlagsConflict},
	} {
		// A dry run whose read cannot reach Infrahub stops there, dialling nothing.
		code, doc := executeCreate(t, append([]string{"--dry-run"}, c.args...)...)
		if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0].Rule != c.rule {
			t.Errorf("%v: exit %d, findings %+v; want 2 with %s", c.args, code, doc.Findings, c.rule)
		}
	}
}
