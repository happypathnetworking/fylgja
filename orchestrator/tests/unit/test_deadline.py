"""A rehearsal's deadline held to `internal/rehearsal/deadline_test.go`: `TestDeadline`'s cases
by name, then the budgets read from a compiled bundle's manifest and the packages (research
§5.16), the golden rehearsal's 2,580 s from the four compiled stages of its plan, the
mechanism's constants held to the Go source, and `rehearsal.deadline.unfit` as the server
worded it."""

import re
import shutil
from pathlib import Path

import pytest

from fylgja_orchestrator.documents import deadline as d
from fylgja_orchestrator.documents.deadline import (
    CEILING_S,
    MECHANISM,
    ROLE_BASELINE,
    ROLE_REFUSED,
    ROLE_REHEARSED,
    DeadlineStage,
    NodePlan,
    deadline,
    fits,
)
from fylgja_orchestrator.documents.findings import REJECTION

REPOSITORY = Path(__file__).resolve().parents[3]


def node(name, deploy, readiness, push, destroy) -> NodePlan:
    """One node's plan with its package's four budgets."""
    return NodePlan(name, deploy, readiness, push, destroy)


def srl(name):
    return node(name, 180, 60, 30, 60)


def eos(name):
    return node(name, 300, 90, 30, 60)


def fixture_nodes():
    return (srl("n1"), srl("n2"), srl("n3"))


def host(name, start, read) -> NodePlan:
    """A probe's host with the ping package's budgets, its flow's start and read as given."""
    return NodePlan(name, 60, 30, 0, 30, host=True, start_timeout_s=start, read_timeout_s=read)


def probed_nodes():
    return fixture_nodes() + (host("n1-loop-a", 30, 30), host("n1-loop-b", 30, 30), host("n3-loop-a", 30, 30),
                              host("n3-loop-b", 30, 30))


def stages_of(roles, nodes):
    return [DeadlineStage(r, tuple(nodes)) for r in roles]


MIXED = (srl("n1"), eos("n2"), srl("n3"))


@pytest.mark.parametrize("name,stages,want", [
    # The fixture's branch point is refused and adds nothing: the baseline 570, two marks and
    # the head 630 each, the destroy 120.
    ("the fixture's refused branch point, two marks and the head",
     [DeadlineStage(ROLE_REFUSED)] + stages_of([ROLE_BASELINE, ROLE_REHEARSED, ROLE_REHEARSED], fixture_nodes()), 1950),
    ("a compiled branch point", stages_of([ROLE_BASELINE] + [ROLE_REHEARSED] * 3, fixture_nodes()), 2580),
    # Each budget is the largest over a stage's nodes: the baseline 720, each step 780.
    ("the mixed fixture's three stages", stages_of([ROLE_BASELINE, ROLE_REHEARSED, ROLE_REHEARSED], MIXED), 2400),
    ("one stage alone is the baseline and the destroy", stages_of([ROLE_BASELINE], fixture_nodes()), 570 + 120),
    # Each rehearsed stage starts and reads its hosts' flows, (30 + 15) + (30 + 15); the
    # baseline starts none.
    ("the probed fixture's refused branch point, two marks and the head",
     [DeadlineStage(ROLE_REFUSED)] + stages_of([ROLE_BASELINE, ROLE_REHEARSED, ROLE_REHEARSED], probed_nodes()),
     570 + 720 + 720 + 120),
])
def test_deadline(name, stages, want):
    assert deadline(MECHANISM, stages) == want, name
    assert fits(want, CEILING_S), name


def test_deadline_takes_each_budgets_largest():
    # The deploy from one node and the destroy from another.
    odd = (node("a", 100, 10, 5, 200), node("b", 300, 90, 40, 60))
    want = 30 + 60 + 300 + (90 + 15) + (40 + 15) + 30 + (120 + 30) + 30 + 200 + 30
    assert deadline(MECHANISM, stages_of([ROLE_BASELINE], odd)) == want

    # The flows' budgets are each the largest over a rehearsed stage's hosts.
    hosts = fixture_nodes() + (host("a", 10, 40), host("b", 25, 5))
    base = deadline(MECHANISM, stages_of([ROLE_REHEARSED], fixture_nodes()))
    assert deadline(MECHANISM, stages_of([ROLE_REHEARSED], hosts)) == base + 25 + 15 + 40 + 15


def test_a_stage_list_over_the_ceiling():
    # Six marks of the mixed twin need 720 + 6×780 + 120 = 5,520 s.
    over = deadline(MECHANISM, stages_of([ROLE_BASELINE] + [ROLE_REHEARSED] * 6, MIXED))
    assert over == 5520 and not fits(over, CEILING_S)
    assert fits(CEILING_S, CEILING_S) and not fits(CEILING_S + 1, CEILING_S)
    assert CEILING_S == 3600


def _go_seconds(path: Path, name: str) -> int:
    match = re.search(rf"\b{name}\s*=\s*(\d+)\s*\*\s*time\.Second", path.read_text())
    assert match, f"{name} in {path}"
    return int(match.group(1))


def test_the_mechanism_is_the_cores():
    options = REPOSITORY / "internal" / "provision" / "options.go"
    want = d.Mechanism(
        check_host=_go_seconds(options, "CheckHostBudget"), stage=_go_seconds(options, "StageBudget"),
        record=_go_seconds(options, "RecordBudget"), plan_teardown=_go_seconds(options, "PlanTeardownBudget"),
        unstage=_go_seconds(options, "UnstageBudget"), inspect_twin=_go_seconds(options, "InspectTwinBudget"),
        readiness_margin=_go_seconds(options, "ReadinessMargin"), push_margin=_go_seconds(options, "PushMargin"),
        verify_margin=_go_seconds(options, "VerifyMargin"), flows_margin=_go_seconds(options, "FlowsMargin"),
        wait=_go_seconds(REPOSITORY / "internal" / "verify" / "wait.go", "DefaultBudget"),
    )
    assert want == MECHANISM


def test_the_packages_budgets():
    budgets = d.load_budgets()
    assert budgets.psp["nokia_srlinux"] == NodePlan("", 180, 60, 30, 60)
    assert budgets.psp["arista_eos"] == NodePlan("", 300, 90, 30, 60)
    assert budgets.probes["ping"] == NodePlan("", 60, 30, 0, 30, host=True, start_timeout_s=30, read_timeout_s=30)


def test_an_override_shadows_a_shipped_package(tmp_path, monkeypatch):
    override = tmp_path / "psp"
    override.mkdir()
    text = (REPOSITORY / "psp" / "nokia_srlinux.yaml").read_text()
    (override / "nokia_srlinux.yaml").write_text(text.replace("deploy_timeout_s: 180", "deploy_timeout_s: 240"))
    monkeypatch.setenv(d.ENV_PSP_OVERRIDE, str(override))
    budgets = d.load_budgets()
    assert budgets.psp["nokia_srlinux"].deploy_timeout_s == 240
    assert budgets.psp["arista_eos"].deploy_timeout_s == 300


def _bundle(name: str) -> dict[str, bytes]:
    root = REPOSITORY / "testdata" / "golden" / name
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_node_plans_from_a_compiled_bundle():
    budgets = d.load_budgets()
    assert d.node_plans(_bundle("three-node"), budgets) == (
        NodePlan("n1", 180, 60, 30, 60), NodePlan("n2", 180, 60, 30, 60), NodePlan("n3", 180, 60, 30, 60))
    probed = d.node_plans(_bundle("three-node-probed"), budgets)
    assert [n.name for n in probed] == ["n1", "n1-loop-a", "n1-loop-b", "n2", "n3"]
    assert probed[1] == NodePlan("n1-loop-a", 60, 30, 0, 30, host=True, start_timeout_s=30, read_timeout_s=30)
    mixed = d.node_plans(_bundle("mixed"), budgets)
    assert [(n.name, n.deploy_timeout_s) for n in mixed] == [("e1", 300), ("e2", 300), ("s1", 180)]


def test_a_node_whose_package_is_not_held_is_left_out():
    budgets = d.load_budgets()
    only_srl = d.Budgets({"nokia_srlinux": budgets.psp["nokia_srlinux"]}, {})
    assert [n.name for n in d.node_plans(_bundle("mixed"), only_srl)] == ["s1"]
    assert [n.name for n in d.node_plans(_bundle("three-node-probed"), only_srl)] == ["n1", "n2", "n3"]


def test_a_bundle_with_no_manifest_is_refused():
    with pytest.raises(ValueError, match="manifest.json"):
        d.node_plans({"topology.clab.yml": b""}, d.load_budgets())
    with pytest.raises(ValueError, match="manifest.json"):
        d.node_plans({"manifest.json": b"{"}, d.load_budgets())


def test_the_golden_rehearsals_deadline():
    # The golden's plan: the branch point refused, then seeded, third-link, bad-port and the
    # head compiled on the three-node fixture's devices, a baseline and three rehearsed.
    plans = d.node_plans(_bundle("three-node"), d.load_budgets())
    stages = [DeadlineStage(ROLE_REFUSED)] + stages_of([ROLE_BASELINE] + [ROLE_REHEARSED] * 3, plans)
    assert deadline(MECHANISM, stages) == 2580


def test_go_duration():
    for seconds, want in [(0, "0s"), (30, "30s"), (60, "1m0s"), (2580, "43m0s"), (3600, "1h0m0s"), (3840, "1h4m0s"),
                          (5520, "1h32m0s"), (90061, "25h1m1s")]:
        assert d.go_duration(seconds) == want


def test_unfit():
    found = d.unfit("change-1", 3840)
    assert len(found) == 1
    f = found[0]
    assert (f.severity, f.step, f.rule, f.object) == (REJECTION, "start", "rehearsal.deadline.unfit", "change-1")
    assert f.message == ("the stages need 1h4m0s (3840s) to be rehearsed, over the ceiling of 1h0m0s (3600s): "
                         "no rehearsal is started whose budgets cannot end within it; rehearse fewer stages")


def test_the_budgets_read_the_repositorys_packages(tmp_path):
    # Directories given explicitly read those alone, a later one shadowing an earlier.
    shutil.copy(REPOSITORY / "probes" / "ping.yaml", tmp_path / "ping.yaml")
    budgets = d.load_budgets(psp_dirs=[], probe_dirs=[tmp_path])
    assert budgets.psp == {} and set(budgets.probes) == {"ping"}
