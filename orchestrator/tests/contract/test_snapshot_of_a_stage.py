"""A stage's snapshot against a real Infrahub (T021; SC-002, SC-004), as
`internal/server/snapshot_contract_test.go`'s `TestStageTakenTwiceHasOneSnapshot` and
`TestStepTargetFromASnapshot`'s read half held the Go server to it.

One stage taken twice has one snapshot: on a seeded branch with a draft proposed change and
one mark, the stage plan runs twice (conftest's `plan_of`, the adapter's takes and a core
server's compiles); each compiled stage names one snapshot id and one bundle id in both, the
two takes of each differing in observed_at alone. The store that keeps the first take is the
core's, which a step's target files into (`resolveSnapshot`): a core server of the test's own
files the first plan's takes through `twin diff`, then the second plan's, and keeps each first
entry, bytes and modification time, adding none.

A step's snapshot target is what `stage plan` compiles from the same read: `read --stage
--out`, through a recording proxy, writes the snapshot the plan's mark names, with the mark's
branch, at and scope; the core then files it from the file and builds it from the id, each to
the plan's bundle, with no request to Infrahub, since the core holds no INFRAHUB_*. No twin
boots. The branch, its proposed change and its stage are deleted when each test ends.

    set -a; . local/.env; set +a; orchestrator/.venv/bin/pytest -q orchestrator -m contract -k test_snapshot_of_a_stage
"""

import copy
import io
import json
import os
import time

import pytest

from fylgja_orchestrator.adapters.infrahub import __main__ as adapter
from fylgja_orchestrator.adapters.infrahub import snapshot, stages
from fylgja_orchestrator.documents import findings

from .conftest import PLAN_COMPILED, SCOPE, plan_of

pytestmark = pytest.mark.contract

LABEL = "seeded"


def entries(directory) -> dict[str, tuple[bytes, int]]:
    """A store's entries by name: what each holds and when it was written."""
    if not directory.is_dir():
        return {}
    return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in sorted(directory.iterdir()) if p.is_file()}


def test_stage_taken_twice_has_one_snapshot(fixture_tool, core, own_core, tmp_path):
    with fixture_tool.throwaway("taken-twice") as branch:
        fixture_tool.propose(branch)
        fixture_tool.mark(branch, LABEL, description=LABEL)

        first = plan_of(branch, core, tmp_path / "first")
        compiled = {p.stage.label: p for p in first.stages if p.status == PLAN_COMPILED}
        assert sorted(compiled) == sorted([LABEL, stages.LABEL_HEAD]), (
            f"the first plan compiled {sorted(compiled)}; want {LABEL} and head (the branch point reads main, which "
            f"holds no device): {first.outcomes}")
        for p in compiled.values():
            print(f"{p.stage.ref}: snapshot {p.snapshot['snapshot_id']}, bundle {p.bundle_id}")

        # The core files each compiled stage's take, as a step to it would.
        snapshots = own_core.state / "snapshots"

        def file_all(plan) -> None:
            for p in plan.stages:
                if p.status == PLAN_COMPILED:
                    code, doc = own_core.diff(p.path, p.path)
                    assert code == 0, doc
                    assert (doc["snapshot_from"], doc["bundle_from"]) == (p.snapshot["snapshot_id"], p.bundle_id)

        file_all(first)
        before = entries(snapshots)
        named = sorted(p.snapshot["snapshot_id"] + ".json" for p in compiled.values())
        assert sorted(before) == named, f"the core filed {sorted(before)}; want the entries the stages name, {named}"
        # Back-date every entry, so a rewrite within the clock's resolution could not hide.
        old = time.time_ns() - 3600 * 10**9
        for name in before:
            os.utime(snapshots / name, ns=(old, old))
        before = entries(snapshots)

        second = plan_of(branch, core, tmp_path / "second")
        assert [p.stage.label for p in second.stages] == [p.stage.label for p in first.stages]
        for a, b in zip(first.stages, second.stages, strict=True):
            sid = (a.snapshot or {}).get("snapshot_id"), (b.snapshot or {}).get("snapshot_id")
            assert sid[0] == sid[1], f"{a.stage.ref} names snapshot {sid[1]} in the second plan and {sid[0]} first"
            assert a.bundle_id == b.bundle_id, f"{a.stage.ref} compiles to {b.bundle_id} and {a.bundle_id}"
            if a.status == PLAN_COMPILED:
                assert a.snapshot["observed_at"] != b.snapshot["observed_at"], "the two takes were observed at one time"
                x, y = copy.deepcopy(a.snapshot), copy.deepcopy(b.snapshot)
                for t in (x, y):
                    t["observed_at"] = t["ctm"]["envelope"]["observed_at"] = "2000-01-01T00:00:00.000000Z"
                assert snapshot.marshal(x) == snapshot.marshal(y), f"{a.stage.ref}'s takes differ beyond observed_at"

        file_all(second)
        after = entries(snapshots)
        assert sorted(after) == sorted(before), f"after the second plan the store holds {sorted(after)}"
        for name, (data, mtime) in before.items():
            assert after[name][0] == data, f"the second plan rewrote {name}; the store keeps the first take"
            assert after[name][1] == mtime, f"{name} was modified by the second plan"
        assert not list((own_core.state / "bundles").glob("*.ctm.json")), "a CTM was written beside the bundles"
        print(f"{LABEL} taken twice: snapshot {compiled[LABEL].snapshot['snapshot_id']}")


def test_step_target_from_a_snapshot(fixture_tool, core, own_core, proxy, tmp_path):
    with fixture_tool.throwaway("target") as branch:
        fixture_tool.propose(branch)
        fixture_tool.mark(branch, LABEL, description=LABEL)
        ref = str(stages.Ref(branch, LABEL))

        # The plan's stage: the snapshot and the bundle a stage step to it would build.
        plan = plan_of(branch, core, tmp_path / "plan")
        [mark] = [p for p in plan.stages if p.stage.label == LABEL]
        assert mark.status == PLAN_COMPILED, plan.outcomes
        sid, bid, at = mark.snapshot["snapshot_id"], mark.bundle_id, mark.resolved.at
        print(f"stage plan: {ref} at {at} compiled to snapshot {sid}, bundle {bid}")

        # read --stage --out of the mark: the file the adapter writes.
        out = tmp_path / "snap.json"
        stdout, stderr = io.StringIO(), io.StringIO()
        env = adapter.Env(environ={**os.environ, "INFRAHUB_ADDRESS": proxy.address})
        code = adapter.main(["read", "--stage", ref, "--scope", SCOPE, "--out", str(out), "--json"], stdout, stderr,
                            env)
        doc = json.loads(stdout.getvalue())
        assert code == findings.EXIT_OK and doc["snapshot_id"] == sid, doc
        findings.validate(doc)
        read = len(proxy.recorded)
        assert read, "the read sent no request through the proxy, so its count proves nothing"
        file = out.read_bytes()
        s = snapshot.unmarshal(file)
        assert s["snapshot_id"] == sid
        e = s["ctm"]["envelope"]
        assert (e["branch"], e.get("at"), e["scope"]) == (branch, at, SCOPE), e
        print(f"read --stage --out: snapshot {sid} observed at {s['observed_at']}; {read} request(s) to Infrahub")

    # The target, built by a core holding no INFRAHUB_*, after the branch is gone: from the
    # file, then from the id it was filed under. Each names the plan's snapshot and bundle.
    def build(how: str, arg: str) -> None:
        code, doc = own_core.run("twin", "diff", "--from", arg, "--to", arg)
        assert code == 0, f"the target from the {how} was refused: {doc['findings']}"
        assert (doc["snapshot_from"], doc["bundle_from"]) == (sid, bid), doc
        stored = entries(own_core.state / "snapshots")
        assert list(stored) == [sid + ".json"], f"after the target from the {how} the store holds {list(stored)}"
        assert stored[sid + ".json"][0] == file, f"the store's entry is not the file the read sent ({how})"
        assert sorted(p.name for p in (own_core.state / "bundles").iterdir()) == [bid]
        print(f"the target from the {how}: snapshot {sid}, bundle {bid}")

    build("file", str(out))
    build("id", sid)
    assert len(proxy.recorded) == read, "the core's target sent a request to Infrahub"
