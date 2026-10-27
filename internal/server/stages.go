package server

import (
	"context"
	"fmt"
	"sync"
	"time"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/stages"
	"github.com/happypathnetworking/fylgja/internal/step"
)

type stageFlags struct {
	branch string
	// branchGiven is whether --branch was given at all, apart from its value: an explicit
	// empty one is a branch refused, not one left out (M4's --interval= precedent).
	branchGiven bool
	// scope is --scope as given, read only when scopeGiven: not given, the server's default
	// stands (017).
	scope      string
	scopeGiven bool
}

// branchGuard refuses a --branch that is not a branch as the reference syntax names one,
// before any connection: stage.ref.invalid, exit 2, at step start, in the shape a
// --stage's refusal takes (specs/014-proposed-change-stages/contracts/stage-reference.md).
func branchGuard(op, branch string) error {
	err := stages.CheckBranch(branch)
	if err == nil {
		return nil
	}
	doc := findings.RuleErrorDocument(op, nil, findings.RuleStageRefInvalid, branch, err.Error())
	doc.Findings[0].Step = findings.StepStart
	return &result{doc: doc}
}

// intentStamper is the stages' Stamper on the server: an intent client per (branch, at,
// scope), whose Stamps reads when the intent and the artifacts were written and never a
// value of intent, with the at verbatim on every page, or none when it is empty.
//
// Before a branch's first stamps read it checks the branch's conformance, once per branch
// for the command it serves, so a plan does not fetch the schema per stage (017): the
// stamps select the library's kinds, and on a branch whose schema lacks one they would
// fail naming nothing of the mapping's table. A branch that does not conform answers every
// stamps read with an *intent.ConformanceError, which the stages file as its schema.*
// findings. The schema endpoint has no time axis, so the check is unpinned whatever the at.
// One per command: newIntentStamper.
type intentStamper struct {
	mu sync.Mutex
	// conformed is each branch checked so far: nil when it conforms, its
	// *intent.ConformanceError when it does not. A check that could not run is not kept.
	conformed map[string]error
}

// newIntentStamper is a command's stamper, which has checked no branch yet.
func newIntentStamper() *intentStamper {
	return &intentStamper{conformed: map[string]error{}}
}

func (s *intentStamper) Stamps(ctx context.Context, branch, at, scope string) (intent.Stamps, error) {
	cfg, err := intent.FromEnv(branch, at)
	if err != nil {
		return intent.Stamps{}, err
	}
	cfg.Scope = intent.ScopeTag(scope)
	client := intent.New(cfg)
	if err := s.conform(ctx, branch, client); err != nil {
		return intent.Stamps{}, err
	}
	return client.Stamps(ctx)
}

// conform is branch's conformance, checked through client the first time the branch is
// asked for and remembered after.
func (s *intentStamper) conform(ctx context.Context, branch string, client *intent.Client) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if err, ok := s.conformed[branch]; ok {
		return err
	}
	_, list, err := client.CheckConformance(ctx)
	if err != nil {
		return err
	}
	var refused error
	if list.Rejected() {
		refused = &intent.ConformanceError{Branch: branch, Findings: list}
	}
	s.conformed[branch] = refused
	return refused
}

// The noun stage (014, D-045): a proposed change's stages, the operator's marks between
// its two derived ends, listed and planned. Both verbs dial Infrahub and nothing else: no
// workflow service, no worker, no containerlab, no host budget.

// runStageList lists the stages of every open proposed change, or of the one whose source
// branch --branch names. The kind absent from the default branch is stage.kind.absent,
// exit 1; an Infrahub that cannot be reached or refuses the credential is operation.failed,
// exit 2, at step resolve, as a create's resolution reports it. A reserved label among the
// rows is a rejection beside them, exit 1, the rows still listed; the warnings leave the
// exit 0.
func runStageList(ctx context.Context, opts *options, f *stageFlags) error {
	const op = findings.OpStageList
	if f.branchGiven {
		if refused := branchGuard(op, f.branch); refused != nil {
			return refused
		}
	}
	// The scope the heads' stamps are read under (017), after --branch's guard and before
	// any connection.
	scope, err := scopeOf(opts, op, nil, f.scope, f.scopeGiven)
	if err != nil {
		return err
	}
	subject := &findings.Subject{Scope: scope}
	if ctx == nil {
		ctx = context.Background()
	}
	reader, err := intent.StageReaderFromEnv()
	if err != nil {
		return failAt(op, subject, findings.StepResolve, op, "%v", err)
	}
	res, list, err := stages.List(ctx, reader, newIntentStamper(), f.branch, scope, recordView(hostRecord(opts)))
	if err != nil {
		return failAt(op, subject, findings.StepResolve, op, "%v", err)
	}
	doc := findings.NewDocument(op, subject, list)
	if carriesRule(list, findings.RuleStageKindAbsent) {
		return &result{doc: doc}
	}
	printList(opts, res)
	doc.Stages = res.Block()
	return &result{doc: doc}
}

// hostRecord is twin.json under the state root, or nil when it is absent or cannot be
// read: the host is twin show's to report, and the list says nothing of it but the mark.
// The record carries its state and its last step, so the mark can say a twin is diverged
// and which stage it was stepping towards.
func hostRecord(opts *options) *wire.TwinRecord {
	paths, err := opts.paths()
	if err != nil {
		return nil
	}
	rec, err := lab.ReadRecord(paths.TwinJSON)
	if err != nil {
		return nil
	}
	return &rec
}

// recordView is the record's stage as the listing and the step judge it, nil when there
// is none, carrying the record's scope when it names one this build reads under
// (scopeKnown): its head is judged under that scope, never the listing's (017). A record
// naming none carries "", and is judged under the listing's.
func recordView(rec *wire.TwinRecord) *stages.RecordView {
	v := stages.RecordViewOf(rec)
	if v != nil && scopeKnown(rec) {
		v.Scope = rec.Provenance.Scope
	}
	return v
}

// heading names one proposed change as the list and the plan head its stages
// (specs/014-proposed-change-stages/contracts/stage-commands.md): its name quoted, its
// id, its source branch, the destination when into is set, whether it is a draft, and how
// many stages it has; then, when scope is given, the scope every stage was read under,
// as the plan's heading ends (017; contracts/scope-and-commands.md, "The text").
func heading(pc stages.ProposedChange, into bool, n int, scope string) string {
	line := fmt.Sprintf("proposed change %q (%s) on branch %s", pc.Name, pc.ID, pc.Branch)
	if into {
		line += " → " + pc.Destination
	}
	if pc.Draft {
		line += ", draft"
	}
	line += " (" + plural(n, "stage") + ")"
	if scope != "" {
		line += ", scope " + scope
	}
	return line
}

// printList prints the listing: a heading per proposed change, then one line per stage
// with its reference, branch, at and source padded so the ats and the descriptions line up
// within the proposed change, whatever each at's width (Infrahub writes a branch's origin
// with Z and a stamp with +00:00), the description quoted, and the twin's row marked;
// beside a diverged record the mark says which stage the failed step was going to. A stage
// with no at shows it unresolved. The orphans follow, one line each.
func printList(opts *options, res stages.ListResult) {
	twinMark := "  ← twin"
	if r := res.Record; r != nil && r.State == wire.StateDiverged && r.Towards != "" {
		twinMark = fmt.Sprintf("  ← twin (diverged towards %s)", stages.Ref{Branch: r.ProposedChange.Branch, Label: r.Towards})
	}
	if len(res.Rows) == 0 {
		if res.Branch != "" {
			opts.note("branch %s: no open proposed change", res.Branch)
		} else {
			opts.note("no open proposed change")
		}
	}
	for start := 0; start < len(res.Rows); {
		end := start
		for end < len(res.Rows) && res.Rows[end].ProposedChange.ID == res.Rows[start].ProposedChange.ID {
			end++
		}
		rows := res.Rows[start:end]
		refWidth, branchWidth, atWidth, sourceWidth := 0, 0, 0, 0
		for _, r := range rows {
			refWidth = max(refWidth, len(r.Ref.String()))
			branchWidth = max(branchWidth, len(r.Branch))
			atWidth = max(atWidth, len(atText(r.At)))
			sourceWidth = max(sourceWidth, len(source(r.AtSource)))
		}
		opts.note("%s", heading(rows[0].ProposedChange, false, len(rows), ""))
		for _, r := range rows {
			mark := ""
			if r.Twin {
				mark = twinMark
			}
			opts.note("  %-*s  %-*s  at %-*s %-*s  %q%s", refWidth, r.Ref, branchWidth, r.Branch, atWidth, atText(r.At),
				sourceWidth, source(r.AtSource), r.Description, mark)
		}
		start = end
	}
	for _, o := range res.Orphans {
		opts.note("orphaned: stage %q (%s) names no proposed change", o.Label, o.ID)
	}
}

// atText is a listed at as the text prints it: verbatim, or unresolved when the stage has
// none.
func atText(at string) string {
	if at == "" {
		return "unresolved"
	}
	return at
}

// source is where an at came from as the text names it, in parentheses: (written),
// (branch point).
func source(atSource string) string { return "(" + findings.AtSourceText(atSource) + ")" }

// runStagePlan plans the open proposed change whose source branch --branch names: each of
// its stages read, compiled and filed in the store on the stage pipeline, and the step
// between each consecutive pair, printed as each is known. A refused stage is reported and
// the plan goes on; the exit is 1 when any was refused or failed, and 0 otherwise, whatever
// the warnings. The kind absent, no open proposed change on the branch, or the
// branch gone refuses the whole plan with nothing compiled, exit 1; an Infrahub that
// cannot be reached while finding it is operation.failed, exit 2.
func runStagePlan(ctx context.Context, opts *options, f *stageFlags) error {
	const op = findings.OpStagePlan
	if !f.branchGiven && f.branch == "" {
		return fail(op, nil, "--branch is required")
	}
	if refused := branchGuard(op, f.branch); refused != nil {
		return refused
	}
	// The scope every stage is resolved and read under (017), after --branch's guards and
	// before the packages load.
	scope, err := scopeOf(opts, op, nil, f.scope, f.scopeGiven)
	if err != nil {
		return err
	}
	subject := &findings.Subject{Scope: scope}
	if ctx == nil {
		ctx = context.Background()
	}
	planned, err := planStages(ctx, opts, op, subject, f.branch, scope,
		func(pc stages.ProposedChange, n int) { opts.note("%s", heading(pc, true, n, scope)) },
		func(st stages.PlanStage) { printPlanned(opts, st) },
		func(p step.Pair) { opts.note("%s", p.Text()) })
	if err != nil {
		return err
	}
	res := planned.res
	doc := findings.NewDocument(op, subject, res.Findings)
	if doc.Plan, err = res.Block(); err != nil {
		return fail(op, subject, "%v", err)
	}
	return &result{doc: doc}
}

// plannedStages is a proposed change's stages as stage plan plans them: the plan, the
// packages it compiled with, the state root its bundles are filed under, the reader it read
// through, the scope it read under, and the server's clock when it began.
type plannedStages struct {
	res    *stages.PlanResult
	reg    *psp.Registry
	paths  lab.Paths
	reader stages.Reader
	scope  string
	now    time.Time
}

// planStages is stage plan's plan of branch's open proposed change under scope, which twin
// rehearse plans with too (015), so a rehearsal's stages are the plan's by construction: the
// packages, loaded before anything is dialled as a create loads them for its read; the state
// root; the stage reader; then stages.Plan, each bundle and its CTM filed as the dry run
// files them, with onChange, onStage and onStep as stages.Plan calls them. A failure is the
// document the command ends with, subject its subject.
func planStages(ctx context.Context, opts *options, op string, subject *findings.Subject, branch, scope string,
	onChange func(stages.ProposedChange, int), onStage func(stages.PlanStage), onStep func(step.Pair)) (plannedStages, error) {
	reg, err := psp.Load(opts.pspDir)
	if err != nil {
		return plannedStages{}, loadFailureAt(op, subject, findings.StepRead, err)
	}
	paths, err := opts.paths()
	if err != nil {
		return plannedStages{}, failAt(op, subject, findings.StepCompile, op, "%v", err)
	}
	reader, err := intent.StageReaderFromEnv()
	if err != nil {
		return plannedStages{}, failAt(op, subject, findings.StepResolve, op, "%v", err)
	}

	// Each bundle is filed as the dry run files it.
	file := func(ctx context.Context, files map[string][]byte, id string) (findings.List, error) {
		_, list, err := fileCompiled(ctx, paths.Bundles, files, id)
		return list, err
	}
	now := time.Now().UTC()
	res, err := stages.Plan(ctx, reader, newIntentStamper(), branch, scope, reg, stages.NewPipeline(file), now, onChange, onStage, onStep)
	if err != nil {
		return plannedStages{}, failAt(op, subject, findings.StepResolve, op, "%v", err)
	}
	return plannedStages{res: res, reg: reg, paths: paths, reader: reader, scope: scope, now: now}, nil
}

// printPlanned prints one planned stage: its resolution, bundle_id and what its read holds
// when it compiled, and otherwise one line naming the first rejection's rule; then its
// findings under it, indented, each in the document's text-line shape. The document's
// stderr rendering is unchanged, so text prints each twice: under its stage, where a
// finding naming a device or an interface says whose it is, and with the rest.
func printPlanned(opts *options, st stages.PlanStage) {
	if st.Status != stages.PlanCompiled {
		why := st.Status
		if st.Rule != "" {
			why = fmt.Sprintf("%s (%s)", st.Status, st.Rule)
		}
		opts.note("%s: %s", st.Ref, why)
	} else {
		opts.note("%s: %s", st.Ref, st.Resolved.Block().Resolution())
		opts.note("  bundle_id %s", st.Bundle.ID)
		opts.note("  read: %s", readCounts(st.Read.Counts, st.Read.Packages, st.Read.Lossy))
	}
	for _, line := range st.Findings.TextLines() {
		opts.note("  %s", line)
	}
}
