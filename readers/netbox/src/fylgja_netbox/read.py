"""The read: a branch of NetBox, or `main`, as it stands, under a scope, by the mapping and a reader document, into a
blueprint 1 with its source envelope, or the findings that refused it (D-095).

`read` judges every rule it can in one pass (Constitution III) and answers a `Result` whose blueprint is None exactly
when a finding is an error. It never reads again by itself, and raises nothing for a refusal it judges; a
`NetBoxError` passes through. Its order: `observed_at`, the reader's clock, taken before the first request and pinning
nothing; the scope's form, with nothing sent where it is at fault (`scope.invalid`); for a branch, whether NetBox
names the branching plugin, with nothing sent where it names none (`branch.unsupported`), then the branch by its
name, which must be listed and `ready` (`branch.unknown`, `branch.unready`), either ending the read before the
bracket opens; **the open** (bracket.mark); the scope's tag and the devices that carry it (`scope.empty`, where there
is no tag or no device); their platforms, held to the ids asked; their interfaces, of every type; and those
interfaces' cables, held to the ids asked; and where the reader document names one, the configuration context of the
probes by its name: each list held whole (`read.incomplete`), one that is not ending the read, since the rest would
judge a partial list; the mapping (mapping.build); the probes from that context (probes.select, probes.build), over
each scoped device's name in NetBox to its blueprint name; **one render every scoped device**, in name
order then id, a device the mapping refused among them, so that every fault of every device is filed at once
(renders.judge); **the close** (bracket.close); the envelope; and what was built held to blueprint 1, each problem an
error under its own rule. The close is taken on every path past the open, so a read refused by `scope.empty` or
`read.incomplete` carries the close's findings beside it.

A 400 past the branch's read is answered by the bracket. NetBox answers 400 to a list by an id it does not hold, so
an object deleted between the read's own list and a request by its id shows so; to a list under the header of a
branch it no longer holds or that is syncing or merged; and to a render under the header of a branch deleted
(design/verified-facts.md, "NetBox 4.7.5 with netbox-branching 1.2.3", and "A render under the header of a branch that
is gone").

- **At the open**, for a branch, the branch is read again (bracket.reread): gone, no longer `ready` or synced, the
  read is refused by `read.moved`; its list not whole, by `read.incomplete`, carrying the 400's words; as it was, the
  transport's error is raised as it came. A 400 at `main`'s open is raised as it came, there being no branch to read
  again.
- **At a list**, the read takes the close: where it files `read.moved`, the read is refused by it, with
  `read.incomplete` beside it where the close files that too; where it files `read.incomplete` alone, the changelog
  not listed whole, so that whether it moved cannot be told, the read is refused by that, its message carrying the
  400's own words so that both are seen; and where it files nothing, the changelog did not move, and the transport's
  error is raised as it was.
- **At a render**, which answers every status but 401 and 403 for the read to judge, a 400 in NetBox's no-template
  words is `render.template.missing`, the device's own; any other 400 is `render.unavailable`, quoting NetBox's
  words, and is weighed at the close taken after the last render: where the close files `read.moved` that is the
  finding, and the render files nothing of its own, and where it does not, the `render.unavailable` stands. A device
  deleted under the read is `render.unavailable` 404 beside the close's `read.moved`.
- **At the close**, a 400 to its own requests under a branch's header is `read.moved` (bracket.close); on `main` it is
  raised as it came.

A branch's name is never empty, nor whitespace alone: `read` and `check` refuse such a one, a `ValueError`, before any
request, since it names no branch and `main` is None.

The id addresses the network and the probes alone (D-006), so the envelope travels unhashed: where the read was made
from (`source`, `branch`, `scope`), by which mapping and against which NetBox (`mapping`), at which point of the
changelog read from (`changelog`, the id the close took), when (`observed_at`), and its fidelity rows. Every result
carries the connection's version warning, where it has one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fylgja_core import blueprint
from fylgja_core.documents import Problem
from fylgja_core.findings import Finding, order

from fylgja_netbox import bracket, mapping, probes, renders
from fylgja_netbox.document import ReaderDocument
from fylgja_netbox.rows import Branch, Context, Device, Listing, Source, incomplete
from fylgja_netbox.transport import NetBoxError, named

# Rule ids. Callers and tests match on them (rules.md).
RULE_SCOPE_INVALID = "scope.invalid"
RULE_SCOPE_EMPTY = "scope.empty"
RULE_BRANCH_UNSUPPORTED = "branch.unsupported"
RULE_BRANCH_UNKNOWN = "branch.unknown"
RULE_BRANCH_UNREADY = "branch.unready"

SOURCE = "netbox"
"""The envelope's `source`."""

SCOPE = "tag:"
"""What begins every scope, `tag:<name>`: the scope is every `dcim.device` that carries the tag, whatever its
status."""

READY = "ready"
"""The one status of a branch that is read."""

OBSERVED = "%Y-%m-%dT%H:%M:%S.%fZ"
"""The envelope's `observed_at`: UTC, to the microsecond."""

REFUSED = 400
"""NetBox's status for a request by an id it does not hold, and for one under the header of a branch it no longer
holds."""


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
    """What a read built before its close: the mapping, each device's configuration by its id, the probes and the
    fidelity rows of those omitted, the findings, and apart from them the `render.unavailable` of each render NetBox
    refused 400 in other words than its no-template answer's, which the close weighs."""

    mapped: mapping.Mapped
    configs: dict[int, str]
    probes: tuple[dict[str, Any], ...]
    omitted: tuple[dict[str, str], ...]
    findings: tuple[Finding, ...]
    refused: tuple[Finding, ...]


def read(conn: Source, *, branch: str | None, scope: str, document: ReaderDocument) -> Result:
    """The branch named `branch`, or `main` where it is None, read as it stands under `scope`, by the mapping and
    `document`, as a blueprint 1 with its source envelope, or the findings that refused it. An empty `branch`, or one
    of whitespace alone, is a `ValueError`, raised before any request."""
    _named(branch)
    observed_at = datetime.now(UTC).strftime(OBSERVED)
    warned = _warned(conn)
    if not _scoped(scope):
        return _result(None, [_invalid(scope, branch), *warned])
    opened: Branch | None = None
    if branch is not None:
        found = _branch(conn, branch)
        if isinstance(found, Finding):
            return _result(None, [found, *warned])
        opened = found

    try:
        before = bracket.mark(conn, opened)
    except NetBoxError as e:
        if e.status != REFUSED or opened is None:
            raise
        left = bracket.reread(conn, opened)
        if left is None:
            raise
        return _result(None, [*_after_refusal((left,), e), *warned])
    try:
        gathered = _gather(conn, opened, scope, document, branch=branch)
    except NetBoxError as e:
        if e.status != REFUSED:
            raise
        closing = bracket.close(conn, opened, before)[1]
        if not closing:
            raise
        return _result(None, [*_after_refusal(closing, e), *warned])
    after, closing = bracket.close(conn, opened, before)
    if isinstance(gathered, _Ended):
        return _result(None, [*gathered.findings, *closing, *warned], empty=gathered.empty)
    moved = any(finding.rule == bracket.RULE_MOVED for finding in closing)
    weighed = [] if moved else list(gathered.refused)

    mapped = gathered.mapped
    by_name = {name: device_id for device_id, name in mapped.names.items()}
    network = {
        "devices": [{**device, **_config(gathered.configs.get(by_name[device["name"]]))} for device in mapped.devices],
        "links": [dict(link) for link in mapped.links],
    }
    envelope = {
        "source": SOURCE,
        "branch": branch,
        "scope": scope,
        "mapping": {"reader": mapping.READER, "model": mapping.MODEL, "version": conn.version},
        "changelog": after,
        "observed_at": observed_at,
        "fidelity": sorted((dict(row) for row in (*mapped.fidelity, *gathered.omitted)), key=_row),
    }
    held = [dict(probe) for probe in gathered.probes]
    doc = {"blueprint_version": blueprint.VERSION, "network": network, "probes": held, "source": envelope}
    problems = [_problem(problem, branch) for problem in blueprint.validate(doc)]
    return _result(doc, [*gathered.findings, *weighed, *problems, *closing, *warned])


def check(conn: Source, *, branch: str | None) -> tuple[Finding, ...]:
    """The connection's version warning, where it has one, and for a branch, whether NetBox names the plugin and the
    branch is there and `ready`: the one `branch.*` finding that applies, or `read.incomplete` where NetBox's list of
    the branches of that name is not whole; for `main` nothing is sent. An empty `branch`, or one of whitespace alone,
    is a `ValueError`, raised before any request."""
    _named(branch)
    warned = _warned(conn)
    if branch is None:
        return order(warned)
    found = _branch(conn, branch)
    return order([found, *warned] if isinstance(found, Finding) else warned)


def _branch(conn: Source, name: str) -> Branch | Finding:
    """The branch `name` as NetBox lists it, `ready`; or `branch.unsupported` where NetBox names no branching plugin,
    with nothing sent, `read.incomplete` where the list is not whole, `branch.unknown` where it lists none of the name,
    and `branch.unready` where its status is another. Two rows of the name are a `NetBoxError` (transport.named),
    which passes through."""
    if conn.branching is None:
        message = (
            f"NetBox names no netbox_branching among its plugins, so it holds no branch {name} to read: read main, or "
            "install the plugin."
        )
        return Finding(rule=RULE_BRANCH_UNSUPPORTED, severity="error", object=name, message=message)
    listed = conn.branches(name)
    cut = incomplete(listed, branch=name)
    if cut is not None:
        return cut
    held = named(listed, name, branch=name)
    if held is None:
        message = f"NetBox lists no branch {name}, so branch {name} is not read: check the branch's name."
        return Finding(rule=RULE_BRANCH_UNKNOWN, severity="error", object=name, message=message)
    if held.status != READY:
        status = held.status
        message = f"The status of branch {name} is {status}, not {READY}, so it is not read: read it once it is."
        return Finding(rule=RULE_BRANCH_UNREADY, severity="error", object=name, message=message)
    return held


def _gather(
    conn: Source, opened: Branch | None, scope: str, document: ReaderDocument, *, branch: str | None
) -> _Ended | _Gathered:
    """Every list of the read, each held whole, then the mapping and every scoped device's render, between the open and
    the close; or the findings that ended it before the mapping."""
    tags = conn.tags(opened, scope.removeprefix(SCOPE))
    cut = incomplete(tags, branch=branch)
    if cut is not None:
        return _Ended((cut,), False)
    tag = named(tags, scope.removeprefix(SCOPE), branch=branch)
    if tag is None:
        return _Ended((_empty(scope, branch, tagged=False),), True)
    devices = conn.devices(opened, tag.id)
    cut = incomplete(devices, branch=branch)
    if cut is not None:
        return _Ended((cut,), False)
    if not devices.items:
        return _Ended((_empty(scope, branch, tagged=True),), True)
    asked = sorted({device.platform for device in devices.items if device.platform is not None})
    platforms = conn.platforms(opened, asked)
    cut = incomplete(platforms, branch=branch, asked=asked)
    if cut is not None:
        return _Ended((cut,), False)
    ports = conn.ports(opened, sorted(device.id for device in devices.items))
    cut = incomplete(ports, branch=branch)
    if cut is not None:
        return _Ended((cut,), False)
    asked = sorted({port.cable for port in ports.items if port.cable is not None})
    cables = conn.cables(opened, asked)
    cut = incomplete(cables, branch=branch, asked=asked)
    if cut is not None:
        return _Ended((cut,), False)
    contexts = conn.contexts(opened, document.probes) if document.probes is not None else None
    cut = incomplete(contexts, branch=branch) if contexts is not None else None
    if cut is not None:
        return _Ended((cut,), False)

    mapped = mapping.build(devices.items, platforms.items, ports.items, cables.items, document, branch=branch)
    scoped = {d.name: mapped.names[d.id] for d in devices.items if d.name is not None and d.id in mapped.names}
    probed, omitted, found = _probes(contexts, document.probes, scoped, branch=branch)
    configs, judged, refused = _renders(conn, opened, devices.items, branch=branch)
    return _Gathered(mapped, configs, tuple(probed), omitted, (*mapped.findings, *found, *judged), tuple(refused))


def _probes(
    contexts: Listing[Context] | None, name: str | None, scoped: dict[str, str], *, branch: str | None
) -> tuple[list[dict[str, Any]], tuple[dict[str, str], ...], tuple[Finding, ...]]:
    """The blueprint's probes, the fidelity rows of those omitted and the findings, from `contexts`, the whole list
    NetBox answered for the context `name` the reader document names (probes.select, probes.build), over `scoped`, each
    scoped device's name in NetBox to its blueprint name; none, and no fault, where the document names no context."""
    if contexts is None or name is None:
        return [], (), ()
    selected = probes.select(contexts, name, branch=branch)
    if isinstance(selected, Finding):
        return [], (), (selected,)
    return probes.build(selected, scoped, branch=branch)


def _renders(
    conn: Source, opened: Branch | None, devices: Sequence[Device], *, branch: str | None
) -> tuple[dict[int, str], list[Finding], list[Finding]]:
    """Each scoped device's configuration by its id, whether or not the mapping refused the device, the findings of
    those that have none, and apart from them those of a render NetBox refused 400 in other words than its no-template
    answer's: one render a device, in name order then id, a device with no name last."""
    configs: dict[int, str] = {}
    found: list[Finding] = []
    refused: list[Finding] = []
    for device in sorted(devices, key=lambda d: (d.name is None, d.name or "", d.id)):
        rendered = conn.render(opened, device.id)
        judged = renders.judge(device, rendered, branch=branch)
        if not isinstance(judged, Finding):
            configs[device.id] = judged
        elif rendered.status == REFUSED and judged.rule == renders.RULE_UNAVAILABLE:
            refused.append(judged)
        else:
            found.append(judged)
    return configs, found, refused


def _where(branch: str | None) -> str:
    return f"branch {branch}" if branch is not None else "main"


def _named(branch: str | None) -> None:
    """An empty name, or one of whitespace alone, refused: it names no branch, and `main` is None."""
    if branch is not None and not branch.strip():
        raise ValueError("the branch's name is empty or whitespace alone: give a branch's name, or None to read main")


def _scoped(scope: str) -> bool:
    """Whether `scope` is of its one form, `tag:<name>`."""
    return scope.startswith(SCOPE) and bool(scope.removeprefix(SCOPE))


def _invalid(scope: str, branch: str | None) -> Finding:
    message = f"The scope {scope!r} is not tag:<name>, so nothing of {_where(branch)} is read."
    return Finding(rule=RULE_SCOPE_INVALID, severity="error", object=scope, message=message)


def _empty(scope: str, branch: str | None, *, tagged: bool) -> Finding:
    tag = scope.removeprefix(SCOPE)
    said = f"no dcim.device carries the tag {tag}" if tagged else f"NetBox lists no tag {tag}"
    message = f"On {_where(branch)} {said}, so the scope {scope} selects no device."
    return Finding(rule=RULE_SCOPE_EMPTY, severity="error", object=scope, message=message)


def _after_refusal(closing: Sequence[Finding], refused: NetBoxError) -> list[Finding]:
    """The close's findings, or the branch's read again at the open, after NetBox refused a list of the read 400: as
    they stand where one is `read.moved`; else, a list not whole being all they could say, each with the refusal's own
    words, which the transport quotes as text, cut and with no token, so that the operator sees both."""
    if any(finding.rule == bracket.RULE_MOVED for finding in closing):
        return list(closing)
    said = str(refused).rstrip(".")
    return [
        Finding(
            rule=finding.rule,
            severity=finding.severity,
            object=finding.object,
            message=f"{finding.message.rstrip('.')}, read after NetBox refused a list of the read: {said}.",
        )
        for finding in closing
    ]


def _row(row: dict[str, str]) -> tuple[str, str, str, str]:
    return row["disposition"], row["object"], row["source"], row["reason"]


def _config(text: str | None) -> dict[str, str]:
    """A device's `config` member, or none where its render was refused."""
    return {"config": text} if text is not None else {}


def _problem(problem: Problem, branch: str | None) -> Finding:
    """A problem of the blueprint built, as an error under the problem's own rule, its pointer the object."""
    message = (
        f"The blueprint read from {_where(branch)} breaks {problem.rule} at {problem.pointer or '/'}: "
        f"{problem.detail}."
    )
    return Finding(rule=problem.rule, severity="error", object=problem.pointer, message=message)


def _warned(conn: Source) -> list[Finding]:
    return [conn.unverified] if conn.unverified is not None else []


def _result(doc: dict[str, Any] | None, findings: Sequence[Finding], *, empty: bool = False) -> Result:
    ordered = order(findings)
    refused = any(finding.severity == "error" for finding in ordered)
    return Result(None if refused else doc, ordered, empty)
