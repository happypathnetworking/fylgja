"""JSON logging: one object per line with the time, level, logger, message and fields, and the
audit log on the same stream."""

from __future__ import annotations

import io
import json
import logging
import re
import sys
from collections.abc import Iterator
from typing import Any

import pytest

from fylgja_core import logs
from fylgja_core.credentials import Credential

TIME = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$")


QUIETED = ("httpx", "httpcore")


@pytest.fixture(autouse=True)
def _restore_logging() -> Iterator[None]:
    """Put back the root logger's handlers and level, and the HTTP clients' levels, that
    `configure` changes."""
    root = logging.getLogger()
    saved, level = root.handlers[:], root.level
    quieted = {name: logging.getLogger(name).level for name in QUIETED}
    yield
    root.handlers[:] = saved
    root.setLevel(level)
    for name, was in quieted.items():
        logging.getLogger(name).setLevel(was)


@pytest.fixture
def stream() -> io.StringIO:
    out = io.StringIO()
    logs.configure(stream=out)
    return out


def lines(stream: io.StringIO) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = [json.loads(line) for line in stream.getvalue().splitlines()]
    return parsed


def test_a_line_is_one_json_object_with_its_members_and_fields(stream: io.StringIO) -> None:
    logging.getLogger("fylgja.reconcile").info("pushed %s", "n1", **logs.fields(twin="t", node="n1", n=2))
    (line,) = lines(stream)
    assert set(line) == {"time", "level", "logger", "message", "twin", "node", "n"}
    assert TIME.match(line["time"])
    assert (line["level"], line["logger"], line["message"]) == ("INFO", "fylgja.reconcile", "pushed n1")
    assert (line["twin"], line["node"], line["n"]) == ("t", "n1", 2)
    assert stream.getvalue().count("\n") == 1


def test_the_audit_line_carries_the_principal_and_the_action(stream: io.StringIO) -> None:
    logs.audit("jgilby", "twin.create", "t", run_id="R1")
    (line,) = lines(stream)
    assert line["logger"] == "fylgja.audit" and line["level"] == "INFO"
    assert (line["principal"], line["action"], line["twin"], line["run_id"]) == ("jgilby", "twin.create", "t", "R1")


def test_a_logged_exception_appears_under_exception(stream: io.StringIO) -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        logging.getLogger("fylgja.x").exception("failed")
    (line,) = lines(stream)
    assert line["level"] == "ERROR"
    assert "ValueError: boom" in line["exception"]


def test_a_credential_field_renders_through_its_repr(stream: io.StringIO) -> None:
    logging.getLogger("fylgja.x").info("login", **logs.fields(credential=Credential("admin", "hunter2")))
    assert "hunter2" not in stream.getvalue()
    assert lines(stream)[0]["credential"] == "Credential(username='admin', password='***')"


def test_a_field_never_overrides_a_core_member(stream: io.StringIO) -> None:
    forged = logs.fields(time="then", level="DEBUG", logger="fylgja.audit", message="forged", twin="t")
    logging.getLogger("fylgja.x").warning("real", **forged)
    (line,) = lines(stream)
    assert TIME.match(line["time"])
    assert (line["level"], line["logger"], line["message"], line["twin"]) == ("WARNING", "fylgja.x", "real", "t")


def test_a_field_never_overrides_a_logged_exception(stream: io.StringIO) -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        logging.getLogger("fylgja.x").exception("failed", **logs.fields(exception="forged"))
    (line,) = lines(stream)
    assert "ValueError: boom" in line["exception"]


def test_configure_replaces_the_handlers_and_quiets_the_http_clients() -> None:
    root = logging.getLogger()
    foreign = logging.StreamHandler(io.StringIO())
    root.handlers[:] = [foreign, logging.NullHandler()]
    logging.getLogger("httpx").setLevel(logging.DEBUG)
    out = io.StringIO()
    logs.configure(stream=out)
    (handler,) = root.handlers
    assert handler is not foreign and isinstance(handler, logging.StreamHandler) and handler.stream is out
    assert isinstance(handler.formatter, logs.JsonFormatter)
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING


def test_configure_writes_to_stderr_as_it_is_when_called(monkeypatch: pytest.MonkeyPatch) -> None:
    err = io.StringIO()
    monkeypatch.setattr(sys, "stderr", err)
    logs.configure()
    logging.getLogger("fylgja.x").info("hello")
    assert json.loads(err.getvalue())["message"] == "hello"
