"""The command `fylgja-netbox` (D-095, D-096): the reader's calls from a shell, for an integrator who joins a branch of
NetBox to the core with a blueprint file between them.

`read` reads a branch of NetBox's branching plugin as it stands, or `main` where no `--branch` is given, under a
scope, by a reader document, and writes the blueprint to `--out`. `check` reads NetBox's version and the plugin's,
and for a branch whether NetBox holds it `ready`. The address, the token and the CA are `FYLGJA_NETBOX_ADDRESS`,
`FYLGJA_NETBOX_TOKEN` and `FYLGJA_NETBOX_CA` alone, never a flag (D-042): an https:// address is verified against the
CA file, or the system's trust where it is unset or empty. The variables and the reader document are checked in one
pass before NetBox is reached, each fault named. The reader document's path and `--out`'s are taken as given, a
relative one from the working directory.

Each finding is one line on stderr, `<severity> <rule> <object>: <message>`, in a result's order (findings.order), the
connection's version warning among them where the pair of NetBox's version and the plugin's is not one the reader was
verified on. A blueprint holds every device's configuration, so it is written to `--out` alone, whole or not at all and
readable by its owner alone, and never printed; no line the command prints holds the token, or a half of it.

Exit codes: 0, no error finding: `read` wrote the blueprint and printed its id and its counts, `check` printed
`ok: NetBox <version>, netbox-branching <version, or none>`, and for a branch `, branch <name> ready`. 1, an error
finding, `read.moved` among them where the changelog moved under the read: `--out` is not written, and a file already
there is left as it was. 2, a failure of the command's own: its arguments refused, a variable not set or one it cannot
use (the variable named, never its value), a reader document refused or not read, a `NetBoxError` (NetBox refused a
request, answered what is no answer, or was not reached), or `--out` not written.
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

from fylgja_netbox import document
from fylgja_netbox.document import ReaderDocument
from fylgja_netbox.read import check, read
from fylgja_netbox.transport import TOKEN as TOKEN
from fylgja_netbox.transport import NetBox, NetBoxError, connect, redact

# The three variables the command reads, and no flag (D-042); the token's is the one the transport names a refused
# token by.
ADDRESS = "FYLGJA_NETBOX_ADDRESS"
CA = "FYLGJA_NETBOX_CA"

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_FAILURE = 2


class Failure(Exception):
    """What happened to the command itself, in lines for stderr; it exits 2."""

    def __init__(self, *lines: str) -> None:
        self.lines = lines
        super().__init__(*lines)


Command = Callable[[NetBox, argparse.Namespace, ReaderDocument | None], int]


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
        # The last resort: one line, never a traceback, and never the token or a half of it, whatever quoted it.
        line = f"{type(e).__name__}: {e}"
        token = os.environ.get(TOKEN)
        _error(redact(line, token) if token else line)
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
    except NetBoxError as e:
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
    for name, held, required in checks:
        value = os.environ.get(name)
        if not value:
            if required:
                lines.append(f"{name} is not set")
            continue
        try:
            held(value)
        except (InvalidAddress, InvalidToken, InvalidCA) as e:
            lines.append(f"{name} {e}")
    return lines


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fylgja-netbox",
        description=(
            "Fylgja's NetBox reader: a branch of NetBox's branching plugin, or main, read as it stands into a "
            "blueprint, each device's configuration rendered by NetBox at the read, or the findings that refused it. "
            f"NetBox is ${ADDRESS}, read with the v2 token in ${TOKEN}, an https:// address verified against ${CA} "
            "where it is set."
        ),
    )
    commands = parser.add_subparsers(dest="name", required=True, metavar="COMMAND")

    def command(name: str, about: str, call: Command) -> argparse.ArgumentParser:
        p = commands.add_parser(name, help=about, description=about)
        p.set_defaults(command=call)
        p.add_argument(
            "--branch", metavar="B", type=_branch, help="the branch to read, by its name; main where it is not given"
        )
        return p

    read_parser = command(
        "read",
        "Read a branch as it stands, or main, under a scope, into a blueprint written to --out, and print its id and "
        "counts. Every list is held to the count NetBox answers for it, and each device's configuration is what "
        "NetBox renders for it, as text. The changelog read from is marked before the first list and after the last "
        "render, and a branch read again then: a read either moved under is refused, read.moved, read again. Exit 1 "
        "where a finding is an error, writing nothing.",
        _read,
    )
    read_parser.add_argument("--scope", required=True, metavar="tag:N", help="the devices to read: those tagged N")
    read_parser.add_argument("--reader", required=True, type=Path, metavar="FILE", help="the reader document")
    read_parser.add_argument("--out", required=True, type=Path, metavar="FILE", help="the file the blueprint goes to")
    command(
        "check",
        "Print NetBox's version and the branching plugin's, and for a branch whether NetBox holds it ready; exit 1 "
        "where it does not. For main nothing is asked beyond the versions, so no grant of the token's is checked.",
        _check,
    )
    return parser


def _branch(value: str) -> str:
    """A branch's name, refused where it is empty or whitespace alone: it names no branch, and `main` is read with none
    given."""
    if not value.strip():
        raise argparse.ArgumentTypeError("a branch's name is not empty or whitespace alone; give none to read main")
    return value


# Commands.


def _read(conn: NetBox, args: argparse.Namespace, reading: ReaderDocument | None) -> int:
    assert reading is not None, "read is given its reader document"
    result = read(conn, branch=args.branch, scope=args.scope, document=reading)
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


def _check(conn: NetBox, args: argparse.Namespace, _: ReaderDocument | None) -> int:
    refused = _said(check(conn, branch=args.branch))
    if refused == EXIT_OK:
        ready = f", branch {args.branch} ready" if args.branch is not None else ""
        print(f"ok: NetBox {conn.version}, netbox-branching {conn.branching or 'none'}{ready}")
    return refused


# Text.


def _said(found: Iterable[Finding]) -> int:
    """Each finding a line on stderr, in a result's order; exit 1 where one is an error, else 0."""
    ordered = order(found)
    for finding in ordered:
        about = f" {finding.object}" if finding.object is not None else ""
        _error(f"{finding.severity} {finding.rule}{about}: {finding.message}")
    return EXIT_REFUSED if any(finding.severity == "error" for finding in ordered) else EXIT_OK


def _problem_lines(e: Rejected) -> list[str]:
    return [f"  {p.rule} at {p.pointer or '/'}: {p.detail}" for p in e.problems]


def _error(line: str) -> None:
    print(line, file=sys.stderr)
