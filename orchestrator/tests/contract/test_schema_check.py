"""The adapter's `schema-check` against a real Infrahub, as `internal/cli/schema_contract_test.go`
held `fylgja schema check` to it (T020; FR-013 and SC-004 of 017): both fixtures conform, and
the check says what it verified on each, the line naming the library's commit and the kinds,
`--json`'s block each kind's fields; a branch that does not exist is an operational failure
naming it and saying it does not exist; and the check reads no intent: through a recording
proxy, the schema endpoint and no GraphQL at all. The check writes nothing in its working
directory.

The fixture branch is only read; the mixed fixture is seeded on a throwaway
`fylgja-test-py-*` branch, deleted when the test ends.

    set -a; . local/.env; set +a; orchestrator/.venv/bin/pytest -q orchestrator -m contract -k test_schema_check
"""

import io
import json
import os

import pytest

from fylgja_orchestrator.adapters.infrahub import __main__ as adapter
from fylgja_orchestrator.adapters.infrahub import mapping
from fylgja_orchestrator.documents import findings

from .conftest import FIXTURE_BRANCH

pytestmark = pytest.mark.contract

CONFORMANT_LINE = ("conformant with opsmill/schema-library@26336e9: DcimDevice, DcimPlatform, "
                   "OrganizationManufacturer, InterfacePhysical, DcimCable, DcimConnector")


def check(branch: str, *flags: str, address: str = "") -> tuple[int, str, str]:
    """`schema-check --branch <b>`: its exit, stdout and stderr, the token in neither."""
    stdout, stderr = io.StringIO(), io.StringIO()
    environ = dict(os.environ)
    if address:
        environ["INFRAHUB_ADDRESS"] = address
    code = adapter.main(["schema-check", "--branch", branch, *flags], stdout, stderr, adapter.Env(environ=environ))
    token = os.environ["INFRAHUB_API_TOKEN"]
    assert token not in stdout.getvalue() + stderr.getvalue()
    return code, stdout.getvalue(), stderr.getvalue()


def check_json(branch: str, proxy, cwd, monkeypatch) -> tuple[int, dict]:
    """--json through the recording proxy, in a scratch working directory, so that anything
    the command writes relative to it is caught."""
    monkeypatch.chdir(cwd)
    code, out, _ = check(branch, "--json", address=proxy.address)
    doc = json.loads(out)
    findings.validate(doc)
    assert list(cwd.iterdir()) == [], "schema check wrote into the working directory"
    return code, doc


def test_schema_check_passes_on_both_fixtures(fixture_tool, proxy, tmp_path, monkeypatch):
    with fixture_tool.throwaway("mixed", mixed=True) as mixed:
        for branch in (FIXTURE_BRANCH, mixed):
            code, out, _ = check(branch)
            assert code == findings.EXIT_OK
            assert out.startswith(CONFORMANT_LINE + "\n"), out

            cwd = tmp_path / branch
            cwd.mkdir()
            code, doc = check_json(branch, proxy, cwd, monkeypatch)
            assert code == findings.EXIT_OK, doc["findings"]
            assert doc["status"] == findings.STATUS_OK
            verified = doc.get("verified")
            assert verified, "a clean check reported nothing as verified"
            assert (verified["model"], verified["version"]) == (mapping.MODEL, mapping.VERSION)
            assert [k["kind"] for k in verified["kinds"]] == [k.kind for k in mapping.TABLES]
            for k in verified["kinds"]:
                assert k["fields"], f"kind {k['kind']} names no field"


def test_schema_check_on_a_missing_branch(proxy, tmp_path, monkeypatch):
    branch = "fylgja-test-no-such-branch"
    code, doc = check_json(branch, proxy, tmp_path, monkeypatch)
    assert code == findings.EXIT_ERROR, doc["findings"]
    [f] = doc["findings"]
    assert f["rule"] == "operation.failed"
    # Naming the branch is not enough: Infrahub says it does not exist in the schema
    # endpoint's body, and a bare "HTTP 400" would tell an operator with a typo nothing.
    assert branch in f["message"]
    assert "not found" in f["message"]
    assert os.environ["INFRAHUB_API_TOKEN"] not in f["message"]


def test_schema_check_issues_no_object_query(proxy, tmp_path, monkeypatch):
    code, _ = check_json(FIXTURE_BRANCH, proxy, tmp_path, monkeypatch)
    assert code == findings.EXIT_OK
    assert "/api/schema" in proxy.paths(), f"the schema endpoint was not recorded ({proxy.paths()})"
    assert proxy.graphql_bodies() == [], "schema check issued a GraphQL request; it must read no intent"
