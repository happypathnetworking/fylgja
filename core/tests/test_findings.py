"""Findings 1 (formats/findings-1.schema.json): a verdict as a model, which encodes to a
document the schema accepts and reads back."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from fylgja_core import documents, findings
from fylgja_core.documents import Problem, Rejected
from fylgja_core.findings import RULE_INVALID, RULE_VERSION, Counts, Finding, Loss, Subject, Verdict, Wait

ID_B = "b" * 64
RUN = "01ARZ3NDEKTSV4RRFFQ69G5FAV"
STEP = Verdict(
    operation="step",
    status="ok",
    subject=Subject(twin="three-node", run_id=RUN, bundle_id=ID_B),
    findings=(Finding(rule="verify.neighbor.skipped", severity="info", object="n1:ethernet-1/10",
                      message="A synthesized link's neighbour is not asserted."),),
    counts=Counts(held=12, failed=0, skipped=1),
    wait=Wait(outcome="settled", budget_s=120, after_s=18.5),
    loss=(Loss(probe="n1-loop", from_="a", outcome="measured", sent=90, lost=2, longest_gap_s=0.4),
          Loss(probe="n1-loop", from_="b", outcome="not_read")),
)


def doc() -> dict[str, Any]:
    encoded: dict[str, Any] = documents.encode(STEP)
    return copy.deepcopy(encoded)


def test_a_verdict_encodes_to_a_valid_document_and_decodes_back() -> None:
    assert findings.validate(doc()) == []
    assert findings.decode(doc()) == STEP


def test_a_loss_names_the_host_it_ran_from() -> None:
    assert doc()["loss"][1] == {"probe": "n1-loop", "from": "b", "outcome": "not_read"}


def test_a_restore_verdict_carries_verifys_counts_and_its_wait_and_no_loss() -> None:
    restored = Verdict(operation="restore", status="ok", subject=Subject(twin="three-node", run_id=RUN, bundle_id=ID_B),
                       findings=(), counts=Counts(held=12, failed=0, skipped=1),
                       wait=Wait(outcome="settled", budget_s=180, after_s=2.5))
    encoded = documents.encode(restored)
    assert findings.validate(encoded) == []
    assert "loss" not in encoded
    assert findings.decode(encoded) == restored


def test_a_compile_verdict_carries_no_counts_wait_or_loss() -> None:
    rejected = Verdict(operation="compile", status="rejected", subject=Subject(blueprint_id=ID_B),
                       findings=(Finding(rule="platform.unsupported", severity="error", object="n2",
                                         message="No loaded package is junos."),))
    encoded = documents.encode(rejected)
    assert findings.validate(encoded) == []
    assert set(encoded) == {"findings_version", "operation", "status", "subject", "findings"}


def test_another_version_is_refused_first() -> None:
    other = {**doc(), "findings_version": "2"}
    assert findings.validate(other) == [Problem("/findings_version", RULE_VERSION, "version '2'; this core reads 1")]


def test_a_measured_loss_without_its_counters_is_a_schema_fault() -> None:
    bad = doc()
    del bad["loss"][0]["sent"]
    bad["findings"][0]["rule"] = "NoDots"
    found = findings.validate(bad)
    assert {p.rule for p in found} == {RULE_INVALID}
    assert {p.pointer for p in found} == {"/loss/0", "/findings/0/rule"}
    with pytest.raises(Rejected):
        findings.decode(bad)


def test_findings_sort_by_severity_then_rule_then_object() -> None:
    info = Finding(rule="a.b", severity="info", object="x", message="i")
    warning = Finding(rule="a.a", severity="warning", object="x", message="w")
    error_y = Finding(rule="a.a", severity="error", object="y", message="e")
    error_x = Finding(rule="a.a", severity="error", object="x", message="e")
    error_none = Finding(rule="a.a", severity="error", message="e")
    ordered = findings.order([info, warning, error_y, error_x, error_none])
    assert ordered == (error_none, error_x, error_y, warning, info)
    assert findings.SEVERITIES == ("error", "warning", "info")
