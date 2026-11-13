"""The NetBox contract tier: `netbox/`'s code against the running development NetBox (CONTRIBUTING.md, Test tiers).

Every test under tests/contract is marked `contract_netbox`: `make test` deselects them and `make contract-netbox`
runs them, with `local/.env` loaded. The variables are read inside the fixtures, never at import, since the pure
tier collects this file too. Without them a test is skipped, and fails where `CI` is set. No value of them is
printed.

A test that writes does so under a branch of its own, `fylgja-contract-<8 hex>`, deleted whatever the test did, so
that `main` is left as the seed left it; the session's start deletes every such branch a stopped run left. A branch
still `new` or `provisioning` is waited on, by reads alone, before its `DELETE`. The writer is `box.py`'s `Box`, its
`repr` naming the address's variable.
"""

from __future__ import annotations

import os
import secrets
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from box import ADDRESS, BRANCH_WAIT_S, BRANCHES, TOKEN, Box, BoxError, branch_named, branched

_HERE = Path(__file__).resolve().parent

PREFIX = "fylgja-contract-"
"""The name of every branch the tier makes, before its eight hex digits."""


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every test under tests/contract `contract_netbox`, before `-m` selects."""
    for item in items:
        if item.path.is_relative_to(_HERE):
            item.add_marker(pytest.mark.contract_netbox)


def need(*names: str) -> None:
    """Skip, or fail where `CI` is set, naming each of `names` that is not set."""
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        named = ", ".join(missing)
        sentence = f"the NetBox contract tier needs {named} set: load local/.env and run make contract-netbox"
        if os.environ.get("CI"):
            pytest.fail(sentence)
        pytest.skip(sentence)


class _Box(Box):
    """`box.py`'s `Box`, its `repr` naming the address's variable: pytest prints a failing test's arguments by their
    repr, and the `Box`'s own holds the address."""

    def __repr__(self) -> str:
        return f"Box(<{ADDRESS}>)"


def writer(address: str, token: str, *, transport: httpx.BaseTransport | None = None) -> Box:
    """`box.py`'s `Box` at `address` with `token`, over `transport` where a test gives one, its `repr` holding no
    address."""
    return _Box(address, token, transport=transport)


@pytest.fixture(scope="session")
def box() -> Iterator[Box]:
    """The superuser's `Box`, as the seed makes it (`writer`)."""
    need(ADDRESS, TOKEN)
    made = writer(os.environ[ADDRESS], os.environ[TOKEN])
    try:
        yield made
    finally:
        made.close()


CLOCK: Callable[[], float] = time.monotonic
SLEEP: Callable[[float], None] = time.sleep
"""The clock and the sleep of the branches' waits, read at each wait, which the pure tier replaces."""

UNSETTLED = ("new", "provisioning")
"""The statuses of a branch whose `DELETE` the tier does not send until the branch has left them: NetBox refused 500
the `DELETE` of a branch provisioning, and of one read `new` just before, which status NetBox then held not read, and
the branch stayed (design/verified-facts.md, "A branch deleted before it is `ready`"). A `DELETE` of a branch `new`
was not read; it is waited on because it comes before provisioning."""

POLL_S = 1.0
"""Seconds between two reads of a branch the tier waits on before its `DELETE`, as `branched` reads one."""


def settled(box: Box, row: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The branch `row`, one of the tier's, once NetBox holds it in no status of `UNSETTLED`, read by its name every
    `POLL_S` (`branch_named`) and never made; None where it is gone. `BRANCH_WAIT_S` at most, the bound `box.py`'s
    docstring sizes from its readings; one still unsettled then is a `BoxError` naming it and its status."""
    name, held = str(row["name"]), row
    started = CLOCK()
    while held["status"]["value"] in UNSETTLED:
        waited = CLOCK() - started
        if waited >= BRANCH_WAIT_S:
            status = held["status"]["value"]
            raise BoxError(f"the branch {name} was still {status} {BRANCH_WAIT_S:g} s on, so no DELETE was sent")
        SLEEP(min(POLL_S, BRANCH_WAIT_S - waited))
        found = branch_named(box, name)
        if found is None:
            return None
        held = found
    return held


def removed(box: Box, row: Mapping[str, Any]) -> None:
    """The branch `row`, one of the tier's, deleted once it has settled (`settled`), whatever status it then holds;
    nothing is sent where it is gone before."""
    held = settled(box, row)
    if held is not None:
        box.delete(f"{BRANCHES}{held['id']}/")


def delete(box: Box, name: str) -> None:
    """The branch `name` deleted where it stands, held to that name (`branch_named`), once NetBox will delete it
    (`removed`)."""
    left = branch_named(box, name)
    if left is not None:
        removed(box, left)


def sweep(box: Box) -> None:
    """Every branch whose own name begins `PREFIX` deleted, each once NetBox will delete it (`removed`), and no
    other."""
    for row in box.listed(BRANCHES):
        if str(row.get("name", "")).startswith(PREFIX):
            removed(box, row)


@contextmanager
def scratch(box: Box, name: str) -> Iterator[dict[str, Any]]:
    """The branch `name`, made and `ready`; deleted on leaving, whatever happened inside, also where it never read
    `ready`."""
    try:
        yield branched(box, name, clock=CLOCK, sleep=SLEEP)
    finally:
        delete(box, name)


@pytest.fixture(scope="session", autouse=True)
def no_branch_left(box: Box) -> None:
    """Every branch of the tier's that a stopped run left, deleted before the first test."""
    sweep(box)


@pytest.fixture
def branch(box: Box) -> Iterator[dict[str, Any]]:
    """A branch of the test's own, `fylgja-contract-<8 hex>`, `ready`: its representation, with its `id`, `name` and
    `schema_id`. Deleted whatever the test did."""
    with scratch(box, PREFIX + secrets.token_hex(4)) as made:
        yield made
