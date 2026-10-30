"""The cables against `internal/intent`'s cable_test.go: a cable the mapping cannot place
is omitted, an info finding and a fidelity row, and never refuses the read; a connector of
another kind is never a link; each cable judged once, by the first reason that applies; a
management cable reaches the CTM; a cable listing fewer ends than it counts is omitted."""

import pytest

from fylgja_orchestrator.adapters.infrahub import read
from fylgja_orchestrator.documents.findings import INFO, Finding

from .dcim import Dcim
from .test_read import read_fake


@pytest.fixture
def fake(infrahub):
    return Dcim.from_ctm(infrahub)


FIXED_ROWS = [
    {"disposition": "approximated", "object": "interface.enabled", "source": "InterfacePhysical.status",
     "reason": "a port is enabled unless its status is disabled; the library's status is not an admin state"},
    {"disposition": "approximated", "object": "interface.mgmt_only", "source": "InterfacePhysical.role",
     "reason": "the management port is the port whose role is management; the library has no management-only flag"},
]
"""The fixed rows every read of this reader writes (mapping.md §5)."""

PLATFORM_ROW = {"disposition": "omitted", "object": "platform.version", "source": "DcimPlatform",
                "reason": "the library's platform carries no version"}
"""The third fixed row, after every omitted cable whose object sorts first."""


def omitted(obj: str, source: str, reason: str) -> dict:
    return {"disposition": "omitted", "object": obj, "source": source, "reason": reason}


def device(c: dict, name: str) -> dict | None:
    return next((d for d in c["devices"] if d["name"] == name), None)


def interface(d: dict, name: str) -> dict | None:
    return next((i for i in d["interfaces"] if i["name"] == name), None)


# A cable the mapping cannot place is omitted and never refuses the read (US2 scenarios 2
# and 3; FR-006): three ends, one end, an end on a device outside the scope, and an end
# that is not a physical port, a console port or a virtual interface carrying a cable (the
# spec's edge case: the interface is not read, and its cable is omitted naming its kind).
# Each is an info finding naming the cable, its reason and every end it can name, and a
# fidelity row with the same reason; its ports stay in the CTM, cabled to nothing. A cable
# with no label is named by its id. The three fixture cables, each reached from both its
# ends, are three links.
def test_cables_the_read_cannot_place(fake):
    fake.add_ports("n1", "ethernet-1/3", "ethernet-1/4", "ethernet-1/5")
    fake.add_ports("n2", "ethernet-1/3", "ethernet-1/4")
    fake.add_ports("n3", "ethernet-1/3", "ethernet-1/4")
    fake.add_device("cs1", "Opengear", "Console OS", [], "port1")
    fake.cable("cable-three", "c-three", "n1:ethernet-1/3", "n2:ethernet-1/3", "n3:ethernet-1/3")
    fake.cable("cable-one", "c-one", "n1:ethernet-1/4")
    fake.cable("cable-out", "c-out", "n1:ethernet-1/5", "cs1:port1")
    fake.cable("cable-console", "", "n2:ethernet-1/4", "DcimConsolePort#cp-7")
    fake.cable("cable-virtual", "c-virtual", "n3:ethernet-1/4", "InterfaceVirtual#vi-lo0")

    c, found = read_fake(fake)

    assert not found.rejected and c is not None, f"findings {found}; a cable refused the read"
    assert list(found) == [
        Finding(INFO, read.RULE_OMIT_CABLE_ENDS, "c-one",
                "cable c-one is omitted: other than two ends (1); its ends are n1:ethernet-1/4"),
        Finding(INFO, read.RULE_OMIT_CABLE_OUTSIDE_SCOPE, "c-out",
                "cable c-out is omitted: an end outside the scope (id-cs1:port1); its ends are id-cs1:port1, "
                "n1:ethernet-1/5"),
        Finding(INFO, read.RULE_OMIT_CABLE_ENDS, "c-three",
                "cable c-three is omitted: other than two ends (3); its ends are n1:ethernet-1/3, n2:ethernet-1/3, "
                "n3:ethernet-1/3"),
        Finding(INFO, read.RULE_OMIT_CABLE_ENDPOINT, "c-virtual",
                "cable c-virtual is omitted: an end not on a physical port (InterfaceVirtual); its ends are "
                "n3:ethernet-1/4"),
        Finding(INFO, read.RULE_OMIT_CABLE_ENDPOINT, "cable-console",
                "cable cable-console is omitted: an end not on a physical port (DcimConsolePort); its ends are "
                "n2:ethernet-1/4"),
    ]
    assert c["envelope"]["fidelity"] == [
        *FIXED_ROWS,
        omitted("c-one", "DcimCable", "other than two ends (1)"),
        omitted("c-out", "DcimCable", "an end outside the scope (id-cs1:port1)"),
        omitted("c-three", "DcimCable", "other than two ends (3)"),
        omitted("c-virtual", "DcimCable", "an end not on a physical port (InterfaceVirtual)"),
        omitted("cable-console", "DcimCable", "an end not on a physical port (DcimConsolePort)"),
        PLATFORM_ROW,
    ]
    assert len(c["links"]) == 3, f"links {c['links']}; want the fixture's three alone"
    for dev, name in (("n1", "ethernet-1/3"), ("n1", "ethernet-1/5"), ("n2", "ethernet-1/4"),
                      ("n3", "ethernet-1/3"), ("n3", "ethernet-1/4")):
        port = interface(device(c, dev), name)
        assert port is not None and not port.get("link"), f"{dev}:{name} is {port}; want it read, linked to nothing"
    assert device(c, "cs1") is None, "the device outside the scope was read"
    assert read.summarize(c).cables_omitted == 5
    for d in c["devices"]:
        assert interface(d, "lo0") is None, f"{d['name']} reads the virtual interface lo0"


# A connector that is not a DcimCable, a kind of the operator's own inheriting
# DcimConnector, which conformance allows (FR-012), is never a link, even between two
# physical ports in the scope: it is omitted under its own reason, an info finding naming
# it by its id, since the read selects a label on a DcimCable alone, with its kind and its
# ends, and a fidelity row whose source is its kind (FR-006; T096). Its ports stay in the
# CTM, cabled to nothing, and the read's success line counts it among the cables omitted.
def test_a_connector_that_is_not_a_cable_is_omitted(fake):
    fake.add_ports("n1", "ethernet-1/3")
    fake.add_ports("n2", "ethernet-1/3")
    fake.cable("jumper-1", "j-1", "n1:ethernet-1/3", "n2:ethernet-1/3").kind = "AcmeJumper"

    c, found = read_fake(fake)

    assert not found.rejected and c is not None, f"findings {found}; the connector refused the read"
    assert list(found) == [
        Finding(INFO, read.RULE_OMIT_CABLE_KIND, "jumper-1",
                "connector jumper-1 is omitted: a connector that is not a DcimCable (AcmeJumper); its ends are "
                "n1:ethernet-1/3, n2:ethernet-1/3"),
    ]
    assert c["envelope"]["fidelity"] == [
        *FIXED_ROWS,
        omitted("jumper-1", "AcmeJumper", "a connector that is not a DcimCable (AcmeJumper)"),
        PLATFORM_ROW,
    ]
    assert len(c["links"]) == 3, f"links {c['links']}; want the fixture's three alone"
    for dev in ("n1", "n2"):
        port = interface(device(c, dev), "ethernet-1/3")
        assert port is not None and not port.get("link"), f"{dev}:ethernet-1/3 is {port}; want it linked to nothing"
    assert read.summarize(c).cables_omitted == 1


# The first reason that applies is the one given, in R-05's order: the connector's kind
# (T096), then its ends, then the kind of an end, then the scope. A cable reached from
# several ports in the scope is judged once. A cable none of whose ends is in the scope is
# reached from no port read, and is not read.
@pytest.mark.parametrize(
    ("kind", "ends", "rule"),
    [
        ("", ["n1:ethernet-1/3", "n2:ethernet-1/3", "cs1:port1"], read.RULE_OMIT_CABLE_ENDS),
        ("", ["n1:ethernet-1/3", "n2:ethernet-1/3", "DcimConsolePort#cp-7"], read.RULE_OMIT_CABLE_ENDS),
        ("", ["n1:ethernet-1/3", "DcimConsolePort#cp-7"], read.RULE_OMIT_CABLE_ENDPOINT),
        ("", ["n1:ethernet-1/3", "cs1:port1"], read.RULE_OMIT_CABLE_OUTSIDE_SCOPE),
        ("", None, read.RULE_OMIT_CABLE_ENDS),
        ("AcmeJumper", ["n1:ethernet-1/3", "DcimConsolePort#cp-7", "cs1:port1"], read.RULE_OMIT_CABLE_KIND),
        ("AcmeJumper", ["n1:ethernet-1/3", "n2:ethernet-1/3"], read.RULE_OMIT_CABLE_KIND),
    ],
    ids=[
        "three ends, one outside",
        "three ends, one a console port",
        "an end a console port, reached from the other",
        "an end outside, reached from the other",
        "no end",
        "another kind, three ends, one a console port, one outside",
        "another kind, two physical ends in the scope",
    ],
)
def test_a_cable_is_judged_once_by_the_first_reason(fake, kind, ends, rule):
    """kind is the connector's, "" a DcimCable."""
    fake.add_ports("n1", "ethernet-1/3")
    fake.add_ports("n2", "ethernet-1/3")
    fake.add_device("cs1", "Opengear", "Console OS", [], "port1")
    fake.cable("cable-x", "c-x", *(ends or [])).kind = kind
    if ends is None:
        # A cable with no end is reached from no port; it is the port's connector all the
        # same when Infrahub still names it there.
        _, p = fake.port("n1:ethernet-1/3")
        p.cable = "cable-x"

    c, found = read_fake(fake)

    # A connector of another kind has no label the read selects: its id names it.
    obj = "cable-x" if kind else "c-x"
    assert c is not None and len(found) == 1 and found[0].rule == rule and found[0].object == obj, (
        f"findings {found}; want one, {rule} of {obj}"
    )


# A cable between two devices in the scope with an end on a management port is a link like
# any other: it reaches the CTM (US2 scenario 4; FR-007). One cable has both ends on
# management ports, the other one end, n3:mgmt0 to n2's uncabled ethernet-1/3; n3's rather
# than n1's, which the first cable already holds, since a port is the end of one cable and
# two links ending on one interface are refused (LinkTerminations).
#
# Not ported: the Go test's second half, which compiles the CTM (stage.Compile) and finds
# one omit.link.mgmt_only per link. The compiler is the core's, in Go, which keeps that
# assertion; the adapter has no compile to run.
def test_management_cable_reaches_the_ctm(fake):
    fake.add_ports("n2", "ethernet-1/3")
    fake.cable("cable-mgmt", "n1:mgmt0|n2:mgmt0", "n1:mgmt0", "n2:mgmt0")
    fake.cable("cable-half", "n2:ethernet-1/3|n3:mgmt0", "n3:mgmt0", "n2:ethernet-1/3")

    c, found = read_fake(fake)

    assert not found.rejected and c is not None, f"findings {found}; want a clean read"
    both, half = "n1:mgmt0|n2:mgmt0", "n2:ethernet-1/3|n3:mgmt0"
    ids = {link["id"] for link in c["links"]}
    assert both in ids and half in ids and len(c["links"]) == 5, (
        f"links {c['links']}; want the fixture's three, {both} and {half}"
    )
    for dev, port, link in (("n1", "mgmt0", both), ("n2", "mgmt0", both), ("n3", "mgmt0", half)):
        mgmt = interface(device(c, dev), port)
        assert mgmt["mgmt_only"] and mgmt.get("link") == link, (
            f"{dev}:{port} {mgmt}; want the management port, linked to {link}"
        )
    data = interface(device(c, "n2"), "ethernet-1/3")
    assert not data["mgmt_only"] and data.get("link") == half, (
        f"n2:ethernet-1/3 {data}; want a data port, linked to {half}"
    )
    assert read.summarize(c).cables_omitted == 0


# A cable that counts two ends and lists fewer, an end Infrahub would not give, is not two
# ends either: omitted, never a link with a missing end.
def test_a_cable_listing_fewer_ends_than_it_counts_is_omitted(fake):
    fake.add_ports("n1", "ethernet-1/3")
    fake.cable("cable-short", "c-short", "n1:ethernet-1/3")
    fake.short = {"cable-short": 2}

    c, found = read_fake(fake)

    want = Finding(INFO, read.RULE_OMIT_CABLE_ENDS, "c-short",
                   "cable c-short is omitted: other than two ends (1 listed of 2); its ends are n1:ethernet-1/3")
    assert c is not None and list(found) == [want] and len(c["links"]) == 3, (
        f"findings {found}, CTM {c is not None}; want exactly {want} and the fixture's three links"
    )
