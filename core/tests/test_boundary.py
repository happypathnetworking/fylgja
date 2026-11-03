"""The API is the boundary (Constitution XI, D-025): the thin CLI and the client library reach
the core through API 1 alone. Imported in a fresh interpreter, they load from `fylgja_core`
only the model package, never the compiler, the store, a driver, the loop or the server."""

from __future__ import annotations

import subprocess
import sys

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
    "driver",
    "drivers",
    "containerlab",
    "reconcile",
    "queue",
    "push",
    "readiness",
    "credentials",
    "config",
    "packages",
    "server",
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


def test_no_allowed_module_is_a_forbidden_one() -> None:
    assert not any(forbidden(m) for m in ALLOWED)
    assert forbidden("fylgja_core.push_eapi") and forbidden("fylgja_core.server.app")
    assert forbidden("fylgja_core.containerlab.driver") and not forbidden("fylgja_core.problem")
