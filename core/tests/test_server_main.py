"""fylgja-core-server: a start refused by name when its settings are not whole, the application
it builds over the store its settings name, held for one core by a lock or a Lease, and the
process uvicorn serves, over TLS when it is given a certificate and key."""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import errno
import functools
import json
import logging
import os
import shlex
import signal
import socket
import ssl
import subprocess
import sys
import threading
import time
import tomllib
import types
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
import tls
import uvicorn
from fake_leases import FakeLeases
from fake_s3 import FakeS3
from fakes import FakeDriver
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Route
from starlette.testclient import TestClient
from test_containerlab_cli import gone_within

from fylgja_core import config, kubeapi, lease, packages
from fylgja_core import drivers as registry
from fylgja_core.client import messages
from fylgja_core.config import Misconfigured, Settings
from fylgja_core.containerlab.driver import EVENTS_ARGV
from fylgja_core.driver import Driver
from fylgja_core.lease import Lease, Record, Refused
from fylgja_core.local_store import LocalStore
from fylgja_core.object_store import ObjectStore
from fylgja_core.reconcile import Reconciler
from fylgja_core.s3 import S3
from fylgja_core.server import __main__ as server
from fylgja_core.server import auth
from fylgja_core.store import Locked

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "main-test-token"
S3_KEYS = ("AKIDEXAMPLE", "fixture-secret-not-a-credential")
DEADLINE_S = 10.0
IDENTITY = "core-0"
"""The holder `main` takes the Lease as, in place of the host's name."""


def until(done: Any, what: str) -> None:
    """Poll `done()` until it is true, failing after `DEADLINE_S`."""
    deadline = time.monotonic() + DEADLINE_S
    while not done():
        assert time.monotonic() < deadline, f"{what} did not happen within {DEADLINE_S:g}s"
        time.sleep(0.01)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    """Put back the root logger's handlers and level, which `main`'s `logs.configure` replaces."""
    root = logging.getLogger()
    saved, level = root.handlers[:], root.level
    yield
    root.handlers[:] = saved
    root.setLevel(level)


STUB_DOCKER = """#!/bin/sh
# The pure tier's docker (test_server_main.py): it records each call, its pid and its arguments a line, tab-separated,
# lists no lab, and follows events until it is killed. Anything else is not the driver's to ask here.
line=$$
for arg in "$@"; do line="$line	$arg"; done
printf '%s\\n' "$line" >> {calls}
case "$1" in
  events) exec sleep 600 ;;
  ps) exit 0 ;;
esac
echo "the stub docker answers no $1" >&2
exit 1
"""


def docker_calls(tmp_path: Path) -> list[tuple[int, list[str]]]:
    """Each call of the stub `docker` the `environ` fixture puts first on `PATH`: its pid and its command line."""
    path = tmp_path / "docker.calls"
    if not path.exists():
        return []
    lines = path.read_text().split("\n")[:-1]  # a line not yet ended is not yet a call
    return [(int(pid), ["docker", *args]) for pid, *args in (line.split("\t") for line in lines)]


def kill_stub_followers(tmp_path: Path) -> None:
    """Kill each `docker events` the stub still runs, its pid now `sleep`'s, whatever ended the test."""
    for pid, _ in docker_calls(tmp_path):
        try:
            argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        except OSError:
            continue  # gone
        if Path(argv[0].decode(errors="replace")).name == "sleep":
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)


def followers_of_this_process() -> list[int]:
    """This process's children that lead a session of their own, as each command the local driver runs does."""
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            state, ppid, _, session = (entry / "stat").read_text().rpartition(")")[2].split()[:4]
        except (OSError, ValueError):
            continue
        if int(ppid) == os.getpid() and int(session) == int(entry.name) and state != "Z":
            found.append(int(entry.name))
    return found


@pytest.fixture
def environ(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, str]]:
    """A whole environment for the server, set in the process's, every other FYLGJA_* variable unset. A stub `docker`
    goes first on `PATH`, which `cli.environment` passes to every command the local driver runs, in this process's
    lifespans and in a server it starts alike: the pure tier never runs the host's `docker` (`docker_calls`)."""
    for name in [n for n in os.environ if n.startswith("FYLGJA_")]:
        monkeypatch.delenv(name)
    tokens = tmp_path / "tokens"
    tokens.write_text(f"{auth.hash_token(TOKEN)} tester\n")
    stub = tmp_path / "bin" / "docker"
    stub.parent.mkdir()
    stub.write_text(STUB_DOCKER.replace("{calls}", shlex.quote(str(tmp_path / "docker.calls"))))
    stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{stub.parent}:{os.environ.get('PATH', os.defpath)}")
    values = {"FYLGJA_STORE": str(tmp_path / "store"), "FYLGJA_PACKAGES": f"{ROOT / 'psp'}:{ROOT / 'probes'}",
              "FYLGJA_TOKENS": str(tokens), "FYLGJA_LISTEN": "127.0.0.1:7651"}
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    yield values
    kill_stub_followers(tmp_path)


def settings(environ: dict[str, str]) -> Settings:
    return config.from_environ(environ)


def logged(err: str) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = [json.loads(line) for line in err.splitlines()]
    return lines


def test_an_empty_environment_exits_2_naming_the_variable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in [n for n in os.environ if n.startswith("FYLGJA_")]:
        monkeypatch.delenv(name)
    assert server.main([]) == 2
    (line,) = logged(capsys.readouterr().err)
    assert (line["level"], line["variable"], line["rule"]) == ("ERROR", "FYLGJA_STORE", "settings.missing")
    assert "FYLGJA_STORE" in line["message"]


def test_python_run_optimised_exits_2_before_the_settings_are_read(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`-O` and `PYTHONOPTIMIZE` strip the assert inside asyncio that drops a connection accepted in
    the turn before a lost Lease's cut (the facts), so the server does not start optimised."""
    monkeypatch.setattr(server, "_optimised", lambda: True)
    monkeypatch.setenv("FYLGJA_STORE", "")  # no setting is read: the refusal comes first
    assert server.main([]) == 2
    (line,) = logged(capsys.readouterr().err)
    assert (line["level"], line["rule"]) == ("ERROR", "server.optimised")
    assert "PYTHONOPTIMIZE" in line["message"] and "variable" not in line


class Endpoint:
    """`server.S3` in a test: `connect` makes the store's client over `fake`, an S3 endpoint in
    memory, keeping what it was given but the keys (`made`) and each HTTP client it opened
    (`http`), so a test sees it closed."""

    def __init__(self, fake: FakeS3) -> None:
        self.fake = fake
        self.made: list[tuple[str, str, str, Path | None]] = []
        self.http: list[httpx.Client] = []

    def connect(self, endpoint: str, bucket: str, access_key: str, secret_key: str, region: str = "us-east-1",
                ca: Path | None = None) -> S3:
        self.made.append((endpoint, bucket, region, ca))
        http = httpx.Client(transport=httpx.MockTransport(self.fake.handler))
        self.http.append(http)
        return S3(http, endpoint, bucket, access_key, secret_key, region)


def object_store(environ: dict[str, str], prefix: str = "dev/core", ca: Path | None = None) -> Settings:
    """`environ`'s settings with an object store under a Lease, on the clabernetes driver."""
    access_key, secret_key = S3_KEYS
    location = config.S3Location("fylgja", prefix, "http://s3.example.internal:7070", "us-east-1", access_key,
                                 secret_key, ca)
    return dataclasses.replace(settings(environ), store=location, lease="fylgja-core", driver="clabernetes",
                               clabernetes_namespace="c9s", pod_cidr="198.51.100.0/24")


def made_drivers(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Driver, Path | None]]:
    """Each driver `build_app` makes, with the root it was given: a `FakeDriver` under the name asked
    for, so no cluster is reached."""
    made: list[tuple[Driver, Path | None]] = []

    def make(name: str, *, root: Path | None, **kw: Any) -> Driver:
        made.append((FakeDriver(name), root))
        return made[-1][0]

    monkeypatch.setattr(registry, "make", make)
    return made


def closed_drivers(monkeypatch: pytest.MonkeyPatch) -> list[Driver]:
    """Each driver the server closes (`drivers.close`), in order."""
    closed: list[Driver] = []

    async def close(driver: Driver) -> None:
        closed.append(driver)

    monkeypatch.setattr(registry, "close", close)
    return closed


@pytest.fixture
def leases(monkeypatch: pytest.MonkeyPatch) -> FakeLeases:
    """The Lease `main` takes, `FYLGJA_LEASE`, held in memory: `FakeLeases` in place of the
    `KubeLeases` it makes, under the holder `IDENTITY`, renewed every 1 s for 60 s: no test of
    `main` waits on a renewal, and a host stalled for a second loses nothing."""
    fake = FakeLeases()

    def kube_leases(name: str, namespace: str | None = None) -> FakeLeases:
        assert (name, namespace) == (fake.name, None)  # the core's namespace, the client's default
        return fake

    monkeypatch.setattr(lease, "KubeLeases", kube_leases)
    monkeypatch.setattr(lease, "Lease", functools.partial(Lease, renew_s=1.0, duration_s=60.0))
    monkeypatch.setattr(lease, "identity", lambda: IDENTITY)
    monkeypatch.setenv("FYLGJA_LEASE", fake.name)
    return fake


def test_build_app_checks_the_settings_it_is_given_first(
    environ: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Settings given whole, not read by `from_environ`, are checked too: what one rules out of another is refused by
    # name before the object store is opened.
    endpoint = Endpoint(FakeS3("fylgja"))
    monkeypatch.setattr(server, "S3", endpoint)
    base = object_store(environ)
    with pytest.raises(Misconfigured) as e:
        server.build_app(dataclasses.replace(base, lease=None))
    assert e.value.variable == "FYLGJA_LEASE"
    with pytest.raises(Misconfigured) as e:
        server.build_app(dataclasses.replace(base, driver="containerlab"))
    assert e.value.variable == "FYLGJA_DRIVER"
    assert endpoint.made == [] and endpoint.fake.requests == []


def test_build_app_opens_the_object_store_its_settings_name(
    environ: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    endpoint = Endpoint(FakeS3("fylgja"))
    monkeypatch.setattr(server, "S3", endpoint)
    opened: list[str] = []
    open_ = ObjectStore.open

    def recorded(s3: S3, prefix: str = "") -> ObjectStore:
        opened.append(prefix)
        return open_(s3, prefix)

    monkeypatch.setattr(ObjectStore, "open", recorded)
    made = made_drivers(monkeypatch)
    ca = Path("/etc/fylgja/s3-ca.pem")  # handed to S3.connect, which this test's endpoint never reads
    app, store = server.build_app(object_store(environ, "dev/core", ca))
    try:
        assert isinstance(store, ObjectStore)
        with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
            assert client.get("/v1/version").json()["api"] == "1"
            drivers = client.get("/v1/drivers").json()["drivers"]
    finally:
        store.close()
    assert opened == ["dev/core"]
    assert endpoint.made == [("http://s3.example.internal:7070", "fylgja", "us-east-1", ca)]
    assert [(d["name"], d["default"]) for d in drivers] == [("clabernetes", True)]
    assert [root for _, root in made] == [None]  # an object store has no directory to give a driver
    assert [http.is_closed for http in endpoint.http] == [True]
    assert not Path(environ["FYLGJA_STORE"]).exists()


@pytest.mark.parametrize(("fault", "status", "variable", "rule"), [
    ("ignores-a-condition", 2, "FYLGJA_S3_ENDPOINT", "store.unconditional"),
    ("refuses-the-keys", 1, "FYLGJA_STORE", None),
    ("refuses-the-first-put", 1, "FYLGJA_STORE", None),
], ids=["unconditional", "s3-error", "precondition-failed"])
def test_an_object_store_that_does_not_open_is_refused_by_name_with_nothing_left_open(
    environ: dict[str, str], leases: FakeLeases, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    fault: str, status: int, variable: str, rule: str | None,
) -> None:
    access_key, secret_key = S3_KEYS
    for name, value in {"FYLGJA_STORE": "s3://fylgja/dev/core", "FYLGJA_S3_ENDPOINT": "http://s3.example.internal:7070",
                        "FYLGJA_S3_ACCESS_KEY": access_key, "FYLGJA_S3_SECRET_KEY": secret_key,
                        "FYLGJA_DRIVER": "clabernetes", "FYLGJA_CLABERNETES_NAMESPACE": "c9s",
                        "FYLGJA_POD_CIDR": "198.51.100.0/24"}.items():
        monkeypatch.setenv(name, value)
    fake = FakeS3("fylgja")
    if fault == "ignores-a-condition":
        fake.ignore.add("if-none-match")  # the proof's second put is accepted: Unconditional
    elif fault == "refuses-the-keys":
        fake.forced.append((403, "AccessDenied"))  # an S3Error
    else:
        fake.forced.append((412, "PreconditionFailed"))  # an S3Error too, raised by the proof's first put
    endpoint = Endpoint(fake)
    monkeypatch.setattr(server, "S3", endpoint)
    monkeypatch.setattr(registry, "make", lambda *args, **kw: pytest.fail("a driver was made"))
    assert server.main([]) == status
    err = capsys.readouterr().err
    leaked = any(key in err for key in S3_KEYS)  # outside the assert, which would print what it compares
    assert not leaked
    (line,) = [entry for entry in logged(err) if entry["level"] == "ERROR"]
    assert (line["variable"], line.get("rule")) == (variable, rule)
    assert [http.is_closed for http in endpoint.http] == [True]
    # Taken and not released: a start that fails after the Lease is left to this pod's next start.
    assert leases.record is not None and leases.record.holder == IDENTITY and leases.closed


@pytest.mark.parametrize(("ca", "reason"), [
    ("absent", "No such file or directory"),
    ("not-a-bundle", "NO_CERTIFICATE_OR_CRL_FOUND"),
])
def test_a_ca_bundle_that_does_not_load_exits_2_naming_fylgja_s3_ca(
    environ: dict[str, str], leases: FakeLeases, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], ca: str, reason: str,
) -> None:
    path = tmp_path / "s3-ca.pem"
    if ca == "not-a-bundle":
        path.write_text("fixture-ca-content\n")
    access_key, secret_key = S3_KEYS
    for name, value in {"FYLGJA_STORE": "s3://fylgja", "FYLGJA_S3_ENDPOINT": "https://s3.example.internal:7070",
                        "FYLGJA_S3_ACCESS_KEY": access_key, "FYLGJA_S3_SECRET_KEY": secret_key,
                        "FYLGJA_S3_CA": str(path), "FYLGJA_DRIVER": "clabernetes",
                        "FYLGJA_CLABERNETES_NAMESPACE": "c9s", "FYLGJA_POD_CIDR": "198.51.100.0/24"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(registry, "make", lambda *args, **kw: pytest.fail("a driver was made"))
    assert server.main([]) == 2
    err = capsys.readouterr().err
    shown = "fixture-ca-content" in err or any(key in err for key in S3_KEYS)  # outside the assert, as above
    assert not shown
    (line,) = [entry for entry in logged(err) if entry["level"] == "ERROR"]
    assert line["variable"] == "FYLGJA_S3_CA"
    assert line["message"] == f"cannot start: the CA bundle FYLGJA_S3_CA names cannot be loaded: {reason}"


def test_main_takes_the_lease_before_it_opens_the_store(
    environ: dict[str, str], leases: FakeLeases, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    seen: list[tuple[list[str], bool]] = []  # at build_app: the holders the Lease was written with, and its API closed
    build_app = server.build_app

    def recorded(settings: Settings, *, closing: threading.Event | None = None) -> Any:
        seen.append(([write.holder for write in leases.written], leases.closed))
        return build_app(settings, closing=closing)

    monkeypatch.setattr(server, "build_app", recorded)
    monkeypatch.setenv("FYLGJA_LISTEN", f"127.0.0.1:{free_port()}")
    monkeypatch.setattr(server._Server, "run", lambda self, sockets=None: None)
    assert server.main([]) == 0
    assert seen == [([IDENTITY], True)]  # taken, and its client closed so uvicorn's loop makes its own
    infos = [entry["message"] for entry in logged(capsys.readouterr().err) if entry["level"] == "INFO"]
    assert "holding the Lease fylgja-core as core-0" in infos
    LocalStore.open(Path(environ["FYLGJA_STORE"])).close()


def test_waiting_for_a_lease_another_holds_opens_nothing_and_ctrl_c_returns_130(
    environ: dict[str, str], leases: FakeLeases, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Its record is taken once seen unchanged for 60 s: never within this test, whatever the host's load.
    monkeypatch.setattr(lease, "Lease", functools.partial(Lease, renew_s=0.1, duration_s=60.0))
    port = free_port()
    monkeypatch.setenv("FYLGJA_LISTEN", f"127.0.0.1:{port}")
    monkeypatch.setattr(server, "build_app", lambda *args, **kw: pytest.fail("the application was built"))
    store = Path(environ["FYLGJA_STORE"])
    waiting: list[bool] = []  # at each read: whether the port binds and the store is not there

    class Watched(FakeLeases):
        async def read(self) -> Record | None:
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", port))
            waiting.append(not store.exists())
            return await super().read()

    watched = Watched()
    watched.set("other")
    watched.read_errors = [None, None, KeyboardInterrupt()]
    monkeypatch.setattr(lease, "KubeLeases", lambda name, namespace=None: watched)
    assert server.main([]) == 130
    assert waiting == [True, True, True] and not store.exists()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))  # nothing listens on it
    assert (watched.writes, watched.closed) == (0, True)
    infos = [entry["message"] for entry in logged(capsys.readouterr().err) if entry["level"] == "INFO"]
    assert [message for message in infos if "other" in message] == ["waiting for the Lease fylgja-core, held by other"]


def test_a_lease_the_core_may_not_take_exits_2_naming_fylgja_lease(
    environ: dict[str, str], leases: FakeLeases, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    leases.write_errors = [Refused("create Lease fylgja-core: 403 Forbidden", status=403)]
    monkeypatch.setattr(server, "build_app", lambda *args, **kw: pytest.fail("the application was built"))
    assert server.main([]) == 2
    (line,) = [entry for entry in logged(capsys.readouterr().err) if entry["level"] == "ERROR"]
    assert line["variable"] == "FYLGJA_LEASE"
    assert line["message"] == ("cannot start: the Lease fylgja-core cannot be taken: create Lease fylgja-core: 403 "
                               "Forbidden")
    assert leases.closed


def test_a_lease_with_no_cluster_to_reach_exits_2_naming_kubeconfig(
    environ: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The Lease's own API, `KubeLeases`, with no service account and no KUBECONFIG: it can make no client.
    monkeypatch.setattr(kubeapi, "SERVICE_ACCOUNT", tmp_path / "no-service-account")
    monkeypatch.delenv("KUBECONFIG", raising=False)
    monkeypatch.setenv("FYLGJA_LEASE", "fylgja-core")
    monkeypatch.setattr(server, "build_app", lambda *args, **kw: pytest.fail("the application was built"))
    assert server.main([]) == 2
    (line,) = [entry for entry in logged(capsys.readouterr().err) if entry["level"] == "ERROR"]
    assert line["variable"] == "KUBECONFIG"
    assert line["message"] == ("cannot start: the Lease fylgja-core cannot be taken: KUBECONFIG is not set, or is "
                               f"empty, and there is no service account at {tmp_path / 'no-service-account'}: the core "
                               "can reach no cluster")


def test_a_lease_lost_before_the_server_serves_exits_1_releasing_nothing(
    environ: dict[str, str], leases: FakeLeases, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("FYLGJA_LISTEN", f"127.0.0.1:{free_port()}")
    build_app = server.build_app

    def taken_meanwhile(settings: Settings, *, closing: threading.Event | None = None) -> Any:
        built = build_app(settings, closing=closing)
        leases.set("b")  # another core took it while the application was built
        return built

    monkeypatch.setattr(server, "build_app", taken_meanwhile)
    assert server.main([]) == 1
    (line,) = [entry for entry in logged(capsys.readouterr().err) if entry["level"] == "ERROR"]
    assert (line["rule"], line["lease"]) == ("lease.lost", "fylgja-core")
    assert line["message"] == "the server stops at once: the Lease fylgja-core is held by b"
    assert [write.holder for write in leases.written] == [IDENTITY, IDENTITY] and leases.closed
    LocalStore.open(Path(environ["FYLGJA_STORE"])).close()


def test_ctrl_c_while_the_store_is_opened_returns_130_with_the_lease_released(
    environ: dict[str, str], leases: FakeLeases, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def interrupted(*args: Any, **kw: Any) -> Any:
        raise KeyboardInterrupt  # Ctrl-C once the store is open: an object store's proof widens this window

    monkeypatch.setattr(packages, "load", interrupted)
    monkeypatch.setenv("FYLGJA_LISTEN", f"127.0.0.1:{free_port()}")
    assert server.main([]) == 130
    err = capsys.readouterr().err
    assert "Traceback" not in err
    infos = [entry["message"] for entry in logged(err) if entry["level"] == "INFO"]
    assert infos[-2:] == ["released the Lease fylgja-core", "stopped by SIGINT"]
    assert [write.holder for write in leases.written] == [IDENTITY, ""] and leases.closed
    LocalStore.open(Path(environ["FYLGJA_STORE"])).close()  # the store it opened is closed again


@pytest.mark.parametrize(("failing", "status"), [(1, 0), (2, 130)], ids=["after-the-take", "after-the-release"])
def test_a_lease_client_close_that_raises_in_the_start_is_one_warning_and_the_status_stands(
    environ: dict[str, str], leases: FakeLeases, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    failing: int, status: int,
) -> None:
    # `main` closes the Lease's client after the take, and after the release where the start is stopped.
    closes: list[str] = []
    close = leases.close

    async def failing_one() -> None:
        await close()
        closes.append("closed")
        if len(closes) == failing:
            raise OSError("fixture text, never logged")

    def interrupted(*args: Any, **kw: Any) -> Any:
        raise KeyboardInterrupt  # Ctrl-C once the store is open: the Lease released, its client closed again

    monkeypatch.setattr(leases, "close", failing_one)
    if failing == 2:
        monkeypatch.setattr(packages, "load", interrupted)
    monkeypatch.setenv("FYLGJA_LISTEN", f"127.0.0.1:{free_port()}")
    monkeypatch.setattr(server._Server, "run", lambda self, sockets=None: None)
    assert server.main([]) == status
    err = capsys.readouterr().err
    assert "Traceback" not in err and "fixture text" not in err
    entries = logged(err)
    assert [entry["message"] for entry in entries if entry["level"] == "WARNING"] == [
        "the Lease's client was not closed (OSError)"]
    assert len(closes) == failing and leases.written[0].holder == IDENTITY
    LocalStore.open(Path(environ["FYLGJA_STORE"])).close()  # the store is closed


class Unhandled(Exception):
    """SIGTERM reached the `sigterm` fixture's guard: no handler of `main`'s took it."""


@pytest.fixture
def sigterm() -> Iterator[Callable[[], None]]:
    """A sender of SIGTERM to this process alone, as the kubelet's to the core's PID 1, under a
    guard: where `main` has no handler of its own, the signal raises `Unhandled` in place of
    ending the test run. `main` puts back the handler it found, the guard, before it returns."""

    def guard(signum: int, frame: Any) -> None:
        raise Unhandled("SIGTERM reached no handler of main's")

    before = signal.signal(signal.SIGTERM, guard)
    try:
        yield lambda: os.kill(os.getpid(), signal.SIGTERM)
        assert signal.getsignal(signal.SIGTERM) is guard, "main did not put back the SIGTERM handler it found"
    finally:
        signal.signal(signal.SIGTERM, before)


def test_sigterm_while_waiting_for_a_lease_another_holds_returns_143_with_nothing_opened_or_released(
    environ: dict[str, str], leases: FakeLeases, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    sigterm: Callable[[], None],
) -> None:
    # The wait is cut as Ctrl-C cuts it: a pod stopped while it waits stops, where PID 1 would ignore the signal.
    monkeypatch.setattr(lease, "Lease", functools.partial(Lease, renew_s=0.1, duration_s=60.0))
    monkeypatch.setattr(server, "build_app", lambda *args, **kw: pytest.fail("the application was built"))
    reads: list[Record | None] = []

    class Watched(FakeLeases):
        async def read(self) -> Record | None:
            if len(reads) > 2:  # the read SIGTERM was sent in answered: a handler that no longer cuts the wait fails
                pytest.fail("SIGTERM did not cut the wait for the Lease")
            if len(reads) == 2:
                sigterm()
            reads.append(await super().read())
            return reads[-1]

    watched = Watched()
    watched.set("other")
    monkeypatch.setattr(lease, "KubeLeases", lambda name, namespace=None: watched)
    assert server.main([]) == 143
    assert not Path(environ["FYLGJA_STORE"]).exists()
    assert (watched.writes, watched.closed) == (0, True)  # nothing held, so nothing released; its client closed
    err = capsys.readouterr().err
    assert "Traceback" not in err
    infos = [entry["message"] for entry in logged(err) if entry["level"] == "INFO"]
    assert infos[-1] == "stopped by SIGTERM while waiting for the Lease fylgja-core"


def test_sigterm_while_the_store_is_opened_returns_143_with_the_store_closed_and_the_lease_released(
    environ: dict[str, str], leases: FakeLeases, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    sigterm: Callable[[], None],
) -> None:
    def terminated(*args: Any, **kw: Any) -> Any:
        sigterm()  # once the store is open: an object store's proof widens this window
        pytest.fail("SIGTERM did not end the store's open")

    monkeypatch.setattr(packages, "load", terminated)
    monkeypatch.setenv("FYLGJA_LISTEN", f"127.0.0.1:{free_port()}")
    assert server.main([]) == 143
    err = capsys.readouterr().err
    assert "Traceback" not in err
    infos = [entry["message"] for entry in logged(err) if entry["level"] == "INFO"]
    assert infos[-2:] == ["released the Lease fylgja-core", "stopped by SIGTERM"]
    assert [write.holder for write in leases.written] == [IDENTITY, ""] and leases.closed
    LocalStore.open(Path(environ["FYLGJA_STORE"])).close()  # the store it opened is closed again


def test_sigterm_between_the_stores_open_and_uvicorns_run_returns_143_with_all_closed_and_the_lease_released(
    environ: dict[str, str], leases: FakeLeases, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    sigterm: Callable[[], None],
) -> None:
    closed = closed_drivers(monkeypatch)

    def listener(host: str, port: int) -> socket.socket:
        sigterm()  # as the address is bound: the window between the store's open and uvicorn's run
        pytest.fail("SIGTERM did not end the start")

    monkeypatch.setattr(server, "_listener", listener)
    try:
        status = server.main([])
    except KeyboardInterrupt:
        pytest.fail("SIGTERM, taken as Ctrl-C, escaped main")
    assert status == 143
    err = capsys.readouterr().err
    assert "Traceback" not in err
    infos = [entry["message"] for entry in logged(err) if entry["level"] == "INFO"]
    assert infos[-2:] == ["released the Lease fylgja-core", "stopped by SIGTERM"]
    assert [write.holder for write in leases.written] == [IDENTITY, ""] and leases.closed and len(closed) == 1
    LocalStore.open(Path(environ["FYLGJA_STORE"])).close()  # the store it opened is closed again


def test_ctrl_c_before_anything_is_held_returns_130_with_no_traceback(
    environ: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    def interrupted(environ: Any) -> Settings:
        raise KeyboardInterrupt  # as the settings are read: nothing is held yet

    monkeypatch.setattr(config, "from_environ", interrupted)
    try:
        status = server.main([])
    except KeyboardInterrupt:
        pytest.fail("Ctrl-C escaped main")
    assert status == 130
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert [entry["message"] for entry in logged(err)] == ["stopped by SIGINT"]
    assert not Path(environ["FYLGJA_STORE"]).exists()


def test_ctrl_c_as_the_starts_closing_event_is_made_takes_no_lease(
    environ: dict[str, str], leases: FakeLeases, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    # The event the application's streams end by is made before the Lease is taken: a signal landing as it is
    # made, a call into Python where a pending signal is handled, finds nothing held, so main's last resort holds.
    made: list[int] = []

    def event() -> threading.Event:
        made.append(1)
        if len(made) == 2:  # main's `terminated` is the first, `_start`'s `closing` the second
            raise KeyboardInterrupt
        return threading.Event()

    monkeypatch.setattr(server, "threading", types.SimpleNamespace(Event=event))
    monkeypatch.setenv("FYLGJA_LISTEN", f"127.0.0.1:{free_port()}")
    try:
        status = server.main([])
    except KeyboardInterrupt:
        pytest.fail("Ctrl-C escaped main")
    assert status == 130 and len(made) == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err and [entry["message"] for entry in logged(err)] == ["stopped by SIGINT"]
    assert leases.written == [] and not Path(environ["FYLGJA_STORE"]).exists()  # nothing taken, nothing opened


@pytest.mark.parametrize("raised_again", [True, False], ids=["raised-again", "raised-again-to-nothing"])
def test_sigterm_while_serving_stops_gracefully_and_returns_143_with_the_lease_released(
    environ: dict[str, str], leases: FakeLeases, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    sigterm: Callable[[], None], raised_again: bool,
) -> None:
    """uvicorn takes SIGTERM while it serves, stops gracefully, then puts back the handler it found and raises the
    signal again (uvicorn 0.54.0, `Server.capture_signals`): `main`'s, which ends the run as Ctrl-C does. Where that
    raise reaches nothing, as the default handler of a container's PID 1 ignores it, `main` returns 143 all the same."""
    if not raised_again:
        monkeypatch.setattr(signal, "raise_signal", lambda sent: None)
    port = free_port()
    monkeypatch.setenv("FYLGJA_LISTEN", f"127.0.0.1:{port}")
    served: list[bool] = []

    def answers() -> bool:
        try:
            return httpx.get(f"http://127.0.0.1:{port}/v1/version", timeout=1.0).status_code == 200
        except httpx.TransportError:
            return False

    def stop_once_served() -> None:
        try:
            until(answers, "the server's first answer")
            served.append(True)
        finally:
            sigterm()  # answered or not, so a server that never answers is not left serving

    stopper = threading.Thread(target=stop_once_served, daemon=True)
    stopper.start()
    try:
        assert server.main([]) == 143
    finally:
        stopper.join(timeout=DEADLINE_S)
    assert served == [True]
    err = capsys.readouterr().err
    assert "Traceback" not in err
    infos = [entry["message"] for entry in logged(err) if entry["level"] == "INFO"]
    assert "released the Lease fylgja-core" in infos and infos[-1] == "stopped by SIGTERM"
    assert leases.written[0].holder == IDENTITY and leases.written[-1].holder == "" and leases.closed
    LocalStore.open(Path(environ["FYLGJA_STORE"])).close()  # the store is closed


@pytest.mark.parametrize(("sent", "status"), [(signal.SIGINT, 130), (signal.SIGTERM, 143)], ids=["SIGINT", "SIGTERM"])
def test_a_signal_while_serving_whose_raise_again_is_refused_stops_gracefully_with_its_status(
    environ: dict[str, str], leases: FakeLeases, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    sent: signal.Signals, status: int,
) -> None:
    """In a pod on the cluster a process may not signal itself: its AppArmor label is stacked, and `raise` answers
    EACCES (verified-facts.md). uvicorn's raise again of the signal it caught, once it has stopped gracefully, is then
    refused: `main` returns the signal's status all the same, the Lease released, with no traceback. The signal is sent
    under a guard, so one that reaches no handler of the server's fails the test and does not end the run."""

    def guard(signum: int, frame: Any) -> None:
        raise Unhandled(f"{signal.Signals(signum).name} reached no handler of the server's")

    def refused(signum: int) -> None:
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(signal, "raise_signal", refused)
    port = free_port()
    monkeypatch.setenv("FYLGJA_LISTEN", f"127.0.0.1:{port}")
    served: list[bool] = []

    def answers() -> bool:
        try:
            return httpx.get(f"http://127.0.0.1:{port}/v1/version", timeout=1.0).status_code == 200
        except httpx.TransportError:
            return False

    def stop_once_served() -> None:
        try:
            until(answers, "the server's first answer")
            served.append(True)
        finally:
            os.kill(os.getpid(), sent)

    before = signal.signal(sent, guard)
    stopper = threading.Thread(target=stop_once_served, daemon=True)
    try:
        stopper.start()
        assert server.main([]) == status
        assert signal.getsignal(sent) is guard, "main did not put back the handler it found"
    finally:
        stopper.join(timeout=DEADLINE_S)
        signal.signal(sent, before)
    assert served == [True]
    err = capsys.readouterr().err
    assert "Traceback" not in err
    infos = [entry["message"] for entry in logged(err) if entry["level"] == "INFO"]
    assert "released the Lease fylgja-core" in infos and infos[-1] == f"stopped by {sent.name}"
    assert leases.written[0].holder == IDENTITY and leases.written[-1].holder == "" and leases.closed
    LocalStore.open(Path(environ["FYLGJA_STORE"])).close()  # the store is closed


@pytest.mark.parametrize("what", ["the Lease's client", "the driver"])
def test_a_close_that_raises_as_the_server_stops_is_one_warning_and_the_status_stands(
    environ: dict[str, str], leases: FakeLeases, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    sigterm: Callable[[], None], what: str,
) -> None:
    closes: list[str] = []
    if what == "the driver":
        async def failing(driver: Driver) -> None:
            raise OSError("fixture text, never logged")

        monkeypatch.setattr(registry, "close", failing)
    else:
        close = leases.close

        async def failing_the_servers() -> None:
            await close()
            closes.append("closed")
            if len(closes) > 1:  # the server's, as it stops: the first is the take's
                raise OSError("fixture text, never logged")

        monkeypatch.setattr(leases, "close", failing_the_servers)
    port = free_port()
    monkeypatch.setenv("FYLGJA_LISTEN", f"127.0.0.1:{port}")

    def answers() -> bool:
        try:
            return httpx.get(f"http://127.0.0.1:{port}/v1/version", timeout=1.0).status_code == 200
        except httpx.TransportError:
            return False

    def stop_once_served() -> None:
        try:
            until(answers, "the server's first answer")
        finally:
            sigterm()

    stopper = threading.Thread(target=stop_once_served, daemon=True)
    stopper.start()
    try:
        assert server.main([]) == 143
    finally:
        stopper.join(timeout=DEADLINE_S)
    err = capsys.readouterr().err
    assert "Traceback" not in err and "fixture text" not in err
    entries = logged(err)
    warnings = [entry["message"] for entry in entries if entry["level"] == "WARNING"]
    assert warnings == [f"{what} was not closed (OSError)"]
    assert [entry["message"] for entry in entries if entry["level"] == "INFO"][-1] == "stopped by SIGTERM"
    assert leases.written[-1].holder == ""  # released before the close
    LocalStore.open(Path(environ["FYLGJA_STORE"])).close()  # the store is closed


def test_an_os_error_raised_while_the_server_serves_is_raised_as_it_is(environ: dict[str, str]) -> None:
    """`capture_signals` takes the refusal of uvicorn's raise again as no fault only once the server has stopped on a
    signal: an `OSError` raised while it serves, a `PermissionError` among them, is raised, signalled or not."""
    app, store = server.build_app(settings(environ))
    try:
        served = server._Server(uvicorn.Config(app, log_config=None), threading.Event())
        for signalled in (False, True):
            served.signalled = signalled
            for failure in (OSError("while it serves"), PermissionError(errno.EACCES, "while it serves")):
                with pytest.raises(type(failure), match="while it serves"), served.capture_signals():
                    raise failure
    finally:
        store.close()


@pytest.mark.parametrize(
    ("failure", "raised"),
    [(PermissionError(errno.EACCES, "Permission denied"), False), (OSError(errno.EINVAL, "Invalid argument"), True)],
    ids=["EACCES", "EINVAL"],
)
def test_only_the_refusal_of_the_raise_again_after_a_signalled_stop_is_no_fault(
    environ: dict[str, str], monkeypatch: pytest.MonkeyPatch, failure: OSError, raised: bool
) -> None:
    """The refusal read in a pod is EACCES, a `PermissionError`: that alone, once the server has stopped on a signal, is
    taken as a raise that reached no handler. Any other `OSError` from uvicorn's raise again is raised as it is."""

    def raise_again(signum: int) -> None:
        raise failure

    monkeypatch.setattr(signal, "raise_signal", raise_again)
    app, store = server.build_app(settings(environ))
    try:
        served = server._Server(uvicorn.Config(app, log_config=None), threading.Event())
        with contextlib.ExitStack() as expected:
            if raised:
                expected.enter_context(pytest.raises(OSError, match="Invalid argument"))
            with served.capture_signals():
                served.handle_exit(signal.SIGTERM, None)  # as uvicorn's handler does on the signal
        assert served.signalled and served.terminated.is_set()
    finally:
        store.close()


def test_the_application_answers_the_version_and_its_driver(environ: dict[str, str]) -> None:
    app, store = server.build_app(settings(environ))
    try:
        with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
            assert client.get("/v1/version").json()["api"] == "1"
            drivers = client.get("/v1/drivers").json()["drivers"]
    finally:
        store.close()
    assert [(d["name"], d["default"]) for d in drivers] == [("containerlab", True)]


def test_the_loop_follows_docker_events_through_the_stub_alone(environ: dict[str, str], tmp_path: Path) -> None:
    """The lifespan's local driver follows `docker events` (D-058), and in the pure tier that `docker` is the stub:
    the one command the driver started is the stub's, its pid the `sleep` the stub became, and it is gone once the
    lifespan has ended."""
    app, store = server.build_app(settings(environ))
    try:
        with TestClient(app):
            until(lambda: docker_calls(tmp_path), "the stub's docker events")
            ((pid, argv),) = docker_calls(tmp_path)
            assert argv == list(EVENTS_ARGV)
            until(lambda: followers_of_this_process() == [pid], "the follow, and it alone")
            assert Path(f"/proc/{pid}/cmdline").read_bytes() == b"sleep\x00600\x00"  # the stub's, not the host's docker
    finally:
        store.close()
    assert gone_within(pid, 1.0)
    assert followers_of_this_process() == []


def test_the_loop_resyncs_at_the_setting(environ: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[Reconciler] = []

    class Recorded(Reconciler):
        def __init__(self, *args: Any, **kw: Any) -> None:
            super().__init__(*args, **kw)
            built.append(self)

    monkeypatch.setattr(server, "Reconciler", Recorded)
    _, store = server.build_app(settings({**environ, "FYLGJA_RESYNC_S": "3600"}))
    store.close()
    assert [r.resync_s for r in built] == [3600]


def test_one_store_is_held_by_one_core_until_it_closes(environ: dict[str, str]) -> None:
    _, store = server.build_app(settings(environ))
    with pytest.raises(Locked):
        server.build_app(settings(environ))
    store.close()
    _, again = server.build_app(settings(environ))
    again.close()


def test_a_store_another_core_holds_exits_1_naming_the_holder(
    environ: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    held = LocalStore.open(Path(environ["FYLGJA_STORE"]))
    try:
        assert server.main([]) == 1
    finally:
        held.close()
    (line,) = [entry for entry in logged(capsys.readouterr().err) if entry["level"] == "ERROR"]
    assert str(os.getpid()) in line["message"]


def test_a_token_file_it_cannot_read_exits_2(
    environ: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    bad = tmp_path / "bad-tokens"
    bad.write_text(f"{TOKEN} tester\n")  # a token where its hash belongs
    monkeypatch.setenv("FYLGJA_TOKENS", str(bad))
    assert server.main([]) == 2
    err = capsys.readouterr().err
    shown = TOKEN in err  # compared outside the assert, so a failure prints no token
    assert not shown
    (line,) = [entry for entry in logged(err) if entry["level"] == "ERROR"]
    assert line["variable"] == "FYLGJA_TOKENS" and "line 1" in line["message"]
    LocalStore.open(Path(environ["FYLGJA_STORE"])).close()  # the store it opened is closed again


@pytest.fixture
def clabernetes(environ: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """`environ` under the clabernetes driver, off the cluster whatever the host running the
    tests: no service account, and `KUBECONFIG` unset."""
    monkeypatch.setattr(kubeapi, "SERVICE_ACCOUNT", tmp_path / "no-service-account")
    monkeypatch.delenv("KUBECONFIG", raising=False)
    values = {"FYLGJA_DRIVER": "clabernetes", "FYLGJA_CLABERNETES_NAMESPACE": "c9s", "FYLGJA_POD_CIDR": "10.244.0.0/16"}
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return {**environ, **values}


def test_the_clabernetes_driver_with_no_cluster_to_reach_exits_2_naming_kubeconfig(
    clabernetes: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert server.main([]) == 2
    (line,) = [entry for entry in logged(capsys.readouterr().err) if entry["level"] == "ERROR"]
    assert line["variable"] == "KUBECONFIG" and line["message"].startswith("cannot start: KUBECONFIG")
    LocalStore.open(Path(clabernetes["FYLGJA_STORE"])).close()  # the store it opened is closed again


def test_a_kubeconfig_whose_context_is_missing_exits_2_naming_kubeconfig(
    clabernetes: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "kubeconfig"
    path.write_text("apiVersion: v1\nkind: Config\nclusters: []\nusers: []\ncontexts: []\ncurrent-context: absent\n")
    monkeypatch.setenv("KUBECONFIG", str(path))
    assert server.main([]) == 2
    err = capsys.readouterr().err
    assert "Traceback" not in err
    (line,) = [entry for entry in logged(err) if entry["level"] == "ERROR"]
    assert line["variable"] == "KUBECONFIG"
    assert line["message"] == (f"cannot start: KUBECONFIG names {path}, which cannot be read as a kubeconfig "
                               "(ConfigError)")
    LocalStore.open(Path(clabernetes["FYLGJA_STORE"])).close()


def test_main_serves_the_application_with_uvicorn_and_closes_the_store(
    environ: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    port = free_port()  # main binds the address itself before uvicorn serves on it
    monkeypatch.setenv("FYLGJA_LISTEN", f"127.0.0.1:{port}")
    served: list[uvicorn.Config] = []
    monkeypatch.setattr(server._Server, "run", lambda self, sockets=None: served.append(self.config))
    assert server.main([]) == 0
    (config_,) = served
    assert (config_.host, config_.port, config_.log_config, config_.access_log) == ("127.0.0.1", port, None, False)
    assert config_.timeout_graceful_shutdown == server.GRACE_S
    # The cut at a loss rests on h11's protocol and asyncio's server (verified-facts.md): neither left to "auto",
    # which would take httptools or uvloop, were either installed.
    assert (config_.http, config_.loop) == ("h11", "asyncio")
    LocalStore.open(Path(environ["FYLGJA_STORE"])).close()
    assert all(isinstance(line, dict) for line in logged(capsys.readouterr().err))


def test_a_store_close_that_raises_as_the_server_ends_is_one_warning_and_the_status_stands(
    environ: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    build_app = server.build_app

    def unclosable(settings: Settings, *, closing: threading.Event | None = None) -> Any:
        app, store = build_app(settings, closing=closing)
        close = store.close

        def failing() -> None:
            close()
            raise OSError("fixture text, never logged")

        monkeypatch.setattr(store, "close", failing)
        return app, store

    monkeypatch.setattr(server, "build_app", unclosable)
    monkeypatch.setenv("FYLGJA_LISTEN", f"127.0.0.1:{free_port()}")
    monkeypatch.setattr(server._Server, "run", lambda self, sockets=None: None)
    assert server.main([]) == 0
    err = capsys.readouterr().err
    assert "Traceback" not in err and "fixture text" not in err
    assert [entry["message"] for entry in logged(err) if entry["level"] == "WARNING"] == [
        "the store was not closed (OSError)"]
    LocalStore.open(Path(environ["FYLGJA_STORE"])).close()  # its own close ran before the raise


def test_the_server_refuses_a_configuration_it_cannot_serve_through_its_layer(environ: dict[str, str]) -> None:
    app, store = server.build_app(settings(environ))
    try:
        loaded = uvicorn.Config(app, log_config=None)
        loaded.load()
        with pytest.raises(ValueError, match="not yet loaded"):
            server._Server(loaded, threading.Event())
        with pytest.raises(ValueError, match="not yet loaded"):
            server._Server(uvicorn.Config("fylgja_core.server.app:application", log_config=None), threading.Event())
    finally:
        store.close()


def test_a_shutdown_ends_an_open_watch_at_once(environ: dict[str, str]) -> None:
    closing = threading.Event()
    app, store = server.build_app(settings(environ), closing=closing)
    uv = server._Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_config=None, access_log=False,
                                       timeout_graceful_shutdown=server.GRACE_S), closing)
    thread = threading.Thread(target=uv.run, daemon=True)
    thread.start()
    try:
        until(lambda: uv.started, "the server's start")
        host, port = uv.servers[0].sockets[0].getsockname()[:2]
        with httpx.Client(base_url=f"http://{host}:{port}", headers={"Authorization": f"Bearer {TOKEN}"},
                          trust_env=False, timeout=10.0) as client, \
                client.stream("GET", "/v1/twins", params={"watch": "true"}) as watch:
            assert watch.status_code == 200
            began = time.monotonic()
            uv.should_exit = True
            assert list(messages(watch.iter_lines())) == []  # the stream ends; it is not cut
        thread.join(timeout=server.GRACE_S * 2)
        assert not thread.is_alive() and time.monotonic() - began < server.GRACE_S
    finally:
        uv.should_exit = True
        thread.join(timeout=server.GRACE_S * 2)
        store.close()


def test_build_app_closes_the_driver_it_made_when_it_fails_after(
    environ: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    made = made_drivers(monkeypatch)
    closed = closed_drivers(monkeypatch)

    def failing(**kw: Any) -> Any:
        raise RuntimeError("the application cannot be made")

    monkeypatch.setattr(server, "create_app", failing)
    with pytest.raises(RuntimeError, match="cannot be made"):
        server.build_app(settings(environ))
    assert closed == [driver for driver, _ in made] and len(closed) == 1
    LocalStore.open(Path(environ["FYLGJA_STORE"])).close()  # the store it opened is closed again


def test_build_app_raises_its_own_error_when_a_close_after_it_fails(
    environ: dict[str, str], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    made_drivers(monkeypatch)

    async def failing_close(driver: Driver) -> None:
        raise OSError("fixture text, never logged")

    def failing(**kw: Any) -> Any:
        raise RuntimeError("the application cannot be made")

    monkeypatch.setattr(registry, "close", failing_close)
    monkeypatch.setattr(server, "create_app", failing)
    with pytest.raises(RuntimeError, match="cannot be made"):
        server.build_app(settings(environ))
    assert [record.getMessage() for record in caplog.records if record.levelno >= logging.WARNING] == [
        "the driver was not closed (OSError)"]
    LocalStore.open(Path(environ["FYLGJA_STORE"])).close()  # and the store was closed all the same


AT_ONCE_S = 2.0
"""How soon a server that lost its Lease has stopped: well under `GRACE_S`, which a stop that gave
its connections their grace would take, with room for a host stalled a second."""


def lease_server(
    app: Starlette, closing: threading.Event, held: Lease | None, environ: dict[str, str],
    tls_pair: tuple[Path, Path] | None = None,
) -> server._Server:
    """A `_Server` of `app` configured as `main` configures it (`_config`), on a free loopback
    port, over TLS with `tls_pair`; holding `held`, and closing the driver `build_app` made."""
    served = dataclasses.replace(settings(environ), listen=("127.0.0.1", 0), tls=tls_pair)
    return server._Server(server._config(app, served), closing, held, driver=app.state.driver)


def ran(uv: server._Server, sockets: list[socket.socket] | None = None) -> tuple[threading.Thread, list[Any]]:
    """`uv` run in a daemon thread of its own, which a test joins with a bound, so a run that
    hangs fails its test and holds no exit of the suite; and the code of each `SystemExit` it
    ended with."""
    exits: list[Any] = []

    def run() -> None:
        try:
            uv.run(sockets=sockets)
        except SystemExit as e:
            exits.append(e.code)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread, exits


@contextlib.contextmanager
def under_a_lease(
    environ: dict[str, str], fake: FakeLeases, *, routes: Sequence[BaseRoute] = (), renew_s: float = 0.05,
    duration_s: float = 30.0, tls_pair: tuple[Path, Path] | None = None, **lease_kw: Any,
) -> Iterator[tuple[server._Server, Driver, threading.Thread]]:
    """A `_Server` over `environ`'s application, `routes` added, over TLS with `tls_pair`, run in a
    thread holding the Lease `fake` keeps, as `a`, taken just before; the driver it serves; and
    the thread. Renewed every `renew_s`, the Lease is lost only by a test's doing: its duration
    survives a host stalled. Leaving stops the server if it is still running."""
    closing = threading.Event()
    app, store = server.build_app(settings(environ), closing=closing)
    app.router.routes.extend(routes)
    held = Lease(fake, "a", renew_s=renew_s, duration_s=duration_s, **lease_kw)
    asyncio.run(held.acquire())
    uv = lease_server(app, closing, held, environ, tls_pair)
    thread, _ = ran(uv)
    try:
        until(lambda: uv.started, "the server's start")
        yield uv, app.state.driver, thread
    finally:
        uv.should_exit = True
        thread.join(timeout=server.GRACE_S * 2)
        store.close()
    assert not thread.is_alive()


async def held_open(request: Request) -> Response:
    """A request in flight until it is cancelled."""
    await asyncio.sleep(DEADLINE_S * 3)
    return JSONResponse({"held": True})


def requested(port: int, method: str, path: str, answers: dict[str, object]) -> None:
    """`method path` on the server at `port`: its status, or the type of the transport's failure."""
    try:
        with httpx.Client(headers={"Authorization": f"Bearer {TOKEN}"}, trust_env=False, timeout=DEADLINE_S) as client:
            answers[path] = client.request(method, f"http://127.0.0.1:{port}{path}").status_code
    except httpx.TransportError as e:
        answers[path] = type(e).__name__


def test_a_server_under_a_lease_holds_it_while_it_serves_and_releases_it_as_it_stops(
    environ: dict[str, str], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    closed = closed_drivers(monkeypatch)
    fake = FakeLeases()
    with under_a_lease(environ, fake) as (uv, driver, _):
        renewed = fake.writes  # the take, and the renewal before the lifespan started
        until(lambda: fake.writes >= renewed + 2, "renewals beside the loop")
        uv.should_exit = True
    assert [write.holder for write in fake.written][:2] == ["a", "a"] and fake.written[-1].holder == ""
    assert not uv.lost and fake.closed and closed == [driver]
    assert "released the Lease fylgja-core" in [record.getMessage() for record in caplog.records]
    assert [record.getMessage() for record in caplog.records if record.levelno >= logging.WARNING] == []


def test_a_lost_lease_cuts_the_requests_in_flight_and_stops_the_loop_at_once_with_nothing_released(
    environ: dict[str, str], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    closed = closed_drivers(monkeypatch)
    began: list[float] = []  # when the loop's stop began, on the clock a log record is timed by
    stop = Reconciler.stop

    async def timed(self: Reconciler) -> None:
        began.append(time.time())
        await stop(self)

    monkeypatch.setattr(Reconciler, "stop", timed)
    go = threading.Event()  # set once the Lease is lost: the write below writes then, were it still running
    written: list[str] = []

    async def writes(request: Request) -> Response:
        while not go.is_set():
            await asyncio.sleep(0.005)
        written.append("written after the loss")
        return JSONResponse({"written": True})

    answers: dict[str, object] = {}
    fake = FakeLeases()
    routes = [Route("/test/held", held_open), Route("/test/write", writes, methods=["POST"])]
    with under_a_lease(environ, fake, routes=routes) as (uv, driver, thread):
        port = uv.servers[0].sockets[0].getsockname()[1]
        callers = [threading.Thread(target=requested, args=(port, "GET", "/test/held", answers)),
                   threading.Thread(target=requested, args=(port, "POST", "/test/write", answers))]
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", headers={"Authorization": f"Bearer {TOKEN}"},
                          trust_env=False, timeout=DEADLINE_S) as client, \
                client.stream("GET", "/v1/twins", params={"watch": "true"}) as watch:
            assert watch.status_code == 200
            for caller in callers:
                caller.start()
            until(lambda: len(uv.server_state.tasks) == 3, "the watch, the held request and the write in flight")
            until(lambda: docker_calls(tmp_path), "the loop's docker events")
            fake.set("b")  # another holder took it: the next renewal answers Conflict, and reads back b
            until(lambda: uv.lost, "the loss")
            go.set()
            try:
                for _ in watch.iter_lines():
                    pass
            except httpx.TransportError:
                cut = True
            else:
                cut = False
            thread.join(timeout=AT_ONCE_S)
            for caller in callers:
                caller.join(timeout=AT_ONCE_S)
        assert not thread.is_alive()
    # Each request in flight had its connection dropped: no answer, a success least of all; and the write never wrote.
    assert cut and sorted(answers) == ["/test/held", "/test/write"]
    assert [answer for answer in answers.values() if not isinstance(answer, str)] == []
    assert written == []
    # The one ERROR line, and nothing at ERROR after it: the requests cut ended quietly, and the loop stopped through
    # the lifespan's shutdown, begun at the loss (verified-facts.md).
    errors = [record for record in caplog.records if record.levelno >= logging.ERROR]
    assert [(record.getMessage(), getattr(record, "fields", {}).get("rule")) for record in errors] == [
        ("the server stops at once: the Lease fylgja-core is held by b", "lease.lost")]
    assert [record.getMessage() for record in caplog.records if record.exc_info] == []
    assert began and began[0] - errors[0].created < 0.5
    assert uv.lost and uv.force_exit
    assert "" not in [write.holder for write in fake.written] and fake.closed and closed == [driver]
    assert followers_of_this_process() == []  # the loop stopped, and its docker events with it


def test_a_request_cancelled_while_the_lease_is_held_fails_as_it_does_without_the_server_layer(
    environ: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    # The layer that ends a request the loss cut is inert otherwise: uvicorn answers and logs it as it always has.
    answers: dict[str, object] = {}
    fake = FakeLeases()
    with under_a_lease(environ, fake, routes=[Route("/test/held", held_open)]) as (uv, _, _):
        port = uv.servers[0].sockets[0].getsockname()[1]
        caller = threading.Thread(target=requested, args=(port, "GET", "/test/held", answers))
        caller.start()
        until(lambda: len(uv.server_state.tasks) == 1, "the request in flight")
        uv.servers[0].get_loop().call_soon_threadsafe(lambda: [task.cancel() for task in list(uv.server_state.tasks)])
        caller.join(timeout=DEADLINE_S)
    assert answers == {"/test/held": 500} and not uv.lost
    errors = [(record.name, record.getMessage().splitlines()[0], record.exc_info is not None)
              for record in caplog.records if record.levelno >= logging.ERROR]
    assert errors == [("uvicorn.error", "Exception in ASGI application", True)]


WRITE = (f"POST /test/write HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer {TOKEN}\r\n"
         "Content-Length: 0\r\n\r\n").encode()
"""A request to the write route, as a client sends it once its handshake is done."""


def asked_over_tls(raw: socket.socket, cert: Path, request: bytes) -> bytes:
    """`raw`'s TLS handshake, verified against `cert`, then `request` sent and the first bytes of
    the answer read: b"" where the server dropped the connection, whenever it did."""
    try:
        with ssl.create_default_context(cafile=str(cert)).wrap_socket(raw, server_hostname="127.0.0.1") as wrapped:
            wrapped.sendall(request)
            return wrapped.recv(1024)
    except OSError:  # ssl.SSLError, a reset: dropped
        return b""


def accepted(uv: server._Server, count: int) -> Callable[[], bool]:
    """Whether the listener has made a transport of each of `count` connections: asyncio's `Server`
    keeps them from then (verified-facts.md), before a TLS handshake, which uvicorn waits for."""
    return lambda: len(vars(uv.servers[0])["_clients"]) == count  # asyncio's own set, read in the facts


def test_a_tls_handshake_that_ends_after_the_loss_is_dropped_and_writes_nothing(
    environ: dict[str, str], caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    cert, key = tls.pair(tmp_path / "tls")
    written: list[str] = []

    async def writes(request: Request) -> Response:
        written.append("written after the loss")
        return JSONResponse({"written": True})

    fake = FakeLeases()
    routes = [Route("/test/write", writes, methods=["POST"])]
    with under_a_lease(environ, fake, routes=routes, tls_pair=(cert, key)) as (uv, _, thread):
        port = uv.servers[0].sockets[0].getsockname()[1]
        with socket.create_connection(("127.0.0.1", port), timeout=DEADLINE_S) as raw:
            until(accepted(uv, 1), "the connection, accepted before the loss and its handshake not begun")
            fake.set("b")
            until(lambda: uv.lost, "the loss")
            answer = asked_over_tls(raw, cert, WRITE)
        thread.join(timeout=DEADLINE_S)
    assert answer == b"" and written == []  # dropped: no answer, a success least of all, and nothing written
    assert [(record.getMessage(), getattr(record, "fields", {}).get("rule")) for record in caplog.records
            if record.levelno >= logging.ERROR] == [
        ("the server stops at once: the Lease fylgja-core is held by b", "lease.lost")]


def test_a_client_that_sends_nothing_does_not_hold_a_lost_server(
    environ: dict[str, str], caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    cert, key = tls.pair(tmp_path / "tls")
    fake = FakeLeases()
    with under_a_lease(environ, fake, tls_pair=(cert, key)) as (uv, _, thread):
        port = uv.servers[0].sockets[0].getsockname()[1]
        with socket.create_connection(("127.0.0.1", port), timeout=DEADLINE_S):  # no ClientHello, ever
            until(accepted(uv, 1), "the silent connection, accepted before the loss")
            fake.set("b")
            until(lambda: uv.lost, "the loss")
            thread.join(timeout=1.0)
            assert not thread.is_alive()  # it gave the connection no grace
    assert [(record.getMessage(), getattr(record, "fields", {}).get("rule")) for record in caplog.records
            if record.levelno >= logging.ERROR] == [
        ("the server stops at once: the Lease fylgja-core is held by b", "lease.lost")]


def test_a_loss_while_the_lifespan_starts_serves_no_request(
    environ: dict[str, str], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, tmp_path: Path
) -> None:
    cert, key = tls.pair(tmp_path / "tls")
    written: list[str] = []

    async def writes(request: Request) -> Response:
        written.append("written after the loss")
        return JSONResponse({"written": True})

    listener = server._listener("127.0.0.1", 0)  # bound and listening before uvicorn serves on it, as main has it
    port = listener.getsockname()[1]
    answers: list[bytes] = []
    connected = threading.Event()

    def ask() -> None:
        with socket.create_connection(("127.0.0.1", port), timeout=DEADLINE_S) as raw:
            connected.set()
            answers.append(asked_over_tls(raw, cert, WRITE))

    caller = threading.Thread(target=ask, daemon=True)
    start = Reconciler.start

    async def lost_while_starting(self: Reconciler) -> None:
        await start(self)
        caller.start()  # its connection waits in the listener's backlog until the server serves
        deadline = time.monotonic() + DEADLINE_S
        while not connected.is_set():  # connected before the loss closes the listener: no race on real time
            assert time.monotonic() < deadline, f"the caller did not connect within {DEADLINE_S:g}s"
            await asyncio.sleep(0.01)
        fake.set("b")
        while not uv.lost:
            await asyncio.sleep(0.01)  # the Lease is lost while the lifespan starts

    monkeypatch.setattr(Reconciler, "start", lost_while_starting)
    fake = FakeLeases()
    closing = threading.Event()
    app, store = server.build_app(settings(environ), closing=closing)
    try:
        app.router.routes.append(Route("/test/write", writes, methods=["POST"]))
        held = Lease(fake, "a", renew_s=0.05, duration_s=30.0)
        asyncio.run(held.acquire())
        uv = lease_server(app, closing, held, environ, (cert, key))
        thread, exits = ran(uv, sockets=[listener])
        thread.join(timeout=DEADLINE_S)
        caller.join(timeout=DEADLINE_S)
    finally:
        listener.close()
        store.close()
    assert not thread.is_alive() and exits == [] and uv.lost and answers == [b""] and written == []
    assert [(record.getMessage(), getattr(record, "fields", {}).get("rule")) for record in caplog.records
            if record.levelno >= logging.ERROR] == [
        ("the server stops at once: the Lease fylgja-core is held by b", "lease.lost")]


def test_a_loop_whose_stop_hangs_once_the_lease_is_lost_is_left_and_the_server_exits_1(
    environ: dict[str, str], leases: FakeLeases, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A stop that hangs cannot keep serving a core that no longer holds the Lease: it is given LOST_STOP_S.
    monkeypatch.setattr(server, "LOST_STOP_S", 0.1)
    monkeypatch.setenv("FYLGJA_LISTEN", f"127.0.0.1:{free_port()}")
    start = Reconciler.start

    async def started_then_taken(self: Reconciler) -> None:
        await start(self)
        leases.set("b")  # another core takes it once the loop runs

    async def hangs(self: Reconciler) -> None:
        await asyncio.sleep(DEADLINE_S * 3)  # ended only by a cancel; bounded, so a regression fails, never hangs

    monkeypatch.setattr(Reconciler, "start", started_then_taken)
    monkeypatch.setattr(Reconciler, "stop", hangs)
    began = time.monotonic()
    assert server.main([]) == 1
    assert time.monotonic() - began < server.GRACE_S
    entries = logged(capsys.readouterr().err)
    assert [entry["message"] for entry in entries if entry["level"] == "WARNING"] == [
        "the loop's stop did not end (TimeoutError): the server stops all the same"]
    errors = [entry for entry in entries if entry["level"] == "ERROR"]
    assert (errors[0]["message"], errors[0]["rule"]) == ("the server stops at once: the Lease fylgja-core is held by b",
                                                         "lease.lost")
    # Left to the event loop's close, the lifespan's task is cancelled there, and its traceback may follow: here alone.
    assert {entry["logger"] for entry in errors[1:]} <= {"uvicorn.error"}
    assert "" not in [write.holder for write in leases.written]
    LocalStore.open(Path(environ["FYLGJA_STORE"])).close()


def test_renewals_ended_by_what_the_lease_does_not_raise_stop_the_server_as_a_loss(
    environ: dict[str, str], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # `hold` raises `Lost` alone by its contract; whatever else ends it ends the renewals as surely, and a server left
    # serving would hold a Lease the next core takes at the duration's end.
    closed = closed_drivers(monkeypatch)
    fake = FakeLeases()
    with under_a_lease(environ, fake) as (uv, driver, thread):
        fake.write_errors = [RuntimeError("fixture text, never logged")]
        thread.join(timeout=AT_ONCE_S)
        assert not thread.is_alive()
    assert uv.lost and "" not in [write.holder for write in fake.written] and fake.closed and closed == [driver]
    (record,) = [record for record in caplog.records
                 if record.levelno >= logging.ERROR and record.name.startswith("fylgja.")]
    assert (record.getMessage(), getattr(record, "fields", {}).get("rule")) == (
        "the server stops at once: the Lease fylgja-core is no longer renewed (RuntimeError)", "lease.lost")


def test_a_shutdown_during_a_renewal_cancels_it_before_the_release(
    environ: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    # A release while a renewal is in flight would make that renewal read back no holder, `Lost` for this core's own
    # release: the renewal is cancelled first. Here the renewal stays in flight until a release is written and then
    # lands, so one not cancelled first would read back the release; every wait is on an event, none on seconds.
    in_flight = threading.Event()

    class Renewing(FakeLeases):
        def __init__(self) -> None:
            super().__init__()
            self.released = asyncio.Event()

        async def write(self, holder: str, transitions: int, version: str | None) -> Record:
            if holder and self.writes == 2:  # the third write: the first renewal beside the loop
                in_flight.set()
                await self.released.wait()
            answered = await super().write(holder, transitions, version)
            if not holder:
                self.released.set()
            return answered

    async def at_once(seconds: float) -> None:
        await asyncio.sleep(0)  # the first renewal follows the start's at once, bounded by renew_s, 10 s

    fake = Renewing()
    with under_a_lease(environ, fake, renew_s=10.0, sleep=at_once) as (uv, _, thread):
        until(in_flight.is_set, "the first renewal beside the loop, in flight")
        uv.should_exit = True
        thread.join(timeout=server.GRACE_S * 2)
    assert [write.holder for write in fake.written] == ["a", "a", ""]  # the renewal in flight never wrote
    assert not uv.lost
    assert [record.getMessage() for record in caplog.records if record.levelno >= logging.ERROR] == []


def test_a_forced_exit_stops_the_loop_before_the_lease_is_released(
    environ: dict[str, str], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    order: list[str] = []
    stop = Reconciler.stop

    async def recorded(self: Reconciler) -> None:
        order.append("the loop's stop")
        await stop(self)

    class Released(FakeLeases):
        async def write(self, holder: str, transitions: int, version: str | None) -> Record:
            if not holder:
                order.append("the release")
            return await super().write(holder, transitions, version)

    monkeypatch.setattr(Reconciler, "stop", recorded)
    fake = Released()
    with under_a_lease(environ, fake) as (uv, _, thread):
        uv.force_exit = True  # a second Ctrl-C, landed before uvicorn's shutdown reached the lifespan's
        uv.should_exit = True
        thread.join(timeout=DEADLINE_S)
    assert order == ["the loop's stop", "the release"] and not uv.lost
    assert [record.getMessage() for record in caplog.records if record.levelno >= logging.ERROR] == []


def test_a_forced_exit_whose_loop_does_not_stop_in_time_leaves_the_lease_unreleased(
    environ: dict[str, str], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(server, "LOST_STOP_S", 0.1)

    async def hangs(self: Reconciler) -> None:
        await asyncio.sleep(DEADLINE_S * 3)  # ended only by a cancel; bounded, so a regression fails, never hangs

    monkeypatch.setattr(Reconciler, "stop", hangs)
    fake = FakeLeases()
    with under_a_lease(environ, fake) as (uv, _, thread):
        uv.force_exit = True
        uv.should_exit = True
        thread.join(timeout=DEADLINE_S)
    assert "" not in [write.holder for write in fake.written] and fake.closed and not uv.lost
    assert [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING] == [
        "the loop's stop did not end (TimeoutError): the Lease fylgja-core is not released, and its next holder takes "
        "it once its duration has passed"]


def test_a_start_whose_renewal_fails_otherwise_than_lost_is_the_loss_it_is(
    environ: dict[str, str], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    closed = closed_drivers(monkeypatch)
    fake = FakeLeases()
    closing = threading.Event()
    app, store = server.build_app(settings(environ), closing=closing)
    try:
        held = Lease(fake, "a", renew_s=0.05, duration_s=30.0)
        asyncio.run(held.acquire())
        fake.write_errors = [RuntimeError("fixture text, never logged")]  # the start's renewal
        uv = lease_server(app, closing, held, environ)
        thread, exits = ran(uv)
        thread.join(timeout=DEADLINE_S)
    finally:
        store.close()
    assert not thread.is_alive() and exits == [1] and uv.lost
    assert [(record.getMessage(), getattr(record, "fields", {}).get("rule")) for record in caplog.records
            if record.levelno >= logging.ERROR] == [
        ("the server stops at once: the Lease fylgja-core is no longer renewed (RuntimeError)", "lease.lost")]
    assert [write.holder for write in fake.written] == ["a", "a"] and fake.closed and closed == [app.state.driver]


def test_a_start_once_the_leases_duration_has_passed_is_lost_with_nothing_written(
    environ: dict[str, str], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    closed = closed_drivers(monkeypatch)
    fake = FakeLeases()
    now = [0.0]
    closing = threading.Event()
    app, store = server.build_app(settings(environ), closing=closing)
    try:
        held = Lease(fake, "a", monotonic=lambda: now[0], renew_s=5.0, duration_s=15.0)
        asyncio.run(held.acquire())
        now[0] = 15.0  # the time from the take to the start took the whole duration
        uv = lease_server(app, closing, held, environ)
        thread, exits = ran(uv)
        thread.join(timeout=DEADLINE_S)
    finally:
        store.close()
    assert not thread.is_alive() and exits == [1] and uv.lost
    assert [(record.getMessage(), getattr(record, "fields", {}).get("rule")) for record in caplog.records
            if record.levelno >= logging.ERROR] == [
        ("the server stops at once: no renewal succeeded within 15 s", "lease.lost")]
    assert [write.holder for write in fake.written] == ["a"] and fake.closed and closed == [app.state.driver]


def test_a_start_that_fails_under_a_lease_stops_holding_it_and_releases_nothing(
    environ: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failing(self: Reconciler) -> None:
        raise RuntimeError("the loop cannot start")

    monkeypatch.setattr(Reconciler, "start", failing)
    closed = closed_drivers(monkeypatch)
    pending: list[list[str]] = []  # at the Lease's close: every task of the loop still to finish, but the closer

    class Closed(FakeLeases):
        async def close(self) -> None:
            pending.append([repr(t) for t in asyncio.all_tasks() if t is not asyncio.current_task() and not t.done()])
            await super().close()

    fake = Closed()
    closing = threading.Event()
    app, store = server.build_app(settings(environ), closing=closing)
    try:
        held = Lease(fake, "a", renew_s=0.05, duration_s=30.0)
        asyncio.run(held.acquire())
        uv = lease_server(app, closing, held, environ)
        thread, exits = ran(uv)
        thread.join(timeout=DEADLINE_S)
    finally:
        store.close()
    assert not thread.is_alive() and exits == [3]  # uvicorn's STARTUP_FAILURE
    assert pending == [[]] and fake.closed
    assert fake.written[-1].holder == "a" and not uv.lost  # left to this pod's next start
    assert closed == [app.state.driver]


def test_main_hands_uvicorn_the_tls_pair(
    environ: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cert, key = tls.pair(tmp_path / "tls")
    monkeypatch.setenv("FYLGJA_TLS_CERT", str(cert))
    monkeypatch.setenv("FYLGJA_TLS_KEY", str(key))
    monkeypatch.setenv("FYLGJA_LISTEN", f"127.0.0.1:{free_port()}")
    served: list[uvicorn.Config] = []
    monkeypatch.setattr(server._Server, "run", lambda self, sockets=None: served.append(self.config))
    assert server.main([]) == 0
    (config_,) = served
    assert (config_.ssl_certfile, config_.ssl_keyfile) == (cert, key)
    assert [entry for entry in logged(capsys.readouterr().err) if entry["level"] != "INFO"] == []
    LocalStore.open(Path(environ["FYLGJA_STORE"])).close()


def test_the_server_answers_over_tls_with_the_pair(environ: dict[str, str], tmp_path: Path) -> None:
    cert, key = tls.pair(tmp_path / "tls")
    closing = threading.Event()
    app, store = server.build_app(settings(environ), closing=closing)
    try:
        with tls.served(app, (cert, key), closing) as port:
            with httpx.Client(base_url=f"https://127.0.0.1:{port}",
                              verify=ssl.create_default_context(cafile=str(cert)), trust_env=False,
                              timeout=10.0) as client:
                assert client.get("/v1/version").json()["api"] == "1"
            with pytest.raises(httpx.TransportError):  # plain HTTP is not answered on it
                httpx.get(f"http://127.0.0.1:{port}/v1/version", trust_env=False, timeout=10.0)
    finally:
        store.close()


@pytest.mark.parametrize("fault", ["not-a-certificate", "another-certificates-key"])
def test_a_tls_pair_that_does_not_load_exits_2_before_the_lease_is_read_or_the_store_made(
    environ: dict[str, str], leases: FakeLeases, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str], fault: str,
) -> None:
    cert, key = tls.pair(tmp_path / "a")
    if fault == "not-a-certificate":
        cert.write_text("not a certificate\n")
    else:
        _, key = tls.pair(tmp_path / "b")
    monkeypatch.setenv("FYLGJA_TLS_CERT", str(cert))
    monkeypatch.setenv("FYLGJA_TLS_KEY", str(key))
    assert server.main([]) == 2
    err = capsys.readouterr().err
    # Outside the assert, which would print what it compares: no line of either file is in the log.
    shown = any(line in err for path in (cert, key) for line in path.read_text().splitlines() if len(line) > 8)
    assert not shown
    (line,) = [entry for entry in logged(err) if entry["level"] == "ERROR"]
    assert line["variable"] == "FYLGJA_TLS_CERT"
    assert line["message"].startswith("cannot start: FYLGJA_TLS_CERT and FYLGJA_TLS_KEY name a certificate and key "
                                      "that do not load: ")
    assert (leases.reads, leases.writes) == (0, 0) and not Path(environ["FYLGJA_STORE"]).exists()


def test_an_encrypted_key_exits_2_naming_fylgja_tls_key_with_no_prompt(
    environ: dict[str, str], leases: FakeLeases, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cert, key = tls.pair(tmp_path / "tls")
    monkeypatch.setenv("FYLGJA_TLS_CERT", str(cert))
    monkeypatch.setenv("FYLGJA_TLS_KEY", str(tls.encrypted(key)))
    assert server.main([]) == 2
    (line,) = [entry for entry in logged(capsys.readouterr().err) if entry["level"] == "ERROR"]
    assert (line["variable"], line["message"]) == (
        "FYLGJA_TLS_KEY", "cannot start: FYLGJA_TLS_KEY is encrypted: the server reads an unencrypted key")
    assert (leases.reads, leases.writes) == (0, 0) and not Path(environ["FYLGJA_STORE"]).exists()


def ipv6_loopback() -> bool:
    """Whether this host can listen on `::1`."""
    try:
        with socket.socket(socket.AF_INET6) as probe:
            probe.bind(("::1", 0))
    except OSError:
        return False
    return True


@pytest.mark.parametrize(("host", "warned"), [("0.0.0.0", True), ("127.0.0.1", False), ("::1", False),
                                              ("localhost", False)])
def test_an_address_off_loopback_without_tls_is_one_warning(
    environ: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], host: str,
    warned: bool,
) -> None:
    if host == "::1" and not ipv6_loopback():
        pytest.skip("this host has no IPv6 loopback to listen on")
    monkeypatch.setenv("FYLGJA_LISTEN", f"{host}:{free_port()}")
    monkeypatch.setattr(server._Server, "run", lambda self, sockets=None: None)
    assert server.main([]) == 0
    warnings = [entry for entry in logged(capsys.readouterr().err) if entry["level"] == "WARNING"]
    assert [entry["variable"] for entry in warnings] == (["FYLGJA_TLS_CERT"] if warned else [])
    LocalStore.open(Path(environ["FYLGJA_STORE"])).close()


def test_an_address_off_loopback_with_tls_is_no_warning(
    environ: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    cert, key = tls.pair(tmp_path / "tls")
    monkeypatch.setenv("FYLGJA_TLS_CERT", str(cert))
    monkeypatch.setenv("FYLGJA_TLS_KEY", str(key))
    monkeypatch.setenv("FYLGJA_LISTEN", f"0.0.0.0:{free_port()}")
    monkeypatch.setattr(server._Server, "run", lambda self, sockets=None: None)
    assert server.main([]) == 0
    assert [entry for entry in logged(capsys.readouterr().err) if entry["level"] == "WARNING"] == []
    LocalStore.open(Path(environ["FYLGJA_STORE"])).close()


def test_an_address_it_cannot_listen_on_exits_2_naming_the_variable(
    environ: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    closed = closed_drivers(monkeypatch)
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", 0))
        taken.listen()
        monkeypatch.setenv("FYLGJA_LISTEN", f"127.0.0.1:{taken.getsockname()[1]}")
        assert server.main([]) == 2
    monkeypatch.setenv("FYLGJA_LISTEN", "no-such-host.invalid:7650")
    assert server.main([]) == 2
    refusals = [entry for entry in logged(capsys.readouterr().err) if entry["level"] == "ERROR"]
    assert [entry["variable"] for entry in refusals] == ["FYLGJA_LISTEN", "FYLGJA_LISTEN"]
    assert len(closed) == 2  # each start's driver closed, as its store
    LocalStore.open(Path(environ["FYLGJA_STORE"])).close()


def test_a_lifespan_that_fails_to_start_exits_1(
    environ: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def failing(self: Reconciler) -> None:
        raise RuntimeError("the loop cannot start")

    monkeypatch.setattr(Reconciler, "start", failing)
    monkeypatch.setenv("FYLGJA_LISTEN", f"127.0.0.1:{free_port()}")
    assert server.main([]) == 1
    errors = [entry["message"] for entry in logged(capsys.readouterr().err) if entry["level"] == "ERROR"]
    assert errors[-1].startswith("cannot start: the application did not start")
    LocalStore.open(Path(environ["FYLGJA_STORE"])).close()


def test_ctrl_c_returns_130_with_the_store_closed(environ: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    def interrupted(self: uvicorn.Server, sockets: Any = None) -> None:
        raise KeyboardInterrupt

    monkeypatch.setenv("FYLGJA_LISTEN", f"127.0.0.1:{free_port()}")
    monkeypatch.setattr(server._Server, "run", interrupted)
    assert server.main([]) == 130
    LocalStore.open(Path(environ["FYLGJA_STORE"])).close()


@pytest.mark.parametrize(("sent", "status"), [(signal.SIGINT, 130), (signal.SIGTERM, 143)])
def test_the_process_stops_on_a_signal_with_its_status_and_no_traceback(
    environ: dict[str, str], tmp_path: Path, sent: signal.Signals, status: int
) -> None:
    """And the `docker events` it follows is gone: the command leads a session of its own, so the signal sent to the
    server never reaches it. Under SIGINT the interpreter's exit ends it too, so SIGTERM's case, and in this process
    `test_the_loop_follows_docker_events_through_the_stub_alone`, are the ones that hold the loop's stop to ending it.
    The `docker` is the stub `environ` puts first on `PATH`, which the server's commands get through
    `cli.environment`."""
    port = free_port()
    env = {**environ, "FYLGJA_LISTEN": f"127.0.0.1:{port}", "PATH": os.environ.get("PATH", "")}
    with (tmp_path / "stderr").open("w") as err:
        process = subprocess.Popen([sys.executable, "-m", "fylgja_core.server"], env=env, stderr=err,
                                   stdout=subprocess.DEVNULL)
    try:
        def answers() -> bool:
            try:
                return httpx.get(f"http://127.0.0.1:{port}/v1/version", timeout=1.0).status_code == 200
            except httpx.TransportError:
                return False

        until(answers, "the server's first answer")
        until(lambda: docker_calls(tmp_path), "the stub's docker events")
        process.send_signal(sent)
        assert process.wait(timeout=DEADLINE_S) == status
        ((pid, argv),) = docker_calls(tmp_path)
        assert argv == list(EVENTS_ARGV)
        assert gone_within(pid, 1.0), "the server left its docker events running"
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        kill_stub_followers(tmp_path)
    text = (tmp_path / "stderr").read_text()
    assert "Traceback" not in text and logged(text)
    LocalStore.open(Path(environ["FYLGJA_STORE"])).close()


IMPORTING_S = 0.3
"""When a test sends SIGTERM to a server just started: inside its import of the server's modules,
0.7 to 0.9 s on the development host and about 2 s in the image (verified-facts.md)."""


def test_the_console_script_is_the_entry_module() -> None:
    project = tomllib.loads((ROOT / "core" / "pyproject.toml").read_text())
    assert project["project"]["scripts"]["fylgja-core-server"] == "fylgja_core.server.entry:main"


def _console_script_probe(blocked: str) -> subprocess.CompletedProcess[str]:
    probe = (f"import sys; sys.modules[{blocked!r}] = None; "
             "from fylgja_core.server.entry import main; sys.exit(main())")
    return subprocess.run([sys.executable, "-I", "-c", probe], capture_output=True, text=True, timeout=DEADLINE_S)


def test_the_console_script_without_the_server_extra_says_so_in_one_line_and_exits_2() -> None:
    done = _console_script_probe("uvicorn")
    assert done.returncode == 2
    assert done.stdout == ""
    assert "Traceback" not in done.stderr
    lines = done.stderr.splitlines()
    assert len(lines) == 1
    line = json.loads(lines[0])
    assert line["level"] == "ERROR"
    assert line["rule"] == "server.extra.missing"
    assert "uvicorn" in line["message"]
    assert "fylgja-core[server]" in line["message"]


def test_a_missing_module_of_the_cores_own_is_not_taken_for_the_extra() -> None:
    done = _console_script_probe("fylgja_core.config")
    assert done.returncode == 1
    assert "Traceback" in done.stderr
    assert "fylgja_core.config" in done.stderr
    assert "server.extra.missing" not in done.stderr


def test_sigterm_while_the_console_script_imports_the_server_exits_143_with_nothing_logged_or_opened(
    environ: dict[str, str], tmp_path: Path
) -> None:
    """In a container the server is PID 1, which ignores a signal it has no handler for, and the
    import of the server's modules comes before `main` installs its own: the console script has
    one first. Run as the venv installs it (`make venv`), with an environment it would serve."""
    script = Path(sys.executable).parent / "fylgja-core-server"
    env = {**environ, "FYLGJA_LISTEN": f"127.0.0.1:{free_port()}", "PATH": os.environ.get("PATH", "")}
    with (tmp_path / "stderr").open("w") as err:
        process = subprocess.Popen([str(script)], env=env, stderr=err, stdout=subprocess.DEVNULL)
    try:
        time.sleep(IMPORTING_S)
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=DEADLINE_S) == 143
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        kill_stub_followers(tmp_path)
    assert (tmp_path / "stderr").read_text() == ""  # main never ran: nothing configured its log, nothing said
    assert not Path(environ["FYLGJA_STORE"]).exists()
