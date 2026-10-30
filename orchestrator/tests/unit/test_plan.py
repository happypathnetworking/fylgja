"""The plan block and its text held to the goldens captured from `fylgja stage plan`
(`tests/golden/plan.json`, `plan.txt`, `plan.stderr.txt`) byte for byte, and to the Go tests
of what renders them: `internal/step`'s `TestDiffNodeAdded`, `TestPairTextOrder`,
`TestPairTextOneLine` and `TestPairJSONSatisfiesTheContract` (the pair's text and JSON), and
`internal/stages`' `pairOf` and `build`'s refusal (the step not computed, the stage's status
and rule). The plan's orchestration over the adapter and the core is the stage-plan
flow's."""

import json
from pathlib import Path

import pytest

from fylgja_orchestrator.documents import findings
from fylgja_orchestrator.documents.findings import REJECTION, WARNING, Findings
from fylgja_orchestrator.documents.plan import (
    PLAN_COMPILED,
    PLAN_FAILED,
    PLAN_REFUSED,
    Pair,
    PlanResult,
    PlanStage,
    StepDiff,
    artifacts_moved,
    pair_of,
    read_counts,
    step_of_diff,
)

GOLDEN = Path(__file__).resolve().parents[1] / "golden"
REPOSITORY = Path(__file__).resolve().parents[3]
SCOPE = "tag:fylgja"

ID_A = "35aea06f" * 8
ID_B = "9c2d01e7" * 8


def golden_plan() -> tuple[dict, PlanResult]:
    """The golden document, and the plan rebuilt from its block as the flow fills it: each
    stage with its packages (the three SR Linux devices), each step from the core's answer."""
    doc = json.loads((GOLDEN / "plan.json").read_text())
    block = doc["plan"]
    res = PlanResult(branch=block["branch"], proposed_change=block["proposed_change"], destination="main")
    for i, sb in enumerate(block["stages"]):
        stage = PlanStage.from_block(sb, [("nokia_srlinux", 3)] if sb.get("read") else [])
        step = StepDiff.from_dict(block["steps"][i - 1]) if i and block["steps"][i - 1]["computed"] else None
        res.add(stage, step)
    return doc, res


def test_the_golden_plan():
    doc, res = golden_plan()
    out = res.document(SCOPE)
    assert out.json() == (GOLDEN / "plan.json").read_text()
    assert out.exit_code == 1
    assert res.text(SCOPE) == (GOLDEN / "plan.txt").read_text()
    assert out.text() == (GOLDEN / "plan.stderr.txt").read_text()
    findings.validate(out.to_dict())


def test_the_golden_plans_stages():
    _, res = golden_plan()
    assert [(s.status, s.rule) for s in res.stages] == [
        (PLAN_REFUSED, "scope.empty"), (PLAN_COMPILED, ""), (PLAN_COMPILED, ""), (PLAN_COMPILED, ""),
        (PLAN_COMPILED, "")]
    assert [p.step is not None for p in res.steps] == [False, True, True, True]
    assert res.steps[0].why == "fylgja-test-golden-41263/branch-point was refused"


def link(a, pa, b, pb) -> dict:
    return {"id": f"{a}:{pa}|{b}:{pb}", "a": {"node": a, "port": pa}, "b": {"node": b, "port": pb}}


def node_added() -> StepDiff:
    """TestDiffNodeAdded's step: n4 added with its artifact, cabled to n1."""
    return StepDiff(
        nodes_added=["n4"], nodes_changed=[{"node": "n1", "reasons": ["bootstrap", "mapping"]}],
        links_added=[link("n1", "e1-3", "n4", "e1-1")],
        artifacts_changed=[{"node": "n1", "name": "device-config", "from": "28881d3d0d61d3fe5acf1f1ee0e31a60",
                            "to": "9a0177b2e8c1d4f5a6b7c8d9e0f1a2b3"}],
        artifacts_added=[{"node": "n4", "name": "device-config"}])


def test_diff_node_added():
    assert Pair.between("change-1/seeded", "change-1/third-link", ID_A, ID_B, node_added()).text() == "\n".join([
        "step change-1/seeded → change-1/third-link (35aea06f… → 9c2d01e7…):",
        "  nodes: +n4; ~n1 (bootstrap, mapping)",
        "  links: +n1:e1-3 — n4:e1-1",
        "  artifacts: n1 device-config 28881d3d… → 9a0177b2…; n4 device-config added",
    ])
    back = StepDiff(
        nodes_removed=["n4"], nodes_changed=[{"node": "n1", "reasons": ["bootstrap", "mapping"]}],
        links_removed=[link("n1", "e1-3", "n4", "e1-1")],
        artifacts_changed=[{"node": "n1", "name": "device-config", "from": "9a0177b2e8c1d4f5a6b7c8d9e0f1a2b3",
                            "to": "28881d3d0d61d3fe5acf1f1ee0e31a60"}],
        artifacts_removed=[{"node": "n4", "name": "device-config"}])
    assert Pair.between("change-1/third-link", "change-1/seeded", ID_B, ID_A, back).text() == "\n".join([
        "step change-1/third-link → change-1/seeded (9c2d01e7… → 35aea06f…):",
        "  nodes: -n4; ~n1 (bootstrap, mapping)",
        "  links: -n1:e1-3 — n4:e1-1",
        "  artifacts: n1 device-config 9a0177b2… → 28881d3d…; n4 device-config removed",
    ])


def test_pair_text_order():
    # The artifacts line is sorted by node across the three kinds of change, and the nodes
    # line puts added before removed before changed.
    s = StepDiff(nodes_removed=["n1"], nodes_changed=[{"node": "n2", "reasons": ["bootstrap"]}],
                 artifacts_changed=[{"node": "n3", "name": "device-config", "from": "95a3a91788e63626cdb9b4ecdf56eb58",
                                     "to": "9a0177b2e8c1d4f5a6b7c8d9e0f1a2b3"}],
                 artifacts_removed=[{"node": "n1", "name": "device-config"}])
    assert Pair.between("change-1/seeded", "change-1/third-link", ID_A, ID_B, s).text() == "\n".join([
        "step change-1/seeded → change-1/third-link (35aea06f… → 9c2d01e7…):",
        "  nodes: -n1; ~n2 (bootstrap)",
        "  links: unchanged",
        "  artifacts: n1 device-config removed; n3 device-config 95a3a917… → 9a0177b2…",
    ])


def test_pair_text_one_line():
    assert Pair.between("change-1/third-link", "change-1/live", ID_A, ID_B, StepDiff(unchanged=True)).text() == (
        "step change-1/third-link → change-1/live (35aea06f… → 9c2d01e7…): unchanged; the ids differ by provenance "
        "alone")
    assert Pair.not_computed("change-1/live", "change-1/head", ID_A, "", "change-1/head was refused").text() == (
        "step change-1/live → change-1/head (35aea06f… → —): not computed (change-1/head was refused)")
    assert Pair.between("change-1/seeded", "change-1/third-link", ID_A, ID_A, StepDiff(unchanged=True)).text() == (
        "step change-1/seeded → change-1/third-link (35aea06f… → 35aea06f…): unchanged; the two are one bundle")


def plan_document(pairs: list[Pair]) -> dict:
    """A stage.plan document carrying pairs, one more stage than pairs, to hold each pair to
    the contract's step."""
    _, res = golden_plan()
    res.steps = pairs
    res.stages = res.stages[: len(pairs) + 1]
    return res.document(SCOPE).to_dict()


def test_pair_json_satisfies_the_contract():
    pairs = [
        Pair.between("change-1/seeded", "change-1/third-link", ID_A, ID_B, node_added()),
        Pair.between("change-1/third-link", "change-1/live", ID_A, ID_B, StepDiff(unchanged=True)),
        Pair.not_computed("change-1/live", "change-1/head", ID_A, "", "change-1/head was refused"),
        Pair.not_computed("change-1/later", "change-1/head", "", "", "change-1/later and change-1/head were refused"),
    ]
    findings.validate(plan_document(pairs))
    raw = json.dumps(pairs[0].to_dict())
    for whole in (ID_A, ID_B, "28881d3d0d61d3fe5acf1f1ee0e31a60", "9a0177b2e8c1d4f5a6b7c8d9e0f1a2b3"):
        assert f'"{whole}"' in raw
    d = pairs[0].to_dict()
    assert d["computed"] is True and d["unchanged"] is False
    # An added node's artifact goes with the node: the contract lists changed ones alone.
    assert d["artifacts"] == {"changed": [{"node": "n1", "name": "device-config",
                                           "from": "28881d3d0d61d3fe5acf1f1ee0e31a60",
                                           "to": "9a0177b2e8c1d4f5a6b7c8d9e0f1a2b3"}]}
    assert pairs[2].to_dict() == {"from": "change-1/live", "to": "change-1/head", "from_bundle_id": ID_A,
                                  "to_bundle_id": None, "computed": False, "not_computed": "change-1/head was refused"}
    # A pair read back as the contract carries it renders the same.
    for p in pairs[1:]:
        assert Pair.from_dict(p.to_dict()) == p


def manifest(nodes: dict) -> bytes:
    listed = [{"name": n, "artifact": {"name": a} if a else None} for n, a in nodes.items()]
    return json.dumps({"nodes": listed}).encode()


def test_artifacts_moved():
    # An added node's artifact and one a node kept gained; a removed node's and one a node kept
    # lost; a host, which has none, never.
    was = manifest({"n1": "device-config", "n2": "device-config", "n3": None, "n5": "device-config",
                    "n1-loop-a": None})
    now = manifest({"n1": "device-config", "n3": "device-config", "n4": "device-config", "n5": None,
                    "n4-loop-a": None})
    added, removed = artifacts_moved(was, now)
    assert added == [{"node": "n3", "name": "device-config"}, {"node": "n4", "name": "device-config"}]
    assert removed == [{"node": "n2", "name": "device-config"}, {"node": "n5", "name": "device-config"}]


def test_the_step_of_a_twin_diff_answer():
    three = (REPOSITORY / "testdata" / "golden" / "three-node" / "manifest.json").read_bytes()
    four = json.loads(three)
    four["nodes"].append({"name": "n4", "artifact": {"name": "device-config"}})
    answer = {"operation": "twin.diff", "step": Pair.between("snapshot 1…", "snapshot 2…", ID_A, ID_B,
                                                               node_added()).to_dict()}
    s = step_of_diff(answer, three, json.dumps(four))
    assert s.artifacts_added == [{"node": "n4", "name": "device-config"}] and s.artifacts_removed == []
    assert s.nodes_added == ["n4"] and s.links_added == [link("n1", "e1-3", "n4", "e1-1")]
    assert step_of_diff(answer).artifacts_added == []
    assert step_of_diff({"step": {"computed": False}}) is None
    assert step_of_diff({}) is None


def stage(ref: str, bundle: str = "", **kw) -> PlanStage:
    return PlanStage(ref=ref, label=ref.split("/", 1)[1], bundle_id=bundle, **kw)


def test_pair_of():
    a, b, c, d = (stage("change-1/branch-point"), stage("change-1/seeded", ID_A), stage("change-1/later"),
                  stage("change-1/head", ID_B))
    assert pair_of(a, b) == Pair.not_computed(a.ref, b.ref, "", ID_A, "change-1/branch-point was refused")
    assert pair_of(b, c).why == "change-1/later was refused"
    assert pair_of(a, c).why == "change-1/branch-point and change-1/later were refused"
    assert pair_of(b, d, StepDiff(unchanged=True)) == Pair.between(b.ref, d.ref, ID_A, ID_B, StepDiff(unchanged=True))
    with pytest.raises(ValueError, match="no step was given"):
        pair_of(b, d)


def test_a_stage_stopped():
    # The first rejection's rule, operation.failed making it failed; a warning before it is
    # kept and named by no rule.
    refused = stage("change-1/seeded").stop([
        findings.Finding(WARNING, "stage.main.moved", "change-1", "main moved", "resolve"),
        findings.Finding(REJECTION, "stage.artifact.stale", "n1", "stale", "resolve"),
        findings.Finding(REJECTION, "scope.empty", "tag:fylgja", "none", "read"),
    ])
    assert (refused.status, refused.rule) == (PLAN_REFUSED, "stage.artifact.stale")
    assert refused.lines()[0] == "change-1/seeded: refused (stage.artifact.stale)"
    failed = stage("change-1/seeded").stop([findings.Finding(REJECTION, "operation.failed", "change-1/seeded",
                                                             "the read could not run", "read")])
    assert (failed.status, failed.rule) == (PLAN_FAILED, "operation.failed")
    assert failed.lines() == ["change-1/seeded: failed (operation.failed)",
                              "  rejection operation.failed [step read] change-1/seeded: the read could not run"]


def test_a_plan_refused_whole():
    refusal = Findings([findings.Finding(REJECTION, "stage.unknown", "change-9",
                                         "branch change-9 has no open proposed change", "resolve")])
    res = PlanResult(branch="change-9", findings=refusal)
    doc = res.document(SCOPE)
    assert res.block() is None and "plan" not in doc.to_dict() and doc.status == "rejected"
    assert res.lines(SCOPE) == []
    findings.validate(doc.to_dict())


def test_read_counts():
    read = {"devices": 3, "interfaces": 15, "links": 3, "artifacts": 3, "lossy_mappings": 1, "shared_ports": 2}
    assert read_counts(read, [("arista_eos", 2), ("nokia_srlinux", 1)]) == (
        "3 devices (arista_eos 2, nokia_srlinux 1), 15 interfaces, 3 links, 3 artifacts, 1 lossy mappings, "
        "2 shared ports")
    assert read_counts(read, []).startswith("3 devices, 15 interfaces")


def test_a_compiled_stage_block_names_its_ids_and_a_refused_one_nulls():
    _, res = golden_plan()
    refused, seeded = res.stages[0].block(), res.stages[1].block()
    assert refused["snapshot_id"] is None and refused["bundle_id"] is None and refused["read"] is None
    assert seeded["snapshot_id"].startswith("78232019") and seeded["bundle_id"].startswith("ce705cdb")
    # A stage refused at resolution carries its reference, label, description and source
    # alone, its branch and at left out.
    early = PlanStage(ref="change-1/later", label="later", description="later", at_source="given").stop(
        [findings.Finding(REJECTION, "stage.at.future", "change-1/later", "in the future", "resolve")])
    assert list(early.block()) == ["ref", "label", "description", "at_source", "snapshot_id", "bundle_id", "read",
                                   "findings"]
