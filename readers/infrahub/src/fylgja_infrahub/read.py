"""The read: a branch of Infrahub at a time, under a scope, into a blueprint 1 with its source envelope, or the
findings that refused it (D-082).

`read` judges every rule it can in one pass (Constitution III) and answers a `Result` whose blueprint is None exactly
when a finding is an error; it never raises `Refused`, which `head` alone raises, since it answers a bare time. Its
order: the forms of the scope, `at` and `generated_since`, with nothing sent where one is at fault; the branch's
schema, held to the mapping's table, which ends the read where it differs; the scope's devices, which end it where
there is none (`scope.empty`) or the list is not whole; their ports, which end it where they are not whole; the
mapping; each scoped device's artifact, selected from its listing, then its content fetched and judged, in name
order, a device the mapping refused among them, since choosing the artifact needs the reader document's `artifact` and
the listing alone, so that every fault of every device is filed at once (P3-24); the stale rule over the artifacts
selected (stale.py), from the scope's stamps, their cables', the query groups' and the events of the branch's
history, its own and, for a branch but `main`, `main`'s up to its `branched_from` (P3-45), each list held whole before
the rule is judged; the probes, where the reader document asks for them, the kind held to the schema
already read and every `FylgjaProbe` read at `at` as every other list (probes.py); and the blueprint, its source
envelope beside the network, held to blueprint 1.

The id addresses the network and the probes alone (D-006), so the envelope travels unhashed: where the read was made
from (`source`, `branch`, `at` as given, `scope`), by which mapping and against which schema, when (`observed_at`, the
reader's clock, taken before the first request and pinning nothing), and its fidelity rows. Every result carries the
connection's version warning, where it has one.

`head` answers the first instant after the branch's latest write, `times.after` of the latest of every stamp of the
scope as it stands, every `FylgjaProbe`'s stamp where the branch has the kind, and every event of the branch's history,
its own since it was made and `main`'s up to then (stale.latest, stale.inherited), for a caller that wants the branch as
it stands: a read pinned at exactly a write's stamp
answers its values with the earlier stamps, and one a microsecond after answers the write (design/verified-facts.md,
"Infrahub 1.11.11"). A write whose event Infrahub has not yet logged, which it does up to seconds after, is not
counted: a caller that has just written waits that out.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fylgja_core import blueprint
from fylgja_core.documents import Problem
from fylgja_core.findings import Finding, order

from fylgja_infrahub import artifacts, mapping, probes, schema, stale, times
from fylgja_infrahub.document import ReaderDocument
from fylgja_infrahub.rows import (
    RULE_INCOMPLETE,
    Artifact,
    CableStamp,
    Device,
    Event,
    Listing,
    Schema,
    Source,
    Stamp,
    Stamped,
    incomplete,
)

# Rule ids. Callers and tests match on them (rules.md).
RULE_SCOPE_INVALID = "scope.invalid"
RULE_SCOPE_EMPTY = "scope.empty"

SCOPE = "tag:"
"""What begins every scope, `tag:<name>`: the scope is every `DcimDevice` that carries the tag, whatever its
status."""

SOURCE = "infrahub"
"""The envelope's `source`."""

OBSERVED = "%Y-%m-%dT%H:%M:%S.%fZ"
"""The envelope's `observed_at`: UTC, to the microsecond."""

FIDELITY_KEYS = ("disposition", "object", "source", "reason")
"""A fidelity row's members, which the envelope's rows are sorted by in this order."""


@dataclass(frozen=True)
class Result:
    """What a read answers: the blueprint, None exactly when a finding is an error; every finding, in a result's order
    (findings.order); and whether the scope selected no device."""

    blueprint: dict[str, Any] | None
    findings: tuple[Finding, ...]
    empty: bool


class Refused(Exception):
    """A call that answers a bare value could not answer one, with the findings that say why: raised by `head` alone,
    since `read` puts every refusal in its `Result`."""

    def __init__(self, findings: Sequence[Finding]) -> None:
        self.findings = tuple(findings)
        super().__init__("; ".join(f"{f.rule} {f.object}: {f.message}" for f in self.findings))


def check_schema(conn: Source, *, branch: str) -> tuple[Finding, ...]:
    """Every way the present schema of `branch` differs from the mapping's table (schema.check), with the
    connection's version warning, where it has one."""
    return order([*schema.check(conn.schema(branch), branch=branch), *_warned(conn)])


def read(
    conn: Source,
    *,
    branch: str,
    at: str,
    scope: str,
    document: ReaderDocument,
    generated_since: str | None = None,
) -> Result:
    """`branch` read at `at`, sent as given, under `scope`, by the mapping and `document`, as a blueprint 1 with its
    source envelope, or the findings that refused it."""
    observed_at = datetime.now(UTC).strftime(OBSERVED)
    warned = _warned(conn)
    forms = _forms(branch=branch, at=at, scope=scope, generated_since=generated_since)
    if forms:
        return _result(None, [*forms, *warned])

    held = conn.schema(branch)
    differs = schema.check(held, branch=branch)
    if differs:
        return _result(None, [*differs, *warned])

    tag = scope.removeprefix(SCOPE)
    devices = conn.devices(branch, at, tag)
    cut = incomplete(devices, branch=branch, at=at)
    if cut is not None:
        return _result(None, [cut, *warned])
    if not devices.items:
        return _result(None, [_empty(scope, branch=branch, at=at), *warned], empty=True)
    ports = conn.ports(branch, at, sorted(device.id for device in devices.items))
    cut = incomplete(ports, branch=branch, at=at)
    if cut is not None:
        return _result(None, [cut, *warned])

    mapped = mapping.build(devices.items, ports.items, document, branch=branch, at=at)
    found = list(mapped.findings)
    configs, judged, selected = _configurations(conn, devices.items, document, branch=branch, at=at)
    found += judged
    found += _stale(conn, held, tag, devices.items, selected, branch=branch, at=at, generated_since=generated_since)
    declared, omitted, filed = _probes(conn, held, devices.items, mapped.names, document, branch=branch, at=at)
    found += filed
    fidelity = sorted([*mapped.fidelity, *omitted], key=lambda row: tuple(row[key] for key in FIDELITY_KEYS))

    by_name = {name: device_id for device_id, name in mapped.names.items()}
    network = {
        "devices": [{**device, **_config(configs.get(by_name[device["name"]]))} for device in mapped.devices],
        "links": [dict(link) for link in mapped.links],
    }
    envelope = {
        "source": SOURCE,
        "branch": branch,
        "at": at,
        "scope": scope,
        "mapping": {"reader": schema.READER, "model": schema.MODEL, "version": schema.COMMIT},
        "schema_hash": held.hash,
        "observed_at": observed_at,
        "fidelity": [dict(row) for row in fidelity],
    }
    doc = {"blueprint_version": blueprint.VERSION, "network": network, "probes": declared, "source": envelope}
    found += [_problem(problem, branch=branch, at=at) for problem in blueprint.validate(doc)]
    return _result(doc, [*found, *warned])


def head(conn: Source, *, branch: str, scope: str) -> str:
    """The first instant after `branch`'s latest write under `scope`, the branch read as it stands: `times.after` of
    the latest of every stamp of the scope's devices, their cables' and their checksums' among them, of every
    `FylgjaProbe`'s stamp, whatever devices it names, where the branch's schema holds the kind, since a probe is the
    blueprint's too (P3-38), and of every event of the branch since it was made and, for a branch but `main`, of
    `main`'s up to then, what the branch was made holding (P3-45), nothing discounted (stale.latest), in the layout
    Infrahub answered it in.
    `Refused` with `scope.invalid` where the scope is not `tag:<name>`, and nothing is sent; with the schema check's
    findings (`schema.*`) where the branch's schema differs from the mapping's table, since its reads select the
    table's fields, and nothing else is read (P3-51); with `scope.empty` where it selects no device; and with
    `read.incomplete` where a list it reads is not whole. A source that answers its devices with no time at all is a
    `ValueError`, since the branch then has no write to answer the instant after."""
    if not _scoped(scope):
        raise Refused([_invalid(scope, branch=branch, at=None)])
    held = conn.schema(branch)
    differs = schema.check(held, branch=branch)
    if differs:
        raise Refused(differs)
    stamped = conn.stamps(branch, None, scope.removeprefix(SCOPE))
    cuts = _cuts(stamped, branch=branch, at=None)
    if cuts:
        raise Refused(cuts)
    if not stamped.items:
        raise Refused([_empty(scope, branch=branch, at=None)])
    cables = conn.cable_stamps(branch, None, sorted(device.id for device in stamped.items))
    cuts = _cable_cuts(cables, branch=branch, at=None)
    if cuts:
        raise Refused(cuts)
    probed = _probe_stamps(conn, held, branch)
    # The logs are read down to the latest stamp: an event no later than it cannot be the latest write.
    floor = stale.latest(stamped.items, cables.items, (), probed)
    point = conn.branch(branch).branched_from
    events = conn.events(branch, stale.logs(branch), stale.since(branch, point, floor), floor)
    cut = incomplete(events, branch=branch, at=None)
    if cut is not None:
        raise Refused([cut])
    latest = stale.latest(stamped.items, cables.items, stale.inherited(events.items, branch, point), probed)
    if latest is None:
        raise ValueError(f"branch {branch} answered no stamp of the scope {scope}'s devices and no event")
    return times.after(latest)


def _probe_stamps(conn: Source, held: Schema, branch: str) -> tuple[tuple[str, Stamp], ...]:
    """Every `FylgjaProbe`'s stamp on `branch` as it stands, where `held`, the branch's schema already read, holds the
    kind, and none where it lacks it; `Refused` with `read.incomplete` where the list is not whole."""
    if probes.KIND not in held.nodes:
        return ()
    listing = conn.probe_stamps(branch, None)
    cut = incomplete(listing, branch=branch, at=None, key=lambda item: item[0])
    if cut is not None:
        raise Refused([cut])
    return listing.items


def _forms(*, branch: str, at: str, scope: str, generated_since: str | None) -> list[Finding]:
    """Every fault of the scope's form and of the two times', before anything is sent: a `generated_since` later than
    `at` among them, since it would stand for a regeneration the bytes read at `at` cannot carry (P3-30)."""
    found = [
        refused
        for value in (at, generated_since)
        if value is not None and (refused := times.invalid(value, branch=branch)) is not None
    ]
    if not found and generated_since is not None and times.later(generated_since, at):
        message = (
            f"generated_since {generated_since!r} is later than the time read, {at}, so it would stand for a "
            f"regeneration that a read of branch {branch} at {at} cannot meet; give one no later than at."
        )
        found.append(Finding(rule=times.RULE_INVALID, severity="error", object=generated_since, message=message))
    if not _scoped(scope):
        found.append(_invalid(scope, branch=branch, at=at))
    return found


def _scoped(scope: str) -> bool:
    """Whether `scope` is of its one form, `tag:<name>`."""
    return scope.startswith(SCOPE) and bool(scope.removeprefix(SCOPE))


def _when(at: str | None) -> str:
    return f"at {at}" if at is not None else "as it stands"


def _invalid(scope: str, *, branch: str, at: str | None) -> Finding:
    message = f"The scope {scope!r} is not tag:<name>, so nothing of branch {branch} is read {_when(at)}."
    return Finding(rule=RULE_SCOPE_INVALID, severity="error", object=scope, message=message)


def _empty(scope: str, *, branch: str, at: str | None) -> Finding:
    tag = scope.removeprefix(SCOPE)
    message = f"No DcimDevice on branch {branch} {_when(at)} carries the tag {tag}, so the scope {scope} selects none."
    return Finding(rule=RULE_SCOPE_EMPTY, severity="error", object=scope, message=message)


def _configurations(
    conn: Source, devices: Sequence[Device], document: ReaderDocument, *, branch: str, at: str
) -> tuple[dict[str, str], list[Finding], dict[str, str]]:
    """Each scoped device's configuration by its id, whether or not the mapping refused the device, the findings of
    those that have none, and the id of the artifact selected for each device it was selected for, by the device's
    id: every artifact selected from its listing first, so that no content is fetched for a device refused there, then
    each one's content fetched and judged, in name order."""
    found: list[Finding] = []
    selected: list[tuple[Device, Artifact, str]] = []
    for device in sorted(devices, key=lambda d: (d.name, d.id)):
        chosen = artifacts.select(device, document.artifact, branch=branch, at=at)
        if isinstance(chosen, Finding):
            found.append(chosen)
            continue
        assert chosen.storage_id is not None, "select answers no artifact without a storage id"
        selected.append((device, chosen, chosen.storage_id))
    configs: dict[str, str] = {}
    for device, artifact, storage_id in selected:
        content = conn.content(branch, at, storage_id)
        text = artifacts.judge(device, artifact, content, branch=branch, at=at)
        if isinstance(text, Finding):
            found.append(text)
        else:
            configs[device.id] = text
    return configs, found, {device.id: artifact.id for device, artifact, _ in selected}


def _stale(
    conn: Source,
    held: Schema,
    tag: str,
    devices: Sequence[Device],
    selected: Mapping[str, str],
    *,
    branch: str,
    at: str,
    generated_since: str | None,
) -> list[Finding]:
    """The stale rule over the artifacts `selected` (stale.judge), from the scope's stamps, their cables' and the
    internal query groups' of the queries the scope's artifacts render through, each read at `at`, and the events of
    the branch's history down to the earliest checksum stamp among the devices judged, or `generated_since` where that
    is later (stale.floor, P3-50): its own log's, and, for a branch but `main`, `main`'s up to its `branched_from`
    (stale.inherited, P3-45); or `read.incomplete` for
    each of those lists that is not whole, the rule unjudged, since a list in part could pass a stale device. A device
    of `devices` whose artifact was selected and the stamps read did not list is `read.incomplete` too, by its name,
    and the rest are judged. Nothing is read where no artifact was selected, and no event where none of those has a
    checksum stamp."""
    if not selected:
        return []
    stamped = conn.stamps(branch, at, tag)
    cuts = _cuts(stamped, branch=branch, at=at, only=selected)
    if cuts:
        return cuts
    listed = {device.id for device in stamped.items}
    unlisted = [
        Finding(
            rule=RULE_INCOMPLETE,
            severity="error",
            object=device.name,
            message=(
                f"Infrahub listed device {device.name} on branch {branch} at {at}, and the stale rule's read of the "
                "scope's stamps did not, so that list is not whole and the device is not judged."
            ),
        )
        for device in devices
        if device.id in selected and device.id not in listed
    ]
    cables = conn.cable_stamps(branch, at, sorted(listed))
    cuts = _cable_cuts(cables, branch=branch, at=at)
    if cuts:
        return [*unlisted, *cuts]
    queries = sorted({g.query for device in stamped.items for g in device.artifacts.items if g.query is not None})
    groups = conn.groups(branch, at, queries)
    cut = incomplete(groups, branch=branch, at=at)
    if cut is not None:
        return [*unlisted, cut]
    lowest = stale.floor(stamped.items, selected, generated_since)
    history: tuple[Event, ...] = ()
    if lowest is not None:
        point = conn.branch(branch).branched_from
        events = conn.events(branch, stale.logs(branch), stale.since(branch, point, lowest), lowest)
        cut = incomplete(events, branch=branch, at=at)
        if cut is not None:
            return [*unlisted, cut]
        history = stale.inherited(events.items, branch, point)
    found = stale.judge(
        stamped.items,
        cables.items,
        groups.items,
        history,
        held,
        selected,
        branch=branch,
        at=at,
        generated_since=generated_since,
    )
    return [*unlisted, *found]


def _probes(
    conn: Source,
    held: Schema,
    devices: Sequence[Device],
    names: Mapping[str, str],
    document: ReaderDocument,
    *,
    branch: str,
    at: str,
) -> tuple[list[dict[str, Any]], tuple[dict[str, str], ...], list[Finding]]:
    """The blueprint's probes, the fidelity rows of those omitted and the findings, where the document asks for probes:
    the kind held to `held`, the schema already read, and nothing read where it is absent; then every `FylgjaProbe`
    read at `at`, held whole, and built over each scoped device's name in Infrahub to its blueprint name, `names` being
    by id (probes.build). None, and no fault, where the document asks for none."""
    if not document.probes:
        return [], (), []
    lacking = probes.absent(held, branch=branch)
    if lacking is not None:
        return [], (), [lacking]
    listing = conn.probes(branch, at)
    cut = incomplete(listing, branch=branch, at=at)
    if cut is not None:
        return [], (), [cut]
    scoped = {device.name: names[device.id] for device in devices if device.id in names}
    built, omitted, found = probes.build(listing, scoped, branch=branch, at=at)
    return built, omitted, list(found)


def _cuts(
    stamped: Listing[Stamped], *, branch: str, at: str | None, only: Collection[str] | None = None
) -> list[Finding]:
    """`read.incomplete` for the stamps' list of devices where it is not whole; else for each nested list of each
    device whose id is in `only`, or of every device where it is None, that is not whole: an interface by its id, an
    address by its own and an artifact by its own."""
    cut = incomplete(stamped, branch=branch, at=at)
    if cut is not None:
        return [cut]
    found = []
    for device in stamped.items:
        if only is not None and device.id not in only:
            continue
        found += [
            cut
            for cut in (
                incomplete(device.interfaces, branch=branch, at=at, key=lambda interface: interface[0]),
                incomplete(device.addresses, branch=branch, at=at, key=lambda address: address[1]),
                incomplete(device.artifacts, branch=branch, at=at),
            )
            if cut is not None
        ]
    return found


def _cable_cuts(cables: Listing[CableStamp], *, branch: str, at: str | None) -> list[Finding]:
    """`read.incomplete` for the list of the scope's connectors where it is not whole, each row a port's, since a
    connector is listed once for each port it ends; else for each connector's ends that are not whole on any of its
    rows, since each row's device is judged over its own, once a connector however many of its rows are cut."""
    cut = incomplete(cables, branch=branch, at=at, key=lambda cable: cable.port)
    if cut is not None:
        return [cut]
    cuts: dict[str, Finding] = {}
    for cable in cables.items:
        if cable.id not in cuts and (cut := incomplete(cable.ends, branch=branch, at=at)) is not None:
            cuts[cable.id] = cut
    return list(cuts.values())


def _config(text: str | None) -> dict[str, str]:
    """A device's `config` member, or none where its configuration was refused."""
    return {"config": text} if text is not None else {}


def _problem(problem: Problem, *, branch: str, at: str) -> Finding:
    """A problem of the blueprint built, as an error under the problem's own rule, its pointer the object."""
    message = (
        f"The blueprint read from branch {branch} at {at} breaks {problem.rule} at {problem.pointer or '/'}: "
        f"{problem.detail}."
    )
    return Finding(rule=problem.rule, severity="error", object=problem.pointer, message=message)


def _warned(conn: Source) -> list[Finding]:
    return [conn.unverified] if conn.unverified is not None else []


def _result(doc: dict[str, Any] | None, findings: Sequence[Finding], *, empty: bool = False) -> Result:
    ordered = order(findings)
    refused = any(finding.severity == "error" for finding in ordered)
    return Result(None if refused else doc, ordered, empty)
