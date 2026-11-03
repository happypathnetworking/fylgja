"""Per-client bearer tokens mapped to principals (D-025).

The tokens file holds one `<sha256 hex of the token> <principal>` per line, blank lines and
`#` comments left out, so the file never holds a token itself and several are valid at once.
`AuthMiddleware` reads `Authorization: Bearer <token>`, sets `scope["state"]["principal"]`
(Starlette's `request.state.principal`), or answers the 401 problem.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from starlette.types import ASGIApp, Receive, Scope, Send

from fylgja_core.server import problems

RULE_MISSING = "auth.token.missing"
RULE_UNKNOWN = "auth.token.unknown"

# The one call that needs no token: a client asks which API version it speaks.
_HASH = re.compile(r"[0-9a-f]{64}")
EXEMPT = ("GET", "/v1/version")


def hash_token(token: str) -> str:
    """The sha256 hex of the token's UTF-8: what the tokens file holds."""
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class Tokens:
    """Token hashes and the principal each maps to."""

    principals: dict[str, str]

    @classmethod
    def load(cls, path: Path) -> Tokens:
        """The tokens file at `path`; a bad line is a ValueError naming the file and line, never the content."""
        principals: dict[str, str] = {}
        seen: dict[str, int] = {}
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) != 2:
                raise ValueError(f"{path} line {number}: expected a token hash and a principal")
            if not _HASH.fullmatch(parts[0]):
                raise ValueError(f"{path} line {number}: the first field is not a sha256 hash in lowercase hex")
            if parts[0] in seen:
                raise ValueError(f"{path} lines {seen[parts[0]]} and {number}: the same token hash twice")
            seen[parts[0]] = number
            principals[parts[0]] = parts[1]
        return cls(principals)

    def principal(self, token: str) -> str | None:
        """The principal `token` belongs to, or None."""
        return self.principals.get(hash_token(token))


class AuthMiddleware:
    """A pure ASGI middleware: a known bearer token's principal, or the 401 problem."""

    def __init__(self, app: ASGIApp, tokens: Tokens) -> None:
        self.app = app
        self.tokens = tokens

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan" or (scope["type"] == "http" and (scope["method"], scope["path"]) == EXEMPT):
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            # Fail closed: no other scope (a websocket) is authenticated, so none is served.
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            return
        headers = dict(scope["headers"])
        scheme, _, token = headers.get(b"authorization", b"").decode("latin-1").partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            response = problems.problem(
                401, RULE_MISSING, "no bearer token in the Authorization header", instance=scope["path"]
            )
        elif (principal := self.tokens.principal(token.strip())) is None:
            response = problems.problem(401, RULE_UNKNOWN, "the bearer token is not known", instance=scope["path"])
        else:
            scope.setdefault("state", {})["principal"] = principal
            await self.app(scope, receive, send)
            return
        await response(scope, receive, send)
