"""The OSPF adjacency check's pure parts: every link end of the bundle expected FULL, each device's two answers parsed
as SR Linux gives them (tests/nornir/answers/, captured from a running node), and the judgement, in which a silent
instance, a state short of FULL, an unread node and a bundle with no links are each a failure, so nothing passes
vacuously."""

from __future__ import annotations

from pathlib import Path

from fylgja_orchestrator.nornir import ospf
from fylgja_orchestrator.nornir.ospf import (
    COMMANDS,
    RULE_ABSENT,
    RULE_NO_LINKS,
    RULE_NOT_FULL,
    RULE_UNREAD,
    Unread,
    expected,
    judge,
    parse,
)

ANSWERS = Path(__file__).resolve().parent / "answers"
BUNDLE = {
    "nodes": [{"name": "n1", "platform": "nokia_srlinux"}, {"name": "n2", "platform": "nokia_srlinux"}],
    "links": [{"a": {"device": "n2", "interface": "ethernet-1/1"}, "b": {"device": "n1", "interface": "ethernet-1/1"}}],
}
ENDS = [("n1", "ethernet-1/1"), ("n2", "ethernet-1/1")]


def _answer(name: str) -> str:
    return (ANSWERS / name).read_text()


FULL = {"ethernet-1/1": "full"}


def test_the_commands_are_the_oper_state_read_then_the_adjacency_read() -> None:
    oper, adjacency = COMMANDS
    assert oper.endswith("ospf instance main oper-state | as json")
    assert adjacency.endswith("area * interface * neighbor * adjacency-state | as json")


def test_expected_is_both_ends_of_every_link_sorted() -> None:
    assert expected(BUNDLE) == ENDS


def test_parse_reads_each_interfaces_state_without_its_subinterface() -> None:
    assert parse(_answer("oper.json"), _answer("full.json")) == FULL


def test_parse_answers_empty_for_an_instance_with_no_neighbour() -> None:
    assert parse(_answer("oper.json"), _answer("no-neighbour.json")) == {}


def test_parse_answers_none_for_a_node_without_ospf() -> None:
    assert parse(_answer("absent.json"), _answer("no-neighbour.json")) is None


def test_all_full_is_no_failure() -> None:
    assert judge(ENDS, ["n1", "n2"], {"n1": FULL, "n2": FULL}) == []


def test_a_missing_neighbour_names_the_end() -> None:
    found = judge(ENDS, ["n1", "n2"], {"n1": FULL, "n2": {}})
    assert [(f["rule"], f["object"]) for f in found] == [(RULE_NOT_FULL, "n2:ethernet-1/1")]
    assert found[0]["severity"] == "error"
    assert "no neighbour" in found[0]["message"]


def test_a_state_short_of_full_names_the_state() -> None:
    for state in ("exchange", "two-way", "init"):
        found = judge(ENDS, ["n1", "n2"], {"n1": FULL, "n2": {"ethernet-1/1": state}})
        assert [(f["rule"], f["object"]) for f in found] == [(RULE_NOT_FULL, "n2:ethernet-1/1")]
        assert state in found[0]["message"]


def test_a_node_without_an_instance_fails_itself_and_not_its_ends() -> None:
    found = judge(ENDS, ["n1", "n2"], {"n1": FULL, "n2": None})
    assert [(f["rule"], f["object"]) for f in found] == [(RULE_ABSENT, "n2")]


def test_an_unread_node_is_said_and_the_other_end_still_judged() -> None:
    found = judge(ENDS, ["n1", "n2"], {"n1": Unread("timed out"), "n2": {}})
    assert [(f["rule"], f["object"]) for f in found] == [(RULE_UNREAD, "n1"), (RULE_NOT_FULL, "n2:ethernet-1/1")]
    assert "timed out" in found[0]["message"]


def test_a_device_with_no_answer_at_all_is_unread() -> None:
    found = judge(ENDS, ["n1", "n2"], {"n1": FULL})
    assert [(f["rule"], f["object"]) for f in found] == [(RULE_UNREAD, "n2")]


def test_no_links_cannot_pass() -> None:
    assert [f["rule"] for f in judge([], ["n1"], {"n1": FULL})] == [RULE_NO_LINKS]
    assert "object" not in judge([], ["n1"], {"n1": FULL})[0]


def test_every_rule_is_an_error() -> None:
    rules = {value for name, value in vars(ospf).items() if name.startswith("RULE_")}
    assert set(ospf.SEVERITY) == rules and set(ospf.SEVERITY.values()) == {"error"}
