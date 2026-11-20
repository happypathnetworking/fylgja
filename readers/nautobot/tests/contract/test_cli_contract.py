"""The command `fylgja-nautobot` against the development Nautobot (cli.py; README.md, "The command"): `read` with the
seed's reader document writes the blueprint the library reads, `check` passes, and a `read` of a scope no device carries
is refused, writing nothing. The command is the installed console script, run as a process with the reader's variables
and never the write token; neither of its streams holds a token. No assertion message prints the address or a token."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from fylgja_core import blueprint

from fylgja_nautobot import Nautobot, ReaderDocument, read
from fylgja_nautobot.transport import TOKEN, redact

from .conftest import READER_DOCUMENT, WRITE_TOKEN, scrubbed

COMMAND = Path(sys.executable).parent / "fylgja-nautobot"
"""The console script `make venv` installs beside the interpreter the tier runs on."""

SCOPE = "tag:fylgja"
MISSING = "fylgja-contract-none"
"""A tag Nautobot lacks: no tag of the tier's own, which are named by 8 hex digits."""


def run(*args: str) -> subprocess.CompletedProcess[str]:
    """The command run with `args`, in an environment holding the reader's variables and not the write token. A test
    asserts on its status as a plain value, never on the process, whose repr holds both streams unscrubbed."""
    env = {name: value for name, value in os.environ.items() if name != WRITE_TOKEN}
    return subprocess.run([str(COMMAND), *args], env=env, capture_output=True, text=True, check=False)


def tokened(done: subprocess.CompletedProcess[str]) -> list[str]:
    """The names of the tokens either stream of `done` holds, whole or a half of one, as the transport hides them
    (transport.redact)."""
    streams = done.stdout + done.stderr
    held = {name: os.environ.get(name, "") for name in (TOKEN, WRITE_TOKEN)}
    return [name for name, token in held.items() if token and redact(streams, token) != streams]


def test_read_writes_the_blueprint_the_library_reads(conn: Nautobot, document: ReaderDocument, tmp_path: Path) -> None:
    out = tmp_path / "blueprint.json"
    done = run("read", "--scope", SCOPE, "--reader", str(READER_DOCUMENT), "--out", str(out))
    assert tokened(done) == []
    status = done.returncode
    assert status == 0, scrubbed(done.stderr)
    written = json.loads(out.read_text())
    library = read(conn, scope=SCOPE, document=document).blueprint
    assert library is not None
    assert blueprint.blueprint_id(written) == blueprint.blueprint_id(library)
    assert done.stdout.split()[0] == blueprint.blueprint_id(library)


def test_check_passes() -> None:
    passed = run("check")
    assert tokened(passed) == []
    status = passed.returncode
    assert status == 0, scrubbed(passed.stderr)
    assert passed.stdout.startswith("ok: Nautobot ")


def test_a_read_of_a_scope_no_device_carries_writes_nothing(tmp_path: Path) -> None:
    out = tmp_path / "blueprint.json"
    done = run("read", "--scope", f"tag:{MISSING}", "--reader", str(READER_DOCUMENT), "--out", str(out))
    assert tokened(done) == []
    status = done.returncode
    assert status == 1, scrubbed(done.stderr)
    assert f"error scope.empty tag:{MISSING}:" in done.stderr
    assert not out.exists()
