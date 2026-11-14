#!/usr/bin/env python3
"""A demonstration on the development host: one source of truth's runbook, from nothing running to a rehearsal's
verdict, with no step by hand beyond the host's stated preconditions (design/core.md, "Phase 10"; D-104).

Run from the repository root as `python3 -I scripts/demo.py up {infrahub|netbox} --local <local> --main <main
checkout> --ref <branch or empty>` and `python3 -I scripts/demo.py down --local <local> --main <main checkout>
[--purge]`. The standard library alone; no script imports another, and this one is never installed.

- `up` holds `<local>/demo/lock` while it runs and reads the environment, the shell's overlaid by `<local>/.env`.
  It judges the host's preconditions, `checks`, what only the host's owner can give, in two parts. First those no
  stop can cure: every one that fails is said in a line of its own, exit 2, and nothing is settled, stopped or
  started for a run that could never start. Then it ends what an earlier run left (`settle`) and stops the other
  source where that is up (`alone`), since either starts the same two deployments, and judges the host's room, its
  memory and its ports, with both done. Where that passes it writes what can be generated (`prepare`), records its
  source, pulls the images the seeded twin runs where Docker holds none (`pull`), and takes its source's runbook
  in order (`STEPS`): each step the make target the runbook names, run as a child with `<local>/.env` read again
  before it, and the core and the runner started where the runbook has them. Once the source is up it reads
  Docker's networks as the local driver does and stops, the source left up, where they leave the lab pool no /24
  (`pool_checked`). From `settle` on, every way out says last what is left up (`left_up`); a step that fails is
  exit 1, naming the step. Its last step opens the change, which its source turns into a flow run of
  `twin-rehearse/main` on the edge's Prefect, by Infrahub's check or NetBox's webhook: `up` is told nothing of it,
  and finds the run by the ids Prefect listed before the change (`follow`), waits for its end within the flow's own
  bound, reads the document it filed as Infrahub's check reads it, with the edge's own credential, keeps it, and
  says the verdict and where a person reads the report in the source (`readout`).
- A make target is given no variable but its own. make reads variables from its environment and from what a make
  above it hands on, so every make child, each step, the other source's stop and `down`'s targets, is given the
  loaded environment without make's own names and without every name the `Makefile` assigns by `?=` (`make_env`),
  and its variables on its command line alone; a stop that is no purge says `PURGE=` there (`stop_words`). The
  names the caller set that no target is given are said once, and never a value.
- `down` holds the same lock, and ends what the demonstration `<local>/demo/source` records started (`settle`,
  then the Prefect server and the source by their own targets): the runner and the core by their recorded pids,
  each only where the pid still reads as that process, and through the core every twin its store holds. It is exit
  0 only where the store is settled: read empty through a core of the demonstration's own.

The core and the runner are the two things no target starts in the background: `start_core` and `start_runner`
start each in a session of its own, record its pid and wait until it serves, and `refuse_runners` stops a run beside
a runner it may not end. A core's answer is taken for the demonstration's only where the listener at its port is
its own pid (`owns`), read again before each destroy, before the list that follows them and before the store is
called settled, and none is started where anything listens there already: a twin is listed and destroyed through no
other core.

What the script keeps is under `<local>/demo/` (`records`). What it writes that can be generated, `prepare`: that
directory, the token file its core reads, and in `<local>/.env`, where the loaded environment gives the name no
value, the core's address and a client's token. No value of `<local>/.env` is ever printed: a refusal names a
variable by its name and a line by its number.

Every process, socket, file of the host's and clock the script touches goes through one seam, `Host`, and `Real` is
its one implementation.

Exit 0, for `up` a rehearsal `passed` and for `down` everything ended; 1 for a failure, a verdict other than `passed`
or none; 2 for a command line not understood, a precondition of the host's not met, a line of `<local>/.env` that is
not read as a shell would read it, a value that is not UTF-8 or that a child would not be given as the file has it,
or another demonstration command running; 130 for a Ctrl-C. Each but the passed verdict is said on stderr.
"""

from __future__ import annotations

import argparse
import base64
import errno
import fcntl
import grp
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.message import Message
from ipaddress import IPv4Network, ip_network
from pathlib import Path
from typing import IO, Any, NamedTuple, Protocol

ROOT = Path(__file__).resolve().parent.parent
"""The checkout this file is in: every child's working directory, and whose venv and packages the core runs from."""

SOURCES = ("infrahub", "netbox")
"""The sources of truth a demonstration is of."""

VENV = ROOT / "core" / ".venv"
COMMANDS = ("fylgja-core-server", "fylgja-core", "fylgja-orchestrator", "prefect")
"""What a demonstration runs from `VENV`'s `bin`, which `make venv` puts there."""

CORE = VENV / "bin" / "fylgja-core-server"
CLI = VENV / "bin" / "fylgja-core"
"""The core's server, which the demonstration starts from this checkout on the local driver, and its CLI, by which
the twins an earlier run left are listed and destroyed."""

RUNNER_COMMAND = "fylgja-orchestrator"
"""The command a runner is, whatever checkout's venv it runs from: `edge_dev.py serve` becomes it, with the one word
`serve`."""

TOOLS = ("docker", "containerlab", "git", "make", "ss")
"""What a demonstration runs from PATH."""

GROUPS = ("docker", "clab_admins")
"""The groups a process needs to reach the Docker daemon and to run containerlab's labs."""

LOGIN = ("FYLGJA_CREDENTIAL_SRLINUX_USERNAME", "FYLGJA_CREDENTIAL_SRLINUX_PASSWORD")
"""The node login's two names (D-042), asked for by name and never given a default."""

APPARMOR_PROFILE = "/etc/apparmor.d/usr.sbin.rsyslogd"
APPARMOR_LOCAL = "/etc/apparmor.d/local/usr.sbin.rsyslogd"
APPARMOR_LINES = ("/opt/srlinux/** mr,", "/run/srlinux/** rw,")
"""Ubuntu's profile of rsyslogd, the file that widens it, and the two lines SR Linux's rsyslogd needs there
(design/verified-facts.md, "Ubuntu hosts"). Whether the widened profile is loaded is not a user's to read."""

PROJECTS = {"infrahub": "fylgja-core-infrahub", "netbox": "fylgja-core-netbox"}
"""Each source's Compose project, as `infrahub_dev.py` and `netbox_dev.py` name it, held equal by a test."""

PORTS = {"infrahub": 8000, "netbox": 8800}
"""The port each source is served on at loopback, as its script's `ADDRESS` has it."""

PREFECT_PORT = 4200
"""The edge's Prefect's port, `edge_dev.py`'s `PORT`."""

SOURCE_MB = {"infrahub": 4608, "netbox": 1536}
"""The memory a source's stack needs where it is not up, in MiB: the 4.5 GiB and the 1.36 GiB read of each."""

TWIN_MB = 7168
"""The memory the twin and the edge need, in MiB: the fixture's three nodes at 2048 MiB each by
`psp/nokia_srlinux.yaml`, and 1024 for the probes' hosts, the core, Prefect and the runner, a first value."""

POOL = "FYLGJA_LAB_POOL"
DEFAULT_POOL = "172.20.0.0/16"
"""The server's setting of the local driver's pool, and the pool where it gives none: this script's own copy of
`fylgja_core.containerlab.pool.DEFAULT_POOL`."""

FORMAT = "{{json .Name}} {{json .IPAM.Config}}"
"""What `docker network inspect --format` is asked for, a line a network: its name as a JSON string, one space, and
its IPAM config, a list of objects or `null`. This script's own copy of `fylgja_core.containerlab.pool.FORMAT`."""

PLAIN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
"""A network's name that a refusal writes as it is; any other it writes as a JSON string, as the driver's does."""

NETWORK_IDS = ("docker", "network", "ls", "--format", "{{.ID}}")
"""The local driver's own words for the ids of Docker's networks (`fylgja_core.containerlab.driver`,
`_docker_networks`), held to its source by a test."""

MAKES_OWN = ("MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES", "MAKELEVEL", "GNUMAKEFLAGS", "MAKEFILES")
"""What make reads of its own from its environment: the flags and the command line's variables a make above it hands
on, its depth, and makefiles to read before the checkout's. No make child of the script's is given one
(`make_env`)."""

MAKE_VARIABLES = (
    "LOCAL", "INFRAHUB_VERSION", "INFRAHUB_SDK_VERSION", "REF", "SEED_BRANCH", "PURGE", "PROPOSED_CHANGE",
    "NETBOX_VERSION", "NETBOX_DOCKER_VERSION", "NETBOX_BRANCHING_VERSION", "NETBOX_BRANCH", "NETBOX_TAG", "SOURCE",
    "IMAGE", "DRIVER",
)  # fmt: skip
"""Every name the `Makefile` assigns by `?=`, in its order, held to it by a test: make takes each from its
environment where that holds it, so no make child of the script's is given one (`make_env`), and a target's
variables are its command line's alone."""

IMAGES = ("ghcr.io/nokia/srlinux:24.7.1", "alpine:3.24.2")
"""The images the seeded twin runs, its nodes' and its probe hosts', as `psp/nokia_srlinux.yaml` and
`probes/ping.yaml` name them, held equal by a test."""

LISTEN = "FYLGJA_LISTEN"
DEFAULT_LISTEN = "127.0.0.1:7650"
"""The server's setting of its listen address, and the address where it gives none, the core's own default."""

LISTEN_REFUSED = (
    f"{LISTEN} is not 127.0.0.1:<port>: the demonstration's core serves HTTP on loopback; set it so in local/.env, "
    "or delete the line"
)
"""What is said of a listen address that is not loopback's with a port: the check's sentence, and the reason why
nothing is started or settled at such an address."""

OWN = "FYLGJA_"
"""How the names begin whose values the script itself reads, hashes, writes or sends."""

API_ADDRESS = "FYLGJA_API_ADDRESS"
API_TOKEN = "FYLGJA_API_TOKEN"
API_CA = "FYLGJA_API_CA"
RUNNER_TOKEN = "FYLGJA_ORCHESTRATOR_API_TOKEN"
TOKENS = "FYLGJA_TOKENS"
STORE = "FYLGJA_STORE"

AUTH = "FYLGJA_ORCHESTRATOR_AUTH"
"""The basic auth the edge's Prefect asks, a `user:password`, as `make orchestrator-env` names it in `<local>/.env`."""

RUNNER_SOURCE = "FYLGJA_ORCHESTRATOR_SOURCE"
"""The change source a runner serves, which `edge_dev.py serve` sets in its environment."""

PREFECT_HOME = "PREFECT_HOME"
"""Prefect's home, which the server and the runner of one `<local>/` are each given (`prefect_home`)."""

FLOW = "twin-rehearse"
PLAN_FLOW = "stage-plan"
DEPLOYMENT = "main"
"""The two flows the runner serves, each as the deployment `<flow>/main` (`fylgja_orchestrator.edge.flows`, held
equal by a test)."""

ARTIFACT_TYPE = "fylgja-document"
"""The type of the artifact a flow run files its document as (`fylgja_orchestrator.edge.flows`, and the checks' glue
that reads it, `infrahub/checks/fylgja_glue.py`; held equal by a test)."""

ENDED = frozenset({"COMPLETED", "FAILED", "CANCELLED", "CRASHED"})
"""The state types a flow run ends in, the glue's."""

PASSED = "passed"
"""The one status of a rehearsal's document that is exit 0, as the check `fylgja-twin` passes for it alone."""

THREAD = "Fylgja rehearsal"
"""The label of the thread the example posts a rehearsal's report in on Infrahub's proposed change
(`fylgja_orchestrator.infrahub.source.THREAD_LABEL`, held equal by a test)."""

RUNS_LIMIT = 50
"""The runs one list of a deployment's asks for, newest first: Prefect takes at most 200."""

WHERE_TO_LOOK = {
    "infrahub": "read the proposed change's checks in Infrahub, and the task workers' logs",
    "netbox": "the tag's request did not reach Prefect; read NetBox's background tasks, and run make netbox-hook",
}
"""Where to read why a change of each source started no run: Infrahub's check starts it from a task worker, and
NetBox's webhook sends the request that starts it."""

READY = "READY"
"""A deployment's `status` once a runner serves it."""

SERVING = "fylgja-orchestrator: serving"
"""How the line begins that the runner prints once it has made its deployments, before it serves them."""

PRINCIPALS = ((API_TOKEN, "demo"), (RUNNER_TOKEN, "orchestrator"))
"""The two tokens the demonstration's core knows, each by its name in the environment, with the principal its hash
is listed under in the token file (D-025): the client's, and the runner's, which `make orchestrator-env` makes."""

NOT_THE_CORES = ("FYLGJA_TLS_CERT", "FYLGJA_TLS_KEY", "FYLGJA_LEASE")
"""Settings the demonstration's core is never given: it serves HTTP on loopback, over a store that is a directory."""

REQUEST_TIMEOUT_S = 30
"""Seconds one request is given to answer."""

DOCKER_TIMEOUT_S = 60
"""Seconds one read by a child is given: of the host, by `docker`, `containerlab`, `ss` or `git`, `netbox_dev.py`'s
bound for an inspection; of Prefect's API's address, by `edge_dev.py api`, which asks Docker for it; and of the
core's twins, by its CLI."""

PULL_TIMEOUT_S = 1800
"""Seconds one `docker pull` is given; a first value. Another tag of the node's image, 3.2 GB, was read to take 108 s
(design/verified-facts.md, 2026-11-12), and the one pulled here Docker lists at 5.19 GB."""

CORE_WAIT_S = 60
"""Seconds the core is given from its start to answer its version: it was read to answer 1.23 to 1.32 s after its
start, five times (design/verified-facts.md, "NetBox 4.7.5 with netbox-branching 1.2.3", 2026-11-14), of which this
is 45 times the slowest."""

SERVE_WAIT_S = 60
"""Seconds the runner is given from its start to serve both deployments: both read `READY` 3.66 to 5.11 s after its
start, five times ("Prefect 3.9.2", 2026-11-14), of which this is 11.7 times the slowest. Where `PREFECT_BIND` is not
set, `edge_dev.py` first asks Docker for the bridge's gateway, within this."""

STOP_WAIT_S = 30
"""Seconds a process is given to exit after SIGTERM before it is killed, `edge_dev.py`'s `DOWN_WAIT_S`: the runner
was read gone 0.69 to 3.93 s after its signal and the core 0.43 to 0.55 s (the same facts), of which this is 7.6
times the slowest."""

POLL_S = 5.0
"""Seconds between two asks of Prefect while the change's flow run is waited for, the checks' glue's."""

APPEAR_WAIT_S = 300
"""Seconds from the last step's return for the change's flow run to be listed: a proposed change's run was read to be
made 69.0 s after the change's creation ("Infrahub 1.11.11", 2026-11-12, one run) and the tag's 0.94 to 1.03 s after its
`PATCH` ("NetBox 4.7.5 with netbox-branching 1.2.3"), of which this is 4.3 times the slower."""

RUN_WAIT_S = 4200
"""Seconds from the change's flow run listed to its end: no reading, but the flow's own bound,
`flows.REHEARSE_TIMEOUT_S`, 3900 s, and 300 s, held equal by a test."""

DESTROY_TIMEOUT_S = 300
"""Seconds one `fylgja-core twin destroy` is given: one was read to take 2.3 s (the same facts), and
`psp/nokia_srlinux.yaml` gives a node 60 s to stop; a first value."""

ASK_S = 1.0
"""Seconds between two asks of a process just started: of the core's version, and of the runner's line, process and
deployments."""

STOP_POLL_S = 0.5
"""Seconds between two reads of a process that was signalled, `edge_dev.end_session`'s."""

KILL_WAIT_S = 1.0
"""Seconds a process is given to be gone after SIGKILL; a first value."""

PORT_FREE_WAIT_S = 5.0
"""Seconds the port of a core just ended is given to be free before one is started at the same address: a listener
was read to outlast its process by 3 to 107 ms, the longest for a process of 600 MiB; a first value, 47 times that."""

PORT_FREE_POLL_S = 0.1
"""Seconds between two reads of that port."""

TIMED_OUT = 124
"""The status `Real.run` answers for a child that outlasted its timeout and was killed, as `timeout` exits."""

NOT_FOUND = 127
"""The status `Real.run` answers for a command the PATH it was run under does not hold, as a shell exits."""

NOT_RUN = 126
"""The status `Real.run` answers for a command that is found and is not run, as a shell exits: one that is not this
user's to run, or that the kernel cannot run."""

BASH_KEEPS = frozenset(
    {
        "UID", "EUID", "PPID", "BASHOPTS", "SHELLOPTS", "BASH_VERSINFO", "GROUPS", "RANDOM", "SRANDOM", "SECONDS",
        "LINENO", "FUNCNAME", "DIRSTACK", "BASHPID", "EPOCHSECONDS", "EPOCHREALTIME", "HISTCMD", "BASH_COMMAND",
        "BASH_SUBSHELL", "BASH_MONOSECONDS", "PIPESTATUS", "COMP_WORDBREAKS", "BASH_LINENO", "BASH_SOURCE", "BASH_ARGC",
        "BASH_ARGV", "BASH_ALIASES", "BASH_CMDS", "_", "BASH_ARGV0", "SHLVL", "OPTIND",
    }
)  # fmt: skip
"""Names bash keeps for itself: where a file it loads assigns one, bash exports its own value, another than the
file's (`SHLVL`, lowered) or none, and dash the file's, but for an `OPTIND` that is no number, where dash stops
loading the file. The shells do not agree, so a line that assigns one is not read."""

BLANK = " \t"
"""What a shell takes for a blank between words: a space and a tab, and no other character Python calls white."""

ASSIGNMENT = re.compile(r"(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)", re.DOTALL)
VALUE = re.compile(
    r"""(?:'(?P<single>[^'\x00]*)'|"(?P<double>[^"$`\\\x00]*)"|(?P<bare>[^\s\x00-\x1f\x7f'"$`\\~;&|<>(){}]*))"""
    r"""(?:[ \t]+#.*|[ \t]*)""",
    re.DOTALL,
)
"""An assignment's value as this script reads it, a comment after it aside: one pair of single quotes, one pair of
double quotes holding no `$`, backquote or backslash, or one word, perhaps empty, free of what a shell would expand,
escape or end a command at, and of every control character and every character Python calls white space, which to a
shell is part of the word (a carriage return, a form feed, a no-break space, a line separator). No NUL anywhere: a
shell drops it, and no child can be given one."""

LOOPBACK = re.compile(r"127\.0\.0\.1:([1-9][0-9]{0,4})")

USER = re.compile(r'",pid=([0-9]+),fd=[0-9]+\)')
"""A user of a listener as `ss -Hltnp` writes one after its name: its pid."""

AFTER_THE_SCHEME = re.compile(r"[^\s/?#@]+(?:/[^\s?#]*)?")
"""What follows the scheme in Prefect's API as `edge_dev.py api` prints it: a host, with its port, and a path, with no
login, query or fragment, and no white space."""


class Stop(Exception):
    """The run ends here: its exit status, and the lines said on stderr."""

    def __init__(self, status: int, lines: Sequence[str]) -> None:
        super().__init__(f"exit {status}")
        self.status = status
        self.lines = tuple(lines)


class Unread(Exception):
    """A line this script does not read as a shell would: its number, the name it assigns, None where it assigns
    none, whether a carriage return is all that stands in the way, and whether the name is one bash keeps for itself.
    Never the value."""

    def __init__(
        self, name: str | None, line: int, carriage_return: bool = False, kept_by_bash: bool = False
    ) -> None:
        super().__init__(f"line {line} is not read" if name is None else f"line {line} gives {name} what is not read")
        self.name = name
        self.line = line
        self.carriage_return = carriage_return
        self.kept_by_bash = kept_by_bash


class Done(NamedTuple):
    """A child that ended: its exit status, and what it printed on stdout where that was captured."""

    status: int
    out: str


class Answer(NamedTuple):
    """An answer to a request: its status, None where nothing answered, and its body read as JSON, None where it is
    none."""

    status: int | None
    body: Any


class Process(NamedTuple):
    """A process as `/proc` shows it: its command line and its environment."""

    argv: list[str]
    environ: dict[str, str]


class Host(Protocol):
    """Everything of the host the script touches: its processes, its sockets, its files outside `<local>/`, its
    clock, its randomness. The tests give a fake in its place, and start nothing."""

    def run(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: Path | None = None,
        capture: bool = False,
        timeout: float | None = None,
    ) -> Done:
        """A child run to its end, under `env` where it is given and this process's environment where not. A child
        not captured prints as it will; one captured prints nothing, and its stdout is answered. One that outlasts
        `timeout` is killed, and its status is `TIMED_OUT`; a command that is not found, on the PATH of `env` where
        that is given, is no exception, and its status is `NOT_FOUND`, nor is one found that may not be run or that
        the kernel cannot run, whose status is `NOT_RUN`. A captured child that could not be started for any other
        reason is `NOT_RUN` too, so that no read of the host ends in an exception; one not captured raises its
        `OSError`."""
        ...

    def start(self, argv: Sequence[str], *, env: Mapping[str, str], cwd: Path, log: Path) -> int:
        """A child started in a session of its own, its stdin null and both its outputs appended to `log`; its
        pid."""
        ...

    def process(self, pid: int) -> Process | None:
        """Process `pid` as `/proc` shows it, or None where there is none or it cannot be read. No `pid` at or under
        1 is one: nothing is decided of init, and 0 and below name no process."""
        ...

    def pids(self) -> list[int]:
        """Every process's pid."""
        ...

    def signal(self, pid: int, number: int) -> bool:
        """Signal `number` sent to the session `pid` leads; False where there is no such process or it is not this
        user's to signal, and for a `pid` at or under 1 with nothing sent, which would name this process's own
        group, init's, or every process."""
        ...

    def ask(self, method: str, url: str, *, auth: str | None = None, body: Any = None) -> Answer:
        """One request, `body` sent as JSON where it is given and `auth`, a `user:password`, as basic auth, with no
        proxy and no redirect followed, given `REQUEST_TIMEOUT_S`. No exception carries a request: where nothing
        answered, the answer's status is None."""
        ...

    def groups(self) -> set[int]:
        """The gids this process holds."""
        ...

    def gid(self, name: str) -> int | None:
        """The gid of the host's group `name`, or None where it has none."""
        ...

    def euid(self) -> int: ...

    def which(self, name: str) -> str | None:
        """The executable `name` on PATH, or at `name` where that is a path; None where there is none."""
        ...

    def text(self, path: Path) -> str | None:
        """What the file `path` holds, or None where there is no such file: its bytes decoded as UTF-8 and nothing
        else done to them, so that no line end is translated and a carriage return is still there, and a byte that
        is no UTF-8 is kept, as the surrogate that stands for it (`surrogateescape`): the reader sees what the file
        holds, and refuses what it does not read. One that is not this user's to read raises `PermissionError`."""
        ...

    def clock(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...

    def secret(self) -> str:
        """A token made anew."""
        ...

    def lock(self, path: Path) -> bool:
        """Take the lock file `path`, made with its directory where absent, and hold it until this process ends;
        False where another process holds it."""
        ...


class Real:
    """The host itself. Nothing outside this class names `subprocess`, `urllib`, `os.kill`, `os.killpg`, `time`,
    `secrets`, `fcntl` or `grp`, which a test holds."""

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        """No redirect is followed: an auth is sent to the address asked, and to no other."""

        def redirect_request(
            self,
            req: urllib.request.Request,
            fp: IO[bytes],
            code: int,
            msg: str,
            headers: Message,
            newurl: str,
        ) -> urllib.request.Request | None:
            return None

    def __init__(self) -> None:
        self._direct = urllib.request.build_opener(urllib.request.ProxyHandler({}), self._NoRedirect())
        self._started: dict[int, subprocess.Popen[bytes]] = {}
        self._locks: list[int] = []

    def run(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        cwd: Path | None = None,
        capture: bool = False,
        timeout: float | None = None,
    ) -> Done:
        try:
            done = subprocess.run(
                list(argv),
                env=None if env is None else dict(env),
                cwd=cwd,
                stdout=subprocess.PIPE if capture else None,
                stderr=subprocess.DEVNULL if capture else None,
                encoding="utf-8",
                errors="replace",
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return Done(TIMED_OUT, "")
        except (FileNotFoundError, NotADirectoryError):  # the second: an element of PATH that is a file
            return Done(NOT_FOUND, "")
        except PermissionError:
            return Done(NOT_RUN, "")
        except OSError as not_started:
            if capture or not_started.errno == errno.ENOEXEC:  # the second: no format the kernel runs, and no `#!`
                return Done(NOT_RUN, "")
            raise
        return Done(done.returncode, done.stdout or "")

    def start(self, argv: Sequence[str], *, env: Mapping[str, str], cwd: Path, log: Path) -> int:
        with log.open("ab") as out:
            started = subprocess.Popen(
                list(argv),
                env=dict(env),
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        self._started[started.pid] = started
        return started.pid

    def _exited(self, pid: int) -> bool:
        """Whether `pid` is a child this started that has exited: it is reaped here, so that it is no process, where
        `/proc` would show it until its parent did so."""
        started = self._started.get(pid)
        return started is not None and started.poll() is not None

    def process(self, pid: int) -> Process | None:
        if pid <= 1 or self._exited(pid):
            return None
        try:
            argv = Path(f"/proc/{pid}/cmdline").read_bytes()
            environ = Path(f"/proc/{pid}/environ").read_bytes()
        except OSError:
            return None
        # Decoded as this process's own arguments and environment were, `surrogateescape` and all: a path that
        # holds a byte that is not UTF-8 then reads as this script itself holds that path, and compares equal.
        parts = [os.fsdecode(part) for part in argv.split(b"\0") if part]
        pairs = [os.fsdecode(entry).partition("=") for entry in environ.split(b"\0") if b"=" in entry]
        return Process(parts, {name: value for name, _, value in pairs}) if parts else None

    def pids(self) -> list[int]:
        found = sorted(int(entry.name) for entry in Path("/proc").iterdir() if entry.name.isdigit())
        return [pid for pid in found if not self._exited(pid)]

    def signal(self, pid: int, number: int) -> bool:
        if pid <= 1 or self._exited(pid):
            return False
        try:
            os.killpg(pid, number)
        except (ProcessLookupError, PermissionError):
            return False
        return True

    def ask(self, method: str, url: str, *, auth: str | None = None, body: Any = None) -> Answer:
        import http.client  # for an exception's class alone: no connection is made by it here

        headers = {"Accept": "application/json"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if auth is not None:
            headers["Authorization"] = f"Basic {base64.b64encode(auth.encode()).decode()}"
        try:
            request = urllib.request.Request(url, data=data, method=method, headers=headers)
            try:
                with self._direct.open(request, timeout=REQUEST_TIMEOUT_S) as answer:
                    status, read = int(answer.status), answer.read()
            except urllib.error.HTTPError as refused:
                with refused:
                    status, read = refused.code, refused.read()
        except (OSError, http.client.HTTPException, ValueError):
            return Answer(None, None)
        try:
            return Answer(status, json.loads(read))
        except ValueError:
            return Answer(status, None)

    def groups(self) -> set[int]:
        return {*os.getgroups(), os.getegid()}

    def gid(self, name: str) -> int | None:
        try:
            return grp.getgrnam(name).gr_gid
        except KeyError:
            return None

    def euid(self) -> int:
        return os.geteuid()

    def which(self, name: str) -> str | None:
        return shutil.which(name)

    def text(self, path: Path) -> str | None:
        try:
            return path.read_bytes().decode("utf-8", "surrogateescape")
        except (FileNotFoundError, NotADirectoryError, IsADirectoryError):
            return None

    def clock(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def secret(self) -> str:
        return secrets.token_urlsafe(24)

    def lock(self, path: Path) -> bool:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(descriptor)
            return False
        self._locks.append(descriptor)
        return True


def say(line: str) -> None:
    print(f"demo: {line}", flush=True)


def fail(line: str, status: int = 1) -> int:
    print(f"demo: {line}", file=sys.stderr, flush=True)
    return status


@dataclass(frozen=True)
class Records:
    """What the script keeps under `<local>/demo/`: the word of the last `up` that passed its checks; the pids of the
    core and the runner it started, and of the Prefect server where `make prefect-up` started one for it; the core's
    and the runner's logs; the core's store, and the marker that it is unsettled, empty, which stands from before a
    core is started over the store until a core of the demonstration's own has listed no twin; its token file; the
    lock; and the last rehearsal's document."""

    source: Path
    core_pid: Path
    runner_pid: Path
    prefect_pid: Path
    core_log: Path
    runner_log: Path
    store: Path
    unsettled: Path
    tokens: Path
    lock: Path
    rehearsal: Path


def records(local: Path) -> Records:
    """The records of `local`, each path resolved, so that it has one spelling whatever spelling of `local` a command
    was given: a core is known by its store's path."""
    home = local.resolve() / "demo"
    return Records(
        source=home / "source",
        core_pid=home / "core.pid",
        runner_pid=home / "runner.pid",
        prefect_pid=home / "prefect.pid",
        core_log=home / "core.log",
        runner_log=home / "runner.log",
        store=home / "store",
        unsettled=home / "unsettled",
        tokens=home / "tokens",
        lock=home / "lock",
        rehearsal=home / "rehearsal.json",
    )


def read_env(text: str) -> dict[str, str]:
    """The names `text` assigns, each with its value as a shell that loads the file reads it (`set -a; . file`), or
    `Unread`: the script holds no value a shell loading the file would not.

    What is read: a line is ended by a newline and by nothing else; a blank line and a comment hold nothing; any
    other line is `NAME=value` or `export NAME=value`, blanks before and after it aside, a blank being a space or a
    tab. The last line of a name wins. A value is one pair of single quotes, one pair of double quotes or one word,
    its quotes taken off and a comment after it aside; a name assigned nothing holds `""`.

    What is refused, with the line's number and the name where the line has one: any other line, since a shell
    would act on it (`unset X`, `X+=2`, `. other`); a name of `BASH_KEEPS`, whatever it is given; and a value a
    shell would do more to than this does, which is not guessed at: one holding a `$`, a backquote or a backslash
    outside single quotes, a quote left open, more than one word or pair of quotes, a NUL, or, outside quotes, a
    `~`, a brace, a character that ends a command (`;`, `&`, `|`, `<`, `>`, `(`, `)`), a control character or a
    character Python alone calls white space. So a file saved with CRLF line ends is refused at its first line that
    is no comment, and `Unread` says where taking the carriage returns out is all the line needs."""
    held: dict[str, str] = {}
    for number, line in enumerate(text.split("\n"), 1):
        try:
            assigned = assignment(line)
        except Unread as unread:
            carriage_return = False
            if "\r" in line:
                try:
                    assignment(line.replace("\r", ""))
                    carriage_return = True
                except Unread:
                    pass
            raise Unread(unread.name, number, carriage_return, unread.kept_by_bash) from None
        if assigned is not None:
            held[assigned[0]] = assigned[1]
    return held


def assignment(line: str) -> tuple[str, str] | None:
    """The name and the value one line assigns, None for a blank line or a comment, and `Unread`, its line not yet
    numbered, for any other line (`read_env`)."""
    line = line.strip(BLANK)
    if not line or line.startswith("#"):
        return None
    assigned = ASSIGNMENT.fullmatch(line)
    if not assigned:
        raise Unread(None, 0)
    if assigned[1] in BASH_KEEPS:
        raise Unread(assigned[1], 0, kept_by_bash=True)
    value = VALUE.fullmatch(assigned[2])
    if not value:
        raise Unread(assigned[1], 0)
    return assigned[1], value["single"] or value["double"] or value["bare"] or ""


def loaded(local: Path, environ: Mapping[str, str], host: Host) -> dict[str, str]:
    """`environ` overlaid by `<local>/.env`, as a shell that loads the file has it, and `environ` alone where there
    is no file. A file that is not this user's to read stops the run, exit 2, and so does a line `read_env` does not
    read, naming the line by its number and the name where it has one, and never the value; and so does a value
    that is not carried (`unfit`), each said by its name alone. Every value the file gives is judged. Of the shell's
    own, only one whose name begins `FYLGJA_`, which the script may read, hash, write or send: every other passes
    through untouched, whatever its bytes, and reaches a child as it came."""
    path = local / ".env"
    try:
        text = host.text(path)
    except PermissionError:
        raise Stop(2, [f"{path} is not this user's to read"]) from None
    try:
        held = {} if text is None else read_env(text)
    except Unread as unread:
        raise Stop(2, [f"{path} line {unread.line} {unread_as(unread)}"]) from None
    env = {**environ, **held}
    refused = [
        said
        for name, value in env.items()
        if (name in held or name.startswith(OWN)) and (said := unfit(name, value, of_the_file=name in held))
    ]
    if refused:
        raise Stop(2, refused)
    return env


def unfit(name: str, value: str, *, of_the_file: bool = True) -> str | None:
    """What is said of a value the script does not carry, by its name alone, and None for one it does.

    No value the script may itself use holds a byte that is not UTF-8, which `Host.text` hands on as a surrogate,
    and under a locale of UTF-8 the process's environment too: the script writes a value into a line, sends one in a
    header and hashes one, each as UTF-8. And a value `<local>/.env` gives is one the process's locale gives a child
    as the file has it,
    since a shell that loads the file gives a child the file's own bytes: not one the locale cannot encode, nor one
    it would write as other bytes, as ISO-8859-1 writes one byte for a character the file holds as two. A value of
    the shell's own is not asked that: its bytes are given back to a child as they came."""
    try:
        held = value.encode("utf-8")
    except UnicodeEncodeError:
        return f"{name} holds a byte that is not UTF-8"
    if not of_the_file:
        return None
    try:
        if os.fsencode(value) != held:
            return f"{name} holds a character this locale would not write as the file has it"
    except UnicodeEncodeError:
        return f"{name} holds a character this locale cannot encode"
    return None


def encoded(name: str, value: str) -> bytes:
    """The bytes of `value` as a child is given them, as a line is written and as a token is hashed: its UTF-8,
    which is what `<local>/.env` holds for it (`Host.text`) and what a shell that loads the file gives a child. A
    value that is not carried (`unfit`) stops the run, exit 2, by its name alone. An encoding's exception holds the
    whole value, so the `Stop` is raised with none being handled and carries none, as its cause or as its context:
    nothing of a value is ever said."""
    refused = unfit(name, value)
    if refused is not None:
        raise Stop(2, [refused])
    return value.encode("utf-8")


def unread_as(unread: Unread) -> str:
    """What is said of a line that is not read, after its file and its number: the carriage return, with the name
    it is given to where there is one, where that is all that stands in the way, as in a file saved with CRLF line
    ends; a name bash keeps; else what the script reads."""
    if unread.carriage_return:
        crlf = "the file may be saved with CRLF line ends; save it with LF alone"
        if unread.name is None:
            return f"holds a carriage return, which a shell takes for part of the line: {crlf}"
        return f"gives {unread.name} a carriage return, which a shell keeps in the value: {crlf}"
    if unread.kept_by_bash:
        return (
            f"assigns {unread.name}, a name bash keeps for itself, so that a shell that loads the file may not hold "
            "the value: take the line out"
        )
    if unread.name is None:
        return (
            "is not blank, a comment or [export ]NAME=value, and this script reads no other line, since a shell that "
            "loads the file would act on it: take the line out"
        )
    return (
        f"gives {unread.name} a value this script does not read as a shell would: it holds a $, a backquote or a "
        "backslash outside single quotes, or is neither one pair of quotes nor one word free of blanks, control "
        "characters and ~ ; & | < > ( ) { }; write it in single quotes"
    )


def listen_of(env: Mapping[str, str]) -> str:
    """The address the demonstration's core listens on: `FYLGJA_LISTEN` as loaded, else the core's default."""
    return env.get(LISTEN) or DEFAULT_LISTEN


def port_of(listen: str) -> int | None:
    """The port of a listen address that is `127.0.0.1:<a port from 1 to 65535>`, and None for any other."""
    found = LOOPBACK.fullmatch(listen)
    return int(found[1]) if found and int(found[1]) <= 65535 else None


def own_lines(env: Mapping[str, str], listen: str, host: Host) -> list[tuple[str, str]]:
    """The lines the demonstration adds to `<local>/.env`: the core's address, `listen`, and a client's token made
    anew, each only where `env`, the loaded environment, gives its name no value."""
    lines = []
    if not env.get(API_ADDRESS):
        lines.append((API_ADDRESS, listen))
    if not env.get(API_TOKEN):
        lines.append((API_TOKEN, host.secret()))
    return lines


def hashed(name: str, token: str) -> str:
    """A token's line in the token file holds this, the SHA-256 of its bytes in hex (D-025): its UTF-8, the bytes
    the file it was read from holds, which are a child's too (`encoded`, under the token's name in the
    environment)."""
    return hashlib.sha256(encoded(name, token)).hexdigest()


def token_lines(held: str, env: Mapping[str, str]) -> list[str]:
    """The lines the token file whose text is `held` lacks: `<sha256 hex> <principal>` for each token of `PRINCIPALS`
    that `env` holds and whose hash begins no line of `held`, so one line where the two tokens are one. A hash is
    never listed twice, which the core refuses at its start, and no line holds a token."""
    listed = {fields[0] for line in held.splitlines() if (fields := line.split())}
    lines = []
    for name, principal in PRINCIPALS:
        token = env.get(name)
        if token and hashed(name, token) not in listed:
            listed.add(hashed(name, token))
            lines.append(f"{hashed(name, token)} {principal}")
    return lines


def append(path: Path, lines: Sequence[str]) -> None:
    """`lines` appended to `path`, a newline added first where its last line has none and every byte there kept; a
    file made here is made at mode 0600, and one already there keeps its mode."""
    held = path.read_bytes() if path.exists() else b""
    ending = b"\n" if held and not held.endswith(b"\n") else b""
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "wb") as out:
        out.write(ending + "".join(f"{line}\n" for line in lines).encode())


def prepare(local: Path, env: Mapping[str, str], listen: str, host: Host) -> None:
    """What the demonstration needs under `local` that can be generated, made where it is missing: `<local>/demo/`,
    mode 0700; the core's token file there, empty, mode 0600; and `own_lines` appended to `<local>/.env`, whose names
    are said and whose values never are. What is there already is kept, byte for byte."""
    kept = records(local)
    home = kept.tokens.parent
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    home.chmod(0o700)
    if not kept.tokens.exists():
        os.close(os.open(kept.tokens, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    kept.tokens.chmod(0o600)
    lines = own_lines(env, listen, host)
    if lines:
        path = local / ".env"
        append(path, [f"{name}={value}" for name, value in lines])
        say(f"{path}: added {', '.join(name for name, _ in lines)}")


def step_env(env: Mapping[str, str], records: Records, listen: str) -> dict[str, str]:
    """A step's child's environment: `env`, the loaded one, with the core's address the listen address and the token
    file the demonstration's, which `make orchestrator-env` lists the runner's token in, and with no CA, since the
    demonstration's core serves HTTP."""
    given = {name: value for name, value in env.items() if name != API_CA}
    return given | {API_ADDRESS: listen, TOKENS: str(records.tokens)}


def make_env(env: Mapping[str, str], records: Records, listen: str) -> dict[str, str]:
    """Every make child's environment, each step's, the other source's stop and `down`'s targets alike: a step's
    (`step_env`) without make's own names (`MAKES_OWN`) and without every name the `Makefile` would take from it
    (`MAKE_VARIABLES`). `env` is the loaded environment, `<local>/.env` already laid over the shell's, so neither
    can put one back.

    make reads a variable from its environment and hands a command line's on in `MAKEFLAGS`: given the caller's, a
    `PURGE=1` exported in a shell, written in `<local>/.env` or given to `make netbox-demo` would make a stop that
    says "its volumes kept" remove them, a `SOURCE` drop a step, a branch's name have a seed delete and build
    another branch, and a flag pass over a failure. So a target's variables are those of its command line and no
    other (`make_words`, `stop_words`)."""
    given = step_env(env, records, listen)
    return {name: value for name, value in given.items() if name not in MAKES_OWN and name not in MAKE_VARIABLES}


def not_passed_on(env: Mapping[str, str], given: Sequence[str]) -> list[str]:
    """The names of `MAKE_VARIABLES` that `env`, the loaded environment, gives a value and that no make target will
    see so: all but `LOCAL`, which the script gives every target itself, and but one whose very word, `NAME=value`,
    is among `given`, the variables the command gives its targets on their command lines."""
    return [
        name
        for name in MAKE_VARIABLES
        if name != "LOCAL" and env.get(name) and f"{name}={env[name]}" not in given
    ]


def say_not_passed_on(env: Mapping[str, str], given: Sequence[str]) -> None:
    """Say once, by their names and never a value, the make variables the caller set that no target is given."""
    names = not_passed_on(env, given)
    if names:
        say(
            f"not passed on to the make targets: {', '.join(names)}; the demonstration runs each at the Makefile's "
            "own value"
        )


def core_env(env: Mapping[str, str], records: Records, listen: str) -> dict[str, str]:
    """The demonstration's core's environment: a step's, with the local driver, the demonstration's own store, this
    checkout's packages and the listen address, and with no certificate, key or lease. `<local>/.env`'s own token
    file and store are never the demonstration's core's, so every twin it lists is the demonstration's."""
    given = {name: value for name, value in step_env(env, records, listen).items() if name not in NOT_THE_CORES}
    return given | {
        "FYLGJA_DRIVER": "containerlab",
        STORE: str(records.store),
        "FYLGJA_PACKAGES": f"{ROOT / 'psp'}:{ROOT / 'probes'}",
        LISTEN: listen,
    }


def listeners(ss_output: str, port: int) -> list[str]:
    """The local addresses `ss -Hltn`'s lines listen on at `port`, whatever the address: `*:4200` and `[::]:4200`
    among them, `127.0.0.1:14200` never. `edge_dev.py`'s, held by value."""
    found = []
    for line in ss_output.splitlines():
        fields = line.split()
        if len(fields) >= 4 and fields[3].rpartition(":")[2] == str(port):
            found.append(fields[3])
    return found


def listener_pids(ss_output: str, port: int) -> set[int]:
    """The pids `ss -Hltnp`'s lines name for the listeners at `port`, whatever the address: each `pid=` of a line's
    `users:(("<name>",pid=<pid>,fd=<fd>),…)`. A listener that is another user's process is named none."""
    found: set[int] = set()
    for line in ss_output.splitlines():
        fields = line.split()
        if len(fields) >= 4 and fields[3].rpartition(":")[2] == str(port):
            found.update(int(pid) for pid in USER.findall(line.partition("users:(")[2]))
    return found


def owns(pid: int, listen: str, host: Host) -> bool:
    """Whether the listener at the port of `listen` is process `pid`'s own, by `ss -Hltnp`: only then is what answers
    there that process. An answer proves nothing of who gave it, and every twin the demonstration lists and destroys
    is to be its own core's. False too where `listen` is no address a port is read from, or `ss` is not read."""
    port = port_of(listen)
    if port is None:
        return False
    heard = host.run(["ss", "-Hltnp"], capture=True, timeout=DOCKER_TIMEOUT_S)
    return heard.status == 0 and pid in listener_pids(heard.out, port)


def pool_of(env: Mapping[str, str]) -> IPv4Network:
    """The local driver's pool as the server reads it from `env` (`fylgja_core.config.lab_pool`, reproduced here):
    `FYLGJA_LAB_POOL` where it has a value, an IPv4 network in CIDR form, no host bit set, of prefix 24 or shorter;
    `DEFAULT_POOL` where it is unset or empty. `ValueError`, whose text is the server's rule and holds no value, for
    a value that is no such network."""
    text = env.get(POOL, "")
    if not text:
        return IPv4Network(DEFAULT_POOL)
    try:
        if "/" not in text:  # a bare address reads as a /32
            raise ValueError(text)
        network = IPv4Network(text)
        if network.prefixlen > 24:
            raise ValueError(text)
    except ValueError:
        raise ValueError(f"{POOL} is not an IPv4 network in CIDR form that holds a /24") from None
    return network


def docker_networks(env: Mapping[str, str], host: Host) -> str:
    """Docker's answer for every network of the host's in `FORMAT`, asked in the local driver's own words
    (`fylgja_core.containerlab.driver`, `_docker_networks`): the networks' ids (`NETWORK_IDS`), then one `docker
    network inspect` of them all, never one a name; `""` where Docker lists none. Each is run under `env`, the
    loaded environment, as the checks ask Docker and as the core's driver will, so that it is the same daemon that
    is asked; each is given `DOCKER_TIMEOUT_S`, and one that exits other than 0 stops the run, exit 1, naming the
    command and its status."""
    listed = host.run(NETWORK_IDS, env=env, capture=True, timeout=DOCKER_TIMEOUT_S)
    if listed.status != 0:
        raise Stop(1, [f"`{' '.join(NETWORK_IDS)}` exited {listed.status}: Docker's networks were not read"])
    ids = listed.out.split()
    if not ids:
        return ""
    inspected = host.run(
        ["docker", "network", "inspect", "--format", FORMAT, *ids], env=env, capture=True, timeout=DOCKER_TIMEOUT_S
    )
    if inspected.status != 0:
        raise Stop(1, [f"`docker network inspect` exited {inspected.status}: Docker's networks were not read"])
    return inspected.out


def networks(answered: str) -> list[tuple[str, IPv4Network]]:
    """Each Docker network of `answered`, Docker's answer in `FORMAT`, with each IPv4 subnet it holds: a `(name,
    subnet)` pair a subnet, in the answer's order, as `fylgja_core.containerlab.pool.networks` reads it. A network
    with no IPv4 subnet gives nothing, and an IPv6 subnet is passed over. The answer is split on the newline alone,
    which ends a network's line: a name may hold what `str.splitlines` would split on."""
    found = []
    for line in answered.split("\n"):
        if not line.strip():
            continue
        name, end = json.JSONDecoder().raw_decode(line)
        for config in json.loads(line[end:]) or []:
            network = ip_network(config["Subnet"], strict=False) if config.get("Subnet") else None
            if isinstance(network, IPv4Network):
                found.append((str(name), network))
    return found


def holders(pool: IPv4Network, networks: Sequence[tuple[str, IPv4Network]]) -> list[tuple[str, IPv4Network]]:
    """The Docker networks that hold part of `pool`: each `(name, subnet)` of `networks` whose subnet overlaps it,
    one wider than the pool among them, sorted by name, then subnet (`pool.holders`)."""
    return sorted((name, subnet) for name, subnet in networks if subnet.overlaps(pool))


def chosen(pool: IPv4Network, taken: Sequence[IPv4Network]) -> IPv4Network | None:
    """The first /24 of `pool`, in address order, that overlaps no network of `taken`; None where none is free,
    which is where the local driver refuses a create (`pool.choose`)."""
    for subnet in pool.subnets(new_prefix=24):
        if not any(subnet.overlaps(other) for other in taken):
            return subnet
    return None


def refusal(pool: IPv4Network, holding: Sequence[tuple[str, IPv4Network]]) -> str:
    """What the local driver says of a pool with no free /24, byte for byte (`pool.refusal`): that it has none, each
    Docker network of `holding` by its name and subnet, and the setting that moves the pool. A name that is not
    plain is written as a JSON string."""
    held = ""
    if holding:
        named = ", ".join(
            f"{name if PLAIN.fullmatch(name) else json.dumps(name)} ({subnet})" for name, subnet in holding
        )
        held = f" Docker networks holding part of it: {named}."
    return (
        f"The pool {pool} has no /24 that neither a Docker network nor another twin holds.{held} Set {POOL} to an "
        "IPv4 network with a free /24, and start the core again."
    )


def pool_checked(source: str, pool: IPv4Network, env: Mapping[str, str], host: Host) -> None:
    """Once `source` is up, read Docker's networks, under `env`, and stop, exit 2, where they leave `pool` no /24:
    where the local driver would refuse the twin's create, and only there. The lines are the driver's own refusal,
    which names each network that overlaps the pool and the setting, and that the source is left up. Networks that
    overlap the pool while a /24 of it is free stop nothing, and nothing is said of them. An answer of Docker's that
    is not in the form asked for stops the run, exit 1."""
    try:
        found = networks(docker_networks(env, host))
    except (ValueError, TypeError, KeyError, AttributeError):
        raise Stop(1, ["`docker network inspect` printed what is not read: Docker's networks were not read"]) from None
    if chosen(pool, [subnet for _, subnet in found]) is None:
        raise Stop(
            2,
            [
                refusal(pool, holders(pool, found)),
                f"{source} is left up: set {POOL} in local/.env, then run make {source}-demo again",
            ],
        )


def apparmor(host: Host) -> list[str] | None:
    """The lines of `APPARMOR_LINES` that `APPARMOR_LOCAL` lacks, its comments and its spacing aside: none where
    `APPARMOR_PROFILE` is no file, since nothing confines rsyslogd so; both where the local file is absent. None
    where the local file is not this user's to read."""
    try:
        if host.text(Path(APPARMOR_PROFILE)) is None:
            return []
    except PermissionError:
        pass  # there, and not this user's to read: a profile all the same
    try:
        held = host.text(Path(APPARMOR_LOCAL)) or ""
    except PermissionError:
        return None
    lines = {" ".join(line.partition("#")[0].split()) for line in held.splitlines()}
    return [line for line in APPARMOR_LINES if line not in lines]


def quoted(lines: Sequence[str]) -> str:
    return " and ".join(f"`{line}`" for line in lines)


def notices(host: Host) -> list[str]:
    """What `up` says of the host that is no stop: where `APPARMOR_LOCAL` is not this user's to read, the two lines
    to check it for."""
    if apparmor(host) is None:
        return [f"cannot read {APPARMOR_LOCAL}: check that it holds {quoted(APPARMOR_LINES)}"]
    return []


def available_mb(meminfo: str | None) -> int | None:
    """`MemAvailable` of `/proc/meminfo`'s text, in whole MiB; None where it names none."""
    for line in (meminfo or "").splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] == "MemAvailable:" and fields[1].isdigit():
            return int(fields[1]) // 1024
    return None


def prefect_home(local: Path) -> Path:
    """The edge's Prefect's home under `local`, `edge_dev.py`'s: its server's and every runner's `PREFECT_HOME`, and
    where `make prefect-up` records its server's pid, in `server.pid`."""
    return local / "prefect"


def recorded(path: Path, host: Host) -> int | None:
    """The pid the file `path` names; None where there is no such file or it names none."""
    try:
        return int((host.text(path) or "").strip())
    except ValueError:
        return None


def is_prefect(process: Process | None, local: Path) -> bool:
    """Whether a process is the Prefect server of `local`, as `make prefect-up` itself reads one up already
    (`edge_dev.is_ours`, reproduced and held to it by a test): a word of its command line is named `prefect`,
    `server` is among them, and its `PREFECT_HOME` is `prefect_home(local)`. A pid another process has since taken,
    another home's server and a worker are none."""
    return (
        process is not None
        and any(Path(word).name == "prefect" for word in process.argv)
        and "server" in process.argv
        and process.environ.get(PREFECT_HOME) == str(prefect_home(local))
    )


def prefect_recorded(local: Path, host: Host) -> bool:
    """Whether `<local>/prefect/server.pid`, `make prefect-up`'s, names this `local`'s Prefect server, up
    (`is_prefect`): the one case in which that target starts none, and in which port 4200 is its own."""
    pid = recorded(prefect_home(local) / "server.pid", host)
    return pid is not None and is_prefect(host.process(pid), local)


def checks(
    source: str, env: Mapping[str, str], *, local: Path, ref: str, host: Host, room: bool | None = None
) -> list[str]:
    """The host's preconditions for a demonstration of `source` that are not met, a sentence each and none where all
    are: what only the host's owner can give. `env` is the loaded environment, and `ref` the branch Infrahub
    registers this repository at.

    They are of two parts, which `up` asks for apart, and which keep one order when asked together:

    - **what no stop can cure** (`room=False`), asked before anything is settled or stopped, so that nothing is
      stopped for a run that could never start: the venv's commands; the tools on PATH; Docker's daemon, its Compose
      plugin and containerlab, each answering; the two groups, but for root; the AppArmor widening, where the
      profile is; the node login in `<local>/.env`; a listen address on loopback; a pool that is one; and for
      Infrahub a branch that names a commit;
    - **the host's room** (`room=True`), asked once an earlier run is settled and the other source stopped, since
      each holds some of it: memory for the twin and the edge, and for the source where it is not up; and the ports
      of the core, the edge's Prefect and the source, each free but where its own holder is recorded or running.

    With `room` None both are asked, the room's sentences in their place, after the AppArmor widening's.

    A check that needs a tool is left out where the tool is not on PATH, which the first part says, and what rests
    on whether the source is up, the memory and the source's port, where the Docker daemon does not say. Asked for
    alone, the room takes the daemon to answer, the first part having asked it."""
    failing: list[str] = []
    listen = listen_of(env)
    cure, judge_room = room is not True, room is not False

    def read(*argv: str, cwd: Path | None = None) -> Done:
        return host.run(argv, env=env, cwd=cwd, capture=True, timeout=DOCKER_TIMEOUT_S)

    on_path = {name: host.which(name) is not None for name in TOOLS}
    answers = on_path["docker"]
    if cure:
        lacking = [name for name in COMMANDS if host.which(str(VENV / "bin" / name)) is None]
        if lacking:
            failing.append(f"{VENV} lacks {', '.join(lacking)}: run make venv")

        failing += [f"{name} is not on PATH" for name in TOOLS if not on_path[name]]

        if on_path["docker"]:
            info = read("docker", "info")
            if info.status != 0:
                answers = False
                failing.append(f"`docker info` exited {info.status}: the Docker daemon does not answer this user")
            compose = read("docker", "compose", "version")
            if compose.status != 0:
                failing.append(f"`docker compose version` exited {compose.status}: Docker's Compose plugin is needed")
        if on_path["containerlab"]:
            version = read("containerlab", "version")
            if version.status != 0:
                failing.append(f"`containerlab version` exited {version.status}")

        if host.euid() != 0:
            held = host.groups()
            for group in GROUPS:
                gid = host.gid(group)
                if gid is None:
                    failing.append(f"the host has no group {group}")
                elif gid not in held:
                    failing.append(
                        f"this process is not in the group {group}: add the user to it and log in again, since a "
                        "group added reaches no process begun before it"
                    )

        missing = apparmor(host)
        if missing:
            failing.append(
                f"{APPARMOR_LOCAL} lacks {quoted(missing)}: SR Linux's rsyslogd needs them on Ubuntu; add them as "
                f'root and reload the profile with apparmor_parser -r {APPARMOR_PROFILE} (design/verified-facts.md, '
                '"Ubuntu hosts")'
            )

    if judge_room:
        source_up: bool | None = None  # None: not read
        if answers:
            listed = read(*up_argv(source))
            if listed.status != 0:
                failing.append(f"`docker ps` exited {listed.status}: whether {source} is up was not read")
            else:
                source_up = bool(listed.out.split())

        if source_up is not None:
            have = available_mb(host.text(Path("/proc/meminfo")))
            need = TWIN_MB + (0 if source_up else SOURCE_MB[source])
            if have is None:
                failing.append("/proc/meminfo names no MemAvailable: the memory available was not read")
            elif have < need:
                parts = (
                    f"for the twin and the edge, {source} being up"
                    if source_up
                    else f"{SOURCE_MB[source]} for {source}, which is not up, and {TWIN_MB} for the twin and the edge"
                )
                failing.append(
                    f"{have} MiB of memory is available and the {source} demonstration needs {need}: {parts}"
                )

        if on_path["ss"]:
            heard = read("ss", "-Hltn")
            if heard.status != 0:
                failing.append(f"`ss -Hltn` exited {heard.status}: the listeners were not read")
            else:
                needed: list[tuple[int, str]] = []
                port = port_of(listen)
                if port is not None:
                    needed.append((port, "the core"))
                if not prefect_recorded(local, host):
                    needed.append((PREFECT_PORT, "the edge's Prefect"))
                if source_up is False:
                    needed.append((PORTS[source], source))
                for port, needs in needed:
                    found = listeners(heard.out, port)
                    if found:
                        failing.append(
                            f"port {port} is listened on at {found[0].rpartition(':')[0]} by a process the "
                            f"demonstration did not start, and {needs} needs it"
                        )

    if not cure:
        return failing
    path = local / ".env"
    if host.text(path) is None:
        failing.append(f"{path} is not there: make it, mode 0600, with {' and '.join(LOGIN)} (.env.example)")
    else:
        unset = [name for name in LOGIN if not env.get(name)]
        if unset:
            failing.append(
                f"local/.env gives {' and '.join(unset)} no value: add the lines; the image's documented default "
                "login is enough (.env.example)"
            )

    if port_of(listen) is None:
        failing.append(LISTEN_REFUSED)

    try:
        pool_of(env)
    except ValueError as refused:
        failing.append(str(refused))

    if source == "infrahub":
        if not ref:
            failing.append(
                "no branch is checked out and REF names none: Infrahub registers this repository at a branch; check "
                "one out, or give REF=<branch>"
            )
        elif on_path["git"] and (
            # A ref git would read as an option names no branch, and git is not given it.
            ref.startswith("-")
            or read("git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", cwd=ROOT).status != 0
        ):
            failing.append(f"REF names {ref}, which is no commit of this repository")
    return failing


def serve_argv(source: str, local: Path, main: Path) -> list[str]:
    """The words `make orchestrator-serve SOURCE=<source>` runs, which become the runner of `source`: held to the
    recipe by a test."""
    edge = ["python3", "-I", "scripts/edge_dev.py", "serve"]
    return [*edge, "--source", source, "--local", str(local), "--main", str(main)]


def api_argv(local: Path, main: Path) -> list[str]:
    """The words `make netbox-hook` reads Prefect's API by, which print it as the host reaches it."""
    return ["python3", "-I", "scripts/edge_dev.py", "api", "--local", str(local), "--main", str(main)]


def is_core(process: Process | None, records: Records) -> bool:
    """Whether a process is the demonstration's core, whatever checkout it runs from: a word of its command line is a
    path named `fylgja-core-server`, and its store is the demonstration's, the one under the main checkout's
    `local/`, by its resolved path. A reused pid, a core of another store and a child of the core's, which inherits
    its environment, are never read as it, nor ended."""
    return (
        process is not None
        and any(Path(word).name == CORE.name for word in process.argv)
        and process.environ.get(STORE) == str(records.store)
    )


def is_runner(process: Process | None, local: Path) -> bool:
    """Whether a process is a runner that serves the Prefect of `local`, whatever checkout it runs from: a word of
    its command line is named `fylgja-orchestrator`, `serve` is among them, and its `PREFECT_HOME` is
    `prefect_home(local)`. `edge_dev.py serve` is none until it has become the runner."""
    return (
        process is not None
        and any(Path(word).name == RUNNER_COMMAND for word in process.argv)
        and "serve" in process.argv
        and process.environ.get(PREFECT_HOME) == str(prefect_home(local))
    )


def is_becoming_runner(process: Process | None, local: Path) -> bool:
    """Whether a process is `edge_dev.py serve` as the script starts it for `local`, before it has become the runner:
    its command line is the words `serve_argv` gives for a source of `SOURCES` and this `--local`, whatever `--main`,
    and no word more. For about three seconds after its start this is what a recorded runner's pid reads as."""
    if process is None or len(process.argv) != len(serve_argv(SOURCES[0], local, ROOT)):
        return False
    return any(process.argv[:-1] == serve_argv(source, local, ROOT)[:-1] for source in SOURCES)


def runners(local: Path, host: Host) -> list[tuple[int, str]]:
    """Every runner that serves the Prefect of `local`: its pid, and the change source it serves, `""` where its
    environment names none."""
    found = []
    for pid in host.pids():
        process = host.process(pid)
        if process is not None and is_runner(process, local):
            found.append((pid, process.environ.get(RUNNER_SOURCE, "")))
    return found


def refuse_runners(source: str, records: Records, local: Path, host: Host) -> None:
    """Stop, exit 2, beside a runner that a demonstration of `source` may not end and cannot share Prefect with,
    each said and nothing started or stopped: one under the home that `runner.pid` does not name, which this
    demonstration did not start; and the recorded one where it serves the other source, since either source's runner
    serves the same two deployments. This source's own recorded runner is none: `settle` ends it."""
    ours = recorded(records.runner_pid, host)
    refused = []
    for pid, serves in runners(local, host):
        if pid != ours:
            refused.append(
                f"a runner this demonstration did not start serves {prefect_home(local)}, pid {pid}: stop it by its "
                "pid"
            )
        elif serves != source:
            refused.append(
                f"the {serves if serves in SOURCES else 'other'} demonstration's runner is up, pid {pid}: one "
                "Prefect serves one source's runner; run make demo-down first"
            )
    if refused:
        raise Stop(2, refused)


def start_recorded(
    what: str, argv: Sequence[str], env: Mapping[str, str], pid_file: Path, log: Path, host: Host
) -> int:
    """`argv` started in a session of its own under `env`, in the checkout, and its pid: the log of the start
    before is kept as `<log>.1`, so that `log` is this start's own, and the pid is written to `pid_file` at once. A
    command that cannot be started stops the run, exit 1, said in the error's own word with the command's path and
    the log's, and nothing of `env` or of the other words; no pid file is left. No child runs unrecorded: where its
    pid cannot be written it is ended, and the run stops, exit 1, saying so, or that it still stands."""
    if log.exists():
        log.replace(log.with_name(f"{log.name}.1"))
    try:
        pid = host.start(argv, env=env, cwd=ROOT, log=log)
    except OSError as refused:
        pid_file.unlink(missing_ok=True)
        raise Stop(
            1, [f"the {what} was not started, {word_of(refused)}: its command is {argv[0]} and its log {log}"]
        ) from None
    try:
        pid_file.write_text(f"{pid}\n")
    except OSError as refused:
        gone = end(pid, host, lambda process: process is not None)
        raise Stop(
            1,
            [
                f"the {what}, pid {pid}, was started and its pid could not be written to {pid_file}, "
                f"{word_of(refused)}: {'it was ended' if gone else 'it still stands, and is to be ended by its pid'}"
            ],
        ) from None
    return pid


def word_of(refused: OSError) -> str:
    """An error of the host's in its own word, `os.strerror`'s, and never its text, which may hold more."""
    return os.strerror(refused.errno) if refused.errno else type(refused).__name__


def start_core(env: Mapping[str, str], records: Records, listen: str, host: Host) -> int:
    """Start the demonstration's core at `listen`, in a session of its own under `core_env`, and wait until it
    answers `GET /v1/version`, which needs no token, asked every `ASK_S`; its pid, recorded in `core.pid`.

    Nothing is started where anything listens at the port already (`ss -Hltn`): what answers there is not the
    demonstration's core, and no core of its own could bind beside it. Stop, exit 1; likewise where the listeners
    are not read, or `listen` is no address a port is read from. Before the start the store is marked unsettled
    (`Records.unsettled`), since from then on it may hold a twin that only a list through this core finds.

    An answer of 200 counts only while the pid still reads as the core and `ss -Hltnp` names that pid for the
    port's listener (`owns`): a 200 proves nothing of who answered, and a child just started is alive whoever
    answers. One the pid does not own is no answer, and the wait goes on. Where the process is gone first the record
    is removed and the run stops, exit 1, naming its log; where `CORE_WAIT_S` passes it stops, exit 1, the core left
    up and recorded, and named by its pid for the user to end: `down` ends one that has come to listen by then, and
    leaves one that has not."""
    port = port_of(listen)
    if port is None:
        raise Stop(1, [LISTEN_REFUSED])
    heard = host.run(["ss", "-Hltn"], capture=True, timeout=DOCKER_TIMEOUT_S)
    if heard.status != 0:
        raise Stop(
            1, [f"`ss -Hltn` exited {heard.status}: whether port {port} is free was not read, and no core was started"]
        )
    held = listeners(heard.out, port)
    if held:
        raise Stop(
            1,
            [
                f"port {port} is listened on at {held[0].rpartition(':')[0]} by a process the demonstration did not "
                "start: its core cannot start there, and no twin was read"
            ],
        )
    records.unsettled.touch()
    core = core_env(env, records, listen)
    pid = start_recorded("core", [str(CORE)], core, records.core_pid, records.core_log, host)
    begun = host.clock()
    while host.clock() - begun < CORE_WAIT_S:
        answered = host.ask("GET", f"http://{listen}/v1/version").status == 200
        if not is_core(host.process(pid), records):
            records.core_pid.unlink(missing_ok=True)
            raise Stop(1, [f"the core exited before it answered: read {records.core_log}"])
        if answered and owns(pid, listen, host):
            say(f"the core answers at {listen}, pid {pid}, its log {records.core_log}")
            return pid
        host.sleep(ASK_S)
    raise Stop(
        1,
        [
            f"the core did not answer at {listen} within {CORE_WAIT_S} s: read {records.core_log}; end it by its "
            f"pid, {pid}, then run make demo-down"
        ],
    )


def prefect_api(env: Mapping[str, str], local: Path, main: Path, host: Host) -> str:
    """Prefect's API as the host reaches it, `http://<the bind>:4200/api` with no slash after it: what `edge_dev.py
    api` prints under `env`, a step's environment, as `make netbox-hook` reads it. `Host.ask` follows no redirect,
    so every address built on this is exact. Stop, exit 1, where the command exits other than 0 or prints anything
    but one http address with no login, query or fragment."""
    argv = api_argv(local, main)
    words = " ".join(argv[:4])
    done = host.run(argv, env=env, cwd=ROOT, capture=True, timeout=DOCKER_TIMEOUT_S)
    if done.status != 0:
        raise Stop(1, [f"`{words}` exited {done.status}: Prefect's API was not read"])
    api = done.out.strip().rstrip("/")
    scheme, _, rest = api.partition("://")
    if scheme != "http" or not AFTER_THE_SCHEME.fullmatch(rest):
        raise Stop(1, [f"`{words}` printed no http address alone: Prefect's API was not read"])
    return api


def start_runner(
    source: str, env: Mapping[str, str], records: Records, local: Path, main: Path, listen: str, host: Host
) -> int:
    """Start the runner of `source` by the words `make orchestrator-serve` runs, in a session of its own under a
    step's environment, of which `edge_dev.py` makes the runner's own, and wait until it serves; its pid, recorded
    in `runner.pid`.

    It serves once all three hold, read every `ASK_S`: this start's log holds the runner's line; the pid reads as
    the runner, which `edge_dev.py serve` has then become; and Prefect answers both deployments by name with the
    status `READY`, asked with the basic auth of `env`. None alone says so: a runner that has stopped leaves both
    `READY` by name. Prefect's API is read first, and where it is not read nothing is started. Where the process is
    gone first the record is removed and the run stops, exit 1, naming its log; where `SERVE_WAIT_S` passes it
    stops, exit 1, the runner left up and recorded for `down` to end."""
    given = step_env(env, records, listen)
    api = prefect_api(given, local, main, host)
    argv = serve_argv(source, local, main)
    pid = start_recorded("runner", argv, given, records.runner_pid, records.runner_log, host)
    deployments = [f"{flow}/{DEPLOYMENT}" for flow in (PLAN_FLOW, FLOW)]

    def ready(deployment: str) -> bool:
        answer = host.ask("GET", f"{api}/deployments/name/{deployment}", auth=env.get(AUTH) or None)
        return answer.status == 200 and isinstance(answer.body, dict) and answer.body.get("status") == READY

    begun = host.clock()
    while host.clock() - begun < SERVE_WAIT_S:
        process = host.process(pid)
        if process is None:
            records.runner_pid.unlink(missing_ok=True)
            raise Stop(1, [f"the runner exited before it served: read {records.runner_log}"])
        if (
            SERVING in (host.text(records.runner_log) or "")
            and is_runner(process, local)
            and all(ready(deployment) for deployment in deployments)
        ):
            say(f"the runner serves {' and '.join(deployments)}, pid {pid}, its log {records.runner_log}")
            return pid
        host.sleep(ASK_S)
    raise Stop(
        1,
        [
            f"the runner did not serve {' and '.join(deployments)} within {SERVE_WAIT_S} s: read "
            f"{records.runner_log}; make demo-down ends it"
        ],
    )


def end(pid: int, host: Host, ours: Callable[[Process | None], bool]) -> bool:
    """End the process `pid` that `ours` reads as the caller's, and answer whether it is gone: SIGTERM to the session
    it leads, and SIGKILL where it still stands `STOP_WAIT_S` later, as `edge_dev.end_session`, then `KILL_WAIT_S`
    for it to be gone, so that what it held is free.

    A signal rests on the latest reading: `/proc` is read by `ours` immediately before each, and a pid that no
    longer reads as the caller's is not signalled, the caller's process being gone. False where the process stands
    after SIGKILL and its wait, or stands and could not be signalled."""
    if not ours(host.process(pid)):
        return True
    if not host.signal(pid, signal.SIGTERM):
        return not ours(host.process(pid))
    for number, wait in ((signal.SIGKILL, STOP_WAIT_S), (None, KILL_WAIT_S)):
        begun = host.clock()
        while host.clock() - begun < wait:
            if not ours(host.process(pid)):
                return True
            host.sleep(STOP_POLL_S)
        if not ours(host.process(pid)):
            return True
        if number is not None:
            host.signal(pid, number)
    return False


def held(path: Path, what: str, ours: Callable[[Process | None], bool], host: Host) -> tuple[int, Process] | None:
    """The pid the record `path` names with its process, where that reads as what the file says, by `ours`: the
    one case in which a recorded pid is signalled. In any other the file is removed and one line said, and None
    answered: a file that names no pid, a pid that names no process, and a pid that by now names another process,
    which is left as it is. None, with nothing said, where there is no file."""
    if host.text(path) is None:
        return None
    pid = recorded(path, host)
    process = None if pid is None else host.process(pid)
    if pid is not None and process is not None and ours(process):
        return pid, process
    path.unlink(missing_ok=True)
    if pid is None:
        say(f"{path} names no pid: the file removed")
    elif process is None:
        say(f"the {what} recorded in {path}, pid {pid}, is gone: the file removed")
    else:
        say(f"pid {pid} of {path} is not the demonstration's {what}: it is left, and the file removed")
    return None


def client_env(env: Mapping[str, str], listen: str) -> dict[str, str]:
    """The core's CLI's environment: `env`, the loaded one, whose `FYLGJA_API_TOKEN` is the client's, with the
    core's address `listen` and no CA, since the demonstration's core serves HTTP."""
    return {name: value for name, value in env.items() if name != API_CA} | {API_ADDRESS: listen}


def twins(env: Mapping[str, str], listen: str, host: Host) -> list[str]:
    """The names of the twins the core at `listen` lists, by `fylgja-core twin list --json`, given its address and
    its token by its environment alone. Stop, exit 1, where the command exits other than 0 or prints anything but a
    list of records that each have a name."""
    asked = "`fylgja-core twin list --json`"
    done = host.run(
        [str(CLI), "twin", "list", "--json"],
        env=client_env(env, listen),
        cwd=ROOT,
        capture=True,
        timeout=DOCKER_TIMEOUT_S,
    )
    if done.status != 0:
        raise Stop(1, [f"{asked} exited {done.status}: the twins of the core at {listen} were not read"])
    try:
        listed = json.loads(done.out)
    except ValueError:
        listed = None
    if not isinstance(listed, list) or not all(
        isinstance(record, dict) and isinstance(record.get("name"), str) for record in listed
    ):
        raise Stop(1, [f"{asked} printed no list of twins: those of the core at {listen} were not read"])
    return [record["name"] for record in listed]


def port_freed(listen: str, host: Host) -> None:
    """Wait until nothing listens at the port of `listen`, by `ss -Hltn` read every `PORT_FREE_POLL_S`, for at most
    `PORT_FREE_WAIT_S`: a core the script has just ended can hold its port for a moment after its process is gone,
    and a core started at once at the same address would be refused for a listener that is the script's own. Past
    the bound, or where `ss` is not read, the start's own read of the port decides."""
    port = port_of(listen)
    begun = host.clock()
    while port is not None and host.clock() - begun < PORT_FREE_WAIT_S:
        heard = host.run(["ss", "-Hltn"], capture=True, timeout=DOCKER_TIMEOUT_S)
        if heard.status != 0 or not listeners(heard.out, port):
            return
        host.sleep(PORT_FREE_POLL_S)


def ended(what: str, pid: int, ours: Callable[[Process | None], bool], pid_file: Path, host: Host) -> None:
    """End the recorded process `pid`, remove its record and say that it ended; where it still stands, stop the
    run, exit 1, naming it, its record kept: nothing is said to be ended that is not."""
    if not end(pid, host, ours):
        raise Stop(
            1,
            [
                f"the {what}, pid {pid}, still stands after SIGKILL, or could not be signalled: its record {pid_file} "
                "is kept; end it by its pid, then run make demo-down again"
            ],
        )
    pid_file.unlink(missing_ok=True)
    say(f"the {what}, pid {pid}, ended")


def settle(env: Mapping[str, str], records: Records, local: Path, listen: str, host: Host) -> None:
    """End what an earlier run left, so that a demonstration leaves no twin, process or listener behind it; signal
    nothing but a process read as the recorded runner or core (`held`, and `end` again before each signal); and list
    and destroy through nothing but a core whose pid owns its listener (`owns`).

    Where `listen` is no address a port is read from, nothing is done: Stop, exit 1, with the check's sentence.

    The recorded runner is ended and `runner.pid` removed: given SIGTERM it cancels the flow run it was running,
    whose own clean-up asks its twin's deletion (design/verified-facts.md, "Prefect 3.9.2", 2026-11-14). The recorded
    pid is the demonstration's runner where it reads as the runner, and where it is still `edge_dev.py serve` by the
    words the script started it by, which becomes the runner (`is_becoming_runner`).

    The core's part goes by the marker `unsettled`, which `start_core` writes before it starts a core and which is
    removed here alone, once a list through an owned core has answered empty. With no marker the store was read
    empty, and nothing is asked of it: a recorded core is ended as a recorded pid is. With the marker, every twin
    the store holds is destroyed through a core:

    - the recorded core where it is up, asked at its own listen address, and only where it owns the listener there:
      where it does not, or its address is none a port is read from, what answers may be another's, and the run
      stops, exit 1, no twin read and the core left up;
    - where that core does not list its twins, why is said, it is ended, its port waited for where a core is to be
      started at the same one (`port_freed`), and it is replaced;
    - else, and where no core is recorded up, one started for the purpose at `listen` (`start_core`), since a twin
      outlives the core that made it and is listed by the next over the same store.

    Each twin listed is asked destroyed by `fylgja-core twin destroy`, which waits for its verdict, within
    `DESTROY_TIMEOUT_S`, and the list is read again. A twin still on it, or a list that is not read through the
    core started or after the destroys, stops the run, exit 1, saying why and naming the core, which is left up and
    recorded, the marker standing. An empty list removes the marker, and the core is then ended and `core.pid`
    removed.

    Who owns the listener is read again immediately before each destroy; before the list that follows the destroys,
    since a destroy waits minutes at the longest and that list goes, with the client's token, to whatever is at the
    address; and after the list that answers empty, before the marker is removed: the core may have gone since the
    last reading and another process be at its address. Where it no longer owns it the run stops, exit 1, the store
    not read whole and the marker standing.

    Nothing of Docker is read: a lab's container that no twin names is not this script's to find."""
    if port_of(listen) is None:
        raise Stop(1, [LISTEN_REFUSED])

    def the_runner(process: Process | None) -> bool:
        return is_runner(process, local) or is_becoming_runner(process, local)

    def the_core(process: Process | None) -> bool:
        return is_core(process, records)

    def left_up(pid: int, address: str) -> str:
        return (
            f"the core, pid {pid}, is left up at {address}: read {records.core_log}, then run make demo-down again"
        )

    def still_owned(pid: int, address: str) -> None:
        if not owns(pid, address, host):
            raise Stop(
                1,
                [
                    f"the core, pid {pid}, is no longer shown by `ss -Hltnp` to listen at {address}: the store was "
                    "not read whole, since what answers there may be another's; run make demo-down again"
                ],
            )

    runner = held(records.runner_pid, "runner", the_runner, host)
    if runner is not None:
        ended("runner", runner[0], the_runner, records.runner_pid, host)

    core = held(records.core_pid, "core", the_core, host)
    if host.text(records.unsettled) is None:
        if core is not None:
            ended("core", core[0], the_core, records.core_pid, host)
        return

    pid, address = 0, listen
    left: list[str] | None = None
    if core is not None:
        pid, address = core[0], core[1].environ.get(LISTEN) or DEFAULT_LISTEN
        if port_of(address) is None:
            raise Stop(
                1,
                [
                    f"the core, pid {pid}, was given a {LISTEN} that is not 127.0.0.1:<port>: no twin was read "
                    "through it; it is left up: end it by its pid, then run make demo-down again"
                ],
            )
        if not owns(pid, address, host):
            raise Stop(
                1,
                [
                    f"the core, pid {pid}, is not shown by `ss -Hltnp` to listen at {address}: no twin was read, "
                    "since what answers there may be another's; it is left up: end it by its pid if it never "
                    "listens, then run make demo-down again"
                ],
            )
        try:
            left = twins(env, address, host)
        except Stop as unread:
            for line in unread.lines:
                say(line)
            say(f"ending the core, pid {pid}, which did not list its twins, to start one that does")
            ended("core", pid, the_core, records.core_pid, host)
            if port_of(address) == port_of(listen):
                port_freed(listen, host)
    if left is None:
        say(f"starting a core at {listen}, to end what the store of an earlier one holds")
        pid, address = start_core(env, records, listen, host), listen
        try:
            left = twins(env, address, host)
        except Stop as unread:
            raise Stop(1, [*unread.lines, left_up(pid, address)]) from None

    for name in left:
        still_owned(pid, address)
        say(f"destroying the twin {name}, which an earlier run left")
        destroyed = host.run(
            [str(CLI), "twin", "destroy", name], env=client_env(env, address), cwd=ROOT, timeout=DESTROY_TIMEOUT_S
        )
        if destroyed.status != 0:
            say(f"`fylgja-core twin destroy {name}` exited {destroyed.status}")
    if left:
        still_owned(pid, address)
        try:
            still = twins(env, address, host)
        except Stop as unread:
            raise Stop(1, [*unread.lines, left_up(pid, address)]) from None
        if still:
            raise Stop(1, [f"still standing after its destroy: {', '.join(still)}; {left_up(pid, address)}"])
    still_owned(pid, address)
    records.unsettled.unlink(missing_ok=True)
    ended("core", pid, the_core, records.core_pid, host)


def make_words(target: str, local: Path, *variables: str) -> list[str]:
    """The words a make target is run by, in the checkout: `LOCAL` given, since `local` is the main checkout's
    whatever checkout this is, then the target's own variables."""
    return ["make", "--no-print-directory", target, f"LOCAL={local}", *variables]


def stop_words(source: str, local: Path, purge: bool = False) -> list[str]:
    """The words a source is stopped by: its own `down` target, with `PURGE=1` where `purge` and `PURGE=` where
    not, on the command line, which make takes before anything its environment holds: a stop that is no purge says
    so itself."""
    return make_words(f"{source}-down", local, "PURGE=1" if purge else "PURGE=")


class Step(NamedTuple):
    """One step of a source's runbook: a make target with its variables (`kind` `make`), or the start of the core or
    of the runner (`core`, `runner`), which no target makes in the background; and how many times it is asked
    before its failure ends the run."""

    kind: str
    target: str = ""
    variables: tuple[str, ...] = ()
    asks: int = 1


REF = "REF="
"""The variable `make infrahub-register` is given its branch by: `make_argv` writes the branch after it."""

STEPS: dict[str, tuple[Step, ...]] = {
    "infrahub": (
        Step("make", "infrahub-up", asks=3),
        Step("make", "orchestrator-env"),
        Step("core"),
        Step("make", "infrahub-up"),
        Step("make", "infrahub-register", (REF,), asks=2),
        Step("make", "prefect-up"),
        Step("runner"),
        Step("make", "infrahub-seed", ("PROPOSED_CHANGE=1",)),
    ),
    "netbox": (
        Step("make", "netbox-up"),
        Step("make", "netbox-seed"),
        Step("make", "orchestrator-env", ("SOURCE=netbox",)),
        Step("core"),
        Step("make", "prefect-up"),
        Step("runner"),
        Step("make", "netbox-hook"),
        Step("make", "netbox-change", ("NETBOX_TAG=1",)),
    ),
}
"""Each source's runbook, in its order (CONTRIBUTING.md, "Running the example orchestrator" and "With NetBox"), held
to those blocks by a test.

The core is started where each runbook says to restart it, once its token file is whole, so it is started once.
Infrahub's seed is taken once, last, with its proposed change, as NetBox's change is its last with its tag: the
runbook seeds before Prefect is up, and a proposed change opened before the runner serves fails its check.

Infrahub's first `infrahub-up` is asked up to three times: on kept volumes the target was read to exit other than 0
while Infrahub's database was still unhealthy and to pass when run again, on the second ask on 2026-11-14 and the
third on 2026-11-13; a first value. Its registration is asked twice, as its runbook says. Every other step is asked
once."""

STEP_WORDS = {"core": "the core", "runner": "the runner"}
"""How a step that is no make target is said."""


def variables_of(step: Step, ref: str) -> list[str]:
    """A make step's variables as it is run with them: the registration's `REF` given `ref`, the branch."""
    return [f"{REF}{ref}" if variable == REF else variable for variable in step.variables]


def make_argv(step: Step, local: Path, ref: str) -> list[str]:
    """The words a make step is run by (`make_words`): its target, `LOCAL` and its variables. Nothing of the
    environment is among them: a child is given its secrets by its environment alone."""
    return make_words(step.target, local, *variables_of(step, ref))


def words_of(step: Step, ref: str) -> str:
    """A step as it is said: a make step by its target and its variables, the core and the runner by name."""
    if step.kind != "make":
        return STEP_WORDS[step.kind]
    return " ".join(["make", step.target, *variables_of(step, ref)])


def pull(env: Mapping[str, str], host: Host) -> None:
    """Pull each image of `IMAGES` that Docker does not hold, so that no pull counts against a twin's deploy: each
    is asked of Docker, `docker image inspect`, which exits 0 for one it holds and 1 for one it does not, and one it
    does not hold is pulled, `docker pull`, printing as it will, within `PULL_TIMEOUT_S`; each under `env`, the
    loaded environment, as the checks ask Docker and as the core's driver will. A pull that exits other than 0, and
    a read that exits neither 0 nor 1, stops the run, exit 1, naming the command and its status."""
    for ref in IMAGES:
        held = host.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", ref],
            env=env,
            capture=True,
            timeout=DOCKER_TIMEOUT_S,
        )
        if held.status == 0:
            continue
        if held.status != 1:
            raise Stop(
                1, [f"`docker image inspect {ref}` exited {held.status}: whether Docker holds the image was not read"]
            )
        say(f"pulling {ref}, which Docker does not hold")
        pulled = host.run(["docker", "pull", ref], env=env, timeout=PULL_TIMEOUT_S)
        if pulled.status != 0:
            raise Stop(1, [f"`docker pull {ref}` exited {pulled.status}: the image the twin runs was not pulled"])


def up_argv(source: str) -> list[str]:
    """The words that read whether `source` is up: its Compose project's running containers, by their ids."""
    return ["docker", "ps", "-q", "--filter", f"label=com.docker.compose.project={PROJECTS[source]}"]


def alone(source: str, env: Mapping[str, str], records: Records, local: Path, listen: str, host: Host) -> None:
    """Stop the other source where it is up, before `source` is brought up: either source, up, starts
    `stage-plan/main` and `twin-rehearse/main` by name, Infrahub's task workers and NetBox's webhook. Where any
    container of the other's Compose project runs, that is said in one line and its own `down` target is run, by
    `stop_words`, whose `PURGE=` no environment can undo, under a make child's environment (`make_env`): its volumes
    are kept. A `down` that exits other than 0 stops the run, exit 1, with nothing else started. Where `docker` is
    not on PATH, or its read exits other than 0, nothing is stopped: the checks say what is wrong with Docker."""
    if host.which("docker") is None:
        return
    for other in SOURCES:
        if other == source:
            continue
        listed = host.run(up_argv(other), env=env, capture=True, timeout=DOCKER_TIMEOUT_S)
        if listed.status != 0 or not listed.out.split():
            continue
        say(f"{other} is up: stopping it, its volumes kept, since it starts the same deployments")
        stopped = host.run(stop_words(other, local), env=make_env(env, records, listen), cwd=ROOT)
        if stopped.status != 0:
            raise Stop(
                1, [f"make {other}-down exited {stopped.status}: {other} is still up, and nothing was started"]
            )


class Unanswered(Exception):
    """A read of Prefect's that was not answered as asked: nothing answered, a status other than 200, or a body that is
    not what was asked for. It is asked again at the next poll. Its text says which read, never a request's."""


class NoRun(Stop):
    """No run of the change's was listed within `APPEAR_WAIT_S`: `up` says where its source shows why."""


class NotEnded(Stop):
    """The change's run did not end within `RUN_WAIT_S`: `up` names the runner's log."""


@dataclass(frozen=True)
class Prefect:
    """The edge's Prefect at `api`, `http://<the bind>:4200/api` as `prefect_api` reads it, asked through `host` with
    the basic auth `auth`, the `user:password` of `FYLGJA_ORCHESTRATOR_AUTH`, which `Host.ask` sends in a header it
    builds and which is in no URL, body or line, and is never shown (`repr`). Each address is `<api>/<path>`, one
    slash between, exact, since no redirect is followed. A 401 to any request stops the run at once, exit 1, naming
    the variable and never its value; any other answer is the caller's to judge."""

    api: str
    auth: str = field(repr=False)
    host: Host = field(repr=False)

    def get(self, path: str) -> Answer:
        return self._answered(self.host.ask("GET", f"{self.api}/{path}", auth=self.auth or None))

    def post(self, path: str, body: Any) -> Answer:
        return self._answered(self.host.ask("POST", f"{self.api}/{path}", auth=self.auth or None, body=body))

    def _answered(self, answer: Answer) -> Answer:
        if answer.status == 401:
            raise Stop(1, [f"Prefect at {self.api} refused the edge's credential ({AUTH})"])
        return answer


class Run(NamedTuple):
    """A flow run as Prefect lists it: its id, its state's type (`RUNNING`, `CRASHED`, ...) and its state's name
    (`Running`, `TimedOut` for a run past its time limit, ...), and the branch its parameters name, `""` where they
    name none."""

    id: str
    state: str
    name: str
    branch: str


def deployment(prefect: Prefect, flow: str) -> str:
    """The id of the deployment `<flow>/main`, by its name. Stop, exit 1, where Prefect answers none."""
    answer = prefect.get(f"deployments/name/{flow}/{DEPLOYMENT}")
    ident = answer.body.get("id") if answer.status == 200 and isinstance(answer.body, dict) else None
    if not isinstance(ident, str) or not ident:
        how = "did not answer" if answer.status is None else f"answered HTTP {answer.status}"
        raise Stop(1, [f"Prefect at {prefect.api} {how} for the deployment {flow}/{DEPLOYMENT}: no id was read"])
    return ident


def runs_body(deployment_id: str) -> dict[str, Any]:
    """The body of `POST /api/flow_runs/filter` that lists the deployment's runs, newest first, `RUNS_LIMIT` of them
    (design/verified-facts.md, "Prefect 3.9.2", 2026-11-14)."""
    return {
        "flow_runs": {"deployment_id": {"any_": [deployment_id]}},
        "sort": "EXPECTED_START_TIME_DESC",
        "limit": RUNS_LIMIT,
    }


def created(row: Any) -> datetime:
    """When a run was made, by its row's `created`; one written with no zone is UTC. `ValueError` where it names no
    time."""
    if not isinstance(row, dict) or not isinstance(row.get("created"), str):
        raise ValueError("no created")
    made = datetime.fromisoformat(row["created"])
    return made if made.tzinfo is not None else made.replace(tzinfo=UTC)


def run_of(row: Any) -> Run:
    """A row of the list as a `Run`; `ValueError` where it has no id or state type."""
    ident = row.get("id") if isinstance(row, dict) else None
    state = row.get("state") if isinstance(row, dict) else None
    kind = state.get("type") if isinstance(state, dict) else None
    if not isinstance(ident, str) or not ident or not isinstance(kind, str) or not isinstance(state, dict):
        raise ValueError("no run")
    name = state.get("name")
    parameters = row.get("parameters")
    branch = parameters.get("branch") if isinstance(parameters, dict) else None
    return Run(ident, kind, name if isinstance(name, str) else "", branch if isinstance(branch, str) else "")


def listed(prefect: Prefect, deployment_id: str) -> list[Run]:
    """The deployment's runs as Prefect lists them (`runs_body`), oldest first by their creation. `Unanswered` where
    nothing answered, the status is other than 200, or the body is not a list of runs that each have an id, a state
    type and a time of creation."""
    answer = prefect.post("flow_runs/filter", runs_body(deployment_id))
    if answer.status != 200 or not isinstance(answer.body, list):
        raise Unanswered(f"the list of the runs of {FLOW}/{DEPLOYMENT}")
    try:
        rows = sorted(((created(row), run_of(row)) for row in answer.body), key=lambda each: each[0])
    except ValueError:
        raise Unanswered(f"the list of the runs of {FLOW}/{DEPLOYMENT}") from None
    return [run for _, run in rows]


def document_body(run_id: str) -> dict[str, Any]:
    """The body of `POST /api/artifacts/filter` that asks for the document the run filed, as the checks' glue asks
    for it (`fylgja_glue.Prefect.document`, held to it by a test)."""
    return {
        "artifacts": {"flow_run_id": {"any_": [run_id]}, "type": {"any_": [ARTIFACT_TYPE]}},
        "sort": "CREATED_DESC",
        "limit": 1,
    }


def document(prefect: Prefect, run_id: str) -> dict[str, Any] | None:
    """The document the run filed, as the glue reads it: the newest artifact of `ARTIFACT_TYPE` of the run, its
    `data` a JSON string, parsed, or an object, taken as it is; None where the run filed none. `Unanswered` where
    nothing answered, the status is other than 200 or the body is no list; Stop, exit 1, where the artifact's data is
    no JSON object, which no reading of it again would mend."""
    answer = prefect.post("artifacts/filter", document_body(run_id))
    if answer.status != 200 or not isinstance(answer.body, list):
        raise Unanswered(f"the read of flow run {run_id}'s document")
    if not answer.body:
        return None
    data = answer.body[0].get("data") if isinstance(answer.body[0], dict) else None
    try:
        held = json.loads(data) if isinstance(data, str) else data
    except ValueError:
        held = None
    if not isinstance(held, dict):
        raise Stop(
            1,
            [
                f"Prefect at {prefect.api} answered flow run {run_id}'s document with an artifact whose data is no "
                "JSON object"
            ],
        )
    return held


def follow(prefect: Prefect, deployment_id: str, known: frozenset[str], host: Host) -> Run:
    """The change's flow run of the deployment, once it has ended: the first made of the runs whose ids are not in
    `known`, the ids listed just before the change was opened, so that no run of an earlier change, ended or left
    running, is ever taken for it.

    Asked every `POLL_S` (`listed`) from the moment it is called, the last step's return: until `APPEAR_WAIT_S` after
    that for a new run, saying how many where there are several, and then until `RUN_WAIT_S` after its listing for
    its state to be one of `ENDED`, saying each state it is listed in once. By the host's clock, and no ask at or after
    a bound. A list unanswered (`Unanswered`) is asked again at the next poll and ends nothing by itself; a 401 stops
    the run at once (`Prefect`). No new run in time is `NoRun`, and no end in time `NotEnded`, each exit 1."""
    begun = host.clock()
    run: Run | None = None
    while run is None:
        if host.clock() - begun >= APPEAR_WAIT_S:
            raise NoRun(1, [f"no run of {FLOW}/{DEPLOYMENT} was started within {APPEAR_WAIT_S} s of the change"])
        try:
            new = [each for each in listed(prefect, deployment_id) if each.id not in known]
        except Unanswered:
            new = []
        if not new:
            host.sleep(POLL_S)
            continue
        run, appeared = new[0], host.clock()
        if len(new) > 1:
            say(
                f"{len(new)} runs of {FLOW}/{DEPLOYMENT} were started since the change: following the first made, "
                f"flow run {run.id}"
            )
        say(f"flow run {run.id} of {FLOW}/{DEPLOYMENT}: {run.state}")
    while run.state not in ENDED:
        host.sleep(POLL_S)
        if host.clock() - appeared >= RUN_WAIT_S:
            raise NotEnded(
                1,
                [
                    f"flow run {run.id} of {FLOW}/{DEPLOYMENT} had not ended {RUN_WAIT_S} s after it was listed, "
                    f"{run.state}"
                ],
            )
        try:
            now = next((each for each in listed(prefect, deployment_id) if each.id == run.id), None)
        except Unanswered:
            now = None
        if now is None:
            continue
        if now.state != run.state:
            say(f"flow run {run.id} of {FLOW}/{DEPLOYMENT}: {now.state}")
        run = now
    return run


def filed(prefect: Prefect, run: Run, until: float, log: Path, host: Host) -> dict[str, Any] | None:
    """The document the ended run filed (`document`), None where it filed none: a read unanswered is asked again
    every `POLL_S`, until `until` by the host's clock, with no ask at or after it. Past it, Stop, exit 1, naming the
    runner's log `log`."""
    while host.clock() < until:
        try:
            return document(prefect, run.id)
        except Unanswered:
            host.sleep(POLL_S)
    raise Stop(
        1,
        [
            f"flow run {run.id} of {FLOW}/{DEPLOYMENT} ended {run.name or run.state}, and Prefect did not answer the "
            f"read of its document: read {log}"
        ],
    )


def keep(path: Path, held: Mapping[str, Any]) -> None:
    """The document read, written to `path` as JSON, at mode 0600 from its creation, as the token file is; one there
    already is replaced, and its mode made 0600."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as out:
        os.fchmod(out.fileno(), 0o600)
        out.write(json.dumps(held, indent=2) + "\n")


def readout(
    source: str, run: Run, document: Mapping[str, Any] | None, env: Mapping[str, str], local: Path
) -> tuple[int, list[str]]:
    """The exit status and the last lines of an `up` that read its verdict: 0 for a document whose `status` is
    `PASSED`, and 1 for any other and for none. First what the run concluded; then, where it filed a document, where
    a person reads its report, in the source, at its address as `env`, the loaded environment, gives it, the change
    named by the run's own branch, signing in as admin with the password named by its variable and never given; last,
    always, where the document is kept and what is left up, which `make demo-down` ends."""
    kept = records(local)
    left = f"the core, the runner, Prefect and {source} are left up: make demo-down ends them"
    if document is None:
        return 1, [
            f"flow run {run.id} ended {run.name or run.state} and filed no rehearsal: read {kept.runner_log}",
            f"no document was filed; {left}",
        ]
    status = document.get("status")
    if status == PASSED:
        stages = document.get("stages")
        first = (
            f"the rehearsal passed: {len(stages) if isinstance(stages, list) else 0} stages, "
            f"{document.get('took_s')} s, flow run {run.id}"
        )
    else:
        first = f"the rehearsal ended {status}, not passed: flow run {run.id}"
    if source == "infrahub":
        change = proposed_change(local)
        named = f' "{change}"' if change else ""
        where = (
            f"the report is in Infrahub at {env.get('FYLGJA_INFRAHUB_ADDRESS', '')}: the proposed change{named} of the "
            f'branch {run.branch}, its thread "{THREAD}"; sign in as admin with the password local/.env holds as '
            "INFRAHUB_INITIAL_ADMIN_PASSWORD"
        )
    else:
        where = (
            f"the report is in NetBox at {env.get('FYLGJA_NETBOX_ADDRESS', '')}: the branch {run.branch}, its Journal "
            "tab, the newest entry; sign in as admin with the password local/.env holds as "
            "FYLGJA_NETBOX_SUPERUSER_PASSWORD"
        )
    return 0 if status == PASSED else 1, [first, where, f"the document is {kept.rehearsal}; {left}"]


def proposed_change(local: Path) -> str | None:
    """The name of the proposed change `<local>/infrahub/seed.json` records, which `make infrahub-seed
    PROPOSED_CHANGE=1` wrote; None where the file is absent, unread or names none."""
    try:
        seeded = json.loads((local / "infrahub" / "seed.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    change = seeded.get("proposed_change") if isinstance(seeded, dict) else None
    name = change.get("name") if isinstance(change, dict) else None
    return name if isinstance(name, str) and name else None


def locked(local: Path, host: Host) -> None:
    """Hold `<local>/demo/lock` until this process ends: one demonstration command runs at a time, and a second
    stops here, exit 2."""
    lock = records(local).lock
    if not host.lock(lock):
        raise Stop(2, [f"another demonstration command holds {lock}: one runs at a time"])


def left_up(source: str, env: Mapping[str, str], records: Records, local: Path, host: Host) -> str:
    """The last line of an `up` that ends before a verdict, a Ctrl-C's among them: what stands, and the target that
    ends it. After a verdict, everything the demonstration started is up, and `readout` says so.

    `source`, where a container of its Compose project runs, read of Docker now (`up_argv`) and not taken from what
    the run did, since it may have been up before; where Docker does not say, that is said. The core and the
    runner, each where its recorded pid still reads as it. The edge's Prefect, where this `local`'s server is
    recorded (`prefect_recorded`), whoever started it: `make demo-down` ends the one the demonstration started, and
    no other. A core that does not listen at its address (`owns`) is named so, and as what `make demo-down` leaves:
    it reads no twin through a core it cannot show to be listening, so that one is ended by its pid."""
    standing = []
    listed = host.run(up_argv(source), env=env, capture=True, timeout=DOCKER_TIMEOUT_S)
    if listed.status != 0:
        standing.append(f"{source}, if it is up, which Docker did not say")
    elif listed.out.split():
        standing.append(source)
    deaf: int | None = None
    core = recorded(records.core_pid, host)
    process = None if core is None else host.process(core)
    if core is not None and process is not None and is_core(process, records):
        if owns(core, process.environ.get(LISTEN) or DEFAULT_LISTEN, host):
            standing.append(f"the core (pid {core})")
        else:
            deaf = core
            standing.append(f"the core (pid {core}), which does not listen")
    if prefect_recorded(local, host):
        standing.append("the edge's Prefect")
    runner = recorded(records.runner_pid, host)
    if runner is not None:
        serving = host.process(runner)
        if is_runner(serving, local) or is_becoming_runner(serving, local):
            standing.append(f"the runner (pid {runner})")
    if not standing:
        return "nothing the demonstration starts is left up"
    ends = "make demo-down ends what the demonstration started"
    if deaf is not None:
        ends += f", but for the core, which it leaves while it does not listen: end it by its pid, {deaf}"
    return f"left up: {', '.join(standing)}; {ends}"


def up(source: str, local: Path, main: Path, ref: str, environ: Mapping[str, str], host: Host) -> int:
    """A demonstration of `source`, to its rehearsal's verdict. In order:

    - the lock, and the environment, `<local>/.env` laid over `environ`;
    - `refuse_runners`: beside a runner it may not end, nothing is started or stopped, exit 2;
    - the checks no stop can cure (`checks`, `room=False`), with `notices` said first: exit 2 with every one not
      met, and nothing settled, stopped or started, so that nothing is stopped for a run that could never start;
    - once, the make variables the caller set that no target is given, by their names (`say_not_passed_on`);
    - `settle`, so that an earlier run's runner, core and twins hold no port or memory; the listen address reads,
      the checks having said so;
    - `alone`: the other source stopped where it is up;
    - the checks of the host's room (`checks`, `room=True`), its memory and its ports, judged with the earlier run
      settled and the other source stopped: exit 2 with each not met;
    - `prepare`, then the record of `source`, then `pull`;
    - the steps of `STEPS[source]`, each said first, `<local>/.env` read again before each: a make step run as a
      child under `make_env`, its variables its command line's alone, printing as it will, with no bound of the
      script's, and asked again while it has asks left, each further ask said; the core and the runner started
      (`start_core`, `start_runner`). After the first, the pool (`pool_checked`). After `make orchestrator-env`, the
      token file is given the lines it lacks (`token_lines`), so the core is started over a file that lists both
      its tokens. Before `make prefect-up` whether this `local`'s server is recorded is read, and after it
      `prefect.pid` is written where none was and one is, whatever the step's status: only a server the step
      started is the demonstration's to end.

    - before the last step, the one that opens the change, Prefect's API read again under a step's environment, the
      id of `twin-rehearse/main` and the ids of its runs listed then (`known`); after it, the change's run waited
      for (`follow`), from the step's return, and the document it filed read (`filed`) within the wait's whole
      bound, kept in `rehearsal.json` (`keep`), and the readout said (`readout`): its status is `up`'s, 0 for
      `passed` alone, its lines on stdout for 0 and on stderr for 1.

    From `settle` on, every way out but the readout says last what is left up, with `make demo-down` (`left_up`): a
    step that fails, exit 1, `step <i>, make <target>, exited <n>`, or the core's or the runner's own lines after its
    step, no later step being run; the pool's refusal and a check of the room, exit 2; a line a step wrote into
    `<local>/.env` that is not read, exit 2 at the next read; Prefect not read before the change, its run not started
    or not ended in time, its document not read, or the edge's credential refused, exit 1; and an error of the
    host's, exit 1, in its own word. A Ctrl-C anywhere once the lock is held is exit 130, said, with the same last
    line. `main`, the main checkout, is what the runner's words and the read of Prefect's API are given (`serve_argv`,
    `api_argv`); each target finds the main checkout itself."""
    locked(local, host)
    env: Mapping[str, str] = environ
    kept = records(local)
    try:
        env = loaded(local, environ, host)
        return verdict_of(source, local, main, ref, environ, env, kept, host)
    except KeyboardInterrupt:
        raise Stop(130, ["up was interrupted", left_up(source, env, kept, local, host)]) from None


def verdict_of(
    source: str,
    local: Path,
    main: Path,
    ref: str,
    environ: Mapping[str, str],
    env: Mapping[str, str],
    kept: Records,
    host: Host,
) -> int:
    """`up` once its lock is held and the environment loaded: everything from the runners refused to the readout."""
    listen = listen_of(env)
    refuse_runners(source, kept, local, host)
    for line in notices(host):
        say(line)
    failing = checks(source, env, local=local, ref=ref, host=host, room=False)
    if failing:
        raise Stop(2, failing)
    steps = STEPS[source]
    say_not_passed_on(env, ["PURGE=", *(word for step in steps for word in variables_of(step, ref))])

    def made(number: int, step: Step) -> None:
        """A make step, asked until it exits 0 or has no ask left, `<local>/.env` read again before each ask."""
        argv = make_argv(step, local, ref)
        served_before = step.target == "prefect-up" and prefect_recorded(local, host)
        exited = 0
        for ask in range(1, step.asks + 1):
            exited = host.run(argv, env=make_env(loaded(local, environ, host), kept, listen), cwd=ROOT).status
            if exited == 0 or ask == step.asks:
                break
            say(f"step {number}, make {step.target}, exited {exited}: asking it again, {ask + 1} of {step.asks}")
        if step.target == "prefect-up" and not served_before and prefect_recorded(local, host):
            kept.prefect_pid.write_text(f"{recorded(prefect_home(local) / 'server.pid', host)}\n")
        if exited != 0:
            raise Stop(1, [f"step {number}, make {step.target}, exited {exited}"])
        if step.target == "orchestrator-env":
            lines = token_lines(host.text(kept.tokens) or "", loaded(local, environ, host))
            if lines:
                append(kept.tokens, lines)
            for line in lines:
                say(f"{kept.tokens}: listed the principal {line.split()[1]} by its token's hash")

    try:
        settle(env, kept, local, listen, host)
        alone(source, env, kept, local, listen, host)
        short = checks(source, env, local=local, ref=ref, host=host, room=True)
        if short:
            raise Stop(2, short)
        say("the host's checks passed")
        pool = pool_of(env)
        prepare(local, env, listen, host)
        kept.source.write_text(f"{source}\n")
        pull(env, host)
        prefect: Prefect | None = None
        rehearse, known = "", frozenset[str]()
        for number, step in enumerate(steps, 1):
            if number == len(steps):
                given = loaded(local, environ, host)
                api = prefect_api(step_env(given, kept, listen), local, main, host)
                prefect = Prefect(api, given.get(AUTH, ""), host)
                rehearse = deployment(prefect, FLOW)
                try:
                    known = frozenset(run.id for run in listed(prefect, rehearse))
                except Unanswered as unread:
                    raise Stop(1, [f"Prefect at {api} did not answer {unread}: the change was not opened"]) from None
            say(f"step {number} of {len(steps)}: {words_of(step, ref)}")
            if step.kind == "make":
                made(number, step)
            else:
                again = loaded(local, environ, host)
                try:
                    if step.kind == "core":
                        start_core(again, kept, listen, host)
                    else:
                        start_runner(source, again, kept, local, main, listen, host)
                except Stop as failed:
                    first, *rest = failed.lines
                    raise Stop(failed.status, [f"step {number}, {STEP_WORDS[step.kind]}: {first}", *rest]) from None
            if number == 1:
                pool_checked(source, pool, loaded(local, environ, host), host)
        assert prefect is not None  # the last step is the change's, and the list was read before it
        returned = host.clock()
        try:
            run = follow(prefect, rehearse, known, host)
        except NoRun as late:
            raise Stop(1, [f"{late.lines[0]}: {WHERE_TO_LOOK[source]}"]) from None
        except NotEnded as late:
            raise Stop(1, [f"{late.lines[0]}: read {kept.runner_log}"]) from None
        held = filed(prefect, run, returned + APPEAR_WAIT_S + RUN_WAIT_S, kept.runner_log, host)
        if held is not None:
            keep(kept.rehearsal, held)
        exited, lines = readout(source, run, held, loaded(local, environ, host), local)
    except Stop as stop:
        raise Stop(stop.status, [*stop.lines, left_up(source, env, kept, local, host)]) from None
    except OSError as refused:
        where = f": {refused.filename}" if refused.filename else ""
        cut = f"up was cut short, {word_of(refused)}{where}"
        raise Stop(1, [cut, left_up(source, env, kept, local, host)]) from None
    for line in lines:
        if exited == 0:
            say(line)
        else:
            fail(line)
    return exited


def down(local: Path, main: Path, purge: bool, environ: Mapping[str, str], host: Host) -> int:
    """Take the lock, and end what the demonstration recorded under `local` started: 0 where everything it had to
    end is ended and its store is settled, and where nothing is recorded, neither `source` nor the marker nor a
    core's or a runner's pid, with nothing done. Where the marker or a pid is there with no `source`, `settle` is run
    all the same, no source and no Prefect server is stopped, which is said, and the exit is by the marker.

    Three acts, each tried whatever the one before did or raised, a failure of each said, an error of the host's by
    its own word, and the exit 1 where any failed: `settle`, the runner, every twin and the core; `make
    prefect-down`, only where `prefect.pid` names the pid `make prefect-up` has recorded, the server it started for
    the demonstration, the record then removed, and a record that names any other removed with nothing stopped; and
    `make <source>-down`, with `PURGE=1` where `purge` and `PURGE=` where not (`stop_words`). Each target is run
    under a make child's environment (`make_env`), so no variable of the caller's reaches it; those the caller set
    are said first, once, by their names (`say_not_passed_on`). The exit is 1 too wherever the marker `unsettled` still
    stands at the end: a `down` that could not read the store never passes for one that found it empty. `source` is
    kept, so that a later `down` with `purge` knows whose volumes to remove. `main` is taken as `up` takes it and is
    not read: each target finds the main checkout itself. A Ctrl-C once the lock is held is exit 130: the failures
    met so far are said, then that it was interrupted, then the line that says not everything was ended."""
    locked(local, host)
    failed: list[str] = []
    try:
        return ended_all(local, purge, environ, failed, host)
    except KeyboardInterrupt:
        for line in failed:
            fail(line)
        fail("down was interrupted")
        return fail("down: not everything was ended: read the lines above, then run make demo-down again", 130)


def ended_all(local: Path, purge: bool, environ: Mapping[str, str], failed: list[str], host: Host) -> int:
    """`down` once its lock is held, each failure added to `failed` as it comes, so that a Ctrl-C still says them."""
    kept = records(local)
    home = kept.source.parent
    named = host.text(kept.source)
    if named is None and all(host.text(left) is None for left in (kept.unsettled, kept.core_pid, kept.runner_pid)):
        say(f"no demonstration is recorded under {home}: nothing to end")
        return 0
    source = "" if named is None else named.strip()
    env = loaded(local, environ, host)
    listen = listen_of(env)

    def tried(what: str, act: Callable[[], None]) -> None:
        try:
            act()
        except Stop as stop:
            failed.extend(stop.lines)
        except OSError as refused:
            where = f": {refused.filename}" if refused.filename else ""
            failed.append(f"{what} was cut short, {word_of(refused)}{where}")

    def make(words: Sequence[str]) -> bool:
        made = host.run(words, env=make_env(env, kept, listen), cwd=ROOT)
        if made.status != 0:
            failed.append(f"make {words[2]} exited {made.status}")
        return made.status == 0

    def prefect_down() -> None:
        if host.text(kept.prefect_pid) is None:
            return
        server = prefect_home(local) / "server.pid"
        ours = recorded(kept.prefect_pid, host)
        if ours is None or ours != recorded(server, host):
            kept.prefect_pid.unlink(missing_ok=True)
            say(
                f"{kept.prefect_pid} does not name the Prefect server {server} names: whatever serves there is left, "
                "and the file removed"
            )
        elif make(make_words("prefect-down", local)):
            kept.prefect_pid.unlink(missing_ok=True)

    def source_down() -> None:
        if source in SOURCES:
            make(stop_words(source, local, purge))
        else:
            failed.append(f"{kept.source} names neither {' nor '.join(SOURCES)}: no source was stopped")

    say_not_passed_on(env, ["PURGE=1" if purge else "PURGE="])
    tried("the end of the runner, the twins and the core", lambda: settle(env, kept, local, listen, host))
    if named is None:
        say(f"no source is recorded under {home}: neither a source nor the Prefect server was stopped")
    else:
        tried("make prefect-down", prefect_down)
        tried(f"make {source}-down" if source in SOURCES else "the source's stop", source_down)
    if host.text(kept.unsettled) is not None:
        failed.append(
            f"{kept.unsettled} stands: the demonstration's store was not read empty through a core of its own"
        )

    for line in failed:
        fail(line)
    if failed:
        return fail("down: not everything was ended: read the lines above, then run make demo-down again")
    if named is None:
        say(f"what was recorded under {home} is ended")
    else:
        say(f"the {source} demonstration is ended: its records stay under {home}")
    return 0


def parser() -> argparse.ArgumentParser:
    made = argparse.ArgumentParser(prog="demo.py", description=(__doc__ or "").splitlines()[0])
    verbs = made.add_subparsers(dest="verb", required=True)
    for verb in ("up", "down"):
        each = verbs.add_parser(verb)
        if verb == "up":
            each.add_argument("source", choices=SOURCES, help="the source of truth the demonstration is of")
            each.add_argument(
                "--ref", required=True, help="the branch Infrahub registers this repository at; empty where none is"
            )
        else:
            each.add_argument("--purge", action="store_true", help="remove the sources' volumes too")
        each.add_argument("--local", type=Path, required=True, help="the main checkout's local/")
        each.add_argument("--main", type=Path, required=True, help="the main checkout")
    return made


def main(argv: Sequence[str], *, environ: Mapping[str, str] = os.environ, host: Host | None = None) -> int:
    try:
        args = parser().parse_args(argv)
    except SystemExit as e:
        return 0 if e.code in (0, None) else 2
    local, main_checkout = args.local.absolute(), args.main.absolute()
    on: Host = Real() if host is None else host
    try:
        if args.verb == "up":
            return up(args.source, local, main_checkout, args.ref, environ, on)
        return down(local, main_checkout, args.purge, environ, on)
    except Stop as stop:
        for line in stop.lines:
            fail(line)
        return stop.status
    except OSError as e:
        return fail(f"{args.verb}: {e}")
    except KeyboardInterrupt:
        return fail(f"{args.verb} was interrupted", 130)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
