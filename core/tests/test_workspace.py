"""The uv workspace and its lock (D-108): the root `pyproject.toml` is uv's tables alone and names the four
distributions as members; `uv.lock` holds them editable at their versions and each exact pin of theirs at that
version, so the pins stay the statement the lock is checked against (`uv sync --locked` checks the rest); and
`make venv` is a locked sync into `core/.venv`."""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
MEMBERS = ["core", "readers/infrahub", "readers/netbox", "orchestrator"]
NAMES = {
    "core": "fylgja-core",
    "readers/infrahub": "fylgja-infrahub",
    "readers/netbox": "fylgja-netbox",
    "orchestrator": "fylgja-orchestrator",
}
PINNED = re.compile(r"^([A-Za-z0-9._-]+)==([^\s;,]+)$")


def load(path: str) -> dict[str, Any]:
    with (ROOT / path).open("rb") as f:
        return tomllib.load(f)


def normalised(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


UV_VERSION = load("pyproject.toml")["tool"]["uv"]["required-version"].removeprefix("==")


def test_the_root_is_a_workspace_of_the_four_and_no_distribution() -> None:
    root = load("pyproject.toml")
    assert list(root) == ["tool"]
    assert list(root["tool"]) == ["uv"]
    uv = root["tool"]["uv"]
    assert re.fullmatch(r"==\d+\.\d+\.\d+", uv["required-version"])
    assert uv["python-downloads"] == "never"
    assert uv["workspace"] == {"members": MEMBERS}
    assert uv["sources"] == {name: {"workspace": True} for name in ("fylgja-core", "fylgja-infrahub", "fylgja-netbox")}
    assert set(uv) == {"required-version", "python-downloads", "workspace", "sources"}
    for member in MEMBERS:
        assert load(f"{member}/pyproject.toml")["project"]["name"] == NAMES[member]
    for tests in ("infrahub", "netbox"):
        assert "project" not in load(f"{tests}/pyproject.toml")


def packages() -> dict[str, list[dict[str, Any]]]:
    found: dict[str, list[dict[str, Any]]] = {}
    for entry in load("uv.lock")["package"]:
        found.setdefault(normalised(entry["name"]), []).append(entry)
    return found


def test_the_lock_holds_the_four_editable_at_their_versions() -> None:
    locked = packages()
    for member in MEMBERS:
        name = NAMES[member]
        (entry,) = locked[name]
        assert entry["source"] == {"editable": member}
        assert entry["version"] == load(f"{member}/pyproject.toml")["project"]["version"]


def test_each_exact_pin_is_the_locks_version() -> None:
    locked = packages()
    found = 0
    for member in MEMBERS:
        project = load(f"{member}/pyproject.toml")["project"]
        extras = project.get("optional-dependencies", {})
        entries = [*project.get("dependencies", []), *(entry for extra in extras.values() for entry in extra)]
        for entry in entries:
            pin = PINNED.match(entry)
            if pin is None:
                continue
            found += 1
            versions = locked[normalised(pin[1])]
            assert [v["version"] for v in versions] == [pin[2]], f"{member}: {entry}"
    assert found == 30


def test_venv_is_a_locked_sync_into_core_venv() -> None:
    dry = subprocess.run(["make", "-n", "venv"], cwd=ROOT, capture_output=True, text=True, check=True)
    lines = dry.stdout.splitlines()
    sync = [line for line in lines if "uv sync" in line]
    assert len(sync) == 1
    assert f"UV_PROJECT_ENVIRONMENT={ROOT}/core/.venv" in sync[0]
    assert "uv sync --locked --all-packages --all-extras --python python3" in sync[0]
    assert not [line for line in lines if "pip" in line]


def test_ci_installs_the_trees_uv_before_make_venv() -> None:
    workflow_text = (ROOT / ".github/workflows/ci.yml").read_text()
    workflow = yaml.safe_load(workflow_text)
    jobs = workflow["jobs"]
    assert set(jobs) == {"lint-and-test", "image"}
    steps = jobs["lint-and-test"]["steps"]
    uses = [step.get("uses", "") for step in steps]
    (python,) = [i for i, name in enumerate(uses) if name.startswith("actions/setup-python@")]
    (setup,) = [i for i, name in enumerate(uses) if name.startswith("astral-sh/setup-uv@")]
    (venv,) = [i for i, step in enumerate(steps) if step.get("run") == "make venv"]
    assert python < setup < venv
    assert steps[python]["with"] == {"python-version": "3.14"}
    assert re.fullmatch(r"astral-sh/setup-uv@[0-9a-f]{40}", steps[setup]["uses"])
    assert re.search(rf"uses: {re.escape(steps[setup]['uses'])} # v\d+\.\d+\.\d+$", workflow_text, re.MULTILINE)
    assert steps[setup]["with"] == {"version": UV_VERSION}
    assert not [step for step in jobs["image"]["steps"] if "setup-uv" in step.get("uses", "")]


# What calls pip or makes a venv by anything but uv: `pip install` and its kin not led by `uv `, `python -m pip`,
# `-m venv`, a call of an environment's `bin/pip`, and the same two as the words of an argument list.
PIP_OR_VENV = {
    "pip as a command": re.compile(r"(?<!uv )\bpip (install|wheel|download|freeze)\b"),
    "-m pip": re.compile(r"-m pip\b"),
    "bin/pip": re.compile(r"/bin/pip\b"),
    "-m venv": re.compile(r"-m venv\b"),
    "an argument list's pip or venv": re.compile(r'"-m",\s*"(pip|venv)"'),
}
PIP_OR_VENV_EXAMPLES = {
    "pip as a command": "\t$(VENV)/bin/pip install -q thing",
    "-m pip": "    python3 -m pip install thing",
    "bin/pip": "ENV=/opt/venv/bin/pip",
    "-m venv": "\tpython3 -m venv $(LOCAL)/x",
    "an argument list's pip or venv": 'run(["python3", "-m", "venv", "x"])',
}


def test_the_patterns_that_find_pip_and_venvs_are_not_blind() -> None:
    assert PIP_OR_VENV.keys() == PIP_OR_VENV_EXAMPLES.keys()
    for kind, example in PIP_OR_VENV_EXAMPLES.items():
        assert PIP_OR_VENV[kind].search(example), kind
    assert not PIP_OR_VENV["pip as a command"].search("RUN uv pip install --python /v/bin/python x")


def test_what_the_tree_runs_calls_pip_and_makes_venvs_by_uv_alone() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "--", "Makefile", "Dockerfile", "netbox/dev/Dockerfile", ".github/workflows/*.yml",
         "scripts/*.py", "testdata/s3/generate.py"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.split("\0")
    files = [name for name in tracked if name]
    assert {"Makefile", "Dockerfile", "netbox/dev/Dockerfile", ".github/workflows/ci.yml", "scripts/wheelcheck.py",
            "testdata/s3/generate.py"} <= set(files)
    found = [
        f"{name}:{number}: {line.strip()}"
        for name in files
        for number, line in enumerate((ROOT / name).read_text().splitlines(), 1)
        for pattern in PIP_OR_VENV.values()
        if pattern.search(line)
    ]
    assert found == []
