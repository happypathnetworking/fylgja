"""The reader's contract tier: the reader against the running development Infrahub (CONTRIBUTING.md, Test tiers).

Every test under tests/contract is marked `contract`: `make test` deselects them, and `make contract` runs them with
`local/.env` loaded and `FYLGJA_INFRAHUB_SEED` set on its command line, the path of the main checkout's `seed.json`.
The variables are read inside the fixtures, never at import, since the pure tier collects this file too. Without
`FYLGJA_INFRAHUB_ADDRESS` or `FYLGJA_INFRAHUB_TOKEN` every test is skipped, and fails where `CI` is set; a test that
writes needs the writer's `FYLGJA_INFRAHUB_WRITE_TOKEN` too, and one that reads the seed `FYLGJA_INFRAHUB_SEED`.

No value of them is printed. A connect is made through `reader` or `writer_of`, whose frames are hidden from pytest's
tracebacks: a frame below them holds a token as an argument, which pytest prints for a failing frame, so a connect
that fails, and the sweep, end the test in one sentence naming the variables, with no traceback (`refuse`), the
address in it replaced by its variable's name.

The reader is never given the writer. A test writes only on a branch `fylgja-contract-<8 hex>` the writer makes from
`main` and deletes whatever happened; the session's start deletes any such branch that a stopped run left, and any
`FylgjaProbe` named `fc-*` where `main`'s schema holds the kind. Every connection `reader` makes is over `Recorded`,
which keeps each request the reader sends in `SENT`, so that the session's last test, `LAST`, can hold the reader to
sending nothing that writes.
"""

from __future__ import annotations

import contextlib
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any, NamedTuple, NoReturn

import httpx
import pytest
from fylgja_core.client import InvalidAddress, InvalidCA, InvalidToken, base_url, trust

from fylgja_infrahub import Infrahub, InfrahubError, ReaderDocument, connect
from fylgja_infrahub.document import load as load_document
from fylgja_infrahub.transport import KEEPALIVE_S

from .writer import TOKEN as WRITE_TOKEN
from .writer import Writer, WriterError
from .writer import connect as writer_from

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parents[3]
READER_DOCUMENT = ROOT / "infrahub" / "seed" / "reader.yaml"
"""The reader document of the seeded fixture network."""

ADDRESS = "FYLGJA_INFRAHUB_ADDRESS"
TOKEN = "FYLGJA_INFRAHUB_TOKEN"
CA = "FYLGJA_INFRAHUB_CA"
SEED = "FYLGJA_INFRAHUB_SEED"

OURS = (InfrahubError, WriterError, InvalidAddress, InvalidToken, InvalidCA)
"""The errors whose text holds no token: the reader's, the writer's and the client's predicates."""

LAST = "test_the_reader_wrote_nothing"
"""The test the session runs last, once every other has read through `reader`."""


class Sent(NamedTuple):
    """One request a reader's connection sent: its method, its path, and, for a POST, the first word of its GraphQL
    document past the comments, None for any other request."""

    method: str
    path: str
    document: str | None


SENT: list[Sent] = []
"""Every request the reader's connections sent through `Recorded`, in the order sent, over the session."""


class Recorded(httpx.BaseTransport):
    """A transport that keeps each request in `SENT` and passes it on to `inner`."""

    def __init__(self, inner: httpx.BaseTransport) -> None:
        self.inner = inner

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        SENT.append(Sent(request.method, request.url.path, _first(request) if request.method == "POST" else None))
        return self.inner.handle_request(request)

    def close(self) -> None:
        self.inner.close()


def _first(request: httpx.Request) -> str:
    """The first word of a POST's GraphQL document, its comment lines passed over; "" where it holds none."""
    try:
        document = json.loads(request.content).get("query")
    except (ValueError, AttributeError):
        return ""
    lines = [line for line in str(document or "").splitlines() if not line.lstrip().startswith("#")]
    words = "\n".join(lines).split(maxsplit=1)
    return words[0] if words else ""


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every test under tests/contract `contract`, before `-m` selects, and run `LAST` after every other."""
    for item in items:
        if item.path.is_relative_to(_HERE):
            item.add_marker(pytest.mark.contract)
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
        refuse(f"the contract tier needs {', '.join(missing)} set: load local/.env and run make contract")


def said(e: Exception) -> str:
    """What a failure said: one of `OURS` by its text, the address replaced by its variable's name; anything else by
    its type alone, since its text could hold a token."""
    if not isinstance(e, OURS):
        return type(e).__name__
    text = f"{type(e).__name__}: {e}"
    address = os.environ.get(ADDRESS, "")
    forms = {address, address.rstrip("/")}
    with contextlib.suppress(InvalidAddress):
        forms.add(base_url(address))
    for form in sorted(filter(None, forms), key=len, reverse=True):
        text = text.replace(form, f"<{ADDRESS}>")
    return text


def scrubbed(text: str) -> str:
    """`text` with the address, in each of its forms, and each token of the tier's replaced by its variable's name: a
    process's output, which a failing assertion may show."""
    forms = {name: {os.environ.get(name, "")} for name in (TOKEN, WRITE_TOKEN)}
    address = os.environ.get(ADDRESS, "")
    forms[ADDRESS] = {address, address.rstrip("/")}
    with contextlib.suppress(InvalidAddress):
        forms[ADDRESS].add(base_url(address))
    named = [(form, name) for name, held in forms.items() for form in held if form]
    for form, name in sorted(named, key=lambda pair: len(pair[0]), reverse=True):
        text = text.replace(form, f"<{name}>")
    return text


def ca() -> Path | None:
    """The CA file an `https://` address is verified against, where `FYLGJA_INFRAHUB_CA` names one."""
    named = os.environ.get(CA)
    return Path(named) if named else None


def real() -> httpx.HTTPTransport:
    """A real transport, as `connect` makes its own: an `https://` address verified against `FYLGJA_INFRAHUB_CA`
    where it names a file, and an idle connection kept `KEEPALIVE_S`."""
    return httpx.HTTPTransport(verify=trust(ca()), limits=httpx.Limits(keepalive_expiry=KEEPALIVE_S))


def reader(*, transport: httpx.BaseTransport | None = None) -> Infrahub:
    """The reader's connection, with the reader's token, over `Recorded` and `transport`, a real one (`real`) where it
    is None: a connect that fails ends the test in one sentence."""
    __tracebackhide__ = True
    try:
        inner = transport if transport is not None else real()
        return connect(os.environ[ADDRESS], os.environ[TOKEN], ca=ca(), transport=Recorded(inner))
    except Exception as e:
        failure = f"the reader could not connect with {ADDRESS}, {TOKEN} and {CA}: {said(e)}"
    refuse(failure)


def writer_of() -> Writer:
    """The tier's own writer, with the admin's token: one that cannot be made ends the test in one sentence."""
    __tracebackhide__ = True
    try:
        return writer_from(os.environ[ADDRESS], os.environ[WRITE_TOKEN], os.environ.get(CA))
    except Exception as e:
        failure = f"the tier's writer could not be made with {ADDRESS}, {WRITE_TOKEN} and {CA}: {said(e)}"
    refuse(failure)


@pytest.fixture(scope="session", autouse=True)
def _tier() -> None:
    """Every test needs the reader's address and token; where the writer's token is set too, the session's start
    deletes what a stopped run left."""
    need(ADDRESS, TOKEN)
    if not os.environ.get(WRITE_TOKEN):
        return
    made = writer_of()
    swept: list[str] = []
    failure: str | None = None
    try:
        swept = made.sweep()
    except Exception as e:
        failure = f"the sweep of what a stopped run left failed: {said(e)}"
    finally:
        made.close()
    if failure is not None:
        refuse(failure)
    if swept:
        print(f"deleted what a stopped run left: {', '.join(swept)}")


@pytest.fixture(scope="session")
def conn() -> Iterator[Infrahub]:
    """The reader's connection, with the reader's token."""
    with reader() as made:
        yield made


@pytest.fixture(scope="session")
def writer() -> Iterator[Writer]:
    """The tier's own writer, with the admin's token; a test that writes skips without it."""
    need(WRITE_TOKEN)
    made = writer_of()
    try:
        yield made
    finally:
        made.close()


@pytest.fixture(scope="session")
def seed() -> dict[str, Any]:
    """`seed.json` as `make infrahub-seed` wrote it: its branch, its scope and its stages, each a label and a time."""
    need(SEED)
    found: dict[str, Any] = json.loads(Path(os.environ[SEED]).read_text())
    return found


@pytest.fixture(scope="session")
def document() -> ReaderDocument:
    """The seeded fixture network's reader document, `infrahub/seed/reader.yaml`."""
    return load_document(READER_DOCUMENT)
