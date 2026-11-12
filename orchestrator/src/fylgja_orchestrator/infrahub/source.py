"""The Infrahub change source (D-085, D-088): a proposed change found by its branch, its stages in order, each read
through the reader (D-082), and the report posted as one thread of two comments.

A change is the one open proposed change whose source branch is the reference a trigger names: none is `NoChange`,
and two are refused naming both, since the source picks none. Its stages are the branch point, the destination as it
stood when the branch was cut, left out where Infrahub gives no time of the cut; then the branch's marks, ordered by
their time and then by label, a mark with no time after those with one; then the head, the branch as it stands. Each
stage's pin is a `Pin`, which only this source reads, carrying the proposed change's id: the head's has no time until
its read resolves one.

A stage is read through `fylgja_infrahub.read`, its `Result` handed on as a `Read` member for member. A mark labelled
as one of the source's own stages, or with no time or one that does not parse (P5-43), is refused by a finding of the
source's and nothing is read. The head is read after the proposed change's artifact validation has completed, waited
for under a bound, at the later of the reader's `head` and the validation's completion, with that completion as
`generated_since`, so that it is never later than the time read (P5-9); where no validator appears within its own
bound, the head is read on its artifacts' stamps alone, with the info `stage.validation.absent` (P5-58). A mark is
given the completion in force at its time.
The branch point is given none, and is decided by the destination read at the cut (P5-42); the destination's
head is then asked as a comparison alone, a warning filed where its blueprint there is not the cut's: every write to
`main` moves its head, a mark, a thread and a proposed change among them, so a time alone cannot say it moved (P5-28).
Only `head` raises `fylgja_infrahub.Refused`; it is caught around each call of `head` and answered as a `Read` of its
findings, since the library names a source's exception by its type alone. The reader's `InfrahubError` of a refused
token, 401 or 403, is raised as the source's own `SourceError`, in the sentence its own transport gives by the
status, naming no variable (P5-41, P5-44); any other `InfrahubError`, a `ValueError` from `head` or a `SourceError` is
raised on.

A time is a string as Infrahub returned it and is sent back verbatim. Marks are ordered by `datetime.fromisoformat`,
a time it reads with no zone counted as one that does not parse;
the validation's completion is compared with the head's answer, and among validators, by the reader's own times.

The source's own requests go through its transport (transport.py); the reader's through a connection of the reader's,
made at the first read that needs it and kept.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import httpx
from fylgja_core.blueprint import blueprint_id
from fylgja_core.findings import Finding, order
from fylgja_infrahub import Infrahub, InfrahubError, ReaderDocument, Refused, Result, connect, head, read, times
from fylgja_infrahub.read import RULE_SCOPE_EMPTY as SCOPE_EMPTY

from fylgja_orchestrator.infrahub.transport import REFUSED, SourceError, Transport, refused_token
from fylgja_orchestrator.rehearsal.report import Report
from fylgja_orchestrator.rehearsal.source import Change, Read, Stage

# Rule ids. The catalogue is orchestrator/rules.md, "Findings: the Infrahub change source".
RULE_AT_UNRESOLVED = "stage.at.unresolved"
RULE_LABEL_RESERVED = "stage.label.reserved"
RULE_MAIN_MOVED = "stage.main.moved"
RULE_VALIDATION_UNFINISHED = "stage.validation.unfinished"
RULE_VALIDATION_ABSENT = "stage.validation.absent"

SEVERITY: dict[str, Literal["error", "warning", "info"]] = {
    RULE_AT_UNRESOLVED: "error",
    RULE_LABEL_RESERVED: "error",
    RULE_MAIN_MOVED: "warning",
    RULE_VALIDATION_UNFINISHED: "warning",
    RULE_VALIDATION_ABSENT: "info",
}
"""The severity each of the source's rules is filed at."""

BRANCH_POINT = "branch-point"
"""The label of the first stage: the destination as it stood when the branch was cut."""

HEAD = "head"
"""The label of the last stage: the branch as it stands."""

THREAD_LABEL = "Fylgja rehearsal"
"""The label of the thread a report is posted in."""

COMMENT_LIMIT = 4092
"""The bytes one part of a report may take, its UTF-8 encoding measured."""

VALIDATION_WAIT_S = 240.0
"""Seconds the head's read waits for the artifact validation to complete."""

VALIDATION_POLL_S = 5.0
"""Seconds between two reads of the validation."""

VALIDATION_APPEAR_S = 120.0
"""Seconds after the first read with no validator, at which none is waited for: one was first answered 25 s and 46 s
after a proposed change's create on a quiet instance, and created 70.5 s after one whose pipeline queued behind
another's; a change that touches no device has none (design/verified-facts.md, "Infrahub 1.11.11")."""

Kind = Literal["branch-point", "mark", "head"]


@dataclass(frozen=True)
class Pin:
    """Where a stage is read: its kind, the branch, the time (empty for the head until its read, and for a mark with
    none), and the proposed change's id, whose validation the read asks after."""

    kind: Kind
    branch: str
    at: str
    change: str


@dataclass(frozen=True)
class Mark:
    """A `FylgjaStage` naming the branch: its label and description, its `as_of` as written, and when Infrahub says
    it was written, its edge's `created_at`."""

    label: str
    description: str
    as_of: str | None
    written: str | None


def mark_time(mark: Mark) -> str | None:
    """The time a mark stands at: its `as_of`, else the time Infrahub gave its writing; None where it has neither."""
    return mark.as_of if mark.as_of is not None else mark.written


def stages_of(
    branch: str, destination: str, cut: str | None, marks: Sequence[Mark], *, change: str
) -> tuple[Stage, ...]:
    """The stages of the proposed change `change` from `branch` into `destination`: the branch point where `cut`, the
    time the branch was cut, is given; each of `marks` by its time, parsed, then by its label, one with no time after
    those with one, or with one that does not parse, by label; and the head."""
    timed = [(mark, at, moment) for mark in marks if (at := mark_time(mark)) and (moment := _instant(at)) is not None]
    timed.sort(key=lambda found: (found[2], found[0].label))
    untimed = sorted(
        ((mark, mark_time(mark) or "") for mark in marks if _instant(mark_time(mark) or "") is None),
        key=lambda found: found[0].label,
    )
    stages: list[Stage] = []
    if cut is not None:
        stages.append(
            Stage(
                BRANCH_POINT,
                f"{destination} as it was when {branch} was cut",
                f"branch {destination} at {cut}",
                Pin("branch-point", destination, cut, change),
            )
        )
    for mark, at in [*((mark, at) for mark, at, _ in timed), *untimed]:
        stages.append(
            Stage(
                mark.label,
                mark.description or f"the mark {mark.label}",
                _where(branch, at),
                Pin("mark", branch, at, change),
            )
        )
    stages.append(Stage(HEAD, f"the head of {branch}", f"the head of branch {branch}", Pin("head", branch, "", change)))
    return tuple(stages)


def _instant(at: str) -> datetime | None:
    """The instant a mark's time names, to order the marks by; None where it names none with a zone."""
    try:
        moment = datetime.fromisoformat(at)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def _where(branch: str, at: str) -> str:
    """A mark's pin in words: the branch at its time, or its time unread or not parsing."""
    if not at:
        return f"branch {branch}, its time unread"
    if _instant(at) is None:
        return f"branch {branch} at {at!r}, which does not parse"
    return f"branch {branch} at {at}"


def validated(
    poll: Callable[[], Sequence[tuple[str, str | None]]],
    *,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> tuple[str | None, bool]:
    """Waits on the artifact validation, `poll` answering each validator's state and `completed_at`, every
    `VALIDATION_POLL_S`: the latest completion and False once a validator exists and every one is done, its state
    `completed` and its `completed_at` answered, since a validator run again reads `in_progress` while its first
    run's `completed_at` may stand; None and False where none exists `VALIDATION_APPEAR_S` after the first poll; and
    at `VALIDATION_WAIT_S`, the latest completion among those done, or None, and True, the bound passed."""
    began = clock()
    while True:
        rows = poll()
        done = _done(rows)
        if rows and len(done) == len(rows):
            return times.latest(done), False
        waited = clock() - began
        if not rows and waited >= VALIDATION_APPEAR_S:
            return None, False
        if waited >= VALIDATION_WAIT_S:
            return times.latest(done), True
        sleep(VALIDATION_POLL_S)


def _done(rows: Sequence[tuple[str, str | None]]) -> list[str]:
    """The `completed_at` of each validator among `rows` that is done: its state `completed`, its time answered."""
    return [completed for state, completed in rows if state == "completed" and completed]


class NoChange(SourceError):
    """No open proposed change has the branch a trigger names as its source."""


@dataclass(frozen=True)
class _Proposal:
    """What the source read of a change beside the `Change` it answered."""

    change: Change
    destination: str
    draft: bool
    cut: str | None


class InfrahubSource:
    """The change source over one Infrahub, read with one token, and a reader document: the four calls of the seam
    and `is_draft`. Made with no request; `transport`, `sleep` and `clock` replace the network, the wait and its
    clock, for tests."""

    comment_limit: int | None = COMMENT_LIMIT

    def __init__(
        self,
        address: str,
        token: str,
        document: ReaderDocument,
        *,
        ca: Path | None = None,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._transport = Transport(address, token, ca=ca, transport=transport)
        self._address = address
        self._token = token
        self._ca = ca
        self._network = transport
        self._document = document
        self._sleep = sleep
        self._clock = clock
        self._conn: Infrahub | None = None
        self._proposals: dict[str, _Proposal] = {}

    def __repr__(self) -> str:
        """Neither the token nor the address, which may hold a login."""
        return f"InfrahubSource(comment_limit={self.comment_limit!r})"

    def close(self) -> None:
        """Closes the source's connections, its own and the reader's."""
        self._transport.close()
        if self._conn is not None:
            self._conn.close()

    def change(self, ref: str) -> Change:
        """The open proposed change whose source branch is `ref`; `NoChange` where there is none, and a `SourceError`
        naming each where there are more."""
        nodes = _nodes(
            self._transport.ask("proposed_change", {"branch": ref}),
            "CoreProposedChange",
            f"the open proposed changes of branch {ref}",
        )
        if not nodes:
            raise NoChange(f"no open proposed change has source branch {ref}")
        if len(nodes) > 1:
            named = " and ".join(f'"{_value(node, "name")}" ({node.get("id")})' for node in nodes)
            raise SourceError(
                f"{len(nodes)} open proposed changes have source branch {ref}, {named}: the source rehearses one, so "
                "close all but one"
            )
        node = nodes[0]
        found, name, destination = node.get("id"), _value(node, "name"), _value(node, "destination_branch")
        draft = node.get("is_draft")
        draft = draft.get("value") if isinstance(draft, dict) else None
        if not isinstance(found, str) or not found or name is None or destination is None or type(draft) is not bool:
            raise SourceError(
                f"the open proposed change of branch {ref}: Infrahub answered one with no id, name, destination_branch "
                "or is_draft"
            )
        cut = self._cut(ref)
        where = f'proposed change "{name}", branch {ref} into {destination}'
        if cut is None:
            where += f"; the time {ref} was cut could not be read, so its branch point is not rehearsed"
        change = Change(ref, found, name, where)
        self._proposals[found] = _Proposal(change, destination, draft, cut)
        return change

    def is_draft(self, change: Change) -> bool:
        """Whether the proposed change is a draft, as it was read."""
        return self._proposal(change).draft

    def stages(self, change: Change) -> Sequence[Stage]:
        """The change's stages in order (`stages_of`), its marks read as they stand."""
        proposal = self._proposal(change)
        edges = _edges(
            self._transport.ask("marks", {"branch": change.ref}), "FylgjaStage", f"the marks of branch {change.ref}"
        )
        marks = []
        for edge in edges:
            node, meta = edge["node"], edge.get("node_metadata")
            label = _value(node, "label")
            if label is None:
                raise SourceError(f"the marks of branch {change.ref}: Infrahub answered a FylgjaStage with no label")
            written = meta.get("created_at") if isinstance(meta, dict) else None
            marks.append(
                Mark(
                    label,
                    _value(node, "description") or "",
                    _value(node, "as_of") or None,
                    written if isinstance(written, str) and written else None,
                )
            )
        return stages_of(change.ref, proposal.destination, proposal.cut, marks, change=change.id)

    def read(self, stage: Stage, scope: str) -> Read:
        """The stage read under `scope` through the reader, by its pin's kind."""
        pin = stage.pin
        if not isinstance(pin, Pin):
            raise SourceError(f"the stage {stage.label} is not one this source answered: its pin is no Pin")
        if pin.kind == "mark":
            return self._mark(stage.label, pin, scope)
        if pin.kind == "head":
            return self._head(pin, scope)
        return self._branch_point(pin, scope)

    def post(self, change: Change, report: Report) -> None:
        """The report as one thread on the proposed change, unresolved and labelled `THREAD_LABEL`, of two comments,
        the summary and then the detail; each part measured first, and nothing sent where one is larger than
        `comment_limit`. A comment refused once the thread exists is a `SourceError` naming the thread, which is kept:
        the account may delete nothing."""
        parts = (("summary", report.summary), ("detail", report.detail))
        limit = self.comment_limit
        for part, text in parts:
            size = len(text.encode())
            if limit is not None and size > limit:
                raise SourceError(
                    f"the report's {part} is {size} bytes, more than the {limit} one comment takes, so nothing was "
                    f"posted on {change.where}"
                )
        data = self._transport.ask("thread_create", {"change": change.id, "label": THREAD_LABEL})
        thread = _created(data, "CoreChangeThreadCreate", f"the thread on {change.where}")
        for part, text in parts:
            try:
                made = self._transport.ask("comment_create", {"thread": thread, "text": text})
                _created(made, "CoreThreadCommentCreate", f"the {part} in thread {thread}")
            except SourceError as e:
                failure = SourceError(
                    f"the thread {thread} was made on {change.where}, but its {part} was refused, and nothing was "
                    f"deleted: {e}",
                    status=e.status,
                )
            else:
                continue
            # Raised outside the handler, as every refusal of the source's is: its text is whole.
            raise failure

    def _mark(self, label: str, pin: Pin, scope: str) -> Read:
        """A mark read at its time, given the latest completion of the validation in force then; refused with nothing
        read where it is labelled as the source's own stage or has no time."""
        if label in (BRANCH_POINT, HEAD):
            message = (
                f"The mark {label} on branch {pin.branch} is labelled as a stage the source makes of every change, "
                f"{BRANCH_POINT} or {HEAD}, so it is not read: label it otherwise."
            )
            return Read(None, (_finding(RULE_LABEL_RESERVED, label, message),), False)
        if not pin.at:
            message = (
                f"The mark {label} on branch {pin.branch} has no as_of, and Infrahub gave no time of its writing, so "
                "there is no time to read the branch at: give the mark an as_of."
            )
            return Read(None, (_finding(RULE_AT_UNRESOLVED, label, message),), False)
        if _instant(pin.at) is None:
            message = (
                f"The mark {label} on branch {pin.branch} stands at {pin.at!r}, which does not parse as an ISO 8601 "
                "time with a zone, so there is no time to read the branch at: give the mark an as_of that does."
            )
            return Read(None, (_finding(RULE_AT_UNRESOLVED, label, message),), False)
        since = times.latest(_done(self._validators(pin.change, at=pin.at)))
        conn = self._reader()
        got = self._guarded(pin.branch, lambda: read(conn, branch=pin.branch, at=pin.at, scope=scope,
                                                      document=self._document, generated_since=since))
        return _read(got)

    def _head(self, pin: Pin, scope: str) -> Read:
        """The head, read once the validation has completed or its wait has ended, at the later of the reader's
        `head` and the completion, given the completion; where the wait passed its bound, on the artifacts' stamps
        alone, with `stage.validation.unfinished`; where no validator appeared, so too, with the info
        `stage.validation.absent`."""
        completed, passed = validated(lambda: self._validators(pin.change), sleep=self._sleep, clock=self._clock)
        warned: list[Finding] = []
        if not passed and completed is None:
            message = (
                f"No artifact validation of proposed change {pin.change} appeared {VALIDATION_APPEAR_S:g} s after it "
                f"was first asked for, so the head of {pin.branch} is read on its artifacts' stamps alone, with no "
                "generated_since."
            )
            warned.append(_finding(RULE_VALIDATION_ABSENT, pin.branch, message))
        if passed:
            message = (
                f"The artifact validation of proposed change {pin.change} had not completed {VALIDATION_WAIT_S:g} s "
                f"after it was first asked for, so the head of {pin.branch} is read on its artifacts' stamps alone, "
                "with no generated_since."
            )
            warned.append(_finding(RULE_VALIDATION_UNFINISHED, pin.branch, message))
        conn = self._reader()
        try:
            at = self._guarded(pin.branch, lambda: head(conn, branch=pin.branch, scope=scope))
        except Refused as e:
            return _refused(e, warned)
        since: str | None = None
        if not passed and completed is not None:
            since = completed
            if times.later(completed, at):
                at = completed
        got = self._guarded(pin.branch, lambda: read(conn, branch=pin.branch, at=at, scope=scope,
                                                     document=self._document, generated_since=since))
        return Read(got.blueprint, order([*got.findings, *warned]), got.empty)

    def _branch_point(self, pin: Pin, scope: str) -> Read:
        """The destination read at the cut, given no completion, which decides the stage (P5-42); and, where it gives
        a blueprint, the destination's head asked and read there as a comparison alone: `stage.main.moved` where the
        two blueprints differ, or where the head is refused with `scope.empty`, the scoped devices gone since the cut;
        nothing more where it is refused otherwise or read there with no blueprint."""
        proposal = self._proposals.get(pin.change)
        if proposal is None:
            raise SourceError(f"the branch point of {pin.branch} is of proposed change {pin.change}, which this source "
                              "has not answered")
        conn = self._reader()
        then = self._guarded(pin.branch, lambda: read(conn, branch=pin.branch, at=pin.at, scope=scope,
                                                      document=self._document))
        if then.blueprint is None:
            return _read(then)
        try:
            now = self._guarded(pin.branch, lambda: head(conn, branch=pin.branch, scope=scope))
        except Refused as e:
            if not any(finding.rule == SCOPE_EMPTY for finding in e.findings):
                return _read(then)
        else:
            now_read = self._guarded(pin.branch, lambda: read(conn, branch=pin.branch, at=now, scope=scope,
                                                              document=self._document))
            if now_read.blueprint is None or blueprint_id(now_read.blueprint) == blueprint_id(then.blueprint):
                return _read(then)
        message = (
            f"{pin.branch} has moved since {proposal.change.ref} was cut at {pin.at}: the branch point reads "
            f"{pin.branch} as it was then."
        )
        moved = _finding(RULE_MAIN_MOVED, pin.branch, message)
        return Read(then.blueprint, order([*then.findings, moved]), then.empty)

    def _proposal(self, change: Change) -> _Proposal:
        """What was read of `change`, read again by its branch where this source has not answered it."""
        if change.id not in self._proposals:
            self.change(change.ref)
        proposal = self._proposals.get(change.id)
        if proposal is None:
            raise SourceError(f"the open proposed change of branch {change.ref} is no longer {change.id}")
        return proposal

    def _cut(self, ref: str) -> str | None:
        """When the branch `ref` was cut, its `branched_from` as Infrahub answered it; None where it lists no such
        branch or answers none."""
        listed = self._transport.ask("branch", {"name": ref}).get("Branch")
        found = [b for b in listed if isinstance(b, dict) and b.get("name") == ref] if isinstance(listed, list) else []
        cut = found[0].get("branched_from") if found else None
        return cut if isinstance(cut, str) and cut else None

    def _validators(self, change: str, *, at: str | None = None) -> list[tuple[str, str | None]]:
        """Each artifact validator of the proposed change `change`, as it stands or at `at`: its state and its
        `completed_at`, None where Infrahub answers none or the empty string, as while it runs."""
        what = f"the artifact validators of proposed change {change}"
        rows: list[tuple[str, str | None]] = []
        for node in _nodes(self._transport.ask("artifact_validation", {"change": change}, at=at),
                           "CoreArtifactValidator", what):
            completed = _value(node, "completed_at") or None
            if completed is not None:
                try:
                    times.parse(completed)
                except ValueError:
                    said = f"{what}: Infrahub answered a completed_at {completed!r}, which is no time"
                    raise SourceError(said) from None
            rows.append((_value(node, "state") or "", completed))
        return rows

    def _reader(self) -> Infrahub:
        """The reader's connection, made at the first call that needs it and kept."""
        if self._conn is None:
            self._conn = self._guarded(
                None, lambda: connect(self._address, self._token, ca=self._ca, transport=self._network)
            )
        return self._conn

    def _guarded[T](self, branch: str | None, call: Callable[[], T]) -> T:
        """`call`, a call of the reader's; its `InfrahubError` of a refused token, 401 or 403, raised as the source's
        own `SourceError`, raised from nothing, since the reader's names the variable the reader's command reads its
        token from, which is not the runner's. Any other is raised on."""
        try:
            return call()
        except InfrahubError as e:
            if e.status not in REFUSED:
                raise
            status = e.status
        asked = f"a read of branch {branch} through the reader" if branch is not None else "the reader's connect"
        raise SourceError(refused_token(asked, status, self._transport.url), status=status)


def _read(result: Result) -> Read:
    """The reader's `Result` as a `Read`, member for member."""
    return Read(result.blueprint, result.findings, result.empty)


def _refused(e: Refused, warned: Sequence[Finding] = ()) -> Read:
    """A `head` refused, as a `Read` of its findings and `warned`, empty exactly where one is `scope.empty`."""
    return Read(None, order([*e.findings, *warned]), any(finding.rule == SCOPE_EMPTY for finding in e.findings))


def _finding(rule: str, obj: str, message: str) -> Finding:
    return Finding(rule=rule, severity=SEVERITY[rule], object=obj, message=message)


def _value(node: dict[str, Any], field: str) -> str | None:
    """An attribute's value, `{field: {"value": ...}}`; None where it is null or no string."""
    attribute = node.get(field)
    value = attribute.get("value") if isinstance(attribute, dict) else None
    return value if isinstance(value, str) else None


def _edges(data: dict[str, Any], root: str, what: str) -> list[dict[str, Any]]:
    """The edges of the list `root`, each holding a node, once they are as many as the `count` Infrahub answered; a
    `SourceError` otherwise, since a list read in part could hide a change, a mark or a validator."""
    page = data.get(root)
    count = page.get("count") if isinstance(page, dict) else None
    edges = page.get("edges") if isinstance(page, dict) else None
    if type(count) is not int or not isinstance(edges, list):
        raise SourceError(f"{what}: Infrahub answered no count and edges of {root}")
    held = [edge for edge in edges if isinstance(edge, dict) and isinstance(edge.get("node"), dict)]
    if len(held) != count:
        raise SourceError(f"{what}: Infrahub answered {len(held)} of the {count} {root} it counted")
    return held


def _nodes(data: dict[str, Any], root: str, what: str) -> list[dict[str, Any]]:
    return [edge["node"] for edge in _edges(data, root, what)]


def _created(data: dict[str, Any], root: str, what: str) -> str:
    """The id of the object a mutation `root` made; a `SourceError` where it answered no `ok` and id."""
    made = data.get(root)
    made_object = made.get("object") if isinstance(made, dict) else None
    found = made_object.get("id") if isinstance(made_object, dict) else None
    if not isinstance(made, dict) or made.get("ok") is not True or not isinstance(found, str) or not found:
        raise SourceError(f"{what}: Infrahub answered no ok and id of {root}")
    return found
