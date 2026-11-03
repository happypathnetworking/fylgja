"""Probe declaration 1: a file an operator writes to declare probes outside intent
(formats/probes-1.schema.json, D-008).

A producer (the orchestrator) reads a declaration and writes its probes, sorted by name,
into the blueprint it writes; the core itself reads probes inside a blueprint. The loader
lives here, in the shared model package, for that producer. Each element is exactly a
blueprint probe, so `Probe` is `blueprint.Probe`, and the order of a declaration is free.

`validate` holds a declaration to the schema and to the rules its $comment names, and
checks each probe's format against the loaded probe packages' formats, as the compiler
checks a blueprint's (rule probe.format.unknown).
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fylgja_core import blueprint, documents
from fylgja_core.documents import Problem, Rejected

VERSION = "1"

# Rule ids. Clients and tests match on them.
RULE_INVALID = "probes.invalid"
RULE_VERSION = "probes.version.unsupported"
RULE_NAME_DUPLICATE = "probe.name.duplicate"
RULE_GATEWAY_OUTSIDE = "probe.gateway.outside"
RULE_ADDRESS_DUPLICATE = "probe.address.duplicate"
RULE_FORMAT_UNKNOWN = "probe.format.unknown"


@dataclass(frozen=True, kw_only=True)
class Declaration:
    """A probe declaration 1 document as a model: blueprint probes, in the file's order."""

    probes_version: str = VERSION
    probes: tuple[blueprint.Probe, ...]


def validate(doc: Any, formats: Collection[str]) -> list[Problem]:
    """Every problem with `doc` as a declaration, sorted; `formats` are the loaded probe
    packages' formats. An empty list means it is valid."""
    problems = documents.unsupported_version(doc, "probes_version", VERSION, RULE_VERSION)
    if problems:
        return problems
    problems = documents.schema_problems("probes-1", doc, RULE_INVALID)
    if problems:
        return problems
    probes = doc["probes"]
    seen: dict[str, int] = {}
    for i, probe in enumerate(probes):
        if probe["name"] in seen:
            detail = f"{probe['name']!r} is probe {seen[probe['name']]}'s name too"
            problems.append(Problem(f"/probes/{i}/name", RULE_NAME_DUPLICATE, detail))
        seen.setdefault(probe["name"], i)
        if probe["format"] not in formats:
            loaded = ", ".join(sorted(formats)) or "none"
            detail = f"no loaded probe package runs {probe['format']!r}; loaded: {loaded}"
            problems.append(Problem(f"/probes/{i}/format", RULE_FORMAT_UNKNOWN, detail))
    problems += blueprint.probe_problems(probes, "/probes", RULE_GATEWAY_OUTSIDE, RULE_ADDRESS_DUPLICATE)
    return sorted(set(problems))


def decode(doc: Any, formats: Collection[str]) -> Declaration:
    """The `Declaration` a document holds, or `Rejected` with every problem."""
    problems = validate(doc, formats)
    if problems:
        raise Rejected(problems)
    return documents.decode(Declaration, doc)


def load(path: Path, formats: Collection[str]) -> Declaration:
    """The `Declaration` in a file, or `Rejected` naming the file."""
    return documents.load(path, RULE_INVALID, lambda doc: decode(doc, formats))
