"""Every shipped package and every fixture declaration is its format's (formats/)."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from fylgja_core import packages, schemas

ROOT = Path(__file__).resolve().parents[2]
PLATFORMS = [*sorted((ROOT / "psp").glob("*.yaml")), ROOT / "testdata" / "packages" / "chassisos.yaml"]
PROBE_PACKAGES = sorted((ROOT / "probes").glob("*.yaml"))
DECLARATIONS = sorted((ROOT / "testdata" / "probes").glob("*.json"))
# Invalid declarations whose fault is a cross-field rule or a package lookup, which the
# schema cannot state: the core holds them, so the schema alone passes them.
BEYOND_SCHEMA = {"probe.address.duplicate.json", "probe.gateway.outside.json", "probe.name.duplicate.json",
                 "probe.format.unknown.json"}


def errors(name: str, doc: Any) -> list[str]:
    return [e.message for e in schemas.validator(name).iter_errors(doc)]


@pytest.mark.parametrize("path", PLATFORMS, ids=lambda p: p.name)
def test_each_platform_package_is_platform_package_1(path: Path) -> None:
    assert errors("platform-package-1", yaml.safe_load(path.read_text())) == []


@pytest.mark.parametrize("path", PROBE_PACKAGES, ids=lambda p: p.name)
def test_each_probe_package_is_probe_package_1(path: Path) -> None:
    assert errors("probe-package-1", yaml.safe_load(path.read_text())) == []


@pytest.mark.parametrize("path", DECLARATIONS, ids=lambda p: p.name)
def test_each_probe_declaration_is_probes_1(path: Path) -> None:
    assert errors("probes-1", json.loads(path.read_text())) == []


INVALID = sorted((ROOT / "testdata" / "probes" / "invalid").glob("*.json"))


@pytest.mark.parametrize("path", INVALID, ids=lambda p: p.name)
def test_each_invalid_declaration_fails_its_schema_unless_its_fault_is_beyond_it(path: Path) -> None:
    found = errors("probes-1", json.loads(path.read_text()))
    assert (found == []) == (path.name in BEYOND_SCHEMA), found


def test_the_shipped_packages_of_a_checkout_are_the_trees() -> None:
    assert packages.shipped() == (ROOT / "psp", ROOT / "probes")


def test_the_shipped_packages_of_an_install_are_beside_the_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "site" / "shipped_pkg"
    for directory in (package, package / "shipped" / "psp", package / "shipped" / "probes"):
        directory.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text("")
    monkeypatch.syspath_prepend(str(tmp_path / "site"))
    importlib.invalidate_caches()
    assert packages.shipped("shipped_pkg") == (package / "shipped" / "psp", package / "shipped" / "probes")


def test_an_install_with_neither_has_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = tmp_path / "site" / "bare_pkg"
    (package / "shipped" / "psp").mkdir(parents=True)  # one of the two is not a package pair
    (package / "__init__.py").write_text("")
    monkeypatch.syspath_prepend(str(tmp_path / "site"))
    importlib.invalidate_caches()
    with pytest.raises(FileNotFoundError):
        packages.shipped("bare_pkg")
    with pytest.raises(ModuleNotFoundError):
        packages.shipped("no_such_package_anywhere")
