"""The cluster tier's wrappers of `Kube` held to the protocol in the pure tier. A cluster test
hands the driver a class of its own that passes each call to the client (`Observed`, `Killing`);
a call added to `clabernetes.kube.Kube` and missing from one of them would be found only when
the driver made it on the cluster, in a window. Each wrapper is read by `ast`, never imported:
its module imports lightkube and the cluster's fixtures."""

from __future__ import annotations

import ast
import inspect
from collections.abc import Iterator
from pathlib import Path

from fylgja_core.clabernetes.kube import Kube

CLUSTER = Path(__file__).resolve().parent / "cluster"
WRAPPER = "`Kube` over"
"""How a wrapper's docstring begins."""

type Param = tuple[str, str, str | None]
"""A parameter as its name, its kind (`inspect.Parameter.kind`'s name) and the `repr` of its default,
None where it has none."""
type Member = tuple[str, tuple[Param, ...], bool]
"""A call as its name, its parameters after `self`, and whether it is awaited."""


def protocol() -> set[Member]:
    """`Kube`'s calls. One is awaited when it is a coroutine function: `watch_pods`, a plain
    function answering an async generator, is not."""
    return {(name, tuple((p.name, p.kind.name, None if p.default is p.empty else repr(p.default))
                         for p in inspect.signature(f).parameters.values())[1:], inspect.iscoroutinefunction(f))
            for name, f in vars(Kube).items() if inspect.isfunction(f) and not name.startswith("_")}


def default(node: ast.expr | None) -> str | None:
    """The `repr` of a parameter's default, read as a literal; None where it has none."""
    return None if node is None else repr(ast.literal_eval(node))


def own_nodes(f: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[ast.AST]:
    """The nodes of `f`'s own body: those of a function, async function or lambda nested in it are
    that function's, so not walked."""
    pending: list[ast.AST] = list(f.body)
    while pending:
        node = pending.pop()
        yield node
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            pending.extend(ast.iter_child_nodes(node))


def member(f: ast.FunctionDef | ast.AsyncFunctionDef) -> Member:
    """A wrapper's method as a `Member`. An `async def` that yields, in its own body, is an async
    generator function: called, it answers its generator at once, as the protocol's `watch_pods`
    does, so it is not awaited."""
    a = f.args
    positional = [*a.posonlyargs, *a.args]
    defaults = [None] * (len(positional) - len(a.defaults)) + list(a.defaults)
    params: list[Param] = [(p.arg, "POSITIONAL_ONLY" if p in a.posonlyargs else "POSITIONAL_OR_KEYWORD", default(d))
                           for p, d in zip(positional, defaults, strict=True)]
    if a.vararg:
        params.append((a.vararg.arg, "VAR_POSITIONAL", None))
    params += [(p.arg, "KEYWORD_ONLY", default(d)) for p, d in zip(a.kwonlyargs, a.kw_defaults, strict=True)]
    if a.kwarg:
        params.append((a.kwarg.arg, "VAR_KEYWORD", None))
    yields = any(isinstance(n, ast.Yield | ast.YieldFrom) for n in own_nodes(f))
    return f.name, tuple(params[1:]), isinstance(f, ast.AsyncFunctionDef) and not yields


def wrappers(directory: Path) -> dict[str, set[Member]]:
    """Each class of the modules of `directory` whose docstring begins with `WRAPPER`, by
    `path:class`, with its public calls."""
    found = {}
    for path in sorted(directory.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ClassDef) and (ast.get_docstring(node) or "").startswith(WRAPPER):
                found[f"{path.name}:{node.name}"] = {
                    member(f) for f in node.body
                    if isinstance(f, ast.FunctionDef | ast.AsyncFunctionDef) and not f.name.startswith("_")}
    return found


def test_each_kube_wrapper_has_every_call_of_the_protocol() -> None:
    calls = protocol()
    assert len(calls) == 12, sorted(calls)  # the twelve calls `kube.py` names
    found = wrappers(CLUSTER)
    # The walk is not blind: it finds both wrappers the cluster tier has.
    assert set(found) == {"test_restore_cluster.py:Observed", "test_clabernetes_changes_cluster.py:Killing"}
    for name, members in found.items():
        assert calls - members == set(), f"{name} lacks, or differs from, these calls of Kube: {calls - members}"
