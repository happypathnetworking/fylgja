"""The `eapi` replace: one eAPI `runCmds` request in a named configuration session (D-027).

The request opens the session, empties it with `rollback clean-config` and loads the startup
configuration into it with `copy startup-config session-config` (the pair makes the session
exactly the baseline containerlab left; the copy alone would merge), sends the configuration's
lines, asks `show session-config diffs` and commits: one atomic commit. It is sent with
`format: "text"`, since the diff command has no JSON model.

A committed session's name cannot be reused, so each attempt names its own. A refused request
leaves its session pending, and the node allows five, so it is aborted at once, best effort.
The node names the refused command in its own answer, so no second request asks for a reason.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from fylgja_core import node_http
from fylgja_core.credentials import Credential
from fylgja_core.platform_package import PlatformPackage
from fylgja_core.push import Pushed, Refused, Unauthorized, Unreachable, lines, post

ENABLE = "enable"
ROLLBACK = "rollback clean-config"
COPY = "copy startup-config session-config"
DIFF = "show session-config diffs"
COMMIT = "commit"
ABORT = "abort"

NO_COMMAND = "the node refused the push and named no command Fylgja can read"
NO_REASON = "the node named no reason"

_log = logging.getLogger("fylgja.push")


def session(attempt: int, ns: int) -> str:
    """The configuration session one attempt pushes in: its number and a clock's nanoseconds."""
    return f"fylgja-{attempt}-{ns}"


def commands(config: str, session: str) -> list[str]:
    """The replace's commands: the session made the baseline, the configuration's lines, the diff, the commit."""
    return [ENABLE, f"configure session {session}", ROLLBACK, COPY, *lines(config), DIFF, COMMIT]


def abort_commands(session: str) -> list[str]:
    """The request that removes a refused, pending session."""
    return [ENABLE, f"configure session {session}", ABORT]


def request(commands: list[str]) -> dict[str, Any]:
    """The eAPI `runCmds` request that runs `commands` in order, answered as text."""
    return {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "runCmds",
        "params": {"version": 1, "cmds": commands, "format": "text"},
    }


async def replace(
    address: str,
    package: PlatformPackage,
    config: str,
    credential: Credential,
    *,
    attempt: int,
    client: httpx.AsyncClient,
) -> Pushed | Refused:
    """Replace the node's configuration in one request; a refused session is aborted."""
    name = session(attempt, time.time_ns())
    cmds = commands(config, name)
    url = node_http.url(address, package.push.port, "/command-api")
    start = time.monotonic()
    answer = await post(client, url, request(cmds), credential, timeout_s=package.push.timeout_s)
    elapsed = time.monotonic() - start
    error = answer.get("error")
    if error is None:
        _log.info("pushed %s by eapi: %d commands in %.2fs", address, len(cmds), elapsed)
        return Pushed(diff=_diff(answer["result"]), duration_s=elapsed)
    found = _refusal(error, cmds)
    _log.info("%s refused the eapi replace of %d commands in %.2fs: %s", address, len(cmds), elapsed, found)
    await _abort(client, url, credential, address, name, package.push.timeout_s)
    return Refused(found)


def _refusal(error: object, cmds: list[str]) -> str:
    """The refused command and the node's errors for it: the last entry of `error.data` is the one."""
    data = error.get("data") if isinstance(error, dict) else None
    if not isinstance(data, list) or not 0 < len(data) <= len(cmds):
        return NO_COMMAND
    i = len(data) - 1
    entry = data[i]
    errors = entry.get("errors") if isinstance(entry, dict) else None
    reasons = [e for e in errors if isinstance(e, str)] if isinstance(errors, list) else []
    return f"command {i + 1} ({cmds[i]!r}) refused: {'; '.join(reasons) or NO_REASON}"


async def _abort(
    client: httpx.AsyncClient, url: str, credential: Credential, address: str, name: str, timeout_s: float
) -> None:
    """Abort the refused session, once and best effort: a failure is logged, never raised."""
    try:
        answer = await post(client, url, request(abort_commands(name)), credential, timeout_s=timeout_s)
    except (Unreachable, Unauthorized) as err:
        _log.warning("%s: the refused session %s was not aborted: %s", address, name, err.message)
        return
    if answer.get("error") is not None:
        _log.warning("%s: the node refused to abort the refused session %s", address, name)
        return
    _log.info("%s: aborted the refused session %s", address, name)


def _diff(result: object) -> str:
    """The diff command's output, the entry before the commit's; "" when it is absent."""
    entry = result[-2] if isinstance(result, list) and len(result) >= 2 else None
    output = entry.get("output") if isinstance(entry, dict) else None
    return output if isinstance(output, str) else ""
