"""A branch can hold intent Infrahub accepts and Fylgja cannot build, as
`internal/intent/defects_contract_test.go` held the Go reader to it (T020): every such
defect is reported by name, against the object at fault, and no snapshot or bundle is made.

The three seeded are the library's (017), on a throwaway `fylgja-test-py-*` branch: a cable
from n2's ethernet-1/99, which the SR Linux package's rule matches out of its range; an
uncabled port of n3, `console`, that no rule of the package matches; and a cable joining two
ports of n1. The Go reader ran every rule the compile runs and named all three in one pass.
The adapter runs the CTM's own rules alone, and the rules that read a package's ports are
the core's, which runs them on the snapshot when it compiles it (research §5.11). So the
port holds each defect to the side whose rule it is, each in one pass of that side: the
first two seeded, the adapter's read is clean and writes its snapshot, and the core's
compile of it refuses both, in one pass, with no bundle; then the third, and the adapter's
read is refused on it alone, writing no snapshot. The branch is deleted when the test ends.

    set -a; . local/.env; set +a; orchestrator/.venv/bin/pytest -q orchestrator -m contract -k test_read_defects
"""

import json

import pytest

from fylgja_orchestrator.adapters.infrahub import __main__ as adapter
from fylgja_orchestrator.adapters.infrahub import validate
from fylgja_orchestrator.documents import findings

from .conftest import SCOPE

pytestmark = pytest.mark.contract

RULE_UNMAPPABLE_LINKED = "interface.unmappable.linked"
RULE_INTERFACE_RULE_UNMATCHED = "interface.rule.unmatched"


def rejections(doc: dict) -> dict[str, str]:
    """A findings document's rejections by rule, each named once, every finding worded."""
    got = {}
    for f in doc["findings"]:
        assert f["message"], f"finding {f['rule']} on {f['object']} carries no message"
        if f["severity"] == findings.REJECTION:
            assert f["rule"] not in got, f"{f['rule']} reported twice: {got.get(f['rule'])} and {f['object']}"
            got[f["rule"]] = f["object"]
    return got


def adapter_read(branch: str, out) -> dict:
    """The adapter's `read --json`: its document, as the contract holds it."""
    answer = adapter.read(branch, scope=SCOPE, out=str(out), env=adapter.Env())
    doc = json.loads(answer.doc.json())
    findings.validate(doc)
    return doc


def test_seeded_defects_are_each_reported_by_their_side(fixture_tool, core, tmp_path):
    with fixture_tool.throwaway("defects") as branch:
        for port in ("n2:ethernet-1/99", "n3:ethernet-1/3", "n3:console"):
            fixture_tool.change(branch, "-add-interface", port)
        fixture_tool.change(branch, "-add-cable", "c-far=n2:ethernet-1/99,n3:ethernet-1/3")

        # The package's rules are the core's: the read is clean and writes its snapshot.
        snap = tmp_path / "packages.json"
        doc = adapter_read(branch, snap)
        assert doc["status"] == findings.STATUS_OK, doc["findings"]
        assert rejections(doc) == {}
        assert snap.is_file()
        code, compiled = core.compile(snap, tmp_path / "bundle")
        findings.validate(compiled)
        assert compiled["status"] == findings.STATUS_REJECTED, compiled["findings"]
        assert code == findings.EXIT_REJECTED
        # Both, in one pass: an operator fixing intent wants every problem at once.
        assert rejections(compiled) == {
            RULE_UNMAPPABLE_LINKED: "n2:ethernet-1/99",
            RULE_INTERFACE_RULE_UNMATCHED: "n3:console",
        }
        assert not compiled.get("bundle_id")
        assert not (tmp_path / "bundle").exists()

        # The CTM's own rule is the adapter's: the read is refused and writes nothing.
        for port in ("n1:ethernet-1/5", "n1:ethernet-1/6"):
            fixture_tool.change(branch, "-add-interface", port)
        fixture_tool.change(branch, "-add-cable", "c-loop=n1:ethernet-1/5,n1:ethernet-1/6")
        refused = tmp_path / "loop.json"
        doc = adapter_read(branch, refused)
    assert doc["status"] == findings.STATUS_REJECTED, doc["findings"]
    assert rejections(doc) == {validate.RULE_LINK_ENDPOINTS_SAME_DEVICE: "n1:ethernet-1/5|n1:ethernet-1/6"}
    assert not refused.exists()
    assert "snapshot_id" not in doc
