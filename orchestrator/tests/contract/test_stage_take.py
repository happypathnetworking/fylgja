"""A branch read and taken to a snapshot from a real Infrahub, then compiled by the core (T021),
as `internal/stage`'s contract tests held the Go reader's read-and-compile to it:
`artifact_contract_test.go` (each device's artifact read and carried into the bundle byte for
byte, a description change detected and a serial number change not, a device with no current
artifact refused by name), `mixed_contract_test.go` (two platforms read as
`testdata/ctm/mixed.json` and compiled with both packages' answers) and
`reproducibility_contract_test.go` (a read pinned at T reproducing its snapshot id and its
bundle across a regeneration, a new node and a tag, and the unpinned read after them moving
both).

The read and the take are the adapter's (`read.read`, `snapshot.take`), the compile the core's
`twin compile --snapshot` on a server of the test's own with no INFRAHUB_*, as `stage.Read`
and `stage.Compile` were the Go tests' two halves. Each test seeds its own throwaway
`fylgja-test-py-*` branch through the fixture tool and deletes it when it ends. Boot no twin
while they run.

    set -a; . local/.env; set +a; orchestrator/.venv/bin/pytest -q orchestrator -m contract -k test_stage_take
"""

import copy
import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fylgja_orchestrator.adapters.infrahub import snapshot
from fylgja_orchestrator.adapters.infrahub import read as reading
from fylgja_orchestrator.documents.findings import REJECTION, Finding

from .conftest import ARTIFACT_NAME, ARTIFACT_WAIT_S, FIXTURE_BRANCH, REPO, SCOPE, artifacts_of, read_under

pytestmark = pytest.mark.contract

BUNDLE_VERSION = "6"
MANIFEST = "manifest.json"
TOPOLOGY = "topology.clab.yml"
SEEDED = reading.Counts(devices=3, interfaces=15, links=3, artifacts=3)


def marker(branch: str) -> str:
    """`testsupport.MarkerDescription`: the description every seeded device carries, which the
    template prints in its artifact's header."""
    suffix = "fixture" if branch == FIXTURE_BRANCH else branch.removeprefix("fylgja-")
    return f"FYLGJA-MARKER-{suffix}"


def md5(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()  # noqa: S324 - Infrahub's checksum


def bundle_files(root: Path) -> dict[str, bytes]:
    """A compiled bundle's files by their path under it."""
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


class Taker:
    """Reads a branch, takes the read and has the core compile it, each into a directory of
    its own under the test's: what `stage.Read`, `snapshot.Take` and `stage.Compile` did."""

    def __init__(self, core, root: Path):
        self.core, self.root, self.n = core, root, 0

    def read(self, branch: str, at: str = "") -> dict:
        ctm, found, err = read_under(branch, at)
        assert err is None, f"reading {branch} at {at!r}: {err}"
        assert ctm is not None and not found.rejected, f"reading {branch} at {at!r} was rejected: {list(found)}"
        return ctm

    def take(self, branch: str, at: str = "") -> tuple[dict, str, dict[str, bytes]]:
        """The take of a read, its bundle id and its bundle's files."""
        taken = snapshot.take(self.read(branch, at), [])
        self.n += 1
        path = self.root / f"{self.n}.json"
        snapshot.write(path, taken)
        out = self.root / f"{self.n}.bundle"
        code, doc = self.core.compile(path, out)
        assert code == 0, f"compiling {branch} at {at!r} was rejected: {doc['findings']}"
        assert doc["snapshot_id"] == taken["snapshot_id"]
        return taken, doc["bundle_id"], bundle_files(out)


def content_of(ctm: dict) -> dict[str, str]:
    return {d["name"]: d["artifact"]["content"] for d in ctm["devices"] if d.get("artifact")}


def checksums_of(ctm: dict) -> dict[str, str]:
    return {d["name"]: d["artifact"]["checksum"] for d in ctm["devices"] if d.get("artifact")}


def outside_artifacts(ctm: dict) -> bytes:
    """A CTM's canonical encoding with each artifact's content and checksum and the envelope's
    observed_at blanked: everything a read carries but the artifacts' bytes and its instant."""
    cp = copy.deepcopy(ctm)
    cp["envelope"]["observed_at"] = ""
    for d in cp["devices"]:
        if d.get("artifact"):
            d["artifact"]["content"] = d["artifact"]["checksum"] = ""
    return json.dumps(snapshot.normalize(cp), indent=2, sort_keys=True).encode()


def same_outside_artifacts(what: str, was: dict, now: dict) -> None:
    a, b = outside_artifacts(was).decode().split("\n"), outside_artifacts(now).decode().split("\n")
    for i, (x, y) in enumerate(zip(a, b, strict=False)):
        assert x == y, f"{what} changed the CTM outside the artifacts, first at line {i + 1}:\n was {x}\n now {y}"
    assert len(a) == len(b), f"{what} changed the CTM outside the artifacts: {len(a)} lines, then {len(b)}"


def await_checksum(branch: str, device: str, other_than: str, wait: float = ARTIFACT_WAIT_S) -> dict:
    """Polls until the device's artifact is listed with a checksum other than other_than."""
    deadline = time.monotonic() + wait
    while True:
        listed = artifacts_of(branch)
        if listed.get(device, {}).get("checksum", other_than) != other_than:
            return listed
        assert time.monotonic() < deadline, (
            f"{device}'s artifact checksum stayed {other_than} for {wait}s after a change was generated")
        time.sleep(0.5)


def test_artifact_on_a_seeded_branch(fixture_tool, core, tmp_path):
    """M5's tier-2 proofs share one seeded throwaway branch, in order, because seeding and
    generating is most of each proof's cost: the read and the bundle, then detection, then the
    refusals, which add devices and so come last."""
    taker = Taker(core, tmp_path)
    with fixture_tool.throwaway("artifact") as branch:
        artifact_read_and_bundle(taker, branch)
        artifact_detection(fixture_tool, taker, branch)
        artifact_refusals(fixture_tool, branch)


def artifact_read_and_bundle(taker: Taker, branch: str) -> None:
    """The read fetches every device's artifact and the bundle carries it: three devices each
    with an artifact whose checksum is Infrahub's and whose bytes hash to it, and the core's
    files carry configs/<n>.device-config, byte for byte, with the manifest's entry and bundle
    6."""
    taken, bundle_id, files = taker.take(branch)
    ctm = taken["ctm"]
    infrahub = {d: a["checksum"] for d, a in artifacts_of(branch).items()}
    assert len(ctm["devices"]) == 3 and len(infrahub) == 3, infrahub
    for d in ctm["devices"]:
        a = d.get("artifact")
        assert a is not None, f"device {d['name']} was read with no artifact"
        assert (a["name"], a["content_type"], a["checksum"]) == (ARTIFACT_NAME, "text/plain", infrahub[d["name"]])
        assert md5(a["content"]) == a["checksum"], f"device {d['name']}'s artifact bytes do not hash to its checksum"

    manifest = json.loads(files[MANIFEST])
    assert manifest["bundle_version"] == BUNDLE_VERSION
    content = content_of(ctm)
    for n in manifest["nodes"]:
        file = f"configs/{n['name']}.{ARTIFACT_NAME}"
        a = n.get("artifact")
        assert a is not None and (a["name"], a["checksum"], a["file"], a["size"]) == (
            ARTIFACT_NAME, infrahub[n["name"]], file, len(content[n["name"]].encode())), a
        assert files[file].decode() == content[n["name"]], f"{file} is not the artifact's bytes, unchanged"
    print(f"bundle_id {bundle_id}")


def artifact_detection(fixture_tool, taker: Taker, branch: str) -> None:
    """A configuration change is detected by the read and nothing else is. Two reads of an
    unchanged branch take one snapshot id and compile to one bundle id. A description change,
    regenerated, moves them, and the two CTMs are equal outside the artifacts and the instant
    each was read. A serial number change, regenerated, leaves them where they were: Infrahub
    writes nothing for a regeneration whose output matches, not the checksum and not the
    storage id."""
    first, id, _ = taker.take(branch)
    again, again_id, _ = taker.take(branch)
    assert again_id == id and again["snapshot_id"] == first["snapshot_id"], "two reads of an unchanged branch differ"

    before = artifacts_of(branch)
    fixture_tool.run("-branch", branch, "-describe", f"device:n1={marker(branch)}-moved")
    fixture_tool.change(branch, "-generate")
    await_checksum(branch, "n1", before["n1"]["checksum"])
    moved, moved_id, _ = taker.take(branch)
    assert moved_id != id, f"a description change, regenerated, left bundle_id at {id}"
    assert moved["snapshot_id"] != first["snapshot_id"]
    was, now = content_of(first["ctm"]), content_of(moved["ctm"])
    assert was["n1"] != now["n1"], "n1's artifact bytes did not change with its description"
    for d in ("n2", "n3"):
        assert was[d] == now[d], f"{d}'s artifact bytes changed with n1's description"
    same_outside_artifacts("a description change, regenerated,", first["ctm"], moved["ctm"])
    print(f"description change: bundle_id {id} -> {moved_id}")

    # A regeneration that writes nothing gives nothing to wait for, so the listing is watched
    # for 20 seconds, well past what a regeneration that changes bytes takes, and must not move.
    listed = artifacts_of(branch)
    fixture_tool.run("-branch", branch, "-set-serial", "n1=LAB-0001")
    fixture_tool.change(branch, "-generate")
    end = time.monotonic() + 20
    while time.monotonic() < end:
        assert artifacts_of(branch) == listed, "a serial number change, regenerated, moved Infrahub's listing"
        time.sleep(1)
    unmoved, unmoved_id, _ = taker.take(branch)
    assert unmoved_id == moved_id, f"a serial number change, regenerated, moved bundle_id {moved_id} -> {unmoved_id}"
    assert unmoved["snapshot_id"] == moved["snapshot_id"]
    assert content_of(unmoved["ctm"]) == now, "a serial number change, regenerated, changed an artifact's bytes"
    same_outside_artifacts("a serial number change, regenerated,", moved["ctm"], unmoved["ctm"])


def artifact_refusals(fixture_tool, branch: str) -> None:
    """A device with no current artifact is refused by name, and the read writes no CTM. n4 is
    not in the group the definition renders for; n5 is, but nothing has been generated since it
    joined. Each carries the tag and the platform the fixture's devices do, so its package is
    found and its artifact looked for."""
    common = ("-device-platform", "Nokia/SR Linux", "-device-tag", "fylgja", "-device-management", "mgmt0")
    fixture_tool.run("-branch", branch, "-add-device", "n4:mgmt0", *common)
    fixture_tool.run("-branch", branch, "-add-device", "n5:mgmt0", *common, "-device-group")
    ctm, found, err = read_under(branch)
    assert err is None
    assert ctm is None, "a refused read returned a CTM"
    assert list(found) == [
        Finding(REJECTION, reading.RULE_ARTIFACT_MISSING, d, f"device {d} has no artifact named {ARTIFACT_NAME} on "
                f"branch {branch}") for d in ("n4", "n5")]


def test_mixed_seed_reads(fixture_tool, core, tmp_path):
    """A branch of two platforms reads and compiles: three devices, each device's package found
    by its manufacturer and platform, three artifacts under one name, and one bundle carrying
    both packages' answers. The read is testdata/ctm/mixed.json below the envelope (SC-001 of
    017), the throwaway's marker replaced by the fixture's in each artifact and its checksum
    recomputed as Infrahub's, the MD5 of the bytes; of the envelope, the scope, the mapping and
    the fidelity list's three fixed rows match too."""
    with fixture_tool.throwaway("mixed", mixed=True) as branch:
        ctm, found, err = read_under(branch)
    assert err is None and ctm is not None and not found.rejected, list(found)
    assert len(ctm["devices"]) == 3
    platforms = {}
    for d in ctm["devices"]:
        platforms[d["name"]] = d["platform"]["package"]
        a = d.get("artifact")
        assert a is not None and (a["name"], a["content_type"]) == (ARTIFACT_NAME, "text/plain"), a
    assert platforms == {"e1": "arista_eos", "e2": "arista_eos", "s1": "nokia_srlinux"}
    # The template branches on the platform: an EOS device's configuration opens with `!`.
    e1 = next(d for d in ctm["devices"] if d["name"] == "e1")["artifact"]["content"]
    assert e1.startswith("! e1:"), f"e1's artifact is not EOS text:\n{e1}"

    want = snapshot.normalize(json.loads((REPO / "testdata" / "ctm" / "mixed.json").read_text()))
    e, w = ctm["envelope"], want["envelope"]
    assert e["scope"] == SCOPE == w["scope"]
    assert e["mapping"] == w["mapping"]
    assert len(e["fidelity"]) == 3 and e["fidelity"] == w["fidelity"]
    read = snapshot.normalize(copy.deepcopy(ctm))
    read["envelope"] = w
    mine, fixture = marker(branch), marker(w["branch"])
    for d in read["devices"]:
        a = d.get("artifact")
        if a is None:
            continue
        assert mine in a["content"], f"device {d['name']}'s artifact does not carry the branch's marker {mine}"
        a["content"] = a["content"].replace(mine, fixture)
        a["checksum"] = md5(a["content"])
    assert snapshot.marshal(snapshot.take(read)) == snapshot.marshal(snapshot.take(want)), (
        "the read and the committed fixture disagree")

    path = tmp_path / "mixed.json"
    snapshot.write(path, snapshot.take(ctm, []))
    code, doc = core.compile(path, tmp_path / "mixed.bundle")
    assert code == 0, doc["findings"]
    manifest = json.loads((tmp_path / "mixed.bundle" / MANIFEST).read_text())
    assert manifest["bundle_version"] == BUNDLE_VERSION
    # One bundle, both platforms' answers: each node under its own package's bootstrap route,
    # and a forwarding entry per package.
    vias = {n["name"]: n["bootstrap"]["via"] for n in manifest["nodes"]}
    for n in manifest["nodes"]:
        assert n.get("artifact") and n["artifact"]["checksum"], f"manifest node {n['name']} carries no artifact entry"
    assert vias == {"e1": "push", "e2": "push", "s1": "startup_config"}
    forwarding = manifest["fidelity"]["production_forwarding"]
    assert len(forwarding) == 2 and forwarding["arista_eos"] and forwarding["nokia_srlinux"], forwarding
    print(f"bundle_id {doc['bundle_id']}")


def test_seed_mixed_refuses_the_fixture_branch(fixture_tool):
    """The mixed seed refuses the durable fixture branch, which holds the three-node fixture,
    before any request: nothing is written, so this needs no branch of its own."""
    with pytest.raises(RuntimeError, match=f"-mixed refuses branch {FIXTURE_BRANCH}"):
        fixture_tool.seed(FIXTURE_BRANCH, mixed=True)


def test_pinned_read_reproduces_its_bundle(fixture_tool, core, tmp_path):
    """A pinned reference reproduces its snapshot and its bundle against a branch that changed
    (Constitution V, VI). The takes pinned to T before and after n1's description changed and
    was regenerated (new bytes, a new storage object), and after n4 was added and cs1, a device
    complete but for the tag and rendered before T, was tagged, have one snapshot id and compile
    to one bundle, file for file, though each was observed at another time: the id leaves
    observed_at out. The unpinned take after the changes reads cs1 and n4 and moves both ids
    and the topology."""
    taker = Taker(core, tmp_path)
    with fixture_tool.throwaway("repro") as branch:
        fixture_tool.run("-branch", branch, "-add-device", "cs1:mgmt0", "-device-platform", "Nokia/SR Linux",
                         "-device-management", "mgmt0", "-device-group")
        fixture_tool.change(branch, "-generate")
        # The local clock read after the seed returns sees the whole seed: Infrahub runs on the
        # same kernel clock. Six fractional digits, since intent.at.precision refuses nine.
        at = datetime.now(UTC).strftime(reading.OBSERVED_AT_FORMAT)
        print(f"branch {branch}, T = {at}")

        before, before_id, before_files = taker.take(branch, at)
        assert reading.summarize(before["ctm"]) == SEEDED, "the read at T does not see the whole seed"
        sums_at_t = checksums_of(before["ctm"])

        current = artifacts_of(branch)
        fixture_tool.run("-branch", branch, "-describe", f"device:n1={marker(branch)}-moved")
        fixture_tool.change(branch, "-generate")
        regenerated = await_checksum(branch, "n1", current["n1"]["checksum"])["n1"]
        assert regenerated["storage_id"] != current["n1"]["storage_id"], "n1's regeneration kept its storage id"

        reconfigured, reconfigured_id, reconfigured_files = taker.take(branch, at)
        assert reading.summarize(reconfigured["ctm"]) == SEEDED
        assert checksums_of(reconfigured["ctm"]) == sums_at_t
        assert reconfigured_files == before_files, "the pinned bundles either side of the regeneration differ"
        assert reconfigured_id == before_id and reconfigured["snapshot_id"] == before["snapshot_id"]

        print(fixture_tool.change(branch, "-add-fourth-node", "n1").strip())
        # The fourth node's generate can return before n1's artifact is rewritten for its new
        # port: wait for n1's checksum to move and n4's to be listed, bounded at 240 s.
        deadline = time.monotonic() + 240
        while True:
            listed = artifacts_of(branch)
            if listed["n1"]["checksum"] != regenerated["checksum"] and listed.get("n4", {}).get("checksum"):
                break
            assert time.monotonic() < deadline, f"240s after n4 was added, the listing is {listed}"
            time.sleep(0.5)
        fixture_tool.run("-branch", branch, "-tag-devices", "cs1")

        after, after_id, after_files = taker.take(branch, at)
        assert reading.summarize(after["ctm"]) == SEEDED
        assert "cs1" not in {d["name"] for d in after["ctm"]["devices"]}, "the read pinned to T read cs1"
        assert checksums_of(after["ctm"]) == sums_at_t
        assert after_files == before_files, "the pinned bundles either side of both changes differ"
        assert after_id == before_id and after["snapshot_id"] == before["snapshot_id"]
        assert after["observed_at"] != before["observed_at"], "the takes either side were observed at one time"

        unpinned, unpinned_id, unpinned_files = taker.take(branch)
        assert reading.summarize(unpinned["ctm"]) == reading.Counts(devices=5, interfaces=19, links=4, artifacts=5)
        assert "cs1" in {d["name"] for d in unpinned["ctm"]["devices"]}, "the unpinned read did not read cs1"
        assert unpinned_id != before_id and unpinned["snapshot_id"] != before["snapshot_id"]
        assert unpinned_files[TOPOLOGY] != before_files[TOPOLOGY], "the change did not reach the topology"
        now = checksums_of(unpinned["ctm"])["n1"]
        assert now != sums_at_t["n1"] and now == artifacts_of(branch)["n1"]["checksum"]

        print(f"pinned at T before the change: bundle {before_id}, snapshot {before['snapshot_id']}")
        print(f"pinned at T after the change:  bundle {after_id}, snapshot {after['snapshot_id']}")
        print(f"unpinned after the change:     bundle {unpinned_id}, snapshot {unpinned['snapshot_id']}")

