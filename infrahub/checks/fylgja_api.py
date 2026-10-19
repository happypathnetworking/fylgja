"""The glue Fylgja's two Infrahub checks share (contracts/checks.md; research R-13, R-15, R-16).

It decides nothing. It reads the check's two variables, finds the open proposed change by its
source branch with the check's own client, asks Fylgja's API one operation and reads the
answer's frames to its document (contracts/api.md), sends the operator's interrupt, and posts
a comment. Every verdict, deadline and wording of a report is the server's.

No sentence here carries the token, and none carries a variable's value but the address's: a
fault names the variable, or the address it reached for. Stdlib and httpx alone, as Infrahub's
task-worker image carries them (research §1.1). Importing it does nothing.
"""

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

# The task worker's environment, given by the Compose override (research R-17).
ENV_ADDRESS = "FYLGJA_API_ADDRESS"
ENV_TOKEN = "FYLGJA_API_TOKEN"

# The API's version and headers, as internal/api/wire.go names them.
API_VERSION = "1"
HEADER_VERSION = "Fylgja-Api-Version"
HEADER_VERSIONS = "Fylgja-Api-Versions"
HEADER_STREAM = "Fylgja-Stream"

# The renderings a check asks for (contracts/api.md, "What render asks for").
RENDER_TEXT = "text"
RENDER_MARKDOWN = "markdown"

# The default branch, where the proposed change and its comments live (research §1.2).
DEFAULT_BRANCH = "main"

# DIAL_TIMEOUT bounds a connection, as the Go client's api.DialTimeout does; HEADER_TIMEOUT the
# wait for an answer's headers, which the server sends before it works (api.HeaderTimeout).
# Nothing bounds the answer once it has begun: a rehearsal's frames come minutes apart.
DIAL_TIMEOUT = 5.0
HEADER_TIMEOUT = 30.0

# INTERRUPT_TIMEOUT bounds the blocking interrupt, which holds the task worker's event loop.
INTERRUPT_TIMEOUT = 10.0

# MAX_PROBLEM_BYTES bounds what is read of a transport fault's body, as api.MaxProblemBytes.
MAX_PROBLEM_BYTES = 64 * 1024

# MAX_CAUSE_CHARS bounds an error of Infrahub's or the transport's quoted in a message.
MAX_CAUSE_CHARS = 500


def path(operation: str) -> str:
    """An operation's path under the API's version: stage.plan is /v1/stage/plan."""
    return f"/v{API_VERSION}/" + operation.replace(".", "/")


class Fault(Exception):
    """Why a check cannot conclude from Fylgja's answer, as one sentence for log_error."""


class Unset(Fault):
    """A variable the check needs is unset or empty in the task worker: nothing is sent."""

    def __init__(self, name: str) -> None:
        super().__init__(
            f"{name} is not set in this task worker's environment: the check cannot reach Fylgja, "
            "and nothing was sent"
        )
        self.name = name


class Unreachable(Fault):
    """Nothing answers at the address, or what answers is not the API."""

    def __init__(self, address: str, cause: str) -> None:
        super().__init__(f"the API at {address} cannot be reached: {cause}")


class TokenRefused(Fault):
    """The API answered 401: the token is not the server's."""

    def __init__(self, address: str) -> None:
        super().__init__(f"the API at {address} refused this check's token ({ENV_TOKEN})")


class VersionUnknown(Fault):
    """The API answered 404 naming the versions it serves, and this one is not among them."""

    def __init__(self, address: str, served: str) -> None:
        super().__init__(f"the API at {address} serves version {served}; this check speaks version {API_VERSION}")


class Unreadable(Fault):
    """The API answered 400: it could not read the request."""

    def __init__(self, address: str, message: str) -> None:
        super().__init__(f"the API at {address} could not read this check's request: {message}")


class Unexpected(Fault):
    """Any other status: something at the address answered, but not with an answer."""

    def __init__(self, address: str, status: str) -> None:
        super().__init__(f"the API at {address} answered {status}")


class Cut(Fault):
    """The answer ended before its document: the server stopped, or the connection was lost.
    answer holds what was read of it, so a caller can tell a cut after the run's start."""

    def __init__(self, address: str, cause: str, answer: Answer) -> None:
        super().__init__(f"the API at {address} stopped answering before the command ended: {cause}")
        self.answer = answer


@dataclass(frozen=True)
class ProposedChange:
    """The open proposed change a check runs for, as its source branch finds it."""

    id: str
    name: str
    is_draft: bool


@dataclass
class Answer:
    """One operation's answer, as far as it was read.

    out and err are the out and err frames' texts in the order they came, each one or more
    whole lines. started is whether a start frame came, after which a run may exist; run is
    the run frame's identity. document is the findings document, None until its frame; text
    and markdown are the renderings that frame carried, "" when it carried none. interrupted
    is whether the deadline passed with the answer open and the interrupt was sent, and
    interrupt_failure why it was not delivered, None when it was.
    """

    out: list[str] = field(default_factory=list)
    err: list[str] = field(default_factory=list)
    started: bool = False
    run: dict[str, Any] | None = None
    document: dict[str, Any] | None = None
    text: str = ""
    markdown: str = ""
    interrupted: bool = False
    interrupt_failure: str | None = None


def variables() -> tuple[str, str]:
    """The API's address and token, from the task worker's environment.

    An unset or empty one is Unset naming the variable, the address first; a token that no
    request header can carry is a Fault naming the variable. Neither value is in either.
    """
    address = os.environ.get(ENV_ADDRESS, "")
    token = os.environ.get(ENV_TOKEN, "")
    for name, value in ((ENV_ADDRESS, address), (ENV_TOKEN, token)):
        if not value:
            raise Unset(name)
    # A local/.env saved with CRLF line endings leaves a carriage return on every value, which
    # httpx would refuse once the request was built (internal/api/client.go's ErrTokenUnsendable).
    if token != token.strip() or any(ord(c) < 0x20 or ord(c) == 0x7F for c in token):
        raise Fault(f"{ENV_TOKEN} holds a character a request header cannot carry: nothing was sent")
    return address, token


async def proposed_change(client: Any, branch: str) -> ProposedChange | None:
    """The open proposed change whose source branch is branch, or None when none is open.

    It is read on the default branch with the check's own client (research §1.3): Infrahub
    hands a check its source branch and never its proposed change's id (§1.2), and opens one
    proposed change per source branch at most. The SDK raises on a GraphQL error, which
    Infrahub answers 200; a read that fails is a Fault, never a proposed change missing.
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
    return f"no open proposed change has source branch {branch}: nothing was asked of Fylgja"


async def call(
    address: str,
    token: str,
    operation_path: str,
    render: str,
    args: dict[str, Any],
    stream: str | None = None,
    deadline: float | None = None,
) -> Answer:
    """One POST of an operation to Fylgja's API, its answer read frame by frame to the document.

    The answer is the Answer with its document. A transport fault is the Fault the Go client
    reports for it: Unreachable, TokenRefused, VersionUnknown, Unreadable, Unexpected, and Cut
    for an answer that ends before its document.

    With stream, 16 random bytes in hex, the request names its answer under Fylgja-Stream, and
    from the run's start an interrupt reaches the run. If deadline (a time.monotonic() value)
    passes with the answer still open, the interrupt is sent and the answer read on to its
    document or its cut. If the check is cancelled or timed out once the run started, the
    interrupt is sent with a blocking call, since nothing is awaited in that handler (research
    §1.4), and the cancellation goes on.
    """
    base = _base(address)
    body: dict[str, Any] = {"args": args}
    if render:
        body["render"] = render
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    if stream:
        headers[HEADER_STREAM] = stream
    answer = Answer()
    # The address is the operator's, with no proxy of the environment's, and the API never
    # redirects, so no redirect is followed and the token goes nowhere else (D-042).
    timeout = httpx.Timeout(DIAL_TIMEOUT, read=None)
    async with httpx.AsyncClient(timeout=timeout, trust_env=False, follow_redirects=False) as client:
        request = client.build_request("POST", base + operation_path, json=body, headers=headers)
        try:
            response = await asyncio.wait_for(client.send(request, stream=True), HEADER_TIMEOUT)
        except TimeoutError:
            raise Unreachable(address, f"no answer within {HEADER_TIMEOUT:.0f}s of the request") from None
        except httpx.HTTPError as exc:
            raise Unreachable(address, cause(exc)) from None
        try:
            await _accept(response, address)
            reader = asyncio.ensure_future(_read(response, address, answer))
            try:
                if deadline is not None and stream:
                    done, _ = await asyncio.wait({reader}, timeout=max(0.0, deadline - time.monotonic()))
                    if not done:
                        answer.interrupted = True
                        answer.interrupt_failure = interrupt_blocking(address, token, stream)
                await reader
            except Fault:
                raise
            except BaseException:
                reader.cancel()
                if stream and answer.started and answer.document is None and not answer.interrupted:
                    interrupt_blocking(address, token, stream)
                raise
        finally:
            await response.aclose()
    return answer


def interrupt_blocking(address: str, token: str, stream: str) -> str | None:
    """The operator's interrupt, POST /v1/streams/{stream}/interrupt, as a blocking call.

    A check Infrahub has cut can still make it, where every await is cancelled (research
    §1.4). None when delivered; otherwise why not, for the caller to log. It never raises,
    since it runs inside the handler of another exception.
    """
    try:
        base = _base(address)
        with httpx.Client(timeout=INTERRUPT_TIMEOUT, trust_env=False, follow_redirects=False) as client:
            response = client.post(
                base + f"/v{API_VERSION}/streams/{stream}/interrupt",
                headers={"Authorization": f"Bearer {token}"},
            )
    except Fault as fault:
        return str(fault)
    except Exception as exc:  # noqa: BLE001 - a failed interrupt is reported, never raised
        return str(Unreachable(address, cause(exc)))
    if response.status_code == 204:
        return None
    if response.status_code == 404 and HEADER_VERSIONS not in response.headers:
        return "the answer the interrupt names has ended"
    if response.status_code == 401:
        return str(TokenRefused(address))
    return str(Unexpected(address, f"{response.status_code} {response.reason_phrase}"))


async def post_comment(client: Any, change_id: str, text: str) -> str | None:
    """One CoreChangeComment on the proposed change, saved on the default branch: text the
    report's markdown, change the proposed change (research §1.2, §1.3). It is the check's one
    write (D-049). None when posted; otherwise why not, for the caller to log as information,
    since a comment that cannot be posted fails nothing (FR-019).
    """
    try:
        comment = await client.create(
            kind="CoreChangeComment",
            branch=DEFAULT_BRANCH,
            data={"text": text, "change": change_id},
        )
        await comment.save()
    except Exception as exc:  # noqa: BLE001 - reported, and the conclusion stays the report's
        return cause(exc)
    return None


def cause(exc: BaseException) -> str:
    """An error as one bounded line: a GraphQL error's messages, as the SDK carries them, rather
    than its query, which would quote the comment's markdown; otherwise its first line."""
    errors = getattr(exc, "errors", None)
    if isinstance(errors, list) and errors:
        text = "; ".join(e.get("message", str(e)) if isinstance(e, dict) else str(e) for e in errors)
    else:
        lines = str(exc).strip().splitlines()
        text = lines[0] if lines else type(exc).__name__
    return text if len(text) <= MAX_CAUSE_CHARS else text[: MAX_CAUSE_CHARS - 1] + "…"


def _base(address: str) -> str:
    """The server's root URL, from host:port or an http:// or https:// URL without a user or
    password. An address refused is named by its variable alone, since it may hold one."""
    if address.startswith(("http://", "https://")):
        try:
            url = httpx.URL(address)
        except httpx.InvalidURL:
            raise Fault(f"{ENV_ADDRESS} is not host:port or an http:// or https:// URL: nothing was sent") from None
        if url.userinfo or not url.host or url.query or url.fragment:
            raise Fault(
                f"{ENV_ADDRESS} is not an http:// or https:// URL of a server without a user or password: "
                "nothing was sent"
            )
        return address.rstrip("/")
    host, sep, port = address.rpartition(":")
    if not sep or not host or not port.isdigit() or "/" in address or "@" in address:
        raise Fault(f"{ENV_ADDRESS} is not host:port or an http:// or https:// URL: nothing was sent")
    return "http://" + address


async def _accept(response: httpx.Response, address: str) -> None:
    """Nothing for an answer of the API's; the Fault for any other status (contracts/api.md,
    "The transport's statuses"), as internal/api/client.go's fault reads it."""
    status = response.status_code
    if status == 200:
        if HEADER_VERSION not in response.headers:
            raise Unreachable(address, f"what answers there is not the API: its answer names no {HEADER_VERSION}")
        return
    if status == 401:
        raise TokenRefused(address)
    if status == 404:
        served = response.headers.get(HEADER_VERSIONS, "")
        if served and API_VERSION not in (v.strip() for v in served.split(",")):
            raise VersionUnknown(address, served)
    if status == 400:
        raise Unreadable(address, await _problem(response))
    raise Unexpected(address, f"{status} {response.reason_phrase}")


async def _problem(response: httpx.Response) -> str:
    """A fault's body's message, as much of it as a problem can be."""
    held = bytearray()
    try:
        async for chunk in response.aiter_bytes():
            held += chunk
            if len(held) > MAX_PROBLEM_BYTES:
                break
        message = json.loads(bytes(held[:MAX_PROBLEM_BYTES])).get("message", "")
    except (httpx.HTTPError, ValueError, AttributeError):
        message = ""
    return message or "its answer gave no reason"


async def _read(response: httpx.Response, address: str, answer: Answer) -> None:
    """The answer's frames into answer, one JSON object a line, to the document frame. Lines are
    split on newline alone, as the Go client splits them: a frame's JSON escapes every newline,
    but not every character str.splitlines() would split on."""
    held = bytearray()
    try:
        async for chunk in response.aiter_bytes():
            held += chunk
            while (end := held.find(b"\n")) >= 0:
                line = bytes(held[:end])
                del held[: end + 1]
                if _frame(line, address, answer):
                    return
    except httpx.HTTPError as exc:
        raise Cut(address, cause(exc), answer) from None
    if held.strip() and _frame(bytes(held), address, answer):
        return
    raise Cut(address, "the connection closed", answer)


def _frame(line: bytes, address: str, answer: Answer) -> bool:
    """One frame into answer; True for the document, the last. A frame of a kind this check does
    not use (event, files, one a later server adds) is passed over (contracts/api.md)."""
    if not line.strip():
        return False
    try:
        frame = json.loads(line)
    except ValueError as exc:
        raise Cut(address, f"a line of the answer is not a frame: {exc}", answer) from None
    if not isinstance(frame, dict):
        raise Cut(address, "a line of the answer is not a frame: not a JSON object", answer)
    if "document" in frame:
        answer.document = frame["document"]
        answer.text = frame.get("text") or ""
        answer.markdown = frame.get("markdown") or ""
        return True
    if "out" in frame:
        answer.out.append(frame["out"])
    elif "err" in frame:
        answer.err.append(frame["err"])
    elif "start" in frame:
        answer.started = True
    elif "run" in frame:
        answer.run = frame["run"]
    return False
