"""The rehearsal library's fixture: the core's own server on its fake runtime (`harness.serving`).

And Prefect kept to the tests' own: before any test imports the edge's flows, and Prefect with them, its home is a
temporary directory of the session's, removed when the session ends, and it sends nothing about itself anywhere.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from harness import Served, serving

# Prefect's variables are set here, at the conftest's import, before anything imports Prefect: pytest imports this
# file before any test module, and `harness`, imported above, imports none of Prefect.
_PREFECT_HOME = tempfile.TemporaryDirectory(prefix="fylgja-prefect-home-")
os.environ["PREFECT_HOME"] = _PREFECT_HOME.name
os.environ["DO_NOT_TRACK"] = "1"
os.environ["PREFECT_SERVER_ANALYTICS_ENABLED"] = "false"


def pytest_sessionfinish() -> None:
    """The session's Prefect home removed, whatever was put in it."""
    _PREFECT_HOME.cleanup()


@pytest.fixture
def served(tmp_path: Path) -> Iterator[Served]:
    """API 1 served on the fake runtime under `tmp_path`, and its two clients, until the test ends."""
    with serving(tmp_path) as core:
        yield core
