"""Each rule of the reader provoked on the development Nautobot (D-118, D-119; rules.md): a Nautobot naming no Golden
Config, and a pair of versions the reader was not verified on; a scope of another form; a list answered short of its
count; a tag Nautobot lacks and one no device carries; a device with no platform, a platform with no manufacturer and a
pair no row of the document holds; a device renamed to its label, two of one label, and one named `""`; each cable
the mapping omits, and a breakout with a leg cabled to nothing, which is a link; a device in no setting's group, a
template the repository lacks, a template raising for one device and rendering whitespace for another, and a render
answered otherwise; the probes' refusals; and an account that may view devices alone, whose render is smaller and no
error.

Nautobot has no branch, so each test writes only objects of the tier's naming, `fylgja-contract-<8 hex>`, through
`box`, deleted in a `finally` in the reverse of the order made, a device's cables before the device (`making`); or
edits a seeded object it puts back there (`restored`); or pushes to the template repository and pushes the tracked
templates back (`pushed`). A device tagged `fylgja` is stored by the setting's dynamic group only once the group is
saved, so a test that makes one saves the group after, and again once it is deleted (`Made.regroup`): otherwise each
read would be refused by `group.stale` beside the fault provoked (test_groups_contract.py holds that rule). Each reads
with the reader's token. A provocation Nautobot cannot be written into is made in flight by `reader_over`, the test
saying so and why. No assertion message prints the address or a token."""

from __future__ import annotations

import copy
import json
import os
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any

import httpx
import pytest

from fylgja_nautobot import Match, Nautobot, ReaderDocument, Result, check, read
from fylgja_nautobot.transport import RENDER, STATUS

from .conftest import (
    ADDRESS,
    ROOT,
    SEEDING,
    SENT,
    TEMPLATE,
    Writes,
    account,
    contract_name,
    pushed,
    reader,
    reader_over,
    restored,
    settle,
    writer,
)

SCOPE = "tag:fylgja"
CONTEXT = "fylgja-probes"
SOURCE = "extras.configcontext"
MISSING = "fylgja-contract-none"
"""A tag Nautobot lacks: no tag of the tier's own, which are named by 8 hex digits."""

DEVICES = "dcim/devices/"
CABLES = "dcim/cables/"
INTERFACES = "dcim/interfaces/"
PLATFORMS = "dcim/platforms/"
GROUPS = "extras/dynamic-groups/"
GROUP = "GoldenConfigSetting Default Settings scope"
"""The installed setting's dynamic group, whose filter the seed sets to the devices tagged `fylgja`."""

INTERFACE = "dcim.interface"
DRIVER = "arista_eos"
"""A platform's network driver the template repository holds no template of: the setting's path template names
`<network driver>.j2`, and the repository holds `nokia_srl.j2` alone."""

FIXTURE = json.loads((ROOT / "testdata" / "blueprint" / "three-node.json").read_text())
LINKS: list[dict[str, Any]] = FIXTURE["network"]["links"]
"""The seeded fixture's three links."""


@pytest.fixture(scope="module")
def unprobed(document: ReaderDocument) -> ReaderDocument:
    """The seeded fixture network's reader document, naming no configuration context of probes."""
    return ReaderDocument(document.platforms, None)


def found(result: Result) -> list[tuple[str, str | None]]:
    """Every finding's rule and object, the version warning aside, sorted."""
    return sorted((f.rule, f.object) for f in result.findings if f.rule != "nautobot.version.unverified")


def errors(result: Result) -> list[tuple[str, str | None]]:
    return sorted((f.rule, f.object) for f in result.findings if f.severity == "error")


def refused(result: Result, *wanted: tuple[str, str]) -> None:
    """The read gave no blueprint, and its findings are `wanted` and nothing else, so no other object is named."""
    assert result.blueprint is None
    assert found(result) == sorted(wanted)


def taken(result: Result) -> dict[str, Any]:
    """The blueprint a read answered, which must have no error."""
    assert errors(result) == []
    assert result.blueprint is not None
    return result.blueprint


def seeded(box: Writes, name: str) -> dict[str, Any]:
    """The seeded device `name`."""
    held = box.one(DEVICES, name=name)
    assert held is not None, name
    return held


def port(box: Writes, device: str, name: str) -> str:
    """The id of the seeded interface `device:name`."""
    held = box.one(INTERFACES, device_id=seeded(box, device)["id"], name=name)
    assert held is not None, f"{device}:{name}"
    return str(held["id"])


def nokia(box: Writes) -> str:
    """The id of the seeded platform's manufacturer, `Nokia`."""
    platform = box.get(f"{PLATFORMS}{seeded(box, 'n2')['platform']['id']}/")
    return str(platform["manufacturer"]["id"])


def owning(document: ReaderDocument, platform: str) -> ReaderDocument:
    """`document` with a row mapping `Nokia` and `platform` too, so that a device of it is no `platform.unmatched`."""
    return ReaderDocument((*document.platforms, Match("Nokia", platform, "nokia_srlinux")), document.probes)


def links(*added: dict[str, Any]) -> list[dict[str, Any]]:
    """The fixture's links and `added`, in a blueprint's order."""
    ends = ("a", "b")
    return sorted([*LINKS, *added], key=lambda link: tuple(link[e][m] for e in ends for m in ("device", "interface")))


def quoted(result: Result, configs: Mapping[str, str]) -> list[str]:
    """The lines of `configs` some finding's message holds, a line of whitespace alone aside."""
    lines = {line for text in configs.values() for line in text.splitlines() if line.strip()}
    return sorted(line for line in lines if any(line in f.message for f in result.findings))


class Made:
    """What a test makes, each object by its path, in the order made, for `making` to delete in the reverse order;
    and whether it saved the setting's group, which `making` then saves again."""

    def __init__(self, box: Writes) -> None:
        self.box = box
        self.paths: list[str] = []
        self.grouped = False

    def post(self, path: str, body: Mapping[str, object]) -> dict[str, Any]:
        """The object made at `path` of `body`, kept for its delete."""
        row: dict[str, Any] = self.box.post(path, dict(body))
        self.paths.append(f"{path}{row['id']}/")
        return row

    def device(self, **body: object) -> dict[str, Any]:
        """A device of `n2`'s device type, role, location and platform, tagged `fylgja`, named and commented
        `contract_name()`, with `body` over them; a member given None is left out. Its comments name it to the sweep
        where its name does not."""
        like = seeded(self.box, "n2")
        named = contract_name()
        held: dict[str, object] = {
            "name": named,
            "comments": named,
            "device_type": like["device_type"]["id"],
            "role": like["role"]["id"],
            "location": like["location"]["id"],
            "platform": like["platform"]["id"],
            "status": "Active",
            "tags": [tag["id"] for tag in like["tags"]],
        }
        held.update(body)
        return self.post(DEVICES, {name: value for name, value in held.items() if value is not None})

    def regroup(self) -> None:
        """The setting's dynamic group saved with its own filter, so that its stored members are the devices its filter
        lists now (design/verified-facts.md, "A device is rendered only while it is a member of a setting's dynamic
        group, and the members are stored.")."""
        self.grouped = True
        group = self.box.one(GROUPS, name=GROUP)
        assert group is not None
        self.box.patch(f"{GROUPS}{group['id']}/", {"filter": group["filter"]})


@contextmanager
def making(box: Writes) -> Iterator[Made]:
    """A `Made` for the test; on leaving, whatever happened, each object deleted in the reverse of the order made, a
    device's cables first, since Nautobot leaves a deleted device's cables standing (design/verified-facts.md), and the
    group saved again where the test saved it."""
    made = Made(box)
    try:
        yield made
    finally:
        try:
            for path in reversed(made.paths):
                if path.startswith(DEVICES):
                    for cable in box.listed(CABLES, device_id=path.removeprefix(DEVICES).strip("/")):
                        box.delete(f"{CABLES}{cable['id']}/")
                box.delete(path)
        finally:
            if made.grouped:
                made.regroup()


def test_a_nautobot_without_golden_config_is_refused_before_any_list(unprobed: ReaderDocument) -> None:
    """In flight: the development Nautobot has Golden Config, and one without it is another install, so the app is
    taken out of `/api/status/`'s `nautobot-apps` on its way to the reader. The read sends nothing more, and the pair
    `<version>/none` is no pair the reader was verified on."""

    def bare(request: httpx.Request, response: httpx.Response) -> httpx.Response:
        if request.url.path != STATUS:
            return response
        return httpx.Response(response.status_code, json={**response.json(), "nautobot-apps": {}})

    with reader_over(bare) as alone:
        assert alone.golden_config is None
        result = read(alone, scope=SCOPE, document=unprobed)
        checked = check(alone)
        sent = [(request.method, request.path) for request in SENT[alone]]
    assert sent == [("GET", STATUS)]
    refused(result, ("golden_config.absent", "nautobot_golden_config"))
    warned = ("nautobot.version.unverified", "warning", f"{alone.version}/none")
    assert [(f.rule, f.severity, f.object) for f in result.findings if f.severity == "warning"] == [warned]
    absent = ("golden_config.absent", "error", "nautobot_golden_config")
    assert sorted((f.rule, f.severity, f.object) for f in checked) == sorted([absent, warned])


def test_a_pair_not_supported_warns(unprobed: ReaderDocument) -> None:
    """In flight: the development Nautobot is of the one pair the reader was verified on, so `/api/status/`'s
    `nautobot-version` is answered `3.2.9` on its way to the reader. The read goes on, and its blueprint and `check`
    carry the warning, the version the envelope's."""

    def newer(request: httpx.Request, response: httpx.Response) -> httpx.Response:
        if request.url.path != STATUS:
            return response
        return httpx.Response(response.status_code, json={**response.json(), "nautobot-version": "3.2.9"})

    with reader_over(newer) as other:
        result = read(other, scope=SCOPE, document=unprobed)
        checked = check(other)
    doc = taken(result)
    warned = ("nautobot.version.unverified", "warning", f"3.2.9/{other.golden_config}")
    assert [(f.rule, f.severity, f.object) for f in result.findings] == [warned]
    assert [(f.rule, f.severity, f.object) for f in checked] == [warned]
    assert doc["source"]["mapping"]["version"] == "3.2.9"


def test_a_scope_of_another_form_sends_nothing(unprobed: ReaderDocument) -> None:
    with reader() as own:
        sent = list(SENT[own])
        result = read(own, scope="site:lab", document=unprobed)
        assert SENT[own] == sent
    refused(result, ("scope.invalid", "site:lab"))


def test_a_list_cut_short_is_incomplete(unprobed: ReaderDocument) -> None:
    """In flight: Nautobot answers each list whole, so every answer of the interfaces list has its `count` raised by
    one on its way to the reader. The pager reads on until a page answers none, and holds one row fewer than the
    count; the close is taken after it, and nothing moved."""

    def raised(request: httpx.Request, response: httpx.Response) -> httpx.Response:
        if request.url.path != f"/api/{INTERFACES}":
            return response
        body = response.json()
        return httpx.Response(response.status_code, json={**body, "count": body["count"] + 1})

    with reader_over(raised) as short:
        result = read(short, scope=SCOPE, document=unprobed)
        asked = [request.path for request in SENT[short]].count(f"/api/{INTERFACES}")
    refused(result, ("read.incomplete", INTERFACE))
    assert asked == 2, "the pager ends at the page that answers none"
    assert "counted 16" in result.findings[0].message and "answered 15" in result.findings[0].message


def test_a_tag_on_no_device_and_one_nautobot_lacks(conn: Nautobot, box: Writes, unprobed: ReaderDocument) -> None:
    lacking = read(conn, scope=f"tag:{MISSING}", document=unprobed)
    refused(lacking, ("scope.empty", f"tag:{MISSING}"))
    assert lacking.empty is True and "lists no tag" in lacking.findings[0].message

    with making(box) as made:
        tag = made.post("extras/tags/", {"name": contract_name(), "content_types": ["dcim.device"]})
        bare = read(conn, scope=f"tag:{tag['name']}", document=unprobed)
    refused(bare, ("scope.empty", f"tag:{tag['name']}"))
    assert bare.empty is True and "no dcim.device carries" in bare.findings[0].message


def test_a_device_with_no_platform_and_a_pair_no_row_names(
    conn: Nautobot, box: Writes, unprobed: ReaderDocument
) -> None:
    """Three devices of the tier's own, tagged `fylgja`: one of no platform, whose render Golden Config refuses too,
    since the setting's path template renders `.j2` from a device of no platform (design/verified-facts.md); one of a
    platform of no manufacturer, which Nautobot takes and Golden Config renders; and one of a platform of `Nokia` that
    no row of the document names, which renders too."""
    with making(box) as made:
        maker = nokia(box)
        bare = made.post(PLATFORMS, {"name": contract_name(), "network_driver": "nokia_srl"})
        assert bare["manufacturer"] is None
        other = made.post(PLATFORMS, {"name": contract_name(), "manufacturer": maker, "network_driver": "nokia_srl"})
        none = made.device(platform=None)
        unmade = made.device(platform=bare["id"])
        unmatched = made.device(platform=other["id"])
        made.regroup()
        result = read(conn, scope=SCOPE, document=unprobed)
    refused(
        result,
        ("platform.missing", none["name"]),
        ("render.template.missing", none["name"]),
        ("platform.missing", unmade["name"]),
        ("platform.unmatched", unmatched["name"]),
    )
    (missing,) = [f for f in result.findings if f.rule == "render.template.missing"]
    assert "Jinja template .j2 not found in git repository fylgja-templates" in missing.message


def test_a_renamed_device_and_two_of_one_label(conn: Nautobot, box: Writes, unprobed: ReaderDocument) -> None:
    """`n1` renamed `N1`, then a device of the tier's own named `n1` beside it on the one location, which Nautobot
    takes (design/verified-facts.md); `n1`'s name is put back after."""
    n1 = seeded(box, "n1")
    with restored(box, f"{DEVICES}{n1['id']}/", ["name"]):
        box.patch(f"{DEVICES}{n1['id']}/", {"name": "N1"})
        result = read(conn, scope=SCOPE, document=unprobed)
        doc = taken(result)
        assert [(f.rule, f.severity, f.object) for f in result.findings] == [("device.name.renamed", "info", "N1")]
        assert [device["name"] for device in doc["network"]["devices"]] == ["n1", "n2", "n3"]
        assert doc["network"]["links"] == LINKS
        rows = [row for row in doc["source"]["fidelity"] if row["source"] == "dcim.device.name"]
        assert [(row["disposition"], row["object"]) for row in rows] == [("approximated", "N1")]

        with making(box) as made:
            made.device(name="n1")
            made.regroup()
            result = read(conn, scope=SCOPE, document=unprobed)
    refused(result, ("device.name.duplicate", "N1"), ("device.name.duplicate", "n1"))


def test_a_device_named_empty_is_unmappable(conn: Nautobot, box: Writes, unprobed: ReaderDocument) -> None:
    """A device named `""`, which Nautobot takes (design/verified-facts.md, "A device's `name` may be null, or
    empty."), tagged `fylgja` and of `n2`'s platform, its comments the tier's name: it is refused by its id, and its
    render, which Golden Config refused 400 for a device named `""` (design/verified-facts.md), is `render.failed`
    beside it, under the same object."""
    with making(box) as made:
        nameless = made.device(name="")
        made.regroup()
        assert nameless["name"] == ""
        result = read(conn, scope=SCOPE, document=unprobed)
    called = f"dcim.device {nameless['id']}"
    refused(result, ("device.name.unmappable", called), ("render.failed", called))


def test_each_cable_omitted_is_its_rule(conn: Nautobot, box: Writes, unprobed: ReaderDocument) -> None:
    """A device of the tier's own tagged `fylgja`, `near`, and one untagged of no platform, `far`, with a rear port, a
    front port and an interface: a cable from `near` to the front port; one to `far`'s interface, given no label so
    that it is named by its id; one between the seeded `n2 mgmt0` and `n3 mgmt0`; the installed `1x2 Breakout` from
    one of `near`'s interfaces to two more, a side of two terminations; and the breakout again from one of `near`'s to
    `n1 ethernet-1/10` and a third, the third then cabled to nothing, which maps by the two ends it has, a link
    (design/verified-facts.md, "A cable's `terminations` is one member a connector of a side"). Each cable but the
    one named by its id is labelled with the tier's name."""
    with making(box) as made:
        near = made.device()
        far = made.device(tags=[], platform=None)
        body = [{"device": near["id"], "name": f"e{i}", "type": "1000base-t", "status": "Active"} for i in range(1, 8)]
        ports = {row["name"]: row["id"] for row in box.post(INTERFACES, body)}
        rear = box.post("dcim/rear-ports/", {"device": far["id"], "name": "r1", "type": "8p8c", "positions": 1})
        front = {"device": far["id"], "name": "f1", "type": "8p8c", "rear_port": rear["id"], "rear_port_position": 1}
        front_port = box.post("dcim/front-ports/", front)["id"]
        outside = box.post(INTERFACES, {"device": far["id"], "name": "x1", "type": "1000base-t", "status": "Active"})
        made.regroup()
        breakout = box.one("dcim/cable-types/", name="1x2 Breakout")
        assert breakout is not None

        def cable(a: tuple[str, str], b: tuple[str, str], label: str) -> dict[str, Any]:
            return made.post(
                CABLES,
                {
                    "termination_a_type": a[0],
                    "termination_a_id": a[1],
                    "termination_b_type": b[0],
                    "termination_b_id": b[1],
                    "status": "Connected",
                    "label": label,
                },
            )

        def lanes(label: str, **ends: str) -> dict[str, Any]:
            held = {lane: {"object_type": INTERFACE, "id": id} for lane, id in ends.items()}
            body = {"cable_type": breakout["id"], "status": "Connected", "label": label, "terminations": held}
            return made.post(CABLES, body)

        named = {kind: contract_name() for kind in ("endpoint", "management", "ends", "leg")}
        cable((INTERFACE, ports["e1"]), ("dcim.frontport", front_port), named["endpoint"])
        unlabelled = cable((INTERFACE, ports["e2"]), (INTERFACE, outside["id"]), "")
        cable((INTERFACE, port(box, "n2", "mgmt0")), (INTERFACE, port(box, "n3", "mgmt0")), named["management"])
        lanes(named["ends"], a1=ports["e3"], b1=ports["e4"], b2=ports["e5"])
        leg = lanes(named["leg"], a1=ports["e6"], b1=port(box, "n1", "ethernet-1/10"), b2=ports["e7"])
        box.patch(f"{CABLES}{leg['id']}/", {"terminations": {"b2": None}})
        assert box.get(f"{CABLES}{leg['id']}/")["terminations"]["b2"] is None

        result = read(conn, scope=SCOPE, document=unprobed)
    doc = taken(result)
    omitted = [
        ("omit.cable.endpoint", named["endpoint"]),
        ("omit.cable.outside_scope", f"cable {unlabelled['id']}"),
        ("omit.cable.management", named["management"]),
        ("omit.cable.ends", named["ends"]),
    ]
    assert found(result) == sorted(omitted)
    assert {f.severity for f in result.findings} == {"info"}
    rows = [(row["disposition"], row["object"]) for row in doc["source"]["fidelity"] if row["source"] == "dcim.cable"]
    assert sorted(rows) == sorted(("omitted", what) for _, what in omitted)
    kept = {"a": {"device": near["name"], "interface": "e6"}, "b": {"device": "n1", "interface": "ethernet-1/10"}}
    assert doc["network"]["links"] == links(kept)


def test_a_device_in_no_setting_is_refused(conn: Nautobot, box: Writes, unprobed: ReaderDocument) -> None:
    """A device of the tier's own carrying a tag of the tier's own alone, which no setting's group's filter names, read
    under that tag: Golden Config renders it under no setting, and no group's filter lists it, so the read is refused
    by `render.setting.absent` alone. test_groups_contract.py holds the other case, a device the filter lists and the
    stored members lack, `group.stale` beside it."""
    with making(box) as made:
        tag = made.post("extras/tags/", {"name": contract_name(), "content_types": ["dcim.device"]})
        device = made.device(tags=[tag["id"]])
        result = read(conn, scope=f"tag:{tag['name']}", document=unprobed)
    refused(result, ("render.setting.absent", device["name"]))
    assert "No Golden Config settings found for this device" in result.findings[0].message


def test_a_template_the_repository_lacks(conn: Nautobot, box: Writes, unprobed: ReaderDocument) -> None:
    """A platform of the tier's own, of `Nokia` and of the network driver `DRIVER`, which a row of the document maps,
    and a device of it tagged `fylgja`, the group saved: the setting's path template names `arista_eos.j2`, which the
    repository lacks."""
    with making(box) as made:
        other = made.post(PLATFORMS, {"name": contract_name(), "manufacturer": nokia(box), "network_driver": DRIVER})
        device = made.device(platform=other["id"])
        made.regroup()
        result = read(conn, scope=SCOPE, document=owning(unprobed, other["name"]))
    refused(result, ("render.template.missing", device["name"]))
    assert f"Jinja template {DRIVER}.j2 not found in git repository" in result.findings[0].message


def test_a_template_raising_for_one_device_and_one_rendering_whitespace(box: Writes, unprobed: ReaderDocument) -> None:
    """A commit of the template repository whose template raises for `n2`, renders whitespace alone for `n3`, and
    renders `n1` as the tracked one does, pushed and rendered once by `box`, so that its head is fetched before the
    read and the bracket does not move under it: `n2` and `n3` are refused in the one read, each named alone, and
    `n1`, rendered, is quoted in no message. The tracked templates are pushed back after, and each seeded device
    rendered again."""
    text = (
        '{% if hostname == "n2" %}{{ nosuch.x }}{% elif hostname == "n3" %}{{ "   \\n" }}{% else %}'
        + TEMPLATE.read_text()
        + "{% endif %}\n"
    )
    ids = {row["name"]: row["id"] for row in box.listed(DEVICES, tags="fylgja")}
    commit = None
    try:
        commit = pushed(text)
        n1 = box.get(SEEDING.RENDER, device_id=ids["n1"])["intended_config"]
        with reader() as own:
            result = read(own, scope=SCOPE, document=unprobed)
            asked = [request.path for request in SENT[own]].count(RENDER)
    finally:
        if commit is not None:
            pushed(TEMPLATE.read_text())
            settle(box)
    refused(result, ("render.failed", "n2"), ("render.empty", "n3"))
    assert asked == 3, "each scoped device is rendered"
    assert quoted(result, {"n1": n1}) == []


def test_a_render_answered_otherwise(box: Writes, unprobed: ReaderDocument) -> None:
    """In flight: Golden Config answers a render 200 or 400 as the template and the device have it, and no other answer
    can be written into it, so on their way to the reader `n1`'s render is answered 502, `n2`'s 200 with no
    `intended_config`, and `n3`'s 400 in the words of a device not found. The close finds nothing moved, so the
    device not found stands."""
    ids = {row["id"]: row["name"] for row in box.listed(DEVICES, tags="fylgja")}

    def otherwise(request: httpx.Request, response: httpx.Response) -> httpx.Response:
        if request.url.path != RENDER:
            return response
        device = request.url.params["device_id"]
        if ids[device] == "n1":
            return httpx.Response(502, text="Bad Gateway", headers={"Content-Type": "text/plain"})
        if ids[device] == "n2":
            return httpx.Response(200, json={"intended_config_lines": [], "diff": None})
        if ids[device] == "n3":
            return httpx.Response(400, json={"detail": f"Device with id '{device}' not found"})
        return response

    with reader_over(otherwise) as own:
        result = read(own, scope=SCOPE, document=unprobed)
    refused(result, ("render.unavailable", "n1"), ("render.invalid", "n2"), ("render.device.unknown", "n3"))
    (unavailable,) = [f for f in result.findings if f.rule == "render.unavailable"]
    assert "HTTP 502" in unavailable.message and "Bad Gateway" not in unavailable.message


def test_the_probes_refusals(box: Writes, conn: Nautobot, document: ReaderDocument) -> None:
    """The seeded context `fylgja-probes` edited, one fault at a time, and put back after: set active; given a probe
    whose ends are on `n9`, which no device is; and its probe `n1-loop`'s first end given a gateway outside its
    address's prefix."""
    held = box.one("extras/config-contexts/", name=CONTEXT)
    assert held is not None
    path = f"extras/config-contexts/{held['id']}/"
    seed = held["data"]

    def setting(edit: Callable[[dict[str, Any]], dict[str, Any]] = lambda data: data, *, active: bool = False) -> None:
        box.patch(path, {"data": edit(copy.deepcopy(seed)), "is_active": active})

    def gateway(data: dict[str, Any]) -> dict[str, Any]:
        data["probes"][0]["endpoints"][0]["gateway"] = "10.1.11.1"
        return data

    n9 = {
        "name": "n9-loop",
        "format": "ping",
        "endpoints": [
            {"device": "n9", "interface": "ethernet-1/1", "address": "192.0.2.2/24", "gateway": "192.0.2.1"},
            {"device": "n9", "interface": "ethernet-1/2", "address": "198.51.100.2/24", "gateway": "198.51.100.1"},
        ],
    }
    with restored(box, path, ["data", "is_active"]):
        setting(active=True)
        refused(read(conn, scope=SCOPE, document=document), ("probe.context.active", CONTEXT))

        setting(lambda data: {**data, "probes": [*data["probes"], n9]})
        result = read(conn, scope=SCOPE, document=document)
        doc = taken(result)
        assert found(result) == [("omit.probe.outside_scope", "n9-loop")]
        assert [probe["name"] for probe in doc["probes"]] == ["n1-loop"]
        rows = [(row["disposition"], row["object"]) for row in doc["source"]["fidelity"] if row["source"] == SOURCE]
        assert rows == [("omitted", "n9-loop")]

        setting(gateway)
        refused(read(conn, scope=SCOPE, document=document), ("probe.gateway.outside", "n1-loop"))


def test_the_view_only_accounts_render_is_smaller_and_no_error(conn: Nautobot, box: Writes) -> None:
    """An account of the tier's own whose one grant is `view` on `dcim.device`, made as plan 1 makes the reader's and
    deleted after: Golden Config runs the setting's query under the rendering account's grants, so its render of `n1`
    is answered 200 and holds none of the interface lines the reader's render holds. This is the README's known limit:
    an account that sees less gets a smaller configuration and no error, which the reader cannot tell
    (design/verified-facts.md, "The query runs with the rendering account's grants, and a render of what the account
    cannot see is answered 200 without it.")."""
    n1 = seeded(box, "n1")["id"]
    full = conn.render(n1)
    assert full.status == 200 and full.text is not None
    lines = [line for line in full.text.splitlines() if line.startswith("set / interface ")]
    assert lines, "the reader's render holds the interface lines"
    with account(box, [("dcim.device", "view")]) as token:
        viewer = writer(os.environ[ADDRESS], token)
        try:
            answer = viewer.get(SEEDING.RENDER, device_id=n1)
        finally:
            viewer.close()
    text = answer.get("intended_config") if isinstance(answer, dict) else None
    assert isinstance(text, str)
    assert "set / system name host-name n1" in text.splitlines()
    assert [line for line in lines if line in text.splitlines()] == []
