"""Verify (D-051, D-031, D-030, D-032, D-048): a twin created to Ready through the loop on the
fakes, its layer 1 read by a fake gNMI reader seeded consistent with its bundle, and judged.

Each test perturbs the seeded facts, the record or the manifest, and reads the verdict's
status, counts and findings: a held assertion files no finding, a failed one an error, a skip
an info `verify.skipped`; a node that cannot be read ends the verdict `failed`."""

from __future__ import annotations

import asyncio
import dataclasses
import json
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeDriver, FakeReader
from test_reconcile import ENVIRON, PASSWORD, PLATFORMS, PROBES, file_blueprint, json_logs, make, new_twin

from fylgja_core import blueprint, bundle, compiler, documents, findings, gnmi, verify
from fylgja_core.bundle import Manifest
from fylgja_core.credentials import Credential, Missing, Provider
from fylgja_core.driver import Exec
from fylgja_core.findings import Counts, Subject, Verdict
from fylgja_core.local_store import LocalStore
from fylgja_core.platform_package import PlatformPackage
from fylgja_core.twin_record import TwinRecord
from fylgja_core.verify import Verifier

ROOT = Path(__file__).resolve().parents[2]
PROBED = "testdata/blueprint/three-node-probed.json"
SRL = PLATFORMS["nokia_srlinux"].conformance
EOS = PLATFORMS["arista_eos"].conformance
BASELINE = Counts(held=8 + 6 + 3 + 2, failed=0, skipped=3 + 2)
OTHER_BUNDLE = "f" * 64


@pytest.fixture
def store(tmp_path: Path) -> Iterator[LocalStore]:
    s = LocalStore.open(tmp_path / "store")
    yield s
    s.close()


@dataclasses.dataclass
class Lab:
    """A twin `t` created to Ready on the fakes, and a reader seeded consistent with it."""

    driver: FakeDriver
    reader: FakeReader
    record: TwinRecord
    manifest: Manifest

    def facts(self, node: str) -> dict[str, Any]:
        return self.reader.facts[("t", node)]


def ready(store: LocalStore, path: str = PROBED) -> Lab:
    new_twin(store, file_blueprint(store, path))
    driver = FakeDriver()
    asyncio.run(make(store, driver).reconcile("t"))
    record = store.get_twin("t")
    assert record.status.bundle_id is not None and record.status.deployment_id is not None
    manifest = bundle.decode(json.loads(store.get_bundle(record.status.bundle_id)["manifest.json"]))
    reader = FakeReader(driver)
    reader.seed("t", manifest, PLATFORMS)
    return Lab(driver=driver, reader=reader, record=record, manifest=manifest)


def verified(
    lab: Lab,
    *,
    record: TwinRecord | None = None,
    manifest: Manifest | None = None,
    environ: Mapping[str, str] = ENVIRON,
    reader: Any = None,
) -> Verdict:
    """Verify `lab` and hold the verdict to findings 1 and to its subject."""
    record = record or lab.record
    bundle_id = record.status.bundle_id
    assert bundle_id is not None
    verifier = Verifier(PLATFORMS, PROBES, Provider(environ), reader=reader or lab.reader)
    verdict = asyncio.run(verifier.verify(record, manifest or lab.manifest, bundle_id, lab.driver.exec))
    assert findings.validate(documents.encode(verdict)) == []
    assert verdict.operation == "verify"
    assert verdict.subject == Subject(twin="t", bundle_id=bundle_id, deployment_id=record.status.deployment_id)
    assert verdict.findings == findings.order(verdict.findings)
    assert verdict.counts is not None
    assert len([f for f in verdict.findings if f.rule == verify.RULE_SKIPPED]) == verdict.counts.skipped
    assert all(f.severity == "info" for f in verdict.findings if f.rule == verify.RULE_SKIPPED)
    assert all(f.severity == "error" for f in verdict.findings if f.rule != verify.RULE_SKIPPED)
    asserted = [f for f in verdict.findings if f.severity == "error" and f.rule != verify.RULE_NODE_UNREAD]
    assert len(asserted) == verdict.counts.failed
    return verdict


def errors(verdict: Verdict) -> list[tuple[str, str | None]]:
    return [(f.rule, f.object) for f in verdict.findings if f.severity == "error"]


def skipped(verdict: Verdict) -> list[str | None]:
    return [f.object for f in verdict.findings if f.rule == verify.RULE_SKIPPED]


def message(verdict: Verdict, rule: str, obj: str) -> str:
    (found,) = [f for f in verdict.findings if f.rule == rule and f.object == obj]
    return found.message


def at(template: str, port: str) -> str:
    return template.replace("{node_name}", port)


def neighbour_entry(system_name: str, port_id: str) -> dict[str, str]:
    return {SRL.port.neighbor.system_name: system_name, SRL.port.neighbor.port_id: port_id}


# The assertions on a seeded twin.


def test_a_seeded_twin_verifies_ok_with_every_assertion_counted(store: LocalStore) -> None:
    lab = ready(store)
    verdict = verified(lab)

    assert verdict.status == "ok" and verdict.counts == BASELINE
    assert len(verdict.findings) == 5 and all(f.severity == "info" for f in verdict.findings)
    assert skipped(verdict) == ["n1", "n1:ethernet-1/10", "n1:ethernet-1/11", "n2", "n3"]
    for node in ("n1", "n2", "n3"):
        assert node in message(verdict, verify.RULE_SKIPPED, node)  # each read host name is named
    assert "n1-loop-a" in message(verdict, verify.RULE_SKIPPED, "n1:ethernet-1/10")
    # One Get per device node, asking the paths its assertions need.
    assert sorted(node for node, _ in lab.reader.calls) == ["n1", "n2", "n3"]
    for node, paths in lab.reader.calls:
        assert list(paths) == verify.paths(lab.manifest, node, PLATFORMS["nokia_srlinux"])
    bursts = [c for c in lab.driver.calls if c[0] == "exec" and c[3] == "ping"]
    assert bursts == [("exec", "t", "n1-loop-a", "ping", "-c", "5", "-i", "0.2", "-W", "2", "10.1.11.2"),
                      ("exec", "t", "n1-loop-b", "ping", "-c", "5", "-i", "0.2", "-W", "2", "10.1.10.2")]


def test_paths_are_the_host_name_and_both_reads_of_each_cabled_enabled_port() -> None:
    def compiled(path: str) -> Manifest:
        return compiler.compile(blueprint.load(ROOT / path), PLATFORMS, PROBES).manifest

    srl = PLATFORMS["nokia_srlinux"]
    probed = compiled(PROBED)
    ports = ["ethernet-1/1", "ethernet-1/10", "ethernet-1/11", "ethernet-1/2"]
    assert verify.paths(probed, "n1", srl) == ["/system/name/host-name"] + [
        path for port in ports for path in (f"/interface[name={port}]/admin-state",
                                            f"/system/lldp/interface[name={port}]/neighbor")]
    assert verify.paths(probed, "n2", srl) == [
        "/system/name/host-name",
        "/interface[name=ethernet-1/1]/admin-state", "/system/lldp/interface[name=ethernet-1/1]/neighbor",
        "/interface[name=ethernet-1/2]/admin-state", "/system/lldp/interface[name=ethernet-1/2]/neighbor"]
    disabled = compiled("testdata/blueprint/steps/three-node-n1-disabled.json")
    assert verify.paths(disabled, "n1", srl) == [
        "/system/name/host-name",
        "/interface[name=ethernet-1/1]/admin-state", "/system/lldp/interface[name=ethernet-1/1]/neighbor"]
    mixed = compiled("testdata/blueprint/mixed.json")
    assert verify.paths(mixed, "e1", PLATFORMS["arista_eos"]) == [
        "/system/state/hostname",
        "/interfaces/interface[name=Ethernet1]/state/admin-status",
        "/lldp/interfaces/interface[name=Ethernet1]/neighbors/neighbor",
        "/interfaces/interface[name=Ethernet2/1]/state/admin-status",
        "/lldp/interfaces/interface[name=Ethernet2/1]/neighbors/neighbor"]


def test_a_configured_node_s_production_host_name_is_reported_and_its_neighbours_judged_against_it(
    store: LocalStore,
) -> None:
    lab = ready(store)
    lab.facts("n1")[SRL.host_name] = "leaf-01"
    verdict = verified(lab)
    # The far ends still list n1: they are judged against the read host name, leaf-01.
    assert verdict.status == "nonconforming"
    assert errors(verdict) == [(verify.RULE_PORT_NEIGHBOR, "n2:ethernet-1/1"),
                               (verify.RULE_PORT_NEIGHBOR, "n3:ethernet-1/2")]
    assert "n1" in message(verdict, verify.RULE_PORT_NEIGHBOR, "n2:ethernet-1/1")
    assert "leaf-01" in message(verdict, verify.RULE_PORT_NEIGHBOR, "n2:ethernet-1/1")

    lab.facts("n2")[at(SRL.port.neighbor.path, "ethernet-1/1")] = [neighbour_entry("leaf-01", "ethernet-1/1")]
    lab.facts("n3")[at(SRL.port.neighbor.path, "ethernet-1/2")] = [neighbour_entry("leaf-01", "ethernet-1/2")]
    verdict = verified(lab)
    assert verdict.status == "ok" and verdict.counts == BASELINE
    assert "leaf-01" in message(verdict, verify.RULE_SKIPPED, "n1")


def test_an_unconfigured_node_s_host_name_is_asserted_against_its_device_name(store: LocalStore) -> None:
    lab = ready(store)
    lab.facts("n1")[SRL.host_name] = "leaf-01"
    lab.facts("n2")[at(SRL.port.neighbor.path, "ethernet-1/1")] = [neighbour_entry("leaf-01", "ethernet-1/1")]
    lab.facts("n3")[at(SRL.port.neighbor.path, "ethernet-1/2")] = [neighbour_entry("leaf-01", "ethernet-1/2")]
    nodes = tuple(dataclasses.replace(n, config=None) if n.name == "n1" else n for n in lab.manifest.nodes)
    verdict = verified(lab, manifest=dataclasses.replace(lab.manifest, nodes=nodes))

    assert verdict.status == "nonconforming"
    # n1's host name asserted and failed; its claim a skip; the neighbours toward it still held.
    assert verdict.counts == Counts(held=BASELINE.held - 1, failed=1, skipped=BASELINE.skipped)
    assert errors(verdict) == [(verify.RULE_HOST_NAME, "n1")]
    assert "leaf-01" in message(verdict, verify.RULE_HOST_NAME, "n1")
    assert skipped(verdict).count("n1") == 1  # the claim, not the host name


def test_a_far_end_that_lists_no_neighbour_fails_at_that_end_alone(store: LocalStore) -> None:
    lab = ready(store)
    lab.facts("n3")[at(SRL.port.neighbor.path, "ethernet-1/2")] = []
    verdict = verified(lab)

    assert verdict.status == "nonconforming"
    assert verdict.counts == Counts(held=BASELINE.held - 1, failed=1, skipped=BASELINE.skipped)
    assert errors(verdict) == [(verify.RULE_PORT_NEIGHBOR, "n3:ethernet-1/2")]  # n1:ethernet-1/2's end held
    assert "no neighbour" in message(verdict, verify.RULE_PORT_NEIGHBOR, "n3:ethernet-1/2")


def test_a_port_that_lists_two_neighbours_fails_naming_the_count(store: LocalStore) -> None:
    lab = ready(store)
    lab.facts("n2")[at(SRL.port.neighbor.path, "ethernet-1/1")] = [
        neighbour_entry("n1", "ethernet-1/1"), neighbour_entry("n3", "ethernet-1/1")]
    verdict = verified(lab)

    assert verdict.status == "nonconforming"
    assert verdict.counts == Counts(held=8 + 5 + 3 + 2, failed=1, skipped=3 + 2)
    assert errors(verdict) == [(verify.RULE_PORT_NEIGHBOR, "n2:ethernet-1/1")]
    assert "2 neighbours" in message(verdict, verify.RULE_PORT_NEIGHBOR, "n2:ethernet-1/1")


@pytest.mark.parametrize("configured", [True, False], ids=["configured", "unconfigured"])
def test_a_node_that_reports_no_host_name_fails_and_the_neighbours_facing_it_are_skipped(
    store: LocalStore, configured: bool
) -> None:
    lab = ready(store)
    del lab.facts("n1")[SRL.host_name]
    nodes = tuple(n if configured or n.name != "n1" else dataclasses.replace(n, config=None)
                  for n in lab.manifest.nodes)
    verdict = verified(lab, manifest=dataclasses.replace(lab.manifest, nodes=nodes))

    assert verdict.status == "nonconforming"
    assert errors(verdict) == [(verify.RULE_HOST_NAME, "n1")]
    assert message(verdict, verify.RULE_HOST_NAME, "n1") == "n1 reports no host name."
    for port in ("n2:ethernet-1/1", "n3:ethernet-1/2"):  # the two ends facing n1
        assert "n1 reports no host name" in message(verdict, verify.RULE_SKIPPED, port)
    if configured:
        # held: 8 enabled ports, 4 neighbours, 3 claims, 2 bursts; skipped: n2's and n3's host
        # names, 2 synthesized neighbours, the 2 neighbours facing n1.
        assert verdict.counts == Counts(held=8 + 4 + 3 + 2, failed=1, skipped=2 + 2 + 2)
    else:
        # As configured, but n1 makes no claim: one claim fewer held, one more skipped.
        assert verdict.counts == Counts(held=8 + 4 + 2 + 2, failed=1, skipped=2 + 2 + 2 + 1)


def test_a_neighbour_s_port_is_judged_by_the_far_port_s_node_name_not_its_production_name(
    store: LocalStore,
) -> None:
    lab = ready(store)
    # n2:ethernet-1/1 as its node names it otherwise, as a rename would: the seed and the paths follow the row.
    rows = tuple(dataclasses.replace(r, node_name="ethernet-1/9") if (r.device, r.interface) == ("n2", "ethernet-1/1")
                 else r for r in lab.manifest.mapping)
    manifest = dataclasses.replace(lab.manifest, mapping=rows)
    lab.reader.seed("t", manifest, PLATFORMS)
    near = at(SRL.port.neighbor.path, "ethernet-1/1")
    assert lab.facts("n1")[near] == [neighbour_entry("n2", "ethernet-1/9")]  # LLDP carries the node's own name
    verdict = verified(lab, manifest=manifest)
    assert verdict.status == "ok" and verdict.counts == BASELINE
    asked = dict(lab.reader.calls)["n2"]  # n2's own reads of the port are by its node name too
    assert {at(SRL.port.enabled.path, "ethernet-1/9"), at(SRL.port.neighbor.path, "ethernet-1/9")} <= set(asked)

    lab.facts("n1")[near] = [neighbour_entry("n2", "ethernet-1/1")]  # the far port's production name
    verdict = verified(lab, manifest=manifest)
    assert verdict.status == "nonconforming"
    assert errors(verdict) == [(verify.RULE_PORT_NEIGHBOR, "n1:ethernet-1/1")]
    assert message(verdict, verify.RULE_PORT_NEIGHBOR, "n1:ethernet-1/1") == (
        "n1:ethernet-1/1 lists its neighbour as n2 on ethernet-1/1, not n2 on ethernet-1/9.")


def test_an_eos_node_s_neighbour_is_read_one_container_below_the_entry(store: LocalStore) -> None:
    lab = ready(store, "testdata/blueprint/mixed.json")
    near = at(EOS.port.neighbor.path, "Ethernet1")
    assert lab.facts("e1")[near] == [{"state": {"system-name": "s1", "port-id": "ethernet-1/1"}}]
    verdict = verified(lab)
    assert verdict.status == "ok" and verdict.counts == Counts(held=6 + 6 + 3, failed=0, skipped=3)

    lab.facts("e1")[near] = [{"state": {"system-name": "s1", "port-id": "ethernet-1/2"}}]
    verdict = verified(lab)
    assert verdict.status == "nonconforming" and errors(verdict) == [(verify.RULE_PORT_NEIGHBOR, "e1:Ethernet1")]

    # The entry as cEOS 4.32.0.2F answers it and the reader hands it on: its members prefixed.
    lab.facts("e1")[near] = [{"openconfig-lldp:id": "1", "openconfig-lldp:state": {
        "id": "1", "port-id": "ethernet-1/1", "port-id-type": "INTERFACE_NAME", "system-name": "s1"}}]
    assert verified(lab).status == "ok"


def test_a_port_intent_disables_and_its_link_are_skipped_at_both_ends(store: LocalStore) -> None:
    lab = ready(store, "testdata/blueprint/steps/three-node-n1-disabled.json")
    verdict = verified(lab)

    assert verdict.status == "ok"
    # held: 5 enabled ports, 4 neighbours, 3 claims; skipped: 3 host names, n1:ethernet-1/2's state, 2 neighbours.
    assert verdict.counts == Counts(held=5 + 4 + 3, failed=0, skipped=3 + 1 + 2)
    assert skipped(verdict) == ["n1", "n1:ethernet-1/2", "n1:ethernet-1/2", "n2", "n3", "n3:ethernet-1/2"]

    lab.facts("n3")[at(SRL.port.enabled.path, "ethernet-1/2")] = "disable"  # its far end is still asserted
    verdict = verified(lab)
    assert verdict.status == "nonconforming" and errors(verdict) == [(verify.RULE_PORT_ENABLED, "n3:ethernet-1/2")]
    assert "disable" in message(verdict, verify.RULE_PORT_ENABLED, "n3:ethernet-1/2")


def test_an_unreported_enabled_leaf_means_the_package_s_absent(store: LocalStore) -> None:
    lab = ready(store)
    del lab.facts("n2")[at(SRL.port.enabled.path, "ethernet-1/1")]
    verdict = verified(lab)
    assert verdict.status == "nonconforming" and errors(verdict) == [(verify.RULE_PORT_ENABLED, "n2:ethernet-1/1")]


def test_a_claim_not_held_fails(store: LocalStore) -> None:
    lab = ready(store)
    nodes = tuple(dataclasses.replace(n, holds=OTHER_BUNDLE) if n.name == "n1" else n
                  for n in lab.record.status.nodes)
    record = dataclasses.replace(lab.record, status=dataclasses.replace(lab.record.status, nodes=nodes))
    verdict = verified(lab, record=record)

    assert verdict.status == "nonconforming"
    assert verdict.counts == Counts(held=BASELINE.held - 1, failed=1, skipped=BASELINE.skipped)
    assert errors(verdict) == [(verify.RULE_CLAIM, "n1")]
    assert OTHER_BUNDLE in message(verdict, verify.RULE_CLAIM, "n1")


def test_an_unmanaged_node_makes_no_claim_and_its_host_name_is_asserted(store: LocalStore) -> None:
    lab = ready(store, "testdata/blueprint/three-node-unmanaged.json")
    verdict = verified(lab)

    assert verdict.status == "ok"
    # held: 6 enabled ports, 6 neighbours, 2 claims, n2's host name; skipped: 2 host names, n2's claim.
    assert verdict.counts == Counts(held=6 + 6 + 2 + 1, failed=0, skipped=2 + 1)
    assert skipped(verdict) == ["n1", "n2", "n3"]
    assert "configuration" in message(verdict, verify.RULE_SKIPPED, "n2")


# The burst.


def test_a_burst_that_loses_echoes_fails_that_direction_alone(store: LocalStore) -> None:
    lab = ready(store)
    lab.driver.lossy.add(("t", "n1-loop-a"))
    verdict = verified(lab)

    assert verdict.status == "nonconforming"
    assert verdict.counts == Counts(held=BASELINE.held - 1, failed=1, skipped=BASELINE.skipped)
    assert errors(verdict) == [(verify.RULE_BURST, "n1-loop/a")]  # n1-loop/b held
    assert "3 of 5 echoes answered" in message(verdict, verify.RULE_BURST, "n1-loop/a")


def test_a_probe_whose_endpoint_intent_disables_skips_both_bursts_and_runs_no_ping(store: LocalStore) -> None:
    lab = ready(store)
    rows = tuple(dataclasses.replace(r, enabled=False) if (r.device, r.interface) == ("n1", "ethernet-1/10") else r
                 for r in lab.manifest.mapping)
    verdict = verified(lab, manifest=dataclasses.replace(lab.manifest, mapping=rows))

    assert verdict.status == "ok"
    # held: 7 enabled ports, 6 neighbours, 3 claims; skipped: 3 host names, 2 synthesized
    # neighbours, n1:ethernet-1/10's state, the 2 bursts.
    assert verdict.counts == Counts(held=7 + 6 + 3, failed=0, skipped=3 + 2 + 1 + 2)
    for about in ("n1-loop/a", "n1-loop/b"):
        text = message(verdict, verify.RULE_SKIPPED, about)
        assert "n1:ethernet-1/10" in text and "disabled by intent" in text
    assert [c for c in lab.driver.calls if c[0] == "exec" and c[3] == "ping"] == []


def test_a_probe_host_that_cannot_be_reached_is_unread_and_its_burst_skipped(store: LocalStore) -> None:
    lab = ready(store)
    lab.driver.unreachable_exec.add(("t", "n1-loop-b"))
    verdict = verified(lab)

    assert verdict.status == "failed"
    assert verdict.counts == Counts(held=BASELINE.held - 1, failed=0, skipped=BASELINE.skipped + 1)
    assert errors(verdict) == [(verify.RULE_NODE_UNREAD, "n1-loop-b")]
    assert "n1-loop/b" in skipped(verdict)


# A node that cannot be read.


def test_an_unreadable_node_fails_the_verdict_and_skips_what_faces_it(store: LocalStore) -> None:
    lab = ready(store)
    lab.reader.unreadable.add(("t", "n3"))
    verdict = verified(lab)

    assert verdict.status == "failed"
    # held: n1's 4 and n2's 2 enabled ports, the n1-n2 link's 2 neighbours, 2 claims, 2 bursts.
    # skipped: n1's and n2's host names, n3's 6 assertions, the 2 neighbours facing n3, 2 synthesized.
    assert verdict.counts == Counts(held=6 + 2 + 2 + 2, failed=0, skipped=2 + 6 + 2 + 2)
    assert errors(verdict) == [(verify.RULE_NODE_UNREAD, "n3")]
    unread = message(verdict, verify.RULE_NODE_UNREAD, "n3")
    n3 = next(n for n in lab.record.status.nodes if n.name == "n3")
    assert f"{n3.address}:57400" in unread and "UNAVAILABLE" in unread
    assert sorted(o for o in skipped(verdict) if o is not None and o.startswith("n3")) == [
        "n3", "n3", "n3:ethernet-1/1", "n3:ethernet-1/1", "n3:ethernet-1/2", "n3:ethernet-1/2"]
    assert {"n1:ethernet-1/2", "n2:ethernet-1/2"} <= set(skipped(verdict))  # the neighbours facing n3


def test_a_node_with_no_address_or_missing_from_the_record_is_unread(store: LocalStore) -> None:
    lab = ready(store)
    nodes = tuple(dataclasses.replace(n, address=None) if n.name == "n2" else n
                  for n in lab.record.status.nodes if n.name != "n3")
    record = dataclasses.replace(lab.record, status=dataclasses.replace(lab.record.status, nodes=nodes))
    verdict = verified(lab, record=record)

    assert verdict.status == "failed"
    assert errors(verdict) == [(verify.RULE_NODE_UNREAD, "n2"), (verify.RULE_NODE_UNREAD, "n3")]
    assert "no address" in message(verdict, verify.RULE_NODE_UNREAD, "n2")
    assert "no such node" in message(verdict, verify.RULE_NODE_UNREAD, "n3")
    assert [node for node, _ in lab.reader.calls] == ["n1"]
    # held: n1's 4 enabled ports, its claim, 2 bursts; every neighbour faces an unread node.
    assert verdict.counts == Counts(held=4 + 1 + 2, failed=0, skipped=3 + 4 + 6 + 2 + 2)


def test_a_missing_credential_is_an_unread_node_with_the_provider_s_message(store: LocalStore) -> None:
    lab = ready(store)
    environ = {k: v for k, v in ENVIRON.items() if k != "FYLGJA_CREDENTIAL_SRLINUX_PASSWORD"}
    verdict = verified(lab, environ=environ)

    assert verdict.status == "failed"
    assert errors(verdict) == [(verify.RULE_NODE_UNREAD, n) for n in ("n1", "n2", "n3")]
    provider = str(Missing("FYLGJA_CREDENTIAL_SRLINUX_PASSWORD"))
    assert all(provider in message(verdict, verify.RULE_NODE_UNREAD, n) for n in ("n1", "n2", "n3"))
    assert lab.reader.calls == []
    assert verdict.counts == Counts(held=2, failed=0, skipped=3 + 8 + 6 + 2 + 3)  # the bursts alone held


def test_the_nodes_are_read_at_once_and_the_bursts_after_one_at_a_time(store: LocalStore) -> None:
    lab = ready(store)
    seen: list[str] = []
    in_flight = peak = 0
    budgets: set[float] = set()

    async def reading(
        address: str,
        package: PlatformPackage,
        credential: Credential,
        paths: Sequence[str],
        *,
        timeout_s: float = gnmi.GNMI_TIMEOUT_S,
        pool: str = "",
    ) -> dict[str, Any]:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        budgets.add(timeout_s)
        try:
            return await lab.reader(address, package, credential, paths, timeout_s=timeout_s, pool=pool)
        finally:
            in_flight -= 1
            seen.append("read")

    async def running(twin: str, node: str, argv: Sequence[str], timeout_s: float) -> Exec:
        seen.append(f"exec {node} {timeout_s:g}")
        return await lab.driver.exec(twin, node, argv, timeout_s)

    bundle_id = lab.record.status.bundle_id
    assert bundle_id is not None
    verifier = Verifier(PLATFORMS, PROBES, Provider(ENVIRON), reader=reading, read_timeout_s=2.5)
    verdict = asyncio.run(verifier.verify(lab.record, lab.manifest, bundle_id, running))

    assert verdict.status == "ok" and peak == 3 and budgets == {2.5}
    assert seen == ["read"] * 3 + ["exec n1-loop-a 8", "exec n1-loop-b 8"]


def test_verify_reads_in_the_twins_own_pool(store: LocalStore) -> None:
    lab = ready(store)
    assert verified(lab).status == "ok"

    # Each node's read takes its thread from the twin's own pool, never another twin's (D-075).
    assert len(lab.reader.calls) == 3 and lab.reader.pools == [lab.record.name] * 3


def test_no_password_reaches_a_finding_or_a_log_line(store: LocalStore) -> None:
    lab = ready(store)
    lab.reader.unreadable.add(("t", "n3"))
    environ = {**ENVIRON, "FYLGJA_CREDENTIAL_SRLINUX_PASSWORD": PASSWORD}
    with json_logs() as out:
        verdict = verified(lab, environ=environ)

    assert verdict.status == "failed"
    assert PASSWORD not in json.dumps(documents.encode(verdict))
    text = out.getvalue()
    assert PASSWORD not in text
    lines = [json.loads(line) for line in text.splitlines()]
    assert any(line["logger"] == "fylgja.credentials" for line in lines)  # the provider logged, by variable name
