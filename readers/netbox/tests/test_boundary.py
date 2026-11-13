"""The reader is installed into a platform it does not own, so it reaches the core through the base install alone and
meets NetBox through httpx alone (D-095, D-096, D-084). Imported in a fresh interpreter, its modules load nothing of
the Infrahub reader, of the example orchestrator, of Prefect, of a client library of Infrahub's or NetBox's or of the
core's `server` extra, and of the core only seven modules of the model and the client; and their source imports the
standard library, those seven, the reader itself and httpx, a function-local import included, which an import of the
modules alone would not run, and httpx in `transport.py` alone."""

from __future__ import annotations

import ast
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
READER = SRC / "fylgja_netbox"
OWN = "fylgja_netbox"
TRANSPORT = READER / "transport.py"

# The core's modules the reader may load: the model it builds and checks, and the client's TLS and token rules.
ALLOWED_CORE = {"fylgja_core"} | {
    f"fylgja_core.{m}" for m in ("blueprint", "probes", "findings", "documents", "schemas", "problem", "client")
}
# What the reader may never load, by module or package prefix: the other reader, the example, Prefect, the client
# libraries of Infrahub and of NetBox, and the libraries of the core's `server` extra.
FORBIDDEN = (
    "fylgja_infrahub",
    "fylgja_orchestrator",
    "prefect",
    "infrahub_sdk",
    "pynetbox",
    "starlette",
    "uvicorn",
    "grpc",
    "google.protobuf",
    "pygnmi",
    "lightkube",
    "msgspec",
    "httpx2",
)

PROBE = """
import importlib
import pkgutil
import sys

import fylgja_netbox

walked = [module.name for module in pkgutil.walk_packages(fylgja_netbox.__path__, "fylgja_netbox.")]
for name in [*walked, *sys.argv[1:]]:
    importlib.import_module(name)
print("\\n".join(sorted(sys.modules)))
"""


def _files() -> list[Path]:
    """Every Python file under `src/fylgja_netbox/`."""
    return sorted(p for p in READER.rglob("*.py") if "__pycache__" not in p.parts)


def _module(path: Path) -> str:
    """The dotted name of the module a file under `src/` is."""
    parts = path.relative_to(SRC).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def loaded(*also: str) -> set[str]:
    """Every module a fresh interpreter, isolated (`-I`), holds after importing each module of the reader, walked with
    `pkgutil`, and each of `also`."""
    argv = [sys.executable, "-I", "-c", PROBE, *also]
    return set(subprocess.run(argv, check=True, capture_output=True, text=True).stdout.split())


def refused(found: Iterable[str]) -> set[str]:
    """The modules among `found` the reader may never load: one under `FORBIDDEN`, or one of the core's not allowed."""
    return {
        m
        for m in found
        if any(m == root or m.startswith(f"{root}.") for root in FORBIDDEN)
        or ((m == "fylgja_core" or m.startswith("fylgja_core.")) and m not in ALLOWED_CORE)
    }


def test_the_reader_loads_nothing_of_the_other_reader_the_example_prefect_or_the_server() -> None:
    modules = {_module(p) for p in _files()}
    assert {OWN, f"{OWN}.rows", f"{OWN}.transport"} <= modules
    found = loaded()
    assert modules <= found, "the walk is blind"
    assert refused(found) == set()
    assert {"starlette.responses", "fylgja_core.server"} <= refused(loaded("fylgja_core.server.problems")), (
        "the probe is blind"
    )


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
    """Whether the reader may import `name`: of the standard library, the reader's own or httpx, or one of the core's
    allowed modules or something in one; `fylgja_core` itself only as the package, never a module of it not allowed."""
    if name.partition(".")[0] in (*sys.stdlib_module_names, OWN, "httpx"):
        return True
    return name in ALLOWED_CORE or any(name.startswith(f"{m}.") for m in ALLOWED_CORE - {"fylgja_core"})


def _imports() -> dict[Path, set[str]]:
    """What each Python file of the reader imports."""
    found = {}
    for path in _files():
        module = _module(path)
        package = module if path.name == "__init__.py" else module.rpartition(".")[0]
        found[path] = imported(path.read_text(), package)
    return found


def test_every_source_imports_only_what_the_reader_may() -> None:
    imports = _imports()
    assert READER / "__init__.py" in imports, "the scan is blind"
    assert any(name.startswith("fylgja_core.") for names in imports.values() for name in names), "the scan is blind"
    outside = [f"{path.name}: {name}" for path, names in imports.items() for name in sorted(names) if not allowed(name)]
    assert outside == []


def test_httpx_is_the_transports_alone() -> None:
    importers = {
        path.relative_to(READER).as_posix()
        for path, names in _imports().items()
        if any(name == "httpx" or name.startswith("httpx.") for name in names)
    }
    assert importers == {"transport.py"}


def test_the_scan_sees_an_import_inside_a_function() -> None:
    source = (
        "import json\n"
        "from fylgja_core.findings import Finding\n"
        "def f():\n"
        "    import httpx\n"
        "    from fylgja_core import compiler\n"
        "    import fylgja_core.server.app\n"
        "    import fylgja_infrahub.rows\n"
        "    from pynetbox import api\n"
        "    from . import rows\n"
        "    from .rows import Listing\n"
    )
    assert imported(source, OWN) == {
        "json",
        "fylgja_core.findings.Finding",
        "httpx",
        "fylgja_core.compiler",
        "fylgja_core.server.app",
        "fylgja_infrahub.rows",
        "pynetbox.api",
        f"{OWN}.rows",
        f"{OWN}.rows.Listing",
    }
    assert [allowed(n) for n in ("json", "fylgja_core.findings.Finding", "httpx", f"{OWN}.rows", "fylgja_core")] == [
        True
    ] * 5
    assert [
        allowed(n)
        for n in ("fylgja_core.compiler", "fylgja_core.server.app", "fylgja_infrahub.rows", "pynetbox.api", "prefect")
    ] == [False] * 5
