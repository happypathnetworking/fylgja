"""Proposed changes, their stages and their branches as the default branch holds them (014,
D-045), ported from `internal/intent/stages.go`'s `StageReader`, word for word.

The reader asks Infrahub's unnamed endpoints, `GET /api/schema` and `POST /graphql`, so an
installation whose default branch is not called `main` needs nothing of it; only the event
log is a branch's (D-048), read by `events.intent_events`. A stage is read, never written:
every request is a query (Constitution III). Nothing here is resolved: a mark's `at` is its
written `as_of` or None, and `label_written_at` its label's `updated_at` verbatim; the
`stages` module orders and resolves them.
"""

from dataclasses import dataclass, field

from fylgja_orchestrator.adapters.infrahub import events, queries
from fylgja_orchestrator.adapters.infrahub.client import ClientError
from fylgja_orchestrator.adapters.infrahub.read import ReadError
from fylgja_orchestrator.adapters.infrahub.read import query as ask
from fylgja_orchestrator.adapters.infrahub.stamps import StampError, parse_stamp

STAGE_KIND = "FylgjaStage"
"""The kind the reader checks for and lists: the one Fylgja-owned kind a stage is (D-057)."""

STAGE_SCHEMA_FILE = "schema/fylgja-stage.yaml"
"""The file that defines the kind and the extension, named by stage.kind.absent and by
schema check so an operator knows what to load."""

PROPOSED_CHANGE_KIND = "CoreProposedChange"
"""Infrahub's kind a stage belongs to."""

STAGE_EXTENSION = "fylgja_stages"
"""The relationship STAGE_SCHEMA_FILE adds to PROPOSED_CHANGE_KIND."""

STAGE_RELATIONSHIP = "proposed_change"
"""The stage's own side of it, to its proposed change."""

STAGE_FIELDS = ("label", "as_of", "description")
"""Every attribute of the kind the build reads. The attribute that carries the reference's
`at` is `as_of`, because Infrahub 1.11.2 refuses a two-character attribute name."""


@dataclass(frozen=True)
class Mark:
    """One mark as Infrahub holds it. `at` is the written `as_of` verbatim or None when
    unwritten; `label_written_at` is `label.updated_at` verbatim, the mark's own write
    stamp, which is its `at` when no `as_of` is written."""

    id: str
    label: str
    label_written_at: str = ""
    at: str | None = None
    description: str = ""


@dataclass(frozen=True)
class ProposedChange:
    """One open proposed change as Infrahub holds it, with its marks. Its `name` is the
    operator's and never an identity (Infrahub does not keep it unique): `id` is, and
    `branch`, its source branch, is how Fylgja finds it, one open proposed change per
    source branch."""

    id: str
    name: str
    branch: str
    destination: str = "main"
    state: str = "open"
    draft: bool = False
    stages: tuple[Mark, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class BranchInfo:
    """A branch's point of origin and its creation, verbatim: the branch point's `at` is
    `branched_from`, which a rebase moves and `created_at` does not."""

    name: str
    branched_from: str = ""
    created_at: str = ""


class StageKindError(Exception):
    """The default branch's schema cannot serve `--stage`, `stage list` and `stage plan`:
    the kind is absent, or it lacks an attribute or the relationship this build reads, or
    the proposed change lacks the extension. Every caller files it as stage.kind.absent
    naming STAGE_SCHEMA_FILE. `missing` names what the kind lacks, the attributes in
    STAGE_FIELDS' order and then STAGE_RELATIONSHIP, empty when the kind itself is absent;
    `extension` that the proposed change lacks the extension."""

    def __init__(self, missing=(), extension: bool = False):
        self.missing = list(missing)
        self.extension = extension
        super().__init__(self._message())

    def _message(self) -> str:
        if not self.missing and not self.extension:
            return f"the default branch's schema has no kind {STAGE_KIND}"
        parts = []
        if self.missing:
            attrs = [m for m in self.missing if m != STAGE_RELATIONSHIP]
            lacks = []
            if len(attrs) == 1:
                lacks.append("the attribute " + attrs[0])
            elif attrs:
                lacks.append("the attributes " + ", ".join(attrs))
            if STAGE_RELATIONSHIP in self.missing:
                lacks.append("the relationship " + STAGE_RELATIONSHIP)
            parts.append(f"kind {STAGE_KIND} on the default branch lacks {' and '.join(lacks)}, which this build reads")
        if self.extension:
            parts.append(
                f"kind {PROPOSED_CHANGE_KIND} on the default branch lacks {STAGE_EXTENSION}, "
                f"the extension {STAGE_SCHEMA_FILE} adds"
            )
        return "; ".join(parts)


def _mark(node: dict, description: str | None = None) -> Mark:
    """One mark from what Infrahub returned. A null `as_of` is unwritten; an operator cannot
    write "" (the kind refuses what is not a time), so "" is unwritten too."""
    label = node.get("label") if isinstance(node.get("label"), dict) else {}
    written = label.get("updated_at")
    at = queries.value(node.get("as_of"))
    return Mark(
        id=node.get("id") or "",
        label=queries.value(label),
        label_written_at=written if isinstance(written, str) else "",
        at=at or None,
        description=queries.value(node.get("description")) if description is None else description,
    )


def _by_label(marks) -> list[Mark]:
    return sorted(marks, key=lambda m: (m.label, m.id))


def _has(relationships, name: str, peer: str) -> bool:
    return any(isinstance(r, dict) and r.get("name") == name and r.get("peer") == peer for r in relationships or [])


class StageReader:
    """Reads proposed changes, their stages and their branches from the default branch
    through a DefaultClient, whose failures name `(the default branch)` and never the
    credential. Every method raises ReadError when Infrahub cannot be read, as the Go
    reader returned its error, for the caller to report as operation.failed."""

    def __init__(self, default):
        self.default = default

    def check(self) -> None:
        """The default branch's schema holds the kind with every attribute in STAGE_FIELDS
        and its relationship to its proposed change, and the proposed change the extension
        back: StageKindError when it does not. Run before any query, since a query of a
        kind the schema lacks is an HTTP 200 whose message names nothing an operator can
        act on."""
        try:
            nodes = self.default.schema_nodes("reading the schema")
        except ClientError as e:
            raise ReadError(str(e)) from None
        found, extension, missing = False, False, []
        for n in nodes:
            if n.get("kind") == STAGE_KIND:
                found = True
                have = {a.get("name") for a in n.get("attributes") or [] if isinstance(a, dict)}
                missing.extend(f for f in STAGE_FIELDS if f not in have)
                if not _has(n.get("relationships"), STAGE_RELATIONSHIP, PROPOSED_CHANGE_KIND):
                    missing.append(STAGE_RELATIONSHIP)
            elif n.get("kind") == PROPOSED_CHANGE_KIND:
                extension = _has(n.get("relationships"), STAGE_EXTENSION, STAGE_KIND)
        # Without the kind there is nothing for the extension to name: the kind's absence
        # is the one thing said.
        if not found:
            raise StageKindError()
        if missing or not extension:
            raise StageKindError(missing, not extension)

    def proposed_changes(self, branch: str = "") -> list[ProposedChange]:
        """The open proposed changes, every one when `branch` is empty or the one whose
        source branch it is, each with its marks, paged. An empty branch is left out of the
        variables, which Infrahub reads as no filter; "" would match none. They come back
        sorted by branch then id, and each one's marks by label then id, whatever the server
        does; the marks' order as stages is the stages module's, by `at`. Only `open` is
        asked for: a closed, merged or canceled proposed change is not visible to Fylgja,
        draft or not."""
        out = []
        offset = 0
        while True:
            variables = {"limit": queries.PAGE_SIZE, "offset": offset}
            if branch:
                variables["branch"] = branch
            page = ask(self.default, queries.PROPOSED_CHANGES, variables, "reading proposed changes").get(
                "CoreProposedChange"
            )
            for n in queries.nodes(page):
                draft = (n.get("is_draft") or {}).get("value") if isinstance(n.get("is_draft"), dict) else None
                out.append(
                    ProposedChange(
                        id=n.get("id") or "",
                        name=queries.value(n.get("name")),
                        branch=queries.value(n.get("source_branch")),
                        destination=queries.value(n.get("destination_branch")),
                        state=queries.value(n.get("state")),
                        draft=draft is True,
                        stages=tuple(_by_label(_mark(s) for s in queries.nodes(n.get(STAGE_EXTENSION)))),
                    )
                )
            if offset + queries.PAGE_SIZE >= queries.count(page):
                break
            offset += queries.PAGE_SIZE
        return sorted(out, key=lambda pc: (pc.branch, pc.id))

    def orphans(self) -> list[Mark]:
        """Every stage that names no proposed change, removed from its proposed change's
        fylgja_stages (D-047), sorted by label then id. Nothing is planned from one; stage
        list warns of each (stage.orphaned)."""
        found = []
        offset = 0
        while True:
            variables = {"limit": queries.PAGE_SIZE, "offset": offset}
            page = ask(self.default, queries.ORPHAN_STAGES, variables, "reading orphaned stages").get(STAGE_KIND)
            found.extend(_mark(s, "") for s in queries.nodes(page))
            if offset + queries.PAGE_SIZE >= queries.count(page):
                break
            offset += queries.PAGE_SIZE
        return _by_label(found)

    def branch(self, name: str) -> BranchInfo | None:
        """A branch's point of origin and its creation; None when Infrahub holds no branch
        of that name."""
        data = ask(self.default, queries.BRANCH_POINT, {"name": name}, "reading branch " + name)
        for b in data.get("Branch") or []:
            if isinstance(b, dict) and b.get("name") == name:
                return BranchInfo(
                    name=name,
                    branched_from=b.get("branched_from") if isinstance(b.get("branched_from"), str) else "",
                    created_at=b.get("created_at") if isinstance(b.get("created_at"), str) else "",
                )
        return None

    def validations(self, id: str, at: str) -> str:
        """When the proposed change's artifact validators last completed, read pinned at
        `at`: the latest `completed_at` value across them (one per artifact definition), ""
        when none has. `at` is sent verbatim as the request's own, and not at all when
        empty. The value is read, never its updated_at: pinned, the value is the one in
        force at `at` and the metadata the current one."""
        what = "reading the artifact validations of proposed change " + id
        try:
            data = self.default.graphql(queries.ARTIFACT_VALIDATIONS, {"id": id}, what, at=at) or {}
        except ClientError as e:
            raise ReadError(str(e)) from None
        latest, latest_at = "", None
        for n in queries.nodes(data.get("CoreArtifactValidator")):
            completed = queries.value(n.get("completed_at"))
            if not completed:
                continue  # queued or running: not completed at at
            try:
                instant = parse_stamp(completed)
            except StampError as e:
                raise ReadError(f"{what} {self.default.where(at)}: {e}") from None
            if not latest or instant > latest_at:
                latest, latest_at = completed, instant
        return latest

    def intent_events(self, branch: str, since: str, after: str = "") -> list:
        """The branch's intent events after `after`, newest first, since its branch point
        (`events.intent_events`, D-048)."""
        return events.intent_events(self.default, branch, since, after)
