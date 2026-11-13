"""The bracket against the development NetBox (D-095; design/verified-facts.md, "NetBox 4.7.5 with netbox-branching
1.2.3"): an edit moves the changelog it was made under, and not `main`'s; a journal entry on a branch moves `main`'s by
a row no read reads; a render moves neither; a sync moves no changelog and is seen by the branch's `last_sync`; a
merge moves `main`'s by a row of the object merged; and a branch deleted under a read is seen at the close. Every
write is the superuser's, through `box`; `main` is written only by one tag of the tier's naming, deleted in a
`finally`, and by the journal entry on the test's branch, deleted the same way. No assertion message prints the
address or a token."""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from typing import Any

from fylgja_netbox import NetBox
from fylgja_netbox.bracket import RULE_MOVED, close, mark, moved
from fylgja_netbox.rows import Branch, incomplete

from .conftest import BRANCHES, PREFIX, BoxError, Writes

ACTION_WAIT_S = 60.0
"""Seconds a sync or a merge is waited for until the branch reads it done. In the readings of
design/verified-facts.md, "A sync" and "A merge", a sync's job read `completed` 0.73 s after its request was answered,
and a merge's 1.56 s; 60 s is about 38 times the slowest, 1.56 s, a derivation."""

POLL_S = 0.2
"""Seconds between two reads of the branch while a sync or a merge is waited for."""


def waited(box: Writes, branch: Branch, done: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    """The branch's representation once `done` holds of it, read every `POLL_S`; `ACTION_WAIT_S` at most."""
    started = time.monotonic()
    while True:
        row: dict[str, Any] = box.get(f"{BRANCHES}{branch.id}/")
        if done(row):
            return row
        assert time.monotonic() - started < ACTION_WAIT_S, f"branch {branch.name}: {row['status']['value']}"
        time.sleep(POLL_S)


def settled(box: Writes, branch: Branch) -> None:
    """Return once the branch has left `merging`, or is gone, `ACTION_WAIT_S` at most, the bound of `waited` and the
    same readings: a merge that is still running when a test ends could land its objects on `main` after the test's
    clean-up."""
    started = time.monotonic()
    while True:
        try:
            row: dict[str, Any] = box.get(f"{BRANCHES}{branch.id}/")
        except BoxError:
            return
        if row["status"]["value"] != "merging":
            return
        assert time.monotonic() - started < ACTION_WAIT_S, f"branch {branch.name}: merging"
        time.sleep(POLL_S)


def found(conn: NetBox, branch: Branch) -> Branch:
    """The branch as the reader lists it by its name, `last_sync` and all."""
    listed = conn.branches(branch.name)
    assert [row.id for row in listed.items] == [branch.id]
    return listed.items[0]


def test_an_edit_moves_the_changelog_it_was_made_under(conn: NetBox, box: Writes, branch: Branch) -> None:
    opened = found(conn, branch)
    on_main = conn.latest(None)
    opening = mark(conn, branch)
    before = opening.id
    devices = conn.devices(branch, conn.tags(branch, "fylgja").items[0].id)
    n2 = [device.id for device in devices.items if device.name == "n2"]
    port = next(port for port in conn.ports(branch, n2).items if port.name == "ethernet-1/1")
    box.patch(f"dcim/interfaces/{port.id}/", {"enabled": False}, branch=branch.schema_id)

    after = conn.latest(branch)
    assert after is not None and (before is None or after > before)
    changes = conn.changes(branch, before)
    assert incomplete(changes, branch=branch.name) is None
    assert [change.kind for change in changes.items] == ["dcim.interface"]
    assert conn.latest(None) == on_main

    refused = moved(before, after, changes.items, branch=branch.name)
    assert refused is not None
    assert (refused.rule, refused.object) == (RULE_MOVED, branch.name)
    closed, findings = close(conn, opened, opening)
    assert closed == after
    assert [(finding.rule, finding.object) for finding in findings] == [(RULE_MOVED, branch.name)]


def test_a_journal_entry_on_a_branch_moves_mains_changelog_by_a_row_no_read_reads(
    conn: NetBox, box: Writes, branch: Branch
) -> None:
    opening = mark(conn, None)
    before = opening.id
    under = conn.latest(branch)
    body = {"assigned_object_type": "netbox_branching.branch", "assigned_object_id": branch.id, "comments": "fylgja"}
    entry = box.post("extras/journal-entries/", {**body, "kind": "info"})
    try:
        after = conn.latest(None)
        assert after != before
        changes = conn.changes(None, before)
        assert [change.kind for change in changes.items] == ["extras.journalentry"]
        assert conn.latest(branch) == under
        assert moved(before, after, changes.items, branch=None) is None
        assert close(conn, None, opening) == (after, ())
    finally:
        box.delete(f"extras/journal-entries/{entry['id']}/")


def test_a_render_moves_no_changelog(conn: NetBox, box: Writes, branch: Branch) -> None:
    opened = found(conn, branch)
    opening = mark(conn, branch)
    ids = (conn.latest(None), opening.id)
    devices = conn.devices(branch, conn.tags(branch, "fylgja").items[0].id)
    assert len(devices.items) == 3
    for device in devices.items:
        rendered = box.post(f"dcim/devices/{device.id}/render-config/", None, branch=branch.schema_id)
        assert rendered["content"].strip(), device.name
    assert (conn.latest(None), conn.latest(branch)) == ids
    assert close(conn, opened, opening) == (ids[1], ())


def test_a_sync_is_seen_by_the_bracket(conn: NetBox, box: Writes, branch: Branch) -> None:
    """A sync adds no row to either changelog and changes what the branch reads (design/verified-facts.md, "A sync"),
    so the bracket sees it by the branch's `last_sync`: what is synced is one tag of the tier's naming, made on
    `main`."""
    opened = found(conn, branch)
    opening = mark(conn, branch)
    assert close(conn, opened, opening) == (opening.id, ())
    name = PREFIX + secrets.token_hex(4)
    made = box.post("extras/tags/", {"name": name, "slug": name})
    try:
        assert conn.tags(branch, name).count == 0
        on_main = conn.latest(None)
        box.post(f"{BRANCHES}{branch.id}/sync/", {"commit": True})
        waited(box, branch, lambda row: row["status"]["value"] == "ready" and row["last_sync"] != opened.last_sync)
        assert conn.tags(branch, name).count == 1
        assert conn.latest(branch) == opening.id
        assert conn.latest(None) == on_main, "the sync itself added a row to main's changelog"

        closed, findings = close(conn, opened, opening)
        assert closed is None
        assert [(finding.rule, finding.object) for finding in findings] == [(RULE_MOVED, branch.name)]
        assert "last_sync" in findings[0].message
    finally:
        box.delete(f"extras/tags/{made['id']}/")


def test_a_merge_moves_mains_changelog(conn: NetBox, box: Writes, branch: Branch) -> None:
    """A merge adds to `main`'s changelog a row of the object merged, and a merged branch can be deleted
    (design/verified-facts.md, "A merge"): the branch merges one tag of the tier's naming, deleted on `main` after,
    and the fixture deletes the branch."""
    opened = found(conn, branch)
    under = mark(conn, branch)
    name = PREFIX + secrets.token_hex(4)
    box.post("extras/tags/", {"name": name, "slug": name}, branch=branch.schema_id)
    opening = mark(conn, None)
    before = opening.id
    try:
        box.post(f"{BRANCHES}{branch.id}/merge/", {"commit": True})
        waited(box, branch, lambda row: row["status"]["value"] == "merged")
        after = conn.latest(None)
        changes = conn.changes(None, before)
        assert "extras.tag" in [change.kind for change in changes.items]
        refused = moved(before, after, changes.items, branch=None)
        assert refused is not None
        assert (refused.rule, refused.object) == (RULE_MOVED, "main")
        assert [finding.rule for finding in close(conn, None, opening)[1]] == [RULE_MOVED]

        closed, findings = close(conn, opened, under)
        assert closed is None
        assert [(finding.rule, finding.object) for finding in findings] == [(RULE_MOVED, branch.name)]
        assert "merged" in findings[0].message
    finally:
        try:
            settled(box, branch)
        finally:
            on_main = box.one("extras/tags/", name=name)
            if on_main is not None:
                box.delete(f"extras/tags/{on_main['id']}/")


def test_a_branch_deleted_under_a_read_is_moved(conn: NetBox, box: Writes, branch: Branch) -> None:
    """The branch the read opened on, the test's own, deleted before the close: NetBox lists none of its id, and the
    close asks nothing under its header. The fixture then finds no branch to delete."""
    opened = found(conn, branch)
    opening = mark(conn, branch)
    box.delete(f"{BRANCHES}{branch.id}/")
    closed, findings = close(conn, opened, opening)
    assert closed is None
    assert [(finding.rule, finding.object) for finding in findings] == [(RULE_MOVED, branch.name)]
    assert f"no branch {branch.name}" in findings[0].message
