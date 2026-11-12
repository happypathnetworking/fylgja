"""The glue of the checks `fylgja-step` and `fylgja-twin` (D-085, D-088), on Infrahub's task worker with the standard
library and httpx alone: it finds the open proposed change of the branch a check runs on, starts a deployment of the
edge's Prefect over HTTP, waits for its run, asks it to cancel at the check's own deadline, reads the document the run
filed and concludes from that document's `status` alone. It decides nothing of the rehearsal's and writes nothing to
Infrahub: the flow posts the report (D-087).

It holds no token of the core's or of Infrahub's. The task worker gives it two variables, `FYLGJA_ORCHESTRATOR_ADDRESS`,
the edge's Prefect as a host and a port with no scheme (`host.docker.internal:4200` on the development host), and
`FYLGJA_ORCHESTRATOR_AUTH`, that Prefect's basic auth as `user:password`; the proposed change is read through the
check's own client of Infrahub, the `ask` a check hands in. No message names the auth, and of the two variables only
the address, which a fault names as the Prefect it tried. Prefect's own client is never used: the worker's Prefect
environment is Infrahub's own (design/verified-facts.md, "Infrahub 1.11.11", "A check's runtime").

Infrahub cuts a check at its `timeout` with no message of its own (its validator ends `failure`, "A timed-out check
ends its validator"), so a check keeps a deadline of its own before it: its `timeout` less `DEADLINE_MARGIN_S`, above
its flow's `timeout_seconds`. Past it the run is asked to cancel, and the check waits on until its `timeout` less
`CLOSE_MARGIN_S`, Prefect's 30 s of clean-up and the 3.2 s to `CANCELLED` within it ("Prefect 3.9.2", "A cancel over
HTTP"), and concludes in what is left. A `BaseException` in the check while its run has not ended, Infrahub's own cut
among them, asks the cancel with a blocking request, never an `await`, and is raised again.

A proposed change runs the check code its source branch was made with ("A branch keeps the registration's commit it
was made with"): a branch made before an import of this file runs the file as it was.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

ENV_ADDRESS = "FYLGJA_ORCHESTRATOR_ADDRESS"
ENV_AUTH = "FYLGJA_ORCHESTRATOR_AUTH"

STEP_FLOW = "stage-plan"
TWIN_FLOW = "twin-rehearse"
DEPLOYMENT = "main"
"""The edge's two flows, each served as `<flow>/main` (`fylgja_orchestrator.edge.flows`, compared there by value)."""
ARTIFACT_TYPE = "fylgja-document"
"""The type of the artifact a flow files its document as."""

STEP_TIMEOUT_S = 900
TWIN_TIMEOUT_S = 4260
"""Each check's `timeout`, which Infrahub cuts it at."""
DEADLINE_MARGIN_S = 240
"""A check's own deadline is its `timeout` less this: 660 s and 4020 s after it began, above its flow's
`timeout_seconds` (600 s and 3900 s) by 60 s and 120 s, which cover the 14.3 s a run was read to take to start and one
503 asked again."""
CLOSE_MARGIN_S = 120
"""After its cancel a check waits on until its `timeout` less this, and concludes in what is left."""
POLL_S = 5.0
RETRY_503_S = 5.0
"""A 503 to the deployment's read, to the run's start or to the read of its document is asked once more after this, and
a second is a fault; creates sent at once were read to answer 503 ("Prefect 3.9.2", "Creates sent at once answer
503"). A poll of the run's state is not asked again so: the next poll asks."""
REQUEST_TIMEOUT = httpx.Timeout(30.0, connect=5.0)
CANCEL_TIMEOUT = httpx.Timeout(10.0)
"""The blocking cancel's bound: 10 s for each phase of its one request, as httpx's `Timeout` bounds them (to connect,
to write, to read and to take a connection from the pool), not for the request whole."""
STATE_MESSAGE_LIMIT = 500
"""The characters of a run's state message a conclusion quotes, at most."""

ENDED = frozenset({"COMPLETED", "FAILED", "CANCELLED", "CRASHED"})
"""The state types a run ends in."""

UNREAD = "UNREAD"
"""The state type of a run whose state no read has answered yet."""

PROPOSED_CHANGE = """
query FylgjaProposedChange($branch: String!) {
  CoreProposedChange(source_branch__value: $branch, state__value: "open") {
    count
    edges { node { id name { value } is_draft { value } } }
  }
}
"""
"""The open proposed changes whose source branch is the one asked, read on `main`."""

THREAD = "The report is in this proposed change's thread."

Ask = Callable[[str, Mapping[str, Any]], Awaitable[Mapping[str, Any]]]
"""The check's own client of Infrahub: a query and its variables, answered on `main` (`self.client.execute_graphql`)."""


class Fault(Exception):
    """What stops a check before it concludes from a document: its message is the check's, naming the address where
    Prefect is the cause, never the auth."""


@dataclass(frozen=True)
class Found:
    """The open proposed change of a branch."""

    id: str
    name: str
    draft: bool


@dataclass(frozen=True)
class Outcome:
    """A check's conclusion: whether it passed, and its message."""

    passed: bool
    message: str


@dataclass(frozen=True)
class State:
    """A flow run's state as Prefect answers it: its type (`RUNNING`, `CANCELLED`, ...), its name (`TimedOut` for a
    run past its time limit) and its message."""

    type: str
    name: str
    message: str


async def find(ask: Ask, branch: str) -> Found | None:
    """The open proposed change whose source branch is `branch`; None where there is none, and a `Fault` naming each
    where there are more, which Infrahub refuses to make and no check picks among."""
    try:
        answer = await ask(PROPOSED_CHANGE, {"branch": branch})
    except Exception as error:
        raise Fault(
            f"the open proposed change of branch {branch} could not be read: {type(error).__name__}: {error}"
        ) from None
    root = answer.get("CoreProposedChange") if isinstance(answer, Mapping) else None
    edges = root.get("edges") if isinstance(root, Mapping) else None
    if not isinstance(edges, list):
        raise Fault(f"Infrahub answered the open proposed changes of branch {branch} with no edges")
    found: list[Found] = []
    for edge in edges:
        node = edge.get("node") if isinstance(edge, Mapping) else None
        node = node if isinstance(node, Mapping) else {}
        ident, name, draft = node.get("id"), _value(node, "name"), _value(node, "is_draft")
        if not isinstance(ident, str) or not isinstance(name, str) or not isinstance(draft, bool):
            raise Fault(f"Infrahub answered the open proposed changes of branch {branch} with no id, name or is_draft")
        found.append(Found(ident, name, draft))
    if len(found) > 1:
        named = " and ".join(f'"{change.name}" ({change.id})' for change in found)
        raise Fault(
            f"{len(found)} open proposed changes have source branch {branch}, {named}: nothing was started; close all "
            "but one"
        )
    return found[0] if found else None


def _value(node: Mapping[str, Any], name: str) -> Any:
    held = node.get(name)
    return held.get("value") if isinstance(held, Mapping) else None


class Prefect:
    """The edge's Prefect at `address`, asked over HTTP with basic auth `auth`, every request bounded, with no proxy of
    the environment's and no redirect followed. Each method is a coroutine but `cancel`, which blocks, for a check that
    is being cut short may await nothing more. `sleep` and `clock` are for tests."""

    def __init__(
        self,
        address: str,
        auth: tuple[str, str],
        *,
        transport: httpx.MockTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.address = address
        self.base = f"http://{address}/api"
        self._auth = httpx.BasicAuth(*auth)
        self._transport = transport
        self._sleep = sleep
        self._clock = clock
        self._client = httpx.AsyncClient(
            base_url=self.base, auth=self._auth, timeout=REQUEST_TIMEOUT, trust_env=False, transport=transport
        )
        self.unread: str | None = None
        """Why the last read of a run's state failed, where it did; None once one is answered."""

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> Prefect:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def start(self, flow: str, parameters: Mapping[str, Any]) -> str:
        """The id of a run of `<flow>/main` started with `parameters`."""
        deployment = await self._ask(
            "GET",
            f"/deployments/name/{flow}/{DEPLOYMENT}",
            f"the read of the deployment {flow}/{DEPLOYMENT}",
            missing=f"serves no deployment {flow}/{DEPLOYMENT}: make orchestrator-serve starts its runner",
            busy=": nothing was started",
        )
        created = await self._ask(
            "POST",
            f"/deployments/{_id(deployment, self, 'the deployment')}/create_flow_run",
            f"the start of a run of {flow}/{DEPLOYMENT}",
            body={"parameters": dict(parameters)},
            busy=": no run was read as started",
        )
        return _id(created, self, "the run it started")

    async def wait(self, run_id: str, until: float) -> State:
        """The state of the run `run_id`, read every `POLL_S` until it has ended or the clock reaches `until`, whichever
        is first: no read is sent at or after `until`. A read that fails is asked again at the next poll, and the last
        state answered is the one returned."""
        state = State(UNREAD, "", "")
        while True:
            try:
                answer = await self._ask("GET", f"/flow_runs/{run_id}", f"the read of flow run {run_id}", retry=False)
                state = _state(answer)
                self.unread = None
            except Fault as fault:
                self.unread = str(fault)
            if state.type in ENDED:
                return state
            left = until - self._clock()
            if left <= 0:
                return state
            await self._sleep(min(POLL_S, left))
            if self._clock() >= until:
                return state

    def cancel(self, run_id: str) -> str | int | None:
        """Asks the run `run_id` to cancel, blocking, bounded by `CANCEL_TIMEOUT`. Where Prefect accepts the ask (200 or
        201), its answer's status (`ACCEPT` for a running run, `REJECT` for a scheduled one, cancelled at once, `ABORT`
        for one already ended; empty where it gives none); where it answers any other HTTP status, that status; and
        None where the ask was not answered. No `force`, which would move a run that has just ended out of its end."""
        try:
            with httpx.Client(
                base_url=self.base, auth=self._auth, timeout=CANCEL_TIMEOUT, trust_env=False, transport=self._transport
            ) as client:
                response = client.post(f"/flow_runs/{run_id}/set_state", json={"state": {"type": "CANCELLING"}})
        except httpx.HTTPError:
            return None
        if response.status_code not in (200, 201):
            return response.status_code
        try:
            answer = response.json()
        except ValueError:
            return ""
        status = answer.get("status") if isinstance(answer, dict) else None
        return status if isinstance(status, str) else ""

    async def document(self, run_id: str) -> dict[str, Any] | None:
        """The document the run `run_id` filed, parsed from its artifact's JSON string; None where it filed none."""
        what = f"the read of flow run {run_id}'s document"
        found = await self._ask(
            "POST",
            "/artifacts/filter",
            what,
            body={
                "artifacts": {"flow_run_id": {"any_": [run_id]}, "type": {"any_": [ARTIFACT_TYPE]}},
                "sort": "CREATED_DESC",
                "limit": 1,
            },
        )
        if not isinstance(found, list):
            raise Fault(f"Prefect at {self.address} answered {what} with no list of artifacts")
        if not found:
            return None
        data = found[0].get("data") if isinstance(found[0], dict) else None
        try:
            document = json.loads(data) if isinstance(data, str) else data
        except ValueError:
            document = None
        if not isinstance(document, dict):
            raise Fault(f"Prefect at {self.address} answered {what} with an artifact whose data is no JSON object")
        return document

    async def _ask(
        self,
        method: str,
        path: str,
        what: str,
        *,
        body: Any = None,
        missing: str | None = None,
        busy: str = "",
        retry: bool = True,
    ) -> Any:
        """The JSON answer to one request, asked once more `RETRY_503_S` after a 503 where `retry`, a second 503 a
        `Fault` ending in `busy`; any other answer but a 2xx is a `Fault` naming the address, a 404 saying `missing`
        where it is given."""
        response = await self._send(method, path, what, body)
        if response.status_code == 503 and retry:
            await self._sleep(RETRY_503_S)
            response = await self._send(method, path, what, body)
            if response.status_code == 503:
                raise Fault(f"Prefect at {self.address} answered 503 twice to {what}{busy}")
        if response.status_code == 401:
            raise Fault(f"Prefect at {self.address} refused this check's credential ({ENV_AUTH})")
        if response.status_code == 404 and missing is not None:
            raise Fault(f"Prefect at {self.address} {missing}")
        if not 200 <= response.status_code < 300:
            raise Fault(f"Prefect at {self.address} answered HTTP {response.status_code} to {what}")
        try:
            return response.json()
        except ValueError:
            raise Fault(f"Prefect at {self.address} answered {what} with no JSON") from None

    async def _send(self, method: str, path: str, what: str, body: Any) -> httpx.Response:
        try:
            return await self._client.request(method, path, json=body)
        except httpx.HTTPError as error:
            raise Fault(
                f"Prefect at {self.address} could not be reached for {what}: {type(error).__name__}: {error}"
            ) from None


def _id(answer: Any, prefect: Prefect, what: str) -> str:
    ident = answer.get("id") if isinstance(answer, dict) else None
    if not isinstance(ident, str) or not ident:
        raise Fault(f"Prefect at {prefect.address} answered {what} with no id")
    return ident


def _state(answer: Any) -> State:
    held = answer.get("state") if isinstance(answer, dict) else None
    held = held if isinstance(held, dict) else {}
    kind, name, message = (held.get(key) for key in ("type", "name", "message"))
    return State(kind if isinstance(kind, str) else UNREAD, name or "", message or "")


@dataclass(frozen=True)
class _Check:
    """What tells the two checks apart: the flow each starts, its document's version member and passing status, and
    the words of its conclusions where the run filed no document."""

    flow: str
    version: str
    passing: str
    skips_draft: bool
    thread: bool
    what: str
    stopped: str
    goes_on: str


_STEP = _Check(
    flow=STEP_FLOW,
    version="plan_version",
    passing="planned",
    skips_draft=False,
    thread=False,
    what="the stage plan",
    stopped="; re-run the checks to plan again",
    goes_on="; it goes on",
)
_TWIN = _Check(
    flow=TWIN_FLOW,
    version="rehearsal_version",
    passing="passed",
    skips_draft=True,
    thread=True,
    what="the rehearsal",
    stopped=", and its twin's deletion was asked; re-run the checks to rehearse again",
    goes_on="; it goes on, and fylgja-core twin list shows a twin it leaves",
)


async def step(
    ask: Ask,
    branch: str,
    *,
    timeout: int,
    environ: Mapping[str, str] = os.environ,
    transport: httpx.MockTransport | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Outcome:
    """`fylgja-step`: the plan of the proposed change whose source branch is `branch`, draft or not, by a run of
    `stage-plan/main`; passed exactly when its plan 1 document's status is `planned`."""
    return await _checked(_STEP, ask, branch, timeout, environ, transport, sleep, clock)


async def twin(
    ask: Ask,
    branch: str,
    *,
    timeout: int,
    environ: Mapping[str, str] = os.environ,
    transport: httpx.MockTransport | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Outcome:
    """`fylgja-twin`: the rehearsal of the proposed change whose source branch is `branch` by a run of
    `twin-rehearse/main`; passed exactly when its rehearsal 1 document's status is `passed`. A draft passes having read
    neither variable and started nothing."""
    return await _checked(_TWIN, ask, branch, timeout, environ, transport, sleep, clock)


async def _checked(
    check: _Check,
    ask: Ask,
    branch: str,
    timeout: int,
    environ: Mapping[str, str],
    transport: httpx.MockTransport | None,
    sleep: Callable[[float], Awaitable[None]],
    clock: Callable[[], float],
) -> Outcome:
    began = clock()
    try:
        change = await find(ask, branch)
        if change is None:
            return Outcome(False, f"no open proposed change has source branch {branch}: nothing was started")
        if check.skips_draft and change.draft:
            return Outcome(
                True,
                f'not rehearsed: proposed change "{change.name}" is a draft. To rehearse it, mark it ready for review '
                "and re-run its checks; leaving draft starts nothing by itself.",
            )
        address, auth = _variables(environ)
    except Fault as fault:
        return Outcome(False, str(fault))
    async with Prefect(address, auth, transport=transport, sleep=sleep, clock=clock) as prefect:
        try:
            run_id = await prefect.start(check.flow, {"branch": branch})
        except Fault as fault:
            return Outcome(False, str(fault))
        return await _followed(check, prefect, run_id, timeout, began)


async def _followed(check: _Check, prefect: Prefect, run_id: str, timeout: int, began: float) -> Outcome:
    """The conclusion of the run `run_id`: waited for to the check's own deadline, asked to cancel there, waited for
    to the close, and concluded from its document, or from its state where it filed none."""
    state: State | None = None
    try:
        state = await prefect.wait(run_id, began + timeout - DEADLINE_MARGIN_S)
        first: list[str] = []
        if state.type not in ENDED:
            answered = prefect.cancel(run_id)
            said = f"this check's own deadline, {timeout - DEADLINE_MARGIN_S} s after it began, passed: "
            said += "the run was asked to cancel"
            if answered is None:
                said += f", and Prefect at {prefect.address} did not answer"
            elif isinstance(answered, int):
                said += f", and Prefect at {prefect.address} did not accept it (HTTP {answered})"
            first.append(said)
            state = await prefect.wait(run_id, began + timeout - CLOSE_MARGIN_S)
        if state.type not in ENDED:
            said = (
                f"flow run {run_id} of {check.flow}/{DEPLOYMENT} had not ended {timeout - CLOSE_MARGIN_S} s after this "
                f"check began{check.goes_on}"
            )
            if prefect.unread is not None:
                said += f"; the last read of its state failed: {prefect.unread}"
            return Outcome(False, "\n".join([*first, said]))
        try:
            document = await prefect.document(run_id)
        except Fault as fault:
            said = f"flow run {run_id} of {check.flow}/{DEPLOYMENT} ended {state.type}, then {fault}"
            return Outcome(False, "\n".join([*first, said]))
    except BaseException:
        if state is None or state.type not in ENDED:
            prefect.cancel(run_id)
        raise
    if document is None:
        return Outcome(False, "\n".join([*first, _unfiled(check, run_id, state)]))
    outcome = _concluded(check, document)
    return Outcome(outcome.passed, "\n".join([*first, outcome.message]))


def _concluded(check: _Check, document: Mapping[str, Any]) -> Outcome:
    """The conclusion of a document: its status alone, the message its headline."""
    version = document.get(check.version)
    if version != "1":
        return Outcome(False, f"the run filed a document of version {version}, which this check does not read")
    status, headline = document.get("status"), document.get("headline")
    if not isinstance(headline, str) or not headline:
        headline = f"the run filed a document of status {status} with no headline"
    message = f"{headline}\n{THREAD}" if check.thread else headline
    return Outcome(status == check.passing, message)


def _unfiled(check: _Check, run_id: str, state: State) -> str:
    """The conclusion of a run that ended in `state` and filed no document."""
    if state.type == "CANCELLED":
        return f"{check.what} was stopped (flow run {run_id}: CANCELLED){check.stopped}"
    if state.type == "FAILED" and state.name == "TimedOut":
        return f"{check.what} passed its time limit (flow run {run_id}: FAILED, TimedOut){check.stopped}"
    said = f"flow run {run_id} of {check.flow}/{DEPLOYMENT} ended {state.type}"
    if state.message:
        said += f": {state.message[:STATE_MESSAGE_LIMIT]}"
    return f"{said}, and filed no document"


def _variables(environ: Mapping[str, str]) -> tuple[str, tuple[str, str]]:
    """The edge's Prefect address and its basic auth, from the task worker's two variables, or a `Fault` naming the
    one unset or malformed, never its value."""
    address = environ.get(ENV_ADDRESS, "")
    if not address:
        raise Fault(f"{ENV_ADDRESS} is not set, so this check cannot reach the edge's Prefect: nothing was started")
    if "://" in address:
        raise Fault(
            f"{ENV_ADDRESS} holds a scheme: it is the edge's Prefect as a host and a port, such as "
            "host.docker.internal:4200, with no scheme; nothing was started"
        )
    auth = environ.get(ENV_AUTH, "")
    if not auth:
        raise Fault(f"{ENV_AUTH} is not set, so this check cannot reach the edge's Prefect: nothing was started")
    user, _, password = auth.partition(":")
    if not user or not password:
        raise Fault(f"{ENV_AUTH} is not user:password, the edge's Prefect's basic auth: nothing was started")
    return address, (user, password)
