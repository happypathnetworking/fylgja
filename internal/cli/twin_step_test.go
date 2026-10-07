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

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/stage"
	"github.com/happypathnetworking/fylgja/internal/waypoint"
)

// The series twin step walks in tier 1: steps/1 is the mixed fixture
// read at its own at, steps/2 a branch that adds the link e1:Ethernet3 — s1:ethernet-1/3 and
// re-renders e1's and s1's artifacts (the fixture tool's -add-mixed-link, in the fake), and
// steps/3 the
// mixed fixture again at a later at, so the step from steps/1 is unchanged but for
// provenance. steps/4 reads a branch with no contract node, steps/6 is held twice, and
// other/3 is of another series.
const (
	stepMixedAt   = "2026-09-20T12:00:00Z"
	stepWrittenAt = "2026-09-21T08:00:00.000000+00:00"
	stepLaterAt   = "2026-09-22T00:00:00Z"
	stepRunID     = "01a1b2c3-0000-7000-8000-000000000001"
	createRunID   = "01a1b2c3-0000-7000-8000-000000000000"
)

// stepInfrahub serves the series.
func stepInfrahub(t *testing.T) *fakeInfrahub {
	t.Helper()
	f := newFakeInfrahub(t)
	mixed, err := ctm.Load(repoPath("testdata", "ctm", "mixed.json"))
	if err != nil {
		t.Fatal(err)
	}
	f.branches = map[string]*ctm.CTM{"mixed-fixture": mixed, "mixed-step": withMixedLink(t), "contractless": mixed,
		"mixed-less": withoutE2(t)}
	f.contractless = map[string]bool{"contractless": true}
	f.waypoint("wp-steps-2", "steps", 2, "mixed-step", stepWrittenAt, "", "a link between e1 and s1")
	f.waypoint("wp-steps-1", "steps", 1, "mixed-fixture", stepWrittenAt, stepMixedAt, "the mixed fixture as sealed")
	f.waypoint("wp-steps-3", "steps", 3, "mixed-fixture", stepWrittenAt, stepLaterAt, "the fixture again")
	f.waypoint("wp-steps-4", "steps", 4, "contractless", stepWrittenAt, stepLaterAt, "")
	f.waypoint("wp-steps-5", "steps", 5, "mixed-less", stepWrittenAt, stepLaterAt, "e2 retired")
	f.waypoint("wp-steps-6a", "steps", 6, "mixed-fixture", stepWrittenAt, stepLaterAt, "")
	f.waypoint("wp-steps-6b", "steps", 6, "mixed-fixture", stepWrittenAt, stepLaterAt, "")
	f.waypoint("wp-other-3", "other", 3, "mixed-fixture", stepWrittenAt, stepMixedAt, "")
	return f
}

// withMixedLink is the mixed fixture read from branch mixed-step with the link
// e1:Ethernet3 — s1:ethernet-1/3 added and e1's and s1's artifacts re-rendered for it, each
// carrying the marker in a comment line, as the seed's role line does.
func withMixedLink(t *testing.T) *ctm.CTM {
	t.Helper()
	c, err := ctm.Load(repoPath("testdata", "ctm", "mixed.json"))
	if err != nil {
		t.Fatal(err)
	}
	c.Envelope.Branch = "mixed-step"
	const link = "e1:Ethernet3|s1:ethernet-1/3"
	c.Links = append(c.Links, ctm.Link{ID: link, Endpoints: []ctm.Endpoint{
		{Device: "e1", Interface: "Ethernet3"}, {Device: "s1", Interface: "ethernet-1/3"}}})
	for i := range c.Devices {
		d := &c.Devices[i]
		var name, extra string
		switch d.Name {
		case "e1":
			name = "Ethernet3"
			extra = "interface Ethernet3\n   description to s1 ethernet-1/3\n   no shutdown\n! role leaf-" + marker + "\n"
		case "s1":
			name = "ethernet-1/3"
			extra = "set / interface ethernet-1/3 description \"to e1 Ethernet3\"\n" +
				"set / interface ethernet-1/3 admin-state enable\n# role leaf-" + marker + "\n"
		default:
			continue
		}
		enabled := true
		d.Interfaces = append(d.Interfaces, ctm.Interface{Name: name, Iftype: "physical", Enabled: &enabled, Link: link})
		d.Artifact.Content += extra
		sum := md5.Sum([]byte(d.Artifact.Content))
		d.Artifact.Checksum = hex.EncodeToString(sum[:])
	}
	return c
}

// withoutE2 is the mixed fixture read from branch mixed-less with e2 and its two links
// removed, s1's and e1's ends of them left uncabled.
func withoutE2(t *testing.T) *ctm.CTM {
	t.Helper()
	c, err := ctm.Load(repoPath("testdata", "ctm", "mixed.json"))
	if err != nil {
		t.Fatal(err)
	}
	c.Envelope.Branch = "mixed-less"
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
	// before is how many requests Infrahub had answered once the fixture was built.
	before int
}

// stepHost is a host running the mixed twin, built from steps/1 by run createRunID: the
// state root, the fake Infrahub, containerlab answering inspect-three.json and plan, both
// logins set and no host budget, and no workflow service. The from bundle is built and filed
// through waypoint plan's own path, as a create's compile files it, and twin.json 4 records
// it; change adjusts the record before it is written.
func stepHost(t *testing.T, plan string, change func(*lab.RecordFields)) *stepHostFixture {
	t.Helper()
	paths := useStateRoot(t)
	useService(t, nil)
	mixedDryRunEnv(t)
	infra := stepInfrahub(t)
	infra.start()
	fromID := buildWaypoint(t, paths, waypoint.Ref{Series: "steps", Sequence: 1})
	writeTwin(t, paths, stepRecordOf(t, fromID, change))
	return &stepHostFixture{paths: paths, infra: infra, clab: useStepClab(t, "inspect-three.json", plan), fromID: fromID,
		before: len(infra.requests())}
}

// compiledWaypoint is what waypoint plan's path hands its filing for one reference.
type compiledWaypoint struct {
	files    map[string][]byte
	id       string
	snapshot *ctm.CTM
}

// builtWaypoints holds buildWaypoint's read and compile by reference, once for the package.
// Every caller reads stepInfrahub's fixture as stepHost builds it, unchanged, so a reference
// compiles to the same files each time; only the filing, into each test's own store, is
// done again.
var builtWaypoints = struct {
	sync.Mutex
	byRef map[waypoint.Ref]compiledWaypoint
}{byRef: map[waypoint.Ref]compiledWaypoint{}}

// buildWaypoint reads, compiles and files ref through waypoint plan's path and returns its id.
// The read and the compile are builtWaypoints' after the first.
func buildWaypoint(t *testing.T, paths lab.Paths, ref waypoint.Ref) string {
	t.Helper()
	ctx := context.Background()
	builtWaypoints.Lock()
	built, ok := builtWaypoints.byRef[ref]
	builtWaypoints.Unlock()
	if ok {
		if _, _, err := fileCompiled(ctx, paths.Bundles, built.files, built.id, built.snapshot); err != nil {
			t.Fatal(err)
		}
		return built.id
	}
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	reader, err := intent.WaypointReaderFromEnv()
	if err != nil {
		t.Fatal(err)
	}
	all, _, err := waypoint.ListAll(ctx, reader)
	if err != nil {
		t.Fatal(err)
	}
	file := func(ctx context.Context, files map[string][]byte, id string, snapshot *ctm.CTM) (findings.List, error) {
		built = compiledWaypoint{files: files, id: id, snapshot: snapshot}
		_, list, err := fileCompiled(ctx, paths.Bundles, files, id, snapshot)
		return list, err
	}
	w := waypoint.Build(ctx, all, ref, reg, waypoint.NewStages(file), time.Now().UTC())
	if w.Status != waypoint.PlanCompiled {
		t.Fatalf("%s did not compile: %+v", ref, w.Findings)
	}
	if built.id != w.Bundle.ID {
		t.Fatalf("%s filed %s and compiled to %s", ref, built.id, w.Bundle.ID)
	}
	builtWaypoints.Lock()
	builtWaypoints.byRef[ref] = built
	builtWaypoints.Unlock()
	return w.Bundle.ID
}

// stepRecordOf is twin.json 4 of the mixed twin created from steps/1.
func stepRecordOf(t *testing.T, bundleID string, change func(*lab.RecordFields)) wire.TwinRecord {
	t.Helper()
	observed := "2026-09-21T09:00:00.000000Z"
	f := lab.RecordFields{
		BundleID:   bundleID,
		Provenance: wire.Provenance{Branch: "mixed-fixture", At: stepMixedAt, SchemaHash: "fixture", ContractVersion: "0.2"},
		ObservedAt: &observed,
		Source:     wire.SourceIntent,
		RunID:      createRunID,
		Version:    "0.1.0-dev",
		RecordedAt: time.Date(2026, 9, 21, 9, 1, 2, 0, time.UTC),
		Waypoint:   &wire.WaypointRef{Series: "steps", Sequence: 1, Description: "the mixed fixture as sealed", AtSource: "given"},
	}
	for i, n := range []string{"e1", "e2", "s1"} {
		image, id := "ceos:4.32.0.2F", "arista_eos"
		if n == "s1" {
			image, id = "ghcr.io/nokia/srlinux:24.7.1", "nokia_srlinux"
		}
		f.Nodes = append(f.Nodes, wire.TwinNode{Name: n, Container: "clab-fylgja-" + n, Image: image,
			PSP: wire.PSPRef{ID: id, Source: "embedded"}, MgmtIPv4: fmt.Sprintf("172.20.20.%d", i+2), ReadyAfterS: 9})
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

// stepDryRunLines is the dry run's text for the step steps/1 → steps/2 under
// plan-link-added.json, through the push: line (contracts/cli.md).
func stepDryRunLines(fromID, toID string) []string {
	return []string{
		"dry run: no lab, container, twin directory or run is changed",
		"twin: waypoint steps/1 (bundle " + short(fromID) + "), pinned at " + stepMixedAt + "; 3 nodes",
		`waypoint steps/2: branch mixed-step at ` + stepWrittenAt + ` (written), "a link between e1 and s1"`,
		"step steps/1 → steps/2 (" + short(fromID) + " → " + short(toID) + "):",
		"  nodes: ~e1 (mapping); ~s1 (bootstrap, mapping)",
		"  links: +e1:eth3 — s1:e1-3",
		"  artifacts: e1 device-config 644a78b3… → 9f22a736…; s1 device-config 34df00ec… → 5612b2a0…",
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

// The dry run of the step steps/1 → steps/2 says, line for line, what a step would do and
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
			want := strings.Join(append(stepDryRunLines(h.fromID, toID),
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
			if d == nil || d.Verdict != wantVerdict || d.Follow != nil || len(d.Nodes) != 3 || d.MemorySumMB != 5120 ||
				!d.Host.LabPresent || !d.Host.TwinDirPresent {
				t.Errorf("dry_run %+v; want %s over the target's three nodes, no follow, the twin present", d, wantVerdict)
			}
			st := doc.Step
			if st == nil || st.StepRunBlock != nil || st.AllowRestart != !refused || st.From.BundleID != h.fromID ||
				st.To.BundleID != toID || st.To.Branch != "mixed-step" || !slices.Equal(st.Reconcile.Restarted, []string{"e1"}) ||
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
			if doc.Waypoint == nil || doc.Waypoint.Series != "steps" || doc.Waypoint.Sequence != 2 || doc.Waypoint.Branch != "mixed-step" {
				t.Errorf("waypoint block %+v; want steps/2 on mixed-step", doc.Waypoint)
			}
			if sub := doc.Subject; sub == nil || sub.Waypoint != "steps/2" || sub.Branch != "mixed-step" || sub.At != stepWrittenAt || sub.RunID != "" {
				t.Errorf("subject %+v; want steps/2 resolved and no run", sub)
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
	if got := sha256Of(t, h.paths.TwinJSON); got != record {
		t.Errorf("twin.json changed under a dry run")
	}
	if got := stateRootListing(t, h.paths.Twin); !slices.Equal(got, twinDir) {
		t.Errorf("the twin directory changed under a dry run:\n%v\nwas\n%v", got, twinDir)
	}
}

// divergedStepHost is stepHost's twin left diverged by a step towards steps/2 that stopped
// at push, e1 refused and s1 landed.
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
		From: wire.StepSide{Waypoint: rec.Waypoint, BundleID: rec.BundleID, At: stepMixedAt},
		To: wire.StepSide{Waypoint: &wire.WaypointRef{Series: "steps", Sequence: 2, AtSource: "written"},
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
		Message: "the twin is diverged: step run fylgja-step " + stepRunID + " towards waypoint steps/2 stopped at phase push " +
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
		})
	}
}

// Two warnings leave the exit as it is: a step that skips waypoints of the series, and a
// package whose declared link change containerlab's plan contradicts.
func TestStepWarnings(t *testing.T) {
	t.Run("skipped", func(t *testing.T) {
		stepHost(t, "plan-nothing.json", nil)
		out := runStepCmd(t, "--waypoint", "steps/3", "--dry-run")
		want := findings.Finding{Severity: findings.Warning, Rule: findings.RuleStepSequenceSkipped, Object: "steps/3",
			Step: findings.StepResolve, Message: "the step from steps/1 to steps/3 skips waypoint 2; the step is between the two bundles either way"}
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
		out := runStepCmd(t, "--waypoint", "steps/3", "--dry-run", "--allow-restart")
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
		// fromLess builds the twin from steps/5, e2 retired, so that a step to steps/2 adds e2.
		fromLess bool
		args     []string
		plan     string
		line     string
	}{
		{name: "a recreate and a delete", args: []string{"--waypoint", "steps/5"},
			plan: `{"dry-run": true, "deployed-lab": false, "lab-name": "fylgja", "added-nodes": [], "deleted-nodes": ["e2"],
				"recreated-nodes": ["s1"], "started-nodes": [], "added-links": [], "deleted-endpoints": [], "restarted-nodes": [],
				"node-change-reasons": {"s1": "config drift: Image"}}`,
			line: "reconcile: recreate s1 (config drift: Image; nokia_srlinux declares live); delete e2"},
		{name: "a create", fromLess: true, args: []string{"--waypoint", "steps/2"},
			plan: `{"dry-run": true, "deployed-lab": false, "lab-name": "fylgja", "added-nodes": ["e2"], "deleted-nodes": [],
				"recreated-nodes": [], "started-nodes": [],
				"added-links": ["e1:eth2_1 -- e2:eth1", "e2:eth3_1_1 -- s1:e1-2", "e1:eth3 -- s1:e1-3"], "deleted-endpoints": [],
				"restarted-nodes": ["e1"], "node-change-reasons": {"e1": "added link"}}`,
			line: "reconcile: restart e1 (added link; arista_eos declares restart); create e2; live s1 (nokia_srlinux declares live)"},
	} {
		t.Run(c.name, func(t *testing.T) {
			h := stepHost(t, "plan-nothing.json", nil)
			if c.fromLess {
				fromID := buildWaypoint(t, h.paths, waypoint.Ref{Series: "steps", Sequence: 5})
				writeTwin(t, h.paths, stepRecordOf(t, fromID, func(f *lab.RecordFields) {
					f.Provenance.Branch, f.Provenance.At = "mixed-less", stepLaterAt
					f.Waypoint = &wire.WaypointRef{Series: "steps", Sequence: 5, Description: "e2 retired", AtSource: "given"}
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
// (contracts/cli.md).
func TestStepRefusedBeforeAnyConnection(t *testing.T) {
	const orphanAt = "/tmp/scratchpad/twin3/bundle/topology.clab.yml"
	refusal := func(rule, step, object, message string) findings.Finding {
		return findings.Finding{Severity: findings.Rejection, Rule: rule, Step: step, Object: object, Message: message}
	}
	for _, c := range []struct {
		name string
		// host builds the host; nil is the waypoint twin of steps/1 under plan-link-added.
		host func(t *testing.T) *stepHostFixture
		args []string
		code int
		// want is the one rejection; its object or message "" is filled from the host by fill.
		want findings.Finding
		fill func(h *stepHostFixture, f *findings.Finding)
		// asked says whether Infrahub was asked anything once the host was built.
		asked bool
	}{
		{name: "no lab and no twin directory", host: func(t *testing.T) *stepHostFixture {
			paths := useStateRoot(t)
			useService(t, nil)
			infra := stepInfrahub(t)
			infra.start()
			return &stepHostFixture{paths: paths, infra: infra, clab: useStepClab(t, "inspect-empty.json", "")}
		}, code: findings.ExitRejected, want: refusal(findings.RuleStepTwinUnsteppable, findings.StepResolve, "lab fylgja",
			"no twin: no lab fylgja and no twin directory; only a twin built from a waypoint steps (fylgja twin create --waypoint)")},
		{name: "an orphan", host: func(t *testing.T) *stepHostFixture {
			paths := useStateRoot(t)
			useService(t, nil)
			infra := stepInfrahub(t)
			infra.start()
			return &stepHostFixture{paths: paths, infra: infra, clab: useStepClab(t, "inspect-three.json", "")}
		}, code: findings.ExitRejected, want: refusal(findings.RuleStepTwinUnsteppable, findings.StepResolve, "lab fylgja",
			"an orphan: no twin.json records it; deployed from "+orphanAt+"; only a twin built from a waypoint steps; fylgja twin destroy clears it")},
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
					"; only a twin built from a waypoint steps; fylgja twin destroy clears it"
			}},
		{name: "a record whose lab is absent", host: func(t *testing.T) *stepHostFixture {
			h := stepHost(t, "plan-link-added.json", nil)
			h.clab.inspect = []byte("{}")
			return h
		}, code: findings.ExitRejected, want: refusal(findings.RuleStepTwinUnsteppable, findings.StepResolve, "", ""),
			fill: func(h *stepHostFixture, f *findings.Finding) {
				f.Object = h.paths.Twin
				f.Message = "the twin of branch mixed-fixture at " + stepMixedAt + ", bundle_id " + h.fromID +
					", provisioned by run fylgja-provision " + createRunID + ", 3 nodes recorded, but lab fylgja is absent; " +
					"only a twin built from a waypoint steps; fylgja twin destroy clears it"
			}},
		{name: "a leftover twin directory", host: func(t *testing.T) *stepHostFixture {
			paths := useStateRoot(t)
			useService(t, nil)
			infra := stepInfrahub(t)
			infra.start()
			if err := os.MkdirAll(filepath.Join(paths.Twin, "bundle"), 0o755); err != nil {
				t.Fatal(err)
			}
			return &stepHostFixture{paths: paths, infra: infra, clab: useStepClab(t, "inspect-empty.json", "")}
		}, code: findings.ExitRejected, want: refusal(findings.RuleStepTwinUnsteppable, findings.StepResolve, "",
			"a leftover twin directory: no twin.json and no lab fylgja; only a twin built from a waypoint steps; fylgja twin destroy clears it"),
			fill: func(h *stepHostFixture, f *findings.Finding) { f.Object = h.paths.Twin }},
		{name: "a twin of a branch", host: func(t *testing.T) *stepHostFixture {
			return stepHost(t, "plan-link-added.json", func(f *lab.RecordFields) { f.Waypoint, f.Provenance.At = nil, "" })
		}, code: findings.ExitRejected, want: refusal(findings.RuleStepTwinUnsteppable, findings.StepResolve, "",
			"the twin was created from branch mixed-fixture, not from a waypoint, so it names no series to step along; only a twin built from a waypoint steps"),
			fill: func(h *stepHostFixture, f *findings.Finding) { f.Object = h.fromID }},
		{name: "a twin of a branch at a time", host: func(t *testing.T) *stepHostFixture {
			return stepHost(t, "plan-link-added.json", func(f *lab.RecordFields) { f.Waypoint = nil })
		}, code: findings.ExitRejected, want: refusal(findings.RuleStepTwinUnsteppable, findings.StepResolve, "",
			"the twin was created from branch mixed-fixture at "+stepMixedAt+", not from a waypoint, so it names no series to step along; only a twin built from a waypoint steps"),
			fill: func(h *stepHostFixture, f *findings.Finding) { f.Object = h.fromID }},
		{name: "a twin of a bundle", host: func(t *testing.T) *stepHostFixture {
			return stepHost(t, "plan-link-added.json", func(f *lab.RecordFields) {
				f.Waypoint, f.Source, f.ObservedAt, f.Provenance.At = nil, wire.SourceBundle, nil, ""
			})
		}, code: findings.ExitRejected, want: refusal(findings.RuleStepTwinUnsteppable, findings.StepResolve, "",
			"the twin was created from a bundle, not from a waypoint, so it names no series to step along; only a twin built from a waypoint steps"),
			fill: func(h *stepHostFixture, f *findings.Finding) { f.Object = h.fromID }},
		{name: "a diverged twin", host: divergedStepHost, code: findings.ExitRejected, want: divergedRefusal(""),
			fill: func(h *stepHostFixture, f *findings.Finding) { f.Object = h.fromID }},
		{name: "another series", args: []string{"--waypoint", "other/3"}, code: findings.ExitRejected, asked: true,
			want: refusal(findings.RuleStepTargetForeign, findings.StepResolve, "other/3",
				"waypoint other/3 is not of series steps, the twin's series, whose sequences are 1, 2, 3, 4, 5, 6; a step stays inside the series the twin was built from")},
		{name: "a series with no waypoints", host: func(t *testing.T) *stepHostFixture {
			return stepHost(t, "plan-link-added.json", func(f *lab.RecordFields) { f.Waypoint.Series = "gone" })
		}, code: findings.ExitRejected, asked: true, want: refusal(findings.RuleStepTargetUnknown, findings.StepResolve, "gone",
			"series gone has no waypoints; the series are: other, steps")},
		{name: "no next", host: func(t *testing.T) *stepHostFixture {
			return stepHost(t, "plan-link-added.json", func(f *lab.RecordFields) { f.Waypoint.Sequence = 6 })
		}, code: findings.ExitRejected, asked: true, want: refusal(findings.RuleStepTargetUnknown, findings.StepResolve, "steps",
			"series steps has no waypoint after 6; its sequences are 1, 2, 3, 4, 5, 6")},
		{name: "a sequence the series lacks", args: []string{"--waypoint", "steps/7"}, code: findings.ExitRejected, asked: true,
			want: refusal(findings.RuleStepTargetUnknown, findings.StepResolve, "steps/7",
				"series steps has no waypoint 7; its sequences are 1, 2, 3, 4, 5, 6")},
		{name: "the current one", args: []string{"--waypoint", "steps/1"}, code: findings.ExitRejected, asked: true,
			want: refusal(findings.RuleStepTargetCurrent, findings.StepResolve, "steps/1", "the twin is already at waypoint steps/1; series steps's sequences are 1, 2, 3, 4, 5, 6")},
		{name: "the kind absent", host: func(t *testing.T) *stepHostFixture {
			h := stepHost(t, "plan-link-added.json", nil)
			h.infra.kind = nil
			return h
		}, code: findings.ExitRejected, asked: true, want: refusal(findings.RuleWaypointKindAbsent, findings.StepResolve, intent.WaypointKind, ""),
			fill: func(h *stepHostFixture, f *findings.Finding) { f.Message = "" }},
		{name: "a duplicate target", args: []string{"--waypoint", "steps/6"}, code: findings.ExitRejected, asked: true,
			want: refusal(findings.RuleWaypointDuplicate, findings.StepResolve, "steps/6", "")},
		{name: "a refused read", args: []string{"--waypoint", "steps/4"}, code: findings.ExitRejected, asked: true,
			want: refusal(findings.RuleContractNodeMissing, findings.StepRead, "", "")},
		{name: "a refused compile", host: func(t *testing.T) *stepHostFixture {
			h := stepHost(t, "plan-link-added.json", nil)
			toID := buildWaypoint(t, h.paths, waypoint.Ref{Series: "steps", Sequence: 2})
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
		}, args: []string{"--waypoint", "steps/5", "--allow-restart"}, code: findings.ExitRejected, asked: true,
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
		{name: "--waypoint=", args: []string{"--waypoint="}, code: findings.ExitError,
			want: refusal(findings.RuleWaypointRefInvalid, findings.StepStart, "",
				`--waypoint "" is not a waypoint reference: expected <series>/<sequence>, a series with no "/" and no whitespace and a positive integer`)},
	} {
		t.Run(c.name, func(t *testing.T) {
			host := c.host
			if host == nil {
				host = func(t *testing.T) *stepHostFixture { return stepHost(t, "plan-link-added.json", nil) }
			}
			h := host(t)
			if c.name == "--waypoint=" {
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
			if c.name == "--waypoint=" && len(h.clab.calls) != 0 {
				t.Errorf("containerlab was asked %v before the flag was refused", h.clab.calls)
			}
			if plans := h.clab.asked("clab", "deploy"); got.Step != findings.StepCompare && len(plans) != 0 {
				t.Errorf("a refusal at %s read containerlab's plan %v", got.Step, plans)
			}
		})
	}
}

// A target whose read cannot run, and a target whose at carries more fractional digits than
// Infrahub honours, end the command as M10 ends them for a waypoint: exit 2, status error,
// not a refusal's 1 (contracts/cli.md's resolution row). Nothing of the
// step is computed: containerlab's plan is never read and no service is dialled.
func TestStepTargetErrorsExitTwo(t *testing.T) {
	for _, c := range []struct {
		name string
		args []string
		host func(h *stepHostFixture)
		want findings.Finding // its message "" is not compared
	}{
		{name: "the target's read cannot run",
			host: func(h *stepHostFixture) { delete(h.infra.branches, "mixed-step") },
			want: findings.Finding{Severity: findings.Rejection, Rule: findings.RuleOperationFailed, Step: findings.StepRead, Object: "steps/2"}},
		{name: "the target's at carries nine fractional digits", args: []string{"--waypoint", "steps/7"},
			host: func(h *stepHostFixture) {
				h.infra.waypoint("wp-steps-7", "steps", 7, "mixed-fixture", stepWrittenAt, "2026-09-22T00:00:00.123456789Z", "")
			},
			want: findings.Finding{Severity: findings.Rejection, Rule: findings.RuleAtPrecision, Step: findings.StepResolve, Object: "steps/7",
				Message: "waypoint steps/7: at 2026-09-22T00:00:00.123456789Z carries 9 fractional digits; Infrahub honours at most 6 " +
					"(microseconds). Write the waypoint's as_of with at most six."}},
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

// --branch, --at, --interval and --no-follow are not flags of twin step: flag parsing
// refuses each, exit 2, before anything is read.
func TestStepTakesNoBranchFlags(t *testing.T) {
	for _, flag := range []string{"--branch=x", "--at=x", "--interval=1m", "--no-follow"} {
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
			Message: "step run " + stepRunID + " towards waypoint steps/2 stopped at phase " + phase + "; …"}
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
				return "stepped to waypoint steps/2 (bundle " + short(toID) + ") in 71.2s: reconcile 3.9s; readiness e1 54.8s; push e1 1.6s, s1 2.4s"
			}},
		{name: "unchanged", args: []string{"--waypoint", "steps/3"}, plan: "plan-nothing.json",
			res: provision.StepResult{Outcome: provision.StepUnchanged, PushPlan: []wire.StepPush{},
				Timings: wire.StepTimings{WholeS: 1.8}, Record: &wire.TwinRecord{State: wire.StateReady}},
			code: findings.ExitOK, status: findings.StatusOK,
			closing: func(_, toID string) string {
				return "unchanged; the record moves to waypoint steps/3 (bundle " + short(toID) + ") in 1.8s"
			}, events: unchangedStepEvents()},
		{name: "diverged at push", args: []string{"--allow-restart"}, plan: "plan-link-added.json",
			res: provision.StepResult{Outcome: provision.StepDiverged, Phase: findings.StepPush, Step: findings.StepPush,
				PushPlan: pushed(wire.PushRefused, findings.RulePushRefused), Timings: timings,
				Record: &wire.TwinRecord{State: wire.StateDiverged},
				Findings: findings.List{
					{Severity: findings.Rejection, Rule: findings.RulePushRefused, Object: "e1", Step: findings.StepPush,
						Message: "node e1 refused artifact device-config (checksum 9f22a736…) at line 7: Invalid input"},
					diverged(findings.StepPush)}},
			code: findings.ExitUnclean, status: findings.StatusDiverged,
			closing: func(fromID, toID string) string {
				return "diverged towards waypoint steps/2 (bundle " + short(toID) + ") at phase push: landed s1; not landed e1 (push.refused); " +
					"the twin is up at waypoint steps/1 (bundle " + short(fromID) + "); fylgja twin destroy clears it"
			}},
		// The wait's clause follows M11's line on an unchanged and a diverged result too, as
		// contracts/cli.md quotes them.
		{name: "unchanged, the wait settled", args: []string{"--waypoint", "steps/3"}, plan: "plan-nothing.json",
			res: provision.StepResult{Outcome: provision.StepUnchanged, PushPlan: []wire.StepPush{},
				Timings: wire.StepTimings{WholeS: 1.8}, Record: &wire.TwinRecord{State: wire.StateReady},
				Wait: &wire.StepWait{Outcome: wire.WaitSettled, BudgetS: 120, Reads: 1, AfterS: 1.1, Failing: []wire.StepFinding{}}},
			code: findings.ExitOK, status: findings.StatusOK,
			closing: func(_, toID string) string {
				return "unchanged; the record moves to waypoint steps/3 (bundle " + short(toID) + ") in 1.8s; settled after 1.1s"
			}, events: unchangedStepEvents()},
		{name: "diverged at push, the wait settled", args: []string{"--allow-restart"}, plan: "plan-link-added.json",
			res: provision.StepResult{Outcome: provision.StepDiverged, Phase: findings.StepPush, Step: findings.StepPush,
				PushPlan: pushed(wire.PushRefused, findings.RulePushRefused), Timings: timings,
				Record: &wire.TwinRecord{State: wire.StateDiverged},
				Wait:   &wire.StepWait{Outcome: wire.WaitSettled, BudgetS: 120, Reads: 2, AfterS: 1.9, Failing: []wire.StepFinding{}},
				Findings: findings.List{
					{Severity: findings.Rejection, Rule: findings.RulePushRefused, Object: "e1", Step: findings.StepPush,
						Message: "node e1 refused artifact device-config (checksum 9f22a736…) at line 7: Invalid input"},
					diverged(findings.StepPush)}},
			code: findings.ExitUnclean, status: findings.StatusDiverged,
			closing: func(fromID, toID string) string {
				return "diverged towards waypoint steps/2 (bundle " + short(toID) + ") at phase push: landed s1; not landed e1 (push.refused); " +
					"the twin is up at waypoint steps/1 (bundle " + short(fromID) + "); fylgja twin destroy clears it; settled after 1.9s"
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
				return "diverged towards waypoint steps/2 (bundle " + short(toID) + ") at phase readiness: landed none; not landed e1, s1; " +
					"the twin is up at waypoint steps/1 (bundle " + short(fromID) + "); fylgja twin destroy clears it"
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
				in.From.Waypoint == nil || in.From.Waypoint.Sequence != 1 || in.To.Waypoint == nil || len(in.Diff) == 0 ||
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
			// once the step moves the twin. The command's second run filed the
			// target's CTM last, so its read's time is the one beside the bundle in the store.
			wantFrom := wire.StepSide{Waypoint: &wire.WaypointRef{Series: "steps", Sequence: 1,
				Description: "the mixed fixture as sealed", AtSource: "given"}, BundleID: h.fromID, At: stepMixedAt}
			wantTo := wire.StepSide{Waypoint: &wire.WaypointRef{Series: "steps", Sequence: 2,
				Description: "a link between e1 and s1", AtSource: "written"}, BundleID: toID, At: stepWrittenAt, Branch: "mixed-step"}
			wantPlan := wire.ReconcilePlan{Restarted: []string{"e1"}, LinksAdded: []string{"e1:eth2 -- s1:e1-2"},
				Reasons: map[string]string{"e1": "added link"}}
			if unchanged {
				wantTo = wire.StepSide{Waypoint: &wire.WaypointRef{Series: "steps", Sequence: 3, Description: "the fixture again",
					AtSource: "given"}, BundleID: toID, At: stepLaterAt, Branch: "mixed-fixture"}
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
			read, err := ctm.Load(filepath.Join(h.paths.Bundles, toID+".ctm.json"))
			if err != nil {
				t.Fatal(err)
			}
			firstAt, lastAt := svc.stepped[0].ObservedAt, svc.stepped[1].ObservedAt
			if lastAt != read.Envelope.ObservedAt {
				t.Errorf("the second run's observed_at %q; want its target read's, %q", lastAt, read.Envelope.ObservedAt)
			}
			if at, err := time.Parse(stage.ObservedAtFormat, firstAt); err != nil || at.Before(began) || firstAt > lastAt {
				t.Errorf("the first run's observed_at %q; want a read's time from %s to %s", firstAt, began.Format(stage.ObservedAtFormat), lastAt)
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
				Message: "step run " + stepRunID + " towards waypoint steps/2 stopped at phase readiness; …"}}}
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
		for _, f := range diverged.Findings {
			if !slices.Contains(doc.Findings, f) {
				t.Errorf("findings %+v lack the run's %+v", doc.Findings, f)
			}
		}
		tail := "\nstep readiness e1: begins\n" + waiting + "\ndiverged towards waypoint steps/2 (bundle " + short(doc.BundleID) +
			") at phase readiness: landed none; not landed e1, s1; the twin is up at waypoint steps/1 (bundle " + short(h.fromID) +
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
func TestStepWaitFlag(t *testing.T) {
	for _, c := range []struct {
		name  string
		args  []string
		waitS int
	}{
		{"left out", nil, 120},
		{"30s", []string{"--wait", "30s"}, 30},
		{"0", []string{"--wait=0"}, 0},
		{"2m", []string{"--wait", "2m"}, 120},
		{"a part of a second", []string{"--wait", "1500ms"}, 2},
	} {
		t.Run(c.name, func(t *testing.T) {
			stepHost(t, "plan-link-added.json", nil)
			svc := &fakeService{runID: stepRunID, events: stepEvents(), stepResult: provision.StepResult{Outcome: provision.StepStepped,
				Findings: findings.List{}, Record: &wire.TwinRecord{State: wire.StateReady}}}
			useService(t, svc)
			useInterrupts(t)
			out := runStepCmd(t, append([]string{"--allow-restart"}, c.args...)...)
			if out.code != findings.ExitOK || len(svc.stepped) != 2 {
				t.Fatalf("exit %d, %d runs started; want 0, one per run of the command; findings %+v", out.code, len(svc.stepped),
					out.doc.Findings)
			}
			for _, in := range svc.stepped {
				if in.WaitS != c.waitS {
					t.Errorf("the run's input carries wait_s %d, want %d", in.WaitS, c.waitS)
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
}

// The run prints how its wait ended after step record: and adds it to the closing line after
// M11's timings, in the words the warning begins with; M11's line is otherwise byte for byte
// what it was, and the exit is M11's (contracts/cli.md, twin step --wait).
// An activity that failed outright prints that the wait could not complete.
func TestStepRunReportsTheWait(t *testing.T) {
	const m11 = "stepped to waypoint steps/2 (bundle %s) in 71.2s: reconcile 3.9s; readiness e1 54.8s; push e1 1.6s, s1 2.4s"
	reconcile := 3.9
	e1Took, s1Took := 1.6, 2.4
	neighbor := func(object string) wire.StepFinding {
		return wire.StepFinding{Rule: findings.RuleVerifyNeighbor, Object: object, Message: "node " + object + " sees no neighbour"}
	}
	observed := func(detail string) provision.Event {
		return provision.Event{WorkflowID: provision.WorkflowStep, Step: "observe", End: true, Outcome: provision.EventDone,
			Duration: 2600 * time.Millisecond, Detail: detail}
	}
	for _, c := range []struct {
		name     string
		wait     *wire.StepWait
		event    provision.Event
		progress string
		clause   string
	}{
		{"settled", &wire.StepWait{Outcome: wire.WaitSettled, BudgetS: 120, Reads: 2, AfterS: 2.4, Failing: []wire.StepFinding{}},
			observed("settled after 2.4s (2 reads)"), "step observe: settled after 2.4s (2 reads)", "; settled after 2.4s"},
		{"expired", &wire.StepWait{Outcome: wire.WaitExpired, BudgetS: 120, Reads: 58, AfterS: 120,
			Failing: []wire.StepFinding{neighbor("s1:ethernet-1/3"), neighbor("e1:Ethernet3"), neighbor("e2:Ethernet1")}},
			observed("expired after 120.0s (58 reads, 3 failing)"), "step observe: expired after 120.0s (58 reads, 3 failing)",
			"; wait expired after 120.0s with 3 assertions failing"},
		{"cancelled", &wire.StepWait{Outcome: wire.WaitCancelled, BudgetS: 120, Reads: 7, AfterS: 12.4},
			observed("cancelled after 12.4s (7 reads)"), "step observe: cancelled after 12.4s (7 reads)", "; wait cancelled after 12.4s"},
		{"incomplete, the activity failed", &wire.StepWait{Outcome: wire.WaitIncomplete, BudgetS: 120,
			Failing: []wire.StepFinding{{Rule: findings.RuleOperationFailed, Object: "/state/twin/twin.json", Message: "disk full"}}},
			provision.Event{WorkflowID: provision.WorkflowStep, Step: "observe", End: true, Outcome: provision.EventFailed,
				Duration: 100 * time.Millisecond, Rule: findings.RuleOperationFailed, Message: "reading the twin's record for the step's wait: disk full"},
			"step observe: could not complete: reading the twin's record for the step's wait: disk full", "; wait could not complete"},
		// The end of VerifyTwin's window is not retried, and the service closes the activity
		// timed out: the wait could not complete, as for one that failed outright.
		{"incomplete, the window ended", &wire.StepWait{Outcome: wire.WaitIncomplete, BudgetS: 120,
			Failing: []wire.StepFinding{{Rule: findings.RuleOperationFailed, Object: stepRunID,
				Message: "activity ScheduleToClose timeout (type: ScheduleToClose)"}}},
			provision.Event{WorkflowID: provision.WorkflowStep, Step: "observe", End: true, Outcome: provision.EventTimedOut,
				Duration: 150 * time.Second, Message: "activity ScheduleToClose timeout"},
			"step observe: could not complete: activity ScheduleToClose timeout", "; wait could not complete"},
		{"the wait not run", nil, provision.Event{}, "", ""},
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
				Record: &wire.TwinRecord{State: wire.StateReady}, Wait: c.wait,
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
		})
	}
}
