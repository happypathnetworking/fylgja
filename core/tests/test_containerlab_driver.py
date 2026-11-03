"""The local driver's live half (D-017, D-018, D-019, D-043), in the pure tier: a fake runner
stands for the two CLIs, recording each command line and answering canned output."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
from collections.abc import Mapping, Sequence
from ipaddress import IPv4Network
from pathlib import Path
from typing import Any

import pytest

from fylgja_core import blueprint, bundle, compiler, containerlab, platform_package, probe_package
from fylgja_core.containerlab import plan as clab_plan
from fylgja_core.containerlab.cli import TIMED_OUT, CommandFailed
from fylgja_core.containerlab.driver import (
    RULE_CAPACITY,
    RULE_IMAGE,
    ContainerlabDriver,
    deploy_budget,
    destroy_budget,
)
from fylgja_core.containerlab.plan import TOPOLOGY
from fylgja_core.containerlab.pool import DEFAULT_POOL
from fylgja_core.driver import Allocation, Inspection, NodeState, Planned, Refusal

ROOT = Path(__file__).resolve().parents[2]
PLATFORMS = {
    p.id: p
    for p in map(platform_package.load, [ROOT / "psp/nokia_srlinux.yaml", ROOT / "psp/arista_eos.yaml",
                                         ROOT / "testdata/packages/chassisos.yaml"])
}
PROBES = {p.format: p for p in [probe_package.load(ROOT / "probes/ping.yaml")]}

NETWORK_LS = ("docker", "network", "ls", "--format", "{{.ID}}")
NETWORK_INSPECT = ("docker", "network", "inspect", "--format", "{{json .IPAM.Config}}")
IMAGE_INSPECT = ("docker", "image", "inspect", "--format", "{{.Id}}")


class FakeRunner:
    """An async callable with `cli.run`'s signature. It records each command line and its
    budget, raises `CommandFailed` with `status` for a command that starts with a prefix in
    `fail`, and answers the canned stdout of the longest prefix in `answers` that starts it; a
    command with neither is the test's error."""

    def __init__(
        self, answers: Mapping[tuple[str, ...], str], fail: Sequence[tuple[str, ...]] = (), status: int = 1
    ) -> None:
        self.answers = dict(answers)
        self.fail = list(fail)
        self.status = status
        self.calls: list[tuple[str, ...]] = []
        self.budgets: list[float] = []
        self.cwds: list[Path | None] = []

    async def __call__(
        self, argv: Sequence[str], *, timeout_s: float, env: Mapping[str, str] | None = None, cwd: Path | None = None
    ) -> str:
        args = tuple(argv)
        self.calls.append(args)
        self.budgets.append(timeout_s)
        self.cwds.append(cwd)
        if any(args[: len(prefix)] == prefix for prefix in self.fail):
            raise CommandFailed(args, self.status, "Error response from daemon: no such object\n")
        matches = [prefix for prefix in self.answers if args[: len(prefix)] == prefix]
        assert matches, f"unexpected command {args}"
        return self.answers[max(matches, key=len)]


def docker(*configs: str) -> dict[tuple[str, ...], str]:
    """Docker answering one network per IPAM config, each `{{json .IPAM.Config}}` line as given."""
    ids = [f"net{i}" for i in range(len(configs))]
    return {NETWORK_LS: "".join(f"{i}\n" for i in ids), (*NETWORK_INSPECT, *ids): "".join(f"{c}\n" for c in configs)}


# A default bridge, the host and none networks (no IPv4 config), and a lab's dual-stack network.
HOLDING_172_20_0 = docker(
    '[{"Subnet":"172.17.0.0/16","Gateway":"172.17.0.1"}]',
    "[]",
    "null",
    '[{"Subnet":"172.20.0.0/24","Gateway":"172.20.0.1"},{"Subnet":"3fff:172:20::/64"}]',
)


def manifest(name: str) -> bundle.Manifest:
    return compiler.compile(blueprint.load(ROOT / f"testdata/blueprint/{name}.json"), PLATFORMS, PROBES).manifest


def meminfo(tmp_path: Path, available_kb: int) -> Path:
    path = tmp_path / "meminfo"
    path.write_text(f"MemTotal:       65536000 kB\nMemFree:         1000000 kB\nMemAvailable:   {available_kb} kB\n")
    return path


ROOMY_KB = 64 * 1024 * 1024  # 64 GiB


def admit(
    tmp_path: Path,
    runner: FakeRunner,
    name: str = "three-node",
    reserved: Sequence[Allocation] = (),
    *,
    pool: IPv4Network = DEFAULT_POOL,
    available_kb: int = ROOMY_KB,
    cpus: int = 64,
) -> Allocation | Refusal:
    driver = ContainerlabDriver(tmp_path, pool=pool, runner=runner, meminfo=meminfo(tmp_path, available_kb), cpus=cpus)
    return asyncio.run(driver.admit(manifest(name), PLATFORMS, PROBES, "t", reserved))


def test_the_driver_is_the_local_one() -> None:
    driver = ContainerlabDriver(Path("unused"))
    assert driver.name == containerlab.NAME == "containerlab"
    assert driver.capabilities() == containerlab.CAPABILITIES
    assert (RULE_CAPACITY, RULE_IMAGE) == ("admission.capacity", "admission.image.absent")


def test_the_drivers_plan_is_the_pure_plan(tmp_path: Path) -> None:
    c = compiler.compile(blueprint.load(ROOT / "testdata/blueprint/three-node.json"), PLATFORMS, PROBES)
    allocation = {"lab": "t", "mgmt_subnet": "172.20.2.0/24"}
    planned = ContainerlabDriver(tmp_path).plan(c.manifest, c.id, PLATFORMS, PROBES, "t", allocation)
    assert planned == clab_plan.plan(c.manifest, c.id, PLATFORMS, PROBES, "t", allocation)


def test_admit_takes_the_first_subnet_neither_docker_nor_another_twin_holds(tmp_path: Path) -> None:
    runner = FakeRunner(HOLDING_172_20_0)
    allocation = admit(tmp_path, runner, reserved=[{"lab": "u", "mgmt_subnet": "172.20.1.0/24"}])
    assert allocation == {"lab": "t", "mgmt_subnet": "172.20.2.0/24"}
    # Every network's config is read in one inspect; SR Linux's image is public, so never inspected.
    assert runner.calls == [NETWORK_LS, (*NETWORK_INSPECT, "net0", "net1", "net2", "net3")]


def test_a_twin_admitted_beside_one_recorded_but_not_deployed_gets_another_subnet(tmp_path: Path) -> None:
    first = admit(tmp_path, FakeRunner(docker("[]")))
    assert first == {"lab": "t", "mgmt_subnet": "172.20.0.0/24"}
    assert admit(tmp_path, FakeRunner(docker("[]")), reserved=[first]) == {"lab": "t", "mgmt_subnet": "172.20.1.0/24"}


def test_admit_logs_the_twin_the_subnet_and_the_demand(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO", logger="fylgja.containerlab")
    admit(tmp_path, FakeRunner(HOLDING_172_20_0))
    assert [r.getMessage() for r in caplog.records] == [
        "admit t: subnet 172.20.1.0/24; demand 3 nodes, 1.5 CPU, 6144 MiB"]


def test_an_exhausted_pool_is_refused_for_capacity(tmp_path: Path) -> None:
    refused = admit(tmp_path, FakeRunner(HOLDING_172_20_0), pool=IPv4Network("172.20.0.0/24"))
    assert refused == Refusal(RULE_CAPACITY, "The pool 172.20.0.0/24 has no /24 that neither a Docker network "
                                             "nor another twin holds.")
    reserved = admit(tmp_path, FakeRunner(docker("[]")), reserved=[{"lab": "u", "mgmt_subnet": "172.20.0.0/24"}],
                     pool=IPv4Network("172.20.0.0/24"))
    assert isinstance(reserved, Refusal) and reserved.rule == "admission.capacity"


def test_a_twin_larger_than_the_hosts_available_memory_is_refused_naming_the_shortfall(tmp_path: Path) -> None:
    refused = admit(tmp_path, FakeRunner(HOLDING_172_20_0), available_kb=1048576)
    assert refused == Refusal(RULE_CAPACITY, "The twin needs 6144 MiB of memory, and the host has 1024 MiB available.")


def test_a_twin_needing_more_cpu_than_the_host_has_is_refused(tmp_path: Path) -> None:
    refused = admit(tmp_path, FakeRunner(HOLDING_172_20_0), cpus=1)
    assert refused == Refusal(RULE_CAPACITY, "The twin needs 1.5 CPUs, and the host has 1.")


def test_every_shortfall_is_named_in_one_refusal(tmp_path: Path) -> None:
    refused = admit(tmp_path, FakeRunner(HOLDING_172_20_0), pool=IPv4Network("172.20.0.0/24"), available_kb=1048576,
                    cpus=1)
    assert isinstance(refused, Refusal) and refused.rule == RULE_CAPACITY
    assert refused.message == (
        "The pool 172.20.0.0/24 has no /24 that neither a Docker network nor another twin holds. "
        "The twin needs 6144 MiB of memory, and the host has 1024 MiB available. "
        "The twin needs 1.5 CPUs, and the host has 1.")


def test_an_absent_gated_image_is_refused_naming_it(tmp_path: Path) -> None:
    runner = FakeRunner(HOLDING_172_20_0, fail=[IMAGE_INSPECT])
    refused = admit(tmp_path, runner, "mixed")
    assert refused == Refusal(RULE_IMAGE, "The image ceos:4.32.0.2F (arista_eos) is account-gated and not on the host, "
                                          "and the local driver never pulls it: import it under that tag.")
    # Only the gated image is inspected; the public SR Linux one is containerlab's to pull at deploy.
    assert [c for c in runner.calls if c[:3] == ("docker", "image", "inspect")] == [(*IMAGE_INSPECT, "ceos:4.32.0.2F")]


def test_a_present_gated_image_is_admitted(tmp_path: Path) -> None:
    runner = FakeRunner({**HOLDING_172_20_0, IMAGE_INSPECT: "sha256:4c2b\n"})
    assert admit(tmp_path, runner, "mixed") == {"lab": "t", "mgmt_subnet": "172.20.1.0/24"}


def test_a_hung_image_inspect_is_a_driver_error_not_an_absence(tmp_path: Path) -> None:
    with pytest.raises(CommandFailed) as raised:
        admit(tmp_path, FakeRunner(HOLDING_172_20_0, fail=[IMAGE_INSPECT], status=TIMED_OUT), "mixed")
    assert raised.value.returncode == TIMED_OUT


DEPLOY: tuple[str, ...] = ("containerlab", "deploy")


def planned(name: str, twin: str = "t", subnet: str = "172.20.2.0/24") -> Planned:
    c = compiler.compile(blueprint.load(ROOT / f"testdata/blueprint/{name}.json"), PLATFORMS, PROBES)
    return clab_plan.plan(c.manifest, c.id, PLATFORMS, PROBES, twin, {"lab": twin, "mgmt_subnet": subnet})


def apply(
    tmp_path: Path, runner: FakeRunner, p: Planned, files: Mapping[str, bytes] | None = None, reconfigure: bool = False
) -> None:
    driver = ContainerlabDriver(tmp_path, runner=runner)
    asyncio.run(driver.apply(p.deployment, p.files if files is None else files, PLATFORMS, PROBES, reconfigure))


def test_apply_writes_the_deployments_files_under_the_twins_directory_and_deploys_them(tmp_path: Path) -> None:
    p = planned("three-node")
    runner = FakeRunner({DEPLOY: ""})
    apply(tmp_path, runner, p)
    directory = tmp_path / "containerlab" / "t"
    topology = directory / TOPOLOGY
    assert topology.read_bytes() == p.files[TOPOLOGY]
    assert [path.name for path in directory.iterdir()] == [TOPOLOGY]  # no temporary file left beside it
    assert runner.calls == [("containerlab", "deploy", "-t", str(topology))]
    assert runner.budgets == [180 + 60]
    assert runner.cwds == [directory]


def test_apply_with_reconfigure_deploys_with_reconfigure(tmp_path: Path) -> None:
    runner = FakeRunner({DEPLOY: ""})
    apply(tmp_path, runner, planned("three-node"), reconfigure=True)
    assert runner.calls == [("containerlab", "deploy", "-t", str(tmp_path / "containerlab/t" / TOPOLOGY),
                             "--reconfigure")]


def test_a_repeat_apply_replaces_the_files_and_deploys_again(tmp_path: Path) -> None:
    # A repeat of a running lab is containerlab's own reconcile; a step's plan replaces the file.
    runner = FakeRunner({DEPLOY: ""})
    apply(tmp_path, runner, planned("three-node"))
    stepped = planned("three-node-probed")
    apply(tmp_path, runner, stepped)
    assert (tmp_path / "containerlab/t" / TOPOLOGY).read_bytes() == stepped.files[TOPOLOGY]
    assert [path.name for path in (tmp_path / "containerlab/t").iterdir()] == [TOPOLOGY]
    assert runner.calls == [("containerlab", "deploy", "-t", str(tmp_path / "containerlab/t" / TOPOLOGY))] * 2


def test_files_that_are_not_the_deployments_are_refused_before_any_command_or_write(tmp_path: Path) -> None:
    p = planned("three-node")
    runner = FakeRunner({DEPLOY: ""})
    with pytest.raises(ValueError, match=r"topology\.clab\.yml is not the deployment's: its SHA-256 differs"):
        apply(tmp_path, runner, p, {TOPOLOGY: p.files[TOPOLOGY] + b"# changed\n"})
    with pytest.raises(ValueError, match=r"the files \[\] are not the deployment's \['topology\.clab\.yml'\]"):
        apply(tmp_path, runner, p, {})
    with pytest.raises(ValueError, match="are not the deployment's"):
        apply(tmp_path, runner, p, {**p.files, "extra.yml": b""})
    assert runner.calls == []
    assert not (tmp_path / "containerlab").exists()


def test_the_deploy_budget_is_the_slowest_package_the_nodes_use_plus_a_minute() -> None:
    assert deploy_budget(planned("three-node").files, PLATFORMS, PROBES) == 180 + 60  # EOS's 300 s is not used
    assert deploy_budget(planned("mixed").files, PLATFORMS, PROBES) == 300 + 60
    assert deploy_budget(planned("three-node-probed").files, PLATFORMS, PROBES) == 180 + 60
    ping = PROBES["ping"]
    clab = dataclasses.replace(ping.runtime.containerlab, deploy_timeout_s=400)
    slow = {"ping": dataclasses.replace(ping, runtime=dataclasses.replace(ping.runtime, containerlab=clab))}
    assert deploy_budget(planned("three-node-probed").files, PLATFORMS, slow) == 400 + 60
    assert deploy_budget(planned("three-node").files, PLATFORMS, slow) == 180 + 60


def test_a_node_no_given_package_runs_has_no_budget() -> None:
    with pytest.raises(ValueError, match=r"no package given runs the node e1 \(ceos, ceos:4\.32\.0\.2F\)"):
        deploy_budget(planned("mixed").files, {"nokia_srlinux": PLATFORMS["nokia_srlinux"]}, PROBES)


class Inspected(ContainerlabDriver):
    """The driver over a canned inspection."""

    def __init__(self, inspection: Inspection) -> None:
        super().__init__(Path("unused"))
        self.inspection = inspection

    async def inspect(self, twin: str) -> Inspection:
        return self.inspection


def test_endpoints_are_the_running_nodes_addresses() -> None:
    def node(name: str, address: str | None, running: bool) -> NodeState:
        return NodeState(name=name, handle=f"clab-t-{name}", incarnation="2026-11-03T12:00:00Z", address=address,
                         running=running)

    # n4 is held to the rule as well: an address is a running node's alone.
    nodes = (node("n3", None, False), node("n1", "172.20.2.2", True), node("n2", None, True),
             node("n4", "172.20.2.5", False))
    driver = Inspected(Inspection(state="present", nodes=nodes))
    assert asyncio.run(driver.endpoints("t")) == {"n1": "172.20.2.2"}
    assert asyncio.run(Inspected(Inspection(state="absent", nodes=())).endpoints("t")) == {}


# inspect and destroy. Docker's answers are canned in the shapes Docker 29.8.1 gave for
# containerlab 0.81.0's labs (verified-facts.md): an exited container keeps its last StartedAt
# and its IPAM address, and loses its IPAddress.

PS: tuple[str, ...] = ("docker", "ps", "-a", "--filter", "label=containerlab=t", "--format", "{{.Names}}")
INSPECT: tuple[str, ...] = ("docker", "inspect", "--type", "container")
NETWORK: tuple[str, ...] = ("docker", "network", "inspect", "clab-t")
DESTROY: tuple[str, ...] = ("containerlab", "destroy")
NETWORK_RM: tuple[str, ...] = ("docker", "network", "rm", "clab-t")


def container(
    node: str, running: bool = True, address: str = "", started: str = "2026-11-03T12:00:00.416491086Z"
) -> dict[str, Any]:
    """A `docker inspect` member of a containerlab node, the members the driver reads in their
    real shape; `address` is the one containerlab assigned it."""
    network = {"IPAMConfig": {"IPv4Address": address} if address else None, "IPAddress": address if running else "",
               "Gateway": "172.20.2.1" if running else ""}
    return {
        "Id": f"{node}0123456789abcdef",
        "Name": f"/clab-t-{node}",
        "State": {"Status": "running" if running else "exited", "Running": running, "StartedAt": started},
        "Config": {"Labels": {"containerlab": "t", "clab-node-name": node, "clab-node-kind": "nokia_srlinux",
                              "clab-node-longname": f"clab-t-{node}", "fylgja.twin": "t"}},
        "NetworkSettings": {"Networks": {"clab-t": network}},
    }


def lab(*containers: dict[str, Any]) -> dict[tuple[str, ...], str]:
    names = [c["Name"].lstrip("/") for c in containers]
    return {PS: "".join(f"{n}\n" for n in names), (*INSPECT, *names): json.dumps(list(containers))}


RUNNING = lab(container("n2", address="172.20.2.3", started="2026-11-03T12:00:01.418188892Z"),
              container("n1", address="172.20.2.2"),
              container("n3", address="172.20.2.4", started="2026-11-03T12:00:02.414991394Z"))
NOTHING: dict[tuple[str, ...], str] = {PS: ""}


def driver(tmp_path: Path, runner: FakeRunner) -> ContainerlabDriver:
    """The driver with the host's residue staged under `tmp_path`: an empty hosts file and ssh config directory."""
    hosts = tmp_path / "etc-hosts"
    if not hosts.exists():
        hosts.write_text("127.0.0.1 localhost\n")
    ssh_config_dir = tmp_path / "ssh_config.d"
    ssh_config_dir.mkdir(exist_ok=True)
    return ContainerlabDriver(tmp_path / "root", runner=runner, hosts_path=hosts, ssh_config_dir=ssh_config_dir)


def inspect(tmp_path: Path, runner: FakeRunner) -> Inspection:
    return asyncio.run(driver(tmp_path, runner).inspect("t"))


def test_inspect_reads_each_nodes_name_handle_incarnation_and_address(tmp_path: Path) -> None:
    runner = FakeRunner(RUNNING)
    assert inspect(tmp_path, runner) == Inspection(state="present", nodes=(
        NodeState(name="n1", handle="clab-t-n1", incarnation="2026-11-03T12:00:00.416491086Z",
                  address="172.20.2.2", running=True),
        NodeState(name="n2", handle="clab-t-n2", incarnation="2026-11-03T12:00:01.418188892Z",
                  address="172.20.2.3", running=True),
        NodeState(name="n3", handle="clab-t-n3", incarnation="2026-11-03T12:00:02.414991394Z",
                  address="172.20.2.4", running=True),
    ))
    assert runner.calls == [PS, (*INSPECT, "clab-t-n2", "clab-t-n1", "clab-t-n3")]


def test_an_exited_container_is_present_not_running_and_without_an_address(tmp_path: Path) -> None:
    exited = lab(container("n1", running=False, address="172.20.2.2"), container("n2", address="172.20.2.3"))
    inspection = inspect(tmp_path, FakeRunner(exited))
    assert inspection.state == "present"
    assert [(n.name, n.running, n.address) for n in inspection.nodes] == [("n1", False, None),
                                                                          ("n2", True, "172.20.2.3")]


def test_a_node_never_started_has_no_incarnation(tmp_path: Path) -> None:
    created = lab(container("n1", running=False, started="0001-01-01T00:00:00Z"))
    assert inspect(tmp_path, FakeRunner(created)).nodes[0].incarnation is None


def test_a_twin_the_runtime_holds_nothing_of_is_absent(tmp_path: Path) -> None:
    runner = FakeRunner(NOTHING, fail=[NETWORK])
    assert inspect(tmp_path, runner) == Inspection(state="absent", nodes=())
    assert runner.calls == [PS, NETWORK]


def test_host_entries_with_no_container_are_residue(tmp_path: Path) -> None:
    (tmp_path / "etc-hosts").write_text("127.0.0.1 localhost\n###### CLAB-t-START ######\n"
                                        "172.20.2.2\tclab-t-n1 dbc5223ecae4\t# Kind: nokia_srlinux\n"
                                        "###### CLAB-t-END ######\n")
    runner = FakeRunner(NOTHING, fail=[NETWORK])
    assert inspect(tmp_path, runner) == Inspection(state="residue", nodes=())
    assert runner.calls == [PS]


def test_another_twins_host_entries_are_not_this_ones_residue(tmp_path: Path) -> None:
    # The twin t-2's entries hold clab-t-2-n1, which begins with clab-t- but is no node of t.
    (tmp_path / "etc-hosts").write_text("###### CLAB-t-2-START ######\n"
                                        "172.20.3.2\tclab-t-2-n1 b85f77e7fa3a\t# Kind: nokia_srlinux\n"
                                        "###### CLAB-t-2-END ######\n")
    assert inspect(tmp_path, FakeRunner(NOTHING, fail=[NETWORK])).state == "absent"


def test_the_ssh_config_or_the_network_alone_is_residue(tmp_path: Path) -> None:
    (tmp_path / "ssh_config.d").mkdir()
    (tmp_path / "ssh_config.d" / "clab-t.conf").write_text("Host clab-t-n1\n")
    assert inspect(tmp_path, FakeRunner(NOTHING, fail=[NETWORK])).state == "residue"
    (tmp_path / "ssh_config.d" / "clab-t.conf").unlink()
    assert inspect(tmp_path, FakeRunner({**NOTHING, NETWORK: "[]\n"})).state == "residue"


def test_a_hung_network_inspect_is_a_driver_error_not_an_absence(tmp_path: Path) -> None:
    with pytest.raises(CommandFailed):
        inspect(tmp_path, FakeRunner(NOTHING, fail=[NETWORK], status=TIMED_OUT))


def test_endpoints_read_the_running_lab(tmp_path: Path) -> None:
    exited = lab(container("n1", address="172.20.2.2"), container("n2", running=False, address="172.20.2.3"))
    assert asyncio.run(driver(tmp_path, FakeRunner(exited)).endpoints("t")) == {"n1": "172.20.2.2"}


def destroy(tmp_path: Path, runner: FakeRunner, p: Planned | None = None) -> None:
    p = p or planned("three-node")
    asyncio.run(driver(tmp_path, runner).destroy(p.deployment, p.files, PLATFORMS, PROBES))


def test_destroying_a_present_lab_destroys_it_with_cleanup_and_removes_the_twins_directory(tmp_path: Path) -> None:
    runner = FakeRunner({**RUNNING, DEPLOY: "", DESTROY: ""}, fail=[NETWORK])
    p = planned("three-node")
    asyncio.run(driver(tmp_path, runner).apply(p.deployment, p.files, PLATFORMS, PROBES))
    runner.calls.clear()
    runner.budgets.clear()
    destroy(tmp_path, runner, p)
    topology = str(tmp_path / "root/containerlab/t" / TOPOLOGY)
    assert runner.calls == [PS, (*INSPECT, "clab-t-n2", "clab-t-n1", "clab-t-n3"),
                            ("containerlab", "destroy", "-t", topology, "--cleanup"), NETWORK]
    assert runner.budgets[2] == 60 + 60
    assert not (tmp_path / "root/containerlab/t").exists()


def test_a_network_a_destroy_leaves_is_removed(tmp_path: Path) -> None:
    runner = FakeRunner({**RUNNING, DESTROY: "", NETWORK: "[]\n", NETWORK_RM: ""})
    destroy(tmp_path, runner)
    assert runner.calls[-3:] == [("containerlab", "destroy", "-t", str(tmp_path / "root/containerlab/t" / TOPOLOGY),
                                  "--cleanup"), NETWORK, NETWORK_RM]


def test_root_owned_residue_is_deployed_then_destroyed(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO", logger="fylgja.containerlab")
    (tmp_path / "ssh_config.d").mkdir()
    (tmp_path / "ssh_config.d" / "clab-t.conf").write_text("Host clab-t-n1\n")
    runner = FakeRunner({**NOTHING, DEPLOY: "", DESTROY: ""}, fail=[NETWORK])
    destroy(tmp_path, runner)
    topology = str(tmp_path / "root/containerlab/t" / TOPOLOGY)
    assert runner.calls == [PS, ("containerlab", "deploy", "-t", topology),
                            ("containerlab", "destroy", "-t", topology, "--cleanup"), NETWORK]
    assert runner.budgets[1:3] == [180 + 60, 60 + 60]
    assert "destroy t: residue and no container: deploy, then destroy (D-023)" in caplog.messages
    assert not (tmp_path / "root/containerlab/t").exists()


def test_a_management_network_alone_is_removed_without_a_deploy(tmp_path: Path) -> None:
    # A deploy refused at its start leaves only the network, which docker can remove (D-019);
    # deploying that topology again would be refused again.
    runner = FakeRunner({**NOTHING, NETWORK: "[]\n", NETWORK_RM: ""})
    destroy(tmp_path, runner)
    assert runner.calls == [PS, NETWORK, NETWORK, NETWORK_RM]


def test_destroying_what_is_absent_does_nothing_but_remove_the_twins_directory(tmp_path: Path) -> None:
    (tmp_path / "root/containerlab/t/clab-t").mkdir(parents=True)
    runner = FakeRunner(NOTHING, fail=[NETWORK])
    destroy(tmp_path, runner)
    destroy(tmp_path, runner)
    assert runner.calls == [PS, NETWORK] * 2
    assert not (tmp_path / "root/containerlab/t").exists()
    assert (tmp_path / "root/containerlab").is_dir()


def test_destroy_refuses_files_that_are_not_the_deployments_before_any_command(tmp_path: Path) -> None:
    p = planned("three-node")
    runner = FakeRunner(RUNNING)
    with pytest.raises(ValueError, match="is not the deployment's"):
        asyncio.run(driver(tmp_path, runner).destroy(p.deployment, {TOPOLOGY: b"name: t\n"}, PLATFORMS, PROBES))
    assert runner.calls == []


def test_the_destroy_budget_is_the_slowest_package_the_nodes_use_plus_a_minute() -> None:
    assert destroy_budget(planned("three-node").files, PLATFORMS, PROBES) == 60 + 60
    assert destroy_budget(planned("three-node-probed").files, PLATFORMS, PROBES) == 60 + 60  # ping's is 30
    srl = PLATFORMS["nokia_srlinux"]
    clab = dataclasses.replace(srl.runtime.containerlab, destroy_timeout_s=90)
    slow = {**PLATFORMS, "nokia_srlinux": dataclasses.replace(srl, runtime=dataclasses.replace(srl.runtime,
                                                                                               containerlab=clab))}
    assert destroy_budget(planned("mixed").files, slow, PROBES) == 90 + 60


def test_a_failed_destroy_leaves_the_rest_for_the_next_destroy(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO", logger="fylgja.containerlab")
    p = planned("three-node")
    failing = FakeRunner({**RUNNING, DEPLOY: "", NETWORK: "[]\n", NETWORK_RM: ""}, fail=[DESTROY])
    asyncio.run(driver(tmp_path, failing).apply(p.deployment, p.files, PLATFORMS, PROBES))
    failing.calls.clear()
    with pytest.raises(CommandFailed):
        destroy(tmp_path, failing, p)
    assert failing.calls[-1][:2] == DESTROY  # no network check or removal after it
    assert (tmp_path / "root/containerlab/t" / TOPOLOGY).exists()
    assert [(r.levelname, r.getMessage().split(":")[0]) for r in caplog.records if r.levelname == "WARNING"] == [
        ("WARNING", "destroy t failed, and the next destroy finds what is left")]
    again = FakeRunner({**RUNNING, DESTROY: "", NETWORK: "[]\n", NETWORK_RM: ""})
    destroy(tmp_path, again, p)
    assert [c[:2] for c in again.calls] == [PS[:2], INSPECT[:2], DESTROY, NETWORK[:2], NETWORK_RM[:2]]
    assert not (tmp_path / "root/containerlab/t").exists()


def test_a_failed_rule_2_deploy_is_raised_and_destroys_nothing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "ssh_config.d").mkdir()
    (tmp_path / "ssh_config.d" / "clab-t.conf").write_text("Host clab-t-n1\n")
    runner = FakeRunner({**NOTHING, DESTROY: ""}, fail=[DEPLOY, NETWORK])
    with pytest.raises(CommandFailed):
        destroy(tmp_path, runner)
    assert [c[:2] for c in runner.calls] == [PS[:2], DEPLOY]
    assert any(r.levelname == "WARNING" and "destroy t failed" in r.getMessage() for r in caplog.records)


def test_an_unreadable_hosts_file_holds_no_residue(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    unreadable = tmp_path / "hosts-is-a-directory"
    unreadable.mkdir()
    (tmp_path / "ssh_config.d").mkdir()
    d = ContainerlabDriver(tmp_path / "root", runner=FakeRunner(NOTHING, fail=[NETWORK]), hosts_path=unreadable,
                           ssh_config_dir=tmp_path / "ssh_config.d")
    assert asyncio.run(d.inspect("t")).state == "absent"
    assert any(r.levelname == "WARNING" and "cannot be read" in r.getMessage() for r in caplog.records)


def test_a_hosts_file_that_is_not_utf8_is_still_read(tmp_path: Path) -> None:
    (tmp_path / "etc-hosts").write_bytes(b"127.0.0.1 h\xf6st\n###### CLAB-t-START ######\n")
    assert inspect(tmp_path, FakeRunner(NOTHING, fail=[NETWORK])).state == "residue"


@pytest.mark.skipif(os.geteuid() == 0, reason="root removes a read-only directory's entries")
def test_a_twins_directory_that_cannot_be_removed_is_left_and_never_wedges_destroy(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # As containerlab leaves a root-owned lab directory: its entries cannot be unlinked.
    locked = tmp_path / "root/containerlab/t/clab-t"
    locked.mkdir(parents=True)
    (locked / "topology-data.json").write_text("{}")
    locked.chmod(0o500)
    try:
        destroy(tmp_path, FakeRunner(NOTHING, fail=[NETWORK]))
        assert locked.is_dir()
        assert any(r.levelname == "WARNING" and "its directory" in r.getMessage() and "is left" in r.getMessage()
                   for r in caplog.records)
    finally:
        locked.chmod(0o700)
