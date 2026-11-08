"""Fakes of the reconcile loop's runtime: a driver that keeps its labs in memory, and a readiness
wait, a push and a gNMI reader that answer by node. The loop's tests, the API's and verify's
share them.

`FakeDriver` answers the seam's calls over `labs` (twin to node to `NodeState`) and records
each in `calls`. The readiness wait, the push and the reader are called with a node's address;
given the driver, they name the node it belongs to, so a test says which nodes answer, refuse
or are unreachable by name.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import itertools
from collections.abc import AsyncIterator, Mapping, Sequence
from typing import Any

from fylgja_core import blueprint, deployment, gnmi, mapping, push
from fylgja_core.bundle import Manifest
from fylgja_core.credentials import Credential
from fylgja_core.deployment import Deployment
from fylgja_core.driver import (
    Action,
    Allocation,
    Capabilities,
    ChangeReason,
    Changes,
    DriverFailed,
    Exec,
    Inspection,
    NodeChange,
    NodeState,
    Planned,
    Refusal,
)
from fylgja_core.gnmi import Unreadable
from fylgja_core.platform_package import PlatformPackage
from fylgja_core.probe_package import ProbePackage
from fylgja_core.readiness import RULE_TIMEOUT, RULE_UNAUTHORIZED, NotReady

PLAN = "plan.txt"
CAPABILITIES = Capabilities(
    nodes="provisions", relink=True, forwarding="software", access="direct", isolation="names", reapply=False)


def hosts(manifest: Manifest) -> list[str]:
    """The probe hosts a manifest places, `<probe>-a` and `<probe>-b`, in probe order."""
    return [f"{probe.name}-{side}" for probe in manifest.probes for side in "ab"]


class FakeDriver:
    """A runtime in memory. `admit` answers the first `10.0.<n>.0/24` no reserved allocation
    holds, or `refuse`; `plan` renders `plan.txt` (the lab, its subnet and one line per node);
    `apply` makes every node anew (`10.0.<n>.<i>`, incarnation `boot-<k>`) when the lab is absent
    or `reconfigure` is asked. Over a lab that exists it makes anew, with a new incarnation, each
    node `changes` from the plan it last applied would call `added` (at the first free address),
    `restarted` or `recreated` (at its own); it drops a node `plan.txt` no longer names and keeps
    the rest as they are, so the same plan changes nothing, as containerlab's plain redeploy does
    (D-023). `fail_apply` and `fail_destroy` raise
    `DriverFailed` with nothing changed, and `fail_inspect_once` the next `inspect` once, as a
    runtime that blips. `fail_after` names a call after which, once it has
    taken effect, a kill is raised (`RuntimeError("killed")`), once. `block` names a call that, once recorded, waits
    until it is cancelled, as a runtime that never answers. `residue` holds the twins whose lab was removed
    by hand and left leftovers: `inspect` answers `residue` for them, and `apply` and `destroy`
    clear it. `silent` holds `(twin, node)` pairs whose transport never answers until a
    reconfigure makes the twin's nodes anew. `plan` also renders a `link` line per link and per
    probe host (its `eth1` to the port it is cabled to), and a `host` line per probe host, which
    every `apply` keeps so that `exec` of a host answers its address; `changes` compares two such
    renders: a kept node whose link lines change is `recabled`, or `restarted` when named in
    `restarts`, or `recreated` when named in `recreates`; a probe host whose `host` line (its
    address) changes is `recreated` (`exec`), as its start-up lines change, with `links` too
    when its link changes, so a moved host is `recreated` (`exec`, `links`), as the local
    driver answers. `changes` raises `ValueError` for two twins' deployments. `exec` raises
    `DriverFailed` for a node the lab lacks, one not running or one in `unreachable_exec`; it
    answers `exec_answers` for a node set there, a `ping` with BusyBox's summary (every echo of
    five answered, or three when `(twin, node)` is in `lossy`, status 1), and a probe host's
    readiness command with its address line. `relink=False` makes a driver that declares it
    cannot change a link, and `reapply=True` one that declares applying a deployment again
    finishes an apply cut short (D-068). `emit` reports a twin whose runtime changed: `events`
    yields each name emitted, in order, once, for good (D-058); `fail_events_once` makes the next
    `events` raise at once, as a driver that breaks the seam's contract. The names are kept in a
    list and each `events` call makes its own wake-up, on the loop that iterates it, so one fake
    serves a reconciler stopped on one event loop and started on another. `own_events=True`
    makes `apply` and `destroy` emit their twin as each is called, failing or not, as a real
    runtime's events follow what its deploy or destroy touched; otherwise only a test's `emit`
    names a twin."""

    def __init__(
        self,
        name: str = "fake",
        *,
        refuse: Refusal | None = None,
        fail_apply: bool = False,
        relink: bool = True,
        reapply: bool = False,
        own_events: bool = False,
    ) -> None:
        self.name = name
        self.relink = relink
        self.reapply = reapply
        self.own_events = own_events
        self.restarts: set[str] = set()
        self.recreates: set[str] = set()
        self.refuse = refuse
        self.fail_apply = fail_apply
        self.fail_destroy = False
        self.fail_inspect_once = False
        self.fail_events_once = False
        self.fail_after: str | None = None
        self.block: str | None = None
        self.labs: dict[str, dict[str, NodeState]] = {}
        self.residue: set[str] = set()
        self.silent: set[tuple[str, str]] = set()
        self.exec_answers: dict[tuple[str, str], Exec] = {}
        self.unreachable_exec: set[tuple[str, str]] = set()
        self.lossy: set[tuple[str, str]] = set()
        self._addresses: dict[str, dict[str, str]] = {}
        self._plans: dict[str, bytes] = {}  # each twin's `plan.txt` as last applied
        self.calls: list[tuple[str, ...]] = []
        self._boots: dict[str, int] = {}
        self._emitted: list[str] = []  # names emitted that no `events` has yielded yet
        self._listening: set[asyncio.Event] = set()  # each running `events` call's wake-up

    def capabilities(self) -> Capabilities:
        return dataclasses.replace(CAPABILITIES, relink=self.relink, reapply=self.reapply)

    async def admit(
        self,
        manifest: Manifest,
        platforms: Mapping[str, PlatformPackage],
        probe_packages: Mapping[str, ProbePackage],
        twin: str,
        reserved: Sequence[Allocation],
        held: Deployment | None = None,
    ) -> Allocation | Refusal:
        self.calls.append(("admit", twin, "held") if held is not None else ("admit", twin))
        await self._held("admit")  # a runtime call yields, so two admissions can interleave
        if self.refuse is not None:
            return self.refuse
        allocation: Allocation
        if held is not None:
            allocation = dict(held.allocation)
        else:
            taken = {a.get("mgmt_subnet") for a in reserved}
            n = next(n for n in itertools.count(1) if f"10.0.{n}.0/24" not in taken)
            allocation = {"lab": twin, "mgmt_subnet": f"10.0.{n}.0/24"}
        self._killed_after("admit")
        return allocation

    def plan(
        self,
        manifest: Manifest,
        bundle_id: str,
        platforms: Mapping[str, PlatformPackage],
        probe_packages: Mapping[str, ProbePackage],
        twin: str,
        allocation: Allocation,
    ) -> Planned:
        self.calls.append(("plan", twin))
        names = [node.name for node in manifest.nodes] + hosts(manifest)
        lines = [f"lab {allocation['lab']}", f"subnet {allocation['mgmt_subnet']}", *(f"node {n}" for n in names),
                 *(f"link {k.a.device}:{k.a.interface} {k.b.device}:{k.b.interface}" for k in manifest.links),
                 *(f"link {probe.name}-{side}:eth1 {endpoint.device}:{endpoint.interface}"
                   for probe in manifest.probes for side, endpoint in zip("ab", probe.endpoints, strict=True)),
                 *(f"host {probe.name}-{side} {endpoint.address}"
                   for probe in manifest.probes for side, endpoint in zip("ab", probe.endpoints, strict=True))]
        files = {PLAN: ("\n".join(lines) + "\n").encode()}
        listed = (deployment.File(path=PLAN, sha256=hashlib.sha256(files[PLAN]).hexdigest()),)
        body = {"driver": self.name, "twin": twin, "bundle_id": bundle_id,
                "files": [{"path": f.path, "sha256": f.sha256} for f in listed]}
        planned = Deployment(
            id=hashlib.sha256(blueprint.canonical(body)).hexdigest(),
            driver=self.name,
            twin=twin,
            allocation=dict(allocation),
            bundle_id=bundle_id,
            files=listed,
            demand=deployment.Demand(nodes=len(names), cpu=float(len(names)), memory_mb=512 * len(names)),
            fidelity=deployment.Fidelity(forwarding="software", approximations=(), omitted=(),
                                         synthesized=tuple(sorted(hosts(manifest))),
                                         lossy=deployment.Lossy(mappings=0, shared_ports=0)),
        )
        return Planned(deployment=planned, files=files)

    def changes(
        self,
        before: Planned,
        after: Planned,
        platforms: Mapping[str, PlatformPackage],
        probe_packages: Mapping[str, ProbePackage],
    ) -> Changes:
        self.calls.append(("changes", before.deployment.twin))
        if before.deployment.twin != after.deployment.twin:
            raise ValueError(f"the deployments are of two twins, {before.deployment.twin} and {after.deployment.twin}")
        old, new = _render(before), _render(after)
        nodes = tuple(self._change(name, old, new) for name in sorted(old.nodes | new.nodes))
        return Changes(nodes=nodes, links_added=tuple(sorted(new.links - old.links)),
                       links_removed=tuple(sorted(old.links - new.links)))

    def _change(self, name: str, old: _Render, new: _Render) -> NodeChange:
        """What going from the render `old` to `new` does to the node `name`, as `changes` answers it."""
        if name not in old.nodes:
            return NodeChange(node=name, action="added", reasons=())
        if name not in new.nodes:
            return NodeChange(node=name, action="removed", reasons=())
        reasons: list[ChangeReason] = []
        if old.hosts.get(name) != new.hosts.get(name):
            reasons.append("exec")
        if _on(name, old.links) != _on(name, new.links):
            reasons.append("links")
        action: Action
        if "exec" in reasons:
            action = "recreated"
        elif reasons:
            action = "restarted" if name in self.restarts else "recreated" if name in self.recreates else "recabled"
        else:
            action = "kept"
        return NodeChange(node=name, action=action, reasons=tuple(reasons))

    async def apply(
        self,
        deployment: Deployment,
        files: Mapping[str, bytes],
        platforms: Mapping[str, PlatformPackage],
        probe_packages: Mapping[str, ProbePackage],
        reconfigure: bool = False,
    ) -> None:
        twin = deployment.twin
        self.calls.append(("apply", twin, "reconfigure") if reconfigure else ("apply", twin))
        if self.own_events:
            self.emit(twin)
        await self._held("apply")
        if self.fail_apply:
            raise DriverFailed(f"the deploy of {twin} failed")
        lines = files[PLAN].decode().splitlines()
        names = [line.removeprefix("node ") for line in lines if line.startswith("node ")]
        n = int(str(deployment.allocation["mgmt_subnet"]).split(".")[2])
        lab = self.labs.get(twin)
        if reconfigure or not lab:
            k = self._boot(twin)
            self.labs[twin] = {
                name: NodeState(name=name, handle=f"{twin}-{name}", incarnation=f"boot-{k}", address=f"10.0.{n}.{i}",
                                running=True)
                for i, name in enumerate(names, 1)
            }
            self.silent = {(t, node) for t, node in self.silent if t != twin}
        else:  # a step's deploy over the running lab: anew what `changes` from the plan it runs calls so
            old, new = _render_text(self._plans.get(twin, files[PLAN])), _render_text(files[PLAN])
            anew = [name for name in names
                    if name not in lab or self._change(name, old, new).action in ("added", "restarted", "recreated")]
            kept = {name: lab[name] for name in names if name in lab}
            if anew:
                k = self._boot(twin)
                taken = {state.address for state in kept.values()}
                free = (a for a in (f"10.0.{n}.{i}" for i in itertools.count(1)) if a not in taken)
                for name in anew:
                    address = kept[name].address if name in kept else next(free)
                    kept[name] = NodeState(name=name, handle=f"{twin}-{name}", incarnation=f"boot-{k}",
                                           address=address, running=True)
            self.labs[twin] = {name: kept[name] for name in names}
        self._addresses[twin] = dict(_render_text(files[PLAN]).hosts)
        self._plans[twin] = files[PLAN]
        self.residue.discard(twin)
        self._killed_after("apply")

    async def inspect(self, twin: str) -> Inspection:
        self.calls.append(("inspect", twin))
        await self._held("inspect")
        if self.fail_inspect_once:
            self.fail_inspect_once = False
            raise DriverFailed(f"the inspect of {twin} failed")
        lab = self.labs.get(twin)
        if lab:
            return Inspection(state="present", nodes=tuple(lab[name] for name in sorted(lab)))
        return Inspection(state="residue" if twin in self.residue else "absent", nodes=())

    async def destroy(
        self,
        deployment: Deployment,
        files: Mapping[str, bytes],
        platforms: Mapping[str, PlatformPackage],
        probe_packages: Mapping[str, ProbePackage],
    ) -> None:
        twin = deployment.twin
        self.calls.append(("destroy", twin))
        if self.own_events:
            self.emit(twin)
        await self._held("destroy")
        if self.fail_destroy:
            raise DriverFailed(f"the destroy of {twin} failed")
        self.labs.pop(twin, None)
        self._plans.pop(twin, None)
        self.residue.discard(twin)
        self.silent = {(t, node) for t, node in self.silent if t != twin}
        self._killed_after("destroy")

    async def endpoints(self, twin: str) -> Mapping[str, str]:
        self.calls.append(("endpoints", twin))
        lab = self.labs.get(twin, {})
        return {name: state.address for name, state in sorted(lab.items()) if state.running and state.address}

    async def exec(self, twin: str, node: str, argv: Sequence[str], timeout_s: float) -> Exec:
        self.calls.append(("exec", twin, node, *argv))
        await self._held("exec")
        state = self.labs.get(twin, {}).get(node)
        if state is None or not state.running or (twin, node) in self.unreachable_exec:
            raise DriverFailed(f"{node} of {twin} cannot be reached")
        answer = self.exec_answers.get((twin, node))
        if answer is not None:
            return answer
        if argv and argv[0] == "ping":
            if (twin, node) in self.lossy:
                return Exec(1, "5 packets transmitted, 3 packets received, 40% packet loss\n", "")
            return Exec(0, "5 packets transmitted, 5 packets received, 0% packet loss\n", "")
        address = self._addresses.get(twin, {}).get(node)
        return Exec(0, "" if address is None else f"2: eth1    inet {address} scope global eth1\n", "")

    async def events(self) -> AsyncIterator[str]:
        if self.fail_events_once:
            self.fail_events_once = False
            raise RuntimeError("the fake's events failed")
        woken = asyncio.Event()  # made here, so it waits on the loop that iterates this call
        self._listening.add(woken)
        try:
            while True:
                while self._emitted:
                    yield self._emitted.pop(0)
                woken.clear()
                await woken.wait()
        finally:
            self._listening.discard(woken)

    def emit(self, name: str) -> None:
        """Report `name` as a twin whose runtime changed: the next name an `events` call yields,
        after any emitted before it. Called on the loop's thread."""
        self._emitted.append(name)
        for woken in self._listening:
            woken.set()

    def replace(self, twin: str, node: str) -> NodeState:
        """The node `node` of `twin` made anew behind the loop's back, as a runtime replaces a container or a
        pod: running, at its address and handle, its incarnation the twin's next boot's (`boot-<k>`)."""
        was = self.labs[twin][node]
        made = NodeState(name=node, handle=was.handle, incarnation=f"boot-{self._boot(twin)}", address=was.address,
                         running=True)
        self.labs[twin][node] = made
        return made

    def node_at(self, address: str) -> tuple[str, str] | None:
        """The `(twin, node)` whose node holds `address`, or None."""
        for twin, lab in self.labs.items():
            for name, state in lab.items():
                if state.address == address:
                    return twin, name
        return None

    def answers(self, address: str) -> bool:
        """Whether the node at `address` runs and its transport answers."""
        at = self.node_at(address)
        return at is not None and at not in self.silent and self.labs[at[0]][at[1]].running

    def _boot(self, twin: str) -> int:
        """The twin's next boot: the incarnation every node an apply makes anew takes."""
        k = self._boots.get(twin, 0) + 1
        self._boots[twin] = k
        return k

    async def _held(self, call: str) -> None:
        await asyncio.sleep(0)
        if self.block == call:
            await asyncio.get_running_loop().create_future()  # never answered: waits until cancelled

    def _killed_after(self, call: str) -> None:
        if self.fail_after == call:
            self.fail_after = None
            raise RuntimeError("killed")


@dataclasses.dataclass(frozen=True)
class _Render:
    nodes: frozenset[str]
    links: frozenset[tuple[str, str]]
    hosts: Mapping[str, str]


def _render(planned: Planned) -> _Render:
    """A `plan.txt` read back: its nodes, its links (each pair sorted) and its probe hosts."""
    return _render_text(planned.files[PLAN])


def _render_text(plan: bytes) -> _Render:
    nodes: set[str] = set()
    links: set[tuple[str, str]] = set()
    hosts: dict[str, str] = {}
    for line in plan.decode().splitlines():
        word, _, rest = line.partition(" ")
        if word == "node":
            nodes.add(rest)
        elif word == "link":
            a, b = sorted(rest.split())
            links.add((a, b))
        elif word == "host":
            name, address = rest.split()
            hosts[name] = address
    return _Render(nodes=frozenset(nodes), links=frozenset(links), hosts=hosts)


def _on(name: str, links: frozenset[tuple[str, str]]) -> set[tuple[str, str]]:
    return {link for link in links if any(end.partition(":")[0] == name for end in link)}


class FakeReady:
    """A readiness wait: a node answers when it is in `answers` (every node, when None) and,
    given the driver, the driver's node at the address runs and is not silent; a node in
    `refuse_login` refuses the login (`readiness.unauthorized`). Each call is recorded as
    `(node, timeout_s)`, the node by name when the driver knows the address."""

    def __init__(self, answers: set[str] | None, refuse_login: set[str] | None, driver: FakeDriver | None) -> None:
        if (answers is not None or refuse_login) and driver is None:
            raise ValueError("naming the nodes that answer needs the driver that knows their addresses")
        self.answers = answers
        self.refuse_login = set(refuse_login or ())
        self.driver = driver
        self.calls: list[tuple[str, float | None]] = []

    async def __call__(
        self, address: str, package: PlatformPackage, credential: Credential, *, timeout_s: float | None = None
    ) -> float:
        node = _name(self.driver, address)
        self.calls.append((node, timeout_s))
        await asyncio.sleep(0)
        if node in self.refuse_login:
            raise NotReady(RULE_UNAUTHORIZED, f"{address}:{package.push.port} refused the login")
        answering = self.answers is None or node in self.answers
        if self.driver is not None:
            answering = answering and self.driver.answers(address)
        if not answering:
            budget = package.readiness.timeout_s if timeout_s is None else timeout_s
            raise NotReady(RULE_TIMEOUT, f"{address}:{package.push.port} did not answer within {budget:g}s")
        return 0.0


class FakePush:
    """A push: it refuses the nodes in `refuse`, is unreachable once for each node in
    `unreachable` (the node is then dropped from it), and commits otherwise with a one-line
    diff. After `kill_after` calls, the next one raises a kill (`RuntimeError("killed")`), once.
    Each call is recorded as `(node, config)`."""

    def __init__(
        self, refuse: set[str] | None, unreachable: set[str] | None, kill_after: int | None, driver: FakeDriver | None
    ) -> None:
        if (refuse or unreachable) and driver is None:
            raise ValueError("naming the nodes that refuse needs the driver that knows their addresses")
        self.refuse = set(refuse or ())
        self.unreachable = set(unreachable or ())
        self.kill_after = kill_after
        self.driver = driver
        self.calls: list[tuple[str, str]] = []

    async def __call__(
        self, address: str, package: PlatformPackage, config: str, credential: Credential
    ) -> push.Pushed | push.Refused:
        if self.kill_after is not None and len(self.calls) >= self.kill_after:
            self.kill_after = None
            raise RuntimeError("killed")
        node = _name(self.driver, address)
        self.calls.append((node, config))
        await asyncio.sleep(0)
        if node in self.unreachable:
            self.unreachable.discard(node)
            raise push.Unreachable(f"https://{address}/jsonrpc gave no answer: ConnectError")
        if node in self.refuse:
            return push.Refused(f"At line 1: {node} refused the configuration")
        return push.Pushed(diff=f"+ {node}\n", duration_s=0.0)


class FakeReader:
    """A gNMI reader over `facts`, keyed `(twin, node)`, each a path to its value as `gnmi.get`
    hands it: a leaf's value, and a list path's entries as a list, one per neighbour (both kinds
    answer that once the reader collects them, verified-facts.md "gNMI"). It names the node by
    the driver's address, raises `Unreadable` for a node in `unreadable` or an address no node
    holds, and answers each asked path it has, leaving the rest out, as a node leaves out a
    value it does not hold. Each call is recorded as `(node, paths)`. `seed` writes facts
    consistent with a manifest, an entry's members without module prefixes; a test perturbs
    them."""

    def __init__(self, driver: FakeDriver) -> None:
        self.driver = driver
        self.facts: dict[tuple[str, str], dict[str, Any]] = {}
        self.unreadable: set[tuple[str, str]] = set()
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    async def __call__(
        self,
        address: str,
        package: PlatformPackage,
        credential: Credential,
        paths: Sequence[str],
        *,
        timeout_s: float = gnmi.GNMI_TIMEOUT_S,
    ) -> dict[str, Any]:
        at = self.driver.node_at(address)
        self.calls.append((at[1] if at is not None else address, tuple(paths)))
        await asyncio.sleep(0)
        if at is None or at in self.unreadable:
            raise Unreadable(f"{address}:{package.gnmi.port}", "UNAVAILABLE")
        facts = self.facts.get(at, {})
        return {path: facts[path] for path in paths if path in facts}

    def seed(self, twin: str, manifest: Manifest, platforms: Mapping[str, PlatformPackage]) -> None:
        """Facts as a twin built to `manifest` reports them: each node's host name its name,
        every cabled port enabled, and each end of every intent link listing one neighbour, the
        far node by name on the far port by its node name, in the package's shape."""
        packages = {node.name: platforms[node.platform] for node in manifest.nodes}
        rows = {(row.device, row.interface): row for row in manifest.mapping}
        for node in manifest.nodes:
            self.facts[(twin, node.name)] = {packages[node.name].conformance.host_name: node.name}
        for row in manifest.mapping:
            if row.disposition == "cabled":
                enabled = packages[row.device].conformance.port.enabled
                self.facts[(twin, row.device)][_rendered(enabled.path, row.node_name)] = enabled.value
        for link in manifest.links:
            for near, far in ((link.a, link.b), (link.b, link.a)):
                neighbor = packages[near.device].conformance.port.neighbor
                entry: dict[str, Any] = {}
                _put(entry, neighbor.system_name, far.device)
                _put(entry, neighbor.port_id, rows[(far.device, far.interface)].node_name)
                path = _rendered(neighbor.path, rows[(near.device, near.interface)].node_name)
                self.facts[(twin, near.device)][path] = [entry]


def _rendered(template: str, node_name: str | None) -> str:
    assert node_name is not None
    return mapping.render(template, {"node_name": node_name})


def _put(entry: dict[str, Any], subpath: str, value: Any) -> None:
    """`value` at a `/`-separated subpath inside `entry`, making the containers above it."""
    *above, last = subpath.split("/")
    for part in above:
        entry = entry.setdefault(part, {})
    entry[last] = value


def fake_ready(
    answers: set[str] | None = None, *, refuse_login: set[str] | None = None, driver: FakeDriver | None = None
) -> FakeReady:
    """A `ReadyFn` that records its calls; see `FakeReady`."""
    return FakeReady(answers, refuse_login, driver)


def fake_push(
    refuse: set[str] | None = None,
    unreachable: set[str] | None = None,
    *,
    kill_after: int | None = None,
    driver: FakeDriver | None = None,
) -> FakePush:
    """A `PushFn` that records its calls; see `FakePush`."""
    return FakePush(refuse, unreachable, kill_after, driver)


def _name(driver: FakeDriver | None, address: str) -> str:
    at = driver.node_at(address) if driver is not None else None
    return at[1] if at is not None else address
