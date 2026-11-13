"""The transport: the one module that speaks to NetBox, over plain HTTP and httpx, with no client library of
NetBox's (D-096).

It sends `GET /api/status/` and `GET` lists of `/api/plugins/branching/branches/`, `/api/extras/tags/`,
`/api/dcim/devices/`, `/api/dcim/platforms/`, `/api/dcim/interfaces/`, `/api/dcim/cables/`,
`/api/extras/config-contexts/`, where the probes are declared, and `/api/core/object-changes/`, the changelog, and
`POST /api/dcim/devices/<id>/render-config/` with no body, a device's
render, which adds no row to a changelog (design/verified-facts.md, "A branch has a changelog of its own"); nothing
else: it never writes. Each call answers rows (rows.py), never NetBox's JSON. A list is read `PAGE` at a time, by
`limit` and the offset of what was read, until the `count` NetBox answered for it, which is kept beside what was read
so that `rows.incomplete` can hold the two to each other; NetBox's `next` is never followed, since it holds NetBox's
own address, nor is a redirect. A list by ids asks `IDS` of them a request. Every row is held to what was asked, since
NetBox answers the whole list to a parameter it does not know (design/verified-facts.md, "NetBox 4.7.5 with
netbox-branching 1.2.3"): a row of another name, id, tag or device than was asked is an error, never a row, and so is
a change at or below the id it was asked above.

`connect` reads NetBox's version and the branching plugin's once; a pair not in `SUPPORTED` is a warning,
`netbox.version.unverified`, carried on every result of the connection and logged once. The token is held by the
`NetBox` alone, checked by the client's bearer rule before any request, so that no HTTP library's complaint can quote
it, and sent as `Authorization: Bearer <token>`, NetBox's v2 token. A branch is selected by its `schema_id` in the
header `X-NetBox-Branch`; `main` is read with none. Every failure is a `NetBoxError` whose text names what was being
read and the branch, `branch <name>` or `main`, and keeps the status NetBox answered. None holds the token: NetBox's
own words and a transport failure's text have it, and each half of it, replaced by `<redacted>`, and the error is
raised from nothing, since an httpx exception carries its request, whose headers hold it.
"""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol, Self

import httpx
from fylgja_core.client import base_url, bearer, trust
from fylgja_core.findings import Finding

from fylgja_netbox.rows import Branch, Cable, Change, Context, Device, End, Listing, Platform, Port, Rendered, Tag

# Rule ids. Callers and tests match on them (rules.md).
RULE_UNVERIFIED = "netbox.version.unverified"

SUPPORTED: tuple[tuple[str, str], ...] = (("4.7.5", "1.2.3"),)
"""The pairs of NetBox's version and the branching plugin's the reader was verified on, NetBox's first
(design/verified-facts.md, "NetBox 4.7.5 with netbox-branching 1.2.3")."""

PAGE = 100
"""How many rows one request of a list asks for: NetBox answered a page of 100 whole (design/verified-facts.md)."""

IDS = 50
"""The most ids one request of a list by ids names."""

TIMEOUT_S = 60.0
"""Seconds one request is given, a first value and no measurement of need, in place of httpx's own 5 s. The slowest
of the reader's requests read was a page of 100 interfaces under a branch's header, 1.21 s, and in another run the
devices by their tag, 1.04 s, each by the reader's token (design/verified-facts.md, "NetBox 4.7.5 with
netbox-branching 1.2.3"); 60 s is about 50 times the slowest, 1.21 s, a derivation."""

TOKEN = "FYLGJA_NETBOX_TOKEN"
"""The variable a refused token is named by: the command reads the token from it."""

REDACTED = "<redacted>"
"""What stands for the token, or a half of it, in an error's text."""

QUOTED = 300
"""How many characters of NetBox's own words an error quotes."""

HALF = 8
"""The fewest characters a half of the token has for it to be replaced on its own: a shorter one would match ordinary
words. NetBox's v2 token, `nbt_<key>.<token>`, has a key of 12 and a token of 40."""

STATUS = "/api/status/"
BRANCHES = "/api/plugins/branching/branches/"
TAGS = "/api/extras/tags/"
DEVICES = "/api/dcim/devices/"
PLATFORMS = "/api/dcim/platforms/"
INTERFACES = "/api/dcim/interfaces/"
CABLES = "/api/dcim/cables/"
CONTEXTS = "/api/extras/config-contexts/"
CHANGES = "/api/core/object-changes/"

PLUGIN = "netbox_branching"
"""The branching plugin's name among those `/api/status/` names."""

log = logging.getLogger("fylgja.netbox")

Params = Sequence[tuple[str, str]]


class NetBoxError(Exception):
    """NetBox refused a request, answered what is no answer, or was not reached. The text names what was being read
    and the branch, and holds no token. `status` is the HTTP status NetBox answered, 200 for an answer that is no
    answer to what was asked, and None where NetBox was not reached."""

    def __init__(self, message: str, status: int | None) -> None:
        super().__init__(message)
        self.status = status


def _where(branch: Branch | None) -> str:
    return f"branch {branch.name}" if branch is not None else "main"


class Named(Protocol):
    """A row found by its name: a tag, a branch, a configuration context."""

    @property
    def name(self) -> str: ...


def named[T: Named](listing: Listing[T], name: str, *, branch: str | None) -> T | None:
    """The one row of `listing` named `name`, None where it holds none. NetBox's installed source holds a tag's, a
    branch's and a configuration context's name unique (design/verified-facts.md, read in the source and not run), and
    the reader does not rely on it: where the name answers more than one row, which of them the read would take cannot
    be told, so that is an error naming the list, the name and the rows, raised before anything is built on one.
    `branch` is the name of the branch read, None for `main`."""
    held = [row for row in listing.items if row.name == name]
    if len(held) > 1:
        where = f"branch {branch}" if branch is not None else "main"
        said = f"HTTP 200: answered {len(held)} rows named {name}, where the read takes the one object of a name"
        raise NetBoxError(f"reading {listing.what} ({where}): {said}", 200)
    return held[0] if held else None


class NetBox:
    """One NetBox, read through one pool of connections: a `rows.Source` and a context manager. Made by `connect`,
    which reads `version`, NetBox's own, and `branching`, the branching plugin's, None where NetBox names none;
    `unverified` is the warning every result carries where the pair is not in `SUPPORTED`."""

    version: str
    branching: str | None
    unverified: Finding | None

    def __init__(self, http: httpx.Client, *, url: str, token: str) -> None:
        self._http = http
        self._url = url
        self._token = token
        self._hidden = _parts(token)
        self.version = ""
        self.branching = None
        self.unverified = None

    def __repr__(self) -> str:
        """The two versions alone, neither the token nor the address: a test's fixtures are listed by their repr."""
        return f"NetBox(version={self.version!r}, branching={self.branching!r})"

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._http.close()

    def branches(self, name: str) -> Listing[Branch]:
        """Every branch named `name`, read under no branch's header, as the plugin lists them by `?name=`."""
        what = "netbox_branching.branch"
        count, results = self.listed(BRANCHES, what, [("name", name)], branch=None)
        rows = tuple(self._row(what, None, result, _branch) for result in results)
        for row in rows:
            if row.name != name:
                raise self._unasked(what, None, f"{row.id} named {row.name}")
        return Listing(what, count, rows)

    def tags(self, branch: Branch | None, name: str) -> Listing[Tag]:
        """Every tag named `name`, by `?name=`."""
        what = "extras.tag"
        count, results = self.listed(TAGS, what, [("name", name)], branch=branch)
        rows = tuple(self._row(what, branch, result, _tag) for result in results)
        for row in rows:
            if row.name != name:
                raise self._unasked(what, branch, f"{row.id} named {row.name}")
        return Listing(what, count, rows)

    def devices(self, branch: Branch | None, tag: int) -> Listing[Device]:
        """Every device that carries the tag whose id is `tag`, by `?tag_id=`."""
        what = "dcim.device"
        count, results = self.listed(DEVICES, what, [("tag_id", str(tag))], branch=branch)
        rows = []
        for result in results:
            row = self._row(what, branch, result, _device)
            if tag not in self._row(what, branch, result, _tagged):
                raise self._unasked(what, branch, f"{row.id} without the tag {tag}")
            rows.append(row)
        return Listing(what, count, tuple(rows))

    def platforms(self, branch: Branch | None, ids: Sequence[int]) -> Listing[Platform]:
        """The platforms whose ids are `ids`, by `?id=`; with no id, none, and nothing is sent."""
        return self._by_ids(PLATFORMS, "dcim.platform", "id", ids, branch, _platform, lambda row: row.id)

    def ports(self, branch: Branch | None, devices: Sequence[int]) -> Listing[Port]:
        """Every interface, whatever its type, of the devices whose ids are `devices`, by `?device_id=`; with no
        device, none, and nothing is sent."""
        return self._by_ids(
            INTERFACES, "dcim.interface", "device_id", devices, branch, _port, lambda row: row.device, "dcim.device"
        )

    def cables(self, branch: Branch | None, ids: Sequence[int]) -> Listing[Cable]:
        """The cables whose ids are `ids`, by `?id=`; with no id, none, and nothing is sent."""
        return self._by_ids(CABLES, "dcim.cable", "id", ids, branch, _cable, lambda row: row.id)

    def contexts(self, branch: Branch | None, name: str) -> Listing[Context]:
        """Every configuration context named `name`, by `?name=`, each with its `data` as NetBox answered it."""
        what = "extras.configcontext"
        count, results = self.listed(CONTEXTS, what, [("name", name)], branch=branch)
        rows = tuple(self._row(what, branch, result, _context) for result in results)
        for row in rows:
            if row.name != name:
                raise self._unasked(what, branch, f"{row.id} named {row.name}")
        return Listing(what, count, rows)

    def render(self, branch: Branch | None, device: int) -> Rendered:
        """What NetBox renders for the device whose id is `device`, by `POST <device>/render-config/` with
        `Accept: text/plain` and no body, under `branch`'s header: the status and the bytes, for the read to judge
        (renders.judge), with the content type NetBox gave them, whatever the status but 401 and 403, a refused
        token, which are a `NetBoxError` as on every other request. A 200's bytes are the configuration, verbatim;
        another status's are NetBox's words, which a finding quotes, so the token, and each half of it, is replaced in
        them, and in the content type, which a finding quotes whatever the status."""
        doing, where = f"rendering dcim.device {device}", _where(branch)
        path = f"{DEVICES}{device}/render-config/"
        response = self._send("POST", path, doing, where, branch, accept="text/plain")
        status = response.status_code
        if status in (401, 403):
            raise self._refused(doing, where, status)
        body = response.content
        if status != 200:
            for part in self._hidden:
                body = body.replace(part.encode(), REDACTED.encode())
        given = response.headers.get("Content-Type")
        return Rendered(status, body, self._hide(given) if given is not None else None)

    def latest(self, branch: Branch | None) -> int | None:
        """The highest id of the changelog read from, `main`'s with no branch and the branch's under its header, by
        `?limit=1&ordering=-id`; None where it holds no row, `count 0`."""
        top = self._first(branch, [])[1]
        return top.id if top is not None else None

    def counted(self, branch: Branch | None, upto: int) -> int:
        """How many rows that changelog holds whose id is at or below `upto`, by `?id__lte=` with `limit=1` and
        `ordering=-id`, its `count`: NetBox honours `id__lte` (design/verified-facts.md, "An upper bound on the id"),
        and a row above `upto` answered is an error, since an unknown parameter answers the whole list."""
        count, top = self._first(branch, [("id__lte", str(upto))])
        if top is not None and top.id > upto:
            raise self._unasked("core.objectchange", branch, str(top.id))
        return count

    def _first(self, branch: Branch | None, params: Params) -> tuple[int, Change | None]:
        """The `count` of the changelog asked with `params`, `limit=1` and `ordering=-id`, and its row of the highest
        id, None where it holds none. An answer of other than one row to a count, or of a row to none, is an error."""
        what = "core.objectchange"
        doing, where = f"reading {what}", _where(branch)
        answer = self._get(CHANGES, what, branch, [*params, ("limit", "1"), ("ordering", "-id")])
        count = answer.get("count") if isinstance(answer, dict) else None
        got = answer.get("results") if isinstance(answer, dict) else None
        if type(count) is not int or not isinstance(got, list):
            raise self._error(doing, where, 200, "HTTP 200: answered no count and results")
        if len(got) > 1:
            raise self._error(doing, where, 200, f"HTTP 200: answered {len(got)} rows to a limit of 1")
        if bool(count) != bool(got):
            held = "a row" if got else "no row"
            raise self._error(doing, where, 200, f"HTTP 200: answered a count of {count} and {held}")
        return count, self._row(what, branch, got[0], _change) if got else None

    def changes(self, branch: Branch | None, after: int | None) -> Listing[Change]:
        """Every row of that changelog whose id is above `after`, by `?id__gt=` and `ordering=id`, every row where it
        is None, read whole by the pager; a row at or below `after` is an error, since NetBox answers the whole list to
        a parameter it does not honour."""
        what = "core.objectchange"
        above = [("id__gt", str(after))] if after is not None else []
        count, results = self.listed(CHANGES, what, [*above, ("ordering", "id")], branch=branch)
        rows = tuple(self._row(what, branch, result, _change) for result in results)
        for row in rows:
            if after is not None and row.id <= after:
                raise self._unasked(what, branch, str(row.id))
        return Listing(what, count, rows)

    def listed(
        self, path: str, what: str, params: Params, *, branch: Branch | None, size: int = PAGE
    ) -> tuple[int, list[dict[str, Any]]]:
        """The results of every page of the list at `path`, `what` by NetBox's object type, asked with `params` under
        `branch`'s header, `size` at a time, and the largest `count` a page answered. It asks `limit=size` and the
        offset of the results read so far until it has read as many as that count or a page answers none, so a list
        answered short of its count ends it, to be judged by `rows.incomplete`; `next` is never followed."""
        count, results = 0, list[dict[str, Any]]()
        while True:
            asked = [*params, ("limit", str(size)), ("offset", str(len(results)))]
            answer = self._get(path, what, branch, asked)
            answered = answer.get("count") if isinstance(answer, dict) else None
            got = answer.get("results") if isinstance(answer, dict) else None
            if type(answered) is not int or not isinstance(got, list):
                raise self._error(f"reading {what}", _where(branch), 200, "HTTP 200: answered no count and results")
            count = max(count, answered)
            results.extend(got)
            if not got or len(results) >= count:
                return count, results

    def _by_ids[T](
        self,
        path: str,
        what: str,
        name: str,
        ids: Sequence[int],
        branch: Branch | None,
        project: Callable[[dict[str, Any]], T],
        asked_by: Callable[[T], int],
        owner: str | None = None,
    ) -> Listing[T]:
        """The list at `path` of the objects whose ids are `ids`, asked as the parameter `name`, `IDS` of them a
        request: one `Listing` whose count is the sum of the requests' counts. A row whose `asked_by`, its own id, or
        its `owner`'s where it is given, is no id of its request is an error."""
        wanted = list(dict.fromkeys(ids))
        count, rows = 0, list[T]()
        for start in range(0, len(wanted), IDS):
            chunk = wanted[start : start + IDS]
            answered, results = self.listed(path, what, [(name, str(id)) for id in chunk], branch=branch)
            count += answered
            for result in results:
                row = self._row(what, branch, result, project)
                if asked_by(row) not in chunk:
                    of = f" of the {owner} {asked_by(row)}" if owner is not None else ""
                    raise self._unasked(what, branch, f"{result['id']}{of}")
                rows.append(row)
        return Listing(what, count, tuple(rows))

    def _row[T](self, what: str, branch: Branch | None, result: object, project: Callable[[dict[str, Any]], T]) -> T:
        """`result` as a row of `what`; one that is none is an error saying what it lacks."""
        try:
            if not isinstance(result, dict):
                raise ValueError("no object")
            _id(result)
            return project(result)
        except ValueError as e:
            said = f"HTTP 200: answered a {what} with {e}"
        raise self._error(f"reading {what}", _where(branch), 200, said)

    def _unasked(self, what: str, branch: Branch | None, row: str) -> NetBoxError:
        said = f"HTTP 200: answered the {what} {row}, which the request did not ask for"
        return self._error(f"reading {what}", _where(branch), 200, said)

    def _read_versions(self) -> None:
        """`version` and `branching` from `GET /api/status/`, and `unverified` where the pair is not in `SUPPORTED`,
        logged once."""
        doing = "reading NetBox's version"
        answer = self._answer(self._send("GET", STATUS, doing, None, None), doing, None)
        version = answer.get("netbox-version") if isinstance(answer, dict) else None
        plugins = answer.get("plugins") if isinstance(answer, dict) else None
        if not isinstance(version, str) or not version:
            raise self._error(doing, None, 200, "HTTP 200: answered no netbox-version")
        if not isinstance(plugins, dict):
            raise self._error(doing, None, 200, "HTTP 200: answered no plugins")
        branching = plugins.get(PLUGIN)
        self.version = version
        self.branching = branching if isinstance(branching, str) and branching else None
        if (version, self.branching) not in SUPPORTED:
            verified = " and ".join(f"NetBox {v} with netbox-branching {b}" for v, b in SUPPORTED)
            plugin = f"with netbox-branching {self.branching}" if self.branching else "naming no netbox-branching"
            message = (
                f"NetBox is version {version} {plugin}, and this reader is verified on {verified} alone, so it may "
                "misread what NetBox answers."
            )
            found = f"{version}/{self.branching or 'none'}"
            self.unverified = Finding(rule=RULE_UNVERIFIED, severity="warning", object=found, message=message)
            log.warning(message)

    def _get(self, path: str, what: str, branch: Branch | None, params: Params) -> Any:
        """NetBox's answer to `GET path` with `params`, under `branch`'s header, as JSON."""
        doing, where = f"reading {what}", _where(branch)
        return self._answer(self._send("GET", path, doing, where, branch, params=params), doing, where)

    def _send(
        self,
        method: str,
        path: str,
        doing: str,
        where: str | None,
        branch: Branch | None,
        *,
        params: Params = (),
        accept: str | None = None,
    ) -> httpx.Response:
        """The one sender: every request the reader makes goes through here, under `branch`'s header where it is
        given, asking `accept` in place of JSON where it is given. NetBox not reached is an error of no status."""
        headers = {"X-NetBox-Branch": branch.schema_id} if branch is not None else {}
        if accept is not None:
            headers["Accept"] = accept
        try:
            return self._http.request(method, path, params=list(params), headers=headers)
        except httpx.HTTPError as e:
            # Hidden before it is bound: the exception's text can hold the token, and a traceback can show its locals.
            said = self._hide(f"NetBox at {self._url} was not reached: {type(e).__name__}: {e}")
            failure = self._error(doing, where, None, said)
        raise failure from None

    def _answer(self, response: httpx.Response, doing: str, where: str | None) -> Any:
        """The JSON NetBox answered under HTTP 200; any other status is a `NetBoxError` in NetBox's words, a refused
        token's quoting nothing and a redirect's naming the path it points to alone."""
        status = response.status_code
        if status in (401, 403):
            raise self._refused(doing, where, status)
        if 300 <= status <= 399:
            raise self._error(doing, where, status, f"HTTP {status}: {_moved(response)}")
        if status != 200:
            raise self._error(doing, where, status, f"HTTP {status}: {self._words(response)}")
        try:
            return json.loads(response.content)
        except ValueError:
            raise self._error(doing, where, 200, "HTTP 200: answered no JSON") from None

    def _refused(self, doing: str, where: str | None, status: int) -> NetBoxError:
        """A refused token, named by its variable, quoting nothing of the answer: NetBox answers 403 both to a token
        it never made and to one whose account may not read the list (design/verified-facts.md)."""
        if status == 401:
            return self._error(doing, where, status, f"HTTP {status}: NetBox refused the token {TOKEN} holds")
        said = f"HTTP {status}: NetBox refused the token {TOKEN} holds, or its account may not read this"
        return self._error(doing, where, status, said)

    def _words(self, response: httpx.Response) -> str:
        """NetBox's own words in a refusal: its `detail` where the body is JSON and carries one, else the body, the
        token replaced and then cut at `QUOTED` characters. A body is read as JSON only where its content type is
        `application/json`: NetBox answers a render with no template in `text/plain`, single-quoted
        (design/verified-facts.md), and a text that happens to parse is quoted as it stands."""
        body = None
        if response.headers.get("Content-Type", "").split(";")[0].strip().lower() == "application/json":
            with contextlib.suppress(ValueError):
                body = json.loads(response.content)
        if isinstance(body, dict) and isinstance(body.get("detail"), str):
            text = body["detail"]
        elif body is not None:
            text = json.dumps(body)
        else:
            text = response.text
        said = " ".join(self._hide(text).split())
        return said[:QUOTED] if said else "an empty body"

    def _hide(self, text: str) -> str:
        """`text` with the token, and each half of it, replaced (redact)."""
        return redact(text, self._token)

    def _error(self, doing: str, where: str | None, status: int | None, said: str) -> NetBoxError:
        place = f" ({where})" if where is not None else ""
        return NetBoxError(" ".join(self._hide(f"{doing}{place}: {said}").split()), status)


def connect(
    address: str, token: str, *, ca: Path | None = None, transport: httpx.BaseTransport | None = None
) -> NetBox:
    """The `NetBox` at `address`, an http(s):// URL or host:port, read with `token`, its two versions read. An
    `https://` address is verified against the CA file `ca`, or the system's trust where it is None.
    `InvalidAddress`, `InvalidToken` and `InvalidCA` (fylgja_core.client) are raised before any request, each a
    predicate that repeats nothing; `transport` replaces the network, for tests."""
    url = base_url(address)
    http = httpx.Client(
        base_url=url,
        headers={"Authorization": bearer(token), "Accept": "application/json"},
        transport=transport,
        verify=trust(ca),
        timeout=TIMEOUT_S,
        trust_env=False,
    )
    conn = NetBox(http, url=url, token=token)
    try:
        conn._read_versions()
    except BaseException:
        conn.close()
        raise
    return conn


def redact(text: str, token: str) -> str:
    """`text` with `token`, and each half of a v2 token long enough not to match ordinary words, replaced by
    `REDACTED`, the longer first: what the transport does to every text it raises, and the command to its last resort's
    line, so that the two hide the same."""
    for part in _parts(token):
        text = text.replace(part, REDACTED)
    return text


def _parts(token: str) -> list[str]:
    """What is replaced wherever it is echoed: the token, then each half of a v2 token, `nbt_<key>.<token>`, long
    enough not to match ordinary words, the longer first."""
    halves = token.removeprefix("nbt_").split(".") if "." in token else []
    return [token, *sorted((half for half in halves if len(half) >= HALF), key=len, reverse=True)]


def _moved(response: httpx.Response) -> str:
    """Where a redirect points, by its `Location`'s path alone, never its host or its query."""
    location = response.headers.get("Location")
    try:
        path = httpx.URL(location).path if location else ""
    except httpx.InvalidURL:
        path = ""
    return f"a redirect to {path}" if path else "a redirect with no Location"


def _id(row: dict[str, Any]) -> int:
    found = row.get("id")
    if type(found) is not int:
        raise ValueError("no id")
    return found


def _text(row: dict[str, Any], member: str, *, empty: bool = False) -> str:
    found = row.get(member)
    if not isinstance(found, str) or (not found and not empty):
        raise ValueError(f"no {member}")
    return found


def _flag(row: dict[str, Any], member: str) -> bool:
    found = row.get(member)
    if not isinstance(found, bool):
        raise ValueError(f"no {member}")
    return found


def _nested(row: dict[str, Any], member: str, *, null: bool) -> dict[str, Any] | None:
    """The object at `member`, None where it is null and `null` allows it; absent, or anything else, is a
    `ValueError`."""
    found = row.get(member)
    if member not in row or (found is None and not null):
        raise ValueError(f"no {member}")
    if found is not None and not isinstance(found, dict):
        raise ValueError(f"a {member} that is no object")
    return found


def _peer(row: dict[str, Any], member: str, field: str, *, null: bool) -> Any:
    """The `field` of the object at `member`, None where that object is null and `null` allows it."""
    found = _nested(row, member, null=null)
    if found is None:
        return None
    value = found.get(field)
    if value is None or (field == "id" and type(value) is not int) or (field != "id" and not isinstance(value, str)):
        raise ValueError(f"a {member} with no {field}")
    return value


def _branch(row: dict[str, Any]) -> Branch:
    synced = row.get("last_sync")
    if "last_sync" not in row or not (synced is None or isinstance(synced, str)):
        raise ValueError("no last_sync")
    status = _peer(row, "status", "value", null=False)
    return Branch(_id(row), _text(row, "name"), _text(row, "schema_id"), status, synced)


def _change(row: dict[str, Any]) -> Change:
    return Change(_id(row), _text(row, "changed_object_type"))


def _tag(row: dict[str, Any]) -> Tag:
    return Tag(_id(row), _text(row, "name"))


def _device(row: dict[str, Any]) -> Device:
    name = row.get("name")
    if "name" not in row or not (name is None or isinstance(name, str)):
        raise ValueError("no name")
    return Device(_id(row), name, _peer(row, "platform", "id", null=True))


def _tagged(row: dict[str, Any]) -> list[int]:
    """The ids of the tags a device carries."""
    tags = row.get("tags")
    if not isinstance(tags, list) or not all(isinstance(tag, dict) and type(tag.get("id")) is int for tag in tags):
        raise ValueError("no tags, each with an id")
    return [tag["id"] for tag in tags]


def _platform(row: dict[str, Any]) -> Platform:
    return Platform(_id(row), _text(row, "name"), _peer(row, "manufacturer", "name", null=True))


def _port(row: dict[str, Any]) -> Port:
    return Port(
        _id(row),
        _peer(row, "device", "id", null=False),
        _text(row, "name"),
        _peer(row, "type", "value", null=False),
        _flag(row, "enabled"),
        _flag(row, "mgmt_only"),
        _peer(row, "cable", "id", null=True),
    )


def _context(row: dict[str, Any]) -> Context:
    if "data" not in row:
        raise ValueError("no data")
    return Context(_id(row), _text(row, "name"), _flag(row, "is_active"), row["data"])


def _cable(row: dict[str, Any]) -> Cable:
    label = _text(row, "label", empty=True)
    return Cable(_id(row), label or None, _ends(row, "a_terminations"), _ends(row, "b_terminations"))


def _ends(row: dict[str, Any], member: str) -> tuple[End, ...]:
    """A side of a cable, each termination its object's type, id and display text, None where NetBox answered no
    object or no display."""
    side = row.get(member)
    if not isinstance(side, list) or not all(isinstance(end, dict) for end in side):
        raise ValueError(f"no {member}")
    ends = []
    for end in side:
        kind, found = end.get("object_type"), end.get("object_id")
        if not isinstance(kind, str) or not kind or type(found) is not int:
            raise ValueError(f"{member} not each an object_type and an object_id")
        held = end.get("object")
        display = held.get("display") if isinstance(held, dict) else None
        ends.append(End(kind, found, display if isinstance(display, str) else None))
    return tuple(ends)
