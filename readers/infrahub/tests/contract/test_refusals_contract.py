"""Each refusal of the reader's provoked on purpose on the development Infrahub (CONTRIBUTING.md, Test tiers;
design/verified-facts.md, "Infrahub 1.11.11"). A test that writes does so with the tier's writer on a branch of its own
made from `main`, and reads that branch with the reader at `head`, asked `QUIET_S` after its last write; a test that
writes nothing reads `main` at its `head`. What the writer may not write, a schema without `DcimCable.label`, and a
list cut short, which a pinned read of a real Infrahub never answers, are made in flight: the test's reader is given a
transport of its own (`Altered`) that passes every request to a real one and alters the answers it names on their way
back. Each test asserts the rule, the object, that no blueprint is given and that no other device is named, comparing
plain values, so that a failing one prints no blueprint, no address and no token. The session's last test holds every
request the reader's connections sent to reads (conftest, `Recorded`)."""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from fylgja_infrahub import Infrahub, ReaderDocument, Refused, Result, check_schema, head, read, times
from fylgja_infrahub.artifacts import RULE_MISMATCH, RULE_MISSING, RULE_UNREADY
from fylgja_infrahub.document import Match
from fylgja_infrahub.mapping import RULE_PLATFORM_UNMATCHED
from fylgja_infrahub.rows import RULE_INCOMPLETE, Stamp
from fylgja_infrahub.schema import RULE_FIELD_MISSING
from fylgja_infrahub.stale import RULE_STALE, counted

from .conftest import LAST, SENT, reader, real
from .writer import Writer

QUIET_S = 10.0
"""Seconds a test waits after its last write before it asks `head`: a write's events are logged up to 5.92 s after it
(design/verified-facts.md, "Infrahub 1.11.11")."""

SETTLE_S = 60.0
"""How long `head` is asked again, `QUIET_S` apart, while it is refused for a list not whole alone (P3-36)."""

DEVICES = ("n1", "n2", "n3")
ADDED = "n9"
"""The seed's three devices, and the one a test adds to the scope."""

DEFINITION = "device-config"
"""The artifact definition the registration made, which names its artifacts so too (`.infrahub.yml`)."""

SERIAL = "FYLGJA-CONTRACT-serial"
"""A serial number for `n1`, which the template does not render (`infrahub/templates/device_config.j2`)."""

FREE = {"n1": "ethernet-1/2", "n2": "ethernet-1/11"}
"""A port of `n1`'s and one of `n2`'s that no cable of `main`'s ends, which the removal test's cable joins."""

LABEL = "n1:ethernet-1/2|n2:ethernet-1/11"

GENERATED_S = 180.0
"""How long a regeneration is waited for: the readings' took 9.2 s and 14.1 s (design/verified-facts.md)."""

POLL_S = 2.0

ARTIFACTS = """
query ($device: String!, $name: String!) {
  DcimDevice(name__value: $device) {
    edges { node { artifacts(name__value: $name) { edges { node {
      id status { value } checksum { value updated_at }
    } } } } }
  }
}
"""
INTERFACES = """
query ($device: String!) {
  DcimDevice(name__value: $device) { edges { node { interfaces { edges {
    node_metadata { updated_at updated_by { id } created_at } node { id name { value } }
  } } } } }
}
"""
DEFINITIONS = "query ($name: String!) { CoreArtifactDefinition(name__value: $name) { edges { node { id } } } }"
GROUPS = """
query { CoreGraphQLQueryGroup(group_type__value: "internal") { edges { node_metadata { created_by { id } } } } }
"""


class Altered(httpx.BaseTransport):
    """A transport of a test's own: every request passed to a real transport (conftest, `real`), and the body of each
    answer `picks` names given to `alter` on its way back, the answer then made anew around what it returns. `altered`
    counts the answers altered."""

    def __init__(self, picks: Callable[[httpx.Request], bool], alter: Callable[[bytes], bytes]) -> None:
        self.inner = real()
        self.picks = picks
        self.alter = alter
        self.altered = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self.inner.handle_request(request)
        if not self.picks(request):
            return response
        try:
            body = response.read()
        finally:
            response.close()
        self.altered += 1
        # The body read is decoded, and a new one is counted afresh.
        framing = ("content-length", "content-encoding")
        kept = [(k, v) for k, v in response.headers.multi_items() if k.lower() not in framing]
        return httpx.Response(response.status_code, headers=kept, content=self.alter(body), request=request)

    def close(self) -> None:
        self.inner.close()


def operation(request: httpx.Request) -> str | None:
    """The name of the GraphQL operation a POST asks for; None for any other request."""
    if request.method != "POST":
        return None
    named = json.loads(request.content).get("operationName")
    return named if isinstance(named, str) else None


def errors(result: Result) -> list[tuple[str, str | None]]:
    """The errors of a result, by rule and object."""
    return [(f.rule, f.object) for f in result.findings if f.severity == "error"]


def named(result: Result) -> set[str]:
    """The devices any finding of a result names as its object."""
    return {f.object for f in result.findings if f.object in (*DEVICES, ADDED)}


def settled(conn: Infrahub, branch: str, scope: str) -> str:
    """`head` of `branch`, asked `QUIET_S` after the test's last write, and again `QUIET_S` on while it is refused for a
    list not whole alone, as one is while the event log grows under its pager, within `SETTLE_S` (P3-36)."""
    deadline = time.monotonic() + SETTLE_S
    while True:
        time.sleep(QUIET_S)
        try:
            return head(conn, branch=branch, scope=scope)
        except Refused as e:
            if any(f.rule != RULE_INCOMPLETE for f in e.findings) or time.monotonic() > deadline:
                raise


def generated(writer: Writer, branch: str, device: str) -> dict[str, Any]:
    """`device`'s one artifact `DEFINITION` on `branch`, as the writer reads it: its id, status and checksum, the
    checksum's stamp among it."""
    (held,) = writer.gql(branch, ARTIFACTS, {"device": device, "name": DEFINITION})["DcimDevice"]["edges"]
    found: dict[str, Any]
    ((found,),) = [[edge["node"] for edge in held["node"]["artifacts"]["edges"]]]
    return found


def artifact(writer: Writer, branch: str, device: str) -> tuple[str, str | None]:
    """The id and the checksum of `device`'s one artifact `DEFINITION` on `branch`, as the writer reads them."""
    found = generated(writer, branch, device)
    return found["id"], found["checksum"]["value"]


def regenerate(writer: Writer, branch: str, before: dict[str, str | None]) -> None:
    """Ask the generation for every target, as `infrahub/seed/seed.py`'s `generate` asks it, and wait until each device
    of `before` has a checksum other than the one given there, `Ready`, then `QUIET_S` more for the task workers' group
    writes."""
    (definition,) = writer.gql(branch, DEFINITIONS, {"name": DEFINITION})["CoreArtifactDefinition"]["edges"]
    writer.rest("POST", f"/api/artifact/generate/{definition['node']['id']}", params={"branch": branch},
                body={"nodes": []})
    started = time.monotonic()
    while True:
        now = {device: generated(writer, branch, device) for device in before}
        if all(now[d]["checksum"]["value"] != before[d] and now[d]["status"]["value"] == "Ready" for d in before):
            break
        assert time.monotonic() - started < GENERATED_S, f"{sorted(before)} not regenerated within {GENERATED_S:g} s"
        time.sleep(POLL_S)
    time.sleep(QUIET_S)


def port(writer: Writer, branch: str, device: str, name: str) -> tuple[str, Stamp]:
    """The id of `device`'s interface `name` on `branch`, and its stamp, as the writer reads them."""
    (held,) = writer.gql(branch, INTERFACES, {"device": device})["DcimDevice"]["edges"]
    edges = [edge for edge in held["node"]["interfaces"]["edges"] if edge["node"]["name"]["value"] == name]
    ((meta, found),) = [(edge["node_metadata"], edge["node"]["id"]) for edge in edges]
    return found, Stamp(meta["updated_at"], (meta["updated_by"] or {}).get("id"), meta["created_at"])


def workers(writer: Writer, branch: str) -> frozenset[str]:
    """The accounts that made the internal query groups on `branch`: the task workers', as the stale rule tells them."""
    edges = writer.gql(branch, GROUPS)["CoreGraphQLQueryGroup"]["edges"]
    return frozenset(edge["node_metadata"]["created_by"]["id"] for edge in edges if edge["node_metadata"]["created_by"])


def test_a_device_added_to_the_scope_has_no_artifact(
    conn: Infrahub, writer: Writer, seed: dict[str, Any], document: ReaderDocument
) -> None:
    """A `DcimDevice` made on the branch with the scope's tag and the seed's platform, a member of no group the artifact
    definition generates for: `artifact.missing` for it alone. Its `node.created` names the platform among its related
    nodes, and it moves the platform's node stamp, which every device reads; neither names another device, since the
    platform counts through its own events and its `name` stamp alone (P3-42, P3-44; design/verified-facts.md, "A
    device made on the scope's platform", "The platform's node stamp moves with a device made on it")."""
    tag = seed["scope"].removeprefix("tag:")
    with writer.branch() as branch:
        made = {
            "name": {"value": ADDED},
            "location": {"id": writer.named(branch, "LocationSite", "lab")},
            "platform": {"id": writer.named(branch, "DcimPlatform", "SR Linux")},
            "tags": [{"id": writer.named(branch, "BuiltinTag", tag)}],
        }
        writer.mutate(branch, "DcimDeviceCreate", made)
        at = settled(conn, branch, seed["scope"])
        result = read(conn, branch=branch, at=at, scope=seed["scope"], document=document)
    assert errors(result) == [(RULE_MISSING, ADDED)]
    assert (result.blueprint is None, named(result)) == (True, {ADDED})


def test_an_artifact_not_ready_is_refused(
    conn: Infrahub, writer: Writer, seed: dict[str, Any], document: ReaderDocument
) -> None:
    """`n1`'s artifact's status written `Pending` on the branch, which `CoreArtifactUpdate` accepts, its checksum and
    storage id left as they were (design/verified-facts.md): `artifact.unready` for `n1` alone, naming the status."""
    with writer.branch() as branch:
        found, _ = artifact(writer, branch, "n1")
        writer.mutate(branch, "CoreArtifactUpdate", {"id": found, "status": {"value": "Pending"}})
        at = settled(conn, branch, seed["scope"])
        result = read(conn, branch=branch, at=at, scope=seed["scope"], document=document)
    assert errors(result) == [(RULE_UNREADY, "n1")]
    assert (result.blueprint is None, named(result)) == (True, {"n1"})
    assert ["is Pending, not Ready" in f.message for f in result.findings if f.rule == RULE_UNREADY] == [True]


def test_bytes_that_are_not_the_checksums_are_refused(
    conn: Infrahub, writer: Writer, seed: dict[str, Any], document: ReaderDocument
) -> None:
    """`n1`'s artifact's checksum written as 32 zeros on the branch, which `CoreArtifactUpdate` accepts, its storage id
    left as it was, so that the bytes stored under it are not the checksum's (design/verified-facts.md):
    `artifact.checksum.mismatch` for `n1` alone."""
    with writer.branch() as branch:
        found, _ = artifact(writer, branch, "n1")
        writer.mutate(branch, "CoreArtifactUpdate", {"id": found, "checksum": {"value": "0" * 32}})
        at = settled(conn, branch, seed["scope"])
        result = read(conn, branch=branch, at=at, scope=seed["scope"], document=document)
    assert errors(result) == [(RULE_MISMATCH, "n1")]
    assert (result.blueprint is None, named(result)) == (True, {"n1"})


def test_intent_edited_after_its_generation_is_stale(
    conn: Infrahub, writer: Writer, seed: dict[str, Any], document: ReaderDocument
) -> None:
    """`n1`'s `serial_number`, which the template does not render, written on the branch and nothing regenerated:
    `artifact.stale` for `n1` alone. The same read with a `generated_since` of that `head`, which vouches for a
    regeneration there that stored the same bytes, gives a blueprint, `n1`'s configuration the bytes its artifact
    listed before the write."""
    with writer.branch() as branch:
        _, before = artifact(writer, branch, "n1")
        writer.mutate(branch, "DcimDeviceUpdate", {"id": writer.named(branch, "DcimDevice", "n1"),
                                                   "serial_number": {"value": SERIAL}})
        at = settled(conn, branch, seed["scope"])
        stale = read(conn, branch=branch, at=at, scope=seed["scope"], document=document)
        vouched = read(conn, branch=branch, at=at, scope=seed["scope"], document=document, generated_since=at)
    assert errors(stale) == [(RULE_STALE, "n1")]
    assert (stale.blueprint is None, named(stale)) == (True, {"n1"})
    assert errors(vouched) == []
    assert vouched.blueprint is not None
    configs = {device["name"]: device["config"] for device in vouched.blueprint["network"]["devices"]}
    # A boolean, so that a failure prints no configuration.
    held = hashlib.md5(configs["n1"].encode(), usedforsecurity=False).hexdigest() == before
    assert held, "n1's configuration is the one its artifact listed before the write"


def test_a_removal_is_stale_by_its_event(
    conn: Infrahub, writer: Writer, seed: dict[str, Any], document: ReaderDocument
) -> None:
    """A cable added on the branch between `n1`'s and `n2`'s free ports and the configurations regenerated, then the
    cable's two ends removed from it (`RelationshipRemove`): neither port's stamp moves, each still the task workers'
    restamp after the generation, which the rule counts at the port's making, so that only the cable's event, naming
    both ports, shows the removal (design/verified-facts.md). `artifact.stale` for `n1` and `n2`, and not `n3`; and
    each port's stamp, as the rule counts it, no later than its device's checksum, so that the test fails where the
    event is not read. A delete of the cable would not do: it moves both ports' stamps forward."""
    with writer.branch() as branch:
        ports = {device: port(writer, branch, device, name)[0] for device, name in FREE.items()}
        before = {device: artifact(writer, branch, device)[1] for device in FREE}
        made = {"label": {"value": LABEL}, "connected_endpoints": [{"id": ports[device]} for device in FREE]}
        cable = writer.mutate(branch, "DcimCableCreate", made, select="ok object { id }")["object"]["id"]
        regenerate(writer, branch, before)
        sums = {device: generated(writer, branch, device)["checksum"]["updated_at"] for device in FREE}
        ends = [{"id": ports[device]} for device in FREE]
        writer.mutate(branch, "RelationshipRemove", {"id": cable, "name": "connected_endpoints", "nodes": ends})
        at = settled(conn, branch, seed["scope"])
        result = read(conn, branch=branch, at=at, scope=seed["scope"], document=document)
        own = workers(writer, branch)
        stamped = {device: counted(port(writer, branch, device, name)[1], own) for device, name in FREE.items()}
    assert errors(result) == [(RULE_STALE, "n1"), (RULE_STALE, "n2")]
    assert (result.blueprint is None, named(result)) == (True, {"n1", "n2"})
    assert [when is not None for when in stamped.values()] == [True, True], "each port's stamp counted"
    later = {device: when is not None and times.later(when, sums[device]) for device, when in stamped.items()}
    assert later == {"n1": False, "n2": False}, "only the event shows the removal"


def schema_of(branch: str) -> Callable[[httpx.Request], bool]:
    """Whether a request reads `branch`'s schema, `GET /api/schema?branch=<branch>`."""

    def picks(request: httpx.Request) -> bool:
        return (request.method, request.url.path, request.url.params.get("branch")) == ("GET", "/api/schema", branch)

    return picks


def unlabelled(body: bytes) -> bytes:
    """A schema answer with the attribute `label` taken out of `DcimCable`'s entry."""
    answer = json.loads(body)
    for node in answer["nodes"]:
        if node["kind"] == "DcimCable":
            node["attributes"] = [attribute for attribute in node["attributes"] if attribute["name"] != "label"]
    return json.dumps(answer).encode()


def test_a_drifted_schema_ends_the_read(
    conn: Infrahub, writer: Writer, seed: dict[str, Any], document: ReaderDocument
) -> None:
    """A schema load removing `DcimCable.label` (`state: absent`) on a branch was refused with HTTP 422, as an
    extension and as the node's own definition, for the uniqueness constraint and the display label that name it
    (design/verified-facts.md), so the drift is made in flight: the branch's schema answer has the attribute taken out
    of `DcimCable`'s entry. `check_schema` and `read` both answer `schema.field.missing` for `DcimCable.label` alone,
    the read nothing of the network; `main`, read through the same connection, still conforms."""
    with writer.branch() as branch:
        drift = Altered(schema_of(branch), unlabelled)
        at = head(conn, branch=branch, scope=seed["scope"])
        with reader(transport=drift) as drifted:
            checked = check_schema(drifted, branch=branch)
            result = read(drifted, branch=branch, at=at, scope=seed["scope"], document=document)
            on_main = check_schema(drifted, branch="main")
    missing = [(RULE_FIELD_MISSING, "DcimCable.label")]
    assert [(f.rule, f.object) for f in checked] == missing
    assert ([(f.rule, f.object) for f in result.findings], result.blueprint is None) == (missing, True)
    assert (on_main, drift.altered) == ((), 2)


def last_edge_out(body: bytes) -> bytes:
    """A ports' answer with its last edge taken out."""
    answer = json.loads(body)
    answer["data"]["InterfacePhysical"]["edges"] = answer["data"]["InterfacePhysical"]["edges"][:-1]
    return json.dumps(answer).encode()


def test_a_list_cut_short_is_incomplete(conn: Infrahub, seed: dict[str, Any], document: ReaderDocument) -> None:
    """The last edge taken out of each answer to the ports' query in flight, since a pinned read of a real Infrahub is
    whole whatever is written: the pager asks again at the offset it has read until a page answers no edge, so the list
    ends one short of the count Infrahub answered, `read.incomplete` for `InterfacePhysical` alone, and nothing past it
    is judged. A cut of the first answer alone is made whole by the next page, asked at the offset read so far."""
    at = head(conn, branch="main", scope=seed["scope"])
    cut = Altered(lambda request: operation(request) == "Ports", last_edge_out)
    with reader(transport=cut) as short:
        result = read(short, branch="main", at=at, scope=seed["scope"], document=document)
    assert errors(result) == [(RULE_INCOMPLETE, "InterfacePhysical")]
    assert (result.blueprint is None, named(result), cut.altered) == (True, set(), 2)


def test_a_platform_no_row_names_is_unmatched(conn: Infrahub, seed: dict[str, Any], document: ReaderDocument) -> None:
    """A reader document whose one row is Nokia's SR OS, where every scoped device is Nokia's SR Linux:
    `platform.unmatched` for each of the three, and no other error."""
    other = ReaderDocument((Match("Nokia", "SR OS", "nokia_srlinux"),), document.artifact, document.probes)
    at = head(conn, branch="main", scope=seed["scope"])
    result = read(conn, branch="main", at=at, scope=seed["scope"], document=other)
    assert sorted(errors(result)) == [(RULE_PLATFORM_UNMATCHED, device) for device in DEVICES]
    assert (result.blueprint is None, named(result)) == (True, set(DEVICES))


def test_the_reader_wrote_nothing(request: pytest.FixtureRequest) -> None:
    """The session's last (conftest, `LAST`): every request the reader's connections sent, each made by the conftest's
    `reader` over `Recorded`, was a `GET`, or a `POST` to `/graphql/<branch>` of a document whose operation is a
    `query`. The command's connections, in processes of their own (test_cli_contract.py), and the `connect` of a wrong
    token (test_transport_contract.py), which reads the version alone, are not recorded. Selected alone it has nothing
    to hold, and is skipped."""
    if all(item.name == LAST for item in request.session.items):
        pytest.skip("selected alone: no other test of the tier read through the conftest's reader in this session")
    assert SENT, "the session's reads were recorded"
    assert {sent.method for sent in SENT} <= {"GET", "POST"}
    posts = [sent for sent in SENT if sent.method == "POST"]
    assert [sent.path for sent in posts if not sent.path.startswith("/graphql/")] == []
    assert {sent.document for sent in posts} == {"query"}
