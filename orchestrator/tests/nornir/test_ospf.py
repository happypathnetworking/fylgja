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


# A check that cannot run answers findings, never an exception: a rehearsal's every path ends in its document.

RECORD = {"status": {"nodes": [{"name": "n1", "handle": "h1", "address": "192.0.2.11"},
                               {"name": "n2", "handle": "h2", "address": "192.0.2.12"}]}}
ROOT = Path(__file__).resolve().parents[3]
LOGIN = {"FYLGJA_CREDENTIAL_SRLINUX_USERNAME": "admin", "FYLGJA_CREDENTIAL_SRLINUX_PASSWORD": "s3cret"}


def test_a_login_not_set_is_every_device_unread_and_names_the_variable() -> None:
    found = ospf.check(ROOT / "psp", {})(RECORD, BUNDLE, 1.0)
    assert [(f["rule"], f["object"]) for f in found] == [(RULE_UNREAD, "n1"), (RULE_UNREAD, "n2")]
    assert "FYLGJA_CREDENTIAL_SRLINUX_USERNAME is not set" in found[0]["message"]


def test_a_package_not_found_is_every_device_unread(tmp_path: Path) -> None:
    found = ospf.check(tmp_path, LOGIN)(RECORD, BUNDLE, 1.0)
    assert [(f["rule"], f["object"]) for f in found] == [(RULE_UNREAD, "n1"), (RULE_UNREAD, "n2")]
    assert "FileNotFoundError" in found[0]["message"]
    assert all("s3cret" not in f["message"] for f in found)


class _Response:
    def __init__(self, result: str) -> None:
        self.result = result


class _Host:
    """One host's MultiResult as Nornir answers it: `failed`, `exception`, and its first result's responses."""

    def __init__(self, *texts: str, failed: bool = False, exception: BaseException | None = None) -> None:
        self.failed, self.exception = failed, exception
        self.scrapli_response = [_Response(text) for text in texts]

    def __getitem__(self, index: int) -> _Host:
        return self


def test_each_hosts_answers_are_parsed_and_a_failed_or_garbled_one_is_unread() -> None:
    result = {
        "n1": _Host(_answer("oper.json"), _answer("full.json")),
        "n2": _Host(failed=True, exception=TimeoutError("timed out")),
        "n3": _Host("not json", "{}"),
    }
    answers = ospf.answered(result)
    assert answers["n1"] == FULL
    assert answers["n2"] == Unread("TimeoutError: timed out")
    n3 = answers["n3"]
    assert isinstance(n3, Unread) and n3.reason.startswith("JSONDecodeError")
