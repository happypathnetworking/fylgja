"""The local store (Constitution IX, D-024, D-041): documents by id, twin records by
compare-and-set, runs and their events, in a directory."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from fylgja_core import blueprint, deployment, documents, store
from fylgja_core.local_store import LocalStore

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _close_stores(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Close every store a test opens, so no file or lock outlives it."""
    opened: list[LocalStore] = []
    real = LocalStore.open.__func__  # type: ignore[attr-defined]

    def tracking(cls: type[LocalStore], root: Path) -> LocalStore:
        s: LocalStore = real(cls, root)
        opened.append(s)
        return s

    monkeypatch.setattr(LocalStore, "open", classmethod(tracking))
    yield
    for s in opened:
        s.close()


def test_open_creates_the_d041_layout(tmp_path: Path) -> None:
    s = LocalStore.open(tmp_path / "store")
    assert {p.name for p in (tmp_path / "store").iterdir()} >= {"blueprints", "bundles", "deployments", "twins", "runs"}
    s.close()


def test_a_blueprint_is_filed_by_its_id_once_and_read_back_whole(tmp_path: Path) -> None:
    s = LocalStore.open(tmp_path)
    doc = json.loads((ROOT / "testdata/blueprint/three-node.json").read_text())
    bid, created = s.put_blueprint(doc)
    assert created and bid == blueprint.blueprint_id(doc)
    assert (tmp_path / "blueprints" / f"{bid}.json").exists()
    assert s.put_blueprint(doc) == (bid, False)
    assert s.get_blueprint(bid) == doc  # the source envelope included
    with pytest.raises(store.NotFound):
        s.get_blueprint("f" * 64)
    assert not list(tmp_path.glob("blueprints/.tmp*"))  # no temp file left behind


def test_a_filed_document_is_never_overwritten(tmp_path: Path) -> None:
    s = LocalStore.open(tmp_path)
    doc = json.loads((ROOT / "testdata/blueprint/three-node.json").read_text())
    bid, _ = s.put_blueprint(doc)
    path = tmp_path / "blueprints" / f"{bid}.json"
    path.write_text("sentinel")
    assert s.put_blueprint(doc) == (bid, False) and path.read_text() == "sentinel"


def test_a_bundle_is_its_files_under_its_id(tmp_path: Path) -> None:
    s = LocalStore.open(tmp_path)
    files = {"manifest.json": b"{}", "configs/n1.cfg": b"set / system\n"}
    assert s.put_bundle("a" * 64, files) is True
    assert s.put_bundle("a" * 64, {"manifest.json": b"other"}) is False
    assert s.get_bundle("a" * 64) == files
    assert (tmp_path / "bundles" / ("a" * 64) / "configs" / "n1.cfg").read_bytes() == b"set / system\n"
    assert not list((tmp_path / "bundles").glob(".tmp*"))
    with pytest.raises(store.NotFound):
        s.get_bundle("b" * 64)


def test_a_deployment_is_its_document_and_its_rendered_files(tmp_path: Path) -> None:
    s = LocalStore.open(tmp_path)
    d = deployment.Deployment(
        id="c" * 64,
        driver="containerlab",
        twin="t",
        allocation={"lab": "t"},
        bundle_id="a" * 64,
        files=(deployment.File(path="topology.clab.yml", sha256="d" * 64),),
        demand=deployment.Demand(nodes=1, cpu=0.5, memory_mb=2048),
        fidelity=deployment.Fidelity(
            forwarding="software",
            approximations=(),
            omitted=(),
            synthesized=(),
            lossy=deployment.Lossy(mappings=0, shared_ports=0),
        ),
    )
    assert s.put_deployment(d, {"topology.clab.yml": b"name: t\n"}) is True
    got, files = s.get_deployment("c" * 64)
    assert got == d and files == {"topology.clab.yml": b"name: t\n"}
    assert json.loads((tmp_path / "deployments" / ("c" * 64) / "deployment.json").read_text()) == documents.encode(d)
    with pytest.raises(store.NotFound):
        s.get_deployment("e" * 64)
