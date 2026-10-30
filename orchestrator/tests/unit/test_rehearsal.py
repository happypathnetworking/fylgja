"""The rehearsal's verdicts, block, text and markdown held to the Go implementation: the
goldens captured from the running build (`tests/golden/rehearsal.json`, `.txt`,
`.stderr.txt`, `.md` and `.full.md`) rendered byte for byte but for `fylgja-cli` in the
reproduce lines (FR-023, SC-007), and the block rebuilt from the run it reports; then every
case of `internal/rehearsal`'s `verdict_test.go`, `report_test.go` and `markdown_test.go`,
each carried over under its Go name in snake case."""

import json
import re
from pathlib import Path

import jsonschema
import pytest

from fylgja_orchestrator.documents import findings
from fylgja_orchestrator.documents import rehearsal as r
from fylgja_orchestrator.documents.deadline import ROLE_NOT_REACHED, ROLE_REHEARSED
from fylgja_orchestrator.documents.findings import REJECTION, WARNING, Document, Finding, Findings, new_document
from fylgja_orchestrator.documents.plan import Pair, StepDiff

from .rehearsal_examples import (
    ADDED,
    BASELINE_FINDING,
    CHANGE,
    HEAD_ID,
    HEAD_SNAPSHOT,
    LOST_WHY,
    REHEARSE_RUN,
    RESOLVED_AT,
    SCOPE,
    SEEDED_SNAPSHOT,
    STEP_RUN,
    THIRD_ID,
    THIRD_SNAPSHOT,
    F,
    alone_run,
    bad_port,
    branch_point,
    carries_no_content,
    counts,
    cut_at_push_run,
    cut_before_readiness_run,
    cut_run,
    destroyed,
    examples,
    failed_run,
    flow_of,
    head,
    held_run,
    loss_of,
    lost_run,
    new_finding_run,
    not_built_error_run,
    not_built_run,
    pairs,
    passed_run,
    probed_counts,
    probed_run,
    refused_run,
    restarted_run,
    seeded,
    step_to,
    third_link,
    unclean_run,
    unverified_run,
    wait,
)

GOLDEN = Path(__file__).resolve().parents[1] / "golden"


# The goldens.


def _cli_lines(text: str, indent: str = "") -> str:
    """The golden's text with `fylgja-cli` where the Go server's reproduce lines named
    `fylgja`: whole lines alone, so a finding's message that names the core's command keeps
    it."""
    old, new = indent + "fylgja twin ", indent + "fylgja-cli twin "
    return "".join(new + line[len(old):] if line.startswith(old) else line for line in text.splitlines(True))


def golden_document() -> Document:
    doc = Document.from_dict(json.loads((GOLDEN / "rehearsal.json").read_text()))
    doc.blocks["rehearsal"]["reproduce"] = r.reproduce(doc.blocks["rehearsal"], doc.subject["scope"])
    return doc


def golden_steps() -> list:
    return json.loads((GOLDEN / "plan.json").read_text())["plan"]["steps"]


def test_the_golden_reproduce_lines():
    block = json.loads((GOLDEN / "rehearsal.json").read_text())["rehearsal"]
    want = [line.replace("fylgja twin ", "fylgja-cli twin ", 1) for line in block["reproduce"]]
    assert r.reproduce(block, "tag:fylgja") == want


def test_the_golden_document():
    # The README's one hand edit, <state-root>, is the destroy's report carried through,
    # which Go's encoder writes escaped.
    raw = (GOLDEN / "rehearsal.json").read_text().replace("<state-root>", "\\u003cstate-root\\u003e")
    assert golden_document().json() == raw.replace('"fylgja twin ', '"fylgja-cli twin ')
    findings.validate(golden_document().to_dict())


def test_the_golden_markdown():
    md = r.markdown(golden_document(), golden_steps())
    assert md == _cli_lines((GOLDEN / "rehearsal.md").read_text())
    assert len(md.encode()) <= r.COMMENT_MAX
    # The whole form, which the shortened one is because it is over a comment.
    pairs_ = [Pair.from_dict(s) for s in golden_steps()]
    full = r._join(r._parts(golden_document(), pairs_, False))
    assert full == _cli_lines((GOLDEN / "rehearsal.full.md").read_text())
    assert len(full.encode()) > r.COMMENT_MAX


def test_the_golden_text():
    doc = golden_document()
    assert r.text(doc) == _cli_lines((GOLDEN / "rehearsal.txt").read_text(), "  ")
    assert doc.text() == (GOLDEN / "rehearsal.stderr.txt").read_text()
    out = (GOLDEN / "rehearsal.out.txt").read_text()
    assert out.endswith((GOLDEN / "rehearsal.txt").read_text())


def golden_run() -> tuple[r.Input, r.Result]:
    """The golden rehearsal's plan and run as the flow fills them: each stage's plan
    findings (resolve, read, compile), each child's own (the step's push.refused and
    step.diverged), the waits, counts and timings the core reported."""
    doc = json.loads((GOLDEN / "rehearsal.json").read_text())
    b = doc["rehearsal"]
    stages, results = [], []
    for s in b["stages"]:
        mine = [Finding.from_dict(f) for f in s["findings"]]
        plan = [f for f in mine if f.step in ("resolve", "read", "compile")]
        child = [f for f in mine if f not in plan and not f.rule.startswith("rehearsal.")]
        role = ROLE_REHEARSED if s["role"] == ROLE_NOT_REACHED else s["role"]
        stages.append(r.Stage(s["ref"], s["label"], s["description"], s["at_source"], s.get("branch", ""),
                              s.get("at", ""), s["snapshot_id"] or "", s["bundle_id"] or "", role, plan))
        if s["verdict"] in (r.VERDICT_REFUSED, r.VERDICT_NOT_REACHED):
            continue
        p, st = s["provision"], s["step"]
        provision = r.Provision(p["outcome"], p["run"]["run_id"]) if p else None
        step = r.StepRun(st["outcome"], st.get("phase", ""), "", st["run"]["run_id"], st["restarted"],
                         st["recreated"], st["created"], st["pushed"], st["timings"]) if st else None
        w = dict(s["wait"], failing=[])
        results.append(r.StageResult(s["ref"], s["verdict"], provision, step, w, s["verify"], s["loss"],
                                     s["new_findings"], child, s["took_s"]))
    pc = b["proposed_change"]
    inp = r.Input(pc, b["resolved_at"], doc["subject"]["scope"], b["deadline_s"], b["ceiling_s"], b["reclaimed"],
                  stages)
    return inp, r.Result(r.OUTCOME_STAGE_FAILED, b["run"], b["used_s"], results, b["destroy"])


def test_the_golden_block_is_built_from_its_run():
    inp, res = golden_run()
    assert r.build(inp, res) == golden_document().blocks["rehearsal"]


def test_the_golden_verdicts():
    inp, res = golden_run()
    third, bad = res.stages[1], res.stages[2]
    assert r.classify(r.StepOutcome(third.step.outcome), third.wait, [], False) == (r.VERDICT_PASSED, [])
    assert r.classify(r.StepOutcome(bad.step.outcome, bad.step.phase, "push"), bad.wait, [], False) == (
        r.VERDICT_FAILED, [])


# verdict_test.go


NEIGHBOR_N1 = {"rule": "verify.neighbor", "object": "n1:ethernet-1/2",
               "message": "node n1 (172.20.20.2): port ethernet-1/2 sees no neighbour"}
NEIGHBOR_N3 = {"rule": "verify.neighbor", "object": "n3:ethernet-1/3",
               "message": "node n3 (172.20.20.4): port ethernet-1/3 sees no neighbour"}
PORT_N1 = {"rule": "verify.port.enabled", "object": "n1:ethernet-1/2",
           "message": 'node n1 (172.20.20.2): port ethernet-1/2 reads "disable"'}
RECORD_N2 = {"rule": "verify.record.holds", "object": "n2", "message": "the record says n2 holds the previous bundle"}


def wait_of(outcome: str, *failing: dict) -> dict:
    return {"outcome": outcome, "budget_s": 120, "reads": 3, "after_s": 4.2, "failing": list(failing)}


def stepped(outcome: str) -> r.StepOutcome:
    return r.StepOutcome(outcome)


BASELINE = [NEIGHBOR_N1]


@pytest.mark.parametrize("name,step,w,baseline,cut,want,added", [
    ("a finding the baseline had", stepped("stepped"), wait_of("expired", NEIGHBOR_N1), BASELINE, False,
     r.VERDICT_PASSED, []),
    ("a finding the baseline did not have", stepped("stepped"), wait_of("expired", NEIGHBOR_N1, NEIGHBOR_N3), BASELINE,
     False, r.VERDICT_FAILED, [NEIGHBOR_N3]),
    ("another rule on the baseline's object", stepped("stepped"), wait_of("expired", PORT_N1), BASELINE, False,
     r.VERDICT_FAILED, [PORT_N1]),
    ("a finding the baseline alone had fails nothing", stepped("stepped"), wait_of("settled"), BASELINE, False,
     r.VERDICT_PASSED, []),
    ("unchanged and settled", stepped("unchanged"), wait_of("settled"), [], False, r.VERDICT_PASSED, []),
    ("verify.record.holds is ignored if present", stepped("stepped"), wait_of("expired", RECORD_N2), [], False,
     r.VERDICT_PASSED, []),
    ("a wait incomplete", stepped("stepped"), wait_of("incomplete", NEIGHBOR_N3), BASELINE, False, r.VERDICT_ERROR, []),
    ("a wait cancelled", stepped("unchanged"), wait_of("cancelled"), [], False, r.VERDICT_ERROR, []),
    ("no wait", stepped("stepped"), None, [], False, r.VERDICT_ERROR, []),
    ("cut mid-step", r.StepOutcome("cancelled", "readiness"), None, BASELINE, True, r.VERDICT_ERROR, []),
    ("cut after a settled wait", stepped("stepped"), wait_of("settled"), [], True, r.VERDICT_ERROR, []),
    ("the step gave no result", None, None, [], False, r.VERDICT_ERROR, []),
    ("rejected by its locks", r.StepOutcome("rejected", step="inspect"), None, [], False, r.VERDICT_ERROR, []),
    ("could not run", r.StepOutcome("error", step="host_check"), None, [], False, r.VERDICT_ERROR, []),
    ("cancelled before its stage", r.StepOutcome("cancelled", step="compare"), None, [], False, r.VERDICT_ERROR, []),
    ("an outcome unknown", stepped("waiting"), wait_of("settled"), [], False, r.VERDICT_ERROR, []),
])
def test_verdict(name, step, w, baseline, cut, want, added):
    assert r.classify(step, w, baseline, cut) == (want, added), name


@pytest.mark.parametrize("phase", ["reconcile", "readiness", "push", "record"])
def test_verdict_of_a_divergence(phase):
    # A divergence at each phase fails the stage, whatever its wait; its wait's new findings
    # are reported when it read every node.
    diverged = r.StepOutcome("diverged", phase, phase)
    assert r.classify(diverged, wait_of("expired", NEIGHBOR_N1, NEIGHBOR_N3), BASELINE, False) == (
        r.VERDICT_FAILED, [NEIGHBOR_N3])
    assert r.classify(diverged, wait_of("incomplete", NEIGHBOR_N3), BASELINE, False) == (r.VERDICT_FAILED, [])
    assert r.classify(diverged, None, BASELINE, False)[0] == r.VERDICT_FAILED


def test_cancelled_before_stage():
    assert r.StepOutcome("cancelled").cancelled_before_stage()
    assert not r.StepOutcome("cancelled", "push").cancelled_before_stage()
    assert not r.StepOutcome("diverged", "push").cancelled_before_stage()


def test_new_findings():
    # The stage's order kept, every one the baseline has dropped by rule and object, whatever
    # the message.
    moved = dict(NEIGHBOR_N1, message="node n1 (172.20.20.2): port ethernet-1/2 sees n4 ethernet-1/1")
    assert r.new_findings([NEIGHBOR_N1], [NEIGHBOR_N3, RECORD_N2, moved, PORT_N1]) == [NEIGHBOR_N3, PORT_N1]
    assert r.new_findings([], []) == []


def test_stop():
    for v, want in {r.VERDICT_PASSED: False, r.VERDICT_BASELINE: False, r.VERDICT_REFUSED: False,
                    r.VERDICT_FAILED: True, r.VERDICT_ERROR: True, r.VERDICT_NOT_REACHED: True}.items():
        assert r.stop(v) == want, v


BURST = {"rule": "verify.burst", "object": "n1-loop",
         "message": "probe n1-loop: 0 of 5 replies from n1-loop-b at 10.1.11.2"}


@pytest.mark.parametrize("name,step,w,baseline,added", [
    ("the burst alone", stepped("stepped"), wait_of("expired", BURST), [], [BURST]),
    ("the burst against a baseline that had none", stepped("stepped"), wait_of("expired", BURST), BASELINE, [BURST]),
    ("beside a finding the baseline had", stepped("stepped"), wait_of("expired", NEIGHBOR_N1, BURST), BASELINE,
     [BURST]),
    ("beside a finding the baseline did not have", stepped("stepped"), wait_of("expired", NEIGHBOR_N3, BURST),
     BASELINE, [NEIGHBOR_N3, BURST]),
    ("on an unchanged step", stepped("unchanged"), wait_of("expired", BURST), [], [BURST]),
    ("diverged at its flows", r.StepOutcome("diverged", "flows", "flows"), wait_of("expired", BURST), [], [BURST]),
])
def test_a_burst_failed_fails_the_stage(name, step, w, baseline, added):
    assert r.classify(step, w, baseline, False) == (r.VERDICT_FAILED, added), name


# report_test.go


def carries_finding(found, severity: str, rule: str, obj: str) -> bool:
    for f in found:
        f = f if isinstance(f, Finding) else Finding.from_dict(f)
        if f.severity == severity and f.rule == rule and f.object == obj:
            return True
    return False


@pytest.mark.parametrize("e", examples(), ids=lambda e: e.name)
def test_block_validates(e):
    doc = e.document()
    findings.validate(doc.to_dict())
    carries_no_content(e.name, doc.json())
    assert len(doc.blocks["rehearsal"]["stages"]) == len(e.inp.stages)


def test_block_validates_reads_the_contract():
    doc = passed_run().document()
    doc.blocks["rehearsal"]["stages"][1]["verdict"] = "skipped"
    with pytest.raises(jsonschema.ValidationError):
        findings.validate(doc.to_dict())


def _roles(b: dict) -> list:
    return [(s["role"], s["verdict"]) for s in b["stages"]]


@pytest.mark.parametrize("e,want,baseline", [
    (passed_run(), [("refused", "refused"), ("baseline", "baseline"), ("rehearsed", "passed"),
                    ("rehearsed", "passed")], True),
    (failed_run(), [("refused", "refused"), ("baseline", "baseline"), ("rehearsed", "passed"), ("rehearsed", "failed"),
                    ("not_reached", "not_reached")], True),
    (cut_run(), [("baseline", "baseline"), ("rehearsed", "error"), ("not_reached", "not_reached")], True),
    (not_built_run(), [("refused", "refused"), ("baseline", "error"), ("not_reached", "not_reached")], False),
    (unverified_run(), [("refused", "refused"), ("baseline", "error"), ("not_reached", "not_reached")], False),
    (refused_run(), [("not_reached", "not_reached")] * 4, False),
    (held_run(), [("refused", "refused"), ("not_reached", "not_reached"), ("not_reached", "not_reached")], False),
], ids=lambda x: x.name if hasattr(x, "name") else "")
def test_build_roles_and_verdicts(e, want, baseline):
    b = e.block()
    assert _roles(b) == want
    assert (b["baseline"] is not None) == baseline


def test_build_roles_and_verdicts_beyond_the_table():
    # The run lists the stages after the one that stopped it as not reached, which reads as
    # a result that leaves them out.
    listed = failed_run()
    listed.res.stages.append(r.StageResult(listed.inp.stages[-1].ref, r.VERDICT_NOT_REACHED))
    assert listed.block() == failed_run().block()

    # The baseline's findings are its wait's; a later stage's repeat is a warning of its own,
    # prefixed by the stage, and never a new finding.
    b = failed_run().block()
    assert b["baseline"]["findings"] == [BASELINE_FINDING]
    third = b["stages"][2]
    assert third["new_findings"] == []
    assert carries_finding(third["findings"], WARNING, "verify.neighbor", CHANGE + "/third-link: n1:ethernet-1/2")

    # A baseline whose wait settled keeps its findings as one that expired does.
    settled = passed_run()
    settled.res.stages[0].wait = wait("settled", 3.2, 2, BASELINE_FINDING)
    assert settled.block()["baseline"]["findings"] == [BASELINE_FINDING]

    # A baseline built whose wait could not complete is error and has no baseline findings
    # (T100).
    doc = unverified_run().document()
    seeded_ = doc.blocks["rehearsal"]["stages"][1]
    assert doc.blocks["rehearsal"]["baseline"] is None
    for found in (seeded_["findings"], doc.findings):
        assert carries_finding(found, WARNING, "operation.failed", CHANGE + "/seeded: " + REHEARSE_RUN)
        assert carries_finding(found, REJECTION, "rehearsal.stage.error", CHANGE + "/seeded")
    assert r.closing(doc) == ("rehearsal error: stage change-1/seeded could not be rehearsed: its wait ended "
                              "incomplete after 0.0s; the twin is destroyed")


@pytest.mark.parametrize("e,stage,rule,step,message", [
    (failed_run(), 3, "rehearsal.stage.failed", "push",
     "diverged at phase push: landed n3; not landed n1 (push.refused)"),
    (new_finding_run(), 1, "rehearsal.stage.failed", "observe",
     "its wait holds a finding the baseline's did not: verify.neighbor n1:ethernet-1/3"),
    (cut_run(), 1, "rehearsal.deadline.cut", "readiness",
     "the deadline of 1980s passed at stage change-1/third-link: change-1/seeded took 88.1s"),
    (not_built_run(), 1, "rehearsal.baseline.failed", "provision",
     "the baseline change-1/seeded could not be built: its provision ended failed at readiness"),
    (not_built_error_run(), 1, "rehearsal.stage.error", "deploy", "its provision ended error at deploy"),
], ids=lambda x: x.name if hasattr(x, "name") else "")
def test_build_files_the_rehearsals_own_findings(e, stage, rule, step, message):
    b = e.block()
    st = b["stages"][stage]
    found = [f for f in st["findings"] if f["rule"] == rule]
    assert found, rule
    f = found[-1]
    assert (f["severity"], f.get("step"), f["message"], f["object"]) == (REJECTION, step, message, st["ref"])


def test_build_files_the_rehearsals_own_findings_beyond_the_table():
    # A step that could not run is rehearsal.stage.error at the step it stopped at; a run
    # cancelled by the operator files none of the rehearsal's.
    rejected = cut_run()
    rejected.res.outcome = r.OUTCOME_STAGE_ERROR
    locked = step_to(CHANGE + "/third-link", 1, "rejected", 0.4)
    locked.step = "inspect"
    rejected.res.stages[1].step = locked
    b = rejected.block()
    assert carries_finding(b["stages"][1]["findings"], REJECTION, "rehearsal.stage.error", CHANGE + "/third-link")
    assert b["stages"][1]["findings"][0]["step"] == "inspect"
    cancelled = cut_run()
    cancelled.res.outcome = r.OUTCOME_CANCELLED
    assert cancelled.block()["stages"][1]["findings"] == []


def test_baseline_whose_provision_did_not_start():
    e = not_built_error_run()
    e.res.destroy = destroyed()
    e.res.stages = [r.StageResult(CHANGE + "/seeded", r.VERDICT_ERROR, took_s=0.4, findings=[
        F(REJECTION, "provision", "operation.failed", "fylgja-provision",
          "the child workflow could not start: the workflow service did not answer")])]
    doc = e.document()
    own = [f for f in doc.blocks["rehearsal"]["stages"][1]["findings"] if f["rule"] == "rehearsal.stage.error"]
    assert len(own) == 1 and own[0]["message"] == "its provision did not run"
    assert r.closing(doc) == ("rehearsal error: stage change-1/seeded could not be rehearsed: its provision did not "
                              "run; the twin is destroyed")
    for line in r.stage_lines(doc.blocks["rehearsal"]):
        assert "step" not in line


def _copy_of(s: r.Stage, label: str) -> r.Stage:
    s.ref, s.label, s.role = CHANGE + "/" + label, label, ROLE_REHEARSED
    return s


def _unchanged_at(ref: str, n: int, v: str, w: dict, c: dict, *new: dict) -> r.StageResult:
    """An unchanged step into ref whose wait holds failing, new the ones the baseline's did
    not."""
    return r.StageResult(ref, v, step=step_to(ref, n, "unchanged", 0.9), wait=w, counts=c, new_findings=list(new),
                         took_s=w["after_s"] + 0.9)


def test_reproduce():
    assert passed_run().block()["reproduce"] == []
    assert cut_run().block()["reproduce"] == []

    # The failure at the first rehearsed stage.
    assert new_finding_run().block()["reproduce"] == [
        "fylgja-cli twin create --stage change-1/seeded --scope tag:fylgja",
        "fylgja-cli twin step --stage change-1/third-link --allow-restart",
        "fylgja-cli twin verify", "fylgja-cli twin destroy"]

    # The create names the scope every stage was read under, always; each step takes none.
    edge = new_finding_run()
    edge.inp.scope = "tag:edge"
    assert edge.block()["reproduce"] == [
        "fylgja-cli twin create --stage change-1/seeded --scope tag:edge",
        "fylgja-cli twin step --stage change-1/third-link --allow-restart",
        "fylgja-cli twin verify", "fylgja-cli twin destroy"]

    # The failure at the third rehearsed stage, after the refused branch point.
    third = failed_run()
    third.inp.stages = [branch_point(), seeded(), third_link(ROLE_REHEARSED),
                        r.Stage(CHANGE + "/live", "live", at_source="given", branch=CHANGE,
                                at="2026-10-16T17:30:02.000000+00:00", bundle_id=THIRD_ID, role=ROLE_REHEARSED),
                        bad_port(ROLE_REHEARSED), head(ROLE_REHEARSED)]
    import copy
    live = copy.deepcopy(third.res.stages[1])
    live.ref = CHANGE + "/live"
    third.res.stages = third.res.stages[:2] + [live] + third.res.stages[2:]
    assert third.block()["reproduce"] == [
        "fylgja-cli twin create --stage change-1/seeded --scope tag:fylgja",
        "fylgja-cli twin step --stage change-1/third-link --allow-restart",
        "fylgja-cli twin step --stage change-1/live --allow-restart",
        "fylgja-cli twin step --stage change-1/bad-port --allow-restart",
        "fylgja-cli twin verify", "fylgja-cli twin destroy"]


def _sharing_cases():
    sharing = new_finding_run()
    sharing.inp.stages = [seeded(), _copy_of(seeded(), "seeded-copy"), third_link(ROLE_REHEARSED),
                          head(ROLE_REHEARSED)]
    sharing.res.stages = [sharing.res.stages[0], _unchanged_at(CHANGE + "/seeded-copy", 1, r.VERDICT_PASSED,
                                                               wait("settled", 1.0, 1), counts(6, 0)),
                          sharing.res.stages[1]]
    pair_of = failed_run()
    pair_of.inp.stages = [branch_point(), seeded(), third_link(ROLE_REHEARSED),
                          _copy_of(third_link(ROLE_REHEARSED), "third-copy"), bad_port(ROLE_REHEARSED),
                          head(ROLE_REHEARSED)]
    pair_of.res.stages = [pair_of.res.stages[0], pair_of.res.stages[1],
                          _unchanged_at(CHANGE + "/third-copy", 3, r.VERDICT_PASSED,
                                        wait("expired", 120, 58, BASELINE_FINDING), counts(8, 1)),
                          pair_of.res.stages[2]]
    failed_copy = failed_run()
    failed_copy.inp.stages = [branch_point(), seeded(), third_link(ROLE_REHEARSED),
                              _copy_of(third_link(ROLE_REHEARSED), "third-copy"), head(ROLE_REHEARSED)]
    failed_copy.res.stages = [failed_copy.res.stages[0], failed_copy.res.stages[1],
                              _unchanged_at(CHANGE + "/third-copy", 3, r.VERDICT_FAILED,
                                            wait("expired", 120, 61, BASELINE_FINDING, ADDED), counts(8, 2), ADDED)]
    failed_at_baseline = new_finding_run()
    failed_at_baseline.inp.stages = [seeded(), _copy_of(seeded(), "seeded-copy"), head(ROLE_REHEARSED)]
    failed_at_baseline.res.stages = [failed_at_baseline.res.stages[0],
                                     _unchanged_at(CHANGE + "/seeded-copy", 1, r.VERDICT_FAILED,
                                                   wait("expired", 120, 61, ADDED), counts(6, 1), ADDED)]
    create = "fylgja-cli twin create --stage change-1/seeded --scope tag:fylgja"
    return [
        ("a mark at the baseline's at", sharing, [
            create, "fylgja-cli twin step --stage change-1/third-link --allow-restart",
            "fylgja-cli twin verify", "fylgja-cli twin destroy"]),
        ("two marks sharing an at before the failed stage", pair_of, [
            create, "fylgja-cli twin step --stage change-1/third-link --allow-restart",
            "fylgja-cli twin step --stage change-1/bad-port --allow-restart",
            "fylgja-cli twin verify", "fylgja-cli twin destroy"]),
        ("a failed stage at the at of the stage before it", failed_copy, [
            create, "fylgja-cli twin step --stage change-1/third-link --allow-restart",
            "fylgja-cli twin verify", "fylgja-cli twin destroy"]),
        ("a failed stage at the baseline's at", failed_at_baseline, [
            create, "fylgja-cli twin verify --wait", "fylgja-cli twin destroy"]),
    ]


@pytest.mark.parametrize("name,e,want", _sharing_cases(), ids=lambda x: x if isinstance(x, str) else "")
def test_reproduce_leaves_out_a_stage_at_the_last_at(name, e, want):
    # A mark sharing the branch and at of the last stage a command named is left out; a
    # failed stage so left out is reproduced by the verify alone (T099, T107).
    assert e.block()["reproduce"] == want, name
    doc = e.document()
    assert r.closing(doc).endswith("reproduce it by hand:\n  " + "\n  ".join(want)), name
    md = r.markdown(doc)
    assert "**Reproduce by hand**:\n\n```\n" + "\n".join(want) + "\n```\n" in md, name
    assert len(md.encode()) <= r.COMMENT_MAX


@pytest.mark.parametrize("ref,want", [
    ("change-1/seeded", "change-1/seeded"), ("change-1/it's", "'change-1/it'\\''s'"),
    ("change-1/a;b", "'change-1/a;b'"), ("change-1/$HOME", "'change-1/$HOME'"),
    ('change-1/"x"', "'change-1/\"x\"'"),
])
def test_reproduce_quotes_a_word_a_shell_reads(ref, want):
    assert r.shell_word(ref) == want


REPRODUCE_FAILED = ("\n  fylgja-cli twin create --stage change-1/seeded --scope tag:fylgja"
                    "\n  fylgja-cli twin step --stage change-1/third-link --allow-restart"
                    "\n  fylgja-cli twin step --stage change-1/bad-port --allow-restart"
                    "\n  fylgja-cli twin verify\n  fylgja-cli twin destroy")


@pytest.mark.parametrize("e,lines,closing", [
    (passed_run(), [
        "stage change-1/branch-point: refused (scope.empty)",
        "stage change-1/seeded: created; settled after 3.2s (2 reads); 15 held, 0 failed, 0 skipped; baseline",
        "stage change-1/third-link: stepped in 4.5s (push n1 2.5s, n3 2.6s); settled after 6.1s (4 reads); "
        "19 held, 0 failed, 0 skipped; passed",
        "stage change-1/head: unchanged in 0.9s; settled after 1.0s (1 read); 19 held, 0 failed, 0 skipped; passed",
    ], "rehearsal ok: 3 stages rehearsed, every one passed; the twin is destroyed; 118.4s of the 1980s deadline"),
    (failed_run(), [
        "stage change-1/branch-point: refused (scope.empty)",
        "stage change-1/seeded: created; expired after 120.0s (58 reads); 14 held, 1 failed, 0 skipped; baseline",
        "stage change-1/third-link: stepped in 4.5s (push n1 2.5s, n3 2.6s); expired after 120.0s (60 reads); "
        "18 held, 1 failed, 0 skipped; passed",
        "stage change-1/bad-port: diverged at phase push: restarted n3 61.2s; landed n3; not landed n1 "
        "(push.refused); expired after 120.0s (58 reads); 18 held, 1 failed, 0 skipped; failed",
        "stage change-1/head: not reached",
    ], "rehearsal nonconforming: stage change-1/bad-port failed at phase push; the twin is destroyed; reproduce it by "
       "hand:" + REPRODUCE_FAILED),
    (new_finding_run(), [
        "stage change-1/seeded: created; settled after 3.2s (2 reads); 15 held, 0 failed, 0 skipped; baseline",
        "stage change-1/third-link: stepped in 4.5s (push n1 2.5s, n3 2.6s); expired after 120.0s (61 reads); "
        "18 held, 1 failed, 0 skipped; failed: verify.neighbor n1:ethernet-1/3",
        "stage change-1/head: not reached",
    ], "rehearsal nonconforming: stage change-1/third-link failed: verify.neighbor n1:ethernet-1/3; the twin is "
       "destroyed; reproduce it by hand:\n  fylgja-cli twin create --stage change-1/seeded --scope tag:fylgja"
       "\n  fylgja-cli twin step --stage change-1/third-link --allow-restart"
       "\n  fylgja-cli twin verify\n  fylgja-cli twin destroy"),
    (cut_run(), [
        "stage change-1/seeded: created; settled after 3.2s (2 reads); 15 held, 0 failed, 0 skipped; baseline",
        "stage change-1/third-link: cancelled at phase readiness; error: the deadline passed",
        "stage change-1/head: not reached",
    ], "rehearsal error: the deadline of 1980s passed at stage change-1/third-link; the twin is destroyed"),
    (not_built_run(), [
        "stage change-1/branch-point: refused (scope.empty)",
        "stage change-1/seeded: not built: its provision ended failed at readiness",
        "stage change-1/third-link: not reached",
    ], "rehearsal failed: the baseline change-1/seeded could not be built: its provision ended failed at readiness; "
       "the twin is destroyed"),
    (not_built_error_run(), [
        "stage change-1/branch-point: refused (scope.empty)",
        "stage change-1/seeded: not built: its provision ended error at deploy; error",
        "stage change-1/third-link: not reached",
    ], "rehearsal error: stage change-1/seeded could not be rehearsed: its provision ended error at deploy; the twin "
       "is destroyed"),
    (unclean_run(), None,
     "rehearsal unclean: 3 stages rehearsed, every one passed; the destroy left lab fylgja (1 container); twin "
     "destroy clears it"),
    (alone_run(), [
        "stage change-1/seeded: created; settled after 3.2s (2 reads); 15 held, 0 failed, 0 skipped; baseline",
    ], "rehearsal ok: the baseline alone was built and verified, and no step was rehearsed; the twin is destroyed; "
       "61.2s of the 720s deadline"),
    (refused_run(), [
        "stage change-1/seeded: not reached", "stage change-1/third-link: not reached",
        "stage change-1/bad-port: not reached", "stage change-1/head: not reached",
    ], "rehearsal rejected: nothing was started"),
    (held_run(), [
        "stage change-1/branch-point: refused (scope.empty)",
        "stage change-1/seeded: not reached", "stage change-1/third-link: not reached",
    ], "rehearsal rejected: the run touched nothing, since a run already holds the id of its baseline's provision; "
       "no destroy was needed"),
    (lost_run(), None, "rehearsal error: run fylgja-rehearse " + REHEARSE_RUN + " was started and its end was not "
     "read (" + LOST_WHY + "); it goes on to its destroy, and fylgja twin show says where it is"),
], ids=lambda x: x.name if hasattr(x, "name") else "")
def test_stage_lines_and_closing(e, lines, closing):
    if lines is not None:
        assert r.stage_lines(e.block()) == lines
    assert r.closing(e.document()) == closing


@pytest.mark.parametrize("name,e,at,want", [
    ("stepped, a node restarted and one recreated", restarted_run(), 2,
     "stage change-1/third-link: stepped in 95.3s (restarted n3 61.2s; recreated n1 70.4s; push n1 2.5s, n3 2.6s); "
     "settled after 6.1s (4 reads); 19 held, 0 failed, 0 skipped; passed"),
    ("cut before its readiness answered", cut_before_readiness_run(), 3,
     "stage change-1/bad-port: cancelled at phase readiness: restarted n3; error: the deadline passed"),
    ("cut at its push", cut_at_push_run(), 3,
     "stage change-1/bad-port: cancelled at phase push: restarted n3 61.2s; landed n3; not landed n1 (not attempted); "
     "error: the deadline passed"),
])
def test_stage_lines_name_the_restarts(name, e, at, want):
    assert r.stage_lines(e.block())[at] == want, name


def _closing_of(b: dict, status: str) -> str:
    return r.closing(Document("twin.rehearse", status, blocks={"rehearsal": b}))


def test_stage_lines_and_closing_beyond_the_table():
    # The block is what it was: the cut stage's finding is the deadline's, and its step still
    # carries the node it restarted.
    cut = cut_before_readiness_run().block()["stages"][3]
    rules = [f["rule"] for f in cut["findings"]]
    assert "rehearsal.deadline.cut" in rules and "rehearsal.stage.failed" not in rules
    assert cut["step"]["restarted"] == ["n3"]

    # A step that could not run, and a run the operator cancelled, each say so.
    locked = cut_run()
    locked.res.outcome = r.OUTCOME_STAGE_ERROR
    st = step_to(CHANGE + "/third-link", 1, "rejected", 0.4)
    st.step = "inspect"
    locked.res.stages[1].step = st
    b = locked.block()
    assert r.stage_lines(b)[1] == "stage change-1/third-link: rejected; error: its step was rejected"
    assert _closing_of(b, "error") == ("rehearsal error: stage change-1/third-link could not be rehearsed: its step "
                                       "was rejected; the twin is destroyed")
    cancelled = cut_run()
    cancelled.res.outcome = r.OUTCOME_CANCELLED
    assert _closing_of(cancelled.block(), "error") == ("rehearsal error: the run was cancelled at stage "
                                                       "change-1/third-link; the twin is destroyed")
    incomplete = passed_run()
    incomplete.res.outcome = r.OUTCOME_STAGE_ERROR
    incomplete.res.stages[2].verdict = r.VERDICT_ERROR
    incomplete.res.stages[2].wait = wait("incomplete", 120, 40)
    assert r.stage_lines(incomplete.block())[3] == (
        "stage change-1/head: unchanged in 0.9s; incomplete after 120.0s (40 reads); 19 held, 0 failed, 0 skipped; "
        "error: its wait ended incomplete after 120.0s")


def test_block_of_a_run_whose_end_was_not_read():
    doc = lost_run().document()
    b = doc.blocks["rehearsal"]
    assert b["run"]["run_id"] == REHEARSE_RUN and b["destroy"] is None and b["baseline"] is None
    assert b["reproduce"] == []
    for s in b["stages"][1:]:
        assert (s["role"], s["verdict"], s["findings"]) == (ROLE_NOT_REACHED, r.VERDICT_NOT_REACHED, [])
    closing = r.closing(doc)
    for never in ("nothing was started", "every one passed", "the twin is destroyed", "did not report"):
        assert never not in closing


def _compact(value) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def test_findings_are_the_stages_in_order():
    b = failed_run().block()
    found = r.findings_of(b)
    assert len(found) == sum(len(s["findings"]) for s in b["stages"])
    assert found[0].rule == "scope.empty"
    raw = _compact(b)
    for want in ('"reclaimed":null', '"new_findings":[]', '"provision":null'):
        assert want in raw


def test_the_verify_cell_counts_the_burst():
    unread = probed_counts(8, 0, False)
    unread["burst"] = {"held": 0, "failed": 0, "unread": 1}
    for name, c, want in [
        ("no probe", counts(8, 0), "19 held, 0 failed, 0 skipped"),
        ("a burst held", probed_counts(8, 0, False), "20 held, 0 failed, 0 skipped"),
        ("a burst failed", probed_counts(8, 0, True), "19 held, 1 failed, 0 skipped"),
        ("a burst not run", unread, "19 held, 0 failed, 0 skipped, 1 unread"),
    ]:
        assert r.counts_text(c) == want, name

    e = probed_run()
    burst = {"rule": "verify.burst", "object": "n1-loop",
             "message": "probe n1-loop: 4 of 5 replies from n1-loop-b at 10.1.11.2"}
    e.res.outcome = r.OUTCOME_STAGE_FAILED
    third = e.res.stages[1]
    third.verdict, third.wait = r.VERDICT_FAILED, wait("expired", 120, 60, burst)
    third.counts = probed_counts(8, 0, True)
    third.new_findings = [burst]
    assert r.stage_lines(e.block())[1] == (
        "stage change-1/third-link: stepped in 64.5s (push n1 2.5s, n3 2.6s); expired after 120.0s (60 reads); "
        "19 held, 1 failed, 0 skipped; loss n1-loop 274/300, gap 54.8s; failed: verify.burst n1-loop")
    assert ("| expired after 120.0s | 19 held, 1 failed, 0 skipped | n1-loop 274/300, gap 54.8s | verify.burst n1-loop "
            "| failed |\n") in r.markdown(e.document(), pairs())


def test_each_stage_carries_its_steps_loss():
    e = probed_run()
    e.inp.stages.append(bad_port(ROLE_REHEARSED))
    b = e.block()
    assert b["stages"][1]["loss"] == loss_of(flow_of("n1-loop", "measured", 300, 274, 54.8))
    for i in (0, 2, 3):
        assert b["stages"][i]["loss"] is None
    raw = _compact(e.document().to_dict())
    assert '"verify":null,"loss":null,"new_findings":[]' in raw
    assert ('"loss":{"basis":"container","probes":[{"probe":"n1-loop","from":"clab-fylgja-n1-loop-a",'
            '"to":"clab-fylgja-n1-loop-b","outcome":"measured","sent":300,"lost":274,"longest_gap_s":54.8}],'
            '"added":[],"dropped":[]}') in raw
    assert r.stage_lines(b) == [
        "stage change-1/seeded: created; settled after 3.2s (2 reads); 16 held, 0 failed, 0 skipped; baseline",
        "stage change-1/third-link: stepped in 64.5s (push n1 2.5s, n3 2.6s); settled after 6.1s (4 reads); "
        "20 held, 0 failed, 0 skipped; loss n1-loop 274/300, gap 54.8s; passed",
        "stage change-1/head: refused (platform.unsupported)",
        "stage change-1/bad-port: not reached",
    ]
    none = passed_run()
    plain = r.stage_lines(none.block())
    for s in none.res.stages[1:]:
        s.loss = loss_of()
    got = r.stage_lines(none.block())
    assert got == plain and "loss" not in "\n".join(got)


# markdown_test.go

CAVEAT = r.CAVEAT


def md_lines(*lines: str) -> str:
    return "\n".join(lines)


TABLE_HEAD = ("| stage | at | snapshot | bundle | step | wait | verify | loss | new verification failures | verdict |\n"
              "|---|---|---|---|---|---|---|---|---|---|")
BP_ROW = "| change-1/branch-point | 2026-10-16T17:20:19.944651+00:00 | — | — | | | | — | | refused (scope.empty) |"
STAGES_HEAD = "**Stages** (Infrahub's view does not show them):"
BP_STAGE = "- `change-1/branch-point` main at 2026-10-16T17:20:19.944651+00:00 (branch point)"
SEEDED_STAGE = '- `change-1/seeded` change-1 at 2026-10-16T17:25:30.118244+00:00 (written) "after the link is cabled"'
THIRD_STAGE = '- `change-1/third-link` change-1 at 2026-10-16T17:30:00.000000+00:00 (given) "third link"'
HEAD_STAGE = "- `change-1/head` change-1 at 2026-10-16T17:30:11.884302+00:00 (head)"
LINK_EDGE = '  s1 -- "+link n1:e1-3 — n3:e1-3; ~n1, ~n3 (bootstrap, mapping); artifacts n1, n3" --> s2'


def test_markdown():
    passed = r.markdown(passed_run().document(), pairs())
    assert passed == md_lines(
        '## Fylgja rehearsed proposed change "third link" on change-1, scope tag:fylgja',
        "",
        "Run `fylgja-rehearse 01a1b2c3-0000-7000-8000-0000000000aa`, stages resolved at 2026-10-17T14:02:11Z. "
        "Status **ok**. 118.4s of the 1980s deadline (ceiling 3600s).",
        "",
        TABLE_HEAD,
        BP_ROW,
        "| change-1/seeded | 2026-10-16T17:25:30.118244+00:00 | a1a1a1a1… | 5c5c5c5c… | created | settled after 3.2s "
        "| 15 held, 0 failed, 0 skipped | — | — | baseline |",
        "| change-1/third-link | 2026-10-16T17:30:00.000000+00:00 | a2a2a2a2… | d0d0d0d0… | stepped 4.5s; push n1, n3 "
        "| settled after 6.1s | 19 held, 0 failed, 0 skipped | — | none | passed |",
        "| change-1/head | 2026-10-16T17:30:11.884302+00:00 | a4a4a4a4… | cccccccc… | unchanged | settled after 1.0s "
        "| 19 held, 0 failed, 0 skipped | — | none | passed |",
        "",
        "```mermaid",
        "flowchart TD",
        '  s0["change-1/branch-point<br/>refused"]',
        '  s1["change-1/seeded<br/>baseline"]',
        '  s2["change-1/third-link<br/>passed"]',
        '  s3["change-1/head<br/>passed"]',
        '  s0 -. "not computed" .-> s1',
        LINK_EDGE,
        '  s2 -- "unchanged" --> s3',
        "```",
        "",
        STAGES_HEAD, "", BP_STAGE, SEEDED_STAGE, THIRD_STAGE, HEAD_STAGE,
        "",
        "**Warnings**: none",
        "",
        "**Baseline findings** (reported, failing nothing): none",
        "",
        CAVEAT,
        "",
    )

    failed = r.markdown(failed_run().document(), pairs())
    assert failed == md_lines(
        '## Fylgja rehearsed proposed change "third link" on change-1, scope tag:fylgja',
        "",
        "Run `fylgja-rehearse 01a1b2c3-0000-7000-8000-0000000000aa`, stages resolved at 2026-10-17T14:02:11Z. "
        "Status **nonconforming**. 301.6s of the 2610s deadline (ceiling 3600s).",
        "",
        TABLE_HEAD,
        BP_ROW,
        "| change-1/seeded | 2026-10-16T17:25:30.118244+00:00 | a1a1a1a1… | 5c5c5c5c… | created | expired after 120.0s "
        "| 14 held, 1 failed, 0 skipped | — | — | baseline |",
        "| change-1/third-link | 2026-10-16T17:30:00.000000+00:00 | a2a2a2a2… | d0d0d0d0… | stepped 4.5s; push n1, n3 "
        "| expired after 120.0s | 18 held, 1 failed, 0 skipped | — | none | passed |",
        "| change-1/bad-port | 2026-10-16T17:30:05.000000+00:00 | a3a3a3a3… | babababa… | diverged at push 29.8s; "
        "restarted n3 61.2s; push n3; not landed n1 (push.refused) | expired after 120.0s | 18 held, 1 failed, 0 "
        "skipped "
        "| — | none | failed |",
        "| change-1/head | 2026-10-16T17:30:11.884302+00:00 | a4a4a4a4… | cccccccc… | | | | — | | not reached |",
        "",
        "```mermaid",
        "flowchart TD",
        '  s0["change-1/branch-point<br/>refused"]',
        '  s1["change-1/seeded<br/>baseline"]',
        '  s2["change-1/third-link<br/>passed"]',
        '  s3["change-1/bad-port<br/>failed"]',
        '  s4["change-1/head<br/>not reached"]',
        '  s0 -. "not computed" .-> s1',
        LINK_EDGE,
        '  s2 -- "~n1 (mapping); artifacts n1" --> s3',
        '  s3 -- "unchanged" --> s4',
        "  classDef failed stroke:#d32f2f,stroke-width:3px",
        "  class s3 failed",
        "```",
        "",
        "**Findings**:",
        "",
        "- `push.refused` n1: n1 refused artifact device-config (checksum 9a0177b2e8c1d4f5a6b7c8d9e0f1a2b3) at line "
        "12: "
        "invalid port ethernet-1/99",
        "- `rehearsal.stage.failed` change-1/bad-port: diverged at phase push: landed n3; not landed n1 (push.refused)",
        "- `scope.empty` tag:fylgja: scope tag:fylgja selects no device on branch main",
        "",
        STAGES_HEAD, "", BP_STAGE, SEEDED_STAGE, THIRD_STAGE,
        '- `change-1/bad-port` change-1 at 2026-10-16T17:30:05.000000+00:00 (given) '
        '"a port \\<disabled\\> \\\\"by mistake\\\\" \\| n1\\\\nsecond line"',
        HEAD_STAGE,
        "",
        "**Warnings**: none",
        "",
        "**Baseline findings** (reported, failing nothing):",
        "",
        "- `verify.neighbor` n1:ethernet-1/2: node n1 (172.20.20.2): port ethernet-1/2 sees no neighbour at "
        "/interface\\[name=ethernet-1/2\\]; link l1 names n2 ethernet-1/2 at its far end",
        "",
        "**Reproduce by hand**:",
        "",
        "```",
        "fylgja-cli twin create --stage change-1/seeded --scope tag:fylgja",
        "fylgja-cli twin step --stage change-1/third-link --allow-restart",
        "fylgja-cli twin step --stage change-1/bad-port --allow-restart",
        "fylgja-cli twin verify",
        "fylgja-cli twin destroy",
        "```",
        "",
        CAVEAT,
        "",
    )

    # The caveat is last on every run, the reproduce block on a failure alone, and no line of
    # any artifact's content, not even a checksum, anywhere.
    for e in examples():
        md = r.markdown(e.document(), pairs())
        assert md.endswith("\n\n" + CAVEAT + "\n"), e.name
        assert ("**Reproduce by hand**" in md) == bool(e.block()["reproduce"]), e.name
        carries_no_content(e.name + "'s markdown", md)


def _within_comment(md: str) -> None:
    assert len(md.encode()) <= r.COMMENT_MAX, f"{len(md.encode())} bytes, over {r.COMMENT_MAX}"


def test_markdown_of_a_baseline_not_verified():
    md = r.markdown(unverified_run().document(), pairs())
    for want in [
        "| change-1/seeded | 2026-10-16T17:25:30.118244+00:00 | a1a1a1a1… | 5c5c5c5c… | created | incomplete after "
        "0.0s "
        "| | — | — | error |",
        "**Findings**:\n\n- `rehearsal.stage.error` change-1/seeded: its wait ended incomplete after 0.0s\n"
        "- `scope.empty` tag:fylgja: scope tag:fylgja selects no device on branch main\n\n",
        "**Warnings**:\n\n- `operation.failed` change-1/seeded: " + REHEARSE_RUN + ": activity verify\\_twin failed: "
        "the workflow service did not answer (stage seeded)\n\n",
        "**Baseline findings** (reported, failing nothing): none\n\n",
    ]:
        assert want in md
    _within_comment(md)


def test_markdown_of_a_stage_not_compared():
    e = passed_run()
    e.status = "error"
    e.res.outcome = r.OUTCOME_STAGE_ERROR
    e.res.stages = e.res.stages[:2]
    third = e.res.stages[1]
    third.verdict, third.counts = r.VERDICT_ERROR, counts(8, 1)
    third.wait = {"outcome": "incomplete", "budget_s": 120, "reads": 3, "after_s": 9.4, "from": RESOLVED_AT,
                  "failing": [ADDED]}
    b = e.block()
    for brief in (False, True):
        row = [line for line in r._table(b, False, brief).split("\n") if line.startswith("| change-1/third-link |")][0]
        assert row.endswith("| incomplete after 9.4s | 18 held, 1 failed, 0 skipped | — | not compared | error |")
    md = r.markdown(e.document(), pairs())
    assert "| none | error |" not in md
    _within_comment(md)


@pytest.mark.parametrize("e,want", [
    (restarted_run(), "| change-1/third-link | 2026-10-16T17:30:00.000000+00:00 | a2a2a2a2… | d0d0d0d0… | stepped "
                      "95.3s; "
                      "restarted n3 61.2s; recreated n1 70.4s; push n1, n3 | settled after 6.1s |"),
    (cut_before_readiness_run(), "| change-1/bad-port | 2026-10-16T17:30:05.000000+00:00 | a3a3a3a3… | babababa… | "
                                 "cancelled at readiness; restarted n3 | | | — | | error |"),
    (cut_at_push_run(), "| change-1/bad-port | 2026-10-16T17:30:05.000000+00:00 | a3a3a3a3… | babababa… | cancelled at "
                        "push; restarted n3 61.2s; push n3; not landed n1 | | | — | | error |"),
], ids=lambda x: x.name if hasattr(x, "name") else "")
def test_markdown_names_the_restarts_time(e, want):
    md = r.markdown(e.document(), pairs())
    assert want in md
    _within_comment(md)


def test_markdown_names_each_warnings_stages():
    unrepresented = "artifact device-config names interface ethernet-1/99 at line 17, which the twin does not represent"
    moved = "main has moved since change-1's branch point"
    e = failed_run()
    e.inp.stages[0].findings.append(F(WARNING, "resolve", "stage.main.moved", CHANGE, moved))
    for i in (3, 4):
        e.inp.stages[i].findings.append(F(WARNING, "read", "artifact.interface.unrepresented", "n1:ethernet-1/99",
                                          unrepresented))
        e.inp.stages[i].findings.append(F(WARNING, "compile", "artifact.interface.unrepresented", "n1:ethernet-1/99",
                                          unrepresented))
    e.inp.stages[4].findings.append(F(WARNING, "compile", "artifact.interface.unrepresented", "n2:ethernet-1/98",
                                      "artifact device-config names interface ethernet-1/98"))
    doc = e.document()
    doc.findings.append(F(WARNING, "resolve", "rehearsal.stage.moved", CHANGE + "/head", "stage change-1/head moved"))
    md = r.markdown(doc, pairs())
    assert md_lines(
        "**Warnings**:",
        "",
        "- `artifact.interface.unrepresented` n1:ethernet-1/99: " + unrepresented + " (stages bad-port, head)",
        "- `artifact.interface.unrepresented` n2:ethernet-1/98: artifact device-config names interface ethernet-1/98 "
        "(stage head)",
        "- `rehearsal.stage.moved` change-1/head: stage change-1/head moved",
        "- `stage.main.moved` change-1: " + moved,
        "",
    ) in md
    _within_comment(md)

    # Brief, each is named by identifier and object, its stages kept.
    brief = r._join(r._parts(doc, pairs(), True))
    assert ("- `artifact.interface.unrepresented` n1:ethernet-1/99 (stages bad-port, head)\n"
            "- `artifact.interface.unrepresented` n2:ethernet-1/98 (stage head)\n"
            "- `rehearsal.stage.moved` change-1/head\n- `stage.main.moved` change-1\n") in brief

    # A label is the operator's, escaped where it lands.
    e.inp.stages[4].label = "he*ad"
    assert "(stages bad-port, he\\*ad)" in r.markdown(e.document(), pairs())


def want_stages_in_the_table(label: str, md: str, b: dict, unread: bool) -> None:
    """Fails unless the markdown's table has a row for each of the block's stages that begins
    with its reference and ends with its verdict."""
    for s in b["stages"]:
        begins, ends = "\n| " + r._cell(s["ref"]) + " |", r._cell(r._verdict_cell(s, unread)) + " |\n"
        assert any(("\n" + line).startswith(begins) and line.endswith(" | " + ends)
                   for line in md.splitlines(True)), f"{label}: no row begins {begins[1:]!r} and ends {ends!r}"


def test_markdown_fits_a_comment():
    unrepresented = ("artifact device-config names interface ethernet-1/99 at line 17, which the twin does not "
                     "represent: omitted (omit.interface.unmappable: rule ethernet matched, but {port} is 99, outside "
                     "its range 1..58; no such port on the node)")
    refusal = ("node n1 refused artifact device-config (checksum 592e1578066373b636e0676ce1667e26): "
               + "the node's message, cut " * 40)
    e = failed_run()
    for i in (3, 4):
        e.inp.stages[i].findings.append(F(WARNING, "read", "artifact.interface.unrepresented", "n1:ethernet-1/99",
                                          unrepresented))
        e.inp.stages[i].findings.append(F(WARNING, "compile", "artifact.interface.unrepresented", "n1:ethernet-1/99",
                                          unrepresented))
    doc = e.document()
    doc.findings.append(F(REJECTION, "push", "push.refused", "n1", refusal))
    doc.findings.append(F(REJECTION, "push", "step.diverged", STEP_RUN + "2",
                          "step run " + STEP_RUN + "2 towards stage change-1/bad-port stopped at phase push: "
                          "landed n3; "
                          "not landed n1 (push.refused)"))
    assert len(r._join(r._parts(doc, pairs(), False)).encode()) > r.COMMENT_MAX
    md = r.markdown(doc, pairs())
    _within_comment(md)
    for want in [
        "| change-1/bad-port | 2026-10-16T17:30:05.000000+00:00 | a3a3a3a3… | babababa… | diverged at push | expired "
        "after "
        "120.0s | 18 held, 1 failed, 0 skipped | — | none | failed |",
        '  s3["change-1/bad-port<br/>failed"]',
        "**Findings**:\n\n- `push.refused` n1 (×2)\n- `rehearsal.stage.failed` change-1/bad-port\n- `scope.empty` "
        "tag:fylgja\n- `step.diverged` " + STEP_RUN + "2\n\n",
        STAGES_HEAD,
        "**Warnings**:\n\n- `artifact.interface.unrepresented` n1:ethernet-1/99 (stages bad-port, head)\n\n",
        "**Baseline findings** (reported, failing nothing):\n\n- `verify.neighbor` n1:ethernet-1/2\n\n",
        "**Reproduce by hand**:\n\n```\nfylgja-cli twin create --stage change-1/seeded --scope tag:fylgja\n",
        "\n\n" + r.fit_note([]) + "\n\n" + CAVEAT + "\n",
    ]:
        assert want in md
    for message in (unrepresented, "the node's message", "invalid port ethernet-1/99", "sees no neighbour"):
        assert message not in md


@pytest.mark.parametrize("marks,table,left,row", [
    (14, "and the table each step by its outcome and its new verification failures by the first few",
     "the drawing and the stages are left out",
     "| change-1/mark-13 | 2026-10-16T17:30:11.884302+00:00 | a4a4a4a4… | cccccccc… | unchanged | settled after 1.0s "
     "| 19 held, 0 failed, 0 skipped | — | none | passed |"),
    (60, "; the table gives each stage's reference and verdict alone", "the drawing and the stages are left out",
     "| change-1/mark-59 | passed |"),
])
def test_markdown_fits_a_comment_with_many_stages(marks, table, left, row):
    # Fourteen more stages keep the brief table and leave the drawing and the stages out;
    # sixty keep each stage's reference and verdict in the table, and still fit (T083).
    e = passed_run()
    for i in range(marks):
        s = head(ROLE_REHEARSED)
        s.ref = f"{CHANGE}/mark-{i:02d}"
        e.inp.stages.append(s)
        e.res.stages.append(r.StageResult(s.ref, r.VERDICT_PASSED, step=step_to(s.ref, 3, "unchanged", 0.9),
                                          wait=wait("settled", 1.0, 1), counts=counts(8, 0), took_s=1.9))
    md = r.markdown(e.document(), pairs())
    _within_comment(md)
    for want in ['## Fylgja rehearsed proposed change "third link" on change-1, scope tag:fylgja\n\nRun '
                 '`fylgja-rehearse ' + REHEARSE_RUN + "`",
                 "\n" + row + "\n", table,
                 "; " + left + "; fylgja-twin's message is the whole report as text.*\n\n" + CAVEAT + "\n"]:
        assert want in md
    want_stages_in_the_table(f"{marks} more stages", md, e.block(), False)
    assert "```" not in md and "**Stages**" not in md


def test_markdown_with_no_block_fits_a_comment():
    message = "the deploy could not run: " + "the workflow service's message, cut " * 14

    def doc(n: int, pad: int) -> Document:
        found = Findings()
        for i in range(n):
            obj = f"lab fylgja node n{i:03d}" + ("x" * pad if i == n - 1 else "")
            found.add_step(REJECTION, "deploy", "operation.failed", obj, message)
        d = new_document("twin.rehearse", {"branch": "change-9"}, found)
        d.status = "error"
        return d

    n = 40
    while "**Findings**:" in r.markdown(doc(n, 0)):
        n += 1
    kept = kept_near = left_out = 0
    for count in (n - 1, n):
        for pad in range(45):
            d = doc(count, pad)
            assert len(r._join(r._parts(d, [], False)).encode()) > r.COMMENT_MAX
            md = r.markdown(d)
            _within_comment(md)
            assert "table" not in md
            assert md.startswith("## Fylgja did not rehearse branch change-9\n\nStatus **error**.\n\n")
            assert md.endswith("; fylgja-twin's message is the whole report as text.*\n\n" + CAVEAT + "\n")
            if "**Findings**:" in md:
                kept += 1
                if len(md.encode()) > r.COMMENT_MAX - 20:
                    kept_near += 1
            elif "the findings is left out" in md:
                left_out += 1
    assert kept and kept_near and left_out
    assert r.fit_note([], none=True) == ("*To fit what Infrahub keeps of a comment (4092 bytes), each finding is named "
                                         "by its identifier and object alone; fylgja-twin's message is the whole "
                                         "report as text.*")


def test_markdown_fits_what_the_ceiling_does_not_bound():
    # One stage's new findings.
    e = new_finding_run()
    many = [{"rule": "verify.neighbor", "object": f"n1:ethernet-1/{i + 1}",
             "message": "node n1 (172.20.20.2): port sees no neighbour"} for i in range(200)]
    e.res.stages[1].new_findings, e.res.stages[1].wait = many, wait("expired", 120, 61, *many)
    md = r.markdown(e.document(), pairs())
    _within_comment(md)
    assert "| verify.neighbor n1:ethernet-1/1, verify.neighbor n1:ethernet-1/10 and 198 more | failed |" in md
    want_stages_in_the_table("many new findings", md, e.block(), False)

    # A refusal with many marks.
    for marks, all_fit in ((80, True), (300, False)):
        e = refused_run()
        for i in range(marks):
            s = head(ROLE_REHEARSED)
            s.ref = f"{CHANGE}/mark-{i:03d}"
            e.inp.stages.append(s)
        md = r.markdown(e.document(), pairs())
        _within_comment(md)
        b = e.block()
        if all_fit:
            want_stages_in_the_table(f"a refusal with {marks} marks", md, b, False)
            continue
        rows = md.count(" | not reached |\n")
        left = len(b["stages"]) - rows
        assert rows > 0 and left > 0
        assert f"\n| … and {left} more | |\n" in md
        assert f"the table gives each stage's reference and verdict alone, and the last {left} are left out of it" in md
        assert f"| change-1/mark-{rows - len(e.inp.stages) + marks - 1:03d} | not reached |\n" in md

    # A name longer than a comment.
    e = failed_run()
    e.inp.proposed_change["name"] = "a long name " * 500
    md = r.markdown(e.document(), pairs())
    heading = md.split("\n", 1)[0]
    _within_comment(md)
    assert len(heading.encode()) <= 200
    assert heading.startswith('## Fylgja rehearsed proposed change "a long name a long')
    assert '…" on change-1, scope tag:fylgja' in heading
    want_stages_in_the_table("a long name", md, e.block(), False)

    # A scope longer than a comment: cut with an ellipsis as a name is, and never left out.
    e = failed_run()
    doc = e.document()
    doc.subject["scope"] = "tag:" + "a-long-tag-" * 500
    full = r._join(r._parts(doc, pairs(), False))
    assert full.split("\n", 1)[0].endswith(" on change-1, scope tag:a-long-tag-a-long-tag-" + "a-long-tag-" * 498)
    md = r.markdown(doc, pairs())
    heading = md.split("\n", 1)[0]
    _within_comment(md)
    assert len(heading.encode()) <= 200
    assert heading.startswith('## Fylgja rehearsed proposed change "third link" on change-1, scope tag:a-long-tag-')
    assert heading.endswith("…")
    want_stages_in_the_table("a long scope", md, e.block(), False)
    assert r.clip("ab€cd", 6) == "ab…"


def test_markdown_escapes():
    odd = bad_port(ROLE_REHEARSED)
    odd.ref, odd.label = CHANGE + '/a"<b>#c|d', 'a"<b>#c|d'
    e = passed_run()
    e.inp.stages[3] = odd
    e.res.stages[2].ref = odd.ref
    md = r.markdown(e.document())
    for want in [
        '  s3["change-1/a#quot;#lt;b#gt;#35;c|d<br/>passed"]',
        '  s2 -. "not computed" .-> s3',
        '| change-1/a"\\<b\\>\\#c\\|d | 2026-10-16T17:30:05.000000+00:00 | a3a3a3a3… | babababa… | unchanged |',
        '- `change-1/a"<b>#c|d` change-1 at 2026-10-16T17:30:05.000000+00:00 (given) '
        '"a port \\<disabled\\> \\\\"by mistake\\\\" \\| n1\\\\nsecond line"',
    ]:
        assert want in md
    assert not any(line.startswith("second line") for line in md.split("\n"))
    assert r._mermaid('a "b" <c> #d\ne') == "a #quot;b#quot; #lt;c#gt; #35;d e"

    # A backtick is written as its entity, in a node's label and in an edge's (T109).
    ticked = passed_run()
    ticked.inp.stages[3].ref = "`odd/head"
    ticked.res.stages[2].ref = "`odd/head"
    ps = pairs() + [Pair.between(CHANGE + "/third-link", "`odd/head", THIRD_ID, HEAD_ID,
                                 StepDiff(nodes_added=["n`4"]))]
    drawn = r._drawing(ticked.block(), ps, False)
    for want in ('  s3["#96;odd/head<br/>passed"]', '  s2 -- "+n#96;4" --> s3'):
        assert want in drawn
    inner = drawn.removeprefix("```mermaid").removesuffix("```")
    assert "`" not in inner
    assert r._mermaid("`a`") == "#96;a#96;"
    assert r._code("a`b``c") == "```a`b``c```"
    assert r._code("`x") == "`` `x ``"
    assert r._fenced("", "a\n```\nb") == "````\na\n```\nb\n````"

    # The proposed change's name is the operator's too.
    e = passed_run()
    e.inp.proposed_change["name"] = "a *bold* [link](x) <b>"
    assert r.markdown(e.document()).startswith(
        '## Fylgja rehearsed proposed change "a \\*bold\\* \\[link\\](x) \\<b\\>" on change-1, scope tag:fylgja')


def test_markdown_of_a_refusal():
    md = r.markdown(refused_run().document(), pairs())
    for want in [
        '## Fylgja did not rehearse proposed change "third link" on change-1, scope tag:fylgja',
        "No run was started; stages resolved at 2026-10-17T14:02:11Z. Status **rejected**. Deadline 3840s "
        "(ceiling 3600s).",
        '  s0["change-1/seeded<br/>not reached"]',
        "**Findings**:\n\n- `rehearsal.deadline.unfit` change-1: the stages need 3840s, over the ceiling of 3600s",
    ]:
        assert want in md

    md = r.markdown(held_run().document(), pairs())
    for want in [
        '## Fylgja did not rehearse proposed change "third link" on change-1, scope tag:fylgja',
        "Run `fylgja-rehearse " + REHEARSE_RUN + "` touched nothing, since a run already holds the id of its "
        "baseline's "
        "provision, and no destroy was needed; stages resolved at 2026-10-17T14:02:11Z. Status **rejected**. "
        "Deadline 1980s (ceiling 3600s).",
        '  s1["change-1/seeded<br/>not reached"]',
        "**Findings**:\n\n- `run.in_flight` fylgja-provision: the rehearsal's fylgja-provision could not start: a run "
        "is already in flight under its id\n- `scope.empty` tag:fylgja: scope tag:fylgja selects no device on branch "
        "main",
    ]:
        assert want in md

    assert r.markdown(lost_run().document(), pairs()) == md_lines(
        '## Fylgja started rehearsing proposed change "third link" on change-1, scope tag:fylgja',
        "",
        "Run `fylgja-rehearse " + REHEARSE_RUN + "` was started, and its end was not read: " + LOST_WHY
        + ". It goes on "
        "to its destroy, and `fylgja twin show` says where it is. Stages resolved at 2026-10-17T14:02:11Z. Status "
        "**error**. Deadline 1980s (ceiling 3600s).",
        "",
        TABLE_HEAD,
        BP_ROW,
        "| change-1/seeded | 2026-10-16T17:25:30.118244+00:00 | a1a1a1a1… | 5c5c5c5c… | | | | — | | not read |",
        "| change-1/third-link | 2026-10-16T17:30:00.000000+00:00 | a2a2a2a2… | d0d0d0d0… | | | | — | | not read |",
        "| change-1/head | 2026-10-16T17:30:11.884302+00:00 | a4a4a4a4… | cccccccc… | | | | — | | not read |",
        "",
        "```mermaid",
        "flowchart TD",
        '  s0["change-1/branch-point<br/>refused"]',
        '  s1["change-1/seeded<br/>not read"]',
        '  s2["change-1/third-link<br/>not read"]',
        '  s3["change-1/head<br/>not read"]',
        '  s0 -. "not computed" .-> s1',
        LINK_EDGE,
        '  s2 -- "unchanged" --> s3',
        "```",
        "",
        "**Findings**:",
        "",
        "- `operation.failed` provision: " + LOST_WHY,
        "- `scope.empty` tag:fylgja: scope tag:fylgja selects no device on branch main",
        "",
        STAGES_HEAD, "", BP_STAGE, SEEDED_STAGE, THIRD_STAGE, HEAD_STAGE,
        "",
        "**Warnings**: none",
        "",
        "**Baseline findings** (reported, failing nothing): none",
        "",
        CAVEAT,
        "",
    )

    unknown = Findings([F(REJECTION, "resolve", "stage.unknown", "change-9",
                          "branch change-9 has no open proposed change")])
    doc = new_document("twin.rehearse", {"branch": "change-9"}, unknown)
    assert r.markdown(doc) == md_lines(
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
        CAVEAT,
        "",
    )
    # Refused once the scope was resolved, the heading names it after the branch.
    doc.subject["scope"] = SCOPE
    assert r.markdown(doc).split("\n", 1)[0] == "## Fylgja did not rehearse branch change-9, scope tag:fylgja"


def test_markdown_draws_every_change():
    cabled = {"id": "l3", "a": {"node": "n1", "port": "e1-3"}, "b": {"node": "n3", "port": "e1-3"}}
    gone = StepDiff(links_removed=[cabled],
                    nodes_added=["n4"], nodes_removed=["n2"],
                    artifacts_added=[{"node": "n4", "name": "device-config"}],
                    artifacts_removed=[{"node": "n2", "name": "device-config"}])
    assert r.changed(gone) == "-link n1:e1-3 — n3:e1-3; +n4; -n2; artifacts n2, n4"
    assert r.changed(StepDiff()) == "unchanged"
    md = r.markdown(passed_run().document(), [Pair.between(CHANGE + "/seeded", CHANGE + "/third-link", "", "", gone)])
    assert '  s1 -- "-link n1:e1-3 — n3:e1-3; +n4; -n2; artifacts n2, n4" --> s2' in md
    carries_no_content("the drawing of every change", md)


def test_step_cell_of_every_outcome():
    def cell(outcome: str, phase: str = "", *pushed: dict) -> str:
        step = {"outcome": outcome, "phase": phase, "restarted": [], "recreated": [], "created": [],
                "pushed": list(pushed), "timings": {"whole_s": 7.5}}
        return r._step_cell({"step": step})

    assert cell("cancelled") == "cancelled before its stage"
    assert cell("cancelled", "readiness") == "cancelled at readiness"
    assert cell("rejected") == "rejected"
    assert cell("error") == "could not run"
    assert r._step_cell({}) == ""
    assert cell("diverged", "push", {"node": "n1", "outcome": "landed"}, {"node": "n3", "outcome": "failed"}) == (
        "diverged at push 7.5s; push n1; not landed n3")


def _failed_class(nodes: str) -> str:
    return "  classDef failed stroke:#d32f2f,stroke-width:3px\n  class " + nodes + " failed\n"


def test_markdown_of_a_cut_a_failed_baseline_and_an_unclean_destroy():
    def heads(status: str, used: str) -> str:
        return ('## Fylgja rehearsed proposed change "third link" on change-1, scope tag:fylgja\n\n'
                'Run `fylgja-rehearse '
                + REHEARSE_RUN + "`, stages resolved at 2026-10-17T14:02:11Z. Status **" + status + "**. " + used
                + " of the 1980s deadline (ceiling 3600s).\n\n" + TABLE_HEAD + "\n")

    bp = BP_ROW + "\n"
    base = ("| change-1/seeded | 2026-10-16T17:25:30.118244+00:00 | a1a1a1a1… | 5c5c5c5c… | created | settled after "
    "3.2s "
            "| 15 held, 0 failed, 0 skipped | — | — | baseline |\n")
    link = LINK_EDGE + "\n"
    missed = "- `scope.empty` tag:fylgja: scope tag:fylgja selects no device on branch main\n"
    tail = "**Warnings**: none\n\n**Baseline findings** (reported, failing nothing): none\n\n" + CAVEAT + "\n"
    unclean = unclean_run().document()
    unclean.findings.append(F(REJECTION, "teardown", "cleanup.incomplete", "lab fylgja",
                              "clab destroy exited 1; fylgja twin destroy clears it"))
    for name, doc, want in [
        ("cut", cut_run().document(), heads("error", "2001.2s") + base
         + "| change-1/third-link | 2026-10-16T17:30:00.000000+00:00 | a2a2a2a2… | d0d0d0d0… | cancelled at readiness "
           "| | "
           "| — | | error |\n"
         + "| change-1/head | 2026-10-16T17:30:11.884302+00:00 | a4a4a4a4… | cccccccc… | | | | — | | not reached |\n\n"
         + "```mermaid\nflowchart TD\n" + '  s0["change-1/seeded<br/>baseline"]\n'
         + '  s1["change-1/third-link<br/>error"]\n'
         + '  s2["change-1/head<br/>not reached"]\n'
         + '  s0 -- "+link n1:e1-3 — n3:e1-3; ~n1, ~n3 (bootstrap, mapping); artifacts n1, n3" --> s1\n'
         + '  s1 -- "unchanged" --> s2\n' + _failed_class("s1") + "```\n\n**Findings**:\n\n"
         + "- `rehearsal.deadline.cut` change-1/third-link: the deadline of 1980s passed at stage change-1/third-link: "
           "change-1/seeded took 88.1s\n\n"),
        ("not built", not_built_run().document(), heads("failed", "243.0s") + bp
         + "| change-1/seeded | 2026-10-16T17:25:30.118244+00:00 | a1a1a1a1… | 5c5c5c5c… | not built (failed at "
           "readiness) "
           "| | | — | — | error |\n"
         + "| change-1/third-link | 2026-10-16T17:30:00.000000+00:00 | a2a2a2a2… | d0d0d0d0… | | | | — | | not reached "
           "|\n\n"
         + "```mermaid\nflowchart TD\n" + '  s0["change-1/branch-point<br/>refused"]\n'
         + '  s1["change-1/seeded<br/>error"]\n'
         + '  s2["change-1/third-link<br/>not reached"]\n' + '  s0 -. "not computed" .-> s1\n' + link
         + _failed_class("s1") + "```\n\n**Findings**:\n\n"
         + "- `readiness.timeout` n2: n2 did not answer its probe within 60s\n"
         + "- `rehearsal.baseline.failed` change-1/seeded: the baseline change-1/seeded could not be built: its "
           "provision ended failed at readiness\n"
         + missed + "\n"),
        ("unclean", unclean, heads("unclean", "118.4s") + bp + base
         + "| change-1/third-link | 2026-10-16T17:30:00.000000+00:00 | a2a2a2a2… | d0d0d0d0… | stepped 4.5s; push n1, "
           "n3 "
           "| settled after 6.1s | 19 held, 0 failed, 0 skipped | — | none | passed |\n"
         + "| change-1/head | 2026-10-16T17:30:11.884302+00:00 | a4a4a4a4… | cccccccc… | unchanged | settled after "
           "1.0s "
           "| 19 held, 0 failed, 0 skipped | — | none | passed |\n\n"
         + "```mermaid\nflowchart TD\n" + '  s0["change-1/branch-point<br/>refused"]\n'
         + '  s1["change-1/seeded<br/>baseline"]\n' + '  s2["change-1/third-link<br/>passed"]\n'
         + '  s3["change-1/head<br/>passed"]\n' + '  s0 -. "not computed" .-> s1\n' + link
         + '  s2 -- "unchanged" --> s3\n```\n\n**Findings**:\n\n'
         + "- `cleanup.incomplete` lab fylgja: clab destroy exited 1; fylgja twin destroy clears it\n" + missed + "\n"),
    ]:
        md = r.markdown(doc, pairs())
        assert md.startswith(want + STAGES_HEAD + "\n"), name
        assert md.endswith(tail), name
        _within_comment(md)
        carries_no_content(name + "'s markdown", md)


def test_snapshot_column_before_bundle():
    e = passed_run()
    e.inp.stages[3].bundle_id = THIRD_ID  # the head: third-link's bundle, its own snapshot
    doc = e.document()
    md = r.markdown(doc, pairs())
    for want in [
        "\n" + TABLE_HEAD + "\n",
        "\n" + BP_ROW + "\n",
        "\n| change-1/seeded | 2026-10-16T17:25:30.118244+00:00 | a1a1a1a1… | 5c5c5c5c… | created |",
        "\n| change-1/third-link | 2026-10-16T17:30:00.000000+00:00 | a2a2a2a2… | d0d0d0d0… | stepped 4.5s;",
        "\n| change-1/head | 2026-10-16T17:30:11.884302+00:00 | a4a4a4a4… | d0d0d0d0… | unchanged |",
    ]:
        assert want in md
    _within_comment(md)
    stages = doc.blocks["rehearsal"]["stages"]
    assert stages[0]["snapshot_id"] is None and stages[0]["bundle_id"] is None
    assert [s["snapshot_id"] for s in stages[1:]] == [SEEDED_SNAPSHOT, THIRD_SNAPSHOT, HEAD_SNAPSHOT]
    assert stages[2]["bundle_id"] == stages[3]["bundle_id"] and stages[2]["snapshot_id"] != stages[3]["snapshot_id"]
    assert [stages[2]["role"], stages[3]["role"]] == [ROLE_REHEARSED, ROLE_REHEARSED]
    assert not doc.findings.carries("rehearsal.steps.none")


def test_the_loss_column():
    md = r.markdown(probed_run().document(), pairs())
    for want in [
        "\n\n" + TABLE_HEAD + "\n",
        "\n| change-1/seeded | 2026-10-16T17:25:30.118244+00:00 | a1a1a1a1… | 5c5c5c5c… | created | settled after 3.2s "
        "| 16 held, 0 failed, 0 skipped | — | — | baseline |\n",
        "\n| change-1/third-link | 2026-10-16T17:30:00.000000+00:00 | a2a2a2a2… | d0d0d0d0… | stepped 64.5s; push n1, "
        "n3 "
        "| settled after 6.1s | 20 held, 0 failed, 0 skipped | n1-loop 274/300, gap 54.8s | none | passed |\n",
        "\n| change-1/head | 2026-10-16T17:30:11.884302+00:00 | a4a4a4a4… | — | | | | — | | refused "
        "(platform.unsupported) |\n\n",
    ]:
        assert want in md
    caveat = ("*Fidelity is asserted, not measured: the twin's containers forward in software and keep their own "
              "timing; a loss figure is the container's, never a hardware forwarder's.*")
    assert caveat == CAVEAT and md.endswith("\n\n" + caveat + "\n")


def test_the_loss_column_of_a_rehearsal_with_no_probe():
    none = passed_run()
    none.name = "ok, every step's loss naming no probe"
    for s in none.res.stages[1:]:
        s.loss = loss_of()
    for e in (passed_run(), none, failed_run(), cut_run(), not_built_run(), refused_run(), lost_run()):
        md = r.markdown(e.document(), pairs())
        rows = 0
        for line in md.split("\n"):
            if not line.startswith("| " + CHANGE + "/"):
                continue
            rows += 1
            cells = line.split("|")
            assert len(cells) == 12 and cells[8].strip() == "—", f"{e.name}: {line}"
        assert rows == len(e.inp.stages), e.name
        assert "loss without" not in md, e.name


def test_loss_cell_of_every_outcome():
    loss = loss_of(flow_of("a-loop", "measured", 312, 0, 0), flow_of("b-loop", "interrupted", 40, 12, 3),
                   flow_of("c-loop", "not_started", 0, 0, 0), flow_of("d-loop", "not_read", 0, 0, 0))
    loss["added"], loss["dropped"] = ["e-loop"], ["f-loop"]
    s = {"loss": loss}
    assert r._loss_cell(s, False) == ("a-loop 0/312, gap 0.0s; b-loop 12/40 interrupted, gap 3.0s; c-loop not started; "
                                      "d-loop not read; e-loop added, not measured; f-loop dropped, not measured")
    assert r._loss_cell(s, True) == ("a-loop 0/312; b-loop 12/40 interrupted; c-loop not started; d-loop not read; "
                                     "e-loop added, not measured; f-loop dropped, not measured")
    assert r._loss_cell({}, False) == "—"


def _probed(marks: int, pad: int):
    e = probed_run()
    for i in range(marks):
        s = head(ROLE_REHEARSED)
        s.ref = f"{CHANGE}/mark-{i:02d}"
        e.inp.stages.append(s)
        e.res.stages.append(r.StageResult(s.ref, r.VERDICT_PASSED, step=step_to(s.ref, 3, "unchanged", 0.9),
                                          wait=wait("settled", 1.0, 1), counts=probed_counts(8, 0, False),
                                          loss=loss_of(flow_of("n1-loop" + "x" * pad, "measured", 300, 0, 0.2)),
                                          took_s=1.9))
    return e


def test_the_loss_column_shortened():
    md = r.markdown(_probed(14, 0).document(), pairs())
    for want in [
        "\n| change-1/third-link | 2026-10-16T17:30:00.000000+00:00 | a2a2a2a2… | d0d0d0d0… | stepped | settled after "
        "6.1s "
        "| 20 held, 0 failed, 0 skipped | n1-loop 274/300 | none | passed |\n",
        "\n| change-1/mark-13 | 2026-10-16T17:30:11.884302+00:00 | a4a4a4a4… | cccccccc… | unchanged | settled after "
        "1.0s | 20 held, 0 failed, 0 skipped | n1-loop 0/300 | none | passed |\n",
        ", and the table each step by its outcome, its loss without its gaps and its new verification failures by the "
        "first few;",
    ]:
        assert want in md
    _within_comment(md)
    assert "gap " not in md
    md = r.markdown(_probed(60, 0).document(), pairs())
    _within_comment(md)
    assert "; the table gives each stage's reference and verdict alone" in md
    assert "its loss without" not in md and "\n| change-1/mark-59 | passed |\n" in md

    brief = verdicts = 0
    for marks in range(8, 41):
        for pad in range(0, 13, 3):
            d = _probed(marks, pad).document()
            if len(r._join(r._parts(d, pairs(), False)).encode()) <= r.COMMENT_MAX:
                continue
            md = r.markdown(d, pairs())
            _within_comment(md)
            want_stages_in_the_table(f"{marks} more stages padded by {pad}", md, d.blocks["rehearsal"], False)
            if "its loss without its gaps" in md:
                brief += 1
            elif "reference and verdict alone" in md:
                verdicts += 1
    assert brief and verdicts


# The renderers carry over nothing the core owns.


def test_the_documents_import_nothing_of_the_adapter():
    for name in ("rehearsal", "plan", "deadline"):
        source = (Path(r.__file__).parent / f"{name}.py").read_text()
        assert not re.search(r"^\s*(from|import)\s+[\w.]*adapters", source, re.M), name
