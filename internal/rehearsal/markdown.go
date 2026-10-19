package rehearsal

import (
	"fmt"
	"sort"
	"strings"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/step"
)

// Caveat is the markdown's last line: what a twin's fidelity is (FR-014).
const Caveat = "*Fidelity is asserted, not measured: the twin's containers forward in software and keep their own timing.*"

// Markdown is the rehearsal's report as GitHub-flavoured markdown (FR-014; research R-10;
// contracts/rehearse-command.md, "The markdown"), the comment a check posts on the proposed
// change: the heading naming Fylgja, the proposed change and its branch; the run, when the
// stages were resolved, the status and the time used against the deadline and the
// ceiling; a table of the stages; a Mermaid drawing of the stages and what each step between
// them changed; on any status but ok the findings that say why; the stages as stage list
// prints them, since Infrahub's view does not show them; the warnings; the baseline's
// findings; on a failure the commands that reproduce it; and the fidelity caveat, last.
//
// It is rendered from the document and the plan's steps alone, both of which name what
// changed and never a line of it: the block holds no step's difference
// (rehearsal.schema.json leaves it to stage plan's), and the warnings and a refusal's
// reasons are the document's. A document with no block, refused before the proposed change
// was found, is the heading, the status, the findings and the caveat. Every operator's
// string is escaped where it lands: as markdown text, in a table cell, in a code span, and
// in Mermaid's quoted labels, where ", < and > are #quot;, #lt; and #gt;.
func Markdown(doc *findings.Document, steps []step.Pair) string {
	var out []string
	b := doc.Rehearsal
	if b == nil {
		branch := ""
		if doc.Subject != nil {
			branch = doc.Subject.Branch
		}
		out = append(out, "## Fylgja did not rehearse branch "+inline(branch),
			fmt.Sprintf("Status **%s**.", doc.Status))
		out = append(out, findingsSection("Findings", rejections(doc.Findings))...)
		out = append(out, warningsSection(doc.Findings)...)
		return strings.Join(append(out, Caveat), "\n\n") + "\n"
	}

	verb := "rehearsed"
	if b.Run == nil {
		verb = "did not rehearse"
	}
	out = append(out, fmt.Sprintf("## Fylgja %s proposed change %s on %s", verb, inline(fmt.Sprintf("%q", b.ProposedChange.Name)),
		inline(b.ProposedChange.Branch)))
	if b.Run != nil {
		out = append(out, fmt.Sprintf("Run %s, stages resolved at %s. Status **%s**. %.1fs of the %ds deadline (ceiling %ds).",
			code(b.Run.WorkflowID+" "+b.Run.RunID), inline(b.ResolvedAt), doc.Status, b.UsedS, b.DeadlineS, b.CeilingS))
	} else {
		out = append(out, fmt.Sprintf("No run was started; stages resolved at %s. Status **%s**. Deadline %ds (ceiling %ds).",
			inline(b.ResolvedAt), doc.Status, b.DeadlineS, b.CeilingS))
	}
	out = append(out, table(*b), drawing(*b, steps))
	if doc.Status != findings.StatusOK {
		out = append(out, findingsSection("Findings", rejections(doc.Findings))...)
	}
	out = append(out, stagesSection(*b))
	out = append(out, warningsSection(doc.Findings)...)
	var baseline []findings.StepWaitFailing
	if b.Baseline != nil {
		baseline = b.Baseline.Findings
	}
	out = append(out, failingSection("Baseline findings", "(reported, failing nothing)", baseline)...)
	if len(b.Reproduce) > 0 {
		out = append(out, "**Reproduce by hand**:", fenced("", strings.Join(b.Reproduce, "\n")))
	}
	return strings.Join(append(out, Caveat), "\n\n") + "\n"
}

// table is one row per stage: the reference, the at, the bundle, the step's outcome with the
// nodes it touched, the wait's outcome, the counts, the new findings and the verdict.
func table(b findings.RehearsalBlock) string {
	lines := []string{
		"| stage | at | bundle | step | wait | verify | new findings | verdict |",
		"|---|---|---|---|---|---|---|---|",
	}
	for _, s := range b.Stages {
		at, bundle := "—", "—"
		if s.At != "" {
			at = cell(s.At)
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
		lines = append(lines, row(cell(s.Ref), at, bundle, cell(stepCell(s)), wait, counts, cell(newCell(s)), cell(verdictCell(s))))
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
// time, the nodes containerlab's plan touched and the pushes that landed and did not.
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
		return "cancelled at " + st.Phase
	case outcomeRejected:
		return "rejected"
	default:
		return "could not run"
	}
	for _, l := range []struct {
		verb  string
		nodes []string
	}{{"restarted", st.Restarted}, {"recreated", st.Recreated}, {"created", st.Created}} {
		if len(l.nodes) > 0 {
			parts = append(parts, l.verb+" "+strings.Join(l.nodes, ", "))
		}
	}
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

// newCell is the stage's new findings: a dash on the baseline, none or each by rule and
// object on a rehearsed stage whose wait ran, and nothing elsewhere.
func newCell(s findings.RehearsalStage) string {
	switch {
	case s.Role == RoleBaseline:
		return "—"
	case s.Role == RoleRehearsed && s.Wait != nil:
		return findingsText(s.NewFindings)
	}
	return ""
}

// verdictCell is the verdict as the text words it: refused with what refused it, not
// reached in two words.
func verdictCell(s findings.RehearsalStage) string {
	if Verdict(s.Verdict) == VerdictRefused {
		return refusedText(s)
	}
	return verdictWords(s.Verdict)
}

func verdictWords(v string) string { return strings.ReplaceAll(v, "_", " ") }

// drawing is the Mermaid flowchart: one node per stage labelled with its reference and
// verdict, and one edge per pair of stages labelled with what the step between them
// changed, dotted where the plan computed none.
func drawing(b findings.RehearsalBlock, steps []step.Pair) string {
	lines := []string{"```mermaid", "flowchart LR"}
	for i, s := range b.Stages {
		lines = append(lines, fmt.Sprintf("  s%d[\"%s<br/>%s\"]", i, mermaid(s.Ref), mermaid(verdictWords(s.Verdict))))
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
// section's, and a stage's wait is the table's.
func warningsSection(l findings.List) []string {
	var warnings findings.List
	for _, f := range l {
		if f.Severity == findings.Warning && !strings.HasPrefix(f.Rule, "verify.") {
			warnings = append(warnings, f)
		}
	}
	return findingsSection("Warnings", warnings)
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
// the order WriteText prints them; none when there are none.
func findingsSection(title string, l findings.List) []string {
	if len(l) == 0 {
		return []string{"**" + title + "**: none"}
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
		lines = append(lines, findingLine(f.Rule, f.Object, f.Message))
	}
	return []string{"**" + title + "**:", strings.Join(lines, "\n")}
}

// failingSection is a titled list of failing assertions, the note after the title; none
// when there are none.
func failingSection(title, note string, fs []findings.StepWaitFailing) []string {
	head := "**" + title + "** " + note + ":"
	if len(fs) == 0 {
		return []string{head + " none"}
	}
	lines := make([]string, 0, len(fs))
	for _, f := range fs {
		lines = append(lines, findingLine(f.Rule, f.Object, f.Message))
	}
	return []string{head, strings.Join(lines, "\n")}
}

func findingLine(rule, object, message string) string {
	line := "- " + code(rule)
	if object != "" {
		line += " " + inline(object)
	}
	return line + ": " + inline(message)
}

// short is a bundle id's first eight characters and an ellipsis, as the text prints it.
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
// #…; as an entity, then the quote that would end the label and the angle brackets it would
// read as markup, each as its entity; a line break as a space.
func mermaid(s string) string {
	return strings.NewReplacer("#", "#35;", `"`, "#quot;", "<", "#lt;", ">", "#gt;", "\n", " ", "\r", " ").Replace(s)
}
