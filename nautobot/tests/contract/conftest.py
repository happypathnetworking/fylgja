"""The Nautobot contract tier: `nautobot/`'s code against the running development Nautobot (CONTRIBUTING.md, Test
tiers).

Every test under tests/contract is marked `contract_nautobot`: `make test` deselects them and `make contract-nautobot`
runs them, with `local/.env` loaded. The variables are read inside the fixtures, never at import, since the pure tier
collects this file too. Without them a test is skipped, and fails where `CI` is set. No value of them is printed.

Nautobot has no branch to write under, so a test that writes names its objects `fylgja-contract-<8 hex>` and deletes
them whatever the test did, and the session's start deletes every tag so named that a stopped run left; the seed's own
objects are never touched. The writer is `box.py`'s `Box`, its `repr` naming the address's variable.
"""

from __future__ import annotations

import os
import secrets
import subprocess
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from box import ADDRESS, TOKEN, Box

_HERE = Path(__file__).resolve().parent

PREFIX = "fylgja-contract-"
"""The name of every object the tier makes, before its eight hex digits."""

TAGS = "extras/tags/"


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every test under tests/contract `contract_nautobot`, before `-m` selects."""
    for item in items:
        if item.path.is_relative_to(_HERE):
            item.add_marker(pytest.mark.contract_nautobot)


def need(*names: str) -> None:
    """Skip, or fail where `CI` is set, naming each of `names` that is not set."""
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        named = ", ".join(missing)
        sentence = f"the Nautobot contract tier needs {named} set: load local/.env and run make contract-nautobot"
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


@pytest.fixture(scope="session")
def served() -> Path:
    """The directory the `git` service serves: the main checkout's `local/nautobot/git`, found from the repository's
    common directory as the Makefile's `MAIN` is, so that a worktree reaches the same one."""
    common = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=_HERE,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return Path(common).parent / "local" / "nautobot" / "git"


def sweep(box: Box) -> None:
    """Every tag whose own name begins `PREFIX` deleted, and no other."""
    for row in box.listed(TAGS):
        if str(row.get("name", "")).startswith(PREFIX):
            box.delete(f"{TAGS}{row['id']}/")


@pytest.fixture(scope="session", autouse=True)
def nothing_left(box: Box) -> None:
    """Every tag of the tier's that a stopped run left, deleted before the first test."""
    sweep(box)


@pytest.fixture
def scratch(box: Box) -> Iterator[str]:
    """A name of the test's own, `fylgja-contract-<8 hex>`, for the object it writes: any tag of that name is deleted
    after, whatever the test did."""
    name = PREFIX + secrets.token_hex(4)
    try:
        yield name
    finally:
        left = box.one(TAGS, name=name)
        if left is not None:
            box.delete(f"{TAGS}{left['id']}/")
