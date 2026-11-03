"""The push: a node gets exactly the configuration its source rendered, by a replace (D-027).

A replace resets the node to the baseline its containerlab kind left, sends the configuration's
lines and commits once. What a step records of the change is the device's own diff, and Fylgja
never saves the running configuration. The mechanism is the platform package's `push.delivery`
(D-014): `json_rpc` is `push_jsonrpc`, `eapi` is `push_eapi`. The module reaches a node by its
management address and names no runtime and no vendor.

Nothing logged or raised quotes a request or an answer, which echo the configuration, or the
password: a log line names the address, the mechanism, the command count, the duration and a
refusal's reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from fylgja_core.credentials import Credential
from fylgja_core.platform_package import PlatformPackage

RULE_REFUSED = "push.refused"
RULE_UNREACHABLE = "push.unreachable"


@dataclass(frozen=True)
class Pushed:
    """The replace committed: `diff` is the device's diff of it, `duration_s` the request's seconds."""

    diff: str
    duration_s: float


@dataclass(frozen=True)
class Refused:
    """The node refused the replace, and nothing landed: `message` is the node's reason."""

    message: str
    rule: str = RULE_REFUSED


class Unreachable(Exception):
    """The node gave the push no answer: refused connection, TLS failure, timeout, no JSON-RPC answer.

    Transient: the loop pushes again. The message names the URL, never a body.
    """

    rule = RULE_UNREACHABLE

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(f"{RULE_UNREACHABLE}: {message}")


def lines(config: str) -> list[str]:
    """The configuration's non-empty lines, each sent as it is."""
    return [line for line in config.split("\n") if line.strip()]


async def push(
    address: str,
    package: PlatformPackage,
    config: str,
    credential: Credential,
    *,
    attempt: int = 1,
    client: httpx.AsyncClient | None = None,
) -> Pushed | Refused:
    """Replace the node's configuration with `config` by the package's delivery; `Unreachable` on no answer.

    `attempt` numbers this push among the loop's tries of it.
    """
    from fylgja_core import push_jsonrpc  # the mechanisms import this module's types

    own = client is None
    http = client if client is not None else httpx.AsyncClient(verify=False)  # boot-time certificate, unverified
    try:
        if package.push.delivery == "json_rpc":
            return await push_jsonrpc.replace(address, package, config, credential, client=http)
        raise NotImplementedError(f"the {package.push.delivery} replace is not built yet")
    finally:
        if own:
            await http.aclose()


async def post(
    client: httpx.AsyncClient, url: str, body: dict[str, Any], credential: Credential, *, timeout_s: float
) -> dict[str, Any]:
    """POST one JSON-RPC request with basic auth; the answer, a JSON object with an `error` or a `result`.

    A transport failure, a status other than 200 or a body that is no such answer is `Unreachable`.
    """
    auth = httpx.BasicAuth(credential.username, credential.password)
    try:
        response = await client.post(url, json=body, auth=auth, timeout=timeout_s)
    except httpx.TransportError as err:
        detail = f": {err}" if str(err) else ""
        raise Unreachable(f"{url} gave no answer: {type(err).__name__}{detail}") from err
    if response.status_code != 200:
        raise Unreachable(f"{url} answered HTTP {response.status_code}")
    try:
        answer = response.json()
    except ValueError:
        answer = None
    if not isinstance(answer, dict) or (answer.get("error") is None and "result" not in answer):
        raise Unreachable(f"{url} answered HTTP 200 with no JSON-RPC answer")
    return answer
