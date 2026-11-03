"""The local driver's reach into its runtime: the `containerlab` and `docker` CLIs, each run
as a subprocess, never through an SDK (D-018, D-043).

Every command line is logged at INFO on `fylgja.containerlab` before it runs, so an operator
can repeat it by hand; no command's stdout is ever logged, since it can hold a node's
configuration. A command that fails or outruns its budget raises `CommandFailed`, and one
whose caller is cancelled is killed. Each command leads a process group of its own, which is
killed whole, so neither it nor a child it spawned outlives the call that ran it.
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

_log = logging.getLogger("fylgja.containerlab")

TIMED_OUT = -1
"""The status `run` reports for a command it killed at its budget."""

STDERR_KEPT = 4096
"""How many bytes of a failed command's stderr `CommandFailed` keeps: the last, where a CLI
writes its error."""


class CommandFailed(Exception):
    """A command exited with a non-zero status, or ran past its budget (status `TIMED_OUT`,
    stderr saying so). `stderr` is the last `STDERR_KEPT` bytes of the command's. Its message
    names the command and the status, never its output."""

    def __init__(self, argv: Sequence[str], returncode: int, stderr: str) -> None:
        self.argv = tuple(argv)
        self.returncode = returncode
        self.stderr = stderr
        status = stderr if returncode == TIMED_OUT else f"exited with status {returncode}"
        super().__init__(f"{shlex.join(self.argv)} {status}")


async def run(
    argv: Sequence[str], *, timeout_s: float, env: Mapping[str, str] | None = None, cwd: Path | None = None
) -> str:
    """The stdout of `argv` run to completion within `timeout_s` seconds, with `env` as its
    whole environment (the core's when None) and `cwd` as its directory; `CommandFailed` for a
    non-zero status, or when the budget runs out and the command is killed."""
    args = tuple(argv)
    _log.info("%s", shlex.join(args))
    process = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=None if env is None else dict(env),
        cwd=cwd,
        start_new_session=True,  # its own process group, so that its children are killed with it
    )
    try:
        async with asyncio.timeout(timeout_s):
            stdout, stderr = await process.communicate()
    except TimeoutError:
        await _kill(process)
        raise CommandFailed(args, TIMED_OUT, f"timed out after {timeout_s:g} s") from None
    except BaseException:  # the caller was cancelled: the command must not outlive it
        await _kill(process)
        raise
    if process.returncode:
        raise CommandFailed(args, process.returncode, stderr[-STDERR_KEPT:].decode(errors="replace"))
    return stdout.decode(errors="replace")


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
