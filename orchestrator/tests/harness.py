"""The core's own server on its fake runtime, for the rehearsal library's tests (D-034): API 1's real application over
a local store, the shipped packages, the real reconcile loop and verify, and the core's fakes of a runtime, served by
uvicorn on a loopback port in a thread, and reached by the core's own client as two principals.

It is built as `core/tests/test_api.py` builds its application, whose fixture keeps its push and readiness fakes to
itself. Starlette's `TestClient` answers a request only once its response has ended, so no `Client` could watch
through it: the application is served for real. The runtime seeds the gNMI reader from every bundle it applies, so
verify holds on every twin unless a test says otherwise. Every clock and wait the library is handed in a test is a
`Clock`, which never waits what it is asked; a test acts on the harness through it, through a `Wrapped` client, or
at a `progress` line it names.
"""

from __future__ import annotations

import contextlib
import json
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path
from typing import Any

import uvicorn
from fakes import FakeDriver, FakePush, FakeReader, FakeReady, fake_push, fake_ready
from fylgja_core import bundle, packages
from fylgja_core.client import Client
from fylgja_core.credentials import Provider
from fylgja_core.deployment import Deployment
from fylgja_core.local_store import LocalStore
from fylgja_core.platform_package import PlatformPackage
from fylgja_core.probe_package import ProbePackage
from fylgja_core.reconcile import Reconciler
from fylgja_core.server import auth
from fylgja_core.server.app import create_app
from fylgja_core.verify import Verifier

ROOT = Path(__file__).resolve().parents[2]
# The two clients' tokens, test values: alice is the rehearsal's principal, bob another's.
ALICE = "alice-test-token"
BOB = "bob-test-token"
# The node logins the fake runtime's push, readiness wait and reader are handed, and never check: test values.
ENVIRON = {
    "FYLGJA_CREDENTIAL_SRLINUX_USERNAME": "test-user",
    "FYLGJA_CREDENTIAL_SRLINUX_PASSWORD": "test-password",
    "FYLGJA_CREDENTIAL_EOS_USERNAME": "test-user",
    "FYLGJA_CREDENTIAL_EOS_PASSWORD": "test-password",
}
# A yield to the server's thread on every sleep of a `Clock`, so that the loop works while the library waits.
YIELD_S = 0.005


class Runtime(FakeDriver):
    """The core's fake driver, whose `apply` then seeds `reader` with the facts the applied deployment's bundle
    gives, as `test_api.py`'s `seed_reader` does by hand: verify holds on every twin it applies. A test that wants a
    node unread or a fact perturbed changes `reader` after the apply."""

    def __init__(self, store: LocalStore) -> None:
        super().__init__()
        self.store = store
        self.reader = FakeReader(self)

    async def apply(
        self,
        deployment: Deployment,
        files: Mapping[str, bytes],
        platforms: Mapping[str, PlatformPackage],
        probe_packages: Mapping[str, ProbePackage],
        reconfigure: bool = False,
    ) -> None:
        await super().apply(deployment, files, platforms, probe_packages, reconfigure)
        manifest = bundle.decode(json.loads(self.store.get_bundle(deployment.bundle_id)["manifest.json"]))
        self.reader.seed(deployment.twin, manifest, platforms)


@dataclass
class Served:
    """The served core: a client as alice and one as bob, at `address`, and what the application is built over, for
    a test to arrange and to look into."""

    client: Client
    other: Client
    address: str
    driver: Runtime
    reader: FakeReader
    pusher: FakePush
    ready: FakeReady
    store: LocalStore


@contextlib.contextmanager
def serving(root: Path) -> Iterator[Served]:
    """API 1 over a local store under `root`, with the loop's waits shortened, served by uvicorn on a loopback port
    of its own until the block is left, lifespan and all. Leaving ends every open stream, stops the server and
    closes the store, whatever the block raised."""
    store = LocalStore.open(root / "store")
    tokens = root / "tokens"
    tokens.write_text(f"# the tests' clients\n{auth.hash_token(ALICE)} alice\n{auth.hash_token(BOB)} bob\n")
    loaded = packages.load([ROOT / "psp", ROOT / "probes"])
    driver = Runtime(store)
    pusher, ready = fake_push(driver=driver), fake_ready(driver=driver)
    verifier = Verifier(loaded.platforms, loaded.probes, Provider(ENVIRON), reader=driver.reader)
    reconciler = Reconciler(store, {driver.name: driver}, loaded.platforms, loaded.probes, Provider(ENVIRON),
                            workers=1, pusher=pusher, readiness=ready, cancel_poll_s=0.01, verifier=verifier,
                            step_wait_s=1.0, verify_poll_s=0.01)
    closing = threading.Event()
    app = create_app(store=store, loaded=loaded, drivers={driver.name: driver}, default_driver=driver.name,
                     reconciler=reconciler, tokens=auth.Tokens.load(tokens), build=version("fylgja-core"),
                     closing=closing, verifier=verifier)
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_config=None, access_log=False,
                            timeout_graceful_shutdown=1)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="uvicorn")
    thread.start()
    try:
        wait_for(lambda: True if server.started else None)
        host, port = server.servers[0].sockets[0].getsockname()[:2]
        address = f"{host}:{port}"
        with Client(address, ALICE) as client, Client(address, BOB) as other:
            yield Served(client=client, other=other, address=address, driver=driver, reader=driver.reader,
                         pusher=pusher, ready=ready, store=store)
    finally:
        closing.set()  # as the server begins to stop, every open stream ends
        server.should_exit = True
        thread.join(timeout=10)
        store.close()
    assert not thread.is_alive(), "the server did not stop"


def wait_for[T](read: Callable[[], T | None], timeout_s: float = 10.0) -> T:
    """`read()` once it answers something, polled while the loop works, in real time."""
    deadline = time.monotonic() + timeout_s
    while (value := read()) is None:
        assert time.monotonic() < deadline, "the loop did not get there in time"
        time.sleep(0.01)
    return value


@dataclass
class Clock:
    """The library's clock and its sleep in one: `now()` reads `t`, and `sleep(s)` records `s` in `slept`, moves `t`
    by `s`, runs `on_sleep` when it is set, and yields `YIELD_S` of real time to the server's thread. It never waits
    what it was asked."""

    t: float = 0.0
    slept: list[float] = field(default_factory=list)
    on_sleep: Callable[[], None] | None = None

    def now(self) -> float:
        return self.t

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.t += s
        if self.on_sleep is not None:
            self.on_sleep()
        time.sleep(YIELD_S)


class Wrapped(Client):
    """`client` with some of its calls the test's: each keyword names a call of `Client` and gives what takes its
    place, called as the client's would be and answering what it answers (`get_twin=` the `(record, etag)` pair).
    Every other call is the client's own, over its connection, and a call of the client's that makes others makes the
    test's: `follow` reads through `watch_twin`, `get_run`, `list_runs` and `watch_run`, so replacing one changes what
    `follow` sees. It shares `client`'s connection pool, so closing it, as leaving `with Wrapped(...)` does, closes
    `client`'s too."""

    def __init__(self, client: Client, **calls: Callable[..., Any]) -> None:
        unknown = sorted(set(calls) - {name for name in dir(Client) if not name.startswith("_")})
        if unknown:
            raise TypeError(f"Client has no call {', '.join(unknown)}")
        # The client's state shared, not its initialiser run again: the same connection pool and the same token.
        vars(self).update(vars(client))
        vars(self).update(calls)
