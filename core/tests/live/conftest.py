"""The live tier: booted images on the local containerlab driver (CONTRIBUTING.md, Test tiers).

Every test under tests/live is marked `live`: `make test` deselects them and `make live` runs
them. Each module boots and destroys its own labs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every test under tests/live `live`, before `-m` selects."""
    for item in items:
        if item.path.is_relative_to(_HERE):
            item.add_marker(pytest.mark.live)
