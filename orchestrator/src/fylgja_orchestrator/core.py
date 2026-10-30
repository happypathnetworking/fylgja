"""The core's client (data-model §7; R-08; FR-017, FR-022): the API `fylgja serve` answers,
spoken as `internal/api/client.go` speaks it, from the orchestrator's side.

Its environment is `FYLGJA_API_ADDRESS` (host:port or an http:// or https:// URL, default
`127.0.0.1:7650`) and `FYLGJA_API_TOKEN`, read where each request is built and never held:
not in a field, not in an error, not in a log line. Every run is started under `detach`, so
its answer ends at the run's identity, and is then read by `run.read` every two seconds to
its document: the answer stream is never opened, and a flow rerun after its platform
restarts reads the run it started rather than starting a second into `run.in_flight`
(R-03, R-04). A failure between this client and the server is a `CoreFailure`, worded as
`internal/cli/failures.go` words it, which a flow turns into its document.
"""

import base64
import json
import os
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from .documents.findings import (
    OP_COMPILE,
    OP_RUN_INTERRUPT,
    OP_RUN_READ,
    OP_TWIN_DESTROY,
    OP_TWIN_DIFF,
    OP_TWIN_SHOW,
    OP_TWIN_VERIFY,
    RULE_OPERATION_FAILED,
    Document,
    rule_error_document,
)

ENV_ADDRESS = "FYLGJA_API_ADDRESS"
ENV_TOKEN = "FYLGJA_API_TOKEN"
DEFAULT_ADDRESS = "127.0.0.1:7650"

VERSION = "1"
"""The API's version, the first element of every path."""

HEADER_VERSION = "Fylgja-Api-Version"
HEADER_VERSIONS = "Fylgja-Api-Versions"
HEADER_BUILD = "Fylgja-Build"

DIAL_TIMEOUT_S = 5.0
"""The connection's bound, `api.DialTimeout`. The answer has none: a run's answer, or a
create's read and compile before its start, takes as long as it takes, and the flow's own
timeout bounds it."""

MAX_FRAME_BYTES = 64 << 20
"""The longest frame of an answer this client reads, `api.MaxFrameBytes`."""

MAX_PROBLEM_BYTES = 64 << 10
"""What is read of a transport fault's body, `api.MaxProblemBytes`."""

POLL_S = 2.0
"""How often a detached run is read (R-08)."""

RENDER_TEXT = "text"

STATE_RUNNING = "running"
"""A run that has not closed, as run.read's run frame names it: that answer ends by EOF."""

RULE_API_UNREACHABLE = "api.unreachable"
RULE_API_TOKEN_REFUSED = "api.token.refused"
RULE_API_VERSION_UNKNOWN = "api.version.unknown"
RULE_API_TRANSFER_TOO_LARGE = "api.transfer.too_large"

_HOST_PORT = re.compile(r"^(?:\[[^\]]*\]|[^:/\[\]]*):([^:]*)$")


class CoreFailure(Exception):
    """A failure between this client and the server, as the command's own document: status
    error, exit 2, no step, its rule and words `internal/cli/failures.go`'s. No sentence names
    the token."""

    def __init__(self, rule: str, object: str, message: str):
        super().__init__(message)
        self.rule = rule
        self.object = object
        self.message = message

    def document(self, operation: str, subject: dict | None = None) -> Document:
        return rule_error_document(operation, subject, self.rule, self.object, self.message)


@dataclass(frozen=True)
class RunRef:
    """A run's identity. A start frame names the workflow alone; run.read's run frame adds
    the run's state."""

    workflow_id: str
    run_id: str = ""
    state: str = ""

    def __str__(self) -> str:
        return f"{self.workflow_id} {self.run_id}".rstrip()


@dataclass(frozen=True)
class File:
    """One file crossing whole: the path the operator gave, or its path inside a bundle, and
    its bytes."""

    path: str
    data: bytes

    def wire(self) -> dict:
        return {"path": self.path, "data": base64.b64encode(self.data).decode("ascii")}


@dataclass
class Answer:
    """An answer read to its end: its frames by kind, in their order. `document` is None only
    for a run.read of a running run, which ends by EOF; `out` are the lines for stdout, each
    without its newline, and `err` those for stderr."""

    operation: str
    build: str = ""
    start: str = ""
    run: RunRef | None = None
    events: list[dict] = field(default_factory=list)
    out: list[str] = field(default_factory=list)
    err: list[str] = field(default_factory=list)
    files: list[File] = field(default_factory=list)
    document: Document | None = None
    text: str = ""

    @property
    def running(self) -> bool:
        return self.run is not None and self.run.state == STATE_RUNNING


def _without_userinfo(address: str) -> str:
    """The address with anything before an @ in its authority left out: a URL's user and
    password, which no sentence names (`withoutUserinfo`)."""
    scheme, sep, rest = address.partition("://")
    if not sep:
        scheme, rest = "", address
    else:
        scheme += sep
    cut = min([i for i in (rest.find(c) for c in "/?#") if i >= 0], default=len(rest))
    return scheme + rest[:cut].rpartition("@")[2] + rest[cut:]


def _control(s: str) -> bool:
    return any(ord(c) < 0x20 or ord(c) == 0x7F for c in s)


def _shown(address: str) -> str:
    """An address as a sentence names it: without a URL's user or password, and quoted when
    it holds a control character (`shownAddress`)."""
    shown = _without_userinfo(address)
    return json.dumps(shown) if _control(shown) else shown


def _decimal_port(port: str) -> bool:
    return port.isascii() and port.isdigit() and 1 <= int(port) <= 65535


def unreachable(shown: str, cause: str) -> CoreFailure:
    """api.unreachable as `failures.go` words an *api.Unreachable: nothing answers at the
    address, what answers is not the API, or the address is none a request can be sent to."""
    return CoreFailure(RULE_API_UNREACHABLE, shown,
                       f"the API at {shown} cannot be reached: {cause}; fylgja serve runs on the lab host")


def base_url(address: str) -> str:
    """The server's root from host:port or a URL, refused whole before anything is dialled as
    `baseURL` refuses it (api.unreachable): a user or password, a control character, a
    host:port with no port or a path, a URL with no host, a query or a fragment."""
    shown = _shown(address)
    takes = f"{ENV_ADDRESS} takes host:port or an http:// or https:// URL"
    if _without_userinfo(address) != address:
        raise unreachable(shown, f"{shown} names a user or password, which {ENV_ADDRESS} never carries: it takes "
                                 "host:port or an http:// or https:// URL without one")
    control = _control(address)
    if address.startswith(("http://", "https://")):
        u = urlsplit(address)
        try:
            port = u.port
        except ValueError:
            port = -1
        if control or not u.hostname or u.query or u.fragment or u.username is not None or port == -1:
            raise unreachable(shown, f"{shown} is not a URL of a server: {takes}")
        return address.rstrip("/")
    m = _HOST_PORT.match(address)
    if control or m is None or not _decimal_port(m.group(1)):
        raise unreachable(shown, f"{shown} is not host:port: {takes}")
    return "http://" + address


def path(operation: str) -> str:
    """An operation's path under the version: /v1/twin/create for twin.create."""
    return f"/v{VERSION}/" + operation.replace(".", "/")


class Core:
    """The client of one server, from the environment `environ` (the process's by default).
    `transport` is httpx's, a test's stub server's or a mock; `sleep` the poll's wait."""

    def __init__(self, environ: Mapping[str, str] | None = None, *, transport: httpx.BaseTransport | None = None,
                 sleep: Callable[[float], None] = time.sleep, poll_s: float = POLL_S,
                 max_frame_bytes: int = MAX_FRAME_BYTES):
        self._environ = os.environ if environ is None else environ
        self._transport = transport
        self._sleep = sleep
        self.poll_s = poll_s
        self.max_frame_bytes = max_frame_bytes
        self.address = self._environ.get(ENV_ADDRESS) or DEFAULT_ADDRESS

    def __repr__(self) -> str:
        return f"Core(address={_shown(self.address)!r})"

    # The token, read where a request is built and nowhere else.

    def _token(self) -> bytes:
        token = self._environ.get(ENV_TOKEN, "")
        if not token:
            raise CoreFailure(RULE_API_TOKEN_REFUSED, ENV_TOKEN, f"{ENV_TOKEN} is not set; a client sends the API's "
                              "token with every request, and nothing was sent")
        raw = token.encode("utf-8", "surrogateescape")
        if any((b < 0x20 and b != 0x09) or b == 0x7F for b in raw):
            raise CoreFailure(RULE_API_TOKEN_REFUSED, ENV_TOKEN, f"{ENV_TOKEN} holds a character a request header "
                              "cannot carry, such as a carriage return; nothing was sent")
        if raw[-1:] in (b" ", b"\t"):
            raise CoreFailure(RULE_API_TOKEN_REFUSED, ENV_TOKEN, f"{ENV_TOKEN} ends in a space or a tab, which a "
                              "request header cannot carry; nothing was sent")
        return raw

    # The transport.

    def call(self, operation: str, args: dict | None = None, files=(), render: str = "",
             on_out: Callable[[str], None] | None = None) -> Answer:
        """Sends one operation's request and reads its answer to its end: the document, or the
        EOF a running run.read ends by. `on_out` takes each out line as it arrives."""
        token = self._token()
        url = base_url(self.address) + path(operation)
        body: dict = {}
        if render:
            body["render"] = render
        if args:
            body["args"] = args
        files = list(files)
        if files:
            body["files"] = [f.wire() for f in files]
        # No Expect: 100-continue, which the Go client sends so a refused token costs no
        # upload: httpx sends the body whatever the server answers first.
        headers = [(b"Authorization", b"Bearer " + token), (b"Content-Type", b"application/json")]
        shown = _shown(self.address)
        timeout = httpx.Timeout(None, connect=DIAL_TIMEOUT_S, pool=DIAL_TIMEOUT_S)
        try:
            with (httpx.Client(transport=self._transport, trust_env=False, follow_redirects=False,
                               timeout=timeout) as http,
                  http.stream("POST", url, content=json.dumps(body).encode(), headers=headers) as resp):
                if resp.status_code != 200:
                    raise self._fault(operation, resp)
                if not resp.headers.get(HEADER_VERSION):
                    raise unreachable(shown, f"what answers there is not the API: its answer names no {HEADER_VERSION}")
                answer = Answer(operation, build=resp.headers.get(HEADER_BUILD, ""))
                self._frames(resp, answer, on_out)
                return answer
        except httpx.TransportError as e:
            raise unreachable(shown, _cause(e)) from None

    def _fault(self, operation: str, resp: httpx.Response) -> CoreFailure:
        """The failure a status other than the answer's is (`Client.fault`)."""
        shown = _shown(self.address)
        status = resp.status_code
        if status == 401:
            return CoreFailure(RULE_API_TOKEN_REFUSED, shown, f"the API at {shown} refused this client's token; "
                               f"{ENV_TOKEN} must be the token fylgja serve was started with")
        if status == 404:
            served = resp.headers.get(HEADER_VERSIONS, "")
            if served and VERSION not in (v.strip() for v in served.split(",")):
                return CoreFailure(RULE_API_VERSION_UNKNOWN, shown, f"the API at {shown} serves version {served}; "
                                   f"this client speaks version {VERSION}")
        if status == 413:
            message = _problem(resp) or ("the request is larger than this server's transfer bound; nothing was read "
                                         "or filed")
            return CoreFailure(RULE_API_TRANSFER_TOO_LARGE, operation, message)
        if status == 400:
            return CoreFailure(RULE_OPERATION_FAILED, operation,
                               f"the API at {shown} could not read this request: {_problem(resp)}")
        return CoreFailure(RULE_OPERATION_FAILED, operation,
                           f"the API at {shown} answered {status} {resp.reason_phrase}".rstrip())

    def _frames(self, resp: httpx.Response, answer: Answer, on_out) -> None:
        """Reads the answer's frames into answer, one line each, as `Answer.Next` reads them."""
        shown = _shown(self.address)
        held = b""

        def cut(cause: str) -> CoreFailure:
            return CoreFailure(RULE_API_UNREACHABLE, shown, _stopped(shown, cause, answer))

        try:
            for chunk in resp.iter_raw():
                held += chunk
                while (i := held.find(b"\n")) >= 0:
                    line, held = held[:i], held[i + 1:]
                    if len(line) > self.max_frame_bytes:
                        raise self._too_large(answer.operation)
                    if self._frame(line, answer, on_out, cut):
                        return
                if len(held) > self.max_frame_bytes:
                    raise self._too_large(answer.operation)
        except httpx.TransportError as e:
            raise cut(_cause(e)) from None
        if held.strip():
            raise cut("unexpected EOF")
        if not answer.running:
            raise cut("unexpected EOF")

    def _too_large(self, operation: str) -> CoreFailure:
        shown = _shown(self.address)
        return CoreFailure(RULE_API_TRANSFER_TOO_LARGE, operation,
                           f"the API at {shown} sent an answer frame larger than this client's bound of "
                           f"{self.max_frame_bytes} bytes ({self.max_frame_bytes >> 20} MiB); nothing was written on "
                           "this machine")

    @staticmethod
    def _frame(line: bytes, answer: Answer, on_out, cut) -> bool:
        """Files one frame into answer; True at the document, the answer's last. A frame of a
        kind this client does not know is passed over."""
        if not line.strip():
            return False
        try:
            f = json.loads(line)
            if not isinstance(f, dict):
                raise ValueError("not an object")
        except ValueError as e:
            raise cut(f"a line of the answer is not a frame: {e}") from None
        if f.get("document"):
            answer.document = Document.from_dict(f["document"])
            answer.text = f.get("text", "")
            return True
        if f.get("out"):
            for text in f["out"].splitlines():
                answer.out.append(text)
                if on_out is not None:
                    on_out(text)
        elif f.get("err"):
            answer.err.extend(f["err"].splitlines())
        elif f.get("start") is not None:
            answer.start = f["start"].get("workflow_id", "")
        elif f.get("run") is not None:
            r = f["run"]
            answer.run = RunRef(r.get("workflow_id", ""), r.get("run_id", ""), r.get("state", ""))
        elif f.get("event") is not None:
            answer.events.append(f["event"])
        elif f.get("files") is not None:
            answer.files.extend(File(x["path"], base64.b64decode(x.get("data") or "")) for x in f["files"])
        return False

    # The operations.

    def start(self, operation: str, args: dict | None = None, files=(),
              on_out: Callable[[str], None] | None = None) -> Answer:
        """Starts a run under `detach` (twin.create, twin.provision, twin.step, twin.destroy):
        the answer ends at the run's identity, `answer.run`, with the document run.detached
        names it in; a run the core refused to start has no identity, and its document says
        why. The out lines before the start (a create's snapshot and bundle) reach `on_out`."""
        return self.call(operation, {**(args or {}), "detach": True}, files, RENDER_TEXT, on_out)

    def read(self, workflow_id: str, run_id: str = "", render: bool = True,
             on_out: Callable[[str], None] | None = None) -> Answer:
        """Reads a run by its identity every `poll_s` until its answer carries its document:
        the run's own, operation run.read, or run.unknown's. Each read replays the run's
        lines from its start, so `on_out` takes only the lines no earlier read gave it, and
        never the line naming the run's state, which every read writes first."""
        printed = 0
        while True:
            answer = self.call(OP_RUN_READ, _identity(workflow_id, run_id), render=RENDER_TEXT if render else "")
            if answer.run is not None:
                run_id = answer.run.run_id
                note = f"run {answer.run.workflow_id} {answer.run.run_id}: {answer.run.state}"
                answer.out = [line for line in answer.out if line != note]
            if on_out is not None:
                for line in answer.out[printed:]:
                    on_out(line)
            printed = max(printed, len(answer.out))
            if answer.document is not None:
                return answer
            self._sleep(self.poll_s)

    def run(self, operation: str, args: dict | None = None, files=(),
            on_out: Callable[[str], None] | None = None) -> Answer:
        """Starts a run detached and reads it to its document; a run the core refused to start
        answers the refusal."""
        started = self.start(operation, args, files, on_out)
        if started.run is None or not started.run.run_id:
            return started
        return self.read(started.run.workflow_id, started.run.run_id, on_out=on_out)

    def interrupt(self, workflow_id: str, run_id: str = "") -> Document:
        """Asks the run to cancel, as a stream's first interrupt asks it: run.cancel.requested,
        run.ended or run.unknown."""
        return self.call(OP_RUN_INTERRUPT, _identity(workflow_id, run_id)).document

    def show(self) -> Document:
        """twin.show's document: the record, the host and the runs in flight under `show`."""
        return self.call(OP_TWIN_SHOW).document

    def compile(self, snapshot: str, files=(), out: str = "") -> Answer:
        """twin.compile of a snapshot id, or of the path of a snapshot file `files` carries: the
        bundle's files under `answer.files`, and the document."""
        args = {"snapshot": snapshot}
        if out:
            args["out"] = out
        return self.call(OP_COMPILE, args, files)

    def diff(self, from_: str, to: str, files=()) -> Document:
        """twin.diff, the step between two snapshots, each an id or the path of a file `files`
        carries: its `step` block, or `unchanged`."""
        return self.call(OP_TWIN_DIFF, {"from": from_, "to": to}, files).document

    def verify(self, wait: str = "", on_out: Callable[[str], None] | None = None) -> Answer:
        """twin.verify of the twin standing, waited for `wait` when given."""
        return self.call(OP_TWIN_VERIFY, {"wait": wait} if wait else None, render=RENDER_TEXT, on_out=on_out)

    def destroy(self, on_out: Callable[[str], None] | None = None) -> Answer:
        """twin.destroy, detached and read to its document."""
        return self.run(OP_TWIN_DESTROY, on_out=on_out)

    def dry_run(self, operation: str, args: dict | None = None, files=(),
                on_out: Callable[[str], None] | None = None) -> Answer:
        """A run's dry run (twin.create, twin.provision, twin.step): it starts nothing, so it
        is never detached, and its answer is its lines and its document."""
        return self.call(operation, {**(args or {}), "dry_run": True}, files, RENDER_TEXT, on_out)


def _identity(workflow_id: str, run_id: str) -> dict:
    args = {"workflow_id": workflow_id}
    if run_id:
        args["run_id"] = run_id
    return args


def _cause(e: httpx.TransportError) -> str:
    """A transport error's own words, which name no URL."""
    return str(e) or type(e).__name__


def _problem(resp: httpx.Response) -> str:
    """A fault's body's message, as much of it as a problem can be."""
    body = b""
    for chunk in resp.iter_raw():
        body += chunk
        if len(body) >= MAX_PROBLEM_BYTES:
            break
    try:
        p = json.loads(body[:MAX_PROBLEM_BYTES])
    except ValueError:
        return ""
    return p.get("message", "") if isinstance(p, dict) else ""


def _stopped(address: str, cause: str, answer: Answer) -> str:
    """The answer that ended before its document, and what that leaves of a run
    (`stoppedAnswering`): none before the server began to start one, one that may have been
    started once it had, and the run it named once it had named it, which goes on. This
    client never interrupts a run's stream, so none was asked to cancel."""
    message = f"the API at {address} stopped answering before the command ended: {cause}"
    if answer.run is not None and answer.run.run_id:
        message += (f"; run {answer.run.workflow_id} {answer.run.run_id} was not cancelled and goes on: fylgja twin "
                    "show names it")
    elif answer.start:
        message += "; a run may have been started and was not cancelled: fylgja twin show names it"
    return message
