"""The local driver's reach into its runtime: the `containerlab` and `docker` CLIs, each run
as a subprocess, never through an SDK (D-018, D-043).

Every command line is logged at INFO on `fylgja.containerlab` before it runs, so an operator
can repeat it by hand; no command's stdout is ever logged, since it can hold a node's
configuration. A command that fails or outruns its budget raises `CommandFailed`, and one
whose caller is cancelled is killed: none outlives the call that ran it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import shlex
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_log = logging.getLogger("fylgja.containerlab")

TIMED_OUT = -1
"""The status `run` reports for a command it killed at its budget."""


class CommandFailed(Exception):
    """A command exited with a non-zero status, or ran past its budget (status `TIMED_OUT`,
    stderr saying so). Its message names the command and the status, never stdout."""

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
        raise CommandFailed(args, process.returncode, stderr.decode(errors="replace"))
    return stdout.decode()


async def run_json(
    argv: Sequence[str], *, timeout_s: float, env: Mapping[str, str] | None = None, cwd: Path | None = None
) -> Any:
    """`run`'s stdout parsed as one JSON document."""
    return json.loads(await run(argv, timeout_s=timeout_s, env=env, cwd=cwd))


async def _kill(process: asyncio.subprocess.Process) -> None:
    """Kill `process` and reap it."""
    with contextlib.suppress(ProcessLookupError):
        process.kill()
    await process.wait()
