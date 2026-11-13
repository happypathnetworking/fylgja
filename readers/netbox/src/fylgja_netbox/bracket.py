"""The bracket: a read is of one state, or refused (D-095).

NetBox reads no earlier time, and a read is tens of requests with no instant in common, so an edit made between two of
them gives a blueprint of a network that never was. The read marks the changelog it reads from, `main`'s or the
branch's, at its open, before its first list (`mark`), and again at its close, after its last render (`close`). Two
comparisons guard it:

- **The latest id.** Where it moved and the changelog holds above the open's id, and at or below the close's, a row of
  a kind a read reads, the read is refused, `read.moved`, with the remedy: read again. The rows of `UNREAD`, a journal
  entry's and the branch object's own, which the example writes while a branch is rehearsed, refuse nothing; any other
  kind does, one NetBox adds later among them. The rows are listed whole, held to their `count` (`read.incomplete`),
  and must reach the row of the close's id. The ids are not dense (design/verified-facts.md, "NetBox 4.7.5 with
  netbox-branching 1.2.3"), so the latest ids are compared, never the count of the whole changelog.
- **The rows at or below the open's id.** A row of a lower id that commits after the open moves no latest id, so the
  open also counts the rows at or below its id, by `id__lte`, which NetBox honours (the same facts, "An upper bound on
  the id"), and the close counts them again: a difference is `read.moved`. This is the one count compared, of the rows
  below a fixed id. A late row of a kind no read reads refuses the read too, its kind not being listed. A row pruned
  from the changelog at or below the open's id during the read, which NetBox's retention of its changelog would do,
  takes one from that count as a late row adds one, so the two cancel and that pair is not seen: nothing was read of
  that retention.

A sync of a branch changes what the branch reads and adds no row to either changelog (the same facts, "A sync"), so a
branch is read again at the close, its list held to its `count`: one that NetBox no longer lists, that is no longer
`ready`, or whose `last_sync` moved is `read.moved` too. A sync, a merge or a delete that begins after that read
answers the close's own requests under the branch's header 400, as NetBox answers every request under the header of a
branch deleted, syncing or merged, so such a 400 is `read.moved` as well, quoting NetBox's words. `close` is the whole
close, for the read's end and for a request by an id the read itself listed that NetBox refuses 400, an object deleted
under the read showing so.

What is not guarded: what a template renders of a device's own journal entries, a journal entry's row refusing nothing;
and what lives on `main` alone and is not branched, the reader account's permissions among them, since a branch's read
marks the branch's changelog and not `main`'s.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from fylgja_core.findings import Finding

from fylgja_netbox.rows import Branch, Change, Listing, Source, incomplete
from fylgja_netbox.transport import NetBoxError

# Rule ids. Callers and tests match on them (rules.md).
RULE_MOVED = "read.moved"

UNREAD: tuple[str, ...] = ("extras.journalentry", "netbox_branching.branch")
"""The kinds of the changelog's rows that no read reads: a journal entry's, written, changed or deleted on a branch,
and the branch object's own, made, edited or deleted, each of which adds its row to `main`'s changelog alone
(design/verified-facts.md, "The kinds of a changelog's rows")."""

AGAIN = "read again"
"""The remedy every `read.moved` ends in."""

REFUSED = 400
"""NetBox's status for every request under the header of a branch deleted, syncing or merged."""


def _where(branch: str | None) -> str:
    return f"branch {branch}" if branch is not None else "main"


def _id(found: int | None) -> str:
    return "none" if found is None else str(found)


def _rows(count: int) -> str:
    return f"{count} row{'s' if count != 1 else ''}"


def moved(before: int | None, after: int | None, between: Sequence[Change], *, branch: str | None) -> Finding | None:
    """`read.moved` where the changelog's latest id `after`, taken at the close, is not `before`, taken at the open,
    unless `between`, the rows listed above `before`, holds the row of the id `after` and every row at or below it is
    of a kind in `UNREAD`; None where nothing moved. A row above `after` was written after the close, under no part of
    the read; the row of `after` among them is the proof that the list reached the close. `branch` is the name of the
    branch read, None for `main`, and the finding's object."""
    if after == before:
        return None
    under = [change for change in between if after is None or change.id <= after]
    counted = sorted(change.kind for change in under if change.kind not in UNREAD)
    reached = after is not None and any(change.id == after for change in under)
    if reached and not counted:
        return None
    where = _where(branch)
    opened = f"its latest id {_id(before)} at the read's open and {_id(after)} at its close"
    if counted:
        kinds = ", ".join(sorted(set(counted)))
        rows = f"{_rows(len(counted))} of a kind a read reads between them ({kinds})"
    elif under:
        rows = f"no row of the close's id {_id(after)} among the rows listed above {_id(before)}"
    else:
        rows = f"no row listed above {_id(before)}"
    return Finding(
        rule=RULE_MOVED,
        severity="error",
        object=branch if branch is not None else "main",
        message=(
            f"The changelog of {where} moved during the read, {opened}, with {rows}, so the read may hold two states "
            f"of {where}: {AGAIN}."
        ),
    )


def branch_moved(opened: Branch, found: Listing[Branch]) -> Finding | None:
    """`read.moved` where `found`, the branches NetBox lists by `opened`'s name at the close, holds no branch of
    `opened`'s id, or holds it no longer `ready`, or synced, its `last_sync` moved; None where it is as it was."""
    where = _where(opened.name)
    same = [branch for branch in found.items if branch.id == opened.id]
    if len(same) != 1:
        said = f"NetBox lists no branch {opened.name} of the id {opened.id} at the read's close"
    elif same[0].status != "ready":
        said = f"Branch {opened.name} is {same[0].status} at the read's close, where it was {opened.status} at its open"
    elif same[0].last_sync != opened.last_sync:
        said = (
            f"Branch {opened.name} was synced during the read, its last_sync {opened.last_sync or 'none'} at the "
            f"read's open and {same[0].last_sync or 'none'} at its close, and a sync adds no row to its changelog"
        )
    else:
        return None
    return Finding(
        rule=RULE_MOVED,
        severity="error",
        object=opened.name,
        message=f"{said}, so the read may hold two states of {where}: {AGAIN}.",
    )


def reread(conn: Source, opened: Branch) -> Finding | None:
    """The branch `opened` read again by its name, under no branch's header: `read.incomplete`, object
    `netbox_branching.branch`, where NetBox's list of that name is not whole, since whether the branch moved cannot
    then be told; else `branch_moved`'s finding, None where the branch is as it was."""
    listed = conn.branches(opened.name)
    return incomplete(listed, branch=opened.name) or branch_moved(opened, listed)


def refused(opened: Branch, error: NetBoxError) -> Finding:
    """`read.moved` for a 400 NetBox answered a request of the close under the header of the branch `opened`, which it
    answers under the header of a branch deleted, syncing or merged: `error`'s text, which quotes NetBox's words as
    text, cut and with no token (transport.py), is quoted."""
    said = str(error).rstrip(".")
    return Finding(
        rule=RULE_MOVED,
        severity="error",
        object=opened.name,
        message=(
            f"NetBox refused a request of the read's close under the header of branch {opened.name} ({said}), as it "
            f"refuses one under the header of a branch deleted, syncing or merged, so the read may hold two states of "
            f"branch {opened.name}: {AGAIN}."
        ),
    )


@dataclass(frozen=True)
class Mark:
    """What the open takes of the changelog read from: its latest id, None where it holds no row; how many rows it
    holds at or below that id, 0 where it holds none; and which changelog it is, the `schema_id` of the branch whose
    changelog it was taken of, None for `main`'s, so that a close compares one changelog with itself."""

    id: int | None
    below: int
    schema_id: str | None


def mark(conn: Source, branch: Branch | None) -> Mark:
    """The open's `Mark` of the changelog `branch` reads from, `main`'s where it is None: the latest id, then the count
    of the rows at or below it, which is not asked where the changelog holds no row."""
    latest = conn.latest(branch)
    below = conn.counted(branch, latest) if latest is not None else 0
    return Mark(latest, below, branch.schema_id if branch is not None else None)


def shifted(before: Mark, below: int, *, branch: str | None) -> Finding | None:
    """`read.moved` where `below`, the rows the changelog holds at the close at or below the id the open took, is not
    the count the open took: a row of a lower id committed after the open, which moves no latest id. This is the one
    count the bracket compares, and it is of the rows below a fixed id, never of the whole changelog; None where it is
    the same, or where the open took no id."""
    if before.id is None or below == before.below:
        return None
    where = _where(branch)
    return Finding(
        rule=RULE_MOVED,
        severity="error",
        object=branch if branch is not None else "main",
        message=(
            f"The changelog of {where} held {_rows(before.below)} at or below its id {before.id} at the read's open "
            f"and {below} at its close, a row written below that id during the read, so the read may hold two states "
            f"of {where}: {AGAIN}."
        ),
    )


def close(conn: Source, opened: Branch | None, before: Mark) -> tuple[int | None, tuple[Finding, ...]]:
    """The read's close: the latest id of the changelog read from, and the findings the read is refused by, none where
    it is of one state. `opened` is the branch as the read found it at its open, None for `main`, and `before` the
    open's `mark`, which must be of the changelog `opened` reads from: a `Mark` of another is a `ValueError`, raised
    before any request. A branch is read again first (`reread`), and where it moved, or its list is not whole, nothing
    more is asked: under the header of a branch syncing or merged NetBox answers 400 (design/verified-facts.md, "A
    sync"), and the close id is then None. The rows above the open's id are listed only where the latest id moved; the
    rows at or below the open's id are counted again where the open took an id.

    The findings are `read.moved`, of the branch, of the rows listed or of the count, and `read.incomplete`, object
    `core.objectchange`, where the rows listed are short of their count, or `netbox_branching.branch`, where the
    branch's list is: one may be filed without the other, so a close can refuse a read by `read.incomplete` alone, a
    list not whole, of which it cannot tell whether it moved.

    A 400 NetBox answers `latest`, `changes` or `counted` under a branch's header is `read.moved` alone (`refused`), and
    the close id None: a sync, a merge or a delete that begins after the branch's read answers them so. On `main` no
    header is sent, and a 400 there, like any other `NetBoxError`, passes through.

    Called after the last render, and again where NetBox refuses 400 a request by an id the read took from its own
    earlier answer; read.py says what the read does with each answer the close gives there."""
    held = opened.schema_id if opened is not None else None
    if before.schema_id != held:
        taken = f"the branch whose schema_id is {before.schema_id}" if before.schema_id is not None else "main"
        asked = f"branch {opened.name}" if opened is not None else "main"
        raise ValueError(f"close was given a Mark of the changelog of {taken} for a read of {asked}, another changelog")
    if opened is not None:
        left = reread(conn, opened)
        if left is not None:
            return None, (left,)
    name = opened.name if opened is not None else None
    found: list[Finding | None] = []
    try:
        after = conn.latest(opened)
        if after != before.id:
            listed = conn.changes(opened, before.id)
            found += [incomplete(listed, branch=name), moved(before.id, after, listed.items, branch=name)]
        if before.id is not None:
            found.append(shifted(before, conn.counted(opened, before.id), branch=name))
    except NetBoxError as e:
        if e.status != REFUSED or opened is None:
            raise
        return None, (refused(opened, e),)
    return after, tuple(finding for finding in found if finding is not None)
