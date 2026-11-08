"""The clabernetes driver's live half (D-057, D-060), in the pure tier: `FakeKube` stands for the
cluster, with its own clock, so nothing waits. The driver's names, its pure calls, which are plan
3's, and `admit`, which reserves the twin's namespace and the site's values and refuses a
namespace of the twin's name that is not the twin's, and a pull credential set badly, by the
credential's own rule. `apply`, which makes the namespace, the pull secrets and the Topology and
waits for the pods: the fake's Topology status is written only by the controller's pass, the
pass that observes a new generation keeps the readiness of the one before, and a replaced pod
stays deleting and `Ready`, so a wait that trusted any of them at one read would return early. And
the one recreate `apply` makes itself, a cEOS port added after boot, under an annotation a
resumed `apply` finishes: a kill is an `apply` stopped at a call the fake fails. And `inspect`,
`endpoints`, `destroy` and `exec`, which answer as the local driver's wherever a caller of the
seam can tell: a node is its pod, its incarnation the pod's uid and its container's restart
count. And `events`, one watch on the twins' pods, which names the twin of a pod that comes, goes
or changes in what the loop reads of it, and nothing for any other change."""

from __future__ import annotations

import asyncio
import base64
import copy
import dataclasses
import hashlib
import json
import logging
import re
from collections.abc import AsyncGenerator, Callable, Mapping
from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from aio import bounded, cancelled, closed
from fake_kube import FakeKube, undecodable
from fakes import FakeDriver, FakeReader, fake_push, fake_ready
from test_containerlab_driver import apply_hot_add

from fylgja_core import blueprint, clabernetes, compiler, credentials, logs, platform_package, probe_package
from fylgja_core.clabernetes import changes as clabernetes_changes
from fylgja_core.clabernetes import plan as clabernetes_plan
from fylgja_core.clabernetes.driver import (
    _HOT_ADD,
    EXEC_UNREACHED,
    MARGIN_S,
    POLL_S,
    RECREATE_ANNOTATION,
    RENEWAL_WINDOW_S,
    RENEWALS,
    RULE_NAMESPACE,
    ClabernetesDriver,
    _current,
    deploy_budget,
    destroy_budget,
    twin_of,
)
from fylgja_core.clabernetes.kube import NODE_LABEL, KubeFailed, Pod, Service
from fylgja_core.clabernetes.plan import NAMESPACE, POLICY, TOPOLOGY
from fylgja_core.containerlab import driver as containerlab_driver
from fylgja_core.credentials import Provider
from fylgja_core.deployment import Deployment, File
from fylgja_core.driver import (
    Allocation,
    DriverFailed,
    Exec,
    Inspection,
    NodeState,
    Planned,
    Refusal,
    events_backoff,
)
from fylgja_core.local_store import LocalStore
from fylgja_core.reconcile import RESTORE_PRINCIPAL, Reconciler
from fylgja_core.twin_record import Spec, Status, TwinRecord
from fylgja_core.verify import Verifier

ROOT = Path(__file__).resolve().parents[2]
PLATFORMS = {
    p.id: p
    for p in map(platform_package.load, [ROOT / "psp/nokia_srlinux.yaml", ROOT / "psp/arista_eos.yaml",
                                         ROOT / "testdata/packages/chassisos.yaml"])
}
PROBES = {p.format: p for p in [probe_package.load(ROOT / "probes/ping.yaml")]}
ENVIRON = {
    "FYLGJA_CREDENTIAL_ARISTA_CEOS_REGISTRY": "registry.example:5000/lab",
    "FYLGJA_CREDENTIAL_ARISTA_CEOS_USERNAME": "puller",
    "FYLGJA_CREDENTIAL_ARISTA_CEOS_PASSWORD": "s3cret-value",
}
NS = "fylgja-twin-t"
ADMITTED: dict[str, Any] = {"namespace": NS, "controller_namespace": "c9s", "pod_cidr": "10.244.0.0/16",
                            "registries": {"ARISTA_CEOS": "registry.example:5000/lab"}}
TAKEN = ("The namespace fylgja-twin-t exists and is not the twin t's: it lacks the labels fylgja.owner=core and "
         "fylgja.twin=t.")


class Holding(Provider):
    """A provider whose `registries()` answers `held`, keys the real one could not produce among them,
    and whose `pull` gives each a whole login."""

    def __init__(self, held: dict[str, str]) -> None:
        environ: dict[str, str] = {}
        for key, prefix in held.items():
            environ |= {credentials.variable(key, "REGISTRY"): prefix, credentials.variable(key, "USERNAME"): "puller",
                        credentials.variable(key, "PASSWORD"): "s3cret-value"}
        super().__init__(environ)
        self._held = held

    def registries(self) -> dict[str, str]:
        return dict(self._held)


def compiled(name: str) -> compiler.Compiled:
    return compiler.compile(blueprint.load(ROOT / f"testdata/blueprint/{name}.json"), PLATFORMS, PROBES)


def driver(fake: FakeKube, provider: Provider | None = None, core_namespace: str | None = None) -> ClabernetesDriver:
    return ClabernetesDriver(fake, Provider(ENVIRON) if provider is None else provider, controller_namespace="c9s",
                             pod_cidr="10.244.0.0/16", core_namespace=core_namespace, clock=fake.clock,
                             sleep=fake.sleep)


def admit(
    fake: FakeKube,
    *,
    provider: Provider | None = None,
    core_namespace: str | None = None,
    held: Deployment | None = None,
) -> Allocation | Refusal:
    c = compiled("mixed")
    return asyncio.run(driver(fake, provider, core_namespace).admit(c.manifest, PLATFORMS, PROBES, "t", [],
                                                                    held=held))


def test_the_driver_is_clabernetes() -> None:
    d = driver(FakeKube())
    assert d.name == clabernetes.NAME == "clabernetes"
    assert d.capabilities() == clabernetes.CAPABILITIES
    assert (RULE_NAMESPACE, RECREATE_ANNOTATION, MARGIN_S, POLL_S) == (
        "admission.namespace.taken", "fylgja.recreate", 60.0, 2.0)


def test_the_driver_answers_as_the_local_driver_by_its_margin_its_unreached_statuses_and_the_hot_add_reason(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    # Each is written in both drivers, so that nothing above the seam tells them apart.
    assert MARGIN_S == containerlab_driver.MARGIN_S
    assert EXEC_UNREACHED == containerlab_driver.DOCKER_EXEC_UNREACHED
    with caplog.at_level(logging.INFO, logger="fylgja.containerlab"):
        apply_hot_add(tmp_path)  # the local driver removes e1 and e2, logging why
    removed = [m for m in caplog.messages if m.startswith("apply t: removed ")]
    assert len(removed) == 2 and all(m.endswith(f", {_HOT_ADD}") for m in removed)


def test_the_drivers_plan_and_changes_are_the_pure_ones_and_reach_no_cluster() -> None:
    fake = FakeKube()
    d = driver(fake)
    compiled_pair = compiled("three-node"), compiled("steps/two-node")
    before, after = (d.plan(c.manifest, c.id, PLATFORMS, PROBES, "t", ADMITTED) for c in compiled_pair)
    assert [before, after] == [clabernetes_plan.plan(c.manifest, c.id, PLATFORMS, PROBES, "t", ADMITTED)
                               for c in compiled_pair]
    assert d.changes(before, after, PLATFORMS, PROBES) == clabernetes_changes.changes(before, after, PLATFORMS,
                                                                                      PROBES)
    assert fake.calls == []


def test_admit_reserves_the_twins_namespace_and_the_sites_values() -> None:
    fake = FakeKube()
    assert admit(fake) == ADMITTED
    assert fake.calls == [("namespace", NS)]
    # The core's namespace is a member only when the core runs as a pod.
    assert admit(FakeKube(), core_namespace="fylgja") == {**ADMITTED, "core_namespace": "fylgja"}
    assert admit(FakeKube(), provider=Provider({})) == {**ADMITTED, "registries": {}}


@pytest.mark.parametrize("labels", [{"fylgja.owner": "core", "fylgja.twin": "u"}, {}, {"fylgja.twin": "t"}],
                         ids=["another-twins", "unlabelled", "no-owner"])
def test_a_namespace_of_the_twins_name_that_is_not_the_twins_refuses_it(
    labels: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    fake = FakeKube()
    fake.add_namespace(NS, labels)
    with caplog.at_level(logging.INFO, logger="fylgja.clabernetes"):
        assert admit(fake) == Refusal(RULE_NAMESPACE, TAKEN)
    assert f"admit t refused, {RULE_NAMESPACE}: {TAKEN}" in caplog.messages
    assert fake.calls == [("namespace", NS)]


@pytest.mark.parametrize("deleting", [False, True], ids=["standing", "deleting"])
def test_a_namespace_carrying_the_twins_labels_is_the_twins(deleting: bool) -> None:
    fake = FakeKube()
    fake.add_namespace(NS, {"fylgja.owner": "core", "fylgja.twin": "t",
                            "pod-security.kubernetes.io/enforce": "privileged"})
    fake.namespaces[NS] = dataclasses.replace(fake.namespaces[NS], deleting=deleting)
    # One still being deleted is the twin's too: apply acts once it is gone.
    assert admit(fake) == ADMITTED


OTHER = {"FYLGJA_CREDENTIAL_OTHER_REGISTRY": "registry.example:5000/other",
         "FYLGJA_CREDENTIAL_OTHER_USERNAME": "puller", "FYLGJA_CREDENTIAL_OTHER_PASSWORD": "s3cret-value"}
"""A second pull credential, whole."""


def held_on(allocation: Allocation) -> Deployment:
    """The deployment a twin stepping from `three-node` holds, planned on `allocation`."""
    c = compiled("three-node")
    return clabernetes_plan.plan(c.manifest, c.id, PLATFORMS, PROBES, "t", allocation).deployment


def test_a_stepping_twin_keeps_its_allocation_and_admit_reaches_no_cluster(caplog: pytest.LogCaptureFixture) -> None:
    # The provider holds another registry now too: the twin keeps the registries it was admitted with.
    held_allocation = {**ADMITTED, "registries": {"OTHER": "registry.example:5000/other"}}
    fake = FakeKube()
    fake.add_namespace(NS, {})
    with caplog.at_level(logging.INFO, logger="fylgja.clabernetes"):
        assert admit(fake, provider=Provider({**ENVIRON, **OTHER}), held=held_on(held_allocation)) == held_allocation
    assert fake.calls == []
    assert f"admit t: held allocation, namespace {NS}" in caplog.messages


@pytest.mark.parametrize(("environ", "rule", "variable"), [
    ({k: v for k, v in ENVIRON.items() if not k.endswith("_PASSWORD")}, credentials.RULE_MISSING,
     "FYLGJA_CREDENTIAL_ARISTA_CEOS_PASSWORD"),
    ({}, credentials.RULE_MISSING, "FYLGJA_CREDENTIAL_ARISTA_CEOS_REGISTRY"),
    ({**ENVIRON, "FYLGJA_CREDENTIAL_ARISTA_CEOS_REGISTRY": "https://registry.example:5000/lab"},
     credentials.RULE_MALFORMED, "FYLGJA_CREDENTIAL_ARISTA_CEOS_REGISTRY"),
    ({**ENVIRON, "FYLGJA_CREDENTIAL_ARISTA_CEOS_REGISTRY": "mirror.example:5000/lab"}, credentials.RULE_MALFORMED,
     "FYLGJA_CREDENTIAL_ARISTA_CEOS_REGISTRY"),
], ids=["password-missing", "removed", "malformed", "another-registry"])
def test_a_stepping_twins_pull_credential_the_provider_cannot_give_whole_refuses_the_step_reading_no_cluster(
    environ: dict[str, str], rule: str, variable: str,
) -> None:
    # Refused at admission, before the step touches anything; else every apply after would fail.
    fake = FakeKube()
    answer = admit(fake, provider=Provider(environ), held=held_on(ADMITTED))
    assert isinstance(answer, Refusal)
    assert answer.rule == rule and answer.message.startswith(f"{rule}: ") and variable in answer.message
    for value in ("registry.example", "mirror.example", "puller", "s3cret-value"):
        assert value not in answer.message
    assert fake.calls == []


def test_a_failure_reading_the_namespace_is_a_driver_failure() -> None:
    fake = FakeKube()
    fake.fail["namespace"] = [KubeFailed(f"namespace Namespace {NS}: 500 Internal Server Error", 500)]
    with pytest.raises(DriverFailed, match="500"):
        admit(fake)


def test_admit_logs_what_it_reserved_by_twin_and_never_a_value_of_a_credential(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG):
        admit(FakeKube())
    assert f"admit t: namespace {NS}; registries ARISTA_CEOS" in caplog.messages
    assert "registry.example" not in caplog.text and "s3cret-value" not in caplog.text


def test_a_malformed_registry_refuses_the_twin_by_the_credentials_rule_naming_the_variable_alone() -> None:
    environ = {**ENVIRON, "FYLGJA_CREDENTIAL_ARISTA_CEOS_REGISTRY": "https://registry.example:5000/lab"}
    answer = admit(FakeKube(), provider=Provider(environ))
    assert isinstance(answer, Refusal)
    assert answer.rule == credentials.RULE_MALFORMED == "credential.malformed"
    assert "FYLGJA_CREDENTIAL_ARISTA_CEOS_REGISTRY" in answer.message
    assert "registry.example" not in answer.message


@pytest.mark.parametrize("part", ["USERNAME", "PASSWORD"])
def test_a_pull_credential_with_its_registry_set_and_its_login_not_refuses_the_twin_naming_the_variable(
    part: str,
) -> None:
    # The registry set alone would admit the twin and then fail every apply for ever.
    environ = {k: v for k, v in ENVIRON.items() if not k.endswith(f"_{part}")}
    answer = admit(FakeKube(), provider=Provider(environ))
    missing = credentials.Missing(f"FYLGJA_CREDENTIAL_ARISTA_CEOS_{part}")
    assert answer == Refusal(credentials.RULE_MISSING, str(missing))
    assert "registry.example" not in str(missing) and "s3cret-value" not in str(missing)


@pytest.mark.parametrize("key", ["ARISTA_", "A" * 242, "ARISTA CEOS"], ids=["trailing-underscore", "long", "space"])
def test_a_registry_key_whose_pull_secret_kubernetes_would_refuse_refuses_the_twin(key: str) -> None:
    fake = FakeKube()
    answer = admit(fake, provider=Holding({"ARISTA_CEOS": "registry.example:5000/lab", key: "registry.example:5000"}))
    assert isinstance(answer, Refusal)
    assert answer.rule == credentials.RULE_MALFORMED
    assert f"FYLGJA_CREDENTIAL_{key}_REGISTRY" in answer.message
    assert clabernetes.pull_secret(key) in answer.message
    assert "registry.example" not in answer.message


def test_a_pull_secret_name_of_253_characters_is_one_kubernetes_accepts() -> None:
    key = "A" * 241
    assert len(clabernetes.pull_secret(key)) == 253
    answer = admit(FakeKube(), provider=Holding({key: "registry.example:5000/lab"}))
    assert answer == {**ADMITTED, "registries": {key: "registry.example:5000/lab"}}


# apply.

BARE: dict[str, Any] = {**ADMITTED, "registries": {}}
"""The allocation of a twin admitted with no pull credential set: its Topology names no pull secret."""
OWNED = {"fylgja.owner": "core", "fylgja.twin": "t"}
NODES = ("n1", "n2", "n3")
LOCAL = {"spec": {"externalTrafficPolicy": "Local"}}
NOT_READY = "the twin t was not ready within 240s: the Topology t has not observed its generation 1; no ready pod for "


def planned(name: str, allocation: Allocation = BARE) -> Planned:
    c = compiled(name)
    return clabernetes_plan.plan(c.manifest, c.id, PLATFORMS, PROBES, "t", allocation)


def apply(
    fake: FakeKube,
    p: Planned,
    *,
    provider: Provider | None = None,
    deployment: Deployment | None = None,
    files: Mapping[str, bytes] | None = None,
    reconfigure: bool = False,
) -> None:
    asyncio.run(driver(fake, provider).apply(p.deployment if deployment is None else deployment,
                                             p.files if files is None else files, PLATFORMS, PROBES,
                                             reconfigure=reconfigure))


def listing(deployment: Deployment, files: Mapping[str, bytes]) -> Deployment:
    """`deployment` listing `files` as its own, each with its SHA-256."""
    listed = tuple(File(path=path, sha256=hashlib.sha256(data).hexdigest()) for path, data in sorted(files.items()))
    return dataclasses.replace(deployment, files=listed)


def uids(fake: FakeKube) -> dict[str, str]:
    return {node: fake.pod_of(NS, node).uid for node in NODES}


def pods_of(fake: FakeKube, node: str) -> list[Pod]:
    return [p for p in asyncio.run(fake.pods(NS, {})) if p.labels.get(NODE_LABEL) == node]


def test_apply_applies_the_namespace_the_policy_and_the_topology_as_rendered(caplog: pytest.LogCaptureFixture) -> None:
    fake = FakeKube()
    p = planned("three-node")
    with caplog.at_level(logging.INFO, logger="fylgja.clabernetes"):
        apply(fake, p)
    assert [c[:2] for c in fake.calls if c[0] == "apply"] == [
        ("apply", "Namespace"), ("apply", "NetworkPolicy"), ("apply", "Topology")]
    assert fake.objects[("Namespace", None, NS)] == yaml.safe_load(p.files[NAMESPACE])
    assert fake.objects[("NetworkPolicy", NS, "fylgja-isolation")] == yaml.safe_load(p.files[POLICY])
    assert fake.objects[("Topology", NS, "t")] == yaml.safe_load(p.files[TOPOLOGY])
    assert [m for m in caplog.messages if " applied " in m] == [
        f"apply t: applied Namespace {NS}", "apply t: applied NetworkPolicy fylgja-isolation",
        "apply t: applied Topology t"]
    assert all(fake.pod_of(NS, node).ready for node in NODES)


def test_apply_makes_each_pull_secret_from_the_provider_before_the_topology_and_writes_no_value_of_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = FakeKube()
    p = planned("mixed", ADMITTED)
    with caplog.at_level(logging.DEBUG):
        apply(fake, p)
    assert [c[1] for c in fake.calls if c[0] == "apply"] == ["Namespace", "NetworkPolicy", "Secret", "Topology"]
    [name] = yaml.safe_load(p.files[TOPOLOGY])["spec"]["imagePull"]["pullSecrets"]
    secret = fake.objects[("Secret", NS, name)]
    assert secret["metadata"] == {"name": name, "namespace": NS, "labels": OWNED}
    assert secret["type"] == "kubernetes.io/dockerconfigjson"
    assert list(secret["data"]) == [".dockerconfigjson"]
    login = base64.b64encode(b"puller:s3cret-value").decode()
    assert json.loads(base64.b64decode(secret["data"][".dockerconfigjson"])) == {
        "auths": {"registry.example:5000": {"username": "puller", "password": "s3cret-value", "auth": login}}}
    assert f"apply t: applied Secret {name}" in caplog.messages
    for value in ("s3cret-value", login, secret["data"][".dockerconfigjson"]):
        assert value not in caplog.text
        assert not any(value.encode() in data for data in p.files.values())


@pytest.mark.parametrize(("environ", "rule", "variable"), [
    ({k: v for k, v in ENVIRON.items() if not k.endswith("_PASSWORD")}, credentials.RULE_MISSING,
     "FYLGJA_CREDENTIAL_ARISTA_CEOS_PASSWORD"),
    ({**ENVIRON, "FYLGJA_CREDENTIAL_ARISTA_CEOS_REGISTRY": "https://registry.example:5000/lab"},
     credentials.RULE_MALFORMED, "FYLGJA_CREDENTIAL_ARISTA_CEOS_REGISTRY"),
], ids=["missing", "malformed"])
def test_a_pull_credential_the_provider_refuses_fails_the_apply_before_any_secret_or_the_topology(
    environ: dict[str, str], rule: str, variable: str,
) -> None:
    fake = FakeKube()
    with pytest.raises(DriverFailed, match=variable) as caught:
        apply(fake, planned("mixed", ADMITTED), provider=Provider(environ))
    assert str(caught.value).startswith(f"{rule}: ")
    assert "registry.example" not in str(caught.value) and "s3cret-value" not in str(caught.value)
    assert [c[1] for c in fake.calls if c[0] == "apply"] == ["Namespace", "NetworkPolicy"]


def test_a_twin_admitted_with_a_registry_holds_its_pull_secret_though_no_node_uses_its_image() -> None:
    # The Topology names every registry's pull secret (D-069), and clabernetes makes no pod while
    # one it names is missing (verified-facts.md): an SR Linux twin needs the cEOS Secret too.
    fake = FakeKube()
    p = planned("three-node", ADMITTED)
    apply(fake, p)
    [name] = yaml.safe_load(p.files[TOPOLOGY])["spec"]["imagePull"]["pullSecrets"]
    assert ("Secret", NS, name) in fake.objects
    assert all(fake.pod_of(NS, node).ready for node in NODES)


def test_every_pull_credential_is_read_before_the_first_secret_is_applied() -> None:
    # The second key's login missing: the first key's Secret is not left applied.
    fake = FakeKube()
    two = {**ADMITTED, "registries": {**ADMITTED["registries"], "OTHER": "registry.example:5000/other"}}
    environ = {**ENVIRON, "FYLGJA_CREDENTIAL_OTHER_REGISTRY": "registry.example:5000/other"}
    with pytest.raises(DriverFailed, match="FYLGJA_CREDENTIAL_OTHER_USERNAME"):
        apply(fake, planned("mixed", two), provider=Provider(environ))
    assert [c[1] for c in fake.calls if c[0] == "apply"] == ["Namespace", "NetworkPolicy"]


@pytest.mark.parametrize("prefix", ["registry.example:5000/lab", "registry.example:5000"], ids=["path", "host"])
def test_a_pull_secret_holds_the_login_under_the_host_of_the_allocations_prefix(prefix: str) -> None:
    fake = FakeKube()
    allocation = {**ADMITTED, "registries": {"ARISTA_CEOS": prefix}}
    apply(fake, planned("mixed", allocation),
          provider=Provider({**ENVIRON, "FYLGJA_CREDENTIAL_ARISTA_CEOS_REGISTRY": prefix}))
    secret = fake.objects[("Secret", NS, clabernetes.pull_secret("ARISTA_CEOS"))]
    assert list(json.loads(base64.b64decode(secret["data"][".dockerconfigjson"]))["auths"]) == ["registry.example:5000"]


def test_a_pull_credential_whose_registry_is_not_the_admitted_prefix_fails_the_apply_naming_its_variable() -> None:
    # The Topology's images carry the prefix fixed at admission: a Secret for another registry
    # would let no node pull, and the deploy budget would run out naming only unready nodes.
    fake = FakeKube()
    environ = {**ENVIRON, "FYLGJA_CREDENTIAL_ARISTA_CEOS_REGISTRY": "mirror.example:5000/lab"}
    with pytest.raises(DriverFailed, match="FYLGJA_CREDENTIAL_ARISTA_CEOS_REGISTRY") as caught:
        apply(fake, planned("mixed", ADMITTED), provider=Provider(environ))
    for value in ("registry.example", "mirror.example", "s3cret-value", "puller"):
        assert value not in str(caught.value)
    assert [c[1] for c in fake.calls if c[0] == "apply"] == ["Namespace", "NetworkPolicy"]


def test_apply_waits_for_every_pod_and_then_patches_each_load_balancer_to_local_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = FakeKube()
    fake.ready_s, fake.settle_s = 50, 3
    with caplog.at_level(logging.INFO, logger="fylgja.clabernetes"):
        apply(fake, planned("three-node"))
    assert fake.now >= 50
    patched = [i for i, c in enumerate(fake.calls) if c[0] == "patch_service"]
    assert [fake.calls[i] for i in patched] == [("patch_service", NS, node, LOCAL) for node in NODES]
    assert max(i for i, c in enumerate(fake.calls) if c[0] == "pods") < min(patched)  # after the wait
    balancers = [s for s in asyncio.run(fake.services(NS)) if s.type == "LoadBalancer"]
    assert [(s.name, s.traffic_policy) for s in balancers] == [(node, "Local") for node in NODES]
    assert [f"apply t: patched the Service {node} to externalTrafficPolicy Local (D-037)" for node in NODES] == [
        m for m in caplog.messages if "patched" in m]


class Unbalanced(FakeKube):
    """`FakeKube` whose `services` answers no Service of a name in `hidden`: a node's LoadBalancer
    not yet made."""

    def __init__(self) -> None:
        super().__init__()
        self.hidden: set[str] = set()

    async def services(self, namespace: str) -> list[Service]:
        return [s for s in await super().services(namespace) if s.name not in self.hidden]


def test_apply_waits_for_a_load_balancer_for_each_node_that_declares_ports() -> None:
    fake = Unbalanced()
    fake.hidden = {"n2"}
    fake.at(50, fake.hidden.clear)
    apply(fake, planned("three-node"))
    assert fake.now >= 50
    assert ("patch_service", NS, "n2", LOCAL) in fake.calls


def test_a_node_that_declares_ports_never_given_a_load_balancer_fails_the_apply_naming_it() -> None:
    fake = Unbalanced()
    fake.hidden = {"n2"}
    with pytest.raises(DriverFailed, match=re.escape("the twin t was not ready within 240s: no LoadBalancer Service "
                                                     "for n2")):
        apply(fake, planned("three-node"))


def test_apply_waits_until_each_load_balancer_has_its_address_and_names_one_that_never_has() -> None:
    fake = FakeKube()
    fake.address_s = {"n2": 50}
    apply(fake, planned("three-node"))
    assert fake.now >= 50
    never = FakeKube()
    never.address_s = {"n2": 10_000}
    with pytest.raises(DriverFailed, match=re.escape("the twin t was not ready within 240s: no address for the "
                                                     "Services n2")):
        apply(never, planned("three-node"))


WINDOW_S = 1.5
"""The fake's `settle_s` for a stale status narrower than a poll, as on the cluster (about 0.14 s
against `POLL_S`): the generation is observed at +1.5 s, still ready from before, and the pass that
reconciles it comes at +3 s, so the wait's read at +2 s falls inside the window."""


def test_a_step_that_only_re_cables_returns_once_its_own_generation_reads_ready_twice() -> None:
    # Until the controller's pass, the Topology reads the generation before; then, at +1.5 s, its
    # generation observed and still ready from before, every pod as it was. A wait that believed
    # that one read would return at +2 s, before the re-cable's status is written.
    fake = FakeKube()
    apply(fake, planned("three-node"))
    before = uids(fake)
    fake.settle_s = WINDOW_S
    start = fake.now
    apply(fake, planned("steps/three-node-unlinked"))
    # Observed at +1.5, not ready at +3 (read at +4), ready at +4.5: read ready at +6 and at +8.
    assert fake.now == start + 8
    assert uids(fake) == before


def test_a_step_that_replaces_a_node_returns_at_its_new_pod_not_on_the_status_left_from_before() -> None:
    fake = FakeKube()
    apply(fake, planned("three-node", ADMITTED))
    before = uids(fake)
    fake.replaces = {"n3"}
    fake.settle_s, fake.terminate_s, fake.ready_s = WINDOW_S, 5, 30
    apply(fake, planned("steps/three-node-n3-eos", ADMITTED))
    after = uids(fake)
    assert after["n3"] != before["n3"] and fake.pod_of(NS, "n3").ready
    assert {node: after[node] for node in ("n1", "n2")} == {node: before[node] for node in ("n1", "n2")}


def test_a_step_that_removes_a_node_waits_until_its_pod_is_gone() -> None:
    fake = FakeKube()
    apply(fake, planned("three-node"))
    fake.settle_s, fake.terminate_s = 10, 30
    start = fake.now
    apply(fake, planned("steps/two-node"))
    # Observed at +10; reconciled at +20, when n3's pod begins to go; ready at +30, while it is still
    # listed, deleting, until +50.
    assert fake.now >= start + 20 + 30
    assert pods_of(fake, "n3") == []


def test_a_node_whose_pod_is_being_replaced_is_waited_for_at_its_new_pod() -> None:
    # The old pod is deleting and still Ready, and the Topology reads ready until the controller's
    # pass: a wait that trusted either would return at once.
    fake = FakeKube()
    p = planned("three-node")
    apply(fake, p)
    old = fake.pod_of(NS, "n1")
    fake.settle_s = fake.terminate_s = 5
    fake.terminate(NS, "n1")
    start = fake.now
    fake.at(40, lambda: fake.set_ready(NS, "n1", True))
    apply(fake, p)
    assert fake.now >= start + 40
    new = fake.pod_of(NS, "n1")
    assert new.uid != old.uid and new.ready and not new.deleting
    assert not any(c[0] == "delete_pod" for c in fake.calls)


def test_a_nodes_pod_is_its_newest_not_being_deleted_whether_or_not_it_is_ready() -> None:
    # The newer pod's name sorts first, so only its creation time makes it the node's.
    older = Pod(name="n1-b", namespace=NS, uid="uid-1", labels={NODE_LABEL: "n1"}, phase="Running", ready=True,
                deleting=False, created="2026-11-05T00:00:00+00:00", restarts=0, container_running=True)
    newer = dataclasses.replace(older, name="n1-a", uid="uid-2", phase="Pending", ready=False,
                                created="2026-11-05T00:00:05+00:00", container_running=False)
    assert _current([older, newer], "n1") == _current([newer, older], "n1") == newer
    # The newest deleting and still Ready, the older standing: the older is the node's; a node
    # whose only pod is deleting has none.
    going = dataclasses.replace(older, name="n1-c", uid="uid-3", created="2026-11-05T00:00:10+00:00", deleting=True)
    assert _current([older, going], "n1") == _current([going, older], "n1") == older
    assert _current([going], "n1") is None


def test_a_twin_never_ready_fails_the_apply_once_the_deploy_budget_has_passed() -> None:
    fake = FakeKube()
    fake.controller = False
    start = fake.now
    with pytest.raises(DriverFailed, match=re.escape(NOT_READY + "n1, n2, n3")):
        apply(fake, planned("three-node"))
    assert 240 <= fake.now - start < 240 + 2 * POLL_S  # SR Linux's 180 s, and the minute


def test_a_twin_observed_whose_pods_are_not_ready_within_the_budget_fails_the_apply_once_it_has_passed() -> None:
    # The controller on: the generation observed at +30 s, the pods made at +60 s and Ready only at
    # +360 s. The settled wait shares the one budget the first wait began.
    fake = FakeKube()
    fake.settle_s, fake.ready_s = 30, 300
    start = fake.now
    with pytest.raises(DriverFailed, match=re.escape("the twin t was not ready within 240s: the Topology t is not "
                                                     "ready; no ready pod for n1, n2, n3")):
        apply(fake, planned("three-node"))
    assert 240 <= fake.now - start < 240 + 2 * POLL_S


def test_the_budgets_are_the_slowest_package_the_topologys_nodes_use_plus_a_minute() -> None:
    mixed = planned("mixed", ADMITTED)
    registries = ADMITTED["registries"]
    assert deploy_budget(planned("three-node").files, PLATFORMS, PROBES, {}) == 180 + 60
    assert deploy_budget(mixed.files, PLATFORMS, PROBES, registries) == 300 + 60  # cEOS, under its prefix
    assert deploy_budget(planned("three-node-probed").files, PLATFORMS, PROBES, {}) == 180 + 60
    assert destroy_budget(planned("three-node").files, PLATFORMS, PROBES, {}) == 60 + 60
    eos = PLATFORMS["arista_eos"]
    clab = dataclasses.replace(eos.runtime.containerlab, destroy_timeout_s=90)
    slow = {**PLATFORMS, "arista_eos": dataclasses.replace(eos, runtime=dataclasses.replace(eos.runtime,
                                                                                            containerlab=clab))}
    assert destroy_budget(mixed.files, slow, PROBES, registries) == 90 + 60
    # The registries are the deployment's: under none that write its image, no package runs a gated node.
    unrun = r"no package given runs the node e1 \(ceos, registry\.example:5000/lab/ceos:4\.32\.0\.2F\)"
    with pytest.raises(ValueError, match=unrun):
        deploy_budget(mixed.files, PLATFORMS, PROBES, {})


@pytest.mark.parametrize("labels", [{"fylgja.owner": "core", "fylgja.twin": "u"}, {}],
                         ids=["another-twins", "unlabelled"])
def test_a_namespace_of_the_twins_name_that_is_not_the_twins_fails_the_apply_and_is_left_as_it_is(
    labels: dict[str, str],
) -> None:
    fake = FakeKube()
    fake.add_namespace(NS, labels)
    with pytest.raises(DriverFailed, match=re.escape(f"the namespace {NS} exists and is not the twin t's: it lacks "
                                                     "the labels fylgja.owner=core and fylgja.twin=t")):
        apply(fake, planned("three-node"))
    assert not any(c[0] == "apply" for c in fake.calls)
    assert fake.namespaces[NS].labels == {**labels, "kubernetes.io/metadata.name": NS}


def test_a_twins_namespace_being_deleted_fails_the_apply_until_it_is_gone() -> None:
    fake = FakeKube()
    fake.namespace_delete_s = 30
    fake.add_namespace(NS, OWNED)
    asyncio.run(fake.delete_namespace(NS))
    p = planned("three-node")
    with pytest.raises(DriverFailed, match=re.escape(f"the namespace {NS} is being deleted: the twin t is applied "
                                                     "once it is gone")):
        apply(fake, p)
    assert not any(c[0] == "apply" for c in fake.calls)
    asyncio.run(fake.sleep(30))
    assert NS not in fake.namespaces
    apply(fake, p)
    assert not fake.namespaces[NS].deleting and OWNED.items() <= fake.namespaces[NS].labels.items()
    assert all(fake.pod_of(NS, node).ready for node in NODES)


def test_a_repeat_apply_deletes_no_pod_patches_no_service_and_keeps_every_uid() -> None:
    fake = FakeKube()
    fake.settle_s = fake.terminate_s = 3
    p = planned("three-node")
    apply(fake, p)
    before, mark = uids(fake), len(fake.calls)
    apply(fake, p)
    assert not any(c[0] in ("delete_pod", "patch_service") for c in fake.calls[mark:])
    assert uids(fake) == before


def test_reconfigure_replaces_every_pod_after_the_topologys_apply_and_waits_for_the_new_ones(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = FakeKube()
    p = planned("three-node")
    apply(fake, p)
    old = {node: fake.pod_of(NS, node) for node in NODES}
    fake.settle_s, fake.ready_s, fake.terminate_s = 5, 30, 10
    mark, start = len(fake.calls), fake.now
    with caplog.at_level(logging.INFO, logger="fylgja.clabernetes"):
        apply(fake, p, reconfigure=True)
    calls = fake.calls[mark:]
    deleted = [i for i, c in enumerate(calls) if c[0] == "delete_pod"]
    assert [calls[i] for i in deleted] == [("delete_pod", NS, old[node].name) for node in NODES]
    assert min(deleted) > calls.index(("apply", "Topology", NS, "t"))
    assert fake.now >= start + 30
    for node in NODES:
        new = fake.pod_of(NS, node)
        assert new.uid != old[node].uid and new.ready and not new.deleting
        assert (f"apply t: deleted the pod {old[node].name} (uid {old[node].uid}) of the node {node}, since "
                "reconfigure makes every node anew") in caplog.messages


def test_a_probe_host_gets_a_pod_and_no_load_balancer() -> None:
    fake = FakeKube()
    apply(fake, planned("three-node-probed"))
    assert fake.pod_of(NS, "n1-loop-a").ready
    names = [s.name for s in asyncio.run(fake.services(NS))]
    assert "n1-loop-a" not in names and "n1-loop-a-wire" in names


def test_what_is_not_a_clabernetes_deployment_of_the_twin_is_refused_before_any_call() -> None:
    fake = FakeKube()
    p = planned("three-node")
    changed = {**p.files, TOPOLOGY: p.files[TOPOLOGY] + b"\n"}
    missing = {path: data for path, data in p.files.items() if path != POLICY}
    for files in (changed, missing):
        with pytest.raises(ValueError, match="not the deployment's"):
            apply(fake, p, files=files)
    extra = {**p.files, "extra.yaml": b"kind: Extra\n"}
    with pytest.raises(ValueError, match=r"are not a clabernetes deployment's"):
        apply(fake, p, deployment=listing(p.deployment, extra), files=extra)
    elsewhere = dataclasses.replace(p.deployment, allocation={**BARE, "namespace": "fylgja-twin-u"})
    with pytest.raises(ValueError, match="the deployment's namespace 'fylgja-twin-u' is not the twin t's"):
        apply(fake, p, deployment=elsewhere)
    for text in (b"a: 1\n---\nb: 2\n", b"- a list\n", b"{unclosed\n"):
        files = {**p.files, POLICY: text}
        with pytest.raises(ValueError, match=r"networkpolicy\.yaml is not one YAML mapping"):
            apply(fake, p, deployment=listing(p.deployment, files), files=files)
    m = planned("mixed", ADMITTED)
    with pytest.raises(ValueError, match="no package given runs the node e1"):
        asyncio.run(driver(fake).apply(m.deployment, m.files, {"nokia_srlinux": PLATFORMS["nokia_srlinux"]}, PROBES))
    assert fake.calls == []


@pytest.mark.parametrize(("path", "member", "value", "message"), [
    (NAMESPACE, ("kind",), "ConfigMap", "its kind is 'ConfigMap', not Namespace"),
    (NAMESPACE, ("metadata", "name"), "fylgja-twin-u", "its name is 'fylgja-twin-u', not fylgja-twin-t"),
    (POLICY, ("kind",), "Namespace", "its kind is 'Namespace', not NetworkPolicy"),
    (POLICY, ("metadata", "namespace"), "fylgja-twin-u", "its namespace is 'fylgja-twin-u', not fylgja-twin-t"),
    (POLICY, ("metadata", "namespace"), None, "its namespace is None, not fylgja-twin-t"),
    (TOPOLOGY, ("kind",), "Deployment", "its kind is 'Deployment', not Topology"),
    (TOPOLOGY, ("metadata", "namespace"), "default", "its namespace is 'default', not fylgja-twin-t"),
    (TOPOLOGY, ("metadata", "name"), "u", "its name is 'u', not t"),
], ids=["namespace-kind", "namespace-name", "policy-kind", "policy-namespace", "policy-no-namespace",
        "topology-kind", "topology-namespace", "topology-name"])
def test_a_document_bound_elsewhere_than_the_twins_namespace_is_refused_before_any_call(
    path: str, member: tuple[str, ...], value: str | None, message: str,
) -> None:
    # Each file is the deployment's, by its SHA-256, and still not what the plan renders for the twin.
    fake = FakeKube()
    p = planned("three-node")
    document = yaml.safe_load(p.files[path])
    held = document
    for key in member[:-1]:
        held = held[key]
    if value is None:
        del held[member[-1]]
    else:
        held[member[-1]] = value
    files = {**p.files, path: yaml.safe_dump(document).encode()}
    with pytest.raises(ValueError, match=re.escape(f"{path} is not the twin t's: {message}")):
        apply(fake, p, deployment=listing(p.deployment, files), files=files)
    assert fake.calls == []


def test_an_apply_cancelled_while_it_waits_stops_where_it_is() -> None:
    fake = FakeKube()
    fake.settle_s = 20
    p = planned("three-node")

    async def body() -> None:
        task = asyncio.create_task(driver(fake).apply(p.deployment, p.files, PLATFORMS, PROBES, reconfigure=True))
        while fake.now < 10 and not task.done():
            await asyncio.sleep(0)
        await cancelled(task)

    bounded(body)
    assert 10 <= fake.now < 20  # before the Topology was observed, and so before reconfigure's deletions
    assert ("apply", "Topology", NS, "t") in fake.calls
    assert not any(c[0] == "delete_pod" for c in fake.calls)


# The hot-add recreate: a cEOS port added after boot arrives only with a new pod.

MIXED = ("e1", "e2", "s1")
HOT_ADD = "since it gains a port its kind cannot add after boot"


class Recording(FakeKube):
    """`FakeKube` keeping the annotations of each Topology it is given to apply, in order, a
    killed apply's too (`objects` holds only the last); each read of the Topology `t`, as its time,
    its generation and whether that is observed; and, at each pod's deletion, its time and whether
    the Topology `t` had observed its generation."""

    def __init__(self) -> None:
        super().__init__()
        self.annotations: list[dict[str, str] | None] = []
        self.reads: list[tuple[float, int, bool]] = []
        self.observed: list[bool] = []
        self.deleted_at: list[float] = []

    async def apply(self, obj: Mapping[str, Any]) -> None:
        if obj["kind"] == "Topology":
            self.annotations.append(copy.deepcopy(obj["metadata"].get("annotations")))
        await super().apply(obj)

    async def topology(self, namespace: str, name: str) -> Mapping[str, Any] | None:
        found = await super().topology(namespace, name)
        if found is not None and name == "t":
            generation = found["metadata"]["generation"]
            observed = (found.get("status") or {}).get("observedGeneration") == generation
            self.reads.append((self.now, generation, observed))
        return found

    async def delete_pod(self, namespace: str, name: str) -> None:
        self.observed.append(self._observed.get((namespace, "t")) == self._generations.get((namespace, "t")))
        self.deleted_at.append(self.now)
        await super().delete_pod(namespace, name)


def stepped() -> tuple[Recording, Planned, dict[str, Pod]]:
    """`mixed` applied and settled, then the controller's passes and a pod's going made slow;
    the step adding a link between e1 and e2 on two ports configured and uncabled, planned on
    the same allocation; and each node's pod before it."""
    fake = Recording()
    apply(fake, planned("mixed", ADMITTED))
    fake.settle_s, fake.terminate_s, fake.ready_s = 5, 10, 20
    return fake, planned("steps/mixed-e2-port", ADMITTED), {node: fake.pod_of(NS, node) for node in MIXED}


def recreating(*pods: Pod) -> dict[str, str]:
    """The annotation an apply makes to replace `pods`."""
    pending = {pod.labels[NODE_LABEL]: pod.uid for pod in pods}
    return {RECREATE_ANNOTATION: json.dumps(pending, sort_keys=True, separators=(",", ":"))}


def held_annotations(fake: FakeKube) -> dict[str, str] | None:
    """The annotations of the Topology the cluster holds."""
    annotations: dict[str, str] | None = fake.objects[("Topology", NS, "t")]["metadata"].get("annotations")
    return annotations


def test_a_port_added_after_boot_replaces_the_nodes_pod_under_an_annotation_the_apply_then_removes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake, step, old = stepped()
    mark, applied = len(fake.calls), len(fake.annotations)
    with caplog.at_level(logging.INFO, logger="fylgja.clabernetes"):
        apply(fake, step)
    calls = fake.calls[mark:]
    assert fake.annotations[applied:] == [recreating(old["e1"], old["e2"]), None]
    topologies = [i for i, c in enumerate(calls) if c[:2] == ("apply", "Topology")]
    deleted = [i for i, c in enumerate(calls) if c[0] == "delete_pod"]
    assert [calls[i] for i in deleted] == [("delete_pod", NS, old[node].name) for node in ("e1", "e2")]
    assert topologies[0] < min(deleted) and max(deleted) < topologies[1]
    assert fake.observed == [True, True]  # a pod replaced before the controller saw the port would lack it
    assert held_annotations(fake) is None
    new = {node: fake.pod_of(NS, node) for node in MIXED}
    assert [new[node].uid != old[node].uid for node in MIXED] == [True, True, False]
    assert all(pod.ready and not pod.deleting for pod in new.values())
    for node in ("e1", "e2"):
        assert f"apply t: deleted the pod {old[node].name} (uid {old[node].uid}) of the node {node}, {HOT_ADD}" in (
            caplog.messages)


@pytest.mark.parametrize("reconfigure", [False, True], ids=["port-added", "reconfigure"])
def test_apply_deletes_a_pod_only_at_the_second_of_two_reads_that_find_the_generation_observed(
    reconfigure: bool,
) -> None:
    # The controller's first write of a new generation comes before it acts on it (verified-facts.md):
    # a pod deleted at the first read that finds the generation observed may fall inside that window.
    fake, step, _ = stepped()
    target = planned("mixed", ADMITTED) if reconfigure else step
    generation, mark = fake._generations[(NS, "t")] + (0 if reconfigure else 1), len(fake.reads)
    apply(fake, target, reconfigure=reconfigure)
    first = min(at for at, read, observed in fake.reads[mark:] if read == generation and observed)
    assert fake.deleted_at and min(fake.deleted_at) >= first + POLL_S


def test_a_kill_before_the_deletions_leaves_the_annotation_and_a_new_drivers_apply_finishes_them() -> None:
    fake, step, old = stepped()
    fake.fail["delete_pod"] = [RuntimeError("killed")]
    with pytest.raises(RuntimeError, match="killed"):
        apply(fake, step)
    assert held_annotations(fake) == recreating(old["e1"], old["e2"])
    assert {node: fake.pod_of(NS, node).uid for node in MIXED} == {node: pod.uid for node, pod in old.items()}
    mark = len(fake.calls)
    apply(fake, step)  # each apply is a new driver's
    assert [c for c in fake.calls[mark:] if c[0] == "delete_pod"] == [
        ("delete_pod", NS, old[node].name) for node in ("e1", "e2")]
    assert held_annotations(fake) is None
    assert [fake.pod_of(NS, node).uid != old[node].uid for node in MIXED] == [True, True, False]


def test_a_kill_in_the_first_wait_is_resumed_and_still_waits_for_the_generation_before_it_deletes() -> None:
    # The annotated Topology landed and the wait's first poll was killed, before the controller's
    # pass: a resume that skipped the wait because the annotation is already there would delete
    # both pods before the controller saw the port.
    fake, step, old = stepped()
    fake.fail["topology"] = [None, RuntimeError("killed")]  # the current Topology's read, then the poll
    with pytest.raises(RuntimeError, match="killed"):
        apply(fake, step)
    assert held_annotations(fake) == recreating(old["e1"], old["e2"])
    assert not any(c[0] == "delete_pod" for c in fake.calls)
    apply(fake, step)  # each apply is a new driver's
    assert [c for c in fake.calls if c[0] == "delete_pod"] == [
        ("delete_pod", NS, old[node].name) for node in ("e1", "e2")]
    assert fake.observed == [True, True]
    assert held_annotations(fake) is None
    assert [fake.pod_of(NS, node).uid != old[node].uid for node in MIXED] == [True, True, False]


def test_a_kill_at_the_second_deletion_is_resumed_at_the_pod_still_at_its_uid(caplog: pytest.LogCaptureFixture) -> None:
    fake, step, old = stepped()
    fake.fail["delete_pod"] = [None, RuntimeError("killed")]
    with pytest.raises(RuntimeError, match="killed"):
        apply(fake, step)
    replacement = fake.pod_of(NS, "e1")
    assert replacement.uid != old["e1"].uid and fake.pod_of(NS, "e2").uid == old["e2"].uid
    mark = len(fake.calls)
    with caplog.at_level(logging.INFO, logger="fylgja.clabernetes"):
        apply(fake, step)
    assert [c for c in fake.calls[mark:] if c[0] == "delete_pod"] == [("delete_pod", NS, old["e2"].name)]
    assert fake.pod_of(NS, "e1").uid == replacement.uid
    assert [fake.pod_of(NS, node).uid != old[node].uid for node in MIXED] == [True, True, False]
    assert held_annotations(fake) is None
    assert (f"apply t: the node e1's pod is at uid {replacement.uid}, not {old['e1'].uid}: already replaced, so "
            "left") in caplog.messages


def test_a_kill_at_the_apply_that_removes_the_annotation_is_resumed_with_no_pod_deleted() -> None:
    fake, step, old = stepped()
    fake.fail["apply"] = [None, None, None, None, RuntimeError("killed")]  # the step's fifth apply
    with pytest.raises(RuntimeError, match="killed"):
        apply(fake, step)
    assert held_annotations(fake) == recreating(old["e1"], old["e2"])
    replaced = {node: fake.pod_of(NS, node).uid for node in MIXED}
    mark = len(fake.calls)
    apply(fake, step)
    assert not any(c[0] == "delete_pod" for c in fake.calls[mark:])
    assert held_annotations(fake) is None
    assert {node: fake.pod_of(NS, node).uid for node in MIXED} == replaced


def test_reconfigure_with_a_port_added_after_boot_compares_nothing_and_replaces_every_pod_once() -> None:
    # Every pod is replaced, so no node is named for the port: the Topology is applied as rendered, once.
    fake, step, old = stepped()
    mark, applied = len(fake.calls), len(fake.annotations)
    apply(fake, step, reconfigure=True)
    assert fake.annotations[applied:] == [None]
    assert [c for c in fake.calls[mark:] if c[0] == "delete_pod"] == [
        ("delete_pod", NS, old[node].name) for node in MIXED]
    assert fake.observed == [True, True, True]
    assert held_annotations(fake) is None
    assert all(fake.pod_of(NS, node).uid != old[node].uid and fake.pod_of(NS, node).ready for node in MIXED)


def test_reconfigure_resuming_a_killed_port_addition_replaces_every_pod_once() -> None:
    # The annotation a killed apply left names e1 and e2; reconfigure deletes every pod, so it
    # replaces them by its own deletions and none twice.
    fake, step, old = stepped()
    fake.fail["delete_pod"] = [RuntimeError("killed")]
    with pytest.raises(RuntimeError, match="killed"):
        apply(fake, step)
    mark, applied = len(fake.calls), len(fake.annotations)
    apply(fake, step, reconfigure=True)
    assert [c for c in fake.calls[mark:] if c[0] == "delete_pod"] == [
        ("delete_pod", NS, old[node].name) for node in MIXED]
    # The annotation is kept until the deletions, then removed.
    assert fake.annotations[applied:] == [recreating(old["e1"], old["e2"]), None]
    assert held_annotations(fake) is None
    assert all(fake.pod_of(NS, node).uid != old[node].uid for node in MIXED)


def test_reconfigure_over_a_topology_the_comparison_cannot_read_still_replaces_every_pod() -> None:
    # The remedy for a silent node must not fail on what only the hot-add's comparison reads.
    fake, _, old = stepped()
    p = planned("mixed", ADMITTED)
    definition = fake.objects[("Topology", NS, "t")]["spec"]["definition"]
    edited = yaml.safe_load(definition["containerlab"])
    edited["topology"]["links"] = [{"endpoints": [1, 2]}]
    definition["containerlab"] = yaml.safe_dump(edited)
    apply(fake, p, reconfigure=True)
    assert all(fake.pod_of(NS, node).uid != old[node].uid and fake.pod_of(NS, node).ready for node in MIXED)


def test_a_create_and_the_same_topology_again_apply_no_annotation_and_delete_no_pod() -> None:
    fake = Recording()
    fake.settle_s = fake.terminate_s = 5
    p = planned("mixed", ADMITTED)
    apply(fake, p)
    before = {node: fake.pod_of(NS, node).uid for node in MIXED}
    apply(fake, p)
    assert fake.annotations == [None, None]
    assert not any(c[0] == "delete_pod" for c in fake.calls)
    assert {node: fake.pod_of(NS, node).uid for node in MIXED} == before


def test_a_node_gaining_a_port_with_no_pod_is_not_named_since_it_comes_up_with_its_ports() -> None:
    fake, step, old = stepped()
    fake.controller = False
    asyncio.run(fake.delete_pod(NS, old["e1"].name))
    asyncio.run(fake.sleep(fake.terminate_s))
    fake.controller = True
    applied = len(fake.annotations)
    apply(fake, step)
    assert fake.annotations[applied:] == [recreating(old["e2"]), None]
    assert fake.pod_of(NS, "e1").ready and fake.pod_of(NS, "e2").uid != old["e2"].uid


@pytest.mark.parametrize("value", ["[]", "{unclosed", '{"e1":1}'], ids=["list", "not-json", "uid-not-text"])
def test_an_annotation_that_is_no_object_of_node_to_pod_uid_fails_the_apply_naming_it(value: str) -> None:
    fake = Recording()
    p = planned("mixed", ADMITTED)
    apply(fake, p)
    fake.objects[("Topology", NS, "t")]["metadata"]["annotations"] = {RECREATE_ANNOTATION: value}
    applied = len(fake.annotations)
    with pytest.raises(DriverFailed, match=re.escape(f"the annotation {RECREATE_ANNOTATION}")):
        apply(fake, p)
    assert fake.annotations[applied:] == []
    assert not any(c[0] == "delete_pod" for c in fake.calls)


def test_a_topology_on_the_cluster_the_comparison_cannot_read_fails_the_apply_naming_it() -> None:
    fake = Recording()
    p = planned("mixed", ADMITTED)
    apply(fake, p)
    definition = fake.objects[("Topology", NS, "t")]["spec"]["definition"]
    definition["containerlab"] = definition["containerlab"].replace("registry.example:5000/lab/", "elsewhere.example/")
    applied = len(fake.annotations)
    with pytest.raises(DriverFailed, match=re.escape(f"the Topology {NS}/t the cluster holds cannot be compared: "
                                                     "ValueError: no package given runs the node e1 (ceos, "
                                                     "elsewhere.example/ceos:4.32.0.2F)")):
        apply(fake, p)
    assert fake.annotations[applied:] == []


@pytest.mark.parametrize(("definition", "cause"), [
    ("{unclosed\n", "ParserError"),
    ("name: t\n", "KeyError: 'topology'"),
    ("- a list\n", "TypeError: list indices must be integers or slices, not str"),
], ids=["not-yaml", "no-topology", "not-a-mapping"])
def test_each_failure_to_read_the_clusters_topology_fails_the_apply_naming_it(definition: str, cause: str) -> None:
    fake = Recording()
    p = planned("mixed", ADMITTED)
    apply(fake, p)
    fake.objects[("Topology", NS, "t")]["spec"]["definition"]["containerlab"] = definition
    applied = len(fake.annotations)
    with pytest.raises(DriverFailed, match=re.escape(f"the Topology {NS}/t the cluster holds cannot be compared: "
                                                     f"{cause}")):
        apply(fake, p)
    assert fake.annotations[applied:] == []


def test_a_fault_in_the_comparison_itself_is_no_driver_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    # A programming error in changes is not the cluster's: as a DriverFailed the loop would retry it for ever.
    fake = Recording()
    p = planned("mixed", ADMITTED)
    apply(fake, p)

    def faulty(*args: object) -> None:
        raise RuntimeError("a fault in changes")

    monkeypatch.setattr(clabernetes_changes, "changes", faulty)
    with pytest.raises(RuntimeError, match="a fault in changes"):
        apply(fake, p)


@pytest.mark.parametrize("links", [
    [{"endpoints": [1, 2]}],
    {"endpoints": ["e1:eth1", "e2:eth1"]},
    [["e1:eth1", "e2:eth1"]],
], ids=["endpoints-not-text", "links-not-a-list", "a-link-not-a-mapping"])
def test_a_topology_on_the_cluster_whose_links_the_driver_never_wrote_fails_the_apply_naming_it(links: Any) -> None:
    # Only a hand-edited Topology reaches it; an endpoint that is not text would otherwise leave
    # the comparison as an AttributeError, which the loop never retries.
    fake = Recording()
    p = planned("mixed", ADMITTED)
    apply(fake, p)
    definition = fake.objects[("Topology", NS, "t")]["spec"]["definition"]
    edited = yaml.safe_load(definition["containerlab"])
    edited["topology"]["links"] = links
    definition["containerlab"] = yaml.safe_dump(edited)
    applied = len(fake.annotations)
    with pytest.raises(DriverFailed, match=re.escape(f"the Topology {NS}/t the cluster holds is not one the driver "
                                                     "wrote: its links are not a list of links whose endpoints are "
                                                     "text")):
        apply(fake, p)
    assert fake.annotations[applied:] == []


# inspect, endpoints, destroy and exec.

PING = ("ping", "-c", "1", "10.0.0.1")


def inspect(fake: FakeKube) -> Inspection:
    return asyncio.run(driver(fake).inspect("t"))


def node_of(inspection: Inspection, name: str) -> NodeState:
    [node] = [n for n in inspection.nodes if n.name == name]
    return node


def destroy(fake: FakeKube, p: Planned, *, files: Mapping[str, bytes] | None = None) -> None:
    asyncio.run(driver(fake).destroy(p.deployment, p.files if files is None else files, PLATFORMS, PROBES))


def exec_in(fake: FakeKube, node: str, argv: tuple[str, ...] = PING) -> Exec:
    return asyncio.run(driver(fake).exec("t", node, argv, 5.0))


def test_inspect_answers_each_node_as_its_pod_its_incarnation_the_uid_and_the_restarts() -> None:
    fake = FakeKube()
    apply(fake, planned("three-node"))
    pods = {node: fake.pod_of(NS, node) for node in NODES}
    assert inspect(fake) == Inspection("present", (
        NodeState("n1", pods["n1"].name, "uid-1/0", "192.0.2.1", True),
        NodeState("n2", pods["n2"].name, "uid-2/0", "192.0.2.2", True),
        NodeState("n3", pods["n3"].name, "uid-3/0", "192.0.2.3", True)))
    # The kubelet restarts the container in place: the same pod and uid, and the push lost.
    fake.restart(NS, "n1")
    fake.start(NS, "n1")
    assert node_of(inspect(fake), "n1") == NodeState("n1", pods["n1"].name, "uid-1/1", "192.0.2.1", True)


def test_a_node_whose_container_is_down_in_its_running_pod_is_not_running_until_it_starts() -> None:
    # Read on the cluster: a container ended in its pod leaves the pod's phase `Running` while it is
    # terminated and while it restarts, and the restart count moves when it starts.
    fake = FakeKube()
    apply(fake, planned("three-node"))
    pod = fake.pod_of(NS, "n1")
    fake.restart(NS, "n1")
    assert fake.pod_of(NS, "n1").phase == "Running"
    assert node_of(inspect(fake), "n1") == NodeState("n1", pod.name, "uid-1/0", "192.0.2.1", False)
    assert asyncio.run(driver(fake).endpoints("t")) == {"n2": "192.0.2.2", "n3": "192.0.2.3"}
    fake.start(NS, "n1")
    assert node_of(inspect(fake), "n1") == NodeState("n1", pod.name, "uid-1/1", "192.0.2.1", True)
    assert asyncio.run(driver(fake).endpoints("t")) == {"n1": "192.0.2.1", "n2": "192.0.2.2", "n3": "192.0.2.3"}


def test_a_probe_host_runs_with_no_address() -> None:
    fake = FakeKube()
    apply(fake, planned("three-node-probed"))
    host = fake.pod_of(NS, "n1-loop-a")
    found = inspect(fake)
    assert [n.name for n in found.nodes] == ["n1", "n1-loop-a", "n1-loop-b", "n2", "n3"]
    assert node_of(found, "n1-loop-a") == NodeState("n1-loop-a", host.name, f"{host.uid}/0", None, True)


def test_a_node_being_replaced_is_its_new_pod_not_running_until_it_runs_at_its_address_still() -> None:
    fake = FakeKube()
    apply(fake, planned("three-node"))
    fake.terminate(NS, "n1")  # the old pod deleting and Ready, the new one Pending
    new = fake.pod_of(NS, "n1")
    assert node_of(inspect(fake), "n1") == NodeState("n1", new.name, f"{new.uid}/0", "192.0.2.1", False)
    fake.set_ready(NS, "n1", True)
    assert node_of(inspect(fake), "n1") == NodeState("n1", new.name, f"{new.uid}/0", "192.0.2.1", True)


def test_a_node_whose_every_pod_is_being_deleted_is_its_newest_and_not_running() -> None:
    fake = FakeKube()
    apply(fake, planned("three-node"))
    fake.controller, fake.terminate_s = False, 30
    fake.terminate(NS, "n1")
    newest = fake.pod_of(NS, "n1")
    fake.set_ready(NS, "n1", True)  # Running: a pod being deleted runs no node all the same
    asyncio.run(fake.delete_pod(NS, newest.name))
    assert all(p.deleting for p in pods_of(fake, "n1")) and len(pods_of(fake, "n1")) == 2
    assert fake.pod_of(NS, "n1").phase == "Running"
    assert node_of(inspect(fake), "n1") == NodeState("n1", newest.name, f"{newest.uid}/0", "192.0.2.1", False)


def test_a_pod_not_running_is_a_node_not_running() -> None:
    fake = FakeKube()
    apply(fake, planned("three-node"))
    fake.set_phase(NS, "n2", "Pending")
    assert [n.running for n in inspect(fake).nodes] == [True, False, True]


def test_a_namespace_absent_or_not_the_twins_is_absent_and_the_twins_holding_no_pod_is_residue() -> None:
    fake = FakeKube()
    assert inspect(fake) == Inspection("absent", ())
    fake.add_namespace(NS, OWNED)
    assert inspect(fake) == Inspection("residue", ())
    # Another twin's namespace holding pods labelled as this twin's is still not this twin's.
    other = FakeKube()
    apply(other, planned("three-node"))
    other.namespaces[NS] = dataclasses.replace(other.namespaces[NS], labels={**OWNED, "fylgja.twin": "u"})
    mark = len(other.calls)
    assert inspect(other) == Inspection("absent", ())
    assert other.calls[mark:] == [("namespace", NS)]


def test_inspect_patches_a_load_balancer_found_not_local_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    fake = FakeKube()
    apply(fake, planned("three-node"))
    fake.set_policy(NS, "n1", "Cluster")
    mark = len(fake.calls)
    with caplog.at_level(logging.INFO, logger="fylgja.clabernetes"):
        inspect(fake)
    assert [c for c in fake.calls[mark:] if c[0] == "patch_service"] == [("patch_service", NS, "n1", LOCAL)]
    assert [(r.levelname, r.getMessage()) for r in caplog.records if "n1" in r.getMessage()] == [
        ("WARNING", "inspect t: the Service n1 was at externalTrafficPolicy Cluster: patched to Local (D-037, D-057)")]
    mark = len(fake.calls)
    inspect(fake)
    assert not any(c[0] == "patch_service" for c in fake.calls[mark:])


def test_a_pod_of_the_twin_with_no_node_label_fails_the_inspect_naming_it() -> None:
    fake = FakeKube()
    apply(fake, planned("three-node"))
    stray = dataclasses.replace(fake.pod_of(NS, "n1"), name="stray", uid="uid-0", labels=OWNED)
    fake._pods[(NS, stray.name)] = stray
    with pytest.raises(DriverFailed, match=re.escape(f"the pod stray of the twin t has no {NODE_LABEL} label")):
        inspect(fake)


def test_endpoints_are_each_running_nodes_address_leaving_out_a_probe_host_and_a_node_not_running() -> None:
    fake = FakeKube()
    apply(fake, planned("three-node-probed"))
    assert asyncio.run(driver(fake).endpoints("t")) == {"n1": "192.0.2.1", "n2": "192.0.2.2", "n3": "192.0.2.3"}
    fake.set_phase(NS, "n2", "Pending")
    assert asyncio.run(driver(fake).endpoints("t")) == {"n1": "192.0.2.1", "n3": "192.0.2.3"}
    assert asyncio.run(driver(FakeKube()).endpoints("t")) == {}


def test_destroy_deletes_the_namespace_and_waits_until_it_is_gone(caplog: pytest.LogCaptureFixture) -> None:
    fake = FakeKube()
    p = planned("three-node")
    apply(fake, p)
    fake.namespace_delete_s = 30
    mark, start = len(fake.calls), fake.now
    with caplog.at_level(logging.INFO, logger="fylgja.clabernetes"):
        destroy(fake, p)
    assert fake.now >= start + 30
    assert [c for c in fake.calls[mark:] if c[0] == "delete_namespace"] == [("delete_namespace", NS)]
    assert inspect(fake) == Inspection("absent", ())
    assert [m for m in caplog.messages if m.startswith("destroy t")] == [
        f"destroy t: deleted the namespace {NS}", f"destroy t: the namespace {NS} is gone"]


def test_destroy_of_a_namespace_absent_is_nothing_done() -> None:
    fake = FakeKube()
    destroy(fake, planned("three-node"))
    assert fake.calls == [("namespace", NS)]


def test_destroy_of_a_namespace_being_deleted_sends_no_second_delete_and_waits() -> None:
    fake = FakeKube()
    p = planned("three-node")
    apply(fake, p)
    fake.namespace_delete_s = 30
    asyncio.run(fake.delete_namespace(NS))
    mark, start = len(fake.calls), fake.now
    destroy(fake, p)
    assert not any(c[0] == "delete_namespace" for c in fake.calls[mark:])
    assert fake.now >= start + 30 and NS not in fake.namespaces


def test_a_namespace_never_gone_fails_the_destroy_once_its_budget_has_passed() -> None:
    fake = FakeKube()
    p = planned("three-node")
    apply(fake, p)
    fake.namespace_delete_s = 10_000
    start = fake.now
    with pytest.raises(DriverFailed, match=re.escape(f"the namespace {NS} was not gone within 120s")):
        destroy(fake, p)
    assert 120 <= fake.now - start < 120 + 2 * POLL_S  # SR Linux's 60 s, and the minute


@pytest.mark.parametrize("labels", [{"fylgja.owner": "core", "fylgja.twin": "u"}, {}],
                         ids=["another-twins", "unlabelled"])
def test_destroy_leaves_a_namespace_that_is_not_the_twins_and_warns(
    labels: dict[str, str], caplog: pytest.LogCaptureFixture,
) -> None:
    fake = FakeKube()
    fake.add_namespace(NS, labels)
    with caplog.at_level(logging.INFO, logger="fylgja.clabernetes"):
        destroy(fake, planned("three-node"))
    assert fake.calls == [("namespace", NS)]
    assert NS in fake.namespaces
    assert [(r.levelname, r.getMessage()) for r in caplog.records] == [
        ("WARNING", f"destroy t: the namespace {NS} is not the twin's: it lacks the labels fylgja.owner=core and "
                    "fylgja.twin=t, so it is left")]


def test_destroy_refuses_files_that_are_not_the_deployments_before_any_call() -> None:
    fake = FakeKube()
    p = planned("three-node")
    with pytest.raises(ValueError, match="not the deployment's"):
        destroy(fake, p, files={**p.files, TOPOLOGY: p.files[TOPOLOGY] + b"\n"})
    extra = {**p.files, "extra.yaml": b"kind: Extra\n"}
    with pytest.raises(ValueError, match=r"are not a clabernetes deployment's"):
        asyncio.run(driver(fake).destroy(listing(p.deployment, extra), extra, PLATFORMS, PROBES))
    assert fake.calls == []


def test_destroy_refuses_an_allocation_whose_namespace_is_not_the_twins_before_any_call() -> None:
    # As apply does: a missing namespace is the same refusal, not a KeyError.
    fake = FakeKube()
    p = planned("three-node")
    elsewhere = dataclasses.replace(p.deployment, allocation={**BARE, "namespace": "fylgja-twin-u"})
    with pytest.raises(ValueError, match="the deployment's namespace 'fylgja-twin-u' is not the twin t's"):
        asyncio.run(driver(fake).destroy(elsewhere, p.files, PLATFORMS, PROBES))
    unnamed = dataclasses.replace(p.deployment, allocation={k: v for k, v in BARE.items() if k != "namespace"})
    with pytest.raises(ValueError, match="the deployment's namespace None is not the twin t's"):
        asyncio.run(driver(fake).destroy(unnamed, p.files, PLATFORMS, PROBES))
    assert fake.calls == []


def test_exec_runs_the_argument_vector_in_the_nodes_pod_and_answers_a_non_zero_status_as_it_is() -> None:
    fake = FakeKube()
    apply(fake, planned("three-node"))
    pod = fake.pod_of(NS, "n1")
    mark = len(fake.calls)
    assert exec_in(fake, "n1") == Exec(0, "", "")
    assert [c for c in fake.calls[mark:] if c[0] == "exec"] == [("exec", NS, pod.name, PING, 5.0)]
    fake.exec_answers[(NS, pod.name)] = Exec(1, "", "lost")
    assert exec_in(fake, "n1") == Exec(1, "", "lost")


def test_exec_runs_in_a_replaced_nodes_new_pod() -> None:
    fake = FakeKube()
    apply(fake, planned("three-node"))
    fake.terminate(NS, "n1")
    new = fake.pod_of(NS, "n1")
    exec_in(fake, "n1")
    assert fake.calls[-1] == ("exec", NS, new.name, PING, 5.0)


@pytest.mark.parametrize("status", [125, 126, 127])
def test_a_status_the_local_driver_takes_for_a_command_not_run_is_a_driver_failure(status: int) -> None:
    fake = FakeKube()
    apply(fake, planned("three-node"))
    pod = fake.pod_of(NS, "n1")
    fake.exec_answers[(NS, pod.name)] = Exec(status, "", "")
    with pytest.raises(DriverFailed, match=re.escape(f"exec into {pod.name} failed with status {status}")):
        exec_in(fake, "n1")


def test_a_binary_the_node_lacks_is_a_driver_failure() -> None:
    # The API's 500, where docker answers 127.
    fake = FakeKube()
    apply(fake, planned("three-node"))
    pod = fake.pod_of(NS, "n1")
    fake.exec_answers[(NS, pod.name)] = KubeFailed(f"exec Pod {NS}/{pod.name}: 500 Internal Server Error", 500)
    with pytest.raises(DriverFailed, match="500 Internal Server Error"):
        exec_in(fake, "n1", ("no-such-binary",))


def test_exec_into_a_node_with_no_pod_is_a_driver_failure_and_runs_nothing() -> None:
    fake = FakeKube()
    apply(fake, planned("three-node"))
    with pytest.raises(DriverFailed, match=re.escape("the twin t has no pod for the node n9")):
        exec_in(fake, "n9")
    assert not any(c[0] == "exec" for c in fake.calls)


def test_exec_into_a_namespace_that_is_not_the_twins_is_a_driver_failure_and_runs_nothing() -> None:
    # inspect answers absent there, so exec finds no pod there either.
    fake = FakeKube()
    apply(fake, planned("three-node"))
    fake.namespaces[NS] = dataclasses.replace(fake.namespaces[NS], labels={**OWNED, "fylgja.twin": "u"})
    with pytest.raises(DriverFailed, match=re.escape("the twin t has no pod for the node n1")):
        exec_in(fake, "n1")
    with pytest.raises(DriverFailed, match=re.escape("the twin t has no pod for the node n1")):
        exec_in(FakeKube(), "n1")
    assert not any(c[0] == "exec" for c in fake.calls)


# events (D-058): one watch on the owner's pods in every namespace, naming the twin of each pod that comes, goes or
# changes in what the loop reads of it.

OWNER_ONLY = {"fylgja.owner": "core"}
MARKERS = ("192.0.2.1", "secret-marker")
STANDING = Pod(name="n1-6b8f6b9c4-bbbbc", namespace=NS, uid="uid-1", labels={**OWNED, NODE_LABEL: "n1"},
               phase="Running", ready=True, deleting=False, created="2026-11-05T00:00:00+00:00", restarts=0,
               container_running=True)
"""A node's pod as it stands, running and `Ready`: what the test feeds the fake's watch."""


def of(twin: str, name: str = STANDING.name, **changed: Any) -> Pod:
    """`STANDING` as the twin `twin`'s pod `name`, in its namespace, with `changed`."""
    return dataclasses.replace(STANDING, name=name, namespace=clabernetes.namespace_of(twin),
                               labels={**STANDING.labels, "fylgja.twin": twin}, **changed)


def events_driver(fake: FakeKube, **kw: Any) -> ClabernetesDriver:
    return ClabernetesDriver(fake, Provider(ENVIRON), controller_namespace="c9s", pod_cidr="10.244.0.0/16",
                             clock=fake.clock, sleep=fake.sleep, **{"backoff": lambda _: 0.0, **kw})


async def _until_quiet(fake: FakeKube, task: asyncio.Task[Any]) -> None:
    """Return once one watch is open and has read every change the fake gave it; what ended `task` before is the
    test's failure."""
    async with asyncio.timeout(5):
        while fake.watches != 1 or fake.queued:
            if task.done():
                await task
                pytest.fail("events ended")
            await asyncio.sleep(0)


def named(fake: FakeKube, *steps: Callable[[], object], driver: ClabernetesDriver | None = None) -> list[list[str]]:
    """What `events` names as its watch begins, and then during each of `steps` (a coroutine function's awaited), each
    run once the names before it are read. The task is then cancelled, which must end it within 2 s and its watch
    with it (rule B)."""
    names: list[str] = []
    each: list[list[str]] = []
    d = events_driver(fake) if driver is None else driver

    async def consume() -> None:
        async for name in d.events():
            names.append(name)

    async def body() -> None:
        task = asyncio.create_task(consume())
        await _until_quiet(fake, task)
        each.append(names[:])
        for step in steps:
            mark = len(names)
            done = step()
            if asyncio.iscoroutine(done):
                await done
            await _until_quiet(fake, task)
            each.append(names[mark:])
        await cancelled(task)
        assert fake.watches == 0

    bounded(body)
    return each


def watched(fake: FakeKube) -> list[tuple[Any, ...]]:
    return [call for call in fake.calls if call[0] == "watch_pods"]


def test_events_watches_the_owners_pods_in_every_namespace_once_and_names_the_twin_of_each_pod_added() -> None:
    fake = FakeKube()
    fake.feed("ADDED", of("t"))
    assert named(fake, lambda: fake.feed("ADDED", of("u")), lambda: fake.feed("ADDED", of("t", "n2-x"))) == [
        ["t"], ["u"], ["t"]]
    assert watched(fake) == [("watch_pods", OWNER_ONLY)]


@pytest.mark.parametrize("changed", [{"ready": False}, {"uid": "uid-2"}, {"restarts": 1}, {"phase": "Failed"},
                                     {"deleting": True}, {"container_running": False}], ids=lambda c: next(iter(c)))
def test_a_pod_modified_in_what_the_loop_reads_of_it_names_its_twin_and_so_does_the_change_back(
    changed: dict[str, Any],
) -> None:
    # Its incarnation (the uid and the restart count, D-069), whether it runs (the phase, its deletion, its container's
    # state), and whether it is Ready (D-058).
    fake = FakeKube()
    pod = of("t")
    fake.feed("ADDED", pod)
    other = dataclasses.replace(pod, **changed)
    assert named(fake, lambda: fake.feed("MODIFIED", other), lambda: fake.feed("MODIFIED", other),
                 lambda: fake.feed("MODIFIED", pod)) == [["t"], ["t"], [], ["t"]]


def test_a_pod_modified_in_nothing_the_loop_reads_names_nothing() -> None:
    # How often the cluster modifies a settled pod was not read; whatever it modifies, a twin is not inspected for it.
    fake = FakeKube()
    pod = of("t")
    fake.feed("ADDED", pod)
    relabelled = dataclasses.replace(pod, labels={**pod.labels, "c9s.run/other": "x"})
    assert named(fake, lambda: fake.feed("MODIFIED", pod), lambda: fake.feed("MODIFIED", relabelled)) == [
        ["t"], [], []]


def test_a_pod_deleted_names_its_twin_and_one_added_under_its_name_after_it_names_it_again() -> None:
    fake = FakeKube()
    pod = of("t")
    fake.feed("ADDED", pod)
    assert named(fake, lambda: fake.feed("DELETED", dataclasses.replace(pod, deleting=True)),
                 lambda: fake.feed("ADDED", pod)) == [["t"], ["t"], ["t"]]


@pytest.mark.parametrize("labels", [OWNER_ONLY, {**OWNER_ONLY, "fylgja.twin": "Bad_Name"},
                                    {**OWNER_ONLY, "fylgja.twin": ""}], ids=["no-twin-label", "no-twin-name", "empty"])
def test_a_pod_that_names_no_twin_names_nothing_and_the_watch_goes_on(
    labels: dict[str, str], caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("DEBUG", logger="fylgja.clabernetes")
    fake = FakeKube()
    stray = dataclasses.replace(STANDING, labels={**labels, NODE_LABEL: "n1"})
    assert named(fake, lambda: fake.feed("ADDED", stray), lambda: fake.feed("MODIFIED", dataclasses.replace(
        stray, ready=False)), lambda: fake.feed("DELETED", stray), lambda: fake.feed("ADDED", of("t"))) == [
        [], [], [], [], ["t"]]
    assert [r.levelname for r in caplog.records if r.levelname != "DEBUG"] == []
    assert "Bad_Name" not in caplog.text


def test_a_pods_twin_is_its_twin_label_beside_the_owners_and_never_its_namespace_or_its_name() -> None:
    assert twin_of(dataclasses.replace(STANDING, namespace="fylgja-twin-u", name="u-n1-x")) == "t"
    for labels in ({"fylgja.twin": "t"}, {"fylgja.owner": "someone", "fylgja.twin": "t"}, OWNER_ONLY,
                   {**OWNER_ONLY, "fylgja.twin": "Bad_Name"}):
        assert twin_of(dataclasses.replace(STANDING, labels=labels)) is None, labels


def test_a_watch_that_raises_is_watched_again_and_its_first_events_name_every_twin_with_a_pod(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Rule D: the new watch begins with each pod there, ADDED (verified-facts.md, lightkube 1.0.1), so every twin
    with a pod is named again; a change to a pod seen before the failure names its twin as before."""
    fake = FakeKube()
    t, u = of("t"), of("u")
    for pod in (t, u):
        fake.feed("ADDED", pod)
    each = named(fake, lambda: fake.fail_watch(RuntimeError("a line the watch cannot decode")),
                 lambda: fake.feed("MODIFIED", dataclasses.replace(t, ready=False)),
                 lambda: fake.feed("MODIFIED", dataclasses.replace(t, ready=False)))
    assert each == [["t", "u"], ["t", "u"], ["t"], []]
    assert watched(fake) == [("watch_pods", OWNER_ONLY)] * 2
    assert [r.getMessage() for r in caplog.records if r.levelname == "WARNING"] == [
        "the pod watch ended (RuntimeError): it is watched again in 0s, and names the twin of each pod there again"]


def test_a_watch_that_raises_at_its_start_is_asked_again() -> None:
    """First what a real watch raises, a first line lightkube cannot decode (`LightKube.watch_pods` retries the API's
    and the transport's failures itself: test_clabernetes_kube.py's
    `test_a_line_the_watch_cannot_decode_is_raised_past_lightkubes_retries_and_watched_again`); then anything, the
    `Kube` protocol's contract letting a watch raise it."""
    fake = FakeKube()
    fake.feed("ADDED", of("t"))
    fake.fail["watch_pods"] = [undecodable(), RuntimeError("again")]
    assert named(fake) == [["t"]]
    assert watched(fake) == [("watch_pods", OWNER_ONLY)] * 3


def test_after_the_watch_restarts_for_itself_each_twin_with_a_pod_is_named_and_one_whose_pods_all_went_is_not() -> None:
    """`Kube.watch_pods` reconnects for itself and then delivers every pod there again, ADDED, never a deletion it
    missed (pre-flight ruling 4): the driver does not restart it, and a twin whose every pod went during the gap is
    named by the loop's resync alone."""
    fake = FakeKube()
    for twin in ("t", "u", "v"):
        fake.feed("ADDED", of(twin))

    def gap() -> None:
        fake.break_watch()
        fake.feed("DELETED", of("v", deleting=True))
        fake.feed("MODIFIED", of("t", ready=False))
        fake.restart_watch()

    assert named(fake, gap) == [["t", "u", "v"], ["t", "u"]]
    assert watched(fake) == [("watch_pods", OWNER_ONLY)]


def test_the_backoff_grows_while_the_watch_names_nothing_a_name_resets_it_and_the_drivers_sleep_waits_it() -> None:
    """Held to the `Kube` protocol's contract, a watch that may raise anything, not to `LightKube`'s behaviour."""
    asked: list[float | None] = []

    def backoff(previous: float | None) -> float:
        asked.append(previous)
        return 0.5 if previous is None else previous * 2

    fake = FakeKube()
    fake.feed("ADDED", of("t"))
    fake.fail["watch_pods"] = [undecodable(), RuntimeError("again")]
    start = fake.now
    assert named(fake, lambda: fake.fail_watch(RuntimeError("once more")),
                 driver=events_driver(fake, backoff=backoff)) == [["t"], ["t"]]
    assert asked == [None, 0.5, None]
    assert fake.now - start == 0.5 + 1.0 + 0.5  # the driver's own sleep, which the fake's time is


def test_events_waits_the_seams_one_backoff_by_default() -> None:
    """Not a copy of it (pre-flight ruling 9)."""
    defaults = ClabernetesDriver.__init__.__kwdefaults__
    assert defaults is not None
    assert defaults["backoff"] is events_backoff and defaults["sleep"] is asyncio.sleep


def test_nothing_of_a_failed_watch_reaches_a_log_and_the_watch_goes_on(caplog: pytest.LogCaptureFixture) -> None:
    """Constitution X: an API's or a transport's error can name the API server's address, so a failure is logged by
    its type alone, never its text, and with no traceback. Fed what a real watch raises, a line lightkube cannot
    decode, at its start and again while it runs, each of msgspec's two types with the markers in its text, as no
    real one need carry them: `LightKube.watch_pods` retries the API's refusals and the transport's failures, and
    logs its own retries so (test_clabernetes_kube.py). A refusal that ends a watch with its status code is a
    renewal's (`test_a_deletion_that_fails_ends_the_watch_by_its_type_and_status_...`, below)."""
    caplog.set_level("DEBUG")
    marked = " ".join(MARKERS)
    fake = FakeKube()
    fake.feed("ADDED", of("t"))
    no_json, no_event = undecodable(), undecodable(b'["not an event"]')
    fake.fail["watch_pods"] = [type(no_json)(f"JSON is malformed: {marked}")]
    each = named(fake, lambda: fake.fail_watch(type(no_event)(f"Expected `object`, got `array`: {marked}")),
                 lambda: fake.feed("MODIFIED", of("t", ready=False)))
    assert each == [["t"], ["t"], ["t"]]  # it went on
    formatted = [logs.JsonFormatter().format(record) for record in caplog.records]
    assert not [line for line in formatted if any(marker in line for marker in MARKERS)]
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert [r.getMessage().split(":")[0] for r in warnings] == [
        "the pod watch ended (DecodeError)", "the pod watch ended (ValidationError)"]
    assert [getattr(r, "fields", None) for r in warnings] == [
        {"error": "DecodeError", "retry_s": 0.0}, {"error": "ValidationError", "retry_s": 0.0}]
    assert all(r.exc_info is None for r in caplog.records)


def test_cancelling_events_ends_its_watch_and_the_cancel_goes_on() -> None:
    fake = FakeKube()
    fake.feed("ADDED", of("t"))

    async def body() -> None:
        async def consume() -> None:
            async for _ in events_driver(fake).events():
                pass

        task = asyncio.create_task(consume())
        await _until_quiet(fake, task)
        assert fake.watches == 1
        await cancelled(task)
        assert fake.watches == 0

    bounded(body)


def test_closing_events_between_two_names_ends_its_watch() -> None:
    fake = FakeKube()
    for twin in ("t", "u"):
        fake.feed("ADDED", of(twin))

    async def body() -> None:
        names = events_driver(fake).events()
        assert isinstance(names, AsyncGenerator)
        async with asyncio.timeout(5):
            assert await anext(names) == "t"
        assert fake.watches == 1
        await closed(names)
        assert fake.watches == 0  # at once, not when the watch is collected

    bounded(body)


def test_what_the_cluster_does_to_a_pod_names_its_twin_at_each_change_the_loop_reads() -> None:
    """As the fake models the cluster (verified-facts.md, "the clabernetes driver's calls"): a pod deleted reads
    deleting, its replacement comes Pending, the old one goes, and the replacement runs Ready; a container ended in its
    pod is ended, when the driver deletes the pod and it is replaced as any deleted pod is; and a kept pod's readiness
    blinks, each move a kick that costs the loop one inspect and writes nothing."""
    fake = FakeKube()
    apply(fake, planned("three-node"))
    n1 = fake.pod_of(NS, "n1")

    async def time_passes() -> None:
        await fake.sleep(0)

    each = named(fake, lambda: fake.delete_pod(NS, n1.name), time_passes,
                 lambda: fake.restart(NS, "n2"), time_passes,
                 lambda: fake.set_ready(NS, "n3", False), lambda: fake.set_ready(NS, "n3", True))
    assert each == [["t"] * 3, ["t"] * 3, ["t"], ["t"] * 4, ["t"], ["t"], ["t"]]


# A container restarted in its pod (D-069, and the ruling on plan 5's cluster reading): clabernetes 0.10.1 does not
# give the node its management address again, so the driver deletes that pod and the Deployment makes it anew.

def deletions(fake: FakeKube, since: int = 0) -> list[tuple[Any, ...]]:
    return [call for call in fake.calls[since:] if call[0] == "delete_pod"]


async def time_passes(fake: FakeKube) -> None:
    await fake.sleep(0)


def test_a_container_ended_in_its_pod_is_renewed_at_its_end_and_not_again_once_its_count_moves(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Read on the cluster: a container ended in its pod is delivered `terminated` at its restart count, 24.6 s before
    it runs again at one restart more, in a state no starting pod passes through. The pod is renewed at the end, by
    its uid, once: the count's move, delivered for the pod already being deleted, renews nothing; the replacement is
    kept."""
    caplog.set_level("INFO", logger="fylgja.audit")
    fake = FakeKube()
    apply(fake, planned("three-node"))
    fake.terminate_s = 5.0  # the old pod stays, deleting, as on the cluster for a second or two
    n2 = fake.pod_of(NS, "n2")
    mark = len(fake.calls)
    counted = dataclasses.replace(n2, deleting=True, restarts=1, container_running=True, container_ended=False)
    each = named(fake, lambda: fake.restart(NS, "n2"), lambda: fake.feed("MODIFIED", counted),
                 lambda: time_passes(fake), lambda: fake.set_ready(NS, "n2", False),
                 lambda: fake.set_ready(NS, "n2", True))
    assert deletions(fake, mark) == [("delete_pod", NS, n2.name)]
    replacement = fake.pod_of(NS, "n2")
    assert replacement.uid != n2.uid and replacement.restarts == 0 and replacement.ready
    # Ended, then its deletion and its replacement's coming; the count's move; the replacement Ready (the old pod gone
    # meanwhile, at 5 s, is not: no time passes); a blink of the replacement, which is kept.
    assert each == [["t"] * 3, ["t"] * 3, ["t"], ["t"], ["t"], ["t"]]
    [renewed] = [getattr(r, "fields", {}) for r in caplog.records if r.getMessage() == "renew"]
    assert (renewed["pod"], renewed["uid"], renewed["restarts"]) == (n2.name, n2.uid, 0)


def test_a_new_pod_waiting_to_start_is_never_renewed() -> None:
    """A pod starting, its container waiting to run with no last state, is not ended: it is never renewed."""
    fake = FakeKube()
    apply(fake, planned("three-node"))
    mark = len(fake.calls)
    starting = Pod(name="n2-0480a93d2-zzzzz", namespace=NS, uid="uid-new", labels={**OWNED, NODE_LABEL: "n2"},
                   phase="Pending", ready=False, deleting=False, created="2026-11-05T00:01:00+00:00", restarts=0,
                   container_running=False, container_ended=False)
    named(fake, lambda: fake.feed("ADDED", starting),
          lambda: fake.feed("MODIFIED", dataclasses.replace(starting, phase="Running", container_running=True)))
    assert deletions(fake, mark) == []


def test_a_container_that_ends_before_it_was_delivered_running_is_renewed() -> None:
    """The end alone is a change: a container that fails as it starts goes from waiting to ended with its pod never
    delivered running, and is renewed then."""
    fake = FakeKube()
    apply(fake, planned("three-node"))
    mark = len(fake.calls)
    starting = Pod(name="n2-0480a93d2-zzzzz", namespace=NS, uid="uid-new", labels={**OWNED, NODE_LABEL: "n2"},
                   phase="Running", ready=False, deleting=False, created="2026-11-05T00:01:00+00:00", restarts=0,
                   container_running=False, container_ended=False)
    named(fake, lambda: fake.feed("ADDED", starting),
          lambda: fake.feed("MODIFIED", dataclasses.replace(starting, container_ended=True)))
    assert deletions(fake, mark) == [("delete_pod", NS, starting.name)]


def test_a_restarted_pod_delivered_again_while_its_deletion_is_under_way_is_not_deleted_again() -> None:
    """Once: a change the watch delivers after the deletion, from before it, finds the pod being deleted."""
    fake = FakeKube()
    apply(fake, planned("three-node"))
    fake.terminate_s = 5.0  # the old pod stays, deleting, as on the cluster for a second or two
    n2 = fake.pod_of(NS, "n2")
    mark = len(fake.calls)

    def ended_and_again_at_once() -> None:
        fake.restart(NS, "n2")
        ended = fake.pod_of(NS, "n2")
        fake.feed("MODIFIED", dataclasses.replace(ended, phase="Failed"))  # from before the deletion, not deleting

    named(fake, ended_and_again_at_once)
    assert deletions(fake, mark) == [("delete_pod", NS, n2.name)]


def test_a_renewal_deletes_the_pod_at_the_uid_delivered_and_no_other() -> None:
    """By its uid, as the hot-add's deletions are: a pod no longer standing at the uid delivered is left, and so is
    another pod of the twin, restarted or not, until it is delivered itself."""
    fake = FakeKube()
    apply(fake, planned("three-node"))
    fake.restart(NS, "n1")
    fake.start(NS, "n1")
    d = events_driver(fake)
    n2 = fake.pod_of(NS, "n2")
    mark = len(fake.calls)
    asyncio.run(d._renew("t", dataclasses.replace(n2, uid="uid-gone", restarts=1)))
    assert deletions(fake, mark) == []
    n1 = fake.pod_of(NS, "n1")
    asyncio.run(d._renew("t", n1))
    assert deletions(fake, mark) == [("delete_pod", NS, n1.name)]


def test_a_pod_delivered_again_by_a_fresh_watch_with_its_container_restarted_is_replaced_then() -> None:
    """Level-triggered: the rule is a restart count above 0 as the watch delivers the pod, never the count's move. A
    container restarted before the watch began (a core started then) is replaced at the watch's first delivery,
    with nothing kept to compare; and one restarted while the watch was down, when the watch delivers it again."""
    fake = FakeKube()
    apply(fake, planned("three-node"))
    n1, n2 = fake.pod_of(NS, "n1"), fake.pod_of(NS, "n2")
    fake.restart(NS, "n1")
    fake.start(NS, "n1")  # no watch open: its first delivery holds the count at 1
    mark = len(fake.calls)

    def gap() -> None:
        fake.break_watch()
        fake.restart(NS, "n2")
        fake.start(NS, "n2")
        fake.restart_watch()

    named(fake, gap)
    assert deletions(fake, mark) == [("delete_pod", NS, n1.name), ("delete_pod", NS, n2.name)]
    assert fake.pod_of(NS, "n1").uid != n1.uid and fake.pod_of(NS, "n2").uid != n2.uid


def test_a_pods_renewal_is_made_before_its_twin_is_named() -> None:
    """The order: a pass the name kicks must find the pod being deleted, never the node running at `<uid>/1` at an
    address that does not answer again, or it takes a restore that can only time out."""
    fake = FakeKube()
    apply(fake, planned("three-node"))
    mark = len(fake.calls)
    seen: list[int] = []  # the deletions the fake had seen as each name arrived

    async def body() -> None:
        async def consume() -> None:
            async for _ in events_driver(fake).events():
                seen.append(len(deletions(fake, mark)))

        task = asyncio.create_task(consume())
        try:
            await _until_quiet(fake, task)
            before = len(seen)
            fake.restart(NS, "n2")
            await _until_quiet(fake, task)
            made = seen[before]
            assert made == 1, f"the name after the container's end came with {made} deletion(s) made"
        finally:
            await cancelled(task)

    bounded(body)


def test_a_renewal_is_audited_by_the_cores_own_principal_naming_the_twin_the_node_and_the_pod(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Constitution X: the renewal changes a twin under no run, so each deletion is one audit line by the core's own
    principal, the restore's, naming the twin, the node and the pod, never an address; no other line says it."""
    caplog.set_level("DEBUG")
    fake = FakeKube()
    apply(fake, planned("three-node"))
    n2 = fake.pod_of(NS, "n2")
    caplog.clear()
    named(fake, lambda: fake.restart(NS, "n2"))
    audited = [(r.getMessage(), getattr(r, "fields", None)) for r in caplog.records if r.name == "fylgja.audit"]
    assert audited == [("renew", {"principal": RESTORE_PRINCIPAL, "action": "renew", "twin": "t", "node": "n2",
                                  "pod": n2.name, "uid": n2.uid, "restarts": 0})]
    assert not [r for r in caplog.records if r.name != "fylgja.audit" and n2.name in r.getMessage()]


@pytest.mark.parametrize("case", ["deleting", "no-twin-label", "no-twin-name", "no-node-label", "another-namespace",
                                  "a-namespace-not-the-twins"])
def test_a_restarted_pod_is_left_unless_it_is_the_twins_standing_pod_in_the_twins_own_namespace(case: str) -> None:
    fake = FakeKube()
    apply(fake, planned("three-node"))
    n2 = dataclasses.replace(fake.pod_of(NS, "n2"), restarts=1)
    pods = {
        "deleting": dataclasses.replace(n2, deleting=True),
        "no-twin-label": dataclasses.replace(n2, labels={**OWNER_ONLY, NODE_LABEL: "n2"}),
        "no-twin-name": dataclasses.replace(n2, labels={**n2.labels, "fylgja.twin": "Bad_Name"}),
        "no-node-label": dataclasses.replace(n2, labels={k: v for k, v in n2.labels.items() if k != NODE_LABEL}),
        "another-namespace": dataclasses.replace(n2, namespace="elsewhere"),
        "a-namespace-not-the-twins": of("u", restarts=1),
    }
    fake.add_namespace("fylgja-twin-u", {"fylgja.owner": "core"})  # it lacks the twin's label: not the twin u's
    mark = len(fake.calls)
    named(fake, lambda: fake.feed("MODIFIED", pods[case]))
    assert deletions(fake, mark) == []


def test_a_deletion_that_fails_ends_the_watch_by_its_type_and_status_and_the_pod_is_replaced_at_the_retry(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Rule A, as for any failure of the source: one WARNING by type and status, never the text, then the watch
    again, whose first events deliver the pod again, and the deletion is made then."""
    caplog.set_level("DEBUG")
    fake = FakeKube()
    apply(fake, planned("three-node"))
    n2 = fake.pod_of(NS, "n2")
    fake.fail["delete_pod"] = [KubeFailed(f"delete_pod Pod {NS}/{n2.name}: 500 Internal Server Error: "
                                          f"{' '.join(MARKERS)}", 500)]
    mark = len(fake.calls)
    named(fake, lambda: fake.restart(NS, "n2"))
    assert deletions(fake, mark) == [("delete_pod", NS, n2.name)] * 2
    assert watched(fake) == [("watch_pods", OWNER_ONLY)] * 2
    assert fake.pod_of(NS, "n2").uid != n2.uid
    formatted = [logs.JsonFormatter().format(record) for record in caplog.records]
    assert not [line for line in formatted if any(marker in line for marker in MARKERS)]
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert [r.getMessage().split(":")[0] for r in warnings] == [
        f"the renewal of the pod {n2.name} of the node n2 of the twin t failed (KubeFailed, status 500)"]
    assert [getattr(r, "fields", None) for r in warnings] == [
        {"error": "KubeFailed", "status": 500, "twin": "t", "node": "n2", "pod": n2.name, "retry_s": 0.0}]


class AddressBook:
    """What `FakeReader` asks of a driver, the twin and node at an address, from the record's nodes, whose
    LoadBalancer addresses a replaced pod keeps."""

    def __init__(self) -> None:
        self.nodes: dict[str, tuple[str, str]] = {}

    def node_at(self, address: str) -> tuple[str, str] | None:
        return self.nodes.get(address)


def test_through_the_loop_a_container_ended_in_its_pod_ends_restored_at_its_replacement(tmp_path: Path) -> None:
    """The loop over the clabernetes driver over `FakeKube`: a create, then `n2`'s container ended in its pod. The
    driver deletes the pod as it reads the end, before it names the twin, so the loop's pass finds `n2` not running
    and waits for it; the replacement runs, and one restore readies, pushes and verifies it, its verify holding, the
    twin Ready again at the replacement's uid.

    The reader is `FakeReader` over an `AddressBook`, filled from the record once the create has ended: a create
    runs no verify, so nothing reads it before the restore does. The fake's readiness answers any address, so this
    test cannot show what a restore taken at the old pod would meet on the cluster, where the address of a container
    restarted in its pod does not answer; the order that keeps the loop from taking one is
    `test_a_pods_renewal_is_made_before_its_twin_is_named`'s."""
    environ = {**ENVIRON, "FYLGJA_CREDENTIAL_SRLINUX_USERNAME": "admin", "FYLGJA_CREDENTIAL_SRLINUX_PASSWORD": "pw"}
    provider = Provider(environ)
    fake = FakeKube()
    d = ClabernetesDriver(fake, provider, controller_namespace="c9s", pod_cidr="10.244.0.0/16", clock=fake.clock,
                          sleep=fake.sleep, backoff=lambda _: 0.0)
    book = AddressBook()
    reader = FakeReader(cast(FakeDriver, book))  # FakeReader calls its driver's `node_at` alone
    reader.seed("t", compiled("three-node").manifest, PLATFORMS)
    store = LocalStore.open(tmp_path / "store")
    r = Reconciler(store, {d.name: d}, PLATFORMS, PROBES, provider, resync_s=3600.0, step_wait_s=1.0,
                   verify_poll_s=0.01, cancel_poll_s=0.01, pusher=fake_push(), readiness=fake_ready(),
                   verifier=Verifier(PLATFORMS, PROBES, provider, reader=reader))
    blueprint_id, _ = store.put_blueprint(json.loads((ROOT / "testdata/blueprint/three-node.json").read_text()))

    def ready(record: TwinRecord) -> tuple[str, str | None]:
        (condition,) = [c for c in record.status.conditions if c.type == "Ready"]
        return condition.status, condition.reason

    async def until(done: Callable[[], bool]) -> None:
        while not done():
            await fake.sleep(0.5)
            await asyncio.sleep(0.01)

    async def body() -> None:
        await r.start()
        try:
            async with asyncio.timeout(20):
                store.create_twin(TwinRecord(name="t", revision=1, generation=1,
                                             spec=Spec(blueprint_id=blueprint_id, driver=d.name, allow_restart=False),
                                             status=Status(observed_generation=0, conditions=(), nodes=())))
                r.kick("t")
                await until(lambda: store.get_twin("t").status.observed_generation == 1
                            and store.get_twin("t").status.run_id is None)
                created = store.get_twin("t")
                assert ready(created) == ("True", "twin.ready")
                book.nodes = {n.address: ("t", n.name) for n in created.status.nodes if n.address}
                old, mark = fake.pod_of(NS, "n2"), len(fake.calls)
                fake.restart(NS, "n2")
                await until(lambda: fake.pod_of(NS, "n2").uid != old.uid
                            and any(r.operation == "restore" and r.state == "ended" for r in store.list_runs("t"))
                            and store.get_twin("t").status.run_id is None
                            and ready(store.get_twin("t")) == ("True", "twin.ready"))
                assert deletions(fake, mark) == [("delete_pod", NS, old.name)]
                (restore,) = [run for run in store.list_runs("t") if run.operation == "restore"]
                verdict = restore.verdict
                assert verdict is not None and verdict.wait is not None
                assert (restore.state, verdict.status, verdict.wait.outcome) == ("ended", "ok", "settled")
                replacement = fake.pod_of(NS, "n2")
                record = store.get_twin("t")
                (n2,) = [n for n in record.status.nodes if n.name == "n2"]
                assert (n2.incarnation, n2.holds) == (f"{replacement.uid}/0", record.status.bundle_id)
                assert [n for n in record.status.nodes if n.name != "n2"] == [
                    n for n in created.status.nodes if n.name != "n2"]
        finally:
            await r.stop()
            store.close()

    bounded(body)


def failing_twin(fake: FakeKube, node: str = "n1") -> Pod:
    """The twin `u`'s one pod, of the node `node`, its container restarted in it, in `u`'s own namespace, listed after
    every pod of `t`: a watch's listing goes in namespace and name order."""
    fake.add_namespace("fylgja-twin-u", {"fylgja.owner": "core", "fylgja.twin": "u"})
    pod = of("u", name=f"{node}-6b8f6b9c4-bbbbc", restarts=1)
    pod = dataclasses.replace(pod, labels={**pod.labels, NODE_LABEL: node})
    fake.feed("ADDED", pod)
    return pod


class Recorded:
    """A backoff that records each `previous` it is asked with, answering `events_backoff`'s delay."""

    def __init__(self) -> None:
        self.asked: list[float | None] = []

    def __call__(self, previous: float | None) -> float:
        self.asked.append(previous)
        return events_backoff(previous)


def test_a_renewal_that_keeps_failing_waits_a_backoff_of_its_own_growing_round_after_round(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The names a round gives before the failing pod do not reset it: each round that ends in a failed renewal waits
    the backoff of the last such round, up to its ceiling; the failing pod's twin is named in each round; and the
    WARNING says it was that pod's renewal, by the failure's type and status alone (rule A)."""
    caplog.set_level("DEBUG")
    fake = FakeKube()
    apply(fake, planned("three-node"))
    u = failing_twin(fake)
    fake.fail["delete_pod"] = [KubeFailed(f"delete_pod Pod {u.namespace}/{u.name}: 403 Forbidden: {' '.join(MARKERS)}",
                                          403)] * 8
    backoff = Recorded()
    each = named(fake, driver=events_driver(fake, backoff=backoff))
    assert backoff.asked == [None, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0]  # the ceiling, 60 s
    assert each[0][:32] == ["t", "t", "t", "u"] * 8  # the failing pod's twin named in every round
    assert [call[2] for call in deletions(fake)] == [u.name] * 9  # the ninth deletion made
    formatted = [logs.JsonFormatter().format(record) for record in caplog.records]
    assert not [line for line in formatted if any(marker in line for marker in MARKERS)]
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert [r.getMessage() for r in warnings][:1] == [
        f"the renewal of the pod {u.name} of the node n1 of the twin u failed (KubeFailed, status 403): it is watched "
        "again in 1s, and names the twin of each pod there again"]
    assert [getattr(r, "fields", None) for r in warnings][:2] == [
        {"error": "KubeFailed", "status": 403, "twin": "u", "node": "n1", "pod": u.name, "retry_s": 1.0},
        {"error": "KubeFailed", "status": 403, "twin": "u", "node": "n1", "pod": u.name, "retry_s": 2.0}]
    assert len(warnings) == 8


def test_a_watch_failure_after_failed_renewals_resets_the_renewals_backoff() -> None:
    fake = FakeKube()
    apply(fake, planned("three-node"))
    u = failing_twin(fake)
    refused = KubeFailed(f"delete_pod Pod {u.namespace}/{u.name}: 403 Forbidden", 403)
    fake.fail["delete_pod"] = [refused, refused, refused]
    fake.fail["watch_pods"] = [None, None, RuntimeError("a line the watch cannot decode")]
    backoff = Recorded()
    named(fake, driver=events_driver(fake, backoff=backoff))
    # Two failed renewals, the second waiting on the first; the watch's own failure, its own backoff; then a third
    # failed renewal, which begins again.
    assert backoff.asked == [None, 1.0, None, None]


def renewed(fake: FakeKube, node: str) -> Callable[[], object]:
    """A step for `named`: the node's container ended in its pod, then time for its replacement."""

    async def step() -> None:
        fake.restart(NS, node)
        await fake.sleep(0)

    return step


def test_a_node_is_renewed_at_most_three_times_in_ten_minutes_and_its_pod_is_then_left(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The bound, against the driver's clock: the fourth restart of a node inside the window is left, logged once
    however many times its pod is delivered, and its twin named; delivered once the window has room, it is renewed
    again. The count is the node's: another node of the twin, `n1`, and the node of that name, `n2`, in another twin,
    are renewed while `t`'s `n2` is left."""
    caplog.set_level("INFO", logger="fylgja.clabernetes")
    fake = FakeKube()
    apply(fake, planned("three-node"))
    mark = len(fake.calls)
    left: list[Pod] = []

    async def fourth() -> None:
        await fake.sleep(0)  # the third replacement runs, Ready
        fake.restart(NS, "n2")
        left.append(fake.pod_of(NS, "n2"))

    async def window_passes() -> None:
        await fake.sleep(RENEWAL_WINDOW_S)
        fake.set_ready(NS, "n2", False)

    each = named(fake, renewed(fake, "n2"), renewed(fake, "n2"), renewed(fake, "n2"), fourth,
                 lambda: fake.start(NS, "n2"), lambda: time_passes(fake),
                 renewed(fake, "n1"), lambda: failing_twin(fake, "n2"), window_passes)
    pods = [call[2] for call in deletions(fake, mark)]
    assert len(pods) == 6, pods  # n2 three times, n1, u's n2, then n2 again at a delivery once the window had room
    assert left[0].name not in pods[:5] and pods[5] == left[0].name
    # The replacement Ready, then its container's end, left; its running again at one restart more, the same restart,
    # logged no more; Ready. Each change of the left pod still names its twin.
    assert each[4:7] == [["t", "t"], ["t"], ["t"]]
    warned = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert warned == [f"events t: left the pod {left[0].name} of the node n2 at 0 restarts: the node was renewed "
                      f"{RENEWALS} times in the last {RENEWAL_WINDOW_S:g}s, so the cluster is not asked to make it "
                      "anew again yet"]


def test_a_left_pod_is_logged_once_at_each_restart_however_often_it_is_delivered(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The WARNING's key is the pod and its restart: left at its container's end, its running again at one restart
    more is the same restart, and is not logged again, nor is any other delivery meanwhile; its next end is another
    restart, logged once more."""
    caplog.set_level("INFO", logger="fylgja.clabernetes")
    fake = FakeKube()
    apply(fake, planned("three-node"))
    left: list[Pod] = []

    async def ended() -> None:
        await fake.sleep(0)  # the replacement before it runs, Ready
        fake.restart(NS, "n2")
        left.append(fake.pod_of(NS, "n2"))

    named(fake, renewed(fake, "n2"), renewed(fake, "n2"), renewed(fake, "n2"), ended,
          lambda: fake.start(NS, "n2"), lambda: time_passes(fake), lambda: fake.set_ready(NS, "n2", False),
          lambda: fake.restart(NS, "n2"), lambda: fake.start(NS, "n2"), lambda: time_passes(fake))
    warned = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert [line.split(": the node")[0] for line in warned] == [
        f"events t: left the pod {left[0].name} of the node n2 at 0 restarts",
        f"events t: left the pod {left[0].name} of the node n2 at 1 restart"]


def test_a_twin_destroyed_and_made_again_is_renewed_at_its_first_restart() -> None:
    """The bound's counts are the twin's for as long as it is: `destroy` drops them once the twin is gone, so a twin
    made again under its name inside the window does not inherit its count."""
    fake = FakeKube()
    p = planned("three-node")
    apply(fake, p)
    d = events_driver(fake)
    mark = len(fake.calls)

    async def destroyed_and_made_again() -> None:
        await fake.sleep(0)
        await d.destroy(p.deployment, p.files, PLATFORMS, PROBES)
        await d.apply(p.deployment, p.files, PLATFORMS, PROBES)

    named(fake, renewed(fake, "n2"), renewed(fake, "n2"), renewed(fake, "n2"), destroyed_and_made_again,
          renewed(fake, "n2"), driver=d)
    renewals = [call[2] for call in deletions(fake, mark)]
    assert len(renewals) == 4, renewals  # three of the twin destroyed, and the first of the twin made again


async def renewed_to_the_bound(fake: FakeKube, d: ClabernetesDriver, twin: str, node: str) -> None:
    """The node's pod renewed `RENEWALS` times through `_renew`, each time its newest pod, and its next one left."""
    namespace = clabernetes.namespace_of(twin)
    for _ in range(RENEWALS):
        await d._renew(twin, fake.pod_of(namespace, node))
    mark = len(fake.calls)
    await d._renew(twin, fake.pod_of(namespace, node))
    assert deletions(fake, mark) == [], "the bound did not hold"


def test_a_twins_destroy_keeps_the_renewals_of_a_twin_whose_name_begins_with_its_own() -> None:
    """The counts `destroy` drops are its twin's by name, not by a prefix of it: `tu`'s node, renewed to the bound,
    is still left once `t` is destroyed."""
    fake = FakeKube()
    p = planned("three-node")
    apply(fake, p)
    fake.add_namespace("fylgja-twin-tu", {"fylgja.owner": "core", "fylgja.twin": "tu"})
    fake.feed("ADDED", of("tu"))
    d = events_driver(fake)

    async def body() -> None:
        await renewed_to_the_bound(fake, d, "tu", "n1")
        await d.destroy(p.deployment, p.files, PLATFORMS, PROBES)
        mark = len(fake.calls)
        await d._renew("tu", fake.pod_of("fylgja-twin-tu", "n1"))
        assert deletions(fake, mark) == []

    asyncio.run(body())


def test_a_destroy_whose_namespace_outlives_its_budget_keeps_the_twins_renewals() -> None:
    """The counts go once the twin is gone, not when its destroy begins: a destroy that fails leaves the twin there,
    and its node renewed to the bound is still left."""
    fake = FakeKube()
    p = planned("three-node")
    apply(fake, p)
    fake.namespace_delete_s = 3600.0  # gone long after the destroy's budget
    d = events_driver(fake)

    async def body() -> None:
        await renewed_to_the_bound(fake, d, "t", "n2")
        with pytest.raises(DriverFailed, match="was not gone within"):
            await d.destroy(p.deployment, p.files, PLATFORMS, PROBES)
        mark = len(fake.calls)
        await d._renew("t", fake.pod_of(NS, "n2"))
        assert deletions(fake, mark) == []

    asyncio.run(body())


def test_the_renewals_kept_are_of_nodes_renewed_within_the_window() -> None:
    """A node's renewals are dropped from the driver's memory when they are next read with every one past the window,
    even when the renewal read then fails: the memory holds no node it has not renewed within ten minutes."""
    fake = FakeKube()
    apply(fake, planned("three-node"))
    d = events_driver(fake)

    async def body() -> None:
        await d._renew("t", fake.pod_of(NS, "n2"))
        assert list(d._renewals) == [("t", "n2")]
        await fake.sleep(RENEWAL_WINDOW_S)
        fake.fail["delete_pod"] = [KubeFailed(f"delete_pod Pod {NS}/n2: 403 Forbidden", 403)]
        with pytest.raises(KubeFailed):
            await d._renew("t", fake.pod_of(NS, "n2"))
        assert d._renewals == {}

    asyncio.run(body())
