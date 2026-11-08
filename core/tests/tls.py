"""A certificate and its key for the pure tier's TLS tests (D-063), made by `openssl` under a
test's own directory, never in the tree: one self-signed certificate for `IP:127.0.0.1`, good for
two days, and its key encrypted where a test needs one. Without `openssl` on the path a test that
needs them is skipped, and fails when `CI` is set, where it must run. `served` runs a server over
them, as `fylgja-core-server` serves TLS."""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from starlette.applications import Starlette

from fylgja_core.config import Settings
from fylgja_core.server import __main__ as server

PASSPHRASE = "fixture-passphrase-not-a-credential"
"""What `encrypted` encrypts a key under, handed to `openssl` through its environment."""
START_S = 10.0
"""How long `served` waits for its server to start."""


def _openssl() -> str:
    openssl = shutil.which("openssl")
    if openssl is None:
        if os.environ.get("CI"):
            pytest.fail("openssl is not on the path, and CI runs the TLS tests")
        pytest.skip("openssl is not on the path")
    return openssl


def pair(directory: Path) -> tuple[Path, Path]:
    """A certificate and its key, `cert.pem` and `key.pem` under `directory` (made if absent), the
    key at mode `0600`."""
    openssl = _openssl()
    directory.mkdir(parents=True, exist_ok=True)
    cert, key = directory / "cert.pem", directory / "key.pem"
    subprocess.run([openssl, "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes",
                    "-days", "2", "-subj", "/CN=fylgja-test", "-addext", "subjectAltName=IP:127.0.0.1",
                    "-keyout", str(key), "-out", str(cert)], check=True, capture_output=True)
    key.chmod(0o600)
    return cert, key


def encrypted(key: Path) -> Path:
    """`key` encrypted under `PASSPHRASE`, as `key-encrypted.pem` beside it at mode `0600`."""
    out = key.with_name("key-encrypted.pem")
    subprocess.run([_openssl(), "pkey", "-in", str(key), "-out", str(out), "-aes256",
                    "-passout", "env:FIXTURE_PASSPHRASE"],
                   check=True, capture_output=True, env={**os.environ, "FIXTURE_PASSPHRASE": PASSPHRASE})
    out.chmod(0o600)
    return out


@contextlib.contextmanager
def served(app: Starlette, pair: tuple[Path, Path], closing: threading.Event | None = None) -> Iterator[int]:
    """`app` served over TLS with `pair` as `fylgja-core-server` serves it, by its `_Server` over its
    `_config`, on a free loopback port in a thread of its own: the port. `closing` is set as the server
    begins to stop. Leaving stops the server, whatever the body raised."""
    # `_config` reads the listen address and the pair alone; the rest of the settings are `main`'s.
    settings = Settings(store=Path(os.devnull), listen=("127.0.0.1", 0), driver="containerlab", workers=1,
                        step_wait_s=1, resync_s=1, packages=(), tokens=Path(os.devnull), tls=pair)
    uv = server._Server(server._config(app, settings), closing or threading.Event())
    thread = threading.Thread(target=uv.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + START_S
        while not uv.started:
            assert thread.is_alive() and time.monotonic() < deadline, "the server did not start"
            time.sleep(0.01)
        yield uv.servers[0].sockets[0].getsockname()[1]
    finally:
        uv.should_exit = True
        thread.join(timeout=server.GRACE_S * 2)
    assert not thread.is_alive(), "the server did not stop"
