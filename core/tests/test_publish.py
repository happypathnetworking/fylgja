"""The publish check (D-106): `scripts/publish.py` holds the tag, `VERSION`, the changelog's head and `dist/`'s three
wheels to one another before anything is uploaded, naming every fault in one pass, and performs no upload itself. The
script is loaded by path, as `test_wheelcheck.py` loads its own; the wheels are zip files made under `tmp_path` holding
a `METADATA` and a `COMMIT`."""

from __future__ import annotations

import importlib.util
import zipfile
from functools import cache
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "publish.py"
COMMIT = "a" * 40
OTHER = "b" * 40
PACKAGES = {"fylgja_core": "fylgja-core", "fylgja_infrahub": "fylgja-infrahub", "fylgja_netbox": "fylgja-netbox"}


@cache
def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("script_publish", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def wheel(dist: Path, package: str, version: str, *, meta_version: str | None = None, floor: str | None = None,
          commit: str = COMMIT) -> None:
    """One wheel in `dist`: its file name at `version`, its METADATA at `meta_version` (default `version`)."""
    dist.mkdir(exist_ok=True)
    stem = f"{package}-{version}"
    meta = f"Metadata-Version: 2.4\nName: {PACKAGES[package]}\nVersion: {meta_version or version}\n"
    if package != "fylgja_core":
        major = int(version.split(".")[0])
        meta += f"Requires-Dist: fylgja-core{floor or '>=' + version},<{major + 1}\n"
    with zipfile.ZipFile(dist / f"{stem}-py3-none-any.whl", "w") as z:
        z.writestr(f"{stem}.dist-info/METADATA", meta)
        z.writestr(f"{package}/COMMIT", commit + "\n")


def three(dist: Path, version: str = "1.0.0rc1") -> None:
    for package in PACKAGES:
        wheel(dist, package, version)


def tree(path: Path, version: str = "1.0.0rc1", head: str = "## 1.0.0rc1 - 2026-11-20") -> Path:
    path.mkdir(exist_ok=True)
    (path / "VERSION").write_text(version + "\n")
    (path / "CHANGELOG.md").write_text(f"# Changelog\n\nWhat it holds.\n\n{head}\n\nThe first release.\n\n"
                                       "## 0.9.0 - 2026-01-01\n\nEarlier.\n")
    return path


def test_the_index_is_told_by_the_versions_form() -> None:
    script = _script()
    assert script.index("1.0.0") == "pypi"
    assert script.index("1.0.0rc1") == "testpypi"
    for bad in ("1.0.0.dev0", "1.0", "1.0.0a1", "1.0.0+x", "01.0.0"):
        with pytest.raises(script.Failure):
            script.index(bad)


def test_a_tree_that_is_the_tag_passes(tmp_path: Path) -> None:
    root = tree(tmp_path / "root")
    three(tmp_path / "dist")
    assert _script().check("v1.0.0rc1", COMMIT, tmp_path / "dist", root) == "testpypi"


@pytest.mark.parametrize("tag", ["v1.0.0", "1.0.0rc1", "v1.0.0-rc1"])
def test_a_tag_that_is_not_the_version_is_refused(tmp_path: Path, tag: str) -> None:
    root = tree(tmp_path / "root")
    three(tmp_path / "dist")
    with pytest.raises(_script().Failure, match="tag"):
        _script().check(tag, COMMIT, tmp_path / "dist", root)


def test_every_fault_of_the_wheels_is_named_in_one_pass(tmp_path: Path) -> None:
    root = tree(tmp_path / "root")
    dist = tmp_path / "dist"
    wheel(dist, "fylgja_core", "1.0.0rc1", meta_version="1.0.0rc2", commit=OTHER)
    wheel(dist, "fylgja_infrahub", "1.0.0rc1", floor=">=1.0")
    wheel(dist, "fylgja_netbox", "1.0.0rc2")  # a name of another version, and the NetBox reader at VERSION missing
    # the example's wheel and an sdist are not allowed
    with zipfile.ZipFile(dist / "fylgja_orchestrator-1.0.0rc1-py3-none-any.whl", "w") as z:
        z.writestr("fylgja_orchestrator-1.0.0rc1.dist-info/METADATA", "Name: fylgja-orchestrator\nVersion: 1.0.0rc1\n")
    (dist / "fylgja_core-1.0.0rc1.tar.gz").write_bytes(b"")
    with pytest.raises(_script().Failure) as caught:
        _script().check("v1.0.0rc1", COMMIT, dist, root)
    text = str(caught.value)
    lines = text.splitlines()
    assert len(lines) == len(set(lines)) >= 6
    for fragment in ("fylgja_orchestrator-1.0.0rc1-py3-none-any.whl", "fylgja_core-1.0.0rc1.tar.gz",
                     "fylgja_netbox-1.0.0rc1-py3-none-any.whl: is missing", "fylgja_netbox-1.0.0rc2", "1.0.0rc2",
                     ">=1.0", OTHER):
        assert fragment in text, fragment
    # the other faults of a COMMIT: dirty and unknown
    for bad in (COMMIT + "-dirty", "unknown"):
        again = tmp_path / ("d" + bad[-5:])
        three(again)
        wheel(again, "fylgja_netbox", "1.0.0rc1", commit=bad)
        with pytest.raises(_script().Failure, match="fylgja_netbox"):
            _script().check("v1.0.0rc1", COMMIT, again, root)


def test_an_undated_or_other_head_is_refused(tmp_path: Path) -> None:
    three(tmp_path / "dist")
    for head, why in (("## 1.0.0rc1 - unreleased", "unreleased"), ("## 1.0.1 - 2026-11-20", "1.0.1"),
                      ("## 1.0.0rc1 2026-11-20", "heading")):
        root = tree(tmp_path / "r", head=head)
        with pytest.raises(_script().Failure) as caught:
            _script().check("v1.0.0rc1", COMMIT, tmp_path / "dist", root)
        assert str(caught.value).count("\n") == 0 and why in str(caught.value)


def test_the_notes_are_the_head_sections_body(tmp_path: Path) -> None:
    root = tree(tmp_path / "root")
    assert _script().notes(root) == "The first release.\n"


def test_the_index_is_written_for_the_workflow(tmp_path: Path, capsys: pytest.CaptureFixture[str],
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    root = tree(tmp_path / "root")
    three(tmp_path / "dist")
    out = tmp_path / "out"
    out.write_text("earlier=1\n")
    script = _script()
    monkeypatch.setattr(script, "ROOT", root)
    status = script.main(["check", "--tag", "v1.0.0rc1", "--commit", COMMIT, "--dist", str(tmp_path / "dist"),
                          "--output", str(out)])
    assert status == 0
    assert capsys.readouterr().out == "index=testpypi\n"
    assert out.read_text() == "earlier=1\nindex=testpypi\n"
