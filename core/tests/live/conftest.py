"""The live tier: booted images on the local containerlab driver (CONTRIBUTING.md, Test tiers).

Every test under tests/live is marked `live`: `make test` deselects them and `make live` runs
them. The driver's module boots and destroys its own labs. The push module's session lab,
`push-live`, is one SR Linux node and one cEOS node, deployed under a temporary directory and
destroyed at the session's end. They share mixed.json's own link (`e1:Ethernet1` to
`s1:ethernet-1/1`): a cEOS node with no Ethernet port refuses `ip routing`, which mixed.json's
`e1` configuration carries (design/verified-facts.md).

Phases 4 and 5's end-to-end scenarios, a twin created through API 1 and the thin CLI, stepped to
every step fixture, its core killed and its step cancelled, are the conformance suite's
(`tests/conformance`), written once for any driver: `make live` runs that suite too, on the local
driver's harness. What stays here is the local driver's own.
"""

from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

LAB = "push-live"
NODES = ("s1", "e1")
TOPOLOGY = """\
name: push-live
topology:
  nodes:
    s1:
      kind: nokia_srlinux
      image: ghcr.io/nokia/srlinux:24.7.1
    e1:
      kind: ceos
      image: ceos:4.32.0.2F
  links:
    - endpoints: ["s1:e1-1", "e1:eth1"]
"""
DEPLOY_TIMEOUT_S = 300
DESTROY_TIMEOUT_S = 60
INSPECT_TIMEOUT_S = 60

_HERE = Path(__file__).resolve().parent


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every test under tests/live `live`, before `-m` selects."""
    for item in items:
        if item.path.is_relative_to(_HERE):
            item.add_marker(pytest.mark.live)


def _clab(*args: str, timeout_s: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["containerlab", *args], capture_output=True, text=True, timeout=timeout_s, check=False)


def _addresses(topology: Path) -> dict[str, str]:
    """Each node's IPv4 management address, as `inspect --format json` gives it after the deploy.

    The answer maps the lab's name to one entry per container: `name` is `clab-<lab>-<node>` and
    `ipv4_address` carries its prefix length.
    """
    inspected = _clab("inspect", "-t", str(topology), "--format", "json", timeout_s=INSPECT_TIMEOUT_S)
    assert inspected.returncode == 0, inspected.stderr[-2000:]
    entries = json.loads(inspected.stdout)[LAB]
    by_container = {entry["name"]: entry["ipv4_address"].split("/")[0] for entry in entries}
    return {node: by_container[f"clab-{LAB}-{node}"] for node in NODES}


@pytest.fixture(scope="session")
def nodes(tmp_path_factory: pytest.TempPathFactory) -> Iterator[dict[str, str]]:
    """The lab's nodes by name, each at its management address; destroyed at the session's end."""
    topology = tmp_path_factory.mktemp(LAB) / f"{LAB}.clab.yml"
    topology.write_text(TOPOLOGY)
    try:
        start = time.monotonic()
        deployed = _clab("deploy", "-t", str(topology), timeout_s=DEPLOY_TIMEOUT_S)
        print(f"\ncontainerlab deploy: rc {deployed.returncode} in {time.monotonic() - start:.1f}s", flush=True)
        assert deployed.returncode == 0, deployed.stderr[-2000:]
        start = time.monotonic()
        addresses = _addresses(topology)
        print(f"containerlab inspect: {time.monotonic() - start:.2f}s", flush=True)
        yield addresses
    finally:
        start = time.monotonic()
        destroyed = _clab("destroy", "-t", str(topology), "--cleanup", timeout_s=DESTROY_TIMEOUT_S)
        print(f"\ncontainerlab destroy: rc {destroyed.returncode} in {time.monotonic() - start:.1f}s", flush=True)
        assert destroyed.returncode == 0, destroyed.stderr[-2000:]
