"""The create flow from the fixture, as the core's dry run (T028; R-15, FR-028, SC-002).

`twin-create --branch fylgja-fixture --dry-run` runs on Prefect's test harness against the real
Infrahub and a core server of the test's own, started with no INFRAHUB_* and no node login:
the flow reads the fixture and files snapshot `0940db93…` under the orchestrator's root, and
the core compiles it to bundle `c3872f5c…` and checks the host, which refuses only the logins
the test's core lacks. No twin boots: a dry run starts no run, and the host check could not
pass. The document is the run's artifact, as a check reads it.

    set -a; . local/.env; set +a; orchestrator/.venv/bin/pytest -q orchestrator -m contract \
        -k test_flows_create_from_fixture -s
"""

import json

import pytest

from fylgja_orchestrator.documents.findings import REJECTION, STATUS_REJECTED

from .conftest import FIXTURE_BRANCH, LOGIN_NAMES, SCOPE, artifact_of, flow_runs_of, use_core

pytestmark = pytest.mark.contract

SNAPSHOT_ID = "0940db93e2ad1244a097824ececdaa6979500b1ddeeef15ca3cd612da68656ef"
BUNDLE_PREFIX = "c3872f5c"
LOGIN_UNSET = "host.probe.login_unset"


def test_flows_create_from_fixture(platform, own_core, tmp_path, monkeypatch):
    from fylgja_orchestrator.flows.twin_create import twin_create

    flows = use_core(monkeypatch, own_core, tmp_path / "orchestrator")
    doc, _ = flows.run(twin_create, branch=FIXTURE_BRANCH, scope=SCOPE, dry_run=True)
    text = flows.text()

    # The snapshot the flow filed, under its root, and the one the core was sent.
    filed = sorted(p.name for p in (flows.root / "snapshots").iterdir())
    assert filed == [f"{SNAPSHOT_ID}.json"], f"the orchestrator's store holds {filed}"
    body = json.loads((flows.root / "snapshots" / filed[0]).read_text())
    assert body["snapshot_version"] == "2" and body["probes"] == [], body.keys()
    assert not (flows.root / "twin.json").exists(), "a dry run wrote the orchestrator's record"

    # The core's dry run: the bundle compiled, the host refused for the logins alone.
    assert doc.operation == "twin.create", doc.operation
    assert doc.blocks.get("bundle_id", "").startswith(BUNDLE_PREFIX), doc.blocks
    assert SNAPSHOT_ID[:8] in text and BUNDLE_PREFIX in text, text
    rejections = [f for f in doc.findings if f.severity == REJECTION]
    assert rejections and {f.rule for f in rejections} == {LOGIN_UNSET}, [f.to_dict() for f in rejections]
    assert sorted({f.object for f in rejections}) == sorted(n for n in LOGIN_NAMES if "SRLINUX" in n), rejections
    assert doc.status == STATUS_REJECTED and doc.exit_code == 1, doc.status

    # Nothing ran: the core was asked one dry run, which starts no run.
    assert own_core.operations() == [("twin.create", "rejected")], own_core.operations()
    assert not (own_core.state / "twin").exists(), "the dry run made a twin directory"

    # The run on the harness, its document filed as the run's artifact.
    [run] = flow_runs_of("twin-create")[:1]
    assert run.state.is_completed(), run.state
    assert artifact_of(str(run.id)) == doc.to_dict()
