"""The adapter's client against the running Infrahub: the fixture branch's schema conforms
to the table, a missing branch and a refused credential are named, and a pinned `at` with
an offset reaches GraphQL verbatim. Reads only."""

import os
from datetime import UTC, datetime

import pytest

from fylgja_orchestrator.adapters.infrahub import schema
from fylgja_orchestrator.adapters.infrahub.client import Client, ClientError, Config, from_env

pytestmark = pytest.mark.contract


def test_the_fixture_branch_conforms():
    conf, found = schema.check_conformance(Client(from_env("fylgja-fixture")))
    assert list(found) == []
    assert conf.schema_hash
    assert [k for k, _ in conf.kinds] == [
        "DcimDevice", "DcimPlatform", "OrganizationManufacturer", "InterfacePhysical", "DcimCable", "DcimConnector",
    ]


def test_a_missing_branch_is_named_by_the_schema_endpoint():
    with pytest.raises(ClientError) as raised:
        Client(from_env("fylgja-test-py-no-such-branch")).schema_document()
    assert raised.value.branch_missing
    assert str(raised.value) == (
        "reading the schema (branch fylgja-test-py-no-such-branch): "
        "HTTP 400: Branch: fylgja-test-py-no-such-branch not found."
    )


def test_a_missing_branch_is_named_by_graphql():
    with pytest.raises(ClientError) as raised:
        Client(from_env("fylgja-test-py-no-such-branch")).graphql("query { Branch { name } }")
    assert raised.value.branch_missing


def test_a_refused_credential_is_named_and_never_quoted():
    cfg = from_env("main")
    wrong = Config(address=cfg.address, token="fylgja-not-a-token", branch="main")
    for read in (lambda c: c.schema_document(), lambda c: c.graphql("query { Branch { name } }")):
        with pytest.raises(ClientError) as raised:
            read(Client(wrong))
        assert raised.value.credential_refused
        assert "fylgja-not-a-token" not in str(raised.value)
        assert os.environ["INFRAHUB_API_TOKEN"] not in str(raised.value)


def test_a_pinned_at_with_an_offset_is_read():
    at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")
    data = Client(from_env("main", at)).graphql("query { Branch { name } }")
    assert "main" in {b["name"] for b in data["Branch"]}
