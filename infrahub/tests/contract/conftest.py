"""The contract tier: `infrahub/`'s code against the running development Infrahub (CONTRIBUTING.md, Test tiers).

Every test under tests/contract is marked `contract`: `make test` deselects them and `make contract` runs them, with
`local/.env` loaded and `FYLGJA_INFRAHUB_CTL` and `FYLGJA_INFRAHUB_SEED` set on its command line. The variables are
read inside the fixtures, never at import, since the pure tier collects this file too. Without them a test is
skipped, and fails where `CI` is set. No value of them is printed.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from hub import Hub, connect

_HERE = Path(__file__).resolve().parent


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every test under tests/contract `contract`, before `-m` selects."""
    for item in items:
        if item.path.is_relative_to(_HERE):
            item.add_marker(pytest.mark.contract)


def need(*names: str) -> None:
    """Skip, or fail where `CI` is set, naming each of `names` that is not set."""
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        sentence = f"the contract tier needs {', '.join(missing)} set: load local/.env and run make contract"
        if os.environ.get("CI"):
            pytest.fail(sentence)
        pytest.skip(sentence)


@pytest.fixture(scope="session")
def hub() -> Iterator[Hub]:
    """The writer's `Hub`, as `make infrahub-register` makes it."""
    need("FYLGJA_INFRAHUB_ADDRESS", "FYLGJA_INFRAHUB_WRITE_TOKEN", "FYLGJA_INFRAHUB_CTL")
    made = connect(os.environ, ctl=Path(os.environ["FYLGJA_INFRAHUB_CTL"]))
    try:
        yield made
    finally:
        made.close()
