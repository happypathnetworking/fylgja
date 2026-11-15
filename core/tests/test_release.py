"""The release's one version (D-106): written once, in `VERSION` at the root, as `formats/` is the one place a format
lives (D-066), and read by every distribution's build, each `setup.py` passing it to `setup(version=...)` and each
`pyproject.toml` listing `version` as dynamic; and each reader requiring the core at that version or later within the
major. setuptools is no library of the development venv, so each `setup.py` is loaded here over a stand-in for the two
names it takes from it, `setup` recording what it is given."""

from __future__ import annotations

import importlib.util
import re
import sys
import tomllib
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
MEMBERS = ["core", "readers/infrahub", "readers/netbox", "orchestrator"]
READERS = ["readers/infrahub", "readers/netbox"]
# A release, X.Y.Z, or its candidate, X.Y.ZrcN.
FORM = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(rc[1-9]\d*)?")
VERSION = (ROOT / "VERSION").read_text().strip()


def project(member: str) -> dict[str, Any]:
    with (ROOT / member / "pyproject.toml").open("rb") as f:
        found: dict[str, Any] = tomllib.load(f)["project"]
    return found


class _BuildPy:
    """Stands in for setuptools' `build_py`; nothing here runs it."""


def load_setup(member: str, monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, list[dict[str, Any]]]:
    """`<member>/setup.py`, loaded over the stand-in, and the keywords each call of its `setup()` was given."""
    given: list[dict[str, Any]] = []
    setuptools = ModuleType("setuptools")
    vars(setuptools)["setup"] = lambda **kw: given.append(kw)
    command = ModuleType("setuptools.command.build_py")
    vars(command)["build_py"] = _BuildPy
    monkeypatch.setitem(sys.modules, "setuptools", setuptools)
    monkeypatch.setitem(sys.modules, "setuptools.command", ModuleType("setuptools.command"))
    monkeypatch.setitem(sys.modules, "setuptools.command.build_py", command)
    spec = importlib.util.spec_from_file_location(f"setup_{member.replace('/', '_')}", ROOT / member / "setup.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, given


def test_the_version_is_one_line_of_a_release_or_a_candidate() -> None:
    assert (ROOT / "VERSION").read_text() == VERSION + "\n"
    assert FORM.fullmatch(VERSION), VERSION
    assert VERSION == "1.0.0rc1"


@pytest.mark.parametrize("member", MEMBERS)
def test_each_distribution_takes_its_version_from_the_one_file(
    member: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    found = project(member)
    assert "version" not in found
    assert "version" in found["dynamic"]
    module, given = load_setup(member, monkeypatch)
    assert module.ROOT == ROOT
    assert module.FORMATS == ROOT / "formats"
    assert [kw["version"] for kw in given] == [VERSION]
    assert module.version() == VERSION

    with pytest.raises(SystemExit, match=re.escape(str(tmp_path / "VERSION"))):
        module.version(tmp_path)
    (tmp_path / "VERSION").write_text("1.0.0rc1\n1.0.0\n")
    with pytest.raises(SystemExit, match=re.escape(str(tmp_path / "VERSION"))):
        module.version(tmp_path)
    (tmp_path / "VERSION").write_text("\n")
    with pytest.raises(SystemExit, match=re.escape(str(tmp_path / "VERSION"))):
        module.version(tmp_path)
    (tmp_path / "VERSION").write_text(" 2.1.0 \n")
    assert module.version(tmp_path) == "2.1.0"


@pytest.mark.parametrize("member", READERS)
def test_each_reader_requires_the_core_at_its_own_version_within_the_major(member: str) -> None:
    on_core = [entry for entry in project(member)["dependencies"] if re.match(r"fylgja-core\b", entry)]
    assert on_core == [f"fylgja-core>={VERSION},<{int(VERSION.split('.')[0]) + 1}"]


def test_the_example_names_the_core_and_the_readers_without_a_range() -> None:
    dependencies = project("orchestrator")["dependencies"]
    ours = [entry for entry in dependencies if entry.startswith("fylgja-")]
    assert ours == ["fylgja-core", "fylgja-infrahub", "fylgja-netbox"]
