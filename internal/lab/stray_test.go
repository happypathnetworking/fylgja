package lab

import (
	"context"
	"path/filepath"
	"slices"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// fakeProcs is a process table: a kill removes the process, unless stubborn keeps it.
type fakeProcs struct {
	mu       sync.Mutex
	procs    []Process
	kills    []int
	killErr  error
	stubborn bool
	onKill   func(pid int)
}

func (f *fakeProcs) Processes() ([]Process, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	return slices.Clone(f.procs), nil
}

func (f *fakeProcs) Kill(pid int) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.kills = append(f.kills, pid)
	if f.onKill != nil {
		f.onKill(pid)
	}
	if f.killErr != nil {
		return f.killErr
	}
	if !f.stubborn {
		f.procs = slices.DeleteFunc(f.procs, func(p Process) bool { return p.PID == pid })
	}
	return nil
}

func (f *fakeProcs) killed() []int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return slices.Clone(f.kills)
}

const strayTopo = "/state/twin/bundle/topology.clab.yml"

func TestActsOnLab(t *testing.T) {
	for _, c := range []struct {
		args string
		want bool
	}{
		{"clab deploy --topo " + strayTopo + " --format json", true},
		{"clab deploy --topo " + strayTopo + " --format json --reconfigure", true},
		{"/usr/bin/containerlab deploy -t " + strayTopo, true},
		{"clab deploy --topo=" + strayTopo, true},
		{"clab destroy --name fylgja --cleanup", true},
		{"clab destroy -n fylgja", true},
		{"clab inspect --all --format json", false},
		{"clab inspect --name fylgja", false},
		{"clab deploy --topo /home/op/other/topology.clab.yml", false},
		{"clab destroy --name srl01 --cleanup", false},
		{"vim " + strayTopo, false},
		{"clab", false},
	} {
		if got := actsOnLab(strings.Fields(c.args), strayTopo); got != c.want {
			t.Errorf("actsOnLab(%q) = %v, want %v", c.args, got, c.want)
		}
	}
}

// Only a containerlab deploying or destroying lab fylgja is stopped, and StopStrays returns
// once it is gone.
func TestStopStraysKillsOnlyAContainerlabActingOnLabFylgja(t *testing.T) {
	procs := &fakeProcs{procs: []Process{
		{PID: 101, Args: strings.Fields("clab deploy --topo " + strayTopo + " --format json")},
		{PID: 102, Args: strings.Fields("clab destroy --name fylgja --cleanup")},
		{PID: 103, Args: strings.Fields("clab inspect --all --format json")},
		{PID: 104, Args: strings.Fields("clab deploy --topo /home/op/other/topology.clab.yml")},
		{PID: 105, Args: strings.Fields("vim " + strayTopo)},
	}}
	c := quietClab(&fakeRunner{})
	c.Procs = procs

	stopped, err := c.StopStrays(context.Background(), strayTopo)
	if err != nil {
		t.Fatal(err)
	}
	if got := procs.killed(); !slices.Equal(got, []int{101, 102}) {
		t.Errorf("killed %v, want 101 and 102 only", got)
	}
	if len(stopped) != 2 {
		t.Errorf("stopped %+v, want the two acting on lab fylgja", stopped)
	}
	left, _ := procs.Processes()
	if len(left) != 3 {
		t.Errorf("processes left %+v, want the three that act on nothing of Fylgja's", left)
	}
}

func TestStopStraysNamesAContainerlabThatWillNotStop(t *testing.T) {
	stray := Process{PID: 4242, Args: strings.Fields("clab deploy --topo " + strayTopo)}
	t.Run("the kill is refused", func(t *testing.T) {
		c := quietClab(&fakeRunner{})
		c.Procs = &fakeProcs{procs: []Process{stray}, killErr: syscall.EPERM}
		_, err := c.StopStrays(context.Background(), strayTopo)
		if err == nil || !strings.Contains(err.Error(), "4242") || !strings.Contains(err.Error(), "sudo kill -9 4242") {
			t.Errorf("error %v, want pid 4242 named with the command that stops it", err)
		}
	})
	t.Run("the process outlives the kill", func(t *testing.T) {
		c := quietClab(&fakeRunner{})
		c.Procs = &fakeProcs{procs: []Process{stray}, stubborn: true}
		ctx, cancel := context.WithTimeout(context.Background(), 150*time.Millisecond)
		defer cancel()
		_, err := c.StopStrays(ctx, strayTopo)
		if err == nil || !strings.Contains(err.Error(), "after it was killed") || !strings.Contains(err.Error(), "4242") {
			t.Errorf("error %v, want pid 4242 named as still running after the kill", err)
		}
	})
}

// A deploy retried after its worker was killed stops the earlier attempt's clab before it
// runs anything, then reconfigures the partial lab: one deploy acts on the lab at a time.
func TestDeployLabStopsAStrayDeployFirst(t *testing.T) {
	f := &fakeRunner{replies: map[string][]reply{
		"inspect": {{stdout: recorded(t, "inspect-three.json")}},
		"deploy":  {{stdout: recorded(t, "inspect-three.json")}},
	}}
	a := testActivities(t, f)
	topo := filepath.Join(a.Paths.TwinBundle, "topology.clab.yml")
	callsAtKill := -1
	procs := &fakeProcs{
		procs:  []Process{{PID: 1824220, Args: []string{"clab", "deploy", "--topo", topo, "--format", "json"}}},
		onKill: func(int) { callsAtKill = len(f.calls) },
	}
	a.Clab.Procs = procs

	if _, err := a.DeployLab(context.Background(), wire.DeployInput{TwinDir: a.Paths.Twin, Nodes: threeNodePlan()}); err != nil {
		t.Fatal(err)
	}
	if got := procs.killed(); !slices.Equal(got, []int{1824220}) || callsAtKill != 0 {
		t.Errorf("killed %v with %d containerlab calls already made; want the stray killed before any", got, callsAtKill)
	}
	var deploys []string
	for _, c := range f.calls {
		if c.args[1] == "deploy" {
			deploys = append(deploys, strings.Join(c.args, " "))
		}
	}
	if len(deploys) != 1 || !strings.HasSuffix(deploys[0], "--reconfigure") {
		t.Errorf("deploys %v, want exactly one, reconfiguring the partial lab", deploys)
	}
}

// A stray that cannot be stopped is deploy.failed naming it, and nothing is deployed beside
// it.
func TestDeployLabRefusesToDeployBesideAStrayItCannotStop(t *testing.T) {
	f := &fakeRunner{}
	a := testActivities(t, f)
	a.Clab.Procs = &fakeProcs{
		procs:   []Process{{PID: 4242, Args: []string{"clab", "deploy", "--topo", filepath.Join(a.Paths.TwinBundle, "topology.clab.yml")}}},
		killErr: syscall.EPERM,
	}

	_, err := a.DeployLab(context.Background(), wire.DeployInput{TwinDir: a.Paths.Twin, Nodes: threeNodePlan()})
	got := stepFailure(t, err, findings.RuleDeployFailed)
	if !strings.Contains(got.Message, "4242") || !strings.Contains(got.Message, "no second deploy") {
		t.Errorf("message %q, want the stray named and no second deploy started", got.Message)
	}
	if len(f.calls) != 0 {
		t.Errorf("containerlab was run %+v beside a stray", f.calls)
	}
}

// A step's reconcile stops a containerlab still acting on the lab before it applies the
// target, as a deploy does: one containerlab acts on the lab at a time.
func TestReconcileLabStopsAStrayFirst(t *testing.T) {
	f := &fakeRunner{replies: map[string][]reply{"deploy": {{stdout: recorded(t, "deploy-one.json")}}}}
	a, _ := steppingTwin(t, f)
	callsAtKill := -1
	// The stop takes a while, as a stray clab that finishes its own work does, and none of
	// that wait is the apply's: took_s runs from clab deploy's start.
	const stopTakes = 300 * time.Millisecond
	procs := &fakeProcs{
		procs: []Process{{PID: 1824221, Args: []string{"clab", "deploy", "--topo", filepath.Join(a.Paths.TwinBundle, "topology.clab.yml"), "--format", "json"}}},
		onKill: func(int) {
			callsAtKill = len(f.calls)
			time.Sleep(stopTakes)
		},
	}
	a.Clab.Procs = procs

	in := wire.ReconcileInput{TwinDir: a.Paths.Twin, Nodes: []wire.NodePlan{{Name: "n1", DeployTimeoutS: 120}},
		Plan: wire.ReconcilePlan{Restarted: []string{"n1"}}}
	res, err := a.ReconcileLab(context.Background(), in)
	if err != nil {
		t.Fatal(err)
	}
	if got := procs.killed(); !slices.Equal(got, []int{1824221}) || callsAtKill != 0 {
		t.Errorf("killed %v with %d containerlab calls already made; want the stray killed before any", got, callsAtKill)
	}
	if res.TookS >= stopTakes.Seconds() {
		t.Errorf("the reconcile took %vs, want less than the %v the stray's stop took: the wait is not the apply's", res.TookS, stopTakes)
	}
	if len(f.calls) != 1 || f.calls[0].args[1] != "deploy" {
		t.Errorf("containerlab saw %+v, want the one apply", f.calls)
	}
}

// A stray the reconcile cannot stop is deploy.failed at step reconcile naming it, and
// nothing is applied beside it.
func TestReconcileLabRefusesToReconcileBesideAStrayItCannotStop(t *testing.T) {
	f := &fakeRunner{}
	a, _ := steppingTwin(t, f)
	a.Clab.Procs = &fakeProcs{
		procs:   []Process{{PID: 4243, Args: []string{"clab", "deploy", "--topo", filepath.Join(a.Paths.TwinBundle, "topology.clab.yml")}}},
		killErr: syscall.EPERM,
	}

	_, err := a.ReconcileLab(context.Background(), wire.ReconcileInput{TwinDir: a.Paths.Twin,
		Nodes: []wire.NodePlan{{Name: "n1", DeployTimeoutS: 120}}, Plan: wire.ReconcilePlan{Restarted: []string{"n1"}}})
	got := stepFailure(t, err, findings.RuleDeployFailed)
	if got.Step != findings.StepReconcile || got.Object != "lab fylgja" ||
		!strings.Contains(got.Message, "4243") || !strings.Contains(got.Message, "no second deploy") {
		t.Errorf("finding %+v, want step reconcile on lab fylgja, the stray named and no second deploy started", got)
	}
	if len(f.calls) != 0 {
		t.Errorf("containerlab was run %+v beside a stray", f.calls)
	}
}

// A teardown stops a containerlab still acting on the lab before it destroys it.
func TestDestroyLabStopsAStrayFirst(t *testing.T) {
	f := &fakeRunner{replies: map[string][]reply{
		"inspect": {{stdout: recorded(t, "inspect-three.json")}, {stdout: recorded(t, "inspect-empty.json")}},
		"destroy": {{}},
	}}
	a := testActivities(t, f)
	callsAtKill := -1
	procs := &fakeProcs{
		procs:  []Process{{PID: 77, Args: strings.Fields("clab deploy --topo " + filepath.Join(a.Paths.TwinBundle, "topology.clab.yml") + " --format json")}},
		onKill: func(int) { callsAtKill = len(f.calls) },
	}
	a.Clab.Procs = procs

	res, err := a.DestroyLab(context.Background(), wire.DestroyLabInput{DestroyTimeoutS: 60})
	if err != nil || !res.Removed {
		t.Fatalf("result %+v, %v; want the lab removed", res, err)
	}
	if got := procs.killed(); !slices.Equal(got, []int{77}) || callsAtKill != 0 {
		t.Errorf("killed %v with %s containerlab calls already made; want the stray killed before any", got, strconv.Itoa(callsAtKill))
	}
}
