"""A proposed change's stages as the adapter reads them from a real Infrahub (T021; D-045 to
D-048), as `internal/stages/stages_contract_test.go` held the Go reader to it: the kind on
the default branch and the product's reader of it; a proposed change with marks listed and
planned as the branch point, each mark at its write stamp and the head one microsecond after
the branch's latest; a mark's read the read of its branch at its at (SC-002); a mark edited,
relabelled and given an as_of; the refusals (a stale mark, a rebase, a reserved label, a
future as_of, an unknown label, a closed proposed change, an unknown branch); and the
staleness rule seeing every write of a device and a removal.

The plan is the Go tests' `planOf` made of the adapter's halves and the core's (conftest's
`plan_of`): each stage resolved and taken by the adapter, compiled by a core server of the
test's own, and each two consecutive compiled stages diffed by its `twin diff`, since
`stage plan` is the orchestrator's flow's (T025). On this install's main, which holds no
tagged device, the branch point is refused scope.empty and stage.main.moved is never filed:
its warning's case is tier 1's (`tests/unit/test_stages.py`), since no test writes main.

Each test seeds its own throwaway `fylgja-test-py-*` branch through the fixture tool,
proposes from it and deletes, when it ends, the stages, the proposed change and the branch.
Boot no twin while they run.

    set -a; . local/.env; set +a; orchestrator/.venv/bin/pytest -q orchestrator -m contract -k test_stages
"""

import json
import re
import time
from datetime import UTC, datetime, timedelta

import pytest

from fylgja_orchestrator.adapters.infrahub import __main__ as adapter
from fylgja_orchestrator.adapters.infrahub import stages
from fylgja_orchestrator.adapters.infrahub import read as reading
from fylgja_orchestrator.adapters.infrahub import stage_reader as sr
from fylgja_orchestrator.adapters.infrahub.client import Client, default_from_env, from_env
from fylgja_orchestrator.documents.findings import STATUS_OK

from .conftest import (
    PLAN_COMPILED,
    PLAN_REFUSED,
    SCOPE,
    TEST_PREFIX,
    artifacts_ready_at,
    await_joined,
    await_moved,
    branch_origin,
    checksums,
    find,
    plan_of,
    refused,
    resolve,
    stage_reader,
    stamper,
)

pytestmark = pytest.mark.contract

BP, HEAD = stages.LABEL_BRANCH_POINT, stages.LABEL_HEAD
SCOPE_EMPTY = reading.RULE_SCOPE_EMPTY
STALE = stages.RULE_STAGE_ARTIFACT_STALE
EVENT = "(Infrahub's event log: "


def nanos(t: datetime) -> int:
    return int(t.timestamp()) * 1_000_000_000 + t.microsecond * 1000


def schema_hash(branch: str = "") -> str:
    """A branch's schema hash as GET /api/schema/summary gives it, under the key main whatever
    the branch; "" is the default branch."""
    path = "/api/schema/summary" + (f"?branch={branch}" if branch else "")
    body, status = Client(from_env("main")).get(path, "reading the schema summary")
    assert status == 200, f"GET {path}: HTTP {status}"
    hashed = json.loads(body).get("main")
    assert hashed, f"{path} gave no schema hash"
    return hashed


def test_stage_kind_loads(fixture_tool):
    """The kind is on the default branch with its three attributes, its relationship and the
    extension, the waypoint kind it replaced is not (D-045), and the product's reader accepts
    it. With the kind and the schema library there, the schema load on a throwaway branch is
    an empty diff: its hash is main's. A stage marked through the default branch's GraphQL is
    read with its proposed change; a second of its label on the same proposed change is
    refused by Infrahub naming the uniqueness constraint, and a label holding a '/' by the
    regex. Deleting the stages leaves none the product can see, and no orphan."""
    reader = stage_reader()
    reader.check()

    nodes = {n["kind"]: n for n in default_from_env().schema_nodes()}
    assert "FylgjaWaypoint" not in nodes, "main's schema still lists FylgjaWaypoint; 014 removes it"
    stage = nodes[sr.STAGE_KIND]
    assert stage.get("branch") == "agnostic"
    assert stage.get("uniqueness_constraints") == [["proposed_change", "label__value"]]
    attrs = {a["name"]: (a["kind"], a["optional"], a.get("regex") or "") for a in stage["attributes"]}
    assert attrs == {
        "label": ("Text", False, stages.LABEL_PATTERN),
        "as_of": ("DateTime", True, ""),
        "description": ("Text", True, ""),
    }
    rels = [(r["peer"], r["cardinality"], r["optional"]) for r in stage["relationships"]
            if r["name"] == sr.STAGE_RELATIONSHIP]
    assert rels == [(sr.PROPOSED_CHANGE_KIND, "one", False)]
    ext = [(r["peer"], r["cardinality"]) for r in nodes[sr.PROPOSED_CHANGE_KIND]["relationships"]
           if r["name"] == sr.STAGE_EXTENSION]
    assert ext == [(sr.STAGE_KIND, "many")]

    with fixture_tool.throwaway("kind", schema_only=True) as name:
        assert schema_hash(name) == schema_hash(), (
            "loading schema/ on the branch moved its schema hash from main's; with the library and the kind on the "
            "default branch the load is an empty diff")
        print(f"branch {name}, schema hash {schema_hash(name)} (the default branch's)")
        id = fixture_tool.propose(name)
        _, stamp = fixture_tool.mark(name, "seeded", description="from the harness")

        def mine(branch: str) -> list[sr.ProposedChange]:
            return [pc for pc in reader.proposed_changes(branch) if pc.branch == name]

        [pc] = mine(name)
        assert (pc.id, pc.name, pc.destination, pc.state, pc.draft) == (id, name, "main", "open", True)
        assert [(m.label, m.label_written_at, m.at, m.description) for m in pc.stages] == [
            ("seeded", stamp, None, "from the harness")]
        # An empty filter is no filter: every open proposed change, this one among them.
        assert [pc.id for pc in mine("")] == [id]
        branched_from, created_at = branch_origin(name)
        assert reader.branch(name) == sr.BranchInfo(name, branched_from, created_at)
        assert reader.branch(name + "-absent") is None

        # One label per proposed change: the same label again is refused at the write, and so
        # is a label the kind's regex refuses.
        with pytest.raises(RuntimeError, match="uniqueness constraint"):
            fixture_tool.mark(name, "seeded")
        with pytest.raises(RuntimeError, match="regex"):
            fixture_tool.mark(name, "a/b")
        [pc] = mine(name)
        assert len(pc.stages) == 1, f"after the refused writes the product reads {pc.stages}; want the one stage"

        assert "deleted 1 stage of proposed change" in fixture_tool.run("-branch", name, "-delete-stages")
        [pc] = mine(name)
        assert pc.stages == ()
        assert reader.orphans() == [], "after the stages were deleted the product reads orphans"


def test_stages_list_and_plan(fixture_tool, core, tmp_path):
    """A proposed change with two marks lists and plans as four stages in order: the branch
    point, each mark at its own write stamp verbatim, and the head one microsecond after the
    branch's latest stamp. The branch point is refused scope.empty and its step not computed;
    the marks and the head compile to three ids, the step between the marks is the link added
    with n1 and n3 changed, and the step to the head is unchanged. The mark's snapshot is the
    read of the branch at its at, observed_at aside, and compiles to the same id (SC-002).
    Then the first mark is edited three times: a description edit leaves its at, and a twin
    built from it unmoved; a relabel leaves the old reference unknown and the new one at the
    relabel's write; an as_of of its first at gives that at back, given."""
    with fixture_tool.throwaway("list") as name:
        id = fixture_tool.propose(name)
        # Each mark written last, after the writes it seals and after their generate.
        _, seeded_at = fixture_tool.mark(name, "seeded", description="seeded")
        before = checksums(name)
        fixture_tool.change(name, "-add-link")
        await_moved(name, before, "n1", "n3")
        await_joined(name)
        _, third_at = fixture_tool.mark(name, "third-link", description="third link")
        latest = artifacts_ready_at(name)
        branched_from, _ = branch_origin(name)

        want = [
            (BP, "main", branched_from, stages.AT_BRANCH_POINT),
            ("seeded", name, seeded_at, stages.AT_WRITTEN),
            ("third-link", name, third_at, stages.AT_WRITTEN),
            (HEAD, name, "", stages.AT_HEAD),
        ]
        answer = adapter.stage_list(branch=name, scope=SCOPE, env=adapter.Env())
        assert answer.doc.status == STATUS_OK and list(answer.doc.findings) == [], list(answer.doc.findings)
        rows = answer.doc.blocks["stages"]["rows"]
        for r in rows:
            assert (r["proposed_change"]["id"], r["ref"].split("/")[0], r["twin"]) == (id, name, False), r
        got = [(r["label"], r["branch"], r.get("at", ""), r["at_source"]) for r in rows]
        assert len(got) == 4
        # The head's at is computed: the instant after the latest checksum stamp.
        assert stages.parse_at(got[3][2]) == nanos(latest) + 1000, (
            f"the head's at is {got[3][2]}; want one microsecond after the latest checksum stamp {latest.isoformat()}")
        want[3] = (*want[3][:2], got[3][2], want[3][3])
        assert got == want

        plan = plan_of(name, core, tmp_path / "plan")
        assert plan.outcomes == [
            (BP, PLAN_REFUSED, SCOPE_EMPTY), ("seeded", PLAN_COMPILED, ""), ("third-link", PLAN_COMPILED, ""),
            (HEAD, PLAN_COMPILED, ""),
        ], plan.found
        assert plan.change.proposed_change.id == id and plan.change.proposed_change.draft
        for p, (_, branch, at, source) in zip(plan.stages[1:], want[1:], strict=True):
            r = p.resolved
            assert (r.branch, r.at, r.at_source) == (branch, at, source), f"{p.stage.ref} planned at {r}"
            assert p.found == [], f"{p.stage.ref} compiled with findings {p.found}"
        ids = [p.bundle_id for p in plan.stages[1:]]
        assert len(set(ids)) == 3, f"the three compiled stages have ids {ids}; want three distinct"

        assert len(plan.steps) == 3
        assert plan.steps[0] is None, "the step from the refused branch point was computed"
        s = plan.steps[1]
        assert s["computed"] and not s["unchanged"], s
        changed = [n["node"] for n in s["nodes"]["changed"]]
        for n in s["nodes"]["changed"]:
            assert "bootstrap" in n["reasons"], f"{n['node']} changed for {n['reasons']}; want its bootstrap among them"
        for a in s["artifacts"]["changed"]:
            assert a["from"] != a["to"] and a["from"] == before[a["node"]], a
        assert len(s["links"]["added"]) == 1 and s["links"]["removed"] == []
        assert s["nodes"]["added"] == [] and s["nodes"]["removed"] == []
        assert changed == ["n1", "n3"] and [a["node"] for a in s["artifacts"]["changed"]] == ["n1", "n3"]
        assert plan.steps[2]["computed"] and plan.steps[2]["unchanged"], plan.steps[2]

        # SC-002: the mark's reference reads the snapshot --branch reads at its at, and
        # compiles to the id the plan printed.
        seeded = plan.stages[1]
        by_at = tmp_path / "by-at.json"
        answer = adapter.read(name, at=seeded_at, scope=SCOPE, out=str(by_at), env=adapter.Env())
        assert answer.doc.status == STATUS_OK, list(answer.doc.findings)
        taken = json.loads(by_at.read_text())
        assert taken["ctm"]["envelope"]["at"] == seeded.snapshot["ctm"]["envelope"]["at"] == seeded_at
        assert taken["snapshot_id"] == seeded.snapshot["snapshot_id"], (
            f"the snapshot {seeded.stage.ref} plans from differs from --branch {name} --at {seeded_at}'s")
        code, doc = core.compile(by_at, tmp_path / "by-at.bundle")
        assert code == 0 and doc["bundle_id"] == seeded.bundle_id, doc
        print(f"{seeded.stage.ref}: at {seeded_at} (written), snapshot {taken['snapshot_id']}, "
              f"bundle {doc['bundle_id']}")

        # Editing the mark, the proposed change found again after each edit.
        first = seeded.resolved
        record = stages.RecordView(stages.RecordChange(id, name), first.label, first.branch, first.at, first.at_source)

        def edit(field: str, value: str) -> stages.Change:
            fixture_tool.update_stage(name, current, field, value)
            return find(name)

        def mark_of(what: str, ch: stages.Change, label: str) -> stages.Stage:
            for st in ch.stages:
                if st.mark is not None and st.id == first.id:
                    assert st.label == label, f"after {what} the mark {first.id} is labelled {st.label!r}"
                    print(f"after {what}: {st.ref} at {st.at} ({st.at_source}), label written at "
                          f"{st.mark.label_written_at}")
                    return st
            raise AssertionError(f"after {what} the mark {first.id} is not among {name}'s stages")

        current = "seeded"
        ch = edit("description", "seeded, described again")
        st = mark_of("a description edit", ch, "seeded")
        assert (st.at, st.at_source, st.resolved.description) == (first.at, stages.AT_WRITTEN,
                                                                    "seeded, described again")
        assert list(stages.twin_moved(ch, record)) == [], "after a description edit the record's stage reads as moved"

        ch = edit("label", "relabelled")
        current = "relabelled"
        relabelled = mark_of("a relabel", ch, "relabelled")
        assert stages.later_than(relabelled.at, first.at) and relabelled.at_source == stages.AT_WRITTEN
        _, found = resolve(first.ref)
        refused("the old reference after a relabel", found, stages.RULE_STAGE_UNKNOWN, str(first.ref))
        [moved] = stages.twin_moved(ch, record)
        assert (moved.rule, moved.severity) == (stages.RULE_STAGE_TWIN_MOVED, "warning")
        assert f"{first.ref} no longer exists" in moved.message, moved.message

        ch = edit("as_of", first.at)
        st = mark_of("an as_of edit", ch, "relabelled")
        assert (st.at, st.at_source) == (first.at, stages.AT_GIVEN)


def test_stage_refusals(fixture_tool, core, tmp_path):
    """The refusals tier 2 can make, on one proposed change in the order its story makes
    them. An intent change with no regenerate makes the mark after it stale on every device it
    moved, and a generate then a fresh mark plans; an edit the template does not render (the
    serial number) leaves the mark stale through a generate that moves no checksum, and the
    proposed change's checks clear it (D-046). A rebase moves the branch point past every
    mark, each refused naming the rebase while the derived stages are still planned. A mark
    labelled head is refused as reserved, a given as_of in the future as unresolved; once the
    proposed change is closed its branch names no stage, nor does a branch that does not
    exist."""
    devices = ("n1", "n2", "n3")
    with fixture_tool.throwaway("refusals") as name:
        id = fixture_tool.propose(name)
        reader = stage_reader()

        def fresh(label: str) -> stages.Resolved:
            res, found = resolve(stages.Ref(name, label))
            assert list(found) == [] and res is not None, f"{name}/{label}: {list(found)}; want it resolved"
            return res

        def stale(label: str) -> None:
            _, found = resolve(stages.Ref(name, label))
            for m in refused(f"{name}/{label}", found, STALE, *devices):
                assert stages.REMEDY in m, f"{name}/{label}: {m!r} names not both remedies"

        # An intent change the artifact renders, with no generate: stale on each device.
        fixture_tool.change(name, "-set-description", "stale-description")
        fixture_tool.mark(name, "description-stale", description="the description, not rendered")
        stale("description-stale")
        before = checksums(name)
        fixture_tool.change(name, "-generate")
        await_moved(name, before, *devices)
        fixture_tool.mark(name, "description-fresh", description="the description, rendered")
        fresh("description-fresh")

        # The serial number, which the template does not print: a generate rewrites nothing,
        # and only the proposed change's checks clear it.
        fixture_tool.change(name, "-set-serial", "n1,n2,n3=stale-serial")
        fixture_tool.mark(name, "serial-stale")
        stale("serial-stale")
        before = checksums(name)
        fixture_tool.change(name, "-generate")
        assert checksums(name) == before, "a generate after the serial number's edit moved the checksums"
        fixture_tool.mark(name, "serial-generated")
        stale("serial-generated")
        started = time.monotonic()
        out = fixture_tool.run("-branch", name, "-run-check")
        completed = re.search(r"validator completed at (\S+), after", out).group(1)
        print(f"the run-check's artifact validator completed at {completed}, {time.monotonic() - started:.0f}s after "
              "the call")
        assert checksums(name) == before, "the run-check moved the checksums; the bytes are identical"
        fixture_tool.mark(name, "serial-checked")
        checked = fresh("serial-checked")
        assert reader.validations(id, checked.at) == completed

        plan = plan_of(name, core, tmp_path / "before")
        assert plan.outcomes == [
            (BP, PLAN_REFUSED, SCOPE_EMPTY),
            ("description-stale", PLAN_REFUSED, STALE),
            ("description-fresh", PLAN_COMPILED, ""),
            ("serial-stale", PLAN_REFUSED, STALE),
            ("serial-generated", PLAN_REFUSED, STALE),
            ("serial-checked", PLAN_COMPILED, ""),
            (HEAD, PLAN_COMPILED, ""),
        ]
        for i, step in enumerate(plan.steps):
            both = plan.stages[i].status == plan.stages[i + 1].status == PLAN_COMPILED
            assert (step is not None) == both, f"step {i}: computed {step is not None}; want a step only between two"

        # A rebase moves branched_from to its own moment and leaves created_at: every mark
        # falls before the branch point, and the refusal says a rebase did it.
        marks = ["description-stale", "description-fresh", "serial-stale", "serial-generated", "serial-checked"]
        _, created_before = branch_origin(name)
        print(fixture_tool.run("-branch", name, "-rebase").strip())
        branched_from, created_at = branch_origin(name)
        assert created_at == created_before, f"the rebase moved created_at {created_before} → {created_at}"
        plan = plan_of(name, core, tmp_path / "rebased")
        assert plan.outcomes == ([(BP, PLAN_REFUSED, SCOPE_EMPTY)]
                                 + [(m, PLAN_REFUSED, stages.RULE_STAGE_AT_BEFORE_BRANCH_POINT) for m in marks]
                                 + [(HEAD, PLAN_COMPILED, "")])
        for p in plan.stages:
            if p.rule != stages.RULE_STAGE_AT_BEFORE_BRANCH_POINT:
                continue
            for m in refused(str(p.stage.ref), p.found, stages.RULE_STAGE_AT_BEFORE_BRANCH_POINT, str(p.stage.ref)):
                assert f"a rebase at {branched_from}" in m and f"(the branch was created at {created_at})" in m, m

        # A mark labelled like a derived stage: Infrahub takes it, Fylgja refuses it.
        fixture_tool.mark(name, HEAD)
        _, found = resolve(stages.Ref(name, HEAD))
        refused(f"{name}/head", found, stages.RULE_STAGE_LABEL_RESERVED, f"{name}/{HEAD}")

        # A given as_of later than the clock seals nothing yet.
        future = (datetime.now(UTC) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        fixture_tool.mark(name, "future", at=future)
        _, found = resolve(stages.Ref(name, "future"))
        for m in refused(f"{name}/future", found, stages.RULE_STAGE_AT_UNRESOLVED, f"{name}/future"):
            assert "later than the current time" in m, m

        # A label the open proposed change lacks names no stage of it; the refusal names its
        # stages in order: the branch point, the marks by their at, and the head.
        _, found = resolve(stages.Ref(name, "nosuch"))
        order = [BP, *marks, "future", HEAD]
        for m in refused(f"{name}/nosuch", found, stages.RULE_STAGE_UNKNOWN, f"{name}/nosuch"):
            assert m == (f'proposed change "{name}" ({id}) on branch {name} has no stage "nosuch"; its stages are: '
                         + ", ".join(order))

        # Closed, the proposed change keeps its stages but its branch names none.
        fixture_tool.run("-branch", name, "-close")
        _, found = resolve(stages.Ref(name, "serial-checked"))
        for m in refused("after the close", found, stages.RULE_STAGE_UNKNOWN, name):
            assert f"no open proposed change has source branch {name}" in m, m
        plan = plan_of(name, core, tmp_path / "closed")
        assert plan.change is None and plan.stages == []
        refused("the plan after the close", plan.found, stages.RULE_STAGE_UNKNOWN, name)

    absent = f"{TEST_PREFIX}st-absent-{time.time_ns()}"
    _, found = resolve(stages.Ref(absent, "seeded"))
    refused("an unknown branch", found, stages.RULE_STAGE_UNKNOWN, absent)


def test_stages_see_every_write_of_a_device(fixture_tool):
    """SC-009 of 017 against the real Infrahub: after a fresh mark, each write on what a
    tagged device owns or reaches makes the next mark stale on every tagged device that
    reaches it, and on no other. cs1, an untagged device created on the platform the three
    stand on, reaches all three by the platform's update event; a write of cs1's own makes no
    mark stale. The platform's and the manufacturer's descriptions reach the three; the
    n1 — n2 cable's status moves its stamp and n1's and n2's intent; the same cable re-ended
    to n1's port alone reaches n1 and n2 by its events; and a virtual interface's description,
    its creation cleared first, reaches n1 alone. The proposed change's checks clear each write
    before the next (D-046)."""
    with fixture_tool.throwaway("every-write") as name:
        fixture_tool.propose(name)

        def resolved(label: str):
            return resolve(stages.Ref(name, label))[1]

        def fresh(label: str) -> None:
            found = resolved(label)
            assert list(found) == [], f"{name}/{label}: {list(found)}; want it fresh"

        def stale(label: str, *devices: str) -> list[str]:
            messages = refused(f"{name}/{label}", resolved(label), STALE, *devices)
            for m in messages:
                assert stages.REMEDY in m, f"{name}/{label}: {m!r} names not both remedies"
            return messages

        def checked(label: str, what: str) -> None:
            started = time.monotonic()
            out = fixture_tool.run("-branch", name, "-run-check")
            print(f"after {what}, {out.strip()} ({time.monotonic() - started:.0f}s)")
            fixture_tool.mark(name, label + "-checked", description=what + ", checked")
            fresh(label + "-checked")

        def mark(label: str, what: str, last: bool, *devices: str) -> list[str]:
            fixture_tool.mark(name, label, description=what)
            messages = stale(label, *devices)
            if not last:
                checked(label, what)
            return messages

        fixture_tool.mark(name, "seeded", description="seeded")
        fresh("seeded")

        # cs1 is outside the scope, and created on the platform every tagged device stands on.
        # The events land a few seconds after the write, so the mark is judged again until
        # every finding names one.
        fixture_tool.run("-branch", name, "-add-device", "cs1:mgmt0,ethernet-1/1", "-device-platform",
                         "Nokia/SR Linux", "-device-management", "mgmt0")
        fixture_tool.mark(name, "untagged-created", description="cs1 created on the platform")

        def names_events(found) -> bool:
            return bool(list(found)) and all(EVENT in f.message for f in found)

        found = resolved("untagged-created")
        deadline = time.monotonic() + 30
        while not names_events(found) and time.monotonic() < deadline:
            time.sleep(1)
            found = resolved("untagged-created")
        for m in refused(f"{name}/untagged-created", found, STALE, "n1", "n2", "n3"):
            print(f"{name}/untagged-created: {m}")
            assert stages.REMEDY in m and EVENT + "infrahub.node.updated of a DcimPlatform; " in m, m
        checked("untagged-created", "cs1 created on the platform")

        # cs1's own write: its node is no tagged device's, nor in any one's ids.
        fixture_tool.run("-branch", name, "-describe", "device:cs1=untagged-description")
        fixture_tool.mark(name, "untagged", description="cs1 described")
        fresh("untagged")

        # The seed's platform and its manufacturer, which every device stands on.
        fixture_tool.run("-branch", name, "-describe", "platform:SR Linux=described")
        mark("platform", "the platform described", False, "n1", "n2", "n3")
        fixture_tool.run("-branch", name, "-describe", "manufacturer:Nokia=described")
        mark("manufacturer", "the manufacturer described", False, "n1", "n2", "n3")

        # The n1 — n2 cable's status, a write of the cable alone: n1's and n2's intent move
        # to its stamp, n3's does not.
        n1n2 = "n1:ethernet-1/1|n2:ethernet-1/1"
        before = stamper().stamps(name, "", SCOPE)
        out = fixture_tool.run("-branch", name, "-set-cable-status", f"{n1n2}=planned")
        cable_at = re.search(r"stamped at (\S+)$", out.strip()).group(1)
        after = stamper().stamps(name, "", SCOPE)
        for d in ("n1", "n2"):
            assert after.devices[d].intent == cable_at, (
                f"after the cable's status {d}'s intent stamp is {after.devices[d].intent} (before it "
                f"{before.devices[d].intent}); want the cable's, {cable_at}")
        assert after.devices["n3"].intent == before.devices["n3"].intent, "the cable's status moved n3's intent stamp"
        mark("cable-status", "the n1 — n2 cable's status set", False, "n1", "n2")

        # The re-ending moves no stamp: the cable's events, and its former port's, land in the
        # log a few seconds after the write, and the head passes the write by them alone.
        def head_of() -> str:
            return find(name).first(HEAD).at

        sent = nanos(datetime.now(UTC))
        fixture_tool.run("-branch", name, "-re-end-cable", "n1:ethernet-1/1=n1:ethernet-1/1")
        deadline = time.monotonic() + 30
        while True:
            at = stages.parse_at(head_of())
            if at is not None and at > sent:
                break
            assert time.monotonic() < deadline, "the head has not passed the re-ending 30 s after it was sent"
            time.sleep(0.25)
        messages = mark("cable", "the cable re-ended", False, "n1", "n2")
        # n2 reaches the cable no more: its former port's id, which the events name, is how.
        assert len(messages) == 2 and EVENT + "infrahub.node." in messages[1], messages

        fixture_tool.run("-branch", name, "-add-virtual-interface", "n1:lo0")
        checked("virtual-created", "a virtual interface added to n1")
        fixture_tool.run("-branch", name, "-describe", "virtual:n1:lo0=described")
        mark("virtual", "n1's virtual interface described", True, "n1")


def test_stages_see_a_removal(fixture_tool, core, tmp_path):
    """D-048 against the real Infrahub: the cable n1:ethernet-1/1 — n2:ethernet-1/1 deleted
    as the branch's latest write stamps its two end ports, so n1's and n2's intent stamps and
    the branch's latest move to it and n3's does not; its events land after its stamp and move
    the head past it. A stage marked after the delete, and the head, are refused stale for n1
    and n2, naming the events; the mark before it is fresh. A regenerate then clears the head,
    which reads two links, and leaves the mark after the delete stale."""
    with fixture_tool.throwaway("removal") as name:
        fixture_tool.propose(name)

        def head_of() -> str:
            return find(name).first(HEAD).at

        def stamps():
            return stamper().stamps(name, "", SCOPE)

        _, seeded_at = fixture_tool.mark(name, "seeded", description="before the delete")
        before, head_before = stamps(), head_of()
        sent = nanos(datetime.now(UTC))
        out = fixture_tool.run("-branch", name, "-delete-link", "n1:ethernet-1/1")
        returned = re.search(r"returned at (\S+)$", out.strip()).group(1)
        print(f"seeded marked at {seeded_at}; the delete returned at {returned}")
        after = stamps()
        assert stages.later_than(after.latest, before.latest), (
            f"the delete left the branch's latest stamp at {after.latest} (before it {before.latest})")
        for d in ("n1", "n2"):
            assert after.devices[d].intent == after.latest, (
                f"after the delete {d}'s intent stamp is {after.devices[d].intent}; want the branch's latest "
                f"{after.latest}")
        assert after.devices["n3"].intent == before.devices["n3"].intent, "the delete moved n3's intent stamp"

        # The delete's events land after its stamp: wait for the head to pass the stamps' head
        # by them and settle, two reads a second apart agreeing.
        stamps_at = stages.parse_at(stages.head_at(after.latest))
        head_after, deadline, passed = head_of(), time.monotonic() + 30, False
        while True:
            at = stages.parse_at(head_after)
            if at is not None and at > sent and at > stamps_at:
                if not passed:
                    passed = True
                    print(f"the head passed the delete at {head_after}")
                time.sleep(1)
                again = head_of()
                if again == head_after:
                    break
                head_after = again
            else:
                assert time.monotonic() < deadline, (
                    f"the head is {head_after} 30 s after the delete; want it past the stamps' head by its events")
                time.sleep(0.25)
                head_after = head_of()
        print(f"the head moved from {head_before} past the delete to {head_after}")
        _, removed_at = fixture_tool.mark(name, "removed", description="after the delete")
        print(f"removed marked at {removed_at}")

        plan = plan_of(name, core, tmp_path / "deleted")
        assert plan.outcomes == [
            (BP, PLAN_REFUSED, SCOPE_EMPTY), ("seeded", PLAN_COMPILED, ""), ("removed", PLAN_REFUSED, STALE),
            (HEAD, PLAN_REFUSED, STALE),
        ], plan.found
        assert plan.stages[1].counts.links == 3
        for p in plan.stages[2:]:
            for m in refused(p.stage.label, p.found, STALE, "n1", "n2"):
                assert EVENT + "infrahub.node." in m, m
                print(m)

        before_sums = checksums(name)
        fixture_tool.change(name, "-generate")
        await_moved(name, before_sums, "n1", "n2")
        regenerated = stamps()
        assert head_of() == stages.head_at(regenerated.latest), "after the regenerate the head is not the stamps'"
        plan = plan_of(name, core, tmp_path / "regenerated")
        assert plan.outcomes == [
            (BP, PLAN_REFUSED, SCOPE_EMPTY), ("seeded", PLAN_COMPILED, ""), ("removed", PLAN_REFUSED, STALE),
            (HEAD, PLAN_COMPILED, ""),
        ], plan.found
        refused("removed after the regenerate", plan.stages[2].found, STALE, "n1", "n2")
        assert plan.stages[3].counts.links == 2

