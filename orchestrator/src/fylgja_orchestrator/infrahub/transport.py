"""The change source's transport: its own few requests to Infrahub, over plain HTTP and httpx, with no SDK (D-083).

The reader's transport sends no mutation, and the source must write a thread and its comments, so it speaks for itself
here: `POST /graphql/<branch, percent-escaped>[?at=<at, verbatim>]` of one document under `queries/`, each named by
its operation, and nothing else. `at` is a time as Infrahub answered it, sent back as given. Every request is given
30 s, 5 s of them to connect, on a connection kept no more than 1 s idle (on one kept 2.0 s idle, one request in three
trials was refused), and reads no proxy or certificate from the environment; the token is sent in the one header
`X-INFRAHUB-KEY`, checked by the client's bearer rule before any request so that no HTTP library's complaint can
quote it.

Every failure is a `SourceError` saying what was asked and where. A token refused, HTTP 401 or 403 or a 200 whose
first error carries one of them, is `refused_token`'s sentence by its status, the call named and no value, which the
source gives for the reader's too: a 401 the token refused, a 403 the account lacking a permission the call requires,
with the permissions Infrahub's words name (P5-44). Any other status than 200, or a 200 whose body holds `errors`,
quotes Infrahub's messages, cut at `QUOTED` characters, the token replaced first. None holds the token: its text has
it replaced by `<redacted>`, and one of httpx's is raised from nothing, since an httpx exception carries its request,
whose headers hold it. A request Infrahub sheds under load is sent again after the wait it names, up to `SHED_BUDGET_S`
in all, and nothing is printed while it waits.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Mapping
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx
from fylgja_core.client import base_url, bearer, trust

TIMEOUT = httpx.Timeout(30.0, connect=5.0)
"""What one request is given: 30 s, 5 s of them to connect."""

KEEPALIVE_S = 1.0
"""Seconds an idle connection is kept for the next request, as the reader keeps one: on a connection kept 2.0 s idle,
one request in three trials was refused (`RemoteProtocolError`), and from 2.2 s Infrahub's answer came on a new
connection; the source asks every `VALIDATION_POLL_S` while it waits (design/verified-facts.md, "Infrahub 1.11.11")."""

SHED_WAIT_DEFAULT_S = 5
"""Seconds waited before a shed request is sent again where Infrahub's `Retry-After` is missing or no count of seconds.
Infrahub 1.11.11's backpressure answers a request it sheds with HTTP 429, `Retry-After` in whole seconds and
`X-Infrahub-Admission: shed`, written before any handler runs, so the request did nothing and is sent again, a mutation
among them (design/verified-facts.md, "Infrahub 1.11.11")."""

SHED_WAIT_MAX_S = 30
"""The most seconds one wait for a shed request lasts, whatever `Retry-After` says; the least is 1."""

SHED_BUDGET_S = 300
"""The most seconds the waits for one shed request add up to, ours: of the order of infrahub-sdk's own bound for a 429,
10 retries of at most 60 s each (design/verified-facts.md, "Infrahub 1.11.11"). A wait that would pass it is not taken,
and the last 429 fails as any 429 does."""

QUOTED = 500
"""How many characters of Infrahub's messages an error quotes."""

REDACTED = "<redacted>"
"""What stands for the token in an error's text."""

REFUSED = (401, 403)
"""The statuses of a token Infrahub refused: 401, no valid token; 403, an account that lacks a permission the call
requires."""

CALLS = {
    "proposed_change": "a read of the proposed change",
    "branch": "a read of the branch",
    "marks": "a read of the marks",
    "artifact_validation": "a read of the artifact validation",
    "thread_create": "the thread's create",
    "comment_create": "a comment's create",
}
"""Each document's call in words, for a refused token's sentence."""

_PERMISSION = re.compile(r"\b(?:object|global):[A-Za-z0-9_*]+(?::[A-Za-z0-9_*]+)+")

_QUERIES = resources.files("fylgja_orchestrator.infrahub") / "queries"
_OPERATION = re.compile(r"(?:query|mutation)\s+([_A-Za-z][_0-9A-Za-z]*)")


class SourceError(Exception):
    """Infrahub refused what the source asked, answered what is no answer, or was not reached; or what it answered
    cannot be a change's. The text says what was asked and where, and holds no token. `status` is a refused token's,
    401 or 403, which `refused_token`'s sentence says (P5-48), and None for every other failure."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def refused_token(call: str, status: int, url: str, words: str = "") -> str:
    """The sentence of a token Infrahub refused for `call`, by its status, whichever connection sent it: a 401, the
    token refused; a 403, the account lacking a permission the call requires, with each permission Infrahub's `words`
    name, already scrubbed of the token. No variable is named, since the source is given its token by whoever runs
    it, and no value."""
    if status == 401:
        return f"{call}: the change source's token was refused: HTTP 401 from Infrahub at {url}"
    said = (
        f"the change source's account lacks a permission Infrahub requires for {call}: HTTP {status} from Infrahub "
        f"at {url}"
    )
    named = list(dict.fromkeys(_PERMISSION.findall(words)))
    return f"{said}; Infrahub names {' or '.join(named)}" if named else said


@cache
def _document(name: str) -> tuple[str, str]:
    """The text of `queries/<name>.gql` and the name of its operation."""
    text = (_QUERIES / f"{name}.gql").read_text()
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    found = _OPERATION.match(body.lstrip())
    if found is None:
        raise ValueError(f"queries/{name}.gql names no operation")
    return text, found[1]


class Transport:
    """One Infrahub, asked through one pool of connections with one token. Made with no request: the address and the
    CA are read by the core's client rules (`InvalidAddress`, `InvalidCA`) and the token by its bearer rule
    (`InvalidToken`), each a predicate that repeats nothing; `transport` replaces the network and `sleep` the wait for a
    shed request, for tests."""

    def __init__(
        self,
        address: str,
        token: str,
        *,
        ca: Path | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._url = base_url(address)
        bearer(token)
        self._token = token
        self._sleep = sleep
        self._http = httpx.Client(
            base_url=self._url,
            headers={"X-INFRAHUB-KEY": token},
            transport=transport,
            verify=trust(ca),
            timeout=TIMEOUT,
            limits=httpx.Limits(keepalive_expiry=KEEPALIVE_S),
            trust_env=False,
        )

    def __repr__(self) -> str:
        """Neither the token nor the address, which may hold a login."""
        return "Transport()"

    @property
    def url(self) -> str:
        """The URL Infrahub is asked at, as `base_url` made it."""
        return self._url

    def close(self) -> None:
        self._http.close()

    def ask(
        self, name: str, variables: Mapping[str, Any], *, branch: str = "main", at: str | None = None
    ) -> dict[str, Any]:
        """The `data` Infrahub answers the document `queries/<name>.gql`, given `variables`, on `branch`'s endpoint,
        pinned at `at`, sent verbatim, where it is given. A `SourceError` where Infrahub answers any status but 200, a
        200 whose body holds `errors`, or no `data`, or is not reached."""
        document, operation = _document(name)
        what = f"asking {operation} of Infrahub (branch {branch}{f', at {at}' if at is not None else ''})"
        body = {"query": document, "variables": dict(variables), "operationName": operation}
        response, shed_s = self._post(f"/graphql/{quote(branch, safe='')}", what, at, body)
        try:
            answer = json.loads(response.content)
        except ValueError:
            answer = None
        errors = answer.get("errors") if isinstance(answer, dict) else None
        refused = response.status_code if response.status_code in REFUSED else _status(errors) if errors else None
        if refused in REFUSED:
            words = self._hide(_messages(errors)) if errors else ""
            raise SourceError(refused_token(CALLS.get(name, f"asking {operation}"), refused, self._url, words),
                              status=refused)
        if response.status_code != 200:
            words = _messages(errors) if errors else response.text.strip() or "an empty body"
            gave_up = f"; Infrahub shed the request for {shed_s} s, so it was given up" if _is_shed(response) else ""
            raise SourceError(f"{what}: HTTP {response.status_code}: {self._quote(words)}{gave_up}")
        if errors:
            status = _status(errors)
            said = "HTTP 200" if status is None else f"HTTP 200, http_status {status}"
            raise SourceError(f"{what}: {said}: {self._quote(_messages(errors))}")
        data = answer.get("data") if isinstance(answer, dict) else None
        if not isinstance(data, dict):
            raise SourceError(f"{what}: HTTP 200: answered no data")
        return data

    def _post(self, path: str, what: str, at: str | None, body: object) -> tuple[httpx.Response, int]:
        """The response to one request and the seconds waited for it, a shed one sent again after each wait that fits
        in `SHED_BUDGET_S`; once the next would not, the last 429 is answered."""
        waited = 0
        while True:
            response = self._request(path, what, at, body)
            if not _is_shed(response):
                return response, waited
            wait = _shed_wait(response)
            if waited + wait > SHED_BUDGET_S:
                return response, waited
            self._sleep(wait)
            waited += wait

    def _request(self, path: str, what: str, at: str | None, body: object) -> httpx.Response:
        try:
            return self._http.post(path, params={"at": at} if at is not None else None, json=body)
        except httpx.HTTPError as e:
            # Hidden before it is bound: the exception's text can hold the token, and a traceback can show its locals.
            said = self._hide(f"{what}: Infrahub at {self._url} was not reached: {type(e).__name__}: {e}")
            failure = SourceError(said)
        # Raised outside the handler, so that the error carries no context, whose request holds the token.
        raise failure

    def _quote(self, words: str) -> str:
        """Infrahub's words, the token replaced first and then cut at `QUOTED` characters, so that no part of it is
        left at the cut."""
        return self._hide(words)[:QUOTED]

    def _hide(self, text: str) -> str:
        return " ".join(text.replace(self._token, REDACTED).split())


def _is_shed(response: httpx.Response) -> bool:
    """Whether `response` is a request Infrahub's backpressure shed: HTTP 429 marked `X-Infrahub-Admission: shed`."""
    return response.status_code == 429 and response.headers.get("X-Infrahub-Admission", "").strip().lower() == "shed"


def _shed_wait(response: httpx.Response) -> int:
    """The seconds to wait before a shed request is sent again: its `Retry-After`, held to 1 to `SHED_WAIT_MAX_S`, or
    `SHED_WAIT_DEFAULT_S` where that is missing or no count of seconds. A count of more than three digits is past the
    most, and is not read: `int` refuses one of more than 4,300."""
    said = response.headers.get("Retry-After", "").strip()
    if not (said.isascii() and said.isdigit()):
        return SHED_WAIT_DEFAULT_S
    if len(said) > 3:
        return SHED_WAIT_MAX_S
    return min(max(int(said), 1), SHED_WAIT_MAX_S)


def _status(errors: object) -> int | None:
    """The status the first GraphQL error carries at `extensions.http_status`; None where it carries none."""
    first = errors[0] if isinstance(errors, list) and errors else errors
    extensions = first.get("extensions") if isinstance(first, dict) else None
    status = extensions.get("http_status") if isinstance(extensions, dict) else None
    return status if type(status) is int else None


def _messages(errors: object) -> str:
    """Each error's message: an object's `message`, or a string as it is."""
    said = []
    for error in errors if isinstance(errors, list) else [errors]:
        message = error.get("message") if isinstance(error, dict) else error
        said.append(str(message if message is not None else error))
    return "; ".join(said)
