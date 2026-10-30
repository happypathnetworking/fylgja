package server

import (
	"os"
	"reflect"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/step"
)

// manifestProbe is a probe's manifest entry with its two hosts on device dev, a towards b.
func manifestProbe(name, dev, a, b string) compiler.ManifestProbeEntry {
	return compiler.ManifestProbeEntry{Name: name, Format: "ping", Hosts: [2]compiler.ProbeHost{
		{Endpoint: "a", Node: name + "-a", Device: dev, Interface: "ethernet-1/10", Port: "eth1", Address: a},
		{Endpoint: "b", Node: name + "-b", Device: dev, Interface: "ethernet-1/11", Port: "eth1", Address: b}}}
}

// hostNode is the host check's plan for a host whose flow pings far.
func hostNode(name, probe, endpoint, far string) wire.NodePlan {
	return wire.NodePlan{Name: name, Host: &wire.ProbePlan{Format: "ping", Probe: probe, Endpoint: endpoint,
		Flow: wire.FlowSpec{IntervalS: 0.2, Command: []string{"ping", "-i", "0.2", far}, StartTimeoutS: 30, ReadTimeoutS: 30}}}
}

// The step's flows are the probes both bundles carry, each run in its a host's container
// towards its b host's, its far address b's without the prefix and its flow the one the host
// check rendered for a; a probe the target alone carries is added, one the twin's bundle
// alone carries dropped, each in name order (016, research R-21). A step whose bundles carry
// no probe has none of the three, so its input is 019's; and a host the host check did not
// plan is an error.
func TestFlowsOfTwoManifests(t *testing.T) {
	from := compiler.Manifest{Probes: []compiler.ManifestProbeEntry{
		manifestProbe("n1-loop", "n1", "10.1.10.2/24", "10.1.11.2/24"),
		manifestProbe("n3-loop", "n3", "10.3.10.2/24", "10.3.11.2/24"),
		manifestProbe("n4-loop", "n3", "10.4.10.2/24", "10.4.11.2/24")}}
	to := compiler.Manifest{Probes: []compiler.ManifestProbeEntry{
		manifestProbe("n1-loop", "n1", "10.1.10.2/24", "10.1.11.2/24"),
		manifestProbe("n2-loop", "n2", "10.2.10.2/24", "10.2.11.2/24")}}
	nodes := []wire.NodePlan{{Name: "n1"}, {Name: "n2"},
		hostNode("n1-loop-a", "n1-loop", "a", "10.1.11.2"), hostNode("n1-loop-b", "n1-loop", "b", "10.1.10.2"),
		hostNode("n2-loop-a", "n2-loop", "a", "10.2.11.2"), hostNode("n2-loop-b", "n2-loop", "b", "10.2.10.2")}

	flows, added, dropped, err := flowsOf(from, to, nodes)
	if err != nil {
		t.Fatal(err)
	}
	want := []wire.FlowPlan{{Probe: "n1-loop", From: "clab-fylgja-n1-loop-a", To: "clab-fylgja-n1-loop-b", Far: "10.1.11.2",
		Flow: nodes[2].Host.Flow}}
	if !reflect.DeepEqual(flows, want) {
		t.Errorf("flows %+v, want %+v", flows, want)
	}
	if !reflect.DeepEqual(added, []string{"n2-loop"}) || !reflect.DeepEqual(dropped, []string{"n3-loop", "n4-loop"}) {
		t.Errorf("added %q and dropped %q, want [n2-loop] and [n3-loop n4-loop]", added, dropped)
	}

	// No probe on either side: nothing, so the input marshals as 019's did.
	flows, added, dropped, err = flowsOf(compiler.Manifest{}, compiler.Manifest{Probes: []compiler.ManifestProbeEntry{}},
		[]wire.NodePlan{{Name: "n1"}})
	if err != nil || flows != nil || added != nil || dropped != nil {
		t.Errorf("a probe-less step's flows %+v, added %q, dropped %q, err %v; want none of them", flows, added, dropped, err)
	}

	if _, _, _, err := flowsOf(from, to, nodes[:2]); err == nil {
		t.Error("a probe both carry whose a host the host check did not plan gave no error")
	}
}

// A step from a probed twin reads the twin's own manifest, whose hosts name no support
// package (psp null): the from side's packages are the devices' alone, and the flow is the
// probe both bundles carry (016). Run 27 found the server's step panicking here on the
// first step from a probed twin, a dry run's included.
func TestStepInputFromAProbedTwin(t *testing.T) {
	raw, err := os.ReadFile(repoPath("testdata", "golden", "three-node-probed", compiler.ManifestFile))
	if err != nil {
		t.Fatal(err)
	}
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	const id = "5222063bac574cf7ba031a0cb7a04dc0ae8b40cca84403215bf5356c50dfcde9"
	probed := step.Bundle{ID: id, Files: map[string][]byte{compiler.ManifestFile: raw}}
	plan := wire.CheckHostResult{Nodes: []wire.NodePlan{
		{Name: "n1", PSPID: "nokia_srlinux"}, {Name: "n2", PSPID: "nokia_srlinux"}, {Name: "n3", PSPID: "nokia_srlinux"},
		hostNode("n1-loop-a", "n1-loop", "a", "10.1.11.2"), hostNode("n1-loop-b", "n1-loop", "b", "10.1.10.2")}}

	in, packages, err := stepInput(&stepFlags{}, &wire.TwinRecord{BundleID: id}, probed, stepTarget{bundle: probed}, "",
		step.Step{Unchanged: true}, nil, plan, wire.ReconcilePlan{}, reg, "test")
	if err != nil {
		t.Fatal(err)
	}
	var from []string
	for _, p := range packages.from {
		from = append(from, p.Node+":"+p.ID)
	}
	if want := []string{"n1:nokia_srlinux", "n2:nokia_srlinux", "n3:nokia_srlinux"}; !reflect.DeepEqual(from, want) {
		t.Errorf("the from side's packages %q, want %q", from, want)
	}
	if len(in.Flows) != 1 || in.Flows[0].Probe != "n1-loop" || in.Added != nil || in.Dropped != nil {
		t.Errorf("flows %+v, added %q, dropped %q; want n1-loop's flow alone", in.Flows, in.Added, in.Dropped)
	}
}

// The flows step's line says how each flow started and the loss step's what each lost,
// after the stage and after the wait (016, contracts/cli.md, twin step); a flows step that
// failed keeps M2's line.
func TestPrintEventFlowsAndLoss(t *testing.T) {
	for _, c := range []struct {
		event provision.Event
		want  string
	}{
		{provision.Event{Step: "flows"}, "step flows: begins\n"},
		{provision.Event{Step: "flows", End: true, Outcome: provision.EventDone, Detail: "n1-loop started"},
			"step flows: n1-loop started\n"},
		{provision.Event{Step: "flows", End: true, Outcome: provision.EventDone,
			Detail: "n1-loop not started: docker exec exited 1"}, "step flows: n1-loop not started: docker exec exited 1\n"},
		{provision.Event{Step: "loss", End: true, Outcome: provision.EventDone,
			Detail: "n1-loop 0/312 lost, longest gap 0.0s (container timing)"},
			"step loss: n1-loop 0/312 lost, longest gap 0.0s (container timing)\n"},
		{provision.Event{Step: "flows", End: true, Outcome: provision.EventFailed, Rule: findings.RuleOperationFailed,
			Message: "the worker could not start the flows"},
			"step flows: failed operation.failed: the worker could not start the flows\n"},
	} {
		if got := captureStdout(t, func() { printEvent(testOptions(t, false), c.event) }); got != c.want {
			t.Errorf("%+v printed %q, want %q", c.event, got, c.want)
		}
	}
}

// The closing line ends with what the step's flows lost, lost over sent per probe, after the
// wait's clause (016, contracts/cli.md): a flow interrupted, not started or not read says so,
// and a step with no probe, or one whose flows were never read, adds nothing.
func TestStepClosingCarriesTheLoss(t *testing.T) {
	const (
		fromID = "348fd9340000000000000000000000000000000000000000000000000000abcd"
		toID   = "ee291b0f0000000000000000000000000000000000000000000000000000abcd"
	)
	in := provision.StepInput{
		From: wire.StepSide{SnapshotID: strings.Repeat("576933ec", 8), BundleID: fromID},
		To:   wire.StepSide{SnapshotID: strings.Repeat("9c2d01e7", 8), BundleID: toID},
	}
	const stepped = "stepped to snapshot 9c2d01e7… (bundle ee291b0f…) in 71.2s"
	settled := &wire.StepWait{Outcome: wire.WaitSettled, AfterS: 1.9}
	measured := wire.ProbeLoss{Probe: "n1-loop", Outcome: wire.FlowMeasured, Sent: 312}
	for _, c := range []struct {
		label string
		wait  *wire.StepWait
		loss  *wire.Loss
		want  string
	}{
		{"measured", settled, &wire.Loss{Basis: wire.LossBasisContainer, Probes: []wire.ProbeLoss{measured}},
			stepped + "; settled after 1.9s; loss n1-loop 0/312"},
		{"no wait", nil, &wire.Loss{Basis: wire.LossBasisContainer, Probes: []wire.ProbeLoss{measured}},
			stepped + "; loss n1-loop 0/312"},
		{"each outcome", settled, &wire.Loss{Basis: wire.LossBasisContainer, Probes: []wire.ProbeLoss{
			{Probe: "n1-loop", Outcome: wire.FlowInterrupted, Sent: 300, Lost: 274},
			{Probe: "n2-loop", Outcome: wire.FlowNotStarted}, {Probe: "n3-loop", Outcome: wire.FlowNotRead}}},
			stepped + "; settled after 1.9s; loss n1-loop 274/300 interrupted, n2-loop not started, n3-loop not read"},
		{"no probe", settled, &wire.Loss{Basis: wire.LossBasisContainer, Added: []string{"n2-loop"}},
			stepped + "; settled after 1.9s"},
		{"never read", settled, nil, stepped + "; settled after 1.9s"},
	} {
		res := provision.StepResult{Outcome: provision.StepStepped, Timings: wire.StepTimings{WholeS: 71.2}, Wait: c.wait, Loss: c.loss}
		if got := stepClosing(in, res); got != c.want {
			t.Errorf("%s:\n got %q\nwant %q", c.label, got, c.want)
		}
	}
}
