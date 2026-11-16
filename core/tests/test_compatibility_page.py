"""`docs/compatibility.md` holds to the tree: the formats it holds are `formats/`'s files less the example's two, and
the API's document; the commands it holds are the `project.scripts` of the three published `pyproject.toml`; the
example's two formats and its command are under "Not promised", and the enum values a client refuses are the ones
the findings schema closes."""

from __future__ import annotations

import json
import re
import tomllib

from pages import ROOT, prose, section, text

PAGE = "docs/compatibility.md"
PYPROJECTS = ("core", "readers/infrahub", "readers/netbox")
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
    assert len(published) == 4, "the parse is blind"
    held = {m.group(1) for line in section(text(PAGE), "### The commands") if (m := re.match(r"\| `([\w-]+)`", line))}
    assert held == published
    assert "`fylgja-orchestrator`" in _not_promised()
    assert "`fylgja-orchestrator`" not in _held()


def test_the_page_names_the_enums_a_client_refuses_a_new_value_of() -> None:
    schema = json.loads((ROOT / "formats" / "findings-1.schema.json").read_text())
    closed = {"status", "operation", "severity", "wait.outcome", "loss.outcome", "loss.from"}
    body = "\n".join(section(text(PAGE), "## Reading an answer"))
    assert closed <= set(re.findall(r"`([\w.]+)`", body))
    assert {"ok", "rejected"} <= set(schema["properties"]["status"]["enum"]), "the parse is blind"


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
    assert "sets the SR Linux login alone: a blueprint with EOS nodes needs the EOS pair too" in body


def test_no_user_page_says_a_step_reports_loss() -> None:
    """A step lists each probe's flow as not started: it measures no loss."""
    assert "not yet run" in " ".join(text("README.md").split())
    for page in ("README.md", "docs/glossary.md", "docs/installing.md", "docs/cli.md", "docs/api.md"):
        assert not re.search(r"report the loss|reports? (?:the )?loss", text(page)), page
