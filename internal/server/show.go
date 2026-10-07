package server

import (
	"context"
	"errors"
	"fmt"
	"maps"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
)

// serviceReads is what twin show learned from the workflow service.
type serviceReads struct {
	following *provision.FollowingState
	lastCheck *provision.CheckRecord
	inFlight  []provision.RunInFlight
}

// runShow reports the twin. The host is inspected in this process, as the dry
// run inspects it, through M3's InspectHost; a host that cannot be inspected is the only
// failure. The service is asked best-effort, under the server's ServiceBudget.
func runShow(ctx context.Context, opts *options) error {
	const op = findings.OpTwinShow
	if ctx == nil {
		ctx = context.Background()
	}
	cannotInspect := func(err error) error {
		return &result{doc: findings.RuleErrorDocument(op, nil, findings.RuleOperationFailed, "lab "+wire.LabName,
			fmt.Sprintf("inspecting the host: %v", err))}
	}
	paths, err := opts.paths()
	if err != nil {
		return cannotInspect(err)
	}
	acts := &lab.Activities{
		Clab:  &lab.Clab{Runner: opts.c.s.Runner, Log: opts.c.log},
		Paths: paths,
	}
	host, err := acts.InspectHost(ctx)
	if err != nil {
		return cannotInspect(err)
	}

	var list findings.List
	reads, err := readService(ctx, opts)
	unreachableAt := ""
	if err != nil {
		var cause error
		unreachableAt, cause = serviceAddress(opts, err)
		list.Add(findings.Warning, findings.RuleShowServiceUnreachable, unreachableAt,
			fmt.Sprintf("workflow service unreachable at %s (%v); whether the twin is following and whether a run is in flight are unknown",
				unreachableAt, cause))
	}

	block, text := decideShow(host, reads, unreachableAt)
	printShow(opts, block, text)

	doc := findings.NewDocument(op, nil, list)
	doc.Show = &block
	return &result{doc: doc}
}

// readService dials the workflow service and makes twin show's three reads, all within the
// server's ServiceBudget. The reads run beside the budget, so a service that never answers
// costs the budget and no more.
func readService(ctx context.Context, opts *options) (serviceReads, error) {
	budget := opts.c.s.ServiceBudget
	ctx, cancel := context.WithTimeout(ctx, budget)
	defer cancel()
	type answer struct {
		reads serviceReads
		err   error
	}
	done := make(chan answer, 1)
	// The reads can outlive the request, past the budget, so they take what they need of
	// the server before they start and read none of its fields afterwards.
	dial, log := opts.c.s.Dial, opts.c.log
	go func() {
		var a answer
		defer func() { done <- a }()
		svc, err := dial(ctx, log)
		if err != nil {
			a.err = err
			return
		}
		defer svc.Close()
		if a.reads.following, a.err = svc.Following(ctx); a.err != nil {
			return
		}
		if a.reads.lastCheck, a.err = svc.LastCheck(ctx, a.reads.following); a.err != nil {
			return
		}
		a.reads.inFlight, a.err = svc.InFlight(ctx)
	}()
	select {
	case a := <-done:
		// A read that failed leaves every read unknown, the ones made before it included:
		// a following reported beside "following: unknown" would contradict it.
		if a.err != nil && ctx.Err() != nil {
			return serviceReads{}, fmt.Errorf("no answer within %s", budget)
		}
		if a.err != nil {
			return serviceReads{}, a.err
		}
		return a.reads, nil
	case <-ctx.Done():
		return serviceReads{}, fmt.Errorf("no answer within %s", budget)
	}
}

// serviceAddress is where the service that did not answer was looked for, and why it did not
// answer, without the address repeated.
func serviceAddress(opts *options, err error) (string, error) {
	var unreachable *provision.UnreachableError
	if errors.As(err, &unreachable) {
		return unreachable.Address, unreachable.Err
	}
	if v, ok := opts.getenv(lab.EnvTemporalAddress); ok && v != "" {
		return v, err
	}
	return provision.DefaultAddress, err
}

// showText is what the text layout says beyond the block's own fields: the kind's line and
// the lines under it.
type showText struct {
	kind    string
	details []string
	// hostHeld is set when a run in flight holds the host: the twin: line then says what the
	// host holds, without M3's phrase or its remedy.
	hostHeld bool
	// step is the record block's line for a record that has stepped, or "".
	step string
}

// decideShow builds the show block and its text from what the host holds and what the
// service said (the kind table). unreachableAt is the service's address when
// it did not answer, and "" when it did.
func decideShow(host lab.HostState, reads serviceReads, unreachableAt string) (findings.ShowBlock, showText) {
	block := findings.ShowBlock{
		Host:    findings.ShowHost{LabPresent: host.Lab.Present, TwinDirPresent: host.TwinDirPresent, Phrase: host.Describe()},
		Service: findings.ShowServiceOK,
	}
	// Containerlab says which nodes run; twin.json says what each was pushed, by node
	// name.
	// A node the record does not name — an orphan's — has no artifact.
	pushed := map[string]*findings.ShowArtifact{}
	pkg := map[string]*string{}
	if host.Twin != nil {
		// A version 4 record names the bundle each node holds, and the artifact shown is
		// that bundle's; a node holding none runs containerlab's baseline and shows
		// none.
		// An earlier record holds nothing by node, and shows each.
		holdsNamed := host.Twin.State != ""
		for _, n := range host.Twin.Nodes {
			if a := n.Artifact; a != nil && (!holdsNamed || n.Holds != nil) {
				pushed[n.Name] = &findings.ShowArtifact{Name: a.Name, Checksum: a.Checksum}
			}
			if id := n.PSP.ID; id != "" {
				pkg[n.Name] = &id
			}
		}
	}
	for _, n := range host.Lab.Nodes {
		block.Host.Nodes = append(block.Host.Nodes, findings.ShowNode{Name: n.Name, Container: n.Container, State: n.State,
			MgmtIPv4: n.MgmtIPv4, PSP: pkg[n.Name], Artifact: pushed[n.Name]})
	}
	reachable := unreachableAt == ""
	if !reachable {
		block.Service = findings.ShowServiceUnreachable
	}

	rec := host.Twin
	if rec != nil {
		block.Record = &findings.ShowRecord{
			Branch: rec.Provenance.Branch, At: rec.Provenance.At, BundleID: rec.BundleID, SchemaHash: rec.Provenance.SchemaHash,
			ContractVersion: rec.Provenance.ContractVersion, ObservedAt: rec.ObservedAt, ObservedAtNote: rec.ObservedAtNote,
			Source: rec.Source, Run: findings.ShowRef{WorkflowID: rec.Run.WorkflowID, RunID: rec.Run.RunID},
			WorkerVersion: rec.ProvisionedBy.Version, RecordedAt: rec.RecordedAt, Nodes: len(rec.Nodes),
		}
		// A version 3 record names the waypoint the twin was created from.
		if w := rec.Waypoint; w != nil {
			block.Record.Waypoint = showWaypoint(w)
		}
		// A version 4 record says whether the twin is ready or diverged, and its last step.
		block.Record.State = rec.State
		block.Record.Step = showStep(rec.Step, waitRecorded(rec))
	}

	var text showText
	if rec != nil && rec.Step != nil {
		text.step = stepLine(rec.Step, waitRecorded(rec))
	}
	following := reads.following
	if following != nil {
		block.Following = &findings.ShowFollowing{Branch: following.Branch, IntervalS: following.IntervalS,
			ScheduleID: provision.FollowScheduleID, NextCheckAt: timeString(following.NextCheckAt), LastCheck: showCheck(reads.lastCheck)}
	}
	block.InFlight = showRuns(reads.inFlight)

	note := func(s string) { block.Notes = append(block.Notes, s) }
	bestEffort := func() {
		if rec.ObservedAt != nil {
			note(fmt.Sprintf("reproducing the twin with --at %s is best-effort", *rec.ObservedAt))
		}
	}
	provisioning := provisionAtHost(block.InFlight)
	switch rebuild := rebuildInFlight(block.InFlight); {
	case rebuild != nil:
		// The host is mid-rebuild: an empty host or a lab without a record is the rebuild's own
		// work, not an orphan, and a create would be refused as run.in_flight.
		// The twin: line still says what the host holds.
		text.hostHeld = true
		if following != nil {
			block.Kind = findings.ShowKindFollowing
			text.kind = fmt.Sprintf("following of branch %s is rebuilding the twin: check %s at step %s",
				following.Branch, rebuild.WorkflowID, rebuild.Step)
			if c := block.Following.LastCheck; c != nil {
				text.details = append(text.details, fmt.Sprintf("last check: %s at %s, %s", c.WorkflowID, checkTime(c), c.Outcome))
			}
			if next := block.Following.NextCheckAt; next != "" {
				text.details = append(text.details, "next check: "+next)
			}
			note(text.kind)
			break
		}
		// Following was stopped under the check, as twin destroy does before cancelling it.
		block.Kind = findings.ShowKindNone
		s := fmt.Sprintf("check %s is rebuilding the twin at step %s; following has stopped", rebuild.WorkflowID, rebuild.Step)
		text.kind = "none; " + s
		note(s)
	case rec == nil && provisioning != nil:
		// An operator's create or provision has reached the host: a lab or twin directory with
		// no twin.json is that run's work, or its cleanup's, not a run cut short, and a destroy
		// would cancel it. No create advice: a create is refused beside it.
		block.Kind = findings.ShowKindNone
		text.hostHeld = true
		s := fmt.Sprintf("run %s %s is at step %s, and the host holds its work", provisioning.WorkflowID, provisioning.RunID, provisioning.Step)
		text.kind = "none; " + s
		note(s)
		if following != nil {
			s := scheduleWithoutTwin(following.Branch)
			note(s)
			text.kind += "; " + s
		} else if c, s := followingStopped(reads.lastCheck); c != nil {
			block.LastCheck = c
			note(s)
			text.kind += "; " + s
		}
	case rec == nil:
		block.Kind = findings.ShowKindNone
		text.kind = "none"
		if block.Host.Phrase == "" {
			note("no twin")
		} else {
			note(block.Host.Phrase + "; fylgja twin destroy clears it")
		}
		if following != nil {
			s := scheduleWithoutTwin(following.Branch)
			// A create replaces the Schedule only on an empty host: beside an orphan or an
			// unreadable twin.json it is refused as host.lab.present or host.twin.present.
			if block.Host.Phrase == "" {
				s += "; fylgja twin create replaces it"
			}
			note(s)
			text.kind += "; " + s
		} else if c, s := followingStopped(reads.lastCheck); c != nil {
			block.LastCheck = c
			s += createStartsAgain
			note(s)
			text.kind += "; " + s
		}
	case !host.Lab.Present:
		// A record whose lab is gone (M3's shape b) is no twin: whether the twin exists is what
		// containerlab says (D-014). A check skips it as nothing to compare against, and a
		// create is refused as host.twin.present, so no create is advised. A rebuild whose
		// destroy removed the lab but not twin.json leaves this host too, and its failed check
		// is reported as it is with no record.
		block.Kind = findings.ShowKindNone
		text.kind = "none"
		note(block.Host.Phrase + "; fylgja twin destroy clears it")
		if following != nil {
			s := scheduleWithoutTwin(following.Branch)
			note(s)
			text.kind += "; " + s
		} else if c, s := followingStopped(reads.lastCheck); c != nil {
			block.LastCheck = c
			s += createStartsAgain
			note(s)
			text.kind += "; " + s
		}
	case rec.State == wire.StateDiverged && rec.Step != nil:
		// A step failed or was cancelled after the host was touched: the twin is up, where
		// the record's top level says, and only a destroy clears it. No create
		// advice beside a lab that exists.
		block.Kind = findings.ShowKindDiverged
		text.kind = divergedKind(rec)
		note(text.kind)
	case rec.Provenance.At != "":
		block.Kind = findings.ShowKindPinned
		text.kind = fmt.Sprintf("pinned at %s; not following", rec.Provenance.At)
		if w := rec.Waypoint; w != nil {
			text.kind = fmt.Sprintf("pinned at %s, waypoint %s/%d; not following", rec.Provenance.At, w.Series, w.Sequence)
			if st := rec.Step; st != nil {
				text.kind = fmt.Sprintf("pinned at %s, waypoint %s/%d (stepped from %s by run %s %s, ended %s); not following",
					rec.Provenance.At, w.Series, w.Sequence, waypointOf(st.From.Waypoint), st.Run.WorkflowID, st.Run.RunID, st.EndedAt)
			}
		}
		note(text.kind)
	case rec.Source == wire.SourceBundle:
		block.Kind = findings.ShowKindFromBundle
		text.kind = "from a bundle; not following"
		note("provisioned from a bundle; read time unknown; not following")
	case reachable && following != nil && following.Branch == rec.Provenance.Branch:
		block.Kind = findings.ShowKindFollowing
		text.kind = fmt.Sprintf("following branch %s, checked every %s", following.Branch, time.Duration(following.IntervalS)*time.Second)
		if c := block.Following.LastCheck; c != nil {
			line := fmt.Sprintf("last check: %s at %s, %s", c.WorkflowID, checkTime(c), c.Outcome)
			if c.Outcome != provision.CheckUnchanged && c.Step != "" {
				line += " at step " + c.Step
			}
			text.details = append(text.details, line)
		}
		if next := block.Following.NextCheckAt; next != "" {
			text.details = append(text.details, "next check: "+next)
		}
		const discards = "a rebuild discards the twin's runtime state"
		text.details = append(text.details, discards)
		note(discards)
		bestEffort()
	case reachable && following != nil:
		block.Kind = findings.ShowKindFrozen
		s := fmt.Sprintf("following of branch %s exists, but the twin is of branch %s: checks skip", following.Branch, rec.Provenance.Branch)
		text.kind = "frozen; " + s
		note(s)
		bestEffort()
	default:
		block.Kind = findings.ShowKindFrozen
		text.kind = "frozen"
		if reachable {
			text.kind += "; not following"
			note("not following")
		}
		bestEffort()
	}
	// A step run that has touched the host is named after the kind, as M4 names a rebuild
	// in flight: the record still says where the twin was.
	if r := stepAtHost(block.InFlight); r != nil && rec != nil {
		text.hostHeld = true
		s := fmt.Sprintf("run %s %s is at step %s", r.WorkflowID, r.RunID, r.Step)
		if towards := stepTowards(reads.inFlight, r.RunID); towards != "" {
			s += ", stepping towards waypoint " + towards
		}
		text.kind += "; " + s
		note(s)
	}
	if !reachable {
		s := fmt.Sprintf("following: unknown (workflow service unreachable at %s)", unreachableAt)
		text.kind += "; " + s
		note(s)
	}
	return block, text
}

// showWaypoint is a recorded waypoint as the show block carries it.
func showWaypoint(w *wire.WaypointRef) *findings.ShowWaypoint {
	if w == nil {
		return nil
	}
	return &findings.ShowWaypoint{Series: w.Series, Sequence: w.Sequence, Description: w.Description, AtSource: w.AtSource}
}

// waitRecorded says whether the record is version 5 or later, whose step block carries the
// step's wait, null until it has run.
func waitRecorded(rec *wire.TwinRecord) bool {
	v, err := strconv.Atoi(rec.TwinVersion)
	return err == nil && v >= 5
}

// showStep is twin.json 4's step block as twin show shows it (contracts/show.schema.json),
// or nil for a record that has not stepped. A version 5 record's adds its wait, or null while
// it has not run.
func showStep(st *wire.StepRecord, waitKnown bool) *findings.ShowStep {
	if st == nil {
		return nil
	}
	side := func(s wire.StepSide) findings.StepSideBlock {
		return findings.StepSideBlock{Waypoint: showWaypoint(s.Waypoint), BundleID: s.BundleID, At: s.At}
	}
	out := &findings.ShowStep{Outcome: st.Outcome, From: side(st.From), To: side(st.To),
		Run: findings.ShowRef{WorkflowID: st.Run.WorkflowID, RunID: st.Run.RunID}, Restarted: lifecycleNodes(st.Reconcile),
		StartedAt: st.StartedAt, EndedAt: st.EndedAt,
		Timings: &findings.StepTimingsBlock{ReconcileS: st.Timings.ReconcileS, Readiness: st.Timings.Readiness,
			Push: st.Timings.Push, WholeS: st.Timings.WholeS}}
	if st.Phase != nil {
		out.Phase = *st.Phase
	}
	for _, p := range st.Pushed {
		out.Pushed = append(out.Pushed, findings.StepPushedEntry{Node: p.Node, Reasons: p.Reasons, Outcome: p.Outcome,
			Rule: p.Rule, TookS: p.TookS})
	}
	out.WaitKnown = waitKnown
	if w := st.Wait; waitKnown && w != nil {
		out.Wait = &findings.ShowWait{Outcome: w.Outcome, BudgetS: w.BudgetS, Reads: w.Reads, AfterS: w.AfterS}
		for _, f := range w.Failing {
			out.Wait.Failing = append(out.Wait.Failing, findings.ShowWaitFailing{Rule: f.Rule, Object: f.Object})
		}
	}
	return out
}

// lifecycleNodes is every node the reconcile restarted, recreated or created, sorted.
func lifecycleNodes(r wire.StepReconcile) []string {
	var out []string
	for _, l := range [][]string{r.Restarted, r.Recreated, r.Added} {
		out = append(out, l...)
	}
	slices.Sort(out)
	return slices.Compact(out)
}

// divergedKind is the kind line of a diverged twin (contracts/cli.md, twin show).
func divergedKind(rec *wire.TwinRecord) string {
	st := rec.Step
	return fmt.Sprintf("diverged towards waypoint %s (bundle %s): run %s %s stopped at phase %s; landed: %s; not landed: %s; "+
		"the twin is at waypoint %s (bundle %s); fylgja twin destroy clears it",
		waypointOf(st.To.Waypoint), shortID(st.To.BundleID), st.Run.WorkflowID, st.Run.RunID, phaseOf(st),
		orNone(landed(st)), orNone(notLanded(st)), waypointOf(rec.Waypoint), shortID(rec.BundleID))
}

// stepLine is the record block's line for a record that has stepped: how the step went, or
// where it stopped (contracts/cli.md, twin show). A version 5 record's line ends with how
// the step's wait ended.
func stepLine(st *wire.StepRecord, waitKnown bool) string {
	line := m11StepLine(st)
	if !waitKnown {
		return line
	}
	return line + "; " + showWaitClause(st.Wait)
}

// showWaitClause is how a version 5 record's wait ended, as its step line names it.
func showWaitClause(w *wire.StepWait) string {
	switch {
	case w == nil:
		return "wait not run"
	case w.Outcome == wire.WaitSettled:
		return "settled after " + seconds(w.AfterS)
	case w.Outcome == wire.WaitExpired:
		return fmt.Sprintf("wait expired after %s (%d failing)", seconds(w.AfterS), len(w.Failing))
	case w.Outcome == wire.WaitCancelled:
		return "wait cancelled after " + seconds(w.AfterS)
	}
	return "wait could not complete"
}

// m11StepLine is M11's step line, unchanged by the wait.
func m11StepLine(st *wire.StepRecord) string {
	if st.Outcome == wire.StepDiverged {
		return fmt.Sprintf("diverged: step run %s %s towards %s (bundle %s) stopped at phase %s, ended %s; landed %s; not landed %s",
			st.Run.WorkflowID, st.Run.RunID, waypointOf(st.To.Waypoint), shortID(st.To.BundleID), phaseOf(st), st.EndedAt,
			orNone(landed(st)), orNone(notLanded(st)))
	}
	line := fmt.Sprintf("stepped from %s by run %s %s, ended %s", waypointOf(st.From.Waypoint), st.Run.WorkflowID,
		st.Run.RunID, st.EndedAt)
	if st.Outcome == wire.StepUnchanged {
		return line + "; unchanged: nothing reconciled, awaited or pushed"
	}
	if t := st.Timings; t.ReconcileS != nil {
		line += "; reconcile " + seconds(*t.ReconcileS)
		var lifecycle []string
		for _, n := range st.Reconcile.Nodes {
			if n.Reported != wire.ReportedLive {
				lifecycle = append(lifecycle, n.Reported+" "+n.Node)
			}
		}
		if len(lifecycle) > 0 {
			line += " (" + strings.Join(lifecycle, ", ") + ")"
		}
	}
	if s := perNode(st.Timings.Readiness); s != "" {
		line += "; readiness " + s
	}
	if s := perNode(st.Timings.Push); s != "" {
		line += "; push " + s
	}
	return line
}

// perNode is each node's seconds, in name order: "e1 1.6s, s1 2.4s".
func perNode(m map[string]float64) string {
	var parts []string
	for _, n := range slices.Sorted(maps.Keys(m)) {
		parts = append(parts, n+" "+seconds(m[n]))
	}
	return strings.Join(parts, ", ")
}

// seconds is a duration in seconds as the step's lines print it: 3.9s.
func seconds(s float64) string { return fmt.Sprintf("%.1fs", s) }

// landed and notLanded name a step's pushes that landed, and those that did not with the
// identifier of the finding that says why: "e1 (push.refused)".
func landed(st *wire.StepRecord) string {
	var out []string
	for _, p := range st.Pushed {
		if p.Outcome == wire.PushLanded {
			out = append(out, p.Node)
		}
	}
	return strings.Join(out, ", ")
}

func notLanded(st *wire.StepRecord) string {
	var out []string
	for _, p := range st.Pushed {
		if p.Outcome != wire.PushLanded {
			out = append(out, withRule(p.Node, p.Rule))
		}
	}
	return strings.Join(out, ", ")
}

func withRule(node, rule string) string {
	if rule == "" {
		return node
	}
	return fmt.Sprintf("%s (%s)", node, rule)
}

func orNone(s string) string {
	if s == "" {
		return "none"
	}
	return s
}

func phaseOf(st *wire.StepRecord) string {
	if st.Phase == nil {
		return "unknown"
	}
	return *st.Phase
}

// waypointOf names a recorded waypoint as series/sequence.
func waypointOf(w *wire.WaypointRef) string {
	if w == nil {
		return "none"
	}
	return fmt.Sprintf("%s/%d", w.Series, w.Sequence)
}

// shortID is a bundle id's first eight characters and an ellipsis, as the step's lines
// print it.
func shortID(id string) string {
	if len(id) > 8 {
		return id[:8] + "…"
	}
	return id
}

// stepAtHost is the step run in flight at a step that has touched the host (its stage
// through its record), or nil.
func stepAtHost(runs []findings.ShowRun) *findings.ShowRun {
	for i, r := range runs {
		if r.WorkflowID != wire.StepWorkflowID {
			continue
		}
		switch r.Step {
		case findings.StepStage, findings.StepReconcile, findings.StepReadiness, findings.StepPush, findings.StepRecord:
			return &runs[i]
		}
	}
	return nil
}

// stepTowards is the waypoint the step run runID is stepping towards, as the service read
// it, or "".
func stepTowards(runs []provision.RunInFlight, runID string) string {
	for _, r := range runs {
		if r.WorkflowID == wire.StepWorkflowID && r.RunID == runID {
			return r.Towards
		}
	}
	return ""
}

// scheduleWithoutTwin is the statement of a Schedule beside a host that holds no twin.
func scheduleWithoutTwin(branch string) string {
	return fmt.Sprintf("following of branch %s exists, and a check finds nothing to compare against", branch)
}

// createStartsAgain ends the "following of branch B stopped: …" sentence, where no run in
// flight holds the host.
const createStartsAgain = "; fylgja twin create starts again"

// followingStopped is a last check that ended rebuild_failed and stopped following, as the show
// block carries it, with that sentence up to createStartsAgain; nil for any other check.
// Only a host with no Schedule asks.
func followingStopped(last *provision.CheckRecord) (*findings.ShowCheck, string) {
	if last == nil || last.Result.Outcome != provision.CheckRebuildFailed || !last.Result.FollowingStopped {
		return nil, ""
	}
	c := showCheck(last)
	cleanup := ""
	if c.Cleanup != nil {
		cleanup = fmt.Sprintf("; cleanup teardown %s, unstage %s", c.Cleanup.Teardown, c.Cleanup.Unstage)
	}
	return c, fmt.Sprintf("following of branch %s stopped: the check %s at %s ended %s at step %s%s",
		last.Result.Branch, last.WorkflowID, timeString(last.ClosedAt), last.Result.Outcome, last.Result.Step, cleanup)
}

// showCheck is a closed check as the show block carries it.
func showCheck(rec *provision.CheckRecord) *findings.ShowCheck {
	if rec == nil {
		return nil
	}
	r := rec.Result
	c := &findings.ShowCheck{
		WorkflowID: rec.WorkflowID, RunID: rec.RunID, ScheduledAt: timeString(rec.ScheduledAt), ClosedAt: timeString(rec.ClosedAt),
		Outcome: r.Outcome, Step: r.Step, TwinBundleID: r.TwinBundleID, BundleID: r.BundleID, Findings: r.Findings,
	}
	var cleanup *provision.CleanupResult
	switch {
	case r.Provision != nil:
		cleanup = &r.Provision.Cleanup
	case r.Destroy != nil:
		cleanup = &r.Destroy.Cleanup
	}
	if cleanup != nil {
		c.Cleanup = &findings.CleanupBlock{Teardown: orSkipped(cleanup.Teardown), Unstage: orSkipped(cleanup.Unstage),
			Removed: cleanup.Removed, Remaining: cleanup.Remaining}
	}
	return c
}

func orSkipped(status string) string {
	if status == "" {
		return provision.CleanupSkipped
	}
	return status
}

// timeString is t in RFC 3339, UTC, or "" for no time.
func timeString(t time.Time) string {
	if t.IsZero() {
		return ""
	}
	return t.UTC().Format(time.RFC3339)
}

// checkTime is when a check closed, as the last check: line says it, or when it was due.
func checkTime(c *findings.ShowCheck) string {
	at := c.ClosedAt
	if at == "" {
		at = c.ScheduledAt
	}
	if t, err := time.Parse(time.RFC3339, at); err == nil {
		return t.Format("15:04:05Z07:00")
	}
	return at
}

// printShow writes twin show's text layout (contracts/cli.md): the host, the record, the kind
// and the runs in flight. A last check that was not unchanged has its findings written on
// stderr, under the check's identifiers, as a run's would be.
func printShow(opts *options, block findings.ShowBlock, text showText) {
	h := block.Host
	if !h.LabPresent && !h.TwinDirPresent {
		opts.note("twin: none: no lab %s, no twin directory", wire.LabName)
	} else {
		line := "lab " + wire.LabName + " absent"
		if h.LabPresent {
			line = fmt.Sprintf("lab %s present (%s)", wire.LabName, plural(len(h.Nodes), "node"))
		}
		line += "; " + presence("twin directory", h.TwinDirPresent)
		if (block.Record == nil || !h.LabPresent) && h.Phrase != "" && !text.hostHeld {
			line += "; " + h.Phrase + "; fylgja twin destroy clears it"
		}
		opts.note("twin: %s", line)
		for _, n := range h.Nodes {
			// The package the node runs under, then what it was pushed: with two
			// platforms in one twin, which node is which is the first thing to read.
			// Both are the record's; a node it does not name has neither.
			line := ""
			if n.PSP != nil {
				line += "  " + *n.PSP
			}
			if a := n.Artifact; a != nil {
				line += fmt.Sprintf("  %s %s", a.Name, a.Checksum)
			}
			opts.note("  %s  %s  %s  %s%s", n.Name, n.Container, n.State, n.MgmtIPv4, line)
		}
	}

	if r := block.Record; r != nil {
		ref := "branch " + r.Branch
		if r.At != "" {
			ref += " at " + r.At
		}
		if w := r.Waypoint; w != nil {
			ref += fmt.Sprintf(" (waypoint %s/%d, at %s)", w.Series, w.Sequence, w.AtSource)
		}
		opts.note("record: %s, bundle_id %s, schema %s, contract %s", ref, r.BundleID, r.SchemaHash, r.ContractVersion)
		switch {
		case r.ObservedAt == nil:
			// The note says "unknown:" itself (lab.ObservedAtUnknown, M2's twin.json).
			opts.note("  intent read: %s", r.ObservedAtNote)
		case r.At != "":
			opts.note("  intent read at %s", *r.ObservedAt)
		default:
			opts.note("  intent read at %s; reproducing it with --at that instant is best-effort", *r.ObservedAt)
		}
		opts.note("  provisioned by run %s %s (source %s), worker %s, recorded %s, %s",
			r.Run.WorkflowID, r.Run.RunID, r.Source, r.WorkerVersion, r.RecordedAt, plural(r.Nodes, "node"))
		if text.step != "" {
			opts.note("  %s", text.step)
		}
	}

	opts.note("kind: %s", text.kind)
	for _, d := range text.details {
		opts.note("  %s", d)
	}

	printInFlight(opts, block.Service, block.InFlight)

	if opts.asJSON {
		return
	}
	last := block.LastCheck
	if block.Following != nil {
		last = block.Following.LastCheck
	}
	if last != nil && last.Outcome != provision.CheckUnchanged && len(last.Findings) > 0 {
		_, _ = fmt.Fprintf(opts.stderr(), "check %s %s ended %s:\n", last.WorkflowID, last.RunID, last.Outcome)
		_ = (&findings.Document{Findings: last.Findings}).WriteText(opts.stderr())
	}
}

// showRuns are the runs in flight as the show block carries them; a check carries its
// child's.
func showRuns(runs []provision.RunInFlight) []findings.ShowRun {
	var out []findings.ShowRun
	for _, r := range runs {
		run := findings.ShowRun{WorkflowID: r.WorkflowID, RunID: r.RunID, Step: r.Step}
		if c := r.Child; c != nil {
			run.Child = &findings.ShowRun{WorkflowID: c.WorkflowID, RunID: c.RunID, Step: c.Step}
		}
		out = append(out, run)
	}
	return out
}

// printInFlight writes the in flight: line, or lines (contracts/cli.md, twin show): unknown
// when the service did not answer, none, the one run, or each run under it. twin verify
// prints it as twin show does.
func printInFlight(opts *options, service string, runs []findings.ShowRun) {
	switch {
	case service == findings.ShowServiceUnreachable:
		opts.note("in flight: unknown")
	case len(runs) == 0:
		opts.note("in flight: none")
	case len(runs) == 1:
		opts.note("in flight: %s", runInFlight(runs[0]))
	default:
		opts.note("in flight:")
		for _, r := range runs {
			opts.note("  %s", runInFlight(r))
		}
	}
}

// rebuildInFlight is the check in flight at its destroy or provision step, or nil: while it
// is, the host holds whatever the rebuild has reached.
func rebuildInFlight(runs []findings.ShowRun) *findings.ShowRun {
	for i, r := range runs {
		if strings.HasPrefix(r.WorkflowID, provision.WorkflowReconcile+"-") &&
			(r.Step == findings.StepDestroy || r.Step == findings.StepProvision) {
			return &runs[i]
		}
	}
	return nil
}

// provisionAtHost is the operator's provisioning run in flight at a step that has touched the
// host (stage through record, the push among them since M5, or its cleanup), or nil. A check's child is never listed as
// the operator's run (provision.Client.InFlight).
func provisionAtHost(runs []findings.ShowRun) *findings.ShowRun {
	for i, r := range runs {
		if r.WorkflowID != provision.WorkflowProvision {
			continue
		}
		switch r.Step {
		case findings.StepStage, findings.StepDeploy, findings.StepReadiness, findings.StepPush, findings.StepRecord,
			findings.StepTeardown, findings.StepUnstage:
			return &runs[i]
		}
	}
	return nil
}

// runInFlight names a run in flight and its step; a check carries its child's.
func runInFlight(r findings.ShowRun) string {
	if !strings.HasPrefix(r.WorkflowID, provision.WorkflowReconcile+"-") {
		return fmt.Sprintf("run %s %s at step %s", r.WorkflowID, r.RunID, r.Step)
	}
	s := fmt.Sprintf("check %s at step %s", r.WorkflowID, r.Step)
	if c := r.Child; c != nil {
		s += fmt.Sprintf(" (run %s %s at step %s)", c.WorkflowID, c.RunID, c.Step)
	}
	return s
}

// plural is n and noun, with an s unless n is one.
func plural(n int, noun string) string {
	if n == 1 {
		return fmt.Sprintf("1 %s", noun)
	}
	return fmt.Sprintf("%d %ss", n, noun)
}
