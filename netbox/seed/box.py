"""Everything that seeds the development NetBox: one httpx transport over its REST API, and the wait for a branch.

`Box` is given the address and the superuser's token, `FYLGJA_NETBOX_ADDRESS` and `FYLGJA_NETBOX_WRITE_TOKEN` where
the seed and the account read them (D-042); it has no default address and makes no request until it is asked one.
Every path is relative to `<address>/api/`, every request carries the token as `Authorization: Bearer <token>`, and a
branch is selected by its `schema_id` in the header `X-NetBox-Branch` (design/verified-facts.md, "NetBox 4.7.5 with
netbox-branching 1.2.3").

Every failure is a `BoxError` of one sentence, built here with the token and each of its halves replaced, and each
value a caller hands `hide`, before NetBox's words are cut; none is chained to the exception it came from: an httpx
exception carries its request, whose headers hold the token. A token a header cannot carry is refused before a
client is made, since httpx would print it in a `repr` no replacement matches.

Run by `core/.venv/bin/python`; httpx and the standard library alone, never `fylgja_core`, a reader, the example or a
client library of NetBox's.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx

ADDRESS = "FYLGJA_NETBOX_ADDRESS"
TOKEN = "FYLGJA_NETBOX_WRITE_TOKEN"

PAGE = 50
"""Rows asked of NetBox a page, by `limit` and `offset`."""

BRANCH_WAIT_S = 120
"""Seconds a branch is given to read `ready` from its request, a bound sized from readings and no measurement of need.
Branches read `ready` 11.1 s at most after their request; and two whose `DELETE` NetBox refused while they
provisioned read `ready` at reads 26.7 s to 28.2 s after it, how much sooner not read (design/verified-facts.md,
"NetBox 4.7.5 with netbox-branching 1.2.3", "A branch deleted before it is `ready`"). 120 s is about 4.3 times the
slowest, 28.2 s, a derivation."""

TIMEOUT_S = 30.0
"""Seconds one request is given, a first value and no measurement of need, in place of httpx's own 5 s. The slowest
request read was a branch's `DELETE`: 3.41 s and 3.31 s in one script, and 2.83 s in another run
(design/verified-facts.md, "NetBox 4.7.5 with netbox-branching 1.2.3"); 30 s is 8.8 times the slowest, 3.41 s, a
derivation."""

BRANCHES = "plugins/branching/branches/"

WORDS = 300
"""How many characters of NetBox's own words a refusal carries."""

HIDDEN = "<token>"
"""What stands for the token, or a half of it, wherever NetBox or httpx echoes it."""

HALF = 8
"""The fewest characters a half of the token has for it to be replaced on its own: a shorter one would match ordinary
words. NetBox's v2 token, `nbt_<key>.<token>`, has a key of 12 and a token of 40."""


class BoxError(Exception):
    """A request or a wait that failed, said in one sentence that holds no part of the token; `status` is NetBox's
    HTTP status where it answered one, and None where it answered none, or answered a list or a branch that will not
    do."""

    def __init__(self, sentence: str, status: int | None = None) -> None:
        super().__init__(sentence)
        self.status = status


class Unfit(BoxError):
    """An answer NetBox gave that will not do, though it is NetBox's own, such as two rows where one at most was asked:
    it carries no status, and NetBox not running is not its cause."""


class Box:
    """The superuser's reach into one NetBox's REST API, for the seed and the accounts."""

    def __init__(self, address: str, token: str, *, transport: httpx.BaseTransport | None = None) -> None:
        if not token or not all("!" <= character <= "~" for character in token):
            raise BoxError("the token is empty or holds a character a header cannot carry")
        self._address = address.rstrip("/")
        self._parts = parts(token)
        self._client = httpx.Client(
            base_url=f"{self._address}/api/",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            transport=transport,
            timeout=TIMEOUT_S,
            trust_env=False,
        )
        self.ensured: list[tuple[str, str, int]] = []
        """What `ensure` did, in order: `"made"` or `"found"`, the path, and the object's id."""

    def __repr__(self) -> str:
        return f"Box({self._address!r})"

    def close(self) -> None:
        self._client.close()

    def hide(self, *values: str) -> None:
        """Each of `values`, and each half of one presented as `nbt_<key>.<token>`, replaced wherever NetBox or httpx
        echoes it, as the token is: a secret a request carries, which a refusal may echo, as itself or as
        `json.dumps` writes it. A part shorter than `HALF` is left, since it would match ordinary words."""
        held = {*self._parts, *(part for value in values for part in parts(value) if len(part) >= HALF)}
        self._parts = sorted(held, key=len, reverse=True)

    def get(self, path: str, *, branch: str | None = None, **params: object) -> Any:
        """NetBox's answer to `GET path` with `params` as its query, under `branch` where it is given."""
        return self._send("GET", path, branch, params=params)

    def listed(self, path: str, *, branch: str | None = None, **params: object) -> list[dict[str, Any]]:
        """Every row of the list at `path`, read `PAGE` at a time; a `BoxError` where the rows are not the `count`
        NetBox answers, or the `count` moves between pages."""
        rows: list[dict[str, Any]] = []
        count: int | None = None
        while True:
            answer = self.get(path, branch=branch, **params, limit=PAGE, offset=len(rows))
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
            raise BoxError(f"GET {where(path)} listed {len(rows)} rows where NetBox counts {count}")
        return rows

    def one(self, path: str, *, branch: str | None = None, **params: object) -> dict[str, Any] | None:
        """The one row at `path` that `params` match, None where none does; an `Unfit` where two or more do."""
        rows = self.listed(path, branch=branch, **params)
        if len(rows) > 1:
            lookup = ", ".join(f"{name}={value}" for name, value in params.items())
            raise Unfit(f"GET {where(path)} with {lookup} matched {len(rows)} rows where one at most was asked")
        return rows[0] if rows else None

    def ensure(
        self, path: str, lookup: Mapping[str, object], body: Mapping[str, object], *, branch: str | None = None
    ) -> dict[str, Any]:
        """The row at `path` that `lookup` matches, found, or made by posting `body` where none is; which is recorded
        in `ensured`. Two that match are a `BoxError`, and nothing is sent."""
        found = self.one(path, branch=branch, **lookup)
        if found is not None:
            self.ensured.append(("found", path, identity(path, found)))
            return found
        made = self.post(path, dict(body), branch=branch)
        if not isinstance(made, dict):
            raise BoxError(f"POST {where(path)} answered no object")
        self.ensured.append(("made", path, identity(path, made)))
        return made

    def post(self, path: str, body: object, *, branch: str | None = None) -> Any:
        return self._send("POST", path, branch, body=body)

    def patch(self, path: str, body: object, *, branch: str | None = None) -> Any:
        return self._send("PATCH", path, branch, body=body)

    def delete(self, path: str, *, branch: str | None = None) -> None:
        self._send("DELETE", path, branch)

    def _send(
        self,
        method: str,
        path: str,
        branch: str | None,
        *,
        params: Mapping[str, object] | None = None,
        body: object | None = None,
    ) -> Any:
        """NetBox's answer as JSON, None where it answers no body; a status outside 200 to 299, or no answer, is a
        `BoxError` with the method, the path and NetBox's words or httpx's, or for a redirect where it points.

        httpx follows no redirect, so a 3xx taken for success would be a `DELETE` or a `POST` that did nothing and
        said nothing. Django answers a path without its trailing slash with 301 under `APPEND_SLASH`, its documented
        behaviour; NetBox answering so was not read on the instance."""
        headers = {"X-NetBox-Branch": branch} if branch is not None else None
        asked = query(params or {})
        failure: str | None = None
        try:
            response = self._client.request(method, path.lstrip("/"), params=asked, json=body, headers=headers)
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
        """`text` with each part replaced, the longer first, and each also as `json.dumps` writes it inside a string,
        a quote, a backslash or a character outside ASCII escaped: a refusal with no `detail` is its body
        serialised."""
        for part in self._parts:
            text = text.replace(json.dumps(part)[1:-1], HIDDEN).replace(part, HIDDEN)
        return text

    def _words(self, response: httpx.Response) -> str:
        """NetBox's own words in a refusal: its `detail` where the body carries one, else the body, cut at `WORDS`
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


def parts(token: str) -> list[str]:
    """What is replaced wherever it is echoed: the token, then each half of a v2 token, `nbt_<key>.<token>`, long
    enough not to match ordinary words, the longer first."""
    halves = token.removeprefix("nbt_").split(".") if "." in token else []
    return [token, *sorted((half for half in halves if len(half) >= HALF), key=len, reverse=True)]


def moved(response: httpx.Response) -> str:
    """Where a redirect points, by its `Location`'s path alone, never its host or its query."""
    location = response.headers.get("Location")
    try:
        path = httpx.URL(location).path if location else ""
    except httpx.InvalidURL:
        path = ""
    return f"a redirect to {path}" if path else "a redirect with no Location"


def where(path: str) -> str:
    """`path` as NetBox is asked it, under `/api/`."""
    return f"/api/{path.lstrip('/')}"


def query(params: Mapping[str, object]) -> httpx.QueryParams:
    """`params` as a query: a list or a tuple once a member, a bool as NetBox's filters read one. None is a
    `ValueError` naming the parameter, raised before any request: it would be sent as the text `None`."""
    pairs: list[tuple[str, str | int | float | bool | None]] = []
    for name, value in params.items():
        for member in value if isinstance(value, (list, tuple)) else [value]:
            if member is None:
                raise ValueError(f"the query parameter {name} is None")
            pairs.append((name, ("true" if member else "false") if isinstance(member, bool) else str(member)))
    return httpx.QueryParams(pairs)


def identity(path: str, row: Mapping[str, Any]) -> int:
    found = row.get("id")
    if not isinstance(found, int):
        raise BoxError(f"{where(path)} answered an object with no id")
    return found


def branch_named(box: Box, name: str) -> dict[str, Any] | None:
    """The branch `name`, found by `?name=`, None where none is; a row whose own `name` is another is a `BoxError`
    naming both, never a branch to wait for, write to or delete."""
    found = box.one(BRANCHES, name=name)
    if found is not None and found.get("name") != name:
        raise BoxError(f"GET {where(BRANCHES)} with name={name} answered the branch {found.get('name')}")
    return found


def branched(
    box: Box,
    name: str,
    *,
    timeout_s: float = BRANCH_WAIT_S,
    poll_s: float = 1.0,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """The branch `name`, made where none stands, read every `poll_s` until its `status.value` is `ready`, and its
    representation then; `failed` is a `BoxError` at once, and any other status at `timeout_s` from the start one
    naming the last. A sleep never passes the bound."""
    started = clock()
    current = branch_named(box, name)
    if current is None:
        current = box.post(BRANCHES, {"name": name})
        if not isinstance(current, dict):
            raise BoxError(f"POST {where(BRANCHES)} answered no branch for {name}")
    path = f"{BRANCHES}{identity(BRANCHES, current)}/"
    while True:
        status = current.get("status")
        value = status.get("value") if isinstance(status, dict) else None
        if value == "ready":
            return current
        if value == "failed":
            raise BoxError(f"the branch {name} is failed")
        waited = clock() - started
        if waited >= timeout_s:
            raise BoxError(f"the branch {name} was not ready within {timeout_s:g} s: its status is {value}")
        sleep(min(poll_s, timeout_s - waited))
        current = box.get(path)
        if not isinstance(current, dict):
            raise BoxError(f"GET {where(path)} answered no branch for {name}")
