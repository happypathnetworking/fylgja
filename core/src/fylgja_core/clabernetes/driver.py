"""The clabernetes driver: a twin as a containerlab topology in its own Kubernetes namespace,
behind the seam (D-017, D-019, D-057).

The pure half is `plan` and `changes`; this is the live half. It reaches the cluster through a
`Kube` alone (`kube.py`, the package's one module that imports lightkube), so the pure tier
stands a fake in for the cluster (D-060); it is given its clock and its sleep, so no test waits.

`admit` reserves what `plan` binds, so that a resumed plan renders the same files from the
record alone (D-017): the twin's own namespace, `namespace_of(twin)`, and what the site
decides that the plan writes, clabernetes' namespace, the cluster's pod CIDR, the core's
namespace when the core runs as a pod, and the image prefix of every pull credential set. A
namespace is the twin's by its name and its two labels, `OWNER_LABEL: OWNER` and
`TWIN_LABEL: <twin>`: one of that name without both is never the driver's to use, and the twin
is refused (`admission.namespace.taken`). A pull credential the provider cannot give whole, its
registry set and its login not, refuses it too, under the credential's own rule, and so does a
registry key whose pull secret is no name Kubernetes accepts; a stepping twin's admission reads
each of its held credentials again, so a step is refused before it touches anything. The message
names the variable, never its value. Admission by capacity is phase 7's.

`apply` applies the deployment's files as rendered, and a pull secret for each registry of the
allocation, made from the credential provider and handed to the cluster alone: no Secret is a
file, and no object's body is logged (Constitution X). It returns once the twin is ready, which
neither the Topology's status nor the pods say alone (verified-facts.md, "the Topology's status,
and the pods replaced" and "the clabernetes driver's calls"): the status reads ready from the
generation before until the controller's pass, and for about 0.14 s after the pass that
observes a new generation, every old pod still `Ready`; and a node being replaced has two pods,
the old one deleting and still `Ready`. So it believes the twin ready only at two reads in a
row, `POLL_S` apart, and deletes a pod it replaces only at the second of two reads that find the
generation observed. A deploy's budget is the slowest package the Topology's nodes use, plus
`MARGIN_S`, as locally.

A node is its pod (D-057). `inspect` reads the twin's pods by its two labels and each node's
by `NODE_LABEL`: the pod's name is the node's handle, the pod's uid and its container's restart
count its incarnation, since a container restarted in place keeps the pod's uid (D-069), and
its LoadBalancer Service's address its address. It patches a Service it finds not `Local`,
since the seam's `Inspection` carries no drift and every pass inspects. `destroy` deletes the
twin's namespace and waits for it to go. `exec` runs in the node's pod and answers as the
local driver's does, so nothing above the seam tells them apart.

`events` holds one watch on the pods labelled `OWNER_LABEL: OWNER` in every namespace and names
a pod's twin, read from its `TWIN_LABEL` alone, when the pod comes, goes, or changes in what
`inspect` reads of it or in whether it is `Ready` (D-058): a drained host's pods are new pods,
and the loop pushes each again without waiting for the resync. A pod modified in nothing the
loop reads names nothing; how often the cluster modifies a settled pod is not yet read
(verified-facts.md). The watch begins with every pod there and reconnects for itself: a change
during lightkube's own reconnect is delivered when it asks again at the version it reached, and
after a version too old, or a fresh watch after a failure, every pod there is delivered again,
so every twin with a pod is named again; one whose every pod went during such a gap is the
resync's. Nothing of a failure's text is
logged, since it can name the API server's address. The core's own applies raise events too,
each costing the loop a pass that finds nothing to do. A pod the watch delivers with its
container ended or restarted in it is deleted before its twin is named, so the cluster makes the
node anew: such a node's management address does not answer again (verified-facts.md), and the
loop never makes a node; at most three times in ten minutes a node, after which its pod is left.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import re
import shlex
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from typing import Any

import yaml

from fylgja_core import credentials, logs, platform_package, probe_package
from fylgja_core.bundle import Manifest
from fylgja_core.clabernetes import (
    CAPABILITIES,
    NAME,
    OWNER,
    OWNER_LABEL,
    TWIN_LABEL,
    namespace_of,
    pull_secret,
)
from fylgja_core.clabernetes import changes as clabernetes_changes
from fylgja_core.clabernetes import plan as clabernetes_plan
from fylgja_core.clabernetes.changes import sections_of, wrapped
from fylgja_core.clabernetes.kube import NODE_LABEL, Kube, KubeFailed, Namespace, Pod
from fylgja_core.clabernetes.plan import NAMESPACE, POLICY, TOPOLOGY
from fylgja_core.credentials import RULE_MALFORMED, Malformed, Missing, Provider
from fylgja_core.deployment import Deployment
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
    check_files,
    events_backoff,
)
from fylgja_core.platform_package import PlatformPackage
from fylgja_core.probe_package import ProbePackage
from fylgja_core.store import check_twin_name

# Rule ids. Clients and tests match on them; the catalogue is docs/rules.md.
RULE_NAMESPACE = "admission.namespace.taken"

RECREATE_ANNOTATION = "fylgja.recreate"
"""The annotation on the Topology an `apply` makes with a pod to replace: a JSON object of each
node whose pod must be replaced, a port added after boot, to that pod's uid. An `apply` that
finds it finishes the replacement and removes it (D-057)."""

MARGIN_S = 60.0
"""What a deploy's or a destroy's budget adds to its slowest package's timeout, as locally."""

POLL_S = 2.0
"""How often the driver's waits read the cluster again."""

SETTLED_READS = 2
"""How many reads in a row, `POLL_S` apart, must find the twin ready before `apply` believes
it, and must find the Topology's generation observed before `apply` deletes a pod: the
Topology's first write of a new generation can keep the readiness of the one before for about
0.14 s, every old pod still `Ready` (verified-facts.md, "the clabernetes driver's calls"). When
the controller writes what a replaced pod is made from was not read. Two reads `POLL_S` apart
cannot both fall in that window while it stays narrower than `POLL_S`; it was read only on a
lightly loaded cluster."""

SECRET_NAME_MAX = 253
"""The longest name a Secret may have: a DNS-1123 subdomain's."""

LOCAL = "Local"
"""The `externalTrafficPolicy` `apply` sets on each LoadBalancer Service: it keeps the client's
address, which the twin's policy admits, where clabernetes' `Cluster` rewrites it (D-037)."""

EXEC_UNREACHED = (125, 126, 127)
"""The statuses `exec` answers as `DriverFailed`, not as the command's: those the local driver
takes for a command that could not be run, `docker exec`'s own, so that the two drivers answer
alike. Here a binary the node lacks is the API's 500 (verified-facts.md, lightkube 1.0.1), and a
126 or 127 is a shell's command it could not invoke or find."""

_HOT_ADD = "since it gains a port its kind cannot add after boot"
"""Why `apply` replaces a node's pod that `changes` finds `recreated` for `hot_add`, as logged."""

RENEWALS = 3
"""How many times `events` has the cluster make a node anew in `RENEWAL_WINDOW_S` before it leaves
the node's pod as it is: the kubelet slows a container that keeps ending to one restart in five
minutes, and each renewal costs a pod, a restore run in the store and its log lines."""

RENEWAL_WINDOW_S = 600.0
"""The window `RENEWALS` counts in, on the driver's clock."""

RENEWAL_PRINCIPAL = "core"
"""Who renews a pod in an audit line: the core's own principal, the restore's
(`reconcile.RESTORE_PRINCIPAL`), since the renewal changes a twin under no run (Constitution X)."""

_SUBDOMAIN = re.compile(r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?(?:\.[a-z0-9](?:[-a-z0-9]*[a-z0-9])?)*")

_log = logging.getLogger("fylgja.clabernetes")


class ClabernetesDriver:
    """The clabernetes driver, over `kube`, its reach into the cluster, and `credentials`, the
    provider of the pull credentials. `controller_namespace` is clabernetes' namespace,
    `pod_cidr` the cluster's pod network and `core_namespace` the core's own when it runs as a
    pod: what `admit` reserves of the site. `clock` and `sleep` are the waits' time, and
    `poll_s` how often they read again; `backoff` is how long `events` waits, on `sleep`, before
    it watches again (`events_backoff`). All are injectable, for the pure tier."""

    name = NAME

    def __init__(
        self,
        kube: Kube,
        credentials: Provider,
        *,
        controller_namespace: str,
        pod_cidr: str,
        core_namespace: str | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        poll_s: float = POLL_S,
        backoff: Callable[[float | None], float] = events_backoff,
    ) -> None:
        self.kube = kube
        self.credentials = credentials
        self.controller_namespace = controller_namespace
        self.pod_cidr = pod_cidr
        self.core_namespace = core_namespace
        self.clock = clock
        self.sleep = sleep
        self.poll_s = poll_s
        self._backoff = backoff
        # Each node's renewals by `events`, (twin, node) to their times on `clock` within `RENEWAL_WINDOW_S`, a key
        # dropped when it is next read with every time past the window; and each pod left at a restart once the bound
        # was reached, (twin, uid, restart), so it is logged once. Both are kept while the twin is: `destroy` drops the
        # twin's once it is gone, so a twin made again under its name starts afresh. In memory alone: a core restarted
        # counts again, which its own restarts bound.
        self._renewals: dict[tuple[str, str], list[float]] = {}
        self._left: set[tuple[str, str, int]] = set()

    def capabilities(self) -> Capabilities:
        return CAPABILITIES

    def plan(
        self,
        manifest: Manifest,
        bundle_id: str,
        platforms: Mapping[str, PlatformPackage],
        probe_packages: Mapping[str, ProbePackage],
        twin: str,
        allocation: Allocation,
    ) -> Planned:
        return clabernetes_plan.plan(manifest, bundle_id, platforms, probe_packages, twin, allocation)

    def changes(
        self,
        before: Planned,
        after: Planned,
        platforms: Mapping[str, PlatformPackage],
        probe_packages: Mapping[str, ProbePackage],
    ) -> Changes:
        return clabernetes_changes.changes(before, after, platforms, probe_packages)

    async def admit(
        self,
        manifest: Manifest,
        platforms: Mapping[str, PlatformPackage],
        probe_packages: Mapping[str, ProbePackage],
        twin: str,
        reserved: Sequence[Allocation],
        held: Deployment | None = None,
    ) -> Allocation | Refusal:
        """The twin's namespace and the site's values as its allocation, `registries` holding
        every pull credential's prefix the provider holds now; or a refusal.

        It reads the namespace `namespace_of(twin)`: one that exists and is not the twin's is
        refused (`admission.namespace.taken`); one of the twin's still being deleted is admitted,
        and `apply` acts once it is gone. A pull credential the provider cannot give whole
        refuses the twin under the credential's own rule: a registry variable that is no image
        prefix (`credential.malformed`), or a registry set whose login is not
        (`credential.missing`), which would otherwise admit the twin and fail every `apply`
        after it. So does a registry key whose pull secret's name Kubernetes would refuse (not
        a DNS-1123 subdomain of at most 253 characters), under `credential.malformed`. Each
        message names the variable, never a value; no login is kept.

        With `held`, the deployment a stepping twin has applied, the answer is
        `held.allocation` unchanged, and the cluster is not read: the twin keeps its namespace
        and the registries it was admitted with (D-049). Each of those credentials is read from
        the provider again, so that a step is refused before it touches anything: one the
        provider refuses under its own rule, and one whose registry is no longer the prefix the
        twin was admitted with under `credential.malformed`. `apply` reads them again, for a
        credential removed while a run is under way. `reserved` is not read: a namespace is the
        twin's by its name, so no other twin's allocation can hold it."""
        if held is not None:
            try:
                for key, prefix in sorted(held.allocation["registries"].items()):
                    if self.credentials.pull(key).registry != prefix:
                        return _refuse(twin, RULE_MALFORMED, f"{RULE_MALFORMED}: {_drifted(key, twin)}")
            except (Missing, Malformed) as e:
                return _refuse(twin, e.rule, str(e))
            _log.info("admit %s: held allocation, namespace %s", twin, held.allocation["namespace"])
            return dict(held.allocation)
        namespace = namespace_of(twin)
        found = await self.kube.namespace(namespace)
        if found is not None and not _owned(found, twin):
            return _refuse(twin, RULE_NAMESPACE,
                           f"The namespace {namespace} exists and is not the twin {twin}'s: it lacks the labels "
                           f"{OWNER_LABEL}={OWNER} and {TWIN_LABEL}={twin}.")
        try:
            registries = self.credentials.registries()
            for key in registries:
                self.credentials.pull(key)  # its login too: the registry alone would fail every apply
        except (Missing, Malformed) as e:
            return _refuse(twin, e.rule, str(e))
        for key in registries:
            secret = pull_secret(key)
            if len(secret) > SECRET_NAME_MAX or not _SUBDOMAIN.fullmatch(secret):
                return _refuse(twin, RULE_MALFORMED,
                               f"{RULE_MALFORMED}: the environment variable FYLGJA_CREDENTIAL_{key}_REGISTRY gives "
                               f"the pull secret {secret}, which is no name Kubernetes accepts: a DNS-1123 subdomain "
                               f"of at most {SECRET_NAME_MAX} characters")
        allocation = {"namespace": namespace, "controller_namespace": self.controller_namespace,
                      "pod_cidr": self.pod_cidr, "registries": registries}
        if self.core_namespace is not None:
            allocation["core_namespace"] = self.core_namespace
        _log.info("admit %s: namespace %s; registries %s", twin, namespace, ", ".join(registries) or "none")
        return allocation

    async def apply(
        self,
        deployment: Deployment,
        files: Mapping[str, bytes],
        platforms: Mapping[str, PlatformPackage],
        probe_packages: Mapping[str, ProbePackage],
        reconfigure: bool = False,
    ) -> None:
        """Make the cluster hold the deployment: its Namespace, its NetworkPolicy, a pull secret
        for each registry of its allocation, and its Topology, each applied server-side; wait for
        the twin to be ready; then patch each LoadBalancer Service to `Local` (D-037).

        `ValueError`, before any call, for files that are not the deployment's (`check_files`),
        not the three a plan renders or not each one YAML mapping, an allocation whose namespace
        is not the twin's, a document not bound to it (`_bound`: the Namespace of that name, the
        NetworkPolicy in it, and the Topology named for the twin in it), or a node no given
        package runs. The namespace is read before anything is applied: one of the twin's name
        that is not the twin's, or one still being deleted, is `DriverFailed` with nothing
        applied, and the loop's retry applies once it is gone. One someone else makes between
        that read and the Namespace's apply is labelled the twin's by the forced server-side
        apply; the window is milliseconds, and accepted. Each
        pull secret, `pull_secret(key)` for each key of the allocation's registries, sorted, is a
        Docker config holding the provider's login keyed by the host of the allocation's prefix,
        applied before the Topology, which gets no pod while a secret it names is missing
        (verified-facts.md). Every credential is read before the first Secret is applied: one
        the provider refuses, or whose registry is not the allocation's prefix, is `DriverFailed`
        naming the variable, with no Secret applied.

        Under clabernetes' `live` link mode a port added after boot to a node whose kind cannot
        add one replaces no pod and the node never lists it; the node's next pod does
        (verified-facts.md). So before the Topology is applied, the one the cluster holds is
        read, the "before", as the topology on disk is the local driver's, and each node
        `changes` finds `recreated` for `hot_add` is named with the uid of its pod now (a node
        with no pod comes up with its ports, and is left out). Those, with any the Topology's
        annotation `RECREATE_ANNOTATION` already names, are pending: the Topology is applied
        carrying them in that annotation, a JSON object of node to uid, and as rendered when
        none is. A Topology the comparison cannot read, or an annotation that is no such
        object, is `DriverFailed` naming it, before the Topology is applied. With
        `reconfigure` no node is compared, as locally, since every pod is replaced: a Topology
        the comparison cannot read does not fail the remedy, and only what the annotation
        already names is pending.

        Then two waits share the deploy's budget. The first holds until the Topology has
        observed its generation, at two reads in a row, `poll_s` apart, when the apply deletes
        a pod after it (pending names one, or `reconfigure`): the controller's first write of a
        new generation can keep the status of the one before, and a pod deleted in that window
        was not read to come back from the new definition. Each pod of the twin still at a uid pending names is
        then deleted, a node whose pod is at another uid or gone logged and left; with
        `reconfigure`, every pod of the twin is deleted instead, so every node is made anew.
        When pending named any, the Topology is applied again as rendered, which removes the
        annotation and moves no generation. An `apply` stopped anywhere between the two applies
        leaves the annotation on the cluster, and the next finishes what it names: a pod already
        replaced is not replaced again. The second wait holds until two reads in a row, `poll_s`
        apart (`SETTLED_READS`), each find the generation still observed and the Topology ready,
        every node the definition names with its pod (`_current`, its newest not being deleted)
        `Ready`, no pod of a node it does not name remaining, a LoadBalancer Service for each
        node whose definition declares `ports`, and every LoadBalancer Service with an address;
        a read that finds anything else starts the count again. The status may read ready from
        before until the controller's pass, and for about 0.14 s after the pass that observes a
        new generation, every old pod still `Ready`; and a node being replaced keeps its old pod,
        deleting and `Ready`, for a while. The budget run out in either is `DriverFailed` naming
        what is not ready; a cancel stops it where it is."""
        namespace = _checked(deployment, files)
        twin = deployment.twin
        documents = {path: _document(path, data) for path, data in sorted(files.items())}
        _bound(documents, namespace, twin)
        registries: Mapping[str, str] = deployment.allocation["registries"]
        budget = deploy_budget(files, platforms, probe_packages, registries)
        deadline = self.clock() + budget
        definition: Mapping[str, Any] = wrapped(documents[TOPOLOGY])["nodes"]
        nodes = frozenset(definition)
        ported = frozenset(node for node, spec in definition.items() if spec.get("ports"))

        found = await self.kube.namespace(namespace)
        if found is not None and not _owned(found, twin):
            raise DriverFailed(f"the namespace {namespace} exists and is not the twin {twin}'s: it lacks the labels "
                               f"{OWNER_LABEL}={OWNER} and {TWIN_LABEL}={twin}")
        if found is not None and found.deleting:
            raise DriverFailed(f"the namespace {namespace} is being deleted: the twin {twin} is applied once it is "
                               "gone")
        for path in (NAMESPACE, POLICY):
            await self._apply(twin, documents[path])
        secrets = [self._pull_secret(twin, namespace, key, registries[key]) for key in sorted(registries)]
        for secret in secrets:
            await self._apply(twin, secret)

        topology = documents[TOPOLOGY]
        name = topology["metadata"]["name"]
        where = f"{namespace}/{name}"
        current = await self.kube.topology(namespace, name)
        unfinished = _unfinished(current, where)
        computed: dict[str, str] = {}
        if current is not None and not reconfigure and (
                hot_added := _hot_added(current, where, deployment, files, platforms, probe_packages)):
            pods = await self.kube.pods(namespace, _labels(twin))
            computed = {node: pod.uid for node in hot_added if (pod := _current(pods, node)) is not None}
        pending = {**unfinished, **computed}
        if pending:
            annotation = json.dumps(pending, sort_keys=True, separators=(",", ":"))
            _log.info("apply %s: the Topology %s names in %s the pods to replace, each node gaining a port its kind "
                      "cannot add after boot: %s", twin, name, RECREATE_ANNOTATION,
                      ", ".join(f"{node} (uid {uid})" for node, uid in sorted(pending.items())))
            await self._apply(twin, {**topology, "metadata": {**topology["metadata"],
                                                              "annotations": {RECREATE_ANNOTATION: annotation}}})
        else:
            await self._apply(twin, topology)
        observed_reads = SETTLED_READS if pending or reconfigure else 1
        await self._wait(twin, namespace, name, nodes, ported, budget, deadline, settled=False,
                         reads=observed_reads)
        if reconfigure:
            for pod in await self.kube.pods(namespace, _labels(twin)):
                if not pod.deleting:
                    await self.kube.delete_pod(namespace, pod.name)
                    _log.info("apply %s: deleted the pod %s (uid %s) of the node %s, since reconfigure makes every "
                              "node anew", twin, pod.name, pod.uid, pod.labels.get(NODE_LABEL))
        elif pending:
            await self._replace(twin, namespace, pending)
        if pending:
            await self._apply(twin, topology)
            _log.info("apply %s: removed the annotation %s from the Topology %s", twin, RECREATE_ANNOTATION, name)
        await self._wait(twin, namespace, name, nodes, ported, budget, deadline, settled=True, reads=SETTLED_READS)
        for service in await self.kube.services(namespace):
            if service.type == "LoadBalancer" and service.traffic_policy != LOCAL:
                await self.kube.patch_service(namespace, service.name, {"spec": {"externalTrafficPolicy": LOCAL}})
                _log.info("apply %s: patched the Service %s to externalTrafficPolicy %s (D-037)", twin, service.name,
                          LOCAL)
        _log.info("apply %s: ready", twin)

    async def inspect(self, twin: str) -> Inspection:
        """What the cluster holds of the twin, in its namespace `namespace_of(twin)`: `absent`
        when that does not exist or is not the twin's; `residue` when it is the twin's and holds
        no pod carrying the twin's labels; else `present`, a node for each value of
        `NODE_LABEL` among those pods, sorted by name.

        A node is the pod that stands for it: its newest not being deleted, or the newest of all
        when every one is (a node being replaced is its new pod, not running until it runs). Its
        handle is the pod's name; its incarnation `<uid>/<restarts>`, the pod's uid and its
        container's restart count, since a container restarted in place keeps the pod's uid
        (D-069); it runs when the pod's phase is `Running`, it is not being deleted and its
        container's state is `running`: a container ended in its pod leaves the phase `Running`
        while it is down (verified-facts.md, "the clabernetes driver's calls"), and a node still
        booting runs, as the local driver's container does, whether or not it is `Ready`; and its
        address is that of the `LoadBalancer` Service named for it, kept while its pod is
        replaced, and None without one: a probe host declares no port and has none. A pod of the
        twin with no `NODE_LABEL` is `DriverFailed` naming it.

        Each `LoadBalancer` Service of the namespace not at `Local` is patched to it and logged at
        WARNING with the value found: the seam's `Inspection` carries no drift, and every pass
        inspects (D-037, D-057)."""
        namespace = await self._held(twin)
        if namespace is None:
            return Inspection("absent", ())
        pods = await self.kube.pods(namespace, _labels(twin))
        if not pods:
            return Inspection("residue", ())
        for pod in pods:
            if not pod.labels.get(NODE_LABEL):
                raise DriverFailed(f"the pod {pod.name} of the twin {twin} has no {NODE_LABEL} label")
        services = await self.kube.services(namespace)
        for service in services:
            if service.type == "LoadBalancer" and service.traffic_policy != LOCAL:
                await self.kube.patch_service(namespace, service.name, {"spec": {"externalTrafficPolicy": LOCAL}})
                _log.warning("inspect %s: the Service %s was at externalTrafficPolicy %s: patched to %s (D-037, D-057)",
                             twin, service.name, service.traffic_policy, LOCAL)
        addresses = {service.name: service.address for service in services if service.type == "LoadBalancer"}
        nodes = []
        for node in sorted({pod.labels[NODE_LABEL] for pod in pods}):
            standing = _standing_for(pods, node)
            assert standing is not None, "a node named by a pod has one"
            nodes.append(NodeState(name=node, handle=standing.name, incarnation=f"{standing.uid}/{standing.restarts}",
                                   address=addresses.get(node),
                                   running=_runs(standing)))
        return Inspection("present", tuple(nodes))

    async def destroy(
        self,
        deployment: Deployment,
        files: Mapping[str, bytes],
        platforms: Mapping[str, PlatformPackage],
        probe_packages: Mapping[str, ProbePackage],
    ) -> None:
        """Delete the twin's namespace, the allocation's, with all it holds, and wait until it
        is gone. `ValueError`, before any call, as `apply` refuses: files that are not the
        deployment's (`check_files`) or not the three a plan renders, an allocation whose
        namespace is not the twin's, or a node no given package runs.

        A namespace absent is nothing done. One that is not the twin's is logged at WARNING and
        left: the driver never deletes it. One already being deleted is not asked again. The
        namespace is read every `poll_s` until it is gone; once the destroy's budget has passed
        (`destroy_budget`) it is `DriverFailed`, the loop's to retry. With the twin gone, what
        `events`' renewal kept of it is dropped (`_forget`), so a twin made again under its name
        is not bounded by the count of the one before."""
        namespace = _checked(deployment, files)
        twin = deployment.twin
        budget = destroy_budget(files, platforms, probe_packages, deployment.allocation["registries"])
        deadline = self.clock() + budget
        found = await self.kube.namespace(namespace)
        if found is None:
            _log.info("destroy %s: the namespace %s is absent: nothing to delete", twin, namespace)
            self._forget(twin)
            return
        if not _owned(found, twin):
            _log.warning("destroy %s: the namespace %s is not the twin's: it lacks the labels %s=%s and %s=%s, so it "
                         "is left", twin, namespace, OWNER_LABEL, OWNER, TWIN_LABEL, twin)
            return
        if found.deleting:
            _log.info("destroy %s: the namespace %s is already being deleted", twin, namespace)
        else:
            await self.kube.delete_namespace(namespace)
            _log.info("destroy %s: deleted the namespace %s", twin, namespace)
        while await self.kube.namespace(namespace) is not None:
            if self.clock() >= deadline:
                raise DriverFailed(f"the namespace {namespace} was not gone within {budget:g}s")
            await self.sleep(self.poll_s)
        _log.info("destroy %s: the namespace %s is gone", twin, namespace)
        self._forget(twin)

    def _forget(self, twin: str) -> None:
        """Drop what `events`' renewal keeps of `twin`, gone: its nodes' renewals and its pods left."""
        self._renewals = {key: times for key, times in self._renewals.items() if key[0] != twin}
        self._left = {left for left in self._left if left[0] != twin}

    async def endpoints(self, twin: str) -> Mapping[str, str]:
        """Each running node's address, by node name, as the local driver's: a node not running,
        or with no address (a probe host, or a Service not yet given one), is left out."""
        inspection = await self.inspect(twin)
        return {n.name: n.address for n in inspection.nodes if n.running and n.address}

    async def exec(self, twin: str, node: str, argv: Sequence[str], timeout_s: float) -> Exec:
        """Run `argv` in the node's pod, the one `inspect` answers for it, naming no container
        and with no shell, within `timeout_s`; the status and the tail of each output as
        `Kube.exec` keeps it, never logged.

        The two drivers answer alike: a non-zero status is the command's answer, but one in
        `EXEC_UNREACHED`, which the local driver takes for a command that could not be run, is
        `DriverFailed` naming the pod and the status. A node with no pod is `DriverFailed` with
        nothing run, and so is one whose twin's namespace is missing or not the twin's, where
        `inspect` answers `absent`; a binary the node lacks (the API's 500, where docker answers
        127), a pod gone and a budget run out are each a `KubeFailed`, a `DriverFailed`. A
        budget run out leaves the command running in the node (verified-facts.md), so a caller
        passes one that ends by itself."""
        namespace = await self._held(twin)
        pods = await self.kube.pods(namespace, _labels(twin)) if namespace is not None else []
        pod = _standing_for(pods, node)
        if namespace is None or pod is None:
            raise DriverFailed(f"the twin {twin} has no pod for the node {node}")
        _log.info("exec %s: %s in the pod %s of the node %s", twin, shlex.join(argv), pod.name, node)
        answer = await self.kube.exec(namespace, pod.name, argv, timeout_s)
        if answer.returncode in EXEC_UNREACHED:
            raise DriverFailed(f"exec into {pod.name} failed with status {answer.returncode}")
        return answer

    async def events(self) -> AsyncIterator[str]:
        """The twins whose runtime changed (D-058), from one watch on the pods labelled
        `OWNER_LABEL: OWNER` in every namespace (`Kube.watch_pods`): the twin of each pod
        (`twin_of`) that is added or deleted, or modified in what the loop reads of it through
        `inspect` (`_read`: its uid and its container's restart count, its incarnation; its phase,
        its deletion and its container's state, whether it runs) or in whether it is `Ready`. A
        change to nothing of that names nothing, so a twin is not inspected for it (how often the
        cluster modifies a settled pod is not yet read); nor does a pod that names no twin, passed
        over at DEBUG, its labels never logged.

        The watch reconnects for itself (`Kube.watch_pods`): lightkube asks again at the version it
        reached, so a change during its reconnect is delivered then, not lost; after a version too
        old, or a fresh watch after a failure, it delivers every pod there again, `ADDED`, so every
        twin with a pod is named again, and a twin whose every pod went during that gap is named by
        the loop's resync alone (pre-flight ruling 4). So a pod whose container ended or restarted
        during a reconnect is renewed when the change is delivered, and one whose end a fresh
        watch missed is renewed when that watch delivers it, ended or at a count above 0.

        Should the watch raise or end all the same, that is one WARNING naming it by its type and
        the API's status code, never its text, which can name the API server's address; then,
        after `backoff(previous)` (the seam's `events_backoff`, which the first name a watch yields
        resets) on the driver's `sleep`, it is watched again with nothing kept, and its first
        events name every twin with a pod. It ends only when cancelled, and a cancel or a close
        ends the watch with it.

        A pod not being deleted whose container has ended in it (`Pod.container_ended`, a state no
        starting pod passes through) or restarted in it (its restart count above 0) is deleted
        before its twin is named (`_renew`), so the cluster makes the node anew: a container
        restarted in its pod does not get its management address again on clabernetes 0.10.1
        (verified-facts.md, "a container restarted in its pod"), and the loop never makes a node.
        Renewed at the container's end, about 25 s before the kubelet restarts it, the replacement
        boots inside the node's boot window. A pass the name kicks finds the pod being deleted,
        never the node running at an address that does not answer. The rule reads the pod as
        delivered, not its move, so a pod a fresh watch delivers again is renewed then.

        A renewal that fails deletes nothing: the pod's twin is named, then the watch ends with a
        WARNING naming the pod, by the failure's type and status, and the next watch delivers the
        pod again. Such a round waits a backoff of its own, `backoff(the last such delay)`, which
        the names it gave do not reset and a round that ends otherwise does: while a deletion keeps
        failing, twins whose pods come after it in the listing are named by the resync alone, and
        the round repeats at most once a minute."""
        previous: float | None = None  # the watch's own failures: the first name a watch yields resets it
        renewing: float | None = None  # rounds that end in a failed renewal: reset by a round that ends otherwise
        while True:
            # What each pod was last read as, by namespace and name. A pod deleted while lightkube's watch was down is
            # never delivered `DELETED` by the fresh watch after it, so what was read of it stays until this loop's next
            # round: a slow growth, known and left (D-070 item 11).
            kept: dict[tuple[str, str], _Read] = {}
            failed: tuple[str, Pod, Exception] | None = None
            try:
                async with contextlib.aclosing(self.kube.watch_pods({OWNER_LABEL: OWNER})) as changes:
                    async for operation, pod in changes:
                        twin = twin_of(pod)
                        if twin is None:
                            _log.debug("the pod watch: a pod that names no twin is passed over")
                            continue
                        where, read = (pod.namespace, pod.name), _read(pod)
                        if operation == "DELETED":
                            kept.pop(where, None)
                        elif operation == "MODIFIED" and kept.get(where) == read:
                            continue
                        else:
                            kept[where] = read
                        renewing_it = pod.restarts > 0 or pod.container_ended
                        if operation != "DELETED" and renewing_it and not pod.deleting:
                            try:
                                await self._renew(twin, pod)
                            except Exception as e:  # nothing deleted: the twin is named, then the watch ends
                                failed = (twin, pod, e)
                        previous = None  # the watch works: a later failure waits the first backoff again
                        yield twin
                        if failed is not None:
                            break
            except Exception as e:  # whatever the watch raised; it is never raised past the seam
                how, fields = _failure(e)
            else:
                how, fields = "no failure", {}
            if failed is not None:
                twin, pod, error = failed
                how, fields = _failure(error)
                renewing = delay = self._backoff(renewing)
                _log.warning("the renewal of the pod %s of the node %s of the twin %s failed (%s): it is watched again "
                             "in %gs, and names the twin of each pod there again", pod.name,
                             pod.labels.get(NODE_LABEL), twin, how, delay,
                             **logs.fields(**fields, twin=twin, node=pod.labels.get(NODE_LABEL), pod=pod.name,
                                           retry_s=delay))
            else:
                renewing = None
                delay = previous = self._backoff(previous)
                _log.warning("the pod watch ended (%s): it is watched again in %gs, and names the twin of each pod "
                             "there again", how, delay, **logs.fields(**fields, retry_s=delay))
            await self.sleep(delay)

    async def _renew(self, twin: str, pod: Pod) -> None:
        """Delete `pod`, the twin's, whose container ended or restarted in it, so that its
        Deployment makes the node anew: on clabernetes 0.10.1 an SR Linux node's container
        restarted in its pod holds no address on its management subinterface again, and its ports
        answer nothing from outside (verified-facts.md; cEOS and a probe host were not read, and
        the rule is every node's alike). Held to the test the hot-add's deletions pass (`_replace`): the pod
        must be in the twin's own namespace, `namespace_of(twin)`, which must be the twin's
        (`_held`), and must stand there at its uid, a node's pod (`NODE_LABEL`) carrying both of
        the twin's labels and not being deleted: a pod already replaced, or a change delivered
        after the deletion from before it, deletes nothing. Each deletion is one audit line, the
        one line that says it: the renewal changes a twin under no run, so it is the core's own
        principal's (`RENEWAL_PRINCIPAL`), naming the twin, the node, the pod, its uid and its
        restart count (Constitution X). A failure is raised, to `events`, which watches again.

        A node is renewed at most `RENEWALS` times in `RENEWAL_WINDOW_S`, on the driver's clock,
        counted in the driver's memory, so a core restarted counts again. Past that its pod is left
        as it is, with one WARNING for that pod at that restart (its container's end at a count
        and its running at the next are one restart), and its twin is named as for any change: the
        loop reads it, and its restore reports what it finds. A delivery once the window has room
        renews it again."""
        namespace = namespace_of(twin)
        if pod.namespace != namespace or await self._held(twin) != namespace:
            return
        for standing in await self.kube.pods(namespace, _labels(twin)):
            node = standing.labels.get(NODE_LABEL)
            if standing.uid != pod.uid or not node or standing.deleting:
                continue
            now, key = self.clock(), (twin, node)
            recent = [at for at in self._renewals.pop(key, []) if now - at < RENEWAL_WINDOW_S]
            if recent:
                self._renewals[key] = recent
            if len(recent) >= RENEWALS:
                restart = standing.restarts + int(standing.container_ended)  # ended at n, it runs again at n + 1
                if (twin, standing.uid, restart) not in self._left:
                    self._left.add((twin, standing.uid, restart))
                    _log.warning("events %s: left the pod %s of the node %s at %d restart%s: the node was renewed %d "
                                 "times in the last %gs, so the cluster is not asked to make it anew again yet", twin,
                                 standing.name, node, standing.restarts, "" if standing.restarts == 1 else "s",
                                 RENEWALS, RENEWAL_WINDOW_S,
                                 **logs.fields(twin=twin, node=node, pod=standing.name, restarts=standing.restarts))
                return
            await self.kube.delete_pod(namespace, standing.name)
            self._renewals[key] = [*recent, now]
            logs.audit(RENEWAL_PRINCIPAL, "renew", twin, node=node, pod=standing.name, uid=standing.uid,
                       restarts=standing.restarts)

    async def _held(self, twin: str) -> str | None:
        """The twin's namespace, `namespace_of(twin)`, when it exists and is the twin's (`_owned`);
        None otherwise, and nothing of it is the driver's to read or act in."""
        namespace = namespace_of(twin)
        found = await self.kube.namespace(namespace)
        return namespace if found is not None and _owned(found, twin) else None

    async def _apply(self, twin: str, obj: Mapping[str, Any]) -> None:
        """Apply `obj`, logged by its kind and name, never its body."""
        await self.kube.apply(obj)
        _log.info("apply %s: applied %s %s", twin, obj["kind"], obj["metadata"]["name"])

    async def _replace(self, twin: str, namespace: str, pending: Mapping[str, str]) -> None:
        """Delete each pod of the twin still at a uid `pending` names, node to uid, so that the
        node comes up anew with its ports. A node whose pod is already at another uid, or that
        has none, is logged and left: a killed `apply` deleted it, or someone else did."""
        pods = await self.kube.pods(namespace, _labels(twin))
        standing = {pod.uid: pod for pod in pods if not pod.deleting}
        for node, uid in sorted(pending.items()):
            if (pod := standing.get(uid)) is not None:
                await self.kube.delete_pod(namespace, pod.name)
                _log.info("apply %s: deleted the pod %s (uid %s) of the node %s, %s", twin, pod.name, uid, node,
                          _HOT_ADD)
            elif (now := _current(pods, node)) is not None:
                _log.info("apply %s: the node %s's pod is at uid %s, not %s: already replaced, so left", twin, node,
                          now.uid, uid)
            else:
                _log.info("apply %s: the node %s has no pod, the one at uid %s gone: nothing to replace", twin, node,
                          uid)

    def _pull_secret(self, twin: str, namespace: str, key: str, prefix: str) -> dict[str, Any]:
        """The Secret `pull_secret(key)` of the twin's namespace: a Docker config holding the
        login of the pull credential `key`, read from the provider now, under the host of
        `prefix` (up to its first `/`), the allocation's prefix for `key`, which the Topology's
        images are written under. `DriverFailed` naming the variable when the provider refuses
        it, `Missing` or `Malformed` alike, or when its registry is not `prefix`: the twin is
        bound to the prefix it was admitted with (D-057)."""
        try:
            credential = self.credentials.pull(key)
        except (Missing, Malformed) as e:
            raise DriverFailed(str(e)) from e
        if credential.registry != prefix:
            raise DriverFailed(_drifted(key, twin))
        host = prefix.split("/", 1)[0]
        login = f"{credential.username}:{credential.password}".encode()
        config = {"auths": {host: {"username": credential.username, "password": credential.password,
                                   "auth": _base64(login)}}}
        return {
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": pull_secret(key), "namespace": namespace, "labels": _labels(twin)},
            "type": "kubernetes.io/dockerconfigjson",
            "data": {".dockerconfigjson": _base64(json.dumps(config).encode())},
        }

    async def _wait(
        self, twin: str, namespace: str, name: str, nodes: frozenset[str], ported: frozenset[str], budget: float,
        deadline: float, *, settled: bool, reads: int,
    ) -> None:
        """Read the cluster every `poll_s` until `reads` reads in a row find nothing in
        `_waiting`, a read that finds anything starting the count again: for the Topology `name`'s
        generation observed, and, when `settled`, for the twin ready. The controller's first
        write of a new generation keeps the readiness of the one before for about 0.14 s, every
        old pod `Ready`, before it acts on the generation (verified-facts.md, "the clabernetes
        driver's calls"), so one read can find the twin ready on the generation before; two
        reads `poll_s` apart cannot both, while the window stays narrower than `poll_s`: it was
        read only on a lightly loaded cluster. `DriverFailed` once `deadline` has passed at a read
        that finds something, naming all that keeps the twin from being ready."""
        found_nothing = 0
        while True:
            waiting = await self._waiting(twin, namespace, name, nodes, ported, settled=settled)
            if not waiting:
                found_nothing += 1
                if found_nothing == reads:
                    return
            else:
                found_nothing = 0
                if self.clock() >= deadline:
                    if not settled:
                        waiting = await self._waiting(twin, namespace, name, nodes, ported, settled=True) or waiting
                    raise DriverFailed(f"the twin {twin} was not ready within {budget:g}s: {'; '.join(waiting)}")
            await self.sleep(self.poll_s)

    async def _waiting(
        self, twin: str, namespace: str, name: str, nodes: frozenset[str], ported: frozenset[str], *, settled: bool,
    ) -> list[str]:
        """What keeps the twin from being ready, a phrase each, none when it is: the Topology
        `name` absent, or its generation not observed; and, when `settled`, the Topology not
        ready, each node of `nodes` without a ready pod, the pods of any node not in `nodes`,
        deleting or not, each node of `ported`, those whose definition declares `ports`,
        without its LoadBalancer Service, the Service named for it, and each LoadBalancer
        Service without an address."""
        waiting: list[str] = []
        topology = await self.kube.topology(namespace, name)
        if topology is None:
            waiting.append(f"the Topology {name} is absent")
        else:
            generation = topology["metadata"]["generation"]
            status = topology.get("status") or {}
            if status.get("observedGeneration") != generation:
                waiting.append(f"the Topology {name} has not observed its generation {generation}")
            elif settled and status.get("topologyReady") is not True:
                waiting.append(f"the Topology {name} is not ready")
        if not settled:
            return waiting
        pods = await self.kube.pods(namespace, _labels(twin))
        unready = sorted(node for node in nodes if not ((pod := _current(pods, node)) and pod.ready))
        if unready:
            waiting.append(f"no ready pod for {', '.join(unready)}")
        unnamed = sorted({pod.labels[NODE_LABEL] for pod in pods if pod.labels.get(NODE_LABEL, "") not in {"", *nodes}})
        if unnamed:
            waiting.append(f"the pods of {', '.join(unnamed)}, which the topology does not name, remain")
        balancers = [s for s in await self.kube.services(namespace) if s.type == "LoadBalancer"]
        unmade = sorted(ported - {s.name for s in balancers})
        if unmade:
            waiting.append(f"no LoadBalancer Service for {', '.join(unmade)}")
        unaddressed = [s.name for s in balancers if not s.address]
        if unaddressed:
            waiting.append(f"no address for the Services {', '.join(unaddressed)}")
        return waiting


def deploy_budget(
    files: Mapping[str, bytes],
    platforms: Mapping[str, PlatformPackage],
    probe_packages: Mapping[str, ProbePackage],
    registries: Mapping[str, str],
) -> float:
    """The budget of a deploy of `files`: the largest `deploy_timeout_s` of the packages the
    Topology's nodes use, since nodes deploy in parallel, plus `MARGIN_S`. `registries` is the
    deployment's `allocation["registries"]`, the prefixes a gated node's image is written
    under, which the files do not carry. `ValueError` for a node no given package runs."""
    sections = _sections(files, platforms, probe_packages, registries)
    return max(section.deploy_timeout_s for section in sections) + MARGIN_S


def destroy_budget(
    files: Mapping[str, bytes],
    platforms: Mapping[str, PlatformPackage],
    probe_packages: Mapping[str, ProbePackage],
    registries: Mapping[str, str],
) -> float:
    """The budget of a destroy of `files`: the largest `destroy_timeout_s` of the packages the
    Topology's nodes use, plus `MARGIN_S`; `registries` as `deploy_budget` takes it."""
    sections = _sections(files, platforms, probe_packages, registries)
    return max(section.destroy_timeout_s for section in sections) + MARGIN_S


def _sections(
    files: Mapping[str, bytes],
    platforms: Mapping[str, PlatformPackage],
    probe_packages: Mapping[str, ProbePackage],
    registries: Mapping[str, str],
) -> list[platform_package.Containerlab | probe_package.Containerlab]:
    """The containerlab section of each package a node of the Topology in `files` uses, found as
    `changes` finds it (`clabernetes.changes.sections_of`)."""
    nodes: Mapping[str, Any] = wrapped(yaml.safe_load(files[TOPOLOGY]))["nodes"]
    return [section for name, node in nodes.items()
            for section in sections_of(name, node, platforms, probe_packages, [registries])]


def _hot_added(
    current: Mapping[str, Any],
    where: str,
    deployment: Deployment,
    files: Mapping[str, bytes],
    platforms: Mapping[str, PlatformPackage],
    probe_packages: Mapping[str, ProbePackage],
) -> list[str]:
    """Each node `changes` finds `recreated` for `hot_add` from `current`, the Topology `where`
    (`<namespace>/<name>`) the cluster holds, to the one in `files`. The cluster's Topology is
    the "before", as the topology on disk is the local driver's (D-057); both sides carry
    `deployment`, `changes` checking only that they are one twin's. `DriverFailed` naming the
    Topology and the cause when the comparison cannot read it, by what reading a Topology
    raises (`ValueError`, `KeyError`, `TypeError`, `yaml.YAMLError`); anything else is a fault
    of the comparison, not of the cluster, and is raised as it is, never retried. A Topology
    whose links are not as `plan` writes them (`_links_as_written`), which only a hand-edited
    one is, is `DriverFailed` naming it before the comparison reads them: an endpoint that is
    not text would otherwise fail the comparison with an `AttributeError`, which is none of
    those.

    A node whose link mode changed, which the controller rebuilds itself, and which is also
    named here for `hot_add` may have its old pod deleted by both the controller and `apply`:
    either way it ends at one new pod, with its ports."""
    metadata = current.get("metadata") or {}
    try:
        if not _links_as_written(wrapped(current)):
            raise DriverFailed(f"the Topology {where} the cluster holds is not one the driver wrote: its links are not "
                               "a list of links whose endpoints are text")
        before = {"apiVersion": current["apiVersion"], "kind": current["kind"],
                  "metadata": {"name": metadata["name"], "namespace": metadata["namespace"]}, "spec": current["spec"]}
        diff = clabernetes_changes.changes(Planned(deployment, {TOPOLOGY: yaml.safe_dump(before).encode()}),
                                           Planned(deployment, files), platforms, probe_packages)
    except (ValueError, KeyError, TypeError, yaml.YAMLError) as e:
        cause = type(e).__name__ if isinstance(e, yaml.YAMLError) else f"{type(e).__name__}: {e}"
        raise DriverFailed(f"the Topology {where} the cluster holds cannot be compared: {cause}") from e
    return [n.node for n in diff.nodes if n.action == "recreated" and "hot_add" in n.reasons]


def _links_as_written(definition: Any) -> bool:
    """Whether `definition`, the `topology` member of the containerlab definition a Topology on
    the cluster holds, has its links as `plan` writes them: a list of mappings, each with its
    `endpoints` a list of strings, which is all the comparison reads of a link."""
    links = definition.get("links") if isinstance(definition, dict) else None
    return isinstance(links, list) and all(
        isinstance(link, dict) and isinstance(link.get("endpoints"), list)
        and all(isinstance(endpoint, str) for endpoint in link["endpoints"])
        for link in links)


def _unfinished(topology: Mapping[str, Any] | None, where: str) -> dict[str, str]:
    """What an `apply` stopped before it finished left to replace: the JSON object, node to pod
    uid, in the annotation `RECREATE_ANNOTATION` of `topology`, the Topology `where` the cluster
    holds; empty when there is no Topology or no annotation. `DriverFailed` naming the
    annotation, and never quoting it, for a value that is no such object."""
    if topology is None:
        return {}
    value = ((topology.get("metadata") or {}).get("annotations") or {}).get(RECREATE_ANNOTATION)
    if value is None:
        return {}
    try:
        found = json.loads(value)
    except (TypeError, ValueError):
        found = None
    if not (isinstance(found, dict) and all(isinstance(uid, str) for uid in found.values())):
        raise DriverFailed(f"the Topology {where} carries the annotation {RECREATE_ANNOTATION}, which is no JSON "
                           "object of each node to its pod's uid")
    return found


def _checked(deployment: Deployment, files: Mapping[str, bytes]) -> str:
    """The twin's namespace, `namespace_of(deployment.twin)`, which `apply` and `destroy` act
    in. `ValueError` unless `files` are exactly the deployment's, each with the SHA-256 it lists
    (`check_files`), and the three a plan renders, and unless the allocation names that
    namespace; an allocation that names none is refused alike."""
    check_files(deployment, files)
    if set(files) != {NAMESPACE, POLICY, TOPOLOGY}:
        raise ValueError(f"the files {sorted(files)} are not a clabernetes deployment's: {NAMESPACE}, {POLICY} "
                         f"and {TOPOLOGY}")
    twin = deployment.twin
    namespace = namespace_of(twin)
    if deployment.allocation.get("namespace") != namespace:
        raise ValueError(f"the deployment's namespace {deployment.allocation.get('namespace')!r} is not the twin "
                         f"{twin}'s, {namespace}")
    return namespace


def _bound(documents: Mapping[str, Mapping[str, Any]], namespace: str, twin: str) -> None:
    """`ValueError` unless each of the deployment's documents is bound to the twin's namespace,
    `namespace`, as `plan` renders it: `NAMESPACE` the Namespace of that name, `POLICY` a
    NetworkPolicy in it, and `TOPOLOGY` the Topology named for the twin in it; so that `apply`
    acts in the namespace it checked and nowhere else (one with no namespace would land in the
    client's default)."""
    bound = {NAMESPACE: ("Namespace", None, namespace), POLICY: ("NetworkPolicy", namespace, None),
             TOPOLOGY: ("Topology", namespace, twin)}
    for path, (kind, inside, name) in bound.items():
        document = documents[path]
        metadata = document.get("metadata")
        held: Mapping[str, Any] = metadata if isinstance(metadata, dict) else {}
        if document.get("kind") != kind:
            raise ValueError(f"{path} is not the twin {twin}'s: its kind is {document.get('kind')!r}, not {kind}")
        if inside is not None and held.get("namespace") != inside:
            raise ValueError(f"{path} is not the twin {twin}'s: its namespace is {held.get('namespace')!r}, not "
                             f"{inside}")
        if name is not None and held.get("name") != name:
            raise ValueError(f"{path} is not the twin {twin}'s: its name is {held.get('name')!r}, not {name}")


def _drifted(key: str, twin: str) -> str:
    """Why the pull credential `key` no longer serves the twin: its registry is not the prefix the
    twin was admitted with. Names the variable, never its value."""
    return (f"the environment variable {credentials.variable(key, 'REGISTRY')} names another registry than the one "
            f"the twin {twin} was admitted with, under which its images are written for its life (D-057)")


def _owned(namespace: Namespace, twin: str) -> bool:
    """Whether `namespace` is the twin's: it carries both labels, the twin's name in the second."""
    return namespace.labels.get(OWNER_LABEL) == OWNER and namespace.labels.get(TWIN_LABEL) == twin


def twin_of(pod: Pod) -> str | None:
    """The twin `pod` is of: its `TWIN_LABEL`, when it carries `OWNER_LABEL: OWNER` too and the
    value is a twin name (`check_twin_name`); else None. Never read from the pod's namespace or
    its name."""
    twin = pod.labels.get(TWIN_LABEL)
    if pod.labels.get(OWNER_LABEL) != OWNER or twin is None:
        return None
    try:
        return check_twin_name(twin)
    except ValueError:
        return None


_Read = tuple[str, int, str, bool, bool, bool, bool]


def _read(pod: Pod) -> _Read:
    """What the loop reads of `pod` through `inspect`, and whether it is `Ready`, which `events`
    names its twin for a change of: its uid and its container's restart count (the node's
    incarnation, D-069), its phase, its deletion and its container's state (whether the node
    runs), and its `Ready` condition (D-058). A kept pod's `Ready` can blink for a second or two
    after a step, its uid and restarts unchanged (verified-facts.md, "the clabernetes driver's
    calls"): each move costs the loop one inspect, which finds nothing moved and writes nothing.
    And whether its container has ended in it, which `events` renews the pod for."""
    return (pod.uid, pod.restarts, pod.phase, pod.deleting, pod.container_running, pod.ready, pod.container_ended)


def _failure(e: Exception) -> tuple[str, dict[str, Any]]:
    """How a failure of the pod watch, or of a renewal, is logged: its type and, for the API's
    refusal, its status code; never its text, which can name the API server's address
    (Constitution X)."""
    if isinstance(e, KubeFailed) and e.status is not None:
        return f"{type(e).__name__}, status {e.status}", {"error": type(e).__name__, "status": e.status}
    return type(e).__name__, {"error": type(e).__name__}


def _labels(twin: str) -> dict[str, str]:
    """The two labels every object the driver makes carries, and every pod of the twin."""
    return {OWNER_LABEL: OWNER, TWIN_LABEL: twin}


def _current(pods: Sequence[Pod], node: str) -> Pod | None:
    """The node's pod among `pods`: its newest not being deleted, by creation time and then by
    name; None when it has none. A node being replaced has two pods for a while, the old one
    deleting and still `Ready` beside its `Pending` replacement (verified-facts.md), and the
    old one is never the node's."""
    found = [pod for pod in pods if pod.labels.get(NODE_LABEL) == node and not pod.deleting]
    return max(found, key=lambda pod: (pod.created, pod.name), default=None)


def _runs(pod: Pod) -> bool:
    """Whether the node `pod` stands for runs: the pod's phase `Running`, the pod not being
    deleted, and its container running."""
    return pod.phase == "Running" and not pod.deleting and pod.container_running


def _standing_for(pods: Sequence[Pod], node: str) -> Pod | None:
    """The pod that stands for the node in `inspect` and `exec`: its own (`_current`), or, when
    every pod it has is being deleted, the newest of those; None when it has none."""
    found = [pod for pod in pods if pod.labels.get(NODE_LABEL) == node]
    return _current(found, node) or max(found, key=lambda pod: (pod.created, pod.name), default=None)


def _document(path: str, data: bytes) -> dict[str, Any]:
    """The one YAML mapping the deployment's file `path` holds; `ValueError` for anything else."""
    try:
        document = yaml.safe_load(data)
    except yaml.YAMLError as e:
        raise ValueError(f"{path} is not one YAML mapping: {type(e).__name__}") from None
    if not isinstance(document, dict):
        raise ValueError(f"{path} is not one YAML mapping")
    return document


def _base64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _refuse(twin: str, rule: str, message: str) -> Refusal:
    _log.info("admit %s refused, %s: %s", twin, rule, message)
    return Refusal(rule, message)
