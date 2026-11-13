"""`box.py` against the running development NetBox: its status, a list read whole, a branch, and a refused token."""

from __future__ import annotations

import os
import secrets
from typing import Any

import pytest
from box import ADDRESS, PAGE, Box, BoxError

from .conftest import need


def test_status_names_netbox_and_the_plugin(box: Box) -> None:
    status = box.get("status/")
    assert isinstance(status["netbox-version"], str) and status["netbox-version"]
    assert isinstance(status["plugins"]["netbox_branching"], str) and status["plugins"]["netbox_branching"]


def test_listed_is_what_netbox_counts(box: Box) -> None:
    """More than one page: NetBox lists more object types than `PAGE`."""
    count = box.get("core/object-types/", limit=1)["count"]
    assert count > PAGE
    rows = box.listed("core/object-types/")
    assert len(rows) == count
    assert len({row["id"] for row in rows}) == count


def test_a_branch_is_ready_and_its_schema_id_selects_it(box: Box, branch: dict[str, Any]) -> None:
    """The fixture waits up to `BRANCH_WAIT_S`, 120 s, for `ready`: branches read `ready` 11.1 s at most after their
    request, and two whose `DELETE` NetBox refused while they provisioned read `ready` at reads 26.7 s to 28.2 s after
    it (design/verified-facts.md, "NetBox 4.7.5 with netbox-branching 1.2.3"); 120 s is about 4.3 times the slowest,
    28.2 s, a derivation."""
    assert branch["name"].startswith("fylgja-contract-")
    assert isinstance(branch["id"], int)
    assert branch["status"]["value"] == "ready"
    schema_id = branch["schema_id"]
    assert isinstance(schema_id, str) and len(schema_id) == 8
    made = box.post("dcim/sites/", {"name": "p9-contract", "slug": "p9-contract"}, branch=schema_id)
    found = box.one("dcim/sites/", branch=schema_id, name="p9-contract")
    assert found is not None and found["id"] == made["id"]
    assert box.one("dcim/sites/", name="p9-contract") is None


def test_a_token_netbox_never_made_is_a_boxerror_of_that_status() -> None:
    """A token of the v2 shape that NetBox never made was read refused with 403 and `Invalid v2 token`."""
    need(ADDRESS)
    key, secret = secrets.token_hex(6), secrets.token_hex(20)
    forged = Box(os.environ[ADDRESS], f"nbt_{key}.{secret}")
    try:
        with pytest.raises(BoxError) as raised:
            forged.get("status/")
    finally:
        forged.close()
    error = raised.value
    assert error.status == 403
    assert "Invalid v2 token" in str(error)
    for text in (str(error), repr(error)):
        assert key not in text and secret not in text
    assert error.__cause__ is None and error.__context__ is None


def test_no_contract_branch_outlives_its_test(box: Box) -> None:
    """Defined last in its module, it sees the branches of the tests pytest runs before it, the accounts' module's
    and this module's, and not the seed's module's, run after it: it reads what those left, and guards nothing of the
    tier. The pure tier's `netbox/tests/test_contract_branches.py` holds the rule itself, that the fixture deletes
    each branch whatever its test did."""
    names = [row["name"] for row in box.listed("plugins/branching/branches/")]
    assert [name for name in names if name.startswith("fylgja-contract-")] == []
