"""The Infrahub change source (D-085, D-088) over rows each test builds and an `httpx.MockTransport` whose handler the
test writes, never an answer captured from Infrahub (D-034, D-083): the open proposed change found by its branch; its
stages ordered, the branch point, the marks by time and the head, each with its pin; the head read after a bounded
wait for the artifact validation, at the later of its `head` and the validation's completion; a mark given the
completion in force at its time, and the branch point none, with a warning where `main` has moved since the cut; the
reader's `read` and `head` replaced by fakes that record what they were given; and the report posted as one thread of
two comments, measured before anything is sent, with the token in no error's text."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import httpx
import pytest
from fylgja_core.findings import Finding
from fylgja_infrahub import Infrahub, InfrahubError, Refused, Result, document

from fylgja_orchestrator.infrahub import source as module
from fylgja_orchestrator.infrahub.source import (
    BRANCH_POINT,
    HEAD,
    THREAD_LABEL,
    VALIDATION_APPEAR_S,
    VALIDATION_POLL_S,
    VALIDATION_WAIT_S,
    InfrahubSource,
    Mark,
    NoChange,
    Pin,
    mark_time,
    stages_of,
    validated,
)
from fylgja_orchestrator.infrahub.transport import SourceError, Transport
from fylgja_orchestrator.rehearsal import Change, Read, Report, Stage

ROOT = Path(__file__).resolve().parents[2]
BLUEPRINTS = ROOT / "testdata" / "blueprint"
DOCUMENT = document.load(ROOT / "infrahub" / "seed" / "reader.yaml")

ADDRESS = "http://infrahub.example"
TOKEN = "Not-a.real_token~0+/9=="
"""A token as Infrahub's are: an RFC 6750 bearer token, whose characters a header carries."""
SCOPE = "tag:fylgja"
REF = "change-1"
PC = "pc-1"
NAME = "Rehearse change-1"
CUT = "2026-11-09T09:00:00.000000Z"
A_AT = "2026-11-09T10:00:01+00:00"
B_AT = "2026-11-09T10:00:02.000000Z"
HEAD_AT = "2026-11-09T11:00:00.000001+00:00"
COMPLETED = "2026-11-09T11:05:00.250000Z"
EARLIER = "2026-11-09T10:30:00.000000Z"
MAIN_HEAD = "2026-11-09T12:00:00.000001+00:00"
T9 = "2026-11-10T21:17:57.875103Z"

CHANGE = Change(REF, PC, NAME, f'proposed change "{NAME}", branch {REF} into main')


def blueprint(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((BLUEPRINTS / name).read_text())
    return loaded


THREE = blueprint("three-node.json")
TWO = blueprint("steps/two-node.json")


# A fake Infrahub. Each operation a test names answers from what the request carried: its variables, its branch and its
# `at`; a body is sent as JSON under HTTP 200, and an `httpx.Response` as it is.
Answer = Callable[[Mapping[str, Any], str, str | None], object]


class Hub:
    """A fake Infrahub: `GET /api/info` answers 1.11.11, and each `POST /graphql/<branch>` the answer of its operation.
    `asked` holds each GraphQL request, `(operation, branch, at, variables)`, and `calls` the same in the order shared
    with the fake reader, `("ask", operation, at)`; `versions` counts the version's reads."""

    def __init__(self, calls: list[tuple[Any, ...]], **answers: Answer) -> None:
        self.calls = calls
        self.answers = answers
        self.asked: list[tuple[str, str, str | None, dict[str, Any]]] = []
        self.versions = 0
        self.keyed = True
        self.info_status = 200

    def __call__(self, request: httpx.Request) -> httpx.Response:
        # Compared outside any assert, so that no failure prints the header (core/tests/test_config.py's `same`).
        self.keyed = self.keyed and request.headers.get("X-INFRAHUB-KEY") == TOKEN
        if request.url.path == "/api/info":
            self.versions += 1
            if self.info_status != 200:
                return httpx.Response(self.info_status, json={"errors": [{"message": "Invalid token"}]})
            return httpx.Response(200, json={"deployment_id": "d", "version": "1.11.11"})
        assert request.method == "POST", request.url
        assert request.url.path.startswith("/graphql/"), request.url
        body = json.loads(request.content)
        operation, variables = body["operationName"], body["variables"]
        branch, at = unquote(request.url.path.removeprefix("/graphql/")), request.url.params.get("at")
        self.asked.append((operation, branch, at, variables))
        self.calls.append(("ask", operation, at))
        assert operation in self.answers, f"no answer for {operation}"
        answer = self.answers[operation](variables, branch, at)
        return answer if isinstance(answer, httpx.Response) else httpx.Response(200, json=answer)

    @property
    def operations(self) -> list[str]:
        return [operation for operation, *_ in self.asked]


def always(body: object) -> Answer:
    return lambda variables, branch, at: body


def in_turn(*bodies: object) -> Answer:
    """Each body in turn, the last for every request after."""
    given = iter(bodies)
    last: list[object] = []

    def answer(variables: Mapping[str, Any], branch: str, at: str | None) -> object:
        last[:] = [next(given, *last)]
        return last[0]

    return answer


def proposed(*changes: tuple[str, str, str, bool]) -> dict[str, Any]:
    """`CoreProposedChange` answering `changes`, each `(id, name, destination, is_draft)`, open, from `REF`."""
    edges = [
        {
            "node": {
                "id": found,
                "name": {"value": name},
                "is_draft": {"value": draft},
                "source_branch": {"value": REF},
                "destination_branch": {"value": destination},
                "state": {"value": "open"},
            }
        }
        for found, name, destination, draft in changes
    ]
    return {"data": {"CoreProposedChange": {"count": len(edges), "edges": edges}}}


def branch(cut: str | None) -> dict[str, Any]:
    """`Branch` answering `REF` with `cut` as its `branched_from`, or no branch where it is None."""
    listed = [{"name": REF, "branched_from": cut, "created_at": cut}] if cut is not None else []
    return {"data": {"Branch": listed}}


def marks(*rows: tuple[str, str | None, str | None, str]) -> dict[str, Any]:
    """`FylgjaStage` answering `rows`, each `(label, as_of, description, created_at)`."""
    edges = [
        {
            "node": {
                "id": f"m-{label}",
                "label": {"value": label},
                "as_of": {"value": as_of},
                "description": {"value": description},
            },
            "node_metadata": {"created_at": created, "updated_at": created},
        }
        for label, as_of, description, created in rows
    ]
    return {"data": {"FylgjaStage": {"count": len(edges), "edges": edges}}}


def validators(*rows: tuple[str, str | None]) -> dict[str, Any]:
    """`CoreArtifactValidator` answering `rows`, each `(state, completed_at)`."""
    edges = [
        {"node": {"id": f"v-{k}", "state": {"value": state}, "completed_at": {"value": completed}}}
        for k, (state, completed) in enumerate(rows)
    ]
    return {"data": {"CoreArtifactValidator": {"count": len(edges), "edges": edges}}}


def created(kind: str, made: str) -> dict[str, Any]:
    return {"data": {kind: {"ok": True, "object": {"id": made}}}}


class Reader:
    """The reader's `head` and `read`, replaced: `heads` answers `head` by branch, a time or an exception raised;
    `results` answers `read` by branch and time, an unpinned three-node blueprint where it is None. Each call is
    recorded in `calls`, `("head", branch)` and `("read", branch, at, generated_since)`, and `conns` holds each
    connection either was given."""

    def __init__(
        self,
        calls: list[tuple[Any, ...]],
        heads: Mapping[str, str | Exception] | None = None,
        results: Callable[[str, str], Result] | None = None,
    ) -> None:
        self.calls = calls
        self.heads = heads or {}
        self.results = results
        self.conns: list[object] = []

    def head(self, conn: object, *, branch: str, scope: str) -> str:
        self.conns.append(conn)
        self.calls.append(("head", branch))
        assert scope == SCOPE
        answer = self.heads[branch]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def read(
        self,
        conn: object,
        *,
        branch: str,
        at: str,
        scope: str,
        document: object,
        generated_since: str | None = None,
    ) -> Result:
        self.conns.append(conn)
        self.calls.append(("read", branch, at, generated_since))
        assert scope == SCOPE
        assert document is DOCUMENT
        return self.results(branch, at) if self.results is not None else Result(THREE, (), False)


class Clock:
    """A clock `sleep` advances, each sleep recorded."""

    def __init__(self) -> None:
        self.t = 1000.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds


class World:
    """A source over a fake Infrahub, a fake reader and a fake clock, sharing one record of calls."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, **answers: Answer) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.hub = Hub(self.calls, **answers)
        self.reader = Reader(self.calls)
        self.clock = Clock()
        monkeypatch.setattr(module, "head", self.reader.head)
        monkeypatch.setattr(module, "read", self.reader.read)
        self.source = InfrahubSource(
            ADDRESS,
            TOKEN,
            DOCUMENT,
            transport=httpx.MockTransport(self.hub),
            sleep=self.clock.sleep,
            clock=self.clock.now,
        )


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., World]]:
    made: list[World] = []

    def make(**answers: Answer) -> World:
        made.append(World(monkeypatch, **answers))
        return made[-1]

    yield make
    for each in made:
        each.source.close()
        assert each.hub.keyed, "a request was sent without the token in X-INFRAHUB-KEY"


def staged(cut: str | None, *found: Mark) -> tuple[Stage, ...]:
    return stages_of(REF, "main", cut, found, change=PC)


def by_label(stages: Sequence[Stage], label: str) -> Stage:
    return next(stage for stage in stages if stage.label == label)


# The stages and their pins.


def test_the_stages_are_the_branch_point_the_marks_in_time_order_and_the_head() -> None:
    stages = staged(CUT, Mark("b", "", B_AT, None), Mark("a", "", A_AT, None))
    assert [stage.label for stage in stages] == ["branch-point", "a", "b", "head"]
    assert [stage.pin for stage in stages] == [
        Pin("branch-point", "main", CUT, PC),
        Pin("mark", REF, A_AT, PC),
        Pin("mark", REF, B_AT, PC),
        Pin("head", REF, "", PC),
    ]
    assert (BRANCH_POINT, HEAD) == ("branch-point", "head")
    point, head = stages[0], stages[-1]
    assert (point.description, point.where) == (f"main as it was when {REF} was cut", f"branch main at {CUT}")
    assert (head.description, head.where) == (f"the head of {REF}", f"the head of branch {REF}")


def test_two_marks_at_one_instant_are_ordered_by_label_and_one_with_no_time_comes_last() -> None:
    # One instant written two ways: the `+00:00` layout and `Z` with six digits.
    stages = staged(
        CUT,
        Mark("z-untimed", "", None, None),
        Mark("y", "", "2026-11-09T10:00:01.000000Z", None),
        Mark("x", "", A_AT, None),
        Mark("w", "", B_AT, None),
        Mark("a-untimed", "", None, None),
    )
    assert [stage.label for stage in stages] == ["branch-point", "x", "y", "w", "a-untimed", "z-untimed", "head"]
    assert by_label(stages, "y").pin == Pin("mark", REF, "2026-11-09T10:00:01.000000Z", PC)
    assert by_label(stages, "a-untimed").pin == Pin("mark", REF, "", PC)


def test_a_branch_with_no_cut_time_has_no_branch_point() -> None:
    assert [stage.label for stage in stages_of(REF, "main", None, [], change=PC)] == ["head"]
    assert [stage.label for stage in staged(None, Mark("a", "", A_AT, None))] == ["a", "head"]


def test_a_marks_time_is_its_as_of_else_the_time_infrahub_gave_its_writing() -> None:
    assert mark_time(Mark("m", "", "T1", "T2")) == "T1"
    assert mark_time(Mark("m", "", None, "T2")) == "T2"
    assert mark_time(Mark("m", "", None, None)) is None
    written = staged(CUT, Mark("m", "", None, B_AT))
    assert by_label(written, "m").pin == Pin("mark", REF, B_AT, PC)


def test_a_mark_whose_time_does_not_parse_comes_last_and_is_refused_alone(world: Callable[..., World]) -> None:
    stages = staged(
        CUT,
        Mark("z", "", None, None),
        Mark("bad", "", "2026-11-09 sometime", None),
        Mark("naive", "", "2026-11-09T10:00:00", None),
        Mark("a", "", A_AT, None),
    )
    assert [stage.label for stage in stages] == ["branch-point", "a", "bad", "naive", "z", "head"]
    bad = by_label(stages, "bad")
    assert bad.pin == Pin("mark", REF, "2026-11-09 sometime", PC)
    assert bad.where == f"branch {REF} at '2026-11-09 sometime', which does not parse"

    w = world()
    for label in ("bad", "naive"):
        got = w.source.read(by_label(stages, label), SCOPE)
        [finding] = got.findings
        assert (got.blueprint, got.empty) == (None, False)
        assert (finding.rule, finding.severity, finding.object) == ("stage.at.unresolved", "error", label)
        assert "does not parse" in finding.message
    assert w.calls == []


def test_a_marks_where_names_its_time_and_its_description_is_its_own_or_its_label() -> None:
    stages = staged(CUT, Mark("a", "the third link", A_AT, None), Mark("b", "", None, None))
    a, b = by_label(stages, "a"), by_label(stages, "b")
    assert (a.description, a.where) == ("the third link", f"branch {REF} at {A_AT}")
    assert (b.description, b.where) == ("the mark b", f"branch {REF}, its time unread")


# The wait for the artifact validation.


class Polled:
    """A scripted poll: each answer in turn, the last for every poll after, and the clock's time at each poll."""

    def __init__(self, clock: Clock, *answers: Sequence[tuple[str, str | None]]) -> None:
        self.clock = clock
        self.answers = list(answers)
        self.at: list[float] = []

    def __call__(self) -> Sequence[tuple[str, str | None]]:
        self.at.append(self.clock.t)
        return self.answers[min(len(self.at), len(self.answers)) - 1]


def test_the_wait_ends_when_every_validator_has_completed() -> None:
    clock = Clock()
    poll = Polled(
        clock,
        [("queued", None)],
        [("in_progress", None), ("completed", EARLIER)],
        [("completed", T9), ("completed", EARLIER)],
    )
    assert validated(poll, sleep=clock.sleep, clock=clock.now) == (T9, False)
    assert poll.at == [1000.0, 1005.0, 1010.0]
    assert clock.slept == [VALIDATION_POLL_S] * 2 == [5.0, 5.0]


def test_the_wait_gives_up_at_its_bound_and_says_so() -> None:
    clock = Clock()
    poll = Polled(clock, [("in_progress", None)])
    assert validated(poll, sleep=clock.sleep, clock=clock.now) == (None, True)
    assert VALIDATION_WAIT_S == 240.0
    assert poll.at == [1000.0 + 5 * k for k in range(49)]

    clock = Clock()
    partly = Polled(clock, [("completed", EARLIER), ("in_progress", None)])
    assert validated(partly, sleep=clock.sleep, clock=clock.now) == (EARLIER, True)
    assert partly.at[-1] == 1240.0

    # One run again whose state reads in_progress while its completed_at still holds the run before is not done.
    clock = Clock()
    rerun = Polled(clock, [("in_progress", EARLIER)])
    assert validated(rerun, sleep=clock.sleep, clock=clock.now) == (None, True)


def test_the_wait_ends_after_120_s_when_no_validator_appears() -> None:
    clock = Clock()
    poll = Polled(clock, [])
    assert validated(poll, sleep=clock.sleep, clock=clock.now) == (None, False)
    # One was read to appear 70.5 s after a create that queued behind another's (P5-58).
    assert VALIDATION_APPEAR_S == 120.0
    assert poll.at == [1000.0 + 5 * k for k in range(25)]

    # One that appears within the 120 s is waited for under the whole bound.
    clock = Clock()
    late = Polled(clock, *([[]] * 24), [("in_progress", "")], [("completed", T9)])
    assert validated(late, sleep=clock.sleep, clock=clock.now) == (T9, False)
    assert late.at[-1] == 1125.0


# A stage read.


def test_a_reserved_label_and_a_mark_with_no_time_are_refused_without_a_read(world: Callable[..., World]) -> None:
    w = world()
    stages = staged(CUT, Mark("head", "", A_AT, None), Mark(BRANCH_POINT, "", B_AT, None), Mark("m", "", None, None))
    marked = [stage for stage in stages if isinstance(stage.pin, Pin) and stage.pin.kind == "mark"]
    assert [stage.label for stage in marked] == ["head", "branch-point", "m"]

    rules = ["stage.label.reserved", "stage.label.reserved", "stage.at.unresolved"]
    for stage, rule in zip(marked, rules, strict=True):
        got = w.source.read(stage, SCOPE)
        assert got.blueprint is None
        assert got.empty is False
        [finding] = got.findings
        assert (finding.rule, finding.severity, finding.object) == (rule, "error", stage.label)
        assert finding.message
    assert w.calls == []
    assert w.hub.versions == 0


def test_the_head_is_pinned_after_the_wait_and_given_the_validations_completion(world: Callable[..., World]) -> None:
    w = world(ArtifactValidation=in_turn(validators(("in_progress", "")), validators(("completed", COMPLETED))))
    w.reader.heads = {REF: HEAD_AT}
    head = staged(CUT)[-1]
    got = w.source.read(head, SCOPE)
    assert got == Read(THREE, (), False)
    # The completion is later than the head: the read is pinned there, never at a `generated_since` past `at`.
    assert w.calls == [
        ("ask", "ArtifactValidation", None),
        ("ask", "ArtifactValidation", None),
        ("head", REF),
        ("read", REF, COMPLETED, COMPLETED),
    ]
    assert w.clock.slept == [5.0]
    assert [(branch, at, variables) for _, branch, at, variables in w.hub.asked] == [("main", None, {"change": PC})] * 2

    w = world(ArtifactValidation=always(validators(("completed", EARLIER))))
    w.reader.heads = {REF: HEAD_AT}
    w.source.read(head, SCOPE)
    assert w.calls[-2:] == [("head", REF), ("read", REF, HEAD_AT, EARLIER)]


def test_a_head_with_no_validation_is_read_at_its_head_alone_and_says_so(world: Callable[..., World]) -> None:
    w = world(ArtifactValidation=always(validators()))
    w.reader.heads = {REF: HEAD_AT}
    got = w.source.read(staged(CUT)[-1], SCOPE)
    assert w.calls[-2:] == [("head", REF), ("read", REF, HEAD_AT, None)]
    assert w.clock.t == 1120.0
    assert (got.blueprint, got.empty) == (THREE, False)
    assert [(f.rule, f.severity, f.object) for f in got.findings] == [("stage.validation.absent", "info", REF)]
    assert got.findings[0].message == (
        f"No artifact validation of proposed change {PC} appeared 120 s after it was first asked for, so the head of "
        f"{REF} is read on its artifacts' stamps alone, with no generated_since."
    )


def test_a_wait_that_passed_its_bound_gives_no_generated_since_and_files_the_warning(
    world: Callable[..., World],
) -> None:
    w = world(ArtifactValidation=always(validators(("completed", EARLIER), ("in_progress", ""))))
    stale = Finding(rule="artifact.stale", severity="error", object="n1", message="n1's configuration is stale.")
    w.reader.heads = {REF: HEAD_AT}
    w.reader.results = lambda branch, at: Result(None, (stale,), False)
    got = w.source.read(staged(CUT)[-1], SCOPE)
    assert w.calls[-2:] == [("head", REF), ("read", REF, HEAD_AT, None)]
    assert w.clock.t == 1240.0
    assert got.blueprint is None
    assert got.empty is False
    assert [(f.rule, f.severity, f.object) for f in got.findings] == [
        ("artifact.stale", "error", "n1"),
        ("stage.validation.unfinished", "warning", REF),
    ]
    assert got.findings[1].message == (
        f"The artifact validation of proposed change {PC} had not completed 240 s after it was first asked for, so "
        f"the head of {REF} is read on its artifacts' stamps alone, with no generated_since."
    )


def test_a_head_stage_whose_scope_is_refused_is_a_read_of_its_findings(world: Callable[..., World]) -> None:
    empty = Finding(rule="scope.empty", severity="error", object=SCOPE, message="No device carries the tag.")
    cut = Finding(rule="read.incomplete", severity="error", object="DcimDevice", message="2 of 3 were read.")
    w = world(ArtifactValidation=always(validators(("completed", COMPLETED))))
    w.reader.heads = {REF: Refused([empty])}
    assert w.source.read(staged(CUT)[-1], SCOPE) == Read(None, (empty,), True)

    w.reader.heads = {REF: Refused([cut])}
    assert w.source.read(staged(CUT)[-1], SCOPE) == Read(None, (cut,), False)
    assert [call for call in w.calls if call[0] == "read"] == []

    # A wait that passed its bound keeps its warning beside the refusal's findings.
    w = world(ArtifactValidation=always(validators(("in_progress", ""))))
    w.reader.heads = {REF: Refused([empty])}
    got = w.source.read(staged(CUT)[-1], SCOPE)
    assert (got.blueprint, got.empty) == (None, True)
    assert [(f.rule, f.severity) for f in got.findings] == [
        ("scope.empty", "error"),
        ("stage.validation.unfinished", "warning"),
    ]


def test_an_infrahub_error_or_a_value_error_from_head_is_raised_on(world: Callable[..., World]) -> None:
    w = world(ArtifactValidation=always(validators(("completed", COMPLETED))))
    for raised in (InfrahubError("reading Events (branch change-1): HTTP 500: no", 500), ValueError("no stamp")):
        w.reader.heads = {REF: raised}
        with pytest.raises(type(raised)) as caught:
            w.source.read(staged(CUT)[-1], SCOPE)
        assert caught.value is raised


def test_a_mark_is_given_the_completion_in_force_at_its_time(world: Callable[..., World]) -> None:
    in_force = {
        A_AT: validators(("in_progress", "")),
        B_AT: validators(("completed", EARLIER), ("completed", COMPLETED)),
    }
    w = world(ArtifactValidation=lambda variables, branch, at: in_force[at or ""])
    stages = staged(CUT, Mark("a", "", A_AT, None), Mark("b", "", B_AT, None))
    for label in ("a", "b"):
        assert w.source.read(by_label(stages, label), SCOPE) == Read(THREE, (), False)
    assert w.calls == [
        ("ask", "ArtifactValidation", A_AT),
        ("read", REF, A_AT, None),
        ("ask", "ArtifactValidation", B_AT),
        ("read", REF, B_AT, COMPLETED),
    ]
    assert [(branch, variables) for _, branch, _, variables in w.hub.asked] == [("main", {"change": PC})] * 2
    assert w.clock.slept == []


def answered(w: World) -> Stage:
    """The branch point of the change `w`'s source answers, the calls of its finding cleared."""
    point = w.source.stages(w.source.change(REF))[0]
    assert point.pin == Pin("branch-point", "main", CUT, PC)
    w.calls.clear()
    return point


CHANGED: dict[str, Answer] = {
    "ProposedChange": always(proposed((PC, NAME, "main", False))),
    "BranchCut": always(branch(CUT)),
    "Marks": always(marks()),
}


def test_the_branch_point_is_given_none_and_warns_when_main_has_moved(world: Callable[..., World]) -> None:
    w = world(**CHANGED)
    w.reader.heads = {"main": MAIN_HEAD}
    w.reader.results = lambda branch, at: Result(TWO if at == CUT else THREE, (), False)
    point = answered(w)
    got = w.source.read(point, SCOPE)
    assert w.calls == [("read", "main", CUT, None), ("head", "main"), ("read", "main", MAIN_HEAD, None)]
    assert got.blueprint == TWO
    assert got.empty is False
    [moved] = got.findings
    assert (moved.rule, moved.severity, moved.object) == ("stage.main.moved", "warning", "main")
    assert moved.message == (
        f"main has moved since {REF} was cut at {CUT}: the branch point reads main as it was then."
    )

    # Written to since, but holding the same blueprint: no warning.
    w = world(**CHANGED)
    w.reader.heads = {"main": MAIN_HEAD}
    assert w.source.read(answered(w), SCOPE) == Read(THREE, (), False)
    assert w.calls == [("read", "main", CUT, None), ("head", "main"), ("read", "main", MAIN_HEAD, None)]

    # A branch point the reader refuses at the cut is answered as it is, and main's head is not asked.
    stale = Finding(rule="artifact.stale", severity="error", object="n1", message="n1's configuration is stale.")
    w = world(**CHANGED)
    w.reader.heads = {"main": MAIN_HEAD}
    w.reader.results = lambda branch, at: Result(None, (stale,), False)
    assert w.source.read(answered(w), SCOPE) == Read(None, (stale,), False)
    assert w.calls == [("read", "main", CUT, None)]


def test_the_branch_point_stands_by_the_cut_when_mains_head_is_refused_or_unread(world: Callable[..., World]) -> None:
    # main's head refused because no device is in scope there now: the scoped devices are gone since the cut, a move.
    empty = Finding(rule="scope.empty", severity="error", object=SCOPE, message="No device carries the tag.")
    w = world(**CHANGED)
    w.reader.heads = {"main": Refused([empty])}
    got = w.source.read(answered(w), SCOPE)
    assert w.calls == [("read", "main", CUT, None), ("head", "main")]
    assert (got.blueprint, got.empty) == (THREE, False)
    assert [(f.rule, f.severity, f.object) for f in got.findings] == [("stage.main.moved", "warning", "main")]

    # Refused otherwise: no comparison, and the cut's read as it stands.
    cut = Finding(rule="read.incomplete", severity="error", object="DcimDevice", message="2 of 3 were read.")
    w = world(**CHANGED)
    w.reader.heads = {"main": Refused([cut])}
    assert w.source.read(answered(w), SCOPE) == Read(THREE, (), False)
    assert w.calls == [("read", "main", CUT, None), ("head", "main")]

    # main read at its head gives no blueprint: no warning.
    stale = Finding(rule="artifact.stale", severity="error", object="n1", message="n1's configuration is stale.")
    w = world(**CHANGED)
    w.reader.heads = {"main": MAIN_HEAD}
    w.reader.results = lambda branch, at: Result(THREE, (), False) if at == CUT else Result(None, (stale,), False)
    assert w.source.read(answered(w), SCOPE) == Read(THREE, (), False)
    assert w.calls == [("read", "main", CUT, None), ("head", "main"), ("read", "main", MAIN_HEAD, None)]


def test_the_branch_point_of_an_unanswered_change_is_not_read(world: Callable[..., World]) -> None:
    point = staged(CUT)[0]

    # A branch point of a change this source has not answered names no branch to warn of, and is not read.
    w = world()
    with pytest.raises(SourceError):
        w.source.read(point, SCOPE)
    assert w.calls == []


def test_the_source_connects_to_the_reader_once_at_its_first_read(world: Callable[..., World]) -> None:
    w = world(**CHANGED, ArtifactValidation=always(validators(("completed", COMPLETED))))
    w.reader.heads = {REF: HEAD_AT, "main": MAIN_HEAD}
    change = w.source.change(REF)
    stages = w.source.stages(change)
    assert w.hub.versions == 0
    for stage in stages:
        w.source.read(stage, SCOPE)
    assert w.hub.versions == 1
    assert len(w.reader.conns) == 5  # the branch point's head and two reads, and the head's head and read
    assert all(conn is w.reader.conns[0] for conn in w.reader.conns)
    assert isinstance(w.reader.conns[0], Infrahub)


# The change.


def test_the_change_is_the_open_proposed_change_of_its_branch(world: Callable[..., World]) -> None:
    w = world(
        ProposedChange=always(proposed((PC, NAME, "main", True))),
        BranchCut=always(branch(CUT)),
        Marks=always(marks(("b", B_AT, "the address", B_AT), ("a", None, None, A_AT))),
    )
    assert w.source.comment_limit == 4092
    change = w.source.change(REF)
    assert change == CHANGE
    assert w.source.is_draft(change) is True
    stages = w.source.stages(change)
    assert [(stage.label, stage.description, stage.pin) for stage in stages] == [
        ("branch-point", f"main as it was when {REF} was cut", Pin("branch-point", "main", CUT, PC)),
        ("a", "the mark a", Pin("mark", REF, A_AT, PC)),
        ("b", "the address", Pin("mark", REF, B_AT, PC)),
        ("head", f"the head of {REF}", Pin("head", REF, "", PC)),
    ]
    assert [(operation, branch, at, variables) for operation, branch, at, variables in w.hub.asked] == [
        ("ProposedChange", "main", None, {"branch": REF}),
        ("BranchCut", "main", None, {"name": REF}),
        ("Marks", "main", None, {"branch": REF}),
    ]


def test_the_infrahub_source_gives_phase_8s_two_sentences(world: Callable[..., World]) -> None:
    # The words the library said for every source before the seam gave them: Infrahub's check is asked again by
    # running the checks.
    sentences = ("Run the checks again.", "Check the scope the checks run with.")
    assert (InfrahubSource.again, InfrahubSource.scope_remedy) == sentences
    w = world()
    assert (w.source.again, w.source.scope_remedy) == sentences


def test_no_open_proposed_change_of_the_branch_is_no_change(world: Callable[..., World]) -> None:
    w = world(ProposedChange=always(proposed()))
    with pytest.raises(NoChange) as caught:
        w.source.change(REF)
    assert isinstance(caught.value, SourceError)
    assert str(caught.value) == f"no open proposed change has source branch {REF}"


def test_two_open_proposed_changes_of_one_branch_are_refused_naming_both(world: Callable[..., World]) -> None:
    w = world(ProposedChange=always(proposed((PC, NAME, "main", False), ("pc-2", "Another", "main", False))))
    with pytest.raises(SourceError) as caught:
        w.source.change(REF)
    assert not isinstance(caught.value, NoChange)
    said = str(caught.value)
    assert all(part in said for part in (REF, PC, NAME, "pc-2", "Another")), said


def test_a_branch_whose_cut_time_cannot_be_read_says_so_and_has_no_branch_point(world: Callable[..., World]) -> None:
    for answer in (branch(None), {"data": {"Branch": [{"name": REF, "branched_from": None}]}}):
        w = world(
            ProposedChange=always(proposed((PC, NAME, "main", False))),
            BranchCut=always(answer),
            Marks=always(marks(("a", A_AT, None, A_AT))),
        )
        change = w.source.change(REF)
        assert change.where == (
            f'proposed change "{NAME}", branch {REF} into main; the time {REF} was cut could not be read, so its '
            "branch point is not rehearsed"
        )
        assert [stage.label for stage in w.source.stages(change)] == ["a", "head"]


# The report.

REPORT = Report("failed", "Rehearsal failed\nIt did.", "## Summary\n\nIt did.", "## Detail\n\nAll of it.")


def test_a_report_is_one_thread_and_two_comments_in_order(world: Callable[..., World]) -> None:
    w = world(
        ThreadCreate=always(created("CoreChangeThreadCreate", "th-1")),
        CommentCreate=in_turn(created("CoreThreadCommentCreate", "c-1"), created("CoreThreadCommentCreate", "c-2")),
    )
    w.source.post(CHANGE, REPORT)
    assert w.hub.asked == [
        ("ThreadCreate", "main", None, {"change": PC, "label": THREAD_LABEL}),
        ("CommentCreate", "main", None, {"thread": "th-1", "text": REPORT.summary}),
        ("CommentCreate", "main", None, {"thread": "th-1", "text": REPORT.detail}),
    ]
    assert THREAD_LABEL == "Fylgja rehearsal"


def test_a_part_of_4093_bytes_sends_nothing(world: Callable[..., World]) -> None:
    w = world()
    fits = "x" * 4092
    for summary, detail, part, size in (("ok", "€" * 1365, "detail", "4095"), (fits + "y", "ok", "summary", "4093")):
        with pytest.raises(SourceError) as caught:
            w.source.post(CHANGE, Report("failed", "h", summary, detail))
        assert part in str(caught.value)
        assert size in str(caught.value)
    assert w.hub.asked == []


def test_a_comment_refused_names_the_thread_and_deletes_nothing(world: Callable[..., World]) -> None:
    refused = {"data": {"CoreThreadCommentCreate": None},
               "errors": [{"message": "A comment's text may not be empty", "extensions": {"http_status": 422}}]}
    w = world(
        ThreadCreate=always(created("CoreChangeThreadCreate", "th-1")),
        CommentCreate=in_turn(created("CoreThreadCommentCreate", "c-1"), refused),
    )
    with pytest.raises(SourceError) as caught:
        w.source.post(CHANGE, REPORT)
    said = str(caught.value)
    assert all(part in said for part in ("th-1", "detail", "422", "may not be empty")), said
    assert w.hub.operations == ["ThreadCreate", "CommentCreate", "CommentCreate"]


def test_a_graphql_error_under_http_200_is_a_source_error_and_no_text_holds_the_token(
    world: Callable[..., World],
) -> None:
    echoed = f"Invalid filter for token {TOKEN}: " + "x" * 2000
    w = world(
        ProposedChange=in_turn(
            {"data": None, "errors": [{"message": echoed, "extensions": {"http_status": 422}}]},
            httpx.Response(401, json={"errors": [{"message": f"Invalid token {TOKEN}"}]}),
        )
    )
    # Each check worked out into a bool before its assert, so that no failure prints a text that may hold the token.
    texts = [repr(w.source)]
    with pytest.raises(SourceError) as caught:
        w.source.change(REF)
    said = str(caught.value)
    texts += [said, repr(caught.value)]
    _, marker, quoted = said.partition("HTTP 200, http_status 422: ")
    begins = bool(marker) and quoted.startswith("Invalid filter for token <redacted>: x")
    assert begins, "the error does not quote Infrahub's words after its status"
    assert len(quoted) == 500
    with pytest.raises(SourceError) as caught:
        w.source.change(REF)
    said = str(caught.value)
    texts += [said, repr(caught.value)]
    named = said.endswith(f"the change source's token was refused: HTTP 401 from Infrahub at {ADDRESS}")
    assert named, "a 401 is not the source's own sentence"
    leaked = any(TOKEN in text for text in texts)
    assert not leaked, "a text holds the token"


VARIABLES = ("FYLGJA_INFRAHUB_TOKEN", "FYLGJA_ORCHESTRATOR_INFRAHUB_TOKEN")


def scrubbed(error: BaseException, sentence: str, status: int) -> bool:
    """Whether `error` is a `SourceError` of the refused token's `status` holding `sentence`, neither the token nor a
    variable's name, raised from nothing."""
    said = str(error)
    return (
        isinstance(error, SourceError)
        and error.status == status
        and sentence in said
        and TOKEN not in said
        and not any(name in said or name in repr(error) for name in VARIABLES)
        and error.__cause__ is None
        and error.__context__ is None
    )


def test_a_source_error_of_no_refused_token_has_no_status() -> None:
    assert (SourceError("asked, and not answered").status, NoChange("no change").status) == (None, None)
    assert SourceError("refused", status=401).status == 401


def token_refused(call: str) -> str:
    """The source's sentence for a 401: the token refused."""
    return f"{call}: the change source's token was refused: HTTP 401 from Infrahub at {ADDRESS}"


def lacks(call: str) -> str:
    """The source's sentence for a 403: the account lacks a permission the call requires."""
    return (
        f"the change source's account lacks a permission Infrahub requires for {call}: HTTP 403 from Infrahub at "
        f"{ADDRESS}"
    )


def forbidden_by(permission: str) -> dict[str, Any]:
    """A 403 under HTTP 200 as Infrahub answers it, naming `permission`, and the token, which must be scrubbed."""
    message = f"You do not have one of the following permissions: {permission} (token {TOKEN})"
    return {"data": None, "errors": [{"message": message, "extensions": {"http_status": 403}}]}


def test_a_401_at_the_readers_connect_is_the_token_refused(world: Callable[..., World]) -> None:
    w = world(ArtifactValidation=always(validators(("completed", EARLIER))))
    w.hub.info_status = 401
    with pytest.raises(SourceError) as caught:
        w.source.read(staged(CUT, Mark("a", "", A_AT, None))[1], SCOPE)
    held = scrubbed(caught.value, token_refused("the reader's connect"), 401)
    assert held, "a 401 at the connect is not the token refused"


def test_a_403_from_the_readers_head_or_read_is_a_permission_lacking(world: Callable[..., World]) -> None:
    reader = "reading Devices (branch change-1): HTTP 403: the token FYLGJA_INFRAHUB_TOKEN holds may not read it"
    answers = {"ArtifactValidation": always(validators(("completed", EARLIER)))}
    w = world(**answers)
    w.reader.heads = {REF: InfrahubError(reader, 403)}
    with pytest.raises(SourceError) as caught:
        w.source.read(staged(CUT)[-1], SCOPE)
    held = scrubbed(caught.value, lacks(f"a read of branch {REF} through the reader"), 403)
    assert held, "a 403 from head is not a permission lacking"

    w = world(**answers)

    def forbidden(branch: str, at: str) -> Result:
        raise InfrahubError(reader, 403)

    w.reader.results = forbidden
    with pytest.raises(SourceError) as caught:
        w.source.read(staged(CUT, Mark("a", "", A_AT, None))[1], SCOPE)
    held = scrubbed(caught.value, lacks(f"a read of branch {REF} through the reader"), 403)
    assert held, "a 403 from read is not a permission lacking"


def test_a_401_of_the_sources_own_is_the_token_refused(world: Callable[..., World]) -> None:
    w = world(ProposedChange=always(httpx.Response(401, json={"errors": [{"message": "Invalid token"}]})))
    with pytest.raises(SourceError) as caught:
        w.source.change(REF)
    held = scrubbed(caught.value, token_refused("a read of the proposed change"), 401)
    assert held, "a 401 of the source's own is not the token refused"


def test_a_403_from_the_threads_create_names_the_call_and_the_permission(world: Callable[..., World]) -> None:
    permission = "object:Core:ChangeThread:create:allow_default"
    w = world(ThreadCreate=always(forbidden_by(permission)))
    with pytest.raises(SourceError) as caught:
        w.source.post(CHANGE, REPORT)
    held = scrubbed(caught.value, lacks("the thread's create") + f"; Infrahub names {permission}", 403)
    assert held, "a 403 from the thread's create does not name the call and the permission"
    assert w.hub.operations == ["ThreadCreate"]


def test_a_403_from_a_comments_create_names_the_call_and_the_permission(world: Callable[..., World]) -> None:
    permission = "object:Core:ThreadComment:create:allow_default"
    w = world(
        ThreadCreate=always(created("CoreChangeThreadCreate", "th-1")),
        CommentCreate=always(forbidden_by(permission)),
    )
    with pytest.raises(SourceError) as caught:
        w.source.post(CHANGE, REPORT)
    held = scrubbed(caught.value, lacks("a comment's create") + f"; Infrahub names {permission}", 403)
    assert held, "a 403 from a comment's create does not name the call and the permission"
    named = "th-1" in str(caught.value) and "summary" in str(caught.value)
    assert named, "the refusal does not name the thread and the part"


def test_the_transport_reads_nothing_of_the_environment_and_gives_each_request_30_s() -> None:
    transport = Transport(ADDRESS, TOKEN, transport=httpx.MockTransport(lambda request: httpx.Response(200)))
    http = transport._http
    settings = (http.trust_env, http.timeout)
    transport.close()
    assert settings == (False, httpx.Timeout(30.0, connect=5.0))


def test_the_transport_keeps_an_idle_connection_1_s(monkeypatch: pytest.MonkeyPatch) -> None:
    # Infrahub refused a request sent on a connection idle 2.0 s, and the source asks every 5 s (P5-59).
    made: list[httpx.Limits | None] = []
    real = httpx.Client

    def client(*args: Any, **kwargs: Any) -> httpx.Client:
        made.append(kwargs.get("limits"))
        return real(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", client)
    Transport(ADDRESS, TOKEN).close()
    assert [limits.keepalive_expiry if limits is not None else None for limits in made] == [1.0]


def test_infrahub_not_reached_is_a_source_error_naming_the_address(world: Callable[..., World]) -> None:
    def unreachable(variables: Mapping[str, Any], branch: str, at: str | None) -> object:
        raise httpx.ConnectError(f"refused, with {TOKEN}")

    w = world(ProposedChange=unreachable)
    with pytest.raises(SourceError) as caught:
        w.source.change(REF)
    said = str(caught.value)
    named = ADDRESS in said and "ConnectError" in said
    assert named, "the error does not name the address and the failure"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    leaked = TOKEN in said
    assert not leaked, "the error holds the token"
