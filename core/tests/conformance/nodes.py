"""What a scenario asks a node itself, at the address the twin record gives it, through the
node's own push transport and the login the environment holds: SR Linux's JSON-RPC and EOS's
eAPI. A scenario asks only where the driver's `access` is `direct`, the address then reaching
the node from the test's host.

Nothing here shows the address: a print names the node, and a node that gives no answer, or
refuses the login, fails by the push's exception type alone, since its message names the URL,
raised again in a frame that holds the address in no argument.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Iterator
from typing import Any

from conformance.reads import ROOT
from fylgja_core import node_http, platform_package, push_eapi
from fylgja_core.credentials import Provider
from fylgja_core.push import Unauthorized, Unreachable, post

SRLINUX = platform_package.load(ROOT / "psp" / "nokia_srlinux.yaml")
EOS = platform_package.load(ROOT / "psp" / "arista_eos.yaml")


def _srlinux(address: str, body: dict[str, Any]) -> dict[str, Any]:
    """`body`, a JSON-RPC request, sent to SR Linux at `address` with its login: the answer."""
    credential = Provider(os.environ).login(SRLINUX.credentials)  # its repr hides the password

    async def ask() -> dict[str, Any]:
        async with node_http.client() as client:
            url = node_http.url(address, SRLINUX.push.port, "/jsonrpc")
            try:
                return await post(client, url, body, credential, timeout_s=SRLINUX.push.timeout_s)
            except (Unreachable, Unauthorized) as e:  # Timeout too; by its type alone: its message names the URL
                raise type(e)(f"{type(e).__name__} at the record's address") from None

    return asyncio.run(ask())


def host_name(address: str, node: str) -> str:
    """The host name of the node `node` at `address`, read through its own push transport: a
    JSON-RPC `cli` request."""
    body = {"jsonrpc": "2.0", "id": 1, "method": "cli",
            "params": {"commands": ["info from running / system name host-name"], "output-format": "text"}}
    answer = _srlinux(address, body)
    assert "error" not in answer, answer
    entries = answer["result"]
    print(f"[conformance] {node}'s answer: a {type(entries).__name__} of {[type(e).__name__ for e in entries]}: "
          f"{entries!r:.120}", flush=True)
    text = "\n".join(e if isinstance(e, str) else json.dumps(e) for e in entries)
    found = re.search(r"host-name (\S+)", text)
    assert found, entries
    return found.group(1)


def srlinux_get(address: str, path: str, datastore: str) -> Any:
    """`path` read from SR Linux's `datastore` through its push transport, a JSON-RPC `get`: the
    answer's result."""
    body = {"jsonrpc": "2.0", "id": 1, "method": "get",
            "params": {"commands": [{"path": path, "datastore": datastore}]}}
    answer = _srlinux(address, body)
    assert "error" not in answer, answer
    return answer["result"]


def objects(value: Any) -> Iterator[dict[str, Any]]:
    """Every JSON object within `value`, outermost first."""
    if isinstance(value, dict):
        yield value
        for inner in value.values():
            yield from objects(inner)
    elif isinstance(value, list):
        for inner in value:
            yield from objects(inner)


def srlinux_described(address: str, port: str) -> Any:
    """`port`'s description in SR Linux's running configuration, None when it has none: only a
    pushed configuration sets one, the kind's baseline none."""
    found = srlinux_get(address, f"/interface[name={port}]", "running")
    print(f"[conformance] {port} in the running configuration: {found!r:.200}", flush=True)
    return next((o["description"] for o in objects(found) if "description" in o), None)


def srlinux_neighbours(address: str, port: str) -> list[tuple[str, str]]:
    """The LLDP neighbours SR Linux lists on `port`, read from its state through its push
    transport (a JSON-RPC `get`): each one's `system-name` and `port-id`."""
    found = srlinux_get(address, f"/system/lldp/interface[name={port}]/neighbor", "state")
    neighbours = [o for o in objects(found) if "system-name" in o]
    print(f"[conformance] {port}'s LLDP neighbours, as SR Linux lists them: "
          f"{[{k: n.get(k) for k in ('system-name', 'port-id', 'port-id-type')} for n in neighbours]}", flush=True)
    return [(str(n["system-name"]), str(n.get("port-id"))) for n in neighbours]


def eos_answer(address: str, command: str, format: str = "text") -> dict[str, Any]:
    """`command` in EOS's CLI on the node at `address`, through eAPI's `runCmds` as the push sends
    it (`push_eapi.request`), with the EOS login, answered in `format` (`text` or `json`): the
    whole JSON-RPC answer, its `result` or the node's `error`, for a scenario that reads a refusal
    or waits one out."""
    body = push_eapi.request([command])
    body["params"]["format"] = format
    credential = Provider(os.environ).login(EOS.credentials)  # its repr hides the password

    async def ask() -> dict[str, Any]:
        async with node_http.client() as client:
            url = node_http.url(address, EOS.push.port, "/command-api")
            try:
                return await post(client, url, body, credential, timeout_s=EOS.push.timeout_s)
            except (Unreachable, Unauthorized) as e:  # Timeout too; by its type alone: its message names the URL
                raise type(e)(f"{type(e).__name__} at the record's address") from None

    return asyncio.run(ask())


def eos(address: str, command: str, format: str = "text") -> Any:
    """`eos_answer`'s command entry of the result, `{"output": ...}` for text. A node's refusal
    fails the test."""
    answer = eos_answer(address, command, format)
    assert "error" not in answer, answer["error"]
    return answer["result"][0]
