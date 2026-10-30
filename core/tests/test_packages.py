"""Every shipped package and every fixture declaration is its format's (formats/)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from fylgja_core import schemas

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
