"""`docs/client.md` holds to the client library (`fylgja_core.client`): its `Call` table lists `Client`'s public
methods, each with the parameters, in order, that `inspect.signature` gives; its `Error` table lists every
exception class the module defines; each `fylgja_core` name the page gives is importable; and its example compiles
and calls nothing the client lacks."""

from __future__ import annotations

import ast
import dataclasses
import importlib
import inspect
import re

from pages import blocks, rows, section, text, ticked

from fylgja_core import client
from fylgja_core.client import Client, Followed

PAGE = "docs/client.md"


def _methods() -> set[str]:
    return {n for n, v in vars(Client).items() if not n.startswith("_") and callable(v)}


def _signature(cell: str) -> tuple[str, ast.arguments]:
    """The name and the arguments a signature cell gives, parsed as a `def`; `…` stands for parameters the cell's
    neighbour says, and is read as none."""
    source = ticked(cell)[0].replace(", …", "").replace("…", "")
    function = ast.parse(f"def {source}: pass").body[0]
    assert isinstance(function, ast.FunctionDef)
    return function.name, function.args


def _shape(args: ast.arguments) -> list[tuple[str, str | None]]:
    """Each parameter in order as (name, default's source or None), a bare `*` as ("*", None)."""
    found: list[tuple[str, str | None]] = [(a.arg, None) for a in args.posonlyargs + args.args]
    defaults = [None] * (len(found) - len(args.defaults)) + [ast.unparse(d) for d in args.defaults]
    found = [(name, default) for (name, _), default in zip(found, defaults, strict=True)]
    if args.kwonlyargs:
        found.append(("*", None))
    found += [(a.arg, ast.unparse(d) if d is not None else None) for a, d in zip(args.kwonlyargs, args.kw_defaults,
                                                                                   strict=True)]
    return found


def _real(function: object, drop: int = 0) -> list[tuple[str, str | None]]:
    found: list[tuple[str, str | None]] = []
    starred = False
    for p in list(inspect.signature(function).parameters.values())[drop:]:  # type: ignore[arg-type]
        if p.kind is inspect.Parameter.KEYWORD_ONLY and not starred:
            found.append(("*", None))
            starred = True
        found.append((p.name, None if p.default is inspect.Parameter.empty else repr(p.default)))
    return found


def test_the_call_table_is_every_public_method_with_its_signature() -> None:
    found = rows(section(text(PAGE), "## Calls"), "Call")
    assert found, "the parse is blind"
    listed = {_signature(row[0])[0]: row for row in found}
    assert len(listed) == len(found), "a call has one row"
    assert set(listed) == _methods() | {"Client"}
    for name, row in listed.items():
        _, args = _signature(row[0])
        shown = _shape(args)
        if name == "Client":
            real = _real(Client.__init__, drop=1)
            assert shown == real[: len(shown)], name
            assert [n for n, _ in real[len(shown):]] == ["transport", "sleep", "notice"]
            assert "…" in row[0]
            for hidden in ("transport", "sleep", "notice"):
                assert f"`{hidden}`" in row[1], f"the row says {hidden}"
        else:
            assert shown == _real(getattr(Client, name), drop=1), name
        assert row[1], f"{name} has its route and answer"


def test_the_error_table_is_every_error_the_module_defines() -> None:
    found = rows(section(text(PAGE), "## Errors"), "Error")
    assert found, "the parse is blind"
    listed = [ticked(row[0])[0] for row in found]
    assert len(listed) == len(set(listed))
    defined = {
        n for n, v in vars(client).items()
        if not n.startswith("_") and inspect.isclass(v) and issubclass(v, Exception) and v.__module__ == client.__name__
    }
    assert set(listed) == defined
    assert len(defined) == 8, "eight errors"


def _names() -> set[str]:
    page = text(PAGE)
    names = set(re.findall(r"`(fylgja_core(?:\.[A-Za-z_][A-Za-z0-9_]*)+)`", page))
    for info, lines in blocks(page):
        if info == "python":
            for node in ast.walk(ast.parse("\n".join(lines))):
                if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] == "fylgja_core":
                    names |= {f"{node.module}.{a.name}" for a in node.names}
                    names.add(node.module)
    return names


def _resolve(dotted: str) -> object:
    parts = dotted.split(".")
    for k in range(len(parts), 0, -1):
        try:
            found: object = importlib.import_module(".".join(parts[:k]))
        except ModuleNotFoundError:
            continue
        for part in parts[k:]:
            found = getattr(found, part)
        return found
    raise AssertionError(dotted)


def test_every_fylgja_core_name_the_page_gives_exists() -> None:
    names = _names()
    assert {"fylgja_core.client", "fylgja_core.client.Client", "fylgja_core.documents.Rejected"} <= names, \
        "the parse is blind"
    for name in names:
        assert not any(part.startswith("_") for part in name.split(".")), f"{name} is private"
        assert _resolve(name) is not None, name


def test_the_example_calls_only_what_the_client_has() -> None:
    examples = [lines for info, lines in blocks(text(PAGE)) if info == "python"]
    assert len(examples) == 1, "the parse is blind"
    tree = ast.parse("\n".join(examples[0]))  # compiles
    compile(tree, PAGE, "exec")
    bound: set[str] = set()
    followed: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.With):
            for item in node.items:
                call = item.context_expr
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "Client":
                    assert isinstance(item.optional_vars, ast.Name)
                    bound.add(item.optional_vars.id)
    assert bound == {"client"}, "the parse is blind"
    fields = {f.name for f in dataclasses.fields(Followed)}
    called = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and isinstance(node.func.value, ast.Name) and node.func.value.id in bound:
            called.add(node.func.attr)
            assert node.func.attr in _methods(), node.func.attr
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) \
                and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "follow":
            followed |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    assert {"put_blueprint", "apply_twin", "follow"} <= called, "the parse is blind"
    assert followed, "the parse is blind"
    read = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
            and n.value.id in followed}
    assert read and read <= fields, read
