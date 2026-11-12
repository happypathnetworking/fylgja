"""The stale rule and `head` against the development Infrahub: the seed's stages read fresh; an address edited on a
branch of the tier's own refuses its device alone until a regeneration clears it, and then a port renamed, with
nothing regenerated, refuses `n1` and `n2`, at the cable's far end, and not `n3`; `head` reads the seeded branch as it
stands; and the same read twice gives one id (CONTRIBUTING.md, Test tiers; design/verified-facts.md,
"Infrahub 1.11.11", "What a stale rule can be built on"). Each assertion compares plain values, so that a failing one
prints no blueprint, no address and no token.

A write's events are logged up to 5.92 s after it, and the task workers' group writes follow a generation's
checksums by up to 7.9 s, so `head` is asked `QUIET_S` after a write and after a regeneration
(design/verified-facts.md, "Infrahub 1.11.11")."""

from __future__ import annotations

import json
import time
from typing import Any

from fylgja_core import blueprint

from fylgja_infrahub import Infrahub, ReaderDocument, Result, head, read, times
from fylgja_infrahub.stale import RULE_STALE

from .writer import Writer

QUIET_S = 10.0
"""Seconds a test waits after a write, or a regeneration, before it asks `head`."""

GENERATED_S = 180.0
"""How long a regeneration is waited for: on a scratch branch one had all its checksums moved 11.5 s after it was
asked, and the first seed of `main` read its configurations `Ready` 36 s after (design/verified-facts.md)."""

POLL_S = 2.0

DEFINITION = "device-config"
"""The artifact definition the registration made, which names its artifacts so too (`.infrahub.yml`)."""

PORT = "ethernet-1/10"
EDITED = "192.0.2.10/24"
"""`n1`'s port whose address the edit changes, and the address it is given, in a documentation range."""

FAR = "ethernet-1/1"
RENAMED = "ethernet-1/9"
"""`n1`'s port at the cable to `n2:ethernet-1/1`, which `n2`'s configuration renders by its name, and the name it is
given, which no port of `n1`'s holds."""

PORTS = """
query ($device: String!) {
  DcimDevice(name__value: $device) { edges { node { id interfaces { edges { node { id name { value } } } } } } }
}
"""

ADDRESSES = """
query {
  DcimDevice(name__value: "n1") {
    edges { node { interfaces { edges { node {
      name { value }
      ... on InterfacePhysical { ip_addresses { edges { node { id address { value } } } } }
    } } } } }
  }
}
"""
DEFINITIONS = "query ($name: String!) { CoreArtifactDefinition(name__value: $name) { edges { node { id } } } }"
GENERATED = """
query ($device: String!, $name: String!) {
  DcimDevice(name__value: $device) {
    edges { node { artifacts(name__value: $name) { edges { node { status { value } checksum { value } } } } } }
  }
}
"""


def errors(result: Result) -> list[tuple[str, str | None]]:
    """The errors of a result, by rule and object."""
    return [(f.rule, f.object) for f in result.findings if f.severity == "error"]


def ran(conn: Infrahub, branch: str, at: str, seed: dict[str, Any], document: ReaderDocument) -> Result:
    return read(conn, branch=branch, at=at, scope=seed["scope"], document=document)


def unobserved(result: Result) -> dict[str, Any]:
    assert result.blueprint is not None
    return {**result.blueprint, "source": {k: v for k, v in result.blueprint["source"].items() if k != "observed_at"}}


def test_the_seeds_stages_are_not_stale(conn: Infrahub, seed: dict[str, Any], document: ReaderDocument) -> None:
    """Each stage's time is already after every stamp and event of its stage, its generation's among them."""
    for stage in seed["stages"]:
        result = ran(conn, seed["branch"], stage["at"], seed, document)
        assert (stage["label"], errors(result)) == (stage["label"], [])
        assert result.blueprint is not None


def address(writer: Writer, branch: str) -> tuple[str, str]:
    """The id and the value of the one address on `n1`'s `PORT` on `branch`."""
    (device,) = writer.gql(branch, ADDRESSES)["DcimDevice"]["edges"]
    ports = [edge["node"] for edge in device["node"]["interfaces"]["edges"] if edge["node"]["name"]["value"] == PORT]
    ((held,),) = [[edge["node"] for edge in port["ip_addresses"]["edges"]] for port in ports]
    return held["id"], held["address"]["value"]


def checksum(writer: Writer, branch: str, device: str = "n1") -> tuple[str, str | None]:
    """The device's artifact's status and checksum on `branch`."""
    (held,) = writer.gql(branch, GENERATED, {"device": device, "name": DEFINITION})["DcimDevice"]["edges"]
    ((artifact,),) = [[edge["node"] for edge in held["node"]["artifacts"]["edges"]]]
    return artifact["status"]["value"], artifact["checksum"]["value"]


def generated(writer: Writer, branch: str, nodes: list[str], before: tuple[str, str | None], device: str) -> None:
    """Ask the generation for `nodes`, every target where it is empty, as `infrahub/seed/seed.py`'s `generate` asks
    it, and wait until `device`'s checksum has moved from `before`, `Ready`, then `QUIET_S` more for the task workers'
    group writes."""
    (definition,) = writer.gql(branch, DEFINITIONS, {"name": DEFINITION})["CoreArtifactDefinition"]["edges"]
    path = f"/api/artifact/generate/{definition['node']['id']}"
    writer.rest("POST", path, params={"branch": branch}, body={"nodes": nodes})
    started = time.monotonic()
    now = checksum(writer, branch, device)
    while now == before or now[0] != "Ready":
        assert time.monotonic() - started < GENERATED_S, f"{device} not regenerated within {GENERATED_S:g} s"
        time.sleep(POLL_S)
        now = checksum(writer, branch, device)
    time.sleep(QUIET_S)


def test_an_address_edit_on_the_branch_is_stale_and_a_regeneration_clears_it(
    conn: Infrahub, writer: Writer, seed: dict[str, Any], document: ReaderDocument
) -> None:
    """An address's edit moves its own stamp alone, as `__system__`, and its event names the address alone, so the
    rule reads the address's stamp under its port; nothing regenerates unasked, and the regeneration is asked as
    `infrahub/seed/seed.py`'s `generate` asks it (design/verified-facts.md, "Infrahub 1.11.11"). Then, on the same
    branch, `n1`'s port at the cable to `n2` renamed and nothing regenerated: `n1` is stale by its own port, and `n2`,
    whose own stamps the rename moves none of, by the far port's `name` alone, since it renders that port's name; `n3`,
    on no cable to that port, is not (P3-27). A generation asked for `n1` alone, `{"nodes": [<its id>]}`, moved `n1`'s
    checksum not at all in 180 s on the instance, which is why `n1` is left ungenerated here."""
    with writer.branch() as branch:
        found, held = address(writer, branch)
        assert held != EDITED
        before = checksum(writer, branch)
        mutation = (
            f"mutation {{ IpamIPAddressUpdate(data: {{id: {json.dumps(found)}, address: {{value: "
            f"{json.dumps(EDITED)}}}}}) {{ ok }} }}"
        )
        assert writer.gql(branch, mutation)["IpamIPAddressUpdate"]["ok"] is True
        time.sleep(QUIET_S)
        edited_at = head(conn, branch=branch, scope=seed["scope"])
        stale = ran(conn, branch, edited_at, seed, document)
        assert errors(stale) == [(RULE_STALE, "n1")]
        assert stale.blueprint is None
        assert checksum(writer, branch) == before, "nothing regenerates unasked"

        generated(writer, branch, [], before, "n1")
        regenerated_at = head(conn, branch=branch, scope=seed["scope"])
        fresh = ran(conn, branch, regenerated_at, seed, document)
        assert errors(fresh) == []
        assert fresh.blueprint is not None
        configs = {device["name"]: device["config"] for device in fresh.blueprint["network"]["devices"]}
        # A boolean, so that a failure prints no configuration.
        met = EDITED in configs["n1"]
        assert met, "the read meets the regenerated configuration"
        assert times.later(regenerated_at, edited_at)

        (n1,) = writer.gql(branch, PORTS, {"device": "n1"})["DcimDevice"]["edges"]
        ports = {edge["node"]["name"]["value"]: edge["node"]["id"] for edge in n1["node"]["interfaces"]["edges"]}
        assert RENAMED not in ports
        rename = (
            f"mutation {{ InterfacePhysicalUpdate(data: {{id: {json.dumps(ports[FAR])}, name: {{value: "
            f"{json.dumps(RENAMED)}}}}}) {{ ok }} }}"
        )
        held_n2 = checksum(writer, branch, "n2")
        assert writer.gql(branch, rename)["InterfacePhysicalUpdate"]["ok"] is True
        time.sleep(QUIET_S)
        renamed_at = head(conn, branch=branch, scope=seed["scope"])
        far = ran(conn, branch, renamed_at, seed, document)
        assert errors(far) == [(RULE_STALE, "n1"), (RULE_STALE, "n2")]
        assert checksum(writer, branch, "n2") == held_n2, "nothing regenerates unasked"
        assert times.later(renamed_at, regenerated_at)


def test_head_reads_the_branch_as_it_is(conn: Infrahub, seed: dict[str, Any], document: ReaderDocument) -> None:
    """Nothing writes intent on the seeded branch after its last stage, so a read at that stage's time and a read at
    `head`, taken afterwards, give one blueprint, whatever Infrahub's own later writes (plan 0, reconciled 20)."""
    last = seed["stages"][-1]["at"]
    at = head(conn, branch=seed["branch"], scope=seed["scope"])
    times.parse(at)
    then, now = ran(conn, seed["branch"], last, seed, document), ran(conn, seed["branch"], at, seed, document)
    assert (errors(then), errors(now)) == ([], [])
    assert then.blueprint is not None and now.blueprint is not None
    assert blueprint.blueprint_id(then.blueprint) == blueprint.blueprint_id(now.blueprint)


def test_the_same_read_twice_gives_one_id(conn: Infrahub, seed: dict[str, Any], document: ReaderDocument) -> None:
    for stage in seed["stages"]:
        first, again = (ran(conn, seed["branch"], stage["at"], seed, document) for _ in range(2))
        assert unobserved(first) == unobserved(again)
        assert first.blueprint is not None and again.blueprint is not None
        assert blueprint.blueprint_id(first.blueprint) == blueprint.blueprint_id(again.blueprint)
