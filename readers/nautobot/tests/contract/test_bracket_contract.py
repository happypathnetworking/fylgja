"""The bracket against the development Nautobot (D-118; design/verified-facts.md, "Nautobot 3.2.8 with Golden Config
3.0.8", "The bracket"): the open lists Golden Config's settings and the repository they name, and takes its head; an
edit moves the changelog's newest row and its count; a push moves no head until the next render fetches it, which
moves the head and writes one row, so the close refuses the read on both; and a render with nothing to fetch moves
nothing. Every write is the superuser's, through `box`: one tag of the tier's naming, deleted in a `finally`, and one
commit to the template repository, pushed back and fetched again in a `finally`. No assertion message prints the
address or a token."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fylgja_core.findings import Finding

from fylgja_nautobot import Nautobot
from fylgja_nautobot.bracket import RULE_MOVED, Mark, close, mark
from fylgja_nautobot.rows import Setting

from .conftest import SEEDING, TEMPLATE, Writes, contract_name, pushed, settle

SETTING = "Default Settings"
"""The installed setting the seed points at the template repository."""

REPOSITORY = "fylgja-templates"
"""The template repository the seed registers."""


def opened(conn: Nautobot) -> tuple[Mark, tuple[Setting, ...]]:
    """The open's `Mark` and the settings, which must be whole."""
    held = mark(conn)
    assert not isinstance(held, Finding), held.message
    return held


def ruled(found: tuple[Finding, ...]) -> list[tuple[str, str | None]]:
    return [(finding.rule, finding.object) for finding in found]


def rendered(box: Writes, name: str) -> dict[str, Any]:
    """The seeded device `name` rendered once by the superuser's token."""
    (device,) = [row for row in box.listed("dcim/devices/", tags="fylgja") if row["name"] == name]
    answer: dict[str, Any] = box.get(SEEDING.RENDER, device_id=device["id"])
    return answer


def test_the_open_lists_the_settings_and_their_repositorys_head(conn: Nautobot, box: Writes) -> None:
    held, settings = opened(conn)
    (default,) = [setting for setting in settings if setting.name == SETTING]
    (repository,) = box.listed("extras/git-repositories/", name=REPOSITORY)
    assert default.repository == repository["id"]
    row = box.get(f"plugins/golden-config/golden-config-settings/{default.id}/")
    assert default.group == row["dynamic_group"]["id"]
    assert held.heads == ((repository["id"], REPOSITORY, repository["current_head"]),)
    count, newest = conn.newest()
    assert (held.count, held.newest) == (count, newest)
    assert newest is not None and newest.time == box.get("extras/object-changes/", limit=1)["results"][0]["time"]


def test_an_edit_moves_the_newest_row_and_the_count(conn: Nautobot, box: Writes) -> None:
    before, _ = opened(conn)
    assert before.newest is not None
    assert close(conn, before) == ()
    name = contract_name()
    made: dict[str, Any] | None = None
    try:
        made = box.post("extras/tags/", {"name": name, "content_types": ["dcim.device"]})
        count, newest = conn.newest()
        assert count == before.count + 1
        assert newest is not None and newest.id != before.newest.id
        assert datetime.fromisoformat(newest.time) > datetime.fromisoformat(before.newest.time)
        found = close(conn, before)
        assert ruled(found) == [(RULE_MOVED, "extras.objectchange")]
        for said in (before.newest.id, before.newest.time, newest.id, newest.time, "read again"):
            assert said in found[0].message
    finally:
        if made is not None:
            box.delete(f"extras/tags/{made['id']}/")


def test_a_push_moves_the_head_at_the_next_render(conn: Nautobot, box: Writes) -> None:
    """A commit the repository serves is not Nautobot's until a render fetches it: the render saves the new head and
    writes one changelog row, its own, whose kind counts like any other (D-118)."""
    before, _ = opened(conn)
    ((_, _, head),) = before.heads
    commit = None
    try:
        commit = pushed(TEMPLATE.read_text() + "{# " + contract_name() + " #}\n")
        assert commit != head
        assert close(conn, before) == (), "a push alone moved the bracket"
        rendered(box, "n1")
        count, _ = conn.newest()
        assert count == before.count + 1
        assert conn.repositories([id for id, _, _ in before.heads]).items[0].head == commit
        found = close(conn, before)
        assert ruled(found) == [(RULE_MOVED, "extras.objectchange"), (RULE_MOVED, REPOSITORY)]
        for said in (head, commit, "current_head", "read again"):
            assert said in found[1].message
    finally:
        if commit is not None:
            pushed(TEMPLATE.read_text())
            settle(box)


def test_a_render_with_nothing_to_fetch_moves_nothing(conn: Nautobot, box: Writes) -> None:
    before, _ = opened(conn)
    for name in ("n1", "n2", "n3"):
        assert isinstance(rendered(box, name).get("intended_config"), str)
    assert close(conn, before) == ()
