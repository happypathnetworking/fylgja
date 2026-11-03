"""Problem 1 (formats/problem-1.schema.json): an RFC 9457 problem document as a model, which
encodes to a document the schema accepts and reads back."""

from __future__ import annotations

import pytest

from fylgja_core import documents, problem
from fylgja_core.documents import Rejected
from fylgja_core.findings import Finding
from fylgja_core.problem import RULE_INVALID, ProblemDocument

UNPROCESSABLE = ProblemDocument(
    type="https://github.com/happypathnetworking/fylgja/core/problems/unprocessable",
    title="Unprocessable",
    status=422,
    detail="The blueprint does not compile.",
    instance="/v1/bundles",
    rule="bundle.rejected",
    findings=(Finding(rule="platform.unsupported", severity="error", object="/network/devices/1/platform",
                      message="No loaded package is junos."),),
)


def test_a_problem_encodes_to_a_valid_document_and_decodes_back() -> None:
    doc = documents.encode(UNPROCESSABLE)
    assert problem.validate(doc) == []
    assert problem.decode(doc) == UNPROCESSABLE


def test_a_problem_with_one_fault_carries_no_findings() -> None:
    conflict = ProblemDocument(type="about:blank", title="Conflict", status=412, rule="twin.conflict")
    doc = documents.encode(conflict)
    assert problem.validate(doc) == []
    assert set(doc) == {"type", "title", "status", "rule"}


def test_a_schema_fault_is_reported_with_its_pointer_and_decode_refuses_it() -> None:
    bad = {**documents.encode(UNPROCESSABLE), "status": 200, "findings": []}
    found = problem.validate(bad)
    assert {p.rule for p in found} == {RULE_INVALID}
    assert {p.pointer for p in found} == {"/status", "/findings"}
    with pytest.raises(Rejected):
        problem.decode(bad)
