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
from fylgja_core.containerlab.cli import TIMED_OUT, CommandFailed
from fylgja_core.driver import DriverFailed


def test_run_answers_the_commands_stdout() -> None:
    assert asyncio.run(cli.run(["sh", "-c", "echo hi"], timeout_s=5)) == "hi\n"


def test_a_failing_command_raises_with_its_status_and_stderr_and_never_its_stdout() -> None:
    with pytest.raises(CommandFailed) as raised:
        asyncio.run(cli.run(["sh", "-c", "echo printed; echo complaint >&2; exit 3"], timeout_s=5))
    e = raised.value
    assert isinstance(e, DriverFailed)  # the seam's runtime-neutral failure: the loop names no runtime to catch it
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


def gone_within(pid: int, seconds: float) -> bool:
    """Whether `pid` exits within `seconds`; a zombie has exited, its reaping its new parent's."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            stat = Path(f"/proc/{pid}/stat").read_text()
        except FileNotFoundError:
            return True
        if stat.rpartition(")")[2].split()[0] == "Z":
            return True
        time.sleep(0.02)
    return False


def test_a_hanging_commands_children_are_killed_with_it(tmp_path: Path) -> None:
    # A wrapper's child holds the pipes: killing the wrapper alone would leave the call
    # waiting on them, and the child running past the budget.
    pidfile = tmp_path / "pid"
    budget = 1.0  # room for a loaded runner to start the child before the budget runs out

    async def scenario() -> tuple[CommandFailed, float]:
        start = time.monotonic()
        task = asyncio.create_task(cli.run(["sh", "-c", f"sleep 5 & echo $! > {pidfile}; wait"], timeout_s=budget))
        while not task.done() and not (pidfile.exists() and pidfile.read_text().strip()):
            await asyncio.sleep(0.01)
        with pytest.raises(CommandFailed) as raised:
            await task
        return raised.value, time.monotonic() - start

    failed, elapsed = asyncio.run(scenario())
    assert elapsed < budget + 1.0
    assert failed.returncode == TIMED_OUT
    assert pidfile.read_text().strip(), "the child never started"
    assert gone_within(int(pidfile.read_text()), 1.0)


def test_a_cancelled_runs_children_are_killed_with_it(tmp_path: Path) -> None:
    pidfile = tmp_path / "pid"

    async def scenario() -> None:
        task = asyncio.create_task(cli.run(["sh", "-c", f"sleep 5 & echo $! > {pidfile}; wait"], timeout_s=10))
        while not pidfile.exists() or not pidfile.read_text().strip():
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1.0)

    asyncio.run(scenario())
    assert gone_within(int(pidfile.read_text()), 1.0)


def test_a_failures_stderr_is_bounded_to_its_last_4_kib() -> None:
    with pytest.raises(CommandFailed) as raised:
        asyncio.run(cli.run(["sh", "-c", "head -c 10000 /dev/zero | tr '\\0' x >&2; printf end >&2; exit 1"],
                            timeout_s=5))
    assert len(raised.value.stderr) == 4096
    assert raised.value.stderr.endswith("xxend")


def test_output_that_is_not_utf8_is_decoded_with_replacements() -> None:
    assert asyncio.run(cli.run(["sh", "-c", "printf 'a\\377b'"], timeout_s=5)) == "a\ufffdb"
    with pytest.raises(CommandFailed) as raised:
        asyncio.run(cli.run(["sh", "-c", "printf 'a\\377b' >&2; exit 1"], timeout_s=5))
    assert raised.value.stderr == "a\ufffdb"


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


def test_run_status_answers_a_non_zero_status_as_data() -> None:
    answer = asyncio.run(cli.run_status(["sh", "-c", "echo out; echo err >&2; exit 3"], timeout_s=5))
    assert answer == (3, "out\n", "err\n")


def test_run_status_still_raises_for_a_budget_run_out() -> None:
    with pytest.raises(CommandFailed) as raised:
        asyncio.run(cli.run_status(["sleep", "30"], timeout_s=0.2))
    assert raised.value.returncode == TIMED_OUT


# A deploy's output goes to a file (D-056): the core holds no pipe whose closing ends the command.


def test_run_with_a_log_file_writes_both_outputs_to_it_in_order_and_answers_nothing(tmp_path: Path) -> None:
    log = tmp_path / "deploy.log"
    out = asyncio.run(cli.run(["sh", "-c", "echo out; echo err >&2; echo more"], timeout_s=5, log=log))
    assert out == ""
    assert log.read_text() == "out\nerr\nmore\n"


def test_a_failure_with_a_log_file_raises_with_the_files_tail(tmp_path: Path) -> None:
    log = tmp_path / "deploy.log"
    with pytest.raises(CommandFailed) as raised:
        asyncio.run(cli.run(["sh", "-c", "echo printed; echo complaint >&2; exit 3"], timeout_s=5, log=log))
    assert raised.value.returncode == 3
    assert raised.value.stderr == "printed\ncomplaint\n"
    assert str(raised.value) == "sh -c 'echo printed; echo complaint >&2; exit 3' exited with status 3"


def test_a_log_file_holds_the_last_run_alone(tmp_path: Path) -> None:
    log = tmp_path / "deploy.log"
    asyncio.run(cli.run(["sh", "-c", "echo first"], timeout_s=5, log=log))
    asyncio.run(cli.run(["sh", "-c", "echo second"], timeout_s=5, log=log))
    assert log.read_text() == "second\n"


def test_a_budget_run_out_with_a_log_file_is_reported_as_before(tmp_path: Path) -> None:
    log = tmp_path / "deploy.log"
    with pytest.raises(CommandFailed) as raised:
        asyncio.run(cli.run(["sh", "-c", "echo begun; sleep 5"], timeout_s=0.2, log=log))
    assert raised.value.returncode == TIMED_OUT
    assert raised.value.stderr == "timed out after 0.2 s"
    assert log.read_text() == "begun\n"


def test_a_log_file_that_cannot_be_opened_fails_before_the_command_runs(tmp_path: Path) -> None:
    pidfile = tmp_path / "ran"
    log = tmp_path / "missing" / "deploy.log"
    with pytest.raises(DriverFailed) as raised:
        asyncio.run(cli.run(["sh", "-c", f"touch {pidfile}"], timeout_s=5, log=log))
    assert not isinstance(raised.value, CommandFailed)
    assert str(log) in str(raised.value)
    assert not pidfile.exists()


def test_the_core_holds_no_descriptor_of_the_log_file_while_the_command_runs(tmp_path: Path) -> None:
    log = tmp_path / "deploy.log"

    def held() -> list[str]:
        fds = Path("/proc/self/fd")
        return [str(f) for f in fds.iterdir() if os.path.realpath(fds / f) == str(log)]

    async def body() -> None:
        task = asyncio.create_task(cli.run(["sh", "-c", "echo begun; sleep 0.5; echo done"], timeout_s=5, log=log))
        await asyncio.sleep(0.2)
        assert log.read_text() == "begun\n"
        assert held() == []  # the child writes on; nothing of the core's ends it once the core is gone
        await task

    asyncio.run(body())
    assert log.read_text() == "begun\ndone\n"
