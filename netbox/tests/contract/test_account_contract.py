"""`netbox/seed/account.py`'s account against the running development NetBox: what its token reads, what it is
refused, and the account made twice.

`reader` is a `Box` over the account's own token, `FYLGJA_NETBOX_TOKEN`, which `make netbox-seed` writes into
`local/.env`; `box` is the superuser's; the `reader` is made by the conftest's `writer`, whose `repr` holds no
address. The module's fixture seeds `main` first, as
`make netbox-seed` does; on a `main` the seed has already filled it writes nothing. Each refusal is asserted at the
status it was read to answer (design/verified-facts.md, "NetBox 4.7.5 with netbox-branching 1.2.3"): a write or a
list refused for want of a permission is 403. Every write a test expects refused is under its own branch's header or
of that branch, which the `branch` fixture deletes, so that one that wrongly succeeded lands on no row of `main`.

The tests rest on two budgets (design/verified-facts.md, "NetBox 4.7.5 with netbox-branching 1.2.3"). The `branch`
fixture waits up to `BRANCH_WAIT_S`, 120 s, for `ready`: branches read `ready` 11.1 s at most after their request,
and two whose `DELETE` NetBox refused while they provisioned read `ready` at reads 26.7 s to 28.2 s after it; 120 s
is about 4.3 times the slowest, 28.2 s, a derivation. Every request is given `TIMEOUT_S`, 30 s, a first value: a
user's create read 1.48 s, and the slowest request read, a branch's `DELETE`, read in scripts beside the tier and not
as the fixture ends, 3.41 s and 3.31 s in one script and 2.83 s in another; 30 s is 8.8 times the slowest, a
derivation.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import account
import pytest
import seed
from box import ADDRESS, BRANCHES, Box, BoxError, branch_named

from .conftest import need, writer

ROOT = Path(__file__).resolve().parents[3]
FILES = ROOT / "netbox" / "seed"

JOURNAL = "extras/journal-entries/"
BRANCH_TYPE = "netbox_branching.branch"


@pytest.fixture(scope="module")
def fixture(box: Box) -> dict[str, Any]:
    """`main` seeded, and the fixture it was seeded from."""
    seed.seed(box, FILES)
    return seed.load(FILES)


def own(name: str) -> Iterator[Box]:
    line = account.LINES[name]
    need(ADDRESS, line)
    made = writer(os.environ[ADDRESS], os.environ[line])
    try:
        yield made
    finally:
        made.close()


@pytest.fixture(scope="module")
def reader() -> Iterator[Box]:
    """The reader's `Box`, over `fylgja-reader`'s token."""
    yield from own(account.READER)


SITE = {"name": "fylgja-contract-site", "slug": "fylgja-contract-site"}


def refused(status: int, call: Any, *args: Any, **kwargs: Any) -> str:
    """`call(*args, **kwargs)` raises a `BoxError` of `status`; its sentence."""
    with pytest.raises(BoxError) as raised:
        call(*args, **kwargs)
    assert raised.value.status == status, str(raised.value)
    return str(raised.value)


def changelogs(box: Box, under: str) -> tuple[int, int]:
    """The `count` of `main`'s changelog and of the branch `under`'s."""
    return (
        box.get("core/object-changes/", limit=1)["count"],
        box.get("core/object-changes/", branch=under, limit=1)["count"],
    )


def read(who: Box, box: Box, under: str | None) -> dict[str, Any]:
    """What a read reads, by `who`'s token, under the branch `under` where it is given; each list and the render
    held to the superuser's. Answers the devices by their names."""
    devices = {row["name"]: row for row in who.listed("dcim/devices/", branch=under, tag=seed.TAG)}
    assert sorted(devices) == ["n1", "n2", "n3"]
    ports: list[dict[str, Any]] = []
    cables: set[int] = set()
    for device in devices.values():
        ports += who.listed("dcim/interfaces/", branch=under, device_id=device["id"])
        cables |= {row["id"] for row in who.listed("dcim/cables/", branch=under, device_id=device["id"])}
    assert len(ports) == 15
    assert len(cables) == 2
    platform = who.one("dcim/platforms/", branch=under, name="SR Linux")
    assert platform is not None and platform["manufacturer"]["name"] == "Nokia"
    assert who.one("dcim/manufacturers/", branch=under, name="Nokia") is not None
    assert who.one("extras/tags/", branch=under, name=seed.TAG) is not None
    context = who.one("extras/config-contexts/", branch=under, name="fylgja-probes")
    assert context is not None and context["is_active"] is False
    changes = who.get("core/object-changes/", branch=under, limit=1)
    assert changes["count"] == box.get("core/object-changes/", branch=under, limit=1)["count"]
    path = f"dcim/devices/{devices['n1']['id']}/render-config/"
    assert who.post(path, None, branch=under)["content"] == box.post(path, None, branch=under)["content"]
    return devices


def test_the_readers_token_reads_what_a_read_reads(
    box: Box, reader: Box, fixture: dict[str, Any], branch: dict[str, Any]
) -> None:
    read(reader, box, None)
    found = branch_named(reader, branch["name"])
    assert found is not None and found["id"] == branch["id"] and found["schema_id"] == branch["schema_id"]
    read(reader, box, branch["schema_id"])


def test_the_readers_token_writes_nothing(
    box: Box, reader: Box, fixture: dict[str, Any], branch: dict[str, Any]
) -> None:
    under = branch["schema_id"]
    changes = changelogs(box, under)
    n1 = box.one("dcim/devices/", name="n1")
    tag = box.one("extras/tags/", name=seed.TAG)
    assert n1 is not None and tag is not None
    refused(403, reader.post, "dcim/sites/", SITE, branch=under)
    entry = {"assigned_object_type": BRANCH_TYPE, "assigned_object_id": branch["id"], "kind": "info", "comments": "x"}
    refused(403, reader.post, JOURNAL, entry, branch=under)
    refused(403, reader.patch, f"{BRANCHES}{branch['id']}/", {"tags": [tag["id"]]})
    refused(403, reader.delete, f"dcim/devices/{n1['id']}/", branch=under)
    assert changelogs(box, under) == changes
    assert box.one("dcim/sites/", branch=under, name=SITE["name"]) is None
    assert box.one("dcim/devices/", branch=under, name="n1") is not None


def test_the_accounts_made_twice_keep_their_tokens(box: Box, tmp_path: Path) -> None:
    """The line the environment gives, in a file of mode 0600 of the test's own, removed after."""
    names = [account.LINES[name] for name in account.GRANTS]
    need(*names)
    env = tmp_path / ".env"
    descriptor = os.open(env, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w") as out:
            out.write("".join(f"{name}={os.environ[name]}\n" for name in names))
        before = env.read_bytes()
        holders = {name: box.one("users/users/", username=name) for name in account.GRANTS}
        assert all(row is not None for row in holders.values())
        counted = {
            name: box.get("users/tokens/", user_id=row["id"], limit=1)["count"]
            for name, row in holders.items()
            if row is not None
        }
        assert account.ensure(env, box) == []
        unmoved = env.read_bytes() == before
        assert unmoved
        assert {
            name: box.get("users/tokens/", user_id=row["id"], limit=1)["count"]
            for name, row in holders.items()
            if row is not None
        } == counted
    finally:
        env.unlink(missing_ok=True)
