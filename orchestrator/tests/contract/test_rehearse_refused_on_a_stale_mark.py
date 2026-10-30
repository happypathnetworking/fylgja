"""A rehearsal refused before any run on a stale mark (T028; R-15, FR-028; US1 scenario 5):
`internal/server/rehearse_contract_test.go`'s `TestRehearseRefusesBeforeAnyRun` carried over
to the rehearse flow.

On a throwaway branch with a draft, the mark `seeded`, then an intent change with no generate
and the mark `description-stale` after it, `twin-rehearse` on Prefect's test harness is
refused with the plan's findings, `stage.artifact.stale` on each device the change moved,
rejected, exit 1, with 014's words. The core of the test's own (no INFRAHUB_*, no node login)
is asked to compile and nothing else: no run starts, no host is checked and no twin directory
is made. The report is posted on the proposed change as one thread holding the markdown, which
the flow posts now that no check does (R-11). The branch, its stages, its proposed change and
the thread are deleted when the test ends.

    set -a; . local/.env; set +a; orchestrator/.venv/bin/pytest -q orchestrator -m contract \
        -k test_rehearse_refused_on_a_stale_mark -s
"""

import pytest

from fylgja_orchestrator.adapters.infrahub.stages import LABEL_BRANCH_POINT, LABEL_HEAD
from fylgja_orchestrator.documents.deadline import ROLE_REFUSED
from fylgja_orchestrator.documents.findings import REJECTION, STATUS_REJECTED

from .conftest import SCOPE, artifact_of, flow_runs_of, threads_of, use_core

pytestmark = pytest.mark.contract

DEVICES = ["n1", "n2", "n3"]
STALE = "stage.artifact.stale"
COMPILE_ONLY = {"twin.compile", "twin.diff"}
"""What a plan asks the core: each stage's compile and each pair's step."""


def rejections_of(found, rule: str) -> list[str]:
    """A list's rejections of rule, by object, in order (the Go test's rejectionsOf)."""
    return [f.object for f in found if f.severity == REJECTION and f.rule == rule]


def test_rehearse_refused_on_a_stale_mark(platform, fixture_tool, own_core, tmp_path, monkeypatch):
    from fylgja_orchestrator.flows.twin_rehearse import twin_rehearse

    with fixture_tool.throwaway("stale") as name:
        id = fixture_tool.propose(name)
        fixture_tool.mark(name, "seeded", description="seeded")
        fixture_tool.change(name, "-set-description", "stale-description")
        fixture_tool.mark(name, "description-stale", description="the description, not rendered")

        flows = use_core(monkeypatch, own_core, tmp_path / "orchestrator")
        doc, took = flows.run(twin_rehearse, branch=name, scope=SCOPE, markdown=True)
        print(f"twin-rehearse refused in {took:.1f}s")
        text = flows.text()

        assert doc.status == STATUS_REJECTED and doc.exit_code == 1, (doc.status, text)
        got = rejections_of(doc.findings, STALE)
        assert got[:len(DEVICES)] == DEVICES, f"{STALE} names {got}; want {DEVICES} first"
        block = doc.blocks.get("rehearsal")
        assert block is not None, f"the refusal carries no rehearsal block: {doc.to_dict()}"
        assert block["proposed_change"]["id"] == id, block["proposed_change"]
        assert (block.get("run"), block.get("destroy"), block.get("baseline")) == (None, None, None), (
            "the refusal names a run, a destroy or a baseline", block)
        labels = [s["label"] for s in block["stages"]]
        assert labels == [LABEL_BRANCH_POINT, "seeded", "description-stale", LABEL_HEAD], labels
        [stale] = [s for s in block["stages"] if s["label"] == "description-stale"]
        assert stale["role"] == ROLE_REFUSED, stale
        assert [f["object"] for f in stale["findings"] if f["rule"] == STALE] == DEVICES, stale["findings"]
        assert f"{name}/description-stale: refused ({STALE})" in text, text

        # Before any run: the core compiled, and was asked nothing that runs or checks the host.
        asked = {op for op, _ in own_core.operations()}
        assert asked and asked <= COMPILE_ONLY, own_core.operations()
        assert not (own_core.state / "twin").exists(), "the refusal made a twin directory"
        assert not (flows.root / "twin.json").exists(), "the refusal wrote the orchestrator's record"

        # The report: posted as one thread holding the markdown printed (the sink, a printed
        # line, drops its last newline), and the run's artifact.
        [md] = flows.markdown
        assert threads_of(id) == [[md + "\n"]], "the report is not the proposed change's one thread"
        assert "rehearsal.report.unposted" not in {f.rule for f in doc.findings}
        [run] = flow_runs_of("twin-rehearse")[:1]
        assert run.state.is_completed(), run.state
        assert artifact_of(str(run.id)) == doc.to_dict()
