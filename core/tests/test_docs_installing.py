"""`docs/installing.md` holds to the tree: each install line names a published distribution and the extras the core
has, the Python it asks for is the floor every published `pyproject.toml` states, the host's tools are at
`CONTRIBUTING.md`'s versions and the `--version` line is the form the build gives."""

from __future__ import annotations

import re
import shlex
import tomllib

from pages import ROOT, blocks, rows, section, text

from fylgja_core import release

PAGE = "docs/installing.md"
PYPROJECTS = ("core", "readers/infrahub", "readers/netbox")


def _project(member: str) -> dict[str, object]:
    project: dict[str, object] = tomllib.loads((ROOT / member / "pyproject.toml").read_text())["project"]
    return project


def _published() -> set[str]:
    return {str(_project(member)["name"]) for member in PYPROJECTS}


def _extras() -> set[str]:
    optional = _project("core")["optional-dependencies"]
    assert isinstance(optional, dict)
    return set(optional) - {"dev"}


def _install_lines() -> list[list[str]]:
    """The requirements of each `pip install` or `uv pip install` line of the page's `sh` blocks."""
    found: list[list[str]] = []
    for info, lines in blocks(text(PAGE)):
        if info != "sh":
            continue
        for line in lines:
            argv = shlex.split(line.split("#")[0])
            if not argv:
                continue
            pip = argv[0].rsplit("/", 1)[-1] == "pip" and argv[1:2] == ["install"]
            if pip or argv[:3] == ["uv", "pip", "install"]:
                found.append(argv)
    return found


def _requirement(token: str) -> tuple[str, set[str]]:
    """The distribution and the extras a requirement or a wheel path names; fails on any other form."""
    wheel = re.fullmatch(r"dist/(fylgja_[a-z]+)-[^/]*\.whl(?:\[([a-z,]+)\])?", token)
    if wheel:
        name, extras = wheel.group(1).replace("_", "-"), wheel.group(2)
    else:
        plain = re.fullmatch(r"(fylgja-[a-z]+)(?:\[([a-z,]+)\])?", token)
        assert plain, f"not a requirement the page may give: {token}"
        name, extras = plain.group(1), plain.group(2)
    return name, set(extras.split(",")) if extras else set()


def test_each_install_line_names_a_published_distribution_and_its_extras() -> None:
    lines = _install_lines()
    assert lines, "the parse is blind"
    named: set[str] = set()
    extras_named: set[str] = set()
    for argv in lines:
        assert not any("index-url" in a or "==" in a for a in argv), f"an index or a pin: {argv}"
        rest = argv[argv.index("install") + 1:]
        requirements = [a for k, a in enumerate(rest) if not a.startswith("-") and rest[k - 1:k] != ["--python"]]
        assert requirements, f"nothing to install: {argv}"
        for token in requirements:
            name, extras = _requirement(token)
            assert name in _published(), f"{name} is no published distribution"
            assert extras <= (_extras() if name == "fylgja-core" else set()), f"{token}: no such extra"
            named.add(name)
            extras_named |= extras
    assert named == _published(), "each distribution is named at least once"
    assert extras_named == _extras(), "each extra is named at least once"
    assert "fylgja-orchestrator" not in text(PAGE).replace("pip install", ""), "the orchestrator is not published"


def test_the_python_the_page_asks_for_is_the_floor() -> None:
    asked = set(re.findall(r"Python (3\.\d+)", text(PAGE)))
    assert asked, "the parse is blind"
    floors = {str(_project(member)["requires-python"]) for member in PYPROJECTS}
    assert len(floors) == 1, "the published builds state one floor"
    assert {f">={version}" for version in asked} == floors


def test_the_hosts_tools_are_at_contributings_versions() -> None:
    table = rows(section(text("CONTRIBUTING.md"), "## Tooling"), "Tool")
    row = next((r for r in table if r[0] == "containerlab, Docker"), None)
    assert row is not None, "the parse is blind"
    containerlab, docker = (v.strip() for v in row[1].split(","))
    body = text(PAGE)
    assert re.findall(r"containerlab (\d+\.\d+\.\d+)", body) == [containerlab]
    assert re.findall(r"Docker (\d+\.\d+\.\d+)", body) == [docker]


def test_the_version_line_is_the_builds_form() -> None:
    consoles = [lines for info, lines in blocks(text(PAGE)) if info == "console"]
    found = [lines for lines in consoles if lines[:1] == ["$ fylgja-core --version"]]
    assert len(found) == 1, "the parse is blind"
    assert len(found[0]) == 2
    shown = found[0][1].replace("<version>", release.version("fylgja-core", "fylgja_core"))
    shown = shown.replace("<commit>", release.commit("fylgja_core"))
    assert shown == "fylgja-core " + release.build("fylgja-core", "fylgja_core")
