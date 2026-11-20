"""The read: Nautobot as it stands under a scope, by the mapping and a reader document, as a blueprint 1 with its
source envelope, or the findings that refused it (D-118).

`read` judges every rule it can in one pass (Constitution III) and answers a `Result` whose blueprint is None exactly
when a finding is an error. It never reads again by itself, and raises nothing for a refusal it judges; a
`NautobotError` passes through. Its order: `observed_at`, the reader's clock, taken before the first request and
pinning nothing; the scope's form, with nothing sent where it is at fault (`scope.invalid`); whether Nautobot names
Golden Config, with nothing more sent where it names none (`golden_config.absent`); **the open** (bracket.mark), its
own lists not whole ending the read with no close; the scope's tag by its name and the devices that carry it
(`scope.empty`, where there is no tag or no device); their platforms and those platforms' manufacturers, each held to
the ids asked; their interfaces, of every type; those interfaces' cables, held to the ids asked; and the dynamic groups
of the settings the open listed, held to the ids asked, and for each group whose filter can be sent, its stored members
and the devices its filter lists, each restricted to the scoped devices (groups.judge: `group.stale`,
`group.unchecked`); the configuration context the reader document names for the probes, where it names one, by its
name (probes.select: `probe.context.absent`, `probe.context.active`): each list held whole (`read.incomplete`), one
that is not ending the read, since the rest would judge a partial list; the mapping (mapping.build); the probes built
from the context, each end's device named as the mapping names it (probes.build); **one render every scoped device**,
in name order then id, a device the mapping refused among them, so that every fault of every device is filed at once
(renders.judge); **the close** (bracket.close); the envelope; and what was built held to blueprint 1, each problem an
error under its own rule.

The close is taken on every path past the open (D-098), so a read refused by `scope.empty` or `read.incomplete`
carries the close's findings beside it, and a 400 after the open is weighed there. Nautobot answers 400 to a list by
an id no object has, interfaces by `device_id` say, so an object deleted between the read's own list and a request by
its id shows so (design/verified-facts.md, "Nautobot 3.2.8 with Golden Config 3.0.8"); and Golden Config answers 400
`Device with id '<id>' not found` to a device deleted under the read.

- **At a list**, a 400 takes the close: where it files `read.moved`, the read is refused by the close's findings; where
  it files `read.incomplete` alone, a close that cannot tell whether a head moved, the read is refused by that, its
  message carrying the 400's own words so that both are seen; and where it files nothing, nothing moved, and the
  transport's error is raised as it came. Any other refusal passes through with no close.
- **At a render**, which answers every status but 401 and 403 for the read to judge, `render.device.unknown`, and
  `render.unavailable` of a 400, are weighed at the close taken after the last render: where the close files
  `read.moved` that is the finding, and the render files nothing of its own; where it does not, the render's finding
  stands. Every other finding of a render is the device's own, and stands beside the close's.

The id addresses the network and the probes alone (D-006), so the envelope travels unhashed: where the read was made
from (`source`, `scope`), by which mapping and against which Nautobot (`mapping`), at which point of the changelog
(`changelog`, the open's newest row by its id and time, None where it held none), of which commit of each template
repository (`templates`, each repository's name to its `current_head` at the open), when (`observed_at`), and its
fidelity rows. Every result carries the connection's version warning, where it has one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fylgja_core import blueprint
from fylgja_core.documents import Problem
from fylgja_core.findings import Finding, order

from fylgja_nautobot import bracket, groups, mapping, probes, renders
from fylgja_nautobot.document import ReaderDocument
from fylgja_nautobot.rows import Context, Device, Setting, Source, incomplete
from fylgja_nautobot.transport import NautobotError, named

# Rule ids. Callers and tests match on them (rules.md).
RULE_SCOPE_INVALID = "scope.invalid"
RULE_SCOPE_EMPTY = "scope.empty"
RULE_GOLDEN_CONFIG_ABSENT = "golden_config.absent"

SOURCE = "nautobot"
"""The envelope's `source`."""

SCOPE = "tag:"
"""What begins every scope, `tag:<name>`: the scope is every `dcim.device` that carries the tag, whatever its
status."""

APP = "nautobot_golden_config"
"""The object a `golden_config.absent` names: the Golden Config app, by its name among Nautobot's apps."""

OBSERVED = "%Y-%m-%dT%H:%M:%S.%fZ"
"""The envelope's `observed_at`: UTC, to the microsecond."""

REFUSED = 400
"""Nautobot's status for a list by an id no object has, and Golden Config's for a render it refuses."""

WEIGHED = (renders.RULE_DEVICE_UNKNOWN, renders.RULE_UNAVAILABLE)
"""The rules of a render's 400 that the close weighs: a device not found, and a 400 in other words."""


@dataclass(frozen=True)
class Result:
    """What a read answers: the blueprint, None exactly when a finding is an error; every finding, in a result's order
    (findings.order); and whether the scope selected no device."""

    blueprint: dict[str, Any] | None
    findings: tuple[Finding, ...]
    empty: bool


@dataclass(frozen=True)
class _Ended:
    """A read ended before the mapping: the findings that ended it, and whether the scope selected no device."""

    findings: tuple[Finding, ...]
    empty: bool


@dataclass(frozen=True)
class _Gathered:
    """What a read built before its close: the mapping, the probes and the fidelity rows of those omitted, each device's
    configuration by its id, the findings, and apart from them those of each render refused 400 that the close
    weighs."""

    mapped: mapping.Mapped
    probes: list[dict[str, Any]]
    omitted: tuple[dict[str, str], ...]
    configs: dict[str, str]
    findings: tuple[Finding, ...]
    weighed: tuple[Finding, ...]


def read(conn: Source, *, scope: str, document: ReaderDocument) -> Result:
    """Nautobot as it stands under `scope`, read by the mapping and `document`."""
    observed_at = datetime.now(UTC).strftime(OBSERVED)
    warned = _warned(conn)
    if not _scoped(scope):
        return _result(None, [_invalid(scope), *warned])
    if conn.golden_config is None:
        return _result(None, [_absent(), *warned])

    opened = bracket.mark(conn)
    if isinstance(opened, Finding):
        return _result(None, [opened, *warned])
    before, settings = opened
    try:
        gathered = _gather(conn, scope, document, settings)
    except NautobotError as e:
        if e.status != REFUSED:
            raise
        closing = bracket.close(conn, before)
        if not closing:
            raise
        return _result(None, [*_after_refusal(closing, e), *warned])
    closing = bracket.close(conn, before)
    if isinstance(gathered, _Ended):
        return _result(None, [*gathered.findings, *closing, *warned], empty=gathered.empty)
    moved = any(finding.rule == bracket.RULE_MOVED for finding in closing)
    weighed = [] if moved else list(gathered.weighed)

    mapped = gathered.mapped
    by_name = {name: device_id for device_id, name in mapped.names.items()}
    network = {
        "devices": [{**device, **_config(gathered.configs.get(by_name[device["name"]]))} for device in mapped.devices],
        "links": [dict(link) for link in mapped.links],
    }
    envelope = {
        "source": SOURCE,
        "scope": scope,
        "mapping": {"reader": mapping.READER, "model": mapping.MODEL, "version": conn.version},
        "changelog": {"id": before.newest.id, "time": before.newest.time} if before.newest is not None else None,
        "templates": {name: head for _, name, head in before.heads},
        "observed_at": observed_at,
        "fidelity": sorted((dict(row) for row in (*mapped.fidelity, *gathered.omitted)), key=_row),
    }
    doc = {"blueprint_version": blueprint.VERSION, "network": network, "probes": gathered.probes, "source": envelope}
    problems = [_problem(problem) for problem in blueprint.validate(doc)]
    return _result(doc, [*gathered.findings, *weighed, *problems, *closing, *warned])


def check(conn: Source) -> tuple[Finding, ...]:
    """The connection's version warning, where it has one, and `golden_config.absent` where Golden Config is not
    installed; nothing is sent."""
    absent = [_absent()] if conn.golden_config is None else []
    return order([*absent, *_warned(conn)])


def _gather(conn: Source, scope: str, document: ReaderDocument, settings: Sequence[Setting]) -> _Ended | _Gathered:
    """Every list of the read, each held whole, the groups of `settings`, the open's, judged among them, then the
    mapping and every scoped device's render, between the open and the close; or the findings that ended it before the
    mapping."""
    name = scope.removeprefix(SCOPE)
    tags = conn.tags(name)
    cut = incomplete(tags)
    if cut is not None:
        return _Ended((cut,), False)
    tag = named(tags, name)
    if tag is None:
        return _Ended((_empty(scope, tagged=False),), True)
    devices = conn.devices(tag)
    cut = incomplete(devices)
    if cut is not None:
        return _Ended((cut,), False)
    if not devices.items:
        return _Ended((_empty(scope, tagged=True),), True)
    asked = sorted({device.platform for device in devices.items if device.platform is not None})
    platforms = conn.platforms(asked)
    cut = incomplete(platforms, asked=asked)
    if cut is not None:
        return _Ended((cut,), False)
    asked = sorted({platform.manufacturer for platform in platforms.items if platform.manufacturer is not None})
    manufacturers = conn.manufacturers(asked)
    cut = incomplete(manufacturers, asked=asked)
    if cut is not None:
        return _Ended((cut,), False)
    ports = conn.ports(sorted(device.id for device in devices.items))
    cut = incomplete(ports)
    if cut is not None:
        return _Ended((cut,), False)
    asked = sorted({port.cable for port in ports.items if port.cable is not None})
    cables = conn.cables(asked)
    cut = incomplete(cables, asked=asked)
    if cut is not None:
        return _Ended((cut,), False)
    grouped = _groups(conn, settings, devices.items)
    if isinstance(grouped, _Ended):
        return grouped

    context = _context(conn, document)
    if isinstance(context, _Ended):
        return context

    mapped = mapping.build(devices.items, platforms.items, manufacturers.items, ports.items, cables.items, document)
    declared: list[dict[str, Any]] = []
    omitted: tuple[dict[str, str], ...] = ()
    probed: tuple[Finding, ...] = ()
    if isinstance(context, Finding):
        probed = (context,)
    elif context is not None:
        scoped = {device.name: mapped.names[device.id] for device in devices.items if device.id in mapped.names}
        declared, omitted, probed = probes.build(context, {name: label for name, label in scoped.items() if name})
    configs, judged, weighed = _renders(conn, devices.items)
    found = (*mapped.findings, *grouped, *probed, *judged)
    return _Gathered(mapped, declared, omitted, configs, found, tuple(weighed))


def _context(conn: Source, document: ReaderDocument) -> _Ended | Context | Finding | None:
    """The configuration context the document names for the probes, asked once by its name and held whole, the one
    row of the name where it is inactive, or the finding that refuses it (probes.select); None where the document names
    none, and nothing is asked; or the `read.incomplete` that ended the read."""
    if document.probes is None:
        return None
    listed = conn.contexts(document.probes)
    cut = incomplete(listed)
    if cut is not None:
        return _Ended((cut,), False)
    return probes.select(listed, document.probes)


def _groups(conn: Source, settings: Sequence[Setting], devices: Sequence[Device]) -> _Ended | list[Finding]:
    """The findings of the dynamic groups of `settings`, each asked once by its id and held to the ids asked, in name
    order then id; for a group whose filter `groups.params` can send, its stored members and the devices its filter
    lists, each restricted to the scoped `devices` and held whole; or the `read.incomplete` that ended the read."""
    asked = sorted({setting.group for setting in settings})
    listed = conn.groups(asked)
    cut = incomplete(listed, asked=asked)
    if cut is not None:
        return _Ended((cut,), False)
    scoped = {device.id: renders.called(device) for device in devices}
    ids = sorted(scoped)
    found = []
    for group in sorted(listed.items, key=lambda group: (group.name, group.id)):
        sent = groups.params(group)
        if sent is None:
            judged = groups.judge(group, (), (), scoped)
        else:
            stored = conn.stored(group.id, ids)
            cut = incomplete(stored)
            if cut is not None:
                return _Ended((cut,), False)
            matching = conn.matching(sent, ids, group.name)
            cut = incomplete(matching)
            if cut is not None:
                return _Ended((cut,), False)
            judged = groups.judge(group, stored.items, [device.id for device in matching.items], scoped)
        if judged is not None:
            found.append(judged)
    return found


def _renders(conn: Source, devices: Sequence[Device]) -> tuple[dict[str, str], list[Finding], list[Finding]]:
    """Each scoped device's configuration by its id, whether or not the mapping refused the device, the findings of
    those that have none, and apart from them those the close weighs: one render a device, in name order then id, a
    device with no name last."""
    configs: dict[str, str] = {}
    found: list[Finding] = []
    weighed: list[Finding] = []
    for device in sorted(devices, key=lambda d: (not d.name, d.name or "", d.id)):
        rendered = conn.render(device.id)
        judged = renders.judge(device, rendered)
        if not isinstance(judged, Finding):
            configs[device.id] = judged
        elif rendered.status == REFUSED and judged.rule in WEIGHED:
            weighed.append(judged)
        else:
            found.append(judged)
    return configs, found, weighed


def _row(row: dict[str, str]) -> tuple[str, str, str, str]:
    """A fidelity row's place: by its four members, in the envelope's order."""
    return (row["disposition"], row["object"], row["source"], row["reason"])


def _scoped(scope: str) -> bool:
    """Whether `scope` is of its one form, `tag:<name>`."""
    return scope.startswith(SCOPE) and bool(scope.removeprefix(SCOPE))


def _invalid(scope: str) -> Finding:
    message = f"The scope {scope!r} is not tag:<name>, so nothing of Nautobot is read."
    return Finding(rule=RULE_SCOPE_INVALID, severity="error", object=scope, message=message)


def _absent() -> Finding:
    message = (
        f"Nautobot names no {APP} among its apps, and a device's configuration is Golden Config's render of it, so "
        "nothing is read: install the Golden Config app."
    )
    return Finding(rule=RULE_GOLDEN_CONFIG_ABSENT, severity="error", object=APP, message=message)


def _empty(scope: str, *, tagged: bool) -> Finding:
    tag = scope.removeprefix(SCOPE)
    said = f"no dcim.device carries the tag {tag}" if tagged else f"Nautobot lists no tag {tag}"
    message = f"In Nautobot {said}, so the scope {scope} selects no device."
    return Finding(rule=RULE_SCOPE_EMPTY, severity="error", object=scope, message=message)


def _after_refusal(closing: Sequence[Finding], refused: NautobotError) -> list[Finding]:
    """The close's findings after Nautobot refused a list of the read 400: as they stand where one is `read.moved`;
    else, a list not whole being all they could say, each with the refusal's own words, which the transport quotes
    cut and with no token, so that the operator sees both."""
    if any(finding.rule == bracket.RULE_MOVED for finding in closing):
        return list(closing)
    said = str(refused).rstrip(".")
    return [
        Finding(
            rule=finding.rule,
            severity=finding.severity,
            object=finding.object,
            message=f"{finding.message.rstrip('.')}, read after Nautobot refused a list of the read: {said}.",
        )
        for finding in closing
    ]


def _config(text: str | None) -> dict[str, str]:
    """A device's `config` member, or none where its render was refused."""
    return {"config": text} if text is not None else {}


def _problem(problem: Problem) -> Finding:
    """A problem of the blueprint built, as an error under the problem's own rule, its pointer the object."""
    message = f"The blueprint read from Nautobot breaks {problem.rule} at {problem.pointer or '/'}: {problem.detail}."
    return Finding(rule=problem.rule, severity="error", object=problem.pointer, message=message)


def _warned(conn: Source) -> list[Finding]:
    return [conn.unverified] if conn.unverified is not None else []


def _result(doc: dict[str, Any] | None, findings: Sequence[Finding], *, empty: bool = False) -> Result:
    ordered = order(findings)
    refused = any(finding.severity == "error" for finding in ordered)
    return Result(None if refused else doc, ordered, empty)
