"""The client library of API 1 (formats/api-1.openapi.yaml, D-025): one method per call the
thin CLI and the orchestrator make, each answering the API's documents as JSON values.

It reaches the core over HTTP alone and holds no rule of the core's: every refusal is the
server's, raised as a `ProblemError` carrying the problem document. What happened to the
client itself (a server it cannot reach or whose certificate it does not trust, an answer that
is no API 1 document) is a `TransportError`, `Untrusted` for the certificate. An https://
address is verified against the CA file the caller names, or the system's trust, never httpx's
bundled roots (`trust`, D-063). Before its first call it reads the server's version and refuses
a server of another API. The token travels in the Authorization header and nowhere else: no
message, repr or log line holds it, and a token that is no RFC 6750 bearer token is refused
before any request, since an HTTP library's complaint about a header would quote it.

A watch outlives the server it was opened on. When its stream ends before its proper end (a
twin's `DELETED`; for a run, its event page saying it has ended), is cut off, or is answered a
proxy's 5xx while the server is away, the client opens it again after the last revision or
event seen, which the server resumes from, so each event arrives once. The waits between tries
grow, each try is given `RECONNECT_CONNECT_S` to connect, and the watch gives up after
`RECONNECTS` early ends in a row with no event between them: about three minutes at most, where
the server's address drops what is sent to it, as a LoadBalancer's does while no pod is ready
behind it (verified-facts.md). A refusal, an answer that is no stream, an event the client
cannot read and a certificate it does not trust end it at once.
"""

from __future__ import annotations

import contextlib
import ipaddress
import json
import re
import ssl
import time
from collections.abc import Callable, Generator, Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self
from urllib.parse import quote

import httpx

from fylgja_core import problem
from fylgja_core.documents import Rejected
from fylgja_core.problem import ProblemDocument

API = "1"
JSON_TYPES = "application/json, application/problem+json"
EVENT_STREAM = "text/event-stream"
TIMEOUT_S = 30.0
# A verify answers once every node has been read (at once, up to gNMI's 15 s budget) and each
# probe's burst has run, one after another (up to 8 s each): longer than `TIMEOUT_S` for a
# twin of a few probes. Its read is still bounded, so a server that stops answering fails the
# call rather than holding it; 300 s covers the reads and some thirty bursts.
VERIFY_TIMEOUT = httpx.Timeout(TIMEOUT_S, read=300.0)
# A watch ended early waits `reconnect_delay(n)` before its nth try in a row and gives up after
# `RECONNECTS`: 0.5, 1, 2, 4, 8 and ten of 10 s, 115.5 s in all, which outlasts a pod replaced
# under a 15 s Lease (D-062). No jitter: a watch is one person's. Each try is given
# `RECONNECT_CONNECT_S` to connect, its TLS handshake within it: a LoadBalancer's address with no
# ready pod drops what is sent to it, and one open waited out the 30 s of `TIMEOUT_S` there
# (verified-facts.md), so fifteen could hold a watch for ten minutes. Bounded so, it gives up within
# about three minutes: 115.5 s of waits and fifteen opens of 5 s at most.
RECONNECTS = 15
RECONNECT_FIRST_S = 0.5
RECONNECT_MAX_S = 10.0
RECONNECT_CONNECT_S = 5.0
RECONNECT_TIMEOUT = httpx.Timeout(TIMEOUT_S, connect=RECONNECT_CONNECT_S)


def reconnect_delay(n: int) -> float:
    """The wait before a watch's `n`th reconnect in a row: doubling from `RECONNECT_FIRST_S`, at
    most `RECONNECT_MAX_S`."""
    return min(RECONNECT_FIRST_S * 2.0 ** (n - 1), RECONNECT_MAX_S)


class ProblemError(Exception):
    """The server refused a request with a problem document (RFC 9457)."""

    def __init__(self, status: int, problem: ProblemDocument) -> None:
        self.status = status
        self.problem = problem
        super().__init__(f"{status} {problem.rule}: {problem.detail or problem.title}")


class TransportError(Exception):
    """The request did not reach the server, or the server's answer is no API 1 document."""


class _Interrupted(TransportError):
    """The connection failed, but for a certificate not trusted (`Untrusted`), or a 5xx came with
    no problem document, a proxy's while the server is away: a watch opens again after it, and
    every other call sees a `TransportError`."""


class Untrusted(TransportError):
    """The server's certificate failed verification against the client's trust. A watch ends at
    once: a certificate not trusted does not become trusted by waiting."""


class UnsupportedVersion(ValueError):
    """The server speaks another API version than this client's."""


class InvalidAddress(ValueError):
    """The address is no server's; the message is a predicate and never repeats it."""


class InvalidToken(ValueError):
    """The token is no bearer token; the message is a predicate and never repeats it."""


class InvalidCA(ValueError):
    """The CA file cannot be read as CA certificates; the message is a predicate and never repeats
    the path or what the file holds."""


# RFC 6750's b64token, the one form a bearer token takes in an Authorization header.
_BEARER = re.compile(r"[A-Za-z0-9\-._~+/]+=*")
# A host name's labels, as resolvers take them (underscores included), IDNA-encoded.
_LABEL = re.compile(r"[A-Za-z0-9_]([A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?")


@dataclass(frozen=True)
class Message:
    """One server-sent event: its name, the stream's last id, and its data lines joined."""

    event: str | None
    id: str | None
    data: str


def messages(lines: Iterable[str]) -> Iterator[Message]:
    """The server-sent events in a stream's lines, as the HTML standard reads an event stream:
    `field: value` lines, a blank line ending each message, `:` lines comments. A message
    with no data is not dispatched, and an unfinished one at the stream's end is dropped."""
    event: str | None = None
    last_id: str | None = None
    data: list[str] = []
    for line in lines:
        if not line:
            if data:
                yield Message(event, last_id, "\n".join(data))
            event, data = None, []
            continue
        if line.startswith(":"):
            continue
        name, _, value = line.partition(":")
        value = value.removeprefix(" ")
        if name == "event":
            event = value
        elif name == "data":
            data.append(value)
        elif name == "id" and "\0" not in value:
            last_id = value


def base_url(address: str) -> str:
    """The server's URL from an address: an http(s):// URL as given (a path kept, for an
    ingress that mounts the API under one), or host:port over http. `InvalidAddress`
    otherwise: its message is a predicate for the caller to name its subject, and never
    repeats the address, which might hold a login."""
    refused = InvalidAddress("is not an http(s):// URL or host:port")
    try:
        url = httpx.URL(address if "://" in address else f"http://{address}")
    except httpx.InvalidURL:
        raise refused from None
    if url.scheme not in ("http", "https") or not _is_host(url.raw_host.decode("ascii")):
        raise refused
    if url.port is not None and not 0 < url.port < 65536:
        raise refused
    if url.userinfo:
        raise InvalidAddress("holds a login; the client's one credential is its token")
    return str(url.copy_with(query=None, fragment=None)).rstrip("/")


def _is_host(host: str) -> bool:
    """Whether `host` is an IP address or a host name: never a space, a percent escape or an
    empty label, which a URL parser would carry along quoted."""
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return bool(host) and all(_LABEL.fullmatch(label) for label in host.split("."))
    return True


def bearer(token: str) -> str:
    """The Authorization header's value for `token`, or `InvalidToken`: an RFC 6750 bearer
    token is letters, digits and -._~+/ with trailing =, so no control character, space or
    non-ASCII character can reach the header, nor the error an HTTP library would raise quoting
    it."""
    if not _BEARER.fullmatch(token):
        raise InvalidToken("is not an RFC 6750 bearer token: letters, digits and -._~+/ with trailing =")
    return f"Bearer {token}"


def trust(ca: Path | None) -> ssl.SSLContext:
    """What an https:// address is verified against: the CA certificates in the file `ca`, or with
    None the system's trust, which a site can add its own CA to, unlike httpx's bundled roots
    (D-063). `InvalidCA` when `ca` cannot be read or holds no certificate, for each of which `ssl`
    raises an `OSError` (verified-facts.md)."""
    try:
        return ssl.create_default_context(cafile=ca)
    except OSError:
        raise InvalidCA("names no file of CA certificates that can be read") from None


class Client:
    """API 1's calls over one HTTP connection pool, synchronous."""

    def __init__(
        self,
        address: str,
        token: str,
        *,
        ca: Path | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        notice: Callable[[str], None] | None = None,
    ) -> None:
        """`ca` names the CA file an https:// address is verified against, the system's trust
        when None (`trust`). `transport` replaces the network and `sleep` the waits before a watch
        reconnects, for tests; `notice`, when given, is told once when a watch begins to
        reconnect."""
        self._url = base_url(address)
        self._http = httpx.Client(
            base_url=self._url,
            headers={"Authorization": bearer(token), "Accept": JSON_TYPES},
            transport=transport,
            verify=trust(ca),
            trust_env=False,
            timeout=TIMEOUT_S,
        )
        self._spoken = False
        self._sleep = sleep
        self._notice = notice

    def __repr__(self) -> str:
        return f"Client({self._url!r})"

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # meta

    def version(self) -> dict[str, Any]:
        """The server's versions; `UnsupportedVersion` when its API is not this client's."""
        doc = _document("GET", "/v1/version", self._send("GET", "/v1/version"))
        if doc.get("api") != API:
            raise UnsupportedVersion(f"the server speaks API {doc.get('api')!r}; this client speaks API {API}")
        self._spoken = True
        return doc

    # blueprints and bundles

    def put_blueprint(self, doc: Mapping[str, Any]) -> str:
        """File a blueprint; its id."""
        blueprint_id: str = _member("POST", "/v1/blueprints", self._call("POST", "/v1/blueprints", body=doc), "id", str)
        return blueprint_id

    def get_blueprint(self, blueprint_id: str) -> dict[str, Any]:
        """A filed blueprint."""
        return self._call("GET", f"/v1/blueprints/{_segment(blueprint_id)}")

    def build_bundle(self, blueprint_id: str) -> dict[str, Any]:
        """Compile a filed blueprint: the bundle's id, manifest, fidelity and findings."""
        return self._call("POST", "/v1/bundles", body={"blueprint_id": blueprint_id})

    def get_bundle(self, bundle_id: str) -> dict[str, Any]:
        """A filed bundle's id and manifest."""
        return self._call("GET", f"/v1/bundles/{_segment(bundle_id)}")

    def diff_bundles(self, from_id: str, to_id: str) -> dict[str, Any]:
        """What a step from one filed bundle to another changes."""
        return self._call("GET", f"/v1/bundles/{_segment(from_id)}/diff/{_segment(to_id)}")

    def list_drivers(self) -> list[dict[str, Any]]:
        """The drivers the core serves, sorted by name."""
        drivers: list[dict[str, Any]] = _member("GET", "/v1/drivers", self._call("GET", "/v1/drivers"), "drivers", list)
        return drivers

    # twins

    def list_twins(self) -> list[dict[str, Any]]:
        """Every twin's record, sorted by name."""
        twins: list[dict[str, Any]] = _member("GET", "/v1/twins", self._call("GET", "/v1/twins"), "twins", list)
        return twins

    def get_twin(self, name: str) -> tuple[dict[str, Any], str]:
        """A twin's record and its ETag, the revision quoted, for an If-Match."""
        path = f"/v1/twins/{_segment(name)}"
        response = self._respond("GET", path)
        etag = response.headers.get("etag")
        if etag is None:
            raise TransportError(f"GET {path} answered no ETag")
        return _document("GET", path, response), etag

    def apply_twin(
        self,
        name: str,
        spec: Mapping[str, Any],
        *,
        if_match: str | None = None,
        if_none_match: str | None = None,
        dry_run: bool = False,
    ) -> tuple[dict[str, Any], str | None]:
        """Write a twin's spec: the record and its ETag, or with `dry_run` the plan and no ETag."""
        path = f"/v1/twins/{_segment(name)}"
        headers = {k: v for k, v in (("If-Match", if_match), ("If-None-Match", if_none_match)) if v is not None}
        params = {"dry_run": "true"} if dry_run else None
        response = self._respond("PUT", path, params=params, body={"spec": dict(spec)}, headers=headers)
        return _document("PUT", path, response), response.headers.get("etag")

    def delete_twin(self, name: str, *, if_match: str | None = None) -> dict[str, Any]:
        """Ask for a twin's deletion: the record, deletion requested."""
        headers = {"If-Match": if_match} if if_match is not None else None
        return self._call("DELETE", f"/v1/twins/{_segment(name)}", headers=headers)

    def watch_twin(self, name: str, since_revision: int | None = None) -> Iterator[dict[str, Any]]:
        """Each WatchEvent of a twin, after `since_revision` when given, ending after DELETED, as
        API 1 ends the watch of one twin. A stream that ends before then is opened again after the
        last revision yielded (`_early_end`)."""
        path = f"/v1/twins/{_segment(name)}"
        if not self._spoken:
            self.version()
        revision, early = since_revision, 0
        while True:
            params = {"watch": "true"}
            if revision is not None:
                params["since_revision"] = str(revision)
            try:
                with contextlib.closing(self._stream(path, params, {}, reconnect=early > 0)) as stream:
                    for message in stream:
                        event = _data(path, message)
                        revision, early = _revision(path, event), 0
                        yield event
                        if event.get("type") == "DELETED":
                            return
                why = f"GET {self._url}{path} ended before its end"
            except _Interrupted as e:
                why = str(e)
            early += 1
            self._early_end(why, early)

    # runs

    def list_runs(self, twin: str | None = None) -> list[dict[str, Any]]:
        """Runs, newest first, of one twin when given."""
        params = {"twin": twin} if twin is not None else None
        doc = self._call("GET", "/v1/runs", params=params)
        runs: list[dict[str, Any]] = _member("GET", "/v1/runs", doc, "runs", list)
        return runs

    def get_run(self, run_id: str) -> dict[str, Any]:
        """One run, its verdict once it has ended."""
        return self._call("GET", f"/v1/runs/{_segment(run_id)}")

    def run_events(self, run_id: str, after: int = 0, *, timeout: httpx.Timeout | None = None) -> dict[str, Any]:
        """A run's events after the cursor `after`: an EventPage, under `timeout` when given, else
        the client's."""
        return self._call("GET", f"/v1/runs/{_segment(run_id)}/events", params={"after": str(after)},
                          timeout=timeout)

    def watch_run(self, run_id: str, after: int = 0) -> Iterator[dict[str, Any]]:
        """Each Event of a run after the cursor `after`, until the run has ended. The stream
        carries no mark of its end, so once it ends the run's event page says whether the run
        has; that page's events come first, being those a server that stopped as the run ended
        never sent. A stream that ends before the run does is opened again after the last event
        yielded (`_early_end`)."""
        path = f"/v1/runs/{_segment(run_id)}/events"
        if not self._spoken:
            self.version()
        cursor, early = after, 0
        while True:
            headers = {"Last-Event-ID": str(cursor)} if cursor else {}
            try:
                with contextlib.closing(self._stream(path, {"after": str(cursor)}, headers,
                                                     reconnect=early > 0)) as stream:
                    for message in stream:
                        event = _data(path, message)
                        cursor, early = _seq(path, event), 0
                        yield event
                # Read as the stream ends, when the server may be going away: given 5 s to connect, as a reconnect is.
                page = self.run_events(run_id, cursor, timeout=RECONNECT_TIMEOUT)
                events = _member("GET", path, page, "events", list)
                following = _member("GET", path, page, "next", int)
                ended = _member("GET", path, page, "ended", bool)
                for event in events:
                    cursor, early = _seq(path, event), 0
                    yield event
                cursor = following
                if ended:
                    return
                why = f"GET {self._url}{path} ended before its end"
            except _Interrupted as e:
                why = str(e)
            early += 1
            self._early_end(why, early)

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        """Ask a run to cancel: the run, cancelling."""
        return self._call("POST", f"/v1/runs/{_segment(run_id)}/cancel")

    def verify_twin(self, name: str) -> dict[str, Any]:
        """Read every node of the twin once and judge it: the verdict, a findings 1 document."""
        return self._call("POST", f"/v1/twins/{_segment(name)}/verifications", timeout=VERIFY_TIMEOUT)

    # the wire

    def _call(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
    ) -> dict[str, Any]:
        response = self._respond(method, path, params=params, body=body, headers=headers, timeout=timeout)
        return _document(method, path, response)

    def _respond(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
    ) -> httpx.Response:
        if not self._spoken:
            self.version()
        return self._send(method, path, params=params, body=body, headers=headers, timeout=timeout)

    def _send(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
    ) -> httpx.Response:
        """One request, under `timeout` when given, else the client's."""
        try:
            response = self._http.request(method, path, params=params, json=body, headers=headers,
                                          timeout=httpx.USE_CLIENT_DEFAULT if timeout is None else timeout)
        except httpx.HTTPError as e:
            raise self._failure(method, path, e) from e
        if not response.is_success:
            raise _refusal(method, path, response)
        return response

    def _stream(
        self, path: str, params: Mapping[str, str], headers: Mapping[str, str], *, reconnect: bool = False
    ) -> Generator[Message]:
        """One stream's messages, from its opening to its end or its failure; the caller has
        read the server's version. A `reconnect`'s open is given `RECONNECT_CONNECT_S` to connect."""
        # A watch can sit idle for as long as the loop works, so only its reads have no bound.
        timeout = httpx.Timeout(TIMEOUT_S, connect=RECONNECT_CONNECT_S if reconnect else TIMEOUT_S, read=None)
        try:
            with self._http.stream(
                "GET", path, params=params, headers={"Accept": EVENT_STREAM, **headers}, timeout=timeout
            ) as response:
                if not response.is_success:
                    response.read()
                    raise _refusal("GET", path, response)
                media = response.headers.get("content-type", "").partition(";")[0].strip()
                if media != EVENT_STREAM:
                    raise TransportError(f"GET {path} answered {media or 'no media type'}, not {EVENT_STREAM}")
                yield from messages(response.iter_lines())
        except httpx.HTTPError as e:
            raise self._failure("GET", path, e) from e

    def _early_end(self, why: str, early: int) -> None:
        """A watch's `early`th early end in a row, `why` it ended: given up past `RECONNECTS`,
        else said once at the first and waited out before the watch opens again."""
        if early > RECONNECTS:
            raise TransportError(f"{why}; not resumed after {RECONNECTS} reconnects")
        if early == 1 and self._notice is not None:
            self._notice(f"{why}; reconnecting")
        self._sleep(reconnect_delay(early))

    def _failure(self, method: str, path: str, e: httpx.HTTPError) -> TransportError:
        """A transport failure as the client raises it: `Untrusted` where the server's certificate
        failed verification, which no reconnect mends, else `_Interrupted`."""
        failed = f"{method} {self._url}{path} failed"
        verification = _failed_verification(e)
        if verification is not None:  # `ssl` sets its `verify_message`; one raised by another hand may have none
            said = getattr(verification, "verify_message", None) or "certificate verify failed"
            return Untrusted(f"{failed}: the server's certificate is not trusted: {said}")
        return _Interrupted(f"{failed}: {_said(e)}")


def _failed_verification(e: BaseException) -> ssl.SSLCertVerificationError | None:
    """The certificate verification that failed in `e`'s chain, if one did. httpcore's pool raises
    its `ConnectError` again `from None`, so the `ssl` error is its context, not its cause
    (verified-facts.md): the chain is followed through either."""
    seen: set[int] = set()
    found: BaseException | None = e
    while found is not None and id(found) not in seen:
        if isinstance(found, ssl.SSLCertVerificationError):
            return found
        seen.add(id(found))
        found = found.__cause__ or found.__context__
    return None


def _said(e: httpx.HTTPError) -> str:
    """What a transport failure says, for a message. A local protocol error is named by its
    type alone: it is the library refusing the request it was handed, and its text quotes the
    offending header, which may be the Authorization header."""
    local = isinstance(e, httpx.LocalProtocolError) or type(e).__module__.partition(".")[0] == "h11"
    return type(e).__name__ if local else (str(e) or type(e).__name__)


def _segment(value: str) -> str:
    """A path parameter, quoted so that it stays one segment; the server judges its form."""
    return quote(value, safe="")


def _refusal(method: str, path: str, response: httpx.Response) -> ProblemError | TransportError:
    """A non-2xx answer: the server's problem document, or no API 1 answer at all, which for a
    5xx is a proxy's while the server is away and so `_Interrupted`."""
    try:
        return ProblemError(response.status_code, problem.decode(response.json()))
    except (ValueError, Rejected):
        failure = _Interrupted if response.is_server_error else TransportError
        return failure(f"{method} {path} answered {response.status_code} with no problem document")


def _document(method: str, path: str, response: httpx.Response) -> dict[str, Any]:
    try:
        doc = response.json()
    except ValueError:
        doc = None
    if not isinstance(doc, dict):
        raise TransportError(f"{method} {path} answered {response.status_code} with no JSON document")
    return doc


def _member(method: str, path: str, doc: Mapping[str, Any], key: str, kind: type) -> Any:
    """A document's member the client answers, which must be there and of its kind."""
    value = doc.get(key)
    if not isinstance(value, kind):
        raise TransportError(f"{method} {path} answered a document with no {key} {kind.__name__}")
    return value


def _data(path: str, message: Message) -> dict[str, Any]:
    try:
        doc = json.loads(message.data)
    except ValueError:
        doc = None
    if not isinstance(doc, dict):
        raise TransportError(f"GET {path} sent an event whose data is no JSON document")
    return doc


def _revision(path: str, event: Mapping[str, Any]) -> int:
    """A WatchEvent's cursor: its object's revision."""
    found = event.get("object")
    revision = found.get("revision") if isinstance(found, dict) else None
    if not isinstance(revision, int) or isinstance(revision, bool):
        raise TransportError(f"GET {path} sent a WatchEvent with no object revision")
    return revision


def _seq(path: str, event: Any) -> int:
    """An Event's cursor: its seq."""
    seq = event.get("seq") if isinstance(event, dict) else None
    if not isinstance(seq, int) or isinstance(seq, bool):
        raise TransportError(f"GET {path} sent an Event with no seq")
    return seq
