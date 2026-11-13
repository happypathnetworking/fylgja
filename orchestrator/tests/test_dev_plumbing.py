"""The development Prefect, its runner and what the task workers are given: `scripts/edge_dev.py`, loaded by its path
as `make` runs it, the targets that run it as `make -n` prints them, and `infrahub/dev/compose.override.yml` read as
YAML. Nothing here opens a socket or starts a process but `make -n`, which prints a recipe and runs none of it: the
listeners are `ss` lines written here, `os.execve` is replaced, and the tokens are the tests' own."""

from __future__ import annotations

import ast
import importlib.util
import json
import stat
import subprocess
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
        "FYLGJA_ORCHESTRATOR_NETBOX_READER",
        "FYLGJA_ORCHESTRATOR_NETBOX_SCOPE",
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


ORCHESTRATOR_NETBOX_TOKEN = "orchestrators-own-netbox-token"
NETBOX_READERS_TOKEN = "the-netbox-readers-token"
NETBOX_WRITE_TOKEN = "the-netbox-superusers-token"
NETBOX_PASSWORD = "the-netbox-superusers-password"

BOTH = {
    "PATH": "/usr/bin",
    "HOME": "/srv/example/home",
    "PREFECT_API_URL": "http://192.0.2.9:4200/api",
    "FYLGJA_API_ADDRESS": "127.0.0.1:7650",
    "FYLGJA_API_TOKEN": DEVELOPER_API_TOKEN,
    "FYLGJA_INFRAHUB_ADDRESS": "http://127.0.0.1:8000",
    "FYLGJA_INFRAHUB_TOKEN": ADMIN_TOKEN,
    "FYLGJA_INFRAHUB_WRITE_TOKEN": ADMIN_TOKEN,
    "FYLGJA_NETBOX_ADDRESS": "http://127.0.0.1:8800",
    "FYLGJA_NETBOX_CA": "/srv/example/netbox-ca.pem",
    "FYLGJA_NETBOX_TOKEN": NETBOX_READERS_TOKEN,
    "FYLGJA_NETBOX_WRITE_TOKEN": NETBOX_WRITE_TOKEN,
    "FYLGJA_NETBOX_SUPERUSER_PASSWORD": NETBOX_PASSWORD,
    "FYLGJA_NETBOX_SECRET_KEY": "the-netbox-secret-key",
    "FYLGJA_NETBOX_API_TOKEN_PEPPER": "the-netbox-pepper",
    "FYLGJA_ORCHESTRATOR_API_TOKEN": ORCHESTRATOR_API_TOKEN,
    "FYLGJA_ORCHESTRATOR_INFRAHUB_TOKEN": ORCHESTRATOR_INFRAHUB_TOKEN,
    "FYLGJA_ORCHESTRATOR_NETBOX_TOKEN": ORCHESTRATOR_NETBOX_TOKEN,
    "FYLGJA_ORCHESTRATOR_AUTH": AUTH,
    "FYLGJA_ORCHESTRATOR_SCOPE": "tag:infrahubs",
    "FYLGJA_ORCHESTRATOR_READER": "/srv/example/infrahub/reader.yaml",
    "FYLGJA_ORCHESTRATOR_NETBOX_SCOPE": "tag:netboxs",
    "FYLGJA_ORCHESTRATOR_NETBOX_READER": "/srv/example/netbox/reader.yaml",
    "FYLGJA_ORCHESTRATOR_ROOT": "/srv/example/orchestrator",
    "FYLGJA_ORCHESTRATOR_SOURCE": "infrahub",
    "FYLGJA_CREDENTIAL_SRLINUX_PASSWORD": "a-node-password",
    "INFRAHUB_INITIAL_ADMIN_TOKEN": ADMIN_TOKEN,
}
"""`local/.env` loaded with both sources' lines, both write tokens and NetBox's Compose secrets, and the caller's own
Prefect and source."""


def test_env_lines_add_netboxs_reader_and_scope_where_absent() -> None:
    held = {name: "held" for name in edge_dev.ENV_NAMES if not name.startswith("FYLGJA_ORCHESTRATOR_NETBOX_")}
    assert edge_dev.ENV_NAMES[-2:] == ("FYLGJA_ORCHESTRATOR_NETBOX_READER", "FYLGJA_ORCHESTRATOR_NETBOX_SCOPE")
    assert edge_dev.env_lines(held, MAIN, "tag:fylgja") == [
        ("FYLGJA_ORCHESTRATOR_NETBOX_READER", str(MAIN / "netbox" / "seed" / "reader.yaml")),
        ("FYLGJA_ORCHESTRATOR_NETBOX_SCOPE", "tag:fylgja"),
    ]
    reader_held = held | {"FYLGJA_ORCHESTRATOR_NETBOX_READER": "/srv/example/mine.yaml"}
    assert edge_dev.env_lines(reader_held, MAIN, "tag:other") == [("FYLGJA_ORCHESTRATOR_NETBOX_SCOPE", "tag:fylgja")]


def _by_path(name: str, path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """The module at `path`, loaded by its path under `name` for this test alone, as `make netbox-seed` runs it beside
    its `box`, and never imported as a package."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


def test_the_netbox_scope_is_the_netbox_seeds(monkeypatch: pytest.MonkeyPatch) -> None:
    seed = ROOT / "netbox" / "seed"
    _by_path("box", seed / "box.py", monkeypatch)
    assert edge_dev.NETBOX_SEED_SCOPE == _by_path("netbox_seed_under_test", seed / "seed.py", monkeypatch).SCOPE


def test_the_netbox_runner_is_given_netboxs_own_and_nothing_of_infrahubs() -> None:
    home = Path("/srv/example/local/prefect")
    given = edge_dev.runner_env(BOTH, BIND, home=home, source="netbox")

    netbox_token_is_the_orchestrators = same(given["FYLGJA_NETBOX_TOKEN"], ORCHESTRATOR_NETBOX_TOKEN)
    core_token_is_the_orchestrators = same(given["FYLGJA_API_TOKEN"], ORCHESTRATOR_API_TOKEN)
    assert netbox_token_is_the_orchestrators
    assert core_token_is_the_orchestrators
    assert given["FYLGJA_ORCHESTRATOR_SOURCE"] == "netbox"
    assert given["FYLGJA_ORCHESTRATOR_READER"] == "/srv/example/netbox/reader.yaml"
    assert given["FYLGJA_ORCHESTRATOR_SCOPE"] == "tag:netboxs"
    assert given["FYLGJA_NETBOX_ADDRESS"] == "http://127.0.0.1:8800"
    assert given["FYLGJA_NETBOX_CA"] == "/srv/example/netbox-ca.pem"
    assert given["PREFECT_API_URL"] == "http://192.0.2.1:4200/api"
    assert [name for name in given if name.startswith("FYLGJA_INFRAHUB_")] == []
    assert [name for name in given if name.startswith("FYLGJA_ORCHESTRATOR_NETBOX_")] == []
    assert sorted(given) == [
        "DO_NOT_TRACK",
        "FYLGJA_API_ADDRESS",
        "FYLGJA_API_TOKEN",
        "FYLGJA_NETBOX_ADDRESS",
        "FYLGJA_NETBOX_CA",
        "FYLGJA_NETBOX_TOKEN",
        "FYLGJA_ORCHESTRATOR_READER",
        "FYLGJA_ORCHESTRATOR_ROOT",
        "FYLGJA_ORCHESTRATOR_SCOPE",
        "FYLGJA_ORCHESTRATOR_SOURCE",
        "HOME",
        "PATH",
        "PREFECT_API_AUTH_STRING",
        "PREFECT_API_URL",
        "PREFECT_HOME",
        "PREFECT_SERVER_ANALYTICS_ENABLED",
    ]
    values = list(given.values())
    for secret in (NETBOX_WRITE_TOKEN, NETBOX_PASSWORD, NETBOX_READERS_TOKEN, ADMIN_TOKEN, DEVELOPER_API_TOKEN,
                   ORCHESTRATOR_INFRAHUB_TOKEN):
        held = any(same(value, secret) for value in values)
        assert not held


def test_the_infrahub_runner_is_given_no_netbox_name_and_its_source_said() -> None:
    environ = BOTH | {"FYLGJA_ORCHESTRATOR_SOURCE": "netbox"}
    given = edge_dev.runner_env(environ, BIND, home=Path("/srv/example/local/prefect"))

    infrahub_token_is_the_orchestrators = same(given["FYLGJA_INFRAHUB_TOKEN"], ORCHESTRATOR_INFRAHUB_TOKEN)
    assert infrahub_token_is_the_orchestrators
    assert given["FYLGJA_ORCHESTRATOR_SOURCE"] == "infrahub"
    assert given["FYLGJA_ORCHESTRATOR_READER"] == "/srv/example/infrahub/reader.yaml"
    assert given["FYLGJA_ORCHESTRATOR_SCOPE"] == "tag:infrahubs"
    assert [name for name in given if "NETBOX" in name] == []
    values = list(given.values())
    for secret in (NETBOX_WRITE_TOKEN, NETBOX_PASSWORD, NETBOX_READERS_TOKEN, ORCHESTRATOR_NETBOX_TOKEN):
        held = any(same(value, secret) for value in values)
        assert not held
    assert edge_dev.source_env(environ, "infrahub")["FYLGJA_ORCHESTRATOR_SOURCE"] == "infrahub"


@pytest.mark.parametrize(
    ("source", "missing", "remedy"),
    [
        ("netbox", "FYLGJA_NETBOX_ADDRESS", "run make netbox-up"),
        ("netbox", "FYLGJA_ORCHESTRATOR_NETBOX_TOKEN", "run make netbox-seed"),
        ("netbox", "FYLGJA_ORCHESTRATOR_NETBOX_READER", "run make orchestrator-env SOURCE=netbox"),
        ("netbox", "FYLGJA_ORCHESTRATOR_NETBOX_SCOPE", "run make orchestrator-env SOURCE=netbox"),
        ("netbox", "FYLGJA_ORCHESTRATOR_API_TOKEN", "run make orchestrator-env SOURCE=netbox"),
        ("infrahub", "FYLGJA_ORCHESTRATOR_API_TOKEN", "run make orchestrator-env"),
        ("infrahub", "FYLGJA_ORCHESTRATOR_INFRAHUB_TOKEN", "run make orchestrator-env"),
    ],
)
def test_a_missing_name_names_the_target_that_writes_it(source: str, missing: str, remedy: str) -> None:
    short = {name: value for name, value in BOTH.items() if name != missing}
    with pytest.raises(edge_dev.Missing) as raised:
        edge_dev.source_env(short, source)
    assert str(raised.value) == f"{missing} is not set: {remedy} and load local/.env"


def test_netboxs_ca_may_be_unset_and_the_runners_auth_may_not() -> None:
    without_ca = {name: value for name, value in BOTH.items() if name != "FYLGJA_NETBOX_CA"}
    assert "FYLGJA_NETBOX_CA" not in edge_dev.source_env(without_ca, "netbox")
    without_auth = {name: value for name, value in BOTH.items() if name != "FYLGJA_ORCHESTRATOR_AUTH"}
    assert "FYLGJA_NETBOX_TOKEN" in edge_dev.source_env(without_auth, "netbox")
    with pytest.raises(edge_dev.Missing) as raised:
        edge_dev.runner_env(without_auth, BIND, home=Path("/srv/example/local/prefect"), source="netbox")
    assert str(raised.value) == (
        "FYLGJA_ORCHESTRATOR_AUTH is not set: run make orchestrator-env SOURCE=netbox and load local/.env"
    )


class Execed(Exception):
    """`os.execve` replaced: what it was given, and never a return."""

    def __init__(self, path: object, argv: list[str], environ: dict[str, str]) -> None:
        super().__init__("execve")
        self.path, self.argv, self.environ = path, argv, environ


def _execve(path: object, argv: list[str], environ: dict[str, str]) -> None:
    raise Execed(path, argv, environ)


VERB = ["--local", "/srv/example/local", "--main", str(MAIN)]


def test_a_netbox_name_missing_is_named_and_exit_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(edge_dev.os, "execve", _execve)
    environ = {name: value for name, value in BOTH.items() if name != "FYLGJA_ORCHESTRATOR_NETBOX_TOKEN"}
    environ["PREFECT_BIND"] = BIND
    assert edge_dev.main(["serve", "--source", "netbox", *VERB], environ=environ) == 2
    said = capsys.readouterr()
    assert said.out == ""
    assert said.err.splitlines() == [
        "edge_dev: FYLGJA_ORCHESTRATOR_NETBOX_TOKEN is not set: run make netbox-seed and load local/.env"
    ]


def test_serve_becomes_the_runner_under_the_sources_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(edge_dev.os, "execve", _execve)
    environ = BOTH | {"PREFECT_BIND": BIND}
    with pytest.raises(Execed) as execed:
        edge_dev.main(["serve", "--source", "netbox", *VERB], environ=environ)
    assert execed.value.path == edge_dev.RUNNER
    assert execed.value.argv == [str(edge_dev.RUNNER), "serve"]
    expected = edge_dev.runner_env(environ, BIND, home=Path("/srv/example/local/prefect"), source="netbox")
    given_the_runners = same(execed.value.environ, expected)
    assert given_the_runners
    with pytest.raises(Execed) as execed:
        edge_dev.main(["serve", *VERB], environ=environ)
    assert execed.value.environ["FYLGJA_ORCHESTRATOR_SOURCE"] == "infrahub"


def test_run_becomes_the_command_under_the_sources_environment_and_no_prefect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(edge_dev.os, "execve", _execve)
    argv = ["run", "--source", "netbox", *VERB, "--", "stage", "mark", "--branch", "b", "--label", "l"]
    with pytest.raises(Execed) as execed:
        edge_dev.main(argv, environ=BOTH)
    assert execed.value.path == edge_dev.RUNNER
    assert execed.value.argv == [str(edge_dev.RUNNER), "stage", "mark", "--branch", "b", "--label", "l"]
    given = execed.value.environ
    given_the_sources = same(given, edge_dev.source_env(BOTH, "netbox"))
    assert given_the_sources
    assert [name for name in given if name.startswith("PREFECT_")] == []
    assert "FYLGJA_ORCHESTRATOR_AUTH" not in given
    assert given["FYLGJA_ORCHESTRATOR_SOURCE"] == "netbox"
    netbox_token_is_the_orchestrators = same(given["FYLGJA_NETBOX_TOKEN"], ORCHESTRATOR_NETBOX_TOKEN)
    assert netbox_token_is_the_orchestrators


def test_run_needs_a_command_and_no_auth(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(edge_dev.os, "execve", _execve)
    assert edge_dev.main(["run", "--source", "netbox", *VERB, "--"], environ=BOTH) == 2
    capsys.readouterr()
    without_auth = {name: value for name, value in BOTH.items() if name != "FYLGJA_ORCHESTRATOR_AUTH"}
    with pytest.raises(Execed):
        edge_dev.main(["run", "--source", "netbox", *VERB, "--", "stage", "list"], environ=without_auth)


def test_api_prints_the_address_alone(capsys: pytest.CaptureFixture[str]) -> None:
    assert edge_dev.main(["api", *VERB], environ={"PREFECT_BIND": BIND}) == 0
    said = capsys.readouterr()
    assert said.out == "http://192.0.2.1:4200/api\n"
    assert said.err == ""


@pytest.mark.parametrize("verb", ["env", "prefect-up", "prefect-down", "serve", "run", "api"])
def test_every_verb_needs_local_and_main(verb: str, capsys: pytest.CaptureFixture[str]) -> None:
    command = ["--", "stage", "list"] if verb == "run" else []
    assert edge_dev.main([verb, "--main", str(MAIN), *command], environ={}) == 2
    assert edge_dev.main([verb, "--local", "/srv/example/local", *command], environ={}) == 2
    capsys.readouterr()


@pytest.mark.parametrize("verb", ["run", "api"])
def test_a_verb_that_needs_neither_local_nor_main_says_so(verb: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert edge_dev.main([verb, "--help"], environ={}) == 0
    helped = " ".join(capsys.readouterr().out.split())
    assert f"required of every verb, and not read by {verb}" in helped


def test_env_without_local_env_names_both_targets_that_make_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    local = tmp_path / "local"
    local.mkdir()
    assert edge_dev.main(["env", "--local", str(local), "--main", str(tmp_path)], environ={}) == 2
    assert capsys.readouterr().err.splitlines() == [
        f"edge_dev: {local / '.env'} is not there: run make infrahub-up or make netbox-up first"
    ]
    assert list(local.iterdir()) == []


def _make_n(tmp_path: Path, *words: str) -> list[str]:
    """The lines `make -n` prints of a target's recipe, run in this checkout over a `LOCAL` of the test's: printed, and
    none of it run."""
    argv = ["make", "-n", "--no-print-directory", "-C", str(ROOT), *words, f"MAIN={MAIN}", f"LOCAL={tmp_path}"]
    made = subprocess.run(argv, capture_output=True, text=True, check=True, timeout=60, env={"PATH": "/usr/bin:/bin"})
    return made.stdout.splitlines()


def test_orchestrator_env_under_netbox_runs_nothing_of_infrahubs(tmp_path: Path) -> None:
    env_line = f"python3 -I scripts/edge_dev.py env --local {tmp_path} --main {MAIN}"
    assert _make_n(tmp_path, "orchestrator-env", "SOURCE=netbox") == [env_line]
    infrahubs = _make_n(tmp_path, "orchestrator-env")
    assert env_line in infrahubs
    assert any("infrahub/seed/account.py" in line for line in infrahubs)
    assert any("infrahub-sdk[ctl]" in line for line in infrahubs)


def test_orchestrator_serve_passes_the_source(tmp_path: Path) -> None:
    serve = f"python3 -I scripts/edge_dev.py serve --source {{}} --local {tmp_path} --main {MAIN}"
    assert _make_n(tmp_path, "orchestrator-serve", "SOURCE=netbox") == [serve.format("netbox")]
    assert _make_n(tmp_path, "orchestrator-serve") == [serve.format("infrahub")]


def test_orchestrator_env_refuses_a_source_it_does_not_know(tmp_path: Path) -> None:
    """As `orchestrator-serve` refuses it, and never by taking Infrahub's path: `make -n` prints nothing of the
    recipe."""
    for source in ("netbx", "", "infrahub netbox"):
        argv = ["make", "-n", "--no-print-directory", "-C", str(ROOT), "orchestrator-env", f"SOURCE={source}"]
        argv += [f"MAIN={MAIN}", f"LOCAL={tmp_path}"]
        env = {"PATH": "/usr/bin:/bin"}
        made = subprocess.run(argv, capture_output=True, text=True, check=False, timeout=60, env=env)
        assert made.returncode != 0, source
        assert made.stdout == "", source
        assert "SOURCE is infrahub or netbox" in made.stderr, source


def test_netbox_hook_reads_prefects_api_then_installs_the_trigger(tmp_path: Path) -> None:
    api = f"python3 -I scripts/edge_dev.py api --local {tmp_path} --main {MAIN}"
    assert _make_n(tmp_path, "netbox-hook") == [
        f'prefect=$({api}) && core/.venv/bin/python netbox/seed/hook.py --prefect "$prefect"'
    ]


def test_netbox_change_marks_through_the_examples_command_and_tags_only_by_1(tmp_path: Path) -> None:
    mark = f"python3 -I scripts/edge_dev.py run --source netbox --local {tmp_path} --main {MAIN} -- stage mark"
    change = "core/.venv/bin/python netbox/seed/change.py --branch {} {}-- " + mark
    assert _make_n(tmp_path, "netbox-change") == [change.format("third-link", "")]
    assert _make_n(tmp_path, "netbox-change", "NETBOX_BRANCH=other") == [change.format("other", "")]
    assert _make_n(tmp_path, "netbox-change", "NETBOX_TAG=1") == [change.format("third-link", "--tag ")]
    assert _make_n(tmp_path, "netbox-change", "NETBOX_TAG=yes") == [change.format("third-link", "")]


def _assigned(path: Path) -> dict[str, Any]:
    """The constants `path` assigns at its top, read by `ast` and never run: `netbox/seed/`'s scripts run beside their
    `box` alone, and import nothing of the example's."""
    held: dict[str, Any] = {}
    for statement in ast.parse(path.read_text(), str(path)).body:
        if isinstance(statement, ast.Assign) and len(statement.targets) == 1:
            target = statement.targets[0]
            if isinstance(target, ast.Name):
                try:
                    held[target.id] = ast.literal_eval(statement.value)
                except ValueError:
                    continue
    return held


def test_the_hooks_and_the_changes_values_are_the_examples() -> None:
    """What `netbox/seed/hook.py` and `change.py` hold by value of the example's: the tag, the flow and the deployment
    a tag starts, and the labels of the steps they mark, each a label `stage mark` takes."""
    from fylgja_orchestrator.edge import flows
    from fylgja_orchestrator.netbox import HEAD, LABEL, MAIN, TAG

    hook = _assigned(ROOT / "netbox" / "seed" / "hook.py")
    change = _assigned(ROOT / "netbox" / "seed" / "change.py")
    assert hook["TAG"] == change["TAG"] == TAG
    assert (hook["FLOW"], hook["DEPLOYMENT"]) == (flows.TWIN_REHEARSE, flows.DEPLOYMENT)
    labels = [label for label, _, _ in change["STEPS"]]
    assert labels == ["third-link", "n1-address"]
    assert all(LABEL.fullmatch(label) and label not in (MAIN, HEAD) for label in labels)


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
