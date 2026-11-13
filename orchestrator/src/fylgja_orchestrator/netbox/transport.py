"""The change source's transport: its own few requests to NetBox, over plain HTTP and httpx, with no client library of
NetBox's (D-096, D-097).

The reader writes nothing, and the source must write a journal entry and a branch's tags, so it speaks for itself
here: `GET`, `POST` and `PATCH` of NetBox's REST API under `/api/`, each with no `X-NetBox-Branch` header, since a
branch object, its tags and its journal entries live on `main`. A list is read `PAGE` at a time, by `limit` and the
offset of what was read, until it holds the `count` NetBox answered; NetBox's `next` is never followed, since it holds
NetBox's own address, nor is a redirect (design/verified-facts.md, "NetBox 4.7.5 with netbox-branching 1.2.3"). Every
request is given 30 s, 5 s of them to connect, and reads no proxy or certificate from the environment; the token is
sent in the one header `Authorization`, as NetBox's v2 token is, checked by the client's bearer rule before any request
so that no HTTP library's complaint can quote it.

Every failure is a `SourceError` saying what was asked. A token refused, HTTP 401 or 403, is `refused_token`'s
sentence by its status, the call named, quoting nothing of the answer and naming no variable, which the source gives
for the reader's too: NetBox answers 403 both to a token it never made and to an account that may not do what was
asked, and the source is given its token by whoever runs it, who names where they read it from. Any other status
outside 200 to 299 quotes NetBox's words, cut at `QUOTED` characters, the token and each half of it replaced first.
None holds the token, and one of httpx's is raised from nothing, since an httpx exception carries its request, whose
headers hold it.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx
from fylgja_core.client import base_url, bearer, trust
from fylgja_netbox import redact

Wire = httpx.BaseTransport
"""What replaces the network, for tests: an httpx transport."""

TIMEOUT = httpx.Timeout(30.0, connect=5.0)
"""What one request is given: 30 s, 5 s of them to connect."""

PAGE = 100
"""How many rows one request of a list asks for: NetBox answered a page of 100 whole (design/verified-facts.md)."""

QUOTED = 500
"""How many characters of NetBox's words an error quotes."""

REFUSED = (401, 403)
"""The statuses of a token NetBox refused: 401, no valid token; 403, a token NetBox never made, or an account that may
not do what was asked."""

type Param = str | tuple[str, ...]
"""A query parameter's value: a string, or a tuple of them, each sent once under the one name."""


class SourceError(Exception):
    """NetBox refused what the source asked, answered what is no answer, or was not reached; or what it answered
    cannot be a change's. The text says what was asked, and holds no token. `status` is the status NetBox answered
    where it answered one that refused the request, and None where it answered none, or one that is no answer."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def refused_token(call: str, status: int, url: str) -> str:
    """The sentence of a token NetBox refused for `call`, by its status alone, whichever connection sent it: a 401, the
    token refused; a 403, the token refused or its account lacking a permission the call requires, which NetBox
    answers alike. No variable is named, since the source is given its token by whoever runs it, who names it (the
    edge, as for the Infrahub source), and nothing of NetBox's answer is quoted."""
    if status == 401:
        return f"{call}: NetBox refused the change source's token: HTTP 401 from NetBox at {url}"
    return (
        f"{call}: NetBox refused the change source's token, or its account may not do this: HTTP {status} from "
        f"NetBox at {url}"
    )


class Transport:
    """One NetBox, asked through one pool of connections with one token. Made with no request: the address and the
    CA are read by the core's client rules (`InvalidAddress`, `InvalidCA`) and the token by its bearer rule
    (`InvalidToken`), each a predicate that repeats nothing; `transport` replaces the network, for tests."""

    def __init__(self, address: str, token: str, *, ca: Path | None = None, transport: Wire | None = None) -> None:
        self._url = base_url(address)
        self._token = token
        self._http = httpx.Client(
            base_url=f"{self._url.rstrip('/')}/api/",
            headers={"Authorization": bearer(token), "Accept": "application/json"},
            transport=transport,
            verify=trust(ca),
            timeout=TIMEOUT,
            trust_env=False,
        )

    def __repr__(self) -> str:
        """Neither the token nor the address, which may hold a login."""
        return "Transport()"

    @property
    def url(self) -> str:
        """The URL NetBox is asked at, as `base_url` made it."""
        return self._url

    def close(self) -> None:
        self._http.close()

    def get(self, path: str, **params: Param) -> dict[str, Any]:
        """The object NetBox answers `GET /api/<path>` with `params` as its query."""
        return self._send("GET", path, params=params)

    def listed(self, path: str, **params: Param) -> list[dict[str, Any]]:
        """Every row of the list at `/api/<path>` that `params` ask, read `PAGE` at a time by `limit` and the offset of
        the rows read so far, until they are the `count` NetBox answered. A `SourceError` where a page answers no count
        and results, a row is no object, the count moves between pages, or the rows are fewer or more than it: a list
        read in part could hide a mark."""
        what = f"listing /api/{path.lstrip('/')}"
        rows: list[dict[str, Any]] = []
        count: int | None = None
        while True:
            answer = self.get(path, **params, limit=str(PAGE), offset=str(len(rows)))
            answered, results = answer.get("count"), answer.get("results")
            if type(answered) is not int or not isinstance(results, list):
                raise SourceError(f"{what}: HTTP 200: answered no count and results")
            if count is not None and answered != count:
                raise SourceError(f"{what}: NetBox counted {count} rows, then {answered}")
            count = answered
            if not all(isinstance(row, dict) for row in results):
                raise SourceError(f"{what}: HTTP 200: answered a row that is no object")
            rows.extend(results)
            if not results or len(rows) >= count:
                break
        if len(rows) != count:
            raise SourceError(f"{what}: NetBox answered {len(rows)} of the {count} rows it counted")
        return rows

    def post(self, path: str, body: Mapping[str, Any]) -> dict[str, Any]:
        """The object NetBox answers `POST /api/<path>` of `body`."""
        return self._send("POST", path, body=body)

    def patch(self, path: str, body: Mapping[str, Any]) -> dict[str, Any]:
        """The object NetBox answers `PATCH /api/<path>` of `body`."""
        return self._send("PATCH", path, body=body)

    def _send(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Param] | None = None,
        body: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """The one sender: NetBox's answer as a JSON object; anything else a `SourceError` of what was asked."""
        what = f"{method} /api/{path.lstrip('/')}"
        query: list[tuple[str, str | int | float | bool | None]] = [
            (name, member) for name, value in (params or {}).items()
            for member in (value if isinstance(value, tuple) else (value,))
        ]
        failure: SourceError | None = None
        try:
            response = self._http.request(method, path.lstrip("/"), params=query,
                                          json=dict(body) if body is not None else None)
        except httpx.HTTPError as e:
            # Hidden before it is bound: the exception's text can hold the token, and a traceback can show its locals.
            failure = SourceError(self._hide(f"{what}: NetBox at {self._url} was not reached: {type(e).__name__}: {e}"))
        if failure is not None:
            # Raised outside the handler, so that the error carries no context, whose request holds the token.
            raise failure
        status = response.status_code
        if status in REFUSED:
            raise SourceError(refused_token(what, status, self._url), status=status)
        if 300 <= status <= 399:
            raise SourceError(f"{what}: HTTP {status}: {_moved(response)}", status=status)
        if not 200 <= status <= 299:
            raise SourceError(f"{what}: HTTP {status}: {self._words(response)}", status=status)
        try:
            answer = json.loads(response.content)
        except ValueError:
            answer = None
        if not isinstance(answer, dict):
            raise SourceError(f"{what}: HTTP {status}: answered no JSON object")
        return answer

    def _words(self, response: httpx.Response) -> str:
        """NetBox's own words in a refusal: its `detail` where the body carries one, else the body, the token replaced
        and then cut at `QUOTED` characters, so that no part of it is left at the cut."""
        body = None
        with contextlib.suppress(ValueError):
            body = json.loads(response.content)
        if isinstance(body, dict) and isinstance(body.get("detail"), str):
            text = body["detail"]
        elif body is not None:
            text = json.dumps(body)
        else:
            text = response.text
        said = self._hide(text)[:QUOTED]
        return said if said else "an empty body"

    def _hide(self, text: str) -> str:
        """`text` with the token, and each half of it, replaced, on one line."""
        return " ".join(redact(text, self._token).split())


def _moved(response: httpx.Response) -> str:
    """Where a redirect points, by its `Location`'s path alone, never its host or its query."""
    location = response.headers.get("Location")
    try:
        path = httpx.URL(location).path if location else ""
    except httpx.InvalidURL:
        path = ""
    return f"a redirect to {path}" if path else "a redirect with no Location"
