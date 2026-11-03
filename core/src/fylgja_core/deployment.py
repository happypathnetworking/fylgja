"""Deployment 1: a driver plan's output, the pure binding of one bundle to one twin on one
runtime (formats/deployment-1.schema.json, D-011, D-017).

`Deployment` is the document's model. `Fidelity` is this twin's on this runtime, and
`CompileFidelity` the runtime-independent part a compile answers (POST /v1/bundles);
both are asserted, never measured (Constitution X).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from fylgja_core import documents
from fylgja_core.documents import Problem, Rejected

VERSION = "1"

# Rule ids. Clients and tests match on them.
RULE_INVALID = "deployment.invalid"
RULE_VERSION = "deployment.version.unsupported"


@dataclass(frozen=True, kw_only=True)
class File:
    """A rendered runtime artifact under the deployment's directory, by path and SHA-256."""

    path: str
    sha256: str


@dataclass(frozen=True, kw_only=True)
class Demand:
    """What the deployment needs; admission compares it with the driver's free capacity."""

    nodes: int
    cpu: float
    memory_mb: int


@dataclass(frozen=True, kw_only=True)
class Approximation:
    """One package's sentence on how the twin differs from production."""

    package: str
    text: str


@dataclass(frozen=True, kw_only=True)
class Omitted:
    """An interface the twin does not represent, and why."""

    device: str
    interface: str
    omission: Literal["out_of_range", "no_rule", "shared"]


@dataclass(frozen=True, kw_only=True)
class Lossy:
    """Counts of the rename's many-to-one mappings."""

    mappings: int
    shared_ports: int


@dataclass(frozen=True, kw_only=True)
class CompileFidelity:
    """The runtime-independent part of fidelity, answered by a compile."""

    approximations: tuple[Approximation, ...]
    omitted: tuple[Omitted, ...]
    synthesized: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class Fidelity:
    """Fidelity for this twin on this runtime."""

    forwarding: Literal["software", "hardware"]
    approximations: tuple[Approximation, ...]
    omitted: tuple[Omitted, ...]
    synthesized: tuple[str, ...]
    lossy: Lossy


@dataclass(frozen=True, kw_only=True)
class Deployment:
    """A deployment 1 document as a model. `allocation` is shaped by the driver that
    reserved it, and carried as it is."""

    deployment_version: str = VERSION
    id: str
    driver: str
    twin: str
    allocation: Mapping[str, Any]
    bundle_id: str
    files: tuple[File, ...]
    demand: Demand
    fidelity: Fidelity


def validate(doc: Any) -> list[Problem]:
    """Every problem with `doc` as a deployment, sorted; an empty list means it is valid."""
    problems = documents.unsupported_version(doc, "deployment_version", VERSION, RULE_VERSION)
    if problems:
        return problems
    return documents.schema_problems("deployment-1", doc, RULE_INVALID)


def decode(doc: Any) -> Deployment:
    """The `Deployment` a document holds, or `Rejected` with every problem."""
    problems = validate(doc)
    if problems:
        raise Rejected(problems)
    return documents.decode(Deployment, doc)
