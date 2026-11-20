"""The reader asks Nautobot to write nothing (D-118, D-119): its transport sends every request through one sender, whose
method is the literal `GET`; it names no parameter `branch`, Golden Config's, which names a branch of the template
repository to render from; and no other module of the reader names a path of Nautobot's, so that no request is sent
from anywhere else. Read from the source, with `ast`, so that a request no test sends is held too."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

READER = Path(__file__).resolve().parents[1] / "src" / "fylgja_nautobot"
TRANSPORT = READER / "transport.py"
SENDER = "_send"
"""The transport's one sender: the one function that hands a request to httpx."""

WRITES = ("POST", "PATCH", "PUT", "DELETE")
"""The methods that write, none of which the transport names."""


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


HANDS = ("request", "send", "stream", "post", "put", "patch", "delete", "head", "options")
"""What hands httpx a request, by any receiver or none: its client's and its module's senders, the convenience ones
among them, which carry no method's literal."""

CLIENTS = ("self._http", "httpx")
"""The receivers `get` hands a request to; a `get` of anything else is a mapping's."""


def _handed(tree: ast.AST) -> list[tuple[str, str, ast.Call]]:
    """Each call in `tree` that hands httpx a request: the function it is made in, the sender's name and the call."""
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
            found.append((inside, name, call))
    return found


def _words(tree: ast.AST) -> set[str]:
    return {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}


def test_every_request_is_a_get() -> None:
    tree = ast.parse(TRANSPORT.read_text())
    handed = _handed(tree)
    # httpx is handed a request by the sender alone, by its `request`, and the method is the literal GET.
    assert [(inside, name) for inside, name, _ in handed] == [(SENDER, "request")]
    (_, _, call) = handed[0]
    assert call.args and isinstance(call.args[0], ast.Constant) and call.args[0].value == "GET"
    assert sorted(word for word in _words(tree) if word.strip().upper() in WRITES) == []


def test_no_parameter_named_branch_is_ever_sent() -> None:
    """Golden Config's render takes `branch`, a branch of the template repository (design/verified-facts.md): the reader
    renders the branch the repository is registered with, so no string of the transport is the parameter's name."""
    tree = ast.parse(TRANSPORT.read_text())
    words = _words(tree)
    assert "tags" in words, "the scan is blind"
    assert sorted(word for word in words if word.strip().lower() == "branch") == []
    pairs = [node for node in ast.walk(tree) if isinstance(node, ast.Tuple) and len(node.elts) == 2]
    named = [ast.unparse(node.elts[0]) for node in pairs if isinstance(node.elts[0], ast.Constant)]
    assert "'tags'" in named, "the scan is blind"
    assert [name for name in named if "branch" in name.lower()] == []


def test_no_other_module_names_a_path_of_nautobots() -> None:
    """Its docstrings included: a path named in another module's text is one a reviewer would look for a request on."""
    assert "/api/" in TRANSPORT.read_text(), "the scan is blind"
    others = sorted(p for p in READER.rglob("*.py") if p != TRANSPORT and "__pycache__" not in p.parts)
    assert others
    assert [p.name for p in others if "/api/" in p.read_text()] == []


@pytest.mark.parametrize(
    "call",
    [
        *(f"self._http.{name}('/x')" for name in ("get", "post", "put", "patch", "delete", "head", "options")),
        *(f"httpx.{name}('http://nautobot.example/x')" for name in ("get", "post", "put", "patch", "delete", "head")),
        "httpx.options('http://nautobot.example/x')",
        "post('http://nautobot.example/x')",
        "self._http.stream('GET', '/x')",
        "self._http.send(request)",
    ],
)
def test_every_sender_of_httpxs_is_caught(call: str) -> None:
    """A convenience sender carries no method's literal and is named no `request`: the walk sees it all the same."""
    assert _handed(ast.parse(f"def elsewhere(self):\n    {call}\n")) != []


def test_a_mappings_get_is_no_sender() -> None:
    assert _handed(ast.parse("def f(row):\n    row.get('id')\n    response.headers.get('Location')\n")) == []
