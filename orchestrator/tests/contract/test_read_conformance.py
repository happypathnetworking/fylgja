"""Conformance against a real Infrahub, as `internal/intent/conformance_contract_test.go`
held the Go reader to it (T020): the fixture branch conforms, and the check says what it
verified; the schema endpoint has no time axis, so a pinned read's schema hash is the
branch's current one; and a branch whose DCIM lacks a kind the mapping reads is refused by
name, once, the message naming the library's commit, the read refusing it on that finding
alone with no request beyond the schema's.

The last seeds a throwaway `fylgja-test-py-*` branch with the library alone (`-schema-only`)
and removes `DcimCable` from it (`-load-schema-file`), deleting it when it ends.

    set -a; . local/.env; set +a; orchestrator/.venv/bin/pytest -q orchestrator -m contract -k test_read_conformance
"""

from pathlib import Path

import pytest

from fylgja_orchestrator.adapters.infrahub import mapping, schema
from fylgja_orchestrator.adapters.infrahub.client import Client, from_env
from fylgja_orchestrator.documents.findings import REJECTION

from .conftest import FIXTURE_BRANCH, read_under

pytestmark = pytest.mark.contract

CABLE_ABSENT = Path(__file__).resolve().parents[1] / "data" / "schema" / "dcim-cable-absent.yaml"


def conformance(branch: str, at: str = ""):
    return schema.check_conformance(Client(from_env(branch, at)))


def test_conformance_on_the_fixture_branch():
    conf, found = conformance(FIXTURE_BRANCH)
    assert not found.rejected, list(found)
    assert (conf.model, conf.version) == (mapping.MODEL, mapping.VERSION)
    assert len(conf.kinds) == len(mapping.TABLES)
    assert conf.schema_hash


def test_conformance_sends_no_at():
    # The hash a read records is the branch's current schema hash, even for a pinned read:
    # deliberate, and recorded here so nobody reads it as "the schema as of at".
    unpinned, _ = conformance(FIXTURE_BRANCH)
    pinned = schema.schema_info(Client(from_env(FIXTURE_BRANCH, "2026-09-09T00:00:00Z")))
    assert pinned.hash == unpinned.schema_hash


def test_schema_check_names_a_missing_kind(fixture_tool, proxy):
    """US3 of 017 (FR-011, FR-012): on a branch holding the library alone, DcimCable removed
    by a state: absent document. Conformance names it once, though Infrahub also leaves
    DcimConnector with no implementer, and the read refuses the branch on it with no request
    beyond the schema's."""
    with fixture_tool.throwaway("nocable", schema_only=True) as branch:
        print(fixture_tool.change(branch, "-load-schema-file", str(CABLE_ABSENT)).strip())

        _, found = conformance(branch)
        assert len(found) == 1, f"findings {list(found)}; want schema.kind.missing DcimCable alone"
        f = found[0]
        assert (f.severity, f.rule, f.object) == (REJECTION, schema.RULE_KIND_MISSING, "DcimCable")
        assert f.message.endswith(f"as {mapping.MODEL}@{mapping.VERSION} has it")

        ctm, read, err = read_under(branch, address=proxy.address)
    assert err is None
    assert ctm is None
    assert list(read) == list(found)
    assert proxy.paths() == ["/api/schema"], "the read asked more than the schema endpoint"
