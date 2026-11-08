"""The local driver's CLI runner (D-018, D-043): a command as a subprocess, its stdout
answered, a failure or a hang raised with the command named, every command line logged and
no stdout; and a long-lived command followed a line at a time, killed when its reader is done
(D-058)."""

from __future__ import annotations

import asyncio
import os
import shutil
import time
from pathlib import Path
from typing import Any

import pytest
from aio import bounded, cancelled, closed

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
        await cancelled(task)

    bounded(scenario)
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
        await cancelled(task)

    bounded(scenario)
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
    assert asyncio.run(cli.run(["sh", "-c", "echo $GREETING"], timeout_s=5, env={"GREETING": "x"})) == "x\n"
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


def test_the_allow_list_names_two_variables_and_none_of_the_cores() -> None:
    assert cli.ALLOWED_ENV == ("DOCKER_HOST", "PATH")
    assert not any(name.startswith("FYLGJA_") for name in cli.ALLOWED_ENV)


def test_environment_keeps_the_allowed_names_that_are_set() -> None:
    assert cli.environment({"PATH": "/bin", "HOME": "/h", "FYLGJA_STORE": "/s", "LANG": "C"}) == {"PATH": "/bin"}
    assert cli.environment({}) == {}


def _set_the_servers_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {
        "DOCKER_HOST": "unix:///run/docker.example.sock", "HOME": "/home/example",
        "FYLGJA_CREDENTIAL_SRLINUX_PASSWORD": "never-passed-7c1e", "FYLGJA_TOKENS": "/t",
        "AWS_SECRET_ACCESS_KEY": "never-passed-7c1e", "CLAB_LABDIR_BASE": "/elsewhere",
    }.items():
        monkeypatch.setenv(name, value)


def _names(env_output: str) -> set[str]:
    return {line.split("=", 1)[0] for line in env_output.splitlines() if "=" in line}


def test_run_gives_a_command_the_allowed_names_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_the_servers_environment(monkeypatch)
    out = asyncio.run(cli.run(["env"], timeout_s=5))
    assert _names(out) == set(cli.ALLOWED_ENV)
    assert "never-passed-7c1e" not in out


def test_run_status_gives_a_command_the_allowed_names_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_the_servers_environment(monkeypatch)
    status, out, _ = asyncio.run(cli.run_status(["env"], timeout_s=5))
    assert status == 0
    assert _names(out) == set(cli.ALLOWED_ENV)
    assert "never-passed-7c1e" not in out


def test_a_command_given_a_log_file_gets_the_allowed_names_alone(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _set_the_servers_environment(monkeypatch)
    log = tmp_path / "deploy.log"
    assert asyncio.run(cli.run(["env"], timeout_s=5, log=log)) == ""
    assert _names(log.read_text()) == set(cli.ALLOWED_ENV)
    assert "never-passed-7c1e" not in log.read_text()


def test_a_server_with_none_of_the_allowed_names_still_runs_a_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "environ", {"FYLGJA_TOKENS": "/t"})
    assert asyncio.run(cli.run(["env"], timeout_s=5)) == ""


# A follow: a long-lived command's stdout, a line at a time, as the local driver reads `docker events` (D-058).


async def _followed(argv: list[str], **kw: Any) -> list[tuple[str, float]]:
    """Each line `follow` yields, with the time it came, until the follow ends."""
    return [(line, time.monotonic()) async for line in cli.follow(argv, **kw)]


def test_follow_yields_each_line_as_its_command_writes_it_and_ends_with_it() -> None:
    (a, a_at), (b, b_at) = asyncio.run(_followed(["sh", "-c", "echo a; sleep 0.5; echo b"]))
    assert (a, b) == ("a", "b")
    assert b_at - a_at >= 0.25  # `a` came before the command slept, not once it had ended


def test_a_follow_whose_command_fails_raises_its_status_and_stderr_after_its_lines() -> None:
    yielded: list[str] = []

    async def body() -> None:
        async for line in cli.follow(["sh", "-c", "echo a; echo no >&2; exit 3"]):
            yielded.append(line)

    with pytest.raises(CommandFailed) as raised:
        asyncio.run(body())
    assert yielded == ["a"]
    assert (raised.value.returncode, raised.value.stderr) == (3, "no\n")
    assert str(raised.value) == "sh -c 'echo a; echo no >&2; exit 3' exited with status 3"


def test_closing_a_follow_kills_its_command_and_its_commands_children() -> None:
    """Its whole group: a child left running would hold the command's stdout open, and the close would wait on it."""

    async def body() -> list[int]:
        lines = cli.follow(["sh", "-c", "sleep 60 & echo $$ $!; wait"])
        pids = [int(pid) for pid in (await anext(lines)).split()]
        await closed(lines)  # well under the child's sleep
        return pids

    shell, child = bounded(body)
    assert gone_within(shell, 1.0) and gone_within(child, 1.0)


def test_a_cancelled_follow_kills_its_command_and_the_cancel_goes_on(tmp_path: Path) -> None:
    pidfile = tmp_path / "pid"

    async def body() -> None:
        async def consume() -> None:
            async for _ in cli.follow(["sh", "-c", f"echo $$ > {pidfile}; echo begun; exec sleep 60"]):
                pass

        task = asyncio.create_task(consume())
        async with asyncio.timeout(5):
            while not pidfile.exists() or not pidfile.read_text().strip():
                if task.done():
                    await task  # what ended the follow first is the test's failure
                await asyncio.sleep(0.01)
        await cancelled(task)

    bounded(body)
    assert gone_within(int(pidfile.read_text()), 1.0)


def test_a_command_the_driver_runs_in_the_pure_tier_finds_the_guards_docker_and_containerlab() -> None:
    """tests/conftest.py's guard stands first on the `PATH` a command gets, so the host's binaries are never reached,
    and a test that ran one of its stubs fails at its teardown."""
    path = cli.environment(os.environ)["PATH"]
    for name in ("docker", "containerlab"):
        found = shutil.which(name, path=path)
        assert found is not None, name
        assert Path(found).read_bytes().startswith(b"#!/bin/sh\n# The pure tier's guard (tests/conftest.py)"), found


def test_follow_gives_its_command_the_allowed_names_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_the_servers_environment(monkeypatch)
    lines = [line for line, _ in asyncio.run(_followed(["env"]))]
    assert _names("\n".join(lines)) == set(cli.ALLOWED_ENV)
    assert not any("never-passed-7c1e" in line for line in lines)


def test_follow_logs_its_command_line_once_and_no_line_it_yields(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("DEBUG", logger="fylgja.containerlab")
    assert [line for line, _ in asyncio.run(_followed(["sh", "-c", "echo ${0}put", "out"]))] == ["output"]
    assert [(r.name, r.levelname, r.getMessage()) for r in caplog.records] == [
        ("fylgja.containerlab", "INFO", "sh -c 'echo ${0}put' out")]
    assert "output" not in caplog.text


@pytest.mark.parametrize(("make", "status"), [("absent", 127), ("not executable", 126)])
def test_a_follow_whose_command_cannot_start_raises_command_failed(tmp_path: Path, make: str, status: int) -> None:
    """A host without `docker` is the driver's to retry, as a failed command is, and not a traceback (pre-flight
    ruling 5). The status is a shell's for a command it cannot find, or cannot run."""
    if make == "not executable":
        (tmp_path / "docker").write_text("#!/bin/sh\n")
    with pytest.raises(CommandFailed) as raised:
        asyncio.run(_followed(["docker", "events"], env={"PATH": str(tmp_path)}))
    assert raised.value.returncode == status
    assert str(raised.value) == f"docker events exited with status {status}"
