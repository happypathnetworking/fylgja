package server

import (
	"context"
	"fmt"
	"time"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/step"
	"github.com/happypathnetworking/fylgja/internal/waypoint"
)

type waypointFlags struct {
	series string
	// seriesGiven is whether --series was given at all, apart from its value: an explicit
	// empty one is a series refused, not one left out (M4's --interval= precedent).
	seriesGiven bool
}

// seriesGuard refuses a --series that is not a series as the reference syntax names one,
// before any connection: waypoint.ref.invalid, exit 2, at step start, in the shape a
// --waypoint's refusal takes (contracts/cli.md).
func seriesGuard(op, series string) error {
	err := waypoint.CheckSeries(series)
	if err == nil {
		return nil
	}
	doc := findings.RuleErrorDocument(op, nil, findings.RuleWaypointRefInvalid, series, err.Error())
	doc.Findings[0].Step = findings.StepStart
	return &result{doc: doc}
}

// The noun waypoint (M10): the waypoints the operator
// wrote in Infrahub, listed and planned. Both verbs dial Infrahub and nothing else: no
// workflow service, no worker, no containerlab, no host budget.

// runWaypointList lists the waypoints. The kind absent from the default
// branch is waypoint.kind.absent, exit 1; an Infrahub that cannot be reached or refuses the
// credential is operation.failed, exit 2, at step resolve, as a create's resolution
// reports it. The two warnings leave the exit 0.
func runWaypointList(ctx context.Context, opts *options, f *waypointFlags) error {
	const op = findings.OpWaypointList
	if f.seriesGiven {
		if refused := seriesGuard(op, f.series); refused != nil {
			return refused
		}
	}
	if ctx == nil {
		ctx = context.Background()
	}
	reader, err := intent.WaypointReaderFromEnv()
	if err != nil {
		return failAt(op, nil, findings.StepResolve, op, "%v", err)
	}
	res, list, err := waypoint.List(ctx, reader, f.series, hostRecord(opts))
	if err != nil {
		return failAt(op, nil, findings.StepResolve, op, "%v", err)
	}
	doc := findings.NewDocument(op, nil, list)
	if list.Rejected() {
		return &result{doc: doc}
	}
	printList(opts, res)
	doc.Waypoints = res.Block()
	return &result{doc: doc}
}

// hostRecord is twin.json under the state root, or nil when it is absent or cannot be
// read: the host is twin show's to report, and the list says nothing of it but the mark.
// The record carries its state and its last step, so the mark can say a twin is diverged
// and which waypoint it was stepping towards.
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

// printList prints the listing (contracts/cli.md): a heading per series, then one line per
// waypoint with its reference and branch padded so the ats line up within the series, the
// description quoted, and the twin's row marked; beside a diverged record the mark says
// which waypoint the failed step was going to.
func printList(opts *options, res waypoint.ListResult) {
	twinMark := "  ← twin"
	if r := res.Record; r != nil && r.Towards != nil {
		twinMark = fmt.Sprintf("  ← twin (diverged towards %s/%d)", r.Towards.Series, r.Towards.Sequence)
	}
	if len(res.Rows) == 0 {
		if res.Series != "" {
			opts.note("series %s: no waypoints", res.Series)
		} else {
			opts.note("no waypoints")
		}
		return
	}
	for start := 0; start < len(res.Rows); {
		end := start
		for end < len(res.Rows) && res.Rows[end].Ref.Series == res.Rows[start].Ref.Series {
			end++
		}
		rows := res.Rows[start:end]
		refWidth, branchWidth := 0, 0
		for _, r := range rows {
			refWidth = max(refWidth, len(r.Ref.String()))
			branchWidth = max(branchWidth, len(r.Branch))
		}
		opts.note("series %s (%s)", rows[0].Ref.Series, plural(len(rows), "waypoint"))
		for _, r := range rows {
			mark := ""
			if r.Twin {
				mark = twinMark
			}
			opts.note("  %-*s  branch %-*s  at %s (%s)  %q%s", refWidth, r.Ref, branchWidth, r.Branch, r.At, r.AtSource,
				r.Description, mark)
		}
		start = end
	}
}

// runWaypointPlan plans one series: each waypoint read, compiled and filed
// in the store on the stage pipeline, and the step between each consecutive pair, printed as
// each is known. A refused waypoint is reported and the plan goes on; the exit is 1 when any
// was refused or failed, and 0 otherwise, whatever the warnings. The series unknown or the
// kind absent refuses the whole plan with nothing compiled, exit 1; an Infrahub that cannot
// be reached while listing is operation.failed, exit 2.
func runWaypointPlan(ctx context.Context, opts *options, f *waypointFlags) error {
	const op = findings.OpWaypointPlan
	if !f.seriesGiven {
		return fail(op, nil, "--series is required")
	}
	if refused := seriesGuard(op, f.series); refused != nil {
		return refused
	}
	// Packages are loaded before anything is dialled, as a create loads them for its read.
	reg, err := psp.Load(opts.pspDir)
	if err != nil {
		return loadFailureAt(op, nil, findings.StepRead, err)
	}
	paths, err := opts.paths()
	if err != nil {
		return failAt(op, nil, findings.StepCompile, op, "%v", err)
	}
	if ctx == nil {
		ctx = context.Background()
	}
	reader, err := intent.WaypointReaderFromEnv()
	if err != nil {
		return failAt(op, nil, findings.StepResolve, op, "%v", err)
	}

	// Each bundle and its CTM are filed as the dry run files them.
	file := func(ctx context.Context, files map[string][]byte, id string, snapshot *ctm.CTM) (findings.List, error) {
		_, list, err := fileCompiled(ctx, paths.Bundles, files, id, snapshot)
		return list, err
	}
	res, err := waypoint.Plan(ctx, reader, f.series, reg, waypoint.NewStages(file), time.Now().UTC(),
		func(n int) { opts.note("series %s (%s)", f.series, plural(n, "waypoint")) },
		func(w waypoint.PlanWaypoint) { printPlanned(opts, w) },
		func(p step.Pair) { opts.note("%s", p.Text()) })
	if err != nil {
		return failAt(op, nil, findings.StepResolve, op, "%v", err)
	}
	doc := findings.NewDocument(op, nil, res.Findings)
	if doc.Plan, err = res.Block(); err != nil {
		return fail(op, nil, "%v", err)
	}
	return &result{doc: doc}
}

// printPlanned prints one planned waypoint (contracts/cli.md): its resolution, bundle_id and
// what its read holds when it compiled, and otherwise one line naming the first rejection's
// rule; then its findings under it, indented, each in the document's text-line shape. The
// document's stderr rendering is unchanged, so text prints each twice: under its waypoint,
// where a finding naming a device or an interface says whose it is, and with the rest.
func printPlanned(opts *options, w waypoint.PlanWaypoint) {
	if w.Status != waypoint.PlanCompiled {
		why := string(w.Status)
		if w.Rule != "" {
			why = fmt.Sprintf("%s (%s)", w.Status, w.Rule)
		}
		opts.note("%s: %s", w.Ref, why)
	} else {
		opts.note("%s: %s", w.Ref, w.Resolved.Block().Resolution())
		opts.note("  bundle_id %s", w.Bundle.ID)
		opts.note("  read: %s", readCounts(w.Read.Counts, w.Read.Packages, w.Read.Lossy))
	}
	for _, line := range w.Findings.TextLines() {
		opts.note("  %s", line)
	}
}
