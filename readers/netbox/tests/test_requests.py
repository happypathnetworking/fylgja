"""The reader writes nothing to NetBox (D-095): its transport sends every request through one sender, each a `GET` but
the render's `POST`, and no other module of the reader names a path of NetBox's, so that no request is sent from
anywhere else. Read from the source, with `ast`, so that a request no test sends is held too."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

READER = Path(__file__).resolve().parents[1] / "src" / "fylgja_netbox"
TRANSPORT = READER / "transport.py"
SENDER = "_send"
"""The transport's one sender: the one method that hands a request to httpx."""


def _calls(tree: ast.AST) -> list[tuple[str, ast.Call]]:
    """Each call in `tree` with the name of the function it is made in."""
    found: list[tuple[str, ast.Call]] = []

    def walk(node: ast.AST, inside: str) -> None:
        for child in ast.iter_child_nodes(node):
            named = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else inside
            if isinstance(child, ast.Call):
                found.append((inside, child))
            walk(child, named)

    walk(tree, "<module>")
    return found


def _named(call: ast.Call, name: str) -> bool:
    return isinstance(call.func, ast.Attribute) and call.func.attr == name


HANDS = ("request", "send", "stream", "post", "put", "patch", "delete", "head", "options")
"""What hands httpx a request, by any receiver or none: its client's and its module's senders, the convenience ones
among them, which carry no method's literal."""

CLIENTS = ("self._http", "httpx")
"""The receivers `get` hands a request to; a `get` of anything else is a mapping's."""


def _handed(tree: ast.AST) -> list[tuple[str, str]]:
    """Each call in `tree` that hands httpx a request: the function it is made in and the sender's name."""
    found = []
    for inside, call in _calls(tree):
        func = call.func
        if isinstance(func, ast.Attribute):
            name, receiver = func.attr, ast.unparse(func.value)
        elif isinstance(func, ast.Name):
            name, receiver = func.id, ""
        else:
            continue
        if name in HANDS or (name == "get" and receiver in CLIENTS):
            found.append((inside, name))
    return found


def test_the_transport_sends_get_and_the_render_alone() -> None:
    tree = ast.parse(TRANSPORT.read_text())
    calls = _calls(tree)
    sent = [(inside, call) for inside, call in calls if _named(call, SENDER)]
    methods = [
        (inside, call.args[0].value if call.args and isinstance(call.args[0], ast.Constant) else None)
        for inside, call in sent
    ]
    assert ("_get", "GET") in methods, "the walk is blind"
    assert [(inside, method) for inside, method in methods if inside != "render" and method != "GET"] == []
    assert [method for inside, method in methods if inside == "render" and method != "POST"] == []
    # httpx is handed a request by the sender alone, and by its `request`.
    assert _handed(tree) == [(SENDER, "request")]
    words = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert sorted(word for word in words if word.upper() in ("PATCH", "PUT", "DELETE")) == []


def test_no_other_module_names_a_path_of_netboxs() -> None:
    """Its docstrings included: a path named in another module's text is one a reviewer would look for a request on."""
    assert "/api/" in TRANSPORT.read_text(), "the scan is blind"
    others = sorted(p for p in READER.rglob("*.py") if p != TRANSPORT and "__pycache__" not in p.parts)
    assert others
    assert [p.name for p in others if "/api/" in p.read_text()] == []


@pytest.mark.parametrize(
    "call",
    [
        *(f"self._http.{name}('/x')" for name in ("get", "post", "put", "patch", "delete", "head", "options")),
        *(f"httpx.{name}('http://netbox.example/x')" for name in ("get", "post", "put", "patch", "delete", "head")),
        "httpx.options('http://netbox.example/x')",
        "post('http://netbox.example/x')",
        "self._http.stream('GET', '/x')",
        "self._http.send(request)",
    ],
)
def test_every_sender_of_httpxs_is_caught(call: str) -> None:
    """A convenience sender carries no method's literal and is named no `request`: the walk sees it all the same."""
    assert _handed(ast.parse(f"def elsewhere(self):\n    {call}\n")) != []


def test_a_mappings_get_is_no_sender() -> None:
    assert _handed(ast.parse("def f(row):\n    row.get('id')\n    response.headers.get('Location')\n")) == []
