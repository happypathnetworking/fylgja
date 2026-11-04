"""Probe package 1: how one probe format's hosts are run (formats/probe-package-1.schema.json,
D-008, D-014).

A package is YAML under probes/. `validate` holds it to the schema and to two rules of the
loader's: its `format` names a mechanism this build runs, since a value this build has no
mechanism for is refused at load, naming the values there are (D-014); and every command,
and the readiness text, uses only the placeholders the drivers' plan, readiness, flows and
verify render, a host's two start-up commands only the four the plan renders into them.
`decode` builds the `ProbePackage` model.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fylgja_core import documents, platform_package
from fylgja_core.documents import Problem, Rejected
from fylgja_core.platform_package import Image, placeholders

VERSION = "1"

# The probe formats this build has a mechanism for: how a flow's and a burst's output is
# read. A package of another format is code to add before it is data (probes/README.md).
MECHANISMS = frozenset({"ping"})

# What a command or the readiness text may name; each is rendered where the schema says.
PLACEHOLDERS = frozenset({"interface", "address", "far_address", "gateway", "interval", "count", "wait"})

# What a host's start-up commands (host.address, host.route) may name: the four the plan renders.
HOST_PLACEHOLDERS = frozenset({"interface", "address", "far_address", "gateway"})

# Rule ids. Those a platform package shares are its: both are packages.
RULE_INVALID = platform_package.RULE_INVALID
RULE_VERSION = platform_package.RULE_VERSION
RULE_PLACEHOLDERS = platform_package.RULE_PLACEHOLDERS
RULE_FORMAT = "package.format.unsupported"


@dataclass(frozen=True, kw_only=True)
class Host:
    """How a host is set up when its container starts: its data port, and two commands."""

    interface: str
    address: tuple[str, ...]
    route: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class Readiness:
    """A host is ready once `command`'s output holds `expect`, within the bound."""

    command: tuple[str, ...]
    expect: str
    timeout_s: int


@dataclass(frozen=True, kw_only=True)
class Flow:
    """The continuous flow a step measures loss with."""

    interval_s: float
    command: tuple[str, ...]
    start_timeout_s: int
    read_timeout_s: int


@dataclass(frozen=True, kw_only=True)
class Burst:
    """Verify's burst: `count` packets, held when every one is answered."""

    count: int
    wait_s: int
    command: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class Fidelity:
    """What the package asserts of its own fidelity."""

    approximations: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class Resources:
    """What one host needs: a pod request on clabernetes, an admission budget locally."""

    cpu: float
    memory_mb: int


@dataclass(frozen=True, kw_only=True)
class Containerlab:
    """The section both containerlab drivers read; the host's kind is always linux."""

    image: Image
    resources: Resources
    deploy_timeout_s: int
    destroy_timeout_s: int


@dataclass(frozen=True, kw_only=True)
class Runtime:
    """Per-runtime sections; only containerlab exists now."""

    containerlab: Containerlab


@dataclass(frozen=True, kw_only=True)
class ProbePackage:
    """A probe package 1 document as a model."""

    probe_package_version: str = VERSION
    format: str
    host: Host
    readiness: Readiness
    flow: Flow
    burst: Burst
    fidelity: Fidelity
    runtime: Runtime


def validate(doc: Any) -> list[Problem]:
    """Every problem with `doc` as a probe package, sorted; an empty list means it is valid."""
    problems = documents.unsupported_version(doc, "probe_package_version", VERSION, RULE_VERSION)
    if problems:
        return problems
    problems = documents.schema_problems("probe-package-1", doc, RULE_INVALID)
    if problems:
        return problems
    if doc["format"] not in MECHANISMS:
        detail = f"no mechanism runs {doc['format']!r}; this build runs {', '.join(sorted(MECHANISMS))}"
        problems.append(Problem("/format", RULE_FORMAT, detail))
    for pointer, words in (("/host/address", doc["host"]["address"]), ("/host/route", doc["host"]["route"])):
        for i, word in enumerate(words):
            problems += _placeholders(f"{pointer}/{i}", word, host=True)
    for pointer, words in (
        ("/readiness/command", doc["readiness"]["command"]),
        ("/flow/command", doc["flow"]["command"]),
        ("/burst/command", doc["burst"]["command"]),
    ):
        for i, word in enumerate(words):
            problems += _placeholders(f"{pointer}/{i}", word)
    problems += _placeholders("/readiness/expect", doc["readiness"]["expect"])
    return sorted(set(problems))


def decode(doc: Any) -> ProbePackage:
    """The `ProbePackage` a document holds, or `Rejected` with every problem."""
    problems = validate(doc)
    if problems:
        raise Rejected(problems)
    return documents.decode(ProbePackage, doc)


def load(path: Path) -> ProbePackage:
    """The `ProbePackage` in a YAML file, or `Rejected` naming the file."""
    return documents.load(path, RULE_INVALID, decode)


def _placeholders(pointer: str, text: str, host: bool = False) -> list[Problem]:
    allowed = HOST_PLACEHOLDERS if host else PLACEHOLDERS
    known = ", ".join("{" + name + "}" for name in sorted(allowed))
    if host:
        why = f"no placeholder a host command may name; it may name {known}"
    else:
        why = f"no placeholder; there are {known}"
    return [
        Problem(pointer, RULE_PLACEHOLDERS, f"{{{name}}} is {why}")
        for name in placeholders(text)
        if name not in allowed
    ]
