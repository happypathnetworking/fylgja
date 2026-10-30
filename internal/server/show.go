package server

import (
	"context"
	"errors"
	"fmt"
	"maps"
	"slices"
	"strconv"
	"strings"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
)

// serviceReads is what twin show learned from the workflow service: the runs in flight, the
// one thing it asks since nothing follows a branch (019).
type serviceReads struct {
	inFlight []provision.RunInFlight
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
		// The message is the same whatever the cause (019): the service did not answer within
		// the budget the read is given, so what is in flight is unknown.
		unreachableAt, _ = serviceAddress(opts, err)
		list.Add(findings.Warning, findings.RuleShowServiceUnreachable, unreachableAt,
			fmt.Sprintf("the workflow service at %s did not answer within %s: whether a run is in flight is unknown",
				unreachableAt, opts.c.s.ServiceBudget))
	}

	block, text := decideShow(host, reads, unreachableAt)
	printShow(opts, block, text)

	doc := findings.NewDocument(op, nil, list)
	doc.Show = &block
	return &result{doc: doc}
}

// readService dials the workflow service and reads the runs in flight, within the server's
// ServiceBudget. The reads run beside the budget, so a service that never answers
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
		a.reads.inFlight, a.err = svc.InFlight(ctx)
	}()
	select {
	case a := <-done:
		// A read that failed leaves the runs in flight unknown, whatever it listed first.
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
	// record is the record line, whose last clause is the scope and the mapping the record
	// names, or the scope unknown for a record that names none (recordLine).
	record string
	// step is the record block's line for a record that has stepped, or "".
	step string
	// hosts is each node the record names as a probe's host, by name, with its probe (016):
	// its line names its format and its probe where a device's names its package and its
	// artifact. The show block carries no probe, so it is the text's alone.
	hosts map[string]*wire.TwinProbe
}

// decideShow builds the show block and its text from what the host holds and what the
// service said (the kind table, 019's research R-10). unreachableAt is the service's address when
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
	hosts := map[string]*wire.TwinProbe{}
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
			if ref := n.PSP; ref != nil && ref.ID != "" {
				id := ref.ID
				pkg[n.Name] = &id
			}
			if n.Probe != nil {
				hosts[n.Name] = n.Probe
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
			Branch: rec.Provenance.Branch, At: rec.Provenance.At, SnapshotID: rec.SnapshotID, BundleID: rec.BundleID,
			SchemaHash: rec.Provenance.SchemaHash,
			ObservedAt: rec.ObservedAt, ObservedAtNote: rec.ObservedAtNote,
			Source: rec.Source, Run: findings.ShowRef{WorkflowID: rec.Run.WorkflowID, RunID: rec.Run.RunID},
			WorkerVersion: rec.ProvisionedBy.Version, RecordedAt: rec.RecordedAt, Nodes: len(rec.Nodes),
		}
		// A version 8 record names the scope its read was made under and the mapping that
		// read it (017); an earlier one names neither, and shows neither, nor does an 8
		// whose scope is not tag:<name> or whose mapping twin.json 8 cannot hold, either of
		// which show.schema.json would refuse: it shows the scope only beside the mapping.
		if scopeKnown(rec) && mappingKnown(rec.Provenance.Mapping) {
			m := rec.Provenance.Mapping
			block.Record.Scope = rec.Provenance.Scope
			block.Record.Mapping = &findings.ShowMapping{Reader: m.Reader, Model: m.Model, Version: m.Version}
		}
		// A record names no stage and no rehearsal from twin.json 12 (020), and one of 11 or
		// earlier that names them shows neither.
		// A version 4 record says whether the twin is ready or diverged, and its last step.
		block.Record.State = rec.State
		block.Record.Step = showStep(rec.Step, waitRecorded(rec))
	}

	text := showText{hosts: hosts}
	if rec != nil {
		text.record = recordLine(rec)
	}
	if rec != nil && rec.Step != nil {
		text.step = stepLine(rec, waitRecorded(rec))
	}
	block.InFlight = showRuns(reads.inFlight)

	note := func(s string) { block.Notes = append(block.Notes, s) }
	provisioning := provisionAtHost(block.InFlight)
	switch {
	case rec == nil && provisioning != nil:
		// An operator's create or provision has reached the host: a lab or twin directory with
		// no twin.json is that run's work, or its cleanup's, not a run cut short, and a destroy
		// would cancel it. No create advice: a create is refused beside it.
		block.Kind = findings.ShowKindNone
		text.hostHeld = true
		s := fmt.Sprintf("run %s %s is at step %s, and the host holds its work", provisioning.WorkflowID, provisioning.RunID, provisioning.Step)
		text.kind = "none; " + s
		note(s)
	case rec == nil:
		block.Kind = findings.ShowKindNone
		text.kind = "none"
		if block.Host.Phrase == "" {
			note("no twin")
		} else {
			note(block.Host.Phrase + "; fylgja twin destroy clears it")
		}
	case !host.Lab.Present:
		// A record whose lab is gone (M3's shape b) is no twin: whether the twin exists is what
		// containerlab says (D-014). A create is refused as host.twin.present, so no create is
		// advised.
		block.Kind = findings.ShowKindNone
		text.kind = "none"
		note(block.Host.Phrase + "; fylgja twin destroy clears it")
	case rec.State == wire.StateDiverged && rec.Step != nil:
		// A step failed or was cancelled after the host was touched: the twin is up, where
		// the record's top level says, and only a destroy clears it. No create
		// advice beside a lab that exists.
		block.Kind = findings.ShowKindDiverged
		text.kind = divergedKind(rec)
		note(text.kind)
	case rec.Source == wire.SourceBundle:
		block.Kind = findings.ShowKindFromBundle
		text.kind = "from a bundle"
		note("provisioned from a bundle; read time unknown")
	default:
		// A twin from intent or a snapshot is frozen at the snapshot its record names, and
		// changes only when the operator steps it (D-062): its line names that snapshot and
		// what it was read from. A record naming none, an earlier build's rebuild's or a
		// record of 8 or earlier, cannot be stepped, and says so.
		block.Kind = findings.ShowKindSnapshot
		text.kind = snapshotKind(rec)
		if rec.SnapshotID == nil && recordSteps(rec) {
			text.details = append(text.details, noSnapshotNote)
			note(noSnapshotNote)
		}
		if rec.Provenance.At == "" && rec.ObservedAt != nil {
			note(fmt.Sprintf("reproducing the twin with --at %s is best-effort", *rec.ObservedAt))
		}
	}
	// A record of 11 or earlier is shown, naming its version, and twin step refuses it (020,
	// research R-06): a twin, diverged or not, whose lab is there.
	if rec != nil && host.Lab.Present && !recordSteps(rec) {
		s := fmt.Sprintf(oldRecordNote, rec.TwinVersion)
		text.details = append(text.details, s)
		note(s)
	}
	// A step run that has touched the host is named after the kind, as M4 named a rebuild
	// in flight until 019: the record still says where the twin was.
	if r := stepAtHost(block.InFlight); r != nil && rec != nil {
		text.hostHeld = true
		s := fmt.Sprintf("run %s %s is at step %s", r.WorkflowID, r.RunID, r.Step)
		if towards := stepTowards(reads.inFlight, r.RunID); towards != "" {
			s += ", stepping towards " + towards
		}
		text.kind += "; " + s
		note(s)
	}
	if !reachable {
		s := fmt.Sprintf("in flight: unknown (workflow service unreachable at %s)", unreachableAt)
		text.kind += "; " + s
		note(s)
	}
	return block, text
}

// waitRecorded says whether the record is version 5 or later, whose step block carries the
// step's wait, null until it has run.
func waitRecorded(rec *wire.TwinRecord) bool {
	v, err := strconv.Atoi(rec.TwinVersion)
	return err == nil && v >= 5
}

// recordSteps says whether the record is version 12 or later, which twin step steps (020,
// research R-06); one of 11 or earlier is shown naming its version and destroyed.
func recordSteps(rec *wire.TwinRecord) bool {
	v, err := strconv.Atoi(rec.TwinVersion)
	return err == nil && v >= 12
}

// oldRecordNote is what twin show says of a record of 11 or earlier, its version in place of
// %s (020, research R-06).
const oldRecordNote = "the twin's record is twin.json %s, a version this build no longer steps; fylgja twin destroy clears it"

// scopeRecorded says whether the record is version 8 or later, whose provenance names the
// scope its read was made under and the mapping that read it (017). twin step refuses a
// record that does not (stepScopeUnknown).
func scopeRecorded(rec *wire.TwinRecord) bool {
	v, err := strconv.Atoi(rec.TwinVersion)
	return err == nil && v >= 8
}

// scopeKnown says whether the record names a scope this build reads under: a record of 8 or
// later whose provenance's scope is tag:<name>. No build of this tree writes another
// (NewRecord and NewStepRecord refuse one), so an 8 that does not was edited by hand: twin
// show treats its scope as unknown, as a 7's, and twin step refuses it (stepScopeUnknown).
func scopeKnown(rec *wire.TwinRecord) bool {
	return scopeRecorded(rec) && ctm.ValidScope(rec.Provenance.Scope)
}

// mappingKnown says whether a record's mapping is one twin.json 8 holds: a reader's name of
// its form (ctm.ValidReader), a model and a version. No build of this tree writes another
// (NewRecord and NewStepRecord refuse one), so a record that does not was edited by hand:
// twin show names its reader unknown and shows no mapping, and twin step refuses it
// (stepScopeUnknown), since a step that diverges writes it into its own record.
func mappingKnown(m wire.Mapping) bool {
	return len(mappingUnheld(m)) == 0
}

// mappingUnheld names each field of a mapping twin.json 8 cannot hold, in the order reader,
// model, version: `reader "Infrahub DCIM"`, `model ""`, `version ""`. Empty when it holds them
// all.
func mappingUnheld(m wire.Mapping) []string {
	var named []string
	if !ctm.ValidReader(m.Reader) {
		named = append(named, fmt.Sprintf("reader %q", m.Reader))
	}
	if m.Model == "" {
		named = append(named, `model ""`)
	}
	if m.Version == "" {
		named = append(named, `version ""`)
	}
	return named
}

// recordLine is the record line twin show, twin create and twin provision print
// (contracts/cli.md, 017 and 018): the reference the record was read from, its snapshot, its
// bundle, its schema and its provenance, "record: branch b at …, snapshot …, bundle_id …,
// schema …, scope tag:fylgja, read by infrahub-dcim from opsmill/schema-library@26336e9".
func recordLine(rec *wire.TwinRecord) string {
	ref := "branch " + rec.Provenance.Branch
	if rec.Provenance.At != "" {
		ref += " at " + rec.Provenance.At
	}
	return fmt.Sprintf("record: %s, %s, bundle_id %s, schema %s, %s", ref, snapshotClause(rec), rec.BundleID,
		rec.Provenance.SchemaHash, provenanceClause(rec))
}

// snapshotClause is the record line's snapshot (018): "snapshot <id>", the full id, as the
// bundle's is printed; "snapshot none" for a 9 or 10 naming none, a twin twin provision
// built or an earlier build's following rebuild made (until 019); and "snapshot none
// (record <version>)" for a record of 8 or earlier, which names none, "(record 8)" for an
// 8.
func snapshotClause(rec *wire.TwinRecord) string {
	switch {
	case rec.SnapshotID != nil:
		return "snapshot " + *rec.SnapshotID
	case snapshotRecorded(rec):
		return "snapshot none"
	default:
		return fmt.Sprintf("snapshot none (record %s)", rec.TwinVersion)
	}
}

// snapshotRecorded says whether the record is version 9 or later, which names the snapshot
// the twin was built from or last stepped to, or null for none (018).
func snapshotRecorded(rec *wire.TwinRecord) bool {
	v, err := strconv.Atoi(rec.TwinVersion)
	return err == nil && v >= 9
}

// provenanceClause is the record line's last clause (contracts/cli.md): "scope tag:fylgja,
// read by infrahub-dcim from opsmill/schema-library@26336e9"; for a record of 7 or
// earlier, "scope unknown (record 7)"; for an 8 naming a scope that is not tag:<name>,
// `scope unknown (record 8 names scope "fylgja", not tag:<name>)`; and for an 8 whose
// mapping twin.json 8 cannot hold, each field it fails named, `scope tag:fylgja, read by an
// unknown reader (record 8 names mapping reader "Infrahub DCIM")`.
func provenanceClause(rec *wire.TwinRecord) string {
	if !scopeRecorded(rec) {
		return fmt.Sprintf("scope unknown (record %s)", rec.TwinVersion)
	}
	if !scopeKnown(rec) {
		return fmt.Sprintf("scope unknown (record %s names scope %q, not tag:<name>)", rec.TwinVersion, rec.Provenance.Scope)
	}
	m := rec.Provenance.Mapping
	if named := mappingUnheld(m); len(named) > 0 {
		return fmt.Sprintf("scope %s, read by an unknown reader (record %s names mapping %s)", rec.Provenance.Scope,
			rec.TwinVersion, strings.Join(named, ", "))
	}
	return fmt.Sprintf("scope %s, read by %s from %s@%s", rec.Provenance.Scope, m.Reader, m.Model, m.Version)
}

// showStep is twin.json 4's step block as twin show shows it (contracts/show.schema.json),
// or nil for a record that has not stepped. A version 5 record's adds its wait, or null while
// it has not run.
func showStep(st *wire.StepRecord, waitKnown bool) *findings.ShowStep {
	if st == nil {
		return nil
	}
	side := func(s wire.StepSide) findings.StepSideBlock {
		return findings.StepSideBlock{SnapshotID: s.SnapshotID, BundleID: s.BundleID, At: s.At}
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

// divergedKind is the kind line of a diverged twin (contracts/cli.md, twin show). Its target
// is named by its Name() and where the twin is by wire.TwinRecord.Position() (019): by its
// snapshot or bundle, a record naming no stage from 020.
func divergedKind(rec *wire.TwinRecord) string {
	st := rec.Step
	return fmt.Sprintf("diverged towards %s (bundle %s): run %s %s stopped at phase %s; landed: %s; not landed: %s; "+
		"the twin is at %s (bundle %s); fylgja twin destroy clears it",
		st.To.Name(), shortID(st.To.BundleID), st.Run.WorkflowID, st.Run.RunID, phaseOf(st),
		orNone(landed(st)), orNone(notLanded(st)), rec.Position(), shortID(rec.BundleID))
}

// noSnapshotNote is what twin show says of a twin whose record names no snapshot (019): an
// earlier build's rebuild, or a record of 8 or earlier, which twin step refuses.
const noSnapshotNote = "the twin's record names no snapshot, so fylgja twin step refuses it; fylgja twin destroy clears it"

// snapshotKind is the kind line of a twin built from intent or a snapshot (contracts/cli.md,
// 019): the snapshot its record names, short, or none; in brackets its branch and its at, or
// the time it was read when it has none; then the step that took it there. A record names no
// stage and no rehearsal from 020 (research R-06), and one of 11 or earlier that names them
// shows neither.
//
//	snapshot 9c2d01e7… (branch change-1 at …) (stepped from snapshot 576933ec… by run fylgja-step 0a1b…, ended …)
func snapshotKind(rec *wire.TwinRecord) string {
	id := "none"
	if rec.SnapshotID != nil {
		id = shortID(*rec.SnapshotID)
	}
	observed := ""
	if rec.ObservedAt != nil {
		observed = *rec.ObservedAt
	}
	line := fmt.Sprintf("snapshot %s (%s)", id, branchRef(rec.Provenance.Branch, rec.Provenance.At, observed))
	if st := rec.Step; st != nil {
		line += fmt.Sprintf(" (stepped from %s by run %s %s, ended %s)", st.From.Name(), st.Run.WorkflowID,
			st.Run.RunID, st.EndedAt)
	}
	return line
}

// branchRef is what a snapshot is of, as the kind line and a step's twin and target lines
// name it (019): branch B at T when it is pinned, else branch B, read at the time it was
// read, or the branch alone when that is unknown.
func branchRef(branch, at, observedAt string) string {
	ref := "branch " + branch
	switch {
	case at != "":
		ref += " at " + at
	case observedAt != "":
		ref += ", read at " + observedAt
	}
	return ref
}

// stepLine is the record block's line for a record that has stepped: how the step went, or
// where it stopped (contracts/cli.md, twin show). A version 5 record's line ends with how
// the step's wait ended. Each side is named by its Name().
func stepLine(rec *wire.TwinRecord, waitKnown bool) string {
	line := m11StepLine(rec)
	if !waitKnown {
		return line
	}
	return line + "; " + showWaitClause(rec.Step.Wait)
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

// m11StepLine is M11's step line of rec's step, unchanged by the wait.
func m11StepLine(rec *wire.TwinRecord) string {
	st := rec.Step
	if st.Outcome == wire.StepDiverged {
		return fmt.Sprintf("diverged: step run %s %s towards %s (bundle %s) stopped at phase %s, ended %s; landed %s; not landed %s",
			st.Run.WorkflowID, st.Run.RunID, st.To.Name(), shortID(st.To.BundleID), phaseOf(st), st.EndedAt,
			orNone(landed(st)), orNone(notLanded(st)))
	}
	line := fmt.Sprintf("stepped from %s by run %s %s, ended %s", st.From.Name(), st.Run.WorkflowID,
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

// stepTowards is the side the step run runID is stepping towards, as the service read it
// from the run's input and wire.StepSide.Name() names it, or "".
func stepTowards(runs []provision.RunInFlight, runID string) string {
	for _, r := range runs {
		if r.WorkflowID == wire.StepWorkflowID && r.RunID == runID {
			return r.Towards
		}
	}
	return ""
}

// printShow writes twin show's text layout (contracts/cli.md): the host, the record, the kind
// and the runs in flight.
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
			// A probe's host has no package and no artifact: its line names its format and the
			// probe and endpoint it is (016).
			line := ""
			if n.PSP != nil {
				line += "  " + *n.PSP
			}
			if a := n.Artifact; a != nil {
				line += fmt.Sprintf("  %s %s", a.Name, a.Checksum)
			}
			if p := text.hosts[n.Name]; p != nil {
				line += fmt.Sprintf("  %s host  probe %s %s", p.Format, p.Name, p.Endpoint)
			}
			opts.note("  %s  %s  %s  %s%s", n.Name, n.Container, n.State, n.MgmtIPv4, line)
		}
	}

	if r := block.Record; r != nil {
		opts.note("%s", text.record)
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
}

// showRuns are the runs in flight as the show block carries them. None carries a child from
// 020: no workflow the worker serves starts one.
func showRuns(runs []provision.RunInFlight) []findings.ShowRun {
	var out []findings.ShowRun
	for _, r := range runs {
		out = append(out, findings.ShowRun{WorkflowID: r.WorkflowID, RunID: r.RunID, Step: r.Step})
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

// provisionAtHost is the provisioning run in flight at a step that has touched the host
// (stage through record, the push among them since M5, or its cleanup), or nil.
func provisionAtHost(runs []findings.ShowRun) *findings.ShowRun {
	for i := range runs {
		run := &runs[i]
		if run.WorkflowID != provision.WorkflowProvision {
			continue
		}
		switch run.Step {
		case findings.StepStage, findings.StepDeploy, findings.StepReadiness, findings.StepPush, findings.StepRecord,
			findings.StepTeardown, findings.StepUnstage:
			return run
		}
	}
	return nil
}

// runInFlight names a run in flight and its step:
//
//	run fylgja-step 03c3… at step push
func runInFlight(r findings.ShowRun) string {
	return fmt.Sprintf("run %s %s at step %s", r.WorkflowID, r.RunID, r.Step)
}

// plural is n and noun, with an s unless n is one.
func plural(n int, noun string) string {
	if n == 1 {
		return fmt.Sprintf("1 %s", noun)
	}
	return fmt.Sprintf("%d %ss", n, noun)
}
