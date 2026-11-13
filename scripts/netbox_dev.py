#!/usr/bin/env python3
"""The development host's NetBox: its lines in `local/.env`, and its Compose project up, stopped and purged.

Run from the repository root as `python3 -I scripts/netbox_dev.py env|up|down ...`, by `make netbox-up` and
`make netbox-down` (CONTRIBUTING.md, D-096). The standard library alone; no script imports another.

- `env --local <local>` adds to `<local>/.env` each of `NAMES` it does not hold, generated, and prints the names it
  added and never a value. A line already there is kept byte for byte: a pepper made again would refuse every token
  a kept database holds, and a password made again would not be the superuser's. A name the file holds with an empty
  value is refused, exit 2, the file untouched.
- `up` does `env`; fetches netbox-docker's release for its version once into `<local>/netbox/`; where the project's
  network stands with another subnet than the override's, removes its containers and network and keeps its volumes,
  so that the start makes the network again (what Compose's `up` alone does to such a network was not read), and
  where the network could not be inspected says so in one line and goes on; builds the plugin's image from the
  override's directory; starts the project and waits for Docker to call `netbox` healthy, then asks
  Compose once more where the first start failed, since Compose gives up on the worker while NetBox migrates. It
  then reads `/api/status/` with the superuser's token, the line `WRITE_TOKEN` of `local/.env`, provisioning one and
  writing that line where the file holds none or NetBox refuses it, and is done once NetBox names its version, the
  plugin's and a running worker: without a worker no branch is ever ready.
- `down` stops the project, giving each container `STOP_TIMEOUT_S`, and keeps its containers, network and volumes;
  with `--purge` it removes them (`down -v`). Either way `local/.env`, the release and the image stay.

Every Compose command names the project `PROJECT`, the release as its directory, `local/.env` as its env file, the
release's file and the override, and runs with the three versions and the override's directory set over the
environment it inherits and with no other name beginning `FYLGJA_NETBOX_`, which Compose reads from `local/.env`
alone. Exit 0, 1 for a failure said on stderr, 2 for a command line not understood or a name of `NAMES` held with no
value.
"""

from __future__ import annotations

import argparse
import io
import ipaddress
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from http.client import HTTPException
from pathlib import Path

PROJECT = "fylgja-core-netbox"
"""The Compose project; the spike's `fylgja-netbox` is never named."""

RELEASE_URL = "https://github.com/netbox-community/netbox-docker/archive/refs/tags/{version}.tar.gz"
"""netbox-docker's release of a version, GitHub's archive of its tag, fetched once and never vendored or changed."""

ADDRESS = "http://127.0.0.1:8800"
"""Where the override publishes NetBox on this host, and `FYLGJA_NETBOX_ADDRESS`'s value."""

SUPERUSER = "admin"
"""The superuser the override has netbox-docker make at the first start, whose token `up` provisions."""

NAMES = (
    "FYLGJA_NETBOX_SUPERUSER_PASSWORD",
    "FYLGJA_NETBOX_SECRET_KEY",
    "FYLGJA_NETBOX_API_TOKEN_PEPPER",
    "FYLGJA_NETBOX_ADDRESS",
)
"""What `env` writes into `local/.env`: the override's three secrets, then the address (D-042)."""

SECRETS = NAMES[:3]
FIXED = {"FYLGJA_NETBOX_ADDRESS": ADDRESS}

WRITE_TOKEN = "FYLGJA_NETBOX_WRITE_TOKEN"
"""The superuser's token, as NetBox presents it (`nbt_<key>.<token>`), which `up` writes once NetBox answers."""

UP_WAIT_S = 1200
"""How long `up` waits, from its first start, for Docker to call `netbox` healthy: on new volumes it read healthy
748.7 s after `up -d` began, which this is 1.6 times (design/verified-facts.md, "NetBox 4.7.5 with netbox-branching
1.2.3"); the archived repository read 653 s on 4.7.4."""

STATUS_WAIT_S = 60
"""How long `up` waits, from `netbox` healthy, for `/api/status/` to answer with a running worker: a worker started
was counted about 16 s after its start (design/verified-facts.md)."""

POLL_S = 5
"""Seconds between two asks of Docker or of `/api/status/`."""

STOP_TIMEOUT_S = 60
"""Seconds `down` gives each container to exit by itself before Docker kills it. Under Compose's own 10 s every
container exited 0, the stop whole in 10.6 s (design/verified-facts.md)."""

FETCH_TIMEOUT_S = 60
"""Seconds the release's server is given to answer the fetch."""

REQUEST_TIMEOUT_S = 10
"""Seconds NetBox is given to answer one request: provisioning a token took 1.68 s (design/verified-facts.md)."""

PS_TIMEOUT_S = 60
"""Seconds `docker compose ps` is given to answer one ask."""

INSPECT_TIMEOUT_S = 60
"""Seconds `docker network inspect` is given to answer."""

NETWORK = f"{PROJECT}_default"
"""The project's one network, Compose's default, as Docker names it."""

SUBNET = "198.51.100.0/24"
"""The override's subnet for `NETWORK`: a documentation range, outside the private ranges Docker takes its networks'
subnets from, so that it never meets the local driver's lab pool (core/src/fylgja_core/containerlab/pool.py) nor a
network Docker gives itself."""

RECREATE = ["down", "--timeout", str(STOP_TIMEOUT_S)]
"""Compose's verb that removes the project's containers and network and keeps its volumes, each container given
`STOP_TIMEOUT_S` to exit as `down` gives it."""

ASSIGNMENT = re.compile(r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)")
QUOTED = re.compile(r"""\s*("[^"]*"|'[^']*')(?:\s+#.*)?""")
COMMENT = re.compile(r"\s#.*")
EMPTY = ("", '""', "''")
VERSION_FORM = re.compile(r"[0-9]+(?:\.[0-9A-Za-z]+)+")


@dataclass(frozen=True)
class Versions:
    """NetBox's version, netbox-docker's and the branching plugin's."""

    netbox: str
    docker: str
    branching: str


@dataclass(frozen=True)
class Status:
    """What `/api/status/` names: NetBox's version, the branching plugin's or None where it lists none, and
    `rq-workers-running`."""

    netbox: str
    branching: str | None
    workers: int


class Refused(Exception):
    """NetBox refuses the token it was asked with."""


class Uninspected(Exception):
    """Docker's inspection of a network gave no answer that tells its subnets or that it does not stand."""


Run = Callable[[Sequence[str], Mapping[str, str]], int]
Fetch = Callable[[str, Path], None]
Network = Callable[[str], list[str] | None]
Health = Callable[[Sequence[str], Mapping[str, str]], str | None]
Info = Callable[[str, str], Status | None]
Provision = Callable[[str, str, str], str | None]


def say(line: str) -> None:
    print(f"netbox_dev: {line}", flush=True)


def fail(line: str) -> int:
    print(f"netbox_dev: {line}", file=sys.stderr, flush=True)
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
    kept, it would hand Compose an empty value, which the override refuses. `NAME= # a note` is refused too: a shell
    reads it as empty and Compose as the text `# a note`, two readers and two values. Every byte already in the file
    is kept, a newline added only where its last line has none. The three secrets are made by `secrets`, 64
    characters each. The file is left at mode 0600 whether or not anything was added.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    held = path.read_bytes() if path.exists() else b""
    values = assignments(held)
    empty = [name for name in NAMES if values.get(name) in EMPTY]
    if empty:
        raise NoValue(path, empty)
    added = [name for name in NAMES if name not in values]
    if added:
        new = {name: secrets.token_urlsafe(48) for name in SECRETS} | FIXED
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


def set_line(path: Path, name: str, value: str) -> None:
    """`NAME=value` in `path`: the line that holds the name replaced, the last of them where there are several, or
    the line appended where none does; every other byte kept, and the file left at mode 0600, written by a rename."""
    data = path.read_bytes() if path.exists() else b""
    lines = data.splitlines(keepends=True)
    holding = [
        number
        for number, line in enumerate(lines)
        if (found := ASSIGNMENT.fullmatch(line.decode().strip())) and found[1] == name
    ]
    written = f"{name}={value}".encode()
    if holding:
        line = lines[holding[-1]]
        lines[holding[-1]] = written + line[len(line.rstrip(b"\r\n")) :]
    else:
        if lines and not lines[-1].endswith((b"\n", b"\r")):
            lines[-1] += b"\n"
        lines.append(written + b"\n")
    replace_file(path, b"".join(lines))
    path.chmod(0o600)


def report_env(path: Path, added: Sequence[str]) -> None:
    if added:
        say(f"{path}: added {', '.join(added)}")
    else:
        say(f"{path}: holds every name already; nothing written")


def release(local: Path, versions: Versions) -> Path:
    """Where netbox-docker's release is unpacked: `<local>/netbox/netbox-docker-<its version>`."""
    return local / "netbox" / f"netbox-docker-{versions.docker}"


def compose(local: Path, versions: Versions, override: Path) -> list[str]:
    """The Compose command, less its verb: the project, the release as its directory, `local/.env` and both files."""
    found = release(local, versions)
    return [
        "docker",
        "compose",
        "-p",
        PROJECT,
        "--project-directory",
        str(found),
        "--env-file",
        str(local / ".env"),
        "-f",
        str(found / "docker-compose.yml"),
        "-f",
        str(override),
    ]


def compose_env(versions: Versions, dev: Path, base: Mapping[str, str]) -> dict[str, str]:
    """Compose's environment: `base` less every name beginning `FYLGJA_NETBOX_`, with the three versions and the
    override's directory, `dev`, set.

    Compose takes a variable of its own environment over `--env-file`'s. So the versions are the make variables'
    whatever the shell or `local/.env` holds, and a secret exported in the shell, set or empty, is left out, so that
    Compose reads each from `local/.env` alone: a pepper or a password the file does not hold would initialise a new
    database the file cannot open. No token reaches Compose either: the override reads none.
    """
    kept = {name: value for name, value in base.items() if not name.startswith("FYLGJA_NETBOX_")}
    return kept | {
        "FYLGJA_NETBOX_VERSION": versions.netbox,
        "FYLGJA_NETBOX_DOCKER_VERSION": versions.docker,
        "FYLGJA_NETBOX_BRANCHING_VERSION": versions.branching,
        "FYLGJA_NETBOX_DEV": str(dev),
    }


def ipv4(subnets: Sequence[str]) -> list[str]:
    """The IPv4 subnets among `subnets`, as Docker writes them; a subnet that does not read is kept, as no IPv6 one."""
    kept = []
    for subnet in subnets:
        try:
            if ipaddress.ip_network(subnet, strict=False).version == 6:
                continue
        except ValueError:
            pass
        kept.append(subnet)
    return kept


def up(
    local: Path,
    versions: Versions,
    override: Path,
    *,
    run: Run,
    fetch: Fetch,
    network: Network,
    health: Health,
    info: Info,
    provision: Provision,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
) -> int:
    """Write `local/.env`'s missing names, fetch the release, recreate a network of another subnet, build, start,
    wait, and settle the token.

    What Compose's `up` alone does to a standing network whose subnet the override changes was not read. So where
    `network` answers `NETWORK`'s subnets and its IPv4 ones are not `SUBNET` alone, the project's containers and
    network are removed by `RECREATE`, the volumes kept, and the start makes the network again, its failure then
    naming `SUBNET`; where it answers None, for a network that does not stand, nothing more is done; and where it
    raises `Uninspected` one line says so, naming `SUBNET`, and `up` goes on as for a network that does not stand.

    0 once NetBox names both versions and a running worker; 1 for a failure; 2, with nothing fetched, built or
    started, where `local/.env` holds one of `NAMES` with no value.
    """
    env = local / ".env"
    try:
        added = write_env(env)
    except NoValue as e:
        fail(str(e))
        return 2
    report_env(env, added)
    override = override.absolute()

    found = release(local, versions)
    if found.is_dir():
        say(f"{found} is there")
    else:
        url = RELEASE_URL.format(version=versions.docker)
        part = found.with_name(found.name + ".part")
        shutil.rmtree(part, ignore_errors=True)
        try:
            fetch(url, part)
            part.replace(found)
        except (OSError, HTTPException, tarfile.TarError) as e:
            return fail(f"fetching {url} failed: {e}")
        finally:
            shutil.rmtree(part, ignore_errors=True)
        say(f"fetched {url} into {found}")

    base = compose(local, versions, override)
    environment = compose_env(versions, override.parent, os.environ)
    try:
        subnets = network(NETWORK)
    except Uninspected as e:
        say(
            f"{NETWORK} could not be inspected ({e}): going on as for a network that does not stand; once NetBox is "
            f"up, `docker network inspect {NETWORK}` should name the override's {SUBNET} alone"
        )
        subnets = None
    recreated = subnets is not None and ipv4(subnets) != [SUBNET]
    if recreated:
        say(
            f"{NETWORK} stands with {', '.join(subnets or []) or 'no subnet'}, not the override's {SUBNET}: removing "
            f"{PROJECT}'s containers and network, its volumes kept, so that the start makes the network again"
        )
        status = run([*base, *RECREATE], environment)
        if status != 0:
            return fail(f"`docker compose {' '.join(RECREATE)}` of {PROJECT} exited {status}")
    status = run([*base, "build", "netbox"], environment)
    if status != 0:
        return fail(f"`docker compose build netbox` of {PROJECT} exited {status}")
    argv = [*base, "up", "-d", "--quiet-pull"]
    started = clock()
    first = run(argv, environment)
    if first != 0:
        after = (
            f", after its network was removed to be made again with the override's {SUBNET}: where another network "
            f"holds that range, `docker network ls` names it"
            if recreated
            else ""
        )
        say(f"the first start of {PROJECT} exited {first}{after}; waiting for Docker to call netbox healthy")
    healthy = wait_healthy(base, environment, health=health, clock=clock, sleep=sleep, started=started)
    if healthy is None:
        return 1
    if first != 0:
        say(f"asking Compose once more to start {PROJECT}, its worker among it")
        second = run(argv, environment)
        if second != 0:
            return fail(f"the second start of {PROJECT} exited {second}")
    return settle(
        env, versions, override.parent, info=info, provision=provision, clock=clock, sleep=sleep, healthy=healthy
    )


def wait_healthy(
    base: Sequence[str],
    environment: Mapping[str, str],
    *,
    health: Health,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    started: float,
) -> float | None:
    """Ask Docker every `POLL_S` until it calls `netbox` healthy, and answer the clock's reading then; None, said on
    stderr, once `UP_WAIT_S` has passed since `started`."""
    while True:
        said = health(base, environment)
        waited = clock() - started
        if said == "healthy":
            say(f"netbox healthy {waited:.0f} s after its start")
            return clock()
        if waited >= UP_WAIT_S:
            fail(
                f"netbox was not healthy within {UP_WAIT_S} s of its start (Docker read {said or 'no container'}); "
                f"read `docker compose -p {PROJECT} logs netbox`"
            )
            return None
        sleep(POLL_S)


def named(status: Status) -> str:
    plugin = f"netbox_branching {status.branching}" if status.branching is not None else "no netbox_branching"
    return f"NetBox {status.netbox} with {plugin}"


def settle(
    env: Path,
    versions: Versions,
    dev: Path,
    *,
    info: Info,
    provision: Provision,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    healthy: float,
) -> int:
    """Read `/api/status/` with `local/.env`'s `WRITE_TOKEN` every `POLL_S` until it names both versions and a
    running worker (0), another NetBox, another plugin or none (1, at once), or `STATUS_WAIT_S` passes from
    `healthy` (1).

    Where the file holds no token, or NetBox refuses the one it holds (a purge keeps `local/.env`, and its token line
    is then of the instance before), the superuser's is provisioned once with the file's password and its line
    written. A password NetBox refuses is the volumes' of another file, and only a purge mends it.
    """
    token = held(env, WRITE_TOKEN) or None
    provisioned = False
    while True:
        if token is None:
            password = held(env, NAMES[0])
            made = provision(ADDRESS, SUPERUSER, password) if password else None
            if made is None:
                return fail(
                    f"NetBox refuses {SUPERUSER}'s password from {env}: its volumes were made with another one; "
                    f"`make netbox-down PURGE=1` removes them, and the next `make netbox-up` starts an empty NetBox"
                )
            set_line(env, WRITE_TOKEN, made)
            say(f"{env}: {WRITE_TOKEN} written, {SUPERUSER}'s token as NetBox provisioned it")
            token, provisioned = made, True
        try:
            status = info(ADDRESS, token)
        except Refused:
            if provisioned:
                return fail(f"NetBox refuses the token it has just provisioned for {SUPERUSER}")
            say(f"NetBox refuses the token {env} holds as {WRITE_TOKEN}; provisioning {SUPERUSER}'s again")
            token = None
            continue
        if status is not None:
            if status.netbox != versions.netbox or status.branching not in (None, versions.branching):
                expected = named(Status(versions.netbox, versions.branching, 1))
                return fail(f"{ADDRESS} answers {named(status)}, not {expected}")
            if status.branching is None:
                return fail(
                    f"{ADDRESS} answers {named(status)}: {dev / 'plugins.py'} was not loaded, "
                    f"or the image lacks the plugin"
                )
            if status.workers > 0:
                say(f"{named(status)} answers at {ADDRESS}, {status.workers} worker(s) running")
                return 0
        if clock() - healthy >= STATUS_WAIT_S:
            if status is None:
                return fail(f"{ADDRESS}/api/status/ did not answer within {STATUS_WAIT_S} s of netbox healthy")
            return fail(
                f"no netbox-worker ran within {STATUS_WAIT_S} s of netbox healthy, and without one no branch is ever "
                f"ready; read `docker compose -p {PROJECT} logs netbox-worker`"
            )
        sleep(POLL_S)


def down(local: Path, versions: Versions, override: Path, *, purge: bool, run: Run) -> int:
    """Stop the project, or with `purge` remove its containers, network and volumes. 0 or 1.

    The stop gives each container `STOP_TIMEOUT_S` to exit by itself. A purge takes Compose's own timeout: what it
    would kill is removed with its volumes.
    """
    override = override.absolute()
    verb = ["down", "-v"] if purge else ["stop", "--timeout", str(STOP_TIMEOUT_S)]
    status = run([*compose(local, versions, override), *verb], compose_env(versions, override.parent, os.environ))
    if status != 0:
        return fail(f"`docker compose {' '.join(verb)}` of {PROJECT} exited {status}")
    if purge:
        say(
            f"{PROJECT} removed with its volumes; local/.env, the release and the image are kept, and the next "
            f"`make netbox-up` provisions {WRITE_TOKEN} again"
        )
    else:
        say(f"{PROJECT} stopped; its containers, network and volumes are kept")
    return 0


def run_compose(argv: Sequence[str], env: Mapping[str, str]) -> int:
    return subprocess.run(list(argv), env=dict(env), check=False).returncode


def health_of(printed: str) -> str | None:
    """What `docker compose ps --format json` says of `netbox`'s health, from its rows, a JSON array or a row a line;
    None where no row is `netbox`'s or nothing readable was printed."""
    text = printed.strip()
    try:
        rows = json.loads(text) if text.startswith("[") else [json.loads(line) for line in text.splitlines() if line]
    except ValueError:
        return None
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and row.get("Service") == "netbox":
            said = row.get("Health")
            return said if isinstance(said, str) and said else None
    return None


def compose_health(base: Sequence[str], env: Mapping[str, str]) -> str | None:
    """Docker's word on `netbox`'s health: `starting`, `healthy` or `unhealthy`, or None where no container of it
    runs or Compose answers nothing readable."""
    try:
        done = subprocess.run(
            [*base, "ps", "--format", "json", "netbox"],
            env=dict(env),
            capture_output=True,
            text=True,
            check=False,
            timeout=PS_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return None
    return health_of(done.stdout) if done.returncode == 0 else None


def network_subnets(name: str) -> list[str] | None:
    """The subnets of the Docker network `name`, as `docker network inspect` answers its IPAM configuration; None where
    Docker says it finds no such network (`not found`, `No such network`). `Uninspected`, naming why, where it does
    not answer in `INSPECT_TIMEOUT_S`, exits non-zero otherwise, or prints what does not read as a list."""
    try:
        done = subprocess.run(
            ["docker", "network", "inspect", "--format", "{{json .IPAM.Config}}", name],
            capture_output=True,
            text=True,
            check=False,
            timeout=INSPECT_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as e:
        raise Uninspected(f"`docker network inspect` did not answer within {INSPECT_TIMEOUT_S} s") from e
    if done.returncode != 0:
        said = done.stderr.strip()
        if "not found" in said.lower() or "no such network" in said.lower():
            return None
        first = said.splitlines()[0][:200] if said else "nothing on stderr"
        raise Uninspected(f"`docker network inspect` exited {done.returncode}: {first}")
    try:
        configs = json.loads(done.stdout)
    except ValueError as e:
        raise Uninspected("`docker network inspect`'s answer did not read as JSON") from e
    if configs is not None and not isinstance(configs, list):
        raise Uninspected("`docker network inspect`'s answer did not read as a list of IPAM configurations")
    return [
        config["Subnet"]
        for config in configs or []
        if isinstance(config, dict) and isinstance(config.get("Subnet"), str) and config["Subnet"]
    ]


def fetch_release(url: str, dest: Path) -> None:
    """The archive at `url` unpacked as the directory `dest`, its one top directory stripped, by `tarfile` with the
    `data` filter. urllib sends its own User-Agent, which the archive answered (design/verified-facts.md)."""
    with urllib.request.urlopen(urllib.request.Request(url), timeout=FETCH_TIMEOUT_S) as response:
        packed = response.read()
    with tarfile.open(fileobj=io.BytesIO(packed), mode="r:gz") as tar:
        members = tar.getmembers()
        tops = {member.name.split("/", 1)[0] for member in members}
        if len(tops) != 1:
            raise tarfile.TarError(f"{url} holds {len(tops)} top entries, not one directory")
        [top] = tops
        inner = []
        for member in members:
            if member.name == top:
                if not member.isdir():
                    raise tarfile.TarError(f"{url} holds {top} as no directory")
                continue
            member.name = member.name.removeprefix(f"{top}/")
            if member.islnk():
                member.linkname = member.linkname.removeprefix(f"{top}/")
            inner.append(member)
        dest.mkdir(parents=True)
        tar.extractall(dest, members=inner, filter="data")


def ask_status(address: str, token: str) -> Status | None:
    """What `<address>/api/status/` names, asked with `token`; `Refused` where NetBox answers 403, as it does a token
    it never made, and None where it answers nothing readable."""
    request = urllib.request.Request(
        f"{address}/api/status/", headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
            body = json.load(response)
    except urllib.error.HTTPError as e:
        e.close()
        if e.code == 403:
            raise Refused(f"{address}/api/status/ answered 403: NetBox refuses the token") from None
        return None
    except (OSError, HTTPException, ValueError):
        return None
    if not isinstance(body, dict):
        return None
    netbox, plugins, workers = body.get("netbox-version"), body.get("plugins"), body.get("rq-workers-running")
    if not isinstance(netbox, str) or not isinstance(plugins, dict) or type(workers) is not int:
        return None
    branching = plugins.get("netbox_branching")
    return Status(netbox, branching if isinstance(branching, str) else None, workers)


def provision_token(address: str, user: str, password: str) -> str | None:
    """A token of `user`'s, provisioned with its password and answered as NetBox presents it, `nbt_<key>.<token>`;
    None where NetBox refuses the password (403). Nothing is printed, and no error holds the password or a token."""
    url = f"{address}/api/users/tokens/provision/"
    request = urllib.request.Request(
        url,
        data=json.dumps({"username": user, "password": password}).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
            answer = json.load(response)
    except urllib.error.HTTPError as e:
        e.close()
        if e.code == 403:
            return None
        raise OSError(f"{url} answered {e.code}") from None
    except ValueError:
        raise OSError(f"{url} answered no JSON") from None
    key = answer.get("key") if isinstance(answer, dict) else None
    token = answer.get("token") if isinstance(answer, dict) else None
    if not isinstance(key, str) or not isinstance(token, str) or not key or not token:
        raise OSError(f"{url} answered no key and token")
    return f"nbt_{key}.{token}"


def parser() -> argparse.ArgumentParser:
    made = argparse.ArgumentParser(prog="netbox_dev.py", description=(__doc__ or "").splitlines()[0])
    verbs = made.add_subparsers(dest="verb", required=True)
    env = verbs.add_parser("env", help="add local/.env's missing names")
    env.add_argument("--local", type=Path, required=True, help="the main checkout's local/")
    for verb in ("up", "down"):
        each = verbs.add_parser(verb, help=f"{verb} the Compose project {PROJECT}")
        each.add_argument("--local", type=Path, required=True, help="the main checkout's local/")
        each.add_argument("--netbox", required=True, help="NetBox's version")
        each.add_argument("--docker", required=True, help="netbox-docker's version")
        each.add_argument("--branching", required=True, help="netbox-branching's version")
        each.add_argument("--override", type=Path, required=True, help="the Compose override, in netbox/dev/")
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
        for flag in ("netbox", "docker", "branching"):
            if not VERSION_FORM.fullmatch(getattr(args, flag)):
                print(f"netbox_dev: --{flag} {getattr(args, flag)!r} is not a version", file=sys.stderr)
                return 2
        versions = Versions(args.netbox, args.docker, args.branching)
        override = args.override.absolute()
        if args.verb == "up":
            return up(
                local,
                versions,
                override,
                run=run_compose,
                fetch=fetch_release,
                network=network_subnets,
                health=compose_health,
                info=ask_status,
                provision=provision_token,
                clock=time.monotonic,
                sleep=time.sleep,
            )
        return down(local, versions, override, purge=args.purge, run=run_compose)
    except (OSError, HTTPException) as e:
        return fail(f"{args.verb}: {e}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
