"""The transport: the one module that speaks to Infrahub, over plain HTTP and httpx, with no SDK (D-083).

It sends `GET /api/info`, `GET /api/schema?branch=`, `GET /api/storage/object/<id>` and `POST /graphql/<branch,
percent-escaped>[?at=<at, verbatim, URL-encoded>]`, and nothing else: it never writes. Every GraphQL document is a
file under `queries/`, each one named `query`, and each call answers rows (rows.py), never Infrahub's JSON. A list is
read `PAGE` at a time until the total Infrahub answered for it, which is kept beside what was read, so that
`rows.incomplete` can hold the two to each other; a nested list is selected whole with its `count`, since Infrahub
answers one with no limit whole (design/verified-facts.md, "Infrahub 1.11.11"). The branch's event log, which grows
while it is read, is read `EVENTS_PAGE` at a time, newest first, down to the floor its caller gives. A time a row holds
is one Infrahub answered that reads as a time (`times.parse`): a stamp is compared and never sent, so one that is no
time is a fault of the answer, refused where it is read.

`connect` reads Infrahub's version once; one not in `SUPPORTED` is a warning, `infrahub.version.unverified`, carried on
every result of the connection and logged once. The token is held by the `Infrahub` alone, checked by the client's
bearer rule before any request, so that no HTTP library's complaint can quote it, and sent in the one header
`X-INFRAHUB-KEY`. Every failure is an `InfrahubError` whose text names what was being read, the branch and the time,
and keeps the status Infrahub answered. None holds the token: a transport failure's text has it replaced by
`<redacted>`, and the error is raised from nothing, since an httpx exception carries its request, whose headers hold it.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any, Self
from urllib.parse import quote

import httpx
from fylgja_core.client import base_url, bearer, trust
from fylgja_core.findings import Finding

from fylgja_infrahub import times
from fylgja_infrahub.rows import (
    Artifact,
    Attribute,
    Branch,
    CableEnd,
    CableStamp,
    Connector,
    Content,
    Device,
    End,
    End4,
    Event,
    Generated,
    Group,
    Kind,
    Listing,
    Port,
    Probe,
    Relationship,
    Schema,
    Stamp,
    Stamped,
)

# Rule ids. Callers and tests match on them (rules.md).
RULE_UNVERIFIED = "infrahub.version.unverified"

SUPPORTED: tuple[str, ...] = ("1.11.11",)
"""The versions of Infrahub the reader was verified on (design/verified-facts.md)."""

PAGE = 100
"""How many objects one request of a list asks for."""

EVENTS_PAGE = 50
"""How many events one request of the event log asks for: `InfrahubEvent` refuses a `limit` above 50
(design/verified-facts.md, "Infrahub 1.11.11")."""

MUTATED = "NodeMutatedEvent"
"""The event type of a node's own write."""

TIMEOUT_S = 60.0
"""Seconds one request is given."""

KEEPALIVE_S = 1.0
"""Seconds an idle connection is kept for the next request. Infrahub's server closes one idle for 2 s, and a request
sent 2 s after the last, on a connection kept for httpx's own 5 s, once went unanswered (design/verified-facts.md,
"Infrahub 1.11.11")."""

TOKEN = "FYLGJA_INFRAHUB_TOKEN"
"""The variable a refused token is named by: the command reads the token from it."""

REDACTED = "<redacted>"
"""What stands for the token in an error's text."""

QUOTED = 300
"""How many characters of a refusal's body that is no error document an error quotes."""

log = logging.getLogger("fylgja.infrahub")

_QUERIES = resources.files("fylgja_infrahub") / "queries"
_OPERATION = re.compile(r"query\s+([_A-Za-z][_0-9A-Za-z]*)")


class InfrahubError(Exception):
    """Infrahub refused a request, answered what is no answer, or was not reached. The text names what was being read,
    the branch and the time, and holds no token. `status` is the HTTP status Infrahub answered; where that is 200, the
    status its first GraphQL error carries at `extensions.http_status` (design/verified-facts.md); None where Infrahub
    was not reached."""

    def __init__(self, message: str, status: int | None) -> None:
        super().__init__(message)
        self.status = status


@cache
def _document(name: str) -> tuple[str, str]:
    """The text of `queries/<name>.graphql` and the name of its operation."""
    text = (_QUERIES / f"{name}.graphql").read_text()
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    found = _OPERATION.match(body.lstrip())
    if found is None:
        raise ValueError(f"queries/{name}.graphql names no operation")
    return text, found[1]


def _where(branch: str, at: str | None) -> str:
    return f"branch {branch}" if at is None else f"branch {branch}, at {at}"


class Infrahub:
    """One Infrahub, read through one pool of connections: a `rows.Source` and a context manager. Made by `connect`,
    which reads `version`; `unverified` is the warning every result carries where that version is not in
    `SUPPORTED`."""

    version: str
    unverified: Finding | None

    def __init__(self, http: httpx.Client, *, url: str, token: str) -> None:
        self._http = http
        self._url = url
        self._token = token
        self.version = ""
        self.unverified = None

    def __repr__(self) -> str:
        """The version alone, neither the token nor the address: a test's fixtures are listed by their repr."""
        return f"Infrahub(version={self.version!r})"

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def schema(self, branch: str) -> Schema:
        """The branch's schema, `GET /api/schema?branch=`: its hash, the key `main`, and its nodes and generics. An
        answer with no hash is an `InfrahubError`."""
        what, where = "reading the schema", _where(branch, None)
        answer = self._answer(self._send("GET", "/api/schema", what, where, params={"branch": branch}), what, where)
        try:
            return _schema(answer)
        except ValueError as e:
            raise self._error(what, where, 200, f"HTTP 200: answered {e}") from None

    def devices(self, branch: str, at: str | None, tag: str) -> Listing[Device]:
        """Every `DcimDevice` that carries the tag `tag`, with its platform, its manufacturer and its artifacts."""
        count, edges = self.paged("devices", "DcimDevice", {"tag": tag}, branch=branch, at=at)
        return Listing("DcimDevice", count, self._rows("devices", _device, _nodes(edges), branch, at))

    def ports(self, branch: str, at: str | None, devices: Sequence[str]) -> Listing[Port]:
        """Every `InterfacePhysical` of the devices whose ids are `devices`, with its connector and that connector's
        ends; with no device, none, and nothing is sent."""
        if not devices:
            return Listing("InterfacePhysical", 0, ())
        count, edges = self.paged("ports", "InterfacePhysical", {"devices": list(devices)}, branch=branch, at=at)
        return Listing("InterfacePhysical", count, self._rows("ports", _port, _nodes(edges), branch, at))

    def content(self, branch: str, at: str | None, storage_id: str) -> Content:
        """The bytes Infrahub stores under `storage_id`, `GET /api/storage/object/<storage_id, percent-escaped>`, and
        the status it answered, whatever that is, for the read to judge. The request carries no branch and no time: a
        storage id names one object, which Infrahub still serves after a rewrite has listed another in its place, so
        a read at a past time fetches the bytes it listed then (design/verified-facts.md, "Infrahub 1.11.11").
        `branch` and `at` name the read in an error; Infrahub not reached is an `InfrahubError`."""
        what, where = f"reading the content stored under {storage_id}", _where(branch, at)
        response = self._send("GET", f"/api/storage/object/{quote(storage_id, safe='')}", what, where)
        return Content(response.status_code, response.content)

    def stamps(self, branch: str, at: str | None, tag: str) -> Listing[Stamped]:
        """The stamps of every `DcimDevice` that carries the tag `tag`, each on the edge its node is read through: the
        device's, its platform's, its manufacturer's, each of its interfaces' of either kind and each address's under
        an interface; when the platform's `name` and the manufacturer's were last written; and each artifact by its id,
        with its checksum stamp, its definition's `artifact_name` and its query's id."""
        count, edges = self.paged("stamps", "DcimDevice", {"tag": tag}, branch=branch, at=at)
        return Listing("DcimDevice", count, self._rows("stamps", _stamped, _edges(edges), branch, at))

    def cable_stamps(self, branch: str, at: str | None, devices: Sequence[str]) -> Listing[CableStamp]:
        """The connector of every `InterfacePhysical` that has one, of the devices whose ids are `devices`, with its
        stamp on the port's `connector` edge, one row a port, by the port's id, as the list
        `InterfacePhysical.connector`; with no device, none, and nothing is sent."""
        what = "InterfacePhysical.connector"
        if not devices:
            return Listing(what, 0, ())
        variables = {"devices": list(devices)}
        count, edges = self.paged("cable_stamps", "InterfacePhysical", variables, branch=branch, at=at)
        return Listing(what, count, self._rows("cable_stamps", _cable_stamp, _nodes(edges), branch, at))

    def groups(self, branch: str, at: str | None, queries: Sequence[str]) -> Listing[Group]:
        """Every internal `CoreGraphQLQueryGroup` of the queries whose ids are `queries`, with the account that made it;
        with no query, none, and nothing is sent."""
        what = "CoreGraphQLQueryGroup"
        if not queries:
            return Listing(what, 0, ())
        count, edges = self.paged("query_groups", what, {"queries": list(queries)}, branch=branch, at=at)
        return Listing(what, count, self._rows("query_groups", _group, _edges(edges), branch, at))

    def events(self, branch: str, logs: Sequence[str], since: str, floor: str | None) -> Listing[Event]:
        """The events of the branches `logs`, in one list, since `since`, sent as given, newest first, `EVENTS_PAGE` a
        page on `branch`'s own endpoint and with no time: every page down to the first that holds an event no later
        than `floor`, or every page where it is None, the pages ending too at one answered short of what its `count`
        and `limit` say. The listing's `count` is what the pages read should hold by those two, less each event a page
        answered again: the log grows while it is paged, newest first, so a page can begin with the last event of the
        page before, which is kept once, and no event shifted across the pages is missed; an event logged after the
        first page was answered is not read in this call."""
        what, where = "reading Events", _where(branch, None)
        lowest = times.parse(floor) if floor is not None else None
        kept: dict[str, Event] = {}
        expected = offset = 0
        while True:
            asked = {"branches": list(logs), "since": since, "limit": EVENTS_PAGE, "offset": offset}
            page = self.graphql("events", asked, branch=branch, at=None).get("InfrahubEvent")
            answered = page.get("count") if isinstance(page, dict) else None
            got = page.get("edges") if isinstance(page, dict) else None
            if type(answered) is not int or not isinstance(got, list):
                raise self._error(what, where, 200, "HTTP 200: answered no count and edges of InfrahubEvent")
            rows = self._rows("events", _event, _nodes(got), branch, None)
            should = max(0, min(EVENTS_PAGE, answered - offset))
            before = set(kept)
            expected += should - sum(1 for event in rows if event.id in before)
            kept |= {event.id: event for event in rows if event.id not in kept}
            offset += len(got)
            reached = lowest is not None and any(times.parse(event.occurred_at) <= lowest for event in rows)
            if reached or not got or len(got) < should or offset >= answered:
                return Listing("InfrahubEvent", expected, tuple(kept.values()))

    def branch(self, name: str) -> Branch:
        """The branch `name` and when it was made, `Branch(name:)` on the branch's own endpoint; a branch Infrahub
        lists under no such name is an `InfrahubError`."""
        listed = self.graphql("branch", {"name": name}, branch=name, at=None).get("Branch")
        found = [b for b in listed if isinstance(b, dict) and b.get("name") == name] if isinstance(listed, list) else []
        what, where = "reading BranchPoint", _where(name, None)
        if not found:
            raise self._error(what, where, 200, f"HTTP 200: answered no branch {name}")
        try:
            branched_from = _time(found[0], "branched_from")
        except ValueError as e:
            raise self._error(what, where, 200, f"HTTP 200: answered {e}") from None
        if branched_from is None:
            raise self._error(what, where, 200, f"HTTP 200: answered no branched_from of {name}")
        return Branch(name, branched_from)

    def probes(self, branch: str, at: str | None) -> Listing[Probe]:
        """Every `FylgjaProbe`, with its ten attributes, read through the branch's endpoint at `at`: the kind is
        branch-agnostic, and a read pinned a microsecond after a write answers the probe as it stood then
        (design/verified-facts.md, "Infrahub 1.11.11")."""
        count, edges = self.paged("probes", "FylgjaProbe", {}, branch=branch, at=at)
        return Listing("FylgjaProbe", count, self._rows("probes", _probe, _nodes(edges), branch, at))

    def probe_stamps(self, branch: str, at: str | None) -> Listing[tuple[str, Stamp]]:
        """Every `FylgjaProbe`'s stamp, the `node_metadata` of its edge, by its id, read through the branch's endpoint
        at `at`, or as it stands where it is None."""
        count, edges = self.paged("probe_stamps", "FylgjaProbe", {}, branch=branch, at=at)
        return Listing("FylgjaProbe", count, self._rows("probe_stamps", _probe_stamp, _edges(edges), branch, at))

    def graphql(self, name: str, variables: Mapping[str, Any], *, branch: str, at: str | None) -> dict[str, Any]:
        """The `data` of the document `queries/<name>.graphql`, given `variables`, on `branch`'s endpoint and pinned at
        `at`, sent verbatim, where it is given. An answer with `errors`, under HTTP 200 too, is an `InfrahubError`."""
        document, operation = _document(name)
        what, where = f"reading {operation}", _where(branch, at)
        body = {"query": document, "variables": dict(variables), "operationName": operation}
        params = {"at": at} if at is not None else None
        answer = self._answer(
            self._send("POST", f"/graphql/{quote(branch, safe='')}", what, where, params=params, body=body), what, where
        )
        errors = answer.get("errors") if isinstance(answer, dict) else None
        if errors:
            status = _status(errors)
            said = "HTTP 200" if status == 200 else f"HTTP 200, http_status {status}"
            if status in (401, 403):
                raise self._refused(what, where, status, said)
            raise self._error(what, where, status, f"{said}: {_messages(errors)}")
        data = answer.get("data") if isinstance(answer, dict) else None
        if not isinstance(data, dict):
            raise self._error(what, where, 200, "HTTP 200: answered no data")
        return data

    def paged(
        self,
        name: str,
        root: str,
        variables: Mapping[str, Any],
        *,
        branch: str,
        at: str | None,
        size: int = PAGE,
    ) -> tuple[int, list[dict[str, Any]]]:
        """The edges of every page of the list `root` the document `name` selects, `size` at a time, and the largest
        `count` a page answered. It asks until it has read as many as that count or a page answers no edge, each page
        at the offset of the edges read so far, so a list answered short of its count ends it, to be judged by
        `rows.incomplete`."""
        count, edges = 0, list[dict[str, Any]]()
        while True:
            data = self.graphql(name, {**variables, "limit": size, "offset": len(edges)}, branch=branch, at=at)
            page = data.get(root)
            answered = page.get("count") if isinstance(page, dict) else None
            got = page.get("edges") if isinstance(page, dict) else None
            if type(answered) is not int or not isinstance(got, list):
                what = f"reading {_document(name)[1]}"
                raise self._error(what, _where(branch, at), 200, f"HTTP 200: answered no count and edges of {root}")
            count = max(count, answered)
            edges.extend(got)
            if not got or len(edges) >= count:
                return count, edges

    def _rows[T](
        self,
        name: str,
        project: Callable[[dict[str, Any]], T],
        items: list[dict[str, Any]],
        branch: str,
        at: str | None,
    ) -> tuple[T, ...]:
        """Each of `items`, the nodes (`_nodes`) or the whole edges (`_edges`) of a list the document `name` answered,
        as a row; one that is none is an `InfrahubError` saying what it lacks."""
        try:
            return tuple(project(item) for item in items)
        except ValueError as e:
            what = f"reading {_document(name)[1]}"
            raise self._error(what, _where(branch, at), 200, f"HTTP 200: answered {e}") from None

    def _read_version(self) -> None:
        """`version` from `GET /api/info`, and `unverified` where it is not in `SUPPORTED`, logged once."""
        what = "reading Infrahub's version"
        answer = self._answer(self._send("GET", "/api/info", what, None), what, None)
        version = answer.get("version") if isinstance(answer, dict) else None
        if not isinstance(version, str) or not version:
            raise self._error(what, None, 200, "HTTP 200: answered no version")
        self.version = version
        if version not in SUPPORTED:
            message = (
                f"Infrahub is version {version}, and this reader is verified on {', '.join(SUPPORTED)} alone, so it "
                "may misread what Infrahub answers."
            )
            self.unverified = Finding(rule=RULE_UNVERIFIED, severity="warning", object=version, message=message)
            log.warning(message)

    def _send(
        self,
        method: str,
        path: str,
        what: str,
        where: str | None,
        *,
        params: Mapping[str, str] | None = None,
        body: object | None = None,
    ) -> httpx.Response:
        try:
            return self._http.request(method, path, params=params, json=body)
        except httpx.HTTPError as e:
            # Hidden before it is bound: the exception's text can hold the token, and a traceback can show its locals.
            said = self._hide(f"Infrahub at {self._url} was not reached: {type(e).__name__}: {e}")
            failure = self._error(what, where, None, said)
        raise failure from None

    def _answer(self, response: httpx.Response, what: str, where: str | None) -> Any:
        """The JSON Infrahub answered under HTTP 200; any other status is an `InfrahubError` in Infrahub's words."""
        status = response.status_code
        if status in (401, 403):
            raise self._refused(what, where, status, f"HTTP {status}")
        if status != 200:
            raise self._error(what, where, status, f"HTTP {status}: {self._words(response)}")
        try:
            return json.loads(response.content)
        except ValueError:
            raise self._error(what, where, 200, "HTTP 200: answered no JSON") from None

    def _refused(self, what: str, where: str | None, status: int, said: str) -> InfrahubError:
        """A refused token, named by its variable, quoting nothing of the answer."""
        if status == 401:
            return self._error(what, where, status, f"{said}: Infrahub refused the token {TOKEN} holds")
        return self._error(what, where, status, f"{said}: the token {TOKEN} holds may not read it")

    def _words(self, response: httpx.Response) -> str:
        """Infrahub's own words in a refusal, the token replaced: its errors' messages where the body carries them,
        else the body, cut at `QUOTED` characters."""
        try:
            body = json.loads(response.content)
        except ValueError:
            body = None
        if isinstance(body, dict):
            for key in ("errors", "detail", "message"):
                if body.get(key):
                    return self._hide(_messages(body[key]))
        text = self._hide(response.text).strip()
        return text[:QUOTED] if text else "an empty body"

    def _hide(self, text: str) -> str:
        return text.replace(self._token, REDACTED)

    def _error(self, what: str, where: str | None, status: int | None, said: str) -> InfrahubError:
        place = f" ({where})" if where is not None else ""
        return InfrahubError(" ".join(self._hide(f"{what}{place}: {said}").split()), status)


def connect(
    address: str, token: str, *, ca: Path | None = None, transport: httpx.BaseTransport | None = None
) -> Infrahub:
    """The `Infrahub` at `address`, an http(s):// URL or host:port, read with `token`, its version read. An `https://`
    address is verified against the CA file `ca`, or the system's trust where it is None. `InvalidAddress`,
    `InvalidToken` and `InvalidCA` (fylgja_core.client) are raised before any request, each a predicate that repeats
    nothing; `transport` replaces the network, for tests."""
    url = base_url(address)
    bearer(token)
    http = httpx.Client(
        base_url=url,
        headers={"X-INFRAHUB-KEY": token},
        transport=transport,
        verify=trust(ca),
        timeout=TIMEOUT_S,
        limits=httpx.Limits(keepalive_expiry=KEEPALIVE_S),
        trust_env=False,
    )
    conn = Infrahub(http, url=url, token=token)
    try:
        conn._read_version()
    except BaseException:
        conn.close()
        raise
    return conn


def _status(errors: object) -> int:
    """The status the first GraphQL error carries at `extensions.http_status`; 200 where it carries none."""
    first = errors[0] if isinstance(errors, list) and errors else errors
    extensions = first.get("extensions") if isinstance(first, dict) else None
    status = extensions.get("http_status") if isinstance(extensions, dict) else None
    return status if type(status) is int else 200


def _messages(errors: object) -> str:
    """Each error's message: an object's `message`, or a string as it is."""
    said = []
    for error in errors if isinstance(errors, list) else [errors]:
        message = error.get("message") if isinstance(error, dict) else error
        said.append(str(message if message is not None else error))
    return "; ".join(said)


def _nodes(edges: Sequence[object]) -> list[dict[str, Any]]:
    """The nodes of a list's edges; an edge with no node is left out, so that the list falls short of its count."""
    return [edge["node"] for edge in _edges(edges)]


def _edges(edges: Sequence[object]) -> list[dict[str, Any]]:
    """The edges of a list that hold a node, each whole, its `node_metadata` beside its node; an edge with no node is
    left out, so that the list falls short of its count."""
    return [edge for edge in edges if isinstance(edge, dict) and isinstance(edge.get("node"), dict)]


def _id(node: Mapping[str, Any], kind: str) -> str:
    found = node.get("id")
    if not isinstance(found, str) or not found:
        raise ValueError(f"a {kind} with no id")
    return found


def _value(node: Mapping[str, Any] | None, field: str) -> str | None:
    """An attribute's value, `{field: {"value": ...}}`; None where it is null or no string."""
    attribute = node.get(field) if node is not None else None
    value = attribute.get("value") if isinstance(attribute, dict) else None
    return value if isinstance(value, str) else None


def _required(node: Mapping[str, Any], field: str, kind: str) -> str:
    value = _value(node, field)
    if value is None:
        raise ValueError(f"a {kind} with no {field}")
    return value


def _peer(node: Mapping[str, Any] | None, field: str) -> dict[str, Any] | None:
    """A relationship's node, `{field: {"node": ...}}`; None where it is null."""
    relationship = node.get(field) if node is not None else None
    peer = relationship.get("node") if isinstance(relationship, dict) else None
    return peer if isinstance(peer, dict) else None


def _typename(node: Mapping[str, Any], kind: str) -> str:
    found = node.get("__typename")
    if not isinstance(found, str) or not found:
        raise ValueError(f"a {kind} with no __typename")
    return found


def _listing[T](
    node: Mapping[str, Any],
    field: str,
    what: str,
    project: Callable[[dict[str, Any]], T],
    pick: Callable[[Sequence[object]], list[dict[str, Any]]] = _nodes,
) -> Listing[T]:
    """A nested list, `{field: {"count": ..., "edges": [...]}}`, as the `Listing` `what`: each of its nodes projected,
    or each of its whole edges where `pick` is `_edges`."""
    nested = node.get(field)
    count = nested.get("count") if isinstance(nested, dict) else None
    edges = nested.get("edges") if isinstance(nested, dict) else None
    if type(count) is not int or not isinstance(edges, list):
        raise ValueError(f"{what} with no count and edges")
    return Listing(what, count, tuple(project(item) for item in pick(edges)))


def _time(node: Mapping[str, Any] | None, field: str) -> str | None:
    """A time Infrahub answered at `field`, as it answered it; None where it is null. One that is no time is a
    `ValueError` quoting it."""
    found = node.get(field) if node is not None else None
    if found is None:
        return None
    try:
        times.parse(found if isinstance(found, str) else "")
    except ValueError:
        raise ValueError(f"the {field} {found!r}, which is no time") from None
    return str(found)


def _id_at(node: Mapping[str, Any] | None, field: str) -> str | None:
    """The id at `field`, `{field: {"id": ...}}`, an account's or a peer's; None where there is none."""
    held = node.get(field) if node is not None else None
    found = held.get("id") if isinstance(held, dict) else None
    return found if isinstance(found, str) and found else None


def _stamp(meta: object) -> Stamp:
    """A `node_metadata` as a `Stamp`; null as a stamp of nothing."""
    if not isinstance(meta, dict):
        return Stamp(None, None, None)
    return Stamp(_time(meta, "updated_at"), _id_at(meta, "updated_by"), _time(meta, "created_at"))


def _edged(node: Mapping[str, Any], field: str) -> object:
    """The `node_metadata` of the relationship's edge at `field`, `{field: {"node_metadata": ..., "node": ...}}`."""
    edge = node.get(field)
    return edge.get("node_metadata") if isinstance(edge, dict) else None


def _interface(edge: dict[str, Any]) -> tuple[str, Stamp]:
    return _id(edge["node"], "interface"), _stamp(edge.get("node_metadata"))


def _probe_stamp(edge: dict[str, Any]) -> tuple[str, Stamp]:
    return _id(edge["node"], "FylgjaProbe"), _stamp(edge.get("node_metadata"))


def _stamped(edge: dict[str, Any]) -> Stamped:
    node = edge["node"]
    name = _required(node, "name", "DcimDevice")
    ids, shared = [_id(node, "DcimDevice")], list[Stamp]()
    platform_name_at: str | None = None
    manufacturer_name_at: str | None = None
    platform = _peer(node, "platform")
    if platform is not None:
        ids.append(_id(platform, f"{name}'s platform"))
        shared.append(_stamp(_edged(node, "platform")))
        platform_name_at = _named_at(platform)
        manufacturer = _peer(platform, "manufacturer")
        if manufacturer is not None:
            ids.append(_id(manufacturer, f"{name}'s manufacturer"))
            shared.append(_stamp(_edged(platform, "manufacturer")))
            manufacturer_name_at = _named_at(manufacturer)
    interfaces = _listing(node, "interfaces", f"{name}.interfaces", _interface, _edges)
    # The interfaces' addresses, one list of all of them: each interface's nested list counted into its total.
    addresses: list[tuple[str, str, Stamp]] = []
    counted = 0
    for interface in _nodes(node["interfaces"]["edges"]):
        if "ip_addresses" not in interface:
            continue  # no InterfaceLayer3, whose addresses alone the document selects
        held = _listing(interface, "ip_addresses", f"{name}.ip_addresses", _interface, _edges)
        counted += held.count
        addresses += [(_id(interface, "interface"), address, stamp) for address, stamp in held.items]
    return Stamped(
        ids[0],
        name,
        (*ids, *(interface for interface, _ in interfaces.items), *(address for _, address, _ in addresses)),
        _stamp(edge.get("node_metadata")),
        tuple(shared),
        platform_name_at,
        manufacturer_name_at,
        interfaces,
        Listing(f"{name}.ip_addresses", counted, tuple(addresses)),
        _listing(node, "artifacts", f"{name}.artifacts", _generated),
    )


def _generated(node: dict[str, Any]) -> Generated:
    definition = _peer(node, "definition")
    name = _value(definition, "artifact_name")
    if name is None:
        raise ValueError("a CoreArtifact with no definition's artifact_name")
    checksum = node.get("checksum")
    query = _peer(_peer(definition, "transformation"), "query")
    found = query.get("id") if query is not None else None
    return Generated(
        _id(node, "CoreArtifact"),
        name,
        _time(checksum if isinstance(checksum, dict) else None, "updated_at"),
        found if isinstance(found, str) and found else None,
    )


def _cable_stamp(node: dict[str, Any]) -> CableStamp:
    device = _peer(node, "device")
    if device is None:
        raise ValueError("an InterfacePhysical with no device")
    connector = _peer(node, "connector")
    if connector is None:
        raise ValueError("an InterfacePhysical listed by its connector with none")
    found, label = _id(connector, "connector"), _value(connector, "label")
    return CableStamp(
        found,
        _id(node, "InterfacePhysical"),
        _id(device, "InterfacePhysical's device"),
        _stamp(_edged(node, "connector")),
        _listing(connector, "connected_endpoints", f"{label or found}.connected_endpoints", _cable_end),
    )


def _cable_end(end: dict[str, Any]) -> CableEnd:
    """An end of a connector: on an interface, when its name and its device's were last written; on anything else,
    its id alone."""
    device = _peer(end, "device")
    return CableEnd(
        _id(end, "connector's end"),
        _named_at(end),
        _id(device, "end's device") if device is not None else None,
        _named_at(device),
    )


def _named_at(node: Mapping[str, Any] | None) -> str | None:
    """When the node's `name` was last written, `{name: {updated_at: ...}}`; None where Infrahub answered none."""
    name = node.get("name") if node is not None else None
    return _time(name if isinstance(name, dict) else None, "updated_at")


def _group(edge: dict[str, Any]) -> Group:
    meta = edge.get("node_metadata")
    made_by = _id_at(meta if isinstance(meta, dict) else None, "created_by")
    return Group(_id(edge["node"], "CoreGraphQLQueryGroup"), made_by)


def _event(node: dict[str, Any]) -> Event:
    name, occurred = node.get("event"), _time(node, "occurred_at")
    if not isinstance(name, str) or not name or occurred is None:
        raise ValueError("an InfrahubEvent with no event or no occurred_at")
    logged = node.get("branch")
    if not isinstance(logged, str) or not logged:
        raise ValueError("an InfrahubEvent with no branch")
    primary = node.get("primary_node") if isinstance(node.get("primary_node"), dict) else None
    kind, primary_id = (primary.get("kind"), primary.get("id")) if primary is not None else (None, None)
    account = node.get("account_id")
    return Event(
        _id(node, "InfrahubEvent"),
        name,
        occurred,
        node.get("__typename") == MUTATED,
        kind if isinstance(kind, str) and kind else None,
        primary_id if isinstance(primary_id, str) and primary_id else None,
        account if isinstance(account, str) and account else None,
        tuple(_text(a, "name", "an event's attribute") for a in _list(node, "attributes")),
        tuple((_text(r, "name", "an event's relationship"), _id_at(r, "peer")) for r in _list(node, "relationships")),
        tuple(_text(r, "id", "an event's related node") for r in _list(node, "related_nodes")),
        logged,
    )


def _list(node: Mapping[str, Any], field: str) -> list[dict[str, Any]]:
    """The list of objects at `field`, none where it is absent or null; anything else is a `ValueError`."""
    found = node.get(field)
    if found is None:
        return []
    if not isinstance(found, list) or not all(isinstance(entry, dict) for entry in found):
        raise ValueError(f"an InfrahubEvent whose {field} is no list of objects")
    return found


def _device(node: dict[str, Any]) -> Device:
    name = _required(node, "name", "DcimDevice")
    platform = _peer(node, "platform")
    return Device(
        _id(node, "DcimDevice"),
        name,
        _value(platform, "name"),
        _value(_peer(platform, "manufacturer"), "name"),
        _listing(node, "artifacts", f"{name}.artifacts", _artifact),
    )


def _artifact(node: dict[str, Any]) -> Artifact:
    definition = _value(_peer(node, "definition"), "artifact_name")
    if definition is None:
        raise ValueError("a CoreArtifact with no definition's artifact_name")
    return Artifact(
        _id(node, "CoreArtifact"),
        definition,
        _value(node, "status"),
        _value(node, "checksum"),
        _value(node, "storage_id"),
    )


def _port(node: dict[str, Any]) -> Port:
    device = _peer(node, "device")
    if device is None:
        raise ValueError("an InterfacePhysical with no device")
    connector = _peer(node, "connector")
    return Port(
        _id(node, "InterfacePhysical"),
        _id(device, "InterfacePhysical's device"),
        _required(node, "name", "InterfacePhysical"),
        _value(node, "role"),
        _value(node, "status"),
        _connector(connector) if connector is not None else None,
    )


def _connector(node: dict[str, Any]) -> Connector:
    found, label = _id(node, "connector"), _value(node, "label")
    return Connector(
        found,
        _typename(node, "connector"),
        label,
        _listing(node, "connected_endpoints", f"{label or found}.connected_endpoints", _end),
    )


def _end(node: dict[str, Any]) -> End:
    device = _peer(node, "device")
    return End(
        _id(node, "connector's end"),
        _typename(node, "connector's end"),
        _id(device, "end's device") if device is not None else None,
        _value(node, "name"),
    )


def _probe(node: dict[str, Any]) -> Probe:
    """A `FylgjaProbe` with each attribute as Infrahub answered it, a null one None: whether the probe is one the
    declaration admits is the read's to judge, a finding naming the probe, not a fault of the answer."""

    def end(side: str) -> End4:
        device, interface, address, gateway = (
            _value(node, f"{side}_{field}") for field in ("device", "interface", "address", "gateway")
        )
        return device, interface, address, gateway

    return Probe(_id(node, "FylgjaProbe"), _value(node, "name"), _value(node, "format"), end("a"), end("b"))


def _schema(doc: object) -> Schema:
    """The schema `GET /api/schema` answered, as rows; a `ValueError` naming what it lacks."""
    if not isinstance(doc, dict):
        raise ValueError("no schema")
    found = doc.get("main")
    if not isinstance(found, str) or not found:
        raise ValueError("no schema hash")
    return Schema(found, _kinds(doc.get("nodes"), "nodes"), _kinds(doc.get("generics"), "generics"))


def _kinds(entries: object, what: str) -> dict[str, Kind]:
    if not isinstance(entries, list) or not all(isinstance(entry, dict) for entry in entries):
        raise ValueError(f"no list of {what}")
    kinds = {}
    for entry in entries:
        kind = _text(entry, "kind", f"an entry of {what}")
        attributes = {
            _text(a, "name", f"an attribute of {kind}"): Attribute(
                _text(a, "kind", f"an attribute of {kind}"),
                _flag(a, "optional", f"an attribute of {kind}"),
                tuple(_text(choice, "name", f"a choice of {kind}") for choice in a.get("choices") or ()),
            )
            for a in _entries(entry, "attributes", kind)
        }
        relationships = {
            _text(r, "name", f"a relationship of {kind}"): Relationship(
                _text(r, "peer", f"a relationship of {kind}"),
                _text(r, "kind", f"a relationship of {kind}"),
                _text(r, "cardinality", f"a relationship of {kind}"),
                _flag(r, "optional", f"a relationship of {kind}"),
            )
            for r in _entries(entry, "relationships", kind)
        }
        used_by = entry.get("used_by") or []
        if not isinstance(used_by, list) or not all(isinstance(user, str) for user in used_by):
            raise ValueError(f"{kind} with a used_by that is no list of kinds")
        kinds[kind] = Kind(attributes, relationships, tuple(used_by))
    return kinds


def _entries(entry: dict[str, Any], field: str, kind: str) -> list[dict[str, Any]]:
    found = entry.get(field)
    if not isinstance(found, list) or not all(isinstance(item, dict) for item in found):
        raise ValueError(f"{kind} with no list of {field}")
    return found


def _text(entry: object, field: str, what: str) -> str:
    found = entry.get(field) if isinstance(entry, dict) else None
    if not isinstance(found, str) or not found:
        raise ValueError(f"{what} with no {field}")
    return found


def _flag(entry: dict[str, Any], field: str, what: str) -> bool:
    found = entry.get(field)
    if not isinstance(found, bool):
        raise ValueError(f"{what} with no {field}")
    return found
