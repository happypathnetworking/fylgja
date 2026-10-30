"""`fylgja-cli`, the orchestrator's client (FR-020; research R-02, R-08): the commands the
core's CLI loses, noun-verb as `fylgja`'s, each running its flow in this process.

    intent read --branch <b> [--at <t>] [--stage <b>/<l>] [--scope tag:<n>] [--probes <f>] --out <file>
    stage list [--branch <b>] [--scope tag:<n>]
    stage plan --branch <b> [--scope tag:<n>] [--probes <f>]
    twin create --branch <b>|--stage <b>/<l> [--scope tag:<n>] [--probes <f>] [--dry-run]
    twin step [--stage <b>/<l>] [--scope tag:<n>] [--probes <f>] [--allow-restart] [--wait <d>] [--dry-run]
    twin rehearse --branch <b> [--scope tag:<n>] [--probes <f>] [--markdown]
    schema check --branch <b>

`--json` on every command. Each runs its flow function here (R-08): on the platform
PREFECT_API_URL names when it is set, which must answer first (`platform.unreachable`, exit
2), else on Prefect's ephemeral server under PREFECT_HOME, so no runner is needed for a hand
command and every run is recorded. `stage list` runs no flow: it starts nothing, and is the
adapter's listing with the record's twin row (`flows/stage_list.py`).

What it prints is what `fylgja` printed for the command (`internal/cli/root.go`, `send.go`):
the out lines on stdout as they arrive, then the findings document, its text on stderr or,
under --json, the document alone on stdout; under --markdown, `twin rehearse`'s report as
markdown on stdout and nothing else there, the out lines and the findings on stderr. The exit
is the document's status's. A command line it refuses is the command's own document, status
error, exit 2, and an unknown command a line on stderr, exit 2, as cobra's were.

Prefect is imported only once a command runs a flow, after the two settings the command
line needs are given their defaults (`prepare`): the console handler's level, so the run's
log lines, which repeat the out lines, are not printed again on stderr, and the ephemeral
server's start-up bound, whose 20 s a first start in a fresh PREFECT_HOME exceeds (research
§5.17).
"""

import argparse
import os
import sys
from collections.abc import Callable, Mapping

from . import __version__
from .core import CoreFailure
from .documents.findings import (
    OP_INTENT_READ,
    OP_SCHEMA_CHECK,
    OP_STAGE_LIST,
    OP_STAGE_PLAN,
    OP_TWIN_CREATE,
    OP_TWIN_REHEARSE,
    OP_TWIN_STEP,
    Document,
    error_document,
    render,
)
from .record import check_platform

PROG = "fylgja-cli"

PREFECT_DEFAULTS = {
    # The run's log carries every out line, which the console handler would print again on
    # stderr; a client prints its own (research §5.17's run log, T027).
    "PREFECT_LOGGING_HANDLERS_CONSOLE_LEVEL": "CRITICAL",
    # A first ephemeral start in a fresh PREFECT_HOME took longer than Prefect's 20 s
    # (research §5.17, §5.18: about 10 to 31 s).
    "PREFECT_SERVER_EPHEMERAL_STARTUP_TIMEOUT_SECONDS": "180",
}
"""Prefect's settings `fylgja-cli` gives a default, each kept when the environment sets it."""

SCOPE_USAGE = ("the devices to read, tag:<name>: every device carrying the tag of that name (default: "
               "FYLGJA_DEFAULT_SCOPE)")
PROBES_USAGE = ("a probe declaration file: every snapshot the command takes carries its probes, in place of the ones "
                "declared in Infrahub (default: the probes of FylgjaProbe on the default branch, and none when it "
                "holds none)")
DEFAULT_WAIT = "2m0s"

# The command each noun and verb name: its operation, and the flow it runs ("stage-list" is
# the one body with no flow).
COMMANDS = {
    ("intent", "read"): (OP_INTENT_READ, "intent-read"),
    ("stage", "list"): (OP_STAGE_LIST, "stage-list"),
    ("stage", "plan"): (OP_STAGE_PLAN, "stage-plan"),
    ("twin", "create"): (OP_TWIN_CREATE, "twin-create"),
    ("twin", "step"): (OP_TWIN_STEP, "twin-step"),
    ("twin", "rehearse"): (OP_TWIN_REHEARSE, "twin-rehearse"),
    ("schema", "check"): (OP_SCHEMA_CHECK, "schema-check"),
}


class Usage(Exception):
    """A command line argparse refuses, and the command it names: `prog` is the refusing
    parser's, `fylgja-cli twin create` for a leaf."""

    def __init__(self, message: str, prog: str):
        super().__init__(message)
        self.prog = prog

    def operation(self) -> str:
        """The operation a leaf's refusal belongs to, "" for the root's or a noun's, which
        name none and get no document (`operationOf`)."""
        parts = self.prog.split()
        return ".".join(parts[1:]) if len(parts) == 3 else ""


class Parser(argparse.ArgumentParser):
    """argparse, refusing by raising rather than exiting, so a refusal is a document."""

    def error(self, message):
        raise Usage(message, self.prog)


def _json(p: argparse.ArgumentParser) -> None:
    # On the root and every leaf, as cobra's persistent flag: the leaf's leaves the root's
    # value alone when not given.
    p.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                   help="emit one findings document on stdout and nothing else there")


def parser() -> Parser:
    root = Parser(prog=PROG, description="Fylgja's orchestrator: read intent, plan a proposed change's stages, and "
                                         "drive the core's twin through them")
    root.add_argument("--json", action="store_true", default=False,
                      help="emit one findings document on stdout and nothing else there")
    root.add_argument("--version", action="version", version=f"{PROG} {__version__}")
    nouns = root.add_subparsers(dest="noun", metavar="<command>")

    intent = nouns.add_parser("intent", help="Read intent from the source of truth")
    verbs = intent.add_subparsers(dest="verb", metavar="<verb>")
    p = verbs.add_parser("read", help="Read a branch into a validated intent snapshot",
                         description="Read the devices an Infrahub branch's scope selects, by the mapping of the "
                                     "schema library's DCIM at 26336e9, and write a snapshot file, which the "
                                     "orchestrator also files under its snapshots/. Conformance, data completeness "
                                     "and the intent rules are checked in one pass and reported together; any "
                                     "rejection means no file is written and nothing is filed. Reads only.")
    p.add_argument("--branch", default="", help="Infrahub branch to read (this or --stage is required)")
    p.add_argument("--at", default="",
                   help="point in time to read at, passed verbatim; omitted entirely when not given")
    p.add_argument("--stage", default=None, help="stage to read, <branch>/<label>: the pinned branch and at a proposed "
                                                 "change's stage resolves to, in place of --branch and --at")
    p.add_argument("--scope", default=None, help=SCOPE_USAGE)
    p.add_argument("--probes", default=None, help=PROBES_USAGE)
    p.add_argument("--out", default="", help="path of the snapshot file to write (required)")
    _json(p)

    stage = nouns.add_parser("stage", help="List and plan the stages of Infrahub's open proposed changes")
    verbs = stage.add_subparsers(dest="verb", metavar="<verb>")
    p = verbs.add_parser("list", help="List every open proposed change's stages and the reference each resolves to",
                         description="List the stages of Infrahub's open proposed changes, or of the one whose source "
                                     "branch --branch names, in order: the branch point, the marks by their at, and "
                                     "the head, each with the branch and at it resolves to and where the at came "
                                     "from. The stage the orchestrator's record names as the twin's is marked while "
                                     "fylgja twin show names its snapshot.")
    p.add_argument("--branch", default=None, help="list the open proposed change of this source branch alone")
    p.add_argument("--scope", default=None, help=SCOPE_USAGE)
    _json(p)
    p = verbs.add_parser("plan", help="Read and compile each stage of a proposed change, and print the step between "
                                      "each pair",
                         description="Read each stage of the open proposed change whose source branch --branch names, "
                                     "in order, file its snapshot, have the core compile it, and print the stage's "
                                     "snapshot_id above its bundle_id; between each consecutive pair, the core's step "
                                     "between the two. A stage that is refused is reported and the plan goes on.")
    p.add_argument("--branch", default="", help="the source branch of the proposed change to plan (required)")
    p.add_argument("--scope", default=None, help=SCOPE_USAGE)
    p.add_argument("--probes", default=None, help=PROBES_USAGE + "; every stage carries the one list")
    _json(p)

    twin = nouns.add_parser("twin", help="Build twins from a branch or a stage, and rehearse proposed changes")
    verbs = twin.add_subparsers(dest="verb", metavar="<verb>")
    p = verbs.add_parser("create", help="Provision one twin from a branch or a stage",
                         description="Read an Infrahub branch or a proposed change's stage, file its snapshot, and "
                                     "have the core provision one twin from it, printing a line as each step begins "
                                     "and ends, until every node answers its readiness probe or the run has cleaned "
                                     "up after itself. The core's run goes on if this command is interrupted: fylgja "
                                     "twin show names it.")
    p.add_argument("--branch", default="", help="Infrahub branch to read (this or --stage is required)")
    p.add_argument("--stage", default=None,
                   help="stage to build the twin from, <branch>/<label>: the pinned branch and at a proposed change's "
                        "stage resolves to")
    p.add_argument("--scope", default=None, help=SCOPE_USAGE)
    p.add_argument("--probes", default=None, help=PROBES_USAGE)
    p.add_argument("--dry-run", action="store_true", help="read and file the snapshot, and have the core compile it, "
                                                          "file the bundle and check the host; start no run")
    _json(p)
    p = verbs.add_parser("step", help="Take the running twin to another stage, without a rebuild",
                         description="Take the running twin to a stage of any proposed change, the one --stage names "
                                     "or, left out, the next stage of the one the orchestrator's record names, "
                                     "which needs fylgja twin show to name the record's snapshot. The target is "
                                     "read and filed, and the core steps the twin to it, waits for it to conform "
                                     "and records it.")
    p.add_argument("--stage", default=None, help="the stage to step to, <branch>/<label>, of any proposed change; left "
                                                 "out, the next stage of the twin's own proposed change")
    p.add_argument("--scope", default=None, help=SCOPE_USAGE + "; left out, the scope the twin's record names")
    p.add_argument("--probes", default=None, help=PROBES_USAGE)
    p.add_argument("--allow-restart", action="store_true",
                   help="proceed when containerlab's plan restarts or recreates a node, which loses its running state "
                        "until the step pushes it again")
    p.add_argument("--wait", default=None, help="after the record, read the twin until it conforms, at most this long "
                                                f"(default {DEFAULT_WAIT}; 0 reads once)")
    p.add_argument("--dry-run", action="store_true", help="read and file the target, and have the core compile it, "
                                                          "check the host and read containerlab's plan; start no run")
    _json(p)
    p = verbs.add_parser("rehearse", help="Rehearse a proposed change's stages on a twin, stopping at the first that "
                                          "fails",
                         description="Plan the open proposed change whose source branch --branch names, then on one "
                                     "twin create the first stage that compiled, step to each later stage in order "
                                     "and verify it, stop at the first that fails, and destroy the twin whatever "
                                     "happened. The report is posted on the proposed change as one thread. "
                                     "--markdown prints it as that comment.")
    p.add_argument("--branch", default="", help="the source branch of the proposed change to rehearse (required)")
    p.add_argument("--scope", default=None, help=SCOPE_USAGE)
    p.add_argument("--probes", default=None, help=PROBES_USAGE + "; every stage carries the one list")
    p.add_argument("--markdown", action="store_true",
                   help="emit the report as markdown on stdout and nothing else there, the progress and the findings "
                        "on stderr")
    _json(p)

    schema = nouns.add_parser("schema", help="Inspect the intent schema on a branch")
    verbs = schema.add_subparsers(dest="verb", metavar="<verb>")
    p = verbs.add_parser("check", help="Check a branch's schema against the schema library the reader reads",
                         description="Run the conformance half of intent read alone: the branch's schema holds every "
                                     "kind and field the mapping reads. No intent is read and nothing is written.")
    p.add_argument("--branch", default="", help="Infrahub branch to check (required)")
    _json(p)
    root.nouns = {"intent": intent, "stage": stage, "twin": twin, "schema": schema}
    return root


def params(key: tuple[str, str], a: argparse.Namespace) -> dict:
    """The flow's parameters from the command line (data-model §7)."""
    match key:
        case ("intent", "read"):
            return {"branch": a.branch, "at": a.at, "stage": a.stage, "scope": a.scope, "probes_path": a.probes,
                    "out": a.out}
        case ("stage", "list"):
            return {"branch": a.branch, "scope": a.scope}
        case ("stage", "plan"):
            return {"branch": a.branch, "scope": a.scope, "probes_path": a.probes}
        case ("twin", "create"):
            return {"branch": a.branch, "stage": a.stage, "scope": a.scope, "probes_path": a.probes,
                    "dry_run": a.dry_run}
        case ("twin", "step"):
            return {"stage": a.stage, "scope": a.scope, "probes_path": a.probes, "allow_restart": a.allow_restart,
                    "wait": a.wait, "dry_run": a.dry_run}
        case ("twin", "rehearse"):
            return {"branch": a.branch, "scope": a.scope, "probes_path": a.probes, "markdown": a.markdown}
        case _:
            return {"branch": a.branch}


# Running a command.


def prepare(environ) -> None:
    """Prefect's two settings given their defaults, before Prefect is imported."""
    for name, value in PREFECT_DEFAULTS.items():
        environ.setdefault(name, value)


def runners() -> dict[str, Callable[..., Document]]:
    """Each command's runner by its flow's name: the six flows, and stage list's body over the
    process's environment."""
    from .flows import (
        intent_read,
        schema_check,
        stage_list,
        stage_plan,
        twin_create,
        twin_rehearse,
        twin_step,
    )
    from .flows.common import Deps

    return {
        "intent-read": intent_read.intent_read,
        "stage-list": lambda **kw: stage_list.run(Deps.from_env(), **kw),
        "stage-plan": stage_plan.stage_plan,
        "twin-create": twin_create.twin_create,
        "twin-step": twin_step.twin_step,
        "twin-rehearse": twin_rehearse.twin_rehearse,
        "schema-check": schema_check.schema_check,
    }


def _writer(stream) -> Callable[[str], None]:
    def write(line: str) -> None:
        stream.write(line + "\n")
        stream.flush()
    return write


def _discard(_: str) -> None:
    pass


def run(op: str, flow: str, kwargs: dict, runner: Callable[..., Document], stdout, stderr, as_json: bool,
        markdown: bool) -> Document:
    """The command's flow run here, its out lines and markdown sent where the mode says, and
    its document: the one it returned, else the one it filed before what it raised, else the
    flow's failure as the command's own."""
    from .flows import common

    out = _discard if as_json else _writer(stderr if markdown else stdout)
    filed: list[Document] = []
    tokens = [(common.OUT, common.OUT.set(out)), (common.FILED, common.FILED.set(filed))]
    if markdown:
        from .flows import twin_rehearse

        tokens.append((twin_rehearse.MARKDOWN, twin_rehearse.MARKDOWN.set(_writer(stdout))))
    try:
        doc = runner(**kwargs)
    except (Exception, KeyboardInterrupt) as e:
        if filed:
            return filed[-1]
        why = "interrupted" if isinstance(e, KeyboardInterrupt) else str(e) or type(e).__name__
        return error_document(op, None, f"the flow {flow} did not end with its document: {why}; any run of the "
                                        "core's it started goes on, and fylgja twin show names it")
    finally:
        for var, token in reversed(tokens):
            var.reset(token)
    if not isinstance(doc, Document):
        return error_document(op, None, f"the flow {flow} returned no findings document")
    return doc


def main(argv=None, stdout=None, stderr=None, environ: Mapping[str, str] | None = None,
         flows: Mapping[str, Callable[..., Document]] | None = None) -> int:
    """Runs one command and returns its exit code. `environ` and `flows` are the process's
    and the six flows' unless a test gives its own; the process's environment gains
    Prefect's two defaults only when none is given."""
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    argv = sys.argv[1:] if argv is None else list(argv)
    if environ is None:
        prepare(os.environ)
        environ = os.environ
    p = parser()
    try:
        # Known arguments first, so a flag no command knows is refused by the command it was
        # given to, as cobra's `unknown flag` was, rather than by the root.
        a, extra = p.parse_known_args(argv)
        if extra:
            prog = PROG if not a.noun else " ".join([PROG, a.noun] + ([a.verb] if getattr(a, "verb", None) else []))
            raise Usage(f"unrecognized arguments: {' '.join(extra)}", prog)
    except Usage as e:
        op = e.operation()
        if not op:
            stderr.write(f"{PROG}: {e}\n")
            return 2
        return render(error_document(op, None, str(e)), stdout, stderr, "--json" in argv)
    except SystemExit as e:  # --help and --version
        return int(e.code or 0)

    if not a.noun or not getattr(a, "verb", None):
        # A noun or nothing: its help, as cobra printed a command with no run of its own.
        sub = p.nouns[a.noun] if a.noun else p
        sub.print_help(stdout)
        return 0
    key = (a.noun, a.verb)
    op, flow = COMMANDS[key]
    markdown = getattr(a, "markdown", False)
    if markdown and a.json:
        return render(error_document(op, None, "--markdown and --json cannot be given together: each is the one "
                                               "thing printed on stdout"), stdout, stderr, True)
    if flow != "stage-list":
        try:
            check_platform(environ)
        except CoreFailure as e:
            return render(e.document(op), stdout, stderr, a.json)
    runner = (flows if flows is not None else runners())[flow]
    doc = run(op, flow, params(key, a), runner, stdout, stderr, a.json, markdown)
    return render(doc, stdout, stderr, a.json)


if __name__ == "__main__":
    sys.exit(main())
