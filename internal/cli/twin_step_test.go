package cli

import (
	"context"
	"crypto/md5"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"maps"
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/probe"
	"github.com/happypathnetworking/fylgja/internal/provision"
	"github.com/happypathnetworking/fylgja/internal/psp"
	snap "github.com/happypathnetworking/fylgja/internal/snapshot"
	intentstage "github.com/happypathnetworking/fylgja/internal/stage"
	"github.com/happypathnetworking/fylgja/internal/stages"
)

// The proposed change twin step walks in tier 1 (014): pc-1 on branch change-1, whose
// source branch reads four intents by version (the fake's versions), so each stage reads
// its own at. Its stages in order: the branch point (main, the fixture); sealed, the mixed
// fixture at a given at; linked, unwritten, at its mark's writing, which adds the link
// e1:Ethernet3 — s1:ethernet-1/3 and re-renders e1's and s1's artifacts (the fixture tool's
// -add-mixed-link, in the fake); again, the mixed fixture at a later at, so the step from
// sealed is unchanged but for provenance; less, e2 retired; and the head, at the branch's
// latest stamp.
const (
	stepMixedAt   = "2026-10-16T08:30:00Z"
	stepWrittenAt = fakeMarkedAt
	stepLaterAt   = "2026-10-16T11:00:00Z"
	stepLessAt    = "2026-10-16T12:00:00Z"
	stepRunID     = "01a1b2c3-0000-7000-8000-000000000001"
	createRunID   = "01a1b2c3-0000-7000-8000-000000000000"
	// stepStages is the proposed change's stages, as its refusals name them.
	stepStages = "branch-point, sealed, linked, again, less, head"
	// noTargetMessage is step.target.unknown's message for a step given no target, of a twin
	// whose record names no stage (019, research R-08).
	noTargetMessage = "the twin names no stage, so there is no next stage to step to; " +
		"give --stage <branch>/<label> or --snapshot <id|file>"
)

// stepChange is the twin's proposed change as its record names it.
var stepChange = wire.StageChange{ID: "pc-1", Branch: "change-1"}

// stepInfrahub serves the proposed change.
func stepInfrahub(t *testing.T) *fakeInfrahub {
	t.Helper()
	f := newFakeInfrahub(t)
	mixed, err := ctm.Load(repoPath("testdata", "ctm", "mixed.json"))
	if err != nil {
		t.Fatal(err)
	}
	mixed.Envelope.Branch = "change-1"
	f.versions = map[string][]fakeVersion{"change-1": {
		{Since: "2026-10-16T08:10:00.000000+00:00", CTM: mixed},
		{Since: "2026-10-16T09:30:00.000000+00:00", CTM: withMixedLink(t)},
		{Since: "2026-10-16T10:30:00.000000+00:00", CTM: mixed},
		{Since: "2026-10-16T11:30:00.000000+00:00", CTM: withoutE2(t)},
	}}
	f.change("pc-1", "change-1",
		mark("st-linked", "linked", "", "a link between e1 and s1"),
		mark("st-sealed", "sealed", stepMixedAt, "the mixed fixture as sealed"),
		mark("st-again", "again", stepLaterAt, "the fixture again"),
		mark("st-less", "less", stepLessAt, "e2 retired"))
	return f
}

// withMixedLink is the mixed fixture read from branch change-1 with the link
// e1:Ethernet3 — s1:ethernet-1/3 added and e1's and s1's artifacts re-rendered for it, each
// carrying the marker as the template writes a device's description, in the header's
// `platform <manufacturer> <platform>; <description>` line.
func withMixedLink(t *testing.T) *ctm.CTM {
	t.Helper()
	c, err := ctm.Load(repoPath("testdata", "ctm", "mixed.json"))
	if err != nil {
		t.Fatal(err)
	}
	c.Envelope.Branch = "change-1"
	const link = "e1:Ethernet3|s1:ethernet-1/3"
	c.Links = append(c.Links, ctm.Link{ID: link, Endpoints: []ctm.Endpoint{
		{Device: "e1", Interface: "Ethernet3"}, {Device: "s1", Interface: "ethernet-1/3"}}})
	for i := range c.Devices {
		d := &c.Devices[i]
		var name, extra string
		switch d.Name {
		case "e1":
			name = "Ethernet3"
			extra = "interface Ethernet3\n   description to s1 ethernet-1/3\n   no shutdown\n"
		case "s1":
			name = "ethernet-1/3"
			extra = "set / interface ethernet-1/3 description \"to e1 Ethernet3\"\n" +
				"set / interface ethernet-1/3 admin-state enable\n"
		default:
			continue
		}
		enabled := true
		d.Interfaces = append(d.Interfaces, ctm.Interface{Name: name, Enabled: &enabled, Link: link})
		const description = "; FYLGJA-MARKER-mixed-fixture\n"
		if !strings.Contains(d.Artifact.Content, description) {
			t.Fatalf("%s's artifact has no header line ending %q", d.Name, description)
		}
		d.Artifact.Content = strings.Replace(d.Artifact.Content, description, "; "+marker+"\n", 1) + extra
		sum := md5.Sum([]byte(d.Artifact.Content))
		d.Artifact.Checksum = hex.EncodeToString(sum[:])
	}
	return c
}

// withoutE2 is the mixed fixture read from branch change-1 with e2 and its two links
// removed, s1's and e1's ends of them left uncabled.
func withoutE2(t *testing.T) *ctm.CTM {
	t.Helper()
	c, err := ctm.Load(repoPath("testdata", "ctm", "mixed.json"))
	if err != nil {
		t.Fatal(err)
	}
	c.Envelope.Branch = "change-1"
	gone := map[string]bool{}
	var links []ctm.Link
	for _, l := range c.Links {
		if l.Endpoints[0].Device == "e2" || l.Endpoints[1].Device == "e2" {
			gone[l.ID] = true
			continue
		}
		links = append(links, l)
	}
	c.Links = links
	var devices []ctm.Device
	for _, d := range c.Devices {
		if d.Name == "e2" {
			continue
		}
		for i := range d.Interfaces {
			if gone[d.Interfaces[i].Link] {
				d.Interfaces[i].Link = ""
			}
		}
		devices = append(devices, d)
	}
	c.Devices = devices
	return c
}

// stepClab answers the host's tools as a host running the mixed twin does: clab inspect
// --all with the recording inspect, clab deploy --dry-run with the plan recording plan
// (internal/lab/testdata), a docker presence call from images; every call recorded with
// its environment.
type stepClab struct {
	t       *testing.T
	inspect []byte
	plan    []byte
	images  map[string]bool

	mu    sync.Mutex
	calls [][]string
	envs  [][]string
}

func (c *stepClab) Run(_ context.Context, env []string, args ...string) ([]byte, []byte, int, error) {
	c.mu.Lock()
	c.calls = append(c.calls, args)
	c.envs = append(c.envs, env)
	c.mu.Unlock()
	switch {
	case args[0] == "docker":
		ref := args[len(args)-1]
		if c.images[ref] {
			return []byte("sha256:58c3600aacc0c1bd385817e8028fb12f2abb850136ccd9791cec846da82633d4\n"), nil, 0, nil
		}
		return nil, []byte("Error response from daemon: No such image: " + ref + "\n"), 1, nil
	case slices.Equal(args, inspectAll):
		return c.inspect, nil, 0, nil
	case len(args) > 2 && args[1] == "deploy" && slices.Contains(args, "--dry-run"):
		return c.plan, nil, 0, nil
	}
	c.t.Errorf("containerlab was asked %v, which a step never asks", args)
	return nil, []byte("unexpected"), 1, nil
}

// asked is every call containerlab was asked whose first two words are those given.
func (c *stepClab) asked(words ...string) [][]string {
	c.mu.Lock()
	defer c.mu.Unlock()
	var out [][]string
	for _, call := range c.calls {
		if len(call) >= len(words) && slices.Equal(call[:len(words)], words) {
			out = append(out, call)
		}
	}
	return out
}

// useStepClab makes the command's containerlab answer from the two recordings.
func useStepClab(t *testing.T, inspect, plan string) *stepClab {
	t.Helper()
	read := func(name string) []byte {
		if name == "" {
			return nil
		}
		b, err := os.ReadFile(repoPath("internal", "lab", "testdata", name))
		if err != nil {
			t.Fatal(err)
		}
		return b
	}
	c := &stepClab{t: t, inspect: read(inspect), plan: read(plan), images: map[string]bool{"ceos:4.32.0.2F": true}}
	saved := dryRunRunner
	t.Cleanup(func() { dryRunRunner = saved })
	dryRunRunner = c
	return c
}

// stepHostFixture is a host running the mixed twin, as stepHost builds it.
type stepHostFixture struct {
	paths  lab.Paths
	infra  *fakeInfrahub
	clab   *stepClab
	fromID string
	// fromSnapshot is the snapshot the record names, as a create since 018 records it.
	fromSnapshot string
	// before is how many requests Infrahub had answered once the fixture was built.
	before int
	// svc is the workflow service useNoRunsInFlight installed.
	svc *fakeService
}

// useNoRunsInFlight is the workflow service a step refused before its run sees: it answers
// the step's first question, the runs in flight, with none, and fails the test should the
// step start or cancel anything (T080).
func useNoRunsInFlight(t *testing.T) *fakeService {
	t.Helper()
	svc := &fakeService{readOnly: t}
	useService(t, svc)
	return svc
}

// stepHost is a host running the mixed twin, built from stage change-1/sealed by run
// createRunID: the state root, the fake Infrahub, containerlab answering inspect-three.json
// and plan, both logins set and no host budget, and a workflow service with no run in
// flight that starts nothing (useNoRunsInFlight). The from stage's snapshot and bundle are
// taken, built and filed through stage plan's own path, as a create files them, and twin.json
// 9 records both; change adjusts the record before it is written.
func stepHost(t *testing.T, plan string, change func(*lab.RecordFields)) *stepHostFixture {
	t.Helper()
	paths := useStateRoot(t)
	svc := useNoRunsInFlight(t)
	mixedDryRunEnv(t)
	infra := stepInfrahub(t)
	infra.start()
	fromID := buildStage(t, paths, "sealed")
	fromSnapshot := snapshotOf(t, fromID)
	writeTwin(t, paths, stepRecordOf(t, fromID, func(f *lab.RecordFields) {
		f.SnapshotID = fromSnapshot
		if change != nil {
			change(f)
		}
	}))
	return &stepHostFixture{paths: paths, infra: infra, clab: useStepClab(t, "inspect-three.json", plan), fromID: fromID,
		fromSnapshot: fromSnapshot, before: len(infra.requests()), svc: svc}
}

// compiledStage is what stage plan's path hands its take and its filing for one label.
type compiledStage struct {
	snapshot *snap.Snapshot
	files    map[string][]byte
	id       string
}

// builtStages holds buildStage's read, take and compile by label, once for the package, and
// the snapshot each bundle compileStage built was taken as. Every caller reads stepInfrahub's
// proposed change as stepHost builds it, unchanged, so a label compiles to the same files
// each time; only the filing, into each test's own stores, is done again.
var builtStages = struct {
	sync.Mutex
	byLabel    map[string]compiledStage
	snapshotOf map[string]string
}{byLabel: map[string]compiledStage{}, snapshotOf: map[string]string{}}

// snapshotOf is the snapshot id of a bundle compileStage built, as a create records it beside
// the bundle.
func snapshotOf(t *testing.T, bundleID string) string {
	t.Helper()
	builtStages.Lock()
	defer builtStages.Unlock()
	id, ok := builtStages.snapshotOf[bundleID]
	if !ok {
		t.Fatalf("bundle %s was not built by compileStage", bundleID)
	}
	return id
}

// stepStamper reads a branch's stamps as the server's does, but for the conformance check
// before a branch's first, which every branch stepInfrahub serves passes.
type stepStamper struct{}

func (stepStamper) Stamps(ctx context.Context, branch, at, scope string) (intent.Stamps, error) {
	cfg, err := intent.FromEnv(branch, at)
	if err != nil {
		return intent.Stamps{}, err
	}
	cfg.Scope = intent.ScopeTag(scope)
	return intent.New(cfg).Stamps(ctx)
}

// buildStage finds change-1's proposed change and reads, compiles and files its stage label
// through stage plan's path, and returns its id. The read and the compile are builtStages'
// after the first.
func buildStage(t *testing.T, paths lab.Paths, label string) string {
	t.Helper()
	builtStages.Lock()
	built, ok := builtStages.byLabel[label]
	builtStages.Unlock()
	if ok {
		if _, err := snap.NewDirStore(paths.Snapshots).Put(context.Background(), built.snapshot); err != nil {
			t.Fatal(err)
		}
		if _, _, err := fileCompiled(context.Background(), paths.Bundles, built.files, built.id); err != nil {
			t.Fatal(err)
		}
		return built.id
	}
	built = compileStage(t, paths, label)
	builtStages.Lock()
	builtStages.byLabel[label] = built
	builtStages.Unlock()
	return built.id
}

// compileStage is buildStage's read, take, compile and filing, against the fake Infrahub as it
// stands: a test that has changed stepInfrahub's proposed change builds its stages here,
// never through builtStages.
func compileStage(t *testing.T, paths lab.Paths, label string) compiledStage {
	t.Helper()
	ctx := context.Background()
	var built compiledStage
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	reader, err := intent.StageReaderFromEnv()
	if err != nil {
		t.Fatal(err)
	}
	ch, list, err := stages.Find(ctx, reader, stepStamper{}, "change-1", "tag:fylgja")
	if err != nil || ch == nil {
		t.Fatalf("change-1's proposed change was not found: %v %+v", err, list)
	}
	take := func(ctx context.Context, c *ctm.CTM, probes []probe.Probe) (string, findings.List, error) {
		built.snapshot = snap.Take(c, probes)
		_, err := snap.NewDirStore(paths.Snapshots).Put(ctx, built.snapshot)
		return built.snapshot.ID, nil, err
	}
	file := func(ctx context.Context, files map[string][]byte, id string) (findings.List, error) {
		built.files, built.id = files, id
		_, list, err := fileCompiled(ctx, paths.Bundles, files, id)
		return list, err
	}
	ref := stages.Ref{Branch: "change-1", Label: label}
	s := stages.Build(ctx, reader, stepStamper{}, reg, ch, ref, stages.NewPipeline(take, file, nil, nil), time.Now().UTC())
	if s.Status != stages.PlanCompiled {
		t.Fatalf("%s did not compile: %+v", ref, s.Findings)
	}
	if built.id != s.Bundle.ID || built.snapshot.ID != s.SnapshotID {
		t.Fatalf("%s filed %s and %s and compiled to %s and %s", ref, built.snapshot.ID, built.id, s.SnapshotID, s.Bundle.ID)
	}
	builtStages.Lock()
	builtStages.snapshotOf[built.id] = built.snapshot.ID
	builtStages.Unlock()
	return built
}

// stepStage is the record's reference to change-1's stage label.
func stepStage(label, description, atSource string) *wire.StageRef {
	return &wire.StageRef{ProposedChange: stepChange, Label: label, Description: description, AtSource: atSource}
}

// supersededHost is stepHost's twin, or divergedStepHost's when diverged, with its record
// rewritten as twin.json 5, carrying waypoint as M10's record did, or no waypoint key when it
// is nil; a diverged record's step carries it on both sides, as M11's did.
func supersededHost(t *testing.T, waypoint map[string]any, diverged bool) *stepHostFixture {
	t.Helper()
	var h *stepHostFixture
	if diverged {
		h = divergedStepHost(t)
	} else {
		h = stepHost(t, "plan-link-added.json", func(f *lab.RecordFields) {
			if waypoint == nil {
				f.Stage = nil
			}
		})
	}
	b, err := os.ReadFile(h.paths.TwinJSON)
	if err != nil {
		t.Fatal(err)
	}
	var m map[string]any
	if err := json.Unmarshal(b, &m); err != nil {
		t.Fatal(err)
	}
	for k, v := range m {
		if v == lab.TwinVersion && strings.Contains(k, "version") {
			m[k] = "5"
		}
	}
	unsnapshotted(m)
	contractProvenance(m)
	delete(m, "rehearsal")
	delete(m, "stage")
	if waypoint != nil {
		m["waypoint"] = waypoint
	}
	if step, ok := m["step"].(map[string]any); ok {
		for _, side := range []string{"from", "to"} {
			s := step[side].(map[string]any)
			delete(s, "stage")
			s["waypoint"] = waypoint
		}
	}
	if b, err = json.Marshal(m); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(h.paths.TwinJSON, b, 0o644); err != nil {
		t.Fatal(err)
	}
	return h
}

// unscopedHost is stepHost's twin with its record rewritten as a worker of twin.json version,
// 6 or 7, wrote it: the stage it names as written, the contract version in place of the
// scope and the mapping (017), and for a 6 no rehearsal key.
func unscopedHost(t *testing.T, version string) *stepHostFixture {
	t.Helper()
	return editedRecordHost(t, func(m map[string]any) {
		m["twin_version"] = version
		unsnapshotted(m)
		contractProvenance(m)
		if version == "6" {
			delete(m, "rehearsal")
		}
	})
}

// misscopedHost is stepHost's twin with its record an 8 whose provenance's scope is
// scope, as no build of this tree writes one (NewRecord refuses it): edited by hand.
func misscopedHost(t *testing.T, scope string) *stepHostFixture {
	t.Helper()
	return editedRecordHost(t, func(m map[string]any) {
		m["provenance"].(map[string]any)["scope"] = scope
	})
}

// mismappedHost is stepHost's twin with its record's mapping edited by hand, each field
// given replacing the record's: a twin.json 8 naming scope tag:fylgja and a mapping 8 cannot
// hold, which no build of this tree writes (T113).
func mismappedHost(t *testing.T, fields map[string]string) *stepHostFixture {
	t.Helper()
	return editedRecordHost(t, func(m map[string]any) {
		mapping := m["provenance"].(map[string]any)["mapping"].(map[string]any)
		for k, v := range fields {
			mapping[k] = v
		}
	})
}

// editedRecordHost is stepHost's twin with its twin.json edited as JSON by edit.
func editedRecordHost(t *testing.T, edit func(map[string]any)) *stepHostFixture {
	t.Helper()
	h := stepHost(t, "plan-link-added.json", nil)
	b, err := os.ReadFile(h.paths.TwinJSON)
	if err != nil {
		t.Fatal(err)
	}
	var m map[string]any
	if err := json.Unmarshal(b, &m); err != nil {
		t.Fatal(err)
	}
	edit(m)
	if b, err = json.Marshal(m); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(h.paths.TwinJSON, b, 0o644); err != nil {
		t.Fatal(err)
	}
	return h
}

// stepRecordOf is twin.json 8 of the mixed twin created from stage change-1/sealed.
func stepRecordOf(t *testing.T, bundleID string, change func(*lab.RecordFields)) wire.TwinRecord {
	t.Helper()
	observed := "2026-09-21T09:00:00.000000Z"
	f := lab.RecordFields{
		BundleID:   bundleID,
		Provenance: wire.Provenance{Branch: "change-1", At: stepMixedAt, SchemaHash: "fixture", Scope: "tag:fylgja", Mapping: dcimMapping},
		ObservedAt: &observed,
		Source:     wire.SourceIntent,
		RunID:      createRunID,
		Version:    "0.1.0-dev",
		RecordedAt: time.Date(2026, 9, 21, 9, 1, 2, 0, time.UTC),
		Stage:      stepStage("sealed", "the mixed fixture as sealed", "given"),
	}
	for i, n := range []string{"e1", "e2", "s1"} {
		image, id := "ceos:4.32.0.2F", "arista_eos"
		if n == "s1" {
			image, id = "ghcr.io/nokia/srlinux:24.7.1", "nokia_srlinux"
		}
		f.Nodes = append(f.Nodes, wire.TwinNode{Name: n, Container: "clab-fylgja-" + n, Image: image,
			PSP: &wire.PSPRef{ID: id, Source: "embedded"}, MgmtIPv4: fmt.Sprintf("172.20.20.%d", i+2), ReadyAfterS: 9})
	}
	if change != nil {
		change(&f)
	}
	rec, err := lab.NewRecord(f)
	if err != nil {
		t.Fatal(err)
	}
	return rec
}

// stepOutput is what twin step put in front of the operator, in text and in JSON.
type stepOutput struct {
	code   int
	stdout string
	stderr string
	doc    *findings.Document
}

// runStepCmd runs `fylgja twin step <args>` through the command line, once in text and
// once with --json; the JSON document is validated against this feature's contracts.
func runStepCmd(t *testing.T, args ...string) stepOutput {
	t.Helper()
	run := func(asJSON bool) (int, string, string) {
		opts := &options{}
		root := &cobra.Command{Use: "fylgja", SilenceUsage: true, SilenceErrors: true}
		root.PersistentFlags().BoolVar(&opts.asJSON, "json", false, "")
		root.AddCommand(newTwinCmd(opts))
		all := append([]string{"twin", "step"}, args...)
		if asJSON {
			all = append(all, "--json")
		}
		root.SetArgs(all)
		var code int
		var stdout string
		stderr := captureStderr(t, func() {
			stdout = captureStdout(t, func() {
				cmd, err := root.ExecuteC()
				code = report(opts, cmd, err)
			})
		})
		return code, stdout, stderr
	}
	var out stepOutput
	out.code, out.stdout, out.stderr = run(false)
	code, jsonOut, jsonErr := run(true)
	if code != out.code {
		t.Errorf("--json exits %d, text %d", code, out.code)
	}
	if jsonErr != "" {
		t.Errorf("--json wrote on stderr: %s", jsonErr)
	}
	out.doc = &findings.Document{}
	if err := json.Unmarshal([]byte(jsonOut), out.doc); err != nil {
		t.Fatalf("stdout is not one findings document: %v\n%s", err, jsonOut)
	}
	validateM10Document(t, out.doc)
	if out.doc.Operation != findings.OpTwinStep {
		t.Errorf("operation %q, want %s", out.doc.Operation, findings.OpTwinStep)
	}
	return out
}

// refusalOf is the one rejection of doc, failing the test unless there is exactly one.
func refusalOf(t *testing.T, doc *findings.Document) findings.Finding {
	t.Helper()
	var got []findings.Finding
	for _, f := range doc.Findings {
		if f.Severity == findings.Rejection {
			got = append(got, f)
		}
	}
	if len(got) != 1 {
		t.Fatalf("rejections %+v, want exactly one", got)
	}
	return got[0]
}

// noContent fails when any output carries the marker, a line of configuration the fake
// renders or a device diff's line.
func noContent(t *testing.T, label string, outputs ...string) {
	t.Helper()
	for _, o := range outputs {
		if strings.Contains(o, marker) {
			t.Errorf("%s carries the marker:\n%s", label, o)
		}
		for _, prefix := range []string{"insert /", "delete /", "update /", "replace /", "interface Ethernet3", "set / interface"} {
			if strings.Contains(o, prefix) {
				t.Errorf("%s carries %q:\n%s", label, prefix, o)
			}
		}
		if strings.Contains(o, fakeToken) {
			t.Errorf("%s carries the credential", label)
		}
	}
}

func sha256Of(t *testing.T, path string) string {
	t.Helper()
	b, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	sum := sha256.Sum256(b)
	return hex.EncodeToString(sum[:])
}

// short is an id as the step's lines print it.
func short(id string) string { return id[:8] + "…" }

// samePlan says two of containerlab's plans name the same lifecycles, links and reasons, an
// empty list and none alike.
func samePlan(a, b wire.ReconcilePlan) bool {
	return slices.Equal(a.Added, b.Added) && slices.Equal(a.Deleted, b.Deleted) && slices.Equal(a.Recreated, b.Recreated) &&
		slices.Equal(a.Restarted, b.Restarted) && slices.Equal(a.LinksAdded, b.LinksAdded) &&
		slices.Equal(a.EndpointsDeleted, b.EndpointsDeleted) && maps.Equal(a.Reasons, b.Reasons)
}

// stepDryRunLines is the dry run's text for the step change-1/sealed → change-1/linked
// under plan-link-added.json, through the push: line (contracts/cli.md), from h's twin.
func stepDryRunLines(h *stepHostFixture, toID string) []string {
	return []string{
		"dry run: no lab, container, twin directory or run is changed",
		"twin: stage change-1/sealed (snapshot " + short(h.fromSnapshot) + ", bundle " + short(h.fromID) + "), pinned at " +
			stepMixedAt + "; 3 nodes",
		`stage change-1/linked: branch change-1 at ` + stepWrittenAt + ` (written), "a link between e1 and s1"`,
		"step change-1/sealed → change-1/linked (" + short(h.fromID) + " → " + short(toID) + "):",
		"  nodes: ~e1 (mapping); ~s1 (bootstrap, mapping)",
		"  links: +e1:eth3 — s1:e1-3",
		"  artifacts: e1 device-config b1431710… → cbc8c75d…; s1 device-config fdf83f15… → 8e15691e…",
		"reconcile: restart e1 (added link; arista_eos declares restart); live s1 (nokia_srlinux declares live)",
		"push: e1 (artifact, restarted); s1 (artifact, bootstrap); e2 untouched",
		// M12: the step's wait after its record, at the default budget.
		"wait: after the record, until the twin conforms, at most 2m0s",
	}
}

// restartRequired is step.restart.required as plan-link-added.json draws it.
var restartRequired = findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepRestartRequired, Object: "e1",
	Step: findings.StepCompare, Message: "containerlab would restart e1 (added link; package arista_eos declares restart): " +
		"it loses its running state and its push until the step pushes it again; give --allow-restart to proceed, " +
		"or --dry-run to see the step"}

// The dry run of the step change-1/sealed → change-1/linked says, line for line, what a step would do and
// that containerlab would restart e1; it refuses the step without --allow-restart and
// clears it with the flag. Nothing on the host or in the twin directory changes: the plan is
// read from the store's copy of the target against the twin directory's lab state, and the
// target's bundle and CTM are filed in the store. No output quotes configuration and no
// workflow service is dialled.
func TestStepDryRun(t *testing.T) {
	h := stepHost(t, "plan-link-added.json", nil)
	record := sha256Of(t, h.paths.TwinJSON)
	twinDir := stateRootListing(t, h.paths.Twin)

	for _, c := range []struct {
		name    string
		args    []string
		code    int
		verdict string
	}{
		{"refused", []string{"--dry-run"}, findings.ExitRejected, findings.VerdictRefused + " (" + findings.RuleStepRestartRequired + ")"},
		{"clear", []string{"--dry-run", "--allow-restart"}, findings.ExitOK, findings.VerdictClear},
	} {
		t.Run(c.name, func(t *testing.T) {
			h.clab.calls = nil
			out := runStepCmd(t, c.args...)
			if out.code != c.code {
				t.Fatalf("exit %d, want %d; findings %+v", out.code, c.code, out.doc.Findings)
			}
			toID := out.doc.BundleID
			want := strings.Join(append(stepDryRunLines(h, toID),
				"memory: sum 5120 MiB; host budget unset",
				"host: lab fylgja present; twin directory present",
				"verdict: "+c.verdict), "\n") + "\n"
			if out.stdout != want {
				t.Errorf("stdout:\n%s\nwant:\n%s", out.stdout, want)
			}
			noContent(t, "the dry run", out.stdout, out.stderr)
			raw, err := json.Marshal(out.doc)
			if err != nil {
				t.Fatal(err)
			}
			noContent(t, "the dry run's document", string(raw))

			doc := out.doc
			refused := c.code == findings.ExitRejected
			if refused != slices.Contains(doc.Findings, restartRequired) {
				t.Errorf("findings %+v; want %+v exactly when refused", doc.Findings, restartRequired)
			}
			if !carriesRule(doc.Findings, findings.RuleHostMemoryUnbudgeted) || carriesRule(doc.Findings, findings.RuleHostLabPresent) ||
				carriesRule(doc.Findings, findings.RuleHostTwinPresent) {
				t.Errorf("findings %+v; want the unbudgeted warning and neither presence refusal", doc.Findings)
			}
			d := doc.DryRun
			wantVerdict := findings.VerdictClear
			if refused {
				wantVerdict = findings.VerdictRefused
			}
			if d == nil || d.Verdict != wantVerdict || len(d.Nodes) != 3 || d.MemorySumMB != 5120 ||
				!d.Host.LabPresent || !d.Host.TwinDirPresent {
				t.Errorf("dry_run %+v; want %s over the target's three nodes, the twin present", d, wantVerdict)
			}
			st := doc.Step
			if st == nil || st.StepRunBlock != nil || st.AllowRestart != !refused || st.From.BundleID != h.fromID ||
				st.To.BundleID != toID || st.To.Branch != "change-1" || !slices.Equal(st.Reconcile.Restarted, []string{"e1"}) ||
				len(st.PushPlan) != 2 || st.PushPlan[0].Node != "e1" || st.PushPlan[1].Node != "s1" {
				t.Errorf("step block %+v; want the two sides, e1 restarted, e1 and s1 pushed, and no run", st)
			}
			// The JSON says what the reconcile: and push: lines print, with the link
			// plan-link-added.json adds, which the reconcile: line does not print.
			restart, live := "restart", "live"
			reconcile, err := json.Marshal(findings.StepReconcileBlock{Restarted: []string{"e1"}, LinksAdded: []string{"e1:eth2 -- s1:e1-2"},
				Nodes: []findings.StepPlanNode{{Node: "e1", Declared: &restart, Reported: "restart", Reason: "added link"},
					{Node: "s1", Declared: &live, Reported: "live"}}})
			if err != nil {
				t.Fatal(err)
			}
			pushPlan := []findings.StepPushPlanEntry{{Node: "e1", Reasons: []string{"artifact", "restarted"}},
				{Node: "s1", Reasons: []string{"artifact", "bootstrap"}}}
			if st != nil {
				got, err := json.Marshal(st.Reconcile)
				if err != nil {
					t.Fatal(err)
				}
				if string(got) != string(reconcile) {
					t.Errorf("step.reconcile\n got %s\nwant %s", got, reconcile)
				}
				if !reflect.DeepEqual(st.PushPlan, pushPlan) {
					t.Errorf("step.push_plan %+v, want %+v", st.PushPlan, pushPlan)
				}
			}
			if doc.Stage == nil || doc.Stage.Ref != "change-1/linked" || doc.Stage.Branch != "change-1" ||
				doc.Stage.AtSource != findings.AtSourceWritten || doc.Stage.ProposedChange.ID != stepChange.ID {
				t.Errorf("stage block %+v; want change-1/linked, written, of pc-1", doc.Stage)
			}
			if sub := doc.Subject; sub == nil || sub.Stage != "change-1/linked" || sub.Branch != "change-1" || sub.At != stepWrittenAt || sub.RunID != "" {
				t.Errorf("subject %+v; want change-1/linked resolved and no run", sub)
			}

			// containerlab's plan is the store's copy of the target, against the twin
			// directory's lab state: once per run of the command, text and
			// JSON, and nothing else of containerlab but inspect.
			wantPlan := []string{"clab", "deploy", "--dry-run", "--topo",
				filepath.Join(h.paths.Bundles, toID, "topology.clab.yml"), "--format", "json"}
			plans := 0
			for i, call := range h.clab.calls {
				switch {
				case call[0] == "docker" || slices.Equal(call, inspectAll):
				case slices.Equal(call, wantPlan):
					plans++
					if !slices.Contains(h.clab.envs[i], "CLAB_LABDIR_BASE="+h.paths.Twin) {
						t.Errorf("the plan was read with the environment %v, without CLAB_LABDIR_BASE=%s", h.clab.envs[i], h.paths.Twin)
					}
				default:
					t.Errorf("containerlab was asked %v", call)
				}
			}
			if plans != 2 {
				t.Errorf("containerlab's plan was asked %d times; want once per run of the command, %v", plans, wantPlan)
			}
			if got := storedBundles(t, h.paths.Bundles); !slices.Equal(got, sortedCopy(h.fromID, toID)) {
				t.Errorf("the store holds %v; want the from bundle and the target, each with its CTM", got)
			}
			// The marker is in the target's filed artifacts, so its absence from every output
			// above proves something.
			files := artifactFiles(t, filepath.Join(h.paths.Bundles, toID))
			for p := range files {
				if filepath.Base(p) == "e2.device-config" {
					delete(files, p)
				}
			}
			carriesMarker(t, "the target's changed artifacts", files)
		})
	}
	// FR-017: a step to a snapshot keeps --allow-restart (019). The same target by its
	// snapshot id is refused step.restart.required naming e1 without the flag, and is clear
	// with it.
	target, toID := targetSnapshot(t, h, "linked")
	for _, c := range []struct {
		name    string
		args    []string
		code    int
		verdict string
	}{
		{"to a snapshot, refused", []string{"--dry-run"}, findings.ExitRejected, findings.VerdictRefused},
		{"to a snapshot, clear", []string{"--dry-run", "--allow-restart"}, findings.ExitOK, findings.VerdictClear},
	} {
		t.Run(c.name, func(t *testing.T) {
			out := runStepCmd(t, append(c.args, "--snapshot", target.ID)...)
			if out.code != c.code {
				t.Fatalf("exit %d, want %d; findings %+v", out.code, c.code, out.doc.Findings)
			}
			refused := c.code == findings.ExitRejected
			doc := out.doc
			if refused != slices.Contains(doc.Findings, restartRequired) {
				t.Errorf("findings %+v; want %+v exactly when refused", doc.Findings, restartRequired)
			}
			if d := doc.DryRun; d == nil || d.Verdict != c.verdict {
				t.Errorf("dry_run %+v; want %s", d, c.verdict)
			}
			if st := doc.Step; doc.SnapshotID != target.ID || doc.BundleID != toID || st == nil || st.StepRunBlock != nil ||
				st.AllowRestart != !refused || st.To.SnapshotID != target.ID || !slices.Equal(st.Reconcile.Restarted, []string{"e1"}) {
				t.Errorf("snapshot %s, bundle %s, step block %+v; want the target's, e1 restarted, and no run", doc.SnapshotID,
					doc.BundleID, st)
			}
		})
	}
	if got := sha256Of(t, h.paths.TwinJSON); got != record {
		t.Errorf("twin.json changed under a dry run")
	}
	if got := stateRootListing(t, h.paths.Twin); !slices.Equal(got, twinDir) {
		t.Errorf("the twin directory changed under a dry run:\n%v\nwas\n%v", got, twinDir)
	}
}

// divergedStepHost is stepHost's twin left diverged by a step towards change-1/linked that
// stopped at push, e1 refused and s1 landed.
func divergedStepHost(t *testing.T) *stepHostFixture {
	t.Helper()
	h := stepHost(t, "plan-link-added.json", nil)
	rec, err := lab.ReadRecord(h.paths.TwinJSON)
	if err != nil {
		t.Fatal(err)
	}
	phase := findings.StepPush
	rec.State = wire.StateDiverged
	rec.Step = &wire.StepRecord{Outcome: wire.StepDiverged, Phase: &phase,
		Run:  wire.RunRef{WorkflowID: provision.WorkflowStep, RunID: stepRunID},
		From: wire.StepSide{Stage: rec.Stage, BundleID: rec.BundleID, At: stepMixedAt},
		To: wire.StepSide{Stage: stepStage("linked", "a link between e1 and s1", "written"),
			BundleID: strings.Repeat("f44ca840", 8), At: stepWrittenAt},
		Pushed: []wire.StepPush{{Node: "e1", Reasons: []string{"artifact"}, Outcome: wire.PushRefused, Rule: findings.RulePushRefused},
			{Node: "s1", Reasons: []string{"artifact"}, Outcome: wire.PushLanded}}}
	writeTwin(t, h.paths, rec)
	return h
}

// divergedRefusal is step.twin.diverged as divergedStepHost's record draws it, its object the
// record's bundle_id.
func divergedRefusal(bundleID string) findings.Finding {
	return findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepTwinDiverged, Step: findings.StepResolve, Object: bundleID,
		Message: "the twin is diverged: step run fylgja-step " + stepRunID + " towards stage change-1/linked stopped at phase push " +
			"(landed: s1; not landed: e1 (push.refused)); it accepts only fylgja twin destroy"}
}

// The dry run gives the step's refusals as the step gives them, each in its own form:
// a diverged twin is refused before anything is read,
// with no verdict; a merge package refuses the verdict, naming the package and its nodes;
// and a host-check refusal is named in the verdict beside the plan's rules, containerlab's
// plan still read, where the step stops at the host check. No service is dialled, and the
// record and the twin directory are as they were.
func TestStepDryRunRefusals(t *testing.T) {
	const opening = "dry run: no lab, container, twin directory or run is changed\n"
	for _, c := range []struct {
		name string
		host func(t *testing.T) *stepHostFixture
		args []string
		// rules are the rejections' rules in the document's order, which the verdict names.
		rules []string
		// want is the refusal the case is about, its object "" filled with the from bundle.
		want *findings.Finding
		// memory is the dry run's memory: line, and "" when it stops before the host check.
		memory string
		// plans is how often containerlab's plan was read, over the text and JSON runs.
		plans int
		// asked says whether Infrahub was asked anything once the host was built.
		asked bool
	}{
		{name: "a diverged twin", host: divergedStepHost, rules: []string{findings.RuleStepTwinDiverged}},
		{name: "a merge package", host: func(t *testing.T) *stepHostFixture {
			h := stepHost(t, "plan-link-added.json", nil)
			t.Setenv("FYLGJA_PSP_DIR", overridePackage(t, "nokia_srlinux", "mode: replace", "mode: merge"))
			return h
		}, args: []string{"--allow-restart"}, rules: []string{findings.RuleStepPackageMerge},
			want: &findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepPackageMerge, Step: findings.StepCompare,
				Object: "nokia_srlinux", Message: "support package nokia_srlinux pushes by merge, which a step cannot use: a step " +
					"removes what the previous artifact added, and only a replace does that; nodes s1; a create from it is unaffected"},
			memory: "memory: sum 5120 MiB; host budget unset", plans: 2, asked: true},
		{name: "the host's memory beside the plan's rule", host: func(t *testing.T) *stepHostFixture {
			h := stepHost(t, "plan-link-added.json", nil)
			t.Setenv(lab.EnvHostMemoryMB, "4096")
			return h
		}, rules: []string{findings.RuleHostMemoryExceeded, findings.RuleStepRestartRequired}, want: &restartRequired,
			memory: "memory: sum 5120 MiB; host budget 4096 MiB", plans: 2, asked: true},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := c.host(t)
			h.clab.calls = nil
			record := sha256Of(t, h.paths.TwinJSON)
			twinDir := stateRootListing(t, h.paths.Twin)

			out := runStepCmd(t, append([]string{"--dry-run"}, c.args...)...)
			if out.code != findings.ExitRejected || out.doc.Status != findings.StatusRejected {
				t.Fatalf("exit %d, status %s; want 1, rejected; findings %+v", out.code, out.doc.Status, out.doc.Findings)
			}
			var rules []string
			for _, f := range out.doc.Findings {
				if f.Severity == findings.Rejection {
					rules = append(rules, f.Rule)
				}
			}
			if !slices.Equal(rules, c.rules) {
				t.Errorf("rejections %v; want %v; findings %+v", rules, c.rules, out.doc.Findings)
			}
			if c.want != nil && !slices.Contains(out.doc.Findings, *c.want) {
				t.Errorf("findings %+v; want %+v", out.doc.Findings, *c.want)
			}
			noContent(t, "the dry run", out.stdout, out.stderr)

			if c.memory == "" {
				// Refused at resolve, before any read: no verdict, no step, no dry_run block.
				if want := divergedRefusal(h.fromID); refusalOf(t, out.doc) != want {
					t.Errorf("refusal %+v; want %+v", refusalOf(t, out.doc), want)
				}
				if out.stdout != opening {
					t.Errorf("stdout:\n%s\nwant only:\n%s", out.stdout, opening)
				}
				if out.doc.DryRun != nil || out.doc.Step != nil || out.doc.BundleID != "" {
					t.Errorf("dry_run %+v, step %+v, bundle_id %q; want none of them", out.doc.DryRun, out.doc.Step, out.doc.BundleID)
				}
			} else {
				verdict := "verdict: " + findings.VerdictRefused + " (" + strings.Join(c.rules, ", ") + ")\n"
				tail := c.memory + "\nhost: lab fylgja present; twin directory present\n" + verdict
				if !strings.HasPrefix(out.stdout, opening) || !strings.HasSuffix(out.stdout, tail) {
					t.Errorf("stdout:\n%s\nwant it to end:\n%s", out.stdout, tail)
				}
				if d := out.doc.DryRun; d == nil || d.Verdict != findings.VerdictRefused {
					t.Errorf("dry_run %+v; want verdict %s", d, findings.VerdictRefused)
				}
				if st := out.doc.Step; st == nil || st.StepRunBlock != nil || !slices.Equal(st.Reconcile.Restarted, []string{"e1"}) {
					t.Errorf("step block %+v; want e1 restarted and no run", st)
				}
			}
			if plans := len(h.clab.asked("clab", "deploy")); plans != c.plans {
				t.Errorf("containerlab's plan was read %d times; want %d", plans, c.plans)
			}
			if asked := len(h.infra.requests()) > h.before; asked != c.asked {
				t.Errorf("Infrahub asked after the host was built: %v, want %v", asked, c.asked)
			}
			if got := sha256Of(t, h.paths.TwinJSON); got != record {
				t.Errorf("twin.json changed under a dry run")
			}
			if got := stateRootListing(t, h.paths.Twin); !slices.Equal(got, twinDir) {
				t.Errorf("the twin directory changed under a dry run:\n%v\nwas\n%v", got, twinDir)
			}
			if len(h.svc.reads) != 0 || len(h.svc.calls) != 0 {
				t.Errorf("the dry run asked the workflow service %v %v; want nothing, as twin create --dry-run", h.svc.reads, h.svc.calls)
			}
		})
	}
}

// Beside a rehearsal in flight a step is refused run.in_flight, naming the rehearsal's run,
// before the host or Infrahub is read (FR-007, FR-008; T080): during the baseline's
// provision, where the host holds a lab and no record and the step would call the
// rehearsal's twin an orphan, and after a diverged stage, where it would refuse the twin as
// diverged. Nothing is started, and containerlab is asked nothing.
func TestStepBesideARehearsalNamesItBeforeAnyRead(t *testing.T) {
	for _, c := range []struct {
		name string
		host func(t *testing.T) *stepHostFixture
		run  provision.RunInFlight
	}{
		{"during the baseline's provision", func(t *testing.T) *stepHostFixture {
			paths := useStateRoot(t)
			infra := stepInfrahub(t)
			infra.start()
			return &stepHostFixture{paths: paths, infra: infra, clab: useStepClab(t, "inspect-three.json", ""),
				before: len(infra.requests())}
		}, provision.RunInFlight{WorkflowID: provision.WorkflowRehearse, RunID: "r1", Step: "provision",
			Child: &provision.RunInFlight{WorkflowID: provision.WorkflowProvision, RunID: "p1", Step: findings.StepDeploy}}},
		{"after a diverged stage", divergedStepHost, provision.RunInFlight{WorkflowID: provision.WorkflowRehearse, RunID: "r1",
			Step: "destroy", Child: &provision.RunInFlight{WorkflowID: provision.WorkflowDestroy, RunID: "d1", Step: findings.StepTeardown}}},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := c.host(t)
			svc := &fakeService{readOnly: t, inFlight: []provision.RunInFlight{c.run}}
			useService(t, svc)
			h.clab.calls = nil

			out := runStepCmd(t, "--allow-restart")
			want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleRunInFlight, Step: findings.StepStart,
				Object:  provision.WorkflowRehearse,
				Message: "rehearsal run r1 is already in flight; wait for it to finish, or run fylgja twin destroy to cancel it"}
			if got := refusalOf(t, out.doc); out.code != findings.ExitRejected || len(out.doc.Findings) != 1 || got != want {
				t.Errorf("exit %d, findings %+v; want 1 and %+v alone", out.code, out.doc.Findings, want)
			}
			if asked := len(h.infra.requests()) > h.before; asked {
				t.Errorf("Infrahub was asked %+v; want nothing read", h.infra.requests()[h.before:])
			}
			if len(h.clab.calls) != 0 {
				t.Errorf("containerlab or docker was asked %v; want nothing read", h.clab.calls)
			}
			svc.mu.Lock()
			defer svc.mu.Unlock()
			if len(svc.calls) != 0 {
				t.Errorf("the service was asked %v; want nothing started", svc.calls)
			}
		})
	}
}

// Two warnings leave the exit as it is: a step that skips stages of its proposed change, and
// a package whose declared link change containerlab's plan contradicts.
func TestStepWarnings(t *testing.T) {
	t.Run("skipped", func(t *testing.T) {
		stepHost(t, "plan-nothing.json", nil)
		out := runStepCmd(t, "--stage", "change-1/again", "--dry-run")
		want := findings.Finding{Severity: findings.Warning, Rule: findings.RuleStepStageSkipped, Object: "change-1/again",
			Step: findings.StepResolve, Message: "the step from change-1/sealed to change-1/again skips stage linked; the step is between the two bundles either way"}
		if out.code != findings.ExitOK || !slices.Contains(out.doc.Findings, want) {
			t.Errorf("exit %d, findings %+v; want 0 beside %+v", out.code, out.doc.Findings, want)
		}
		for _, line := range []string{"reconcile: nothing to apply\n", "push: nobody\n", "verdict: clear\n",
			": unchanged; the ids differ by provenance alone\n"} {
			if !strings.Contains(out.stdout, line) {
				t.Errorf("stdout does not say %q:\n%s", line, out.stdout)
			}
		}
	})
	// An unchanged step pushes nobody even beside a lab containerlab would change, as the run
	// does: the plan is printed as containerlab gave it.
	t.Run("unchanged beside a drifted lab", func(t *testing.T) {
		stepHost(t, "plan-link-added.json", nil)
		out := runStepCmd(t, "--stage", "change-1/again", "--dry-run", "--allow-restart")
		if out.code != findings.ExitOK || !strings.Contains(out.stdout,
			"reconcile: restart e1 (added link; arista_eos declares restart); live s1 (nokia_srlinux declares live)\npush: nobody\n") ||
			out.doc.Step == nil || len(out.doc.Step.PushPlan) != 0 {
			t.Errorf("exit %d, stdout:\n%s", out.code, out.stdout)
		}
	})
	t.Run("undeclared", func(t *testing.T) {
		h := stepHost(t, "plan-link-added.json", nil)
		h.clab.plan = []byte(`{"dry-run": true, "deployed-lab": false, "lab-name": "fylgja", "added-nodes": [],
			"deleted-nodes": [], "recreated-nodes": [], "added-links": ["e1:eth3 -- s1:e1-3"], "deleted-endpoints": [],
			"restarted-nodes": ["s1"], "node-change-reasons": {"s1": "added link"}}`)
		out := runStepCmd(t, "--dry-run", "--allow-restart")
		want := []findings.Finding{
			{Severity: findings.Warning, Rule: findings.RuleStepRestartUndeclared, Object: "e1", Step: findings.StepCompare,
				Message: "package arista_eos declares that a link change restarts the node, but containerlab's plan re-cables e1 live; " +
					"the step acts on containerlab's plan and records both"},
			{Severity: findings.Warning, Rule: findings.RuleStepRestartUndeclared, Object: "s1", Step: findings.StepCompare,
				Message: "package nokia_srlinux declares that a link change is live, but containerlab's plan restarts s1 (added link); " +
					"the step acts on containerlab's plan and records both"},
		}
		for _, w := range want {
			if !slices.Contains(out.doc.Findings, w) {
				t.Errorf("findings %+v; want %+v", out.doc.Findings, w)
			}
		}
		if out.code != findings.ExitOK || !strings.Contains(out.stdout,
			"reconcile: live e1 (arista_eos declares restart); restart s1 (added link; nokia_srlinux declares live)\n") {
			t.Errorf("exit %d, stdout:\n%s", out.code, out.stdout)
		}
	})
}

// The reconcile: line names containerlab's other lifecycles as contracts/cli.md does: a
// recreated node with its reason and its package's declaration, a created node with no
// declaration, since no link change of its is at stake, and a deleted node last. Each plan
// is written here, as containerlab would print it for the step; every
// node it touches is one the target bundle names, so its package is found.
func TestStepDryRunReconcileLifecycles(t *testing.T) {
	for _, c := range []struct {
		name string
		// fromLess builds the twin from change-1/less, e2 retired, so that a step to
		// change-1/linked adds e2.
		fromLess bool
		args     []string
		plan     string
		line     string
	}{
		{name: "a recreate and a delete", args: []string{"--stage", "change-1/less"},
			plan: `{"dry-run": true, "deployed-lab": false, "lab-name": "fylgja", "added-nodes": [], "deleted-nodes": ["e2"],
				"recreated-nodes": ["s1"], "started-nodes": [], "added-links": [], "deleted-endpoints": [], "restarted-nodes": [],
				"node-change-reasons": {"s1": "config drift: Image"}}`,
			line: "reconcile: recreate s1 (config drift: Image; nokia_srlinux declares live); delete e2"},
		{name: "a create", fromLess: true, args: []string{"--stage", "change-1/linked"},
			plan: `{"dry-run": true, "deployed-lab": false, "lab-name": "fylgja", "added-nodes": ["e2"], "deleted-nodes": [],
				"recreated-nodes": [], "started-nodes": [],
				"added-links": ["e1:eth2_1 -- e2:eth1", "e2:eth3_1_1 -- s1:e1-2", "e1:eth3 -- s1:e1-3"], "deleted-endpoints": [],
				"restarted-nodes": ["e1"], "node-change-reasons": {"e1": "added link"}}`,
			line: "reconcile: restart e1 (added link; arista_eos declares restart); create e2; live s1 (nokia_srlinux declares live)"},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := stepHost(t, "plan-nothing.json", nil)
			if c.fromLess {
				fromID := buildStage(t, h.paths, "less")
				writeTwin(t, h.paths, stepRecordOf(t, fromID, func(f *lab.RecordFields) {
					f.Provenance.At, f.SnapshotID = stepLessAt, snapshotOf(t, fromID)
					f.Stage = stepStage("less", "e2 retired", "given")
					f.Nodes = slices.DeleteFunc(f.Nodes, func(n wire.TwinNode) bool { return n.Name == "e2" })
				}))
			}
			h.clab.plan = []byte(c.plan)
			out := runStepCmd(t, append([]string{"--dry-run", "--allow-restart"}, c.args...)...)
			if !strings.Contains(out.stdout, "\n"+c.line+"\n") {
				t.Errorf("stdout does not say %q:\n%s", c.line, out.stdout)
			}
			noContent(t, "the dry run", out.stdout, out.stderr)
		})
	}
}

// Every refusal of contracts/cli.md's table before the run ends the command with its rule,
// step, object, message and exit, and the workflow service is never dialled. So does
// each part of the command that cannot run: operation.failed, exit 2, at its step
// (contracts/cli.md). A target refused at its resolution is refused before any branch's
// intent is read, and before the from bundle, the host check and containerlab's plan:
// its host has neither the record's bundle nor the memory a step needs, and is refused
// for the target alone (FR-018, SC-005).
func TestStepRefusedBeforeAnyConnection(t *testing.T) {
	const orphanAt = "/tmp/scratchpad/twin3/bundle/topology.clab.yml"
	refusal := func(rule, step, object, message string) findings.Finding {
		return findings.Finding{Severity: findings.Rejection, Rule: rule, Step: step, Object: object, Message: message}
	}
	// unsourced ends step.twin.unsteppable's message for a twin whose record names no
	// snapshot (019, research R-03).
	const unsourced = "; only a twin whose record names a snapshot steps; fylgja twin destroy clears it"
	// misscoped is step.twin.unsteppable's message for an 8 whose scope is not tag:<name>.
	misscoped := func(scope string) string {
		return `the twin's record names scope "` + scope + `", which is not tag:<name>, and every read a step makes is ` +
			"under the record's scope; fylgja twin destroy clears it"
	}
	// mismapped is its message for an 8 whose mapping twin.json 8 cannot hold, each failing
	// field named in twin show's order.
	mismapped := func(named string) string {
		return "the twin's record names mapping " + named + ", which twin.json 8 cannot hold, and a step that diverges " +
			"keeps the record's mapping in the record it writes; fylgja twin destroy clears it"
	}
	// refusedTarget is the stage twin's host with the record's bundle gone from the store
	// and too little memory for the step, edited: a target refused there is refused
	// before the from bundle is read and the host checked, either of which would refuse
	// the step otherwise.
	refusedTarget := func(edit func(h *stepHostFixture)) func(t *testing.T) *stepHostFixture {
		return func(t *testing.T) *stepHostFixture {
			h := stepHost(t, "plan-link-added.json", nil)
			if err := os.RemoveAll(filepath.Join(h.paths.Bundles, h.fromID)); err != nil {
				t.Fatal(err)
			}
			t.Setenv(lab.EnvHostMemoryMB, "4096")
			edit(h)
			return h
		}
	}
	for _, c := range []struct {
		name string
		// host builds the host; nil is the stage twin of change-1/sealed under plan-link-added.
		host func(t *testing.T) *stepHostFixture
		args []string
		code int
		// want is the one rejection; its object or message "" is filled from the host by fill.
		want findings.Finding
		fill func(h *stepHostFixture, f *findings.Finding)
		// asked says whether Infrahub was asked anything once the host was built; unread,
		// that it was asked no branch's intent, as no refusal before the read is.
		asked, unread bool
	}{
		{name: "no lab and no twin directory", host: func(t *testing.T) *stepHostFixture {
			paths := useStateRoot(t)
			useNoRunsInFlight(t)
			infra := stepInfrahub(t)
			infra.start()
			return &stepHostFixture{paths: paths, infra: infra, clab: useStepClab(t, "inspect-empty.json", "")}
		}, code: findings.ExitRejected, want: refusal(findings.RuleStepTwinUnsteppable, findings.StepResolve, "lab fylgja",
			"no twin: no lab fylgja and no twin directory; a twin built from a snapshot steps (fylgja twin create --branch, --stage or --snapshot)")},
		{name: "an orphan", host: func(t *testing.T) *stepHostFixture {
			paths := useStateRoot(t)
			useNoRunsInFlight(t)
			infra := stepInfrahub(t)
			infra.start()
			return &stepHostFixture{paths: paths, infra: infra, clab: useStepClab(t, "inspect-three.json", "")}
		}, code: findings.ExitRejected, want: refusal(findings.RuleStepTwinUnsteppable, findings.StepResolve, "lab fylgja",
			"an orphan: no twin.json records it; deployed from "+orphanAt+"; a twin built from a snapshot steps; fylgja twin destroy clears it")},
		{name: "a record that cannot be read", host: func(t *testing.T) *stepHostFixture {
			h := stepHost(t, "plan-link-added.json", nil)
			if err := os.WriteFile(h.paths.TwinJSON, []byte("{"), 0o644); err != nil {
				t.Fatal(err)
			}
			return h
		}, code: findings.ExitRejected, want: refusal(findings.RuleStepTwinUnsteppable, findings.StepResolve, "lab fylgja", ""),
			fill: func(h *stepHostFixture, f *findings.Finding) {
				_, err := lab.ReadRecord(h.paths.TwinJSON)
				f.Message = "treated as an orphan: twin.json could not be read (" + err.Error() + "); deployed from " + orphanAt +
					"; a twin built from a snapshot steps; fylgja twin destroy clears it"
			}},
		{name: "a record whose lab is absent", host: func(t *testing.T) *stepHostFixture {
			h := stepHost(t, "plan-link-added.json", nil)
			h.clab.inspect = []byte("{}")
			return h
		}, code: findings.ExitRejected, want: refusal(findings.RuleStepTwinUnsteppable, findings.StepResolve, "", ""),
			fill: func(h *stepHostFixture, f *findings.Finding) {
				f.Object = h.paths.Twin
				f.Message = "the twin of branch change-1 at " + stepMixedAt + ", bundle_id " + h.fromID +
					", provisioned by run fylgja-provision " + createRunID + ", 3 nodes recorded, but lab fylgja is absent; " +
					"a twin built from a snapshot steps; fylgja twin destroy clears it"
			}},
		{name: "a leftover twin directory", host: func(t *testing.T) *stepHostFixture {
			paths := useStateRoot(t)
			useNoRunsInFlight(t)
			infra := stepInfrahub(t)
			infra.start()
			if err := os.MkdirAll(filepath.Join(paths.Twin, "bundle"), 0o755); err != nil {
				t.Fatal(err)
			}
			return &stepHostFixture{paths: paths, infra: infra, clab: useStepClab(t, "inspect-empty.json", "")}
		}, code: findings.ExitRejected, want: refusal(findings.RuleStepTwinUnsteppable, findings.StepResolve, "",
			"a leftover twin directory: no twin.json and no lab fylgja; a twin built from a snapshot steps; fylgja twin destroy clears it"),
			fill: func(h *stepHostFixture, f *findings.Finding) { f.Object = h.paths.Twin }},
		// A twin naming no stage, given no target, has no next stage (019, research R-08):
		// refused from its record alone (TestStepWithNoTargetNamesNoStage).
		{name: "a twin of a branch given no target", host: func(t *testing.T) *stepHostFixture {
			return stepHost(t, "plan-link-added.json", func(f *lab.RecordFields) { f.Stage, f.Provenance.At = nil, "" })
		}, code: findings.ExitRejected, want: refusal(findings.RuleStepTargetUnknown, findings.StepResolve, "", noTargetMessage),
			fill: func(h *stepHostFixture, f *findings.Finding) { f.Object = h.fromID }},
		{name: "a twin of a branch at a time given no target", host: func(t *testing.T) *stepHostFixture {
			return stepHost(t, "plan-link-added.json", func(f *lab.RecordFields) { f.Stage = nil })
		}, code: findings.ExitRejected, want: refusal(findings.RuleStepTargetUnknown, findings.StepResolve, "", noTargetMessage),
			fill: func(h *stepHostFixture, f *findings.Finding) { f.Object = h.fromID }},
		// A twin whose record names no snapshot (019, research R-03): a bundle twin, a record of
		// 8, and a 9 or a 10 naming none, an earlier build's rebuild, each refused naming why,
		// after the record's version and scope are judged and before Infrahub is asked. One
		// naming no stage is refused so given no target, from its record alone (R-08, as
		// amended; TestStepWithNoTargetNamesNoStage).
		{name: "a twin of a bundle", host: func(t *testing.T) *stepHostFixture {
			return stepHost(t, "plan-link-added.json", func(f *lab.RecordFields) {
				f.Stage, f.Source, f.ObservedAt, f.Provenance.At, f.SnapshotID = nil, wire.SourceBundle, nil, "", ""
			})
		}, code: findings.ExitRejected, want: refusal(findings.RuleStepTwinUnsteppable, findings.StepResolve, "",
			"the twin was provisioned from a bundle, which names no snapshot"+unsourced),
			fill: func(h *stepHostFixture, f *findings.Finding) { f.Object = h.fromID }},
		{name: "a twin of a bundle of twin.json 8", host: func(t *testing.T) *stepHostFixture {
			return editedRecordHost(t, func(m map[string]any) {
				m["twin_version"], m["source"], m["stage"], m["observed_at"] = "8", wire.SourceBundle, nil, nil
				m["observed_at_note"] = lab.ObservedAtUnknown
				unsnapshotted(m)
			})
		}, code: findings.ExitRejected, want: refusal(findings.RuleStepTwinUnsteppable, findings.StepResolve, "",
			"the twin was provisioned from a bundle, which names no snapshot"+unsourced),
			fill: func(h *stepHostFixture, f *findings.Finding) { f.Object = h.fromID }},
		// The stage twin of a record of 8 that stepped under 018 now refuses (the clarification).
		{name: "a stage twin of twin.json 8", host: func(t *testing.T) *stepHostFixture {
			return editedRecordHost(t, func(m map[string]any) {
				m["twin_version"] = "8"
				unsnapshotted(m)
			})
		}, code: findings.ExitRejected, want: refusal(findings.RuleStepTwinUnsteppable, findings.StepResolve, "",
			"the twin was created from a record version that names no snapshot (twin.json 8)"+unsourced),
			fill: func(h *stepHostFixture, f *findings.Finding) { f.Object = h.fromID }},
		{name: "a stage twin of twin.json 9 naming no snapshot", host: func(t *testing.T) *stepHostFixture {
			return editedRecordHost(t, func(m map[string]any) { m["twin_version"], m["snapshot_id"] = "9", nil })
		}, code: findings.ExitRejected, want: refusal(findings.RuleStepTwinUnsteppable, findings.StepResolve, "",
			"the twin's record names no snapshot (an earlier build's rebuild made it)"+unsourced),
			fill: func(h *stepHostFixture, f *findings.Finding) { f.Object = h.fromID }},
		{name: "a stage twin of twin.json 10 naming no snapshot", host: func(t *testing.T) *stepHostFixture {
			return stepHost(t, "plan-link-added.json", func(f *lab.RecordFields) { f.SnapshotID = "" })
		}, code: findings.ExitRejected, want: refusal(findings.RuleStepTwinUnsteppable, findings.StepResolve, "",
			"the twin's record names no snapshot (an earlier build's rebuild made it)"+unsourced),
			fill: func(h *stepHostFixture, f *findings.Finding) { f.Object = h.fromID }},
		{name: "a branch twin naming no snapshot", host: func(t *testing.T) *stepHostFixture {
			return stepHost(t, "plan-link-added.json", func(f *lab.RecordFields) { f.Stage, f.SnapshotID = nil, "" })
		}, code: findings.ExitRejected, want: refusal(findings.RuleStepTwinUnsteppable, findings.StepResolve, "",
			"the twin's record names no snapshot (an earlier build's rebuild made it)"+unsourced),
			fill: func(h *stepHostFixture, f *findings.Finding) { f.Object = h.fromID }},
		// The order (R-03): the record's version and scope are judged before its snapshot, so a
		// bundle twin of 7 is refused naming its version, and a 10 naming no snapshot and a
		// scope that is not tag:<name> naming its scope.
		{name: "a twin of a bundle of twin.json 7", host: func(t *testing.T) *stepHostFixture {
			return editedRecordHost(t, func(m map[string]any) {
				m["twin_version"], m["source"], m["stage"], m["observed_at"] = "7", wire.SourceBundle, nil, nil
				m["observed_at_note"] = lab.ObservedAtUnknown
				unsnapshotted(m)
				contractProvenance(m)
			})
		}, code: findings.ExitRejected, want: refusal(findings.RuleStepTwinUnsteppable, findings.StepResolve, "",
			"the twin was created from a record version this build no longer reads (twin.json 7); fylgja twin destroy clears it"),
			fill: func(h *stepHostFixture, f *findings.Finding) { f.Object = h.fromID }},
		{name: "a twin of twin.json 10 naming no snapshot and scope fylgja", host: func(t *testing.T) *stepHostFixture {
			return editedRecordHost(t, func(m map[string]any) {
				m["snapshot_id"] = nil
				m["provenance"].(map[string]any)["scope"] = "fylgja"
			})
		}, code: findings.ExitRejected, want: refusal(findings.RuleStepTwinUnsteppable, findings.StepResolve, "", misscoped("fylgja")),
			fill: func(h *stepHostFixture, f *findings.Finding) { f.Object = h.fromID }},
		// A record of twin.json 5 or earlier reads with no stage (R-11): one naming M10's
		// waypoint is the superseded reference, one naming none the branch it was read from.
		{name: "a record of twin.json 5 naming a waypoint", host: func(t *testing.T) *stepHostFixture {
			return supersededHost(t, map[string]any{"series": "steps", "sequence": 1,
				"description": "the mixed fixture as sealed", "at_source": "given"}, false)
		}, code: findings.ExitRejected, want: refusal(findings.RuleStepTwinUnsteppable, findings.StepResolve, "",
			"the twin was created from a waypoint of a record version this build no longer reads (twin.json 5); "+
				"a twin built from a snapshot steps; fylgja twin destroy clears it"),
			fill: func(h *stepHostFixture, f *findings.Finding) { f.Object = h.fromID }},
		{name: "a record of twin.json 5 naming no waypoint", host: func(t *testing.T) *stepHostFixture {
			return supersededHost(t, nil, false)
		}, code: findings.ExitRejected, want: refusal(findings.RuleStepTwinUnsteppable, findings.StepResolve, "",
			"the twin was created from a record version this build no longer reads (twin.json 5); fylgja twin destroy clears it"),
			fill: func(h *stepHostFixture, f *findings.Finding) { f.Object = h.fromID }},
		// A diverged one is refused as diverged, towards the waypoint it was.
		{name: "a diverged record of twin.json 5", host: func(t *testing.T) *stepHostFixture {
			return supersededHost(t, map[string]any{"series": "steps", "sequence": 1,
				"description": "the mixed fixture as sealed", "at_source": "given"}, true)
		}, code: findings.ExitRejected, want: refusal(findings.RuleStepTwinDiverged, findings.StepResolve, "",
			"the twin is diverged: step run fylgja-step "+stepRunID+" towards a waypoint of a record version this build no "+
				"longer reads (twin.json 5) stopped at phase push (landed: s1; not landed: e1 (push.refused)); it accepts only "+
				"fylgja twin destroy"),
			fill: func(h *stepHostFixture, f *findings.Finding) { f.Object = h.fromID }},
		{name: "a diverged twin", host: divergedStepHost, code: findings.ExitRejected, want: divergedRefusal(""),
			fill: func(h *stepHostFixture, f *findings.Finding) { f.Object = h.fromID }},
		// A stage twin of a record of 7 or earlier names no scope (017): it is refused naming
		// its version, before its proposed change is asked for, as a 5's waypoint is.
		{name: "a record of twin.json 7", host: func(t *testing.T) *stepHostFixture { return unscopedHost(t, "7") },
			code: findings.ExitRejected, want: refusal(findings.RuleStepTwinUnsteppable, findings.StepResolve, "",
				"the twin was created from a record version this build no longer reads (twin.json 7); fylgja twin destroy clears it"),
			fill: func(h *stepHostFixture, f *findings.Finding) { f.Object = h.fromID }},
		{name: "a record of twin.json 6", host: func(t *testing.T) *stepHostFixture { return unscopedHost(t, "6") },
			code: findings.ExitRejected, want: refusal(findings.RuleStepTwinUnsteppable, findings.StepResolve, "",
				"the twin was created from a record version this build no longer reads (twin.json 6); fylgja twin destroy clears it"),
			fill: func(h *stepHostFixture, f *findings.Finding) { f.Object = h.fromID }},
		// An 8 whose scope is not tag:<name>, edited by hand, names no scope a read can be
		// made under: refused naming the value, as a 7 is, before Infrahub is asked (T097).
		{name: "a record of twin.json 8 naming scope \"\"", host: func(t *testing.T) *stepHostFixture { return misscopedHost(t, "") },
			code: findings.ExitRejected, want: refusal(findings.RuleStepTwinUnsteppable, findings.StepResolve, "", misscoped("")),
			fill: func(h *stepHostFixture, f *findings.Finding) { f.Object = h.fromID }},
		{name: "a record of twin.json 8 naming scope fylgja", host: func(t *testing.T) *stepHostFixture { return misscopedHost(t, "fylgja") },
			code: findings.ExitRejected, want: refusal(findings.RuleStepTwinUnsteppable, findings.StepResolve, "", misscoped("fylgja")),
			fill: func(h *stepHostFixture, f *findings.Finding) { f.Object = h.fromID }},
		{name: "a record of twin.json 8 naming scope tag:", host: func(t *testing.T) *stepHostFixture { return misscopedHost(t, "tag:") },
			code: findings.ExitRejected, want: refusal(findings.RuleStepTwinUnsteppable, findings.StepResolve, "", misscoped("tag:")),
			fill: func(h *stepHostFixture, f *findings.Finding) { f.Object = h.fromID }},
		// An 8 of scope tag:fylgja whose mapping 8 cannot hold, edited by hand: a step that
		// diverged would keep it in the record it writes, which NewStepRecord refuses, failing
		// the record activity with the nodes changed. Refused before Infrahub is asked, each
		// failing field named (T113).
		{name: "a record of twin.json 8 naming mapping reader Infrahub DCIM", host: func(t *testing.T) *stepHostFixture {
			return mismappedHost(t, map[string]string{"reader": "Infrahub DCIM"})
		}, code: findings.ExitRejected, want: refusal(findings.RuleStepTwinUnsteppable, findings.StepResolve, "",
			mismapped(`reader "Infrahub DCIM"`)),
			fill: func(h *stepHostFixture, f *findings.Finding) { f.Object = h.fromID }},
		{name: "a record of twin.json 8 naming an empty mapping model and version", host: func(t *testing.T) *stepHostFixture {
			return mismappedHost(t, map[string]string{"model": "", "version": ""})
		}, code: findings.ExitRejected, want: refusal(findings.RuleStepTwinUnsteppable, findings.StepResolve, "",
			mismapped(`model "", version ""`)),
			fill: func(h *stepHostFixture, f *findings.Finding) { f.Object = h.fromID }},
		{name: "a record of twin.json 8 naming mapping reader -dcim and an empty model", host: func(t *testing.T) *stepHostFixture {
			return mismappedHost(t, map[string]string{"reader": "-dcim", "model": ""})
		}, code: findings.ExitRejected, want: refusal(findings.RuleStepTwinUnsteppable, findings.StepResolve, "",
			mismapped(`reader "-dcim", model ""`)),
			fill: func(h *stepHostFixture, f *findings.Finding) { f.Object = h.fromID }},
		// A stage of any proposed change is a target (019, research R-07): one of a branch with
		// none open is refused as its resolution refuses it, naming the branches with one.
		{name: "another branch with no open proposed change", args: []string{"--stage", "other/x"}, code: findings.ExitRejected,
			asked: true, unread: true, want: refusal(findings.RuleStageUnknown, findings.StepResolve, "other",
				"no open proposed change has source branch other; the branches with one are: change-1")},
		{name: "the twin's proposed change no longer open", host: func(t *testing.T) *stepHostFixture {
			return stepHost(t, "plan-link-added.json", func(f *lab.RecordFields) { f.Stage.ProposedChange.ID = "pc-0" })
		}, code: findings.ExitRejected, asked: true, unread: true, want: refusal(findings.RuleStepTargetUnknown, findings.StepResolve, "change-1/sealed",
			"proposed change pc-0 on branch change-1, the twin's, is no longer open (the open proposed change on change-1 is pc-1), "+
				"so the twin has no next stage; give --stage <branch>/<label> or --snapshot <id|file>")},
		{name: "no open proposed change on the twin's branch", host: func(t *testing.T) *stepHostFixture {
			h := stepHost(t, "plan-link-added.json", nil)
			h.infra.changes[0].State = "merged"
			return h
		}, code: findings.ExitRejected, asked: true, unread: true, want: refusal(findings.RuleStageUnknown, findings.StepResolve, "change-1",
			"no open proposed change has source branch change-1; there is no open proposed change")},
		{name: "the twin's label gone", host: func(t *testing.T) *stepHostFixture {
			return stepHost(t, "plan-link-added.json", func(f *lab.RecordFields) { f.Stage.Label = "gone" })
		}, code: findings.ExitRejected, asked: true, unread: true, want: refusal(findings.RuleStepTargetUnknown, findings.StepResolve, "change-1/gone",
			"the twin's stage change-1/gone is no longer a stage of proposed change pc-1 on branch change-1; its stages are: "+stepStages)},
		// A twin at the head has no next, and the head it was built from has since moved.
		{name: "no next", host: func(t *testing.T) *stepHostFixture {
			return stepHost(t, "plan-link-added.json", func(f *lab.RecordFields) { f.Stage = stepStage("head", "", "head") })
		}, code: findings.ExitRejected, asked: true, unread: true, want: refusal(findings.RuleStepTargetUnknown, findings.StepResolve, "change-1/head",
			"proposed change pc-1 on change-1 has no stage after change-1/head; its stages are: "+stepStages+
				"; the head has moved since the twin was built (now at 2026-10-16T11:30:00.000001+00:00): --stage change-1/head steps to it")},
		{name: "a stage the proposed change lacks", args: []string{"--stage", "change-1/nosuch"}, code: findings.ExitRejected, asked: true, unread: true,
			want: refusal(findings.RuleStepTargetUnknown, findings.StepResolve, "change-1/nosuch",
				`proposed change pc-1 on change-1 has no stage "nosuch"; its stages are: `+stepStages)},
		{name: "the current one", args: []string{"--stage", "change-1/sealed"}, code: findings.ExitRejected, asked: true, unread: true,
			want: refusal(findings.RuleStepTargetCurrent, findings.StepResolve, "change-1/sealed",
				"the twin is already at stage change-1/sealed (branch change-1, at "+stepMixedAt+"); the proposed change's stages are: "+stepStages)},
		{name: "the kind absent", host: func(t *testing.T) *stepHostFixture {
			h := stepHost(t, "plan-link-added.json", nil)
			h.infra.kind = nil
			return h
		}, code: findings.ExitRejected, asked: true, unread: true, want: refusal(findings.RuleStageKindAbsent, findings.StepResolve, intent.StageKind, ""),
			fill: func(h *stepHostFixture, f *findings.Finding) { f.Message = "" }},
		{name: "a duplicate target", host: func(t *testing.T) *stepHostFixture {
			h := stepHost(t, "plan-link-added.json", nil)
			h.infra.changes[0].Stages = append(h.infra.changes[0].Stages,
				mark("st-twice-a", "twice", "2026-10-16T11:45:00Z", ""), mark("st-twice-b", "twice", "2026-10-16T11:50:00Z", ""))
			return h
		}, args: []string{"--stage", "change-1/twice"}, code: findings.ExitRejected, asked: true, unread: true,
			want: refusal(findings.RuleStageDuplicate, findings.StepResolve, "change-1/twice", "")},
		{name: "a target taking a reserved label", host: refusedTarget(func(h *stepHostFixture) {
			h.infra.changes[0].Stages = append(h.infra.changes[0].Stages, mark("st-head", "head", "2026-10-16T11:45:00Z", ""))
		}), args: []string{"--stage", "change-1/head"}, code: findings.ExitRejected, asked: true, unread: true,
			want: refusal(findings.RuleStageLabelReserved, findings.StepResolve, "change-1/head",
				`stage change-1/head is a mark labelled "head", which names the derived head of every proposed change and is `+
					"reserved; relabel it (schema/README.md); the head of change-1 is still its derived stage")},
		// A rebase moved the branch point past again's at, though not past the branch's
		// creation.
		{name: "a target before the branch point, after a rebase", host: refusedTarget(func(h *stepHostFixture) {
			h.infra.changes[0].BranchedFrom = "2026-10-16T11:15:00.000000+00:00"
		}), args: []string{"--stage", "change-1/again"}, code: findings.ExitRejected, asked: true, unread: true,
			want: refusal(findings.RuleStageAtBeforeBranchPoint, findings.StepResolve, "change-1/again",
				"stage change-1/again has at "+stepLaterAt+", before the branch point 2026-10-16T11:15:00.000000+00:00 of "+
					"change-1: a rebase at 2026-10-16T11:15:00.000000+00:00 moved the branch point past it (the branch was "+
					"created at "+fakeBranchedFrom+"); mark the stage again, or delete it")},
		// Its message names the server's clock, so its words are not compared.
		{name: "a target given an as_of later than now", host: refusedTarget(func(h *stepHostFixture) {
			h.infra.changes[0].Stages = append(h.infra.changes[0].Stages, mark("st-future", "future", "2099-01-01T00:00:00Z", ""))
		}), args: []string{"--stage", "change-1/future"}, code: findings.ExitRejected, asked: true, unread: true,
			want: refusal(findings.RuleStageAtUnresolved, findings.StepResolve, "change-1/future", "")},
		// The branch point reads main, none of whose devices is tagged here.
		{name: "a refused read", host: func(t *testing.T) *stepHostFixture {
			h := stepHost(t, "plan-link-added.json", nil)
			h.infra.untagged = map[string]bool{"main": true}
			return h
		}, args: []string{"--stage", "change-1/branch-point"}, code: findings.ExitRejected, asked: true,
			want: refusal(findings.RuleScopeEmpty, findings.StepRead, "", "")},
		{name: "a refused compile", host: func(t *testing.T) *stepHostFixture {
			h := stepHost(t, "plan-link-added.json", nil)
			toID := buildStage(t, h.paths, "linked")
			manifest := filepath.Join(h.paths.Bundles, toID, "manifest.json")
			if err := os.Chmod(manifest, 0o644); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(manifest, []byte("{}"), 0o644); err != nil {
				t.Fatal(err)
			}
			return h
		}, code: findings.ExitRejected, asked: true, want: refusal(findings.RuleBundleIDMismatch, findings.StepCompile, "", "")},
		{name: "the record's bundle not in the store", host: func(t *testing.T) *stepHostFixture {
			h := stepHost(t, "plan-link-added.json", nil)
			if err := os.RemoveAll(filepath.Join(h.paths.Bundles, h.fromID)); err != nil {
				t.Fatal(err)
			}
			return h
		}, code: findings.ExitRejected, asked: true, want: refusal(findings.RuleStepBundleMissing, findings.StepResolve, "", ""),
			fill: func(h *stepHostFixture, f *findings.Finding) {
				f.Object = h.fromID
				f.Message = "the record names bundle " + h.fromID + ", which the store under " + h.paths.Bundles +
					" does not hold; a step starts from the bundle the twin was built from and cannot be computed without it; " +
					"fylgja twin destroy and create again"
			}},
		// The store cannot say whether it holds the record's bundle: its entry is a link to
		// itself, which stat refuses for a reason other than absence.
		{name: "the store cannot inspect the record's bundle", host: func(t *testing.T) *stepHostFixture {
			h := stepHost(t, "plan-link-added.json", nil)
			dir := filepath.Join(h.paths.Bundles, h.fromID)
			if err := os.RemoveAll(dir); err != nil {
				t.Fatal(err)
			}
			if err := os.Symlink(dir, dir); err != nil {
				t.Fatal(err)
			}
			return h
		}, code: findings.ExitError, asked: true, want: refusal(findings.RuleOperationFailed, findings.StepResolve, "", ""),
			fill: func(h *stepHostFixture, f *findings.Finding) {
				_, err := bundle.NewDirStore(h.paths.Bundles).Has(context.Background(), h.fromID)
				f.Object = h.fromID
				f.Message = "reading bundle " + h.fromID + " from the store: " + fmt.Sprint(err)
			}},
		// The store holds the record's bundle, but its read refuses it: a symbolic link is no
		// part of a bundle's id, and a bundle holds regular files only.
		{name: "the record's bundle cannot be read from the store", host: func(t *testing.T) *stepHostFixture {
			h := stepHost(t, "plan-link-added.json", nil)
			if err := os.Symlink("manifest.json", filepath.Join(h.paths.Bundles, h.fromID, "manifest.link")); err != nil {
				t.Fatal(err)
			}
			return h
		}, code: findings.ExitError, asked: true, want: refusal(findings.RuleOperationFailed, findings.StepResolve, "", ""),
			fill: func(h *stepHostFixture, f *findings.Finding) {
				_, err := bundle.LoadFiles(filepath.Join(h.paths.Bundles, h.fromID))
				f.Object = h.fromID
				f.Message = "reading bundle " + h.fromID + " from the store: " + fmt.Sprint(err)
			}},
		{name: "the host's memory", host: func(t *testing.T) *stepHostFixture {
			h := stepHost(t, "plan-link-added.json", nil)
			t.Setenv(lab.EnvHostMemoryMB, "4096")
			return h
		}, args: []string{"--allow-restart"}, code: findings.ExitRejected, asked: true,
			want: refusal(findings.RuleHostMemoryExceeded, findings.StepHostCheck, "", "")},
		{name: "the host check cannot run", host: func(t *testing.T) *stepHostFixture {
			h := stepHost(t, "plan-link-added.json", nil)
			t.Setenv(lab.EnvHostMemoryMB, "lots")
			return h
		}, code: findings.ExitError, asked: true, want: refusal(findings.RuleOperationFailed, findings.StepHostCheck,
			findings.StepHostCheck, "host check: "+lab.EnvHostMemoryMB+` must be a positive whole number of MiB, got "lots"`)},
		{name: "a merge package", host: func(t *testing.T) *stepHostFixture {
			h := stepHost(t, "plan-link-added.json", nil)
			t.Setenv("FYLGJA_PSP_DIR", overridePackage(t, "nokia_srlinux", "mode: replace", "mode: merge"))
			return h
		}, args: []string{"--allow-restart"}, code: findings.ExitRejected, asked: true,
			want: refusal(findings.RuleStepPackageMerge, findings.StepCompare, "nokia_srlinux",
				"support package nokia_srlinux pushes by merge, which a step cannot use: a step removes what the previous "+
					"artifact added, and only a replace does that; nodes s1; a create from it is unaffected")},
		{name: "a merge package the target no longer runs on every node", host: func(t *testing.T) *stepHostFixture {
			h := stepHost(t, "plan-link-added.json", nil)
			t.Setenv("FYLGJA_PSP_DIR", overridePackage(t, "arista_eos", "mode: replace", "mode: merge"))
			return h
		}, args: []string{"--stage", "change-1/less", "--allow-restart"}, code: findings.ExitRejected, asked: true,
			want: refusal(findings.RuleStepPackageMerge, findings.StepCompare, "arista_eos",
				"support package arista_eos pushes by merge, which a step cannot use: a step removes what the previous "+
					"artifact added, and only a replace does that; nodes e1, e2; a create from it is unaffected")},
		{name: "a change containerlab would not apply", host: func(t *testing.T) *stepHostFixture {
			h := stepHost(t, "plan-link-added.json", nil)
			t.Setenv("FYLGJA_PSP_DIR", overridePackage(t, "nokia_srlinux", "ref: ghcr.io/nokia/srlinux:24.7.1", "ref: ghcr.io/nokia/srlinux:24.7.2"))
			return h
		}, args: []string{"--allow-restart"}, code: findings.ExitRejected, asked: true,
			want: refusal(findings.RuleStepNodeUnapplied, findings.StepCompare, "s1",
				"node s1 changes in image between the two bundles, but containerlab's reconcile would not recreate it "+
					"(its plan: live); the running node would keep its image; a step cannot apply it")},
		{name: "a restart without the flag", code: findings.ExitRejected, asked: true, want: restartRequired},
		{name: "--stage=", args: []string{"--stage="}, code: findings.ExitError,
			want: refusal(findings.RuleStageRefInvalid, findings.StepStart, "", stageRefInvalid(""))},
	} {
		t.Run(c.name, func(t *testing.T) {
			host := c.host
			if host == nil {
				host = func(t *testing.T) *stepHostFixture { return stepHost(t, "plan-link-added.json", nil) }
			}
			h := host(t)
			if c.name == "--stage=" {
				h.clab.calls = nil
			}
			want := c.want
			if c.fill != nil {
				c.fill(h, &want)
			}
			out := runStepCmd(t, c.args...)
			got := refusalOf(t, out.doc)
			if want.Message == "" {
				want.Message = got.Message
			}
			if want.Object == "" && got.Object != "" && c.fill == nil {
				want.Object = got.Object
			}
			if out.code != c.code || got != want {
				t.Errorf("exit %d, refusal %+v\nwant exit %d, %+v", out.code, got, c.code, want)
			}
			noContent(t, "the refusal", out.stdout, out.stderr)
			if asked := len(h.infra.requests()) > h.before; asked != c.asked {
				t.Errorf("Infrahub asked after the host was built: %v, want %v", asked, c.asked)
			}
			if read := intentReadAfter(h.infra, h.before); (!c.asked || c.unread) && len(read) != 0 {
				t.Errorf("a branch's intent was read for a target refused before its read: %+v", read)
			}
			if c.name == "--stage=" && len(h.clab.calls) != 0 {
				t.Errorf("containerlab was asked %v before the flag was refused", h.clab.calls)
			}
			if plans := h.clab.asked("clab", "deploy"); got.Step != findings.StepCompare && len(plans) != 0 {
				t.Errorf("a refusal at %s read containerlab's plan %v", got.Step, plans)
			}
		})
	}
}

// A target whose read cannot run, and a target whose at carries more fractional digits than
// Infrahub honours, end the command as a create ends them for a stage: exit 2, status error,
// not a refusal's 1 (contracts/cli.md's resolution row). Nothing of the
// step is computed: containerlab's plan is never read and no service is dialled.
func TestStepTargetErrorsExitTwo(t *testing.T) {
	for _, c := range []struct {
		name string
		args []string
		host func(h *stepHostFixture)
		want findings.Finding // its message "" is not compared
		// unread is a target refused before its read: no branch's intent is asked.
		unread bool
	}{
		{name: "the target's read cannot run",
			host: func(h *stepHostFixture) { h.infra.readStatus = map[string]int{"change-1": 500} },
			want: findings.Finding{Severity: findings.Rejection, Rule: findings.RuleOperationFailed, Step: findings.StepRead, Object: "change-1/linked"}},
		{name: "the target's at carries nine fractional digits", args: []string{"--stage", "change-1/nine"},
			host: func(h *stepHostFixture) {
				h.infra.changes[0].Stages = append(h.infra.changes[0].Stages, mark("st-nine", "nine", "2026-10-16T09:45:00.123456789Z", ""))
			},
			want: findings.Finding{Severity: findings.Rejection, Rule: findings.RuleAtPrecision, Step: findings.StepResolve, Object: "change-1/nine",
				Message: "stage change-1/nine: at 2026-10-16T09:45:00.123456789Z carries 9 fractional digits; Infrahub honours at most 6 " +
					"(microseconds). Write the stage's as_of with at most six."},
			unread: true},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := stepHost(t, "plan-link-added.json", nil)
			c.host(h)
			out := runStepCmd(t, c.args...)
			if out.code != findings.ExitError || out.doc.Status != findings.StatusError {
				t.Errorf("exit %d, status %s; want 2, error; findings %+v", out.code, out.doc.Status, out.doc.Findings)
			}
			got := refusalOf(t, out.doc)
			if c.want.Message == "" {
				c.want.Message = got.Message
			}
			if got != c.want {
				t.Errorf("finding %+v\nwant %+v", got, c.want)
			}
			if plans := h.clab.asked("clab", "deploy"); len(plans) != 0 {
				t.Errorf("containerlab's plan was read %v for a target that did not compile", plans)
			}
			if read := intentReadAfter(h.infra, h.before); c.unread && len(read) != 0 {
				t.Errorf("a branch's intent was read for a target refused before its read: %+v", read)
			}
			noContent(t, "the error", out.stdout, out.stderr)
		})
	}
}

// overridePackage is a --psp-dir holding the shipped package id with old replaced by new.
func overridePackage(t *testing.T, id, old, new string) string {
	t.Helper()
	b, err := os.ReadFile(repoPath("psp", id+".yaml"))
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(b), old) {
		t.Fatalf("psp/%s.yaml does not say %q", id, old)
	}
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, id+".yaml"), []byte(strings.Replace(string(b), old, new, 1)), 0o644); err != nil {
		t.Fatal(err)
	}
	return dir
}

// --branch, --at, --interval and --no-follow are not flags of twin step, and neither is 017's
// --scope, since a step reads under its record's: flag parsing refuses each, exit 2, before
// anything is read.
func TestStepTakesNoBranchFlags(t *testing.T) {
	for _, flag := range []string{"--branch=x", "--at=x", "--interval=1m", "--no-follow", "--scope=tag:fylgja"} {
		t.Run(flag, func(t *testing.T) {
			h := stepHost(t, "plan-link-added.json", nil)
			h.clab.calls = nil
			// Flag parsing stops at the unknown flag, so the refusal is text, as for every
			// command (cobra).
			opts := &options{}
			root := &cobra.Command{Use: "fylgja", SilenceUsage: true, SilenceErrors: true}
			root.AddCommand(newTwinCmd(opts))
			root.SetArgs([]string{"twin", "step", flag})
			var code int
			stderr := captureStderr(t, func() {
				captureStdout(t, func() {
					cmd, err := root.ExecuteC()
					code = report(opts, cmd, err)
				})
			})
			name, _, _ := strings.Cut(flag, "=")
			if code != findings.ExitError || !strings.Contains(stderr, "rejection operation.failed twin.step: unknown flag: "+name) {
				t.Errorf("exit %d, stderr %q; want 2, unknown flag %s", code, stderr, name)
			}
			if len(h.clab.calls) != 0 || len(h.infra.requests()) > h.before {
				t.Errorf("something was read before the flag was refused")
			}
		})
	}
}

// The step reads under the scope its twin records, never the server's default (017;
// FR-020; US1 scenario 7): with the server's default tag:other, a twin recorded under
// tag:fylgja finds its target, resolves it and reads its devices by the tag fylgja, and its
// document names that scope; beside the default tag:fylgja, a twin recorded under tag:other
// reads by the tag other, which no device of the fake carries, and its target is refused
// scope.empty naming tag:other.
func TestStepReadsUnderTheRecordsScope(t *testing.T) {
	for _, c := range []struct {
		name, server, record, tag string
		code                      int
	}{
		{"the record's tag:fylgja beside the default tag:other", "tag:other", "tag:fylgja", "fylgja", findings.ExitOK},
		{"the record's tag:other beside the default tag:fylgja", "tag:fylgja", "tag:other", "other", findings.ExitRejected},
	} {
		t.Run(c.name, func(t *testing.T) {
			saved := defaultScope
			t.Cleanup(func() { defaultScope = saved })
			defaultScope = c.server
			h := stepHost(t, "plan-link-added.json", func(f *lab.RecordFields) { f.Provenance.Scope = c.record })
			out := runStepCmd(t, "--dry-run", "--allow-restart")
			if out.code != c.code || out.doc.Subject == nil || out.doc.Subject.Scope != c.record {
				t.Fatalf("exit %d, subject %+v, findings %+v; want %d under %s", out.code, out.doc.Subject, out.doc.Findings, c.code, c.record)
			}
			var tags []any
			for _, r := range h.infra.requests()[h.before:] {
				if r.Operation == "Devices" {
					tags = append(tags, r.Variables["tag"])
				}
			}
			if len(tags) == 0 || slices.ContainsFunc(tags, func(tag any) bool { return tag != c.tag }) {
				t.Errorf("the step's device reads sent the tags %v; want %q on every one", tags, c.tag)
			}
			if c.code == findings.ExitOK {
				return
			}
			empty := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleScopeEmpty, Object: c.record,
				Step: findings.StepRead, Message: "scope " + c.record + " selects no device on branch change-1 at " + stepWrittenAt}
			if !slices.Contains(out.doc.Findings, empty) {
				t.Errorf("findings %+v; want %+v", out.doc.Findings, empty)
			}
		})
	}
}

// A step run in flight, or a provisioning or destroy run, refuses the start with M2's
// run.in_flight naming the run: the service is asked once and nothing starts.
func TestStepRefusedBesideARunInFlight(t *testing.T) {
	for _, c := range []struct{ workflowID, message string }{
		{provision.WorkflowProvision, "provisioning run 01a1 is already in flight; wait for it to finish, or run fylgja twin destroy to cancel it"},
		{provision.WorkflowDestroy, "destroy run 01a1 is already in flight; wait for it to finish"},
		{provision.WorkflowStep, "step run 01a1 is already in flight; wait for it to finish, or run fylgja twin destroy to cancel it"},
	} {
		t.Run(c.workflowID, func(t *testing.T) {
			stepHost(t, "plan-link-added.json", nil)
			want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleRunInFlight, Object: c.workflowID,
				Step: findings.StepStart, Message: c.message}
			svc := &fakeService{startErr: &provision.StartError{Status: findings.StatusRejected, Finding: want}}
			useService(t, svc)
			useInterrupts(t)
			out := runStepCmd(t, "--allow-restart")
			if got := refusalOf(t, out.doc); out.code != findings.ExitRejected || got != want {
				t.Errorf("exit %d, %+v; want 1, %+v", out.code, got, want)
			}
			if !slices.Equal(svc.calls, []string{"StartStep", "StartStep"}) {
				t.Errorf("the service was asked %v; want StartStep once per run of the command", svc.calls)
			}
		})
	}
}

// stepEvents are the step run's progress as the client reports it.
func stepEvents() []provision.Event {
	done := func(step string, d time.Duration, detail string) provision.Event {
		return provision.Event{WorkflowID: provision.WorkflowStep, Step: step, End: true, Outcome: provision.EventDone,
			Duration: d, Detail: detail}
	}
	return []provision.Event{
		done("inspect", 100*time.Millisecond, ""),
		done("host check", 300*time.Millisecond, ""),
		done("plan reconcile", 500*time.Millisecond, "restart e1"),
		done("stage", 200*time.Millisecond, ""),
		done("reconcile", 3900*time.Millisecond, "3 nodes"),
		done("readiness e1", 54800*time.Millisecond, ""),
		done("push e1", 1600*time.Millisecond, ""),
		done("push s1", 2400*time.Millisecond, ""),
		done("record", 100*time.Millisecond, ""),
	}
}

// unchangedStepEvents are an unchanged step run's progress as the client reports it: the
// run stages the target and records it, and reconciles, awaits and pushes nothing.
func unchangedStepEvents() []provision.Event {
	var out []provision.Event
	for _, e := range stepEvents() {
		switch {
		case e.Step == "plan reconcile":
			e.Detail = "nothing to apply"
		case e.Step == "reconcile" || strings.HasPrefix(e.Step, "readiness ") || strings.HasPrefix(e.Step, "push "):
			continue
		}
		out = append(out, e)
	}
	return out
}

// The run: a step the fake service replays as stepped, unchanged, diverged, and cancelled
// before and after its stage prints its progress and its closing line word for word, and
// exits as its status says. The unchanged run replays its own events, and prints no
// reconcile, readiness or push line. The run's input carries what the command decided and no
// content, the document validates against this feature's contracts, the run's repeats of
// the command's warnings are dropped, and no output quotes configuration.
func TestStepRuns(t *testing.T) {
	reconcile := 3.9
	pushed := func(e1Outcome, e1Rule string) []wire.StepPush {
		e1Took, s1Took := 1.6, 2.4
		return []wire.StepPush{
			{Node: "e1", Reasons: []string{"artifact", "restarted"}, Outcome: e1Outcome, Rule: e1Rule, TookS: &e1Took},
			{Node: "s1", Reasons: []string{"artifact", "bootstrap"}, Outcome: wire.PushLanded, TookS: &s1Took},
		}
	}
	timings := wire.StepTimings{ReconcileS: &reconcile, Readiness: map[string]float64{"e1": 54.8},
		Push: map[string]float64{"e1": 1.6, "s1": 2.4}, WholeS: 71.2}
	diverged := func(phase string) findings.Finding {
		return findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepDiverged, Object: stepRunID, Step: phase,
			Message: "step run " + stepRunID + " towards stage change-1/linked stopped at phase " + phase + "; …"}
	}
	for _, c := range []struct {
		name    string
		args    []string
		plan    string
		res     provision.StepResult
		code    int
		status  findings.Status
		closing func(fromID, toID string) string
		// events are the run's progress the fake service replays; nil is stepEvents().
		events []provision.Event
	}{
		{name: "stepped", args: []string{"--allow-restart"}, plan: "plan-link-added.json",
			res: provision.StepResult{Outcome: provision.StepStepped, PushPlan: pushed(wire.PushLanded, ""), Timings: timings,
				Record: &wire.TwinRecord{State: wire.StateReady}},
			code: findings.ExitOK, status: findings.StatusOK,
			closing: func(_, toID string) string {
				return "stepped to stage change-1/linked (bundle " + short(toID) + ") in 71.2s: reconcile 3.9s; readiness e1 54.8s; push e1 1.6s, s1 2.4s"
			}},
		{name: "unchanged", args: []string{"--stage", "change-1/again"}, plan: "plan-nothing.json",
			res: provision.StepResult{Outcome: provision.StepUnchanged, PushPlan: []wire.StepPush{},
				Timings: wire.StepTimings{WholeS: 1.8}, Record: &wire.TwinRecord{State: wire.StateReady}},
			code: findings.ExitOK, status: findings.StatusOK,
			closing: func(_, toID string) string {
				return "unchanged; the record moves to stage change-1/again (bundle " + short(toID) + ") in 1.8s"
			}, events: unchangedStepEvents()},
		{name: "diverged at push", args: []string{"--allow-restart"}, plan: "plan-link-added.json",
			res: provision.StepResult{Outcome: provision.StepDiverged, Phase: findings.StepPush, Step: findings.StepPush,
				PushPlan: pushed(wire.PushRefused, findings.RulePushRefused), Timings: timings,
				Record: &wire.TwinRecord{State: wire.StateDiverged},
				Findings: findings.List{
					{Severity: findings.Rejection, Rule: findings.RulePushRefused, Object: "e1", Step: findings.StepPush,
						Message: "node e1 refused artifact device-config (checksum cbc8c75d…) at line 7: Invalid input"},
					diverged(findings.StepPush)}},
			code: findings.ExitUnclean, status: findings.StatusDiverged,
			closing: func(fromID, toID string) string {
				return "diverged towards stage change-1/linked (bundle " + short(toID) + ") at phase push: landed s1; not landed e1 (push.refused); " +
					"the twin is up at stage change-1/sealed (bundle " + short(fromID) + "); fylgja twin destroy clears it"
			}},
		// The wait's clause follows M11's line on an unchanged and a diverged result too, as
		// contracts/cli.md quotes them.
		{name: "unchanged, the wait settled", args: []string{"--stage", "change-1/again"}, plan: "plan-nothing.json",
			res: provision.StepResult{Outcome: provision.StepUnchanged, PushPlan: []wire.StepPush{},
				Timings: wire.StepTimings{WholeS: 1.8}, Record: &wire.TwinRecord{State: wire.StateReady},
				Wait: &wire.StepWait{Outcome: wire.WaitSettled, BudgetS: 120, Reads: 1, AfterS: 1.1, Failing: []wire.StepFinding{}}},
			code: findings.ExitOK, status: findings.StatusOK,
			closing: func(_, toID string) string {
				return "unchanged; the record moves to stage change-1/again (bundle " + short(toID) + ") in 1.8s; settled after 1.1s"
			}, events: unchangedStepEvents()},
		{name: "diverged at push, the wait settled", args: []string{"--allow-restart"}, plan: "plan-link-added.json",
			res: provision.StepResult{Outcome: provision.StepDiverged, Phase: findings.StepPush, Step: findings.StepPush,
				PushPlan: pushed(wire.PushRefused, findings.RulePushRefused), Timings: timings,
				Record: &wire.TwinRecord{State: wire.StateDiverged},
				Wait:   &wire.StepWait{Outcome: wire.WaitSettled, BudgetS: 120, Reads: 2, AfterS: 1.9, Failing: []wire.StepFinding{}},
				Findings: findings.List{
					{Severity: findings.Rejection, Rule: findings.RulePushRefused, Object: "e1", Step: findings.StepPush,
						Message: "node e1 refused artifact device-config (checksum cbc8c75d…) at line 7: Invalid input"},
					diverged(findings.StepPush)}},
			code: findings.ExitUnclean, status: findings.StatusDiverged,
			closing: func(fromID, toID string) string {
				return "diverged towards stage change-1/linked (bundle " + short(toID) + ") at phase push: landed s1; not landed e1 (push.refused); " +
					"the twin is up at stage change-1/sealed (bundle " + short(fromID) + "); fylgja twin destroy clears it; settled after 1.9s"
			}},
		{name: "cancelled before the stage", args: []string{"--allow-restart"}, plan: "plan-link-added.json",
			res: provision.StepResult{Outcome: provision.OutcomeCancelled, Step: findings.StepCompare,
				Findings: findings.List{{Severity: findings.Rejection, Rule: findings.RuleRunCancelled, Object: stepRunID,
					Step: findings.StepCompare, Message: "run " + stepRunID + " was cancelled at step compare, before the host was touched; " +
						"nothing on the host was touched and the record is unchanged"}}},
			code: findings.ExitError, status: findings.StatusError,
			closing: func(string, string) string { return "" }},
		{name: "cancelled after the stage", args: []string{"--allow-restart"}, plan: "plan-link-added.json",
			res: provision.StepResult{Outcome: provision.OutcomeCancelled, Phase: findings.StepReadiness, Step: findings.StepReadiness,
				PushPlan: []wire.StepPush{{Node: "e1", Reasons: []string{"artifact", "restarted"}, Outcome: wire.PushNotAttempted},
					{Node: "s1", Reasons: []string{"artifact", "bootstrap"}, Outcome: wire.PushNotAttempted}},
				Record: &wire.TwinRecord{State: wire.StateDiverged},
				Findings: findings.List{
					{Severity: findings.Rejection, Rule: findings.RuleRunCancelled, Object: stepRunID, Step: findings.StepReadiness,
						Message: "run " + stepRunID + " was cancelled at step readiness; the record was written diverged and nothing was torn down"},
					diverged(findings.StepReadiness)}},
			code: findings.ExitUnclean, status: findings.StatusDiverged,
			closing: func(fromID, toID string) string {
				return "diverged towards stage change-1/linked (bundle " + short(toID) + ") at phase readiness: landed none; not landed e1, s1; " +
					"the twin is up at stage change-1/sealed (bundle " + short(fromID) + "); fylgja twin destroy clears it"
			}},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := stepHost(t, c.plan, nil)
			unbudgeted := findings.Finding{}
			res := c.res
			res.StartedAt, res.EndedAt = "2026-10-02T09:14:30Z", "2026-10-02T09:15:41Z"
			if res.Findings == nil {
				res.Findings = findings.List{}
			}
			events := c.events
			if events == nil {
				events = stepEvents()
			}
			svc := &fakeService{runID: stepRunID, events: events}
			useService(t, svc)
			useInterrupts(t)
			svc.stepResult = res
			// The run repeats the command's host-check warning, which the document keeps once.
			first := runStepCmd(t, append(c.args, "--dry-run")...)
			for _, f := range first.doc.Findings {
				if f.Rule == findings.RuleHostMemoryUnbudgeted {
					unbudgeted = f
				}
			}
			svc.stepResult.Findings = append(findings.List{unbudgeted}, res.Findings...)

			began := time.Now().UTC().Truncate(time.Microsecond)
			out := runStepCmd(t, c.args...)
			toID := out.doc.BundleID
			if out.code != c.code || out.doc.Status != c.status {
				t.Fatalf("exit %d, status %s; want %d, %s; findings %+v", out.code, out.doc.Status, c.code, c.status, out.doc.Findings)
			}
			wantTail := []string{"run fylgja-step " + stepRunID,
				"step inspect: done in 0.1s",
				"step host check: done in 0.3s",
				"step plan reconcile: done in 0.5s (restart e1)",
				"step stage: done in 0.2s",
				"step reconcile: done in 3.9s (3 nodes)",
				"step readiness e1: ready in 54.8s",
				"step push e1: done in 1.6s",
				"step push s1: done in 2.4s",
				"step record: done in 0.1s",
			}
			unchanged := strings.HasPrefix(c.name, "unchanged")
			if unchanged {
				wantTail = []string{"run fylgja-step " + stepRunID,
					"step inspect: done in 0.1s",
					"step host check: done in 0.3s",
					"step plan reconcile: done in 0.5s (nothing to apply)",
					"step stage: done in 0.2s",
					"step record: done in 0.1s",
				}
				for _, line := range []string{"step reconcile", "step readiness", "step push"} {
					if strings.Contains(out.stdout, line) {
						t.Errorf("an unchanged run printed %q:\n%s", line, out.stdout)
					}
				}
			}
			if closing := c.closing(h.fromID, toID); closing != "" {
				wantTail = append(wantTail, closing)
			}
			if !strings.HasSuffix(out.stdout, "\n"+strings.Join(wantTail, "\n")+"\n") {
				t.Errorf("stdout:\n%s\nwant it to end:\n%s", out.stdout, strings.Join(wantTail, "\n"))
			}
			if strings.Contains(out.stdout, "dry run") || strings.Contains(out.stdout, "verdict:") {
				t.Errorf("a run printed the dry run's lines:\n%s", out.stdout)
			}
			n := 0
			for _, f := range out.doc.Findings {
				if f == unbudgeted {
					n++
				}
			}
			if n != 1 {
				t.Errorf("findings %+v carry the unbudgeted warning %d times, want once", out.doc.Findings, n)
			}
			for _, f := range res.Findings {
				if !slices.Contains(out.doc.Findings, f) {
					t.Errorf("findings %+v lack the run's %+v", out.doc.Findings, f)
				}
			}
			st := out.doc.Step
			if st == nil || st.StepRunBlock == nil || st.Run.RunID != stepRunID || out.doc.Subject.RunID != stepRunID {
				t.Errorf("step block %+v, subject %+v; want the run named", st, out.doc.Subject)
			}

			// The run's input: two runs of the command, each starting the run once.
			if len(svc.stepped) != 2 {
				t.Fatalf("the service started %d runs, want one per run of the command", len(svc.stepped))
			}
			in := svc.stepped[0]
			if in.From.BundleID != h.fromID || in.To.BundleID != toID || in.ToBundlePath != filepath.Join(h.paths.Bundles, toID) ||
				in.ObservedAt == "" || in.Unchanged != unchanged || in.AllowRestart != slices.Contains(c.args, "--allow-restart") ||
				in.From.Stage == nil || in.From.Stage.Label != "sealed" || in.To.Stage == nil || len(in.Diff) == 0 ||
				in.Declared["e1"] != "restart" || in.Declared["s1"] != "live" || in.Version != version {
				t.Errorf("the run's input %+v does not carry what the command decided", in)
			}
			if wantPush := 2; unchanged {
				if len(in.PushPlan) != 0 {
					t.Errorf("an unchanged step's push plan %+v; want nobody", in.PushPlan)
				}
			} else if len(in.PushPlan) != wantPush {
				t.Errorf("push plan %+v; want e1 and s1", in.PushPlan)
			}

			// Both sides whole, as the record and the resolved target give them, which the
			// step's record names; containerlab's plan as
			// its recording reads; and the target read's own observed_at, which the record takes
			// once the step moves the twin.
			// Each side names its snapshot (018): the record's, and the one the target's build
			// took, which the document names beside the target's bundle.
			wantFrom := wire.StepSide{Stage: stepStage("sealed", "the mixed fixture as sealed", "given"), SnapshotID: h.fromSnapshot,
				BundleID: h.fromID, At: stepMixedAt}
			toSnapshot := out.doc.SnapshotID
			if !snap.IsID(toSnapshot) || toSnapshot == h.fromSnapshot || !slices.Contains(filedSnapshots(t, h.paths), toSnapshot+".json") {
				t.Errorf("the document names snapshot %q; want the target's, filed in the store", toSnapshot)
			}
			wantTo := wire.StepSide{Stage: stepStage("linked", "a link between e1 and s1", "written"), SnapshotID: toSnapshot,
				BundleID: toID, At: stepWrittenAt, Branch: "change-1"}
			wantPlan := wire.ReconcilePlan{Restarted: []string{"e1"}, LinksAdded: []string{"e1:eth2 -- s1:e1-2"},
				Reasons: map[string]string{"e1": "added link"}}
			if unchanged {
				wantTo = wire.StepSide{Stage: stepStage("again", "the fixture again", "given"), SnapshotID: toSnapshot, BundleID: toID,
					At: stepLaterAt, Branch: "change-1"}
				wantPlan = wire.ReconcilePlan{}
			}
			asJSON := func(v any) string {
				b, _ := json.Marshal(v)
				return string(b)
			}
			for i, got := range svc.stepped {
				if !reflect.DeepEqual(got.From, wantFrom) || !reflect.DeepEqual(got.To, wantTo) {
					t.Errorf("run %d's sides %s → %s\nwant %s → %s", i, asJSON(got.From), asJSON(got.To), asJSON(wantFrom), asJSON(wantTo))
				}
				if !samePlan(got.Plan, wantPlan) {
					t.Errorf("run %d's plan %s; want %s, as containerlab's plan reads", i, asJSON(got.Plan), asJSON(wantPlan))
				}
			}
			// Each run's observed_at is its own command's read's time: within the commands'
			// span, the second's no earlier than the first's. The store kept the read beside
			// the bundle until 018 retired the sidecar.
			ended := time.Now().UTC()
			firstAt, lastAt := svc.stepped[0].ObservedAt, svc.stepped[1].ObservedAt
			if at, err := time.Parse(intentstage.ObservedAtFormat, lastAt); err != nil || at.After(ended) || firstAt > lastAt {
				t.Errorf("the second run's observed_at %q; want a read's time from the first run's %s to %s", lastAt, firstAt,
					ended.Format(intentstage.ObservedAtFormat))
			}
			if at, err := time.Parse(intentstage.ObservedAtFormat, firstAt); err != nil || at.Before(began) || firstAt > lastAt {
				t.Errorf("the first run's observed_at %q; want a read's time from %s to %s", firstAt, began.Format(intentstage.ObservedAtFormat), lastAt)
			}

			raw, err := json.Marshal(in)
			if err != nil {
				t.Fatal(err)
			}
			doc, err := json.Marshal(out.doc)
			if err != nil {
				t.Fatal(err)
			}
			noContent(t, "the run", out.stdout, out.stderr, string(raw), string(doc))
		})
	}
}

// No service and no worker are exit 2 at step start under their own identifiers, as for a
// create, and a dial that fails under no identifier of its own is
// operation.failed at start, as a start that fails is: nothing is started, and the subject
// names no run (contracts/cli.md).
func TestStepStartRefusals(t *testing.T) {
	dialFailed := errors.New("the workflow service's client could not be built")
	refusals := append(startRefusals(), startRefusal{"the dial fails", findings.RuleOperationFailed, func(t *testing.T) {
		saved := dialService
		t.Cleanup(func() { dialService = saved })
		dialService = func(context.Context) (provision.Service, error) { return nil, dialFailed }
	}})
	for _, c := range refusals {
		t.Run(c.name, func(t *testing.T) {
			stepHost(t, "plan-link-added.json", nil)
			useInterrupts(t)
			c.use(t)
			out := runStepCmd(t, "--allow-restart")
			got := refusalOf(t, out.doc)
			if out.code != findings.ExitError || out.doc.Status != findings.StatusError || got.Rule != c.rule ||
				got.Step != findings.StepStart {
				t.Errorf("exit %d, status %s, %+v; want 2, error, %s at step start", out.code, out.doc.Status, got, c.rule)
			}
			if want := (findings.Finding{Severity: findings.Rejection, Rule: findings.RuleOperationFailed, Object: findings.StepStart,
				Step: findings.StepStart, Message: dialFailed.Error()}); c.rule == findings.RuleOperationFailed && got != want {
				t.Errorf("finding %+v\nwant %+v", got, want)
			}
			if sub := out.doc.Subject; sub != nil && sub.RunID != "" {
				t.Errorf("subject names run %q, but no run was started", sub.RunID)
			}
		})
	}
}

// An interrupt during the step run is answered as a provisioning run's is, its
// record standing for the cleanup ("cancelled … by twin destroy or otherwise";
// contracts/cli.md): the first asks the run to cancel and says the command waits for its
// record, and the command then ends as the run closes; a second stops waiting, run.cancelled
// at the step the run had reached; and one that arrives before the start has returned
// abandons the start, which started nothing, or is the first when the start succeeded.
// Each command is bounded, so a signal nothing answers fails the test rather than
// hanging it.
func TestStepInterrupt(t *testing.T) {
	cancelled := func(step, message string) findings.Finding {
		return findings.Finding{Severity: findings.Rejection, Rule: findings.RuleRunCancelled, Object: stepRunID, Step: step,
			Message: message}
	}
	// What the run closes as once cancelled: diverged during its readiness, or before its stage.
	diverged := provision.StepResult{Outcome: provision.OutcomeCancelled, Phase: findings.StepReadiness, Step: findings.StepReadiness,
		PushPlan: []wire.StepPush{{Node: "e1", Reasons: []string{"artifact", "restarted"}, Outcome: wire.PushNotAttempted},
			{Node: "s1", Reasons: []string{"artifact", "bootstrap"}, Outcome: wire.PushNotAttempted}},
		Record: &wire.TwinRecord{State: wire.StateDiverged}, StartedAt: "2026-10-02T09:14:30Z", EndedAt: "2026-10-02T09:15:41Z",
		Findings: findings.List{
			cancelled(findings.StepReadiness, "run "+stepRunID+" was cancelled at step readiness; the record was written diverged and nothing was torn down"),
			{Severity: findings.Rejection, Rule: findings.RuleStepDiverged, Object: stepRunID, Step: findings.StepReadiness,
				Message: "step run " + stepRunID + " towards stage change-1/linked stopped at phase readiness; …"}}}
	beforeStage := provision.StepResult{Outcome: provision.OutcomeCancelled, Step: findings.StepInspect,
		StartedAt: "2026-10-02T09:14:30Z", EndedAt: "2026-10-02T09:14:31Z",
		Findings: findings.List{cancelled(findings.StepInspect, "run "+stepRunID+" was cancelled at step inspect, before the host "+
			"was touched; nothing on the host was touched and the record is unchanged")}}
	// The run has reached its readiness when the signal comes.
	events := []provision.Event{{WorkflowID: provision.WorkflowStep, Step: "readiness e1", FindingStep: findings.StepReadiness}}
	const waiting = "run cancelled; waiting for its record"

	// runInterrupted runs the step in text, where the operator reads the line, against svc.
	runInterrupted := func(t *testing.T, svc *fakeService) (string, int, *findings.Document) {
		t.Helper()
		useService(t, svc)
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		var err error
		stdout := captureStdout(t, func() { err = runTwinStep(ctx, &options{}, &stepFlags{allowRestart: true}) })
		code, doc := exitOf(t, err)
		validateM10Document(t, doc)
		noContent(t, "the interrupted step", stdout)
		return stdout, code, doc
	}

	t.Run("the first cancels the run and waits for its record", func(t *testing.T) {
		h := stepHost(t, "plan-link-added.json", nil)
		interrupts := useInterrupts(t)
		release := make(chan struct{})
		svc := &fakeService{runID: stepRunID, events: events, release: release, stepResult: diverged}
		svc.onCancel = func() { close(release) }
		svc.afterFollow = func() { interrupts <- os.Interrupt }
		stdout, code, doc := runInterrupted(t, svc)
		if svc.cancels != 1 {
			t.Errorf("Cancel called %d times, want once", svc.cancels)
		}
		if code != findings.ExitUnclean || doc.Status != findings.StatusDiverged {
			t.Fatalf("exit %d, status %s; want 4, diverged, as the run closed; findings %+v", code, doc.Status, doc.Findings)
		}
		if doc.Step == nil || doc.Step.Wait != nil || doc.Step.WaitCounts != nil {
			t.Errorf("step block %+v, want one with neither wait nor wait_counts: the run was cancelled before its wait", doc.Step)
		}
		for _, f := range diverged.Findings {
			if !slices.Contains(doc.Findings, f) {
				t.Errorf("findings %+v lack the run's %+v", doc.Findings, f)
			}
		}
		tail := "\nstep readiness e1: begins\n" + waiting + "\ndiverged towards stage change-1/linked (bundle " + short(doc.BundleID) +
			") at phase readiness: landed none; not landed e1, s1; the twin is up at stage change-1/sealed (bundle " + short(h.fromID) +
			"); fylgja twin destroy clears it\n"
		if !strings.HasSuffix(stdout, tail) {
			t.Errorf("stdout:\n%s\nwant it to end:%s", stdout, tail)
		}
	})

	t.Run("a second stops waiting", func(t *testing.T) {
		stepHost(t, "plan-link-added.json", nil)
		interrupts := useInterrupts(t)
		svc := &fakeService{runID: stepRunID, events: events, release: make(chan struct{})}
		svc.afterFollow = func() { interrupts <- os.Interrupt; interrupts <- os.Interrupt }
		stdout, code, doc := runInterrupted(t, svc)
		want := cancelled(findings.StepReadiness, "stopped waiting for run "+stepRunID+"; it continues on the workflow service, "+
			"and fylgja twin destroy will wait for it")
		if got := refusalOf(t, doc); svc.cancels != 1 || code != findings.ExitError || doc.Status != findings.StatusError || got != want {
			t.Errorf("Cancel called %d times, exit %d, status %s, %+v\nwant once, 2, error, %+v", svc.cancels, code, doc.Status, got, want)
		}
		if !strings.HasSuffix(stdout, "\n"+waiting+"\n") {
			t.Errorf("stdout:\n%s\nwant it to end %q", stdout, waiting)
		}
	})

	t.Run("one before the start returns abandons it", func(t *testing.T) {
		stepHost(t, "plan-link-added.json", nil)
		interrupts := useInterrupts(t)
		svc := &fakeService{startBlocks: true, startErr: context.Canceled}
		interrupts <- os.Interrupt
		stdout, code, doc := runInterrupted(t, svc)
		want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleRunCancelled, Object: provision.WorkflowStep,
			Step: findings.StepStart, Message: "interrupted before the step run was started, so nothing was started (context canceled)"}
		if got := refusalOf(t, doc); code != findings.ExitError || doc.Status != findings.StatusError || got != want {
			t.Errorf("exit %d, status %s, %+v\nwant 2, error, %+v", code, doc.Status, got, want)
		}
		svc.mu.Lock()
		defer svc.mu.Unlock()
		if !svc.abandoned || svc.cancels != 0 || !slices.Equal(svc.calls, []string{"StartStep"}) {
			t.Errorf("abandoned %v, Cancel called %d times, the service asked %v; want the one start abandoned and nothing cancelled",
				svc.abandoned, svc.cancels, svc.calls)
		}
		if doc.Subject.RunID != "" || strings.Contains(stdout, "run "+provision.WorkflowStep) {
			t.Errorf("subject %+v, stdout:\n%s\nwant no run named or followed", doc.Subject, stdout)
		}
	})

	t.Run("one racing a start that succeeds is the first", func(t *testing.T) {
		stepHost(t, "plan-link-added.json", nil)
		interrupts := useInterrupts(t)
		release := make(chan struct{})
		svc := &fakeService{runID: stepRunID, startBlocks: true, release: release, stepResult: beforeStage}
		svc.onCancel = func() { close(release) }
		interrupts <- os.Interrupt
		stdout, code, doc := runInterrupted(t, svc)
		if svc.cancels != 1 || !svc.abandoned {
			t.Errorf("Cancel called %d times, start abandoned %v; want once, true", svc.cancels, svc.abandoned)
		}
		if code != findings.ExitError || doc.Status != findings.StatusError || doc.Subject.RunID != stepRunID ||
			!slices.Contains(doc.Findings, beforeStage.Findings[0]) {
			t.Errorf("exit %d, status %s, subject %+v, findings %+v; want 2, error, the run named and its run.cancelled",
				code, doc.Status, doc.Subject, doc.Findings)
		}
		if line := "\nrun " + provision.WorkflowStep + " " + stepRunID + "\n" + waiting + "\n"; !strings.HasSuffix(stdout, line) {
			t.Errorf("stdout:\n%s\nwant it to end:%s", stdout, line)
		}
	})
}

// --wait sets the budget of the step's wait after its record, in seconds, a part of a second
// counting as a whole one; left out, it is verify.DefaultBudget's 120. --wait 0 reads once.
// A step to a snapshot takes it as a step to a stage does (FR-017).
func TestStepWaitFlag(t *testing.T) {
	for _, c := range []struct {
		name     string
		args     []string
		waitS    int
		snapshot bool
	}{
		{"left out", nil, 120, false},
		{"30s", []string{"--wait", "30s"}, 30, false},
		{"0", []string{"--wait=0"}, 0, false},
		{"2m", []string{"--wait", "2m"}, 120, false},
		{"a part of a second", []string{"--wait", "1500ms"}, 2, false},
		{"30s to a snapshot", []string{"--wait", "30s"}, 30, true},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := stepHost(t, "plan-link-added.json", nil)
			args := append([]string{"--allow-restart"}, c.args...)
			var target string
			if c.snapshot {
				s, _ := targetSnapshot(t, h, "linked")
				target = s.ID
				args = append(args, "--snapshot", target)
			}
			svc := &fakeService{runID: stepRunID, events: stepEvents(), stepResult: provision.StepResult{Outcome: provision.StepStepped,
				Findings: findings.List{}, Record: &wire.TwinRecord{State: wire.StateReady}}}
			useService(t, svc)
			useInterrupts(t)
			out := runStepCmd(t, args...)
			if out.code != findings.ExitOK || len(svc.stepped) != 2 {
				t.Fatalf("exit %d, %d runs started; want 0, one per run of the command; findings %+v", out.code, len(svc.stepped),
					out.doc.Findings)
			}
			for _, in := range svc.stepped {
				if in.WaitS != c.waitS {
					t.Errorf("the run's input carries wait_s %d, want %d", in.WaitS, c.waitS)
				}
				if c.snapshot && in.To.SnapshotID != target {
					t.Errorf("the run steps to snapshot %q, want %s", in.To.SnapshotID, target)
				}
			}
		})
	}
}

// --wait's value is refused before any connection as verify.wait.invalid, exit 2, at step
// start, object --wait: empty, not a duration, or negative. Neither
// Infrahub, containerlab nor the workflow service is asked anything, on the run and on the
// dry run alike.
func TestStepWaitRefusedBeforeAnyConnection(t *testing.T) {
	for _, c := range []struct {
		args    []string
		message string
	}{
		{[]string{"--wait="}, "--wait= is empty; give a duration such as --wait=2m, or leave --wait out for the default 2m0s"},
		{[]string{"--wait=banana"}, `--wait=banana is not a duration: time: invalid duration "banana"`},
		{[]string{"--wait", "banana", "--dry-run"}, `--wait=banana is not a duration: time: invalid duration "banana"`},
		{[]string{"--wait=-5s"}, "--wait=-5s is not a duration: a budget cannot be negative"},
	} {
		t.Run(strings.Join(c.args, " "), func(t *testing.T) {
			h := stepHost(t, "plan-link-added.json", nil)
			h.clab.calls = nil
			out := runStepCmd(t, append([]string{"--allow-restart"}, c.args...)...)
			want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleVerifyWaitInvalid, Object: "--wait",
				Step: findings.StepStart, Message: c.message}
			if out.code != findings.ExitError || out.doc.Status != findings.StatusError || len(out.doc.Findings) != 1 ||
				out.doc.Findings[0] != want {
				t.Errorf("exit %d, status %s, findings %+v; want 2, error, %+v alone", out.code, out.doc.Status, out.doc.Findings, want)
			}
			if len(h.infra.requests()) > h.before || len(h.clab.calls) != 0 {
				t.Errorf("Infrahub was asked %d times and containerlab %v after the host was built; want nothing",
					len(h.infra.requests())-h.before, h.clab.calls)
			}
			if strings.Contains(out.stdout, "dry run") {
				t.Errorf("the refusal printed the dry run's lines:\n%s", out.stdout)
			}
		})
	}
}

// The dry run says the step will wait after its record and for at most how long, after the
// push: line, and its document's step.wait is the budget alone.
func TestStepDryRunWait(t *testing.T) {
	stepHost(t, "plan-link-added.json", nil)
	out := runStepCmd(t, "--dry-run", "--allow-restart", "--wait", "30s")
	lines := strings.Split(out.stdout, "\n")
	push := slices.IndexFunc(lines, func(l string) bool { return strings.HasPrefix(l, "push: ") })
	if push < 0 || push+1 >= len(lines) || lines[push+1] != "wait: after the record, until the twin conforms, at most 30s" {
		t.Errorf("stdout:\n%s\nwant the wait line right after the push: line", out.stdout)
	}
	if w := out.doc.Step.Wait; w == nil || w.BudgetS != 30 || w.Outcome != "" {
		t.Errorf("step.wait %+v, want the budget 30 alone", w)
	}
	raw, err := json.Marshal(out.doc)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(raw), `"wait":{"budget_s":30}`) {
		t.Errorf("document %s, want step.wait {\"budget_s\":30}", raw)
	}
	if strings.Contains(string(raw), `"wait_counts"`) {
		t.Errorf("the dry run's document carries wait_counts: %s", raw)
	}
}

// The run prints how its wait ended after step record: and adds it to the closing line after
// M11's timings, in the words the warning begins with; M11's line is otherwise byte for byte
// what it was, and the exit is M11's (contracts/cli.md, twin step --wait).
// An activity that failed outright prints that the wait could not complete. The document
// carries the wait's last read counted by kind beside the wait when the wait read, and no
// key otherwise (015).
func TestStepRunReportsTheWait(t *testing.T) {
	const m11 = "stepped to stage change-1/linked (bundle %s) in 71.2s: reconcile 3.9s; readiness e1 54.8s; push e1 1.6s, s1 2.4s"
	reconcile := 3.9
	e1Took, s1Took := 1.6, 2.4
	neighbor := func(object string) wire.StepFinding {
		return wire.StepFinding{Rule: findings.RuleVerifyNeighbor, Object: object, Message: "node " + object + " sees no neighbour"}
	}
	observed := func(detail string) provision.Event {
		return provision.Event{WorkflowID: provision.WorkflowStep, Step: "observe", End: true, Outcome: provision.EventDone,
			Duration: 2600 * time.Millisecond, Detail: detail}
	}
	zero, three := 0, 3
	settledCounts := &wire.VerifyCounts{HostName: findings.VerifyCount{Held: 3, Unread: &zero},
		PortEnabled: findings.VerifyCount{Held: 6, Skipped: &zero, Unread: &zero},
		Neighbor:    findings.VerifyCount{Held: 6, Skipped: &zero, Unread: &zero}, Record: findings.VerifyCount{Held: 3}}
	expiredCounts := &wire.VerifyCounts{HostName: findings.VerifyCount{Held: 3, Unread: &zero},
		PortEnabled: findings.VerifyCount{Held: 6, Skipped: &zero, Unread: &zero},
		Neighbor:    findings.VerifyCount{Held: 3, Failed: 3, Skipped: &three, Unread: &zero}, Record: findings.VerifyCount{Held: 3}}
	for _, c := range []struct {
		name     string
		wait     *wire.StepWait
		counts   *wire.VerifyCounts
		event    provision.Event
		progress string
		clause   string
	}{
		{"settled", &wire.StepWait{Outcome: wire.WaitSettled, BudgetS: 120, Reads: 2, AfterS: 2.4, Failing: []wire.StepFinding{}}, settledCounts,
			observed("settled after 2.4s (2 reads)"), "step observe: settled after 2.4s (2 reads)", "; settled after 2.4s"},
		{"expired", &wire.StepWait{Outcome: wire.WaitExpired, BudgetS: 120, Reads: 58, AfterS: 120,
			Failing: []wire.StepFinding{neighbor("s1:ethernet-1/3"), neighbor("e1:Ethernet3"), neighbor("e2:Ethernet1")}}, expiredCounts,
			observed("expired after 120.0s (58 reads, 3 failing)"), "step observe: expired after 120.0s (58 reads, 3 failing)",
			"; wait expired after 120.0s with 3 assertions failing"},
		{"cancelled", &wire.StepWait{Outcome: wire.WaitCancelled, BudgetS: 120, Reads: 7, AfterS: 12.4}, settledCounts,
			observed("cancelled after 12.4s (7 reads)"), "step observe: cancelled after 12.4s (7 reads)", "; wait cancelled after 12.4s"},
		{"incomplete, the activity failed", &wire.StepWait{Outcome: wire.WaitIncomplete, BudgetS: 120,
			Failing: []wire.StepFinding{{Rule: findings.RuleOperationFailed, Object: "/state/twin/twin.json", Message: "disk full"}}}, nil,
			provision.Event{WorkflowID: provision.WorkflowStep, Step: "observe", End: true, Outcome: provision.EventFailed,
				Duration: 100 * time.Millisecond, Rule: findings.RuleOperationFailed, Message: "reading the twin's record for the step's wait: disk full"},
			"step observe: could not complete: reading the twin's record for the step's wait: disk full", "; wait could not complete"},
		// The end of VerifyTwin's window is not retried, and the service closes the activity
		// timed out: the wait could not complete, as for one that failed outright.
		{"incomplete, the window ended", &wire.StepWait{Outcome: wire.WaitIncomplete, BudgetS: 120,
			Failing: []wire.StepFinding{{Rule: findings.RuleOperationFailed, Object: stepRunID,
				Message: "activity ScheduleToClose timeout (type: ScheduleToClose)"}}}, nil,
			provision.Event{WorkflowID: provision.WorkflowStep, Step: "observe", End: true, Outcome: provision.EventTimedOut,
				Duration: 150 * time.Second, Message: "activity ScheduleToClose timeout"},
			"step observe: could not complete: activity ScheduleToClose timeout", "; wait could not complete"},
		{"the wait not run", nil, nil, provision.Event{}, "", ""},
	} {
		t.Run(c.name, func(t *testing.T) {
			stepHost(t, "plan-link-added.json", nil)
			events := stepEvents()
			if c.event.Step != "" {
				events = append(events, c.event)
			}
			res := provision.StepResult{Outcome: provision.StepStepped, Findings: findings.List{},
				PushPlan: []wire.StepPush{{Node: "e1", Reasons: []string{"artifact", "restarted"}, Outcome: wire.PushLanded, TookS: &e1Took},
					{Node: "s1", Reasons: []string{"artifact", "bootstrap"}, Outcome: wire.PushLanded, TookS: &s1Took}},
				Timings: wire.StepTimings{ReconcileS: &reconcile, Readiness: map[string]float64{"e1": 54.8},
					Push: map[string]float64{"e1": 1.6, "s1": 2.4}, WholeS: 71.2},
				Record: &wire.TwinRecord{State: wire.StateReady}, Wait: c.wait, WaitCounts: c.counts,
				StartedAt: "2026-10-02T09:14:30Z", EndedAt: "2026-10-02T09:15:41Z"}
			if c.wait != nil && c.wait.Outcome != wire.WaitSettled {
				res.Findings = findings.List{{Severity: findings.Warning, Rule: findings.RuleVerifyWaitUnsettled, Object: stepRunID,
					Step: findings.StepObserve, Message: strings.TrimPrefix(c.clause, "; wait ") + " …"}}
			}
			svc := &fakeService{runID: stepRunID, events: events, stepResult: res}
			useService(t, svc)
			useInterrupts(t)
			out := runStepCmd(t, "--allow-restart")
			if out.code != findings.ExitOK || out.doc.Status != findings.StatusOK {
				t.Fatalf("exit %d status %s, want 0, ok: the wait changes neither; findings %+v", out.code, out.doc.Status, out.doc.Findings)
			}
			tail := []string{"step record: done in 0.1s"}
			if c.progress != "" {
				tail = append(tail, c.progress)
			}
			tail = append(tail, fmt.Sprintf(m11, short(out.doc.BundleID))+c.clause)
			if !strings.HasSuffix(out.stdout, "\n"+strings.Join(tail, "\n")+"\n") {
				t.Errorf("stdout:\n%s\nwant it to end:\n%s", out.stdout, strings.Join(tail, "\n"))
			}
			switch w := out.doc.Step.Wait; {
			case c.wait == nil && w != nil:
				t.Errorf("step.wait %+v, want none: the wait did not run", w)
			case c.wait != nil && (w == nil || w.Outcome != c.wait.Outcome || w.Reads != c.wait.Reads || w.AfterS != c.wait.AfterS ||
				len(w.Failing) != len(c.wait.Failing)):
				t.Errorf("step.wait %+v, want the run's %+v", w, c.wait)
			}
			if got := out.doc.Step.WaitCounts; !reflect.DeepEqual(got, c.counts) {
				t.Errorf("step.wait_counts %+v, want the run's %+v", got, c.counts)
			}
		})
	}
}

// The run prints how each flow started after step stage: and what each lost after step
// observe:, labelled container timing, and the closing line ends with the loss, lost over
// sent per probe (016, contracts/cli.md, twin step). The document carries the run's loss;
// the dry run's, which starts nothing, carries loss null. A twin whose bundles carry no
// probe starts its run with no flow, nothing added and nothing dropped.
func TestStepRunReportsTheLoss(t *testing.T) {
	stepHost(t, "plan-link-added.json", nil)
	dry := runStepCmd(t, "--dry-run", "--allow-restart")
	raw, err := json.Marshal(dry.doc)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(raw), `"loss":null`) {
		t.Errorf("the dry run's document %s, want step.loss null", raw)
	}

	stepHost(t, "plan-link-added.json", nil)
	done := func(step string, d time.Duration, detail string) provision.Event {
		return provision.Event{WorkflowID: provision.WorkflowStep, Step: step, End: true, Outcome: provision.EventDone,
			Duration: d, Detail: detail}
	}
	var events []provision.Event
	for _, e := range stepEvents() {
		events = append(events, e)
		if e.Step == "stage" {
			events = append(events, done("flows", 400*time.Millisecond, "n1-loop started"))
		}
	}
	events = append(events, done("observe", 2600*time.Millisecond, "settled after 2.4s (2 reads)"),
		done("loss", 5100*time.Millisecond, "n1-loop 0/312 lost, longest gap 0.0s (container timing)"))
	reconcile := 3.9
	e1Took, s1Took := 1.6, 2.4
	loss := &wire.Loss{Basis: wire.LossBasisContainer, Probes: []wire.ProbeLoss{{Probe: "n1-loop",
		From: "clab-fylgja-n1-loop-a", To: "clab-fylgja-n1-loop-b", Outcome: wire.FlowMeasured, Sent: 312}},
		Added: []string{}, Dropped: []string{}}
	svc := &fakeService{runID: stepRunID, events: events, stepResult: provision.StepResult{Outcome: provision.StepStepped,
		Findings: findings.List{},
		PushPlan: []wire.StepPush{{Node: "e1", Reasons: []string{"artifact", "restarted"}, Outcome: wire.PushLanded, TookS: &e1Took},
			{Node: "s1", Reasons: []string{"artifact", "bootstrap"}, Outcome: wire.PushLanded, TookS: &s1Took}},
		Timings: wire.StepTimings{ReconcileS: &reconcile, Readiness: map[string]float64{"e1": 54.8},
			Push: map[string]float64{"e1": 1.6, "s1": 2.4}, WholeS: 71.2},
		Record: &wire.TwinRecord{State: wire.StateReady},
		Wait:   &wire.StepWait{Outcome: wire.WaitSettled, BudgetS: 120, Reads: 2, AfterS: 2.4, Failing: []wire.StepFinding{}},
		Loss:   loss, StartedAt: "2026-10-02T09:14:30Z", EndedAt: "2026-10-02T09:15:41Z"}}
	useService(t, svc)
	useInterrupts(t)
	out := runStepCmd(t, "--allow-restart")
	if out.code != findings.ExitOK || out.doc.Status != findings.StatusOK {
		t.Fatalf("exit %d status %s, want 0, ok: the loss changes neither; findings %+v", out.code, out.doc.Status, out.doc.Findings)
	}
	if !strings.Contains(out.stdout, "\nstep stage: done in 0.2s\nstep flows: n1-loop started\nstep reconcile: ") {
		t.Errorf("stdout:\n%s\nwant step flows: right after step stage:", out.stdout)
	}
	tail := []string{"step observe: settled after 2.4s (2 reads)",
		"step loss: n1-loop 0/312 lost, longest gap 0.0s (container timing)",
		"stepped to stage change-1/linked (bundle " + short(out.doc.BundleID) + ") in 71.2s: reconcile 3.9s; readiness e1 54.8s; " +
			"push e1 1.6s, s1 2.4s; settled after 2.4s; loss n1-loop 0/312"}
	if !strings.HasSuffix(out.stdout, "\n"+strings.Join(tail, "\n")+"\n") {
		t.Errorf("stdout:\n%s\nwant it to end:\n%s", out.stdout, strings.Join(tail, "\n"))
	}
	want := &findings.StepLoss{Basis: "container", Probes: []findings.StepProbeLoss{{Probe: "n1-loop",
		From: "clab-fylgja-n1-loop-a", To: "clab-fylgja-n1-loop-b", Outcome: "measured", Sent: 312}}, Added: []string{}, Dropped: []string{}}
	if got := out.doc.Step.Loss; !reflect.DeepEqual(got, want) {
		t.Errorf("step.loss %+v, want the run's %+v", got, want)
	}
	svc.mu.Lock()
	defer svc.mu.Unlock()
	if len(svc.stepped) == 0 {
		t.Fatal("no step run started")
	}
	for _, in := range svc.stepped {
		if in.Flows != nil || in.Added != nil || in.Dropped != nil {
			t.Errorf("a probe-less twin's step started with flows %+v, added %q, dropped %q; want none", in.Flows, in.Added, in.Dropped)
		}
	}
}

// US2's step scenarios through the harness (014, T036), on stepInfrahub's proposed change:
// the target with none given, a step back, a stage foreign to the twin's proposed change, a
// step from the branch point to the head, a target that is the twin's own stage under
// another reference, a head that has moved since the twin was built, and a stale target.
// TestStepRefusedBeforeAnyConnection holds the refusals of the table in contracts/cli.md; these
// are the scenarios of spec.md's US2.

// stepHeadAt is the head of change-1 as stepInfrahub serves it: one microsecond after its
// last version's stamp.
const stepHeadAt = "2026-10-16T11:30:00.000001+00:00"

// stepTwin is a twin of change-1's stage label as its create records it, at at on branch,
// from bundle id; retired drops e2, as less and the head retired it.
type stepTwin struct {
	id, label, description, atSource, branch, at string
	retired                                      bool
}

// twinAt rewrites stepHost's record as the twin of w, which then steps from w's snapshot and
// bundle.
func twinAt(t *testing.T, h *stepHostFixture, w stepTwin) {
	t.Helper()
	h.fromSnapshot = snapshotOf(t, w.id)
	writeTwin(t, h.paths, stepRecordOf(t, w.id, func(f *lab.RecordFields) {
		f.SnapshotID = h.fromSnapshot
		f.Provenance.Branch, f.Provenance.At = w.branch, w.at
		f.Stage = stepStage(w.label, w.description, w.atSource)
		if w.retired {
			f.Nodes = slices.DeleteFunc(f.Nodes, func(n wire.TwinNode) bool { return n.Name == "e2" })
		}
	}))
	h.fromID = w.id
}

// lineOf is stdout's nth line, from 1, or "" past its end.
func lineOf(stdout string, n int) string {
	l := lines2(stdout)
	if n > len(l) {
		return ""
	}
	return l[n-1]
}

// onlyInspected fails unless containerlab was asked nothing but the host's state, once per
// run of the command: nothing of the step's own (the target's host check, containerlab's
// plan) was reached.
func onlyInspected(t *testing.T, label string, c *stepClab) {
	t.Helper()
	c.mu.Lock()
	defer c.mu.Unlock()
	for _, call := range c.calls {
		if !slices.Equal(call, inspectAll) {
			t.Errorf("%s: containerlab was asked %v; a refusal at resolve asks only for the host's state", label, call)
		}
	}
}

// intentReadAfter is every request for a branch's intent the fake answered after the
// first n: its devices, their ports or an artifact's content.
func intentReadAfter(f *fakeInfrahub, n int) []fakeRequest {
	var out []fakeRequest
	for _, r := range f.requests()[n:] {
		if strings.HasPrefix(r.Path, "/api/storage/") || r.Operation == "Devices" || r.Operation == "Ports" {
			out = append(out, r)
		}
	}
	return out
}

// Scenario 2: with no target, a step goes to the next stage of the twin's proposed change,
// the head when no mark follows (the next mark is TestStepDryRun's, sealed to linked); at
// the head, with the head where the twin was built, nothing follows, and the step is
// refused saying so.
func TestStepWithNoTargetGoesToTheNextStage(t *testing.T) {
	for _, c := range []struct {
		name string
		// from is the twin's stage.
		from stepTwin
		plan string
		// target is the target's resolved line; "" when the step is refused.
		target string
		want   findings.Finding
	}{
		{name: "the head when no mark follows", from: stepTwin{label: "less", description: "e2 retired", atSource: "given",
			branch: "change-1", at: stepLessAt, retired: true}, plan: "plan-nothing.json",
			target: "stage change-1/head: branch change-1 at " + stepHeadAt + " (head)"},
		{name: "nothing after the head", from: stepTwin{label: "head", atSource: "head", branch: "change-1", at: stepHeadAt,
			retired: true}, plan: "plan-nothing.json",
			want: findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepTargetUnknown, Object: "change-1/head",
				Step: findings.StepResolve, Message: "proposed change pc-1 on change-1 has no stage after change-1/head; " +
					"its stages are: " + stepStages}},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := stepHost(t, c.plan, nil)
			w := c.from
			w.id = buildStage(t, h.paths, w.label)
			twinAt(t, h, w)
			h.clab.calls = nil
			out := runStepCmd(t, "--dry-run")
			if c.target == "" {
				if got := refusalOf(t, out.doc); out.code != findings.ExitRejected || got != c.want {
					t.Errorf("exit %d, refusal %+v\nwant 1, %+v", out.code, got, c.want)
				}
				onlyInspected(t, c.name, h.clab)
				return
			}
			to := strings.TrimPrefix(strings.SplitN(c.target, ":", 2)[0], "stage ")
			if out.code != findings.ExitOK || lineOf(out.stdout, 3) != c.target || out.doc.Subject.Stage != to ||
				!strings.HasPrefix(lineOf(out.stdout, 4), "step change-1/"+w.label+" → "+to+" (") {
				t.Errorf("exit %d, subject %+v, stdout:\n%s\nwant 0, the step from change-1/%s to %s, resolved as %q",
					out.code, out.doc.Subject, out.stdout, w.label, to, c.target)
			}
			if carriesRule(out.doc.Findings, findings.RuleStepStageSkipped) {
				t.Errorf("findings %+v; the next stage skips none", out.doc.Findings)
			}
		})
	}
}

// Scenario 3: a step back to an earlier mark goes there, forward or back alike: from
// linked to sealed, the step takes the link off, containerlab deletes its two ends, and the
// push sends e1 and s1 sealed's artifacts by their packages' replace, which takes off each
// node what sealed lacks (M11's step back). The dry run's lines and the run's first and
// closing lines are pinned.
func TestStepBackToAnEarlierMark(t *testing.T) {
	h := stepHost(t, "plan-nothing.json", nil)
	sealedID := h.fromID
	linkedID := buildStage(t, h.paths, "linked")
	twinAt(t, h, stepTwin{id: linkedID, label: "linked", description: "a link between e1 and s1", atSource: "written",
		branch: "change-1", at: stepWrittenAt})
	h.clab.plan = []byte(`{"dry-run": true, "deployed-lab": false, "lab-name": "fylgja", "added-nodes": [], "deleted-nodes": [],
		"recreated-nodes": [], "started-nodes": [], "added-links": [], "deleted-endpoints": ["e1:eth3", "s1:e1-3"],
		"restarted-nodes": ["e1"], "node-change-reasons": {"e1": "deleted endpoint"}}`)
	first := []string{
		"twin: stage change-1/linked (snapshot " + short(h.fromSnapshot) + ", bundle " + short(linkedID) + "), pinned at " +
			stepWrittenAt + "; 3 nodes",
		`stage change-1/sealed: branch change-1 at ` + stepMixedAt + ` (given), "the mixed fixture as sealed"`,
		"step change-1/linked → change-1/sealed (" + short(linkedID) + " → " + short(sealedID) + "):",
		"  nodes: ~e1 (mapping); ~s1 (bootstrap, mapping)",
		"  links: -e1:eth3 — s1:e1-3",
		"  artifacts: e1 device-config cbc8c75d… → b1431710…; s1 device-config 8e15691e… → fdf83f15…",
		"reconcile: restart e1 (deleted endpoint; arista_eos declares restart); live s1 (nokia_srlinux declares live)",
		"push: e1 (artifact, restarted); s1 (artifact, bootstrap); e2 untouched",
	}

	out := runStepCmd(t, "--stage", "change-1/sealed", "--dry-run", "--allow-restart")
	want := lines(append(append([]string{"dry run: no lab, container, twin directory or run is changed"}, first...),
		"wait: after the record, until the twin conforms, at most 2m0s",
		"memory: sum 5120 MiB; host budget unset",
		"host: lab fylgja present; twin directory present",
		"verdict: clear")...)
	if out.code != findings.ExitOK || out.stdout != want || out.doc.BundleID != sealedID {
		t.Errorf("exit %d, bundle_id %s, stdout:\n%s\nwant 0, sealed's %s, and:\n%s", out.code, out.doc.BundleID, out.stdout, sealedID, want)
	}
	if carriesRule(out.doc.Findings, findings.RuleStepStageSkipped) {
		t.Errorf("findings %+v; a step to the stage before skips none", out.doc.Findings)
	}
	if carriesRule(out.doc.Findings, findings.RuleStageTwinMoved) {
		t.Errorf("findings %+v; the twin's mark still resolves to the record's reference, so it has not moved", out.doc.Findings)
	}
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	if st := out.doc.Step; st == nil || len(st.PushPlan) != 2 {
		t.Fatalf("step block %+v; want e1 and s1 pushed", st)
	}
	for _, p := range out.doc.Step.PushPlan {
		id := map[string]string{"e1": "arista_eos", "s1": "nokia_srlinux"}[p.Node]
		if pkg, ok := reg.LookupID(id); !ok || pkg.Config.Mode != psp.ModeReplace {
			t.Errorf("node %s pushes by package %s, mode %v; a step back takes off what the earlier stage lacks only by replace",
				p.Node, id, pkg)
		}
	}

	// The run: its first lines are the dry run's, its closing line names the stage it
	// stepped back to.
	svc := &fakeService{runID: stepRunID, events: stepEvents()}
	reconcile, e1Took, s1Took := 3.9, 1.6, 2.4
	svc.stepResult = provision.StepResult{Outcome: provision.StepStepped, Findings: findings.List{},
		PushPlan: []wire.StepPush{
			{Node: "e1", Reasons: []string{"artifact", "restarted"}, Outcome: wire.PushLanded, TookS: &e1Took},
			{Node: "s1", Reasons: []string{"artifact", "bootstrap"}, Outcome: wire.PushLanded, TookS: &s1Took}},
		Timings: wire.StepTimings{ReconcileS: &reconcile, Readiness: map[string]float64{"e1": 54.8},
			Push: map[string]float64{"e1": 1.6, "s1": 2.4}, WholeS: 71.2},
		Record:    &wire.TwinRecord{State: wire.StateReady},
		StartedAt: "2026-10-02T09:14:30Z", EndedAt: "2026-10-02T09:15:41Z"}
	useService(t, svc)
	useInterrupts(t)
	out = runStepCmd(t, "--stage", "change-1/sealed", "--allow-restart")
	want = lines(append(first,
		"run fylgja-step "+stepRunID,
		"step inspect: done in 0.1s",
		"step host check: done in 0.3s",
		"step plan reconcile: done in 0.5s (restart e1)",
		"step stage: done in 0.2s",
		"step reconcile: done in 3.9s (3 nodes)",
		"step readiness e1: ready in 54.8s",
		"step push e1: done in 1.6s",
		"step push s1: done in 2.4s",
		"step record: done in 0.1s",
		"stepped to stage change-1/sealed (bundle "+short(sealedID)+") in 71.2s: reconcile 3.9s; readiness e1 54.8s; push e1 1.6s, s1 2.4s")...)
	if out.code != findings.ExitOK || out.stdout != want || carriesRule(out.doc.Findings, findings.RuleStageTwinMoved) {
		t.Errorf("exit %d, findings %+v, stdout:\n%s\nwant 0, no stage.twin.moved, and:\n%s", out.code, out.doc.Findings,
			out.stdout, want)
	}
	in := svc.stepped[0]
	wantFrom := wire.StepSide{Stage: stepStage("linked", "a link between e1 and s1", "written"), SnapshotID: snapshotOf(t, linkedID),
		BundleID: linkedID, At: stepWrittenAt}
	wantTo := wire.StepSide{Stage: stepStage("sealed", "the mixed fixture as sealed", "given"), SnapshotID: snapshotOf(t, sealedID),
		BundleID: sealedID, At: stepMixedAt, Branch: "change-1"}
	if !reflect.DeepEqual(in.From, wantFrom) || !reflect.DeepEqual(in.To, wantTo) || len(in.PushPlan) != 2 ||
		!slices.Equal(in.PushPlan[0].Reasons, []string{"artifact", "restarted"}) || !slices.Equal(in.PushPlan[1].Reasons, []string{"artifact", "bootstrap"}) {
		t.Errorf("the run's input from %+v to %+v, push plan %+v; want linked → sealed, e1 (artifact, restarted) and s1 "+
			"(artifact, bootstrap)", in.From, in.To, in.PushPlan)
	}
	noContent(t, "the step back", out.stdout, out.stderr)
}

// US3 scenario 3 (FR-014, FR-016; research R-07): a stage twin of proposed change pc-1 steps
// to a stage of another, of another branch or opened on the twin's own branch since pc-1
// closed, and the record names that stage, its proposed change and its branch;
// step.target.foreign refuses it no longer. Between two proposed changes no mark is skipped,
// and the twin's own stage is not read for stage.twin.moved, though pc-1 is closed. The dry
// run's resolution and step lines and the run's input are pinned, and the record the run then
// writes is read back.
func TestStepToAStageOfAnotherProposedChange(t *testing.T) {
	const description = "the link, proposed again"
	for _, c := range []struct {
		name, branch string
		setup        func(t *testing.T, f *fakeInfrahub)
	}{
		{name: "of another branch", branch: "change-2", setup: func(t *testing.T, f *fakeInfrahub) {
			mixed, err := ctm.Load(repoPath("testdata", "ctm", "mixed.json"))
			if err != nil {
				t.Fatal(err)
			}
			mixed.Envelope.Branch = "change-2"
			linked := withMixedLink(t)
			linked.Envelope.Branch = "change-2"
			f.versions["change-2"] = []fakeVersion{{Since: "2026-10-16T08:10:00.000000+00:00", CTM: mixed},
				{Since: "2026-10-16T09:30:00.000000+00:00", CTM: linked}}
			f.change("pc-2", "change-2", mark("st-2-linked", "linked", "", description))
		}},
		{name: "opened on the twin's branch", branch: "change-1", setup: func(t *testing.T, f *fakeInfrahub) {
			f.changes[0].State = "closed"
			f.change("pc-2", "change-1", mark("st-2-linked", "linked", "", description))
		}},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := stepHost(t, "plan-link-added.json", nil)
			c.setup(t, h.infra)
			ref := c.branch + "/linked"
			resolved := "stage " + ref + ": branch " + c.branch + " at " + stepWrittenAt + ` (written), "` + description + `"`
			out := runStepCmd(t, "--stage", ref, "--dry-run", "--allow-restart")
			if out.code != findings.ExitOK || lineOf(out.stdout, 3) != resolved || out.doc.Subject.Stage != ref ||
				!strings.HasPrefix(lineOf(out.stdout, 4), "step change-1/sealed → "+ref+" (") ||
				!strings.Contains(out.stdout, "\nverdict: clear\n") {
				t.Errorf("exit %d, subject %+v, findings %+v, stdout:\n%s\nwant 0, the step from change-1/sealed to %s, resolved as %q",
					out.code, out.doc.Subject, out.doc.Findings, out.stdout, ref, resolved)
			}
			for _, rule := range []string{findings.RuleStepStageSkipped, findings.RuleStageTwinMoved} {
				if carriesRule(out.doc.Findings, rule) {
					t.Errorf("findings %+v; a step out of the twin's proposed change files no %s", out.doc.Findings, rule)
				}
			}

			svc := stepToSnapshotRun(t)
			out = runStepCmd(t, "--stage", ref, "--allow-restart")
			if out.code != findings.ExitOK || len(svc.stepped) != 2 {
				t.Fatalf("exit %d, %d runs started; want 0 and one per run of the command: %+v", out.code, len(svc.stepped),
					out.doc.Findings)
			}
			in := svc.stepped[1]
			wantTo := &wire.StageRef{ProposedChange: wire.StageChange{ID: "pc-2", Branch: c.branch}, Label: "linked",
				Description: description, AtSource: findings.AtSourceWritten}
			if !reflect.DeepEqual(in.From.Stage, stepStage("sealed", "the mixed fixture as sealed", "given")) ||
				!reflect.DeepEqual(in.To.Stage, wantTo) || in.To.Branch != c.branch || in.To.At != stepWrittenAt {
				t.Errorf("the run's input %+v → %+v; want sealed's side to pc-2's linked on %s at %s", in.From, in.To, c.branch, stepWrittenAt)
			}
			rec := recordOnHost(t, h, in)
			if rec.Stage == nil || !reflect.DeepEqual(*rec.Stage, *wantTo) || rec.Provenance.Branch != c.branch ||
				rec.Provenance.At != stepWrittenAt || rec.Source != wire.SourceIntent || rec.SnapshotID == nil ||
				*rec.SnapshotID != in.To.SnapshotID || rec.BundleID != in.To.BundleID {
				t.Errorf("the record after the step %+v, stage %+v; want pc-2's linked on %s at %s, its snapshot and bundle",
					rec, rec.Stage, c.branch, stepWrittenAt)
			}
		})
	}
}

// US3 scenario 1 (FR-014; research R-08): a twin whose record names no stage, built from
// --branch or --snapshot, or stepped to a snapshot since, has no next stage, so twin step
// given neither --stage nor --snapshot is refused step.target.unknown, its object the
// record's bundle, from the record alone: neither the workflow service nor Infrahub nor
// containerlab is asked anything, the dry run's and --allow-restart's included, and the
// record is as it was. A record that no target can step meets its own refusal first, from
// the same file read (FR-012 and FR-014, R-08 as amended): a diverged twin, then one whose
// scope no read can be made under, then one naming no snapshot.
func TestStepWithNoTargetNamesNoStage(t *testing.T) {
	noTarget := func(bundleID string) findings.Finding {
		return findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepTargetUnknown, Step: findings.StepResolve,
			Object: bundleID, Message: noTargetMessage}
	}
	refused := func(t *testing.T, h *stepHostFixture, want findings.Finding) {
		t.Helper()
		useService(t, nil)
		h.clab.calls = nil
		before := len(h.infra.requests())
		record := sha256Of(t, h.paths.TwinJSON)
		for _, args := range [][]string{nil, {"--dry-run"}, {"--allow-restart", "--wait", "1m"}} {
			out := runStepCmd(t, args...)
			if got := refusalOf(t, out.doc); out.code != findings.ExitRejected || got != want || out.doc.Step != nil {
				t.Errorf("%v: exit %d, refusal %+v, step %+v\nwant 1, %+v and no step", args, out.code, got, out.doc.Step, want)
			}
			if n := len(h.infra.requests()); n != before {
				t.Errorf("%v: Infrahub was asked %+v", args, h.infra.requests()[before:])
			}
			if len(h.clab.calls) != 0 {
				t.Errorf("%v: containerlab or docker was asked %v", args, h.clab.calls)
			}
		}
		if sha256Of(t, h.paths.TwinJSON) != record {
			t.Errorf("twin.json changed under a refused step")
		}
	}
	for _, from := range []int{0, 2} {
		t.Run("built from "+stepFroms[from].name, func(t *testing.T) {
			h := stepHost(t, "plan-link-added.json", stepFroms[from].change)
			refused(t, h, noTarget(h.fromID))
		})
	}
	unsteppable := func(message string) func(h *stepHostFixture) findings.Finding {
		return func(h *stepHostFixture) findings.Finding {
			return findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepTwinUnsteppable, Step: findings.StepResolve,
				Object: h.fromID, Message: message}
		}
	}
	for _, c := range []struct {
		name string
		host func(t *testing.T) *stepHostFixture
		want func(h *stepHostFixture) findings.Finding
	}{
		{"diverged, built from --snapshot", func(t *testing.T) *stepHostFixture {
			h := divergedStepHost(t)
			rec, err := lab.ReadRecord(h.paths.TwinJSON)
			if err != nil {
				t.Fatal(err)
			}
			rec.Stage, rec.Step.From.Stage, rec.Source = nil, nil, wire.SourceSnapshot
			writeTwin(t, h.paths, rec)
			return h
		}, func(h *stepHostFixture) findings.Finding { return divergedRefusal(h.fromID) }},
		{"of twin.json 10 naming scope fylgja and no snapshot", func(t *testing.T) *stepHostFixture {
			return editedRecordHost(t, func(m map[string]any) {
				m["stage"], m["snapshot_id"] = nil, nil
				m["provenance"].(map[string]any)["scope"] = "fylgja"
			})
		}, unsteppable(`the twin's record names scope "fylgja", which is not tag:<name>, and every read a step makes is ` +
			"under the record's scope; fylgja twin destroy clears it")},
		{"of a bundle", func(t *testing.T) *stepHostFixture {
			return stepHost(t, "plan-link-added.json", func(f *lab.RecordFields) {
				f.Stage, f.Source, f.ObservedAt, f.Provenance.At, f.SnapshotID = nil, wire.SourceBundle, nil, "", ""
			})
		}, unsteppable("the twin was provisioned from a bundle, which names no snapshot; only a twin whose record names a " +
			"snapshot steps; fylgja twin destroy clears it")},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := c.host(t)
			refused(t, h, c.want(h))
		})
	}
	// A stage twin stepped to a snapshot names no stage afterwards: its next step needs a
	// target too.
	t.Run("stepped to a snapshot", func(t *testing.T) {
		h := stepHost(t, "plan-link-added.json", nil)
		target, toID := targetSnapshot(t, h, "linked")
		svc := stepToSnapshotRun(t)
		if out := runStepCmd(t, "--snapshot", target.ID, "--allow-restart"); out.code != findings.ExitOK || len(svc.stepped) != 2 {
			t.Fatalf("the step to the snapshot: exit %d, %d runs; findings %+v", out.code, len(svc.stepped), out.doc.Findings)
		}
		if rec := recordOnHost(t, h, svc.stepped[1]); rec.Stage != nil || rec.BundleID != toID {
			t.Fatalf("the record after the step names stage %+v, bundle %s; want none and %s", rec.Stage, rec.BundleID, toID)
		}
		refused(t, h, noTarget(toID))
	})
}

// US3 scenarios 2 and 5, and SC-004's third reference (FR-014, FR-016; research R-07): a twin
// whose record names no stage, built from --branch or --snapshot, steps to --stage
// <branch>/<label>, resolved and read under the record's scope, and the record names the
// stage beside the source it keeps (twin.json 10 holds a stage beside source snapshot). No
// stage.twin.moved and no step.stage.skipped is filed, since the twin names no stage to have
// moved or to skip from. A stage resolving to the twin's own (branch, at) is
// step.target.current, as for a stage twin.
func TestStepStagelessTwinToAStage(t *testing.T) {
	for _, from := range []int{0, 2} {
		t.Run("built from "+stepFroms[from].name, func(t *testing.T) {
			h := stepHost(t, "plan-link-added.json", stepFroms[from].change)
			twin := "twin: snapshot " + short(h.fromSnapshot) + " (bundle " + short(h.fromID) + "), branch change-1"
			out := runStepCmd(t, "--stage", "change-1/linked", "--dry-run", "--allow-restart")
			resolved := "stage change-1/linked: branch change-1 at " + stepWrittenAt + ` (written), "a link between e1 and s1"`
			if out.code != findings.ExitOK || !strings.HasPrefix(lineOf(out.stdout, 2), twin) || lineOf(out.stdout, 3) != resolved ||
				!strings.HasPrefix(lineOf(out.stdout, 4), "step snapshot "+short(h.fromSnapshot)+" → change-1/linked (") ||
				!strings.Contains(out.stdout, "\nverdict: clear\n") {
				t.Errorf("exit %d, findings %+v, stdout:\n%s\nwant 0, the step from the twin's snapshot to change-1/linked",
					out.code, out.doc.Findings, out.stdout)
			}
			for _, rule := range []string{findings.RuleStepStageSkipped, findings.RuleStageTwinMoved} {
				if carriesRule(out.doc.Findings, rule) {
					t.Errorf("findings %+v; a twin naming no stage files no %s", out.doc.Findings, rule)
				}
			}

			svc := stepToSnapshotRun(t)
			if out = runStepCmd(t, "--stage", "change-1/linked", "--allow-restart"); out.code != findings.ExitOK || len(svc.stepped) != 2 {
				t.Fatalf("exit %d, %d runs started; findings %+v", out.code, len(svc.stepped), out.doc.Findings)
			}
			in := svc.stepped[1]
			want := stepStage("linked", "a link between e1 and s1", findings.AtSourceWritten)
			if in.From.Stage != nil || in.From.SnapshotID != h.fromSnapshot || !reflect.DeepEqual(in.To.Stage, want) {
				t.Errorf("the run's input %+v → %+v; want the twin's snapshot, no stage, to change-1/linked", in.From, in.To)
			}
			rec := recordOnHost(t, h, in)
			if rec.Stage == nil || !reflect.DeepEqual(*rec.Stage, *want) || rec.Source != stepFroms[from].source ||
				rec.Provenance.Branch != "change-1" || rec.Provenance.At != stepWrittenAt || rec.BundleID != in.To.BundleID {
				t.Errorf("the record after the step %+v, stage %+v; want change-1/linked beside source %s", rec, rec.Stage,
					stepFroms[from].source)
			}
		})
	}
	t.Run("to the twin's own reference", func(t *testing.T) {
		h := stepHost(t, "plan-link-added.json", func(f *lab.RecordFields) { f.Stage = nil })
		out := runStepCmd(t, "--stage", "change-1/sealed", "--allow-restart")
		want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepTargetCurrent, Step: findings.StepResolve,
			Object: "change-1/sealed", Message: "the twin is already at stage change-1/sealed (branch change-1, at " + stepMixedAt +
				"); the proposed change's stages are: " + stepStages}
		if got := refusalOf(t, out.doc); out.code != findings.ExitRejected || got != want {
			t.Errorf("exit %d, refusal %+v\nwant 1, %+v", out.code, got, want)
		}
		if read := intentReadAfter(h.infra, h.before); len(read) != 0 {
			t.Errorf("a target refused before its read was read: %+v", read)
		}
	})
}

// Scenario 5: from the branch point, a step to the head goes straight there, warning that it
// skips the marks between, and with no target goes to the first mark, skipping none. main
// here reads as the mixed fixture, as change-1 began.
func TestStepFromTheBranchPointToTheHead(t *testing.T) {
	h := stepHost(t, "plan-nothing.json", nil)
	mixed, err := ctm.Load(repoPath("testdata", "ctm", "mixed.json"))
	if err != nil {
		t.Fatal(err)
	}
	mixed.Envelope.Branch = "main"
	h.infra.branches["main"] = mixed
	bp := compileStage(t, h.paths, "branch-point")
	twinAt(t, h, stepTwin{id: bp.id, label: "branch-point", atSource: "branch_point", branch: "main", at: fakeBranchedFrom})
	twinLine := "twin: stage change-1/branch-point (snapshot " + short(bp.snapshot.ID) + ", bundle %s), pinned at " +
		fakeBranchedFrom + "; 3 nodes"

	t.Run("to the head", func(t *testing.T) {
		h.clab.plan = []byte(`{"dry-run": true, "deployed-lab": false, "lab-name": "fylgja", "added-nodes": [],
			"deleted-nodes": ["e2"], "recreated-nodes": [], "started-nodes": [], "added-links": [],
			"deleted-endpoints": ["e1:eth2_1", "s1:e1-2"], "restarted-nodes": ["e1"], "node-change-reasons": {"e1": "deleted endpoint"}}`)
		out := runStepCmd(t, "--stage", "change-1/head", "--dry-run", "--allow-restart")
		skipped := findings.Finding{Severity: findings.Warning, Rule: findings.RuleStepStageSkipped, Object: "change-1/head",
			Step: findings.StepResolve, Message: "the step from change-1/branch-point to change-1/head skips stages sealed, linked, " +
				"again, less; the step is between the two bundles either way"}
		if out.code != findings.ExitOK || !slices.Contains(out.doc.Findings, skipped) || out.doc.Findings.Rejected() {
			t.Errorf("exit %d, findings %+v; want 0 beside %+v", out.code, out.doc.Findings, skipped)
		}
		for i, line := range []string{fmt.Sprintf(twinLine, short(bp.id)), "stage change-1/head: branch change-1 at " + stepHeadAt + " (head)"} {
			if got := lineOf(out.stdout, i+2); got != line {
				t.Errorf("stdout line %d %q, want %q:\n%s", i+2, got, line, out.stdout)
			}
		}
		if !strings.HasPrefix(lineOf(out.stdout, 4), "step change-1/branch-point → change-1/head (") ||
			!strings.Contains(out.stdout, "\nverdict: clear\n") {
			t.Errorf("stdout:\n%s\nwant the step from the branch point to the head, clear", out.stdout)
		}
	})
	t.Run("with no target", func(t *testing.T) {
		h.clab.plan = []byte(`{"dry-run": true, "deployed-lab": false, "lab-name": "fylgja", "added-nodes": [], "deleted-nodes": [],
			"recreated-nodes": [], "started-nodes": [], "added-links": [], "deleted-endpoints": [], "restarted-nodes": []}`)
		out := runStepCmd(t, "--dry-run")
		if out.code != findings.ExitOK || out.doc.Subject.Stage != "change-1/sealed" || carriesRule(out.doc.Findings, findings.RuleStepStageSkipped) ||
			!strings.HasPrefix(lineOf(out.stdout, 4), "step change-1/branch-point → change-1/sealed (") {
			t.Errorf("exit %d, subject %+v, findings %+v, stdout:\n%s\nwant 0, the step to sealed skipping none",
				out.code, out.doc.Subject, out.doc.Findings, out.stdout)
		}
	})
}

// A target is the twin's own stage when it resolves to the record's branch and at, whatever
// its label: another mark whose as_of is the record's at, and the head while it is where the
// twin was built, are each refused as current; and so is the next stage when none is
// given, which that other mark is, before the from bundle, the host check and
// containerlab's plan.
func TestStepTargetCurrentByResolvedReference(t *testing.T) {
	twinMark := func(_ *testing.T, h *stepHostFixture) {
		h.infra.changes[0].Stages = append(h.infra.changes[0].Stages, mark("st-twin", "twin", stepMixedAt, ""))
	}
	for _, c := range []struct {
		name, ref string
		// next is set when no target is given, ref being the next stage's.
		next    bool
		setup   func(t *testing.T, h *stepHostFixture)
		message string
	}{
		{name: "another mark at the twin's at", ref: "change-1/twin", setup: twinMark,
			message: "the twin is already at stage change-1/twin (branch change-1, at " + stepMixedAt + "); the proposed change's " +
				"stages are: branch-point, sealed, twin, linked, again, less, head"},
		{name: "the next stage at the twin's at", ref: "change-1/twin", next: true, setup: twinMark,
			message: "the twin is already at stage change-1/twin (branch change-1, at " + stepMixedAt + "); the proposed change's " +
				"stages are: branch-point, sealed, twin, linked, again, less, head"},
		{name: "the head where the twin was built", ref: "change-1/head",
			setup: func(t *testing.T, h *stepHostFixture) {
				twinAt(t, h, stepTwin{id: buildStage(t, h.paths, "head"), label: "head", atSource: "head", branch: "change-1",
					at: stepHeadAt, retired: true})
			},
			message: "the twin is already at stage change-1/head (branch change-1, at " + stepHeadAt + "); the proposed change's " +
				"stages are: " + stepStages},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := stepHost(t, "plan-nothing.json", nil)
			c.setup(t, h)
			h.clab.calls = nil
			args := []string{"--stage", c.ref, "--dry-run"}
			if c.next {
				args = args[2:]
			}
			out := runStepCmd(t, args...)
			want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepTargetCurrent, Object: c.ref,
				Step: findings.StepResolve, Message: c.message}
			if got := refusalOf(t, out.doc); out.code != findings.ExitRejected || got != want {
				t.Errorf("exit %d, refusal %+v\nwant 1, %+v", out.code, got, want)
			}
			onlyInspected(t, c.name, h.clab)
		})
	}
}

// Scenario 6: a twin built at the head, the branch written since: stage list warns that the
// record's stage has moved, a step with no target is refused naming the moved head and the
// reference that steps to it, and --stage <branch>/head is a target, not the current stage,
// since it now resolves to another at; the step, dry run and run alike, carries stage
// list's stage.twin.moved once, in its words, and steps.
func TestStepToAMovedHead(t *testing.T) {
	h, old, moved := movedHeadHost(t)

	code, doc, raw := stageDoc(t, "list", "--branch", "change-1")
	if code != findings.ExitOK || !slices.Contains(doc.Findings, moved) {
		t.Errorf("stage list: exit %d, findings %+v; want 0 beside %+v\n%s", code, doc.Findings, moved, raw)
	}

	out := runStepCmd(t, "--dry-run")
	if got := refusalOf(t, out.doc); out.code != findings.ExitRejected || got.Rule != findings.RuleStepTargetUnknown ||
		!strings.HasSuffix(got.Message, "; the head has moved since the twin was built (now at "+stepHeadAt+"): --stage change-1/head steps to it") {
		t.Errorf("with no target: exit %d, refusal %+v; want step.target.unknown naming the moved head", out.code, got)
	}

	h.clab.plan = []byte(movedHeadPlan)
	out = runStepCmd(t, "--stage", "change-1/head", "--dry-run", "--allow-restart")
	if out.code != findings.ExitOK || out.doc.Findings.Rejected() || out.doc.BundleID == old.id ||
		lineOf(out.stdout, 3) != "stage change-1/head: branch change-1 at "+stepHeadAt+" (head)" ||
		!strings.HasPrefix(lineOf(out.stdout, 4), "step change-1/head → change-1/head ("+short(old.id)+" → ") {
		t.Errorf("--stage change-1/head: exit %d, findings %+v, stdout:\n%s\nwant 0, the step from the head as built to the "+
			"head as it is", out.code, out.doc.Findings, out.stdout)
	}
	movedOnce(t, "the dry run", out, moved)

	svc := &fakeService{runID: stepRunID, events: stepEvents()}
	reconcile, e1Took := 3.9, 1.6
	svc.stepResult = provision.StepResult{Outcome: provision.StepStepped, Findings: findings.List{},
		PushPlan: []wire.StepPush{{Node: "e1", Reasons: []string{"artifact", "restarted"}, Outcome: wire.PushLanded, TookS: &e1Took}},
		Timings: wire.StepTimings{ReconcileS: &reconcile, Readiness: map[string]float64{"e1": 54.8},
			Push: map[string]float64{"e1": 1.6}, WholeS: 62.5},
		Record:    &wire.TwinRecord{State: wire.StateReady},
		StartedAt: "2026-10-02T09:14:30Z", EndedAt: "2026-10-02T09:15:33Z"}
	useService(t, svc)
	useInterrupts(t)
	out = runStepCmd(t, "--stage", "change-1/head", "--allow-restart")
	if l := lines2(out.stdout); out.code != findings.ExitOK || len(svc.stepped) == 0 || len(l) == 0 ||
		!strings.HasPrefix(l[len(l)-1], "stepped to stage change-1/head (bundle ") {
		t.Errorf("the run: exit %d, stdout:\n%s\nwant 0 and the step to the head as it is", out.code, out.stdout)
	}
	movedOnce(t, "the run", out, moved)
}

// movedHeadPlan is containerlab's plan for the step from the head as built, with e2, to the
// head as it is, with e2 retired.
const movedHeadPlan = `{"dry-run": true, "deployed-lab": false, "lab-name": "fylgja", "added-nodes": [],
	"deleted-nodes": ["e2"], "recreated-nodes": [], "started-nodes": [], "added-links": [],
	"deleted-endpoints": ["e1:eth2_1", "s1:e1-2"], "restarted-nodes": ["e1"], "node-change-reasons": {"e1": "deleted endpoint"}}`

// movedHeadHost is stepHost's host with its twin built at the head of change-1 before the
// branch's last write, the head since written: the host, the twin's compiled head, and the
// stage.twin.moved stage list files for it.
func movedHeadHost(t *testing.T) (*stepHostFixture, compiledStage, findings.Finding) {
	t.Helper()
	const oldHead = "2026-10-16T10:30:00.000001+00:00"
	h := stepHost(t, "plan-nothing.json", nil)
	versions := h.infra.versions["change-1"]
	h.infra.versions["change-1"] = versions[:3]
	old := compileStage(t, h.paths, "head")
	twinAt(t, h, stepTwin{id: old.id, label: "head", atSource: "head", branch: "change-1", at: oldHead})
	h.infra.versions["change-1"] = versions
	moved := findings.Finding{Severity: findings.Warning, Rule: findings.RuleStageTwinMoved, Object: "change-1/head",
		Message: "the twin was built from stage change-1/head at branch change-1, at " + oldHead + " (head); change-1/head now " +
			"resolves to branch change-1, at " + stepHeadAt + " (head); the twin is pinned to what it was built from"}
	return h, old, moved
}

// movedOnce fails unless the step's document carries moved exactly once and its text says
// it exactly once.
func movedOnce(t *testing.T, label string, out stepOutput, moved findings.Finding) {
	t.Helper()
	var got findings.List
	for _, f := range out.doc.Findings {
		if f.Rule == findings.RuleStageTwinMoved {
			got = append(got, f)
		}
	}
	line := "warning stage.twin.moved change-1/head: " + moved.Message + "\n"
	if !slices.Equal(got, findings.List{moved}) || strings.Count(out.stdout+out.stderr, line) != 1 {
		t.Errorf("%s: stage.twin.moved %+v, stdout:\n%s\nstderr:\n%s\nwant stage list's %+v once, in both renderings",
			label, got, out.stdout, out.stderr, moved)
	}
}

// Every document twin step ends with once its target is chosen carries the warnings found
// by then, a failure's as well as a refusal's: a twin at the head after the head moved,
// stepped to the head as it is, whose step fails reading the from bundle, at the host check
// or at the run's start, carries the one stage.twin.moved before its operation.failed; one
// refused on a path whose document is built from the command's findings (the store emptied
// of the from bundle, the host's memory) carries it once too.
func TestStepFailureCarriesTheMovedStage(t *testing.T) {
	for _, c := range []struct {
		name string
		// setup breaks the step; the run is a dry run unless run is set.
		setup func(t *testing.T, h *stepHostFixture, old compiledStage)
		run   bool
		code  int
		rule  string
		step  string
	}{
		{name: "the store cannot inspect the from bundle", code: findings.ExitError, rule: findings.RuleOperationFailed,
			step: findings.StepResolve, setup: func(t *testing.T, h *stepHostFixture, old compiledStage) {
				dir := filepath.Join(h.paths.Bundles, old.id)
				if err := os.RemoveAll(dir); err != nil {
					t.Fatal(err)
				}
				if err := os.Symlink(dir, dir); err != nil {
					t.Fatal(err)
				}
			}},
		{name: "the from bundle cannot be read", code: findings.ExitError, rule: findings.RuleOperationFailed,
			step: findings.StepResolve, setup: func(t *testing.T, h *stepHostFixture, old compiledStage) {
				if err := os.Symlink("manifest.json", filepath.Join(h.paths.Bundles, old.id, "manifest.link")); err != nil {
					t.Fatal(err)
				}
			}},
		{name: "the host check cannot run", code: findings.ExitError, rule: findings.RuleOperationFailed,
			step: findings.StepHostCheck, setup: func(t *testing.T, _ *stepHostFixture, _ compiledStage) {
				t.Setenv(lab.EnvHostMemoryMB, "lots")
			}},
		{name: "the run's start fails", run: true, code: findings.ExitError, rule: findings.RuleOperationFailed,
			step: findings.StepStart, setup: func(t *testing.T, _ *stepHostFixture, _ compiledStage) {
				useInterrupts(t)
				useService(t, &fakeService{startErr: errors.New("the workflow service's client could not start the run")})
			}},
		{name: "the store emptied of the from bundle", code: findings.ExitRejected, rule: findings.RuleStepBundleMissing,
			step: findings.StepResolve, setup: func(t *testing.T, h *stepHostFixture, old compiledStage) {
				if err := os.RemoveAll(filepath.Join(h.paths.Bundles, old.id)); err != nil {
					t.Fatal(err)
				}
			}},
		// The head as it is runs two nodes, e2 retired.
		{name: "the host's memory", run: true, code: findings.ExitRejected, rule: findings.RuleHostMemoryExceeded,
			step: findings.StepHostCheck, setup: func(t *testing.T, _ *stepHostFixture, _ compiledStage) {
				t.Setenv(lab.EnvHostMemoryMB, "2048")
			}},
	} {
		t.Run(c.name, func(t *testing.T) {
			h, old, moved := movedHeadHost(t)
			h.clab.plan = []byte(movedHeadPlan)
			c.setup(t, h, old)
			args := []string{"--stage", "change-1/head", "--allow-restart"}
			if !c.run {
				args = append(args, "--dry-run")
			}
			out := runStepCmd(t, args...)
			got := refusalOf(t, out.doc)
			if out.code != c.code || got.Rule != c.rule || got.Step != c.step {
				t.Errorf("exit %d, refusal %+v; want %d, %s at %s", out.code, got, c.code, c.rule, c.step)
			}
			movedOnce(t, c.name, out, moved)
			if i, j := slices.Index(out.doc.Findings, moved), slices.Index(out.doc.Findings, got); i > j {
				t.Errorf("findings %+v; want stage.twin.moved before the %s it was found before", out.doc.Findings, got.Rule)
			}
			if out.doc.Stage == nil || out.doc.Stage.Label != "head" {
				t.Errorf("stage block %+v; want the target's, change-1/head", out.doc.Stage)
			}
		})
	}
}

// Scenario 8, for a step: a target marked before its artifacts were regenerated is refused
// as stale at resolution, given or chosen as the next stage, with the findings stage plan
// gives it, before it is read and before anything of the step: no service is dialled and
// containerlab is asked for nothing but the host's state.
func TestStepToAStaleStageIsRefused(t *testing.T) {
	h := stepHost(t, "plan-link-added.json", nil)
	h.infra.stamps = map[string]fakeDeviceStamps{
		"change-1/e1": {Intent: "2026-10-16T09:45:00.000000+00:00", Artifact: "2026-10-16T09:30:00.000000+00:00"},
	}
	_, doc, raw := stageDoc(t, "plan", "--branch", "change-1")
	stages, _ := planned(t, doc)
	i := slices.IndexFunc(stages, func(st findings.PlanStage) bool { return st.Label == "linked" })
	if i < 0 || stages[i].BundleID != nil || !slices.Equal(rulesOf(stages[i].Findings), []string{findings.RuleStageArtifactStale + " e1"}) {
		t.Fatalf("stage plan did not refuse change-1/linked stale for e1\n%s", raw)
	}
	want := stages[i].Findings
	before := len(h.infra.requests())
	h.clab.calls = nil
	for _, args := range [][]string{{"--stage", "change-1/linked"}, {}} {
		out := runStepCmd(t, append(args, "--allow-restart")...)
		if out.code != findings.ExitRejected || !reflect.DeepEqual(out.doc.Findings, want) || out.doc.Step != nil {
			t.Errorf("%v: exit %d, findings %+v, step %+v\nwant 1, stage plan's %+v, and no step", args, out.code,
				out.doc.Findings, out.doc.Step, want)
		}
	}
	onlyInspected(t, "a stale target", h.clab)
	if got := intentReadAfter(h.infra, before); len(got) != 0 {
		t.Errorf("the stale target was read: %+v", got)
	}
}

// A step names each side's snapshot (018; R-13, R-09). From a 9 record of stage sealed to
// stage again, the twin line names the record's snapshot, the run's input names sealed's on
// its from side and the one the target's build took on its to side, which the document names
// beside the target's bundle; the record NewStepRecord builds from that input names the
// target's at its top level once the step moves the twin, and both in its step, while a
// diverged step keeps the record's own. A record of 8, which names none and which 018 let
// step, is refused before Infrahub is asked, the dry run's included (019, research R-03).
func TestStepNamesEachSidesSnapshot(t *testing.T) {
	t.Run("from a 9 record", func(t *testing.T) {
		h := stepHost(t, "plan-nothing.json", nil)
		svc := &fakeService{runID: stepRunID, events: unchangedStepEvents()}
		useService(t, svc)
		useInterrupts(t)
		svc.stepResult = provision.StepResult{Outcome: provision.StepUnchanged, PushPlan: []wire.StepPush{},
			Timings: wire.StepTimings{WholeS: 1.8}, Record: &wire.TwinRecord{State: wire.StateReady}, Findings: findings.List{},
			StartedAt: "2026-10-02T09:14:30Z", EndedAt: "2026-10-02T09:14:32Z"}

		out := runStepCmd(t, "--stage", "change-1/again")
		if out.code != findings.ExitOK || len(svc.stepped) != 2 {
			t.Fatalf("exit %d, %d runs started; want 0 and one per run of the command: %+v", out.code, len(svc.stepped), out.doc.Findings)
		}
		in := svc.stepped[1]
		if want := "twin: stage change-1/sealed (snapshot " + short(h.fromSnapshot) + ", bundle " + short(h.fromID) + "), pinned at " +
			stepMixedAt + "; 3 nodes"; lineOf(out.stdout, 1) != want {
			t.Errorf("the twin line %q, want %q", lineOf(out.stdout, 1), want)
		}
		if in.From.SnapshotID != h.fromSnapshot || !snap.IsID(in.To.SnapshotID) || in.To.SnapshotID == h.fromSnapshot ||
			in.To.SnapshotID != snapshotOfTarget(t, h, in.To.BundleID) {
			t.Errorf("the input's sides name snapshots %q → %q; want the record's %s, then the target's", in.From.SnapshotID,
				in.To.SnapshotID, h.fromSnapshot)
		}
		if st := out.doc.Step; out.doc.SnapshotID != in.To.SnapshotID || out.doc.BundleID != in.To.BundleID || st == nil ||
			st.From.SnapshotID != h.fromSnapshot || st.To.SnapshotID != in.To.SnapshotID {
			t.Errorf("the document names snapshot %q and step %+v; want the target's beside its bundle, and both sides'",
				out.doc.SnapshotID, st)
		}

		prev, err := lab.ReadRecord(h.paths.TwinJSON)
		if err != nil {
			t.Fatal(err)
		}
		moved, err := lab.NewStepRecord(prev, recordedStep(prev, in, wire.StepUnchanged))
		if err != nil {
			t.Fatal(err)
		}
		if moved.SnapshotID == nil || *moved.SnapshotID != in.To.SnapshotID || moved.Step == nil ||
			moved.Step.From.SnapshotID != h.fromSnapshot || moved.Step.To.SnapshotID != in.To.SnapshotID {
			t.Errorf("the record after the step names snapshot %v and step %+v; want the target's, and both sides'",
				moved.SnapshotID, moved.Step)
		}
		diverged, err := lab.NewStepRecord(prev, recordedStep(prev, in, wire.StepDiverged))
		if err != nil {
			t.Fatal(err)
		}
		if diverged.SnapshotID == nil || *diverged.SnapshotID != h.fromSnapshot || diverged.Step == nil ||
			diverged.Step.From.SnapshotID != h.fromSnapshot || diverged.Step.To.SnapshotID != in.To.SnapshotID {
			t.Errorf("the record after a diverged step names snapshot %v and step %+v; want the record's own, and both sides'",
				diverged.SnapshotID, diverged.Step)
		}
	})

	t.Run("from an 8 record, refused", func(t *testing.T) {
		h := editedRecordHost(t, func(m map[string]any) {
			m["twin_version"] = "8"
			unsnapshotted(m)
		})
		out := runStepCmd(t, "--dry-run", "--allow-restart")
		want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepTwinUnsteppable, Step: findings.StepResolve,
			Object: h.fromID, Message: "the twin was created from a record version that names no snapshot (twin.json 8); only a " +
				"twin whose record names a snapshot steps; fylgja twin destroy clears it"}
		if got := refusalOf(t, out.doc); out.code != findings.ExitRejected || got != want || out.doc.Step != nil {
			t.Errorf("exit %d, refusal %+v, step %+v; want 1 with %+v and no step", out.code, got, out.doc.Step, want)
		}
		if len(h.infra.requests()) != h.before {
			t.Errorf("Infrahub was asked %+v after the host was built", h.infra.requests()[h.before:])
		}
	})
}

// snapshotOfTarget is the snapshot the step's build of its target filed: the one entry of
// snapshots/ that is not the from side's, whose bundle is bundleID.
func snapshotOfTarget(t *testing.T, h *stepHostFixture, bundleID string) string {
	t.Helper()
	var found []string
	for _, name := range filedSnapshots(t, h.paths) {
		if id := strings.TrimSuffix(name, ".json"); id != h.fromSnapshot {
			found = append(found, id)
		}
	}
	if len(found) != 1 || !slices.Contains(storedBundles(t, h.paths.Bundles), bundleID) {
		t.Fatalf("snapshots/ holds %v beside the from side's, and bundles/ %v; want the target's one snapshot and bundle %s",
			found, storedBundles(t, h.paths.Bundles), bundleID)
	}
	return found[0]
}

// recordedStep is what the step's record activity hands NewStepRecord for a step of in from
// prev ending outcome: an unchanged step with the target staged and every node of prev
// running, or a diverged one at its push, with nothing staged and nothing landed.
func recordedStep(prev wire.TwinRecord, in provision.StepInput, outcome string) lab.StepFields {
	f := lab.StepFields{Outcome: outcome, From: in.From, To: in.To, ObservedAt: in.ObservedAt, RunID: stepRunID,
		Version: version, Pushed: []wire.StepPush{}, StartedAt: "2026-10-02T09:14:30Z", EndedAt: "2026-10-02T09:14:32Z",
		RecordedAt: time.Date(2026, 10, 2, 9, 14, 32, 0, time.UTC)}
	if outcome == wire.StepDiverged {
		f.Phase = findings.StepPush
		return f
	}
	provenance := prev.Provenance
	provenance.At = in.To.At
	f.Staged = &lab.StagedTarget{BundleID: in.To.BundleID, Provenance: provenance, PSP: map[string]wire.PSPRef{}}
	for _, n := range prev.Nodes {
		f.Nodes = append(f.Nodes, wire.LabNode{Name: n.Name, Container: n.Container, Image: n.Image, State: "running",
			MgmtIPv4: n.MgmtIPv4})
		f.Staged.PSP[n.Name] = *n.PSP
	}
	return f
}

// 019, US2: twin step --snapshot <id|file> steps any twin whose record names a snapshot to a
// snapshot of any branch (research R-04). The client sends it as twin create sends one; the
// server resolves it as create's --snapshot does, compiles and files its bundle, and steps
// to it as to a stage, with no request to Infrahub for the target.

// --stage beside --snapshot is the server's snapshot.flags.conflict at start, exit 2, naming
// --stage: the snapshot is the target (US3 scenario 6). It is refused before any connection,
// whether --snapshot is an id, a file, a file not there or given empty, and whatever --stage
// says: the client reads no file beside --stage, so the guard answers whatever the file, and
// nothing is filed, dialled, inspected or asked of Infrahub.
func TestStepSnapshotBesideAStageIsRefused(t *testing.T) {
	want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleSnapshotFlagsConflict, Step: findings.StepStart,
		Object: "--stage", Message: "--stage is meaningless with --snapshot: the snapshot is the target"}
	file := snapshotFile(t, nil)
	missing := filepath.Join(t.TempDir(), "typo.json")
	for _, stage := range []string{"--stage=change-1/linked", "--stage="} {
		for _, g := range []struct{ name, arg string }{
			{"an id", fixtureSnapshotID}, {"a file", file}, {"a file not there", missing}, {"--snapshot=", ""},
		} {
			t.Run(stage+" beside "+g.name, func(t *testing.T) {
				h := stepHost(t, "plan-link-added.json", nil)
				h.clab.calls = nil
				snapshots := filedSnapshots(t, h.paths)
				dials := countDials(t)
				awaitIdle(t)
				served := servedRequests(findings.OpTwinStep, string(findings.StatusError))

				code, doc, raw := executeClient(t, "twin", "step", "--snapshot="+g.arg, stage)
				if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0] != want || doc.Subject.Snapshot != g.arg {
					t.Errorf("exit %d, findings %+v, subject %+v; want 2 with %+v alone", code, doc.Findings, doc.Subject, want)
				}
				if n := dials.Load(); n != 0 || len(h.infra.requests()) != h.before || len(h.clab.calls) != 0 {
					t.Errorf("dialled %d times, asked Infrahub %+v and containerlab %v before the refusal", n,
						h.infra.requests()[h.before:], h.clab.calls)
				}
				awaitIdle(t)
				if got := servedRequests(findings.OpTwinStep, string(findings.StatusError)) - served; got != 1 {
					t.Errorf("the server logged %d refused steps, want 1: the refusal is the server's", got)
				}
				if got := filedSnapshots(t, h.paths); !slices.Equal(got, snapshots) {
					t.Errorf("snapshots/ holds %v after a refusal before any connection, held %v", got, snapshots)
				}
				validateM10Document(t, doc)
				mustCarryNoToken(t, stage, raw)
			})
		}
	}
}

// A --snapshot the client cannot send is its own operation.failed, exit 2, as on create, and
// no request reaches the server: a file it cannot read, worded as the operating system words
// it, and an explicit empty --snapshot= with no --stage beside it, which names no file.
func TestStepSnapshotTheClientCannotSend(t *testing.T) {
	missing := filepath.Join(t.TempDir(), "absent.json")
	for _, c := range []struct {
		name, arg, message string
	}{
		{"a file not there", missing, "reading snapshot: open " + missing + ": no such file or directory"},
		{"--snapshot=", "", "--snapshot= is empty; give a snapshot id or the path of a snapshot file"},
	} {
		t.Run(c.name, func(t *testing.T) {
			useStateRoot(t)
			dials := countDials(t)
			awaitIdle(t)
			before := strings.Count(harness.log.String(), "operation="+findings.OpTwinStep+" ")

			code, doc, _ := executeClient(t, "twin", "step", "--snapshot="+c.arg, "--dry-run")
			want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleOperationFailed, Object: findings.OpTwinStep,
				Message: c.message}
			if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0] != want || doc.Subject.Snapshot != c.arg {
				t.Errorf("exit %d, findings %+v, subject %+v; want 2 with %+v", code, doc.Findings, doc.Subject, want)
			}
			awaitIdle(t)
			if after := strings.Count(harness.log.String(), "operation="+findings.OpTwinStep+" "); after != before || dials.Load() != 0 {
				t.Errorf("the server logged %d steps and the service was dialled %d times; want none", after-before, dials.Load())
			}
			validateM10Document(t, doc)
		})
	}
}

// A step's files are one snapshot file beside a --snapshot that is a path, under that path,
// or none, as a create's are (contracts/api.md, "019: following removed"): a raw twin.step
// request carrying another is the server's operation.failed, exit 2, naming twin step, before
// any connection, and nothing is filed.
func TestAStepsFilesAreOneSnapshotFile(t *testing.T) {
	one := []api.File{{Path: "snap.json", Data: []byte("{")}}
	for _, c := range []struct {
		name    string
		args    given
		files   []api.File
		message string
	}{
		{"a file beside no --snapshot", given{"dry_run": true}, one,
			"the request carries 1 file where twin step takes a snapshot file beside --snapshot alone"},
		{"a file beside an id", given{"snapshot": fixtureSnapshotID}, one,
			"the request carries 1 file where twin step takes a snapshot file beside --snapshot alone"},
		{"two files", given{"snapshot": "snap.json"}, append(one, api.File{Path: "other.json"}),
			"the request carries 2 files where twin step takes a snapshot file beside --snapshot alone"},
		{"no file beside a path", given{"snapshot": "snap.json"}, nil,
			"the request carries no file where twin step takes the snapshot file --snapshot names, under that path"},
		{"a file under another path", given{"snapshot": "other.json"}, one,
			"the request carries its snapshot file under another path than --snapshot gives, where twin step takes a " +
				"snapshot file beside --snapshot alone, under that path"},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := stepHost(t, "plan-link-added.json", nil)
			h.clab.calls = nil
			snapshots := filedSnapshots(t, h.paths)
			dials := countDials(t)
			var err error
			captureStdout(t, func() { err = send(context.Background(), &options{}, findings.OpTwinStep, c.args, c.files, handlers{}) })
			code, doc := exitOf(t, err)
			want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleOperationFailed, Object: findings.OpTwinStep,
				Message: c.message}
			if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0] != want {
				t.Errorf("exit %d, findings %+v; want 2 with %+v", code, doc.Findings, want)
			}
			if n := dials.Load(); n != 0 || len(h.infra.requests()) != h.before || len(h.clab.calls) != 0 {
				t.Errorf("dialled %d times, asked Infrahub %+v and containerlab %v before the refusal", n,
					h.infra.requests()[h.before:], h.clab.calls)
			}
			if got := filedSnapshots(t, h.paths); !slices.Equal(got, snapshots) {
				t.Errorf("snapshots/ holds %v after the refusal, held %v", got, snapshots)
			}
		})
	}
}

// targetSnapshot files change-1's stage label as a snapshot the operator holds, as a create,
// a plan or intent read --out on this server files one, and returns it, with its bundle's id.
// Infrahub's requests are counted again after it, so h.before is what the step must leave
// unmoved: no request reaches Infrahub for a snapshot target.
func targetSnapshot(t *testing.T, h *stepHostFixture, label string) (*snap.Snapshot, string) {
	t.Helper()
	bundleID := buildStage(t, h.paths, label)
	s, err := snap.NewDirStore(h.paths.Snapshots).Fetch(context.Background(), snapshotOf(t, bundleID))
	if err != nil {
		t.Fatal(err)
	}
	h.before = len(h.infra.requests())
	return s, bundleID
}

// targetFile is the stored snapshot id written to a file of the test's own, edited by edit
// as JSON, the file an operator holds; its entry leaves h's store, so the step files it.
func targetFile(t *testing.T, h *stepHostFixture, id string, edit func(doc map[string]any)) string {
	t.Helper()
	entry := filepath.Join(h.paths.Snapshots, id+".json")
	raw, err := os.ReadFile(entry)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Remove(entry); err != nil {
		t.Fatal(err)
	}
	if edit != nil {
		var doc map[string]any
		if err := json.Unmarshal(raw, &doc); err != nil {
			t.Fatal(err)
		}
		edit(doc)
		if raw, err = json.MarshalIndent(doc, "", "  "); err != nil {
			t.Fatal(err)
		}
	}
	path := filepath.Join(t.TempDir(), "target.json")
	if err := os.WriteFile(path, raw, 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}

// envelopeOf is a snapshot document's CTM envelope, as JSON, for an edit.
func envelopeOf(doc map[string]any) map[string]any {
	return doc["ctm"].(map[string]any)["envelope"].(map[string]any)
}

// recordOnHost is twin.json as the step's record activity writes it once the step of in has
// moved the twin: the target's bundle staged in the twin directory, as the run's stage leaves
// it, every node of the target running, and every push landed. It validates against the
// current contract.
func recordOnHost(t *testing.T, h *stepHostFixture, in provision.StepInput) *wire.TwinRecord {
	t.Helper()
	files, err := bundle.LoadFiles(in.ToBundlePath)
	if err != nil {
		t.Fatal(err)
	}
	for p, b := range files {
		dst := filepath.Join(h.paths.TwinBundle, filepath.FromSlash(p))
		if err := os.MkdirAll(filepath.Dir(dst), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(dst, b, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	var m compiler.Manifest
	if err := json.Unmarshal(files[compiler.ManifestFile], &m); err != nil {
		t.Fatal(err)
	}
	var nodes []wire.LabNode
	for _, n := range m.Nodes {
		nodes = append(nodes, wire.LabNode{Name: n.Name, Container: "clab-fylgja-" + n.Name, Image: n.Image, State: "running"})
	}
	pushed := []wire.StepPush{}
	for _, p := range in.PushPlan {
		pushed = append(pushed, wire.StepPush{Node: p.Node, Reasons: p.Reasons, Outcome: wire.PushLanded})
	}
	acts := &lab.Activities{Paths: h.paths, Version: version}
	if _, err := acts.RecordStep(context.Background(), wire.RecordStepInput{TwinDir: h.paths.Twin, From: in.From, To: in.To,
		Outcome: wire.StepStepped, RunID: stepRunID, ObservedAt: in.ObservedAt, PushPlan: pushed, Nodes: nodes,
		StartedAt: "2026-10-02T09:14:30Z", EndedAt: "2026-10-02T09:15:41Z"}); err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(h.paths.TwinJSON)
	if err != nil {
		t.Fatal(err)
	}
	validateTwinJSON(t, raw)
	rec, err := lab.ReadRecord(h.paths.TwinJSON)
	if err != nil {
		t.Fatal(err)
	}
	return &rec
}

// stepToSnapshotRun is the fake service a step to a snapshot runs on: it replays the step's
// progress and ends stepped, as TestStepRuns' stepped run does.
func stepToSnapshotRun(t *testing.T) *fakeService {
	t.Helper()
	reconcile := 3.9
	e1Took, s1Took := 1.6, 2.4
	svc := &fakeService{runID: stepRunID, events: stepEvents(), stepResult: provision.StepResult{Outcome: provision.StepStepped,
		PushPlan: []wire.StepPush{
			{Node: "e1", Reasons: []string{"artifact", "restarted"}, Outcome: wire.PushLanded, TookS: &e1Took},
			{Node: "s1", Reasons: []string{"artifact", "bootstrap"}, Outcome: wire.PushLanded, TookS: &s1Took}},
		Timings: wire.StepTimings{ReconcileS: &reconcile, Readiness: map[string]float64{"e1": 54.8},
			Push: map[string]float64{"e1": 1.6, "s1": 2.4}, WholeS: 71.2},
		Record: &wire.TwinRecord{State: wire.StateReady}, Findings: findings.List{},
		StartedAt: "2026-10-02T09:14:30Z", EndedAt: "2026-10-02T09:15:41Z"}}
	useService(t, svc)
	useInterrupts(t)
	return svc
}

// stepFroms are the three twins a snapshot steps (US2 scenarios 1–3): one built from
// --branch, unpinned; one from --stage, change-1/sealed; one from --snapshot, pinned. Each
// names sealed's snapshot and bundle.
var stepFroms = []struct {
	name   string
	change func(*lab.RecordFields)
	source string
}{
	{"--branch", func(f *lab.RecordFields) { f.Stage, f.Provenance.At = nil, "" }, wire.SourceIntent},
	{"--stage", nil, wire.SourceIntent},
	{"--snapshot", func(f *lab.RecordFields) { f.Stage, f.Source = nil, wire.SourceSnapshot }, wire.SourceSnapshot},
}

// US2 scenarios 1–3 (FR-012, FR-013): a twin built by each of --branch, --stage and
// --snapshot steps to a snapshot of change-1's stage linked, by its id and by a file. The
// server compiles it and files its bundle, and starts the step run with a to side naming no
// stage, the snapshot, its bundle and the envelope's branch and at, and the stored
// document's observed_at; the fake Infrahub is asked nothing. A file is filed under its id.
// The record the run then writes names the target's snapshot, bundle, branch and at and no
// stage, keeps the twin's source, and validates against twin.json 10; its step block names
// the from side's stage, from a stage twin, and none on its to side.
func TestStepToASnapshot(t *testing.T) {
	for _, from := range stepFroms {
		for _, by := range []string{"id", "file"} {
			t.Run("from "+from.name+" by "+by, func(t *testing.T) {
				h := stepHost(t, "plan-link-added.json", from.change)
				target, toID := targetSnapshot(t, h, "linked")
				env := target.CTM.Envelope
				arg := target.ID
				if by == "file" {
					arg = targetFile(t, h, target.ID, nil)
				}
				svc := stepToSnapshotRun(t)

				out := runStepCmd(t, "--snapshot", arg, "--allow-restart")
				if out.code != findings.ExitOK || len(svc.stepped) != 2 {
					t.Fatalf("exit %d, %d runs started; want 0 and one per run of the command: %+v", out.code, len(svc.stepped),
						out.doc.Findings)
				}
				if n := len(h.infra.requests()); n != h.before {
					t.Errorf("Infrahub was asked %+v for a snapshot target", h.infra.requests()[h.before:])
				}
				if got := filedSnapshots(t, h.paths); !slices.Contains(got, target.ID+".json") {
					t.Errorf("snapshots/ holds %v; want the target filed under its id", got)
				}
				prev, err := lab.ReadRecord(h.paths.TwinJSON)
				if err != nil {
					t.Fatal(err)
				}
				wantFrom := wire.StepSide{Stage: prev.Stage, SnapshotID: h.fromSnapshot, BundleID: h.fromID, At: prev.Provenance.At}
				wantTo := wire.StepSide{SnapshotID: target.ID, BundleID: toID, At: env.At, Branch: env.Branch}
				for i, in := range svc.stepped {
					if !reflect.DeepEqual(in.From, wantFrom) || !reflect.DeepEqual(in.To, wantTo) ||
						in.ObservedAt != target.ObservedAt || in.ToBundlePath != filepath.Join(h.paths.Bundles, toID) {
						t.Errorf("run %d's input %+v → %+v, observed at %s; want %+v → %+v, observed at %s", i, in.From, in.To,
							in.ObservedAt, wantFrom, wantTo, target.ObservedAt)
					}
				}
				doc := out.doc
				if doc.SnapshotID != target.ID || doc.BundleID != toID || doc.Stage != nil || doc.Subject.Snapshot != arg ||
					doc.Subject.Branch != env.Branch || doc.Subject.At != env.At || doc.Subject.Stage != "" ||
					doc.Subject.Scope != "tag:fylgja" {
					t.Errorf("document names snapshot %s, bundle %s, stage %+v, subject %+v; want the target's, no stage, "+
						"the snapshot as given", doc.SnapshotID, doc.BundleID, doc.Stage, doc.Subject)
				}
				if st := doc.Step; st == nil || (st.From.Stage != nil) != (prev.Stage != nil) || st.To.Stage != nil ||
					st.To.SnapshotID != target.ID || st.From.SnapshotID != h.fromSnapshot {
					t.Errorf("step block %+v; want the record's side and the target's, which names no stage", st)
				}

				rec := recordOnHost(t, h, svc.stepped[1])
				if rec.SnapshotID == nil || *rec.SnapshotID != target.ID || rec.BundleID != toID || rec.Stage != nil ||
					rec.Provenance.Branch != env.Branch || rec.Provenance.At != env.At || rec.Source != from.source ||
					rec.State != wire.StateReady || rec.TwinVersion != lab.TwinVersion {
					t.Errorf("the record after the step %+v; want snapshot %s, bundle %s, branch %s at %s, no stage, source %s",
						rec, target.ID, toID, env.Branch, env.At, from.source)
				}
				if st := rec.Step; st == nil || st.To.Stage != nil || (st.From.Stage != nil) != (prev.Stage != nil) {
					t.Errorf("the record's step %+v; want the from side's stage, if any, and none on the to side", st)
				}
			})
		}
	}
}

// US2 scenarios 4, 5 and 7, and the edges: each refusal of a snapshot target is the server's,
// before any run, and touches neither the twin nor Infrahub. A bundle twin is refused naming
// no snapshot; an id the store does not hold is snapshot.unknown naming the id; a file is
// refused by its own rules as on create, snapshot.id.mismatch naming both ids among them, and
// one breaking the CTM's own rules at compile, filed nowhere; a compile refused once the file
// is filed, a platform no package matches, at compile, the snapshot left filed; and a diverged
// twin as diverged, before the snapshot is read.
func TestStepToASnapshotRefused(t *testing.T) {
	refusal := func(rule, step, object, message string) findings.Finding {
		return findings.Finding{Severity: findings.Rejection, Rule: rule, Step: step, Object: object, Message: message}
	}
	unknown := strings.Repeat("0", 64)
	declared := strings.Repeat("1", 64)
	for _, c := range []struct {
		name string
		host func(t *testing.T) *stepHostFixture
		// arg is --snapshot's value, from the linked target and h; want's "" object or
		// message is filled by fill.
		arg  func(t *testing.T, h *stepHostFixture, target *snap.Snapshot) string
		want findings.Finding
		fill func(h *stepHostFixture, target *snap.Snapshot, arg string, f *findings.Finding)
	}{
		{name: "a twin of a bundle", host: func(t *testing.T) *stepHostFixture {
			return stepHost(t, "plan-link-added.json", func(f *lab.RecordFields) {
				f.Stage, f.Source, f.ObservedAt, f.Provenance.At, f.SnapshotID = nil, wire.SourceBundle, nil, "", ""
			})
		}, want: refusal(findings.RuleStepTwinUnsteppable, findings.StepResolve, "", "the twin was provisioned from a bundle, "+
			"which names no snapshot; only a twin whose record names a snapshot steps; fylgja twin destroy clears it"),
			fill: func(h *stepHostFixture, _ *snap.Snapshot, _ string, f *findings.Finding) { f.Object = h.fromID }},
		{name: "a diverged twin", host: divergedStepHost, want: divergedRefusal(""),
			fill: func(h *stepHostFixture, _ *snap.Snapshot, _ string, f *findings.Finding) { f.Object = h.fromID }},
		{name: "an id the store does not hold",
			arg:  func(*testing.T, *stepHostFixture, *snap.Snapshot) string { return unknown },
			want: refusal(findings.RuleSnapshotUnknown, findings.StepResolve, unknown, ""),
			fill: func(h *stepHostFixture, _ *snap.Snapshot, _ string, f *findings.Finding) {
				f.Message = "the store under " + h.paths.Snapshots + " holds no snapshot " + unknown + "; a snapshot id comes " +
					"from a create, a dry run, a plan or intent read --out on this server"
			}},
		{name: "a file declaring another id", arg: func(t *testing.T, h *stepHostFixture, target *snap.Snapshot) string {
			return targetFile(t, h, target.ID, func(d map[string]any) { d["snapshot_id"] = declared })
		}, want: refusal(findings.RuleSnapshotIDMismatch, findings.StepResolve, "", ""),
			fill: func(_ *stepHostFixture, target *snap.Snapshot, arg string, f *findings.Finding) {
				f.Object = arg
				f.Message = arg + " declares snapshot_id " + declared + ", but its body hashes to " + target.ID +
					"; leave snapshot_id out to have it computed"
			}},
		{name: "a file of another snapshot version", arg: func(t *testing.T, h *stepHostFixture, target *snap.Snapshot) string {
			return targetFile(t, h, target.ID, func(d map[string]any) { d["snapshot_version"] = "3" })
		}, want: refusal(findings.RuleSnapshotVersionUnsupported, findings.StepResolve, "",
			`the snapshot declares snapshot_version "3"; this build reads "1" and "2", and nothing converts one`),
			fill: func(_ *stepHostFixture, _ *snap.Snapshot, arg string, f *findings.Finding) { f.Object = arg }},
		{name: "a file with a probe not the contract's", arg: func(t *testing.T, h *stepHostFixture, target *snap.Snapshot) string {
			return targetFile(t, h, target.ID, func(d map[string]any) { d["probes"] = []any{map[string]any{}} })
		}, want: refusal(findings.RuleSnapshotInvalid, findings.StepResolve, "probes[0].name", "")},
		{name: "a file breaking the CTM's own rules", arg: func(t *testing.T, h *stepHostFixture, target *snap.Snapshot) string {
			return targetFile(t, h, target.ID, func(d map[string]any) {
				delete(d, "snapshot_id")
				envelopeOf(d)["branch"] = ""
			})
		}, want: refusal(findings.RuleRequiredMissing, findings.StepCompile, "envelope.branch",
			"the branch intent was read from is not recorded")},
		{name: "a compile refused", arg: func(t *testing.T, h *stepHostFixture, target *snap.Snapshot) string {
			return targetFile(t, h, target.ID, func(d map[string]any) {
				delete(d, "snapshot_id")
				d["ctm"].(map[string]any)["devices"].([]any)[0].(map[string]any)["platform"].(map[string]any)["package"] = "nosuch"
			})
		}, want: refusal(findings.RulePlatformUnsupported, findings.StepCompile, "", "")},
	} {
		t.Run(c.name, func(t *testing.T) {
			host := c.host
			if host == nil {
				host = func(t *testing.T) *stepHostFixture { return stepHost(t, "plan-link-added.json", nil) }
			}
			h := host(t)
			target, _ := targetSnapshot(t, h, "linked")
			arg := target.ID
			if c.arg != nil {
				arg = c.arg(t, h, target)
			}
			record := sha256Of(t, h.paths.TwinJSON)
			snapshots := filedSnapshots(t, h.paths)
			want := c.want
			if c.fill != nil {
				c.fill(h, target, arg, &want)
			}

			out := runStepCmd(t, "--snapshot", arg, "--allow-restart")
			got := refusalOf(t, out.doc)
			if want.Message == "" {
				want.Message = got.Message
			}
			if want.Object == "" {
				want.Object = got.Object
			}
			if out.code != findings.ExitRejected || got != want {
				t.Errorf("exit %d, refusal %+v\nwant exit 1, %+v", out.code, got, want)
			}
			if len(h.svc.stepped) != 0 || len(h.infra.requests()) != h.before {
				t.Errorf("%d runs started and Infrahub asked %+v; want neither", len(h.svc.stepped), h.infra.requests()[h.before:])
			}
			if plans := h.clab.asked("clab", "deploy"); len(plans) != 0 {
				t.Errorf("containerlab's plan was read: %v", plans)
			}
			if sha256Of(t, h.paths.TwinJSON) != record {
				t.Errorf("twin.json changed under a refusal")
			}
			// The store keeps every entry it held, and gains the file's only once the file's own
			// rules and the CTM's passed: a compile refused after that leaves it filed and names
			// it, in the document and by its stored line.
			filed := slices.DeleteFunc(filedSnapshots(t, h.paths), func(e string) bool { return slices.Contains(snapshots, e) })
			if c.name != "a compile refused" {
				if len(filed) != 0 || out.doc.SnapshotID != "" {
					t.Errorf("snapshots/ gained %v and the document names snapshot %q; want neither", filed, out.doc.SnapshotID)
				}
				return
			}
			if len(filed) != 1 || out.doc.SnapshotID+".json" != filed[0] ||
				!strings.Contains(out.stdout, storedLines(h.paths, out.doc.SnapshotID, "")[0]+"\n") {
				t.Errorf("snapshots/ gained %v, the document names snapshot %q, stdout:\n%s\nwant the file's snapshot filed and named",
					filed, out.doc.SnapshotID, out.stdout)
			}
		})
	}
}

// US4 scenarios 1, 2 and 4 (FR-015; research R-06): a twin's scope and mapping are fixed
// when it is created. A snapshot target whose envelope names another scope, or another
// mapping version, is refused step.twin.unsteppable before any run, its object the
// snapshot's id, naming the record's and the target's, by a file and then by the id it was
// filed under, the dry run's included: the snapshot stays filed and is named, no bundle is
// filed, Infrahub is asked nothing and twin.json is unchanged. A stage target is judged on its
// bundle's manifest after its build: against a record whose mapping version differs it is
// refused the same way, its object the stage's reference, before the host check and
// containerlab's plan; and a stage or a snapshot under the record's scope and mapping passes
// without a word.
func TestStepTargetKeepsScopeAndMapping(t *testing.T) {
	const dcim = "infrahub-dcim opsmill/schema-library 26336e9"
	const fixed = "; a twin's scope and mapping are fixed when it is created; fylgja twin destroy and create again to change them"
	unheld := func(object, record, target string) findings.Finding {
		return findings.Finding{Severity: findings.Rejection, Rule: findings.RuleStepTwinUnsteppable, Step: findings.StepResolve,
			Object: object, Message: "the twin's record names " + record + "; " + target + fixed}
	}
	for _, c := range []struct {
		name string
		edit func(env map[string]any)
		// target is what the refusal says the snapshot names, after its name.
		target string
	}{
		{"a snapshot of another scope", func(env map[string]any) { env["scope"] = "tag:other" },
			"names scope tag:other and mapping " + dcim},
		{"a snapshot of another mapping version", func(env map[string]any) { env["mapping"].(map[string]any)["version"] = "0f0f0f0" },
			"names scope tag:fylgja and mapping infrahub-dcim opsmill/schema-library 0f0f0f0"},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := stepHost(t, "plan-link-added.json", nil)
			target, _ := targetSnapshot(t, h, "linked")
			file := targetFile(t, h, target.ID, func(d map[string]any) {
				delete(d, "snapshot_id")
				c.edit(envelopeOf(d))
			})
			record := sha256Of(t, h.paths.TwinJSON)
			bundles := storedBundles(t, h.paths.Bundles)
			var id string
			for _, args := range [][]string{{"--allow-restart"}, {"--dry-run"}, {"--allow-restart"}} {
				arg := file
				if id != "" {
					arg = id
				}
				out := runStepCmd(t, append([]string{"--snapshot", arg}, args...)...)
				id = out.doc.SnapshotID
				if id == "" || id == target.ID {
					t.Fatalf("%v: the document names snapshot %q; want the edited file's own id", args, id)
				}
				want := unheld(id, "scope tag:fylgja and mapping "+dcim, "snapshot "+short(id)+" "+c.target)
				if got := refusalOf(t, out.doc); out.code != findings.ExitRejected || got != want || out.doc.Step != nil {
					t.Errorf("%s %v: exit %d, refusal %+v, step %+v\nwant 1, %+v and no step", arg, args, out.code, got, out.doc.Step, want)
				}
				if !strings.Contains(out.stdout, storedLines(h.paths, id, "")[0]+"\n") {
					t.Errorf("%v: stdout does not name the filed snapshot:\n%s", args, out.stdout)
				}
			}
			if !slices.Contains(filedSnapshots(t, h.paths), id+".json") {
				t.Errorf("snapshots/ holds %v; want the target filed under %s", filedSnapshots(t, h.paths), id)
			}
			if got := storedBundles(t, h.paths.Bundles); !slices.Equal(got, bundles) {
				t.Errorf("bundles/ holds %v, held %v; a refused target's bundle is never filed", got, bundles)
			}
			if len(h.svc.stepped) != 0 || len(h.infra.requests()) != h.before || len(h.clab.asked("clab", "deploy")) != 0 {
				t.Errorf("%d runs started, Infrahub asked %+v, containerlab's plan read %v; want none", len(h.svc.stepped),
					h.infra.requests()[h.before:], h.clab.asked("clab", "deploy"))
			}
			if sha256Of(t, h.paths.TwinJSON) != record {
				t.Errorf("twin.json changed under a refused step")
			}
		})
	}
	t.Run("a stage under another mapping version", func(t *testing.T) {
		h := stepHost(t, "plan-link-added.json", func(f *lab.RecordFields) { f.Provenance.Mapping.Version = "0f0f0f0" })
		record := sha256Of(t, h.paths.TwinJSON)
		want := unheld("change-1/linked", "scope tag:fylgja and mapping infrahub-dcim opsmill/schema-library 0f0f0f0",
			"stage change-1/linked names scope tag:fylgja and mapping "+dcim)
		for _, args := range [][]string{{"--allow-restart"}, {"--dry-run"}} {
			out := runStepCmd(t, append([]string{"--stage", "change-1/linked"}, args...)...)
			if got := refusalOf(t, out.doc); out.code != findings.ExitRejected || got != want || out.doc.Step != nil ||
				out.doc.Stage == nil || out.doc.Stage.Ref != "change-1/linked" {
				t.Errorf("%v: exit %d, refusal %+v, step %+v, stage %+v\nwant 1, %+v, no step and the resolved stage", args,
					out.code, got, out.doc.Step, out.doc.Stage, want)
			}
		}
		if len(h.svc.stepped) != 0 || len(h.clab.asked("clab", "deploy")) != 0 {
			t.Errorf("%d runs started, containerlab's plan read %v; want neither", len(h.svc.stepped), h.clab.asked("clab", "deploy"))
		}
		if sha256Of(t, h.paths.TwinJSON) != record {
			t.Errorf("twin.json changed under a refused step")
		}
	})
	for _, c := range []struct {
		name string
		args func(t *testing.T, h *stepHostFixture) []string
	}{
		{"a stage under the record's scope and mapping", func(*testing.T, *stepHostFixture) []string {
			return []string{"--stage", "change-1/linked"}
		}},
		{"a snapshot under the record's scope and mapping", func(t *testing.T, h *stepHostFixture) []string {
			target, _ := targetSnapshot(t, h, "linked")
			return []string{"--snapshot", target.ID}
		}},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := stepHost(t, "plan-link-added.json", nil)
			out := runStepCmd(t, append(c.args(t, h), "--dry-run", "--allow-restart")...)
			if out.code != findings.ExitOK || out.doc.Findings.Rejected() || carriesRule(out.doc.Findings, findings.RuleStepTwinUnsteppable) {
				t.Errorf("exit %d, findings %+v; want 0 and no step.twin.unsteppable", out.code, out.doc.Findings)
			}
		})
	}
}

// The edges of a snapshot target (US2 scenario 6, US4 scenario 3, FR-017): the twin's own
// snapshot compiles to the twin's bundle, and the step is unchanged; a snapshot of another
// branch under the same scope steps, and the record names that branch; a file declaring no
// id is filed under the id its body hashes to; and a run in flight refuses the start with
// run.in_flight, as for a stage. None asks Infrahub anything.
func TestStepToASnapshotEdges(t *testing.T) {
	t.Run("the twin's own snapshot, unchanged", func(t *testing.T) {
		h := stepHost(t, "plan-nothing.json", nil)
		svc := &fakeService{runID: stepRunID, events: unchangedStepEvents(), stepResult: provision.StepResult{
			Outcome: provision.StepUnchanged, PushPlan: []wire.StepPush{}, Timings: wire.StepTimings{WholeS: 1.8},
			Record: &wire.TwinRecord{State: wire.StateReady}, Findings: findings.List{},
			StartedAt: "2026-10-02T09:14:30Z", EndedAt: "2026-10-02T09:14:32Z"}}
		useService(t, svc)
		useInterrupts(t)
		out := runStepCmd(t, "--snapshot", h.fromSnapshot)
		if out.code != findings.ExitOK || len(svc.stepped) != 2 {
			t.Fatalf("exit %d, %d runs; want 0 and one per run of the command: %+v", out.code, len(svc.stepped), out.doc.Findings)
		}
		var diff struct{ Unchanged bool }
		if out.doc.Step != nil {
			if err := json.Unmarshal(out.doc.Step.Diff, &diff); err != nil {
				t.Fatal(err)
			}
		}
		if in := svc.stepped[0]; !in.Unchanged || in.To.BundleID != h.fromID || in.To.SnapshotID != h.fromSnapshot ||
			len(in.PushPlan) != 0 || !diff.Unchanged {
			t.Errorf("the run's input %+v, step %+v; want an unchanged step to the twin's own bundle", in, out.doc.Step)
		}
		if len(h.infra.requests()) != h.before {
			t.Errorf("Infrahub was asked %+v", h.infra.requests()[h.before:])
		}
	})

	t.Run("a snapshot of another branch", func(t *testing.T) {
		h := stepHost(t, "plan-link-added.json", nil)
		target, _ := targetSnapshot(t, h, "linked")
		file := targetFile(t, h, target.ID, func(d map[string]any) {
			delete(d, "snapshot_id")
			envelopeOf(d)["branch"] = "other"
		})
		svc := stepToSnapshotRun(t)
		out := runStepCmd(t, "--snapshot", file, "--allow-restart")
		if out.code != findings.ExitOK || len(svc.stepped) != 2 {
			t.Fatalf("exit %d, %d runs; want 0 and one per run of the command: %+v", out.code, len(svc.stepped), out.doc.Findings)
		}
		in := svc.stepped[1]
		if in.To.Branch != "other" || in.To.SnapshotID == target.ID || out.doc.Subject.Branch != "other" ||
			out.doc.Subject.Scope != "tag:fylgja" {
			t.Errorf("the run's to side %+v, subject %+v; want branch other, under the record's scope", in.To, out.doc.Subject)
		}
		if rec := recordOnHost(t, h, in); rec.Provenance.Branch != "other" || rec.Provenance.Scope != "tag:fylgja" ||
			rec.SnapshotID == nil || *rec.SnapshotID != in.To.SnapshotID {
			t.Errorf("the record after the step names %+v and snapshot %v; want branch other under tag:fylgja", rec.Provenance,
				rec.SnapshotID)
		}
		if len(h.infra.requests()) != h.before {
			t.Errorf("Infrahub was asked %+v", h.infra.requests()[h.before:])
		}
	})

	t.Run("a file declaring no id", func(t *testing.T) {
		h := stepHost(t, "plan-link-added.json", nil)
		target, toID := targetSnapshot(t, h, "linked")
		file := targetFile(t, h, target.ID, func(d map[string]any) { delete(d, "snapshot_id") })
		out := runStepCmd(t, "--snapshot", file, "--dry-run", "--allow-restart")
		if out.code != findings.ExitOK || out.doc.SnapshotID != target.ID || out.doc.BundleID != toID {
			t.Errorf("exit %d, snapshot %s, bundle %s; want 0 naming %s and %s", out.code, out.doc.SnapshotID, out.doc.BundleID,
				target.ID, toID)
		}
		if got := filedSnapshots(t, h.paths); !slices.Contains(got, target.ID+".json") {
			t.Errorf("snapshots/ holds %v; want the file filed under the id its body hashes to", got)
		}
	})

	t.Run("a run in flight", func(t *testing.T) {
		h := stepHost(t, "plan-link-added.json", nil)
		target, _ := targetSnapshot(t, h, "linked")
		want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleRunInFlight, Object: provision.WorkflowStep,
			Step: findings.StepStart, Message: "step run 01a1 is already in flight; wait for it to finish, or run fylgja twin " +
				"destroy to cancel it"}
		svc := &fakeService{startErr: &provision.StartError{Status: findings.StatusRejected, Finding: want}}
		useService(t, svc)
		useInterrupts(t)
		out := runStepCmd(t, "--snapshot", target.ID, "--allow-restart")
		if got := refusalOf(t, out.doc); out.code != findings.ExitRejected || got != want {
			t.Errorf("exit %d, %+v; want 1, %+v", out.code, got, want)
		}
		if len(h.infra.requests()) != h.before {
			t.Errorf("Infrahub was asked %+v", h.infra.requests()[h.before:])
		}
	})
}

// The dry run of a step to a snapshot (US2 scenario 8; contracts/commands.md, "The text"),
// line for line: the twin line, a stage twin's as before and a stage-less twin's naming its
// snapshot and what it is of, its branch at its at or read at its read; the target line in
// place of a stage's resolution, pinned or read; the step between the two sides' names,
// containerlab's plan, the push plan and the wait; then the host and the verdict. It files
// the snapshot sent and the bundle, starts no run and dials no service, and changes nothing of
// the twin; Infrahub is asked nothing.
func TestStepToASnapshotDryRun(t *testing.T) {
	for _, c := range []struct {
		name   string
		change func(*lab.RecordFields)
		// twin is the twin line, from h.
		twin func(h *stepHostFixture) string
		// unpinned makes the target a snapshot read with no at.
		unpinned bool
	}{
		{"from a stage twin", nil, func(h *stepHostFixture) string {
			return "twin: stage change-1/sealed (snapshot " + short(h.fromSnapshot) + ", bundle " + short(h.fromID) + "), pinned at " +
				stepMixedAt + "; 3 nodes"
		}, false},
		{"from a branch twin pinned", func(f *lab.RecordFields) { f.Stage = nil }, func(h *stepHostFixture) string {
			return "twin: snapshot " + short(h.fromSnapshot) + " (bundle " + short(h.fromID) + "), branch change-1 at " + stepMixedAt +
				"; 3 nodes"
		}, false},
		{"from a branch twin read", func(f *lab.RecordFields) { f.Stage, f.Provenance.At = nil, "" }, func(h *stepHostFixture) string {
			return "twin: snapshot " + short(h.fromSnapshot) + " (bundle " + short(h.fromID) + "), branch change-1, read at " +
				"2026-09-21T09:00:00.000000Z; 3 nodes"
		}, false},
		{"to a snapshot read with no at", nil, func(h *stepHostFixture) string {
			return "twin: stage change-1/sealed (snapshot " + short(h.fromSnapshot) + ", bundle " + short(h.fromID) + "), pinned at " +
				stepMixedAt + "; 3 nodes"
		}, true},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := stepHost(t, "plan-link-added.json", c.change)
			target, _ := targetSnapshot(t, h, "linked")
			if target.CTM.Envelope.At != stepWrittenAt {
				t.Fatalf("linked's snapshot is pinned at %s, want %s", target.CTM.Envelope.At, stepWrittenAt)
			}
			file := targetFile(t, h, target.ID, func(d map[string]any) {
				if c.unpinned {
					delete(d, "snapshot_id")
					envelopeOf(d)["at"] = ""
				}
			})
			record := sha256Of(t, h.paths.TwinJSON)
			twinDir := stateRootListing(t, h.paths.Twin)

			out := runStepCmd(t, "--dry-run", "--allow-restart", "--snapshot", file)
			if out.code != findings.ExitOK || out.doc.DryRun == nil || out.doc.Step == nil || out.doc.Step.StepRunBlock != nil {
				t.Fatalf("exit %d, dry_run %+v, step %+v, findings %+v; want 0 with a dry run and no run", out.code, out.doc.DryRun,
					out.doc.Step, out.doc.Findings)
			}
			toSnapshot, toID := out.doc.SnapshotID, out.doc.BundleID
			of := "branch change-1 at " + stepWrittenAt
			if c.unpinned {
				of = "branch change-1, read at " + target.ObservedAt
			}
			from := "change-1/sealed"
			if c.change != nil {
				from = "snapshot " + short(h.fromSnapshot)
			}
			want := stepDryRunLines(h, toID)
			want[1] = c.twin(h)
			want[2] = "target: snapshot " + short(toSnapshot) + " (" + of + ")"
			want[3] = "step " + from + " → snapshot " + short(toSnapshot) + " (" + short(h.fromID) + " → " + short(toID) + "):"
			want = append(want, "memory: sum 5120 MiB; host budget unset", "host: lab fylgja present; twin directory present",
				"verdict: "+findings.VerdictClear)
			if got := strings.Join(want, "\n") + "\n"; out.stdout != got {
				t.Errorf("stdout:\n%s\nwant:\n%s", out.stdout, got)
			}
			noContent(t, "the dry run", out.stdout, out.stderr)
			if !c.unpinned && toSnapshot != target.ID {
				t.Errorf("the document names snapshot %s, want %s", toSnapshot, target.ID)
			}
			if got := filedSnapshots(t, h.paths); !slices.Contains(got, toSnapshot+".json") {
				t.Errorf("snapshots/ holds %v; want the file filed", got)
			}
			if got := storedBundles(t, h.paths.Bundles); !slices.Contains(got, toID) {
				t.Errorf("bundles/ holds %v; want the target's filed", got)
			}
			if len(h.svc.stepped) != 0 || len(h.infra.requests()) != h.before {
				t.Errorf("%d runs started and Infrahub asked %+v; want neither", len(h.svc.stepped), h.infra.requests()[h.before:])
			}
			if sha256Of(t, h.paths.TwinJSON) != record || !slices.Equal(stateRootListing(t, h.paths.Twin), twinDir) {
				t.Errorf("the twin directory changed under a dry run")
			}
		})
	}
}

// A step to a snapshot closes as a step to a stage closes, the target named snapshot <short>
// (contracts/commands.md, "The text"): stepped, unchanged, and diverged naming where the
// twin is still up, its stage from a stage twin and its snapshot from a stage-less one. While
// such a step runs, twin show names it stepping towards snapshot <short>, as the service reads
// the run's input.
func TestStepToASnapshotCloses(t *testing.T) {
	diverged := provision.StepResult{Outcome: provision.StepDiverged, Phase: findings.StepPush, Step: findings.StepPush,
		PushPlan: []wire.StepPush{
			{Node: "e1", Reasons: []string{"artifact", "restarted"}, Outcome: wire.PushRefused, Rule: findings.RulePushRefused},
			{Node: "s1", Reasons: []string{"artifact", "bootstrap"}, Outcome: wire.PushLanded}},
		Timings: wire.StepTimings{WholeS: 71.2}, Record: &wire.TwinRecord{State: wire.StateDiverged},
		Findings: findings.List{{Severity: findings.Rejection, Rule: findings.RulePushRefused, Object: "e1", Step: findings.StepPush,
			Message: "node e1 refused artifact device-config (checksum cbc8c75d…) at line 7: Invalid input"}}}
	for _, c := range []struct {
		name    string
		change  func(*lab.RecordFields)
		plan    string
		own     bool // the target is the twin's own snapshot
		res     *provision.StepResult
		code    int
		closing func(h *stepHostFixture, toSnapshot, toID string) string
	}{
		{name: "stepped", plan: "plan-link-added.json", code: findings.ExitOK,
			closing: func(_ *stepHostFixture, toSnapshot, toID string) string {
				return "stepped to snapshot " + short(toSnapshot) + " (bundle " + short(toID) + ") in 71.2s: reconcile 3.9s; " +
					"readiness e1 54.8s; push e1 1.6s, s1 2.4s"
			}},
		{name: "unchanged", plan: "plan-nothing.json", own: true, res: &provision.StepResult{Outcome: provision.StepUnchanged,
			PushPlan: []wire.StepPush{}, Timings: wire.StepTimings{WholeS: 1.8}, Record: &wire.TwinRecord{State: wire.StateReady}},
			code: findings.ExitOK, closing: func(_ *stepHostFixture, toSnapshot, toID string) string {
				return "unchanged; the record moves to snapshot " + short(toSnapshot) + " (bundle " + short(toID) + ") in 1.8s"
			}},
		{name: "diverged from a stage twin", plan: "plan-link-added.json", res: &diverged, code: findings.ExitUnclean,
			closing: func(h *stepHostFixture, toSnapshot, toID string) string {
				return "diverged towards snapshot " + short(toSnapshot) + " (bundle " + short(toID) + ") at phase push: landed s1; " +
					"not landed e1 (push.refused); the twin is up at stage change-1/sealed (bundle " + short(h.fromID) + "); " +
					"fylgja twin destroy clears it"
			}},
		{name: "diverged from a snapshot twin", change: func(f *lab.RecordFields) { f.Stage, f.Source = nil, wire.SourceSnapshot },
			plan: "plan-link-added.json", res: &diverged, code: findings.ExitUnclean,
			closing: func(h *stepHostFixture, toSnapshot, toID string) string {
				return "diverged towards snapshot " + short(toSnapshot) + " (bundle " + short(toID) + ") at phase push: landed s1; " +
					"not landed e1 (push.refused); the twin is up at snapshot " + short(h.fromSnapshot) + " (bundle " +
					short(h.fromID) + "); fylgja twin destroy clears it"
			}},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := stepHost(t, c.plan, c.change)
			arg := h.fromSnapshot
			if !c.own {
				target, _ := targetSnapshot(t, h, "linked")
				arg = target.ID
			}
			svc := stepToSnapshotRun(t)
			if c.res != nil {
				res := *c.res
				res.StartedAt, res.EndedAt = "2026-10-02T09:14:30Z", "2026-10-02T09:15:41Z"
				if res.Findings == nil {
					res.Findings = findings.List{}
				}
				svc.stepResult = res
			}
			if c.own {
				svc.events = unchangedStepEvents()
			}
			out := runStepCmd(t, "--snapshot", arg, "--allow-restart")
			if out.code != c.code || len(svc.stepped) != 2 {
				t.Fatalf("exit %d, %d runs; want %d and one per run of the command: %+v", out.code, len(svc.stepped), c.code,
					out.doc.Findings)
			}
			if want := c.closing(h, out.doc.SnapshotID, out.doc.BundleID); !strings.HasSuffix(out.stdout, "\n"+want+"\n") {
				t.Errorf("stdout:\n%s\nwant it to end:\n%s", out.stdout, want)
			}
			if len(h.infra.requests()) != h.before {
				t.Errorf("Infrahub was asked %+v", h.infra.requests()[h.before:])
			}
			if c.name != "stepped" {
				return
			}

			// The run in flight, as the service names its target from the input the command
			// started it with.
			towards := svc.stepped[0].To.Name()
			show := showWith(t, h.paths, "inspect-three.json", &fakeService{inFlight: []provision.RunInFlight{
				{WorkflowID: provision.WorkflowStep, RunID: stepRunID, Step: findings.StepPush, Towards: towards}}})
			want := "run fylgja-step " + stepRunID + " is at step push, stepping towards snapshot " + short(out.doc.SnapshotID)
			if !strings.Contains(show.stdout, "; "+want+"\n") || !slices.Contains(show.doc.Show.Notes, want) {
				t.Errorf("twin show:\n%s\nnotes %q; want the kind line and a note saying %q", show.stdout, show.doc.Show.Notes, want)
			}
		})
	}
}

// twin step --detach (020) decides everything a followed step decides, prints the step, the
// reconcile and the push lines before the run, then ends once the run has started: none of
// its progress, exit 0, the command's warnings then run.detached naming the run. --detach
// beside --dry-run is run.flags.conflict, exit 1, before the twin's record is read.
func TestStepDetachedEndsAtTheRun(t *testing.T) {
	stepHost(t, "plan-link-added.json", nil)
	svc := &fakeService{runID: stepRunID, events: stepEvents()}
	useService(t, svc)
	useInterrupts(t)

	out := runStepCmd(t, "--allow-restart", "--detach")
	if out.code != findings.ExitOK || out.doc.Status != findings.StatusOK || out.doc.Subject.RunID != stepRunID {
		t.Fatalf("exit %d, document %+v; want 0, ok, naming %s", out.code, out.doc, stepRunID)
	}
	last := out.doc.Findings[len(out.doc.Findings)-1]
	if last.Rule != findings.RuleRunDetached || last.Object != provision.WorkflowStep+" "+stepRunID {
		t.Errorf("last finding %+v, want run.detached naming the step run", last)
	}
	if strings.Contains(out.stdout, "step inspect") || strings.Contains(out.stdout, "run fylgja-step") {
		t.Errorf("a detached step printed its run's progress:\n%s", out.stdout)
	}
	if !strings.Contains(out.stdout, "push: ") || !strings.Contains(out.stderr, "started; read it with fylgja run read") {
		t.Errorf("stdout:\n%s\nstderr:\n%s\nwant the step's lines before the run, and run.detached", out.stdout, out.stderr)
	}
	if len(svc.stepped) != 2 {
		t.Errorf("%d step runs started, want one in each rendering", len(svc.stepped))
	}

	conflict := runStepCmd(t, "--dry-run", "--detach")
	if f := refusalOf(t, conflict.doc); conflict.code != findings.ExitRejected || f.Rule != findings.RuleRunFlagsConflict {
		t.Errorf("--dry-run --detach: exit %d, %+v; want run.flags.conflict, exit 1", conflict.code, f)
	}
}
