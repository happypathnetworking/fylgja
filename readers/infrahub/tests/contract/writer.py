"""The contract tier's own writer: the admin's reach into the development Infrahub, which makes the branches, the
objects and the schema a contract test reads and deletes them after. The reader is never given it.

`connect` makes the `Writer` from the three values the tier reads, `FYLGJA_INFRAHUB_ADDRESS`,
`FYLGJA_INFRAHUB_WRITE_TOKEN` and, where set, `FYLGJA_INFRAHUB_CA`, and never from the environment whole, which pytest
would print as an argument of a failing frame. The token goes to Infrahub as the header `X-INFRAHUB-KEY` and nowhere
else. Every failure is a `WriterError` of one sentence with the token replaced, raised from nothing, since an httpx
exception carries its request, whose headers hold the key; a text that can hold the token is hidden before it is bound
to a name, since a traceback can show a frame's locals.

It is modelled on `infrahub/seed/hub.py`, the seed's writer, and imports nothing of it: `infrahub/` is no
distribution. A test writes only on a branch `fylgja-contract-<8 hex>` that `branch` makes from `main` and deletes
whatever happened; `sweep` deletes what a stopped run left.
"""

from __future__ import annotations

import json
import re
import secrets
import ssl
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from typing import Any
from urllib.parse import quote

import httpx

ADDRESS = "FYLGJA_INFRAHUB_ADDRESS"
TOKEN = "FYLGJA_INFRAHUB_WRITE_TOKEN"
CA = "FYLGJA_INFRAHUB_CA"

PREFIX = "fylgja-contract-"
OURS = re.compile(r"fylgja-contract-[0-9a-f]{8}")
"""The branches the tier makes: the prefix and 8 hex digits."""

PROBE = "FylgjaProbe"
PROBES = "fc-"
"""The kind of a probe, and the prefix of the name of each probe the tier makes."""

REQUEST_TIMEOUT_S = 60.0
"""Seconds one request is given, as the seed's writer gives it."""

KEEPALIVE_S = 1.0
"""Seconds an idle connection is kept: Infrahub's server closes one idle for 2 s, and a request sent on a connection it
was closing went unanswered (design/verified-facts.md, "Infrahub 1.11.11")."""

WAIT_S = 120.0
"""How long a branch is read for after a create that failed or went unanswered, and a schema after its load: one
create's branch was listed 75.1 s after it was sent, and a load was read 6 s after it returned
(design/verified-facts.md, "Infrahub 1.11.11")."""

POLL_S = 2.0
HIDDEN = "<token>"

BRANCHES = "query { Branch { name } }"
LISTED = "query ($name: String) { Branch(name: $name) { name } }"
CREATE = (
    "mutation ($name: String!) { BranchCreate(data: {name: $name, sync_with_git: false}, wait_until_completion: true) "
    "{ ok } }"
)
DELETE = "mutation ($name: String!) { BranchDelete(data: {name: $name}, wait_until_completion: true) { ok } }"
PROBES_READ = "query { FylgjaProbe { edges { node { id name { value } } } } }"
PROBE_DELETE = "mutation ($id: String!) { FylgjaProbeDelete(data: {id: $id}) { ok } }"


class WriterError(Exception):
    """A request or a wait that failed, said in one sentence that holds no token."""


class Writer:
    """The tier's writer over one httpx client. Made by `connect`."""

    def __init__(
        self,
        client: httpx.Client,
        *,
        token: str,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._token = token
        self._clock = clock
        self._sleep = sleep

    def __repr__(self) -> str:
        """Neither the token nor the address: a test's fixtures are listed by their repr."""
        return "Writer()"

    def close(self) -> None:
        self._client.close()

    def gql(self, branch: str, document: str, variables: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """The answer's `data` to `document` on `branch`'s endpoint; an answer with `errors`, under HTTP 200 too, is a
        `WriterError` naming each error's message and its `http_status`."""
        path = f"/graphql/{quote(branch, safe='')}"
        response = self._send("POST", path, None, {"query": document, "variables": dict(variables or {})})
        body = _decoded(response)
        if response.status_code != 200:
            raise self._error(f"POST {path} answered HTTP {response.status_code}: {self._words(response, body)}")
        if not isinstance(body, dict):
            raise self._error(f"POST {path} answered HTTP 200 with a body that is no GraphQL answer")
        if body.get("errors"):
            raise self._error(f"POST {path} answered HTTP 200 with errors: {_messages(body['errors'])}")
        data = body.get("data")
        if not isinstance(data, dict):
            raise self._error(f"POST {path} answered HTTP 200 with no data")
        return data

    def mutate(self, branch: str, name: str, data: Mapping[str, Any], *, select: str = "ok") -> dict[str, Any]:
        """The answer of the mutation `name` on `branch`, `data` its input written as a GraphQL literal and `select`
        what it selects, `ok` among it; an answer whose `ok` is not true is a `WriterError`."""
        answer = self.gql(branch, f"mutation {{ {name}(data: {_literal(data)}) {{ {select} }} }}").get(name)
        if not (isinstance(answer, dict) and answer.get("ok") is True):
            raise self._error(f"{name} on {branch} answered no ok")
        return answer

    def named(self, branch: str, kind: str, name: str) -> str:
        """The id of the one `kind` on `branch` whose `name` is `name`; none, or several, is a `WriterError`."""
        document = f"query ($name: String!) {{ {kind}(name__value: $name) {{ edges {{ node {{ id }} }} }} }}"
        edges = (self.gql(branch, document, {"name": name}).get(kind) or {}).get("edges") or []
        if len(edges) != 1:
            raise self._error(f"{branch} holds {len(edges)} {kind} named {name}, not one")
        found: str = edges[0]["node"]["id"]
        return found

    def rest(
        self, method: str, path: str, *, params: Mapping[str, str] | None = None, body: object | None = None
    ) -> httpx.Response:
        """The response to one REST request, `body` sent as JSON where it is given; a status of 400 or more is a
        `WriterError` with Infrahub's words."""
        response = self._send(method, path, params, body)
        if response.status_code >= 400:
            said = self._words(response, _decoded(response))  # hidden there, before it is bound here
            raise self._error(f"{method} {path} answered HTTP {response.status_code}: {said}")
        return response

    def load_schema(self, branch: str, document: Mapping[str, Any]) -> None:
        """Load the schema `document` (`{"version": "1.0", "nodes": [...]}` and the like) on `branch`, and wait until
        the branch's schema hash is the one the load answered, within `WAIT_S`: a schema read as a load returns does not
        yet show it."""
        response = self.rest("POST", "/api/schema/load", params={"branch": branch}, body={"schemas": [document]})
        answer = _decoded(response)
        loaded = answer.get("hash") if isinstance(answer, dict) else None
        if not isinstance(loaded, str):
            raise self._error(f"the schema load on {branch} answered no hash")
        self._wait(lambda: self._schema_hash(branch) == loaded, f"{branch}'s schema at the hash its load answered")

    @contextmanager
    def branch(self) -> Iterator[str]:
        """A branch `fylgja-contract-<8 hex>` made from `main`, deleted on the way out whatever happened in it."""
        name = f"{PREFIX}{secrets.token_hex(4)}"
        try:
            self._make(name)
            yield name
        finally:
            if self._listed(name):
                self._delete(name)

    def sweep(self) -> list[str]:
        """Delete every branch `fylgja-contract-<8 hex>` and, where `main`'s schema holds the kind, every
        `FylgjaProbe` named `fc-*` that a stopped run left; answers what was deleted."""
        swept = []
        for edge in self.gql("main", BRANCHES).get("Branch") or []:
            name = edge.get("name") if isinstance(edge, dict) else None
            if isinstance(name, str) and OURS.fullmatch(name):
                self._delete(name)
                swept.append(name)
        if PROBE in self._summary("main").get("nodes", {}):
            for edge in self.gql("main", PROBES_READ)[PROBE]["edges"]:
                node = edge["node"]
                if str(node["name"]["value"]).startswith(PROBES):
                    self.gql("main", PROBE_DELETE, {"id": node["id"]})
                    swept.append(f"{PROBE} {node['name']['value']}")
        return swept

    def _make(self, name: str) -> None:
        """Make `name` from `main`. A create that fails or goes unanswered within the request's timeout can make its
        branch all the same, so it is then read for until it is listed, within `WAIT_S`."""
        failed: str | None = None
        try:
            answer = self.gql("main", CREATE, {"name": name}).get("BranchCreate")
        except WriterError as e:
            failed = str(e)
        else:
            if not (isinstance(answer, dict) and answer.get("ok") is True):
                failed = f"BranchCreate answered {answer}"
        if failed is not None:
            self._wait(lambda: self._listed(name), f"{name}, after its BranchCreate failed ({failed}),")

    def _delete(self, name: str) -> None:
        answer = self.gql("main", DELETE, {"name": name}).get("BranchDelete")
        if not (isinstance(answer, dict) and answer.get("ok") is True):
            raise self._error(f"deleting {name}: BranchDelete answered no ok")

    def _listed(self, name: str) -> bool:
        return bool(self.gql("main", LISTED, {"name": name}).get("Branch"))

    def _summary(self, branch: str) -> dict[str, Any]:
        """`GET /api/schema/summary?branch=`: the branch's schema hash under `main`, and a hash a kind under `nodes`
        and `generics`."""
        summary = _decoded(self.rest("GET", "/api/schema/summary", params={"branch": branch}))
        if not isinstance(summary, dict):
            raise self._error(f"the schema summary of {branch} is no JSON object")
        return summary

    def _schema_hash(self, branch: str) -> str | None:
        found = self._summary(branch).get("main")
        return found if isinstance(found, str) else None

    def _wait(self, done: Callable[[], bool], what: str) -> None:
        started = self._clock()
        while not done():
            waited = self._clock() - started
            if waited >= WAIT_S:
                raise self._error(f"{what} not within {WAIT_S:g} s")
            self._sleep(min(POLL_S, WAIT_S - waited))

    def _send(
        self, method: str, path: str, params: Mapping[str, str] | None, body: object | None
    ) -> httpx.Response:
        try:
            return self._client.request(method, path, params=params, json=body)
        except httpx.HTTPError as e:
            failure = self._hide(f"{method} {path} was not answered: {type(e).__name__}: {e}")
        raise self._error(failure) from None

    def _words(self, response: httpx.Response, body: object) -> str:
        """Infrahub's own words in a refusal, the token replaced: its errors' messages where the body carries them,
        else the body, cut at 300 characters."""
        if isinstance(body, dict):
            for key in ("errors", "detail", "message"):
                if body.get(key):
                    return self._hide(_messages(body[key]))
        text = self._hide(response.text).strip()
        return text[:300] if text else "an empty body"

    def _hide(self, text: str) -> str:
        return text.replace(self._token, HIDDEN)

    def _error(self, sentence: str) -> WriterError:
        return WriterError(" ".join(self._hide(sentence).split()))


def _literal(value: object) -> str:
    """`value` as a GraphQL input literal: an object's keys bare, a list's items each so, and a string, a number, a
    boolean or null as JSON writes it."""
    if isinstance(value, Mapping):
        return "{" + ", ".join(f"{key}: {_literal(item)}" for key, item in value.items()) + "}"
    if isinstance(value, list | tuple):
        return "[" + ", ".join(_literal(item) for item in value) + "]"
    return json.dumps(value)


def _decoded(response: httpx.Response) -> Any:
    try:
        return json.loads(response.content)
    except ValueError:
        return None


def _messages(errors: object) -> str:
    """Each GraphQL error's message, with the `http_status` its extensions carry."""
    said = []
    for error in errors if isinstance(errors, list) else [errors]:
        if isinstance(error, dict):
            extensions = error.get("extensions")
            status = extensions.get("http_status") if isinstance(extensions, dict) else None
            text = str(error.get("message", error))
            said.append(f"{text} (http_status {status})" if status is not None else text)
        else:
            said.append(str(error))
    return "; ".join(said)


def connect(
    address: str, token: str, ca: str | None = None, *, transport: httpx.BaseTransport | None = None
) -> Writer:
    """The `Writer` at `address`, an http(s):// URL, writing with `token`, an `https://` address verified against
    the CA file `ca` where it is given. A value missing, a token a header cannot carry (anything but printable ASCII
    free of whitespace), or a CA that does not load, is a `WriterError` naming the variable alone. Its frame is hidden
    from pytest's tracebacks, since it holds the token."""
    __tracebackhide__ = True
    if not address:
        raise WriterError(f"{ADDRESS} is not set")
    if not token:
        raise WriterError(f"{TOKEN} is not set")
    if not all("!" <= character <= "~" for character in token):
        raise WriterError(f"{TOKEN} holds a character a header cannot carry")
    verify: ssl.SSLContext | bool = True
    if ca:
        failure: str | None = None
        try:
            verify = ssl.create_default_context(cafile=ca)
        except (OSError, ssl.SSLError) as e:
            failure = f"{CA} does not load: {e}"
        if failure is not None:
            raise WriterError(failure)
    client = httpx.Client(
        base_url=address,
        headers={"X-INFRAHUB-KEY": token},
        transport=transport,
        verify=verify,
        timeout=REQUEST_TIMEOUT_S,
        limits=httpx.Limits(keepalive_expiry=KEEPALIVE_S),
        trust_env=False,
    )
    return Writer(client, token=token)
