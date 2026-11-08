"""The clabernetes driver's `changes`: what the cluster does to each node's pod to go from one
deployment's Topology to another's (D-049, D-057).

It is pure, as the local driver's is (Constitution V and XIII): no I/O, clock or environment,
which a test enforces through its imports. clabernetes has no dry run to ask, so the answer is
written from the facts recorded on the cluster (verified-facts.md, "clabernetes 0.10.1" and
"k3s v1.37.1+k3s1, three servers, with clabernetes 0.10.1"), in the seam's vocabulary. It
compares the two containerlab definitions the Topologies wrap through the local driver's
`compare`, so a node in both gets the local driver's reasons, and finds a node's packages by
its image as the Topology writes it (`sections_of`, the local driver's lookup told how):
a package runs a node when its kind is the node's and its image, written under either
deployment's registries (`plan.image`), is the node's, and a gated image whose pull secret
neither allocation holds is written under none; a probe package runs a `linux` node by its
image, likewise. The rules, and the facts each is written from:

- A link change under the `live` mode re-cables and keeps the pod, `recabled`: no pod was
  replaced ("Steps", and "Steps across hosts").
- A link change under the `restart` mode replaces the link's pods ("Steps": `restart` and
  `recreate` each replaced the link's cEOS pods). It is `restarted`, the seam's word for a
  link change under that mode, and `restarts()` covers it as it covers `recreated`.
- A change to a host's start-up lines alone replaces that host's pod and keeps the others,
  `recreated` for `exec` ("A probe host runs as locally").
- A port added after boot to a kind that cannot add one is never seen until the pod is
  replaced ("Steps"; "A cEOS port added after boot arrives with a new pod"). It is `recreated`
  for `hot_add`, by the local driver's approximation, and `apply` makes it so.
- A node in one definition only is `added` or `removed`; under `live` the others keep their
  pods ("Steps").
- A change to a node's link mode replaces that node's pod, and no other ("fylgja-core, phase
  6: the Topology's status, and the pods replaced, read by hand": of three nodes cabled in a
  line, one node's mode changed replaced its pod alone, and two nodes' replaced those two,
  their neighbour kept). It is `recreated` for `link_mode`, as the local driver answers it. The
  earlier readings that a mode change replaces every pod ("Steps"; "Steps across hosts") had
  changed every node's mode at once.
- A change to a node's kind and image replaces that node's pod alone, its neighbours
  re-cabled ("fylgja-core, phase 6: the clabernetes driver's calls": `n3` from SR Linux to
  cEOS). It is `recreated` for `kind` and `image`.

Its oracle is the cluster (D-057): `core/tests/cluster/test_clabernetes_changes_cluster.py`
holds every kind of change the step fixtures make to the pods' uids before and after the
step. A uid changes exactly for `restarted` and `recreated`; an `added` node is a new pod and
a `removed` one has none. No fact covers three answers yet: that a node added with another
link mode than the twin's replaces no other pod (`added`), that a link changed between two
nodes of different link modes replaces the pod at its `restart` end alone and re-cables its
`live` end (`restarted` at one end, `recabled` at the other), and that a probe host keeps its
pod when a device's link mode changes (`kept`).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import yaml

from fylgja_core.clabernetes.plan import TOPOLOGY, image
from fylgja_core.containerlab.changes import Section, compare
from fylgja_core.containerlab.changes import sections_of as clab_sections_of
from fylgja_core.driver import Changes, Planned
from fylgja_core.platform_package import Image, PlatformPackage
from fylgja_core.probe_package import ProbePackage


def changes(
    before: Planned,
    after: Planned,
    platforms: Mapping[str, PlatformPackage],
    probe_packages: Mapping[str, ProbePackage],
) -> Changes:
    """What the cluster does to each node's pod to go from `before` to `after`. `ValueError` for
    deployments of two twins, or for a node no given package runs."""
    if before.deployment.twin != after.deployment.twin:
        raise ValueError(f"the deployments are of two twins, {before.deployment.twin} and {after.deployment.twin}")
    registries = tuple(planned.deployment.allocation["registries"] for planned in (before, after))

    def sections(name: str, node: Mapping[str, Any]) -> list[Section]:
        return sections_of(name, node, platforms, probe_packages, registries)

    return compare(_definition(before), _definition(after), sections)


def sections_of(
    name: str,
    node: Mapping[str, Any],
    platforms: Mapping[str, PlatformPackage],
    probe_packages: Mapping[str, ProbePackage],
    registries: Sequence[Mapping[str, str]],
) -> list[Section]:
    """The containerlab section of each package that runs the Topology's node `name`, whose
    definition entry is `node`: the local driver's lookup, a package's image matched as the
    Topology writes it under any of `registries`, each an allocation's (`plan.image`).
    `ValueError` for a node no given package runs."""

    def written(pulled: Image) -> set[str]:
        return _written(pulled, registries)

    return clab_sections_of(name, node, platforms, probe_packages, written)


def wrapped(topology: Mapping[str, Any]) -> dict[str, Any]:
    """The `topology` member of the containerlab definition the Topology object `topology`
    holds in `spec.definition.containerlab`: a deployment's file as parsed, or the Topology the
    cluster holds, which `apply` reads as its before (D-057)."""
    definition: dict[str, Any] = yaml.safe_load(topology["spec"]["definition"]["containerlab"])["topology"]
    return definition


def _definition(planned: Planned) -> dict[str, Any]:
    return wrapped(yaml.safe_load(planned.files[TOPOLOGY]))


def _written(pulled: Image, registries: Sequence[Mapping[str, str]]) -> set[str]:
    """Each reference the Topology writes `pulled` as, one per registries given; none under
    registries that hold no prefix for its pull secret."""
    written = set()
    for held in registries:
        try:
            written.add(image(pulled, held))
        except KeyError:
            continue
    return written
