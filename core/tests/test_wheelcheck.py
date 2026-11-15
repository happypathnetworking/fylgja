"""The wheel check's parts that need no network (D-066, D-084): the floors it installs the base
alone at are the lower bounds of the base's ranges in `core/pyproject.toml`, read from there and
stated by no test, and an entry that is no range is refused; and the base modules it imports
there are the seventeen `test_boundary_base.py` holds, read from the script by `ast`, so the two
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
from typing import ClassVar

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
    monkeypatch.setattr(module, "run", lambda argv, cwd, env=None: ran.append((argv, cwd)))
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


def _tree_commit() -> str:
    """The tree's commit as `Makefile`'s `COMMIT` and each `setup.py` read it: HEAD, and `-dirty` where git has
    anything to say of the tree."""
    def git(*argv: str) -> str:
        return subprocess.run(["git", "-C", str(ROOT), *argv], capture_output=True, text=True, check=True).stdout

    return git("rev-parse", "HEAD").strip() + ("-dirty" if git("status", "--porcelain").strip() else "")


def test_the_trees_commit_is_read_as_the_build_reads_it(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _script()
    module.tree_commit.cache_clear()
    assert module.tree_commit() == _tree_commit()
    module.tree_commit.cache_clear()
    monkeypatch.setenv("PATH", "")
    assert module.tree_commit() == "unknown"
    module.tree_commit.cache_clear()


def test_each_wheel_is_built_at_the_trees_commit_whatever_the_environment_says(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _script()
    given: list[dict[str, str] | None] = []
    monkeypatch.setattr(module, "run", lambda argv, cwd, env=None: given.append(env))
    monkeypatch.setattr(module, "uv", lambda: "uv")
    monkeypatch.setenv("FYLGJA_BUILD_COMMIT", "f" * 40)
    monkeypatch.setattr(module, "tree_commit", lambda: "0" * 40 + "-dirty")
    module.wheel(Path("/t/src/core"), Path("/t/dist"))
    monkeypatch.setattr(module, "tree_commit", lambda: "unknown")
    module.wheel(Path("/t/src/core"), Path("/t/dist"))
    assert given[0] is not None and given[0]["FYLGJA_BUILD_COMMIT"] == "0" * 40 + "-dirty"
    assert given[1] is not None and "FYLGJA_BUILD_COMMIT" not in given[1]  # no git: the build says unknown itself


def test_a_wheel_holding_another_commit_or_none_is_named(tmp_path: Path) -> None:
    module = _script()
    wheel = tmp_path / "w-1-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("fylgja_core/COMMIT", "a" * 40 + "\n")
    module.held_commit(wheel, "fylgja_core", "a" * 40)
    for package, commit in (("fylgja_core", "b" * 40), ("fylgja_netbox", "a" * 40)):
        with pytest.raises(module.Failure) as raised:
            module.held_commit(wheel, package, commit)
        assert wheel.name in str(raised.value) and f"{package}/COMMIT" in str(raised.value)


def test_a_command_answers_version_with_its_program_the_version_and_the_commit(tmp_path: Path) -> None:
    module = _script()
    for said, passes in (("prog 1.0.0rc1 (commit abc)\n", True), ("prog 1.0.0rc1\n", False),
                         ("other 1.0.0rc1 (commit abc)\n", False), ("prog 1.0.0rc1 (commit abd)\n", False)):
        command = tmp_path / "prog"
        command.write_text("#!/bin/sh\nprintf '%s\\n' '" + said.rstrip("\n") + "'\n")
        command.chmod(0o755)
        if passes:
            module.answers_version(command, "prog", "1.0.0rc1", "abc", tmp_path)
        else:
            with pytest.raises(module.Failure, match="--version"):
                module.answers_version(command, "prog", "1.0.0rc1", "abc", tmp_path)


def test_the_core_packages_are_the_directories_setup_py_names() -> None:
    assert _script().core_packages() == ("psp", "probes")


def test_a_core_packages_list_that_is_none_is_refused(tmp_path: Path) -> None:
    module = _script()
    setup = tmp_path / "setup.py"
    setup.write_text("OTHER = ('psp',)\n")
    with pytest.raises(module.Failure, match="CORE_PACKAGES"):
        module.core_packages(setup)
    setup.write_text("CORE_PACKAGES = ['psp']\n")
    with pytest.raises(module.Failure, match="tuple of strings"):
        module.core_packages(setup)


def _shipped_wheel(tmp_path: Path, members: dict[str, bytes]) -> Path:
    path = tmp_path / "w.whl"
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return path


def _tracked() -> dict[str, bytes]:
    return {f"fylgja_core/shipped/{n}": d for n, d in _script().tracked_packages(("psp", "probes")).items()}


def test_a_wheel_carrying_the_tracked_yaml_of_each_package_and_nothing_else_passes(tmp_path: Path) -> None:
    carried = _tracked()
    assert {"fylgja_core/shipped/psp/nokia_srlinux.yaml", "fylgja_core/shipped/probes/ping.yaml"} <= carried.keys()
    assert _script().shipped(_shipped_wheel(tmp_path, carried)) == len(carried)


def test_a_wheel_whose_shipped_packages_differ_from_the_trees_is_named(tmp_path: Path) -> None:
    module = _script()
    carried = _tracked()
    missing = dict(carried)
    del missing["fylgja_core/shipped/probes/ping.yaml"]
    with pytest.raises(module.Failure, match=r"missing from the wheel: probes/ping\.yaml"):
        module.shipped(_shipped_wheel(tmp_path, missing))
    extra = {**carried, "fylgja_core/shipped/psp/README.md": b"a readme\n"}
    with pytest.raises(module.Failure, match=r"extra in the wheel: psp/README\.md"):
        module.shipped(_shipped_wheel(tmp_path, extra))
    changed = {**carried, "fylgja_core/shipped/psp/arista_eos.yaml": b"changed\n"}
    with pytest.raises(module.Failure, match=r"differs from the tree's: psp/arista_eos\.yaml"):
        module.shipped(_shipped_wheel(tmp_path, changed))


def _described(tmp_path: Path, fields: list[str], body: str = "", licence: bytes | None = None) -> Path:
    """A wheel holding a `METADATA` of `fields` (one `Name: value` line each) and `body`, and `fylgja_core/LICENSE`
    where `licence` is given."""
    path = tmp_path / "fylgja_core-1.0.0rc1-py3-none-any.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("fylgja_core-1.0.0rc1.dist-info/METADATA", "\n".join(fields) + "\n\n" + body)
        if licence is not None:
            archive.writestr("fylgja_core/LICENSE", licence)
    return path


def _published_fields(module: ModuleType, core: bool) -> list[str]:
    classifiers = [*module.CLASSIFIERS, *([module.CORE_CLASSIFIER] if core else [])]
    docs = "tree/main/docs" if core else "tree/main/readers/netbox"
    return [
        "Metadata-Version: 2.4", "Name: fylgja-core", "Version: 1.0.0rc1", "License-Expression: Apache-2.0",
        f"Project-URL: Repository, {module.REPOSITORY}",
        f"Project-URL: Changelog, {module.REPOSITORY}/blob/main/CHANGELOG.md",
        f"Project-URL: Documentation, {module.REPOSITORY}/{docs}",
        *(f"Classifier: {c}" for c in classifiers),
        *(["Description-Content-Type: text/markdown"] if core else []),
    ]


def test_a_published_wheel_states_the_projects_metadata_and_any_other_is_named(tmp_path: Path) -> None:
    module = _script()
    readme = module.rewritten_readme()
    assert readme != (ROOT / "README.md").read_text(), "the parse is blind"
    good = _published_fields(module, True)
    module.published_metadata(_described(tmp_path, good, readme), "tree/main/docs", core=True)
    module.published_metadata(_described(tmp_path, _published_fields(module, False)), "tree/main/readers/netbox")
    # Each fault, and the line of the failure that names it.
    bad = {
        "License-Expression is None": [f for f in good if not f.startswith("License-Expression")],
        "License-Expression is ['MIT']": [f.replace("Apache-2.0", "MIT") for f in good],
        "Project-URL is": [f for f in good if not f.startswith("Project-URL: Changelog")],
        "Classifier is": [f for f in good if "Typing" not in f],
        "'License :: OSI Approved :: Apache Software License'": [
            *good, "Classifier: License :: OSI Approved :: Apache Software License"],
        "Author-email is ['someone@example.org']": [*good, "Author-email: someone@example.org"],
        "Description-Content-Type is None": [f for f in good if not f.startswith("Description-Content-Type")],
    }
    for said, fields in bad.items():
        with pytest.raises(module.Failure, match="METADATA") as raised:
            module.published_metadata(_described(tmp_path, fields, readme), "tree/main/docs", core=True)
        (line,) = [line for line in str(raised.value).splitlines()[1:]]
        assert said in line, (said, line)
    with pytest.raises(module.Failure, match="README"):
        module.published_metadata(_described(tmp_path, good, "another text"), "tree/main/docs", core=True)
    with pytest.raises(module.Failure, match="Classifier"):
        module.published_metadata(_described(tmp_path, _published_fields(module, False), readme), "tree/main/docs",
                                  core=True)


def test_the_example_must_be_marked_never_to_be_uploaded(tmp_path: Path) -> None:
    module = _script()
    base = ["Metadata-Version: 2.4", "Name: fylgja-core", "Version: 1.0.0rc1"]
    module.private_metadata(_described(tmp_path, [*base, "Classifier: Private :: Do Not Upload"]))
    for fields in (base, [*base, "Classifier: Private :: Do Not Upload", "Classifier: Typing :: Typed"],
                   [*base, "Classifier: Private :: Do Not Upload", f"Project-URL: Repository, {module.REPOSITORY}"]):
        with pytest.raises(module.Failure):
            module.private_metadata(_described(tmp_path, fields))


def test_a_wheel_holds_the_roots_licence_or_is_named(tmp_path: Path) -> None:
    module = _script()
    text = (ROOT / "LICENSE").read_bytes()
    module.held_licence(_described(tmp_path, ["Name: x"], licence=text), "fylgja_core")
    module.held_licence(_described(tmp_path, ["Name: x"]), "fylgja_core", expected=False)
    for licence, expected in ((None, True), (text + b"x", True), (text, False)):
        wheel = _described(tmp_path, ["Name: x"], licence=licence)
        with pytest.raises(module.Failure, match="LICENSE"):
            module.held_licence(wheel, "fylgja_core", expected)


def test_the_netbox_readers_links_directory_is_the_two_wheels_alone(tmp_path: Path,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    module = _script()
    core = tmp_path / "fylgja_core-1.0.0rc1-py3-none-any.whl"
    reader = tmp_path / "netbox-reader" / "dist" / "fylgja_netbox-1.0.0rc1-py3-none-any.whl"
    reader.parent.mkdir(parents=True)
    for wheel in (core, reader):
        wheel.write_bytes(b"a wheel")
    (reader.parent / "fylgja_infrahub-1.0.0rc1-py3-none-any.whl").write_bytes(b"another, built beside it")
    for name in ("versioned", "requires_core", "held_commit", "published_metadata", "held_licence",
                 "carried_by_netbox_reader", "run", "answers_version", "refused_without_token"):
        monkeypatch.setattr(module, name, lambda *a, **k: None)
    monkeypatch.setattr(module, "build_netbox_reader", lambda tmp: reader)
    monkeypatch.setattr(module, "base_requirements", lambda wheel: ["httpx>=0.27.0,<1"])
    monkeypatch.setattr(module, "venv", lambda path: path / "bin")
    installs: list[tuple[tuple[str, ...], list[str] | None]] = []

    def install(env: Path, *requirements: str, constraints: Path | None = None,
                find_links: Path | None = None) -> None:
        installs.append((requirements, sorted(p.name for p in find_links.iterdir()) if find_links else None))

    monkeypatch.setattr(module, "install", install)
    module.check_netbox_reader(tmp_path, core)
    version = module.tree_version()
    by_name = [links for requirements, links in installs if requirements == (f"fylgja-netbox=={version}",)]
    assert by_name == [sorted([core.name, reader.name])]
    assert [links for _, links in installs if links is not None] == by_name


def test_a_loopback_request_goes_by_no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    import http.server
    import socket
    import threading

    class Answer(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"direct")

        def log_message(self, *args: object) -> None:
            pass

    with socket.socket() as probe:  # a port nothing listens on, as the proxy the environment names
        probe.bind(("127.0.0.1", 0))
        closed = probe.getsockname()[1]
    for name in ("no_proxy", "NO_PROXY"):
        monkeypatch.delenv(name, raising=False)
    for name in ("http_proxy", "HTTP_PROXY"):
        monkeypatch.setenv(name, f"http://127.0.0.1:{closed}")
    server = http.server.HTTPServer(("127.0.0.1", 0), Answer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert _script().answers(f"http://127.0.0.1:{server.server_address[1]}/", "t") == (200, b"direct")
    finally:
        server.shutdown()
        server.server_close()


class _Server:
    """A `subprocess.Popen` of the server that never ends by itself: its `returncode` is `None` until it is signalled
    (143) or killed (-9); it records its environment and whether it was killed and waited on."""

    made: ClassVar[list[_Server]] = []

    def __init__(self, argv: list[str], *, env: dict[str, str], stdout: object, **kw: object) -> None:
        self.env = env
        self.returncode: int | None = None
        self.killed = self.waited = False
        _Server.made.append(self)

    def poll(self) -> int | None:
        return self.returncode

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9

    def wait(self, timeout: float | None = None) -> int | None:
        self.waited = True
        return self.returncode

    def send_signal(self, sig: int) -> None:
        self.returncode = 143


def _serving(monkeypatch: pytest.MonkeyPatch, replies: list[object]) -> ModuleType:
    """The script with the token, the hash, the server and its answers faked: `replies` are what `answers` gives in
    turn, an exception raised, anything else returned."""
    import secrets

    module = _script()
    _Server.made.clear()
    monkeypatch.setattr(module.secrets, "token_urlsafe", lambda n: "the-token-of-the-check")
    assert module.secrets is secrets

    def hashed(argv: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        assert kw.get("input") == "the-token-of-the-check"
        return subprocess.CompletedProcess(argv, 0, "ab" * 32 + "\n", "")

    monkeypatch.setattr(module.subprocess, "run", hashed)
    monkeypatch.setattr(module.subprocess, "Popen", _Server)
    monkeypatch.setattr(module.time, "sleep", lambda s: None)
    replies = list(replies)

    def answers(url: str, token: str, body: bytes | None = None) -> tuple[int, bytes]:
        assert token == "the-token-of-the-check"
        reply = replies.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        assert isinstance(reply, tuple)
        return reply

    monkeypatch.setattr(module, "answers", answers)
    monkeypatch.setenv("PYTHONPATH", "/elsewhere")
    monkeypatch.setenv("PYTHONHOME", "/elsewhere")
    monkeypatch.setenv("FYLGJA_PACKAGES", "/elsewhere")
    return module


def _holds_the_token(tmp: Path) -> list[str]:
    return [str(p) for p in tmp.rglob("*") if p.is_file() and b"the-token-of-the-check" in p.read_bytes()]


def test_serve_fails_at_once_on_an_answer_other_than_200_and_ends_the_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _serving(monkeypatch, [(503, b"not ready")])
    (tmp_path / "env").mkdir()
    with pytest.raises(module.Failure, match="503") as raised:
        module.serve(tmp_path, tmp_path / "env", "1.0.0rc1 (commit unknown)")
    assert "the-token-of-the-check" not in str(raised.value)
    (server,) = _Server.made
    assert server.killed and server.waited
    assert not [k for k in server.env if k.startswith(("FYLGJA_", "PYTHON")) and k not in (
        "FYLGJA_STORE", "FYLGJA_TOKENS", "FYLGJA_LISTEN")]
    assert (tmp_path / "serve" / "tokens").read_text() == "ab" * 32 + " wheelcheck\n"
    assert _holds_the_token(tmp_path) == []


def test_serve_waits_through_a_broken_answer_and_ends_the_server_on_a_wrong_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import http.client
    import json

    module = _serving(monkeypatch, [http.client.BadStatusLine("garbled"), ConnectionRefusedError(),
                                    (200, json.dumps({"build": "another"}).encode())])
    (tmp_path / "env").mkdir()
    with pytest.raises(module.Failure, match="says the build 'another'") as raised:
        module.serve(tmp_path, tmp_path / "env", "1.0.0rc1 (commit unknown)")
    assert "the-token-of-the-check" not in str(raised.value)
    (server,) = _Server.made
    assert server.killed and server.waited
    assert _holds_the_token(tmp_path) == []
