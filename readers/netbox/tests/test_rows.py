"""Every list NetBox answers is held to the `count` it gave for it (D-095): a list short of its `count`, longer than
it, holding one object twice, or lacking an id it was asked for by id is `read.incomplete`, an error, and never
mapped."""

from __future__ import annotations

from fake import three_node

from fylgja_netbox.rows import RULE_INCOMPLETE, Device, Listing, Port, Source, incomplete


def device(id: int, name: str) -> Device:
    return Device(id, name, 1)


D1, D2, D3 = device(1, "n1"), device(2, "n2"), device(3, "n3")


def test_a_whole_list_has_no_finding() -> None:
    assert incomplete(Listing("dcim.device", 3, (D1, D2, D3)), branch="b") is None
    assert incomplete(Listing("dcim.device", 3, (D1, D2, D3)), branch=None, asked={1, 2, 3}) is None


def test_a_list_short_of_its_count_is_incomplete() -> None:
    finding = incomplete(Listing("dcim.device", 3, (D1, D2)), branch="b")
    assert finding is not None
    assert (finding.rule, finding.severity, finding.object) == (RULE_INCOMPLETE, "error", "dcim.device")
    assert RULE_INCOMPLETE == "read.incomplete"
    for held in ("counted 3", "answered 2", "branch b"):
        assert held in finding.message
    on_main = incomplete(Listing("dcim.device", 3, (D1, D2)), branch=None)
    assert on_main is not None
    assert "main" in on_main.message
    assert "branch" not in on_main.message


def test_a_list_longer_than_its_count_is_incomplete() -> None:
    port = Port(7, 1, "ethernet-1/1", "25gbase-x-sfp28", True, False, None)
    finding = incomplete(Listing("dcim.interface", 0, (port,)), branch="b")
    assert finding is not None
    assert (finding.rule, finding.severity, finding.object) == (RULE_INCOMPLETE, "error", "dcim.interface")
    for held in ("counted 0", "answered 1", "branch b"):
        assert held in finding.message


def test_an_object_twice_is_incomplete() -> None:
    finding = incomplete(Listing("dcim.device", 2, (D1, D1)), branch="b")
    assert finding is not None
    assert (finding.rule, finding.severity, finding.object) == (RULE_INCOMPLETE, "error", "dcim.device")
    for held in ("counted 2", "answered 2", "1 of them", "branch b"):
        assert held in finding.message


def test_an_id_asked_for_and_not_answered_is_incomplete() -> None:
    finding = incomplete(Listing("dcim.platform", 1, (D1,)), branch="b", asked={1, 2})
    assert finding is not None
    assert (finding.rule, finding.severity, finding.object) == (RULE_INCOMPLETE, "error", "dcim.platform")
    for held in ("counted 1", "answered 1", "1 of the 2 ids", "id 2", "branch b"):
        assert held in finding.message


def test_an_empty_list_of_count_zero_is_whole() -> None:
    assert incomplete(Listing("dcim.cable", 0, ()), branch="b") is None
    assert incomplete(Listing("dcim.cable", 0, ()), branch=None, asked=set()) is None


def test_the_fake_is_a_source() -> None:
    source: Source = three_node()
    assert source.devices(None, 1).count == 3
