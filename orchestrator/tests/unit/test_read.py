"""The read against `internal/intent`'s project_test.go: the three-node fixture, seeded in
the library's kinds, reads to `testdata/ctm/three-node.json` but for the envelope's instant
and hash, and asks for nothing outside its scope; each port projected, each device without
a package refused in one pass, a scope selecting nothing refused, every page read. The
fake (dcim.py) answers in Infrahub's wire shapes; the SDK runs whole."""

import copy
import functools
import json

import pytest

from fylgja_orchestrator.adapters.infrahub import packages, read, snapshot
from fylgja_orchestrator.adapters.infrahub.client import Client, Config
from fylgja_orchestrator.documents.findings import REJECTION, Finding

from .conftest import ADDRESS, TOKEN
from .dcim import REPO, Dcim

OBSERVED = "2026-09-18T00:00:00.000000Z"


def fixture_ctm(name="three-node.json"):
    return snapshot.normalize(json.loads((REPO / "testdata" / "ctm" / name).read_text()))


@functools.cache
def _registry(override: str):
    return packages.load(override_dir=override)


def registry(override=None):
    """The shipped packages, and an override directory's; loaded once per directory, since
    a registry is never changed."""
    return _registry(str(override) if override else "")


def read_fake(f, at="", scope="tag:fylgja", reg=None):
    client = Client(Config(address=ADDRESS, token=TOKEN, branch=f.branch, at=at), requester=f.infrahub)
    return read.read(client, scope, reg or registry(), OBSERVED)


@pytest.fixture
def fake(infrahub):
    return Dcim.from_ctm(infrahub)


def test_read_is_the_fixture(fake):
    c, found = read_fake(fake)
    assert list(found) == [] and c is not None
    want = fixture_ctm()
    assert c["devices"] == want["devices"]
    assert c["links"] == want["links"]
    e, w = c["envelope"], want["envelope"]
    assert (e["branch"], e["scope"], e["mapping"], e["fidelity"]) == (
        w["branch"], "tag:fylgja", w["mapping"], w["fidelity"])
    assert e["mapping"] == {"reader": "infrahub-dcim", "model": "opsmill/schema-library", "version": "26336e9"}
    assert len(e["fidelity"]) == 3
    devices = fake.infrahub.served("Devices")
    assert len(devices) == 1 and devices[0]["variables"]["tag"] == "fylgja"
    assert "DcimDevice(tags__name__value: $tag, limit: $limit, offset: $offset) {" in devices[0]["query_text"]
    ports = fake.infrahub.served("Ports")
    assert len(ports) == 1 and ports[0]["variables"]["devices"] == ["id-n1", "id-n2", "id-n3"]
    assert "InterfacePhysical(device__ids: $devices, limit: $limit, offset: $offset) {" in ports[0]["query_text"]


def test_read_snapshot_is_the_fixtures_with_the_reads_envelope(fake):
    """The read taken: the fixture's CTM wrapped with the read's envelope, its id the
    hash of the body without observed_at."""
    client = Client(Config(address=ADDRESS, token=TOKEN, branch=fake.branch), requester=fake.infrahub)
    taken, found = read.read_snapshot(client, "tag:fylgja", registry(), [], OBSERVED)
    assert list(found) == []
    want = fixture_ctm()
    want["envelope"].pop("at")
    want["envelope"]["observed_at"] = OBSERVED
    want["envelope"]["schema_hash"] = fake.infrahub.schema["main"]
    assert taken == snapshot.take(want, [])
    assert snapshot.marshal(taken) == snapshot.marshal(snapshot.take(copy.deepcopy(want)))


def test_read_asks_for_nothing_outside_its_scope(fake):
    fake.add_device("cs1", "Opengear", "Console OS", [], "port1")
    fake.add_device("o1", "Nokia", "SR Linux", ["other"], "ethernet-1/1")
    # n1's virtual interfaces are on no root the read asks: the fake has no way to serve them.

    c, found = read_fake(fake)

    assert not found.rejected and c is not None
    names = [d["name"] for d in c["devices"]]
    assert "cs1" not in names and "o1" not in names
    n1 = next(d for d in c["devices"] if d["name"] == "n1")
    assert len(n1["interfaces"]) == 5
    ports = fake.infrahub.served("Ports")
    assert len(ports) == 1
    assert "id-cs1" not in ports[0]["variables"]["devices"] and "id-o1" not in ports[0]["variables"]["devices"]
    for r in fake.infrahub.served("Devices") + ports:
        for never in ("InterfaceVirtual", "interfaces", "address", "description", "location", "serial", "site"):
            assert never not in r["query_text"], f"operation {r['operation']} asks for {never!r}"


def device_fields(query: str) -> list[str]:
    """The names a Devices query selects on the DcimDevice node itself: the top level of
    DcimDevice.edges.node's selection, each fragment spread's and inline fragment's own top
    level included, every argument list and deeper selection skipped."""
    import re

    tokens = re.findall(r"\.\.\.|[A-Za-z_][A-Za-z0-9_]*|[{}()]", query)

    def close_of(i):
        depth = 0
        for j in range(i, len(tokens)):
            if tokens[j] in "{(":
                depth += 1
            elif tokens[j] in "})":
                depth -= 1
                if depth == 0:
                    return j
        raise AssertionError(f"unbalanced query:\n{query}")

    def set_of(i):
        j = i + 1
        if tokens[j] == "(":
            j = close_of(j) + 1
        assert tokens[j] == "{", f"{tokens[i]} selects nothing"
        return j

    def fragment(name):
        for k in range(len(tokens) - 4):
            if tokens[k] == "fragment" and tokens[k + 1] == name:
                return k + 4
        raise AssertionError(f"no fragment {name}")

    def top(open_):
        out = []
        end = close_of(open_)
        j = open_ + 1
        while j < end:
            tok = tokens[j]
            if tok in ("(", "{"):
                j = close_of(j)
            elif tok == "..." and tokens[j + 1] == "on":
                out += top(j + 3)
                j = close_of(j + 3)
            elif tok == "...":
                out += top(fragment(tokens[j + 1]))
                j += 1
            else:
                out.append(tok)
            j += 1
        return out

    def child(open_, name):
        depth = 0
        for j in range(open_ + 1, close_of(open_)):
            if tokens[j] in "{(":
                depth += 1
            elif tokens[j] in "})":
                depth -= 1
            elif depth == 0 and tokens[j] == name:
                return set_of(j)
        raise AssertionError(f"no {name}")

    return top(child(child(set_of(tokens.index("DcimDevice")), "edges"), "node"))


def test_devices_reads_not_the_devices_role_status_or_type(fake):
    c, found = read_fake(fake)
    assert not found.rejected
    devices = fake.infrahub.served("Devices")
    assert devices
    for r in devices:
        fields = device_fields(r["query_text"])
        for want in ("id", "name", "platform", "artifacts"):
            assert want in fields
        for never in ("role", "status", "device_type"):
            assert never not in fields


def test_read_of_two_management_ports_compiles_one(fake):
    """The read's half: both ports read mgmt_only. That the compile keeps the first by name
    and omits the second (omit.mgmt.extra) is the core's, which compiles the snapshot."""
    fake.device("n1").ports.append(read_port("n1:mgmt1", "mgmt1", role="management"))

    c, found = read_fake(fake)

    assert not found.rejected and c is not None
    n1 = next(d for d in c["devices"] if d["name"] == "n1")
    for name in ("mgmt0", "mgmt1"):
        assert next(i for i in n1["interfaces"] if i["name"] == name)["mgmt_only"]


def read_port(port_id, name, role="", status=""):
    from .dcim import Port

    return Port(id=port_id, name=name, role=role, status=status)


def device_of(c, name):
    return next((d for d in c["devices"] if d["name"] == name), None)


def interface_of(c, device, name):
    return next(i for i in device_of(c, device)["interfaces"] if i["name"] == name)


def test_read_projects_each_port(fake):
    fake.port("n2:ethernet-1/2")[1].status = "disabled"
    fake.port("n3:ethernet-1/1")[1].status = "maintenance"
    fake.device("n2").status = "maintenance"
    fake.add_device("n4", "Nokia", "SR Linux", ["fylgja"])
    fake.add_ready_artifact("n4")

    c, found = read_fake(fake)

    assert not found.rejected and c is not None
    assert not interface_of(c, "n2", "ethernet-1/2")["enabled"]
    assert interface_of(c, "n3", "ethernet-1/1")["enabled"] and interface_of(c, "n1", "ethernet-1/1")["enabled"]
    assert interface_of(c, "n1", "mgmt0")["mgmt_only"] and not interface_of(c, "n1", "ethernet-1/1")["mgmt_only"]
    assert device_of(c, "n2") is not None
    n4 = device_of(c, "n4")
    assert n4["interfaces"] == [] and n4["platform"]["package"] == "nokia_srlinux" and n4.get("artifact")


def test_read_refuses_every_device_without_a_package(fake):
    n1, n2, n3 = fake.device("n1"), fake.device("n2"), fake.device("n3")
    n1.manufacturer, n1.platform = "nokia", "SR-Linux"
    n2.manufacturer, n2.platform = "", ""
    n3.manufacturer, n3.platform = "", "Orphan OS"
    fake.add_device("n4", "Nokia", "SR Linux", ["fylgja"])
    fake.add_device("n5", "", "SR Linux", ["fylgja"]).empty_manufacturer = True

    c, found = read_fake(fake)

    assert c is None
    matches = "the packages match: arista_eos [Arista / EOS], nokia_srlinux [Nokia / SR Linux]"
    assert list(found) == [
        Finding(REJECTION, "platform.unmatched", "n1",
                f'device n1: manufacturer "nokia", platform "SR-Linux"; {matches}'),
        Finding(REJECTION, "platform.missing", "n2",
                "device n2 carries no platform; its support package is the one whose matches name its platform "
                "and manufacturer"),
        Finding(REJECTION, "platform.missing", "n3",
                'device n3 carries platform "Orphan OS" with no manufacturer; its support package is the one whose '
                "matches name both"),
        Finding(REJECTION, "platform.unmatched", "n5", f'device n5: manufacturer "", platform "SR Linux"; {matches}'),
        Finding(REJECTION, "artifact.missing", "n4",
                "device n4 has no artifact named device-config on branch fylgja-fixture"),
    ]
    for d in ("n1", "n2", "n3", "n5"):
        assert fake.infrahub.count(f"/api/storage/object/storage-{d}") == 0


def test_scope_selecting_nothing_is_refused(fake):
    c, found = read_fake(fake, scope="tag:nothing")

    assert c is None
    assert list(found) == [
        Finding(REJECTION, "scope.empty", "tag:nothing", "scope tag:nothing selects no device on branch fylgja-fixture")
    ]
    devices = fake.infrahub.served("Devices")
    assert len(devices) == 1 and devices[0]["variables"]["tag"] == "nothing"
    assert fake.infrahub.served("Ports") == []


def test_scope_selecting_nothing_at_an_instant_names_it(fake):
    at = "2026-10-20T00:00:00Z"

    c, found = read_fake(fake, at=at, scope="tag:nothing")

    assert c is None
    assert list(found) == [
        Finding(REJECTION, "scope.empty", "tag:nothing",
                f"scope tag:nothing selects no device on branch fylgja-fixture at {at}")
    ]
    devices = fake.infrahub.served("Devices")
    assert len(devices) == 1 and devices[0]["query"].get("at") == [at]
    assert fake.infrahub.served("Ports") == []


def test_read_pages_devices_and_ports(fake):
    fake.devices, fake.cables, fake.artifacts = [], {}, {}
    fake.infrahub.objects.clear()
    for i in range(150):
        name = f"d{i:03d}"
        fake.add_device(name, "Nokia", "SR Linux", ["fylgja"], "ethernet-1/1", "ethernet-1/2")
        fake.add_ready_artifact(name)

    c, found = read_fake(fake)

    assert not found.rejected and c is not None and len(c["devices"]) == 150
    assert all(len(d["interfaces"]) == 2 for d in c["devices"])
    ports = fake.infrahub.served("Ports")
    assert len(ports) == 3
    assert len(ports[0]["variables"]["devices"]) == 100 and ports[1]["variables"]["offset"] == 100
    assert len(ports[2]["variables"]["devices"]) == 50
    assert len(fake.infrahub.served("Devices")) == 2


# Beyond project_test.go: the scope's form, `at`'s precision, the lossy and mixed fixtures,
# and the summary.


def test_a_scope_not_a_tag_is_no_read(fake):
    with pytest.raises(read.ReadError, match=r'the read names scope "fylgja", which is not tag:<name>'):
        read_fake(fake, scope="fylgja")
    assert fake.infrahub.requests == []


def test_an_at_finer_than_infrahub_honours_is_refused_before_any_query(fake):
    at = "2026-09-08T12:00:00.1234567Z"
    client = Client(Config(address=ADDRESS, token=TOKEN, branch=fake.branch, at=at), requester=fake.infrahub)

    taken, found = read.read_snapshot(client, "tag:fylgja", registry(), [], OBSERVED)

    assert taken is None
    assert list(found) == [
        Finding(REJECTION, "intent.at.precision", at,
                f"at {at} carries 7 fractional digits; Infrahub honours at most 6 (microseconds). "
                "Re-run with a coarser --at.")
    ]
    assert fake.infrahub.requests == []


def test_a_pinned_read_carries_at_verbatim_in_the_envelope(fake):
    at = "2026-09-08T12:00:00.123456+00:00"
    c, found = read_fake(fake, at=at)
    assert not found.rejected
    assert c["envelope"]["at"] == at
    assert all(r["query"].get("at") == [at] for r in fake.infrahub.requests if r["path"] != "/api/schema")


@pytest.mark.parametrize(
    "name,override",
    [
        ("three-node.json", None),
        ("lossy.json", REPO / "testdata" / "psp" / "lossy"),
        ("mixed.json", None),
    ],
)
def test_each_fixture_reads_to_its_ctm(infrahub, name, override):
    """Each fixture CTM, seeded in the library's kinds, reads back to itself but for the
    envelope's instant and hash: SR Linux alone, a lossy package's devices beside SR
    Linux's, and EOS beside SR Linux."""
    f = Dcim.from_ctm(infrahub, REPO / "testdata" / "ctm" / name)
    c, found = read_fake(f, reg=registry(override))
    assert not found.rejected, list(found)
    want = fixture_ctm(name)
    assert c["devices"] == want["devices"]
    assert c["links"] == want["links"]
    assert c["envelope"]["fidelity"] == want["envelope"]["fidelity"]
    assert {d["platform"]["package"] for d in c["devices"]} == {d["platform"]["package"] for d in want["devices"]}


def test_the_summary_counts_what_was_read(fake):
    fake.cable("cable-x", "loose", "n1:ethernet-1/10", "Other#elsewhere")
    c, found = read_fake(fake)
    assert not found.rejected
    counts = read.summarize(c)
    assert counts == read.Counts(devices=3, interfaces=15, links=3, artifacts=3, cables_omitted=1)
    assert read.devices_by_package(c) == [("nokia_srlinux", 3)]
    assert read.summarize(None) == read.Counts()
