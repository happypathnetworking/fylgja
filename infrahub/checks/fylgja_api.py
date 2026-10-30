"""The glue Fylgja's two Infrahub checks share (contracts/checks.md; 020's research R-12, data-model §9).

It decides nothing. It reads the check's two variables, finds the open proposed change by its
source branch with the check's own client, triggers one flow's deployment on the
orchestrator's platform (Prefect's API, over plain HTTP: 020's research §1.3), waits for the
flow run, reads its document (the run's artifact fylgja-findings, §1.4) and its out lines (the
run's log), and asks the run to cancel at the check's own deadline. Every verdict, deadline,
wording and report is the orchestrator's; the rehearse flow posts the report itself (R-11).

No sentence here carries the credential, and none carries a variable's value but the
address's: a fault names the variable, or the address it reached for. Stdlib and httpx alone,
as Infrahub's task-worker image carries them (020's research §1.1): never Prefect's client,
whose environment there points at Infrahub's own server. Importing it does nothing.
"""

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

# The task worker's environment, given by the Compose override (020's data-model §10).
ENV_ADDRESS = "FYLGJA_ORCHESTRATOR_ADDRESS"
ENV_AUTH = "FYLGJA_ORCHESTRATOR_AUTH"

# The flows the checks trigger, each served by the runner as the deployment main (R-08).
FLOW_STAGE_PLAN = "stage-plan"
FLOW_TWIN_REHEARSE = "twin-rehearse"
DEPLOYMENT = "main"

# ARTIFACT_TYPE is the type of the artifact a flow files its document under, its data the
# document's JSON (fylgja_orchestrator.flows.common's ARTIFACT_TYPE). OUT_LOGGER is the logger
# a flow's out lines are logged under in its run's log (common's OUT_LOGGER), told apart from
# Prefect's own lines in the same log (research §5.21).
ARTIFACT_TYPE = "fylgja-findings"
OUT_LOGGER = "prefect.flow_runs.fylgja"

# The flow run's ended states: Prefect's terminal state types.
ENDED = frozenset({"COMPLETED", "FAILED", "CANCELLED", "CRASHED"})

# The default branch, where the proposed change lives (015's research §1.2).
DEFAULT_BRANCH = "main"

# DIAL_TIMEOUT bounds a connection, and REQUEST_TIMEOUT one request's answer: every request
# here answers at once, the wait being the check's polls.
DIAL_TIMEOUT = 5.0
REQUEST_TIMEOUT = 30.0

# POLL_S is the wait between two reads of a flow run's state (R-12).
POLL_S = 5.0

# RETRY_503_S is the wait before the one retry of a request the platform answered 503, as it
# answers the first create_flow_run just after its deployments appear (research §1.2).
RETRY_503_S = 5.0

# A run's log lands on the platform a second or so after its state ends (research §5.21): its
# out lines are read until two reads LOG_SETTLE_S apart agree, at most LOG_READS reads, each a
# page of LOG_PAGE records at a time.
LOG_SETTLE_S = 1.0
LOG_READS = 5
LOG_PAGE = 200

# CANCEL_TIMEOUT bounds the blocking cancellation, which holds the task worker's event loop.
CANCEL_TIMEOUT = 10.0

# CLOSE_MARGIN_S is how long before its timeout a check stops waiting for its flow run: a run
# that has not ended by then is the check's own failure, and the check concludes before
# Infrahub's timeout, which would leave its validator in_progress (FR-021). It covers what the
# check does after a run that ends just before it: the document's read, the out lines' reads
# and the conclusion. Nothing is posted by a check (R-11).
CLOSE_MARGIN_S = 120

# FR-017's one exception, the one rule the checks hold beside the status's mapping (D-052):
# a branch point refused scope.empty at read, the scope selecting no device on main (017's
# FR-015, R-20), is not a refusal of the change, and the other stages decide. It reads the
# finding's rule and step and the stage's at_source and nothing else, as the orchestrator's
# passed_over does: fylgja-step passes it over in the plan, and fylgja-twin in a refusal that
# says the host is held. The three values are the orchestrator's rule scope.empty, the
# findings contract's step read and the stage's at_source branch_point, held by
# test_checks_glue.py (internal/rehearsal's Go test did until 020's T035).
RULE_SCOPE_EMPTY = "scope.empty"
STEP_READ = "read"
AT_BRANCH_POINT = "branch_point"

# MAX_CAUSE_CHARS bounds an error of Infrahub's, the platform's or the transport's quoted in
# a message.
MAX_CAUSE_CHARS = 500

# The severities' order in a document's text, as WriteText orders them.
RANK = {"rejection": 0, "warning": 1, "info": 2}


class Fault(Exception):
    """Why a check cannot conclude from the orchestrator's answer, as one sentence for log_error."""


class Unset(Fault):
    """A variable the check needs is unset or empty in the task worker: nothing is sent."""

    def __init__(self, name: str) -> None:
        super().__init__(
            f"{name} is not set in this task worker's environment: the check cannot reach the orchestrator's "
            "platform, and nothing was sent"
        )
        self.name = name


class Unreachable(Fault):
    """Nothing answers at the address."""

    def __init__(self, address: str, cause: str) -> None:
        super().__init__(f"the orchestrator's platform at {address} cannot be reached: {cause}")


class CredentialRefused(Fault):
    """The platform answered 401: the credential is not its own."""

    def __init__(self, address: str) -> None:
        super().__init__(f"the orchestrator's platform at {address} refused this check's credential ({ENV_AUTH})")


class NoDeployment(Fault):
    """The platform answers, and serves no deployment of the flow: no runner serves it."""

    def __init__(self, address: str, name: str) -> None:
        super().__init__(
            f"the orchestrator's platform at {address} serves no deployment {name}: "
            "its runner, fylgja-orchestrator serve, has not served it"
        )


class Unexpected(Fault):
    """Any other answer: something at the address answered, but not as the platform does."""

    def __init__(self, address: str, what: str) -> None:
        super().__init__(f"the orchestrator's platform at {address} answered {what}")


class Lost(Fault):
    """The platform could not be read once the flow run had been triggered: the run goes on, and
    ran holds what was read of it."""

    def __init__(self, fault: Fault, ran: "Ran") -> None:
        super().__init__(f"flow run {ran.flow_run_id} of {ran.flow}/{DEPLOYMENT} was triggered, then {fault}")
        self.ran = ran


@dataclass(frozen=True)
class ProposedChange:
    """The open proposed change a check runs for, as its source branch finds it."""

    id: str
    name: str
    is_draft: bool


@dataclass(frozen=True)
class State:
    """A flow run's state as the platform reads it: its type (SCHEDULED, RUNNING, COMPLETED,
    FAILED, …), its name (Completed, TimedOut, …) and its message."""

    type: str = ""
    name: str = ""
    message: str = ""

    @property
    def ended(self) -> bool:
        return self.type in ENDED

    def __str__(self) -> str:
        said = self.type or "unread"
        if self.name and self.name.upper() != self.type:
            said += f" ({self.name})"
        if self.message:
            said += f": {_bounded(self.message)}"
        return said


@dataclass
class Ran:
    """One flow run, as far as the check read it.

    state is the last state read; document the run's findings document, None when it filed
    none; lines its out lines, in order; lines_failure why they could not be read, None when
    they were. cancelled is whether the check's deadline passed with the run not ended and the
    cancellation was asked, cancel_failure why it was not delivered, None when it was.
    """

    flow: str
    flow_run_id: str
    state: State = field(default_factory=State)
    document: dict[str, Any] | None = None
    lines: list[str] = field(default_factory=list)
    lines_failure: str | None = None
    cancelled: bool = False
    cancel_failure: str | None = None

    def heading(self) -> str:
        """The run's identity and its state, for the check's message."""
        return f"flow run {self.flow_run_id} of {self.flow}/{DEPLOYMENT}: {self.state}"


def variables() -> tuple[str, tuple[str, str]]:
    """The platform's address, and its credential as basic auth's user and password, from the
    task worker's environment.

    An unset or empty one is Unset naming the variable, the address first; a credential that
    is not user:password, or holds a character a request header cannot carry, is a Fault
    naming the variable. Neither value is in either.
    """
    address = os.environ.get(ENV_ADDRESS, "")
    auth = os.environ.get(ENV_AUTH, "")
    for name, value in ((ENV_ADDRESS, address), (ENV_AUTH, auth)):
        if not value:
            raise Unset(name)
    # A local/.env saved with CRLF line endings leaves a carriage return on every value.
    if auth != auth.strip() or any(ord(c) < 0x20 or ord(c) == 0x7F for c in auth):
        raise Fault(f"{ENV_AUTH} holds a character a request header cannot carry: nothing was sent")
    user, sep, password = auth.partition(":")
    if not sep or not user or not password:
        raise Fault(f"{ENV_AUTH} is not user:password: nothing was sent")
    return address, (user, password)


async def proposed_change(client: Any, branch: str) -> ProposedChange | None:
    """The open proposed change whose source branch is branch, or None when none is open.

    It is read on the default branch with the check's own client (015's research §1.3):
    Infrahub hands a check its source branch and never its proposed change's id (§1.2), and
    opens one proposed change per source branch at most. The SDK raises on a GraphQL error,
    which Infrahub answers 200; a read that fails is a Fault, never a proposed change missing.
    """
    try:
        nodes = await client.filters(
            kind="CoreProposedChange",
            branch=DEFAULT_BRANCH,
            source_branch__value=branch,
            state__value="open",
        )
    except Exception as exc:  # noqa: BLE001 - every failure of the read is the check's failure
        raise Fault(f"the proposed change from branch {branch} could not be read from Infrahub: {cause(exc)}") from None
    if not nodes:
        return None
    node = nodes[0]
    return ProposedChange(id=node.id, name=node.name.value, is_draft=bool(node.is_draft.value))


def none_open(branch: str) -> str:
    """The sentence for a check run on a branch with no open proposed change."""
    return f"no open proposed change has source branch {branch}: nothing was asked of the orchestrator"


def rejections_past_branch_point(
    found: list[dict[str, Any]] | None, stages: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """A document's rejections, in order, but for the branch point's lone scope.empty at read
    among stages (FR-017's exception): the plan's stages for stage-plan, the rehearsal block's
    for twin-rehearse. Each stage's findings are also in the document's own list
    (stages.schema.json, rehearsal.schema.json), where the one passed over is found by key."""
    rejections = [f for f in found or [] if f.get("severity") == "rejection"]
    for excused in branch_point_refusal(stages):
        key = finding_key(excused)
        for i, f in enumerate(rejections):
            if finding_key(f) == key:
                del rejections[i]
                break
    return rejections


def branch_point_refusal(stages: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """The branch point's one rejection when it is scope.empty at read, else none."""
    for stage in stages or []:
        if stage.get("at_source") != AT_BRANCH_POINT:
            continue
        rejections = [f for f in stage.get("findings") or [] if f.get("severity") == "rejection"]
        if (
            len(rejections) == 1
            and rejections[0].get("rule") == RULE_SCOPE_EMPTY
            and rejections[0].get("step") == STEP_READ
        ):
            return rejections
    return []


def finding_key(finding: dict[str, Any]) -> tuple[Any, ...]:
    """A finding as the document's list and a stage's both carry it."""
    return tuple(finding.get(k) for k in ("severity", "rule", "object", "step", "message"))


def findings_text(document: dict[str, Any] | None) -> str:
    """The document's findings as WriteText prints them: each on its line, rejections first,
    then warnings, then info, each by rule then object, the order of equals kept, then the
    summary when there is any; "" for none. The text a check's message carries, as 015's
    answer's text frame carried it."""
    found = [f for f in (document or {}).get("findings") or [] if isinstance(f, dict)]
    ordered = sorted(found, key=lambda f: (RANK.get(f.get("severity"), 0), f.get("rule") or "", f.get("object") or ""))
    lines = [finding_line(f) for f in ordered]
    if found:
        n = {s: sum(1 for f in found if f.get("severity") == s) for s in RANK}
        lines.append(f"{len(found)} finding(s): {n['rejection']} rejection, {n['warning']} warning, {n['info']} info")
    return "\n".join(lines)


def finding_line(finding: dict[str, Any]) -> str:
    """One finding as WriteText prints it: `<severity> <rule>[ [step <step>]] <where>: <message>`,
    where is the object, or the file (and line) with the object after it."""
    where = finding.get("object") or ""
    location = finding.get("location")
    if isinstance(location, dict):
        where = location.get("file") or ""
        if (location.get("line") or 0) > 0:
            where = f"{where}:{location['line']}"
        if finding.get("object"):
            where = f"{where} ({finding['object']})"
    rule = finding.get("rule") or ""
    if finding.get("step"):
        rule = f"{rule} [step {finding['step']}]"
    return f"{finding.get('severity')} {rule} {where}: {finding.get('message')}"


class Platform:
    """The orchestrator's platform, Prefect's API at the address, asked with the credential.

    Each request goes to the address alone, with no proxy of the environment's and no
    redirect followed, so the credential goes nowhere else (D-042's rule, the platform's
    credential in the core token's place). transport replaces httpx's, for a test.
    """

    def __init__(self, address: str, auth: tuple[str, str], transport: httpx.BaseTransport | None = None) -> None:
        self.address = address
        self._api = _base(address) + "/api"
        self._auth = auth
        self._transport = transport

    async def trigger(self, flow: str, parameters: dict[str, Any]) -> str:
        """A new run of the flow's deployment main with parameters: its id.

        GET /api/deployments/name/<flow>/main for the deployment's id, then POST
        /api/deployments/<id>/create_flow_run; a 503 to either is asked once more after
        RETRY_503_S. A deployment the platform does not serve is NoDeployment.
        """
        name = f"{flow}/{DEPLOYMENT}"
        async with self._client() as client:
            response = await self._retried(client, "GET", f"/deployments/name/{flow}/{DEPLOYMENT}")
            if response.status_code == 404:
                raise NoDeployment(self.address, name)
            deployment = self._field(response, 200, f"the read of deployment {name}", "id")
            response = await self._retried(
                client, "POST", f"/deployments/{deployment}/create_flow_run", {"parameters": parameters}
            )
            return str(self._field(response, 201, f"a run of deployment {name}", "id"))

    async def wait(self, flow_run_id: str, deadline: float) -> State:
        """The flow run's state once it has ended, or the last state read once deadline (a
        time.monotonic() value) has passed with it not ended, read every POLL_S.

        A read that cannot reach the platform is asked again at the next poll, and is
        Unreachable only when the last read before deadline failed; any other fault, a
        refused credential or a run the platform does not hold, is raised at once.
        """
        state = State()
        failure: Fault | None = None
        async with self._client() as client:
            while True:
                try:
                    state = await self._state(client, flow_run_id)
                    failure = None
                except Unreachable as fault:
                    failure = fault
                if failure is None and state.ended:
                    return state
                left = deadline - time.monotonic()
                if left <= 0:
                    break
                await asyncio.sleep(min(POLL_S, left))
        if failure is not None:
            raise failure
        return state

    async def document(self, flow_run_id: str) -> dict[str, Any] | None:
        """The run's findings document, its artifact fylgja-findings's data parsed, or None
        when the run filed none (POST /api/artifacts/filter)."""
        body = {
            "artifacts": {"flow_run_id": {"any_": [flow_run_id]}, "type": {"any_": [ARTIFACT_TYPE]}},
            "sort": "CREATED_DESC",
            "limit": 1,
        }
        async with self._client() as client:
            response = await self._send(client, "POST", "/artifacts/filter", body)
            artifacts = self._json(response, 200, "the read of the run's artifacts")
        if not isinstance(artifacts, list):
            raise Unexpected(self.address, "the read of the run's artifacts with something not a list")
        if not artifacts:
            return None
        data = artifacts[0].get("data") if isinstance(artifacts[0], dict) else None
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except ValueError as exc:
                raise Unexpected(self.address, f"an artifact {ARTIFACT_TYPE} whose data is not JSON: {exc}") from None
        if not isinstance(data, dict):
            raise Unexpected(self.address, f"an artifact {ARTIFACT_TYPE} whose data is not a document")
        return data

    async def lines(self, flow_run_id: str) -> list[str]:
        """The run's out lines, in order: the records of its log under OUT_LOGGER (POST
        /api/logs/filter), read until two reads LOG_SETTLE_S apart agree or LOG_READS have
        been made, since the log lands a little after the state."""
        previous: list[str] | None = None
        async with self._client() as client:
            for read in range(LOG_READS):
                got = await self._out_lines(client, flow_run_id)
                if got == previous:
                    return got
                previous = got
                if read < LOG_READS - 1:
                    await asyncio.sleep(LOG_SETTLE_S)
        return previous or []

    def cancel(self, flow_run_id: str) -> str | None:
        """The run asked to cancel, POST /api/flow_runs/<id>/set_state CANCELLING, as a blocking
        call: a check Infrahub has cut can still make it, where every await is cancelled (015's
        research §1.4). Without force, which would move a run that has just ended out of its
        end (research §5.21): the platform accepts it of a running run, ends a scheduled one
        cancelled at once, and aborts it for one already ended, which is no failure. None when
        delivered or nothing was left to cancel; otherwise why not, for the caller to log. It
        never raises, since it runs inside the handler of another exception."""
        try:
            with httpx.Client(
                base_url=self._api,
                auth=self._auth,
                timeout=CANCEL_TIMEOUT,
                trust_env=False,
                follow_redirects=False,
                transport=self._transport,
            ) as client:
                response = client.post(f"/flow_runs/{flow_run_id}/set_state", json={"state": {"type": "CANCELLING"}})
        except Exception as exc:  # noqa: BLE001 - a failed cancellation is reported, never raised
            return str(Unreachable(self.address, cause(exc)))
        if response.status_code == 401:
            return str(CredentialRefused(self.address))
        if response.status_code == 404:
            return f"the orchestrator's platform at {self.address} holds no flow run {flow_run_id}"
        if response.status_code not in (200, 201):
            return str(Unexpected(self.address, f"{response.status_code} {response.reason_phrase} to the cancellation"))
        try:
            status = response.json().get("status")
        except (ValueError, AttributeError):
            status = None
        if status in ("ACCEPT", "REJECT", "ABORT"):
            return None
        return str(Unexpected(self.address, f"{status or 'no status'} to the cancellation"))

    def _client(self) -> httpx.AsyncClient:
        try:
            return httpx.AsyncClient(
                base_url=self._api,
                auth=self._auth,
                timeout=httpx.Timeout(REQUEST_TIMEOUT, connect=DIAL_TIMEOUT),
                trust_env=False,
                follow_redirects=False,
                transport=self._transport,
            )
        except Exception:  # noqa: BLE001 - whatever httpx cannot read of the address is the variable's
            raise Fault(f"{ENV_ADDRESS} cannot be used: httpx cannot read it as a URL; nothing was sent") from None

    async def _send(self, client: httpx.AsyncClient, method: str, path: str, body: Any = None) -> httpx.Response:
        """One request; a transport failure is Unreachable and a 401 CredentialRefused."""
        try:
            response = await client.request(method, path, json=body)
        except httpx.HTTPError as exc:
            raise Unreachable(self.address, cause(exc)) from None
        if response.status_code == 401:
            raise CredentialRefused(self.address)
        return response

    async def _retried(self, client: httpx.AsyncClient, method: str, path: str, body: Any = None) -> httpx.Response:
        """One request, asked once more after RETRY_503_S when the platform answers 503."""
        response = await self._send(client, method, path, body)
        if response.status_code == 503:
            await asyncio.sleep(RETRY_503_S)
            response = await self._send(client, method, path, body)
        return response

    async def _state(self, client: httpx.AsyncClient, flow_run_id: str) -> State:
        response = await self._send(client, "GET", f"/flow_runs/{flow_run_id}")
        if response.status_code == 404:
            raise Fault(f"the orchestrator's platform at {self.address} holds no flow run {flow_run_id}")
        run = self._json(response, 200, f"the read of flow run {flow_run_id}")
        state = run.get("state") if isinstance(run, dict) else None
        if not isinstance(state, dict):
            return State()
        return State(str(state.get("type") or ""), str(state.get("name") or ""), str(state.get("message") or ""))

    async def _out_lines(self, client: httpx.AsyncClient, flow_run_id: str) -> list[str]:
        lines: list[str] = []
        offset = 0
        while True:
            body = {
                "logs": {"flow_run_id": {"any_": [flow_run_id]}},
                "sort": "TIMESTAMP_ASC",
                "limit": LOG_PAGE,
                "offset": offset,
            }
            response = await self._send(client, "POST", "/logs/filter", body)
            page = self._json(response, 200, "the read of the run's log")
            if not isinstance(page, list):
                raise Unexpected(self.address, "the read of the run's log with something not a list")
            lines += [r.get("message", "") for r in page if isinstance(r, dict) and r.get("name") == OUT_LOGGER]
            if len(page) < LOG_PAGE:
                return lines
            offset += LOG_PAGE

    def _json(self, response: httpx.Response, status: int, what: str) -> Any:
        """The answer's JSON when its status is status; otherwise Unexpected naming what was asked."""
        if response.status_code != status:
            raise Unexpected(self.address, f"{response.status_code} {response.reason_phrase} to {what}")
        try:
            return response.json()
        except ValueError:
            raise Unexpected(self.address, f"{what} with something not JSON") from None

    def _field(self, response: httpx.Response, status: int, what: str, key: str) -> Any:
        body = self._json(response, status, what)
        if not isinstance(body, dict) or not body.get(key):
            raise Unexpected(self.address, f"{what} with no {key}")
        return body[key]


async def run(
    platform: Platform,
    flow: str,
    parameters: dict[str, Any],
    deadline: float,
    close_by: float | None = None,
) -> Ran:
    """One run of the flow, triggered, waited for to its end, then read: its document and its
    out lines.

    If deadline (a time.monotonic() value) passes with the run not ended, the run is asked to
    cancel, and then waited for until close_by when it is given: a cancelled rehearsal still
    destroys and files its document within the runner's grace (research §5.18). A run not
    ended by then is returned as last read, with no document. A fault before the run exists
    is raised as it is; one once it exists is Lost, the run going on. If the check is
    cancelled or timed out while the run has not ended, the run is asked to cancel with a
    blocking call, since nothing is awaited in that handler (015's research §1.4), and the
    cancellation goes on.
    """
    ran = Ran(flow, await platform.trigger(flow, parameters))
    try:
        ran.state = await platform.wait(ran.flow_run_id, deadline)
        if not ran.state.ended:
            ran.cancelled = True
            ran.cancel_failure = platform.cancel(ran.flow_run_id)
            if close_by is not None:
                ran.state = await platform.wait(ran.flow_run_id, close_by)
        if ran.state.ended:
            ran.document = await platform.document(ran.flow_run_id)
    except Fault as fault:
        raise Lost(fault, ran) from None
    except BaseException:
        if not ran.state.ended:
            platform.cancel(ran.flow_run_id)
        raise
    if ran.state.ended:
        try:
            ran.lines = await platform.lines(ran.flow_run_id)
        except Fault as fault:
            ran.lines_failure = str(fault)
    return ran


def cause(exc: BaseException) -> str:
    """An error as one bounded line: a GraphQL error's messages, as the SDK carries them, rather
    than its query; otherwise its first line, or its type when it says nothing."""
    errors = getattr(exc, "errors", None)
    if isinstance(errors, list) and errors:
        text = "; ".join(e.get("message", str(e)) if isinstance(e, dict) else str(e) for e in errors)
    else:
        lines = str(exc).strip().splitlines()
        text = lines[0] if lines else type(exc).__name__
    return _bounded(text)


def _bounded(text: str) -> str:
    return text if len(text) <= MAX_CAUSE_CHARS else text[: MAX_CAUSE_CHARS - 1] + "…"


def _base(address: str) -> str:
    """The platform's root URL, from host:port or an http:// or https:// URL without a user or
    password, its port 1 to 65535, as the core's client takes its address. An address refused
    is named by its variable alone, since it may hold one."""
    if address.startswith(("http://", "https://")):
        try:
            url = httpx.URL(address)
        except httpx.InvalidURL:
            raise Fault(f"{ENV_ADDRESS} is not host:port or an http:// or https:// URL: nothing was sent") from None
        if url.port is not None and not 1 <= url.port <= 65535:
            raise Fault(f"{ENV_ADDRESS} is not host:port or an http:// or https:// URL: nothing was sent")
        if url.userinfo or not url.host or url.query or url.fragment:
            raise Fault(
                f"{ENV_ADDRESS} is not an http:// or https:// URL of a server without a user or password: "
                "nothing was sent"
            )
        return address.rstrip("/")
    host, sep, port = address.rpartition(":")
    # httpx builds a request to a port over 65535, and the connect fails with an error that is
    # not httpx's, so the range is checked here; isdigit alone would take any script's digits.
    decimal = port.isascii() and port.isdigit() and 1 <= int(port) <= 65535
    if not sep or not host or not decimal or "/" in address or "@" in address:
        raise Fault(f"{ENV_ADDRESS} is not host:port or an http:// or https:// URL: nothing was sent")
    return "http://" + address
