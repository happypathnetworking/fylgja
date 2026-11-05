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

    twin = verbs("twin", "create, step, show, list, verify and destroy twins")
    create = twin("create", "File the blueprint (or name a bundle), create the twin, and wait for its create run.",
                  _twin_create)
    create.add_argument("name")
    source = create.add_mutually_exclusive_group(required=True)
    source.add_argument("--blueprint", type=Path, metavar="FILE", help="a blueprint file, JSON or YAML, to file")
    source.add_argument("--bundle", metavar="ID", help="a filed bundle's id")
    create.add_argument("--driver", metavar="D", help="the driver to run it on; the server's default otherwise")
    create.add_argument("--allow-restart", action="store_true", help="let the loop restart or recreate nodes")
    create.add_argument("--no-wait", action="store_true", help="write the spec and print the record, not waiting")
    step = twin("step", "File the blueprint (or name a bundle), write it as the spec of a twin that exists, and "
                        "wait for the run toward it; exit by its verdict.", _twin_step)
    step.add_argument("name")
    source = step.add_mutually_exclusive_group(required=True)
    source.add_argument("--blueprint", type=Path, metavar="FILE", help="a blueprint file, JSON or YAML, to file")
    source.add_argument("--bundle", metavar="ID", help="a filed bundle's id")
    step.add_argument("--allow-restart", action="store_true", help="let the step restart or recreate nodes")
    how = step.add_mutually_exclusive_group()  # a dry run writes nothing, so there is nothing to wait for
    how.add_argument("--no-wait", action="store_true", help="write the spec and print the record, not waiting")
    how.add_argument("--dry-run", action="store_true",
                     help="print what the step would change and its verdict, writing no spec; exit by the verdict")
    twin("show", "Show one twin's record.", _twin_show).add_argument("name")
    twin("list", "List every twin.", _twin_list)
    destroy = twin("destroy", "Ask for the twin's deletion and wait for its destroy run.", _twin_destroy)
    destroy.add_argument("name")
    destroy.add_argument("--no-wait", action="store_true", help="ask and print the record, not waiting")

    twin("verify", "Read every node once and judge it against its bundle; exit by the verdict.",
         _twin_verify).add_argument("name")

    run = verbs("run", "read, follow and cancel runs")
    run("get", "Show a run and, once it has ended, its verdict.", _run_get).add_argument("id")
    run("watch", "Print a run's events until it ends; exit by its verdict.", _run_watch).add_argument("id")
    run("cancel", "Ask a run to cancel.", _run_cancel).add_argument("id")

    verbs("blueprint", "file blueprints")("push", "File a blueprint file, JSON or YAML; print its id.",
                                          _blueprint_push).add_argument("file", type=Path)

    bundle = verbs("bundle", "compile and read bundles")
    bundle("build", "Compile a filed blueprint into a bundle.", _bundle_build).add_argument("blueprint_id")
    bundle("get", "Show a filed bundle's manifest.", _bundle_get).add_argument("id")
    diff = bundle("diff", "Show what a step from one filed bundle to another changes.", _bundle_diff)
    diff.add_argument("from_id", metavar="FROM")
    diff.add_argument("to_id", metavar="TO")
    return parser


# Commands.


def _source(ctx: Context, args: argparse.Namespace) -> dict[str, Any]:
    """A partial spec naming what `--blueprint` (filed first) or `--bundle` gives."""
    if args.blueprint is not None:
        return {"blueprint_id": ctx.client.put_blueprint(_blueprint_file(args.blueprint))}
    return {"bundle_id": args.bundle}


def _twin_create(ctx: Context, args: argparse.Namespace) -> int:
    spec = _source(ctx, args)
    # A partial spec: what is not named here, the server fills (its driver, no restart).
    if args.driver is not None:
        spec["driver"] = args.driver
    if args.allow_restart:
        spec["allow_restart"] = True
    record, _ = ctx.client.apply_twin(args.name, spec, if_none_match="*")
    if args.no_wait:
        ctx.show(record, _twin_lines(record))
        return 0
    settled = _settle(ctx, record)
    run = _ended(ctx.client, _run_of(ctx.client, args.name, ("create",), settled.run_id))
    ctx.show(run, _twin_lines(settled.record) + _run_lines(run))
    return EXIT[_verdict(run).status]


def _twin_step(ctx: Context, args: argparse.Namespace) -> int:
    # A partial spec with no driver: the twin keeps its own. If-Match * asks the server to refuse a
    # twin that does not exist, rather than create one.
    spec = _source(ctx, args)
    if args.allow_restart:
        spec["allow_restart"] = True
    if args.dry_run:
        plan, _ = ctx.client.apply_twin(args.name, spec, if_match="*", dry_run=True)
        try:
            verdict = findings.decode(plan["verdict"])
        except Rejected as e:
            raise Failure("the plan's verdict is no findings 1 document:", *_problem_lines(e)) from None
        ctx.show(plan, _plan_lines(plan, verdict))
        return EXIT[verdict.status]
    record, _ = ctx.client.apply_twin(args.name, spec, if_match="*")
    if args.no_wait:
        ctx.show(record, _twin_lines(record))
        return 0
    if record["status"]["observed_generation"] == record["generation"]:
        # A written spec moves the generation past the observed one: this one was the twin's already.
        ctx.show(record, [*_twin_lines(record), "the twin's spec is this already: no run started"])
        return 0
    settled = _settle(ctx, record)
    # The run toward the spec is a step, or a create for a twin whose create never applied (D-050).
    run = _ended(ctx.client, _run_of(ctx.client, args.name, ("step", "create"), settled.run_id))
    ctx.show(run, _twin_lines(settled.record) + _run_lines(run))
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
    try:
        settled = _settle(ctx, record)
    except ProblemError as e:
        # Gone before the watch began: the destroy run says how it went.
        if e.status != 404:
            raise
        settled = Settled(record, record["status"].get("run_id"), gone=True)
    run = _ended(ctx.client, _run_of(ctx.client, args.name, ("destroy",), settled.run_id))
    # Deleted only when the twin is gone; a teardown that kept the record shows where it stands.
    head = [f"twin {args.name} deleted"] if settled.gone else _twin_lines(settled.record)
    ctx.show(run, head + _run_lines(run))
    return EXIT[_verdict(run).status]


def _twin_verify(ctx: Context, args: argparse.Namespace) -> int:
    document = ctx.client.verify_twin(args.name)
    try:
        verdict = findings.decode(document)
    except Rejected as e:
        raise Failure("the verdict is no findings 1 document:", *_problem_lines(e)) from None
    ctx.show(document, _verdict_lines(verdict))
    return EXIT[verdict.status]


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
    else:
        # The exit code is the verdict's, so the text says which and why.
        for line in _verdict_lines(_verdict(run)):
            print(line)
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


def _bundle_diff(ctx: Context, args: argparse.Namespace) -> int:
    doc = ctx.client.diff_bundles(args.from_id, args.to_id)
    ctx.show(doc, _diff_lines(doc))
    return 0


# Waiting.


@dataclass(frozen=True)
class Settled:
    """How a wait for a twin ended: the last record seen, the last run the records named, and
    whether the twin is gone."""

    record: dict[str, Any]
    run_id: str | None
    gone: bool = False


def _settle(ctx: Context, record: dict[str, Any]) -> Settled:
    """Watch a twin until the loop has acted on its generation or the twin is gone, with a
    progress line each time the phase a record shows its run in flight at moves (`_phase`). The
    record that settles the run, or the twin's deletion, prints none: a step that ended short of
    `applied` leaves `phase` the running twin's, which is no phase the run reached."""
    seen: str | None = record["status"].get("run_id")
    if record["status"]["observed_generation"] == record["generation"]:
        return Settled(record, seen)
    name, phase = record["name"], _phase(record["status"])
    for event in ctx.client.watch_twin(name, since_revision=record["revision"]):
        record = event["object"]
        seen = record["status"].get("run_id", seen)
        settled = record["status"]["observed_generation"] == record["generation"]
        now = _phase(record["status"])
        if not settled and event["type"] != "DELETED" and now is not None and now != phase:
            phase = now
            ctx.progress(f"{name}: {phase}")
        if event["type"] == "DELETED":
            return Settled(record, seen, gone=True)
        if settled:
            return Settled(record, seen)
    raise Failure(f"the watch of twin {name} ended before the loop acted on generation {record['generation']}")


def _phase(status: Mapping[str, Any]) -> str | None:
    """The phase a record shows its run last completed: a running step's `last_step.phase`, which
    moves before `phase` does (until `applied` a step records its phases there alone), else
    `phase`; None when the record shows neither."""
    last = status.get("last_step")
    if last is not None and last["outcome"] == "running":
        step_phase: str = last["phase"]
        return step_phase
    phase: str | None = status.get("phase")
    return phase


def _run_of(client: Client, twin: str, operations: Sequence[str], seen: str | None) -> dict[str, Any]:
    """The run a record last named, if it is of one of the operations, else the twin's newest of them."""
    if seen is not None:
        run = client.get_run(seen)
        if run["operation"] in operations:
            return run
    for run in client.list_runs(twin=twin):
        if run["operation"] in operations:
            return run
    raise Failure(f"twin {twin} has no {' or '.join(operations)} run")


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


# Files.


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


# Text.


def _twin_lines(record: Mapping[str, Any]) -> list[str]:
    status = record["status"]
    lines = [f"twin {record['name']}: generation {record['generation']}, observed {status['observed_generation']}"]
    if "deletion_requested_at" in record:
        lines.append(f"deletion requested at {record['deletion_requested_at']}")
    lines.append(f"Ready: {_ready(status)}")
    lines += [f"{c['type']}: {_condition(c)}" for kind in ("Stepping", "Diverged") for c in status["conditions"]
              if c["type"] == kind]
    lines += [f"phase: {status.get('phase', 'none')}", f"bundle: {status.get('bundle_id', 'none')}"]
    if "last_step" in status:
        last = status["last_step"]
        lines.append(f"last step: {last['outcome']} {last['from'][:12]} -> {last['to'][:12]} at {last['phase']}")
    if "run_id" in status:
        lines.append(f"run: {status['run_id']}")
    lines.append("nodes:" if status["nodes"] else "nodes: none")
    for node in status["nodes"]:
        via = f" via {node['access']}" if "access" in node else ""
        lines.append(f"  {node['name']} {node.get('address', 'no address yet')}{via}")
    return lines


def _ready(status: Mapping[str, Any]) -> str:
    ready = next((c for c in status["conditions"] if c["type"] == "Ready"), None)
    return "not reported" if ready is None else _condition(ready)


def _condition(condition: Mapping[str, Any]) -> str:
    """A condition's status, and its reason when it has one."""
    return f"{condition['status']} ({condition['reason']})" if "reason" in condition else str(condition["status"])


def _run_lines(run: Mapping[str, Any]) -> list[str]:
    ended = f", ended at {run['ended_at']}" if "ended_at" in run else ""
    return [f"run {run['id']}: {run['operation']} of twin {run['twin']}, {run['state']}",
            f"asked by {run['principal']} at {run['created_at']}{ended}",
            *(_verdict_lines(_verdict(run)) if "verdict" in run else [])]


def _verdict_lines(verdict: Verdict) -> list[str]:
    """A verdict's status, counts and each of its findings."""
    lines = [f"verdict: {verdict.status}"]
    if verdict.counts is not None:
        c = verdict.counts
        lines.append(f"  held {c.held}, failed {c.failed}, skipped {c.skipped}")
    return lines + [f"  {_finding(documents.encode(f))}" for f in verdict.findings]


def _plan_lines(plan: Mapping[str, Any], verdict: Verdict) -> list[str]:
    """A dry run's plan: the deployment it would apply, its verdict and, for a step, each node's
    change (with its reasons when it has any) and each link added and removed."""
    lines = [f"deployment: {plan['deployment']['id']}", *_verdict_lines(verdict)]
    changes = plan.get("changes")
    if changes is not None:
        lines.append("changes:")
        lines += [f"  {c['node']}: {c['action']}" + (f" ({', '.join(c['reasons'])})" if c["reasons"] else "")
                  for c in changes["nodes"]]
        for what in ("added", "removed"):
            lines += [f"  link {what}: {a} -- {b}" for a, b in changes[f"links_{what}"]]
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
    unmanaged = ", ".join(n["name"] for n in manifest["nodes"] if "config" not in n)
    return [f"bundle {bundle_id}", f"blueprint: {manifest['blueprint_id']}", f"nodes: {nodes or 'none'}",
            *([f"unmanaged: {unmanaged}"] if unmanaged else []),
            f"links: {len(manifest['links'])}, probes: {len(manifest['probes'])}"]


def _diff_lines(doc: Mapping[str, Any]) -> list[str]:
    head = f"diff {doc['from']} -> {doc['to']}"
    if doc["unchanged"]:
        return [f"{head}: unchanged"]

    def end(e: Mapping[str, Any]) -> str:
        return f"{e['device']}:{e['interface']}"

    nodes, links, probes = doc["nodes"], doc["links"], doc["probes"]
    lines = [head]
    for what, names in (("nodes added", nodes["added"]), ("nodes removed", nodes["removed"])):
        if names:
            lines.append(f"{what}: {', '.join(names)}")
    lines += [f"node {c['node']} changed: {', '.join(c['reasons'])}" for c in nodes["changed"]]
    for what, found in (("links added", links["added"]), ("links removed", links["removed"])):
        lines += [f"{what}: {end(link['a'])} -- {end(link['b'])}" for link in found]
    for what, names in (("probes added", probes["added"]), ("probes removed", probes["removed"])):
        if names:
            lines.append(f"{what}: {', '.join(names)}")
    return lines


def _finding(f: Mapping[str, Any]) -> str:
    about = f" {f['object']}" if "object" in f else ""
    return f"{f['severity']} {f['rule']}{about}: {f['message']}"


def _problem_lines(e: Rejected) -> list[str]:
    return [f"  {p.rule} at {p.pointer or '/'}: {p.detail}" for p in e.problems]


def _error(line: str) -> None:
    print(line, file=sys.stderr)
