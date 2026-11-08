"""The seam's boundary (Constitution XIII, D-046): nothing above the seam names a runtime.
A driver's package is behind the seam: only the drivers' own packages and the driver registry
import `fylgja_core.containerlab` or `fylgja_core.clabernetes`; every other module reaches a
runtime through `fylgja_core.driver` and the registry alone.

The two containerlab drivers share the local driver's pure half and nothing else of it
(D-057): clabernetes imports the local driver's `plan` and `changes` modules alone, never its
package's names, its CLI runner or its pool, and the local driver imports nothing of
clabernetes. lightkube, and httpx2 beneath it, are imported by three modules alone (D-064): the one
that makes the core's Kubernetes client, `kubeapi.py`, the Lease, `lease.py`, and the clabernetes
driver's reach into Kubernetes, `clabernetes/kube.py`. The first two are above the seam, and import
nothing of a driver's package."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "fylgja_core"
LOCAL = "fylgja_core.containerlab"
CLABERNETES = "fylgja_core.clabernetes"
DRIVERS = (LOCAL, CLABERNETES)
BEHIND = (SRC / "containerlab", SRC / "clabernetes")
REGISTRY = SRC / "drivers.py"
# What clabernetes may import of the local driver: its pure half.
SHARED = {f"{LOCAL}.plan", f"{LOCAL}.changes"}
# The Kubernetes client and its HTTP stack, and the modules that may import them: the one that makes the client and
# the Lease, above the seam, and the driver's reach.
KUBERNETES = ("lightkube", "httpx2")
REACH = SRC / "clabernetes" / "kube.py"
KUBERNETES_MODULES = (SRC / "kubeapi.py", SRC / "lease.py", REACH)


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


def within(module: str, package: str) -> bool:
    return module == package or module.startswith(f"{package}.")


def names_a_driver(module: str) -> bool:
    return any(within(module, driver) for driver in DRIVERS)


ABOVE = sorted(p for p in SRC.rglob("*.py") if not any(p.is_relative_to(b) for b in BEHIND) and p != REGISTRY)


@pytest.mark.parametrize("path", ABOVE, ids=lambda p: p.relative_to(SRC).as_posix())
def test_no_module_above_the_seam_imports_a_driver(path: Path) -> None:
    found = sorted(m for m in imports(path.read_text()) if names_a_driver(m))
    assert found == [], f"{path.relative_to(SRC)} names a runtime: {found}"


def test_the_registry_is_the_one_that_does() -> None:
    # The scan sees an import of each driver where there is one: the registry's.
    assert {"fylgja_core.containerlab", "fylgja_core.containerlab.driver", "fylgja_core.clabernetes",
            "fylgja_core.clabernetes.driver"} <= imports(REGISTRY.read_text())
    assert ABOVE and all(p.suffix == ".py" for p in ABOVE)
    assert SRC / "driver.py" in ABOVE and SRC / "compiler.py" in ABOVE
    # Both drivers' packages are behind the seam, and an import of either is refused above it.
    assert not any(p.is_relative_to(SRC / "clabernetes") for p in ABOVE)
    assert names_a_driver("fylgja_core.clabernetes.plan") and not names_a_driver("fylgja_core.clabernetes_x")


def test_the_drivers_share_the_local_drivers_pure_half_alone() -> None:
    local, clabernetes = (sorted(directory.rglob("*.py")) for directory in BEHIND)
    assert local and clabernetes, "the scan is blind"
    reached = {
        p.relative_to(SRC).as_posix(): found
        for p in clabernetes
        if (found := sorted(m for m in imports(p.read_text()) if within(m, LOCAL) and m not in SHARED))
    }
    assert reached == {}, f"clabernetes reaches beyond the local driver's plan and changes: {reached}"
    backwards = {
        p.relative_to(SRC).as_posix(): found
        for p in local
        if (found := sorted(m for m in imports(p.read_text()) if within(m, CLABERNETES)))
    }
    assert backwards == {}, f"the local driver imports clabernetes: {backwards}"
    # The scan tells the shared modules from the rest of the local driver's package.
    source = "from fylgja_core.containerlab import NAME, changes, plan, pool\n"
    assert imports(source) - SHARED == {"fylgja_core.containerlab", "fylgja_core.containerlab.pool"}


def test_lightkube_is_imported_by_the_client_the_lease_and_the_clabernetes_drivers_reach_alone() -> None:
    reaching = {
        p.relative_to(SRC).as_posix(): found
        for p in sorted(SRC.rglob("*.py"))
        if (found := sorted(m for m in imports(p.read_text()) if any(within(m, k) for k in KUBERNETES)))
    }
    allowed = {p.relative_to(SRC).as_posix() for p in KUBERNETES_MODULES}
    assert set(reaching) == allowed, f"lightkube or httpx2 is imported beyond {sorted(allowed)}: {reaching}"
    # Those outside the driver's package are above the seam, so the scan above holds them to name no runtime.
    assert all(p in ABOVE for p in KUBERNETES_MODULES if not p.is_relative_to(SRC / "clabernetes"))
    reach = REACH.relative_to(SRC).as_posix()
    # The scan sees the reach's imports of both, httpx2's websockets among them.
    assert {m.split(".")[0] for m in reaching[reach]} == set(KUBERNETES)
    assert "httpx2.websockets" in reaching[reach]
