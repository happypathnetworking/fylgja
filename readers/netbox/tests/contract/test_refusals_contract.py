"""Each rule of the reader provoked on the development NetBox (D-095, D-096; rules.md): a branch NetBox lacks and one
not `ready`; a NetBox naming no branching plugin; a scope of another form; a list answered short of its count; a
device with no platform, a platform with no manufacturer and a pair no row of the document holds; a device renamed to
its label, two of one label and one with no name; each cable the mapping omits; a device with no template, a template
failing for one device and one rendering nothing for one, three devices at fault three ways at once, and a render
answered otherwise; and the probes' refusals. Each test writes under its own branch's header, through `box`, and reads
that branch by its name with the reader's token. A provocation NetBox cannot be written into is made in flight by
`reader_over`, the test saying so and why. No assertion message prints the address or a token."""

from __future__ import annotations

import copy
import re
import secrets
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest

from fylgja_netbox import NetBox, ReaderDocument, Result, check, read
from fylgja_netbox.document import Match
from fylgja_netbox.rows import Branch

from .conftest import BRANCHES, PREFIX, SENT, Sent, Writes, branched, delete, reader, reader_over

SCOPE = "tag:fylgja"
CONTEXT = "fylgja-probes"
SOURCE = "extras.configcontext"
MISSING = "fylgja-contract-none"
"""A branch NetBox lacks: no branch of the tier's own, which are named by 8 hex digits."""

LINKS = [
    {"a": {"device": "n1", "interface": "ethernet-1/1"}, "b": {"device": "n2", "interface": "ethernet-1/1"}},
    {"a": {"device": "n2", "interface": "ethernet-1/2"}, "b": {"device": "n3", "interface": "ethernet-1/1"}},
]
"""The seeded fixture's two links on `main`."""

UNREADY = re.compile(r"is (new|provisioning), not ready")
"""What `branch.unready` says of a branch just made: its status, `new` then `provisioning` before `ready`
(design/verified-facts.md, "A branch deleted before it is `ready`")."""


@pytest.fixture(scope="module")
def unprobed(document: ReaderDocument) -> ReaderDocument:
    """The seeded fixture network's reader document, naming no configuration context of probes."""
    return ReaderDocument(document.platforms, None)


def found(result: Result) -> list[tuple[str, str | None]]:
    """Every finding's rule and object, the version warning aside, sorted."""
    return sorted((f.rule, f.object) for f in result.findings if f.rule != "netbox.version.unverified")


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


def seeded(box: Writes, branch: Branch, name: str = "n1") -> dict[str, Any]:
    """The seeded device `name` under the branch's header, whose device type, role, site, platform and tag a device the
    test makes takes."""
    held = box.one("dcim/devices/", branch=branch.schema_id, name=name)
    assert held is not None, name
    return held


def made(box: Writes, branch: Branch, **body: object) -> dict[str, Any]:
    """A device made under the branch's header of `n1`'s device type, role, site and platform, tagged `fylgja`, with
    `body` over them; a member given None is left out."""
    like = seeded(box, branch)
    held: dict[str, object] = {
        "device_type": like["device_type"]["id"],
        "role": like["role"]["id"],
        "site": like["site"]["id"],
        "platform": like["platform"]["id"],
        "status": "active",
        "tags": [tag["id"] for tag in like["tags"]],
    }
    held.update(body)
    return dict(box.post("dcim/devices/", {k: v for k, v in held.items() if v is not None}, branch=branch.schema_id))


def port(box: Writes, branch: Branch, device: str, name: str) -> int:
    """The id of the seeded interface `device:name` under the branch's header."""
    held = box.one("dcim/interfaces/", branch=branch.schema_id, device_id=seeded(box, branch, device)["id"], name=name)
    assert held is not None, f"{device}:{name}"
    return int(held["id"])


def template(box: Writes, branch: Branch) -> dict[str, Any]:
    """The seeded configuration template `fylgja-srlinux` under the branch's header."""
    held = box.one("extras/config-templates/", branch=branch.schema_id, name="fylgja-srlinux")
    assert held is not None
    return held


def coded(box: Writes, branch: Branch, code: Callable[[str], str]) -> None:
    """The template `fylgja-srlinux`'s code set under the branch's header to `code` of its own."""
    held = template(box, branch)
    body = {"template_code": code(held["template_code"])}
    box.patch(f"extras/config-templates/{held['id']}/", body, branch=branch.schema_id)


def rendered(box: Writes, device: int, schema_id: str | None = None) -> str:
    """The configuration NetBox renders for the device, through the tests' writer: `{configtemplate, content}`."""
    return str(box.post(f"dcim/devices/{device}/render-config/", None, branch=schema_id)["content"])


def renders(sent: list[Sent]) -> list[str]:
    """The device ids a connection asked renders of, in the order asked."""
    return [m[1] for _, path in sent if (m := re.fullmatch(r"/api/dcim/devices/(\d+)/render-config/", path))]


def seeded_on_main(box: Writes, name: str) -> int:
    """The id of the seeded device `name` on `main`."""
    held = box.one("dcim/devices/", name=name)
    assert held is not None, name
    return int(held["id"])


OWN = "fc-own"
"""A platform the tests make, of the manufacturer `Nokia` and with no template."""


def untemplated(box: Writes, branch: Branch) -> int:
    """The id of a platform `OWN` made under the branch's header, of `n1`'s platform's manufacturer and with no
    template."""
    nokia = box.get(f"dcim/platforms/{seeded(box, branch)['platform']['id']}/", branch=branch.schema_id)["manufacturer"]
    own = box.post("dcim/platforms/", {"name": OWN, "slug": OWN, "manufacturer": nokia["id"]}, branch=branch.schema_id)
    assert own["config_template"] is None
    return int(own["id"])


def owning(document: ReaderDocument) -> ReaderDocument:
    """`document` with a row mapping `OWN` too, so that a device of it is no `platform.unmatched`."""
    return ReaderDocument((*document.platforms, Match("Nokia", OWN, "nokia_srlinux")), document.probes)


def quoted(result: Result, configs: dict[str, str]) -> list[str]:
    """The lines of `configs` some finding's message holds, a line of whitespace alone aside."""
    lines = {line for text in configs.values() for line in text.splitlines() if line.strip()}
    return sorted(line for line in lines if any(line in f.message for f in result.findings))


def probe(name: str, device: str, *ends: tuple[str, str, str]) -> dict[str, Any]:
    """A probe of the format `ping` whose endpoints are `ends`, each `(interface, address, gateway)` on `device`."""
    return {
        "name": name,
        "format": "ping",
        "endpoints": [{"device": device, "interface": i, "address": a, "gateway": g} for i, a, g in ends],
    }


def test_a_branch_netbox_lacks_and_one_not_ready(conn: NetBox, box: Writes, unprobed: ReaderDocument) -> None:
    """The branch just made is read before it is `ready`, then waited for until it is, and only then deleted: NetBox
    refuses a `DELETE` of a branch still provisioning, 500, and the branch stays (design/verified-facts.md, "A branch
    deleted before it is `ready`")."""
    refused(read(conn, branch=MISSING, scope=SCOPE, document=unprobed), ("branch.unknown", MISSING))
    assert [(f.rule, f.object) for f in check(conn, branch=MISSING)] == [("branch.unknown", MISSING)]

    name = PREFIX + secrets.token_hex(4)
    box.post(BRANCHES, {"name": name})
    try:
        result = read(conn, branch=name, scope=SCOPE, document=unprobed)
        checked = check(conn, branch=name)
    finally:
        try:
            branched(box, name)
        finally:
            delete(box, name)
    refused(result, ("branch.unready", name))
    assert [(f.rule, f.object) for f in checked] == [("branch.unready", name)]
    assert all(UNREADY.search(f.message) for f in (*result.findings, *checked)), "the status is given verbatim"


def test_a_netbox_naming_no_plugin_refuses_a_branch(unprobed: ReaderDocument) -> None:
    """In flight: the development NetBox has the branching plugin, and one without it is another install, so the
    plugin is taken out of `/api/status/`'s answer on its way to the reader. A branch asked of it sends nothing more,
    and the pair `4.7.5/none` is no pair the reader was verified on."""

    def bare(request: httpx.Request, response: httpx.Response) -> httpx.Response:
        if request.url.path != "/api/status/":
            return response
        return httpx.Response(response.status_code, json={**response.json(), "plugins": {}})

    with reader_over(bare) as alone:
        assert alone.branching is None
        result = read(alone, branch=MISSING, scope=SCOPE, document=unprobed)
        checked = check(alone, branch=MISSING)
        assert SENT[alone] == [Sent("GET", "/api/status/")]
    refused(result, ("branch.unsupported", MISSING))
    warned = ("netbox.version.unverified", "warning", f"{alone.version}/none")
    assert [(f.rule, f.severity, f.object) for f in result.findings if f.severity == "warning"] == [warned]
    unsupported = ("branch.unsupported", "error", MISSING)
    assert sorted((f.rule, f.severity, f.object) for f in checked) == sorted([unsupported, warned])


def test_a_scope_of_another_form_sends_nothing(unprobed: ReaderDocument) -> None:
    with reader() as own:
        sent = list(SENT[own])
        result = read(own, branch=None, scope="site:lab", document=unprobed)
        assert SENT[own] == sent
    refused(result, ("scope.invalid", "site:lab"))


def test_a_list_cut_short_is_incomplete(unprobed: ReaderDocument) -> None:
    """In flight: NetBox answers each list whole, so every answer of the interfaces list has its `count` raised by one
    on its way to the reader. The pager reads on until a page answers none, and holds one row fewer than the count. A
    single row cut from the first answer would not do: the pager asks the next offset and reads the list whole."""

    def raised(request: httpx.Request, response: httpx.Response) -> httpx.Response:
        if request.url.path != "/api/dcim/interfaces/":
            return response
        body = response.json()
        return httpx.Response(response.status_code, json={**body, "count": body["count"] + 1})

    with reader_over(raised) as short:
        result = read(short, branch=None, scope=SCOPE, document=unprobed)
        asked = [path for _, path in SENT[short]].count("/api/dcim/interfaces/")
    refused(result, ("read.incomplete", "dcim.interface"))
    assert asked == 2, "the pager ends at the page that answers none"
    assert "counted 16" in result.findings[0].message and "answered 15" in result.findings[0].message


def test_a_device_with_no_platform_and_a_platform_with_no_manufacturer(
    conn: NetBox, box: Writes, branch: Branch, unprobed: ReaderDocument
) -> None:
    """Each device is given the template `fylgja-srlinux` of its own, so that its render, which a platform otherwise
    gives it, is no fault beside the platform's."""
    code = template(box, branch)["id"]
    bare = box.post("dcim/platforms/", {"name": "fc-bare", "slug": "fc-bare"}, branch=branch.schema_id)
    made(box, branch, name="fc-none", platform=None, config_template=code)
    made(box, branch, name="fc-unmade", platform=bare["id"], config_template=code)
    result = read(conn, branch=branch.name, scope=SCOPE, document=unprobed)
    refused(result, ("platform.missing", "fc-none"), ("platform.missing", "fc-unmade"))


def test_a_platform_no_row_names_is_unmatched(conn: NetBox) -> None:
    other = ReaderDocument((Match("Nokia", "SR OS", "nokia_srlinux"),), None)
    result = read(conn, branch=None, scope=SCOPE, document=other)
    refused(result, *(("platform.unmatched", name) for name in ("n1", "n2", "n3")))


def test_a_renamed_device_and_two_of_one_label(
    conn: NetBox, box: Writes, branch: Branch, unprobed: ReaderDocument
) -> None:
    """`n1` renamed `N1`, and a device `n1` beside it on a second site: NetBox refuses two names that differ in letter
    case alone on one site, and takes them on two (design/verified-facts.md, "A device's name, per site")."""
    n1 = seeded(box, branch)
    box.patch(f"dcim/devices/{n1['id']}/", {"name": "N1"}, branch=branch.schema_id)
    result = read(conn, branch=branch.name, scope=SCOPE, document=unprobed)
    doc = taken(result)
    assert [(f.rule, f.severity, f.object) for f in result.findings] == [("device.name.renamed", "info", "N1")]
    assert [device["name"] for device in doc["network"]["devices"]] == ["n1", "n2", "n3"]
    assert doc["network"]["links"] == LINKS
    rows = [row for row in doc["source"]["fidelity"] if row["source"] == "dcim.device.name"]
    assert [(row["disposition"], row["object"]) for row in rows] == [("approximated", "N1")]

    second = {"name": "fc-second", "slug": "fc-second", "status": "active"}
    made(box, branch, name="n1", site=box.post("dcim/sites/", second, branch=branch.schema_id)["id"])
    result = read(conn, branch=branch.name, scope=SCOPE, document=unprobed)
    refused(result, ("device.name.duplicate", "N1"), ("device.name.duplicate", "n1"))


def test_a_device_with_no_name_is_unmappable(
    conn: NetBox, box: Writes, branch: Branch, unprobed: ReaderDocument
) -> None:
    nameless = made(box, branch, name=None)
    assert nameless["name"] is None
    result = read(conn, branch=branch.name, scope=SCOPE, document=unprobed)
    refused(result, ("device.name.unmappable", f"dcim.device {nameless['id']}"))


def test_each_cable_omitted_is_its_rule(conn: NetBox, box: Writes, branch: Branch, unprobed: ReaderDocument) -> None:
    """An end on a front port; an end on a device with no tag, the cable given no label so that it is named by its
    id; an end on a management port; and the two shapes of a side of other than one termination that NetBox takes,
    two interfaces on side A and two on side B (design/verified-facts.md, "A cable from an interface to a front port
    was taken"). A cable with no B side NetBox refuses 400, so that shape is the pure tier's alone."""
    under = branch.schema_id
    far = made(box, branch, name="fc-far", tags=[], platform=None)["id"]
    rear = box.post("dcim/rear-ports/", {"device": far, "name": "r1", "type": "8p8c", "positions": 1}, branch=under)
    front = {"device": far, "name": "f1", "type": "8p8c", "rear_port": rear["id"], "rear_port_position": 1}
    front_port = box.post("dcim/front-ports/", front, branch=under)["id"]
    outside = box.post("dcim/interfaces/", {"device": far, "name": "e1", "type": "1000base-t"}, branch=under)["id"]

    def end(*ids: int, kind: str = "dcim.interface") -> list[dict[str, object]]:
        return [{"object_type": kind, "object_id": id} for id in ids]

    def p(device: str, name: str) -> int:
        return port(box, branch, device, name)

    cables = {
        "fc-endpoint": (end(p("n1", "ethernet-1/10")), end(front_port, kind="dcim.frontport")),
        "": (end(p("n1", "ethernet-1/11")), end(outside)),
        "fc-management": (end(p("n2", "mgmt0")), end(p("n3", "mgmt0"))),
        "fc-ends-a": (end(p("n2", "ethernet-1/10"), p("n2", "ethernet-1/11")), end(p("n3", "ethernet-1/10"))),
        "fc-ends-b": (end(p("n1", "ethernet-1/2")), end(p("n3", "ethernet-1/2"), p("n3", "ethernet-1/11"))),
    }
    ids = {}
    for label, (a, b) in cables.items():
        body = {"a_terminations": a, "b_terminations": b, "status": "connected", "label": label}
        ids[label] = box.post("dcim/cables/", body, branch=under)["id"]

    result = read(conn, branch=branch.name, scope=SCOPE, document=unprobed)
    doc = taken(result)
    omitted = [
        ("omit.cable.endpoint", "fc-endpoint"),
        ("omit.cable.outside_scope", f"cable {ids['']}"),
        ("omit.cable.management", "fc-management"),
        ("omit.cable.ends", "fc-ends-a"),
        ("omit.cable.ends", "fc-ends-b"),
    ]
    assert found(result) == sorted(omitted)
    assert {f.severity for f in result.findings} == {"info"}
    rows = [(row["disposition"], row["object"]) for row in doc["source"]["fidelity"] if row["source"] == "dcim.cable"]
    assert sorted(rows) == sorted(("omitted", what) for _, what in omitted)
    assert doc["network"]["links"] == LINKS


def test_a_device_with_no_template_is_refused(
    conn: NetBox, box: Writes, branch: Branch, unprobed: ReaderDocument
) -> None:
    """A platform of its own, of the manufacturer `Nokia` and with no template, which a row of the document maps, so
    that the render is the device's one fault."""
    made(box, branch, name="fc-bare", platform=untemplated(box, branch))
    result = read(conn, branch=branch.name, scope=SCOPE, document=owning(unprobed))
    refused(result, ("render.template.missing", "fc-bare"))


def test_a_template_failing_for_one_device_refuses_it_alone(
    box: Writes, branch: Branch, unprobed: ReaderDocument
) -> None:
    """The template of design/verified-facts.md, "A template that fails for one device refuses that device alone":
    `n2`'s render fails, and `n1`'s and `n3`'s are still asked and rendered."""
    coded(box, branch, lambda code: '{% if device.name == "n2" %}{{ device.nosuch.x }}{% endif %}' + code)
    held = {row["name"]: row["id"] for row in box.listed("dcim/devices/", branch=branch.schema_id, tag="fylgja")}
    with reader() as own:
        result = read(own, branch=branch.name, scope=SCOPE, document=unprobed)
        asked = renders(SENT[own])
    refused(result, ("render.failed", "n2"))
    assert asked == [str(held[name]) for name in ("n1", "n2", "n3")]
    others = {name: rendered(box, held[name], branch.schema_id) for name in ("n1", "n3")}
    assert quoted(result, others) == []


def test_a_template_rendering_nothing_for_one_device(
    conn: NetBox, box: Writes, branch: Branch, unprobed: ReaderDocument
) -> None:
    """`n3`'s render is a newline alone, written as an expression, since NetBox strips the whitespace around a
    template's code (design/verified-facts.md, "A template that renders nothing answers 200 with no byte")."""
    coded(box, branch, lambda code: '{% if device.name == "n3" %}{{ "\\n" }}{% else %}' + code + "{% endif %}")
    result = read(conn, branch=branch.name, scope=SCOPE, document=unprobed)
    refused(result, ("render.empty", "n3"))


def test_three_devices_at_fault_three_ways_in_one_read(
    conn: NetBox, box: Writes, branch: Branch, unprobed: ReaderDocument
) -> None:
    """`n2`'s template failing, `n3`'s rendering a newline alone, and a device of a platform with no template: each
    filed in the one read, and no message holds a line of `n1`'s configuration."""
    coded(
        box,
        branch,
        lambda code: (
            '{% if device.name == "n2" %}{{ device.nosuch.x }}{% endif %}'
            '{% if device.name == "n3" %}{{ "\\n" }}{% else %}' + code + "{% endif %}"
        ),
    )
    made(box, branch, name="fc-bare", platform=untemplated(box, branch))
    result = read(conn, branch=branch.name, scope=SCOPE, document=owning(unprobed))
    refused(result, ("render.failed", "n2"), ("render.empty", "n3"), ("render.template.missing", "fc-bare"))
    n1 = seeded(box, branch)["id"]
    assert quoted(result, {"n1": rendered(box, n1, branch.schema_id)}) == []


def test_a_render_answered_otherwise_is_unavailable(box: Writes, unprobed: ReaderDocument) -> None:
    """In flight: the development NetBox answers a render 200, 400 or 500 as its template has it, and no other status
    can be written into it, so `n1`'s render is answered 502 on its way to the reader."""
    n1 = seeded_on_main(box, "n1")

    def gateway(request: httpx.Request, response: httpx.Response) -> httpx.Response:
        if request.url.path != f"/api/dcim/devices/{n1}/render-config/":
            return response
        return httpx.Response(502, text="Bad Gateway", headers={"Content-Type": "text/plain"})

    with reader_over(gateway) as own:
        result = read(own, branch=None, scope=SCOPE, document=unprobed)
    refused(result, ("render.unavailable", "n1"))
    assert "HTTP 502" in result.findings[0].message
    assert "Bad Gateway" not in result.findings[0].message


def test_a_render_of_another_content_type_is_invalid(box: Writes, unprobed: ReaderDocument) -> None:
    """In flight: the development NetBox answers a render asked as `text/plain` in `text/plain`, so `n2`'s render's
    content type is made NetBox's JSON envelope's on its way to the reader."""
    n2 = seeded_on_main(box, "n2")

    def enveloped(request: httpx.Request, response: httpx.Response) -> httpx.Response:
        if request.url.path != f"/api/dcim/devices/{n2}/render-config/":
            return response
        return httpx.Response(200, content=response.content, headers={"Content-Type": "application/json"})

    with reader_over(enveloped) as own:
        result = read(own, branch=None, scope=SCOPE, document=unprobed)
    refused(result, ("render.invalid", "n2"))
    assert "application/json" in result.findings[0].message


@pytest.fixture
def context(box: Writes, branch: Branch) -> Iterator[Callable[..., None]]:
    """A function that sets the context `fylgja-probes` under the branch's header: its `data`, edited from the seed's
    by a function of a copy of it, and its `is_active`."""
    held = box.one("extras/config-contexts/", branch=branch.schema_id, name=CONTEXT)
    assert held is not None
    seed = held["data"]

    def setting(edit: Callable[[dict[str, Any]], dict[str, Any]] = lambda data: data, *, active: bool = False) -> None:
        body = {"data": edit(copy.deepcopy(seed)), "is_active": active}
        box.patch(f"extras/config-contexts/{held['id']}/", body, branch=branch.schema_id)

    yield setting


def test_the_probes_refusals(
    conn: NetBox, branch: Branch, document: ReaderDocument, context: Callable[..., None]
) -> None:
    """The seeded context's data edited under the branch's header, one fault at a time, the seeded probe `n1-loop`'s
    ends on `n1 ethernet-1/10` (`10.1.10.2/24` by `10.1.10.1`) and `n1 ethernet-1/11` (`10.1.11.2/24` by
    `10.1.11.1`)."""

    def read_branch() -> Result:
        return read(conn, branch=branch.name, scope=SCOPE, document=document)

    def ends(data: dict[str, Any], **over: Any) -> dict[str, Any]:
        """`data` with the first probe's first endpoint's members `over`, a member given None taken out."""
        end = data["probes"][0]["endpoints"][0]
        end.update(over)
        for member in [member for member, value in over.items() if value is None]:
            del end[member]
        return data

    context(active=True)
    refused(read_branch(), ("probe.context.active", CONTEXT))

    n9 = probe(
        "n9-loop",
        "n9",
        ("ethernet-1/1", "192.0.2.2/24", "192.0.2.1"),
        ("ethernet-1/2", "198.51.100.2/24", "198.51.100.1"),
    )
    context(lambda data: {**data, "probes": [*data["probes"], n9]})
    result = read_branch()
    doc = taken(result)
    assert found(result) == [("omit.probe.outside_scope", "n9-loop")]
    assert [probe["name"] for probe in doc["probes"]] == ["n1-loop"]
    rows = [(row["disposition"], row["object"]) for row in doc["source"]["fidelity"] if row["source"] == SOURCE]
    assert rows == [("omitted", "n9-loop")]

    twice = probe(
        "n1-loop", "n1", ("ethernet-1/10", "10.1.10.3/24", "10.1.10.1"), ("ethernet-1/11", "10.1.11.3/24", "10.1.11.1")
    )
    faults: list[tuple[Callable[[dict[str, Any]], dict[str, Any]], tuple[str, str]]] = [
        (lambda data: ends(data, gateway="10.1.11.1"), ("probe.gateway.outside", "n1-loop")),
        (lambda data: ends(data, address="10.1.11.2/24", gateway="10.1.11.1"), ("probe.address.duplicate", "n1-loop")),
        (lambda data: {**data, "probes": [*data["probes"], twice]}, ("probe.name.duplicate", "n1-loop")),
        (lambda data: {**data, "probes_version": "2"}, ("probes.version.unsupported", CONTEXT)),
        (lambda data: ends(data, gateway=None), ("probes.invalid", "n1-loop")),
    ]
    judged = []
    for edit, wanted in faults:
        context(edit)
        result = read_branch()
        judged.append((wanted, result.blueprint is None, found(result)))
    assert judged == [(wanted, True, [wanted]) for _, wanted in faults], "each of the declaration's rules, in turn"
