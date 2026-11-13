"""The NetBox reader's contract tier: the reader against the running development NetBox (CONTRIBUTING.md, Test tiers).

Every test under tests/contract is marked `contract_netbox`: `make test` deselects them, and `make contract-netbox`
runs them with `local/.env` loaded, after `netbox/`'s own tier. The variables are read inside the fixtures, never at
import, since the pure tier collects this file too. Without `FYLGJA_NETBOX_ADDRESS` or `FYLGJA_NETBOX_TOKEN` every
test is skipped, and fails where `CI` is set; a test that writes needs the superuser's `FYLGJA_NETBOX_WRITE_TOKEN`
too. An `https://` address is verified against `FYLGJA_NETBOX_CA`, where it names a file.

No value of them is printed. A connect is made through `reader`, whose frame is hidden from pytest's tracebacks: a
frame below it holds the token as an argument, which pytest prints for a failing frame, so a connect that fails, and
the sweep, end the test in one sentence naming the variables, with no traceback (`refuse`), the address in it replaced
by its variable's name.

The reader is never given the write token. The tests' own writes are made by `netbox/seed/box.py`'s `Box`, loaded by
its path with the write token, and only under the header of a branch `fylgja-contract-<8 hex>` made from `main` and
deleted whatever happened; the session's start deletes any such branch that a stopped run left. The branches'
functions are the loaded module's (`branch_named`, `branched`, `BRANCHES`); what `netbox/tests/contract/conftest.py`
adds to them, which cannot be imported, is written again here, and the pure tier's
`tests/test_contract_branches.py` holds it. Every connection `reader` makes is over `Recorded`, which keeps each
request the connection sends, by the connection, in `SENT`.
"""

from __future__ import annotations

import contextlib
import importlib.util
import os
import secrets
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType
from typing import Any, NamedTuple, NoReturn, Protocol, cast

import httpx
import pytest
from fylgja_core.client import InvalidAddress, InvalidCA, InvalidToken, base_url, trust

from fylgja_netbox import NetBox, NetBoxError, ReaderDocument, connect
from fylgja_netbox.document import load as load_document
from fylgja_netbox.rows import Branch
from fylgja_netbox.transport import TOKEN

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parents[3]
READER_DOCUMENT = ROOT / "netbox" / "seed" / "reader.yaml"
"""The reader document of the seeded fixture network."""

ADDRESS = "FYLGJA_NETBOX_ADDRESS"
CA = "FYLGJA_NETBOX_CA"

PREFIX = "fylgja-contract-"
"""The name of every branch the tier makes, before its eight hex digits."""


def _loaded(path: Path) -> ModuleType:
    """The module at `path`, loaded by its path: `netbox/seed/` is no package the reader may import."""
    spec = importlib.util.spec_from_file_location("fylgja_netbox_contract_box", path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BOX = _loaded(ROOT / "netbox" / "seed" / "box.py")
"""`netbox/seed/box.py`: the tests' own writes, and the branches' functions."""

WRITE_TOKEN: str = BOX.TOKEN
BRANCHES: str = BOX.BRANCHES
BRANCH_WAIT_S: float = BOX.BRANCH_WAIT_S
BoxError: type[Exception] = BOX.BoxError


class Writes(Protocol):
    """`netbox/seed/box.py`'s `Box` as built: paths relative to `/api/`, and `branch` a branch's `schema_id`, sent as
    `X-NetBox-Branch`."""

    ensured: list[tuple[str, str, int]]

    def close(self) -> None: ...

    def hide(self, *values: str) -> None: ...

    def get(self, path: str, *, branch: str | None = None, **params: object) -> Any: ...

    def listed(self, path: str, *, branch: str | None = None, **params: object) -> list[dict[str, Any]]: ...

    def one(self, path: str, *, branch: str | None = None, **params: object) -> dict[str, Any] | None: ...

    def ensure(
        self, path: str, lookup: Mapping[str, object], body: Mapping[str, object], *, branch: str | None = None
    ) -> dict[str, Any]: ...

    def post(self, path: str, body: object, *, branch: str | None = None) -> Any: ...

    def patch(self, path: str, body: object, *, branch: str | None = None) -> Any: ...

    def delete(self, path: str, *, branch: str | None = None) -> None: ...


_Box = type("Box", (BOX.Box,), {"__repr__": lambda self: f"Box(<{ADDRESS}>)"})
"""`netbox/seed/box.py`'s `Box`, its `repr` naming the address's variable: pytest prints a failing test's arguments
by their repr, and the `Box`'s own holds the address."""


def writer(address: str, token: str, *, transport: httpx.BaseTransport | None = None) -> Writes:
    """`netbox/seed/box.py`'s `Box` at `address` with `token`, over `transport` where a test gives one."""
    return cast(Writes, _Box(address, token, transport=transport))


def branch_named(box: Writes, name: str) -> dict[str, Any] | None:
    """The branch `name`, None where none stands, held to that name: the loaded module's."""
    return cast(dict[str, Any] | None, BOX.branch_named(box, name))


CLOCK: Callable[[], float] = time.monotonic
SLEEP: Callable[[float], None] = time.sleep
"""The clock and the sleep of the branches' waits, read at each wait, which the pure tier replaces."""


def branched(box: Writes, name: str) -> dict[str, Any]:
    """The branch `name`, made where none stands and waited for until `ready`, `BRANCH_WAIT_S` at most: the loaded
    module's. In the readings of design/verified-facts.md, "NetBox 4.7.5 with netbox-branching 1.2.3", branches read
    `ready` 11.1 s, 8.4 s at most, 7.2 s, 7.0 s, 6.91 s, 6.8 s, 6.77 s, 6.2 s, 6.0 s, 5.87 s, 5.85 s, 5.8 s three times
    and 5.7 s after their request; and two whose `DELETE` NetBox refused while they provisioned read `ready` at reads
    26.7 s to 28.2 s after it, how much sooner not read ("A branch deleted before it is `ready`"). 120 s is about 4.3
    times the slowest, 28.2 s, a derivation; the bound is the module's `BRANCH_WAIT_S`."""
    return cast(dict[str, Any], BOX.branched(box, name, timeout_s=BRANCH_WAIT_S, clock=CLOCK, sleep=SLEEP))


OURS = (NetBoxError, BoxError, InvalidAddress, InvalidToken, InvalidCA)
"""The errors whose text holds no token: the reader's, the tests' writer's and the client's predicates."""


class Sent(NamedTuple):
    """One request a connection sent: its method and its path."""

    method: str
    path: str


SENT: dict[NetBox | str, list[Sent]] = {}
"""The requests each connection `reader` made sent, by the connection, in the order sent, and those of a connect that
made none, by a name of its own (`recording`): a test reads its own connection's, and the session's last test every
connection's."""


class Recorded(httpx.BaseTransport):
    """A transport that keeps each request in `sent` and passes it on to `inner`."""

    def __init__(self, inner: httpx.BaseTransport) -> None:
        self.inner = inner
        self.sent: list[Sent] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(Sent(request.method, request.url.path))
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


LAST = "test_the_reader_wrote_nothing"
"""The test that reads every connection's `SENT`, which runs last of the session, whatever its module's place."""


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every test under tests/contract `contract_netbox`, before `-m` selects, and put `LAST` last."""
    for item in items:
        if item.path.is_relative_to(_HERE):
            item.add_marker(pytest.mark.contract_netbox)
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
        refuse(f"the NetBox reader's contract tier needs {named} set: load local/.env and run make contract-netbox")


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
    """The CA file an `https://` address is verified against, where `FYLGJA_NETBOX_CA` names one."""
    named = os.environ.get(CA)
    return Path(named) if named else None


def real() -> httpx.HTTPTransport:
    """A real transport, as `connect` makes its own: an `https://` address verified against `FYLGJA_NETBOX_CA` where
    it names a file."""
    return httpx.HTTPTransport(verify=trust(ca()))


def recording(name: str) -> Recorded:
    """A real transport whose requests are kept in `SENT` under `name`: for a connect that is refused, and so makes no
    connection to keep them under."""
    made = Recorded(real())
    SENT[name] = made.sent
    return made


def reader(*, transport: httpx.BaseTransport | None = None) -> NetBox:
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


def reader_over(alter: Callable[[httpx.Request, httpx.Response], httpx.Response]) -> NetBox:
    """The reader's connection over a real transport whose every answer, read, is given to `alter(request, response)`
    on its way back, and what that returns answered in its place: a provocation NetBox cannot be written into, made
    in flight."""
    __tracebackhide__ = True
    return reader(transport=Altered(real(), alter))


UNSETTLED = ("new", "provisioning")
"""The statuses of a branch whose `DELETE` the tier does not send until the branch has left them: NetBox refused 500
the `DELETE` of a branch provisioning, and of one read `new` just before, which status NetBox then held not read, and
the branch stayed (design/verified-facts.md, "A branch deleted before it is `ready`"). A `DELETE` of a branch `new`
was not read; it is waited on because it comes before provisioning."""

POLL_S = 1.0
"""Seconds between two reads of a branch the tier waits on before its `DELETE`, as `branched` reads one."""


def _settled(box: Writes, row: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The branch `row`, one of the tier's, once NetBox holds it in no status of `UNSETTLED`, read by its name every
    `POLL_S` (`branch_named`) and never made; None where it is gone. `BRANCH_WAIT_S` at most, the bound `branched`'s
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


def _removed(box: Writes, row: Mapping[str, Any]) -> bool:
    """The branch `row`, one of the tier's, deleted once it has settled (`_settled`), whatever status it then holds,
    `failed` among them, and True; False where it is gone before, and nothing is sent. A `DELETE` of a `failed` branch
    was not read: where NetBox refuses one, the `BoxError` names the branch and its status."""
    held = _settled(box, row)
    if held is None:
        return False
    try:
        box.delete(f"{BRANCHES}{held['id']}/")
    except BoxError as e:
        status = held["status"]["value"]
        raise BoxError(f"the branch {held['name']}, {status}, was not deleted: {e}", getattr(e, "status", None)) from e
    return True


def delete(box: Writes, name: str) -> None:
    """The branch `name` deleted where it stands, held to that name (`branch_named`), once NetBox will delete it
    (`_removed`)."""
    left = branch_named(box, name)
    if left is not None:
        _removed(box, left)


def sweep(box: Writes) -> list[str]:
    """Every branch whose own name begins `PREFIX` deleted, each once NetBox will delete it (`_removed`), and no other;
    the names of those deleted, one gone before its `DELETE` not among them."""
    swept = []
    for row in box.listed(BRANCHES):
        if str(row.get("name", "")).startswith(PREFIX) and _removed(box, row):
            swept.append(str(row["name"]))
    return swept


@contextmanager
def scratch(box: Writes, name: str) -> Iterator[dict[str, Any]]:
    """The branch `name`, made and `ready`; deleted on leaving, whatever happened inside, also where it never read
    `ready`."""
    try:
        yield branched(box, name)
    finally:
        delete(box, name)


def as_row(made: Mapping[str, Any]) -> Branch:
    """A branch's representation as the reader's row."""
    return Branch(made["id"], made["name"], made["schema_id"], made["status"]["value"], made["last_sync"])


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
    deletes every branch of the tier's that a stopped run left."""
    need(ADDRESS, TOKEN)
    if not os.environ.get(WRITE_TOKEN):
        return
    made = _writer()
    swept: list[str] = []
    failure: str | None = None
    try:
        swept = sweep(made)
    except Exception as e:
        failure = f"the sweep of what a stopped run left failed: {said(e)}"
    finally:
        made.close()
    if failure is not None:
        refuse(failure)
    if swept:
        print(f"deleted what a stopped run left: {', '.join(swept)}")


@pytest.fixture(scope="session")
def conn() -> Iterator[NetBox]:
    """The reader's connection, with the reader's token."""
    with reader() as made:
        yield made


@pytest.fixture(scope="session")
def box() -> Iterator[Writes]:
    """The tests' own writer, `netbox/seed/box.py`'s `Box` with the superuser's token; a test that writes skips
    without it."""
    need(WRITE_TOKEN)
    made = _writer()
    try:
        yield made
    finally:
        made.close()


@pytest.fixture
def branch(box: Writes) -> Iterator[Branch]:
    """A branch of the test's own, `fylgja-contract-<8 hex>`, `ready`, as the reader's row. Deleted whatever the test
    did."""
    with scratch(box, PREFIX + secrets.token_hex(4)) as made:
        yield as_row(made)


@pytest.fixture(scope="session")
def document() -> ReaderDocument:
    """The seeded fixture network's reader document, `netbox/seed/reader.yaml`."""
    return load_document(READER_DOCUMENT)
