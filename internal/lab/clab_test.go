package lab

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"reflect"
	"runtime"
	"slices"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// call is one invocation a fakeRunner saw.
type call struct {
	env  []string
	args []string
}

// reply is what a fakeRunner answers for one containerlab subcommand.
type reply struct {
	stdout, stderr []byte
	exit           int
	err            error
}

// fakeRunner stands in for containerlab with outputs recorded from the real
// tool,
// keyed by subcommand: inspect, deploy, destroy.
type fakeRunner struct {
	replies map[string][]reply // consumed in order; the last one repeats
	calls   []call
}

func (f *fakeRunner) Run(_ context.Context, env []string, args ...string) ([]byte, []byte, int, error) {
	f.calls = append(f.calls, call{env: env, args: args})
	sub := ""
	if len(args) > 1 {
		sub = args[1]
	}
	queue := f.replies[sub]
	if len(queue) == 0 {
		return nil, []byte("fakeRunner: no reply for " + sub), 1, nil
	}
	r := queue[0]
	if len(queue) > 1 {
		f.replies[sub] = queue[1:]
	}
	return r.stdout, r.stderr, r.exit, r.err
}

func recorded(t *testing.T, name string) []byte {
	t.Helper()
	b, err := os.ReadFile(filepath.Join("testdata", name))
	if err != nil {
		t.Fatal(err)
	}
	return b
}

// quietClab is a Clab over r that logs nowhere and sees an empty process table, so no test
// lists or kills the host's real processes.
func quietClab(r Runner) *Clab {
	return &Clab{Runner: r, Log: slog.New(slog.NewTextHandler(&bytes.Buffer{}, nil)), Procs: &fakeProcs{}}
}

func TestInspectAllAbsent(t *testing.T) {
	f := &fakeRunner{replies: map[string][]reply{"inspect": {{stdout: recorded(t, "inspect-empty.json")}}}}
	state, err := quietClab(f).InspectAll(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if state.Present || len(state.Nodes) != 0 || len(state.TopoPaths) != 0 {
		t.Errorf("state = %+v, want absent, with no topology path", state)
	}
	want := []string{"clab", "inspect", "--all", "--format", "json"}
	if len(f.calls) != 1 || !reflect.DeepEqual(f.calls[0].args, want) || f.calls[0].env != nil {
		t.Errorf("calls = %+v, want exactly %v with no environment override", f.calls, want)
	}
}

func TestInspectAllThreeRunningNodes(t *testing.T) {
	f := &fakeRunner{replies: map[string][]reply{"inspect": {{stdout: recorded(t, "inspect-three.json")}}}}
	state, err := quietClab(f).InspectAll(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if !state.Present || len(state.Nodes) != 3 {
		t.Fatalf("state = %+v, want lab fylgja with three nodes", state)
	}
	for i, want := range []struct{ name, addr string }{
		{"n1", "172.20.20.2"}, {"n2", "172.20.20.3"}, {"n3", "172.20.20.4"},
	} {
		n := state.Nodes[i]
		if n.Name != want.name || n.MgmtIPv4 != want.addr || n.Container != "clab-fylgja-"+want.name ||
			n.Kind != "nokia_srlinux" || n.State != "running" || n.Image != "ghcr.io/nokia/srlinux:24.7.1" {
			t.Errorf("node %d = %+v, want %s at %s", i, n, want.name, want.addr)
		}
	}
	if want := []string{"/tmp/scratchpad/twin3/bundle/topology.clab.yml"}; !reflect.DeepEqual(state.TopoPaths, want) {
		t.Errorf("TopoPaths = %q, want %q: three containers from one topology name it once", state.TopoPaths, want)
	}
}

// A lab deployed by hand from outside the state root: containerlab's absLabPath names the
// topology it came from, whatever the caller's directory.
func TestInspectAllOrphanTopoPath(t *testing.T) {
	f := &fakeRunner{replies: map[string][]reply{"inspect": {{stdout: recorded(t, "inspect-one-orphan.json")}}}}
	state, err := quietClab(f).InspectAll(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if !state.Present || len(state.Nodes) != 1 || state.Nodes[0].Name != "n1" {
		t.Fatalf("state = %+v, want lab fylgja with one node n1", state)
	}
	if want := []string{"/tmp/scratchpad/orphan/topology.clab.yml"}; !reflect.DeepEqual(state.TopoPaths, want) {
		t.Errorf("TopoPaths = %q, want %q", state.TopoPaths, want)
	}
}

// Containers that disagree on their topology are named with every distinct path, sorted.
// inspect-three-paths.json is hand-edited from inspect-three.json (n3's labPath and
// absLabPath only): containerlab never produced two paths for one lab here.
func TestInspectAllDistinctTopoPaths(t *testing.T) {
	f := &fakeRunner{replies: map[string][]reply{"inspect": {{stdout: recorded(t, "inspect-three-paths.json")}}}}
	state, err := quietClab(f).InspectAll(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if !state.Present || len(state.Nodes) != 3 {
		t.Fatalf("state = %+v, want lab fylgja with three nodes", state)
	}
	want := []string{"/tmp/scratchpad/elsewhere/topology.clab.yml", "/tmp/scratchpad/twin3/bundle/topology.clab.yml"}
	if !reflect.DeepEqual(state.TopoPaths, want) {
		t.Errorf("TopoPaths = %q, want %q", state.TopoPaths, want)
	}
}

// Another lab on the host is somebody else's: lab fylgja is absent.
func TestInspectAllIgnoresOtherLabs(t *testing.T) {
	other := []byte(`{"srl01":[{"name":"clab-srl01-a","kind":"nokia_srlinux","state":"running","ipv4_address":"172.20.20.9/24"}]}`)
	f := &fakeRunner{replies: map[string][]reply{"inspect": {{stdout: other}}}}
	state, err := quietClab(f).InspectAll(context.Background())
	if err != nil || state.Present {
		t.Errorf("state = %+v, %v; want lab fylgja absent", state, err)
	}
}

func TestInspectAllFailureCarriesStderr(t *testing.T) {
	f := &fakeRunner{replies: map[string][]reply{"inspect": {{
		stderr: []byte(`   ERROR  Unknown container runtime "bogus".` + "\n"), exit: 1,
	}}}}
	_, err := quietClab(f).InspectAll(context.Background())
	var tool *ToolError
	if !errors.As(err, &tool) || tool.Exit != 1 || !strings.Contains(err.Error(), "Unknown container runtime") {
		t.Errorf("err = %v; want a *ToolError carrying exit 1 and stderr", err)
	}
}

func TestDeployArgumentsAndLabDirectory(t *testing.T) {
	for _, reconfigure := range []bool{false, true} {
		f := &fakeRunner{replies: map[string][]reply{"deploy": {{stdout: recorded(t, "deploy-one.json")}}}}
		state, err := quietClab(f).Deploy(context.Background(), "/s/twin/bundle/topology.clab.yml", "/s/twin", reconfigure)
		if err != nil {
			t.Fatal(err)
		}
		want := []string{"clab", "deploy", "--topo", "/s/twin/bundle/topology.clab.yml", "--format", "json"}
		if reconfigure {
			want = append(want, "--reconfigure")
		}
		if len(f.calls) != 1 || !reflect.DeepEqual(f.calls[0].args, want) {
			t.Errorf("reconfigure=%v: args = %v, want %v", reconfigure, f.calls, want)
		}
		if !reflect.DeepEqual(f.calls[0].env, []string{"CLAB_LABDIR_BASE=/s/twin"}) {
			t.Errorf("env = %v, want the lab directory override alone", f.calls[0].env)
		}
		if !state.Present || len(state.Nodes) != 1 || state.Nodes[0].Name != "n1" || state.Nodes[0].MgmtIPv4 != "172.20.20.2" {
			t.Errorf("state = %+v, want n1 at 172.20.20.2", state)
		}
	}
}

// A failed deploy prints nothing on stdout and explains itself on stderr; the
// explanation is what an operator needs, so it must survive into the error.
func TestDeployFailureSurfacesStderr(t *testing.T) {
	f := &fakeRunner{replies: map[string][]reply{"deploy": {{stderr: recorded(t, "deploy-failed.stderr"), exit: 1}}}}
	_, err := quietClab(f).Deploy(context.Background(), "/s/twin/bundle/topology.clab.yml", "/s/twin", false)
	var tool *ToolError
	if !errors.As(err, &tool) || tool.Exit != 1 {
		t.Fatalf("err = %v; want a *ToolError with exit 1", err)
	}
	if !strings.Contains(tool.Stderr, "Failed to parse value 'e1-1'") {
		t.Errorf("stderr lost SR Linux's reason: %q", tool.Stderr)
	}
}

func TestDestroyArguments(t *testing.T) {
	f := &fakeRunner{replies: map[string][]reply{"destroy": {{}}}}
	if err := quietClab(f).Destroy(context.Background()); err != nil {
		t.Fatal(err)
	}
	want := []string{"clab", "destroy", "--name", "fylgja", "--cleanup"}
	if len(f.calls) != 1 || !reflect.DeepEqual(f.calls[0].args, want) || f.calls[0].env != nil {
		t.Errorf("calls = %+v, want exactly %v", f.calls, want)
	}

	f = &fakeRunner{replies: map[string][]reply{"destroy": {{stderr: []byte("boom"), exit: 1}}}}
	if err := quietClab(f).Destroy(context.Background()); err == nil {
		t.Error("a failed destroy must be an error")
	}
}

// Every invocation is logged with its arguments and environment override, so a broken
// lab can be reproduced by hand.
func TestEveryInvocationIsLogged(t *testing.T) {
	var buf bytes.Buffer
	f := &fakeRunner{replies: map[string][]reply{
		"inspect": {{stdout: []byte("{}")}},
		"deploy":  {{stdout: recorded(t, "deploy-one.json")}},
		"destroy": {{}},
	}}
	c := &Clab{Runner: f, Log: slog.New(slog.NewTextHandler(&buf, nil))}
	ctx := context.Background()
	if _, err := c.InspectAll(ctx); err != nil {
		t.Fatal(err)
	}
	if _, err := c.Deploy(ctx, "/s/twin/bundle/topology.clab.yml", "/s/twin", true); err != nil {
		t.Fatal(err)
	}
	if err := c.Destroy(ctx); err != nil {
		t.Fatal(err)
	}
	out := buf.String()
	for _, want := range []string{
		"clab inspect --all --format json",
		"clab deploy --topo /s/twin/bundle/topology.clab.yml --format json --reconfigure",
		"CLAB_LABDIR_BASE=/s/twin",
		"clab destroy --name fylgja --cleanup",
	} {
		if !strings.Contains(out, want) {
			t.Errorf("log does not carry %q:\n%s", want, out)
		}
	}
}

// A failed invocation is logged at Warn with its arguments and environment override, so a
// logger that keeps only warnings (the dry run's) still records the command that broke;
// a successful one logs nothing there. Only the override is logged, never the
// inherited environment.
func TestFailedInvocationIsLoggedAtWarn(t *testing.T) {
	t.Setenv("FYLGJA_TEST_INHERITED", "inherited-sentinel")
	var buf bytes.Buffer
	f := &fakeRunner{replies: map[string][]reply{
		"inspect": {{stdout: []byte("{}")}, {stderr: []byte("boom"), exit: 1}},
		"deploy":  {{stderr: recorded(t, "deploy-failed.stderr"), exit: 1}},
	}}
	c := &Clab{Runner: f, Log: slog.New(slog.NewTextHandler(&buf, &slog.HandlerOptions{Level: slog.LevelWarn}))}
	ctx := context.Background()

	if _, err := c.InspectAll(ctx); err != nil {
		t.Fatal(err)
	}
	if buf.Len() != 0 {
		t.Fatalf("a successful invocation logged at Warn:\n%s", buf.String())
	}
	if _, err := c.InspectAll(ctx); err == nil {
		t.Fatal("a non-zero inspect must be an error")
	}
	if _, err := c.Deploy(ctx, "/s/twin/bundle/topology.clab.yml", "/s/twin", false); err == nil {
		t.Fatal("a non-zero deploy must be an error")
	}

	lines := strings.Split(strings.TrimSuffix(buf.String(), "\n"), "\n")
	if len(lines) != 2 {
		t.Fatalf("logged %d lines, want one per failed invocation:\n%s", len(lines), buf.String())
	}
	for i, want := range [][]string{
		{"level=WARN", "clab inspect --all --format json", "exit=1", "boom"},
		{"level=WARN", "clab deploy --topo /s/twin/bundle/topology.clab.yml --format json", "CLAB_LABDIR_BASE=/s/twin", "exit=1"},
	} {
		for _, s := range want {
			if !strings.Contains(lines[i], s) {
				t.Errorf("line %d does not carry %q:\n%s", i+1, s, lines[i])
			}
		}
	}
	if strings.Contains(buf.String(), "inherited-sentinel") {
		t.Errorf("the inherited environment reached the log:\n%s", buf.String())
	}
}

// Every child starts in its own process group and dies with the thread that started it,
// so a clab never outlives the worker. Silent when missing, so pinned.
func TestExecRunnerChildAttributes(t *testing.T) {
	attr := childSysProcAttr()
	if !attr.Setpgid || attr.Pdeathsig != syscall.SIGKILL {
		t.Errorf("SysProcAttr = {Setpgid:%v Pdeathsig:%v}, want a new process group and SIGKILL",
			attr.Setpgid, attr.Pdeathsig)
	}
}

// Cancelling kills the child's whole process group, promptly: a grandchild left alive
// would keep acting on the host after the activity reported itself stopped, and would hold
// the output pipe open past the runner's wait.
func TestExecRunnerCancelKillsTheProcessGroup(t *testing.T) {
	if runtime.GOOS != "linux" {
		t.Skip("the lab host is Linux; process groups and Pdeathsig are exercised there")
	}
	t.Parallel()
	pidFile := filepath.Join(t.TempDir(), "grandchild.pid")
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	done := make(chan error, 1)
	go func() {
		_, _, _, err := ExecRunner{}.Run(ctx, nil, "sh", "-c", `sleep 30 & echo $! > "$1"; sleep 30`, "sh", pidFile)
		done <- err
	}()

	grandchild := waitForPID(t, pidFile)
	cancelled := time.Now()
	cancel()
	var err error
	select {
	case err = <-done:
	case <-time.After(10 * time.Second):
		t.Fatal("the runner had not returned 10s after cancellation")
	}
	if took := time.Since(cancelled); took > time.Second {
		t.Errorf("the runner returned %v after cancellation, want within a second", took)
	}
	if !errors.Is(err, context.Canceled) {
		t.Errorf("err = %v, want the cancellation", err)
	}
	for deadline := time.Now().Add(time.Second); alive(grandchild); time.Sleep(10 * time.Millisecond) {
		if time.Now().After(deadline) {
			t.Fatalf("grandchild %d outlived its cancelled process group", grandchild)
		}
	}
}

// waitForPID reads the pid a shell wrote to path, once it has written all of it.
func waitForPID(t *testing.T, path string) int {
	t.Helper()
	for deadline := time.Now().Add(5 * time.Second); time.Now().Before(deadline); time.Sleep(5 * time.Millisecond) {
		b, err := os.ReadFile(path)
		if err != nil || !bytes.HasSuffix(b, []byte("\n")) {
			continue
		}
		if pid, err := strconv.Atoi(strings.TrimSpace(string(b))); err == nil {
			return pid
		}
	}
	t.Fatal("the shell never reported its background child")
	return 0
}

// alive reports whether pid is a process that has not exited: present, and not a zombie.
func alive(pid int) bool {
	b, err := os.ReadFile(fmt.Sprintf("/proc/%d/stat", pid))
	if err != nil {
		return false
	}
	i := bytes.LastIndexByte(b, ')')
	return i < 0 || i+2 >= len(b) || b[i+2] != 'Z'
}

// DeployPlan reads each of containerlab's dry-run plans into the lists it acts on, and
// Nodes says what containerlab does to each node a plan touches. The documents are
// plans containerlab 0.79.0 printed, in the shape it printed them.
func TestDeployPlanParsesEachDocument(t *testing.T) {
	empty := wire.ReconcilePlan{Added: []string{}, Deleted: []string{}, Recreated: []string{}, Restarted: []string{},
		LinksAdded: []string{}, EndpointsDeleted: []string{}}
	with := func(change func(p *wire.ReconcilePlan)) wire.ReconcilePlan {
		p := empty
		change(&p)
		return p
	}
	for _, c := range []struct {
		file  string
		plan  wire.ReconcilePlan
		nodes []wire.PlanNode
	}{
		{"plan-nothing.json", empty, []wire.PlanNode{}},
		// An image change read without the lab's state is invisible: an empty plan.
		{"plan-image-unseen.json", empty, []wire.PlanNode{}},
		{"plan-link-added.json", with(func(p *wire.ReconcilePlan) {
			p.Restarted, p.LinksAdded, p.Reasons = []string{"e1"}, []string{"e1:eth2 -- s1:e1-2"}, map[string]string{"e1": "added link"}
		}), []wire.PlanNode{{Node: "e1", Reported: "restart", Reason: "added link"}, {Node: "s1", Reported: "live"}}},
		{"plan-endpoint-deleted.json", with(func(p *wire.ReconcilePlan) {
			p.Restarted, p.EndpointsDeleted, p.Reasons = []string{"e1"}, []string{"e1:eth2", "s1:e1-2"}, map[string]string{"e1": "deleted endpoint"}
		}), []wire.PlanNode{{Node: "e1", Reported: "restart", Reason: "deleted endpoint"}, {Node: "s1", Reported: "live"}}},
		{"plan-node-added.json", with(func(p *wire.ReconcilePlan) {
			p.Added, p.LinksAdded = []string{"s2"}, []string{"s1:e1-3 -- s2:e1-1"}
		}), []wire.PlanNode{{Node: "s1", Reported: "live"}, {Node: "s2", Reported: "create"}}},
		{"plan-node-removed.json", with(func(p *wire.ReconcilePlan) {
			p.Deleted, p.EndpointsDeleted = []string{"e1"}, []string{"s1:e1-1"}
		}), []wire.PlanNode{{Node: "s1", Reported: "live"}}},
		{"plan-image-changed.json", with(func(p *wire.ReconcilePlan) {
			p.Recreated, p.Reasons = []string{"s2"}, map[string]string{"s2": "config drift: Image"}
		}), []wire.PlanNode{{Node: "s2", Reported: "recreate", Reason: "config drift: Image"}}},
		{"plan-kind-changed.json", with(func(p *wire.ReconcilePlan) {
			p.Recreated, p.Restarted, p.LinksAdded, p.EndpointsDeleted = []string{"s1"}, []string{"e1"}, []string{"e1:eth1 -- s1:eth1"}, []string{"s1:e1-1"}
			p.Reasons = map[string]string{"s1": "config drift: Kind, Image", "e1": "added link"}
		}), []wire.PlanNode{{Node: "e1", Reported: "restart", Reason: "added link"},
			{Node: "s1", Reported: "recreate", Reason: "config drift: Kind, Image"}}},
	} {
		t.Run(c.file, func(t *testing.T) {
			f := &fakeRunner{replies: map[string][]reply{"deploy": {{stdout: recorded(t, c.file),
				stderr: []byte("INFO Containerlab started version=0.79.0\n")}}}}
			plan, err := quietClab(f).DeployPlan(context.Background(), "/s/bundles/ee29/topology.clab.yml", "/s/twin")
			if err != nil {
				t.Fatal(err)
			}
			if !reflect.DeepEqual(plan, c.plan) {
				t.Errorf("plan:\n got %+v\nwant %+v", plan, c.plan)
			}
			if got := plan.Nodes(); !reflect.DeepEqual(got, c.nodes) {
				t.Errorf("Nodes:\n got %+v\nwant %+v", got, c.nodes)
			}
			if plan.Empty() != (len(c.nodes) == 0) {
				t.Errorf("Empty() = %v", plan.Empty())
			}
		})
	}
}

// The plan is a dry run of the target's topology with containerlab's lab directory at the
// twin directory, where the lab's state is: the runner gets exactly that.
func TestDeployPlanArguments(t *testing.T) {
	f := &fakeRunner{replies: map[string][]reply{"deploy": {{stdout: recorded(t, "plan-nothing.json")}}}}
	if _, err := quietClab(f).DeployPlan(context.Background(), "/s/bundles/ee29/topology.clab.yml", "/s/twin"); err != nil {
		t.Fatal(err)
	}
	want := []string{"clab", "deploy", "--dry-run", "--topo", "/s/bundles/ee29/topology.clab.yml", "--format", "json"}
	if len(f.calls) != 1 || !reflect.DeepEqual(f.calls[0].args, want) {
		t.Errorf("args = %v, want %v", f.calls, want)
	}
	if !reflect.DeepEqual(f.calls[0].env, []string{"CLAB_LABDIR_BASE=/s/twin"}) {
		t.Errorf("env = %v, want the twin directory as the lab directory base alone", f.calls[0].env)
	}
}

// A plan that would deploy the lab afresh is no reconcile: containerlab found no running lab
// under the twin directory (containerlab 0.79.0's answer, verbatim). Neither is a document that
// is not a dry run, nor one that is not JSON; a failed dry run is containerlab's error.
func TestDeployPlanRefuses(t *testing.T) {
	for _, c := range []struct {
		name  string
		reply reply
		want  string
	}{
		{"a fresh deploy", reply{stdout: recorded(t, "plan-no-lab.json")},
			"containerlab's plan would deploy lab m11-run3-probe afresh: it finds no running lab to reconcile under /s/twin"},
		{"not a dry run", reply{stdout: recorded(t, "deploy-one.json")}, "is not a dry-run plan"},
		{"a dry run that says it is not one", reply{stdout: []byte(`{"dry-run": false, "deployed-lab": false}`)}, "is not a dry-run plan"},
		{"not JSON", reply{stdout: []byte("plan")}, "reading containerlab's dry-run plan"},
		{"containerlab failed", reply{stderr: []byte(`Arista cEOS node "s1" has an interface named "e1-1" which doesn't match the required pattern`), exit: 1},
			"exited 1: Arista cEOS node"},
	} {
		t.Run(c.name, func(t *testing.T) {
			f := &fakeRunner{replies: map[string][]reply{"deploy": {c.reply}}}
			if _, err := quietClab(f).DeployPlan(context.Background(), "/s/bundles/ee29/topology.clab.yml", "/s/twin"); err == nil ||
				!strings.Contains(err.Error(), c.want) {
				t.Errorf("err = %v, want one saying %q", err, c.want)
			}
		})
	}
}

// Reconcile is Deploy's command without --reconfigure, which would recreate every node, and
// logs containerlab's account of what it did to each node; Deploy
// keeps --reconfigure for a present lab (TestDeployArgumentsAndLabDirectory).
func TestReconcileArgumentsAndLifecycleLines(t *testing.T) {
	stderr := "02:01:30 INFO Applying link change without node lifecycle action node=s1 change=\"added link\"\n" +
		"02:01:31 INFO Restarting node after link apply node=e1\n" +
		"02:01:32 INFO Created link: e1:eth3 ▪┄┄▪ s1:e1-3\n"
	f := &fakeRunner{replies: map[string][]reply{"deploy": {{stdout: recorded(t, "deploy-one.json"), stderr: []byte(stderr)}}}}
	var logged bytes.Buffer
	c := &Clab{Runner: f, Log: slog.New(slog.NewTextHandler(&logged, nil)), Procs: &fakeProcs{}}
	state, err := c.Reconcile(context.Background(), "/s/twin/bundle/topology.clab.yml", "/s/twin")
	if err != nil {
		t.Fatal(err)
	}
	want := []string{"clab", "deploy", "--topo", "/s/twin/bundle/topology.clab.yml", "--format", "json"}
	if len(f.calls) != 1 || !reflect.DeepEqual(f.calls[0].args, want) || slices.Contains(f.calls[0].args, "--reconfigure") {
		t.Errorf("args = %v, want %v and no --reconfigure", f.calls, want)
	}
	if !reflect.DeepEqual(f.calls[0].env, []string{"CLAB_LABDIR_BASE=/s/twin"}) {
		t.Errorf("env = %v", f.calls[0].env)
	}
	if !state.Present || len(state.Nodes) != 1 {
		t.Errorf("state = %+v, want the inspect document parsed as a deploy's", state)
	}
	for _, line := range []string{"Restarting node after link apply node=e1", "Applying link change without node lifecycle action node=s1"} {
		if !strings.Contains(logged.String(), line) {
			t.Errorf("the log does not carry %q:\n%s", line, logged.String())
		}
	}
	if strings.Contains(logged.String(), "line=\"02:01:32 INFO Created link") {
		t.Errorf("a line naming no node's lifecycle was logged as one:\n%s", logged.String())
	}

	f = &fakeRunner{replies: map[string][]reply{"deploy": {{stderr: recorded(t, "deploy-failed.stderr"), exit: 1}}}}
	var tool *ToolError
	if _, err := quietClab(f).Reconcile(context.Background(), "/s/twin/bundle/topology.clab.yml", "/s/twin"); !errors.As(err, &tool) {
		t.Errorf("a failed reconcile: err = %v, want a *ToolError", err)
	}
}
