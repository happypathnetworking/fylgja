"""The example's NetBox contract tier: the NetBox change source against the running development NetBox, through a core
of the tests' own on its fake runtime, and NetBox's own webhook starting the rehearsal on a Prefect server of the
tests' own (CONTRIBUTING.md, Test tiers; D-034, D-096, D-097).

Every test under tests/contract_netbox is marked `contract_netbox`: `make test` deselects them, and `make
contract-netbox` runs them with `local/.env` loaded, after `netbox/`'s tier and the NetBox reader's. The variables are
read inside the fixtures, never at import, since the pure tier collects this file too. Without them a test is skipped,
and fails where `CI` is set. The guard of the credentials is phase 8's tier's, taken from `contract/conftest.py`: each
token held as a `Secret`, and every report of a test here with each credential's value replaced by its name, the
NetBox tier's among `CREDENTIALS`, before pytest shows it, and NetBox's address by its variable's (`hidden`).

The source reads and writes with the example's account's token, `FYLGJA_ORCHESTRATOR_NETBOX_TOKEN`; the set-up's writes
are `netbox/seed/box.py`'s `Box`'s, loaded by its path, with the superuser's, `FYLGJA_NETBOX_WRITE_TOKEN`, which the
source and the runner are never given. A test's branch is `fylgja-contract-<8 hex>`, made from `main`, waited for until
`ready` and deleted whatever happened, its journal entries with it; the session's start deletes any such branch a
stopped run left. The branches' functions are the loaded module's (`branch_named`, `branched`); what the other tiers
add to them, which cannot be imported, is written again here and held by the pure tier's
`tests/test_contract_netbox_branches.py`: NetBox refuses 500 the `DELETE` of a branch still provisioning, so a branch
is waited for until it has left `new` and `provisioning` before it is deleted (design/verified-facts.md, "A branch
deleted before it is `ready`"). Whatever a test writes on `main` it removes in a `finally`.

The tag `TAG` is ensured before any test's branch is made, so that its row of `main`'s changelog never counts against
a branch, and left: it is the installed trigger's, with the event rule and the webhook `make netbox-hook` writes.
Setting it on a branch sends that webhook, to the edge's Prefect at port 4200 of the host where the trigger is
as installed: a test that sets it stops where anything listens there (`edge_port_free`), so that no rehearsal of the
edge's is started, and each sending that fails, there or at a receiver a test leaves unanswered, is a failed
background task of NetBox's, which the session's end deletes where the superuser's password is set (`Failed`).
"""

from __future__ import annotations

import contextlib
import importlib.util
import os
import re
import secrets
import subprocess
import sys
import time
from collections.abc import Callable, Generator, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any, NoReturn, Protocol, cast

import httpx
import pytest
from contract.conftest import Secret, hide, scrubbed
from contract.conftest import refuse as _refuse
from fylgja_core.client import InvalidAddress, base_url, trust
from fylgja_netbox import ReaderDocument
from fylgja_netbox.document import load as load_document
from harness import Served, serving

from fylgja_orchestrator.netbox import TAG, NetBoxSource

__all__ = ["Secret", "hide"]

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parents[2]
SEED = ROOT / "netbox" / "seed"
READER_DOCUMENT = SEED / "reader.yaml"
"""The reader document of the seeded fixture network."""

ADDRESS = "FYLGJA_NETBOX_ADDRESS"
WRITE_TOKEN = "FYLGJA_NETBOX_WRITE_TOKEN"
READER_TOKEN = "FYLGJA_NETBOX_TOKEN"
EXAMPLE_TOKEN = "FYLGJA_ORCHESTRATOR_NETBOX_TOKEN"
PASSWORD = "FYLGJA_NETBOX_SUPERUSER_PASSWORD"
CA = "FYLGJA_NETBOX_CA"

SCOPE = "tag:fylgja"
"""The scope the seed tags its three devices under, `netbox/seed/seed.py`'s `SCOPE`."""
SUPERUSER = "admin"
"""The superuser's login name, as `netbox/dev/compose.override.yml` makes it."""
EXAMPLE = "fylgja-orchestrator"
"""The example's account's login name, as `netbox/seed/account.py` makes it."""

PREFIX = "fylgja-contract-"
"""The name of every branch, and of every tag, event rule and webhook, the tier makes, before its eight hex digits."""

EDGE_PORT = 4200
"""The port the installed webhook reaches the edge's Prefect at (`netbox/seed/hook.py`'s `RECEIVER`)."""

TIMEOUT = httpx.Timeout(30.0, connect=5.0)


def loaded(name: str, path: Path, **aliases: ModuleType) -> ModuleType:
    """The module at `path`, loaded by its path as `name`: `netbox/seed/` is no package the example may import. Each of
    `aliases` stands, while it is loaded, for the module of that name its imports name."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    saved = {alias: sys.modules.get(alias) for alias in aliases}
    sys.modules.update(aliases)
    try:
        spec.loader.exec_module(module)
    finally:
        for alias, held in saved.items():
            if held is None:
                sys.modules.pop(alias, None)
            else:
                sys.modules[alias] = held
    return module


BOX = loaded("fylgja_orchestrator_contract_box", SEED / "box.py")
"""`netbox/seed/box.py`: the tests' own writes, and the branches' functions."""
CHANGE = loaded("fylgja_orchestrator_contract_change", SEED / "change.py", box=BOX)
"""`netbox/seed/change.py`: the seeded change's steps, which a test writes on its own branch."""
HOOK = loaded("fylgja_orchestrator_contract_hook", SEED / "hook.py", box=BOX)
"""`netbox/seed/hook.py`: the installed trigger's names and where its webhook sends."""

_CREATE = re.compile(r"/api/deployments/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}/create_flow_run")


def trigger_fault(webhook: Mapping[str, Any] | None) -> str | None:
    """Why the installed webhook, as NetBox answers it, is no trigger `make netbox-hook` installed, in one sentence
    naming the repair; None where it is one, or where none is installed. A run of the hook module killed before its
    end leaves the webhook naming the module's own Prefect, a port no one serves, so a module that took such a webhook
    for the state to write back would keep the trigger broken: the webhook must name `hook.py`'s `RECEIVER` and a
    deployment's `create_flow_run`."""
    if webhook is None:
        return None
    url = webhook.get("payload_url")
    try:
        parsed = httpx.URL(url) if isinstance(url, str) else None
    except httpx.InvalidURL:
        parsed = None
    if (parsed is not None and parsed.scheme == "http" and f"{parsed.host}:{parsed.port}" == HOOK.RECEIVER
            and _CREATE.fullmatch(parsed.path) and not parsed.query):
        return None
    return (f"the installed webhook {webhook.get('name')} does not send to {HOOK.RECEIVER}, as make netbox-hook "
            "installs it, so nothing was started: a run killed before its end may have left it so; run make "
            "netbox-hook, with the development Prefect up, and run again")

BRANCHES: str = BOX.BRANCHES
BRANCH_WAIT_S: float = BOX.BRANCH_WAIT_S
BoxError: type[Exception] = BOX.BoxError
TAGS = "extras/tags/"
ENTRIES = "extras/journal-entries/"
CHANGES = "core/object-changes/"


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
    `ready` 11.1 s after their request at the slowest, and two whose `DELETE` NetBox refused while they provisioned
    read `ready` at reads 26.7 s to 28.2 s after it. 120 s is about 4.3 times the slowest, 28.2 s, a derivation; the
    bound is the module's `BRANCH_WAIT_S`."""
    return cast(dict[str, Any], BOX.branched(box, name, timeout_s=BRANCH_WAIT_S, clock=CLOCK, sleep=SLEEP))


UNSETTLED = ("new", "provisioning")
"""The statuses of a branch whose `DELETE` the tier does not send until the branch has left them: NetBox refused 500
the `DELETE` of a branch provisioning, and the branch stayed (design/verified-facts.md, "A branch deleted before it is
`ready`"). A `DELETE` of a branch `new` was not read; it is waited on because it comes before provisioning."""

POLL_S = 1.0
"""Seconds between two reads of a branch the tier waits on, as `branched` reads one."""


def settled(box: Writes, row: Mapping[str, Any], *, leave: tuple[str, ...] = UNSETTLED) -> Mapping[str, Any] | None:
    """The branch `row`, one of the tier's, once NetBox holds it in no status of `leave`, read by its name every
    `POLL_S` (`branch_named`) and never made; None where it is gone. `BRANCH_WAIT_S` at most; one still in such a
    status then is a `BoxError` naming it and its status."""
    name, held = str(row["name"]), row
    started = CLOCK()
    while held["status"]["value"] in leave:
        waited = CLOCK() - started
        if waited >= BRANCH_WAIT_S:
            status = held["status"]["value"]
            raise BoxError(f"the branch {name} was still {status} {BRANCH_WAIT_S:g} s on")
        SLEEP(min(POLL_S, BRANCH_WAIT_S - waited))
        found = branch_named(box, name)
        if found is None:
            return None
        held = found
    return held


def _removed(box: Writes, row: Mapping[str, Any]) -> bool:
    """The branch `row`, one of the tier's, deleted once it has settled (`settled`), whatever status it then holds, and
    True; False where it is gone before, and nothing is sent. Where NetBox refuses the `DELETE`, the `BoxError` names
    the branch and its status."""
    held = settled(box, row)
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


def scratch_name() -> str:
    """A name of the tier's own: `PREFIX` and eight hex digits."""
    return PREFIX + secrets.token_hex(4)


def need(*names: str) -> None:
    """Skip, or fail where `CI` is set, naming each of `names` that is not set."""
    __tracebackhide__ = True
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        refuse(f"the example's NetBox contract tier needs {', '.join(missing)} set: load local/.env and run make "
               "contract-netbox")


def refuse(sentence: str) -> NoReturn:
    """End the test in `sentence`, with no traceback: a failure where `CI` is set, a skip elsewhere."""
    __tracebackhide__ = True
    _refuse(sentence)


def secret(name: str) -> Secret:
    """The variable `name` as a `Secret`; skipped, or failed where `CI` is set, where it is not set."""
    __tracebackhide__ = True
    need(name)
    return Secret(name, os.environ[name])


def ca() -> Path | None:
    """The CA file an `https://` address is verified against, where `FYLGJA_NETBOX_CA` names one."""
    named = os.environ.get(CA)
    return Path(named) if named else None


def edge_port_free() -> None:
    """Stop the test where anything listens on port 4200, by `ss -Hltn`: setting the tag would send the installed
    webhook there, and an edge's Prefect would rehearse the test's branch."""
    __tracebackhide__ = True
    listed = subprocess.run(["ss", "-Hltn"], capture_output=True, text=True, check=True, timeout=30).stdout
    held = [line.split()[3] for line in listed.splitlines() if len(line.split()) > 3
            and line.split()[3].rpartition(":")[2] == str(EDGE_PORT)]
    if held:
        pytest.fail(f"port {EDGE_PORT} is listened on ({', '.join(held)}): the installed webhook would start a "
                    "rehearsal there when the tag is set, so nothing was set; stop what listens there (make "
                    "prefect-down) and run again", pytrace=False)


def entries(box: Writes, branch: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The journal entries on `branch`, in the order written, as the source lists them."""
    return box.listed(ENTRIES, assigned_object_type="netbox_branching.branch", assigned_object_id=branch["id"],
                      ordering="created")


def tags_of(box: Writes, branch: Mapping[str, Any]) -> list[str]:
    """The slugs of `branch`'s tags, as it stands."""
    held = box.get(f"{BRANCHES}{branch['id']}/")
    return [tag["slug"] for tag in held.get("tags") or []]


def set_tags(box: Writes, branch: Mapping[str, Any], *slugs: str) -> None:
    """`branch`'s tags set to `slugs`, by the superuser, as `change.py --tag` sets `TAG`."""
    box.patch(f"{BRANCHES}{branch['id']}/", {"tags": [{"slug": slug} for slug in slugs]})


@contextmanager
def signed_in(address: str, password: Secret) -> Iterator[httpx.Client]:
    """A session of NetBox's pages, signed in as the superuser by its login form: `/login/`'s CSRF token sent back with
    the password, which NetBox answers with a redirect and a session cookie."""
    with httpx.Client(base_url=address.rstrip("/"), timeout=TIMEOUT, verify=trust(ca()), trust_env=False) as client:
        page = client.get("/login/")
        found = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page.text)
        assert page.status_code == 200 and found is not None, f"/login/ answered {page.status_code} with no form"
        answer = client.post("/login/", data={"username": SUPERUSER, "password": password.value,
                                              "csrfmiddlewaretoken": found[1], "next": "/"},
                             headers={"Referer": f"{address.rstrip('/')}/login/"})
        assert answer.status_code == 302 and "sessionid" in client.cookies, (
            f"/login/ as {SUPERUSER} answered {answer.status_code}")
        yield client


def in_turn(*steps: Callable[[], object]) -> None:
    """Each of `steps` run in its order, each whatever the one before it raised; the first failure raised then."""
    failures: list[BaseException] = []
    for each in steps:
        try:
            each()
        except Exception as e:  # each step runs; the first failure is raised once all have
            failures.append(e)
    if failures:
        raise failures[0]


QUEUES = 3
"""NetBox's background queues, `default`, `high` and `low`, each numbered in its pages."""
SENDING = "extras.webhooks.send_webhook"
"""The function a background task that sends a webhook runs."""
_TASK = re.compile(r"/core/background-tasks/([0-9a-f-]{36})/")


def failed_tasks(pages: httpx.Client) -> set[str]:
    """The ids of every failed background task NetBox's pages list, of each queue: the API's
    `core/background-tasks/` listed none, failed or not (design/verified-facts.md, "What the receiver answered is the
    task's, and not a job's"), and the pages listed each ("A failed sending of a webhook is listed on NetBox's pages
    and deleted through the API")."""
    found: set[str] = set()
    for queue in range(QUEUES):
        page = pages.get(f"/core/background-queues/{queue}/failed/")
        assert page.status_code == 200, f"the failed tasks of queue {queue} answered {page.status_code}"
        found |= set(_TASK.findall(page.text))
    return found


def _address_forms() -> list[str]:
    """NetBox's address in each form a row or an error may give it, the longest first."""
    address = os.environ.get(ADDRESS, "")
    forms = {address, address.rstrip("/")}
    with contextlib.suppress(InvalidAddress):
        forms.add(base_url(address))
    return sorted(filter(None, forms), key=len, reverse=True)


def hidden(text: str) -> str:
    """`text` with each credential's value replaced by its name (`contract/conftest.py`'s `scrubbed`), and NetBox's
    address by its variable's: every row NetBox answers holds it in its `url`."""
    text = scrubbed(text)
    for form in _address_forms():
        text = text.replace(form, f"<{ADDRESS}>")
    return text


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """Every report of a test of the tier's, its set-up and teardown too, `hidden` in its long representation and its
    captured sections before pytest shows either, as phase 8's tier's are scrubbed."""
    report = yield
    if report.longrepr is not None and not isinstance(report.longrepr, tuple):
        text = str(report.longrepr)
        if hidden(text) != text:
            report.longrepr = hidden(text)
    report.sections = [(title, hidden(content)) for title, content in report.sections]
    return report


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every test under tests/contract_netbox `contract_netbox`, before `-m` selects."""
    for item in items:
        if item.path.is_relative_to(_HERE):
            item.add_marker(pytest.mark.contract_netbox)


@pytest.fixture(scope="session")
def box() -> Iterator[Writes]:
    """The tests' own writer, `netbox/seed/box.py`'s `Box` with the superuser's token, which hides the other two
    tokens as its own."""
    need(ADDRESS, WRITE_TOKEN, EXAMPLE_TOKEN)
    made = writer(os.environ[ADDRESS], os.environ[WRITE_TOKEN])
    made.hide(os.environ[EXAMPLE_TOKEN], os.environ.get(READER_TOKEN, ""))
    try:
        yield made
    finally:
        made.close()


@pytest.fixture(scope="session", autouse=True)
def _tier(box: Writes) -> Iterator[None]:
    """The session's start deletes every branch of the tier's a stopped run left; its end reads that no branch of the
    tier's is left, and deletes each background task NetBox failed to send a webhook in since it began (`Failed`)."""
    swept = sweep(box)
    if swept:
        print(f"deleted what a stopped run left: {', '.join(swept)}")
    failed = Failed.begun()
    yield
    session_end(failed, box)


def session_end(failed: Failed, box: Writes) -> None:
    """The session's end, each step whatever the one before it raised (`in_turn`): the failed sendings deleted, then
    the branches read for any of the tier's left."""

    def no_branch_left() -> None:
        assert [row["name"] for row in box.listed(BRANCHES) if str(row["name"]).startswith(PREFIX)] == []

    in_turn(lambda: failed.ended(box), no_branch_left)


class Failed:
    """The background tasks of NetBox's that fail during the session: those its pages list as failed at the end and
    not at the start, deleted at the end where each is a webhook's sending created since the session began, by the
    task's own `created_at`, through the API by the superuser's token: every such sending, whoever set it off, the
    tier's settings of the tag and a person's or another run's alike, since a task names no one. A failed task of
    another function, or one created before the session began, is left. Without the superuser's password the pages
    are not read, and the end says so."""

    def __init__(self, before: set[str] | None, began: datetime) -> None:
        self.before = before
        self.began = began

    @classmethod
    def begun(cls) -> Failed:
        began = datetime.now(UTC)
        if not os.environ.get(PASSWORD):
            return cls(None, began)
        with signed_in(os.environ[ADDRESS], secret(PASSWORD)) as pages:
            return cls(failed_tasks(pages), began)

    def ours(self, task: Mapping[str, Any]) -> bool:
        """Whether the failed task `task`, as NetBox answers it, is a webhook's sending the session made."""
        created = task.get("created_at")
        return (task.get("func_name") == SENDING and isinstance(created, str)
                and datetime.fromisoformat(created) >= self.began)

    def ended(self, box: Writes) -> None:
        if self.before is None:
            print(f"{PASSWORD} is not set: a failed sending of a webhook the session made is left in NetBox")
            return
        with signed_in(os.environ[ADDRESS], secret(PASSWORD)) as pages:
            new = failed_tasks(pages) - self.before
        deleted = 0
        for task in sorted(new):
            if self.ours(box.get(f"core/background-tasks/{task}/")):
                box.post(f"core/background-tasks/{task}/delete/", {})
                deleted += 1
        print(f"deleted {deleted} failed sending{'' if deleted == 1 else 's'} of a webhook, of {len(new)} failed "
              "tasks the session saw")


@pytest.fixture(scope="session")
def tag(box: Writes) -> dict[str, Any]:
    """The tag `TAG`, limited to branches as `netbox/seed/hook.py` makes it: found, or made where it is not; left."""
    return box.ensure(TAGS, {"slug": TAG}, {"name": TAG, "slug": TAG, "object_types": ["netbox_branching.branch"]})


@pytest.fixture
def branch(box: Writes, tag: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """A branch of the test's own, `fylgja-contract-<8 hex>`, `ready`, as NetBox answers it; made once `TAG` stands,
    and deleted whatever the test did, its journal entries with it."""
    with scratch(box, scratch_name()) as made:
        yield made


@pytest.fixture(scope="module")
def core(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Served]:
    """API 1 on the fake runtime (`harness.serving`), the module's one core: the marks are given to it, and the runner
    is served its address."""
    with serving(tmp_path_factory.mktemp("core")) as served:
        yield served


@pytest.fixture(scope="session")
def document() -> ReaderDocument:
    """The seeded fixture network's reader document, `netbox/seed/reader.yaml`."""
    return load_document(READER_DOCUMENT)


@pytest.fixture(scope="session")
def example_token() -> Secret:
    """The example's account's token, which the source and the runner read and write with."""
    return secret(EXAMPLE_TOKEN)


@pytest.fixture(scope="session")
def example_user(box: Writes) -> int:
    """The example's account's user id, which a journal entry it writes holds as `created_by`."""
    [user] = box.listed("users/users/", username=EXAMPLE)
    return int(user["id"])


@pytest.fixture
def source(core: Served, document: ReaderDocument, example_token: Secret) -> Iterator[NetBoxSource]:
    """The NetBox change source with the example's token, the module's core keeping its marks' blueprints."""
    made = NetBoxSource(os.environ[ADDRESS], example_token.value, document, core.client, ca=ca())
    try:
        yield made
    finally:
        made.close()


@contextmanager
def on_main(box: Writes, path: str, body: Mapping[str, object]) -> Iterator[dict[str, Any]]:
    """An object of `path` made on `main` by the superuser of `body`, and deleted on leaving, whatever happened."""
    made: dict[str, Any] = box.post(path, dict(body))
    try:
        yield made
    finally:
        with contextlib.suppress(BoxError):
            box.delete(f"{path}{made['id']}/")
        assert box.one(path, id=made["id"]) is None, f"{path}{made['id']} is still on main"
