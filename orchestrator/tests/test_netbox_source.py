"""The NetBox change source (D-085, D-097) over `fake_netbox.FakeNetBox`, a handler for `httpx.MockTransport` over
state each test sets, never an answer captured from NetBox (D-034, D-096); the reader's `connect` and `read` replaced
by fakes that record what they were given; and the core's own server on its fake runtime (`served`) where a mark's
blueprint is put or read back. The change is a ready branch found by its exact name; its stages `main`, the marks in
the order written and the head; `main` and the head read through the reader and read again where they moved; a mark
read from its entry and its blueprint from the core, refused by name where the rehearsal cannot use it; a mark taken
as its blueprint put and then its entry written; the tag taken off once; and the report one journal entry whose kind
is its status. No text the source makes holds its token."""

from __future__ import annotations

import difflib
import json
import logging
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import drafts
import httpx
import pytest
from fake_netbox import ADDRESS, BRANCH, ELSEWHERE, EVENTRULE, JOURNALENTRY, TAG_TYPE, TOKEN, WEBHOOK, FakeNetBox
from fylgja_core.blueprint import blueprint_id
from fylgja_core.client import Client, InvalidAddress, InvalidCA, InvalidToken, ProblemError
from fylgja_core.findings import Finding
from fylgja_core.problem import ProblemDocument
from fylgja_netbox import NetBoxError, Result, document
from fylgja_netbox.bracket import UNREAD
from harness import Served, Wrapped

from fylgja_orchestrator import netbox
from fylgja_orchestrator.netbox import source as module
from fylgja_orchestrator.netbox.source import (
    HEAD,
    KIND,
    LABEL,
    MAIN,
    MARK_PREFIX,
    MOVED_READS,
    READY,
    TAG,
    Mark,
    Marked,
    NetBoxSource,
    NoChange,
    Pin,
    Unready,
    mark_text,
    marks_of,
    spaced,
    stages_of,
)
from fylgja_orchestrator.netbox.transport import SourceError, Transport
from fylgja_orchestrator.rehearsal import Change, Report, Stage, render, rules
from fylgja_orchestrator.rehearsal.rules import clause

ROOT = Path(__file__).resolve().parents[2]
BLUEPRINTS = ROOT / "testdata" / "blueprint"
DOCUMENT = document.load(ROOT / "netbox" / "seed" / "reader.yaml")
SCOPE = "tag:fylgja"
REF = "third-link"
OBSERVED = "2026-11-13T09:00:00.123456Z"
ID = "0123456789abcdef" * 4
"""A blueprint's id as the core gives one: 64 lowercase hex."""
PC = "0000000a"
"""A branch's `schema_id`, the change's id, for stages built without a source."""


def blueprint(name: str, observed: str = OBSERVED) -> dict[str, Any]:
    """A blueprint of `testdata/`, its source envelope the NetBox reader's, read at `observed`."""
    loaded: dict[str, Any] = json.loads((BLUEPRINTS / name).read_text())
    loaded["source"] = {"source": "netbox", "branch": REF, "scope": SCOPE, "observed_at": observed}
    return loaded


THREE = blueprint("three-node.json")
UNLINKED = blueprint("steps/three-node-unlinked.json")


def finding(rule: str, severity: str = "error", obj: str = REF, message: str = "said") -> Finding:
    return Finding(rule=rule, severity=severity, object=obj, message=message)  # type: ignore[arg-type]


MOVED = finding("read.moved", message="NetBox moved under the read.")
UNVERIFIED = finding("netbox.version.unverified", "warning", "4.8.0/1.3.0", "NetBox is version 4.8.0.")


class Conn:
    """The reader's connection, replaced: it records its closing."""

    closed = False

    def close(self) -> None:
        self.closed = True


class Reader:
    """The reader's `connect` and `read`, replaced: `results` answers `read` by branch, None for `main`, each `Result`
    listed in turn and the last for every read after, or an exception raised. `calls` holds each read's
    `(branch, scope)`, `connects` each connect's `(address, token, ca, transport)`."""

    def __init__(self) -> None:
        self.results: dict[str | None, list[Result | Exception]] = {}
        self.calls: list[tuple[str | None, str]] = []
        self.connects: list[tuple[str, str, Path | None, object]] = []
        self.conns: list[Conn] = []
        self.refuse: Exception | None = None

    def connect(self, address: str, token: str, *, ca: Path | None = None, transport: object = None) -> Conn:
        self.connects.append((address, token, ca, transport))
        if self.refuse is not None:
            raise self.refuse
        self.conns.append(Conn())
        return self.conns[-1]

    def read(self, conn: object, *, branch: str | None, scope: str, document: object) -> Result:
        assert conn is self.conns[-1]
        assert document is DOCUMENT
        self.calls.append((branch, scope))
        listed = self.results[branch]
        answer = listed.pop(0) if len(listed) > 1 else listed[0]
        if isinstance(answer, Exception):
            raise answer
        return answer


class Core:
    """The core, for a test that needs none of its own: a blueprint put is held by its id, and `asked` holds each
    call."""

    def __init__(self) -> None:
        self.held: dict[str, dict[str, Any]] = {}
        self.asked: list[tuple[str, str]] = []

    def put_blueprint(self, doc: Mapping[str, Any]) -> str:
        found = blueprint_id(dict(doc))
        self.asked.append(("put_blueprint", found))
        self.held[found] = dict(doc)
        return found

    def get_blueprint(self, found: str) -> dict[str, Any]:
        self.asked.append(("get_blueprint", found))
        if found not in self.held:
            problem = ProblemDocument(type="about:blank", title="Not Found", status=404, rule="blueprint.not_found")
            raise ProblemError(404, problem)
        return self.held[found]


class World:
    """A source over a fake NetBox, a fake reader and a core."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, core: Client | Core) -> None:
        self.netbox = FakeNetBox()
        self.reader = Reader()
        self.core = core
        monkeypatch.setattr(module, "connect", self.reader.connect)
        monkeypatch.setattr(module, "read", self.reader.read)
        self.wire = httpx.MockTransport(self.netbox)
        self.source = NetBoxSource(ADDRESS, TOKEN, DOCUMENT, cast(Client, core), transport=self.wire)


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., World]]:
    made: list[World] = []

    def make(core: Client | Core | None = None) -> World:
        made.append(World(monkeypatch, core if core is not None else Core()))
        return made[-1]

    yield make
    for each in made:
        each.source.close()
        assert each.netbox.keyed, "a request was sent without the token in Authorization alone, or under a branch"


def entry(text: str, k: int = 1) -> dict[str, Any]:
    """A journal entry of id `k` holding `text`."""
    return {"id": k, "comments": text}


REDO = (
    "Have someone who may delete journal entries delete entry {entry} in NetBox and mark the step again{under}, which "
    "can be done only while the branch still stands at that step; otherwise seed the change again."
)
"""How a mark the source does not read is taken again: its entry deleted first, by a person who may."""


def malformed(called: str, entry: int, fault: str) -> str:
    """The sentence of `mark.malformed` for the mark `called` ("the mark <label>", or "the mark") of `REF`."""
    return (f"{called[0].upper()}{called[1:]} on branch {REF}, journal entry {entry}, is not read: {fault}. "
            + REDO.format(entry=entry, under=""))


def unheld(label: str, found: str, *, other: bool = False) -> str:
    """The sentence of `mark.unheld` for the mark `label` naming the blueprint `found`."""
    said = f"answered another document than the blueprint {found[:12]}" if other else f"holds no blueprint {found[:12]}"
    return (f"The core {said}, which the mark {label} on branch {REF} names: a mark belongs to the core it was given "
            "to. Rehearse through that core, or seed and mark the change again for this one.")


def by_label(stages: Sequence[Stage], label: str) -> Stage:
    return next(stage for stage in stages if stage.label == label)


def change_of(w: World, ref: str = REF) -> Change:
    return w.source.change(ref)


# The change.


def test_the_change_is_a_ready_branch_found_by_its_exact_name(world: Callable[..., World]) -> None:
    w = world()
    found = w.netbox.branch(REF)
    other = w.netbox.branch(f"{REF}-2")
    assert (w.netbox.log, w.reader.connects) == ([], []), "the source asked something when it was made"
    assert w.source.change(REF) == Change(REF, found["schema_id"], REF, f"branch {REF}")
    assert w.source.change(f"{REF}-2").id == other["schema_id"] != found["schema_id"]
    assert w.source.is_draft(w.source.change(REF)) is False
    # A row of another name, as NetBox answers a parameter it does not know, is not the branch.
    w.netbox.scripted[("GET", "plugins/branching/branches/")] = [
        httpx.Response(200, json={"count": 2, "next": None, "results": [other, found]})
    ]
    assert w.source.change(REF).id == found["schema_id"]
    assert w.reader.connects == []


def test_a_branch_gone_is_no_change_and_one_not_ready_is_refused_with_its_status(world: Callable[..., World]) -> None:
    w = world()
    w.netbox.branch(REF)
    with pytest.raises(NoChange) as gone:
        w.source.change("no-such-branch")
    assert str(gone.value) == "no branch is named no-such-branch"
    assert isinstance(gone.value, SourceError) and gone.value.status is None
    for status in ("merged", "syncing", "provisioning"):
        w.netbox.branch(f"b-{status}", status=status)
        with pytest.raises(Unready) as unready:
            w.source.change(f"b-{status}")
        assert str(unready.value) == f"branch b-{status} is {status}, and only a ready branch is rehearsed"
        assert isinstance(unready.value, SourceError)
    assert READY == "ready"


# A mark's entry.


def test_a_marks_text_is_read_back_as_it_was_written() -> None:
    text = mark_text(REF, ID, SCOPE, OBSERVED)
    assert marks_of([entry(text)]) == (Mark(REF, ID, SCOPE, OBSERVED, (1,), None),)
    lines = text.split("\n")
    assert lines[0] == "Fylgja stage: third-link" == f"{MARK_PREFIX}{REF}"
    assert lines[1:] == ["", f"- blueprint: {ID}", f"- scope: {SCOPE}", f"- read: {OBSERVED}"]
    # Other lines are a person's to add, anywhere after the first.
    noted = f"{MARK_PREFIX}{REF}\nThe third link, cabled.\n- read: {OBSERVED}\n- scope: {SCOPE}\n\n- blueprint: {ID}"
    assert marks_of([entry(noted)]) == (Mark(REF, ID, SCOPE, OBSERVED, (1,), None),)


def test_an_entry_that_is_no_mark_is_no_stage(world: Callable[..., World]) -> None:
    report = render(drafts.passed(), limit=None)
    texts = [
        f"{report.summary}\n\n{report.detail}",
        "Checked the cabling with the site team.",
        f"Note: {MARK_PREFIX}{REF}",
        "",
    ]
    assert marks_of([entry(text, k) for k, text in enumerate(texts, 1)]) == ()
    w = world()
    branch = w.netbox.branch(REF)
    for text in texts:
        w.netbox.entry(branch, text)
    w.netbox.entry(branch, mark_text("n1-address", ID, SCOPE, OBSERVED))
    assert [stage.label for stage in w.source.stages(change_of(w))] == [MAIN, "n1-address", HEAD]


MALFORMED = {
    "no blueprint line": (
        REF,
        f"{MARK_PREFIX}{REF}\n\n- scope: {SCOPE}\n- read: {OBSERVED}",
        "- blueprint: is missing",
    ),
    "two scope lines": (
        REF,
        f"{mark_text(REF, ID, SCOPE, OBSERVED)}\n- scope: tag:other",
        "- scope: is there 2 times",
    ),
    "an id of 63": (REF, mark_text(REF, ID[:63], SCOPE, OBSERVED), "not 64 lowercase hexadecimal"),
    "the label head": (HEAD, mark_text(HEAD, ID, SCOPE, OBSERVED), "a stage the source makes"),
    "the label main": (MAIN, mark_text(MAIN, ID, SCOPE, OBSERVED), "a stage the source makes"),
    "no label": ("", f"{MARK_PREFIX}\n\n- blueprint: {ID}\n- scope: {SCOPE}\n- read: {OBSERVED}", "it has no label"),
    "the label Third": ("Third", mark_text("Third", ID, SCOPE, OBSERVED), "no label"),
    "an empty scope": (REF, mark_text(REF, ID, "", OBSERVED), "its scope is empty"),
    "an empty time": (REF, mark_text(REF, ID, SCOPE, " "), "its time read is empty"),
}


@pytest.mark.parametrize("label, text, fault", MALFORMED.values(), ids=MALFORMED.keys())
def test_a_mark_with_a_line_missing_twice_or_malformed_is_a_stage_refused_by_name(
    world: Callable[..., World], label: str, text: str, fault: str
) -> None:
    (mark,) = marks_of([entry(text, 4)])
    assert mark.label == label and mark.entries == (4,)
    assert mark.fault is not None and fault in mark.fault, mark.fault
    # A mark with no label, or labelled as a stage the source makes, is the stage of its entry: no mark stands as a
    # second main or head.
    named = label if label not in ("", MAIN, HEAD) else "journal entry 4"
    stages = stages_of(REF, [mark], change=PC)
    assert [stage.label for stage in stages] == [MAIN, named, HEAD]
    stage = stages[1]
    assert stage.where.endswith(", which is not read")
    w = world()
    got = w.source.read(stage, SCOPE)
    assert (got.blueprint, got.empty) == (None, False)
    (refused,) = got.findings
    assert (refused.rule, refused.severity, refused.object) == ("mark.malformed", "error", named)
    assert refused.message == malformed(f"the mark {label}" if label else "the mark", 4, mark.fault)
    assert isinstance(w.core, Core) and w.core.asked == []
    assert (w.reader.calls, w.netbox.log) == ([], [])


def test_two_marks_of_one_label_are_one_stage_refused_naming_both_entries(world: Callable[..., World]) -> None:
    entries = [entry("a note", k) for k in range(1, 8)]
    entries[2] = entry(mark_text("a", ID, SCOPE, OBSERVED), 3)
    entries[4] = entry(mark_text("b", ID, SCOPE, OBSERVED), 5)
    entries[6] = entry(mark_text("a", "f" * 64, SCOPE, "2026-11-13T09:30:00.000000Z"), 7)
    marks = marks_of(entries)
    assert [(mark.label, mark.entries) for mark in marks] == [("a", (3, 7)), ("b", (5,))]
    stages = stages_of(REF, marks, change=PC)
    assert [stage.label for stage in stages] == [MAIN, "a", "b", HEAD]
    w = world()
    got = w.source.read(stages[1], SCOPE)
    (refused,) = got.findings
    assert (refused.rule, refused.severity, refused.object) == ("mark.duplicate", "error", "a")
    assert refused.message == (
        f"Branch {REF} has 2 marks labelled a, journal entries 3 and 7: a label is unique within its branch. Delete "
        "all but one."
    )
    assert got.blueprint is None
    assert isinstance(w.core, Core) and w.core.asked == []


# The stages.


def test_the_stages_are_main_the_marks_in_the_order_written_and_the_head(world: Callable[..., World]) -> None:
    w = world()
    w.netbox.page = 2
    branch = w.netbox.branch(REF)
    w.netbox.entry(branch, "Started on the third link.")
    w.netbox.entry(branch, mark_text("b", ID, SCOPE, "2026-11-13T09:10:00.000000Z"))
    w.netbox.entry(branch, "A note between.")
    w.netbox.entry(branch, mark_text("a", "e" * 64, SCOPE, "2026-11-13T09:20:00.000000Z"))
    w.netbox.entry(w.netbox.branch("another"), mark_text("c", ID, SCOPE, OBSERVED))
    w.netbox.entry(branch, "A note after.")
    w.netbox.entry(branch, "And one more.")
    stages = w.source.stages(change_of(w))
    assert [stage.label for stage in stages] == [MAIN, "b", "a", HEAD]
    pins = [stage.pin for stage in stages]
    assert all(isinstance(pin, Pin) and pin.branch == REF for pin in pins)
    assert [pin.kind for pin in pins if isinstance(pin, Pin)] == ["main", "mark", "mark", "head"]
    assert (stages[0].description, stages[0].where) == ("main as it stands",
                                                        "main as it stands when the rehearsal reads it")
    at = "2026-11-13T09:10:00.000000Z"
    assert (stages[1].description, stages[1].where) == ("the mark b", f"the mark b of branch {REF}, read at {at}")
    assert "2026-11-13T09:20:00.000000Z" in stages[2].where
    assert (stages[3].description, stages[3].where) == (f"the head of {REF}",
                                                        f"branch {REF} as it stands when the rehearsal reads it")
    offsets = [dict(query).get("offset") for _, path, query, _ in w.netbox.log if path == "extras/journal-entries/"]
    assert offsets == ["0", "2", "4"]
    assert not any(ELSEWHERE in str(query) for *_, query, _ in w.netbox.log)
    assert w.reader.calls == []


def test_a_list_netbox_answers_short_of_its_count_is_a_source_error(world: Callable[..., World]) -> None:
    w = world()
    branch = w.netbox.branch(REF)
    for k in range(3):
        w.netbox.entry(branch, f"note {k}")
    short = {"count": 3, "next": f"{ELSEWHERE}/?offset=2", "results": w.netbox.entries[:2]}
    w.netbox.scripted[("GET", "extras/journal-entries/")] = [
        httpx.Response(200, json=short), httpx.Response(200, json={**short, "results": []})
    ]
    with pytest.raises(SourceError) as caught:
        w.source.stages(change_of(w))
    assert "answered 2 of the 3 rows it counted" in str(caught.value)


# Main and the head.


def test_main_and_the_head_are_read_through_the_reader_as_they_stand(world: Callable[..., World]) -> None:
    w = world()
    w.netbox.branch(REF)
    w.reader.results = {None: [Result(UNLINKED, (UNVERIFIED,), False)], REF: [Result(THREE, (), False)]}
    stages = w.source.stages(change_of(w))
    first, last = w.source.read(stages[0], SCOPE), w.source.read(stages[-1], SCOPE)
    assert (first.blueprint, first.findings, first.empty) == (UNLINKED, (UNVERIFIED,), False)
    assert (last.blueprint, last.findings, last.empty) == (THREE, (), False)
    assert w.reader.calls == [(None, SCOPE), (REF, SCOPE)]
    assert w.reader.connects == [(ADDRESS, TOKEN, None, w.wire)], "the reader is not connected once, as the source is"
    empty = Result(None, (finding("scope.empty", obj=SCOPE),), True)
    w.reader.results[REF] = [empty]
    got = w.source.read(stages[-1], SCOPE)
    assert (got.blueprint, got.findings, got.empty) == (None, empty.findings, True)


def test_a_read_refused_as_moved_is_read_again_and_three_refusals_refuse_the_stage(
    world: Callable[..., World],
) -> None:
    w = world()
    w.netbox.branch(REF)
    head = w.source.stages(change_of(w))[-1]
    w.reader.results = {REF: [Result(None, (MOVED,), False), Result(THREE, (), False)]}
    got = w.source.read(head, SCOPE)
    assert len(w.reader.calls) == 2
    assert got.blueprint == THREE
    assert "read.moved" not in [f.rule for f in got.findings]

    w.reader.calls.clear()
    w.reader.results = {REF: [Result(None, (MOVED,), False)]}
    got = w.source.read(head, SCOPE)
    assert len(w.reader.calls) == MOVED_READS == 3
    assert got.blueprint is None
    assert got.findings == (MOVED,)

    # A refusal of another rule is not read again.
    w.reader.calls.clear()
    w.reader.results = {REF: [Result(None, (finding("render.failed", obj="n1"),), False)]}
    w.source.read(head, SCOPE)
    assert len(w.reader.calls) == 1


def test_a_head_the_reader_refuses_is_a_read_of_its_findings(world: Callable[..., World]) -> None:
    w = world()
    w.netbox.branch(REF)
    head = w.source.stages(change_of(w))[-1]
    unready = finding("branch.unready", message=f"Branch {REF} is merged.")
    w.reader.results = {REF: [Result(None, (unready,), False)]}
    got = w.source.read(head, SCOPE)
    assert (got.blueprint, got.findings, got.empty) == (None, (unready,), False)
    assert len(w.reader.calls) == 1


def test_the_triggers_own_webhook_and_rule_are_no_change_of_main(world: Callable[..., World]) -> None:
    """`make netbox-hook` writes the webhook and the event rule on `main`, and a repair of either adds a row of its
    kind to `main`'s changelog (design/verified-facts.md, "A rule's change is counted as a change of `main`"): no read
    reads either, so neither is counted, each left out by its object type's id as the reader's two are. A tag is still
    counted, since a tag can be a scope."""
    w = world()
    w.netbox.branch(REF)
    w.reader.results = {None: [Result(UNLINKED, (), False)]}
    first = w.source.stages(change_of(w))[0]
    w.netbox.changed(WEBHOOK)
    w.netbox.changed(EVENTRULE)
    assert w.source.read(first, SCOPE).findings == ()
    counted = [query for method, path, query, _ in w.netbox.log if path == "core/object-changes/"]
    left = [value for name, value in counted[-1] if name == "changed_object_type_id__n"]
    assert left == [str(JOURNALENTRY), str(BRANCH), str(WEBHOOK), str(EVENTRULE)]
    asked = [dict(query) for _, path, query, _ in w.netbox.log if path == "core/object-types/"]
    assert [(q["app_label"], q["model"]) for q in asked] == [
        ("extras", "journalentry"), ("netbox_branching", "branch"), ("extras", "webhook"), ("extras", "eventrule")]
    uncounted = netbox.source.UNCOUNTED
    assert uncounted == (*UNREAD, "extras.webhook", "extras.eventrule")
    w.netbox.changed(TAG_TYPE)
    (gained,) = w.source.read(first, SCOPE).findings
    assert gained.message.startswith(f"main has gained 1 change since branch {REF}")


def test_main_gained_since_the_branch_took_it_is_a_warning_on_mains_read(world: Callable[..., World]) -> None:
    w = world()
    branch = w.netbox.branch(REF)
    w.reader.results = {None: [Result(UNLINKED, (), False)]}
    first = w.source.stages(change_of(w))[0]
    # The branch's own journal and tags add rows to main's changelog that are no change of main's.
    w.netbox.entry(branch, mark_text("a", ID, SCOPE, OBSERVED))
    w.netbox.changed(168)
    assert w.source.read(first, SCOPE).findings == ()
    w.netbox.changed(40)
    w.netbox.changed(41)
    got = w.source.read(first, SCOPE)
    assert got.blueprint == UNLINKED
    (gained,) = got.findings
    assert (gained.rule, gained.severity, gained.object) == ("stage.main.gained", "warning", REF)
    assert gained.message == (
        f"main has gained 2 changes since branch {REF} was made or last synchronised, at {branch['last_sync']}, "
        "counted of every kind but a journal entry's, a branch's own, a webhook's and an event rule's, and the marks "
        "were taken against main as it stood then: the first stage is main as it stands, so the first step may undo "
        "those changes on the twin. To rehearse against main as it stands, synchronise the branch and seed its steps "
        "again."
    )
    counted = [query for method, path, query, _ in w.netbox.log if path == "core/object-changes/"]
    assert counted[-1] == [("time_after", branch["last_sync"]), ("changed_object_type_id__n", "128"),
                           ("changed_object_type_id__n", "168"), ("changed_object_type_id__n", "1"),
                           ("changed_object_type_id__n", "122"), ("limit", "1")]
    assert [path for _, path in w.netbox.requests()].count("core/object-types/") == 4, "the types are read again"
    # One change, after a sync that moved `last_sync` past the two.
    branch["last_sync"] = w.netbox.now()
    w.netbox.changed(42)
    (gained,) = w.source.read(first, SCOPE).findings
    assert gained.message.startswith(f"main has gained 1 change since branch {REF}")
    # A main the reader refused is counted against nothing.
    w.netbox.log.clear()
    w.reader.results = {None: [Result(None, (finding("scope.empty", obj=SCOPE),), True)]}
    assert w.source.read(first, SCOPE).findings[0].rule == "scope.empty"
    assert w.netbox.log == []


def test_mains_read_of_a_branch_replaced_under_the_rehearsal_is_a_source_error(world: Callable[..., World]) -> None:
    w = world()
    w.netbox.branch(REF)
    w.reader.results = {None: [Result(UNLINKED, (), False)]}
    first = w.source.stages(change_of(w))[0]
    replaced = w.netbox.branch(REF)
    w.netbox.branches.pop(0)
    with pytest.raises(SourceError) as caught:
        w.source.read(first, SCOPE)
    assert str(caught.value) == f"the branch named {REF} is no longer 00000001, but {replaced['schema_id']}"


# A mark read back.


def marked(w: World, label: str, found: str, scope: str = SCOPE) -> Stage:
    """The stage of a mark labelled `label` naming the blueprint `found`, written on `REF`'s branch."""
    branch = w.netbox.branches[0] if w.netbox.branches else w.netbox.branch(REF)
    w.netbox.entry(branch, mark_text(label, found, scope, OBSERVED))
    return by_label(w.source.stages(change_of(w)), label)


def test_a_mark_is_read_back_from_the_core_by_its_id(served: Served, world: Callable[..., World]) -> None:
    found = served.client.put_blueprint(THREE)
    w = world(served.client)
    got = w.source.read(marked(w, "third-link", found), SCOPE)
    assert (got.blueprint, got.findings, got.empty) == (served.client.get_blueprint(found), (), False)
    assert w.reader.calls == []


def test_a_mark_the_core_does_not_hold_is_refused_by_name(served: Served, world: Callable[..., World]) -> None:
    w = world(served.client)
    got = w.source.read(marked(w, "third-link", ID), SCOPE)
    (refused,) = got.findings
    assert (refused.rule, refused.severity, refused.object) == ("mark.unheld", "error", "third-link")
    assert "third-link" in refused.message and ID[:12] in refused.message and ID not in refused.message
    assert refused.message == unheld("third-link", ID)
    assert got.blueprint is None


def test_a_blueprint_the_core_answers_for_another_id_is_refused_as_unheld(
    served: Served, world: Callable[..., World]
) -> None:
    found = served.client.put_blueprint(THREE)
    other = served.client.get_blueprint(served.client.put_blueprint(UNLINKED))
    for answered in (other, {"blueprint_version": "1"}):
        w = world(Wrapped(served.client, get_blueprint=lambda asked, answered=answered: answered))
        got = w.source.read(marked(w, "third-link", found), SCOPE)
        (refused,) = got.findings
        assert (refused.rule, refused.severity, refused.object) == ("mark.unheld", "error", "third-link")
        assert refused.message == unheld("third-link", found, other=True)
        assert got.blueprint is None


def test_a_mark_given_as_one_principal_is_read_as_another(served: Served, world: Callable[..., World]) -> None:
    found = served.client.put_blueprint(THREE)
    w = world(served.other)
    got = w.source.read(marked(w, "third-link", found), SCOPE)
    assert got.blueprint is not None and blueprint_id(got.blueprint) == found


def test_a_mark_read_under_another_scope_is_refused_and_the_core_unasked(
    served: Served, world: Callable[..., World]
) -> None:
    asked: list[str] = []

    def recorder(found: str) -> dict[str, Any]:
        asked.append(found)
        return served.client.get_blueprint(found)

    w = world(Wrapped(served.client, get_blueprint=recorder))
    got = w.source.read(marked(w, "third-link", served.client.put_blueprint(THREE), scope="tag:other"), SCOPE)
    (refused,) = got.findings
    assert (refused.rule, refused.severity, refused.object) == ("mark.scope", "error", "third-link")
    (number,) = [row["id"] for row in w.netbox.entries]
    assert refused.message == (
        f"The mark third-link on branch {REF}, journal entry {number}, was read under scope tag:other, and this "
        f"rehearsal reads under {SCOPE}. Rehearse under tag:other, or have someone who may delete journal entries "
        f"delete entry {number} in NetBox and mark the step again under {SCOPE}, which can be done only while the "
        "branch still stands at that step; otherwise seed the change again."
    )
    assert asked == []


def test_a_core_that_refuses_otherwise_is_raised_on(served: Served, world: Callable[..., World]) -> None:
    problem = ProblemDocument(type="about:blank", title="Unauthorized", status=401, rule="auth.unauthenticated")

    def refusing(found: str) -> dict[str, Any]:
        raise ProblemError(401, problem)

    w = world(Wrapped(served.client, get_blueprint=refusing))
    with pytest.raises(ProblemError) as caught:
        w.source.read(marked(w, "third-link", ID), SCOPE)
    assert caught.value.status == 401


# A mark taken.


def test_mark_puts_the_blueprint_then_writes_the_entry(served: Served, world: Callable[..., World]) -> None:
    w = world(served.client)
    w.netbox.branch(REF)
    held: list[bool] = []

    def on_entry(body: Mapping[str, Any]) -> None:
        named = marks_of([entry(body["comments"])])[0].blueprint_id
        assert named is not None
        held.append(blueprint_id(served.client.get_blueprint(named)) == named)

    w.netbox.on_entry = on_entry
    w.reader.results = {REF: [Result(THREE, (UNVERIFIED,), False)]}
    change = change_of(w)
    made = w.source.mark(change, "third-link", SCOPE)
    assert made == Marked("third-link", blueprint_id(THREE), (UNVERIFIED,))
    assert held == [True], "the entry was written before the core held its blueprint"
    (written,) = w.netbox.entries
    assert written["kind"]["value"] == "info"
    assert written["comments"] == mark_text("third-link", blueprint_id(THREE), SCOPE, OBSERVED)
    assert w.reader.calls == [(REF, SCOPE)]
    assert [stage.label for stage in w.source.stages(change)] == [MAIN, "third-link", HEAD]


def test_a_mark_is_read_as_the_head_is_again_where_it_moved(world: Callable[..., World]) -> None:
    w = world()
    w.netbox.branch(REF)
    w.reader.results = {REF: [Result(None, (MOVED,), False), Result(THREE, (), False)]}
    made = w.source.mark(change_of(w), "third-link", SCOPE)
    assert made.blueprint_id == blueprint_id(THREE)
    assert len(w.reader.calls) == 2


def test_a_read_refused_writes_no_mark(world: Callable[..., World]) -> None:
    w = world()
    w.netbox.branch(REF)
    refusal = (finding("render.failed", obj="n1"),)
    w.reader.results = {REF: [Result(None, refusal, False)]}
    assert w.source.mark(change_of(w), "x", SCOPE) == Marked("x", None, refusal)
    assert w.netbox.requests("POST") == []
    assert isinstance(w.core, Core) and w.core.asked == []


@pytest.mark.parametrize("label", ["third-link", "main", "head", "Third", "", "a" * 41, "-a", "a_b"])
def test_mark_refuses_a_label_the_branch_has_and_one_that_is_no_label(world: Callable[..., World], label: str) -> None:
    w = world()
    branch = w.netbox.branch(REF)
    w.netbox.entry(branch, mark_text("third-link", ID, SCOPE, OBSERVED))
    w.reader.results = {REF: [Result(THREE, (), False)]}
    with pytest.raises(SourceError):
        w.source.mark(change_of(w), label, SCOPE)
    assert w.reader.calls == []
    assert w.netbox.requests("POST") == []
    assert LABEL.fullmatch("a" * 40) and LABEL.fullmatch("n1-address")


# The tag, and the report.


def test_claim_takes_the_tag_off_once_and_a_second_claim_sends_no_write(world: Callable[..., World]) -> None:
    w = world()
    branch = w.netbox.branch(REF, tags=(TAG, "other"))
    change = change_of(w)
    w.netbox.log.clear()
    w.source.claim(change)
    patches = [(path, body) for method, path, _, body in w.netbox.log if method == "PATCH"]
    assert patches == [(f"plugins/branching/branches/{branch['id']}/", {"tags": [{"slug": "other"}]})]
    assert [tag["slug"] for tag in branch["tags"]] == ["other"]
    w.netbox.log.clear()
    w.source.claim(change)
    assert w.netbox.requests() == [("GET", "plugins/branching/branches/")]
    assert TAG == "fylgja-rehearse"


REPORT = Report(status="passed", headline="Rehearsal passed\nVerified.", summary="## Rehearsal passed",
                detail="**Rehearsal detail**: twin `t`.")


@pytest.mark.parametrize(
    "status, kind",
    [("passed", "success"), ("failed", "danger"), ("not_rehearsed", "warning"), ("stopped", "warning"),
     ("surprise", "warning")],
)
def test_a_report_is_one_journal_entry_whose_kind_is_its_status(
    world: Callable[..., World], status: str, kind: str
) -> None:
    w = world()
    branch = w.netbox.branch(REF)
    change = change_of(w)
    w.netbox.log.clear()
    detail = "x" * 100_000
    w.source.post(change, Report(status=status, headline="h", summary="## Rehearsal", detail=detail))
    posts = [body for method, path, _, body in w.netbox.log if method == "POST"]
    assert posts == [{"assigned_object_type": "netbox_branching.branch", "assigned_object_id": branch["id"],
                      "kind": kind, "comments": f"## Rehearsal\n\n{detail}"}]
    assert KIND.get(status, "warning") == kind
    assert w.source.comment_limit is None


def test_the_netbox_source_gives_its_two_sentences(world: Callable[..., World]) -> None:
    w = world()
    for source in (NetBoxSource, w.source):
        assert source.again == "Set the tag `fylgja-rehearse` on the branch again."
        assert source.scope_remedy == "Check the scope the runner is given."
    assert clause(w.source.again) == "set the tag `fylgja-rehearse` on the branch again"


REPORTS = {
    "passed": drafts.passed,
    "failed": drafts.failed_at_four,
    "not_rehearsed": drafts.no_room,
    "stopped": drafts.stopped,
    "held": drafts.held,
}


@pytest.mark.parametrize("make", REPORTS.values(), ids=REPORTS.keys())
def test_each_list_of_the_report_is_given_the_empty_line_netbox_renders_it_by(make: Callable[[], Any]) -> None:
    made = render(make(), limit=None)
    text = f"{made.summary}\n\n{made.detail}"
    lines, out = text.split("\n"), spaced(text).split("\n")
    # Only empty lines are added, and only before an item whose line before is text, not another item.
    edits = difflib.SequenceMatcher(a=lines, b=out, autojunk=False).get_opcodes()
    assert {tag for tag, *_ in edits} <= {"equal", "insert"}
    added = [line for tag, _, _, j1, j2 in edits if tag == "insert" for line in out[j1:j2]]
    assert added and set(added) == {""}, "no list was given its empty line: the test is blind"
    item = ("- ", "1. ", "2. ", "3. ", "4. ", "5. ")
    for k, line in enumerate(out):
        if line.startswith(item) and k:
            assert out[k - 1] == "" or out[k - 1].startswith(item), f"a list follows text at line {k}: {line!r}"
    assert spaced(spaced(text)) == spaced(text)
    assert spaced("a\n\n- b\n- c\n| t |") == "a\n\n- b\n- c\n| t |"
    assert spaced("**Stages**\n1. main: x\n2. head: y") == "**Stages**\n\n1. main: x\n2. head: y"


def test_the_report_filed_has_its_lists_spaced_and_is_otherwise_the_librarys(world: Callable[..., World]) -> None:
    w = world()
    w.netbox.branch(REF)
    made = render(drafts.failed_at_four(), limit=None)
    w.source.post(change_of(w), made)
    (written,) = w.netbox.entries
    assert written["comments"] == spaced(f"{made.summary}\n\n{made.detail}")
    assert written["comments"] != f"{made.summary}\n\n{made.detail}"


# Refusals, and the token.


def test_a_journal_entry_or_a_tag_write_netbox_refuses_is_a_source_error_with_its_status_and_no_token(
    world: Callable[..., World],
) -> None:
    w = world()
    w.netbox.branch(REF, tags=(TAG,))
    change = change_of(w)
    denied = {"detail": f"You do not have permission to perform this action. ({TOKEN})"}
    transport = Transport(ADDRESS, TOKEN)
    texts = [repr(w.source), repr(transport)]
    transport.close()
    w.netbox.scripted[("POST", "extras/journal-entries/")] = [httpx.Response(403, json=denied)]
    with pytest.raises(SourceError) as posted:
        w.source.post(change, REPORT)
    w.netbox.scripted[("PATCH", f"plugins/branching/branches/{w.netbox.branches[0]['id']}/")] = [
        httpx.Response(403, json=denied)
    ]
    with pytest.raises(SourceError) as claimed:
        w.source.claim(change)
    for caught in (posted, claimed):
        assert caught.value.status == 403
        texts += [str(caught.value), repr(caught.value)]
        assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert str(posted.value).startswith("POST /api/extras/journal-entries/: NetBox refused the change source's token")
    assert str(claimed.value).startswith("PATCH /api/plugins/branching/branches/")
    named = any(name in str(caught.value) for caught in (posted, claimed) for name in VARIABLES)
    assert not named, "the source's sentence names a variable, which is the edge's to name"
    leaked = any(TOKEN in text for text in texts)
    assert not leaked, "a text holds the token"
    assert w.netbox.entries == []


def test_netbox_s_words_are_quoted_with_the_token_and_its_halves_hidden(world: Callable[..., World]) -> None:
    w = world()
    w.netbox.branch(REF)
    change = change_of(w)
    key, secret = TOKEN.removeprefix("nbt_").split(".")
    echoed = {"detail": f"Bad comments for {TOKEN}, key {key}, secret {secret}: " + "y" * 2000}
    w.netbox.scripted[("POST", "extras/journal-entries/")] = [httpx.Response(400, json=echoed)]
    with pytest.raises(SourceError) as caught:
        w.source.post(change, REPORT)
    said = str(caught.value)
    assert caught.value.status == 400
    _, marker, quoted = said.partition("HTTP 400: ")
    begins = bool(marker) and quoted.startswith("Bad comments for <redacted>, key <redacted>, secret <redacted>: y")
    assert begins, "the error does not quote NetBox's words with the token hidden"
    assert len(quoted) == 500
    leaked = any(part in said for part in (TOKEN, key, secret))
    assert not leaked, "the error holds the token or a half of it"


def test_netbox_not_reached_is_a_source_error_naming_the_address(monkeypatch: pytest.MonkeyPatch) -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"refused, with {TOKEN}")

    source = NetBoxSource(ADDRESS, TOKEN, DOCUMENT, cast(Client, Core()), transport=httpx.MockTransport(unreachable))
    with pytest.raises(SourceError) as caught:
        source.change(REF)
    source.close()
    said = str(caught.value)
    named = ADDRESS in said and "ConnectError" in said and caught.value.status is None
    assert named, "the error does not name the address and the failure"
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    leaked = TOKEN in said
    assert not leaked, "the error holds the token"


VARIABLES = ("FYLGJA_NETBOX_TOKEN", "FYLGJA_ORCHESTRATOR_NETBOX_TOKEN")
READERS = "HTTP 403: NetBox refused the token FYLGJA_NETBOX_TOKEN holds, or its account may not read this (reader)"


def test_a_refused_token_of_the_readers_is_the_sources_error_by_its_status(world: Callable[..., World]) -> None:
    w = world()
    w.netbox.branch(REF)
    head = w.source.stages(change_of(w))[-1]
    texts: list[str] = []
    for status in (401, 403):
        w.reader.results = {REF: [NetBoxError(f"reading dcim.device (branch {REF}): {READERS}", status)]}
        with pytest.raises(SourceError) as caught:
            w.source.read(head, SCOPE)
        said = str(caught.value)
        assert caught.value.status == status
        assert said.startswith(f"a read of branch {REF} through the reader: NetBox refused the change source's token")
        assert said.endswith(f"HTTP {status} from NetBox at {ADDRESS}")
        # The variable is the edge's to name, as for the Infrahub source: the source is given its token.
        assert not any(name in said or name in repr(caught.value) for name in VARIABLES), said
        assert "(reader)" not in said, "the reader's words were quoted"
        assert caught.value.__cause__ is None and caught.value.__context__ is None
        texts += [said, repr(caught.value), repr(w.source)]
    # At the reader's connect, too, and for `main`.
    w2 = world()
    w2.netbox.branch(REF)
    w2.reader.refuse = NetBoxError(f"reading NetBox's version: {READERS}", 403)
    with pytest.raises(SourceError) as caught:
        w2.source.read(w2.source.stages(change_of(w2))[0], SCOPE)
    assert caught.value.status == 403
    assert str(caught.value).startswith("the reader's connect: NetBox refused the change source's token")
    texts.append(str(caught.value))
    leaked = any(TOKEN in text for text in texts)
    assert not leaked, "a text holds the token"


def test_any_other_error_of_the_readers_is_raised_on(world: Callable[..., World]) -> None:
    w = world()
    w.netbox.branch(REF)
    head = w.source.stages(change_of(w))[-1]
    w.reader.results = {REF: [NetBoxError("reading dcim.device: HTTP 500: boom", 500)]}
    with pytest.raises(NetBoxError):
        w.source.read(head, SCOPE)


@pytest.mark.parametrize(
    "address, token, ca, refused",
    [
        ("ftp://netbox.example", TOKEN, None, InvalidAddress),
        (ADDRESS, "a token with spaces", None, InvalidToken),
        (ADDRESS, TOKEN, Path("/nonexistent/fylgja-ca.pem"), InvalidCA),
    ],
)
def test_an_address_a_token_or_a_ca_the_clients_rules_refuse_is_refused_when_the_source_is_made(
    monkeypatch: pytest.MonkeyPatch, address: str, token: str, ca: Path | None, refused: type[ValueError]
) -> None:
    # The reader's connect is given what the source was, and refuses by the same rules: so it is refused here, before
    # any request, as the Infrahub source's is, and the connect never meets it.
    asked: list[httpx.Request] = []
    connected: list[object] = []
    monkeypatch.setattr(module, "connect", lambda *args, **kwargs: connected.append(args))

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request)
        return httpx.Response(200, json={})

    with pytest.raises(refused) as caught:
        NetBoxSource(address, token, DOCUMENT, cast(Client, Core()), ca=ca, transport=httpx.MockTransport(handler))
    said = str(caught.value)
    assert address not in said and token not in said and "fylgja-ca" not in said
    assert (asked, connected) == ([], [])


def test_no_text_the_source_makes_holds_its_token(
    served: Served, world: Callable[..., World], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    w = world(served.client)
    w.netbox.branch(REF, tags=(TAG,))
    w.reader.results = {None: [Result(UNLINKED, (), False)], REF: [Result(THREE, (UNVERIFIED,), False)]}
    w.netbox.changed(40)
    change = change_of(w)
    made = w.source.mark(change, "third-link", SCOPE)
    w.source.claim(change)
    reads = [w.source.read(stage, SCOPE) for stage in w.source.stages(change)]
    w.source.post(change, render(drafts.passed(), limit=None))
    texts = [repr(w.source), repr(w.source._transport), repr(made), *caplog.messages]
    texts += [f.message for got in reads for f in got.findings] + [f.message for f in made.findings]
    texts += [json.dumps(body) for *_, body in w.netbox.log] + [row["comments"] for row in w.netbox.entries]
    assert len(w.netbox.entries) == 2 and any(f.rule == "stage.main.gained" for f in reads[0].findings)
    leaked = any(TOKEN in text for text in texts)
    assert not leaked, "a text holds the token"


def test_the_transport_reads_nothing_of_the_environment_and_gives_each_request_30_s() -> None:
    transport = Transport(ADDRESS, TOKEN, transport=httpx.MockTransport(lambda request: httpx.Response(200)))
    http = transport._http
    settings = (http.trust_env, http.timeout)
    transport.close()
    assert settings == (False, httpx.Timeout(30.0, connect=5.0))


def test_close_closes_the_sources_connections_and_never_the_cores(served: Served, world: Callable[..., World]) -> None:
    w = world(served.client)
    w.netbox.branch(REF)
    w.reader.results = {REF: [Result(THREE, (), False)]}
    w.source.read(w.source.stages(change_of(w))[-1], SCOPE)
    w.source.close()
    assert w.reader.conns[0].closed
    assert served.client.list_twins() == []


def test_the_package_exports_the_sources_names() -> None:
    assert netbox.NetBoxSource is NetBoxSource and netbox.SourceError is SourceError
    assert issubclass(netbox.NoChange, netbox.SourceError) and issubclass(netbox.Unready, netbox.SourceError)
    assert (netbox.MAIN, netbox.HEAD, netbox.MARK_PREFIX, netbox.MOVED_READS) == ("main", "head", "Fylgja stage: ", 3)
    assert rules.STAGE_REFUSED == "stage.refused"


def test_every_remedy_the_source_gives_says_what_can_be_done(served: Served, world: Callable[..., World]) -> None:
    # A mark is never taken of a label the branch has (D-097), and NetBox reads no branch as it stood earlier: no
    # sentence may ask a label taken again without first saying its entry is deleted, nor ask a past step marked anew.
    w = world(served.client)
    branch = w.netbox.branch(REF)
    held = served.client.put_blueprint(THREE)
    for text in (
        mark_text("dup", held, SCOPE, OBSERVED), mark_text("dup", held, SCOPE, OBSERVED),
        mark_text("bad", held[:63], SCOPE, OBSERVED), f"{MARK_PREFIX}\n- blueprint: {held}",
        mark_text(HEAD, held, SCOPE, OBSERVED), mark_text("other", held, "tag:other", OBSERVED),
        mark_text("lost", ID, SCOPE, OBSERVED),
    ):
        w.netbox.entry(branch, text)
    w.netbox.changed(40)
    w.reader.results = {None: [Result(UNLINKED, (), False)]}
    stages = w.source.stages(change_of(w))
    said = [f for stage in stages[:-1] for f in w.source.read(stage, SCOPE).findings]
    # Every rule the source files is said here, so that one added later is held too.
    assert {f.rule for f in said} == set(module.SEVERITY), "the test is blind"
    for f in said:
        lowered = f.message.lower()
        assert not any(words in lowered for words in ("take it again", "mark the branch again",
                                                      "mark its steps again")), f.message
        if "mark the step again" in lowered:
            assert lowered.index("delete entry") < lowered.index("mark the step again"), f.message
        assert "seed" in lowered or f.rule == "mark.duplicate", f.message
