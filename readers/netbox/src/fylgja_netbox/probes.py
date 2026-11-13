"""The probes: the probe declaration a configuration context holds, read into blueprint 1's `probes`, where the reader
document names the context (D-095).

A probe is declared beside intent and not in it, and NetBox has no kind for one, so the declaration is the `data` of a
configuration context the installation names in the reader document. The context is inactive, so that no device's
rendered context takes it, and it is still listed by its name (design/verified-facts.md, "NetBox 4.7.5 with
netbox-branching 1.2.3"): NetBox needs no schema of Fylgja's and no further plugin. `select` takes the context from the
whole list NetBox answered for its name: none listed is `probe.context.absent`, and one active is
`probe.context.active`, since every device it applies to would take the probes into its rendered context.

`build` reads the context's `data` as a probe declaration (formats/probes-1.schema.json). A probe an end of which names
no scoped device, by its name in NetBox compared exactly, is omitted, an `info` finding and a fidelity row, since its
host could be placed nowhere; an end that names no device at all is no end of another scope, and is left to the
loader. The rest, each end's device its blueprint name, are held to the declaration's rules by the core's own loader,
each problem an error naming the probe, or the context where the fault is the declaration's own, and a problem refuses
every probe. Data that is no mapping with a list `probes` of mappings, or that states another `probes_version`, is
given to the loader as it is, which refuses it. Whether a probe package runs a format is the compiler's to say, so the
formats the probes name are the formats given, and `probe.format.unknown` is never filed. The probes are sorted by
name, so the same data in any order gives one id. Every finding names the branch read, or `main`.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from fylgja_core import probes as declaration
from fylgja_core.documents import Problem
from fylgja_core.findings import Finding, order

from fylgja_netbox.rows import Context, Listing
from fylgja_netbox.transport import QUOTED, named

# Rule ids. Callers and tests match on them (rules.md).
RULE_CONTEXT_ABSENT = "probe.context.absent"
RULE_CONTEXT_ACTIVE = "probe.context.active"
RULE_OMIT_OUTSIDE = "omit.probe.outside_scope"
# The declaration's rules, which the core's loader files and the reader passes on.
RULE_VERSION = declaration.RULE_VERSION
RULE_INVALID = declaration.RULE_INVALID
RULE_NAME_DUPLICATE = declaration.RULE_NAME_DUPLICATE
RULE_GATEWAY_OUTSIDE = declaration.RULE_GATEWAY_OUTSIDE
RULE_ADDRESS_DUPLICATE = declaration.RULE_ADDRESS_DUPLICATE

SOURCE = "extras.configcontext"
"""The object type a configuration context is, and the `source` of each fidelity row of a probe omitted."""

_AT = re.compile(r"/probes/(\d+)(?:/|$)")


def _where(branch: str | None) -> str:
    return f"branch {branch}" if branch is not None else "main"


def select(listing: Listing[Context], name: str, *, branch: str | None) -> Context | Finding:
    """The configuration context `name` from `listing`, the whole list NetBox answered for that name
    (rows.incomplete), where it is inactive; `probe.context.absent` where `listing` holds none of the name, and
    `probe.context.active` where the one it holds is active. Two rows of the name are a `NetBoxError`
    (transport.named). `branch` is the name of the branch read, None for `main`."""
    held = named(listing, name, branch=branch)
    where = _where(branch)
    if held is None:
        message = (
            f"NetBox lists no configuration context {name} on {where}, which the reader document names for the "
            "probes, so no probe is read: make the context, inactive, or correct the document's probes."
        )
        return Finding(rule=RULE_CONTEXT_ABSENT, severity="error", object=name, message=message)
    if held.active:
        message = (
            f"The configuration context {name} on {where}, which the reader document names for the probes, is "
            "active, so every device it applies to takes the probes into its rendered context: set it inactive."
        )
        return Finding(rule=RULE_CONTEXT_ACTIVE, severity="error", object=name, message=message)
    return held


def build(
    context: Context, devices: Mapping[str, str], *, branch: str | None
) -> tuple[list[dict[str, Any]], tuple[dict[str, str], ...], tuple[Finding, ...]]:
    """The blueprint's probes from `context`'s `data` and `devices`, each scoped device's name in NetBox to its
    blueprint name: the probes sorted by name, a fidelity row for each probe omitted, and the findings, in a result's
    order. A probe an end of which names a device not among `devices`, compared exactly, is omitted,
    `omit.probe.outside_scope`; each problem of the rest as a declaration is an error under its own rule, naming the
    probe, or the context where the fault is the declaration's own, and then none is given, since the read is
    refused. Each probe given is a copy, sharing nothing with `context`. `branch` is the name of the branch read, None
    for `main`."""
    where = _where(branch)
    data = context.data
    if not _declared(data):
        problems = declaration.validate(data, ())
        return [], (), order([_refused(problem, context, [], where) for problem in problems])
    found: list[Finding] = []
    fidelity: list[dict[str, str]] = []
    kept: list[dict[str, Any]] = []
    for probe in data["probes"]:
        name = _called(probe, context)
        outside = [end["device"] for end in _ends(probe) if isinstance(end.get("device"), str)]
        outside = [device for device in outside if device not in devices]
        if outside:
            reason = f"an end on the device {outside[0]}, which is no device of the scope"
            message = (
                f"Probe {name} of the configuration context {context.name} on {where} is omitted from the blueprint: "
                f"{reason}."
            )
            found.append(Finding(rule=RULE_OMIT_OUTSIDE, severity="info", object=name, message=message))
            fidelity.append({"disposition": "omitted", "object": name, "source": SOURCE, "reason": reason})
            continue
        kept.append(_renamed(copy.deepcopy(probe), devices))
    kept.sort(key=_order)
    formats = {probe["format"] for probe in kept if isinstance(probe.get("format"), str)}
    problems = declaration.validate({**data, "probes": kept}, formats)
    named = [_called(probe, context) for probe in kept]
    found += [_refused(problem, context, named, where) for problem in problems]
    rows = sorted(fidelity, key=lambda row: (row["disposition"], row["object"], row["source"], row["reason"]))
    return ([] if problems else kept), tuple(rows), order(found)


def _declared(data: Any) -> bool:
    """Whether `data` is a mapping of no other `probes_version` than the declaration's with a list `probes` of
    mappings, whose probes can be judged one by one."""
    if not isinstance(data, dict) or data.get("probes_version", declaration.VERSION) != declaration.VERSION:
        return False
    held = data.get("probes")
    return isinstance(held, list) and all(isinstance(probe, dict) for probe in held)


def _ends(probe: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The probe's endpoints that are mappings; none where its `endpoints` is no list."""
    held = probe.get("endpoints")
    return [end for end in held if isinstance(end, dict)] if isinstance(held, list) else []


def _renamed(probe: Mapping[str, Any], devices: Mapping[str, str]) -> dict[str, Any]:
    """The probe, each end that names a device of `devices` naming its blueprint name, all else as it was."""
    held = probe.get("endpoints")
    if not isinstance(held, list):
        return dict(probe)
    ends = [
        {**end, "device": devices[end["device"]]}
        if isinstance(end, dict) and isinstance(end.get("device"), str) and end["device"] in devices
        else end
        for end in held
    ]
    return {**probe, "endpoints": ends}


def _order(probe: Mapping[str, Any]) -> tuple[str, str]:
    """A probe's place: by its name, then, for probes of one name, by the whole probe, so that any order of the data
    gives one order."""
    name = probe.get("name")
    return (name if isinstance(name, str) else "", json.dumps(probe, sort_keys=True))


def _called(probe: Mapping[str, Any], context: Context) -> str:
    """A probe as findings name it: its name, or the context's where it has none that is a string."""
    name = probe.get("name")
    return name if isinstance(name, str) and name else context.name


def _refused(problem: Problem, context: Context, named: Sequence[str], where: str) -> Finding:
    """A problem of the declaration as an error under its own rule, its object the probe it is at, by `named`, each
    probe's name in the declaration's order; the context's where the problem is the declaration's own. The loader's
    words are quoted as the transport quotes NetBox's, their runs of whitespace made one space and cut at `QUOTED`
    characters, since they quote the value at fault, of any length."""
    at = _AT.match(problem.pointer)
    pointer = problem.pointer or "/"
    if at is not None and int(at[1]) < len(named):
        name = named[int(at[1])]
        said = f"Probe {name} of the configuration context {context.name} on {where}"
    else:
        name = context.name
        said = f"The configuration context {context.name} on {where}"
    detail = " ".join(problem.detail.split())[:QUOTED]
    message = f"{said} breaks {problem.rule} at {pointer}: {detail}."
    return Finding(rule=problem.rule, severity="error", object=name, message=message)
