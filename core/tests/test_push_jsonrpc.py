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
from fylgja_core.push import (
    RULE_REFUSED,
    RULE_UNAUTHORIZED,
    RULE_UNREACHABLE,
    Pushed,
    Refused,
    Unauthorized,
    Unreachable,
    lines,
    push,
)
from fylgja_core.push_jsonrpc import REASON_NOT_GIVEN, REASON_VALIDATES, commands, reason, request, validate_commands

PSP = Path(__file__).resolve().parents[2] / "psp"
SRLINUX = platform_package.load(PSP / "nokia_srlinux.yaml")
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
# The node's own answers, SR Linux 24.7.1 (design/verified-facts.md): the echo is one command per
# line, and the request's output follows the reason.
CHECKPOINT = "/system/configuration/checkpoint[id=__startup__]:\n    Loaded startup configuration\n\n"
COMMITTED = "All changes have been committed. Leaving candidate mode.\n"
REFUSED = (
    "Error: Cli commands 'enter candidate private\nload startup\nset / system name host-name s1\n"
    "set / interface ethernet-1/99 admin-state enable\ndiff flat\ncommit now' failed with error 1: "
    'At line 6: Error: Error in path: .interface{.name=="ethernet-1/99"}\n'
    "    [InvalidArgument] invalid port 99, max is 58\n\n" + CHECKPOINT + "delete / interface ethernet-1/1\n"
    "insert / interface ethernet-1/99 admin-state enable\n"
)
REFUSED_REASON = (
    'At line 6: Error: Error in path: .interface{.name=="ethernet-1/99"}\n'
    "    [InvalidArgument] invalid port 99, max is 58"
)
PARSE_REFUSED = (
    "Error: Cli commands 'enter candidate private\nload startup\nset / system name host-name s1\n"
    "set / bogus thing\ndiff flat\ncommit now' failed with error 1: At line 4: Parsing error: Unknown token "
    "'bogus'. Options are ['!!', '#', 'interface', 'system', '|']\n" + CHECKPOINT
)
CUT = (
    "Error: Cli commands 'enter candidate private\nload startup\n# s1: production configuration\n"
    "set / system name host-name s1\nset / interface ethernet-1/11 subinterface 0 ipv4 a..."
)
DIFF = CHECKPOINT + "insert / system name host-name s1\n" + COMMITTED
VALIDATE_REFUSED = (
    "Error: Cli commands 'enter candidate private\ncommit validate' failed with error 1: At line 2: Error in "
    "/interface[name=ethernet-1/1]/subinterface[index=0]/vlan/encap/single-tagged/vlan-id::\n"
    "    vlan-id only configurable if vlan-tagging enabled on parent interface\nError: Validate failed\n"
)
VALIDATE_REASON = (
    "At line 2: Error in /interface[name=ethernet-1/1]/subinterface[index=0]/vlan/encap/single-tagged/vlan-id::\n"
    "    vlan-id only configurable if vlan-tagging enabled on parent interface\nError: Validate failed"
)

Answer = httpx.Response | httpx.HTTPError
Handler = Callable[[httpx.Request], httpx.Response]


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


def _push(handler: Handler, config: str = CONFIG) -> Pushed | Refused:
    async def run() -> Pushed | Refused:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await push("10.0.0.5", SRLINUX, config, CRED, client=client)

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


def test_a_replace_is_one_post_with_basic_auth_within_the_budget_answering_the_devices_diff() -> None:
    handler, seen = _answers(_result([{"text": DIFF}]))
    answer = _push(handler)
    assert isinstance(answer, Pushed) and answer.diff == "insert / system name host-name s1\n"
    assert answer.duration_s >= 0
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


def test_the_diff_is_diff_flats_lines_without_the_reset_and_the_commit() -> None:
    text = CHECKPOINT + 'delete / interface ethernet-1/2\ninsert / interface ethernet-1/1 description "x"\n' + COMMITTED
    handler, _ = _answers(_result([{"text": text}]))
    answer = _push(handler)
    assert isinstance(answer, Pushed)
    assert answer.diff == 'delete / interface ethernet-1/2\ninsert / interface ethernet-1/1 description "x"\n'


def test_a_repeat_push_changes_nothing_so_its_diff_is_empty() -> None:
    handler, _ = _answers(_result([{"text": CHECKPOINT + COMMITTED}]))
    answer = _push(handler)
    assert isinstance(answer, Pushed) and answer.diff == ""


def test_several_text_entries_are_read_in_order() -> None:
    handler, _ = _answers(_result([{"text": "insert / a\n"}, {"text": ""}, {"text": "delete / b\n"}]))
    answer = _push(handler)
    assert isinstance(answer, Pushed) and answer.diff == "insert / a\ndelete / b\n"


@pytest.mark.parametrize(
    "result",
    [None, "insert / x\n", {"text": "insert / x\n"}, [], [{}], ["insert / x\n"], [{"text": 1}], [{"output": "x"}], 7],
    ids=["null", "string", "object", "empty", "no-text", "string-entry", "text-not-a-string", "output", "number"],
)
def test_a_committed_answer_of_any_other_shape_is_pushed_with_no_diff(result: object) -> None:
    handler, seen = _answers(_result(result))
    answer = _push(handler)
    assert isinstance(answer, Pushed) and answer.diff == "" and len(seen) == 1


@pytest.mark.parametrize(
    ("message", "found"),
    [
        (REFUSED, REFUSED_REASON),
        (
            PARSE_REFUSED,
            "At line 4: Parsing error: Unknown token 'bogus'. Options are ['!!', '#', 'interface', 'system', '|']",
        ),
        (VALIDATE_REFUSED, VALIDATE_REASON),
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
        ("Error: Cli commands 'enter candidate private, load startup, set / x' failed with error 1", ""),
        ("Error: Cli commands 'enter candidate private, load startup, set / x' failed with error 1: At", ""),
        ("Error: Cli commands 'enter candidate private, load startup, set / x' failed with error 1: At line 3: ", ""),
        ("Error: Cli commands 'x' failed with error 1: Error: not the recorded shape", ""),
        (
            "Error: Cli commands 'x' failed with error 1: At line 3: Error: x\ninsert / system name host-name s1\n"
            "  delete / interface ethernet-1/2\nupdate / a\nreplace / b\nstill the reason\n\ninsert / c",
            "At line 3: Error: x\nstill the reason",
        ),
    ],
    ids=[
        "after-the-echo",
        "to-the-output",
        "validate",
        "cut",
        "nothing-follows",
        "last-marker",
        "to-the-empty-line",
        "marker-in-the-diff",
        "cut-in-the-code",
        "cut-after-the-code",
        "cut-after-the-line",
        "another-shape",
        "diff-lines-dropped",
    ],
)
def test_the_reason_is_after_the_last_marker_before_the_first_empty_line_or_the_output(
    message: str, found: str
) -> None:
    assert reason(message) == found


def test_a_reason_never_carries_a_diff_line_into_the_refusal_or_the_log(caplog: pytest.LogCaptureFixture) -> None:
    message = REFUSED.replace("58\n\n", "58\ninsert / system name host-name s1\n\n")
    handler, seen = _answers(_error(message))
    with caplog.at_level(logging.DEBUG):
        answer = _push(handler)
    assert answer == Refused(REFUSED_REASON) and len(seen) == 1
    assert "invalid port 99" in caplog.text and "host-name s1" not in caplog.text


def test_a_refusal_answers_the_nodes_reason_and_asks_nothing_more() -> None:
    handler, seen = _answers(_error(REFUSED))
    answer = _push(handler)
    assert answer == Refused(REFUSED_REASON)
    assert isinstance(answer, Refused) and answer.rule == RULE_REFUSED == "push.refused"
    assert len(seen) == 1


@pytest.mark.parametrize(
    ("second", "found"),
    [
        (_error(VALIDATE_REFUSED), VALIDATE_REASON),
        (_result([{"text": "All changes are valid.\n"}]), REASON_VALIDATES),
        (_error(CUT), REASON_NOT_GIVEN),
        (_error(""), REASON_NOT_GIVEN),
        (httpx.Response(500), REASON_NOT_GIVEN),
        (httpx.Response(200, text="not json"), REASON_NOT_GIVEN),
        (httpx.ConnectError("refused"), REASON_NOT_GIVEN),
        (httpx.DecodingError("garbled"), REASON_NOT_GIVEN),
        (httpx.Response(401), REASON_NOT_GIVEN),
        (httpx.Response(403), REASON_NOT_GIVEN),
    ],
    ids=[
        "a-reason",
        "validates",
        "cut-again",
        "no-message",
        "http-500",
        "no-answer",
        "transport",
        "garbled",
        "http-401",
        "http-403",
    ],
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
        httpx.Response(200, text="<html>"),
        httpx.DecodingError("garbled"),
        httpx.Response(200, json={"jsonrpc": "2.0", "id": 1}),
    ],
    ids=["connect", "timeout", "http-503", "not-json", "garbled", "no-result-no-error"],
)
def test_a_node_that_gives_no_answer_is_unreachable_never_refused(failure: Answer) -> None:
    handler, seen = _answers(failure)
    with pytest.raises(Unreachable) as e:
        _push(handler)
    assert e.value.rule == RULE_UNREACHABLE == "push.unreachable"
    assert "10.0.0.5" in str(e.value) and len(seen) == 1
    if isinstance(failure, httpx.Response) and failure.status_code != 200:
        assert str(failure.status_code) in str(e.value)


@pytest.mark.parametrize("status", [401, 403])
def test_a_refused_login_is_unauthorized_never_unreachable(status: int) -> None:
    handler, seen = _answers(httpx.Response(status))
    with pytest.raises(Unauthorized) as e:
        _push(handler)
    assert e.value.rule == RULE_UNAUTHORIZED == "push.unauthorized" and not isinstance(e.value, Unreachable)
    assert "10.0.0.5" in str(e.value) and str(status) in str(e.value) and "s3cret" not in str(e.value)
    assert len(seen) == 1


def test_the_log_names_the_address_and_the_command_count_and_never_the_password_or_the_config(
    caplog: pytest.LogCaptureFixture,
) -> None:
    handler, _ = _answers(
        _result([{"text": DIFF}]), _error(REFUSED), _error(CUT), _result([{"text": "All changes are valid.\n"}])
    )
    with caplog.at_level(logging.DEBUG):
        for _ in range(3):
            _push(handler)
    assert "10.0.0.5" in caplog.text and "6 commands" in caplog.text and "json_rpc" in caplog.text
    assert "invalid port 99" in caplog.text and REASON_VALIDATES in caplog.text
    for secret in ("s3cret", AUTH, AUTH.removeprefix("Basic "), "host-name s1", "ethernet-1/1 admin-state"):
        assert secret not in caplog.text
