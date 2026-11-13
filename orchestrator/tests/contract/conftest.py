"""The example's contract tier: the change source against the seeded development Infrahub, and the two deployments on
a Prefect server of the tests' own (CONTRIBUTING.md, Test tiers; D-034, D-083).

Every test under tests/contract is marked `contract`: `make test` deselects them, and `make contract` runs them with
`local/.env` loaded and `FYLGJA_INFRAHUB_SEED` set on its command line, the path of the main checkout's `seed.json`. The
variables are read inside the fixtures, never at import, since the pure tier collects this file too. Without them a
test is skipped, and fails where `CI` is set. No value of them is printed, and none is put in an assertion's message:
a test compares outside the assert. Each token is held as a `Secret`, whose value no `repr`, `str` or traceback shows,
and read by `.value` only where a request or a process's environment is built; beneath that, every report of a test
here has each credential's value replaced by its name before pytest shows it (P5-60), since a long traceback shows
every frame's arguments, the source's and the reader's among them.

The set-up's writes are the writer's, `FYLGJA_INFRAHUB_WRITE_TOKEN`, the admin's, which the source and the runner are
never given; the source reads and posts with the example's account's token, `FYLGJA_ORCHESTRATOR_INFRAHUB_TOKEN`. A
module's proposed changes, made on the seed's branch, are deleted at its end, and none is open after: a seed without
`PROPOSED_CHANGE=1` leaves none open (P5-24), which the start of each module reads too. A proposed change starts
Infrahub's own checks, which reach the edge's Prefect at port 4200 of the host: a module that makes one stops where
anything listens there (P5-24), so that they conclude "cannot be reached" and start nothing.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import time
from collections.abc import Generator, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, NoReturn

import httpx
import pytest
from fylgja_core.client import base_url, trust
from fylgja_infrahub import ReaderDocument
from fylgja_infrahub.document import load as load_document
from fylgja_infrahub.transport import KEEPALIVE_S

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parents[2]
READER_DOCUMENT = ROOT / "infrahub" / "seed" / "reader.yaml"
"""The reader document of the seeded fixture network."""

ADDRESS = "FYLGJA_INFRAHUB_ADDRESS"
TOKEN = "FYLGJA_INFRAHUB_TOKEN"
WRITE_TOKEN = "FYLGJA_INFRAHUB_WRITE_TOKEN"
EXAMPLE_TOKEN = "FYLGJA_ORCHESTRATOR_INFRAHUB_TOKEN"
CA = "FYLGJA_INFRAHUB_CA"
SEED = "FYLGJA_INFRAHUB_SEED"

EDGE_PORT = 4200
"""The port the task workers reach the edge's Prefect at (`infrahub/dev/compose.override.yml`)."""

TIMEOUT = httpx.Timeout(60.0, connect=5.0)
VALIDATION_S = 300.0
"""How long a set-up waits for a proposed change's artifact validation to complete: it was first read complete 45.7 s
after the create on a quiet instance, and passed 94.6 s after the create of one queued behind another's (a derivation;
design/verified-facts.md, "Infrahub 1.11.11")."""

OPEN_READ = (
    'query ($branch: String!) { CoreProposedChange(source_branch__value: $branch, state__value: "open") '
    "{ count edges { node { id name { value } } } } }"
)
PROPOSED_CREATE = (
    "mutation ($name: String!, $branch: String!, $draft: Boolean!) { CoreProposedChangeCreate(data: {name: {value: "
    '$name}, source_branch: {value: $branch}, destination_branch: {value: "main"}, is_draft: {value: $draft}}) '
    "{ ok object { id } } }"
)
PROPOSED_UPDATE = (
    "mutation ($id: String!, $draft: Boolean!) { CoreProposedChangeUpdate(data: {id: $id, is_draft: {value: $draft}}) "
    "{ ok } }"
)
PROPOSED_DELETE = "mutation ($id: String!) { CoreProposedChangeDelete(data: {id: $id}) { ok } }"
VALIDATORS = (
    "query ($id: ID!) { CoreArtifactValidator(proposed_change__ids: [$id]) { count edges { node { id state { value } "
    "conclusion { value } started_at { value } completed_at { value } } } } }"
)
THREADS = (
    "query ($id: ID!) { CoreChangeThread(change__ids: [$id]) { count edges { node { id label { value } } } } }"
)
COMMENTS = (
    "query ($id: ID!) { CoreThreadComment(thread__ids: [$id]) { count edges { node { text { value } } "
    "node_metadata { created_at created_by { id } } } } }"
)


@dataclass(frozen=True)
class Secret:
    """A credential of the tier's: the name it is known by, and its value, which no `repr`, `str` or traceback of
    pytest's shows. `.value` is read only where a request or a process's environment is built."""

    name: str
    value: str = field(repr=False)

    def __str__(self) -> str:
        return f"<{self.name}>"

    def __repr__(self) -> str:
        return f"Secret({self.name})"


HIDDEN: dict[str, str] = {}
"""Each credential a test made itself, by its name, whose value a report of the tier's has replaced (`hide`)."""

CREDENTIALS = (
    TOKEN,
    WRITE_TOKEN,
    EXAMPLE_TOKEN,
    "FYLGJA_NETBOX_TOKEN",
    "FYLGJA_NETBOX_WRITE_TOKEN",
    "FYLGJA_ORCHESTRATOR_NETBOX_TOKEN",
    "FYLGJA_NETBOX_SUPERUSER_PASSWORD",
)
"""The variables whose values a report of the tier's has replaced, read when a report is made: Infrahub's three, and
every NetBox credential `tests/contract_netbox/` reads, whose conftest takes this guard, the superuser's password among
them."""


def hide(secret: Secret) -> Secret:
    """`secret`, its value replaced by its name in every report of the tier's from now on."""
    HIDDEN[secret.name] = secret.value
    return secret


def secret(name: str) -> Secret:
    """The variable `name` as a `Secret`; skipped, or failed where `CI` is set, where it is not set."""
    __tracebackhide__ = True
    need(name)
    return Secret(name, os.environ[name])


def scrubbed(text: str) -> str:
    """`text` with each credential's value replaced by its name, the longest first."""
    held = {name: os.environ.get(name, "") for name in CREDENTIALS} | HIDDEN
    for name, value in sorted(held.items(), key=lambda pair: len(pair[1]), reverse=True):
        if value:
            text = text.replace(value, f"<{name}>")
    return text


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(
    item: pytest.Item, call: pytest.CallInfo[None]
) -> Generator[None, pytest.TestReport, pytest.TestReport]:
    """Every report of a test of the tier's, its set-up and teardown too, with each credential's value replaced by
    its name in its long representation and its captured sections, before pytest shows either."""
    report = yield
    if report.longrepr is not None and not isinstance(report.longrepr, tuple):
        text = str(report.longrepr)
        if scrubbed(text) != text:
            report.longrepr = scrubbed(text)
    report.sections = [(title, scrubbed(content)) for title, content in report.sections]
    return report


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every test under tests/contract `contract`, before `-m` selects."""
    for item in items:
        if item.path.is_relative_to(_HERE):
            item.add_marker(pytest.mark.contract)


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


def ca() -> Path | None:
    """The CA file an `https://` address is verified against, where `FYLGJA_INFRAHUB_CA` names one."""
    named = os.environ.get(CA)
    return Path(named) if named else None


def edge_port_free() -> None:
    """Stop the test where anything listens on port 4200, by `ss -Hltn`: Infrahub's checks of a proposed change made
    here would reach it with the task workers' credential (P5-24)."""
    __tracebackhide__ = True
    listed = subprocess.run(["ss", "-Hltn"], capture_output=True, text=True, check=True, timeout=30).stdout
    held = [line.split()[3] for line in listed.splitlines() if len(line.split()) > 3
            and line.split()[3].rpartition(":")[2] == str(EDGE_PORT)]
    if held:
        pytest.fail(f"port {EDGE_PORT} is listened on ({', '.join(held)}): the checks of a proposed change made here "
                    "would reach it, so nothing was made; stop what listens there (make prefect-down) and run again",
                    pytrace=False)


class WriterError(Exception):
    """A write or read of the set-up's refused, in one sentence that holds no token."""


class Writer:
    """The set-up's own reach into Infrahub, with the admin's token: GraphQL on `main`, and nothing else."""

    def __init__(self, address: str, token: Secret) -> None:
        self._token = token
        # An idle connection kept no longer than the reader keeps one: on one kept 2.0 s idle, a request was refused.
        self._http = httpx.Client(base_url=base_url(address), headers={"X-INFRAHUB-KEY": token.value},
                                  timeout=TIMEOUT,
                                  verify=trust(ca()), limits=httpx.Limits(keepalive_expiry=KEEPALIVE_S),
                                  trust_env=False)

    def __repr__(self) -> str:
        return "Writer()"

    def close(self) -> None:
        self._http.close()

    def gql(self, query: str, variables: Mapping[str, object] | None = None, *, token: Secret | None = None
            ) -> dict[str, Any]:
        """The answer's `data` to `query` on `main`, with the admin's token or `token`; a `WriterError` naming the
        errors' messages and `http_status` where it holds any."""
        answer, status = self.ask(query, variables, token=token)
        errors = answer.get("errors") if isinstance(answer, dict) else None
        if status != 200 or errors:
            raise WriterError(f"HTTP {status}: {self._hidden(errors or answer)}")
        data = answer.get("data") if isinstance(answer, dict) else None
        if not isinstance(data, dict):
            raise WriterError(f"HTTP {status}: no data")
        return data

    def ask(self, query: str, variables: Mapping[str, object] | None = None, *, token: Secret | None = None
            ) -> tuple[Any, int]:
        """The whole answer to `query` on `main` and its HTTP status, errors and all, with the admin's token or
        `token`."""
        headers = {"X-INFRAHUB-KEY": token.value} if token is not None else None
        try:
            response = self._http.post("/graphql/main", json={"query": query, "variables": dict(variables or {})},
                                       headers=headers)
        except httpx.HTTPError as e:
            failure = WriterError(f"Infrahub was not reached: {type(e).__name__}")
        else:
            try:
                return response.json(), response.status_code
            except ValueError:
                return None, response.status_code
        raise failure

    def _hidden(self, said: object) -> str:
        return str(said).replace(self._token.value, "<redacted>")[:500]

    def open_changes(self, branch: str) -> list[str]:
        """The ids of the open proposed changes of `branch`."""
        page = self.gql(OPEN_READ, {"branch": branch})["CoreProposedChange"]
        return [edge["node"]["id"] for edge in page["edges"]]

    def validators(self, change: str) -> list[dict[str, Any]]:
        """The artifact validators of the proposed change `change`, each its state and its two times."""
        page = self.gql(VALIDATORS, {"id": change})["CoreArtifactValidator"]
        return [
            {key: edge["node"][key]["value"] for key in ("state", "conclusion", "started_at", "completed_at")}
            for edge in page["edges"]
        ]

    def threads(self, change: str) -> list[str]:
        """The ids of the proposed change's threads."""
        return [edge["node"]["id"] for edge in self.gql(THREADS, {"id": change})["CoreChangeThread"]["edges"]]

    def comments(self, thread: str) -> list[tuple[str, str, str]]:
        """The thread's comments in the order written: each its text, its `created_at` and its author's id."""
        edges = self.gql(COMMENTS, {"id": thread})["CoreThreadComment"]["edges"]
        found = [(edge["node"]["text"]["value"], edge["node_metadata"]["created_at"],
                  edge["node_metadata"]["created_by"]["id"]) for edge in edges]
        return sorted(found, key=lambda comment: comment[1])


@dataclass(frozen=True)
class Proposal:
    """A proposed change of the seed's branch a module made: its id, its name, and the time its create was answered,
    by the test process's monotonic clock."""

    id: str
    name: str
    made: float


@dataclass
class Proposals:
    """The proposed changes a module makes on `branch` with the writer, each deleted at the module's end."""

    writer: Writer
    branch: str
    made: list[str] = field(default_factory=list)

    def make(self, *, draft: bool) -> Proposal:
        name = f"Rehearse {self.branch} (contract {secrets.token_hex(4)})"
        answer = self.writer.gql(PROPOSED_CREATE, {"name": name, "branch": self.branch, "draft": draft})
        made = answer["CoreProposedChangeCreate"]
        if not (isinstance(made, dict) and made.get("ok") is True):
            raise WriterError(f"CoreProposedChangeCreate of {self.branch} answered no ok")
        proposal = Proposal(str(made["object"]["id"]), name, time.monotonic())
        self.made.append(proposal.id)
        return proposal

    def set_draft(self, change: str, draft: bool) -> None:
        answer = self.writer.gql(PROPOSED_UPDATE, {"id": change, "draft": draft})["CoreProposedChangeUpdate"]
        if not (isinstance(answer, dict) and answer.get("ok") is True):
            raise WriterError(f"CoreProposedChangeUpdate of {change} answered no ok")

    def delete(self, change: str) -> None:
        answer = self.writer.gql(PROPOSED_DELETE, {"id": change})["CoreProposedChangeDelete"]
        if not (isinstance(answer, dict) and answer.get("ok") is True):
            raise WriterError(f"CoreProposedChangeDelete of {change} answered no ok")
        self.made.remove(change)

    def validated(self, change: str, *, timeout_s: float = VALIDATION_S) -> dict[str, Any]:
        """The proposed change's one artifact validator once it reads `completed`, polled every 2 s."""
        began = time.monotonic()
        while True:
            rows = self.writer.validators(change)
            if rows and all(row["state"] == "completed" and row["completed_at"] for row in rows):
                [row] = rows
                return row
            if time.monotonic() - began > timeout_s:
                raise WriterError(f"the artifact validation of {change} had not completed {timeout_s:g} s on: {rows}")
            time.sleep(2.0)


@pytest.fixture(scope="session")
def seed() -> dict[str, Any]:
    """`seed.json` as `make infrahub-seed` wrote it: its branch, its scope, its stages and marks, and its proposed
    change, null for a seed without `PROPOSED_CHANGE=1`."""
    need(SEED)
    found: dict[str, Any] = json.loads(Path(os.environ[SEED]).read_text())
    return found


@pytest.fixture(scope="session")
def writer() -> Iterator[Writer]:
    """The set-up's writer, with the admin's token."""
    need(ADDRESS)
    made = Writer(os.environ[ADDRESS], secret(WRITE_TOKEN))
    try:
        yield made
    finally:
        made.close()


@pytest.fixture(scope="session")
def document() -> ReaderDocument:
    """The seeded fixture network's reader document, `infrahub/seed/reader.yaml`."""
    return load_document(READER_DOCUMENT)


@pytest.fixture(scope="session")
def example_token() -> Secret:
    """The example's account's token, which the source and the runner read and post with."""
    return secret(EXAMPLE_TOKEN)


@pytest.fixture(scope="module")
def proposals(writer: Writer, seed: dict[str, Any]) -> Iterator[Proposals]:
    """The module's proposed changes of the seed's branch, none open at its start, as a seed without the flag leaves
    the branch, and each deleted at its end, none open after."""
    edge_port_free()
    branch = seed["branch"]
    if seed.get("proposed_change") is not None:
        refuse(f"seed.json names a proposed change of {branch}: run make infrahub-seed without PROPOSED_CHANGE=1")
    held = writer.open_changes(branch)
    assert held == [], f"a proposed change of {branch} is open before the module: run make infrahub-seed"
    made = Proposals(writer, branch)
    try:
        yield made
    finally:
        for change in list(made.made):
            made.delete(change)
        left = writer.open_changes(branch)
        assert left == [], f"a proposed change of {branch} is open after the module"
