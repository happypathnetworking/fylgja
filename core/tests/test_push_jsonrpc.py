"""The JSON-RPC replace: one request resets the candidate to the baseline and commits (D-027), and
a refusal cut before its reason asks the node once more, with `commit validate` (D-028)."""

from __future__ import annotations

import asyncio
import base64
import itertools
import json
import logging
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from fylgja_core import platform_package, push_jsonrpc
from fylgja_core.credentials import Credential
from fylgja_core.platform_package import PlatformPackage
from fylgja_core.push import RULE_REFUSED, RULE_UNREACHABLE, Pushed, Refused, Unreachable, lines, push
from fylgja_core.push_jsonrpc import REASON_NOT_GIVEN, REASON_VALIDATES, commands, reason, request, validate_commands

PSP = Path(__file__).resolve().parents[2] / "psp"
SRLINUX = platform_package.load(PSP / "nokia_srlinux.yaml")
EOS = platform_package.load(PSP / "arista_eos.yaml")
CRED = Credential(username="admin", password="s3cret")
AUTH = "Basic " + base64.b64encode(b"admin:s3cret").decode()
CONFIG = "set / system name host-name s1\n\nset / interface ethernet-1/1 admin-state enable\n"
SENT = [
    "enter candidate private",
    "load startup",
    "set / system name host-name s1",
    "set / interface ethernet-1/1 admin-state enable",
    "diff flat",
    "commit now",
]
REFUSED = (
    "Error: Cli commands 'enter candidate private, load startup, set / x' failed with error 1: "
    "At line 3: Error: invalid port 99, max is 58\n\ninsert / interface…"
)
CUT = "Error: Cli commands 'enter candidate private, load startup, set / system name host-name s1, set / interf"
VALIDATE_REFUSED = (
    "Error: Cli commands 'enter candidate private, commit validate' failed with error 1: "
    "At line 2: Error: vlan encapsulation needs vlan-tagging on ethernet-1/1\n\n"
)

Answer = httpx.Response | httpx.TransportError
Handler = Callable[[httpx.Request], httpx.Response]


def _answers(*answers: Answer) -> tuple[Handler, list[httpx.Request]]:
    """A handler giving each answer in turn, raising a transport error, and the requests it saw."""
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        answer = answers[len(seen) - 1]
        if isinstance(answer, httpx.TransportError):
            raise answer
        return answer

    return handler, seen


def _push(handler: Handler, package: PlatformPackage = SRLINUX, config: str = CONFIG) -> Pushed | Refused:
    async def run() -> Pushed | Refused:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await push("10.0.0.5", package, config, CRED, client=client)

    return asyncio.run(run())


def _result(result: object) -> httpx.Response:
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": result})


def _error(message: str) -> httpx.Response:
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "error": {"code": -1, "message": message}})


def test_lines_are_the_non_empty_lines_each_sent_as_it_is() -> None:
    assert lines("a\n\n   \n  b c\nd") == ["a", "  b c", "d"]


def test_a_replace_resets_to_the_baseline_sends_the_lines_asks_the_diff_and_commits() -> None:
    assert commands(CONFIG) == SENT
    assert validate_commands() == ["enter candidate private", "commit validate"]
    assert request(["x"]) == {"jsonrpc": "2.0", "id": 1, "method": "cli", "params": {"commands": ["x"]}}


def test_the_two_sentences_are_d028s_word_for_word() -> None:
    assert REASON_VALIDATES == (
        "the node's message ends before any reason Fylgja can read, and the candidate it refused passes "
        "`commit validate`, which does not run every check a commit does (D-028)"
    )
    assert REASON_NOT_GIVEN == (
        "the node's message ends before any reason Fylgja can read, and asking again with `commit validate` "
        "gave none (D-028)"
    )


def test_a_replace_is_one_post_with_basic_auth_within_the_budget_answering_the_diff_commands_entry() -> None:
    handler, seen = _answers(_result([f"output {i}" for i in range(len(SENT))]))
    answer = _push(handler)
    assert isinstance(answer, Pushed) and answer.diff == "output 4" and answer.duration_s >= 0
    assert len(seen) == 1
    req = seen[0]
    assert req.method == "POST" and (req.url.scheme, req.url.host, req.url.port or 443, req.url.path) == (
        "https",
        "10.0.0.5",
        SRLINUX.push.port,
        "/jsonrpc",
    )
    assert json.loads(req.content) == request(commands(CONFIG))
    assert req.headers["authorization"] == AUTH
    assert req.extensions["timeout"] == dict.fromkeys(("connect", "read", "write", "pool"), SRLINUX.push.timeout_s)


@pytest.mark.parametrize(
    ("entry", "diff"),
    [(None, ""), ("", ""), ({}, ""), ({"text": "insert / x\n"}, "insert / x\n"), ("insert / y\n", "insert / y\n")],
    ids=["null", "empty", "empty-object", "text-object", "string"],
)
def test_the_diff_entry_is_taken_as_a_string_and_empty_or_null_is_no_diff(entry: object, diff: str) -> None:
    result: list[object] = [{}] * len(SENT)
    result[SENT.index("diff flat")] = entry
    handler, _ = _answers(_result(result))
    answer = _push(handler)
    assert isinstance(answer, Pushed) and answer.diff == diff


def test_a_committed_answer_with_no_entry_for_the_diff_is_pushed_with_no_diff() -> None:
    handler, _ = _answers(_result([{"text": "All changes have been committed. Leaving candidate mode.\n"}]))
    answer = _push(handler)
    assert isinstance(answer, Pushed) and answer.diff == ""


@pytest.mark.parametrize(
    ("message", "found"),
    [
        (REFUSED, "At line 3: Error: invalid port 99, max is 58"),
        (CUT, ""),
        ("Error: Cli commands 'enter candidate private' failed with error 1: ", ""),
        (
            "Error: Cli commands 'set / x description \"' failed with error 9: no\"' failed with error 1: "
            "At line 3: Error: real\n\nmore",
            "At line 3: Error: real",
        ),
        (
            "Error: Cli commands 'x' failed with error 1: At line 1: Error: one\ntwo\n  \ndiff",
            "At line 1: Error: one\ntwo",
        ),
        (CUT + '\n\ninsert / system description "\' failed with error 1: At line 1: lie"', ""),
    ],
    ids=["after-the-echo", "cut", "nothing-follows", "last-marker", "to-the-empty-line", "marker-in-the-diff"],
)
def test_the_reason_is_after_the_last_marker_before_the_first_empty_line(message: str, found: str) -> None:
    assert reason(message) == found


def test_a_refusal_answers_the_nodes_reason_and_asks_nothing_more() -> None:
    handler, seen = _answers(_error(REFUSED))
    answer = _push(handler)
    assert answer == Refused("At line 3: Error: invalid port 99, max is 58")
    assert isinstance(answer, Refused) and answer.rule == RULE_REFUSED == "push.refused"
    assert len(seen) == 1


@pytest.mark.parametrize(
    ("second", "found"),
    [
        (_error(VALIDATE_REFUSED), "At line 2: Error: vlan encapsulation needs vlan-tagging on ethernet-1/1"),
        (_result([{"text": "All changes are valid.\n"}]), REASON_VALIDATES),
        (_error(CUT), REASON_NOT_GIVEN),
        (_error(""), REASON_NOT_GIVEN),
        (httpx.Response(500), REASON_NOT_GIVEN),
        (httpx.Response(200, text="not json"), REASON_NOT_GIVEN),
        (httpx.ConnectError("refused"), REASON_NOT_GIVEN),
    ],
    ids=["a-reason", "validates", "cut-again", "no-message", "http-500", "no-answer", "transport"],
)
def test_a_cut_refusal_asks_again_exactly_once_with_commit_validate(second: Answer, found: str) -> None:
    handler, seen = _answers(_error(CUT), second)
    assert _push(handler) == Refused(found)
    assert len(seen) == 2
    first, again = seen
    assert json.loads(again.content) == request(validate_commands())
    assert again.method == "POST" and again.url == first.url and again.headers["authorization"] == AUTH
    assert 0 < again.extensions["timeout"]["read"] <= SRLINUX.push.timeout_s


def test_a_cut_refusal_with_the_budget_spent_asks_nothing_more(monkeypatch: pytest.MonkeyPatch) -> None:
    ticks = itertools.count(0.0, SRLINUX.push.timeout_s + 1.0)
    monkeypatch.setattr(push_jsonrpc, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    handler, seen = _answers(_error(CUT))
    assert _push(handler) == Refused(REASON_NOT_GIVEN)
    assert len(seen) == 1


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ConnectError("refused"),
        httpx.ReadTimeout("slow"),
        httpx.Response(503),
        httpx.Response(401),
        httpx.Response(200, text="<html>"),
        httpx.Response(200, json={"jsonrpc": "2.0", "id": 1}),
    ],
    ids=["connect", "timeout", "http-503", "http-401", "not-json", "no-result-no-error"],
)
def test_a_node_that_gives_no_answer_is_unreachable_never_refused(failure: Answer) -> None:
    handler, seen = _answers(failure)
    with pytest.raises(Unreachable) as e:
        _push(handler)
    assert e.value.rule == RULE_UNREACHABLE == "push.unreachable"
    assert "10.0.0.5" in str(e.value) and len(seen) == 1
    if isinstance(failure, httpx.Response) and failure.status_code != 200:
        assert str(failure.status_code) in str(e.value)


def test_the_log_names_the_address_and_the_command_count_and_never_the_password_or_the_config(
    caplog: pytest.LogCaptureFixture,
) -> None:
    diff: list[object] = [{}, {}, {}, {}, "insert / system name host-name s1\n", {}]
    handler, _ = _answers(_result(diff), _error(REFUSED), _error(CUT), _result([{"text": "All changes are valid.\n"}]))
    with caplog.at_level(logging.DEBUG):
        for _ in range(3):
            _push(handler)
    assert "10.0.0.5" in caplog.text and "6 commands" in caplog.text and "json_rpc" in caplog.text
    assert "invalid port 99" in caplog.text and REASON_VALIDATES in caplog.text
    for secret in ("s3cret", AUTH, AUTH.removeprefix("Basic "), "host-name s1", "ethernet-1/1 admin-state"):
        assert secret not in caplog.text


def test_eapi_is_not_yet_a_mechanism_this_build_pushes_by() -> None:
    handler, seen = _answers()
    with pytest.raises(NotImplementedError):
        _push(handler, EOS)
    assert seen == []
