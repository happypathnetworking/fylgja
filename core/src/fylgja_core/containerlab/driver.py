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

`apply` writes the deployment's files, each checked against its hash, into the twin's
directory and deploys the topology: on a running lab that is containerlab's own reconcile,
and `reconfigure` is the loop's remedy for a partial lab (D-023). A deploy's budget, and a
destroy's, is the slowest package the topology's nodes use, plus a minute.

`inspect` finds the twin's containers by containerlab's label `containerlab=<lab>` and reads
each one's node name from the label `clab-node-name`, its incarnation from `State.StartedAt`
and its address on the lab's management network, `clab-<twin>`. Those keys are the ones
containerlab 0.79.0 was seen to set (verified-facts.md); the live tier verifies them on the
running version. With no container, what a killed destroy leaves is residue: the lab's block
of `/etc/hosts` entries, its ssh config `clab-<twin>.conf`, or its management network.
`destroy` removes everything; the root-owned residue only containerlab can clear, so finding
it and no container it deploys, then destroys (recovery rule 2, D-019, D-023), while a
network left alone, as a deploy refused at its start leaves it, is removed with `docker`.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import os
import secrets
import shutil
from collections.abc import Awaitable, Callable, Mapping, Sequence
from ipaddress import IPv4Network
from pathlib import Path
from typing import Any

import yaml

from fylgja_core import containerlab, platform_package, probe_package
from fylgja_core.bundle import Manifest
from fylgja_core.containerlab import cli, pool
from fylgja_core.containerlab import plan as clab_plan
from fylgja_core.containerlab.plan import TOPOLOGY
from fylgja_core.deployment import Deployment
from fylgja_core.driver import Allocation, Capabilities, Inspection, NodeState, Planned, Refusal
from fylgja_core.platform_package import Image, PlatformPackage
from fylgja_core.probe_package import ProbePackage
from fylgja_core.store import check_file_key, check_twin_name

# Rule ids. Clients and tests match on them; the catalogue is docs/rules.md.
RULE_CAPACITY = "admission.capacity"
RULE_IMAGE = "admission.image.absent"

DOCKER_TIMEOUT_S = 30.0
"""The budget of one `docker` read."""

MARGIN_S = 60.0
"""What a deploy's or a destroy's budget adds to its slowest package's timeout, for containerlab's own work."""

NEVER_STARTED = "0001-01-01T00:00:00Z"
"""Docker's `State.StartedAt` for a container created and never started: no incarnation."""

_log = logging.getLogger("fylgja.containerlab")


class ContainerlabDriver:
    """The local driver. `runner` runs a command line and answers its stdout, as `cli.run`
    does; `meminfo` and `cpus` are the host's capacity (`/proc/meminfo`'s `MemAvailable`, and
    `os.cpu_count()` when None); `hosts_path` and `ssh_config_dir` are where containerlab
    writes a lab's host entries and ssh config. All are injectable, for the pure tier."""

    name = containerlab.NAME

    def __init__(
        self,
        root: Path,
        *,
        pool: IPv4Network = pool.DEFAULT_POOL,
        runner: Callable[..., Awaitable[str]] = cli.run,
        meminfo: Path = Path("/proc/meminfo"),
        cpus: int | None = None,
        hosts_path: Path = Path("/etc/hosts"),
        ssh_config_dir: Path = Path("/etc/ssh/ssh_config.d"),
    ) -> None:
        self.root = Path(root).absolute()
        self.pool = pool
        self._run = runner
        self._meminfo = meminfo
        self._cpus = cpus
        self._hosts_path = hosts_path
        self._ssh_config_dir = ssh_config_dir

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
        shortfall (`admission.capacity`) or every absent gated image (`admission.image.absent`).

        The contract: the loop admits a twin once and records the allocation in its record; a
        resume plans with the recorded allocation and never admits again. So the twin's own
        management network, which holds its subnet once deployed, never counts against it."""
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

    async def apply(
        self,
        deployment: Deployment,
        files: Mapping[str, bytes],
        platforms: Mapping[str, PlatformPackage],
        probe_packages: Mapping[str, ProbePackage],
        reconfigure: bool = False,
    ) -> None:
        """Write the deployment's files under the twin's directory and deploy its topology, with
        `--reconfigure` when asked; `ValueError`, before any write or command, for files that are
        not the deployment's or a node no given package runs."""
        _check_files(deployment, files)
        budget = deploy_budget(files, platforms, probe_packages)
        directory = self._write(deployment.twin, files)
        argv = ["containerlab", "deploy", "-t", str(directory / TOPOLOGY)]
        await self._run([*argv, "--reconfigure"] if reconfigure else argv, timeout_s=budget, cwd=directory)

    async def inspect(self, twin: str) -> Inspection:
        """The twin's containers, by node name, `present` when there is one; else `residue` when
        the twin's host entries, ssh config or management network remain, and `absent`."""
        names = (await self._run(
            ["docker", "ps", "-a", "--filter", f"label=containerlab={twin}", "--format", "{{.Names}}"],
            timeout_s=DOCKER_TIMEOUT_S)).split()
        if names:
            found = json.loads(await self._run(["docker", "inspect", "--type", "container", *names],
                                               timeout_s=DOCKER_TIMEOUT_S))
            nodes = sorted((_node(twin, doc) for doc in found), key=lambda n: n.name)
            return Inspection(state="present", nodes=tuple(nodes))
        residue = self._root_owned_residue(twin) or await self._network_exists(twin)
        return Inspection(state="residue" if residue else "absent", nodes=())

    async def destroy(
        self,
        deployment: Deployment,
        files: Mapping[str, bytes],
        platforms: Mapping[str, PlatformPackage],
        probe_packages: Mapping[str, ProbePackage],
    ) -> None:
        """Remove everything the twin holds: its containers, host entries, ssh config and
        management network, and the twin's directory. Root-owned residue with no container is
        deployed, then destroyed (rule 2); nothing found is nothing done. `ValueError`, before
        any command, for files that are not the deployment's."""
        _check_files(deployment, files)
        twin = deployment.twin
        budget = destroy_budget(files, platforms, probe_packages)
        inspection = await self.inspect(twin)
        lab = inspection.state == "present"
        if inspection.state == "residue" and self._root_owned_residue(twin):
            _log.info("destroy %s: residue and no container: deploy, then destroy (D-023)", twin)
            await self.apply(deployment, files, platforms, probe_packages)
            lab = True
        if lab:
            directory = self._write(twin, files)
            await self._run(["containerlab", "destroy", "-t", str(directory / TOPOLOGY), "--cleanup"],
                            timeout_s=budget, cwd=directory)
        if inspection.state != "absent" and await self._network_exists(twin):
            await self._run(["docker", "network", "rm", f"clab-{twin}"], timeout_s=DOCKER_TIMEOUT_S)
        if self._directory(twin).exists():
            shutil.rmtree(self._directory(twin))

    async def endpoints(self, twin: str) -> Mapping[str, str]:
        """Each running node's management address, by node name; a node without one is left out."""
        inspection = await self.inspect(twin)
        return {n.name: n.address for n in sorted(inspection.nodes, key=lambda n: n.name) if n.running and n.address}

    def _directory(self, twin: str) -> Path:
        """The twin's working directory; containerlab makes the lab's own, `clab-<twin>/`, inside it."""
        return self.root / "containerlab" / check_twin_name(twin)

    def _write(self, twin: str, files: Mapping[str, bytes]) -> Path:
        """Write `files` under the twin's directory, each whole or not at all; the directory."""
        directory = self._directory(twin)
        for path, data in sorted(files.items()):
            target = directory / path
            target.parent.mkdir(parents=True, exist_ok=True)
            _write_atomic(target, data)
        return directory

    def _root_owned_residue(self, twin: str) -> bool:
        """Whether the lab's block of host entries or its ssh config remains: what containerlab
        writes as root, and only its destroy clears. A block is opened by a line naming its lab
        exactly, so the twin `t-2`'s entries (`clab-t-2-n1`) are never taken for `t`'s; the
        marker is the format string in the containerlab 0.81.0 binary, which the live tier
        verifies on a running lab."""
        start = f"###### CLAB-{twin}-START ######"
        hosts = self._hosts_path.read_text() if self._hosts_path.exists() else ""
        return any(line.strip() == start for line in hosts.splitlines()) or (
            self._ssh_config_dir / f"clab-{twin}.conf").exists()

    async def _network_exists(self, twin: str) -> bool:
        """Whether the lab's management network exists; a hung `docker` is a driver error."""
        try:
            await self._run(["docker", "network", "inspect", f"clab-{twin}"], timeout_s=DOCKER_TIMEOUT_S)
        except cli.CommandFailed as e:
            if e.returncode == cli.TIMED_OUT:
                raise
            return False
        return True

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


def deploy_budget(
    files: Mapping[str, bytes], platforms: Mapping[str, PlatformPackage], probe_packages: Mapping[str, ProbePackage]
) -> float:
    """The budget of a deploy of `files`: the largest `deploy_timeout_s` of the packages the
    topology's nodes use, since nodes deploy in parallel, plus `MARGIN_S`."""
    return max(section.deploy_timeout_s for section in _sections(files, platforms, probe_packages)) + MARGIN_S


def destroy_budget(
    files: Mapping[str, bytes], platforms: Mapping[str, PlatformPackage], probe_packages: Mapping[str, ProbePackage]
) -> float:
    """The budget of a destroy of `files`: the largest `destroy_timeout_s` of the packages the
    topology's nodes use, plus `MARGIN_S`."""
    return max(section.destroy_timeout_s for section in _sections(files, platforms, probe_packages)) + MARGIN_S


def _node(twin: str, doc: Mapping[str, Any]) -> NodeState:
    """A node from its container's `docker inspect` member; its address is the one it holds
    on the lab's management network while it runs."""
    running = bool(doc["State"]["Running"])
    started = doc["State"]["StartedAt"]
    network = (doc["NetworkSettings"]["Networks"] or {}).get(f"clab-{twin}") or {}
    return NodeState(
        name=doc["Config"]["Labels"]["clab-node-name"],
        handle=doc["Name"].lstrip("/"),
        incarnation=None if started == NEVER_STARTED else started,
        address=(network.get("IPAddress") or None) if running else None,
        running=running,
    )


def _sections(
    files: Mapping[str, bytes], platforms: Mapping[str, PlatformPackage], probe_packages: Mapping[str, ProbePackage]
) -> list[platform_package.Containerlab | probe_package.Containerlab]:
    """The containerlab section of each package a node of the topology uses: a platform's by
    the node's kind and image, a probe package's by a linux node's image. The deployment does
    not name its packages, and its topology, the plan's render, does. `ValueError` for a node
    no given package runs."""
    used: list[platform_package.Containerlab | probe_package.Containerlab] = []
    for name, node in yaml.safe_load(files[TOPOLOGY])["topology"]["nodes"].items():
        kind, image = node["kind"], node["image"]
        sections: list[platform_package.Containerlab | probe_package.Containerlab] = [
            p.runtime.containerlab for p in platforms.values()
            if (p.runtime.containerlab.kind, p.runtime.containerlab.image.ref) == (kind, image)]
        if kind == "linux":
            sections += [q.runtime.containerlab for q in probe_packages.values()
                         if q.runtime.containerlab.image.ref == image]
        if not sections:
            raise ValueError(f"no package given runs the node {name} ({kind}, {image})")
        used += sections
    return used


def _check_files(deployment: Deployment, files: Mapping[str, bytes]) -> None:
    """`ValueError` unless `files` are exactly the deployment's, each with the SHA-256 it lists."""
    listed = {f.path: f.sha256 for f in deployment.files}
    if set(files) != set(listed):
        raise ValueError(f"the files {sorted(files)} are not the deployment's {sorted(listed)}")
    for path, data in files.items():
        check_file_key(path)
        if hashlib.sha256(data).hexdigest() != listed[path]:
            raise ValueError(f"{path} is not the deployment's: its SHA-256 differs from the one {deployment.id} lists")
    if TOPOLOGY not in files:
        raise ValueError(f"the deployment {deployment.id} lists no {TOPOLOGY}")


def _write_atomic(path: Path, data: bytes) -> None:
    """Replace `path` with `data`, whole or not at all, as the local store writes: a fsynced
    temporary file beside it, renamed into place, and the directory fsynced."""
    temp = path.parent / f".tmp-{secrets.token_hex(8)}"
    try:
        with temp.open("xb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


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
