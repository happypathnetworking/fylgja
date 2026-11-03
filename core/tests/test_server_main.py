"""fylgja-core-server: a start refused by name when its settings are not whole, the application
it builds over one store held for one core, and the process uvicorn serves."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from starlette.testclient import TestClient

from fylgja_core import config
from fylgja_core.client import messages
from fylgja_core.config import Settings
from fylgja_core.local_store import LocalStore
from fylgja_core.server import __main__ as server
from fylgja_core.server import auth
from fylgja_core.store import Locked

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "main-test-token"


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    """Put back the root logger's handlers and level, which `main`'s `logs.configure` replaces."""
    root = logging.getLogger()
    saved, level = root.handlers[:], root.level
    yield
    root.handlers[:] = saved
    root.setLevel(level)


@pytest.fixture
def environ(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """A whole environment for the server, set in the process's, every other FYLGJA_* variable unset."""
    for name in [n for n in os.environ if n.startswith("FYLGJA_")]:
        monkeypatch.delenv(name)
    tokens = tmp_path / "tokens"
    tokens.write_text(f"{auth.hash_token(TOKEN)} tester\n")
    values = {"FYLGJA_STORE": str(tmp_path / "store"), "FYLGJA_PACKAGES": f"{ROOT / 'psp'}:{ROOT / 'probes'}",
              "FYLGJA_TOKENS": str(tokens), "FYLGJA_LISTEN": "127.0.0.1:7651"}
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return values


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


def test_the_application_answers_the_version_and_its_driver(environ: dict[str, str]) -> None:
    app, store = server.build_app(settings(environ))
    try:
        with TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}) as client:
            assert client.get("/v1/version").json()["api"] == "1"
            drivers = client.get("/v1/drivers").json()["drivers"]
    finally:
        store.close()
    assert [(d["name"], d["default"]) for d in drivers] == [("containerlab", True)]


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
    assert TOKEN not in err
    (line,) = [entry for entry in logged(err) if entry["level"] == "ERROR"]
    assert line["variable"] == "FYLGJA_TOKENS" and "line 1" in line["message"]
    LocalStore.open(Path(environ["FYLGJA_STORE"])).close()  # the store it opened is closed again


def test_main_serves_the_application_with_uvicorn_and_closes_the_store(
    environ: dict[str, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    served: list[uvicorn.Config] = []
    monkeypatch.setattr(server._Server, "run", lambda self, sockets=None: served.append(self.config))
    assert server.main([]) == 0
    (config_,) = served
    assert (config_.host, config_.port, config_.log_config, config_.access_log) == ("127.0.0.1", 7651, None, False)
    assert config_.timeout_graceful_shutdown == server.GRACE_S
    LocalStore.open(Path(environ["FYLGJA_STORE"])).close()
    assert all(isinstance(line, dict) for line in logged(capsys.readouterr().err))


def test_a_shutdown_ends_an_open_watch_at_once(environ: dict[str, str]) -> None:
    closing = threading.Event()
    app, store = server.build_app(settings(environ), closing=closing)
    uv = server._Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_config=None, access_log=False,
                                       timeout_graceful_shutdown=server.GRACE_S), closing)
    thread = threading.Thread(target=uv.run)
    thread.start()
    try:
        while not uv.started:
            time.sleep(0.01)
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
