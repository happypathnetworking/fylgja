"""`docs/cli.md` holds to the CLI: its `Command` table names each of the parser's commands with its options, its
`Variable` table the variables the CLI reads, its `Status` table the exit statuses it has, each compared with the code
as sets, both ways; and each example is what the CLI prints over the fake API 1 server, line for line. No example
is typed by hand and left unheld: a change to the CLI's text fails here until the page says it."""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Callable
from typing import Any

import pytest
from fake_api import (
    _PLATFORMS,
    _PROBES,
    ADDRESS,
    BLUEPRINT_ID,
    BUNDLE_ID,
    CAPACITY,
    DEPLOYMENT,
    DESTROY_RUN_ID,
    PUSH_REFUSED,
    RUN_ID,
    TOKEN,
    FakeAPI,
    check_component,
    ok,
    record,
    run,
    verification,
    watch,
)
from fake_api import NODES as FAKE_NODES
from pages import ROOT, blocks, flags, options, rows, section, statuses, text, ticked

from fylgja_core import blueprint, cli, compiler

PAGE = "docs/cli.md"
TWIN = "demo"
"""The twin every example names, as its command line does; the fake's documents are renamed to it."""
PROBED_FILE = ROOT / "testdata" / "blueprint" / "three-node-probed.json"
PROBED = json.loads(PROBED_FILE.read_text())
PROBED_BLUEPRINT_ID = blueprint.blueprint_id(PROBED)
PROBED_ID = compiler.compile(blueprint.decode(PROBED), _PLATFORMS, _PROBES).id
"""The compiled id of `three-node-probed.json`: the bundle the dry-run step goes to and the diff ends at."""
NODES = [
    {**FAKE_NODES[0], "address": "192.0.2.11"},
    {**FAKE_NODES[1], "address": "192.0.2.12"},
    {**FAKE_NODES[2], "address": "192.0.2.13"},
]
"""The fake's three nodes, each with an address in 192.0.2.0/24 and the second reached by `bastion.example`."""


def _commands() -> dict[tuple[str, ...], frozenset[str]]:
    """The `Command` table as the paths its first cells name and the options its second cells name."""
    found: dict[tuple[str, ...], frozenset[str]] = {}
    for row in rows(section(text(PAGE), "## Commands"), "Command"):
        words = ticked(row[0])[0].split()[1:]
        path: list[str] = []
        for word in words:
            if word.isupper():
                break
            path.append(word)
        found[tuple(path)] = frozenset(flags(row[1]))
    return found


def test_the_page_names_every_command_and_each_its_options() -> None:
    """A noun with verbs under it is no command, so it has no row; the root has one."""
    held = options(cli._parser())
    leaves = {path: longs for path, longs in held.items()
              if not path or not any(other[:len(path)] == path and other != path for other in held)}
    found = _commands()
    assert len(found) > 1, "the parse is blind"
    assert found == leaves
    nodes = {path: longs for path, longs in held.items() if path and path not in leaves}
    assert nodes, "the parse is blind"
    assert all(not longs for longs in nodes.values()), "a noun's option has no row until it is listed"
    assert found[()] == {"--json", "--version"}
    assert len(found) == 15, "the root and fourteen commands"


def test_the_page_names_the_variables_the_cli_reads() -> None:
    found = {ticked(row[0])[0] for row in rows(section(text(PAGE), "## Before a command"), "Variable")}
    assert found, "the parse is blind"
    assert found == {cli.ADDRESS, cli.TOKEN, cli.CA}


def test_the_page_names_the_exit_statuses_the_cli_has() -> None:
    found = statuses(section(text(PAGE), "## Exit statuses"))
    assert found, "the parse is blind"
    assert found == set(cli.EXIT.values()) | {cli.EXIT_FAILURE}


def test_the_json_section_names_every_command_that_takes_json() -> None:
    """The list of what `--json` prints gives each leaf command that takes it, by its words."""
    held = options(cli._parser())
    body = " ".join(section(text(PAGE), "### Waiting and printing"))
    body = re.sub(r"\s+", " ", body)
    leaves = [path for path, longs in held.items() if path and "--json" in longs]
    assert len(leaves) >= 10, "the parse is blind"
    for path in leaves:
        assert f"`{' '.join(path)}" in body, f"`--json`'s list lacks {' '.join(path)}"


# The examples: each fake answers one command as a server would, the twin named `demo`.


def _renamed(doc: Any) -> Any:
    """A document of the fake's three-node twin, naming `demo` and its subjects' twin the same, and its run asked by
    `operator`, not by the fake's person's name."""
    return json.loads(json.dumps(doc).replace('"three-node"', f'"{TWIN}"').replace('"alice"', '"operator"'))


def _twin(*, revision: int = 1, generation: int = 1, observed: int = 0, **extra: Any) -> dict[str, Any]:
    doc: dict[str, Any] = _renamed(record(revision, generation, observed, **extra))
    if "nodes" in doc["status"] and doc["status"]["nodes"]:
        doc["status"]["nodes"] = NODES
    return doc


def _ready() -> dict[str, Any]:
    return _twin(revision=4, generation=1, observed=1, phase="pushed", ready=("True", None), nodes=True)


def _create() -> FakeAPI:
    path = f"/v1/twins/{TWIN}"
    created = {"Location": path, "ETag": '"1"'}
    return (
        FakeAPI()
        .on("POST", "/v1/blueprints", ok({"id": BLUEPRINT_ID}, 201, {"Location": f"/v1/blueprints/{BLUEPRINT_ID}"}))
        .on("PUT", path, ok(_twin(run_id=RUN_ID), 201, created))
        .on("GET", path, watch(_twin(revision=2, phase="compiled", run_id=RUN_ID),
                               _twin(revision=3, phase="pushed", run_id=RUN_ID), _ready()))
        .on("GET", f"/v1/runs/{RUN_ID}", ok(_renamed(run())))
    )


def _show() -> FakeAPI:
    return FakeAPI().on("GET", f"/v1/twins/{TWIN}", ok(_ready(), headers={"ETag": '"4"'}))


def _step_dry_run() -> FakeAPI:
    plan: dict[str, Any] = {
        "deployment": DEPLOYMENT,
        "verdict": {"findings_version": "1", "operation": "plan", "status": "ok",
                    "subject": {"twin": TWIN, "bundle_id": PROBED_ID, "deployment_id": DEPLOYMENT["id"]},
                    "findings": []},
        "changes": {"nodes": [{"node": n, "action": "kept", "reasons": []} for n in ("n1", "n2", "n3")],
                    "links_added": [], "links_removed": []},
    }
    check_component("Plan", plan)
    return (
        FakeAPI()
        .on("POST", "/v1/blueprints",
            ok({"id": PROBED_BLUEPRINT_ID}, 201, {"Location": f"/v1/blueprints/{PROBED_BLUEPRINT_ID}"}))
        .on("PUT", f"/v1/twins/{TWIN}", ok(plan))
    )


def _verify() -> FakeAPI:
    return FakeAPI().on("POST", f"/v1/twins/{TWIN}/verifications", ok(_renamed(verification())))


def _capacity() -> FakeAPI:
    return FakeAPI().on("GET", "/v1/capacity", ok(CAPACITY))


def _diff() -> FakeAPI:
    doc: dict[str, Any] = {
        "from": BUNDLE_ID, "to": PROBED_ID, "unchanged": False,
        "nodes": {"added": [], "removed": [], "changed": []},
        "links": {"added": [], "removed": []},
        "probes": {"added": ["n1-loop"], "removed": []},
    }
    return FakeAPI().on("GET", f"/v1/bundles/{BUNDLE_ID}/diff/{PROBED_ID}", ok(doc))


def _destroy() -> FakeAPI:
    path = f"/v1/twins/{TWIN}"
    return (
        FakeAPI()
        .on("DELETE", path, ok(_twin(revision=5, generation=2, observed=1, deleting=True, run_id=DESTROY_RUN_ID), 202))
        .on("GET", path, watch(_twin(revision=6, generation=2, observed=1, deleting=True, phase="destroyed",
                                     run_id=DESTROY_RUN_ID), deleted=True))
        .on("GET", f"/v1/runs/{DESTROY_RUN_ID}", ok(_renamed(run("destroy", run_id=DESTROY_RUN_ID))))
    )


EXAMPLES: dict[str, Callable[[], FakeAPI]] = {
    "fylgja-core capacity show": _capacity,
    f"fylgja-core twin create {TWIN} --blueprint testdata/blueprint/three-node.json": _create,
    f"fylgja-core twin show {TWIN}": _show,
    f"fylgja-core twin step {TWIN} --blueprint testdata/blueprint/three-node-probed.json --dry-run": _step_dry_run,
    f"fylgja-core twin verify {TWIN}": _verify,
    f"fylgja-core bundle diff {BUNDLE_ID} {PROBED_ID}": _diff,
    f"fylgja-core twin destroy {TWIN}": _destroy,
}
"""Each console command of the page, as its line gives it, and the fake that answers it. The `FakeAPI` holds each
request and answer to the OpenAPI document, so what the CLI prints is what a server that kept API 1 would have it
print."""


def _consoles() -> dict[str, list[str]]:
    """Each `console` block of the page: its command line after `$ ` and its other lines."""
    found: dict[str, list[str]] = {}
    for info, lines in blocks(text(PAGE)):
        if info == "console":
            assert lines[0].startswith("$ "), lines[0]
            found[lines[0][2:]] = lines[1:]
    return found


def test_each_example_prints_what_the_page_shows(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    shown = _consoles()
    assert shown, "the parse is blind"
    assert set(shown) == set(EXAMPLES)
    monkeypatch.chdir(ROOT)
    monkeypatch.setenv(cli.ADDRESS, ADDRESS)
    monkeypatch.setenv(cli.TOKEN, TOKEN)
    monkeypatch.delenv(cli.CA, raising=False)
    progress: list[str] = []
    for line, fake in EXAMPLES.items():
        api = fake()
        code = cli.main(shlex.split(line)[1:], transport=api.transport, sleep=lambda s: None)
        captured = capsys.readouterr()
        assert captured.out.splitlines() == shown[line], line
        assert code == 0, line
        assert api.failures == [], line
        progress += captured.err.splitlines()
    prose = section(text(PAGE), "## Examples")
    spans = ticked("\n".join(prose[max(k for k, line in enumerate(prose) if line.startswith("```")) + 1:]))
    named = [span for span in spans if re.fullmatch(TWIN + r": \w+", span)]
    assert named, "the parse is blind"
    assert progress == named, "the progress lines on stderr are the ones the page names, in order"


def test_the_examples_keep_to_the_documentation_ranges() -> None:
    """Every address a page shows is in 192.0.2.0/24 or is the loopback address, every access name is `*.example`."""
    assert PUSH_REFUSED, "the parse is blind"
    body = "\n".join(line for _, lines in blocks(text(PAGE)) for line in lines)
    for address in re.findall(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", body):
        assert address.startswith(("192.0.2.", "127.0.0.1")), address
    for host in re.findall(r"\bvia (\S+)", body):
        assert host.endswith(".example"), host
