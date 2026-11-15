"""The release's one version and the commit each build was made at (D-106). The version is written once, in `VERSION`
at the root, as `formats/` is the one place a format lives (D-066), and read by every distribution's build, each
`setup.py` passing it to `setup(version=...)` and each `pyproject.toml` listing `version` as dynamic; and each reader
requiring the core at that version or later within the major. setuptools is no library of the development venv, so
each `setup.py` is loaded here over a stand-in for the two names it takes from it, `setup` recording what it is given.
`fylgja_core.release` answers a distribution's build, `<version> (commit <hash>)`, which each command's `--version` and
`GET /v1/version`'s `build` show; each build writes the commit it was made at into its package as `COMMIT`."""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import re
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from fylgja_core import release

ROOT = Path(__file__).resolve().parents[2]
MEMBERS = ["core", "readers/infrahub", "readers/netbox", "orchestrator"]
READERS = ["readers/infrahub", "readers/netbox"]
# A release, X.Y.Z, or its candidate, X.Y.ZrcN.
FORM = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(rc[1-9]\d*)?")
VERSION = (ROOT / "VERSION").read_text().strip()


def project(member: str) -> dict[str, Any]:
    with (ROOT / member / "pyproject.toml").open("rb") as f:
        found: dict[str, Any] = tomllib.load(f)["project"]
    return found


class _BuildPy:
    """Stands in for setuptools' `build_py`: its own run builds nothing, and its helpers do what setuptools' do."""

    build_lib = ""

    def run(self) -> None:
        pass

    def mkpath(self, name: str) -> None:
        Path(name).mkdir(parents=True, exist_ok=True)

    def copy_file(self, infile: str, outfile: str) -> None:
        shutil.copyfile(infile, outfile)


def load_setup(member: str, monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, list[dict[str, Any]]]:
    """`<member>/setup.py`, loaded over the stand-in, and the keywords each call of its `setup()` was given."""
    given: list[dict[str, Any]] = []
    setuptools = ModuleType("setuptools")
    vars(setuptools)["setup"] = lambda **kw: given.append(kw)
    command = ModuleType("setuptools.command.build_py")
    vars(command)["build_py"] = _BuildPy
    monkeypatch.setitem(sys.modules, "setuptools", setuptools)
    monkeypatch.setitem(sys.modules, "setuptools.command", ModuleType("setuptools.command"))
    monkeypatch.setitem(sys.modules, "setuptools.command.build_py", command)
    spec = importlib.util.spec_from_file_location(f"setup_{member.replace('/', '_')}", ROOT / member / "setup.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, given


def test_the_version_is_one_line_of_a_release_or_a_candidate() -> None:
    assert (ROOT / "VERSION").read_text() == VERSION + "\n"
    assert FORM.fullmatch(VERSION), VERSION
    assert VERSION == "1.0.0rc1"


@pytest.mark.parametrize("member", MEMBERS)
def test_each_distribution_takes_its_version_from_the_one_file(
    member: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    found = project(member)
    assert "version" not in found
    assert "version" in found["dynamic"]
    module, given = load_setup(member, monkeypatch)
    assert module.ROOT == ROOT
    assert module.FORMATS == ROOT / "formats"
    assert [kw["version"] for kw in given] == [VERSION]
    assert module.version() == VERSION

    with pytest.raises(SystemExit, match=re.escape(str(tmp_path / "VERSION"))):
        module.version(tmp_path)
    (tmp_path / "VERSION").write_text("1.0.0rc1\n1.0.0\n")
    with pytest.raises(SystemExit, match=re.escape(str(tmp_path / "VERSION"))):
        module.version(tmp_path)
    (tmp_path / "VERSION").write_text("\n")
    with pytest.raises(SystemExit, match=re.escape(str(tmp_path / "VERSION"))):
        module.version(tmp_path)
    (tmp_path / "VERSION").write_text(" 2.1.0 \n")
    assert module.version(tmp_path) == "2.1.0"


@pytest.mark.parametrize("member", READERS)
def test_each_reader_requires_the_core_at_its_own_version_within_the_major(member: str) -> None:
    on_core = [entry for entry in project(member)["dependencies"] if re.match(r"fylgja-core\b", entry)]
    assert on_core == [f"fylgja-core>={VERSION},<{int(VERSION.split('.')[0]) + 1}"]


def test_the_example_names_the_core_and_the_readers_without_a_range() -> None:
    dependencies = project("orchestrator")["dependencies"]
    ours = [entry for entry in dependencies if entry.startswith("fylgja-")]
    assert ours == ["fylgja-core", "fylgja-infrahub", "fylgja-netbox"]


PACKAGES = {
    "core": "fylgja_core",
    "readers/infrahub": "fylgja_infrahub",
    "readers/netbox": "fylgja_netbox",
    "orchestrator": "fylgja_orchestrator",
}
VARIABLE = "FYLGJA_BUILD_COMMIT"
HEX = "0" * 40


def git(*argv: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *argv], capture_output=True, text=True, check=True).stdout


def head() -> str:
    """The tree's commit as the build reads it: HEAD, and `-dirty` where git has anything to say of the tree."""
    return git("rev-parse", "HEAD").strip() + ("-dirty" if git("status", "--porcelain").strip() else "")


@pytest.fixture(autouse=True)
def _fresh_build(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """`build` is cached, so each test starts and ends with it empty; asking for `monkeypatch` makes this fixture's
    teardown run after the monkeypatch's undo, with the real `build` back."""
    release.build.cache_clear()
    yield
    monkeypatch.undo()
    release.build.cache_clear()


def test_a_checkouts_build_is_its_version_file_and_its_head() -> None:
    assert release.build("fylgja-core", "fylgja_core") == f"{VERSION} (commit {head()})"
    assert release.version("fylgja-core", "fylgja_core") == VERSION
    assert release.commit("fylgja_core") == head()


def test_a_checkout_with_no_git_says_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATH", "")
    assert release.build("fylgja-core", "fylgja_core") == f"{VERSION} (commit unknown)"


def write_installed(root: Path, *, commit: str | None) -> None:
    package = root / "installed_pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    if commit is not None:
        (package / "COMMIT").write_text(commit + "\n")
    info = root / "installed_pkg-1.2.3.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Metadata-Version: 2.1\nName: installed-pkg\nVersion: 1.2.3\n")


def test_an_installed_package_reads_its_metadata_and_its_commit_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_installed(tmp_path, commit="ab" * 20)
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    assert release.build("installed-pkg", "installed_pkg") == f"1.2.3 (commit {'ab' * 20})"
    (tmp_path / "installed_pkg" / "COMMIT").unlink()
    release.build.cache_clear()
    assert release.build("installed-pkg", "installed_pkg") == "1.2.3 (commit unknown)"


def test_version_prints_the_program_and_the_build_and_exits_0(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    parser = argparse.ArgumentParser(prog="prog")
    release.add_version(parser, "fylgja-core", "fylgja_core")
    with pytest.raises(SystemExit) as stopped:
        parser.parse_args(["--version"])
    assert stopped.value.code == 0
    out, err = capsys.readouterr()
    assert re.fullmatch(rf"prog {re.escape(VERSION)} \(commit ([0-9a-f]{{40}}(-dirty)?|unknown)\)\n", out), out
    assert err == ""


def test_the_build_is_computed_only_for_version(monkeypatch: pytest.MonkeyPatch) -> None:
    def refused(*_: str) -> str:
        raise AssertionError("the build is computed only for --version")

    monkeypatch.setattr(release, "build", refused)
    parser = argparse.ArgumentParser(prog="prog")
    release.add_version(parser, "fylgja-core", "fylgja_core")
    assert parser.parse_args([]) == argparse.Namespace()
    with pytest.raises(AssertionError, match="only for --version"):
        parser.parse_args(["--version"])  # the probe is not blind: the build is asked for here


@pytest.mark.parametrize("member", MEMBERS)
def test_each_build_writes_the_commit_it_was_made_at(
    member: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module, _ = load_setup(member, monkeypatch)
    assert module.COMMIT_VARIABLE == VARIABLE
    assert module.commit({VARIABLE: HEX}, tmp_path) == HEX
    assert module.commit({VARIABLE: HEX + "-dirty"}, tmp_path) == HEX + "-dirty"
    for bad in ("HEAD", HEX.upper().replace("0", "A"), HEX[:-1], HEX + "-clean", " " + HEX):
        with pytest.raises(SystemExit, match=VARIABLE) as refused:
            module.commit({VARIABLE: bad}, tmp_path)
        assert bad.strip() not in str(refused.value), "the value a caller gave reaches the build's log"
    assert module.commit({}, tmp_path) == "unknown"
    assert module.commit({VARIABLE: ""}, tmp_path) == "unknown"
    assert module.commit({}, ROOT) == head()

    monkeypatch.setenv(VARIABLE, HEX)
    step = module.BuildPy()
    step.build_lib = str(tmp_path / "lib")
    step.run()
    assert (tmp_path / "lib" / PACKAGES[member] / "COMMIT").read_text() == HEX + "\n"


def build_core(module: ModuleType, lib: Path) -> None:
    step = module.BuildPy()
    step.build_lib = str(lib)
    step.run()


def test_the_cores_build_ships_each_packages_yaml_and_nothing_else(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module, _ = load_setup("core", monkeypatch)
    assert module.CORE_PACKAGES == ("psp", "probes")
    monkeypatch.setenv(VARIABLE, HEX)
    build_core(module, tmp_path / "lib")
    tracked = git("ls-files", "-z", "psp/*.yaml", "probes/*.yaml").split("\0")[:-1]
    assert tracked
    shipped = tmp_path / "lib" / "fylgja_core" / "shipped"
    carried = sorted(p.relative_to(shipped).as_posix() for p in shipped.rglob("*") if p.is_file())
    assert carried == sorted(tracked)
    for name in tracked:
        assert (shipped / name).read_bytes() == (ROOT / name).read_bytes()

    # a copy with an empty probes/ stops the build, naming the directory
    copy = tmp_path / "copy"
    shutil.copytree(ROOT / "psp", copy / "psp")
    (copy / "probes").mkdir()
    (copy / "probes" / "README.md").write_text("no package here\n")
    monkeypatch.setattr(module, "ROOT", copy)
    with pytest.raises(SystemExit, match=re.escape(str(copy / "probes"))):
        build_core(module, tmp_path / "lib2")


PUBLISHED = ["core", "readers/infrahub", "readers/netbox"]
REPOSITORY = "https://github.com/happypathnetworking/fylgja"
CLASSIFIERS = {
    "Development Status :: 5 - Production/Stable",
    "Environment :: Console",
    "Intended Audience :: System Administrators",
    "Intended Audience :: Telecommunications Industry",
    "Programming Language :: Python :: 3 :: Only",
    "Programming Language :: Python :: 3.14",
    "Topic :: System :: Networking",
    "Typing :: Typed",
}


@pytest.mark.parametrize("member", PUBLISHED)
def test_each_published_distribution_states_its_metadata(member: str) -> None:
    found = project(member)
    documentation = f"{REPOSITORY}/tree/main/docs" if member == "core" else f"{REPOSITORY}/tree/main/{member}"
    assert found["urls"] == {
        "Repository": REPOSITORY,
        "Changelog": f"{REPOSITORY}/blob/main/CHANGELOG.md",
        "Documentation": documentation,
    }
    expected = CLASSIFIERS | ({"Operating System :: POSIX :: Linux"} if member == "core" else set())
    assert len(found["classifiers"]) == len(set(found["classifiers"]))
    assert set(found["classifiers"]) == expected
    assert found["license"] == "Apache-2.0"
    assert found["requires-python"] == ">=3.14"
    assert "authors" not in found and "maintainers" not in found
    if member == "core":
        assert "readme" in found["dynamic"]
        assert "readme" not in found
    else:
        assert found["readme"] == "README.md"


def test_the_example_is_marked_never_to_be_uploaded() -> None:
    found = project("orchestrator")
    assert found["classifiers"] == ["Private :: Do Not Upload"]
    assert "urls" not in found and "authors" not in found and "maintainers" not in found


@pytest.mark.parametrize("member", PUBLISHED)
def test_each_published_build_carries_the_licence(
    member: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    module, given = load_setup(member, monkeypatch)
    monkeypatch.setenv(VARIABLE, HEX)
    step = module.BuildPy()
    step.build_lib = str(tmp_path / "lib")
    step.run()
    assert (tmp_path / "lib" / PACKAGES[member] / "LICENSE").read_bytes() == (ROOT / "LICENSE").read_bytes()
    if member == "core":
        assert given[0]["long_description"] == (ROOT / "README.md").read_text()
        assert given[0]["long_description_content_type"] == "text/markdown"
    else:
        assert "long_description" not in given[0]

    # a build whose root holds the packages but no LICENSE stops, naming the file
    bare = tmp_path / "bare"
    for name in ("psp", "probes"):
        shutil.copytree(ROOT / name, bare / name)
    monkeypatch.setattr(module, "ROOT", bare)
    step = module.BuildPy()
    step.build_lib = str(tmp_path / "lib2")
    with pytest.raises(SystemExit, match=re.escape(str(bare / "LICENSE"))):
        step.run()


def test_the_example_build_is_not_given_the_licence(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module, _ = load_setup("orchestrator", monkeypatch)
    monkeypatch.setenv(VARIABLE, HEX)
    step = module.BuildPy()
    step.build_lib = str(tmp_path / "lib")
    step.run()
    assert not (tmp_path / "lib" / "fylgja_orchestrator" / "LICENSE").exists()


def test_the_changelogs_head_is_the_version() -> None:
    """`CHANGELOG.md` opens with the release the tree is at, `unreleased` or dated, every section of the form."""
    spec = importlib.util.spec_from_file_location("script_publish", ROOT / "scripts" / "publish.py")
    assert spec is not None and spec.loader is not None
    publish = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publish)
    text = (ROOT / "CHANGELOG.md").read_text()
    version, date = publish.head(text)
    assert version == VERSION
    assert date == "unreleased" or re.fullmatch(r"\d{4}-\d{2}-\d{2}", date)
    for line in text.splitlines():
        if line.startswith("## "):
            assert re.fullmatch(r"## \S+ - (unreleased|\d{4}-\d{2}-\d{2})", line), line
