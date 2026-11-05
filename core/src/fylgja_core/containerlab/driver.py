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
destroy's, is the slowest package the topology's nodes use, plus a minute. A core killed during
a deploy leaves its `containerlab deploy` running in a session of its own (`cli.run` starts each
command so, and a kill of the core does not reach it), and it runs to completion: its stdout and
stderr go to `deploy.log` in the twin's directory, not into pipes the core holds, since
containerlab dies of SIGPIPE once a pipe's reader is gone (D-056, verified-facts.md).
A step's resume applies again plainly, so before it acts `apply` waits, within the deploy's
budget, for every `containerlab deploy` of the twin's topology still running to end (`strays`, a
scan of `/proc`): two deploys never run on one lab at once. `destroy` waits so too, within the
budget of the deployment it destroys, since a deletion asked after such a kill would otherwise
tear down a lab the deploy goes on making. The pure tier holds `apply`'s wait; the live tier
holds `destroy`'s, with a deletion asked right after a kill mid-deploy (D-055). `apply`'s has
not fired live: each stray had ended before a step's resume reached its apply (D-056).

`inspect` finds the twin's containers by containerlab's label `containerlab=<lab>` and reads
each one's node name from the label `clab-node-name`, its incarnation from `State.StartedAt`
and its address on the lab's management network, `clab-<twin>`. Those keys are the ones
containerlab 0.79.0 was seen to set (verified-facts.md); the live tier verifies them on the
running version. With no container, what a killed destroy leaves is residue: the lab's block
of `/etc/hosts` entries, its ssh config `clab-<twin>.conf`, or its management network.
`destroy` removes everything; the root-owned residue only containerlab can clear, so finding
it and no container it deploys, then destroys (recovery rule 2, D-019, D-023), while a
network left alone, as a deploy refused at its start leaves it, is removed with `docker`.
containerlab's `destroy -t` removes only the nodes its file names, so a container of the lab
the deployment destroyed does not name (one a step's deploy, cut short, added) is removed with
`docker` first (D-055).
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import os
import secrets
import shutil
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from ipaddress import IPv4Network
from pathlib import Path
from typing import Any

import yaml

from fylgja_core import containerlab, platform_package, probe_package
from fylgja_core.bundle import Manifest
from fylgja_core.containerlab import changes as clab_changes
from fylgja_core.containerlab import cli, pool
from fylgja_core.containerlab import plan as clab_plan
from fylgja_core.containerlab.plan import TOPOLOGY
from fylgja_core.deployment import Demand, Deployment
from fylgja_core.driver import (
    Allocation,
    Capabilities,
    Changes,
    DriverFailed,
    Exec,
    Inspection,
    NodeState,
    Planned,
    Refusal,
)
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

EXEC_OUTPUT_KEPT = 65536
"""How many bytes of each of an `exec`'s outputs the driver keeps: the last."""

DOCKER_EXEC_UNREACHED = (125, 126, 127)
"""The statuses `docker exec` itself gives when it could not run the command: the daemon failed,
the command cannot be invoked, or it was not found. A missing or stopped container is not among
them: docker exits 1 and writes `DOCKER_DAEMON_ERRORS` at the start of stderr, which is also
`DriverFailed`. Docker 29.8.1 writes `Error response from daemon: No such container: <name>` for
a missing one (verified-facts.md, phase 5's block)."""

DOCKER_DAEMON_ERRORS = ("Error response from daemon:", "Error: No such container")
"""What stderr starts with when docker, not the command, failed, whatever the status."""

NEVER_STARTED = "0001-01-01T00:00:00Z"
"""Docker's `State.StartedAt` for a container created and never started: no incarnation."""

STRAY_POLL_S = 1.0
"""How often `apply` and `destroy` look again for a stray deploy of the twin to have ended."""

DEPLOY_LOG = "deploy.log"
"""The file in the twin's directory that holds the last deploy's stdout and stderr (D-056): the
deploy writes there and not into pipes the core holds, so a deploy orphaned by a killed core runs
to completion. It is beside the topology it describes, never logged, and removed with the directory."""

_log = logging.getLogger("fylgja.containerlab")


def stray_deploys(topology: str, proc: Path = Path("/proc")) -> list[int]:
    """The pids of the `containerlab deploy` processes running whose command line names the
    topology file `topology`, read from `proc` as the live tier reads it: a deploy a killed core
    left running in its own session. A process that ends while it is read is passed over, and so
    is a zombie, whose command line reads empty."""
    found = []
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            argv = [word.decode(errors="replace") for word in (entry / "cmdline").read_bytes().split(b"\0")]
        except OSError:
            continue
        if Path(argv[0]).name == "containerlab" and "deploy" in argv[1:] and topology in argv:
            found.append(int(entry.name))
    return sorted(found)


class ContainerlabDriver:
    """The local driver. `runner` runs a command line and answers its stdout, as `cli.run`
    does; `meminfo` and `cpus` are the host's capacity (`/proc/meminfo`'s `MemAvailable`, and
    `os.cpu_count()` when None); `hosts_path` and `ssh_config_dir` are where containerlab
    writes a lab's host entries and ssh config; `strays` answers the pids of the `containerlab
    deploy` processes running over a topology file (`stray_deploys`), and `stray_poll_s` is how
    often `apply` and `destroy` ask it again. All are injectable, for the pure tier."""

    name = containerlab.NAME

    def __init__(
        self,
        root: Path,
        *,
        pool: IPv4Network = pool.DEFAULT_POOL,
        runner: Callable[..., Awaitable[str]] = cli.run,
        status_runner: Callable[..., Awaitable[tuple[int, str, str]]] = cli.run_status,
        meminfo: Path = Path("/proc/meminfo"),
        cpus: int | None = None,
        hosts_path: Path = Path("/etc/hosts"),
        ssh_config_dir: Path = Path("/etc/ssh/ssh_config.d"),
        strays: Callable[[str], list[int]] = stray_deploys,
        stray_poll_s: float = STRAY_POLL_S,
    ) -> None:
        self.root = Path(root).absolute()
        self.pool = pool
        self._run = runner
        self._run_status = status_runner
        self._meminfo = meminfo
        self._cpus = cpus
        self._hosts_path = hosts_path
        self._ssh_config_dir = ssh_config_dir
        self._strays = strays
        self._stray_poll_s = stray_poll_s

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

    def changes(
        self,
        before: Planned,
        after: Planned,
        platforms: Mapping[str, PlatformPackage],
        probe_packages: Mapping[str, ProbePackage],
    ) -> Changes:
        return clab_changes.changes(before, after, platforms, probe_packages)

    async def admit(
        self,
        manifest: Manifest,
        platforms: Mapping[str, PlatformPackage],
        probe_packages: Mapping[str, ProbePackage],
        twin: str,
        reserved: Sequence[Allocation],
        held: Deployment | None = None,
    ) -> Allocation | Refusal:
        """The first free /24 of the pool as the twin's allocation, or a refusal naming every
        shortfall (`admission.capacity`) or every absent gated image (`admission.image.absent`).

        With `held`, the deployment a stepping twin has applied, the answer is `held.allocation`
        unchanged: the twin keeps its lab and subnet, so the pool and the Docker networks are not
        consulted. The capacity checked is the demand the manifest adds over `held.demand`, per
        component and floored at zero; every gated image the manifest's packages use is checked
        for presence (D-049).

        The contract: the loop admits a twin once and records the allocation in its record; a
        resume plans with the recorded allocation and never admits again. So the twin's own
        management network, which holds its subnet once deployed, never counts against it."""
        demand = clab_plan.demand(manifest, platforms, probe_packages)
        shortfalls = []
        subnet = None
        if held is None:
            taken = await self._docker_subnets() + [IPv4Network(a["mgmt_subnet"]) for a in reserved]
            subnet = pool.choose(self.pool, taken)
            if subnet is None:
                shortfalls.append(
                    f"The pool {self.pool} has no /24 that neither a Docker network nor another twin holds.")
            needs, verb = demand, "The twin needs"
        else:
            needs = Demand(nodes=max(0, demand.nodes - held.demand.nodes),
                           cpu=max(0.0, demand.cpu - held.demand.cpu),
                           memory_mb=max(0, demand.memory_mb - held.demand.memory_mb))
            verb = "The step adds"
        available = self._memory_available_mib()
        if needs.memory_mb > available:
            shortfalls.append(f"{verb} {needs.memory_mb} MiB of memory, and the host has {available} MiB "
                              "available.")
        cpus = self._cpus if self._cpus is not None else os.cpu_count()
        if cpus is not None and needs.cpu > cpus:
            shortfalls.append(f"{verb} {needs.cpu:g} CPUs, and the host has {cpus}.")
        if shortfalls or (held is None and subnet is None):
            return _refuse(twin, RULE_CAPACITY, " ".join(shortfalls))
        absent = [(package, image) for package, image in _images(manifest, platforms, probe_packages)
                  if image.pull_secret is not None and not await self._image_present(image.ref)]
        if absent:
            return _refuse(twin, RULE_IMAGE, " ".join(
                f"The image {image.ref} ({package}) is account-gated and not on the host, and the local driver "
                "never pulls it: import it under that tag." for package, image in absent))
        if held is not None:
            _log.info("admit %s: held allocation %s; added demand %d nodes, %g CPU, %d MiB",
                      twin, held.allocation["mgmt_subnet"], needs.nodes, needs.cpu, needs.memory_mb)
            return dict(held.allocation)
        assert subnet is not None
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
        not the deployment's or a node no given package runs.

        Under containerlab's live link mode a port added after boot to a node whose kind cannot
        add one comes up in Linux and the node never lists it, so before the deploy the container
        of each node `changes` finds `recreated` for `hot_add` is removed (`docker rm -f`), and the
        deploy creates it anew with its ports (D-049). The previous topology is what the twin's
        directory holds, read before anything is removed or written; none, or `reconfigure` (which recreates
        every node), removes nothing. The comparison reads the topologies alone, so the before
        side carries this deployment as its member, `changes` checking only that it is one twin's.

        Before anything else, a `containerlab deploy` of the twin's topology still running (one a
        killed core left in its own session, by `strays`) is waited for, polled every
        `stray_poll_s` and logged once at INFO, so that a resume's deploy never runs beside it;
        one still running once the deploy's budget has passed is `DriverFailed`, the loop's to
        retry, with nothing written or run.

        The order is: wait for a stray deploy, read the previous topology, compute the changes,
        remove each hot-add container, write the new files, deploy. The on-disk topology is the record of what the lab
        was built from, so it moves only once the containers that must go are gone: a core killed
        before the write leaves the old topology, the retry computes the same hot-add, and the
        removal tolerates the containers already gone. Written first, a kill would leave a retry
        that sees no hot-add and deploys the port into a container never recreated.

        A previous topology `changes` cannot read (a corrupt file, or a node no given package
        runs) is `DriverFailed` naming the file and the cause, before any write or command. A
        container already gone is not a failure (see `_remove`)."""
        _check_files(deployment, files)
        budget = deploy_budget(files, platforms, probe_packages)
        twin = deployment.twin
        previous = self._directory(twin) / TOPOLOGY
        await self._await_strays(twin, previous, budget, "apply", "deploying")
        hot_added: list[str] = []
        if previous.is_file() and not reconfigure:
            try:
                diff = clab_changes.changes(
                    Planned(deployment, {TOPOLOGY: previous.read_bytes()}), Planned(deployment, dict(files)),
                    platforms, probe_packages)
            except Exception as e:
                raise DriverFailed(f"the twin {twin}'s previous topology {previous} cannot be compared: "
                                   f"{type(e).__name__}: {e}") from e
            hot_added = [n.node for n in diff.nodes if n.action == "recreated" and "hot_add" in n.reasons]
        for node in hot_added:
            await self._remove("apply", twin, node, f"clab-{twin}-{node}",
                               "since it gains a port its kind cannot add after boot")
        directory = self._write(twin, files)
        argv = ["containerlab", "deploy", "-t", str(directory / TOPOLOGY)]
        await self._run([*argv, "--reconfigure"] if reconfigure else argv, timeout_s=budget, cwd=directory,
                        log=directory / DEPLOY_LOG)

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
        any command, for files that are not the deployment's.

        Before anything else, a stray `containerlab deploy` of the twin's topology is waited for,
        as `apply` waits for one, within the deploy's budget: a core killed during a deploy and a
        deletion asked at once would otherwise read the lab, and tear it down, while the deploy
        still makes nodes. Then each container of the lab that the deployment's topology does not
        name is removed (`docker rm -f`) before containerlab's destroy, which removes only the
        nodes its file names (verified-facts.md, 0.81.0): a step whose apply was cut short before
        `applied` leaves the record naming the deployment it ran, and the node its deploy added
        would otherwise hold the management network (D-055).

        A command that fails (the destroy, rule 2's deploy, or the network's removal) raises
        `CommandFailed`, logged at WARNING, and leaves the rest undone: the next destroy finds
        what is left and goes on from there. A twin's directory that cannot be removed, such as a root-owned lab
        directory containerlab left, is logged at WARNING and left, so that it never wedges
        a destroy."""
        _check_files(deployment, files)
        twin = deployment.twin
        budget = destroy_budget(files, platforms, probe_packages)
        await self._await_strays(twin, self._directory(twin) / TOPOLOGY,
                                 deploy_budget(files, platforms, probe_packages), "destroy", "destroying")
        inspection = await self.inspect(twin)
        lab = inspection.state == "present"
        named = set(yaml.safe_load(files[TOPOLOGY])["topology"]["nodes"])
        try:
            if inspection.state == "residue" and self._root_owned_residue(twin):
                _log.info("destroy %s: residue and no container: deploy, then destroy (D-023)", twin)
                await self.apply(deployment, files, platforms, probe_packages)
                lab = True
            if lab:
                for node in sorted((n for n in inspection.nodes if n.name not in named), key=lambda n: n.name):
                    await self._remove("destroy", twin, node.name, node.handle,
                                       "since the deployment destroyed does not name it")
                directory = self._write(twin, files)
                await self._run(["containerlab", "destroy", "-t", str(directory / TOPOLOGY), "--cleanup"],
                                timeout_s=budget, cwd=directory)
            if inspection.state != "absent" and await self._network_exists(twin):
                await self._run(["docker", "network", "rm", f"clab-{twin}"], timeout_s=DOCKER_TIMEOUT_S)
        except cli.CommandFailed as e:
            _log.warning("destroy %s failed, and the next destroy finds what is left: %s", twin, e)
            raise
        directory = self._directory(twin)
        if directory.exists():
            try:
                shutil.rmtree(directory)
            except OSError as e:
                _log.warning("destroy %s: its directory %s is left: %s", twin, directory, e)

    async def endpoints(self, twin: str) -> Mapping[str, str]:
        """Each running node's management address, by node name; a node without one is left out."""
        inspection = await self.inspect(twin)
        return {n.name: n.address for n in sorted(inspection.nodes, key=lambda n: n.name) if n.running and n.address}

    async def exec(self, twin: str, node: str, argv: Sequence[str], timeout_s: float) -> Exec:
        """Run `argv` inside the node's container, `docker exec clab-<twin>-<node> <argv>`, no
        shell. A non-zero status is the command's answer, except that `DriverFailed` is raised
        for the statuses `docker exec` itself gives (125 to 127) and for a non-zero status whose
        stderr starts with a `DOCKER_DAEMON_ERRORS` text (a node that does not exist or is not
        running); the message names the handle and the status, never the output. A budget run
        out is `CommandFailed`.
        Each output is cut to its last `EXEC_OUTPUT_KEPT` bytes and never logged."""
        handle = f"clab-{check_twin_name(twin)}-{node}"
        returncode, stdout, stderr = await self._run_status(["docker", "exec", handle, *argv], timeout_s=timeout_s)
        if returncode in DOCKER_EXEC_UNREACHED or (returncode and stderr.startswith(DOCKER_DAEMON_ERRORS)):
            raise DriverFailed(f"docker exec into {handle} failed with status {returncode}")
        return Exec(returncode, _tail(stdout), _tail(stderr))

    def _directory(self, twin: str) -> Path:
        """The twin's working directory; containerlab makes the lab's own, `clab-<twin>/`, inside it."""
        return self.root / "containerlab" / check_twin_name(twin)

    async def _await_strays(self, twin: str, topology: Path, budget: float, operation: str, before: str) -> None:
        """Return once no `containerlab deploy` of `topology` runs, asking `strays` every
        `stray_poll_s`; the wait is logged once, at INFO, naming the `operation` and what it does
        `before`. `DriverFailed` when one still runs once `budget` seconds have passed: a deploy
        that outlives a deploy's budget is not waited out."""
        pids = self._strays(str(topology))
        if not pids:
            return
        _log.info("%s %s: a stray deploy of %s is still running (pid %s): waiting for it to end before %s",
                  operation, twin, twin, ", ".join(map(str, pids)), before)
        deadline = time.monotonic() + budget
        while pids:
            if time.monotonic() >= deadline:
                raise DriverFailed(f"a stray deploy of {twin} did not end within {budget:g}s "
                                   f"(pid {', '.join(map(str, pids))})")
            await asyncio.sleep(self._stray_poll_s)
            pids = self._strays(str(topology))

    async def _remove(self, operation: str, twin: str, node: str, handle: str, why: str) -> None:
        """`docker rm -f` the node's container, `handle` (the name `inspect` read under the lab's
        label, or the one containerlab gives it), logged with the `operation` and `why`. One already
        gone is fine: a core killed between this and the deploy resumes with the old topology on
        disk and asks again, and a destroy that failed after it is retried. Docker 29.8.1
        answers the removal of a missing container with status 0 and no output
        (verified-facts.md, phase 5's block); a non-zero status whose stderr says `No such
        container` is accepted too. Any other non-zero status is `CommandFailed`, its stderr cut to
        its last `cli.STDERR_KEPT` characters as `cli.run` cuts it."""
        argv = ["docker", "rm", "-f", handle]
        returncode, _, stderr = await self._run_status(argv, timeout_s=DOCKER_TIMEOUT_S)
        if returncode == 0:
            _log.info("%s %s: removed %s, or it was already gone (docker answers 0 for both), %s", operation, twin,
                      node, why)
        elif "No such container" in stderr:
            _log.info("%s %s: %s is already gone", operation, twin, node)
        else:
            raise cli.CommandFailed(argv, returncode, stderr[-cli.STDERR_KEPT:])

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
        verifies on a running lab. A hosts file that cannot be read is logged at WARNING and
        holds no residue; one that is not UTF-8 is read with replacements."""
        start = f"###### CLAB-{twin}-START ######"
        try:
            hosts = self._hosts_path.read_text(errors="replace")
        except OSError as e:
            _log.warning("%s cannot be read, so no host entry counts as residue: %s", self._hosts_path, e)
            hosts = ""
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


def _tail(output: str) -> str:
    """The last `EXEC_OUTPUT_KEPT` bytes of `output`, whole characters only."""
    return output.encode()[-EXEC_OUTPUT_KEPT:].decode(errors="ignore")


def _node(twin: str, doc: Mapping[str, Any]) -> NodeState:
    """A node from its container's `docker inspect` member; its address is the one it holds
    on the lab's management network while it runs. `DriverFailed` for a container of the lab
    with no node name, which only containerlab labels."""
    handle = doc["Name"].lstrip("/")
    name = (doc["Config"]["Labels"] or {}).get("clab-node-name")
    if not name:
        raise DriverFailed(f"the container {handle} of the lab {twin} has no clab-node-name label")
    running = bool(doc["State"]["Running"])
    started = doc["State"]["StartedAt"]
    network = (doc["NetworkSettings"]["Networks"] or {}).get(f"clab-{twin}") or {}
    return NodeState(
        name=name,
        handle=handle,
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
        used += clab_changes.sections_of(name, node, platforms, probe_packages)
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
