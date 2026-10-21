package server

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"path/filepath"
	"strings"
	"time"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/stages"
	"github.com/happypathnetworking/fylgja/internal/step"
	"github.com/happypathnetworking/fylgja/internal/verify"
)

type stepFlags struct {
	// stage is --stage as given, <branch>/<label>: the target, in place of the next stage
	// of the twin's proposed change.
	stage string
	// stageGiven is whether --stage was given at all, apart from its value: an explicit
	// empty one is a reference refused, not one left out (M4's --interval= precedent).
	stageGiven   bool
	allowRestart bool
	dryRun       bool
	// wait is --wait as given: the budget of the step's wait after its record.
	wait string
	// waitGiven is whether --wait was given at all, apart from its value: an explicit empty
	// one is refused, not left out (M4's --interval= rule).
	waitGiven bool
	// waitS is the budget in seconds, verify.DefaultBudget's when --wait is left out.
	waitS int
}

// runTwinStep steps the stage twin. Everything up to the run is decided here, each refusal
// ending the command with its document: --stage as given; the packages; a rehearsal in
// flight, asked of the workflow service before anything else is read, since the twin and the
// host are its own (015; T080); the host, whose twin must be a stage twin that is not
// diverged; the record's proposed change and the target (014: research R-16), with stage
// list's stage.twin.moved beside it when the record's stage has moved; the target's
// resolution, read, compile and filing on stage plan's path; the from bundle out of the
// store; the step between the two; the host check on the target and containerlab's plan
// for the lab, both in this process as a dry run reads them; and the rules on that plan.
// Then the dry run reports, or the run starts. Once the target is chosen, every document
// the command ends with carries what it had found by then, a failure's included.
func runTwinStep(ctx context.Context, opts *options, f *stepFlags) error {
	const op = findings.OpTwinStep
	subject := &findings.Subject{}

	var given *stages.Ref
	if f.stageGiven || f.stage != "" {
		ref, refused := stageGuards(op, subject, findings.StepStart, f.stage, nil)
		if refused != nil {
			return refused
		}
		given = &ref
	}
	waitS, refused := stepWait(op, subject, f)
	if refused != nil {
		return refused
	}
	f.waitS = waitS
	if ctx == nil {
		ctx = context.Background()
	}
	// An override package psp validate rejects is refused under its own findings before
	// anything is read, as a create refuses it.
	reg, err := psp.Load(opts.pspDir)
	if err != nil {
		return loadFailureAt(op, subject, findings.StepRead, err)
	}
	paths, err := opts.paths()
	if err != nil {
		return failAt(op, subject, findings.StepResolve, findings.StepResolve, "%v", err)
	}
	if f.dryRun {
		opts.note("dry run: no lab, container, twin directory or run is changed")
	} else if refused := rehearsalHolds(ctx, opts, op, subject); refused != nil {
		return refused
	}

	// The host, read as twin show reads it, changing nothing.
	acts := dryRunActivities(opts, reg, paths)
	host, err := acts.InspectHost(ctx)
	if err != nil {
		return failAt(op, subject, findings.StepResolve, "lab "+wire.LabName, "inspecting the host: %v", err)
	}
	report := wire.HostReport{LabPresent: host.Lab.Present, Nodes: host.Lab.Nodes, TopoPaths: host.Lab.TopoPaths,
		TwinDirPresent: host.TwinDirPresent, Twin: host.Twin, TwinReadError: host.TwinReadError, Phrase: host.Describe()}
	if refused := provision.Ineligible(report, findings.StepResolve, paths.Twin); refused != nil {
		return finish(op, subject, findings.List{*refused})
	}
	rec := host.Twin
	opts.note("twin: stage %s (bundle %s), pinned at %s; %s", rec.Stage.Name(), shortID(rec.BundleID),
		rec.Provenance.At, plural(len(rec.Nodes), "node"))

	// The record's proposed change, found once by its source branch (steps 1–3 and the
	// head's at), and the target chosen among its stages; then the target resolved
	// (steps 4–9), read, compiled and filed as stage plan builds a stage.
	reader, err := intent.StageReaderFromEnv()
	if err != nil {
		return failAt(op, subject, findings.StepResolve, op, "%v", err)
	}
	ch, list, err := stages.Find(ctx, reader, intentStamper{}, rec.Stage.ProposedChange.Branch)
	if err != nil {
		return failAt(op, subject, findings.StepResolve, op, "%v", err)
	}
	if list.Rejected() {
		return finish(op, subject, list)
	}
	view := *stages.RecordViewOf(rec)
	target, _, list := stages.Target(ch, view, given)
	if list.Rejected() {
		return finish(op, subject, list)
	}
	// The record's stage moved under the twin is stage list's warning, beside the target's
	// findings: the step goes from the bundle the record holds whatever its stage now
	// resolves to, so it refuses nothing.
	list = append(list, stages.Moved(ch, view)...)
	subject.Stage = target.String()

	file := func(ctx context.Context, files map[string][]byte, id string, snapshot *ctm.CTM) (findings.List, error) {
		_, filed, err := fileCompiled(ctx, paths.Bundles, files, id, snapshot)
		return filed, err
	}
	built := stages.Build(ctx, reader, intentStamper{}, reg, ch, target, stages.NewPipeline(file), time.Now().UTC())
	list = append(list, built.Findings...)
	var resolved *resolvedStage
	if r := built.Resolved; r != nil {
		resolved = &resolvedStage{block: r.Block(), record: r.StageRef()}
		subject.Branch, subject.At = r.Branch, r.At
		opts.note("%s", resolved.block.Line())
	}
	if built.Status != stages.PlanCompiled {
		doc := findings.NewDocument(op, subject, list)
		// An Infrahub that cannot be reached and M1's precision rule keep M10's exit 2.
		if built.Status == stages.PlanFailed || carriesRule(built.Findings, findings.RuleAtPrecision) {
			doc.Status = findings.StatusError
		}
		if resolved != nil {
			doc.Stage = &resolved.block
		}
		return &result{doc: doc}
	}
	return withStage(stepTo(ctx, opts, f, op, subject, reg, paths, acts, rec, built, list), resolved)
}

// stepTo is the step once the target is compiled and filed: the from bundle, the step, the
// host check and containerlab's plan, the rules, then the dry run's report or the run. list
// is what the command has found so far, warnings alone until the host check, whose
// refusals a dry run goes on beside. Every document stepTo ends with carries it: those
// built from list (finish's, the dry run's report, the run's) by construction, and a
// failure's, built fresh, through withFound.
func stepTo(ctx context.Context, opts *options, f *stepFlags, op string, subject *findings.Subject, reg *psp.Registry,
	paths lab.Paths, acts *lab.Activities, rec *wire.TwinRecord, built stages.PlanStage, list findings.List) error {
	// list as it stands when the failure is met, not as it was passed.
	failed := func(err error) error { return withFound(err, list) }

	// The bundle the twin was built from, out of the store, never re-resolved.
	store := bundle.NewDirStore(paths.Bundles)
	held, err := store.Has(ctx, rec.BundleID)
	if err != nil {
		return failed(failAt(op, subject, findings.StepResolve, rec.BundleID, "reading bundle %s from the store: %v", rec.BundleID, err))
	}
	if !held {
		list.AddStep(findings.Rejection, findings.StepResolve, findings.RuleStepBundleMissing, rec.BundleID, fmt.Sprintf(
			"the record names bundle %s, which the store under %s does not hold; a step starts from the bundle the twin "+
				"was built from and cannot be computed without it; fylgja twin destroy and create again", rec.BundleID, paths.Bundles))
		return finish(op, subject, list)
	}
	files, err := bundle.LoadFiles(store.Path(rec.BundleID))
	if err != nil {
		return failed(failAt(op, subject, findings.StepResolve, rec.BundleID, "reading bundle %s from the store: %v", rec.BundleID, err))
	}
	from := step.Bundle{ID: rec.BundleID, Files: files}

	// The step, as stage plan prints it.
	s, err := step.Diff(from, *built.Bundle)
	if err != nil {
		return failed(failAt(op, subject, findings.StepCompare, rec.BundleID, "%v", err))
	}
	pair := step.Between(rec.Stage.Name(), built.Ref.String(), s)
	opts.note("%s", pair.Text())
	diff, err := json.Marshal(pair)
	if err != nil {
		return failed(failAt(op, subject, findings.StepCompare, rec.BundleID, "%v", err))
	}

	// The host for the twin after the step, without the two refusals that name the twin
	// itself (M4's withoutPresence), as the run's step 2 checks it.
	toPath := store.Path(built.Bundle.ID)
	plan, err := lab.CheckHost(ctx, acts, wire.CheckHostInput{BundlePath: toPath, BundleID: built.Bundle.ID})
	if err != nil {
		return failed(failAt(op, subject, findings.StepHostCheck, findings.StepHostCheck, "host check: %s", activityMessage(err)))
	}
	checked := provision.WithoutPresence(plan.Findings)
	list = append(list, checked...)
	if checked.Rejected() && !f.dryRun {
		return finish(op, subject, list)
	}

	// containerlab's own plan for the target, against the twin directory's lab state, from
	// the store's copy: nothing of the twin directory is read but that state.
	lifecycle, err := acts.Clab.DeployPlan(ctx, filepath.Join(toPath, compiler.TopologyFile), paths.Twin)
	if err != nil {
		return failed(failAt(op, subject, findings.StepCompare, "lab "+wire.LabName, "containerlab's plan: %v", err))
	}

	in, packages, err := stepInput(f, rec, from, built, toPath, s, diff, plan, lifecycle, reg, opts.version())
	if err != nil {
		return failed(failAt(op, subject, findings.StepCompare, rec.BundleID, "%v", err))
	}
	rules := provision.PlanRules{Plan: lifecycle, Target: packages.target, From: packages.from, Changed: in.Changed,
		AllowRestart: f.allowRestart}.Findings()
	list = append(list, rules...)
	opts.note("%s", reconcileLine(lifecycle, packages.target))
	opts.note("%s", pushLine(in.PushPlan, plan.Nodes))

	if f.dryRun {
		opts.note("wait: after the record, until the twin conforms, at most %s", time.Duration(in.WaitS)*time.Second)
		return stepDryRun(opts, op, subject, in, lifecycle, plan, toPath, list)
	}
	if rules.Rejected() {
		return finish(op, subject, list)
	}
	return runStep(ctx, opts, op, subject, in, list)
}

// rehearsalHolds refuses a step beside a rehearsal in flight, run.in_flight naming it, before
// the host or Infrahub is read: during the baseline's provision the host holds a lab and no
// record, and after a diverged stage a diverged twin, each of which the step would otherwise
// refuse under a rule that calls the rehearsal's twin an orphan or diverged
// (contracts/rehearse-command.md; FR-007, FR-008). The workflow service is asked as the
// rehearsal's own holdingRun asks it; a dry run dials none, as twin create --dry-run does
// not, and StartStep refuses a provisioning or destroy run as before. nil when no rehearsal
// is running.
func rehearsalHolds(ctx context.Context, opts *options, op string, subject *findings.Subject) error {
	svc, err := opts.dial(ctx)
	if err != nil {
		return startFailure(op, subject, findings.StepStart, err)
	}
	defer svc.Close()
	runs, err := svc.InFlight(ctx)
	if err != nil {
		return startFailure(op, subject, findings.StepStart, err)
	}
	for _, r := range runs {
		if r.WorkflowID == provision.WorkflowRehearse {
			return &result{doc: provision.InFlightRefusal(r.WorkflowID, r.RunID).Document(op, subject)}
		}
	}
	return nil
}

// withFound carries list, what the command had found before it failed, onto the document
// err holds, first, as withStage carries a resolution's warnings onto a create's: a
// failure's document is built fresh (failAt's, startFailure's, followRun's), so without it
// a step that fails once its target is chosen would drop step.stage.skipped,
// stage.twin.moved and stage.main.moved. Only a failure passes through it, never a document
// built from list, so each finding is carried once.
func withFound(err error, list findings.List) error {
	var res *result
	if len(list) > 0 && errors.As(err, &res) {
		res.doc.Findings = append(append(findings.List{}, list...), res.doc.Findings...)
	}
	return err
}

// stepPackages are the support packages of both bundles' nodes as the step's rules read
// them.
type stepPackages struct {
	target, from []provision.NodePackage
}

// stepInput is the run's input from what the command decided, and both bundles' packages:
// the target's from the host check's plan, which read them from the registry; the from
// bundle's from its manifest, each node's package looked up in the registry by its id, since
// a merge package on either side refuses the step. Declared is each target node's
// package's fidelity.link_change, which the host check's plan does not carry.
func stepInput(f *stepFlags, rec *wire.TwinRecord, from step.Bundle, built stages.PlanStage, toPath string, s step.Step, diff []byte,
	plan wire.CheckHostResult, lifecycle wire.ReconcilePlan, reg *psp.Registry, version string) (provision.StepInput, stepPackages, error) {
	var packages stepPackages
	declared := map[string]string{}
	for _, n := range plan.Nodes {
		linkChange := ""
		if p, ok := reg.LookupID(n.PSPID); ok {
			linkChange = p.Fidelity.LinkChange
		}
		declared[n.Name] = linkChange
		packages.target = append(packages.target, provision.NodePackage{Node: n.Name, ID: n.PSPID, Mode: n.Push.Mode,
			LinkChange: linkChange})
	}
	var m compiler.Manifest
	if err := json.Unmarshal(from.Files[compiler.ManifestFile], &m); err != nil {
		return provision.StepInput{}, packages, fmt.Errorf("reading bundle %s's manifest: %w", rec.BundleID, err)
	}
	for _, n := range m.Nodes {
		if p, ok := reg.LookupID(n.PSP.ID); ok {
			packages.from = append(packages.from, provision.NodePackage{Node: n.Name, ID: n.PSP.ID, Mode: p.Config.Mode,
				LinkChange: p.Fidelity.LinkChange})
		}
	}

	// An unchanged step pushes nobody, as the run does.
	pushes := []step.NodePush{}
	if !s.Unchanged {
		pushes = step.PushPlan(s, step.Lifecycle{Restarted: lifecycle.Restarted, Recreated: lifecycle.Recreated,
			Created: lifecycle.Added, Removed: lifecycle.Deleted})
	}
	r := built.Resolved
	return provision.StepInput{
		From:         wire.StepSide{Stage: rec.Stage, BundleID: rec.BundleID, At: rec.Provenance.At},
		To:           wire.StepSide{Stage: r.StageRef(), BundleID: built.Bundle.ID, At: r.At, Branch: r.Branch},
		ObservedAt:   built.ObservedAt,
		ToBundlePath: toPath,
		Diff:         diff,
		Unchanged:    s.Unchanged,
		Plan:         lifecycle,
		PushPlan:     pushes,
		Changed:      provision.ChangesOf(s),
		AllowRestart: f.allowRestart,
		Declared:     declared,
		WaitS:        f.waitS,
		Version:      version,
	}, packages, nil
}

// stepWait is --wait's budget in seconds, verify.DefaultBudget's when the flag is left out,
// or its refusal as verify.wait.invalid, exit 2, at step start, before any connection: an
// empty value, one that is not a duration, and a
// negative one. A part of a second counts as a whole one, so the budget is never shorter
// than asked; --wait 0 reads once.
func stepWait(op string, subject *findings.Subject, f *stepFlags) (int, error) {
	if !f.waitGiven {
		return int(verify.DefaultBudget / time.Second), nil
	}
	refuse := func(format string, args ...any) error {
		doc := findings.RuleErrorDocument(op, subject, findings.RuleVerifyWaitInvalid, "--wait", fmt.Sprintf(format, args...))
		doc.Findings[0].Step = findings.StepStart
		return &result{doc: doc}
	}
	if f.wait == "" {
		return 0, refuse("--wait= is empty; give a duration such as --wait=2m, or leave --wait out for the default %s",
			verify.DefaultBudget)
	}
	d, err := time.ParseDuration(f.wait)
	switch {
	case err != nil:
		return 0, refuse("--wait=%s is not a duration: %v", f.wait, err)
	case d < 0:
		return 0, refuse("--wait=%s is not a duration: a budget cannot be negative", f.wait)
	}
	return int(math.Ceil(d.Seconds())), nil
}

// stepDryRun is the step's dry run: M2's memory: and host: lines from the host check,
// and the verdict over the host check's refusals and the rules'; the document carries
// dry_run over the target's nodes, with no follow, and the step block with no run fields.
func stepDryRun(opts *options, op string, subject *findings.Subject, in provision.StepInput, lifecycle wire.ReconcilePlan,
	plan wire.CheckHostResult, toPath string, list findings.List) error {
	artifacts, lossy, err := manifestSummary(toPath)
	if err != nil {
		return withFound(failAt(op, subject, findings.StepHostCheck, findings.StepHostCheck, "host check: %v", err), list)
	}
	block, verdict := dryRunBlock(plan, artifacts, lossy, list)
	printDryRunHost(opts, plan)
	opts.note("verdict: %s", verdict)

	doc := findings.NewDocument(op, subject, list)
	doc.BundleID = in.To.BundleID
	doc.DryRun = block
	doc.Step = provision.StepBlockOf(in, lifecycle)
	return &result{doc: doc}
}

// runStep starts the step run, follows it until it closes and reports how it ended. The run
// is started and followed as a provisioning run is: an interrupt before the start abandons
// it, the first after asks the run to cancel and keeps waiting for its record, and a second
// stops waiting. The command's own warnings lead the document, and the run's
// repeats of them are dropped: the run checks the host and the plan again as second locks.
// They lead a start's failure and a failure met while following too.
func runStep(ctx context.Context, opts *options, op string, subject *findings.Subject, in provision.StepInput,
	list findings.List) error {
	svc, err := opts.dial(ctx)
	if err != nil {
		return withFound(startFailure(op, subject, findings.StepStart, err), list)
	}
	defer svc.Close()

	interrupts, err := opts.c.startFrame(provision.WorkflowStep)
	if err != nil {
		return withFound(goneBeforeStart(op, subject, provision.WorkflowStep, err), list)
	}

	runID, interrupted, err := startRun(ctx, provision.WorkflowStep,
		func(ctx context.Context) (string, error) { return svc.StartStep(ctx, in) }, interrupts)
	if err != nil {
		return withFound(startFailure(op, subject, findings.StepStart, err), list)
	}
	subject.RunID = runID
	opts.c.runFrame(provision.WorkflowStep, runID)

	res, err := followRun(ctx, opts, svc, op, subject, provision.WorkflowStep, runID, interrupts, interrupted,
		func(ctx context.Context) (provision.StepResult, error) { return svc.ResultOfStep(ctx, runID) },
		"run cancelled; waiting for its record", nil)
	if err != nil {
		return withFound(err, list)
	}
	if line := stepClosing(in, res); line != "" {
		opts.note("%s", line)
	}
	doc := provision.StepDocument(subject, in, res)
	doc.Findings = append(append(findings.List{}, list...), withoutRepeats(res.Findings, list)...)
	return &result{doc: doc}
}

// withoutRepeats is the run's findings without those the command already reported, by
// step, rule, object and message (M4's withoutRepeatedHostCheck, over every step).
func withoutRepeats(run, reported findings.List) findings.List {
	type key struct{ step, rule, object, message string }
	seen := map[key]bool{}
	for _, f := range reported {
		seen[key{f.Step, f.Rule, f.Object, f.Message}] = true
	}
	out := findings.List{}
	for _, f := range run {
		if !seen[key{f.Step, f.Rule, f.Object, f.Message}] {
			out = append(out, f)
		}
	}
	return out
}

// reconcileLine is what containerlab's plan does to each node it touches, with its reason
// and the node's package's declaration beside it, or that it applies nothing
// (contracts/cli.md): "reconcile: restart e1 (added link; <e1's package> declares restart);
// live s1 (added link; <s1's package> declares live)". A created node declares nothing: no link
// change of its is at stake. A deleted node is named last.
func reconcileLine(plan wire.ReconcilePlan, packages []provision.NodePackage) string {
	if plan.Empty() {
		return "reconcile: nothing to apply"
	}
	byNode := map[string]provision.NodePackage{}
	for _, p := range packages {
		byNode[p.Node] = p
	}
	var parts []string
	for _, n := range plan.Nodes() {
		var why []string
		if n.Reason != "" {
			why = append(why, n.Reason)
		}
		if p, ok := byNode[n.Node]; ok && p.LinkChange != "" && n.Reported != wire.ReportedCreate {
			why = append(why, p.ID+" declares "+p.LinkChange)
		}
		part := n.Reported + " " + n.Node
		if len(why) > 0 {
			part += " (" + strings.Join(why, "; ") + ")"
		}
		parts = append(parts, part)
	}
	for _, n := range plan.Deleted {
		parts = append(parts, "delete "+n)
	}
	return "reconcile: " + strings.Join(parts, "; ")
}

// pushLine is who the step pushes and why, and who it leaves untouched (contracts/cli.md):
// "push: e1 (artifact, restarted); s1 (artifact, bootstrap); e2 untouched", or "push:
// nobody".
func pushLine(pushes []step.NodePush, nodes []wire.NodePlan) string {
	if len(pushes) == 0 {
		return "push: nobody"
	}
	pushed := map[string]bool{}
	var parts []string
	for _, p := range pushes {
		pushed[p.Node] = true
		parts = append(parts, fmt.Sprintf("%s (%s)", p.Node, strings.Join(p.Reasons, ", ")))
	}
	var untouched []string
	for _, n := range nodes {
		if !pushed[n.Name] {
			untouched = append(untouched, n.Name)
		}
	}
	line := "push: " + strings.Join(parts, "; ")
	if len(untouched) > 0 {
		line += "; " + strings.Join(untouched, ", ") + " untouched"
	}
	return line
}

// stepClosing is the run's closing line (contracts/cli.md), or "" for a run that ended
// before its stage, whose findings say why: stepped, with the times; unchanged; or diverged,
// naming the phase, each node's push, and the stage the twin is still at. After M11's
// line and its timings comes how the wait after the record ended, when it ran.
func stepClosing(in provision.StepInput, res provision.StepResult) string {
	line := m11Closing(in, res)
	if line == "" || res.Wait == nil {
		return line
	}
	return line + "; " + waitClause(*res.Wait)
}

// waitClause is how the step's wait ended, in the words the warning verify.wait.unsettled
// begins with (contracts/cli.md, twin step --wait).
func waitClause(w wire.StepWait) string {
	switch w.Outcome {
	case wire.WaitSettled:
		return "settled after " + seconds(w.AfterS)
	case wire.WaitExpired:
		return fmt.Sprintf("wait expired after %s with %s failing", seconds(w.AfterS), plural(len(w.Failing), "assertion"))
	case wire.WaitCancelled:
		return "wait cancelled after " + seconds(w.AfterS)
	}
	return "wait could not complete"
}

// m11Closing is M11's closing line, unchanged by the wait.
func m11Closing(in provision.StepInput, res provision.StepResult) string {
	to, from := in.To.Stage.Name(), in.From.Stage.Name()
	switch {
	case res.Phase != "":
		return fmt.Sprintf("diverged towards stage %s (bundle %s) at phase %s: %s; the twin is up at stage %s (bundle %s); "+
			"fylgja twin destroy clears it", to, shortID(in.To.BundleID), res.Phase, provision.Landed(res.PushPlan, " "),
			from, shortID(in.From.BundleID))
	case res.Outcome == provision.StepUnchanged:
		return fmt.Sprintf("unchanged; the record moves to stage %s (bundle %s) in %s", to, shortID(in.To.BundleID),
			seconds(res.Timings.WholeS))
	case res.Outcome == provision.StepStepped:
		line := fmt.Sprintf("stepped to stage %s (bundle %s) in %s", to, shortID(in.To.BundleID), seconds(res.Timings.WholeS))
		var parts []string
		if t := res.Timings.ReconcileS; t != nil {
			parts = append(parts, "reconcile "+seconds(*t))
		}
		if s := perNode(res.Timings.Readiness); s != "" {
			parts = append(parts, "readiness "+s)
		}
		if s := perNode(res.Timings.Push); s != "" {
			parts = append(parts, "push "+s)
		}
		if len(parts) > 0 {
			line += ": " + strings.Join(parts, "; ")
		}
		return line
	}
	return ""
}
