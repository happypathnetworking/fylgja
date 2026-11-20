"""The transport: the one module that speaks to Nautobot, over plain HTTP and httpx, with no client library of
Nautobot's (D-118, D-096).

It sends `GET /api/status/` and `GET` lists of `/api/extras/tags/`, `/api/dcim/devices/`, `/api/dcim/platforms/`,
`/api/dcim/manufacturers/`, `/api/dcim/interfaces/`, `/api/dcim/cables/`, `/api/extras/object-changes/`, Golden Config's
`/api/plugins/golden-config/golden-config-settings/`, `/api/extras/git-repositories/`, `/api/extras/dynamic-groups/` and
`/api/extras/static-group-associations/`, `/api/extras/config-contexts/`, and Golden Config's render of one device,
`/api/plugins/golden-config/generate-intended-config/` by `device_id` alone; nothing else, and never a method that
writes. Each call answers rows (rows.py), never Nautobot's JSON. A list is read `PAGE` at a time, by
`limit` and the offset of what was read, until the `count` Nautobot answered for it, which is kept beside what was read
so that `rows.incomplete` can hold the two to each other; Nautobot's `next` is never followed, since it holds Nautobot's
own address, nor is a redirect. A list by ids asks as many of them a request as keep its path and query within
`MAX_REQUEST` bytes, `IDS` at most, and sends nothing for none. Every row is held to what was asked: a row of another
name, id, tag or device than was asked is an error, never a row.

A request too long for the server is not answered at all: the development Nautobot's uWSGI, at the image's
`buffer-size = 4096`, dropped every request whose path and query were 1825 bytes or more, with no response, and logged
`invalid request block size` (design/verified-facts.md). How many ids fit depends on the parameter's name, and a site's
server is not the reader's to tune, so the batch is bounded by its length; a request dropped is a `NautobotError` of no
status, never a short list.

`connect` reads Nautobot's version and the Golden Config app's once, from `nautobot-apps`; a pair not in `SUPPORTED`
is a warning, `nautobot.version.unverified`, carried on every result of the connection and logged once. The token is
held by the `Nautobot` alone, checked by the client's bearer rule before any request, so that no HTTP library's
complaint can quote it, and sent as `Authorization: Token <token>`, Nautobot's own scheme. Every failure is a
`NautobotError` whose text names what was being read and keeps the status Nautobot answered. None holds the token:
Nautobot's own words and a transport failure's text have it replaced by `<redacted>`, and the error is raised from
nothing, since an httpx exception carries its request, whose headers hold it.

What each list is asked by, and the rows' members, are as read on Nautobot 3.2.8 with Golden Config 3.0.8
(design/verified-facts.md, "Nautobot 3.2.8 with Golden Config 3.0.8"): `?name=` of tags is exact, letter case
included; devices are asked by `?tags=` with the tag's id, which Nautobot answers 400 for a tag it does not hold;
platforms, manufacturers and cables by `?id=`, which answers no row, and no error, for an id no object has, so that
`rows.incomplete` tells the lack; interfaces by `?device_id=`, which answers 400 for an id no device has; a related
object is answered as `{id, object_type, url}`; and a cable's ends are its `terminations`, one member a connector of a
side, `a1`, `b1`, `b2`, each the object cabled there, or null for a connector cabled to nothing. The changelog is
listed newest first, so its newest row and its total count are one request of `?limit=1`; Golden Config's settings
are listed whole, each naming its template repository and its dynamic group as related objects; and repositories are
asked by `?id=`, which answers no row for an id no repository has. A configuration context is asked by `?name=`,
which is exact and lists an inactive one, and answers its `is_active` and its `data`. Dynamic groups are asked by
`?id=` too; a group's stored members are its rows of `static-group-associations/` by `?dynamic_group=` and
`?associated_object_id=`, which lists them whole for a group of any type, with a count, and restricted to the devices
asked, each naming its group, its object's type and its object's id; and the devices a group's filter lists are the
device list asked by the filter's own parameters beside `?id=`, which answered what a save of the filter stored
(design/verified-facts.md, "A group's stored members").
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import TracebackType
from typing import Any, Protocol, Self

import httpx
from fylgja_core.client import base_url, bearer, trust
from fylgja_core.findings import Finding

from fylgja_nautobot.rows import (
    Cable,
    Change,
    Context,
    Device,
    End,
    Group,
    Listing,
    Manufacturer,
    Platform,
    Port,
    Rendered,
    Repository,
    Setting,
    Tag,
)

# Rule ids. Callers and tests match on them (rules.md).
RULE_UNVERIFIED = "nautobot.version.unverified"

SUPPORTED: tuple[tuple[str, str], ...] = (("3.2.8", "3.0.8"),)
"""The pairs of Nautobot's version and Golden Config's the reader passed its contract tier on, Nautobot's first
(design/verified-facts.md, "Nautobot 3.2.8 with Golden Config 3.0.8")."""

PAGE = 100
"""How many rows one request of a list asks for: Nautobot answered a page of 100 whole (design/verified-facts.md)."""

IDS = 50
"""The most ids one request of a list by ids names, whatever their length."""

MAX_REQUEST = 1500
"""The most bytes of a request's path and query, as sent, `limit` and an `offset` of `OFFSET` digits included, that a
list by ids is batched to. The development Nautobot answered 1824 bytes and dropped 1825, the same for `?id=` and
`?device_id=` (design/verified-facts.md); 1500 is about 0.82 of 1824, a derivation, leaving room for a longer host
name or other headers, which uWSGI's block holds beside the query."""

OFFSET = 10
"""The digits an offset is reserved when a batch is measured: a list of fewer than ten thousand million rows."""

TIMEOUT_S = 60.0
"""Seconds one request is given, a first value and no measurement of need, in place of httpx's own 5 s. A failing
render took 11.5 s (design/verified-facts.md, "Nautobot 3.2.8 with Golden Config 3.0.8"); 60 s is about 5.2 times
that, a derivation."""

TOKEN = "FYLGJA_NAUTOBOT_TOKEN"
"""The variable a refused token is named by: the command reads the token from it."""

REDACTED = "<redacted>"
"""What stands for the token in an error's text."""

QUOTED = 300
"""How many characters of Nautobot's own words an error quotes."""

STATUS = "/api/status/"
TAGS = "/api/extras/tags/"
DEVICES = "/api/dcim/devices/"
PLATFORMS = "/api/dcim/platforms/"
MANUFACTURERS = "/api/dcim/manufacturers/"
INTERFACES = "/api/dcim/interfaces/"
CABLES = "/api/dcim/cables/"
CHANGES = "/api/extras/object-changes/"
SETTINGS = "/api/plugins/golden-config/golden-config-settings/"
REPOSITORIES = "/api/extras/git-repositories/"
GROUPS = "/api/extras/dynamic-groups/"
ASSOCIATIONS = "/api/extras/static-group-associations/"
CONTEXTS = "/api/extras/config-contexts/"
RENDER = "/api/plugins/golden-config/generate-intended-config/"

APP = "nautobot_golden_config"
"""The Golden Config app's name among those `/api/status/`'s `nautobot-apps` names."""

VERSION = "reading Nautobot's version"
"""What `connect`'s one request is said to be doing."""

DEVICE = "dcim.device"
"""The object type of a device, which a group's stored member must be."""

LANE = re.compile(r"([ab])([1-9][0-9]*)")
"""A member of a cable's `terminations`: its side and its connector's number, from 1."""

log = logging.getLogger("fylgja.nautobot")

Params = Sequence[tuple[str, str]]


class NautobotError(Exception):
    """Nautobot refused a request, answered what is no answer, or was not reached. The text names what was being read
    and holds no token. `status` is the HTTP status Nautobot answered, 200 for an answer that is no answer to what was
    asked, and None where Nautobot was not reached."""

    def __init__(self, message: str, status: int | None) -> None:
        super().__init__(message)
        self.status = status


class Named(Protocol):
    """A row found by its name: a tag, a configuration context."""

    @property
    def name(self) -> str: ...


def named[T: Named](listing: Listing[T], name: str) -> T | None:
    """The one row of `listing` named `name`, None where it holds none. Nautobot's `?name=` of a tag or a
    configuration context is exact, letter case included (design/verified-facts.md); the reader does not rely on a
    name being unique: where the name answers more than one row, which of them the read would take cannot be told, so
    that is an error naming the list and the name, raised before anything is built on one."""
    held = [row for row in listing.items if row.name == name]
    if len(held) > 1:
        said = f"HTTP 200: answered {len(held)} rows named {name}, where the read takes the one object of a name"
        raise NautobotError(f"reading {listing.what}: {said}", 200)
    return held[0] if held else None


class Nautobot:
    """One Nautobot, read through one pool of connections: a `rows.Source` and a context manager. Made by `connect`,
    which reads `version`, Nautobot's own, and `golden_config`, the Golden Config app's, None where Nautobot names
    none; `unverified` is the warning every result carries where the pair is not in `SUPPORTED`."""

    version: str
    golden_config: str | None
    unverified: Finding | None

    def __init__(self, http: httpx.Client, *, url: str, token: str) -> None:
        self._http = http
        self._url = url
        self._token = token
        self.version = ""
        self.golden_config = None
        self.unverified = None

    def __repr__(self) -> str:
        """The two versions alone, neither the token nor the address: a test's fixtures are listed by their repr."""
        return f"Nautobot(version={self.version!r}, golden_config={self.golden_config!r})"

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the pool of connections."""
        self._http.close()

    def tags(self, name: str) -> Listing[Tag]:
        """Every tag named `name`, by `?name=`."""
        what = "extras.tag"
        count, results = self.listed(TAGS, what, [("name", name)])
        rows = tuple(self._row(what, result, _tag) for result in results)
        for row in rows:
            if row.name != name:
                raise self._unasked(what, f"{row.id} named {row.name}")
        return Listing(what, count, rows)

    def devices(self, tag: Tag) -> Listing[Device]:
        """Every device that carries `tag`, by `?tags=` with the tag's id."""
        what = "dcim.device"
        count, results = self.listed(DEVICES, what, [("tags", tag.id)])
        rows = []
        for result in results:
            row = self._row(what, result, _device)
            if tag.id not in self._row(what, result, _tagged):
                raise self._unasked(what, f"{row.id} without the tag {tag.id}")
            rows.append(row)
        return Listing(what, count, tuple(rows))

    def platforms(self, ids: Sequence[str]) -> Listing[Platform]:
        """The platforms whose ids are `ids`, by `?id=`; with no id, none, and nothing is sent."""
        return self._by_ids(PLATFORMS, "dcim.platform", "id", ids, _platform, lambda row: row.id)

    def manufacturers(self, ids: Sequence[str]) -> Listing[Manufacturer]:
        """The manufacturers whose ids are `ids`, by `?id=`; with no id, none, and nothing is sent."""
        return self._by_ids(MANUFACTURERS, "dcim.manufacturer", "id", ids, _manufacturer, lambda row: row.id)

    def ports(self, devices: Sequence[str]) -> Listing[Port]:
        """Every interface, whatever its type, of the devices whose ids are `devices`, by `?device_id=`; with no
        device, none, and nothing is sent."""
        return self._by_ids(
            INTERFACES, "dcim.interface", "device_id", devices, _port, lambda row: row.device, "dcim.device"
        )

    def cables(self, ids: Sequence[str]) -> Listing[Cable]:
        """The cables whose ids are `ids`, by `?id=`; with no id, none, and nothing is sent."""
        return self._by_ids(CABLES, "dcim.cable", "id", ids, _cable, lambda row: row.id)

    def contexts(self, name: str) -> Listing[Context]:
        """Every configuration context named `name`, by `?name=`, which is exact, letter case included, and lists an
        inactive context. A row of another name is an error."""
        what = "extras.configcontext"
        count, results = self.listed(CONTEXTS, what, [("name", name)])
        rows = tuple(self._row(what, result, _context) for result in results)
        for row in rows:
            if row.name != name:
                raise self._unasked(what, f"{row.id} named {row.name}")
        return Listing(what, count, rows)

    def render(self, device: str) -> Rendered:
        """What Golden Config renders for the device whose id is `device`, by one `GET` of `RENDER` with `device_id`
        and no other parameter, Golden Config's `branch` never among them: a `Rendered` of whatever status Nautobot
        answered but 401 and 403, which are the token's refusal. Under 200 its `text` is the answer's
        `intended_config` where the answer is a JSON object holding it as text, and nothing else of the answer is
        kept; under any other status its `detail` is Golden Config's words, the answer's `detail` where Nautobot calls
        the body `application/json` and it holds one as text, the token replaced and the words uncut. A redirect is
        not followed."""
        doing = f"rendering dcim.device {device}"
        response = self._send(RENDER, doing, params=[("device_id", device)])
        status = response.status_code
        if status in (401, 403):
            raise self._refused(doing, status)
        if status != 200:
            return Rendered(status, None, self._detail(response))
        try:
            answer = json.loads(response.content)
        except ValueError:
            return Rendered(status, None, None)
        text = answer.get("intended_config") if isinstance(answer, dict) else None
        return Rendered(status, text if isinstance(text, str) else None, None)

    def newest(self) -> tuple[int, Change | None]:
        """The changelog's total count and its newest row, None where the count is 0, by one `?limit=1`: Nautobot lists
        the changelog newest first. A count with no row, a row with a count of none, more than one row, or a `time`
        that `datetime.fromisoformat` refuses is an error, since none is the changelog's newest row."""
        what = "extras.objectchange"
        answer = self._get(CHANGES, what, [("limit", "1")])
        count = answer.get("count") if isinstance(answer, dict) else None
        results = answer.get("results") if isinstance(answer, dict) else None
        if type(count) is not int or not isinstance(results, list):
            raise self._error(f"reading {what}", 200, "HTTP 200: answered no count and results")
        said = None
        if len(results) > 1:
            said = f"{len(results)} rows to a limit of 1"
        elif count and not results:
            said = f"a count of {count} and no row"
        elif not count and results:
            said = f"a count of {count} and a row"
        if said is not None:
            raise self._error(f"reading {what}", 200, f"HTTP 200: answered {said}")
        if not results:
            return count, None
        row = self._row(what, results[0], _change)
        try:
            datetime.fromisoformat(row.time)
        except ValueError:
            said = f"a time {row.time[:QUOTED]} that is no ISO 8601 time"
        else:
            return count, row
        raise self._error(f"reading {what}", 200, f"HTTP 200: answered {said}")

    def settings(self) -> Listing[Setting]:
        """Every Golden Config setting, the list read whole."""
        what = "nautobot_golden_config.goldenconfigsetting"
        count, results = self.listed(SETTINGS, what, [])
        return Listing(what, count, tuple(self._row(what, result, _setting) for result in results))

    def repositories(self, ids: Sequence[str]) -> Listing[Repository]:
        """The Git repositories whose ids are `ids`, by `?id=`; with no id, none, and nothing is sent."""
        return self._by_ids(REPOSITORIES, "extras.gitrepository", "id", ids, _repository, lambda row: row.id)

    def groups(self, ids: Sequence[str]) -> Listing[Group]:
        """The dynamic groups whose ids are `ids`, by `?id=`; with no id, none, and nothing is sent."""
        return self._by_ids(GROUPS, "extras.dynamicgroup", "id", ids, _group, lambda row: row.id)

    def stored(self, group: str, devices: Sequence[str]) -> Listing[str]:
        """The ids of the devices, among `devices`, stored as the members of the dynamic group `group`: its rows of
        `ASSOCIATIONS` by `?dynamic_group=` and `?associated_object_id=` of the devices; with no device, none, and
        nothing is sent. A row of another group, or of an object that is no `dcim.device`, is an error."""
        what = "extras.staticgroupassociation"
        held = self._by_ids(
            ASSOCIATIONS,
            what,
            "associated_object_id",
            devices,
            _association,
            lambda row: row.device,
            DEVICE,
            fixed=[("dynamic_group", group)],
        )
        for row in held.items:
            if row.group != group:
                raise self._unasked(what, f"{row.id} of the extras.dynamicgroup {row.group}")
            if row.kind != DEVICE:
                raise self._unasked(what, f"{row.id} of the {row.kind} {row.device}")
        return Listing(what, held.count, tuple(row.device for row in held.items))

    def matching(
        self, filter: Sequence[tuple[str, str]], devices: Sequence[str], group: str | None = None
    ) -> Listing[Device]:
        """The devices, among `devices`, that the device list answers asked with `filter`, a filter's parameters, sent
        first and in its order, beside `?id=` of the devices; with no device, none, and nothing is sent. Where `group`
        is given, the name of the dynamic group whose filter it is, the listing and its errors say so: Nautobot
        answers 400 to a filter naming a tag it no longer holds."""
        what = DEVICE if group is None else f"{DEVICE} by the filter of dynamic group {group}"
        return self._by_ids(DEVICES, what, "id", devices, _device, lambda row: row.id, fixed=filter)

    def listed(self, path: str, what: str, params: Params, *, size: int = PAGE) -> tuple[int, list[dict[str, Any]]]:
        """The results of every page of the list at `path`, `what` by Nautobot's object type, asked with `params`,
        `size` at a time, and the largest `count` a page answered. It asks `limit=size` and the offset of the results
        read so far until it has read as many as that count or a page answers none, so a list answered short of its
        count ends it, to be judged by `rows.incomplete`; `next` is never followed."""
        count, results = 0, list[dict[str, Any]]()
        while True:
            asked = [*params, ("limit", str(size)), ("offset", str(len(results)))]
            answer = self._get(path, what, asked)
            answered = answer.get("count") if isinstance(answer, dict) else None
            got = answer.get("results") if isinstance(answer, dict) else None
            if type(answered) is not int or not isinstance(got, list):
                raise self._error(f"reading {what}", 200, "HTTP 200: answered no count and results")
            count = max(count, answered)
            results.extend(got)
            if not got or len(results) >= count:
                return count, results

    def _by_ids[T](
        self,
        path: str,
        what: str,
        name: str,
        ids: Sequence[str],
        project: Callable[[dict[str, Any]], T],
        asked_by: Callable[[T], str],
        owner: str | None = None,
        *,
        fixed: Params = (),
    ) -> Listing[T]:
        """The list at `path` of the objects whose ids are `ids`, asked as the parameter `name`, in batches
        (`_batches`), each request carrying the parameters `fixed` first: one `Listing` whose count is the sum of the
        requests' counts. A row whose `asked_by`, its own id, or its `owner`'s where it is given, is no id of its
        request is an error."""
        count, rows = 0, list[T]()
        for chunk in self._batches(path, name, list(dict.fromkeys(ids)), fixed):
            answered, results = self.listed(path, what, [*fixed, *((name, id) for id in chunk)])
            count += answered
            for result in results:
                row = self._row(what, result, project)
                if asked_by(row) not in chunk:
                    of = f" of the {owner} {asked_by(row)}" if owner is not None else ""
                    raise self._unasked(what, f"{result['id']}{of}")
                rows.append(row)
        return Listing(what, count, tuple(rows))

    def _batches(self, path: str, name: str, ids: list[str], fixed: Params = ()) -> list[list[str]]:
        """`ids` in order, cut into batches each as long as its request's path and query stay within `MAX_REQUEST`
        bytes, as httpx encodes them, the parameters `fixed`, `limit` and an offset of `OFFSET` digits included, and
        `IDS` at most. An id too long to fit alone is a batch of its own."""
        tail = [("limit", str(PAGE)), ("offset", "9" * OFFSET)]
        batches: list[list[str]] = []
        for id in ids:
            if batches and len(batches[-1]) < IDS:
                tried = [*batches[-1], id]
                sent = self._http.build_request("GET", path, params=[*fixed, *((name, i) for i in tried), *tail])
                if len(sent.url.raw_path) <= MAX_REQUEST:
                    batches[-1] = tried
                    continue
            batches.append([id])
        return batches

    def _row[T](self, what: str, result: object, project: Callable[[dict[str, Any]], T]) -> T:
        """`result` as a row of `what`; one that is none is an error saying what it lacks."""
        try:
            if not isinstance(result, dict):
                raise ValueError("no object")
            _id(result)
            return project(result)
        except ValueError as e:
            said = f"HTTP 200: answered a {what} with {e}"
        raise self._error(f"reading {what}", 200, said)

    def _unasked(self, what: str, row: str) -> NautobotError:
        said = f"HTTP 200: answered the {what} {row}, which the request did not ask for"
        return self._error(f"reading {what}", 200, said)

    def _read_versions(self) -> None:
        """`version` and `golden_config` from `GET /api/status/`, and `unverified` where the pair is not in
        `SUPPORTED`, logged once."""
        answer = self._answer(self._send(STATUS, VERSION), VERSION)
        version = answer.get("nautobot-version") if isinstance(answer, dict) else None
        apps = answer.get("nautobot-apps") if isinstance(answer, dict) else None
        if not isinstance(version, str) or not version:
            raise self._error(VERSION, 200, "HTTP 200: answered no nautobot-version")
        if not isinstance(apps, dict):
            raise self._error(VERSION, 200, "HTTP 200: answered no nautobot-apps")
        golden_config = apps.get(APP)
        self.version = version
        self.golden_config = golden_config if isinstance(golden_config, str) and golden_config else None
        if (version, self.golden_config) not in SUPPORTED:
            verified = " and ".join(f"Nautobot {v} with Golden Config {g}" for v, g in SUPPORTED)
            app = f"with Golden Config {self.golden_config}" if self.golden_config else "naming no Golden Config"
            message = (
                f"Nautobot is version {version} {app}, and this reader is verified on {verified} alone, so it may "
                "misread what Nautobot answers."
            )
            found = f"{version}/{self.golden_config or 'none'}"
            self.unverified = Finding(rule=RULE_UNVERIFIED, severity="warning", object=found, message=message)
            log.warning(message)

    def _get(self, path: str, what: str, params: Params) -> Any:
        """Nautobot's answer to `GET path` with `params`, as JSON."""
        doing = f"reading {what}"
        return self._answer(self._send(path, doing, params=params), doing)

    def _send(self, path: str, doing: str, *, params: Params = ()) -> httpx.Response:
        """The one sender: every request the reader makes goes through here, and each is a `GET`. Nautobot not reached
        is an error of no status."""
        try:
            return self._http.request("GET", path, params=list(params))
        except httpx.HTTPError as e:
            # Hidden before it is bound: the exception's text can hold the token, and a traceback can show its locals.
            said = self._hide(f"Nautobot at {self._url} was not reached: {type(e).__name__}: {e}")
            failure = self._error(doing, None, said)
        raise failure from None

    def _answer(self, response: httpx.Response, doing: str) -> Any:
        """The JSON Nautobot answered under HTTP 200; any other status is a `NautobotError` in Nautobot's words, a
        refused token's quoting nothing and a redirect's naming the path it points to alone."""
        status = response.status_code
        if status in (401, 403):
            raise self._refused(doing, status)
        if 300 <= status <= 399:
            raise self._error(doing, status, f"HTTP {status}: {_moved(response)}")
        if status != 200:
            raise self._error(doing, status, f"HTTP {status}: {self._words(response)}")
        try:
            return json.loads(response.content)
        except ValueError:
            # Raised after the block: inside it, the decode error, whose `.doc` is the whole body, would ride along as
            # the error's `__context__`.
            failure = self._error(doing, 200, "HTTP 200: answered no JSON")
        raise failure

    def _refused(self, doing: str, status: int) -> NautobotError:
        """A refused token, named by its variable, quoting nothing of the answer: Nautobot answers 403 both to a token
        it never made and to one whose account may not read the list (design/verified-facts.md)."""
        if status == 401:
            return self._error(doing, status, f"HTTP {status}: Nautobot refused the token {TOKEN} holds")
        said = f"HTTP {status}: Nautobot refused the token {TOKEN} holds, or its account may not read this"
        return self._error(doing, status, said)

    def _words(self, response: httpx.Response) -> str:
        """Nautobot's own words in a refusal: its `detail` where the body is JSON and carries one, else the body, the
        token replaced and then cut at `QUOTED` characters. A body is read as JSON only where its content type is
        `application/json`, and a text that happens to parse is quoted as it stands."""
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

    def _detail(self, response: httpx.Response) -> str | None:
        """The `detail` of a refusal's JSON body, as text, the token replaced and uncut; None where the body is not
        `application/json`, or holds no text `detail`."""
        if response.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            return None
        try:
            body = json.loads(response.content)
        except ValueError:
            return None
        detail = body.get("detail") if isinstance(body, dict) else None
        return self._hide(detail) if isinstance(detail, str) else None

    def _hide(self, text: str) -> str:
        """`text` with the token replaced (redact)."""
        return redact(text, self._token)

    def _error(self, doing: str, status: int | None, said: str) -> NautobotError:
        return NautobotError(" ".join(self._hide(f"{doing}: {said}").split()), status)


def connect(
    address: str, token: str, *, ca: Path | None = None, transport: httpx.BaseTransport | None = None
) -> Nautobot:
    """The `Nautobot` at `address`, an http(s):// URL or host:port, read with `token`, its two versions read. An
    `https://` address is verified against the CA file `ca`, or the system's trust where it is None.
    `InvalidAddress`, `InvalidToken` and `InvalidCA` (fylgja_core.client) are raised before any request, each a
    predicate that repeats nothing; the token is held to the bearer rule, its header value discarded, and sent in
    Nautobot's own scheme. `transport` replaces the network, for tests."""
    url = base_url(address)
    bearer(token)
    http = httpx.Client(
        base_url=url,
        headers={"Authorization": f"Token {token}", "Accept": "application/json"},
        transport=transport,
        verify=trust(ca),
        timeout=TIMEOUT_S,
        trust_env=False,
    )
    conn = Nautobot(http, url=url, token=token)
    try:
        conn._read_versions()
    except BaseException:
        conn.close()
        raise
    return conn


def redact(text: str, token: str) -> str:
    """`text` with `token` replaced by `REDACTED`: what the transport does to every text it raises, and the command to
    its last resort's line, so that the two hide the same. An empty token replaces nothing."""
    return text.replace(token, REDACTED) if token else text


def _moved(response: httpx.Response) -> str:
    """Where a redirect points, by its `Location`'s path alone, never its host or its query."""
    location = response.headers.get("Location")
    try:
        path = httpx.URL(location).path if location else ""
    except httpx.InvalidURL:
        path = ""
    return f"a redirect to {path}" if path else "a redirect with no Location"


def _id(row: dict[str, Any]) -> str:
    found = row.get("id")
    if not isinstance(found, str) or not found:
        raise ValueError("no id")
    return found


def _text(row: dict[str, Any], member: str) -> str:
    found = row.get(member)
    if not isinstance(found, str) or not found:
        raise ValueError(f"no {member}")
    return found


def _flag(row: dict[str, Any], member: str) -> bool:
    found = row.get(member)
    if not isinstance(found, bool):
        raise ValueError(f"no {member}")
    return found


def _related(row: dict[str, Any], member: str, *, null: bool) -> str | None:
    """The id of the object at `member`, answered as `{id, object_type, url}`, None where it is null and `null` allows
    it; absent, or anything else, is a `ValueError`."""
    found = row.get(member)
    if member not in row or (found is None and not null):
        raise ValueError(f"no {member}")
    if found is None:
        return None
    held = found.get("id") if isinstance(found, dict) else None
    if not isinstance(held, str) or not held:
        raise ValueError(f"a {member} with no id")
    return held


def _link(row: dict[str, Any], member: str) -> str:
    """The id of the object at `member`, which may not be null."""
    held = _related(row, member, null=False)
    if held is None:
        raise ValueError(f"no {member}")
    return held


def _tag(row: dict[str, Any]) -> Tag:
    return Tag(_id(row), _text(row, "name"))


def _device(row: dict[str, Any]) -> Device:
    name = row.get("name")
    if "name" not in row or not (name is None or isinstance(name, str)):
        raise ValueError("no name")
    return Device(_id(row), name, _related(row, "platform", null=True))


def _tagged(row: dict[str, Any]) -> list[str]:
    """The ids of the tags a device carries."""
    tags = row.get("tags")
    if not isinstance(tags, list) or not all(isinstance(tag, dict) and isinstance(tag.get("id"), str) for tag in tags):
        raise ValueError("no tags, each with an id")
    return [tag["id"] for tag in tags]


def _platform(row: dict[str, Any]) -> Platform:
    return Platform(_id(row), _text(row, "name"), _related(row, "manufacturer", null=True))


def _manufacturer(row: dict[str, Any]) -> Manufacturer:
    return Manufacturer(_id(row), _text(row, "name"))


def _port(row: dict[str, Any]) -> Port:
    kind = row.get("type")
    value = kind.get("value") if isinstance(kind, dict) else None
    if not isinstance(value, str) or not value:
        raise ValueError("a type with no value")
    return Port(
        _id(row),
        _link(row, "device"),
        _text(row, "name"),
        value,
        _flag(row, "enabled"),
        _flag(row, "mgmt_only"),
        _related(row, "cable", null=True),
    )


def _change(row: dict[str, Any]) -> Change:
    return Change(_id(row), _text(row, "time"))


def _setting(row: dict[str, Any]) -> Setting:
    weight = row.get("weight")
    if type(weight) is not int:
        raise ValueError("no weight")
    return Setting(
        _id(row),
        _text(row, "name"),
        weight,
        _related(row, "jinja_repository", null=True),
        _link(row, "dynamic_group"),
    )


def _group(row: dict[str, Any]) -> Group:
    """A dynamic group; its `filter` is whatever JSON Nautobot answered, and must be there."""
    if "filter" not in row:
        raise ValueError("no filter")
    return Group(_id(row), _text(row, "name"), _text(row, "group_type"), row["filter"])


def _context(row: dict[str, Any]) -> Context:
    """A configuration context; its `data` is whatever JSON Nautobot answered, and must be there."""
    if "data" not in row:
        raise ValueError("no data")
    return Context(_id(row), _text(row, "name"), _flag(row, "is_active"), row["data"])


@dataclass(frozen=True)
class _Association:
    """A stored member of a dynamic group: its own id, its group's id, its object's type and its object's id."""

    id: str
    group: str
    kind: str
    device: str


def _association(row: dict[str, Any]) -> _Association:
    return _Association(
        _id(row),
        _link(row, "dynamic_group"),
        _text(row, "associated_object_type"),
        _text(row, "associated_object_id"),
    )


def _repository(row: dict[str, Any]) -> Repository:
    """A repository; its `current_head` is text, empty where Nautobot never synced it (design/verified-facts.md)."""
    head = row.get("current_head")
    if not isinstance(head, str):
        raise ValueError("no current_head")
    return Repository(_id(row), _text(row, "name"), head)


def _cable(row: dict[str, Any]) -> Cable:
    label = row.get("label")
    if "label" not in row or not (label is None or isinstance(label, str)):
        raise ValueError("no label")
    a, b = _ends(row)
    return Cable(_id(row), label or None, a, b)


def _ends(row: dict[str, Any]) -> tuple[tuple[End, ...], tuple[End, ...]]:
    """A cable's two sides from its `terminations`, each its connectors' objects in the order of their numbers, a
    connector cabled to nothing, null, left out; each object its type, its id and its display text, None where
    Nautobot answered none."""
    lanes = row.get("terminations")
    if not isinstance(lanes, dict):
        raise ValueError("no terminations")
    sides: dict[str, list[tuple[int, End]]] = {"a": [], "b": []}
    for key, held in lanes.items():
        matched = LANE.fullmatch(key) if isinstance(key, str) else None
        if matched is None:
            raise ValueError(f"terminations with a member {key} that is no side and connector")
        if held is None:
            continue
        kind = held.get("object_type") if isinstance(held, dict) else None
        found = held.get("id") if isinstance(held, dict) else None
        if not isinstance(kind, str) or not kind or not isinstance(found, str) or not found:
            raise ValueError("terminations not each an object_type and an id, or null")
        display = held.get("display")
        sides[matched[1]].append((int(matched[2]), End(kind, found, display if isinstance(display, str) else None)))
    a, b = (tuple(end for _, end in sorted(sides[side], key=lambda lane: lane[0])) for side in ("a", "b"))
    return a, b
