package rehearsal

import (
	"time"

	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// Ceiling is the longest deadline a rehearsal may have: a mechanism constant of Fylgja's,
// the operator's patience as the wait's budget is, never a platform's (research R-09). A
// rehearsal whose stages need more is refused before any run, rehearsal.deadline.unfit.
const Ceiling = 3600 * time.Second

// The roles a stage takes in a rehearsal (rehearsal.schema.json, $defs/stage).
const (
	// RoleRefused is a stage the plan refused: the branch point refused
	// scope.empty, passed over, or a stage whose refusal refused the rehearsal.
	RoleRefused = "refused"
	// RoleBaseline is the first compiled stage, created and verified.
	RoleBaseline = "baseline"
	// RoleRehearsed is a compiled stage after the baseline, stepped to and verified.
	RoleRehearsed = "rehearsed"
	// RoleNotReached is a stage the run did not come to: after one that was not passed, or
	// in a rehearsal refused before any run.
	RoleNotReached = "not_reached"
)

// Mechanism is the mechanism constants that bound each activity a rehearsal's children run,
// none a platform's (Constitution II). The workflows' package fills it from its own
// constants and verify's wait budget, so this package imports neither.
type Mechanism struct {
	// CheckHost bounds the host check: once in a create, twice in a step (its own and its
	// read of containerlab's plan).
	CheckHost time.Duration
	// Stage bounds staging a bundle into the twin directory.
	Stage time.Duration
	// Record bounds writing the twin's record.
	Record time.Duration
	// PlanTeardown and Unstage bound the destroy's two steps around the lab's removal.
	PlanTeardown time.Duration
	Unstage      time.Duration
	// InspectTwin bounds a step's read of the twin it starts from.
	InspectTwin time.Duration
	// ReadinessMargin, PushMargin and VerifyMargin are added to the readiness budget, the
	// push budget and the wait's budget, as each activity's timeout adds them.
	ReadinessMargin time.Duration
	PushMargin      time.Duration
	VerifyMargin    time.Duration
	// Wait is a wait's budget: verify's default, which every stage of a rehearsal waits.
	Wait time.Duration
}

// DeadlineStage is one compiled stage as the deadline sums it: the role the rehearsal gives
// it, baseline or rehearsed, and the host check's plan of each of its nodes, whose budgets
// are its package's.
type DeadlineStage struct {
	Role  string
	Nodes []wire.NodePlan
}

// Deadline is the time a rehearsal of stages is bounded by: each stage's budgets summed,
// the largest of each over the stage's nodes, and the destroy once (data-model §4):
//
//	baseline  = CheckHost + Stage + deploy + (readiness + ReadinessMargin) + (push + PushMargin) + Record + (Wait + VerifyMargin)
//	rehearsed = InspectTwin + 2 CheckHost + Stage + deploy + (readiness + ReadinessMargin) + (push + PushMargin) + Record + (Wait + VerifyMargin)
//	destroy   = PlanTeardown + destroy + Unstage
//
// A stage of another role is not run, and adds nothing. The destroy's budget is the largest
// over every stage counted, since the run may stop at any of them.
func Deadline(m Mechanism, stages []DeadlineStage) time.Duration {
	var total time.Duration
	destroy := 0
	for _, s := range stages {
		b := budgetsOf(s.Nodes)
		build := m.Stage + seconds(b.deploy) + seconds(b.readiness) + m.ReadinessMargin +
			seconds(b.push) + m.PushMargin + m.Record + m.Wait + m.VerifyMargin
		switch s.Role {
		case RoleBaseline:
			total += m.CheckHost + build
		case RoleRehearsed:
			total += m.InspectTwin + 2*m.CheckHost + build
		default:
			continue
		}
		destroy = max(destroy, b.destroy)
	}
	return total + m.PlanTeardown + seconds(destroy) + m.Unstage
}

// Fits says whether a deadline is within the ceiling.
func Fits(deadline, ceiling time.Duration) bool { return deadline <= ceiling }

// budgets are a stage's budgets in seconds, each the largest over its nodes.
type budgets struct{ deploy, readiness, push, destroy int }

func budgetsOf(nodes []wire.NodePlan) budgets {
	var b budgets
	for _, n := range nodes {
		b.deploy = max(b.deploy, n.DeployTimeoutS)
		b.readiness = max(b.readiness, n.TimeoutS)
		b.push = max(b.push, n.Push.TimeoutS)
		b.destroy = max(b.destroy, n.DestroyTimeoutS)
	}
	return b
}

func seconds(s int) time.Duration { return time.Duration(s) * time.Second }
