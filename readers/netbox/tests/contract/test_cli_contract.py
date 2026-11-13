"""The command `fylgja-netbox` against the development NetBox (cli.py; README.md, "The command"): `read` of `main` with
the seed's reader document writes the blueprint the library reads, `check` passes on `main` and refuses a branch NetBox
lacks, a branch read twice by it gives the library's id both times, and a `read` of a scope no device carries is
refused, writing nothing. The command is the installed console script, run as a process with the reader's variables
and never the write token; neither of its streams holds a token. No assertion message prints the address or a
token."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from fylgja_core import blueprint

from fylgja_netbox import NetBox, ReaderDocument, read
from fylgja_netbox.rows import Branch
from fylgja_netbox.transport import TOKEN, redact

from .conftest import READER_DOCUMENT, WRITE_TOKEN, Writes, scrubbed

COMMAND = Path(sys.executable).parent / "fylgja-netbox"
"""The console script `make venv` installs beside the interpreter the tier runs on."""

SCOPE = "tag:fylgja"
MISSING = "fylgja-contract-none"


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


def test_read_writes_the_blueprint_the_library_reads(conn: NetBox, document: ReaderDocument, tmp_path: Path) -> None:
    out = tmp_path / "blueprint.json"
    done = run("read", "--scope", SCOPE, "--reader", str(READER_DOCUMENT), "--out", str(out))
    assert tokened(done) == []
    status = done.returncode
    assert status == 0, scrubbed(done.stderr)
    written = json.loads(out.read_text())
    library = read(conn, branch=None, scope=SCOPE, document=document).blueprint
    assert library is not None
    assert blueprint.blueprint_id(written) == blueprint.blueprint_id(library)
    assert done.stdout.split()[0] == blueprint.blueprint_id(library)


def test_a_branch_read_twice_through_the_command_is_one_id(
    conn: NetBox, box: Writes, branch: Branch, document: ReaderDocument, tmp_path: Path
) -> None:
    """A branch of the test's own holding the third cable of `testdata/blueprint/three-node.json`, read twice by the
    command: each file the blueprint the library reads of the branch, and not `main`'s."""
    ends = []
    for name in ("n1", "n3"):
        device = box.one("dcim/devices/", branch=branch.schema_id, name=name)
        assert device is not None, name
        port = box.one("dcim/interfaces/", branch=branch.schema_id, device_id=device["id"], name="ethernet-1/2")
        assert port is not None, name
        ends.append([{"object_type": "dcim.interface", "object_id": port["id"]}])
    box.post("dcim/cables/", {"a_terminations": ends[0], "b_terminations": ends[1]}, branch=branch.schema_id)

    ids = []
    for turn in (1, 2):
        out = tmp_path / f"branch-{turn}.json"
        asked = ("--branch", branch.name, "--scope", SCOPE, "--reader", str(READER_DOCUMENT), "--out", str(out))
        done = run("read", *asked)
        assert tokened(done) == []
        status = done.returncode
        assert status == 0, scrubbed(done.stderr)
        ids.append(blueprint.blueprint_id(json.loads(out.read_text())))
    on_branch = read(conn, branch=branch.name, scope=SCOPE, document=document).blueprint
    on_main = read(conn, branch=None, scope=SCOPE, document=document).blueprint
    assert on_branch is not None and on_main is not None
    assert ids == [blueprint.blueprint_id(on_branch)] * 2
    assert ids[0] != blueprint.blueprint_id(on_main)


def test_check_passes_on_main_and_refuses_a_branch_netbox_lacks() -> None:
    passed = run("check")
    assert tokened(passed) == []
    status = passed.returncode
    assert status == 0, scrubbed(passed.stderr)
    assert passed.stdout.startswith("ok: NetBox ")

    lacking = run("check", "--branch", MISSING)
    assert tokened(lacking) == []
    status = lacking.returncode
    assert status == 1, scrubbed(lacking.stderr)
    assert f"error branch.unknown {MISSING}:" in lacking.stderr


def test_a_read_of_a_scope_no_device_carries_writes_nothing(tmp_path: Path) -> None:
    out = tmp_path / "blueprint.json"
    done = run("read", "--scope", f"tag:{MISSING}", "--reader", str(READER_DOCUMENT), "--out", str(out))
    assert tokened(done) == []
    status = done.returncode
    assert status == 1, scrubbed(done.stderr)
    assert f"error scope.empty tag:{MISSING}:" in done.stderr
    assert not out.exists()
