"""Every list Infrahub answers is held to the total it gave for it (D-082): a list short of its `count`, longer than
it, or holding one object twice is `read.incomplete`, an error, and never mapped."""

from __future__ import annotations

from fake import listing, three_node

from fylgja_infrahub.rows import RULE_INCOMPLETE, Device, Listing, Source, incomplete

AT = "2026-11-09T10:00:00.000000+00:00"


def device(name: str) -> Device:
    return Device(f"device-{name}", name, "SR Linux", "Nokia", listing(f"{name}.artifacts", []))


D1, D2, D3 = device("n1"), device("n2"), device("n3")


def test_a_whole_list_has_no_finding() -> None:
    assert incomplete(Listing("DcimDevice", 3, (D1, D2, D3)), branch="b", at=AT) is None


def test_a_list_short_of_its_count_is_incomplete() -> None:
    finding = incomplete(Listing("DcimDevice", 3, (D1, D2)), branch="b", at=AT)
    assert finding is not None
    assert (finding.rule, finding.severity, finding.object) == (RULE_INCOMPLETE, "error", "DcimDevice")
    assert RULE_INCOMPLETE == "read.incomplete"
    for held in ("counted 3", "answered 2", "branch b", AT):
        assert held in finding.message


def test_a_list_longer_than_its_count_is_incomplete() -> None:
    finding = incomplete(Listing("n1.artifacts", 1, (D1, D2)), branch="b", at=None)
    assert finding is not None
    assert (finding.rule, finding.severity, finding.object) == (RULE_INCOMPLETE, "error", "n1.artifacts")
    for held in ("counted 1", "answered 2", "branch b"):
        assert held in finding.message


def test_an_object_twice_is_incomplete() -> None:
    finding = incomplete(Listing("DcimDevice", 2, (D1, D1)), branch="b", at=AT)
    assert finding is not None
    assert (finding.rule, finding.severity, finding.object) == (RULE_INCOMPLETE, "error", "DcimDevice")
    for held in ("counted 2", "answered 2", "1 of them", "branch b", AT):
        assert held in finding.message


def test_an_empty_list_of_count_zero_is_whole() -> None:
    assert incomplete(Listing("InterfacePhysical", 0, ()), branch="b", at=AT) is None


def test_the_fake_is_a_source() -> None:
    source: Source = three_node()
    assert source.devices("main", None, "fylgja").count == 3
