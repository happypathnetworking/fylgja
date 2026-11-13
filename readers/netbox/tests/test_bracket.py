"""The bracket (D-095): a read is of one state where the changelog it reads from holds, between the latest id taken at
its open and the one taken at its close, no row of a kind a read reads, and where the branch it reads was not synced,
since a sync adds no row to either changelog (design/verified-facts.md, "NetBox 4.7.5 with netbox-branching 1.2.3").
Over rows built in the tests and `FakeSource`, never NetBox's answers (D-034)."""

from __future__ import annotations

import pytest
from fake import listing, three_node

from fylgja_netbox import NetBoxError, bracket
from fylgja_netbox.bracket import RULE_MOVED, UNREAD, Mark, branch_moved, close, mark, moved
from fylgja_netbox.rows import RULE_INCOMPLETE, Branch, Change

BRANCH = Branch(7, "b", "p9d46y7z", "ready", "2026-11-12T16:30:00.115200Z")


def test_nothing_moved_is_no_finding() -> None:
    assert moved(7, 7, (), branch="b") is None
    assert moved(None, None, (), branch=None) is None


def test_a_row_a_read_reads_is_moved() -> None:
    between = (Change(8, "dcim.interface"), Change(9, "extras.journalentry"))
    found = moved(7, 9, between, branch="b")
    assert found is not None
    assert (found.rule, found.severity, found.object) == ("read.moved", "error", "b")
    for said in ("branch b", "7", "9", "dcim.interface", "read again"):
        assert said in found.message, said
    assert "extras.journalentry" not in found.message
    assert found.message.endswith("read again.")

    on_main = moved(7, 9, between, branch=None)
    assert on_main is not None
    assert on_main.object == "main"
    assert "main" in on_main.message


def test_rows_no_read_reads_do_not_count() -> None:
    assert UNREAD == ("extras.journalentry", "netbox_branching.branch")
    between = tuple(Change(8 + number, kind) for number, kind in enumerate(UNREAD))
    assert moved(7, 9, between, branch="b") is None
    assert moved(7, 9, between, branch=None) is None


def test_a_first_row_is_moved() -> None:
    found = moved(None, 3, (Change(3, "dcim.cable"),), branch="b")
    assert found is not None
    assert found.rule == RULE_MOVED
    assert "none" in found.message and "3" in found.message and "dcim.cable" in found.message


def test_an_id_that_moved_with_no_row_listed_is_moved() -> None:
    for before, after in ((7, 9), (7, None)):
        found = moved(before, after, (), branch="b")
        assert found is not None, (before, after)
        assert found.rule == RULE_MOVED
        assert "7" in found.message and ("9" if after else "none") in found.message
        assert found.message.endswith("read again.")


def test_a_kind_netbox_adds_later_counts() -> None:
    found = moved(7, 8, (Change(8, "dcim.newthing"),), branch="b")
    assert found is not None
    assert "dcim.newthing" in found.message


def test_the_kinds_are_counted_and_sorted() -> None:
    between = (Change(8, "dcim.interface"), Change(9, "dcim.cable"), Change(10, "dcim.interface"))
    found = moved(7, 10, between, branch="b")
    assert found is not None
    assert "3 rows" in found.message
    assert found.message.index("dcim.cable") < found.message.index("dcim.interface")


def test_a_row_above_the_close_is_not_between() -> None:
    """A row written after the close was taken is no edit under the read: what the read holds was read before it."""
    between = (Change(8, "extras.journalentry"), Change(11, "dcim.interface"))
    assert moved(7, 8, between, branch="b") is None


def test_a_branch_synced_or_no_longer_ready_is_moved() -> None:
    """A sync adds no row to either changelog and changes what the branch reads, so the branch is read again at the
    close: gone, not `ready`, or its `last_sync` moved is `read.moved`; as it was is nothing."""
    assert branch_moved(BRANCH, listing("netbox_branching.branch", [BRANCH])) is None

    synced = Branch(7, "b", "p9d46y7z", "ready", "2026-11-12T16:30:02.487998Z")
    syncing = Branch(7, "b", "p9d46y7z", "syncing", BRANCH.last_sync)
    again = Branch(8, "b", "q1w2e3r4", "ready", BRANCH.last_sync)
    cases = [
        ([synced], ("last_sync", "2026-11-12T16:30:00.115200Z", "2026-11-12T16:30:02.487998Z")),
        ([syncing], ("syncing",)),
        ([], ("no branch b",)),
        ([again], ("no branch b",)),
    ]
    for rows, phrases in cases:
        found = branch_moved(BRANCH, listing("netbox_branching.branch", rows))
        assert found is not None, rows
        assert (found.rule, found.severity, found.object) == (RULE_MOVED, "error", "b")
        assert "branch b" in found.message
        for phrase in phrases:
            assert phrase in found.message, (rows, phrase)
        assert found.message.endswith("read again.")


def test_rows_that_lack_the_close_id_are_moved() -> None:
    """The row of the id taken at the close is the read's proof that every row up to it was listed: rows of `UNREAD`
    alone, without it, refuse."""
    found = moved(7, 9, (Change(8, "extras.journalentry"),), branch="b")
    assert found is not None
    assert found.rule == RULE_MOVED
    assert "9" in found.message and found.message.endswith("read again.")


def test_the_open_marks_the_latest_id_and_the_rows_at_or_below_it() -> None:
    conn = three_node()
    conn.latests = [7]
    conn.counts = [5]
    assert mark(conn, BRANCH) == Mark(7, 5, BRANCH.schema_id)
    assert conn.calls == [("latest", "b"), ("counted", "b")]

    conn = three_node()
    conn.latests = [None]
    assert mark(conn, None) == Mark(None, 0, None)
    assert conn.calls == [("latest", None)]


def test_the_close_reads_the_branch_then_the_changelog() -> None:
    conn = three_node()
    conn.held_branches = listing("netbox_branching.branch", [BRANCH])
    conn.latests = [9]
    conn.counts = [5]
    conn.changed = (Change(8, "dcim.interface"), Change(9, "dcim.interface"))
    after, found = close(conn, BRANCH, Mark(7, 5, BRANCH.schema_id))
    assert after == 9
    assert [(f.rule, f.object) for f in found] == [(RULE_MOVED, "b")]
    assert conn.calls == [("branches", None), ("latest", "b"), ("changes", "b"), ("counted", "b")]


def test_the_close_of_a_read_that_did_not_move_lists_no_change() -> None:
    conn = three_node()
    conn.latests = [7]
    conn.counts = [5]
    assert close(conn, None, Mark(7, 5, None)) == (7, ())
    assert conn.calls == [("latest", None), ("counted", None)]

    conn = three_node()
    conn.latests = [9]
    conn.counts = [5]
    conn.changed = (Change(8, "extras.journalentry"), Change(9, "netbox_branching.branch"))
    assert close(conn, None, Mark(7, 5, None)) == (9, ())
    assert conn.calls == [("latest", None), ("changes", None), ("counted", None)]


def test_a_short_list_of_the_changes_is_incomplete() -> None:
    """A list answered short of its `count` may lack the very row that refuses the read: it is `read.incomplete`."""
    conn = three_node()
    conn.latests = [9]
    conn.counts = [5]
    conn.changed = (Change(9, "extras.journalentry"),)
    conn.changed_count = 2
    after, found = close(conn, None, Mark(7, 5, None))
    assert after == 9
    assert [(f.rule, f.object) for f in found] == [(RULE_INCOMPLETE, "core.objectchange")]


def test_a_row_written_below_the_open_id_after_the_open_is_moved() -> None:
    """A row whose id is below the one the open read, committed after it, moves no latest id: the count of the rows at
    or below the open's id does. Unmoved, it is nothing."""
    conn = three_node()
    conn.latests = [7]
    conn.counts = [6]
    after, found = close(conn, None, Mark(7, 5, None))
    assert after == 7
    assert [(f.rule, f.object) for f in found] == [(RULE_MOVED, "main")]
    for said in ("main", "7", "5", "6", "read again"):
        assert said in found[0].message, said

    conn = three_node()
    conn.latests = [7]
    conn.counts = [5]
    assert close(conn, None, Mark(7, 5, None)) == (7, ())

    conn = three_node()
    conn.latests = [7]
    conn.counts = [2]
    after, found = close(conn, None, Mark(7, 1, None))
    assert "held 1 row at or below its id 7" in found[0].message
    assert "1 rows" not in found[0].message


def test_the_branch_read_at_the_close_is_held_to_its_count() -> None:
    """A list of the branches of the name short of its `count` may lack the branch read: `read.incomplete`, as at the
    branch's first read, and nothing more is asked."""
    conn = three_node()
    conn.held_branches = listing("netbox_branching.branch", [BRANCH], count=2)
    after, found = close(conn, BRANCH, Mark(7, 5, BRANCH.schema_id))
    assert after is None
    assert [(f.rule, f.object) for f in found] == [(RULE_INCOMPLETE, "netbox_branching.branch")]
    assert "branch b" in found[0].message
    assert conn.calls == [("branches", None)]


@pytest.mark.parametrize("call", ["latest", "changes", "counted"])
def test_a_400_to_the_closes_own_requests_under_a_branch_is_moved(call: str) -> None:
    """A sync, a merge or a delete that begins after the close has read the branch again answers the close's requests
    under the branch's header 400, as NetBox answers every request under the header of a branch deleted, syncing or
    merged (design/verified-facts.md): `read.moved`, quoting NetBox's words, and no close id."""
    refused = NetBoxError("reading core.objectchange (branch b): HTTP 400: Selected branch is not ready.", 400)
    conn = three_node()
    conn.held_branches = listing("netbox_branching.branch", [BRANCH])
    conn.latests = [9]
    conn.counts = [5]
    conn.changed = (Change(8, "extras.journalentry"), Change(9, "extras.journalentry"))
    conn.raising = {call: refused}
    after, found = close(conn, BRANCH, Mark(7, 5, BRANCH.schema_id))
    assert after is None
    assert [(f.rule, f.severity, f.object) for f in found] == [(RULE_MOVED, "error", "b")]
    for said in ("branch b", "HTTP 400", "Selected branch is not ready", "read again"):
        assert said in found[0].message, said
    assert found[0].message.endswith("read again.")


def test_a_400_to_the_close_of_main_and_another_refusal_pass_through() -> None:
    """On `main` no header is sent, so a 400 is no branch moved: it is raised as it came, as is any other status under
    a branch's header."""
    for opened, refused in (
        (None, NetBoxError("reading core.objectchange (main): HTTP 400: x", 400)),
        (BRANCH, NetBoxError("reading core.objectchange (branch b): HTTP 500: Server Error", 500)),
    ):
        conn = three_node()
        conn.held_branches = listing("netbox_branching.branch", [BRANCH])
        conn.latests = [9]
        conn.raising = {"changes": refused}
        schema_id = opened.schema_id if opened is not None else None
        with pytest.raises(NetBoxError) as raised:
            close(conn, opened, Mark(7, 5, schema_id))
        assert raised.value is refused


def test_the_close_of_a_branch_that_moved_reads_no_changelog_under_its_header() -> None:
    """Under the header of a branch that is syncing or merged NetBox answers 400 `Selected branch is not ready.`, so
    the close asks nothing more once the branch has moved."""
    conn = three_node()
    conn.held_branches = listing("netbox_branching.branch", [Branch(7, "b", "p9d46y7z", "syncing", BRANCH.last_sync)])
    after, found = close(conn, BRANCH, Mark(7, 5, BRANCH.schema_id))
    assert after is None
    assert [f.rule for f in found] == [RULE_MOVED]
    assert conn.calls == [("branches", None)]


def test_the_fake_answers_its_latest_ids_and_counts_in_order_then_the_last_again() -> None:
    conn = three_node()
    conn.latests = [None, 3, 5]
    conn.counts = [0, 2]
    assert [conn.latest(None) for _ in range(5)] == [None, 3, 5, 5, 5]
    assert [conn.counted(None, 3) for _ in range(3)] == [0, 2, 2]
    assert bracket.RULE_MOVED == "read.moved"


def test_a_mark_closes_only_the_changelog_it_was_taken_of() -> None:
    """A `Mark` holds the changelog it was taken of, `main`'s or a branch's by its `schema_id`, and a close against
    another is a caller's mistake, refused before any request: it would compare two changelogs."""
    other = Branch(8, "c", "q1w2e3r4", "ready", None)
    for opened, before in (
        (BRANCH, Mark(7, 5, None)),
        (None, Mark(7, 5, BRANCH.schema_id)),
        (other, Mark(7, 5, BRANCH.schema_id)),
    ):
        conn = three_node()
        with pytest.raises(ValueError, match="changelog"):
            close(conn, opened, before)
        assert conn.calls == []
