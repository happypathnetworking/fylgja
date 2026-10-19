package rehearsal

import (
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
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
		"Run `fylgja-rehearse 01a1b2c3-0000-7000-8000-0000000000aa`, stages resolved at 2026-10-17T14:02:11Z. Status **ok**. 118.4s of the 1950s deadline (ceiling 3600s).",
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
		"Run `fylgja-rehearse 01a1b2c3-0000-7000-8000-0000000000aa`, stages resolved at 2026-10-17T14:02:11Z. Status **nonconforming**. 301.6s of the 2580s deadline (ceiling 3600s).",
		"",
		"| stage | at | bundle | step | wait | verify | new findings | verdict |",
		"|---|---|---|---|---|---|---|---|",
		"| change-1/branch-point | 2026-10-16T17:20:19.944651+00:00 | — | | | | | refused (contract.node.missing) |",
		"| change-1/seeded | 2026-10-16T17:25:30.118244+00:00 | 5c5c5c5c… | created | expired after 120.0s | 14 held, 1 failed, 0 skipped | — | baseline |",
		"| change-1/third-link | 2026-10-16T17:30:00.000000+00:00 | d0d0d0d0… | stepped 4.5s; push n1, n3 | expired after 120.0s | 18 held, 1 failed, 0 skipped | none | passed |",
		"| change-1/bad-port | 2026-10-16T17:30:05.000000+00:00 | babababa… | diverged at push 29.8s; restarted n3; push n3; not landed n1 (push.refused) | expired after 120.0s | 18 held, 1 failed, 0 skipped | none | failed |",
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
