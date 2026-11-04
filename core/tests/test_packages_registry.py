"""The packages the server loads at start: two of one id are refused, naming both files."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from fylgja_core import documents, packages

ROOT = Path(__file__).resolve().parents[2]


def test_the_shipped_packages_load() -> None:
    loaded = packages.load([ROOT / "psp", ROOT / "probes"])
    assert sorted(loaded.platforms) == ["arista_eos", "nokia_srlinux"]
    assert sorted(loaded.probes) == ["ping"]


def test_a_second_package_with_one_id_is_refused_naming_both_files(tmp_path: Path) -> None:
    shutil.copy(ROOT / "psp" / "nokia_srlinux.yaml", tmp_path / "copy.yaml")
    with pytest.raises(documents.Rejected) as e:
        packages.load([ROOT / "psp", tmp_path])
    assert [p.rule for p in e.value.problems] == ["package.id.duplicate"]
    assert str(tmp_path / "copy.yaml") in str(e.value)
    assert str(ROOT / "psp" / "nokia_srlinux.yaml") in str(e.value)


def test_a_second_probe_format_is_refused(tmp_path: Path) -> None:
    shutil.copy(ROOT / "probes" / "ping.yaml", tmp_path / "again.yaml")
    with pytest.raises(documents.Rejected) as e:
        packages.load([ROOT / "probes", tmp_path])
    assert [p.rule for p in e.value.problems] == ["package.id.duplicate"]


def test_a_file_that_is_no_package_is_refused_naming_it(tmp_path: Path) -> None:
    (tmp_path / "other.yaml").write_text("name: x\n")
    with pytest.raises(documents.Rejected) as e:
        packages.load([tmp_path])
    assert str(tmp_path / "other.yaml") in str(e.value)
