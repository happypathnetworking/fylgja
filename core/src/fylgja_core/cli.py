"""The thin CLI, `fylgja-core` (D-026): a client of API 1 like any other (D-025).

Commands are noun-verb. Each reaches the core through the client library alone and holds no
rule of its own: every refusal is the server's, printed as its status, rule and detail. The
CLI renders the API's documents as a few lines of text, or with `--json` prints them as they
came, one JSON value per command. It reads `FYLGJA_API_ADDRESS` and `FYLGJA_API_TOKEN`
(D-042) and never prints the token.

Exit codes: 0 ok; 1 a negative verdict (rejected, failed, nonconforming); 2 a problem
document, a transport failure, or a failure of the CLI's own (a variable not set, a file it
cannot read, a blueprint the model package refuses); 3 a twin left dirty (unclean, diverged).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from fylgja_core import blueprint, documents, findings
from fylgja_core.client import Client, ProblemError, TransportError, UnsupportedVersion, base_url, bearer
from fylgja_core.documents import Malformed, Rejected
from fylgja_core.findings import Verdict

ADDRESS = "FYLGJA_API_ADDRESS"
TOKEN = "FYLGJA_API_TOKEN"

# The exit code of each verdict status (findings-1's $comment, D-026).
EXIT: dict[str, int] = {"ok": 0, "rejected": 1, "failed": 1, "nonconforming": 1, "unclean": 3, "diverged": 3}
EXIT_FAILURE = 2


class Failure(Exception):
    """What happened to the CLI itself, in lines for stderr; it exits 2."""

    def __init__(self, *lines: str) -> None:
        self.lines = lines
        super().__init__(*lines)


@dataclass(frozen=True)
class Context:
    """A command's client and how it prints."""

    client: Client
    json: bool

    def show(self, doc: Any, lines: Iterable[str]) -> None:
        """The command's output: the document as JSON, or its text."""
        if self.json:
            print(json.dumps(doc, indent=2))
        else:
            for line in lines:
                print(line)

    def progress(self, line: str) -> None:
        """A line on stderr while a command waits; none with --json."""
        if not self.json:
            print(line, file=sys.stderr)


Command = Callable[[Context, argparse.Namespace], int]


def main(argv: Sequence[str] | None = None, *, transport: httpx.BaseTransport | None = None) -> int:
    """Run one command; its exit code. `transport` replaces the network, for tests."""
    try:
        args = _parser().parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else EXIT_FAILURE
    try:
        return _run(args, transport)
    except KeyboardInterrupt:
        return EXIT_FAILURE
    except Exception as e:
        # The last resort: one line, never a traceback, and never the token, whatever quoted it.
        token = os.environ.get(TOKEN)
        line = f"{type(e).__name__}: {e}"
        _error(line.replace(token, "<token>") if token else line)
        return EXIT_FAILURE


def _run(args: argparse.Namespace, transport: httpx.BaseTransport | None) -> int:
    # Both variables are checked in one pass; a refusal names the variable, never its value.
    refused = False
    for name, check in ((ADDRESS, base_url), (TOKEN, bearer)):
        value = os.environ.get(name)
        if not value:
            _error(f"{name} is not set")
            refused = True
            continue
        try:
            check(value)
        except ValueError as e:
            _error(f"{name} {e}")
            refused = True
    if refused:
        return EXIT_FAILURE
    client = Client(os.environ[ADDRESS], os.environ[TOKEN], transport=transport)
    command: Command = args.command
    try:
        with client:
            return command(Context(client, args.json), args)
    except ProblemError as e:
        if args.json:
            print(json.dumps(documents.encode(e.problem), indent=2))
        _error(str(e))
        for finding in e.problem.findings or ():
            _error(f"  {_finding(documents.encode(finding))}")
    except (TransportError, UnsupportedVersion) as e:
        _error(str(e))
    except Failure as e:
        for line in e.lines:
            _error(line)
    return EXIT_FAILURE


def _parser() -> argparse.ArgumentParser:
    # --json is taken before the noun or after the verb; SUPPRESS keeps a verb's parser from
    # overwriting the one given before the noun.
    json_flag = argparse.ArgumentParser(add_help=False)
    json_flag.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                           help="print the API's documents as JSON")
    parser = argparse.ArgumentParser(
        prog="fylgja-core",
        description=f"The core's thin CLI, a client of API 1 at ${ADDRESS} with the token in ${TOKEN}.",
    )
    parser.add_argument("--json", action="store_true", help="print the API's documents as JSON")
    nouns = parser.add_subparsers(dest="noun", required=True, metavar="NOUN")

    def verbs(noun: str, about: str) -> Callable[[str, str, Command], argparse.ArgumentParser]:
        group = nouns.add_parser(noun, help=about).add_subparsers(dest="verb", required=True, metavar="VERB")

        def verb(name: str, about: str, command: Command) -> argparse.ArgumentParser:
            p = group.add_parser(name, parents=[json_flag], help=about, description=about)
            p.set_defaults(command=command)
            return p

        return verb

    twin = verbs("twin", "create, show, list and destroy twins")
    create = twin("create", "File the blueprint (or name a bundle), create the twin, and wait for its create run.",
                  _twin_create)
    create.add_argument("name")
    source = create.add_mutually_exclusive_group(required=True)
    source.add_argument("--blueprint", type=Path, metavar="FILE", help="a blueprint file, JSON or YAML, to file")
    source.add_argument("--bundle", metavar="ID", help="a filed bundle's id")
    create.add_argument("--driver", metavar="D", help="the driver to run it on; the server's default otherwise")
    create.add_argument("--allow-restart", action="store_true", help="let the loop restart or recreate nodes")
    create.add_argument("--no-wait", action="store_true", help="write the spec and print the record, not waiting")
    twin("show", "Show one twin's record.", _twin_show).add_argument("name")
    twin("list", "List every twin.", _twin_list)
    destroy = twin("destroy", "Ask for the twin's deletion and wait for its destroy run.", _twin_destroy)
    destroy.add_argument("name")
    destroy.add_argument("--no-wait", action="store_true", help="ask and print the record, not waiting")

    run = verbs("run", "read, follow and cancel runs")
    run("get", "Show a run and, once it has ended, its verdict.", _run_get).add_argument("id")
    run("watch", "Print a run's events until it ends; exit by its verdict.", _run_watch).add_argument("id")
    run("cancel", "Ask a run to cancel.", _run_cancel).add_argument("id")

    verbs("blueprint", "file blueprints")("push", "File a blueprint file, JSON or YAML; print its id.",
                                          _blueprint_push).add_argument("file", type=Path)

    bundle = verbs("bundle", "compile and read bundles")
    bundle("build", "Compile a filed blueprint into a bundle.", _bundle_build).add_argument("blueprint_id")
    bundle("get", "Show a filed bundle's manifest.", _bundle_get).add_argument("id")
    return parser


# Commands.


def _twin_create(ctx: Context, args: argparse.Namespace) -> int:
    spec: dict[str, Any] = {}
    if args.blueprint is not None:
        spec["blueprint_id"] = ctx.client.put_blueprint(_blueprint_file(args.blueprint))
    else:
        spec["bundle_id"] = args.bundle
    # API 1's TwinApply requires the driver: with none named, the one the server says is its default.
    spec["driver"] = args.driver or _default_driver(ctx.client)
    spec["allow_restart"] = args.allow_restart
    record, _ = ctx.client.apply_twin(args.name, spec, if_none_match="*")
    if args.no_wait:
        ctx.show(record, _twin_lines(record))
        return 0
    record, seen = _settle(ctx, record)
    run = _ended(ctx.client, _run_of(ctx.client, args.name, "create", seen))
    ctx.show(run, _twin_lines(record) + _run_lines(run))
    return EXIT[_verdict(run).status]


def _twin_show(ctx: Context, args: argparse.Namespace) -> int:
    record, _ = ctx.client.get_twin(args.name)
    ctx.show(record, _twin_lines(record))
    return 0


def _twin_list(ctx: Context, args: argparse.Namespace) -> int:
    twins = ctx.client.list_twins()
    lines = [
        f"{r['name']}: generation {r['generation']}, observed {r['status']['observed_generation']}, "
        f"Ready {_ready(r['status'])}, phase {r['status'].get('phase', 'none')}"
        for r in twins
    ]
    ctx.show(twins, lines or ["no twins"])
    return 0


def _twin_destroy(ctx: Context, args: argparse.Namespace) -> int:
    record = ctx.client.delete_twin(args.name)
    if args.no_wait:
        ctx.show(record, _twin_lines(record))
        return 0
    seen = record["status"].get("run_id")
    try:
        _, seen = _settle(ctx, record)
    except ProblemError as e:
        # Gone before the watch began: the destroy run says how it went.
        if e.status != 404:
            raise
    run = _ended(ctx.client, _run_of(ctx.client, args.name, "destroy", seen))
    ctx.show(run, [f"twin {args.name} deleted", *_run_lines(run)])
    return EXIT[_verdict(run).status]


def _run_get(ctx: Context, args: argparse.Namespace) -> int:
    run = ctx.client.get_run(args.id)
    ctx.show(run, _run_lines(run))
    return 0


def _run_watch(ctx: Context, args: argparse.Namespace) -> int:
    events = []
    for event in ctx.client.watch_run(args.id):
        events.append(event)
        if not ctx.json:
            print(_event_line(event))
    run = _ended(ctx.client, ctx.client.get_run(args.id))
    if ctx.json:
        print(json.dumps(events, indent=2))
    return EXIT[_verdict(run).status]


def _run_cancel(ctx: Context, args: argparse.Namespace) -> int:
    run = ctx.client.cancel_run(args.id)
    ctx.show(run, _run_lines(run))
    return 0


def _blueprint_push(ctx: Context, args: argparse.Namespace) -> int:
    blueprint_id = ctx.client.put_blueprint(_blueprint_file(args.file))
    ctx.show({"id": blueprint_id}, [f"blueprint {blueprint_id}"])
    return 0


def _bundle_build(ctx: Context, args: argparse.Namespace) -> int:
    result = ctx.client.build_bundle(args.blueprint_id)
    fidelity = result["fidelity"]
    lines = _bundle_lines(result["id"], result["manifest"])
    lines.append(f"fidelity: {len(fidelity['approximations'])} approximations, {len(fidelity['omitted'])} omitted, "
                 f"{len(fidelity['synthesized'])} synthesized")
    ctx.show(result, lines + [f"  {_finding(f)}" for f in result["findings"]])
    return 0


def _bundle_get(ctx: Context, args: argparse.Namespace) -> int:
    doc = ctx.client.get_bundle(args.id)
    ctx.show(doc, _bundle_lines(doc["id"], doc["manifest"]))
    return 0


# Waiting.


def _settle(ctx: Context, record: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    """Watch a twin until the loop has acted on its generation or the twin is gone: the last
    record seen, and the last run the records named."""
    seen: str | None = record["status"].get("run_id")
    if record["status"]["observed_generation"] == record["generation"]:
        return record, seen
    name, phase = record["name"], record["status"].get("phase")
    for event in ctx.client.watch_twin(name, since_revision=record["revision"]):
        record = event["object"]
        seen = record["status"].get("run_id", seen)
        if record["status"].get("phase", phase) != phase:
            phase = record["status"]["phase"]
            ctx.progress(f"{name}: {phase}")
        if event["type"] == "DELETED" or record["status"]["observed_generation"] == record["generation"]:
            return record, seen
    raise Failure(f"the watch of twin {name} ended before the loop acted on generation {record['generation']}")


def _run_of(client: Client, twin: str, operation: str, seen: str | None) -> dict[str, Any]:
    """The run a record last named, if it is the operation's, else the twin's newest of it."""
    if seen is not None:
        run = client.get_run(seen)
        if run["operation"] == operation:
            return run
    for run in client.list_runs(twin=twin):
        if run["operation"] == operation:
            return run
    raise Failure(f"twin {twin} has no {operation} run")


def _ended(client: Client, run: dict[str, Any]) -> dict[str, Any]:
    """The run once it has ended: its events followed until their stream ends, then read again."""
    if run["state"] != "ended":
        for _ in client.watch_run(run["id"]):
            pass
        run = client.get_run(run["id"])
    if "verdict" not in run:
        raise Failure(f"run {run['id']} is {run['state']}, with no verdict")
    return run


def _verdict(run: Mapping[str, Any]) -> Verdict:
    try:
        return findings.decode(run["verdict"])
    except Rejected as e:
        raise Failure(f"run {run['id']}'s verdict is no findings 1 document:", *_problem_lines(e)) from None


# Files and the server's defaults.


def _blueprint_file(path: Path) -> dict[str, Any]:
    """The blueprint document in a file, held to blueprint 1 by the model package before it is
    sent; the server refuses such a file the same way."""
    try:
        doc = documents.read(path)
    except (OSError, UnicodeDecodeError) as e:
        raise Failure(f"{path}: {getattr(e, 'strerror', None) or e}") from None
    except Malformed as e:
        raise Failure(str(e)) from None
    problems = blueprint.validate(doc)
    if problems:
        raise Failure(f"{path} is not a valid blueprint:", *_problem_lines(Rejected(problems)))
    loaded: dict[str, Any] = doc
    return loaded


def _default_driver(client: Client) -> str:
    for driver in client.list_drivers():
        if driver["default"]:
            name: str = driver["name"]
            return name
    raise Failure("the server names no default driver; name one with --driver")


# Text.


def _twin_lines(record: Mapping[str, Any]) -> list[str]:
    status = record["status"]
    lines = [f"twin {record['name']}: generation {record['generation']}, observed {status['observed_generation']}"]
    if "deletion_requested_at" in record:
        lines.append(f"deletion requested at {record['deletion_requested_at']}")
    lines += [f"Ready: {_ready(status)}", f"phase: {status.get('phase', 'none')}",
              f"bundle: {status.get('bundle_id', 'none')}"]
    if "run_id" in status:
        lines.append(f"run: {status['run_id']}")
    lines.append("nodes:" if status["nodes"] else "nodes: none")
    for node in status["nodes"]:
        via = f" via {node['access']}" if "access" in node else ""
        lines.append(f"  {node['name']} {node.get('address', 'no address yet')}{via}")
    return lines


def _ready(status: Mapping[str, Any]) -> str:
    ready = next((c for c in status["conditions"] if c["type"] == "Ready"), None)
    if ready is None:
        return "not reported"
    return f"{ready['status']} ({ready['reason']})" if "reason" in ready else str(ready["status"])


def _run_lines(run: Mapping[str, Any]) -> list[str]:
    ended = f", ended at {run['ended_at']}" if "ended_at" in run else ""
    lines = [f"run {run['id']}: {run['operation']} of twin {run['twin']}, {run['state']}",
             f"asked by {run['principal']} at {run['created_at']}{ended}"]
    if "verdict" in run:
        verdict = _verdict(run)
        lines.append(f"verdict: {verdict.status}")
        if verdict.counts is not None:
            c = verdict.counts
            lines.append(f"  held {c.held}, failed {c.failed}, skipped {c.skipped}")
        lines += [f"  {_finding(documents.encode(f))}" for f in verdict.findings]
    return lines


def _event_line(event: Mapping[str, Any]) -> str:
    parts = [str(event["seq"]), event["at"], event["phase"], event["outcome"]]
    if "node" in event:
        parts.append(event["node"])
    if "duration_s" in event:
        parts.append(f"{event['duration_s']:g}s")
    if "rule" in event:
        parts.append(event["rule"])
    return " ".join(parts)


def _bundle_lines(bundle_id: str, manifest: Mapping[str, Any]) -> list[str]:
    nodes = ", ".join(f"{n['name']} ({n['platform']})" for n in manifest["nodes"])
    return [f"bundle {bundle_id}", f"blueprint: {manifest['blueprint_id']}", f"nodes: {nodes or 'none'}",
            f"links: {len(manifest['links'])}, probes: {len(manifest['probes'])}"]


def _finding(f: Mapping[str, Any]) -> str:
    about = f" {f['object']}" if "object" in f else ""
    return f"{f['severity']} {f['rule']}{about}: {f['message']}"


def _problem_lines(e: Rejected) -> list[str]:
    return [f"  {p.rule} at {p.pointer or '/'}: {p.detail}" for p in e.problems]


def _error(line: str) -> None:
    print(line, file=sys.stderr)
