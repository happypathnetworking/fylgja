"""`docs/server.md` holds to the server: its `Variable` table names every variable the configuration reads, under
each store and driver, and the credential provider's, each default is the configuration's constant, its `Option`
table the server's parser's options and its `Status` table every status the server returns, each compared with the
code as sets, both ways; and the two recipes the page gives are run."""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path

from pages import ROOT, blocks, flags, options, rows, section, statuses, text, ticked
from test_config import FULL, S3

from fylgja_core import config, credentials, packages
from fylgja_core.containerlab import pool
from fylgja_core.server import __main__ as server
from fylgja_core.server import auth

PAGE = "docs/server.md"
SERVER = ROOT / "core/src/fylgja_core/server"


class Recording(Mapping[str, str]):
    """A mapping that records each key it is asked for, whether it holds it or not."""

    def __init__(self, data: Mapping[str, str]) -> None:
        self._data = dict(data)
        self.asked: set[str] = set()

    def __getitem__(self, key: str) -> str:
        self.asked.add(key)
        return self._data[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)


def _read(environ: Mapping[str, str]) -> set[str]:
    """The names `config.from_environ` asks `environ` for."""
    recording = Recording(environ)
    config.from_environ(recording)
    return recording.asked


def _settings() -> list[list[str]]:
    found = rows(section(text(PAGE), "## Settings"), "Variable")
    assert found, "the parse is blind"
    return found


def test_the_settings_table_is_every_variable_the_configuration_reads() -> None:
    directory = {**FULL, "FYLGJA_TLS_CERT": "/etc/fylgja/tls.crt", "FYLGJA_TLS_KEY": "/etc/fylgja/tls.key"}
    object_store = {**S3, "FYLGJA_S3_CA": "/etc/fylgja/ca.pem", "FYLGJA_S3_REGION": "us-west-2"}
    read = _read(directory) | _read(object_store)
    read |= {credentials.variable("X", p).replace("_X_", "_<NAME>_") for p in ("USERNAME", "PASSWORD", "REGISTRY")}
    assert len(read) >= 20, "the parse is blind"
    listed = {name for row in _settings() for name in ticked(row[0])}
    assert listed == read
    assert not {name for name in listed if name == "FYLGJA_BUILD_COMMIT" or name.startswith("FYLGJA_API_")}


def test_each_default_the_page_gives_is_the_configurations() -> None:
    by_name = {ticked(row[0])[0]: row for row in _settings()}
    held = {
        "FYLGJA_LISTEN": config.DEFAULT_LISTEN,
        "FYLGJA_DRIVER": config.DEFAULT_DRIVER,
        "FYLGJA_WORKERS": str(config.DEFAULT_WORKERS),
        "FYLGJA_STEP_WAIT_S": str(config.DEFAULT_STEP_WAIT_S),
        "FYLGJA_RESYNC_S": str(config.DEFAULT_RESYNC_S),
        "FYLGJA_S3_REGION": config.DEFAULT_S3_REGION,
        "FYLGJA_LAB_POOL": str(pool.DEFAULT_POOL),
    }
    for name, default in held.items():
        assert default in ticked(by_name[name][1]), f"{name}'s default is not `{default}`"
    for name in ("FYLGJA_STORE", "FYLGJA_TOKENS"):
        assert "required" in by_name[name][1], f"{name} is not required"


def _statuses_the_server_gives() -> set[int]:
    """Each integer a `return` gives in the server's `__main__`, those of `_stopped`'s tuples, each `SystemExit` of an
    integer, and the console script's `return` and `SystemExit`, read by `ast`; a bool is no status."""
    found: set[int] = set()

    def number(node: ast.AST | None) -> None:
        if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
            found.add(node.value)

    for name in ("__main__.py", "entry.py"):
        tree = ast.parse((SERVER / name).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Return):
                number(node.value)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "SystemExit":
                for argument in node.args:
                    number(argument)
            elif isinstance(node, ast.FunctionDef) and node.name == "_stopped":
                for inner in ast.walk(node):
                    number(inner)
    return found


def test_the_page_names_the_servers_options_and_exit_statuses() -> None:
    page = text(PAGE)
    found = rows(section(page, "## Options"), "Option")
    assert found, "the parse is blind"
    listed = {option for row in found for option in flags(row[0])}
    assert listed == options(server._parser())[()]
    given = _statuses_the_server_gives()
    assert len(given) >= 5, "the parse is blind"
    assert statuses(section(page, "## Exit statuses")) == given


def _recipe() -> tuple[str, str]:
    """The `sh` block under `## The token file`, and the principal it adds a line for."""
    (body,) = [lines for info, lines in blocks("\n".join(section(text(PAGE), "## The token file"))) if info == "sh"]
    recipe = "\n".join(body) + "\n"
    found = re.search(r'" (\S+) >> "\$FYLGJA_TOKENS"', recipe)
    assert found, "the parse is blind"
    return recipe, found.group(1)


def test_the_token_recipe_makes_a_line_the_server_accepts(tmp_path: Path) -> None:
    recipe, principal = _recipe()
    tokens = tmp_path / "tokens"
    environ = {"PATH": "/usr/bin:/bin", "FYLGJA_TOKENS": str(tokens)}
    run = subprocess.run(["bash", "-eu", "-c", recipe], cwd=tmp_path, env=environ, capture_output=True, text=True,
                         check=False)
    assert (run.returncode, run.stdout) == (0, "")
    (client,) = [path for path in tmp_path.iterdir() if path != tokens]
    (assignment,) = client.read_text().splitlines()
    name, _, token = assignment.partition("=")
    assert name == "FYLGJA_API_TOKEN"
    assert token
    assert auth.Tokens.load(tokens).principal(token) == principal
    assert token not in tokens.read_text()


def test_the_packages_line_prints_the_shipped_ones() -> None:
    (body,) = [lines for info, lines in blocks("\n".join(section(text(PAGE), "## The packages"))) if info == "sh"]
    found = re.search(r"python3 -c '([^']+)'", "\n".join(body))
    assert found, "the parse is blind"
    run = subprocess.run([sys.executable, "-c", found.group(1)], capture_output=True, text=True, check=False)
    assert run.returncode == 0
    assert run.stdout.strip() == ":".join(map(str, packages.shipped()))
