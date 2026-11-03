"""The local driver: a twin as a containerlab lab on this host, behind the seam (D-017, D-018,
D-019, D-043).

The pure half is `plan` and `pool`; this is the live half. It reaches Docker and containerlab
through their CLIs alone, run by `runner` (`cli.run`, which logs every command line), so the
pure tier stands a fake in for both. The driver's working files live under
`<root>/containerlab/<twin>/`, `root` being the directory the server gives it.

`admit` reserves what `plan` binds: a /24 of the pool that no Docker network and no other
twin's allocation holds. It refuses a twin the host cannot fit (`admission.capacity`: the
pool exhausted, or the demand above the host's available memory or its CPU count), and one
whose account-gated image is not on the host (`admission.image.absent`), since locally a
`pull_secret` is a presence check and the image is never pulled (D-015). An ungated image is
containerlab's to pull at deploy.
"""

from __future__ import annotations

import ipaddress
import json
import logging
import os
from collections.abc import Awaitable, Callable, Mapping, Sequence
from ipaddress import IPv4Network
from pathlib import Path

from fylgja_core import containerlab
from fylgja_core.bundle import Manifest
from fylgja_core.containerlab import cli, pool
from fylgja_core.containerlab import plan as clab_plan
from fylgja_core.driver import Allocation, Capabilities, Planned, Refusal
from fylgja_core.platform_package import Image, PlatformPackage
from fylgja_core.probe_package import ProbePackage

# Rule ids. Clients and tests match on them; the catalogue is docs/rules.md.
RULE_CAPACITY = "admission.capacity"
RULE_IMAGE = "admission.image.absent"

DOCKER_TIMEOUT_S = 30.0
"""The budget of one `docker` read."""

_log = logging.getLogger("fylgja.containerlab")


class ContainerlabDriver:
    """The local driver. `runner` runs a command line and answers its stdout, as `cli.run`
    does; `meminfo` and `cpus` are the host's capacity (`/proc/meminfo`'s `MemAvailable`, and
    `os.cpu_count()` when None). All three are injectable, for the pure tier."""

    name = containerlab.NAME

    def __init__(
        self,
        root: Path,
        *,
        pool: IPv4Network = pool.DEFAULT_POOL,
        runner: Callable[..., Awaitable[str]] = cli.run,
        meminfo: Path = Path("/proc/meminfo"),
        cpus: int | None = None,
    ) -> None:
        self.root = Path(root).absolute()
        self.pool = pool
        self._run = runner
        self._meminfo = meminfo
        self._cpus = cpus

    def capabilities(self) -> Capabilities:
        return containerlab.CAPABILITIES

    def plan(
        self,
        manifest: Manifest,
        bundle_id: str,
        platforms: Mapping[str, PlatformPackage],
        probe_packages: Mapping[str, ProbePackage],
        twin: str,
        allocation: Allocation,
    ) -> Planned:
        return clab_plan.plan(manifest, bundle_id, platforms, probe_packages, twin, allocation)

    async def admit(
        self,
        manifest: Manifest,
        platforms: Mapping[str, PlatformPackage],
        probe_packages: Mapping[str, ProbePackage],
        twin: str,
        reserved: Sequence[Allocation],
    ) -> Allocation | Refusal:
        """The first free /24 of the pool as the twin's allocation, or a refusal naming every
        shortfall (`admission.capacity`) or every absent gated image (`admission.image.absent`)."""
        taken = await self._docker_subnets() + [IPv4Network(a["mgmt_subnet"]) for a in reserved]
        subnet = pool.choose(self.pool, taken)
        demand = clab_plan.demand(manifest, platforms, probe_packages)
        shortfalls = []
        if subnet is None:
            shortfalls.append(f"The pool {self.pool} has no /24 that neither a Docker network nor another twin holds.")
        available = self._memory_available_mib()
        if demand.memory_mb > available:
            shortfalls.append(f"The twin needs {demand.memory_mb} MiB of memory, and the host has {available} MiB "
                              "available.")
        cpus = self._cpus if self._cpus is not None else os.cpu_count()
        if cpus is not None and demand.cpu > cpus:
            shortfalls.append(f"The twin needs {demand.cpu:g} CPUs, and the host has {cpus}.")
        if shortfalls or subnet is None:
            return _refuse(twin, RULE_CAPACITY, " ".join(shortfalls))
        absent = [(package, image) for package, image in _images(manifest, platforms, probe_packages)
                  if image.pull_secret is not None and not await self._image_present(image.ref)]
        if absent:
            return _refuse(twin, RULE_IMAGE, " ".join(
                f"The image {image.ref} ({package}) is account-gated and not on the host, and the local driver "
                "never pulls it: import it under that tag." for package, image in absent))
        _log.info("admit %s: subnet %s; demand %d nodes, %g CPU, %d MiB",
                  twin, subnet, demand.nodes, demand.cpu, demand.memory_mb)
        return pool.allocation(twin, subnet)

    async def _docker_subnets(self) -> list[IPv4Network]:
        """Every IPv4 subnet a Docker network on the host holds."""
        ids = (await self._run(["docker", "network", "ls", "--format", "{{.ID}}"], timeout_s=DOCKER_TIMEOUT_S)).split()
        if not ids:
            return []
        configs = await self._run(["docker", "network", "inspect", "--format", "{{json .IPAM.Config}}", *ids],
                                  timeout_s=DOCKER_TIMEOUT_S)
        subnets = []
        for line in configs.splitlines():  # one network's config per line: a list, or null for none
            for config in (json.loads(line) if line.strip() else None) or []:
                network = ipaddress.ip_network(config["Subnet"], strict=False) if config.get("Subnet") else None
                if isinstance(network, IPv4Network):
                    subnets.append(network)
        return subnets

    async def _image_present(self, ref: str) -> bool:
        """Whether Docker holds the image `ref`; a hung `docker` is a driver error, not an absence."""
        try:
            await self._run(["docker", "image", "inspect", "--format", "{{.Id}}", ref], timeout_s=DOCKER_TIMEOUT_S)
        except cli.CommandFailed as e:
            if e.returncode == cli.TIMED_OUT:
                raise
            return False
        return True

    def _memory_available_mib(self) -> int:
        """The host's `MemAvailable`, in MiB."""
        for line in self._meminfo.read_text().splitlines():
            key, _, value = line.partition(":")
            if key == "MemAvailable":
                return int(value.split()[0]) // 1024  # the kernel writes kB, which are KiB
        raise ValueError(f"{self._meminfo} has no MemAvailable")


def _images(
    manifest: Manifest, platforms: Mapping[str, PlatformPackage], probe_packages: Mapping[str, ProbePackage]
) -> list[tuple[str, Image]]:
    """Each package the twin's nodes use, by id or format, with its image: the platforms in
    order, then the probe formats."""
    used = sorted({node.platform for node in manifest.nodes})
    formats = sorted({probe.format for probe in manifest.probes})
    return [(p, platforms[p].runtime.containerlab.image) for p in used] + [
        (f, probe_packages[f].runtime.containerlab.image) for f in formats]


def _refuse(twin: str, rule: str, message: str) -> Refusal:
    _log.info("admit %s refused, %s: %s", twin, rule, message)
    return Refusal(rule, message)
