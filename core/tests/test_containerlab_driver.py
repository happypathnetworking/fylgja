"""The local driver's live half (D-017, D-018, D-019, D-043), in the pure tier: a fake runner
stands for the two CLIs, recording each command line and answering canned output."""

from __future__ import annotations

import asyncio
import dataclasses
from collections.abc import Mapping, Sequence
from ipaddress import IPv4Network
from pathlib import Path

import pytest

from fylgja_core import blueprint, bundle, compiler, containerlab, platform_package, probe_package
from fylgja_core.containerlab import plan as clab_plan
from fylgja_core.containerlab.cli import TIMED_OUT, CommandFailed
from fylgja_core.containerlab.driver import RULE_CAPACITY, RULE_IMAGE, ContainerlabDriver, deploy_budget
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


DEPLOY = ("containerlab", "deploy")


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
