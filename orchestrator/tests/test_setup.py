"""The example's wheel carries the formats its own code reads, by a list, `ORCHESTRATOR_FORMATS` in
`orchestrator/setup.py`, as the core's carries the core's (D-066, D-084): a format of the core's is the core's wheel's
to carry, never this one's. setuptools is no library of the development venv, so the build step runs here over a
stand-in for the two names `setup.py` takes from it."""

from __future__ import annotations

import ast
import importlib.util
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SETUP = ROOT / "orchestrator" / "setup.py"


def _listed(path: Path, name: str) -> tuple[str, ...]:
    """The tuple of strings `path` assigns to `name`, read by `ast`."""
    (value,) = [
        statement.value
        for statement in ast.parse(path.read_text(), str(path)).body
        if isinstance(statement, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == name for target in statement.targets)
    ]
    found = ast.literal_eval(value)
    assert isinstance(found, tuple) and all(isinstance(n, str) for n in found), f"{name} is no tuple of strings"
    return found


def test_the_list_names_formats_under_formats_and_none_of_the_cores() -> None:
    listed = _listed(SETUP, "ORCHESTRATOR_FORMATS")
    assert list(listed) == sorted(set(listed))
    core = _listed(ROOT / "core" / "setup.py", "CORE_FORMATS")
    assert "blueprint-1.schema.json" in core
    assert set(listed).isdisjoint(core)
    assert [n for n in listed if not (ROOT / "formats" / n).is_file()] == []


class _BuildPy:
    """Stands in for setuptools' `build_py`: its own run builds nothing, and its two helpers do what setuptools' do."""

    build_lib = ""

    def run(self) -> None:
        pass

    def mkpath(self, name: str) -> None:
        Path(name).mkdir(parents=True, exist_ok=True)

    def copy_file(self, infile: str, outfile: str) -> None:
        shutil.copyfile(infile, outfile)


@pytest.fixture
def setup_py(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """`orchestrator/setup.py`, loaded over the stand-in, its `setup()` a call that does nothing."""
    setuptools = ModuleType("setuptools")
    vars(setuptools)["setup"] = lambda **_: None
    command = ModuleType("setuptools.command.build_py")
    vars(command)["build_py"] = _BuildPy
    monkeypatch.setitem(sys.modules, "setuptools", setuptools)
    monkeypatch.setitem(sys.modules, "setuptools.command", ModuleType("setuptools.command"))
    monkeypatch.setitem(sys.modules, "setuptools.command.build_py", command)
    spec = importlib.util.spec_from_file_location("orchestrator_setup", SETUP)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build(setup_py: ModuleType, build_lib: Path) -> list[str]:
    """The files the build step leaves under `build_lib`."""
    step = setup_py.BuildPy()
    step.build_lib = str(build_lib)
    step.run()
    return sorted(p.relative_to(build_lib).as_posix() for p in build_lib.rglob("*") if p.is_file())


def test_the_build_copies_the_listed_formats_and_stops_at_one_missing(
    setup_py: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    listed = _listed(SETUP, "ORCHESTRATOR_FORMATS")
    assert _build(setup_py, tmp_path / "shipped") == [f"fylgja_orchestrator/formats/{n}" for n in listed]

    formats = tmp_path / "formats"
    formats.mkdir()
    (formats / "a-1.schema.json").write_text("{}\n")
    monkeypatch.setattr(setup_py, "FORMATS", formats)
    monkeypatch.setattr(setup_py, "ORCHESTRATOR_FORMATS", ())
    assert _build(setup_py, tmp_path / "none") == []
    monkeypatch.setattr(setup_py, "ORCHESTRATOR_FORMATS", ("a-1.schema.json",))
    assert _build(setup_py, tmp_path / "one") == ["fylgja_orchestrator/formats/a-1.schema.json"]
    monkeypatch.setattr(setup_py, "ORCHESTRATOR_FORMATS", ("a-1.schema.json", "b-1.schema.json"))
    with pytest.raises(SystemExit, match=r"^no b-1\.schema\.json under "):
        _build(setup_py, tmp_path / "missing")
