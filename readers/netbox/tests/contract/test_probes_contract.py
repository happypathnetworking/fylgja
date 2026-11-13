"""The probes against the development NetBox (D-095; design/verified-facts.md, "NetBox 4.7.5 with netbox-branching
1.2.3", "The probes' context, read"): the seed's context `fylgja-probes`, inactive, read from `main` by its name into
`testdata/blueprint/three-node-probed.json`'s probe, and the same state read twice into one id; the context's data
edited under a branch's header, the branch's alone; and a context NetBox lists none of, refused. Every write is the
superuser's, through `box`, under the header of the test's own branch. No assertion message prints the address or a
token."""

from __future__ import annotations

import json
from typing import Any

from fylgja_core import blueprint

from fylgja_netbox import NetBox, ReaderDocument, Result, read
from fylgja_netbox.rows import Branch

from .conftest import ROOT, Writes

SCOPE = "tag:fylgja"
CONTEXT = "fylgja-probes"
PROBED = json.loads((ROOT / "testdata" / "blueprint" / "three-node-probed.json").read_text())

N2_LOOP = {
    "name": "n2-loop",
    "format": "ping",
    "endpoints": [
        {"device": "n2", "interface": "ethernet-1/10", "address": "192.0.2.2/24", "gateway": "192.0.2.1"},
        {"device": "n2", "interface": "ethernet-1/11", "address": "198.51.100.2/24", "gateway": "198.51.100.1"},
    ],
}
"""A second probe, of the documentation ranges, on a device of the scope."""


def errors(result: Result) -> list[tuple[str, str | None]]:
    return [(finding.rule, finding.object) for finding in result.findings if finding.severity == "error"]


def taken(result: Result) -> dict[str, Any]:
    """The blueprint a read answered, which must have no error."""
    assert errors(result) == []
    assert result.blueprint is not None
    return result.blueprint


def test_the_seeded_probe_is_read(conn: NetBox, document: ReaderDocument) -> None:
    assert document.probes == CONTEXT
    doc = taken(read(conn, branch=None, scope=SCOPE, document=document))
    assert blueprint.validate(doc) == []
    assert doc["probes"] == PROBED["probes"]
    assert [row for row in doc["source"]["fidelity"] if row["source"] == "extras.configcontext"] == []

    again = taken(read(conn, branch=None, scope=SCOPE, document=document))
    assert blueprint.blueprint_id(again) == blueprint.blueprint_id(doc)
    print(f"main read twice with the seed's reader document: {blueprint.blueprint_id(doc)}")


def test_a_context_edited_on_a_branch_is_the_branchs(
    conn: NetBox, box: Writes, branch: Branch, document: ReaderDocument
) -> None:
    held = box.one("extras/config-contexts/", branch=branch.schema_id, name=CONTEXT)
    assert held is not None
    data = {**held["data"], "probes": [*held["data"]["probes"], N2_LOOP]}
    box.patch(f"extras/config-contexts/{held['id']}/", {"data": data}, branch=branch.schema_id)

    on_branch = taken(read(conn, branch=branch.name, scope=SCOPE, document=document))
    on_main = taken(read(conn, branch=None, scope=SCOPE, document=document))
    assert on_branch["probes"] == [*PROBED["probes"], N2_LOOP]
    assert on_main["probes"] == PROBED["probes"]


def test_a_context_netbox_lacks_is_refused_there(conn: NetBox, document: ReaderDocument) -> None:
    lacking = ReaderDocument(document.platforms, "fylgja-contract-none")
    result = read(conn, branch=None, scope=SCOPE, document=lacking)
    assert result.blueprint is None
    assert errors(result) == [("probe.context.absent", "fylgja-contract-none")]
