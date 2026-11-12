"""Rehearsal 1 documents built by hand in the shape of `sources.FIVE`, a change of five stages, for the report's tests
(D-087): each validated as it is built, its headline the one `report.headline` gives it, as a rehearsal's document
holds it. A test that changes a document gives it its headline again with `headed`."""

from __future__ import annotations

from collections.abc import Sequence
from hashlib import sha256
from typing import Any

from sources import CHANGE, SCOPE

from fylgja_orchestrator.rehearsal import documents, rules, twin_name, twin_prefix
from fylgja_orchestrator.rehearsal.documents import finding
from fylgja_orchestrator.rehearsal.report import headline
from fylgja_orchestrator.rehearsal.rules import quote

RUN = "run-1"
TWIN = twin_name(CHANGE, RUN)
EARLIER = twin_prefix(CHANGE) + "00000000"
READ_AT = "2026-11-09T10:15:11Z"
LABELS = ("branch-point", "seeded", "third-node", "third-link", "head")
# What each stage changed from the one built before it, as the plan says it; the first selects no device in scope.
CHANGED = (
    None,
    "baseline: 2 nodes, 1 link",
    "1 node added (n3); 1 link added (n1 to n3)",
    "1 link added (n2 to n3)",
    "nothing",
)
EMPTY = finding("scope.empty", "error", "The scope selects no device.", SCOPE)
PUSH = finding("push.refused", "error", "At line 1: n2 refused the configuration", "n2")
UNREAD = finding("verify.node.unread", "error", "n1 could not be read over gNMI.", "n1")
APPROXIMATION = {"package": "nokia_srlinux", "text": "No linecard model"}
HELD = {"held": 9, "failed": 0, "skipped": 0}
ROOM = ["fake: 2 of 8 CPUs and 4096 of 16384 MiB free", "pending: 0 nodes, 0 CPUs, 0 MiB"]


def _id(text: str) -> str:
    """A content address that looks like the core's."""
    return sha256(text.encode()).hexdigest()


def run(k: int) -> str:
    """The core's run that took the twin to stage `k`, a ULID."""
    return f"01JC0Z8X4M3T5V6W7Y8Z9A{k:04d}"


def plan(labels: Sequence[str] = LABELS, changed: Sequence[str | None] = CHANGED) -> dict[str, Any]:
    """The plan of a change of a stage a label: the first selects no device in scope, and every other built, saying
    what it changed as `changed` does."""
    stages: list[dict[str, Any]] = [
        {"label": labels[0], "where": f"stage {labels[0]} as pinned", "outcome": "empty", "findings": [EMPTY]}
    ]
    for label, words in zip(labels[1:], changed[1:], strict=True):
        stages.append({
            "label": label,
            "where": f"stage {label} as pinned",
            "outcome": "built",
            "blueprint_id": _id(f"blueprint {label}"),
            "bundle_id": _id(f"bundle {label}"),
            "changed": words,
            "unchanged": words == "nothing",
            "findings": [],
            "omitted": [],
            "approximations": [APPROXIMATION],
        })
    n = len(labels)
    doc: dict[str, Any] = {
        "plan_version": "1",
        "status": "planned",
        "headline": f"Plan: {n - 1} of {n} stages build\nThe baseline is stage 2, {labels[1]}; {n - 2} stages follow "
        "it.",
        "change": {"id": CHANGE.id, "where": CHANGE.where},
        "scope": SCOPE,
        "read_at": READ_AT,
        "findings": [],
        "stages": stages,
    }
    assert documents.validate("plan-1", doc) == []
    return doc


def headed(doc: dict[str, Any]) -> dict[str, Any]:
    """`doc` with the headline the report gives it, once it validates."""
    doc["headline"] = headline(doc)
    assert documents.validate("rehearsal-1", doc) == []
    return doc


def rehearsal(
    status: str, planned: dict[str, Any] | None, stages: list[dict[str, Any]], findings: list[dict[str, Any]],
    **members: Any,
) -> dict[str, Any]:
    """A rehearsal 1 document of the plan `planned`, its stages and its own findings as given, and any other member
    as `members` gives it."""
    doc: dict[str, Any] = {
        "rehearsal_version": "1",
        "status": status,
        "headline": "",
        "plan": planned,
        "twin": TWIN,
        "run_id": RUN,
        "took_s": 75.2,
        "stages": stages,
        "already_failing": [],
        "reclaimed": [],
        "findings": findings,
    }
    return headed(doc | members)


def created(k: int) -> dict[str, Any]:
    """Stage `k`, the baseline the twin was created at, verified."""
    return {"result": "created", "counts": dict(HELD), "run_id": run(k), "took_s": 41.0}


def stepped(k: int) -> dict[str, Any]:
    """Stage `k`, stepped to and verified."""
    return {"result": "passed", "counts": dict(HELD), "run_id": run(k), "took_s": 12.5}


def unreached(count: int) -> list[dict[str, Any]]:
    """`count` stages not reached."""
    return [{"result": "not_reached"} for _ in range(count)]


def passed() -> dict[str, Any]:
    """A rehearsal of every stage: the baseline created, two stepped to, and the head, unchanged, skipped; an earlier
    rehearsal's twin removed before it started."""
    reclaimed = finding(rules.TWIN_RECLAIMED, "warning", f"The twin {EARLIER}, left by an earlier rehearsal of this "
                        "change, was removed before this one started.")
    stages = [{"result": "empty"}, created(2), stepped(3), stepped(4), {"result": "skipped"}]
    return rehearsal("passed", plan(), stages, [reclaimed], reclaimed=[EARLIER])


def failed_at(
    k: int, labels: Sequence[str] = LABELS, changed: Sequence[str | None] = CHANGED, failure: dict[str, Any] = PUSH
) -> dict[str, Any]:
    """A rehearsal of the plan of `labels` whose step to stage `k`, after the baseline, failed with `failure` and left
    the twin diverged: the stages before it created or passed, those after it not reached."""
    stages = [
        {"result": "empty"},
        created(2),
        *(stepped(j) for j in range(3, k)),
        {"result": "failed", "failures": [failure], "run_id": run(k), "took_s": 13.1},
        *unreached(len(labels) - k),
    ]
    cause = f"The step to stage {k}, {labels[k - 1]}, failed and left the twin diverged: {quote(failure)}."
    return rehearsal("failed", plan(labels, changed), stages, [finding(rules.STAGE_FAILED, "error", cause)])


def failed_at_four() -> dict[str, Any]:
    """The rehearsal the maintainer was shown the report of: the step to stage 4, third-link, refused by n2."""
    return failed_at(4)


def no_room() -> dict[str, Any]:
    """A rehearsal the runtime had no room for: the look's dry run of stage 2, the baseline, refused for room, and the
    capacity then read."""
    cause = ("The runtime has no room for the twin of stage 2, seeded: The twin needs 4 CPUs, and the host has 2 free "
             "with 0 pending. Nothing is wrong with the change: run the checks again when the runtime has room.")
    stages = [{"result": "empty"}, *unreached(4)]
    return rehearsal("not_rehearsed", plan(), stages, [finding(rules.CAPACITY, "error", cause)], took_s=3.4, room=ROOM)


def stopped() -> dict[str, Any]:
    """A rehearsal whose twin a newer rehearsal of the change deleted as it stepped to stage 3."""
    cause = (f"The twin {TWIN} was deleted while the rehearsal ran, by a newer rehearsal of this change or by hand, so "
             "it stopped at stage 3, third-node. The newer rehearsal's report stands.")
    stages = [{"result": "empty"}, created(2), *unreached(3)]
    return rehearsal("stopped", plan(), stages, [finding(rules.TWIN_DELETED, "error", cause)], took_s=52.0)


def held() -> dict[str, Any]:
    """A rehearsal that ended before its plan began: an earlier rehearsal's twin was not removed in time."""
    cause = (f"An earlier rehearsal's twin, {EARLIER}, was not removed within 120 s, so this rehearsal did not start. "
             f"Remove it with fylgja-core twin destroy {EARLIER}, then run the checks again.")
    return rehearsal("not_rehearsed", None, [], [finding(rules.TWIN_HELD, "error", cause)], took_s=120.4)
