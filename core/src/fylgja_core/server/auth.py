"""Per-client bearer tokens mapped to principals (D-025).

The tokens file holds one `<sha256 hex of the token> <principal>` per line, blank lines and
`#` comments left out, so the file never holds a token itself and several are valid at once.
`AuthMiddleware` reads `Authorization: Bearer <token>`, sets `scope["state"]["principal"]`
(Starlette's `request.state.principal`), or answers the 401 problem.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from starlette.types import ASGIApp, Receive, Scope, Send

from fylgja_core.server import problems

RULE_MISSING = "auth.token.missing"
RULE_UNKNOWN = "auth.token.unknown"

# The one call that needs no token: a client asks which API version it speaks.
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
        """The tokens file at `path`; a line that is not `<hash> <principal>` is a ValueError naming its number."""
        principals: dict[str, str] = {}
        for number, line in enumerate(path.read_text().splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) != 2:
                raise ValueError(f"{path} line {number}: expected a token hash and a principal")
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
        if scope["type"] != "http" or (scope["method"], scope["path"]) == EXEMPT:
            await self.app(scope, receive, send)
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
