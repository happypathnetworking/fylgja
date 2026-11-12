"""The command `fylgja-infrahub` against the development Infrahub, run as an integrator runs it: a process of its own,
the console script beside the interpreter running the tier, given the reader's three variables and nothing of the
writer's (CONTRIBUTING.md, Test tiers; readers/infrahub/README.md, "The command"). `read` of the seed's first stage
writes the library's blueprint; `schema-check` of `main` holds; `head` prints a time; and a `read` of a scope no device
carries is refused. Each assertion compares plain values, the command's output among them scrubbed of the address and
the tokens first (conftest, `scrubbed`), so that a failing one shows nothing raw."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from fylgja_core import blueprint

from fylgja_infrahub import Infrahub, ReaderDocument, read, schema, times

from .conftest import ADDRESS, CA, READER_DOCUMENT, TOKEN, scrubbed

COMMAND = Path(sys.executable).with_name("fylgja-infrahub")
"""The console script `make venv` installs beside the interpreter."""

NONE = "tag:fylgja-contract-none"
"""A scope no device carries: no tag of the seed's."""

TIMEOUT_S = 300.0
"""How long one run of the command is given."""


def run(*args: str) -> subprocess.CompletedProcess[str]:
    """The command run with `args`, its environment the reader's three variables, where set, and `PATH` alone."""
    env = {name: os.environ[name] for name in ("PATH", ADDRESS, TOKEN, CA) if os.environ.get(name)}
    return subprocess.run([str(COMMAND), *args], capture_output=True, text=True, env=env, timeout=TIMEOUT_S)


def said(done: subprocess.CompletedProcess[str]) -> str:
    """What a run printed, scrubbed, for an assertion's message."""
    return scrubbed(f"exit {done.returncode}; stdout: {done.stdout!r}; stderr: {done.stderr!r}")


def test_read_writes_the_librarys_blueprint(
    conn: Infrahub, seed: dict[str, Any], document: ReaderDocument, tmp_path: Path
) -> None:
    """`read` of the seeded branch at its first stage's time exits 0 and writes the blueprint the library reads there,
    by id, which it prints first."""
    at, out = seed["stages"][0]["at"], tmp_path / "blueprint.json"
    args = ("--branch", seed["branch"], "--scope", seed["scope"], "--reader", str(READER_DOCUMENT), "--at", at)
    done = run("read", *args, "--out", str(out))
    assert done.returncode == 0, said(done)
    library = read(conn, branch=seed["branch"], at=at, scope=seed["scope"], document=document)
    assert library.blueprint is not None
    written = blueprint.blueprint_id(json.loads(out.read_text()))
    assert (written, scrubbed(done.stdout).split()[0]) == (blueprint.blueprint_id(library.blueprint),) * 2


def test_schema_check_of_main_holds() -> None:
    done = run("schema-check", "--branch", "main")
    assert (done.returncode, scrubbed(done.stdout)) == (0, f"ok: {schema.MODEL}@{schema.COMMIT}\n"), said(done)


def test_head_prints_a_time(seed: dict[str, Any]) -> None:
    done = run("head", "--branch", seed["branch"], "--scope", seed["scope"])
    assert done.returncode == 0, said(done)
    times.parse(scrubbed(done.stdout).strip())


def test_a_read_of_a_scope_no_device_carries_exits_1(seed: dict[str, Any], tmp_path: Path) -> None:
    """Refused with `scope.empty`, one line on stderr, and `--out` not written."""
    out = tmp_path / "blueprint.json"
    args = ("--branch", "main", "--scope", NONE, "--reader", str(READER_DOCUMENT), "--at", seed["stages"][0]["at"])
    done = run("read", *args, "--out", str(out))
    assert (done.returncode, scrubbed(done.stdout), out.exists()) == (1, "", False), said(done)
    lines = [line.split()[:3] for line in scrubbed(done.stderr).splitlines()]
    assert lines == [["error", "scope.empty", NONE + ":"]], said(done)
