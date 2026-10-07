package server

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"maps"
	"math"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"time"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/verify"
)

type verifyFlags struct {
	// wait is --wait's value: the flag's own default when it was given bare, read only when
	// waitGiven.
	wait string
	// waitGiven is whether --wait was given at all, apart from its value: an explicit empty
	// one is refused, not left out (M4's --interval= rule).
	waitGiven bool
	// args are the positional arguments, which only a bare --wait leaves behind.
	args []string
}

// runTwinVerify reads the twin and reports it against intent, each part changing nothing on
// the host, in the record or in the store: --wait; the
// packages; the host as twin show inspects it; the runs in flight, best-effort; the twin,
// refused when there is none; the staged bundle; the packages and logins its nodes need,
// every refusal in one pass; the assertions; then one read, or the wait, and the report.
// No interrupt is taken: an interrupt ends the client by the signal, and the request's work
// with it, writing nothing.
func runTwinVerify(ctx context.Context, opts *options, f *verifyFlags) error {
	const op = findings.OpTwinVerify
	budget, refused := verifyBudget(op, f)
	if refused != nil {
		return refused
	}
	if ctx == nil {
		ctx = context.Background()
	}
	// An override package psp validate rejects is refused under its own findings, as every
	// command refuses it.
	reg, err := psp.Load(opts.pspDir)
	if err != nil {
		return loadFailure(op, nil, err)
	}
	cannotInspect := func(err error) error {
		return failAt(op, nil, findings.StepObserve, "lab "+wire.LabName, "inspecting the host: %v", err)
	}
	paths, err := opts.paths()
	if err != nil {
		return cannotInspect(err)
	}
	acts := dryRunActivities(opts, reg, paths)
	host, err := acts.InspectHost(ctx)
	if err != nil {
		return cannotInspect(err)
	}

	// The runs in flight, as twin show asks for them: a service that does not answer is a
	// warning, and the read goes on.
	var list findings.List
	service := findings.ShowServiceOK
	reads, err := readService(ctx, opts)
	if err != nil {
		at, cause := serviceAddress(opts, err)
		service = findings.ShowServiceUnreachable
		list.Add(findings.Warning, findings.RuleShowServiceUnreachable, at,
			fmt.Sprintf("workflow service unreachable at %s (%v); whether a run is in flight is unknown", at, cause))
	}
	inFlight := showRuns(reads.inFlight)

	// A twin is a readable record beside a present lab, of whatever kind.
	if !host.Lab.Present || host.Twin == nil {
		object, message := twinAbsent(host, paths, inFlight)
		list.AddStep(findings.Rejection, findings.StepObserve, findings.RuleVerifyTwinAbsent, object, message)
		return finish(op, nil, list)
	}
	rec := host.Twin

	stagedID := ""
	failed := func(object, format string, args ...any) error {
		l := append(findings.List{}, list...)
		l.AddStep(findings.Rejection, findings.StepObserve, findings.RuleOperationFailed, object, fmt.Sprintf(format, args...))
		doc := findings.NewDocument(op, nil, l)
		doc.Status = findings.StatusError
		doc.BundleID = stagedID
		return &result{doc: doc}
	}
	// The staged bundle is what the twin runs, or is being taken to: a
	// "3" manifest reads, every row enabled.
	m, err := stagedManifest(paths.TwinBundle)
	if err != nil {
		return failed(paths.TwinBundle, "reading the staged bundle: %v", err)
	}
	if stagedID, err = bundle.IDOfDir(paths.TwinBundle); err != nil {
		return failed(paths.TwinBundle, "reading the staged bundle: %v", err)
	}

	if refusals := verifyPackages(m, reg, opts.getenv); refusals.Rejected() {
		doc := findings.NewDocument(op, nil, append(list, refusals...))
		doc.BundleID = stagedID
		return &result{doc: doc}
	}
	assertions, err := verify.Derive(m)
	if err != nil {
		object := paths.TwinBundle
		if me := (*verify.ManifestError)(nil); errors.As(err, &me) {
			object = me.Object
		}
		return failed(object, "%v", err)
	}

	opts.note("%s", verifyTwinLine(rec))
	opts.note("staged: bundle %s; %s over %s, %d skipped", shortID(stagedID), plural(len(assertions), "assertion"),
		plural(len(m.Nodes), "node"), countOutcome(assertions, verify.Skipped))

	in := verify.Input{Manifest: m, StagedID: stagedID, Record: *rec, Lab: host.Lab.Nodes, Packages: reg,
		Reader: opts.c.reader(), Getenv: opts.getenv}
	var (
		report verify.Report
		wait   *findings.VerifyWait
		waited verify.WaitResult
	)
	if f.waitGiven {
		// A node a read could not dial is looked up again before the next read, through the
		// same inspection the host was read by.
		inspect := func(ctx context.Context) ([]wire.LabNode, error) {
			state, err := acts.Clab.InspectAll(ctx)
			if err != nil {
				return nil, err
			}
			return append([]wire.LabNode{}, state.Nodes...), nil
		}
		waited = verify.Wait(ctx, in, assertions, verify.WaitOptions{Budget: budget, Sleep: opts.c.s.Sleep, Now: opts.c.s.Now, Lab: inspect})
		// Only an interrupt ends a wait cancelled, and none is handled here: the client
		// ends by the signal first, and the request's context with it. A context ended by
		// any other hand writes no report.
		if waited.Outcome == verify.WaitCancelled {
			return ctx.Err()
		}
		report = waited.Last
		wait = &findings.VerifyWait{BudgetS: int(budget / time.Second), Reads: waited.Reads, Outcome: waited.Outcome,
			AfterS: math.Round(waited.AfterS*1000) / 1000}
	} else {
		report = verify.Read(ctx, in, assertions)
	}
	block := report.Block(verify.TwinOf(*rec, stagedID), inFlight, service, wait)

	printVerify(opts, report, block)
	if f.waitGiven {
		opts.note("%s", waitLine(budget, waited))
	}

	list = append(list, report.Findings()...)
	doc := findings.NewDocument(op, nil, list)
	doc.BundleID = stagedID
	doc.Verify = block
	// The status is set here, never derived: every assertion's finding is a rejection, and
	// what it ends is decided by whether every node was read.
	doc.Status = verifyStatus(report)
	return &result{doc: doc}
}

// verifyBudget is --wait's budget, zero when it was not given, or its refusal as
// verify.wait.invalid, exit 2, at step start: a value that is not a
// duration, a negative or empty one, and a word a bare --wait left behind as an argument.
// A part of a second counts as a whole one, as twin step --wait counts it, so the wait,
// budget_s and the last line agree and the budget is never shorter than asked.
func verifyBudget(op string, f *verifyFlags) (time.Duration, error) {
	if !f.waitGiven {
		return 0, nil
	}
	refuse := func(format string, args ...any) error {
		doc := findings.RuleErrorDocument(op, nil, findings.RuleVerifyWaitInvalid, "--wait", fmt.Sprintf(format, args...))
		doc.Findings[0].Step = findings.StepStart
		return &result{doc: doc}
	}
	if f.wait == "" {
		return 0, refuse("--wait= is empty; give a duration such as --wait=2m, or --wait alone for the default %s",
			verify.DefaultBudget)
	}
	d, err := time.ParseDuration(f.wait)
	switch {
	case err != nil:
		return 0, refuse("--wait=%s is not a duration: %v", f.wait, err)
	case d < 0:
		return 0, refuse("--wait=%s is not a duration: a budget cannot be negative", f.wait)
	case len(f.args) > 0:
		return 0, refuse("--wait takes its value as --wait=<duration>; %q was given as an argument", f.args[0])
	}
	return time.Duration(math.Ceil(d.Seconds())) * time.Second, nil
}

// twinAbsent is verify.twin.absent's object and message (contracts/cli.md): the host in
// M3's phrase and nothing to verify, then the remedy, or the run that holds the host in its
// place. The object is the lab while it is present, or on an empty host, and the twin
// directory when only that is.
func twinAbsent(host lab.HostState, paths lab.Paths, runs []findings.ShowRun) (object, message string) {
	object = "lab " + wire.LabName
	if !host.Lab.Present && host.TwinDirPresent {
		object = paths.Twin
	}
	phrase := host.Describe()
	message = phrase + "; nothing to verify"
	if phrase == "" {
		message = fmt.Sprintf("no twin: no lab %s and no twin directory; nothing to verify", wire.LabName)
	}
	switch holder := hostHolder(runs); {
	case holder != nil:
		message += fmt.Sprintf("; run %s %s is at step %s", holder.WorkflowID, holder.RunID, holder.Step)
	case phrase != "":
		message += "; fylgja twin destroy clears it"
	}
	return object, message
}

// hostHolder is the run in flight whose work the host holds, or nil: a check's rebuild,
// an operator's provisioning run from its stage through its cleanup, or a step from its
// stage through its record.
func hostHolder(runs []findings.ShowRun) *findings.ShowRun {
	if r := rebuildInFlight(runs); r != nil {
		return r
	}
	if r := provisionAtHost(runs); r != nil {
		return r
	}
	return stepAtHost(runs)
}

// stagedManifest reads the staged bundle's manifest as written, whatever its
// bundle_version: a "3" manifest has no enabled key, and reads every row enabled.
func stagedManifest(dir string) (compiler.Manifest, error) {
	b, err := os.ReadFile(filepath.Join(dir, compiler.ManifestFile))
	if err != nil {
		return compiler.Manifest{}, err
	}
	var m compiler.Manifest
	if err := json.Unmarshal(b, &m); err != nil {
		return compiler.Manifest{}, fmt.Errorf("%s: %w", filepath.Join(dir, compiler.ManifestFile), err)
	}
	return m, nil
}

// verifyPackages refuses, in one pass, what would stop a node being read:
// a package no longer loaded, one with no conformance facet or a readiness probe that is
// not gNMI, and a readiness login unset, worded as the host check words it. Each at step
// observe.
func verifyPackages(m compiler.Manifest, reg *psp.Registry, getenv func(string) (string, bool)) findings.List {
	var (
		out      findings.List
		missing  = map[string][]string{}
		sources  = map[string]string{}
		found    = map[string]*psp.PSP{}
		probeFor []wire.NodePlan
	)
	for _, n := range m.Nodes {
		p, ok := reg.LookupID(n.PSP.ID)
		if !ok {
			missing[n.PSP.ID] = append(missing[n.PSP.ID], n.Name)
			sources[n.PSP.ID] = n.PSP.Source
			continue
		}
		found[n.PSP.ID] = p
		probeFor = append(probeFor, wire.NodePlan{Name: n.Name, PSPID: n.PSP.ID, Probe: verify.ReadinessProbe(p)})
	}
	add := func(rule, object, format string, args ...any) {
		out.AddStep(findings.Rejection, findings.StepObserve, rule, object, fmt.Sprintf(format, args...))
	}
	for _, id := range slices.Sorted(maps.Keys(missing)) {
		add(findings.RuleHostPSPMissing, id, "support package %s (manifest source %s), named by %s, is not on this worker",
			id, sources[id], strings.Join(missing[id], ", "))
	}
	for _, id := range slices.Sorted(maps.Keys(found)) {
		p := found[id]
		if p.Conformance == nil {
			add(findings.RuleVerifyPackageUnreadable, id,
				"support package %s declares no conformance block; fylgja twin verify cannot read its nodes", id)
		}
		if probe := p.Readiness.Probe; probe != psp.ProbeGNMIGet && probe != psp.ProbeGNMISubscribe {
			add(findings.RuleVerifyPackageUnreadable, id,
				"support package %s's readiness probe is %s; fylgja twin verify reads by gNMI only", id, probe)
		}
	}
	return append(out, lab.ProbeLoginsUnset(probeFor, getenv).AtStep(findings.StepObserve)...)
}

// verifyStatus is what the report ends the command as: error when a node
// was not read, the other nodes' assertions kept; nonconforming when every node was read
// and an assertion or a claim did not hold; ok otherwise.
func verifyStatus(r verify.Report) findings.Status {
	switch {
	case !r.AllRead():
		return findings.StatusError
	case !r.Conforms() || slices.ContainsFunc(r.Claims, func(c verify.Claim) bool { return c.Outcome != verify.Held }):
		return findings.StatusNonconforming
	}
	return findings.StatusOK
}

// verifyTwinLine is the twin: line (contracts/cli.md): the record's reference as twin show
// names it, the bundle the record says the twin is at, its state, a diverged twin's step,
// and the node count.
func verifyTwinLine(rec *wire.TwinRecord) string {
	ref := "branch " + rec.Provenance.Branch
	if rec.Waypoint != nil {
		ref = "waypoint " + waypointOf(rec.Waypoint)
	} else if rec.Provenance.At != "" {
		ref += " at " + rec.Provenance.At
	}
	state := "ready"
	switch st := rec.Step; {
	case rec.State == wire.StateDiverged && st != nil:
		state = fmt.Sprintf("diverged towards %s (bundle %s) at phase %s by run %s %s", waypointOf(st.To.Waypoint),
			shortID(st.To.BundleID), phaseOf(st), st.Run.WorkflowID, st.Run.RunID)
	case rec.Waypoint != nil && rec.Provenance.At != "":
		state += ", pinned at " + rec.Provenance.At
	}
	return fmt.Sprintf("twin: %s (bundle %s), %s; %s", ref, shortID(rec.BundleID), state, plural(len(rec.Nodes), "node"))
}

// printVerify writes one line per node, the skips, the runs in flight, the nodes the bundle
// does not name and the counts (contracts/cli.md), from the read the block was built from.
func printVerify(opts *options, r verify.Report, block *findings.VerifyBlock) {
	claims := map[string]verify.Claim{}
	for _, c := range r.Claims {
		claims[c.Node] = c
	}
	unread := map[string]verify.NodeError{}
	for _, e := range r.Unread {
		unread[e.Node] = e
	}
	for _, n := range r.Nodes {
		var mine []verify.Assertion
		for _, a := range r.Assertions {
			if a.Node == n.Node {
				mine = append(mine, a)
			}
		}
		var claim *verify.Claim
		if c, ok := claims[n.Node]; ok {
			claim = &c
		}
		var e *verify.NodeError
		if ne, ok := unread[n.Node]; ok {
			e = &ne
		}
		opts.note("%s", nodeLine(n, mine, claim, e))
	}
	opts.note("skipped: %s", skippedText(block.Skipped))
	printInFlight(opts, block.Service, block.InFlight)
	if len(block.ExtraNodes) > 0 {
		opts.note("not in the bundle: %s", strings.Join(block.ExtraNodes, ", "))
	}
	c := block.Counts
	var failed []string
	for _, k := range []struct {
		n    int
		noun string
	}{{c.HostName.Failed, "host name"}, {c.PortEnabled.Failed, "port"}, {c.Neighbor.Failed, "link end"}, {c.Record.Failed, "record claim"}} {
		if k.n > 0 {
			failed = append(failed, plural(k.n, k.noun))
		}
	}
	var unreadNodes []string
	for _, e := range r.Unread {
		unreadNodes = append(unreadNodes, e.Node)
	}
	opts.note("held: %s, %s, %s, %s (the record's, not read); failed: %s; unread: %s",
		plural(c.HostName.Held, "host name"), plural(c.PortEnabled.Held, "port"), plural(c.Neighbor.Held, "link end"),
		plural(c.Record.Held, "record claim"), orNone(strings.Join(failed, ", ")), orNone(strings.Join(unreadNodes, ", ")))
}

// nodeLine is one node's line: its address and package, then each assertion in its held
// form, or naming itself and its rule where it did not hold, then the record's claim; an
// unread node's line says why it was not read.
func nodeLine(n verify.NodeRead, as []verify.Assertion, claim *verify.Claim, e *verify.NodeError) string {
	addr := n.Addr
	if addr == "" {
		addr = "no address"
	}
	head := fmt.Sprintf("%s (%s, %s)", n.Node, addr, n.PSP)
	if e != nil {
		return fmt.Sprintf("%s: not read: %s (%s)", head, e.Error, findings.RuleOperationFailed)
	}
	var hostName, enabled, ports, neighbours, seen []string
	for _, a := range as {
		switch a.Kind {
		case verify.KindHostName:
			switch a.Outcome {
			case verify.Held:
				hostName = append(hostName, "host name "+a.Read)
			case verify.Failed:
				hostName = append(hostName, fmt.Sprintf("host name %q (%s)", a.Read, findings.RuleVerifyHostName))
			case verify.Absent:
				hostName = append(hostName, fmt.Sprintf("host name reads nothing (%s)", findings.RuleVerifyHostName))
			}
		case verify.KindPortEnabled:
			switch a.Outcome {
			case verify.Held:
				enabled = append(enabled, a.Port)
			case verify.Failed:
				ports = append(ports, fmt.Sprintf("%s reads %q (%s)", a.Port, a.Read, findings.RuleVerifyPortEnabled))
			case verify.Absent:
				ports = append(ports, fmt.Sprintf("%s reads nothing (%s)", a.Port, findings.RuleVerifyPortEnabled))
			}
		case verify.KindNeighbor:
			switch {
			case a.Outcome == verify.Held:
				neighbours = append(neighbours, a.Read)
			case a.Outcome == verify.Absent:
				seen = append(seen, fmt.Sprintf("%s sees no neighbour (%s)", a.Port, findings.RuleVerifyNeighbor))
			case a.Outcome == verify.Failed && len(a.Seen) == 0:
				seen = append(seen, fmt.Sprintf("%s reads %s (%s)", a.Port, a.Read, findings.RuleVerifyNeighbor))
			case a.Outcome == verify.Failed:
				seen = append(seen, fmt.Sprintf("%s sees %s (%s)", a.Port, a.Read, findings.RuleVerifyNeighbor))
			}
		}
	}
	parts := hostName
	if len(enabled) > 0 {
		parts = append(parts, strings.Join(enabled, ", ")+" enabled")
	}
	parts = append(parts, ports...)
	switch len(neighbours) {
	case 0:
	case 1:
		parts = append(parts, "neighbour "+neighbours[0])
	default:
		parts = append(parts, "neighbours "+strings.Join(neighbours, ", "))
	}
	parts = append(parts, seen...)
	switch {
	case claim == nil:
	case claim.Outcome == verify.Held:
		parts = append(parts, "record: holds "+shortID(claim.Staged))
	case claim.Unnamed:
		parts = append(parts, fmt.Sprintf("record: does not name it (%s)", findings.RuleVerifyRecordHolds))
	case claim.Holds == nil:
		parts = append(parts, fmt.Sprintf("record: holds no bundle (%s)", findings.RuleVerifyRecordHolds))
	default:
		parts = append(parts, fmt.Sprintf("record: holds %s, not the staged bundle (%s)", shortID(*claim.Holds),
			findings.RuleVerifyRecordHolds))
	}
	return head + ": " + strings.Join(parts, "; ")
}

// skippedText names each skip and why (contracts/cli.md): a port intent disables, then each
// link on such a port, once for both its ends.
func skippedText(skips []findings.VerifySkip) string {
	var parts []string
	done := map[string]bool{}
	for _, s := range skips {
		at := s.Node + ":" + s.Port
		if s.Link == nil {
			reason := s.Reason
			if reason == "intent disables "+at {
				reason = "intent disables it"
			}
			parts = append(parts, fmt.Sprintf("%s (%s)", at, reason))
			continue
		}
		id := *s.Link
		if done[id] {
			continue
		}
		done[id] = true
		parts = append(parts, fmt.Sprintf("link %s at both ends (%s)", id, strings.TrimPrefix(s.Reason, "link "+id+" is not asserted: ")))
	}
	return orNone(strings.Join(parts, "; "))
}

// waitLine is --wait's last line (contracts/cli.md): settled, or the budget expired with a
// node still unread, or with assertions still failing.
func waitLine(budget time.Duration, w verify.WaitResult) string {
	if w.Outcome == verify.WaitSettled {
		return fmt.Sprintf("settled after %s (%s; budget %s)", seconds(w.AfterS), plural(w.Reads, "read"), budget)
	}
	head := fmt.Sprintf("budget %s expired after %s (%s)", budget, seconds(w.AfterS), plural(w.Reads, "read"))
	if !w.Last.AllRead() {
		var nodes []string
		for _, e := range w.Last.Unread {
			nodes = append(nodes, e.Node)
		}
		return fmt.Sprintf("%s: %s still unread", head, strings.Join(nodes, ", "))
	}
	failing := countOutcome(w.Last.Assertions, verify.Failed) + countOutcome(w.Last.Assertions, verify.Absent)
	return fmt.Sprintf("%s: %s still failing", head, plural(failing, "assertion"))
}

// countOutcome counts the assertions that came out as outcome.
func countOutcome(as []verify.Assertion, outcome string) int {
	n := 0
	for _, a := range as {
		if a.Outcome == outcome {
			n++
		}
	}
	return n
}
