"""The transport, the one module that speaks to Infrahub (D-083), over an `httpx.MockTransport` whose answers each test
builds: a count and edges of nodes, never an answer captured from Infrahub (D-034). It reads Infrahub's version once,
sends each document to the branch's path with `at` verbatim, pages every list to the total Infrahub answered, keeps
the status of a refusal with the branch and the time, and holds the token out of every error, repr and log line."""

from __future__ import annotations

import dataclasses
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fylgja_core.client import InvalidToken

from fylgja_infrahub import SUPPORTED, InfrahubError, connect, transport
from fylgja_infrahub.rows import (
    Artifact,
    Attribute,
    Branch,
    CableEnd,
    CableStamp,
    Connector,
    Content,
    Device,
    End,
    Event,
    Generated,
    Group,
    Kind,
    Listing,
    Port,
    Probe,
    Relationship,
    Schema,
    Stamp,
    Stamped,
    incomplete,
)
from fylgja_infrahub.transport import Infrahub

QUERIES = Path(__file__).resolve().parents[1] / "src" / "fylgja_infrahub" / "queries"
ADDRESS = "http://infrahub.example"
TOKEN = "Not-a.real_token~0+/9=="
"""A token as Infrahub's are: an RFC 6750 bearer token, whose characters a header carries."""
AT = "2026-11-09T10:00:00.123456+00:00"

Answer = Callable[[httpx.Request], httpx.Response]


class Served:
    """A fake Infrahub: `GET /api/info` answers `version`, or `info` where it is given, and every other request
    `answer`; each request is kept."""

    def __init__(self, answer: Answer | None = None, *, version: str = "1.11.11", info: Answer | None = None) -> None:
        self.answer = answer
        self.version = version
        self.info = info
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.path == "/api/info":
            if self.info is not None:
                return self.info(request)
            return httpx.Response(200, json={"deployment_id": "d", "version": self.version})
        assert self.answer is not None, f"no answer for {request.url}"
        return self.answer(request)

    @property
    def asked(self) -> list[httpx.Request]:
        """The requests after the version's."""
        return [request for request in self.requests if request.url.path != "/api/info"]


def opened(served: Served) -> Infrahub:
    return connect(ADDRESS, TOKEN, transport=httpx.MockTransport(served))


def page(root: str, count: int, nodes: list[dict[str, Any]]) -> httpx.Response:
    return httpx.Response(200, json={"data": {root: {"count": count, "edges": [{"node": node} for node in nodes]}}})


def ids(*names: str) -> list[dict[str, Any]]:
    return [{"id": name} for name in names]


def variables(request: httpx.Request) -> dict[str, Any]:
    found: dict[str, Any] = json.loads(request.content)["variables"]
    return found


def test_connect_reads_the_version(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="fylgja.infrahub")
    assert SUPPORTED == ("1.11.11",)
    with opened(Served()) as conn:
        assert (conn.version, conn.unverified) == ("1.11.11", None)
        assert repr(conn) == "Infrahub(version='1.11.11')", "the repr holds neither the address nor the token"
    assert [r for r in caplog.records if r.name == "fylgja.infrahub" and r.levelno >= logging.WARNING] == []

    served = Served(version="1.12.0")
    with opened(served) as conn:
        finding = conn.unverified
        assert finding is not None
        assert (finding.rule, finding.severity, finding.object) == ("infrahub.version.unverified", "warning", "1.12.0")
        assert "1.11.11" in finding.message
        assert conn.version == "1.12.0"
    assert [(r.method, r.url.path) for r in served.requests] == [("GET", "/api/info")]
    warned = [r for r in caplog.records if r.name == "fylgja.infrahub" and r.levelno >= logging.WARNING]
    assert [r.levelno for r in warned] == [logging.WARNING]
    assert "1.12.0" in warned[0].getMessage()


def test_connect_keeps_an_idle_connection_1_s(monkeypatch: pytest.MonkeyPatch) -> None:
    # Infrahub refused a request sent on a connection idle 2.0 s (design/verified-facts.md, "Infrahub 1.11.11").
    made: list[httpx.Limits | None] = []
    real = httpx.Client

    def client(*args: Any, **kwargs: Any) -> httpx.Client:
        made.append(kwargs.get("limits"))
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", client)
    opened(Served()).close()
    assert [limits.keepalive_expiry if limits is not None else None for limits in made] == [1.0]


def test_the_librarys_logger_has_a_null_handler() -> None:
    """The library gives its logger a `NullHandler`, as the logging HOWTO advises a library: so the version warning
    reaches no stream through Python's last resort where the program attached no handler, and the command prints it
    once, as its finding line (ruling P3-40)."""
    handlers = logging.getLogger("fylgja.infrahub").handlers
    assert any(type(handler) is logging.NullHandler for handler in handlers)


def test_a_query_goes_to_the_branchs_path_with_at_verbatim() -> None:
    served = Served(lambda request: page("DcimDevice", 0, []))
    asked = {"tag": "fylgja", "limit": 1, "offset": 0}
    with opened(served) as conn:
        assert conn.graphql("devices", asked, branch="a b/c", at=AT) == {"DcimDevice": {"count": 0, "edges": []}}
        conn.graphql("devices", asked, branch="main", at=None)
    pinned, unpinned = served.asked
    assert pinned.method == "POST"
    assert pinned.url.raw_path == b"/graphql/a%20b%2Fc?at=2026-11-09T10%3A00%3A00.123456%2B00%3A00"
    assert pinned.headers["X-INFRAHUB-KEY"] == TOKEN
    body = json.loads(pinned.content)
    assert body == {"query": (QUERIES / "devices.graphql").read_text(), "variables": asked, "operationName": "Devices"}
    assert (unpinned.method, unpinned.url.raw_path) == ("POST", b"/graphql/main")


def test_the_pager_reads_every_page_and_answers_the_count() -> None:
    every = [f"port-{i}" for i in range(250)]

    def answer(request: httpx.Request) -> httpx.Response:
        asked = variables(request)
        return page("InterfacePhysical", 250, ids(*every[asked["offset"] : asked["offset"] + asked["limit"]]))

    served = Served(answer)
    with opened(served) as conn:
        count, edges = conn.paged("ports", "InterfacePhysical", {"devices": ["d"]}, branch="main", at=AT)
    assert transport.PAGE == 100
    assert [(variables(r)["offset"], variables(r)["limit"], variables(r)["devices"]) for r in served.asked] == [
        (0, 100, ["d"]),
        (100, 100, ["d"]),
        (200, 100, ["d"]),
    ]
    assert (count, [edge["node"]["id"] for edge in edges]) == (250, every)


def test_the_pager_ends_on_a_list_short_of_its_count() -> None:
    answers = iter([page("DcimDevice", 3, ids("a", "b")), page("DcimDevice", 3, [])])
    served = Served(lambda request: next(answers))
    with opened(served) as conn:
        count, edges = conn.paged("devices", "DcimDevice", {"tag": "t"}, branch="main", at=None)
    assert [variables(r)["offset"] for r in served.asked] == [0, 2]
    assert (count, [edge["node"]["id"] for edge in edges]) == (3, ["a", "b"])


def test_the_pager_answers_the_largest_count_a_page_gave() -> None:
    answers = iter([page("DcimDevice", 3, ids("a", "b")), page("DcimDevice", 2, ids("c"))])
    served = Served(lambda request: next(answers))
    with opened(served) as conn:
        count, edges = conn.paged("devices", "DcimDevice", {"tag": "t"}, branch="main", at=None)
    assert [variables(r)["offset"] for r in served.asked] == [0, 2]
    assert (count, [edge["node"]["id"] for edge in edges]) == (3, ["a", "b", "c"])


def test_a_page_longer_than_its_count_ends_the_pager() -> None:
    served = Served(lambda request: page("DcimDevice", 1, ids("a", "b")))
    with opened(served) as conn:
        count, edges = conn.paged("devices", "DcimDevice", {"tag": "t"}, branch="main", at=None)
    assert len(served.asked) == 1
    assert (count, [edge["node"]["id"] for edge in edges]) == (1, ["a", "b"])


@pytest.mark.parametrize(
    "body",
    [{"errors": [{"message": "Branch: x not found."}]}, {"errors": ["Branch: x not found."]}],
    ids=["objects", "strings"],
)
def test_a_refusal_keeps_its_status_and_names_the_branch_and_the_time(body: dict[str, Any]) -> None:
    with opened(Served(lambda request: httpx.Response(404, json=body))) as conn, pytest.raises(InfrahubError) as raised:
        conn.devices("x", AT, "fylgja")
    assert raised.value.status == 404
    for held in ("Branch: x not found.", "branch x", AT, "HTTP 404"):
        assert held in str(raised.value)


@pytest.mark.parametrize("status", [401, 403])
def test_a_refused_token_is_named_and_nothing_is_quoted(status: int) -> None:
    body = {"data": None, "errors": [{"message": "Invalid token", "extensions": {"http_status": status}}]}
    served = Served(lambda request: httpx.Response(status, json=body))
    with opened(served) as conn, pytest.raises(InfrahubError) as raised:
        conn.devices("main", None, "fylgja")
    assert raised.value.status == status
    assert "FYLGJA_INFRAHUB_TOKEN" in str(raised.value)
    assert "branch main" in str(raised.value)
    assert "Invalid token" not in str(raised.value)


def test_a_token_infrahub_refuses_at_connect_is_named_and_nothing_is_quoted() -> None:
    """`GET /api/info` refuses a wrong token, HTTP 401, though it answers a request with none
    (design/verified-facts.md), so `connect` refuses it before any query (P3-15)."""
    body = {"data": None, "errors": [{"message": "Invalid token", "extensions": {"code": 401}}]}
    served = Served(info=lambda request: httpx.Response(401, json=body))
    with pytest.raises(InfrahubError) as raised:
        opened(served)
    assert raised.value.status == 401
    assert "reading Infrahub's version" in str(raised.value)
    assert "FYLGJA_INFRAHUB_TOKEN" in str(raised.value)
    assert "Invalid token" not in str(raised.value)
    assert TOKEN not in str(raised.value)
    assert [(r.method, r.url.path) for r in served.requests] == [("GET", "/api/info")]


def test_a_refusal_under_200_keeps_the_status_its_first_error_carries() -> None:
    """Infrahub refuses a selection the schema lacks under HTTP 200, each error carrying its own status at
    `extensions.http_status` (reading (a), design/verified-facts.md)."""
    body = {
        "data": None,
        "errors": [
            {"message": "Cannot query field 'x' on type 'DcimDevice'.", "extensions": {"http_status": 500}},
            {"message": "Cannot query field 'y' on type 'DcimDevice'.", "extensions": {"http_status": 422}},
        ],
    }
    with opened(Served(lambda request: httpx.Response(200, json=body))) as conn, pytest.raises(InfrahubError) as raised:
        conn.devices("main", AT, "fylgja")
    assert raised.value.status == 500
    for held in ("Cannot query field 'x'", "Cannot query field 'y'", "branch main", AT, "HTTP 200", "500"):
        assert held in str(raised.value)


def test_no_error_repr_cause_or_log_line_holds_the_token(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)

    def unreached(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"no route, having sent X-INFRAHUB-KEY: {TOKEN}", request=request)

    with opened(Served(unreached)) as conn:
        with pytest.raises(InfrahubError) as raised:
            conn.devices("main", AT, "fylgja")
        held = repr(conn)
    with pytest.raises(InfrahubError) as at_connect:
        connect(ADDRESS, TOKEN, transport=httpx.MockTransport(unreached))
    for e in (raised.value, at_connect.value):
        assert e.status is None
        assert e.__cause__ is None and e.__context__ is None and e.__suppress_context__
        assert "ConnectError" in str(e) and "<redacted>" in str(e)
        for text in (str(e), repr(e)):
            assert TOKEN not in text
    # A traceback can show each frame's locals: no frame between the call and the raise holds the token in one.
    frames = [entry.frame for entry in raised.traceback[1:]]
    assert [entry.name for entry in raised.traceback[1:]][-1] == "_send", "the walk is blind"
    held_locals = [(f.code.name, name) for f in frames for name, value in f.f_locals.items() if TOKEN in repr(value)]
    assert held_locals == []
    assert "branch main" in str(raised.value) and AT in str(raised.value)
    assert TOKEN not in held and "infrahub.example" not in held
    assert TOKEN not in caplog.text


@pytest.mark.parametrize("token", ["", "two words", "line\n", "tökén"])
def test_a_token_that_is_no_header_value_is_refused_before_any_request(token: str) -> None:
    served = Served()
    with pytest.raises(InvalidToken):
        connect(ADDRESS, token, transport=httpx.MockTransport(served))
    assert served.requests == []


SCHEMA = {
    "main": "5c4f2e",
    "nodes": [
        {
            "kind": "DcimDevice",
            "attributes": [
                {"name": "name", "kind": "Text", "optional": False, "choices": None},
                {
                    "name": "status",
                    "kind": "Dropdown",
                    "optional": True,
                    "choices": [{"name": "active", "label": "Active"}, {"name": "x"}],
                },
            ],
            "relationships": [
                {
                    "name": "platform",
                    "peer": "DcimPlatform",
                    "kind": "Attribute",
                    "cardinality": "one",
                    "optional": True,
                    "inherited": True,
                },
            ],
        }
    ],
    "generics": [
        {"kind": "DcimInterface", "attributes": [], "relationships": [], "used_by": ["InterfacePhysical", "Other"]}
    ],
    "namespaces": [],
    "profiles": [],
    "templates": [],
}


def test_the_schema_is_read_into_rows() -> None:
    served = Served(lambda request: httpx.Response(200, json=SCHEMA))
    with opened(served) as conn:
        schema = conn.schema("a b")
    (asked,) = served.asked
    assert (asked.method, asked.url.path, dict(asked.url.params)) == ("GET", "/api/schema", {"branch": "a b"})
    assert schema == Schema(
        "5c4f2e",
        {
            "DcimDevice": Kind(
                {"name": Attribute("Text", False), "status": Attribute("Dropdown", True, ("active", "x"))},
                {"platform": Relationship("DcimPlatform", "Attribute", "one", True)},
            )
        },
        {"DcimInterface": Kind({}, {}, ("InterfacePhysical", "Other"))},
    )


def test_a_schema_with_no_hash_is_an_error() -> None:
    hashless = {key: value for key, value in SCHEMA.items() if key != "main"}
    served = Served(lambda request: httpx.Response(200, json=hashless))
    with opened(served) as conn, pytest.raises(InfrahubError) as raised:
        conn.schema("b")
    assert raised.value.status == 200
    assert "branch b" in str(raised.value) and "hash" in str(raised.value)


DEVICES = [
    {
        "id": "d1",
        "name": {"value": "n1"},
        "platform": {"node": {"name": {"value": "SR Linux"}, "manufacturer": {"node": {"name": {"value": "Nokia"}}}}},
        "artifacts": {
            "count": 1,
            "edges": [
                {
                    "node": {
                        "id": "a1",
                        "status": {"value": "Ready"},
                        "checksum": {"value": "c1"},
                        "storage_id": {"value": "s1"},
                        "definition": {"node": {"artifact_name": {"value": "device-config"}}},
                    }
                }
            ],
        },
    },
    {"id": "d2", "name": {"value": "n2"}, "platform": {"node": None}, "artifacts": {"count": 2, "edges": []}},
]
PORTS = [
    {
        "id": "p1",
        "name": {"value": "ethernet-1/1"},
        "role": {"value": None},
        "status": {"value": "active"},
        "device": {"node": {"id": "d1"}},
        "connector": {
            "node": {
                "__typename": "DcimCable",
                "id": "c1",
                "label": {"value": "n1:ethernet-1/1|n2:ethernet-1/1"},
                "connected_endpoints": {
                    "count": 3,
                    "edges": [
                        {
                            "node": {
                                "__typename": "InterfacePhysical",
                                "id": "p1",
                                "name": {"value": "ethernet-1/1"},
                                "device": {"node": {"id": "d1"}},
                            }
                        },
                        {"node": {"__typename": "InterfaceVirtual", "id": "v1"}},
                    ],
                },
            }
        },
    },
    {
        "id": "p2",
        "name": {"value": "mgmt0"},
        "role": {"value": "management"},
        "status": {"value": "disabled"},
        "device": {"node": {"id": "d2"}},
        "connector": {"node": None},
    },
]


def test_the_devices_and_their_ports_are_read_into_rows() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        operation = json.loads(request.content)["operationName"]
        return page("DcimDevice", 2, DEVICES) if operation == "Devices" else page("InterfacePhysical", 2, PORTS)

    served = Served(answer)
    with opened(served) as conn:
        devices = conn.devices("main", AT, "fylgja")
        ports = conn.ports("main", AT, ["d1", "d2"])
        assert conn.ports("main", AT, []) == Listing("InterfacePhysical", 0, ())
    assert [(json.loads(r.content)["operationName"], variables(r)) for r in served.asked] == [
        ("Devices", {"tag": "fylgja", "limit": 100, "offset": 0}),
        ("Ports", {"devices": ["d1", "d2"], "limit": 100, "offset": 0}),
    ]
    artifact = Artifact("a1", "device-config", "Ready", "c1", "s1")
    assert devices == Listing(
        "DcimDevice",
        2,
        (
            Device("d1", "n1", "SR Linux", "Nokia", Listing("n1.artifacts", 1, (artifact,))),
            Device("d2", "n2", None, None, Listing("n2.artifacts", 2, ())),
        ),
    )
    label = "n1:ethernet-1/1|n2:ethernet-1/1"
    ends = (End("p1", "InterfacePhysical", "d1", "ethernet-1/1"), End("v1", "InterfaceVirtual", None, None))
    cable = Connector("c1", "DcimCable", label, Listing(f"{label}.connected_endpoints", 3, ends))
    assert ports == Listing(
        "InterfacePhysical",
        2,
        (
            Port("p1", "d1", "ethernet-1/1", None, "active", cable),
            Port("p2", "d2", "mgmt0", "management", "disabled", None),
        ),
    )


def probe_node(name: str, gateway: str | None) -> dict[str, Any]:
    """A `FylgjaProbe` as Infrahub answers it: each attribute's value, `a_gateway` null where it is None."""
    values = {
        "name": name,
        "format": "ping",
        "a_device": "n1",
        "a_interface": "ethernet-1/10",
        "a_address": "192.0.2.2/24",
        "a_gateway": gateway,
        "b_device": "n1",
        "b_interface": "ethernet-1/11",
        "b_address": "198.51.100.2/24",
        "b_gateway": "198.51.100.1",
    }
    return {"id": f"id-{name}", **{field: {"value": value} for field, value in values.items()}}


def test_the_probes_are_read_into_rows() -> None:
    served = Served(lambda request: page("FylgjaProbe", 1, [probe_node("p1", "192.0.2.1")]))
    with opened(served) as conn:
        probes = conn.probes("b", AT)
    [asked] = served.asked
    assert (operation(asked), variables(asked)) == ("Probes", {"limit": 100, "offset": 0})
    assert (asked.url.path, asked.url.params["at"]) == ("/graphql/b", AT)
    a = ("n1", "ethernet-1/10", "192.0.2.2/24", "192.0.2.1")
    b = ("n1", "ethernet-1/11", "198.51.100.2/24", "198.51.100.1")
    assert probes == Listing("FylgjaProbe", 1, (Probe("id-p1", "p1", "ping", a, b),))

    served = Served(lambda request: page("FylgjaProbe", 1, [probe_node("p1", None)]))
    with opened(served) as conn:
        nulled = conn.probes("b", AT)
    assert nulled.items == (Probe("id-p1", "p1", "ping", (*a[:3], None), b),), "a null is the read's to judge"


def test_the_probes_stamps_are_read_into_rows() -> None:
    edges: list[dict[str, Any]] = [
        {"node_metadata": meta(), "node": {"id": "id-p1"}},
        {"node_metadata": None, "node": {"id": "id-p2"}},
    ]
    served = Served(lambda request: edged("FylgjaProbe", 2, edges))
    with opened(served) as conn:
        stamps = conn.probe_stamps("b", None)
    [asked] = served.asked
    assert (operation(asked), variables(asked)) == ("ProbeStamps", {"limit": 100, "offset": 0})
    assert (asked.url.path, "at" in asked.url.params) == ("/graphql/b", False)
    assert stamps == Listing(
        "FylgjaProbe", 2, (("id-p1", Stamp(T1, "acct-admin", MADE)), ("id-p2", Stamp(None, None, None)))
    )


def test_a_probes_stamp_with_no_id_is_an_error_naming_a_probe() -> None:
    served = Served(lambda request: edged("FylgjaProbe", 1, [{"node_metadata": meta(), "node": {"id": ""}}]))
    with opened(served) as conn, pytest.raises(InfrahubError) as raised:
        conn.probe_stamps("b", None)
    assert raised.value.status == 200
    assert "a FylgjaProbe with no id" in str(raised.value)


def test_an_answer_that_is_no_row_is_an_error() -> None:
    nameless = [{key: value for key, value in DEVICES[0].items() if key != "name"}]
    served = Served(lambda request: page("DcimDevice", 1, nameless))
    with opened(served) as conn, pytest.raises(InfrahubError) as raised:
        conn.devices("main", AT, "fylgja")
    assert raised.value.status == 200
    for held in ("branch main", AT, "name"):
        assert held in str(raised.value)


def test_the_content_is_read_by_its_storage_id_alone_whatever_the_status() -> None:
    """`GET /api/storage/object/<storage_id>` carries no branch and no time: a storage id names one object, which a
    read at a past time still finds, and every status is the read's to judge (design/verified-facts.md, "The stored
    bytes, with a token and without", "An artifact at a past time")."""
    bodies = {b"/api/storage/object/s%2F1": httpx.Response(200, content=b"set / x\n")}
    served = Served(lambda request: bodies.get(request.url.raw_path, httpx.Response(404, content=b"not found")))
    with opened(served) as conn:
        assert conn.content("main", AT, "s/1") == Content(200, b"set / x\n")
        assert conn.content("a b", None, "s2") == Content(404, b"not found")
    first, second = served.asked
    assert (first.method, first.url.raw_path, first.content) == ("GET", b"/api/storage/object/s%2F1", b"")
    assert (second.method, second.url.raw_path) == ("GET", b"/api/storage/object/s2")
    assert first.headers["X-INFRAHUB-KEY"] == TOKEN


def test_content_not_reached_is_an_error_naming_the_read_and_never_the_token() -> None:
    def unreached(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"no route, having sent X-INFRAHUB-KEY: {TOKEN}", request=request)

    with opened(Served(unreached)) as conn, pytest.raises(InfrahubError) as raised:
        conn.content("main", AT, "s1")
    assert raised.value.status is None
    assert raised.value.__cause__ is None and raised.value.__suppress_context__
    for held in ("s1", "branch main", AT, "<redacted>"):
        assert held in str(raised.value)
    assert TOKEN not in str(raised.value) and TOKEN not in repr(raised.value)


T1 = "2026-11-09T10:00:01.000000+00:00"
MADE = "2026-11-09T09:00:00.000000+00:00"
BRANCHED = "2026-11-09T09:00:00.000000Z"


def meta(updated_at: str = T1, by: str = "acct-admin", created_at: str = MADE) -> dict[str, Any]:
    """A `node_metadata` as Infrahub answers it on an edge."""
    return {"updated_at": updated_at, "updated_by": {"id": by}, "created_at": created_at}


def generated(found: str, updated_at: str | None, query: dict[str, Any] | None) -> dict[str, Any]:
    """An artifact as the stamps read selects it: its id, its checksum's stamp, its definition's name and its query."""
    definition = {"artifact_name": {"value": "device-config"}, "transformation": {"node": query}}
    return {"node": {"id": found, "checksum": {"updated_at": updated_at}, "definition": {"node": definition}}}


def addressed(found: str) -> dict[str, Any]:
    """An interface's `ip_addresses` holding the one address `found`, written as `__system__`."""
    return {"count": 1, "edges": [{"node_metadata": meta(by="__system__"), "node": {"id": found}}]}


STAMPED: list[dict[str, Any]] = [
    {
        "node_metadata": meta(),
        "node": {
            "id": "d1",
            "name": {"value": "n1"},
            "platform": {
                "node_metadata": meta(),
                "node": {
                    "id": "p1",
                    "name": {"updated_at": MADE},
                    "manufacturer": {
                        "node_metadata": meta(by="__system__"),
                        "node": {"id": "m1", "name": {"updated_at": T1}},
                    },
                },
            },
            "interfaces": {
                "count": 3,
                "edges": [
                    {"node_metadata": meta(), "node": {"id": "i1", "ip_addresses": addressed("a1")}},
                    {"node_metadata": meta(), "node": {"id": "v1", "ip_addresses": addressed("a2")}},
                    {"node_metadata": meta(), "node": {"id": "x1"}},
                ],
            },
            "artifacts": {"count": 1, "edges": [generated("r1", T1, {"query": {"node": {"id": "q1"}}})]},
        },
    },
    {
        "node_metadata": {"updated_at": T1, "updated_by": None, "created_at": None},
        "node": {
            "id": "d2",
            "name": {"value": "n2"},
            "platform": {"node_metadata": None, "node": None},
            "interfaces": {"count": 0, "edges": []},
            "artifacts": {"count": 1, "edges": [generated("r2", None, None)]},
        },
    },
    {
        "node_metadata": meta(),
        "node": {
            "id": "d3",
            "name": {"value": "n3"},
            "platform": {
                "node_metadata": meta(),
                "node": {
                    "id": "p3",
                    "name": None,
                    "manufacturer": {"node_metadata": meta(), "node": {"id": "m3", "name": {"updated_at": T1}}},
                },
            },
            "interfaces": {"count": 0, "edges": []},
            "artifacts": {"count": 0, "edges": []},
        },
    },
]
"""Three devices' stamps: `n1` with a port and a virtual interface, each holding an address under `InterfaceLayer3`'s
`ip_addresses`, and an interface of no layer 3, which answers none, and its platform's and manufacturer's `name` stamps;
`n2` with no platform and no stamps but its own; and `n3`, whose platform answers no `name` stamp and its manufacturer
one, each kept in its own field (P3-46)."""


def operation(request: httpx.Request) -> str:
    found: str = json.loads(request.content)["operationName"]
    return found


def edged(root: str, count: int, edges: list[dict[str, Any]]) -> httpx.Response:
    """A page of a list whose edges each carry their `node_metadata` beside their node."""
    return httpx.Response(200, json={"data": {root: {"count": count, "edges": edges}}})


def test_the_stamps_are_read_into_rows() -> None:
    served = Served(lambda request: edged("DcimDevice", 3, STAMPED))
    with opened(served) as conn:
        stamps = conn.stamps("main", AT, "fylgja")
    (asked,) = served.asked
    assert (operation(asked), variables(asked)) == ("Stamps", {"tag": "fylgja", "limit": 100, "offset": 0})
    assert asked.url.raw_path == b"/graphql/main?at=2026-11-09T10%3A00%3A00.123456%2B00%3A00"
    admin, system = Stamp(T1, "acct-admin", MADE), Stamp(T1, "__system__", MADE)
    assert stamps == Listing(
        "DcimDevice",
        3,
        (
            Stamped(
                "d1",
                "n1",
                ("d1", "p1", "m1", "i1", "v1", "x1", "a1", "a2"),
                admin,
                (admin, system),
                MADE,
                T1,
                Listing("n1.interfaces", 3, (("i1", admin), ("v1", admin), ("x1", admin))),
                Listing("n1.ip_addresses", 2, (("i1", "a1", system), ("v1", "a2", system))),
                Listing("n1.artifacts", 1, (Generated("r1", "device-config", T1, "q1"),)),
            ),
            Stamped(
                "d2",
                "n2",
                ("d2",),
                Stamp(T1, None, None),
                (),
                None,
                None,
                Listing("n2.interfaces", 0, ()),
                Listing("n2.ip_addresses", 0, ()),
                Listing("n2.artifacts", 1, (Generated("r2", "device-config", None, None),)),
            ),
            Stamped(
                "d3",
                "n3",
                ("d3", "p3", "m3"),
                admin,
                (admin, admin),
                None,
                T1,
                Listing("n3.interfaces", 0, ()),
                Listing("n3.ip_addresses", 0, ()),
                Listing("n3.artifacts", 0, ()),
            ),
        ),
    )


def end(found: str, name_at: str, device: str, device_name_at: str) -> dict[str, Any]:
    """A cable's end as the cable stamps read selects it: an interface by its id with its name's stamp, and its device
    with its own."""
    held = {"id": device, "name": {"updated_at": device_name_at}}
    return {"node": {"id": found, "name": {"updated_at": name_at}, "device": {"node": held}}}


CABLE: dict[str, Any] = {
    "id": "i1",
    "device": {"node": {"id": "d1"}},
    "connector": {
        "node_metadata": meta(),
        "node": {
            "id": "c1",
            "label": {"value": "l1"},
            "connected_endpoints": {
                "count": 3,
                "edges": [end("i1", T1, "d1", MADE), end("i2", MADE, "d2", T1), {"node": {"id": "e3"}}],
            },
        },
    },
}
"""A cabled port: its cable's ends, the near one, the far one and one that is no interface, whose names the far end's
stamps are."""


def test_the_cables_groups_and_branch_are_read_into_rows() -> None:
    def answer(request: httpx.Request) -> httpx.Response:
        if operation(request) == "CableStamps":
            return page("InterfacePhysical", 1, [CABLE])
        if operation(request) == "QueryGroups":
            edge = {"node_metadata": {"created_by": {"id": "acct-own"}}, "node": {"id": "g1"}}
            return edged("CoreGraphQLQueryGroup", 1, [edge])
        listed = [{"name": "b-other", "branched_from": T1}, {"name": "b", "branched_from": BRANCHED}]
        return httpx.Response(200, json={"data": {"Branch": listed}})

    served = Served(answer)
    with opened(served) as conn:
        cables = conn.cable_stamps("b", AT, ["d1"])
        groups = conn.groups("b", AT, ["q1"])
        made = conn.branch("b")
    assert [(operation(r), variables(r)) for r in served.asked] == [
        ("CableStamps", {"devices": ["d1"], "limit": 100, "offset": 0}),
        ("QueryGroups", {"queries": ["q1"], "limit": 100, "offset": 0}),
        ("BranchPoint", {"name": "b"}),
    ]
    assert [r.url.raw_path for r in served.asked][2] == b"/graphql/b"
    ends = (CableEnd("i1", T1, "d1", MADE), CableEnd("i2", MADE, "d2", T1), CableEnd("e3", None, None, None))
    cable = CableStamp("c1", "i1", "d1", Stamp(T1, "acct-admin", MADE), Listing("l1.connected_endpoints", 3, ends))
    assert cables == Listing("InterfacePhysical.connector", 1, (cable,))
    assert groups == Listing("CoreGraphQLQueryGroup", 1, (Group("g1", "acct-own"),))
    assert made == Branch("b", BRANCHED)


def test_with_no_device_or_query_nothing_is_sent() -> None:
    served = Served()
    with opened(served) as conn:
        assert conn.cable_stamps("main", AT, []) == Listing("InterfacePhysical.connector", 0, ())
        assert conn.groups("main", AT, []) == Listing("CoreGraphQLQueryGroup", 0, ())
    assert served.asked == []


def test_a_branch_infrahub_does_not_list_is_an_error() -> None:
    served = Served(lambda request: httpx.Response(200, json={"data": {"Branch": []}}))
    with opened(served) as conn, pytest.raises(InfrahubError) as raised:
        conn.branch("gone")
    assert raised.value.status == 200
    assert "branch gone" in str(raised.value)


def logged(i: int, *, typename: str = "NodeMutatedEvent") -> dict[str, Any]:
    """The `i`th newest event of a log of events a second apart, the newest at 10:59:59."""
    node: dict[str, Any] = {
        "__typename": typename,
        "id": f"e{i}",
        "event": "infrahub.node.updated",
        "occurred_at": f"2026-11-09T10:{59 - i // 60:02d}:{59 - i % 60:02d}.000000+00:00",
        "account_id": "acct-admin",
        "branch": "b",
        "primary_node": {"id": "d1", "kind": "DcimDevice"},
        "related_nodes": [{"id": "x1"}],
    }
    if typename == "NodeMutatedEvent":
        node |= {"attributes": [{"name": "description"}], "relationships": [{"name": "tags", "peer": {"id": "t1"}}]}
    return node


def test_the_events_are_read_into_rows() -> None:
    unnamed = {"primary_node": None, "account_id": None}
    nodes = [logged(0), logged(1, typename="GroupEvent") | unnamed, logged(2) | {"branch": "main"}]
    served = Served(lambda request: page("InfrahubEvent", 3, nodes))
    with opened(served) as conn:
        events = conn.events("b", ("b", "main"), BRANCHED, None)
    (asked,) = served.asked
    assert asked.url.raw_path == b"/graphql/b"
    asked_for = {"branches": ["b", "main"], "since": BRANCHED, "limit": 50, "offset": 0}
    assert (operation(asked), variables(asked)) == ("Events", asked_for)
    first = Event(
        "e0",
        "infrahub.node.updated",
        "2026-11-09T10:59:59.000000+00:00",
        True,
        "DcimDevice",
        "d1",
        "acct-admin",
        ("description",),
        (("tags", "t1"),),
        ("x1",),
        "b",
    )
    second = "2026-11-09T10:59:58.000000+00:00"
    group = Event("e1", "infrahub.node.updated", second, False, None, None, None, (), (), ("x1",), "b")
    third = dataclasses.replace(first, id="e2", occurred_at="2026-11-09T10:59:57.000000+00:00", branch="main")
    assert events == Listing("InfrahubEvent", 3, (first, group, third))


@pytest.mark.parametrize("branch", [None, "", 7, "absent"], ids=["null", "empty", "no string", "absent"])
def test_an_event_with_no_branch_is_an_error(branch: object) -> None:
    """Which log holds an event places it against a branch's `branched_from`, so an event Infrahub answers with no
    branch is a fault of its answer, refused as one with no `event` or no `occurred_at` is, never kept to count past
    the branch point."""
    node = logged(0)
    if branch == "absent":
        del node["branch"]
    else:
        node["branch"] = branch
    served = Served(lambda request: page("InfrahubEvent", 1, [node]))
    with opened(served) as conn, pytest.raises(InfrahubError) as raised:
        conn.events("b", ("b", "main"), BRANCHED, None)
    assert raised.value.status == 200
    for held in ("no branch", "branch b"):
        assert held in str(raised.value)


def test_the_events_are_paged_down_to_the_first_not_later_than_the_floor() -> None:
    log = [logged(i) for i in range(120)]

    def answer(request: httpx.Request) -> httpx.Response:
        asked = variables(request)
        return page("InfrahubEvent", 120, log[asked["offset"] : asked["offset"] + asked["limit"]])

    served = Served(answer)
    with opened(served) as conn:
        floor = conn.events("b", ("b",), BRANCHED, log[70]["occurred_at"])
        whole = conn.events("b", ("b",), BRANCHED, None)
    assert transport.EVENTS_PAGE == 50
    assert [variables(r)["offset"] for r in served.asked] == [0, 50, 0, 50, 100]
    assert (floor.count, [e.id for e in floor.items]) == (100, [f"e{i}" for i in range(100)])
    assert (whole.count, len(whole.items)) == (120, 120)
    assert incomplete(floor, branch="b", at=None) is None


def test_an_event_answered_twice_as_the_log_grows_is_kept_once() -> None:
    """The log is read newest first and grows while it is paged, so an event comes back on the next page and none is
    missed: it is kept once, and the pages are whole."""
    log = [logged(i) for i in range(1, 80)]
    pages = iter([page("InfrahubEvent", 79, log[:50]), page("InfrahubEvent", 80, log[49:79])])
    served = Served(lambda request: next(pages))
    with opened(served) as conn:
        events = conn.events("b", ("b",), BRANCHED, None)
    assert [variables(r)["offset"] for r in served.asked] == [0, 50]
    assert [e.id for e in events.items] == [f"e{i}" for i in range(1, 80)]
    assert incomplete(events, branch="b", at=None) is None


def test_a_short_page_of_events_is_incomplete() -> None:
    served = Served(lambda request: page("InfrahubEvent", 3, [logged(0), logged(1)]))
    with opened(served) as conn:
        events = conn.events("b", ("b",), BRANCHED, None)
    assert len(served.asked) == 1
    finding = incomplete(events, branch="b", at=None)
    assert finding is not None
    assert (finding.rule, finding.object) == ("read.incomplete", "InfrahubEvent")
    assert "counted 3" in finding.message and "answered 2" in finding.message


CABLED = {**CABLE, "connector": {**CABLE["connector"], "node_metadata": meta(created_at="yesterday")}}
UNTIMED_END = {"count": 1, "edges": [end("i2", T1, "d2", "yesterday")]}
FAR = {
    **CABLE,
    "connector": {**CABLE["connector"], "node": {**CABLE["connector"]["node"], "connected_endpoints": UNTIMED_END}},
}
MAIN = {"data": {"Branch": [{"name": "main", "branched_from": "yesterday"}]}}
UNTIMED: dict[str, tuple[Answer, Callable[[Infrahub], object]]] = {
    "a device's": (
        lambda request: edged("DcimDevice", 1, [{**STAMPED[0], "node_metadata": meta("yesterday")}]),
        lambda conn: conn.stamps("main", AT, "fylgja"),
    ),
    "a cable's": (
        lambda request: page("InterfacePhysical", 1, [CABLED]),
        lambda conn: conn.cable_stamps("main", AT, ["d1"]),
    ),
    "a far device's name's": (
        lambda request: page("InterfacePhysical", 1, [FAR]),
        lambda conn: conn.cable_stamps("main", AT, ["d1"]),
    ),
    "an event's": (
        lambda request: page("InfrahubEvent", 1, [logged(0) | {"occurred_at": "yesterday"}]),
        lambda conn: conn.events("main", ("main",), BRANCHED, None),
    ),
    "a branch's": (
        lambda request: httpx.Response(200, json=MAIN),
        lambda conn: conn.branch("main"),
    ),
}


@pytest.mark.parametrize("stamp", list(UNTIMED))
def test_a_stamp_that_is_no_time_is_an_error_and_no_finding(stamp: str) -> None:
    """A stamp is compared and never sent, so one that is no time is a fault of Infrahub's answer, refused where it is
    read into a row."""
    answer, call = UNTIMED[stamp]
    with opened(Served(answer)) as conn, pytest.raises(InfrahubError) as raised:
        call(conn)
    assert raised.value.status == 200
    for held in ("'yesterday'", "branch main"):
        assert held in str(raised.value)
