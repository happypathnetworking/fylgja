"""The seam to a change source (D-085, D-097): four calls and three attributes a source answers, over three values
the library passes back to it and reads only as far as each says.

A source is whatever system holds a change and its stages; the example's own is a layer above this library, and
another system's answers the same calls. The library assumes none of a source's own terms: that a stage can be read
again later, that the change has an object of review, that the trigger comes once, or that the report is a comment.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from fylgja_core.findings import Finding

from fylgja_orchestrator.rehearsal.report import Report


@dataclass(frozen=True)
class Change:
    """A change a trigger names: the reference it was named by, the source's id for it, its name, and `where`, the
    change in words, for the report."""

    ref: str
    id: str
    name: str
    where: str


@dataclass(frozen=True)
class Stage:
    """One stage of a change, in its order: a label, a description, `where`, the pin in words, for the report, and
    the pin itself, which only the source reads. The report says when the rehearsal read its stages, and that a
    stage taken earlier is as it was then, at the time its `where` gives: so a stage a source read before the
    rehearsal's own read says that time in its `where`."""

    label: str
    description: str
    where: str
    pin: object


@dataclass(frozen=True)
class Read:
    """A stage read under a scope: its blueprint, or none where the read was refused; the findings the read gave,
    those that refused it among them; and `empty`, true where the scope selects no device at that stage."""

    blueprint: dict[str, Any] | None
    findings: tuple[Finding, ...]
    empty: bool


class ChangeSource(Protocol):
    """What a source answers: the change a trigger names, its stages in order, a stage read, and the report posted.
    `comment_limit` is the bytes one part of a report may take there, or `None` where the source sets no bound.
    `again` and `scope_remedy` are the source's own words, each one whole sentence ending in a full stop, which the
    library's sentences end in: how one asks for the rehearsal again, and where one checks the scope the stages are
    read under. `scope_remedy` is used whole. `again` is used whole after a sentence of the library's, and also
    inside one, its first letter lowered and its full stop dropped (`rules.clause`), as in `…, then <again>.`: so it
    must read rightly both ways."""

    comment_limit: int | None
    again: str
    scope_remedy: str

    def change(self, ref: str) -> Change: ...

    def stages(self, change: Change) -> Sequence[Stage]: ...

    def read(self, stage: Stage, scope: str) -> Read: ...

    def post(self, change: Change, report: Report) -> None: ...
