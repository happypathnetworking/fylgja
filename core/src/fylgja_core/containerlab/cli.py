"""The local driver's reach into its runtime: the `containerlab` and `docker` CLIs, each run
as a subprocess, never through an SDK (D-018, D-043).

Every command line is logged at INFO on `fylgja.containerlab` before it runs, so an operator
can repeat it by hand; no command's stdout is ever logged, since it can hold a node's
configuration. A command that fails or outruns its budget raises `CommandFailed`, and one
whose caller is cancelled is killed. Each command leads a process group of its own, which is
killed whole, so neither it nor a child it spawned outlives the call that ran it.

A command given a `log` file writes its stdout and stderr there instead of into pipes the
core holds, so that a core killed under it ends nothing: containerlab dies of SIGPIPE once a
pipe's reader is gone, at its next write by inference, and a deploy so orphaned must run to
completion (D-056). The core hands the open file to the child and closes its own copy at once.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shlex
import signal
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from fylgja_core.driver import DriverFailed

_log = logging.getLogger("fylgja.containerlab")

TIMED_OUT = -1
"""The status `run` reports for a command it killed at its budget."""

STDERR_KEPT = 4096
"""How many characters (decoded) of a failed command's stderr `CommandFailed` keeps: the last,
where a CLI writes its error."""


class CommandFailed(DriverFailed):
    """A command exited with a non-zero status, or ran past its budget (status `TIMED_OUT`,
    stderr saying so): the local driver's `DriverFailed`. `stderr` is the last `STDERR_KEPT`
    characters of the command's. Its message names the command and the status, never its output."""

    def __init__(self, argv: Sequence[str], returncode: int, stderr: str) -> None:
        self.argv = tuple(argv)
        self.returncode = returncode
        self.stderr = stderr
        status = stderr if returncode == TIMED_OUT else f"exited with status {returncode}"
        super().__init__(f"{shlex.join(self.argv)} {status}")


async def run(
    argv: Sequence[str], *, timeout_s: float, env: Mapping[str, str] | None = None, cwd: Path | None = None,
    log: Path | None = None,
) -> str:
    """The stdout of `argv` run to completion within `timeout_s` seconds, with `env` as its
    whole environment (the core's when None) and `cwd` as its directory; `CommandFailed` for a
    non-zero status, or when the budget runs out and the command is killed. With `log`, the
    command's stdout and stderr go to that file, truncated first, in the order written: the
    stdout answered is empty, and a failure's stderr is the file's last `STDERR_KEPT`
    characters. A `log` that cannot be opened is `DriverFailed` before the command runs."""
    returncode, stdout, stderr = await run_status(argv, timeout_s=timeout_s, env=env, cwd=cwd, log=log)
    if returncode:
        raise CommandFailed(argv, returncode, stderr[-STDERR_KEPT:])
    return stdout


async def run_status(
    argv: Sequence[str], *, timeout_s: float, env: Mapping[str, str] | None = None, cwd: Path | None = None,
    log: Path | None = None,
) -> tuple[int, str, str]:
    """As `run`, but the exit status, stdout and stderr are answered whole, a non-zero status
    included: it is the command's answer. A budget run out is still `CommandFailed(TIMED_OUT)`.
    With `log`, the stdout answered is empty and the stderr is the file's last `STDERR_KEPT`
    characters, read once the command has ended."""
    args = tuple(argv)
    _log.info("%s", shlex.join(args))
    output: Any = asyncio.subprocess.PIPE
    if log is not None:
        try:
            output = log.open("wb")
        except OSError as e:
            raise DriverFailed(f"{log} cannot be opened for the output of {args[0]}: {e}") from e
    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=output,
            stderr=output,
            env=None if env is None else dict(env),
            cwd=cwd,
            start_new_session=True,  # its own process group, so that its children are killed with it
        )
    finally:
        if log is not None:
            output.close()  # the child holds the file now; nothing of the core's ends it
    try:
        async with asyncio.timeout(timeout_s):
            stdout, stderr = await process.communicate()
    except TimeoutError:
        await _kill(process)
        raise CommandFailed(args, TIMED_OUT, f"timed out after {timeout_s:g} s") from None
    except BaseException:  # the caller was cancelled: the command must not outlive it
        await _kill(process)
        raise
    assert process.returncode is not None
    if log is not None:
        return process.returncode, "", _tail(log)
    return process.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")


def _tail(log: Path) -> str:
    """The last `STDERR_KEPT` characters of `log`, decoded with replacements; empty when the
    file cannot be read, which the command's status still reports."""
    try:
        data = log.read_bytes()
    except OSError:
        return ""
    return data[-STDERR_KEPT * 4:].decode(errors="replace")[-STDERR_KEPT:]


async def run_json(
    argv: Sequence[str], *, timeout_s: float, env: Mapping[str, str] | None = None, cwd: Path | None = None
) -> Any:
    """`run`'s stdout parsed as one JSON document."""
    return json.loads(await run(argv, timeout_s=timeout_s, env=env, cwd=cwd))


async def _kill(process: asyncio.subprocess.Process) -> None:
    """Kill `process`'s whole group, so that no child of it holds the pipes open, and reap it.
    When the group is gone, the process is killed alone, if it is there at all."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        with contextlib.suppress(ProcessLookupError):
            process.kill()
    await process.wait()
