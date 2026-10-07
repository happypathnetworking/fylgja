package cli

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/santhosh-tekuri/jsonschema/v6"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
)

// The answers of the twelve operations as the wire carries them. Each is asked of the
// harness's server three times, over the harness's fakes, as a client other than the CLI
// asks: with no rendering, with "json" and with "text". These tests live beside the
// harness, whose fakes (Infrahub, the workflow service, the nodes) are this package's test
// code, which internal/server's tests cannot import.

// rawAnswer is one answer as the wire carried it: its status, and each line with its frame.
type rawAnswer struct {
	status int
	lines  [][]byte
	frames []api.Frame
}

// ask posts one request to the harness's server, the way the CLI's client does but with the
// rendering given ("" is none), and reads the whole answer. A run's request names a fresh
// stream. Every line is checked against api.schema.json's frame.
func ask(t *testing.T, op, render string, args map[string]any, files []api.File) rawAnswer {
	t.Helper()
	req := api.Request{Render: render, Files: files}
	if len(args) > 0 {
		req.Args = map[string]json.RawMessage{}
		for k, v := range args {
			b, err := json.Marshal(v)
			if err != nil {
				t.Fatal(err)
			}
			req.Args[k] = b
		}
	}
	body, err := api.EncodeRequest(req)
	if err != nil {
		t.Fatal(err)
	}
	hreq, err := http.NewRequest(http.MethodPost, harness.http.URL+api.Path(op), bytes.NewReader(body))
	if err != nil {
		t.Fatal(err)
	}
	hreq.Header.Set("Authorization", "Bearer "+harness.token)
	if takesInterrupts(op) {
		stream, err := newStream()
		if err != nil {
			t.Fatal(err)
		}
		hreq.Header.Set(api.HeaderStream, stream)
	}
	resp, err := http.DefaultClient.Do(hreq)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = resp.Body.Close() }()
	a := rawAnswer{status: resp.StatusCode}
	frame := apiContract(t, "frame")
	r := bufio.NewReader(resp.Body)
	for {
		line, err := r.ReadBytes('\n')
		if len(line) > 0 {
			line = bytes.TrimSuffix(line, []byte("\n"))
			satisfiesContract(t, frame, line, op+" frame")
			var f api.Frame
			if err := json.Unmarshal(line, &f); err != nil {
				t.Fatalf("%s: a line of the answer is not a frame: %v\n%s", op, err, line)
			}
			a.lines = append(a.lines, line)
			a.frames = append(a.frames, f)
		}
		if errors.Is(err, io.EOF) {
			return a
		}
		if err != nil {
			t.Fatalf("%s: reading the answer: %v", op, err)
		}
	}
}

// kinds are the answer's frame kinds in order, leaving out those named.
func (a rawAnswer) kinds(without ...string) []string {
	var out []string
	for _, f := range a.frames {
		k := f.Kind()
		skip := false
		for _, w := range without {
			skip = skip || k == w
		}
		if !skip {
			out = append(out, k)
		}
	}
	return out
}

// text is every frame of kind's text, joined: the out frames' or the err frames'.
func (a rawAnswer) text(kind string) string {
	var b strings.Builder
	for _, f := range a.frames {
		switch {
		case kind == api.KindOut && f.Kind() == api.KindOut:
			b.WriteString(f.Out)
		case kind == api.KindErr && f.Kind() == api.KindErr:
			b.WriteString(f.Err)
		}
	}
	return b.String()
}

// events are the answer's event frames, in order.
func (a rawAnswer) events() []api.Event {
	var out []api.Event
	for _, f := range a.frames {
		if f.Event != nil {
			out = append(out, *f.Event)
		}
	}
	return out
}

// document is the answer's last frame, which must be its document, decoded.
func (a rawAnswer) document(t *testing.T, label string) (api.Frame, *findings.Document) {
	t.Helper()
	if len(a.frames) == 0 || a.frames[len(a.frames)-1].Kind() != api.KindDocument {
		t.Fatalf("%s: the answer does not end with its document: %v", label, a.kinds())
	}
	f := a.frames[len(a.frames)-1]
	var doc findings.Document
	if err := json.Unmarshal(f.Document, &doc); err != nil {
		t.Fatalf("%s: the document does not decode: %v", label, err)
	}
	return f, &doc
}

var apiContracts = struct {
	sync.Mutex
	byDef map[string]*jsonschema.Schema
}{byDef: map[string]*jsonschema.Schema{}}

// apiContract compiles one definition of this feature's api.schema.json once, with the
// findings schema and the blocks it refers to added under their $ids.
func apiContract(t *testing.T, def string) *jsonschema.Schema {
	t.Helper()
	apiContracts.Lock()
	defer apiContracts.Unlock()
	if s, ok := apiContracts.byDef[def]; ok {
		return s
	}
	c := jsonschema.NewCompiler()
	for _, name := range []string{"api.schema.json", "findings.schema.json", "show.schema.json",
		"waypoints.schema.json", "step.schema.json", "verify.schema.json"} {
		f, err := os.Open(repoPath("contracts", name))
		if err != nil {
			t.Fatal(err)
		}
		doc, err := jsonschema.UnmarshalJSON(f)
		_ = f.Close()
		if err != nil {
			t.Fatalf("parsing %s: %v", name, err)
		}
		if err := c.AddResource(doc.(map[string]any)["$id"].(string), doc); err != nil {
			t.Fatal(err)
		}
	}
	s, err := c.Compile("https://fylgja.dev/schemas/api.schema.json#/$defs/" + def)
	if err != nil {
		t.Fatal(err)
	}
	apiContracts.byDef[def] = s
	return s
}

// satisfiesContract validates raw JSON against a compiled schema.
func satisfiesContract(t *testing.T, s *jsonschema.Schema, raw []byte, label string) {
	t.Helper()
	v, err := jsonschema.UnmarshalJSON(bytes.NewReader(raw))
	if err != nil {
		t.Fatalf("%s: %v", label, err)
	}
	if err := s.Validate(v); err != nil {
		t.Errorf("%s does not satisfy the contract: %v\n%s", label, err, raw)
	}
}

// answerCase is one operation asked of the server, set up over the harness's fakes as the
// command test it is named after sets it up.
type answerCase struct {
	name string
	op   string
	// setup builds the host, the fakes and the request, and says what the answer must be.
	setup func(t *testing.T) answerWant
}

// answerWant is a case's request and what its answer must carry.
type answerWant struct {
	args  map[string]any
	files []api.File
	// kinds are the frames of the answer with no rendering, in order.
	kinds  []string
	status findings.Status
	// events are the steps of a run's events in order, as the fake service replays them.
	events []string
	// stdout is what the command's own test asserts the command prints: the out frames under
	// "text", joined. cli, when set, is that output taken from the CLI's command run over the
	// same fakes, where its test asserts the lines by their parts.
	stdout string
	cli    func(t *testing.T) string
	// stderr is what the command wrote to stderr without --json, beside its findings: the
	// err frames under "text". Under "json" the cases write nothing there, as M12 did.
	stderr string
}

// runKinds are a run's frames with no rendering: the start, the run, each event, the
// document.
func runKinds(events int) []string {
	k := []string{api.KindStart, api.KindRun}
	for range events {
		k = append(k, api.KindEvent)
	}
	return append(k, api.KindDocument)
}

// stepsOf are the events' steps, or their notices, in order.
func stepsOf(events []provision.Event) []string {
	var out []string
	for _, e := range events {
		out = append(out, e.Step+e.Notice)
	}
	return out
}

// cliStdout runs a client's command and returns what it printed on stdout.
func cliStdout(t *testing.T, run func() error) string {
	t.Helper()
	var err error
	out := captureStdout(t, func() { err = run() })
	var res *result
	if err != nil && !errors.As(err, &res) {
		t.Fatalf("the command returned %v, want a document", err)
	}
	return out
}

func createReadyEvents() []provision.Event {
	return []provision.Event{
		{Step: "read"},
		{Step: "read", End: true, Outcome: provision.EventDone, Duration: 2100 * time.Millisecond},
		{Step: "compile"},
		{Step: "compile", End: true, Outcome: provision.EventDone, Duration: 100 * time.Millisecond, Detail: "bundle_id " + fixtureBundleID},
		{Step: "readiness n1", End: true, Outcome: provision.EventDone, Duration: 9800 * time.Millisecond},
		{Step: "push n1"},
		{Step: "push n1", End: true, Outcome: provision.EventDone, Duration: 700 * time.Millisecond},
		{Step: "record"},
		{Step: "record", End: true, Outcome: provision.EventDone, Duration: 20 * time.Millisecond},
	}
}

// steppedResult is a step run that stepped, as TestStepRuns' first case replays it.
func steppedResult() provision.StepResult {
	reconcile, e1, s1 := 3.9, 1.6, 2.4
	return provision.StepResult{Outcome: provision.StepStepped,
		StartedAt: "2026-10-02T09:14:30Z", EndedAt: "2026-10-02T09:15:41Z", Findings: findings.List{},
		PushPlan: []wire.StepPush{
			{Node: "e1", Reasons: []string{"artifact", "restarted"}, Outcome: wire.PushLanded, TookS: &e1},
			{Node: "s1", Reasons: []string{"artifact", "bootstrap"}, Outcome: wire.PushLanded, TookS: &s1},
		},
		Timings: wire.StepTimings{ReconcileS: &reconcile, Readiness: map[string]float64{"e1": 54.8},
			Push: map[string]float64{"e1": 1.6, "s1": 2.4}, WholeS: 71.2},
		Record: &wire.TwinRecord{State: wire.StateReady}}
}

func answerCases() []answerCase {
	return []answerCase{
		{"twin create, a run (TestCreateReadyPrintsTheTwin)", findings.OpTwinCreate, func(t *testing.T) answerWant {
			useStateRoot(t)
			events := createReadyEvents()
			useService(t, &fakeService{runID: "run-1", result: readyResult(), events: events})
			return answerWant{args: map[string]any{"branch": "fylgja-fixture"},
				kinds: runKinds(len(events)), status: findings.StatusOK, events: stepsOf(events),
				stdout: lines("run fylgja-provision run-1",
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
					"twin directory /abs/local/twin")}
		}},
		{"twin create --dry-run", findings.OpTwinCreate, func(t *testing.T) answerWant {
			useStateRoot(t)
			useService(t, nil)
			dryRunEnv(t)
			useClab(t, "inspect-empty.json")
			newFakeInfrahub(t).start()
			return answerWant{args: map[string]any{"branch": "fylgja-fixture", "dry_run": true},
				kinds: []string{api.KindDocument}, status: findings.StatusOK,
				cli: func(t *testing.T) string {
					return cliStdout(t, func() error {
						return runCreate(context.Background(), &options{}, &createFlags{branch: "fylgja-fixture", dryRun: true})
					})
				}}
		}},
		{"twin create, refused (TestCreateRefusesBeforeDialling)", findings.OpTwinCreate, func(t *testing.T) answerWant {
			useStateRoot(t)
			useService(t, nil)
			return answerWant{kinds: []string{api.KindDocument}, status: findings.StatusError}
		}},
		{"twin provision, a run (TestProvisionFilesOnceAndSendsTheStoredPath)", findings.OpTwinProvision, func(t *testing.T) answerWant {
			useStateRoot(t)
			events := []provision.Event{
				{Step: "host check"},
				{Step: "host check", End: true, Outcome: provision.EventDone, Duration: 300 * time.Millisecond},
			}
			useService(t, &fakeService{runID: "run-1", result: readyResult(), events: events})
			useInterrupts(t)
			dir := copyGoldenBundle(t, "b")
			files, err := readBundle(dir)
			if err != nil {
				t.Fatal(err)
			}
			return answerWant{args: map[string]any{"bundle": dir}, files: files,
				kinds: runKinds(len(events)), status: findings.StatusOK, events: stepsOf(events),
				cli: func(t *testing.T) string {
					return cliStdout(t, func() error {
						return runTwinProvision(context.Background(), &options{}, &provisionFlags{}, dir)
					})
				}}
		}},
		{"twin provision --dry-run (TestProvisionDryRunTextReport)", findings.OpTwinProvision, func(t *testing.T) answerWant {
			paths := useStateRoot(t)
			useService(t, nil)
			dryRunEnv(t)
			useClab(t, "inspect-empty.json")
			dir := copyGoldenBundle(t, "b")
			files, err := readBundle(dir)
			if err != nil {
				t.Fatal(err)
			}
			return answerWant{args: map[string]any{"bundle": dir, "dry_run": true}, files: files,
				kinds: []string{api.KindDocument}, status: findings.StatusOK,
				stdout: lines("dry run: no lab, container, twin directory or run is created",
					"bundle_id "+fixtureBundleID+"  stored: "+filepath.Join(paths.Bundles, fixtureBundleID),
					"nodes:",
					"  n1  ghcr.io/nokia/srlinux:24.7.1  nokia_srlinux  2048 MiB  push device-config "+fixtureArtifacts["n1"]+" (861 bytes)",
					"  n2  ghcr.io/nokia/srlinux:24.7.1  nokia_srlinux  2048 MiB  push device-config "+fixtureArtifacts["n2"]+" (861 bytes)",
					"  n3  ghcr.io/nokia/srlinux:24.7.1  nokia_srlinux  2048 MiB  push device-config "+fixtureArtifacts["n3"]+" (861 bytes)",
					"mapping: 0 lossy mappings, 0 shared ports",
					"memory: sum 6144 MiB; host budget unset",
					"host: lab fylgja absent; twin directory absent",
					"follow: would not follow (a bundle never follows)",
					"verdict: clear")}
		}},
		{"twin step, a run (TestStepRuns)", findings.OpTwinStep, func(t *testing.T) answerWant {
			stepHost(t, "plan-link-added.json", nil)
			events := stepEvents()
			useService(t, &fakeService{runID: stepRunID, events: events, stepResult: steppedResult()})
			useInterrupts(t)
			return answerWant{args: map[string]any{"allow_restart": true},
				kinds: runKinds(len(events)), status: findings.StatusOK, events: stepsOf(events),
				cli: func(t *testing.T) string { return runStepCmd(t, "--allow-restart").stdout }}
		}},
		{"twin step --dry-run (TestStepDryRun)", findings.OpTwinStep, func(t *testing.T) answerWant {
			h := stepHost(t, "plan-link-added.json", nil)
			toID := runStepCmd(t, "--dry-run", "--allow-restart").doc.BundleID
			return answerWant{args: map[string]any{"dry_run": true, "allow_restart": true},
				kinds: []string{api.KindDocument}, status: findings.StatusOK,
				stdout: lines(append(stepDryRunLines(h.fromID, toID),
					"memory: sum 5120 MiB; host budget unset",
					"host: lab fylgja present; twin directory present",
					"verdict: "+findings.VerdictClear)...)}
		}},
		{"twin destroy (TestDestroyPrintsWhatItRemoved)", findings.OpTwinDestroy, func(t *testing.T) answerWant {
			events := []provision.Event{{Notice: "run fylgja-destroy run-d"}}
			useService(t, &fakeService{destroyEvents: events, destroyRun: destroyedRun(provision.CleanupResult{
				Teardown: provision.CleanupDone, Unstage: provision.CleanupDone,
				Removed: []string{"lab fylgja (3 containers)", "twin directory /abs/local/twin"}}, nil)})
			return answerWant{kinds: []string{api.KindStart, api.KindEvent, api.KindDocument}, status: findings.StatusOK, events: stepsOf(events),
				stdout: lines("run fylgja-destroy run-d", "removed lab fylgja (3 containers)", "removed twin directory /abs/local/twin")}
		}},
		{"twin show (TestShowNoTwin)", findings.OpTwinShow, func(t *testing.T) answerWant {
			useStateRoot(t)
			useService(t, &fakeService{readOnly: t})
			useClab(t, "inspect-empty.json")
			t.Setenv("FYLGJA_TEMPORAL_ADDRESS", "")
			return answerWant{kinds: []string{api.KindDocument}, status: findings.StatusOK,
				stdout: lines("twin: none: no lab fylgja, no twin directory", "kind: none", "in flight: none")}
		}},
		{"twin show, following stopped (TestShowFollowingStopped)", findings.OpTwinShow, func(t *testing.T) answerWant {
			useStateRoot(t)
			check := stoppedCheck()
			useService(t, &fakeService{readOnly: t, lastCheck: check})
			useClab(t, "inspect-empty.json")
			t.Setenv("FYLGJA_TEMPORAL_ADDRESS", "")
			const stopped = "following of branch fylgja-fixture stopped: the check " + showCheckID +
				" at 2026-09-16T19:12:00Z ended rebuild_failed at step provision; cleanup teardown done, unstage done; fylgja twin create starts again"
			var text bytes.Buffer
			if err := (&findings.Document{Findings: check.Result.Findings}).WriteText(&text); err != nil {
				t.Fatal(err)
			}
			return answerWant{kinds: []string{api.KindDocument}, status: findings.StatusOK,
				stdout: lines("twin: none: no lab fylgja, no twin directory", "kind: none; "+stopped, "in flight: none"),
				stderr: "check " + showCheckID + " r-c ended rebuild_failed:\n" + text.String()}
		}},
		{"twin verify (TestVerifyConformingThreeNode)", findings.OpTwinVerify, func(t *testing.T) answerWant {
			h := verifyHost(t, "three-node", nil, nil)
			useVerifyClock(t)
			saved := verifyReader
			t.Cleanup(func() { verifyReader = saved })
			verifyReader = h.healthy(t)
			return answerWant{kinds: []string{api.KindDocument}, status: findings.StatusOK,
				stdout: lines(threeNodeLines(h.staged)...)}
		}},
		{"twin compile (TestCommandAndGoldenShareTheCompilerPath)", findings.OpCompile, func(t *testing.T) answerWant {
			path := repoPath("testdata", "ctm", "three-node.json")
			file, err := readCTM(path)
			if err != nil {
				t.Fatal(err)
			}
			// The server writes nothing: the client's command, run after the three requests,
			// writes the bundle there.
			out := filepath.Join(t.TempDir(), "b")
			return answerWant{args: map[string]any{"ctm": path, "out": out}, files: []api.File{file},
				kinds: []string{api.KindFiles, api.KindDocument}, status: findings.StatusOK,
				cli: func(t *testing.T) string {
					return cliStdout(t, func() error {
						return runCompile(&options{}, &compileFlags{ctmPath: path, out: out})
					})
				}}
		}},
		{"waypoint list (TestWaypointList)", findings.OpWaypointList, func(t *testing.T) answerWant {
			useStateRoot(t)
			useService(t, nil)
			f := seriesInfrahub(t)
			f.waypoint("wp-mid-12", "mid", 12, "fylgja-fixture", demoWrittenAt, fixtureAt, "twelfth")
			f.start()
			return answerWant{kinds: []string{api.KindDocument}, status: findings.StatusOK,
				stdout: lines("series back (2 waypoints)",
					`  back/1  branch fylgja-fixture  at 2026-09-20T00:00:00Z (given)  ""`,
					`  back/2  branch fylgja-fixture  at 2026-09-08T12:00:00Z (given)  ""`,
					"series demo (3 waypoints)",
					`  demo/1  branch fylgja-fixture  at 2026-09-01T09:00:00.000000+00:00 (written)  "before the change"`,
					`  demo/2  branch fylgja-fixture  at 2026-09-08T12:00:00Z (given)  "after the first cut-over"`,
					`  demo/3  branch change-1        at 2026-09-21T15:20:44.000000+00:00 (written)  "after the second"`,
					"series mid (5 waypoints)",
					`  mid/1   branch fylgja-fixture  at 2026-09-02T00:00:00.000000+00:00 (written)  ""`,
					`  mid/2   branch fylgja-fixture  at 2026-09-02T12:00:00.123456789Z (given)  ""`,
					`  mid/3   branch gone            at 2026-09-03T00:00:00.000000+00:00 (written)  ""`,
					`  mid/4   branch fylgja-fixture  at 2026-09-08T12:00:00Z (given)  ""`,
					`  mid/12  branch fylgja-fixture  at 2026-09-08T12:00:00Z (given)  "twelfth"`)}
		}},
		{"waypoint plan (TestWaypointPlan)", findings.OpWaypointPlan, func(t *testing.T) answerWant {
			useStateRoot(t)
			useService(t, nil)
			seriesInfrahub(t).start()
			return answerWant{args: map[string]any{"series": "demo"}, kinds: []string{api.KindDocument}, status: findings.StatusOK,
				cli: func(t *testing.T) string {
					_, stdout, _ := runWaypoint(t, "plan", "--series", "demo")
					return stdout
				}}
		}},
		{"intent read", findings.OpIntentRead, func(t *testing.T) answerWant {
			newFakeInfrahub(t).start()
			out := filepath.Join(t.TempDir(), "ctm.json")
			return answerWant{args: map[string]any{"branch": "fylgja-fixture", "out": out},
				kinds: []string{api.KindFiles, api.KindDocument}, status: findings.StatusOK,
				cli: func(t *testing.T) string {
					return cliStdout(t, func() error {
						return runRead(context.Background(), &options{}, &readFlags{branch: "fylgja-fixture", out: out})
					})
				}}
		}},
		{"schema check (TestCheckNamesTheWaypointKind)", findings.OpSchemaCheck, func(t *testing.T) answerWant {
			newFakeInfrahub(t).start()
			return answerWant{args: map[string]any{"branch": "fylgja-fixture"}, kinds: []string{api.KindDocument}, status: findings.StatusOK,
				cli: func(t *testing.T) string {
					return cliStdout(t, func() error {
						return runCheck(context.Background(), &options{}, &checkFlags{branch: "fylgja-fixture"})
					})
				}}
		}},
		{"psp validate (TestShippedPackageValidatesClean)", findings.OpPSPValidate, func(t *testing.T) answerWant {
			paths := []string{repoPath("psp", "nokia_srlinux.yaml")}
			files, err := readPackages(paths)
			if err != nil {
				t.Fatal(err)
			}
			return answerWant{args: map[string]any{"files": paths}, files: files, kinds: []string{api.KindDocument}, status: findings.StatusOK,
				cli: func(t *testing.T) string {
					return cliStdout(t, func() error { return runPSPValidate(&options{}, paths) })
				}}
		}},
		{"psp validate, refused (TestDefectFixturesAreNamedWithTheirLocation)", findings.OpPSPValidate, func(t *testing.T) answerWant {
			paths := []string{defectPath("version-0-5.yaml")}
			files, err := readPackages(paths)
			if err != nil {
				t.Fatal(err)
			}
			return answerWant{args: map[string]any{"files": paths}, files: files, kinds: []string{api.KindDocument}, status: findings.StatusRejected}
		}},
	}
}

// Each operation answers in its own shape: with no
// rendering, its document alone, a run's start, run and events before it and a CTM's or a
// bundle's files frame before it, and nothing for stdout or stderr; under "json" the same
// frames and no out frame, with nothing for stderr where M12's --json wrote nothing there;
// under "text" the same frames with the lines the command's own test asserts on stdout as
// out frames, and the findings as text beside the document. The document is valid against
// the findings contract, a refused command's included, which is a 200 like any other; the
// events are the run's, in order, in every rendering; every frame is api.schema.json's; and
// nothing carries the API's token or the fakes' credentials.
func TestEachOperationAnswersAsAsked(t *testing.T) {
	covered := map[string]bool{}
	for _, c := range answerCases() {
		t.Run(c.name, func(t *testing.T) {
			covered[c.op] = true
			want := c.setup(t)
			answers := map[string]rawAnswer{}
			for _, render := range []string{"", api.RenderJSON, api.RenderText} {
				label := c.op + ` render "` + render + `"`
				a := ask(t, c.op, render, want.args, want.files)
				answers[render] = a
				if a.status != http.StatusOK {
					t.Fatalf("%s: status %d, want 200 with the document", label, a.status)
				}
				f, doc := a.document(t, label)
				satisfiesContract(t, findingsContract(t, currentContract), f.Document, label+"'s document")
				if doc.Operation != c.op || doc.Status != want.status {
					t.Errorf("%s: operation %s, status %s; want %s, %s; findings %+v", label, doc.Operation, doc.Status, c.op, want.status, doc.Findings)
				}
				var steps []string
				for _, e := range a.events() {
					steps = append(steps, e.Step+e.Notice)
				}
				if !reflect.DeepEqual(steps, want.events) {
					t.Errorf("%s: events %q, want %q in order", label, steps, want.events)
				}
				for _, line := range a.lines {
					for _, secret := range []string{harness.token, sentinel, fakeToken} {
						if bytes.Contains(line, []byte(secret)) {
							t.Errorf("%s carries a credential: %s", label, line)
						}
					}
				}
			}

			none, asJSON, asText := answers[""], answers[api.RenderJSON], answers[api.RenderText]
			if got := none.kinds(); !reflect.DeepEqual(got, want.kinds) {
				t.Errorf("with no rendering the answer is %v, want %v", got, want.kinds)
			}
			if got := asJSON.kinds(api.KindErr); !reflect.DeepEqual(got, want.kinds) {
				t.Errorf(`under "json" the answer is %v, want %v and err frames alone beside them`, asJSON.kinds(), want.kinds)
			}
			if got := asText.kinds(api.KindOut, api.KindErr); !reflect.DeepEqual(got, want.kinds) {
				t.Errorf(`under "text" the answer is %v, want %v and out and err frames beside them`, asText.kinds(), want.kinds)
			}
			for render, a := range map[string]rawAnswer{"": none, api.RenderJSON: asJSON} {
				if f, _ := a.document(t, render); f.Text != "" {
					t.Errorf("render %q: the document carries text %q, which only text asks for", render, f.Text)
				}
			}
			if got := asJSON.text(api.KindErr); got != "" {
				t.Errorf(`under "json" the answer carries for stderr %q, where M12's --json wrote nothing`, got)
			}
			if got := asText.text(api.KindErr); got != want.stderr {
				t.Errorf(`under "text" the answer carries for stderr %q, where M12 wrote %q`, got, want.stderr)
			}

			stdout := want.stdout
			if want.cli != nil {
				stdout = want.cli(t)
			}
			if stdout == "" {
				if want.status == findings.StatusOK {
					t.Fatal("the case names no stdout for a command that ran")
				}
			}
			if got := asText.text(api.KindOut); got != stdout {
				t.Errorf(`under "text" the out frames are:
%s
want what the command prints:
%s`, got, stdout)
			}
			f, doc := asText.document(t, "text")
			var text bytes.Buffer
			if err := doc.WriteText(&text); err != nil {
				t.Fatal(err)
			}
			if len(doc.Findings) == 0 && f.Text != "" || f.Text != text.String() && len(doc.Findings) > 0 {
				t.Errorf(`under "text" the document's text is %q, want the findings as text, %q`, f.Text, text.String())
			}

			// One document, whichever rendering asked for it.
			_, a := none.document(t, "none")
			_, b := asJSON.document(t, "json")
			if a.Status != b.Status || a.Status != doc.Status || !reflect.DeepEqual(a.Findings, b.Findings) || !reflect.DeepEqual(a.Findings, doc.Findings) ||
				a.BundleID != b.BundleID || a.BundleID != doc.BundleID {
				t.Errorf("the renderings answer different documents:\nnone %+v\njson %+v\ntext %+v", a, b, doc)
			}
		})
	}
	for _, op := range api.Operations {
		if !covered[op] {
			t.Errorf("no case asks %s", op)
		}
	}
}

// heldDestroy is the harness's fake service with the destroy held until released, as a
// destroy waiting on a run it cancelled is.
type heldDestroy struct {
	*fakeService
	entered, release chan struct{}
}

func (h *heldDestroy) StartDestroy(ctx context.Context, onEvent func(provision.Event)) (provision.DestroyRun, error) {
	close(h.entered)
	select {
	case <-h.release:
	case <-ctx.Done():
	}
	return h.fakeService.StartDestroy(ctx, onEvent)
}

// twin destroy's answer has a start frame and no run frame: the destroy is one request,
// followed to its end, which takes no interrupt. The start,
// fylgja-destroy's, comes after following has stopped and just before the destroy run is
// started, so a cut from there says a run may have been started. Each event
// of a step carries the workflow it belongs to, the cancelled check's, the cancelled
// create's or the destroy's own; a notice carries its line alone; and the document's subject
// names the destroy run. A client that names a stream on it anyway has nothing opened under
// it: an interrupt for that stream, while the destroy runs, is 404.
func TestDestroyAnswersWithAStartAndNoRun(t *testing.T) {
	const check = "fylgja-reconcile-2026-09-16T19:10:00Z"
	stopEvents := []provision.Event{
		{Notice: "cancelling check " + check + "; waiting for its cleanup"},
		{WorkflowID: provision.WorkflowProvision, Step: "cleanup teardown", End: true, Outcome: provision.EventDone,
			Duration: 2 * time.Second, FindingStep: findings.StepTeardown},
		{Notice: "check " + check + " closed: cancelled"},
	}
	events := destroyCancellingACreate()
	svc := &heldDestroy{fakeService: &fakeService{destroyRun: destroyedRun(provision.CleanupResult{
		Teardown: provision.CleanupDone, Unstage: provision.CleanupDone, Removed: []string{"lab fylgja (3 containers)"}}, nil),
		stopResult: provision.FollowStop{Stopped: true, Branch: "fylgja-fixture", CheckCancelled: check},
		stopEvents: stopEvents, destroyEvents: events}, entered: make(chan struct{}), release: make(chan struct{})}
	useService(t, svc)

	// The destroy is asked under a stream of the test's own, and interrupted while held.
	stream, err := newStream()
	if err != nil {
		t.Fatal(err)
	}
	hreq, err := http.NewRequest(http.MethodPost, harness.http.URL+api.Path(findings.OpTwinDestroy), strings.NewReader("{}"))
	if err != nil {
		t.Fatal(err)
	}
	hreq.Header.Set("Authorization", "Bearer "+harness.token)
	hreq.Header.Set(api.HeaderStream, stream)
	before := requestOutcomes("interrupt")
	type answered struct {
		lines []api.Frame
		err   error
	}
	done := make(chan answered, 1)
	go func() {
		resp, err := http.DefaultClient.Do(hreq)
		if err != nil {
			done <- answered{err: err}
			return
		}
		defer func() { _ = resp.Body.Close() }()
		var got answered
		r := bufio.NewReader(resp.Body)
		for {
			line, err := r.ReadBytes('\n')
			if len(line) > 0 {
				satisfiesContract(t, apiContract(t, "frame"), bytes.TrimSuffix(line, []byte("\n")), "destroy frame")
				var f api.Frame
				if err := json.Unmarshal(line, &f); err != nil {
					got.err = err
					break
				}
				got.lines = append(got.lines, f)
			}
			if err != nil {
				break
			}
		}
		done <- got
	}()
	select {
	case <-svc.entered:
	case <-time.After(5 * time.Second):
		t.Fatal("the destroy never started")
	}
	ireq, err := http.NewRequest(http.MethodPost, harness.http.URL+api.InterruptPath(stream), nil)
	if err != nil {
		t.Fatal(err)
	}
	ireq.Header.Set("Authorization", "Bearer "+harness.token)
	iresp, err := http.DefaultClient.Do(ireq)
	if err != nil {
		t.Fatal(err)
	}
	_ = iresp.Body.Close()
	close(svc.release)
	got := <-done
	if got.err != nil {
		t.Fatal(got.err)
	}

	if iresp.StatusCode != http.StatusNotFound {
		t.Errorf("an interrupt for the destroy's stream answered %d, want 404: a destroy takes none", iresp.StatusCode)
	}
	if got := servedAfter(t, "interrupt", len(before)); got != "stream_ended" {
		t.Errorf("the interrupt was logged %s, want stream_ended", got)
	}
	a := rawAnswer{frames: got.lines}
	var want []string
	for range stopEvents {
		want = append(want, api.KindEvent)
	}
	want = append(want, api.KindStart)
	for range events {
		want = append(want, api.KindEvent)
	}
	if kinds := a.kinds(); !slices.Equal(kinds, append(want, api.KindDocument)) {
		t.Errorf("frames %v, want following's events, the start, the destroy's events and its document, and no run", kinds)
	}
	for _, f := range a.frames {
		if f.Start != nil && *f.Start != (api.RunRef{WorkflowID: provision.WorkflowDestroy}) {
			t.Errorf("start %+v, want the destroy's, %s, with no run id", *f.Start, provision.WorkflowDestroy)
		}
	}
	all := append(slices.Clone(stopEvents), events...)
	for i, e := range a.events() {
		if i == len(all) {
			break
		}
		w := all[i]
		switch {
		case w.Notice != "":
			if e.Notice != w.Notice || e.WorkflowID != "" || e.Step != "" {
				t.Errorf("event %d %+v, want the notice %q alone", i, e, w.Notice)
			}
		case e.WorkflowID != w.WorkflowID || e.Step != w.Step:
			t.Errorf("event %d %+v, want step %q of %s", i, e, w.Step, w.WorkflowID)
		}
	}
	_, doc := a.document(t, "twin.destroy")
	if doc.Subject == nil || doc.Subject.RunID != "run-d" || doc.Status != findings.StatusOK {
		t.Errorf("document %+v, want ok naming the destroy run run-d", doc)
	}
	svc.mu.Lock()
	defer svc.mu.Unlock()
	if svc.cancels != 0 {
		t.Errorf("Cancel called %d times, want none: an interrupt reached nothing", svc.cancels)
	}
}
