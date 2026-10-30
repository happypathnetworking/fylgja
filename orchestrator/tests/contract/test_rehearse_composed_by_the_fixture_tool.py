"""The rehearsal as the fixture tool composes it (T028; R-15, FR-028; US1 scenarios 2 and 8):
`internal/server/rehearse_contract_test.go`'s `TestRehearseComposedByTheFixtureTool` carried
over to the flows, its flags as an operator and tier 3 run them, each printing its line exactly.

`-propose` opens a draft, which `twin-rehearse` rehearses no further than the host check of the
test's core, which holds no node login: refused before any run, its report posted as the
proposed change's one thread. The creation's user checks concluded, `-ready` makes it ready,
`-add-interface` writes one uncabled physical port, active, which `-generate` renders on n1
alone; the ready change's plan (`stage-plan`) reads the head with the port and the core's
compile omits it `omit.interface.unmappable` beside `artifact.interface.unrepresented`, the
package's rules being the core's (research §5.11, §5.20), where the Go test asked `intent.read`
and `twin.compile`. Then the host held: a second core of the test's own whose state root holds
a twin directory, with the logins' names set (the host check reads only that they are), so the
rehearsal of the ready change is refused `host.twin.present` alone, which a check asks again on
and the flow does not post. `-run-checks user` runs only where main holds no check definition,
since a user run of `fylgja-twin` would rehearse the ready change on a twin. `-delete` takes the
proposed change and its thread with the branch.

No twin boots: the first core's host check cannot pass without the logins, the second's
without its twin directory gone, and neither core holds INFRAHUB_*.

    set -a; . local/.env; set +a; orchestrator/.venv/bin/pytest -q orchestrator -m contract \
        -k test_rehearse_composed_by_the_fixture_tool -s
"""

import json
import time

import pytest

from fylgja_orchestrator.adapters.infrahub.stages import LABEL_BRANCH_POINT, LABEL_HEAD
from fylgja_orchestrator.documents.deadline import ROLE_NOT_REACHED, ROLE_REFUSED
from fylgja_orchestrator.documents.findings import REJECTION, STATUS_REJECTED, WARNING

from .conftest import (
    LOGIN_NAMES,
    SCOPE,
    await_user_checks,
    branch_exists,
    check_definitions,
    checksums,
    graphql,
    proposed_changes_of,
    serving,
    threads_of,
    use_core,
    user_validators,
)

pytestmark = pytest.mark.contract

PORT = "ethernet-1/99"
OBJECT = f"n1:{PORT}"
UNREPRESENTED = "artifact.interface.unrepresented"
UNMAPPABLE = "omit.interface.unmappable"
LOGIN_UNSET = "host.probe.login_unset"
TWIN_PRESENT = "host.twin.present"


def open_change(branch: str) -> dict:
    """The branch's one proposed change on main: its id, state and draft."""
    data = graphql("main", "query { CoreProposedChange(source_branch__value: %s) { edges { node { id "
                   "state { value } is_draft { value } } } } }" % json.dumps(branch))
    [e] = data["CoreProposedChange"]["edges"]
    return {"id": e["node"]["id"], "state": e["node"]["state"]["value"], "draft": e["node"]["is_draft"]["value"]}


def rejections(doc) -> list[tuple[str, str]]:
    return [(f.rule, f.object) for f in doc.findings if f.severity == REJECTION]


def test_rehearse_composed_by_the_fixture_tool(platform, fixture_tool, own_core, tmp_path, monkeypatch):
    from fylgja_orchestrator.flows.stage_plan import stage_plan
    from fylgja_orchestrator.flows.twin_rehearse import twin_rehearse

    with fixture_tool.throwaway("composed") as name:
        out = fixture_tool.run("-branch", name, "-propose")
        pc = open_change(name)
        assert pc["draft"] and pc["state"] == "open", pc
        id = pc["id"]
        assert out.startswith(f"proposed change {id} opened on {name}, draft; "), out

        # The draft's refusal: planned, its head the one compiled stage (the baseline, with no
        # step to rehearse), and refused at the host check for the logins the core lacks,
        # before any run, so the head is not reached; the report posted.
        flows = use_core(monkeypatch, own_core, tmp_path / "orchestrator")
        doc, took = flows.run(twin_rehearse, branch=name, scope=SCOPE, markdown=True)
        text = flows.text()
        assert doc.status == STATUS_REJECTED and doc.exit_code == 1, (doc.status, text)
        assert {rule for rule, _ in rejections(doc)} == {"scope.empty", LOGIN_UNSET}, rejections(doc)
        block = doc.blocks["rehearsal"]
        assert block["proposed_change"]["id"] == id and block["proposed_change"]["draft"], block["proposed_change"]
        assert (block.get("run"), block.get("destroy"), block.get("baseline")) == (None, None, None), block
        assert [(s["label"], s["role"]) for s in block["stages"]] == [
            (LABEL_BRANCH_POINT, ROLE_REFUSED), (LABEL_HEAD, ROLE_NOT_REACHED)], block["stages"]
        assert "rehearsal.steps.none" in {f.rule for f in doc.findings if f.severity == WARNING}, doc.findings
        assert [op for op, _ in own_core.operations()] == ["twin.compile", "twin.show", "twin.create"], (
            own_core.operations())
        assert own_core.operations()[-1] == ("twin.create", "rejected"), own_core.operations()
        [md] = flows.markdown
        assert threads_of(id) == [[md + "\n"]], "the draft's report is not the proposed change's one thread"
        print(f"the draft's rehearsal refused in {took:.1f}s, its report posted")

        # The creation's fylgja-twin may not have read the proposed change yet; marked ready
        # before it does, it would rehearse it on a twin, which tier 2 never boots.
        await_user_checks(name, id)
        ready = fixture_tool.run("-branch", name, "-ready")
        assert ready == f"proposed change {id} on {name} marked ready for review\n", ready
        pc = open_change(name)
        assert not pc["draft"] and pc["state"] == "open", pc

        before = checksums(name)
        assert fixture_tool.run("-branch", name, "-add-interface", OBJECT) == (
            f"interface {PORT} added on n1 on {name}: physical, active, no cable; -generate renders it\n")
        got = json.dumps(graphql(name, 'query { InterfacePhysical(device__name__value: "n1", name__value: %s) { edges '
                                       '{ node { status { value } role { value } connector { node { id } } } } } }'
                                 % json.dumps(PORT)), separators=(",", ":"))
        assert ('"status":{"value":"active"}' in got and '"role":{"value":null}' in got
                and '"connector":{"node":null}' in got and got.count('"status"') == 1), (
            f"n1:{PORT} reads {got}; want one physical port, active, not management, with no cable")
        assert checksums(name)["n1"] == before["n1"], "-add-interface rendered something"

        assert fixture_tool.run("-branch", name, "-generate") == f"artifacts rendered and Ready on {name}\n"
        deadline = time.monotonic() + 90
        after = checksums(name)
        while after.get("n1") == before["n1"] and time.monotonic() < deadline:
            time.sleep(1)
            after = checksums(name)
        assert after.get("n1") and after["n1"] != before["n1"], f"n1's checksum did not move: {before} → {after}"
        assert {d: after[d] for d in ("n2", "n3")} == {d: before[d] for d in ("n2", "n3")}, (before, after)

        # The ready change's plan: the head read with the port, which the core's compile
        # omits and warns of, and compiled.
        doc, _ = flows.run(stage_plan, branch=name, scope=SCOPE)
        plan = doc.blocks["plan"]
        assert not plan["proposed_change"]["draft"], plan["proposed_change"]
        bp, head = plan["stages"]
        assert [f["rule"] for f in bp["findings"]] == ["scope.empty"], bp
        assert head["label"] == LABEL_HEAD and head.get("bundle_id"), head
        warned = [f for f in head["findings"] if f["rule"] == UNREPRESENTED and f["object"] == OBJECT]
        assert [f["severity"] for f in warned] == [WARNING] and UNMAPPABLE in warned[0]["message"], head["findings"]
        assert any(f["rule"] == UNMAPPABLE and f["object"] == OBJECT for f in head["findings"]), head["findings"]

        # The host held: a twin directory under a second core's state root, the logins named.
        held_root = tmp_path / "held"
        with serving(held_root / "core", dict.fromkeys(LOGIN_NAMES, "unused")) as held:
            (held.state / "twin").mkdir(parents=True)
            flows = use_core(monkeypatch, held, held_root / "orchestrator")
            doc, took = flows.run(twin_rehearse, branch=name, scope=SCOPE, markdown=True)
            text = flows.text()
            print(f"the held host's rehearsal refused in {took:.1f}s")
            passed = [(r, o) for r, o in rejections(doc) if r == "scope.empty"]
            assert doc.status == STATUS_REJECTED, (doc.status, text)
            assert [r for r, _ in rejections(doc) if (r, _) not in passed] == [TWIN_PRESENT], rejections(doc)
            assert held.operations()[-1] == ("twin.create", "rejected"), held.operations()
            assert {op for op, _ in held.operations()} == {"twin.compile", "twin.show", "twin.create"}
            assert list((held.state / "twin").iterdir()) == [], "the refusal wrote into the twin directory"
            assert not (held_root / "orchestrator" / "twin.json").exists()
        assert threads_of(id) == [[md + "\n"]], "the held host's refusal was posted"

        # With a check registered on main, a user run would have fylgja-twin rehearse this
        # ready proposed change on a twin, which tier 2 never boots.
        defs = check_definitions()
        if defs:
            print(f"main holds the check definitions {sorted(d['name'] for d in defs)}: -run-checks user is not run")
        else:
            started = time.monotonic()
            assert fixture_tool.run("-branch", name, "-run-checks", "user") == (
                f"no user check ran on proposed change {id} on {name}: the branch sees no check definition of a "
                "registered repository\n")
            assert time.monotonic() - started <= 30, "-run-checks user waited with no check to wait for"
            assert user_validators(id) == []

        assert fixture_tool.delete(name) == f"deleted 0 stages, 1 proposed change, branch {name}\n"
        assert not branch_exists(name) and proposed_changes_of(name) == {}
        assert threads_of(id) == [], "the thread outlived its proposed change"
