"""The configuration artifact against `internal/intent`'s artifact_test.go, and the two REST
URLs against storage_test.go: which of a device's artifacts is its configuration, whether
its content is held, whether the bytes served are the bytes Infrahub described, each
refusal worded as the Go reader worded it and never quoting a byte of content; a refused
credential fails the read; a pinned read sends its `at` verbatim everywhere but the schema
endpoint, and never falls back to the current artifact."""

from dataclasses import replace

import pytest

from fylgja_orchestrator.adapters.infrahub import read
from fylgja_orchestrator.adapters.infrahub.client import ENV_TOKEN, Client, Config
from fylgja_orchestrator.documents.findings import REJECTION, Finding

from .conftest import ADDRESS, TOKEN
from .dcim import Dcim, md5_hex
from .test_read import read_fake


@pytest.fixture
def fake(infrahub):
    return Dcim.from_ctm(infrahub)


def sentinel_content(device: str) -> bytes:
    """Artifact bytes that name themselves on every line, so a message quoting any of them
    is caught whichever line it quotes."""
    return f"# CONTENT-SENTINEL {device}\nset / system name host-name CONTENT-SENTINEL-{device}\n".encode()


def no_content(f: Dcim, found) -> None:
    """No finding quotes a byte of any artifact the fake serves: a line of it, or the
    sentinel every test's content carries."""
    for fd in found:
        assert "CONTENT-SENTINEL" not in fd.message, f"{fd.rule} quotes artifact content: {fd.message}"
        for _, body in f.infrahub.objects.values():
            for line in body.decode("utf-8", "replace").split("\n"):
                assert not (len(line) > 8 and line in fd.message), (
                    f"{fd.rule} quotes artifact content {line!r}: {fd.message}"
                )


def storage_count(f: Dcim, storage_id: str) -> int:
    return f.infrahub.count("/api/storage/object/" + storage_id)


def checksum(f: Dcim, device: str) -> str:
    return f.artifacts[device][0].checksum


# The fake unchanged is a clean read: every device comes back with its artifact, byte for
# byte, and nothing of Infrahub's addressing survives into the CTM. Every refusal below is
# this read with one thing changed.
def test_read_carries_each_artifact(fake):
    want = {d.name: fake.infrahub.objects["storage-" + d.name][1] for d in fake.devices}

    c, found = read_fake(fake)

    assert not found.rejected and c is not None, f"a clean fake was refused: {found}"
    for d in c["devices"]:
        a = d.get("artifact")
        assert a is not None, f"device {d['name']} carries no artifact"
        assert a == {
            "name": "device-config",
            "content_type": "text/plain",
            "checksum": md5_hex(want[d["name"]]),
            "content": want[d["name"]].decode(),
        }, f"device {d['name']} artifact {a} is not what Infrahub served"
    for d in fake.devices:
        n = storage_count(fake, "storage-" + d.name)
        assert n == 1, f"device {d.name}'s content was fetched {n} times, want once"


def _rename_definition(f):
    # An artifact of another definition is not this platform's configuration.
    a = f.artifacts["n2"][0]
    a.definition_name = "interfaces-report"
    a.name = "interfaces-report"


def _second_of_that_name(f):
    second = replace(f.artifacts["n2"][0], checksum="00000000000000000000000000000001", storage_id="storage-n2-second")
    f.artifacts["n2"].append(second)


def _ambiguous_message(f):
    sums = sorted([f.artifacts["n2"][0].checksum, f.artifacts["n2"][1].checksum])
    return (f"device n2 has 2 artifacts named device-config (checksums {sums[0]}, {sums[1]}); "
            "fylgja never chooses among them")


def _set(attr, v):
    def setup(f):
        setattr(f.artifacts["n2"][0], attr, v)

    return setup


ARTIFACT_FAULTS = [
    (
        "no artifact of the package's name",
        _rename_definition,
        read.RULE_ARTIFACT_MISSING,
        lambda f: "device n2 has no artifact named device-config on branch fylgja-fixture",
    ),
    (
        "no artifact at all",
        lambda f: f.artifacts.pop("n2"),
        read.RULE_ARTIFACT_MISSING,
        lambda f: "device n2 has no artifact named device-config on branch fylgja-fixture",
    ),
    ("two of that name", _second_of_that_name, read.RULE_ARTIFACT_AMBIGUOUS, _ambiguous_message),
    (
        "pending",
        _set("status", "Pending"),
        read.RULE_ARTIFACT_NOT_READY,
        lambda f: "device n2: artifact device-config is Pending, not Ready; fylgja never regenerates an artifact, "
        "because that is a write to Infrahub",
    ),
    (
        "a generation that failed",
        _set("status", "Error"),
        read.RULE_ARTIFACT_NOT_READY,
        lambda f: "device n2: artifact device-config is Error, not Ready; fylgja never regenerates an artifact, "
        "because that is a write to Infrahub",
    ),
    (
        "Ready with no stored content",
        _set("storage_id", ""),
        read.RULE_ARTIFACT_NOT_READY,
        lambda f: "device n2: artifact device-config is Ready but has no stored content, so it is not held as "
        "current; fylgja never regenerates an artifact, because that is a write to Infrahub",
    ),
    (
        "a content type the package does not accept",
        _set("content_type", "application/json"),
        read.RULE_ARTIFACT_CONTENT_TYPE_UNSUPPORTED,
        lambda f: f"device n2: artifact device-config (checksum {checksum(f, 'n2')}) is application/json; "
        "the nokia_srlinux package accepts text/plain",
    ),
    (
        "bytes that are not text",
        lambda f: f.set_content("n2", bytes([0xFF, 0xFE, 0x00]) + sentinel_content("n2")),
        read.RULE_ARTIFACT_CONTENT_TYPE_UNSUPPORTED,
        lambda f: f"device n2: artifact device-config (checksum {checksum(f, 'n2')}) is text/plain but its "
        "content is not text",
    ),
    (
        "a storage object Infrahub does not hold",
        _set("storage_id", "18d67d7e-0000-0000-0000-000000000000"),
        read.RULE_ARTIFACT_CONTENT_UNAVAILABLE,
        lambda f: f"device n2: artifact device-config (checksum {checksum(f, 'n2')}): Infrahub does not serve its "
        "content: HTTP 404: Unable to find the node 18d67d7e-0000-0000-0000-000000000000 / StorageObject in the "
        "database.",
    ),
    (
        "another status, with no error document",
        lambda f: f.infrahub.objects.__setitem__("storage-n2", (502, b"<html>bad gateway</html>")),
        read.RULE_ARTIFACT_CONTENT_UNAVAILABLE,
        lambda f: f"device n2: artifact device-config (checksum {checksum(f, 'n2')}): Infrahub does not serve its "
        "content: HTTP 502",
    ),
    (
        "bytes that are not the ones Infrahub described",
        lambda f: f.infrahub.objects.__setitem__("storage-n2", (200, sentinel_content("n2 altered"))),
        read.RULE_ARTIFACT_CHECKSUM_MISMATCH,
        lambda f: f"device n2: artifact device-config fetched with checksum {md5_hex(sentinel_content('n2 altered'))}"
        f", Infrahub reports {checksum(f, 'n2')}",
    ),
]


# Each artifact refusal of the read, produced by the read under test from a listing or an
# object store a live branch cannot be made to hold. Each names the device and the
# artifact, and says why in words an operator can act on, with no content in it.
@pytest.mark.parametrize(("setup", "rule", "want"), [t[1:] for t in ARTIFACT_FAULTS],
                         ids=[t[0] for t in ARTIFACT_FAULTS])
def test_read_refuses_each_artifact_fault(fake, setup, rule, want):
    # Every device's bytes carry the sentinel, so a message quoting content from any
    # device — not only the refused one — is caught.
    for d in ("n1", "n2", "n3"):
        fake.set_content(d, sentinel_content(d))
    setup(fake)

    c, found = read_fake(fake)

    assert c is None, "a refused read returned a CTM"
    # No step: the read's callers file its findings under theirs.
    expected = Finding(REJECTION, rule, "n2", want(fake))
    assert list(found) == [expected]
    no_content(fake, found)


# A content fetch answered 401 or 403 is not a device's fault but the credential's: the
# read fails as a whole, naming the variable to fix and every device whose fetch was
# refused, each once, with the artifact and checksum it was reading, and the credential
# appears nowhere — not even when the server quotes the request's header back
# (contracts/cli.md "once per device that failed"). The fetch carries on past a refused
# device and past a served one, so n3 is named after n2 was read.
@pytest.mark.parametrize("status", [401, 403], ids=["Unauthorized", "Forbidden"])
@pytest.mark.parametrize("refused", [["n2"], ["n1", "n3"]], ids=["n2", "n1,n3"])
def test_read_content_credential_refusal_fails_the_read(fake, status, refused):
    for d in refused:
        fake.infrahub.objects["storage-" + d] = (status, f'{{"errors":[{{"message":"key {TOKEN} refused"}}]}}'.encode())

    with pytest.raises(read.ReadError) as raised:
        read_fake(fake)

    msg = str(raised.value)
    for want in (ENV_TOKEN, "reading the artifact content for device", "(branch fylgja-fixture)"):
        assert want in msg, f"error {msg!r} does not say {want!r}"
    for d in ("n1", "n2", "n3"):
        a = fake.artifacts[d][0]
        named = f"device {d} (artifact {a.definition_name}, checksum {a.checksum})"
        want = 1 if d in refused else 0
        got = msg.count(f"device {d} ")
        assert got == want and (want == 0 or named in msg), (
            f"error names {d} {got} times, want {want} as {named!r}: {msg}"
        )
    assert TOKEN not in msg, f"the credential leaked into the error: {msg}"


# Every refused device is reported in one pass, each named once, beside what validation
# finds in the intent itself — an operator fixing a branch sees everything that stops it,
# not the first thing (Constitution III).
def test_read_refuses_every_device_in_one_pass(fake):
    for d in ("n1", "n2", "n3"):
        fake.set_content(d, sentinel_content(d))
    del fake.artifacts["n1"]
    fake.artifacts["n2"][0].status = "Pending"
    fake.infrahub.objects["storage-n3"] = (200, sentinel_content("n1"))
    # And a fault in the intent: a cable with both ends on one device, which reaches the
    # CTM and which validation refuses (mapping.md §4); link.endpoints.same_device is one of
    # the CTM's intrinsic rules, which the read runs.
    fake.add_ports("n1", "ethernet-1/3", "ethernet-1/4")
    fake.cable("cable-loop", "n1:ethernet-1/3|n1:ethernet-1/4", "n1:ethernet-1/3", "n1:ethernet-1/4")

    c, found = read_fake(fake)

    assert c is None, "a refused read returned a CTM"
    by_device: dict[str, list[str]] = {}
    completeness = 0
    for fd in found:
        if fd.object in ("n1", "n2", "n3"):
            by_device.setdefault(fd.object, []).append(fd.rule)
        if fd.rule == "link.endpoints.same_device":
            completeness += 1
    for device, rule in {
        "n1": read.RULE_ARTIFACT_MISSING,
        "n2": read.RULE_ARTIFACT_NOT_READY,
        "n3": read.RULE_ARTIFACT_CHECKSUM_MISMATCH,
    }.items():
        got = by_device.get(device)
        assert got == [rule], f"device {device} named by {got}, want once, by {rule}"
    assert completeness == 1, f"{completeness} link.endpoints.same_device findings beside the refusals: {found}"
    no_content(fake, found)


PINNED_AT = "2026-09-18T10:00:00.123456+00:00"
"""An operator's T with a character a query string must escape, so "verbatim" is shown to
survive the encoding: Infrahub must receive exactly what was typed."""


def asked_only_at(f: Dcim, at: str) -> None:
    """The read asked Infrahub for nothing but the branch as of at: the schema endpoint with
    no at, and every GraphQL query and content fetch with at verbatim — or, unpinned, with
    none. A request without it would be a read of the branch now, the fallback a pinned read
    must never take."""
    for r in f.infrahub.requests:
        sent = r["query"].get("at")
        if r["path"] == "/api/schema":
            assert sent is None, f"the schema endpoint was sent at={sent}; it takes none"
        elif at == "":
            assert sent is None, f"an unpinned read sent {r['path']} {r['operation']} with at={sent}"
        else:
            assert sent == [at], f"a read pinned to {at} sent {r['path']} {r['operation']} with at={sent}"


# A read with at carries it verbatim on the listing and on every content fetch, and a read
# without it carries none, so a pinned read's bytes are the ones Infrahub held at T.
@pytest.mark.parametrize("at", ["", PINNED_AT])
def test_pinned_read_carries_at_verbatim(fake, at):
    c, found = read_fake(fake, at=at)

    assert not found.rejected and c is not None, f"a clean fake was refused: {found}"
    assert c["envelope"].get("at", "") == at
    for d in c["devices"]:
        assert d.get("artifact") is not None, f"device {d['name']} carries no artifact"
    asked_only_at(fake, at)
    for d in fake.devices:
        n = storage_count(fake, "storage-" + d.name)
        assert n == 1, f"device {d.name}'s content was fetched {n} times, want once"


PINNED_REFUSALS = [
    (
        "no artifact then",
        lambda f: f.artifacts.pop("n2"),
        read.RULE_ARTIFACT_MISSING,
        0,
        lambda f: f"device n2 has no artifact named device-config on branch fylgja-fixture at {PINNED_AT}"
        "; the artifact did not exist then",
    ),
    (
        "not Ready then",
        _set("status", "Pending"),
        read.RULE_ARTIFACT_NOT_READY,
        0,
        lambda f: f"device n2: artifact device-config was Pending at {PINNED_AT}"
        ", not Ready; fylgja never regenerates an artifact, because that is a write to Infrahub",
    ),
    (
        "Ready then with no stored content",
        _set("storage_id", ""),
        read.RULE_ARTIFACT_NOT_READY,
        0,
        lambda f: f"device n2: artifact device-config was Ready at {PINNED_AT}"
        " but had no stored content, so it was not held as current; "
        "fylgja never regenerates an artifact, because that is a write to Infrahub",
    ),
    (
        "existed then but is not served",
        _set("storage_id", "18d67d7e-0000-0000-0000-000000000000"),
        read.RULE_ARTIFACT_CONTENT_UNAVAILABLE,
        1,
        lambda f: f"device n2: artifact device-config (checksum {checksum(f, 'n2')}): Infrahub does not serve its "
        f"content as it stood at {PINNED_AT}"
        ": HTTP 404: Unable to find the node 18d67d7e-0000-0000-0000-000000000000 / StorageObject in the database.",
    ),
]


# A pinned read refused says which case applies in its own words — the artifact did not
# exist at T, was not Ready at T, or existed at T but is not served — and never falls back
# to the current artifact: no request of the read went without at, the listing was asked
# once, and the refused device's content was fetched no more than the listing at T named
# (contracts/cli.md).
@pytest.mark.parametrize(("setup", "rule", "fetched", "want"), [t[1:] for t in PINNED_REFUSALS],
                         ids=[t[0] for t in PINNED_REFUSALS])
def test_pinned_read_refuses_in_its_own_words(fake, setup, rule, fetched, want):
    for d in ("n1", "n2", "n3"):
        fake.set_content(d, sentinel_content(d))
    setup(fake)
    # Where the fallback would come from, were there one: the current artifact is served
    # under its own id, ready to be fetched instead.
    fake.infrahub.objects["storage-n2-current"] = (200, sentinel_content("n2 current"))

    c, found = read_fake(fake, at=PINNED_AT)

    assert c is None, "a refused read returned a CTM"
    assert list(found) == [Finding(REJECTION, rule, "n2", want(fake))]
    no_content(fake, found)

    asked_only_at(fake, PINNED_AT)
    n = len(fake.infrahub.served("Devices"))
    assert n == 1, f"the listing was asked {n} times, want once"
    # Every content fetch not of n1's or n3's is of n2's: whatever id it asked for.
    n2 = sum(1 for r in fake.infrahub.requests if r["path"].startswith("/api/storage/object/"))
    n2 -= storage_count(fake, "storage-n1") + storage_count(fake, "storage-n3")
    assert n2 == fetched, f"n2's content was fetched {n2} times, want {fetched}"
    assert storage_count(fake, "storage-n2-current") == 0, "the pinned read fetched the current artifact"


# Unpinned, the same refusals keep M5's present-tense wording, with no at in them: the
# pinned words are the pinned read's alone.
def test_unpinned_refusals_name_no_instant(fake):
    del fake.artifacts["n1"]
    fake.artifacts["n2"][0].status = "Pending"
    fake.artifacts["n3"][0].storage_id = "18d67d7e-0000-0000-0000-000000000000"

    _, found = read_fake(fake)

    assert len(found) == 3, f"findings {found}, want three"
    for fd in found:
        for pinned in (" at ", "did not exist then", " was ", "as it stood"):
            assert pinned not in fd.message, f"unpinned {fd.rule} says {pinned!r}: {fd.message}"
    asked_only_at(fake, "")


# The two REST endpoints differ in exactly one thing, and it is load-bearing: the object
# store has a time axis and the schema endpoint does not.
#
# Sending `at` to the schema endpoint would be harmless — it ignores one — but the read
# would then be making a request nobody verified, and the envelope's schema_hash would look
# as though it were the schema as of `at`, which it is not. Leaving `at` off the content
# fetch would be worse: a pinned read would verify the checksum the listing gave at `at`
# against whatever bytes are current.
#
# Pinning both URLs is the cheapest way to keep the pair from drifting.
STORAGE_ID = "18d67d7e-a006-995e-2cfe-c5124cbde270"
URL_AT = "2026-09-18T16:51:32.118490+00:00"
# The `+` of a timezone offset, URL encoded. Unencoded it is read as a space and the
# request is refused.
URL_AT_ENCODED = "2026-09-18T16%3A51%3A32.118490%2B00%3A00"


@pytest.mark.parametrize(
    ("at", "want"),
    [
        ("", {"schema": "/api/schema?branch=fylgja-fixture", "storage": "/api/storage/object/" + STORAGE_ID}),
        (
            URL_AT,
            {
                "schema": "/api/schema?branch=fylgja-fixture",
                "storage": "/api/storage/object/" + STORAGE_ID + "?at=" + URL_AT_ENCODED,
            },
        ),
    ],
    ids=["unpinned", "pinned"],
)
def test_request_urls_carry_at_only_where_there_is_a_time_axis(infrahub, at, want):
    infrahub.objects[STORAGE_ID] = (200, b"")
    c = Client(Config(address=ADDRESS, token=TOKEN, branch="fylgja-fixture", at=at), requester=infrahub)

    def request_uri() -> str:
        return infrahub.requests[-1]["url"].removeprefix(ADDRESS)

    c.schema_document()
    assert request_uri() == want["schema"]

    c.get_at(read.storage_object_path(STORAGE_ID))
    assert request_uri() == want["storage"]
