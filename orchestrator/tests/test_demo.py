"""`scripts/demo.py`, the demonstration script: the environment it reads, what it writes under `local/`, and the
host's checks. The script is loaded by its path, as `make` runs it, and given `demo_host.FakeHost` for its host:
nothing here starts a process, opens a socket, reads a file of the host's or sleeps. What is written is written under
`tmp_path`, and every secret is the tests' own, compared outside an assert."""

from __future__ import annotations

import ast
import base64
import hashlib
import importlib.util
import inspect
import io
import os
import stat
import sys
from email.message import Message
from ipaddress import IPv4Network
from pathlib import Path
from types import ModuleType
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
    FakeHost,
    demo,
    meminfo,
    passing,
    same,
    ss,
)

WHERE = ["--local", str(LOCAL), "--main", str(MAIN)]
SHELL = {"PATH": "/usr/bin", "HOME": "/srv/example/home"}
"""The shell's environment, which `local/.env` is laid over."""

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


def by_path(name: str) -> ModuleType:
    """Another development script, loaded by its path as `make` runs it, to hold this one's values to."""
    spec = importlib.util.spec_from_file_location(f"{name}_beside_demo", ROOT / "scripts" / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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
        ("X='p \"q\" $r `s` \\t ~ ;'", 'p "q" $r `s` \\t ~ ;'),
        ('X="p; q | r ~"', "p; q | r ~"),
    ],
)
def test_a_value_is_read_as_a_shell_reads_it(line: str, value: str) -> None:
    assert demo.read_env(f"{line}\n") == {"X": value}


def test_a_line_that_assigns_nothing_holds_nothing() -> None:
    assert demo.read_env("") == {}
    assert demo.read_env("\n# X=1\n  # X=2\nset -a\nX =3\nexport X\n1X=4\n. local/other\n") == {}
    assert demo.read_env("X=1\nX=\n") == {"X": ""}
    assert demo.read_env("X=\nX=1") == {"X": "1"}


def test_a_name_held_with_no_value_is_not_held() -> None:
    read = demo.read_env((ROOT / ".env.example").read_text())
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
    "'p' 'q'",
]
"""More than one word or pair of quotes, a quote left open, a tilde, and what ends a command."""


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
            "~ ; & | < > ( ); write it in single quotes"
        ], value
        assert host.ran == [] and host.started == []


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


def hashed(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


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
        tokens=home / "tokens",
        lock=home / "lock",
        rehearsal=home / "rehearsal.json",
    )


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


def test_a_host_that_meets_every_precondition_passes(capsys: pytest.CaptureFixture[str]) -> None:
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

    for source, ref in (("infrahub", "main"), ("netbox", "")):
        host = passing()
        assert status(host, up(source, ref)) == 0
        said = capsys.readouterr()
        assert (said.out.splitlines(), said.err) == (["demo: the host's checks passed"], "")
        assert host.locked == [LOCK]
        assert (host.started, host.signalled, host.asked) == ([], [], [])
        the_file_was_laid_over_the_shell = same(host.ran[0].env, SHELL | ENV)
        assert the_file_was_laid_over_the_shell
        # The children hold the secrets, by their environment alone: no line printed and no command line does.
        shown = any(secret in said.out + said.err for secret in SECRETS)
        on_a_command_line = any(secret in word for ran in host.ran for word in ran.argv for secret in SECRETS)
        assert not shown
        assert not on_a_command_line


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


def test_a_daemon_that_does_not_answer_and_a_missing_compose_are_each_said() -> None:
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


def test_the_apparmor_lines_are_asked_only_where_the_profile_is(capsys: pytest.CaptureFixture[str]) -> None:
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
    assert status(host, up("netbox", "")) == 0
    said = capsys.readouterr()
    assert (said.out.splitlines(), said.err) == ([f"demo: {notice}", "demo: the host's checks passed"], "")

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


def test_down_takes_the_lock_and_ends_nothing_yet(capsys: pytest.CaptureFixture[str]) -> None:
    """What `down` ends is not built: until it is, it says so and is never exit 0, which would say all is ended."""
    host = passing()
    assert status(host, ["down", *WHERE, "--purge"]) == 1
    said = capsys.readouterr()
    assert (said.out, said.err.splitlines()) == ("", ["demo: down: not built yet, and nothing was ended"])
    assert host.locked == [LOCK]
    assert (host.ran, host.started, host.signalled, host.asked) == ([], [], [], [])


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


def test_every_process_socket_file_and_clock_is_the_hosts() -> None:
    tree = ast.parse(DEMO.read_text(), str(DEMO))
    [real] = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Real"]
    within = {id(node) for node in ast.walk(real)}

    def names(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name) and node.id in THE_HOSTS:
            return node.id
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "os":
            return f"os.{node.attr}" if node.attr in ("kill", "killpg") else None
        return None

    outside: list[tuple[int, str]] = []
    inside: set[str] = set()
    for node in ast.walk(tree):
        named = names(node)
        if named is None:
            continue
        if id(node) in within:
            inside.add(named)
        else:
            outside.append((getattr(node, "lineno", 0), named))
    assert outside == []
    # The rule is not empty: `Real` names every one of them.
    assert inside == {*THE_HOSTS, "os.killpg"}

    # And none is reached by another name: each is imported whole and plainly, at the top, and `os` likewise.
    plain = {alias.name.split(".")[0] for node in tree.body if isinstance(node, ast.Import) for alias in node.names}
    assert {*THE_HOSTS, "os"} <= plain
    renamed = [
        (node.lineno, alias.name)
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.asname is not None and alias.name.split(".")[0] in (*THE_HOSTS, "os")
    ]
    taken_from = [
        (node.lineno, node.module)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in (*THE_HOSTS, "os")
    ]
    assert (renamed, taken_from) == ([], [])
    nested = [node.lineno for node in ast.walk(tree) if isinstance(node, ast.Import) and node not in tree.body]
    assert nested == []


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
        return demo.subprocess.CompletedProcess(argv, 3, stdout=None if kwargs["stdout"] is None else "printed\n")

    def popen(argv: list[str], **kwargs: Any) -> Child:
        started.append(Child(argv, **kwargs))
        return started[-1]

    def killpg(pid: int, number: int) -> None:
        sent.append((pid, number))
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
        demo.http.client.RemoteDisconnected("closed"),
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
