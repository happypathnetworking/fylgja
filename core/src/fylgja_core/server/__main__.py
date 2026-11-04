"""fylgja-core-server: one process serving API 1 and running the reconcile loop over one store
(D-023, D-039, D-042).

Everything it runs with comes from `FYLGJA_*` variables (`config`): the store, held locked for
one core; the packages, loaded once; the driver; the token file; the address, which it binds
itself before uvicorn serves on it. The loop starts and stops with the application's lifespan.
SIGTERM and SIGINT are uvicorn's own to handle: as it begins to shut down, the application's
open streams are told to end, so a watch ends rather than waiting out `GRACE_S` to be cut; then
the loop stops. A start refused is one log line, naming the variable or the file at fault and
never a value.

Its exit status:

- 0, stopped cleanly (uvicorn told to exit);
- 130, stopped by SIGINT (Ctrl-C), with no traceback and the store closed;
- 143, stopped by SIGTERM: uvicorn ends the process by the signal it was sent, after the
  graceful shutdown, and the kernel releases the store's lock;
- 1, the store held by another core, or the application's lifespan failing to start;
- 2, a misconfiguration: settings not whole, a package refused, a token file it cannot read, a
  driver it does not serve, an address it cannot listen on (`FYLGJA_LISTEN`).
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import threading
from collections.abc import Sequence
from importlib.metadata import version

import uvicorn
from starlette.applications import Starlette

from fylgja_core import config, drivers, logs, packages
from fylgja_core.config import Misconfigured, Settings
from fylgja_core.credentials import Provider
from fylgja_core.documents import Rejected
from fylgja_core.local_store import LocalStore
from fylgja_core.reconcile import Reconciler
from fylgja_core.server.app import create_app
from fylgja_core.server.auth import Tokens
from fylgja_core.store import Locked

GRACE_S = 5
"""Seconds an open watch is given to end at shutdown before uvicorn cuts it."""

_log = logging.getLogger("fylgja.server")


class _Server(uvicorn.Server):
    """uvicorn's server, which sets `closing` as it begins to shut down, before it waits for the
    connections to close: the application's open streams end, and none is cut."""

    def __init__(self, config: uvicorn.Config, closing: threading.Event) -> None:
        super().__init__(config)
        self._closing = closing

    async def shutdown(self, sockets: list[socket.socket] | None = None) -> None:
        self._closing.set()
        await super().shutdown(sockets)


class _TokenFile(Exception):
    """The token file `FYLGJA_TOKENS` names cannot be read, or holds a line that is no hash and principal."""


def build_app(settings: Settings, *, closing: threading.Event | None = None) -> tuple[Starlette, LocalStore]:
    """The application over the store `settings` name, which it holds until the caller closes
    it: `Locked` when another core holds it. A package refused, a token file it cannot read and
    a driver it does not serve are raised too, with the store closed again. Its open streams end
    once `closing` is set."""
    store = LocalStore.open(settings.store)
    try:
        loaded = packages.load(settings.packages)
        try:
            tokens = Tokens.load(settings.tokens)
        except (OSError, ValueError) as e:
            raise _TokenFile(str(e)) from e
        driver = drivers.make(settings.driver, settings.store)
        served = {driver.name: driver}
        reconciler = Reconciler(store, served, loaded.platforms, loaded.probes, Provider(os.environ),
                                workers=settings.workers)
        app = create_app(store=store, loaded=loaded, drivers=served, default_driver=driver.name,
                         reconciler=reconciler, tokens=tokens, build=version("fylgja-core"), closing=closing)
    except BaseException:
        store.close()
        raise
    return app, store


def _refused(message: str, *args: object, **kw: object) -> None:
    _log.error(message, *args, **logs.fields(**kw))


def _listener(host: str, port: int) -> socket.socket:
    """A socket listening on `host:port`, its family the host's; `OSError` (a `gaierror` for a
    host that does not resolve) when it cannot be had."""
    family, _, _, _, address = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, flags=socket.AI_PASSIVE)[0]
    return socket.create_server(address[:2], family=family)


def main(argv: Sequence[str] | None = None) -> int:
    """Serve API 1 until uvicorn is stopped; the exit status (the module's docstring lists them)."""
    argparse.ArgumentParser(
        prog="fylgja-core-server",
        description="Serve API 1 and run the reconcile loop over one store. Every setting is a FYLGJA_* "
                    "variable: FYLGJA_STORE, FYLGJA_PACKAGES and FYLGJA_TOKENS, and FYLGJA_LISTEN, FYLGJA_DRIVER "
                    "and FYLGJA_WORKERS with their defaults (CONTRIBUTING.md, \"Running the core\").",
    ).parse_args(argv)
    logs.configure()
    try:
        settings = config.from_environ(os.environ)
    except Misconfigured as e:
        _refused("cannot start: %s", e, variable=e.variable, rule=e.rule)
        return 2
    closing = threading.Event()
    try:
        app, store = build_app(settings, closing=closing)
    except Locked as e:
        _refused("cannot start: %s", e.detail, variable="FYLGJA_STORE")
        return 1
    except Rejected as e:
        _refused("cannot start: a package is refused: %s", e, variable="FYLGJA_PACKAGES", rule=e.problems[0].rule)
        return 2
    except _TokenFile as e:
        _refused("cannot start: the token file cannot be read: %s", e, variable="FYLGJA_TOKENS")
        return 2
    except KeyError as e:
        _refused("cannot start: %s", e.args[0], variable="FYLGJA_DRIVER")
        return 2
    except OSError as e:
        _refused("cannot start: %s", e, error=type(e).__name__)
        return 2
    host, port = settings.listen
    try:
        listener = _listener(host, port)
    except OSError as e:  # uvicorn would exit 3 for it: it is the address's fault, so the settings'
        store.close()
        _refused("cannot start: FYLGJA_LISTEN names an address it cannot listen on: %s", e.strerror or e,
                 variable="FYLGJA_LISTEN", error=type(e).__name__)
        return 2
    _log.info("serving API 1 on %s:%d over the store %s, driver %s, %d workers", host, port, settings.store,
              settings.driver, settings.workers, **logs.fields(driver=settings.driver, workers=settings.workers))
    config_ = uvicorn.Config(app, host=host, port=port, log_config=None, access_log=False,
                             timeout_graceful_shutdown=GRACE_S)
    try:
        _Server(config_, closing).run(sockets=[listener])
    except KeyboardInterrupt:  # uvicorn shut down gracefully, then raised the SIGINT it caught
        _log.info("stopped by SIGINT")
        return 130
    except SystemExit:  # uvicorn's startup failure, once the address is bound: the lifespan's, logged above
        _refused("cannot start: the application did not start; the lines above say why")
        return 1
    finally:
        listener.close()
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
