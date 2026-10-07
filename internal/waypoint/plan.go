package waypoint

import (
	"context"
	"encoding/json"
	"fmt"
	"sort"
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

// Stages is the pipeline a plan runs each waypoint through: the stage read, the stage
// compile, and the filing of the bundle and its CTM in the store. They are function values
// so tier 1 can fake what lies under them; the product's are stage.Read, stage.Compile and
// the dry run's filing, one code path with `intent read`, `twin compile` and a create
// (D-011).
type Stages struct {
	Read    func(ctx context.Context, branch, at string, reg *psp.Registry, observedAt string) (*ctm.CTM, findings.List, error)
	Compile func(c *ctm.CTM, reg *psp.Registry) (files map[string][]byte, id string, list findings.List)
	// File files a compiled bundle and the CTM it was compiled from. A refusal is its
	// findings (bundle.id.mismatch); an error is a filing that could not run.
	File func(ctx context.Context, files map[string][]byte, id string, snapshot *ctm.CTM) (findings.List, error)
}

// NewStages is the product's pipeline: the stage pipelines, and file, the command's filing
// in the store under its state root.
func NewStages(file func(ctx context.Context, files map[string][]byte, id string, snapshot *ctm.CTM) (findings.List, error)) Stages {
	return Stages{Read: stage.Read, Compile: stage.Compile, File: file}
}

// How far one planned waypoint got.
const (
	// PlanCompiled: resolved, read, compiled and filed.
	PlanCompiled = "compiled"
	// PlanRefused: refused at resolution, read, compile or filing, under a rule of its own.
	PlanRefused = "refused"
	// PlanFailed: its read, compile or filing could not run (operation.failed).
	PlanFailed = "failed"
)

// PlanWaypoint is one waypoint of a plan, as far as it got.
type PlanWaypoint struct {
	Ref         Ref
	Description string
	// Resolved is set once the waypoint resolved.
	Resolved *Resolved
	// Read is set once its read returned intent: what the read holds, as `intent read`'s
	// summary counts it.
	Read *ReadSummary
	// Bundle is set once it compiled and was filed.
	Bundle *step.Bundle
	// ObservedAt is when its read began, set once the read ran: twin step's record takes
	// it as its own once the step moves the twin to this waypoint.
	ObservedAt string
	// Findings are this waypoint's, each at its step, and a time.reversed warning naming it.
	Findings findings.List
	// Status is PlanCompiled, PlanRefused or PlanFailed; Rule, when it is not compiled, is
	// the first rejection's rule, which the text prints: refused (artifact.not_ready).
	Status string
	Rule   string
}

// ReadSummary is what one waypoint's read holds.
type ReadSummary struct {
	Counts   intent.Counts
	Packages []intent.PackageCount
	Lossy    compiler.SurveyCounts
}

// PlanResult is what `waypoint plan` reports.
type PlanResult struct {
	Series string
	// Waypoints are in sequence order; none when the plan was refused before any.
	Waypoints []PlanWaypoint
	// Steps are one fewer than the waypoints, in order.
	Steps []step.Pair
	// Findings are the document's: a refusal of the whole plan, or every waypoint's
	// findings in sequence order.
	Findings findings.List
}

// Plan lists a series and runs each of its waypoints, in sequence order, through the stage
// pipeline, then diffs each consecutive pair. Nothing but
// Infrahub and the store is reached: no workflow service, worker, containerlab or host.
//
// The kind absent is waypoint.kind.absent and a series with no waypoint waypoint.unknown,
// naming the series that exist; either ends the plan before anything is read. An Infrahub
// that cannot be reached or refuses the credential while listing returns its error.
// Otherwise every waypoint is planned whatever the others did:
//
//  1. resolved from the one listing, findings at resolve;
//  2. read with an observed_at of its own, findings at read; a read that cannot run, a
//     deleted branch among them, is operation.failed naming the waypoint;
//  3. compiled, findings at compile;
//  4. filed with its CTM, as the dry run files them.
//
// onSeries is called once the series is known to hold waypoints, with how many it holds
// (each sequence once), before any is read; onWaypoint as each waypoint finishes; and onStep
// as each step is known, which is once its later waypoint has finished and before
// onWaypoint is called for it: the output reads each step between the two waypoints it
// joins. A step whose side did not compile is not computed, naming it. now is the CLI's
// clock, for the future rule alone.
func Plan(ctx context.Context, r Reader, series string, reg *psp.Registry, stages Stages, now time.Time,
	onSeries func(waypoints int), onWaypoint func(PlanWaypoint), onStep func(step.Pair)) (*PlanResult, error) {
	all, list, err := ListAll(ctx, r)
	if err != nil {
		return nil, err
	}
	res := &PlanResult{Series: series}
	if list != nil {
		res.Findings = list
		return res, nil
	}
	var inSeries []intent.Waypoint
	for _, w := range all {
		if w.Series == series {
			inSeries = append(inSeries, w)
		}
	}
	if len(inSeries) == 0 {
		res.Findings = unknownSeries(all, series)
		return res, nil
	}

	// waypoint.time.reversed as the listing raises it, filed with the later waypoint.
	rows := make([]Resolved, len(inSeries))
	for i, w := range inSeries {
		rows[i] = resolvedRow(w)
	}
	warnings := map[string]findings.List{}
	for _, f := range reversed(rows) {
		warnings[f.Object] = append(warnings[f.Object], f)
	}

	refs := sequencesOf(inSeries)
	if onSeries != nil {
		onSeries(len(refs))
	}
	for _, ref := range refs {
		w := Build(ctx, all, ref, reg, stages, now)
		w.Findings = append(w.Findings, warnings[ref.String()]...)
		if n := len(res.Waypoints); n > 0 {
			pair, err := pairOf(res.Waypoints[n-1], w)
			if err != nil {
				return nil, err
			}
			res.Steps = append(res.Steps, pair)
			if onStep != nil {
				onStep(pair)
			}
		}
		res.Waypoints = append(res.Waypoints, w)
		res.Findings = append(res.Findings, w.Findings...)
		if onWaypoint != nil {
			onWaypoint(w)
		}
	}
	return res, nil
}

// Build runs one waypoint as far as it goes: resolved from the listing all, read with an
// observed_at of its own, compiled, and filed with its CTM, each finding at its step. The
// plan builds each waypoint of a series with it, and twin step builds its target with it,
// so the target's bundle_id is the one waypoint plan prints for that waypoint, by
// construction (D-011).
func Build(ctx context.Context, all []intent.Waypoint, ref Ref, reg *psp.Registry, stages Stages, now time.Time) PlanWaypoint {
	w := PlanWaypoint{Ref: ref, Description: descriptionOf(all, ref)}
	stop := func(list findings.List) PlanWaypoint {
		w.Findings = append(w.Findings, list...)
		w.Status = PlanRefused
		for _, f := range w.Findings {
			if f.Severity == findings.Rejection {
				w.Rule = f.Rule
				if f.Rule == findings.RuleOperationFailed {
					w.Status = PlanFailed
				}
				break
			}
		}
		return w
	}
	failed := func(step string, err error) PlanWaypoint {
		var list findings.List
		list.AddStep(findings.Rejection, step, findings.RuleOperationFailed, ref.String(), err.Error())
		return stop(list)
	}

	resolved, list := ResolveFrom(all, ref, now)
	if list.Rejected() {
		return stop(list)
	}
	w.Resolved = &resolved

	// Captured before the read's first request, so observed_at is never later than
	// anything the read could have seen. stage.Read bounds the read by
	// stage.ReadTimeout.
	observedAt := time.Now().UTC().Format(stage.ObservedAtFormat)
	w.ObservedAt = observedAt
	snapshot, list, err := stages.Read(ctx, resolved.Branch, resolved.At, reg, observedAt)
	if err != nil {
		return failed(findings.StepRead, err)
	}
	list = list.AtStep(findings.StepRead)
	if snapshot == nil {
		return stop(list)
	}
	w.Findings = append(w.Findings, list...)
	w.Read = &ReadSummary{Counts: intent.Summarize(snapshot), Packages: intent.DevicesByPackage(snapshot, reg),
		Lossy: compiler.Survey(snapshot, reg)}

	files, id, compiled := stages.Compile(snapshot, reg)
	compiled = compiled.AtStep(findings.StepCompile)
	if compiled.Rejected() {
		return stop(compiled)
	}
	w.Findings = append(w.Findings, compiled...)

	filed, err := stages.File(ctx, files, id, snapshot)
	if err != nil {
		return failed(findings.StepCompile, err)
	}
	if filed.Rejected() {
		return stop(filed)
	}
	w.Findings = append(w.Findings, filed...)
	w.Bundle = &step.Bundle{ID: id, Files: files}
	w.Status = PlanCompiled
	return w
}

// pairOf is the step between two consecutive waypoints, or why none was computed.
func pairOf(a, b PlanWaypoint) (step.Pair, error) {
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
	for _, w := range []PlanWaypoint{a, b} {
		if w.Bundle == nil {
			refused = append(refused, w.Ref.String())
		}
	}
	why := refused[0] + " was refused"
	if len(refused) == 2 {
		why = strings.Join(refused, " and ") + " were refused"
	}
	return step.NotComputed(from, to, bundleID(a), bundleID(b), why), nil
}

func bundleID(w PlanWaypoint) string {
	if w.Bundle == nil {
		return ""
	}
	return w.Bundle.ID
}

// sequencesOf is each sequence of one series' waypoints once, ascending. A sequence two
// objects hold is planned once, and its resolution refuses it as waypoint.duplicate.
func sequencesOf(inSeries []intent.Waypoint) []Ref {
	seen := map[int]bool{}
	var refs []Ref
	for _, w := range inSeries {
		if !seen[w.Sequence] {
			seen[w.Sequence] = true
			refs = append(refs, Ref{Series: w.Series, Sequence: w.Sequence})
		}
	}
	sort.Slice(refs, func(i, j int) bool { return refs[i].Sequence < refs[j].Sequence })
	return refs
}

// descriptionOf is the description of the first object holding ref, in listing order.
func descriptionOf(all []intent.Waypoint, ref Ref) string {
	for _, w := range all {
		if w.Series == ref.Series && w.Sequence == ref.Sequence {
			return w.Description
		}
	}
	return ""
}

// Block is the result as waypoint plan's document carries it, or nil for a plan refused
// before any waypoint (the contract's plan block holds at least one).
func (p *PlanResult) Block() (*findings.PlanBlock, error) {
	if len(p.Waypoints) == 0 {
		return nil, nil
	}
	b := &findings.PlanBlock{Series: p.Series}
	for _, w := range p.Waypoints {
		b.Waypoints = append(b.Waypoints, w.Block())
	}
	for _, s := range p.Steps {
		raw, err := json.Marshal(s)
		if err != nil {
			return nil, err
		}
		b.Steps = append(b.Steps, raw)
	}
	return b, nil
}

// Block is one waypoint as the plan block carries it.
func (w PlanWaypoint) Block() findings.PlanWaypoint {
	out := findings.PlanWaypoint{Series: w.Ref.Series, Sequence: w.Ref.Sequence, Description: w.Description,
		Findings: w.Findings}
	if r := w.Resolved; r != nil {
		out.Branch, out.At, out.AtSource = r.Branch, r.At, r.AtSource
	}
	if w.Bundle != nil {
		id := w.Bundle.ID
		out.BundleID = &id
	}
	if s := w.Read; s != nil {
		out.Read = &findings.ReadCounts{Devices: s.Counts.Devices, Interfaces: s.Counts.Interfaces, Links: s.Counts.Links,
			Artifacts: s.Counts.Artifacts, LossyMappings: s.Lossy.LossyMappings, SharedPorts: s.Lossy.SharedPorts}
	}
	return out
}
