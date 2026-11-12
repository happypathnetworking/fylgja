"""Every write to the development Infrahub: one httpx transport, the bounded wait, and `infrahubctl` as a child.

`connect` makes the writer's `Hub` from an environment: `FYLGJA_INFRAHUB_ADDRESS`, `FYLGJA_INFRAHUB_WRITE_TOKEN` and,
where set, `FYLGJA_INFRAHUB_CA` (D-042). There is no default address. The token goes to Infrahub as the header
`X-INFRAHUB-KEY` and to `infrahubctl` as `INFRAHUB_API_TOKEN` in the child's environment, never on a command line.

Every failure is a `HubError` of one sentence, built here with the token replaced, and none is chained to the
exception it came from: an httpx exception carries its request, whose headers hold the key. The token is replaced
before any text is cut, split or joined, also where a child's output folds it across lines, and `connect` refuses a
token a header cannot carry, which httpx would print in a `repr` no replacement matches.

Run by `core/.venv/bin/python`; httpx and the standard library alone, never `fylgja_core` and never the SDK (D-083).
"""

from __future__ import annotations

import json
import re
import ssl
import subprocess
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import httpx

ADDRESS = "FYLGJA_INFRAHUB_ADDRESS"
TOKEN = "FYLGJA_INFRAHUB_WRITE_TOKEN"
CA = "FYLGJA_INFRAHUB_CA"

REQUEST_TIMEOUT_S = 60.0
"""Seconds one request is given, the SDK's own default (`infrahub_sdk/config.py`). The longest read on 1.11.11 was
a repository's create, 9.9 s (design/verified-facts.md, "Infrahub 1.11.11")."""

KEEPALIVE_S = 1.0
"""Seconds an idle connection is kept for the next request. Infrahub's server is given a keep-alive of 2 s, gunicorn's
default, which its uvicorn workers take: read in the image's files, not by a run. Kept for httpx's own 5 s, a poll 2 s
after the last request once had no answer; kept for 1 s, 120 polls 2 s apart had none fail (design/verified-facts.md,
"Infrahub 1.11.11")."""

CTL_TIMEOUT_S = 600
"""`infrahubctl`'s `INFRAHUB_TIMEOUT`: it waits the larger of 120 s and this for a schema load, and the library's
first load took the server about 133 s, past the 120 s (design/verified-facts.md, "Infrahub 1.11.11")."""

CTL_LINES = 5
"""How many of `infrahubctl`'s last lines of output a failure carries."""

HIDDEN = "<token>"
"""What stands for the token wherever Infrahub or `infrahubctl` echoes it."""

Run = Callable[..., subprocess.CompletedProcess[str]]


class HubError(Exception):
    """A request, a child or a wait that failed, said in one sentence that holds no token."""


class Hub:
    """The writer's reach into one Infrahub: GraphQL, REST and `infrahubctl`. Made by `connect`."""

    def __init__(
        self, client: httpx.Client, *, address: str, token: str, ctl: Path, environ: Mapping[str, str], run: Run
    ) -> None:
        self._client = client
        self._address = address
        self._token = token
        self._folded = re.compile(r"\s*".join(re.escape(character) for character in token))
        self._ctl = ctl
        self._environ = dict(environ)
        self._run = run

    def __repr__(self) -> str:
        return f"Hub({self._address!r})"

    def close(self) -> None:
        self._client.close()

    def gql(
        self, branch: str, query: str, variables: Mapping[str, object] | None = None, *, at: str | None = None
    ) -> dict[str, Any]:
        """The answer's `data` to `query` on `branch`'s endpoint, read at the time `at` where it is given.

        An answer with `errors`, HTTP 200 among them, is a `HubError` naming each error's message and its
        `http_status`.
        """
        path = f"/graphql/{branch}"
        params = {"at": at} if at is not None else None
        response = self._send("POST", path, params, {"query": query, "variables": dict(variables or {})})
        if response.status_code != 200:
            raise self._error(f"POST {path} answered HTTP {response.status_code}: {words(response, self._hide)}")
        body = decoded(response)
        if not isinstance(body, dict):
            raise self._error(f"POST {path} answered HTTP 200 with a body that is not a GraphQL answer")
        if body.get("errors"):
            raise self._error(f"POST {path} answered HTTP 200 with errors: {messages(body['errors'])}")
        data = body.get("data")
        if not isinstance(data, dict):
            raise self._error(f"POST {path} answered HTTP 200 with no data")
        return data

    def rest(
        self, method: str, path: str, *, params: Mapping[str, str] | None = None, body: object | None = None
    ) -> httpx.Response:
        """The response to one REST request, `body` sent as JSON where it is given; a status of 400 or more is a
        `HubError` with Infrahub's words."""
        response = self._send(method, path, params, body)
        if response.status_code >= 400:
            raise self._error(f"{method} {path} answered HTTP {response.status_code}: {words(response, self._hide)}")
        return response

    def ctl(self, *args: str) -> None:
        """Run `infrahubctl` with `args`, the address, the token and `CTL_TIMEOUT_S` in its environment and no other
        name of Fylgja's or Infrahub's; a status other than 0 is a `HubError` with its output's last lines."""
        argv = [str(self._ctl), *args]
        env = {name: value for name, value in self._environ.items() if not name.startswith(("FYLGJA_", "INFRAHUB_"))}
        env |= {
            "INFRAHUB_ADDRESS": self._address,
            "INFRAHUB_API_TOKEN": self._token,
            "INFRAHUB_TIMEOUT": str(CTL_TIMEOUT_S),
        }
        failure: str | None = None
        try:
            done = self._run(argv, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=False)
        except OSError as e:
            failure = f"infrahubctl could not be started ({self._ctl}): {e.strerror or e}"
        if failure is not None:
            raise self._error(failure)
        if done.returncode != 0:
            output = self._hide("\n".join(part for part in (done.stdout, done.stderr) if part))
            lines = [line.strip() for line in output.splitlines() if line.strip()]
            said = " / ".join(lines[-CTL_LINES:]) or "no output"
            raise self._error(f"infrahubctl {' '.join(args)} exited {done.returncode}: {said}")

    def _send(
        self, method: str, path: str, params: Mapping[str, str] | None, body: object | None
    ) -> httpx.Response:
        try:
            return self._client.request(method, path, params=params, json=body)
        except httpx.HTTPError as e:
            failure = f"{method} {path} was not answered by {self._address}: {type(e).__name__}: {e}"
        raise self._error(failure)

    def _hide(self, text: str) -> str:
        """`text` with the token replaced, also where whitespace or a line break falls inside it."""
        return self._folded.sub(HIDDEN, text)

    def _error(self, sentence: str) -> HubError:
        return HubError(" ".join(self._hide(sentence).split()))


def decoded(response: httpx.Response) -> object:
    try:
        return json.loads(response.content)
    except ValueError:
        return None


def messages(errors: object) -> str:
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


def words(response: httpx.Response, hide: Callable[[str], str]) -> str:
    """Infrahub's own words in a refusal: its errors' messages where the body carries them, else the body, cut at
    300 characters once `hide` has replaced the token in it."""
    body = decoded(response)
    if isinstance(body, dict):
        for key in ("errors", "detail", "message"):
            if body.get(key):
                return hide(messages(body[key]))
    text = hide(response.text).strip()
    return text[:300] if text else "an empty body"


def connect(
    environ: Mapping[str, str],
    *,
    ctl: Path,
    transport: httpx.BaseTransport | None = None,
    run: Run = subprocess.run,
) -> Hub:
    """The writer's `Hub` from `environ`; a variable not set, a token a header cannot carry (anything but printable
    ASCII free of whitespace), or a CA that does not load, is a `HubError` naming the variable alone."""
    address = environ.get(ADDRESS, "")
    if not address:
        raise HubError(f"{ADDRESS} is not set")
    token = environ.get(TOKEN, "")
    if not token:
        raise HubError(f"{TOKEN} is not set")
    if not all("!" <= character <= "~" for character in token):
        raise HubError(f"{TOKEN} holds a character a header cannot carry")
    verify: ssl.SSLContext | bool = True
    ca = environ.get(CA, "")
    if ca:
        failure: str | None = None
        try:
            verify = ssl.create_default_context(cafile=ca)
        except (OSError, ssl.SSLError) as e:
            failure = f"{CA} does not load: {e}"
        if failure is not None:
            raise HubError(failure)
    client = httpx.Client(
        base_url=address,
        headers={"X-INFRAHUB-KEY": token},
        transport=transport,
        verify=verify,
        timeout=REQUEST_TIMEOUT_S,
        limits=httpx.Limits(keepalive_expiry=KEEPALIVE_S),
        trust_env=False,
    )
    return Hub(client, address=address, token=token, ctl=ctl, environ=environ, run=run)


def wait_until[T](
    read: Callable[[], T],
    pending: Callable[[T], list[str]],
    *,
    what: str,
    timeout_s: float,
    poll_s: float = 2.0,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """`read` every `poll_s` until `pending` answers no reason, and answer that reading; at `timeout_s` from the start
    a `HubError` naming `what` and the last reasons. A sleep never passes the bound."""
    started = clock()
    while True:
        reading = read()
        reasons = pending(reading)
        if not reasons:
            return reading
        waited = clock() - started
        if waited >= timeout_s:
            raise HubError(f"{what} not within {timeout_s:g} s: {', '.join(reasons)}")
        sleep(min(poll_s, timeout_s - waited))
