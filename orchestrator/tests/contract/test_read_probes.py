"""Probes as the read takes them from a real Infrahub (T020; SC-005, SC-006), as
`internal/server/probes_contract_test.go`'s `TestProbesFromTheKind` and
`internal/cli/probes_contract_test.go`'s `TestIntentReadFilesASnapshot2` held the Go reader
and the core's server to it.

The kind is the second source of a read's one list: n2-loop written into FylgjaProbe on the
default branch through the fixture tool's `-probes`, then four reads of a seeded throwaway
branch. With no probe file the snapshot carries the kind's n2-loop; with n1-loop's file, the
file's alone; with the probe deleted and neither, `[]`; with an empty file, `none.json`, the
snapshot neither took. The kind must hold no probe when the test starts, since it deletes
every probe there when it ends (`-delete-probes`), and holds none after.

A read with a probe file writes a snapshot `2` carrying that one probe, the kind never
asked; the core's compile of it, on a server of the test's own, places n1-loop's two hosts
on n1's ethernet-1/10 and ethernet-1/11 and records them as synthesized: the Go test's
`twin create --snapshot --dry-run`, less the host check, which is the core's alone. The
branch is deleted when the module's tests end.

    set -a; . local/.env; set +a; orchestrator/.venv/bin/pytest -q orchestrator -m contract -k test_read_probes
"""

import io
import json
import os
import time

import pytest

from fylgja_orchestrator.adapters.infrahub import __main__ as adapter
from fylgja_orchestrator.adapters.infrahub import probes, snapshot
from fylgja_orchestrator.documents import findings

from .conftest import REPO, SCOPE, probe_count

pytestmark = pytest.mark.contract

PROBES = REPO / "testdata" / "probes"


@pytest.fixture(scope="module")
def seeded(fixture_tool):
    with fixture_tool.throwaway("probes") as branch:
        yield branch


def declaration(name: str) -> list[dict]:
    """A declaration under testdata/probes/, parsed as the read parses a file: its probes."""
    path = PROBES / name
    decl, found = probes.parse(path.read_bytes(), str(path))
    assert decl is not None, f"{name}: {list(found)}"
    return decl["probes"]


def test_probes_from_the_kind(fixture_tool, seeded, tmp_path):
    held = probe_count()
    assert held == 0, (f"the default branch holds {held} FylgjaProbe; this test runs on an empty kind, since it "
                       "deletes every probe there")
    try:
        print(fixture_tool.run("-probes", str(PROBES / "n2-loop.json")).strip())

        def read(which: str, probes_path: str | None) -> dict:
            started = time.monotonic()
            out = tmp_path / f"{which.replace(' ', '-')}.json"
            answer = adapter.read(seeded, scope=SCOPE, probes_path=probes_path, out=str(out), env=adapter.Env())
            assert answer.doc.status == findings.STATUS_OK, f"the read {which}: {list(answer.doc.findings)}"
            assert list(answer.doc.findings) == [], f"the read {which} reported findings"
            s = snapshot.read(out)
            assert s["snapshot_id"] == answer.doc.blocks["snapshot_id"]
            assert s["ctm"]["envelope"]["branch"] == seeded
            print(f"the read {which}: snapshot {s['snapshot_id'][:12]} carrying {len(s['probes'])} probe(s) "
                  f"in {time.monotonic() - started:.1f}s")
            return s

        from_kind = read("with no file", None)
        assert from_kind["probes"] == declaration("n2-loop.json")

        from_file = read("with n1-loop's file", str(PROBES / "n1-loop.json"))
        assert from_file["probes"] == declaration("n1-loop.json")

        assert "deleted 1 probe of FylgjaProbe" in fixture_tool.run("-delete-probes")
        neither = read("with neither", None)
        assert neither["probes"] == []

        # An empty file declares none: the take is the one with neither, its snapshot the same.
        empty = read("with an empty file", str(PROBES / "none.json"))
        assert empty["probes"] == [] and empty["snapshot_version"] == snapshot.VERSION
        assert empty["snapshot_id"] == neither["snapshot_id"]

        ids = {from_kind["snapshot_id"], from_file["snapshot_id"], neither["snapshot_id"]}
        assert len(ids) == 3, "the three reads' snapshots are not three, each list its own"
    finally:
        fixture_tool.run("-delete-probes")
        assert probe_count() == 0, "after the test the default branch holds a FylgjaProbe"


def test_a_read_with_a_probe_file_writes_a_snapshot_2_the_core_compiles(seeded, proxy, core, tmp_path):
    out = tmp_path / "snap.json"
    stdout, stderr = io.StringIO(), io.StringIO()
    env = adapter.Env(environ={**os.environ, "INFRAHUB_ADDRESS": proxy.address})
    started = time.monotonic()
    code = adapter.main(["read", "--branch", seeded, "--scope", SCOPE, "--probes", str(PROBES / "n1-loop.json"),
                         "--out", str(out), "--json"], stdout, stderr, env)
    doc = json.loads(stdout.getvalue())
    assert code == findings.EXIT_OK and doc["findings"] == [], doc
    findings.validate(doc)
    raw = out.read_bytes()
    s = snapshot.unmarshal(raw)
    assert b'"snapshot_version": "2"' in raw
    assert s["probes"] == declaration("n1-loop.json")
    assert doc["snapshot_id"] == s["snapshot_id"]
    assert s["ctm"]["envelope"]["branch"] == seeded
    asked = proxy.graphql_bodies()
    assert asked, "the read asked GraphQL nothing"
    assert not [b for b in asked if probes.PROBE_KIND in b], "the kind was read beside a probe file"
    print(f"read --probes: snapshot {s['snapshot_id'][:12]} carrying {len(s['probes'])} probe(s) "
          f"in {time.monotonic() - started:.1f}s")

    started = time.monotonic()
    bundle = tmp_path / "bundle"
    code, compiled = core.compile(out, bundle)
    assert code == findings.EXIT_OK, compiled
    findings.validate(compiled)
    assert compiled["snapshot_id"] == s["snapshot_id"] and compiled["bundle_id"]
    manifest = json.loads((bundle / "manifest.json").read_text())
    assert manifest["fidelity"]["synthesized"] == ["n1-loop-a", "n1-loop-b"]
    [placed] = manifest["probes"]
    assert placed["name"] == "n1-loop"
    assert [(h["node"], h["device"], h["interface"]) for h in placed["hosts"]] == [
        ("n1-loop-a", "n1", "ethernet-1/10"),
        ("n1-loop-b", "n1", "ethernet-1/11"),
    ]
    print(f"twin compile --snapshot: bundle {compiled['bundle_id'][:12]} in {time.monotonic() - started:.1f}s")
