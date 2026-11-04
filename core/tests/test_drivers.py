"""The driver registry: the one place above the seam that names a runtime (Constitution XIII)."""

from __future__ import annotations

from pathlib import Path

import pytest

from fylgja_core import containerlab, drivers
from fylgja_core.containerlab.driver import ContainerlabDriver


def test_the_registry_makes_the_local_driver_rooted_where_it_is_told(tmp_path: Path) -> None:
    driver = drivers.make("containerlab", tmp_path)
    assert driver.name == "containerlab"
    assert isinstance(driver, ContainerlabDriver) and driver.root == tmp_path


def test_an_unknown_driver_is_a_key_error_naming_the_ones_served(tmp_path: Path) -> None:
    with pytest.raises(KeyError, match="no driver 'kubevirt'; this core serves containerlab"):
        drivers.make("kubevirt", tmp_path)
    with pytest.raises(KeyError, match="no driver 'kubevirt'"):
        drivers.capabilities("kubevirt")


def test_the_names_are_sorted_and_each_has_its_capabilities() -> None:
    assert drivers.NAMES == ("containerlab",)
    assert list(drivers.NAMES) == sorted(drivers.NAMES)
    assert drivers.capabilities("containerlab") == containerlab.CAPABILITIES
