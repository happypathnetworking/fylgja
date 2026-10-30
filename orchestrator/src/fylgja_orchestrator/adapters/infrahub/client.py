"""The adapter's connection to Infrahub (data-model §5; R-07), ported from
`internal/intent`'s client.go, at.go and errors.go.

Every request is a read: Fylgja never writes to Infrahub. The address and the credential
come from the process environment alone, never a file or a flag; the credential is sent as
`X-INFRAHUB-KEY` and never printed, logged or kept in an error.

GraphQL goes through `infrahub-sdk` 1.23.2's `execute_graphql`, the branch in the path
(`/graphql/<branch>`; a `?branch=` there answers for `main`). Two of the SDK's habits are
undone here, so the read sends what the Go reader sent:

- **`at` verbatim.** The SDK rewrites an `at` through its `Timestamp` into UTC with six
  fractional digits; the reader sends the operator's value as given, URL-encoded, and
  only when one was given: Infrahub filters `created_at <= at`, so an invented "now"
  hides whatever was written in its second (D-012, D-023). A value finer than the
  microsecond Infrahub honours is refused before any request (`intent.at.precision`).
- **The status.** The SDK's exceptions drop the HTTP status Infrahub answered with, and
  its words for a missing branch; a recorder keeps the last response so each failure says
  which status and which sentence, as the Go reader's did.

The schema endpoint is read first and with no `at`: it has no time axis and ignores one.
"""

import functools
import json
import os
import re
from dataclasses import dataclass
from urllib.parse import quote, urlencode

ENV_ADDRESS = "INFRAHUB_ADDRESS"
ENV_TOKEN = "INFRAHUB_API_TOKEN"

TIMEOUT_S = 60
"""Each request's bound, the Go reader's `http.Client` timeout."""

MAX_AT_FRACTION_DIGITS = 6
"""The precision Infrahub honours in an `at`: microseconds. Verified on 1.11.2: one to six
fractional digits are honoured exactly, a seventh and later digit truncated."""

RULE_AT_PRECISION = "intent.at.precision"

_AT_FRACTION = re.compile(r"\.([0-9]+)")
_OPERATION = re.compile(r"^\s*query\s+([_A-Za-z][_0-9A-Za-z]*)")

_RELOGIN_FAILURES = (AttributeError, TypeError, ValueError)
"""What the SDK's relogin hook raises on a 401 whose body it cannot read as it expects."""

DEFAULT_BRANCH = "(the default branch)"
"""What a default-branch read names in its failures, as a branch read names its (branch,
at): the reader asked no branch of its own."""


def operation_name(query: str) -> str | None:
    """The name of a query document's operation, its first definition's."""
    m = _OPERATION.match(query)
    return m.group(1) if m else None


def default_branch_at(at: str = "") -> str:
    """What a default-branch request asked: the default branch, at an instant when one was
    sent."""
    return f"(the default branch at {at})" if at else DEFAULT_BRANCH


class ConfigError(ValueError):
    """The environment or the arguments name no Infrahub to read: a variable unset, or no
    branch given. Its words never quote a value from the environment."""


class ClientError(Exception):
    """A request Infrahub refused or never answered, safe to print: the credential is never
    in it. `branch_missing` marks Infrahub saying the branch does not exist (a 400 from the
    schema endpoint, a 404 from GraphQL, each with `Branch: <b> not found.`), and
    `credential_refused` a 401 or 403, so a caller tells them from an unreachable Infrahub
    without reading the text."""

    def __init__(
        self, message: str, *, branch_missing: bool = False, credential_refused: bool = False, detail: str = ""
    ):
        super().__init__(message)
        self.branch_missing = branch_missing
        self.credential_refused = credential_refused
        # The cause alone, redacted, without what was asked or of which (branch, at): the
        # read groups the content fetches that failed alike by it, as the Go reader did.
        self.detail = detail or message


def at_fraction_digits(at: str) -> int:
    """The fractional-seconds digits of an instant, 0 when it carries none."""
    m = _AT_FRACTION.search(at)
    return len(m.group(1)) if m else 0


def check_at_precision(at: str) -> str:
    """The refusal of an `at` finer than Infrahub honours, empty when it is acceptable.

    Truncating it was rejected: the operator's `at` is recorded verbatim, and a coarsened
    one would no longer be what they asked for. Nothing else of the form is checked: the
    rest is Infrahub's, which accepts more forms than one parser here would."""
    digits = at_fraction_digits(at)
    if digits <= MAX_AT_FRACTION_DIGITS:
        return ""
    return (
        f"at {at} carries {digits} fractional digits; Infrahub honours at most {MAX_AT_FRACTION_DIGITS} "
        "(microseconds). Re-run with a coarser --at."
    )


@dataclass(frozen=True)
class Config:
    """One branch, optionally at one instant. `at` is empty when the operator supplied
    none, and is then never sent."""

    address: str
    token: str
    branch: str
    at: str = ""

    def __repr__(self) -> str:
        return f"Config(address={self.address!r}, branch={self.branch!r}, at={self.at!r})"

    def describe(self) -> str:
        """The (branch, at) a failure was about, built from what the operator gave."""
        if not self.at:
            return f"(branch {self.branch})"
        return f"(branch {self.branch}, at {self.at})"


def env_credentials(environ=None) -> tuple[str, str]:
    """The address, its trailing slashes trimmed, and the credential, from `environ` (the
    process's when None); ConfigError when either is unset."""
    environ = os.environ if environ is None else environ
    address = environ.get(ENV_ADDRESS, "").rstrip("/")
    token = environ.get(ENV_TOKEN, "")
    if not address:
        raise ConfigError(f"{ENV_ADDRESS} is not set")
    if not token:
        raise ConfigError(f"{ENV_TOKEN} is not set")
    return address, token


def from_env(branch: str, at: str = "") -> Config:
    address, token = env_credentials()
    if not branch:
        raise ConfigError("no branch given")
    return Config(address=address, token=token, branch=branch, at=at)


def startup_line(address: str, reader: str, version: str, scope: str) -> str:
    """What the adapter says before it reads: where, as which reader at which model
    version, under which scope. Never the token."""
    return f"fylgja-infrahub: reading {address} as {reader}@{version}, scope {scope}"


def redact(message: str, token: str) -> str:
    """message with the credential replaced: a transport error can carry a request dump,
    and an error's text is printed, logged and pasted into issues."""
    if not token:
        return message
    return message.replace(token, "<redacted>")


def not_found(branch: str) -> str:
    """Infrahub's sentence for a branch it does not have, from the schema endpoint (400)
    and GraphQL (404)."""
    return f"Branch: {branch} not found."


def unwrap_error_body(message: str) -> list[str]:
    """The messages inside a body that is itself an error document, `errors` holding
    strings (a missing branch's) or `{message}` objects (GraphQL's); [] for prose."""
    if not message.strip().startswith("{"):
        return []
    try:
        body = json.loads(message)
    except ValueError:
        return []
    errors = body.get("errors") if isinstance(body, dict) else None
    out = []
    for e in errors if isinstance(errors, list) else []:
        if isinstance(e, str):
            text = e.strip()
        elif isinstance(e, dict) and isinstance(e.get("message"), str):
            text = e["message"].strip()
        else:
            continue
        if text:
            out.append(text)
    return out


def explain_status(status: int, body: str) -> str:
    """A refusal in Infrahub's own words: `HTTP <code>: <its messages>`, or the status
    alone when the body is no error document (a proxy's page, say)."""
    msgs = unwrap_error_body(body)
    if not msgs:
        return f"HTTP {status}"
    return f"HTTP {status}: {'; '.join(msgs)}"


def auth_failure(status: int) -> str:
    """What to do about a refused credential, quoting nothing from the environment; empty
    for any other status."""
    if status == 401:
        return f"the credential in {ENV_TOKEN} was rejected by Infrahub"
    if status == 403:
        return f"the credential in {ENV_TOKEN} is not permitted to read this branch"
    return ""


class _Last:
    """The SDK's recorder hook, keeping the last response: the status and the body the
    SDK's exceptions leave out."""

    def __init__(self):
        self.response = None

    def record(self, response) -> None:
        self.response = response


@functools.cache
def _sdk():
    """The SDK, imported when a client is first built and not before: its import takes
    about 1.5 s, which nothing that only words a refusal or checks an `at` should pay."""
    import infrahub_sdk
    from infrahub_sdk import exceptions

    class SDKClient(infrahub_sdk.InfrahubClientSync):
        """The SDK's client with the GraphQL URL the Go reader built: the branch
        path-escaped, and `at` verbatim and form-encoded (a `+` in an offset as `%2B`),
        never re-parsed."""

        def _graphql_url(self, branch_name=None, at=None) -> str:
            url = f"{self.config.address}/graphql"
            if branch_name:
                url += "/" + quote(branch_name, safe="")
            if at:
                url += "?" + urlencode({"at": str(at)})
            return url

    return infrahub_sdk.Config, SDKClient, exceptions.Error, exceptions.GraphQLError


@functools.cache
def _sdk_settings(token: str):
    """The SDK's settings for a token, built once per process and copied per client with
    its own recorder and transport. Explicit, so no INFRAHUB_* variable the SDK's settings
    read moves them: the token alone authenticates, and nothing is retried, as the Go reader
    retried nothing. Building them reads the environment and a TLS context of the system's
    certificates, about 30 ms, which a command pays once and tier 1 once, not per client;
    a copy shares the context, which is made for sharing."""
    sdk_config = _sdk()[0]
    settings = sdk_config(
        api_token=token,
        username=None,
        password=None,
        timeout=TIMEOUT_S,
        retry_on_failure=False,
        echo_graphql_queries=False,
    )
    _ = settings.tls_context
    return settings


class Client:
    """Reads one branch, at one instant when `at` is given.

    `requester` replaces the SDK's transport (the SDK's own `sync_requester` hook), which
    tier 1 uses to answer from recorded documents."""

    def __init__(self, config: Config, requester=None):
        self.config = config
        self._last = _Last()
        self._requester = requester
        _, sdk_client, self._sdk_error, self._graphql_error = _sdk()
        settings = _sdk_settings(config.token).model_copy(
            update={"custom_recorder": self._last, "sync_requester": requester}
        )
        self._sdk = sdk_client(address=config.address, config=settings)

    @property
    def branch(self) -> str:
        return self.config.branch

    @property
    def at(self) -> str:
        return self.config.at

    def where(self, at: str | None = None) -> str:
        """What a failure was about: the (branch, at) this client reads."""
        return self.config.describe()

    def _error(self, what: str, detail: str, *, at=None, branch_missing=False, credential_refused=False) -> ClientError:
        message = redact(f"{what} {self.where(at)}: {detail}", self.config.token)
        return ClientError(
            message,
            branch_missing=branch_missing,
            credential_refused=credential_refused,
            detail=redact(detail, self.config.token),
        )

    def _relogin_failure(self, what: str, e: Exception, at=None) -> ClientError:
        """The SDK reads a 401's body as `{"errors": [{"message": …}]}` before anything
        else (its relogin hook), and fails on any other body, errors as strings or no JSON
        at all: the status recorded decides, as the Go reader's transport decided by the
        status alone."""
        response = self._last.response
        refused = auth_failure(response.status_code) if response is not None else ""
        if refused:
            return self._error(what, refused, at=at, credential_refused=True)
        return self._error(what, str(e), at=at)

    def get(self, path: str, what: str = "") -> tuple[bytes, int]:
        """A plain REST read with no `at` (the schema endpoint, which has none): the body
        and the status. A refused credential or an Infrahub that never answered raises,
        naming `what` was being read; any other status is the caller's."""
        what = what or f"reading {path}"
        self._last.response = None
        try:
            response = self._sdk._get(self.config.address + path)
        except self._sdk_error as e:
            raise self._error(what, str(e)) from None
        except _RELOGIN_FAILURES as e:
            raise self._relogin_failure(what, e) from None
        refused = auth_failure(response.status_code)
        if refused:
            raise self._error(what, refused, credential_refused=True)
        return response.content, response.status_code

    def get_at(self, path: str, what: str = "") -> tuple[bytes, int]:
        """`get` carrying the operator's `at`, for the REST endpoints with a time axis (the
        object store, which serves an artifact's content): every request of a pinned read
        is made at the one instant (Constitution VI). With no `at`, the request is the one
        `get` makes."""
        if self.config.at:
            path += ("&" if "?" in path else "?") + urlencode({"at": self.config.at})
        return self.get(path, what)

    def graphql(self, query: str, variables: dict | None = None, what: str = "querying", at: str | None = None) -> dict:
        """One GraphQL request on the branch, at `at` when given: its `data`. The request
        names its operation, the query's own name, as genqlient's did. A refusal raises
        ClientError in Infrahub's own words (`HTTP <code>: <its messages>` for any status but
        200, its messages alone for errors under 200), naming the (branch, at) asked for; a
        missing branch is GraphQL's 404 with Infrahub's sentence. `at` replaces the client's
        own for this request alone ("" sends none); None keeps it."""
        at = self.config.at if at is None else at
        self._last.response = None
        try:
            return self._sdk.execute_graphql(
                query=query,
                variables=variables,
                branch_name=self.config.branch,
                at=at or None,
                operation_name=operation_name(query),
            )
        except _RELOGIN_FAILURES as e:
            raise self._relogin_failure(what, e, at=at) from None
        except self._sdk_error as e:
            response = self._last.response
            if response is None:
                raise self._error(what, str(e), at=at) from None
            status, body = response.status_code, response.text
            refused = auth_failure(status)
            if refused:
                raise self._error(what, refused, at=at, credential_refused=True) from None
            if status == 200 and isinstance(e, self._graphql_error):
                msgs = [m.strip() for m in (err.get("message") for err in e.errors if isinstance(err, dict)) if m]
                raise self._error(what, "; ".join(m for m in msgs if m) or str(e), at=at) from None
            missing = (
                bool(self.config.branch)
                and status == 404
                and not_found(self.config.branch) in unwrap_error_body(body)
            )
            raise self._error(what, explain_status(status, body), at=at, branch_missing=missing) from None

    def schema_document(self) -> dict:
        """The branch's schema as `GET /api/schema?branch=` answers it, with no `at`.

        A failure fails the read: the envelope's schema_hash is required. A branch that does
        not exist is answered here first, 400 with Infrahub's sentence, which the error
        carries through the same redaction as any other body."""
        path = "/api/schema?" + urlencode({"branch": self.config.branch})
        what = "reading the schema"
        body, status = self.get(path, what)
        if status != 200:
            text = body.decode("utf-8", "replace")
            missing = status == 400 and not_found(self.config.branch) in unwrap_error_body(text)
            raise self._error(what, explain_status(status, text), branch_missing=missing)
        try:
            doc = json.loads(body)
        except ValueError as e:
            raise self._error(what, str(e)) from None
        if not isinstance(doc, dict) or not doc.get("main"):
            raise self._error(what, "no schema hash reported")
        return doc


class DefaultClient(Client):
    """Reads Infrahub's unnamed endpoints, `/graphql` and `/api/schema`, which answer for
    the default branch whatever it is called: the stages' proposed changes, the probe kind
    and the event log live on no branch of the operator's (D-045, D-048, D-064), so an
    installation whose default branch is not `main` needs nothing of this client. Nothing is
    pinned unless a request names an `at`. Its failures name `(the default branch)`, and it
    marks no branch missing: it asks for none."""

    def __init__(self, address: str, token: str, requester=None):
        super().__init__(Config(address=address, token=token, branch=""), requester)
        # execute_graphql reads `branch_name or default_branch`: with neither, _graphql_url
        # names no branch, so the request is POST /graphql.
        self._sdk.default_branch = ""

    def where(self, at: str | None = None) -> str:
        return default_branch_at(at or "")

    def on_branch(self, branch: str) -> Client:
        """A client of the same Infrahub reading a branch, unpinned: the event log's kinds
        are the branch schema's."""
        return Client(Config(address=self.config.address, token=self.config.token, branch=branch), self._requester)

    def schema_nodes(self, what: str = "reading the schema") -> list[dict]:
        """The default branch's node kinds as `GET /api/schema` lists them, each with its
        attributes and relationships: what a check of a kind of Fylgja's own reads."""
        body, status = self.get("/api/schema", what)
        if status != 200:
            raise self._error(what, explain_status(status, body.decode("utf-8", "replace")))
        try:
            doc = json.loads(body)
        except ValueError as e:
            raise self._error(what, str(e)) from None
        nodes = doc.get("nodes") if isinstance(doc, dict) else None
        return [n for n in nodes if isinstance(n, dict)] if isinstance(nodes, list) else []


def default_from_env(requester=None) -> DefaultClient:
    """A default-branch client from the variables a read uses, refusing alike when one is
    unset."""
    address, token = env_credentials()
    return DefaultClient(address, token, requester)
