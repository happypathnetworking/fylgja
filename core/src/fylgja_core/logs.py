"""Logging is the standard library's: one JSON object per line on stderr, each with the time,
level, logger, message and the fields it carries (core.md, phase 4). The audit log is the
same stream with the principal and the action, so no second sink is run.
"""

from __future__ import annotations

import datetime
import json
import logging
import sys
from typing import Any, TextIO

_audit_log = logging.getLogger("fylgja.audit")


class JsonFormatter(logging.Formatter):
    """A record as one JSON object, keys sorted. The core members (`time`, `level`, `logger`,
    `message`, and `exception` when one is logged) win over a field of the same name, so no
    field can forge what a line says of itself."""

    def format(self, record: logging.LogRecord) -> str:
        time = datetime.datetime.fromtimestamp(record.created, datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        core: dict[str, Any] = {
            "time": time,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            core["exception"] = self.formatException(record.exc_info)
        line: dict[str, Any] = {**getattr(record, "fields", {}), **core}
        # `repr` for what JSON cannot hold: a Credential's repr hides its password.
        return json.dumps(line, sort_keys=True, default=repr)


def configure(level: int = logging.INFO, stream: TextIO | None = None) -> None:
    """Install one JSON handler on the root logger, replacing any; `stream` is `sys.stderr`
    as it is when called, unless another is given."""
    handler = logging.StreamHandler(sys.stderr if stream is None else stream)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    # Their request lines would log URLs at INFO and DEBUG.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.WARNING)


def fields(**kw: Any) -> dict[str, Any]:
    """The keyword to splat into a logging call: `log.info("pushed", **logs.fields(twin=t))`."""
    return {"extra": {"fields": kw}}


def audit(principal: str, action: str, twin: str, **kw: Any) -> None:
    """One audit line: who did what to which twin."""
    _audit_log.info(action, **fields(principal=principal, action=action, twin=twin, **kw))
