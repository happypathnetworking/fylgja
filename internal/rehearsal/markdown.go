package rehearsal

import (
	"fmt"
	"slices"
	"sort"
	"strings"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/step"
)

// Caveat is the markdown's last line: what a twin's fidelity is (FR-014).
const Caveat = "*Fidelity is asserted, not measured: the twin's containers forward in software and keep their own timing.*"

// CommentMax is the longest markdown Infrahub keeps as a comment, in bytes: 1.11.2 refuses a
// text attribute when 3 and its UTF-8 length reach 4096 (infrahub/core/attribute.py,
// validate_string_length), and fylgja-twin posts the markdown as one comment's text.
const CommentMax = 4092

// Markdown is the rehearsal's report as GitHub-flavoured markdown (FR-014; research R-10;
// contracts/rehearse-command.md, "The markdown"), the comment a check posts on the proposed
// change: the heading naming Fylgja, the proposed change, its branch and the scope read
// (017); the run, when the stages were resolved, the status and the time used against the
// deadline and the ceiling; a table of the stages; a Mermaid drawing of the stages and what each step between
// them changed; on any status but ok the findings that say why; the stages as stage list
// prints them, since Infrahub's view does not show them; the warnings; the baseline's
// findings; on a failure the commands that reproduce it; and the fidelity caveat, last.
//
// It is rendered from the document and the plan's steps alone, both of which name what
// changed and never a line of it: the block holds no step's difference
// (rehearsal.schema.json leaves it to stage plan's), and the warnings and a refusal's
// reasons are the document's. A document with no block, refused before the proposed change
// was found, is the heading, the status, the findings and the caveat. A run that reached no
// stage says why in its run line: refused at its baseline's start, it touched nothing; and
// one whose end was not read was started, says why, and goes on to its destroy, its stages
// not read (FR-021). Every operator's
// string is escaped where it lands: as markdown text, in a table cell, in a code span, and
// in Mermaid's quoted labels, where ", < and > are #quot;, #lt; and #gt;.
//
// It is never longer than CommentMax, so that the comment is kept. A report that would be
// names each finding by its identifier and object alone, identical ones once with their
// count, since fylgja-twin's message, the report's text, holds every message; the table
// names each step by its outcome and its new findings by the first few; and the heading
// cuts a long proposed change's name with an ellipsis. Should that still be too long, whole
// sections are left out by an order of preference: the baseline's findings first, then the
// drawing, the warnings, the stages, the findings and the reproduce commands. They are kept
// from the last of it back while each still fits, so one earlier in it is kept when it fits
// once a later one was left out: a long drawing can go while the baseline's findings stay.
// The table is never left out: it gives
// each stage's reference and verdict alone, then, should even that be too long, as many
// stages as fit and how many are left out. A note before the caveat says what was
// shortened. The heading, the status and the caveat are always kept.
func Markdown(doc *findings.Document, steps []step.Pair) string {
	if md := join(parts(doc, steps, false)); len(md) <= CommentMax {
		return md
	}
	return fit(parts(doc, steps, true))
}

// part is a paragraph of the markdown, a section's title with its list, or a fenced block,
// which fit keeps or leaves out whole: rank 0 always, then the lowest rank first. name is
// what the note calls a part left out. The table, which fit shrinks rather than leaves out,
// carries its block for its shorter forms.
type part struct {
	text  string
	name  string
	rank  int
	table *tableOf
}

// tableOf is the table's block and whether its run's end was not read, for the table's
// shorter forms.
type tableOf struct {
	b      findings.RehearsalBlock
	unread bool
}

// parts are the markdown's paragraphs in order. brief names each finding by its identifier
// and object alone, the table's steps and new findings briefly, and cuts the heading's
// names.
func parts(doc *findings.Document, steps []step.Pair, brief bool) []part {
	var out []part
	b := doc.Rehearsal
	name := func(s string) string {
		if brief {
			return clip(s, nameMax)
		}
		return s
	}
	// The scope every stage was read under follows the branch in the heading (017), so
	// the comment names what was read; a refusal before the scope was resolved names none.
	scope := ""
	if doc.Subject != nil && doc.Subject.Scope != "" {
		scope = ", scope " + inline(name(doc.Subject.Scope))
	}
	if b == nil {
		branch := ""
		if doc.Subject != nil {
			branch = doc.Subject.Branch
		}
		out = append(out, part{text: "## Fylgja did not rehearse branch " + inline(name(branch)) + scope},
			part{text: fmt.Sprintf("Status **%s**.", doc.Status)},
			part{text: findingsSection("Findings", rejections(doc.Findings), brief, nil), name: "the findings", rank: 1},
			part{text: warningsSection(doc.Findings, nil, brief), name: "the warnings", rank: 2})
		return append(out, part{text: Caveat})
	}

	unread := endUnread(*b, doc.Status)
	verb := "rehearsed"
	switch {
	case unread:
		verb = "started rehearsing"
	case b.Run == nil || !reachedAny(*b):
		verb = "did not rehearse"
	}
	out = append(out, part{text: fmt.Sprintf("## Fylgja %s proposed change %s on %s%s", verb,
		inline(fmt.Sprintf("%q", name(b.ProposedChange.Name))), inline(name(b.ProposedChange.Branch)), scope)})
	switch {
	case unread:
		out = append(out, part{text: fmt.Sprintf("Run %s was started, and its end was not read: %s. It goes on to its destroy, "+
			"and %s says where it is. Stages resolved at %s. Status **%s**. Deadline %ds (ceiling %ds).",
			code(b.Run.WorkflowID+" "+b.Run.RunID), whyText(doc, brief), code("fylgja twin show"), inline(b.ResolvedAt),
			doc.Status, b.DeadlineS, b.CeilingS)})
	case b.Run != nil && !reachedAny(*b) && doc.Status == findings.StatusRejected:
		out = append(out, part{text: fmt.Sprintf("Run %s touched nothing, since a run already holds the id of its baseline's "+
			"provision, and no destroy was needed; stages resolved at %s. Status **%s**. Deadline %ds (ceiling %ds).",
			code(b.Run.WorkflowID+" "+b.Run.RunID), inline(b.ResolvedAt), doc.Status, b.DeadlineS, b.CeilingS)})
	case b.Run != nil:
		out = append(out, part{text: fmt.Sprintf("Run %s, stages resolved at %s. Status **%s**. %.1fs of the %ds deadline (ceiling %ds).",
			code(b.Run.WorkflowID+" "+b.Run.RunID), inline(b.ResolvedAt), doc.Status, b.UsedS, b.DeadlineS, b.CeilingS)})
	default:
		out = append(out, part{text: fmt.Sprintf("No run was started; stages resolved at %s. Status **%s**. Deadline %ds (ceiling %ds).",
			inline(b.ResolvedAt), doc.Status, b.DeadlineS, b.CeilingS)})
	}
	out = append(out, part{text: table(*b, unread, brief), name: "the table", table: &tableOf{*b, unread}},
		part{text: drawing(*b, steps, unread), name: "the drawing", rank: 6})
	if doc.Status != findings.StatusOK {
		out = append(out, part{text: findingsSection("Findings", rejections(doc.Findings), brief, nil), name: "the findings", rank: 3})
	}
	out = append(out, part{text: stagesSection(*b), name: "the stages", rank: 4},
		part{text: warningsSection(doc.Findings, b.Stages, brief), name: "the warnings", rank: 5})
	var baseline []findings.StepWaitFailing
	if b.Baseline != nil {
		baseline = b.Baseline.Findings
	}
	out = append(out, part{text: failingSection("Baseline findings", "(reported, failing nothing)", baseline, brief),
		name: "the baseline's findings", rank: 7})
	if len(b.Reproduce) > 0 {
		out = append(out, part{text: "**Reproduce by hand**:\n\n" + fenced("", strings.Join(b.Reproduce, "\n")),
			name: "the commands that reproduce it", rank: 2})
	}
	return append(out, part{text: Caveat})
}

// join is the parts as the markdown: a blank line between two, and a newline at the end.
func join(ps []part) string {
	texts := make([]string, len(ps))
	for i, p := range ps {
		texts[i] = p.text
	}
	return strings.Join(texts, "\n\n") + "\n"
}

// fit is the brief parts within CommentMax: those of rank 0, the table among them, then each
// other in rank order while it fits beside the note, which is placed before the caveat, the
// last part. The table is never left out: should the brief one not fit beside the other
// parts of rank 0, it gives each stage's reference and verdict alone, and should even that
// not fit, as many stages as do and how many are left out. A document with no block has no
// table, and its note names none.
func fit(ps []part) string {
	var names []string
	longest := tableShrunk{none: true}
	for _, p := range ps {
		if p.rank > 0 {
			names = append(names, p.name)
		}
		if p.table != nil {
			longest = tableShrunk{verdicts: true, left: len(p.table.b.Stages)}
		}
	}
	// The note naming every part, and any table cut to no stage, is the longest it can be.
	// The size counts the blank line before each part and, one byte short of the first
	// one's, the newline at the end.
	size := -1 + len(fitNote(names, longest)) + 2
	for _, p := range ps {
		if p.rank == 0 && p.table == nil {
			size += 2 + len(p.text)
		}
	}
	shrunk := tableShrunk{none: longest.none}
	for i, p := range ps {
		if p.table == nil {
			continue
		}
		ps[i].text, shrunk = p.table.within(p.text, CommentMax-size-2)
		size += 2 + len(ps[i].text)
	}
	order := make([]int, len(ps))
	for i := range order {
		order[i] = i
	}
	sort.SliceStable(order, func(i, j int) bool { return ps[order[i]].rank < ps[order[j]].rank })
	kept := make([]bool, len(ps))
	for _, i := range order {
		if ps[i].rank == 0 {
			kept[i] = true
			continue
		}
		if n := size + 2 + len(ps[i].text); n <= CommentMax {
			kept[i], size = true, n
		}
	}
	var out []part
	var left []string
	for i, p := range ps[:len(ps)-1] {
		if kept[i] {
			out = append(out, p)
		} else {
			left = append(left, p.name)
		}
	}
	return join(append(out, part{text: fitNote(left, shrunk)}, ps[len(ps)-1]))
}

// tableShrunk is how far fit shrank the table: to each stage's reference and verdict, and
// how many stages it left out; none when there is no table to shrink.
type tableShrunk struct {
	none     bool
	verdicts bool
	left     int
}

// within is the table within room bytes: brief as it is, or each stage's reference and
// verdict alone, or as many of those rows as fit and a last one counting the rest.
func (t tableOf) within(brief string, room int) (string, tableShrunk) {
	if len(brief) <= room {
		return brief, tableShrunk{}
	}
	lines := []string{"| stage | verdict |", "|---|---|"}
	size := len(lines[0]) + 1 + len(lines[1])
	n := len(t.b.Stages)
	rows := make([]string, n)
	for i, s := range t.b.Stages {
		rows[i] = row(cell(s.Ref), cell(verdictCell(s, t.unread)))
	}
	for _, r := range rows {
		size += 1 + len(r)
	}
	if size <= room {
		return strings.Join(append(lines, rows...), "\n"), tableShrunk{verdicts: true}
	}
	for n > 0 && size+1+len(moreRow(len(rows)-n)) > room {
		n--
		size -= 1 + len(rows[n])
	}
	return strings.Join(append(append(lines, rows[:n]...), moreRow(len(rows)-n)), "\n"), tableShrunk{verdicts: true, left: len(rows) - n}
}

// moreRow is the verdicts table's last row when stages are left out of it.
func moreRow(left int) string { return row(fmt.Sprintf("… and %d more", left), "") }

// fitNote says what fit shortened: every finding named by its identifier and object alone,
// the table's steps and new verification failures briefly or each stage's reference and verdict alone
// with how many stages are left out of it, when there is a table, and the parts left out.
func fitNote(left []string, t tableShrunk) string {
	note := "*To fit what Infrahub keeps of a comment (" + fmt.Sprint(CommentMax) +
		" bytes), each finding is named by its identifier and object alone"
	switch {
	case t.none:
	case t.left > 0:
		note += fmt.Sprintf("; the table gives each stage's reference and verdict alone, and the last %d are left out of it", t.left)
	case t.verdicts:
		note += "; the table gives each stage's reference and verdict alone"
	default:
		note += ", and the table each step by its outcome and its new verification failures by the first few"
	}
	switch len(left) {
	case 0:
	case 1:
		note += "; " + left[0] + " is left out"
	default:
		note += "; " + strings.Join(left[:len(left)-1], ", ") + " and " + left[len(left)-1] + " are left out"
	}
	return note + "; fylgja-twin's message is the whole report as text.*"
}

// nameMax is the most of a proposed change's name, a branch's or a scope's, a brief
// heading keeps, in bytes: enough to tell one from another, and short enough that the
// heading always fits.
const nameMax = 120

// clip is s cut to at most limit bytes, at a rune's edge, with an ellipsis when cut.
func clip(s string, limit int) string {
	if len(s) <= limit {
		return s
	}
	cut := 0
	for i := range s {
		if i > limit-len("…") {
			break
		}
		cut = i
	}
	return s[:cut] + "…"
}

// whyText is why a run's end was not read: the messages of the document's rejections no stage
// filed, or, brief, their identifiers.
func whyText(doc *findings.Document, brief bool) string {
	if !brief {
		return inline(orNone(whyUnread(doc)))
	}
	var rules []string
	for _, f := range unfiled(doc) {
		rules = append(rules, code(f.Rule))
	}
	return orNone(rules)
}

// table is one row per stage: the reference, the at, the snapshot (018) and the bundle by
// their short ids (— for a stage refused), the step's outcome with the nodes it touched,
// the wait's outcome, the counts, the new findings and the verdict, which reads not read
// for a stage of a run whose end was not read. Brief, the step is its outcome alone and the
// new findings the first few and how many more.
func table(b findings.RehearsalBlock, unread, brief bool) string {
	lines := []string{
		"| stage | at | snapshot | bundle | step | wait | verify | new verification failures | verdict |",
		"|---|---|---|---|---|---|---|---|---|",
	}
	for _, s := range b.Stages {
		at, snapshot, bundle := "—", "—", "—"
		if s.At != "" {
			at = cell(s.At)
		}
		if s.SnapshotID != nil {
			snapshot = short(*s.SnapshotID)
		}
		if s.BundleID != nil {
			bundle = short(*s.BundleID)
		}
		wait, counts := "", ""
		if w := s.Wait; w != nil {
			wait = fmt.Sprintf("%s after %.1fs", w.Outcome, w.AfterS)
		}
		if s.Verify != nil {
			counts = countsText(*s.Verify)
		}
		stepped, found := stepCell(s), newCell(s)
		if brief {
			stepped, found = stepOutcome(s), newBrief(s)
		}
		lines = append(lines, row(cell(s.Ref), at, snapshot, bundle, cell(stepped), wait, counts, cell(found), cell(verdictCell(s, unread))))
	}
	return strings.Join(lines, "\n")
}

// row is a table row; an empty cell is written as one space, as the contract shows it.
func row(cells ...string) string {
	var b strings.Builder
	b.WriteString("|")
	for _, c := range cells {
		if c == "" {
			b.WriteString(" |")
			continue
		}
		b.WriteString(" " + c + " |")
	}
	return b.String()
}

// stepCell is what the stage's child did, in a cell: created, or the step's outcome with its
// time, the nodes containerlab's plan touched and the pushes that landed and did not. A step
// cut at a phase names them too, as a diverged one does (FR-004).
func stepCell(s findings.RehearsalStage) string {
	if p := s.Provision; p != nil {
		if p.Outcome == provisionReady {
			return "created"
		}
		return "not built (" + strings.TrimPrefix(provisionEnded(p), "its provision ended ") + ")"
	}
	st := s.Step
	if st == nil {
		return ""
	}
	var parts []string
	switch st.Outcome {
	case wire.StepStepped:
		parts = append(parts, fmt.Sprintf("stepped %.1fs", st.Timings.WholeS))
	case wire.StepUnchanged:
		return "unchanged"
	case wire.StepDiverged:
		parts = append(parts, fmt.Sprintf("diverged at %s %.1fs", st.Phase, st.Timings.WholeS))
	case outcomeCancelled:
		if st.Phase == "" {
			return "cancelled before its stage"
		}
		parts = append(parts, "cancelled at "+st.Phase)
	case outcomeRejected:
		return "rejected"
	default:
		return "could not run"
	}
	parts = append(parts, lifecycle(st)...)
	var landed, not []string
	for _, p := range st.Pushed {
		switch {
		case p.Outcome == wire.PushLanded:
			landed = append(landed, p.Node)
		case p.Rule != "":
			not = append(not, fmt.Sprintf("%s (%s)", p.Node, p.Rule))
		default:
			not = append(not, p.Node)
		}
	}
	if len(landed) > 0 {
		parts = append(parts, "push "+strings.Join(landed, ", "))
	}
	if len(not) > 0 {
		parts = append(parts, "not landed "+strings.Join(not, ", "))
	}
	return strings.Join(parts, "; ")
}

// stepOutcome is the step cell brief: what the stage's child came to, without its nodes and
// times.
func stepOutcome(s findings.RehearsalStage) string {
	if p := s.Provision; p != nil {
		if p.Outcome == provisionReady {
			return "created"
		}
		return "not built"
	}
	st := s.Step
	switch {
	case st == nil:
		return ""
	case st.Outcome == wire.StepDiverged:
		return "diverged at " + st.Phase
	case st.Outcome == wire.StepStepped, st.Outcome == wire.StepUnchanged, st.Outcome == outcomeCancelled, st.Outcome == outcomeRejected:
		return st.Outcome
	}
	return "could not run"
}

// newFew is how many new findings a brief cell names before it counts the rest.
const newFew = 2

// newBrief is the new findings cell brief: the first few, then how many more.
func newBrief(s findings.RehearsalStage) string {
	if s.Role != RoleRehearsed || !compared(s.Wait) || len(s.NewFindings) <= newFew {
		return newCell(s)
	}
	return fmt.Sprintf("%s and %d more", findingsText(s.NewFindings[:newFew]), len(s.NewFindings)-newFew)
}

// newCell is the stage's new findings: a dash on the baseline, none or each by rule and
// object on a rehearsed stage whose wait settled or expired, not compared on one whose wait
// ended otherwise, since Classify compared nothing there (T108), and nothing elsewhere.
func newCell(s findings.RehearsalStage) string {
	switch {
	case s.Role == RoleBaseline:
		return "—"
	case s.Role == RoleRehearsed && compared(s.Wait):
		return findingsText(s.NewFindings)
	case s.Role == RoleRehearsed && s.Wait != nil:
		return "not compared"
	}
	return ""
}

// compared is whether a stage's wait was compared with the baseline's: it settled or
// expired, as Classify's comparable says of the wait it was given.
func compared(w *findings.RehearsalWait) bool {
	return w != nil && (w.Outcome == wire.WaitSettled || w.Outcome == wire.WaitExpired)
}

// verdictCell is the verdict as the text words it: refused with what refused it, not
// reached in two words, and not read on a run whose end was not read.
func verdictCell(s findings.RehearsalStage, unread bool) string {
	if Verdict(s.Verdict) == VerdictRefused {
		return refusedText(s)
	}
	return shownVerdict(s, unread)
}

// shownVerdict is a stage's verdict in words, but not read where the run's end was not read
// and the block says not reached for want of knowing more.
func shownVerdict(s findings.RehearsalStage, unread bool) string {
	if unread && Verdict(s.Verdict) == VerdictNotReached {
		return "not read"
	}
	return verdictWords(s.Verdict)
}

func verdictWords(v string) string { return strings.ReplaceAll(v, "_", " ") }

// drawing is the Mermaid flowchart: one node per stage labelled with its reference and
// verdict, and one edge per pair of stages labelled with what the step between them
// changed, dotted where the plan computed none. It runs top to bottom, since Infrahub
// draws it at the thread's width with a frame its zoom does not grow, so a drawing
// across would be shrunk past reading. A stage that failed or erred is outlined red by a
// class: Infrahub's renderer drops a node's style attribute and keeps the drawing's own
// style block.
func drawing(b findings.RehearsalBlock, steps []step.Pair, unread bool) string {
	lines := []string{"```mermaid", "flowchart TD"}
	for i, s := range b.Stages {
		lines = append(lines, fmt.Sprintf("  s%d[\"%s<br/>%s\"]", i, mermaid(s.Ref), mermaid(shownVerdict(s, unread))))
	}
	for i := 1; i < len(b.Stages); i++ {
		from, to := b.Stages[i-1].Ref, b.Stages[i].Ref
		label, computed := "not computed", false
		for _, p := range steps {
			if p.From == from && p.To == to && p.Step != nil {
				label, computed = changed(*p.Step), true
				break
			}
		}
		if computed {
			lines = append(lines, fmt.Sprintf("  s%d -- \"%s\" --> s%d", i-1, mermaid(label), i))
		} else {
			lines = append(lines, fmt.Sprintf("  s%d -. \"%s\" .-> s%d", i-1, mermaid(label), i))
		}
	}
	var failed []string
	for i, s := range b.Stages {
		if v := Verdict(s.Verdict); v == VerdictFailed || v == VerdictError {
			failed = append(failed, fmt.Sprintf("s%d", i))
		}
	}
	if len(failed) > 0 {
		lines = append(lines, "  classDef failed stroke:#d32f2f,stroke-width:3px",
			"  class "+strings.Join(failed, ",")+" failed")
	}
	return strings.Join(append(lines, "```"), "\n")
}

// changed is what a step changed, by name and never by content: the links added and
// removed, the nodes added, removed and changed with their reasons (nodes changed for the
// same reasons together), and the nodes whose artifact changed, came or went.
//
//	+link n1:e1-3 — n3:e1-3; ~n1, ~n3 (bootstrap, mapping); artifacts n1, n3
func changed(s step.Step) string {
	if s.Unchanged {
		return "unchanged"
	}
	var parts []string
	for _, l := range s.LinksAdded {
		parts = append(parts, "+link "+linkText(l))
	}
	for _, l := range s.LinksRemoved {
		parts = append(parts, "-link "+linkText(l))
	}
	for _, n := range s.NodesAdded {
		parts = append(parts, "+"+n)
	}
	for _, n := range s.NodesRemoved {
		parts = append(parts, "-"+n)
	}
	var order []string
	byReasons := map[string][]string{}
	for _, c := range s.NodesChanged {
		why := strings.Join(c.Reasons, ", ")
		if _, ok := byReasons[why]; !ok {
			order = append(order, why)
		}
		byReasons[why] = append(byReasons[why], "~"+c.Node)
	}
	for _, why := range order {
		parts = append(parts, fmt.Sprintf("%s (%s)", strings.Join(byReasons[why], ", "), why))
	}
	seen := map[string]bool{}
	var nodes []string
	add := func(node string) {
		if !seen[node] {
			seen[node] = true
			nodes = append(nodes, node)
		}
	}
	for _, a := range s.ArtifactsChanged {
		add(a.Node)
	}
	for _, a := range s.ArtifactsAdded {
		add(a.Node)
	}
	for _, a := range s.ArtifactsRemoved {
		add(a.Node)
	}
	if len(nodes) > 0 {
		sort.Strings(nodes)
		parts = append(parts, "artifacts "+strings.Join(nodes, ", "))
	}
	if len(parts) == 0 {
		return "unchanged"
	}
	return strings.Join(parts, "; ")
}

func linkText(l step.LinkRef) string {
	return fmt.Sprintf("%s:%s — %s:%s", l.A.Node, l.A.Port, l.B.Node, l.B.Port)
}

// stagesSection is the proposed change's stages as stage list prints them: each reference,
// the branch and the at it resolved to and where the at came from, and a mark's
// description, quoted.
func stagesSection(b findings.RehearsalBlock) string {
	lines := []string{"**Stages** (Infrahub's view does not show them):", ""}
	for _, s := range b.Stages {
		line := "- " + code(s.Ref)
		if s.At == "" {
			line += " unresolved (" + findings.AtSourceText(s.AtSource) + ")"
		} else {
			line += fmt.Sprintf(" %s at %s (%s)", inline(s.Branch), inline(s.At), findings.AtSourceText(s.AtSource))
		}
		if s.AtSource == findings.AtSourceGiven || s.AtSource == findings.AtSourceWritten {
			line += " " + inline(fmt.Sprintf("%q", s.Description))
		}
		lines = append(lines, line)
	}
	return strings.Join(lines, "\n")
}

// warningsSection is the document's warnings, verify's aside: the baseline's are their own
// section's, and a stage's wait is the table's. A warning a stage filed, as the plan files
// one for each stage that reads it at read and at compile, is listed once, naming each stage
// that filed it, as stage plan prints it under each (FR-014):
//
//	`artifact.interface.unrepresented` n1:ethernet-1/99: … (stages bad-port, head)
//
// The run's own warnings are listed as they came: the rehearsal's, and stage.main.moved,
// which the plan files on the branch point but which is the branch's.
func warningsSection(l findings.List, stages []findings.RehearsalStage, brief bool) string {
	filed := stagesFiling(stages)
	var warnings findings.List
	listed := map[warningKey]bool{}
	for _, f := range l {
		if f.Severity != findings.Warning || strings.HasPrefix(f.Rule, "verify.") {
			continue
		}
		if k := keyOf(f); filed[k] != nil {
			if listed[k] {
				continue
			}
			listed[k] = true
		}
		warnings = append(warnings, f)
	}
	return findingsSection("Warnings", warnings, brief, func(f findings.Finding) string {
		labels := filed[keyOf(f)]
		if labels == nil {
			return ""
		}
		word := "stage"
		if len(labels) > 1 {
			word = "stages"
		}
		named := make([]string, len(labels))
		for i, l := range labels {
			named[i] = inline(l)
		}
		return " (" + word + " " + strings.Join(named, ", ") + ")"
	})
}

// warningKey is a warning as its line names it, its step aside: the plan files the same one
// at read and at compile.
type warningKey struct{ rule, object, message string }

func keyOf(f findings.Finding) warningKey { return warningKey{f.Rule, f.Object, f.Message} }

// stagesFiling is each warning a stage filed, but the run's own, with the labels of the
// stages that filed it, each once, in the stages' order.
func stagesFiling(stages []findings.RehearsalStage) map[warningKey][]string {
	filed := map[warningKey][]string{}
	for _, s := range stages {
		for _, f := range s.Findings {
			if f.Severity != findings.Warning || runsOwn(f.Rule) {
				continue
			}
			k := keyOf(f)
			if !slices.Contains(filed[k], s.Label) {
				filed[k] = append(filed[k], s.Label)
			}
		}
	}
	return filed
}

// runsOwn is whether a warning is the run's or its branch's rather than a stage's.
func runsOwn(rule string) bool {
	return rule == findings.RuleStageMainMoved || strings.HasPrefix(rule, "rehearsal.")
}

func rejections(l findings.List) findings.List {
	var out findings.List
	for _, f := range l {
		if f.Severity == findings.Rejection {
			out = append(out, f)
		}
	}
	return out
}

// findingsSection is a titled list of findings, each by identifier, object and message, in
// the order WriteText prints them, each followed by what suffix, when given, adds to it; none
// when there are none.
func findingsSection(title string, l findings.List, brief bool, suffix func(findings.Finding) string) string {
	if len(l) == 0 {
		return "**" + title + "**: none"
	}
	sorted := append(findings.List{}, l...)
	sort.SliceStable(sorted, func(i, j int) bool {
		if sorted[i].Rule != sorted[j].Rule {
			return sorted[i].Rule < sorted[j].Rule
		}
		return sorted[i].Object < sorted[j].Object
	})
	lines := make([]string, 0, len(sorted))
	for _, f := range sorted {
		line := findingLine(f.Rule, f.Object, f.Message, brief)
		if suffix != nil {
			line += suffix(f)
		}
		lines = append(lines, line)
	}
	return "**" + title + "**:\n\n" + strings.Join(counted(lines), "\n")
}

// failingSection is a titled list of failing assertions, the note after the title; none
// when there are none.
func failingSection(title, note string, fs []findings.StepWaitFailing, brief bool) string {
	head := "**" + title + "** " + note + ":"
	if len(fs) == 0 {
		return head + " none"
	}
	lines := make([]string, 0, len(fs))
	for _, f := range fs {
		lines = append(lines, findingLine(f.Rule, f.Object, f.Message, brief))
	}
	return head + "\n\n" + strings.Join(counted(lines), "\n")
}

// findingLine is a finding as a list item: its identifier, its object and, unless brief,
// its message.
func findingLine(rule, object, message string, brief bool) string {
	line := "- " + code(rule)
	if object != "" {
		line += " " + inline(object)
	}
	if brief {
		return line
	}
	return line + ": " + inline(message)
}

// counted is lines with each run of identical ones written once, followed by its count when
// there are several: a brief list names one finding per stage that repeats it.
func counted(lines []string) []string {
	var out []string
	for i := 0; i < len(lines); {
		j := i + 1
		for j < len(lines) && lines[j] == lines[i] {
			j++
		}
		if j-i > 1 {
			out = append(out, fmt.Sprintf("%s (×%d)", lines[i], j-i))
		} else {
			out = append(out, lines[i])
		}
		i = j
	}
	return out
}

// short is a snapshot's or a bundle's id, its first eight characters and an ellipsis, as the
// text prints it.
func short(id string) string {
	if len(id) > 8 {
		return id[:8] + "…"
	}
	return id
}

// inline is text as markdown shows it verbatim: each character markdown or GFM would read
// as markup escaped with a backslash, and a line break as a space, so an operator's string
// neither formats nor breaks the line it is in.
func inline(s string) string {
	var b strings.Builder
	for _, r := range s {
		switch {
		case r == '\n' || r == '\r':
			b.WriteRune(' ')
		case strings.ContainsRune("\\`*_[]<>|~&#!", r):
			b.WriteRune('\\')
			b.WriteRune(r)
		default:
			b.WriteRune(r)
		}
	}
	return b.String()
}

// cell is inline text in a table cell, where a pipe would end it.
func cell(s string) string { return inline(s) }

// code is a code span holding s verbatim: fenced by one backtick more than the longest run
// in it, and padded when it begins or ends with one.
func code(s string) string {
	fence := strings.Repeat("`", longestRun(s, '`')+1)
	if strings.HasPrefix(s, "`") || strings.HasSuffix(s, "`") {
		s = " " + s + " "
	}
	return fence + s + fence
}

// fenced is a fenced code block holding content verbatim, fenced by three backticks or one
// more than the longest run in it.
func fenced(info, content string) string {
	fence := strings.Repeat("`", max(3, longestRun(content, '`')+1))
	return fence + info + "\n" + content + "\n" + fence
}

func longestRun(s string, c rune) int {
	longest, run := 0, 0
	for _, r := range s {
		if r == c {
			run++
			longest = max(longest, run)
		} else {
			run = 0
		}
	}
	return longest
}

// mermaid is text inside one of Mermaid's quoted labels: # first, since Mermaid reads
// #…; as an entity, then the quote that would end the label, the backtick that would open a
// markdown string closed only by `", and the angle brackets it would read as markup, each as
// its entity; a line break as a space.
func mermaid(s string) string {
	return strings.NewReplacer("#", "#35;", `"`, "#quot;", "`", "#96;", "<", "#lt;", ">", "#gt;", "\n", " ", "\r", " ").Replace(s)
}
