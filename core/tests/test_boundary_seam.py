"""The seam's boundary (Constitution XIII, D-046): nothing above the seam names a runtime.
Only the local driver's own package and the driver registry import `fylgja_core.containerlab`;
every other module reaches a runtime through `fylgja_core.driver` and the registry alone."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "fylgja_core"
DRIVER = "fylgja_core.containerlab"
BEHIND = SRC / "containerlab"
REGISTRY = SRC / "drivers.py"


def imports(source: str) -> set[str]:
    """Every module `source` imports, as the purity tests collect them: a from-import that
    names a module of a package records that module, not the package."""
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None and node.level == 0, "a relative import hides its module"
            for alias in node.names:
                name = f"{node.module}.{alias.name}"
                path = SRC.parent.joinpath(*name.split("."))
                is_module = path.with_suffix(".py").is_file() or (path / "__init__.py").is_file()
                imported.add(name if is_module else node.module)
    return imported


def names_the_driver(module: str) -> bool:
    return module == DRIVER or module.startswith(f"{DRIVER}.")


ABOVE = sorted(p for p in SRC.rglob("*.py") if not p.is_relative_to(BEHIND) and p != REGISTRY)


@pytest.mark.parametrize("path", ABOVE, ids=lambda p: p.relative_to(SRC).as_posix())
def test_no_module_above_the_seam_imports_the_local_driver(path: Path) -> None:
    found = sorted(m for m in imports(path.read_text()) if names_the_driver(m))
    assert found == [], f"{path.relative_to(SRC)} names a runtime: {found}"


def test_the_registry_is_the_one_that_does() -> None:
    # The scan sees an import of the driver where there is one: the registry's.
    assert {"fylgja_core.containerlab", "fylgja_core.containerlab.driver"} <= imports(REGISTRY.read_text())
    assert ABOVE and all(p.suffix == ".py" for p in ABOVE)
    assert SRC / "driver.py" in ABOVE and SRC / "compiler.py" in ABOVE
