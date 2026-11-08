"""The driver seam: the ten calls a runtime answers (Constitution XIII, D-017, D-049, D-058).

Everything above the seam calls these and nothing else; nothing above it names a runtime.
Every call but `exec` is idempotent: `exec` runs what it is given. `plan` is synchronous and
pure: it is the only binding of a bundle to a twin and a runtime (D-011), and returns the
`Deployment` and the rendered files it describes, or raises `Unplannable` when the runtime
cannot hold the bundle as compiled.
`changes` is the other pure call: given two deployments, it answers what the runtime does to each
node to go from the first to the second (D-049). The remaining calls act on the runtime and are `async`;
`events` among them is an asynchronous iterator of the names of twins whose runtime changed (D-058).
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from fylgja_core import findings
from fylgja_core.bundle import Manifest
from fylgja_core.deployment import Deployment
from fylgja_core.findings import Finding
from fylgja_core.platform_package import PlatformPackage
from fylgja_core.probe_package import ProbePackage

# The driver's own shape: what admit reserves for a twin and plan reads back.
# The local driver's is {"lab": str, "mgmt_subnet": str}.
Allocation = Mapping[str, Any]

EVENTS_BACKOFF_FIRST_S = 1.0
EVENTS_BACKOFF_CEILING_S = 60.0


def events_backoff(previous: float | None) -> float:
    """The delay before the next try after a failure, given the one before it (None for the
    first): 1 s, then twice the last, at most 60 s. A driver's `events` starts its source again
    after it (D-058), and the loop tries a twin again after a transient failure by it
    (`reconcile.next_backoff`, D-023): the one backoff of the core."""
    return EVENTS_BACKOFF_FIRST_S if previous is None else min(previous * 2, EVENTS_BACKOFF_CEILING_S)


@dataclass(frozen=True, kw_only=True)
class Capabilities:
    """What a driver declares of its runtime; the API lists it (api-1 Driver). `reapply` is
    whether applying a deployment again finishes an apply that was cut short: where it is true,
    a resumed apply is applied again, with no probe and no `reconfigure`; where it is false, a
    resumed apply probes the lab first and may reconfigure it (D-023, D-068)."""

    nodes: Literal["provisions", "claims"]
    relink: bool
    forwarding: Literal["software", "hardware"]
    access: Literal["direct", "proxied"]
    isolation: Literal["names", "network"]
    reapply: bool


class DriverFailed(Exception):
    """A runtime failure of `admit`, `apply`, `inspect` or `destroy` (and of `endpoints`,
    which inspects): a command or a request the runtime failed or did not answer in time, or
    an answer it should not have given. It is transient: the loop backs off and retries.
    Each driver's own failures subclass it, so nothing above the seam names a runtime to
    catch one. A caller's error, such as files that are not the deployment's, is a
    `ValueError` instead."""


@dataclass(frozen=True)
class Refusal:
    """What `admit` answers when it refuses; `rule` is `admission.capacity` or another `admission.*` rule,
    or a credential's own (`credential.missing`, `credential.malformed`) where admission reads a credential."""

    rule: str
    message: str


class Unplannable(Exception):
    """The bundle cannot be planned on this runtime; `findings` holds every fault, in a
    verdict's order. A plan refuses as a compile does (`compiler.Uncompilable`)."""

    def __init__(self, found: Iterable[Finding]) -> None:
        self.findings = findings.order(found)
        super().__init__(self.findings)

    def __str__(self) -> str:
        return "; ".join(f"{f.rule} on {f.object}: {f.message}" for f in self.findings)


@dataclass(frozen=True)
class Planned:
    """What `plan` answers: the deployment and every rendered file by path, the same paths
    and hashes as `deployment.files`."""

    deployment: Deployment
    files: Mapping[str, bytes]


@dataclass(frozen=True)
class NodeState:
    """One runtime node as `inspect` saw it."""

    name: str
    handle: str
    incarnation: str | None
    address: str | None
    running: bool


@dataclass(frozen=True)
class Inspection:
    """What the runtime holds of a twin, and its nodes. `state` is `absent` when the runtime
    holds nothing of the twin; `present` when it holds at least one of the twin's nodes; and
    `residue` when it holds no node, but leftovers of the twin's isolation unit from a
    destroyed or killed lab (the local driver's host entries, ssh config or management
    network; on clabernetes, the twin's namespace holding none of its pods)."""

    state: Literal["absent", "present", "residue"]
    nodes: tuple[NodeState, ...]


Action = Literal["kept", "added", "removed", "recabled", "restarted", "recreated", "unsupported"]
"""What the runtime does to a node in a step: `recabled` changes its links and the node stays,
`restarted` is a link change under a restart link mode, `recreated` makes the node anew, and
`unsupported` is a change the runtime cannot satisfy."""

ChangeReason = Literal["kind", "image", "link_mode", "exec", "links", "hot_add"]
"""Why a kept node is not simply `kept`: a member of its node differs (`kind`, `image`,
`link_mode`), its start-up lines do (`exec`), its links do (`links`), or a port is added after
boot to a kind that cannot add one (`hot_add`)."""


@dataclass(frozen=True, kw_only=True)
class NodeChange:
    """What a step does to one node, and why; `reasons` are sorted, and empty for a node that is
    `kept`, `added` or `removed`."""

    node: str
    action: Action
    reasons: tuple[ChangeReason, ...]


@dataclass(frozen=True, kw_only=True)
class Changes:
    """What `changes` answers: every node of either deployment by name, and the links added and
    removed. A link is its two endpoints `node:port` in the topology's runtime names, the pair
    sorted; the lists are sorted."""

    nodes: tuple[NodeChange, ...]
    links_added: tuple[tuple[str, str], ...]
    links_removed: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Exec:
    """What `exec` answers: the command's exit status and the tail of its stdout and stderr."""

    returncode: int
    stdout: str
    stderr: str


def restarts(changes: Changes) -> tuple[str, ...]:
    """The nodes the runtime restarts or recreates: what `allow_restart` must cover."""
    return tuple(n.node for n in changes.nodes if n.action in ("restarted", "recreated"))


def relinks(changes: Changes) -> bool:
    """Whether the step changes any link: one added or removed, or a node recabled."""
    return bool(changes.links_added or changes.links_removed) or any(n.action == "recabled" for n in changes.nodes)


def unsupported(changes: Changes) -> tuple[str, ...]:
    """The nodes whose change the runtime cannot satisfy."""
    return tuple(n.node for n in changes.nodes if n.action == "unsupported")


def check_files(deployment: Deployment, files: Mapping[str, bytes]) -> None:
    """`ValueError`, the caller's error, unless `files` are exactly the deployment's, each with
    the SHA-256 it lists: what each driver's `apply` and `destroy` check before they act."""
    listed = {f.path: f.sha256 for f in deployment.files}
    if set(files) != set(listed):
        raise ValueError(f"the files {sorted(files)} are not the deployment's {sorted(listed)}")
    for path, data in sorted(files.items()):
        if hashlib.sha256(data).hexdigest() != listed[path]:
            raise ValueError(f"{path} is not the deployment's: its SHA-256 differs from the one {deployment.id} lists")


class Driver(Protocol):
    """A runtime behind the seam. `apply` and `destroy` take the packages, as `admit` and
    `plan` do: a deploy's and a destroy's budgets are the measured timeouts of the packages
    the deployment's nodes use, which neither the deployment nor its files carry. The five
    calls that act on the runtime, `admit`, `apply`, `inspect`, `destroy` and `exec`, raise
    `DriverFailed` for a runtime failure; `events`, which follows the runtime, is the one that
    raises nothing: it starts its own source again."""

    name: str

    def capabilities(self) -> Capabilities:
        """What this driver declares of its runtime."""
        ...

    async def admit(
        self,
        manifest: Manifest,
        platforms: Mapping[str, PlatformPackage],
        probe_packages: Mapping[str, ProbePackage],
        twin: str,
        reserved: Sequence[Allocation],
        held: Deployment | None = None,
    ) -> Allocation | Refusal:
        """Admit the twin or refuse it; `reserved` is every other twin's recorded allocation.

        `held` is the deployment a stepping twin has applied (D-049): the twin keeps its lab and
        subnet, so the answer is `held.allocation`, and the capacity checked is the demand the
        manifest adds over `held.demand`. Without it, the twin is new and gets a fresh allocation."""
        ...

    def plan(
        self,
        manifest: Manifest,
        bundle_id: str,
        platforms: Mapping[str, PlatformPackage],
        probe_packages: Mapping[str, ProbePackage],
        twin: str,
        allocation: Allocation,
    ) -> Planned:
        """Pure: bind the bundle (named by its content address `bundle_id`) to the twin, or
        raise `Unplannable` with every fault."""
        ...

    def changes(
        self,
        before: Planned,
        after: Planned,
        platforms: Mapping[str, PlatformPackage],
        probe_packages: Mapping[str, ProbePackage],
    ) -> Changes:
        """Pure: what the runtime does to each node to go from the deployment `before` to
        `after`, both one twin's, with the links added and removed (D-049). `ValueError` for
        deployments of two twins, or for a node no given package runs."""
        ...

    async def apply(
        self,
        deployment: Deployment,
        files: Mapping[str, bytes],
        platforms: Mapping[str, PlatformPackage],
        probe_packages: Mapping[str, ProbePackage],
        reconfigure: bool = False,
    ) -> None:
        """Make the runtime hold the deployment. `reconfigure` rebuilds the whole lab: every
        node is made anew, so every node's incarnation changes and every node's `holds` is
        void. It is the loop's remedy for a node that stays silent (D-023), asked only of a
        driver that does not declare `reapply` (D-068)."""
        ...

    async def inspect(self, twin: str) -> Inspection:
        """What the runtime holds of the twin."""
        ...

    async def destroy(
        self,
        deployment: Deployment,
        files: Mapping[str, bytes],
        platforms: Mapping[str, PlatformPackage],
        probe_packages: Mapping[str, ProbePackage],
    ) -> None:
        """Remove the deployment and its residue from the runtime."""
        ...

    async def endpoints(self, twin: str) -> Mapping[str, str]:
        """Node name to management address."""
        ...

    async def exec(self, twin: str, node: str, argv: Sequence[str], timeout_s: float) -> Exec:
        """Run `argv` inside `node`, no shell, within `timeout_s`; the exit status and the
        output's tail. `DriverFailed` when the node cannot be reached or the budget runs out."""
        ...

    def events(self) -> AsyncIterator[str]:
        """The names of the twins whose runtime state may have changed, as the runtime reports
        them (D-058): a node started, stopped, replaced or gone. A name is all it carries to the
        loop: the loop is level-triggered and `inspect` tells it what is true, so an event's
        detail would be a second, staler account. A driver may also act on what its source
        reports where only the runtime can mend a node: the clabernetes driver deletes a pod
        whose container ended or restarted in it before it names the twin, so the cluster makes
        the node anew (D-070). It ends only when cancelled, and raises nothing for a source that
        failed (no `DriverFailed`): it starts its source again after `events_backoff(previous)`
        (1 s, then twice the last, at most 60 s; the first name the source itself yields after a
        restart resets it, and a name from a listing the driver takes beside it does not, so a
        listing that works does not cut short the backoff of a source that fails again). After a
        restart it names every twin it holds that its source can name, since a change may have
        been missed meanwhile: the clabernetes source names a twin by its pods, so a twin whose
        every pod went is named by the loop's resync alone. A name it cannot read as a twin name
        (`store.check_twin_name` raises) is dropped below the seam. Each driver writes it as an
        asynchronous generator; it is declared with `def`, since `async def` here would type a
        coroutine answering an iterator."""
        ...
