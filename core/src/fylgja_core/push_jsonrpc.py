"""The `json_rpc` replace: one JSON-RPC `cli` request (D-027), asked again when its reason is cut (D-028).

The request enters the login's private candidate, loads the startup configuration (the baseline
containerlab left, which also clears what a refused request left in the candidate), sends the
configuration's lines, asks `diff flat` and commits with `commit now`: one atomic commit.

Sent with no output-format, the request is answered with one `{"text": …}` entry holding every
command's output in order: the reset's checkpoint lines, `diff flat`'s lines and the commit's
line. `Pushed.diff` is `diff flat`'s lines alone, the device's diff, so a repeat push's is empty.

A refusal is HTTP 200 with a JSON-RPC error that echoes every command sent, one per line. The
node's reason follows the echo, after `' failed with error '`, and ends at the message's first
empty line or where the request's output begins, at the reset's checkpoint line: a parse error
writes no empty line before it. The node cuts its message at about 1 KiB, which a real replace's
echo outruns, so a refusal with no reason gets one more request, `commit validate`, which lands
nothing. When that gives no reason either, the refusal is one of two sentences (D-028, D-047),
quoting nothing. A reason has the recorded shape `At line N: …`; anything else, a message cut inside or
just after the error code included, is no reason. Each shape is the node's own, as the facts
file (design/verified-facts.md) records it for `json_rpc`.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import httpx

from fylgja_core import node_http
from fylgja_core.credentials import Credential
from fylgja_core.platform_package import PlatformPackage
from fylgja_core.push import Pushed, Refused, Unauthorized, Unreachable, lines, post

ENTER = "enter candidate private"
LOAD = "load startup"
DIFF = "diff flat"
COMMIT = "commit now"
VALIDATE = "commit validate"
MARKER = "' failed with error "

# D-028's two sentences, the first as D-047 rewrote it: part of the core's contract word for word.
REASON_VALIDATES = (
    "the node's message ends before any reason Fylgja can read, and `commit validate` finds nothing wrong "
    "with what reached the candidate: the line it refused was either checked only as the commit applied, "
    "or never entered the candidate (D-047)"
)
REASON_NOT_GIVEN = (
    "the node's message ends before any reason Fylgja can read, and asking again with `commit validate` "
    "gave none (D-028)"
)

_CODE = re.compile(r"^\s*\d+:\s*")  # the error code the node writes before its reason: `1: At line 11: …`
_AT_LINE = re.compile(r"At line \d+: \S")  # the reason's recorded shape, with something after it
_DIFF_LINES = ("insert /", "delete /", "update /", "replace /")  # `diff flat`'s lines: configuration
_OUTPUT = "/system/configuration/checkpoint["  # the reset's output, the first line of the request's output

_log = logging.getLogger("fylgja.push")


def commands(config: str) -> list[str]:
    """The replace's commands: the reset to the baseline, the configuration's lines, the diff, the commit."""
    return [ENTER, LOAD, *lines(config), DIFF, COMMIT]


def validate_commands() -> list[str]:
    """The request that asks a refused candidate for its reason; it lands nothing."""
    return [ENTER, VALIDATE]


def request(commands: list[str]) -> dict[str, Any]:
    """The JSON-RPC `cli` request that runs `commands` in order."""
    return {"jsonrpc": "2.0", "id": 1, "method": "cli", "params": {"commands": commands}}


def reason(message: str) -> str:
    """The node's reason in a refusal's message, or "" when the message gives none.

    It follows the last `' failed with error '` before the message's first empty line or the
    request's output, without the error code the node writes first, and counts only in the
    recorded shape `At line N: …`.
    What follows that line is the request's output, the diff's configuration lines included, and
    is never read; a diff line before it is dropped too, so no configuration line is quoted.
    """
    head = _before_output(message)
    at = head.rfind(MARKER)
    if at < 0:
        return ""
    rest = _CODE.sub("", head[at + len(MARKER) :], count=1)
    if not _AT_LINE.match(rest):
        return ""
    return "\n".join(line for line in rest.split("\n") if not line.strip().startswith(_DIFF_LINES)).strip()


async def replace(
    address: str, package: PlatformPackage, config: str, credential: Credential, *, client: httpx.AsyncClient
) -> Pushed | Refused:
    """Replace the node's configuration in one request; a refusal with no reason asks once more."""
    cmds = commands(config)
    url = node_http.url(address, package.push.port, "/jsonrpc")
    budget = package.push.timeout_s
    start = time.monotonic()
    answer = await post(client, url, request(cmds), credential, timeout_s=budget)
    elapsed = time.monotonic() - start
    error = answer.get("error")
    if error is None:
        _log.info("pushed %s by json_rpc: %d commands in %.2fs", address, len(cmds), elapsed)
        return Pushed(diff=_diff(answer["result"]), duration_s=elapsed)
    found = reason(_message(error)) or await _ask_again(client, url, credential, address, budget - elapsed)
    _log.info("%s refused the json_rpc replace of %d commands in %.2fs: %s", address, len(cmds), elapsed, found)
    return Refused(found)


async def _ask_again(
    client: httpx.AsyncClient, url: str, credential: Credential, address: str, remaining_s: float
) -> str:
    """The reason `commit validate` gives, inside what is left of the push's budget, or a D-028 sentence."""
    if remaining_s <= 0:
        _log.info("%s: the push's budget is spent, so commit validate is not asked", address)
        return REASON_NOT_GIVEN
    try:
        answer = await post(client, url, request(validate_commands()), credential, timeout_s=remaining_s)
    except (Unreachable, Unauthorized) as err:
        _log.warning("%s: commit validate got no answer: %s", address, err.message)
        return REASON_NOT_GIVEN
    error = answer.get("error")
    if error is None:
        return REASON_VALIDATES
    return reason(_message(error)) or REASON_NOT_GIVEN


def _before_output(text: str) -> str:
    kept: list[str] = []
    for line in text.split("\n"):
        if not line.strip() or line.startswith(_OUTPUT):
            break
        kept.append(line)
    return "\n".join(kept)


def _message(error: object) -> str:
    message = error.get("message") if isinstance(error, dict) else None
    return message if isinstance(message, str) else ""


def _diff(result: object) -> str:
    """`diff flat`'s lines in the text of a list result's `{"text": …}` entries; "" for any other shape.

    The text also holds the reset's checkpoint lines and the commit's line, which are no diff.
    `diff flat` writes `insert /` and `delete /` lines. The commit landed whatever the answer's
    shape, so no shape fails the push.
    """
    if not isinstance(result, list):
        return ""
    text = "".join(e["text"] for e in result if isinstance(e, dict) and isinstance(e.get("text"), str))
    return "".join(line for line in text.splitlines(keepends=True) if line.startswith(_DIFF_LINES))
