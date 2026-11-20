"""The bracket (D-118): a read is of one state where the changelog's newest row and its total count, and each template
repository's `current_head`, are at its close what they were at its open. Nautobot's changelog is keyed by UUIDs and
listed newest first, so no id orders it (design/verified-facts.md, "Nautobot 3.2.8 with Golden Config 3.0.8"); the
newest row stands for a row newer than the open's, and the count for a row of an earlier time seen late. Over rows
built in the tests and `FakeSource`, never Nautobot's answers (D-034)."""

from __future__ import annotations

from fake import CHANGE, REPOSITORY, SETTING, listing, three_node
from fylgja_core.findings import Finding

from fylgja_nautobot.bracket import AGAIN, RULE_MOVED, Mark, close, mark, moved
from fylgja_nautobot.rows import RULE_INCOMPLETE, Change, Repository, Setting

HEAD = "0123456789abcdef0123456789abcdef01234567"
PUSHED = "89abcdef0123456789abcdef0123456789abcdef"
HEADS = (("repository-1", "fylgja-templates", HEAD),)
OPEN = Mark(7, Change("change-7", "2026-11-19T21:00:06.129892Z"), HEADS)


def test_nothing_moved_is_no_finding() -> None:
    assert moved(OPEN, OPEN) == ()
    assert moved(OPEN, Mark(7, Change("change-7", "2026-11-19T21:00:06.129892Z"), HEADS)) == ()
    assert moved(Mark(0, None, ()), Mark(0, None, ())) == ()


def test_the_rule_and_the_remedy() -> None:
    assert RULE_MOVED == "read.moved"
    assert AGAIN == "read again"


def test_a_newer_row_is_moved() -> None:
    after = Mark(8, Change("change-8", "2026-11-19T21:00:07.000001Z"), HEADS)
    (found,) = moved(OPEN, after)
    assert (found.rule, found.severity, found.object) == (RULE_MOVED, "error", "extras.objectchange")
    for said in ("2026-11-19T21:00:06.129892Z", "2026-11-19T21:00:07.000001Z", "change-7", "change-8", "read again"):
        assert said in found.message, said
    assert found.message.endswith("read again.")


def test_a_count_moved_with_the_newest_unchanged_is_moved() -> None:
    for count in (8, 6):
        (found,) = moved(OPEN, Mark(count, OPEN.newest, HEADS))
        assert (found.rule, found.severity, found.object) == (RULE_MOVED, "error", "extras.objectchange")
        for said in ("7", str(count), "2026-11-19T21:00:06.129892Z", "read again"):
            assert said in found.message, said
        assert found.message.endswith("read again.")


def test_another_newest_row_of_the_same_time_is_moved() -> None:
    """Two rows can carry one time, to the microsecond: a row of the open's time that is not the open's row is one the
    open did not see, whatever the count."""
    (found,) = moved(OPEN, Mark(7, Change("change-9", "2026-11-19T21:00:06.129892Z"), HEADS))
    assert (found.rule, found.object) == (RULE_MOVED, "extras.objectchange")
    for said in ("change-7", "change-9", "2026-11-19T21:00:06.129892Z", "read again"):
        assert said in found.message, said


def test_an_empty_changelog_opens_with_no_time_and_any_row_refuses() -> None:
    before = Mark(0, None, HEADS)
    (found,) = moved(before, Mark(1, Change("change-1", "2026-11-19T21:00:06.129892Z"), HEADS))
    assert (found.rule, found.object) == (RULE_MOVED, "extras.objectchange")
    for said in ("no row", "change-1", "2026-11-19T21:00:06.129892Z", "read again"):
        assert said in found.message, said


def test_a_changelog_emptied_is_moved() -> None:
    (found,) = moved(OPEN, Mark(0, None, HEADS))
    assert (found.rule, found.object) == (RULE_MOVED, "extras.objectchange")
    for said in ("change-7", "no row", "read again"):
        assert said in found.message, said


def test_a_moved_head_is_moved_by_the_repositorys_name() -> None:
    (found,) = moved(OPEN, Mark(7, OPEN.newest, (("repository-1", "fylgja-templates", PUSHED),)))
    assert (found.rule, found.severity, found.object) == (RULE_MOVED, "error", "fylgja-templates")
    for said in (HEAD, PUSHED, "current_head", "read again"):
        assert said in found.message, said
    assert found.message.endswith("read again.")


def test_a_repository_gone_at_the_close_is_moved() -> None:
    other = ("repository-2", "other-templates", PUSHED)
    before = Mark(7, OPEN.newest, (*HEADS, other))
    (found,) = moved(before, Mark(7, OPEN.newest, (other,)))
    assert (found.rule, found.object) == (RULE_MOVED, "fylgja-templates")
    for said in (HEAD, "no longer", "read again"):
        assert said in found.message, said


def test_the_changelog_and_each_repository_are_one_finding_each() -> None:
    other = ("repository-2", "other-templates", PUSHED)
    before = Mark(7, OPEN.newest, (*HEADS, other))
    after = Mark(9, Change("change-9", "2026-11-19T21:00:08.000000Z"), (("repository-1", "fylgja-templates", PUSHED),))
    assert [found.object for found in moved(before, after)] == [
        "extras.objectchange",
        "fylgja-templates",
        "other-templates",
    ]


def test_the_open_takes_the_newest_before_the_settings() -> None:
    fake = three_node()
    opened = mark(fake)
    assert not isinstance(opened, Finding)
    held, settings = opened
    assert fake.calls == ["newest", "settings", "repositories"]
    assert fake.repositories_asked == [(REPOSITORY.id,)]
    assert held == Mark(fake.held_newest[0], CHANGE, ((REPOSITORY.id, REPOSITORY.name, REPOSITORY.head),))
    assert settings == (SETTING,)


def test_the_heads_are_sorted_by_name_and_a_repository_asked_once() -> None:
    fake = three_node()
    second = Repository("repository-0", "a-templates", PUSHED)
    fake.held_settings = listing(
        "nautobot_golden_config.goldenconfigsetting",
        [
            SETTING,
            Setting("setting-2", "Heavy", 2000, second.id, "group-2"),
            Setting("setting-3", "Light", 500, REPOSITORY.id, "group-3"),
            Setting("setting-4", "None", 100, None, "group-4"),
        ],
    )
    fake.held_repositories = listing("extras.gitrepository", [REPOSITORY, second])
    opened = mark(fake)
    assert not isinstance(opened, Finding)
    held, settings = opened
    assert [name for _, name, _ in held.heads] == ["a-templates", "fylgja-templates"]
    assert fake.repositories_asked == [tuple(sorted({REPOSITORY.id, second.id}))]
    assert len(settings) == 4


def test_settings_not_whole_are_incomplete() -> None:
    fake = three_node()
    fake.held_settings = listing("nautobot_golden_config.goldenconfigsetting", [SETTING], count=2)
    found = mark(fake)
    assert isinstance(found, Finding)
    assert (found.rule, found.object) == (RULE_INCOMPLETE, "nautobot_golden_config.goldenconfigsetting")
    assert fake.calls == ["newest", "settings"]


def test_a_repository_a_setting_names_and_not_listed_is_incomplete() -> None:
    fake = three_node()
    fake.held_repositories = listing("extras.gitrepository", [])
    found = mark(fake)
    assert isinstance(found, Finding)
    assert (found.rule, found.object) == (RULE_INCOMPLETE, "extras.gitrepository")
    assert REPOSITORY.id in found.message


def test_the_close_of_nothing_moved_is_no_finding() -> None:
    fake = three_node()
    opened = mark(fake)
    assert not isinstance(opened, Finding)
    fake.calls.clear()
    assert close(fake, opened[0]) == ()
    assert fake.calls == ["newest", "repositories"]
    assert fake.repositories_asked[-1] == (REPOSITORY.id,)


def test_the_close_finds_a_newer_row_and_a_moved_head() -> None:
    fake = three_node()
    opened = mark(fake)
    assert not isinstance(opened, Finding)
    fake.held_newest = (fake.held_newest[0] + 1, Change("change-new", "2026-11-19T22:00:00.000000Z"))
    fake.held_repositories = listing("extras.gitrepository", [Repository(REPOSITORY.id, REPOSITORY.name, PUSHED)])
    assert [(f.rule, f.object) for f in close(fake, opened[0])] == [
        (RULE_MOVED, "extras.objectchange"),
        (RULE_MOVED, REPOSITORY.name),
    ]


def test_the_close_finds_a_repository_gone() -> None:
    fake = three_node()
    opened = mark(fake)
    assert not isinstance(opened, Finding)
    fake.held_repositories = listing("extras.gitrepository", [])
    assert [(f.rule, f.object) for f in close(fake, opened[0])] == [(RULE_MOVED, REPOSITORY.name)]


def test_the_close_of_repositories_not_whole_is_incomplete_and_the_changelog_still_judged() -> None:
    fake = three_node()
    opened = mark(fake)
    assert not isinstance(opened, Finding)
    fake.held_newest = (fake.held_newest[0] + 1, fake.held_newest[1])
    fake.held_repositories = listing("extras.gitrepository", [REPOSITORY], count=2)
    assert [(f.rule, f.object) for f in close(fake, opened[0])] == [
        (RULE_MOVED, "extras.objectchange"),
        (RULE_INCOMPLETE, "extras.gitrepository"),
    ]


def test_the_close_of_an_open_with_no_repository_asks_none() -> None:
    fake = three_node()
    before = Mark(fake.held_newest[0], fake.held_newest[1], ())
    assert close(fake, before) == ()
    assert fake.repositories_asked == [()]
