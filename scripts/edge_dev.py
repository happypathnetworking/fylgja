#!/usr/bin/env python3
"""The example orchestrator's edge on the development host: its lines in `local/.env`, its Prefect server, its runner.

Run from the repository root as `python3 -I scripts/edge_dev.py env|prefect-up|prefect-down|serve --local <local>
--main <main checkout>`, by `make orchestrator-env`, `make prefect-up`, `make prefect-down` and `make
orchestrator-serve`, with `local/.env` loaded by the caller (CONTRIBUTING.md, "Running the example orchestrator";
D-085). The standard library alone.

- `env` adds to `<local>/.env` each of `ENV_NAMES` it does not hold, generated where it is a secret, and prints each
  name it added and never a value: the basic auth the server and the task workers share, the runner's token of the
  core's, whose hash it appends with the principal `orchestrator` to the token file `FYLGJA_TOKENS` names, a file
  the core reads and this never makes, the scope (`seed.json`'s, else `seed.py`'s), the reader document and the
  commands' records. A line already there is kept byte for byte. The example's Infrahub token is
  `infrahub/seed/account.py`'s, which `make orchestrator-env` runs next.
- `prefect-up` starts `prefect server start` on port `PORT` of the bind address, `PREFECT_BIND` or else the Docker
  bridge's gateway, in a session of its own under `<local>/prefect`, its basic auth from the environment and never an
  argument, and waits for `/api/health`. A listener already on the port that this target did not start is refused,
  and nothing is started or stopped: it is another project's.
- `prefect-down` ends the process `<local>/prefect/server.pid` names, only where it is this project's Prefect server
  (its command line `prefect` and `server`, its `PREFECT_HOME` `<local>/prefect`), and touches no other process.
- `serve` becomes `fylgja-orchestrator serve`, given the runner's own environment (`runner_env`) and no other.

Exit 0; 1 for a failure or a refusal said on stderr; 2 for a command line not understood or a name not set.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from http.client import HTTPException
from pathlib import Path
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parent.parent
"""The checkout `make` runs in, whose venv runs Prefect and the runner."""

PREFECT = ROOT / "core" / ".venv" / "bin" / "prefect"
RUNNER = ROOT / "core" / ".venv" / "bin" / "fylgja-orchestrator"

PORT = 4200
"""The edge's Prefect's port: the task workers reach it at `host.docker.internal:4200`
(`infrahub/dev/compose.override.yml`)."""

UP_WAIT_S = 90
"""How long `prefect-up` waits for `/api/health` once the server is started."""

POLL_S = 1.0
"""Seconds between two asks of `/api/health`."""

HEALTH_TIMEOUT_S = 5
"""Seconds `/api/health` is given to answer one ask."""

DOWN_WAIT_S = 30
"""Seconds `prefect-down` gives the server to exit after SIGTERM before it is killed."""

USER = "fylgja"
"""The basic auth's user; its password is generated."""

PRINCIPAL = "orchestrator"
"""The principal the runner's token of the core's is listed under in the token file (D-025)."""

AUTH = "FYLGJA_ORCHESTRATOR_AUTH"
API_TOKEN = "FYLGJA_ORCHESTRATOR_API_TOKEN"
INFRAHUB_TOKEN = "FYLGJA_ORCHESTRATOR_INFRAHUB_TOKEN"
SCOPE = "FYLGJA_ORCHESTRATOR_SCOPE"
READER = "FYLGJA_ORCHESTRATOR_READER"
RECORDS = "FYLGJA_ORCHESTRATOR_ROOT"
TOKENS = "FYLGJA_TOKENS"
BIND = "PREFECT_BIND"

ENV_NAMES = (AUTH, API_TOKEN, SCOPE, READER, RECORDS)
"""What `env` writes into `local/.env`, in order."""

WRITE_TOKEN = "FYLGJA_INFRAHUB_WRITE_TOKEN"
"""The admin's token, the seed's and the tests' writer's, which the runner is never given."""

PASSED_ON = ("FYLGJA_API_", "FYLGJA_INFRAHUB_", "FYLGJA_ORCHESTRATOR_")
"""The prefixes of the names the runner is given as loaded, less `KEPT_BACK`."""

KEPT_BACK = (WRITE_TOKEN, AUTH, API_TOKEN, INFRAHUB_TOKEN)
"""Names of those prefixes the runner is not given: the admin's token, and the three it is given under the names
`fylgja_orchestrator.edge.settings` and Prefect read (P5-23)."""

ANALYTICS_OFF = {"DO_NOT_TRACK": "1", "PREFECT_SERVER_ANALYTICS_ENABLED": "false"}

ASSIGNMENT = re.compile(r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)")


def say(line: str) -> None:
    print(f"edge_dev: {line}", flush=True)


def fail(line: str, status: int = 1) -> int:
    print(f"edge_dev: {line}", file=sys.stderr, flush=True)
    return status


class Missing(Exception):
    """A name the runner needs is not set, named and never its value."""

    def __init__(self, name: str) -> None:
        super().__init__(f"{name} is not set: run make orchestrator-env and load local/.env")


def listeners(ss_output: str, port: int) -> list[str]:
    """The local addresses `ss -Hltn`'s lines listen on at `port`, whatever the address: `*:4200` and `[::]:4200`
    among them, `127.0.0.1:14200` never."""
    found = []
    for line in ss_output.splitlines():
        fields = line.split()
        if len(fields) >= 4 and fields[3].rpartition(":")[2] == str(port):
            found.append(fields[3])
    return found


def refusal(address: str, port: int) -> str:
    """The one sentence `prefect-up` refuses with where `port` is listened on already."""
    return (
        f"port {port} at {address} is listened on by a process this target did not start; it is not this target's "
        "to stop, and nothing was started"
    )


def env_lines(have: Mapping[str, str], main: Path, scope: str) -> list[tuple[str, str]]:
    """The lines `env` adds, in `ENV_NAMES`' order: each name `have` does not hold, or holds empty, with its value, the
    two secrets generated anew at each call."""
    values = {
        AUTH: f"{USER}:{secrets.token_urlsafe(24)}",
        API_TOKEN: secrets.token_urlsafe(24),
        SCOPE: scope,
        READER: str(main / "infrahub" / "seed" / "reader.yaml"),
        RECORDS: str(main / "local" / "orchestrator"),
    }
    return [(name, values[name]) for name in ENV_NAMES if not have.get(name)]


def runner_env(environ: Mapping[str, str], bind: str, *, home: Path) -> dict[str, str]:
    """The runner's whole environment: Prefect's API at `bind`, its basic auth, its home and its analytics off; the
    runner's own tokens under the names the edge's settings read; every other name of `PASSED_ON` as `environ` holds
    it, less `KEPT_BACK`; and `PATH` and `HOME`. No `INFRAHUB_*` name of Compose's, and no node credential. A name of
    the three the runner's own are taken from that is not set raises `Missing`."""
    for name in (API_TOKEN, INFRAHUB_TOKEN, AUTH):
        if not environ.get(name):
            raise Missing(name)
    given = {name: environ[name] for name in ("PATH", "HOME") if name in environ}
    given |= {
        name: value
        for name, value in environ.items()
        if name.startswith(PASSED_ON) and name not in KEPT_BACK
    }
    given |= {
        "FYLGJA_API_TOKEN": environ[API_TOKEN],
        "FYLGJA_INFRAHUB_TOKEN": environ[INFRAHUB_TOKEN],
        "PREFECT_API_URL": f"http://{bind}:{PORT}/api",
        "PREFECT_API_AUTH_STRING": environ[AUTH],
        "PREFECT_HOME": str(home),
        **ANALYTICS_OFF,
    }
    return given


def hashed(token: str) -> str:
    """A token's line in the token file holds this, the SHA-256 of its bytes in hex (D-025)."""
    return hashlib.sha256(token.encode()).hexdigest()


def held_names(path: Path) -> dict[str, str]:
    """The names `path` assigns, `NAME=…` or `export NAME=…`, each its last line's value as written, and `""` where
    that is empty, `""` or `''`: a shell reads it as empty, and `env` writes it again on a line after it."""
    held: dict[str, str] = {}
    for line in path.read_text().splitlines():
        found = ASSIGNMENT.fullmatch(line.strip())
        if found:
            held[found[1]] = "" if found[2].strip() in ("", '""', "''") else found[2]
    return held


def scope_of(local: Path, main: Path) -> str:
    """The scope the seed read: `<local>/infrahub/seed.json`'s where it is there, else `SCOPE` in the main checkout's
    `infrahub/seed/seed.py`, read by `ast` and never run."""
    seeded = local / "infrahub" / "seed.json"
    if seeded.is_file():
        scope = json.loads(seeded.read_text()).get("scope")
        if isinstance(scope, str) and scope:
            return scope
    source = main / "infrahub" / "seed" / "seed.py"
    for statement in ast.parse(source.read_text(), str(source)).body:
        if (
            isinstance(statement, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "SCOPE" for target in statement.targets)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            return statement.value.value
    raise ValueError(f"{source} assigns no SCOPE")


def append(path: Path, lines: Sequence[str]) -> None:
    """`lines` appended to `path`, a newline added first where its last line has none; a file made here is made at mode
    0600, and one already there keeps its mode (the core's token file is the core's)."""
    held = path.read_bytes() if path.exists() else b""
    ending = b"\n" if held and not held.endswith(b"\n") else b""
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "wb") as out:
        out.write(ending + "".join(f"{line}\n" for line in lines).encode())


def env(local: Path, main: Path, environ: Mapping[str, str]) -> int:
    """`local/.env`'s missing names, as the module says. 2, with nothing written, where the runner's token of the
    core's is to be made and `FYLGJA_TOKENS` is not set or names no file: the core reads its token file and makes
    none, so a file made here would be one no core reads."""
    path = local / ".env"
    if not path.is_file():
        return fail(f"{path} is not there: run make infrahub-up first", 2)
    lines = env_lines(held_names(path), main, scope_of(local, main))
    if not lines:
        say(f"{path} holds every name already; nothing written")
        return 0
    added = dict(lines)
    tokens = environ.get(TOKENS, "")
    if API_TOKEN in added:
        if not tokens:
            return fail(
                f"{TOKENS} is not set: set it in local/.env to the token file the core reads (CONTRIBUTING.md, "
                "\"Running the core\"), so that the runner's token of the core's is listed in it; nothing was written",
                2,
            )
        if not Path(tokens).is_file():
            return fail(
                f"{TOKENS} names {tokens}, which is no file: the core reads its token file and makes none; make it, or "
                "name the one the core reads; nothing was written",
                2,
            )
    append(path, [f"{name}={value}" for name, value in lines])
    say(f"{path}: added {', '.join(added)}")
    if API_TOKEN in added:
        append(Path(tokens), [f"{hashed(added[API_TOKEN])} {PRINCIPAL}"])
        say(f"listed the runner's token under the principal {PRINCIPAL} in {tokens}")
    if API_TOKEN in added:
        say(f"restart the core so that it reads {tokens} again")
    return 0


Run = Callable[..., subprocess.CompletedProcess[str]]


def bridge_gateway(run: Run = subprocess.run) -> str:
    """The Docker bridge's gateway, as `docker network inspect bridge` answers it."""
    answered = run(
        ["docker", "network", "inspect", "bridge", "--format", "{{range .IPAM.Config}}{{.Gateway}} {{end}}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    gateways = answered.stdout.split() if answered.returncode == 0 else []
    if not gateways:
        raise OSError(f"`docker network inspect bridge` exited {answered.returncode} naming no gateway")
    return gateways[0]


def bind_address(environ: Mapping[str, str], run: Run = subprocess.run) -> str:
    return environ.get(BIND) or bridge_gateway(run)


class Process(NamedTuple):
    """A process as `/proc` shows it: its command line and its environment."""

    argv: list[str]
    environ: dict[str, str]


def read_process(pid: int) -> Process | None:
    """Process `pid`'s command line and environment, or None where there is none or it cannot be read."""
    try:
        argv = Path(f"/proc/{pid}/cmdline").read_bytes()
        environ = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return None
    parts = [part.decode(errors="replace") for part in argv.split(b"\0") if part]
    pairs = [entry.decode(errors="replace").partition("=") for entry in environ.split(b"\0") if b"=" in entry]
    return Process(parts, {name: value for name, _, value in pairs}) if parts else None


Read = Callable[[int], Process | None]


def is_ours(process: Process | None, home: Path) -> bool:
    """Whether a process is this project's Prefect server: its command line names `prefect` and `server`, and its
    `PREFECT_HOME` is `home`, so that a reused pid, or another project's server, is never read as up nor stopped."""
    return (
        process is not None
        and any(Path(part).name == "prefect" for part in process.argv)
        and "server" in process.argv
        and process.environ.get("PREFECT_HOME") == str(home)
    )


def home_of(local: Path) -> Path:
    return local / "prefect"


def pid_file(local: Path) -> Path:
    return home_of(local) / "server.pid"


def running(local: Path, read: Read = read_process) -> int | None:
    """The pid `server.pid` names where that process is this project's Prefect server, else None."""
    try:
        pid = int(pid_file(local).read_text().strip())
    except (OSError, ValueError):
        return None
    return pid if is_ours(read(pid), home_of(local)) else None


DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
"""An opener that asks the server itself, whatever proxy the environment names."""


def healthy(address: str) -> bool:
    """Whether `/api/health` at `address` answers 200."""
    try:
        with DIRECT.open(f"http://{address}:{PORT}/api/health", timeout=HEALTH_TIMEOUT_S) as answer:
            return bool(answer.status == 200)
    except (OSError, HTTPException, ValueError):
        return False


def up(
    local: Path,
    environ: Mapping[str, str],
    *,
    run: Run = subprocess.run,
    popen: Callable[..., Any] = subprocess.Popen,
    read: Read = read_process,
    healthy: Callable[[str], bool] = healthy,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Start the server, as the module says: 0 once `/api/health` answers, or where it is up already; 1 otherwise."""
    held = running(local, read)
    if held is not None:
        say(f"the development Prefect is up already, pid {held}")
        return 0
    auth = environ.get(AUTH, "")
    if not auth:
        return fail(f"{AUTH} is not set: run make orchestrator-env and load local/.env", 2)
    bind = bind_address(environ, run)
    ss = run(["ss", "-Hltn"], capture_output=True, text=True, check=True, timeout=30).stdout
    found = listeners(ss, PORT)
    if found:
        return fail(refusal(found[0].rpartition(":")[0], PORT))
    home = home_of(local)
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    server_env = {name: environ[name] for name in ("PATH", "HOME") if name in environ}
    server_env |= {"PREFECT_HOME": str(home), "PREFECT_SERVER_API_AUTH_STRING": auth, **ANALYTICS_OFF}
    log = home / "server.log"
    with log.open("ab") as out:
        started = popen(
            [str(PREFECT), "server", "start", "--host", bind, "--port", str(PORT), "--no-ui"],
            env=server_env,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    pid_file(local).write_text(f"{started.pid}\n")
    begun = clock()
    while clock() - begun < UP_WAIT_S:
        if started.poll() is not None:
            pid_file(local).unlink(missing_ok=True)
            return fail(f"the Prefect server exited {started.returncode}; read {log}")
        if healthy(bind):
            say(f"the development Prefect answers at {bind}:{PORT}, pid {started.pid}, its log {log}")
            return 0
        sleep(POLL_S)
    return fail(f"{bind}:{PORT}/api/health did not answer within {UP_WAIT_S} s; read {log}, and stop it with make "
                "prefect-down")


def end_session(
    pid: int,
    *,
    killpg: Callable[[int, int], None] = os.killpg,
    alive: Callable[[int], bool] = lambda pid: Path(f"/proc/{pid}").exists(),
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """SIGTERM to the server's session, its leader `pid`, and SIGKILL where it has not exited within `DOWN_WAIT_S`."""
    try:
        killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    begun = clock()
    while clock() - begun < DOWN_WAIT_S:
        if not alive(pid):
            return
        sleep(0.5)
    try:
        killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        return


def down(local: Path, *, read: Read = read_process, end: Callable[[int], None] = end_session) -> int:
    """End the server `server.pid` names, only where it is this project's Prefect server, and remove the file."""
    path = pid_file(local)
    try:
        pid = int(path.read_text().strip())
    except OSError:
        say("the development Prefect is not running: no pid file")
        return 0
    except ValueError:
        path.unlink(missing_ok=True)
        say(f"{path} named no pid; removed it")
        return 0
    if not is_ours(read(pid), home_of(local)):
        path.unlink(missing_ok=True)
        say(f"pid {pid} of {path} is not this project's Prefect server; removed the file and stopped nothing")
        return 0
    end(pid)
    path.unlink(missing_ok=True)
    say(f"the development Prefect, pid {pid}, ended")
    return 0


def serve(local: Path, environ: Mapping[str, str]) -> int:
    """Become the runner, as the module says; 2 where a name it needs is not set."""
    try:
        given = runner_env(environ, bind_address(environ), home=home_of(local))
    except Missing as e:
        return fail(str(e), 2)
    os.execve(RUNNER, [str(RUNNER), "serve"], given)


def parser() -> argparse.ArgumentParser:
    made = argparse.ArgumentParser(prog="edge_dev.py", description=(__doc__ or "").splitlines()[0])
    verbs = made.add_subparsers(dest="verb", required=True)
    for verb in ("env", "prefect-up", "prefect-down", "serve"):
        each = verbs.add_parser(verb)
        each.add_argument("--local", type=Path, required=True, help="the main checkout's local/")
        each.add_argument("--main", type=Path, required=True, help="the main checkout")
    return made


def main(argv: Sequence[str], *, environ: Mapping[str, str] = os.environ) -> int:
    try:
        args = parser().parse_args(argv)
    except SystemExit as e:
        return 0 if e.code in (0, None) else 2
    local, main_checkout = args.local.absolute(), args.main.absolute()
    try:
        if args.verb == "env":
            return env(local, main_checkout, environ)
        if args.verb == "prefect-up":
            return up(local, environ)
        if args.verb == "prefect-down":
            return down(local)
        return serve(local, environ)
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        return fail(f"{args.verb}: {e}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
