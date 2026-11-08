"""Log records scrubbed of every IPv4 address, for a test that runs the core against a site: a
node's address, which the push's lines name, is the site's, and pytest's capture holds every record
that reaches the root or a logger that does not propagate, and shows it in a test's report.

`Scrubbing` is a log-record factory: each record of the core's loggers (`fylgja`, `fylgja.*`) is
scrubbed as it is made, before any filter or handler sees it, which a filter on the loggers could
not do for a logger made later (the push's, made at the first push). A record's fields are set
after the factory, so `Scrubbed`, a handler's filter, scrubs them where a handler writes them.
"""

from __future__ import annotations

import logging
import re
from typing import Any

ADDRESS = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")


def scrubbed(text: str) -> str:
    """`text` with every IPv4 address in it replaced: a node's address is the site's."""
    return ADDRESS.sub("<address>", text)


def scrub(record: logging.LogRecord) -> logging.LogRecord:
    """`record` with every IPv4 address out of its message and its fields, its message formatted
    and its arguments dropped. An exception is kept as its type's name at the message's end, never
    its text or its traceback, which can name an address. A message that cannot be formatted
    becomes a marker naming the logger and the level. It never raises: it runs as the record is
    made, inside the code that logs."""
    try:
        message = scrubbed(record.getMessage())
    except Exception:  # a log call's bad format: logging would report it, never raise it
        message = f"(a {record.levelname} record of {record.name} whose message could not be formatted)"
    exception = record.exc_info[1] if record.exc_info else None
    if exception is not None:
        message = f"{message} ({type(exception).__name__})"
    record.msg, record.args, record.exc_info, record.exc_text = message, None, None, None
    fields = getattr(record, "fields", None)
    if isinstance(fields, dict):
        record.fields = {k: scrubbed(v) if isinstance(v, str) else v for k, v in fields.items()}
    return record


class Scrubbing:
    """The log-record factory while the module runs: each record of the core's loggers scrubbed of
    every IPv4 address as it is made (`scrub`), before any filter or handler sees it. The push's
    lines name each node's address, and pytest's capture, which a test's report shows, holds every
    record that reaches the root or a logger that does not propagate; a filter on the loggers
    would miss one made later, as the push's is, imported at the first push. A record's fields,
    set after the factory, are scrubbed by the filter on the module's own file handler."""

    def __init__(self) -> None:
        self.made = logging.getLogRecordFactory()

    def __call__(self, *args: Any, **kw: Any) -> logging.LogRecord:
        record = self.made(*args, **kw)
        return scrub(record) if record.name == "fylgja" or record.name.startswith("fylgja.") else record


class Scrubbed(logging.Filter):
    """A handler's filter: every record it is given scrubbed, its fields included (`scrub`)."""

    def filter(self, record: logging.LogRecord) -> bool:
        scrub(record)
        return True
