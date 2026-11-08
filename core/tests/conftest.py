"""The pure tier's guard: no test reaches the host's `docker` or `containerlab` (Constitution, Development).

Every test not marked `live` or `cluster` runs with a directory first on `PATH` holding a stub of each, which records
its call and exits non-zero, and the test fails at its teardown if either ran. `cli.environment` passes `PATH` to every
command the local driver runs, so the stubs stand wherever the host's binaries would be found. A test that puts its own
stub in front of them, as `test_server_main.py`'s `docker`, is the one exception.

It is a tripwire, not a sandbox: a command run with an environment that has no `PATH`, a binary named by its absolute
path, and a session- or module-scoped fixture set up before this function-scoped patch all reach the host unseen.

Every test, of every tier, also runs with `FYLGJA_API_CA` unset: the CLI reads it whenever it is set, so a value from
the shell's environment, which no test of `core/` can read, would fail each test that runs the CLI in process. A test
that needs it sets it.
"""

from __future__ import annotations

import os
import shlex
from collections.abc import Iterator
from pathlib import Path

import pytest

GUARDED = ("docker", "containerlab")
"""The host's runtimes, which only the live and cluster tiers reach."""

STUB = """#!/bin/sh
# The pure tier's guard (tests/conftest.py): the host's {name} is never reached. The call is recorded, and fails.
printf '%s\\n' "{name} $*" >> {calls}
exit 97
"""


@pytest.fixture(scope="session")
def _guard(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """The stubs' directory, and the file each records its call in."""
    root = tmp_path_factory.mktemp("guard")
    stubs, calls = root / "bin", root / "calls"
    stubs.mkdir()
    for name in GUARDED:
        stub = stubs / name
        stub.write_text(STUB.format(name=name, calls=shlex.quote(str(calls))))
        stub.chmod(0o755)
    return stubs, calls


@pytest.fixture(autouse=True)
def _never_the_hosts_runtime(
    request: pytest.FixtureRequest, _guard: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    if request.node.get_closest_marker("live") or request.node.get_closest_marker("cluster"):
        yield
        return
    stubs, calls = _guard
    before = calls.read_text() if calls.exists() else ""
    monkeypatch.setenv("PATH", f"{stubs}{os.pathsep}{os.environ.get('PATH', os.defpath)}")
    yield
    reached = (calls.read_text() if calls.exists() else "")[len(before):]
    if reached:
        pytest.fail(f"the pure tier ran the host's runtime: {reached.strip()}", pytrace=False)


@pytest.fixture(autouse=True)
def _no_api_ca_from_the_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FYLGJA_API_CA", raising=False)
