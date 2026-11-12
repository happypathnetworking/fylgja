"""fylgja-core-server: one process serving API 1 and running the reconcile loop over one store
(D-023, D-039, D-042).

Everything it runs with comes from `FYLGJA_*` variables (`config`): the store, a directory held
locked for one core, or an object store (`s3://`, D-061) held for one core by the Lease
`FYLGJA_LEASE` names (D-062); the packages, loaded once; the driver, and for the clabernetes
driver clabernetes' namespace and the pod CIDR (`FYLGJA_CLABERNETES_NAMESPACE`,
`FYLGJA_POD_CIDR`); the token file; the address, which it binds itself before uvicorn serves on
it; and the certificate and key it ends TLS with (`FYLGJA_TLS_CERT`, `FYLGJA_TLS_KEY`, D-063),
without which it serves HTTP, which is for loopback. The clabernetes driver and the Lease reach
the cluster from the service account in a pod, and from `KUBECONFIG` off the cluster. The loop
starts and stops with the application's lifespan.

A start takes the settings, then the TLS pair, loaded once to check it; then, with
`FYLGJA_LEASE`, the Lease, before the store is opened (an object store's proof writes), the loop
started or the address bound: a core that waits for it says once whom it waits for, and holds
nothing. Then the application over the store, the address, and uvicorn. A start that fails after
the Lease is taken leaves it to this pod's next start, which holds it under the same name. No
renewal runs from the take to `_Server.startup`, while `build_app` opens the store (an object
store's proof is six requests), loads the packages and makes the driver: a start that takes
longer than the Lease's duration is lost, certainly, at that first renewal (read as 0.16 s on the
cluster, verified-facts.md). While it serves, `_Server` holds the Lease. Lost, the server stops
at once, since the duration is what the next holder waits: its one ERROR line; the loop's stop
begun, bounded by `LOST_STOP_S`; every connection dropped, those uvicorn does not hold yet (a TLS
handshake not done, a connection just accepted) among them, and each request in flight
cancelled, none answered and none given grace, so no request writes after the loss; nothing
released; exit status 1.

While it serves, SIGTERM and SIGINT are uvicorn's own to handle: as it begins to shut down, the
application's open streams are told to end, so a watch ends rather than waiting out `GRACE_S` to
be cut; then the loop stops, and the Lease is released. A second Ctrl-C forces the exit: landing
before uvicorn's shutdown has begun the loop's stop, it makes uvicorn skip it, and the server
stops the loop itself, within `LOST_STOP_S`, releasing the Lease only once it has; landing after,
uvicorn's own stop of the loop runs on, unbounded, and nothing is released until it ends.

The server owns its SIGTERM: in a container it is PID 1, which ignores a signal it has no handler
for. The console script (`entry`) has a handler within 0.2 s of the process's start, which exits 143
while this module is imported, nothing yet opened; `python -m fylgja_core.server` has none until
`main`'s. Before anything that can wait, `main` takes SIGTERM as Ctrl-C (`_on_sigterm`), so one
sent anywhere in the start, while it waits for the Lease or opens the store among it, ends the
start as Ctrl-C does, what was opened closed and a Lease held released, but in the windows below.
uvicorn puts back that handler once it has stopped and raises the signal it caught again, which
ends the run as Ctrl-C's does; and `main` exits 143 after a SIGTERM wherever that raise lands, and
where it is refused: in a pod on the cluster a process may not signal itself
(`_Server.capture_signals`). A start refused is one log line, naming the variable or the file at
fault and never a value.

Three windows are known and left, each failing safe, a Lease it leaves taken by the next holder
once its duration has passed: the interpreter's first 0.14-0.16 s in the image, before the console
script's handler, where SIGTERM is dropped (verified-facts.md); the take's end, once `acquire` has
returned and while the Lease's client closes and the take's event loop ends, where a signal is
taken as one during the wait for the Lease, the Lease taken and not released; and `served.run`
before uvicorn's `capture_signals` (its runner and loop made, `serve` begun), where a signal ends
the run with the store and the listener closed, the driver's close missed and the Lease not
released. The two last were read at 0.2-0.7 ms and 0.3-0.7 ms on the development host (Python
3.14.4, the Lease's client over no connection; one closing a connection to the API takes longer,
not read).

Its exit status:

- 0, stopped cleanly (uvicorn told to exit), the Lease released first when one is held;
- 130, stopped by SIGINT (Ctrl-C), with no traceback, the store closed and the Lease released
  first when one is held; or Ctrl-C anywhere in the start, while it waits for the Lease, while the
  store is opened or before uvicorn runs, what was opened closed again and the Lease released
  first, but in the two windows of the start above, where the status is the same and the Lease
  is left to its duration;
- 143, stopped by SIGTERM, as by Ctrl-C and with what 130 says, whatever the process's id: after
  uvicorn's graceful shutdown, which releases the Lease, or anywhere in the start, its two
  windows above as for 130; or, run by the console script, while this module is imported, before
  anything is;
- 1, the store held by another core, an object store that cannot be opened (an `S3Error`), the
  Lease lost, or the application's lifespan failing to start;
- 2, a misconfiguration: settings not whole (among them an `s3://` store without `FYLGJA_LEASE`
  or with the containerlab driver, and one of the TLS pair without the other), a certificate or
  key that does not load (`FYLGJA_TLS_CERT`), a key that is encrypted, never prompted for
  (`FYLGJA_TLS_KEY`), `FYLGJA_LEASE` set with no cluster to reach
  (`KUBECONFIG`, as for the driver below) or a Lease the service account may not read or write,
  a CA bundle that does not load (`FYLGJA_S3_CA`), an endpoint that fails the store's proof
  (`FYLGJA_S3_ENDPOINT`, rule `store.unconditional`), Python run optimised (`-O` or
  `PYTHONOPTIMIZE`, rule `server.optimised`), a package refused, a token file it cannot
  read, a driver it does not serve, a cluster the clabernetes driver cannot reach (`KUBECONFIG`,
  or in a pod `KUBERNETES_SERVICE_HOST` or `KUBERNETES_SERVICE_PORT`), an address it cannot
  listen on (`FYLGJA_LISTEN`), or, run by the console script from a base install, one of the
  server's libraries not installed (rule `server.extra.missing`).

Waiting for a Lease another holds is no exit: one INFO line a holder, and no socket bound.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import functools
import ipaddress
import logging
import os
import signal
import socket
import ssl
import sys
import threading
from collections.abc import Awaitable, Callable, Iterator, Sequence
from importlib.metadata import version
from pathlib import Path
from types import FrameType
from typing import cast

import uvicorn
from starlette.applications import Starlette
from starlette.types import ASGIApp, Receive, Scope, Send

from fylgja_core import config, drivers, lease, logs, packages
from fylgja_core.config import Misconfigured, S3Location, Settings
from fylgja_core.credentials import Provider
from fylgja_core.documents import Rejected
from fylgja_core.driver import Driver
from fylgja_core.local_store import LocalStore
from fylgja_core.object_store import ObjectStore, Unconditional
from fylgja_core.reconcile import Reconciler
from fylgja_core.s3 import S3, S3Error
from fylgja_core.server.app import create_app
from fylgja_core.server.auth import Tokens
from fylgja_core.store import Locked, Store, StoreError
from fylgja_core.verify import Verifier

GRACE_S = 5
"""Seconds an open watch is given to end at shutdown before uvicorn cuts it."""

LOST_STOP_S = 2.0
"""Seconds a server that lost its Lease gives the loop to stop before it stops all the same."""

_log = logging.getLogger("fylgja.server")


class _Cut:
    """The application, as `_Server` serves it: a request the server cut when its Lease was lost
    ends quietly. The server drops the request's connection before it cancels the request, and
    this ends that one cancellation, `lost()` true, once uvicorn has seen the connection gone (its
    `http.disconnect`), so uvicorn answers nothing and logs nothing for it. Every other
    cancellation, and every exception, propagates as it would without this layer, so `_Faults`
    and uvicorn's own handling are unchanged (verified-facts.md, uvicorn 0.54.0)."""

    def __init__(self, app: ASGIApp, lost: Callable[[], bool]) -> None:
        self.app = app
        self._lost = lost

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        try:
            await self.app(scope, receive, send)
        except asyncio.CancelledError:
            task = asyncio.current_task()
            if not self._lost() or task is None:
                raise
            task.uncancel()
            while (await receive())["type"] != "http.disconnect":
                pass


class _Server(uvicorn.Server):
    """uvicorn's server, which sets `closing` as it begins to shut down, before it waits for the
    connections to close: the application's open streams end, and none is cut. `driver` is closed
    (`drivers.close`) as it stops, and when it fails to start. It serves its application through
    `_Cut`, so `config` is one not yet loaded, of an application object.

    With the Lease `held`, taken before, `startup` renews it and then starts a task that holds it
    (`Lease.hold`), both before the lifespan starts the loop; that renewal failing, `Lost` or
    otherwise, is the loss, and raises `SystemExit(1)`. Whatever ends the task holding the Lease
    is the loss too, since no renewal follows it.

    **Lost**, it stops at once, in this order (`_cut`): its one ERROR line (`rule="lease.lost"`);
    the loop's stop begun (`_stop_the_loop`), no request awaited first; no connection taken any
    more; every connection dropped, aborted, so no response is completed: each one a listener
    accepted, those still in their TLS handshake or not yet handed to uvicorn among them, and each
    one uvicorn holds; each request in flight cancelled, none waited for, which `_Cut` ends
    quietly; with `should_exit` and `force_exit` set, so uvicorn's shutdown gives no grace. All of
    it is one step of the event loop, so no request in flight writes after the loss. Nothing is
    released. A loss while the lifespan starts comes before the listeners are made: `startup`
    drops their connections again once they are.

    **The loop's stop** is the lifespan's shutdown, which uvicorn's own shutdown runs unless
    `force_exit` is set before it reaches it: lost, or a second Ctrl-C. (A second Ctrl-C after it
    has begun leaves uvicorn's own running, unbounded, and nothing is released until it ends; this
    server then runs the lifespan's shutdown again, which uvicorn's `LifespanOn.shutdown` ends at
    once on its event already set, its two INFO lines repeated, so it is left unguarded.)
    Then this server runs it, bounded by `LOST_STOP_S`, before the Lease is released: a loop that
    has not stopped within the bound is one WARNING, the server stops all the same, and a Lease
    still held is not released, so its next holder waits out the duration. The WARNING is for the
    bound alone: a loop's stop that raises is caught by uvicorn's `LifespanOn.shutdown`, which
    logs it with its traceback at ERROR, and the stop has ended (verified-facts.md, uvicorn
    0.54.0).

    `shutdown` runs uvicorn's own, then the loop's stop where uvicorn skipped it, then cancels the
    task holding the Lease, so no renewal in flight reads this core's own release back as `Lost`,
    then releases the Lease unless it is lost or the loop did not stop, and closes the Lease's
    client and the driver, each whatever the one before raised, a close that fails one WARNING.
    A start that fails once the task has begun (the lifespan's, after which uvicorn calls no
    `shutdown`) stops the task and closes both the same way, releasing nothing: the Lease is left
    to this pod's next start."""

    def __init__(self, config: uvicorn.Config, closing: threading.Event, held: lease.Lease | None = None, *,
                 driver: Driver | None = None, terminated: threading.Event | None = None) -> None:
        if config.loaded or isinstance(config.app, str):
            raise ValueError("the server serves an application object through _Cut: give it a configuration not "
                             "yet loaded")
        config.app = _Cut(cast(ASGIApp, config.app), lambda: self.lost)
        super().__init__(config)
        self._closing = closing
        self._held = held
        self._driver = driver
        self._holding: asyncio.Task[None] | None = None
        self._stopping: asyncio.Task[str | None] | None = None
        self.lost = False
        self.terminated = terminated if terminated is not None else threading.Event()
        self.signalled = False

    def handle_exit(self, sig: int, frame: FrameType | None) -> None:
        """uvicorn's, with `terminated` set first for SIGTERM, and `signalled` for either signal:
        `main` exits 143 or 130 by them, whatever the signal uvicorn raises again once it has
        stopped does (the default handler, a container's PID 1's, ignores it; in a pod on the
        cluster it is refused, `capture_signals`)."""
        if sig == signal.SIGTERM:
            self.terminated.set()
        self.signalled = True
        super().handle_exit(sig, frame)

    @contextlib.contextmanager
    def capture_signals(self) -> Iterator[None]:
        """uvicorn's, whose raise again of the signal it caught, once the server has stopped, may
        be refused: in a pod on the cluster a process may not signal itself, and `raise` answers
        EACCES, likely the pod's stacked AppArmor label, the refusal's cause not read
        (verified-facts.md). The server has stopped gracefully all the same, so that refusal, a
        `PermissionError`, is taken as a raise that reached no handler, and `main` exits by the
        signal caught. Any other `OSError`, and one raised while it serves, is raised as it is."""
        stopped = False
        try:
            with super().capture_signals():
                yield
                stopped = True
        except PermissionError:
            if not (stopped and self.signalled):
                raise

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        try:
            if self._held is not None:
                try:
                    await self._held.renew()
                except Exception as e:  # `Lost`, or a renewal that broke the Lease's contract, as `_hold` takes it
                    self._lose(self._held, e)
                    raise SystemExit(1) from None
                self._holding = asyncio.create_task(self._hold(self._held))
            await super().startup(sockets)
            if self.lost:  # lost while the lifespan started: the cut came before the listeners were made
                self._drop()
        except BaseException:
            await self._stop(release=False)
            raise

    async def shutdown(self, sockets: list[socket.socket] | None = None) -> None:
        self._closing.set()
        stopped = False
        try:
            await super().shutdown(sockets)
            stopped = await self._loop_stopped()
        finally:
            await self._stop(release=stopped)

    async def _hold(self, held: lease.Lease) -> None:
        """Hold the Lease until it is lost, then stop the server at once."""
        try:
            await held.hold()
        except Exception as e:  # `Lost`, or a renewal that broke the Lease's contract: either way none follows
            self._lose(held, e)
            self.should_exit = self.force_exit = True  # first: nothing after it can leave the server serving
            self._cut()

    def _lose(self, held: lease.Lease, error: Exception) -> None:
        """`lost` set, and its one ERROR line: what `Lost` says, or the type of what ended the
        renewals, never its text."""
        self.lost = True
        if isinstance(error, lease.Lost):
            why = str(error)
        else:
            why = f"the Lease {held.name} is no longer renewed ({type(error).__name__})"
        _log.error("the server stops at once: %s", why, **logs.fields(lease=held.name, rule=lease.RULE_LOST))

    def _cut(self) -> None:
        """At the loss: the loop's stop begun, which `shutdown` awaits; then `_drop`. All of it
        happens before any request runs again, since this runs in one step of the event loop."""
        self._stopping = asyncio.create_task(self._stop_the_loop())
        self._drop()

    def _drop(self) -> None:
        """Each listener closed and every connection it accepted aborted, those still in their TLS
        handshake or not yet handed to uvicorn among them (`abort_clients`); each connection uvicorn
        holds aborted, so no response is completed; each request in flight cancelled, none waited
        for (verified-facts.md, uvicorn 0.54.0 and Python 3.14.4)."""
        for listener in getattr(self, "servers", ()):  # none yet when the loss comes before the start's end
            listener.close()
            listener.abort_clients()
        for connection in list(self.server_state.connections):
            connection.transport.abort()
        for request in list(self.server_state.tasks):
            request.cancel()

    async def _stop_the_loop(self) -> str | None:
        """The lifespan's shutdown, within `LOST_STOP_S`: None once it has ended, else the type of
        what ended the wait, the bound's `TimeoutError`."""
        try:
            async with asyncio.timeout(LOST_STOP_S):
                await self.lifespan.shutdown()
        except Exception as e:  # TimeoutError: the event loop's close cancels what is left
            return type(e).__name__
        return None

    async def _loop_stopped(self) -> bool:
        """Whether the loop has stopped: in uvicorn's own shutdown, or where `force_exit` made it
        skip that, by `_stop_the_loop`, begun at the loss (`_cut`) or run here. One that has not
        stopped within its bound is one WARNING."""
        if self._stopping is not None:
            failure = await self._stopping
        elif self.force_exit:
            failure = await self._stop_the_loop()
        else:
            return True
        if failure is None:
            return True
        if self._held is not None and not self.lost:
            _log.warning("the loop's stop did not end (%s): the Lease %s is not released, and its next holder takes it "
                         "once its duration has passed", failure, self._held.name,
                         **logs.fields(lease=self._held.name, failure=failure))
        else:
            _log.warning("the loop's stop did not end (%s): the server stops all the same", failure,
                         **logs.fields(failure=failure))
        return False

    async def _stop(self, *, release: bool) -> None:
        """The task holding the Lease cancelled and awaited; the Lease released when `release` and
        it is not lost; its client and the driver closed, each whatever the one before raised, a
        close that fails one WARNING by its type (`_aclosed_anyway`), so the status `main` gives
        stands."""
        task, self._holding = self._holding, None
        try:
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            if self._held is not None:
                try:
                    if release and not self.lost and await self._held.release():
                        _log.info("released the Lease %s", self._held.name, **logs.fields(lease=self._held.name))
                finally:
                    await _aclosed_anyway(self._held.close, "the Lease's client")
        finally:
            if self._driver is not None:
                await _aclosed_anyway(functools.partial(drivers.close, self._driver), "the driver")


class _TokenFile(Exception):
    """The token file `FYLGJA_TOKENS` names cannot be read, or holds a line that is no hash and principal."""


class _CaFile(Exception):
    """The CA bundle `FYLGJA_S3_CA` names cannot be loaded; the message is the error's reason."""


class _Encrypted(Exception):
    """The key `FYLGJA_TLS_KEY` names is encrypted: raised by `_no_password`, which OpenSSL calls
    for a key that needs a password in place of prompting for one on the terminal."""


def _no_password() -> str:
    raise _Encrypted


def _closed_anyway(close: Callable[[], object], what: str) -> None:
    """`close()`, a failure of its own one WARNING by its type: after a failure, so that the one
    being raised is the one that propagates, and at the start's end, so the status stands."""
    try:
        close()
    except Exception as e:
        _log.warning("%s was not closed (%s)", what, type(e).__name__, **logs.fields(failure=type(e).__name__))


async def _aclosed_anyway(close: Callable[[], Awaitable[object]], what: str) -> None:
    """`await close()`, a failure of its own one WARNING by its type, as `_closed_anyway`."""
    try:
        await close()
    except Exception as e:
        _log.warning("%s was not closed (%s)", what, type(e).__name__, **logs.fields(failure=type(e).__name__))


def _reason(error: OSError) -> str:
    """What `error` says went wrong, never a path nor what a file holds: an `ssl.SSLError`'s reason
    (`KEY_VALUES_MISMATCH`), or its message where it has none (`[SSL] PEM lib (_ssl.c:…)`), or the
    system's (`No such file or directory`)."""
    reason: str | None = getattr(error, "reason", None)
    return reason or error.strerror or type(error).__name__


def _open(store: Path | S3Location) -> Store:
    """The store `store` names: a directory, locked; or an object store, once its endpoint has
    passed the store's proof, its client closed again when it does not."""
    if isinstance(store, Path):
        return LocalStore.open(store)
    try:
        s3 = S3.connect(store.endpoint, store.bucket, store.access_key, store.secret_key, store.region, store.ca)
    except OSError as e:  # its trust is built from the CA bundle alone: a file missing, or holding no certificate
        raise _CaFile(_reason(e)) from e
    try:
        return ObjectStore.open(s3, store.prefix)
    except BaseException:
        s3.close()
        raise


def build_app(settings: Settings, *, closing: threading.Event | None = None) -> tuple[Starlette, Store]:
    """The application over the store `settings` name, which it holds until the caller closes
    it: a directory, `Locked` when another core holds it; or an object store, held for one core by
    the Lease the caller has taken, `Unconditional` for an endpoint that fails the store's proof,
    an `S3Error` for one that cannot be reached or refuses, `_CaFile` for a CA bundle that does not
    load. A package refused, a token file it cannot read, a driver it does not serve and one it
    cannot make (`drivers.Unmakeable`) are raised too, with the store closed again, and the driver
    too where it was made (`drivers.close`), the failure raised the one that propagates whatever a
    close raises. The driver is given the store's directory, where the store has one, and is the
    application's `state.driver`, for the server to close. The driver, the verifier and the loop
    read credentials through one provider. Its open streams end once `closing` is set. The
    settings are checked first (`config.check`), whoever made them, before anything is opened."""
    config.check(settings)
    store = _open(settings.store)
    try:
        loaded = packages.load(settings.packages)
        try:
            tokens = Tokens.load(settings.tokens)
        except (OSError, ValueError) as e:
            raise _TokenFile(str(e)) from e
        provider = Provider(os.environ)
        driver = drivers.make(settings.driver, root=settings.store if isinstance(settings.store, Path) else None,
                              credentials=provider, clabernetes_namespace=settings.clabernetes_namespace,
                              pod_cidr=settings.pod_cidr)
        try:
            served = {driver.name: driver}
            verifier = Verifier(loaded.platforms, loaded.probes, provider)
            reconciler = Reconciler(store, served, loaded.platforms, loaded.probes, provider,
                                    workers=settings.workers, resync_s=settings.resync_s, verifier=verifier,
                                    step_wait_s=settings.step_wait_s)
            app = create_app(store=store, loaded=loaded, drivers=served, default_driver=driver.name,
                             reconciler=reconciler, verifier=verifier, tokens=tokens, build=version("fylgja-core"),
                             closing=closing)
        except BaseException:
            _closed_anyway(lambda: asyncio.run(drivers.close(driver)), "the driver")  # no loop runs here yet
            raise
        app.state.driver = driver
    except BaseException:
        _closed_anyway(store.close, "the store")
        raise
    return app, store


def _refused(message: str, *args: object, **kw: object) -> None:
    _log.error(message, *args, **logs.fields(**kw))


def _on_sigterm(terminated: threading.Event, signum: int, frame: FrameType | None) -> None:
    """SIGTERM, outside uvicorn's own handling of it, taken as Ctrl-C is by whatever handles
    SIGINT at that moment: asyncio's runner cancels the task it runs (the wait for the Lease), and
    Python's own handler raises `KeyboardInterrupt` (the store's open), so what was opened is
    closed and a Lease held released by Ctrl-C's paths; `terminated` set first, so `main` exits
    143 where Ctrl-C exits 130. A signal with no handler is ignored by a container's PID 1."""
    terminated.set()
    on_sigint = signal.getsignal(signal.SIGINT)
    if callable(on_sigint):
        on_sigint(signal.SIGINT, frame)
    else:  # SIGINT ignored, as in a shell's background job, or not Python's: SIGTERM ends the wait all the same
        raise KeyboardInterrupt


def _stopped(terminated: threading.Event) -> tuple[str, int]:
    """The signal that stopped the start or the server, by name, and the exit status it gives."""
    return ("SIGTERM", 143) if terminated.is_set() else ("SIGINT", 130)


def _optimised() -> bool:
    """Whether Python runs with `-O` or `PYTHONOPTIMIZE`, which strip every `assert`: one inside
    asyncio is what drops a connection accepted in the turn before a lost Lease's cut (the facts),
    so the server does not start so."""
    return bool(sys.flags.optimize)


def _listener(host: str, port: int) -> socket.socket:
    """A socket listening on `host:port`, its family the host's; `OSError` (a `gaierror` for a
    host that does not resolve) when it cannot be had."""
    family, _, _, _, address = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, flags=socket.AI_PASSIVE)[0]
    return socket.create_server(address[:2], family=family)


def _loopback(host: str) -> bool:
    """Whether `host` is `localhost` or a loopback address."""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _config(app: Starlette, settings: Settings) -> uvicorn.Config:
    """uvicorn's configuration for `app` on `settings.listen`: no logging of its own and no access
    log, `GRACE_S` for open connections at shutdown, and the TLS pair `settings.tls` where it is
    given, which uvicorn loads as `main` checked it. Its protocol is h11's and its event loop
    asyncio's, never left to "auto", which would take httptools or uvloop were either installed:
    the cut at a loss rests on both (verified-facts.md, uvicorn 0.54.0)."""
    host, port = settings.listen
    cert, key = settings.tls if settings.tls is not None else (None, None)
    return uvicorn.Config(app, host=host, port=port, http="h11", loop="asyncio", log_config=None, access_log=False,
                          timeout_graceful_shutdown=GRACE_S, ssl_certfile=cert, ssl_keyfile=key)


async def _taken(held: lease.Lease) -> None:
    """Take the Lease, then close its client: this loop ends here, and uvicorn's makes its own. A
    close that fails is one WARNING by its type (`_aclosed_anyway`), so the start goes on."""
    try:
        await held.acquire()
    finally:
        await _aclosed_anyway(held.close, "the Lease's client")


async def _released(held: lease.Lease) -> None:
    """Release the Lease, saying so where it was written free, then close its client, a close that
    fails one WARNING by its type, so the status `main` gives stands."""
    try:
        if await held.release():
            _log.info("released the Lease %s", held.name, **logs.fields(lease=held.name))
    finally:
        await _aclosed_anyway(held.close, "the Lease's client")


def main(argv: Sequence[str] | None = None) -> int:
    """Serve API 1 until uvicorn is stopped; the exit status (the module's docstring lists them)."""
    argparse.ArgumentParser(
        prog="fylgja-core-server",
        description="Serve API 1 and run the reconcile loop over one store. Every setting is a FYLGJA_* "
                    "variable: FYLGJA_STORE, FYLGJA_PACKAGES and FYLGJA_TOKENS; FYLGJA_LISTEN, FYLGJA_DRIVER, "
                    "FYLGJA_WORKERS, FYLGJA_STEP_WAIT_S and FYLGJA_RESYNC_S with their defaults; "
                    "FYLGJA_CLABERNETES_NAMESPACE and FYLGJA_POD_CIDR, required by the clabernetes driver, which "
                    "reaches the cluster through KUBECONFIG off it; FYLGJA_S3_ENDPOINT, FYLGJA_S3_ACCESS_KEY, "
                    "FYLGJA_S3_SECRET_KEY, FYLGJA_S3_REGION and FYLGJA_S3_CA for an s3:// store, which needs "
                    "FYLGJA_LEASE, the Lease taken before the store is opened; and FYLGJA_TLS_CERT and "
                    "FYLGJA_TLS_KEY, set together, the key unencrypted, for TLS (CONTRIBUTING.md, \"Running the "
                    "core\"). It exits 0 when stopped, 130 on SIGINT, 143 on SIGTERM, 1 when the store is held or "
                    "cannot be opened, the Lease is lost or the application does not start, and 2 on a "
                    "misconfiguration.",
    ).parse_args(argv)
    logs.configure()
    terminated = threading.Event()
    before = signal.signal(signal.SIGTERM, functools.partial(_on_sigterm, terminated))
    try:
        return _start(terminated)
    except KeyboardInterrupt:  # the last resort, where `_start` has no handler and holds nothing: the settings read
        sent, status = _stopped(terminated)
        _log.info("stopped by %s", sent)
        return status
    finally:
        signal.signal(signal.SIGTERM, before if before is not None else signal.SIG_DFL)


def _start(terminated: threading.Event) -> int:
    """`main`'s start and serving, SIGTERM taken as Ctrl-C is (`_on_sigterm`, which sets
    `terminated`), before anything that can wait: the Lease, the store."""
    if _optimised():
        _refused("cannot start: Python runs optimised (-O or PYTHONOPTIMIZE), which strips the assert the stop at a "
                 "lost Lease rests on", rule="server.optimised")
        return 2
    try:
        settings = config.from_environ(os.environ)
    except Misconfigured as e:
        _refused("cannot start: %s", e, variable=e.variable, rule=e.rule)
        return 2
    if settings.tls is not None:
        try:
            ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(*settings.tls, password=_no_password)
        except _Encrypted:
            _refused("cannot start: FYLGJA_TLS_KEY is encrypted: the server reads an unencrypted key",
                     variable="FYLGJA_TLS_KEY")
            return 2
        except OSError as e:  # ssl.SSLError among them
            _refused("cannot start: FYLGJA_TLS_CERT and FYLGJA_TLS_KEY name a certificate and key that do not "
                     "load: %s", _reason(e), variable="FYLGJA_TLS_CERT", error=type(e).__name__)
            return 2
    closing = threading.Event()  # made before the take: a signal handled in the call finds nothing held
    held: lease.Lease | None = None
    if settings.lease is not None:
        name = settings.lease
        held = lease.Lease(lease.KubeLeases(name), lease.identity(), on_wait=lambda holder: _log.info(
            "waiting for the Lease %s, held by %s", name, holder, **logs.fields(lease=name, holder=holder)))
        try:
            asyncio.run(_taken(held))
        except KeyboardInterrupt:
            sent, status = _stopped(terminated)
            _log.info("stopped by %s while waiting for the Lease %s", sent, name, **logs.fields(lease=name))
            return status
        except lease.Refused as e:
            _refused("cannot start: the Lease %s cannot be taken: %s", name, e,
                     variable=e.variable or "FYLGJA_LEASE", lease=name)
            return 2
    try:
        if held is not None:
            _log.info("holding the Lease %s as %s", held.name, held.identity,
                      **logs.fields(lease=held.name, holder=held.identity))
        app, store = build_app(settings, closing=closing)
    except KeyboardInterrupt:  # Ctrl-C or SIGTERM while the store was opened, closed again by build_app
        if held is not None:
            asyncio.run(_released(held))
        sent, status = _stopped(terminated)
        _log.info("stopped by %s", sent)
        return status
    except Misconfigured as e:
        _refused("cannot start: %s", e, variable=e.variable, rule=e.rule)
        return 2
    except Unconditional as e:
        _refused("cannot start: %s", e, variable="FYLGJA_S3_ENDPOINT", rule=e.rule)
        return 2
    except Locked as e:
        _refused("cannot start: %s", e.detail, variable="FYLGJA_STORE")
        return 1
    except (S3Error, StoreError) as e:
        _refused("cannot start: the object store cannot be opened: %s", e, variable="FYLGJA_STORE",
                 error=type(e).__name__)
        return 1
    except _CaFile as e:
        _refused("cannot start: the CA bundle FYLGJA_S3_CA names cannot be loaded: %s", e, variable="FYLGJA_S3_CA")
        return 2
    except Rejected as e:
        _refused("cannot start: a package is refused: %s", e, variable="FYLGJA_PACKAGES", rule=e.problems[0].rule)
        return 2
    except _TokenFile as e:
        _refused("cannot start: the token file cannot be read: %s", e, variable="FYLGJA_TOKENS")
        return 2
    except KeyError as e:
        _refused("cannot start: %s", e.args[0], variable="FYLGJA_DRIVER")
        return 2
    except drivers.Unmakeable as e:
        _refused("cannot start: %s", e, variable=e.variable)
        return 2
    except OSError as e:
        _refused("cannot start: %s", e, error=type(e).__name__)
        return 2
    host, port = settings.listen
    listener: socket.socket | None = None
    try:
        try:
            listener = _listener(host, port)
        except OSError as e:  # uvicorn would exit 3 for it: it is the address's fault, so the settings'
            _closed_anyway(lambda: asyncio.run(drivers.close(app.state.driver)), "the driver")
            _closed_anyway(store.close, "the store")
            _refused("cannot start: FYLGJA_LISTEN names an address it cannot listen on: %s", e.strerror or e,
                     variable="FYLGJA_LISTEN", error=type(e).__name__)
            return 2
        _log.info("serving API 1 on %s:%d over the store %s, driver %s, %d workers", host, port, settings.store,
                  settings.driver, settings.workers, **logs.fields(driver=settings.driver, workers=settings.workers))
        if settings.tls is None and not _loopback(host):
            _log.warning("serving HTTP on %s, which is not a loopback address: a client's token crosses the network "
                         "in clear; FYLGJA_TLS_CERT and FYLGJA_TLS_KEY give it TLS (D-063)", host,
                         **logs.fields(variable="FYLGJA_TLS_CERT"))
        served = _Server(_config(app, settings), closing, held, driver=app.state.driver, terminated=terminated)
    except KeyboardInterrupt:  # Ctrl-C or SIGTERM once the store is open, before uvicorn runs: as while it opened
        if listener is not None:
            listener.close()
        _closed_anyway(lambda: asyncio.run(drivers.close(app.state.driver)), "the driver")
        _closed_anyway(store.close, "the store")
        if held is not None:
            asyncio.run(_released(held))
        sent, status = _stopped(terminated)
        _log.info("stopped by %s", sent)
        return status
    try:
        served.run(sockets=[listener])
    except KeyboardInterrupt:  # uvicorn shut down gracefully, then raised the signal it caught: main's handler took it
        sent, status = _stopped(terminated)
        _log.info("stopped by %s", sent)
        return status
    except SystemExit:  # uvicorn's startup failure, once the address is bound: the lifespan's, logged above
        if not served.lost:  # a Lease lost at the start is one ERROR line, logged above
            _refused("cannot start: the application did not start; the lines above say why")
        return 1
    finally:
        try:
            listener.close()
        finally:
            _closed_anyway(store.close, "the store")  # a failure one WARNING: the status computed stands
    if served.lost:
        return 1
    # uvicorn stopped on a signal, and the one it raised again reached no handler, or was refused (`capture_signals`)
    if terminated.is_set() or served.signalled:
        sent, status = _stopped(terminated)
        _log.info("stopped by %s", sent)
        return status
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
