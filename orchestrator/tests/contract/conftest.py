"""Tier 2: every test here is marked `contract` and reads a real Infrahub, the one the Go
contract tier reads (research R-15). Without INFRAHUB_ADDRESS and INFRAHUB_API_TOKEN each
skips, saying why, so `pytest -m contract` on a host with no Infrahub reports skips, never
failures."""

import os

import pytest

ENV = ("INFRAHUB_ADDRESS", "INFRAHUB_API_TOKEN")


@pytest.fixture(autouse=True)
def _infrahub_required():
    missing = [name for name in ENV if not os.environ.get(name)]
    if missing:
        pytest.skip(f"tier 2 needs {' and '.join(missing)} (load local/.env)")


@pytest.fixture
def infrahub_address():
    return os.environ["INFRAHUB_ADDRESS"].rstrip("/")
