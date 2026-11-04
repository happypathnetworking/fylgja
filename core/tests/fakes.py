"""Fakes of the reconcile loop's runtime: a driver that keeps its labs in memory, and a readiness
wait and a push that answer by node. The loop's tests and the API's share them.

`FakeDriver` answers the seam's seven calls over `labs` (twin to node to `NodeState`) and records
each in `calls`. The readiness wait and the push are called with a node's address; given the
driver, they name the node it belongs to, so a test says which nodes answer, refuse or are
unreachable by name.
"""

from __future__ import annotations

import asyncio
import hashlib
import itertools
from collections.abc import Mapping, Sequence

from fylgja_core import blueprint, deployment, push
from fylgja_core.bundle import Manifest
from fylgja_core.credentials import Credential
from fylgja_core.deployment import Deployment
from fylgja_core.driver import Allocation, Capabilities, DriverFailed, Inspection, NodeState, Planned, Refusal
from fylgja_core.platform_package import PlatformPackage
from fylgja_core.probe_package import ProbePackage
from fylgja_core.readiness import RULE_TIMEOUT, RULE_UNAUTHORIZED, NotReady

PLAN = "plan.txt"
CAPABILITIES = Capabilities(nodes="provisions", relink=False, forwarding="software", access="direct", isolation="names")


def hosts(manifest: Manifest) -> list[str]:
    """The probe hosts a manifest places, `<probe>-a` and `<probe>-b`, in probe order."""
    return [f"{probe.name}-{side}" for probe in manifest.probes for side in "ab"]


class FakeDriver:
    """A runtime in memory. `admit` answers the first `10.0.<n>.0/24` no reserved allocation
    holds, or `refuse`; `plan` renders `plan.txt` (the lab, its subnet and one line per node);
    `apply` makes every node anew (`10.0.<n>.<i>`, incarnation `boot-<k>`) when the lab is absent
    or `reconfigure` is asked, and changes nothing over a lab that exists, as containerlab's
    plain redeploy does (D-023). `fail_apply` and `fail_destroy` raise `DriverFailed` with
    nothing changed. `fail_after` names a call after which, once it has taken effect, a kill is
    raised (`RuntimeError("killed")`), once. `block` names a call that, once recorded, waits
    until it is cancelled, as a runtime that never answers. `residue` holds the twins whose lab was removed
    by hand and left leftovers: `inspect` answers `residue` for them, and `apply` and `destroy`
    clear it. `silent` holds `(twin, node)` pairs whose transport never answers until a
    reconfigure makes the twin's nodes anew."""

    def __init__(self, name: str = "fake", *, refuse: Refusal | None = None, fail_apply: bool = False) -> None:
        self.name = name
        self.refuse = refuse
        self.fail_apply = fail_apply
        self.fail_destroy = False
        self.fail_after: str | None = None
        self.block: str | None = None
        self.labs: dict[str, dict[str, NodeState]] = {}
        self.residue: set[str] = set()
        self.silent: set[tuple[str, str]] = set()
        self.calls: list[tuple[str, ...]] = []
        self._boots: dict[str, int] = {}

    def capabilities(self) -> Capabilities:
        return CAPABILITIES

    async def admit(
        self,
        manifest: Manifest,
        platforms: Mapping[str, PlatformPackage],
        probe_packages: Mapping[str, ProbePackage],
        twin: str,
        reserved: Sequence[Allocation],
    ) -> Allocation | Refusal:
        self.calls.append(("admit", twin))
        await self._held("admit")  # a runtime call yields, so two admissions can interleave
        if self.refuse is not None:
            return self.refuse
        taken = {a.get("mgmt_subnet") for a in reserved}
        n = next(n for n in itertools.count(1) if f"10.0.{n}.0/24" not in taken)
        self._killed_after("admit")
        return {"lab": twin, "mgmt_subnet": f"10.0.{n}.0/24"}

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
        lines = [f"lab {allocation['lab']}", f"subnet {allocation['mgmt_subnet']}", *(f"node {n}" for n in names)]
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
        await self._held("apply")
        if self.fail_apply:
            raise DriverFailed(f"the deploy of {twin} failed")
        if reconfigure or not self.labs.get(twin):
            lines = files[PLAN].decode().splitlines()
            names = [line.removeprefix("node ") for line in lines if line.startswith("node ")]
            n = int(str(deployment.allocation["mgmt_subnet"]).split(".")[2])
            k = self._boots.get(twin, 0) + 1
            self._boots[twin] = k
            self.labs[twin] = {
                name: NodeState(name=name, handle=f"{twin}-{name}", incarnation=f"boot-{k}", address=f"10.0.{n}.{i}",
                                running=True)
                for i, name in enumerate(names, 1)
            }
            self.silent = {(t, node) for t, node in self.silent if t != twin}
        self.residue.discard(twin)
        self._killed_after("apply")

    async def inspect(self, twin: str) -> Inspection:
        self.calls.append(("inspect", twin))
        await self._held("inspect")
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
        await self._held("destroy")
        if self.fail_destroy:
            raise DriverFailed(f"the destroy of {twin} failed")
        self.labs.pop(twin, None)
        self.residue.discard(twin)
        self.silent = {(t, node) for t, node in self.silent if t != twin}
        self._killed_after("destroy")

    async def endpoints(self, twin: str) -> Mapping[str, str]:
        self.calls.append(("endpoints", twin))
        lab = self.labs.get(twin, {})
        return {name: state.address for name, state in sorted(lab.items()) if state.running and state.address}

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

    async def _held(self, call: str) -> None:
        await asyncio.sleep(0)
        if self.block == call:
            await asyncio.get_running_loop().create_future()  # never answered: waits until cancelled

    def _killed_after(self, call: str) -> None:
        if self.fail_after == call:
            self.fail_after = None
            raise RuntimeError("killed")


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
