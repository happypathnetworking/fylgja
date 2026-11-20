"""A fake of the development Nautobot's REST API for the pure tier: `FakeNautobot`, an `httpx.MockTransport` handler.

It keeps what is posted by its path, gives each object a UUID, answers a list with its `count`, a page at a time,
and the filters the seed reads with, and records every request. An object is answered in the shape Nautobot 3.2.8
answers it (design/verified-facts.md, "Nautobot 3.2.8 with Golden Config 3.0.8"): a related object as `{id,
object_type, url}`, a status given by its name and answered so, an interface's `type` as `{value, label}`, its
`cable` and `cable_peer`, a cable's `termination_a_id` and `termination_b_id`, a repository's `current_head`, and a
query's text with its surrounding whitespace dropped. It holds what Nautobot installs: the statuses `Active` and
`Connected`, the namespace `Global`, and Golden Config's `Default Settings` with its dynamic group, of filter `{}`
and no member.

A dynamic group's members are stored, as Nautobot stores them: recomputed from its filter when the group is saved,
by a `PATCH`, unless a test names the group in `stale`, and otherwise left as a test sets them. A render answers 400
`No Golden Config settings found for this device` for a device that is no member, and otherwise the device's
configuration in `testdata/blueprint/three-node.json` with Golden Config's first line, or what a test puts in
`rendered`, its `graphql_data` the device's mapping itself. A filter it does not know, or a request it does not
answer, is an `AssertionError`, so that a test never passes over a read the fake would have answered wrongly.

Nothing here opens a socket.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import httpx

HOST = "nautobot.example"
ADDRESS = f"http://{HOST}"

NETWORK = Path(__file__).resolve().parents[2] / "testdata" / "blueprint" / "three-node.json"

SETTINGS = "plugins/golden-config/golden-config-settings/"
GROUPS = "extras/dynamic-groups/"
RENDER = "plugins/golden-config/generate-intended-config/"
STATUSES = "extras/statuses/"

FIRST = "# {name}: production configuration rendered by Golden Config (fylgja-templates)"
"""The first line of each render, the template's own."""

TYPES = {
    "extras/statuses/": "extras.status",
    "ipam/namespaces/": "ipam.namespace",
    "dcim/manufacturers/": "dcim.manufacturer",
    "dcim/platforms/": "dcim.platform",
    "dcim/device-types/": "dcim.devicetype",
    "dcim/location-types/": "dcim.locationtype",
    "dcim/locations/": "dcim.location",
    "extras/roles/": "extras.role",
    "extras/tags/": "extras.tag",
    "dcim/devices/": "dcim.device",
    "dcim/interfaces/": "dcim.interface",
    "ipam/prefixes/": "ipam.prefix",
    "ipam/ip-addresses/": "ipam.ipaddress",
    "ipam/ip-address-to-interface/": "ipam.ipaddresstointerface",
    "dcim/cables/": "dcim.cable",
    "extras/config-contexts/": "extras.configcontext",
    "extras/git-repositories/": "extras.gitrepository",
    "extras/graphql-queries/": "extras.graphqlquery",
    "extras/dynamic-groups/": "extras.dynamicgroup",
    SETTINGS: "nautobot_golden_config.goldenconfigsetting",
}
"""Each path the fake keeps, and its objects' `object_type`."""

RELATED = {
    "dcim/platforms/": {"manufacturer": "dcim/manufacturers/"},
    "dcim/device-types/": {"manufacturer": "dcim/manufacturers/"},
    "dcim/locations/": {"location_type": "dcim/location-types/"},
    "dcim/devices/": {
        "device_type": "dcim/device-types/",
        "role": "extras/roles/",
        "location": "dcim/locations/",
        "platform": "dcim/platforms/",
    },
    "dcim/interfaces/": {"device": "dcim/devices/"},
    "ipam/prefixes/": {"namespace": "ipam/namespaces/"},
    "ipam/ip-addresses/": {"namespace": "ipam/namespaces/", "parent": "ipam/prefixes/"},
    "ipam/ip-address-to-interface/": {"ip_address": "ipam/ip-addresses/", "interface": "dcim/interfaces/"},
    SETTINGS: {
        "jinja_repository": "extras/git-repositories/",
        "sot_agg_query": "extras/graphql-queries/",
        "dynamic_group": GROUPS,
    },
}
"""The members of each path that name another object by its id, and that object's path."""

FIELDS = {"name", "model", "slug", "prefix", "address"}
"""The filters that match a member of the object's own, as it was posted."""


class FakeNautobot:
    """Nautobot's REST API, kept in memory. `refused` maps a request's number, counted from 1, to the status it is
    answered with instead, its `detail` echoing the request's `Authorization` header, as a careless server might."""

    def __init__(self) -> None:
        self.objects: dict[str, dict[str, dict[str, Any]]] = {}
        self.requests: list[httpx.Request] = []
        self.refused: dict[int, int] = {}
        self.stale: set[str] = set()
        """The ids of the groups whose save leaves their stored members as they are."""
        self.rendered: dict[str, str] = {}
        """What a render of each device, by its name, answers in place of its configuration in the blueprint."""
        for name in ("Active", "Connected"):
            self.add(STATUSES, {"name": name})
        self.add("ipam/namespaces/", {"name": "Global"})
        group = self.add(
            GROUPS,
            {"name": "GoldenConfigSetting Default Settings scope", "content_type": "dcim.device", "filter": {}},
        )
        self.add(
            SETTINGS,
            {
                "name": "Default Settings",
                "slug": "default",
                "weight": 1000,
                "jinja_repository": None,
                "jinja_path_template": "",
                "sot_agg_query": None,
                "dynamic_group": group["id"],
            },
        )

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if len(self.requests) in self.refused:
            detail = f"refused {request.headers.get('Authorization', '')}"
            return httpx.Response(self.refused[len(self.requests)], json={"detail": detail})
        path = request.url.path.removeprefix("/api/")
        if path == RENDER and request.method == "GET":
            return self._render(request.url.params)
        collection, number, rest = split(path)
        assert collection in TYPES, f"the fake answers no {request.method} {path}"
        body: Any = json.loads(request.content) if request.content else None
        if request.method == "GET" and number is None:
            return self._list(collection, request.url.params)
        if request.method == "POST" and number is None:
            refused = self._refusal(collection, body)
            if refused is not None:
                return refused
            return httpx.Response(201, json=self.shown(collection, self.add(collection, body)))
        held = self.objects.get(collection, {}).get(str(number))
        assert held is not None, f"the fake holds no {path}"
        if request.method == "GET" and rest == "members":
            assert collection == GROUPS
            members = [self.objects["dcim/devices/"][device] for device in held.get("members", [])]
            return self._page(request.url.params, "dcim/devices/", members)
        assert rest == "", f"the fake answers no {request.method} {path}"
        if request.method == "GET":
            return httpx.Response(200, json=self.shown(collection, held))
        if request.method == "PATCH":
            held.update(self.kept(collection, body))
            if collection == GROUPS and held["id"] not in self.stale:
                held["members"] = self.matching(held["filter"])
            return httpx.Response(200, json=self.shown(collection, held))
        if request.method == "DELETE":
            del self.objects[collection][held["id"]]
            return httpx.Response(204)
        raise AssertionError(f"the fake answers no {request.method} {path}")

    def add(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """An object of `path` kept as `body` says it, with a UUID of its own, without a request: the fake's state, as
        a test sets it."""
        row = {**self.kept(path, body), "id": str(uuid.uuid4())}
        if path == "extras/git-repositories/":
            row.setdefault("current_head", "")
        if path == GROUPS:
            row.setdefault("members", [])
        self.objects.setdefault(path, {})[row["id"]] = row
        return row

    def kept(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """`body` as Nautobot keeps it: a status by its id, and a query's text with its surrounding whitespace
        dropped."""
        kept = dict(body)
        if isinstance(kept.get("status"), str) and kept["status"] not in self.objects.get(STATUSES, {}):
            kept["status"] = self.held(STATUSES, name=kept["status"])["id"]
        if path == "extras/graphql-queries/" and isinstance(kept.get("query"), str):
            kept["query"] = kept["query"].strip()
        return kept

    def matching(self, filter: dict[str, Any]) -> list[str]:
        """The ids of the devices a group's `filter` selects: those carrying any of its `tags`; none where it names
        none, as the installed group of filter `{}` held none."""
        tags = set(filter.get("tags", []))
        devices = self.objects.get("dcim/devices/", {}).values()
        return [row["id"] for row in devices if tags & self.tags(row)]

    def tags(self, device: dict[str, Any]) -> set[str]:
        return {self.objects["extras/tags/"][tag]["name"] for tag in device.get("tags", [])}

    def held(self, path: str, **fields: object) -> dict[str, Any]:
        """The one object of `path`, as kept, whose members are `fields`: a test's handle on the fake's state."""
        rows = self.objects.get(path, {}).values()
        [found] = [row for row in rows if all(row.get(name) == value for name, value in fields.items())]
        return found

    def port(self, device: str, name: str) -> dict[str, Any]:
        """The interface `name` of the device `device`, as kept."""
        return self.held("dcim/interfaces/", device=self.held("dcim/devices/", name=device)["id"], name=name)

    def group(self) -> dict[str, Any]:
        """The installed setting's dynamic group, as kept."""
        return self.objects[GROUPS][self.held(SETTINGS, slug="default")["dynamic_group"]]

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

    def ref(self, path: str, number: str | None) -> dict[str, Any] | None:
        """The object of `path` whose id is `number` as a row refers to it, None where `number` is."""
        if number is None:
            return None
        return {"id": number, "object_type": TYPES[path], "url": f"{ADDRESS}/api/{path}{number}/"}

    def cable_of(self, port: str) -> dict[str, Any] | None:
        """The cable, as kept, one of whose ends is the interface `port`."""
        for cable in self.objects.get("dcim/cables/", {}).values():
            if port in (cable["termination_a_id"], cable["termination_b_id"]):
                return cable
        return None

    def shown(self, path: str, row: dict[str, Any]) -> dict[str, Any]:
        """`row` as Nautobot answers it."""
        shown = {**row, "object_type": TYPES[path], "url": f"{ADDRESS}/api/{path}{row['id']}/"}
        for member, other in RELATED.get(path, {}).items():
            if member in row:
                shown[member] = self.ref(other, row[member])
        if "status" in row:
            shown["status"] = self.ref(STATUSES, row["status"])
        if path == "dcim/devices/":
            shown["tags"] = [self.ref("extras/tags/", tag) for tag in row.get("tags", [])]
        elif path == "dcim/interfaces/":
            shown["type"] = {"value": row["type"], "label": row["type"]}
            cable = self.cable_of(row["id"])
            shown["cable"] = self.ref("dcim/cables/", cable["id"]) if cable is not None else None
            if cable is None:
                shown["cable_peer"] = None
            else:
                ends = (cable["termination_a_id"], cable["termination_b_id"])
                shown["cable_peer"] = self.ref("dcim/interfaces/", ends[1] if ends[0] == row["id"] else ends[0])
        elif path == "dcim/cables/":
            for side in ("a", "b"):
                shown[f"termination_{side}"] = self.ref("dcim/interfaces/", row[f"termination_{side}_id"])
        elif path == GROUPS:
            shown.pop("members", None)
        return shown

    def _refusal(self, path: str, body: dict[str, Any]) -> httpx.Response | None:
        """Nautobot's 400 for a cable to a port that is cabled already."""
        if path == "dcim/cables/":
            for side in ("a", "b"):
                if self.cable_of(body[f"termination_{side}_id"]) is not None:
                    return httpx.Response(400, json={f"termination_{side}_id": ["Interface is already cabled."]})
        return None

    def _matches(self, path: str, row: dict[str, Any], name: str, value: str) -> bool:
        if name in FIELDS:
            return str(row.get(name)) == value
        if name == "namespace" and path in ("ipam/prefixes/", "ipam/ip-addresses/"):
            return value in (row["namespace"], self.objects["ipam/namespaces/"][row["namespace"]]["name"])
        if name == "tags" and path == "dcim/devices/":
            return value in self.tags(row)
        if name == "device_id" and path == "dcim/interfaces/":
            return str(row["device"]) == value
        if name == "device_id" and path == "dcim/cables/":
            ports = self.objects["dcim/interfaces/"]
            ends = (row["termination_a_id"], row["termination_b_id"])
            return any(end in ports and ports[end]["device"] == value for end in ends)
        if name in ("ip_address", "interface") and path == "ipam/ip-address-to-interface/":
            return str(row[name]) == value
        raise AssertionError(f"the fake knows no filter {name} of {path}")

    def _list(self, path: str, params: httpx.QueryParams) -> httpx.Response:
        rows = list(self.objects.get(path, {}).values())
        for name, value in params.multi_items():
            if name not in ("limit", "offset"):
                rows = [row for row in rows if self._matches(path, row, name, value)]
        return self._page(params, path, rows)

    def _page(self, params: httpx.QueryParams, path: str, rows: list[dict[str, Any]]) -> httpx.Response:
        limit, offset = int(params.get("limit", 50)), int(params.get("offset", 0))
        page = rows[offset : offset + limit]
        following = f"{ADDRESS}/api/{path}?offset={offset + limit}" if offset + limit < len(rows) else None
        results = [self.shown(path, row) for row in page]
        return httpx.Response(200, json={"count": len(rows), "next": following, "previous": None, "results": results})

    def _render(self, params: httpx.QueryParams) -> httpx.Response:
        """Golden Config's render of the device `device_id`, as the installed setting gives it."""
        assert sorted(params) == ["device_id"], f"the fake renders by device_id alone, not {params}"
        number = params["device_id"]
        device = self.objects.get("dcim/devices/", {}).get(number)
        if device is None:
            return httpx.Response(400, json={"detail": f"Device with id '{number}' not found"})
        if number not in self.group().get("members", []):
            return httpx.Response(400, json={"detail": "No Golden Config settings found for this device"})
        name = device["name"]
        if name in self.rendered:
            text = self.rendered[name]
        else:
            network = json.loads(NETWORK.read_text())["network"]
            [config] = [held["config"] for held in network["devices"] if held["name"] == name]
            text = "\n".join([FIRST.format(name=name), *config.split("\n")[1:]])
        active = [row["data"] for row in self.objects.get("extras/config-contexts/", {}).values() if row["is_active"]]
        context = {key: value for data in active for key, value in data.items()}
        data = {"hostname": name, "description": device.get("comments", ""), "config_context": context}
        answer = {"intended_config": text, "intended_config_lines": text.split("\n"), "graphql_data": data}
        return httpx.Response(200, json={**answer, "diff": None, "diff_lines": []})


def split(path: str) -> tuple[str, str | None, str]:
    """A path under `/api/` as its collection, the object's UUID, None where it names the collection, and what
    follows the UUID."""
    parts = path.strip("/").split("/")
    for at, part in enumerate(parts):
        try:
            uuid.UUID(part)
        except ValueError:
            continue
        return "/".join(parts[:at]) + "/", part, "/".join(parts[at + 1 :])
    return "/".join(parts) + "/", None, ""
