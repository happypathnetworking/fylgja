"""The wheel check's parts that need no network (D-066, D-084): the floors it installs the base
alone at are the lower bounds of the base's ranges in `core/pyproject.toml`, read from there and
stated by no test, and an entry that is no range is refused; and the base modules it imports
there are the sixteen `test_boundary_base.py` holds, read from the script by `ast`, so the two
lists cannot drift. What it holds each reader's command never to load beside the base is that
reader's import test's `FORBIDDEN`, the script's tuple read from the loaded module and the test's
by `ast`, so those cannot drift either; nor can what it holds each change source never to load
beside its own reader, which is the example's import scan's `CROSSED`. The check itself builds
and installs, and runs as `make wheelcheck`."""

from __future__ import annotations

import ast
import importlib.util
import tomllib
from functools import cache
from pathlib import Path
from types import ModuleType

import pytest
from test_boundary_base import BASE

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "wheelcheck.py"


@cache
def _script() -> ModuleType:
    """`scripts/wheelcheck.py`, loaded by path."""
    spec = importlib.util.spec_from_file_location("script_wheelcheck", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_floors_are_the_bases_ranges_lower_bounds() -> None:
    with (ROOT / "core" / "pyproject.toml").open("rb") as f:
        entries = tomllib.load(f)["project"]["dependencies"]
    expected = {}
    for entry in entries:
        name, _, rest = entry.partition(">=")
        expected[name] = rest.partition(",<")[0]
    assert set(expected) == {"httpx", "jsonschema", "PyYAML", "referencing"}
    assert _script().floors() == expected


@pytest.mark.parametrize("entry", ["httpx", "httpx>=0.27.0", "httpx==0.28.1"])
def test_a_base_entry_that_is_no_range_is_refused(tmp_path: Path, entry: str) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(f'[project]\nname = "fylgja-core"\ndependencies = ["{entry}"]\n')
    module = _script()
    with pytest.raises(module.Failure) as raised:
        module.floors(pyproject)
    assert entry in str(raised.value)


def test_the_base_modules_the_check_imports_are_the_boundarys() -> None:
    assigned = [
        statement.value
        for statement in ast.parse(SCRIPT.read_text(), str(SCRIPT)).body
        if isinstance(statement, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "BASE_MODULES" for target in statement.targets)
    ]
    assert len(assigned) == 1, "scripts/wheelcheck.py assigns BASE_MODULES once"
    assert ast.literal_eval(assigned[0]) == BASE


def _assigned(path: Path, name: str) -> tuple[object, ...]:
    """The tuple the file at `path` assigns to `name`, read by `ast`."""
    assigned = [
        statement.value
        for statement in ast.parse(path.read_text(), str(path)).body
        if isinstance(statement, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == name for target in statement.targets)
    ]
    assert len(assigned) == 1, f"{path} assigns {name} once"
    held = ast.literal_eval(assigned[0])
    assert isinstance(held, tuple)
    return held


def _forbidden(path: Path) -> tuple[str, ...]:
    """The `FORBIDDEN` a reader's import test at `path` assigns, read by `ast`."""
    return tuple(str(name) for name in _assigned(path, "FORBIDDEN"))


@pytest.mark.parametrize(
    ("name", "reader"),
    [("NOT_BESIDE_READER", "infrahub"), ("NOT_BESIDE_NETBOX_READER", "netbox")],
)
def test_what_a_readers_command_never_loads_is_its_import_tests(name: str, reader: str) -> None:
    held = getattr(_script(), name)
    assert sorted(held) == sorted(_forbidden(ROOT / "readers" / reader / "tests" / "test_boundary.py"))


def test_what_each_change_source_never_loads_is_the_example_scans() -> None:
    """Importing the Infrahub change source loads nothing of the NetBox one or its reader, and the reverse."""
    held = _assigned(SCRIPT, "CROSSED")
    assert held == _assigned(ROOT / "orchestrator" / "tests" / "test_boundary_edge.py", "CROSSED")
    assert sorted(str(pair[0]) for pair in held if isinstance(pair, tuple)) == ["infrahub", "netbox"]
