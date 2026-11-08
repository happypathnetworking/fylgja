"""The local driver's `changes`: what containerlab does to each node to go from one deployment's
topology to another's (D-049).

It is pure (Constitution V and XIII): no I/O, clock or environment, which a test enforces
through its imports. It compares the two rendered `topology.clab.yml` files through
`compare`, which takes two definitions' `topology` members and a way to find a node's
packages, so that clabernetes compares the definitions its `Topology` objects wrap the same
way (D-057). For a node in both, every reason that applies is named: `kind`, `image` and
`link_mode` when that member differs; `exec` when a `linux` node's start-up lines differ;
`links` when the links the node is on differ; and `hot_add` when the node gains a port, on a
kind whose package has `hot_add_ports: false`, only on a node whose kind and image are
unchanged (containerlab's dry run does not name it: under `live` it adds a veth the operating
system never lists). A port gained is one not in the deployment applied before, which stands
for "not present at boot": a port removed and re-added counts as new, a recreate the runtime
would not need (cEOS under `live` re-cables a port present at boot with no restart). The
action is the strongest the reasons call for: `recreated` for any but `links`; else
`restarted` for `links` under the `restart` link mode; else `recabled` for `links`; else
`kept`. A node in one topology only is `added` or `removed`. `link_apply_mode` and
`hot_add_ports` are read here and nowhere above the seam.

Two answers are not exercised on 0.81.0: `link_mode` answered `recreated`, and a hot-add under
the `restart` link mode, answered `recreated` where the dry run would say `restarted`.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from typing import Any

import yaml

from fylgja_core import platform_package, probe_package
from fylgja_core.containerlab.plan import TOPOLOGY
from fylgja_core.driver import Action, ChangeReason, Changes, NodeChange, Planned
from fylgja_core.platform_package import PlatformPackage
from fylgja_core.probe_package import ProbePackage

Section = platform_package.Containerlab | probe_package.Containerlab

Sections = Callable[[str, Mapping[str, Any]], list[Section]]
"""A node's name and its definition entry to its packages' sections; `ValueError` when no
package runs it."""

Written = Callable[[platform_package.Image], Collection[str]]
"""A package's image to each reference a definition may write it as, for a node the package runs."""


def own_ref(image: platform_package.Image) -> tuple[str]:
    """The reference the local driver's definition writes an image as: its own `ref`."""
    return (image.ref,)


def changes(
    before: Planned,
    after: Planned,
    platforms: Mapping[str, PlatformPackage],
    probe_packages: Mapping[str, ProbePackage],
) -> Changes:
    """What the runtime does to each node to go from `before` to `after`. `ValueError` for
    deployments of two twins, or for a node no given package runs."""
    if before.deployment.twin != after.deployment.twin:
        raise ValueError(f"the deployments are of two twins, {before.deployment.twin} and {after.deployment.twin}")

    def sections(name: str, node: Mapping[str, Any]) -> list[Section]:
        return sections_of(name, node, platforms, probe_packages)

    return compare(_topology(before), _topology(after), sections)


def compare(old: Mapping[str, Any], new: Mapping[str, Any], sections: Sections) -> Changes:
    """What the runtime does to each node to go from the containerlab definition whose
    `topology` member is `old` to the one whose `topology` member is `new`, each node's
    packages found by `sections`. Both containerlab drivers compare their definitions so.
    `ValueError` from `sections` for a node no package runs, whichever side holds it."""
    nodes: dict[str, NodeChange] = {}
    for name in sorted(set(old["nodes"]) | set(new["nodes"])):
        for side in (old, new):  # a node no given package runs is refused, whichever side holds it
            if name in side["nodes"]:
                sections(name, side["nodes"][name])
        if name not in old["nodes"]:
            nodes[name] = NodeChange(node=name, action="added", reasons=())
        elif name not in new["nodes"]:
            nodes[name] = NodeChange(node=name, action="removed", reasons=())
        else:
            nodes[name] = _kept(name, old, new, sections)
    was, now = _links(old), _links(new)
    return Changes(
        nodes=tuple(nodes.values()),
        links_added=tuple(sorted(set(now) - set(was))),
        links_removed=tuple(sorted(set(was) - set(now))),
    )


def endpoints(topology: Mapping[str, Any]) -> dict[str, set[str]]:
    """Each node's ports: the ones `topology.links` names for it. `topology` is the document's
    `topology` member."""
    ports: dict[str, set[str]] = {}
    for a, b in _links(topology):
        for endpoint in (a, b):
            node, _, port = endpoint.partition(":")
            ports.setdefault(node, set()).add(port)
    return ports


def package_of(
    kind: str, image: str, platforms: Mapping[str, PlatformPackage], probe_packages: Mapping[str, ProbePackage],
    written: Written = own_ref,
) -> list[Section]:
    """The containerlab section of each package a node of this `kind` and `image` uses: a
    platform's by kind and image, a probe package's by a linux node's image; none when no given
    package runs it. A package's image is matched as `written` says a definition writes it, by
    its own `ref` unless told otherwise, as the local driver writes it."""
    sections: list[Section] = [
        p.runtime.containerlab for p in platforms.values()
        if p.runtime.containerlab.kind == kind and image in written(p.runtime.containerlab.image)]
    if kind == "linux":
        sections += [q.runtime.containerlab for q in probe_packages.values()
                     if image in written(q.runtime.containerlab.image)]
    return sections


def sections_of(
    name: str, node: Mapping[str, Any], platforms: Mapping[str, PlatformPackage],
    probe_packages: Mapping[str, ProbePackage], written: Written = own_ref,
) -> list[Section]:
    """`package_of` for the definition's node `name`, its image matched as `written` says;
    `ValueError` for a node no given package runs."""
    sections = package_of(node["kind"], node["image"], platforms, probe_packages, written)
    if not sections:
        raise ValueError(f"no package given runs the node {name} ({node['kind']}, {node['image']})")
    return sections


def _topology(planned: Planned) -> dict[str, Any]:
    doc: dict[str, Any] = yaml.safe_load(planned.files[TOPOLOGY])["topology"]
    return doc


def _links(topology: Mapping[str, Any]) -> list[tuple[str, str]]:
    """The links as their two endpoints, the pair sorted, the list sorted."""
    pairs = [tuple(sorted(link["endpoints"])) for link in topology["links"]]
    return sorted((a, b) for a, b in pairs)


def _kept(name: str, old: Mapping[str, Any], new: Mapping[str, Any], sections: Sections) -> NodeChange:
    was, now = old["nodes"][name], new["nodes"][name]
    reasons: set[ChangeReason] = set()
    members: tuple[tuple[str, ChangeReason], ...] = (
        ("kind", "kind"), ("image", "image"), ("link-apply-mode", "link_mode"))
    for member, reason in members:
        if was.get(member) != now.get(member):
            reasons.add(reason)
    if now["kind"] == "linux" and was.get("exec") != now.get("exec"):
        reasons.add("exec")
    if _on(name, old) != _on(name, new):
        reasons.add("links")
    # A port gained is one not in the deployment applied before, which stands for "not present at
    # boot": a port removed and re-added counts as new, a recreate the runtime would not need.
    gained = endpoints(new).get(name, set()) - endpoints(old).get(name, set())
    same_container = was["kind"] == now["kind"] and was["image"] == now["image"]  # hot_add: kind and image unchanged
    platform_sections = [s for s in sections(name, now) if isinstance(s, platform_package.Containerlab)]
    if gained and same_container and any(not s.hot_add_ports for s in platform_sections):
        reasons.add("hot_add")
    action: Action
    if reasons - {"links"}:
        action = "recreated"
    elif "links" in reasons:
        restart = any(s.link_apply_mode == "restart" for s in platform_sections)
        action = "restarted" if restart else "recabled"
    else:
        action = "kept"
    return NodeChange(node=name, action=action, reasons=tuple(sorted(reasons)))


def _on(name: str, topology: Mapping[str, Any]) -> list[tuple[str, str]]:
    """The links `name` is on."""
    return [link for link in _links(topology) if any(e.partition(":")[0] == name for e in link)]
