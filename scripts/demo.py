#!/usr/bin/env python3
"""A demonstration on the development host: one source of truth's runbook, from nothing running to a rehearsal's
verdict, with no step by hand beyond the host's stated preconditions (design/core.md, "Phase 10"; D-104).

Run from the repository root as `python3 -I scripts/demo.py up {infrahub|netbox} --local <local> --main <main
checkout> --ref <branch or empty>` and `python3 -I scripts/demo.py down --local <local> --main <main checkout>
[--purge]`. The standard library alone; no script imports another, and this one is never installed.

- `up` holds `<local>/demo/lock` while it runs, reads the environment, the shell's overlaid by `<local>/.env`, and
  judges the host's preconditions, `checks`: what only the host's owner can give. Every one that fails is said in a
  line of its own, and nothing is started. Where they pass it says so.
- `down` holds the same lock. What it ends is not built yet, and it says so.

What the script keeps is under `<local>/demo/` (`records`). What it writes that can be generated, `prepare`: that
directory, the token file its core reads, and in `<local>/.env`, where the loaded environment gives the name no
value, the core's address and a client's token. No value of `<local>/.env` is ever printed: a refusal names a
variable by its name and a line by its number.

Every process, socket, file of the host's and clock the script touches goes through one seam, `Host`, and `Real` is
its one implementation.

Exit 0; 1 for a failure; 2 for a command line not understood, a precondition of the host's not met, a line of
`<local>/.env` that is not read as a shell would read it, a value that is not UTF-8 or that a child would not be
given as the file has it, or another demonstration command running. Each is said on stderr.
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
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from email.message import Message
from ipaddress import IPv4Network
from pathlib import Path
from typing import IO, Any, NamedTuple, Protocol

ROOT = Path(__file__).resolve().parent.parent
"""The checkout this file is in: every child's working directory, and whose venv and packages the core runs from."""

SOURCES = ("infrahub", "netbox")
"""The sources of truth a demonstration is of."""

VENV = ROOT / "core" / ".venv"
COMMANDS = ("fylgja-core-server", "fylgja-core", "fylgja-orchestrator", "prefect")
"""What a demonstration runs from `VENV`'s `bin`, which `make venv` puts there."""

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

LISTEN = "FYLGJA_LISTEN"
DEFAULT_LISTEN = "127.0.0.1:7650"
"""The server's setting of its listen address, and the address where it gives none, the core's own default."""

API_ADDRESS = "FYLGJA_API_ADDRESS"
API_TOKEN = "FYLGJA_API_TOKEN"
API_CA = "FYLGJA_API_CA"
RUNNER_TOKEN = "FYLGJA_ORCHESTRATOR_API_TOKEN"
TOKENS = "FYLGJA_TOKENS"

PRINCIPALS = ((API_TOKEN, "demo"), (RUNNER_TOKEN, "orchestrator"))
"""The two tokens the demonstration's core knows, each by its name in the environment, with the principal its hash
is listed under in the token file (D-025): the client's, and the runner's, which `make orchestrator-env` makes."""

NOT_THE_CORES = ("FYLGJA_TLS_CERT", "FYLGJA_TLS_KEY", "FYLGJA_LEASE")
"""Settings the demonstration's core is never given: it serves HTTP on loopback, over a store that is a directory."""

REQUEST_TIMEOUT_S = 30
"""Seconds one request is given to answer."""

DOCKER_TIMEOUT_S = 60
"""Seconds one read of the host by a child is given, of `docker`, `containerlab`, `ss` or `git`: `netbox_dev.py`'s
bound for an inspection."""

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
        parts = [part.decode(errors="replace") for part in argv.split(b"\0") if part]
        pairs = [entry.decode(errors="replace").partition("=") for entry in environ.split(b"\0") if b"=" in entry]
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
    and the runner's logs; the core's store and its token file; the lock; and the last rehearsal's document."""

    source: Path
    core_pid: Path
    runner_pid: Path
    prefect_pid: Path
    core_log: Path
    runner_log: Path
    store: Path
    tokens: Path
    lock: Path
    rehearsal: Path


def records(local: Path) -> Records:
    home = local / "demo"
    return Records(
        source=home / "source",
        core_pid=home / "core.pid",
        runner_pid=home / "runner.pid",
        prefect_pid=home / "prefect.pid",
        core_log=home / "core.log",
        runner_log=home / "runner.log",
        store=home / "store",
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
    that is not carried (`unfit`), each said by its name alone: every value here is valid UTF-8, the shell's and the
    file's alike, and one the file gives is a child's as the file has it."""
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
    refused = [said for name, value in env.items() if (said := unfit(name, value, of_the_file=name in held))]
    if refused:
        raise Stop(2, refused)
    return env


def unfit(name: str, value: str, *, of_the_file: bool = True) -> str | None:
    """What is said of a value the script does not carry, by its name alone, and None for one it does.

    No value holds a byte that is not UTF-8, which `Host.text` hands on as a surrogate, and under a locale of UTF-8
    the process's environment too: the script writes a value into a line, sends one in a header and hashes one,
    each as UTF-8. And a value `<local>/.env` gives is one the process's locale gives a child as the file has it,
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


def core_env(env: Mapping[str, str], records: Records, listen: str) -> dict[str, str]:
    """The demonstration's core's environment: a step's, with the local driver, the demonstration's own store, this
    checkout's packages and the listen address, and with no certificate, key or lease. `<local>/.env`'s own token
    file and store are never the demonstration's core's, so every twin it lists is the demonstration's."""
    given = {name: value for name, value in step_env(env, records, listen).items() if name not in NOT_THE_CORES}
    return given | {
        "FYLGJA_DRIVER": "containerlab",
        "FYLGJA_STORE": str(records.store),
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


def prefect_recorded(local: Path, host: Host) -> bool:
    """Whether `<local>/prefect/server.pid`, `make prefect-up`'s, names a live process: whose it is, and whether the
    port is its, is that target's to judge."""
    try:
        pid = int((host.text(local / "prefect" / "server.pid") or "").strip())
    except ValueError:
        return False
    return host.process(pid) is not None


def checks(source: str, env: Mapping[str, str], *, local: Path, ref: str, host: Host) -> list[str]:
    """The host's preconditions for a demonstration of `source` that are not met, a sentence each and none where all
    are: what only the host's owner can give, judged before anything is started. `env` is the loaded environment,
    and `ref` the branch Infrahub registers this repository at.

    In order: the venv's commands; the tools on PATH; Docker's daemon, its Compose plugin and containerlab, each
    answering; the two groups, but for root; the AppArmor widening, where the profile is; memory for the twin and
    the edge, and for the source where it is not up; the ports of the core, the edge's Prefect and the source, each
    free but where its own holder is recorded or running; the node login in `<local>/.env`; a listen address on
    loopback; a pool that is one; and for Infrahub a branch that names a commit.

    A check that needs a tool is left out where the tool is not on PATH, which is said, and what rests on whether
    the source is up, the memory and the source's port, where the Docker daemon does not say."""
    failing: list[str] = []
    listen = listen_of(env)

    def read(*argv: str, cwd: Path | None = None) -> Done:
        return host.run(argv, env=env, cwd=cwd, capture=True, timeout=DOCKER_TIMEOUT_S)

    lacking = [name for name in COMMANDS if host.which(str(VENV / "bin" / name)) is None]
    if lacking:
        failing.append(f"{VENV} lacks {', '.join(lacking)}: run make venv")

    on_path = {name: host.which(name) is not None for name in TOOLS}
    failing += [f"{name} is not on PATH" for name in TOOLS if not on_path[name]]

    answers = on_path["docker"]
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
                    f"this process is not in the group {group}: add the user to it and log in again, since a group "
                    "added reaches no process begun before it"
                )

    missing = apparmor(host)
    if missing:
        failing.append(
            f"{APPARMOR_LOCAL} lacks {quoted(missing)}: SR Linux's rsyslogd needs them on Ubuntu; add them as root "
            f'and reload the profile with apparmor_parser -r {APPARMOR_PROFILE} (design/verified-facts.md, "Ubuntu '
            'hosts")'
        )

    source_up: bool | None = None  # None: not read
    if answers:
        listed = read("docker", "ps", "-q", "--filter", f"label=com.docker.compose.project={PROJECTS[source]}")
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
            failing.append(f"{have} MiB of memory is available and the {source} demonstration needs {need}: {parts}")

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
                        f"port {port} is listened on at {found[0].rpartition(':')[0]} by a process the demonstration "
                        f"did not start, and {needs} needs it"
                    )

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
        failing.append(
            f"{LISTEN} is not 127.0.0.1:<port>: the demonstration's core serves HTTP on loopback; set it so in "
            "local/.env, or delete the line"
        )

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


def locked(local: Path, host: Host) -> None:
    """Hold `<local>/demo/lock` until this process ends: one demonstration command runs at a time, and a second
    stops here, exit 2."""
    lock = records(local).lock
    if not host.lock(lock):
        raise Stop(2, [f"another demonstration command holds {lock}: one runs at a time"])


def up(source: str, local: Path, main: Path, ref: str, environ: Mapping[str, str], host: Host) -> int:
    """Take the lock, read the environment and judge the host: `Stop`, exit 2, with every precondition not met and
    nothing started; else say that they passed. `main`, the main checkout, is not read yet."""
    locked(local, host)
    env = loaded(local, environ, host)
    for line in notices(host):
        say(line)
    failing = checks(source, env, local=local, ref=ref, host=host)
    if failing:
        raise Stop(2, failing)
    say("the host's checks passed")
    return 0


def down(local: Path, main: Path, purge: bool, environ: Mapping[str, str], host: Host) -> int:
    """Take the lock. What `down` ends is not built yet: it says so, and is never exit 0, which would say that all
    is ended; nothing it is given but `local` is read yet."""
    locked(local, host)
    return fail("down: not built yet, and nothing was ended")


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


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
