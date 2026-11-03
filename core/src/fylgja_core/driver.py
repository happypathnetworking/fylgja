"""The driver seam: the seven calls a runtime answers (Constitution XIII, D-017).

Everything above the seam calls these and nothing else; nothing above it names a runtime.
Every call is idempotent. `plan` is synchronous and pure: it is the only binding of a bundle
to a twin and a runtime (D-011), and returns the `Deployment` and the rendered files it
describes, or raises `Unplannable` when the runtime cannot hold the bundle as compiled. The
other calls act on the runtime and are `async`.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
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


@dataclass(frozen=True, kw_only=True)
class Capabilities:
    """What a driver declares of its runtime; the API lists it (api-1 Driver)."""

    nodes: Literal["provisions", "claims"]
    relink: bool
    forwarding: Literal["software", "hardware"]
    access: Literal["direct", "proxied"]
    isolation: Literal["names", "network"]


@dataclass(frozen=True)
class Refusal:
    """What `admit` answers when it refuses; `rule` is `admission.capacity` or another `admission.*` rule."""

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
    network)."""

    state: Literal["absent", "present", "residue"]
    nodes: tuple[NodeState, ...]


class Driver(Protocol):
    """A runtime behind the seam."""

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
    ) -> Allocation | Refusal:
        """Admit the twin or refuse it; `reserved` is every other twin's recorded allocation."""
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

    async def apply(self, deployment: Deployment, files: Mapping[str, bytes], reconfigure: bool = False) -> None:
        """Make the runtime hold the deployment."""
        ...

    async def inspect(self, twin: str) -> Inspection:
        """What the runtime holds of the twin."""
        ...

    async def destroy(self, deployment: Deployment, files: Mapping[str, bytes]) -> None:
        """Remove the deployment and its residue from the runtime."""
        ...

    async def endpoints(self, twin: str) -> Mapping[str, str]:
        """Node name to management address."""
        ...
