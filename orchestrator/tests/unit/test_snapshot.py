"""The adapter's snapshot module against the core's (data-model §4, R-07): the four wrapped
fixtures' ids and a fifth carrying every character Go escapes, each file written by Go's
`snapshot.Marshal` and copied into tests/data/snapshot/, read and written back byte for
byte."""

import copy
import json
import os
import random
from pathlib import Path

import pytest

from fylgja_orchestrator.adapters.infrahub import snapshot

DATA = Path(__file__).resolve().parents[1] / "data" / "snapshot"
REPO = Path(__file__).resolve().parents[3]

# internal/snapshot's fixtures_test.go names the four; orchestrator_test.go the fifth,
# which it writes (go test ./internal/snapshot -run TestTheOrchestratorsEscapesFixture -update).
IDS = {
    "three-node": "b9db37f826fc612346974b7f54bc5345513662f21c357a0c51fd2802c9b4de00",
    "lossy": "91f06cd67de31f6c986bc47019e79870b02403a2970d50b6b4497df64c17f10c",
    "mixed": "f3980cc735805c92c13be816c5dadd77c19f321c4c486808511b068f3a9659ff",
    "three-node-probed": "aef03f5d8136b49bb4e0b6b40c9473c5d009af966d07a5fe658860d203c1de3c",
    "escapes": "38e0ced3c6f63a1dc2963f1841080beddfabe99e3731839d14043cf954c67538",
}
FIXTURES = ["three-node", "lossy", "mixed", "three-node-probed"]


def path(name):
    return DATA / f"{name}.json"


@pytest.mark.parametrize("name", FIXTURES)
def test_each_copy_is_the_repositorys_fixture(name):
    # A fixture that moves under testdata/snapshot/ is copied again, and its id here with it.
    assert path(name).read_bytes() == (REPO / "testdata" / "snapshot" / f"{name}.json").read_bytes()


@pytest.mark.parametrize("name", list(IDS))
def test_a_go_written_snapshot_reads_to_its_id_and_writes_back_byte_for_byte(name):
    data = path(name).read_bytes()
    s = snapshot.read(path(name))
    assert s["snapshot_id"] == IDS[name]
    assert json.loads(data)["snapshot_id"] == IDS[name]
    assert snapshot.marshal(s) == data


@pytest.mark.parametrize("name", list(IDS))
def test_a_take_of_the_inner_ctm_is_the_file(name):
    doc = json.loads(path(name).read_bytes())
    ctm, probes = doc["ctm"], doc["probes"]
    before = copy.deepcopy(ctm)
    s = snapshot.take(ctm, probes)
    assert s["snapshot_id"] == IDS[name]
    assert snapshot.marshal(s) == path(name).read_bytes()
    assert ctm == before


def test_the_escapes_are_go_s():
    data = path("escapes").read_bytes()
    hashed = snapshot.hashed_bytes(snapshot.read(path("escapes")))
    for escaped in (b"\\u003c", b"\\u003e", b"\\u0026", b"\\u2028", b"\\u2029", b"\\u0001", b"\\b", b"\\f", b"\\u001f"):
        assert escaped in data
        assert escaped in hashed
    # DEL and the characters beyond ASCII are written raw, as Go writes them.
    for raw in ("\x7f", chr(0xE9), chr(0x1F600)):
        assert raw.encode() in hashed
    for raw in (b"<", b">", b"&", chr(0x2028).encode(), chr(0x2029).encode()):
        assert raw not in hashed


def test_a_lone_surrogate_is_written_as_go_decodes_it():
    s = snapshot.read(path("escapes"))
    replaced = copy.deepcopy(s)
    s["ctm"]["envelope"]["fidelity"][0]["reason"] = "x" + chr(0xD800) + "y"
    replaced["ctm"]["envelope"]["fidelity"][0]["reason"] = "x" + chr(0xFFFD) + "y"
    assert snapshot.hashed_bytes(s) == snapshot.hashed_bytes(replaced)


@pytest.mark.parametrize("name", list(IDS))
def test_the_order_intent_arrived_in_moves_no_id(name):
    doc = json.loads(path(name).read_bytes())
    ctm = doc["ctm"]
    rng = random.Random(name)
    for items in (ctm["devices"], ctm["links"], ctm["envelope"]["fidelity"]):
        rng.shuffle(items)
    for device in ctm["devices"]:
        rng.shuffle(device["interfaces"])
    for link in ctm["links"]:
        link["endpoints"].reverse()
    assert snapshot.snapshot_id({"ctm": ctm, "probes": doc["probes"]}) == IDS[name]


def test_the_defaults_move_no_id():
    doc = json.loads(path("three-node").read_bytes())
    ctm = doc["ctm"]
    for device in ctm["devices"]:
        device["provenance"] = "intent"
        for interface in device["interfaces"]:
            interface.pop("enabled", None)
            interface["provenance"] = ""
    del ctm["ctm_version"]
    assert snapshot.snapshot_id({"ctm": ctm, "probes": []}) == IDS["three-node"]


def test_observed_at_is_not_hashed_and_at_is():
    s = snapshot.read(path("three-node"))
    s["observed_at"] = s["ctm"]["envelope"]["observed_at"] = "2030-01-01T00:00:00.000000Z"
    assert snapshot.snapshot_id(s) == IDS["three-node"]
    s["ctm"]["envelope"]["at"] = "2030-01-01T00:00:00Z"
    assert snapshot.snapshot_id(s) != IDS["three-node"]


def test_a_version_1_reads_as_a_2_under_the_same_id():
    doc = json.loads(path("three-node").read_bytes())
    doc["snapshot_version"] = "1"
    s = snapshot.unmarshal(json.dumps(doc).encode())
    assert s["snapshot_version"] == "2"
    assert s["snapshot_id"] == IDS["three-node"]
    assert snapshot.marshal(s) == path("three-node").read_bytes()


def test_the_id_and_observed_at_are_filled_when_left_out():
    doc = json.loads(path("mixed").read_bytes())
    del doc["snapshot_id"], doc["observed_at"]
    s = snapshot.unmarshal(json.dumps(doc).encode())
    assert snapshot.marshal(s) == path("mixed").read_bytes()


@pytest.mark.parametrize(
    "change, rule, field",
    [
        (lambda d: d.update(snapshot_version="3"), "snapshot.version.unsupported", ""),
        (lambda d: d.pop("snapshot_version"), "snapshot.version.unsupported", ""),
        (lambda d: d.update(snapshot_id="0" * 64), "snapshot.id.mismatch", "snapshot_id"),
        (lambda d: d.update(snapshot_id="NOT-AN-ID"), "snapshot.invalid", "snapshot_id"),
        (lambda d: d.update(extra=1), "snapshot.invalid", "extra"),
        (lambda d: d.update(ctm=None), "snapshot.invalid", "ctm"),
        (lambda d: d.update(probes=None), "snapshot.invalid", "probes"),
        (lambda d: d.update(observed_at="2026-09-08T12:00:00.000001Z"), "snapshot.invalid", "observed_at"),
        (lambda d: d.update(snapshot_version="1"), "snapshot.invalid", "probes"),
    ],
)
def test_a_document_that_is_not_a_snapshot_is_refused(change, rule, field):
    doc = json.loads(path("three-node-probed").read_bytes())
    change(doc)
    with pytest.raises(snapshot.SnapshotError) as refused:
        snapshot.unmarshal(json.dumps(doc).encode())
    assert (refused.value.rule, refused.value.field) == (rule, field)


def test_marshal_refuses_what_it_could_not_read_back():
    s = snapshot.read(path("three-node"))
    for change, rule in (
        (lambda d: d.update(snapshot_id="0" * 64), "snapshot.id.mismatch"),
        (lambda d: d.update(observed_at="2026-09-08T12:00:00Z"), "snapshot.invalid"),
        (lambda d: d.update(snapshot_version="1"), "snapshot.invalid"),
    ):
        bad = copy.deepcopy(s)
        change(bad)
        with pytest.raises(snapshot.SnapshotError) as refused:
            snapshot.marshal(bad)
        assert refused.value.rule == rule


def test_write_files_the_stored_form_whole(tmp_path):
    s = snapshot.read(path("three-node-probed"))
    out = tmp_path / f"{s['snapshot_id']}.json"
    snapshot.write(out, s)
    assert out.read_bytes() == path("three-node-probed").read_bytes()
    assert out.stat().st_mode & 0o777 == 0o644
    assert os.listdir(tmp_path) == [out.name]


def test_write_leaves_nothing_when_refused(tmp_path):
    s = snapshot.read(path("three-node"))
    s["snapshot_id"] = "0" * 64
    with pytest.raises(snapshot.SnapshotError):
        snapshot.write(tmp_path / "x.json", s)
    assert os.listdir(tmp_path) == []
