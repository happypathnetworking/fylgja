"""The example's rules, whose catalogue is `orchestrator/rules.md`: one constant a rule, the severity each is filed at,
the status each error gives, and a finding quoted in a sentence.

A rehearsal's status is given by its document's first error finding, the cause, and by nothing else (D-086): a
document with none has passed. The rules are the example's own, never the core's (formats/README.md, note 11), and
the library branches on a rule, never on a message.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# The errors, each the cause of the status `STATUS` gives it.
STAGES_NONE = "rehearsal.stages.none"
STAGE_REFUSED = "stage.refused"
BASELINE_FAILED = "rehearsal.baseline.failed"
STAGE_FAILED = "rehearsal.stage.failed"
CAPACITY = "rehearsal.capacity"
IMAGE_ABSENT = "rehearsal.image.absent"
ADMISSION_REFUSED = "rehearsal.admission.refused"
CORE_UNREACHABLE = "rehearsal.core.unreachable"
CORE_REFUSED = "rehearsal.core.refused"
SOURCE_FAILED = "rehearsal.source.failed"
TWIN_HELD = "rehearsal.twin.held"
LIMIT_PASSED = "rehearsal.limit.passed"
RUN_CANCELLED = "rehearsal.run.cancelled"
TWIN_DELETED = "rehearsal.twin.deleted"

# The warnings, none of which changes a status.
STEPS_NONE = "rehearsal.steps.none"
TWIN_RECLAIMED = "rehearsal.twin.reclaimed"
REPORT_UNPOSTED = "rehearsal.report.unposted"
TWIN_LEFT = "rehearsal.twin.left"

# The commands' own, which `twin create` and `twin step` file and no rehearsal does: two refusals of the stage a twin
# is taken to, and two notes beside a command's answer.
TARGET_REQUIRED = "step.target.required"
TARGET_UNKNOWN = "step.target.unknown"
TARGET_CURRENT = "step.target.current"
RECORD_STALE = "record.twin.stale"

SEVERITY: dict[str, str] = {
    STAGES_NONE: "error",
    STAGE_REFUSED: "error",
    BASELINE_FAILED: "error",
    STAGE_FAILED: "error",
    CAPACITY: "error",
    IMAGE_ABSENT: "error",
    ADMISSION_REFUSED: "error",
    CORE_UNREACHABLE: "error",
    CORE_REFUSED: "error",
    SOURCE_FAILED: "error",
    TWIN_HELD: "error",
    LIMIT_PASSED: "error",
    RUN_CANCELLED: "error",
    TWIN_DELETED: "error",
    STEPS_NONE: "warning",
    TWIN_RECLAIMED: "warning",
    REPORT_UNPOSTED: "warning",
    TWIN_LEFT: "warning",
    TARGET_REQUIRED: "error",
    TARGET_UNKNOWN: "error",
    TARGET_CURRENT: "info",
    RECORD_STALE: "info",
}

# An error's rule to the status of the rehearsal it is the cause of: failed, where the change failed at a stage;
# not_rehearsed, where the rehearsal could not be carried through for a reason that is not the change's; stopped,
# where it was stopped before anything could be said of the change. A command's refusal of its target is no
# rehearsal's cause, and is failed, so that every error has a status.
STATUS: dict[str, str] = {
    STAGE_REFUSED: "failed",
    BASELINE_FAILED: "failed",
    STAGE_FAILED: "failed",
    STAGES_NONE: "not_rehearsed",
    CAPACITY: "not_rehearsed",
    IMAGE_ABSENT: "not_rehearsed",
    ADMISSION_REFUSED: "not_rehearsed",
    CORE_UNREACHABLE: "not_rehearsed",
    CORE_REFUSED: "not_rehearsed",
    SOURCE_FAILED: "not_rehearsed",
    TWIN_HELD: "not_rehearsed",
    LIMIT_PASSED: "stopped",
    RUN_CANCELLED: "stopped",
    TWIN_DELETED: "stopped",
    TARGET_REQUIRED: "failed",
    TARGET_UNKNOWN: "failed",
}

# The characters a quoted message is cut to, its ellipsis among them.
QUOTED = 300


def quote(f: Mapping[str, Any]) -> str:
    """A finding as a sentence quotes it, `<object>: <message> (<rule>)`: the object and its colon left out where the
    finding names none, and the message's final full stop dropped, then, where it is longer than `QUOTED`
    characters, cut to that many, the last of them `…`."""
    message: str = f["message"]
    message = message.removesuffix(".")
    if len(message) > QUOTED:
        message = message[: QUOTED - 1] + "…"
    about = f.get("object")
    return f"{about}: {message} ({f['rule']})" if about else f"{message} ({f['rule']})"
