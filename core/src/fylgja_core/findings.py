"""Findings 1: a verdict (formats/findings-1.schema.json, D-025).

`Verdict` is the document's model: what a compile, a package validation, a plan, a run or a
verification concluded, with every finding that led there. Anything malformed or refused at
the door is a problem document (problem.py), never a verdict.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Literal

from fylgja_core import documents
from fylgja_core.documents import Problem, Rejected

VERSION = "1"

# Rule ids. Clients and tests match on them.
RULE_INVALID = "findings.invalid"
RULE_VERSION = "findings.version.unsupported"

# The severities, most serious first; findings sort by them.
SEVERITIES: tuple[str, ...] = ("error", "warning", "info")


@dataclass(frozen=True, kw_only=True)
class Finding:
    """One finding: a stable rule, its severity, what it is about, and one plain sentence."""

    rule: str
    severity: Literal["error", "warning", "info"]
    object: str | None = None
    message: str


@dataclass(frozen=True, kw_only=True)
class Subject:
    """What the verdict is about; only the ids that apply are set."""

    twin: str | None = None
    run_id: str | None = None
    blueprint_id: str | None = None
    bundle_id: str | None = None
    deployment_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class Counts:
    """Verify's assertion counts."""

    held: int
    failed: int
    skipped: int


@dataclass(frozen=True, kw_only=True)
class Wait:
    """A step's wait for verify to hold."""

    outcome: Literal["settled", "expired", "cancelled"]
    budget_s: int
    after_s: float


@dataclass(frozen=True, kw_only=True)
class Loss:
    """One probe's flow across a step, from one of its hosts; reported, never asserted."""

    probe: str
    from_: Literal["a", "b"] = field(metadata={"key": "from"})
    outcome: Literal["measured", "not_started", "not_read", "interrupted", "dropped"]
    sent: int | None = None
    lost: int | None = None
    longest_gap_s: float | None = None


@dataclass(frozen=True, kw_only=True)
class Verdict:
    """A findings 1 document as a model."""

    findings_version: str = VERSION
    operation: Literal["compile", "packages.validate", "plan", "create", "step", "destroy", "verify"]
    status: Literal["ok", "rejected", "failed", "unclean", "diverged", "nonconforming"]
    subject: Subject
    findings: tuple[Finding, ...]
    counts: Counts | None = None
    wait: Wait | None = None
    loss: tuple[Loss, ...] | None = None


def order(items: Iterable[Finding]) -> tuple[Finding, ...]:
    """Findings as a verdict lists them: by severity, then rule, then object."""
    return tuple(sorted(items, key=lambda f: (SEVERITIES.index(f.severity), f.rule, f.object or "")))


def validate(doc: Any) -> list[Problem]:
    """Every problem with `doc` as a verdict, sorted; an empty list means it is valid."""
    problems = documents.unsupported_version(doc, "findings_version", VERSION, RULE_VERSION)
    if problems:
        return problems
    return documents.schema_problems("findings-1", doc, RULE_INVALID)


def decode(doc: Any) -> Verdict:
    """The `Verdict` a document holds, or `Rejected` with every problem."""
    problems = validate(doc)
    if problems:
        raise Rejected(problems)
    return documents.decode(Verdict, doc)
