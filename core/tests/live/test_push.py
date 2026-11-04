"""The push on booted nodes: readiness, then both replaces, SR Linux's by JSON-RPC and cEOS's by
eAPI (D-015, D-027, D-028). Each re-exercises what design/verified-facts.md records for its node.

The tests share one lab and run in order: a repeat push meets what the first one landed. Each
prints the seconds it took; `-s` shows them.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import secrets
import time
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

import httpx
import pytest

from fylgja_core import node_http, platform_package, push_eapi, readiness
from fylgja_core.credentials import Credential, Provider
from fylgja_core.platform_package import PlatformPackage
from fylgja_core.push import Pushed, Refused, Unauthorized, Unreachable, post, push
from fylgja_core.push_jsonrpc import REASON_NOT_GIVEN, REASON_VALIDATES

ROOT = Path(__file__).resolve().parents[3]
SRLINUX = platform_package.load(ROOT / "psp" / "nokia_srlinux.yaml")
EOS = platform_package.load(ROOT / "psp" / "arista_eos.yaml")
PACKAGES = {"s1": SRLINUX, "e1": EOS}
MIXED = json.loads((ROOT / "testdata" / "blueprint" / "mixed.json").read_text())
CONFIG = {device["name"]: device["config"] for device in MIXED["network"]["devices"]}

PORT_99 = "set / interface ethernet-1/99 admin-state enable"  # the chassis has 58 ports; only a commit checks
VLAN_UNTAGGED = "set / interface ethernet-1/1 subinterface 0 vlan encap single-tagged vlan-id 10"  # no vlan-tagging
EOS_REFUSED = ["interface Ethernet1", "no such command"]

pytestmark = pytest.mark.skipif(
    not os.environ.get("FYLGJA_CREDENTIAL_SRLINUX_USERNAME"),
    reason="the live tier reads the node logins from the environment: load local/.env first "
    "(set -a; . local/.env; set +a)",
)


def _login(package: PlatformPackage) -> Credential:
    return Provider(os.environ).login(package.credentials)


def _timed[T](label: str, coroutine: Coroutine[Any, Any, T]) -> T:
    start = time.monotonic()
    try:
        return asyncio.run(coroutine)
    finally:
        print(f"\n{label}: {time.monotonic() - start:.2f}s", flush=True)


async def _sessions(address: str, credential: Credential) -> dict[str, Any]:
    """The node's configuration sessions, by name, from `show configuration sessions` over eAPI."""
    body = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "runCmds",
        "params": {"version": 1, "cmds": ["show configuration sessions"], "format": "json"},
    }
    url = node_http.url(address, EOS.push.port, "/command-api")
    async with node_http.client() as client:
        answer = await post(client, url, body, credential, timeout_s=EOS.push.timeout_s)
    sessions: dict[str, Any] = answer["result"][0]["sessions"]
    return sessions


async def _bad_login(address: str, package: PlatformPackage, credential: Credential) -> str:
    """What the node answers the readiness request sent with `credential`: status, type and body.

    The body is cut to 200 characters, the login's username and password replaced.
    """
    path, body = readiness.probe_request(package, credential)
    auth = httpx.BasicAuth(credential.username, credential.password)
    async with node_http.client() as client:
        response = await client.post(node_http.url(address, package.push.port, path), json=body, auth=auth)
    text = response.text.replace(credential.password, "<password>").replace(credential.username, "<username>")
    kind = response.headers.get("content-type", "no content-type")
    return f"HTTP {response.status_code}, {kind}, {len(response.content)}-byte body: {text[:200]!r}"


async def _ready_counting(address: str, package: PlatformPackage, credential: Credential, seen: list[str]) -> float:
    """Readiness for `credential`, counting the requests it sends, within 15 s."""

    async def count(request: httpx.Request) -> None:
        seen.append(request.url.path)

    async with node_http.client() as client:
        client.event_hooks = {"request": [count]}
        return await readiness.await_transport(address, package, credential, timeout_s=15, client=client)


@pytest.fixture(scope="session")
def ready(nodes: dict[str, str]) -> dict[str, float]:
    """Each node's seconds from the lab's addresses being read to its push transport's first answer."""

    async def wait() -> list[float]:
        return await asyncio.gather(
            *(readiness.await_transport(nodes[name], package, _login(package)) for name, package in PACKAGES.items())
        )

    return dict(zip(PACKAGES, asyncio.run(wait()), strict=True))


def test_each_node_answers_its_readiness_request_within_its_package_budget(ready: dict[str, float]) -> None:
    for name, seconds in ready.items():
        package, budget = PACKAGES[name], PACKAGES[name].readiness.timeout_s
        print(f"\n{name} answered {package.push.delivery} {seconds:.1f}s after the deploy (budget {budget}s)")
        assert seconds <= budget


def test_the_srlinux_replace_lands_and_a_repeat_changes_nothing(nodes: dict[str, str], ready: dict[str, float]) -> None:
    credential = _login(SRLINUX)
    first = _timed("s1 replace", push(nodes["s1"], SRLINUX, CONFIG["s1"], credential))
    assert isinstance(first, Pushed), first
    print(f"s1 diff: {len(first.diff.splitlines())} lines; the request {first.duration_s:.2f}s")
    assert "host-name s1" in first.diff
    again = _timed("s1 repeat", push(nodes["s1"], SRLINUX, CONFIG["s1"], credential))
    assert isinstance(again, Pushed), again
    assert again.diff == ""


def test_the_eos_replace_lands_and_a_repeat_changes_nothing(nodes: dict[str, str], ready: dict[str, float]) -> None:
    credential = _login(EOS)
    first = _timed("e1 replace", push(nodes["e1"], EOS, CONFIG["e1"], credential))
    assert isinstance(first, Pushed), first
    print(f"e1 diff: {len(first.diff.splitlines())} lines; the request {first.duration_s:.2f}s")
    assert first.diff != "" and "ip routing" in first.diff
    again = _timed("e1 repeat", push(nodes["e1"], EOS, CONFIG["e1"], credential, attempt=2))
    assert isinstance(again, Pushed), again
    assert again.diff == ""


def test_srlinux_refusals_answer_a_reason_and_a_good_push_still_lands(
    nodes: dict[str, str], ready: dict[str, float]
) -> None:
    credential = _login(SRLINUX)
    port = _timed("s1 refused, port 99", push(nodes["s1"], SRLINUX, f"{CONFIG['s1']}\n{PORT_99}\n", credential))
    assert isinstance(port, Refused), port
    print(f"s1 port 99 refusal: {port.message}")
    assert port.message in (REASON_VALIDATES, REASON_NOT_GIVEN) or "port 99" in port.message
    vlan = _timed("s1 refused, vlan", push(nodes["s1"], SRLINUX, f"{CONFIG['s1']}\n{VLAN_UNTAGGED}\n", credential))
    assert isinstance(vlan, Refused), vlan
    print(f"s1 vlan refusal: {vlan.message}")
    assert "vlan" in vlan.message
    good = _timed("s1 replace after the refusals", push(nodes["s1"], SRLINUX, CONFIG["s1"], credential))
    assert isinstance(good, Pushed), good
    assert "ethernet-1/99" not in good.diff and "vlan" not in good.diff  # neither refused line landed


def test_an_eos_refusal_names_the_command_and_leaves_no_session(nodes: dict[str, str], ready: dict[str, float]) -> None:
    credential = _login(EOS)
    config = "\n".join([CONFIG["e1"], *EOS_REFUSED, ""])
    refused = _timed("e1 refused", push(nodes["e1"], EOS, config, credential, attempt=3))
    assert isinstance(refused, Refused), refused
    print(f"e1 refusal: {refused.message}")
    number = len(push_eapi.commands(config, "any")) - 2  # the refused line, before the diff and the commit
    assert refused.message.startswith(f"command {number} ('no such command') refused: ")
    sessions = _timed("e1 sessions", _sessions(nodes["e1"], credential))
    assert not [name for name in sessions if name.startswith("fylgja-")], sessions


@pytest.mark.parametrize("name", list(PACKAGES))
def test_a_wrong_password_is_refused_at_the_first_attempt_and_the_push_is_unauthorized(
    name: str, nodes: dict[str, str], ready: dict[str, float]
) -> None:
    package, address = PACKAGES[name], nodes[name]
    real = _login(package)
    wrong = Credential(username=real.username, password=f"wrong-{secrets.token_hex(4)}")
    print(f"\n{name} answered a wrong login: {_timed(f'{name} wrong login', _bad_login(address, package, wrong))}")
    seen: list[str] = []
    with pytest.raises(readiness.NotReady) as e:
        _timed(f"{name} readiness, wrong login", _ready_counting(address, package, wrong, seen))
    assert e.value.rule == readiness.RULE_UNAUTHORIZED == "readiness.unauthorized" and len(seen) == 1
    with pytest.raises(Unauthorized) as refused:
        _timed(f"{name} push, wrong login", push(address, package, CONFIG[name], wrong))
    assert wrong.password not in str(refused.value)  # never the real one: a failed assert would print it
    again = _timed(f"{name} readiness, the real login after", readiness.await_transport(address, package, real))
    print(f"{name} still answers the real login: {again:.1f}s")


@pytest.mark.parametrize("package", [SRLINUX, EOS], ids=["json_rpc", "eapi"])
def test_a_push_to_a_closed_port_is_unreachable(package: PlatformPackage) -> None:
    closed = dataclasses.replace(package, push=dataclasses.replace(package.push, port=1))
    with pytest.raises(Unreachable) as e:
        _timed(f"{package.push.delivery} to a closed port", push("127.0.0.1", closed, "x", _login(package)))
    assert "127.0.0.1:1" in e.value.message
