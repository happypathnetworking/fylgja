"""The eAPI replace: one request in a named session made the baseline, then one commit (D-027); a
refused session is aborted, once and best effort, so the node's five-session limit is never reached."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from fylgja_core import platform_package, push_eapi
from fylgja_core.credentials import Credential
from fylgja_core.platform_package import PlatformPackage
from fylgja_core.push import RULE_REFUSED, RULE_UNREACHABLE, Pushed, Refused, Unreachable, push
from fylgja_core.push_eapi import abort_commands, commands, request, session

PSP = Path(__file__).resolve().parents[2] / "psp"
SRLINUX = platform_package.load(PSP / "nokia_srlinux.yaml")
EOS = platform_package.load(PSP / "arista_eos.yaml")
CRED = Credential(username="admin", password="s3cret")
AUTH = "Basic " + base64.b64encode(b"admin:s3cret").decode()
CONFIG = "hostname e1\n!\ninterface Ethernet1\n   no shutdown\n\nno such command\n"
SESSION = "fylgja-1-123"
SENT = [
    "enable",
    "configure session fylgja-1-123",
    "rollback clean-config",
    "copy startup-config session-config",
    "hostname e1",
    "!",
    "interface Ethernet1",
    "   no shutdown",
    "no such command",
    "show session-config diffs",
    "commit",
]
REFUSED_AT = SENT.index("no such command")
ERRORS = ["Invalid input (at token 1: 'such')", "a second reason"]

Answer = httpx.Response | httpx.HTTPError
Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture(autouse=True)
def _nanoseconds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(push_eapi, "time", SimpleNamespace(time_ns=lambda: 123, monotonic=time.monotonic))


def _answers(*answers: Answer) -> tuple[Handler, list[httpx.Request]]:
    """A handler giving each answer in turn, raising an error, and the requests it saw."""
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        answer = answers[len(seen) - 1]
        if isinstance(answer, httpx.HTTPError):
            raise answer
        return answer

    return handler, seen


def _push(handler: Handler, package: PlatformPackage = EOS, *, attempt: int = 1) -> Pushed | Refused:
    async def run() -> Pushed | Refused:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await push("10.0.0.6", package, CONFIG, CRED, attempt=attempt, client=client)

    return asyncio.run(run())


def _result(result: object) -> httpx.Response:
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": "1", "result": result})


def _refused(data: object) -> httpx.Response:
    message = f"CLI command {REFUSED_AT + 1} of {len(SENT)} 'no such command' failed: invalid command"
    error = {"code": 1002, "message": message, "data": data}
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": "1", "error": error})


def _refusal() -> httpx.Response:
    return _refused([{"output": ""}] * REFUSED_AT + [{"errors": ERRORS, "output": "% Invalid input\n"}])


def test_a_session_names_the_attempt_and_the_nanoseconds() -> None:
    assert session(2, 123) == "fylgja-2-123"


def test_a_replace_makes_the_session_the_baseline_sends_the_lines_asks_the_diff_and_commits() -> None:
    assert commands(CONFIG, SESSION) == SENT
    assert abort_commands(SESSION) == ["enable", "configure session fylgja-1-123", "abort"]
    assert request(["x"]) == {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "runCmds",
        "params": {"version": 1, "cmds": ["x"], "format": "text"},
    }


def test_a_replace_is_one_post_with_basic_auth_answering_the_diff_commands_output_and_never_aborts() -> None:
    handler, seen = _answers(_result([{"output": f"output {i}"} for i in range(len(SENT))]))
    answer = _push(handler)
    assert isinstance(answer, Pushed) and answer.diff == "output 9" and answer.duration_s >= 0
    assert len(seen) == 1
    req = seen[0]
    assert req.method == "POST" and (req.url.scheme, req.url.host, req.url.port or 443, req.url.path) == (
        "https",
        "10.0.0.6",
        EOS.push.port,
        "/command-api",
    )
    assert json.loads(req.content) == request(commands(CONFIG, SESSION))
    assert req.headers["authorization"] == AUTH
    assert req.extensions["timeout"] == dict.fromkeys(("connect", "read", "write", "pool"), EOS.push.timeout_s)


def test_each_attempt_names_a_session_of_its_own() -> None:
    handler, seen = _answers(_result([]))
    _push(handler, attempt=3)
    assert json.loads(seen[0].content)["params"]["cmds"][1] == "configure session fylgja-3-123"


@pytest.mark.parametrize(
    "result",
    [[], [{"output": "x"}], [*([{}] * (len(SENT) - 2)), {"output": None}, {}], "committed"],
    ids=["empty", "one-entry", "null-output", "not-a-list"],
)
def test_a_committed_answer_with_no_diff_output_is_pushed_with_no_diff(result: object) -> None:
    handler, seen = _answers(_result(result))
    answer = _push(handler)
    assert isinstance(answer, Pushed) and answer.diff == "" and len(seen) == 1


def test_a_refusal_names_the_command_and_the_nodes_errors_then_aborts_the_session_exactly_once() -> None:
    handler, seen = _answers(_refusal(), _result([{}, {}, {}]))
    answer = _push(handler)
    assert answer == Refused(
        "command 9 ('no such command') refused: Invalid input (at token 1: 'such'); a second reason"
    )
    assert isinstance(answer, Refused) and answer.rule == RULE_REFUSED == "push.refused"
    assert len(seen) == 2
    first, abort = seen
    assert json.loads(abort.content) == request(abort_commands(SESSION))
    assert abort.method == "POST" and abort.url == first.url and abort.headers["authorization"] == AUTH


@pytest.mark.parametrize("data", [None, [], [{}] * (len(SENT) + 1), "x"], ids=["absent", "empty", "too-long", "string"])
def test_a_refusal_naming_no_command_is_still_refused_and_aborted(data: object) -> None:
    handler, seen = _answers(_refused(data), _result([{}, {}, {}]))
    assert _push(handler) == Refused("the node refused the push and named no command Fylgja can read")
    assert len(seen) == 2 and json.loads(seen[1].content) == request(abort_commands(SESSION))


@pytest.mark.parametrize(
    "abort",
    [
        httpx.ConnectError("refused"),
        httpx.ReadTimeout("slow"),
        httpx.Response(500),
        httpx.Response(200, text="not json"),
        httpx.DecodingError("garbled"),
        _refused([{}, {}, {"errors": ["No session"]}]),
    ],
    ids=["connect", "timeout", "http-500", "not-json", "garbled", "refused"],
)
def test_an_abort_that_fails_is_logged_and_never_raised(abort: Answer, caplog: pytest.LogCaptureFixture) -> None:
    handler, seen = _answers(_refusal(), abort)
    with caplog.at_level(logging.WARNING, logger="fylgja.push"):
        answer = _push(handler)
    assert isinstance(answer, Refused) and answer.message.startswith("command 9 ")
    assert len(seen) == 2
    assert SESSION in caplog.text and "10.0.0.6" in caplog.text


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ConnectError("refused"),
        httpx.ReadTimeout("slow"),
        httpx.Response(503),
        httpx.Response(401),
        httpx.Response(200, text="<html>"),
        httpx.DecodingError("garbled"),
        httpx.Response(200, json={"jsonrpc": "2.0", "id": "1"}),
    ],
    ids=["connect", "timeout", "http-503", "http-401", "not-json", "garbled", "no-result-no-error"],
)
def test_a_node_that_gives_no_answer_is_unreachable_never_refused_and_nothing_is_aborted(failure: Answer) -> None:
    handler, seen = _answers(failure)
    with pytest.raises(Unreachable) as e:
        _push(handler)
    assert e.value.rule == RULE_UNREACHABLE == "push.unreachable"
    assert "10.0.0.6" in str(e.value) and len(seen) == 1
    if isinstance(failure, httpx.Response) and failure.status_code != 200:
        assert str(failure.status_code) in str(e.value)


def test_the_log_names_the_address_and_the_command_count_and_never_the_password_or_the_config(
    caplog: pytest.LogCaptureFixture,
) -> None:
    diff: list[object] = [*([{}] * (len(SENT) - 2)), {"output": "+hostname e1\n"}, {}]
    handler, _ = _answers(_result(diff), _refusal(), _result([{}, {}, {}]))
    with caplog.at_level(logging.DEBUG):
        for _ in range(2):
            _push(handler)
    assert "10.0.0.6" in caplog.text and "11 commands" in caplog.text and "eapi" in caplog.text
    assert "Invalid input (at token 1: 'such')" in caplog.text and SESSION in caplog.text
    for secret in ("s3cret", AUTH, AUTH.removeprefix("Basic "), "hostname e1", "Ethernet1", "% Invalid input"):
        assert secret not in caplog.text


def test_the_push_dispatches_on_the_packages_delivery() -> None:
    for package, path, method in [(EOS, "/command-api", "runCmds"), (SRLINUX, "/jsonrpc", "cli")]:
        handler, seen = _answers(_result([]))
        assert isinstance(_push(handler, package), Pushed)
        assert seen[0].url.path == path and json.loads(seen[0].content)["method"] == method
