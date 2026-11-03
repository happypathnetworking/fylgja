"""Platform package 1: what the core must know of one network operating system that the
runtime's kind does not already know (formats/platform-package-1.schema.json, D-013, D-015).

A package is YAML under psp/. `validate` holds it to the schema and to the cross-field rules
the schema's $comment names, all in one pass (Constitution III, and what
POST /v1/packages:validate reports); `decode` builds the `PlatformPackage` model.

A naming template (a rule's `match` and `node_name`, a rename's `port`) is literal text with
`{name}` placeholders; `placeholders` lists them. Matching production names against a rule
is the compiler's, not the loader's.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from fylgja_core import documents
from fylgja_core.documents import Problem, Rejected

VERSION = "1"

# Rule ids, as the schema's $comment names them. Clients and tests match on them.
RULE_INVALID = "package.invalid"
RULE_VERSION = "package.version.unsupported"
RULE_RULE_NAME = "package.rule.name"
RULE_MANAGEMENT_RULE = "package.management.rule"
RULE_PLACEHOLDERS = "package.patterns.placeholders"
RULE_RANGES = "package.ranges.placeholder"
RULE_RENAME_COVERAGE = "package.rename.coverage"

_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


@dataclass(frozen=True, kw_only=True)
class Rule:
    """One interface rule: a data rule with a `match`, or the management rule."""

    name: str
    match: str | None = None
    ranges: Mapping[str, tuple[int, int]] | None = None
    node_name: str | None = None
    management: Literal[True] | None = None


@dataclass(frozen=True, kw_only=True)
class Interfaces:
    """The ordered rules; the first whose match fits a production name decides it."""

    rules: tuple[Rule, ...]


@dataclass(frozen=True, kw_only=True)
class Push:
    """How the configuration reaches a booted node: always a replace with an explicit commit."""

    delivery: Literal["json_rpc", "eapi"]
    port: int
    timeout_s: int


@dataclass(frozen=True, kw_only=True)
class Readiness:
    """A node is ready when its push transport answers, within this bound."""

    timeout_s: int


@dataclass(frozen=True, kw_only=True)
class Gnmi:
    """How a node's state is read; the encoding is always json_ietf."""

    port: int
    tls: bool


@dataclass(frozen=True, kw_only=True)
class ValueAt:
    """A leaf and the value verify asserts there; `absent` is what an unreported leaf means."""

    path: str
    value: str
    absent: str | None = None


@dataclass(frozen=True, kw_only=True)
class Neighbor:
    """Where verify reads a port's LLDP neighbour."""

    path: str
    system_name: str
    port_id: str


@dataclass(frozen=True, kw_only=True)
class Port:
    """Per-port reads; {node_name} renders the port's node name."""

    enabled: ValueAt
    discovering: ValueAt
    neighbor: Neighbor


@dataclass(frozen=True, kw_only=True)
class Conformance:
    """The gNMI paths verify and the conformance suite read on a booted node."""

    host_name: str
    version: str
    port: Port


@dataclass(frozen=True, kw_only=True)
class Fidelity:
    """What the package asserts about its own fidelity."""

    approximations: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class Image:
    """An image and how it is acquired; `pull_secret` is set for a gated image."""

    ref: str
    pull_secret: str | None = None


@dataclass(frozen=True, kw_only=True)
class Resources:
    """What one node needs: a pod request on clabernetes, an admission budget locally."""

    cpu: float
    memory_mb: int


@dataclass(frozen=True, kw_only=True)
class Rename:
    """For a kind with no aliases, the endpoint template for one data rule."""

    rule: str
    port: str


@dataclass(frozen=True, kw_only=True)
class Containerlab:
    """The section both containerlab drivers read."""

    kind: str
    image: Image
    resources: Resources
    deploy_timeout_s: int
    destroy_timeout_s: int
    link_apply_mode: Literal["live", "restart"]
    alias: bool
    rename: tuple[Rename, ...] | None = None
    hot_add_ports: bool


@dataclass(frozen=True, kw_only=True)
class Runtime:
    """Per-runtime sections; only containerlab exists now."""

    containerlab: Containerlab


@dataclass(frozen=True, kw_only=True)
class PlatformPackage:
    """A platform package 1 document as a model."""

    platform_package_version: str = VERSION
    id: str
    versions: tuple[str, ...]
    credentials: str
    interfaces: Interfaces
    push: Push
    readiness: Readiness
    gnmi: Gnmi
    conformance: Conformance
    fidelity: Fidelity
    runtime: Runtime


def placeholders(pattern: str) -> list[str]:
    """The `{name}` placeholders of a naming template, in order, repeats included."""
    return _PLACEHOLDER.findall(pattern)


def validate(doc: Any) -> list[Problem]:
    """Every problem with `doc` as a platform package, sorted; an empty list means it is valid."""
    problems = documents.unsupported_version(doc, "platform_package_version", VERSION, RULE_VERSION)
    if problems:
        return problems
    problems = documents.schema_problems("platform-package-1", doc, RULE_INVALID)
    if problems:
        return problems
    rules = doc["interfaces"]["rules"]
    problems += _names(rules)
    problems += _management(rules)
    problems += _placeholders(rules)
    problems += _rename(rules, doc["runtime"]["containerlab"])
    return sorted(set(problems))


def decode(doc: Any) -> PlatformPackage:
    """The `PlatformPackage` a document holds, or `Rejected` with every problem."""
    problems = validate(doc)
    if problems:
        raise Rejected(problems)
    return documents.decode(PlatformPackage, doc)


def load(path: Path) -> PlatformPackage:
    """The `PlatformPackage` in a YAML file, or `Rejected` naming the file."""
    return documents.load(path, RULE_INVALID, decode)


def _names(rules: list[dict[str, Any]]) -> list[Problem]:
    found: list[Problem] = []
    seen: dict[str, int] = {}
    for i, rule in enumerate(rules):
        if rule["name"] in seen:
            detail = f"{rule['name']!r} is rule {seen[rule['name']]}'s name too"
            found.append(Problem(f"/interfaces/rules/{i}/name", RULE_RULE_NAME, detail))
        seen.setdefault(rule["name"], i)
    return found


def _management(rules: list[dict[str, Any]]) -> list[Problem]:
    management = [i for i, rule in enumerate(rules) if rule.get("management")]
    if not management:
        return [Problem("/interfaces/rules", RULE_MANAGEMENT_RULE, "no rule is the management rule")]
    return [
        Problem(f"/interfaces/rules/{i}", RULE_MANAGEMENT_RULE, f"a second management rule; rule {management[0]} is it")
        for i in management[1:]
    ]


def _placeholders(rules: list[dict[str, Any]]) -> list[Problem]:
    found = []
    for i, rule in enumerate(rules):
        pointer = f"/interfaces/rules/{i}"
        captured = placeholders(rule.get("match", ""))
        for name in sorted({n for n in captured if captured.count(n) > 1}):
            found.append(Problem(f"{pointer}/match", RULE_PLACEHOLDERS, f"{{{name}}} is captured twice"))
        for name in placeholders(rule.get("node_name", "")):
            if name not in captured:
                found.append(Problem(f"{pointer}/node_name", RULE_PLACEHOLDERS, _not_captured(name, rule)))
        for name in rule.get("ranges", {}):
            if name not in captured:
                found.append(Problem(f"{pointer}/ranges/{name}", RULE_RANGES, _not_captured(name, rule)))
    return found


def _not_captured(name: str, rule: dict[str, Any]) -> str:
    if "match" not in rule:
        return f"{{{name}}} in the management rule, whose node_name is a literal"
    return f"{{{name}}} is not captured by the match {rule['match']!r}"


def _rename(rules: list[dict[str, Any]], containerlab: dict[str, Any]) -> list[Problem]:
    data: dict[str, list[str]] = {}
    for rule in rules:
        if "match" in rule:
            data.setdefault(rule["name"], placeholders(rule["match"]))
    found, renamed = [], set()
    for j, entry in enumerate(containerlab.get("rename", [])):
        pointer = f"/runtime/containerlab/rename/{j}"
        if entry["rule"] not in data:
            found.append(Problem(f"{pointer}/rule", RULE_RENAME_COVERAGE, f"{entry['rule']!r} is no data rule"))
            continue
        if entry["rule"] in renamed:
            found.append(Problem(f"{pointer}/rule", RULE_RENAME_COVERAGE, f"{entry['rule']!r} is renamed twice"))
        renamed.add(entry["rule"])
        for name in placeholders(entry["port"]):
            if name not in data[entry["rule"]]:
                detail = f"{{{name}}} is not captured by rule {entry['rule']!r}'s match"
                found.append(Problem(f"{pointer}/port", RULE_PLACEHOLDERS, detail))
    if not containerlab["alias"]:
        for name in data:
            if name not in renamed:
                detail = f"data rule {name!r} has no rename, and the kind has no aliases"
                found.append(Problem("/runtime/containerlab/rename", RULE_RENAME_COVERAGE, detail))
    return found
