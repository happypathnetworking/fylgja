"""The cluster tier's wrappers of `Kube` held to the protocol in the pure tier. A cluster test
hands the driver a class of its own that passes each call to the client (`Observed`, `Killing`);
a call added to `clabernetes.kube.Kube` and missing from one of them would be found only when
the driver made it on the cluster, in a window. Each wrapper is read by `ast`, never imported:
its module imports lightkube and the cluster's fixtures."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from fylgja_core.clabernetes.kube import Kube

CLUSTER = Path(__file__).resolve().parent / "cluster"
WRAPPER = "`Kube` over"
"""How a wrapper's docstring begins."""

type Member = tuple[str, tuple[str, ...], bool]
"""A call as its name, its parameters' names after `self`, and whether it is awaited."""


def protocol() -> set[Member]:
    """`Kube`'s calls. One is awaited when it is a coroutine function: `watch_pods`, a plain
    function answering an async generator, is not."""
    return {(name, tuple(inspect.signature(f).parameters)[1:], inspect.iscoroutinefunction(f))
            for name, f in vars(Kube).items() if inspect.isfunction(f) and not name.startswith("_")}


def member(f: ast.FunctionDef | ast.AsyncFunctionDef) -> Member:
    """A wrapper's method as a `Member`. An `async def` that yields is an async generator
    function: called, it answers its generator at once, as the protocol's `watch_pods` does, so it
    is not awaited."""
    a = f.args
    names = [p.arg for p in [*a.posonlyargs, *a.args, *a.kwonlyargs]]
    names += [p.arg for p in (a.vararg, a.kwarg) if p is not None]
    yields = any(isinstance(n, ast.Yield | ast.YieldFrom) for n in ast.walk(f))
    return f.name, tuple(names[1:]), isinstance(f, ast.AsyncFunctionDef) and not yields


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
