"""JSON logging: one object per line with the time, level, logger, message and fields, and the
audit log on the same stream."""

from __future__ import annotations

import io
import json
import logging
import re
from collections.abc import Iterator
from typing import Any

import pytest

from fylgja_core import logs
from fylgja_core.credentials import Credential

TIME = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z$")


@pytest.fixture
def stream() -> Iterator[io.StringIO]:
    root = logging.getLogger()
    saved, level = root.handlers[:], root.level
    out = io.StringIO()
    logs.configure(stream=out)
    yield out
    root.handlers[:] = saved
    root.setLevel(level)


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


def test_configure_replaces_the_handlers_and_quiets_the_http_clients(stream: io.StringIO) -> None:
    logs.configure(stream=stream)
    assert len(logging.getLogger().handlers) == 1
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING
