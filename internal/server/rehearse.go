package server

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/rehearsal"
	"github.com/happypathnetworking/fylgja/internal/stages"
	"github.com/happypathnetworking/fylgja/internal/step"
	"github.com/happypathnetworking/fylgja/internal/verify"
)

// rehearseFlags are twin rehearse's arguments (015): the proposed change's source branch,
// and whether --branch was given at all.
type rehearseFlags struct {
	branch      string
	branchGiven bool
	// scope is --scope as given, read only when scopeGiven: not given, the server's default
	// stands (017).
	scope      string
	scopeGiven bool
	// probes is --probes as given (016): the probe file every stage's take carries in place
	// of the kind's, as stage plan's.
	probes probesArg
}

// runTwinRehearse is twin rehearse (015; specs/015-proposed-change-rehearsal/contracts/
// rehearse-command.md, "What the server does, in order"). Everything up to the start is
// decided here, each refusal ending the request with its document and nothing started:
//
//  1. the guards, before any connection, as stage plan's are: --branch absent is --branch
//     is required, and one that is not a branch is stage.ref.invalid at start;
//  2. the plan: the open proposed change on the branch found and every stage resolved,
//     read, compiled and filed as stage plan plans them, then the baseline rule (research
//     R-03), a stage refused refusing the rehearsal but the branch point refused
//     scope.empty alone (017's FR-015), which is passed over;
//  3. the deadline, the compiled stages' budgets summed from their node plans, refused
//     rehearsal.deadline.unfit over the ceiling;
//  4. the runs in flight, through the workflow service: a rehearsal, a provisioning, step or
//     destroy run running is run.in_flight;
//  5. the host: the twin of a rehearsal whose run is no longer running reclaimed through the
//     destroy run (R-04), then the host check of the baseline's bundle in this process, as a
//     dry run makes it;
//
// then the run, fylgja-rehearse, its input the step chain the server computed from the plan
// (R-05), followed to its close and its destroy, and the report (R-10).
func runTwinRehearse(ctx context.Context, opts *options, f *rehearseFlags) error {
	const op = findings.OpTwinRehearse
	if !f.branchGiven && f.branch == "" {
		return fail(op, nil, "--branch is required")
	}
	if refused := branchGuard(op, f.branch); refused != nil {
		return refused
	}
	subject := &findings.Subject{Branch: f.branch}
	// The scope every stage is planned under and the baseline's run records (017), after the
	// guards and before the packages load.
	scope, err := scopeOf(opts, op, subject, f.scope, f.scopeGiven)
	if err != nil {
		return err
	}
	subject.Scope = scope
	if ctx == nil {
		ctx = context.Background()
	}

	planned, err := planStages(ctx, opts, op, subject, f.branch, scope, f.probes, nil, nil, nil)
	if err != nil {
		return err
	}
	plan := planned.res
	if plan.ProposedChange == nil {
		// Refused whole before any stage was planned: the kind absent, no open proposed
		// change on the branch, or the branch gone.
		return finish(op, subject, plan.Findings)
	}
	opts.c.steps = plan.Steps

	r := &rehearsing{opts: opts, op: op, subject: subject, planned: planned,
		ceiling: opts.rehearsalCeiling}
	if r.ceiling <= 0 {
		r.ceiling = rehearsal.Ceiling
	}
	baseline, rows, refusal := rehearsalStages(plan)
	r.rows = rows
	if refusal != nil {
		r.printPlan(0)
		return r.refuse(refusalStatus(plan), nil)
	}

	deadline, nodes, err := r.deadline()
	if err != nil {
		return r.failed(failAt(op, subject, findings.StepStart, op, "%v", err))
	}
	r.deadlineS = int(deadline / time.Second)
	r.printPlan(deadline)
	if !rehearsal.Fits(deadline, r.ceiling) {
		var unfit findings.List
		unfit.AddStep(findings.Rejection, findings.StepStart, findings.RuleRehearsalDeadlineUnfit, f.branch, fmt.Sprintf(
			"the stages need %s (%ds) to be rehearsed, over the ceiling of %s (%ds): no rehearsal is started whose "+
				"budgets cannot end within it; rehearse fewer stages", deadline, r.deadlineS, r.ceiling, int(r.ceiling/time.Second)))
		return r.refuse(findings.StatusRejected, unfit)
	}
	in, err := r.input(baseline, nodes)
	if err != nil {
		return r.failed(failAt(op, subject, findings.StepStart, op, "%v", err))
	}

	svc, err := opts.dial(ctx)
	if err != nil {
		return r.failed(startFailure(op, subject, findings.StepStart, err))
	}
	defer svc.Close()
	if refused := r.host(ctx, svc, rows[baseline]); refused != nil {
		return refused
	}
	return r.run(ctx, svc, in)
}

// rehearsalRow is one stage of the plan as the rehearsal takes it: the plan's stage, the
// role the baseline rule gives it, its findings (the plan's, and rehearsal.steps.none on a
// baseline alone), and, on the branch point passed over, the one rejection it was refused
// under.
type rehearsalRow struct {
	stage    stages.PlanStage
	role     string
	findings findings.List
	refused  *provision.RehearseRefusal
}

// rehearsalStages is the baseline rule (research R-03) over the plan's stages, in order. The
// branch point refused with exactly one rejection, scope.empty at read, is kept
// as a refused row and passed over. Any other stage refused or failed refuses the
// rehearsal: its findings are then the plan's, every stage's in order. The first compiled
// stage is the baseline, and each compiled stage after it is rehearsed; one compiled stage
// alone is the baseline, with the warning rehearsal.steps.none. baseline is the baseline's
// index, -1 when the rehearsal is refused.
func rehearsalStages(plan *stages.PlanResult) (baseline int, rows []rehearsalRow, refusal *findings.List) {
	baseline = -1
	refused := false
	for _, st := range plan.Stages {
		row := rehearsalRow{stage: st, findings: append(findings.List{}, st.Findings...)}
		switch {
		case st.Status == stages.PlanCompiled && baseline < 0:
			row.role, baseline = rehearsal.RoleBaseline, len(rows)
		case st.Status == stages.PlanCompiled:
			row.role = rehearsal.RoleRehearsed
		case passedOver(st):
			row.role = rehearsal.RoleRefused
			only := firstRejection(st.Findings)
			row.refused = &provision.RehearseRefusal{Rule: only.Rule, Message: only.Message}
		default:
			row.role, refused = rehearsal.RoleRefused, true
		}
		rows = append(rows, row)
	}
	if refused || baseline < 0 {
		list := append(findings.List{}, plan.Findings...)
		return -1, rows, &list
	}
	if len(rows)-baseline == 1 {
		b := &rows[baseline]
		b.findings.AddStep(findings.Warning, findings.StepResolve, findings.RuleRehearsalStepsNone, b.stage.Ref.String(),
			fmt.Sprintf("stage %s is the only stage that compiled: it is built, verified and destroyed, and no step is rehearsed",
				b.stage.Ref))
	}
	return baseline, rows, nil
}

// passedOver is whether a planned stage is the branch point refused at read scope.empty,
// the scope selecting no device on the default branch at the branch point, which may hold
// untagged devices, and for nothing else: the one refusal a rehearsal passes over (FR-003;
// 017's FR-015, US5 scenario 3). 0.2's generics read refused a default branch holding no
// contract instance there (R-20).
func passedOver(st stages.PlanStage) bool {
	if st.Status != stages.PlanRefused || st.AtSource != stages.AtBranchPoint {
		return false
	}
	n := 0
	for _, f := range st.Findings {
		if f.Severity != findings.Rejection {
			continue
		}
		if n++; f.Rule != findings.RuleScopeEmpty || f.Step != findings.StepRead {
			return false
		}
	}
	return n == 1
}

// firstRejection is the first rejection of a list that holds one.
func firstRejection(list findings.List) findings.Finding {
	for _, f := range list {
		if f.Severity == findings.Rejection {
			return f
		}
	}
	return findings.Finding{}
}

// refusalStatus is how a rehearsal the plan refused ends, as twin step's target ends: error,
// exit 2, when a stage could not be planned (operation.failed) or broke M1's precision rule,
// and rejected, exit 1, otherwise.
func refusalStatus(plan *stages.PlanResult) findings.Status {
	for _, st := range plan.Stages {
		if st.Status == stages.PlanFailed || carriesRule(st.Findings, findings.RuleAtPrecision) {
			return findings.StatusError
		}
	}
	return findings.StatusRejected
}

// rehearsing is one twin rehearse as the server decides and reports it: the request, the
// plan, the rows the baseline rule made of it, the ceiling and the deadline, the dead
// rehearsal reclaimed first, and the findings filed before the run.
type rehearsing struct {
	opts      *options
	op        string
	subject   *findings.Subject
	planned   plannedStages
	rows      []rehearsalRow
	ceiling   time.Duration
	deadlineS int
	reclaimed *findings.RehearsalReclaim
	before    findings.List
}

// deadline is the time the rehearsal is bounded by, summed by rehearsal.Deadline from each
// compiled stage's node plans, read from its copy in the store as the host check plans them
// and without looking at the host (research R-09); and those plans, by stage reference, for
// the step chain's declarations.
func (r *rehearsing) deadline() (time.Duration, map[string][]wire.NodePlan, error) {
	store := bundle.NewDirStore(r.planned.paths.Bundles)
	nodes := map[string][]wire.NodePlan{}
	var counted []rehearsal.DeadlineStage
	for _, row := range r.rows {
		if row.stage.Bundle == nil {
			continue
		}
		plans, err := lab.NodePlans(store.Path(row.stage.Bundle.ID), r.planned.reg, r.planned.packages)
		if err != nil {
			return 0, nil, fmt.Errorf("planning stage %s's nodes for the deadline: %v", row.stage.Ref, err)
		}
		nodes[row.stage.Ref.String()] = plans
		counted = append(counted, rehearsal.DeadlineStage{Role: row.role, Nodes: plans})
	}
	return rehearsal.Deadline(provision.DeadlineMechanism(), counted), nodes, nil
}

// input is the run's input: every stage of the plan in order with its role, the baseline's
// provision and each rehearsed stage's step from the stage before it (R-05).
func (r *rehearsing) input(baseline int, nodes map[string][]wire.NodePlan) (provision.RehearseInput, error) {
	pc := r.planned.res.ProposedChange
	stagesIn, err := rehearseStages(r.rows, baseline, r.planned.res.Steps, nodes, r.planned.reg,
		bundle.NewDirStore(r.planned.paths.Bundles).Path, r.planned.scope, r.opts.version())
	if err != nil {
		return provision.RehearseInput{}, err
	}
	return provision.RehearseInput{
		ProposedChange: findings.StageChange{ID: pc.ID, Name: pc.Name, Branch: pc.Branch, Draft: pc.Draft},
		ResolvedAt:     r.resolvedAt(),
		DeadlineS:      r.deadlineS,
		CeilingS:       int(r.ceiling / time.Second),
		Stages:         stagesIn,
		Version:        r.opts.version(),
	}, nil
}

// resolvedAt is when the server began to resolve and read the stages, RFC 3339 UTC.
func (r *rehearsing) resolvedAt() string { return r.planned.now.UTC().Format(time.RFC3339) }

// rehearseStages is every stage of the plan as the run takes it, in order (data-model §6):
// its reference, its mark's words, what it resolved to, the snapshot it was taken as (018)
// and what it compiled to, and its role, a refused stage naming neither; the baseline's
// provision, already compiled, with its stage and its snapshot; and each rehearsed stage's step
// from the compiled stage before it, as twin step builds one but reading no twin (research
// R-05): From the previous stage's side, To the target's, the store's copy of its bundle,
// the plan's step between the two and what it changes, the push plan before containerlab's
// plan is known, every target node's declared link change, restarts allowed, the default
// wait, and an empty plan, since the run reads containerlab's own at its step 3.
func rehearseStages(rows []rehearsalRow, baseline int, pairs []step.Pair, nodes map[string][]wire.NodePlan,
	reg *psp.Registry, bundlePath func(id string) string, scope, version string) ([]provision.RehearseStage, error) {
	waitS := int(verify.DefaultBudget / time.Second)
	out := make([]provision.RehearseStage, 0, len(rows))
	var prev *stages.PlanStage
	for i, row := range rows {
		st := row.stage
		in := provision.RehearseStage{Ref: st.Ref.String(), Label: st.Label, Description: st.Description,
			AtSource: st.AtSource, Refused: row.refused, Role: row.role, WaitS: waitS}
		if res := st.Resolved; res != nil {
			in.Branch, in.At = res.Branch, res.At
		}
		if st.Bundle == nil {
			out = append(out, in)
			continue
		}
		in.SnapshotID, in.BundleID, in.BundlePath = st.SnapshotID, st.Bundle.ID, bundlePath(st.Bundle.ID)
		switch {
		case i == baseline:
			r := st.Resolved
			in.Provision = &provision.ProvisionInput{Source: wire.SourceIntent, Branch: r.Branch, At: r.At,
				BundlePath: in.BundlePath, BundleID: in.BundleID, ObservedAt: st.ObservedAt, SnapshotID: st.SnapshotID,
				Stage: r.StageRef(), Version: version, Scope: scope}
		case prev != nil:
			pair, ok := pairBetween(pairs, prev.Ref.String(), in.Ref)
			if !ok {
				return nil, fmt.Errorf("the plan holds no step from %s to %s", prev.Ref, in.Ref)
			}
			diff, err := json.Marshal(pair)
			if err != nil {
				return nil, err
			}
			in.Diff = diff
			if in.Step, err = rehearsedStep(*prev, st, *pair.Step, diff, nodes[in.Ref], reg, in.BundlePath, waitS, version); err != nil {
				return nil, fmt.Errorf("stage %s: %w", in.Ref, err)
			}
		}
		out = append(out, in)
		prev = &rows[i].stage
	}
	return out, nil
}

// pairBetween is the plan's step from one stage to the next, when the plan computed it.
func pairBetween(pairs []step.Pair, from, to string) (step.Pair, bool) {
	for _, p := range pairs {
		if p.From == from && p.To == to && p.Step != nil {
			return p, true
		}
	}
	return step.Pair{}, false
}

// rehearsedStep is the step run's input from one compiled stage to the next, each side
// naming its stage's snapshot (018), as twin step's do, and its flows the probes both
// stages' bundles carry, from the two manifests and the target's node plans as twin step
// takes them (flowsOf; 016), so the stage's loss is its step's.
func rehearsedStep(from, to stages.PlanStage, s step.Step, diff []byte, nodes []wire.NodePlan, reg *psp.Registry,
	toPath string, waitS int, version string) (*provision.StepInput, error) {
	declared := map[string]string{}
	for _, n := range nodes {
		linkChange := ""
		if p, ok := reg.LookupID(n.PSPID); ok {
			linkChange = p.Fidelity.LinkChange
		}
		declared[n.Name] = linkChange
	}
	// An unchanged step pushes nobody, as the run does; the run adds to the rest what its
	// own plan restarts, recreates or creates.
	pushes := []step.NodePush{}
	if !s.Unchanged {
		pushes = step.PushPlan(s, step.Lifecycle{})
	}
	var fm, tm compiler.Manifest
	if err := json.Unmarshal(from.Bundle.Files[compiler.ManifestFile], &fm); err != nil {
		return nil, fmt.Errorf("reading bundle %s's manifest: %w", from.Bundle.ID, err)
	}
	if err := json.Unmarshal(to.Bundle.Files[compiler.ManifestFile], &tm); err != nil {
		return nil, fmt.Errorf("reading bundle %s's manifest: %w", to.Bundle.ID, err)
	}
	flows, added, dropped, err := flowsOf(fm, tm, nodes)
	if err != nil {
		return nil, err
	}
	f, t := from.Resolved, to.Resolved
	return &provision.StepInput{
		From:         wire.StepSide{Stage: f.StageRef(), SnapshotID: from.SnapshotID, BundleID: from.Bundle.ID, At: f.At},
		To:           wire.StepSide{Stage: t.StageRef(), SnapshotID: to.SnapshotID, BundleID: to.Bundle.ID, At: t.At, Branch: t.Branch},
		ObservedAt:   to.ObservedAt,
		ToBundlePath: toPath,
		Diff:         diff,
		Unchanged:    s.Unchanged,
		Plan:         wire.ReconcilePlan{},
		PushPlan:     pushes,
		Changed:      provision.ChangesOf(s),
		AllowRestart: true,
		Declared:     declared,
		WaitS:        waitS,
		Version:      version,
		Flows:        flows,
		Added:        added,
		Dropped:      dropped,
	}, nil
}

// printPlan prints the plan as the rehearsal takes it (contracts/rehearse-command.md, "The
// text"): the heading, with the deadline once it is known and ending with the scope every
// stage was read under (017), then one line per stage, its resolution and its role, or why
// it was refused, and its findings under it, indented.
func (r *rehearsing) printPlan(deadline time.Duration) {
	pc := r.planned.res.ProposedChange
	line := fmt.Sprintf("rehearsal of proposed change %q (%s) on branch %s", pc.Name, pc.ID, pc.Branch)
	if pc.Draft {
		line += ", draft"
	}
	line += ": " + plural(len(r.rows), "stage")
	if deadline > 0 {
		line += fmt.Sprintf("; deadline %s (ceiling %s)", deadline, r.ceiling)
	}
	line += ", scope " + r.planned.scope
	r.opts.note("%s", line)
	for _, row := range r.rows {
		st := row.stage
		switch {
		case st.Status != stages.PlanCompiled:
			why := st.Status
			if st.Rule != "" {
				why = fmt.Sprintf("%s (%s)", st.Status, st.Rule)
			}
			r.opts.note("%s: %s", st.Ref, why)
		case row.role == rehearsal.RoleBaseline:
			r.opts.note("%s: %s; baseline", st.Ref, st.Resolved.Block().Resolution())
		default:
			r.opts.note("%s: %s", st.Ref, st.Resolved.Block().Resolution())
		}
		for _, l := range row.findings.TextLines() {
			r.opts.note("  %s", l)
		}
	}
}

// report is the report's input: the proposed change, when its stages were resolved, the
// scope they were read under, which the commands that reproduce a failure name, the deadline
// and the ceiling, the reclaim, and every stage with its role and its findings, and its
// snapshot and bundle once it compiled. A refused stage names neither (018; formats.md §7),
// even one whose compile was refused after its snapshot was filed, which stage plan names.
func (r *rehearsing) report() rehearsal.Input {
	pc := r.planned.res.ProposedChange
	in := rehearsal.Input{ProposedChange: findings.StageChange{ID: pc.ID, Name: pc.Name, Branch: pc.Branch, Draft: pc.Draft},
		ResolvedAt: r.resolvedAt(), Scope: r.planned.scope, DeadlineS: r.deadlineS, CeilingS: int(r.ceiling / time.Second),
		Reclaimed: r.reclaimed}
	for _, row := range r.rows {
		st := rehearsal.Stage{Ref: row.stage.Ref.String(), Label: row.stage.Label, Description: row.stage.Description,
			AtSource: row.stage.AtSource, BundleID: row.stage.BundleID(), Role: row.role, Findings: row.findings}
		if row.stage.Bundle != nil {
			st.SnapshotID = row.stage.SnapshotID
		}
		if res := row.stage.Resolved; res != nil {
			st.Branch, st.At = res.Branch, res.At
		}
		in.Stages = append(in.Stages, st)
	}
	return in
}

// refuse ends a rehearsal refused before any run with status: the block, every stage not
// reached but the refused, the findings filed before the run, then extra.
func (r *rehearsing) refuse(status findings.Status, extra findings.List) error {
	block := rehearsal.Build(r.report(), rehearsal.Result{})
	list := append(append(append(findings.List{}, r.before...), rehearsal.Findings(block)...), extra...)
	doc := findings.NewDocument(r.op, r.subject, list)
	doc.Status = status
	doc.Rehearsal = &block
	return &result{doc: doc}
}

// failed carries the block and the findings filed before the run onto a failure's document,
// built fresh, as twin step's withFound does: the stages are known, and the comment a check
// posts names them.
func (r *rehearsing) failed(err error) error {
	res, ok := err.(*result)
	if !ok {
		return err
	}
	block := rehearsal.Build(r.report(), rehearsal.Result{})
	res.doc.Findings = append(append(append(findings.List{}, r.before...), rehearsal.Findings(block)...), res.doc.Findings...)
	res.doc.Rehearsal = &block
	return res
}

// host is steps 4 and 5 (research R-04): the runs in flight through the service, then the
// host in this process. The twin of a rehearsal whose run is no longer running is reclaimed
// through the destroy run, which refuses rather than cancels a run begun since the read, its
// progress in the answer before the start; a destroy that leaves something refuses the
// rehearsal with cleanup.incomplete, exit 4. Then the host check of the baseline's bundle,
// as a dry run makes it, every refusal it makes under its identifier at host_check. Any
// other record, a hand twin's or an orphan's, is the host check's to refuse, and is never
// reclaimed. nil when the host takes the baseline.
func (r *rehearsing) host(ctx context.Context, svc provision.Service, baseline rehearsalRow) error {
	op, subject := r.op, r.subject
	runs, err := svc.InFlight(ctx)
	if err != nil {
		return r.failed(startFailure(op, subject, findings.StepStart, err))
	}
	if held := holdingRun(runs); held != nil {
		return r.failed(&result{doc: provision.InFlightRefusal(held.WorkflowID, held.RunID).Document(op, subject)})
	}

	acts := r.opts.c.activities(r.planned.reg, r.planned.packages, r.planned.paths)
	host, err := acts.InspectHost(ctx)
	if err != nil {
		return r.failed(failAt(op, subject, findings.StepHostCheck, "lab "+wire.LabName, "inspecting the host: %v", err))
	}
	if rec := host.Twin; rec != nil && rec.Rehearsal != nil && rec.Rehearsal.WorkflowID == provision.WorkflowRehearse {
		if refused := r.reclaim(ctx, svc, *rec.Rehearsal); refused != nil {
			return refused
		}
	}

	bundlePath := bundle.NewDirStore(r.planned.paths.Bundles).Path(baseline.stage.Bundle.ID)
	plan, err := lab.CheckHost(ctx, acts, wire.CheckHostInput{BundlePath: bundlePath, BundleID: baseline.stage.Bundle.ID})
	if err != nil {
		return r.failed(failAt(op, subject, findings.StepHostCheck, findings.StepHostCheck, "host check: %s", activityMessage(err)))
	}
	// The baseline's provision checks the host again and reports its warnings; only a
	// refusal is the server's to report.
	if plan.Findings.Rejected() {
		return r.refuse(findings.StatusRejected, plan.Findings)
	}
	return nil
}

// holdingRun is the run in flight that refuses a rehearsal (contracts/rehearse-command.md,
// step 4): a rehearsal, or a provisioning, step or destroy run of the operator's; nil when
// none is running. A rehearsal's child is listed under the rehearsal, which holds the host
// first.
func holdingRun(runs []provision.RunInFlight) *provision.RunInFlight {
	for i, r := range runs {
		switch r.WorkflowID {
		case provision.WorkflowRehearse, provision.WorkflowProvision, provision.WorkflowStep, provision.WorkflowDestroy:
			return &runs[i]
		}
	}
	return nil
}

// reclaim destroys the twin dead's rehearsal left, through the destroy run as twin destroy
// follows it, its progress in the answer under the notice that names the dead run, with no
// frame of its own before the rehearsal's start. The start reads the runs in flight again
// and cancels none: one begun since host's read refuses the rehearsal, run.in_flight naming
// it, exit 1, with no reclaimed block. What the destroy removed is the block's reclaimed and
// the warning rehearsal.twin.reclaimed; a destroy that leaves something refuses the
// rehearsal, cleanup.incomplete, exit 4. nil once the twin is gone.
func (r *rehearsing) reclaim(ctx context.Context, svc provision.Service, dead wire.RehearsalRef) error {
	r.opts.note("reclaiming the twin of rehearsal run %s", dead.RunID)
	run, err := svc.StartReclaim(ctx, func(e provision.Event) {
		r.opts.c.eventFrame(e)
		printEvent(r.opts, e)
	})
	if err != nil {
		return r.failed(startFailure(r.op, r.subject, findings.StepDestroy, err))
	}
	printCleanup(r.opts, run.Result.Cleanup)
	r.reclaimed = &findings.RehearsalReclaim{Run: findings.ShowRef{WorkflowID: provision.WorkflowRehearse, RunID: dead.RunID},
		Cleanup: *provision.CleanupBlockOf(run.Result.Cleanup)}
	r.before = append(r.before, run.Result.Findings...)
	if len(run.Result.Cleanup.Remaining) > 0 {
		return r.refuse(findings.StatusUnclean, nil)
	}
	removed := "nothing was left to remove"
	if items := run.Result.Cleanup.Removed; len(items) > 0 {
		removed = "it removed " + strings.Join(items, ", ")
	}
	r.before.AddStep(findings.Warning, findings.StepDestroy, findings.RuleRehearsalTwinReclaimed, dead.RunID, fmt.Sprintf(
		"the twin of rehearsal run %s, which is no longer running, was destroyed by destroy run %s before this rehearsal: %s",
		dead.RunID, run.RunID, removed))
	return nil
}

// run starts the rehearsal and follows it and its children to its close, its destroy
// included, then reports (steps 6 and 7; research R-10, R-12). The interrupt is taken from
// the start frame, as a create's is: the first asks the run to cancel and waits for its
// destroy, the second stops waiting.
func (r *rehearsing) run(ctx context.Context, svc provision.Service, in provision.RehearseInput) error {
	op, subject := r.op, r.subject
	interrupts, err := r.opts.c.startFrame(provision.WorkflowRehearse)
	if err != nil {
		return r.failed(goneBeforeStart(op, subject, provision.WorkflowRehearse, err))
	}
	runID, interrupted, err := startRun(ctx, provision.WorkflowRehearse,
		func(ctx context.Context) (string, error) { return svc.StartRehearse(ctx, in) }, interrupts)
	if err != nil {
		return r.failed(startFailure(op, subject, findings.StepStart, err))
	}
	subject.RunID = runID
	r.opts.c.runFrame(provision.WorkflowRehearse, runID)

	p := newRehearsalPrinter(r.opts, in)
	res, err := followRun(ctx, r.opts, svc, op, subject, provision.WorkflowRehearse, runID, interrupts, interrupted,
		func(ctx context.Context) (provision.RehearseResult, error) { return svc.ResultOfRehearse(ctx, runID) },
		"run cancelled; waiting for its destroy", p.print)
	if err != nil {
		return r.lost(runID, err)
	}
	return r.reported(ctx, runID, res, p.followed.get())
}

// lost is the document of a run that started and whose end was not read: its result could
// not be read, or the operator's second interrupt stopped waiting. The block names the run,
// and every stage as the answer left it, not reached, with no destroy, since none was read;
// the closing line and the markdown say the run was started, why its end was not read, and
// that it goes on to its destroy, which twin show follows (FR-021). No stage line is
// printed: the answer learned nothing of them.
func (r *rehearsing) lost(runID string, err error) error {
	res, ok := err.(*result)
	if !ok {
		return err
	}
	block := rehearsal.Build(r.report(), rehearsal.Result{Run: &findings.ShowRef{WorkflowID: provision.WorkflowRehearse, RunID: runID}})
	res.doc.Findings = append(append(append(findings.List{}, r.before...), rehearsal.Findings(block)...), res.doc.Findings...)
	res.doc.Rehearsal = &block
	r.opts.note("%s", rehearsal.Closing(res.doc))
	return res
}

// reported is the rehearsal's document once its run closed: the block through
// rehearsal.Build, its findings and the run's, the destroy's, the stages read again for
// whether a rehearsed stage moved or the proposed change closed, and the status by
// research R-08; then what the destroy removed, the text's line per stage and its closing
// line.
func (r *rehearsing) reported(ctx context.Context, runID string, res provision.RehearseResult, reached string) error {
	block := rehearsal.Build(r.report(), resultOf(runID, res))
	list := append(append(findings.List{}, r.before...), rehearsal.Findings(block)...)
	list = append(list, res.Findings...)
	if d := res.Destroy; d != nil {
		list = append(list, d.Findings...)
	} else if res.Outcome != rehearsal.OutcomeRejected {
		list.AddStep(findings.Rejection, findings.StepDestroy, findings.RuleCleanupIncomplete, runID, fmt.Sprintf(
			"rehearsal run %s closed without its destroy's report, so what the host holds is not known; fylgja twin show "+
				"says what it holds, and fylgja twin destroy clears it", runID))
	}
	if res.Outcome == rehearsal.OutcomeCancelled {
		list.AddStep(findings.Rejection, reached, findings.RuleRunCancelled, runID, fmt.Sprintf(
			"rehearsal run %s was cancelled at stage %s, by the operator's interrupt or a twin destroy; its destroy ran",
			runID, res.Reached))
	}
	list = append(list, r.after(ctx, block)...)

	doc := findings.NewDocument(r.op, r.subject, list)
	doc.Status = rehearsalStatus(res)
	doc.Rehearsal = &block
	// What the destroy removed, as twin destroy and the reclaim say it, straight after its
	// progress lines; what remains is named by its cleanup.incomplete findings.
	if d := res.Destroy; d != nil {
		printCleanup(r.opts, d.Cleanup)
	}
	for _, l := range rehearsal.StageLines(block) {
		r.opts.note("%s", l)
	}
	r.opts.note("%s", rehearsal.Closing(doc))
	return &result{doc: doc}
}

// rehearsalStatus is how a rehearsal that ran ends (research R-08): rejected, exit 1, when its
// baseline's provision could not start because another run holds its id, which touched
// nothing and needs no destroy (FR-007, FR-009); unclean, exit 4, when its destroy left
// something, whatever the stages did; otherwise ok when every rehearsed stage passed,
// nonconforming, exit 5, when a stage failed, failed, exit 3, when the baseline could not be
// built, and error, exit 2, when a stage could not be rehearsed, the deadline cut the
// rehearsal or the run was cancelled.
func rehearsalStatus(res provision.RehearseResult) findings.Status {
	if res.Outcome == rehearsal.OutcomeRejected {
		return findings.StatusRejected
	}
	if d := res.Destroy; d == nil || len(d.Cleanup.Remaining) > 0 {
		return findings.StatusUnclean
	}
	switch res.Outcome {
	case rehearsal.OutcomeOK:
		return findings.StatusOK
	case rehearsal.OutcomeStageFailed:
		return findings.StatusNonconforming
	case rehearsal.OutcomeBaselineFailed:
		return findings.StatusFailed
	}
	return findings.StatusError
}

// resultOf is the run's result as the report reads it: each stage it reached, with its child,
// that child's findings, its wait and counts, and the destroy's cleanup.
func resultOf(runID string, res provision.RehearseResult) rehearsal.Result {
	out := rehearsal.Result{Outcome: res.Outcome, Run: &findings.ShowRef{WorkflowID: provision.WorkflowRehearse, RunID: runID},
		UsedS: res.UsedS}
	if d := res.Destroy; d != nil {
		out.Destroy = provision.CleanupBlockOf(d.Cleanup)
	}
	for _, s := range res.Stages {
		st := rehearsal.StageResult{Ref: s.Ref, Verdict: s.Verdict, Wait: s.Wait, Counts: s.Counts, NewFindings: s.NewFindings,
			TookS: s.TookS}
		childRun := ""
		if s.Run != nil {
			childRun = s.Run.RunID
		}
		if p := s.Provision; p != nil {
			st.Provision = &rehearsal.Provision{Outcome: p.Outcome, RunID: childRun, Step: p.Step}
			if p.Outcome != provision.OutcomeReady {
				st.Provision.Cleanup = provision.CleanupBlockOf(p.Cleanup)
			}
			st.Findings = p.Findings
		}
		if sr := s.Step; sr != nil {
			run := &rehearsal.StepRun{Outcome: sr.Outcome, Phase: sr.Phase, Step: sr.Step, RunID: childRun,
				Pushed: sr.PushPlan, Timings: sr.Timings}
			if lp := sr.Plan; lp != nil {
				run.Restarted, run.Recreated, run.Created = lp.Restarted, lp.Recreated, lp.Added
			}
			st.Step = run
			st.Loss = provision.LossBlockOf(sr.Loss)
			st.Findings = sr.Findings
		}
		out.Stages = append(out.Stages, st)
	}
	return out
}

// after reads the proposed change's stages again once the run has closed, as stage list
// lists them, for movedOrClosed's warnings. Stages that cannot be read again are
// rehearsal.stage.moved naming the branch: whether one moved is unknown.
func (r *rehearsing) after(ctx context.Context, block findings.RehearsalBlock) findings.List {
	branch := r.planned.res.Branch
	res, refused, err := stages.List(ctx, r.planned.reader, newIntentStamper(), branch, r.planned.scope, nil)
	if err == nil && refused.Rejected() {
		err = fmt.Errorf("%s", firstRejection(refused).Message)
	}
	if err != nil {
		var list findings.List
		list.AddStep(findings.Warning, findings.StepResolve, findings.RuleRehearsalStageMoved, branch, fmt.Sprintf(
			"the stages of branch %s could not be read again after the run (%v): whether a rehearsed stage moved is unknown",
			branch, err))
		return list
	}
	return movedOrClosed(branch, block, res.Rows)
}

// movedOrClosed compares the stages as they were rehearsed with rows, the stages listed
// again after the run: rehearsal.change.closed when the proposed change is no longer open
// on branch, and otherwise rehearsal.stage.moved for each stage the rehearsal built or
// stepped to, the head included, that no longer resolves to the branch and at it was
// rehearsed at, or is gone. Both are warnings: what was rehearsed stands.
func movedOrClosed(branch string, block findings.RehearsalBlock, rows []stages.Row) findings.List {
	var list findings.List
	now := map[string]stages.Row{}
	for _, row := range rows {
		if row.ProposedChange.ID == block.ProposedChange.ID {
			now[row.Ref.String()] = row
		}
	}
	if len(now) == 0 {
		list.AddStep(findings.Warning, findings.StepResolve, findings.RuleRehearsalChangeClosed, branch, fmt.Sprintf(
			"proposed change %q (%s) is no longer open on branch %s: it was rehearsed as it stood at %s",
			block.ProposedChange.Name, block.ProposedChange.ID, branch, block.ResolvedAt))
		return list
	}
	for _, s := range block.Stages {
		if s.Role != rehearsal.RoleBaseline && s.Role != rehearsal.RoleRehearsed {
			continue
		}
		row, ok := now[s.Ref]
		switch {
		case !ok:
			list.AddStep(findings.Warning, findings.StepResolve, findings.RuleRehearsalStageMoved, s.Ref, fmt.Sprintf(
				"stage %s was rehearsed at branch %s at %s, and is gone from the proposed change", s.Ref, s.Branch, s.At))
		case row.Branch != s.Branch || row.At != s.At:
			list.AddStep(findings.Warning, findings.StepResolve, findings.RuleRehearsalStageMoved, s.Ref, fmt.Sprintf(
				"stage %s was rehearsed at branch %s at %s, and now resolves to branch %s at %s", s.Ref, s.Branch, s.At,
				row.Branch, atText(row.At)))
		}
	}
	return list
}

// rehearsalPrinter prints a rehearsal's progress (contracts/rehearse-command.md, "The
// text"): each child the run starts announced by the line naming its stage, as the children
// come in the input's order, its own lines as every run prints them, and the baseline's wait
// as that stage's verify. It keeps the step the run reached before its destroy, for the
// run's cancellation to name: the destroy runs last whatever stopped the run.
type rehearsalPrinter struct {
	opts      *options
	baseline  string
	rehearsed []string
	next      int
	followed  *followedStep
}

// The steps a rehearsal names its children by (provision.Client.Follow).
const (
	rehearseProvision = "provision"
	rehearseStep      = "step"
	rehearseDestroy   = "destroy"
)

func newRehearsalPrinter(opts *options, in provision.RehearseInput) *rehearsalPrinter {
	p := &rehearsalPrinter{opts: opts, followed: &followedStep{}}
	for _, s := range in.Stages {
		switch s.Role {
		case rehearsal.RoleBaseline:
			p.baseline = s.Ref
		case rehearsal.RoleRehearsed:
			p.rehearsed = append(p.rehearsed, s.Ref)
		}
	}
	return p
}

func (p *rehearsalPrinter) print(e provision.Event) {
	if !ofTheDestroy(e) {
		p.followed.observe(e)
	}
	if e.Notice != "" || e.WorkflowID != provision.WorkflowRehearse {
		printEvent(p.opts, e)
		return
	}
	switch {
	case e.Step == rehearseProvision && !e.End:
		p.opts.note("stage %s: creating the twin", p.baseline)
	case e.Step == rehearseStep && !e.End:
		ref := "?"
		if p.next < len(p.rehearsed) {
			ref = p.rehearsed[p.next]
		}
		p.next++
		p.opts.note("stage %s: stepping", ref)
	case e.Step == rehearseDestroy && !e.End:
		p.opts.note("destroying the twin")
	case e.Step == stepObserve && !e.End:
		// Its end says how the wait went.
	case e.Step == stepObserve:
		printLabelled(p.opts, "stage "+p.baseline+": verify", e)
	case e.End && e.Outcome == provision.EventDone:
		// A child's close: its own lines said how it ended.
	default:
		printEvent(p.opts, e)
	}
}

// ofTheDestroy is whether an event is the rehearsal's destroy's: its own step that runs the
// destroy child, or that child's.
func ofTheDestroy(e provision.Event) bool {
	return e.WorkflowID == provision.WorkflowDestroy || e.WorkflowID == provision.WorkflowRehearse && e.Step == rehearseDestroy
}
