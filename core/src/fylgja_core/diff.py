"""The bundle diff (API 1 BundleDiff): what two manifests say differs, a pure function with no
runtime in it. A step's runtime-independent facts are here: nodes added, removed and changed
(by platform, mapping or configuration), and links and probes added and removed. The step's
plan and the report read it; `documents.encode(BundleDiff)` is the API document."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from fylgja_core import blueprint, bundle

# Why a node in both bundles changed, in the order a diff lists them.
Reason = Literal["platform", "mapping", "config"]


@dataclass(frozen=True, kw_only=True)
class ChangedNode:
    """A node in both bundles that differs, and why."""

    node: str
    reasons: tuple[Reason, ...]


@dataclass(frozen=True, kw_only=True)
class Nodes:
    """Node changes: those only in `to`, those only in `from`, and those in both that differ."""

    added: tuple[str, ...]
    removed: tuple[str, ...]
    changed: tuple[ChangedNode, ...]


@dataclass(frozen=True, kw_only=True)
class Links:
    """Link changes, each list sorted as blueprint 1 sorts links."""

    added: tuple[blueprint.Link, ...]
    removed: tuple[blueprint.Link, ...]


@dataclass(frozen=True, kw_only=True)
class Probes:
    """A probe whose definition changed is in both lists."""

    added: tuple[str, ...]
    removed: tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class BundleDiff:
    """What stepping from bundle `from_` to bundle `to` changes; `unchanged` is every list empty."""

    from_: str = field(metadata={"key": "from"})
    to: str
    unchanged: bool
    nodes: Nodes
    links: Links
    probes: Probes


def _link_key(link: blueprint.Link) -> tuple[str, str, str, str]:
    return (link.a.device, link.a.interface, link.b.device, link.b.interface)


def _config_differs(before: bundle.File | None, after: bundle.File | None) -> bool:
    if before is None or after is None:
        return (before is None) != (after is None)
    return before.sha256 != after.sha256


def _reasons(
    name: str, before: bundle.Manifest, after: bundle.Manifest, a: bundle.Node, b: bundle.Node
) -> tuple[Reason, ...]:
    reasons: list[Reason] = []
    if a.platform != b.platform:
        reasons.append("platform")
    if tuple(r for r in before.mapping if r.device == name) != tuple(r for r in after.mapping if r.device == name):
        reasons.append("mapping")
    if _config_differs(a.config, b.config):
        reasons.append("config")
    return tuple(reasons)


def diff(from_id: str, before: bundle.Manifest, to_id: str, after: bundle.Manifest) -> BundleDiff:
    """What changes from `before` to `after`; every list is sorted."""
    old = {n.name: n for n in before.nodes}
    new = {n.name: n for n in after.nodes}
    changed = tuple(
        ChangedNode(node=name, reasons=reasons)
        for name in sorted(old.keys() & new.keys())
        if (reasons := _reasons(name, before, after, old[name], new[name]))
    )
    nodes = Nodes(added=tuple(sorted(new.keys() - old.keys())), removed=tuple(sorted(old.keys() - new.keys())),
                  changed=changed)

    old_links = {_link_key(lk): lk for lk in before.links}
    new_links = {_link_key(lk): lk for lk in after.links}
    links = Links(added=tuple(new_links[k] for k in sorted(new_links.keys() - old_links.keys())),
                  removed=tuple(old_links[k] for k in sorted(old_links.keys() - new_links.keys())))

    old_probes = {p.name: p for p in before.probes}
    new_probes = {p.name: p for p in after.probes}
    moved = {n for n in old_probes.keys() & new_probes.keys() if old_probes[n] != new_probes[n]}
    probes = Probes(added=tuple(sorted((new_probes.keys() - old_probes.keys()) | moved)),
                    removed=tuple(sorted((old_probes.keys() - new_probes.keys()) | moved)))

    unchanged = not (nodes.added or nodes.removed or nodes.changed or links.added or links.removed
                     or probes.added or probes.removed)
    return BundleDiff(from_=from_id, to=to_id, unchanged=unchanged, nodes=nodes, links=links, probes=probes)
