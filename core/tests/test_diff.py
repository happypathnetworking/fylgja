"""The bundle diff (API 1 BundleDiff): a pure function of two manifests. Each pair is a base
fixture and one step fixture (testdata/blueprint/steps/README.md)."""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from fylgja_core import blueprint, bundle, compiler, diff, documents, platform_package, probe_package, schemas

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "core" / "src" / "fylgja_core"
FIXTURES = ROOT / "testdata" / "blueprint"
PLATFORMS = {
    p.id: p
    for p in map(platform_package.load, [ROOT / "psp" / "nokia_srlinux.yaml", ROOT / "psp" / "arista_eos.yaml",
                                         ROOT / "testdata" / "packages" / "chassisos.yaml"])
}
PROBES = {p.format: p for p in [probe_package.load(ROOT / "probes" / "ping.yaml")]}


def compiled(name: str) -> compiler.Compiled:
    return compiler.compile(blueprint.load(FIXTURES / f"{name}.json"), PLATFORMS, PROBES)


def link(a: str, ai: str, b: str, bi: str) -> blueprint.Link:
    return blueprint.Link(a=blueprint.Endpoint(device=a, interface=ai), b=blueprint.Endpoint(device=b, interface=bi))


def changed(*pairs: tuple[str, tuple[diff.Reason, ...]]) -> tuple[diff.ChangedNode, ...]:
    return tuple(diff.ChangedNode(node=n, reasons=r) for n, r in pairs)


MAPPING: tuple[diff.Reason, ...] = ("mapping",)
N1L = link("n1", "ethernet-1/1", "n2", "ethernet-1/1")
N1N3 = link("n1", "ethernet-1/2", "n3", "ethernet-1/2")
N2N3 = link("n2", "ethernet-1/2", "n3", "ethernet-1/1")

# (base, step, nodes, links, probes)
PAIRS: list[tuple[str, str, diff.Nodes, diff.Links, diff.Probes]] = [
    ("three-node", "steps/three-node-unlinked",
     diff.Nodes(added=(), removed=(), changed=changed(("n2", MAPPING), ("n3", MAPPING))),
     diff.Links(added=(), removed=(N2N3,)), diff.Probes(added=(), removed=())),
    ("three-node", "steps/two-node",
     diff.Nodes(added=(), removed=("n3",), changed=changed(("n1", MAPPING), ("n2", MAPPING))),
     diff.Links(added=(), removed=(N1N3, N2N3)), diff.Probes(added=(), removed=())),
    ("three-node", "steps/three-node-n3-eos",
     diff.Nodes(added=(), removed=(), changed=changed(("n3", ("platform", "mapping", "config")))),
     diff.Links(added=(link("n1", "ethernet-1/2", "n3", "Ethernet2"), link("n2", "ethernet-1/2", "n3", "Ethernet1")),
                removed=(N1N3, N2N3)),
     diff.Probes(added=(), removed=())),
    ("three-node", "steps/three-node-n1-disabled",
     diff.Nodes(added=(), removed=(), changed=changed(("n1", MAPPING))),
     diff.Links(added=(), removed=()), diff.Probes(added=(), removed=())),
    ("mixed", "steps/mixed-e2-port",
     diff.Nodes(added=(), removed=(), changed=changed(("e1", MAPPING), ("e2", MAPPING))),
     diff.Links(added=(link("e1", "Ethernet10", "e2", "Ethernet10"),), removed=()),
     diff.Probes(added=(), removed=())),
    ("three-node-probed", "steps/three-node-probed-moved",
     diff.Nodes(added=(), removed=(), changed=changed(("n1", MAPPING), ("n2", MAPPING))),
     diff.Links(added=(), removed=()), diff.Probes(added=("n1-loop",), removed=("n1-loop",))),
    ("three-node", "three-node-probed",
     diff.Nodes(added=(), removed=(), changed=changed(("n1", MAPPING))),
     diff.Links(added=(), removed=()), diff.Probes(added=("n1-loop",), removed=())),
    ("three-node", "three-node-unmanaged",
     diff.Nodes(added=(), removed=(), changed=changed(("n2", ("config",)))),
     diff.Links(added=(), removed=()), diff.Probes(added=(), removed=())),
]
IDS = [f"{a}->{b}" for a, b, *_ in PAIRS]


def reversed_pair(
    nodes: diff.Nodes, links: diff.Links, probes: diff.Probes
) -> tuple[diff.Nodes, diff.Links, diff.Probes]:
    """What stepping the pair the other way says: added and removed swap, the changed nodes stay."""
    return (diff.Nodes(added=nodes.removed, removed=nodes.added, changed=nodes.changed),
            diff.Links(added=links.removed, removed=links.added),
            diff.Probes(added=probes.removed, removed=probes.added))


REVERSED = [(b, a, *reversed_pair(n, lk, pr)) for a, b, n, lk, pr in PAIRS]
REVERSED_IDS = [f"{a}->{b}" for a, b, *_ in REVERSED]


@pytest.mark.parametrize(("base", "step", "nodes", "links", "probes"), [*PAIRS, *REVERSED], ids=[*IDS, *REVERSED_IDS])
def test_each_pair_diffs_to_exactly_the_change(
    base: str, step: str, nodes: diff.Nodes, links: diff.Links, probes: diff.Probes
) -> None:
    a, b = compiled(base), compiled(step)
    d = diff.diff("a" * 64, a.manifest, "b" * 64, b.manifest)
    assert (d.from_, d.to) == ("a" * 64, "b" * 64)
    assert (d.nodes, d.links, d.probes) == (nodes, links, probes)
    assert not d.unchanged


@pytest.mark.parametrize(("base", "step"), [(a, b) for a, b, *_ in [*PAIRS, *REVERSED]], ids=[*IDS, *REVERSED_IDS])
def test_the_diff_is_a_valid_api_document(base: str, step: str) -> None:
    d = diff.diff("a" * 64, compiled(base).manifest, "b" * 64, compiled(step).manifest)
    doc = documents.encode(d)
    assert doc["from"] == "a" * 64
    assert list(schemas.api_validator("BundleDiff").iter_errors(doc)) == []


@pytest.mark.parametrize("name", ["three-node", "mixed", "three-node-probed"])
def test_a_manifest_against_itself_is_unchanged(name: str) -> None:
    m = compiled(name).manifest
    d = diff.diff("a" * 64, m, "a" * 64, m)
    assert d.unchanged
    assert d.nodes == diff.Nodes(added=(), removed=(), changed=())
    assert d.links == diff.Links(added=(), removed=())
    assert d.probes == diff.Probes(added=(), removed=())
    assert list(schemas.api_validator("BundleDiff").iter_errors(documents.encode(d))) == []


def test_every_step_fixture_has_a_pair() -> None:
    paired = {step for _, step, *_ in PAIRS}
    on_disk = {f"steps/{p.stem}" for p in (FIXTURES / "steps").glob("*.json")}
    assert on_disk <= paired, f"step fixtures with no row in PAIRS: {sorted(on_disk - paired)}"


def test_a_probe_moved_is_in_both_lists() -> None:
    a, b = compiled("three-node-probed"), compiled("steps/three-node-probed-moved")
    d = diff.diff("a" * 64, a.manifest, "b" * 64, b.manifest)
    assert d.probes.added == d.probes.removed == ("n1-loop",)


def test_the_config_reason_is_a_config_on_one_side_alone_or_two_that_differ() -> None:
    m = compiled("three-node").manifest
    n1 = m.nodes[0]
    assert n1.config is not None, "three-node's n1 carries a configuration"
    no_config = dataclasses.replace(n1, config=None)
    bare = dataclasses.replace(m, nodes=(no_config, *m.nodes[1:]))
    other = bundle.File(file=n1.config.file, sha256="0" * 64)
    edited = dataclasses.replace(m, nodes=(dataclasses.replace(n1, config=other), *m.nodes[1:]))
    for before, after in [(m, bare), (bare, m)]:
        d = diff.diff("a" * 64, before, "b" * 64, after)
        assert d.nodes.changed == changed(("n1", ("config",)))
    assert diff.diff("a" * 64, m, "b" * 64, edited).nodes.changed == changed(("n1", ("config",)))
    assert diff.diff("a" * 64, bare, "b" * 64, bare).unchanged


PURE_IMPORTS = {"__future__", "dataclasses", "typing", "fylgja_core.blueprint", "fylgja_core.bundle"}


def test_the_diff_is_pure() -> None:
    """Constitution V: no I/O, clock or environment. The imports say so."""
    imported = set()
    for node in ast.walk(ast.parse((SRC / "diff.py").read_text())):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.module is not None
            if node.module == "fylgja_core":
                imported |= {f"fylgja_core.{alias.name}" for alias in node.names}
            else:
                imported.add(node.module)
    assert imported <= PURE_IMPORTS, imported - PURE_IMPORTS
