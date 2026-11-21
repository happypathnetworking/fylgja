"""The probes against the development Nautobot (D-118; design/verified-facts.md, "Nautobot 3.2.8 with Golden Config
3.0.8"): the seed's context `fylgja-probes`, inactive, read from its name into `testdata/blueprint/
three-node-probed.json`'s probe, and the same state read twice into one id; and a context Nautobot lists none of,
refused. The reader's token lists the context, which no write is needed for. No assertion message prints the address or
a token."""

from __future__ import annotations

import json
from typing import Any

from fylgja_core import blueprint

from fylgja_nautobot import Nautobot, ReaderDocument, Result, read

from .conftest import ROOT

SCOPE = "tag:fylgja"
CONTEXT = "fylgja-probes"
PROBED = json.loads((ROOT / "testdata" / "blueprint" / "three-node-probed.json").read_text())


def errors(result: Result) -> list[tuple[str, str | None]]:
    return [(finding.rule, finding.object) for finding in result.findings if finding.severity == "error"]


def taken(result: Result) -> dict[str, Any]:
    """The blueprint a read answered, which must have no error."""
    assert errors(result) == []
    assert result.blueprint is not None
    return result.blueprint


def test_the_seeded_probe_is_read(conn: Nautobot, document: ReaderDocument) -> None:
    assert document.probes == CONTEXT
    listed = conn.contexts(CONTEXT)
    assert (listed.count, [(row.name, row.active) for row in listed.items]) == (1, [(CONTEXT, False)])
    doc = taken(read(conn, scope=SCOPE, document=document))
    assert blueprint.validate(doc) == []
    assert doc["probes"] == PROBED["probes"]
    assert [probe["name"] for probe in doc["probes"]] == ["n1-loop"]
    assert [row for row in doc["source"]["fidelity"] if row["source"] == "extras.configcontext"] == []

    again = taken(read(conn, scope=SCOPE, document=document))
    assert blueprint.blueprint_id(again) == blueprint.blueprint_id(doc)
    print(f"read twice with the seed's reader document: {blueprint.blueprint_id(doc)}")


def test_a_context_nautobot_lacks_is_refused_there(conn: Nautobot, document: ReaderDocument) -> None:
    lacking = ReaderDocument(document.platforms, "fylgja-contract-none")
    result = read(conn, scope=SCOPE, document=lacking)
    assert result.blueprint is None
    assert errors(result) == [("probe.context.absent", "fylgja-contract-none")]
