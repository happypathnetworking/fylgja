"""A fake NetBox for the NetBox change source's tests: a handler for `httpx.MockTransport` over state a test sets,
never an answer captured from NetBox (D-034, D-096). It answers the source's own requests as NetBox 4.7.5 with
netbox-branching 1.2.3 was read to (design/verified-facts.md): the branches listed by their exact name and a branch's
tags patched by slug, a branch's journal entries listed in the order written and one written, the object types by
their app label and model, and `main`'s changelog counted by `time_after` and `changed_object_type_id__n`. Every
list is answered `page` rows at most, its `next` an address that is no one's, which the source must never follow.

`log` holds every request, `(method, path, query, body)`, and `keyed` whether every one carried the token in
`Authorization` and nowhere else, with no branch header, compared outside any assert. A test scripts an answer for a
method and a path in `scripted`, each answered in turn and then the fake's own, and is given each journal entry's
body as it is written, before it is kept, in `on_entry`.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl

import httpx

ADDRESS = "http://netbox.example:8800"
TOKEN = "nbt_AbCdEf012345.0123456789abcdefABCDEF0123456789abcdefAB"
"""A token as NetBox's v2 tokens are, `nbt_<key>.<token>`: a test value."""
USER = 3
"""The writer's user id, which an entry's `created_by` holds: an integer, not a row."""
JOURNALENTRY, BRANCH = 128, 168
"""The ids NetBox numbered the two kinds no read reads, as the development NetBox did."""
WEBHOOK, EVENTRULE, TAG_TYPE = 1, 122, 114
"""The ids NetBox numbered a webhook, an event rule and a tag, as the development NetBox did."""
ELSEWHERE = "http://elsewhere.example/api"
"""Where every `next` points: an address the source must never be seen to ask."""


def stamp(k: int) -> str:
    """The `k`th time of the fake's clock, rising a second at a time."""
    return f"2026-11-13T10:{k // 60:02d}:{k % 60:02d}.000000Z"


@dataclass
class Change:
    """A row of `main`'s changelog: its id, its time and its object type's id."""

    id: int
    time: str
    type: int


@dataclass
class FakeNetBox:
    """A fake NetBox's state, and its handler."""

    branches: list[dict[str, Any]] = field(default_factory=list)
    tags: dict[str, dict[str, Any]] = field(default_factory=dict)
    entries: list[dict[str, Any]] = field(default_factory=list)
    changes: list[Change] = field(default_factory=list)
    types: dict[tuple[str, str], int] = field(
        default_factory=lambda: {("extras", "journalentry"): JOURNALENTRY, ("netbox_branching", "branch"): BRANCH,
                                 ("extras", "webhook"): WEBHOOK, ("extras", "eventrule"): EVENTRULE,
                                 ("extras", "tag"): TAG_TYPE}
    )
    page: int = 50
    scripted: dict[tuple[str, str], list[httpx.Response]] = field(default_factory=dict)
    log: list[tuple[str, str, list[tuple[str, str]], Any]] = field(default_factory=list)
    keyed: bool = True
    on_entry: Callable[[Mapping[str, Any]], None] | None = None
    tick: int = 0

    def branch(self, name: str, *, status: str = "ready", tags: tuple[str, ...] = (),
               last_sync: str | None = None) -> dict[str, Any]:
        """A branch made, `ready` unless said, with `tags` by slug; its `created` the fake's clock's now."""
        k = len(self.branches) + 1
        created = self.now()
        row = {
            "id": 270 + k,
            "name": name,
            "schema_id": f"{k:08x}",
            "status": {"value": status, "label": status.capitalize()},
            "tags": [self.tag(slug) for slug in tags],
            "created": created,
            "last_sync": last_sync if last_sync is not None else created,
        }
        self.branches.append(row)
        return row

    def tag(self, slug: str) -> dict[str, Any]:
        """The tag `slug`, made where it is not: a row as NetBox answers one inside a branch's `tags`."""
        if slug not in self.tags:
            k = len(self.tags) + 1
            self.tags[slug] = {"id": k, "name": slug, "slug": slug, "color": "9e9e9e", "display": slug,
                               "display_url": f"/extras/tags/{k}/", "url": f"/api/extras/tags/{k}/"}
        return self.tags[slug]

    def entry(self, branch: Mapping[str, Any], comments: str, kind: str = "info") -> dict[str, Any]:
        """A journal entry written on `branch`, its id and its `created` rising as written; and its changelog row."""
        k = len(self.entries) + 1
        row = {
            "id": k,
            "assigned_object_type": "netbox_branching.branch",
            "assigned_object_id": branch["id"],
            "kind": {"value": kind, "label": kind.capitalize()},
            "comments": comments,
            "created": self.now(),
            "created_by": USER,
        }
        self.entries.append(row)
        self.changed(JOURNALENTRY)
        return row

    def changed(self, kind: int) -> None:
        """A row of `kind` added to `main`'s changelog, at the fake's clock's now."""
        self.changes.append(Change(len(self.changes) + 1, self.now(), kind))

    def now(self) -> str:
        self.tick += 1
        return stamp(self.tick)

    def requests(self, method: str | None = None) -> list[tuple[str, str]]:
        """Each request logged, `(method, path)`, or those of `method`."""
        return [(m, path) for m, path, _, _ in self.log if method is None or m == method]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        # Compared outside any assert, so that no failure prints the header (core/tests/test_config.py's `same`).
        header = request.headers.get("Authorization") == f"Bearer {TOKEN}"
        elsewhere = TOKEN in str(request.url) or TOKEN in request.content.decode()
        self.keyed = self.keyed and header and not elsewhere and "X-NetBox-Branch" not in request.headers
        assert str(request.url).startswith(f"{ADDRESS}/api/"), "a request outside NetBox's API"
        path = request.url.path.removeprefix("/api/")
        query = parse_qsl(request.url.query.decode(), keep_blank_values=True)
        body = json.loads(request.content) if request.content else None
        self.log.append((request.method, path, query, body))
        script = self.scripted.get((request.method, path))
        if script:
            return script.pop(0)
        return self.answer(request.method, path, query, body)

    def answer(self, method: str, path: str, query: list[tuple[str, str]], body: Any) -> httpx.Response:
        params = dict(query)
        if method == "GET" and path == "plugins/branching/branches/":
            return self.listed([row for row in self.branches if row["name"] == params.get("name")], params)
        if method == "PATCH" and path.startswith("plugins/branching/branches/"):
            row = next(row for row in self.branches if path == f"plugins/branching/branches/{row['id']}/")
            row["tags"] = [self.tag(given["slug"]) for given in body["tags"]]
            self.changed(BRANCH)
            return httpx.Response(200, json=row)
        if method == "GET" and path == "extras/journal-entries/":
            assert params.get("assigned_object_type") == "netbox_branching.branch"
            assert params.get("ordering") == "created"
            wanted = int(params["assigned_object_id"])
            return self.listed([row for row in self.entries if row["assigned_object_id"] == wanted], params)
        if method == "POST" and path == "extras/journal-entries/":
            assert set(body) == {"assigned_object_type", "assigned_object_id", "kind", "comments"}, body
            assert body["assigned_object_type"] == "netbox_branching.branch"
            if self.on_entry is not None:
                self.on_entry(body)
            branch = next(row for row in self.branches if row["id"] == body["assigned_object_id"])
            return httpx.Response(201, json=self.entry(branch, body["comments"], body["kind"]))
        if method == "GET" and path == "core/object-types/":
            found = self.types.get((params["app_label"], params["model"]))
            rows = [{"id": found, "app_label": params["app_label"], "model": params["model"]}] if found else []
            return self.listed(rows, params)
        if method == "GET" and path == "core/object-changes/":
            left = {int(value) for name, value in query if name == "changed_object_type_id__n"}
            after = params.get("time_after")
            rows = [{"id": row.id, "time": row.time} for row in self.changes
                    if row.type not in left and (after is None or row.time >= after)]
            return self.listed(rows, params)
        raise AssertionError(f"the fake answers no {method} {path}")

    def listed(self, rows: list[dict[str, Any]], params: Mapping[str, str]) -> httpx.Response:
        """A page of `rows`, as NetBox answers one: from `offset`, `limit` rows but no more than `page`, the whole
        `count`, and a `next` that is no one's address where rows are left."""
        offset = int(params.get("offset", "0"))
        size = min(int(params.get("limit", "50")), self.page)
        results = rows[offset : offset + size]
        following = f"{ELSEWHERE}/?offset={offset + size}" if offset + size < len(rows) else None
        return httpx.Response(200, json={"count": len(rows), "next": following, "previous": None,
                                         "results": results})
