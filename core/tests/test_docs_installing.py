"""`docs/installing.md` holds to the tree: each install line names a published distribution and the extras the core
has, the Python it asks for is the floor every published `pyproject.toml` states, the host's tools are at
`CONTRIBUTING.md`'s versions and the `--version` line is the form the build gives."""

from __future__ import annotations

import re
import shlex
import tomllib

import yaml
from pages import ROOT, blocks, rows, section, text

from fylgja_core import release

PAGE = "docs/installing.md"
PYPROJECTS = ("core", "readers/infrahub", "readers/netbox", "readers/nautobot")


def _project(member: str) -> dict[str, object]:
    project: dict[str, object] = tomllib.loads((ROOT / member / "pyproject.toml").read_text())["project"]
    return project


def _published() -> set[str]:
    return {str(_project(member)["name"]) for member in PYPROJECTS}


def _extras() -> set[str]:
    optional = _project("core")["optional-dependencies"]
    assert isinstance(optional, dict)
    return set(optional) - {"dev"}


def _install_lines(*pages: str) -> list[list[str]]:
    """The arguments of each `pip install` or `uv pip install` line of the `sh` blocks of the page and of `README.md`
    (or of `pages`)."""
    found: list[list[str]] = []
    for page in pages or (PAGE, "README.md"):
        for info, lines in blocks(text(page)):
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


def _wheels(lines: list[str]) -> dict[str, str]:
    """The shell variables the page's `sh` blocks set to one wheel: `name=$(ls dist/<wheel>-*.whl)`, the glob
    expanded by the shell and kept out of the install line."""
    return {m.group(1): m.group(2).replace("_", "-")
            for line in lines if (m := re.fullmatch(r"(\w+)=\$\(ls dist/(fylgja_[a-z]+)-\*\.whl\)", line))}


def _requirement(token: str, wheels: dict[str, str]) -> tuple[str, set[str]]:
    """The distribution and the extras a requirement or a variable holding a wheel names; fails on any other form,
    a `*` among them, which neither uv nor pip expands."""
    assert "*" not in token, f"a glob that reaches the installer cannot install: {token}"
    variable = re.fullmatch(r"\$(\w+)(?:\[([a-z,]+)\])?", token)
    plain = re.fullmatch(r"(fylgja-[a-z]+)(?:\[([a-z,]+)\])?", token)
    if variable and variable.group(1) in wheels:
        name, extras = wheels[variable.group(1)], variable.group(2)
    else:
        assert plain, f"not a requirement the page may give: {token}"
        name, extras = plain.group(1), plain.group(2)
    return name, set(extras.split(",")) if extras else set()


def test_each_install_line_names_a_published_distribution_and_its_extras() -> None:
    wheels = _wheels([line for info, body in blocks(text(PAGE)) if info == "sh" for line in body])
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
            name, extras = _requirement(token, wheels)
            assert name in _published(), f"{name} is no published distribution"
            assert extras <= (_extras() if name == "fylgja-core" else set()), f"{token}: no such extra"
            named.add(name)
            extras_named |= extras
    assert named == _published(), "each distribution is named at least once"
    assert extras_named == _extras(), "each extra is named at least once"
    assert "fylgja-orchestrator" not in text(PAGE), "the orchestrator is not published"


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
    build = release.build("fylgja-core", "fylgja_core")  # one call: the version and the commit are of one reading
    parts = re.fullmatch(r"(\S+) \(commit (.+)\)", build)
    assert parts, build
    shown = found[0][1].replace("<version>", parts.group(1)).replace("<commit>", parts.group(2))
    assert shown == "fylgja-core " + build


def test_a_glob_or_an_unset_variable_is_no_requirement() -> None:
    wheels = {"core": "fylgja-core"}
    assert _requirement("$core[server]", wheels) == ("fylgja-core", {"server"})
    for token in ("dist/fylgja_core-*.whl[server]", "$other"):
        try:
            _requirement(token, wheels)
        except AssertionError:
            continue
        raise AssertionError(f"{token} was accepted")


def test_the_readers_require_the_core_at_the_release_version_below_two_and_the_page_says_so() -> None:
    """The pin is computed from `VERSION`, so a tagging commit that moves the version edits no page: the page says
    "the reader's own version or a later one below 2", and each reader's `pyproject.toml` holds the pin."""
    version = (ROOT / "VERSION").read_text().strip()
    pin = f"fylgja-core>={version},<2"
    for member in PYPROJECTS[1:]:
        assert pin in _project(member)["dependencies"], f"{member} does not require {pin}"  # type: ignore[operator]
    assert "the core at the reader's own version or a later one below 2" in " ".join(text(PAGE).split())


def test_the_uv_the_page_names_is_the_pinned_one() -> None:
    pin = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["uv"]["required-version"]
    named = re.findall(r"uv (\d+\.\d+\.\d+)", text(PAGE))
    assert named, "the parse is blind"
    assert {f"=={v}" for v in named} == {pin}


def test_the_pull_and_the_memory_are_the_srlinux_packages() -> None:
    """The page says to pull the image the package names before the first deploy, and what three nodes want."""
    runtime = yaml.safe_load((ROOT / "psp" / "nokia_srlinux.yaml").read_text())["runtime"]["containerlab"]
    (image,) = [i["ref"] for i in runtime["images"].values()]
    memory = runtime["resources"]["memory_mb"]
    body = text(PAGE)
    shell = [line.strip() for info, lines in blocks(body) if info == "sh" for line in lines]
    assert [line for line in shell if line.startswith("docker pull")] == [f"docker pull {image}"]
    flat = " ".join(body.split())
    assert f"{memory} MiB a node" in flat
    assert f"{3 * memory} MiB" in flat


def test_each_wheel_variable_is_set_before_the_line_that_uses_it() -> None:
    defined: set[str] = set()
    used = 0
    for info, lines in blocks(text(PAGE)):
        if info != "sh":
            continue
        for line in lines:
            defined |= set(_wheels([line]))
            if "install" in line:
                for variable in re.findall(r"\$(\w+)", line):
                    used += 1
                    assert variable in defined, f"${variable} is used before it is set: {line}"
    assert used, "the parse is blind"
