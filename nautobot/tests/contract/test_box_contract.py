"""`box.py` against the running development Nautobot: its status, a list read whole, an object found once, and a
refused token."""

from __future__ import annotations

import os
import secrets

import pytest
from box import ADDRESS, PAGE, Box, BoxError

from .conftest import PREFIX, TAGS, need


def test_status_names_nautobot_and_golden_config(box: Box) -> None:
    status = box.get("status/")
    assert isinstance(status["nautobot-version"], str) and status["nautobot-version"]
    assert isinstance(status["plugins"]["nautobot_golden_config"], str) and status["plugins"]["nautobot_golden_config"]


def test_listed_is_what_nautobot_counts(box: Box) -> None:
    """More than one page: Nautobot lists more content types than `PAGE`."""
    count = box.get("extras/content-types/", limit=1)["count"]
    assert count > PAGE
    rows = box.listed("extras/content-types/")
    assert len(rows) == count
    assert len({row["id"] for row in rows}) == count


def test_a_tag_made_is_found_once(box: Box, scratch: str) -> None:
    made = box.ensure(TAGS, {"name": scratch}, {"name": scratch, "content_types": ["dcim.device"]})
    assert made["name"] == scratch
    found = box.one(TAGS, name=scratch)
    assert found is not None and found["id"] == made["id"]
    again = box.ensure(TAGS, {"name": scratch}, {"name": scratch, "content_types": ["dcim.device"]})
    assert again["id"] == made["id"]
    assert [kind for kind, path, uuid in box.ensured if path == TAGS and uuid == made["id"]] == ["made", "found"]


def test_a_token_nautobot_never_made_is_a_boxerror_of_that_status() -> None:
    """A token Nautobot never made was read refused with 403 and `Invalid token`."""
    need(ADDRESS)
    forged = secrets.token_hex(20)
    refused = Box(os.environ[ADDRESS], forged)
    try:
        with pytest.raises(BoxError) as raised:
            refused.get("status/")
    finally:
        refused.close()
    error = raised.value
    assert error.status == 403
    assert "Invalid token" in str(error)
    for text in (str(error), repr(error)):
        assert forged not in text
    assert error.__cause__ is None and error.__context__ is None


def test_no_contract_object_outlives_its_test(box: Box) -> None:
    """Defined last in its module, it sees what the tests pytest runs before it left; it guards nothing of the tier
    whole, and nothing here reads the seed's own tag."""
    names = [row["name"] for row in box.listed(TAGS)]
    assert [name for name in names if name.startswith(PREFIX)] == []
