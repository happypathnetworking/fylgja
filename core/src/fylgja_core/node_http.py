"""How the core reaches a node over HTTP: the client it builds, and a node's URL.

The client accepts the node's boot-time certificate unverified, as the platform packages
state, and reads no proxy or certificate setting from the environment, so a host's
`HTTPS_PROXY` never routes a request meant for a node. An IPv6 management address is
bracketed in a URL.
"""

from __future__ import annotations

import httpx


def client() -> httpx.AsyncClient:
    """A client for node requests: the certificate unverified, nothing taken from the environment."""
    return httpx.AsyncClient(verify=False, trust_env=False)


def authority(address: str, port: int) -> str:
    """`address:port`, the address bracketed when it is IPv6."""
    host = f"[{address}]" if ":" in address else address
    return f"{host}:{port}"


def url(address: str, port: int, path: str) -> str:
    """The HTTPS URL of `path` on the node at `address`."""
    return f"https://{authority(address, port)}{path}"
