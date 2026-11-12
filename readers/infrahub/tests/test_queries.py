"""Every GraphQL document the reader sends is a file under `queries/`, one `query` each, and the transport names each
by a call and builds none of its own, so the reader reads and never writes (D-082, D-083)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

READER = Path(__file__).resolve().parents[1] / "src" / "fylgja_infrahub"
QUERIES = READER / "queries"
TRANSPORT = READER / "transport.py"

OPERATION = re.compile(r"query\s+[_A-Za-z][_0-9A-Za-z]*\s*[({]")


def _documents() -> dict[str, str]:
    return {path.stem: path.read_text() for path in sorted(QUERIES.glob("*.graphql"))}


def _uncommented(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#")).strip()


def _named() -> set[str]:
    """Each document a call of `transport.py` names: the first argument of every `graphql` and `paged` call."""
    named = set()
    for node in ast.walk(ast.parse(TRANSPORT.read_text())):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in ("graphql", "paged")
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            named.add(node.args[0].value)
    return named


def test_every_document_is_one_query() -> None:
    documents = _documents()
    assert {"devices", "ports"} <= set(documents), "the scan is blind"
    for name, text in documents.items():
        assert OPERATION.match(_uncommented(text)), name
        assert "mutation" not in text, name
        assert "subscription" not in text, name


def test_every_document_is_named_by_a_call_of_the_transport() -> None:
    assert set(_documents()) == _named()


def _block(text: str, field: str) -> str:
    """The selection set of the first `field` in `text`, from its opening brace to the one that closes it."""
    start = text.index("{", text.index(field))
    depth = 0
    for at in range(start, len(text)):
        depth += {"{": 1, "}": -1}.get(text[at], 0)
        if depth == 0:
            return text[start : at + 1]
    raise ValueError(f"{field} is never closed")


def test_a_cables_far_end_is_read_for_its_names_alone() -> None:
    """The stale rule counts a cable's far end by the far port's name and the far device's alone (P3-27), and stays so
    by what it selects: under `connected_endpoints`, the `name` stamps and no `node_metadata`, which an address made on
    the far port moves and the far end renders nothing of."""
    document = _uncommented(_documents()["cable_stamps"])
    assert "node_metadata" in document, "the scan is blind: the port's connector edge carries one"
    ends = _block(document, "connected_endpoints")
    assert "node_metadata" not in ends
    assert ends.count("name { updated_at }") == 2, "the far port's name and the far device's"


def test_the_transport_holds_no_document_of_its_own() -> None:
    strings = [
        node.value
        for node in ast.walk(ast.parse(TRANSPORT.read_text()))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    assert any("graphql" in s for s in strings), "the scan is blind"
    assert [s for s in strings if "query {" in s or "mutation" in s] == []
