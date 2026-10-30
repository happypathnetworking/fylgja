"""The adapter held to the Go reader byte for byte (T021; R-15, FR-016, SC-002), before the Go
reader goes (T035, which removes this file with it).

The same arguments go to `bin/fylgja intent read … --out go.json`, through the host's server
(`FYLGJA_API_ADDRESS`, default 127.0.0.1:7650, and `FYLGJA_API_TOKEN`), and to the adapter's
`read … --out py.json`: for `fylgja-fixture` unpinned and at a pinned `at`, and for a
throwaway branch with a proposed change, by each of three stages and by its branch with a
probe file. The two files are compared byte for byte once each file's `observed_at` lines
are equalised, the instant each read was made being the one thing the two may differ in;
then `fylgja stage list --branch … --json` and the adapter's `stages --branch … --json` are
equal as JSON. Each read's time is printed beside the other's (research §5).

The host's server writes each Go read's snapshot into the host's store, as every `intent read
--out` does; nothing else of the host's is written. The throwaway branch, its proposed change
and its stages are deleted when the test ends. Boot no twin while it runs.

    set -a; . local/.env; set +a; orchestrator/.venv/bin/pytest -q orchestrator -m contract -k test_adapter_matches
"""

import io
import json
import os
import re
import subprocess
import time
from datetime import UTC, timedelta

import pytest

from fylgja_orchestrator.adapters.infrahub import __main__ as adapter

from .conftest import (
    FIXTURE_BRANCH,
    REPO,
    SCOPE,
    artifacts_ready_at,
    await_joined,
    await_moved,
    checksums,
    redact,
)

pytestmark = pytest.mark.contract

OBSERVED_AT = re.compile(rb'^(\s*"observed_at": )"[^"]*"(,?)$', re.M)
TIMES: list[tuple[str, float, float]] = []


@pytest.fixture(scope="module")
def go_cli():
    """`bin/fylgja` as a client of the host's server, with the API's token and address alone."""
    binary = REPO / "bin" / "fylgja"
    token = os.environ.get("FYLGJA_API_TOKEN", "")
    if not binary.is_file() or not token:
        pytest.skip("the compare needs bin/fylgja (make build) and FYLGJA_API_TOKEN (load local/.env)")
    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""), "FYLGJA_API_TOKEN": token}
    if os.environ.get("FYLGJA_API_ADDRESS"):
        env["FYLGJA_API_ADDRESS"] = os.environ["FYLGJA_API_ADDRESS"]

    def run(*args: str) -> tuple[int, dict, float]:
        started = time.monotonic()
        done = subprocess.run([str(binary), *args, "--json"], env=env, capture_output=True, text=True, timeout=300)
        took = time.monotonic() - started
        try:
            return done.returncode, json.loads(done.stdout), took
        except ValueError:
            pytest.skip(f"the host's server did not answer fylgja {args[0]} {args[1]}: {redact(done.stderr.strip())}")

    run("schema", "check", "--branch", FIXTURE_BRANCH)
    return run


def py_cli(*args: str) -> tuple[int, dict, float]:
    """The adapter's command with the same arguments and --json: its exit, document and time."""
    stdout, stderr = io.StringIO(), io.StringIO()
    started = time.monotonic()
    code = adapter.main([*args, "--json"], stdout, stderr, adapter.Env())
    return code, json.loads(stdout.getvalue()), time.monotonic() - started


def equalised(data: bytes) -> bytes:
    return OBSERVED_AT.sub(rb'\1"<observed_at>"\2', data)


def compare(go_cli, tmp_path, what: str, *args: str) -> dict:
    """One read by both, the same arguments: the files byte-equal once observed_at is
    equalised, and the documents' snapshot ids equal. Returns the Go document."""
    go_out, py_out = tmp_path / f"{what}-go.json", tmp_path / f"{what}-py.json"
    code, go_doc, go_took = go_cli("intent", "read", *args, "--out", str(go_out))
    assert code == 0, f"the Go reader's {what}: {go_doc['findings']}"
    code, py_doc, py_took = py_cli("read", *args, "--out", str(py_out))
    assert code == 0, f"the adapter's {what}: {py_doc['findings']}"
    go_bytes, py_bytes = go_out.read_bytes(), py_out.read_bytes()
    assert len(OBSERVED_AT.findall(go_bytes)) == len(OBSERVED_AT.findall(py_bytes)) == 2, (
        "each snapshot carries observed_at twice, at its top and in the CTM's envelope")
    assert equalised(py_bytes) == equalised(go_bytes), f"{what}: the adapter's file differs from the Go reader's"
    assert py_doc["snapshot_id"] == go_doc["snapshot_id"]
    assert py_doc.get("stage") == go_doc.get("stage"), f"{what}: the resolved stages differ"
    assert py_doc["findings"] == go_doc["findings"], f"{what}: the findings differ"
    TIMES.append((what, go_took, py_took))
    print(f"{what}: snapshot {py_doc['snapshot_id'][:12]}, {len(py_bytes)} bytes; the Go reader {go_took:.1f}s, "
          f"the adapter {py_took:.1f}s")
    return go_doc


def test_the_adapter_matches_the_go_reader(go_cli, fixture_tool, tmp_path):
    compare(go_cli, tmp_path, "the fixture", "--branch", FIXTURE_BRANCH, "--scope", SCOPE)
    # The whole second after the fixture's last artifact became Ready, with six fractional
    # digits that nothing may normalise.
    pinned = artifacts_ready_at(FIXTURE_BRANCH).astimezone(UTC).replace(microsecond=0) + timedelta(seconds=1)
    at = pinned.strftime("%Y-%m-%dT%H:%M:%S") + ".654321Z"
    compare(go_cli, tmp_path, "the fixture at a pinned at", "--branch", FIXTURE_BRANCH, "--at", at, "--scope", SCOPE)

    with fixture_tool.throwaway("compare") as branch:
        fixture_tool.propose(branch)
        fixture_tool.mark(branch, "seeded", description="seeded")
        before = checksums(branch)
        fixture_tool.change(branch, "-add-link")
        await_moved(branch, before, "n1", "n3")
        await_joined(branch)
        fixture_tool.mark(branch, "third-link", description="third link")
        for label in ("seeded", "third-link", "head"):
            doc = compare(go_cli, tmp_path, f"stage {label}", "--stage", f"{branch}/{label}", "--scope", SCOPE)
            assert doc["stage"]["label"] == label
        compare(go_cli, tmp_path, "the branch with a probe file", "--branch", branch, "--scope", SCOPE, "--probes",
                str(REPO / "testdata" / "probes" / "n1-loop.json"))

        code, go_doc, go_took = go_cli("stage", "list", "--branch", branch, "--scope", SCOPE)
        assert code == 0, go_doc["findings"]
        code, py_doc, py_took = py_cli("stages", "--branch", branch, "--scope", SCOPE)
        assert code == 0, py_doc["findings"]
        assert py_doc == go_doc, "the adapter's stages document differs from the Go server's stage list"
        assert [r["label"] for r in py_doc["stages"]["rows"]] == ["branch-point", "seeded", "third-link", "head"]
        TIMES.append(("the stage list", go_took, py_took))
        print(f"the stage list: equal; the Go server {go_took:.1f}s, the adapter {py_took:.1f}s")

    go_total, py_total = sum(t[1] for t in TIMES), sum(t[2] for t in TIMES)
    print(f"in all: the Go reader {go_total:.1f}s, the adapter {py_total:.1f}s over {len(TIMES)} reads")
