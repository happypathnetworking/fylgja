"""The stage plan of a throwaway proposed change with three stages (T028; R-15, FR-028, SC-006).

The golden's composition (research §5.1): a throwaway branch with a draft, the mark `seeded`,
a link added and rendered and the mark `third-link`, a port added on n1 and rendered and the
mark `bad-port`. `stage-plan` runs on Prefect's test harness against the real Infrahub and a
core server of the test's own (no INFRAHUB_*), which compiles each stage and computes the
step between each consecutive pair; the branch point is refused `scope.empty`. Until T035 the
plan was also held to `bin/fylgja stage plan --json` through the host's server, the Go
handler, steps equal and each stage equal but for research §5.17's and §5.20's departures
(SC-006; green last in Run 25, research §5.20); the comparison went with the Go handler, and
the flow's own assertions stay.

Nothing of the host's is written. The branch, its stages and its proposed change are deleted
when the test ends. Boot no twin while it runs.

    set -a; . local/.env; set +a; orchestrator/.venv/bin/pytest -q orchestrator -m contract \
        -k test_stage_plan_of_a_throwaway_change -s
"""

import pytest

from fylgja_orchestrator.adapters.infrahub.stages import LABEL_BRANCH_POINT, LABEL_HEAD

from .conftest import SCOPE, artifact_of, await_joined, await_moved, checksums, flow_runs_of, use_core

pytestmark = pytest.mark.contract

UNREPRESENTED = "artifact.interface.unrepresented"
UNMAPPABLE = "omit.interface.unmappable"
PORT = "ethernet-1/99"


def test_stage_plan_of_a_throwaway_change(platform, fixture_tool, own_core, tmp_path, monkeypatch):
    from fylgja_orchestrator.flows.stage_plan import stage_plan

    with fixture_tool.throwaway("plan") as name:
        id = fixture_tool.propose(name)
        # Each mark written last, after the writes it seals and after their generate.
        fixture_tool.mark(name, "seeded", description="seeded")
        before = checksums(name)
        fixture_tool.change(name, "-add-link")
        await_moved(name, before, "n1", "n3")
        await_joined(name)
        fixture_tool.mark(name, "third-link", description="third link")
        before = checksums(name)
        fixture_tool.change(name, "-add-interface", f"n1:{PORT}")
        fixture_tool.change(name, "-generate")
        await_moved(name, before, "n1")
        await_joined(name, "n1", PORT)
        fixture_tool.mark(name, "bad-port", description="a port the push refuses")

        flows = use_core(monkeypatch, own_core, tmp_path / "orchestrator")
        doc, took = flows.run(stage_plan, branch=name, scope=SCOPE)
        print(f"stage plan: the flow {took:.1f}s")
        print(flows.text())

        plan = doc.blocks["plan"]
        assert plan["proposed_change"]["id"] == id, plan["proposed_change"]
        labels = [s["label"] for s in plan["stages"]]
        assert labels == [LABEL_BRANCH_POINT, "seeded", "third-link", "bad-port", LABEL_HEAD], labels
        bp, seeded, third, bad, head = plan["stages"]
        assert [f["rule"] for f in bp["findings"]] == ["scope.empty"] and not bp.get("bundle_id"), bp
        for s in (seeded, third, bad, head):
            assert s.get("snapshot_id") and s.get("bundle_id"), s
        assert len({s["bundle_id"] for s in (seeded, third, bad)}) == 3, plan["stages"]
        for s in (bad, head):
            warned = [f for f in s["findings"] if f["rule"] == UNREPRESENTED and f["object"] == f"n1:{PORT}"]
            assert warned and UNMAPPABLE in warned[0]["message"], s["findings"]
        steps = plan["steps"]
        pairs = [(s["from"].split("/")[-1], s["to"].split("/")[-1], s["computed"], s.get("unchanged")) for s in steps]
        assert pairs == [
            (LABEL_BRANCH_POINT, "seeded", False, None), ("seeded", "third-link", True, False),
            ("third-link", "bad-port", True, False), ("bad-port", LABEL_HEAD, True, True)], steps
        assert [n["node"] for n in steps[1]["nodes"]["changed"]] == ["n1", "n3"], steps[1]
        assert len(steps[1]["links"]["added"]) == 1, steps[1]
        assert [n["node"] for n in steps[2]["nodes"]["changed"]] == ["n1"], steps[2]

        # The core compiled and diffed, and was asked nothing else; the run filed its document.
        asked = {op for op, _ in own_core.operations()}
        assert asked == {"twin.compile", "twin.diff"}, own_core.operations()
        [run] = flow_runs_of("stage-plan")[:1]
        assert run.state.is_completed(), run.state
        assert artifact_of(str(run.id)) == doc.to_dict()
