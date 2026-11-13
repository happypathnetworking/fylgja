"""A fake change source for the rehearsal library's tests: a change of stages a test lists, each read as a blueprint
of `testdata/`, as no device in scope, or as refused by the source, and every read and post it was asked recorded."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from fylgja_core.findings import Finding

from fylgja_orchestrator.rehearsal import Change, Read, Report, Stage

TESTDATA = Path(__file__).resolve().parents[2] / "testdata"
BLUEPRINTS = TESTDATA / "blueprint"
SCOPE = "tag:fylgja"

CHANGE = Change("third-link", "pc-1", "third link", 'Change "third link"')


class FakeSource:
    """A source of one change, `change`, whose stages are `stages` in order, each with what its read answers, or the
    exception its read raises. `reads` holds the label of each stage read, in order, `posted` each report posted;
    `post` raises `fail_post` when it is set, posting nothing. `again` and `scope_remedy` are its two sentences, the
    Infrahub source's by default, so that a test of the library holds the words it said before a source gave them.
    `is_draft` answers `draft`, `claim` appends the change's `ref` to `claimed`, and `close` sets `closed`, for the
    edge's tests; `calls` holds the names of `change`, `is_draft` and `claim` in the order they were called."""

    def __init__(
        self,
        change: Change,
        stages: Sequence[tuple[Stage, Read | Exception]],
        *,
        comment_limit: int | None = 4092,
        again: str = "Run the checks again.",
        scope_remedy: str = "Check the scope the checks run with.",
        draft: bool = False,
    ) -> None:
        self.comment_limit = comment_limit
        self.again = again
        self.scope_remedy = scope_remedy
        self.draft = draft
        self._change = change
        self._stages = list(stages)
        self.reads: list[str] = []
        self.posted: list[Report] = []
        self.fail_post: Exception | None = None
        self.closed = False
        self.claimed: list[str] = []
        self.calls: list[str] = []

    def change(self, ref: str) -> Change:
        self.calls.append("change")
        if ref != self._change.ref:
            raise LookupError(f"no change is named {ref}")
        return self._change

    def is_draft(self, change: Change) -> bool:
        self.calls.append("is_draft")
        return self.draft

    def claim(self, change: Change) -> None:
        self.calls.append("claim")
        self.claimed.append(change.ref)

    def close(self) -> None:
        self.closed = True

    def stages(self, change: Change) -> Sequence[Stage]:
        return [stage for stage, _ in self._stages]

    def read(self, stage: Stage, scope: str) -> Read:
        self.reads.append(stage.label)
        answer = next(answer for known, answer in self._stages if known == stage)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def post(self, change: Change, report: Report) -> None:
        if self.fail_post is not None:
            raise self.fail_post
        self.posted.append(report)


def stage(label: str) -> Stage:
    """A stage labelled `label`, its pin the label itself."""
    return Stage(label=label, description=f"The stage {label}.", where=f"stage {label} as pinned", pin=label)


def built(label: str, fixture: str | Path) -> tuple[Stage, Read]:
    """A stage read as the blueprint `fixture`: a path under `testdata/blueprint/` (`"steps/two-node.json"`), or
    any other given as a `Path`."""
    path = fixture if isinstance(fixture, Path) else BLUEPRINTS / fixture
    return stage(label), Read(json.loads(path.read_text()), (), False)


def empty(label: str) -> tuple[Stage, Read]:
    """A stage in which the scope selects no device."""
    found = Finding(rule="scope.empty", severity="error", object=SCOPE, message="The scope selects no device.")
    return stage(label), Read(None, (found,), True)


def refused(label: str, finding: Finding) -> tuple[Stage, Read]:
    """A stage whose read the source refused with `finding`."""
    return stage(label), Read(None, (finding,), False)


# A change of five stages: its point of departure, empty in scope; two nodes seeded; a third node; the third link;
# and the head, the same blueprint as the stage before it.
FIVE = (
    empty("branch-point"),
    built("seeded", "steps/two-node.json"),
    built("third-node", "steps/three-node-unlinked.json"),
    built("third-link", "three-node.json"),
    built("head", "three-node.json"),
)
