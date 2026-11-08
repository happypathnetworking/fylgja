"""The API is the boundary (Constitution XI, D-025): the thin CLI and the client library reach
the core through API 1 alone. Imported in a fresh interpreter, they load from `fylgja_core`
only the model package, never the compiler, the store, a driver, the loop or the server; and
their source imports nothing else, a function-local import included, which an import of the
modules alone would not run."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "fylgja_core"
CLIENTS = [SRC / "cli.py", SRC / "client.py"]

# The model modules a client may load: the formats, their validation and the ids.
MODEL = {
    "documents",
    "schemas",
    "blueprint",
    "bundle",
    "deployment",
    "twin_record",
    "findings",
    "problem",
    "run",
    "platform_package",
    "probe_package",
    "probes",
    "clock",
    "ulid",
}
ALLOWED = {"fylgja_core", "fylgja_core.cli", "fylgja_core.client"} | {f"fylgja_core.{m}" for m in MODEL}

# What a client must never load, by module or package prefix.
FORBIDDEN = (
    "compiler",
    "store",
    "local_store",
    "object_store",
    "driver",
    "drivers",
    "containerlab",
    "clabernetes",
    "reconcile",
    "queue",
    "push",
    "readiness",
    "credentials",
    "config",
    "packages",
    "server",
    "s3",
    "kubeapi",
    "lease",
)

PROBE = """
import sys
import fylgja_core.cli, fylgja_core.client
print("\\n".join(sorted(m for m in sys.modules if m == "fylgja_core" or m.startswith("fylgja_core."))))
"""


def loaded() -> set[str]:
    out = subprocess.run([sys.executable, "-I", "-c", PROBE], check=True, capture_output=True, text=True).stdout
    return set(out.split())


def forbidden(module: str) -> bool:
    name = module.removeprefix("fylgja_core.")
    return any(name == f or name.startswith((f"{f}.", f"{f}_")) for f in FORBIDDEN)


def test_the_cli_and_the_client_load_only_the_model_package() -> None:
    found = loaded()
    assert {"fylgja_core.cli", "fylgja_core.client"} <= found
    assert found <= ALLOWED, f"beyond the model package: {sorted(found - ALLOWED)}"
    assert not any(forbidden(m) for m in found)


def imported(source: str) -> set[str]:
    """Every `fylgja_core` module a source imports, anywhere in it: a from-import that names a
    module of a package records that module, not the package."""
    found = set()
    for node in ast.walk(ast.parse(source)):
        names: list[str] = []
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None and node.level == 0, "a relative import hides its module"
            for alias in node.names:
                name = f"{node.module}.{alias.name}"
                path = SRC.parent.joinpath(*name.split("."))
                is_module = path.with_suffix(".py").is_file() or (path / "__init__.py").is_file()
                names.append(name if is_module else node.module)
        found |= {n for n in names if n == "fylgja_core" or n.startswith("fylgja_core.")}
    return found


@pytest.mark.parametrize("path", CLIENTS, ids=lambda p: p.name)
def test_the_cli_and_the_client_import_only_the_model_package(path: Path) -> None:
    found = imported(path.read_text())
    assert found, f"{path.name} imports nothing of fylgja_core: the scan is blind"
    assert found <= ALLOWED, f"{path.name} imports beyond the model package: {sorted(found - ALLOWED)}"


def test_the_scan_sees_an_import_inside_a_function() -> None:
    source = "def f():\n    from fylgja_core import compiler\n    import fylgja_core.server.app\n"
    assert imported(source) == {"fylgja_core.compiler", "fylgja_core.server.app"}
    assert imported("from fylgja_core.findings import Verdict\n") == {"fylgja_core.findings"}


def test_no_allowed_module_is_a_forbidden_one() -> None:
    assert not any(forbidden(m) for m in ALLOWED)
    assert forbidden("fylgja_core.push_eapi") and forbidden("fylgja_core.server.app")
    assert forbidden("fylgja_core.containerlab.driver") and not forbidden("fylgja_core.problem")
    assert forbidden("fylgja_core.clabernetes.plan")
