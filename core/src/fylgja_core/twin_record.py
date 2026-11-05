"""Twin record 1: one named twin in the state store, and the twin resource the API serves
(formats/twin-record-1.schema.json, D-019, D-023, D-025).

`TwinRecord` is the document's model: what a client asked for (`Spec`) and what the
reconcile loop last saw (`Status`), with the record's `revision` for compare-and-set and
the twin's `generation`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from fylgja_core import documents
from fylgja_core.documents import Problem, Rejected

VERSION = "1"

# Rule ids. Clients and tests match on them.
RULE_INVALID = "twin_record.invalid"
RULE_VERSION = "twin_record.version.unsupported"

# The phases the loop records, in order; `destroyed` ends a deletion.
Phase = Literal["compiled", "admitted", "planned", "applied", "ready", "pushed", "verified", "flows", "destroyed"]
StepPhase = Literal["compiled", "admitted", "planned", "applied", "ready", "pushed", "verified", "flows"]


@dataclass(frozen=True, kw_only=True)
class Spec:
    """What the twin should be, written by a client; one of the two ids is set."""

    blueprint_id: str | None = None
    bundle_id: str | None = None
    driver: str
    allow_restart: bool


@dataclass(frozen=True, kw_only=True)
class Condition:
    """Ready, Stepping or Diverged, with the stable reason that set it."""

    type: Literal["Ready", "Stepping", "Diverged"]
    status: Literal["True", "False", "Unknown"]
    reason: str | None = None
    since: str | None = None


@dataclass(frozen=True, kw_only=True)
class Node:
    """One runtime node the twin holds, by the driver's handle."""

    name: str
    handle: str
    address: str | None = None
    access: str | None = None
    holds: str | None = None
    incarnation: str | None = None


@dataclass(frozen=True, kw_only=True)
class LastStep:
    """The latest step's outcome, by its run."""

    outcome: Literal["running", "stepped", "unchanged", "diverged", "cancelled", "rejected"]
    from_: str = field(metadata={"key": "from"})
    to: str
    phase: StepPhase
    run_id: str


@dataclass(frozen=True, kw_only=True)
class Status:
    """What the reconcile loop last saw, written only by it."""

    observed_generation: int
    conditions: tuple[Condition, ...]
    phase: Phase | None = None
    run_id: str | None = None
    generation_in_flight: int | None = None
    blueprint_id: str | None = None
    bundle_id: str | None = None
    deployment_id: str | None = None
    allocation: Mapping[str, Any] | None = None
    nodes: tuple[Node, ...]
    last_step: LastStep | None = None


@dataclass(frozen=True, kw_only=True)
class TwinRecord:
    """A twin record 1 document as a model."""

    record_version: str = VERSION
    name: str
    revision: int
    generation: int
    deletion_requested_at: str | None = None
    spec: Spec
    status: Status


def validate(doc: Any) -> list[Problem]:
    """Every problem with `doc` as a twin record, sorted; an empty list means it is valid."""
    problems = documents.unsupported_version(doc, "record_version", VERSION, RULE_VERSION)
    if problems:
        return problems
    return documents.schema_problems("twin-record-1", doc, RULE_INVALID)


def decode(doc: Any) -> TwinRecord:
    """The `TwinRecord` a document holds, or `Rejected` with every problem."""
    problems = validate(doc)
    if problems:
        raise Rejected(problems)
    return documents.decode(TwinRecord, doc)
