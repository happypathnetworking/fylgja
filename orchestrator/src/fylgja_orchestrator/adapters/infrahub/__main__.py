"""The adapter as a tool (research R-07): `python -m fylgja_orchestrator.adapters.infrahub`
with three commands, each answering with the findings document `fylgja` answered with and
exiting by its status.

    read --branch <b> [--at <t>] [--stage <b>/<l>] [--scope tag:<n>] [--probes <f>] --out <file> [--json]
    stages [--branch <b>] [--scope tag:<n>] [--json]
    schema-check --branch <b> [--json]

`read` is `fylgja intent read` as the core's server ran it (`internal/server/read.go`): the
guards, the scope, the packages, the probes, the stage's resolution, then the read taken as
a snapshot `2` and written to --out, byte for byte the Go reader's. `stages` is `stage
list` (`stages.go`'s `runStageList`), `schema-check` is `schema check` (`schema.go`).
Without --json the success lines go to stdout as the server's `out` lines did and the
findings to stderr as `WriteText` renders them; with it the document alone goes to stdout.
The start-up line goes to stderr either way.

The scope is --scope when given, else FYLGJA_DEFAULT_SCOPE, else `scope.unset`. Infrahub is
INFRAHUB_ADDRESS with INFRAHUB_API_TOKEN, which nothing prints. `fylgja-cli`'s flows call
the same functions (`read`, `stages`, `schema_check`).
"""

import argparse
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime

from ...documents import stages as stages_text
from ...documents.findings import (
    OP_INTENT_READ,
    OP_SCHEMA_CHECK,
    OP_STAGE_LIST,
    STATUS_ERROR,
    STEP_RESOLVE,
    STEP_START,
    Document,
    error_document,
    new_document,
    quote,
    render,
    rule_error_document,
)
from . import mapping, packages, probes, snapshot, stages, validate
from . import read as reading
from . import stage_reader as sr
from .client import (
    Client,
    ClientError,
    Config,
    ConfigError,
    DefaultClient,
    check_at_precision,
    env_credentials,
    startup_line,
)
from .schema import check_conformance

ENV_DEFAULT_SCOPE = "FYLGJA_DEFAULT_SCOPE"
"""The scope a request that names none is read under, the server's default until 020."""

RULE_SCOPE_INVALID = "scope.invalid"
RULE_SCOPE_UNSET = "scope.unset"
RULE_STAGE_FLAGS_CONFLICT = "stage.flags.conflict"

WHOLE_REFERENCE = "a stage is a whole pinned reference (branch and at)"
"""Why --branch and --at are meaningless beside --stage."""


@dataclass
class Answer:
    """A command's answer: the document, the success lines stdout carries in text, which
    --json suppresses, as the server's `note` did, and the snapshot a clean read took and
    wrote, which the intent-read flow files in the orchestrator's store."""

    doc: Document
    notes: list[str] = field(default_factory=list)
    snapshot: dict | None = None


@dataclass
class Env:
    """What a command reads of its process: the environment, the transport tier 1 answers
    through (None for the SDK's own), and the clock."""

    environ: dict = field(default_factory=lambda: dict(os.environ))
    requester: object = None
    now: datetime | None = None
    stderr: object = None

    def say(self, line: str) -> None:
        if self.stderr is not None:
            self.stderr.write(line + "\n")


def _start(env: Env, scope: str) -> tuple[str, str]:
    """The credentials, then the start-up line, said before Infrahub is first asked;
    ConfigError when either variable is unset."""
    address, token = env_credentials(env.environ)
    env.say(startup_line(address, mapping.READER, mapping.VERSION, scope))
    return address, token


def scope_of(op: str, subject: dict | None, given: str | None, env: Env) -> tuple[str, Document | None]:
    """The scope a read is made under (`scopeOf`): --scope when given, whatever its value, else
    FYLGJA_DEFAULT_SCOPE. A value that is not tag:<name>, an empty one included, is
    scope.invalid naming it; neither is scope.unset naming the variable; each exit 2 at step
    start, before the packages load and before any connection."""

    def refuse(rule, object, message):
        return "", rule_error_document(op, subject, rule, object, message, STEP_START)

    if given is not None:
        if not validate.valid_scope(given):
            return refuse(RULE_SCOPE_INVALID, given, (
                f"--scope {quote(given)} is not a scope: the accepted form is tag:<name>, the literal tag: and "
                "one word, the tag every device of the twin carries"))
        return given, None
    default = env.environ.get(ENV_DEFAULT_SCOPE, "")
    if not default:
        return refuse(RULE_SCOPE_UNSET, ENV_DEFAULT_SCOPE, (
            "no --scope was given and there is no default: name one with --scope tag:<name>, or set "
            f"{ENV_DEFAULT_SCOPE} where the adapter runs"))
    if not validate.valid_scope(default):
        return refuse(RULE_SCOPE_INVALID, default, (
            f"{ENV_DEFAULT_SCOPE} {quote(default)} is not a scope: the accepted form is tag:<name>, the literal "
            "tag: and one word, the tag every device of the twin carries"))
    return default, None


def _load_failure(op: str, subject: dict | None, e: packages.PackageError) -> Document:
    """A package refused as `psp validate` refuses it carries its findings (exit 1); anything
    else is the operation failing to run (`loadFailure`)."""
    if e.findings:
        return new_document(op, subject, e.findings)
    return error_document(op, subject, str(e))


def _with_stage(doc: Document, block: dict | None, warnings) -> Document:
    """The resolved stage on every document after a resolution, its warnings first
    (`withStage`)."""
    if block is not None:
        doc.set("stage", block)
        if warnings:
            doc.findings[:0] = list(warnings)
    return doc


def _write_failure(e: OSError) -> str:
    reason = e.strerror or str(e)
    reason = reason[:1].lower() + reason[1:]
    return f"writing snapshot: {e.filename}: {reason}" if e.filename else f"writing snapshot: {reason}"


def _counts(ctm: dict) -> str:
    """What a read holds, as the success line says it: the devices by package, in package id
    order, then the interfaces, links and artifacts. The lossy mappings and shared ports the
    core's line adds are its compiler's survey, which the adapter does not run."""
    n = reading.summarize(ctm)
    parts = [f"{pkg} {count}" for pkg, count in reading.devices_by_package(ctm)]
    devices = f"{n.devices} devices" + (f" ({', '.join(parts)})" if parts else "")
    line = f"{devices}, {n.interfaces} interfaces, {n.links} links, {n.artifacts} artifacts"
    if n.cables_omitted == 1:
        line += "; 1 cable omitted"
    elif n.cables_omitted:
        line += f"; {n.cables_omitted} cables omitted"
    return line


def _named(envelope: dict) -> str:
    """The reference a CTM was read at, its scope and its schema (`scopedSubject`)."""
    out = "branch " + envelope["branch"]
    if envelope.get("at"):
        out += ", at " + envelope["at"]
    if envelope.get("scope"):
        out += ", scope " + envelope["scope"]
    return out + ", schema " + envelope["schema_hash"]


def read(branch: str = "", at: str = "", stage: str | None = None, scope: str | None = None,
         probes_path: str | None = None, out: str = "", env: Env | None = None) -> Answer:
    """`intent read`: the scope of a branch, or of a stage's resolved reference, read and
    validated in one pass, taken as a snapshot `2` with the request's one probe list and
    written to `out`. `stage`, `scope` and `probes_path` are None when not given; an empty
    one given is refused as the core refused it. Any rejection writes nothing."""
    env = env or Env()
    op = OP_INTENT_READ
    subject = {"branch": branch, "at": at, "out": out}
    if not branch and stage is None:
        return Answer(error_document(op, subject, "--branch or --stage is required"))
    if not out:
        return Answer(error_document(op, subject, "--out is required"))

    ref = None
    if stage is not None:
        # A stage is a whole pinned reference, refused beside the flags it stands for before
        # any connection; with no step, as M1's operations carry none.
        try:
            ref = stages.parse_ref(stage)
        except stages.RefError as e:
            return Answer(rule_error_document(op, subject, stages.RULE_STAGE_REF_INVALID, stage, str(e)))
        subject["stage"] = str(ref)
        for given, flag in ((branch, "--branch"), (at, "--at")):
            if given:
                return Answer(rule_error_document(op, subject, RULE_STAGE_FLAGS_CONFLICT, flag,
                                                  f"{flag} is meaningless with --stage: {WHOLE_REFERENCE}"))
    else:
        message = check_at_precision(at)
        if message:
            return Answer(rule_error_document(op, subject, reading.RULE_AT_PRECISION, at, message))

    scope, refused = scope_of(op, subject, scope, env)
    if refused is not None:
        return Answer(refused)
    subject["scope"] = scope

    # The packages before anything is dialled: an override package `psp validate` refuses is
    # refused with its own findings, and no request is sent.
    try:
        registry = packages.load(override_dir=env.environ.get(packages.ENV_OVERRIDE, ""))
    except packages.PackageError as e:
        return Answer(_load_failure(op, subject, e))

    # Captured before the first request, so observed_at is never later than anything the
    # read could have seen.
    observed_at = reading.observed_now()
    try:
        address, token = _start(env, scope)
    except ConfigError as e:
        return Answer(error_document(op, subject, str(e)))
    default = DefaultClient(address, token, env.requester)

    # The request's one probe list, before the stage resolves and the branch is read (016).
    try:
        declared, found = probes.declared(probes_path, default)
    except probes.ProbesError as e:
        return Answer(error_document(op, subject, str(e), e.step, e.object))
    if declared is None:
        return Answer(new_document(op, subject, found))

    notes = []
    block, warnings = None, []
    if ref is not None:
        reader = sr.StageReader(default)
        try:
            res, resolved = stages.resolve(reader, stages.stamper_of(default), registry, ref, scope,
                                           env.now or datetime.now(UTC))
        except (reading.ReadError, stages.StagesError, ClientError) as e:
            return Answer(error_document(op, subject, str(e)))
        # intent read's operations carry no step.
        resolved = resolved.at_step("")
        if res is None:
            doc = new_document(op, subject, resolved)
            if resolved.carries(reading.RULE_AT_PRECISION):
                doc.status = STATUS_ERROR
            return Answer(doc)
        branch, at = res.branch, res.at
        subject["branch"], subject["at"] = branch, at
        block, warnings = res.block(), list(resolved)
        notes.append(stages_text.line(block))

    client = Client(Config(address=address, token=token, branch=branch, at=at), env.requester)
    try:
        taken, found = reading.read_snapshot(client, scope, registry, declared, observed_at)
    except reading.ReadError as e:
        return Answer(_with_stage(error_document(op, subject, str(e)), block, warnings), notes)
    if taken is None:
        return Answer(_with_stage(new_document(op, subject, found), block, warnings), notes)
    try:
        snapshot.write(out, taken)
    except OSError as e:
        return Answer(_with_stage(error_document(op, subject, _write_failure(e)), block, warnings), notes)

    named = _named(taken["ctm"]["envelope"])
    if ref is not None:
        named = f"stage {ref}: {named}"
    notes.append(f"wrote {out}: {_counts(taken['ctm'])} ({named}); snapshot {taken['snapshot_id']}")
    doc = new_document(op, subject, found)
    doc.set("snapshot_id", taken["snapshot_id"])
    return Answer(_with_stage(doc, block, warnings), notes, taken)


def stage_list(branch: str | None = None, scope: str | None = None, env: Env | None = None,
               record: stages.RecordView | None = None) -> Answer:
    """`stage list`: the stages of every open proposed change, or of the one whose source
    branch `branch` names, with the reference each resolves to. The kind absent is
    stage.kind.absent, exit 1, with no block; an Infrahub that cannot be read is
    operation.failed at resolve, exit 2; a reserved label among the rows is a rejection
    beside them; the warnings leave the exit 0. `record` is the twin's record's stage, the
    orchestrator's to give (T024)."""
    env = env or Env()
    op = OP_STAGE_LIST
    if branch is not None:
        try:
            stages.check_branch(branch)
        except stages.RefError as e:
            return Answer(rule_error_document(op, None, stages.RULE_STAGE_REF_INVALID, branch, str(e), STEP_START))
    scope, refused = scope_of(op, None, scope, env)
    if refused is not None:
        return Answer(refused)
    subject = {"scope": scope}
    try:
        address, token = _start(env, scope)
    except ConfigError as e:
        return Answer(error_document(op, subject, str(e), STEP_RESOLVE, op))
    default = DefaultClient(address, token, env.requester)
    try:
        res, found = stages.list_stages(sr.StageReader(default), stages.stamper_of(default), branch or "", scope,
                                        record)
    except (reading.ReadError, stages.StagesError, ClientError) as e:
        return Answer(error_document(op, subject, str(e), STEP_RESOLVE, op))
    doc = new_document(op, subject, found)
    if found.carries(stages.RULE_STAGE_KIND_ABSENT):
        return Answer(doc)
    block = res.block()
    doc.set("stages", block)
    return Answer(doc, stages_text.list_lines(block))


STAGES_REMEDY = f" (load {sr.STAGE_SCHEMA_FILE}; needed only by --stage, stage list and stage plan)"


def stages_verified(default: DefaultClient) -> tuple[dict, str]:
    """Whether the default branch carries the stage kind with every attribute and the
    relationship this build reads, and CoreProposedChange the extension, and schema check's
    last line saying so (`stagesVerified`). Only an Infrahub that cannot be asked raises
    (ReadError)."""
    v = {"kind": sr.STAGE_KIND, "present": True, "missing": [], "extension": True, "file": sr.STAGE_SCHEMA_FILE}
    lacks_extension = f"{sr.PROPOSED_CHANGE_KIND} lacks {sr.STAGE_EXTENSION}"
    try:
        sr.StageReader(default).check()
    except sr.StageKindError as e:
        if not e.missing and not e.extension:
            v["present"], v["extension"] = False, False
            return v, f"stages: {sr.STAGE_KIND} absent from the default branch{STAGES_REMEDY}"
        if not e.missing:
            v["extension"] = False
            return v, (f"stages: {sr.STAGE_KIND} present on the default branch, but {lacks_extension}"
                       f"{STAGES_REMEDY}")
        v["present"], v["missing"], v["extension"] = False, list(e.missing), not e.extension
        line = f"stages: {sr.STAGE_KIND} on the default branch lacks {', '.join(e.missing)}"
        if e.extension:
            line += ", and " + lacks_extension
        return v, line + STAGES_REMEDY
    return v, f"stages: {sr.STAGE_KIND} present on the default branch, with its extension"


def schema_check(branch: str = "", env: Env | None = None) -> Answer:
    """`schema check`: the branch's schema against the mapping's table, and nothing else: no
    object query and no package. On success the document's `verified` names the library's
    commit and every kind and field, and the stage kind on the default branch beside it,
    never a finding."""
    env = env or Env()
    op = OP_SCHEMA_CHECK
    subject = {"branch": branch}
    if not branch:
        return Answer(error_document(op, subject, "--branch is required"))
    try:
        address, token = env_credentials(env.environ)
    except ConfigError as e:
        return Answer(error_document(op, subject, str(e)))
    client = Client(Config(address=address, token=token, branch=branch), env.requester)
    try:
        conformance, found = check_conformance(client)
    except ClientError as e:
        return Answer(error_document(op, subject, str(e)))
    doc = new_document(op, subject, found)
    if found.rejected:
        return Answer(doc)
    # Said only on success, and in detail: "no findings" reads the same whether every check
    # ran or none did.
    verified = conformance.verified()
    notes = [f"conformant with {verified['model']}@{verified['version']}: "
             + ", ".join(k["kind"] for k in verified["kinds"])]
    try:
        verified["stages"], line = stages_verified(DefaultClient(address, token, env.requester))
    except (reading.ReadError, ClientError) as e:
        return Answer(error_document(op, subject, str(e)))
    doc.set("verified", verified)
    notes.append(line)
    return Answer(doc, notes)


# The command line.


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m fylgja_orchestrator.adapters.infrahub",
                                description="Infrahub's adapter: read a branch into a snapshot, list its stages, "
                                            "check its schema.")
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("read", help="read a branch, or a stage, into a snapshot file")
    r.add_argument("--branch", default="", help="Infrahub branch to read (this or --stage is required)")
    r.add_argument("--at", default="", help="point in time to read at, passed verbatim; never sent when not given")
    r.add_argument("--stage", default=None, help="stage to read, <branch>/<label>")
    r.add_argument("--scope", default=None, help="the scope to read, tag:<name>; FYLGJA_DEFAULT_SCOPE when not given")
    r.add_argument("--probes", default=None, help="a probe declaration (probes 1) in place of FylgjaProbe's")
    r.add_argument("--out", default="", help="path of the snapshot file to write (required)")
    r.add_argument("--json", action="store_true", help="the findings document on stdout")

    s = sub.add_parser("stages", help="list the stages of the open proposed changes")
    s.add_argument("--branch", default=None, help="list the open proposed change of this source branch alone")
    s.add_argument("--scope", default=None, help="the scope the heads are read under, tag:<name>")
    s.add_argument("--json", action="store_true", help="the findings document on stdout")

    c = sub.add_parser("schema-check", help="check a branch's schema against the mapping's table")
    c.add_argument("--branch", default="", help="Infrahub branch to check (required)")
    c.add_argument("--json", action="store_true", help="the findings document on stdout")
    return p


def main(argv=None, stdout=None, stderr=None, env: Env | None = None) -> int:
    """Runs one command and returns its exit code: the document's status's, or 2 for a
    command line argparse refuses."""
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    env = env or Env()
    env.stderr = stderr
    try:
        a = _parser().parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)
    if a.command == "read":
        answer = read(a.branch, a.at, a.stage, a.scope, a.probes, a.out, env)
    elif a.command == "stages":
        answer = stage_list(a.branch, a.scope, env)
    else:
        answer = schema_check(a.branch, env)
    if not a.json:
        for line in answer.notes:
            stdout.write(line + "\n")
    return render(answer.doc, stdout, stderr, a.json)


if __name__ == "__main__":
    sys.exit(main())
