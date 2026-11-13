"""A fake of the development NetBox's REST API for the pure tier: `FakeNetBox`, an `httpx.MockTransport` handler.

It keeps what is posted by its path, gives each object an id of its path's own, answers a list with its `count`, a
page at a time, and the filters the seed reads with, and records every request. An object is answered in the shape
NetBox 4.7.5 answers it (design/verified-facts.md, "NetBox 4.7.5 with netbox-branching 1.2.3"): a related object as
a row with its `id` and its name, a status and an interface's type as `{value}`, an interface's `cable` and
`link_peers`, an address's `assigned_object`, a cable's two lists of terminations, and a template's code with its
surrounding whitespace stripped. A user is answered with no password and no `is_superuser`, and made only with a
password, its `groups` and the permissions naming it as rows; a permission's `users` as rows; a token's `user` as a
row, its secret, `token`, answered by its create alone and `null` after. A branch is given a `schema_id` and is
`ready` at its create unless a test adds it in another status, each read of it by its id taking one `new` or
`provisioning` a status nearer `ready`; its `tags` are answered as rows, and its `DELETE` while `new` or
`provisioning` is refused 500, as NetBox refuses it. An object written under a branch's header, `X-NetBox-Branch`
its `schema_id`, is kept as that branch's and read under that header alone, beside `main`'s; deleting the branch
deletes them. A filter it does not know, or a request it does not answer, is an `AssertionError`, so that a test
never passes over a read the fake would have answered wrongly.

Nothing here opens a socket.
"""

from __future__ import annotations

import json
import secrets
from typing import Any

import httpx

HOST = "netbox.example"
ADDRESS = f"http://{HOST}"

NAMED = {
    "dcim/manufacturers/": "name",
    "dcim/platforms/": "name",
    "dcim/device-types/": "model",
    "dcim/sites/": "name",
    "dcim/device-roles/": "name",
    "extras/tags/": "name",
    "extras/config-templates/": "name",
    "extras/config-contexts/": "name",
    "dcim/devices/": "name",
    "dcim/interfaces/": "name",
    "ipam/ip-addresses/": "address",
    "users/users/": "username",
    "users/permissions/": "name",
    "users/groups/": "name",
}
"""What names an object of each path in a row that refers to it."""

RELATED = {
    "dcim/platforms/": {"manufacturer": "dcim/manufacturers/", "config_template": "extras/config-templates/"},
    "dcim/device-types/": {"manufacturer": "dcim/manufacturers/"},
    "dcim/devices/": {
        "device_type": "dcim/device-types/",
        "role": "dcim/device-roles/",
        "site": "dcim/sites/",
        "platform": "dcim/platforms/",
    },
    "users/tokens/": {"user": "users/users/"},
}
"""The members of each path that name another object by its id, and that object's path."""

FIELDS = {"name", "model", "address", "username", "key", "slug"}
"""The filters that match a member of the object's own, as it was posted."""

BRANCHES = "plugins/branching/branches/"

NEARER = {"new": "provisioning", "provisioning": "ready"}
"""The status a branch not yet `ready` reads at the next read of it by its id."""

UNSETTLED = ("new", "provisioning")
"""The statuses in which NetBox refuses a branch's `DELETE`, 500 (design/verified-facts.md, "A branch deleted before it
is `ready`")."""


class FakeNetBox:
    """NetBox's REST API, kept in memory. `refused` maps a request's number, counted from 1, to the status it is
    answered with instead, its `detail` echoing the request's `Authorization` header, as a careless server might."""

    def __init__(self) -> None:
        self.objects: dict[str, dict[int, dict[str, Any]]] = {}
        self.branched: dict[str, dict[str, dict[int, dict[str, Any]]]] = {}
        """What was written under each branch's header, by its `schema_id`, then by path."""
        self.requests: list[httpx.Request] = []
        self.refused: dict[int, int] = {}
        self._made: dict[str, int] = {}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if len(self.requests) in self.refused:
            detail = f"refused {request.headers.get('Authorization', '')}"
            return httpx.Response(self.refused[len(self.requests)], json={"detail": detail})
        path = request.url.path.removeprefix("/api/")
        collection, number = split(path)
        body: Any = json.loads(request.content) if request.content else None
        schema = request.headers.get("X-NetBox-Branch")
        if schema is not None:
            assert schema in self.branched, f"no branch has the schema_id {schema}"
            assert collection != BRANCHES, "a branch is asked for with no branch's header"
        if request.method == "GET" and number is None:
            return self._list(collection, request.url.params, schema)
        if request.method == "POST" and number is None:
            if collection == "users/users/" and not body.get("password"):
                return httpx.Response(400, json={"password": ["This field is required."]})
            row = self.add(collection, body, branch=schema)
            answer = self.shown(collection, row)
            if collection == "users/tokens/":
                answer["token"] = row["token"]
            return httpx.Response(201, json=answer)
        assert schema is None or request.method == "GET", f"the fake answers no {request.method} under a branch"
        held = self.view(collection, schema).get(number) if number is not None else None
        assert held is not None, f"the fake holds no {path}"
        if request.method == "GET":
            if collection == BRANCHES:
                held["status"] = NEARER.get(held["status"], held["status"])
            return httpx.Response(200, json=self.shown(collection, held))
        if request.method == "PATCH":
            held.update(kept(collection, body))
            return httpx.Response(200, json=self.shown(collection, held))
        if request.method == "DELETE":
            if collection == BRANCHES and held["status"] in UNSETTLED:
                refused = "A branch in the provisioning status may not be deleted."
                return httpx.Response(500, json={"error": refused, "exception": "AbortRequest"})
            del self.objects[collection][held["id"]]
            if collection == BRANCHES:
                del self.branched[held["schema_id"]]
            return httpx.Response(204)
        raise AssertionError(f"the fake answers no {request.method} {path}")

    def view(self, path: str, branch: str | None = None) -> dict[int, dict[str, Any]]:
        """The objects of `path` as read on `main`, or under the branch whose `schema_id` is `branch`: `main`'s with the
        branch's own beside them."""
        held = dict(self.objects.get(path, {}))
        if branch is not None:
            held.update(self.branched[branch].get(path, {}))
        return held

    def add(self, path: str, body: dict[str, Any], *, branch: str | None = None) -> dict[str, Any]:
        """An object of `path` kept as `body` says it, with an id of its own, on `main` or as the branch's whose
        `schema_id` is `branch`, without a request: the fake's state, as a test sets it. A branch is `ready` where
        `body` gives no status."""
        self._made[path] = self._made.get(path, 0) + 1
        row = {**kept(path, body), "id": self._made[path]}
        if path == "users/tokens/":
            row = {"key": secrets.token_hex(6), "token": secrets.token_hex(20), **row}
        if path == BRANCHES:
            row = {"schema_id": f"s{row['id']:07d}", "status": "ready", "tags": [], **row}
            self.branched[row["schema_id"]] = {}
        store = self.objects if branch is None else self.branched[branch]
        store.setdefault(path, {})[row["id"]] = row
        return row

    def held(self, path: str, **fields: object) -> dict[str, Any]:
        """The one object of `path`, as kept, whose members are `fields`: a test's handle on the fake's state."""
        rows = self.objects.get(path, {}).values()
        [found] = [row for row in rows if all(row.get(name) == value for name, value in fields.items())]
        return found

    def port(self, device: str, name: str) -> dict[str, Any]:
        """The interface `name` of the device `device`, as kept."""
        return self.held("dcim/interfaces/", device=self.held("dcim/devices/", name=device)["id"], name=name)

    def rows(self, path: str) -> list[dict[str, Any]]:
        return [self.shown(path, row) for row in self.objects.get(path, {}).values()]

    def sent(self, method: str) -> list[tuple[str, Any]]:
        """The path under `/api/` and the body of each request of `method`, in order."""
        return [
            (request.url.path.removeprefix("/api/"), json.loads(request.content) if request.content else None)
            for request in self.requests
            if request.method == method
        ]

    def writes(self) -> list[str]:
        """Each request that is not a `GET`, as its method and path."""
        return [f"{request.method} {request.url.path}" for request in self.requests if request.method != "GET"]

    def ref(self, path: str, number: int | None) -> dict[str, Any] | None:
        """The object of `path` numbered `number` as a row refers to it, None where `number` is."""
        if number is None:
            return None
        row = self.objects[path][number]
        found = {"id": number, NAMED[path]: row[NAMED[path]]}
        if path == "dcim/interfaces/":
            found["device"] = self.ref("dcim/devices/", row["device"])
        return found

    def cable_of(self, port: int) -> dict[str, Any] | None:
        """The cable, as kept, one of whose ends is the interface `port`."""
        for cable in self.objects.get("dcim/cables/", {}).values():
            if port in ends(cable, "a") + ends(cable, "b"):
                return cable
        return None

    def shown(self, path: str, row: dict[str, Any]) -> dict[str, Any]:
        """`row` as NetBox answers it."""
        shown = dict(row)
        for member, other in RELATED.get(path, {}).items():
            if member in row:
                shown[member] = self.ref(other, row[member])
        if "status" in row:
            shown["status"] = {"value": row["status"]}
        if path == "dcim/devices/":
            shown["tags"] = [{**self.objects["extras/tags/"][tag]} for tag in row.get("tags", [])]
            shown["config_template"] = None
        elif path == BRANCHES:
            shown["tags"] = [{**self.objects["extras/tags/"][tag]} for tag in row.get("tags", [])]
        elif path == "dcim/interfaces/":
            shown["device"] = self.ref("dcim/devices/", row["device"])
            shown["type"] = {"value": row["type"]}
            cable = self.cable_of(row["id"])
            shown["cable"] = {"id": cable["id"]} if cable is not None else None
            if cable is None:
                peers: list[int] = []
            else:
                peers = ends(cable, "b") if row["id"] in ends(cable, "a") else ends(cable, "a")
            shown["link_peers"] = [self.ref("dcim/interfaces/", peer) for peer in peers]
        elif path == "ipam/ip-addresses/":
            assert row["assigned_object_type"] == "dcim.interface"
            shown["assigned_object"] = self.ref("dcim/interfaces/", row["assigned_object_id"])
        elif path == "users/users/":
            shown.pop("password", None)
            shown.pop("is_superuser", None)
            shown.setdefault("is_active", True)
            shown["groups"] = [self.ref("users/groups/", group) for group in row.get("groups", [])]
            shown["permissions"] = [
                self.ref("users/permissions/", number)
                for number, grant in self.objects.get("users/permissions/", {}).items()
                if row["id"] in grant.get("users", [])
            ]
        elif path == "users/permissions/":
            shown["users"] = [self.ref("users/users/", user) for user in row.get("users", [])]
        elif path == "users/tokens/":
            shown["token"] = None
        elif path == "dcim/cables/":
            for side in ("a", "b"):
                shown[f"{side}_terminations"] = [
                    {"object_type": "dcim.interface", "object_id": end, "object": self.ref("dcim/interfaces/", end)}
                    for end in ends(row, side)
                ]
        return shown

    def _matches(self, path: str, row: dict[str, Any], name: str, value: str) -> bool:
        if name in FIELDS:
            return str(row.get(name)) == value
        if name == "tag" and path == "dcim/devices/":
            return any(self.objects["extras/tags/"][tag]["slug"] == value for tag in row.get("tags", []))
        if name == "device_id" and path == "dcim/interfaces/":
            return str(row["device"]) == value
        if name == "device_id" and path == "ipam/ip-addresses/":
            return str(self.objects["dcim/interfaces/"][row["assigned_object_id"]]["device"]) == value
        if name == "device_id" and path == "dcim/cables/":
            ports = self.objects["dcim/interfaces/"]
            return any(str(ports[end]["device"]) == value for end in ends(row, "a") + ends(row, "b"))
        if name == "interface_id" and path == "ipam/ip-addresses/":
            return str(row["assigned_object_id"]) == value
        if name == "interface_id" and path == "dcim/cables/":
            return any(str(end) == value for end in ends(row, "a") + ends(row, "b"))
        if name == "is_superuser" and path == "users/users/":
            return ("true" if row.get("is_superuser") else "false") == value
        if name == "user_id" and path == "users/tokens/":
            return str(row["user"]) == value
        raise AssertionError(f"the fake knows no filter {name} of {path}")

    def _list(self, path: str, params: httpx.QueryParams, branch: str | None = None) -> httpx.Response:
        rows = list(self.view(path, branch).values())
        for name, value in params.multi_items():
            if name not in ("limit", "offset"):
                rows = [row for row in rows if self._matches(path, row, name, value)]
        limit, offset = int(params.get("limit", 50)), int(params.get("offset", 0))
        page = rows[offset : offset + limit]
        following = f"{ADDRESS}/api/{path}?offset={offset + limit}" if offset + limit < len(rows) else None
        results = [self.shown(path, row) for row in page]
        return httpx.Response(200, json={"count": len(rows), "next": following, "previous": None, "results": results})


def split(path: str) -> tuple[str, int | None]:
    """A path under `/api/` as its collection and the object's number, None where it names the collection."""
    parts = path.strip("/").split("/")
    if parts[-1].isdigit():
        return "/".join(parts[:-1]) + "/", int(parts[-1])
    return "/".join(parts) + "/", None


def kept(path: str, body: dict[str, Any]) -> dict[str, Any]:
    """`body` as NetBox keeps it: a template's code with its surrounding whitespace stripped."""
    if path == "extras/config-templates/" and isinstance(body.get("template_code"), str):
        return {**body, "template_code": body["template_code"].strip()}
    return dict(body)


def ends(cable: dict[str, Any], side: str) -> list[int]:
    """The interface ids of one side of `cable`, as kept."""
    return [int(end["object_id"]) for end in cable.get(f"{side}_terminations", [])]
