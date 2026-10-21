package rehearsal

import (
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// mechanism is research §1.7's constants: the host check, the stage, the record, the
// teardown's plan, the unstage and the twin's inspection 30 or 60 s, the margins 15, 15 and
// 30 s, and verify's default wait of 120 s; and the baseline's stop-following bound, 30 s
// (T082).
var mechanism = Mechanism{
	CheckHost: 30 * time.Second, Stage: 60 * time.Second, Record: 30 * time.Second,
	PlanTeardown: 30 * time.Second, Unstage: 30 * time.Second, InspectTwin: 30 * time.Second,
	ReadinessMargin: 15 * time.Second, PushMargin: 15 * time.Second, VerifyMargin: 30 * time.Second,
	Wait: 120 * time.Second, Follow: 30 * time.Second,
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
		// The fixture's branch point is refused and adds nothing: the baseline 600, its
		// stop-following among it, two marks and the head 630 each, the destroy 120.
		{"the fixture's refused branch point, two marks and the head",
			append([]DeadlineStage{{Role: RoleRefused}}, stagesOf([]string{RoleBaseline, RoleRehearsed, RoleRehearsed}, fixtureNodes())...),
			1980 * time.Second},
		{"a compiled branch point", stagesOf([]string{RoleBaseline, RoleRehearsed, RoleRehearsed, RoleRehearsed}, fixtureNodes()),
			2610 * time.Second},
		// Each budget is the largest over a stage's nodes: deploy 300 and readiness 90 from
		// the EOS node, push and destroy alike; the baseline 750, each step 780.
		{"the mixed fixture's three stages", stagesOf([]string{RoleBaseline, RoleRehearsed, RoleRehearsed}, mixed),
			2430 * time.Second},
		{"one stage alone is the baseline and the destroy", stagesOf([]string{RoleBaseline}, fixtureNodes()),
			(600 + 120) * time.Second},
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
	want := (30 + 30 + 60 + 300 + (90 + 15) + (40 + 15) + 30 + (120 + 30) + 30 + 200 + 30) * time.Second
	if got := Deadline(mechanism, stagesOf([]string{RoleBaseline}, odd)); got != want {
		t.Errorf("a stage of two nodes' budgets: Deadline = %v, want %v", got, want)
	}

	// Six marks of the mixed twin need 750 + 6×780 + 120 = 5,550 s, over the ceiling.
	over := Deadline(mechanism, stagesOf([]string{RoleBaseline, RoleRehearsed, RoleRehearsed, RoleRehearsed,
		RoleRehearsed, RoleRehearsed, RoleRehearsed}, mixed))
	if over != 5550*time.Second || Fits(over, Ceiling) {
		t.Errorf("a stage list over the ceiling: Deadline = %v, fits %v", over, Fits(over, Ceiling))
	}
	if !Fits(Ceiling, Ceiling) || Fits(Ceiling+time.Second, Ceiling) {
		t.Errorf("Fits is not deadline <= ceiling")
	}
	if Ceiling != time.Hour {
		t.Errorf("Ceiling = %v, want research R-09's hour", Ceiling)
	}
}
