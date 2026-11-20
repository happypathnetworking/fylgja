"""Everything that seeds the development Nautobot: one httpx transport over its REST API.

`Box` is given the address and the superuser's token, `FYLGJA_NAUTOBOT_ADDRESS` and `FYLGJA_NAUTOBOT_WRITE_TOKEN`
where the seed and the account read them (D-042); it has no default address and makes no request until it is asked
one. Every path is relative to `<address>/api/` and every request carries the token as `Authorization: Token <token>`
(design/verified-facts.md, "Nautobot 3.2.8 with Golden Config 3.0.8"). Nautobot has no branch to write under, so
nothing here selects one.

Every failure is a `BoxError` of one sentence, built here with the token and each value a caller hands `hide`
replaced before Nautobot's words are cut; none is chained to the exception it came from: an httpx exception carries
its request, whose headers hold the token. A token a header cannot carry is refused before a client is made, since
httpx would print it in a `repr` no replacement matches.

Run by `core/.venv/bin/python`; httpx and the standard library alone, never `fylgja_core`, a reader, the example or a
client library of Nautobot's.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import httpx

ADDRESS = "FYLGJA_NAUTOBOT_ADDRESS"
TOKEN = "FYLGJA_NAUTOBOT_WRITE_TOKEN"

PAGE = 50
"""Rows asked of Nautobot a page, by `limit` and `offset`."""

TIMEOUT_S = 30.0
"""Seconds one request is given, a first value and no measurement of need, in place of httpx's own 5 s: 30 s is about
3.2 times the slowest render read, 9.26 s, the one that cloned the repository again after a recreate
(design/verified-facts.md, "Nautobot 3.2.8 with Golden Config 3.0.8")."""

WORDS = 300
"""How many characters of Nautobot's own words a refusal carries."""

HIDDEN = "<token>"
"""What stands for the token wherever Nautobot or httpx echoes it."""


class BoxError(Exception):
    """A request that failed, said in one sentence that holds no part of the token; `status` is Nautobot's HTTP status
    where it answered one, and None where it answered none, or answered a list that will not do."""

    def __init__(self, sentence: str, status: int | None = None) -> None:
        super().__init__(sentence)
        self.status = status


class Box:
    """The superuser's reach into one Nautobot's REST API, for the seed and the accounts."""

    def __init__(self, address: str, token: str, *, transport: httpx.BaseTransport | None = None) -> None:
        if not token or not all("!" <= character <= "~" for character in token):
            raise BoxError("the token is empty or holds a character a header cannot carry")
        self._address = address.rstrip("/")
        self._transport = transport
        self._secrets = [token]
        self._client = httpx.Client(
            base_url=f"{self._address}/api/",
            headers={"Authorization": f"Token {token}", "Accept": "application/json"},
            transport=transport,
            timeout=TIMEOUT_S,
            trust_env=False,
        )
        self.ensured: list[tuple[str, str, str]] = []
        """What `ensure` did, in order: `"made"` or `"found"`, the path, and the object's UUID."""

    def __repr__(self) -> str:
        return f"Box({self._address!r})"

    def close(self) -> None:
        self._client.close()

    @property
    def address(self) -> str:
        return self._address

    @property
    def transport(self) -> httpx.BaseTransport | None:
        return self._transport

    def another(self, token: str) -> Box:
        """A box of the same kind at the same address over the same transport, carrying `token` in place of this
        one's: how a token of an account is tried as that account."""
        return type(self)(self._address, token, transport=self._transport)

    def hide(self, *values: str) -> None:
        """Each of `values` replaced wherever Nautobot or httpx echoes it, as the token is: a secret a request carries,
        which a refusal may echo, as itself or as `json.dumps` writes it."""
        held = {*self._secrets, *(value for value in values if value)}
        self._secrets = sorted(held, key=len, reverse=True)

    def get(self, path: str, **params: object) -> Any:
        """Nautobot's answer to `GET path` with `params` as its query."""
        return self._send("GET", path, params=params)

    def listed(self, path: str, **params: object) -> list[dict[str, Any]]:
        """Every row of the list at `path`, read `PAGE` at a time; a `BoxError` where the rows are not the `count`
        Nautobot answers, or the `count` moves between pages."""
        rows: list[dict[str, Any]] = []
        count: int | None = None
        while True:
            answer = self.get(path, **params, limit=PAGE, offset=len(rows))
            if not isinstance(answer, dict) or not isinstance(answer.get("results"), list):
                raise BoxError(f"GET {where(path)} answered no list")
            if count is not None and answer.get("count") != count:
                raise BoxError(f"GET {where(path)} counted {count} rows, then {answer.get('count')}")
            count = answer.get("count")
            if not isinstance(count, int):
                raise BoxError(f"GET {where(path)} answered a list with no count")
            results: list[dict[str, Any]] = answer["results"]
            rows.extend(results)
            if len(rows) >= count or not results or answer.get("next") is None:
                break
        if len(rows) != count:
            raise BoxError(f"GET {where(path)} listed {len(rows)} rows where Nautobot counts {count}")
        return rows

    def one(self, path: str, **params: object) -> dict[str, Any] | None:
        """The one row at `path` that `params` match, None where none does; a `BoxError` where two or more do."""
        rows = self.listed(path, **params)
        if len(rows) > 1:
            lookup = ", ".join(f"{name}={value}" for name, value in params.items())
            raise BoxError(f"GET {where(path)} with {lookup} matched {len(rows)} rows where one at most was asked")
        return rows[0] if rows else None

    def ensure(self, path: str, lookup: Mapping[str, object], body: Mapping[str, object]) -> dict[str, Any]:
        """The row at `path` that `lookup` matches, found, or made by posting `body` where none is; which is recorded
        in `ensured`. Two that match are a `BoxError`, and nothing is sent."""
        found = self.one(path, **lookup)
        if found is not None:
            self.ensured.append(("found", path, identity(path, found)))
            return found
        made = self.post(path, dict(body))
        if not isinstance(made, dict):
            raise BoxError(f"POST {where(path)} answered no object")
        self.ensured.append(("made", path, identity(path, made)))
        return made

    def post(self, path: str, body: object) -> Any:
        return self._send("POST", path, body=body)

    def patch(self, path: str, body: object) -> Any:
        return self._send("PATCH", path, body=body)

    def delete(self, path: str) -> None:
        self._send("DELETE", path)

    def _send(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, object] | None = None,
        body: object | None = None,
    ) -> Any:
        """Nautobot's answer as JSON, None where it answers no body; a status outside 200 to 299, or no answer, is a
        `BoxError` with the method, the path and Nautobot's words or httpx's, or for a redirect where it points.

        httpx follows no redirect, so a 3xx taken for success would be a `DELETE` or a `POST` that did nothing and
        said nothing."""
        asked = query(params or {})
        failure: str | None = None
        try:
            response = self._client.request(method, path.lstrip("/"), params=asked, json=body)
        except httpx.HTTPError as e:
            failure = f"{method} {where(path)} was not answered by {self._address}: {type(e).__name__}: {e}"
        if failure is not None:
            raise self._error(failure)
        status = response.status_code
        if not 200 <= status <= 299:
            said = moved(response) if 300 <= status <= 399 else self._words(response)
            raise self._error(f"{method} {where(path)} answered HTTP {status}: {said}", status)
        if not response.content:
            return None
        try:
            return json.loads(response.content)
        except ValueError:
            failure = f"{method} {where(path)} answered HTTP {status} with a body that is not JSON"
        raise self._error(failure, status)

    def _hide(self, text: str) -> str:
        """`text` with each secret replaced, the longer first, and each also as `json.dumps` writes it inside a string,
        a quote, a backslash or a character outside ASCII escaped: a refusal with no `detail` is its body
        serialised."""
        for secret in self._secrets:
            text = text.replace(json.dumps(secret)[1:-1], HIDDEN).replace(secret, HIDDEN)
        return text

    def _words(self, response: httpx.Response) -> str:
        """Nautobot's own words in a refusal: its `detail` where the body carries one, else the body, cut at `WORDS`
        characters once the token is replaced in it."""
        try:
            body = json.loads(response.content)
        except ValueError:
            body = None
        if isinstance(body, dict) and isinstance(body.get("detail"), str):
            text = body["detail"]
        elif body is not None:
            text = json.dumps(body)
        else:
            text = response.text
        said = " ".join(self._hide(text).split())
        return said[:WORDS] if said else "an empty body"

    def _error(self, sentence: str, status: int | None = None) -> BoxError:
        return BoxError(" ".join(self._hide(sentence).split()), status)


def moved(response: httpx.Response) -> str:
    """Where a redirect points, by its `Location`'s path alone, never its host or its query."""
    location = response.headers.get("Location")
    try:
        path = httpx.URL(location).path if location else ""
    except httpx.InvalidURL:
        path = ""
    return f"a redirect to {path}" if path else "a redirect with no Location"


def where(path: str) -> str:
    """`path` as Nautobot is asked it, under `/api/`."""
    return f"/api/{path.lstrip('/')}"


def query(params: Mapping[str, object]) -> httpx.QueryParams:
    """`params` as a query: a list or a tuple once a member, a bool as Nautobot's filters read one. None is a
    `ValueError` naming the parameter, raised before any request: it would be sent as the text `None`."""
    pairs: list[tuple[str, str | int | float | bool | None]] = []
    for name, value in params.items():
        for member in value if isinstance(value, (list, tuple)) else [value]:
            if member is None:
                raise ValueError(f"the query parameter {name} is None")
            pairs.append((name, ("true" if member else "false") if isinstance(member, bool) else str(member)))
    return httpx.QueryParams(pairs)


def identity(path: str, row: Mapping[str, Any]) -> str:
    found = row.get("id")
    if not isinstance(found, str) or not found:
        raise BoxError(f"{where(path)} answered an object with no id")
    return found
