"""The rehearsal library is kept by whoever replaces its source or its workflow engine (D-081, D-085), so it reaches
the core through the client and the model alone. Imported in a fresh interpreter, its modules load nothing of
Prefect, of a reader, of the example's other layers, of the core's `server` extra or of what the core's own clients
may never load (`core/tests/test_boundary.py`); and their source imports the standard library, five modules of the
core and the library itself, a function-local import included, which an import of the modules alone would not run."""

from __future__ import annotations

import ast
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

from test_boundary import forbidden

REHEARSAL = Path(__file__).resolve().parents[1] / "src" / "fylgja_orchestrator" / "rehearsal"
SRC = REHEARSAL.parents[1]

# What the library may never load, by module or package prefix, beyond the core's own list: the workflow engine,
# the reader, the example's other two layers, the core's server and the libraries of the core's `server` extra.
NEVER = (
    "prefect",
    "fylgja_infrahub",
    "fylgja_orchestrator.infrahub",
    "fylgja_orchestrator.edge",
    "fylgja_core.server",
    "starlette",
    "uvicorn",
    "grpc",
    "pygnmi",
    "lightkube",
    "httpx2",
    "msgspec",
)
# The core's modules the library may import: the client and the model it reads and writes.
CORE = {f"fylgja_core.{m}" for m in ("client", "findings", "problem", "documents", "schemas")}
OWN = "fylgja_orchestrator.rehearsal"

PROBE = """
import importlib
import sys
for name in sys.argv[1:]:
    importlib.import_module(name)
print("\\n".join(sorted(sys.modules)))
"""


def _files() -> list[Path]:
    """Every file under `rehearsal/`, but Python's own caches."""
    return sorted(p for p in REHEARSAL.rglob("*") if p.is_file() and "__pycache__" not in p.parts)


def _module(path: Path) -> str:
    """The dotted name of the module a file under `src/` is."""
    parts = path.relative_to(SRC).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def loaded(modules: Sequence[str]) -> set[str]:
    """Every module a fresh interpreter, isolated (`-I`), holds after importing each of `modules`."""
    argv = [sys.executable, "-I", "-c", PROBE, *modules]
    return set(subprocess.run(argv, check=True, capture_output=True, text=True).stdout.split())


def never(found: Iterable[str]) -> set[str]:
    """The modules among `found` the library may never load."""
    return {
        m
        for m in found
        if any(m == root or m.startswith(f"{root}.") for root in NEVER)
        or (m.startswith("fylgja_core.") and forbidden(m))
    }


def test_the_rehearsal_loads_nothing_of_prefect_the_reader_or_the_server() -> None:
    modules = [_module(p) for p in _files() if p.suffix == ".py"]
    assert OWN in modules
    found = loaded(modules)
    assert set(modules) <= found
    assert never(found) == set()
    assert "starlette.responses" in never(loaded(["fylgja_core.server.problems"])), "the probe is blind"


def imported(source: str, package: str) -> set[str]:
    """Every name `source`, a module of `package`, imports, anywhere in it: a from-import gives the module and the
    name it takes from it, and a relative one is resolved against `package`."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            base = package.split(".")
            base = base[: len(base) - node.level + 1] if node.level else []
            module = ".".join([*base, *([node.module] if node.module else [])])
            found |= {module if alias.name == "*" else f"{module}.{alias.name}" for alias in node.names}
    return found


def allowed(name: str) -> bool:
    """Whether the library may import `name`: of the standard library, one of the core's five modules or something in
    one, or the library's own."""
    if name.partition(".")[0] in sys.stdlib_module_names:
        return True
    return any(name == m or name.startswith(f"{m}.") for m in (*CORE, OWN))


def test_the_rehearsals_source_names_only_the_standard_library_the_cores_client_and_model_and_itself() -> None:
    files = _files()
    assert REHEARSAL / "__init__.py" in files, "the scan is blind"
    unparsed = [p.name for p in files if p.suffix != ".py"]
    assert unparsed == [], f"files the scan cannot read: {unparsed}"
    outside: list[str] = []
    for path in files:
        module = _module(path)
        package = module if path.name == "__init__.py" else module.rpartition(".")[0]
        outside += [f"{path.name}: {name}" for name in sorted(imported(path.read_text(), package)) if not allowed(name)]
    assert outside == []


def test_the_scan_sees_an_import_inside_a_function_and_resolves_a_relative_one() -> None:
    source = (
        "import json\n"
        "from fylgja_core.findings import Finding\n"
        "def f():\n"
        "    from fylgja_core import compiler\n"
        "    import fylgja_core.server.app\n"
        "    from . import names\n"
        "    from .. import edge\n"
    )
    assert imported(source, OWN) == {
        "json",
        "fylgja_core.findings.Finding",
        "fylgja_core.compiler",
        "fylgja_core.server.app",
        f"{OWN}.names",
        "fylgja_orchestrator.edge",
    }
    assert [allowed(n) for n in ("json", "fylgja_core.findings.Finding", f"{OWN}.names")] == [True] * 3
    assert [allowed(n) for n in ("fylgja_core.compiler", "fylgja_core", "fylgja_orchestrator.edge", "httpx")] == [
        False
    ] * 4


INFRAHUB = SRC / "fylgja_orchestrator" / "infrahub"
# What the change source may import beyond the standard library and itself: the reader, the core, httpx, and of the
# library the seam and the report alone, never the example's edge (D-081, D-085).
SOURCE_MAY = ("fylgja_infrahub", "fylgja_core", "httpx", f"{OWN}.source", f"{OWN}.report")


def test_the_change_sources_source_names_the_reader_the_core_httpx_and_the_seam_alone() -> None:
    files = sorted(p for p in INFRAHUB.rglob("*.py") if "__pycache__" not in p.parts)
    assert INFRAHUB / "__init__.py" in files, "the scan is blind"
    own = "fylgja_orchestrator.infrahub"
    outside: list[str] = []
    for path in files:
        module = _module(path)
        package = module if path.name == "__init__.py" else module.rpartition(".")[0]
        for name in sorted(imported(path.read_text(), package)):
            if name.partition(".")[0] in sys.stdlib_module_names:
                continue
            if not any(name == m or name.startswith(f"{m}.") for m in (*SOURCE_MAY, own)):
                outside.append(f"{path.name}: {name}")
    assert outside == []
