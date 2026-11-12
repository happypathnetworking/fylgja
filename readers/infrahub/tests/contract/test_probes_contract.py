"""The probes against the development Infrahub: the seed's `n1-loop` in the blueprint of every stage, read with the
seed's document; and a probe of the tier's own, of the branch-agnostic kind, read through a branch at a time as it stood
then, and omitted from a read whose scope holds none of its devices (CONTRIBUTING.md, Test tiers;
design/verified-facts.md, "Infrahub 1.11.11"). Each assertion compares plain values, so that a failing one prints no
blueprint, no address and no token."""

from __future__ import annotations

import json
import secrets
from typing import Any

from fylgja_infrahub import Infrahub, ReaderDocument, Result, head, read, times
from fylgja_infrahub.rows import Listing, Probe

from .conftest import ROOT
from .writer import PROBES, Writer

THREE_NODE_PROBED = ROOT / "testdata" / "blueprint" / "three-node-probed.json"

STAMPED = """
query ($name: String!) { FylgjaProbe(name__value: $name) { edges { node_metadata { updated_at } node { id } } } }
"""

FIRST, SECOND = "192.0.2.1", "192.0.2.3"
"""The test's probe's gateway of host a, and the one it is changed to, in a documentation range."""


def errors(result: Result) -> list[tuple[str, str | None]]:
    """The errors of a result, by rule and object."""
    return [(f.rule, f.object) for f in result.findings if f.severity == "error"]


def test_the_seeded_probe_is_in_the_blueprint(conn: Infrahub, seed: dict[str, Any], document: ReaderDocument) -> None:
    assert document.probes, "the seed's document asks for probes"
    probes = json.loads(THREE_NODE_PROBED.read_text())["probes"]
    assert [probe["name"] for probe in probes] == ["n1-loop"]
    for stage in seed["stages"]:
        result = read(conn, branch=seed["branch"], at=stage["at"], scope=seed["scope"], document=document)
        assert (stage["label"], errors(result)) == (stage["label"], [])
        assert result.blueprint is not None
        assert result.blueprint["probes"] == probes


def updated(writer: Writer, branch: str, name: str) -> str:
    """When the probe `name` was last written, its edge's `updated_at`, as the writer reads it on `branch`."""
    (edge,) = writer.gql(branch, STAMPED, {"name": name})["FylgjaProbe"]["edges"]
    found: str = edge["node_metadata"]["updated_at"]
    return found


def gateways(listing: Listing[Probe], name: str) -> list[tuple[str, str | None]]:
    """The id and host a's gateway of each probe `name` of a whole list."""
    assert listing.count == len(listing.items)
    return [(probe.id, probe.a[3]) for probe in listing.items if probe.name == name]


def test_probes_are_read_as_they_stood_at_the_time(
    conn: Infrahub, writer: Writer, seed: dict[str, Any], document: ReaderDocument
) -> None:
    """A probe of the tier's own, on devices no scope holds, made through a branch of the tier's and its gateway
    changed: read through that branch a microsecond after each write, it answers each gateway in turn under one id;
    `head` of that branch is later than the change, a probe's stamp among those it counts (P3-38); and the seed's
    document's read of the branch omits it, the seed's `n1-loop` alone in the blueprint. The probe is deleted at the
    end, whatever happened."""
    name = f"{PROBES}{secrets.token_hex(4)}"
    a = {"a_device": "x9", "a_interface": "ethernet-1/10", "a_address": "192.0.2.2/24", "a_gateway": FIRST}
    b = {"b_device": "x8", "b_interface": "ethernet-1/11", "b_address": "198.51.100.2/24", "b_gateway": "198.51.100.1"}
    held = {"name": name, "format": "ping", **a, **b}
    fields = ", ".join(f"{field}: {{value: {json.dumps(value)}}}" for field, value in held.items())
    with writer.branch() as branch:
        made = writer.gql(branch, f"mutation {{ FylgjaProbeCreate(data: {{{fields}}}) {{ ok object {{ id }} }} }}")
        assert made["FylgjaProbeCreate"]["ok"] is True
        found = made["FylgjaProbeCreate"]["object"]["id"]
        try:
            first = updated(writer, branch, name)
            change = f"id: {json.dumps(found)}, a_gateway: {{value: {json.dumps(SECOND)}}}"
            changed = writer.gql(branch, f"mutation {{ FylgjaProbeUpdate(data: {{{change}}}) {{ ok }} }}")
            assert changed["FylgjaProbeUpdate"]["ok"] is True
            second = updated(writer, branch, name)
            assert times.later(second, first)
            assert times.later(head(conn, branch=branch, scope=seed["scope"]), second)

            then, now = (conn.probes(branch, times.after(at)) for at in (first, second))
            assert (gateways(then, name), gateways(now, name)) == ([(found, FIRST)], [(found, SECOND)])

            result = read(conn, branch=branch, at=times.after(second), scope=seed["scope"], document=document)
            assert errors(result) == []
            assert [(f.rule, f.object) for f in result.findings] == [("omit.probe.outside_scope", name)]
            assert result.blueprint is not None
            assert [probe["name"] for probe in result.blueprint["probes"]] == ["n1-loop"]
            rows = [row for row in result.blueprint["source"]["fidelity"] if row["object"] == name]
            assert [(row["disposition"], row["source"]) for row in rows] == [("omitted", "FylgjaProbe")]
        finally:
            gone = writer.gql(branch, f"mutation {{ FylgjaProbeDelete(data: {{id: {json.dumps(found)}}}) {{ ok }} }}")
            assert gone["FylgjaProbeDelete"]["ok"] is True
