package lab

import (
	"context"
	"errors"
	"fmt"
	"path/filepath"
	"reflect"
	"slices"
	"strings"
	"testing"

	"go.temporal.io/sdk/activity"
	"go.temporal.io/sdk/temporal"
	"go.temporal.io/sdk/testsuite"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

var inspectArgs = []string{"clab", "inspect", "--all", "--format", "json"}

// activityEnv runs one activity as the worker does, with heartbeats and cancellation.
func activityEnv(fn any, name string) *testsuite.TestActivityEnvironment {
	var suite testsuite.WorkflowTestSuite
	env := suite.NewTestActivityEnvironment()
	env.RegisterActivityWithOptions(fn, activity.RegisterOptions{Name: name})
	return env
}

// stepFailure asserts err is a non-retryable step failure of type rule and returns the
// finding it carries.
func stepFailure(t *testing.T, err error, rule string) findings.Finding {
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

// onlyInspected fails unless every containerlab invocation was `inspect --all`.
func onlyInspected(t *testing.T, f *fakeRunner) {
	t.Helper()
	for _, c := range f.calls {
		if !reflect.DeepEqual(c.args, inspectArgs) {
			t.Errorf("runner saw %v; only %v was allowed", c.args, inspectArgs)
		}
	}
}

// labOf is containerlab's JSON for lab fylgja with one node per kind, n1 onwards.
func labOf(kinds ...string) []byte {
	parts := make([]string, len(kinds))
	for i, k := range kinds {
		parts[i] = fmt.Sprintf(`{"name":"clab-fylgja-n%d","kind":%q,"state":"running","ipv4_address":"172.20.20.%d/24"}`, i+1, k, i+2)
	}
	return []byte(`{"fylgja":[` + strings.Join(parts, ",") + `]}`)
}

func threeNodePlan() []wire.NodePlan {
	return []wire.NodePlan{{Name: "n1"}, {Name: "n2"}, {Name: "n3"}}
}

// With no lab present, deploy runs a plain `clab deploy` on the staged topology with
// containerlab's working directory in the twin directory, and reports the nodes.
func TestDeployLabAbsentLab(t *testing.T) {
	f := &fakeRunner{replies: map[string][]reply{
		"inspect": {{stdout: recorded(t, "inspect-empty.json")}},
		"deploy":  {{stdout: recorded(t, "inspect-three.json")}},
	}}
	a := testActivities(t, f)
	env := activityEnv(a.DeployLab, wire.ActDeployLab)

	val, err := env.ExecuteActivity(wire.ActDeployLab, wire.DeployInput{TwinDir: a.Paths.Twin, Nodes: threeNodePlan()})
	if err != nil {
		t.Fatal(err)
	}
	var res wire.DeployResult
	if err := val.Get(&res); err != nil {
		t.Fatal(err)
	}
	if len(res.Nodes) != 3 || res.Nodes[0].Name != "n1" || res.Nodes[0].MgmtIPv4 != "172.20.20.2" {
		t.Errorf("nodes = %+v, want n1–n3 with n1 at 172.20.20.2", res.Nodes)
	}

	if len(f.calls) != 2 {
		t.Fatalf("runner saw %+v, want inspect then deploy", f.calls)
	}
	if got := f.calls[0].args; !reflect.DeepEqual(got, inspectArgs) {
		t.Errorf("first call = %v, want inspect --all", got)
	}
	topo := filepath.Join(a.Paths.TwinBundle, "topology.clab.yml")
	if got, want := f.calls[1].args, []string{"clab", "deploy", "--topo", topo, "--format", "json"}; !reflect.DeepEqual(got, want) {
		t.Errorf("deploy = %v, want %v (no --reconfigure on an absent lab)", got, want)
	}
	if got, want := f.calls[1].env, []string{"CLAB_LABDIR_BASE=" + a.Paths.Twin}; !reflect.DeepEqual(got, want) {
		t.Errorf("deploy environment override = %v, want %v", got, want)
	}
}

// A lab present at deploy time is this run's own cut-off attempt: it is recreated with
// --reconfigure, exactly once, and the result is one lab.
func TestDeployLabPresentLabReconfiguresOnce(t *testing.T) {
	f := &fakeRunner{replies: map[string][]reply{
		"inspect": {{stdout: recorded(t, "inspect-three.json")}},
		"deploy":  {{stdout: recorded(t, "inspect-three.json")}},
	}}
	a := testActivities(t, f)

	res, err := a.DeployLab(context.Background(), wire.DeployInput{TwinDir: a.Paths.Twin, Nodes: threeNodePlan()})
	if err != nil {
		t.Fatal(err)
	}
	if len(res.Nodes) != 3 {
		t.Errorf("nodes = %+v, want the one lab's three", res.Nodes)
	}
	var deploys [][]string
	for _, c := range f.calls {
		if c.args[1] == "deploy" {
			deploys = append(deploys, c.args)
		}
	}
	if len(deploys) != 1 || !slices.Contains(deploys[0], "--reconfigure") {
		t.Errorf("deploys = %v, want exactly one, with --reconfigure", deploys)
	}
}

// containerlab failing is deploy.failed, with its own explanation surfaced.
func TestDeployLabToolFailureIsDeployFailed(t *testing.T) {
	f := &fakeRunner{replies: map[string][]reply{
		"inspect": {{stdout: recorded(t, "inspect-empty.json")}},
		"deploy":  {{stderr: recorded(t, "deploy-failed.stderr"), exit: 1}},
	}}
	a := testActivities(t, f)

	_, err := a.DeployLab(context.Background(), wire.DeployInput{TwinDir: a.Paths.Twin, Nodes: threeNodePlan()})
	got := stepFailure(t, err, findings.RuleDeployFailed)
	if got.Step != findings.StepDeploy || got.Object != "lab fylgja" {
		t.Errorf("finding = %+v, want step deploy on lab fylgja", got)
	}
	if !strings.Contains(got.Message, "Failed to parse value 'e1-1'") || !strings.Contains(got.Message, "exited 1") {
		t.Errorf("message %q lost SR Linux's reason or the exit status", got.Message)
	}
}

// containerlab exiting 0 with a node not running is still deploy.failed, naming the node.
func TestDeployLabNodeNotRunningIsDeployFailed(t *testing.T) {
	partial := []byte(`{"fylgja":[
	  {"name":"clab-fylgja-n1","kind":"nokia_srlinux","state":"running","ipv4_address":"172.20.20.2/24"},
	  {"name":"clab-fylgja-n2","kind":"nokia_srlinux","state":"exited","ipv4_address":""}]}`)
	f := &fakeRunner{replies: map[string][]reply{
		"inspect": {{stdout: recorded(t, "inspect-empty.json")}},
		"deploy":  {{stdout: partial}},
	}}
	a := testActivities(t, f)

	_, err := a.DeployLab(context.Background(), wire.DeployInput{TwinDir: a.Paths.Twin, Nodes: threeNodePlan()})
	got := stepFailure(t, err, findings.RuleDeployFailed)
	if !strings.Contains(got.Message, "n2 exited") || !strings.Contains(got.Message, "n3 absent") ||
		strings.Contains(got.Message, "n1") {
		t.Errorf("message %q, want n2 exited and n3 absent named, and n1 not", got.Message)
	}
}

// The teardown budget comes from the packages of what is there: the staged manifest, or an
// orphan's container kinds; the default only for what no package covers (Constitution II).
func TestPlanTeardown(t *testing.T) {
	ctx := context.Background()
	heterogeneous := func(t *testing.T, a *Activities) {
		t.Helper()
		reg, err := psp.Load(filepath.Join("..", "..", "testdata", "psp", "heterogeneous"))
		if err != nil {
			t.Fatal(err)
		}
		a.Registry = reg
	}
	for _, c := range []struct {
		name  string
		setup func(t *testing.T, a *Activities)
		reply []reply
		want  wire.PlanTeardownResult
	}{
		{"a staged SR Linux manifest", func(t *testing.T, a *Activities) {
			if _, err := a.StageBundle(ctx, wire.StageInput{BundlePath: goldenBundle(), BundleID: goldenID}); err != nil {
				t.Fatal(err)
			}
		}, nil, wire.PlanTeardownResult{DestroyTimeoutS: 60, Basis: wire.BasisManifest}},
		{"an orphan budgeted by its containers' kind", heterogeneous,
			[]reply{{stdout: labOf("slowos")}},
			wire.PlanTeardownResult{DestroyTimeoutS: 120, Basis: wire.BasisInspect}},
		{"a kind no package covers", heterogeneous,
			[]reply{{stdout: labOf("ghostos", "fastos")}},
			wire.PlanTeardownResult{DestroyTimeoutS: 60, Basis: wire.BasisInspect, Uncovered: []string{"n1"}}},
		{"nothing to tear down", nil,
			[]reply{{stdout: recorded(t, "inspect-empty.json")}},
			wire.PlanTeardownResult{Basis: wire.BasisNone}},
		{"containerlab cannot be inspected", nil,
			[]reply{{stderr: []byte("   ERROR  Cannot connect to the Docker daemon"), exit: 1}},
			wire.PlanTeardownResult{Basis: wire.BasisInspect}},
	} {
		t.Run(c.name, func(t *testing.T) {
			f := &fakeRunner{replies: map[string][]reply{"inspect": c.reply}}
			a := testActivities(t, f)
			if c.setup != nil {
				c.setup(t, a)
			}
			plan, err := a.PlanTeardown(ctx)
			if err != nil {
				t.Fatalf("PlanTeardown failed: %v; it answers whatever it finds", err)
			}
			if !reflect.DeepEqual(plan, c.want) {
				t.Errorf("plan = %+v, want %+v", plan, c.want)
			}
			onlyInspected(t, f)
		})
	}
}

func TestDestroyLab(t *testing.T) {
	ctx := context.Background()
	destroyArgs := []string{"clab", "destroy", "--name", "fylgja", "--cleanup"}

	t.Run("no lab", func(t *testing.T) {
		f := &fakeRunner{replies: map[string][]reply{"inspect": {{stdout: recorded(t, "inspect-empty.json")}}}}
		res, err := testActivities(t, f).DestroyLab(ctx, wire.DestroyLabInput{DestroyTimeoutS: 60})
		if err != nil || res.Removed {
			t.Errorf("result %+v, %v; want nothing removed and no error", res, err)
		}
		onlyInspected(t, f)
	})
	t.Run("a lab of three", func(t *testing.T) {
		f := &fakeRunner{replies: map[string][]reply{
			"inspect": {{stdout: recorded(t, "inspect-three.json")}, {stdout: recorded(t, "inspect-empty.json")}},
			"destroy": {{}},
		}}
		res, err := testActivities(t, f).DestroyLab(ctx, wire.DestroyLabInput{DestroyTimeoutS: 60})
		if err != nil || !res.Removed || res.Containers != 3 {
			t.Errorf("result %+v, %v; want three containers removed", res, err)
		}
		want := [][]string{inspectArgs, destroyArgs, inspectArgs}
		var got [][]string
		for _, c := range f.calls {
			got = append(got, c.args)
		}
		if !reflect.DeepEqual(got, want) {
			t.Errorf("runner saw %v, want inspect, destroy, inspect", got)
		}
	})
	t.Run("a lab still present afterwards", func(t *testing.T) {
		f := &fakeRunner{replies: map[string][]reply{
			"inspect": {{stdout: recorded(t, "inspect-three.json")}},
			"destroy": {{}},
		}}
		_, err := testActivities(t, f).DestroyLab(ctx, wire.DestroyLabInput{DestroyTimeoutS: 60})
		got := stepFailure(t, err, findings.RuleCleanupIncomplete)
		if got.Step != findings.StepTeardown || got.Object != "lab fylgja" {
			t.Errorf("finding = %+v, want step teardown on lab fylgja", got)
		}
		for _, want := range []string{"still present", "n1 running", "n3 running", "clab destroy --name fylgja --cleanup"} {
			if !strings.Contains(got.Message, want) {
				t.Errorf("message %q does not say %q", got.Message, want)
			}
		}
	})
	t.Run("clab destroy exits non-zero", func(t *testing.T) {
		f := &fakeRunner{replies: map[string][]reply{
			"inspect": {{stdout: recorded(t, "inspect-three.json")}, {stdout: recorded(t, "inspect-empty.json")}},
			"destroy": {{stderr: []byte("boom"), exit: 1}},
		}}
		_, err := testActivities(t, f).DestroyLab(ctx, wire.DestroyLabInput{DestroyTimeoutS: 60})
		got := stepFailure(t, err, findings.RuleCleanupIncomplete)
		if !strings.Contains(got.Message, "boom") || !strings.Contains(got.Message, "clab destroy --name fylgja --cleanup") {
			t.Errorf("message %q, want containerlab's error and the clearing command", got.Message)
		}
	})
}
