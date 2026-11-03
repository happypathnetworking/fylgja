"""Probe package 1's loader: the shipped package loads to its model, and each rejection fixture
under testdata/packages/invalid/probe/ is refused for its fault alone."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from fylgja_core import documents, probe_package
from fylgja_core.documents import Rejected
from fylgja_core.probe_package import RULE_FORMAT, RULE_INVALID, RULE_PLACEHOLDERS, RULE_VERSION, Resources

ROOT = Path(__file__).resolve().parents[2]
SHIPPED = sorted((ROOT / "probes").glob("*.yaml"))
INVALID = ROOT / "testdata" / "packages" / "invalid" / "probe"

# Every rejection fixture, and the (pointer, rule) pairs the loader must report for it.
REJECTED: dict[str, set[tuple[str, str]]] = {
    "version-unknown.yaml": {("/probe_package_version", RULE_VERSION)},
    "schema-command-is-a-string.yaml": {("/host/address", RULE_INVALID)},
    "format-unsupported.yaml": {("/format", RULE_FORMAT)},
    "command-unknown-placeholder.yaml": {("/host/route/3", RULE_PLACEHOLDERS)},
    "expect-unknown-placeholder.yaml": {("/readiness/expect", RULE_PLACEHOLDERS)},
    "several.yaml": {("/format", RULE_FORMAT), ("/host/route/3", RULE_PLACEHOLDERS)},
}


@pytest.mark.parametrize("path", SHIPPED, ids=lambda p: p.name)
def test_each_shipped_package_loads_to_its_model_and_encodes_back_unchanged(path: Path) -> None:
    package = probe_package.load(path)
    assert package.format == path.stem
    assert documents.encode(package) == yaml.safe_load(path.read_text())


def test_the_ping_package_reads_as_written() -> None:
    package = probe_package.load(ROOT / "probes" / "ping.yaml")
    assert package.host.interface == "eth1"
    assert package.host.route[3] == "{far_address}/32"
    assert package.readiness.expect == "{address}" and package.readiness.timeout_s == 30
    assert package.flow.interval_s == 0.2 and package.burst.count == 5 and package.burst.wait_s == 2
    assert package.runtime.containerlab.image.ref == "alpine:3.24.2"
    assert package.runtime.containerlab.image.pull_secret is None
    assert package.runtime.containerlab.resources == Resources(cpu=0.1, memory_mb=32)


def test_the_mechanisms_this_build_runs_are_named() -> None:
    assert frozenset({"ping"}) == probe_package.MECHANISMS


@pytest.mark.parametrize("name", sorted(REJECTED))
def test_each_rejection_fixture_is_refused_for_its_fault_alone(name: str) -> None:
    doc = yaml.safe_load((INVALID / name).read_text())
    found = probe_package.validate(doc)
    assert {(p.pointer, p.rule) for p in found} == REJECTED[name], found
    with pytest.raises(Rejected) as caught:
        probe_package.load(INVALID / name)
    assert caught.value.subject == str(INVALID / name)


def test_a_refused_format_names_the_mechanisms_there_are() -> None:
    doc = yaml.safe_load((INVALID / "format-unsupported.yaml").read_text())
    (problem,) = probe_package.validate(doc)
    assert "traceroute" in problem.detail and "ping" in problem.detail


@pytest.mark.parametrize("field", ["address", "route"])
def test_a_host_command_may_name_only_the_four_placeholders_the_plan_renders(field: str) -> None:
    doc = yaml.safe_load((ROOT / "probes" / "ping.yaml").read_text())
    doc["host"][field].append("{interval}")
    (problem,) = probe_package.validate(doc)
    assert (problem.pointer, problem.rule) == (f"/host/{field}/{len(doc['host'][field]) - 1}", RULE_PLACEHOLDERS)
    assert problem.detail == ("{interval} is no placeholder a host command may name; "
                              "it may name {address}, {far_address}, {gateway}, {interface}")
    assert probe_package.HOST_PLACEHOLDERS < probe_package.PLACEHOLDERS


def test_every_rejection_fixture_has_a_row() -> None:
    assert {p.name for p in INVALID.glob("*.yaml")} == set(REJECTED)
