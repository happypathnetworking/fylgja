"""Every list Nautobot answers is held to the `count` it gave for it (D-118): a list short of its `count`, longer than
it, holding one object twice, or lacking an id it was asked for by id is `read.incomplete`, an error, and never
mapped."""

from __future__ import annotations

from fake import three_node

from fylgja_nautobot.rows import RULE_INCOMPLETE, Device, Listing, Port, Source, Tag, incomplete


def device(id: str, name: str) -> Device:
    return Device(id, name, "p1")


D1, D2, D3 = device("d1", "n1"), device("d2", "n2"), device("d3", "n3")


def test_a_whole_list_has_no_finding() -> None:
    assert incomplete(Listing("dcim.device", 3, (D1, D2, D3))) is None
    assert incomplete(Listing("dcim.device", 3, (D1, D2, D3)), asked={"d1", "d2", "d3"}) is None


def test_a_list_short_of_its_count_is_incomplete() -> None:
    finding = incomplete(Listing("dcim.device", 3, (D1, D2)))
    assert finding is not None
    assert (finding.rule, finding.severity, finding.object) == (RULE_INCOMPLETE, "error", "dcim.device")
    assert RULE_INCOMPLETE == "read.incomplete"
    for held in ("counted 3", "answered 2"):
        assert held in finding.message


def test_a_list_longer_than_its_count_is_incomplete() -> None:
    port = Port("i1", "d1", "ethernet-1/1", "25gbase-x-sfp28", True, False, None)
    finding = incomplete(Listing("dcim.interface", 0, (port,)))
    assert finding is not None
    assert (finding.rule, finding.severity, finding.object) == (RULE_INCOMPLETE, "error", "dcim.interface")
    for held in ("counted 0", "answered 1"):
        assert held in finding.message


def test_an_object_twice_is_incomplete() -> None:
    finding = incomplete(Listing("dcim.device", 2, (D1, D1)))
    assert finding is not None
    assert (finding.rule, finding.severity, finding.object) == (RULE_INCOMPLETE, "error", "dcim.device")
    for held in ("counted 2", "answered 2", "1 of them"):
        assert held in finding.message


def test_an_id_asked_for_and_not_answered_is_incomplete() -> None:
    finding = incomplete(Listing("dcim.platform", 1, (D1,)), asked={"d1", "d2"})
    assert finding is not None
    assert (finding.rule, finding.severity, finding.object) == (RULE_INCOMPLETE, "error", "dcim.platform")
    for held in ("counted 1", "answered 1", "1 of the 2 ids", "id d2"):
        assert held in finding.message


def test_an_empty_list_of_count_zero_is_whole() -> None:
    assert incomplete(Listing("dcim.cable", 0, ())) is None
    assert incomplete(Listing("dcim.cable", 0, ()), asked=set()) is None


def test_the_fake_is_a_source() -> None:
    source: Source = three_node()
    tag = source.tags("fylgja").items[0]
    assert tag == Tag(tag.id, "fylgja")
    assert source.devices(tag).count == 3
