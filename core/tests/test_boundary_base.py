"""The base install (D-084): `fylgja-core` installed with no extra is the model package, the client library and
the thin CLI, over four libraries as ranges, httpx, jsonschema, referencing and PyYAML, each from the lowest release
tried, on which the base's tests passed (verified-facts.md, "The base install at its floors"), to below its next
major. The server's libraries are the extra `server`, which repeats the base's four at today's pins, so that an
install of the extra is today's install.

The sixteen modules of the base, imported in a fresh interpreter, load no module of the extra, and their source
imports, of anything outside the standard library and `fylgja_core`, the base's four alone, a function-local import
included. The extra is told by its own libraries' modules, never by their dependencies: a library the extra brings
may be one a base library loads where it finds it installed (httpx imports `click` when it is there, and click is
uvicorn's), which is no fault of the base's, and in a venv that holds the extra it is always there."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
import tomllib
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from test_boundary import MODEL

CORE = Path(__file__).resolve().parents[1]
SRC = CORE / "src" / "fylgja_core"

# The base's modules, each `fylgja_core.<module>`: the model package and the two clients.
BASE: tuple[str, ...] = (
    "blueprint",
    "bundle",
    "cli",
    "client",
    "clock",
    "deployment",
    "documents",
    "findings",
    "platform_package",
    "probe_package",
    "probes",
    "problem",
    "run",
    "schemas",
    "twin_record",
    "ulid",
)
# The seven of them the Infrahub reader needs (D-084).
READER = {"blueprint", "probes", "findings", "schemas", "documents", "problem", "client"}

# The extra's libraries beyond the base's four, each to the module it installs: a top-level name, but for protobuf,
# whose `google` is a namespace other distributions share.
EXTRA: dict[str, str] = {
    "grpcio": "grpc",
    "httpx2": "httpx2",
    "lightkube": "lightkube",
    "lightkube-models": "lightkube",
    "msgspec": "msgspec",
    "protobuf": "google.protobuf",
    "pygnmi": "pygnmi",
    "starlette": "starlette",
    "uvicorn": "uvicorn",
}
# The extra `server`, each library at today's pin: the server's libraries and the base's four.
SERVER: dict[str, str] = {
    "grpcio": "1.84.0",
    "httpx": "0.28.1",
    "httpx2": "2.16.0",
    "jsonschema": "4.26.0",
    "lightkube": "1.0.1",
    "lightkube-models": "1.37.0.8",
    "msgspec": "0.22.0",
    "protobuf": "7.36.2",
    "pygnmi": "0.8.15",
    "PyYAML": "6.0.3",
    "referencing": "0.37.0",
    "starlette": "1.9.0",
    "uvicorn": "0.54.0",
}
# The base's libraries by the top-level name their source imports.
LIBRARIES = {"httpx", "jsonschema", "referencing", "yaml"}
# Each base library's ceiling, its next major.
CEILINGS = {"httpx": "1", "jsonschema": "5", "PyYAML": "7", "referencing": "1"}
_RANGE = re.compile(r"^([A-Za-z0-9_.-]+)>=([0-9]+(?:\.[0-9]+)*),<([0-9]+)$")

PROBE = """
import importlib
import sys
for name in sys.argv[1:]:
    importlib.import_module("fylgja_core." + name)
print("\\n".join(sorted(sys.modules)))
"""


def loaded(modules: Sequence[str]) -> set[str]:
    """Every module a fresh interpreter, isolated (`-I`), holds after importing each `fylgja_core.<module>`."""
    argv = [sys.executable, "-I", "-c", PROBE, *modules]
    return set(subprocess.run(argv, check=True, capture_output=True, text=True).stdout.split())


def of_the_extra(found: Iterable[str]) -> set[str]:
    """The modules among `found` that are one of the extra's own or inside one."""
    roots = set(EXTRA.values())
    return {m for m in found if any(m == root or m.startswith(f"{root}.") for root in roots)}


def libraries(source: str) -> set[str]:
    """The top-level name of every module `source` imports, anywhere in it, outside the standard library and
    `fylgja_core`; a relative import is `fylgja_core`'s own."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found |= {alias.name.partition(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.partition(".")[0])
    return found - sys.stdlib_module_names - {"fylgja_core"}


def _project() -> dict[str, Any]:
    with (CORE / "pyproject.toml").open("rb") as f:
        project: dict[str, Any] = tomllib.load(f)["project"]
    return project


def _base() -> dict[str, tuple[str, str]]:
    """The base's libraries as `core/pyproject.toml` gives them, each to its floor and its ceiling."""
    found = {}
    for entry in _project()["dependencies"]:
        match = _RANGE.match(entry)
        assert match, f"{entry} is not name>=floor,<ceiling"
        found[match.group(1)] = (match.group(2), match.group(3))
    return found


def _version(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split("."))


def test_the_base_loads_no_module_of_the_server_extra() -> None:
    found = loaded(BASE)
    assert of_the_extra(found) == set()
    assert {"fylgja_core." + m for m in BASE} <= found


def test_the_base_is_the_model_package_and_the_two_clients() -> None:
    assert set(BASE) == MODEL | {"cli", "client"}
    assert set(BASE) >= READER


def test_the_scan_tells_the_extras_modules_from_their_neighbours() -> None:
    found = {
        "google.protobuf.message",
        "google.auth",
        "lightkube.models.core_v1",
        "httpx",
        "httpx2._client",
        "click",
        "starlette",
    }
    assert of_the_extra(found) == {"google.protobuf.message", "lightkube.models.core_v1", "httpx2._client", "starlette"}
    assert "starlette.responses" in of_the_extra(loaded(["server.problems"])), "the probe is blind"


def test_the_base_modules_import_only_the_bases_libraries() -> None:
    found = set().union(*(libraries((SRC / f"{m}.py").read_text()) for m in BASE))
    assert found == LIBRARIES


def test_the_base_is_four_ranges_each_below_its_next_major() -> None:
    base = _base()
    assert len(_project()["dependencies"]) == 4
    assert {name: ceiling for name, (_, ceiling) in base.items()} == CEILINGS


def test_the_server_extra_is_todays_pins_and_repeats_the_base_within_its_ranges() -> None:
    entries = _project()["optional-dependencies"]["server"]
    pins: dict[str, str] = {}
    for entry in entries:
        name, pinned, version = entry.partition("==")
        assert pinned and name and version, f"{entry} is not name==version"
        pins[name] = version
    assert len(entries) == len(pins)
    assert pins == SERVER
    base = _base()
    for name, (floor, ceiling) in base.items():
        pin = pins[name]
        assert _version(floor) <= _version(pin) < _version(ceiling), f"{name}=={pin} is not >={floor},<{ceiling}"
    assert set(pins) - set(base) == set(EXTRA)
