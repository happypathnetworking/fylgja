"""A proposed change's stages (014, D-045 to D-048): the moments of a proposed change that a
twin is built from, planned through and stepped along. Ported from `internal/stages`'
ref.go, resolve.go, stale.go, list.go, target.go and blocks.go, and the read-and-take of
`internal/stage/stage.go` and `internal/server/resolve.go`, word for word: every refusal is
filed under the rule the core filed it under, worded as it worded it.

Every proposed change has two derived stages, the branch point (the destination pinned at
the source branch's branched_from) and the head (the source branch pinned one microsecond
after its latest stamp or intent event), and between them the operator's marks,
FylgjaStage objects ordered by their `at`. This module holds the reference syntax, the order
with its ends derived, every resolution rule and its refusal, the staleness rule, the list,
the step's target and the blocks the findings document carries.

A stage is read, never written: every request to Infrahub is a query (Constitution III). It
resolves before any branch's intent is read, and nothing of the stage enters a CTM, a
snapshot or a bundle. The reads go through two collaborators, faked in tier 1: a reader of
the default branch (`stage_reader.StageReader`: `check`, `proposed_changes`, `orphans`,
`branch`, `validations`, `intent_events`) and a stamper (`Stamper`: `stamps(branch, at,
scope)`). A reader or a stamper that cannot reach Infrahub raises, never a finding, for the
caller to report as operation.failed.
"""

import calendar
import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from functools import cmp_to_key

from fylgja_orchestrator.adapters.infrahub import read as reading
from fylgja_orchestrator.adapters.infrahub import stage_reader as sr
from fylgja_orchestrator.adapters.infrahub.client import (
    MAX_AT_FRACTION_DIGITS,
    Client,
    ClientError,
    Config,
    at_fraction_digits,
    check_at_precision,
)
from fylgja_orchestrator.adapters.infrahub.schema import ConformanceError, check_conformance
from fylgja_orchestrator.adapters.infrahub.stamps import Stamps, read_stamps
from fylgja_orchestrator.documents.findings import REJECTION, WARNING, Finding, Findings, quote

# The reference syntax <branch>/<label>.

BRANCH_PATTERN = r"^[^/\s]+$"
"""A source branch as a reference names one: no "/" and no whitespace, so a reference is one
shell word."""

LABEL_PATTERN = r"^[^/\s]+$"
"""A mark's label. It equals the regex the kind enforces at write (schema/fylgja-stage.yaml),
and a test holds the two equal, so the command line refuses exactly what Infrahub would."""

BRANCH_FORM = 'a branch with no "/" and no whitespace'
"""How a refusal names a branch, the same words in FORM and in the refusal of stage list's
and stage plan's --branch."""

FORM = "<branch>/<label>, " + BRANCH_FORM + " and a label with neither"
"""How a refusal names the syntax, the same words wherever a reference is refused."""

LABEL_BRANCH_POINT = "branch-point"
"""The derived stage at the source branch's branched_from, read on the destination."""

LABEL_HEAD = "head"
"""The derived stage one microsecond after the later of the source branch's latest stamp and
its latest intent event (D-048)."""

# Go's regexp matches `$` at the end of the text alone, as fullmatch does; Python's `\s` is
# Go's `\s` widened to Unicode's spaces, so the pattern is spelled in ASCII's.
_WORD = re.compile(r"[^/\t\n\f\r ]+")

# Where a stage's at came from (FR-007).

AT_GIVEN = "given"
"""as_of is written on the mark, and is used verbatim."""

AT_WRITTEN = "written"
"""The mark carries no as_of, and the at is its own write stamp, its label's updated_at."""

AT_BRANCH_POINT = "branch_point"
"""The source branch's branched_from, verbatim, read on the default branch."""

AT_HEAD = "head"
"""The later of the latest stamp and the latest intent event, plus one microsecond."""

STEP_RESOLVE = "resolve"

# The rules this module files, each the core's id, severity, exit and step
# (`internal/findings/finding.go`); `documents/rules.py` gathers them (T019).

RULE_STAGE_REF_INVALID = "stage.ref.invalid"
RULE_STAGE_KIND_ABSENT = "stage.kind.absent"
RULE_STAGE_UNKNOWN = "stage.unknown"
RULE_STAGE_DUPLICATE = "stage.duplicate"
RULE_STAGE_AT_UNRESOLVED = "stage.at.unresolved"
RULE_STAGE_AT_BEFORE_BRANCH_POINT = "stage.at.before_branch_point"
RULE_STAGE_LABEL_RESERVED = "stage.label.reserved"
RULE_STAGE_ARTIFACT_STALE = "stage.artifact.stale"
RULE_STAGE_ORPHANED = "stage.orphaned"
RULE_STAGE_MAIN_MOVED = "stage.main.moved"
RULE_STAGE_TWIN_MOVED = "stage.twin.moved"
RULE_STEP_TARGET_UNKNOWN = "step.target.unknown"
RULE_STEP_TARGET_CURRENT = "step.target.current"
RULE_STEP_STAGE_SKIPPED = "step.stage.skipped"
RULE_AT_PRECISION = "intent.at.precision"

KIND_REMEDY = f": load {sr.STAGE_SCHEMA_FILE} on it; only --stage, stage list and stage plan need it"
"""What follows the kind's error in every stage.kind.absent finding."""

REMEDY = (
    "regenerate (fylgja-fixture -generate, POST /api/artifact/generate, or the proposed change's checks: "
    "a retry in Infrahub, or CoreProposedChangeRunCheck)"
)
"""Both ways to regenerate a proposed change's artifacts (D-046)."""

NO_TARGET_MESSAGE = (
    "the twin names no stage, so there is no next stage to step to; "
    "give --stage <branch>/<label> or --snapshot <id|file>"
)
"""step.target.unknown's message for a step given no target, of a twin whose record names
no stage (019, research R-08)."""

STATE_DIVERGED = "diverged"


class StagesError(Exception):
    """A resolution that could not run, safe to print: Infrahub holding two open proposed
    changes on one source branch, which it refuses itself, or a stamp that is no time. The
    command files it operation.failed, as the core filed its error."""


class RefError(ValueError):
    """A --stage or --branch value refused before any connection, stage.ref.invalid; its
    words name the form."""


# The reference.


@dataclass(frozen=True)
class Ref:
    """One stage: the proposed change by its source branch, then the label."""

    branch: str
    label: str

    def __str__(self) -> str:
        return self.branch + "/" + self.label

    @property
    def derived(self) -> bool:
        """Whether the reference names one of the two derived stages."""
        return reserved(self.label)


def reserved(label: str) -> bool:
    """Whether a label names a derived stage."""
    return label in (LABEL_BRANCH_POINT, LABEL_HEAD)


def parse_ref(s: str) -> Ref:
    """--stage's value, split at its first "/". Anything but one branch and one label, each
    one shell word, is refused naming the form; the caller files it stage.ref.invalid
    before any connection. A second "/" goes to the label, whose pattern refuses it."""
    branch, sep, label = s.partition("/")
    if sep and _WORD.fullmatch(branch) and _WORD.fullmatch(label):
        return Ref(branch, label)
    raise RefError(f"--stage {quote(s)} is not a stage reference: expected {FORM}")


def check_branch(b: str) -> None:
    """--branch's value on stage list and stage plan: a branch as the reference names one,
    else refused in the shape of parse_ref's sentence."""
    if not _WORD.fullmatch(b):
        raise RefError(f"--branch {quote(b)} is not a branch: expected {BRANCH_FORM}")


# Instants.

_AT = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})"
    r"(?:(?P<sep>[T ])(\d{2}):(\d{2}):(\d{2})(?:[.,](\d+))?(?P<zone>Z|[+-]\d{2}:\d{2})?)?"
)


def _instant(s: str, layouts: str = "any") -> tuple[int, int] | None:
    """An at as the core's `ParseAt` reads it, as nanoseconds since the epoch and the offset
    in seconds: RFC 3339 with any fraction and a Z or an offset, the same with a space for
    the T, the naive forms of both, read as UTC, and a date. `layouts="rfc3339"` reads Go's
    `time.RFC3339Nano` alone. A fraction past nine digits is cut, as Go cuts it."""
    m = _AT.fullmatch(s) if isinstance(s, str) else None
    if m is None:
        return None
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    timed = m.group("sep") is not None
    if layouts == "rfc3339" and (m.group("sep") != "T" or m.group("zone") is None):
        return None
    if not timed:
        hour = minute = second = 0
        fraction = ""
    else:
        hour, minute, second = int(m.group(5)), int(m.group(6)), int(m.group(7))
        fraction = m.group(8) or ""
    try:
        datetime(year, month, day, hour, minute, second)
    except ValueError:
        return None
    offset = 0
    zone = m.group("zone")
    if zone and zone != "Z":
        sign = -1 if zone[0] == "-" else 1
        offset = sign * (int(zone[1:3]) * 3600 + int(zone[4:6]) * 60)
    nanos = int((fraction + "000000000")[:9]) if fraction else 0
    seconds = calendar.timegm((year, month, day, hour, minute, second, 0, 0, 0)) - offset
    return seconds * 1_000_000_000 + nanos, offset


def parse_at(s: str) -> int | None:
    """An at for the comparisons that need an instant: the order, the future rule, the
    branch point, the staleness rule; None for a form none of the layouts reads, about which
    the caller makes no claim. Nothing parsed here is ever sent: a query carries the at as
    written, and the head's as head_at formats it."""
    parsed = _instant(s)
    return parsed[0] if parsed else None


def later(a: str, b: str) -> bool:
    """Whether stamp a is later than b, both as Infrahub returned them; a stamp that does not
    parse is later than nothing and nothing is later than it."""
    ta, tb = parse_at(a), parse_at(b)
    return ta is not None and tb is not None and ta > tb


def later_than(a: str, b: str) -> bool:
    """Whether stamp a is later than stamp b, raising StagesError for one that is no time."""
    ta, tb = parse_at(a), parse_at(b)
    for s, t in ((a, ta), (b, tb)):
        if t is None:
            raise StagesError(f"the stamp {quote(s)} Infrahub returned is not an RFC 3339 time")
    return ta > tb


def head_at(latest: str) -> str:
    """The head's at: the later of the branch's latest stamp and its latest intent event's
    occurred_at, plus one microsecond, in Infrahub's own layout and the stamp's own offset
    (`2026-10-08T05:48:38.544483+00:00`). A read pinned at exactly a stamp sees the node and
    not the value, so the head takes the first instant after."""
    parsed = _instant(latest, "rfc3339")
    if parsed is None:
        raise StagesError(f"the stamp {quote(latest)} Infrahub returned is not an RFC 3339 time")
    nanos, offset = parsed
    local = nanos + offset * 1_000_000_000 + 1_000
    seconds, rest = divmod(local, 1_000_000_000)
    wall = datetime(1970, 1, 1) + timedelta(seconds=seconds)
    sign = "-" if offset < 0 else "+"
    hours, minutes = divmod(abs(offset) // 60, 60)
    return f"{wall:%Y-%m-%dT%H:%M:%S}.{rest // 1000:06d}{sign}{hours:02d}:{minutes:02d}"


def now_text(now: datetime) -> str:
    """How the server's clock is named in a refusal: UTC, six fractional digits."""
    return now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _now_nanos(now: datetime) -> int:
    now = now.astimezone(UTC)
    return calendar.timegm(now.timetuple()) * 1_000_000_000 + now.microsecond * 1_000


# The stages.


@dataclass(frozen=True)
class ProposedChange:
    """The proposed change a stage belongs to, as the blocks name it. `destination` is the
    branch it merges into, main in Infrahub 1.11.2: the branch the branch point is read on,
    and whose movement stage.main.moved reports."""

    id: str
    name: str
    branch: str
    destination: str = "main"
    draft: bool = False

    def block(self) -> dict:
        return {"id": self.id, "name": self.name, "branch": self.branch, "draft": self.draft}


@dataclass(frozen=True)
class Resolved:
    """One stage resolved to the pinned intent reference it names. `branch` is the branch the
    read is on: the destination for the branch point, the source branch otherwise. `at` is
    verbatim; `id` is the mark's object id, "" for a derived stage."""

    ref: Ref
    branch: str
    label: str
    proposed_change: ProposedChange
    at: str = ""
    at_source: str = ""
    description: str = ""
    id: str = ""

    def block(self) -> dict:
        """The resolved stage as the document's stage block carries it ($defs/resolved)."""
        return {
            "ref": str(self.ref),
            "branch": self.branch,
            "label": self.label,
            "proposed_change": self.proposed_change.block(),
            "at": self.at,
            "at_source": self.at_source,
            "description": self.description,
        }


@dataclass(frozen=True)
class Stage:
    """One stage of a proposed change in its place, resolved by the listing's rules alone,
    refusing nothing. `mark` is the operator's object, None for the two derived stages; the
    at is "" when nothing names it."""

    resolved: Resolved
    mark: sr.Mark | None = None

    @property
    def ref(self) -> Ref:
        return self.resolved.ref

    @property
    def label(self) -> str:
        return self.resolved.label

    @property
    def branch(self) -> str:
        return self.resolved.branch

    @property
    def at(self) -> str:
        return self.resolved.at

    @property
    def at_source(self) -> str:
        return self.resolved.at_source

    @property
    def id(self) -> str:
        return self.resolved.id


def refusal(rule: str, object: str, message: str) -> Finding:
    return Finding(REJECTION, rule, object, message, STEP_RESOLVE)


def warning(f: Finding) -> Finding:
    """A resolution's refusal as a listing files it: the same rule, object and wording,
    refusing nothing."""
    return replace(f, severity=WARNING)


def gone(branch: str, id: str) -> str:
    """How a branch deleted under its open proposed change is named: Infrahub cancels the
    proposed change some seconds after, and until then it names a branch that does not
    exist."""
    return (
        f"branch {branch} does not exist; the open proposed change {id} still names it "
        "(Infrahub cancels it about sixteen seconds after a branch is deleted)"
    )


def _rank(st: Stage) -> int:
    if st.mark is not None:
        return 1
    return 0 if st.label == LABEL_BRANCH_POINT else 2


def _less(a: Stage, b: Stage) -> bool:
    ra, rb = _rank(a), _rank(b)
    if ra != rb or ra != 1:
        return ra < rb
    ta, tb = parse_at(a.at), parse_at(b.at)
    if ta is not None and tb is not None and ta != tb:
        return ta < tb
    if (ta is not None) != (tb is not None):
        return ta is not None
    if ta is None and a.at != b.at:
        return a.at < b.at
    if a.label != b.label:
        return a.label < b.label
    return a.id < b.id


def order(stages) -> list[Stage]:
    """A proposed change's stages in order (FR-005): the branch point first, the marks by
    their at, the head last, whatever the marks' stamps. Two marks at one instant go by
    label, then id; a mark whose at does not parse goes after those that do, by its string,
    and makes no time claim. A mark labelled like a derived stage is a mark here."""
    return sorted(stages, key=cmp_to_key(lambda a, b: -1 if _less(a, b) else (1 if _less(b, a) else 0)))


def _latest_event(evs) -> object | None:
    """The latest of the events by when each occurred, None when there is none; two at one
    instant keep the first."""
    latest = None
    for ev in evs:
        if latest is None or later(ev.occurred_at, latest.occurred_at):
            latest = ev
    return latest


class Change:
    """One open proposed change as a resolution reads it (steps 1–3 and 6): the proposed
    change, its source branch's origin (`branched_from`, which a rebase moves, and
    `created_at`, which it does not, both verbatim), and its stages in order, the head's at
    computed from the branch's unpinned stamps and its intent events. `scope` is the scope
    every stage is resolved, read and planned under, tag:<name> (017)."""

    def __init__(self, pc: sr.ProposedChange, info: sr.BranchInfo, head: Stamps, evs, scope: str = ""):
        self.proposed_change = ProposedChange(pc.id, pc.name, pc.branch, pc.destination, pc.draft)
        self.branched_from = info.branched_from
        self.created_at = info.created_at
        self.scope = scope
        self._head = head
        self._main: Stamps | None = None
        # The source branch's intent events read so far, newest first: every one after
        # _events_after, or since the branch point when it is "". None before any read.
        self._events = list(evs or [])
        self._events_after: str | None = None

        def derived(label: str, branch: str, at: str, source: str) -> Stage:
            return Stage(Resolved(Ref(pc.branch, label), branch, label, self.proposed_change, at, source))

        stages = [derived(LABEL_BRANCH_POINT, pc.destination, info.branched_from, AT_BRANCH_POINT)]
        stages.extend(self._mark(m) for m in pc.stages)
        latest = head.latest
        ev = _latest_event(self._events)
        if ev is not None and (not latest or later(ev.occurred_at, latest)):
            latest = ev.occurred_at
        try:
            at = head_at(latest)
        except StagesError:
            at = ""
        stages.append(derived(LABEL_HEAD, pc.branch, at, AT_HEAD))
        self.stages = order(stages)

    def _mark(self, m: sr.Mark) -> Stage:
        """One mark resolved by step 5 without its rules: the written as_of verbatim, or else
        the label's updated_at verbatim."""
        pc = self.proposed_change
        at, source = (m.at, AT_GIVEN) if m.at is not None else (m.label_written_at, AT_WRITTEN)
        return Stage(Resolved(Ref(pc.branch, m.label), pc.branch, m.label, pc, at, source, m.description, m.id), m)

    def labels(self) -> list[str]:
        """The proposed change's stages as references name them, in order, each once. A label
        two marks share is one stage, at its first place; a mark labelled like a derived stage
        shares the derived stage's place. The resolution refuses both."""
        seen, out = set(), []
        for st in self.stages:
            if st.label in seen or (st.mark is not None and reserved(st.label)):
                continue
            seen.add(st.label)
            out.append(st.label)
        return out

    def first(self, label: str) -> Stage | None:
        """The stage a label names in the order: the derived stage for a reserved label, else
        the first mark of it; None when no stage carries it."""
        for st in self.stages:
            if st.label == label and (st.mark is None) == reserved(label):
                return st
        return None

    def describe(self) -> str:
        pc = self.proposed_change
        return f"proposed change {quote(pc.name)} ({pc.id}) on branch {pc.branch}"

    def reserved_refusal(self, ref: Ref) -> Finding:
        """stage.label.reserved for a mark labelled like a derived stage."""
        what = "branch point" if ref.label == LABEL_BRANCH_POINT else "head"
        return refusal(
            RULE_STAGE_LABEL_RESERVED,
            str(ref),
            f"stage {ref} is a mark labelled {quote(ref.label)}, which names the derived {what} of every proposed "
            f"change and is reserved; relabel it (schema/README.md); the {what} of {ref.branch} is still its "
            "derived stage",
        )

    def pick(self, ref: Ref) -> tuple[Stage | None, Findings]:
        """Step 4: the stage the reference names among the branch point, the marks and the
        head. A reserved label names the derived stage, and a mark carrying it refuses the
        reference until it is relabelled; a mark's label names exactly one mark."""
        pc = self.proposed_change
        if ref.branch != pc.branch:
            return None, Findings([refusal(RULE_STAGE_UNKNOWN, str(ref),
                                           f"stage {ref} is not of proposed change {pc.id}, whose source branch is "
                                           f"{pc.branch}")])
        marks = [st for st in self.stages if st.mark is not None and st.label == ref.label]
        if ref.derived:
            if marks:
                return None, Findings([self.reserved_refusal(ref)])
            return self.first(ref.label), Findings()
        if not marks:
            return None, Findings([refusal(RULE_STAGE_UNKNOWN, str(ref),
                                           f"{self.describe()} has no stage {quote(ref.label)}; its stages are: "
                                           f"{', '.join(self.labels())}")])
        if len(marks) == 1:
            return marks[0], Findings()
        ids = sorted(st.id for st in marks)
        return None, Findings([refusal(
            RULE_STAGE_DUPLICATE, str(ref),
            f"stage {ref} is held by {len(marks)} objects (ids {', '.join(ids)}), which the kind's uniqueness "
            "constraint should have refused; none is chosen",
        )])

    def check(self, st: Stage, now: datetime | None) -> Findings:
        """Steps 5 and 7: the stage has an at, honoured by Infrahub, not in the future when
        given, and not before the branch point. The head has none when the scope's stamps
        selected no device and the branch holds no intent event since its branch point:
        scope.empty naming the scope, filed at resolve (017)."""
        ref = st.ref
        if not st.at:
            why = "no as_of is written on it and Infrahub returned no updated_at for its label"
            if st.mark is not None:
                pass
            elif st.at_source == AT_HEAD and not self._head.devices:
                return Findings([replace(reading.scope_empty(self.scope, ref.branch, ""), step=STEP_RESOLVE)])
            elif st.at_source == AT_HEAD:
                why = (f"Infrahub returned no stamp for the devices scope {self.scope} selects on branch {ref.branch} "
                       "or for anything of theirs")
            else:
                why = "Infrahub returned no branched_from for branch " + ref.branch
            return Findings([refusal(RULE_STAGE_AT_UNRESOLVED, str(ref),
                                     f"stage {ref} has no at: {why}, so it names no point in time")])
        if st.mark is None:
            return Findings()
        if check_at_precision(st.at):
            return Findings([refusal(
                RULE_AT_PRECISION, str(ref),
                f"stage {ref}: at {st.at} carries {at_fraction_digits(st.at)} fractional digits; Infrahub honours at "
                f"most {MAX_AT_FRACTION_DIGITS} (microseconds). Write the stage's as_of with at most six.",
            )])
        at = parse_at(st.at)
        if at is None:
            return Findings()  # a form that does not parse makes no claim, and is passed verbatim
        # The future rule, for a given at alone: a written at is Infrahub's own stamp of a
        # write it has already made.
        if st.at_source == AT_GIVEN and now is not None and at > _now_nanos(now):
            return Findings([refusal(
                RULE_STAGE_AT_UNRESOLVED, str(ref),
                f"stage {ref} has at {st.at} ({st.at_source}), later than the current time {now_text(now)}: it seals "
                "nothing yet, and a twin from it could differ between two creates",
            )])
        branched = parse_at(self.branched_from)
        if branched is None or at >= branched:
            return Findings()
        created = parse_at(self.created_at)
        if created is not None and at > created:
            return Findings([refusal(
                RULE_STAGE_AT_BEFORE_BRANCH_POINT, str(ref),
                f"stage {ref} has at {st.at}, before the branch point {self.branched_from} of {ref.branch}: a rebase "
                f"at {self.branched_from} moved the branch point past it (the branch was created at "
                f"{self.created_at}); mark the stage again, or delete it",
            )])
        return Findings([refusal(
            RULE_STAGE_AT_BEFORE_BRANCH_POINT, str(ref),
            f"stage {ref} has at {st.at}, before the branch point {self.branched_from} of {ref.branch}, and before "
            f"the branch was created at {self.created_at}; a stage names a moment on its source branch",
        )])

    def intent_events(self, reader, after: str) -> list:
        """The source branch's intent events that occurred after `after`, newest first, every
        one since the branch point when `after` is "". One read serves every stage of the
        proposed change: a read down to an earlier bound serves a later one, and only a bound
        earlier than the last read's reads again."""
        bound = self._events_after
        if bound is None or (bound != "" and (after == "" or later(bound, after))):
            evs = _read_events(reader, self.proposed_change.branch, self.branched_from, after)
            self._events, self._events_after = evs, after
            return evs
        if after == "" or bound == after:
            return self._events
        return [ev for ev in self._events if later(ev.occurred_at, after)]

    def main_moved(self, stamper) -> Findings:
        """Step 9: the warning stage.main.moved when the destination's latest stamp, read
        unpinned once per proposed change, is later than the branch's branched_from. It
        refuses nothing. A destination whose schema does not conform is refused with its
        schema.* findings instead."""
        if self._main is None:
            try:
                self._main = stamper.stamps(self.proposed_change.destination, "", self.scope)
            except ConformanceError as e:
                return conformance_refusal(e)
        return _main_moved(self, self._main)


def _main_moved(c: Change, main: Stamps) -> Findings:
    latest = parse_at(main.latest) if main.latest else None
    branched = parse_at(c.branched_from)
    if latest is None or branched is None or latest <= branched:
        return Findings()
    b, dest = c.proposed_change.branch, c.proposed_change.destination
    return Findings([Finding(
        WARNING, RULE_STAGE_MAIN_MOVED, b,
        f"{dest} has moved since {b}'s branch point: its latest write is {main.latest}, the branch point "
        f"{c.branched_from}; the branch point stage still reads {dest} as it was then, and nothing is refused",
        STEP_RESOLVE,
    )])


def _read_events(reader, branch: str, since: str, after: str) -> list:
    """The reader's intent events for a branch, none when Infrahub returned no branched_from
    for it: nothing then bounds the log to the branch's own history."""
    if not since:
        return []
    return reader.intent_events(branch, since, after)


def conformance_refusal(e: ConformanceError) -> Findings:
    """A stamps read refused for its branch's schema (017): its schema.* findings, each a
    rejection at resolve whose message names the branch first, since the branch refused may
    be the destination rather than the one the command names."""
    return Findings(replace(f, step=STEP_RESOLVE, message=f"branch {e.branch}: {f.message}") for f in e.findings)


def _unfiled(add: Findings, have: Findings) -> Findings:
    """The findings of add that have does not hold already: a destination whose schema does
    not conform is refused once (017)."""
    key = lambda f: (f.severity, f.rule, f.object, f.message)  # noqa: E731
    seen = {key(f) for f in have}
    return Findings(f for f in add if key(f) not in seen)


def _change(reader, stamper, pc: sr.ProposedChange, info: sr.BranchInfo, scope: str) -> Change:
    """A proposed change's stages in order, its head one microsecond after the later of the
    branch's latest stamp, read unpinned under scope, and its latest intent event; only the
    events after the latest stamp can move it, so only their pages are read."""
    head = stamper.stamps(pc.branch, "", scope)
    if head.latest:
        try:
            head_at(head.latest)
        except StagesError as e:
            raise StagesError(f"the head of {pc.branch}: {e}") from None
    evs = _read_events(reader, pc.branch, info.branched_from, head.latest)
    ch = Change(pc, info, head, evs, scope)
    ch._events_after = head.latest
    return ch


def _check_kind(reader) -> Findings:
    """Step 1: the reader's StageKindError filed as stage.kind.absent."""
    try:
        reader.check()
    except sr.StageKindError as e:
        return Findings([refusal(RULE_STAGE_KIND_ABSENT, sr.STAGE_KIND, f"{e}{KIND_REMEDY}")])
    return Findings()


def _no_open_change(every: list, branch: str) -> Finding:
    names = sorted({pc.branch for pc in every})
    exist = "the branches with one are: " + ", ".join(names) if names else "there is no open proposed change"
    return refusal(RULE_STAGE_UNKNOWN, branch, f"no open proposed change has source branch {branch}; {exist}")


def find(reader, stamper, branch: str, scope: str) -> tuple[Change | None, Findings]:
    """Steps 1–3 for one source branch, and step 6: the kind on the default branch, the open
    proposed change whose source the branch is, the branch's origin, and the head's at. Each
    refusal is a rejection at resolve with no Change, a branch whose schema does not conform
    among them. Two open proposed changes on one branch, which Infrahub refuses, raise
    StagesError: none is chosen. Nothing of the branch's intent is read."""
    kind = _check_kind(reader)
    if kind:
        return None, kind
    open_ = [pc for pc in reader.proposed_changes(branch) if pc.branch == branch]
    if not open_:
        return None, Findings([_no_open_change(reader.proposed_changes(""), branch)])
    if len(open_) > 1:
        ids = ", ".join(pc.id for pc in open_)
        raise StagesError(
            f"branch {branch} has {len(open_)} open proposed changes (ids {ids}), which Infrahub refuses; "
            "none is chosen"
        )
    pc = open_[0]
    info = reader.branch(branch)
    if info is None:
        return None, Findings([refusal(RULE_STAGE_UNKNOWN, branch, gone(branch, pc.id))])
    try:
        return _change(reader, stamper, pc, info, scope), Findings()
    except ConformanceError as e:
        return None, conformance_refusal(e)


def stale(reader, stamper, registry, ch: Change, st: Resolved) -> Findings:
    """Step 8, the staleness rule (D-046, widened by D-048): at the stage's at, each device is
    stale when its intent was written later than its generation stamp, the later of its
    artifact's checksum.updated_at and the proposed change's artifact validator's
    completed_at. Its intent was written at the later of the latest stamp of its own intent
    and the latest intent event naming it, no later than the stage's at. The artifact is the
    one named by the device's package's config.artifact_name, matched exactly
    (Constitution II). One stage.artifact.stale per stale device, sorted by name.

    The stamps are read on the stage's branch pinned at its at; the head's are the unpinned
    stamps its at came from. The events are read after the earliest checksum among the
    devices judged (every one since the branch point when one is unstamped); the branch point
    reads none. The validator is read only when some device's checksum alone leaves it
    stale: pinned at the stage's at, and unpinned for the head, whose at its completion never
    enters. A device no package matches, or with no artifact of its package's name, is the
    read's to refuse, not stale."""
    stamps, validated_at = ch._head, st.at
    if st.at_source == AT_HEAD:
        validated_at = ""
    else:
        try:
            stamps = stamper.stamps(st.branch, st.at, ch.scope)
        except ConformanceError as e:
            return conformance_refusal(e)

    judged = []
    floor, unstamped = "", False
    for name, d in stamps.devices.items():
        pkg = registry.match(d.match.manufacturer, d.match.platform)
        if pkg is None or pkg.artifact_name not in d.artifacts:
            continue
        checksum = d.artifacts[pkg.artifact_name]
        if checksum == "":
            unstamped = True
        elif parse_at(checksum) is None:
            raise StagesError(f"the stamp {quote(checksum)} Infrahub returned is not an RFC 3339 time")
        elif floor == "" or later(floor, checksum):
            floor = checksum
        judged.append((name, pkg.artifact_name, checksum, d))
    if not judged:
        return Findings()
    if unstamped:
        floor = ""
    evs = []
    stage_at = parse_at(st.at)
    if st.branch == ch.proposed_change.branch and stage_at is not None:
        evs = ch.intent_events(reader, floor)

    candidates = []
    for name, artifact, checksum, d in judged:
        intent, event = d.intent, None
        for ev in evs:
            at = parse_at(ev.occurred_at)
            if (at is not None and at > stage_at) or not ev.names(d.ids):
                continue
            if intent == "" or later(ev.occurred_at, intent):
                intent, event = ev.occurred_at, ev
        if intent == "":
            continue
        if checksum != "" and not later_than(intent, checksum):
            continue
        candidates.append((name, artifact, intent, d.intent, checksum, event))
    if not candidates:
        return Findings()
    candidates.sort(key=lambda c: c[0])

    validated = reader.validations(st.proposed_change.id, validated_at)
    found = Findings()
    for name, artifact, intent, stamp, checksum, event in candidates:
        generated = checksum
        if validated and (generated == "" or later_than(validated, generated)):
            generated = validated
        if generated == "":
            continue  # nothing says when it was generated: the read judges the artifact
        if not later_than(intent, generated):
            continue
        checksum_words = "checksum stamped " + checksum if checksum else "its checksum unstamped"
        validator = (
            "the proposed change's artifact validator last completed " + validated
            if validated
            else "no artifact validator of the proposed change had completed"
        )
        written = intent
        if event is not None:
            own = "its latest stamp " + stamp if stamp else "no stamp of its own"
            written = f"{intent} (Infrahub's event log: {event.name} of a {event.kind}; {own})"
        found.append(refusal(
            RULE_STAGE_ARTIFACT_STALE, name,
            f"device {name}: its intent on {st.branch} was written at {written}, later than its artifact {artifact} "
            f"was generated ({checksum_words}; {validator}): {_stale_tail(st)}",
        ))
    return found


def _stale_tail(st: Resolved) -> str:
    """What a stale stage is and what to do, by the kind of stage."""
    if st.at_source == AT_HEAD:
        return f"the head of {st.ref.branch} is later than the artifacts' last regeneration; {REMEDY}"
    if st.at_source == AT_BRANCH_POINT:
        return f"stage {st.ref} reads {st.branch} as it was at the branch point, before its artifacts were regenerated"
    return f"stage {st.ref} was marked before the artifacts were regenerated; {REMEDY} and mark again"


def _resolve(reader, stamper, registry, ch: Change, ref: Ref, now: datetime | None) -> tuple[Resolved | None, Findings]:
    """Steps 4, 5, 7 and 8: the stage named, its at, the branch point, the staleness rule."""
    st, found = ch.pick(ref)
    if st is None:
        return None, found
    found = ch.check(st, now)
    if found:
        return None, found
    found = stale(reader, stamper, registry, ch, st.resolved)
    if found.rejected:
        return None, found
    return st.resolved, Findings()


def resolve_from(
    reader, stamper, registry, ch: Change, ref: Ref, now: datetime | None
) -> tuple[Resolved | None, Findings]:
    """Steps 4–9 for a proposed change already found: twin step finds its target's proposed
    change once, chooses the target, and resolves that."""
    res, found = _resolve(reader, stamper, registry, ch, ref, now)
    if found.rejected:
        return None, found
    found = Findings(found)
    found.extend(ch.main_moved(stamper))
    if found.rejected:
        return None, found
    return res, found


def resolve(reader, stamper, registry, ref: Ref, scope: str, now: datetime) -> tuple[Resolved | None, Findings]:
    """One reference to its pinned (branch, at), the reference contract's nine steps in order,
    the first refusal ending it; the warning of step 9 comes back beside a resolution. Every
    read is the default branch's or a stamps read under scope. `now` is the server's clock,
    for the future rule alone, compared and never sent."""
    ch, found = find(reader, stamper, ref.branch, scope)
    if ch is None:
        return None, found
    return resolve_from(reader, stamper, registry, ch, ref, now)


# The list.


@dataclass(frozen=True)
class RecordChange:
    """The proposed change a record's stage belongs to."""

    id: str
    branch: str


@dataclass(frozen=True)
class RecordView:
    """What the twin's record says of its stage, as the listing and the step read it: the
    orchestrator's record (R-09) once T024 writes it. `branch` and `at` are the record's
    provenance; `scope` the record's scope, or "" for one naming none, judged under the
    listing's; `state` ready or diverged; `towards` the label a diverged step was going to."""

    proposed_change: RecordChange
    label: str
    branch: str
    at: str
    at_source: str
    scope: str = ""
    state: str = "ready"
    towards: str = ""

    @property
    def ref(self) -> Ref:
        return Ref(self.proposed_change.branch, self.label)

    @property
    def derived(self) -> bool:
        return self.at_source in (AT_BRANCH_POINT, AT_HEAD)

    def names(self, st: Stage) -> bool:
        """Whether a listed stage is the one the record names: of its proposed change, of its
        label, and a mark or derived as it was."""
        return (st.resolved.proposed_change.id == self.proposed_change.id and st.label == self.label
                and (st.mark is None) == self.derived)

    def head_in_other_scope(self, id: str, scope: str) -> bool:
        """Whether the record's stage is the head of proposed change id under a scope other
        than scope: the one stage whose at a scope moves."""
        return self.proposed_change.id == id and self.at_source == AT_HEAD and self.scope not in ("", scope)

    def block(self) -> dict:
        """The record's stage as the stages block carries it ($defs/record), towards an
        explicit null unless the record is diverged."""
        towards = None
        if self.state == STATE_DIVERGED and self.towards:
            towards = {"ref": str(Ref(self.proposed_change.branch, self.towards))}
        return {
            "ref": str(self.ref),
            "proposed_change": {"id": self.proposed_change.id, "branch": self.proposed_change.branch},
            "label": self.label,
            "branch": self.branch,
            "at": self.at,
            "at_source": self.at_source,
            "state": self.state,
            "towards": towards,
        }


@dataclass(frozen=True)
class Row:
    """One listed stage, resolved by the listing's rules alone; `twin` is whether the twin
    was built from it."""

    resolved: Resolved
    twin: bool = False

    def block(self) -> dict:
        """The row ($defs/row): the resolved stage's fields, at left out when it has none."""
        b = self.resolved.block()
        if not b["at"]:
            del b["at"]
        b["twin"] = self.twin
        return b


@dataclass(frozen=True)
class Orphan:
    """A stage its proposed change no longer names (D-047): listed, warned, never planned."""

    id: str
    label: str
    at: str
    at_source: str

    def block(self) -> dict:
        return {"id": self.id, "label": self.label, "at": self.at, "at_source": self.at_source}


@dataclass
class ListResult:
    """What `stage list` reports: the rows sorted by branch then each proposed change's
    order, the orphans, and the record's stage when one is named. `branch` is the --branch
    filter, "" when every open proposed change was listed."""

    branch: str = ""
    rows: list[Row] = field(default_factory=list)
    orphans: list[Orphan] = field(default_factory=list)
    record: RecordView | None = None

    def block(self) -> dict:
        """The listing as stage list's document carries it ($defs/list)."""
        return {
            "branch": self.branch or None,
            "rows": [r.block() for r in self.rows],
            "orphans": [o.block() for o in self.orphans],
            "record": self.record.block() if self.record is not None else None,
        }


def list_stages(
    reader, stamper, branch: str, scope: str, record: RecordView | None = None
) -> tuple[ListResult, Findings]:
    """The stages of the open proposed changes, every one when branch is empty or the one
    whose source branch it is, steps 1–6 and 9 applied to each, the record's row marked.
    The kind absent is the one refusal of the whole listing. Beside the rows:
    stage.label.reserved, a rejection, per mark labelled like a derived stage; the schema.*
    findings of a branch whose schema does not conform, once per branch; and warnings:
    stage.at.unresolved or scope.empty for a stage with no at, stage.unknown for a branch
    deleted under its proposed change, stage.main.moved per proposed change,
    stage.orphaned per orphan, and stage.twin.moved (`twin_moved`). A record's head is
    judged under the record's scope, its proposed change's stamps read once more under it."""
    found = _check_kind(reader)
    if found:
        return ListResult(), found
    pcs = sorted(reader.proposed_changes(branch), key=lambda pc: (pc.branch, pc.id))
    res = ListResult(branch=branch, record=record)
    found = Findings()
    changes = []
    recorded = None
    mains: dict[str, Stamps | None] = {}
    for pc in pcs:
        if branch and pc.branch != branch:
            continue
        info = reader.branch(pc.branch)
        refused = False
        if info is None:
            ch = Change(pc, sr.BranchInfo(pc.branch), Stamps("", {}), [], scope)
            found.append(warning(refusal(RULE_STAGE_UNKNOWN, pc.branch,
                                         gone(pc.branch, pc.id) + "; until then its branch point and head have no at")))
        else:
            try:
                ch = _change(reader, stamper, pc, info, scope)
            except ConformanceError as e:
                ch = Change(pc, info, Stamps("", {}), [], scope)
                found.extend(conformance_refusal(e))
                refused = True
            else:
                if record is not None and record.head_in_other_scope(pc.id, scope):
                    recorded = _change(reader, stamper, pc, info, record.scope)
        changes.append(ch)
        for st in ch.stages:
            res.rows.append(Row(st.resolved, record is not None and record.names(st)))
            if st.mark is not None and reserved(st.label):
                found.append(ch.reserved_refusal(st.ref))
            if not st.at and info is not None and not refused:
                found.extend(warning(f) for f in ch.check(st, None))
        if info is None:
            continue
        ch._main = mains.get(ch.proposed_change.destination)
        moved = ch.main_moved(stamper)
        mains[ch.proposed_change.destination] = ch._main
        found.extend(_unfiled(moved, found))

    for o in reader.orphans():
        at, source = (o.at, AT_GIVEN) if o.at is not None else (o.label_written_at, AT_WRITTEN)
        res.orphans.append(Orphan(o.id, o.label, at, source))
        found.add(WARNING, RULE_STAGE_ORPHANED, o.id,
                  f"stage {quote(o.label)} (id {o.id}) names no proposed change: it was removed from its proposed "
                  "change's fylgja_stages; delete the stage")

    # The orchestrator's record carries no at's source (R-09): a derived stage's follows from
    # its label, and a mark's is the mark's as listed, unknown for a mark since deleted.
    if record is not None and not record.at_source and not record.derived:
        for c in changes:
            st = c.first(record.label) if c.proposed_change.id == record.proposed_change.id else None
            if st is not None:
                record = replace(record, at_source=st.at_source)
                res.record = record

    # A listing of another branch says nothing of the record's: its row is not shown.
    if record is not None and (not branch or branch == record.proposed_change.branch):
        ch = None
        for c in changes:
            if c.proposed_change.id == record.proposed_change.id:
                ch = c
        if recorded is not None:
            ch = recorded
        found.extend(twin_moved(ch, record))
    return res, found


def twin_moved(ch: Change | None, rec: RecordView) -> Findings:
    """stage.twin.moved when the record's stage is gone, its proposed change no longer open,
    or no longer resolves to the branch and at the record holds; nothing when it still does.
    `ch` is the proposed change read as the record's, None when no open one was read on its
    source branch. It applies only when `ch` is the record's own proposed change (019): a
    target found in another is a step out of it, and nothing is said."""
    ref = rec.ref
    built = f"the twin was built from stage {ref} at branch {rec.branch}, at {rec.at} ({rec.at_source})"

    def warn(what: str) -> Findings:
        return Findings([Finding(WARNING, RULE_STAGE_TWIN_MOVED, str(ref),
                                 f"{built}; {what}; the twin is pinned to what it was built from")])

    if ch is None:
        return warn(f"proposed change {rec.proposed_change.id} is no longer open, so {ref} is gone")
    if ch.proposed_change.id != rec.proposed_change.id:
        return Findings()
    now = [st for st in ch.stages if rec.names(st)]
    if any(st.branch == rec.branch and st.at == rec.at for st in now):
        return Findings()
    if not now:
        return warn(f"{ref} no longer exists")
    if not now[0].at:
        return warn(f"{ref} now names no point in time")
    return warn(f"{ref} now resolves to branch {now[0].branch}, at {now[0].at} ({now[0].at_source})")


# The step's target.


def target(
    ch: Change, view: RecordView | None, record_branch: str, record_at: str, given: Ref | None
) -> tuple[Ref | None, list[str] | None, Findings]:
    """The stage a twin steps to (FR-018; 019 research R-07): the one given, or else the next
    stage after the record's in its proposed change's order, found by its label. `ch` is the
    open proposed change found on the given reference's branch, or on the record's stage's
    when none is given; `view` the record's stage, None for a record naming none;
    `record_branch` and `record_at` the record's provenance. Its rules, in order, each a
    rejection at resolve, the first ending it:

    1. with none given, a record naming no stage is step.target.unknown;
    2. with none given, the branch's open proposed change not the record's (closed, another
       opened) is step.target.unknown;
    3. with none given, the stage after the record's, or step.target.unknown when the
       record's label is gone or nothing follows it, saying when the head has moved since;
    4. a given label the proposed change lacks is step.target.unknown, naming its stages;
    5. the target resolving to the record's own (branch, at) is step.target.current;
    6. within the record's proposed change, every mark strictly between the record's place
       and the target's, either direction, is skipped, warned step.stage.skipped.

    The chosen reference is then the resolution's, under its own refusals. Reads nothing."""
    pc = ch.proposed_change
    labels = ch.labels()
    stages = ", ".join(labels)
    same = view is not None and pc.id == view.proposed_change.id

    current = -1
    chosen = Ref(pc.branch, "")
    if given is not None:
        if given.label not in labels:
            return None, None, Findings([refusal(RULE_STEP_TARGET_UNKNOWN, str(given),
                                                 f"proposed change {pc.id} on {pc.branch} has no stage "
                                                 f"{quote(given.label)}; its stages are: {stages}")])
        chosen = given
        if same:
            current = labels.index(view.label) if view.label in labels else -1
    elif view is None:
        return None, None, Findings([refusal(RULE_STEP_TARGET_UNKNOWN, record_branch, NO_TARGET_MESSAGE)])
    elif not same:
        b = view.proposed_change.branch
        return None, None, Findings([refusal(
            RULE_STEP_TARGET_UNKNOWN, str(view.ref),
            f"proposed change {view.proposed_change.id} on branch {b}, the twin's, is no longer open "
            f"(the open proposed change on {b} is {pc.id}), so the twin has no next stage; "
            "give --stage <branch>/<label> or --snapshot <id|file>",
        )])
    else:
        current = labels.index(view.label) if view.label in labels else -1
        if current < 0:
            return None, None, Findings([refusal(
                RULE_STEP_TARGET_UNKNOWN, str(view.ref),
                f"the twin's stage {view.ref} is no longer a stage of proposed change {pc.id} on branch {pc.branch}; "
                f"its stages are: {stages}",
            )])
        if current == len(labels) - 1:
            message = f"proposed change {pc.id} on {pc.branch} has no stage after {view.ref}; its stages are: {stages}"
            head = ch.first(LABEL_HEAD)
            if head is not None and view.at_source == AT_HEAD and head.at and head.at != view.at:
                message += (f"; the head has moved since the twin was built (now at {head.at}): --stage {head.ref} "
                            "steps to it")
            return None, None, Findings([refusal(RULE_STEP_TARGET_UNKNOWN, str(view.ref), message)])
        chosen = Ref(pc.branch, labels[current + 1])
    # The next stage is held to it as a given one is: a mark sharing the record's at is the
    # twin's own reference under another label.
    st = ch.first(chosen.label)
    if st is not None and st.at and st.branch == record_branch and st.at == record_at:
        return None, None, Findings([refusal(
            RULE_STEP_TARGET_CURRENT, str(chosen),
            f"the twin is already at stage {chosen} (branch {st.branch}, at {st.at}); the proposed change's stages "
            f"are: {stages}",
        )])
    if current < 0:
        return chosen, None, Findings()
    to = labels.index(chosen.label)
    lo, hi = min(current, to), max(current, to)
    skipped = labels[lo + 1 : max(lo + 1, hi)]
    if not skipped:
        return chosen, None, Findings()
    noun = "stage" if len(skipped) == 1 else "stages"
    return chosen, skipped, Findings([Finding(
        WARNING, RULE_STEP_STAGE_SKIPPED, str(chosen),
        f"the step from {view.ref} to {chosen} skips {noun} {', '.join(skipped)}; the step is between the two "
        "bundles either way",
        STEP_RESOLVE,
    )])


# Infrahub's side.


class Stamper:
    """A branch's stamps at an `at`, unpinned when it is empty, under a scope, tag:<name>
    (017): an intent client per (branch, at), whose stamps say when the intent and the
    artifacts were written and never a value of intent. A branch's conformance is checked the
    first time it is asked for and remembered: one that does not conform raises
    ConformanceError, its schema.* findings; one that cannot be read raises ReadError."""

    def __init__(self, address: str, token: str, requester=None):
        self.address = address
        self.token = token
        self.requester = requester
        self._conformed: dict[str, ConformanceError | None] = {}

    def stamps(self, branch: str, at: str, scope: str) -> Stamps:
        client = Client(Config(address=self.address, token=self.token, branch=branch, at=at), self.requester)
        if branch not in self._conformed:
            try:
                _, found = check_conformance(client)
            except ClientError as e:
                raise reading.ReadError(str(e), e.branch_missing) from None
            self._conformed[branch] = ConformanceError(branch, found) if found.rejected else None
        refused = self._conformed[branch]
        if refused is not None:
            raise refused
        return read_stamps(client, reading.scope_tag(scope))


def stamper_of(default) -> Stamper:
    """A stamper of the Infrahub a DefaultClient reads."""
    return Stamper(default.config.address, default.config.token, default._requester)


def read_stage(
    default, ref: Ref, scope: str, registry, probes=None, now: datetime | None = None, observed_at: str | None = None,
    out=None,
) -> tuple[Resolved | None, dict | None, Findings]:
    """A stage resolved, then its branch read at its at under scope and taken as a snapshot
    `2` with the request's one probe list (`internal/server/resolve.go`'s `resolveStage`
    then `internal/stage`'s read and take): the resolved stage, the snapshot (None when the
    read refused) and the findings, the resolution's warnings first. A refused resolution
    returns no stage and reads nothing; intent.at.precision there keeps the core's exit 2,
    the document's to say. `default` is a DefaultClient."""
    reader = sr.StageReader(default)
    res, found = resolve(reader, stamper_of(default), registry, ref, scope, now or datetime.now(UTC))
    if res is None:
        return None, None, found
    client = Client(
        Config(address=default.config.address, token=default.config.token, branch=res.branch, at=res.at),
        default._requester,
    )
    taken, read_found = reading.read_snapshot(client, scope, registry, probes, observed_at, out)
    found = Findings(found)
    found.extend(read_found)
    return res, taken, found
