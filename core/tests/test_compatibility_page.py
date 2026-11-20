"""`docs/compatibility.md` holds to the tree: the formats it holds are `formats/`'s files less the example's two, and
the API's document; the commands it holds are the `project.scripts` of the four published `pyproject.toml`; the
example's two formats and its command are under "Not promised", and the enum values a client refuses are the ones
the findings schema closes."""

from __future__ import annotations

import json
import re
import tomllib

from pages import ROOT, USER_PAGES, prose, section, text

PAGE = "docs/compatibility.md"
PYPROJECTS = ("core", "readers/infrahub", "readers/netbox", "readers/nautobot")
EXAMPLES = {"plan-1.schema.json", "rehearsal-1.schema.json"}


def _held() -> str:
    return "\n".join(section(text(PAGE), "## What is held"))


def _not_promised() -> str:
    return "\n".join(section(text(PAGE), "## Not promised"))


def _formats(body: str) -> set[str]:
    return set(re.findall(r"\]\(\.\./formats/([\w.-]+\.(?:schema\.json|openapi\.yaml))\)", body))


def test_the_page_holds_every_format_but_the_examples() -> None:
    files = {path.name for path in (ROOT / "formats").glob("*.schema.json")} | {"api-1.openapi.yaml"}
    assert len(files) > 10, "the parse is blind"
    assert _formats(_held()) == files - EXAMPLES
    assert _formats(_not_promised()) == EXAMPLES


def test_the_page_holds_the_published_commands() -> None:
    published: set[str] = set()
    for member in PYPROJECTS:
        project = tomllib.loads((ROOT / member / "pyproject.toml").read_text())["project"]
        published |= set(project["scripts"])
    assert len(published) == 5, "the parse is blind"
    held = {m.group(1) for line in section(text(PAGE), "### The commands") if (m := re.match(r"\| `([\w-]+)`", line))}
    assert held == published
    assert "`fylgja-orchestrator`" in _not_promised()
    assert "`fylgja-orchestrator`" not in _held()


def test_the_page_holds_each_published_readers_settings_and_library() -> None:
    """Each reader's README is linked under "The settings" at its command and under "The Python names" at its library,
    and that README's "## The command" names a `FYLGJA_` variable and its "## The library" is there."""
    settings = "\n".join(section(text(PAGE), "### The settings"))
    names = "\n".join(section(text(PAGE), "### The Python names"))
    readers = [member for member in PYPROJECTS if member != "core"]
    assert len(readers) == 3, "the parse is blind"
    for member in readers:
        link = f"../{member}/README.md"
        assert f"]({link}#the-command)" in settings, member
        assert f"]({link}#the-library)" in names, member
        readme = text(f"{member}/README.md")
        assert re.search(r"`FYLGJA_\w+`", "\n".join(section(readme, "## The command"))), member
        assert "## The library" in readme.splitlines(), member


def test_the_nautobot_readers_rows_are_marked_from_1_1_0() -> None:
    rows = [line for line in _held().splitlines() if line.startswith("|") and "nautobot" in line.lower()]
    assert len(rows) == 2, "the parse is blind"
    assert all("from 1.1.0" in row for row in rows), rows
    for heading in ("### The settings", "### The Python names"):
        body = " ".join("\n".join(section(text(PAGE), heading)).split())
        assert "from 1.1.0, [the Nautobot reader's](../readers/nautobot/README.md#the-" in body, heading
    assert "nautobot" not in _not_promised().lower()


def _enums(node: object, path: tuple[str, ...] = ()) -> set[str]:
    """The name the page gives each `enum` under `node`: its property's name, prefixed by `wait` or `loss` for the
    members of those two objects."""
    found: set[str] = set()
    if isinstance(node, dict):
        if "enum" in node and len(path) >= 2 and path[-2] == "properties":
            owner = path[-3] if len(path) >= 3 else ""
            found.add(f"{owner}.{path[-1]}" if owner in {"wait", "loss"} else path[-1])
        for key, value in node.items():
            found |= _enums(value, (*path, key))
    return found


def test_the_page_names_the_enums_a_client_refuses_a_new_value_of() -> None:
    """The names in the page's sentence are the enums of `findings-1` and `problem-1`, walked: no name is typed here."""
    closed: set[str] = set()
    for name in ("findings", "problem"):
        closed |= _enums(json.loads((ROOT / "formats" / f"{name}-1.schema.json").read_text()))
    assert len(closed) == 6, "the parse is blind"
    body = "\n".join(section(text(PAGE), "## Reading an answer"))
    sentence = next(p for p in body.split("\n\n") if "waits for a major release" in p)
    assert set(re.findall(r"`([\w.]+)`", " ".join(sentence.split()))) == closed


def test_each_page_that_speaks_of_what_it_holds_links_the_page() -> None:
    for page in ("docs/cli.md", "docs/server.md", "docs/api.md", "docs/client.md", "docs/README.md", "README.md"):
        body = "\n".join(prose(text(page)))
        assert re.search(r"\]\((?:\.\./|docs/)?compatibility\.md[)#]", body), page


def test_the_changelog_points_what_1_0_holds_at_the_page() -> None:
    body = text("CHANGELOG.md")
    assert "](docs/compatibility.md)" in body
    assert "decisions.md#d-105" not in body


def test_the_pull_request_template_says_a_held_format_only_adds() -> None:
    assert "its version is still 1, and the change only adds" in text(".github/PULL_REQUEST_TEMPLATE.md")


def test_the_server_page_says_the_packages_words_for_eos_and_that_the_start_sets_sr_linux_alone() -> None:
    body = " ".join(text("docs/server.md").split())
    assert "the kind's default login" in body and "the login the imported image accepts" not in body
    assert "the [kind](glossary.md) being containerlab's `ceos`" in body
    assert "sets the SR Linux login alone: a blueprint with EOS nodes needs the EOS pair too" in body


def test_no_user_page_says_a_step_reports_loss() -> None:
    """A step lists each probe's flow as not started: it measures no loss."""
    assert "not yet run" in " ".join(text("README.md").split())
    pages = (*USER_PAGES, "readers/infrahub/README.md", "readers/netbox/README.md")
    for page in pages:
        assert not re.search(r"reports? (?:the )?loss|loss a step caused|measures? (?:the )?loss", text(page)), page


def test_the_page_words_the_cores_floor_as_the_installing_page_does() -> None:
    body = " ".join(text(PAGE).split())
    assert "the core at the reader's own version or a later one below 2" in body
    assert "fylgja-core>=" not in body, "a pin typed on the page goes stale at the tag"
