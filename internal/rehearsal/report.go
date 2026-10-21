package rehearsal

import (
	"fmt"
	"sort"
	"strings"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// The rehearsal run's outcomes, as its result says them (data-model §6).
const (
	OutcomeOK             = "ok"              // every rehearsed stage passed
	OutcomeStageFailed    = "stage_failed"    // a stage failed: diverged, or a finding the baseline did not have
	OutcomeStageError     = "stage_error"     // a stage's step could not run, or its wait could not complete
	OutcomeBaselineFailed = "baseline_failed" // the baseline's provision ended failed, and cleaned up
	OutcomeCut            = "cut"             // the deadline passed
	OutcomeCancelled      = "cancelled"       // the run itself was cancelled
	OutcomeRejected       = "rejected"        // the baseline's provision could not start, a run holding its id: nothing touched, no destroy
)

// provisionReady is the provision workflow's outcome for a twin built and recorded.
const provisionReady = "ready"

// Input is what the server decided before the run (data-model §1, §7): the proposed
// change, when its stages were resolved, the deadline and the ceiling in seconds, the dead
// rehearsal whose twin was reclaimed first, and every stage of the plan in order with the
// role the rehearsal gives it. The server fills it from the run's input, so this package
// imports no workflow code.
type Input struct {
	ProposedChange findings.StageChange
	ResolvedAt     string
	DeadlineS      int
	CeilingS       int
	Reclaimed      *findings.RehearsalReclaim
	Stages         []Stage
}

// Stage is one stage of the plan as the server resolved, read and compiled it: its
// reference and the mark's label and description, where its at came from, the branch and
// the at it resolved to (empty when it did not), its bundle (empty when refused), the role
// the rehearsal gives it, and the plan's findings at resolve, read and compile.
type Stage struct {
	Ref, Label, Description, AtSource string
	Branch, At                        string
	BundleID                          string
	Role                              string
	Findings                          findings.List
}

// Result is what the run came to, as the server read it once the run closed: the run's
// outcome, the run, its whole time, each stage it reached and the destroy's cleanup. The
// zero Result is a rehearsal refused before any run.
type Result struct {
	Outcome string
	Run     *findings.ShowRef
	UsedS   float64
	Stages  []StageResult
	Destroy *findings.CleanupBlock
}

// StageResult is one stage the run reached: its verdict, the child it ran (the baseline's
// provision, or a rehearsed stage's step), its wait, the wait's last read counted, the
// wait's findings the baseline's did not have, the child's own findings, and the stage's
// whole time on the run's clock.
type StageResult struct {
	Ref         string
	Verdict     Verdict
	Provision   *Provision
	Step        *StepRun
	Wait        *wire.StepWait
	Counts      *wire.VerifyCounts
	NewFindings []wire.StepFinding
	Findings    findings.List
	TookS       float64
}

// Provision is the baseline's provision child as it ended: its outcome, its run, the step it
// stopped at when it did not end ready, and its cleanup when it made one.
type Provision struct {
	Outcome string
	RunID   string
	Step    string
	Cleanup *findings.CleanupBlock
}

// StepRun is a rehearsed stage's step child as it ended: its outcome and run, the phase a
// step that touched the host stopped at, the step the run stopped at when it did not end
// stepped or unchanged, the nodes containerlab's plan restarted, recreated or created, each
// push of its plan with its outcome, and its timings.
type StepRun struct {
	Outcome, Phase, Step          string
	RunID                         string
	Restarted, Recreated, Created []string
	Pushed                        []wire.StepPush
	Timings                       wire.StepTimings
}

// Build is the report's rehearsal block (research R-10; rehearsal.schema.json): every
// stage of the plan in order, with the role the rehearsal gave it and what the run did at
// it. A stage the run did not reach, absent from the result or listed there as not reached,
// is not reached, whatever role it was given; one the plan refused stays refused. Each
// stage's findings are the plan's, the child's, its wait's failing assertions as warnings
// (StageFindings), and the rehearsal's own: the stage that failed carries
// rehearsal.stage.failed, the one that could not be rehearsed rehearsal.stage.error, or
// rehearsal.deadline.cut when the deadline passed (an interrupt's is the server's
// run.cancelled), and a baseline not built rehearsal.baseline.failed. The baseline block is
// set once the baseline was built, its findings its wait's failing assertions; the commands
// that reproduce a failure are Reproduce's.
func Build(in Input, res Result) findings.RehearsalBlock {
	b := findings.RehearsalBlock{
		ProposedChange: in.ProposedChange, ResolvedAt: in.ResolvedAt, DeadlineS: in.DeadlineS, CeilingS: in.CeilingS,
		UsedS: res.UsedS, Reclaimed: in.Reclaimed, Run: res.Run, Destroy: res.Destroy,
		Stages: make([]findings.RehearsalStage, 0, len(in.Stages)),
	}
	reached := make(map[string]StageResult, len(res.Stages))
	for _, r := range res.Stages {
		reached[r.Ref] = r
	}
	var finished []string // each stage the run finished before the one it stopped at, and its time
	for _, s := range in.Stages {
		st := findings.RehearsalStage{Ref: s.Ref, Label: s.Label, Description: s.Description, AtSource: s.AtSource,
			Branch: s.Branch, At: s.At, Role: s.Role, Findings: append(findings.List{}, s.Findings...)}
		if s.BundleID != "" {
			id := s.BundleID
			st.BundleID = &id
		}
		r, ok := reached[s.Ref]
		switch {
		case s.Role == RoleRefused:
			st.Verdict = string(VerdictRefused)
		case !ok, r.Verdict == VerdictNotReached:
			// The run lists each stage after the one that stopped it as not reached; a result
			// that leaves them out says the same.
			st.Role, st.Verdict = RoleNotReached, string(VerdictNotReached)
		default:
			st.Verdict = string(r.Verdict)
			st.Provision = provisionBlock(r.Provision)
			st.Step = stepBlock(r.Step)
			if w := r.Wait; w != nil {
				st.Wait = &findings.RehearsalWait{Outcome: w.Outcome, BudgetS: w.BudgetS, Reads: w.Reads, AfterS: w.AfterS}
			}
			st.Verify = r.Counts
			st.NewFindings = sortedFailing(r.NewFindings)
			st.TookS = r.TookS
			st.Findings = append(st.Findings, r.Findings...)
			st.Findings = append(st.Findings, StageFindings(s.Ref, r.Wait)...)
			if s.Role == RoleBaseline && r.Provision != nil && r.Provision.Outcome == provisionReady {
				b.Baseline = &findings.RehearsalBaseline{Ref: s.Ref, Findings: failingOf(r.Wait)}
			}
			st.Findings = append(st.Findings, ownFindings(st, r, res.Outcome, in.DeadlineS, finished)...)
			finished = append(finished, fmt.Sprintf("%s took %.1fs", s.Ref, r.TookS))
		}
		b.Stages = append(b.Stages, st)
	}
	b.Reproduce = Reproduce(b)
	return b
}

// ownFindings are the rehearsal's own findings at a stage it reached, by its verdict and the
// run's outcome.
func ownFindings(st findings.RehearsalStage, r StageResult, outcome string, deadlineS int, finished []string) findings.List {
	var l findings.List
	switch {
	case st.Role == RoleBaseline && outcome == OutcomeBaselineFailed:
		l.AddStep(findings.Rejection, findings.StepProvision, findings.RuleRehearsalBaselineFailed, st.Ref,
			fmt.Sprintf("the baseline %s could not be built: %s", st.Ref, provisionEnded(st.Provision)))
	case st.Verdict == string(VerdictFailed):
		step, why := findings.StepObserve, "its wait holds a finding the baseline's did not: "+findingsText(st.NewFindings)
		if s := st.Step; s != nil && s.Outcome == wire.StepDiverged {
			step, why = orStep(s.Phase, findings.StepObserve), divergence(s)
		}
		l.AddStep(findings.Rejection, step, findings.RuleRehearsalStageFailed, st.Ref, why)
	case st.Verdict == string(VerdictError) && outcome == OutcomeCut:
		done := "no stage had finished"
		if len(finished) > 0 {
			done = strings.Join(finished, ", ")
		}
		l.AddStep(findings.Rejection, stepReached(r), findings.RuleRehearsalDeadlineCut, st.Ref,
			fmt.Sprintf("the deadline of %ds passed at stage %s: %s", deadlineS, st.Ref, done))
	case st.Verdict == string(VerdictError) && outcome != OutcomeCancelled:
		l.AddStep(findings.Rejection, stepReached(r), findings.RuleRehearsalStageError, st.Ref, errorWhy(st))
	}
	return l
}

// stepReached is the step a stage that could not be rehearsed stopped at: its child's, the
// phase it stopped at, or observe when its child ended and its wait did not.
func stepReached(r StageResult) string {
	switch {
	case r.Step != nil && r.Step.Step != "":
		return r.Step.Step
	case r.Step != nil && r.Step.Phase != "":
		return r.Step.Phase
	case r.Provision != nil && r.Provision.Outcome != provisionReady:
		return orStep(r.Provision.Step, findings.StepProvision)
	case r.Step != nil || r.Provision != nil:
		return findings.StepObserve
	}
	return findings.StepStart
}

func orStep(step, otherwise string) string {
	if step == "" {
		return otherwise
	}
	return step
}

// StageFindings are a stage's wait's failing assertions as warnings, each object prefixed
// with the stage's reference (research R-08): a rejection would end the document rejected,
// and the baseline's fail nothing. A new finding fails its stage through
// rehearsal.stage.failed, which names it.
func StageFindings(ref string, wait *wire.StepWait) findings.List {
	if wait == nil {
		return nil
	}
	var l findings.List
	for _, f := range wait.Failing {
		l.AddStep(findings.Warning, findings.StepObserve, f.Rule, ref+": "+f.Object, f.Message)
	}
	return l
}

// Findings are every stage's findings in the stages' order: the block's share of the
// document's own list.
func Findings(b findings.RehearsalBlock) findings.List {
	var l findings.List
	for _, s := range b.Stages {
		l = append(l, s.Findings...)
	}
	return l
}

// Reproduce is the commands that reproduce a failed stage by hand on the same stages, in
// order (FR-015): the create from the baseline, a step with --allow-restart to each
// rehearsed stage up to and including the failed one, the verify and the destroy. None when
// no stage failed: a stage the run could not rehearse taught nothing to reproduce.
func Reproduce(b findings.RehearsalBlock) []string {
	failed := -1
	for i, s := range b.Stages {
		if s.Verdict == string(VerdictFailed) {
			failed = i
			break
		}
	}
	if failed < 0 {
		return []string{}
	}
	var out []string
	for _, s := range b.Stages[:failed+1] {
		switch s.Role {
		case RoleBaseline:
			out = append(out, "fylgja twin create --stage "+shellWord(s.Ref))
		case RoleRehearsed:
			out = append(out, "fylgja twin step --stage "+shellWord(s.Ref)+" --allow-restart")
		}
	}
	return append(out, "fylgja twin verify", "fylgja twin destroy")
}

// shellWord is a reference as a shell reads it: as it is when every character is one no
// shell interprets, and single-quoted otherwise, since a label is any characters but a
// slash and white space.
func shellWord(s string) string {
	if s != "" && strings.Trim(s, shellSafe) == "" {
		return s
	}
	return "'" + strings.ReplaceAll(s, "'", `'\''`) + "'"
}

// shellSafe are the characters no shell interprets in a word.
const shellSafe = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._/@%+=:,-"

// StageLines are the text's one line per stage after the run (contracts/rehearse-command.md,
// "The text"): what the run did at the stage, its wait and its counts, then its verdict.
//
//	stage change-1/branch-point: refused (contract.node.missing)
//	stage change-1/seeded: created; settled after 3.2s (2 reads); 15 held, 0 failed, 0 skipped; baseline
//	stage change-1/third-link: stepped in 4.5s (push n1 2.5s, n3 2.6s); settled after 6.1s (4 reads); 19 held, 0 failed, 0 skipped; passed
//	stage change-1/bad-port: diverged at phase push: restarted n3 61.2s; landed n3; not landed n1 (push.refused); …; failed
//	stage change-1/head: not reached
func StageLines(b findings.RehearsalBlock) []string {
	out := make([]string, 0, len(b.Stages))
	for _, s := range b.Stages {
		var parts []string
		switch Verdict(s.Verdict) {
		case VerdictRefused:
			parts = []string{refusedText(s)}
		case VerdictNotReached:
			parts = []string{"not reached"}
		default:
			parts = append(parts, childText(s))
			if w := s.Wait; w != nil {
				parts = append(parts, waitText(w))
			}
			if s.Verify != nil {
				parts = append(parts, countsText(*s.Verify))
			}
			parts = append(parts, verdictPhrase(s))
		}
		out = append(out, "stage "+s.Ref+": "+strings.Join(nonEmpty(parts), "; "))
	}
	return out
}

// Closing is the text's last line, from the document and its block: the status, what the
// rehearsal came to, the twin's end, and on ok the time used against the deadline; on a
// failure the commands that reproduce it follow, one per line, indented. A run whose end was
// not read says it was started, why its end was not read, and that it goes on to its
// destroy, and never what its stages came to (FR-021).
//
//	rehearsal ok: 3 stages rehearsed, every one passed; the twin is destroyed; 118.4s of the 1980s deadline
//	rehearsal nonconforming: stage change-1/bad-port failed at phase push; the twin is destroyed; reproduce it by hand:
//	  fylgja twin create --stage change-1/seeded
//	rehearsal error: run fylgja-rehearse 01a1… was started and its end was not read (waiting for run 01a1…: …); it goes on to its destroy, and fylgja twin show says where it is
func Closing(doc *findings.Document) string {
	status := doc.Status
	if doc.Rehearsal == nil {
		return fmt.Sprintf("rehearsal %s: nothing was started", status)
	}
	b := *doc.Rehearsal
	var parts []string
	switch {
	case b.Run == nil:
		parts = []string{whatItCameTo(b, status)}
	case endUnread(b, status):
		parts = []string{fmt.Sprintf("run %s %s was started and its end was not read (%s)", b.Run.WorkflowID, b.Run.RunID,
			orNone(whyUnread(doc))), "it goes on to its destroy, and fylgja twin show says where it is"}
	case b.Destroy == nil && status == findings.StatusRejected:
		parts = []string{whatItCameTo(b, status), "no destroy was needed"}
	default:
		parts = []string{whatItCameTo(b, status), destroyText(b.Destroy)}
	}
	if status == findings.StatusOK {
		parts = append(parts, fmt.Sprintf("%.1fs of the %ds deadline", b.UsedS, b.DeadlineS))
	}
	line := fmt.Sprintf("rehearsal %s: %s", status, strings.Join(nonEmpty(parts), "; "))
	if len(b.Reproduce) == 0 {
		return line
	}
	return line + "; reproduce it by hand:\n  " + strings.Join(b.Reproduce, "\n  ")
}

// whatItCameTo is the closing line's account of the stages: nothing started, a run refused at
// its baseline's start, the stage that failed or could not be rehearsed, the baseline not
// built, or every stage passed.
func whatItCameTo(b findings.RehearsalBlock, status findings.Status) string {
	switch {
	case b.Run == nil:
		return "nothing was started"
	case !reachedAny(b) && status == findings.StatusRejected:
		return "the run touched nothing, since a run already holds the id of its baseline's provision"
	}
	built := 0
	for _, s := range b.Stages {
		if carries(s.Findings, findings.RuleRehearsalBaselineFailed) {
			return fmt.Sprintf("the baseline %s could not be built: %s", s.Ref, provisionEnded(s.Provision))
		}
		switch Verdict(s.Verdict) {
		case VerdictFailed:
			if st := s.Step; st != nil && st.Outcome == wire.StepDiverged {
				return fmt.Sprintf("stage %s failed at phase %s", s.Ref, st.Phase)
			}
			return fmt.Sprintf("stage %s failed: %s", s.Ref, findingsText(s.NewFindings))
		case VerdictError:
			return errorAt(s, b.DeadlineS)
		}
		if s.Role == RoleBaseline || s.Role == RoleRehearsed {
			built++
		}
	}
	if built == 1 {
		return "the baseline alone was built and verified, and no step was rehearsed"
	}
	return fmt.Sprintf("%d stages rehearsed, every one passed", built)
}

// endUnread is whether the block is a started run's whose end was not read: the answer was lost
// waiting for its result, or the operator's second interrupt stopped waiting. Its block names
// the run and nothing the answer did not learn: no stage reached, no destroy (FR-021).
func endUnread(b findings.RehearsalBlock, status findings.Status) bool {
	return b.Run != nil && b.Destroy == nil && !reachedAny(b) && status != findings.StatusRejected
}

// unfiled are the document's rejections that no stage of its block filed: on a run whose end
// was not read, why it was not.
func unfiled(doc *findings.Document) findings.List {
	type key struct{ rule, step, object, message string }
	filed := map[key]bool{}
	if doc.Rehearsal != nil {
		for _, f := range Findings(*doc.Rehearsal) {
			filed[key{f.Rule, f.Step, f.Object, f.Message}] = true
		}
	}
	var out findings.List
	for _, f := range doc.Findings {
		if f.Severity == findings.Rejection && !filed[key{f.Rule, f.Step, f.Object, f.Message}] {
			out = append(out, f)
		}
	}
	return out
}

// whyUnread is why a run's end was not read: unfiled's messages.
func whyUnread(doc *findings.Document) []string {
	var out []string
	for _, f := range unfiled(doc) {
		out = append(out, f.Message)
	}
	return out
}

// reachedAny is whether the run reached a stage: false in a block refused before any run, in
// one whose run was refused at its baseline's start, and in one whose end was not read.
func reachedAny(b findings.RehearsalBlock) bool {
	for _, s := range b.Stages {
		if s.Role == RoleBaseline || s.Role == RoleRehearsed {
			return true
		}
	}
	return false
}

// errorAt is why the rehearsal stopped at a stage it could not rehearse: the deadline, the
// stage's own error, or the run's cancellation.
func errorAt(s findings.RehearsalStage, deadlineS int) string {
	switch {
	case carries(s.Findings, findings.RuleRehearsalDeadlineCut):
		return fmt.Sprintf("the deadline of %ds passed at stage %s", deadlineS, s.Ref)
	case carries(s.Findings, findings.RuleRehearsalStageError):
		return fmt.Sprintf("stage %s could not be rehearsed: %s", s.Ref, errorWhy(s))
	}
	return "the run was cancelled at stage " + s.Ref
}

// destroyText is the twin's end: destroyed, or what the destroy left and what clears it.
func destroyText(c *findings.CleanupBlock) string {
	switch {
	case c == nil:
		return "the destroy did not report"
	case len(c.Remaining) > 0:
		return fmt.Sprintf("the destroy left %s; twin destroy clears it", strings.Join(c.Remaining, ", "))
	}
	return "the twin is destroyed"
}

// childText is what the stage's child did: the baseline created or not built, the step's
// outcome with its time, the nodes containerlab's plan touched and each push's time.
func childText(s findings.RehearsalStage) string {
	if p := s.Provision; p != nil {
		if p.Outcome == provisionReady {
			return "created"
		}
		return "not built: " + provisionEnded(p)
	}
	st := s.Step
	if st == nil {
		return ""
	}
	switch st.Outcome {
	case wire.StepStepped:
		return fmt.Sprintf("stepped in %.1fs", st.Timings.WholeS) + parenthesised(touched(st))
	case wire.StepUnchanged:
		return fmt.Sprintf("unchanged in %.1fs", st.Timings.WholeS)
	case wire.StepDiverged:
		return divergence(st, lifecycle(st)...)
	case outcomeCancelled:
		if st.Phase == "" {
			return "cancelled before its stage"
		}
		return "cancelled at phase " + st.Phase
	case outcomeRejected:
		return "rejected"
	}
	return "could not run"
}

// touched is the nodes containerlab's plan restarted, recreated or created, and each push
// with its time.
func touched(st *findings.RehearsalStep) []string {
	out := lifecycle(st)
	var pushes []string
	for _, p := range st.Pushed {
		if p.TookS != nil {
			pushes = append(pushes, fmt.Sprintf("%s %.1fs", p.Node, *p.TookS))
		} else {
			pushes = append(pushes, p.Node)
		}
	}
	if len(pushes) > 0 {
		out = append(out, "push "+strings.Join(pushes, ", "))
	}
	return out
}

// lifecycle is the nodes containerlab's plan restarted, recreated or created, by verb, each
// restarted or recreated node with the seconds its readiness took, as twin show words a
// step's readiness, and alone when the step was cut before its readiness:
//
//	restarted n3 61.2s; recreated n1 70.4s; created n4
func lifecycle(st *findings.RehearsalStep) []string {
	var out []string
	for _, l := range []struct {
		verb  string
		nodes []string
		timed bool
	}{{"restarted", st.Restarted, true}, {"recreated", st.Recreated, true}, {"created", st.Created, false}} {
		if len(l.nodes) == 0 {
			continue
		}
		named := make([]string, len(l.nodes))
		for i, n := range l.nodes {
			named[i] = n
			if s, ok := st.Timings.Readiness[n]; ok && l.timed {
				named[i] = fmt.Sprintf("%s %.1fs", n, s)
			}
		}
		out = append(out, l.verb+" "+strings.Join(named, ", "))
	}
	return out
}

func parenthesised(parts []string) string {
	if len(parts) == 0 {
		return ""
	}
	return " (" + strings.Join(parts, "; ") + ")"
}

// divergence is a diverged step's why: the phase, then the parts before what landed (the
// stage line's nodes the plan restarted or recreated), and once a push was planned the
// nodes whose push landed and those whose did not, with each one's identifier.
//
//	diverged at phase push: landed n3; not landed n1 (push.refused)
//	diverged at phase push: restarted n3 61.2s; landed n3; not landed n1 (push.refused)
func divergence(st *findings.RehearsalStep, before ...string) string {
	line := "diverged at phase " + st.Phase
	parts := before
	if len(st.Pushed) > 0 {
		var landed, not []string
		for _, p := range st.Pushed {
			switch {
			case p.Outcome == wire.PushLanded:
				landed = append(landed, p.Node)
			case p.Rule != "":
				not = append(not, fmt.Sprintf("%s (%s)", p.Node, p.Rule))
			case p.Outcome == wire.PushNotAttempted:
				not = append(not, p.Node+" (not attempted)")
			default:
				not = append(not, p.Node)
			}
		}
		parts = append(parts, "landed "+orNone(landed))
		if len(not) > 0 {
			parts = append(parts, "not landed "+strings.Join(not, ", "))
		}
	}
	if len(parts) == 0 {
		return line
	}
	return line + ": " + strings.Join(parts, "; ")
}

// verdictPhrase is the line's last part: the verdict, with why on a stage that failed by a
// finding or could not be rehearsed, and nothing on a baseline not built, which its child's
// part says, whatever verdict the run gave it.
func verdictPhrase(s findings.RehearsalStage) string {
	if carries(s.Findings, findings.RuleRehearsalBaselineFailed) {
		return ""
	}
	switch Verdict(s.Verdict) {
	case VerdictFailed:
		if s.Step != nil && s.Step.Outcome == wire.StepDiverged {
			return "failed"
		}
		return "failed: " + findingsText(s.NewFindings)
	case VerdictError:
		switch {
		case carries(s.Findings, findings.RuleRehearsalDeadlineCut):
			return "error: the deadline passed"
		case carries(s.Findings, findings.RuleRehearsalStageError) && s.Provision != nil && s.Provision.Outcome != provisionReady:
			// The child's part says how the provision ended.
			return "error"
		case carries(s.Findings, findings.RuleRehearsalStageError):
			return "error: " + errorWhy(s)
		}
		return "error: the run was cancelled"
	}
	return s.Verdict
}

// errorWhy is why a stage could not be rehearsed, from its child and its wait.
func errorWhy(s findings.RehearsalStage) string {
	if p := s.Provision; p != nil && p.Outcome != provisionReady {
		return provisionEnded(p)
	}
	if st := s.Step; st != nil {
		switch st.Outcome {
		case outcomeRejected:
			return "its step was rejected"
		case outcomeError:
			return "its step could not run"
		case outcomeCancelled:
			if st.Phase == "" {
				return "its step was cancelled before its stage"
			}
			return "its step was cancelled at phase " + st.Phase
		}
	}
	if s.Step == nil && s.Provision == nil {
		return "its step did not run"
	}
	if w := s.Wait; w != nil {
		return fmt.Sprintf("its wait ended %s after %.1fs", w.Outcome, w.AfterS)
	}
	return "its wait did not run"
}

// provisionEnded is how a provision that did not end ready ended, and where.
func provisionEnded(p *findings.RehearsalProvision) string {
	if p == nil {
		return "its provision did not report"
	}
	line := "its provision ended " + p.Outcome
	if p.Step != "" {
		line += " at " + p.Step
	}
	return line
}

// refusedText is a refused stage's verdict with the identifiers that refused it.
func refusedText(s findings.RehearsalStage) string {
	seen := map[string]bool{}
	var rules []string
	for _, f := range s.Findings {
		if f.Severity == findings.Rejection && !seen[f.Rule] {
			seen[f.Rule] = true
			rules = append(rules, f.Rule)
		}
	}
	sort.Strings(rules)
	if len(rules) == 0 {
		return "refused"
	}
	return "refused (" + strings.Join(rules, ", ") + ")"
}

// waitText is how a wait ended: settled after 3.2s (2 reads).
func waitText(w *findings.RehearsalWait) string {
	reads := "reads"
	if w.Reads == 1 {
		reads = "read"
	}
	return fmt.Sprintf("%s after %.1fs (%d %s)", w.Outcome, w.AfterS, w.Reads, reads)
}

// countsText is the wait's last read counted over the three assertion kinds, the record's
// claims aside, which are not waited on: 19 held, 0 failed, 0 skipped, and the unread when
// a node was.
func countsText(c findings.VerifyCounts) string {
	held, failed, skipped, unread := 0, 0, 0, 0
	for _, k := range []findings.VerifyCount{c.HostName, c.PortEnabled, c.Neighbor} {
		held += k.Held
		failed += k.Failed
		if k.Skipped != nil {
			skipped += *k.Skipped
		}
		if k.Unread != nil {
			unread += *k.Unread
		}
	}
	line := fmt.Sprintf("%d held, %d failed, %d skipped", held, failed, skipped)
	if unread > 0 {
		line += fmt.Sprintf(", %d unread", unread)
	}
	return line
}

// findingsText names findings by rule and object: verify.neighbor n1:ethernet-1/3.
func findingsText(fs []findings.StepWaitFailing) string {
	out := make([]string, len(fs))
	for i, f := range fs {
		out[i] = f.Rule + " " + f.Object
	}
	return orNone(out)
}

func carries(l findings.List, rule string) bool {
	for _, f := range l {
		if f.Rule == rule {
			return true
		}
	}
	return false
}

func orNone(xs []string) string {
	if len(xs) == 0 {
		return "none"
	}
	return strings.Join(xs, ", ")
}

func nonEmpty(xs []string) []string {
	out := xs[:0:0]
	for _, x := range xs {
		if x != "" {
			out = append(out, x)
		}
	}
	return out
}

func provisionBlock(p *Provision) *findings.RehearsalProvision {
	if p == nil {
		return nil
	}
	return &findings.RehearsalProvision{Outcome: p.Outcome, Run: findings.ShowRef{WorkflowID: wire.ProvisionWorkflowID, RunID: p.RunID},
		Step: p.Step, Cleanup: p.Cleanup}
}

func stepBlock(s *StepRun) *findings.RehearsalStep {
	if s == nil {
		return nil
	}
	pushed := make([]findings.RehearsalPush, len(s.Pushed))
	for i, p := range s.Pushed {
		pushed[i] = findings.RehearsalPush{Node: p.Node, Outcome: p.Outcome, Rule: p.Rule, TookS: p.TookS}
	}
	return &findings.RehearsalStep{Outcome: s.Outcome, Run: findings.ShowRef{WorkflowID: wire.StepWorkflowID, RunID: s.RunID},
		Phase: s.Phase, Restarted: s.Restarted, Recreated: s.Recreated, Created: s.Created, Pushed: pushed,
		Timings: findings.StepTimingsBlock{ReconcileS: s.Timings.ReconcileS, Readiness: s.Timings.Readiness,
			Push: s.Timings.Push, WholeS: s.Timings.WholeS}}
}

// failingOf is a wait's failing assertions as the block keeps them, in the wait's order.
func failingOf(w *wire.StepWait) []findings.StepWaitFailing {
	if w == nil {
		return []findings.StepWaitFailing{}
	}
	out := make([]findings.StepWaitFailing, len(w.Failing))
	for i, f := range w.Failing {
		out[i] = findings.StepWaitFailing(f)
	}
	return out
}

// sortedFailing is new findings as the block keeps them, by rule then object.
func sortedFailing(fs []wire.StepFinding) []findings.StepWaitFailing {
	out := make([]findings.StepWaitFailing, len(fs))
	for i, f := range fs {
		out[i] = findings.StepWaitFailing(f)
	}
	sort.SliceStable(out, func(i, j int) bool {
		if out[i].Rule != out[j].Rule {
			return out[i].Rule < out[j].Rule
		}
		return out[i].Object < out[j].Object
	})
	return out
}
