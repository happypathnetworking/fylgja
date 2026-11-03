"""Readiness: one wait per node, asking its push transport until it answers or the budget ends."""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

import httpx
import pytest

from fylgja_core import platform_package
from fylgja_core.credentials import Credential
from fylgja_core.platform_package import PlatformPackage
from fylgja_core.readiness import RULE_TIMEOUT, RULE_UNAUTHORIZED, NotReady, await_transport, probe_request

PSP = Path(__file__).resolve().parents[2] / "psp"
SRLINUX = platform_package.load(PSP / "nokia_srlinux.yaml")
EOS = platform_package.load(PSP / "arista_eos.yaml")
CRED = Credential(username="admin", password="s3cret")


def _wait(
    package: PlatformPackage, handler: httpx.MockTransport, *, interval_s: float, timeout_s: float | None = None
) -> float:
    async def run() -> float:
        async with httpx.AsyncClient(transport=handler) as client:
            return await await_transport(
                "10.0.0.5", package, CRED, timeout_s=timeout_s, interval_s=interval_s, client=client
            )

    return asyncio.run(run())


def test_the_probe_request_is_the_packages_delivery() -> None:
    assert probe_request(SRLINUX, CRED) == (
        "/jsonrpc",
        {"jsonrpc": "2.0", "id": 1, "method": "cli", "params": {"commands": ["show version"]}},
    )
    assert probe_request(EOS, CRED) == (
        "/command-api",
        {
            "jsonrpc": "2.0",
            "id": "1",
            "method": "runCmds",
            "params": {"version": 1, "cmds": ["show version"], "format": "json"},
        },
    )


@pytest.mark.parametrize("package", [SRLINUX, EOS], ids=["json_rpc", "eapi"])
def test_an_attempt_posts_the_probe_with_basic_auth_and_ready_is_a_200_with_a_result(
    package: PlatformPackage,
) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"result": []})

    elapsed = _wait(package, httpx.MockTransport(handler), interval_s=0.01)
    path, body = probe_request(package, CRED)
    assert elapsed >= 0 and len(seen) == 1
    req = seen[0]
    assert req.method == "POST" and (
        req.url.scheme,
        req.url.host,
        req.url.port or package.push.port,
        req.url.path,
    ) == ("https", "10.0.0.5", package.push.port, path)
    assert json.loads(req.content) == body
    assert req.headers["authorization"] == "Basic " + base64.b64encode(b"admin:s3cret").decode()


def test_connection_errors_are_retried_until_the_node_answers() -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) <= 2:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json={"result": []})

    _wait(SRLINUX, httpx.MockTransport(handler), interval_s=0.01)
    assert len(attempts) == 3


def test_an_answer_without_a_result_is_not_ready() -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(200, json={"error": "booting"})
        if len(attempts) == 2:
            return httpx.Response(503)
        return httpx.Response(200, json={"result": [{}]})

    _wait(SRLINUX, httpx.MockTransport(handler), interval_s=0.01)
    assert len(attempts) == 3


@pytest.mark.parametrize("status", [401, 403])
def test_a_refused_login_fails_at_once_and_is_not_retried(status: int) -> None:
    attempts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        attempts.append(1)
        return httpx.Response(status)

    with pytest.raises(NotReady) as e:
        _wait(SRLINUX, httpx.MockTransport(handler), interval_s=0.01)
    assert e.value.rule == RULE_UNAUTHORIZED == "readiness.unauthorized" and len(attempts) == 1


def test_a_node_that_never_answers_times_out_naming_the_address_the_port_and_the_budget() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(NotReady) as e:
        _wait(SRLINUX, httpx.MockTransport(handler), timeout_s=0.3, interval_s=0.1)
    assert e.value.rule == RULE_TIMEOUT == "readiness.timeout"
    assert "10.0.0.5" in e.value.message and "443" in e.value.message and "0.3" in e.value.message
