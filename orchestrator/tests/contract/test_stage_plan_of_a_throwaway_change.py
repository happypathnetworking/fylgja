"""The stage plan of a throwaway proposed change with three stages (T028; R-15, FR-028, SC-006).

The golden's composition (research §5.1): a throwaway branch with a draft, the mark `seeded`,
a link added and rendered and the mark `third-link`, a port added on n1 and rendered and the
mark `bad-port`. `stage-plan` runs on Prefect's test harness against the real Infrahub and a
core server of the test's own (no INFRAHUB_*), which compiles each stage and computes the
step between each consecutive pair; then `bin/fylgja stage plan --branch … --json` through the
host's server, the Go handler, which still stands. The plan block's steps are equal, and so is
each stage but for what the departures name (research §5.17, §5.20: a stage's `read` counts its lossy
mappings from the compiled manifest, and a package's rule is the core's, at compile, where
the Go reader also ran it at read); the branch point is refused `scope.empty` in both. The
comparison goes with the Go handler (T035), the flow's own assertions stay.

The host's server files each stage's snapshot into the host's store, as T021's compare does;
nothing else of the host's is written. The branch, its stages and its proposed change are
deleted when the test ends. Boot no twin while it runs.

    set -a; . local/.env; set +a; orchestrator/.venv/bin/pytest -q orchestrator -m contract \
        -k test_stage_plan_of_a_throwaway_change -s
"""

import json
import os
import subprocess
import time

import pytest

from fylgja_orchestrator.adapters.infrahub.stages import LABEL_BRANCH_POINT, LABEL_HEAD

from .conftest import REPO, SCOPE, artifact_of, await_joined, await_moved, checksums, flow_runs_of, redact, use_core

pytestmark = pytest.mark.contract

UNREPRESENTED = "artifact.interface.unrepresented"
UNMAPPABLE = "omit.interface.unmappable"
PORT = "ethernet-1/99"


@pytest.fixture
def go_stage_plan():
    """`bin/fylgja stage plan --branch … --json` through the host's server, with the API's
    address and token alone, taken before the test points the process at its own core: its
    exit, its document and its time."""
    binary = REPO / "bin" / "fylgja"
    token = os.environ.get("FYLGJA_API_TOKEN", "")
    if not binary.is_file() or not token:
        pytest.skip("the compare needs bin/fylgja (make build) and FYLGJA_API_TOKEN (load local/.env)")
    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""), "FYLGJA_API_TOKEN": token}
    if os.environ.get("FYLGJA_API_ADDRESS"):
        env["FYLGJA_API_ADDRESS"] = os.environ["FYLGJA_API_ADDRESS"]

    def run(branch: str) -> tuple[int, dict, float]:
        started = time.monotonic()
        done = subprocess.run([str(binary), "stage", "plan", "--branch", branch, "--scope", SCOPE, "--json"],
                              env=env, capture_output=True, text=True, timeout=600)
        took = time.monotonic() - started
        try:
            return done.returncode, json.loads(done.stdout), took
        except ValueError:
            pytest.skip(f"the host's server did not answer fylgja stage plan: {redact(done.stderr.strip())}")

    return run


def comparable(stage: dict) -> dict:
    """A plan's stage as both sides must agree on it: its findings by severity, step, rule and
    object, the words being each side's, and its `read` counts but the lossy two, which the
    flow takes from the manifest (research §5.17). A finding at step read that the compile
    files again on the same object is dropped: the Go reader ran the package's rules at read
    as well, which the adapter leaves to the core's compile (research §5.11, §5.20), so the
    flow's plan files each once, at compile."""
    found = [(f["severity"], f.get("step"), f["rule"], f["object"]) for f in stage["findings"]]
    at_compile = {(rule, obj) for _, step, rule, obj in found if step == "compile"}
    out = {k: v for k, v in stage.items() if k not in ("read", "findings")}
    out["findings"] = [f for f in found if not (f[1] == "read" and (f[2], f[3]) in at_compile)]
    read = stage.get("read")
    out["read"] = {k: v for k, v in read.items() if k not in ("lossy_mappings", "shared_ports")} if read else read
    return out


def test_stage_plan_of_a_throwaway_change(platform, fixture_tool, own_core, go_stage_plan, tmp_path, monkeypatch):
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
        code, go, go_took = go_stage_plan(name)
        print(f"stage plan: the flow {took:.1f}s, the Go handler through the host's server {go_took:.1f}s")
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

        # SC-006: the steps the Go handler computes for the same proposed change.
        assert (code, go["status"]) == (doc.exit_code, doc.status), (
            code, go["status"], doc.status, [(f["rule"], f["object"], f["message"][:200]) for f in go["findings"]
                                             if f["severity"] == "rejection"])
        assert steps == go["plan"]["steps"]
        for ours, theirs in zip(plan["stages"], go["plan"]["stages"], strict=True):
            assert comparable(ours) == comparable(theirs), (comparable(ours), comparable(theirs))
        assert plan["proposed_change"] == go["plan"]["proposed_change"]

        # The core compiled and diffed, and was asked nothing else; the run filed its document.
        asked = {op for op, _ in own_core.operations()}
        assert asked == {"twin.compile", "twin.diff"}, own_core.operations()
        [run] = flow_runs_of("stage-plan")[:1]
        assert run.state.is_completed(), run.state
        assert artifact_of(str(run.id)) == doc.to_dict()
