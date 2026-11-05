"""Verify: a running twin's layer 1 read against its bundle, and each probe's burst (D-051,
D-031, D-030, D-032, D-048).

The device nodes' assertions are a pure function of the manifest (`_checks`, D-031). Per
device node: its host name, which every node reports, since the kind's baseline and any
configuration both set one, so a node reporting none fails; asserted against the device name
for a node with no configuration, since only the baseline sets it from the node name, and
otherwise read and reported; `port.enabled` on every cabled port, a link's end or a probe's
endpoint; `port.neighbor` on both ends of every intent link, since a shut port still lists a
far end that restarted while the far end sees none, each end judged against the far node's read
host name and the far port's node name; and the record's claim, for a node with a
configuration. The bursts are derived in `Verifier.verify` from the manifest's probes and judged
in `_burst`: from `a` toward `b`'s address and from `b` toward `a`'s. Skips, each an info
finding: a port intent disables, and its link at both ends; a synthesized link's neighbour; a
neighbour whose far node reports no host name to judge it against; the claim of a node with no
configuration; a configured node's host name, which names what was read; both bursts of a probe
whose endpoint intent disables, since the probe cannot pass by intent.

Each device node is read once, by one gNMI Get of every path its assertions need (`paths`, the
package's `conformance` paths, D-030), the nodes at once; then each probe's burst runs by the
driver's `exec`, one at a time. A node that cannot be read (absent from the record, without an
address, without a credential, or one the reader or `exec` cannot reach) files one
`verify.node.unread` error; every assertion of it, and every neighbour facing it, is a skip;
and the verdict is `failed`, never `nonconforming` (D-032). A held assertion files no finding.
Verify changes nothing, reads no configuration, and no message quotes a credential.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from fylgja_core import blueprint, burst, findings, gnmi, mapping, probe_package
from fylgja_core.bundle import Manifest, Node, Row
from fylgja_core.credentials import Missing, Provider
from fylgja_core.driver import DriverFailed, Exec
from fylgja_core.findings import Counts, Finding, Subject, Verdict
from fylgja_core.platform_package import PlatformPackage
from fylgja_core.probe_package import ProbePackage
from fylgja_core.twin_record import TwinRecord

# Rule ids. Clients and tests match on them.
RULE_HOST_NAME = "verify.host_name"
RULE_PORT_ENABLED = "verify.port.enabled"
RULE_PORT_NEIGHBOR = "verify.port.neighbor"
RULE_CLAIM = "verify.claim"
RULE_BURST = "verify.burst"
RULE_SKIPPED = "verify.skipped"
RULE_NODE_UNREAD = gnmi.Unreadable.rule

# A driver's `exec`: twin, node, argument vector, budget in seconds.
ExecFn = Callable[[str, str, Sequence[str], float], Awaitable[Exec]]

# What an assertion of each rule is about, for a skip's message.
_ABOUT = {RULE_HOST_NAME: "host name", RULE_PORT_ENABLED: "admin state", RULE_PORT_NEIGHBOR: "neighbour",
          RULE_CLAIM: "claim"}


@dataclass(frozen=True, kw_only=True)
class _Check:
    """One assertion of a device node, from the manifest: its rule, the node whose read it needs,
    its object; the port, and the far port of a neighbour; whether a host name is reported rather
    than asserted; and why it is not made, when the manifest alone says so."""

    rule: str
    node: str
    object: str
    row: Row | None = None
    far: Row | None = None
    reported: bool = False
    skip: str | None = None


@dataclass(frozen=True, kw_only=True)
class _Read:
    """One device node's Get: what it answered, or why it could not be read."""

    answer: Mapping[str, Any] | None = None
    failure: str | None = None


@dataclass(frozen=True, kw_only=True)
class _Seen:
    """What the judging reads: each device node's read and package, the record's claims, and
    the bundle verified against."""

    reads: Mapping[str, _Read]
    packages: Mapping[str, PlatformPackage]
    holds: Mapping[str, str | None]
    bundle_id: str

    def answer(self, node: str) -> Mapping[str, Any]:
        answer = self.reads[node].answer
        assert answer is not None  # judged only once the node was read
        return answer

    def host_name(self, node: str) -> str | None:
        return _text(self.answer(node).get(self.packages[node].conformance.host_name))


@dataclass(frozen=True)
class _Judged:
    """An assertion's outcome, and its finding unless it held."""

    outcome: Literal["held", "failed", "skipped"]
    finding: Finding | None = None


def paths(manifest: Manifest, node: str, package: PlatformPackage) -> list[str]:
    """The paths one node's Get asks: its host name, and for each cabled port of the node that
    intent enables, its admin state and its neighbour, `{node_name}` rendered from the row."""
    port = package.conformance.port
    asked = [package.conformance.host_name]
    for row in manifest.mapping:
        if row.device == node and row.disposition == "cabled" and row.enabled:
            asked += [_at(port.enabled.path, row), _at(port.neighbor.path, row)]
    return asked


def _checks(manifest: Manifest) -> list[_Check]:
    """Every assertion of the manifest's device nodes; a skip the manifest alone decides carries its reason."""
    rows = {(row.device, row.interface): row for row in manifest.mapping}
    found = [_Check(rule=RULE_HOST_NAME, node=node.name, object=node.name, reported=node.config is not None)
             for node in manifest.nodes]
    for row in manifest.mapping:
        if row.disposition == "cabled":
            skip = None if row.enabled else f"{_port(row)} is disabled by intent, so its admin state is not asserted."
            found.append(_Check(rule=RULE_PORT_ENABLED, node=row.device, object=_port(row), row=row, skip=skip))
    for link in manifest.links:
        for near, far in ((link.a, link.b), (link.b, link.a)):
            here, there = rows[(near.device, near.interface)], rows[(far.device, far.interface)]
            off = next((r for r in (here, there) if not r.enabled), None)
            skip = None if off is None else (f"{_port(off)} is disabled by intent, so {_port(here)}'s neighbour "
                                             "is not asserted.")
            found.append(_Check(rule=RULE_PORT_NEIGHBOR, node=near.device, object=_port(here), row=here, far=there,
                                skip=skip))
    for probe in manifest.probes:
        for host, endpoint, _ in blueprint.hosts(probe):
            row = rows[(endpoint.device, endpoint.interface)]
            found.append(_Check(rule=RULE_PORT_NEIGHBOR, node=row.device, object=_port(row), row=row,
                                skip=f"{_port(row)} is cabled to the probe host {host}, so its neighbour "
                                     "is not asserted."))
    for node in manifest.nodes:
        skip = None if node.config is not None else f"{node.name} carries no configuration, so no claim is asserted."
        found.append(_Check(rule=RULE_CLAIM, node=node.name, object=node.name, skip=skip))
    return found


class Verifier:
    """What verify needs: the loaded packages, the credential provider, and the reader."""

    def __init__(
        self,
        platforms: Mapping[str, PlatformPackage],
        probe_packages: Mapping[str, ProbePackage],
        credentials: Provider,
        *,
        reader: gnmi.ReadFn = gnmi.get,
        read_timeout_s: float = gnmi.GNMI_TIMEOUT_S,
    ) -> None:
        self.platforms = platforms
        self.probe_packages = probe_packages
        self.credentials = credentials
        self.reader = reader
        self.read_timeout_s = read_timeout_s

    async def verify(self, record: TwinRecord, manifest: Manifest, bundle_id: str, exec_fn: ExecFn) -> Verdict:
        """The verdict on `record`'s twin as it runs against `manifest`, the bundle `bundle_id`'s."""
        packages = {node.name: self.platforms[node.platform] for node in manifest.nodes}
        reads = await asyncio.gather(*(self._read(record, manifest, node, packages[node.name])
                                       for node in manifest.nodes))
        by_node = {node.name: read for node, read in zip(manifest.nodes, reads, strict=True)}
        unread = [_unread(name, read.failure) for name, read in by_node.items() if read.failure is not None]
        rows = {(row.device, row.interface): row for row in manifest.mapping}
        bursts: list[_Judged] = []
        for probe in manifest.probes:
            ends = [rows[(endpoint.device, endpoint.interface)] for endpoint in probe.endpoints]
            off = next((row for row in ends if not row.enabled), None)
            for side, (host, _, _) in zip("ab", blueprint.hosts(probe), strict=True):
                if off is not None:
                    about = f"{probe.name}/{side}"
                    bursts.append(_skipped(about, f"{about}'s burst is not asserted, since the probe's endpoint "
                                                  f"{_port(off)} is disabled by intent."))
                    continue
                outcome, failure = await self._burst(record.name, probe, side, host, exec_fn)
                bursts.append(outcome)
                if failure is not None:
                    unread.append(_unread(host, failure))
        seen = _Seen(reads=by_node, packages=packages, holds={n.name: n.holds for n in record.status.nodes},
                     bundle_id=bundle_id)
        judged = [_judge(check, seen) for check in _checks(manifest)] + bursts
        counted = Counter(j.outcome for j in judged)
        counts = Counts(held=counted["held"], failed=counted["failed"], skipped=counted["skipped"])
        status: Literal["ok", "failed", "nonconforming"] = (
            "failed" if unread else "nonconforming" if counts.failed else "ok")
        return Verdict(
            operation="verify",
            status=status,
            subject=Subject(twin=record.name, bundle_id=bundle_id, deployment_id=record.status.deployment_id),
            findings=findings.order(unread + [j.finding for j in judged if j.finding is not None]),
            counts=counts,
        )

    async def _read(self, record: TwinRecord, manifest: Manifest, node: Node, package: PlatformPackage) -> _Read:
        """One Get of every path the node's assertions need, or why the node could not be read."""
        state = next((n for n in record.status.nodes if n.name == node.name), None)
        if state is None:
            return _Read(failure="the record holds no such node")
        if not state.address:
            return _Read(failure="the record gives it no address")
        try:
            credential = self.credentials.login(package.credentials)
            answer = await self.reader(state.address, package, credential, paths(manifest, node.name, package),
                                       timeout_s=self.read_timeout_s)
        except (Missing, gnmi.Unreadable) as error:
            return _Read(failure=str(error))
        return _Read(answer=answer)

    async def _burst(
        self, twin: str, probe: blueprint.Probe, side: str, host: str, exec_fn: ExecFn
    ) -> tuple[_Judged, str | None]:
        """The burst from `host` toward the far host's address, and why the host could not be
        reached, if it could not."""
        package = self.probe_packages[probe.format]
        about, far = f"{probe.name}/{side}", probe_package.host_values(package, probe, side)["far_address"]
        try:
            result = await exec_fn(twin, host, burst.command(package, far), burst.timeout_s(package))
        except DriverFailed as error:
            return _skipped(about, f"{about}'s burst is not asserted, since {host} could not be read."), str(error)
        held, fact = burst.held(package, result)
        if held:
            return _Judged("held"), None
        return _failed(RULE_BURST, about, f"The burst from {host} to {far} did not hold: {fact}."), None


def _judge(check: _Check, seen: _Seen) -> _Judged:
    if check.skip is not None:
        return _skipped(check.object, check.skip)
    if seen.reads[check.node].answer is None:
        verb = "reported" if check.reported else "asserted"
        return _skipped(check.object, f"{check.object}'s {_ABOUT[check.rule]} is not {verb}, since {check.node} "
                                      "could not be read.")
    return _JUDGES[check.rule](check, seen)


def _host_name(check: _Check, seen: _Seen) -> _Judged:
    name = seen.host_name(check.node)
    if name is None:  # the kind's baseline and any configuration both set one: none is a fault
        return _failed(RULE_HOST_NAME, check.object, f"{check.node} reports no host name.")
    if check.reported:
        return _skipped(check.object, f"{check.node} reports its host name as {name}; a configured node's "
                                      "host name is reported, not asserted.")
    if name == check.node:
        return _Judged("held")
    return _failed(RULE_HOST_NAME, check.object, f"{check.node} reports its host name as {name}, not {check.node}.")


def _enabled(check: _Check, seen: _Seen) -> _Judged:
    assert check.row is not None
    enabled = seen.packages[check.node].conformance.port.enabled
    value = seen.answer(check.node).get(_at(enabled.path, check.row))
    observed = enabled.absent if value is None else _text(value)
    if observed == enabled.value:
        return _Judged("held")
    if observed is None:
        return _failed(RULE_PORT_ENABLED, check.object, f"{check.object} reports no admin state, where "
                                                        f"{enabled.value} is asserted.")
    return _failed(RULE_PORT_ENABLED, check.object, f"{check.object}'s admin state reads {observed}, "
                                                    f"not {enabled.value}.")


def _neighbor(check: _Check, seen: _Seen) -> _Judged:
    assert check.row is not None and check.far is not None
    far = check.far.device
    if seen.reads[far].answer is None:
        return _skipped(check.object, f"{check.object}'s neighbour is not asserted, since {far}, its far end, "
                                      "could not be read.")
    far_name = seen.host_name(far)
    if far_name is None:
        return _skipped(check.object, f"{check.object}'s neighbour is not asserted, since {far} reports no host "
                                      "name to judge it against.")
    neighbor = seen.packages[check.node].conformance.port.neighbor
    entries = _entries(seen.answer(check.node).get(_at(neighbor.path, check.row)))
    expected = f"{far_name} on {check.far.node_name}"
    if not entries:
        return _failed(RULE_PORT_NEIGHBOR, check.object, f"{check.object} lists no neighbour, where {expected} "
                                                         "is cabled.")
    if len(entries) > 1:
        return _failed(RULE_PORT_NEIGHBOR, check.object, f"{check.object} lists {len(entries)} neighbours, where "
                                                         f"{expected} alone is cabled.")
    system = _text(gnmi.leaf(entries[0], neighbor.system_name))
    port = _text(gnmi.leaf(entries[0], neighbor.port_id))
    if (system, port) == (far_name, check.far.node_name):
        return _Judged("held")
    return _failed(RULE_PORT_NEIGHBOR, check.object, f"{check.object} lists its neighbour as {system or '(none)'} "
                                                     f"on {port or '(none)'}, not {expected}.")


def _claim(check: _Check, seen: _Seen) -> _Judged:
    holds = seen.holds.get(check.node)
    if holds == seen.bundle_id:
        return _Judged("held")
    return _failed(RULE_CLAIM, check.object, f"The record claims {check.node} holds "
                                             f"{'no bundle' if holds is None else holds}, not {seen.bundle_id}.")


_JUDGES: Mapping[str, Callable[[_Check, _Seen], _Judged]] = {
    RULE_HOST_NAME: _host_name, RULE_PORT_ENABLED: _enabled, RULE_PORT_NEIGHBOR: _neighbor, RULE_CLAIM: _claim}


def _failed(rule: str, about: str, message: str) -> _Judged:
    return _Judged("failed", Finding(rule=rule, severity="error", object=about, message=message))


def _skipped(about: str, message: str) -> _Judged:
    return _Judged("skipped", Finding(rule=RULE_SKIPPED, severity="info", object=about, message=message))


def _unread(node: str, failure: str) -> Finding:
    return Finding(rule=RULE_NODE_UNREAD, severity="error", object=node,
                   message=f"{node} could not be read: {failure.rstrip('.')}.")


def _at(template: str, row: Row) -> str:
    assert row.node_name is not None  # a cabled row has its node name
    return mapping.render(template, {"node_name": row.node_name})


def _port(row: Row) -> str:
    return f"{row.device}:{row.interface}"


def _text(value: Any) -> str | None:
    return None if value is None else str(value)


def _entries(value: Any) -> list[Any]:
    """A neighbour list as entries: none when unreported, one when answered as a lone entry."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]
