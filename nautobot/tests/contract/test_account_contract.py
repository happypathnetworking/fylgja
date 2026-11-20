"""`nautobot/seed/account.py` against the running development Nautobot: the reader's token reads what a read reads and
renders what the superuser renders, writes nothing, and the account made twice keeps its token.

The reader is a `Box` over `FYLGJA_NAUTOBOT_TOKEN`, which `make nautobot-seed` writes to `local/.env` (the account's
line), read inside its fixture and never at import; without it a test is skipped, and fails where `CI` is set. No
value is printed. The tests write nothing but a file under `tmp_path` and read the changelog's count to hold it still.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import account
import pytest
import seed
from box import ADDRESS, Box, BoxError

from .conftest import need, writer

TOKEN = "FYLGJA_NAUTOBOT_TOKEN"

NOWRITE = "fylgja-contract-nowrite"
"""The name of the location a refused create names, which no Nautobot holds after it."""


@pytest.fixture(scope="module")
def reader(box: Box) -> Iterator[Box]:
    """The reader's `Box`, over the account's token."""
    need(ADDRESS, TOKEN)
    made = writer(os.environ[ADDRESS], os.environ[TOKEN])
    try:
        yield made
    finally:
        made.close()


def devices(box: Box) -> dict[str, dict[str, Any]]:
    return {str(row["name"]): row for row in box.listed("dcim/devices/", tags=seed.TAG)}


def counts(box: Box) -> dict[str, int]:
    """The `count` each list of Task 1, Step 7 answers, by what is asked, and the default group's stored members, the
    list the grants grew by for the reader to hold a group to its filter."""
    rows = devices(box)
    group = box.one(seed.GROUPS, name="GoldenConfigSetting Default Settings scope")
    assert group is not None
    got: dict[str, int] = {}

    def listed(label: str, path: str, **params: object) -> None:
        got[label] = len(box.listed(path, **params))

    listed("extras/tags/?name=fylgja", "extras/tags/", name=seed.TAG)
    listed("dcim/devices/?tags=fylgja", "dcim/devices/", tags=seed.TAG)
    for name, row in rows.items():
        listed(f"dcim/interfaces/?device_id={name}", "dcim/interfaces/", device_id=row["id"])
        listed(f"dcim/cables/?device_id={name}", "dcim/cables/", device_id=row["id"])
    listed("dcim/platforms/", "dcim/platforms/")
    listed("dcim/manufacturers/", "dcim/manufacturers/")
    listed("ipam/ip-addresses/", "ipam/ip-addresses/")
    listed("extras/config-contexts/?name=fylgja-probes", "extras/config-contexts/", name="fylgja-probes")
    got["extras/object-changes/"] = box.get("extras/object-changes/", limit=1)["count"]
    listed(seed.SETTINGS, seed.SETTINGS)
    listed("extras/git-repositories/", "extras/git-repositories/")
    listed(seed.GROUPS, seed.GROUPS)
    listed("the default group's members", f"{seed.GROUPS}{group['id']}/members/")
    stored = "extras/static-group-associations/"
    listed("the default group's stored members", stored, dynamic_group=group["id"])
    return got


def changelog(box: Box) -> int:
    count: int = box.get("extras/object-changes/", limit=1)["count"]
    return count


def test_the_readers_token_reads_what_a_read_reads(box: Box, reader: Box) -> None:
    """Each list of Task 1, Step 7, as the reader reads it, counts what the superuser's counts; the changelog's count is
    read before and after each, since a read writes no row."""
    before = changelog(box)
    seen = counts(reader)
    assert changelog(box) == before
    assert seen == counts(box)
    assert seen["dcim/devices/?tags=fylgja"] == 3
    assert seen["the default group's stored members"] == 3


def test_the_readers_render_is_the_superusers(box: Box, reader: Box) -> None:
    """Each device's render by the reader holds the superuser's `intended_config` byte for byte, and its data, with no
    push between the two."""
    rows = devices(box)
    assert sorted(rows) == ["n1", "n2", "n3"]
    for row in rows.values():
        wanted = box.get(seed.RENDER, device_id=row["id"])
        got = reader.get(seed.RENDER, device_id=row["id"])
        assert got["intended_config"] == wanted["intended_config"]
        assert got["graphql_data"] == wanted["graphql_data"]


def test_the_readers_token_writes_nothing(box: Box, reader: Box) -> None:
    """A create, a change and a delete are each refused 403, and the changelog's count has not moved."""
    rows = devices(box)
    before = changelog(box)
    site = next(iter(box.listed("dcim/location-types/", name="Site")))
    n1 = f"dcim/devices/{rows['n1']['id']}/"
    attempts: dict[str, Callable[[], object]] = {
        "POST": lambda: reader.post("dcim/locations/", {"name": NOWRITE, "location_type": site["id"]}),
        "PATCH": lambda: reader.patch(n1, {"comments": "FYLGJA-MARKER-fixture"}),
        "DELETE": lambda: reader.delete(n1),
    }
    for method, attempt in attempts.items():
        with pytest.raises(BoxError) as caught:
            attempt()
        assert (method, caught.value.status) == (method, 403)
    assert changelog(box) == before
    assert box.one("dcim/locations/", name=NOWRITE) is None
    assert sorted(devices(box)) == ["n1", "n2", "n3"]


def test_the_account_made_twice_keeps_its_token(box: Box, tmp_path: Path) -> None:
    """The account run again over a file holding the line writes nothing and changes no byte, and the reader's grants
    are as they were: none made, none brought to its row."""
    need(TOKEN)
    path = tmp_path / ".env"
    path.write_text(f"{TOKEN}={os.environ[TOKEN]}\n")
    path.chmod(0o600)
    before = path.read_bytes()
    assert account.ensure(path, box) == []
    assert (path.read_bytes(), stat.S_IMODE(path.stat().st_mode)) == (before, 0o600)
    assert box.one(account.PERMISSIONS, name=account.TEMPORARY.name) is None
