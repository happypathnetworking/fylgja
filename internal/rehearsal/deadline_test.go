package rehearsal

import (
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// mechanism is research §1.7's constants: the host check, the stage, the record, the
// teardown's plan, the unstage and the twin's inspection 30 or 60 s, the margins 15, 15 and
// 30 s, the flows' margin 15 s (016), and verify's default wait of 120 s. The baseline's stop-following bound, 30 s, that
// 015's T082 added is gone with following (019, R-15).
var mechanism = Mechanism{
	CheckHost: 30 * time.Second, Stage: 60 * time.Second, Record: 30 * time.Second,
	PlanTeardown: 30 * time.Second, Unstage: 30 * time.Second, InspectTwin: 30 * time.Second,
	ReadinessMargin: 15 * time.Second, PushMargin: 15 * time.Second, VerifyMargin: 30 * time.Second,
	FlowsMargin: 15 * time.Second, Wait: 120 * time.Second,
}

// node is one node's plan with its package's four budgets: deploy, readiness, push and
// destroy.
func node(name string, deploy, readiness, push, destroy int) wire.NodePlan {
	return wire.NodePlan{Name: name, DeployTimeoutS: deploy, TimeoutS: readiness, DestroyTimeoutS: destroy,
		Push: wire.PushSpec{TimeoutS: push}}
}

// srl is the SR Linux package's budgets (deploy 180, readiness 60, push 30, destroy 60);
// eos the EOS package's (deploy 300, readiness 90, push 30, destroy 60).
func srl(name string) wire.NodePlan { return node(name, 180, 60, 30, 60) }
func eos(name string) wire.NodePlan { return node(name, 300, 90, 30, 60) }

func fixtureNodes() []wire.NodePlan { return []wire.NodePlan{srl("n1"), srl("n2"), srl("n3")} }

// host is a probe's host with the ping package's budgets (deploy 60, readiness 30, destroy
// 30, the flow's start and read 30 each), flow budgets start and read as given.
func host(name string, start, read int) wire.NodePlan {
	n := node(name, 60, 30, 0, 30)
	n.Host = &wire.ProbePlan{Format: "ping", Flow: wire.FlowSpec{IntervalS: 0.2, StartTimeoutS: start, ReadTimeoutS: read}}
	return n
}

// probedNodes is the fixture with two probes' four hosts (016).
func probedNodes() []wire.NodePlan {
	return append(fixtureNodes(), host("n1-loop-a", 30, 30), host("n1-loop-b", 30, 30), host("n3-loop-a", 30, 30),
		host("n3-loop-b", 30, 30))
}

func stagesOf(roles []string, nodes []wire.NodePlan) []DeadlineStage {
	out := make([]DeadlineStage, len(roles))
	for i, r := range roles {
		out[i] = DeadlineStage{Role: r, Nodes: nodes}
	}
	return out
}

func TestDeadline(t *testing.T) {
	mixed := []wire.NodePlan{srl("n1"), eos("n2"), srl("n3")}
	for _, c := range []struct {
		name   string
		stages []DeadlineStage
		want   time.Duration
	}{
		// The fixture's branch point is refused and adds nothing: the baseline 570, two marks
		// and the head 630 each, the destroy 120.
		{"the fixture's refused branch point, two marks and the head",
			append([]DeadlineStage{{Role: RoleRefused}}, stagesOf([]string{RoleBaseline, RoleRehearsed, RoleRehearsed}, fixtureNodes())...),
			1950 * time.Second},
		{"a compiled branch point", stagesOf([]string{RoleBaseline, RoleRehearsed, RoleRehearsed, RoleRehearsed}, fixtureNodes()),
			2580 * time.Second},
		// Each budget is the largest over a stage's nodes: deploy 300 and readiness 90 from
		// the EOS node, push and destroy alike; the baseline 720, each step 780.
		{"the mixed fixture's three stages", stagesOf([]string{RoleBaseline, RoleRehearsed, RoleRehearsed}, mixed),
			2400 * time.Second},
		{"one stage alone is the baseline and the destroy", stagesOf([]string{RoleBaseline}, fixtureNodes()),
			(570 + 120) * time.Second},
		// 016, research R-16: each rehearsed stage starts and reads its hosts' flows, (30 + 15)
		// + (30 + 15); the baseline starts none, and the hosts' budgets are under SR Linux's.
		{"the probed fixture's refused branch point, two marks and the head",
			append([]DeadlineStage{{Role: RoleRefused}}, stagesOf([]string{RoleBaseline, RoleRehearsed, RoleRehearsed}, probedNodes())...),
			(570 + 720 + 720 + 120) * time.Second},
	} {
		if got := Deadline(mechanism, c.stages); got != c.want {
			t.Errorf("%s: Deadline = %v, want %v", c.name, got, c.want)
		}
		if !Fits(c.want, Ceiling) {
			t.Errorf("%s: %v does not fit the ceiling %v", c.name, c.want, Ceiling)
		}
	}

	// A stage of SR Linux and EOS nodes takes each budget's largest, whichever node holds it:
	// the deploy from one node and the destroy from another.
	odd := []wire.NodePlan{node("a", 100, 10, 5, 200), node("b", 300, 90, 40, 60)}
	want := (30 + 60 + 300 + (90 + 15) + (40 + 15) + 30 + (120 + 30) + 30 + 200 + 30) * time.Second
	if got := Deadline(mechanism, stagesOf([]string{RoleBaseline}, odd)); got != want {
		t.Errorf("a stage of two nodes' budgets: Deadline = %v, want %v", got, want)
	}

	// The flows' budgets are each the largest over a rehearsed stage's hosts, start from one
	// host and read from another.
	hosts := append(fixtureNodes(), host("a", 10, 40), host("b", 25, 5))
	base := Deadline(mechanism, stagesOf([]string{RoleRehearsed}, fixtureNodes()))
	if got, want := Deadline(mechanism, stagesOf([]string{RoleRehearsed}, hosts)), base+(25+15+40+15)*time.Second; got != want {
		t.Errorf("a rehearsed stage's flows: Deadline = %v, want %v", got, want)
	}

	// Six marks of the mixed twin need 720 + 6×780 + 120 = 5,520 s, over the ceiling.
	over := Deadline(mechanism, stagesOf([]string{RoleBaseline, RoleRehearsed, RoleRehearsed, RoleRehearsed,
		RoleRehearsed, RoleRehearsed, RoleRehearsed}, mixed))
	if over != 5520*time.Second || Fits(over, Ceiling) {
		t.Errorf("a stage list over the ceiling: Deadline = %v, fits %v", over, Fits(over, Ceiling))
	}
	if !Fits(Ceiling, Ceiling) || Fits(Ceiling+time.Second, Ceiling) {
		t.Errorf("Fits is not deadline <= ceiling")
	}
	if Ceiling != time.Hour {
		t.Errorf("Ceiling = %v, want research R-09's hour", Ceiling)
	}
}
