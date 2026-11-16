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
    assert "readme" in found["dynamic"]
    assert "readme" not in found


def links_module() -> ModuleType:
    """`readme_links.py` at the root, the one definition every published build's `setup.py` loads by path."""
    spec = importlib.util.spec_from_file_location("readme_links_under_test", ROOT / "readme_links.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TAG = "https://github.com/happypathnetworking/fylgja/blob/v1.0.0rc1/"
RAW = "https://github.com/happypathnetworking/fylgja/raw/v1.0.0rc1/"


def test_a_readmes_links_are_written_absolute_under_the_tagged_tree() -> None:
    links = links_module()
    text = (
        "# T\n\n[a](x.md#y) and [b](#y) and [c](https://example.org/z) and [d](../../design/w.md#v)\n\n"
        "[ref]: sub/r.md\n[abs]: https://example.org/r\n\n"
        "```sh\n[e](in-fence.md)\n[g]: in-fence.md\n```\n\n"
        "````sh\n~~~\n[h](after-tilde.md)\n````\n\n"
        "and `[f](in-code.md)` and ![i](img/i.png) and [j](sub/)\n"
    )
    assert links.readme_text(text, "readers/infrahub", "1.0.0rc1") == (
        "# T\n\n"
        f"[a]({TAG}readers/infrahub/x.md#y) and [b]({TAG}readers/infrahub/README.md#y) and "
        f"[c](https://example.org/z) and [d]({TAG}design/w.md#v)\n\n"
        f"[ref]: {TAG}readers/infrahub/sub/r.md\n[abs]: https://example.org/r\n\n"
        "```sh\n[e](in-fence.md)\n[g]: in-fence.md\n```\n\n"
        "````sh\n~~~\n[h](after-tilde.md)\n````\n\n"
        f"and `[f](in-code.md)` and ![i]({RAW}readers/infrahub/img/i.png) and [j]({TAG}readers/infrahub/sub)\n"
    )
    root = links.readme_text("[a](docs/x.md) [b](#y)\n", "", "1.0.0rc1")
    assert root == f"[a]({TAG}docs/x.md) [b]({TAG}README.md#y)\n"
    with pytest.raises(ValueError, match="above the root"):
        links.readme_text("[a](../../../x.md)\n", "readers/infrahub", "1.0.0rc1")


def test_a_network_path_and_a_one_letter_scheme_are_absolute_and_left_as_they_are() -> None:
    text = "[a](//cdn.example/x.js) and [b](c:/x.md)\n\n[ref]: //cdn.example/r\n"
    assert links_module().readme_text(text, "readers/infrahub", "1.0.0rc1") == text


@pytest.mark.parametrize("member", PUBLISHED)
def test_every_published_readme_is_rewritten_and_each_target_is_a_file_of_the_tree(member: str) -> None:
    links = links_module()
    made = links.readme(ROOT, member if member != "core" else "", VERSION)
    body = re.sub(r"^(?P<f>```|~~~).*?^(?P=f)[^\n]*$", "", made, flags=re.M | re.S)
    body = re.sub(r"`[^`\n]*`", "", body)
    found = re.findall(r"\]\(([^)\s]+)", body) + re.findall(r"^\[[^\]]+\]:\s*(\S+)", body, re.M)
    assert len(found) > 3, "the parse is blind"
    for target in found:
        assert re.match(r"[a-z][a-z0-9+.-]*:", target), target
        for kind in ("blob", "raw"):
            prefix = f"https://github.com/happypathnetworking/fylgja/{kind}/v{VERSION}/"
            if target.startswith(prefix):
                assert (ROOT / target.removeprefix(prefix).split("#")[0]).is_file(), target


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
    directory = "" if member == "core" else member
    assert given[0]["long_description"] == links_module().readme(ROOT, directory, VERSION)
    assert given[0]["long_description"] != (ROOT / directory / "README.md").read_text()
    assert given[0]["long_description_content_type"] == "text/markdown"

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


def _wheels_recipe() -> list[str]:
    """The recipe of `make wheels`, its lines without the leading tab."""
    lines = (ROOT / "Makefile").read_text().splitlines()
    start = lines.index("wheels:") + 1
    end = next(i for i in range(start, len(lines)) if not lines[i].startswith("\t"))
    return [line[1:] for line in lines[start:end]]


def test_make_wheels_removes_each_members_build_directory_first() -> None:
    recipe = _wheels_recipe()
    (build,) = [i for i, line in enumerate(recipe) if "uv build" in line]
    removed = [line for line in recipe[:build] if line.startswith("rm -rf ")]
    assert removed, recipe
    gone = {word for line in removed for word in line.split()[2:]}
    assert {"dist", "core/build", "readers/infrahub/build", "readers/netbox/build"} <= gone


def test_make_wheels_builds_with_the_setuptools_the_build_constraints_name() -> None:
    (build,) = [line for line in _wheels_recipe() if "uv build" in line]
    assert "--build-constraints build-constraints.txt" in build
    lines = [line.strip() for line in (ROOT / "build-constraints.txt").read_text().splitlines()]
    assert [line for line in lines if line and not line.startswith("#")] == ["setuptools==84.2.1"]
    # Each published member's backend allows the pinned version.
    for member in ("core", "readers/infrahub", "readers/netbox"):
        with (ROOT / member / "pyproject.toml").open("rb") as f:
            assert tomllib.load(f)["build-system"]["requires"] == ["setuptools>=80"], member


# Every bold title of "Open questions" (design/decisions.md), as the start of its text, and where the notes put it: a
# known limit, which the notes' "Known limits" list states with a phrase of its own, the one line after the list
# that names the questions of the example and the tooling and promises none, or answered by a change and left out.
LIMITS = {
    "A drain at the packages' requests": "A drain of a cluster host",
    "The node clients under larger twins": "The connections the core opens to the nodes",
    "A condition carrying the last verify's status": "`Ready` condition",
    "A holder that outlives its Lease under a slow store": "A core that holds the Lease",
    "The release on a Conflict": "A core that releases the Lease",
    "A cEOS node with no data link refuses `ip routing`": "A cEOS node with no data link",
    "What a read of Infrahub costs as an instance's history grows": "A read of Infrahub cost more",
    "What the stale rule does not yet rest on a reading of": "The reader's stale rule",
    "A row of the changelog that commits below a higher one": "NetBox may commit a row",
    "A `view` grant with constraints, under the reader": "A `view` grant of NetBox",
    "No rule of verify reads an address": "No rule of verify reads an address",
    "A mark through another core": "A mark made through one core",
}
NAMED = {
    "The size of the twin the many-twins scenario expects refused": "forty-node twin",
    "A check on a task worker that lacks its branch's commit": "task worker's clone",
    "A registration read from GitHub": "registration read from GitHub",
    "Infrahub on volumes kept for days": "Infrahub on volumes kept for days",
    "The cluster's rehearsal against the local driver's": "rehearsal time",
    "Prefect's credential in NetBox's changelog": "Prefect's credential",
    "Authoring a change of several steps in NetBox": "authoring a change of several steps",
    "Three small gaps the last plan left": "three small gaps",
    "`make netbox-up` where the network cannot be inspected": "`make netbox-up`'s network",
}
ANSWERED = {
    "A core test whose margin is the host's load",  # the deploys' order is held by the test, the margin gone
}


def open_question_titles() -> list[str]:
    """The bold lead of each item of "Open questions", whitespace folded to one space."""
    text = (ROOT / "design" / "decisions.md").read_text()
    section = text[text.index("\n## Open questions\n") :]
    return [" ".join(m.split()) for m in re.findall(r"^- \*\*(.+?)\*\*", section, re.M | re.S)]


def test_every_open_question_is_a_known_limit_or_named() -> None:
    titles = open_question_titles()
    assert len(titles) > 10, "the parse is blind"
    changelog = (ROOT / "CHANGELOG.md").read_text()
    head = changelog[changelog.index("\n## ") :]
    limits = head[head.index("\n### Known limits\n") :]
    listed, _, after = limits.partition("\n\nThe example's, ")
    assert after, "the line naming the example's, the suites' and the tooling's questions is missing"
    assert "design/decisions.md#open-questions" in after.replace("\n", " ")
    bullets = [" ".join(b.split()) for b in re.split(r"\n- ", listed)[1:]]
    # a limit that has an open question carries the link to where they are kept
    for phrase in LIMITS.values():
        found = [b for b in bullets if phrase in b]
        assert len(found) == 1, f"{phrase!r} is not one known limit of the notes"
        assert "[oq]" in found[0], found[0]
    assert re.search(r"^\[oq\]: design/decisions\.md#open-questions$", limits, re.M)
    line = " ".join(after.split())
    for title in titles:
        starts = [k for k in {**LIMITS, **NAMED} if title.startswith(k)]
        assert len(starts) == 1 or title in ANSWERED or any(title.startswith(a) for a in ANSWERED), (
            f"the open question {title!r} is neither a known limit, named in the one line, nor answered"
        )
        if starts and starts[0] in NAMED:
            assert NAMED[starts[0]] in line, f"{NAMED[starts[0]]!r} is not named in the one line"
    for key in LIMITS.keys() | NAMED.keys():
        assert any(t.startswith(key) for t in titles), f"{key!r} is no longer an open question: say where it went"
