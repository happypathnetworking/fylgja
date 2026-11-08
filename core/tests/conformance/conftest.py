"""The conformance suite (design/core.md, phase 6): one set of scenarios, run on the harness of
the driver `FYLGJA_CONFORMANCE_DRIVER` names (`make conformance DRIVER=…` sets it; the local
driver's by default).

Every test of the directory is marked with that harness's marker, `live` or `cluster`, before
`-m` selects, so `make test` deselects the suite and the pure tier's guard passes it by; it is
skipped without the node logins, which every harness reads. The session's `harness` is made and
started once, and closed at the end with every twin of the suite (`reads.TWINS`); a harness the
environment cannot make ends the session in one line naming what it lacks; `fylgja` is
the CLI in-process against it; `caps` is the capabilities of the driver the core lists as its
default, its name dropped, since a scenario branches on what a driver can do and never on which
it is.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from conformance.harness import DEFAULT_DRIVER, DRIVER_VARIABLE, MARKERS, Fylgja, Harness, make
from conformance.reads import TWINS

_HERE = Path(__file__).resolve().parent
LOGINS = "FYLGJA_CREDENTIAL_SRLINUX_USERNAME"


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark each test of the suite with its harness's marker, before `-m` selects, and skip it
    without the node logins. The hook is given the session's items: only the suite's are touched."""
    mine = [item for item in items if item.path.is_relative_to(_HERE)]
    if not mine:
        return
    driver = os.environ.get(DRIVER_VARIABLE, DEFAULT_DRIVER)
    if driver not in MARKERS:
        raise pytest.UsageError(f"{DRIVER_VARIABLE} names no harness: the drivers are {' and '.join(MARKERS)}")
    marker = getattr(pytest.mark, MARKERS[driver])
    skip = None if os.environ.get(LOGINS) else pytest.mark.skip(
        reason="the conformance suite reads the node logins from the environment: load local/.env first "
        "(set -a; . local/.env; set +a)")
    for item in mine:
        item.add_marker(marker)
        if skip is not None:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def harness(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Harness]:
    """The session's harness. One the environment cannot make (a variable it reads unset), or whose
    start refuses what it finds (`pytest.UsageError`), ends the session in one line naming why,
    where a fixture's error is reported once a test."""
    try:
        made = make(os.environ.get(DRIVER_VARIABLE, DEFAULT_DRIVER), tmp_path_factory)
    except pytest.UsageError as e:
        pytest.exit(str(e), returncode=pytest.ExitCode.USAGE_ERROR)
    try:
        try:
            made.start()
        except pytest.UsageError as e:
            pytest.exit(str(e), returncode=pytest.ExitCode.USAGE_ERROR)
        yield made
    finally:
        made.close(TWINS)


@pytest.fixture
def fylgja(harness: Harness, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> Fylgja:
    return harness.cli(monkeypatch, capsys)


@pytest.fixture(scope="session")
def caps(harness: Harness) -> dict[str, Any]:
    answer = harness.client().get("/v1/drivers")
    assert answer.status_code == 200, answer.text
    (default,) = [d for d in answer.json()["drivers"] if d["default"]]
    capabilities: dict[str, Any] = default["capabilities"]
    print(f"\n[conformance] the default driver's capabilities: {capabilities}", flush=True)
    return capabilities
