"""The log-record scrubbing the cluster tier's restore module runs the core under (`scrubbing.py`):
every record of the core's loggers made with no IPv4 address in its message, an exception kept as
its type's name alone, a message that cannot be formatted made a marker, and nothing raised into
the code that logs."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator

import pytest
from scrubbing import Scrubbed, Scrubbing

from fylgja_core import logs


class Kept(logging.Handler):
    """Every record it is given, kept."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def kept() -> Iterator[Kept]:
    """The factory set, and a handler on a core's logger made after it, as the push's is."""
    scrubbing = Scrubbing()
    logging.setLogRecordFactory(scrubbing)
    handler = Kept()
    made_later = logging.getLogger("fylgja.scrubbing-test")
    made_later.addHandler(handler)
    made_later.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        logging.setLogRecordFactory(scrubbing.made)
        made_later.removeHandler(handler)


def test_a_core_records_addresses_are_scrubbed_as_it_is_made_and_another_loggers_are_not(kept: Kept) -> None:
    logging.getLogger("fylgja.scrubbing-test").info("pushed %s by %s in %d s", "192.0.2.7", "json_rpc", 3)
    other = Kept()
    logging.getLogger("scrubbing-test-other").addHandler(other)
    logging.getLogger("scrubbing-test-other").warning("left %s", "192.0.2.8")
    assert [r.getMessage() for r in kept.records] == ["pushed <address> by json_rpc in 3 s"]
    assert [r.getMessage() for r in other.records] == ["left 192.0.2.8"]


def test_an_exception_is_kept_by_its_type_name_alone(kept: Kept) -> None:
    try:
        raise ConnectionError("dial tcp 192.0.2.9:443: connection refused")
    except ConnectionError:
        logging.getLogger("fylgja.scrubbing-test").exception("the push to %s failed", "192.0.2.9")
    (record,) = kept.records
    line = logs.JsonFormatter().format(record)
    assert record.getMessage() == "the push to <address> failed (ConnectionError)"
    assert "192.0.2.9" not in line and "connection refused" not in line
    assert record.exc_info is None and "exception" not in json.loads(line)


def test_a_message_that_cannot_be_formatted_is_a_marker_and_nothing_is_raised(kept: Kept) -> None:
    logging.getLogger("fylgja.scrubbing-test").warning("bad %d", "192.0.2.10")
    (record,) = kept.records
    assert record.getMessage() == "(a WARNING record of fylgja.scrubbing-test whose message could not be formatted)"


def test_a_records_fields_are_scrubbed_where_a_handler_writes_them(kept: Kept) -> None:
    filtered = Kept()
    filtered.addFilter(Scrubbed())
    logger = logging.getLogger("fylgja.scrubbing-test")
    logger.addHandler(filtered)
    try:
        logger.info("pushed", **logs.fields(url="https://192.0.2.11/jsonrpc", commands=3))
    finally:
        logger.removeHandler(filtered)
    (record,) = filtered.records
    assert getattr(record, "fields", None) == {"url": "https://<address>/jsonrpc", "commands": 3}
