"""`infrahub/seed/hub.py`: the one transport every write goes through, the bounded wait, and `infrahubctl`.

Infrahub is `httpx.MockTransport`, `infrahubctl` a fake `run`, and the clock a fake: nothing here opens a socket or
starts a process. The token is a value of the tests' own.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from hub import HubError, connect, wait_until

HOST = "infrahub.example"
ADDRESS = f"http://{HOST}"
TOKEN = "s3cr3t-0f-th1s-t3st"
"""The tests' token: no four characters of it are in any sentence `hub.py` writes, `<token>` among them."""
CTL = Path("/opt/example/bin/infrahubctl")
ENVIRON = {"FYLGJA_INFRAHUB_ADDRESS": ADDRESS, "FYLGJA_INFRAHUB_WRITE_TOKEN": TOKEN}
QUERY = "query ($name: String!) { DcimDevice(name__value: $name) { count } }"


def holds_part(text: str) -> bool:
    """Whether `text` holds any four characters of the token in a row."""
    return any(TOKEN[at : at + 4] in text for at in range(len(TOKEN) - 3))


class Clock:
    """A clock that moves only when its `sleep` is called."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def answering(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def test_connect_names_the_variable_that_is_not_set() -> None:
    with pytest.raises(HubError) as raised:
        connect({}, ctl=CTL)
    assert str(raised.value) == "FYLGJA_INFRAHUB_ADDRESS is not set"
    with pytest.raises(HubError) as raised:
        connect({"FYLGJA_INFRAHUB_ADDRESS": ADDRESS}, ctl=CTL)
    assert str(raised.value) == "FYLGJA_INFRAHUB_WRITE_TOKEN is not set"
    with pytest.raises(HubError) as raised:
        connect({"FYLGJA_INFRAHUB_ADDRESS": ADDRESS, "FYLGJA_INFRAHUB_WRITE_TOKEN": ""}, ctl=CTL)
    assert str(raised.value) == "FYLGJA_INFRAHUB_WRITE_TOKEN is not set"


@pytest.mark.parametrize(
    "token",
    [TOKEN + "\r", TOKEN + "\n", TOKEN + "\t", TOKEN + " ", "s3cr3t-0f-th1s-t3sté"],
    ids=["cr", "lf", "tab", "space", "non-ascii"],
)
def test_a_token_a_header_cannot_carry_is_refused_naming_the_variable_alone(token: str) -> None:
    """h11 refuses such a value in an error holding the bytes' `repr`, which no replacement of the token matches."""
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200)

    run = Run()
    with pytest.raises(HubError) as raised:
        connect(ENVIRON | {"FYLGJA_INFRAHUB_WRITE_TOKEN": token}, ctl=CTL, transport=answering(handler), run=run)
    assert str(raised.value) == "FYLGJA_INFRAHUB_WRITE_TOKEN holds a character a header cannot carry"
    assert not holds_part(repr(raised.value))
    assert sent == []
    assert run.calls == []


def test_the_client_drops_an_idle_connection_before_the_server_does(monkeypatch: pytest.MonkeyPatch) -> None:
    """Infrahub's server closes a connection idle for 2 s (design/verified-facts.md), the interval of every wait's
    polls: a connection the client kept longer was once closed under a poll, which then had no answer."""
    made: list[dict[str, Any]] = []
    real = httpx.Client

    def client(**kwargs: Any) -> httpx.Client:
        made.append(kwargs)
        return real(transport=answering(lambda request: httpx.Response(200)))

    monkeypatch.setattr(httpx, "Client", client)
    connect(ENVIRON, ctl=CTL)
    [kwargs] = made
    assert kwargs["limits"].keepalive_expiry < 2
    assert kwargs["trust_env"] is False


def test_gql_posts_to_the_branchs_endpoint_with_the_key_and_the_time() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": {"DcimDevice": {"count": 3}}})

    hub = connect(ENVIRON, ctl=CTL, transport=answering(handler))
    assert hub.gql("third-link", QUERY, {"name": "n1"}, at="2026-11-09T13:44:54.984697Z") == {
        "DcimDevice": {"count": 3},
    }
    assert hub.gql("third-link", QUERY) == {"DcimDevice": {"count": 3}}
    pinned, present = seen
    for request in seen:
        assert request.method == "POST"
        assert request.url.host == HOST
        assert request.url.path == "/graphql/third-link"
        assert request.headers["X-INFRAHUB-KEY"] == TOKEN
    assert pinned.url.params["at"] == "2026-11-09T13:44:54.984697Z"
    assert "at" not in present.url.params
    assert json.loads(pinned.content) == {"query": QUERY, "variables": {"name": "n1"}}
    assert json.loads(present.content) == {"query": QUERY, "variables": {}}


def refused(status: int, body: dict[str, Any]) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    return handler


def unreachable(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("[Errno 111] Connection refused", request=request)


INVALID_TOKEN = {
    "data": None,
    "errors": [
        {
            "message": "Invalid token",
            "extensions": {"code": "AUTHENTICATION_REQUIRED", "http_status": 401, "data": {}},
        },
    ],
}
"""What 1.11.11 answered a wrong token, with HTTP 401."""

NOT_UNIQUE = {
    "data": {"CoreStandardGroupCreate": None},
    "errors": [
        {
            "message": "Violates uniqueness constraint 'name'",
            "locations": [{"line": 1, "column": 29}],
            "path": ["CoreStandardGroupCreate"],
            "extensions": {"code": "UNDEFINED_ERROR", "http_status": 422, "data": {}},
        },
    ],
}
"""What 1.11.11 answered a second group of one name, with HTTP 200."""


@pytest.mark.parametrize(
    ("handler", "words"),
    [
        (refused(401, INVALID_TOKEN), ["HTTP 401", "Invalid token"]),
        (refused(200, NOT_UNIQUE), ["http_status 422", "Violates uniqueness constraint 'name'"]),
        (refused(404, {"errors": ["Branch: x not found."]}), ["HTTP 404", "Branch: x not found."]),
        (unreachable, ["ConnectError", "Connection refused"]),
    ],
    ids=["401", "200-with-422", "404", "connect-error"],
)
def test_no_failure_holds_the_token(handler: Callable[[httpx.Request], httpx.Response], words: list[str]) -> None:
    """None is chained to an httpx exception: one carries its request, whose headers hold the key."""
    hub = connect(ENVIRON, ctl=CTL, transport=answering(handler))
    with pytest.raises(HubError) as raised:
        hub.gql("x", QUERY)
    error = raised.value
    for text in (str(error), repr(error), repr(hub)):
        assert not holds_part(text)
    assert error.__cause__ is None
    assert error.__context__ is None
    assert "\n" not in str(error)
    assert [word for word in words if word not in str(error)] == []


@pytest.mark.parametrize(
    "body",
    ["x" * 290 + TOKEN + " and the rest of the page", f"refused for the key {TOKEN}"],
    ids=["across-the-cut", "in-full"],
)
def test_a_body_that_echoes_the_token_is_cut_only_once_the_token_is_replaced(body: str) -> None:
    """A body with no errors of Infrahub's is cut at 300 characters; a token across the cut is replaced first."""
    hub = connect(ENVIRON, ctl=CTL, transport=answering(lambda request: httpx.Response(500, text=body)))
    with pytest.raises(HubError) as raised:
        hub.gql("x", QUERY)
    assert str(raised.value).startswith("POST /graphql/x answered HTTP 500: ")
    assert not holds_part(str(raised.value))


def test_rest_answers_the_response_and_refuses_an_error_status() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.params["branch"] == "nope":
            body = {"data": None, "errors": [{"message": "Branch: nope not found.", "extensions": {"code": 400}}]}
            return httpx.Response(400, json=body)
        return httpx.Response(200, json={"nodes": [], "generics": []})

    hub = connect(ENVIRON, ctl=CTL, transport=answering(handler))
    assert hub.rest("GET", "/api/schema", params={"branch": "main"}).json() == {"nodes": [], "generics": []}
    assert seen[0].headers["X-INFRAHUB-KEY"] == TOKEN
    with pytest.raises(HubError, match=r"GET /api/schema answered HTTP 400: Branch: nope not found\."):
        hub.rest("GET", "/api/schema", params={"branch": "nope"})


class Run:
    """`infrahubctl`'s fake: each call's arguments and keywords kept, and one status and output answered."""

    def __init__(self, status: int = 0, output: str = "", errors: str | None = None) -> None:
        self.status = status
        self.output = output
        self.errors = errors
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append((list(argv), kwargs))
        return subprocess.CompletedProcess(argv, self.status, stdout=self.output, stderr=self.errors)


def test_ctl_gives_the_token_in_the_childs_environment_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    environ = ENVIRON | {
        "FYLGJA_INFRAHUB_TOKEN": "a-readers-value",
        "INFRAHUB_INITIAL_ADMIN_TOKEN": "an-admins-value",
        "INFRAHUB_TIMEOUT": "5",
        "PATH": "/usr/bin:/bin",
        "HOME": "/home/someone",
    }
    run = Run(output="schema loaded\n")
    hub = connect(environ, ctl=CTL, run=run)
    hub.ctl("schema", "load", "d", "--branch", "main")
    [(argv, kwargs)] = run.calls
    assert argv == [str(CTL), "schema", "load", "d", "--branch", "main"]
    env = kwargs["env"]
    named = {name: env[name] for name in env if name.startswith(("FYLGJA_", "INFRAHUB_"))}
    assert sorted(named) == ["INFRAHUB_ADDRESS", "INFRAHUB_API_TOKEN", "INFRAHUB_TIMEOUT"]
    assert named["INFRAHUB_ADDRESS"] == ADDRESS
    assert named["INFRAHUB_API_TOKEN"] == TOKEN
    assert {name: env[name] for name in ("PATH", "HOME")} == {"PATH": "/usr/bin:/bin", "HOME": "/home/someone"}

    monkeypatch.setattr("hub.CTL_TIMEOUT_S", 7)
    hub.ctl("version")
    assert run.calls[1][1]["env"]["INFRAHUB_TIMEOUT"] == "7"

    lines = [f"line {n}" for n in range(1, 9)] + [f"Unable to read with the key {TOKEN}"]
    failing = connect(environ, ctl=CTL, run=Run(1, "\n".join(lines) + "\n"))
    with pytest.raises(HubError) as raised:
        failing.ctl("schema", "load", "d", "--branch", "main")
    sentence = str(raised.value)
    assert sentence.startswith("infrahubctl schema load d --branch main exited 1: ")
    assert sentence.endswith("Unable to read with the key <token>")
    assert "line 8" in sentence
    assert "line 1 " not in sentence
    assert not holds_part(sentence)
    assert "\n" not in sentence


@pytest.mark.parametrize(
    ("output", "errors"),
    [(f"Unable to read with the key {TOKEN[:9]}\n{TOKEN[9:]}\n", None), ("", f"error: the key {TOKEN} was refused\n")],
    ids=["folded-across-two-lines", "on-its-stderr"],
)
def test_a_childs_output_is_rid_of_the_token_before_its_lines_are_joined(output: str, errors: str | None) -> None:
    """infrahubctl's console wraps a long run of characters when piped, so the token can come back folded."""
    failing = connect(ENVIRON, ctl=CTL, run=Run(1, output, errors))
    with pytest.raises(HubError) as raised:
        failing.ctl("schema", "load", "d", "--branch", "main")
    sentence = str(raised.value)
    assert "<token>" in sentence
    assert not holds_part(sentence)


def test_a_ctl_that_cannot_start_is_one_sentence() -> None:
    def missing(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError(2, "No such file or directory", argv[0])

    hub = connect(ENVIRON, ctl=CTL, run=missing)
    with pytest.raises(HubError, match="infrahubctl could not be started") as raised:
        hub.ctl("version")
    assert raised.value.__context__ is None


def test_wait_until_returns_what_it_read_and_ends_at_its_bound_with_the_last_reasons() -> None:
    clock = Clock()
    readings = iter([1, 2, 3])
    reasons = iter([["n1: Pending"], ["n1: Pending"], []])
    read = wait_until(
        lambda: next(readings),
        lambda reading: next(reasons),
        what="n1's configuration",
        timeout_s=180,
        clock=clock,
        sleep=clock.sleep,
    )
    assert read == 3
    assert clock.slept == [2.0, 2.0]

    clock = Clock()
    with pytest.raises(HubError) as raised:
        wait_until(
            lambda: None,
            lambda reading: ["n1: Pending"],
            what="n1's configuration",
            timeout_s=180,
            clock=clock,
            sleep=clock.sleep,
        )
    assert str(raised.value) == "n1's configuration not within 180 s: n1: Pending"
    assert sum(clock.slept) <= 180
    assert clock.now == 180
