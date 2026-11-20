"""The bracket: a read is of one state, or refused (D-118).

Nautobot reads no earlier time, and a read is tens of requests with no instant in common, so an edit made between two of
them gives a blueprint of a network that never was. The changelog's rows are keyed by UUIDs, so no id orders them, and
the NetBox reader's bracket by the latest id has no counterpart here. The read marks Nautobot at its open, before
anything else is listed (`mark`), and again at its close, after its last render (`close`), and compares the two
(`moved`):

- **The newest row.** Nautobot lists its changelog newest first, and `?limit=1` answers the newest row and the total
  count in one request. A newest row at the close that is not the open's, by its id, is a row written during the read:
  a newer one, or another of the same time, to the microsecond. A changelog with no row opens with none, and any row
  at the close refuses the read.
- **The count.** A row written inside a longer transaction becomes visible only at its commit, carrying the time it
  was written (design/verified-facts.md, "Nautobot 3.2.8 with Golden Config 3.0.8", "The bracket"): a mark taken
  meanwhile does not see it, though it is older than the mark. Where a row of a later time, of a shorter transaction,
  was visible already, the late row moves no newest row; it moves the count, so a count at the close that is not the
  open's is `read.moved` too. A row pruned takes one from the count as a late row adds one, so the two cancel and that
  pair is not seen.
- **The heads.** Inside the bracket the open lists Golden Config's settings, whole, and the template repositories
  they name, by their ids, and takes each repository's `current_head`; the close lists those repositories again. A
  head that moved, or a repository no longer listed, is `read.moved`, object the repository's name: the renders may
  be of two commits.

Every kind of row counts, since nothing of Fylgja's writes to Nautobot, the row a render writes when it fetches a moved
head among them: the renders before it used the older templates. So a read is refused at most once after a push to a
template repository, and the next read finds the head already fetched. Each `read.moved` gives both values, and ends in
the remedy, read again; the reader does not read again by itself.

What the bracket does not see: a row pruned while another becomes visible late, which cancel in the count; and a
refresh of a dynamic group's stored members by the job `RefreshDynamicGroupCaches`, which writes no changelog row. The
read holds the stored members to the group's filter when it lists them, inside the bracket (groups.py), so a
membership stale then refuses the read, by `group.stale`, whose remedy is that refresh.
"""

from __future__ import annotations

from dataclasses import dataclass

from fylgja_core.findings import Finding

from fylgja_nautobot.rows import Change, Repository, Setting, Source, incomplete

# Rule ids. Callers and tests match on them (rules.md).
RULE_MOVED = "read.moved"

AGAIN = "read again"
"""The remedy every `read.moved` ends in."""

CHANGELOG = "extras.objectchange"
"""The object a `read.moved` of the changelog names."""

Head = tuple[str, str, str]
"""A template repository's id, its name and its `current_head`."""


@dataclass(frozen=True)
class Mark:
    """What the bracket takes of Nautobot: the changelog's total `count`; its `newest` row, None where it holds none;
    and each template repository's id, name and `current_head` in `heads`, sorted by name, then id."""

    count: int
    newest: Change | None
    heads: tuple[Head, ...]


def _rows(count: int) -> str:
    return f"{count} row{'s' if count != 1 else ''}"


def _row(change: Change) -> str:
    return f"{change.id} of {change.time}"


def _head(head: str) -> str:
    return head or "empty"


def _changelog(before: Mark, after: Mark) -> Finding | None:
    """`read.moved` of the changelog where its newest row or its count at the close differs from the open's; None
    where both are the same."""
    if before.newest == after.newest and before.count == after.count:
        return None
    if before.newest == after.newest:
        newest = _row(before.newest) if before.newest is not None else "none"
        said = (
            f"held {_rows(before.count)} at the read's open and {after.count} at its close, its newest row {newest} "
            "at both, a row of an earlier time seen late or one pruned"
        )
    elif before.newest is None:
        assert after.newest is not None
        said = f"held no row at the read's open and {_rows(after.count)} at its close, the newest {_row(after.newest)}"
    elif after.newest is None:
        said = (
            f"held {_rows(before.count)} at the read's open, the newest {_row(before.newest)}, and no row at its "
            "close"
        )
    else:
        said = (
            f"moved during the read, its newest row {_row(before.newest)} and its count {before.count} at the "
            f"read's open, and {_row(after.newest)} and {after.count} at its close"
        )
    return Finding(
        rule=RULE_MOVED,
        severity="error",
        object=CHANGELOG,
        message=f"Nautobot's changelog {said}, so the read may hold two states of Nautobot: {AGAIN}.",
    )


def _heads(before: tuple[Head, ...], after: tuple[Head, ...]) -> list[Finding]:
    """`read.moved` of each repository of `before` whose head in `after` differs, or which `after` lacks, in
    `before`'s order."""
    now = {id: head for id, _, head in after}
    found = []
    for id, name, head in before:
        if id not in now:
            said = (
                f"Template repository {name}, its current_head {_head(head)} at the read's open, is no longer listed "
                "at its close, so the renders may be of a repository Nautobot no longer holds"
            )
        elif now[id] != head:
            said = (
                f"The current_head of template repository {name} was {_head(head)} at the read's open and "
                f"{_head(now[id])} at its close, a commit fetched during the read, so the renders may be of two "
                "commits"
            )
        else:
            continue
        found.append(Finding(rule=RULE_MOVED, severity="error", object=name, message=f"{said}: {AGAIN}."))
    return found


def moved(before: Mark, after: Mark) -> tuple[Finding, ...]:
    """The `read.moved` findings of `after`, the close's `Mark`, against `before`, the open's: one for the changelog,
    where its newest row or its count differs, then one for each repository of `before` whose head moved or which is
    gone; none where nothing moved."""
    changelog = _changelog(before, after)
    return (*([changelog] if changelog is not None else []), *_heads(before.heads, after.heads))


def _sorted(repositories: tuple[Repository, ...]) -> tuple[Head, ...]:
    return tuple(sorted(((r.id, r.name, r.head) for r in repositories), key=lambda head: (head[1], head[0])))


def mark(conn: Source) -> tuple[Mark, tuple[Setting, ...]] | Finding:
    """The open's `Mark` and Golden Config's settings: the newest row and the count first, before anything else is
    listed; then the settings, held whole, and the repositories they name, each asked once and held whole and to the
    ids asked. A list that is not whole is its `read.incomplete`, and nothing more is asked."""
    count, newest = conn.newest()
    settings = conn.settings()
    lacking = incomplete(settings)
    if lacking is not None:
        return lacking
    ids = sorted({setting.repository for setting in settings.items if setting.repository is not None})
    repositories = conn.repositories(ids)
    lacking = incomplete(repositories, asked=ids)
    if lacking is not None:
        return lacking
    return Mark(count, newest, _sorted(repositories.items)), settings.items


def close(conn: Source, before: Mark) -> tuple[Finding, ...]:
    """The read's close: the newest row and the count again, then the open's repositories by their ids, and the
    findings the read is refused by, none where it is of one state. A repository no longer listed is `read.moved`;
    their list holding other than its count, or one twice, is `read.incomplete`, object `extras.gitrepository`, since
    whether a head moved cannot then be told, and the changelog is judged all the same."""
    count, newest = conn.newest()
    repositories = conn.repositories([id for id, _, _ in before.heads])
    lacking = incomplete(repositories)
    if lacking is not None:
        changelog = _changelog(before, Mark(count, newest, before.heads))
        return (*([changelog] if changelog is not None else []), lacking)
    return moved(before, Mark(count, newest, _sorted(repositories.items)))
