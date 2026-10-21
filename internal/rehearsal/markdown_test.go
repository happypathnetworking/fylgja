package rehearsal

import (
	"fmt"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/step"
)

// marker is a checksum no artifact has, standing where a step names an artifact's: the
// drawing names a node whose artifact changed and never its checksum, let alone a line.
const marker = "FYLGJA-MARKER"

// pairs are the plan's steps between the example's stages: the branch point refused, so the
// step into the baseline was not computed; a link cabled between n1 and n3, which changes
// both nodes' bootstrap and mapping and both artifacts; bad-port's interface on n1; and the
// head unchanged.
func pairs() []step.Pair {
	link := step.Step{From: seededID, To: thirdID,
		LinksAdded: []step.LinkRef{{ID: "l3", A: step.NodePort{Node: "n1", Port: "e1-3"}, B: step.NodePort{Node: "n3", Port: "e1-3"}}},
		NodesChanged: []step.NodeChange{{Node: "n1", Reasons: []string{"bootstrap", "mapping"}},
			{Node: "n3", Reasons: []string{"bootstrap", "mapping"}}},
		ArtifactsChanged: []step.ArtifactChange{{Node: "n1", Name: "device-config", From: marker, To: marker},
			{Node: "n3", Name: "device-config", From: marker, To: marker}}}
	port := step.Step{From: thirdID, To: badID,
		NodesChanged:     []step.NodeChange{{Node: "n1", Reasons: []string{"mapping"}}},
		ArtifactsChanged: []step.ArtifactChange{{Node: "n1", Name: "device-config", From: marker, To: marker}}}
	return []step.Pair{
		step.NotComputed(change+"/branch-point", change+"/seeded", "", seededID, change+"/branch-point was refused"),
		step.Between(change+"/seeded", change+"/third-link", link),
		step.Between(change+"/third-link", change+"/bad-port", port),
		step.Between(change+"/third-link", change+"/head", step.Step{From: thirdID, To: headID, Unchanged: true}),
		step.Between(change+"/bad-port", change+"/head", step.Step{From: badID, To: headID, Unchanged: true}),
	}
}

func TestMarkdown(t *testing.T) {
	passed := Markdown(passedRun().document(), pairs())
	if want := strings.Join([]string{
		`## Fylgja rehearsed proposed change "third link" on change-1`,
		"",
		"Run `fylgja-rehearse 01a1b2c3-0000-7000-8000-0000000000aa`, stages resolved at 2026-10-17T14:02:11Z. Status **ok**. 118.4s of the 1980s deadline (ceiling 3600s).",
		"",
		"| stage | at | bundle | step | wait | verify | new findings | verdict |",
		"|---|---|---|---|---|---|---|---|",
		"| change-1/branch-point | 2026-10-16T17:20:19.944651+00:00 | — | | | | | refused (contract.node.missing) |",
		"| change-1/seeded | 2026-10-16T17:25:30.118244+00:00 | 5c5c5c5c… | created | settled after 3.2s | 15 held, 0 failed, 0 skipped | — | baseline |",
		"| change-1/third-link | 2026-10-16T17:30:00.000000+00:00 | d0d0d0d0… | stepped 4.5s; push n1, n3 | settled after 6.1s | 19 held, 0 failed, 0 skipped | none | passed |",
		"| change-1/head | 2026-10-16T17:30:11.884302+00:00 | cccccccc… | unchanged | settled after 1.0s | 19 held, 0 failed, 0 skipped | none | passed |",
		"",
		"```mermaid",
		"flowchart LR",
		`  s0["change-1/branch-point<br/>refused"]`,
		`  s1["change-1/seeded<br/>baseline"]`,
		`  s2["change-1/third-link<br/>passed"]`,
		`  s3["change-1/head<br/>passed"]`,
		`  s0 -. "not computed" .-> s1`,
		`  s1 -- "+link n1:e1-3 — n3:e1-3; ~n1, ~n3 (bootstrap, mapping); artifacts n1, n3" --> s2`,
		`  s2 -- "unchanged" --> s3`,
		"```",
		"",
		"**Stages** (Infrahub's view does not show them):",
		"",
		"- `change-1/branch-point` main at 2026-10-16T17:20:19.944651+00:00 (branch point)",
		"- `change-1/seeded` change-1 at 2026-10-16T17:25:30.118244+00:00 (written) \"after the link is cabled\"",
		"- `change-1/third-link` change-1 at 2026-10-16T17:30:00.000000+00:00 (given) \"third link\"",
		"- `change-1/head` change-1 at 2026-10-16T17:30:11.884302+00:00 (head)",
		"",
		"**Warnings**: none",
		"",
		"**Baseline findings** (reported, failing nothing): none",
		"",
		Caveat,
		"",
	}, "\n"); passed != want {
		t.Errorf("the ok run's markdown:\n%s\nwant:\n%s", passed, want)
	}

	failed := Markdown(failedRun().document(), pairs())
	if want := strings.Join([]string{
		`## Fylgja rehearsed proposed change "third link" on change-1`,
		"",
		"Run `fylgja-rehearse 01a1b2c3-0000-7000-8000-0000000000aa`, stages resolved at 2026-10-17T14:02:11Z. Status **nonconforming**. 301.6s of the 2610s deadline (ceiling 3600s).",
		"",
		"| stage | at | bundle | step | wait | verify | new findings | verdict |",
		"|---|---|---|---|---|---|---|---|",
		"| change-1/branch-point | 2026-10-16T17:20:19.944651+00:00 | — | | | | | refused (contract.node.missing) |",
		"| change-1/seeded | 2026-10-16T17:25:30.118244+00:00 | 5c5c5c5c… | created | expired after 120.0s | 14 held, 1 failed, 0 skipped | — | baseline |",
		"| change-1/third-link | 2026-10-16T17:30:00.000000+00:00 | d0d0d0d0… | stepped 4.5s; push n1, n3 | expired after 120.0s | 18 held, 1 failed, 0 skipped | none | passed |",
		"| change-1/bad-port | 2026-10-16T17:30:05.000000+00:00 | babababa… | diverged at push 29.8s; restarted n3 61.2s; push n3; not landed n1 (push.refused) | expired after 120.0s | 18 held, 1 failed, 0 skipped | none | failed |",
		"| change-1/head | 2026-10-16T17:30:11.884302+00:00 | cccccccc… | | | | | not reached |",
		"",
		"```mermaid",
		"flowchart LR",
		`  s0["change-1/branch-point<br/>refused"]`,
		`  s1["change-1/seeded<br/>baseline"]`,
		`  s2["change-1/third-link<br/>passed"]`,
		`  s3["change-1/bad-port<br/>failed"]`,
		`  s4["change-1/head<br/>not reached"]`,
		`  s0 -. "not computed" .-> s1`,
		`  s1 -- "+link n1:e1-3 — n3:e1-3; ~n1, ~n3 (bootstrap, mapping); artifacts n1, n3" --> s2`,
		`  s2 -- "~n1 (mapping); artifacts n1" --> s3`,
		`  s3 -- "unchanged" --> s4`,
		"```",
		"",
		"**Findings**:",
		"",
		"- `contract.node.missing` main: branch defines FylgjaContract but holds no instance of it",
		"- `push.refused` n1: n1 refused artifact device-config (checksum 9a0177b2e8c1d4f5a6b7c8d9e0f1a2b3) at line 12: invalid port ethernet-1/99",
		"- `rehearsal.stage.failed` change-1/bad-port: diverged at phase push: landed n3; not landed n1 (push.refused)",
		"",
		"**Stages** (Infrahub's view does not show them):",
		"",
		"- `change-1/branch-point` main at 2026-10-16T17:20:19.944651+00:00 (branch point)",
		"- `change-1/seeded` change-1 at 2026-10-16T17:25:30.118244+00:00 (written) \"after the link is cabled\"",
		"- `change-1/third-link` change-1 at 2026-10-16T17:30:00.000000+00:00 (given) \"third link\"",
		`- ` + "`change-1/bad-port`" + ` change-1 at 2026-10-16T17:30:05.000000+00:00 (given) "a port \<disabled\> \\"by mistake\\" \| n1\\nsecond line"`,
		"- `change-1/head` change-1 at 2026-10-16T17:30:11.884302+00:00 (head)",
		"",
		"**Warnings**: none",
		"",
		"**Baseline findings** (reported, failing nothing):",
		"",
		`- ` + "`verify.neighbor`" + ` n1:ethernet-1/2: node n1 (172.20.20.2): port ethernet-1/2 sees no neighbour at /interface\[name=ethernet-1/2\]; link l1 names n2 ethernet-1/2 at its far end`,
		"",
		"**Reproduce by hand**:",
		"",
		"```",
		"fylgja twin create --stage change-1/seeded",
		"fylgja twin step --stage change-1/third-link --allow-restart",
		"fylgja twin step --stage change-1/bad-port --allow-restart",
		"fylgja twin verify",
		"fylgja twin destroy",
		"```",
		"",
		Caveat,
		"",
	}, "\n"); failed != want {
		t.Errorf("the failed run's markdown:\n%s\nwant:\n%s", failed, want)
	}

	// The caveat is last on every run, the reproduce block on a failure alone, and no line
	// of any artifact's content, not even a checksum, anywhere.
	for _, e := range examples() {
		md := Markdown(e.document(), pairs())
		if !strings.HasSuffix(md, "\n\n"+Caveat+"\n") {
			t.Errorf("%s: the caveat is not last:\n%s", e.name, md)
		}
		failure := len(Build(e.in, e.res).Reproduce) > 0
		if strings.Contains(md, "**Reproduce by hand**") != failure {
			t.Errorf("%s: the reproduce block is there %v, a stage failed %v:\n%s", e.name, !failure, failure, md)
		}
		carriesNoContent(t, e.name+"'s markdown", md)
	}
}

// A step that restarted or recreated a node names each in its cell with the seconds its
// readiness took (FR-004); one cut before its readiness names the node alone, and one cut at
// its push its pushes, landed and not (T094). The block is the same either way, and the
// markdown still fits a comment.
func TestMarkdownNamesTheRestartsTime(t *testing.T) {
	for _, c := range []struct {
		e    example
		want string
	}{
		{restartedRun(), "| change-1/third-link | 2026-10-16T17:30:00.000000+00:00 | d0d0d0d0… | stepped 95.3s; restarted n3 61.2s; recreated n1 70.4s; push n1, n3 | settled after 6.1s |"},
		{cutBeforeReadinessRun(), "| change-1/bad-port | 2026-10-16T17:30:05.000000+00:00 | babababa… | cancelled at readiness; restarted n3 | | | | error |"},
		{cutAtPushRun(), "| change-1/bad-port | 2026-10-16T17:30:05.000000+00:00 | babababa… | cancelled at push; restarted n3 61.2s; push n3; not landed n1 | | | | error |"},
	} {
		md := Markdown(c.e.document(), pairs())
		if !strings.Contains(md, c.want) {
			t.Errorf("%s: the markdown does not hold %q:\n%s", c.e.name, c.want, md)
		}
		if len(md) > CommentMax {
			t.Errorf("%s: the markdown is %d bytes, over the %d a comment holds", c.e.name, len(md), CommentMax)
		}
	}
}

// A warning a stage filed is listed once, naming each stage that filed it, however many
// steps filed it (FR-014; T075); the run's own warnings are listed as they came, the
// branch's stage.main.moved too, although the plan files it on the branch point.
func TestMarkdownNamesEachWarningsStages(t *testing.T) {
	const unrepresented = "artifact device-config names interface ethernet-1/99 at line 17, which the twin does not represent"
	moved := "main has moved since change-1's branch point"
	e := failedRun()
	e.in.Stages[0].Findings.AddStep(findings.Warning, findings.StepResolve, findings.RuleStageMainMoved, change, moved)
	for _, i := range []int{3, 4} {
		e.in.Stages[i].Findings.AddStep(findings.Warning, findings.StepRead, findings.RuleArtifactInterfaceUnrepresented, "n1:ethernet-1/99", unrepresented)
		e.in.Stages[i].Findings.AddStep(findings.Warning, findings.StepCompile, findings.RuleArtifactInterfaceUnrepresented, "n1:ethernet-1/99", unrepresented)
	}
	e.in.Stages[4].Findings.AddStep(findings.Warning, findings.StepCompile, findings.RuleArtifactInterfaceUnrepresented, "n2:ethernet-1/98",
		"artifact device-config names interface ethernet-1/98")
	doc := e.document()
	doc.Findings.AddStep(findings.Warning, findings.StepResolve, findings.RuleRehearsalStageMoved, change+"/head", "stage change-1/head moved")
	md := Markdown(doc, pairs())
	want := strings.Join([]string{
		"**Warnings**:",
		"",
		"- `artifact.interface.unrepresented` n1:ethernet-1/99: " + unrepresented + " (stages bad-port, head)",
		"- `artifact.interface.unrepresented` n2:ethernet-1/98: artifact device-config names interface ethernet-1/98 (stage head)",
		"- `rehearsal.stage.moved` change-1/head: stage change-1/head moved",
		"- `stage.main.moved` change-1: " + moved,
		"",
	}, "\n")
	if !strings.Contains(md, want) {
		t.Errorf("the warnings are not\n%s\nin:\n%s", want, md)
	}
	if len(md) > CommentMax {
		t.Errorf("the markdown is %d bytes, over the %d a comment holds", len(md), CommentMax)
	}

	// Brief, each is named by identifier and object, its stages kept.
	brief := join(parts(doc, pairs(), true))
	if want := "- `artifact.interface.unrepresented` n1:ethernet-1/99 (stages bad-port, head)\n" +
		"- `artifact.interface.unrepresented` n2:ethernet-1/98 (stage head)\n" +
		"- `rehearsal.stage.moved` change-1/head\n- `stage.main.moved` change-1\n"; !strings.Contains(brief, want) {
		t.Errorf("the brief warnings are not\n%s\nin:\n%s", want, brief)
	}

	// A label is the operator's, escaped where it lands.
	e.in.Stages[4].Label = "he*ad"
	if md := Markdown(e.document(), pairs()); !strings.Contains(md, "(stages bad-port, he\\*ad)") {
		t.Errorf("an escaped label is not in:\n%s", md)
	}
}

// The markdown is kept by Infrahub as a comment, so it is never longer than CommentMax. A
// failure's report that would be, as tier 3's bad-port was (T055: two stages each warning
// twice of ethernet-1/99, and the push's long refusal), names its findings by identifier and
// object alone, the repeated ones once with their count, and keeps every section. One with so
// many stages that it is too long still is leaves sections out whole, the table and the
// reproduce commands kept longest, and breaks no fence or table.
func TestMarkdownFitsAComment(t *testing.T) {
	const unrepresented = "artifact device-config names interface ethernet-1/99 at line 17, which the twin does not represent: " +
		"omitted (omit.interface.unmappable: rule ethernet matched, but {port} is 99, outside its range 1..58; no such port on the node)"
	refusal := "node n1 refused artifact device-config (checksum 592e1578066373b636e0676ce1667e26): " + strings.Repeat("the node's message, cut ", 40)
	// The plan files the warning for each stage that reads the artifact, at read and at
	// compile, as the server hands it to the block.
	e := failedRun()
	for _, i := range []int{3, 4} {
		e.in.Stages[i].Findings.AddStep(findings.Warning, findings.StepRead, findings.RuleArtifactInterfaceUnrepresented, "n1:ethernet-1/99", unrepresented)
		e.in.Stages[i].Findings.AddStep(findings.Warning, findings.StepCompile, findings.RuleArtifactInterfaceUnrepresented, "n1:ethernet-1/99", unrepresented)
	}
	doc := e.document()
	doc.Findings.AddStep(findings.Rejection, findings.StepPush, findings.RulePushRefused, "n1", refusal)
	doc.Findings.AddStep(findings.Rejection, findings.StepPush, findings.RuleStepDiverged, stepRun+"2",
		"step run "+stepRun+"2 towards stage change-1/bad-port stopped at phase push: landed n3; not landed n1 (push.refused)")
	if full := join(parts(doc, pairs(), false)); len(full) <= CommentMax {
		t.Fatalf("the example's full markdown is %d bytes, which a comment holds: it proves nothing", len(full))
	}
	md := Markdown(doc, pairs())
	if len(md) > CommentMax {
		t.Errorf("the markdown is %d bytes, over the %d a comment holds:\n%s", len(md), CommentMax, md)
	}
	for _, want := range []string{
		"| change-1/bad-port | 2026-10-16T17:30:05.000000+00:00 | babababa… | diverged at push | expired after 120.0s | 18 held, 1 failed, 0 skipped | none | failed |",
		`  s3["change-1/bad-port<br/>failed"]`,
		"**Findings**:\n\n- `contract.node.missing` main\n- `push.refused` n1 (×2)\n- `rehearsal.stage.failed` change-1/bad-port\n- `step.diverged` " + stepRun + "2\n\n",
		"**Stages** (Infrahub's view does not show them):",
		"**Warnings**:\n\n- `artifact.interface.unrepresented` n1:ethernet-1/99 (stages bad-port, head)\n\n",
		"**Baseline findings** (reported, failing nothing):\n\n- `verify.neighbor` n1:ethernet-1/2\n\n",
		"**Reproduce by hand**:\n\n```\nfylgja twin create --stage change-1/seeded\n",
		"\n\n" + fitNote(nil, tableShrunk{}) + "\n\n" + Caveat + "\n",
	} {
		if !strings.Contains(md, want) {
			t.Errorf("the shortened markdown does not hold %q:\n%s", want, md)
		}
	}
	for _, message := range []string{unrepresented, "the node's message", "invalid port ethernet-1/99", "sees no neighbour"} {
		if strings.Contains(md, message) {
			t.Errorf("the shortened markdown still holds a finding's message, %q:\n%s", message, md)
		}
	}

	// Fourteen more stages keep the brief table, every step by its outcome, and leave the
	// drawing and the stages out; sixty, which no section left out makes fit, keep each
	// stage's reference and verdict in the table, and still fit (T083).
	for _, c := range []struct {
		marks int
		table string
		left  string
		row   string
	}{
		{14, "and the table each step by its outcome and its new findings by the first few", "the drawing and the stages are left out",
			"| change-1/mark-13 | 2026-10-16T17:30:11.884302+00:00 | cccccccc… | unchanged | settled after 1.0s | 19 held, 0 failed, 0 skipped | none | passed |"},
		{60, "; the table gives each stage's reference and verdict alone", "the drawing and the stages are left out",
			"| change-1/mark-59 | passed |"},
	} {
		e := passedRun()
		for i := range c.marks {
			s := head(RoleRehearsed)
			s.Ref = fmt.Sprintf("%s/mark-%02d", change, i)
			e.in.Stages = append(e.in.Stages, s)
			e.res.Stages = append(e.res.Stages, StageResult{Ref: s.Ref, Verdict: VerdictPassed,
				Step: stepTo(s.Ref, 3, wire.StepUnchanged, 0.9), Wait: wait(wire.WaitSettled, 1.0, 1), Counts: counts(8, 0), TookS: 1.9})
		}
		md := Markdown(e.document(), pairs())
		if len(md) > CommentMax {
			t.Errorf("%d more stages: the markdown is %d bytes, over the %d a comment holds", c.marks, len(md), CommentMax)
		}
		for _, want := range []string{
			`## Fylgja rehearsed proposed change "third link" on change-1` + "\n\nRun `fylgja-rehearse " + rehearseRun + "`",
			"\n" + c.row + "\n",
			c.table, "; " + c.left + "; fylgja-twin's message is the whole report as text.*\n\n" + Caveat + "\n",
		} {
			if !strings.Contains(md, want) {
				t.Errorf("%d more stages: the markdown does not hold %q:\n%s", c.marks, want, md)
			}
		}
		wantStagesInTheTable(t, fmt.Sprintf("%d more stages", c.marks), md, Build(e.in, e.res), false)
		if strings.Contains(md, "```") || strings.Contains(md, "**Stages**") {
			t.Errorf("%d more stages: the drawing or the stages are there:\n%s", c.marks, md)
		}
	}
}

// wantStagesInTheTable fails unless the markdown's table has a row for each of the block's
// stages that begins with its reference and ends with its verdict.
func wantStagesInTheTable(t *testing.T, label, md string, b findings.RehearsalBlock, unread bool) {
	t.Helper()
	for _, s := range b.Stages {
		begins, ends := "\n| "+cell(s.Ref)+" |", " | "+cell(verdictCell(s, unread))+" |\n"
		found := false
		for _, line := range strings.SplitAfter(md, "\n") {
			if strings.HasPrefix("\n"+line, begins) && strings.HasSuffix(line, ends[3:]) {
				found = true
				break
			}
		}
		if !found {
			t.Errorf("%s: no table row begins %q and ends %q:\n%s", label, begins[1:], ends[3:], md)
		}
	}
}

// What the ceiling does not bound still fits a comment, the table kept (T083): a stage with
// many new findings names the first few and counts the rest; a rehearsal refused before any
// run with many marks keeps every stage's reference and verdict, and with more marks than
// fit, as many as do and how many are left out; and a proposed change's name longer than a
// comment is cut in the heading with an ellipsis.
func TestMarkdownFitsWhatTheCeilingDoesNotBound(t *testing.T) {
	// One stage's new findings.
	e := newFindingRun()
	var many []wire.StepFinding
	for i := range 200 {
		many = append(many, wire.StepFinding{Rule: findings.RuleVerifyNeighbor, Object: fmt.Sprintf("n1:ethernet-1/%d", i+1),
			Message: "node n1 (172.20.20.2): port sees no neighbour"})
	}
	e.res.Stages[1].NewFindings, e.res.Stages[1].Wait = many, wait(wire.WaitExpired, 120, 61, many...)
	md := Markdown(e.document(), pairs())
	if len(md) > CommentMax || !strings.Contains(md, "| verify.neighbor n1:ethernet-1/1, verify.neighbor n1:ethernet-1/10 and 198 more | failed |") {
		t.Errorf("many new findings: %d bytes, want the first two and 198 more within %d:\n%s", len(md), CommentMax, md)
	}
	wantStagesInTheTable(t, "many new findings", md, Build(e.in, e.res), false)

	// A refusal with many marks.
	for _, c := range []struct {
		marks int
		left  int
	}{{80, 0}, {300, -1}} {
		e := refusedRun()
		for i := range c.marks {
			s := head(RoleRehearsed)
			s.Ref = fmt.Sprintf("%s/mark-%03d", change, i)
			e.in.Stages = append(e.in.Stages, s)
		}
		md := Markdown(e.document(), pairs())
		if len(md) > CommentMax {
			t.Errorf("a refusal with %d marks: the markdown is %d bytes, over %d", c.marks, len(md), CommentMax)
		}
		b := Build(e.in, e.res)
		if c.left == 0 {
			wantStagesInTheTable(t, fmt.Sprintf("a refusal with %d marks", c.marks), md, b, false)
			continue
		}
		// As many stages as fit, in order, then how many are left out, which the note names.
		rows := strings.Count(md, " | not reached |\n")
		left := len(b.Stages) - rows
		if rows == 0 || left <= 0 || !strings.Contains(md, fmt.Sprintf("\n| … and %d more | |\n", left)) ||
			!strings.Contains(md, fmt.Sprintf("the table gives each stage's reference and verdict alone, and the last %d are left out of it", left)) ||
			!strings.Contains(md, fmt.Sprintf("| change-1/mark-%03d | not reached |\n", rows-len(e.in.Stages)+c.marks-1)) {
			t.Errorf("a refusal with %d marks: %d rows, %d left out:\n%s", c.marks, rows, left, md)
		}
	}

	// A name longer than a comment.
	e = failedRun()
	e.in.ProposedChange.Name = strings.Repeat("a long name ", 500)
	md = Markdown(e.document(), pairs())
	heading, _, _ := strings.Cut(md, "\n")
	if len(md) > CommentMax || len(heading) > 200 || !strings.HasPrefix(heading, `## Fylgja rehearsed proposed change "a long name a long`) ||
		!strings.Contains(heading, `…" on change-1`) {
		t.Errorf("a long name: %d bytes, heading %q; want within %d, the name cut with an ellipsis", len(md), heading, CommentMax)
	}
	wantStagesInTheTable(t, "a long name", md, Build(e.in, e.res), false)
	if got := clip("ab€cd", 6); got != "ab…" {
		t.Errorf("clip cut a rune: %q", got)
	}
}

// An operator's strings are escaped where they land: a description holding quotes, angle
// brackets, a pipe and a newline breaks no line of the Stages; a label holding them breaks
// no table cell, no code span and no Mermaid label.
func TestMarkdownEscapes(t *testing.T) {
	odd := badPort(RoleRehearsed)
	odd.Ref, odd.Label = change+`/a"<b>#c|d`, `a"<b>#c|d`
	e := passedRun()
	e.in.Stages[3] = odd
	e.res.Stages[2].Ref = odd.Ref
	md := Markdown(e.document(), nil)
	for _, want := range []string{
		`  s3["change-1/a#quot;#lt;b#gt;#35;c|d<br/>passed"]`,
		`  s2 -. "not computed" .-> s3`,
		`| change-1/a"\<b\>\#c\|d | 2026-10-16T17:30:05.000000+00:00 | babababa… | unchanged |`,
		"- `change-1/a\"<b>#c|d` change-1 at 2026-10-16T17:30:05.000000+00:00 (given) " +
			`"a port \<disabled\> \\"by mistake\\" \| n1\\nsecond line"`,
	} {
		if !strings.Contains(md, want) {
			t.Errorf("the markdown does not hold %s:\n%s", want, md)
		}
	}
	for i, line := range strings.Split(md, "\n") {
		if strings.HasPrefix(line, "second line") {
			t.Errorf("line %d begins with the description's second line: a newline reached the markdown", i+1)
		}
	}
	if got := mermaid("a \"b\" <c> #d\ne"); got != "a #quot;b#quot; #lt;c#gt; #35;d e" {
		t.Errorf("mermaid = %q", got)
	}
	if got := code("a`b``c"); got != "```a`b``c```" {
		t.Errorf("code = %q", got)
	}
	if got := code("`x"); got != "`` `x ``" {
		t.Errorf("code = %q", got)
	}
	if got := fenced("", "a\n```\nb"); got != "````\na\n```\nb\n````" {
		t.Errorf("fenced = %q", got)
	}
	// The proposed change's name is the operator's too.
	e = passedRun()
	e.in.ProposedChange.Name = "a *bold* [link](x) <b>"
	if md := Markdown(e.document(), nil); !strings.HasPrefix(md,
		`## Fylgja rehearsed proposed change "a \*bold\* \[link\](x) \<b\>" on change-1`) {
		t.Errorf("the heading: %s", strings.SplitN(md, "\n", 2)[0])
	}
}

// A rehearsal refused before any run says no run was started, draws its stages not
// reached, and gives its reasons; a document with no block, refused before the proposed
// change was found, is its heading, its status, its findings and the caveat.
func TestMarkdownOfARefusal(t *testing.T) {
	md := Markdown(refusedRun().document(), pairs())
	for _, want := range []string{
		`## Fylgja did not rehearse proposed change "third link" on change-1`,
		"No run was started; stages resolved at 2026-10-17T14:02:11Z. Status **rejected**. Deadline 3840s (ceiling 3600s).",
		`  s0["change-1/seeded<br/>not reached"]`,
		"**Findings**:\n\n- `rehearsal.deadline.unfit` change-1: the stages need 3840s, over the ceiling of 3600s",
	} {
		if !strings.Contains(md, want) {
			t.Errorf("the refused rehearsal's markdown does not hold %q:\n%s", want, md)
		}
	}

	// A run refused at its baseline's start, another run holding the provision's id, says the
	// run touched nothing and needed no destroy, and rehearsed nothing (T078).
	md = Markdown(heldRun().document(), pairs())
	for _, want := range []string{
		`## Fylgja did not rehearse proposed change "third link" on change-1`,
		"Run `fylgja-rehearse " + rehearseRun + "` touched nothing, since a run already holds the id of its baseline's provision, " +
			"and no destroy was needed; stages resolved at 2026-10-17T14:02:11Z. Status **rejected**. Deadline 1980s (ceiling 3600s).",
		`  s1["change-1/seeded<br/>not reached"]`,
		"**Findings**:\n\n- `contract.node.missing` main: branch defines FylgjaContract but holds no instance of it\n" +
			"- `run.in_flight` fylgja-provision: the rehearsal's fylgja-provision could not start: a run is already in flight under its id",
	} {
		if !strings.Contains(md, want) {
			t.Errorf("the held rehearsal's markdown does not hold %q:\n%s", want, md)
		}
	}

	// A run whose end was not read says it was started, why its end was not read, and that it
	// goes on to its destroy; its stages read not read, and nothing says no run was started
	// (T079).
	if got, want := Markdown(lostRun().document(), pairs()), strings.Join([]string{
		`## Fylgja started rehearsing proposed change "third link" on change-1`,
		"",
		"Run `fylgja-rehearse " + rehearseRun + "` was started, and its end was not read: " + lostWhy + ". It goes on to its destroy, " +
			"and `fylgja twin show` says where it is. Stages resolved at 2026-10-17T14:02:11Z. Status **error**. Deadline 1980s (ceiling 3600s).",
		"",
		"| stage | at | bundle | step | wait | verify | new findings | verdict |",
		"|---|---|---|---|---|---|---|---|",
		"| change-1/branch-point | 2026-10-16T17:20:19.944651+00:00 | — | | | | | refused (contract.node.missing) |",
		"| change-1/seeded | 2026-10-16T17:25:30.118244+00:00 | 5c5c5c5c… | | | | | not read |",
		"| change-1/third-link | 2026-10-16T17:30:00.000000+00:00 | d0d0d0d0… | | | | | not read |",
		"| change-1/head | 2026-10-16T17:30:11.884302+00:00 | cccccccc… | | | | | not read |",
		"",
		"```mermaid",
		"flowchart LR",
		`  s0["change-1/branch-point<br/>refused"]`,
		`  s1["change-1/seeded<br/>not read"]`,
		`  s2["change-1/third-link<br/>not read"]`,
		`  s3["change-1/head<br/>not read"]`,
		`  s0 -. "not computed" .-> s1`,
		`  s1 -- "+link n1:e1-3 — n3:e1-3; ~n1, ~n3 (bootstrap, mapping); artifacts n1, n3" --> s2`,
		`  s2 -- "unchanged" --> s3`,
		"```",
		"",
		"**Findings**:",
		"",
		"- `contract.node.missing` main: branch defines FylgjaContract but holds no instance of it",
		"- `operation.failed` provision: " + lostWhy,
		"",
		"**Stages** (Infrahub's view does not show them):",
		"",
		"- `change-1/branch-point` main at 2026-10-16T17:20:19.944651+00:00 (branch point)",
		"- `change-1/seeded` change-1 at 2026-10-16T17:25:30.118244+00:00 (written) \"after the link is cabled\"",
		"- `change-1/third-link` change-1 at 2026-10-16T17:30:00.000000+00:00 (given) \"third link\"",
		"- `change-1/head` change-1 at 2026-10-16T17:30:11.884302+00:00 (head)",
		"",
		"**Warnings**: none",
		"",
		"**Baseline findings** (reported, failing nothing): none",
		"",
		Caveat,
		"",
	}, "\n"); got != want {
		t.Errorf("the markdown of a run whose end was not read:\n%s\nwant:\n%s", got, want)
	}

	var unknown findings.List
	unknown.AddStep(findings.Rejection, findings.StepResolve, findings.RuleStageUnknown, "change-9",
		"branch change-9 has no open proposed change")
	doc := findings.NewDocument(findings.OpTwinRehearse, &findings.Subject{Branch: "change-9"}, unknown)
	if got, want := Markdown(doc, nil), strings.Join([]string{
		"## Fylgja did not rehearse branch change-9",
		"",
		"Status **rejected**.",
		"",
		"**Findings**:",
		"",
		"- `stage.unknown` change-9: branch change-9 has no open proposed change",
		"",
		"**Warnings**: none",
		"",
		Caveat,
		"",
	}, "\n"); got != want {
		t.Errorf("a document with no block:\n%s\nwant:\n%s", got, want)
	}
}

// What a step changed is drawn by name for every kind of change: links removed, nodes added
// and removed, artifacts added and removed, by node; and a step with no change at all, not
// marked unchanged, is drawn unchanged (T087).
func TestMarkdownDrawsEveryChange(t *testing.T) {
	gone := step.Step{From: thirdID, To: badID,
		LinksRemoved:     []step.LinkRef{{ID: "l3", A: step.NodePort{Node: "n1", Port: "e1-3"}, B: step.NodePort{Node: "n3", Port: "e1-3"}}},
		NodesAdded:       []string{"n4"},
		NodesRemoved:     []string{"n2"},
		ArtifactsAdded:   []step.ArtifactRef{{Node: "n4", Name: "device-config"}},
		ArtifactsRemoved: []step.ArtifactRef{{Node: "n2", Name: "device-config"}}}
	for _, c := range []struct {
		name string
		s    step.Step
		want string
	}{
		{"removed and added", gone, "-link n1:e1-3 — n3:e1-3; +n4; -n2; artifacts n2, n4"},
		{"no change", step.Step{From: thirdID, To: headID}, "unchanged"},
	} {
		if got := changed(c.s); got != c.want {
			t.Errorf("%s: %q, want %q", c.name, got, c.want)
		}
	}
	md := Markdown(passedRun().document(), []step.Pair{step.Between(change+"/seeded", change+"/third-link", gone)})
	if want := `  s1 -- "-link n1:e1-3 — n3:e1-3; +n4; -n2; artifacts n2, n4" --> s2`; !strings.Contains(md, want) {
		t.Errorf("the drawing does not hold %s:\n%s", want, md)
	}
	carriesNoContent(t, "the drawing of every change", md)
}

// A step cell names a step cancelled before its stage or at a phase, rejected, one that
// could not run, and a push that did not land with no identifier, by its node alone (T087).
func TestStepCellOfEveryOutcome(t *testing.T) {
	cell := func(outcome, phase string, pushed ...findings.RehearsalPush) string {
		return stepCell(findings.RehearsalStage{Step: &findings.RehearsalStep{Outcome: outcome, Phase: phase, Pushed: pushed,
			Timings: findings.StepTimingsBlock{WholeS: 7.5}}})
	}
	for _, c := range []struct{ got, want string }{
		{cell(outcomeCancelled, ""), "cancelled before its stage"},
		{cell(outcomeCancelled, findings.StepReadiness), "cancelled at readiness"},
		{cell(outcomeRejected, ""), "rejected"},
		{cell(outcomeError, ""), "could not run"},
		{stepCell(findings.RehearsalStage{}), ""},
		{cell(wire.StepDiverged, findings.StepPush, findings.RehearsalPush{Node: "n1", Outcome: wire.PushLanded},
			findings.RehearsalPush{Node: "n3", Outcome: "failed"}), "diverged at push 7.5s; push n1; not landed n3"},
	} {
		if c.got != c.want {
			t.Errorf("step cell %q, want %q", c.got, c.want)
		}
	}
}

// The markdown of a run the deadline cut, of a baseline not built and of a destroy that left
// the lab, each pinned but for its stages, which TestMarkdown pins (T087).
func TestMarkdownOfACutAFailedBaselineAndAnUncleanDestroy(t *testing.T) {
	head := func(status, used string) string {
		return `## Fylgja rehearsed proposed change "third link" on change-1` + "\n\nRun `fylgja-rehearse " + rehearseRun +
			"`, stages resolved at 2026-10-17T14:02:11Z. Status **" + status + "**. " + used + " of the 1980s deadline (ceiling 3600s).\n\n" +
			"| stage | at | bundle | step | wait | verify | new findings | verdict |\n|---|---|---|---|---|---|---|---|\n"
	}
	const (
		bp     = "| change-1/branch-point | 2026-10-16T17:20:19.944651+00:00 | — | | | | | refused (contract.node.missing) |\n"
		base   = "| change-1/seeded | 2026-10-16T17:25:30.118244+00:00 | 5c5c5c5c… | created | settled after 3.2s | 15 held, 0 failed, 0 skipped | — | baseline |\n"
		link   = `  s1 -- "+link n1:e1-3 — n3:e1-3; ~n1, ~n3 (bootstrap, mapping); artifacts n1, n3" --> s2` + "\n"
		missed = "- `contract.node.missing` main: branch defines FylgjaContract but holds no instance of it\n"
		tail   = "**Warnings**: none\n\n**Baseline findings** (reported, failing nothing): none\n\n" + Caveat + "\n"
	)
	unclean := uncleanRun()
	uncleanDoc := unclean.document()
	uncleanDoc.Findings.AddStep(findings.Rejection, findings.StepTeardown, findings.RuleCleanupIncomplete, "lab fylgja",
		"clab destroy exited 1; fylgja twin destroy clears it")
	for _, c := range []struct {
		name  string
		doc   *findings.Document
		heads string
	}{
		{"cut", cutRun().document(), head("error", "2001.2s") +
			base +
			"| change-1/third-link | 2026-10-16T17:30:00.000000+00:00 | d0d0d0d0… | cancelled at readiness | | | | error |\n" +
			"| change-1/head | 2026-10-16T17:30:11.884302+00:00 | cccccccc… | | | | | not reached |\n\n" +
			"```mermaid\nflowchart LR\n" + `  s0["change-1/seeded<br/>baseline"]` + "\n" + `  s1["change-1/third-link<br/>error"]` + "\n" +
			`  s2["change-1/head<br/>not reached"]` + "\n" +
			`  s0 -- "+link n1:e1-3 — n3:e1-3; ~n1, ~n3 (bootstrap, mapping); artifacts n1, n3" --> s1` + "\n" +
			`  s1 -- "unchanged" --> s2` + "\n```\n\n**Findings**:\n\n" +
			"- `rehearsal.deadline.cut` change-1/third-link: the deadline of 1980s passed at stage change-1/third-link: change-1/seeded took 88.1s\n\n"},
		{"not built", notBuiltRun().document(), head("failed", "243.0s") + bp +
			"| change-1/seeded | 2026-10-16T17:25:30.118244+00:00 | 5c5c5c5c… | not built (failed at readiness) | | | — | error |\n" +
			"| change-1/third-link | 2026-10-16T17:30:00.000000+00:00 | d0d0d0d0… | | | | | not reached |\n\n" +
			"```mermaid\nflowchart LR\n" + `  s0["change-1/branch-point<br/>refused"]` + "\n" + `  s1["change-1/seeded<br/>error"]` + "\n" +
			`  s2["change-1/third-link<br/>not reached"]` + "\n" + `  s0 -. "not computed" .-> s1` + "\n" + link + "```\n\n**Findings**:\n\n" +
			missed + "- `readiness.timeout` n2: n2 did not answer its probe within 60s\n" +
			"- `rehearsal.baseline.failed` change-1/seeded: the baseline change-1/seeded could not be built: its provision ended failed at readiness\n\n"},
		{"unclean", uncleanDoc, head("unclean", "118.4s") + bp + base +
			"| change-1/third-link | 2026-10-16T17:30:00.000000+00:00 | d0d0d0d0… | stepped 4.5s; push n1, n3 | settled after 6.1s | 19 held, 0 failed, 0 skipped | none | passed |\n" +
			"| change-1/head | 2026-10-16T17:30:11.884302+00:00 | cccccccc… | unchanged | settled after 1.0s | 19 held, 0 failed, 0 skipped | none | passed |\n\n" +
			"```mermaid\nflowchart LR\n" + `  s0["change-1/branch-point<br/>refused"]` + "\n" + `  s1["change-1/seeded<br/>baseline"]` + "\n" +
			`  s2["change-1/third-link<br/>passed"]` + "\n" + `  s3["change-1/head<br/>passed"]` + "\n" + `  s0 -. "not computed" .-> s1` + "\n" +
			link + `  s2 -- "unchanged" --> s3` + "\n```\n\n**Findings**:\n\n" + "- `cleanup.incomplete` lab fylgja: clab destroy exited 1; fylgja twin destroy clears it\n" +
			missed + "\n"},
	} {
		md := Markdown(c.doc, pairs())
		if !strings.HasPrefix(md, c.heads+"**Stages** (Infrahub's view does not show them):\n") || !strings.HasSuffix(md, tail) {
			t.Errorf("%s: the markdown:\n%s\nwant it to begin:\n%s**Stages** …\nand end:\n%s", c.name, md, c.heads, tail)
		}
		if len(md) > CommentMax {
			t.Errorf("%s: %d bytes, over %d", c.name, len(md), CommentMax)
		}
		carriesNoContent(t, c.name+"'s markdown", md)
	}
}
