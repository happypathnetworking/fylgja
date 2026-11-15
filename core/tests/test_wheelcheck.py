"""The wheel check's parts that need no network (D-066, D-084): the floors it installs the base
alone at are the lower bounds of the base's ranges in `core/pyproject.toml`, read from there and
stated by no test, and an entry that is no range is refused; and the base modules it imports
there are the sixteen `test_boundary_base.py` holds, read from the script by `ast`, so the two
lists cannot drift. What it holds each reader's command never to load beside the base is that
reader's import test's `FORBIDDEN`, the script's tuple read from the loaded module and the test's
by `ast`, so those cannot drift either; nor can what it holds each change source never to load
beside its own reader, which is the example's import scan's `CROSSED`. The check itself builds
and installs, and runs as `make wheelcheck`."""

from __future__ import annotations

import ast
import importlib.util
import subprocess
import tomllib
import zipfile
from functools import cache
from pathlib import Path
from types import ModuleType

import pytest
from test_boundary_base import BASE

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "wheelcheck.py"
REQUIRED = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["uv"]["required-version"].removeprefix("==")


@cache
def _script() -> ModuleType:
    """`scripts/wheelcheck.py`, loaded by path."""
    spec = importlib.util.spec_from_file_location("script_wheelcheck", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_floors_are_the_bases_ranges_lower_bounds() -> None:
    with (ROOT / "core" / "pyproject.toml").open("rb") as f:
        entries = tomllib.load(f)["project"]["dependencies"]
    expected = {}
    for entry in entries:
        name, _, rest = entry.partition(">=")
        expected[name] = rest.partition(",<")[0]
    assert set(expected) == {"httpx", "jsonschema", "PyYAML", "referencing"}
    assert _script().floors() == expected


@pytest.mark.parametrize("entry", ["httpx", "httpx>=0.27.0", "httpx==0.28.1"])
def test_a_base_entry_that_is_no_range_is_refused(tmp_path: Path, entry: str) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(f'[project]\nname = "fylgja-core"\ndependencies = ["{entry}"]\n')
    module = _script()
    with pytest.raises(module.Failure) as raised:
        module.floors(pyproject)
    assert entry in str(raised.value)


def test_the_base_modules_the_check_imports_are_the_boundarys() -> None:
    assigned = [
        statement.value
        for statement in ast.parse(SCRIPT.read_text(), str(SCRIPT)).body
        if isinstance(statement, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "BASE_MODULES" for target in statement.targets)
    ]
    assert len(assigned) == 1, "scripts/wheelcheck.py assigns BASE_MODULES once"
    assert ast.literal_eval(assigned[0]) == BASE


def _assigned(path: Path, name: str) -> tuple[object, ...]:
    """The tuple the file at `path` assigns to `name`, read by `ast`."""
    assigned = [
        statement.value
        for statement in ast.parse(path.read_text(), str(path)).body
        if isinstance(statement, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == name for target in statement.targets)
    ]
    assert len(assigned) == 1, f"{path} assigns {name} once"
    held = ast.literal_eval(assigned[0])
    assert isinstance(held, tuple)
    return held


def _forbidden(path: Path) -> tuple[str, ...]:
    """The `FORBIDDEN` a reader's import test at `path` assigns, read by `ast`."""
    return tuple(str(name) for name in _assigned(path, "FORBIDDEN"))


@pytest.mark.parametrize(
    ("name", "reader"),
    [("NOT_BESIDE_READER", "infrahub"), ("NOT_BESIDE_NETBOX_READER", "netbox")],
)
def test_what_a_readers_command_never_loads_is_its_import_tests(name: str, reader: str) -> None:
    held = getattr(_script(), name)
    assert sorted(held) == sorted(_forbidden(ROOT / "readers" / reader / "tests" / "test_boundary.py"))


def test_what_each_change_source_never_loads_is_the_example_scans() -> None:
    """Importing the Infrahub change source loads nothing of the NetBox one or its reader, and the reverse."""
    held = _assigned(SCRIPT, "CROSSED")
    assert held == _assigned(ROOT / "orchestrator" / "tests" / "test_boundary_edge.py", "CROSSED")
    assert sorted(str(pair[0]) for pair in held if isinstance(pair, tuple)) == ["infrahub", "netbox"]


def _uv_says(monkeypatch: pytest.MonkeyPatch, module: ModuleType, said: str) -> None:
    """`uv --version` answered `said`, and the PATH holding a uv at /opt/uv."""
    monkeypatch.setattr(module.shutil, "which", lambda name: "/opt/uv")
    monkeypatch.setattr(
        module.subprocess, "run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout=said + "\n", stderr=""),
    )


def test_the_check_needs_uv_on_the_path_and_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _script()
    monkeypatch.setattr(module.shutil, "which", lambda name: None)
    with pytest.raises(module.Failure) as raised:
        module.uv()
    assert "uv" in str(raised.value) and "PATH" in str(raised.value)
    _uv_says(monkeypatch, module, f"uv {REQUIRED} (abc1234 2026-11-01)")
    assert module.uv() == "/opt/uv"


def test_the_check_needs_the_uv_the_root_requires_and_says_both(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every call of the check runs outside the tree, where the root's `required-version` is never seen."""
    module = _script()
    _uv_says(monkeypatch, module, "uv 0.1.0 (abc1234 2026-01-01)")
    with pytest.raises(module.Failure) as raised:
        module.uv()
    said = str(raised.value)
    assert "\n" not in said and "0.1.0" in said and REQUIRED in said


def test_main_with_no_uv_or_another_uv_makes_no_directory(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _script()

    def no_directory(*args: object, **kw: object) -> None:
        raise AssertionError("a temporary directory was made")

    monkeypatch.setattr(module.tempfile, "TemporaryDirectory", no_directory)
    monkeypatch.setattr(module.shutil, "which", lambda name: None)
    assert module.main() == 1
    lines = capsys.readouterr().err.splitlines()
    assert len(lines) == 1 and "uv" in lines[0]
    _uv_says(monkeypatch, module, "uv 0.1.0 (abc1234 2026-01-01)")
    assert module.main() == 1
    lines = capsys.readouterr().err.splitlines()
    assert len(lines) == 1 and "0.1.0" in lines[0] and REQUIRED in lines[0]


def test_each_environment_wheel_and_install_is_uv(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _script()
    ran: list[tuple[list[str], Path]] = []
    monkeypatch.setattr(module, "run", lambda argv, cwd: ran.append((argv, cwd)))
    monkeypatch.setattr(module, "uv", lambda: "uv")
    python = module.sys.executable
    assert module.venv(Path("/t/e")) == Path("/t/e/bin")
    module.wheel(Path("/t/src/core"), Path("/t/dist"))
    module.install(Path("/t/e/bin"), "w.whl", constraints=Path("/t/c.txt"))
    module.install(Path("/t/e/bin"), "a.whl", "b.whl")
    module.install(Path("/t/e/bin"), "fylgja-netbox==1.0.0rc1", find_links=Path("/t/links"))
    assert ran == [
        (["uv", "venv", "--no-project", "--no-python-downloads", "--python", python, "/t/e"], Path("/t")),
        (["uv", "build", "--wheel", "--no-python-downloads", "--python", python, "--out-dir", "/t/dist",
          "/t/src/core"], Path("/t")),
        (["uv", "pip", "install", "--python", "/t/e/bin/python", "--constraints", "/t/c.txt", "w.whl"], Path("/t")),
        (["uv", "pip", "install", "--python", "/t/e/bin/python", "a.whl", "b.whl"], Path("/t")),
        (["uv", "pip", "install", "--python", "/t/e/bin/python", "--no-index", "--find-links", "/t/links",
          "fylgja-netbox==1.0.0rc1"], Path("/t")),
    ]


def _wheel(tmp_path: Path, name: str, version: str, requires: list[str]) -> Path:
    """A wheel holding only its `METADATA`: `name` at `version`, one `Requires-Dist` an entry of `requires`."""
    stem = f"{name.replace('-', '_')}-{version}"
    path = tmp_path / f"{stem}-py3-none-any.whl"
    lines = ["Metadata-Version: 2.4", f"Name: {name}", f"Version: {version}",
             *(f"Requires-Dist: {entry}" for entry in requires)]
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{stem}.dist-info/METADATA", "\n".join(lines) + "\n\n")
    return path


def test_the_tree_version_is_the_one_line_of_version(tmp_path: Path) -> None:
    module = _script()
    assert module.tree_version() == (ROOT / "VERSION").read_text().strip()
    for text in ("", "\n", "1.0.0\n2.0.0\n"):
        (tmp_path / "VERSION").write_text(text)
        with pytest.raises(module.Failure, match="VERSION"):
            module.tree_version(tmp_path / "VERSION")
    with pytest.raises(module.Failure, match="VERSION"):
        module.tree_version(tmp_path / "absent" / "VERSION")


def test_a_wheel_of_another_version_is_named(tmp_path: Path) -> None:
    module = _script()
    wheel = _wheel(tmp_path, "fylgja-core", "1.0.0rc1", [])
    module.versioned(wheel, "1.0.0rc1")
    with pytest.raises(module.Failure) as raised:
        module.versioned(wheel, "1.0.0")
    assert wheel.name in str(raised.value) and "1.0.0rc1" in str(raised.value) and "1.0.0" in str(raised.value)


@pytest.mark.parametrize(
    "entry", ["fylgja-core<2,>=1.0.0rc1", "fylgja-core>=1.0.0rc1,<2", "fylgja_core (<2, >=1.0.0rc1)"]
)
def test_a_reader_requiring_the_core_at_the_version_within_the_major_passes(tmp_path: Path, entry: str) -> None:
    wheel = _wheel(tmp_path, "fylgja-netbox", "1.0.0rc1", [entry, "httpx<1,>=0.27.0"])
    _script().requires_core(wheel, "1.0.0rc1")


@pytest.mark.parametrize(
    "requires",
    [
        [],
        ["fylgja-core"],
        ["fylgja-core>=1.0.0"],
        ["fylgja-core<2,>=1.0.0"],
        ["fylgja-core<3,>=1.0.0rc1"],
        ["fylgja-core<2,>=1.0.0rc1", "fylgja-core<2,>=1.0.0rc1; extra == 'dev'"],
    ],
)
def test_a_reader_requiring_the_core_otherwise_is_named(tmp_path: Path, requires: list[str]) -> None:
    module = _script()
    wheel = _wheel(tmp_path, "fylgja-netbox", "1.0.0rc1", requires)
    with pytest.raises(module.Failure) as raised:
        module.requires_core(wheel, "1.0.0rc1")
    assert wheel.name in str(raised.value) and ">=1.0.0rc1" in str(raised.value)


def test_the_base_requirements_are_the_cores_unmarked_entries(tmp_path: Path) -> None:
    wheel = _wheel(tmp_path, "fylgja-core", "1.0.0rc1",
                   ["httpx<1,>=0.27.0", "PyYAML<7,>=6.0.3", "uvicorn==0.54.0; extra == \"server\""])
    assert _script().base_requirements(wheel) == ["httpx<1,>=0.27.0", "PyYAML<7,>=6.0.3"]
