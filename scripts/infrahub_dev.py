#!/usr/bin/env python3
"""The development host's Infrahub: its lines in `local/.env`, and its Compose project up, stopped and purged.

Run from the repository root as `python3 -I scripts/infrahub_dev.py env|up|down ...`, by `make infrahub-up` and
`make infrahub-down` (CONTRIBUTING.md, D-083). The standard library alone.

- `env --local <local>` adds to `<local>/.env` each of `NAMES` it does not hold, generated, and prints the names it
  added and never a value. A line already there is kept byte for byte: a token made again would not be the one a
  kept database was initialised with. A name the file holds with an empty value is refused, exit 2, the file
  untouched.
- `up` does `env`, makes `<local>/infrahub/repos/` (mode 0700) where it is absent and never empties it, fetches
  Infrahub's published Compose file for the version once into `<local>/infrahub/`, starts the project, asking
  Compose once more where its first start fails, and waits for `/api/info` to answer that version.
- `down` stops the project, giving each container `STOP_TIMEOUT_S` to exit by itself, and keeps its containers,
  network and volumes; with `--purge` it removes them (`down -v`) and `<local>/infrahub/seed.json` with them.

Every Compose command names the project `PROJECT`, `local/.env` as its env file, the fetched file and the override,
and runs with `VERSION` and the two mounts' sources set over the environment it inherits, and with none of `NAMES`
and no other name beginning `INFRAHUB_`, which Compose reads from `local/.env` alone. Exit 0, 1 for a failure said
on stderr, 2 for a command line not understood or a name of `NAMES` held with no value.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from http.client import HTTPException
from pathlib import Path

PROJECT = "fylgja-core-infrahub"
"""The Compose project; the stopped `fylgja-infrahub` beside it on the host is never named."""

COMPOSE_URL = "https://infrahub.opsmill.io/{version}"
"""Infrahub's published Compose file for a version, fetched once and never vendored."""

ADDRESS = "http://127.0.0.1:8000"
"""Where the published file serves Infrahub on this host, and `FYLGJA_INFRAHUB_ADDRESS`'s value."""

UP_WAIT_S = 600
"""How long `up` waits for `/api/info` to answer once Compose's start returns: on new volumes it answered 155 and
158 s after (design/verified-facts.md, "Infrahub 1.11.11")."""

POLL_S = 2
"""Seconds between two asks of `/api/info`."""

STOP_TIMEOUT_S = 60
"""Seconds `down` gives each container to exit by itself before Docker kills it. Compose's own 10 s killed Neo4j
(137) before it had stopped; given 300 s it exited 0 11.3 s after its signal, which this is over five times
(design/verified-facts.md, "Infrahub 1.11.11")."""

FETCH_TIMEOUT_S = 60
"""Seconds the published file's server is given to answer the fetch."""

USER_AGENT = "fylgja-core-infrahub_dev"
"""The fetch's User-Agent: the published file's server refused urllib's own with 403, and answered this one
(design/verified-facts.md, "Infrahub 1.11.11")."""

INFO_TIMEOUT_S = 5
"""Seconds `/api/info` is given to answer one ask."""

NAMES = (
    "INFRAHUB_INITIAL_ADMIN_TOKEN",
    "INFRAHUB_INITIAL_AGENT_TOKEN",
    "INFRAHUB_INITIAL_ADMIN_PASSWORD",
    "INFRAHUB_SECURITY_SECRET_KEY",
    "INFRAHUB_TELEMETRY_OPTOUT",
    "FYLGJA_INFRAHUB_ADDRESS",
    "FYLGJA_INFRAHUB_WRITE_TOKEN",
    "FYLGJA_INFRAHUB_TOKEN",
)
"""What `env` writes into `local/.env`: Compose's four secrets and its telemetry opt-out, then the address and the
writer's and the reader's tokens, both the admin token's value (D-042)."""

SECRETS = NAMES[:4]
ADMIN_TOKEN = NAMES[0]
SAME_AS_ADMIN_TOKEN = ("FYLGJA_INFRAHUB_WRITE_TOKEN", "FYLGJA_INFRAHUB_TOKEN")
FIXED = {"INFRAHUB_TELEMETRY_OPTOUT": "true", "FYLGJA_INFRAHUB_ADDRESS": ADDRESS}

ASSIGNMENT = re.compile(r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)")
QUOTED = re.compile(r"""\s*("[^"]*"|'[^']*')(?:\s+#.*)?""")
COMMENT = re.compile(r"\s#.*")
EMPTY = ("", '""', "''")
VERSION_FORM = re.compile(r"[0-9]+(?:\.[0-9A-Za-z]+)+")

Run = Callable[[Sequence[str], Mapping[str, str]], int]
Fetch = Callable[[str, Path], None]
Info = Callable[[str], str | None]


def say(line: str) -> None:
    print(f"infrahub_dev: {line}", flush=True)


def fail(line: str) -> int:
    print(f"infrahub_dev: {line}", file=sys.stderr, flush=True)
    return 1


class NoValue(Exception):
    """The env file holds one of `NAMES` with an empty value, a line neither kept as it is nor overwritten."""

    def __init__(self, path: Path, names: Sequence[str]) -> None:
        if len(names) == 1:
            super().__init__(f"{path} holds {names[0]} with no value: delete that line or give it a value")
        else:
            super().__init__(f"{path} holds {', '.join(names)} with no value: delete those lines or give each a value")


def uncommented(value: str) -> str:
    """An assignment's value less its comment, as a shell reads it: a quoted value is its quotes and what they hold,
    a comment after them aside; an unquoted one ends where a `#` begins a word, and its spaces are trimmed."""
    quoted = QUOTED.fullmatch(value)
    return quoted[1] if quoted else COMMENT.sub("", value).strip()


def write_env(path: Path) -> list[str]:
    """Add each of `NAMES` that `path` does not hold, and answer the names added, in `NAMES`' order.

    A name is held by a line `NAME=…` or `export NAME=…`, the last such line where there are several, as a shell
    takes it; a commented line holds nothing, and a value ends where an unquoted `#` begins a word. A name held
    with an empty value (`NAME=`, `NAME=""` or `NAME=''`, spaces aside) raises `NoValue` and the file is left
    untouched: kept, it would hand Compose an empty value, which the published file replaces by its own default.
    `NAME= # a note` is refused too: a shell reads it as empty and Compose as the text `# a note`, two readers and two
    values, so it is refused rather than guessed at. Every byte already in the file is kept, a newline added only
    where its last line has none. The four secrets are made by `secrets`; the writer's and the reader's tokens take
    the admin token's value, as the file holds it where it does, its comment aside. The file is written whole through
    a new file of mode 0600 beside it and a rename, and is left at mode 0600 whether or not anything was added.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    held = path.read_bytes() if path.exists() else b""
    values: dict[str, str] = {}
    for line in held.decode().splitlines():
        found = ASSIGNMENT.fullmatch(line.strip())
        if found:
            values[found[1]] = uncommented(found[2])
    empty = [name for name in NAMES if values.get(name) in EMPTY]
    if empty:
        raise NoValue(path, empty)
    added = [name for name in NAMES if name not in values]
    if added:
        new = {name: secrets.token_urlsafe(32) for name in SECRETS if name not in values}
        admin = values[ADMIN_TOKEN] if ADMIN_TOKEN in values else new[ADMIN_TOKEN]
        new |= FIXED | dict.fromkeys(SAME_AS_ADMIN_TOKEN, admin)
        ending = b"\n" if held and not held.endswith(b"\n") else b""
        lines = "".join(f"{name}={new[name]}\n" for name in added).encode()
        part = path.with_name(path.name + ".part")
        part.unlink(missing_ok=True)
        descriptor = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as out:
                out.write(held + ending + lines)
            part.replace(path)
        finally:
            part.unlink(missing_ok=True)
    path.chmod(0o600)
    return added


def report_env(path: Path, added: Sequence[str]) -> None:
    if added:
        say(f"{path}: added {', '.join(added)}")
    else:
        say(f"{path}: holds every name already; nothing written")


def compose(local: Path, version: str, override: Path) -> list[str]:
    """The Compose command, less its verb: the project, its directory, `local/.env` and both files."""
    infrahub = local / "infrahub"
    return [
        "docker",
        "compose",
        "-p",
        PROJECT,
        "--project-directory",
        str(infrahub),
        "--env-file",
        str(local / ".env"),
        "-f",
        str(infrahub / f"docker-compose-{version}.yml"),
        "-f",
        str(override),
    ]


def compose_env(version: str, repo: Path, repos: Path, base: Mapping[str, str]) -> dict[str, str]:
    """Compose's environment: `base` less every name of `NAMES` and every other name beginning `INFRAHUB_`, with
    `VERSION` and the two mounts' sources set.

    Compose takes a variable of its own environment over `--env-file`'s. So `VERSION` is the make variable's
    whatever the shell or `local/.env` holds, and the eight names are left out, set, empty or absent in the shell,
    so that Compose reads them from `local/.env` alone: an exported token would initialise a new database with a
    value the file does not hold, and an empty one would let the published file's default in. Every other
    `INFRAHUB_*` is left out too, since the published file reads about 150 of them, each with a default of its own,
    for its services: an `INFRAHUB_ADDRESS` a shell exports for a client on the host would be the task workers'
    address of Infrahub.
    """
    kept = {name: value for name, value in base.items() if name not in NAMES and not name.startswith("INFRAHUB_")}
    return kept | {"VERSION": version, "FYLGJA_INFRAHUB_REPO": str(repo), "FYLGJA_INFRAHUB_REPOS": str(repos)}


def up(
    local: Path,
    version: str,
    override: Path,
    repo: Path,
    *,
    run: Run,
    fetch: Fetch,
    info: Info,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
) -> int:
    """Write `local/.env`'s missing names, make the mirror's directory, fetch the file, start and wait.

    0 once Infrahub answers the version; 1 for a failure; 2, with nothing made, fetched or started, where `local/.env`
    holds one of `NAMES` with no value.
    """
    env = local / ".env"
    try:
        added = write_env(env)
    except NoValue as e:
        fail(str(e))
        return 2
    report_env(env, added)
    infrahub = local / "infrahub"
    repos = infrahub / "repos"
    repos.mkdir(mode=0o700, parents=True, exist_ok=True)
    repos.chmod(0o700)

    published = infrahub / f"docker-compose-{version}.yml"
    if published.exists():
        say(f"{published} is there")
    else:
        url = COMPOSE_URL.format(version=version)
        part = published.with_name(published.name + ".part")
        try:
            fetch(url, part)
            part.replace(published)
        except (OSError, HTTPException) as e:
            return fail(f"fetching {url} failed: {e}")
        finally:
            part.unlink(missing_ok=True)
        say(f"fetched {url} to {published}")

    argv = [*compose(local, version, override), "up", "-d", "--quiet-pull"]
    environment = compose_env(version, repo, repos, os.environ)
    status = run(argv, environment)
    if status != 0:
        say(f"the first start of {PROJECT} exited {status}; asking Compose once more")
        status = run(argv, environment)
        if status != 0:
            return fail(f"the second start of {PROJECT} exited {status}")
    return wait_for(version, info=info, clock=clock, sleep=sleep)


def wait_for(version: str, *, info: Info, clock: Callable[[], float], sleep: Callable[[float], None]) -> int:
    """Ask `/api/info` every `POLL_S` until it answers `version` (0), another version (1) or `UP_WAIT_S` passes (1).

    The wait is counted from its own start, which `up` makes as Compose's start returns.
    """
    started = clock()
    while True:
        answered = info(ADDRESS)
        waited = clock() - started
        if answered == version:
            say(f"Infrahub {version} answered at {ADDRESS} {waited:.0f} s after Compose's start returned")
            return 0
        if answered is not None:
            return fail(f"{ADDRESS} answers Infrahub {answered}, not {version}")
        if waited >= UP_WAIT_S:
            return fail(
                f"{ADDRESS}/api/info did not answer within {UP_WAIT_S} s; "
                f"read `docker compose -p {PROJECT} logs infrahub-server`"
            )
        sleep(POLL_S)


def down(local: Path, version: str, override: Path, repo: Path, *, purge: bool, run: Run) -> int:
    """Stop the project, or with `purge` remove its containers, network and volumes and then `seed.json`. 0 or 1.

    The stop gives each container `STOP_TIMEOUT_S` to exit by itself. A purge takes Compose's own timeout: what it
    would kill is removed with its volumes.
    """
    verb = ["down", "-v"] if purge else ["stop", "--timeout", str(STOP_TIMEOUT_S)]
    environment = compose_env(version, repo, local / "infrahub" / "repos", os.environ)
    status = run([*compose(local, version, override), *verb], environment)
    if status != 0:
        return fail(f"`docker compose {' '.join(verb)}` of {PROJECT} exited {status}")
    if purge:
        (local / "infrahub" / "seed.json").unlink(missing_ok=True)
        say(f"{PROJECT} removed with its volumes, and its seed file with them")
    else:
        say(f"{PROJECT} stopped; its containers, network and volumes are kept")
    return 0


def run_compose(argv: Sequence[str], env: Mapping[str, str]) -> int:
    return subprocess.run(list(argv), env=dict(env), check=False).returncode


def fetch_url(url: str, dest: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_S) as response, dest.open("wb") as out:
        shutil.copyfileobj(response, out)


def ask_info(address: str) -> str | None:
    """The version `<address>/api/info` answers, or None where it answers nothing readable."""
    try:
        with urllib.request.urlopen(f"{address}/api/info", timeout=INFO_TIMEOUT_S) as response:
            body = json.load(response)
    except (OSError, HTTPException, ValueError):
        return None
    version = body.get("version") if isinstance(body, dict) else None
    return version if isinstance(version, str) else None


def parser() -> argparse.ArgumentParser:
    made = argparse.ArgumentParser(prog="infrahub_dev.py", description=(__doc__ or "").splitlines()[0])
    verbs = made.add_subparsers(dest="verb", required=True)
    env = verbs.add_parser("env", help="add local/.env's missing names")
    env.add_argument("--local", type=Path, required=True, help="the main checkout's local/")
    for verb in ("up", "down"):
        each = verbs.add_parser(verb, help=f"{verb} the Compose project {PROJECT}")
        each.add_argument("--local", type=Path, required=True, help="the main checkout's local/")
        each.add_argument("--version", required=True, help="Infrahub's version")
        each.add_argument("--override", type=Path, required=True, help="the Compose override")
        each.add_argument("--repo", type=Path, required=True, help="the main checkout's .git, mounted read-only")
        if verb == "down":
            each.add_argument("--purge", action="store_true", help="remove the volumes and seed.json")
    return made


def main(argv: Sequence[str]) -> int:
    try:
        args = parser().parse_args(argv)
    except SystemExit as e:
        return 0 if e.code in (0, None) else 2
    local = args.local.absolute()
    try:
        if args.verb == "env":
            try:
                report_env(local / ".env", write_env(local / ".env"))
            except NoValue as e:
                fail(str(e))
                return 2
            return 0
        if not VERSION_FORM.fullmatch(args.version):
            print(f"infrahub_dev: --version {args.version!r} is not a version", file=sys.stderr)
            return 2
        override, repo = args.override.absolute(), args.repo.absolute()
        if args.verb == "up":
            return up(
                local,
                args.version,
                override,
                repo,
                run=run_compose,
                fetch=fetch_url,
                info=ask_info,
                clock=time.monotonic,
                sleep=time.sleep,
            )
        return down(local, args.version, override, repo, purge=args.purge, run=run_compose)
    except OSError as e:
        return fail(f"{args.verb}: {e}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
