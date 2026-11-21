"""The bracket of a real read on the development Nautobot (D-118; design/verified-facts.md, "Nautobot 3.2.8 with Golden
Config 3.0.8", "The bracket"): an edit made between two renders of a read refuses it, and the read made again gives a
blueprint holding the edit; a changelog row made visible late, a count of one more at the close with its newest row
unchanged, refuses it; a push to the template repository between two renders refuses the read once, and the read after
gives a blueprint of the commit pushed; the same state read twice gives one id; and the reader, over the whole session,
sent no request but a `GET`, none with `branch`, and none longer than the request bound.

The edit and the push are made in flight by `reader_over`, as the first render's answer passes on its way to the
reader, since that is the fault the bracket exists for and no write between two calls of the test could land inside one
read. The row made visible late is made in flight too: a transaction's rows become visible at its commit, with the time
they were written (design/verified-facts.md), and no write of the tier's can be timed to commit inside one read, so the
close's count is answered one more on its way to the reader. Every write is the superuser's, through `box`: the edit
of a seeded interface, put back in a `finally` (`restored`), and the push, the tracked templates pushed back and each
seeded device rendered again in a `finally`. No assertion message prints the address or a token."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fylgja_core import blueprint

from fylgja_nautobot import Nautobot, ReaderDocument, Result, read
from fylgja_nautobot.transport import CHANGES, MAX_REQUEST, RENDER

from .conftest import SENT, TEMPLATE, Writes, contract_name, pushed, reader_over, restored, settle

SCOPE = "tag:fylgja"
REPOSITORY = "fylgja-templates"
"""The template repository the seed registers."""

BY_IDS = frozenset({"id", "device_id", "associated_object_id"})
"""The parameters a list by ids is asked by, which the transport batches to `MAX_REQUEST`."""


@pytest.fixture(scope="module")
def unprobed(document: ReaderDocument) -> ReaderDocument:
    """The seeded fixture network's reader document, naming no configuration context of probes."""
    return ReaderDocument(document.platforms, None)


def errors(result: Result) -> list[tuple[str, str | None]]:
    return sorted((finding.rule, finding.object) for finding in result.findings if finding.severity == "error")


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

    def __init__(self, then: Callable[[], object]) -> None:
        self.then = then
        self.done = False

    def __call__(self, request: httpx.Request, response: httpx.Response) -> httpx.Response:
        if not self.done and request.url.path == RENDER:
            self.done = True
            self.then()
        return response


def test_an_edit_between_two_renders_refuses_the_read(
    conn: Nautobot, box: Writes, unprobed: ReaderDocument
) -> None:
    """`n3 ethernet-1/1` disabled as `n1`'s render, the read's first, passes: `n3`'s render after it holds the edit and
    `n1`'s does not, a network that never was. The edit writes a changelog row, which the close sees. Put back after."""
    n3 = box.one("dcim/devices/", name="n3")
    assert n3 is not None
    port = box.one("dcim/interfaces/", device_id=n3["id"], name="ethernet-1/1")
    assert port is not None and port["enabled"] is True
    path = f"dcim/interfaces/{port['id']}/"

    with restored(box, path, ["enabled"]):
        edit = FirstRender(lambda: box.patch(path, {"enabled": False}))
        with reader_over(edit) as own:
            result = read(own, scope=SCOPE, document=unprobed)
        assert edit.done
        assert result.blueprint is None
        assert errors(result) == [("read.moved", "extras.objectchange")]
        assert "read again" in result.findings[0].message

        again = taken(read(conn, scope=SCOPE, document=unprobed))
        held = {(d["name"], i["name"]): i["enabled"] for d in again["network"]["devices"] for i in d["interfaces"]}
        assert held[("n3", "ethernet-1/1")] is False
        n3_config = next(d for d in again["network"]["devices"] if d["name"] == "n3")["config"]
        assert "set / interface ethernet-1/1 admin-state disable" in n3_config.splitlines()


def test_a_row_visible_late_refuses_the_read(unprobed: ReaderDocument) -> None:
    """In flight: the first answer of the changelog after a render has passed, the close's, is answered with its count
    one more and its newest row unchanged, as a row of an earlier time made visible at its transaction's commit is
    seen. The close refuses the read by the count alone, both counts given."""

    class Late:
        def __init__(self) -> None:
            self.rendered = False
            self.raised: int | None = None

        def __call__(self, request: httpx.Request, response: httpx.Response) -> httpx.Response:
            if request.url.path == RENDER:
                self.rendered = True
            elif request.url.path == CHANGES and self.rendered and self.raised is None:
                body = response.json()
                self.raised = body["count"]
                return httpx.Response(response.status_code, json={**body, "count": body["count"] + 1})
            return response

    late = Late()
    with reader_over(late) as own:
        result = read(own, scope=SCOPE, document=unprobed)
    assert late.raised is not None
    assert result.blueprint is None
    assert errors(result) == [("read.moved", "extras.objectchange")]
    message = result.findings[0].message
    assert f"held {late.raised} rows at the read's open and {late.raised + 1} at its close" in message
    assert "at both" in message and "read again" in message


def test_a_push_mid_read_refuses_it_once(conn: Nautobot, box: Writes, document: ReaderDocument) -> None:
    """A commit pushed to the template repository as `n1`'s render, the read's first, passes: `n2`'s render after it
    fetches the commit, which moves the repository's head and writes a changelog row (design/verified-facts.md, "A
    render by the reader after a push moves the head and writes one changelog row."), so the read is refused, naming
    `fylgja-templates` with both heads. The next read finds the head fetched already and gives a blueprint whose
    `templates` is the commit. The tracked templates are pushed back after, and each seeded device rendered again."""
    before = taken(read(conn, scope=SCOPE, document=document))["source"]["templates"][REPOSITORY]
    commits: list[str] = []
    try:
        push = FirstRender(lambda: commits.append(pushed(TEMPLATE.read_text() + "{# " + contract_name() + " #}\n")))
        with reader_over(push) as own:
            result = read(own, scope=SCOPE, document=document)
        assert push.done and len(commits) == 1
        assert result.blueprint is None
        assert errors(result) == [("read.moved", "extras.objectchange"), ("read.moved", REPOSITORY)]
        (head,) = [f for f in result.findings if f.object == REPOSITORY]
        assert before in head.message and commits[0] in head.message and "read again" in head.message

        after = taken(read(conn, scope=SCOPE, document=document))
        assert after["source"]["templates"] == {REPOSITORY: commits[0]}
    finally:
        if commits:
            pushed(TEMPLATE.read_text())
            settle(box)


def test_the_same_state_read_twice_gives_one_id(conn: Nautobot, document: ReaderDocument) -> None:
    """The seeded fixture read twice with the seed's reader document, probes and all: one blueprint but its
    `observed_at`, and one id."""
    first, second = (taken(read(conn, scope=SCOPE, document=document)) for _ in range(2))
    assert but_observed(first) == but_observed(second)
    assert blueprint.blueprint_id(first) == blueprint.blueprint_id(second)
    print(f"the same state read twice: {blueprint.blueprint_id(first)}")


def test_the_reader_sent_get_alone() -> None:
    """Every request of every connection the tier's reader made in this session, read from `SENT`, the refused
    connect of a token Nautobot never made among them: a `GET`, to a path ending in `/`, with no `branch`; and every
    list by ids within `MAX_REQUEST` bytes of path and query. The conftest runs this test last of the session, since it
    judges the session's connections; run alone it has none to judge, and skips saying so. The command's process,
    test_cli_contract.py's, is not recorded here, its transport being its own: the pure tier's tests/test_requests.py
    holds every request the reader's code can send, the command's among them."""
    sent = [request for requests in SENT.values() for request in requests]
    if not sent:
        pytest.skip("this test judges the requests of the session's connections, and no test before it made one")
    assert {request.method for request in sent} == {"GET"}
    assert [request.path for request in sent if not request.path.endswith("/")] == []
    assert [request.path for request in sent if "branch" in request.params] == []
    assert sum(request.path == RENDER for request in sent) > 0, "no render was recorded"
    by_ids = [request for request in sent if BY_IDS & set(request.params)]
    assert by_ids, "no list by ids was recorded"
    assert [(request.path, request.length) for request in by_ids if request.length > MAX_REQUEST] == []
