"""The stamps against `internal/intent`'s stamps_test.go: a branch's IntentStamps, PortStamps
and QueryGroups as Infrahub's GraphQL answers them, paged, folded per device as D-058 and
D-060 count each stamp: the latest instant kept verbatim, each of the five sources of a
device's intent moving it alone, a cable both its ends' devices', a null skipped, each
device's pair and ids, an artifact's checksum never intent, the scope's tag, every page,
a pinned `at` on every request, a stamp that is no time refused, and Infrahub's own
account read from the template query's internal groups. The fake (FakeStamps) is the Go
test's fakeStamps on tier 1's FakeInfrahub; the SDK runs whole."""

from urllib.parse import parse_qs, quote_plus, urlsplit

import pytest

from fylgja_orchestrator.adapters.infrahub import queries
from fylgja_orchestrator.adapters.infrahub.client import Client, Config
from fylgja_orchestrator.adapters.infrahub.packages import Match
from fylgja_orchestrator.adapters.infrahub.read import ReadError
from fylgja_orchestrator.adapters.infrahub.stamps import read_stamps

from .conftest import ADDRESS, TOKEN

PAGE_SIZE = queries.PAGE_SIZE

# The accounts' ids, as Infrahub's GraphQL answers an account: the operator's, the account
# Infrahub's task workers run as, under its default name agent, and another an install may
# give them, or rename agent to.
ACCOUNT_ADMIN = "18dc77a5-3850-admin"
ACCOUNT_AGENT = "18dc77a5-c3c3-agent"
ACCOUNT_WORKERS = "18dc77a5-0000-renamed"

# The template query's id, which every artifact's definition renders through.
QUERY_DEVICE_CONFIG = "18dc77c3-196f-device-config"

# The fixture's own stamps (research §6.6, §8.16): its one platform written first, the
# devices after, interfaces after them, the cabling after that, the artifacts' checksums
# last.
STAMP_PLATFORM = "2026-10-08T05:47:56.812998+00:00"
STAMP_DEVICES = "2026-10-08T05:47:58.232738+00:00"
STAMP_INTERFACES = "2026-10-08T05:48:00.978841+00:00"
STAMP_CABLING = "2026-10-08T05:48:03.562937+00:00"
STAMP_ARTIFACTS = "2026-10-08T05:48:38.544482+00:00"


def edge_page(edges: list, limit: int, offset: int) -> dict:
    """One page of edges, each as given."""
    return {"count": len(edges), "edges": list(edges[min(offset, len(edges)) : offset + limit])}


class FakeStamps:
    """A branch's IntentStamps, PortStamps and QueryGroups as Infrahub's GraphQL answers
    them, paged, and what it was asked. Each device is an edge of the device root, its
    node_metadata beside its node, and each port a node of the physical root; the devices
    are served to the scope's tag alone, the ports to the device ids asked for, and the
    internal query groups to the query ids asked for. A group is (query, group_type, meta):
    its query's id, its group_type, and its node_metadata as Infrahub keeps it, every field
    of it, whichever the query selects."""

    def __init__(self, infrahub, tag="fylgja", devices=(), ports=(), groups=(), branch="change-1"):
        self.infrahub = infrahub
        self.branch = branch
        self.tag = tag
        self.devices = list(devices)
        self.ports = list(ports)
        self.groups = list(groups)
        self.offsets: list[int] = []  # each IntentStamps page's offset
        self.asked: list[list] = []  # each PortStamps request's device ids
        self.asked_query: list[list] = []  # each QueryGroups request's query ids
        infrahub.branches.add(branch)
        infrahub.operations.update(
            IntentStamps=self._intent_stamps, PortStamps=self._port_stamps, QueryGroups=self._query_groups
        )

    def queries(self) -> list[tuple[str, str]]:
        """Each GraphQL request's operation and raw query string."""
        return [
            (r["operation"], urlsplit(r["url"]).query)
            for r in self.infrahub.requests
            if r["path"].startswith("/graphql/")
        ]

    def _refuse_branch(self, branch):
        if branch != self.branch:
            return 404, {"errors": ["no route"]}
        return None

    def _intent_stamps(self, variables, query_text, branch, params):
        if (refused := self._refuse_branch(branch)) is not None:
            return refused
        self.offsets.append(variables["offset"])
        devices = self.devices if variables.get("tag") == self.tag else []
        return {"data": {"DcimDevice": edge_page(devices, variables["limit"], variables["offset"])}}

    def _port_stamps(self, variables, query_text, branch, params):
        if (refused := self._refuse_branch(branch)) is not None:
            return refused
        self.asked.append(variables.get("devices"))
        # Infrahub refuses a page holding an uncabled port's connector stamp, so the query
        # asks for cabled ports alone, as this fake serves them.
        if "connector__isnull: false" not in query_text:
            refusal = "an uncabled port's connector.node_metadata is null in a non-null field"
            return 418, {"errors": [{"message": refusal}]}
        ports = [
            {"node": p}
            for p in self.ports
            if p["connector"]["node"] is not None and p["device"]["node"]["id"] in (variables.get("devices") or [])
        ]
        return {"data": {"InterfacePhysical": edge_page(ports, variables["limit"], variables["offset"])}}

    def _query_groups(self, variables, query_text, branch, params):
        if (refused := self._refuse_branch(branch)) is not None:
            return refused
        self.asked_query.append(variables.get("queries"))
        internal = 'group_type__value: "internal"' in query_text
        groups = [
            {"node_metadata": meta}
            for query, group_type, meta in self.groups
            if query in (variables.get("queries") or []) and (not internal or group_type == "internal")
        ]
        return {"data": {"CoreGraphQLQueryGroup": edge_page(groups, variables["limit"], variables["offset"])}}

    def read(self, at=""):
        client = Client(Config(address=ADDRESS, token=TOKEN, branch=self.branch, at=at), requester=self.infrahub)
        return read_stamps(client, "fylgja")


def meta(s: str) -> dict:
    """An edge wrapper's node_metadata, written by the operator's account; "" is Infrahub's
    null."""
    if not s:
        return {"updated_at": None}
    return meta_by(s, ACCOUNT_ADMIN, STAMP_PLATFORM)


def meta_by(updated: str, by: str, created: str) -> dict:
    """An edge wrapper's node_metadata: its node last written at updated by the account of
    that id, and created at created."""
    return {"updated_at": updated, "created_at": created, "updated_by": {"__typename": "CoreAccount", "id": by}}


def internal_group(created_by: str, updated_by: str) -> tuple:
    """One internal group of the template query, created by the account given and last
    updated by another."""

    def account(i):
        return {"__typename": "CoreAccount", "id": i}

    return (
        QUERY_DEVICE_CONFIG,
        "internal",
        {
            "created_at": STAMP_ARTIFACTS,
            "created_by": account(created_by),
            "updated_at": STAMP_ARTIFACTS,
            "updated_by": account(updated_by),
        },
    )


def value_of(v) -> dict:
    return {"value": v}


def stamped_device(name: str, s: str, interfaces=None, *artifacts) -> dict:
    """A device's edge: its own stamp, on Nokia's SR Linux with the platform and the
    manufacturer stamped at STAMP_PLATFORM, with the interfaces and artifacts given. Its id
    is dev-<name>, its platform's platform-srlinux, its manufacturer's manufacturer-nokia.
    No interface, or no artifact, is Go's nil slice: a null list of edges."""
    return {
        "node_metadata": meta(s),
        "node": {
            "__typename": "DcimDevice",
            "id": "dev-" + name,
            "name": value_of(name),
            "platform": stamped_platform(
                "platform-srlinux", "SR Linux", STAMP_PLATFORM, "manufacturer-nokia", "Nokia", STAMP_PLATFORM
            ),
            "interfaces": {"edges": interfaces},
            "artifacts": {"edges": [{"node": a} for a in artifacts] if artifacts else None},
        },
    }


def stamped_platform(id_: str, name: str, s: str, manufacturer_id: str, manufacturer: str, ms: str) -> dict:
    """A device's platform edge, its manufacturer's within it."""
    return {
        "node_metadata": meta(s),
        "node": {
            "id": id_,
            "name": value_of(name),
            "manufacturer": {
                "node_metadata": meta(ms),
                "node": {"id": manufacturer_id, "name": value_of(manufacturer)},
            },
        },
    }


def on_platform(device: dict, platform: dict) -> dict:
    """A device put on a platform edge of its own."""
    device["node"]["platform"] = platform
    return device


def stamped_interface(typename: str, id_: str, s: str) -> dict:
    """One interface edge of a device, of either kind."""
    return {"node_metadata": meta(s), "node": {"__typename": typename, "id": id_}}


def stamped_artifact(name: str, checksum_stamp: str) -> dict:
    return {
        "name": value_of(name),
        "checksum": {"value": "43e8fd0c2de5f4646f74a51d34742824", "updated_at": checksum_stamp or None},
        "definition": {
            "node": {
                "transformation": {
                    "node": {"__typename": "CoreTransformJinja2", "query": {"node": {"id": QUERY_DEVICE_CONFIG}}}
                }
            }
        },
    }


def stamped_port(device: str, cable: str, s: str) -> dict:
    """A physical port of a device, cabled when cable is not ""."""
    connector = {"node_metadata": meta(""), "node": None}
    if cable:
        connector = {"node_metadata": meta(s), "node": {"__typename": "DcimCable", "id": cable}}
    return {"device": {"node": {"__typename": "DcimDevice", "id": "dev-" + device}}, "connector": connector}


def test_stamps_latest(infrahub):
    """Latest is the latest instant the read returned, compared as times rather than as
    strings, and kept verbatim: a stamp in another offset that sorts after it as text but
    names an earlier instant does not win, and a Z stamp that is later does."""
    f = FakeStamps(
        infrahub,
        devices=[
            stamped_device("n1", STAMP_DEVICES, [stamped_interface("InterfacePhysical", "if-n1-e1", STAMP_INTERFACES)]),
            # 06:48:01+01:00 is 05:48:01Z: lexically the latest string, not the latest instant.
            stamped_device("n2", "2026-10-08T06:48:01.000000+01:00"),
        ],
        ports=[
            stamped_port("n1", "cable-1", "2026-10-08T05:48:03.9Z"),
            stamped_port("n2", "cable-1", "2026-10-08T05:48:03.9Z"),
        ],
    )
    got = f.read()
    assert got.latest == "2026-10-08T05:48:03.9Z", "want the Z cable stamp, the latest instant, verbatim"
    assert got.devices["n2"].intent == "2026-10-08T05:48:03.9Z", "n2's cable is its intent too"


LATER = "2026-10-16T19:00:00.000001+00:00"


def _edit_device(n1, ports):
    n1["node_metadata"] = meta(LATER)


def _edit_physical(n1, ports):
    n1["node"]["interfaces"]["edges"][0]["node_metadata"] = meta(LATER)


def _edit_virtual(n1, ports):
    n1["node"]["interfaces"]["edges"][1]["node_metadata"] = meta(LATER)


def _edit_platform(n1, ports):
    n1["node"]["platform"]["node_metadata"] = meta(LATER)


def _edit_manufacturer(n1, ports):
    n1["node"]["platform"]["node"]["manufacturer"]["node_metadata"] = meta(LATER)


def _edit_cable(n1, ports):
    ports[0]["connector"]["node_metadata"] = meta(LATER)


@pytest.mark.parametrize(
    "edit",
    [_edit_device, _edit_physical, _edit_virtual, _edit_platform, _edit_manufacturer, _edit_cable],
    ids=["the device", "a physical interface", "a virtual interface", "its platform", "its manufacturer", "its cable"],
)
def test_stamps_each_source_moves_the_device(infrahub, edit):
    """Each of the five sources of a device's intent moves its stamp alone (FR-023): the
    device, an interface of either kind, its platform, its platform's manufacturer and the
    cable one of its ports is an end of. n2, beside it on its own platform, keeps its own."""
    n1 = stamped_device(
        "n1",
        STAMP_DEVICES,
        [
            stamped_interface("InterfacePhysical", "if-n1-e1", STAMP_INTERFACES),
            stamped_interface("InterfaceVirtual", "if-n1-lo0", STAMP_INTERFACES),
        ],
    )
    n2 = on_platform(
        stamped_device("n2", STAMP_DEVICES),
        stamped_platform("platform-eos", "EOS", STAMP_PLATFORM, "manufacturer-arista", "Arista", STAMP_PLATFORM),
    )
    ports = [stamped_port("n1", "cable-out", STAMP_CABLING), stamped_port("n2", "", "")]
    edit(n1, ports)
    got = FakeStamps(infrahub, devices=[n1, n2], ports=ports).read()
    assert got.devices["n1"].intent == LATER
    assert got.devices["n2"].intent == STAMP_DEVICES, "n2 keeps its own"
    assert got.latest == LATER


def test_stamps_cable_moves_both_devices_and_no_third(infrahub):
    """A cable is the intent of the device of each of its ends in the scope, and of no
    third: a re-cabling of n1 and n2 moves both, and neither n3 nor anything n3 holds."""
    recabled = "2026-10-16T19:41:12.000300+00:00"
    f = FakeStamps(
        infrahub,
        devices=[stamped_device(n, STAMP_DEVICES) for n in ("n1", "n2", "n3")],
        ports=[
            stamped_port("n1", "cable-12", recabled),
            stamped_port("n2", "cable-12", recabled),
            stamped_port("n2", "cable-23", STAMP_CABLING),
            stamped_port("n3", "cable-23", STAMP_CABLING),
        ],
    )
    got = f.read()
    for name, want in {"n1": recabled, "n2": recabled, "n3": STAMP_CABLING}.items():
        assert got.devices[name].intent == want, name


def test_stamps_skip_a_null(infrahub):
    """A null stamp is skipped wherever it is: a device's own, a platform's, a
    manufacturer's, an interface's, an uncabled port's connector."""
    n1 = on_platform(
        stamped_device("n1", "", [stamped_interface("InterfacePhysical", "if-n1-e1", "")]),
        stamped_platform("platform-srlinux", "SR Linux", "", "manufacturer-nokia", "Nokia", ""),
    )
    f = FakeStamps(
        infrahub,
        devices=[n1, stamped_device("n2", STAMP_DEVICES)],
        ports=[stamped_port("n1", "", ""), stamped_port("n1", "cable-1", "")],
    )
    got = f.read()
    assert got.devices["n1"].intent == "", "n1 has no intent stamped"
    assert got.latest == STAMP_DEVICES, "want n2's"


def test_stamps_match_and_ids(infrahub):
    """Each device keeps its pair, by which the registry picks its package, and the ids an
    intent event names it by, in the order read (D-048): its own, its platform's, its
    manufacturer's, each interface's of both kinds, then each cable's once. A device with no
    platform, or a platform with no manufacturer, has "" where it has none."""
    bare = stamped_device("n2", STAMP_DEVICES)
    bare["node"]["platform"] = {"node_metadata": meta(""), "node": None}
    orphan = on_platform(
        stamped_device("n3", STAMP_DEVICES),
        {
            "node_metadata": meta(STAMP_PLATFORM),
            "node": {
                "id": "platform-orphan",
                "name": value_of("Orphan OS"),
                "manufacturer": {"node_metadata": meta(""), "node": None},
            },
        },
    )
    f = FakeStamps(
        infrahub,
        devices=[
            stamped_device(
                "n1",
                STAMP_DEVICES,
                [
                    stamped_interface("InterfacePhysical", "if-n1-e1", STAMP_INTERFACES),
                    stamped_interface("InterfacePhysical", "if-n1-e2", STAMP_INTERFACES),
                    stamped_interface("InterfaceVirtual", "if-n1-lo0", STAMP_INTERFACES),
                ],
            ),
            bare,
            orphan,
        ],
        # A cable with both ends on n1 is n1's once.
        ports=[stamped_port("n1", "cable-loop", STAMP_CABLING), stamped_port("n1", "cable-loop", STAMP_CABLING)],
    )
    got = f.read()
    assert got.devices["n1"].ids == [
        "dev-n1", "platform-srlinux", "manufacturer-nokia", "if-n1-e1", "if-n1-e2", "if-n1-lo0", "cable-loop"
    ]
    for name, want in {
        "n1": Match(manufacturer="Nokia", platform="SR Linux"),
        "n2": Match(manufacturer="", platform=""),
        "n3": Match(manufacturer="", platform="Orphan OS"),
    }.items():
        assert got.devices[name].match == want, f"{name}'s pair"
    assert got.devices["n2"].ids == ["dev-n2"]
    assert got.devices["n3"].ids == ["dev-n3", "platform-orphan"]


def test_stamps_artifact_checksum(infrahub):
    """An artifact's checksum stamp is the artifact's and the branch's latest, never the
    device's intent: a generate that moves it does not make the device's intent newer."""
    f = FakeStamps(
        infrahub,
        devices=[
            stamped_device(
                "n1",
                STAMP_DEVICES,
                None,
                stamped_artifact("device-config", STAMP_ARTIFACTS),
                stamped_artifact("unrendered", ""),
            ),
            stamped_device("n2", STAMP_DEVICES),
        ],
    )
    got = f.read()
    assert got.latest == STAMP_ARTIFACTS, "want the checksum's"
    n1 = got.devices["n1"]
    assert n1.intent == STAMP_DEVICES, "a checksum is not intent"
    assert n1.artifacts == {"device-config": STAMP_ARTIFACTS, "unrendered": ""}
    assert got.devices["n2"].artifacts == {}, "n2 has no artifact"


def test_stamps_read_under_the_scope(infrahub):
    """The devices are read under the scope's tag alone: a scope that selects none reads no
    device and asks for no port."""
    f = FakeStamps(
        infrahub,
        tag="other",
        devices=[stamped_device("n1", STAMP_DEVICES)],
        ports=[stamped_port("n1", "cable-1", STAMP_CABLING)],
    )
    got = f.read()
    assert got.devices == {} and got.latest == "", "read under a tag no device carries"
    assert f.asked == [], "ports asked for with no device read"


def test_stamps_reads_every_page(infrahub):
    """The devices are paged until every one is read, and their ports are asked for by a
    hundred device ids at a time: 150 devices are two pages of each."""
    devices, ports = [], []
    for i in range(150):
        name = f"n{i:03d}"
        devices.append(stamped_device(name, STAMP_DEVICES))
        ports.append(stamped_port(name, "", ""))
    devices[149]["node_metadata"] = meta(STAMP_ARTIFACTS)
    ports[0] = stamped_port("n000", "cable-1", STAMP_CABLING)
    f = FakeStamps(infrahub, devices=devices, ports=ports)
    got = f.read()
    assert len(got.devices) == 150
    assert f.offsets == [0, PAGE_SIZE], "pages requested at offsets"
    assert len(f.asked) == 2 and len(f.asked[0]) == PAGE_SIZE and len(f.asked[1]) == 50, "ports asked for"
    assert got.latest == STAMP_ARTIFACTS, "the second page's stamp was not read"
    assert got.devices["n000"].intent == STAMP_CABLING, "n000's cable was not read"


def test_stamps_pinned_on_every_page(infrahub):
    """A pinned read sends its `at` verbatim and URL encoded on every page of both
    operations, and an unpinned one sends none (Constitution VI)."""
    at = "2026-10-08T05:48:38.544483+00:00"
    devices = [stamped_device(f"n{i:03d}", STAMP_DEVICES) for i in range(101)]
    f = FakeStamps(infrahub, devices=devices)
    f.read(at)
    sent = f.queries()
    assert [op for op, _ in sent] == ["IntentStamps", "IntentStamps", "PortStamps", "PortStamps"]
    for i, (op, raw) in enumerate(sent):
        assert raw == "at=" + quote_plus(at), f"request {i} ({op}) sent {raw!r}, want at= the instant URL encoded"
        assert parse_qs(raw)["at"] == [at], f"request {i}'s at decoded"

    infrahub.requests.clear()
    f.read()
    for i, (_, raw) in enumerate(f.queries()):
        assert raw == "", f"unpinned request {i} sent {raw!r}"


def test_stamps_refuse_a_stamp_that_is_not_a_time(infrahub):
    """A stamp that is not a time is an error naming it, the branch and the instant, and
    never the credential."""
    f = FakeStamps(infrahub, devices=[stamped_device("n1", "yesterday")])
    with pytest.raises(ReadError) as raised:
        f.read("2026-10-08T05:48:38.544483+00:00")
    message = str(raised.value)
    for want in ['"yesterday"', "branch change-1", "at 2026-10-08T05:48:38.544483+00:00"]:
        assert want in message, f"error {message!r} does not carry {want}"
    assert TOKEN not in message, "the credential reached the error"


@pytest.mark.parametrize(
    ("workers", "other"),
    [(ACCOUNT_AGENT, ACCOUNT_WORKERS), (ACCOUNT_WORKERS, ACCOUNT_AGENT)],
    ids=["the account named agent", "a renamed account"],
)
def test_stamps_leave_out_infrahubs_own_account(infrahub, workers, other):
    """D-058 and D-060: a node Infrahub's own account wrote last contributes its creation,
    and that account is the creator of the template query's internal groups, whatever it is
    named. After a hand generate, the task workers' account adds the new port and the new
    cable to the query's groups, past the checksum (017 research §5.11, §5.12): neither
    moves n1's intent, nor the branch's latest, while the operator's own writes do. An
    account named as Infrahub names it, and one renamed or given to the workers in its
    place, are told apart the same way: by the groups, never by a name."""
    created = "2026-10-26T14:53:17.107000+00:00"  # the operator writes the port
    cabled = "2026-10-26T14:53:17.716000+00:00"  # and the cable, then generates
    generated = "2026-10-26T14:53:24.591000+00:00"  # n1's checksum
    joined = "2026-10-26T14:53:28.761000+00:00"  # the workers' account adds both to the groups
    n1 = stamped_device(
        "n1",
        STAMP_DEVICES,
        [
            stamped_interface("InterfacePhysical", "if-n1-e1", STAMP_INTERFACES),
            {"node_metadata": meta_by(joined, workers, created), "node": {"id": "if-n1-e3"}},
        ],
        stamped_artifact("device-config", generated),
    )
    # n2's interface was last written by an account that created no group: intent.
    n2 = stamped_device(
        "n2",
        STAMP_DEVICES,
        [{"node_metadata": meta_by(joined, other, created), "node": {"id": "if-n2-e1"}}],
        stamped_artifact("device-config", generated),
    )
    port = stamped_port("n1", "cable-13", "")
    port["connector"]["node_metadata"] = meta_by(joined, workers, cabled)
    f = FakeStamps(
        infrahub,
        devices=[n1, n2],
        ports=[port],
        groups=[internal_group(workers, workers), internal_group(workers, workers)],
    )
    got = f.read()
    assert got.devices["n1"].intent == cabled, "want the cable's creation: the groups' join is not intent"
    assert got.devices["n2"].intent == joined, "an account that created no group writes intent"
    assert got.latest == joined, "want n2's"
    assert f.asked_query == [[QUERY_DEVICE_CONFIG]], "want the template query's id once, from both artifacts"


GENERATED = "2026-10-26T15:24:03.380000+00:00"
DELETED = "2026-10-26T15:24:23.227218+00:00"  # the operator's cable delete stamps n1's port
JOINED = "2026-10-26T15:24:05.100000+00:00"  # the workers' account joined n2's port


def _groups_devices() -> list:
    return [
        stamped_device(
            "n1",
            STAMP_DEVICES,
            [{"node_metadata": meta_by(DELETED, ACCOUNT_ADMIN, STAMP_INTERFACES), "node": {"id": "if-n1-e1"}}],
            stamped_artifact("device-config", GENERATED),
        ),
        stamped_device(
            "n2",
            STAMP_DEVICES,
            [{"node_metadata": meta_by(JOINED, ACCOUNT_AGENT, STAMP_INTERFACES), "node": {"id": "if-n2-e1"}}],
            stamped_artifact("device-config", GENERATED),
        ),
    ]


@pytest.mark.parametrize("case", ["a group the operator updated", "no internal group"])
def test_stamps_read_the_groups_creator(infrahub, case):
    """D-060: a member's delete restamps its groups as the deleting account (017 research
    §5.13), so a group's last writer may be the operator. Its creator is still the workers'
    account, and the operator's stamps, the delete's on the cable's end ports among them,
    stay intent; so does every stamp when the only groups are another kind's."""
    if case == "a group the operator updated":
        f = FakeStamps(
            infrahub,
            devices=_groups_devices(),
            groups=[internal_group(ACCOUNT_AGENT, ACCOUNT_ADMIN), internal_group(ACCOUNT_AGENT, ACCOUNT_AGENT)],
        )
        got = f.read()
        assert got.devices["n1"].intent == DELETED, (
            "want the operator's delete: a group's last writer is not Infrahub's own"
        )
        assert got.devices["n2"].intent == STAMP_INTERFACES, "want its port's creation"
        return
    query, _, group_meta = internal_group(ACCOUNT_AGENT, ACCOUNT_AGENT)
    f = FakeStamps(infrahub, devices=_groups_devices(), groups=[(query, "default", group_meta)])
    got = f.read()
    assert got.devices["n2"].intent == JOINED, "with no internal group no stamp is left out"


def test_stamps_ask_for_groups_where_the_stamps_are(infrahub):
    """With no artifact there is no query, so no group is asked for and nothing is left
    out; a pinned read sends its `at` on the groups' request too, read where the stamps
    are."""
    joined = "2026-10-26T15:24:05.100000+00:00"
    bare = stamped_device("n1", joined)
    bare["node_metadata"] = meta_by(joined, ACCOUNT_AGENT, STAMP_DEVICES)
    f = FakeStamps(infrahub, devices=[bare], groups=[internal_group(ACCOUNT_AGENT, ACCOUNT_AGENT)])
    got = f.read()
    assert f.asked_query == [], "groups asked for with no artifact read"
    assert got.devices["n1"].intent == joined

    at = "2026-10-26T15:30:00.000001+00:00"
    infrahub.requests.clear()
    f = FakeStamps(
        infrahub,
        devices=[stamped_device("n1", STAMP_DEVICES, None, stamped_artifact("device-config", STAMP_ARTIFACTS))],
    )
    f.read(at)
    sent = f.queries()
    for op, raw in sent:
        assert raw == "at=" + quote_plus(at), f"{op} sent {raw!r}, want the stamps' at"
    assert [op for op, _ in sent] == ["IntentStamps", "PortStamps", "QueryGroups"]

