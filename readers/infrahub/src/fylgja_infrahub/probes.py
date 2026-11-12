"""The probes: each `FylgjaProbe` read into blueprint 1's `probes`, where the reader document asks for them (D-082).

A probe is declared beside intent and not in it, so its kind ships with the reader, `readers/infrahub/schema/
fylgja-probe.yml`, and is the one schema of Fylgja's a read may need: `absent` holds the branch's schema to it, from the
schema the read has already read, and a read that asks for probes of a branch without it is refused. A probe names its
devices by their names in Infrahub. One an end of which names no scoped device is omitted, an `info` finding and a
fidelity row, since its host could be placed nowhere; the rest are a probe declaration (formats/probes-1.schema.json),
each end's device its blueprint name, held to the declaration's rules by the core's own loader, each problem an error
naming the probe. Whether a probe package runs a format is the compiler's to say, so the formats the probes name are
the formats given. The list is sorted by name, so the same rows in any order give one id.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from fylgja_core import probes as declaration
from fylgja_core.documents import Problem
from fylgja_core.findings import Finding, order

from fylgja_infrahub.rows import Listing, Probe, Schema

# Rule ids. Callers and tests match on them (rules.md).
RULE_KIND_ABSENT = "probe.kind.absent"
RULE_OMIT_OUTSIDE = "omit.probe.outside_scope"
# The declaration's rules, which the core's loader files and the reader passes on, each naming the probe.
RULE_INVALID = declaration.RULE_INVALID
RULE_NAME_DUPLICATE = declaration.RULE_NAME_DUPLICATE
RULE_GATEWAY_OUTSIDE = declaration.RULE_GATEWAY_OUTSIDE
RULE_ADDRESS_DUPLICATE = declaration.RULE_ADDRESS_DUPLICATE

KIND = "FylgjaProbe"
"""The kind a probe is, and the `source` of each fidelity row of a probe omitted."""

FILE = "readers/infrahub/schema/fylgja-probe.yml"
"""The kind's schema, which a branch without it is given."""

FIELDS = (
    "name",
    "format",
    "a_device",
    "a_interface",
    "a_address",
    "a_gateway",
    "b_device",
    "b_interface",
    "b_address",
    "b_gateway",
)
"""The kind's ten attributes, each read: the probe's name and format, and each end's device, port, address and
gateway, a then b."""

ENDPOINT = ("device", "interface", "address", "gateway")
"""A probe endpoint's members in blueprint 1, in the order a row's end holds them."""

_AT = re.compile(r"/probes/(\d+)(?:/|$)")


def absent(schema: Schema, *, branch: str) -> Finding | None:
    """`probe.kind.absent` where the branch's schema lacks `KIND` or one of its `FIELDS`, naming each attribute missing
    and the file to load; None where it holds them all."""
    held = schema.nodes.get(KIND)
    if held is None:
        said = f"has no kind {KIND}"
    else:
        missing = [field for field in FIELDS if field not in held.attributes]
        if not missing:
            return None
        noun = "attribute" if len(missing) == 1 else "attributes"
        said = f"gives {KIND} no {noun} {', '.join(missing)}"
    message = (
        f"Branch {branch}'s present schema {said}, which the reader reads where the reader document asks for probes, "
        f"so none is read: load {FILE} on it."
    )
    return Finding(rule=RULE_KIND_ABSENT, severity="error", object=KIND, message=message)


def build(
    listing: Listing[Probe], devices: Mapping[str, str], *, branch: str, at: str
) -> tuple[list[dict[str, Any]], tuple[dict[str, str], ...], tuple[Finding, ...]]:
    """The blueprint's probes from `listing`, a whole list (rows.incomplete), and `devices`, each scoped device's name
    in Infrahub to its blueprint name: the probes sorted by name, a fidelity row for each probe omitted, and the
    findings, in a result's order. A probe an end of which names no device of `devices` is omitted,
    `omit.probe.outside_scope`; each problem of the rest as a declaration is an error under its own rule naming the
    probe, and then none is given, since the read is refused. A value Infrahub answered null stays null, which the
    declaration refuses (`probes.invalid`), and an end on no device is no end of another scope; a probe whose name is
    null is named by its id."""
    when = f"on branch {branch} at {at}"
    found: list[Finding] = []
    fidelity: list[dict[str, str]] = []
    kept: list[dict[str, Any]] = []
    named: list[str] = []
    for row in sorted(listing.items, key=lambda p: (p.name or "", p.id)):
        name = row.name if row.name is not None else row.id
        outside = [device for device, *_ in (row.a, row.b) if device is not None and device not in devices]
        if outside:
            reason = f"an end on the device {outside[0]}, which is no device of the scope"
            message = f"Probe {name} {when} is omitted from the blueprint: {reason}."
            found.append(Finding(rule=RULE_OMIT_OUTSIDE, severity="info", object=name, message=message))
            fidelity.append({"disposition": "omitted", "object": name, "source": KIND, "reason": reason})
            continue
        endpoints = [
            {**dict(zip(ENDPOINT, end, strict=True)), "device": devices[end[0]] if end[0] is not None else None}
            for end in (row.a, row.b)
        ]
        kept.append({"name": row.name, "format": row.format, "endpoints": endpoints})
        named.append(name)
    formats = {held["format"] for held in kept if isinstance(held["format"], str)}
    problems = declaration.validate({"probes_version": declaration.VERSION, "probes": kept}, formats)
    found += [_refused(problem, named=named, when=when) for problem in problems]
    return ([] if problems else kept), tuple(fidelity), order(found)


def _refused(problem: Problem, *, named: Sequence[str], when: str) -> Finding:
    """A problem of the declaration as an error under its own rule, its object the probe it is at, by `named`, each
    probe's name or else its id, in the declaration's order."""
    at = _AT.match(problem.pointer)
    name = named[int(at[1])] if at is not None else KIND
    message = f"Probe {name} read from {KIND} {when} breaks {problem.rule} at {problem.pointer}: {problem.detail}."
    return Finding(rule=problem.rule, severity="error", object=name, message=message)
