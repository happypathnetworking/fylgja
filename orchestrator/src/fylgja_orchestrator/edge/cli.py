"""The command `fylgja-orchestrator` (D-085): the prototype's six capabilities, of which only the two a check starts
need a server.

`stage list`, `stage plan`, `twin create`, `twin step` and `twin rehearse` each read the settings (`settings`), open
the change source and the core (`run.opened`) and call the rehearsal library in this process, with no Prefect and no
server, closing both whatever the call raised. Each takes `--branch`, the proposed change's source branch, and each
but `stage list`, which reads no stage, `--scope`, which stands in for `FYLGJA_ORCHESTRATOR_SCOPE` where it is given
(P5-49); `twin create` and `twin step` keep their records under
`FYLGJA_ORCHESTRATOR_ROOT`, and `twin rehearse` rehearses on the twin its run id names, `cli-` and a ULID. `serve` runs
the two flows a check starts (`serve`), and is the one command that loads Prefect.

`--json` prints on stdout the document alone (`stage plan`, `twin rehearse`), or the `Listed` or the `Made` as one JSON
object of its fields, a stage by its label, description and where and never its pin. Otherwise a command prints its
text, as each command's function says. Progress lines and findings go to stderr, a finding as `<severity> <rule>
<object>: <message>`.

Exit codes: 0, a plan `planned`, a rehearsal `passed`, a twin made or stepped with no error finding and its run, where
one started, ended `ok`, and `stage list`. 1, any other document or twin, a draft refused among them. 2, a fault of the
command's own: its arguments refused, a variable unset or one the clients' rules refuse (the variable named, never its
value), the reader document refused or not read, or a `SourceError`, an `InfrahubError`, or the core's client's
refusal or failure, each one line and never a traceback; a token, or Prefect's auth string, that any line holds
is replaced.
Where Infrahub refuses the change source's token, by the refusal's status, the line names the variable it was read
from (P5-41, P5-48). `serve` exits as `serve.main` says, and a fault as it begins is one line and exit 2.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fylgja_core import documents, ulid
from fylgja_core.client import Client, FollowError, ProblemError, TransportError, UnsupportedVersion
from fylgja_core.documents import Rejected
from fylgja_infrahub import InfrahubError

from fylgja_orchestrator import rehearsal
from fylgja_orchestrator.edge import run, settings
from fylgja_orchestrator.infrahub import SourceError
from fylgja_orchestrator.infrahub.transport import REFUSED
from fylgja_orchestrator.rehearsal import Listed, Made, Stage

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_FAILURE = 2

RUN_PREFIX = "cli-"
"""The start of a command's run id, which a ULID follows: what names the twin `twin rehearse` makes."""

REDACTED = "<token>"
"""What stands for a token in a line the command prints, as `fylgja_core.cli` writes it."""

SECRETS = (settings.API_TOKEN, settings.INFRAHUB_TOKEN, "PREFECT_API_AUTH_STRING")
"""The variables whose values no line holds: the two tokens, and the runner's credential of Prefect's API."""

BUNDLE_ID = 12
"""The characters of a bundle's id `stage plan` prints."""


@dataclass(frozen=True)
class Context:
    """A command's source and core, opened from its settings, which hold the scope its stages are read under, and
    how it prints."""

    source: run.EdgeSource
    core: Client
    config: settings.Settings
    json: bool


Command = Callable[[Context, argparse.Namespace], int]


def main(argv: Sequence[str] | None = None, *, environ: Mapping[str, str] | None = None) -> int:
    """Run one command under `environ`, the process's environment where it is None; its exit code."""
    env: Mapping[str, str] = os.environ if environ is None else environ
    try:
        args = _parser().parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else EXIT_FAILURE
    try:
        if args.name == "serve":
            from fylgja_orchestrator.edge import serve  # Prefect is loaded here alone (D-085)

            return serve.main(env)
        return _run(args, env)
    except KeyboardInterrupt:
        return EXIT_FAILURE
    except Exception as e:
        # The last resort: one line, never a traceback, and never a token, whatever quoted it.
        _error(f"{type(e).__name__}: {e}", env)
        return EXIT_FAILURE


def _run(args: argparse.Namespace, env: Mapping[str, str]) -> int:
    scope: str | None = getattr(args, "scope", None)
    if scope:
        env = {**env, settings.SCOPE: scope}  # the flag stands in for the variable, before either is judged
    refused = settings.refused(env)
    if refused:
        for line in refused:
            _error(line, env)
        return EXIT_FAILURE
    config = settings.from_env(env)
    try:
        source, core = run.opened(config)
    except Rejected as e:
        _error(f"{settings.READER} names {config.reader}, which is not a valid reader document:", env)
        for problem in e.problems:
            _error(f"  {problem.rule} at {problem.pointer or '/'}: {problem.detail}", env)
        return EXIT_FAILURE
    except (OSError, UnicodeDecodeError) as e:
        _error(f"{settings.READER} names {config.reader}: {getattr(e, 'strerror', None) or e}", env)
        return EXIT_FAILURE
    command: Command = args.command
    context = Context(source, core, config, args.json)
    try:
        return command(context, args)
    except run.DraftRefused as e:
        _error(str(e), env)
        return EXIT_REFUSED
    except SourceError as e:
        line = str(e)
        if e.status in REFUSED:
            line += f"; the change source's token is the one in {settings.INFRAHUB_TOKEN}"
        _error(line, env)
    except (InfrahubError, ProblemError, TransportError, UnsupportedVersion, FollowError) as e:
        _error(str(e), env)
    finally:
        try:
            source.close()
        finally:
            core.close()
    return EXIT_FAILURE


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fylgja-orchestrator",
        description=(
            "Fylgja's example orchestrator: a proposed change of Infrahub planned, and rehearsed on a twin through the "
            "core's API, in this process; or the two flows a check starts, served. The core is "
            f"${settings.API_ADDRESS} with the token in ${settings.API_TOKEN}, Infrahub ${settings.INFRAHUB_ADDRESS} "
            f"with the token in ${settings.INFRAHUB_TOKEN}."
        ),
    )
    nouns = parser.add_subparsers(dest="name", required=True, metavar="COMMAND")

    def noun(name: str, about: str) -> Any:
        return nouns.add_parser(name, help=about, description=about).add_subparsers(
            dest="verb", required=True, metavar="VERB")

    def verb(verbs: Any, name: str, about: str, call: Command, *, scoped: bool = True) -> argparse.ArgumentParser:
        p: argparse.ArgumentParser = verbs.add_parser(name, help=about, description=about)
        p.set_defaults(command=call)
        p.add_argument("--branch", required=True, metavar="B", help="the proposed change's source branch")
        if scoped:
            p.add_argument("--scope", metavar="S", help=f"the devices to read; ${settings.SCOPE} where it is not given")
        p.add_argument("--json", action="store_true", help="print the document, or the result, as JSON")
        return p

    def twin(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument("--twin", required=True, metavar="NAME", help="the twin")
        p.add_argument("--stage", metavar="LABEL", help="the stage to take it to")
        return p

    stage = noun("stage", "The change's stages: listed, or planned.")
    verb(stage, "list", "List the change's stages, none of them read, and the twins that stand at each.", _stage_list,
         scoped=False)
    verb(stage, "plan", "Plan the change: each stage read, filed and built; exit 1 unless it is planned.", _stage_plan)
    twins = noun("twin", "A twin of the change: made at a stage, stepped to another, or the change rehearsed on one.")
    twin(verb(twins, "create", "Create the twin at a stage, by default the first that selects a device.",
              _twin_create))
    step = twin(verb(twins, "step", "Step the twin to a stage, by default the one after the stage it stands at.",
                     _twin_step))
    step.add_argument("--allow-restart", action="store_true", help="allow the step to restart a node")
    verb(twins, "rehearse", "Rehearse the change on a twin of its own, and post the report; exit 1 unless it passed.",
         _twin_rehearse)
    nouns.add_parser("serve", help="Serve the flows stage-plan and twin-rehearse to Prefect at $PREFECT_API_URL.",
                     description="Serve the flows stage-plan and twin-rehearse to Prefect at $PREFECT_API_URL.")
    return parser


# Commands.


def _stage_list(ctx: Context, args: argparse.Namespace) -> int:
    """A line a stage, `<k> <label>: <where>`, with the twins that stand at it, then the stale twins."""
    listed = rehearsal.stage_list(ctx.source, ctx.core, args.branch, root=ctx.config.root)
    if ctx.json:
        _json(_listed(listed))
        return EXIT_OK
    for k, stage in enumerate(listed.stages, 1):
        at = sorted(twin for twin, label in listed.at.items() if label == stage.label)
        print(f"{k} {stage.label}: {stage.where}" + (f"; at it: {', '.join(at)}" if at else ""))
    if listed.stale:
        print(f"stale: {', '.join(listed.stale)}")
    return EXIT_OK


def _stage_plan(ctx: Context, args: argparse.Namespace) -> int:
    """The plan's headline and its change, then a line a stage: `<k> <label>: <outcome>`, what changed, whether it is
    unchanged and its bundle where it built. Its findings, and each stage's, on stderr."""
    doc = run.plan(args.branch, ctx.config.scope, source=ctx.source, core=ctx.core, progress=_progress)
    _said(doc["findings"])
    for stage in doc["stages"]:
        _said(stage.get("findings", ()))
    if ctx.json:
        _json(doc)
    else:
        print(doc["headline"])
        print(doc["change"]["where"])
        for k, stage in enumerate(doc["stages"], 1):
            line = f"{k} {stage['label']}: {stage['outcome']}"
            line += f", {stage['changed']}" if "changed" in stage else ""
            line += " (unchanged)" if stage.get("unchanged") else ""
            line += f", bundle {stage['bundle_id'][:BUNDLE_ID]}" if "bundle_id" in stage else ""
            print(line)
    return EXIT_OK if doc["status"] == "planned" else EXIT_REFUSED


def _twin_create(ctx: Context, args: argparse.Namespace) -> int:
    made = rehearsal.create(ctx.source, ctx.core, args.branch, ctx.config.scope, twin=args.twin, stage=args.stage,
                            root=ctx.config.root, progress=_progress)
    return _made(ctx, made)


def _twin_step(ctx: Context, args: argparse.Namespace) -> int:
    made = rehearsal.step(ctx.source, ctx.core, args.branch, ctx.config.scope, twin=args.twin, stage=args.stage,
                          allow_restart=args.allow_restart, root=ctx.config.root, progress=_progress)
    return _made(ctx, made)


def _twin_rehearse(ctx: Context, args: argparse.Namespace) -> int:
    """The report, whole: its summary, then its detail. A draft is refused (`run.DraftRefused`)."""
    doc = run.rehearse(args.branch, ctx.config.scope, source=ctx.source, core=ctx.core, run_id=RUN_PREFIX + ulid.new(),
                       progress=_progress)
    if ctx.json:
        _json(doc)
    else:
        whole = rehearsal.render(doc, limit=None)
        print(f"{whole.summary}\n\n{whole.detail}")
    return EXIT_OK if doc["status"] == "passed" else EXIT_REFUSED


def _made(ctx: Context, made: Made) -> int:
    """The twin, the stage's label, the blueprint's id and the run's verdict, in one line; its findings on stderr."""
    _said(documents.encode(finding) for finding in made.findings)
    verdict = made.run["verdict"]["status"] if made.run is not None else None
    if ctx.json:
        _json({
            "twin": made.twin,
            "stage": _stage(made.stage) if made.stage is not None else None,
            "blueprint_id": made.blueprint_id,
            "run": made.run,
            "findings": [documents.encode(finding) for finding in made.findings],
        })
    else:
        said = [
            f"stage {made.stage.label}" if made.stage is not None else "no stage",
            f"blueprint {made.blueprint_id}" if made.blueprint_id is not None else "no blueprint",
            f"run {verdict}" if verdict is not None else "no run",
        ]
        print(f"{made.twin}: {', '.join(said)}")
    failed = any(finding.severity == "error" for finding in made.findings)
    return EXIT_REFUSED if failed or verdict not in (None, "ok") else EXIT_OK


# Text.


def _listed(listed: Listed) -> dict[str, Any]:
    return {
        "change": dataclasses.asdict(listed.change),
        "stages": [_stage(stage) for stage in listed.stages],
        "at": dict(listed.at),
        "stale": list(listed.stale),
    }


def _stage(stage: Stage) -> dict[str, str]:
    """A stage by its label, its description and where, and never its pin, which only the source reads."""
    return {"label": stage.label, "description": stage.description, "where": stage.where}


def _json(doc: Any) -> None:
    print(json.dumps(doc, indent=2))


def _said(found: Iterable[Mapping[str, Any]]) -> None:
    """Each finding, a document's member, a line on stderr."""
    for finding in found:
        about = f" {finding['object']}" if finding.get("object") is not None else ""
        _progress(f"{finding['severity']} {finding['rule']}{about}: {finding['message']}")


def _progress(line: str) -> None:
    print(line, file=sys.stderr)


def _error(line: str, env: Mapping[str, str]) -> None:
    """`line` on stderr, the value of each of `SECRETS` that `env` holds replaced."""
    for name in SECRETS:
        token = env.get(name)
        if token:
            line = line.replace(token, REDACTED)
    print(line, file=sys.stderr)

