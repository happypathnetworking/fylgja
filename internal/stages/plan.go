package stages

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/stage"
	"github.com/happypathnetworking/fylgja/internal/step"
)

// Pipeline is what a plan runs each stage through: the stage read, the stage compile, and
// the filing of the bundle and its CTM in the store. They are function values so tier 1
// can fake what lies under them; the product's are stage.Read, stage.Compile and the dry
// run's filing, one code path with `intent read`, `twin compile` and a create (D-011).
type Pipeline struct {
	Read    func(ctx context.Context, branch, at, scope string, reg *psp.Registry, observedAt string) (*ctm.CTM, findings.List, error)
	Compile func(c *ctm.CTM, reg *psp.Registry) (files map[string][]byte, id string, list findings.List)
	// File files a compiled bundle and the CTM it was compiled from. A refusal is its
	// findings (bundle.id.mismatch); an error is a filing that could not run.
	File func(ctx context.Context, files map[string][]byte, id string, snapshot *ctm.CTM) (findings.List, error)
}

// NewPipeline is the product's pipeline: the stage pipelines, and file, the command's
// filing in the store under its state root.
func NewPipeline(file func(ctx context.Context, files map[string][]byte, id string, snapshot *ctm.CTM) (findings.List, error)) Pipeline {
	return Pipeline{Read: stage.Read, Compile: stage.Compile, File: file}
}

// How far one planned stage got.
const (
	// PlanCompiled: resolved, read, compiled and filed.
	PlanCompiled = "compiled"
	// PlanRefused: refused at resolution, read, compile or filing, under a rule of its own.
	PlanRefused = "refused"
	// PlanFailed: its resolution, read, compile or filing could not run (operation.failed).
	PlanFailed = "failed"
)

// PlanStage is one stage of a plan, as far as it got.
type PlanStage struct {
	Ref   Ref
	Label string
	// Description and AtSource are the stage's as the order holds it, known whether or
	// not it resolves.
	Description string
	AtSource    string
	// Resolved is set once the stage resolved: its branch and at.
	Resolved *Resolved
	// Read is set once its read returned intent: what the read holds, as `intent read`'s
	// summary counts it.
	Read *ReadSummary
	// Bundle is set once it compiled and was filed.
	Bundle *step.Bundle
	// ObservedAt is when its read began, set once the read ran: twin step's record takes
	// it as its own once the step moves the twin to this stage.
	ObservedAt string
	// Findings are this stage's, each at its step.
	Findings findings.List
	// Status is PlanCompiled, PlanRefused or PlanFailed; Rule, when it is not compiled, is
	// the first rejection's rule, which the text prints: refused (stage.artifact.stale).
	Status string
	Rule   string
}

// BundleID is the stage's bundle_id, "" when it did not compile.
func (p PlanStage) BundleID() string {
	if p.Bundle == nil {
		return ""
	}
	return p.Bundle.ID
}

// ReadSummary is what one stage's read holds.
type ReadSummary struct {
	Counts   intent.Counts
	Packages []intent.PackageCount
	Lossy    compiler.SurveyCounts
}

// PlanResult is what `stage plan` reports.
type PlanResult struct {
	// Branch is the source branch asked for.
	Branch string
	// ProposedChange is the one planned; nil when the plan was refused before it was found.
	ProposedChange *ProposedChange
	// Stages are in order; none when the plan was refused whole.
	Stages []PlanStage
	// Steps are one fewer than the stages, in order.
	Steps []step.Pair
	// Findings are the document's: a refusal of the whole plan, or every stage's findings
	// in order.
	Findings findings.List
}

// Plan finds the open proposed change whose source branch is branch and runs each of its
// stages, in order, through the stage pipeline, then diffs each consecutive pair. Nothing
// but Infrahub and the store is reached: no workflow service, worker, containerlab or host.
//
// The kind absent, no open proposed change on the branch, or the branch gone is a
// refusal of the whole plan before anything is read. An Infrahub that cannot be reached
// or refuses the credential while finding it returns its error. Otherwise every stage is
// planned whatever the others did:
//
//  1. resolved (steps 4–8, and the main.moved warning with the branch point, refused or
//     not), findings at resolve;
//  2. read with an observed_at of its own, findings at read; a read that cannot run is
//     operation.failed naming the stage;
//  3. compiled, findings at compile;
//  4. filed with its CTM, as the dry run files them.
//
// onChange is called once the proposed change is found, with how many stages it has;
// onStage as each stage finishes; and onStep as each step is known, which is once its
// later stage has finished and before onStage is called for it: the output reads each
// step between the two stages it joins. A step whose side did not compile is not
// computed, naming it. now is the server's clock, for the future rule alone. Every stage
// is resolved and read under scope, tag:<name> (017).
func Plan(ctx context.Context, r Reader, s Stamper, branch, scope string, reg *psp.Registry, p Pipeline, now time.Time,
	onChange func(pc ProposedChange, stages int), onStage func(PlanStage), onStep func(step.Pair)) (*PlanResult, error) {
	ch, list, err := Find(ctx, r, s, branch, scope)
	if err != nil {
		return nil, err
	}
	res := &PlanResult{Branch: branch}
	if list != nil {
		res.Findings = list
		return res, nil
	}
	pc := ch.ProposedChange
	res.ProposedChange = &pc
	labels := ch.Labels()
	if onChange != nil {
		onChange(pc, len(labels))
	}
	for i, label := range labels {
		// main.moved concerns the branch point, which is always first: filed with it once,
		// whatever its resolution, since a plan applies every step to every stage.
		moved := movedNever
		if i == 0 {
			moved = movedAlways
		}
		st := build(ctx, r, s, reg, ch, Ref{Branch: branch, Label: label}, p, now, moved)
		if n := len(res.Stages); n > 0 {
			pair, err := pairOf(res.Stages[n-1], st)
			if err != nil {
				return nil, err
			}
			res.Steps = append(res.Steps, pair)
			if onStep != nil {
				onStep(pair)
			}
		}
		res.Stages = append(res.Stages, st)
		res.Findings = append(res.Findings, st.Findings...)
		if onStage != nil {
			onStage(st)
		}
	}
	return res, nil
}

// Build runs one stage of a proposed change already found as far as it goes: resolved
// (steps 4–9), read with an observed_at of its own, compiled, and filed with its CTM,
// each finding at its step. twin step builds its target with it, and the plan builds each
// stage the same way, so the target's bundle_id is the one stage plan prints for that
// stage, by construction (D-011).
func Build(ctx context.Context, r Reader, s Stamper, reg *psp.Registry, ch *Change, ref Ref, p Pipeline, now time.Time) PlanStage {
	return build(ctx, r, s, reg, ch, ref, p, now, movedResolved)
}

// movedWhen is when build files step 9's warning, stage.main.moved.
type movedWhen int

const (
	// movedNever: a plan's stages after the first, the warning being the branch point's.
	movedNever movedWhen = iota
	// movedResolved: twin step's target, as a create resolves its stage, the first
	// refusal ending the resolution before step 9.
	movedResolved
	// movedAlways: a plan's branch point, refused or not.
	movedAlways
)

// build is Build, with step 9's warning as moved says.
func build(ctx context.Context, r Reader, s Stamper, reg *psp.Registry, ch *Change, ref Ref, p Pipeline, now time.Time,
	moved movedWhen) PlanStage {
	ps := PlanStage{Ref: ref, Label: ref.Label}
	if st, ok := ch.first(ref.Label); ok {
		ps.Description, ps.AtSource = st.Description, st.AtSource
	}
	stop := func(list findings.List) PlanStage {
		ps.Findings = append(ps.Findings, list...)
		ps.Status = PlanRefused
		for _, f := range ps.Findings {
			if f.Severity == findings.Rejection {
				ps.Rule = f.Rule
				if f.Rule == findings.RuleOperationFailed {
					ps.Status = PlanFailed
				}
				break
			}
		}
		return ps
	}
	failed := func(step string, err error) PlanStage {
		var list findings.List
		list.AddStep(findings.Rejection, step, findings.RuleOperationFailed, ref.String(), err.Error())
		return stop(list)
	}

	resolved, list, err := resolve(ctx, r, s, reg, ch, ref, now)
	if err != nil {
		return failed(findings.StepResolve, err)
	}
	if moved == movedAlways || moved == movedResolved && !list.Rejected() {
		warning, err := ch.MainMoved(ctx, s)
		if err != nil {
			return failed(findings.StepResolve, err)
		}
		// A plan's branch point reads the destination's stamps twice, for its staleness
		// and here: a destination whose schema does not conform is refused once.
		list = append(list, unfiled(warning, list)...)
	}
	if list.Rejected() {
		return stop(list)
	}
	ps.Findings = append(ps.Findings, list...)
	ps.Resolved = &resolved

	// Captured before the read's first request, so observed_at is never later than
	// anything the read could have seen. stage.Read bounds the read by
	// stage.ReadTimeout.
	observedAt := time.Now().UTC().Format(stage.ObservedAtFormat)
	ps.ObservedAt = observedAt
	snapshot, list, err := p.Read(ctx, resolved.Branch, resolved.At, ch.Scope, reg, observedAt)
	if err != nil {
		return failed(findings.StepRead, err)
	}
	list = list.AtStep(findings.StepRead)
	if snapshot == nil {
		return stop(list)
	}
	ps.Findings = append(ps.Findings, list...)
	ps.Read = &ReadSummary{Counts: intent.Summarize(snapshot), Packages: intent.DevicesByPackage(snapshot, reg),
		Lossy: compiler.Survey(snapshot, reg)}

	files, id, compiled := p.Compile(snapshot, reg)
	compiled = compiled.AtStep(findings.StepCompile)
	if compiled.Rejected() {
		return stop(compiled)
	}
	ps.Findings = append(ps.Findings, compiled...)

	filed, err := p.File(ctx, files, id, snapshot)
	if err != nil {
		return failed(findings.StepCompile, err)
	}
	if filed.Rejected() {
		return stop(filed)
	}
	ps.Findings = append(ps.Findings, filed...)
	ps.Bundle = &step.Bundle{ID: id, Files: files}
	ps.Status = PlanCompiled
	return ps
}

// pairOf is the step between two consecutive stages, or why none was computed.
func pairOf(a, b PlanStage) (step.Pair, error) {
	from, to := a.Ref.String(), b.Ref.String()
	if a.Bundle != nil && b.Bundle != nil {
		s, err := step.Diff(*a.Bundle, *b.Bundle)
		if err != nil {
			// Two bundles the compile just produced always read; one that does not is a
			// defect, not a finding.
			return step.Pair{}, fmt.Errorf("the step %s → %s: %w", from, to, err)
		}
		return step.Between(from, to, s), nil
	}
	var refused []string
	for _, st := range []PlanStage{a, b} {
		if st.Bundle == nil {
			refused = append(refused, st.Ref.String())
		}
	}
	why := refused[0] + " was refused"
	if len(refused) == 2 {
		why = strings.Join(refused, " and ") + " were refused"
	}
	return step.NotComputed(from, to, a.BundleID(), b.BundleID(), why), nil
}
