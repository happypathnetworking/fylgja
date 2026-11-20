#!/usr/bin/env python3
"""The development host's Nautobot: its lines in `local/.env`, and its Compose project up, stopped and purged.

Run from the repository root as `python3 -I scripts/nautobot_dev.py env|up|down ...`, by `make nautobot-up` and
`make nautobot-down` (CONTRIBUTING.md, D-119). The standard library alone; no script imports another.

- `env --local <local>` adds to `<local>/.env` each of `NAMES` it does not hold, generated, and prints the names it
  added and never a value. A line already there is kept byte for byte: a database password or a secret key made
  again would not open the volumes a kept file made, and a token made again is not what a kept database holds. A
  name the file holds with an empty value is refused, exit 2, the file untouched.
- `up` does `env`; makes `<local>/nautobot/git`, the directory the `git` service serves, where it is absent; builds
  the image from `nautobot/dev/`; starts the project; waits for `/health/` to answer 200, asked from the host and
  never of Docker, whose word on `nautobot` was `unhealthy` while it answered; and then reads `/api/status/` with the
  superuser's token, the line `WRITE_TOKEN` of `local/.env`, which the image's entrypoint takes at each start, and is
  done once Nautobot names its version, Golden Config's and a running worker.
- `down` stops the project, giving each container `STOP_TIMEOUT_S`, and keeps its containers, network and volumes;
  with `--purge` it removes them (`down -v`). Either way `local/.env`, `git/` and the image stay.

Every Compose command names the project `PROJECT`, `<local>/nautobot` as its directory, `local/.env` as its env file
and the project's file, and runs with the three versions and the two directories set over the environment it inherits
and with no other name beginning `FYLGJA_NAUTOBOT_`, which Compose reads from `local/.env` alone. Exit 0, 1 for a
failure said on stderr, 2 for a command line not understood or a name of `NAMES` held with no value.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from http.client import HTTPException
from pathlib import Path

PROJECT = "fylgja-core-nautobot"
"""The Compose project; the spike's `fylgja-phase11-spike` is never named."""

ADDRESS = "http://127.0.0.1:8810"
"""Where the project's file publishes Nautobot on this host, and `FYLGJA_NAUTOBOT_ADDRESS`'s value."""

SUBNET = "203.0.113.0/24"
"""The project's network, a documentation range, which `compose.yml` names."""

SUPERUSER = "admin"
"""The superuser the image's entrypoint makes at the first start and keeps, whose token is the `WRITE_TOKEN` line."""

NAMES = (
    "FYLGJA_NAUTOBOT_SECRET_KEY",
    "FYLGJA_NAUTOBOT_DB_PASSWORD",
    "FYLGJA_NAUTOBOT_SUPERUSER_PASSWORD",
    "FYLGJA_NAUTOBOT_WRITE_TOKEN",
    "FYLGJA_NAUTOBOT_ADDRESS",
)
"""What `env` writes into `local/.env`: the three secrets and the superuser's token, then the address (D-042)."""

SECRETS = NAMES[:4]
WRITE_TOKEN = NAMES[3]
"""The superuser's API token, which Compose gives the image as `NAUTOBOT_SUPERUSER_API_TOKEN`: 40 lowercase hex."""
FIXED = {"FYLGJA_NAUTOBOT_ADDRESS": ADDRESS}

DEV = Path(__file__).resolve().parent.parent / "nautobot" / "dev"
"""The directory of the project's three files, beside this script's: the image's build context."""

UP_WAIT_S = 1200
"""How long `up` waits, from its first start, for `/health/` to answer 200: on new volumes, the slowest reading, 723.0 s
through the target after the purge, had it answering 720 s after `up -d` began, which this is 1.7 times
(design/verified-facts.md, "Nautobot 3.2.8 with Golden Config 3.0.8")."""

STATUS_WAIT_S = 60
"""How long `up` waits, from `/health/` answering, for `/api/status/` to name a running worker: a worker started was
counted 17 s after its start, which this is about 3.5 times (design/verified-facts.md)."""

POLL_S = 5
"""Seconds between two asks of Nautobot."""

STOP_TIMEOUT_S = 60
"""Seconds `down` gives each container to exit by itself before Docker kills it."""

REQUEST_TIMEOUT_S = 10
"""Seconds Nautobot is given to answer one request."""

ASSIGNMENT = re.compile(r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)")
QUOTED = re.compile(r"""\s*("[^"]*"|'[^']*')(?:\s+#.*)?""")
COMMENT = re.compile(r"\s#.*")
EMPTY = ("", '""', "''")
VERSION_FORM = re.compile(r"[0-9]+(?:\.[0-9A-Za-z]+)+")


@dataclass(frozen=True)
class Versions:
    """Nautobot's version, Golden Config's and the image's Python."""

    nautobot: str
    golden_config: str
    python: str


@dataclass(frozen=True)
class Status:
    """What `/api/status/` names: Nautobot's version, Golden Config's or None where it lists none, and
    `celery-workers-running`."""

    nautobot: str
    golden_config: str | None
    workers: int


class Refused(Exception):
    """Nautobot refuses the token it was asked with."""


Run = Callable[[Sequence[str], Mapping[str, str]], int]
Health = Callable[[str], int | None]
Info = Callable[[str, str], Status | None]


def say(line: str) -> None:
    print(f"nautobot_dev: {line}", flush=True)


def fail(line: str) -> int:
    print(f"nautobot_dev: {line}", file=sys.stderr, flush=True)
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


def assignments(held: bytes) -> dict[str, str]:
    """Each name the file's bytes hold and its value less its comment, the last line of a name where it has several,
    as a shell takes it; a commented line holds nothing."""
    values: dict[str, str] = {}
    for line in held.decode().splitlines():
        found = ASSIGNMENT.fullmatch(line.strip())
        if found:
            values[found[1]] = uncommented(found[2])
    return values


def replace_file(path: Path, data: bytes) -> None:
    """`path` written whole through a new file of mode 0600 beside it and a rename."""
    part = path.with_name(path.name + ".part")
    part.unlink(missing_ok=True)
    descriptor = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as out:
            out.write(data)
        part.replace(path)
    finally:
        part.unlink(missing_ok=True)


def write_env(path: Path) -> list[str]:
    """Add each of `NAMES` that `path` does not hold, and answer the names added, in `NAMES`' order.

    A name is held by a line `NAME=…` or `export NAME=…`, the last such line where there are several, as a shell
    takes it; a commented line holds nothing, and a value ends where an unquoted `#` begins a word. A name held with
    an empty value (`NAME=`, `NAME=""` or `NAME=''`, spaces aside) raises `NoValue` and the file is left untouched:
    kept, it would hand Compose an empty value, which the project's file refuses. `NAME= # a note` is refused too: a
    shell reads it as empty and Compose as the text `# a note`, two readers and two values. Every byte already in the
    file is kept, a newline added only where its last line has none. The three secrets are made by `secrets`, 64
    characters each, and the token is 40 hex characters. The file is left at mode 0600 whether or not anything was
    added.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    held = path.read_bytes() if path.exists() else b""
    values = assignments(held)
    empty = [name for name in NAMES if values.get(name) in EMPTY]
    if empty:
        raise NoValue(path, empty)
    added = [name for name in NAMES if name not in values]
    if added:
        new = {name: secrets.token_urlsafe(48) for name in SECRETS[:3]} | {WRITE_TOKEN: secrets.token_hex(20)} | FIXED
        ending = b"\n" if held and not held.endswith(b"\n") else b""
        replace_file(path, held + ending + "".join(f"{name}={new[name]}\n" for name in added).encode())
    path.chmod(0o600)
    return added


def held(path: Path, name: str) -> str | None:
    """The value `path` holds for `name`, as a shell reads it, its quotes taken off; None where it holds none."""
    if not path.exists():
        return None
    value = assignments(path.read_bytes()).get(name)
    if value is not None and len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def report_env(path: Path, added: Sequence[str]) -> None:
    if added:
        say(f"{path}: added {', '.join(added)}")
    else:
        say(f"{path}: holds every name already; nothing written")


def compose(local: Path, dev: Path) -> list[str]:
    """The Compose command, less its verb: the project, `<local>/nautobot` as its directory, `local/.env` and the
    project's file."""
    return [
        "docker",
        "compose",
        "-p",
        PROJECT,
        "--project-directory",
        str(local / "nautobot"),
        "--env-file",
        str(local / ".env"),
        "-f",
        str(dev / "compose.yml"),
    ]


def compose_env(versions: Versions, dev: Path, git: Path, base: Mapping[str, str]) -> dict[str, str]:
    """Compose's environment: `base` less every name beginning `FYLGJA_NAUTOBOT_` and Golden Config's version, with
    the three versions and the two directories, `dev` and `git`, set.

    Compose takes a variable of its own environment over `--env-file`'s. So the versions are the make variables'
    whatever the shell or `local/.env` holds, and a secret exported in the shell, set or empty, is left out, so that
    Compose reads each from `local/.env` alone: a password or a key the file does not hold would initialise a new
    database the file cannot open.
    """
    kept = {
        name: value
        for name, value in base.items()
        if not name.startswith("FYLGJA_NAUTOBOT_") and name != "FYLGJA_GOLDEN_CONFIG_VERSION"
    }
    return kept | {
        "FYLGJA_NAUTOBOT_VERSION": versions.nautobot,
        "FYLGJA_GOLDEN_CONFIG_VERSION": versions.golden_config,
        "FYLGJA_NAUTOBOT_PYTHON": versions.python,
        "FYLGJA_NAUTOBOT_DEV": str(dev),
        "FYLGJA_NAUTOBOT_GIT": str(git),
    }


def up(
    local: Path,
    versions: Versions,
    *,
    dev: Path,
    run: Run,
    health: Health,
    info: Info,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
) -> int:
    """Write `local/.env`'s missing names, make the served directory, build, start, wait for `/health/` and settle
    the status.

    0 once Nautobot names both versions and a running worker; 1 for a failure; 2, with nothing built or started,
    where `local/.env` holds one of `NAMES` with no value. A start that exits non-zero is 1 at once: nothing was read
    to fail on a first start where a second would mend it.
    """
    env = local / ".env"
    try:
        added = write_env(env)
    except NoValue as e:
        fail(str(e))
        return 2
    report_env(env, added)
    dev = dev.absolute()
    git = local / "nautobot" / "git"
    git.mkdir(parents=True, exist_ok=True)

    base = compose(local, dev)
    environment = compose_env(versions, dev, git, os.environ)
    status = run([*base, "build", "nautobot"], environment)
    if status != 0:
        return fail(f"`docker compose build nautobot` of {PROJECT} exited {status}")
    started = clock()
    status = run([*base, "up", "-d", "--quiet-pull"], environment)
    if status != 0:
        return fail(f"`docker compose up -d` of {PROJECT} exited {status}")
    healthy = wait_healthy(health=health, clock=clock, sleep=sleep, started=started)
    if healthy is None:
        return 1
    return settle(env, versions, dev, info=info, clock=clock, sleep=sleep, healthy=healthy)


def wait_healthy(
    *, health: Health, clock: Callable[[], float], sleep: Callable[[float], None], started: float
) -> float | None:
    """Ask `/health/` every `POLL_S` until it answers 200, and answer the clock's reading then; None, said on stderr,
    once `UP_WAIT_S` has passed since `started`."""
    while True:
        said = health(ADDRESS)
        waited = clock() - started
        if said == 200:
            say(f"{ADDRESS}/health/ answered 200 {waited:.0f} s after the start")
            return clock()
        if waited >= UP_WAIT_S:
            fail(
                f"{ADDRESS}/health/ did not answer 200 within {UP_WAIT_S} s of the start (it answered "
                f"{said if said is not None else 'nothing'}); read `docker compose -p {PROJECT} logs nautobot`"
            )
            return None
        sleep(POLL_S)


def named(status: Status) -> str:
    app = f"nautobot_golden_config {status.golden_config}" if status.golden_config is not None else "no Golden Config"
    return f"Nautobot {status.nautobot} with {app}"


def settle(
    env: Path,
    versions: Versions,
    dev: Path,
    *,
    info: Info,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    healthy: float,
) -> int:
    """Read `/api/status/` with `local/.env`'s `WRITE_TOKEN` every `POLL_S` until it names both versions and a
    running worker (0), another Nautobot, another Golden Config or none (1, at once), or `STATUS_WAIT_S` passes from
    `healthy` (1).

    The image's entrypoint takes the line's token and password at each start, so a refusal is no changed line: it is
    something else, and no second try is made. The remedy is a purge, which removes the volumes.
    """
    token = held(env, WRITE_TOKEN) or ""
    while True:
        try:
            status = info(ADDRESS, token)
        except Refused:
            return fail(
                f"Nautobot refuses the token {env} holds as {WRITE_TOKEN}, though its entrypoint takes the line at "
                f"each start: read `docker compose -p {PROJECT} logs nautobot`, or `make nautobot-down PURGE=1` "
                f"removes the volumes, and the next `make nautobot-up` starts an empty Nautobot"
            )
        if status is not None:
            if status.nautobot != versions.nautobot or status.golden_config not in (None, versions.golden_config):
                expected = named(Status(versions.nautobot, versions.golden_config, 1))
                return fail(f"{ADDRESS} answers {named(status)}, not {expected}")
            if status.golden_config is None:
                return fail(
                    f"{ADDRESS} answers {named(status)}: nautobot_golden_config is not among its apps, so "
                    f"{dev / 'nautobot_config.py'} was not loaded, or the image lacks the app"
                )
            if status.workers > 0:
                say(f"{named(status)} answers at {ADDRESS}, {status.workers} worker(s) running")
                return 0
        if clock() - healthy >= STATUS_WAIT_S:
            if status is None:
                return fail(f"{ADDRESS}/api/status/ did not answer within {STATUS_WAIT_S} s of /health/ answering")
            return fail(
                f"no worker ran within {STATUS_WAIT_S} s of /health/ answering, and without one no job runs; "
                f"read `docker compose -p {PROJECT} logs worker`"
            )
        sleep(POLL_S)


def down(local: Path, versions: Versions, *, dev: Path, purge: bool, run: Run) -> int:
    """Stop the project, or with `purge` remove its containers, network and volumes. 0 or 1.

    The stop gives each container `STOP_TIMEOUT_S` to exit by itself. A purge takes Compose's own timeout: what it
    would kill is removed with its volumes.
    """
    dev = dev.absolute()
    verb = ["down", "-v"] if purge else ["stop", "--timeout", str(STOP_TIMEOUT_S)]
    environment = compose_env(versions, dev, local / "nautobot" / "git", os.environ)
    status = run([*compose(local, dev), *verb], environment)
    if status != 0:
        return fail(f"`docker compose {' '.join(verb)}` of {PROJECT} exited {status}")
    if purge:
        say(
            f"{PROJECT} removed with its volumes; local/.env, git/ and the image are kept, and the next "
            f"`make nautobot-up` starts an empty Nautobot with the same token"
        )
    else:
        say(f"{PROJECT} stopped; its containers, network and volumes are kept")
    return 0


def run_compose(argv: Sequence[str], env: Mapping[str, str]) -> int:
    return subprocess.run(list(argv), env=dict(env), check=False).returncode


def ask_health(address: str) -> int | None:
    """The status `GET <address>/health/` answers, an error status too; None where nothing answers."""
    try:
        with urllib.request.urlopen(f"{address}/health/", timeout=REQUEST_TIMEOUT_S) as response:
            return int(response.status)
    except urllib.error.HTTPError as e:
        e.close()
        return e.code
    except (OSError, HTTPException):
        return None


def ask_status(address: str, token: str) -> Status | None:
    """What `<address>/api/status/` names, asked with `token`; `Refused` where Nautobot answers 403, as it does a
    request with a token it never made or none, and None where it answers nothing readable."""
    request = urllib.request.Request(
        f"{address}/api/status/", headers={"Authorization": f"Token {token}", "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
            body = json.load(response)
    except urllib.error.HTTPError as e:
        e.close()
        if e.code == 403:
            raise Refused(f"{address}/api/status/ answered 403: Nautobot refuses the token") from None
        return None
    except (OSError, HTTPException, ValueError):
        return None
    if not isinstance(body, dict):
        return None
    nautobot, apps = body.get("nautobot-version"), body.get("nautobot-apps")
    workers = body.get("celery-workers-running")
    if not isinstance(nautobot, str) or not isinstance(apps, dict) or type(workers) is not int:
        return None
    golden = apps.get("nautobot_golden_config")
    return Status(nautobot, golden if isinstance(golden, str) else None, workers)


def parser() -> argparse.ArgumentParser:
    made = argparse.ArgumentParser(prog="nautobot_dev.py", description=(__doc__ or "").splitlines()[0])
    verbs = made.add_subparsers(dest="verb", required=True)
    env = verbs.add_parser("env", help="add local/.env's missing names")
    env.add_argument("--local", type=Path, required=True, help="the main checkout's local/")
    for verb in ("up", "down"):
        each = verbs.add_parser(verb, help=f"{verb} the Compose project {PROJECT}")
        each.add_argument("--local", type=Path, required=True, help="the main checkout's local/")
        each.add_argument("--nautobot", required=True, help="Nautobot's version")
        each.add_argument("--golden-config", required=True, help="Golden Config's version")
        each.add_argument("--python", required=True, help="the image's Python, its minor version")
        if verb == "down":
            each.add_argument("--purge", action="store_true", help="remove the containers, network and volumes")
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
        for flag in ("nautobot", "golden_config", "python"):
            if not VERSION_FORM.fullmatch(getattr(args, flag)):
                print(
                    f"nautobot_dev: --{flag.replace('_', '-')} {getattr(args, flag)!r} is not a version",
                    file=sys.stderr,
                )
                return 2
        versions = Versions(args.nautobot, args.golden_config, args.python)
        if args.verb == "up":
            return up(
                local,
                versions,
                dev=DEV,
                run=run_compose,
                health=ask_health,
                info=ask_status,
                clock=time.monotonic,
                sleep=time.sleep,
            )
        return down(local, versions, dev=DEV, purge=args.purge, run=run_compose)
    except (OSError, HTTPException) as e:
        return fail(f"{args.verb}: {e}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
