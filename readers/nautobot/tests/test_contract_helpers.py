"""The Nautobot reader's contract tier's own functions, over `httpx.MockTransport` and a bare repository under
`tmp_path`: an edited seeded object is put back whatever the test did, the sweep deletes the tier's objects and no
other, a device's cables first, and a push commits the template given and the tracked one back.

Nothing here opens a socket: Nautobot is a fake that keeps the rows it is given and every request it is sent.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest
from contract.conftest import TEMPLATE, Writes, pushed, restored, sweep, writer

HOST = "nautobot.example"
ADDRESS = f"http://{HOST}"
WRITE = "0123456789abcdef0123456789abcdef01234567"


class Rows:
    """A fake of Nautobot's REST lists under `/api/`: each list's rows by its path, read whole (`count`, `results`,
    `limit` and `offset`), `?device_id=` of cables selecting by either end's device; an object read, patched and
    deleted by its id. Every request is kept as its method and its path."""

    def __init__(self, rows: dict[str, list[dict[str, Any]]]) -> None:
        self.rows = rows
        self.sent: list[tuple[str, str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/")
        self.sent.append((request.method, path))
        for listed, rows in self.rows.items():
            if path == listed and request.method == "GET":
                held = rows
                device = request.url.params.get("device_id")
                if device is not None:
                    held = [row for row in rows if device in row.get("devices", [])]
                start, size = int(request.url.params.get("offset", 0)), int(request.url.params.get("limit", 50))
                return httpx.Response(200, json={"count": len(held), "results": held[start : start + size]})
            if path.startswith(listed) and path != listed:
                id = path.removeprefix(listed).strip("/")
                row = next((row for row in rows if row["id"] == id), None)
                if row is None:
                    return httpx.Response(404, json={"detail": "Not found."})
                if request.method == "GET":
                    return httpx.Response(200, json=row)
                if request.method == "PATCH":
                    row.update(json.loads(request.content))
                    return httpx.Response(200, json=row)
                if request.method == "DELETE":
                    rows.remove(row)
                    return httpx.Response(204)
        return httpx.Response(404, json={"detail": "Not found."})


def over(rows: Rows) -> Writes:
    return writer(ADDRESS, WRITE, transport=httpx.MockTransport(rows))


def port(id: str, *, enabled: bool = True) -> dict[str, Any]:
    return {
        "id": id,
        "name": "ethernet-1/1",
        "enabled": enabled,
        "device": {"id": "d1", "object_type": "dcim.device", "url": f"{ADDRESS}/api/dcim/devices/d1/"},
        "tags": [{"id": "t1", "object_type": "extras.tag", "url": f"{ADDRESS}/api/extras/tags/t1/"}],
    }


def test_restored_puts_back_each_field_it_names_whatever_happened() -> None:
    rows = Rows({"dcim/interfaces/": [port("i1")]})
    box = over(rows)
    with pytest.raises(RuntimeError), restored(box, "dcim/interfaces/i1/", ["enabled", "tags"]) as held:
        assert held["enabled"] is True
        box.patch("dcim/interfaces/i1/", {"enabled": False, "tags": [], "name": "other"})
        raise RuntimeError("the test failed")
    (row,) = rows.rows["dcim/interfaces/"]
    assert (row["enabled"], row["tags"], row["name"]) == (True, ["t1"], "other")
    assert rows.sent[-1] == ("PATCH", "dcim/interfaces/i1/")
    patches = [sent for sent in rows.sent if sent[0] == "PATCH"]
    assert len(patches) == 2


def test_restored_sends_nothing_where_nothing_differs() -> None:
    rows = Rows({"dcim/interfaces/": [port("i1")]})
    with restored(over(rows), "dcim/interfaces/i1/", ["enabled", "device", "tags"]):
        pass
    assert [method for method, _ in rows.sent] == ["GET", "GET"]


def test_the_sweep_deletes_the_tiers_objects_and_no_other() -> None:
    rows = Rows(
        {
            "dcim/devices/": [
                {"id": "d1", "name": "n1"},
                {"id": "d2", "name": "fylgja-contract-0a1b2c3d"},
                {"id": "d3", "name": None},
                {"id": "d4", "name": "", "comments": "fylgja-contract-0f0f0f0f"},
                {"id": "d5", "name": None, "comments": "FYLGJA-MARKER-fixture"},
            ],
            "dcim/cables/": [
                {"id": "c1", "devices": ["d1", "d2"]},
                {"id": "c2", "devices": ["d1", "d3"]},
                {"id": "c3", "devices": ["d1", "d5"], "label": "fylgja-contract-c0ffee00"},
                {"id": "c4", "devices": ["d1", "d4"], "label": ""},
            ],
            "extras/config-contexts/": [{"id": "x1", "name": "fylgja-probes"}],
            "dcim/platforms/": [{"id": "p1", "name": "SR Linux"}, {"id": "p2", "name": "fylgja-contract-00000001"}],
            "dcim/manufacturers/": [{"id": "m1", "name": "Nokia"}],
            "extras/tags/": [
                {"id": "t1", "name": "fylgja"},
                {"id": "t2", "name": "fylgja-contract-ffffffff"},
                {"id": "t3", "name": "FYLGJA-CONTRACT-FFFFFFFF"},
            ],
            "users/permissions/": [{"id": "g1", "name": "fylgja-contract-12345678"}, {"id": "g2", "name": "view"}],
            "users/users/": [
                {"id": "u1", "username": "fylgja-reader"},
                {"id": "u2", "username": "fylgja-contract-12345678"},
            ],
        }
    )
    swept = sweep(over(rows))
    assert swept == [
        "dcim/cables/ fylgja-contract-c0ffee00",
        "dcim/devices/ fylgja-contract-0a1b2c3d",
        "dcim/devices/ fylgja-contract-0f0f0f0f",
        "dcim/platforms/ fylgja-contract-00000001",
        "extras/tags/ fylgja-contract-ffffffff",
        "users/permissions/ fylgja-contract-12345678",
        "users/users/ fylgja-contract-12345678",
    ]
    deleted = [path for method, path in rows.sent if method == "DELETE"]
    assert deleted[:3] == ["dcim/cables/c3/", "dcim/cables/c1/", "dcim/devices/d2/"], "a device's cables go first"
    assert deleted[3:5] == ["dcim/cables/c4/", "dcim/devices/d4/"], "a device named by its comments, its cables first"
    assert {key: [row["id"] for row in held] for key, held in rows.rows.items()} == {
        "dcim/devices/": ["d1", "d3", "d5"],
        "dcim/cables/": ["c2"],
        "extras/config-contexts/": ["x1"],
        "dcim/platforms/": ["p1"],
        "dcim/manufacturers/": ["m1"],
        "extras/tags/": ["t1", "t3"],
        "users/permissions/": ["g2"],
        "users/users/": ["u1"],
    }


def git(repository: Path, *argv: str) -> str:
    done = subprocess.run(["git", "--git-dir", str(repository), *argv], capture_output=True, text=True, check=True)
    return done.stdout


def test_pushed_commits_the_template_given_and_the_tracked_one_back(tmp_path: Path) -> None:
    repository = tmp_path / "templates.git"
    tracked = TEMPLATE.read_text()
    first = pushed(tracked, into=tmp_path)
    assert git(repository, "show", f"{first}:{TEMPLATE.name}") == tracked
    assert (repository / "info" / "refs").is_file(), "made servable over plain HTTP"

    changed = tracked + "# fylgja-contract-0a1b2c3d\n"
    second = pushed(changed, into=tmp_path)
    assert second != first
    assert git(repository, "show", f"{second}:{TEMPLATE.name}") == changed
    assert git(repository, "rev-parse", "refs/heads/main").strip() == second
    assert first in git(repository, "rev-list", second)

    back = pushed(tracked, into=tmp_path)
    assert back not in (first, second)
    assert git(repository, "show", f"{back}:{TEMPLATE.name}") == tracked
    assert git(repository, "rev-parse", f"{back}^{{tree}}") == git(repository, "rev-parse", f"{first}^{{tree}}")
    assert pushed(tracked, into=tmp_path) == back, "the tree is main's already, so nothing is committed"
