"""The fixtures agree with each other: each blueprint describes the network the frozen Go
compiler compiled, whose facts are under testdata/compiler/."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
NAMES = ["lossy", "mixed", "three-node", "three-node-probed"]


def _json(path: Path) -> Any:
    return json.loads(path.read_text())


@pytest.mark.parametrize("name", NAMES)
def test_each_blueprint_is_the_network_the_go_compiler_compiled(name: str) -> None:
    doc = _json(ROOT / "testdata" / "blueprint" / f"{name}.json")
    facts = _json(ROOT / "testdata" / "compiler" / f"{name}.facts.json")
    devices = {d["name"]: d for d in doc["network"]["devices"]}
    assert {n["name"] for n in facts["nodes"]} == set(devices)
    for node in facts["nodes"]:
        config = devices[node["name"]]["config"].encode()
        assert node["platform_package"] == devices[node["name"]]["platform"]
        assert node["config"] == {"sha256": hashlib.sha256(config).hexdigest(), "bytes": len(config)}
    hosts = {f"{p['name']}-{e}" for p in facts["probes"] for e in ("a", "b")}
    device_links = [pair for pair in facts["links"] if not any(end.split(":")[0] in hosts for end in pair)]

    def end(e: dict[str, str]) -> str:
        return f"{e['device']}:{e['interface']}"

    blueprint_links = [sorted([end(lk["a"]), end(lk["b"])]) for lk in doc["network"]["links"]]
    assert sorted(device_links) == sorted(blueprint_links)
    assert [p["name"] for p in doc["probes"]] == [p["name"] for p in facts["probes"]]
