"""The command `fylgja-infrahub` (D-082, D-083): the reader's calls from a shell, for an integrator who joins a branch
of Infrahub to the core with a blueprint file between them.

`read` reads a branch at a time, under a scope, by a reader document, and writes the blueprint to `--out`; without
`--at` it reads at `head`'s answer and says which time on stderr. `head` prints the first instant after the branch's
latest write under a scope. `schema-check` holds the branch's schema to the mapping's table. The address, the token
and the CA are `FYLGJA_INFRAHUB_ADDRESS`, `FYLGJA_INFRAHUB_TOKEN` and `FYLGJA_INFRAHUB_CA` alone, never a flag
(D-042): an https:// address is verified against the CA file, or the system's trust where it is unset or empty. The
variables and the reader document are checked in one pass before Infrahub is reached, each fault named.

Each finding is one line on stderr, `<severity> <rule> <object>: <message>`, in a result's order (findings.order), the
connection's version warning among them where Infrahub's version is not one the reader was verified on. A blueprint
holds every device's configuration, so it is written to `--out` alone, whole or not at all and readable by its owner
alone, and never printed; no line the command prints holds the token.

Exit codes: 0, no error finding: `read` wrote the blueprint and printed its id and its counts, `head` printed the time,
`schema-check` printed `ok: <model>@<commit>`. 1, an error finding, a refusal of `head`'s among them: `--out` is not
written, and a file already there is left as it was. 2, a failure of the command's own: its arguments refused, a
variable not set or one it cannot use (the variable named, never its value), a reader document refused or not read,
an `InfrahubError` (Infrahub refused a request, answered what is no answer, or was not reached), or `--out` not
written.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

from fylgja_core import blueprint
from fylgja_core.client import InvalidAddress, InvalidCA, InvalidToken, base_url, bearer, trust
from fylgja_core.documents import Rejected
from fylgja_core.findings import Finding, order

from fylgja_infrahub import document, schema, times
from fylgja_infrahub.document import ReaderDocument
from fylgja_infrahub.read import Refused, check_schema, head, read
from fylgja_infrahub.transport import REDACTED, Infrahub, InfrahubError, connect
from fylgja_infrahub.transport import TOKEN as TOKEN

# The three variables the command reads, and no flag (D-042); the token's is the one the transport names a refused
# token by.
ADDRESS = "FYLGJA_INFRAHUB_ADDRESS"
CA = "FYLGJA_INFRAHUB_CA"

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_FAILURE = 2


class Failure(Exception):
    """What happened to the command itself, in lines for stderr; it exits 2."""

    def __init__(self, *lines: str) -> None:
        self.lines = lines
        super().__init__(*lines)


Command = Callable[[Infrahub, argparse.Namespace, ReaderDocument | None], int]


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command; its exit code."""
    try:
        args = _parser().parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else EXIT_FAILURE
    try:
        return _run(args)
    except KeyboardInterrupt:
        return EXIT_FAILURE
    except Exception as e:
        # The last resort: one line, never a traceback, and never the token, whatever quoted it.
        token = os.environ.get(TOKEN)
        line = f"{type(e).__name__}: {e}"
        _error(line.replace(token, REDACTED) if token else line)
        return EXIT_FAILURE


def _run(args: argparse.Namespace) -> int:
    failures = _variables()
    reading: ReaderDocument | None = None
    path: Path | None = getattr(args, "reader", None)
    if path is not None:
        try:
            reading = document.load(path)
        except Rejected as e:
            failures += [f"{path} is not a valid reader document:", *_problem_lines(e)]
        except (OSError, UnicodeDecodeError) as e:
            failures.append(f"{path}: {getattr(e, 'strerror', None) or e}")
    if failures:
        for line in failures:
            _error(line)
        return EXIT_FAILURE
    ca = os.environ.get(CA)
    command: Command = args.command
    try:
        conn = connect(os.environ[ADDRESS], os.environ[TOKEN], ca=Path(ca) if ca else None)
        try:
            return command(conn, args, reading)
        finally:
            conn.close()
    except InfrahubError as e:
        _error(str(e))
    except Failure as e:
        for line in e.lines:
            _error(line)
    return EXIT_FAILURE


def _variables() -> list[str]:
    """A line for each variable not set or that the client's rules refuse, in one pass, each naming the variable and
    never its value: the predicate `InvalidAddress`, `InvalidToken` or `InvalidCA` gives. The CA alone may be left
    unset, or empty."""
    lines = []
    checks: tuple[tuple[str, Callable[[str], object], bool], ...] = (
        (ADDRESS, base_url, True),
        (TOKEN, bearer, True),
        (CA, lambda value: trust(Path(value)), False),
    )
    for name, check, required in checks:
        value = os.environ.get(name)
        if not value:
            if required:
                lines.append(f"{name} is not set")
            continue
        try:
            check(value)
        except (InvalidAddress, InvalidToken, InvalidCA) as e:
            lines.append(f"{name} {e}")
    return lines


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fylgja-infrahub",
        description=(
            "Fylgja's Infrahub reader: a branch of Infrahub read into a blueprint, or the findings that refused it. "
            f"Infrahub is ${ADDRESS}, read with the token in ${TOKEN}, an https:// address verified against ${CA} "
            "where it is set."
        ),
    )
    commands = parser.add_subparsers(dest="name", required=True, metavar="COMMAND")

    def command(name: str, about: str, call: Command) -> argparse.ArgumentParser:
        p = commands.add_parser(name, help=about, description=about)
        p.set_defaults(command=call)
        p.add_argument("--branch", required=True, metavar="B", help="the branch to read")
        return p

    read_parser = command(
        "read",
        "Read a branch at a time, under a scope, into a blueprint written to --out, and print its id and counts; "
        "exit 1 where a finding is an error, writing nothing.",
        _read,
    )
    read_parser.add_argument("--scope", required=True, metavar="tag:N", help="the devices to read: those tagged N")
    read_parser.add_argument("--reader", required=True, type=Path, metavar="FILE", help="the reader document")
    read_parser.add_argument("--out", required=True, type=Path, metavar="FILE", help="where the blueprint is written")
    read_parser.add_argument("--at", metavar="T", help="the time to read at, as Infrahub writes one; head's otherwise")
    read_parser.add_argument(
        "--generated-since",
        metavar="T",
        help="a time at which a regeneration of the configurations is known to have completed",
    )
    head_parser = command("head", "Print the first instant after the branch's latest write under a scope.", _head)
    head_parser.add_argument("--scope", required=True, metavar="tag:N", help="the devices whose writes count")
    command("schema-check", "Hold the branch's schema to the mapping's table; print ok, or each difference.", _check)
    return parser


# Commands.


def _read(conn: Infrahub, args: argparse.Namespace, reading: ReaderDocument | None) -> int:
    assert reading is not None, "read is given its reader document"
    at: str | None = args.at
    if at is None:
        # `read` judges the times' forms before it sends anything; head is asked before it here, so
        # generated_since's form is judged before head is.
        if args.generated_since is not None:
            refused = times.invalid(args.generated_since, branch=args.branch)
            if refused is not None:
                return _said([refused, *_warned(conn)])
        try:
            at = head(conn, branch=args.branch, scope=args.scope)
        except Refused as e:
            return _said([*e.findings, *_warned(conn)])
        _error(f"reading branch {args.branch} at {at}, its head under {args.scope}")
    result = read(
        conn,
        branch=args.branch,
        at=at,
        scope=args.scope,
        document=reading,
        generated_since=args.generated_since,
    )
    _said(result.findings)
    if result.blueprint is None:
        return EXIT_REFUSED
    doc = result.blueprint
    try:
        _write(args.out, json.dumps(doc, indent=2) + "\n")
    except OSError as e:
        raise Failure(f"{args.out}: {e.strerror or e}") from None
    network = doc["network"]
    print(
        f"{blueprint.blueprint_id(doc)} {len(network['devices'])} devices, {len(network['links'])} links, "
        f"{len(doc['probes'])} probes"
    )
    return EXIT_OK


def _write(path: Path, text: str) -> None:
    """`text` written to `path` whole or not at all: to a file of its own beside `path`, in the same directory, which
    `os.replace` then puts in its place, so a write that fails leaves a file already there as it was, and leaves no
    other. The file is made as `tempfile.mkstemp` makes one, readable and writable by its owner alone. An `OSError` is
    the caller's to say."""
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(text)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _head(conn: Infrahub, args: argparse.Namespace, _: ReaderDocument | None) -> int:
    try:
        at = head(conn, branch=args.branch, scope=args.scope)
    except Refused as e:
        return _said([*e.findings, *_warned(conn)])
    _said(_warned(conn))
    print(at)
    return EXIT_OK


def _check(conn: Infrahub, args: argparse.Namespace, _: ReaderDocument | None) -> int:
    refused = _said(check_schema(conn, branch=args.branch))
    if refused == EXIT_OK:
        print(f"ok: {schema.MODEL}@{schema.COMMIT}")
    return refused


# Text.


def _said(found: Iterable[Finding]) -> int:
    """Each finding a line on stderr, in a result's order; exit 1 where one is an error, else 0."""
    ordered = order(found)
    for finding in ordered:
        about = f" {finding.object}" if finding.object is not None else ""
        _error(f"{finding.severity} {finding.rule}{about}: {finding.message}")
    return EXIT_REFUSED if any(finding.severity == "error" for finding in ordered) else EXIT_OK


def _warned(conn: Infrahub) -> list[Finding]:
    return [conn.unverified] if conn.unverified is not None else []


def _problem_lines(e: Rejected) -> list[str]:
    return [f"  {p.rule} at {p.pointer or '/'}: {p.detail}" for p in e.problems]


def _error(line: str) -> None:
    print(line, file=sys.stderr)
