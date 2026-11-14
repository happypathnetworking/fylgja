"""`scripts/demo.py`, the demonstration script: the environment it reads, what it writes under `local/`, and the
host's checks; then the core and the runner it starts in the background by recorded pids, and their end; then each
source's runbook taken in order through the make targets there are, the lab pool read once the source is up, the
other source stopped first, and the three targets that run the script. The script is loaded by its path, as `make`
runs it, and given `demo_host.FakeHost` for its host: nothing here opens a socket or sleeps, or starts a process but
`make -n`, which prints a recipe and runs none of it.

What is read of the host: one test of `Real` reads this process's own entry in `/proc` and the group database. What
is read of the checkout: `.env.example`; the script itself, by `ast`; the three development scripts beside it, each
loaded by its path, the core's `config`, `server.auth` and `containerlab.pool`, the text of its local driver's read
of Docker's networks, and the example's `edge.flows`, imported, and the text of its `edge/serve.py`, to hold the
script's values to theirs; the `Makefile`, by its text and by `make -n`; `CONTRIBUTING.md`'s two runbooks; the two
packages the seeded twin runs; and one test walks the tree and reads each file that says what a distribution holds.
No other file of the host's is read. What is written is written under `tmp_path`, by the script and by the fakes
of the make targets (`demo_targets.Targets`), which write `local/.env` by the development scripts' own functions;
and every secret is the tests' own, or made there by those functions, compared outside an assert."""

from __future__ import annotations

import ast
import base64
import errno
import grp
import hashlib
import http.client
import inspect
import io
import json
import os
import signal
import stat
import subprocess
import sys
from collections.abc import Mapping, Sequence
from email.message import Message
from ipaddress import IPv4Network
from pathlib import Path
from typing import Any

import pytest
from demo_host import (
    AUTH,
    CLIENT_TOKEN,
    DEMO,
    ENV,
    LOCAL,
    MAIN,
    NODE_PASSWORD,
    NODE_USER,
    ROOT,
    RUNNER_TOKEN,
    SECRETS,
    SS,
    FakeHost,
    Ran,
    Started,
    demo,
    meminfo,
    network_line,
    passing,
    same,
    short_id,
    ss,
)
from demo_host import ENV_FILE as ENV_TEXT
from demo_targets import (
    API,
    BIND,
    CLI,
    CORE,
    EDGE_DEV,
    MAKE_FAILED,
    NETBOX_DEV,
    PROJECT_NETWORKS,
    PYTHON,
    RUNNER,
    SERVING,
    SHELL,
    Targets,
    becomes,
    by_path,
    exits_at_its_signal,
    first,
    hashed,
    loaded_env,
)

WHERE = ["--local", str(LOCAL), "--main", str(MAIN)]
MEMINFO = Path("/proc/meminfo")
ENV_FILE = LOCAL / ".env"
LOCK = LOCAL / "demo" / "lock"
INFRAHUB_UP = ("docker", "ps", "-q", "--filter", "label=com.docker.compose.project=fylgja-core-infrahub")
NETBOX_UP = ("docker", "ps", "-q", "--filter", "label=com.docker.compose.project=fylgja-core-netbox")


def up(source: str, ref: str = "main") -> list[str]:
    return ["up", source, *WHERE, "--ref", ref]


def without(*names: str) -> dict[str, str]:
    return {name: value for name, value in ENV.items() if name not in names}


def checked(
    host: FakeHost, source: str = "netbox", ref: str = "", *, less: tuple[str, ...] = (), **changed: str
) -> list[str]:
    """The failing sentences of `source`'s checks on `host`, under `ENV` less the names `less` and with `changed` laid
    over it. The environment is given here, so that an assert that fails shows none of it."""
    failing: list[str] = demo.checks(source, without(*less) | changed, local=LOCAL, ref=ref, host=host)
    return failing


def status(host: FakeHost, argv: list[str], *, exported: bool = False) -> int:
    """`main`'s exit status on `host` under the shell's environment, `ENV` exported into it where `exported`; given
    here, as `checked` gives its own."""
    exited: int = demo.main(argv, environ=SHELL | ENV if exported else SHELL, host=host)
    return exited


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_the_environment_is_the_shells_overlaid_by_the_file() -> None:
    text = "A=1\nexport B=two\n# C=3\nA='x y' # note\nD=\"q\"\n"
    assert demo.read_env(text) == {"A": "x y", "B": "two", "D": "q"}

    host = FakeHost()
    host.files[ENV_FILE] = text
    shell = {"A": "the shell's", "E": "kept"}
    assert demo.loaded(LOCAL, shell, host) == {"A": "x y", "B": "two", "D": "q", "E": "kept"}
    assert shell == {"A": "the shell's", "E": "kept"}
    assert demo.loaded(LOCAL, shell, FakeHost()) == shell

    # A login as a person writes one, quoted and exported: read with its quotes off, and the checks hold it given.
    host = passing()
    host.files[ENV_FILE] = (
        f"export FYLGJA_CREDENTIAL_SRLINUX_USERNAME='{NODE_USER}'\n"
        f'FYLGJA_CREDENTIAL_SRLINUX_PASSWORD="{NODE_PASSWORD} with a space!"  # the image\'s own\n'
    )
    env = demo.loaded(LOCAL, SHELL, host)
    read_with_its_quotes_off = same(
        [env[name] for name in demo.LOGIN], [NODE_USER, f"{NODE_PASSWORD} with a space!"]
    )
    assert read_with_its_quotes_off
    failing = demo.checks("netbox", env, local=LOCAL, ref="", host=host)
    assert failing == []


@pytest.mark.parametrize(
    ("line", "value"),
    [
        ("X=", ""),
        ('X=""', ""),
        ("X=''", ""),
        ("X= # a note", ""),
        ("X=p#q", "p#q"),
        ("X=p # q", "p"),
        ("X=p\t# q", "p"),
        ("  export\tX=p  ", "p"),
        ("X=p=q", "p=q"),
        ("X=http://127.0.0.1:8000", "http://127.0.0.1:8000"),
        ("X=tag:fylgja", "tag:fylgja"),
        ("X=nbt_k-1.t_2", "nbt_k-1.t_2"),
        ("X=/srv/example/a.b/c*", "/srv/example/a.b/c*"),
        ("X=\"p 'q' # r\" # s", "p 'q' # r"),
        ("X='p \"q\" $r `s` \\t ~ ; {a,b}'", 'p "q" $r `s` \\t ~ ; {a,b}'),
        ('X="p; q | r ~ {a,b}"', "p; q | r ~ {a,b}"),
        ("export X='p q'", "p q"),
        ("X=p!q", "p!q"),
        ("X=p,q%^+@q]", "p,q%^+@q]"),
        ("X=p # q\r", "p"),
        # Inside quotes a shell keeps what is there, a carriage return and a no-break space among it.
        ("X='p\rq'", "p\rq"),
        ('X="p\xa0q"', "p\xa0q"),
        # A carriage return outside quotes is in the value to a shell: a file saved with CRLF line ends, and a lone one.
        ("X=1\r", None),
        ('X="1"\r', None),
        ("X=p\rq", None),
        # A form feed, a no-break space, a next-line and a line separator are no blank and no line end to a shell.
        ("X=p\x0cq", None),
        ("X=p\xa0", None),
        ("X=p\xa0q", None),
        ("X=p\x85q", None),
        ("X=p\u2028q", None),
        ("X=p\u3000q", None),
        ("X=p\x1fq", None),
        ("X=p\x7fq", None),
        ("\xa0X=p", None),
        ("export\xa0X=p", None),
        ("export\x0bX=p", None),
        # A shell drops a NUL, and no child can be given one.
        ("X=p\x00q", None),
        ("X='p\x00q'", None),
        ('X="p\x00q"', None),
        # bash expands braces on a line that begins `export`.
        ("export X={a,b}", None),
        ("X={a,b}", None),
        ("X=p}", None),
    ],
)
def test_a_value_is_read_as_a_shell_reads_it(line: str, value: str | None) -> None:
    """Each row was read once by `/bin/bash` and by `/bin/dash` (`set -a; . file`): a value given here is what both
    held, and None is a line the script refuses, since it would hold another value than they did or one they
    did not all agree on."""
    if value is None:
        with pytest.raises(demo.Unread):
            demo.read_env(f"{line}\n")
    else:
        assert demo.read_env(f"{line}\n") == {"X": value}


def test_a_blank_line_and_a_comment_hold_nothing() -> None:
    assert demo.read_env("") == {}
    assert demo.read_env("\n# X=1\n  # X=2\n \t \n#\n\t#X=3") == {}
    assert demo.read_env("X=1\nX=\n") == {"X": ""}
    assert demo.read_env("X=\nX=1") == {"X": "1"}
    # A comment's carriage return is the comment's, to a shell too.
    assert demo.read_env("# a file saved with CRLF line ends\r\nX=1\n") == {"X": "1"}


NOT_AN_ASSIGNMENT = (
    "demo: {} line {} is not blank, a comment or [export ]NAME=value, and this script reads no other line, since a "
    "shell that loads the file would act on it: take the line out"
)
CARRIAGE_RETURN = "the file may be saved with CRLF line ends; save it with LF alone"
KEPT_BY_BASH = (
    "demo: {} line {} assigns {}, a name bash keeps for itself, so that a shell that loads the file may not hold the "
    "value: take the line out"
)


def carriage_return_said(path: Path, line: int, name: str | None) -> str:
    """The refusal of a line that reads but for its carriage return: the file, the line and the name it has."""
    where = f"demo: {path} line {line}"
    if name is None:
        return f"{where} holds a carriage return, which a shell takes for part of the line: {CARRIAGE_RETURN}"
    return f"{where} gives {name} a carriage return, which a shell keeps in the value: {CARRIAGE_RETURN}"


BASH_KEEPS = (
    "UID", "EUID", "PPID", "BASHOPTS", "SHELLOPTS", "BASH_VERSINFO", "GROUPS", "RANDOM", "SRANDOM", "SECONDS", "LINENO",
    "FUNCNAME", "DIRSTACK", "BASHPID", "EPOCHSECONDS", "EPOCHREALTIME", "HISTCMD", "BASH_COMMAND", "BASH_SUBSHELL",
    "BASH_MONOSECONDS", "PIPESTATUS", "COMP_WORDBREAKS", "BASH_LINENO", "BASH_SOURCE", "BASH_ARGC", "BASH_ARGV",
    "BASH_ALIASES", "BASH_CMDS", "_", "BASH_ARGV0", "SHLVL", "OPTIND",
)
"""Names the shells do not agree on: assigned by a file it loads, bash exports its own value or none, where dash
exports the file's; the last three were read apart: for `BASH_ARGV0` bash exports nothing; `SHLVL` it exports
lowered by one, or as 0 where the file's is no number; and at an `OPTIND` that is no number dash stops loading the
file, where bash holds 0. Read once on both shells, as the rows of `test_a_value_is_read_as_a_shell_reads_it` were."""


@pytest.mark.parametrize(
    ("text", "name", "line", "carriage_return"),
    [
        # Lines a shell acts on that assign nothing this script could hold as the shell does.
        ("X=1\nunset X\n", None, 2, False),
        ("X=1\nX+=2\n", None, 2, False),
        ("readonly X=1\n", None, 1, False),
        ("declare -x X=1\n", None, 1, False),
        ("X=1\n\nexport X\n", None, 3, False),
        ("# a note\n. local/other\n", None, 2, False),
        ("set -a\nX=1\n", None, 1, False),
        ("X =3\n", None, 1, False),
        ("1X=4\n", None, 1, False),
        ("\xa0X=p\n", None, 1, False),
        ("export\xa0X=p\n", None, 1, False),
        ("export\x0bX=p\n", None, 1, False),
        ("\ufeffX=p\n", None, 1, False),
        # A file saved with CRLF line ends: the first line that is no comment is refused, and the carriage return said.
        ("# a note\r\nX=1\r\nY=2\r\n", "X", 2, True),
        ("# a note\r\n\r\nX=1\r\n", None, 2, True),
        ('X="1"\r\n', "X", 1, True),
        ("A=1\nX=p\rq\n", "X", 2, True),
        ("export X\r\n", None, 1, False),
        ("X=p q\r\n", "X", 1, False),
        ("X=p\x0cq\n", "X", 1, False),
        ("X=p\x00q\n", "X", 1, False),
        # A name bash keeps for itself, plain and after `export`, whatever it is given.
        *((f"A=1\n{name}=5\n", name, 2, False) for name in BASH_KEEPS),
        *((f"export {name}=5\n", name, 1, False) for name in BASH_KEEPS),
        ("UID='5'\r\n", "UID", 1, False),
        ("UID=$HOME\n", "UID", 1, False),
    ],
)
def test_a_line_a_shell_would_read_otherwise_is_refused_by_its_number(
    text: str, name: str | None, line: int, carriage_return: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(demo.Unread) as unread:
        demo.read_env(text)
    assert (unread.value.name, unread.value.line, unread.value.carriage_return) == (name, line, carriage_return)
    assert unread.value.kept_by_bash is (name in BASH_KEEPS)

    host = passing()
    host.files[ENV_FILE] = text
    assert status(host, up("netbox", "")) == 2
    said = capsys.readouterr()
    [sentence] = said.err.split("\n")[:-1]
    if carriage_return:
        assert sentence == carriage_return_said(ENV_FILE, line, name)
    elif name in BASH_KEEPS:
        assert sentence == KEPT_BY_BASH.format(ENV_FILE, line, name)
    elif name is None:
        assert sentence == NOT_AN_ASSIGNMENT.format(ENV_FILE, line)
    else:
        assert sentence.startswith(f"demo: {ENV_FILE} line {line} gives {name} a value this script does not read")
    assert (said.out, host.ran, host.started) == ("", [], [])


def test_the_names_bash_keeps_are_the_scripts() -> None:
    assert sorted(demo.BASH_KEEPS) == sorted(BASH_KEEPS)
    # A name that only begins as one of them is read.
    assert demo.read_env("UIDS=5\nexport BASH_OF_MINE=6\n__=7\n") == {"UIDS": "5", "BASH_OF_MINE": "6", "__": "7"}


@pytest.mark.parametrize(
    ("held", "name", "line"),
    [
        (b"# a note\nX=1\r\nY=2\r\n", "X", 2),
        (b"X=1\r\n", "X", 1),
        (b"X=1\rY=2\n", "X", 1),
        (b'A=1\nexport X="1"\r\n', "X", 2),
        (b"A=1\n\r\nX=1\n", None, 2),
    ],
)
def test_a_carriage_return_in_the_file_reaches_the_reader_and_is_refused(
    tmp_path: Path, held: bytes, name: str | None, line: int, capsys: pytest.CaptureFixture[str]
) -> None:
    """Through `Real.text` and `loaded` on a file of the test's own: the seam the rows that give `read_env` a string
    never cross. A file's line ends are not translated on the way, so what a shell would keep is refused."""
    local = tmp_path / "local"
    local.mkdir()
    env_file = local / ".env"
    env_file.write_bytes(held)
    real = demo.Real()

    text = real.text(env_file)
    assert text is not None
    assert text.encode() == held
    with pytest.raises(demo.Unread) as unread:
        demo.read_env(text)
    assert (unread.value.name, unread.value.line, unread.value.carriage_return) == (name, line, True)

    with pytest.raises(demo.Stop) as stop:
        demo.loaded(local, {}, real)
    said = carriage_return_said(env_file, line, name).removeprefix("demo: ")
    assert (stop.value.status, stop.value.lines) == (2, (said,))

    # The fake reads a file of a test's own as the real host does, and `up` says the same of it.
    host = passing(local, disk=tmp_path)
    assert host.text(env_file) == text
    assert status(host, ["up", "netbox", "--local", str(local), "--main", str(tmp_path), "--ref", ""]) == 2
    assert capsys.readouterr().err.split("\n")[:-1] == [f"demo: {said}"]
    assert host.ran == []


def test_a_carriage_return_inside_quotes_is_read_from_the_file_as_a_shell_reads_it(tmp_path: Path) -> None:
    local = tmp_path / "local"
    local.mkdir()
    (local / ".env").write_bytes(b"X='p\rq'\nY=1 # a note\r\n# a comment\r\nZ=\"\rp\"\n")
    assert demo.loaded(local, {"W": "kept"}, demo.Real()) == {"W": "kept", "X": "p\rq", "Y": "1", "Z": "\rp"}


def test_a_name_held_with_no_value_is_not_held() -> None:
    example = demo.Real().text(ROOT / ".env.example")
    assert example is not None
    read = demo.read_env(example)
    assert set(read.values()) == {""}
    assert {*demo.LOGIN, "FYLGJA_API_ADDRESS", "FYLGJA_API_TOKEN", "FYLGJA_LISTEN", "FYLGJA_LAB_POOL"} <= set(read)

    host = passing()
    listen = demo.listen_of(read)
    assert listen == "127.0.0.1:7650"
    assert [name for name, _ in demo.own_lines(read, listen, host)] == ["FYLGJA_API_ADDRESS", "FYLGJA_API_TOKEN"]
    assert demo.checks("netbox", read, local=LOCAL, ref="", host=host) == [
        "local/.env gives FYLGJA_CREDENTIAL_SRLINUX_USERNAME and FYLGJA_CREDENTIAL_SRLINUX_PASSWORD no value: add the "
        "lines; the image's documented default login is enough (.env.example)"
    ]


UNREAD = ['"$HOME/y"', "`id`", "a\\ b"]
"""A parameter, a command and an escape: what a shell would make of each is not this script's to guess."""

ALSO_UNREAD = [
    "p q", '"p"q', "'p'q", "'p", '"p', " 'p'", "~/y", "p:~/y", "p;q", "p|q", "p&", "p>q", "(p)", "$(id)", '"p\\"q"',
    "'p' 'q'", "{p,q}", "p}", "p\tq",
]
"""More than one word or pair of quotes, a quote left open, a tilde, braces, and what ends a command."""


def test_a_value_the_script_does_not_read_is_named_by_its_name_and_line_alone(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert demo.read_env("X='$HOME'\n") == {"X": "$HOME"}
    for value in (*UNREAD, *ALSO_UNREAD):
        with pytest.raises(demo.Unread) as unread:
            demo.read_env(f"X={value}\n")
        assert (unread.value.name, unread.value.line) == ("X", 1), value
        assert value not in str(unread.value)
        with pytest.raises(demo.Unread) as later:
            demo.read_env(f"# a note\nA=1\n\nexport X={value}\nX=1\n")
        assert (later.value.name, later.value.line) == ("X", 4), value

        host = passing()
        host.files[ENV_FILE] = f"X={value}\n"
        assert status(host, up("netbox", "")) == 2, value
        said = capsys.readouterr()
        assert said.out == ""
        assert said.err.splitlines() == [
            f"demo: {ENV_FILE} line 1 gives X a value this script does not read as a shell would: it holds a $, a "
            "backquote or a backslash outside single quotes, or is neither one pair of quotes nor one word free of "
            "blanks, control characters and ~ ; & | < > ( ) { }; write it in single quotes"
        ], value
        assert host.ran == [] and host.started == []


def test_a_value_the_locale_cannot_encode_is_refused_by_its_name_alone(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The encoding step replaced by one that refuses a value as a locale that is not UTF-8 refuses a character it
    lacks: the exception's own text holds the character, so the refusal is by the name, and holds nothing of it."""
    fsencode = os.fsencode

    def narrow(value: str) -> bytes:
        if "zzqj" in value:
            raise UnicodeEncodeError("iso8859-1", value, value.index("zzqj"), len(value), "ordinal not in range(256)")
        return fsencode(value)

    monkeypatch.setattr(demo.os, "fsencode", narrow)
    refused = "{} holds a character this locale cannot encode"

    host = passing()
    host.files[ENV_FILE] = "A=1\nX='zzqj kkwv'\nexport Y=zzqjkkwv\n"
    with pytest.raises(demo.Stop) as stop:
        demo.loaded(LOCAL, {"W": "kept"}, host)
    assert (stop.value.status, stop.value.lines) == (2, (refused.format("X"), refused.format("Y")))
    assert status(host, up("netbox", "")) == 2
    said = capsys.readouterr()
    assert said.err.split("\n")[:-1] == [f"demo: {refused.format(name)}" for name in ("X", "Y")]
    shown = any(part in said.out + said.err for part in ("zzqj", "kkwv"))
    assert not shown
    assert (said.out, host.ran, host.started) == ("", [], [])

    # And where a value is hashed, should one reach there unjudged.
    with pytest.raises(demo.Stop) as stop:
        demo.token_lines("", {"FYLGJA_API_TOKEN": "zzqjkkwv"})
    assert (stop.value.status, stop.value.lines) == (2, (refused.format("FYLGJA_API_TOKEN"),))
    in_the_stop = any(part in str(stop.value) for part in ("zzqj", "kkwv"))
    assert not in_the_stop
    # The exception the encoding raised holds the whole value: the `Stop` carries it neither as its cause nor as
    # its context, where a traceback or a handler would find it.
    assert (stop.value.__cause__, stop.value.__context__) == (None, None)


NOT_UTF_8 = "{} holds a byte that is not UTF-8"
NOT_AS_THE_FILE = "{} holds a character this locale would not write as the file has it"


def test_a_value_that_is_not_utf_8_is_refused_by_its_name_alone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A value is a child's to be given, a line's to be written and a header's to be sent, each as UTF-8: one that
    holds a byte that is none is refused where the environment is loaded, by its name, and nothing later meets it.
    Through `Real.text` on a file of the test's own, so that the bytes are a file's and not a string's."""
    local = tmp_path / "local"
    local.mkdir()
    env_file = local / ".env"
    real = demo.Real()

    # A comment may hold any byte, and so may a line's own comment: a shell reads neither.
    env_file.write_bytes(b"# caf\xe9, as another editor saved it\nX=1 # \xff\nY='\xc3\xa9'\n")
    assert demo.loaded(local, {"W": "kept"}, real) == {"W": "kept", "X": "1", "Y": "\u00e9"}

    env_file.write_bytes(b"A=1\nFYLGJA_LISTEN='127.0.0.1:76\xff'\nexport X=p\xffq\nY=\xc3\xa9\nZ=\"\xed\xa0\x80\"\n")
    with pytest.raises(demo.Stop) as stop:
        demo.loaded(local, {"W": "kept"}, real)
    assert (stop.value.status, stop.value.lines) == (
        2,
        (NOT_UTF_8.format("FYLGJA_LISTEN"), NOT_UTF_8.format("X"), NOT_UTF_8.format("Z")),
    )
    assert (stop.value.__cause__, stop.value.__context__) == (None, None)

    # `up` says the same and runs nothing; the fake reads the file as the real host does.
    host = passing(local, disk=tmp_path)
    assert host.text(env_file) == real.text(env_file)
    assert status(host, ["up", "netbox", "--local", str(local), "--main", str(tmp_path), "--ref", ""]) == 2
    said = capsys.readouterr()
    assert said.err.split("\n")[:-1] == [f"demo: {NOT_UTF_8.format(name)}" for name in ("FYLGJA_LISTEN", "X", "Z")]
    assert (said.out, host.ran, host.started) == ("", [], [])
    assert sorted(path.name for path in local.iterdir()) == [".env"]

    # And where a value is hashed or written, should one reach there unjudged: a `Stop`, and never a `ValueError`.
    unjudged = "p\udcffq"
    with pytest.raises(demo.Stop) as stop:
        demo.token_lines("", {"FYLGJA_API_TOKEN": unjudged})
    assert (stop.value.status, stop.value.lines) == (2, (NOT_UTF_8.format("FYLGJA_API_TOKEN"),))
    assert (stop.value.__cause__, stop.value.__context__) == (None, None)
    with pytest.raises(demo.Stop) as stop:
        demo.encoded("X", unjudged)
    assert (stop.value.status, stop.value.lines) == (2, (NOT_UTF_8.format("X"),))
    assert (stop.value.__cause__, stop.value.__context__) == (None, None)

    # Of the shell's own values, one whose name begins `FYLGJA_` is held to the same, with the file there and with
    # none: the script reads, hashes, writes or sends no other name's value. Every other passes through untouched,
    # as a variable the shell exported with one Latin-1 byte in it, and reaches a child as the bytes it came as.
    oldpwd = os.fsdecode(b"/srv/example/caf\xe9")
    shells = {"W": "kept", "OLDPWD": oldpwd, "LESS": os.fsdecode(b"-R\xff"), "FYLGJA": oldpwd, "XFYLGJA_X": oldpwd}
    env_file.write_bytes(b"A=1\n")
    for there in (True, False):
        if not there:
            env_file.unlink()
        assert demo.loaded(local, shells, real) == shells | ({"A": "1"} if there else {})
        for name in ("FYLGJA_ORCHESTRATOR_AUTH", "FYLGJA_LISTEN", "FYLGJA_"):
            with pytest.raises(demo.Stop) as stop:
                demo.loaded(local, shells | {name: unjudged}, real)
            assert (stop.value.status, stop.value.lines) == (2, (NOT_UTF_8.format(name),))
            assert (stop.value.__cause__, stop.value.__context__) == (None, None)

    # `up` and `down` run under such a shell, and a child is given the variable as it was: each make step, the core
    # and the runner. (Until its verdict is read, `up` ends at the change opened, exit 1.)
    env_file.write_text(ENV_TEXT)
    for argv, exits in ((["up", "netbox", "--ref", ""], 1), (["down"], 0)):
        host = passing(local, disk=tmp_path)
        exits_at_its_signal(host)
        Targets(host, local)
        exited: int = demo.main([*argv, "--local", str(local), "--main", str(tmp_path)], environ=shells, host=host)
        assert exited == exits, argv
        given = [ran.env for ran in host.ran if ran.env is not None] + [started.env for started in host.started]
        given_as_it_was = all(same(env.get("OLDPWD"), oldpwd) for env in given)
        assert given_as_it_was and os.fsencode(oldpwd) == b"/srv/example/caf\xe9"
        children = len(given)
        assert children >= 4 and len(host.started) == (2 if argv[0] == "up" else 1)
        assert capsys.readouterr().err.splitlines()[:1] == ([f"demo: {OPENED}"] if argv[0] == "up" else [])


def test_a_value_the_locale_would_write_as_other_bytes_is_refused_by_its_name_alone(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The encoding step replaced by ISO-8859-1's, a locale that is not UTF-8: it gives a child one byte for a
    character the file holds as two, where a shell that loads the file gives the file's two. Such a value is
    refused by its name; one the locale writes as the file has it is carried."""

    def latin_1(value: str) -> bytes:
        return value.encode("iso8859-1", "surrogateescape")

    monkeypatch.setattr(demo.os, "fsencode", latin_1)
    host = passing()
    host.files[ENV_FILE] = "A=plain\nX='zzqj\u00e9'\nexport Y=kkwv\u00e9\n"
    with pytest.raises(demo.Stop) as stop:
        demo.loaded(LOCAL, {"W": "kept"}, host)
    assert (stop.value.status, stop.value.lines) == (2, (NOT_AS_THE_FILE.format("X"), NOT_AS_THE_FILE.format("Y")))
    assert (stop.value.__cause__, stop.value.__context__) == (None, None)
    assert status(host, up("netbox", "")) == 2
    said = capsys.readouterr()
    assert said.err.split("\n")[:-1] == [f"demo: {NOT_AS_THE_FILE.format(name)}" for name in ("X", "Y")]
    shown = any(part in said.out + said.err for part in ("zzqj", "kkwv"))
    assert not shown
    assert (said.out, host.ran, host.started) == ("", [], [])

    # A character the locale lacks is still said as that, and a value it writes as the file has it is carried.
    host.files[ENV_FILE] = "A=plain\nX='zzqj\u20ac'\n"
    with pytest.raises(demo.Stop) as stop:
        demo.loaded(LOCAL, {}, host)
    assert stop.value.lines == ("X holds a character this locale cannot encode",)
    assert (stop.value.__cause__, stop.value.__context__) == (None, None)
    host.files[ENV_FILE] = "A=plain\nX='p q'\n"
    assert demo.loaded(LOCAL, {}, host) == {"A": "plain", "X": "p q"}
    assert demo.encoded("A", "plain") == b"plain"
    # A value of the shell's own came as the locale's bytes and is given back to a child as them: it is not held
    # to the file's, with the file there or with none, whatever its name, but where the file gives the name a value
    # of its own.
    shells = {"W": "kept\u00e9", "X": "the shell's \u00e9", "FYLGJA_API_ADDRESS": "caf\u00e9.example:7650"}
    assert demo.loaded(LOCAL, shells, host) == shells | {"A": "plain", "X": "p q"}
    del host.files[ENV_FILE]
    assert demo.loaded(LOCAL, shells, host) == shells


def test_own_lines_add_the_address_and_a_clients_token_only_where_absent() -> None:
    host = FakeHost()
    neither = without("FYLGJA_API_ADDRESS", "FYLGJA_API_TOKEN")
    (first, address), (second, token) = demo.own_lines(neither, demo.listen_of(neither), host)
    assert (first, address, second) == ("FYLGJA_API_ADDRESS", "127.0.0.1:7650", "FYLGJA_API_TOKEN")
    token_is_the_hosts = len(host.secrets) == 1 and same(token, host.secrets[0])
    assert token_is_the_hosts

    both_held = demo.own_lines(ENV, demo.listen_of(ENV), host)
    made = len(host.secrets)
    assert (both_held, made) == ([], 1)

    moved = neither | {"FYLGJA_LISTEN": "127.0.0.1:7700"}
    listen = demo.listen_of(moved)
    (_, address), _ = demo.own_lines(moved, listen, host)
    assert (listen, address) == ("127.0.0.1:7700", "127.0.0.1:7700")
    emptied = demo.listen_of(neither | {"FYLGJA_LISTEN": ""})
    assert emptied == "127.0.0.1:7650"

    address_alone = demo.own_lines(without("FYLGJA_API_ADDRESS"), "127.0.0.1:7650", host)
    assert address_alone == [("FYLGJA_API_ADDRESS", "127.0.0.1:7650")]
    token_alone = [name for name, _ in demo.own_lines(ENV | {"FYLGJA_API_TOKEN": ""}, "127.0.0.1:7650", host)]
    assert token_alone == ["FYLGJA_API_TOKEN"]


def test_the_token_file_lists_each_token_once_by_its_hash(tmp_path: Path) -> None:
    def lacking(held: str, *less: str, **changed: str) -> list[str]:
        """The lines a token file of `held` lacks under `ENV` less `less` with `changed` laid over it, given here so
        that an assert that fails shows no token."""
        lines: list[str] = demo.token_lines(held, without(*less) | changed)
        return lines

    clients, runners = f"{hashed(CLIENT_TOKEN)} demo", f"{hashed(RUNNER_TOKEN)} orchestrator"
    lines = lacking("")
    assert lines == [clients, runners]
    holds_a_token = any(secret in line for line in lines for secret in SECRETS)
    assert not holds_a_token
    held = "".join(f"{line}\n" for line in lines)
    assert lacking(held) == []

    the_two_are_one = lacking("", FYLGJA_ORCHESTRATOR_API_TOKEN=CLIENT_TOKEN)
    assert the_two_are_one == [clients]
    assert lacking("", "FYLGJA_ORCHESTRATOR_API_TOKEN") == [clients]
    assert lacking("", FYLGJA_ORCHESTRATOR_API_TOKEN="") == [clients]
    assert lacking("", "FYLGJA_API_TOKEN", "FYLGJA_ORCHESTRATOR_API_TOKEN") == []

    # The runner's token is made by a later step: its line alone is added then, whatever else the file holds.
    assert lacking(f"# the demonstration's\n\n  {clients}\n") == [runners]
    # A hash listed under another principal is listed: a second line of it would be refused at the core's start.
    assert lacking(f"{runners.split()[0]} another\n") == [clients]

    # The core reads the lines as its own: each token's hash as it hashes one, under its principal.
    from fylgja_core.server.auth import Tokens, hash_token

    file = tmp_path / "tokens"
    file.write_text(held)
    assert Tokens.load(file).principals == {hash_token(CLIENT_TOKEN): "demo", hash_token(RUNNER_TOKEN): "orchestrator"}


def test_everything_the_script_keeps_is_under_local_demo() -> None:
    home = LOCAL / "demo"
    assert demo.records(LOCAL) == demo.Records(
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
    # One spelling of each path, whatever spelling of `local` the command was given: the store's is what a core is
    # known by.
    assert demo.records(LOCAL / "demo" / ".." / "." / "") == demo.records(LOCAL)


def test_prepare_makes_the_directory_and_the_files_at_their_modes_and_keeps_every_byte(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    local = tmp_path / "local"
    local.mkdir()
    env_file = local / ".env"
    held = b"# mine\nFYLGJA_CREDENTIAL_SRLINUX_USERNAME=u\nFYLGJA_CREDENTIAL_SRLINUX_PASSWORD='p w'"
    env_file.write_bytes(held)
    env_file.chmod(0o640)
    host = FakeHost(disk=tmp_path)
    home, tokens = local / "demo", local / "demo" / "tokens"

    env = demo.loaded(local, SHELL, host)
    demo.prepare(local, env, demo.listen_of(env), host)
    assert mode(home) == 0o700
    assert sorted(path.name for path in home.iterdir()) == ["tokens"]
    assert (mode(tokens), tokens.read_bytes()) == (0o600, b"")
    [token] = host.secrets
    written = env_file.read_bytes()
    lines = f"FYLGJA_API_ADDRESS=127.0.0.1:7650\nFYLGJA_API_TOKEN={token}\n".encode()
    every_byte_kept_then_the_two_lines = same(written, held + b"\n" + lines)
    assert every_byte_kept_then_the_two_lines
    assert mode(env_file) == 0o640
    said = capsys.readouterr()
    token_shown = token in said.out + said.err
    assert not token_shown
    assert said.out.splitlines() == [f"demo: {env_file}: added FYLGJA_API_ADDRESS, FYLGJA_API_TOKEN"]

    # Again, over a token file that has gained a line, it and the directory at other modes: nothing of either file
    # changes, and both are the user's alone again.
    tokens.write_text(f"{hashed(token)} demo\n")
    tokens.chmod(0o644)
    home.chmod(0o755)
    env = demo.loaded(local, SHELL, host)
    token_read_back = same(env["FYLGJA_API_TOKEN"], token)
    quotes_taken_off = same(env["FYLGJA_CREDENTIAL_SRLINUX_PASSWORD"], "p w")
    assert token_read_back
    assert quotes_taken_off
    demo.prepare(local, env, demo.listen_of(env), host)
    nothing_changed = same(env_file.read_bytes(), written)
    no_token_made_again = len(host.secrets) == 1
    assert nothing_changed
    assert no_token_made_again
    assert (mode(home), mode(env_file), mode(tokens)) == (0o700, 0o640, 0o600)
    assert tokens.read_text() == f"{hashed(token)} demo\n"
    assert capsys.readouterr().out == ""
    assert sorted(path.name for path in local.iterdir()) == [".env", "demo"]


def test_the_core_is_given_its_own_store_tokens_driver_and_packages() -> None:
    assert demo.ROOT == ROOT
    kept = demo.records(LOCAL)
    env = ENV | {
        "FYLGJA_TOKENS": "elsewhere",
        "FYLGJA_STORE": "elsewhere",
        "FYLGJA_DRIVER": "clabernetes",
        "FYLGJA_PACKAGES": "elsewhere",
        "FYLGJA_TLS_CERT": "c",
        "FYLGJA_TLS_KEY": "k",
        "FYLGJA_LEASE": "l",
        "FYLGJA_API_CA": "a",
        "FYLGJA_LAB_POOL": "198.51.100.0/24",
    }
    before = dict(env)
    core = demo.core_env(env, kept, "127.0.0.1:7700")
    set_for_it = {
        "FYLGJA_API_ADDRESS": "127.0.0.1:7700",
        "FYLGJA_TOKENS": str(LOCAL / "demo" / "tokens"),
        "FYLGJA_DRIVER": "containerlab",
        "FYLGJA_STORE": str(LOCAL / "demo" / "store"),
        "FYLGJA_PACKAGES": f"{ROOT / 'psp'}:{ROOT / 'probes'}",
        "FYLGJA_LISTEN": "127.0.0.1:7700",
    }
    removed = ("FYLGJA_TLS_CERT", "FYLGJA_TLS_KEY", "FYLGJA_LEASE", "FYLGJA_API_CA")
    assert {name: core[name] for name in set_for_it} == set_for_it
    assert [name for name in removed if name in core] == []
    as_loaded = [name for name in env if name not in set_for_it and name not in removed]
    assert {*demo.LOGIN, "FYLGJA_LAB_POOL", "PATH"} <= set(as_loaded)
    the_rest_is_as_loaded = same({name: core[name] for name in as_loaded}, {name: env[name] for name in as_loaded})
    assert the_rest_is_as_loaded
    assert sorted(name for name in core) == sorted(name for name in [*env, "FYLGJA_LISTEN"] if name not in removed)

    step = demo.step_env(env, kept, "127.0.0.1:7700")
    set_for_a_step = {"FYLGJA_API_ADDRESS": "127.0.0.1:7700", "FYLGJA_TOKENS": str(LOCAL / "demo" / "tokens")}
    assert {name: step[name] for name in set_for_a_step} == set_for_a_step
    assert [name for name in step if name == "FYLGJA_API_CA"] == []
    # No store, driver or packages of the demonstration's: a step is a client of the core, and its own are as loaded.
    assert {name: step[name] for name in ("FYLGJA_STORE", "FYLGJA_DRIVER", "FYLGJA_PACKAGES")} == {
        "FYLGJA_STORE": "elsewhere",
        "FYLGJA_DRIVER": "clabernetes",
        "FYLGJA_PACKAGES": "elsewhere",
    }
    kept_as_loaded = [name for name in env if name not in ("FYLGJA_API_ADDRESS", "FYLGJA_TOKENS", "FYLGJA_API_CA")]
    the_steps_rest_is_as_loaded = same(
        {name: step[name] for name in kept_as_loaded}, {name: env[name] for name in kept_as_loaded}
    )
    assert the_steps_rest_is_as_loaded
    plain = demo.step_env(ENV, kept, "127.0.0.1:7700")
    assert [name for name in plain if name in ("FYLGJA_STORE", "FYLGJA_LISTEN", "FYLGJA_DRIVER")] == []
    nothing_given_was_changed = same(env, before)
    assert nothing_given_was_changed

    # The node login is passed on as loaded and never given: an environment without it gives the core none.
    no_login = demo.core_env(without(*demo.LOGIN), kept, "127.0.0.1:7650")
    assert [name for name in no_login if name in demo.LOGIN] == []


def test_the_listeners_are_edge_devs() -> None:
    edge_dev = by_path("edge_dev")
    lines = "\n".join(
        [
            "LISTEN 0      4096       192.0.2.1:4200       0.0.0.0:*",
            "LISTEN 0      4096               *:4200             *:*",
            "LISTEN 0      4096            [::]:4200          [::]:*",
            "LISTEN 0      4096       127.0.0.1:14200      0.0.0.0:*",
            "LISTEN 0      4096       127.0.0.1:8000       0.0.0.0:*",
        ]
    )
    assert demo.listeners(lines, 4200) == ["192.0.2.1:4200", "*:4200", "[::]:4200"]
    for text in (lines, "", "LISTEN 0 4096\n\nnot a line of ss\n"):
        for port in (4200, 8000, 14200, 7650, 420):
            assert demo.listeners(text, port) == edge_dev.listeners(text, port), (text, port)


def test_the_projects_ports_and_sources_are_the_development_scripts() -> None:
    edge_dev, infrahub_dev, netbox_dev = by_path("edge_dev"), by_path("infrahub_dev"), by_path("netbox_dev")
    assert demo.SOURCES == edge_dev.SOURCES == ("infrahub", "netbox")
    assert demo.PROJECTS == {"infrahub": infrahub_dev.PROJECT, "netbox": netbox_dev.PROJECT}
    assert demo.PREFECT_PORT == edge_dev.PORT
    served = {"infrahub": infrahub_dev.ADDRESS, "netbox": netbox_dev.ADDRESS}
    assert {source: f"http://127.0.0.1:{port}" for source, port in demo.PORTS.items()} == served

    from fylgja_core import config

    assert demo.DEFAULT_LISTEN == config.DEFAULT_LISTEN


def test_a_host_that_meets_every_precondition_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    host = passing()
    assert checked(host, "infrahub", "main") == []
    assert [ran.argv for ran in host.ran] == [
        ["docker", "info"],
        ["docker", "compose", "version"],
        ["containerlab", "version"],
        [*INFRAHUB_UP],
        ["ss", "-Hltn"],
        ["git", "rev-parse", "--verify", "--quiet", "main^{commit}"],
    ]
    assert all(ran.capture and ran.timeout == demo.DOCKER_TIMEOUT_S for ran in host.ran)
    given_the_loaded_environment = all(same(ran.env, ENV) for ran in host.ran)
    assert given_the_loaded_environment
    assert host.ran[-1].cwd == ROOT

    host = passing()
    assert checked(host) == []
    assert [ran.argv for ran in host.ran][3:] == [[*NETBOX_UP], ["ss", "-Hltn"]]
    assert demo.notices(host) == []
    secrets_made = len(host.secrets)
    assert (host.started, host.signalled, host.asked, secrets_made) == ([], [], [], 0)

    # `up` judges the host so, says that the checks passed, and goes on to what it writes and its steps: on a host
    # whose `local/` is the test's own (`first`), the reads are the same, under the file laid over the shell.
    for source, ref in (("infrahub", "main"), ("netbox", "")):
        local, kept, host, _ = first(tmp_path / source)
        env = loaded_env(local, host)
        assert status(host, up_of(local, source, ref)) == 1
        assert capsys.readouterr().out.splitlines()[0] == "demo: the host's checks passed"
        assert host.locked == [kept.lock]
        reads = [ran for ran in host.ran[1:] if ran.capture][: len(judged(source, ref))]
        assert [ran.argv for ran in reads] == judged(source, ref)
        the_file_was_laid_over_the_shell = all(same(ran.env, env) for ran in reads)
        assert the_file_was_laid_over_the_shell


def test_a_venv_without_its_commands_names_them() -> None:
    venv = ROOT / "core" / ".venv"
    host = passing()
    host.on_path -= {str(venv / "bin" / "fylgja-core-server"), str(venv / "bin" / "prefect")}
    assert checked(host) == [f"{venv} lacks fylgja-core-server, prefect: run make venv"]

    host = passing()
    host.on_path = set(demo.TOOLS)
    assert checked(host) == [
        f"{venv} lacks fylgja-core-server, fylgja-core, fylgja-orchestrator, prefect: run make venv"
    ]


def test_a_tool_not_on_path_is_named_and_dockers_checks_left_out() -> None:
    host = passing()
    host.on_path.discard("docker")
    # Too little memory and a listener on Infrahub's port, were either judged: whether the source is up is Docker's.
    host.files[MEMINFO] = meminfo(1)
    host.answer("ss", "-Hltn", out=ss("127.0.0.1:8000"))
    assert checked(host, "infrahub", "main") == ["docker is not on PATH"]
    assert [ran.argv for ran in host.ran if ran.argv[0] == "docker"] == []
    assert [ran.argv[0] for ran in host.ran] == ["containerlab", "ss", "git"]

    for tool in ("containerlab", "git", "make", "ss"):
        host = passing()
        host.on_path.discard(tool)
        assert checked(host, "infrahub", "main") == [f"{tool} is not on PATH"]
        assert [ran.argv for ran in host.ran if ran.argv[0] == tool] == []

    host = passing()
    host.on_path -= set(demo.TOOLS)
    assert checked(host, "infrahub", "main") == [f"{tool} is not on PATH" for tool in demo.TOOLS]
    assert host.ran == []


def test_a_daemon_that_does_not_answer_and_a_missing_compose_are_each_said(
    capsys: pytest.CaptureFixture[str],
) -> None:
    host = passing()
    host.answer("docker", "info", status=1)
    host.answer("docker", "compose", "version", status=125)
    host.answer("containerlab", "version", status=2)
    host.files[MEMINFO] = meminfo(1)
    assert checked(host) == [
        "`docker info` exited 1: the Docker daemon does not answer this user",
        "`docker compose version` exited 125: Docker's Compose plugin is needed",
        "`containerlab version` exited 2",
    ]
    # A daemon that does not answer is not asked whether the source is up, and what that would decide is left out.
    assert [ran.argv for ran in host.ran if ran.argv[:2] == ["docker", "ps"]] == []

    host = passing()
    host.answer("docker", "compose", "version", status=1)
    assert checked(host) == ["`docker compose version` exited 1: Docker's Compose plugin is needed"]

    # A read that outlasts its time is killed, and said as `timeout` would say it.
    host = passing()
    host.answer("docker", "info", status=demo.TIMED_OUT)
    assert demo.TIMED_OUT == 124
    assert checked(host) == ["`docker info` exited 124: the Docker daemon does not answer this user"]

    # A tool on this process's PATH and not on the one `local/.env` gives its children is not found by the child:
    # a status as a shell's, and the check's own sentence at exit 2, never an exception.
    host = passing()
    for words in (("docker", "info"), ("docker", "compose", "version"), ("containerlab", "version")):
        host.answer(*words, status=demo.NOT_FOUND)
    assert checked(host, PATH="/srv/example/bin") == [
        "`docker info` exited 127: the Docker daemon does not answer this user",
        "`docker compose version` exited 127: Docker's Compose plugin is needed",
        "`containerlab version` exited 127",
    ]
    assert status(host, up("netbox", "")) == 2
    assert len(capsys.readouterr().err.splitlines()) == 3

    # A daemon that answers `info` and not `ps`: nothing is supposed of the source, and it is said.
    host = passing()
    host.answer("docker", "ps", status=1)
    host.files[MEMINFO] = meminfo(1)
    host.answer("ss", "-Hltn", out=ss("127.0.0.1:8800"))
    assert checked(host) == ["`docker ps` exited 1: whether netbox is up was not read"]

    host = passing()
    host.answer("ss", "-Hltn", status=255)
    assert checked(host) == ["`ss -Hltn` exited 255: the listeners were not read"]


IN_NO_GROUP = (
    "this process is not in the group {}: add the user to it and log in again, since a group added reaches no "
    "process begun before it"
)


def test_a_group_the_process_lacks_is_named_and_root_is_asked_for_none() -> None:
    # The host has the group, and `getent` may list the user in it: only what this process holds is asked, since a
    # process begun before the user was added holds it not (design/verified-facts.md, "Ubuntu hosts").
    host = passing()
    host.held = {1000, 997}
    assert checked(host) == [IN_NO_GROUP.format("docker")]

    host.held = {1000}
    assert checked(host) == [IN_NO_GROUP.format("docker"), IN_NO_GROUP.format("clab_admins")]

    host.gids = {"docker": 998}
    host.held = {1000, 998}
    assert checked(host) == ["the host has no group clab_admins"]

    host.gids, host.held, host.uid = {}, set(), 0
    assert checked(host) == []


def test_the_apparmor_lines_are_asked_only_where_the_profile_is(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    profile, widened = Path(demo.APPARMOR_PROFILE), Path(demo.APPARMOR_LOCAL)
    assert (str(profile), str(widened)) == (
        "/etc/apparmor.d/usr.sbin.rsyslogd",
        "/etc/apparmor.d/local/usr.sbin.rsyslogd",
    )
    lacks = (
        f"{widened} lacks {{}}: SR Linux's rsyslogd needs them on Ubuntu; add them as root and reload the profile "
        f'with apparmor_parser -r {profile} (design/verified-facts.md, "Ubuntu hosts")'
    )

    # No profile: a host that does not confine rsyslogd so, and nothing is asked of it.
    host = passing()
    del host.files[profile], host.files[widened]
    assert checked(host) == []
    assert demo.notices(host) == []

    # Both files the user's to read, as the development host's were read: one line missing is named.
    host = passing()
    assert checked(host) == []
    host.files[widened] = "/opt/srlinux/** mr,\n/run/syslogd.pid* rw,\n"
    assert checked(host) == [lacks.format("`/run/srlinux/** rw,`")]
    assert demo.notices(host) == []

    # A line commented out is missing; another's spacing and its comment are aside.
    host.files[widened] = "# /opt/srlinux/** mr,\n#/opt/srlinux/** mr,\n  /run/srlinux/**   rw,  # SR Linux\n"
    assert checked(host) == [lacks.format("`/opt/srlinux/** mr,`")]

    # The profile with no local file, or an empty one: both lines are missing.
    for held in (None, ""):
        host = passing()
        del host.files[widened]
        if held is not None:
            host.files[widened] = held
        assert checked(host) == [lacks.format("`/opt/srlinux/** mr,` and `/run/srlinux/** rw,`")]

    # A local file that is not this user's to read is no stop: `up` says what to check, and goes on.
    host = passing()
    del host.files[widened]
    host.denied = {widened}
    assert checked(host) == []
    notice = f"cannot read {widened}: check that it holds `/opt/srlinux/** mr,` and `/run/srlinux/** rw,`"
    assert demo.notices(host) == [notice]
    local, _, host, _ = first(tmp_path)
    del host.files[widened]
    host.denied = {widened}
    assert status(host, up_of(local, "netbox", "")) == 1
    said = capsys.readouterr()
    assert said.out.splitlines()[:3] == [
        f"demo: {notice}",
        "demo: the host's checks passed",
        f"demo: {local / '.env'}: added FYLGJA_API_ADDRESS, FYLGJA_API_TOKEN",
    ]
    assert said.err.splitlines()[0] == f"demo: {OPENED}"

    # A profile that is there and not the user's to read is there all the same.
    host = passing()
    del host.files[profile]
    host.denied = {profile}
    host.files[widened] = "/run/srlinux/** rw,\n"
    assert checked(host) == [lacks.format("`/opt/srlinux/** mr,`")]


def test_memory_is_the_twins_where_the_source_is_up_and_the_sources_more_where_it_is_not() -> None:
    assert (demo.SOURCE_MB, demo.TWIN_MB) == ({"infrahub": 4608, "netbox": 1536}, 7168)
    host = passing()
    host.files[MEMINFO] = meminfo(11775)
    assert checked(host, "infrahub", "main") == [
        "11775 MiB of memory is available and the infrahub demonstration needs 11776: 4608 for infrahub, which is "
        "not up, and 7168 for the twin and the edge"
    ]
    host.files[MEMINFO] = meminfo(11776)
    assert checked(host, "infrahub", "main") == []
    # A part of a MiB is not one.
    host.files[MEMINFO] = meminfo(11776).replace(f"{11776 * 1024} kB", f"{11776 * 1024 - 1} kB")
    assert "needs 11776" in checked(host, "infrahub", "main")[0]

    host.files[MEMINFO] = meminfo(7168)
    host.answer(*INFRAHUB_UP, out="3f2a9c1d0b7e\n8c1d0b7e3f2a\n")
    assert checked(host, "infrahub", "main") == []
    host.files[MEMINFO] = meminfo(7167)
    assert checked(host, "infrahub", "main") == [
        "7167 MiB of memory is available and the infrahub demonstration needs 7168: for the twin and the edge, "
        "infrahub being up"
    ]

    # The other source's containers are not this one's: NetBox is asked for by its own project.
    host.files[MEMINFO] = meminfo(8703)
    assert checked(host) == [
        "8703 MiB of memory is available and the netbox demonstration needs 8704: 1536 for netbox, which is not up, "
        "and 7168 for the twin and the edge"
    ]
    host.files[MEMINFO] = meminfo(8704)
    assert checked(host) == []

    host.files[MEMINFO] = "MemTotal:       32000000 kB\n"
    assert checked(host) == ["/proc/meminfo names no MemAvailable: the memory available was not read"]
    del host.files[MEMINFO]
    assert checked(host) == ["/proc/meminfo names no MemAvailable: the memory available was not read"]


LISTENED = "port {} is listened on at {} by a process the demonstration did not start, and {} needs it"


def test_a_port_another_process_listens_on_is_named_with_what_needs_it() -> None:
    assert (demo.PORTS, demo.PREFECT_PORT) == ({"infrahub": 8000, "netbox": 8800}, 4200)
    heard = ss("127.0.0.1:7650", "192.0.2.1:4200", "*:8000", "[::]:8800")
    host = passing()
    host.answer("ss", "-Hltn", out=heard)
    assert checked(host, "infrahub", "main") == [
        LISTENED.format(7650, "127.0.0.1", "the core"),
        LISTENED.format(4200, "192.0.2.1", "the edge's Prefect"),
        LISTENED.format(8000, "*", "infrahub"),
    ]
    assert checked(host) == [
        LISTENED.format(7650, "127.0.0.1", "the core"),
        LISTENED.format(4200, "192.0.2.1", "the edge's Prefect"),
        LISTENED.format(8800, "[::]", "netbox"),
    ]

    # The core's port is the listen address's, wherever `local/.env` puts it.
    assert checked(host, FYLGJA_LISTEN="127.0.0.1:7700") == [
        LISTENED.format(4200, "192.0.2.1", "the edge's Prefect"),
        LISTENED.format(8800, "[::]", "netbox"),
    ]
    host.answer("ss", "-Hltn", out=ss("127.0.0.1:7700"))
    assert checked(host, FYLGJA_LISTEN="127.0.0.1:7700") == [LISTENED.format(7700, "127.0.0.1", "the core")]

    # Prefect's port is `make prefect-up`'s to judge where its pid file names a live process, and only there.
    host = passing()
    host.answer("ss", "-Hltn", out=ss("192.0.2.1:4200"))
    pid_file = LOCAL / "prefect" / "server.pid"
    for held in ("4243\n", "no pid\n", ""):
        host.files[pid_file] = held
        assert checked(host) == [LISTENED.format(4200, "192.0.2.1", "the edge's Prefect")], held
    host.files[pid_file] = "4243\n"
    host.processes[4243] = demo.Process(["/srv/example/core/.venv/bin/prefect", "server", "start"], {})
    assert checked(host) == []

    # The source's port is its own where a container of its project runs, and only of its project.
    host = passing()
    host.answer("ss", "-Hltn", out=ss("*:8000", "*:8800"))
    host.answer(*INFRAHUB_UP, out="3f2a9c1d0b7e\n")
    assert checked(host, "infrahub", "main") == []
    assert checked(host) == [LISTENED.format(8800, "*", "netbox")]


def test_the_login_is_asked_for_by_its_names_and_never_given(capsys: pytest.CaptureFixture[str]) -> None:
    assert demo.LOGIN == ("FYLGJA_CREDENTIAL_SRLINUX_USERNAME", "FYLGJA_CREDENTIAL_SRLINUX_PASSWORD")
    no_value = (
        "local/.env gives {} no value: add the lines; the image's documented default login is enough (.env.example)"
    )
    absent = (
        f"{ENV_FILE} is not there: make it, mode 0600, with FYLGJA_CREDENTIAL_SRLINUX_USERNAME and "
        "FYLGJA_CREDENTIAL_SRLINUX_PASSWORD (.env.example)"
    )

    host = passing()
    assert checked(host, less=(demo.LOGIN[1],)) == [no_value.format("FYLGJA_CREDENTIAL_SRLINUX_PASSWORD")]
    assert checked(host, FYLGJA_CREDENTIAL_SRLINUX_USERNAME="") == [
        no_value.format("FYLGJA_CREDENTIAL_SRLINUX_USERNAME")
    ]
    both = no_value.format("FYLGJA_CREDENTIAL_SRLINUX_USERNAME and FYLGJA_CREDENTIAL_SRLINUX_PASSWORD")
    assert checked(host, less=demo.LOGIN) == [both]

    # No file: it is asked for, whatever the shell holds, since every step's target loads it.
    del host.files[ENV_FILE]
    assert checked(host) == [absent]
    assert status(host, up("netbox", ""), exported=True) == 2
    assert capsys.readouterr().err.splitlines() == [f"demo: {absent}"]

    # A file with neither line: the names are said, and no line the script prints or child it runs is given a login.
    host = passing()
    host.files[ENV_FILE] = "FYLGJA_API_ADDRESS=127.0.0.1:7650\n"
    assert status(host, up("netbox", "")) == 2
    assert capsys.readouterr().err.splitlines() == [f"demo: {both}"]
    assert [name for ran in host.ran for name in demo.LOGIN if name in (ran.env or {})] == []


def test_a_listen_address_off_loopback_is_refused() -> None:
    refused = (
        "FYLGJA_LISTEN is not 127.0.0.1:<port>: the demonstration's core serves HTTP on loopback; set it so in "
        "local/.env, or delete the line"
    )
    host = passing()
    # A listener on every port any of these might name: an address that is refused is asked for no port.
    host.answer("ss", "-Hltn", out=ss("127.0.0.1:7650", "127.0.0.1:0", "127.0.0.1:65536"))
    for value in (
        "0.0.0.0:7650",
        "192.0.2.1:7650",
        "localhost:7650",
        "[::1]:7650",
        ":7650",
        "127.0.0.1",
        "127.0.0.1:",
        "127.0.0.1:0",
        "127.0.0.1:65536",
        "127.0.0.1:07650",
        "127.0.0.1:port",
        "127.0.0.1:7650 ",
        "http://127.0.0.1:7650",
    ):
        assert checked(host, FYLGJA_LISTEN=value) == [refused], value

    host = passing()
    for value in ("127.0.0.1:1", "127.0.0.1:65535", "127.0.0.1:7651", ""):
        assert checked(host, FYLGJA_LISTEN=value) == [], value


def test_a_pool_that_is_no_ipv4_network_with_a_24_is_refused() -> None:
    assert (demo.POOL, demo.DEFAULT_POOL) == ("FYLGJA_LAB_POOL", "172.20.0.0/16")
    refused = "FYLGJA_LAB_POOL is not an IPv4 network in CIDR form that holds a /24"
    host = passing()
    for value in (
        "10.0.0.0/25",
        "10.0.0.1/16",
        "fd00::/64",
        "pool",
        "198.51.100.0",
        "198.51.100.0/33",
        " 198.51.100.0/24",
        "198.51.100.0/24 ",
        " ",
    ):
        assert checked(host, FYLGJA_LAB_POOL=value) == [refused], value
        with pytest.raises(ValueError) as raised:
            demo.pool_of({"FYLGJA_LAB_POOL": value})
        assert str(raised.value) == refused, value

    for value, network in (
        ("198.51.100.0/24", "198.51.100.0/24"),
        ("198.51.100.0/255.255.255.0", "198.51.100.0/24"),
        ("172.16.0.0/12", "172.16.0.0/12"),
        ("172.20.0.0/16", "172.20.0.0/16"),
    ):
        assert checked(host, FYLGJA_LAB_POOL=value) == [], value
        assert demo.pool_of({"FYLGJA_LAB_POOL": value}) == IPv4Network(network)

    # Unset or empty, the driver's default stands, and nothing is refused.
    assert checked(host, FYLGJA_LAB_POOL="") == []
    assert demo.pool_of({}) == demo.pool_of({"FYLGJA_LAB_POOL": ""}) == IPv4Network("172.20.0.0/16")


def test_infrahub_needs_a_branch_and_netbox_none() -> None:
    def gits(host: FakeHost) -> list[list[str]]:
        return [ran.argv for ran in host.ran if ran.argv[0] == "git"]

    host = passing()
    assert checked(host, "infrahub", "") == [
        "no branch is checked out and REF names none: Infrahub registers this repository at a branch; check one out, "
        "or give REF=<branch>"
    ]
    assert checked(host, "netbox", "") == []
    assert gits(host) == []

    host.answer("git", "rev-parse", status=1)
    assert checked(host, "infrahub", "no-such") == ["REF names no-such, which is no commit of this repository"]
    assert gits(host) == [["git", "rev-parse", "--verify", "--quiet", "no-such^{commit}"]]
    assert checked(host, "netbox", "no-such") == []
    assert len(gits(host)) == 1

    # A ref that git would read as an option names no branch, and git is not given it.
    host = passing()
    assert checked(host, "infrahub", "--all") == ["REF names --all, which is no commit of this repository"]
    assert gits(host) == []


def test_several_preconditions_missing_are_all_said_and_nothing_is_started(capsys: pytest.CaptureFixture[str]) -> None:
    host = passing()
    host.held = {1000, 998}
    host.files[MEMINFO] = meminfo(4096)
    # `local/.env` with its tokens and the auth, and the login as `.env.example` leaves it or not at all.
    host.files[ENV_FILE] = "FYLGJA_CREDENTIAL_SRLINUX_USERNAME=\n" + "".join(
        f"{name}={value}\n" for name, value in without(*demo.LOGIN).items() if name.startswith("FYLGJA_")
    )
    assert status(host, up("infrahub")) == 2
    said = capsys.readouterr()
    shown = any(secret in said.out + said.err for secret in SECRETS)
    on_a_command_line = any(secret in word for ran in host.ran for word in ran.argv for secret in SECRETS)
    assert not shown
    assert not on_a_command_line
    assert said.out == ""
    assert said.err.splitlines() == [
        f"demo: {IN_NO_GROUP.format('clab_admins')}",
        "demo: 4096 MiB of memory is available and the infrahub demonstration needs 11776: 4608 for infrahub, which "
        "is not up, and 7168 for the twin and the edge",
        "demo: local/.env gives FYLGJA_CREDENTIAL_SRLINUX_USERNAME and FYLGJA_CREDENTIAL_SRLINUX_PASSWORD no value: "
        "add the lines; the image's documented default login is enough (.env.example)",
    ]
    secrets_made = len(host.secrets)
    assert (host.started, host.signalled, host.asked, secrets_made) == ([], [], [], 0)
    assert [ran.argv for ran in host.ran if ran.argv[0] == "make"] == []
    assert all(ran.capture for ran in host.ran)
    assert not LOCAL.exists()


def test_a_second_command_at_once_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    for argv in (up("infrahub"), up("netbox", ""), ["down", *WHERE], ["down", *WHERE, "--purge"]):
        host = passing()
        host.free = False
        assert status(host, argv) == 2
        said = capsys.readouterr()
        assert said.out == ""
        assert said.err.splitlines() == [f"demo: another demonstration command holds {LOCK}: one runs at a time"]
        assert host.locked == [LOCK]
        assert (host.ran, host.started, host.signalled, host.asked) == ([], [], [], [])


LISTEN = "127.0.0.1:7650"
VERSION = f"http://{LISTEN}/v1/version"
PLAN_READY, REHEARSE_READY = f"{API}/deployments/name/stage-plan/main", f"{API}/deployments/name/twin-rehearse/main"
EDGE = {
    "FYLGJA_ORCHESTRATOR_INFRAHUB_TOKEN": "the-tests-examples-infrahub-token",
    "FYLGJA_NETBOX_ADDRESS": "http://127.0.0.1:8800",
    "FYLGJA_ORCHESTRATOR_NETBOX_TOKEN": "the-tests-examples-netbox-token",
    "FYLGJA_ORCHESTRATOR_NETBOX_READER": "/srv/example/fylgja-core/netbox/seed/reader.yaml",
    "FYLGJA_ORCHESTRATOR_NETBOX_SCOPE": "tag:fylgja",
}
"""What `local/.env` holds beside `ENV` once both sources' steps have run, of which the runner's environment is
made: every secret the tests' own."""

EVERY_SECRET = (*SECRETS, EDGE["FYLGJA_ORCHESTRATOR_INFRAHUB_TOKEN"], EDGE["FYLGJA_ORCHESTRATOR_NETBOX_TOKEN"])

TERM, KILL = signal.SIGTERM, signal.SIGKILL

HEARD, HEARD_BY_PID = ["ss", "-Hltn"], ["ss", "-Hltnp"]
LIST = [CLI, "twin", "list", "--json"]
"""Runs the script makes: who listens, who listens with each listener's pid, and the core's twins."""

LISTEN_REFUSED = (
    "FYLGJA_LISTEN is not 127.0.0.1:<port>: the demonstration's core serves HTTP on loopback; set it so in "
    "local/.env, or delete the line"
)
LEFT_UP = "the core, pid {}, is left up at {}: read {}, then run make demo-down again"
STANDS = (
    "the {}, pid {}, still stands after SIGKILL, or could not be signalled: its record {} is kept; end it by its pid, "
    "then run make demo-down again"
)
UNSETTLED = "{} stands: the demonstration's store was not read empty through a core of its own"
NOT_ALL_ENDED = "demo: down: not everything was ended: read the lines above, then run make demo-down again"

def place(tmp_path: Path) -> tuple[Path, Any, FakeHost]:
    """A `local/` of the test's own as `prepare` and both sources' steps leave it, `demo/` made and `.env` holding
    `ENV` and `EDGE`; its records; and a host on which every check passes, which reads it as the real one would."""
    local = tmp_path / "local"
    (local / "demo").mkdir(parents=True)
    (local / ".env").write_text(ENV_TEXT + "".join(f"{name}={value}\n" for name, value in EDGE.items()))
    return local, demo.records(local), passing(local, disk=tmp_path)


def unsettle(kept: Any) -> None:
    """The store as a core's start leaves it: the marker written, which only a list that answers empty removes."""
    kept.unsettled.write_bytes(b"")


def core_process(kept: Any, listen: str = LISTEN) -> Any:
    """The demonstration's core as `/proc` shows it: the venv's `python3`, then the command's path, under the
    environment it was started with (design/verified-facts.md, "NetBox 4.7.5 with netbox-branching 1.2.3")."""
    return demo.Process([PYTHON, CORE], demo.core_env(ENV | EDGE, kept, listen))


def runner_process(local: Path, source: str = "netbox", python: str = PYTHON, command: str = RUNNER) -> Any:
    """A runner as `/proc` shows it once `edge_dev.py serve` has become it: the venv's `python3`, the command's
    path and `serve`, under the environment `edge_dev.py` itself makes for that source and that `local/`."""
    environ = EDGE_DEV.runner_env(ENV | EDGE, BIND, home=EDGE_DEV.home_of(local), source=source)
    return demo.Process([python, command, "serve"], environ)


def lists(host: FakeHost, *listings: list[str]) -> None:
    """The core's CLI's `twin list --json` prints `listings` in turn, each a list of records as the CLI prints the
    API's document, and its `twin destroy` exits 0."""
    turn = iter(listings)

    def listed(ran: Any) -> Any:
        records = [
            {"name": name, "generation": 1, "status": {"observed_generation": 1, "phase": "pushed"}}
            for name in next(turn)
        ]
        return demo.Done(0, json.dumps(records, indent=2) + "\n")

    host.answers[(CLI, "twin", "list", "--json")] = listed
    host.answer(CLI, "twin", "destroy")


def answers_its_version(host: FakeHost, after: int = 0, listen: str = LISTEN) -> None:
    """The core at `listen` answers its version 200, once `after` asks have met nothing, a connection refused."""
    asks: list[Any] = []

    def reply(asked: Any) -> Any:
        asks.append(asked)
        return demo.Answer(None, None) if len(asks) <= after else demo.Answer(200, {"api": "1", "build": "0.0.0"})

    host.replies.append(("GET", f"http://{listen}/v1/version", reply))


def serves_prefect(host: FakeHost, local: Path, ready_from: float = 0.0) -> None:
    """`edge_dev.py api` prints `API`, and Prefect there answers each deployment by its name, `READY` once the
    clock reads `ready_from` and `NOT_READY` before."""
    host.answer(*demo.api_argv(local, MAIN)[:4], out=f"{API}\n")

    def reply(asked: Any) -> Any:
        status = "READY" if host.now >= ready_from else "NOT_READY"
        return demo.Answer(200, {"id": "a-deployments-id", "name": "main", "status": status, "paused": False})

    host.replies.append(("GET", f"{API}/deployments/name/", reply))


def acts(host: FakeHost) -> list[Any]:
    """What `host` was asked to run, start and signal, in order: a run by its words, a start as `("start", words)`
    and a signal as `(pid, number)`."""
    return [
        act.argv if isinstance(act, Ran) else ("start", act.argv) if isinstance(act, Started) else act
        for act in host.acts
    ]


def shows_a_secret(*texts: str) -> bool:
    return any(secret in text for text in texts for secret in EVERY_SECRET)


def make_n(tmp_path: Path, *words: str) -> list[str]:
    """The lines `make -n` prints of a target's recipe over a `LOCAL` of the test's: printed, and none of it run (as
    `test_dev_plumbing.py`'s)."""
    argv = ["make", "-n", "--no-print-directory", "-C", str(ROOT), *words, f"MAIN={MAIN}", f"LOCAL={tmp_path}"]
    made = subprocess.run(argv, capture_output=True, text=True, check=True, timeout=60, env={"PATH": "/usr/bin:/bin"})
    return made.stdout.splitlines()


def test_the_runners_words_are_make_orchestrator_serves(tmp_path: Path) -> None:
    for source in demo.SOURCES:
        words = demo.serve_argv(source, tmp_path, MAIN)
        assert " ".join(words) == make_n(tmp_path, "orchestrator-serve", f"SOURCE={source}")[-1]
        assert words[:4] == ["python3", "-I", "scripts/edge_dev.py", "serve"]
    [hook] = make_n(tmp_path, "netbox-hook")
    assert f"$({' '.join(demo.api_argv(tmp_path, MAIN))})" in hook
    assert demo.api_argv(tmp_path, MAIN)[:4] == ["python3", "-I", "scripts/edge_dev.py", "api"]


def test_the_names_and_the_waits_are_the_examples_and_the_plans() -> None:
    venv = ROOT / "core" / ".venv" / "bin"
    assert (venv / "fylgja-core-server", venv / "fylgja-core") == (demo.CORE, demo.CLI)
    assert {demo.CORE.name, demo.CLI.name, demo.RUNNER_COMMAND} <= set(demo.COMMANDS)
    assert EDGE_DEV.RUNNER.name == demo.RUNNER_COMMAND
    assert demo.AUTH == EDGE_DEV.AUTH
    assert demo.RUNNER_SOURCE == EDGE_DEV.SOURCE
    assert demo.prefect_home(LOCAL) == EDGE_DEV.home_of(LOCAL)
    assert demo.prefect_home(LOCAL) / "server.pid" == EDGE_DEV.pid_file(LOCAL)

    from fylgja_orchestrator.edge import flows

    assert (demo.PLAN_FLOW, demo.FLOW, demo.DEPLOYMENT) == (flows.STAGE_PLAN, flows.TWIN_REHEARSE, flows.DEPLOYMENT)
    # The line the runner's log is read for is the one `serve` prints, and begins `SERVING`'s own.
    serve = (ROOT / "orchestrator" / "src" / "fylgja_orchestrator" / "edge" / "serve.py").read_text()
    assert f'print(f"{demo.SERVING} ' in serve
    assert SERVING.startswith(f"{demo.SERVING} ")

    assert (demo.CORE_WAIT_S, demo.SERVE_WAIT_S, demo.STOP_WAIT_S, demo.DESTROY_TIMEOUT_S) == (60, 60, 30, 300)
    assert 0 < demo.ASK_S <= 1 and 0 < demo.STOP_POLL_S <= 1


def test_a_process_reads_as_the_core_or_the_runner_by_its_words_and_its_environment() -> None:
    kept = demo.records(LOCAL)
    core = core_process(kept)
    elsewhere = "/srv/another/core/.venv/bin/"
    # Whatever checkout it runs from: the store under the main checkout's `local/` is what makes it the
    # demonstration's, and a demonstration started from one worktree is ended from another. (Each is judged outside
    # its assert, a process's environment holding the tests' secrets.)
    anothers_checkout = demo.Process([f"{elsewhere}python3", f"{elsewhere}fylgja-core-server"], core.environ)
    cores = (core, core_process(kept, "127.0.0.1:7700"), anothers_checkout)
    read_as_the_core = [demo.is_core(each, kept) for each in cores]
    assert read_as_the_core == [True, True, True]
    for other in (
        None,
        # With the store and no word named for the server: the CLI, a child of the core's, which inherits its
        # environment, and a shell.
        demo.Process([PYTHON, CLI, "twin", "list"], core.environ),
        demo.Process(["/usr/bin/containerlab", "deploy", "--topo", "/srv/example/lab.clab.yml"], core.environ),
        demo.Process(["/bin/bash", "-l"], core.environ),
        demo.Process(["/bin/bash", "-c", "echo fylgja-core-server"], core.environ),
        # With that word and another store, or none it names.
        core_process(demo.records(Path("/srv/another/local"))),
        demo.Process(core.argv, {name: value for name, value in core.environ.items() if name != "FYLGJA_STORE"}),
    ):
        read_as_the_core = [demo.is_core(other, kept)]
        assert read_as_the_core == [False], other and other.argv

    for source in demo.SOURCES:
        runner = runner_process(LOCAL, source)
        is_a_runner = demo.is_runner(runner, LOCAL)
        assert is_a_runner, source
        assert runner.environ["PREFECT_HOME"] == str(demo.prefect_home(LOCAL))
        assert runner.environ[demo.RUNNER_SOURCE] == source
    # Whatever checkout it runs from: one Prefect home is served by one source's runner.
    anothers = runner_process(LOCAL, "netbox", f"{elsewhere}python3", f"{elsewhere}fylgja-orchestrator")
    is_a_runner = demo.is_runner(anothers, LOCAL)
    assert is_a_runner
    runner = runner_process(LOCAL)
    for other in (
        None,
        # Under another home; another command of the example's; Prefect's server under this home; and `edge_dev.py
        # serve` itself, before it has become the runner, under a step's environment.
        runner_process(Path("/srv/another/local")),
        demo.Process([PYTHON, RUNNER, "stage", "mark"], runner.environ),
        demo.Process([PYTHON, str(EDGE_DEV.PREFECT), "server", "start"], runner.environ),
        demo.Process(demo.serve_argv("netbox", LOCAL, MAIN), demo.step_env(ENV | EDGE, kept, LISTEN)),
        demo.Process(["/bin/bash", "-c", "echo serve fylgja-orchestrator"], runner.environ),
    ):
        is_a_runner = demo.is_runner(other, LOCAL)
        assert not is_a_runner, other and other.argv

    host = FakeHost()
    host.processes = {
        1: demo.Process(["/sbin/init"], {}),
        4403: runner_process(LOCAL, "infrahub"),
        4401: runner_process(LOCAL, "netbox"),
        4402: runner_process(Path("/srv/another/local"), "netbox"),
        4404: core,
        4405: demo.Process([], runner.environ),
    }
    assert demo.runners(LOCAL, host) == [(4401, "netbox"), (4403, "infrahub")]
    assert demo.runners(Path("/srv/another/local"), host) == [(4402, "netbox")]
    assert (host.ran, host.started, host.signalled, host.asked) == ([], [], [], [])


def test_the_pids_of_a_ports_listeners_are_read_from_ss() -> None:
    """Lines as `ss -Hltnp` prints them, read on the development host on 2026-11-14: the first for a core this user
    started, the next two for a scratch script's own listeners on loopback, one of them shared with a child."""
    core = 'LISTEN 0      2048       127.0.0.1:7651 0.0.0.0:* users:(("fylgja-core-ser",pid=3163539,fd=4))'
    shared = (
        "LISTEN 0      8                                   127.0.0.1:35305 0.0.0.0:* "
        'users:(("python3",pid=3580025,fd=3),("python3",pid=3580023,fd=3))'
    )
    six = 'LISTEN 0      8                               [::1]:33079    [::]:* users:(("python3",pid=3580023,fd=4))  '
    # A process of another user's is named none; a wildcard and an address with its interface are addresses too.
    anothers = "LISTEN 0      4096                  192.0.2.1%eth0:7651 0.0.0.0:*                       "
    wildcard = 'LISTEN 0      4096               *:7651             *:* users:(("python3",pid=7,fd=3))'
    spaced = 'LISTEN 0      8          127.0.0.1:7652 0.0.0.0:* users:(("a name",pid=11,fd=3))'
    assert demo.listener_pids(core, 7651) == {3163539}
    assert demo.listener_pids(shared, 35305) == {3580025, 3580023}
    assert demo.listener_pids(six, 33079) == {3580023}
    assert demo.listener_pids(anothers, 7651) == set()
    assert demo.listener_pids(spaced, 7652) == {11}
    every = "\n".join([core, shared, six, anothers, wildcard, spaced])
    assert demo.listener_pids(every, 7651) == {3163539, 7}
    # Another port, a port that only begins or ends as this one, and what is no line of `ss`.
    for port in (7650, 765, 17651, 651, 4):
        assert demo.listener_pids(every, port) == set(), port
    for text in ("", "\n", "LISTEN 0 4096\n\nnot a line of ss\n", 'users:(("x",pid=5,fd=3))'):
        assert demo.listener_pids(text, 7651) == set(), text
    # The plain reading, `listeners`, takes the same lines.
    assert demo.listeners(every, 7651) == ["127.0.0.1:7651", "192.0.2.1%eth0:7651", "*:7651"]

    # `owns`: the listener at the address's port is the pid's own, by one read of `ss`.
    host = passing()
    host.listening += [("127.0.0.1:7651", 3163539, "fylgja-core-ser"), ("127.0.0.1:631", None, "cupsd")]
    assert demo.owns(3163539, "127.0.0.1:7651", host) is True
    [heard] = host.ran
    assert (heard.argv, heard.env, heard.capture, heard.timeout) == (HEARD_BY_PID, None, True, demo.DOCKER_TIMEOUT_S)
    assert demo.owns(3163540, "127.0.0.1:7651", host) is False
    assert demo.owns(3163539, "127.0.0.1:631", host) is False
    assert demo.owns(3163539, "127.0.0.1:7650", host) is False
    # An address no port is read from owns nothing, and `ss` is not asked; nor does a read that fails say it does.
    asked = len(host.ran)
    assert demo.owns(3163539, "0.0.0.0:7651", host) is False
    assert len(host.ran) == asked
    host.answer("ss", "-Hltnp", status=127)
    assert demo.owns(3163539, "127.0.0.1:7651", host) is False
    # A core of the tests' `/proc` is shown as `ss` would show it, at its own address, while it runs.
    host = passing()
    host.processes[4502] = core_process(demo.records(LOCAL), "127.0.0.1:7700")
    assert demo.owns(4502, "127.0.0.1:7700", host) is True
    assert demo.owns(4502, LISTEN, host) is False
    host.not_listening.add(4502)
    assert demo.owns(4502, "127.0.0.1:7700", host) is False


def test_the_core_is_started_in_its_own_session_and_waited_for_by_its_version(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    local, kept, host = place(tmp_path)
    kept.core_log.write_text("an earlier start's\n")
    recorded_at_each_ask: list[str | None] = []

    def reply(asked: Any) -> Any:
        recorded_at_each_ask.append(kept.core_pid.read_text() if kept.core_pid.exists() else None)
        return demo.Answer(None, None) if len(recorded_at_each_ask) <= 2 else demo.Answer(200, {"api": "1"})

    host.replies.append(("GET", VERSION, reply))
    unsettled_at_the_start: list[bool] = []
    host.on_start = lambda started: unsettled_at_the_start.append(kept.unsettled.exists())
    env = loaded_env(local, host)
    assert not kept.unsettled.exists()
    pid = demo.start_core(env, kept, LISTEN, host)

    # The port is read free before the start, and the store marked unsettled; the answer is the core's own once
    # `ss` names its pid for the port's listener, asked only when it has answered.
    assert acts(host) == [HEARD, ("start", [CORE]), HEARD_BY_PID]
    assert [(ran.env, ran.capture, ran.timeout) for ran in host.ran] == [(None, True, demo.DOCKER_TIMEOUT_S)] * 2
    assert unsettled_at_the_start == [True]
    [started] = host.started
    assert (started.argv, started.cwd, started.log, started.pid) == ([CORE], ROOT, kept.core_log, pid)
    given_the_cores_environment = same(started.env, demo.core_env(env, kept, LISTEN))
    assert given_the_cores_environment
    reads_as_the_core = demo.is_core(host.process(pid), kept)
    assert reads_as_the_core
    # The pid is written at once, before the first ask; the version is asked with no token, a second apart.
    assert recorded_at_each_ask == [f"{pid}\n"] * 3
    assert [(asked.method, asked.url, asked.auth, asked.body) for asked in host.asked] == [
        ("GET", VERSION, None, None)
    ] * 3
    assert (host.slept, host.now) == ([demo.ASK_S] * 2, 2 * demo.ASK_S)
    assert host.now < demo.CORE_WAIT_S
    # The log before is kept, and this start's is its own.
    assert kept.core_log.with_name("core.log.1").read_text() == "an earlier start's\n"
    assert host.signalled == []
    said = capsys.readouterr()
    assert (said.out.splitlines(), said.err) == (
        [f"demo: the core answers at {LISTEN}, pid {pid}, its log {kept.core_log}"],
        "",
    )
    shown = shows_a_secret(said.out, *started.argv)
    assert not shown

    # A second start keeps the first's log in its turn, and listens where it is told.
    kept.core_log.write_text("the first start's\n")
    answers_its_version(host, listen="127.0.0.1:7700")
    again = demo.start_core(env, kept, "127.0.0.1:7700", host)
    assert kept.core_log.with_name("core.log.1").read_text() == "the first start's\n"
    assert (kept.core_pid.read_text(), host.started[-1].env["FYLGJA_LISTEN"]) == (f"{again}\n", "127.0.0.1:7700")
    assert host.asked[-1].url == "http://127.0.0.1:7700/v1/version"


def test_a_core_that_exits_before_it_answers_names_its_log_and_leaves_no_pid(tmp_path: Path) -> None:
    """A child just started is alive at the first ask: every case here has it so, and gone at a later one."""
    local, kept, host = place(tmp_path)
    exited = (1, (f"the core exited before it answered: read {kept.core_log}",))

    # Two seconds in, as a core that could not read its token file. The store may have been touched: it is unsettled.
    host.on_start = lambda started: host.at(2.0, lambda: host.processes.pop(started.pid))
    with pytest.raises(demo.Stop) as stop:
        demo.start_core(loaded_env(local, host), kept, LISTEN, host)
    assert (stop.value.status, stop.value.lines) == exited
    assert not kept.core_pid.exists()
    assert (host.now, len(host.asked), host.signalled) == (2.0, 3, [])
    assert kept.unsettled.exists()

    # Another process took the port between the read of the listeners and the child's bind, and answers 200 there
    # from the first ask on; the child, alive at the first ask, has exited by the second. The first answer is not
    # taken for the core's: `ss` names another pid for the port, or none, a process of another user's.
    for others_pid in (4600, None):
        host = passing(local, disk=tmp_path)
        answers_its_version(host)
        loses_the_port(host, others_pid)
        with pytest.raises(demo.Stop) as stop:
            demo.start_core(loaded_env(local, host), kept, LISTEN, host)
        assert (stop.value.status, stop.value.lines) == exited
        assert not kept.core_pid.exists()
        assert acts(host) == [HEARD, ("start", [CORE]), HEARD_BY_PID]
        assert (host.now, [asked.url for asked in host.asked], host.signalled) == (1.0, [VERSION, VERSION], [])

    # The same through `settle`, an earlier core's record gone stale and the store unsettled: nothing is listed or
    # destroyed through what answers there, whatever it would list.
    host = passing(local, disk=tmp_path)
    kept.core_pid.write_text("4502\n")
    answers_its_version(host)
    lists(host, ["the-users-own-twin"], [])
    loses_the_port(host, 4600)
    with pytest.raises(demo.Stop) as stop:
        demo.settle(loaded_env(local, host), kept, local, LISTEN, host)
    assert (stop.value.status, stop.value.lines) == exited
    assert acts(host) == [HEARD, ("start", [CORE]), HEARD_BY_PID]
    assert host.signalled == []
    assert kept.unsettled.exists()


def loses_the_port(host: FakeHost, others_pid: int | None) -> None:
    """The next child `host` starts never listens: another process, of pid `others_pid`, None for another user's,
    binds the listen address as it starts, and the child, alive at the first ask, has exited a second on."""

    def lost(started: Started) -> None:
        host.not_listening.add(started.pid)
        host.listening.append((LISTEN, others_pid, "fylgja-core-ser"))
        host.at(host.now + 1.0, lambda: host.processes.pop(started.pid))

    host.on_start = lost


PORT_HELD = (
    "port 7650 is listened on at {} by a process the demonstration did not start: its core cannot start there, and "
    "no twin was read"
)


def test_a_listener_at_the_port_before_the_start_is_refused_and_nothing_is_started(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Whatever answers at the listen address before the demonstration's core is started is not that core: none is
    started beside it, and so nothing is ever listed or destroyed through it."""
    local, kept, host = place(tmp_path)
    held = (("127.0.0.1:7650", 4600), ("*:7650", None), ("[::]:7650", 4600), ("192.0.2.1%eth0:7650", None))
    for address, pid in held:
        host = passing(local, disk=tmp_path)
        host.listening.append((address, pid, "fylgja-core-ser"))
        answers_its_version(host)
        with pytest.raises(demo.Stop) as stop:
            demo.start_core(loaded_env(local, host), kept, LISTEN, host)
        assert (stop.value.status, stop.value.lines) == (1, (PORT_HELD.format(address.rpartition(":")[0]),))
        assert acts(host) == [HEARD]
        assert (host.started, host.asked) == ([], [])
        assert not kept.core_pid.exists() and not kept.unsettled.exists()
    [heard] = host.ran
    assert (heard.env, heard.capture, heard.timeout) == (None, True, demo.DOCKER_TIMEOUT_S)

    # A listener at another port is not at this one.
    host = passing(local, disk=tmp_path)
    host.listening += [("127.0.0.1:17650", 4600, "python3"), ("127.0.0.1:765", 4601, "python3")]
    answers_its_version(host)
    demo.start_core(loaded_env(local, host), kept, LISTEN, host)
    assert len(host.started) == 1
    kept.core_pid.unlink()
    kept.unsettled.unlink()

    # Where the listeners are not read, or the address is not one a port is read from, nothing is started either.
    host = passing(local, disk=tmp_path)
    host.answer("ss", "-Hltn", status=127)
    with pytest.raises(demo.Stop) as stop:
        demo.start_core(loaded_env(local, host), kept, LISTEN, host)
    assert (stop.value.status, stop.value.lines) == (
        1,
        ("`ss -Hltn` exited 127: whether port 7650 is free was not read, and no core was started",),
    )
    host = passing(local, disk=tmp_path)
    with pytest.raises(demo.Stop) as stop:
        demo.start_core(loaded_env(local, host), kept, "0.0.0.0:7650", host)
    assert (stop.value.status, stop.value.lines) == (1, (LISTEN_REFUSED,))
    assert (host.ran, host.started) == ([], [])
    assert not kept.core_pid.exists() and not kept.unsettled.exists()

    # The reviewer's case: a record gone stale and the store unsettled, then a core run by hand at the same address
    # over a store of its own, holding a twin of the user's. `settle` starts nothing beside it and asks it nothing.
    local, kept, host = place(tmp_path / "by-hand")
    host.processes[4600] = core_process(demo.records(tmp_path / "another" / "local"))
    kept.source.write_text("netbox\n")
    kept.core_pid.write_text("4502\n")
    unsettle(kept)
    exits_at_its_signal(host)
    answers_its_version(host)
    lists(host, ["the-users-own-twin"], [])
    with pytest.raises(demo.Stop) as stop:
        demo.settle(loaded_env(local, host), kept, local, LISTEN, host)
    assert (stop.value.status, stop.value.lines) == (1, (PORT_HELD.format("127.0.0.1"),))
    assert acts(host) == [HEARD]
    assert (host.started, host.asked, host.signalled) == ([], [], [])
    assert kept.unsettled.exists() and 4600 in host.processes
    capsys.readouterr()

    # `down` there is exit 1, says why, still stops the source, and is exit 1 again when run again: the store has
    # not been read. Once the port is free it starts its own core, reads its own store empty, and is exit 0.
    host.answer("make")
    for _ in range(2):
        host.acts.clear()
        assert status(host, down(local)) == 1
        assert acts(host) == [HEARD, made(local, "netbox-down")]
        assert capsys.readouterr().err.splitlines() == [
            f"demo: {PORT_HELD.format('127.0.0.1')}",
            f"demo: {UNSETTLED.format(kept.unsettled)}",
            NOT_ALL_ENDED,
        ]
        assert kept.unsettled.exists() and 4600 in host.processes
    del host.processes[4600]
    lists(host, [])
    host.acts.clear()
    assert status(host, down(local)) == 0
    [started] = host.started
    assert acts(host) == [
        HEARD,
        ("start", [CORE]),
        HEARD_BY_PID,
        LIST,
        HEARD_BY_PID,
        (started.pid, TERM),
        made(local, "netbox-down"),
    ]
    assert not kept.unsettled.exists() and not kept.core_pid.exists()


def test_an_answer_from_a_port_the_child_does_not_own_is_not_the_cores(tmp_path: Path) -> None:
    """The child alive throughout and never listening, as a core stopped before its bind, while what bound the port
    after the listeners were read answers 200 at every ask: the wait runs to its bound, and no answer is the core's.
    Likewise where `ss` cannot be asked who listens."""
    for case, who in enumerate(("another pid", "another user's", "ss not read")):
        local, kept, host = place(tmp_path / str(case))
        answers_its_version(host)

        def never_binds(started: Started, host: FakeHost = host, who: str = who) -> None:
            host.not_listening.add(started.pid)
            if who == "ss not read":
                host.answer("ss", "-Hltnp", status=1)
            else:
                host.listening.append((LISTEN, 4600 if who == "another pid" else None, "fylgja-core-ser"))

        host.on_start = never_binds
        with pytest.raises(demo.Stop) as stop:
            demo.start_core(loaded_env(local, host), kept, LISTEN, host)
        assert (stop.value.status, stop.value.lines) == (
            1,
            (
                f"the core did not answer at {LISTEN} within 60 s: read {kept.core_log}; end it by its pid, "
                f"{host.started[0].pid}, then run make demo-down",
            ),
        ), who
        # Who listens is asked after every 200, and never believed.
        assert acts(host) == [HEARD, ("start", [CORE]), *([HEARD_BY_PID] * 60)], who
        assert len(host.asked) == 60, who
        assert kept.core_pid.read_text() == f"{host.started[0].pid}\n", who
        assert (host.signalled, kept.unsettled.exists()) == ([], True), who


def test_a_core_that_never_answers_is_a_failure_at_60_s_and_is_left_for_demo_down(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    local, kept, host = place(tmp_path)
    asked_at: list[float] = []

    def reply(asked: Any) -> Any:
        asked_at.append(host.now)
        return demo.Answer(None, None)

    host.replies.append(("GET", VERSION, reply))
    with pytest.raises(demo.Stop) as stop:
        demo.start_core(loaded_env(local, host), kept, LISTEN, host)
    assert (stop.value.status, stop.value.lines) == (
        1,
        (
            f"the core did not answer at {LISTEN} within 60 s: read {kept.core_log}; end it by its pid, "
            f"{host.started[0].pid}, then run make demo-down",
        ),
    )
    # No ask at or after the bound; the core is left as it is, recorded: the next `down` ends one that has come to
    # listen, and leaves and names one that has not, so the sentence says what is true of both. Who listens is not
    # asked where nothing answered.
    assert asked_at == [second * demo.ASK_S for second in range(60)]
    assert max(asked_at) < demo.CORE_WAIT_S <= host.now
    [started] = host.started
    assert kept.core_pid.read_text() == f"{started.pid}\n"
    reads_as_the_core = demo.is_core(host.process(started.pid), kept)
    assert reads_as_the_core
    assert host.signalled == []
    assert acts(host) == [HEARD, ("start", [CORE])]

    # An answer that is not 200 is no answer of the core's: a proxy's 502, or another service's 404.
    for refused in (502, 404):
        host = passing(local, disk=tmp_path)
        host.replies.append(("GET", VERSION, demo.Answer(refused, None)))
        with pytest.raises(demo.Stop) as stop:
            demo.start_core(loaded_env(local, host), kept, LISTEN, host)
        assert stop.value.lines[0].startswith(f"the core did not answer at {LISTEN} within 60 s")
    capsys.readouterr()

    # `down` then ends it. Where it listens and does not list its twins, why it did not is said, it is ended, and
    # one started in its place lists them.
    host = passing(local, disk=tmp_path)
    kept.source.write_text("netbox\n")
    hung = int(kept.core_pid.read_text())
    host.processes[hung] = core_process(kept)
    host.next_pid = hung + 1000
    exits_at_its_signal(host)
    answers_its_version(host)
    listings = iter([demo.Done(2, ""), demo.Done(0, "[]\n")])
    host.answers[(CLI, "twin", "list", "--json")] = lambda ran: next(listings)
    host.answer("make")
    assert status(host, down(local)) == 0
    [replacement] = host.started
    assert acts(host) == [
        HEARD_BY_PID,
        LIST,
        (hung, TERM),
        HEARD,
        HEARD,
        ("start", [CORE]),
        HEARD_BY_PID,
        LIST,
        HEARD_BY_PID,
        (replacement.pid, TERM),
        made(local, "netbox-down"),
    ]
    assert not kept.core_pid.exists() and not kept.unsettled.exists()
    assert hung not in host.processes
    said = capsys.readouterr()
    assert (said.out.splitlines()[:4], said.err) == (
        [
            f"demo: `fylgja-core twin list --json` exited 2: the twins of the core at {LISTEN} were not read",
            f"demo: ending the core, pid {hung}, which did not list its twins, to start one that does",
            f"demo: the core, pid {hung}, ended",
            f"demo: starting a core at {LISTEN}, to end what the store of an earlier one holds",
        ],
        "",
    )

    # Where the list fails for the one started in its place too, that one is left up, and named with the reason.
    local, kept, host = place(tmp_path / "twice")
    host.processes[4502] = core_process(kept)
    kept.core_pid.write_text("4502\n")
    unsettle(kept)
    exits_at_its_signal(host)
    answers_its_version(host)
    host.answers[(CLI, "twin", "list", "--json")] = demo.Done(2, "")
    with pytest.raises(demo.Stop) as stop:
        demo.settle(loaded_env(local, host), kept, local, LISTEN, host)
    [replacement] = host.started
    assert (stop.value.status, stop.value.lines) == (
        1,
        (
            f"`fylgja-core twin list --json` exited 2: the twins of the core at {LISTEN} were not read",
            LEFT_UP.format(replacement.pid, LISTEN, kept.core_log),
        ),
    )
    assert host.signalled == [(4502, TERM)]
    assert (kept.core_pid.read_text(), kept.unsettled.exists()) == (f"{replacement.pid}\n", True)

    # A recorded core whose own `FYLGJA_LISTEN` is no address a port is read from is said as that, `ss` not being
    # asked: it is left, and nothing is read through it.
    local, kept, host = place(tmp_path / "its-own-listen")
    off_loopback = demo.core_env(ENV | EDGE, kept, LISTEN) | {"FYLGJA_LISTEN": "0.0.0.0:7650"}
    host.processes[4502] = demo.Process([PYTHON, CORE], off_loopback)
    kept.core_pid.write_text("4502\n")
    unsettle(kept)
    with pytest.raises(demo.Stop) as stop:
        demo.settle(loaded_env(local, host), kept, local, LISTEN, host)
    assert (stop.value.status, stop.value.lines) == (
        1,
        (
            "the core, pid 4502, was given a FYLGJA_LISTEN that is not 127.0.0.1:<port>: no twin was read through "
            "it; it is left up: end it by its pid, then run make demo-down again",
        ),
    )
    assert (host.acts, host.asked, kept.unsettled.exists()) == ([], [], True)

    # Where the recorded core is not shown to own the listener at its own address, as one that never came to bind,
    # it is asked nothing and left, and that no twin was read is said: the address may be another's to answer at.
    listeners_there: list[list[tuple[str, int | None, str]]] = [
        [],
        [(LISTEN, 4600, "fylgja-core-ser")],
        [(LISTEN, None, "fylgja-core-ser")],
    ]
    for case, others in enumerate(listeners_there):
        local, kept, host = place(tmp_path / f"deaf-{case}")
        kept.source.write_text("netbox\n")
        host.processes[4502] = core_process(kept)
        host.not_listening.add(4502)
        host.listening += others
        kept.core_pid.write_text("4502\n")
        unsettle(kept)
        exits_at_its_signal(host)
        answers_its_version(host)
        lists(host, ["the-users-own-twin"], [])
        host.answer("make")
        capsys.readouterr()
        assert status(host, down(local)) == 1
        assert acts(host) == [HEARD_BY_PID, made(local, "netbox-down")]
        assert (host.signalled, host.started, host.asked) == ([], [], [])
        assert (kept.core_pid.read_text(), kept.unsettled.exists()) == ("4502\n", True)
        assert capsys.readouterr().err.splitlines() == [
            f"demo: the core, pid 4502, is not shown by `ss -Hltnp` to listen at {LISTEN}: no twin was read, since "
            "what answers there may be another's; it is left up: end it by its pid if it never listens, then run "
            "make demo-down again",
            f"demo: {UNSETTLED.format(kept.unsettled)}",
            NOT_ALL_ENDED,
        ]


def test_a_core_that_cannot_be_started_is_a_failure_in_the_errors_own_word(tmp_path: Path) -> None:
    """What `Popen` raises of a command that is not there, or is not this user's to run, is said by its word and the
    command's path: never by its text, and with nothing of the environment it was to be given."""
    local, kept, _ = place(tmp_path)

    class Unstartable(FakeHost):
        raised: OSError = FileNotFoundError(2, "No such file or directory", CORE)

        def start(self, argv: Sequence[str], *, env: Mapping[str, str], cwd: Path, log: Path) -> int:
            raise self.raised

    for raised, word in (
        (FileNotFoundError(2, "No such file or directory", CORE), "No such file or directory"),
        (PermissionError(13, "Permission denied", CORE), "Permission denied"),
        (OSError(8, "Exec format error", CORE), "Exec format error"),
    ):
        host = Unstartable(disk=tmp_path)
        host.answers[("ss",)] = host.heard
        host.raised = raised
        kept.core_pid.write_text("4502\n")
        with pytest.raises(demo.Stop) as stop:
            demo.start_core(loaded_env(local, host), kept, LISTEN, host)
        assert (stop.value.status, stop.value.lines) == (
            1,
            (f"the core was not started, {word}: its command is {CORE} and its log {kept.core_log}",),
        )
        assert not kept.core_pid.exists()
        assert (host.asked, host.signalled, host.slept) == ([], [], [])
        shown = shows_a_secret(*stop.value.lines, str(stop.value))
        assert not shown

    host = Unstartable(disk=tmp_path)
    host.raised = FileNotFoundError(2, "No such file or directory", "python3")
    host.answer(*demo.api_argv(local, MAIN)[:4], out=f"{API}\n")
    kept.runner_pid.write_text("4501\n")
    with pytest.raises(demo.Stop) as stop:
        demo.start_runner("netbox", loaded_env(local, host), kept, local, MAIN, LISTEN, host)
    assert (stop.value.status, stop.value.lines) == (
        1,
        (
            "the runner was not started, No such file or directory: its command is python3 and its log "
            f"{kept.runner_log}",
        ),
    )
    assert not kept.runner_pid.exists()
    assert (host.asked, host.signalled, host.slept) == ([], [], [])
    shown = shows_a_secret(*stop.value.lines, str(stop.value))
    assert not shown


def test_a_child_whose_pid_cannot_be_recorded_is_ended(tmp_path: Path) -> None:
    """No child runs unrecorded: where its pid cannot be written, here a directory standing where the file is to be,
    it is ended, and the run stops saying so, or saying that it still stands."""
    unrecorded = "the {}, pid {}, was started and its pid could not be written to {}, Is a directory: {}"
    for stays in (False, True):
        local, kept, host = place(tmp_path / str(stays))
        kept.core_pid.mkdir()
        kept.runner_pid.mkdir()
        if not stays:
            exits_at_its_signal(host)
        answers_its_version(host)
        serves_prefect(host, local)
        ended = "it still stands, and is to be ended by its pid" if stays else "it was ended"

        with pytest.raises(demo.Stop) as stop:
            demo.start_core(loaded_env(local, host), kept, LISTEN, host)
        [core] = host.started
        assert (stop.value.status, stop.value.lines) == (
            1,
            (unrecorded.format("core", core.pid, kept.core_pid, ended),),
        )
        assert host.signalled == ([(core.pid, TERM), (core.pid, KILL)] if stays else [(core.pid, TERM)])
        assert (core.pid in host.processes) is stays
        assert host.asked == []

        host.signalled.clear()
        with pytest.raises(demo.Stop) as stop:
            demo.start_runner("netbox", loaded_env(local, host), kept, local, MAIN, LISTEN, host)
        runner = host.started[-1]
        assert (stop.value.status, stop.value.lines) == (
            1,
            (unrecorded.format("runner", runner.pid, kept.runner_pid, ended),),
        )
        assert host.signalled == ([(runner.pid, TERM), (runner.pid, KILL)] if stays else [(runner.pid, TERM)])
        assert host.asked == []


def test_the_runner_serves_once_its_line_its_process_and_both_deployments_say_so(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    local, kept, host = place(tmp_path)
    kept.runner_log.write_text(SERVING)
    # Both deployments `READY` from the first ask, as a runner that has stopped leaves them, the process the runner
    # a second in, and the log of this start empty, the line of the start before being in the log kept: not yet.
    # The line written, three seconds in: done.
    serves_prefect(host, local)
    host.on_start = lambda started: host.at(1.0, lambda: becomes(host, started.pid, runner_process(local, "netbox")))
    host.at(3.0, lambda: becomes(host, host.started[0].pid, runner_process(local, "netbox"), kept.runner_log))
    env = loaded_env(local, host)
    pid = demo.start_runner("netbox", env, kept, local, MAIN, LISTEN, host)

    assert (host.now, host.slept) == (3.0, [demo.ASK_S] * 3)
    [started] = host.started
    assert (started.argv, started.cwd, started.log, started.pid) == (
        demo.serve_argv("netbox", local, MAIN),
        ROOT,
        kept.runner_log,
        pid,
    )
    # Its environment is a step's: the auth as `local/.env` names it, which `edge_dev.py` gives Prefect's client, and
    # none under Prefect's own name of this script's making.
    given_a_steps_environment = same(started.env, demo.step_env(env, kept, LISTEN))
    assert given_a_steps_environment
    assert "PREFECT_API_AUTH_STRING" not in started.env and "FYLGJA_ORCHESTRATOR_AUTH" in started.env
    assert kept.runner_pid.read_text() == f"{pid}\n"
    assert kept.runner_log.with_name("runner.log.1").read_text() == SERVING
    # Prefect's API is read first, by the words `make netbox-hook` reads it by, under the same environment.
    [api] = host.ran
    assert (api.argv, api.cwd) == (demo.api_argv(local, MAIN), ROOT)
    assert (api.capture, api.timeout) == (True, demo.DOCKER_TIMEOUT_S)
    api_read_under_a_steps_environment = same(api.env, demo.step_env(env, kept, LISTEN))
    assert api_read_under_a_steps_environment
    assert acts(host) == [demo.api_argv(local, MAIN), ("start", demo.serve_argv("netbox", local, MAIN))]
    # Each deployment is asked by its exact name, once the line is there and the process is the runner, with the
    # auth in the seam's own argument and in no URL.
    assert [(asked.method, asked.url, asked.body) for asked in host.asked] == [
        ("GET", PLAN_READY, None),
        ("GET", REHEARSE_READY, None),
    ]
    auth_given_to_the_seam = all(same(asked.auth, AUTH) for asked in host.asked)
    assert auth_given_to_the_seam
    said = capsys.readouterr()
    assert (said.out.splitlines(), said.err) == (
        [f"demo: the runner serves stage-plan/main and twin-rehearse/main, pid {pid}, its log {kept.runner_log}"],
        "",
    )
    shown = shows_a_secret(said.out, *started.argv, *api.argv, *(asked.url for asked in host.asked))
    assert not shown
    assert host.signalled == []

    # The line there and the process the runner from the first second, and a deployment `NOT_READY`, as each was
    # read at a first ask, until the fifth: done then, and not before.
    local, kept, host = place(tmp_path / "again")
    serves_prefect(host, local, ready_from=5.0)
    host.on_start = lambda started: host.at(
        1.0, lambda: becomes(host, started.pid, runner_process(local, "infrahub"), kept.runner_log)
    )
    pid = demo.start_runner("infrahub", loaded_env(local, host), kept, local, MAIN, LISTEN, host)
    assert host.now == 5.0
    assert host.started[0].argv == demo.serve_argv("infrahub", local, MAIN)
    # The second deployment is asked only where the first is `READY`.
    assert [asked.url for asked in host.asked] == [PLAN_READY] * 4 + [PLAN_READY, REHEARSE_READY]


def test_a_runner_that_exits_is_a_failure_naming_its_log(tmp_path: Path) -> None:
    local, kept, host = place(tmp_path)
    serves_prefect(host, local)
    # As `edge_dev.py serve` exits 2 where a name the runner needs is not set, having said so in its log.
    host.on_start = lambda started: host.at(1.0, lambda: host.processes.pop(started.pid))
    with pytest.raises(demo.Stop) as stop:
        demo.start_runner("netbox", loaded_env(local, host), kept, local, MAIN, LISTEN, host)
    assert (stop.value.status, stop.value.lines) == (
        1,
        (f"the runner exited before it served: read {kept.runner_log}",),
    )
    assert not kept.runner_pid.exists()
    assert (host.now, host.asked, host.signalled) == (1.0, [], [])

    # One that never serves is left, recorded, for `down` to end: no read of it at or after the bound. Each of the
    # three is asked for: no line; a process that does not read as this home's runner, which the script's own words
    # do not lead to and `settle` could not end, here a runner under another home; and a deployment that is not
    # `READY`, is not there, is refused the auth or is not answered.
    for never in ("no line", "not the runner", "not ready", "no such deployment", "auth refused", "nothing answers"):
        local, kept, host = place(tmp_path / never.replace(" ", "-"))
        host.answer(*demo.api_argv(local, MAIN)[:4], out=f"{API}\n")
        asked_at: list[float] = []

        def reply(asked: Any, never: str = never, host: FakeHost = host, asked_at: list[float] = asked_at) -> Any:
            asked_at.append(host.now)
            if never == "no such deployment":
                return demo.Answer(404, {"detail": "Deployment not found"})
            if never == "auth refused":
                return demo.Answer(401, {"exception_message": "Unauthorized"})
            if never == "nothing answers":
                return demo.Answer(None, None)
            return demo.Answer(200, {"id": "an-id", "status": "NOT_READY" if never == "not ready" else "READY"})

        host.replies.append(("GET", f"{API}/deployments/name/", reply))
        if never != "no line":

            def written(log: Path = kept.runner_log) -> None:
                log.write_text(SERVING)

            host.at(1.0, written)
        home = tmp_path / "another" / "local" if never == "not the runner" else local

        def a_second_in(started: Started, host: FakeHost = host, home: Path = home) -> None:
            host.at(1.0, lambda: becomes(host, started.pid, runner_process(home, "netbox")))

        host.on_start = a_second_in
        with pytest.raises(demo.Stop) as stop:
            demo.start_runner("netbox", loaded_env(local, host), kept, local, MAIN, LISTEN, host)
        assert (stop.value.status, stop.value.lines) == (
            1,
            (
                "the runner did not serve stage-plan/main and twin-rehearse/main within 60 s: read "
                f"{kept.runner_log}; make demo-down ends it",
            ),
        ), never
        assert host.now >= demo.SERVE_WAIT_S > max(asked_at, default=0.0), never
        assert bool(asked_at) is (never not in ("no line", "not the runner")), never
        assert kept.runner_pid.read_text() == f"{host.started[0].pid}\n", never
        assert host.signalled == [], never
        shown = shows_a_secret(*stop.value.lines)
        assert not shown


def test_prefects_api_is_read_by_the_hooks_words_and_is_exact(tmp_path: Path) -> None:
    local, kept, host = place(tmp_path)
    env = demo.step_env(loaded_env(local, host), kept, LISTEN)
    for printed in (f"{API}\n", f"{API}/\n", f"  {API}  \n"):
        host.answer(*demo.api_argv(local, MAIN)[:4], out=printed)
        assert demo.prefect_api(env, local, MAIN, host) == API
    [ran] = host.ran[-1:]
    assert (ran.argv, ran.cwd) == (demo.api_argv(local, MAIN), ROOT)
    assert (ran.capture, ran.timeout) == (True, demo.DOCKER_TIMEOUT_S)

    words = "python3 -I scripts/edge_dev.py api"
    host.answer(*demo.api_argv(local, MAIN)[:4], status=1)
    with pytest.raises(demo.Stop) as stop:
        demo.prefect_api(env, local, MAIN, host)
    assert (stop.value.status, stop.value.lines) == (1, (f"`{words}` exited 1: Prefect's API was not read",))
    for printed in (
        "",
        "\n",
        "edge_dev: api: no gateway\n",
        f"{API}\nand a second line\n",
        "http://\n",
        "https://192.0.2.1:4200/api\n",
        f"{API}?a=b\n",
        f"http://fylgja:word@{BIND}:4200/api\n",
    ):
        host.answer(*demo.api_argv(local, MAIN)[:4], out=printed)
        with pytest.raises(demo.Stop) as stop:
            demo.prefect_api(env, local, MAIN, host)
        assert (stop.value.status, stop.value.lines) == (
            1,
            (f"`{words}` printed no http address alone: Prefect's API was not read",),
        ), printed

    # Where the API is not read no runner is started.
    host.answer(*demo.api_argv(local, MAIN)[:4], status=1)
    with pytest.raises(demo.Stop):
        demo.start_runner("netbox", loaded_env(local, host), kept, local, MAIN, LISTEN, host)
    assert (host.started, host.asked) == ([], [])
    assert not kept.runner_pid.exists()


def test_end_terms_and_kills_only_what_stays() -> None:
    """As `test_dev_plumbing.py`'s of `edge_dev.end_session`, through the seam; and a pid is signalled only while it
    still reads as the caller's, read again before each signal, and the answer is whether the process is gone."""
    sleeper, shell = demo.Process(["sleep", "600"], {}), demo.Process(["/bin/bash"], {})

    def ours(process: Any) -> bool:
        return bool(process == sleeper)

    host = FakeHost()
    host.processes[4243] = sleeper
    host.at(2.0, lambda: host.processes.pop(4243))
    assert demo.end(4243, host, ours) is True
    assert host.signalled == [(4243, TERM)]
    assert (host.now, set(host.slept)) == (2.0, {demo.STOP_POLL_S})

    # One that stays through SIGTERM and goes at SIGKILL is waited for after that too, so that what it held is free.
    host = FakeHost()
    host.processes[4243] = sleeper

    def goes_when_killed(pid: int, number: int) -> None:
        if number == KILL:
            host.at(host.now + 0.5, lambda: host.processes.pop(pid))

    host.on_signal = goes_when_killed
    assert demo.end(4243, host, ours) is True
    assert host.signalled == [(4243, TERM), (4243, KILL)]
    assert demo.STOP_WAIT_S + 0.5 <= host.now <= demo.STOP_WAIT_S + demo.KILL_WAIT_S

    # One that goes in the last half second of its wait is read gone before SIGKILL, and is not sent it.
    host = FakeHost()
    host.processes[4243] = sleeper
    host.at(demo.STOP_WAIT_S - 0.1, lambda: host.processes.pop(4243))
    assert demo.end(4243, host, ours) is True
    assert (host.signalled, host.now) == ([(4243, TERM)], demo.STOP_WAIT_S)

    # One that stands after SIGKILL and the wait after it is not gone, and the caller is told so.
    host = FakeHost()
    host.processes[4243] = sleeper
    assert demo.end(4243, host, ours) is False
    assert host.signalled == [(4243, TERM), (4243, KILL)]
    assert host.now >= demo.STOP_WAIT_S + demo.KILL_WAIT_S
    assert (demo.STOP_WAIT_S, EDGE_DEV.DOWN_WAIT_S, demo.KILL_WAIT_S) == (30, 30, 1.0)

    # No such process by now, or another at its pid: nothing is sent or waited for, and the caller's is gone.
    host = FakeHost()
    assert demo.end(4243, host, ours) is True
    host.processes[4243] = shell
    assert demo.end(4243, host, ours) is True
    assert (host.signalled, host.slept, host.processes) == ([], [], {4243: shell})

    # The pid another's by the time SIGTERM has had its wait: it is not killed.
    host = FakeHost()
    host.processes[4243] = sleeper
    host.at(10.0, lambda: becomes(host, 4243, shell))
    assert demo.end(4243, host, ours) is True
    assert (host.signalled, host.processes) == ([(4243, TERM)], {4243: shell})

    # A signal that could not be sent to a process that stands, as one of another user's: not gone, at once.
    class NotThisUsers(FakeHost):
        def signal(self, pid: int, number: int) -> bool:
            self.signalled.append((pid, number))
            return False

    host = NotThisUsers()
    host.processes[4243] = sleeper
    assert demo.end(4243, host, ours) is False
    assert (host.signalled, host.slept) == ([(4243, TERM)], [])


def test_a_recorded_pid_that_is_another_process_is_never_signalled(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A pid reused by another process, and a record gone stale: nothing is signalled but a process read as what its
    file says. Where the store is unsettled a core is started to read it, and that one, which the script started and
    recorded, is the one process it ends."""
    shell = demo.Process(["/bin/bash", "-l"], {"PATH": "/usr/bin"})
    # Another store's core, at an address of its own, as two cores on one host have.
    anothers = core_process(demo.records(tmp_path / "another" / "local"), "127.0.0.1:7700")
    not_the_runner = "pid 4302 of {} is not the demonstration's runner: it is left, and the file removed"
    not_the_core = "pid 4301 of {} is not the demonstration's core: it is left, and the file removed"

    # The store settled: `settle` records no signal, starts and runs nothing, removes both files and says each.
    for at_core_pid, at_runner_pid in ((shell, anothers), (anothers, shell)):
        local, kept, host = place(tmp_path / ("settled-shell" if at_core_pid is shell else "settled-core"))
        host.processes[4301], host.processes[4302] = at_core_pid, at_runner_pid
        kept.core_pid.write_text("4301\n")
        kept.runner_pid.write_text("4302\n")
        demo.settle(loaded_env(local, host), kept, local, LISTEN, host)
        assert (host.signalled, host.started, host.ran, host.asked) == ([], [], [], [])
        assert (host.processes[4301], host.processes[4302]) == (at_core_pid, at_runner_pid)
        assert not kept.core_pid.exists() and not kept.runner_pid.exists()
        assert capsys.readouterr().out.splitlines() == [
            f"demo: {not_the_runner.format(kept.runner_pid)}",
            f"demo: {not_the_core.format(kept.core_pid)}",
        ]

    # The store unsettled: a core is started for the purpose, beside the other, and it alone is signalled.
    for at_core_pid, at_runner_pid in ((shell, anothers), (anothers, shell)):
        local, kept, host = place(tmp_path / ("shell" if at_core_pid is shell else "core"))
        host.processes[4301], host.processes[4302] = at_core_pid, at_runner_pid
        kept.core_pid.write_text("4301\n")
        kept.runner_pid.write_text("4302\n")
        unsettle(kept)
        exits_at_its_signal(host)
        answers_its_version(host)
        lists(host, [])
        demo.settle(loaded_env(local, host), kept, local, LISTEN, host)

        [started] = host.started
        assert host.signalled == [(started.pid, TERM)]
        assert (host.processes[4301], host.processes[4302]) == (at_core_pid, at_runner_pid)
        assert not kept.core_pid.exists() and not kept.runner_pid.exists() and not kept.unsettled.exists()
        assert capsys.readouterr().out.splitlines()[:3] == [
            f"demo: {not_the_runner.format(kept.runner_pid)}",
            f"demo: {not_the_core.format(kept.core_pid)}",
            f"demo: starting a core at {LISTEN}, to end what the store of an earlier one holds",
        ]

    # The other store's core at the demonstration's own address: none is started beside it, and it is asked nothing.
    local, kept, host = place(tmp_path / "here")
    host.processes[4301] = core_process(demo.records(tmp_path / "another" / "local"), LISTEN)
    kept.core_pid.write_text("4301\n")
    unsettle(kept)
    exits_at_its_signal(host)
    answers_its_version(host)
    lists(host, ["the-users-own-twin"], [])
    with pytest.raises(demo.Stop) as stop:
        demo.settle(loaded_env(local, host), kept, local, LISTEN, host)
    assert (stop.value.status, stop.value.lines) == (1, (PORT_HELD.format("127.0.0.1"),))
    assert (acts(host), host.started, host.asked) == ([HEARD], [], [])
    assert sorted(host.processes) == [4301]
    assert kept.unsettled.exists()
    capsys.readouterr()

    # The runner's record alone, the store settled: a runner under another home, Prefect's own server, a pid that
    # names no process, and a file that names no pid. Nothing at all is signalled, started or run.
    for case, (recorded, process, said) in enumerate(
        (
            ("4302\n", runner_process(tmp_path / "another" / "local"), not_the_runner),
            ("4302\n", demo.Process([PYTHON, str(EDGE_DEV.PREFECT), "server", "start"], {}), not_the_runner),
            ("4302\n", None, "the runner recorded in {}, pid 4302, is gone: the file removed"),
            ("not a pid\n", shell, "{} names no pid: the file removed"),
            ("\n", shell, "{} names no pid: the file removed"),
        )
    ):
        local, kept, host = place(tmp_path / f"runner-{case}")
        if process is not None:
            host.processes[4302] = process
        kept.runner_pid.write_text(recorded)
        before = dict(host.processes)
        demo.settle(loaded_env(local, host), kept, local, LISTEN, host)
        assert (host.signalled, host.started, host.ran, host.asked) == ([], [], [], [])
        assert host.processes == before
        assert not kept.runner_pid.exists()
        assert capsys.readouterr().out.splitlines() == [f"demo: {said.format(kept.runner_pid)}"]

    # No record at all: nothing is done, and nothing said.
    local, kept, host = place(tmp_path / "none")
    host.processes[4301], host.processes[4302] = core_process(kept), runner_process(local)
    demo.settle(loaded_env(local, host), kept, local, LISTEN, host)
    assert (host.signalled, host.started, host.ran, host.asked) == ([], [], [], [])
    assert capsys.readouterr().out == ""


def test_the_other_sources_runner_and_a_runner_not_recorded_are_each_refused(tmp_path: Path) -> None:
    local, kept, host = place(tmp_path)
    home = local / "prefect"
    not_started = "a runner this demonstration did not start serves {}, pid {}: stop it by its pid"
    others = (
        "the {} demonstration's runner is up, pid {}: one Prefect serves one source's runner; run make demo-down first"
    )

    def refused(source: str) -> tuple[int, tuple[str, ...]] | None:
        try:
            demo.refuse_runners(source, kept, local, host)
        except demo.Stop as stop:
            return stop.status, stop.lines
        return None

    # No runner under the home, whatever is recorded and whatever serves another home: none is refused.
    host.processes[4400] = runner_process(tmp_path / "another" / "local", "infrahub")
    assert refused("netbox") is None
    kept.runner_pid.write_text("4401\n")
    assert refused("netbox") is None

    # One the demonstration did not start, by hand or by another's: whichever source it serves.
    kept.runner_pid.unlink()
    host.processes[4401] = runner_process(local, "netbox")
    for source in demo.SOURCES:
        assert refused(source) == (2, (not_started.format(home, 4401),))
    kept.runner_pid.write_text("4301\n")
    host.processes[4301] = demo.Process(["/bin/bash", "-l"], {})
    assert refused("netbox") == (2, (not_started.format(home, 4401),))
    kept.runner_pid.write_text("not a pid\n")
    assert refused("netbox") == (2, (not_started.format(home, 4401),))

    # The recorded one: of the other source it is refused, and of this source it is none, for `settle` to end.
    kept.runner_pid.write_text("4401\n")
    assert refused("infrahub") == (2, (others.format("netbox", 4401),))
    assert refused("netbox") is None
    host.processes[4401] = runner_process(local, "infrahub")
    assert refused("netbox") == (2, (others.format("infrahub", 4401),))
    assert refused("infrahub") is None

    # Each is said, the recorded one and one beside it.
    host.processes[4402] = runner_process(local, "netbox")
    assert refused("netbox") == (2, (others.format("infrahub", 4401), not_started.format(home, 4402)))
    assert refused("infrahub") == (2, (not_started.format(home, 4402),))

    # Nothing is started, stopped or run by a refusal, and the record stays.
    assert (host.started, host.signalled, host.ran, host.asked) == ([], [], [], [])
    assert kept.runner_pid.read_text() == "4401\n"
    assert sorted(host.processes) == [4301, 4400, 4401, 4402]


def test_settle_ends_the_runner_then_destroys_every_twin_then_ends_the_core(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    local, kept, host = place(tmp_path)
    host.processes[4501] = runner_process(local, "netbox")
    host.processes[4502] = core_process(kept, "127.0.0.1:7700")
    kept.runner_pid.write_text("4501\n")
    kept.core_pid.write_text("4502\n")
    unsettle(kept)
    exits_at_its_signal(host)
    lists(host, ["rh-a", "rh-b"], [])
    env = loaded_env(local, host)
    demo.settle(env, kept, local, LISTEN, host)

    assert acts(host) == [
        (4501, TERM),
        HEARD_BY_PID,
        LIST,
        HEARD_BY_PID,
        [CLI, "twin", "destroy", "rh-a"],
        HEARD_BY_PID,
        [CLI, "twin", "destroy", "rh-b"],
        HEARD_BY_PID,
        LIST,
        HEARD_BY_PID,
        (4502, TERM),
    ]
    assert (host.started, host.asked) == ([], [])
    assert not kept.runner_pid.exists() and not kept.core_pid.exists() and not kept.unsettled.exists()
    assert sorted(host.processes) == []
    # Who listens at the recorded core's own address is asked first, of `ss`, read and bounded.
    heard, asked_of_the_core = host.ran[0], [ran for ran in host.ran if ran.argv[0] == CLI]
    assert (heard.env, heard.capture, heard.timeout) == (None, True, demo.DOCKER_TIMEOUT_S)
    # The CLI's environment holds the client's token and the address the recorded core listens on, its own and not
    # the one a core would be started at; its words hold neither. A list is read and bounded; a destroy prints as it
    # will, and is given its own bound.
    for ran in asked_of_the_core:
        held = ran.env or {}
        holds_the_clients_token = same(held.get("FYLGJA_API_TOKEN"), CLIENT_TOKEN)
        assert holds_the_clients_token
        assert (held.get("FYLGJA_API_ADDRESS"), "FYLGJA_API_CA" in held, ran.cwd) == ("127.0.0.1:7700", False, ROOT)
        on_its_command_line = shows_a_secret(*ran.argv) or any("127.0.0.1" in word for word in ran.argv)
        assert not on_its_command_line
    assert [(ran.capture, ran.timeout) for ran in asked_of_the_core] == [
        (True, demo.DOCKER_TIMEOUT_S),
        (False, demo.DESTROY_TIMEOUT_S),
        (False, demo.DESTROY_TIMEOUT_S),
        (True, demo.DOCKER_TIMEOUT_S),
    ]
    said = capsys.readouterr()
    assert (said.out.splitlines(), said.err) == (
        [
            "demo: the runner, pid 4501, ended",
            "demo: destroying the twin rh-a, which an earlier run left",
            "demo: destroying the twin rh-b, which an earlier run left",
            "demo: the core, pid 4502, ended",
        ],
        "",
    )
    shown = shows_a_secret(said.out)
    assert not shown

    # A CA of `local/.env`'s own is another core's: the demonstration's serves HTTP, and its CLI is given none.
    local, kept, host = place(tmp_path / "ca")
    host.processes[4502] = core_process(kept)
    kept.core_pid.write_text("4502\n")
    unsettle(kept)
    exits_at_its_signal(host)
    lists(host, [])
    demo.settle(loaded_env(local, host) | {"FYLGJA_API_CA": "/srv/example/ca.pem"}, kept, local, LISTEN, host)
    # Where the core lists none, as after a runner's own end, which asks its twin's deletion: one list, no destroy.
    assert acts(host) == [HEARD_BY_PID, LIST, HEARD_BY_PID, (4502, TERM)]
    assert "FYLGJA_API_CA" not in (host.ran[1].env or {})
    capsys.readouterr()

    # A runner that still stands after SIGKILL is said so, its record kept, and the core's part is not begun.
    local, kept, host = place(tmp_path / "stands")
    host.processes[4501] = runner_process(local, "netbox")
    host.processes[4502] = core_process(kept)
    kept.runner_pid.write_text("4501\n")
    kept.core_pid.write_text("4502\n")
    unsettle(kept)
    with pytest.raises(demo.Stop) as stop:
        demo.settle(loaded_env(local, host), kept, local, LISTEN, host)
    assert (stop.value.status, stop.value.lines) == (1, (STANDS.format("runner", 4501, kept.runner_pid),))
    assert acts(host) == [(4501, TERM), (4501, KILL)]
    assert (kept.runner_pid.read_text(), kept.core_pid.read_text()) == ("4501\n", "4502\n")
    assert kept.unsettled.exists()
    assert "ended" not in capsys.readouterr().out

    # So is a core that stands: the store was read empty, so it is settled, and the core's record is kept.
    local, kept, host = place(tmp_path / "core-stands")
    host.processes[4502] = core_process(kept)
    kept.core_pid.write_text("4502\n")
    unsettle(kept)
    lists(host, [])
    with pytest.raises(demo.Stop) as stop:
        demo.settle(loaded_env(local, host), kept, local, LISTEN, host)
    assert (stop.value.status, stop.value.lines) == (1, (STANDS.format("core", 4502, kept.core_pid),))
    assert acts(host) == [HEARD_BY_PID, LIST, HEARD_BY_PID, (4502, TERM), (4502, KILL)]
    assert (kept.core_pid.read_text(), kept.unsettled.exists()) == ("4502\n", False)
    assert "ended" not in capsys.readouterr().out

    # A listen address that does not read: nothing at all is done, and check 9's sentence is the reason.
    local, kept, host = place(tmp_path / "listen")
    host.processes[4501] = runner_process(local, "netbox")
    kept.runner_pid.write_text("4501\n")
    unsettle(kept)
    for listen in ("0.0.0.0:7650", "127.0.0.1", "localhost:7650"):
        with pytest.raises(demo.Stop) as stop:
            demo.settle(loaded_env(local, host), kept, local, listen, host)
        assert (stop.value.status, stop.value.lines) == (1, (LISTEN_REFUSED,))
    assert (host.acts, host.asked) == ([], [])
    assert (kept.runner_pid.read_text(), kept.unsettled.exists()) == ("4501\n", True)


def test_the_store_is_unsettled_from_a_cores_start_until_a_core_of_its_own_lists_no_twin(tmp_path: Path) -> None:
    """The marker's life: written before a core is started, there at every list and destroy, and removed only once
    the list has answered empty, before the core is ended. With no marker a recorded core is ended and asked
    nothing, the store having been read empty."""
    local, kept, host = place(tmp_path)
    seen: list[tuple[str, bool]] = []
    listings = iter([["rh-a"], ["rh-a"], ["rh-a"], []])

    def at_the_start(started: Started) -> None:
        seen.append(("start", kept.unsettled.exists()))

    def listed(ran: Any) -> Any:
        seen.append(("list", kept.unsettled.exists()))
        return demo.Done(0, json.dumps([{"name": name} for name in next(listings)]) + "\n")

    def destroyed(ran: Any) -> Any:
        seen.append(("destroy", kept.unsettled.exists()))
        return demo.Done(0, "")

    def signalled(pid: int, number: int) -> None:
        seen.append(("signal", kept.unsettled.exists()))
        del host.processes[pid]

    host.on_start, host.on_signal = at_the_start, signalled
    host.answers[(CLI, "twin", "list", "--json")] = listed
    host.answers[(CLI, "twin", "destroy")] = destroyed
    answers_its_version(host)
    assert not kept.unsettled.exists()
    pid = demo.start_core(loaded_env(local, host), kept, LISTEN, host)
    assert seen == [("start", True)]
    assert kept.unsettled.read_bytes() == b""

    # A settle that stops at a twin that stays leaves it; the next, which reads the store empty, removes it.
    with pytest.raises(demo.Stop):
        demo.settle(loaded_env(local, host), kept, local, LISTEN, host)
    assert seen[1:] == [("list", True), ("destroy", True), ("list", True)]
    assert kept.unsettled.exists() and pid in host.processes
    del seen[:]
    demo.settle(loaded_env(local, host), kept, local, LISTEN, host)
    assert seen == [("list", True), ("destroy", True), ("list", True), ("signal", False)]
    assert not kept.unsettled.exists() and not kept.core_pid.exists()

    # No marker: a recorded core is ended as a recorded pid is, and nothing is asked of it or of `ss`.
    local, kept, host = place(tmp_path / "settled")
    host.processes[4502] = core_process(kept)
    kept.core_pid.write_text("4502\n")
    exits_at_its_signal(host)
    demo.settle(loaded_env(local, host), kept, local, LISTEN, host)
    assert acts(host) == [(4502, TERM)]
    assert not kept.core_pid.exists() and not kept.unsettled.exists()

    # No marker and a record gone stale: nothing is started.
    kept.core_pid.write_text("4502\n")
    host.acts.clear()
    demo.settle(loaded_env(local, host), kept, local, LISTEN, host)
    assert (host.acts, kept.core_pid.exists()) == ([], False)


def test_a_twin_left_by_a_core_that_died_is_destroyed_through_a_core_started_for_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    local, kept, host = place(tmp_path)
    kept.core_pid.write_text("4502\n")
    unsettle(kept)
    exits_at_its_signal(host)
    answers_its_version(host, after=1)
    lists(host, ["rh-a"], [])
    env = loaded_env(local, host)
    demo.settle(env, kept, local, LISTEN, host)

    [started] = host.started
    assert acts(host) == [
        HEARD,
        ("start", [CORE]),
        HEARD_BY_PID,
        LIST,
        HEARD_BY_PID,
        [CLI, "twin", "destroy", "rh-a"],
        HEARD_BY_PID,
        LIST,
        HEARD_BY_PID,
        (started.pid, TERM),
    ]
    started_as_the_demonstrations_core = same(started.env, demo.core_env(env, kept, LISTEN))
    assert started_as_the_demonstrations_core
    # It is waited for before it is asked, and asked where it was started.
    assert [asked.url for asked in host.asked] == [VERSION, VERSION]
    assert {(ran.env or {}).get("FYLGJA_API_ADDRESS") for ran in host.ran if ran.argv[0] == CLI} == {LISTEN}
    assert not kept.core_pid.exists() and not kept.unsettled.exists()
    assert sorted(host.processes) == []
    assert capsys.readouterr().out.splitlines() == [
        f"demo: the core recorded in {kept.core_pid}, pid 4502, is gone: the file removed",
        f"demo: starting a core at {LISTEN}, to end what the store of an earlier one holds",
        f"demo: the core answers at {LISTEN}, pid {started.pid}, its log {kept.core_log}",
        "demo: destroying the twin rh-a, which an earlier run left",
        f"demo: the core, pid {started.pid}, ended",
    ]

    # The same with no record of a core at all, the marker alone saying that the store was not read.
    local, kept, host = place(tmp_path / "marker")
    unsettle(kept)
    exits_at_its_signal(host)
    answers_its_version(host)
    lists(host, ["rh-a"], [])
    demo.settle(loaded_env(local, host), kept, local, LISTEN, host)
    assert [words for words in acts(host) if words[:1] == [CLI]] == [LIST, [CLI, "twin", "destroy", "rh-a"], LIST]
    assert not kept.unsettled.exists()

    # A core that exits when started for it, alive at the first ask and gone at the next, is a failure: the twins are
    # not read, and the store stays unsettled.
    local, kept, host = place(tmp_path / "exits")
    kept.core_pid.write_text("4502\n")
    unsettle(kept)
    host.on_start = lambda started: host.at(1.0, lambda: host.processes.pop(started.pid))
    with pytest.raises(demo.Stop) as stop:
        demo.settle(loaded_env(local, host), kept, local, LISTEN, host)
    assert (stop.value.status, stop.value.lines) == (1, (f"the core exited before it answered: read {kept.core_log}",))
    assert (acts(host), host.signalled) == ([HEARD, ("start", [CORE])], [])
    assert kept.unsettled.exists()


def test_a_twin_that_stays_is_a_failure_that_names_it_and_the_core_is_left(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    local, kept, host = place(tmp_path)
    host.processes[4501] = runner_process(local, "infrahub")
    host.processes[4502] = core_process(kept)
    kept.runner_pid.write_text("4501\n")
    kept.core_pid.write_text("4502\n")
    unsettle(kept)
    exits_at_its_signal(host)
    lists(host, ["rh-a", "rh-b", "rh-c"], ["rh-b", "rh-c"])
    # One destroy ends unclean and one outlasts its bound: each is said, and every twin is still asked.
    host.answer(CLI, "twin", "destroy", "rh-b", status=3)
    host.answer(CLI, "twin", "destroy", "rh-c", status=demo.TIMED_OUT)
    with pytest.raises(demo.Stop) as stop:
        demo.settle(loaded_env(local, host), kept, local, LISTEN, host)
    assert (stop.value.status, stop.value.lines) == (
        1,
        (f"still standing after its destroy: rh-b, rh-c; {LEFT_UP.format(4502, LISTEN, kept.core_log)}",),
    )
    assert acts(host) == [
        (4501, TERM),
        HEARD_BY_PID,
        LIST,
        HEARD_BY_PID,
        [CLI, "twin", "destroy", "rh-a"],
        HEARD_BY_PID,
        [CLI, "twin", "destroy", "rh-b"],
        HEARD_BY_PID,
        [CLI, "twin", "destroy", "rh-c"],
        HEARD_BY_PID,
        LIST,
    ]
    assert (kept.core_pid.read_text(), kept.unsettled.exists()) == ("4502\n", True)
    assert sorted(host.processes) == [4502]
    assert capsys.readouterr().out.splitlines()[1:] == [
        "demo: destroying the twin rh-a, which an earlier run left",
        "demo: destroying the twin rh-b, which an earlier run left",
        "demo: `fylgja-core twin destroy rh-b` exited 3",
        "demo: destroying the twin rh-c, which an earlier run left",
        "demo: `fylgja-core twin destroy rh-c` exited 124",
    ]

    # A destroy that exits other than 0 of a twin that is then gone, as one already being deleted, is no failure.
    local, kept, host = place(tmp_path / "gone")
    host.processes[4502] = core_process(kept)
    kept.core_pid.write_text("4502\n")
    unsettle(kept)
    exits_at_its_signal(host)
    lists(host, ["rh-a"], [])
    host.answer(CLI, "twin", "destroy", "rh-a", status=2)
    demo.settle(loaded_env(local, host), kept, local, LISTEN, host)
    assert acts(host)[-1] == (4502, TERM)
    assert not kept.unsettled.exists()

    # A list that is not read, of a core started for the purpose, and the list after the destroys, of a recorded
    # one: a failure that says why and names the core, which is left up, the store still unsettled.
    no_list = "`fylgja-core twin list --json` printed no list of twins: those of the core at {} were not read"
    for case, (done, said) in enumerate(
        (
            (demo.Done(2, ""), "`fylgja-core twin list --json` exited 2: the twins of the core at {} were not read"),
            (demo.Done(0, "no twins\n"), no_list),
            (demo.Done(0, '{"twins": []}\n'), no_list),
            (demo.Done(0, '[{"generation": 1}]\n'), no_list),
            (demo.Done(0, '[{"name": 5}]\n'), no_list),
            (demo.Done(0, ""), no_list),
        )
    ):
        local, kept, host = place(tmp_path / f"unread-{case}")
        kept.core_pid.write_text("4502\n")
        unsettle(kept)
        answers_its_version(host)
        host.answers[(CLI, "twin", "list", "--json")] = done
        with pytest.raises(demo.Stop) as stop:
            demo.settle(loaded_env(local, host), kept, local, LISTEN, host)
        [started] = host.started
        assert (stop.value.status, stop.value.lines) == (
            1,
            (said.format(LISTEN), LEFT_UP.format(started.pid, LISTEN, kept.core_log)),
        )
        assert host.signalled == []
        assert (kept.core_pid.read_text(), kept.unsettled.exists()) == (f"{started.pid}\n", True)

        local, kept, host = place(tmp_path / f"unread-again-{case}")
        host.processes[4502] = core_process(kept)
        kept.core_pid.write_text("4502\n")
        unsettle(kept)
        answers = iter([demo.Done(0, '[{"name": "rh-a"}]\n'), done])

        def in_turn(ran: Any, answers: Any = answers) -> Any:
            return next(answers)

        host.answers[(CLI, "twin", "list", "--json")] = in_turn
        host.answer(CLI, "twin", "destroy")
        with pytest.raises(demo.Stop) as stop:
            demo.settle(loaded_env(local, host), kept, local, LISTEN, host)
        assert (stop.value.status, stop.value.lines) == (
            1,
            (said.format(LISTEN), LEFT_UP.format(4502, LISTEN, kept.core_log)),
        )
        assert (host.signalled, host.started) == ([], [])
        assert (kept.core_pid.read_text(), kept.unsettled.exists()) == ("4502\n", True)


def after_a_netbox_run(tmp_path: Path) -> tuple[Path, Any, FakeHost]:
    """`local/` and the host as a NetBox demonstration leaves them: `source`, the runner and the core recorded and
    up, the core holding no twin, its store unsettled since its start, and the Prefect server `make prefect-up`
    started for it recorded and up. Every
    process exits at its signal, and every make target exits 0."""
    local, kept, host = place(tmp_path)
    kept.source.write_text("netbox\n")
    host.processes[4501] = runner_process(local, "netbox")
    host.processes[4502] = core_process(kept)
    host.processes[4503] = demo.Process(
        [PYTHON, str(EDGE_DEV.PREFECT), "server", "start", "--host", BIND, "--port", "4200", "--no-ui"],
        {"PREFECT_HOME": str(EDGE_DEV.home_of(local))},
    )
    kept.runner_pid.write_text("4501\n")
    kept.core_pid.write_text("4502\n")
    kept.prefect_pid.write_text("4503\n")
    unsettle(kept)
    EDGE_DEV.home_of(local).mkdir()
    EDGE_DEV.pid_file(local).write_text("4503\n")
    exits_at_its_signal(host)
    lists(host, [])
    host.answer("make")
    return local, kept, host


def made(local: Path, target: str, *variables: str) -> list[str]:
    return ["make", "--no-print-directory", target, f"LOCAL={local}", *variables]


def down(local: Path, *more: str) -> list[str]:
    return ["down", "--local", str(local), "--main", str(MAIN), *more]


def test_down_ends_what_the_demonstration_started_and_stops_its_source(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    local, kept, host = after_a_netbox_run(tmp_path)
    assert status(host, down(local)) == 0
    assert acts(host) == [
        (4501, TERM),
        HEARD_BY_PID,
        LIST,
        HEARD_BY_PID,
        (4502, TERM),
        made(local, "prefect-down"),
        made(local, "netbox-down"),
    ]
    assert host.locked == [kept.lock]
    assert (host.started, host.asked) == ([], [])
    # `source` is kept, for a later `down --purge`; the three records of what was ended are gone.
    assert kept.source.read_text() == "netbox\n"
    assert sorted(path.name for path in kept.source.parent.iterdir()) == ["source"]
    # Each target is run as a step is: in the checkout, printing as it will, with no bound of the script's, under
    # the loaded environment with the demonstration's address and token file.
    targets = [ran for ran in host.ran if ran.argv[0] == "make"]
    assert [(ran.cwd, ran.capture, ran.timeout) for ran in targets] == [(ROOT, False, None)] * 2
    env = demo.step_env(loaded_env(local, host), kept, LISTEN)
    each_given_a_steps_environment = all(same(ran.env, env) for ran in targets)
    assert each_given_a_steps_environment
    said = capsys.readouterr()
    assert (said.out.splitlines(), said.err) == (
        [
            "demo: the runner, pid 4501, ended",
            "demo: the core, pid 4502, ended",
            f"demo: the netbox demonstration is ended: its records stay under {kept.source.parent}",
        ],
        "",
    )
    shown = shows_a_secret(said.out, *(word for ran in host.ran for word in ran.argv))
    assert not shown

    # Run again, with nothing left to end but the source, which the record still names.
    host.acts.clear()
    assert status(host, down(local)) == 0
    assert acts(host) == [made(local, "netbox-down")]

    # The listen address is `local/.env`'s where it has one, and Infrahub's demonstration stops Infrahub.
    local, kept, host = after_a_netbox_run(tmp_path / "infrahub")
    kept.source.write_text("infrahub\n")
    kept.core_pid.unlink()
    kept.unsettled.unlink()
    with (local / ".env").open("a") as env_file:
        env_file.write("FYLGJA_LISTEN=127.0.0.1:7700\n")
    assert status(host, down(local)) == 0
    assert acts(host) == [(4501, TERM), made(local, "prefect-down"), made(local, "infrahub-down")]
    assert {(ran.env or {}).get("FYLGJA_API_ADDRESS") for ran in host.ran} == {"127.0.0.1:7700"}


def test_down_leaves_a_prefect_it_did_not_start(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for case in ("no prefect.pid", "another pid", "no server.pid", "no pid"):
        local, kept, host = after_a_netbox_run(tmp_path / case.replace(" ", "-"))
        if case == "no prefect.pid":
            kept.prefect_pid.unlink()
        elif case == "another pid":
            # The server the demonstration started is gone, and another, started by hand since, is recorded.
            EDGE_DEV.pid_file(local).write_text("4600\n")
        elif case == "no server.pid":
            EDGE_DEV.pid_file(local).unlink()
        else:
            kept.prefect_pid.write_text("\n")
        assert status(host, down(local)) == 0, case
        assert [words for words in acts(host) if words[:1] == ["make"]] == [made(local, "netbox-down")], case
        assert host.signalled == [(4501, TERM), (4502, TERM)], case
        assert 4503 in host.processes, case
        # A record that no longer names the server `make prefect-up` records is removed, and said.
        assert not kept.prefect_pid.exists(), case
        left = [line for line in capsys.readouterr().out.splitlines() if "Prefect" in line]
        assert left == (
            []
            if case == "no prefect.pid"
            else [
                f"demo: {kept.prefect_pid} does not name the Prefect server {EDGE_DEV.pid_file(local)} names: "
                "whatever serves there is left, and the file removed"
            ]
        ), case


def test_down_purges_only_by_the_flag(tmp_path: Path) -> None:
    for source in demo.SOURCES:
        local, kept, host = after_a_netbox_run(tmp_path / source)
        kept.source.write_text(f"{source}\n")
        assert status(host, down(local, "--purge")) == 0
        assert acts(host)[-2:] == [made(local, "prefect-down"), made(local, f"{source}-down", "PURGE=1")]
        assert kept.source.read_text() == f"{source}\n"

        local, kept, host = after_a_netbox_run(tmp_path / f"{source}-kept")
        kept.source.write_text(f"{source}\n")
        assert status(host, down(local)) == 0
        assert acts(host)[-1] == made(local, f"{source}-down")
        assert [words for words in acts(host) if "PURGE=1" in words] == []


def test_down_with_nothing_recorded_ends_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    host = passing()
    assert status(host, ["down", *WHERE, "--purge"]) == 0
    said = capsys.readouterr()
    assert (said.out.splitlines(), said.err) == (
        [f"demo: no demonstration is recorded under {LOCAL / 'demo'}: nothing to end"],
        "",
    )
    assert host.locked == [LOCK]
    assert (host.ran, host.started, host.signalled, host.asked) == ([], [], [], [])

    # Whatever else stands under `local/demo/` but the marker and the two recorded pids: no `source`, and nothing
    # of the demonstration's to settle.
    local, kept, host = after_a_netbox_run(tmp_path)
    for record in (kept.source, kept.unsettled, kept.core_pid, kept.runner_pid):
        record.unlink()
    kept.core_log.write_text("an earlier start's\n")
    assert status(host, down(local)) == 0
    assert (host.ran, host.started, host.signalled, host.asked) == ([], [], [], [])
    assert sorted(host.processes) == [4501, 4502, 4503]
    assert capsys.readouterr().out.splitlines() == [
        f"demo: no demonstration is recorded under {local / 'demo'}: nothing to end"
    ]


def test_down_tries_every_act_and_exits_1_where_one_failed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # `prefect-down` exits 1: the source's `down` is still run, and the record of the server kept for another try.
    local, kept, host = after_a_netbox_run(tmp_path)
    host.answer(*made(local, "prefect-down")[:3], status=1)
    assert status(host, down(local)) == 1
    assert acts(host)[-2:] == [made(local, "prefect-down"), made(local, "netbox-down")]
    assert kept.prefect_pid.read_text() == "4503\n"
    assert capsys.readouterr().err.splitlines() == ["demo: make prefect-down exited 1", NOT_ALL_ENDED]

    # A twin that stays: the core is left, the store unsettled, and Prefect and the source are still ended.
    local, kept, host = after_a_netbox_run(tmp_path / "twin")
    lists(host, ["rh-a"], ["rh-a"])
    host.answer(*made(local, "netbox-down")[:3], status=2)
    assert status(host, down(local, "--purge")) == 1
    assert acts(host) == [
        (4501, TERM),
        HEARD_BY_PID,
        LIST,
        HEARD_BY_PID,
        [CLI, "twin", "destroy", "rh-a"],
        HEARD_BY_PID,
        LIST,
        made(local, "prefect-down"),
        made(local, "netbox-down", "PURGE=1"),
    ]
    assert kept.core_pid.read_text() == "4502\n"
    assert (kept.source.read_text(), kept.prefect_pid.exists(), kept.unsettled.exists()) == ("netbox\n", False, True)
    assert capsys.readouterr().err.splitlines() == [
        f"demo: still standing after its destroy: rh-a; {LEFT_UP.format(4502, LISTEN, kept.core_log)}",
        "demo: make netbox-down exited 2",
        f"demo: {UNSETTLED.format(kept.unsettled)}",
        NOT_ALL_ENDED,
    ]

    # A record that names no source: what is recorded is still ended, and neither source is stopped, which is said.
    local, kept, host = after_a_netbox_run(tmp_path / "source")
    kept.source.write_text("nautobot\n")
    assert status(host, down(local)) == 1
    assert acts(host) == [(4501, TERM), HEARD_BY_PID, LIST, HEARD_BY_PID, (4502, TERM), made(local, "prefect-down")]
    assert capsys.readouterr().err.splitlines() == [
        f"demo: {kept.source} names neither infrahub nor netbox: no source was stopped",
        NOT_ALL_ENDED,
    ]

    # A line of `local/.env` that is not read ends the run before anything is ended, exit 2, as it ends `up`.
    local, kept, host = after_a_netbox_run(tmp_path / "unread")
    with (local / ".env").open("a") as env_file:
        env_file.write("X=$HOME\n")
    assert status(host, down(local)) == 2
    assert (host.ran, host.started, host.signalled) == ([], [], [])
    capsys.readouterr()

    # A listen address that does not read: nothing of the runner, the twins or the core is done, for check 9's
    # reason, and Prefect and the source are still ended.
    local, kept, host = after_a_netbox_run(tmp_path / "listen")
    with (local / ".env").open("a") as env_file:
        env_file.write("FYLGJA_LISTEN=0.0.0.0:7650\n")
    assert status(host, down(local)) == 1
    assert acts(host) == [made(local, "prefect-down"), made(local, "netbox-down")]
    assert capsys.readouterr().err.splitlines() == [
        f"demo: {LISTEN_REFUSED}",
        f"demo: {UNSETTLED.format(kept.unsettled)}",
        NOT_ALL_ENDED,
    ]

    # An act that raises is said by the error's own word, and the acts after it are still tried: a record that is
    # not this user's to read; a log that cannot be kept, a directory standing where the log before is to go.
    local, kept, host = after_a_netbox_run(tmp_path / "denied")
    host.denied = {kept.runner_pid}
    assert status(host, down(local)) == 1
    assert acts(host) == [made(local, "prefect-down"), made(local, "netbox-down")]
    assert capsys.readouterr().err.splitlines() == [
        f"demo: the end of the runner, the twins and the core was cut short, Permission denied: {kept.runner_pid}",
        f"demo: {UNSETTLED.format(kept.unsettled)}",
        NOT_ALL_ENDED,
    ]

    local, kept, host = after_a_netbox_run(tmp_path / "log")
    del host.processes[4502]
    kept.core_log.write_text("an earlier start's\n")
    in_the_way = kept.core_log.with_name("core.log.1")
    in_the_way.mkdir()
    assert status(host, down(local)) == 1
    assert acts(host) == [(4501, TERM), HEARD, made(local, "prefect-down"), made(local, "netbox-down")]
    said = capsys.readouterr().err.splitlines()
    assert said[0].startswith("demo: the end of the runner, the twins and the core was cut short, Is a directory: ")
    assert said[1:] == [f"demo: {UNSETTLED.format(kept.unsettled)}", NOT_ALL_ENDED]
    assert host.started == []

    local, kept, host = after_a_netbox_run(tmp_path / "prefect")
    host.denied = {kept.prefect_pid}
    assert status(host, down(local)) == 1
    assert acts(host)[-1] == made(local, "netbox-down")
    assert capsys.readouterr().err.splitlines() == [
        f"demo: make prefect-down was cut short, Permission denied: {kept.prefect_pid}",
        NOT_ALL_ENDED,
    ]


def test_down_is_not_done_until_the_store_has_been_read(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The reviewer's two runs. The recorded core has died and the one started to read the store exits: `down` is
    exit 1, and exit 1 again when run again, trying again each time, the source stopped each time; it is exit 0 only
    once a core of its own has listed no twin."""
    local, kept, host = after_a_netbox_run(tmp_path)
    del host.processes[4502]
    host.on_start = lambda started: host.at(host.now + 1.0, lambda: host.processes.pop(started.pid))
    for run in range(2):
        host.acts.clear()
        assert status(host, down(local)) == 1
        assert [words for words in acts(host) if words[:1] != ["make"]][-2:] == [HEARD, ("start", [CORE])]
        assert acts(host)[-1] == made(local, "netbox-down")
        assert len(host.started) == run + 1
        said = capsys.readouterr()
        assert said.err.splitlines() == [
            f"demo: the core exited before it answered: read {kept.core_log}",
            f"demo: {UNSETTLED.format(kept.unsettled)}",
            NOT_ALL_ENDED,
        ]
        assert "demonstration is ended" not in said.out
        assert kept.unsettled.exists() and not kept.core_pid.exists()

    host.on_start = None
    answers_its_version(host)
    host.acts.clear()
    assert status(host, down(local)) == 0
    served = host.started[-1]
    assert acts(host) == [
        HEARD,
        ("start", [CORE]),
        HEARD_BY_PID,
        LIST,
        HEARD_BY_PID,
        (served.pid, TERM),
        made(local, "netbox-down"),
    ]
    assert not kept.unsettled.exists()
    assert capsys.readouterr().out.splitlines()[-1] == (
        f"demo: the netbox demonstration is ended: its records stay under {kept.source.parent}"
    )


NOT_WHOLE = (
    "the core, pid {}, is no longer shown by `ss -Hltnp` to listen at {}: the store was not read whole, since what "
    "answers there may be another's; run make demo-down again"
)


def dies_and_anothers_binds(host: FakeHost, done: Any, others_pid: int | None = 4600) -> Any:
    """An answer of the CLI's during which the recorded core, pid 4502, exits and another process takes its address:
    one this user runs, which `ss -Hltnp` names by `others_pid`, or with None another user's, which it names by none."""

    def answer(ran: Any) -> Any:
        if 4502 in host.processes:
            host.exit(4502)
            host.listening.append((LISTEN, others_pid, "fylgja-core-ser"))
        return done

    return answer


def test_ownership_is_read_again_before_each_destroy_and_before_the_store_is_called_settled(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The core that owned its listener at the first list may be gone by the next act, and another process at its
    address by then: no twin is destroyed through that one, and an empty list from it settles nothing."""

    # During the first of two destroys: the second twin is not asked destroyed there, and the list is not read again.
    local, kept, host = after_a_netbox_run(tmp_path)
    lists(host, ["rh-a", "rh-b"], [])
    host.answers[(CLI, "twin", "destroy", "rh-a")] = dies_and_anothers_binds(host, demo.Done(2, ""))
    assert status(host, down(local)) == 1
    assert acts(host) == [
        (4501, TERM),
        HEARD_BY_PID,
        LIST,
        HEARD_BY_PID,
        [CLI, "twin", "destroy", "rh-a"],
        HEARD_BY_PID,
        made(local, "prefect-down"),
        made(local, "netbox-down"),
    ]
    assert (kept.unsettled.exists(), kept.core_pid.read_text(), host.signalled) == (True, "4502\n", [(4501, TERM)])
    said = capsys.readouterr()
    assert said.err.splitlines() == [
        f"demo: {NOT_WHOLE.format(4502, LISTEN)}",
        f"demo: {UNSETTLED.format(kept.unsettled)}",
        NOT_ALL_ENDED,
    ]
    assert "demonstration is ended" not in said.out

    # During the one destroy there is, the other process ready to answer the list empty: it is asked for none, and
    # nothing is settled.
    local, kept, host = after_a_netbox_run(tmp_path / "last")
    lists(host, ["rh-a"], [])
    host.answers[(CLI, "twin", "destroy", "rh-a")] = dies_and_anothers_binds(host, demo.Done(0, ""))
    assert status(host, down(local)) == 1
    assert acts(host) == [
        (4501, TERM),
        HEARD_BY_PID,
        LIST,
        HEARD_BY_PID,
        [CLI, "twin", "destroy", "rh-a"],
        HEARD_BY_PID,
        made(local, "prefect-down"),
        made(local, "netbox-down"),
    ]
    assert (kept.unsettled.exists(), host.signalled) == (True, [(4501, TERM)])
    assert capsys.readouterr().err.splitlines()[0] == f"demo: {NOT_WHOLE.format(4502, LISTEN)}"

    # Run again, the other still there: its core's record gone stale, nothing is started beside the other and nothing
    # asked of it. Once the address is free, a core of the demonstration's own reads the store, and it is settled.
    host.acts.clear()
    assert status(host, down(local)) == 1
    assert acts(host) == [HEARD, made(local, "netbox-down")]
    assert capsys.readouterr().err.splitlines()[0] == f"demo: {PORT_HELD.format('127.0.0.1')}"
    host.listening.clear()
    answers_its_version(host)
    lists(host, [])
    host.acts.clear()
    assert status(host, down(local)) == 0
    [started] = host.started
    assert acts(host) == [
        HEARD,
        ("start", [CORE]),
        HEARD_BY_PID,
        LIST,
        HEARD_BY_PID,
        (started.pid, TERM),
        made(local, "netbox-down"),
    ]
    assert not kept.unsettled.exists()
    capsys.readouterr()

    # Between the read of who listens and the first list, which the other answers empty.
    local, kept, host = after_a_netbox_run(tmp_path / "first")
    host.answers[(CLI, "twin", "list", "--json")] = dies_and_anothers_binds(host, demo.Done(0, "[]\n"))
    with pytest.raises(demo.Stop) as stop:
        demo.settle(loaded_env(local, host), kept, local, LISTEN, host)
    assert (stop.value.status, stop.value.lines) == (1, (NOT_WHOLE.format(4502, LISTEN),))
    assert acts(host) == [(4501, TERM), HEARD_BY_PID, LIST, HEARD_BY_PID]
    assert kept.unsettled.exists()

    # The same of a core `settle` itself started: gone by the end of its one destroy.
    local, kept, host = place(tmp_path / "started")
    unsettle(kept)
    answers_its_version(host)
    lists(host, ["rh-a"], [])

    def its_own_dies(ran: Any) -> Any:
        host.exit(host.started[0].pid)
        host.listening.append((LISTEN, None, "fylgja-core-ser"))
        return demo.Done(0, "")

    host.answers[(CLI, "twin", "destroy", "rh-a")] = its_own_dies
    with pytest.raises(demo.Stop) as stop:
        demo.settle(loaded_env(local, host), kept, local, LISTEN, host)
    assert (stop.value.status, stop.value.lines) == (1, (NOT_WHOLE.format(host.started[0].pid, LISTEN),))
    assert (kept.unsettled.exists(), host.signalled) == (True, [])


def test_ownership_is_read_before_the_list_that_follows_the_destroys(tmp_path: Path) -> None:
    """A destroy waits for its verdict, for minutes at the longest, so by the list that follows the destroys the
    reading of who listens made before the last of them is that old. The owned core may be gone by then and another
    process at its address, which a list would reach with the client's token in its environment: the listener is
    read once more, and no list is asked of what is not shown to be the core's."""
    for case, others_pid in enumerate((4600, None)):
        local, kept, host = after_a_netbox_run(tmp_path / str(case))
        # What is at the address by then would list no twin, and every list the test answers is counted.
        lists(host, ["rh-a", "rh-b"], [])
        host.answers[(CLI, "twin", "destroy", "rh-b")] = dies_and_anothers_binds(host, demo.Done(0, ""), others_pid)
        with pytest.raises(demo.Stop) as stop:
            demo.settle(loaded_env(local, host), kept, local, LISTEN, host)
        assert (stop.value.status, stop.value.lines) == (1, (NOT_WHOLE.format(4502, LISTEN),))
        assert acts(host) == [
            (4501, TERM),
            HEARD_BY_PID,
            LIST,
            HEARD_BY_PID,
            [CLI, "twin", "destroy", "rh-a"],
            HEARD_BY_PID,
            [CLI, "twin", "destroy", "rh-b"],
            HEARD_BY_PID,
        ]
        # Nothing run after the last destroy was given the client's token, or anything of the loaded environment.
        assert [ran.env for ran in host.ran[-1:]] == [None]
        # The marker stands and the record is kept, for the `down` that finds the address free again.
        assert (kept.unsettled.exists(), kept.core_pid.read_text(), host.signalled) == (True, "4502\n", [(4501, TERM)])

    # Where the core still owns its listener after the last destroy, the list is asked of it, on that reading.
    local, kept, host = after_a_netbox_run(tmp_path / "owned")
    lists(host, ["rh-a"], [])
    demo.settle(loaded_env(local, host), kept, local, LISTEN, host)
    assert acts(host)[4:] == [[CLI, "twin", "destroy", "rh-a"], HEARD_BY_PID, LIST, HEARD_BY_PID, (4502, TERM)]
    assert not kept.unsettled.exists()


def test_a_port_still_closing_after_a_cores_end_is_waited_for_before_the_next_start(tmp_path: Path) -> None:
    """A core that did not list is ended and one started in its place at the same address: the first's listener can
    outlast its process for a moment, and the start waits for the port, read every tenth of a second, before it
    reads it for its own refusal."""
    local, kept, host = place(tmp_path)
    host.processes[4502] = core_process(kept)
    kept.core_pid.write_text("4502\n")
    unsettle(kept)
    host.lingers = 0.15
    exits_at_its_signal(host)
    answers_its_version(host)
    listings = iter([demo.Done(2, ""), demo.Done(0, "[]\n")])

    def in_turn(ran: Any) -> Any:
        return next(listings)

    host.answers[(CLI, "twin", "list", "--json")] = in_turn
    demo.settle(loaded_env(local, host), kept, local, LISTEN, host)
    [started] = host.started
    # The listener is there at the first two reads and gone at the third; the start's own read follows.
    assert acts(host) == [
        HEARD_BY_PID,
        LIST,
        (4502, TERM),
        HEARD,
        HEARD,
        HEARD,
        HEARD,
        ("start", [CORE]),
        HEARD_BY_PID,
        LIST,
        HEARD_BY_PID,
        (started.pid, TERM),
    ]
    assert (host.slept, demo.PORT_FREE_POLL_S, demo.PORT_FREE_WAIT_S) == ([0.1, 0.1], 0.1, 5.0)
    assert not kept.unsettled.exists()

    # Still there at the bound, as where another process has taken the port: the start's refusal stands.
    local, kept, host = place(tmp_path / "held")
    host.processes[4502] = core_process(kept)
    kept.core_pid.write_text("4502\n")
    unsettle(kept)
    host.lingers = 60.0
    exits_at_its_signal(host)
    host.answers[(CLI, "twin", "list", "--json")] = demo.Done(2, "")
    with pytest.raises(demo.Stop) as stop:
        demo.settle(loaded_env(local, host), kept, local, LISTEN, host)
    assert (stop.value.status, stop.value.lines) == (1, (PORT_HELD.format("127.0.0.1"),))
    waited = acts(host)[3:]
    assert set(map(tuple, waited)) == {("ss", "-Hltn")} and len(waited) >= 51
    assert demo.PORT_FREE_WAIT_S <= host.now + 1e-9 < demo.PORT_FREE_WAIT_S + 2 * demo.PORT_FREE_POLL_S
    assert (host.started, kept.unsettled.exists(), kept.core_pid.exists()) == ([], True, False)

    # A core ended at another port than the one a core is started at is not waited for.
    local, kept, host = place(tmp_path / "elsewhere")
    host.processes[4502] = core_process(kept, "127.0.0.1:7700")
    kept.core_pid.write_text("4502\n")
    unsettle(kept)
    host.lingers = 60.0
    exits_at_its_signal(host)
    answers_its_version(host)
    listings = iter([demo.Done(2, ""), demo.Done(0, "[]\n")])
    host.answers[(CLI, "twin", "list", "--json")] = in_turn
    demo.settle(loaded_env(local, host), kept, local, LISTEN, host)
    assert acts(host)[2:5] == [(4502, TERM), HEARD, ("start", [CORE])]
    assert host.slept == []


def test_a_recorded_runner_not_yet_become_the_runner_is_ended_as_the_runner(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """For about three seconds after its start the pid `runner.pid` names is still `edge_dev.py serve`, by the words
    the script started it by: it is the demonstration's to end, and is not left behind with its record removed."""
    for source in demo.SOURCES:
        local, kept, host = place(tmp_path / source)
        words = demo.serve_argv(source, local, MAIN)
        host.processes[4501] = demo.Process(words, demo.step_env(ENV | EDGE, kept, LISTEN))
        kept.runner_pid.write_text("4501\n")
        exits_at_its_signal(host)
        demo.settle(loaded_env(local, host), kept, local, LISTEN, host)
        assert (acts(host), sorted(host.processes), kept.runner_pid.exists()) == ([(4501, TERM)], [], False)
        assert capsys.readouterr().out.splitlines() == ["demo: the runner, pid 4501, ended"]
        # By then it may have become the runner: it is the same process, and is ended as that.
        host.processes[4501] = demo.Process(words, demo.step_env(ENV | EDGE, kept, LISTEN))
        kept.runner_pid.write_text("4501\n")
        host.on_signal = None

        def execs(host: FakeHost = host, local: Path = local, source: str = source) -> None:
            becomes(host, 4501, runner_process(local, source))

        def exits(host: FakeHost = host) -> None:
            host.exit(4501)

        host.at(host.now + 2.0, execs)
        host.at(host.now + 4.0, exits)
        host.acts.clear()
        demo.settle(loaded_env(local, host), kept, local, LISTEN, host)
        assert (acts(host), sorted(host.processes), kept.runner_pid.exists()) == ([(4501, TERM)], [], False)
        capsys.readouterr()

    # With another `--local`, or other words after `serve`, it is not: left, its record removed, and said.
    local, kept, host = place(tmp_path / "others")
    env = demo.step_env(ENV | EDGE, kept, LISTEN)
    words = demo.serve_argv("netbox", local, MAIN)
    for case, others in enumerate(
        (
            demo.serve_argv("netbox", tmp_path / "another" / "local", MAIN),
            [*words, "--more"],
            words[:-2],
            [*words[:5], "nautobot", *words[6:]],
            [*words[:3], "run", *words[4:], "--", "stage", "mark"],
            demo.api_argv(local, MAIN),
            ["/bin/bash", "-c", " ".join(words)],
        )
    ):
        host.processes[4501] = demo.Process(others, env)
        kept.runner_pid.write_text("4501\n")
        demo.settle(loaded_env(local, host), kept, local, LISTEN, host)
        assert (host.acts, sorted(host.processes), kept.runner_pid.exists()) == ([], [4501], False), case
        assert capsys.readouterr().out.splitlines() == [
            f"demo: pid 4501 of {kept.runner_pid} is not the demonstration's runner: it is left, and the file removed"
        ], case

    # What serves is still judged by `is_runner` alone: a process not yet the runner is none to `runners`, and is
    # not refused as one the demonstration did not start.
    host.processes[4501] = demo.Process(words, env)
    assert demo.runners(local, host) == []
    demo.refuse_runners("netbox", kept, local, host)
    is_a_runner = demo.is_runner(host.processes[4501], local)
    assert not is_a_runner


def test_down_settles_what_is_recorded_though_no_source_is(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A marker or a recorded pid with no `source` beside it is still the demonstration's to settle: `down` does not
    answer that there is nothing to end before it has read them. No source and no Prefect server is stopped, which
    is said, and the exit is by the marker."""
    no_source = "demo: no source is recorded under {}: neither a source nor the Prefect server was stopped"
    local, kept, host = after_a_netbox_run(tmp_path)
    kept.source.unlink()
    lists(host, ["rh-a"], [])
    assert status(host, down(local, "--purge")) == 0
    assert acts(host) == [
        (4501, TERM),
        HEARD_BY_PID,
        LIST,
        HEARD_BY_PID,
        [CLI, "twin", "destroy", "rh-a"],
        HEARD_BY_PID,
        LIST,
        HEARD_BY_PID,
        (4502, TERM),
    ]
    assert sorted(host.processes) == [4503]
    assert sorted(path.name for path in kept.source.parent.iterdir()) == ["prefect.pid"]
    said = capsys.readouterr()
    assert (said.out.splitlines()[-2:], said.err) == (
        [
            no_source.format(kept.source.parent),
            f"demo: what was recorded under {kept.source.parent} is ended",
        ],
        "",
    )

    # Each of the three alone is enough for `settle` to be run: the marker, a core's record, a runner's.
    lives = {"unsettled": None, "core_pid": 4502, "runner_pid": 4501}
    for case, record in enumerate(lives):
        local, kept, host = after_a_netbox_run(tmp_path / str(case))
        for other in ("source", "prefect_pid", "unsettled", "core_pid", "runner_pid"):
            if other != record:
                getattr(kept, other).unlink()
        for pid in (4501, 4502):
            if pid != lives[record]:
                del host.processes[pid]
        answers_its_version(host)
        assert status(host, down(local)) == 0, record
        assert [words for words in acts(host) if words[:1] == ["make"]] == [], record
        assert (len(host.started), bool(host.signalled)) == (int(record == "unsettled"), True), record
        assert sorted(path.name for path in kept.source.parent.iterdir()) == [], record
        capsys.readouterr()

    # The store not read: exit 1, by the marker, and said so.
    local, kept, host = after_a_netbox_run(tmp_path / "unread")
    kept.source.unlink()
    host.not_listening.add(4502)
    assert status(host, down(local)) == 1
    assert [words for words in acts(host) if words[:1] == ["make"]] == []
    said = capsys.readouterr()
    assert said.err.splitlines()[1:] == [f"demo: {UNSETTLED.format(kept.unsettled)}", NOT_ALL_ENDED]
    assert said.out.splitlines()[-1] == no_source.format(kept.source.parent)


UP = {"infrahub": INFRAHUB_UP, "netbox": NETBOX_UP}
"""The read of whether a source is up: its Compose project's running containers."""

OTHER = {"infrahub": "netbox", "netbox": "infrahub"}

NOT_SECRET = (
    "FYLGJA_API_ADDRESS",
    "FYLGJA_INFRAHUB_ADDRESS",
    "FYLGJA_NETBOX_ADDRESS",
    "INFRAHUB_TELEMETRY_OPTOUT",
    "FYLGJA_ORCHESTRATOR_SCOPE",
    "FYLGJA_ORCHESTRATOR_READER",
    "FYLGJA_ORCHESTRATOR_ROOT",
    "FYLGJA_ORCHESTRATOR_NETBOX_READER",
    "FYLGJA_ORCHESTRATOR_NETBOX_SCOPE",
    "FYLGJA_LAB_POOL",
    "FYLGJA_LISTEN",
)
"""The names of `local/.env` whose values are no secret: an address, a scope, a path, a setting. Every other value
the file comes to hold over a run is one."""

def up_of(local: Path, source: str, ref: str = "main") -> list[str]:
    return ["up", source, "--local", str(local), "--main", str(MAIN), "--ref", ref]


def judged(source: str, ref: str = "main") -> list[list[str]]:
    """The reads `checks` makes of a host that meets every precondition, in their order."""
    reads = [
        ["docker", "info"],
        ["docker", "compose", "version"],
        ["containerlab", "version"],
        [*UP[source]],
        ["ss", "-Hltn"],
    ]
    return reads + ([["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"]] if source == "infrahub" else [])


def image_read(ref: str) -> list[str]:
    return ["docker", "image", "inspect", "--format", "{{.Id}}", ref]


def networks_read(host: FakeHost) -> list[list[str]]:
    """The two reads of Docker's networks, as the local driver makes them of the networks `host` has."""
    ids = [short_id(name) for name, _ in host.networks]
    return [["docker", "network", "ls", "-q"], ["docker", "network", "inspect", "--format", demo.FORMAT, *ids]]


def left_up(*standing: str) -> str:
    return f"left up: {', '.join(standing)}; make demo-down ends what the demonstration started"


OPENED = "the change is opened: its rehearsal's verdict is not read"
"""What `up` says at its end until it reads the verdict."""


def secrets_of(local: Path, host: FakeHost) -> list[str]:
    """Every secret a run came to hold: each value of `local/.env` that is not of `NOT_SECRET`, as written, whether
    or not the script reads its line; the tests' own of `demo_host`; and each the fake host made."""
    held: dict[str, str] = NETBOX_DEV.assignments((local / ".env").read_bytes())
    return [*SECRETS, *host.secrets, *(value for name, value in held.items() if value and name not in NOT_SECRET)]


def runbook(heading: str) -> list[str]:
    """The steps of the first fenced block after `heading` in `CONTRIBUTING.md`, in order: each line that begins
    `make `, its comment aside, and the line that says to restart the core, by its first words."""
    text = (ROOT / "CONTRIBUTING.md").read_text()
    assert text.count(f"\n{heading}\n") == 1
    block = text.partition(f"\n{heading}\n")[2].partition("\n```sh\n")[2].partition("\n```\n")[0]
    steps = []
    for line in block.splitlines():
        if line.startswith("make "):
            steps.append(" ".join(line.partition("#")[0].split()))
        elif line.startswith(RESTART):
            steps.append(RESTART)
    return steps


RESTART = "# restart the core"
"""How the line of a runbook begins that has the core started again, once its token file holds the runner's line."""


def as_the_runbook_has_it(source: str, step: Any, less: tuple[str, ...] = ()) -> str:
    """A step in a runbook's words: the core as the line that restarts it, the runner as the target that serves in
    the foreground, a make step as its target and its variables, less those of `less`."""
    if step.kind == "core":
        return RESTART
    if step.kind == "runner":
        return "make orchestrator-serve" + ("" if source == "infrahub" else f" SOURCE={source}")
    assert step.kind == "make"
    return " ".join(["make", step.target, *(variable for variable in step.variables if variable not in less)])


def test_each_sources_steps_are_its_runbooks_in_its_order() -> None:
    assert set(demo.STEPS) == set(demo.SOURCES)
    assert {step.kind for steps in demo.STEPS.values() for step in steps} == {"make", "core", "runner"}

    # NetBox's, word for word, but that the last sets the tag, which asks for the rehearsal.
    netbox = runbook("### With NetBox")
    assert len(netbox) == 8 and netbox[-1] == "make netbox-change"
    steps = demo.STEPS["netbox"]
    assert [as_the_runbook_has_it("netbox", step, less=("NETBOX_TAG=1",)) for step in steps] == netbox
    assert steps[-1] == demo.Step("make", "netbox-change", ("NETBOX_TAG=1",))

    # Infrahub's, but for its seed: the runbook seeds before Prefect is up, and the script once, last, with the
    # proposed change, since a change opened before the runner serves fails its check. The registration is given
    # the branch, which the runbook's target takes from the checkout.
    infrahub = runbook("## Running the example orchestrator")
    assert len(infrahub) == 8 and infrahub.count("make infrahub-seed") == 1
    steps = demo.STEPS["infrahub"]
    seed = demo.Step("make", "infrahub-seed", ("PROPOSED_CHANGE=1",))
    assert steps[-1] == seed
    assert [step for step in steps if step.target == "infrahub-seed"] == [seed]
    assert [as_the_runbook_has_it("infrahub", step, less=(demo.REF,)) for step in steps[:-1]] == [
        line for line in infrahub if line != "make infrahub-seed"
    ]
    assert [step.variables for step in steps if step.target == "infrahub-register"] == [(demo.REF,)]

    # Each core is started once, where its runbook restarts it, and each runner once, after Prefect.
    for source, steps in demo.STEPS.items():
        kinds = [step.kind for step in steps]
        assert (kinds.count("core"), kinds.count("runner")) == (1, 1), source
        targets = [step.target or step.kind for step in steps]
        assert targets.index("orchestrator-env") < targets.index("core") < targets.index("prefect-up"), source
        assert targets.index("prefect-up") + 1 == targets.index("runner"), source

    # How many times each is asked: Infrahub's first `infrahub-up` three, its registration two, every other one.
    asked_again: dict[tuple[str, int], int] = {}
    for source, steps in demo.STEPS.items():
        asked_again |= {(source, index): step.asks for index, step in enumerate(steps) if step.asks != 1}
    assert asked_again == {("infrahub", 0): 3, ("infrahub", 4): 2}
    assert (demo.STEPS["infrahub"][0].target, demo.STEPS["infrahub"][4].target) == ("infrahub-up", "infrahub-register")


RUNS = {
    ("infrahub-up", ()): ("scripts/infrahub_dev.py up ",),
    ("orchestrator-env", ()): ("scripts/edge_dev.py env ", "infrahub/seed/account.py "),
    ("infrahub-register", ("REF=a-branch",)): ("infrahub/seed/register.py --ref a-branch ",),
    ("prefect-up", ()): ("scripts/edge_dev.py prefect-up ",),
    ("infrahub-seed", ("PROPOSED_CHANGE=1",)): ("infrahub/seed/seed.py ", " --proposed-change"),
    ("netbox-up", ()): ("scripts/netbox_dev.py up ",),
    ("netbox-seed", ()): ("netbox/seed/seed.py ", "netbox/seed/account.py "),
    ("orchestrator-env", ("SOURCE=netbox",)): ("scripts/edge_dev.py env ",),
    ("netbox-hook", ()): ("scripts/edge_dev.py api ", "netbox/seed/hook.py "),
    ("netbox-change", ("NETBOX_TAG=1",)): ("netbox/seed/change.py ", " --tag -- "),
}
"""What each make step's recipe runs, by the step's target and its variables as `make_argv` gives them for the branch
`a-branch`: the script or the seed, with the word its variable adds."""


def dry(words: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """`make -n` of the words the script would run a target by, with `MAIN` given as the tests': the recipe printed,
    and none of it run."""
    assert list(words[:2]) == ["make", "--no-print-directory"]
    argv = ["make", "-n", "-C", str(ROOT), *words[1:], f"MAIN={MAIN}"]
    return subprocess.run(argv, capture_output=True, text=True, check=False, timeout=60, env={"PATH": "/usr/bin:/bin"})


def test_every_step_names_a_target_the_makefile_has(tmp_path: Path) -> None:
    seen = set()
    for source, steps in demo.STEPS.items():
        for step in steps:
            if step.kind != "make":
                assert (step.target, step.variables, step.asks) == ("", (), 1), source
                continue
            words = demo.make_argv(step, tmp_path, "a-branch")
            assert words[:4] == ["make", "--no-print-directory", step.target, f"LOCAL={tmp_path}"]
            assert demo.make_words(step.target, tmp_path, *words[4:]) == words
            printed = dry(words)
            assert printed.returncode == 0, words
            for run in RUNS[step.target, tuple(words[4:])]:
                assert run in printed.stdout, (words, run)
            assert f"{tmp_path}" in printed.stdout, words
            seen.add((step.target, tuple(words[4:])))
    assert seen == set(RUNS)
    # With `SOURCE=netbox` nothing of Infrahub's is run, and the tag and the proposed change are by their variables.
    assert "infrahub" not in dry(demo.make_words("orchestrator-env", tmp_path, "SOURCE=netbox")).stdout
    assert "--tag" not in dry(demo.make_words("netbox-change", tmp_path)).stdout
    assert "--proposed-change" not in dry(demo.make_words("infrahub-seed", tmp_path)).stdout
    # A registration given no branch is refused by make itself, as the check refuses it before any step.
    assert dry(demo.make_argv(demo.Step("make", "infrahub-register", (demo.REF,)), tmp_path, "")).returncode == 2

    # The targets that stop a source, and the edge's Prefect: each there, and no volume removed without `PURGE=1`.
    for source, script in (("infrahub", "infrahub_dev"), ("netbox", "netbox_dev")):
        stopped = dry(demo.make_words(f"{source}-down", tmp_path))
        assert stopped.returncode == 0
        assert f"scripts/{script}.py down --local {tmp_path} " in stopped.stdout and "--purge" not in stopped.stdout
        assert dry(demo.make_words(f"{source}-down", tmp_path, "PURGE=1")).stdout.rstrip().endswith(" --purge")
    ended = dry(demo.make_words("prefect-down", tmp_path))
    assert f"scripts/edge_dev.py prefect-down --local {tmp_path} " in ended.stdout


def test_the_three_targets_run_the_script(tmp_path: Path) -> None:
    script = "python3 -I scripts/demo.py"
    where = f"--local {tmp_path} --main {MAIN}"
    for source in demo.SOURCES:
        assert make_n(tmp_path, f"{source}-demo", "REF=b") == [f"{script} up {source} {where} --ref 'b'"]
        # No branch checked out and none given: the script is told so, and says what Infrahub needs.
        assert make_n(tmp_path, f"{source}-demo", "REF=") == [f"{script} up {source} {where} --ref ''"]
    assert [line.rstrip() for line in make_n(tmp_path, "demo-down")] == [f"{script} down {where}"]
    assert make_n(tmp_path, "demo-down", "PURGE=1") == [f"{script} down {where} --purge"]
    assert [line.rstrip() for line in make_n(tmp_path, "demo-down", "PURGE=yes")] == [f"{script} down {where}"]

    # All three are phony: a file of a target's name stops none of them.
    makefile = (ROOT / "Makefile").read_text()
    phony = makefile.partition(".PHONY:")[2].partition("\n\n")[0].replace("\\\n", " ").split()
    assert {"infrahub-demo", "netbox-demo", "demo-down"} <= set(phony)

    # The venv is made where its server's command is missing, by `make venv`, before the script is run, and never
    # where it is there: the tests run from it, so here it is.
    assert demo.CORE.is_file()
    printed = "\n".join(make_n(tmp_path, "netbox-demo", "REF=b"))
    assert "pip" not in printed and "venv" not in printed
    absent = make_n(tmp_path, "netbox-demo", "REF=b", f"VENV={tmp_path / 'no-venv'}")
    assert absent[-1] == f"{script} up netbox {where} --ref 'b'"
    assert absent[0] == "make venv" and any("pip install" in line for line in absent[1:-1])
    assert make_n(tmp_path, "demo-down", f"VENV={tmp_path / 'no-venv'}") == make_n(tmp_path, "demo-down")
    # The rule that makes it is the server's command's own, the one the script starts.
    assert demo.CORE == ROOT / "core" / ".venv" / "bin" / "fylgja-core-server"
    assert "\n$(VENV)/bin/fylgja-core-server:\n\t$(MAKE) venv\n" in makefile
    assert "\ninfrahub-demo netbox-demo: | $(VENV)/bin/fylgja-core-server\n" in makefile


def test_a_run_takes_its_steps_in_order_and_starts_the_core_after_the_token_file_is_whole(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for source in demo.SOURCES:
        local, kept, host, targets = first(tmp_path / source)
        at_the_cores_start: list[str] = []
        at_the_runners_start: list[tuple[list[str], bool]] = []

        def seen(
            child: Started,
            kept: Any = kept,
            targets: Targets = targets,
            at_the_cores_start: list[str] = at_the_cores_start,
            at_the_runners_start: list[tuple[list[str], bool]] = at_the_runners_start,
        ) -> None:
            if child.argv == [CORE]:
                at_the_cores_start.extend(kept.tokens.read_text().splitlines())
            else:
                at_the_runners_start.append((targets.asked[-1], targets.prefect() is not None))
            targets.started(child)

        host.on_start = seen
        # Until the verdict is read, a run ends at the change opened, exit 1, saying what it leaves.
        assert status(host, up_of(local, source)) == 1
        steps = demo.STEPS[source]
        assert targets.asked == [
            [step.target, *("REF=main" if variable == demo.REF else variable for variable in step.variables)]
            for step in steps
            if step.kind == "make"
        ]
        [core, runner] = host.started
        served = targets.prefect()
        assert acts(host) == [
            [*UP[OTHER[source]]],
            *judged(source),
            *(image_read(image) for image in demo.IMAGES),
            *(
                act
                for step in steps
                for act in (
                    [HEARD, ("start", [CORE]), HEARD_BY_PID]
                    if step.kind == "core"
                    else [demo.api_argv(local, MAIN), ("start", demo.serve_argv(source, local, MAIN))]
                    if step.kind == "runner"
                    else [demo.make_argv(step, local, "main"), *(networks_read(host) if step is steps[0] else [])]
                )
            ),
        ]
        # The core is started once its token file is whole: the client's hash under `demo` and the runner's under
        # `orchestrator`, each once, which the core reads at its start alone.
        env = loaded_env(local, host)
        assert sorted(at_the_cores_start) == sorted(
            [
                f"{hashed(env['FYLGJA_API_TOKEN'])} demo",
                f"{hashed(env['FYLGJA_ORCHESTRATOR_API_TOKEN'])} orchestrator",
            ]
        )
        assert kept.tokens.read_text().splitlines() == at_the_cores_start
        assert (core.argv, core.cwd, core.log) == ([CORE], ROOT, kept.core_log)
        # The runner is started after `make prefect-up`, the server then up; and the change is opened once, last,
        # while the runner serves.
        assert at_the_runners_start == [(["prefect-up"], True)]
        assert targets.opened == [True]
        assert (runner.argv, runner.log) == (demo.serve_argv(source, local, MAIN), kept.runner_log)
        # What it records: the source, the two it started, and the Prefect server, which `make prefect-up` started
        # for it, none being recorded live before.
        assert kept.source.read_text() == f"{source}\n"
        assert (kept.core_pid.read_text(), kept.runner_pid.read_text()) == (f"{core.pid}\n", f"{runner.pid}\n")
        assert served is not None and kept.prefect_pid.read_text() == f"{served}\n"
        assert kept.unsettled.exists()
        assert (host.locked, host.signalled) == ([kept.lock], [])
        said = capsys.readouterr()
        expected = [
            "demo: the host's checks passed",
            f"demo: {local / '.env'}: added FYLGJA_API_ADDRESS, FYLGJA_API_TOKEN",
        ]
        asked = iter(targets.asked)
        for number, step in enumerate(steps, 1):
            if step.kind == "core":
                expected += [
                    f"demo: step {number} of {len(steps)}: the core",
                    f"demo: the core answers at {LISTEN}, pid {core.pid}, its log {kept.core_log}",
                ]
            elif step.kind == "runner":
                expected += [
                    f"demo: step {number} of {len(steps)}: the runner",
                    f"demo: the runner serves stage-plan/main and twin-rehearse/main, pid {runner.pid}, its log "
                    f"{kept.runner_log}",
                ]
            else:
                expected.append(f"demo: step {number} of {len(steps)}: make {' '.join(next(asked))}")
                if step.target == "orchestrator-env":
                    # The runner's line is the target's own; the client's is the script's.
                    expected.append(f"demo: {kept.tokens}: listed the principal demo by its token's hash")
        assert said.out.splitlines() == expected
        standing = (source, f"the core (pid {core.pid})", "the edge's Prefect", f"the runner (pid {runner.pid})")
        assert said.err.splitlines() == [f"demo: {OPENED}", f"demo: {left_up(*standing)}"]

        # Run again at once, over what the first left: the runner and the core are ended first, before the host is
        # judged, and started anew; the source and the Prefect server are up, and the server's record stays as the
        # first run wrote it, `make prefect-up` having started none.
        host.acts.clear()
        del targets.asked[:]
        assert status(host, up_of(local, source)) == 1
        again = acts(host)
        assert again[: again.index([*UP[OTHER[source]]])] == [
            (runner.pid, TERM),
            HEARD_BY_PID,
            LIST,
            HEARD_BY_PID,
            (core.pid, TERM),
        ]
        assert [step.target for step in steps if step.kind == "make"] == [words[0] for words in targets.asked]
        assert [started.pid for started in host.started[2:]] == [
            int(kept.core_pid.read_text()),
            int(kept.runner_pid.read_text()),
        ]
        assert len(host.started) == 4
        assert sorted(host.processes) == sorted([served, *(started.pid for started in host.started[2:])])
        assert (targets.prefect(), kept.prefect_pid.read_text()) == (served, f"{served}\n")
        assert kept.tokens.read_text().splitlines() == at_the_cores_start[:2]
        assert targets.opened == [True, True]
        out = capsys.readouterr().out.splitlines()
        assert out[:3] == [
            f"demo: the runner, pid {runner.pid}, ended",
            f"demo: the core, pid {core.pid}, ended",
            "demo: the host's checks passed",
        ]
        assert not [line for line in out if "added" in line or "listed" in line]


def made_before(steps: Sequence[Any], step: Any) -> int:
    """How many make steps `steps` holds before `step`: its place among the targets asked."""
    return [each.kind for each in steps[: list(steps).index(step)]].count("make")


def test_a_prefect_server_up_before_the_run_is_not_recorded_as_the_demonstrations(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`prefect.pid` is written only where `make prefect-up` started a server: one a person started by the same
    target before the run is recorded live in `local/prefect/server.pid`, and `make demo-down` is to leave it."""
    local, kept, host, targets = first(tmp_path)
    EDGE_DEV.append(local / ".env", [f"{EDGE_DEV.AUTH}=fylgja:the-tests-own-earlier-auth"])
    targets.by_hand("prefect-up")
    served = targets.prefect()
    assert served is not None
    assert status(host, up_of(local, "netbox", "")) == 1
    assert (targets.prefect(), kept.prefect_pid.exists()) == (served, False)
    [core, runner] = host.started
    standing = ["netbox", f"the core (pid {core.pid})", "the edge's Prefect", f"the runner (pid {runner.pid})"]
    assert capsys.readouterr().err.splitlines()[-1] == f"demo: {left_up(*standing)}"
    # `make demo-down` then leaves it, and ends the rest.
    assert status(host, down(local)) == 0
    assert (targets.prefect(), sorted(host.processes), "prefect-down" in targets.done) == (served, [served], False)
    capsys.readouterr()

    # A record of a server that is gone is no live one: the server the step starts is the demonstration's. And one
    # the step started is recorded though the step then failed, its wait run out, so that `make demo-down` ends it.
    for case, fails in enumerate((False, True)):
        local, kept, host, targets = first(tmp_path / str(case))
        EDGE_DEV.home_of(local).mkdir()
        EDGE_DEV.pid_file(local).write_text("4503\n")
        if fails:
            targets.fails["prefect-up"] = {1}
        assert status(host, up_of(local, "netbox", "")) == 1
        served = targets.prefect()
        assert served is not None and served != 4503
        assert kept.prefect_pid.read_text() == f"{served}\n"
        err = capsys.readouterr().err.splitlines()
        if fails:
            assert targets.asked[-1] == ["prefect-up"] and len(host.started) == 1
            standing = ["netbox", f"the core (pid {host.started[0].pid})", "the edge's Prefect"]
            assert err == [f"demo: step 5, make prefect-up, exited {MAKE_FAILED}", f"demo: {left_up(*standing)}"]
        # `make demo-down` ends the server with the rest.
        assert status(host, down(local)) == 0
        assert (targets.prefect(), sorted(host.processes), kept.prefect_pid.exists()) == (None, [], False)
        capsys.readouterr()

    # A step that fails having started none leaves no record: the port another's, as the target refuses it.
    local, kept, host, targets = first(tmp_path / "refused")

    def another_takes_the_port(child: Started) -> None:
        targets.started(child)
        host.listening.append((f"{BIND}:4200", 4600, "python3"))

    host.on_start = another_takes_the_port
    assert status(host, up_of(local, "netbox", "")) == 1
    assert (targets.asked[-1], targets.prefect(), kept.prefect_pid.exists()) == (["prefect-up"], None, False)
    standing = ["netbox", f"the core (pid {host.started[0].pid})"]
    assert capsys.readouterr().err.splitlines()[-1] == f"demo: {left_up(*standing)}"


def test_the_file_is_read_again_and_a_line_a_step_wrote_reaches_the_next(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for source in demo.SOURCES:
        local, kept, host, targets = first(tmp_path / source)
        assert "FYLGJA_ORCHESTRATOR_AUTH" not in loaded_env(local, host)
        assert status(host, up_of(local, source)) == 1
        env = loaded_env(local, host)
        auth = env["FYLGJA_ORCHESTRATOR_AUTH"]
        steps = demo.STEPS[source]
        wrote = [step.target or step.kind for step in steps].index("orchestrator-env")
        assert steps[wrote + 1].kind == "core"
        # The step after the one that wrote it is the core's start: its environment holds the line, and so does
        # every child's from there on, each make step's and the runner's; no step before was given it.
        [core, runner] = host.started
        makes = [ran for ran in host.ran if ran.argv[0] == "make"]
        before = made_before(steps, steps[wrote]) + 1
        held_by_the_core = same(core.env.get("FYLGJA_ORCHESTRATOR_AUTH"), auth)
        later = [runner.env, *(ran.env or {} for ran in makes[before:])]
        held_from_there_on = all(same(given.get("FYLGJA_ORCHESTRATOR_AUTH"), auth) for given in later)
        held_before = [ran.argv[2] for ran in makes[:before] if "FYLGJA_ORCHESTRATOR_AUTH" in (ran.env or {})]
        assert held_by_the_core and held_from_there_on
        assert held_before == []
        # Each make step is run under the file as it stood then, with the demonstration's address and token file:
        # the client's token, which `prepare` wrote before the first, is in every one.
        every_step_given_the_clients_token = all(
            same((ran.env or {}).get("FYLGJA_API_TOKEN"), env["FYLGJA_API_TOKEN"]) for ran in makes
        )
        assert every_step_given_the_clients_token
        assert {(ran.env or {}).get("FYLGJA_API_ADDRESS") for ran in makes} == {LISTEN}
        assert {(ran.env or {}).get("FYLGJA_TOKENS") for ran in makes} == {str(kept.tokens)}
        assert [ran.argv[2] for ran in makes if "FYLGJA_API_CA" in (ran.env or {})] == []
        # And in no command line: a child is given it by its environment alone.
        words = [word for ran in host.ran for word in ran.argv]
        words += [word for child in host.started for word in child.argv]
        on_a_command_line = any(auth in word or auth.partition(":")[2] in word for word in words)
        assert not on_a_command_line

    # A line a step wrote that the script does not read as a shell would stops the run at the next read, exit 2, by
    # its name and its line alone, saying what is left up.
    local, kept, host, targets = first(tmp_path / "unread")

    def writes_a_path_with_a_space(env: Mapping[str, str], variables: Sequence[str]) -> bool:
        EDGE_DEV.append(local / ".env", ["FYLGJA_ORCHESTRATOR_ROOT=/srv/an example/local/orchestrator"])
        return True

    targets.netbox_seed = writes_a_path_with_a_space  # type: ignore[method-assign]
    capsys.readouterr()
    assert status(host, up_of(local, "netbox", "")) == 2
    assert [words[0] for words in targets.asked] == ["netbox-up", "netbox-seed"]
    assert host.started == []
    number = len((local / ".env").read_text().splitlines())
    err = capsys.readouterr().err.splitlines()
    assert err[0].startswith(f"demo: {local / '.env'} line {number} gives FYLGJA_ORCHESTRATOR_ROOT a value this script")
    assert err[1:] == [f"demo: {left_up('netbox')}"]
    assert "an example" not in "".join(err)


def test_only_the_first_infrahub_up_and_the_registration_are_asked_again(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def run(case: str, source: str, fails: dict[str, set[int]]) -> tuple[int, list[str], FakeHost, Any]:
        local, _, host, targets = first(tmp_path / case)
        targets.fails = fails
        exited = status(host, up_of(local, source))
        return exited, [words[0] for words in targets.asked], host, capsys.readouterr()

    whole = [step.target for step in demo.STEPS["infrahub"] if step.kind == "make"]
    again = "demo: step {}, make {}, exited 2: asking it again, {} of {}"

    # The registration exits other than 0 once: it is asked again, which is said, and the run goes on.
    exited, asked, host, said = run("register-once", "infrahub", {"infrahub-register": {1}})
    assert asked == [*whole[:4], "infrahub-register", *whole[4:]]
    assert again.format(5, "infrahub-register", 2, 2) in said.out.splitlines()
    assert (exited, said.err.splitlines()[0], len(host.started)) == (1, f"demo: {OPENED}", 2)
    # The words it is asked by are the same each time, the branch among them.
    registrations = [ran.argv for ran in host.ran if ran.argv[2:3] == ["infrahub-register"]]
    assert len(registrations) == 2 and registrations[0] == registrations[1] and registrations[0][-1] == "REF=main"

    # Twice: the run stops, exit 1, naming the step, and no later step is run.
    exited, asked, host, said = run("register-twice", "infrahub", {"infrahub-register": {1, 2}})
    assert asked == [*whole[:4], "infrahub-register"]
    assert (exited, said.err.splitlines()[0]) == (1, "demo: step 5, make infrahub-register, exited 2")
    assert [line for line in said.out.splitlines() if "asking it again" in line] == [
        again.format(5, "infrahub-register", 2, 2)
    ]
    assert len(host.started) == 1

    # The first `infrahub-up` exits other than 0 twice and then passes: each further ask is said, and the run goes on.
    exited, asked, host, said = run("up-twice", "infrahub", {"infrahub-up": {1, 2}})
    assert asked == ["infrahub-up", "infrahub-up", *whole]
    assert [line for line in said.out.splitlines() if "asking it again" in line] == [
        again.format(1, "infrahub-up", 2, 3),
        again.format(1, "infrahub-up", 3, 3),
    ]
    assert (exited, said.err.splitlines()[0]) == (1, f"demo: {OPENED}")
    # The pool is read once the source is up, after the ask that passed and no other.
    reads = [index for index, act in enumerate(acts(host)) if act == ["docker", "network", "ls", "-q"]]
    assert len(reads) == 1 and acts(host)[reads[0] - 1][2] == "infrahub-up"

    # Three times: the run stops, exit 1, naming it, and nothing else is run or started.
    exited, asked, host, said = run("up-thrice", "infrahub", {"infrahub-up": {1, 2, 3}})
    assert asked == ["infrahub-up"] * 3
    assert said.err.splitlines() == ["demo: step 1, make infrahub-up, exited 2", f"demo: {left_up('infrahub')}"]
    assert (exited, host.started) == (1, [])
    assert ["docker", "network", "ls", "-q"] not in acts(host)

    # The second `infrahub-up`, and every other make step of either source, is asked once: one that exits other
    # than 0 stops the run there.
    for source, steps in demo.STEPS.items():
        for index, step in enumerate(steps):
            if step.kind != "make" or step.asks != 1:
                continue
            assert (source, step.target) not in (("infrahub", "infrahub-register"),)
            nth = [each.target for each in steps[: index + 1]].count(step.target)
            exited, asked, host, said = run(f"{source}-{index}", source, {step.target: {nth}})
            assert asked == [each.target for each in steps[: index + 1] if each.kind == "make"], (source, index)
            assert exited == 1
            assert said.err.splitlines()[0] == f"demo: step {index + 1}, make {step.target}, exited 2", (source, index)
            assert "asking it again" not in said.out, (source, index)
    assert [step.asks for step in demo.STEPS["infrahub"] if step.target == "infrahub-up"] == [3, 1]


def test_a_step_that_fails_stops_the_run_and_names_it(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    local, kept, host, targets = first(tmp_path)
    targets.fails = {"netbox-seed": {1}}
    assert status(host, up_of(local, "netbox", "")) == 1
    assert targets.asked == [["netbox-up"], ["netbox-seed"]]
    assert (host.started, host.signalled, host.asked) == ([], [], [])
    said = capsys.readouterr()
    assert said.out.splitlines()[-2:] == ["demo: step 1 of 8: make netbox-up", "demo: step 2 of 8: make netbox-seed"]
    assert said.err.splitlines() == [
        "demo: step 2, make netbox-seed, exited 2",
        "demo: left up: netbox; make demo-down ends what the demonstration started",
    ]
    # `make demo-down` then ends it: the source is recorded, and nothing else was started.
    assert kept.source.read_text() == "netbox\n"
    assert status(host, down(local)) == 0
    assert (acts(host)[-1], host.up) == (made(local, "netbox-down"), set())

    # A core that exits at its start, its token file listing one hash twice: the step is named, with its log, and
    # the runner is not started.
    local, kept, host, targets = first(tmp_path / "core")
    (local / "demo").mkdir()
    kept.tokens.write_text(f"{'0' * 64} someone\n{'0' * 64} someone-else\n")
    assert status(host, up_of(local, "netbox", "")) == 1
    assert [started.argv for started in host.started] == [[CORE]]
    assert targets.asked[-1] == ["orchestrator-env", "SOURCE=netbox"]
    assert capsys.readouterr().err.splitlines() == [
        f"demo: step 4, the core: the core exited before it answered: read {kept.core_log}",
        "demo: left up: netbox; make demo-down ends what the demonstration started",
    ]

    # A runner that exits before it serves, a name it needs never written: named as its step, the core left up.
    local, kept, host, targets = first(tmp_path / "runner")
    targets.netbox_seed = lambda env, variables: True  # type: ignore[method-assign]
    assert status(host, up_of(local, "netbox", "")) == 1
    assert targets.asked[-1] == ["prefect-up"]
    assert capsys.readouterr().err.splitlines() == [
        f"demo: step 6, the runner: the runner exited before it served: read {kept.runner_log}",
        "demo: " + left_up("netbox", f"the core (pid {host.started[0].pid})", "the edge's Prefect"),
    ]
    assert not kept.runner_pid.exists()

    # A later step that fails after the core has gone: its record still names the pid, which reads as no core, so
    # it is not said to be left up.
    local, kept, host, targets = first(tmp_path / "gone")
    targets.fails = {"netbox-hook": {1}}
    brings_prefect_up = targets.prefect_up

    def the_core_goes_first(env: Mapping[str, str], variables: Sequence[str]) -> bool:
        host.exit(host.started[0].pid)
        return brings_prefect_up(env, variables)

    targets.prefect_up = the_core_goes_first  # type: ignore[method-assign]
    assert status(host, up_of(local, "netbox", "")) == 1
    assert kept.core_pid.read_text() == f"{host.started[0].pid}\n" and host.started[0].pid not in host.processes
    assert capsys.readouterr().err.splitlines() == [
        "demo: step 7, make netbox-hook, exited 2",
        "demo: " + left_up("netbox", "the edge's Prefect", f"the runner (pid {host.started[1].pid})"),
    ]


def pool_networks() -> list[tuple[str, list[str]]]:
    """The brief's four: one wider than the default pool, one inside it, one of IPv6 alone, and one that is the
    pool."""
    return [("a", ["172.16.0.0/12"]), ("b", ["172.20.3.0/24"]), ("c", ["fd00::/64"]), ("d", ["172.20.0.0/16"])]


def test_a_network_that_holds_the_whole_pool_stops_the_run_with_the_source_left_up(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from fylgja_core.containerlab import pool

    local, _, host, targets = first(tmp_path)
    host.networks += pool_networks()
    assert status(host, up_of(local, "netbox", "")) == 2
    # After step 1 alone: the source is up, and it is left up, no `down` of it run.
    assert targets.asked == [["netbox-up"]]
    assert acts(host)[-3:] == [made(local, "netbox-up"), *networks_read(host)]
    assert (host.up, host.started) == ({"fylgja-core-netbox"}, [])
    holding = [
        ("a", IPv4Network("172.16.0.0/12")),
        ("b", IPv4Network("172.20.3.0/24")),
        ("d", IPv4Network("172.20.0.0/16")),
    ]
    said = capsys.readouterr()
    assert said.err.splitlines() == [
        f"demo: {pool.refusal(pool.DEFAULT_POOL, holding)}",
        "demo: netbox is left up: set FYLGJA_LAB_POOL in local/.env, then run make netbox-demo again",
    ]
    assert said.err.splitlines()[0] == (
        "demo: The pool 172.20.0.0/16 has no /24 that neither a Docker network nor another twin holds. Docker "
        "networks holding part of it: a (172.16.0.0/12), b (172.20.3.0/24), d (172.20.0.0/16). Set FYLGJA_LAB_POOL "
        "to an IPv4 network with a free /24, and start the core again."
    )
    # It stops because `a` and `d` leave no /24 free: `b` overlaps the pool and is named, and `c` holds none of it.
    assert pool.choose(pool.DEFAULT_POOL, [subnet for _, subnet in holding]) is None
    assert pool.choose(pool.DEFAULT_POOL, [holding[1][1]]) == IPv4Network("172.20.0.0/24")

    # With `b` alone a /24 of the pool is free: no stop, and nothing is said of the pool.
    local, _, host, targets = first(tmp_path / "part")
    host.networks += [("b", ["172.20.3.0/24"]), ("c", ["fd00::/64"])]
    assert status(host, up_of(local, "netbox", "")) == 1
    said = capsys.readouterr()
    assert len(targets.asked) == 6 and said.err.splitlines()[0] == f"demo: {OPENED}"
    assert not [line for line in (said.out + said.err).splitlines() if "FYLGJA_LAB_POOL" in line or "/24" in line]

    # With a pool of the host's own loaded, the four hold none of it: no stop.
    local, _, host, targets = first(tmp_path / "moved")
    host.networks += pool_networks()
    EDGE_DEV.append(local / ".env", ["FYLGJA_LAB_POOL=192.0.2.0/24"])
    assert status(host, up_of(local, "netbox", "")) == 1
    assert len(targets.asked) == 6 and capsys.readouterr().err.splitlines()[0] == f"demo: {OPENED}"
    # The core is given the same pool, by its environment.
    assert host.started[0].env["FYLGJA_LAB_POOL"] == "192.0.2.0/24"
    # And where that pool's one /24 is held, the stop names the pool as loaded.
    local, _, host, targets = first(tmp_path / "moved-and-held")
    host.networks.append(("e", ["192.0.2.128/25"]))
    EDGE_DEV.append(local / ".env", ["FYLGJA_LAB_POOL=192.0.2.0/24"])
    assert status(host, up_of(local, "infrahub")) == 2
    assert capsys.readouterr().err.splitlines() == [
        f"demo: {pool.refusal(IPv4Network('192.0.2.0/24'), [('e', IPv4Network('192.0.2.128/25'))])}",
        "demo: infrahub is left up: set FYLGJA_LAB_POOL in local/.env, then run make infrahub-demo again",
    ]
    assert targets.asked == [["infrahub-up"]]


def answer_of(networks: Sequence[tuple[str, Sequence[str]]]) -> str:
    """Docker's answer to `docker network inspect` in the driver's format for `networks`, a line each."""
    return "".join(f"{network_line(name, subnets)}\n" for name, subnets in networks)


POOLS = {
    "none": "",
    "docker's own": answer_of([("bridge", ["172.17.0.0/16"]), ("host", []), ("none", [])]),
    "the whole pool": answer_of([("d", ["172.20.0.0/16"])]),
    "a wider one": answer_of([("a", ["172.16.0.0/12"]), ("bridge", ["172.17.0.0/16"])]),
    "parts held, a /24 free": answer_of(
        [("b", ["172.20.3.0/24"]), ("first", ["172.20.0.0/24"]), ("half", ["172.20.128.0/17"])]
    ),
    "every /24 held by many": answer_of([(f"lab-{third}", [f"172.20.{third}.0/24"]) for third in range(255, -1, -1)]),
    "every /24 but one": answer_of([(f"lab-{third}", [f"172.20.{third}.0/24"]) for third in range(256) if third != 77]),
    "dual-stack": answer_of([("both", ["172.20.0.0/16", "fd00:1::/64"]), ("two", ["172.20.9.0/24", "172.21.0.0/16"])]),
    "IPv6 alone": answer_of([("six", ["fd00::/64"]), ("host", [])]),
    "names that are not plain": answer_of(
        [
            ('a b"c\u0085d', ["172.20.0.0/17"]),
            ("-dash, (first)", ["172.20.128.0/17"]),
            ("plain_1.x-y", ["172.20.4.0/24"]),
            ("ü", ["172.20.5.0/24"]),
        ]
    ),
    "sorted by name, then subnet": answer_of([("z", ["172.20.0.0/16"]), ("a", ["172.20.9.0/24", "172.20.1.0/24"])]),
    "a host bit set": '"loose" [{"Subnet":"172.20.0.1/16","Gateway":"172.20.0.1"}]\n',
    "a config with no subnet": (
        '"odd" [{"Gateway":"172.20.0.1"},{"Subnet":"","Gateway":""}]\n"d" [{"Subnet":"172.20.0.0/16"}]\n'
    ),
}
"""Docker's answers for sets of networks, as `docker network inspect` prints them in the driver's format, for the
script's reading of each to be held to the driver's."""


@pytest.mark.parametrize("case", list(POOLS))
@pytest.mark.parametrize("lab_pool", ["172.20.0.0/16", "172.20.0.0/24", "192.0.2.0/24", "172.16.0.0/14"])
def test_the_scripts_pool_check_is_the_drivers(case: str, lab_pool: str) -> None:
    from fylgja_core.containerlab import pool

    answered = POOLS[case]
    if case == "names that are not plain":
        # The name reaches the parse as Docker writes it, U+0085 unescaped: the line is still one line.
        assert "\u0085" in answered and len(answered.splitlines()) > len(answered.split("\n")) - 1
    the_pool = IPv4Network(lab_pool)
    found = demo.networks(answered)
    assert found == pool.networks(answered)
    assert demo.holders(the_pool, found) == pool.holders(the_pool, found)
    taken = [subnet for _, subnet in found]
    assert demo.chosen(the_pool, taken) == pool.choose(the_pool, taken)
    assert (demo.chosen(the_pool, taken) is None) == (pool.choose(the_pool, taken) is None)
    assert demo.refusal(the_pool, demo.holders(the_pool, found)) == pool.refusal(
        the_pool, pool.holders(the_pool, found)
    )
    # With no network holding any of it, the refusal names the setting alone, as the driver's.
    assert demo.refusal(the_pool, []) == pool.refusal(the_pool, [])
    # An answer that ends without a newline, and one with a blank line in it, read alike.
    assert demo.networks(answered.rstrip("\n")) == demo.networks(answered.replace("\n", "\n\n")) == found


def test_the_scripts_pool_check_decides_as_the_brief_says() -> None:
    """The rows' decisions themselves, so that the parity above is not of two readings that are both wrong."""
    default = IPv4Network("172.20.0.0/16")

    def stops(case: str) -> bool:
        found = demo.networks(POOLS[case])
        return demo.chosen(default, [subnet for _, subnet in found]) is None

    assert {case: stops(case) for case in POOLS} == {
        "none": False,
        "docker's own": False,
        "the whole pool": True,
        "a wider one": True,
        "parts held, a /24 free": False,
        "every /24 held by many": True,
        "every /24 but one": False,
        "dual-stack": True,
        "IPv6 alone": False,
        "names that are not plain": True,
        "sorted by name, then subnet": True,
        "a host bit set": True,
        "a config with no subnet": True,
    }
    found = demo.networks(POOLS["parts held, a /24 free"])
    assert demo.chosen(default, [subnet for _, subnet in found]) == IPv4Network("172.20.1.0/24")
    assert demo.networks(POOLS["dual-stack"]) == [
        ("both", IPv4Network("172.20.0.0/16")),
        ("two", IPv4Network("172.20.9.0/24")),
        ("two", IPv4Network("172.21.0.0/16")),
    ]
    assert demo.networks(POOLS["IPv6 alone"]) == []
    not_plain = demo.networks(POOLS["names that are not plain"])
    assert demo.refusal(default, demo.holders(default, not_plain)) == (
        "The pool 172.20.0.0/16 has no /24 that neither a Docker network nor another twin holds. Docker networks "
        'holding part of it: "-dash, (first)" (172.20.128.0/17), "a b\\"c\\u0085d" (172.20.0.0/17), plain_1.x-y '
        '(172.20.4.0/24), "\\u00fc" (172.20.5.0/24). Set FYLGJA_LAB_POOL to an IPv4 network with a free /24, and '
        "start the core again."
    )


def test_the_scripts_default_pool_and_format_are_the_drivers() -> None:
    from fylgja_core.containerlab import pool

    assert str(pool.DEFAULT_POOL) == demo.DEFAULT_POOL
    assert demo.FORMAT == pool.FORMAT
    assert demo.POOL == pool.VARIABLE
    assert demo.PLAIN.pattern == pool._PLAIN.pattern


@pytest.mark.parametrize(
    ("value", "network"),
    [
        (None, "172.20.0.0/16"),
        ("", "172.20.0.0/16"),
        ("192.0.2.0/24", "192.0.2.0/24"),
        ("172.16.0.0/12", "172.16.0.0/12"),
        ("10.0.0.0/25", None),
        ("10.0.0.1/16", None),
        ("fd00::/64", None),
        ("pool", None),
        ("10.0.0.1", None),
        (" ", None),
        ("192.0.2.0/24 ", None),
    ],
)
def test_the_scripts_reading_of_the_setting_is_the_servers(value: str | None, network: str | None) -> None:
    from fylgja_core import config
    from fylgja_core.containerlab import pool

    environ = {} if value is None else {"FYLGJA_LAB_POOL": value}
    try:
        the_servers = config.lab_pool(environ) or pool.DEFAULT_POOL
    except config.Misconfigured as refused:
        assert network is None
        with pytest.raises(ValueError) as raised:
            demo.pool_of(environ)
        # The same refusal, the variable named and no value: the server's own words after its name.
        assert refused.variable == demo.POOL
        assert str(raised.value) == str(refused).replace("FYLGJA_LAB_POOL: ", "FYLGJA_LAB_POOL ", 1)
    else:
        assert network is not None
        assert demo.pool_of(environ) == the_servers == IPv4Network(network)


def test_docker_is_asked_once_for_every_network_as_the_driver_asks() -> None:
    from fylgja_core.containerlab import driver, pool

    host = passing()
    host.networks += pool_networks()
    answered = demo.docker_networks(host)
    ids = [short_id(name) for name, _ in host.networks]
    assert len(ids) == 7
    assert [ran.argv for ran in host.ran] == [
        ["docker", "network", "ls", "-q"],
        ["docker", "network", "inspect", "--format", pool.FORMAT, *ids],
    ]
    assert [(ran.capture, ran.timeout, ran.env, ran.cwd) for ran in host.ran] == [
        (True, demo.DOCKER_TIMEOUT_S, None, None)
    ] * 2
    assert answered == answer_of(host.networks)
    assert demo.networks(answered) == pool.networks(answered)
    # The driver's own second question, word for word, and its bound.
    # The driver's own two questions: the ids, which it lists by a format of the id alone and the script by `-q`,
    # each a line an id; then the one inspect, word for word.
    asks = inspect.getsource(driver.ContainerlabDriver._docker_networks)
    assert '["docker", "network", "ls", "--format", "{{.ID}}"]' in asks
    assert '["docker", "network", "inspect", "--format", pool.FORMAT, *ids]' in asks

    # No id listed: no inspect, and no network.
    host = passing()
    host.networks = []
    assert demo.docker_networks(host) == ""
    assert [ran.argv for ran in host.ran] == [["docker", "network", "ls", "-q"]]
    assert demo.networks("") == []

    # Either exiting other than 0 stops the run, exit 1, naming the command and its status; so does a network gone
    # between the two, and an answer that is not in the form asked for.
    host = passing()
    host.answer("docker", "network", "ls", status=1)
    with pytest.raises(demo.Stop) as stop:
        demo.docker_networks(host)
    assert (stop.value.status, stop.value.lines) == (
        1,
        ("`docker network ls -q` exited 1: Docker's networks were not read",),
    )
    assert len(host.ran) == 1

    for status_, change in ((1, None), (demo.TIMED_OUT, None), (1, "gone")):  # the last: a network removed between
        host = passing()
        if change is None:
            host.answer("docker", "network", "inspect", status=status_)
        else:
            listed = host.network_ids

            def goes(ran: Ran, host: FakeHost = host, listed: Any = listed) -> Any:
                done = listed(ran)
                host.networks.pop()
                return done

            host.answers[("docker", "network", "ls", "-q")] = goes
        with pytest.raises(demo.Stop) as stop:
            demo.docker_networks(host)
        assert (stop.value.status, stop.value.lines) == (
            1,
            (f"`docker network inspect` exited {status_}: Docker's networks were not read",),
        )
        assert len(host.ran) == 2

    # An answer that is not in the form asked for is no traceback: the run stops, exit 1, saying so.
    for answered in ("bridge [\n", '"bridge" [{"Subnet":"not a network"}]\n', '"bridge" {"Subnet":"x"}\n', '"a"\n'):
        host = passing()
        host.answer("docker", "network", "inspect", out=answered)
        with pytest.raises(demo.Stop) as stop:
            demo.pool_checked("netbox", IPv4Network("172.20.0.0/16"), host)
        assert (stop.value.status, stop.value.lines) == (
            1,
            ("`docker network inspect` printed what is not read: Docker's networks were not read",),
        ), answered


def test_the_other_source_is_stopped_first_where_it_is_up(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    stopping = "demo: {} is up: stopping it, its volumes kept, since it starts the same deployments"
    for source in demo.SOURCES:
        other = OTHER[source]
        local, kept, host, targets = first(tmp_path / source)
        targets.by_hand(f"{other}-up")
        before = loaded_env(local, host)
        assert status(host, up_of(local, source)) == 1
        # Its `down` target is the first command run, after the one read that finds it up and before the host is
        # judged, with no `PURGE`: its volumes are kept. The checks then find it stopped.
        assert acts(host)[:3] == [[*UP[other]], made(local, f"{other}-down"), ["docker", "info"]]
        assert targets.asked[0] == [f"{other}-down"]
        assert [words for words in targets.asked if words[0].endswith("-down")] == [[f"{other}-down"]]
        assert not [word for ran in host.ran for word in ran.argv if word.startswith("PURGE")]
        assert host.up == {demo.PROJECTS[source]}
        stopped, read = host.ran[1], host.ran[0]
        assert (stopped.cwd, stopped.capture, stopped.timeout) == (ROOT, False, None)
        assert (read.capture, read.timeout) == (True, demo.DOCKER_TIMEOUT_S)
        given_a_steps_environment = same(stopped.env, demo.step_env(before, kept, LISTEN))
        assert given_a_steps_environment
        said = capsys.readouterr()
        assert said.out.splitlines()[:2] == [stopping.format(other), "demo: the host's checks passed"]
        # The other's network still stands, its volumes kept, and is read with the rest once this source is up.
        assert PROJECT_NETWORKS[other] in host.networks

        # None of it running: no such command, and nothing said of it.
        local, kept, host, targets = first(tmp_path / f"{source}-alone")
        assert status(host, up_of(local, source)) == 1
        assert acts(host)[:2] == [[*UP[other]], ["docker", "info"]]
        assert [words for words in targets.asked if words[0].endswith("-down")] == []
        assert "stopping" not in capsys.readouterr().out

    # Where `docker` is not on PATH, or its read exits other than 0, the stop is left out, and the checks say what
    # is wrong with Docker.
    local, kept, host, targets = first(tmp_path / "no-docker")
    targets.by_hand("infrahub-up")
    host.on_path -= {"docker"}
    assert status(host, up_of(local, "netbox", "")) == 2
    assert [ran.argv for ran in host.ran if ran.argv[0] in ("docker", "make")] == []
    assert capsys.readouterr().err.splitlines() == ["demo: docker is not on PATH"]

    local, kept, host, targets = first(tmp_path / "unread")
    targets.by_hand("infrahub-up")
    host.answer("docker", "ps", status=1)
    assert status(host, up_of(local, "netbox", "")) == 2
    assert [ran.argv for ran in host.ran if ran.argv[0] == "make"] == []
    assert capsys.readouterr().err.splitlines() == ["demo: `docker ps` exited 1: whether netbox is up was not read"]
    assert host.up == {"fylgja-core-infrahub"}


def test_a_stop_of_the_other_source_that_fails_ends_the_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    local, _, host, targets = first(tmp_path)
    targets.by_hand("infrahub-up")
    targets.fails = {"infrahub-down": {1}}
    assert status(host, up_of(local, "netbox", "")) == 1
    # Nothing else is run, read or started, and nothing is written: neither the checks nor a step.
    assert acts(host) == [[*UP["infrahub"]], made(local, "infrahub-down")]
    assert (host.started, host.signalled, host.asked) == ([], [], [])
    assert sorted(path.name for path in local.iterdir()) == [".env"]
    said = capsys.readouterr()
    assert said.out.splitlines() == [
        "demo: infrahub is up: stopping it, its volumes kept, since it starts the same deployments"
    ]
    assert said.err.splitlines() == [
        f"demo: make infrahub-down exited {MAKE_FAILED}: infrahub is still up, and nothing was started"
    ]


def test_up_settles_what_an_earlier_run_left_before_it_judges_the_host(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`up`'s order before its steps: the lock, the environment, the runners it may not end, what an earlier run
    left, the other source, the checks, what is generated, the record of the source, the images."""
    # A NetBox run's twin, left in the store of a core that is gone, its runner gone too, and NetBox still up: for
    # an Infrahub run a core is started for the twin and ended, then NetBox is stopped, then the host is judged.
    local, kept, host, targets = first(tmp_path)
    assert status(host, up_of(local, "netbox", "")) == 1
    [core, runner] = host.started
    host.exit(core.pid)
    host.exit(runner.pid)
    targets.twins = ["rh-left"]
    host.acts.clear()
    capsys.readouterr()
    recorded: list[tuple[str, str]] = []

    def judged_then(ran: Ran) -> Any:
        recorded.append(("the checks", kept.source.read_text()))
        return demo.Done(0, "")

    def read_then(ran: Ran) -> Any:
        recorded.append(("the images", kept.source.read_text()))
        return host.image_inspected(ran)

    host.answers[("docker", "info")] = judged_then
    host.answers[("docker", "image", "inspect")] = read_then
    assert status(host, up_of(local, "infrahub")) == 1
    settled = host.started[2]
    assert acts(host)[: acts(host).index(["docker", "info"])] == [
        HEARD,
        ("start", [CORE]),
        HEARD_BY_PID,
        LIST,
        HEARD_BY_PID,
        [CLI, "twin", "destroy", "rh-left"],
        HEARD_BY_PID,
        LIST,
        HEARD_BY_PID,
        (settled.pid, TERM),
        [*UP["netbox"]],
        made(local, "netbox-down"),
    ]
    assert targets.twins == []
    # The record names the source once the checks have passed, before an image is read or a step is run.
    assert recorded == [("the checks", "netbox\n"), ("the images", "infrahub\n"), ("the images", "infrahub\n")]
    assert capsys.readouterr().out.splitlines()[:8] == [
        f"demo: the runner recorded in {kept.runner_pid}, pid {runner.pid}, is gone: the file removed",
        f"demo: the core recorded in {kept.core_pid}, pid {core.pid}, is gone: the file removed",
        f"demo: starting a core at {LISTEN}, to end what the store of an earlier one holds",
        f"demo: the core answers at {LISTEN}, pid {settled.pid}, its log {kept.core_log}",
        "demo: destroying the twin rh-left, which an earlier run left",
        f"demo: the core, pid {settled.pid}, ended",
        "demo: netbox is up: stopping it, its volumes kept, since it starts the same deployments",
        "demo: the host's checks passed",
    ]

    # A runner the demonstration may not end is refused before anything is settled, stopped or judged.
    local, kept, host, targets = first(tmp_path / "refused")
    assert status(host, up_of(local, "netbox", "")) == 1
    host.acts.clear()
    capsys.readouterr()
    assert status(host, up_of(local, "infrahub")) == 2
    assert (host.acts, len(host.started)) == ([], 2)
    assert capsys.readouterr().err.splitlines() == [
        f"demo: the netbox demonstration's runner is up, pid {host.started[1].pid}: one Prefect serves one source's "
        "runner; run make demo-down first"
    ]
    assert kept.source.read_text() == "netbox\n"

    # A listen address that does not read: nothing is settled at it, which check 9 says, and the record of the
    # source stays the earlier run's.
    local, kept, host, targets = first(tmp_path / "listen")
    assert status(host, up_of(local, "netbox", "")) == 1
    EDGE_DEV.append(local / ".env", ["FYLGJA_LISTEN=0.0.0.0:7650"])
    host.acts.clear()
    capsys.readouterr()
    assert status(host, up_of(local, "netbox", "")) == 2
    assert (host.signalled, len(host.started), len(host.processes)) == ([], 2, 3)
    assert [act for act in acts(host) if act[:1] == ["make"] or act[:1] == [CLI]] == []
    assert capsys.readouterr().err.splitlines() == [f"demo: {LISTEN_REFUSED}"]
    assert (kept.core_pid.exists(), kept.runner_pid.exists()) == (True, True)

    # A second command at once is refused before the file is read: the lock is the first thing taken.
    local, kept, host, targets = first(tmp_path / "locked")
    host.free = False
    host.denied = {local / ".env"}
    assert status(host, up_of(local, "netbox", "")) == 2
    assert capsys.readouterr().err.splitlines() == [
        f"demo: another demonstration command holds {kept.lock}: one runs at a time"
    ]


def test_the_images_are_the_packages_the_seeded_twin_runs() -> None:
    import yaml

    def refs(held: Any) -> set[str]:
        """Every string under a key `ref`, however deep."""
        if isinstance(held, dict):
            return {ref for key, value in held.items() for ref in ({value} if key == "ref" else refs(value))}
        return {ref for each in held for ref in refs(each)} if isinstance(held, list) else set()

    found = set()
    for package in (ROOT / "psp" / "nokia_srlinux.yaml", ROOT / "probes" / "ping.yaml"):
        runtime = yaml.safe_load(package.read_text())["runtime"]["containerlab"]
        assert refs(runtime), package
        found |= refs(runtime)
    assert all(isinstance(ref, str) for ref in found)
    assert found == set(demo.IMAGES) and len(demo.IMAGES) == 2
    # The fake host's Docker holds the same two where a test does not say otherwise.
    assert passing().images == set(demo.IMAGES)


def test_an_image_absent_is_pulled_and_one_present_is_not(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    srlinux, alpine = demo.IMAGES
    # Both held: each is asked of Docker once, read and bounded, and nothing is pulled or said.
    host = passing()
    demo.pull(host)
    assert [ran.argv for ran in host.ran] == [image_read(srlinux), image_read(alpine)]
    assert [(ran.capture, ran.timeout, ran.env) for ran in host.ran] == [(True, demo.DOCKER_TIMEOUT_S, None)] * 2
    assert capsys.readouterr().out == ""

    # One absent: it alone is pulled, printing as it will, within its own bound, and then Docker holds it.
    host = passing()
    host.images = {alpine}
    demo.pull(host)
    assert [ran.argv for ran in host.ran] == [image_read(srlinux), ["docker", "pull", srlinux], image_read(alpine)]
    pulled = host.ran[1]
    assert (pulled.capture, pulled.timeout, pulled.env, demo.PULL_TIMEOUT_S) == (False, 1800, None, 1800)
    assert host.images == set(demo.IMAGES)
    assert capsys.readouterr().out.splitlines() == [f"demo: pulling {srlinux}, which Docker does not hold"]

    # Neither held: both pulled, in order.
    host = passing()
    host.images = set()
    demo.pull(host)
    assert [ran.argv[:2] for ran in host.ran] == [["docker", "image"], ["docker", "pull"]] * 2
    capsys.readouterr()

    # A pull that fails, or outlasts its bound, stops the run, exit 1, naming the command and its status; so does a
    # read of Docker that is neither a yes nor a no. The other image is not asked for.
    for status_ in (1, demo.TIMED_OUT):
        host = passing()
        host.images = set()
        host.answer("docker", "pull", status=status_)
        with pytest.raises(demo.Stop) as stop:
            demo.pull(host)
        assert (stop.value.status, stop.value.lines) == (
            1,
            (f"`docker pull {srlinux}` exited {status_}: the image the twin runs was not pulled",),
        )
        assert len(host.ran) == 2
    host = passing()
    host.answer("docker", "image", "inspect", status=demo.TIMED_OUT)
    with pytest.raises(demo.Stop) as stop:
        demo.pull(host)
    assert (stop.value.status, stop.value.lines) == (
        1,
        (f"`docker image inspect {srlinux}` exited 124: whether Docker holds the image was not read",),
    )
    assert len(host.ran) == 1
    capsys.readouterr()

    # In a run: after the checks and before the first step, and a pull that fails leaves nothing started.
    local, _, host, targets = first(tmp_path)
    host.images = {srlinux}
    assert status(host, up_of(local, "netbox", "")) == 1
    run = acts(host)
    assert run[run.index(image_read(srlinux)) :][:4] == [
        image_read(srlinux),
        image_read(alpine),
        ["docker", "pull", alpine],
        made(local, "netbox-up"),
    ]
    assert run.index(["ss", "-Hltn"]) < run.index(image_read(srlinux))
    capsys.readouterr()

    local, _, host, targets = first(tmp_path / "fails")
    host.images = set()
    host.answer("docker", "pull", status=1)
    assert status(host, up_of(local, "netbox", "")) == 1
    assert (targets.asked, host.started) == ([], [])
    assert capsys.readouterr().err.splitlines() == [
        f"demo: `docker pull {srlinux}` exited 1: the image the twin runs was not pulled",
        "demo: nothing the demonstration starts is left up",
    ]


def test_no_secret_is_printed_or_put_on_a_command_line_over_a_whole_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def searched(local: Path, host: FakeHost, *texts: str) -> tuple[bool, bool, bool]:
        """Whether a secret of the run's is in `texts`, the lines printed and the `Stop`s; in a word of a command
        run or started, or a log's path; or in a file under `local/demo/`. Searched here, outside an assert."""
        secrets = secrets_of(local, host)
        words = [word for ran in host.ran for word in ran.argv]
        words += [word for child in host.started for word in [*child.argv, str(child.log), str(child.cwd)]]
        words += [asked.url for asked in host.asked] + [str(path) for path in host.locked]
        kept = [path.read_text() for path in (local / "demo").rglob("*") if path.is_file()]
        return (
            any(secret in text for secret in secrets for text in texts),
            any(secret in word for secret in secrets for word in words),
            any(secret in text for secret in secrets for text in kept),
        )

    for source in demo.SOURCES:
        local, kept, host, targets = first(tmp_path / source)
        assert status(host, up_of(local, source)) == 1
        said = capsys.readouterr()
        assert len(secrets_of(local, host)) >= 12 and len(host.started) == 2 and len(host.asked) >= 3
        assert searched(local, host, said.out, said.err) == (False, False, False)
        # The children hold them, by their environment alone: the core the node login, as loaded; the runner's
        # child the auth and the runner's own tokens, of which `edge_dev.py` makes the runner's; each make step
        # what `local/.env` held when it was asked.
        env = loaded_env(local, host)
        [core, runner] = host.started
        the_core_holds_the_login = same([core.env.get(name) for name in demo.LOGIN], [NODE_USER, NODE_PASSWORD])
        the_runner_holds_the_auth = same(runner.env.get("FYLGJA_ORCHESTRATOR_AUTH"), env["FYLGJA_ORCHESTRATOR_AUTH"])
        the_runner_holds_its_token = same(
            runner.env.get("FYLGJA_ORCHESTRATOR_API_TOKEN"), env["FYLGJA_ORCHESTRATOR_API_TOKEN"]
        )
        assert the_core_holds_the_login and the_runner_holds_the_auth and the_runner_holds_its_token
        last = [ran for ran in host.ran if ran.argv[0] == "make"][-1]
        the_last_step_holds_the_file = same(last.env, demo.step_env(env, kept, LISTEN))
        assert the_last_step_holds_the_file
        # The auth goes to Prefect in the seam's own argument, and in no URL.
        the_auth_was_given_to_the_seam = all(
            same(asked.auth, env["FYLGJA_ORCHESTRATOR_AUTH"]) for asked in host.asked if "/deployments/" in asked.url
        )
        assert the_auth_was_given_to_the_seam

        # Run again over what it left, a twin among it, and then ended.
        targets.twins = ["rh-left"]
        assert status(host, up_of(local, source)) == 1
        assert status(host, down(local)) == 0
        assert status(host, down(local, "--purge")) == 0
        said = capsys.readouterr()
        assert searched(local, host, said.out, said.err) == (False, False, False)
        assert (sorted(host.processes), host.up, targets.twins) == ([], set(), [])

    # Every way `up` stops: a step that fails, one asked again, a pool with no /24, the other source's stop failing,
    # a pull failing, a listen address that does not read, a line a step wrote that is not read.
    def stopped(case: str, source: str, exits: int, arrange: Any) -> None:
        local, _, host, targets = first(tmp_path / case)
        arrange(local, host, targets)
        with pytest.raises(demo.Stop) as stop:
            demo.up(source, local, MAIN, "main", SHELL, host)
        said = capsys.readouterr()
        assert stop.value.status == exits, case
        assert searched(local, host, said.out, said.err, *stop.value.lines) == (False, False, False), case

    stopped("step", "netbox", 1, lambda local, host, targets: targets.fails.update({"netbox-change": {1}}))
    stopped(
        "asked-again", "infrahub", 1, lambda local, host, targets: targets.fails.update({"infrahub-up": {1, 2, 3}})
    )
    stopped("pool", "netbox", 2, lambda local, host, targets: host.networks.extend(pool_networks()))
    stopped(
        "other",
        "netbox",
        1,
        lambda local, host, targets: (targets.by_hand("infrahub-up"), targets.fails.update({"infrahub-down": {1}})),
    )
    stopped(
        "pull",
        "infrahub",
        1,
        lambda local, host, targets: (host.images.clear(), host.answer("docker", "pull", status=1)),
    )
    stopped(
        "listen",
        "netbox",
        2,
        lambda local, host, targets: EDGE_DEV.append(local / ".env", ["FYLGJA_LISTEN=0.0.0.0:7650"]),
    )
    stopped(
        "unread",
        "netbox",
        2,
        lambda local, host, targets: setattr(
            targets,
            "netbox_seed",
            lambda env, variables: EDGE_DEV.append(local / ".env", [f"FYLGJA_NETBOX_TOKEN=${NODE_PASSWORD}"]) is None,
        ),
    )


def test_the_real_host_reads_a_process_whatever_its_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`Real.process` on `/proc` files of the test's own: a path that holds a byte that is not UTF-8 is read as the
    script itself holds such a path, so a core recorded under one still reads as the demonstration's."""
    checkout = os.fsdecode(b"/srv/ex\xffample/fylgja-core")
    assert os.fsencode(checkout) == b"/srv/ex\xffample/fylgja-core"
    core = Path(checkout) / "core" / ".venv" / "bin" / "fylgja-core-server"
    kept = demo.records(Path(checkout) / "local")
    held = {
        "/proc/4502/cmdline": os.fsencode(f"{checkout}/core/.venv/bin/python3") + b"\0" + os.fsencode(core) + b"\0",
        "/proc/4502/environ": b"PATH=/usr/bin\0FYLGJA_STORE=" + os.fsencode(kept.store) + b"\0NOT_AN_ENTRY\0X=a=b\0",
    }

    def read_bytes(path: Path) -> bytes:
        if str(path) not in held:
            raise FileNotFoundError(2, "No such file or directory", str(path))
        return held[str(path)]

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    process = demo.Real().process(4502)
    assert process == demo.Process(
        [f"{checkout}/core/.venv/bin/python3", str(core)],
        {"PATH": "/usr/bin", "FYLGJA_STORE": str(kept.store), "X": "a=b"},
    )
    assert demo.is_core(process, kept)
    assert demo.Real().process(4503) is None


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["up"],
        ["up", *WHERE, "--ref", "main"],
        ["up", "nautobot", *WHERE, "--ref", "main"],
        ["up", "infrahub", "netbox", *WHERE, "--ref", "main"],
        ["up", "infrahub", *WHERE],
        ["up", "infrahub", "--local", str(LOCAL), "--ref", "main"],
        ["up", "infrahub", "--main", str(MAIN), "--ref", "main"],
        ["up", "netbox", *WHERE, "--ref", "", "--purge"],
        ["down"],
        ["down", "--local", str(LOCAL)],
        ["down", "--main", str(MAIN)],
        ["down", "netbox", *WHERE],
        ["down", *WHERE, "--ref", "main"],
        ["sideways", *WHERE],
    ],
)
def test_a_command_line_not_understood_is_exit_2(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    host = passing()
    assert status(host, argv) == 2
    said = capsys.readouterr()
    assert said.out == ""
    assert said.err != ""
    assert (host.locked, host.ran, host.started) == ([], [], [])


SEAM = (
    "run", "start", "process", "pids", "signal", "ask", "groups", "gid", "euid", "which", "text", "clock", "sleep",
    "secret", "lock",
)
"""The seam's calls (the plan's Global Constraints, "The seam")."""

THE_HOSTS = ("subprocess", "urllib", "time", "secrets", "fcntl", "grp")
"""The modules the script reaches a process, a socket, a clock, a secret, a lock or the host's groups by, which
`Real` alone names; `os.kill` and `os.killpg` with them."""


REALS_ALONE = ("http", "socket", "importlib")
"""Modules that reach a socket or another module, which nothing outside `Real` imports or names."""

OS_CALLS = ("kill", "killpg", "system", "popen", "fork", "forkpty")
OS_FAMILIES = ("exec", "spawn", "posix_spawn")
"""The calls of `os` that signal or make a process, by name and by the beginning of a name."""


def seam_rule(source: str) -> tuple[list[tuple[int, str]], set[str]]:
    """What `source` holds outside its class `Real` that only `Real` may, each with its line, and what `Real` names
    of the same.

    Outside `Real`: a name of `THE_HOSTS` or `REALS_ALONE`, or `__import__`; `os.kill`, `os.killpg`, `os.system`,
    `os.popen`, `os.fork` and every `os.exec*`, `os.spawn*` and `os.posix_spawn*`; an import of one of `REALS_ALONE`;
    an import of one of `THE_HOSTS` or of `os` that is not whole, plain and at the top (`from x import y`, `as`, or
    inside a function), so that none is reached by another name."""
    tree = ast.parse(source)
    [real] = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Real"]
    within = {id(node) for node in ast.walk(real)}

    def names(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name) and node.id in (*THE_HOSTS, *REALS_ALONE, "__import__"):
            return node.id
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "os":
            return f"os.{node.attr}" if node.attr in OS_CALLS or node.attr.startswith(OS_FAMILIES) else None
        return None

    outside: list[tuple[int, str]] = []
    inside: set[str] = set()
    for node in ast.walk(tree):
        named = names(node)
        if named is not None and id(node) in within:
            inside.add(named)
        elif named is not None:
            outside.append((getattr(node, "lineno", 0), named))
        elif isinstance(node, (ast.Import, ast.ImportFrom)) and id(node) not in within:
            taken = [node.module or ""] if isinstance(node, ast.ImportFrom) else [alias.name for alias in node.names]
            plain = isinstance(node, ast.Import) and node in tree.body and all(a.asname is None for a in node.names)
            for module in taken:
                root = module.split(".")[0]
                if root in REALS_ALONE or (root in (*THE_HOSTS, "os") and not plain):
                    outside.append((node.lineno, f"import {module}"))
    return outside, inside


def test_every_process_socket_file_and_clock_is_the_hosts() -> None:
    outside, inside = seam_rule(DEMO.read_text())
    assert outside == []
    # The rule is not empty: `Real` names every module of the constraint's, the one call of `os`, and `http`.
    assert inside == {*THE_HOSTS, "os.killpg", "http"}


RULED = "import os\nimport subprocess\nimport time\n\n\nclass Real:\n    def run(self):\n        {}\n\n\n{}\n"
"""A script of the rule's shape, with a statement in `Real` and one outside it."""


@pytest.mark.parametrize(
    ("statement", "named"),
    [
        ("subprocess.run(['true'])", "subprocess"),
        ("time.sleep(1)", "time"),
        ("os.kill(1, 15)", "os.kill"),
        ("os.killpg(1, 15)", "os.killpg"),
        ("os.system('true')", "os.system"),
        ("os.popen('true')", "os.popen"),
        ("os.fork()", "os.fork"),
        ("os.execve('/bin/true', ['true'], {})", "os.execve"),
        ("os.execvp('true', ['true'])", "os.execvp"),
        ("os.spawnv(os.P_WAIT, '/bin/true', ['true'])", "os.spawnv"),
        ("os.posix_spawn('/bin/true', ['true'], {})", "os.posix_spawn"),
        ("os.posix_spawnp('true', ['true'], {})", "os.posix_spawnp"),
        ("http.client.HTTPConnection('192.0.2.1')", "http"),
        ("socket.create_connection(('192.0.2.1', 80))", "socket"),
        ("importlib.import_module('subprocess')", "importlib"),
        ("__import__('subprocess').run(['true'])", "__import__"),
        ("import http.client", "import http.client"),
        ("import socket", "import socket"),
        ("import importlib", "import importlib"),
        ("from importlib import util", "import importlib"),
        ("from http import client", "import http"),
        ("import subprocess as other", "import subprocess"),
        ("from subprocess import run", "import subprocess"),
        ("from os import system", "import os"),
        ("import os as other", "import os"),
        ("def other():\n    import time", "import time"),
    ],
)
def test_the_seams_rule_refuses_each_way_past_the_host(statement: str, named: str) -> None:
    """The rule itself, on scripts of the test's own: each statement is refused outside `Real`, and passes in it."""
    outside, _ = seam_rule(RULED.format("pass", statement))
    assert named in [name for _, name in outside]
    indented = statement.replace("\n", "\n        ")
    assert seam_rule(RULED.format(indented, "pass"))[0] == []
    assert seam_rule(RULED.format("pass", "os.environ.get('PATH')\nos.getpid()"))[0] == []


def test_the_fake_host_is_called_as_the_real_one_is() -> None:
    def called(method: object) -> list[tuple[str, object, object]]:
        assert callable(method)
        return [(p.name, p.kind, p.default) for p in inspect.signature(method).parameters.values()]

    assert {name for name in vars(demo.Host) if not name.startswith("_")} == set(SEAM)
    for name in SEAM:
        assert called(getattr(demo.Real, name)) == called(getattr(demo.Host, name)), name
        assert called(getattr(FakeHost, name)) == called(getattr(demo.Host, name)), name


def test_a_file_or_a_lock_that_is_not_the_users_ends_the_run_and_names_its_path(
    capsys: pytest.CaptureFixture[str],
) -> None:
    host = passing()
    del host.files[ENV_FILE]
    host.denied = {ENV_FILE}
    assert status(host, up("netbox", ""), exported=True) == 2
    assert capsys.readouterr().err.splitlines() == [f"demo: {ENV_FILE} is not this user's to read"]
    assert host.ran == []

    class Unwritable(FakeHost):
        def lock(self, path: Path) -> bool:
            raise PermissionError(13, "Permission denied", str(path))

    assert status(Unwritable(), up("netbox", "")) == 1
    assert capsys.readouterr().err.splitlines() == [f"demo: up: [Errno 13] Permission denied: '{LOCK}'"]


ANOTHERS = 4300
"""A session of another user's, which `killpg` refuses this one."""


class Child:
    """A `Popen` stand-in: a child started, pid 4242, running until a test says it exited."""

    pid = 4242

    def __init__(self, argv: list[str], **kwargs: Any) -> None:
        self.argv = argv
        self.kwargs = kwargs
        self.appends_to = (kwargs["stdout"].name, kwargs["stdout"].mode)
        self.status: int | None = None

    def poll(self) -> int | None:
        return self.status


def test_the_real_host_runs_starts_and_signals_a_child_as_the_seam_says(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`Real`'s calls of `subprocess` and `os.killpg`, each replaced: what it would run is kept, and nothing runs."""
    ran: list[tuple[list[str], dict[str, Any]]] = []
    started: list[Child] = []
    sent: list[tuple[int, int]] = []

    def run(argv: list[str], **kwargs: Any) -> Any:
        ran.append((argv, kwargs))
        if kwargs["timeout"] == 1:
            raise demo.subprocess.TimeoutExpired(argv, 1)
        if argv[0] == "not-on-the-childs-path":
            raise FileNotFoundError(2, "No such file or directory", argv[0])
        if argv[0] == "under-a-file-on-the-path":
            raise NotADirectoryError(20, "Not a directory", argv[0])
        if argv[0] == "not-executable":
            raise PermissionError(13, "Permission denied", argv[0])
        if argv[0] == "no-format-the-kernel-runs":
            raise OSError(errno.ENOEXEC, "Exec format error", argv[0])
        if argv[0] == "too-long-a-list":
            raise OSError(errno.E2BIG, "Argument list too long", argv[0])
        return demo.subprocess.CompletedProcess(argv, 3, stdout=None if kwargs["stdout"] is None else "printed\n")

    def popen(argv: list[str], **kwargs: Any) -> Child:
        started.append(Child(argv, **kwargs))
        return started[-1]

    def killpg(pid: int, number: int) -> None:
        sent.append((pid, number))
        if pid == ANOTHERS:
            raise PermissionError(1, "Operation not permitted")
        if pid != Child.pid:
            raise ProcessLookupError(3, "No such process")

    monkeypatch.setattr(demo.subprocess, "run", run)
    monkeypatch.setattr(demo.subprocess, "Popen", popen)
    monkeypatch.setattr(demo.os, "killpg", killpg)
    real = demo.Real()

    # Captured: its stdout answered, and nothing of it printed. Its environment is the one given, whole.
    assert real.run(("a", "b"), env={"A": "1"}, cwd=tmp_path, capture=True, timeout=60) == demo.Done(3, "printed\n")
    argv, kwargs = ran[-1]
    assert (argv, kwargs["env"], kwargs["cwd"], kwargs["timeout"]) == (["a", "b"], {"A": "1"}, tmp_path, 60)
    assert (kwargs["stdout"], kwargs["stderr"]) == (demo.subprocess.PIPE, demo.subprocess.DEVNULL)
    assert kwargs["check"] is False
    # Not captured: it prints as it will, under this process's environment, with no bound.
    assert real.run(["a"]) == demo.Done(3, "")
    _, kwargs = ran[-1]
    assert (kwargs["env"], kwargs["cwd"], kwargs["stdout"], kwargs["stderr"], kwargs["timeout"]) == (None,) * 5
    assert real.run(["a"], timeout=1) == demo.Done(demo.TIMED_OUT, "")
    # A command the child's PATH does not hold, which may be another than this process's: a status, as a shell's.
    assert demo.NOT_FOUND == 127
    assert real.run(["not-on-the-childs-path", "info"], env={"PATH": "/srv/example/bin"}, capture=True) == demo.Done(
        127, ""
    )
    # A PATH one of whose elements is a file finds nothing either; a name found that may not be run is 126.
    assert real.run(["under-a-file-on-the-path"], env={"PATH": "/srv/example/file"}) == demo.Done(127, "")
    assert demo.NOT_RUN == 126
    assert real.run(["not-executable"], capture=True) == demo.Done(126, "")
    # So is one the kernel cannot run, a file with no format it knows and no `#!`, captured or not, as a shell
    # exits; and any other failure to start a captured read, so that no check ends in an exception's text.
    assert real.run(["no-format-the-kernel-runs"], capture=True) == demo.Done(126, "")
    assert real.run(["no-format-the-kernel-runs"]) == demo.Done(126, "")
    assert real.run(["too-long-a-list"], capture=True, timeout=60) == demo.Done(126, "")
    with pytest.raises(OSError) as not_started:
        real.run(["too-long-a-list"])
    assert not_started.value.errno == errno.E2BIG

    log = tmp_path / "core.log"
    log.write_bytes(b"an earlier start's\n")
    assert real.start(("c", "d"), env={"B": "2"}, cwd=tmp_path, log=log) == Child.pid
    [child] = started
    assert (child.argv, child.kwargs["env"], child.kwargs["cwd"]) == (["c", "d"], {"B": "2"}, tmp_path)
    assert (child.kwargs["stdin"], child.kwargs["stderr"]) == (demo.subprocess.DEVNULL, demo.subprocess.STDOUT)
    assert child.kwargs["start_new_session"] is True
    assert child.appends_to == (str(log), "ab")
    assert log.read_bytes() == b"an earlier start's\n"

    # A signal goes to the child's session; no such process is False, and a child that has exited is none.
    assert real.signal(Child.pid, 15) is True
    assert real.signal(Child.pid + 1, 15) is False
    assert sent == [(Child.pid, 15), (Child.pid + 1, 15)]
    child.status = 0
    assert real.signal(Child.pid, 15) is False
    assert real.process(Child.pid) is None
    assert len(sent) == 2

    # A session of another user's is not this one's to signal: False, and no exception.
    assert real.signal(ANOTHERS, 15) is False
    assert sent[2:] == [(ANOTHERS, 15)]
    # No pid at or under 1 is ever given to `killpg`: 0 is this process's own group, 1 init's, and -1 every process.
    assert [real.signal(pid, 15) for pid in (1, 0, -1, -Child.pid)] == [False, False, False, False]
    assert len(sent) == 3


def test_the_real_host_reads_processes_and_groups_from_the_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """`Real`'s reads of `/proc` and of the host's groups, on this process itself: nothing is started or signalled."""
    real = demo.Real()
    me = real.process(os.getpid())
    found = me is not None
    assert found
    initial = Path(f"/proc/{os.getpid()}/environ").read_bytes().split(b"\0")
    names = sorted(os.fsdecode(entry.partition(b"=")[0]) for entry in initial if b"=" in entry)
    argv_is_the_interpreters = same(me.argv, sys.orig_argv)
    names_are_its_environments = same(sorted(me.environ), names) and "PATH" in me.environ
    path_is_as_it_began = same(me.environ["PATH"], os.fsdecode(dict(e.partition(b"=")[::2] for e in initial)[b"PATH"]))
    assert argv_is_the_interpreters
    assert names_are_its_environments
    assert path_is_as_it_began

    # A pid no process has is none. Pid 0, init and a negative pid are each none with nothing of `/proc` read, so
    # that nothing is ever decided of them, whoever runs this.
    assert real.process(2**22 + 1) is None
    read: list[str] = []
    read_bytes = Path.read_bytes

    def recording(path: Path) -> bytes:
        read.append(str(path))
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", recording)
    assert [real.process(pid) for pid in (0, 1, -1)] == [None, None, None]
    assert read == []
    still_read = real.process(os.getpid()) is not None
    assert still_read
    assert read == [f"/proc/{os.getpid()}/cmdline", f"/proc/{os.getpid()}/environ"]
    monkeypatch.undo()

    pids = real.pids()
    assert os.getpid() in pids
    assert pids == sorted(pids) and pids[0] >= 1

    assert real.euid() == os.geteuid()
    # The effective group with the supplementary ones: under `sg` it is the one group held that the list lacks.
    assert real.groups() == {*os.getgroups(), os.getegid()}
    listed = grp.getgrall()[0]
    assert real.gid(listed.gr_name) == listed.gr_gid
    assert real.gid("fylgja-no-such-group") is None


def test_the_fake_host_answers_as_the_real_one_does() -> None:
    """Where `Real` answers by a rule of its own, the fake keeps the rule, so that no test passes on what the host
    would never answer."""
    host = FakeHost()
    host.answer("a", status=3, out="printed\n")
    host.answers[("b",)] = lambda ran: demo.Done(0, "printed by a function\n")
    # A child's output is answered only where it was captured.
    assert host.run(["a"], capture=True) == demo.Done(3, "printed\n")
    assert host.run(["a"]) == demo.Done(3, "")
    assert host.run(["b"], capture=True) == demo.Done(0, "printed by a function\n")
    assert host.run(["b"]) == demo.Done(0, "")

    # No pid at or under 1 is a process to read or to signal, whatever a test's `/proc` holds.
    seen: list[tuple[int, int]] = []
    host.on_signal = lambda pid, number: seen.append((pid, number))
    host.processes = {pid: demo.Process(["sleep", "600"], {}) for pid in (-1, 0, 1, 7)}
    assert [host.signal(pid, 15) for pid in (-1, 0, 1, 7, 8)] == [False, False, False, True, False]
    assert host.signalled == [(-1, 15), (0, 15), (1, 15), (7, 15), (8, 15)]
    assert seen == [(7, 15)]
    assert [host.process(pid) is None for pid in (-1, 0, 1, 7, 8)] == [True, True, True, False, True]
    # `/proc` lists no pid under 1, and a process with no command line, a zombie or a kernel thread, is none.
    host.processes[9] = demo.Process([], {"A": "1"})
    assert host.pids() == [1, 7, 9]
    assert host.process(9) is None

    # A child just started reads as `/proc` shows one: a `#!` script of the venv's by its interpreter and then its
    # words, as the core was read, and any other by its words alone, each under the environment it was given.
    host = passing()
    log = LOCAL / "demo" / "core.log"
    script = host.start([CORE], env={"A": "1"}, cwd=ROOT, log=log)
    binary = host.start(["python3", "-I", "scripts/edge_dev.py", "serve"], env={"B": "2"}, cwd=ROOT, log=log)
    assert host.process(script) == demo.Process([PYTHON, CORE], {"A": "1"})
    assert host.process(binary) == demo.Process(["python3", "-I", "scripts/edge_dev.py", "serve"], {"B": "2"})
    assert (script, binary) == (5000, 5001)
    assert FakeHost().interpreters == {}
    # What a test says the child does next is done once it is started, with what was started.
    seen_started: list[Any] = []
    host.on_start = seen_started.append
    third = host.start(["a"], env={}, cwd=ROOT, log=log)
    assert [(started.argv, started.pid) for started in seen_started] == [(["a"], third)]

    # What a test says happens at a time happens once, in the order of the times, when a sleep first brings the
    # clock there; and every run, start and signal is kept in one order.
    happened: list[str] = []
    host.at(2.0, lambda: happened.append("at 2"))
    host.at(1.5, lambda: happened.append("at 1.5"))
    host.at(5.0, lambda: happened.append("at 5"))
    host.sleep(1.0)
    assert happened == []
    host.sleep(1.0)
    assert happened == ["at 1.5", "at 2"]
    host.sleep(1.0)
    assert (happened, host.now) == (["at 1.5", "at 2"], 3.0)
    host.sleep(2.0)
    assert happened == ["at 1.5", "at 2", "at 5"]
    host.answer("a")
    host.run(["a", "b"])
    host.signal(script, 15)
    assert acts(host) == [
        ("start", [CORE]),
        ("start", ["python3", "-I", "scripts/edge_dev.py", "serve"]),
        ("start", ["a"]),
        ["a", "b"],
        (script, 15),
    ]

    # What Docker holds, as `docker` prints it: a project's running containers by their short ids, and none of one
    # that is stopped; the networks' ids, and the one line each network is inspected as, in the order of the ids,
    # an id no network has being exit 1; an image held by its id, and exit 1 with nothing printed for one that is
    # not, until it is pulled.
    host = passing()
    assert host.run([*NETBOX_UP], capture=True) == demo.Done(0, "")
    host.up = {"fylgja-core-netbox"}
    ids = host.run([*NETBOX_UP], capture=True).out.split()
    assert len(ids) == 2 and all(len(each) == 12 and int(each, 16) >= 0 for each in ids)
    assert host.run([*INFRAHUB_UP], capture=True) == demo.Done(0, "")
    assert host.run(["docker", "ps", "-q"], capture=True).out.split() == ids
    host.networks.append(("fylgja-core-netbox_default", ["198.51.100.0/24"]))
    host.networks.append(("both", ["172.20.0.0/16", "fd00::/64"]))
    listed = host.run(["docker", "network", "ls", "-q"], capture=True).out.split()
    assert len(listed) == len(set(listed)) == 5 and all(len(each) == 12 for each in listed)
    inspect_ = ["docker", "network", "inspect", "--format", "{{json .Name}} {{json .IPAM.Config}}"]
    assert host.run([*inspect_, *listed], capture=True) == demo.Done(
        0,
        '"bridge" [{"Subnet":"172.17.0.0/16","Gateway":"172.17.0.1"}]\n'
        '"host" null\n'
        '"none" null\n'
        '"fylgja-core-netbox_default" [{"Subnet":"198.51.100.0/24","Gateway":"198.51.100.1"}]\n'
        '"both" [{"Subnet":"172.20.0.0/16","Gateway":"172.20.0.1"},{"Subnet":"fd00::/64","Gateway":"fd00::1"}]\n',
    )
    assert host.run([*inspect_, listed[4], listed[1]], capture=True).out.splitlines() == [
        '"both" [{"Subnet":"172.20.0.0/16","Gateway":"172.20.0.1"},{"Subnet":"fd00::/64","Gateway":"fd00::1"}]',
        '"host" null',
    ]
    assert host.run([*inspect_, listed[0], "0123456789ab"], capture=True) == demo.Done(1, "")
    assert network_line('a "b"\u0085', []) == '"a \\"b\\"\u0085" null'
    held = host.run(["docker", "image", "inspect", "--format", "{{.Id}}", "alpine:3.24.2"], capture=True)
    assert held.status == 0 and held.out.startswith("sha256:") and len(held.out.strip()) == 71
    absent = ["docker", "image", "inspect", "--format", "{{.Id}}", "registry.example/absent:1"]
    assert host.run(absent, capture=True) == demo.Done(1, "")
    assert host.run(["docker", "pull", "registry.example/absent:1"]) == demo.Done(0, "")
    assert host.run(absent, capture=True).status == 0

    # Who listens, as `ss` prints it: the lines there are without a core; then a core at its own address while it
    # runs and is not said to be deaf, named with its pid under `-p` alone, and a test's own listeners, of which one
    # of another user's is named no pid.
    host = passing()
    assert host.run(HEARD, capture=True) == host.run(HEARD_BY_PID, capture=True) == demo.Done(0, SS)
    host.processes[4502] = core_process(demo.records(LOCAL), "127.0.0.1:7700")
    host.processes[4503] = demo.Process([PYTHON, CLI, "twin", "list"], {"FYLGJA_LISTEN": "127.0.0.1:7701"})
    host.listening += [("[::]:7702", 4600, "python3"), ("127.0.0.1:631", None, "cupsd")]
    assert host.run(HEARD, capture=True).out.splitlines()[len(SS.splitlines()) :] == [
        "LISTEN 0      2048       [::]:7702 [::]:*",
        "LISTEN 0      2048       127.0.0.1:631 0.0.0.0:*",
        "LISTEN 0      2048       127.0.0.1:7700 0.0.0.0:*",
    ]
    assert host.run(HEARD_BY_PID, capture=True).out.splitlines()[len(SS.splitlines()) :] == [
        'LISTEN 0      2048       [::]:7702 [::]:* users:(("python3",pid=4600,fd=4))',
        "LISTEN 0      2048       127.0.0.1:631 0.0.0.0:*",
        'LISTEN 0      2048       127.0.0.1:7700 0.0.0.0:* users:(("fylgja-core-ser",pid=4502,fd=4))',
    ]
    host.not_listening.add(4502)
    assert len(host.run(HEARD, capture=True).out.splitlines()) == len(SS.splitlines()) + 2
    # A core ended keeps its listener for the time a test states, named no process, and then it is gone; one that
    # did not listen keeps none, and with no time stated none is kept.
    host = passing()
    host.processes[4502] = core_process(demo.records(LOCAL), "127.0.0.1:7700")
    host.processes[4504] = core_process(demo.records(LOCAL), "127.0.0.1:7701")
    host.not_listening.add(4504)
    host.lingers = 0.15
    host.exit(4502)
    host.exit(4504)
    closing = "LISTEN 0      2048       127.0.0.1:7700 0.0.0.0:*"
    assert (host.process(4502), host.run(HEARD_BY_PID, capture=True).out.splitlines()[-1]) == (None, closing)
    host.sleep(0.1)
    assert host.run(HEARD, capture=True).out.splitlines()[-1] == closing
    host.sleep(0.1)
    assert host.run(HEARD, capture=True) == demo.Done(0, SS)
    host.lingers = 0.0
    host.processes[4502] = core_process(demo.records(LOCAL), "127.0.0.1:7700")
    host.exit(4502)
    assert host.run(HEARD, capture=True) == demo.Done(0, SS)


class Reply:
    """An answer of `urllib`'s opener: a status and a body."""

    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self.body = body

    def read(self) -> bytes:
        return self.body

    def __enter__(self) -> Reply:
        return self

    def __exit__(self, *_: object) -> None:
        return None


class Opener:
    """`urllib`'s opener replaced: it keeps each request, and answers or raises what the test gives next."""

    def __init__(self) -> None:
        self.next: Any = None
        self.asked: list[tuple[Any, float]] = []

    def open(self, request: Any, timeout: float) -> Any:
        self.asked.append((request, timeout))
        if isinstance(self.next, BaseException):
            raise self.next
        return self.next


def test_the_real_hosts_ask_sends_the_auth_in_a_header_and_raises_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """`Real.ask` over an opener of the test's: no socket is opened."""
    opener, built = Opener(), []

    def build_opener(*handlers: Any) -> Opener:
        built.append(handlers)
        return opener

    monkeypatch.setattr(demo.urllib.request, "build_opener", build_opener)
    real = demo.Real()
    [handlers] = built
    [proxy] = [handler for handler in handlers if isinstance(handler, demo.urllib.request.ProxyHandler)]
    [redirect] = [handler for handler in handlers if isinstance(handler, demo.urllib.request.HTTPRedirectHandler)]
    assert proxy.proxies == {}
    assert redirect.redirect_request(None, None, 307, "Temporary Redirect", None, "http://other.example/api") is None

    url = "http://192.0.2.1:4200/api/flow_runs/filter"
    opener.next = Reply(200, b'[{"id": "a"}]')
    answer = real.ask("POST", url, auth=AUTH, body={"limit": 1})
    assert answer == demo.Answer(200, [{"id": "a"}])
    request, timeout = opener.asked[-1]
    assert (request.get_method(), request.full_url, timeout) == ("POST", url, demo.REQUEST_TIMEOUT_S)
    assert (request.data, request.get_header("Content-type")) == (b'{"limit": 1}', "application/json")
    sent = request.get_header("Authorization")
    auth_is_basic = same(sent, "Basic " + base64.b64encode(AUTH.encode()).decode())
    auth_in_the_url = AUTH in request.full_url or AUTH.partition(":")[2] in request.full_url
    assert auth_is_basic
    assert not auth_in_the_url

    opener.next = Reply(200, b'{"version": "1"}')
    assert real.ask("GET", "http://127.0.0.1:7650/v1/version") == demo.Answer(200, {"version": "1"})
    request, _ = opener.asked[-1]
    assert (request.get_method(), request.data, request.get_header("Authorization")) == ("GET", None, None)

    # An answer that is no JSON has its status and no body; a refusal is an answer, its body read.
    for body in (b"", b"<html>"):
        opener.next = Reply(204, body)
        assert real.ask("GET", url) == demo.Answer(204, None)
    opener.next = demo.urllib.error.HTTPError(url, 401, "Unauthorized", Message(), io.BytesIO(b'{"detail": "no"}'))
    answer = real.ask("GET", url, auth=AUTH)
    assert answer == demo.Answer(401, {"detail": "no"})

    # Nothing answered: no exception, whatever was raised.
    for raised in (
        demo.urllib.error.URLError("refused"),
        ConnectionRefusedError(111, "Connection refused"),
        TimeoutError("timed out"),
        http.client.RemoteDisconnected("closed"),
        http.client.IncompleteRead(b"half"),
    ):
        opener.next = raised
        answer = real.ask("GET", url, auth=AUTH)
        assert answer == demo.Answer(None, None)
    asked = len(opener.asked)
    answer = real.ask("GET", "no url at all", auth=AUTH)
    assert answer == demo.Answer(None, None)
    assert len(opener.asked) == asked


def test_the_real_hosts_text_lock_and_secret(tmp_path: Path) -> None:
    """The calls of `Real` that touch nothing but a file of the test's own: no process, socket or sleep."""
    real = demo.Real()
    held = tmp_path / "held"
    held.write_text("a line\n")
    assert real.text(held) == "a line\n"
    assert real.text(tmp_path / "absent") is None
    assert real.text(held / "under-a-file") is None
    assert real.text(tmp_path) is None

    # A file's bytes reach the reader unchanged: a byte that is no UTF-8 is kept, as the surrogate that stands for
    # it, so that the reader sees what the file holds and a value that holds one is refused by its name
    # (`test_a_value_that_is_not_utf_8_is_refused_by_its_name_alone`). The decoding is UTF-8 whatever the locale;
    # what a locale that is not UTF-8 would then give a child is `encoded`'s to judge. The fake reads a file of a
    # test's own likewise.
    raw = tmp_path / "raw"
    raw.write_bytes(b"X=p\xffq\nY=\xc3\xa9\n")
    text = real.text(raw)
    assert text is not None
    assert text.encode("utf-8", "surrogateescape") == b"X=p\xffq\nY=\xc3\xa9\n"
    assert FakeHost(disk=tmp_path).text(raw) == text
    read = demo.read_env(text)
    assert (read["X"], read["Y"]) == ("p\udcffq", "\u00e9")
    assert demo.token_lines("", {"FYLGJA_API_TOKEN": read["Y"]}) == [
        f"{hashlib.sha256(b'\xc3\xa9').hexdigest()} demo"
    ]

    if os.geteuid() != 0:
        held.chmod(0)
        with pytest.raises(PermissionError):
            real.text(held)

    lock = tmp_path / "local" / "demo" / "lock"
    assert real.lock(lock) is True
    assert (mode(lock.parent), mode(lock)) == (0o700, 0o600)
    assert demo.Real().lock(lock) is False
    assert lock.read_bytes() == b""

    one, two = real.secret(), real.secret()
    long_and_made_anew = len(one) >= 32 and len(two) >= 32 and not same(one, two)
    assert long_and_made_anew
    assert real.which(str(tmp_path / "absent")) is None


def test_no_distribution_carries_the_script() -> None:
    """The script is development tooling, run from a checkout: no file that says what a distribution holds names it.
    The tree is walked, so that no process is started: a superset of what is tracked, less what is never tracked."""
    says_what_is_packed = ("pyproject.toml", "setup.py", "setup.cfg", "MANIFEST.in")
    found: list[Path] = []
    for directory, below, files in os.walk(ROOT):
        below[:] = [
            name
            for name in below
            if not name.startswith(".") and name not in ("local", "__pycache__") and not name.endswith(".egg-info")
        ]
        found += [Path(directory) / name for name in files if name in says_what_is_packed]
    listed = {path.relative_to(ROOT).as_posix() for path in found}
    assert {"core/pyproject.toml", "orchestrator/pyproject.toml", "readers/infrahub/pyproject.toml"} <= listed
    assert sorted(path.relative_to(ROOT).as_posix() for path in found if "demo.py" in path.read_text()) == []
