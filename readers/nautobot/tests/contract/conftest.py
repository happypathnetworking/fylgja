"""The Nautobot reader's contract tier: the reader against the running development Nautobot (CONTRIBUTING.md, Test
tiers).

Every test under tests/contract is marked `contract_nautobot`: `make test` deselects them, and `make
contract-nautobot` runs them with `local/.env` loaded, after `nautobot/`'s own tier. The variables are read inside the
fixtures, never at import, since the pure tier collects this file too. Without `FYLGJA_NAUTOBOT_ADDRESS` or
`FYLGJA_NAUTOBOT_TOKEN` every test is skipped, and fails where `CI` is set; a test that writes needs the superuser's
`FYLGJA_NAUTOBOT_WRITE_TOKEN` too. An `https://` address is verified against `FYLGJA_NAUTOBOT_CA`, where it names a
file.

No value of them is printed. A connect is made through `reader`, whose frame is hidden from pytest's tracebacks: a
frame below it holds the token as an argument, which pytest prints for a failing frame, so a connect that fails, and
the sweep, end the test in one sentence naming the variables, with no traceback (`refuse`), the address in it replaced
by its variable's name.

The reader is never given the write token. The tests' own writes are made by `nautobot/seed/box.py`'s `Box`, loaded by
its path with the write token. Nautobot has no branch to write under, so a test writes only objects named
`fylgja-contract-<8 hex>` (`contract_name`), deleted whatever happened, or edits a seeded object it puts back whatever
happened (`restored`): a cable between two seeded devices is so labelled, and a device whose name is no label carries
it as its comments. The session's start deletes every object so named that a stopped run left (`sweep`), and
renders each seeded device once by the superuser's token (`settle`), so that no head a push moved is left for a read
to fetch. A push to the template repository is a commit to the bare repository the `git` service serves, by its path
(`pushed`), put back the same way. `nautobot/seed/seed.py`, whose functions these use, imports `box` by its module
name, so the loaded `box.py` is registered as `box` before it is loaded. Every connection `reader` makes is over
`Recorded`, which keeps each request the connection sends, by the connection, in `SENT`. An account of the tier's own,
whose token only that account can make, is made as plan 1's `nautobot/seed/account.py` makes the reader's, through its
`Basic` (`account`). The pure tier's `tests/test_contract_helpers.py` holds `restored`, `sweep` and `pushed`.
"""

from __future__ import annotations

import contextlib
import importlib.util
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any, NamedTuple, NoReturn, Protocol, cast

import httpx
import pytest
from fylgja_core.client import InvalidAddress, InvalidCA, InvalidToken, base_url, trust

from fylgja_nautobot import Nautobot, NautobotError, ReaderDocument, connect
from fylgja_nautobot.document import load as load_document
from fylgja_nautobot.transport import TOKEN

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parents[3]
SEED = ROOT / "nautobot" / "seed"
READER_DOCUMENT = SEED / "reader.yaml"
"""The reader document of the seeded fixture network."""

ADDRESS = "FYLGJA_NAUTOBOT_ADDRESS"
CA = "FYLGJA_NAUTOBOT_CA"

PREFIX = "fylgja-contract-"
"""The name of every object the tier makes, before its eight hex digits."""


def _loaded(name: str, path: Path) -> ModuleType:
    """The module at `path`, loaded by its path under `name` and registered there, as a dataclass of it needs:
    `nautobot/seed/` is no package the reader may import."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


BOX = _loaded("fylgja_nautobot_contract_box", SEED / "box.py")
"""`nautobot/seed/box.py`: the tests' own writes."""

sys.modules["box"] = BOX
SEEDING = _loaded("fylgja_nautobot_contract_seed", SEED / "seed.py")
"""`nautobot/seed/seed.py`: the templates' commit, the render and the fixture's configurations. It imports `box` by its
module name, which is the loaded `box.py` where nothing else holds that name."""

ACCOUNT = _loaded("fylgja_nautobot_contract_account", SEED / "account.py")
"""`nautobot/seed/account.py`: the `Basic` an account makes its own token under."""

WRITE_TOKEN: str = BOX.TOKEN
BoxError: type[Exception] = BOX.BoxError

TEMPLATE = SEED / SEEDING.TEMPLATES / "nokia_srl.j2"
"""The tracked template the fixture's platform renders, which `pushed` replaces in a commit of its own."""


class Writes(Protocol):
    """`nautobot/seed/box.py`'s `Box` as built: paths relative to `/api/`, and a list read whole to its `count`."""

    ensured: list[tuple[str, str, str]]

    def close(self) -> None: ...

    def hide(self, *values: str) -> None: ...

    def get(self, path: str, **params: object) -> Any: ...

    def listed(self, path: str, **params: object) -> list[dict[str, Any]]: ...

    def one(self, path: str, **params: object) -> dict[str, Any] | None: ...

    def ensure(self, path: str, lookup: Mapping[str, object], body: Mapping[str, object]) -> dict[str, Any]: ...

    def post(self, path: str, body: object) -> Any: ...

    def patch(self, path: str, body: object) -> Any: ...

    def delete(self, path: str) -> None: ...


_Box = type("Box", (BOX.Box,), {"__repr__": lambda self: f"Box(<{ADDRESS}>)"})
"""`nautobot/seed/box.py`'s `Box`, its `repr` naming the address's variable: pytest prints a failing test's arguments
by their repr, and the `Box`'s own holds the address."""


def writer(address: str, token: str, *, transport: httpx.BaseTransport | None = None) -> Writes:
    """`nautobot/seed/box.py`'s `Box` at `address` with `token`, over `transport` where a test gives one."""
    return cast(Writes, _Box(address, token, transport=transport))


def contract_name() -> str:
    """A name of the tier's own, `fylgja-contract-<8 hex>`, for an object a test makes."""
    return PREFIX + secrets.token_hex(4)


OURS = (NautobotError, BoxError, InvalidAddress, InvalidToken, InvalidCA)
"""The errors whose text holds no token: the reader's, the tests' writer's and the client's predicates."""


class Sent(NamedTuple):
    """One request a connection sent: its method, its path, its query's names, in order, and the bytes of its path and
    query as sent."""

    method: str
    path: str
    params: tuple[str, ...]
    length: int


SENT: dict[Nautobot | str, list[Sent]] = {}
"""The requests each connection `reader` made sent, by the connection, in the order sent, and those of a connect that
made none, by a name of its own (`recording`): a test reads its own connection's, and the session's last test every
connection's."""


class Recorded(httpx.BaseTransport):
    """A transport that keeps each request in `sent` and passes it on to `inner`."""

    def __init__(self, inner: httpx.BaseTransport) -> None:
        self.inner = inner
        self.sent: list[Sent] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        names = tuple(name for name, _ in request.url.params.multi_items())
        self.sent.append(Sent(request.method, request.url.path, names, len(request.url.raw_path)))
        return self.inner.handle_request(request)

    def close(self) -> None:
        self.inner.close()


class Altered(httpx.BaseTransport):
    """A transport that passes each request to `inner` and gives its answer, read, to `alter` on its way back."""

    def __init__(
        self, inner: httpx.BaseTransport, alter: Callable[[httpx.Request, httpx.Response], httpx.Response]
    ) -> None:
        self.inner = inner
        self.alter = alter

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self.inner.handle_request(request)
        response.read()
        return self.alter(request, response)

    def close(self) -> None:
        self.inner.close()


LAST = "test_the_reader_sent_get_alone"
"""The test that reads every connection's `SENT`, which runs last of the session, whatever its module's place."""


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every test under tests/contract `contract_nautobot`, before `-m` selects, and put `LAST` last."""
    for item in items:
        if item.path.is_relative_to(_HERE):
            item.add_marker(pytest.mark.contract_nautobot)
    items.sort(key=lambda item: item.path.is_relative_to(_HERE) and item.name == LAST)


def refuse(sentence: str) -> NoReturn:
    """End the test in `sentence`, with no traceback: a failure where `CI` is set, a skip elsewhere."""
    __tracebackhide__ = True
    if os.environ.get("CI"):
        pytest.fail(sentence, pytrace=False)
    pytest.skip(sentence)


def need(*names: str) -> None:
    """Skip, or fail where `CI` is set, naming each of `names` that is not set."""
    __tracebackhide__ = True
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        named = ", ".join(missing)
        refuse(
            f"the Nautobot reader's contract tier needs {named} set: load local/.env and run make contract-nautobot"
        )


def _address_forms() -> list[str]:
    address = os.environ.get(ADDRESS, "")
    forms = {address, address.rstrip("/")}
    with contextlib.suppress(InvalidAddress):
        forms.add(base_url(address))
    return sorted(filter(None, forms), key=len, reverse=True)


def said(e: Exception) -> str:
    """What a failure said: one of `OURS` by its text, the address replaced by its variable's name; anything else by
    its type alone, since its text could hold a token."""
    if not isinstance(e, OURS):
        return type(e).__name__
    text = f"{type(e).__name__}: {e}"
    for form in _address_forms():
        text = text.replace(form, f"<{ADDRESS}>")
    return text


def scrubbed(text: str) -> str:
    """`text` with the address, in each of its forms, and each token of the tier's replaced by its variable's name: a
    process's output, which a failing assertion may show."""
    named = [(os.environ.get(name, ""), name) for name in (TOKEN, WRITE_TOKEN)]
    named += [(form, ADDRESS) for form in _address_forms()]
    for form, name in sorted((pair for pair in named if pair[0]), key=lambda pair: len(pair[0]), reverse=True):
        text = text.replace(form, f"<{name}>")
    return text


def ca() -> Path | None:
    """The CA file an `https://` address is verified against, where `FYLGJA_NAUTOBOT_CA` names one."""
    named = os.environ.get(CA)
    return Path(named) if named else None


def real() -> httpx.HTTPTransport:
    """A real transport, as `connect` makes its own: an `https://` address verified against `FYLGJA_NAUTOBOT_CA`
    where it names a file."""
    return httpx.HTTPTransport(verify=trust(ca()))


def recording(name: str) -> Recorded:
    """A real transport whose requests are kept in `SENT` under `name`: for a connect that is refused, and so makes no
    connection to keep them under."""
    made = Recorded(real())
    SENT[name] = made.sent
    return made


def reader(*, transport: httpx.BaseTransport | None = None) -> Nautobot:
    """The reader's connection, with the reader's token, over `Recorded` and `transport`, a real one (`real`) where
    it is None, its requests kept in `SENT` under it: a connect that fails ends the test in one sentence."""
    __tracebackhide__ = True
    recorded = Recorded(transport if transport is not None else real())
    try:
        made = connect(os.environ[ADDRESS], os.environ[TOKEN], ca=ca(), transport=recorded)
    except Exception as e:
        failure = f"the reader could not connect with {ADDRESS}, {TOKEN} and {CA}: {said(e)}"
    else:
        SENT[made] = recorded.sent
        return made
    refuse(failure)


def reader_over(alter: Callable[[httpx.Request, httpx.Response], httpx.Response]) -> Nautobot:
    """The reader's connection over a real transport whose every answer, read, is given to `alter(request, response)`
    on its way back, and what that returns answered in its place: a provocation Nautobot cannot be written into, made
    in flight."""
    __tracebackhide__ = True
    return reader(transport=Altered(real(), alter))


def _sent(value: object) -> object:
    """A member of a row as a `PATCH` sends it back: a related object, `{id, object_type, url}`, by its id, and a list
    of them by their ids."""
    if isinstance(value, dict) and "object_type" in value:
        return value.get("id")
    if isinstance(value, list):
        return [_sent(member) for member in value]
    return value


@contextmanager
def restored(box: Writes, path: str, fields: Sequence[str]) -> Iterator[dict[str, Any]]:
    """The seeded object at `path`, relative to `/api/`, as it stands, for a test to edit; on leaving, whatever
    happened inside, each of `fields` that no longer holds what it held is written back in one `PATCH`, and nothing
    is sent where none differs."""
    held: dict[str, Any] = box.get(path)
    before = {name: _sent(held.get(name)) for name in fields}
    try:
        yield held
    finally:
        now: dict[str, Any] = box.get(path)
        differ = {name: value for name, value in before.items() if _sent(now.get(name)) != value}
        if differ:
            box.patch(path, differ)


SWEPT: tuple[tuple[str, str], ...] = (
    ("dcim/cables/", "label"),
    ("dcim/devices/", "name"),
    ("dcim/devices/", "comments"),
    ("extras/config-contexts/", "name"),
    ("dcim/platforms/", "name"),
    ("dcim/manufacturers/", "name"),
    ("extras/tags/", "name"),
    ("users/permissions/", "name"),
    ("users/users/", "username"),
)
"""Each list the tier makes objects in, with the member that names them, in the order they are deleted: a cable
between two seeded devices by its label, first; a device by its name, or by its comments where the tier gives it a
name of no label (`""`); a device before the platform and the tag it holds, a manufacturer after its platforms, an
account after its permissions."""

CABLES = "dcim/cables/"


def sweep(box: Writes) -> list[str]:
    """Every object of `SWEPT` whose member there begins `PREFIX` deleted, a device's cables first, and no other; the
    names of those deleted, each `<path> <the member's value>`."""
    swept = []
    for path, member in SWEPT:
        for row in box.listed(path):
            name = str(row.get(member) or "")
            if not name.startswith(PREFIX):
                continue
            if path == "dcim/devices/":
                for cable in box.listed(CABLES, device_id=row["id"]):
                    box.delete(f"{CABLES}{cable['id']}/")
            box.delete(f"{path}{row['id']}/")
            swept.append(f"{path} {name}")
    return swept


def settle(box: Writes) -> None:
    """Each seeded device rendered once by the superuser's token, which fetches any head a push of a stopped run moved;
    a render that is not the fixture's configuration is a `BoxError` naming the device."""
    said = SEEDING.renders(box, SEEDING.configurations())
    if said:
        raise BoxError("; ".join(said))


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


def pushed(text: str, *, into: Path | None = None) -> str:
    """The tracked templates with `TEMPLATE` replaced by `text`, committed onto `main` of the bare repository `into`
    serves, `served()` where it is None, and made servable; the commit `main` then names, which is the commit before
    where its tree is already `main`'s. Pushing the tracked template's own text puts the templates back."""
    target = served() if into is None else into
    with tempfile.TemporaryDirectory() as scratch:
        files = Path(scratch)
        shutil.copytree(SEED / SEEDING.TEMPLATES, files / SEEDING.TEMPLATES)
        (files / SEEDING.TEMPLATES / TEMPLATE.name).write_text(text)
        commit = SEEDING.templates(SEEDING.command, target, files)
    if commit is not None:
        return str(commit)
    at = ["--git-dir", str(target / SEEDING.REPOSITORY)]
    return str(SEEDING.command([*at, "rev-parse", "refs/heads/main"])).strip()


USERS = "users/users/"
PERMISSIONS = "users/permissions/"
TOKENS = "users/tokens/"


def _grant(name: str, kind: str, action: str, holder: str, constraints: Mapping[str, str] | None = None) -> object:
    return {
        "name": name,
        "object_types": [kind],
        "actions": [action],
        "constraints": dict(constraints) if constraints is not None else None,
        "enabled": True,
        "users": [holder],
    }


def _minted(box: Writes, username: str, holder: str) -> str:
    """A write-disabled token of the account `holder`, `username`, made by the account itself, as plan 1's
    `account.mint` makes the reader's: a password generated here, handed to `box.hide` and kept nowhere, set by the
    superuser; a temporary `add` on the account's own tokens; the account's own `POST` under HTTP Basic; the temporary
    grant deleted, whatever came of the `POST`. Its frame is hidden from pytest's tracebacks, which print a failing
    frame's arguments."""
    __tracebackhide__ = True
    password = secrets.token_urlsafe(48)
    box.hide(password)
    box.patch(f"{USERS}{holder}/", {"password": password})
    temporary = box.post(PERMISSIONS, _grant(contract_name(), "users.token", "add", holder, ACCOUNT.OWN))
    try:
        basic = ACCOUNT.Basic(os.environ[ADDRESS], username, password)
        try:
            made = basic.post(TOKENS, {"write_enabled": False, "description": username})
        finally:
            basic.close()
    finally:
        box.delete(f"{PERMISSIONS}{temporary['id']}/")
    key = made.get("key") if isinstance(made, dict) else None
    if not isinstance(key, str) or made.get("write_enabled") is not False:
        raise BoxError(f"POST /api/{TOKENS} answered no write-disabled token for {username}")
    box.hide(key)
    return key


@contextmanager
def account(box: Writes, grants: Sequence[tuple[str, str]]) -> Iterator[str]:
    """An account of the tier's own, named `contract_name()`, holding one permission of the tier's naming for each of
    `grants`, an object type and an action, with no constraint, and the token it made itself (`_minted`), which is
    yielded and handed to `box.hide`; on leaving, whatever happened, its permissions and then the account are deleted,
    its token with it. Nautobot gives a token to the account that requests it alone, so a superuser cannot make one
    for another account (design/verified-facts.md, "A token is the requesting account's, whoever it names.")."""
    username = contract_name()
    made = box.post(USERS, {"username": username, "is_active": True})
    held: list[str] = []
    try:
        for kind, action in grants:
            held.append(box.post(PERMISSIONS, _grant(contract_name(), kind, action, made["id"]))["id"])
        yield _minted(box, username, made["id"])
    finally:
        try:
            for id in held:
                box.delete(f"{PERMISSIONS}{id}/")
        finally:
            box.delete(f"{USERS}{made['id']}/")


def _writer() -> Writes:
    """The tests' own `Box`, with the superuser's token: one that cannot be made ends the test in one sentence."""
    __tracebackhide__ = True
    try:
        made = writer(os.environ[ADDRESS], os.environ[WRITE_TOKEN])
    except Exception as e:
        failure = f"the tests' writer could not be made with {ADDRESS} and {WRITE_TOKEN}: {said(e)}"
    else:
        made.hide(os.environ.get(TOKEN, ""))
        return made
    refuse(failure)


@pytest.fixture(scope="session", autouse=True)
def _tier() -> None:
    """Every test needs the reader's address and token; where the write token is set too, the session's start
    deletes every object of the tier's that a stopped run left, and renders each seeded device once."""
    need(ADDRESS, TOKEN)
    if not os.environ.get(WRITE_TOKEN):
        return
    made = _writer()
    swept: list[str] = []
    failure: str | None = None
    try:
        swept = sweep(made)
        settle(made)
    except Exception as e:
        failure = f"the sweep of what a stopped run left, or the settling render, failed: {said(e)}"
    finally:
        made.close()
    if failure is not None:
        refuse(failure)
    if swept:
        print(f"deleted what a stopped run left: {', '.join(swept)}")


@pytest.fixture(scope="session")
def conn() -> Iterator[Nautobot]:
    """The reader's connection, with the reader's token."""
    with reader() as made:
        yield made


@pytest.fixture(scope="session")
def box() -> Iterator[Writes]:
    """The tests' own writer, `nautobot/seed/box.py`'s `Box` with the superuser's token; a test that writes skips
    without it."""
    need(WRITE_TOKEN)
    made = _writer()
    try:
        yield made
    finally:
        made.close()


@pytest.fixture(scope="session")
def document() -> ReaderDocument:
    """The seeded fixture network's reader document, `nautobot/seed/reader.yaml`."""
    return load_document(READER_DOCUMENT)
