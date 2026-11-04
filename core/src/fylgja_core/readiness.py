"""Readiness: a node is ready when its push transport answers an authenticated request (D-015).

One wait per node. The mechanism is the platform package's `push.delivery`; the module reaches
a node by its management address and names no runtime and no vendor.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

from fylgja_core import node_http
from fylgja_core.credentials import Credential
from fylgja_core.platform_package import PlatformPackage

RULE_TIMEOUT = "readiness.timeout"
RULE_UNAUTHORIZED = "readiness.unauthorized"

_log = logging.getLogger("fylgja.readiness")


class NotReady(Exception):
    """A node did not become ready: `rule` is `readiness.timeout` or `readiness.unauthorized`.

    `readiness.timeout` fails the ready phase. `readiness.unauthorized` will not clear by
    waiting: the node refuses the login.
    """

    def __init__(self, rule: str, message: str) -> None:
        self.rule = rule
        self.message = message
        super().__init__(f"{rule}: {message}")


def probe_request(package: PlatformPackage, credential: Credential) -> tuple[str, dict[str, Any]]:
    """The path and JSON body one readiness attempt sends: `show version` by the package's delivery."""
    del credential  # the login travels as basic auth, never in the body
    if package.push.delivery == "json_rpc":
        return "/jsonrpc", {"jsonrpc": "2.0", "id": 1, "method": "cli", "params": {"commands": ["show version"]}}
    return "/command-api", {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "runCmds",
        "params": {"version": 1, "cmds": ["show version"], "format": "json"},
    }


def _answered(response: httpx.Response) -> bool:
    if response.status_code != 200:
        return False
    try:
        body = response.json()
    except ValueError:
        return False
    return isinstance(body, dict) and "result" in body


async def await_transport(
    address: str,
    package: PlatformPackage,
    credential: Credential,
    *,
    timeout_s: float | None = None,
    interval_s: float = 2.0,
    client: httpx.AsyncClient | None = None,
) -> float:
    """Wait until the node's push transport answers; return the seconds until the first answer.

    Raises `NotReady` at once on a refused login, and when the budget runs out.

    An attempt gives the connection `interval_s * 2`, since a port not yet open refuses at once,
    and the answer the push's own per-request budget within what is left of the wait's: a
    `json_rpc` node takes 3.2-4.4 s to answer `show version` over `cli` (the facts file,
    design/verified-facts.md).
    """
    budget = package.readiness.timeout_s if timeout_s is None else timeout_s
    path, body = probe_request(package, credential)
    url = node_http.url(address, package.push.port, path)
    where = node_http.authority(address, package.push.port)
    auth = httpx.BasicAuth(credential.username, credential.password)
    own = client is None
    http = client if client is not None else node_http.client()
    start = time.monotonic()
    attempt = 0
    try:
        while True:
            attempt += 1
            answer_s = max(interval_s, min(package.push.timeout_s, budget - (time.monotonic() - start)))
            try:
                response = await http.post(
                    url, json=body, auth=auth, timeout=httpx.Timeout(answer_s, connect=interval_s * 2)
                )
            except httpx.HTTPError as err:
                _log.debug("attempt %d to %s: %s", attempt, url, type(err).__name__)
            else:
                if response.status_code in (401, 403):
                    raise NotReady(RULE_UNAUTHORIZED, f"{where} refused the login")
                if _answered(response):
                    return time.monotonic() - start
                _log.debug("attempt %d to %s: HTTP %d", attempt, url, response.status_code)
            if time.monotonic() - start + interval_s > budget:
                raise NotReady(
                    RULE_TIMEOUT,
                    f"{where} did not answer within {budget:g}s",
                )
            await asyncio.sleep(interval_s)
    finally:
        if own:
            await http.aclose()
