package cli

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"io/fs"
	"log/slog"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/converter"
	tlog "go.temporal.io/sdk/log"
	"go.temporal.io/sdk/testsuite"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/stage"
	"github.com/happypathnetworking/fylgja/internal/verify"
)

// marker is what the fixture's artifacts carry in their role comment line:
// testsupport.MarkerRole("fylgja-fixture") less its "leaf-", spelled out because
// testsupport is built only under the contract and fixture tags. A surface that quotes a
// line of configuration carries it.
const marker = "FYLGJA-MARKER-fixture"

// surfaces collects what a run and the commands around it show anyone but the node: every
// document is marshalled into it, so a field added later is walked with the rest.
type surfaces struct {
	t  *testing.T
	mu sync.Mutex
	by map[string][]string
}

func newSurfaces(t *testing.T) *surfaces { return &surfaces{t: t, by: map[string][]string{}} }

// add records v under what: a string or bytes as they are, anything else as its JSON.
func (s *surfaces) add(what string, v any) {
	var text string
	switch x := v.(type) {
	case string:
		text = x
	case []byte:
		text = string(x)
	default:
		b, err := json.Marshal(v)
		if err != nil {
			s.t.Fatalf("marshalling %s: %v", what, err)
		}
		text = string(b)
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	s.by[what] = append(s.by[what], text)
}

// noMarker fails for each surface that carries the marker, and for a kind of surface the
// test expected to see but never collected: a surface with nothing in it proves nothing.
func (s *surfaces) noMarker(want ...string) {
	s.t.Helper()
	s.mu.Lock()
	defer s.mu.Unlock()
	for _, w := range want {
		if len(s.by[w]) == 0 {
			s.t.Errorf("nothing was collected as %s, so its absence of the marker proves nothing", w)
		}
	}
	for what, texts := range s.by {
		for _, text := range texts {
			if strings.Contains(text, marker) {
				s.t.Errorf("%s carries the configuration marker %s:\n%s", what, marker, text)
			}
		}
	}
}

// carriesMarker fails unless every file of files carries the marker: the bytes are meant to be
// there.
func carriesMarker(t *testing.T, what string, files map[string][]byte) {
	t.Helper()
	if len(files) == 0 {
		t.Fatalf("%s holds no artifact file", what)
	}
	for name, b := range files {
		if !bytes.Contains(b, []byte(marker)) {
			t.Errorf("%s %s does not carry the marker", what, name)
		}
	}
}

// artifactFiles returns the files under dir/configs whose name is <node>.device-config.
func artifactFiles(t *testing.T, dir string) map[string][]byte {
	t.Helper()
	out := map[string][]byte{}
	err := filepath.WalkDir(filepath.Join(dir, "configs"), func(p string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() || !strings.HasSuffix(p, ".device-config") {
			return err
		}
		b, err := os.ReadFile(p)
		out[p] = b
		return err
	})
	if err != nil {
		t.Fatal(err)
	}
	return out
}

// readyProber answers every readiness probe at once.
type readyProber struct{}

func (readyProber) Probe(context.Context, string, wire.Probe, func(string) (string, bool)) error {
	return nil
}

// markerNode is an SR Linux JSON-RPC endpoint that commits whatever it is sent, keeping
// the commands: the one place the configuration's bytes are meant to arrive.
type markerNode struct {
	mu       sync.Mutex
	commands []string
}

func (n *markerNode) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Params struct {
			Commands []string `json:"commands"`
		} `json:"params"`
	}
	body, _ := io.ReadAll(r.Body)
	if err := json.Unmarshal(body, &req); err != nil {
		http.Error(w, "not JSON-RPC", http.StatusBadRequest)
		return
	}
	n.mu.Lock()
	n.commands = append(n.commands, req.Params.Commands...)
	n.mu.Unlock()
	_, _ = io.WriteString(w, `{"jsonrpc":"2.0","id":1,"result":[{"text":"All changes have been committed. Leaving candidate mode.\n"}]}`)
}

// stepOf names an activity's step as the create's progress lines name it (contracts/cli.md).
var stepOf = map[string]string{
	wire.ActReadIntent: "read", wire.ActCompile: "compile", wire.ActCheckHost: "host check",
	wire.ActStageBundle: "stage", wire.ActDeployLab: "deploy", wire.ActAwaitReadiness: "readiness",
	wire.ActPushConfig: "push", wire.ActRecordTwin: "record",
}

// The artifact's bytes exist in the CTM, the bundle store, the staged bundle and on the
// node, and nowhere else (Constitution VIII).
//
// A create is driven end to end without infrastructure: the Provision workflow on the
// Temporal test suite, with the worker's own activities wherever they need no host —
// Compile (stage.Compile and the bundle store), CheckHost (over a recorded containerlab),
// StageBundle, AwaitReadiness (a prober that answers), PushConfig (to a JSON-RPC node over
// TLS) and RecordTwin. The read stands in for Infrahub by writing the fixture CTM where a
// read writes one, and the deploy answers as containerlab does. Then the dry run, the
// create's own output in text and JSON, and twin show are run by the commands themselves.
//
// The events are those the create's Follow would print from this run's history, made
// from the activities the test suite saw start and complete: the test suite keeps no
// history, and Follow's mapping of history to events is client_test's.
func TestConfigurationBytesGoToTheNodeAndNowhereElse(t *testing.T) {
	paths := useStateRoot(t)
	dryRunEnv(t)
	t.Setenv("FYLGJA_SRLINUX_PASSWORD", sentinel)
	seen := newSurfaces(t)
	served := markServed()

	var logs bytes.Buffer
	var logMu sync.Mutex
	logger := slog.New(slog.NewTextHandler(lockedWriter{&logMu, &logs}, &slog.HandlerOptions{Level: slog.LevelDebug}))

	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}

	// The CTM carries the marker, and the pure compiler puts it in the bundle's files.
	fixture := repoPath("testdata", "ctm", "three-node.json")
	raw, err := os.ReadFile(fixture)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(raw, []byte(marker)) {
		t.Fatalf("%s does not carry %s; the fixture carries it in each artifact's role line", fixture, marker)
	}
	snapshot, err := ctm.Load(fixture)
	if err != nil {
		t.Fatal(err)
	}
	files, compiledID, list := stage.Compile(snapshot, reg)
	if list.Rejected() {
		t.Fatalf("the fixture does not compile: %v", list)
	}
	compiled := map[string][]byte{}
	for name, b := range files {
		if strings.HasSuffix(name, ".device-config") {
			compiled[name] = b
		}
	}
	carriesMarker(t, "the compiled bundle's", compiled)
	seen.add("compile findings", list)

	// The dry run, before the run, on a clear host.
	useClab(t, "inspect-empty.json")
	dryDir := copyGoldenBundle(t, "dry")
	useService(t, nil)
	for _, asJSON := range []bool{false, true} {
		var runErr error
		stderr := captureStderr(t, func() {
			seen.add("dry-run report", captureStdout(t, func() {
				runErr = runTwinProvision(context.Background(), &options{asJSON: asJSON}, &provisionFlags{dryRun: true}, dryDir)
			}))
		})
		seen.add("dry-run report", stderr)
		code, doc := exitOf(t, runErr)
		if code != findings.ExitOK || doc.DryRun == nil {
			t.Fatalf("dry run exit %d, document %+v; want 0 with a dry_run block", code, doc)
		}
		seen.add("dry-run report", doc)
		seen.add("dry-run report", renderText(t, doc))
	}

	// The node.
	node := &markerNode{}
	srv := httptest.NewTLSServer(node)
	t.Cleanup(srv.Close)
	nodeHost, nodePort, err := net.SplitHostPort(strings.TrimPrefix(srv.URL, "https://"))
	if err != nil {
		t.Fatal(err)
	}
	port, _ := strconv.Atoi(nodePort)

	inspect, err := os.ReadFile(repoPath("internal", "lab", "testdata", "inspect-empty.json"))
	if err != nil {
		t.Fatal(err)
	}
	store := bundle.NewDirStore(paths.Bundles)
	acts := &lab.Activities{
		Clab:     &lab.Clab{Runner: &fakeClab{stdout: inspect}, Log: logger},
		Store:    store,
		Paths:    paths,
		Registry: reg,
		Prober:   readyProber{},
		Getenv: func(k string) (string, bool) {
			v, ok := map[string]string{"FYLGJA_SRLINUX_USERNAME": "admin", "FYLGJA_SRLINUX_PASSWORD": sentinel}[k]
			return v, ok
		},
		Version: "0.1.0-test",
		Log:     logger,
	}
	control := &provision.ControlActivities{Store: store, Paths: paths}

	var suite testsuite.WorkflowTestSuite
	suite.SetLogger(tlog.NewStructuredLogger(logger))
	env := suite.NewTestWorkflowEnvironment()
	env.RegisterWorkflow(provision.Provision)
	for name, fn := range control.Names() {
		env.RegisterActivityWithOptions(fn, activity.RegisterOptions{Name: name})
	}
	hostActs := acts.Names()
	hostActs[wire.ActReadIntent] = func(context.Context, provision.ReadIntentInput) (provision.ReadIntentResult, error) {
		// Where a read leaves its CTM for the compile, which removes it.
		path := filepath.Join(paths.Bundles, ".reads", "marker.ctm.json")
		if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
			return provision.ReadIntentResult{}, err
		}
		return provision.ReadIntentResult{CTMPath: path, ObservedAt: snapshot.Envelope.ObservedAt, Findings: findings.List{}},
			os.WriteFile(path, raw, 0o644)
	}
	hostActs[wire.ActDeployLab] = func(_ context.Context, in wire.DeployInput) (wire.DeployResult, error) {
		var res wire.DeployResult
		for _, n := range in.Nodes {
			res.Nodes = append(res.Nodes, wire.LabNode{Name: n.Name, Container: "clab-fylgja-" + n.Name, Kind: "nokia_srlinux",
				Image: n.Image, State: "running", MgmtIPv4: nodeHost})
		}
		return res, nil
	}
	push := acts.PushConfig
	hostActs[wire.ActPushConfig] = func(ctx context.Context, in wire.PushInput) (wire.PushResult, error) {
		// Only the port differs from the package's: the node is this test's.
		in.Push.Port = port
		return push(ctx, in)
	}
	for name, fn := range hostActs {
		if _, ok := stepOf[name]; ok || name == wire.ActPlanTeardown || name == wire.ActDestroyLab || name == wire.ActUnstageTwin {
			env.RegisterActivityWithOptions(fn, activity.RegisterOptions{Name: name})
		}
	}

	var events []provision.Event
	var evMu sync.Mutex
	started := map[string]time.Time{}
	stepFor := func(info *activity.Info, node string) string {
		step := stepOf[info.ActivityType.Name]
		if node != "" {
			step += " " + node
		}
		return step
	}
	nodeOf := map[string]string{} // activity id → node
	env.SetOnActivityStartedListener(func(info *activity.Info, _ context.Context, args converter.EncodedValues) {
		var in json.RawMessage
		if args.HasValues() {
			if err := args.Get(&in); err != nil {
				t.Errorf("decoding %s's input: %v", info.ActivityType.Name, err)
			}
		}
		seen.add("activity input", string(in))
		var who struct {
			Node string `json:"node"`
		}
		_ = json.Unmarshal(in, &who)
		evMu.Lock()
		defer evMu.Unlock()
		nodeOf[info.ActivityID] = who.Node
		started[info.ActivityID] = time.Now()
		events = append(events, provision.Event{Step: stepFor(info, who.Node), WorkflowID: provision.WorkflowProvision})
	})
	env.SetOnActivityCompletedListener(func(info *activity.Info, result converter.EncodedValue, err error) {
		var res json.RawMessage
		if result != nil && result.HasValue() {
			if gerr := result.Get(&res); gerr != nil {
				t.Errorf("decoding %s's result: %v", info.ActivityType.Name, gerr)
			}
		}
		seen.add("activity result", string(res))
		evMu.Lock()
		defer evMu.Unlock()
		e := provision.Event{Step: stepFor(info, nodeOf[info.ActivityID]), End: true, Outcome: provision.EventDone,
			Duration: time.Since(started[info.ActivityID]), WorkflowID: provision.WorkflowProvision}
		if err != nil {
			e.Outcome, e.Message = provision.EventFailed, err.Error()
			seen.add("activity error", err.Error())
		}
		if info.ActivityType.Name == wire.ActCompile {
			var r provision.CompileResult
			if json.Unmarshal(res, &r) == nil && r.BundleID != "" {
				e.Detail = "bundle_id " + r.BundleID
			}
		}
		events = append(events, e)
	})

	env.ExecuteWorkflow(provision.Provision, provision.ProvisionInput{Source: wire.SourceIntent, Branch: snapshot.Envelope.Branch})
	if !env.IsWorkflowCompleted() || env.GetWorkflowError() != nil {
		t.Fatalf("the run did not complete: %v", env.GetWorkflowError())
	}
	var res provision.ProvisionResult
	if err := env.GetWorkflowResult(&res); err != nil {
		t.Fatal(err)
	}
	if res.Outcome != provision.OutcomeReady || res.BundleID != compiledID || res.Twin == nil || len(res.Twin.Nodes) != 3 {
		t.Fatalf("the run ended %s with bundle %s and twin %+v; want ready, %s, three nodes: %v",
			res.Outcome, res.BundleID, res.Twin, compiledID, res.Findings)
	}
	seen.add("workflow result", res)

	// The bytes are where they belong: the store, the staged bundle, and the node, which
	// was sent every artifact line.
	carriesMarker(t, "the stored bundle's", artifactFiles(t, filepath.Join(paths.Bundles, res.BundleID)))
	carriesMarker(t, "the staged bundle's", artifactFiles(t, filepath.Join(paths.Twin, "bundle")))
	pushedMarker := 0
	for _, c := range node.commands {
		if strings.Contains(c, marker) {
			pushedMarker++
		}
	}
	if pushedMarker != 3 {
		t.Errorf("the node was sent the marker line %d times, want once per node (3)", pushedMarker)
	}

	record, err := os.ReadFile(filepath.Join(paths.Twin, "twin.json"))
	if err != nil {
		t.Fatal(err)
	}
	seen.add("twin.json", record)

	// The create, as the operator sees it: progress and the twin, in text and in JSON.
	for _, asJSON := range []bool{false, true} {
		useService(t, &fakeService{runID: "run-1", result: res, events: events})
		useInterrupts(t)
		var runErr error
		stderr := captureStderr(t, func() {
			seen.add("create output", captureStdout(t, func() {
				runErr = runCreate(context.Background(), &options{asJSON: asJSON}, &createFlags{branch: snapshot.Envelope.Branch, noFollow: true})
			}))
		})
		seen.add("create output", stderr)
		code, doc := exitOf(t, runErr)
		if code != findings.ExitOK || doc.Twin == nil {
			t.Fatalf("create exit %d, document %+v; want 0 with the twin", code, doc)
		}
		seen.add("create document", doc)
		seen.add("create output", renderText(t, doc))
	}

	// twin show, over the record the run wrote.
	out := showWith(t, paths, "inspect-three.json", &fakeService{})
	seen.add("twin show output", out.stdout)
	seen.add("twin show output", out.stderr)
	seen.add("twin show document", out.doc)
	if !strings.Contains(out.stdout, "device-config") {
		t.Errorf("twin show names no artifact, so it did not show this run's record:\n%s", out.stdout)
	}

	// twin verify, over the same record and its staged bundle: what it reads and
	// reports is host names, admin states and neighbour names, never a line of
	// configuration. Every node of this run answers at one address, so the fake node answers
	// by path alone, and the twin does not conform; the report is still the whole surface.
	saved := verifyReader
	t.Cleanup(func() { verifyReader = saved })
	verifyReader = pathNodes{}
	for _, asJSON := range []bool{false, true} {
		var verifyErr error
		stderr := captureStderr(t, func() {
			seen.add("twin verify output", captureStdout(t, func() {
				verifyErr = runTwinVerify(context.Background(), &options{asJSON: asJSON}, &verifyFlags{})
			}))
		})
		seen.add("twin verify output", stderr)
		_, doc := exitOf(t, verifyErr)
		if doc.Verify == nil || len(doc.Verify.Nodes) != 3 {
			t.Fatalf("twin verify read no node of this run's twin: %+v", doc)
		}
		seen.add("twin verify document", doc)
		seen.add("twin verify output", renderText(t, doc))
	}

	logMu.Lock()
	seen.add("log", logs.String())
	logMu.Unlock()
	// What the API's server wrote to the client for each command above, every frame of each
	// answer, and what it logged.
	wireSince, logSince := served.since(t)
	seen.add("API answers", wireSince)
	seen.add("API server log", logSince)
	noSecretServed(t, served, sentinel)
	seen.noMarker("API answers", "API server log", "compile findings", "dry-run report", "activity input", "activity result", "workflow result",
		"twin.json", "create output", "create document", "twin show output", "twin show document",
		"twin verify output", "twin verify document", "log")

	// And the password reached the node alone.
	for what, texts := range seen.by {
		for _, text := range texts {
			if strings.Contains(text, sentinel) {
				t.Errorf("%s carries the push password:\n%s", what, text)
			}
		}
	}
}

// pathNodes answers a read by its path alone, as an SR Linux node would: a host name, a
// port enabled, and no neighbour.
type pathNodes struct{}

func (pathNodes) Get(_ context.Context, _ string, _ wire.Probe, path string, _ func(string) (string, bool)) (verify.Answer, error) {
	switch {
	case strings.HasSuffix(path, "/host-name"):
		return verify.Answer{Updates: []verify.Update{{Path: "srl_nokia-system:system/srl_nokia-system-name:name/host-name", Value: "n1"}}}, nil
	case strings.HasSuffix(path, "/admin-state"):
		return verify.Answer{Updates: []verify.Update{{Path: strings.TrimPrefix(path, "/"), Value: "enable"}}}, nil
	}
	return verify.Answer{}, nil
}

// lockedWriter serialises the log's writes: activities run concurrently.
type lockedWriter struct {
	mu *sync.Mutex
	w  io.Writer
}

func (l lockedWriter) Write(p []byte) (int, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.w.Write(p)
}
