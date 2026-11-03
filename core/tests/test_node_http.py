"""How the core reaches a node over HTTP: one client recipe and one URL rule, used by readiness and the push."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from fylgja_core import node_http, platform_package, readiness
from fylgja_core.credentials import Credential
from fylgja_core.push import Pushed, push

PSP = Path(__file__).resolve().parents[2] / "psp"
SRLINUX = platform_package.load(PSP / "nokia_srlinux.yaml")
EOS = platform_package.load(PSP / "arista_eos.yaml")
CRED = Credential(username="admin", password="s3cret")


@pytest.mark.parametrize(
    ("address", "expected"),
    [("10.0.0.5", "https://10.0.0.5:443/jsonrpc"), ("fd00::5", "https://[fd00::5]:443/jsonrpc")],
    ids=["ipv4", "ipv6"],
)
def test_a_nodes_url_brackets_an_ipv6_address(address: str, expected: str) -> None:
    assert node_http.url(address, 443, "/jsonrpc") == expected
    assert node_http.authority(address, 443) == expected.removeprefix("https://").removesuffix("/jsonrpc")


def test_the_client_takes_nothing_from_the_environment() -> None:
    async def run() -> bool:
        async with node_http.client() as client:
            return client.trust_env

    assert asyncio.run(run()) is False


def test_readiness_and_the_push_build_their_client_by_the_one_recipe(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"result": []})

    monkeypatch.setattr(node_http, "client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    asyncio.run(readiness.await_transport("fd00::5", SRLINUX, CRED, interval_s=0.01))
    for package in (SRLINUX, EOS):
        assert isinstance(asyncio.run(push("fd00::5", package, "x", CRED)), Pushed)
    assert [(r.url.host, r.url.path) for r in seen] == [
        ("fd00::5", "/jsonrpc"),
        ("fd00::5", "/jsonrpc"),
        ("fd00::5", "/command-api"),
    ]
