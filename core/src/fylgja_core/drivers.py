"""The driver registry: the drivers this core serves, by name (Constitution XIII, D-017, D-046).

This is the one module above the seam that names a runtime, and it is the registry, not a
branch: the server lists `NAMES` (GET /v1/drivers) and makes the driver `FYLGJA_DRIVER` names
through `make`, and everything else reaches a runtime through the seam alone, branching at
most on a declared capability. A driver is added here and nowhere else above the seam.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from fylgja_core import containerlab
from fylgja_core.containerlab.driver import ContainerlabDriver
from fylgja_core.driver import Capabilities, Driver

NAMES: tuple[str, ...] = (containerlab.NAME,)
"""Every driver this core serves, sorted."""

_MAKERS: Mapping[str, Callable[[Path], Driver]] = {containerlab.NAME: ContainerlabDriver}
_CAPABILITIES: Mapping[str, Capabilities] = {containerlab.NAME: containerlab.CAPABILITIES}


def make(name: str, root: Path) -> Driver:
    """The driver `name`, its working files under `root` (the store's directory); `KeyError`
    for a name this core does not serve."""
    return _MAKERS[_served(name)](root)


def capabilities(name: str) -> Capabilities:
    """What the driver `name` declares of its runtime, without making it; `KeyError` as `make`."""
    return _CAPABILITIES[_served(name)]


def _served(name: str) -> str:
    if name not in NAMES:
        raise KeyError(f"no driver {name!r}; this core serves {', '.join(NAMES)}")
    return name
