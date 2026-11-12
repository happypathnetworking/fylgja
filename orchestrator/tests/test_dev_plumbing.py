"""The development Prefect, its runner and what the task workers are given: `scripts/edge_dev.py`, loaded by its path
as `make` runs it, and `infrahub/dev/compose.override.yml` read as YAML. Nothing here starts a process or opens a
socket: the listeners are `ss` lines written here, and the tokens are the tests' own."""

from __future__ import annotations

import importlib.util
import json
import stat
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
EDGE_DEV = ROOT / "scripts" / "edge_dev.py"
OVERRIDE = ROOT / "infrahub" / "dev" / "compose.override.yml"
MAIN = Path("/srv/example/fylgja-core")
BIND = "192.0.2.1"

ORCHESTRATOR_API_TOKEN = "orchestrators-own-core-token"
ORCHESTRATOR_INFRAHUB_TOKEN = "orchestrators-own-infrahub-token"
DEVELOPER_API_TOKEN = "a-developers-core-token"
ADMIN_TOKEN = "the-admins-infrahub-token"
AUTH = "fylgja:the-tests-password"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("edge_dev_under_test", EDGE_DEV)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


edge_dev = _load()


def same(a: object, b: object) -> bool:
    """`a == b` as a bool, so that a failure shows no token (as `core/tests/test_config.py`'s `same()`)."""
    return a == b


def test_a_listener_on_4200_is_found_whatever_its_address() -> None:
    ss = "\n".join(
        [
            "LISTEN 0      4096       192.0.2.1:4200       0.0.0.0:*",
            "LISTEN 0      4096               *:4200             *:*",
            "LISTEN 0      4096            [::]:4200          [::]:*",
            "LISTEN 0      4096       127.0.0.1:14200      0.0.0.0:*",
            "LISTEN 0      4096       127.0.0.1:8000       0.0.0.0:*",
        ]
    )
    assert edge_dev.listeners(ss, 4200) == ["192.0.2.1:4200", "*:4200", "[::]:4200"]
    assert edge_dev.listeners("", 4200) == []


def test_the_refusal_names_the_port_and_stops_nothing() -> None:
    said = edge_dev.refusal("192.0.2.1", 4200)
    assert "4200" in said
    assert "192.0.2.1" in said
    assert "nothing was started" in said


def test_env_lines_add_only_what_is_absent() -> None:
    have = {"FYLGJA_ORCHESTRATOR_AUTH": AUTH}
    first = dict(edge_dev.env_lines(have, MAIN, "tag:fylgja"))
    assert list(first) == [
        "FYLGJA_ORCHESTRATOR_API_TOKEN",
        "FYLGJA_ORCHESTRATOR_SCOPE",
        "FYLGJA_ORCHESTRATOR_READER",
        "FYLGJA_ORCHESTRATOR_ROOT",
    ]
    assert first["FYLGJA_ORCHESTRATOR_SCOPE"] == "tag:fylgja"
    assert first["FYLGJA_ORCHESTRATOR_READER"] == str(MAIN / "infrahub" / "seed" / "reader.yaml")
    assert first["FYLGJA_ORCHESTRATOR_ROOT"] == str(MAIN / "local" / "orchestrator")

    one, two = (dict(edge_dev.env_lines({}, MAIN, "tag:fylgja")) for _ in range(2))
    tokens_differ = not same(one["FYLGJA_ORCHESTRATOR_API_TOKEN"], two["FYLGJA_ORCHESTRATOR_API_TOKEN"])
    auths_differ = not same(one["FYLGJA_ORCHESTRATOR_AUTH"], two["FYLGJA_ORCHESTRATOR_AUTH"])
    assert tokens_differ
    assert auths_differ
    user, _, password = one["FYLGJA_ORCHESTRATOR_AUTH"].partition(":")
    password_is_long_and_has_no_colon = len(password) >= 32 and ":" not in password
    assert user == "fylgja"
    assert password_is_long_and_has_no_colon

    every = {name: "held" for name in edge_dev.ENV_NAMES}
    assert edge_dev.env_lines(every, MAIN, "tag:fylgja") == []
    empty = every | {"FYLGJA_ORCHESTRATOR_AUTH": "", "FYLGJA_ORCHESTRATOR_SCOPE": ""}
    assert [name for name, _ in edge_dev.env_lines(empty, MAIN, "tag:fylgja")] == [
        "FYLGJA_ORCHESTRATOR_AUTH",
        "FYLGJA_ORCHESTRATOR_SCOPE",
    ]


def test_the_runner_is_given_its_own_tokens_and_none_of_composes() -> None:
    environ = {
        "PATH": "/usr/bin",
        "FYLGJA_API_ADDRESS": "127.0.0.1:7650",
        "FYLGJA_API_TOKEN": DEVELOPER_API_TOKEN,
        "FYLGJA_INFRAHUB_ADDRESS": "http://127.0.0.1:8000",
        "FYLGJA_INFRAHUB_TOKEN": ADMIN_TOKEN,
        "FYLGJA_INFRAHUB_WRITE_TOKEN": ADMIN_TOKEN,
        "FYLGJA_ORCHESTRATOR_API_TOKEN": ORCHESTRATOR_API_TOKEN,
        "FYLGJA_ORCHESTRATOR_INFRAHUB_TOKEN": ORCHESTRATOR_INFRAHUB_TOKEN,
        "FYLGJA_ORCHESTRATOR_AUTH": AUTH,
        "FYLGJA_ORCHESTRATOR_SCOPE": "tag:fylgja",
        "FYLGJA_ORCHESTRATOR_READER": "/srv/example/reader.yaml",
        "FYLGJA_ORCHESTRATOR_ROOT": "/srv/example/orchestrator",
        "FYLGJA_CREDENTIAL_SRLINUX_PASSWORD": "a-node-password",
        "INFRAHUB_INITIAL_ADMIN_TOKEN": ADMIN_TOKEN,
        "INFRAHUB_INITIAL_AGENT_TOKEN": "the-agents-token",
    }
    home = Path("/srv/example/local/prefect")
    given = edge_dev.runner_env(environ, BIND, home=home)

    core_token_is_the_orchestrators = same(given["FYLGJA_API_TOKEN"], ORCHESTRATOR_API_TOKEN)
    infrahub_token_is_the_orchestrators = same(given["FYLGJA_INFRAHUB_TOKEN"], ORCHESTRATOR_INFRAHUB_TOKEN)
    auth_is_the_servers = same(given["PREFECT_API_AUTH_STRING"], AUTH)
    assert core_token_is_the_orchestrators
    assert infrahub_token_is_the_orchestrators
    assert auth_is_the_servers
    assert given["PREFECT_API_URL"] == "http://192.0.2.1:4200/api"
    assert given["PREFECT_HOME"] == str(home)
    assert given["DO_NOT_TRACK"] == "1"
    assert given["PREFECT_SERVER_ANALYTICS_ENABLED"] == "false"
    assert [name for name in given if name.startswith("INFRAHUB_")] == []
    left_out = {
        "FYLGJA_INFRAHUB_WRITE_TOKEN",
        "FYLGJA_ORCHESTRATOR_API_TOKEN",
        "FYLGJA_ORCHESTRATOR_INFRAHUB_TOKEN",
        "FYLGJA_ORCHESTRATOR_AUTH",
        "FYLGJA_CREDENTIAL_SRLINUX_PASSWORD",
    }
    assert sorted(left_out & set(given)) == []
    values = list(given.values())
    holds_the_admins = any(same(value, ADMIN_TOKEN) for value in values)
    holds_the_developers = any(same(value, DEVELOPER_API_TOKEN) for value in values)
    assert not holds_the_admins
    assert not holds_the_developers
    assert {name: given[name] for name in ("FYLGJA_API_ADDRESS", "FYLGJA_INFRAHUB_ADDRESS")} == {
        "FYLGJA_API_ADDRESS": "127.0.0.1:7650",
        "FYLGJA_INFRAHUB_ADDRESS": "http://127.0.0.1:8000",
    }
    assert given["FYLGJA_ORCHESTRATOR_SCOPE"] == "tag:fylgja"

    for missing in ("FYLGJA_ORCHESTRATOR_API_TOKEN", "FYLGJA_ORCHESTRATOR_INFRAHUB_TOKEN", "FYLGJA_ORCHESTRATOR_AUTH"):
        short = {name: value for name, value in environ.items() if name != missing}
        with pytest.raises(edge_dev.Missing) as raised:
            edge_dev.runner_env(short, BIND, home=home)
        assert str(raised.value) == f"{missing} is not set: run make orchestrator-env and load local/.env"


def test_the_override_gives_the_workers_the_address_and_the_auth_alone() -> None:
    override: dict[str, Any] = yaml.safe_load(OVERRIDE.read_text())
    worker = override["services"]["task-worker"]
    fylgja = {name: value for name, value in worker["environment"].items() if name.startswith("FYLGJA_")}
    assert fylgja == {
        "FYLGJA_ORCHESTRATOR_ADDRESS": "host.docker.internal:4200",
        "FYLGJA_ORCHESTRATOR_AUTH": "${FYLGJA_ORCHESTRATOR_AUTH:-}",
    }
    assert worker["extra_hosts"] == ["host.docker.internal:host-gateway"]
    for name, service in override["services"].items():
        named = set(service.get("environment") or {})
        assert {"FYLGJA_API_TOKEN", "FYLGJA_INFRAHUB_TOKEN"} & named == set(), name


def test_the_scope_is_the_seeds_and_else_seed_pys(tmp_path: Path) -> None:
    main = tmp_path / "main"
    (main / "infrahub" / "seed").mkdir(parents=True)
    (main / "infrahub" / "seed" / "seed.py").write_text('"""A seed."""\n\nSCOPE = "tag:from-the-code"\nOTHER = 1\n')
    local = tmp_path / "local"
    assert edge_dev.scope_of(local, main) == "tag:from-the-code"
    (local / "infrahub").mkdir(parents=True)
    (local / "infrahub" / "seed.json").write_text(json.dumps({"branch": "b", "scope": "tag:seeded", "stages": []}))
    assert edge_dev.scope_of(local, main) == "tag:seeded"


def _env_file(local: Path, text: str) -> Path:
    local.mkdir(parents=True, exist_ok=True)
    env = local / ".env"
    env.write_text(text)
    env.chmod(0o600)
    return env


def test_env_appends_the_names_absent_and_a_second_run_prints_none(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main, local = tmp_path / "main", tmp_path / "main" / "local"
    tokens = tmp_path / "tokens"
    tokens.write_text("# the core's token file\n")
    tokens.chmod(0o640)
    held = "FYLGJA_INFRAHUB_ADDRESS=http://127.0.0.1:8000\nFYLGJA_ORCHESTRATOR_SCOPE=tag:mine"
    env = _env_file(local, held)
    (local / "infrahub").mkdir()
    (local / "infrahub" / "seed.json").write_text(json.dumps({"scope": "tag:fylgja"}))
    environ = {"FYLGJA_TOKENS": str(tokens)}

    assert edge_dev.main(["env", "--local", str(local), "--main", str(main)], environ=environ) == 0
    out = capsys.readouterr().out
    for name in ("FYLGJA_ORCHESTRATOR_AUTH", "FYLGJA_ORCHESTRATOR_API_TOKEN", "FYLGJA_ORCHESTRATOR_READER"):
        assert name in out
    assert "FYLGJA_ORCHESTRATOR_SCOPE" not in out
    assert "restart" in out
    written = env.read_text()
    kept_and_appended = written.startswith(held + "\n")
    assert kept_and_appended
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    values = dict(line.split("=", 1) for line in written.splitlines())
    assert values["FYLGJA_ORCHESTRATOR_SCOPE"] == "tag:mine"
    for value in (values["FYLGJA_ORCHESTRATOR_AUTH"], values["FYLGJA_ORCHESTRATOR_API_TOKEN"]):
        shown = value in out
        assert not shown
    hashed = edge_dev.hashed(values["FYLGJA_ORCHESTRATOR_API_TOKEN"])
    line_is_the_hash = same(tokens.read_text().splitlines()[-1], f"{hashed} orchestrator")
    assert line_is_the_hash
    assert stat.S_IMODE(tokens.stat().st_mode) == 0o640

    before = env.read_bytes()
    assert edge_dev.main(["env", "--local", str(local), "--main", str(main)], environ=environ) == 0
    again = capsys.readouterr().out
    assert [name for name in edge_dev.ENV_NAMES if name in again] == []
    assert env.read_bytes() == before
    assert len(tokens.read_text().splitlines()) == 2


def test_env_writes_the_env_file_before_it_lists_the_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    main, local = tmp_path / "main", tmp_path / "main" / "local"
    tokens = tmp_path / "tokens"
    tokens.write_text("# the core's token file\n")
    _env_file(local, "FYLGJA_INFRAHUB_ADDRESS=http://127.0.0.1:8000\n")
    (local / "infrahub").mkdir()
    (local / "infrahub" / "seed.json").write_text(json.dumps({"scope": "tag:fylgja"}))
    order: list[Path] = []
    real = edge_dev.append

    def recording(path: Path, lines: list[str]) -> None:
        order.append(path)
        real(path, lines)

    monkeypatch.setattr(edge_dev, "append", recording)
    environ = {"FYLGJA_TOKENS": str(tokens)}
    assert edge_dev.main(["env", "--local", str(local), "--main", str(main)], environ=environ) == 0
    assert order == [local / ".env", tokens]


@pytest.mark.parametrize(
    ("named", "says"),
    [
        (None, "FYLGJA_TOKENS is not set: set it in local/.env to the token file the core reads"),
        ("absent", "is no file: the core reads its token file and makes none"),
    ],
    ids=["unset", "no-file"],
)
def test_env_without_the_token_file_is_refused_with_nothing_written(
    tmp_path: Path, named: str | None, says: str, capsys: pytest.CaptureFixture[str]
) -> None:
    main, local = tmp_path / "main", tmp_path / "main" / "local"
    (main / "infrahub" / "seed").mkdir(parents=True)
    (main / "infrahub" / "seed" / "seed.py").write_text('SCOPE = "tag:fylgja"\n')
    env = _env_file(local, "FYLGJA_INFRAHUB_ADDRESS=http://127.0.0.1:8000\n")
    environ = {} if named is None else {"FYLGJA_TOKENS": str(tmp_path / named)}
    assert edge_dev.main(["env", "--local", str(local), "--main", str(main)], environ=environ) == 2
    assert says in capsys.readouterr().err
    assert env.read_text() == "FYLGJA_INFRAHUB_ADDRESS=http://127.0.0.1:8000\n"
    assert sorted(path.name for path in tmp_path.iterdir()) == ["main"]


HOME = Path("/srv/example/local/prefect")
SERVER = ["/srv/example/core/.venv/bin/python", "/srv/example/core/.venv/bin/prefect", "server", "start"]


def ours(argv: list[str] = SERVER, home: Path = HOME) -> Any:
    return edge_dev.Process(argv, {"PREFECT_HOME": str(home)})


def _pid_file(tmp_path: Path, pid: int) -> Path:
    local = tmp_path / "local"
    (local / "prefect").mkdir(parents=True, exist_ok=True)
    (local / "prefect" / "server.pid").write_text(f"{pid}\n")
    return local


def test_prefect_down_ends_only_this_projects_prefect_server(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ended: list[int] = []
    for process in (
        edge_dev.Process(["/usr/bin/python3", "/usr/bin/sleep", "600"], {}),
        ours(home=Path("/srv/another/prefect")),
        None,
    ):
        local = _pid_file(tmp_path, 4242)
        assert edge_dev.down(local, read=lambda pid, p=process: p if pid == 4242 else None, end=ended.append) == 0
        assert ended == []
        assert not (local / "prefect" / "server.pid").exists()
        assert "not this project's Prefect server" in capsys.readouterr().out

    local = _pid_file(tmp_path, 4243)
    home = local / "prefect"
    assert edge_dev.down(local, read=lambda pid: ours(home=home) if pid == 4243 else None, end=ended.append) == 0
    assert ended == [4243]
    assert not (local / "prefect" / "server.pid").exists()


def test_end_session_terms_and_kills_only_where_it_stays() -> None:
    sent: list[tuple[int, int]] = []
    clock = [0.0]

    def sleep(seconds: float) -> None:
        clock[0] += seconds

    edge_dev.end_session(
        4243, killpg=lambda pid, sig: sent.append((pid, sig)), alive=lambda pid: clock[0] < 2,
        clock=lambda: clock[0], sleep=sleep,
    )
    assert sent == [(4243, edge_dev.signal.SIGTERM)]

    sent.clear()
    clock[0] = 0.0
    edge_dev.end_session(
        4243, killpg=lambda pid, sig: sent.append((pid, sig)), alive=lambda pid: True,
        clock=lambda: clock[0], sleep=sleep,
    )
    assert sent == [(4243, edge_dev.signal.SIGTERM), (4243, edge_dev.signal.SIGKILL)]
    assert clock[0] >= edge_dev.DOWN_WAIT_S


class Started:
    """A `Popen` stand-in: the server started, its pid 777, running."""

    pid = 777
    returncode = None

    def __init__(self, argv: list[str], **kwargs: Any) -> None:
        self.argv = argv
        self.kwargs = kwargs

    def poll(self) -> int | None:
        return None


def ss(*addresses: str) -> Any:
    def run(argv: list[str], **kwargs: Any) -> Any:
        assert argv == ["ss", "-Hltn"]
        lines = "".join(f"LISTEN 0      4096       {address}       0.0.0.0:*\n" for address in addresses)
        return edge_dev.subprocess.CompletedProcess(argv, 0, stdout=lines)

    return run


def never(*args: Any, **kwargs: Any) -> Any:
    raise AssertionError("not to be called")


UP_ENV = {"FYLGJA_ORCHESTRATOR_AUTH": AUTH, "PREFECT_BIND": BIND, "PATH": "/usr/bin"}


def test_prefect_up_says_up_where_its_own_server_runs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    local = _pid_file(tmp_path, 4243)
    home = local / "prefect"
    read = lambda pid: ours(home=home) if pid == 4243 else None  # noqa: E731
    assert edge_dev.up(local, UP_ENV, run=never, popen=never, read=read, healthy=never) == 0
    assert "up already, pid 4243" in capsys.readouterr().out


def test_prefect_up_refuses_a_listener_it_did_not_start_and_starts_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    local = _pid_file(tmp_path, 4243)
    other = lambda pid: ours(home=Path("/srv/another/prefect"))  # noqa: E731
    assert edge_dev.up(local, UP_ENV, run=ss("127.0.0.1:4200"), popen=never, read=other, healthy=never) == 1
    assert edge_dev.refusal("127.0.0.1", 4200) in capsys.readouterr().err
    assert (local / "prefect" / "server.pid").read_text() == "4243\n"


def test_prefect_up_over_a_stale_pid_starts_its_server_with_the_auth_in_its_environment(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    local = _pid_file(tmp_path, 4243)
    started: list[Started] = []

    def popen(argv: list[str], **kwargs: Any) -> Started:
        started.append(Started(argv, **kwargs))
        return started[-1]

    read = lambda pid: edge_dev.Process(["/usr/bin/sleep", "600"], {})  # noqa: E731
    assert edge_dev.up(local, UP_ENV, run=ss(), popen=popen, read=read, healthy=lambda address: True) == 0
    [server] = started
    assert server.argv == [str(edge_dev.PREFECT), "server", "start", "--host", BIND, "--port", "4200", "--no-ui"]
    environment = server.kwargs["env"]
    auth_given = same(environment["PREFECT_SERVER_API_AUTH_STRING"], AUTH)
    auth_in_argv = any(same(part, AUTH) for part in server.argv)
    assert auth_given
    assert not auth_in_argv
    assert environment["PREFECT_HOME"] == str(local / "prefect")
    assert sorted(environment) == [
        "DO_NOT_TRACK", "PATH", "PREFECT_HOME", "PREFECT_SERVER_ANALYTICS_ENABLED", "PREFECT_SERVER_API_AUTH_STRING",
    ]
    assert server.kwargs["start_new_session"] is True
    assert (local / "prefect" / "server.pid").read_text() == "777\n"
    assert "answers at 192.0.2.1:4200, pid 777" in capsys.readouterr().out
