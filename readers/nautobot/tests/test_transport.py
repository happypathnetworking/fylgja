"""The transport, the one module that speaks to Nautobot (D-118, D-096), over an `httpx.MockTransport` whose answers
each test builds: a REST list of `count` and `results`, never an answer captured from Nautobot (D-034). It reads
Nautobot's version and Golden Config's once, sends the token as `Token`, pages every list to the `count` Nautobot
answered and never by its `next`, asks ids in batches within the request bound and `IDS`, holds each row to what was
asked, keeps the status of a refusal with Nautobot's words, and holds the token out of every error, repr and log
line."""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Any

import httpx
import pytest
from fylgja_core.client import InvalidToken

from fylgja_nautobot import SUPPORTED, Nautobot, NautobotError, connect, redact, transport
from fylgja_nautobot.rows import (
    Cable,
    Change,
    Context,
    Device,
    End,
    Group,
    Listing,
    Manufacturer,
    Platform,
    Port,
    Rendered,
    Repository,
    Setting,
    Source,
    Tag,
)
from fylgja_nautobot.transport import named

HOST = "nautobot.example"
ADDRESS = f"http://{HOST}"
TOKEN = "0123456789abcdef0123456789abcdef01234567"
"""A token of Nautobot's shape, 40 lowercase hex characters, that no Nautobot made."""

Answer = Callable[[httpx.Request], httpx.Response]


def uid(n: int) -> str:
    """A UUID of Nautobot's form, numbered `n`."""
    return f"00000000-0000-4000-8000-{n:012d}"


TAG = Tag(uid(4), "fylgja")


class Served:
    """A fake Nautobot: `GET /api/status/` answers `status`, or `info` where it is given, and every other request
    `answer`; each request is kept."""

    def __init__(
        self,
        answer: Answer | None = None,
        *,
        version: str = "3.2.8",
        apps: dict[str, str] | None = None,
        info: Answer | None = None,
    ) -> None:
        self.answer = answer
        held = {"nautobot_golden_config": "3.0.8", "nautobot_plugin_nornir": "3.4.0"} if apps is None else apps
        self.status = {"nautobot-version": version, "nautobot-apps": held, "plugins": held}
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


def opened(served: Served) -> Nautobot:
    return connect(ADDRESS, TOKEN, transport=httpx.MockTransport(served))


def page(count: int, results: list[dict[str, Any]], *, after: str | None = None) -> httpx.Response:
    """A REST list's page: `count`, `results`, and a `next` where `after` is given."""
    return httpx.Response(200, json={"count": count, "next": after, "previous": None, "results": results})


def numbers(request: httpx.Request, name: str) -> list[int]:
    return [int(value) for value in request.url.params.get_list(name)]


def offsets(served: Served) -> list[tuple[int, int]]:
    return [(numbers(r, "offset")[0], numbers(r, "limit")[0]) for r in served.asked]


def related(id: str, kind: str) -> dict[str, Any]:
    """A related object as Nautobot answers one at the default depth."""
    return {"id": id, "object_type": kind, "url": f"{ADDRESS}/api/x/{id}/"}


def tag_row(id: str, name: str) -> dict[str, Any]:
    return {"id": id, "object_type": "extras.tag", "name": name, "color": "9e9e9e"}


def device_row(id: str, name: str | None, *, tags: list[str], platform: str | None = uid(1)) -> dict[str, Any]:
    return {
        "id": id,
        "name": name,
        "platform": related(platform, "dcim.platform") if platform is not None else None,
        "tags": [related(tag, "extras.tag") for tag in tags],
    }


def platform_row(id: str, name: str, manufacturer: str | None) -> dict[str, Any]:
    held = related(manufacturer, "dcim.manufacturer") if manufacturer is not None else None
    return {"id": id, "name": name, "manufacturer": held, "network_driver": "nokia_srl"}


def manufacturer_row(id: str, name: str) -> dict[str, Any]:
    return {"id": id, "name": name}


def port_row(
    id: str, device: str, name: str, *, cable: str | None = None, mgmt_only: bool = False, kind: str = "1000base-t"
) -> dict[str, Any]:
    return {
        "id": id,
        "device": related(device, "dcim.device"),
        "name": name,
        "type": {"value": kind, "label": kind},
        "enabled": True,
        "mgmt_only": mgmt_only,
        "cable": related(cable, "dcim.cable") if cable is not None else None,
    }


def end_row(kind: str, id: str) -> dict[str, Any]:
    return related(id, kind)


def cable_row(id: str, label: str, lanes: Mapping[str, dict[str, Any] | None]) -> dict[str, Any]:
    return {"id": id, "label": label, "terminations": lanes, "total_lanes": 1}


def change_row(id: str, time: str) -> dict[str, Any]:
    """A changelog row, as `?limit=1` answers the newest, its `object_data` left out."""
    return {
        "id": id,
        "object_type": "extras.objectchange",
        "action": {"value": "update", "label": "Updated"},
        "changed_object_type": "dcim.interface",
        "time": time,
        "request_id": uid(99),
    }


def setting_row(id: str, name: str, weight: int, repository: str | None, group: str) -> dict[str, Any]:
    """A Golden Config setting at the default depth: its repository, query and group each a related object."""
    held = related(repository, "extras.gitrepository") if repository is not None else None
    return {
        "id": id,
        "object_type": "nautobot_golden_config.goldenconfigsetting",
        "name": name,
        "slug": name.lower(),
        "weight": weight,
        "jinja_path_template": "{{ obj.platform.network_driver }}.j2",
        "jinja_repository": held,
        "sot_agg_query": related(uid(98), "extras.graphqlquery"),
        "dynamic_group": related(group, "extras.dynamicgroup"),
    }


def repository_row(id: str, name: str, head: str) -> dict[str, Any]:
    return {"id": id, "object_type": "extras.gitrepository", "name": name, "branch": "main", "current_head": head}


def group_row(id: str, name: str, kind: str, filter: object) -> dict[str, Any]:
    """A dynamic group at the default depth, as Nautobot answered the setting's (design/verified-facts.md)."""
    return {
        "id": id,
        "object_type": "extras.dynamicgroup",
        "name": name,
        "group_type": kind,
        "filter": filter,
        "content_type": "dcim.device",
        "tenant": None,
    }


def association_row(id: str, group: str, device: str, *, kind: str = "dcim.device") -> dict[str, Any]:
    """A stored member of a dynamic group, as `static-group-associations/?dynamic_group=` answered one."""
    return {
        "id": id,
        "object_type": "extras.staticgroupassociation",
        "associated_object_type": kind,
        "associated_object_id": device,
        "associated_object": related(device, kind),
        "dynamic_group": related(group, "extras.dynamicgroup"),
    }


def context_row(id: str, name: str, *, active: bool = False, data: object = None) -> dict[str, Any]:
    """A configuration context at the default depth: its `is_active` and its `data`, whatever JSON."""
    return {
        "id": id,
        "object_type": "extras.configcontext",
        "name": name,
        "weight": 1000,
        "is_active": active,
        "data": {"probes_version": "1", "probes": []} if data is None else data,
    }


HEAD = "0123456789abcdef0123456789abcdef01234567"
"""A commit of Git's form, 40 lowercase hex characters."""


def warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "fylgja.nautobot" and r.levelno >= logging.WARNING]


def test_connect_reads_both_versions(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="fylgja.nautobot")
    assert SUPPORTED == (("3.2.8", "3.0.8"),)
    served = Served()
    with opened(served) as conn:
        assert (conn.version, conn.golden_config, conn.unverified) == ("3.2.8", "3.0.8", None)
        assert repr(conn) == "Nautobot(version='3.2.8', golden_config='3.0.8')", "the repr holds the versions alone"
    assert [(r.method, r.url.path) for r in served.requests] == [("GET", "/api/status/")]
    assert warnings(caplog) == []

    for version, apps, unverified in [
        ("3.2.9", {"nautobot_golden_config": "3.0.8"}, "3.2.9/3.0.8"),
        ("3.2.8", {"nautobot_golden_config": "3.1.0"}, "3.2.8/3.1.0"),
        ("3.2.8", {}, "3.2.8/none"),
    ]:
        caplog.clear()
        with opened(Served(version=version, apps=apps)) as conn:
            finding = conn.unverified
            assert finding is not None
            assert (finding.rule, finding.severity) == (transport.RULE_UNVERIFIED, "warning")
            assert finding.object == unverified
            assert "3.2.8" in finding.message and "3.0.8" in finding.message
            assert conn.version == version
            assert conn.golden_config == apps.get("nautobot_golden_config")
        warned = warnings(caplog)
        assert [r.levelno for r in warned] == [logging.WARNING]
        assert warned[0].getMessage() == finding.message
    assert transport.RULE_UNVERIFIED == "nautobot.version.unverified"


def test_golden_config_is_read_from_the_apps_alone() -> None:
    """`nautobot-apps` names the installed apps; `plugins` is not read."""
    status = {"nautobot-version": "3.2.8", "nautobot-apps": {}, "plugins": {"nautobot_golden_config": "3.0.8"}}
    with opened(Served(info=lambda request: httpx.Response(200, json=status))) as conn:
        assert conn.golden_config is None


def answering(status: int, body: object) -> Answer:
    """An answer of `status` with `body` as JSON, to every request."""

    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    return answer


@pytest.mark.parametrize(
    "body",
    [
        {"nautobot-apps": {}},
        {"nautobot-version": "", "nautobot-apps": {}},
        {"nautobot-version": "3.2.8"},
        {"nautobot-version": "3.2.8", "nautobot-apps": []},
        [],
    ],
    ids=["no version", "an empty version", "no apps", "apps no mapping", "no object"],
)
def test_a_status_with_no_version_or_no_apps_is_an_error(body: object) -> None:
    with pytest.raises(NautobotError) as raised:
        opened(Served(info=answering(200, body)))
    assert raised.value.status == 200
    assert str(raised.value).startswith("reading Nautobot's version: HTTP 200: answered no ")


def test_nautobot_is_a_source() -> None:
    """mypy holds the transport's `Nautobot` to `rows.Source`, which the read is typed against."""
    with opened(Served()) as conn:
        source: Source = conn
        assert source.version == "3.2.8"


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


def test_the_token_is_sent_as_token() -> None:
    served = Served(lambda request: page(1, [port_row(uid(10), uid(1), "ethernet-1/1")]))
    with opened(served) as conn:
        conn.ports([uid(1)])
    assert len(served.requests) == 2
    for request in served.requests:
        assert request.headers["Authorization"] == f"Token {TOKEN}"
        assert "Bearer" not in request.headers["Authorization"]


def test_each_list_is_asked_by_its_filter_and_read_into_rows() -> None:
    a, b, front = uid(10), uid(13), uid(12)
    answers = {
        "/api/extras/tags/": page(1, [tag_row(TAG.id, "fylgja")]),
        "/api/dcim/devices/": page(
            2,
            [
                device_row(uid(1), "n1", tags=[uid(2), TAG.id]),
                device_row(uid(2), None, tags=[TAG.id], platform=None),
            ],
        ),
        "/api/dcim/platforms/": page(
            2, [platform_row(uid(1), "SR Linux", uid(7)), platform_row(uid(3), "EOS", None)]
        ),
        "/api/dcim/manufacturers/": page(1, [manufacturer_row(uid(7), "Nokia")]),
        "/api/dcim/interfaces/": page(
            2,
            [
                port_row(a, uid(1), "ethernet-1/1", cable=uid(5)),
                port_row(uid(11), uid(2), "lag1", mgmt_only=True, kind="lag"),
            ],
        ),
        "/api/dcim/cables/": page(
            1,
            [
                cable_row(
                    uid(5),
                    "",
                    {
                        "b2": end_row("dcim.interface", b),
                        "a1": end_row("dcim.interface", a),
                        "b1": end_row("dcim.frontport", front),
                    },
                )
            ],
        ),
    }
    served = Served(lambda request: answers[request.url.path])
    with opened(served) as conn:
        assert conn.tags("fylgja") == Listing("extras.tag", 1, (TAG,))
        assert conn.devices(TAG) == Listing(
            "dcim.device", 2, (Device(uid(1), "n1", uid(1)), Device(uid(2), None, None))
        )
        assert conn.platforms([uid(1), uid(3)]) == Listing(
            "dcim.platform", 2, (Platform(uid(1), "SR Linux", uid(7)), Platform(uid(3), "EOS", None))
        )
        assert conn.manufacturers([uid(7)]) == Listing("dcim.manufacturer", 1, (Manufacturer(uid(7), "Nokia"),))
        port = Port(a, uid(1), "ethernet-1/1", "1000base-t", True, False, uid(5))
        lag = Port(uid(11), uid(2), "lag1", "lag", True, True, None)
        assert conn.ports([uid(1), uid(2)]) == Listing("dcim.interface", 2, (port, lag))
        ends = (End("dcim.frontport", front, None), End("dcim.interface", b, None))
        assert conn.cables([uid(5)]) == Listing(
            "dcim.cable", 1, (Cable(uid(5), None, (End("dcim.interface", a, None),), ends),)
        )
    asked = [(r.url.path, sorted(set(r.url.params) - {"limit", "offset"})) for r in served.asked]
    assert asked == [
        ("/api/extras/tags/", ["name"]),
        ("/api/dcim/devices/", ["tags"]),
        ("/api/dcim/platforms/", ["id"]),
        ("/api/dcim/manufacturers/", ["id"]),
        ("/api/dcim/interfaces/", ["device_id"]),
        ("/api/dcim/cables/", ["id"]),
    ]
    tags, devices, platforms, manufacturers, ports, cables = served.asked
    assert (tags.url.params["name"], devices.url.params["tags"]) == ("fylgja", TAG.id)
    assert platforms.url.params.get_list("id") == [uid(1), uid(3)]
    assert manufacturers.url.params.get_list("id") == [uid(7)]
    assert ports.url.params.get_list("device_id") == [uid(1), uid(2)]
    assert cables.url.params.get_list("id") == [uid(5)]
    assert all(request.url.path.endswith("/") for request in served.requests)


def test_a_connector_cabled_to_nothing_is_no_end() -> None:
    """A breakout cable answers null for a connector cabled to nothing (design/verified-facts.md)."""
    lanes = {"a1": end_row("dcim.interface", uid(10)), "b1": end_row("dcim.interface", uid(11)), "b2": None}
    with opened(Served(lambda request: page(1, [cable_row(uid(5), "x", lanes)]))) as conn:
        (cable,) = conn.cables([uid(5)]).items
    assert cable == Cable(uid(5), "x", (End("dcim.interface", uid(10), None),), (End("dcim.interface", uid(11), None),))


def test_the_pager_reads_every_page_and_answers_the_count() -> None:
    every = [port_row(uid(i), uid(1), f"p{i}") for i in range(250)]

    def answer(request: httpx.Request) -> httpx.Response:
        start, size = numbers(request, "offset")[0], numbers(request, "limit")[0]
        return page(250, every[start : start + size])

    served = Served(answer)
    with opened(served) as conn:
        count, results = conn.listed("/api/dcim/interfaces/", "dcim.interface", [("device_id", uid(1))])
    assert transport.PAGE == 100
    assert offsets(served) == [(0, 100), (100, 100), (200, 100)]
    assert all(r.url.params.get_list("device_id") == [uid(1)] for r in served.asked)
    assert (count, len(results)) == (250, 250)
    assert results == every


def test_the_pager_ends_on_a_list_short_of_its_count() -> None:
    answers = iter([page(3, [port_row(uid(1), uid(1), "a"), port_row(uid(2), uid(1), "b")]), page(3, [])])
    served = Served(lambda request: next(answers))
    with opened(served) as conn:
        count, results = conn.listed("/api/dcim/interfaces/", "dcim.interface", [])
    assert offsets(served) == [(0, 100), (2, 100)]
    assert (count, len(results)) == (3, 2)


def test_the_pager_keeps_the_largest_count_a_page_answered() -> None:
    """A row deleted between two pages shifts the offsets and lowers the count: kept at the largest, the list reads
    short of it, for `rows.incomplete` to refuse, never as whole."""
    first = page(3, [port_row(uid(1), uid(1), "a"), port_row(uid(2), uid(1), "b")])
    answers = iter([first, page(2, [port_row(uid(3), uid(1), "c")])])
    served = Served(lambda request: next(answers))
    with opened(served) as conn:
        count, results = conn.listed("/api/dcim/interfaces/", "dcim.interface", [])
    assert offsets(served) == [(0, 100), (2, 100)]
    assert (count, len(results)) == (3, 3)


def test_the_pager_never_follows_next() -> None:
    """Nautobot's `next` holds Nautobot's own address, which may not be the one the reader was given."""
    answers = iter(
        [
            page(
                3,
                [port_row(uid(1), uid(1), "a"), port_row(uid(2), uid(1), "b")],
                after="http://other.example/api/dcim/interfaces/?x=1",
            ),
            page(3, [port_row(uid(3), uid(1), "c")], after="http://other.example/api/dcim/interfaces/?x=2"),
        ]
    )
    served = Served(lambda request: next(answers))
    with opened(served) as conn:
        count, results = conn.listed("/api/dcim/interfaces/", "dcim.interface", [], size=2)
    assert {request.url.host for request in served.requests} == {HOST}
    assert offsets(served) == [(0, 2), (2, 2)]
    assert all("x" not in request.url.params for request in served.requests)
    assert (count, len(results)) == (3, 3)


def test_ids_are_asked_ids_a_request_and_their_counts_summed() -> None:
    """Ids short enough that `IDS` binds before the length does: 50 a request."""

    def answer(request: httpx.Request) -> httpx.Response:
        devices = request.url.params.get_list("device_id")
        return page(len(devices), [port_row(f"p-{d}", d, "mgmt0") for d in devices])

    served = Served(answer)
    wanted = [f"d{i}" for i in range(1, 121)]
    with opened(served) as conn:
        ports = conn.ports([*wanted, wanted[0]])
    assert transport.IDS == 50
    assert [r.url.params.get_list("device_id") for r in served.asked] == [wanted[:50], wanted[50:100], wanted[100:]]
    assert (ports.what, ports.count, len(ports.items)) == ("dcim.interface", 120, 120)
    assert [port.device for port in ports.items] == wanted


@pytest.mark.parametrize(("name", "call"), [("id", "cables"), ("device_id", "ports")])
def test_a_batch_of_ids_never_exceeds_the_request_bound(name: str, call: str) -> None:
    """Nautobot's server drops a request too long for it, unanswered (design/verified-facts.md): each request of a list
    by ids keeps its path and query, `limit` and `offset` included, within `MAX_REQUEST` bytes, each batch as full as
    the bound allows, and the counts of its requests sum to one listing. A list of more than a page pages each batch,
    whose offsets lengthen it, within the bound too."""
    wanted = [uid(i) for i in range(1, 201)]

    def answer(request: httpx.Request) -> httpx.Response:
        asked = request.url.params.get_list(name)
        start = int(request.url.params["offset"])
        rows = [
            cable_row(i, "", LANES) if name == "id" else port_row(f"p-{i}-{n}", i, f"e{n}")
            for i in asked
            for n in range(1 if name == "id" else 3)
        ]
        return page(len(rows), rows[start : start + transport.PAGE])

    served = Served(answer)
    with opened(served) as conn:
        listing = conn.cables(wanted) if call == "cables" else conn.ports(wanted)
    assert transport.MAX_REQUEST == 1500
    lengths = [len(request.url.raw_path) for request in served.asked]
    assert max(lengths) <= transport.MAX_REQUEST
    batches = [request.url.params.get_list(name) for request in served.asked if request.url.params["offset"] == "0"]
    assert [id for batch in batches for id in batch] == wanted
    for batch in batches[:-1]:
        fuller = [*batch, uid(999)]
        query = httpx.QueryParams([*((name, i) for i in fuller), ("limit", "100"), ("offset", "9" * transport.OFFSET)])
        assert len(f"{transport.CABLES if call == 'cables' else transport.INTERFACES}?{query}") > transport.MAX_REQUEST
    assert len(batches) > 1
    per = 1 if name == "id" else 3
    assert (listing.count, len(listing.items)) == (200 * per, 200 * per)


def test_the_newest_row_and_the_count_are_one_request() -> None:
    """One `?limit=1` of the changelog, which Nautobot lists newest first: its `count` the whole changelog's, and its
    one row the newest, its `time` kept as Nautobot answered it (design/verified-facts.md)."""
    time = "2026-11-19T23:12:28.833242Z"
    served = Served(lambda request: page(2904, [change_row(uid(20), time)], after="?limit=1&offset=1"))
    with opened(served) as conn:
        assert conn.newest() == (2904, Change(uid(20), time))
    (request,) = served.asked
    assert request.url.path == "/api/extras/object-changes/"
    assert list(request.url.params.multi_items()) == [("limit", "1")]


def test_an_empty_changelog_is_no_row() -> None:
    with opened(Served(lambda request: page(0, []))) as conn:
        assert conn.newest() == (0, None)


@pytest.mark.parametrize(
    ("count", "results", "said"),
    [
        (3, [], "a count of 3 and no row"),
        (0, [change_row(uid(20), "2026-11-19T23:12:28.833242Z")], "a count of 0 and a row"),
        (
            5,
            [change_row(uid(20), "2026-11-19T23:12:28.833242Z"), change_row(uid(21), "2026-11-19T23:12:28.833241Z")],
            "2 rows to a limit of 1",
        ),
        (1, [change_row(uid(20), "yesterday")], "a time yesterday that is no ISO 8601 time"),
    ],
    ids=["a count with no row", "a row with none", "more than one row", "a time that is no time"],
)
def test_a_newest_row_that_is_no_answer_is_an_error(count: int, results: list[dict[str, Any]], said: str) -> None:
    with opened(Served(lambda request: page(count, results))) as conn, pytest.raises(NautobotError) as raised:
        conn.newest()
    assert raised.value.status == 200
    assert str(raised.value) == f"reading extras.objectchange: HTTP 200: answered {said}"


@pytest.mark.parametrize(("member", "value"), [("id", None), ("time", None), ("time", 5), ("time", "")])
def test_a_newest_row_without_a_member_it_needs_is_an_error(member: str, value: object) -> None:
    row = {**change_row(uid(20), "2026-11-19T23:12:28.833242Z"), member: value}
    with opened(Served(lambda request: page(1, [row]))) as conn, pytest.raises(NautobotError) as raised:
        conn.newest()
    assert raised.value.status == 200
    said = f"answered a extras.objectchange with no {member}"
    assert str(raised.value) == f"reading extras.objectchange: HTTP 200: {said}"


def test_the_settings_are_read_whole_and_the_repositories_by_id() -> None:
    answers = {
        "/api/plugins/golden-config/golden-config-settings/": page(
            2,
            [
                setting_row(uid(30), "Default Settings", 1000, uid(40), uid(50)),
                setting_row(uid(31), "Bare", 10, None, uid(51)),
            ],
        ),
        "/api/extras/git-repositories/": page(
            2, [repository_row(uid(40), "fylgja-templates", HEAD), repository_row(uid(41), "never-synced", "")]
        ),
    }
    served = Served(lambda request: answers[request.url.path])
    with opened(served) as conn:
        assert conn.settings() == Listing(
            "nautobot_golden_config.goldenconfigsetting",
            2,
            (Setting(uid(30), "Default Settings", 1000, uid(40), uid(50)), Setting(uid(31), "Bare", 10, None, uid(51))),
        )
        assert conn.repositories([uid(40), uid(41)]) == Listing(
            "extras.gitrepository",
            2,
            (Repository(uid(40), "fylgja-templates", HEAD), Repository(uid(41), "never-synced", "")),
        )
    settings, repositories = served.asked
    assert sorted(set(settings.url.params) - {"limit", "offset"}) == []
    assert repositories.url.params.get_list("id") == [uid(40), uid(41)]
    assert all(request.url.path.endswith("/") for request in served.requests)


def test_the_groups_are_read_by_id_and_their_members_restricted_to_the_devices_asked() -> None:
    """The groups by `?id=`; a group's stored members by `?dynamic_group=` and `?associated_object_id=` of the devices
    asked, each answered as the device's id; and the devices a filter lists by the filter's own parameters, first, and
    `?id=` of the devices asked (design/verified-facts.md, "A group's stored members")."""
    filter = {"tags": ["fylgja"], "has_interfaces": True}
    answers = {
        "/api/extras/dynamic-groups/": page(
            2, [group_row(uid(50), "scope", "dynamic-filter", filter), group_row(uid(51), "set", "dynamic-set", {})]
        ),
        "/api/extras/static-group-associations/": page(
            2, [association_row(uid(60), uid(50), uid(1)), association_row(uid(61), uid(50), uid(3))]
        ),
        "/api/dcim/devices/": page(2, [device_row(uid(1), "n1", tags=[]), device_row(uid(2), "n2", tags=[])]),
    }
    served = Served(lambda request: answers[request.url.path])
    with opened(served) as conn:
        assert conn.groups([uid(50), uid(51)]) == Listing(
            "extras.dynamicgroup",
            2,
            (Group(uid(50), "scope", "dynamic-filter", filter), Group(uid(51), "set", "dynamic-set", {})),
        )
        assert conn.stored(uid(50), [uid(1), uid(2), uid(3)]) == Listing(
            "extras.staticgroupassociation", 2, (uid(1), uid(3))
        )
        sent = [("tags", "fylgja"), ("has_interfaces", "true")]
        assert conn.matching(sent, [uid(1), uid(2), uid(3)]) == Listing(
            "dcim.device", 2, (Device(uid(1), "n1", uid(1)), Device(uid(2), "n2", uid(1)))
        )
    groups, stored, matching = served.asked
    assert groups.url.params.get_list("id") == [uid(50), uid(51)]
    assert [(k, v) for k, v in stored.url.params.multi_items() if k not in ("limit", "offset")] == [
        ("dynamic_group", uid(50)),
        *(("associated_object_id", uid(i)) for i in (1, 2, 3)),
    ]
    assert [(k, v) for k, v in matching.url.params.multi_items() if k not in ("limit", "offset")] == [
        *sent,
        *(("id", uid(i)) for i in (1, 2, 3)),
    ]
    assert all(request.url.path.endswith("/") for request in served.requests)


def test_a_context_is_read_by_its_name_with_its_data_and_whether_it_is_active() -> None:
    """The context by `?name=` of `extras/config-contexts/`, which lists an inactive one (design/verified-facts.md,
    "A configuration context made with `is_active: false`"); its `data` is whatever JSON Nautobot answered."""
    data = {"probes_version": "1", "probes": [{"name": "n1-loop"}]}
    rows = [
        context_row(uid(70), "fylgja-probes", data=data),
        context_row(uid(71), "fylgja-probes", active=True, data=[]),
    ]
    served = Served(lambda request: page(2, rows))
    with opened(served) as conn:
        assert conn.contexts("fylgja-probes") == Listing(
            "extras.configcontext",
            2,
            (Context(uid(70), "fylgja-probes", False, data), Context(uid(71), "fylgja-probes", True, [])),
        )
    (asked,) = served.asked
    assert asked.url.path == "/api/extras/config-contexts/"
    assert asked.url.params.get_list("name") == ["fylgja-probes"]
    assert sorted(set(asked.url.params) - {"limit", "offset"}) == ["name"]


@pytest.mark.parametrize(
    "row",
    [
        {"id": uid(70), "name": "fylgja-probes", "data": {}},
        {"id": uid(70), "name": "fylgja-probes", "is_active": "no", "data": {}},
        {"id": uid(70), "name": "fylgja-probes", "is_active": False},
        {"id": uid(70), "is_active": False, "data": {}},
    ],
    ids=["no is_active", "is_active no flag", "no data", "no name"],
)
def test_a_context_row_that_is_none_is_an_error(row: dict[str, Any]) -> None:
    with opened(Served(lambda request: page(1, [row]))) as conn, pytest.raises(NautobotError) as raised:
        conn.contexts("fylgja-probes")
    assert raised.value.status == 200
    assert str(raised.value).startswith("reading extras.configcontext: HTTP 200: answered a extras.configcontext with ")


@pytest.mark.parametrize("call", ["stored", "matching"])
def test_a_restricted_list_keeps_its_own_parameters_within_the_request_bound(call: str) -> None:
    """The parameters a list carries beside the ids, the group's id or a filter's, are measured with each batch."""
    wanted = [uid(i) for i in range(1, 121)]
    fixed = [("dynamic_group", uid(50))] if call == "stored" else [("name", "n" * 200), ("tags", "fylgja")]

    def answer(request: httpx.Request) -> httpx.Response:
        if call == "stored":
            asked = request.url.params.get_list("associated_object_id")
            return page(len(asked), [association_row(uid(600 + int(i[-3:])), uid(50), i) for i in asked])
        asked = request.url.params.get_list("id")
        return page(len(asked), [device_row(i, None, tags=[]) for i in asked])

    served = Served(answer)
    with opened(served) as conn:
        listing = conn.stored(uid(50), wanted) if call == "stored" else conn.matching(fixed[:], wanted)
    assert max(len(request.url.raw_path) for request in served.asked) <= transport.MAX_REQUEST
    assert len(served.asked) > 1
    for request in served.asked:
        held = [(k, v) for k, v in request.url.params.multi_items() if k in dict(fixed)]
        assert held == fixed
    assert listing.count == len(listing.items) == 120


def test_no_ids_send_nothing() -> None:
    served = Served()
    with opened(served) as conn:
        assert conn.platforms([]) == Listing("dcim.platform", 0, ())
        assert conn.manufacturers([]) == Listing("dcim.manufacturer", 0, ())
        assert conn.ports([]) == Listing("dcim.interface", 0, ())
        assert conn.cables([]) == Listing("dcim.cable", 0, ())
        assert conn.repositories([]) == Listing("extras.gitrepository", 0, ())
        assert conn.groups([]) == Listing("extras.dynamicgroup", 0, ())
        assert conn.stored(uid(50), []) == Listing("extras.staticgroupassociation", 0, ())
        assert conn.matching([("tags", "fylgja")], []) == Listing("dcim.device", 0, ())
    assert served.asked == []


def read(conn: Nautobot, what: str) -> object:
    calls: dict[str, Callable[[], object]] = {
        "extras.tag": lambda: conn.tags("fylgja"),
        "dcim.device": lambda: conn.devices(TAG),
        "dcim.platform": lambda: conn.platforms([uid(1)]),
        "dcim.manufacturer": lambda: conn.manufacturers([uid(7)]),
        "dcim.interface": lambda: conn.ports([uid(1)]),
        "dcim.cable": lambda: conn.cables([uid(5)]),
        "nautobot_golden_config.goldenconfigsetting": lambda: conn.settings(),
        "extras.gitrepository": lambda: conn.repositories([uid(40)]),
        "extras.dynamicgroup": lambda: conn.groups([uid(50)]),
        "extras.configcontext": lambda: conn.contexts("fylgja-probes"),
        "extras.staticgroupassociation": lambda: conn.stored(uid(50), [uid(1)]),
        "matching dcim.device": lambda: conn.matching([("tags", "fylgja")], [uid(1)]),
    }
    return calls[what]()


def refused_by(what: str, results: list[dict[str, Any]]) -> NautobotError:
    with opened(Served(lambda request: page(len(results), results))) as conn, pytest.raises(NautobotError) as raised:
        read(conn, what)
    return raised.value


LANES = {"a1": end_row("dcim.interface", uid(20)), "b1": end_row("dcim.interface", uid(21))}


@pytest.mark.parametrize(
    ("what", "row", "said"),
    [
        ("dcim.device", device_row(uid(1), "n1", tags=[uid(2)]), f"the dcim.device {uid(1)} without the tag {TAG.id},"),
        (
            "dcim.interface",
            port_row(uid(10), uid(2), "ethernet-1/1"),
            f"the dcim.interface {uid(10)} of the dcim.device {uid(2)},",
        ),
        ("dcim.cable", cable_row(uid(6), "", LANES), f"the dcim.cable {uid(6)},"),
        ("dcim.platform", platform_row(uid(2), "SR Linux", uid(7)), f"the dcim.platform {uid(2)},"),
        ("dcim.manufacturer", manufacturer_row(uid(8), "Nokia"), f"the dcim.manufacturer {uid(8)},"),
        ("extras.tag", tag_row(TAG.id, "fylgja-other"), f"the extras.tag {TAG.id} named fylgja-other,"),
        ("extras.tag", tag_row(TAG.id, "FYLGJA"), f"the extras.tag {TAG.id} named FYLGJA,"),
        ("extras.gitrepository", repository_row(uid(41), "x", HEAD), f"the extras.gitrepository {uid(41)},"),
        ("extras.dynamicgroup", group_row(uid(51), "x", "dynamic-filter", {}), f"the extras.dynamicgroup {uid(51)},"),
        (
            "extras.staticgroupassociation",
            association_row(uid(60), uid(50), uid(2)),
            f"the extras.staticgroupassociation {uid(60)} of the dcim.device {uid(2)},",
        ),
        (
            "extras.staticgroupassociation",
            association_row(uid(60), uid(51), uid(1)),
            f"the extras.staticgroupassociation {uid(60)} of the extras.dynamicgroup {uid(51)},",
        ),
        (
            "extras.staticgroupassociation",
            association_row(uid(60), uid(50), uid(1), kind="dcim.rack"),
            f"the extras.staticgroupassociation {uid(60)} of the dcim.rack {uid(1)},",
        ),
        ("matching dcim.device", device_row(uid(2), "n2", tags=[]), f"the dcim.device {uid(2)},"),
        (
            "extras.configcontext",
            context_row(uid(70), "fylgja-other"),
            f"the extras.configcontext {uid(70)} named fylgja-other,",
        ),
        (
            "extras.configcontext",
            context_row(uid(70), "FYLGJA-PROBES"),
            f"the extras.configcontext {uid(70)} named FYLGJA-PROBES,",
        ),
    ],
    ids=[
        "device",
        "interface",
        "cable",
        "platform",
        "manufacturer",
        "tag",
        "tag of another case",
        "repository",
        "group",
        "stored member of another device",
        "stored member of another group",
        "stored member of another type",
        "device another filter lists",
        "context of another name",
        "context of another case",
    ],
)
def test_a_row_the_request_did_not_ask_for_is_an_error(what: str, row: dict[str, Any], said: str) -> None:
    """A row of another than was asked is refused, never read as one that was: the reader does not rely on Nautobot's
    filters alone."""
    e = refused_by(what, [row])
    assert e.status == 200
    for held in (f"reading {what.removeprefix('matching ')}: ", "HTTP 200", "did not ask for", said):
        assert held in str(e)


def test_a_name_answered_twice_is_an_error() -> None:
    """Which of two rows of one name the read would take cannot be told, so neither is taken (D-098)."""
    twice = Listing("extras.tag", 2, (Tag(uid(1), "fylgja"), Tag(uid(2), "fylgja")))
    with pytest.raises(NautobotError) as raised:
        named(twice, "fylgja")
    assert raised.value.status == 200
    assert str(raised.value) == (
        "reading extras.tag: HTTP 200: answered 2 rows named fylgja, where the read takes the one object of a name"
    )
    once = Listing("extras.tag", 2, (Tag(uid(1), "fylgja"), Tag(uid(2), "FYLGJA")))
    assert named(once, "fylgja") == Tag(uid(1), "fylgja")
    assert named(once, "other") is None


ROWS = {
    "extras.tag": tag_row(TAG.id, "fylgja"),
    "dcim.device": device_row(uid(1), "n1", tags=[TAG.id]),
    "dcim.platform": platform_row(uid(1), "SR Linux", uid(7)),
    "dcim.manufacturer": manufacturer_row(uid(7), "Nokia"),
    "dcim.interface": port_row(uid(10), uid(1), "ethernet-1/1"),
    "dcim.cable": cable_row(uid(5), "", LANES),
    "nautobot_golden_config.goldenconfigsetting": setting_row(uid(30), "Default Settings", 1000, uid(40), uid(50)),
    "extras.gitrepository": repository_row(uid(40), "fylgja-templates", HEAD),
    "extras.dynamicgroup": group_row(uid(50), "scope", "dynamic-filter", {"tags": ["fylgja"]}),
    "extras.staticgroupassociation": association_row(uid(60), uid(50), uid(1)),
}


@pytest.mark.parametrize("what", list(ROWS))
def test_a_row_without_its_id_is_an_error(what: str) -> None:
    for id in (None, "", 1, True):
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
        ("extras.tag", "name", None),
        ("dcim.device", "name", ABSENT),
        ("dcim.device", "name", 5),
        ("dcim.device", "tags", None),
        ("dcim.device", "tags", [{"name": "fylgja"}]),
        ("dcim.device", "platform", ABSENT),
        ("dcim.device", "platform", {"name": "SR Linux"}),
        ("dcim.device", "platform", uid(1)),
        ("dcim.platform", "name", ""),
        ("dcim.platform", "manufacturer", {"object_type": "dcim.manufacturer"}),
        ("dcim.manufacturer", "name", None),
        ("dcim.interface", "enabled", None),
        ("dcim.interface", "mgmt_only", "false"),
        ("dcim.interface", "type", "1000base-t"),
        ("dcim.interface", "type", {"label": "1000BASE-T"}),
        ("dcim.interface", "device", None),
        ("dcim.interface", "cable", {"object_type": "dcim.cable"}),
        ("dcim.cable", "terminations", None),
        ("dcim.cable", "terminations", [LANES["a1"]]),
        ("dcim.cable", "terminations", {"c1": LANES["a1"]}),
        ("dcim.cable", "terminations", {"a0": LANES["a1"]}),
        ("dcim.cable", "terminations", {"a1": {"object_type": "dcim.interface"}}),
        ("dcim.cable", "terminations", {"a1": {"id": uid(20)}}),
        ("dcim.cable", "terminations", {"a1": uid(20)}),
        ("dcim.cable", "label", ABSENT),
        ("dcim.cable", "label", 5),
        ("nautobot_golden_config.goldenconfigsetting", "name", ""),
        ("nautobot_golden_config.goldenconfigsetting", "weight", ABSENT),
        ("nautobot_golden_config.goldenconfigsetting", "weight", "1000"),
        ("nautobot_golden_config.goldenconfigsetting", "weight", True),
        ("nautobot_golden_config.goldenconfigsetting", "jinja_repository", ABSENT),
        ("nautobot_golden_config.goldenconfigsetting", "jinja_repository", uid(40)),
        ("nautobot_golden_config.goldenconfigsetting", "dynamic_group", None),
        ("nautobot_golden_config.goldenconfigsetting", "dynamic_group", {"name": "scope"}),
        ("extras.gitrepository", "name", None),
        ("extras.gitrepository", "current_head", ABSENT),
        ("extras.gitrepository", "current_head", None),
        ("extras.dynamicgroup", "name", ""),
        ("extras.dynamicgroup", "group_type", None),
        ("extras.dynamicgroup", "filter", ABSENT),
        ("extras.staticgroupassociation", "associated_object_id", None),
        ("extras.staticgroupassociation", "associated_object_id", ABSENT),
        ("extras.staticgroupassociation", "associated_object_type", ""),
        ("extras.staticgroupassociation", "dynamic_group", None),
        ("extras.staticgroupassociation", "dynamic_group", uid(50)),
    ],
)
def test_a_row_without_a_member_it_needs_is_an_error(what: str, member: str, value: object) -> None:
    row = {key: held for key, held in ROWS[what].items() if key != member}
    e = refused_by(what, [row if value is ABSENT else {**row, member: value}])
    assert e.status == 200
    assert f"reading {what}: HTTP 200: answered a {what}" in str(e)
    assert member in str(e)


@pytest.mark.parametrize(
    "body", [{"results": []}, {"count": 1}, {"count": "1", "results": []}, {"count": 1, "results": {}}, []]
)
def test_an_answer_that_is_no_list_is_an_error(body: object) -> None:
    with (
        opened(Served(lambda request: httpx.Response(200, json=body))) as conn,
        pytest.raises(NautobotError) as raised,
    ):
        conn.tags("fylgja")
    assert raised.value.status == 200
    assert str(raised.value) == "reading extras.tag: HTTP 200: answered no count and results"


def test_an_answer_that_is_no_json_is_an_error() -> None:
    with (
        opened(Served(lambda request: httpx.Response(200, text="<html>"))) as conn,
        pytest.raises(NautobotError) as raised,
    ):
        conn.tags("fylgja")
    assert (raised.value.status, str(raised.value)) == (200, "reading extras.tag: HTTP 200: answered no JSON")


def test_a_400_keeps_its_status_and_quotes_the_detail() -> None:
    """Nautobot answers 400 to a tag it does not hold, in a body of the filter's name (design/verified-facts.md)."""
    words = {"tags": ["Select a valid choice. fylgja-contract-none is not one of the available choices."]}
    with (
        opened(Served(lambda request: httpx.Response(400, json=words))) as conn,
        pytest.raises(NautobotError) as raised,
    ):
        conn.devices(Tag(uid(9), "fylgja-contract-none"))
    assert raised.value.status == 400
    assert str(raised.value) == (
        'reading dcim.device: HTTP 400: {"tags": ["Select a valid choice. fylgja-contract-none is not one of the '
        'available choices."]}'
    )
    detail = {"detail": "Invalid filter"}
    with (
        opened(Served(lambda request: httpx.Response(400, json=detail))) as conn,
        pytest.raises(NautobotError) as raised,
    ):
        conn.ports([uid(9)])
    assert (raised.value.status, str(raised.value)) == (400, "reading dcim.interface: HTTP 400: Invalid filter")


def test_nautobots_words_are_cut_and_the_token_in_them_replaced() -> None:
    said = f"{TOKEN} " + "x" * 400
    with (
        opened(Served(lambda request: httpx.Response(500, text=said))) as conn,
        pytest.raises(NautobotError) as raised,
    ):
        conn.tags("fylgja")
    assert raised.value.status == 500
    words = str(raised.value).removeprefix("reading extras.tag: HTTP 500: ")
    assert words.startswith("<redacted> xxx")
    assert len(words) == transport.QUOTED == 300
    assert TOKEN not in str(raised.value)


def test_a_body_is_json_only_where_nautobot_says_so() -> None:
    def plain(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, content=b'{"detail": "plain"}', headers={"Content-Type": "text/plain"})

    with opened(Served(plain)) as conn, pytest.raises(NautobotError) as raised:
        conn.tags("fylgja")
    assert str(raised.value) == 'reading extras.tag: HTTP 400: {"detail": "plain"}'


@pytest.mark.parametrize("status", [401, 403])
def test_a_refused_token_names_its_variable_and_quotes_nothing(status: int) -> None:
    def echoed(request: httpx.Request) -> httpx.Response:
        held = request.headers["Authorization"]
        return httpx.Response(status, json={"detail": f"Refused {held}", "x": "Nautobot said"})

    for served in (Served(echoed), Served(info=echoed)):
        with pytest.raises(NautobotError) as raised, opened(served) as conn:
            conn.devices(TAG)
        assert raised.value.status == status
        text = str(raised.value)
        assert "FYLGJA_NAUTOBOT_TOKEN" in text and f"HTTP {status}" in text
        for quoted in ("Refused", "Nautobot said", TOKEN, "Token ", "<redacted>"):
            assert quoted not in text
    assert str(raised.value).startswith("reading Nautobot's version: ")


def test_a_redirect_is_refused_naming_its_path_alone() -> None:
    def moved(request: httpx.Request) -> httpx.Response:
        return httpx.Response(301, headers={"Location": f"http://other.example/api/dcim/devices/?tags={TAG.id}"})

    served = Served(moved)
    with opened(served) as conn, pytest.raises(NautobotError) as raised:
        conn.devices(TAG)
    assert raised.value.status == 301
    assert str(raised.value) == "reading dcim.device: HTTP 301: a redirect to /api/dcim/devices/"
    assert len(served.asked) == 1


def test_no_error_repr_cause_or_log_line_holds_the_token(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)

    def unreached(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"no route, having sent Authorization: Token {TOKEN}", request=request)

    with opened(Served(unreached)) as conn:
        with pytest.raises(NautobotError) as raised:
            conn.ports([uid(1)])
        held = repr(conn)
    with pytest.raises(NautobotError) as at_connect:
        connect(ADDRESS, TOKEN, transport=httpx.MockTransport(unreached))
    for e in (raised.value, at_connect.value):
        assert e.status is None
        assert e.__cause__ is None and e.__context__ is None and e.__suppress_context__
        assert "ConnectError" in str(e) and "<redacted>" in str(e)
        for text in (str(e), repr(e)):
            assert TOKEN not in text
    assert str(raised.value).startswith("reading dcim.interface: Nautobot at http://nautobot.example was not reached")
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


def test_redact_replaces_the_token_and_an_empty_one_nothing() -> None:
    assert redact(f"a {TOKEN} b {TOKEN}", TOKEN) == "a <redacted> b <redacted>"
    assert redact("a b", "") == "a b"
    assert transport.REDACTED == "<redacted>"


RENDER = "/api/plugins/golden-config/generate-intended-config/"


def rendering(status: int, body: object | None = None, *, content: bytes | None = None) -> Served:
    """A Nautobot whose every render answers `status` with `body` as JSON, or `content` as `text/plain`."""

    def answer(request: httpx.Request) -> httpx.Response:
        if content is not None:
            return httpx.Response(status, content=content, headers={"Content-Type": "text/plain"})
        return httpx.Response(status, json=body)

    return Served(answer)


def test_a_render_is_asked_by_the_device_id_alone() -> None:
    """Golden Config's render is one `GET` by `device_id`, never with `branch` or any other parameter (D-118)."""
    body: dict[str, Any] = {
        "intended_config": "set / x\n",
        "intended_config_lines": ["set / x"],
        "graphql_data": {},
        "diff": None,
    }
    served = rendering(200, body)
    with opened(served) as conn:
        assert conn.render(uid(1)) == Rendered(200, "set / x\n", None)
    ((request,),) = [served.asked]
    assert (request.method, request.url.path) == ("GET", RENDER)
    assert request.url.params.multi_items() == [("device_id", uid(1))]


@pytest.mark.parametrize(
    ("status", "body", "rendered"),
    [
        (200, {"intended_config": "   \n"}, Rendered(200, "   \n", None)),
        (200, {"intended_config": None}, Rendered(200, None, None)),
        (200, {"intended_config_lines": []}, Rendered(200, None, None)),
        (200, ["set / x"], Rendered(200, None, None)),
        (
            400,
            {"detail": "No Golden Config settings found for this device"},
            Rendered(400, None, "No Golden Config settings found for this device"),
        ),
        (400, {"device_id": ["Enter a valid UUID."]}, Rendered(400, None, None)),
        (404, {"detail": "Not found."}, Rendered(404, None, "Not found.")),
        (502, None, Rendered(502, None, None)),
    ],
    ids=["whitespace", "null", "no member", "no object", "400", "400 no detail", "404", "502"],
)
def test_a_render_answers_its_status_and_golden_configs_words(
    status: int, body: object, rendered: Rendered
) -> None:
    with opened(rendering(status, body)) as conn:
        assert conn.render(uid(1)) == rendered


def test_a_render_that_is_no_json_is_no_text() -> None:
    with opened(rendering(200, content=b"set / x\n")) as conn:
        assert conn.render(uid(1)) == Rendered(200, None, None)
    with opened(rendering(400, content=b'{"detail": "plain"}')) as conn:
        assert conn.render(uid(1)) == Rendered(400, None, None)


def test_a_renders_words_are_uncut_and_the_token_in_them_replaced() -> None:
    said = f"Error rendering Jinja template: {TOKEN} " + "y" * 400 + "\n"
    with opened(rendering(400, {"detail": said})) as conn:
        held = conn.render(uid(1))
    assert held.status == 400 and held.text is None
    assert held.detail == said.replace(TOKEN, "<redacted>")
    assert TOKEN not in repr(held)


def test_a_render_does_not_follow_a_redirect() -> None:
    def moved(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "http://other.example/login/"})

    served = Served(moved)
    with opened(served) as conn:
        assert conn.render(uid(1)) == Rendered(302, None, None)
    assert len(served.asked) == 1


@pytest.mark.parametrize("status", [401, 403])
def test_a_render_refused_the_token_is_an_error_quoting_nothing(status: int) -> None:
    def echoed(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"detail": f"Refused {request.headers['Authorization']}"})

    with opened(Served(echoed)) as conn, pytest.raises(NautobotError) as raised:
        conn.render(uid(1))
    assert raised.value.status == status
    assert "FYLGJA_NAUTOBOT_TOKEN" in str(raised.value)
    assert TOKEN not in str(raised.value) and "Refused" not in str(raised.value)
    assert str(raised.value).startswith("rendering dcim.device ")


def test_a_render_unreached_is_an_error_of_no_status() -> None:
    def unreached(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"no route, having sent Token {TOKEN}", request=request)

    with opened(Served(unreached)) as conn, pytest.raises(NautobotError) as raised:
        conn.render(uid(1))
    assert raised.value.status is None
    assert TOKEN not in str(raised.value) and raised.value.__cause__ is None


def test_a_group_filter_naming_a_deleted_tag_is_an_error_naming_the_group() -> None:
    """Nautobot answers 400 to a tag it does not hold; the listing by a group's filter says whose filter it was."""
    words = {"tags": ["Select a valid choice. gone is not one of the available choices."]}
    with (
        opened(Served(lambda request: httpx.Response(400, json=words))) as conn,
        pytest.raises(NautobotError) as raised,
    ):
        conn.matching([("tags", "gone")], [uid(1)], group="Tagged")
    assert raised.value.status == 400
    assert str(raised.value).startswith("reading dcim.device by the filter of dynamic group Tagged: HTTP 400: ")


def test_a_group_name_is_the_listings_own_only_where_one_is_given() -> None:
    with opened(Served(lambda request: page(0, []))) as conn:
        assert conn.matching([("tags", "x")], [uid(1)]).what == "dcim.device"
        named = conn.matching([("tags", "x")], [uid(1)], group="Tagged")
    assert named.what == "dcim.device by the filter of dynamic group Tagged"


def test_a_decode_error_is_not_the_context_of_the_error_raised_for_it() -> None:
    """The error's `__context__` would hold a `JSONDecodeError` whose `.doc` is the whole body: none is kept."""
    body = "<html>" + "x" * 5000
    with (
        opened(Served(lambda request: httpx.Response(200, text=body))) as conn,
        pytest.raises(NautobotError) as raised,
    ):
        conn.tags("fylgja")
    assert raised.value.__context__ is None and raised.value.__cause__ is None
    row = change_row(uid(20), "yesterday")
    with opened(Served(lambda request: page(1, [row]))) as conn, pytest.raises(NautobotError) as raised:
        conn.newest()
    assert raised.value.__context__ is None and raised.value.__cause__ is None
