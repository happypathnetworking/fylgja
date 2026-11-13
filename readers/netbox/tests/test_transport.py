"""The transport, the one module that speaks to NetBox (D-096), over an `httpx.MockTransport` whose answers each test
builds: a REST list of `count` and `results`, never an answer captured from NetBox (D-034). It reads NetBox's version
and the branching plugin's once, sends the token as a bearer and a branch by its `schema_id`, pages every list to the
`count` NetBox answered and never by its `next`, asks ids `IDS` a request, holds each row to what was asked, keeps the
status of a refusal with the branch, and holds the token out of every error, repr and log line."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fylgja_core.client import InvalidToken
from fylgja_core.findings import Finding

from fylgja_netbox import SUPPORTED, NetBox, NetBoxError, connect, renders, transport
from fylgja_netbox.rows import (
    Branch,
    Cable,
    Change,
    Context,
    Device,
    End,
    Listing,
    Platform,
    Port,
    Rendered,
    Source,
    Tag,
)

HOST = "netbox.example"
ADDRESS = f"http://{HOST}"
TOKEN = "nbt_0a1b2c3d4e5f.00112233445566778899aabbccddeeff01234567"
"""A token of NetBox's v2 shape, `nbt_<key>.<token>`, a key of 12 and a token of 40, that no NetBox made."""

SYNCED = "2026-11-12T16:30:00.115200Z"
"""A branch's `last_sync`, as NetBox answers one."""

BRANCH = Branch(7, "b", "p9d46y7z", "ready", SYNCED)

Answer = Callable[[httpx.Request], httpx.Response]


class Served:
    """A fake NetBox: `GET /api/status/` answers `status`, or `info` where it is given, and every other request
    `answer`; each request is kept."""

    def __init__(
        self,
        answer: Answer | None = None,
        *,
        version: str = "4.7.5",
        plugins: dict[str, str] | None = None,
        info: Answer | None = None,
    ) -> None:
        self.answer = answer
        held = {"netbox_branching": "1.2.3"} if plugins is None else plugins
        self.status = {"netbox-version": version, "plugins": held}
        self.info = info
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/api/status/":
            if self.info is not None:
                return self.info(request)
            return httpx.Response(200, json=self.status)
        assert self.answer is not None, f"no answer for {request.url}"
        return self.answer(request)

    @property
    def asked(self) -> list[httpx.Request]:
        """The requests after the status request."""
        return [request for request in self.requests if request.url.path != "/api/status/"]


def opened(served: Served) -> NetBox:
    return connect(ADDRESS, TOKEN, transport=httpx.MockTransport(served))


def page(count: int, results: list[dict[str, Any]], *, after: str | None = None) -> httpx.Response:
    """A REST list's page: `count`, `results`, and a `next` where `after` is given."""
    return httpx.Response(200, json={"count": count, "next": after, "previous": None, "results": results})


def numbers(request: httpx.Request, name: str) -> list[int]:
    return [int(value) for value in request.url.params.get_list(name)]


def offsets(served: Served) -> list[tuple[int, int]]:
    return [(numbers(r, "offset")[0], numbers(r, "limit")[0]) for r in served.asked]


def tag_row(id: int, name: str) -> dict[str, Any]:
    return {"id": id, "name": name, "slug": name}


def device_row(id: int, name: str | None, *, tags: list[int], platform: int | None = 1) -> dict[str, Any]:
    return {
        "id": id,
        "name": name,
        "platform": {"id": platform, "name": "SR Linux"} if platform is not None else None,
        "tags": [{"id": tag, "name": f"t{tag}"} for tag in tags],
    }


def platform_row(id: int, name: str, manufacturer: str | None) -> dict[str, Any]:
    return {"id": id, "name": name, "manufacturer": {"id": 1, "name": manufacturer} if manufacturer else None}


def port_row(id: int, device: int, name: str, *, cable: int | None = None, mgmt_only: bool = False) -> dict[str, Any]:
    return {
        "id": id,
        "device": {"id": device, "name": f"n{device}"},
        "name": name,
        "type": {"value": "25gbase-x-sfp28", "label": "SFP28 (25GE)"},
        "enabled": True,
        "mgmt_only": mgmt_only,
        "cable": {"id": cable, "label": ""} if cable is not None else None,
    }


def end_row(kind: str, id: int, display: str | None) -> dict[str, Any]:
    held: dict[str, Any] = {"object_type": kind, "object_id": id}
    if display is not None:
        held["object"] = {"id": id, "display": display, "name": display}
    return held


def cable_row(id: int, label: str, a: list[dict[str, Any]], b: list[dict[str, Any]]) -> dict[str, Any]:
    return {"id": id, "label": label, "a_terminations": a, "b_terminations": b}


def branch_row(id: int, name: str, schema_id: str, status: str, last_sync: str | None = SYNCED) -> dict[str, Any]:
    return {
        "id": id,
        "name": name,
        "schema_id": schema_id,
        "status": {"value": status, "label": status.title()},
        "last_sync": last_sync,
    }


def context_row(id: int, name: str, *, active: bool = False, data: object = None) -> dict[str, Any]:
    held = {"probes_version": "1", "probes": []} if data is None else data
    return {"id": id, "name": name, "is_active": active, "data": held, "weight": 1000, "sites": []}


def change_row(id: int, kind: str) -> dict[str, Any]:
    return {"id": id, "changed_object_type": kind, "action": {"value": "update", "label": "Updated"}}


def warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "fylgja.netbox" and r.levelno >= logging.WARNING]


def test_connect_reads_both_versions(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="fylgja.netbox")
    assert SUPPORTED == (("4.7.5", "1.2.3"),)
    served = Served()
    with opened(served) as conn:
        assert (conn.version, conn.branching, conn.unverified) == ("4.7.5", "1.2.3", None)
        assert repr(conn) == "NetBox(version='4.7.5', branching='1.2.3')", "the repr holds the two versions alone"
    assert [(r.method, r.url.path) for r in served.requests] == [("GET", "/api/status/")]
    assert warnings(caplog) == []

    for version, plugins, unverified in [
        ("4.8.0", {"netbox_branching": "1.2.3"}, "4.8.0/1.2.3"),
        ("4.7.5", {"netbox_branching": "1.3.0"}, "4.7.5/1.3.0"),
        ("4.7.5", {}, "4.7.5/none"),
    ]:
        caplog.clear()
        with opened(Served(version=version, plugins=plugins)) as conn:
            finding = conn.unverified
            assert finding is not None
            assert (finding.rule, finding.severity) == (transport.RULE_UNVERIFIED, "warning")
            assert finding.object == unverified
            assert "4.7.5" in finding.message and "1.2.3" in finding.message
            assert conn.version == version
            assert conn.branching == plugins.get("netbox_branching")
        warned = warnings(caplog)
        assert [r.levelno for r in warned] == [logging.WARNING]
        assert warned[0].getMessage() == finding.message
    assert transport.RULE_UNVERIFIED == "netbox.version.unverified"


def answering(status: int, body: object) -> Answer:
    """An answer of `status` with `body` as JSON, to every request."""

    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    return answer


@pytest.mark.parametrize(
    "body",
    [
        {"plugins": {}},
        {"netbox-version": "", "plugins": {}},
        {"netbox-version": "4.7.5"},
        {"netbox-version": "4.7.5", "plugins": []},
        [],
    ],
    ids=["no version", "an empty version", "no plugins", "plugins no mapping", "no object"],
)
def test_a_status_with_no_version_or_no_plugins_is_an_error(body: object) -> None:
    with pytest.raises(NetBoxError) as raised:
        opened(Served(info=answering(200, body)))
    assert raised.value.status == 200
    assert str(raised.value).startswith("reading NetBox's version: HTTP 200: answered no ")


def test_netbox_is_a_source() -> None:
    """mypy holds the transport's `NetBox` to `rows.Source`, which the read is typed against."""
    with opened(Served()) as conn:
        source: Source = conn
        assert source.version == "4.7.5"


def test_connect_gives_each_request_60_s_reads_no_environment_and_follows_no_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    made: list[dict[str, Any]] = []
    real = httpx.Client

    def client(*args: Any, **kwargs: Any) -> httpx.Client:
        made.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", client)
    opened(Served()).close()
    assert [(k["timeout"], k["trust_env"], k.get("follow_redirects", False)) for k in made] == [(60.0, False, False)]
    assert transport.TIMEOUT_S == 60.0


def test_the_token_is_a_bearer_and_a_branch_is_its_schema_id() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/plugins/branching/branches/":
            return page(1, [branch_row(7, "b", "p9d46y7z", "ready")])
        return page(1, [port_row(10, 1, "ethernet-1/1")])

    served = Served(answer)
    with opened(served) as conn:
        conn.ports(BRANCH, [1])
        conn.ports(None, [1])
        conn.branches("b")
    status, under, on_main, branches = served.requests
    for request in served.requests:
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert under.headers["X-NetBox-Branch"] == "p9d46y7z"
    for request in (status, on_main, branches):
        assert "X-NetBox-Branch" not in request.headers
    assert [(r.method, r.url.path) for r in served.requests] == [
        ("GET", "/api/status/"),
        ("GET", "/api/dcim/interfaces/"),
        ("GET", "/api/dcim/interfaces/"),
        ("GET", "/api/plugins/branching/branches/"),
    ]


def test_each_list_is_asked_by_its_filter_and_read_into_rows() -> None:
    answers = {
        "/api/plugins/branching/branches/": page(1, [branch_row(7, "b", "p9d46y7z", "provisioning")]),
        "/api/extras/tags/": page(1, [tag_row(4, "fylgja")]),
        "/api/dcim/devices/": page(2, [device_row(1, "n1", tags=[2, 4]), device_row(2, None, tags=[4], platform=None)]),
        "/api/dcim/platforms/": page(2, [platform_row(1, "SR Linux", "Nokia"), platform_row(3, "EOS", None)]),
        "/api/dcim/interfaces/": page(
            2, [port_row(10, 1, "ethernet-1/1", cable=5), port_row(11, 2, "mgmt0", mgmt_only=True)]
        ),
        "/api/dcim/cables/": page(
            1,
            [
                cable_row(
                    5,
                    "",
                    [end_row("dcim.interface", 10, "ethernet-1/1")],
                    [end_row("dcim.frontport", 12, None), end_row("dcim.interface", 13, "ethernet-1/2")],
                )
            ],
        ),
    }
    served = Served(lambda request: answers[request.url.path])
    with opened(served) as conn:
        provisioning = Branch(7, "b", "p9d46y7z", "provisioning", SYNCED)
        assert conn.branches("b") == Listing("netbox_branching.branch", 1, (provisioning,))
        assert conn.tags(BRANCH, "fylgja") == Listing("extras.tag", 1, (Tag(4, "fylgja"),))
        assert conn.devices(BRANCH, 4) == Listing("dcim.device", 2, (Device(1, "n1", 1), Device(2, None, None)))
        assert conn.platforms(BRANCH, [1, 3]) == Listing(
            "dcim.platform", 2, (Platform(1, "SR Linux", "Nokia"), Platform(3, "EOS", None))
        )
        port = Port(10, 1, "ethernet-1/1", "25gbase-x-sfp28", True, False, 5)
        mgmt = Port(11, 2, "mgmt0", "25gbase-x-sfp28", True, True, None)
        assert conn.ports(BRANCH, [1, 2]) == Listing("dcim.interface", 2, (port, mgmt))
        ends = (End("dcim.frontport", 12, None), End("dcim.interface", 13, "ethernet-1/2"))
        assert conn.cables(BRANCH, [5]) == Listing(
            "dcim.cable", 1, (Cable(5, None, (End("dcim.interface", 10, "ethernet-1/1"),), ends),)
        )
    asked = [(r.url.path, sorted(set(r.url.params) - {"limit", "offset"})) for r in served.asked]
    assert asked == [
        ("/api/plugins/branching/branches/", ["name"]),
        ("/api/extras/tags/", ["name"]),
        ("/api/dcim/devices/", ["tag_id"]),
        ("/api/dcim/platforms/", ["id"]),
        ("/api/dcim/interfaces/", ["device_id"]),
        ("/api/dcim/cables/", ["id"]),
    ]
    branches, tags, devices, platforms, ports, cables = served.asked
    assert (branches.url.params["name"], tags.url.params["name"], devices.url.params["tag_id"]) == ("b", "fylgja", "4")
    assert (numbers(platforms, "id"), numbers(ports, "device_id"), numbers(cables, "id")) == ([1, 3], [1, 2], [5])
    assert all(request.url.path.endswith("/") for request in served.requests)


def test_a_context_is_asked_by_its_name_under_the_branchs_header() -> None:
    """A configuration context is listed by `?name=`, under the branch's header and with none on `main`, its data
    kept as NetBox answered it, whatever JSON it is."""
    declared = {"probes_version": "1", "probes": [{"name": "n1-loop"}]}
    answers = [
        page(1, [context_row(1, "fylgja-probes", data=declared)]),
        page(1, [context_row(2, "fylgja-probes", active=True, data=[1, "x"])]),
        page(0, []),
    ]
    served = Served(lambda request: answers.pop(0))
    with opened(served) as conn:
        assert conn.contexts(BRANCH, "fylgja-probes") == Listing(
            "extras.configcontext", 1, (Context(1, "fylgja-probes", False, declared),)
        )
        assert conn.contexts(None, "fylgja-probes") == Listing(
            "extras.configcontext", 1, (Context(2, "fylgja-probes", True, [1, "x"]),)
        )
        assert conn.contexts(None, "none") == Listing("extras.configcontext", 0, ())
    under, on_main, none = served.asked
    assert [(r.method, r.url.path) for r in served.asked] == [("GET", "/api/extras/config-contexts/")] * 3
    assert under.headers["X-NetBox-Branch"] == "p9d46y7z"
    assert "X-NetBox-Branch" not in on_main.headers and "X-NetBox-Branch" not in none.headers
    assert sorted(set(under.url.params) - {"limit", "offset"}) == ["name"]
    assert (under.url.params["name"], none.url.params["name"]) == ("fylgja-probes", "none")


def test_the_pager_reads_every_page_and_answers_the_count() -> None:
    every = [port_row(i, 1, f"p{i}") for i in range(250)]

    def answer(request: httpx.Request) -> httpx.Response:
        start, size = numbers(request, "offset")[0], numbers(request, "limit")[0]
        return page(250, every[start : start + size])

    served = Served(answer)
    with opened(served) as conn:
        count, results = conn.listed("/api/dcim/interfaces/", "dcim.interface", [("device_id", "1")], branch=None)
    assert transport.PAGE == 100
    assert offsets(served) == [(0, 100), (100, 100), (200, 100)]
    assert all(numbers(r, "device_id") == [1] for r in served.asked)
    assert (count, len(results)) == (250, 250)
    assert results == every


def test_the_pager_ends_on_a_list_short_of_its_count() -> None:
    answers = iter([page(3, [port_row(1, 1, "a"), port_row(2, 1, "b")]), page(3, [])])
    served = Served(lambda request: next(answers))
    with opened(served) as conn:
        count, results = conn.listed("/api/dcim/interfaces/", "dcim.interface", [], branch=None)
    assert offsets(served) == [(0, 100), (2, 100)]
    assert (count, len(results)) == (3, 2)


def test_the_pager_keeps_the_largest_count_a_page_answered() -> None:
    """A row deleted between two pages shifts the offsets and lowers the count: kept at the largest, the list reads
    short of it, for `rows.incomplete` to refuse, never as whole."""
    answers = iter([page(3, [port_row(1, 1, "a"), port_row(2, 1, "b")]), page(2, [port_row(3, 1, "c")])])
    served = Served(lambda request: next(answers))
    with opened(served) as conn:
        count, results = conn.listed("/api/dcim/interfaces/", "dcim.interface", [], branch=None)
    assert offsets(served) == [(0, 100), (2, 100)]
    assert (count, len(results)) == (3, 3)


def test_the_pager_never_follows_next() -> None:
    """NetBox's `next` holds NetBox's own address, which may not be the one the reader was given."""
    answers = iter(
        [
            page(3, [port_row(1, 1, "a"), port_row(2, 1, "b")], after="http://other.example/api/dcim/interfaces/?x=1"),
            page(3, [port_row(3, 1, "c")], after="http://other.example/api/dcim/interfaces/?x=2"),
        ]
    )
    served = Served(lambda request: next(answers))
    with opened(served) as conn:
        count, results = conn.listed("/api/dcim/interfaces/", "dcim.interface", [], branch=None, size=2)
    assert {request.url.host for request in served.requests} == {HOST}
    assert offsets(served) == [(0, 2), (2, 2)]
    assert all("x" not in request.url.params for request in served.requests)
    assert (count, len(results)) == (3, 3)


def test_ids_are_asked_fifty_a_request_and_their_counts_summed() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        devices = numbers(request, "device_id")
        return page(len(devices), [port_row(1000 + d, d, "mgmt0") for d in devices])

    served = Served(answer)
    with opened(served) as conn:
        ports = conn.ports(None, list(range(1, 121)))
    assert transport.IDS == 50
    assert [numbers(r, "device_id") for r in served.asked] == [
        list(range(1, 51)),
        list(range(51, 101)),
        list(range(101, 121)),
    ]
    assert (ports.what, ports.count, len(ports.items)) == ("dcim.interface", 120, 120)
    assert [port.device for port in ports.items] == list(range(1, 121))


def test_the_latest_id_is_read_under_the_branchs_header() -> None:
    """`?limit=1&ordering=-id` answers the row of the highest id, under the changelog of the branch the header names
    and of `main` with none (design/verified-facts.md, "The changelog's two requests"); one holding no row, `count 0`,
    has no latest id."""
    answers = iter([page(50, [change_row(1288, "dcim.interface")]), page(179, [change_row(1230, "x.y")]), page(0, [])])
    served = Served(lambda request: next(answers))
    with opened(served) as conn:
        assert conn.latest(BRANCH) == 1288
        assert conn.latest(None) == 1230
        assert conn.latest(BRANCH) is None
    under, on_main, empty = served.asked
    for request in served.asked:
        assert (request.method, request.url.path) == ("GET", "/api/core/object-changes/")
        assert list(request.url.params.multi_items()) == [("limit", "1"), ("ordering", "-id")]
    assert under.headers["X-NetBox-Branch"] == empty.headers["X-NetBox-Branch"] == "p9d46y7z"
    assert "X-NetBox-Branch" not in on_main.headers


@pytest.mark.parametrize(
    ("count", "results", "said"),
    [
        (1, [], "answered a count of 1 and no row"),
        (0, [change_row(3, "dcim.interface")], "answered a count of 0 and a row"),
        (2, [change_row(3, "dcim.interface"), change_row(2, "dcim.interface")], "answered 2 rows to a limit of 1"),
    ],
    ids=["a count and no row", "a row and no count", "two rows"],
)
def test_a_latest_id_that_is_no_answer_is_an_error(count: int, results: list[dict[str, Any]], said: str) -> None:
    with opened(Served(lambda request: page(count, results))) as conn, pytest.raises(NetBoxError) as raised:
        conn.latest(BRANCH)
    assert raised.value.status == 200
    assert str(raised.value).startswith("reading core.objectchange (branch b): HTTP 200: ")
    assert said in str(raised.value)


def test_the_rows_at_or_below_an_id_are_counted() -> None:
    """`?id__lte=<n>` is honoured where an unknown parameter answers the whole list (design/verified-facts.md, "An upper
    bound on the id"): its `count` is the rows at or below `n`, and a row above `n` answered is an error."""
    served = Served(lambda request: page(117, [change_row(141, "dcim.interface")]))
    with opened(served) as conn:
        assert conn.counted(BRANCH, 141) == 117
    (asked,) = served.asked
    assert (asked.method, asked.url.path) == ("GET", "/api/core/object-changes/")
    assert list(asked.url.params.multi_items()) == [("id__lte", "141"), ("limit", "1"), ("ordering", "-id")]
    assert asked.headers["X-NetBox-Branch"] == "p9d46y7z"

    with opened(Served(lambda request: page(0, []))) as conn:
        assert conn.counted(None, 141) == 0

    served = Served(lambda request: page(233, [change_row(1477, "dcim.interface")]))
    with opened(served) as conn, pytest.raises(NetBoxError) as raised:
        conn.counted(None, 141)
    assert raised.value.status == 200
    assert "the core.objectchange 1477, which the request did not ask for" in str(raised.value)


def test_the_changes_above_an_id_are_listed_whole() -> None:
    every = [change_row(101 + i, "dcim.interface" if i % 2 else "extras.journalentry") for i in range(250)]

    def answer(request: httpx.Request) -> httpx.Response:
        start, size = numbers(request, "offset")[0], numbers(request, "limit")[0]
        above = request.url.params.get("id__gt")
        rows = every if above is None else [row for row in every if row["id"] > int(above)]
        return page(len(rows), rows[start : start + size])

    served = Served(answer)
    with opened(served) as conn:
        changes = conn.changes(BRANCH, 100)
        first = conn.changes(None, None)
    held = tuple(Change(row["id"], row["changed_object_type"]) for row in every)
    assert changes == Listing("core.objectchange", 250, held)
    assert first.count == 250
    asked = served.asked
    assert [r.headers.get("X-NetBox-Branch") for r in asked] == ["p9d46y7z"] * 3 + [None] * 3
    assert [list(r.url.params.multi_items()) for r in asked[:3]] == [
        [("id__gt", "100"), ("ordering", "id"), ("limit", "100"), ("offset", str(offset))] for offset in (0, 100, 200)
    ]
    assert [list(r.url.params.multi_items()) for r in asked[3:]] == [
        [("ordering", "id"), ("limit", "100"), ("offset", str(offset))] for offset in (0, 100, 200)
    ]

    for row in (change_row(100, "dcim.interface"), change_row(99, "dcim.interface")):
        served = Served(answering(200, {"count": 1, "results": [row]}))
        with opened(served) as conn, pytest.raises(NetBoxError) as raised:
            conn.changes(BRANCH, 100)
        assert raised.value.status == 200
        assert f"the core.objectchange {row['id']}, which the request did not ask for" in str(raised.value)


def test_no_ids_send_nothing() -> None:
    served = Served()
    with opened(served) as conn:
        assert conn.platforms(BRANCH, []) == Listing("dcim.platform", 0, ())
        assert conn.ports(BRANCH, []) == Listing("dcim.interface", 0, ())
        assert conn.cables(BRANCH, []) == Listing("dcim.cable", 0, ())
    assert served.asked == []


def read(conn: NetBox, what: str) -> object:
    calls: dict[str, Callable[[], object]] = {
        "netbox_branching.branch": lambda: conn.branches("b"),
        "extras.tag": lambda: conn.tags(None, "fylgja"),
        "dcim.device": lambda: conn.devices(None, 4),
        "dcim.platform": lambda: conn.platforms(None, [1]),
        "dcim.interface": lambda: conn.ports(None, [1]),
        "dcim.cable": lambda: conn.cables(None, [5]),
        "core.objectchange": lambda: conn.changes(None, 5),
        "extras.configcontext": lambda: conn.contexts(None, "fylgja-probes"),
    }
    return calls[what]()


def refused_by(what: str, results: list[dict[str, Any]]) -> NetBoxError:
    with opened(Served(lambda request: page(len(results), results))) as conn, pytest.raises(NetBoxError) as raised:
        read(conn, what)
    return raised.value


@pytest.mark.parametrize(
    ("what", "row", "said"),
    [
        ("dcim.device", device_row(1, "n1", tags=[2]), "the dcim.device 1 without the tag 4,"),
        ("dcim.interface", port_row(10, 2, "ethernet-1/1"), "the dcim.interface 10 of the dcim.device 2,"),
        (
            "dcim.cable",
            cable_row(6, "", [end_row("dcim.interface", 1, "a")], [end_row("dcim.interface", 2, "b")]),
            "the dcim.cable 6,",
        ),
        ("dcim.platform", platform_row(2, "SR Linux", "Nokia"), "the dcim.platform 2,"),
        ("extras.tag", tag_row(4, "fylgja-other"), "the extras.tag 4 named fylgja-other,"),
        (
            "netbox_branching.branch",
            branch_row(7, "b-other", "p9d46y7z", "ready"),
            "the netbox_branching.branch 7 named b-other,",
        ),
        ("core.objectchange", change_row(5, "dcim.interface"), "the core.objectchange 5,"),
        (
            "extras.configcontext",
            context_row(1, "fylgja-probes-other"),
            "the extras.configcontext 1 named fylgja-probes-other,",
        ),
    ],
    ids=["device", "interface", "cable", "platform", "tag", "branch", "change", "context"],
)
def test_a_row_the_request_did_not_ask_for_is_an_error(what: str, row: dict[str, Any], said: str) -> None:
    """NetBox answers the whole list to a parameter it does not know (design/verified-facts.md, "NetBox 4.7.5 with
    netbox-branching 1.2.3"), so a row of another than was asked is refused, never read as one that was."""
    e = refused_by(what, [row])
    assert e.status == 200
    for held in (f"reading {what} (main)", "HTTP 200", "did not ask for", said):
        assert held in str(e)


ROWS = {
    "netbox_branching.branch": branch_row(7, "b", "p9d46y7z", "ready"),
    "extras.tag": tag_row(4, "fylgja"),
    "dcim.device": device_row(1, "n1", tags=[4]),
    "dcim.platform": platform_row(1, "SR Linux", "Nokia"),
    "dcim.interface": port_row(10, 1, "ethernet-1/1"),
    "dcim.cable": cable_row(5, "", [end_row("dcim.interface", 1, "a")], [end_row("dcim.interface", 2, "b")]),
    "core.objectchange": change_row(6, "dcim.interface"),
    "extras.configcontext": context_row(1, "fylgja-probes"),
}


@pytest.mark.parametrize("what", list(ROWS))
def test_a_row_without_its_id_is_an_error(what: str) -> None:
    for id in (None, "1", True):
        row = {**ROWS[what], "id": id}
        e = refused_by(what, [row])
        assert e.status == 200
        assert f"answered a {what} with no id" in str(e)
    e = refused_by(what, [{key: value for key, value in ROWS[what].items() if key != "id"}])
    assert f"answered a {what} with no id" in str(e)


ABSENT = object()
"""A member left out of the row."""


@pytest.mark.parametrize(
    ("what", "member", "value"),
    [
        ("netbox_branching.branch", "name", ABSENT),
        ("netbox_branching.branch", "schema_id", None),
        ("netbox_branching.branch", "status", "ready"),
        ("netbox_branching.branch", "last_sync", ABSENT),
        ("netbox_branching.branch", "last_sync", 5),
        ("extras.tag", "name", None),
        ("dcim.device", "name", ABSENT),
        ("dcim.device", "tags", None),
        ("dcim.device", "platform", {"name": "SR Linux"}),
        ("dcim.platform", "manufacturer", {"id": 1}),
        ("dcim.interface", "enabled", None),
        ("dcim.interface", "mgmt_only", "false"),
        ("dcim.interface", "type", "1000base-t"),
        ("dcim.interface", "device", None),
        ("dcim.interface", "cable", {"label": ""}),
        ("dcim.cable", "a_terminations", None),
        ("dcim.cable", "b_terminations", [{"object_type": "dcim.interface"}]),
        ("dcim.cable", "label", ABSENT),
        ("core.objectchange", "changed_object_type", None),
        ("core.objectchange", "changed_object_type", ""),
        ("extras.configcontext", "name", None),
        ("extras.configcontext", "is_active", "false"),
        ("extras.configcontext", "data", ABSENT),
    ],
)
def test_a_row_without_a_member_it_needs_is_an_error(what: str, member: str, value: object) -> None:
    row = {key: held for key, held in ROWS[what].items() if key != member}
    e = refused_by(what, [row if value is ABSENT else {**row, member: value}])
    assert e.status == 200
    assert f"reading {what} (main): HTTP 200: answered a {what}" in str(e)
    assert member in str(e)


@pytest.mark.parametrize(
    "body", [{"results": []}, {"count": 1}, {"count": "1", "results": []}, {"count": 1, "results": {}}, []]
)
def test_an_answer_that_is_no_list_is_an_error(body: object) -> None:
    with opened(Served(lambda request: httpx.Response(200, json=body))) as conn, pytest.raises(NetBoxError) as raised:
        conn.tags(BRANCH, "fylgja")
    assert raised.value.status == 200
    assert "reading extras.tag (branch b): HTTP 200: answered no count and results" in str(raised.value)


def test_an_answer_that_is_no_json_is_an_error() -> None:
    with (
        opened(Served(lambda request: httpx.Response(200, text="<html>"))) as conn,
        pytest.raises(NetBoxError) as raised,
    ):
        conn.tags(None, "fylgja")
    assert (raised.value.status, str(raised.value)) == (200, "reading extras.tag (main): HTTP 200: answered no JSON")


def test_a_refusal_keeps_its_status_and_names_the_branch() -> None:
    def invalid(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"detail": "Invalid branch identifier"})

    with opened(Served(invalid)) as conn, pytest.raises(NetBoxError) as raised:
        conn.ports(BRANCH, [1])
    assert raised.value.status == 400
    assert str(raised.value) == "reading dcim.interface (branch b): HTTP 400: Invalid branch identifier"

    def echoed(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"detail": f"Refused {request.headers['Authorization']}", "x": "NetBox said"})

    for status, answer in [(401, answering(401, {"detail": f"Refused {TOKEN}"})), (403, echoed)]:
        with opened(Served(answer)) as conn, pytest.raises(NetBoxError) as raised:
            conn.devices(BRANCH, 4)
        assert raised.value.status == status
        text = str(raised.value)
        assert "FYLGJA_NETBOX_TOKEN" in text and "branch b" in text and f"HTTP {status}" in text
        for quoted in ("Refused", "NetBox said", TOKEN, "Bearer", "<redacted>"):
            assert quoted not in text


def test_an_id_netbox_does_not_hold_is_a_400_with_its_words() -> None:
    """NetBox answers 400 to `?device_id=` naming a device it does not hold (design/verified-facts.md), so a device
    deleted between the read's own list and its ports shows as this status, which the read acts on."""
    words = {"device_id": ["Select a valid choice. 9 is not one of the available choices."]}
    with (
        opened(Served(lambda request: httpx.Response(400, json=words))) as conn,
        pytest.raises(NetBoxError) as raised,
    ):
        conn.ports(None, [9])
    assert raised.value.status == 400
    assert "reading dcim.interface (main): HTTP 400: " in str(raised.value)
    assert "Select a valid choice. 9 is not one of the available choices." in str(raised.value)


def test_netboxs_words_are_cut_and_the_token_in_them_replaced() -> None:
    key, secret = TOKEN.removeprefix("nbt_").split(".")
    said = f"{TOKEN} {secret} {key} " + "x" * 400
    with (
        opened(Served(lambda request: httpx.Response(500, text=said))) as conn,
        pytest.raises(NetBoxError) as raised,
    ):
        conn.tags(None, "fylgja")
    assert raised.value.status == 500
    words = str(raised.value).removeprefix("reading extras.tag (main): HTTP 500: ")
    assert words.startswith("<redacted> <redacted> <redacted> xxx")
    assert len(words) == transport.QUOTED == 300
    for part in (TOKEN, secret, key):
        assert part not in str(raised.value)


NO_TEMPLATE = "{'error': 'No config template found for this device.'}"
"""What NetBox answers a render of a device with no template, 400 in `text/plain` (design/verified-facts.md)."""


@pytest.mark.parametrize(
    ("body", "quoted"),
    [
        (b"1e3", "1e3"),
        (NO_TEMPLATE.encode(), NO_TEMPLATE),
        (b'{"detail": "plain"}', '{"detail": "plain"}'),
    ],
    ids=["a number", "single-quoted", "json-shaped"],
)
def test_a_body_is_json_only_where_netbox_says_so(body: bytes, quoted: str) -> None:
    """A `text/plain` body is quoted as it stands, though it parse as JSON: NetBox answers a render with no template
    in `text/plain`, single-quoted (design/verified-facts.md)."""
    def plain(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, content=body, headers={"Content-Type": "text/plain; charset=utf-8"})

    with opened(Served(plain)) as conn, pytest.raises(NetBoxError) as raised:
        conn.tags(None, "fylgja")
    assert str(raised.value) == f"reading extras.tag (main): HTTP 400: {quoted}"


def test_a_render_is_a_post_of_no_body_asking_for_text_under_the_branchs_header() -> None:
    def text(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"set / x\n", headers={"Content-Type": "text/plain; charset=utf-8"})

    served = Served(text)
    with opened(served) as conn:
        under = conn.render(BRANCH, 12)
        on_main = conn.render(None, 12)
    assert under == on_main == Rendered(200, b"set / x\n", "text/plain; charset=utf-8")
    for request in served.asked:
        assert (request.method, request.url.path, request.url.query) == (
            "POST",
            "/api/dcim/devices/12/render-config/",
            b"",
        )
        assert request.headers["Accept"] == "text/plain"
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        assert request.content == b""
    first, second = served.asked
    assert first.headers["X-NetBox-Branch"] == "p9d46y7z"
    assert "X-NetBox-Branch" not in second.headers


@pytest.mark.parametrize("status", [400, 404, 500, 502, 302])
def test_a_render_answers_its_status_and_bytes_for_the_read_to_judge(status: int) -> None:
    """Every status but 401 and 403 is the read's to judge (renders.judge), its body as NetBox sent it."""
    body = NO_TEMPLATE.encode()

    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body, headers={"Content-Type": "text/plain; charset=utf-8"})

    with opened(Served(answer)) as conn:
        assert conn.render(BRANCH, 12) == Rendered(status, body, "text/plain; charset=utf-8")


@pytest.mark.parametrize("status", [401, 403])
def test_a_refused_token_is_the_transports_error_on_a_render(status: int) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"detail": f"Refused {request.headers['Authorization']}"})

    with opened(Served(refuse)) as conn, pytest.raises(NetBoxError) as raised:
        conn.render(BRANCH, 12)
    assert raised.value.status == status
    text = str(raised.value)
    assert text.startswith(f"rendering dcim.device 12 (branch b): HTTP {status}: NetBox refused the token")
    assert "FYLGJA_NETBOX_TOKEN" in text
    for quoted in ("Refused", TOKEN, "Bearer"):
        assert quoted not in text


def test_a_renders_refusal_holds_no_token_and_its_configuration_is_verbatim() -> None:
    """NetBox's words in a refusal are quoted in a finding, so the token, and each half of it, is replaced in them;
    a configuration, answered 200, is taken as NetBox rendered it."""
    key, secret = TOKEN.removeprefix("nbt_").split(".")
    echoed = f"UndefinedError: {TOKEN} {secret} {key}".encode()

    def answer(request: httpx.Request) -> httpx.Response:
        status = 500 if request.url.path.startswith("/api/dcim/devices/1/") else 200
        held = {"Content-Type": "text/html"} if status == 500 else {}
        return httpx.Response(status, content=echoed if status == 500 else b"set / \xc3\xa9\n", headers=held)

    with opened(Served(answer)) as conn:
        refused = conn.render(None, 1)
        rendered = conn.render(None, 2)
    assert refused == Rendered(500, b"UndefinedError: <redacted> <redacted> <redacted>", "text/html")
    assert rendered == Rendered(200, b"set / \xc3\xa9\n", None)


def test_a_renders_content_type_holds_no_token() -> None:
    """A render's content type is the one string of NetBox's a finding quotes beside a refusal's words
    (renders.judge), so the token, and each half of it, is replaced in it too, whatever the status."""
    key, secret = TOKEN.removeprefix("nbt_").split(".")
    echoed = f"text/x-{TOKEN}; key={key}; secret={secret}"

    def answer(request: httpx.Request) -> httpx.Response:
        status = 500 if request.url.path.startswith("/api/dcim/devices/1/") else 200
        return httpx.Response(status, content=b"x\n", headers={"Content-Type": echoed})

    with opened(Served(answer)) as conn:
        held = [conn.render(None, 1), conn.render(None, 2)]
    for rendered in held:
        assert rendered.content_type == "text/x-<redacted>; key=<redacted>; secret=<redacted>"
    judged = renders.judge(Device(2, "n2", 1), held[1], branch=None)
    assert isinstance(judged, Finding)
    assert judged.rule == "render.invalid"
    assert not any(part in judged.message for part in (TOKEN, key, secret))


def test_a_render_not_reached_is_an_error_of_no_status() -> None:
    def unreached(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"no route, having sent Authorization: Bearer {TOKEN}", request=request)

    with opened(Served(unreached)) as conn, pytest.raises(NetBoxError) as raised:
        conn.render(BRANCH, 12)
    assert raised.value.status is None
    assert "rendering dcim.device 12 (branch b)" in str(raised.value)
    assert TOKEN not in str(raised.value)


def test_a_redirect_is_refused_naming_its_path_alone() -> None:
    def moved(request: httpx.Request) -> httpx.Response:
        return httpx.Response(301, headers={"Location": "http://other.example/api/dcim/devices/?tag_id=4"})

    served = Served(moved)
    with opened(served) as conn, pytest.raises(NetBoxError) as raised:
        conn.devices(None, 4)
    assert raised.value.status == 301
    assert str(raised.value) == "reading dcim.device (main): HTTP 301: a redirect to /api/dcim/devices/"
    assert len(served.asked) == 1


def test_no_error_repr_cause_or_log_line_holds_the_token(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)

    def unreached(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"no route, having sent Authorization: Bearer {TOKEN}", request=request)

    with opened(Served(unreached)) as conn:
        with pytest.raises(NetBoxError) as raised:
            conn.ports(BRANCH, [1])
        held = repr(conn)
    with pytest.raises(NetBoxError) as at_connect:
        connect(ADDRESS, TOKEN, transport=httpx.MockTransport(unreached))
    for e in (raised.value, at_connect.value):
        assert e.status is None
        assert e.__cause__ is None and e.__context__ is None and e.__suppress_context__
        assert "ConnectError" in str(e) and "<redacted>" in str(e)
        for text in (str(e), repr(e)):
            assert TOKEN not in text
    assert "reading dcim.interface (branch b)" in str(raised.value)
    # A traceback can show each frame's locals: no frame between the call and the raise holds the token in one.
    frames = [entry.frame for entry in raised.traceback[1:]]
    assert [entry.name for entry in raised.traceback[1:]][-1] == "_send", "the walk is blind"
    held_locals = [(f.code.name, name) for f in frames for name, value in f.f_locals.items() if TOKEN in repr(value)]
    assert held_locals == []
    assert TOKEN not in held and HOST not in held
    assert TOKEN not in caplog.text


@pytest.mark.parametrize("token", ["", "two words", "line\n", "tökén"])
def test_a_token_that_is_no_header_value_is_refused_before_any_request(token: str) -> None:
    served = Served()
    with pytest.raises(InvalidToken):
        connect(ADDRESS, token, transport=httpx.MockTransport(served))
    assert served.requests == []
