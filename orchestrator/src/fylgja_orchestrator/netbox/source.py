"""The NetBox change source (D-085, D-097): a branch found by its name, its stages `main`, its marks in the order
written and its head, `main` and the head read through the reader (D-095), a mark's blueprint read back from the core,
and the report filed as one journal entry on the branch.

A change is the branch whose name is exactly the reference a trigger names: none is `NoChange`, and one that is not
`ready` is `Unready`, its status named. Its id is the branch's `schema_id`, so a branch made anew under an old name,
or another NetBox's, shares no twin's name with it. NetBox reads no branch as it stood earlier, so a step is read when
it exists: `mark` reads the branch, gives the blueprint to the core, and then writes a journal entry on the branch
naming the label, the blueprint's id, the scope and the time read (`mark_text`), so that no mark names a blueprint
the core was never given. A mark is read back from its entry (`marks_of`) and its blueprint from the core by its id:
one malformed, one of a label two entries share, one read under another scope, each refuses its stage by a finding
of the source's with nothing asked of the core; one whose blueprint the core does not hold, by `mark.unheld`. An
entry whose first line does not begin `MARK_PREFIX`, a report among them, is no mark.

`main` and the head are read as they stand, through `fylgja_netbox.read`, its `Result` handed on as a `Read` member
for member, and read again where the reader refuses one with `read.moved`, `MOVED_READS` reads in all, none waited
between. `main`'s read gains the warning `stage.main.gained` where `main`'s changelog holds rows later than the
branch's `last_sync`, or its `created` where that is null, of any kind but the four of `UNCOUNTED`, which no read
reads: the first stage is `main` as it stands, so the first step may undo them on the twin.
The reader's `NetBoxError` of a refused token, 401 or 403, is raised as the source's own `SourceError`, in the
sentence its own transport gives by the status, never the reader's words; any other `NetBoxError`, a `ProblemError`
of the core's but a blueprint not found, a `TransportError` and a `SourceError` are raised on.

`claim` takes the tag `TAG` off the branch, which asked for the rehearsal, by one `PATCH` of its other tags, and
sends nothing where the tag is not on it. `post` writes the report as one journal entry, its kind the verdict
(`KIND`), the summary and the detail with an empty line before each list, which NetBox renders only so (`spaced`).
The source keeps no store: the marks are NetBox's and the blueprints the core's. Its own requests go through its
transport (transport.py), each on `main`; the reader's through a connection of the reader's, made at the first read
that needs it and kept.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from fylgja_core.blueprint import blueprint_id
from fylgja_core.client import Client, ProblemError
from fylgja_core.findings import Finding, order
from fylgja_netbox import NetBox, NetBoxError, ReaderDocument, Result, connect, read
from fylgja_netbox.bracket import RULE_MOVED as MOVED
from fylgja_netbox.bracket import UNREAD

from fylgja_orchestrator.netbox.transport import REFUSED, SourceError, Transport, Wire, refused_token
from fylgja_orchestrator.rehearsal.report import Report
from fylgja_orchestrator.rehearsal.source import Change, Read, Stage

# Rule ids. The catalogue is orchestrator/rules.md, "Findings: the NetBox change source".
RULE_MARK_MALFORMED = "mark.malformed"
RULE_MARK_DUPLICATE = "mark.duplicate"
RULE_MARK_UNHELD = "mark.unheld"
RULE_MARK_SCOPE = "mark.scope"
RULE_MAIN_GAINED = "stage.main.gained"

SEVERITY: dict[str, Literal["error", "warning", "info"]] = {
    RULE_MARK_MALFORMED: "error",
    RULE_MARK_DUPLICATE: "error",
    RULE_MARK_UNHELD: "error",
    RULE_MARK_SCOPE: "error",
    RULE_MAIN_GAINED: "warning",
}
"""The severity each of the source's rules is filed at."""

MAIN = "main"
"""The label of the first stage: `main` as it stands."""

HEAD = "head"
"""The label of the last stage: the branch as it stands."""

TAG = "fylgja-rehearse"
"""The name and slug of the tag that asks for the rehearsal of the branch it is set on."""

MARK_PREFIX = "Fylgja stage: "
"""How a mark's entry begins: its first line is this, then its label."""

MOVED_READS = 3
"""How many times `main` or the head is read, in all, while the reader refuses it with `read.moved`; none is waited
between, since the reader reads again from the start."""

READY = "ready"
"""The status of a branch that can be rehearsed."""

LABEL = re.compile(r"[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?")
"""What a mark's label is: one to forty lowercase letters, digits and hyphens, beginning and ending with a letter or a
digit."""

KIND = {"passed": "success", "failed": "danger", "not_rehearsed": "warning", "stopped": "warning"}
"""The kind of the report's journal entry, by the rehearsal's status; any other status `warning`."""

BRANCHES = "plugins/branching/branches/"
ENTRIES = "extras/journal-entries/"
CHANGES = "core/object-changes/"
TYPES = "core/object-types/"
BRANCH_TYPE = "netbox_branching.branch"
"""The object type of a branch, as a journal entry is assigned to it."""

UNCOUNTED = (*UNREAD, "extras.webhook", "extras.eventrule")
"""The kinds of `main`'s changelog rows `stage.main.gained` counts nothing of: the two whose rows refuse no read
(`fylgja_netbox.bracket.UNREAD`), a journal entry and a branch's own, and the trigger's two, a webhook and an event
rule, which `make netbox-hook` writes on `main` and no read reads (design/verified-facts.md, "A rule's change is
counted as a change of `main`"). A tag is counted, since a tag can be a scope."""

_KEYS = ("blueprint", "scope", "read")
_LINE = re.compile(r"- (blueprint|scope|read):(.*)")
_ID = re.compile(r"[0-9a-f]{64}")
_ITEM = re.compile(r"(?:[-*+]|[0-9]+\.) ")


@dataclass(frozen=True)
class Mark:
    """A mark as its journal entries give it: its label; the blueprint's id, the scope and the time read, as its first
    entry names them, None where a line is missing or there twice; `entries`, the ids of every entry of that label, in
    the order written; and `fault`, why it is not read, in words, or None."""

    label: str
    blueprint_id: str | None
    scope: str | None
    read: str | None
    entries: tuple[int, ...]
    fault: str | None


@dataclass(frozen=True)
class Pin:
    """Where a stage is read: its kind, the branch, for a mark the mark, and the change's id, the branch's
    `schema_id`, which the branch read again by its name is held to."""

    kind: Literal["main", "mark", "head"]
    branch: str
    mark: Mark | None
    change: str


@dataclass(frozen=True)
class Marked:
    """A mark taken: its label, the id the core gave its blueprint, None where the read was refused and no entry
    written, and the findings the read gave."""

    label: str
    blueprint_id: str | None
    findings: tuple[Finding, ...]


def mark_text(label: str, blueprint_id: str, scope: str, read: str) -> str:
    """A mark's journal entry: its first line `MARK_PREFIX` and the label, an empty line, and then the blueprint's id,
    the scope and the time read, a line each, as a list a person reads and the source parses."""
    return f"{MARK_PREFIX}{label}\n\n- blueprint: {blueprint_id}\n- scope: {scope}\n- read: {read}"


def marks_of(entries: Sequence[Mapping[str, Any]]) -> tuple[Mark, ...]:
    """The marks among a branch's journal entries, `entries` in the order given, each with an `id` and its `comments`:
    one `Mark` a label, at its first entry's place, its `entries` every id of that label. An entry whose first line
    does not begin `MARK_PREFIX` is no mark; one that does is a mark, or a malformed one: one with no label, or
    labelled `main` or `head`, is a mark of its own whatever other entry shares its label, refused by its `fault`."""
    found: dict[str, tuple[Mark, list[int]]] = {}
    for entry in entries:
        text = entry.get("comments")
        lines = text.splitlines() if isinstance(text, str) else []
        if not lines or not lines[0].startswith(MARK_PREFIX):
            continue
        label = lines[0][len(MARK_PREFIX):]
        key = label if label not in ("", MAIN, HEAD) else f"\0{entry['id']}"
        if key in found:
            found[key][1].append(entry["id"])
            continue
        values: dict[str, list[str]] = {key: [] for key in _KEYS}
        for line in lines[1:]:
            matched = _LINE.fullmatch(line.rstrip())
            if matched is not None:
                values[matched[1]].append(matched[2].strip())
        once = {key: said[0] if len(said) == 1 else None for key, said in values.items()}
        mark = Mark(label, once["blueprint"], once["scope"], once["read"], (), _fault(label, values))
        found[key] = (mark, [entry["id"]])
    return tuple(
        Mark(mark.label, mark.blueprint_id, mark.scope, mark.read, tuple(ids), mark.fault)
        for mark, ids in found.values()
    )


def _fault(label: str, values: Mapping[str, Sequence[str]]) -> str | None:
    """Why a mark of `label` whose lines gave `values` is not read, the first of: the label is none, or is a stage the
    source makes; a line is missing or there twice; the blueprint's id is not 64 lowercase hex; the scope or the time
    is empty. None where it is read."""
    if not label:
        return "it has no label"
    if label in (MAIN, HEAD):
        return f"its label {label} is a stage the source makes of every branch"
    if not LABEL.fullmatch(label):
        return (
            f"its label {label!r} is no label, which is 1 to 40 lowercase letters, digits and hyphens, beginning and "
            "ending with a letter or a digit"
        )
    for key in _KEYS:
        if not values[key]:
            return f"its line - {key}: is missing"
        if len(values[key]) > 1:
            return f"its line - {key}: is there {len(values[key])} times"
    if not _ID.fullmatch(values["blueprint"][0]):
        return "its blueprint's id is not 64 lowercase hexadecimal characters"
    if not values["scope"][0]:
        return "its scope is empty"
    if not values["read"][0]:
        return "its time read is empty"
    return None


def stages_of(branch: str, marks: Sequence[Mark], *, change: str) -> tuple[Stage, ...]:
    """The stages of `branch`, whose `schema_id` is `change`: `main` as it stands, each of `marks` in their order, and
    the head. A mark's stage is labelled by its label, but one with no label, or labelled as a stage the source
    makes, which is labelled by its entry (`journal entry <id>`), so that none stands as a second `main` or `head`.
    Its `where` gives the time it was read, which the report says it stands at, and ends `, which is not read` where
    it has a fault or two entries."""
    first = Stage(MAIN, "main as it stands", "main as it stands when the rehearsal reads it",
                  Pin("main", branch, None, change))
    stages = [first]
    for mark in marks:
        where = f"{_called(mark)} of branch {branch}"
        if mark.read:
            where += f", read at {mark.read}"
        if mark.fault is not None or len(mark.entries) > 1:
            where += ", which is not read"
        stages.append(Stage(_label(mark), _called(mark), where, Pin("mark", branch, mark, change)))
    stages.append(
        Stage(HEAD, f"the head of {branch}", f"branch {branch} as it stands when the rehearsal reads it",
              Pin("head", branch, None, change))
    )
    return tuple(stages)


def _label(mark: Mark) -> str:
    """A mark's stage's label: its own, but `journal entry <id>` for one with no label or labelled `main` or `head`."""
    return mark.label if mark.label not in ("", MAIN, HEAD) else f"journal entry {mark.entries[0]}"


def _called(mark: Mark) -> str:
    """A mark in words: `the mark <label>`, or `the mark` for one with no label."""
    return f"the mark {mark.label}" if mark.label else "the mark"


def spaced(text: str) -> str:
    """`text` with an empty line put before each list that directly follows a line of text, and nothing else of it
    changed: NetBox renders a Markdown list only where an empty line stands before it (design/verified-facts.md, "A
    report as a journal entry")."""
    lines = text.split("\n")
    out: list[str] = []
    for k, line in enumerate(lines):
        before = lines[k - 1] if k else ""
        if _ITEM.match(line) and before.strip() and not _ITEM.match(before):
            out.append("")
        out.append(line)
    return "\n".join(out)


class NoChange(SourceError):
    """No branch has the name a trigger names."""


class Unready(SourceError):
    """The branch a trigger names is not `ready`: merged, syncing, provisioning or otherwise, its status said."""


@dataclass(frozen=True)
class _Branch:
    """What the source reads of a branch: its numeric id, which a journal entry is assigned by; its `schema_id`, the
    change's id; its status; its tags' slugs, in order; and the time it last took `main`, its `last_sync`, or its
    `created` where that is null."""

    id: int
    schema_id: str
    status: str
    tags: tuple[str, ...]
    synced: str


class NetBoxSource:
    """The change source over one NetBox, read with one token, a reader document and the core the marks were given to:
    the four calls of the seam, `is_draft`, `claim` and `mark`. Made with no request; `transport` replaces the network,
    for tests. `core` is the edge's, and `close` leaves it open."""

    comment_limit: int | None = None
    """No bound: NetBox kept a journal entry whole at a megabyte (D-097)."""
    again: str = "Set the tag `fylgja-rehearse` on the branch again."
    """How the rehearsal is asked for again: the tag set on the branch, which starts it."""
    scope_remedy: str = "Check the scope the runner is given."
    """Where the scope is set: the runner is given it."""

    def __init__(
        self,
        address: str,
        token: str,
        document: ReaderDocument,
        core: Client,
        *,
        ca: Path | None = None,
        transport: Wire | None = None,
    ) -> None:
        self._transport = Transport(address, token, ca=ca, transport=transport)
        self._address = address
        self._token = token
        self._ca = ca
        self._network = transport
        self._document = document
        self._core = core
        self._conn: NetBox | None = None
        self._types: tuple[str, ...] | None = None

    def __repr__(self) -> str:
        """Neither the token nor the address, which may hold a login."""
        return f"NetBoxSource(comment_limit={self.comment_limit!r})"

    def close(self) -> None:
        """Closes the source's connections, its own and the reader's, and never the core's."""
        self._transport.close()
        if self._conn is not None:
            self._conn.close()

    def change(self, ref: str) -> Change:
        """The branch named exactly `ref`, `ready`; `NoChange` where none is, and `Unready` where it is not ready."""
        branch = self._branch(ref)
        if branch.status != READY:
            raise Unready(f"branch {ref} is {branch.status}, and only a ready branch is rehearsed")
        return Change(ref, branch.schema_id, ref, f"branch {ref}")

    def is_draft(self, change: Change) -> bool:
        """No branch is a draft."""
        return False

    def stages(self, change: Change) -> Sequence[Stage]:
        """The change's stages in order (`stages_of`), its marks read from its journal as it stands."""
        return stages_of(change.ref, self._marks(change, self._branch_of(change)), change=change.id)

    def read(self, stage: Stage, scope: str) -> Read:
        """The stage read under `scope`: `main` and the head through the reader, a mark from its entry and the core."""
        pin = stage.pin
        if not isinstance(pin, Pin):
            raise SourceError(f"the stage {stage.label} is not one this source answered: its pin is no Pin")
        if pin.kind == "mark":
            if pin.mark is None:
                raise SourceError(f"the stage {stage.label} is a mark's, and its pin holds no mark")
            return self._mark(pin.mark, pin.branch, scope)
        if pin.kind == "main":
            return self._main(pin, scope)
        return _read(self._moving(pin.branch, scope))

    def post(self, change: Change, report: Report) -> None:
        """The report as one journal entry on the branch, of kind `KIND` of its status, its summary, an empty line and
        its detail, `spaced`."""
        branch = self._branch_of(change)
        self._entry(branch, KIND.get(report.status, "warning"), spaced(f"{report.summary}\n\n{report.detail}"))

    def claim(self, change: Change) -> None:
        """The tag `TAG` taken off the branch by one `PATCH` of its other tags, where it is on it; nothing sent where it
        is not, as when a rehearsal claimed it first."""
        branch = self._branch_of(change)
        if TAG not in branch.tags:
            return
        kept = [{"slug": slug} for slug in branch.tags if slug != TAG]
        self._transport.patch(f"{BRANCHES}{branch.id}/", {"tags": kept})

    def mark(self, change: Change, label: str, scope: str) -> Marked:
        """A mark of the branch labelled `label`, read under `scope` as the head is: its blueprint given to the core,
        and then its entry written, so that no mark names a blueprint the core was never given. A label that is none,
        or one the branch already has, is a `SourceError` with nothing read through the reader or written; a read
        refused is a `Marked` of no blueprint, its findings, and nothing written."""
        if label in (MAIN, HEAD) or not LABEL.fullmatch(label):
            raise SourceError(
                f"{label!r} is no label of a mark: it is 1 to 40 lowercase letters, digits and hyphens, beginning and "
                f"ending with a letter or a digit, and neither {MAIN} nor {HEAD}"
            )
        branch = self._branch_of(change)
        if any(mark.label == label for mark in self._marks(change, branch)):
            raise SourceError(f"branch {change.ref} already has a mark labelled {label}: a label is unique within "
                              "its branch")
        got = self._moving(change.ref, scope)
        if got.blueprint is None:
            return Marked(label, None, got.findings)
        envelope = got.blueprint.get("source")
        observed = envelope.get("observed_at") if isinstance(envelope, dict) else None
        if not isinstance(observed, str) or not observed:
            raise SourceError(f"the read of branch {change.ref} gave a blueprint with no observed_at")
        given = self._core.put_blueprint(got.blueprint)
        self._entry(branch, "info", mark_text(label, given, scope, observed))
        return Marked(label, given, got.findings)

    # The stages.

    def _mark(self, mark: Mark, branch: str, scope: str) -> Read:
        """A mark read from its entry and its blueprint from the core: refused, and the core unasked, where two entries
        share its label, it has a fault, or it was read under another scope; refused by `mark.unheld` where the core
        holds no such blueprint, or answers a document that is not the blueprint of the mark's id.

        A label is unique within its branch and is never taken twice, and NetBox reads no branch as it stood earlier
        (D-097): so a remedy that asks a step marked again says first that its entry is deleted, by a person who may,
        and that the step can be marked only while the branch still stands at it; otherwise the change is seeded
        again."""
        entry = mark.entries[0]
        named = _label(mark)
        if len(mark.entries) > 1:
            message = (
                f"Branch {branch} has {len(mark.entries)} marks labelled {mark.label}, journal entries "
                f"{_and(str(k) for k in mark.entries)}: a label is unique within its branch. Delete all but "
                "one."
            )
            return _refusal(RULE_MARK_DUPLICATE, named, message)
        called = _called(mark)
        if mark.fault is not None or mark.blueprint_id is None or mark.scope is None:
            message = (
                f"{called[0].upper()}{called[1:]} on branch {branch}, journal entry {entry}, is not read: "
                f"{mark.fault or 'it names no blueprint or scope'}. {_redo(entry)[0].upper()}{_redo(entry)[1:]}"
            )
            return _refusal(RULE_MARK_MALFORMED, named, message)
        if mark.scope != scope:
            message = (
                f"The mark {mark.label} on branch {branch}, journal entry {entry}, was read under scope {mark.scope}, "
                f"and this rehearsal reads under {scope}. Rehearse under {mark.scope}, or {_redo(entry, scope)}"
            )
            return _refusal(RULE_MARK_SCOPE, named, message)
        try:
            blueprint = self._core.get_blueprint(mark.blueprint_id)
        except ProblemError as e:
            if e.status != 404 or e.problem.rule != "blueprint.not_found":
                raise
            said = f"holds no blueprint {mark.blueprint_id[:12]}"
        else:
            if _id_of(blueprint) == mark.blueprint_id:
                return Read(blueprint, (), False)
            said = f"answered another document than the blueprint {mark.blueprint_id[:12]}"
        message = (
            f"The core {said}, which the mark {mark.label} on branch {branch} names: a mark belongs to the core it "
            "was given to. Rehearse through that core, or seed and mark the change again for this one."
        )
        return _refusal(RULE_MARK_UNHELD, named, message)

    def _main(self, pin: Pin, scope: str) -> Read:
        """`main` read as it stands, with `stage.main.gained` where it gave a blueprint and `main` has gained changes
        since the branch last took it: the marks were taken against `main` as it stood then. The branch is read again
        by its name, and one of another id than the change's is the source's error: it was replaced under the
        rehearsal."""
        got = self._moving(None, scope)
        if got.blueprint is None:
            return _read(got)
        branch = self._branch(pin.branch)
        if branch.schema_id != pin.change:
            raise SourceError(f"the branch named {pin.branch} is no longer {pin.change}, but {branch.schema_id}")
        gained = self._gained(branch.synced)
        if not gained:
            return _read(got)
        message = (
            f"main has gained {gained} change{'' if gained == 1 else 's'} since branch {pin.branch} was made or last "
            f"synchronised, at {branch.synced}, counted of every kind but a journal entry's, a branch's own, a "
            "webhook's and an event rule's, and the marks were taken against main as it stood then: the first stage "
            "is main as it stands, so the first step may undo those changes on the twin. To rehearse against main as "
            "it stands, synchronise the branch and seed its steps again."
        )
        found = Finding(rule=RULE_MAIN_GAINED, severity=SEVERITY[RULE_MAIN_GAINED], object=pin.branch,
                        message=message)
        return Read(got.blueprint, order([*got.findings, found]), got.empty)

    def _gained(self, synced: str) -> int:
        """How many rows `main`'s changelog holds of `synced` or later, which `time_after` counts, but of the kinds of
        `UNCOUNTED`, left out by their object types' ids: the name form keeps the kinds it names
        (design/verified-facts.md, "A branch behind `main`")."""
        if self._types is None:
            self._types = tuple(self._type(kind) for kind in UNCOUNTED)
        answer = self._transport.get(CHANGES, time_after=synced, changed_object_type_id__n=self._types, limit="1")
        count = answer.get("count")
        if type(count) is not int:
            raise SourceError(f"counting the changes of main since {synced}: HTTP 200: answered no count")
        return count

    def _type(self, kind: str) -> str:
        """The id of the object type `kind`, `<app_label>.<model>`, as NetBox numbers it."""
        app_label, _, model = kind.partition(".")
        rows = [row for row in self._transport.listed(TYPES, app_label=app_label, model=model)
                if row.get("app_label") == app_label and row.get("model") == model]
        found = rows[0].get("id") if len(rows) == 1 else None
        if type(found) is not int:
            raise SourceError(f"the object type {kind}: NetBox answered {len(rows)} of it where one was asked")
        return str(found)

    def _moving(self, branch: str | None, scope: str) -> Result:
        """`branch`, or `main` where it is None, read through the reader, and read again while the reader refuses it
        with `read.moved`, `MOVED_READS` reads in all: the last read's `Result`."""
        conn = self._reader()
        got = self._guarded(branch, lambda: read(conn, branch=branch, scope=scope, document=self._document))
        for _ in range(MOVED_READS - 1):
            if got.blueprint is not None or not any(f.rule == MOVED for f in got.findings):
                break
            got = self._guarded(branch, lambda: read(conn, branch=branch, scope=scope, document=self._document))
        return got

    def _reader(self) -> NetBox:
        """The reader's connection, made at the first read that needs it and kept."""
        if self._conn is None:
            self._conn = self._guarded(
                "", lambda: connect(self._address, self._token, ca=self._ca, transport=self._network)
            )
        return self._conn

    def _guarded[T](self, branch: str | None, call: Callable[[], T]) -> T:
        """`call`, a call of the reader's; its `NetBoxError` of a refused token, 401 or 403, raised as the source's own
        `SourceError` by its status, raised from nothing, since the reader's words name the variable the reader's
        command reads its token from. Any other is raised on. `branch` is the branch read, None for `main` and the
        empty string for the reader's connect."""
        try:
            return call()
        except NetBoxError as e:
            if e.status not in REFUSED:
                raise
            status = e.status
        asked = ("the reader's connect" if branch == "" else
                 f"a read of {f'branch {branch}' if branch is not None else 'main'} through the reader")
        raise SourceError(refused_token(asked, status, self._transport.url), status=status)

    # The branch and its journal.

    def _branch(self, ref: str) -> _Branch:
        """The branch named exactly `ref`, as it stands; `NoChange` where none is."""
        rows = [row for row in self._transport.listed(BRANCHES, name=ref) if row.get("name") == ref]
        if not rows:
            raise NoChange(f"no branch is named {ref}")
        if len(rows) > 1:
            raise SourceError(f"{len(rows)} branches are named {ref}, ids {_and(str(row.get('id')) for row in rows)}")
        row = rows[0]
        found, schema_id, status, tags = row.get("id"), row.get("schema_id"), row.get("status"), row.get("tags")
        status = status.get("value") if isinstance(status, dict) else status
        synced = row.get("last_sync") or row.get("created")
        slugs = [tag.get("slug") if isinstance(tag, dict) else None for tag in tags] if isinstance(tags, list) else []
        held = tuple(slug for slug in slugs if isinstance(slug, str))
        whole = isinstance(tags, list) and len(held) == len(slugs)
        if (type(found) is not int or not isinstance(schema_id, str) or not schema_id or not isinstance(status, str)
                or not whole or not isinstance(synced, str)):
            raise SourceError(
                f"branch {ref}: NetBox answered a branch with no id, schema_id, status, tags, or last_sync and created"
            )
        return _Branch(found, schema_id, status, held, synced)

    def _branch_of(self, change: Change) -> _Branch:
        """The change's branch as it stands, read again by its name; a `SourceError` where the branch of that name is
        another than the change's."""
        branch = self._branch(change.ref)
        if branch.schema_id != change.id:
            raise SourceError(f"the branch named {change.ref} is no longer {change.id}, but {branch.schema_id}")
        return branch

    def _marks(self, change: Change, branch: _Branch) -> tuple[Mark, ...]:
        """The marks among `branch`'s journal entries, listed whole in the order written."""
        rows = self._transport.listed(ENTRIES, assigned_object_type=BRANCH_TYPE, assigned_object_id=str(branch.id),
                                      ordering="created")
        for row in rows:
            if row.get("assigned_object_id") != branch.id or type(row.get("id")) is not int:
                raise SourceError(f"the journal of branch {change.ref}: NetBox answered an entry {row.get('id')} of "
                                  "another object, or with no id")
        return marks_of(rows)

    def _entry(self, branch: _Branch, kind: str, comments: str) -> None:
        """One journal entry written on `branch`."""
        body = {"assigned_object_type": BRANCH_TYPE, "assigned_object_id": branch.id, "kind": kind,
                "comments": comments}
        self._transport.post(ENTRIES, body)


def _redo(entry: int, scope: str | None = None) -> str:
    """How a step whose mark the source does not read is marked again, as the end of a sentence: its entry deleted
    first, since a label is never taken twice, and only while the branch still stands at that step, since NetBox reads
    no branch as it stood earlier (D-097); otherwise the change seeded again."""
    under = f" under {scope}" if scope is not None else ""
    return (
        f"have someone who may delete journal entries delete entry {entry} in NetBox and mark the step again{under}, "
        "which can be done only while the branch still stands at that step; otherwise seed the change again."
    )


def _id_of(blueprint: Mapping[str, Any]) -> str | None:
    """The id the core gives `blueprint`, by its own rule; None where it is no blueprint."""
    try:
        return blueprint_id(dict(blueprint))
    except (KeyError, TypeError, ValueError):
        return None


def _read(result: Result) -> Read:
    """The reader's `Result` as a `Read`, member for member."""
    return Read(result.blueprint, result.findings, result.empty)


def _refusal(rule: str, label: str, message: str) -> Read:
    """A mark's stage refused by `rule`, its object the mark's label, with nothing read."""
    return Read(None, (Finding(rule=rule, severity=SEVERITY[rule], object=label, message=message),), False)


def _and(said: Iterable[str]) -> str:
    """Items in words: `a`, `a and b`, `a, b and c`."""
    items = list(said)
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"
