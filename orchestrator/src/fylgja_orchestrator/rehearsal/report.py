"""The report a rehearsal posts to its change source (D-087), rendered from its rehearsal 1 document and nothing else.

Its headline, the verdict as a heading and the cause as a first sentence, in two lines of plain text, is what the
library's caller says of the rehearsal and the summary's first lines. The summary is what a reviewer reads first: the
headline, a table of a row a stage saying what changed in words, each failure with its message, the room when the
runtime had none, what the twin does not model and what was already failing before the change in plain words, a wait
only where it expired, when the stages were read, and that fidelity is asserted, not measured (Constitution X). The
detail holds the rest: the twin and the run, then what the summary's lists point to, every finding whole and every
interface left out, and last the stages with their ids and the core's runs. Each part is within the bytes a source's
comment takes, losing first what matters least, cut at a line and never inside a character; the detail is cut first,
so a list the summary cuts says that the detail holds what it left out only where the detail does.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from dataclasses import dataclass, field
from itertools import accumulate
from typing import Any

from fylgja_orchestrator.rehearsal import rules


@dataclass(frozen=True)
class Report:
    """A rehearsal's report: its status, its heading and first sentence as plain text, and its two parts in
    Markdown, each within the bytes the source's `comment_limit` gives one part."""

    status: str
    headline: str
    summary: str
    detail: str


# Why a change was not rehearsed, by its cause, in the catalogue's order.
WHY: dict[str, str] = {
    rules.STAGES_NONE: "no stage to build",
    rules.CAPACITY: "the runtime has no room",
    rules.IMAGE_ABSENT: "an image is absent",
    rules.ADMISSION_REFUSED: "the runtime refused the twin",
    rules.CORE_UNREACHABLE: "the core could not be used",
    rules.CORE_REFUSED: "the core refused the request",
    rules.SOURCE_FAILED: "the source could not be read",
    rules.TWIN_HELD: "an earlier twin is still there",
}
# The characters a label keeps in the heading and the table, the last of them `…` where it is cut.
LABEL = 60
# The characters of a blueprint's or a bundle's id the detail gives.
ID = 12
# A stage's result in the table, by what it came to on the twin; and, for one the rehearsal did not reach, by what
# the plan made of it.
RESULT = {
    "created": "created",
    "passed": "passed",
    "failed": "**failed**",
    "skipped": "unchanged",
    "empty": "no devices",
    "not_reached": "not reached",
}
UNREACHED = {"built": "not reached", "empty": "no devices", "refused": "**failed**", "not_read": "not reached"}
# Why the twin leaves an interface out, in words, by the build's omission.
OMITTED = {
    "out_of_range": "the twin's node has no such port, so it is left out",
    "no_rule": "the twin's node has no such port, so it is left out",
    "extra_management": "the twin's node has one management port, so it is left out",
    "shared": "its port on the twin is taken by a cabled interface, so it is left out",
}
VERIFIED = "Every stage was built on the twin and verified."
ALREADY = "Every stage was built on the twin, and verify found nothing the baseline did not already have."
FIDELITY = "Fidelity is asserted, not measured."
HEADER = ("| # | stage | what changed | result | checks |", "|---|---|---|---|---|")
ELLIPSIS = "…"

# A stage as the plan made it and as it came to on the twin.
type _Stage = tuple[Mapping[str, Any], Mapping[str, Any]]


def headline(document: Mapping[str, Any]) -> str:
    """The verdict and its cause, two lines of plain text: the heading, and the first sentence. It is what the
    library's caller says of the rehearsal and the report's first lines, and the rehearsal stores it as its
    document's `headline`."""
    return f"{_heading(document)}\n{_sentence(document)}"


def render(document: Mapping[str, Any], *, limit: int | None) -> Report:
    """The report of the rehearsal `document`: its summary and its detail, each within `limit` bytes of UTF-8, or
    whole where `limit` is None. The detail is cut first, for the summary to say what it holds."""
    detail = _cut(_detail(document), limit)
    return Report(
        status=document["status"],
        headline=document["headline"],
        summary=_fitted(_summary(document, detail), limit),
        detail=detail,
    )


def _stages(document: Mapping[str, Any]) -> list[_Stage]:
    """Each stage of the change, as the plan made it and as it came to on the twin; none where the plan is null."""
    planned = document["plan"]
    if planned is None:
        return []
    ran = document["stages"]
    return [(stage, ran[i] if i < len(ran) else {}) for i, stage in enumerate(planned["stages"])]


def _cause(document: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """The document's first error finding, which fixes its status; None where it passed."""
    return next((f for f in document["findings"] if f["severity"] == "error"), None)


def _named(document: Mapping[str, Any], stages: Sequence[_Stage]) -> int | None:
    """The stage the heading names, by its number: where the change failed, the stage that failed or that the plan
    refused; where the rehearsal stopped, the stage in progress, the first built one not reached, and none where it
    stopped while its stages were read, its plan unfinished."""
    status = document["status"]
    if status == "stopped" and (document["plan"] or {}).get("status") == "unfinished":
        return None
    for k, (planned, ran) in enumerate(stages, 1):
        result = ran.get("result", "not_reached")
        unreached = result == "not_reached"
        if status == "failed" and (result == "failed" or (unreached and planned["outcome"] == "refused")):
            return k
        if status == "stopped" and unreached and planned["outcome"] == "built":
            return k
    return None


def _heading(document: Mapping[str, Any]) -> str:
    """The verdict: passed, failed or stopped at which stage of how many, or not rehearsed and why."""
    status = document["status"]
    stages = _stages(document)
    n = len(stages)
    if status == "passed":
        return f"Rehearsal passed: {n} stage{'' if n == 1 else 's'}"
    if status == "not_rehearsed":
        cause = _cause(document)
        why = WHY.get(cause["rule"]) if cause is not None else None
        return f"Not rehearsed: {why}" if why else "Not rehearsed"
    verdict = "Rehearsal failed" if status == "failed" else "Rehearsal stopped"
    k = _named(document, stages)
    return f"{verdict} at stage {k} of {n}: {_label(stages[k - 1][0]['label'])}" if k else verdict


def _sentence(document: Mapping[str, Any]) -> str:
    """The cause's message, or what a passed rehearsal verified; where the change failed on a twin it created, the
    stages that passed and those not reached; and, on any status, that the twin may be left."""
    cause = _cause(document)
    steps = [f["message"] for f in document["findings"] if f["rule"] == rules.STEPS_NONE]
    if cause is not None:
        said = [cause["message"], *_reached(document)]
    elif steps:
        said = steps[:1]
    else:
        said = [ALREADY if document["already_failing"] else VERIFIED]
    said += [f["message"] for f in document["findings"] if f["rule"] == rules.TWIN_LEFT]
    return " ".join(said)


def _reached(document: Mapping[str, Any]) -> list[str]:
    """Where the change failed after its twin was created: the stages that passed before it, and those after it,
    not reached."""
    stages = _stages(document)
    k = _named(document, stages)
    if document["status"] != "failed" or k is None or not any(r.get("result") == "created" for _, r in stages):
        return []
    went = [j for j, (_, ran) in enumerate(stages, 1) if ran.get("result") in ("created", "passed", "skipped")]
    after = list(range(k + 1, len(stages) + 1))
    said = [f"{_numbered(went, 'Stage')} passed."] if went else []
    if after:
        said.append(f"{_numbered(after, 'Stage')} {'was' if len(after) == 1 else 'were'} not reached.")
    return said


def _numbered(ks: Sequence[int], word: str = "stage") -> str:
    """`stage 2`, `stages 2 and 3`, `stages 2 to 4`, `stages 2 to 4 and 6`: three or more in a row as a range."""
    runs: list[list[int]] = []
    for k in ks:
        if runs and k == runs[-1][-1] + 1:
            runs[-1].append(k)
        else:
            runs.append([k])
    numbers: list[str] = []
    for run in runs:
        numbers += [f"{run[0]} to {run[-1]}"] if len(run) > 2 else [str(k) for k in run]
    listed = numbers[0] if len(numbers) == 1 else f"{', '.join(numbers[:-1])} and {numbers[-1]}"
    return f"{word}{'' if len(ks) == 1 else 's'} {listed}"


def _label(label: str) -> str:
    """A label cut to `LABEL` characters, the last of them `…` where it is longer."""
    return label if len(label) <= LABEL else label[: LABEL - 1] + ELLIPSIS


def _took(seconds: float) -> str:
    """A time taken: `<s>s`, `<m>m <s>s` or `<h>h <m>m`."""
    s = round(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m {s % 60}s"
    return f"{s // 3600}h {s % 3600 // 60}m"


def _size(text: str) -> int:
    """The bytes of `text` in UTF-8, as a source bounds a comment."""
    return len(text.encode())


# The summary.


# A line of one of the summary's lists, and the lines of the detail that hold it whole.
type _Item = tuple[str, list[str]]


@dataclass
class _List:
    """One list of the summary: its title, its items, and how many of them are left out at its end. One that
    `says_none` says so when it has no item; another is then left out, as is one `gone`."""

    title: str
    items: list[_Item]
    says_none: bool = False
    left: int = 0
    gone: bool = False

    def lines(self, detail: Set[str]) -> list[str]:
        """The list as it stands, its last line, where items are left out, saying how many, and that `detail`, the
        lines of the detail as it is posted, holds them where it holds each whole."""
        if self.gone or not (self.items or self.says_none):
            return []
        if not self.items:
            return [f"**{self.title}:** none"]
        kept = len(self.items) - self.left
        held = all(line in detail for _, lines in self.items[kept:] for line in lines)
        more = [f"- and {self.left} more{', in the detail' if held else ''}"] if self.left else []
        return [f"**{self.title}**", *(line for line, _ in self.items[:kept]), *more]


@dataclass
class _Table:
    """The summary's table: a row a stage, those of `kept` never left out, and each run of rows left out giving way
    to one row that says how many."""

    rows: list[str]
    kept: set[int]
    left: set[int] = field(default_factory=set)

    def lines(self, least: bool = False) -> list[str]:
        """The table as it stands; or, `least`, with every row left out that may be."""
        out = list(HEADER)
        gap = 0
        for i, row in enumerate(self.rows):
            if i in self.left or (least and i not in self.kept):
                gap += 1
                continue
            if gap:
                out.append(_cells("…", f"{gap} more stage{'' if gap == 1 else 's'}", "", "", ""))
                gap = 0
            out.append(row)
        return out


@dataclass
class _Summary:
    """The summary's parts, in its order, what of them is left out, and `detail`, the lines of the detail as it is
    posted."""

    heading: str
    sentence: str
    table: _Table | None
    lists: list[_List]
    waits: list[str]
    last: list[str]
    detail: Set[str]
    waits_gone: bool = False

    def text(self, least: bool = False) -> str:
        """The summary as it stands; or, `least`, with everything left out that may be: what is left is its heading,
        its first sentence, the table's header, its first row, the row of the stage the heading names, its last row,
        and its last two lines."""
        parts = [[self.heading], [self.sentence], self.table.lines(least) if self.table else []]
        if not least:
            parts += [listed.lines(self.detail) for listed in self.lists]
            parts.append([] if self.waits_gone else self.waits)
        parts.append(self.last)
        return "\n\n".join("\n".join(part) for part in parts if any(part))


def _summary(document: Mapping[str, Any], detail: str) -> _Summary:
    """The summary of `document` whole, beside `detail`, its detail as it is posted: its headline, the table, the
    lists, an expired wait's line each, and the two lines that end it."""
    heading, _, sentence = document["headline"].partition("\n")
    stages = _stages(document)
    rows = [_row(k, planned, ran) for k, (planned, ran) in enumerate(stages, 1)]
    named = _named(document, stages)
    table = _Table(rows, {0, len(rows) - 1, *([named - 1] if named else [])}) if rows else None
    baseline = _baseline(stages)
    lists = [
        _List("What failed", _failed(document, stages)),
        _List("The room when it was refused", [(f"- {line}", [f"- {line}"]) for line in document.get("room", [])]),
        _List("Not modelled on the twin", _unmodelled(stages), says_none=True),
        _List("Already failing before this change",
              [(_failure(f), [_whole(f, baseline)]) for f in document["already_failing"]], says_none=True),
    ]
    waits = [f"Verify did not hold within {ran['wait']['budget_s']} s at stage {k}."
             for k, (_, ran) in enumerate(stages, 1) if "wait" in ran]
    return _Summary(f"## {heading}", sentence, table, lists, waits, [_where(document), FIDELITY],
                    frozenset(detail.split("\n")))


def _row(k: int, planned: Mapping[str, Any], ran: Mapping[str, Any]) -> str:
    """Stage `k`'s row: its number, its label, what changed, its result and its checks."""
    result = ran.get("result", "not_reached")
    shown = UNREACHED[planned["outcome"]] if result == "not_reached" else RESULT[result]
    counts = ran.get("counts")
    if counts:
        checks = f"{counts['held']} hold" + (f", {counts['failed']} fail" if counts["failed"] else "")
    elif shown == RESULT["failed"]:
        checks = "not run"
    elif result == "skipped":
        checks = "not run again"
    else:
        checks = ""
    return _cells(str(k), _label(planned["label"]), planned.get("changed", ""), shown, checks)


def _cells(*cells: str) -> str:
    """A row of the table: a cell with nothing in it a single space, and a `|` or a line break in a cell made safe."""
    said = [f" {cell.replace('|', '\\|').replace('\n', ' ')} " if cell else " " for cell in cells]
    return f"|{'|'.join(said)}|"


def _failed(document: Mapping[str, Any], stages: Sequence[_Stage]) -> list[_Item]:
    """What failed: the failures of the stage that failed, the errors of a stage the plan refused, and, where the
    change failed, the rehearsal's own errors. Not rehearsed or stopped, nothing of the change failed: the first
    sentence says the cause, and the detail gives it whole. An empty stage's read keeps its findings, which fail
    nothing."""
    found: list[Mapping[str, Any]] = []
    items: list[_Item] = []
    for k, (planned, ran) in enumerate(stages, 1):
        refused = planned.get("findings", []) if planned["outcome"] == "refused" else []
        for f in [*(f for f in refused if f["severity"] == "error"), *ran.get("failures", [])]:
            if f not in found:
                found.append(f)
                items.append((_failure(f), [_whole(f, k)]))
    own = [f for f in document["findings"] if f["severity"] == "error"] if document["status"] == "failed" else []
    return items + [(_failure(f), [_whole(f)]) for f in own]


def _failure(f: Mapping[str, Any]) -> str:
    """A failure as the summary lists it: ``- `<rule>` <object>: <message>``, the message whole."""
    about = f" {f['object']}" if f.get("object") else ""
    return f"- `{f['rule']}`{about}: {f['message']}"


def _unmodelled(stages: Sequence[_Stage]) -> list[_Item]:
    """What the twin does not model, in words: each interface it leaves out, then each finding of a stage's read or
    build that is no error, a line said once with the stages it is said of."""
    omitted: dict[str, tuple[list[int], list[str]]] = {}
    found: dict[str, tuple[list[int], list[str]]] = {}
    for k, (planned, _) in enumerate(stages, 1):
        for o in planned.get("omitted", []):
            _said_at(omitted, f"- {o['device']} `{o['interface']}`: {OMITTED[o['omission']]}", k, _omission(k, o))
        for f in planned.get("findings", []):
            if f["severity"] != "error":
                message = f["message"].removesuffix(".")
                line = f"- {f['object']}: {message}" if f.get("object") else f"- {message}"
                _said_at(found, line, k, _whole(f, k))
    return [(f"{line} ({_numbered(ks)}).", held) for line, (ks, held) in [*omitted.items(), *found.items()]]


def _said_at(said: dict[str, tuple[list[int], list[str]]], line: str, k: int, held: str) -> None:
    """`line` said of stage `k`, once, and `held`, the detail's line that holds it there."""
    ks, lines = said.setdefault(line, ([], []))
    if k not in ks:
        ks.append(k)
    if held not in lines:
        lines.append(held)


def _where(document: Mapping[str, Any]) -> str:
    """The change, its scope, when the rehearsal read its stages, and how long it took. A stage a source took earlier
    is as it was then, its time in its pin's words, which the detail's line of it gives."""
    took = _took(document["took_s"])
    planned = document["plan"]
    if planned is None:
        return f"The stages were not read. Took {took}."
    return (f"{planned['change']['where']}, scope `{planned['scope']}`. The rehearsal read its stages at "
            f"{planned['read_at']}; one taken earlier is as it was then, at the time its line in the detail gives; "
            f"later edits are not rehearsed. Took {took}.")


def _fitted(summary: _Summary, limit: int | None) -> str:
    """The summary within `limit` bytes. Whatever else goes it keeps its heading, its first sentence, cut to what
    fits beside the rest of what it keeps, the table's header, its first row, the row of the stage the heading names,
    its last row, and its last two lines. While it is over, the lists lose lines from their ends, "Not modelled"
    first, then "Already failing", "The room" and "What failed"; then the table's other rows give way, from its end;
    then the waits' lines go, and the lists whole, in that order."""
    text = summary.text()
    if limit is None or _size(text) <= limit:
        return text
    spare = limit - _size(summary.text(least=True)) + _size(summary.sentence)
    if _size(summary.sentence) > spare:
        summary.sentence = _shortened(summary.sentence, spare)
    cuts = [summary.lists[i] for i in (2, 3, 1, 0)]

    def over() -> bool:
        return _size(summary.text()) > limit

    for listed in cuts:
        while over() and listed.left < len(listed.items):
            listed.left += 1
    if summary.table is not None:
        for i in reversed(range(len(summary.table.rows))):
            if not over():
                break
            if i not in summary.table.kept:
                summary.table.left.add(i)
    summary.waits_gone = over()
    for listed in cuts:
        listed.gone = over()
    text = summary.text()
    return text if _size(text) <= limit else _clipped(text, limit)


def _shortened(text: str, room: int) -> str:
    """`text` cut to at most `room` bytes at a character, its last `…`; nothing where not even that fits."""
    if room < _size(ELLIPSIS):
        return ""
    return text.encode()[: room - _size(ELLIPSIS)].decode(errors="ignore").rstrip() + ELLIPSIS


def _clipped(text: str, limit: int) -> str:
    """The whole lines of `text` from its start that fit within `limit` bytes, the first cut at a character where
    not even it fits: for a limit below what a part always keeps."""
    kept: list[str] = []
    for line in text.split("\n"):
        if _size("\n".join([*kept, line])) > limit:
            break
        kept.append(line)
    return "\n".join(kept) if kept else text.encode()[:limit].decode(errors="ignore")


# The detail.


def _detail(document: Mapping[str, Any]) -> str:
    """The detail of `document` whole, what the summary's lists point to first, since it loses lines from its end:
    the twin, the run and the change, and the twins reclaimed; every finding whole; each interface the twin leaves
    out; the room; each package's approximation once; each warning's message; and last each stage with its pin in
    words, its ids, the core's run, its time, its checks and an expired wait."""
    planned = document["plan"]
    stages = _stages(document)
    change = f", change `{planned['change']['id']}`" if planned is not None else ""
    head = [f"**Rehearsal detail**: twin `{document['twin']}`, run `{document['run_id']}`{change}."]
    if document["reclaimed"]:
        head.append(f"Reclaimed: {', '.join(f'`{twin}`' for twin in document['reclaimed'])}.")
    approximations: list[str] = []
    for stage, _ in stages:
        for a in stage.get("approximations", []):
            line = f"- `{a['package']}`: {a['text']}"
            if line not in approximations:
                approximations.append(line)
    omitted = [_omission(k, o) for k, (stage, _) in enumerate(stages, 1) for o in stage.get("omitted", [])]
    parts = [
        head,
        _titled("Every finding", _findings(document, stages)),
        _titled("Not modelled on the twin", omitted),
        _titled("The room when it was refused", [f"- {line}" for line in document.get("room", [])]),
        _titled("Approximations", approximations),
        _titled("Notes", [f"- {f['message']}" for f in document["findings"] if f["severity"] != "error"]),
        _titled("Stages", [_stage(k, stage, ran) for k, (stage, ran) in enumerate(stages, 1)]),
    ]
    return "\n\n".join("\n".join(part) for part in parts if part)


def _titled(title: str, lines: Sequence[str]) -> list[str]:
    """A part of the detail: its title over its lines, or nothing where it has none."""
    return [f"**{title}**", *lines] if lines else []


def _stage(k: int, planned: Mapping[str, Any], ran: Mapping[str, Any]) -> str:
    """Stage `k`'s line: its label, its pin in words, its ids, the core's run and its time, its checks, and its
    wait where it expired."""
    said = [planned["where"]]
    ids = [f"{name} `{planned[key][:ID]}`" for key, name in (("blueprint_id", "blueprint"), ("bundle_id", "bundle"))
           if key in planned]
    runs = [f"run `{ran['run_id']}`"] if "run_id" in ran else []
    if "took_s" in ran:
        runs.append(_took(ran["took_s"]))
    said += [", ".join(group) for group in (ids, runs) if group]
    if "counts" in ran:
        counts = ran["counts"]
        more = [f", {counts[key]} {word}" for key, word in (("failed", "fail"), ("skipped", "skipped")) if counts[key]]
        said.append(f"{counts['held']} hold{''.join(more)}")
    if "wait" in ran:
        wait = ran["wait"]
        said.append(f"verify's wait expired after {round(wait['after_s'], 1):g} s of {wait['budget_s']}")
    return f"{k}. {planned['label']}: {'; '.join(said)}"


def _findings(document: Mapping[str, Any], stages: Sequence[_Stage]) -> list[str]:
    """Every finding whole: the rehearsal's own errors, then each stage's read and build findings and its failures,
    the baseline's with what was already failing there."""
    lines = [_whole(f) for f in document["findings"] if f["severity"] == "error"]
    baseline = _baseline(stages)
    for k, (planned, ran) in enumerate(stages, 1):
        found: list[Mapping[str, Any]] = []
        failing = document["already_failing"] if k == baseline else []
        for f in [*planned.get("findings", []), *ran.get("failures", []), *failing]:
            if f not in found:
                found.append(f)
        lines += [_whole(f, k) for f in found]
    if baseline is None:
        lines += [_whole(f) for f in document["already_failing"]]
    return lines


def _whole(f: Mapping[str, Any], k: int | None = None) -> str:
    """A finding as the detail gives it, whole: ``- stage <k> `<rule>` <severity> <object>: <message>``, the stage
    left out of one that is no stage's."""
    at = f"stage {k} " if k is not None else ""
    about = f" {f['object']}" if f.get("object") else ""
    return f"- {at}`{f['rule']}` {f['severity']}{about}: {f['message']}"


def _omission(k: int, o: Mapping[str, Any]) -> str:
    """An interface the twin of stage `k` leaves out, as the detail gives it, with the build's omission."""
    return f"- stage {k} {o['device']} `{o['interface']}`: `{o['omission']}`"


def _baseline(stages: Sequence[_Stage]) -> int | None:
    """The stage the twin was created at, by its number; None where it was created at none."""
    return next((k for k, (_, ran) in enumerate(stages, 1) if ran.get("result") == "created"), None)


def _cut(text: str, limit: int | None) -> str:
    """The detail within `limit` bytes: whole lines lost from its end, and then a last line saying how many."""
    if limit is None or _size(text) <= limit:
        return text
    lines = text.split("\n")
    # The bytes of the lines before each, each with its line break.
    before = list(accumulate((_size(line) + 1 for line in lines), initial=0))
    dropped = 0
    for kept in range(len(lines) - 1, 0, -1):
        dropped += bool(lines[kept])
        end = kept
        while end > 1 and not lines[end - 1]:
            end -= 1
        said = f"… cut here: {dropped} more lines did not fit."
        if before[end] - 1 + len("\n\n") + _size(said) <= limit:
            return "\n".join(lines[:end]) + "\n\n" + said
    return _clipped(f"… cut here: {sum(1 for line in lines if line)} more lines did not fit.", limit)
