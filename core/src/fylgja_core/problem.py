"""Problem 1: an RFC 9457 problem document (formats/problem-1.schema.json, D-025).

`ProblemDocument` is the core's one answer for a request that is malformed, unauthorised,
refused or conflicting, and for a server fault. Its `type` is a problem class, `rule` the
stable id clients match on, and `findings` carries several faults at once. The format has
no version member: RFC 9457's shape is the version.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fylgja_core import documents
from fylgja_core.documents import Problem, Rejected
from fylgja_core.findings import Finding

# Rule id. Clients and tests match on it.
RULE_INVALID = "problem.invalid"


@dataclass(frozen=True, kw_only=True)
class ProblemDocument:
    """A problem 1 document as a model."""

    type: str
    title: str
    status: int
    detail: str | None = None
    instance: str | None = None
    rule: str
    findings: tuple[Finding, ...] | None = None


def validate(doc: Any) -> list[Problem]:
    """Every problem with `doc` as a problem document, sorted; an empty list means it is valid."""
    return documents.schema_problems("problem-1", doc, RULE_INVALID)


def decode(doc: Any) -> ProblemDocument:
    """The `ProblemDocument` a document holds, or `Rejected` with every problem."""
    problems = validate(doc)
    if problems:
        raise Rejected(problems)
    return documents.decode(ProblemDocument, doc)
