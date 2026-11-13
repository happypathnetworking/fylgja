"""The bracket of a real read on the development NetBox (D-095; design/verified-facts.md, "NetBox 4.7.5 with
netbox-branching 1.2.3"): an edit made between two renders of a read refuses it, and the read made again gives a
blueprint holding the edit; the branch deleted, or synced, between two renders refuses the read by `read.moved` alone;
a journal entry written during a read of `main` refuses nothing; the same state read twice gives one id, on `main` and
on a branch holding the third cable; and the reader, over the whole session, sent no request but its `GET`s and its
renders. The edit, the delete, the sync and the entry are made in flight by `reader_over`, as the first render's answer
passes on its way to the reader, since that is the fault the bracket exists for and no write between two calls of the
test could land inside one read. Every write is the superuser's, through `box`: under the header of the test's own
branch, the branch itself deleted or synced, the one tag of the tier's naming the sync takes from `main`, made there and
deleted in a `finally`, and the journal entry on that branch object, deleted the same way. No assertion message prints
the address or a token."""

from __future__ import annotations

import json
import re
import secrets
from typing import Any

import httpx
import pytest
from fylgja_core import blueprint

from fylgja_netbox import NetBox, ReaderDocument, Result, read
from fylgja_netbox.rows import Branch

from .conftest import BRANCHES, PREFIX, SENT, Writes, reader_over
from .test_bracket_contract import waited

SCOPE = "tag:fylgja"
RENDER = re.compile(r"/api/dcim/devices/\d+/render-config/")
"""The path of a render, the one request of the reader's that is no `GET`."""


@pytest.fixture(scope="module")
def unprobed(document: ReaderDocument) -> ReaderDocument:
    """The seeded fixture network's reader document, naming no configuration context of probes."""
    return ReaderDocument(document.platforms, None)


def errors(result: Result) -> list[tuple[str, str | None]]:
    return [(finding.rule, finding.object) for finding in result.findings if finding.severity == "error"]


def taken(result: Result) -> dict[str, Any]:
    """The blueprint a read answered, which must have no error."""
    assert errors(result) == []
    assert result.blueprint is not None
    return result.blueprint


def but_observed(doc: dict[str, Any]) -> dict[str, Any]:
    held: dict[str, Any] = json.loads(json.dumps(doc))
    del held["source"]["observed_at"]
    return held


class FirstRender:
    """An `alter` for `reader_over` that calls `then` once, as the first render's answer passes, and changes no
    answer."""

    def __init__(self, then: Any) -> None:
        self.then = then
        self.done = False

    def __call__(self, request: httpx.Request, response: httpx.Response) -> httpx.Response:
        if not self.done and RENDER.fullmatch(request.url.path):
            self.done = True
            self.then()
        return response


def test_an_edit_between_two_renders_refuses_the_read(
    conn: NetBox, box: Writes, branch: Branch, unprobed: ReaderDocument
) -> None:
    """`n3 ethernet-1/10` disabled under the branch's header as `n1`'s render, the read's first, passes: `n3`'s render
    after it holds the edit and `n1`'s does not, a network that never was."""
    n3 = box.one("dcim/devices/", branch=branch.schema_id, name="n3")
    assert n3 is not None
    port = box.one("dcim/interfaces/", branch=branch.schema_id, device_id=n3["id"], name="ethernet-1/10")
    assert port is not None and port["enabled"] is True

    edit = FirstRender(lambda: box.patch(f"dcim/interfaces/{port['id']}/", {"enabled": False}, branch=branch.schema_id))
    with reader_over(edit) as own:
        result = read(own, branch=branch.name, scope=SCOPE, document=unprobed)
    assert edit.done
    assert result.blueprint is None
    assert errors(result) == [("read.moved", branch.name)]
    assert "dcim.interface" in result.findings[0].message and "read again" in result.findings[0].message

    again = taken(read(conn, branch=branch.name, scope=SCOPE, document=unprobed))
    held = {(d["name"], i["name"]): i["enabled"] for d in again["network"]["devices"] for i in d["interfaces"]}
    assert held[("n3", "ethernet-1/10")] is False
    assert "admin-state disable" in next(d for d in again["network"]["devices"] if d["name"] == "n3")["config"]


def test_a_branch_deleted_under_a_read_refuses_it(box: Writes, branch: Branch, unprobed: ReaderDocument) -> None:
    """The test's branch deleted as `n1`'s render, the read's first, passes: NetBox answers the renders after it 400
    under the header of a branch that is gone (design/verified-facts.md, "A render under the header of a branch that is
    gone"), which the close weighs, and the close lists no branch of its id. The read is refused by `read.moved` alone,
    with no document; the fixture then finds no branch to delete."""
    gone = FirstRender(lambda: box.delete(f"{BRANCHES}{branch.id}/"))
    with reader_over(gone) as own:
        result = read(own, branch=branch.name, scope=SCOPE, document=unprobed)
    assert gone.done
    assert result.blueprint is None
    assert [(finding.rule, finding.object) for finding in result.findings] == [("read.moved", branch.name)]
    assert f"no branch {branch.name}" in result.findings[0].message


def test_a_branch_synced_under_a_read_refuses_it(box: Writes, branch: Branch, unprobed: ReaderDocument) -> None:
    """The test's branch synced as `n1`'s render passes, and waited for until it reads `ready` with its `last_sync`
    moved, so that the renders after it are of the synced branch: what it syncs is one tag of the tier's naming, made
    on `main` and deleted there in a `finally` (ruling C2). A sync adds no row to either changelog
    (design/verified-facts.md, "A sync"): the close sees it by the branch's `last_sync`, and the read is refused by
    `read.moved` alone, with no document."""
    name = PREFIX + secrets.token_hex(4)
    made = box.post("extras/tags/", {"name": name, "slug": name})

    def synced() -> None:
        box.post(f"{BRANCHES}{branch.id}/sync/", {"commit": True})
        waited(box, branch, lambda row: row["status"]["value"] == "ready" and row["last_sync"] != branch.last_sync)

    try:
        sync = FirstRender(synced)
        with reader_over(sync) as own:
            result = read(own, branch=branch.name, scope=SCOPE, document=unprobed)
        assert sync.done
        assert result.blueprint is None
        assert [(finding.rule, finding.object) for finding in result.findings] == [("read.moved", branch.name)]
        assert "last_sync" in result.findings[0].message
    finally:
        box.delete(f"extras/tags/{made['id']}/")


def test_a_journal_entry_written_during_a_read_of_main_refuses_nothing(
    conn: NetBox, box: Writes, branch: Branch, unprobed: ReaderDocument
) -> None:
    """A journal entry on the test's branch object, written with no header as the first render's answer passes, adds
    a row of `extras.journalentry` to `main`'s changelog, a kind no read reads (bracket.UNREAD): the read of `main`
    gives a blueprint, read to that row's id."""
    before = conn.latest(None)
    written: list[dict[str, Any]] = []
    body = {
        "assigned_object_type": "netbox_branching.branch",
        "assigned_object_id": branch.id,
        "kind": "info",
        "comments": "fylgja",
    }
    entry = FirstRender(lambda: written.append(box.post("extras/journal-entries/", body)))
    try:
        with reader_over(entry) as own:
            result = read(own, branch=None, scope=SCOPE, document=unprobed)
        assert entry.done and len(written) == 1
        doc = taken(result)
        changes = conn.changes(None, before)
        assert [change.kind for change in changes.items] == ["extras.journalentry"]
        assert doc["source"]["changelog"] == changes.items[0].id
    finally:
        for made in written:
            box.delete(f"extras/journal-entries/{made['id']}/")


def test_the_same_state_read_twice_gives_one_id(
    conn: NetBox, box: Writes, branch: Branch, document: ReaderDocument
) -> None:
    """`main`, and a branch holding the third cable of `testdata/blueprint/three-node.json`, each read twice with the
    seed's reader document, probes and all."""
    on_main = [taken(read(conn, branch=None, scope=SCOPE, document=document)) for _ in range(2)]
    assert but_observed(on_main[0]) == but_observed(on_main[1])
    assert blueprint.blueprint_id(on_main[0]) == blueprint.blueprint_id(on_main[1])

    ends = []
    for name in ("n1", "n3"):
        device = box.one("dcim/devices/", branch=branch.schema_id, name=name)
        assert device is not None, name
        port = box.one("dcim/interfaces/", branch=branch.schema_id, device_id=device["id"], name="ethernet-1/2")
        assert port is not None, name
        ends.append([{"object_type": "dcim.interface", "object_id": port["id"]}])
    box.post("dcim/cables/", {"a_terminations": ends[0], "b_terminations": ends[1]}, branch=branch.schema_id)

    on_branch = [taken(read(conn, branch=branch.name, scope=SCOPE, document=document)) for _ in range(2)]
    assert but_observed(on_branch[0]) == but_observed(on_branch[1])
    assert blueprint.blueprint_id(on_branch[0]) == blueprint.blueprint_id(on_branch[1])
    assert len(on_branch[0]["network"]["links"]) == 3
    assert blueprint.blueprint_id(on_branch[0]) != blueprint.blueprint_id(on_main[0])


def test_the_reader_wrote_nothing() -> None:
    """Every request of every connection the tier's reader made in this session, read from `SENT`, the refused
    connect of a token NetBox never made among them: `GET`s, and `POST`s to a render's path alone. The conftest runs
    this test last of the session, since it judges the session's connections; run alone it has none to judge, and
    skips saying so. The command's process, test_cli_contract.py's, is not recorded here, its transport being its
    own: the pure tier's tests/test_requests.py holds every request the reader's code can send, the command's among
    them, to these."""
    sent = [request for requests in SENT.values() for request in requests]
    if not sent:
        pytest.skip("this test judges the requests of the session's connections, and no test before it made one")
    assert {method for method, _ in sent} <= {"GET", "POST"}
    posted = [path for method, path in sent if method == "POST"]
    assert posted, "no render was recorded"
    assert [path for path in posted if not RENDER.fullmatch(path)] == []
    assert [path for _, path in sent if not path.endswith("/")] == []
