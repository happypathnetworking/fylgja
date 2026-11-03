"""The local driver's CLI runner (D-018, D-043): a command as a subprocess, its stdout
answered, a failure or a hang raised with the command named, every command line logged and
no stdout."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path

import pytest

from fylgja_core.containerlab import cli
from fylgja_core.containerlab.cli import CommandFailed


def test_run_answers_the_commands_stdout() -> None:
    assert asyncio.run(cli.run(["sh", "-c", "echo hi"], timeout_s=5)) == "hi\n"


def test_a_failing_command_raises_with_its_status_and_stderr_and_never_its_stdout() -> None:
    with pytest.raises(CommandFailed) as raised:
        asyncio.run(cli.run(["sh", "-c", "echo printed; echo complaint >&2; exit 3"], timeout_s=5))
    e = raised.value
    assert e.argv == ("sh", "-c", "echo printed; echo complaint >&2; exit 3")
    assert e.returncode == 3
    assert e.stderr == "complaint\n"
    assert str(e) == "sh -c 'echo printed; echo complaint >&2; exit 3' exited with status 3"


def test_a_hanging_command_is_killed_at_its_budget() -> None:
    start = time.monotonic()
    with pytest.raises(CommandFailed) as raised:
        asyncio.run(cli.run(["sleep", "5"], timeout_s=0.2))
    assert time.monotonic() - start < 1.0
    assert raised.value.returncode == -1
    assert raised.value.stderr == "timed out after 0.2 s"
    assert str(raised.value) == "sleep 5 timed out after 0.2 s"


def test_a_cancelled_run_kills_its_command(tmp_path: Path) -> None:
    pidfile = tmp_path / "pid"

    async def scenario() -> None:
        task = asyncio.create_task(cli.run(["sh", "-c", f"echo $$ > {pidfile}; exec sleep 5"], timeout_s=10))
        while not pidfile.exists() or not pidfile.read_text().strip():
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    with pytest.raises(ProcessLookupError):
        os.kill(int(pidfile.read_text()), 0)


def test_run_takes_the_environment_and_the_directory(tmp_path: Path) -> None:
    assert asyncio.run(cli.run(["sh", "-c", "echo $FYLGJA_TEST"], timeout_s=5, env={"FYLGJA_TEST": "x"})) == "x\n"
    assert Path(asyncio.run(cli.run(["pwd"], timeout_s=5, cwd=tmp_path)).strip()) == tmp_path.resolve()


def test_run_json_parses_the_stdout() -> None:
    assert asyncio.run(cli.run_json(["sh", "-c", "echo '{\"a\": [1, null]}'"], timeout_s=5)) == {"a": [1, None]}


def test_every_command_line_is_logged_and_no_stdout(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO", logger="fylgja.containerlab")
    assert asyncio.run(cli.run(["sh", "-c", "echo ${0}put", "out"], timeout_s=5)) == "output\n"
    assert [(r.name, r.levelname, r.getMessage()) for r in caplog.records] == [
        ("fylgja.containerlab", "INFO", "sh -c 'echo ${0}put' out")]
    assert "output" not in caplog.text
