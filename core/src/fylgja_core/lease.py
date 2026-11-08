"""The Lease: one core at a time reconciles a store (D-061, D-062).

On a cluster a store's directory lock does not reach an object store, so the core holds a
`coordination.k8s.io/v1` Lease, written here over lightkube, which has no leader election
(D-064). Its holder is the pod's name (`identity()`), its duration `DURATION_S`, renewed every
`RENEW_S`.

**Taking it.** A Lease that does not exist is created; one no one holds (its holder empty), or one
held under this process's own name (the kubelet restarted the container), is taken at once. One
held by another is judged by this process's own clock, never by the Lease's times, so two pods'
clocks need not agree: a record (its holder and `renewTime`) seen unchanged for `DURATION_S`,
counted from when the read that first saw it answered, is taken, replaced at the
`resourceVersion` read. The holder's renewal was sent before that answer, and a holder stops at
the duration's end, so a record unchanged that long is one its holder has stopped holding.

**Losing it.** The deadline is `DURATION_S` after the last renewal that succeeded was sent. Each
renewal is judged against it before it is written and bounded by it, and so is the sleep before
it, so a holder that cannot renew stops at the deadline, never later: the duration is the promise
made to the next holder. Each renewal is sent `RENEW_S` after the one before it was sent, at once
where that one took as long (unanswered, cut at its bound), so one renewal failing, answered or
not, costs nothing: the next is sent with `RENEW_S` left. A renewal answered `Conflict` reads
the Lease back: another holder named there is `Lost` at once; this one named there goes on at the
version read. A renewal answered 409 never landed, so a Lease read back as its own is a write of an
earlier renewal's that landed and went unanswered (cut at its bound, failed in transport); a waiter
counts from that landing, after that write's send. So the Lease is renewed as of the send of the
first renewal since the last success whose write may have landed unanswered, the earliest it can
be, and as of nothing where there is none (every renewal since was answered, or refused, and the
Lease was written under this name by another hand). A Lease deleted or emptied by another hand
under its holder (a renewal's replace finding no Lease, or a `Conflict` reading back none or no
holder) is `Lost` at once too, since a waiter creates a Lease that is not there, and takes one no
one holds, at once.

**The holder's clock** is `time.monotonic`, which on Linux does not count the time a host is
suspended. A process stalled past its deadline, its event loop held, stops with no write; a host
suspended past it wakes holding the Lease by its own clock, and the refusal of its next renewal
stops it: a 409, the Lease read back held by another or by no one, or a 404, the Lease deleted.
That comes within three times `RENEW_S` of waking, since the sleep before that renewal, its write
and a 409's read-back are each bounded by `RENEW_S`.

What may name the API server's address, a failure's text, is never in a message or a log line:
a failure is named by its type and, where it has one, its HTTP status.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, NoReturn, Protocol

import httpx2
from lightkube import ApiError, AsyncClient, codecs
from lightkube.models.coordination_v1 import LeaseSpec
from lightkube.resources.coordination_v1 import Lease as LeaseModel

from fylgja_core import clock, kubeapi, logs

DURATION_S = 15
"""The Lease's duration, `leaseDurationSeconds`: how long a holder that cannot renew holds it."""

RENEW_S = 5
"""How often a holder renews it, and how often a process waiting for it reads it."""

RULE_LOST = "lease.lost"
"""The rule the server stops under when the Lease is lost (docs/rules.md)."""

FAILURES = (ApiError, httpx2.HTTPError, OSError, TimeoutError)
"""What a call through lightkube raises when the API refuses, the transport fails or its budget
runs out; `ApiError` is an `httpx2.HTTPError`, named for the reader."""

_log = logging.getLogger("fylgja.lease")


class Lost(Exception):
    """The Lease is no longer this process's: its message names the other holder, or says no
    renewal succeeded within the duration."""


class Refused(Exception):
    """The Lease cannot be read or written, and waiting will not change it: the API refused the
    service account (401, 403), a write found no Lease or no namespace (404), or no client could be
    made, `variable` then naming the variable at fault (`kubeapi.Unconfigured`). `status` is the
    API's status code, where it answered one."""

    def __init__(self, message: str, *, variable: str | None = None, status: int | None = None) -> None:
        super().__init__(message)
        self.variable = variable
        self.status = status


class Conflict(Exception):
    """A write found the Lease already there (a create) or moved since it was read (a replace)."""


class Unreachable(Exception):
    """The API did not answer, or answered with a status waiting may change. `failure` is the type
    of what failed and `status` the API's status code, where it answered one; neither is the
    failure's text, which can name the API server's address."""

    def __init__(self, message: str, *, failure: str | None = None, status: int | None = None) -> None:
        super().__init__(message)
        self.failure = failure or type(self).__name__
        self.status = status


@dataclass(frozen=True)
class Record:
    """The Lease as read: `holder` is `""` for a Lease no one holds; `renewed` (its `renewTime`)
    and `version` (its `resourceVersion`) are opaque, compared for equality alone."""

    holder: str
    renewed: str
    transitions: int
    version: str


class Api(Protocol):
    """The Lease's one object, read and written whole."""

    @property
    def name(self) -> str:
        """The Lease's name."""
        ...

    async def read(self) -> Record | None:
        """The Lease, or None when there is none."""
        ...

    async def write(self, holder: str, transitions: int, version: str | None) -> Record:
        """The Lease written held by `holder` (`""` for none) with `transitions`: a create when
        `version` is None, else a replace at it; `Conflict` when it exists or has moved, and
        `Refused` with `status` 404 for a replace where there is no Lease."""
        ...

    async def close(self) -> None:
        """Close what the API holds open."""
        ...


class Lease:
    """The Lease `api` holds, taken and held under `identity`. `monotonic` and `sleep` are the
    clock it judges and waits by; `on_wait` is called once for each holder it waits for."""

    def __init__(
        self,
        api: Api,
        identity: str,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        on_wait: Callable[[str], None] | None = None,
        renew_s: float = RENEW_S,
        duration_s: float = DURATION_S,
    ) -> None:
        self.identity = identity
        self._api = api
        self._monotonic = monotonic
        self._sleep = sleep
        self._on_wait = on_wait
        self._renew_s = renew_s
        self._duration_s = duration_s
        self._held: Record | None = None
        self._renewed_at = 0.0  # when the last write that succeeded was sent: the deadline counts from it
        self._sent_at = 0.0  # when the last write was sent: the next renewal is sent `renew_s` after it
        self._unanswered_at: float | None = None  # the first renewal's send since the last success that may have landed

    @property
    def name(self) -> str:
        """The Lease's name."""
        return self._api.name

    async def acquire(self) -> None:
        """Return holding the Lease, however long another holds it. A read or a write that the
        API does not answer is tried again every `renew_s`, said once at WARNING and once at INFO
        when a read answers again. A take answered `Conflict`, or finding the Lease deleted since
        it was read (`Refused` with `status` 404), reads it again: at once the first time, and
        from the second in a row (no holder waited for between them) after `renew_s`, said once at
        WARNING, so an API that refuses every take (a proxy, a webhook) is not asked at its own
        speed; any other `Refused` (401, 403) is raised at once."""
        seen: tuple[str, str] | None = None  # the holder and renewal of the record waited on
        since = 0.0  # when a read first saw it
        waited: str | None = None
        failing = False
        moved = 0  # takes in a row that found the Lease written or deleted since it was read
        while True:
            try:
                async with asyncio.timeout(self._renew_s):
                    record = await self._api.read()
            except (Unreachable, TimeoutError) as e:
                if not failing:
                    self._unanswered(e)
                failing = True
                await self._sleep(self._renew_s)
                continue
            if failing:
                _log.info("the Lease %s answers again", self.name, **logs.fields(lease=self.name))
                failing = False
            now = self._monotonic()
            transitions: int
            version: str | None
            if record is None:
                transitions, version = 0, None
            elif record.holder == self.identity:
                transitions, version = record.transitions, record.version
            elif record.holder == "":
                transitions, version = record.transitions + 1, record.version
            else:
                if (record.holder, record.renewed) != seen:
                    seen, since = (record.holder, record.renewed), now
                    if record.holder != waited:
                        waited = record.holder
                        if self._on_wait is not None:
                            self._on_wait(record.holder)
                if now - since < self._duration_s:
                    moved = 0
                    await self._sleep(min(self._renew_s, since + self._duration_s - now))
                    continue
                transitions, version = record.transitions + 1, record.version
            sent = self._monotonic()
            try:
                async with asyncio.timeout(self._renew_s):
                    answered = await self._api.write(self.identity, transitions, version)
            except (Conflict, Refused) as e:
                # Another wrote it since it was read, or deleted it (a 404 on a replace: it is created
                # next); a create refused 404 (no such namespace) will not change by waiting.
                if isinstance(e, Refused) and not (version is not None and e.status == 404):
                    raise
                moved += 1
                if moved == 2:
                    _log.warning("the Lease %s was written or deleted by another under two takes in a row: taking it "
                                 "again every %gs", self.name, self._renew_s, **logs.fields(lease=self.name))
                if moved >= 2:
                    await self._sleep(self._renew_s)
                continue
            except (Unreachable, TimeoutError) as e:
                if not failing:
                    self._unanswered(e)
                failing = True
                await self._sleep(self._renew_s)
                continue
            self._held, self._renewed_at, self._sent_at, self._unanswered_at = answered, sent, sent, None
            return

    def _unanswered(self, error: Exception) -> None:
        """The WARNING at the first of a run of calls `acquire` tries again."""
        _log.warning("the Lease %s cannot be read or written (%s): trying again every %gs", self.name,
                     _failure(error), self._renew_s, **logs.fields(lease=self.name, failure=_failure(error)))

    async def renew(self) -> None:
        """One renewal, or `Lost`: when the deadline has passed, before anything is written; when
        a renewal that failed leaves it passed; when its replace finds no Lease; or when one
        answered `Conflict` reads back another holder, no holder or no Lease. One answered
        `Conflict` that reads back this holder goes on at the version read, renewed as of the first
        renewal since the last success that may have landed unanswered, where there is one
        (`_read_back`). A renewal unanswered, cut at its bound or refused otherwise (401, 403) has
        failed, and one that failed with time left returns, said at WARNING."""
        held = self._held
        if held is None:
            raise Lost(f"the Lease {self.name} is not held")
        deadline = self._renewed_at + self._duration_s
        sent = self._monotonic()
        if sent >= deadline:
            self._lost()
        self._sent_at = sent
        try:
            async with asyncio.timeout(min(self._renew_s, deadline - sent)):
                self._held = await self._api.write(self.identity, held.transitions, held.version)
            self._renewed_at, self._unanswered_at = sent, None
            return
        except Conflict:
            failure = await self._read_back(deadline)
            if failure is None:  # read back as its own
                return
        except Refused as e:  # refused by the API: never applied
            if e.status == 404:
                self._lost(f"the Lease {self.name} was deleted by another hand")
            failure = _failure(e)
        except (Unreachable, TimeoutError) as e:
            failure = _failure(e)
            # It may have landed, its answer lost. The first such send is kept, never the latest: the write
            # that landed may be the earliest of them, and a waiter counts from its landing.
            if self._unanswered_at is None:
                self._unanswered_at = sent
        now = self._monotonic()
        if now >= deadline:
            self._lost()
        _log.warning("the Lease %s: a renewal failed (%s); it is lost in %.1fs unless one succeeds", self.name,
                     failure, deadline - now, **logs.fields(lease=self.name, failure=failure))

    async def _read_back(self, deadline: float) -> str | None:
        """After a renewal's `Conflict`, the Lease read back within the deadline: this one there,
        the version read is held, and the Lease renewed as of the send of the first renewal since
        the last success that may have landed unanswered, where there is one: the write that landed
        was sent then or later, and a waiter counts from its landing; the Conflicted renewal itself
        never landed, so it is credited nothing. Another holder there, no holder or no Lease,
        `Lost`. What failed, when the read did."""
        try:
            async with asyncio.timeout(max(0.0, min(self._renew_s, deadline - self._monotonic()))):
                record = await self._api.read()
        except (Unreachable, Refused, TimeoutError) as e:
            return f"Conflict, then {_failure(e)}"
        if record is None:
            self._lost(f"the Lease {self.name} was deleted by another hand")
        if not record.holder:
            self._lost(f"the Lease {self.name} was released by another hand")
        if record.holder != self.identity:
            self._lost(f"the Lease {self.name} is held by {record.holder}")
        self._held = record
        if self._unanswered_at is not None:
            self._renewed_at, self._unanswered_at = self._unanswered_at, None
        return None

    def _lost(self, why: str | None = None) -> NoReturn:
        """`Lost`, the Lease forgotten, so nothing is released: `why`, or no renewal succeeded
        within the duration."""
        self._held = None
        raise Lost(why or f"no renewal succeeded within {self._duration_s:g} s")

    async def hold(self) -> None:
        """Renew the Lease every `renew_s` for ever, until it is `Lost`: each renewal is sent
        `renew_s` after the one before was sent, at once where that one took as long (cut at its
        bound, unanswered), and the sleep before it ends at the deadline at the latest."""
        while True:
            now = self._monotonic()
            wait = min(max(0.0, self._sent_at + self._renew_s - now), self._renewed_at + self._duration_s - now)
            if wait > 0:
                await self._sleep(wait)
            await self.renew()

    async def release(self) -> bool:
        """Write the Lease held by no one, at the version held, so the next holder takes it at
        once; True when it was written. Nothing held (never taken, or lost), nothing is written.
        It never raises: a failure is one WARNING, and the next holder takes it at the duration's
        end."""
        held, self._held = self._held, None
        if held is None:
            return False
        try:
            async with asyncio.timeout(self._renew_s):
                await self._api.write("", held.transitions, held.version)
        except Exception as e:  # any failure: a release is the last thing a stopping core does
            _log.warning("the Lease %s was not released (%s): it is taken %gs after its last renewal", self.name,
                         _failure(e), self._duration_s, **logs.fields(lease=self.name, failure=_failure(e)))
            return False
        return True

    async def close(self) -> None:
        """Close the Lease's API."""
        await self._api.close()


def _failure(error: Exception) -> str:
    """A failure as a message names it: its type, or the type it stands for, and its status code
    where it has one; never its text."""
    named = getattr(error, "failure", None) or type(error).__name__
    status = getattr(error, "status", None)
    return named if status is None else f"{named}, status {status}"


class KubeLeases:
    """`Api` over lightkube: the Lease `name` in `namespace`, None for the client's default (the
    service account's in a pod, the kubeconfig context's off the cluster).

    The client is made by `kubeapi.client()` on first use, and `close()` forgets it, so each event
    loop that uses it gets a client of its own. Every write is a whole Lease built from a mapping,
    never an answered object changed: the holder, `leaseDurationSeconds` `DURATION_S`, `renewTime`
    now (`clock.now()`, a whole second written a microsecond later), the transitions, and for a
    replace the `resourceVersion`; `acquireTime` is set when a write changes the holder and sent
    the same on each renewal after it, kept in this process alone, and none is written with no
    holder. A 409 is `Conflict`; a 404 on a read is None; 401, 403, a 404 on a write and a client
    that cannot be made are `Refused`; any other status, a transport failure and a timeout are
    `Unreachable`."""

    def __init__(self, name: str, namespace: str | None = None) -> None:
        self.name = name
        self.namespace = namespace
        self._client: AsyncClient | None = None
        self._acquired: tuple[str, str] | None = None  # the holder this process last wrote, and since when

    async def read(self) -> Record | None:
        client = self._reached()
        try:
            model = await client.get(LeaseModel, self.name, namespace=self.namespace)
        except FAILURES as e:
            if _status(e) == 404:
                return None
            raise self._failed("read", e) from None
        record = _record(model)
        if self._acquired is not None and record.holder != self._acquired[0]:
            self._acquired = None
        return record

    async def write(self, holder: str, transitions: int, version: str | None) -> Record:
        client = self._reached()
        now = _micro_time(clock.now())
        spec: dict[str, Any] = {"holderIdentity": holder, "leaseDurationSeconds": DURATION_S, "renewTime": now,
                                "leaseTransitions": transitions}
        if not holder:
            self._acquired = None
        else:
            if self._acquired is None or self._acquired[0] != holder:
                self._acquired = (holder, now)
            spec["acquireTime"] = self._acquired[1]
        metadata: dict[str, Any] = {"name": self.name}
        if self.namespace is not None:
            metadata["namespace"] = self.namespace
        if version is not None:
            metadata["resourceVersion"] = version
        obj = codecs.from_dict({"apiVersion": "coordination.k8s.io/v1", "kind": "Lease", "metadata": metadata,
                                "spec": spec})
        assert isinstance(obj, LeaseModel)
        call = "create" if version is None else "replace"
        try:
            if version is None:
                model = await client.create(obj)
            else:
                model = await client.replace(obj)
        except FAILURES as e:
            if _status(e) == 409:
                raise Conflict(f"{call} Lease {self._named()}: 409") from None
            raise self._failed(call, e) from None
        return _record(model)

    async def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await client.close()

    def _reached(self) -> AsyncClient:
        if self._client is None:
            try:
                self._client = kubeapi.client()
            except kubeapi.Unconfigured as e:
                raise Refused(str(e), variable=e.variable) from None
        return self._client

    def _named(self) -> str:
        return f"{self.namespace}/{self.name}" if self.namespace else self.name

    def _failed(self, call: str, error: Exception) -> Refused | Unreachable:
        """The failure `call` raised as the Lease reads it: its status code and the API's reason,
        or its type, never its text nor the API's message."""
        code = _status(error)
        if code in (401, 403) or (code == 404 and call != "read"):
            return Refused(f"{call} Lease {self._named()}: {code} {_reason(error)}".rstrip(), status=code)
        failure = type(error).__name__
        shown = failure if code is None else f"{failure}, status {code}"
        return Unreachable(f"{call} Lease {self._named()}: {shown}", failure=failure, status=code)


def _status(error: Exception) -> int | None:
    """The API's status code `error` carries, None for a failure with no answer."""
    if isinstance(error, ApiError) and error.status.code is not None:
        return error.status.code
    if isinstance(error, httpx2.HTTPStatusError):
        return error.response.status_code
    return None


def _reason(error: Exception) -> str:
    """The API's reason for a refusal (`Forbidden`), a word of its Status or the HTTP reason."""
    if isinstance(error, ApiError) and error.status.reason:
        return error.status.reason
    if isinstance(error, httpx2.HTTPStatusError):
        return error.response.reason_phrase
    return ""


def _micro_time(now: str) -> str:
    """`clock.now()`'s time as a Lease's `MicroTime` may be written: a time at a whole second a
    microsecond later, since lightkube writes it with no fraction and the API refuses that (400:
    verified-facts.md, "A time at a whole second is refused", under lightkube 1.0.1 against
    k3s v1.37.1+k3s1)."""
    return now.replace(".000000Z", ".000001Z")


def _record(model: LeaseModel) -> Record:
    metadata, spec = model.metadata, model.spec or LeaseSpec()
    assert metadata is not None and metadata.resourceVersion, "the API answered a Lease with no resourceVersion"
    return Record(holder=spec.holderIdentity or "",
                  renewed=spec.renewTime.isoformat() if spec.renewTime is not None else "",
                  transitions=spec.leaseTransitions or 0, version=metadata.resourceVersion)


def identity() -> str:
    """This process's name as a holder: the host's name, which in a pod is the pod's (D-062).
    Two cores on one host share it, and the second takes the first's Lease at once, as held under
    its own name; in a pod each has a name of its own."""
    return socket.gethostname()
