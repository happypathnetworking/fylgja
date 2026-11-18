"""The publish check (D-106): `scripts/publish.py` holds the tag, `VERSION`, the changelog's head and `dist/`'s three
wheels to one another before anything is uploaded, naming every fault in one pass, and performs no upload itself. The
script is loaded by path, as `test_wheelcheck.py` loads its own; the wheels are zip files made under `tmp_path` holding
a `METADATA` and a `COMMIT`. The publish workflow, `.github/workflows/publish.yml`, is read as a file: it is never run
here, and its first run is a candidate's tag."""

from __future__ import annotations

import importlib.util
import re
import tomllib
import zipfile
from functools import cache
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "publish.py"
COMMIT = "a" * 40
OTHER = "b" * 40
WORKFLOW = ROOT / ".github" / "workflows" / "publish.yml"
PACKAGES = {"fylgja_core": "fylgja-core", "fylgja_infrahub": "fylgja-infrahub", "fylgja_netbox": "fylgja-netbox"}
# The upload jobs, one an index and a distribution, each named as its environment is (`<index>-<distribution>`).
UPLOADS = {f"{index}-{name}": (index, name) for index in ("testpypi", "pypi") for name in PACKAGES.values()}


@cache
def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("script_publish", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def wheel(dist: Path, package: str, version: str, *, meta_version: str | None = None, floor: str | None = None,
          requirement: str | None = None, commit: str = COMMIT) -> None:
    """One wheel in `dist`: its file name at `version`, its METADATA at `meta_version` (default `version`)."""
    dist.mkdir(exist_ok=True)
    stem = f"{package}-{version}"
    meta = f"Metadata-Version: 2.4\nName: {PACKAGES[package]}\nVersion: {meta_version or version}\n"
    if package != "fylgja_core":
        major = int(version.split(".")[0])
        meta += requirement or f"Requires-Dist: fylgja-core{floor or '>=' + version},<{major + 1}\n"
    with zipfile.ZipFile(dist / f"{stem}-py3-none-any.whl", "w") as z:
        z.writestr(f"{stem}.dist-info/METADATA", meta)
        z.writestr(f"{package}/COMMIT", commit + "\n")


def three(dist: Path, version: str = "1.0.0rc1") -> None:
    for package in PACKAGES:
        wheel(dist, package, version)


def tree(path: Path, version: str = "1.0.0rc1", head: str = "## 1.0.0rc1 - 2026-11-20") -> Path:
    path.mkdir(exist_ok=True)
    (path / "VERSION").write_text(version + "\n")
    (path / "CHANGELOG.md").write_text(f"# Changelog\n\nWhat it holds.\n\n{head}\n\nThe first release.\n\n"
                                       "## 0.9.0 - 2026-01-01\n\nEarlier.\n")
    return path


def test_the_index_is_told_by_the_versions_form() -> None:
    script = _script()
    assert script.index("1.0.0") == "pypi"
    assert script.index("1.0.0rc1") == "testpypi"
    for bad in ("1.0.0.dev0", "1.0", "1.0.0a1", "1.0.0+x", "01.0.0"):
        with pytest.raises(script.Failure):
            script.index(bad)


def test_a_tree_that_is_the_tag_passes(tmp_path: Path) -> None:
    root = tree(tmp_path / "root")
    three(tmp_path / "dist")
    assert _script().check("v1.0.0rc1", COMMIT, tmp_path / "dist", root) == "testpypi"


@pytest.mark.parametrize("tag", ["v1.0.0", "1.0.0rc1", "v1.0.0-rc1"])
def test_a_tag_that_is_not_the_version_is_refused(tmp_path: Path, tag: str) -> None:
    root = tree(tmp_path / "root")
    three(tmp_path / "dist")
    with pytest.raises(_script().Failure, match="tag"):
        _script().check(tag, COMMIT, tmp_path / "dist", root)


def test_every_fault_of_the_wheels_is_named_in_one_pass(tmp_path: Path) -> None:
    root = tree(tmp_path / "root")
    dist = tmp_path / "dist"
    wheel(dist, "fylgja_core", "1.0.0rc1", meta_version="1.0.0rc2", commit=OTHER)
    wheel(dist, "fylgja_infrahub", "1.0.0rc1", floor=">=1.0")
    wheel(dist, "fylgja_netbox", "1.0.0rc2")  # a name of another version, and the NetBox reader at VERSION missing
    # the example's wheel and an sdist are not allowed
    with zipfile.ZipFile(dist / "fylgja_orchestrator-1.0.0rc1-py3-none-any.whl", "w") as z:
        z.writestr("fylgja_orchestrator-1.0.0rc1.dist-info/METADATA", "Name: fylgja-orchestrator\nVersion: 1.0.0rc1\n")
    (dist / "fylgja_core-1.0.0rc1.tar.gz").write_bytes(b"")
    with pytest.raises(_script().Failure) as caught:
        _script().check("v1.0.0rc1", COMMIT, dist, root)
    text = str(caught.value)
    lines = text.splitlines()
    assert len(lines) == len(set(lines)) >= 6
    for fragment in ("fylgja_orchestrator-1.0.0rc1-py3-none-any.whl", "fylgja_core-1.0.0rc1.tar.gz",
                     "fylgja_netbox-1.0.0rc1-py3-none-any.whl: is missing", "fylgja_netbox-1.0.0rc2",
                     "METADATA Version is '1.0.0rc2'", "requires fylgja-core ['<2', '>=1.0'], not ['<2', '>=1.0.0rc1']",
                     OTHER):
        assert fragment in text, fragment
    # the other faults of a COMMIT: dirty and unknown
    for bad in (COMMIT + "-dirty", "unknown"):
        again = tmp_path / ("d" + bad[-5:])
        three(again)
        wheel(again, "fylgja_netbox", "1.0.0rc1", commit=bad)
        with pytest.raises(_script().Failure, match="fylgja_netbox"):
            _script().check("v1.0.0rc1", COMMIT, again, root)


def test_an_undated_or_other_head_is_refused(tmp_path: Path) -> None:
    three(tmp_path / "dist")
    for head, why in (("## 1.0.0rc1 - unreleased", "unreleased"), ("## 1.0.1 - 2026-11-20", "1.0.1"),
                      ("## 1.0.0rc1 2026-11-20", "heading"), ("## 1.0.0rc1 - 2026-99-99", "2026-99-99")):
        root = tree(tmp_path / "r", head=head)
        with pytest.raises(_script().Failure) as caught:
            _script().check("v1.0.0rc1", COMMIT, tmp_path / "dist", root)
        assert str(caught.value).count("\n") == 0 and why in str(caught.value)


def test_the_notes_are_the_head_sections_body(tmp_path: Path) -> None:
    root = tree(tmp_path / "root")
    assert _script().notes(root) == "The first release.\n"


LINKED = """\
See [the page](docs/compatibility.md) and [the questions](design/decisions.md#open-questions "why").
Also [a schema](./formats/findings-1.schema.json), [the web](https://example.org/a/b), [here](#below),
[mail](mailto:someone@example.org) and [more][oq].

```
[kept](docs/in-a-fence.md)
```

[oq]: design/decisions.md#open-questions
[ext]: https://example.org/x
"""
BASE = "https://github.com/example-org/fylgja/blob/v1.0.0/"


def linked(tmp_path: Path, body: str = LINKED) -> Path:
    root = tmp_path / "linked"
    root.mkdir()
    (root / "CHANGELOG.md").write_text(
        f"# Changelog\n\n## 1.0.0 - 2026-11-18\n\n{body}\n## 0.9.0 - 2026-01-01\n\nOld.\n")
    return root


def test_a_relative_link_is_absolute_at_the_tag_and_its_anchor_kept(tmp_path: Path) -> None:
    out = _script().notes(linked(tmp_path), "example-org/fylgja", "v1.0.0")
    assert f"[the page]({BASE}docs/compatibility.md)" in out
    assert f'[the questions]({BASE}design/decisions.md#open-questions "why")' in out
    assert f"[a schema]({BASE}formats/findings-1.schema.json)" in out
    assert f"[oq]: {BASE}design/decisions.md#open-questions\n" in out


def test_an_absolute_link_a_bare_anchor_and_a_fence_are_untouched(tmp_path: Path) -> None:
    out = _script().notes(linked(tmp_path), "example-org/fylgja", "v1.0.0")
    for kept in ("[the web](https://example.org/a/b)", "[here](#below)", "[mail](mailto:someone@example.org)",
                 "[ext]: https://example.org/x\n", "[kept](docs/in-a-fence.md)"):
        assert kept in out


def test_without_a_repository_and_a_tag_the_body_is_verbatim(tmp_path: Path) -> None:
    assert _script().notes(linked(tmp_path)) == LINKED


@pytest.mark.parametrize("target", ["../x.md", "docs/../../x.md", "/x.md", "//host.example/x"])
def test_a_link_that_leaves_the_repository_is_refused(tmp_path: Path, target: str) -> None:
    root = linked(tmp_path, f"A [link]({target}).\n")
    with pytest.raises(_script().Failure, match="not a path inside the repository"):
        _script().notes(root, "example-org/fylgja", "v1.0.0")


def test_the_repository_and_the_tag_hold_their_shapes(tmp_path: Path) -> None:
    root = linked(tmp_path)
    for repository, tag in (("fylgja", "v1.0.0"), ("a/b/c", "v1.0.0"), ("example-org/fylgja", "1.0.0"),
                            ("example-org/fylgja", "v1.0")):
        with pytest.raises(_script().Failure):
            _script().notes(root, repository, tag)
    with pytest.raises(_script().Failure, match="together"):
        _script().notes(root, "example-org/fylgja", None)


def test_the_notes_command_needs_both_and_prints_the_absolute_links(tmp_path: Path,
                                                                    capsys: pytest.CaptureFixture[str],
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_script(), "ROOT", linked(tmp_path))
    with pytest.raises(SystemExit):
        _script().main(["notes"])
    capsys.readouterr()
    assert _script().main(["notes", "--repository", "example-org/fylgja", "--tag", "v1.0.0"]) == 0
    assert f"[the page]({BASE}docs/compatibility.md)" in capsys.readouterr().out


def test_the_index_is_written_for_the_workflow(tmp_path: Path, capsys: pytest.CaptureFixture[str],
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    root = tree(tmp_path / "root")
    three(tmp_path / "dist")
    out = tmp_path / "out"
    out.write_text("earlier=1\n")
    script = _script()
    monkeypatch.setattr(script, "ROOT", root)
    status = script.main(["check", "--tag", "v1.0.0rc1", "--commit", COMMIT, "--dist", str(tmp_path / "dist"),
                          "--output", str(out)])
    assert status == 0
    assert capsys.readouterr().out == "index=testpypi\n"
    assert out.read_text() == "earlier=1\nindex=testpypi\n"


@cache
def _workflow() -> dict[Any, Any]:
    loaded: dict[Any, Any] = yaml.safe_load(WORKFLOW.read_text())
    return loaded


def _trigger() -> Any:
    """The workflow's `on`, which PyYAML reads as the key `True`."""
    workflow = _workflow()
    return workflow["on"] if "on" in workflow else workflow[True]


def _steps(job: str) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = _workflow()["jobs"][job]["steps"]
    return steps


def _uses(job: str, action: str) -> list[dict[str, Any]]:
    return [step for step in _steps(job) if step.get("uses", "").startswith(action + "@")]


def test_the_workflow_runs_on_a_version_tag_alone() -> None:
    assert _workflow()["name"] == "publish"
    assert _trigger() == {"push": {"tags": ["v*"]}}


def test_only_the_upload_jobs_may_ask_for_an_identity_token() -> None:
    workflow = _workflow()
    assert workflow["permissions"] == {"contents": "read"}
    assert {job: spec["permissions"] for job, spec in workflow["jobs"].items()} == {
        "build": {"contents": "read"},
        **{job: {"id-token": "write"} for job in UPLOADS},
        "release": {"contents": "write"},
    }


def test_each_upload_waits_for_its_own_environment_and_index() -> None:
    jobs = _workflow()["jobs"]
    assert jobs["build"]["outputs"] == {"index": "${{ steps.check.outputs.index }}"}
    # Six environments and no other, one an upload job's alone: a pending publisher is unique on its repository, owner,
    # workflow file and environment, not its project (design/verified-facts.md, "PyPI and TestPyPI").
    assert {job: spec.get("environment") for job, spec in jobs.items() if "environment" in spec} == {
        job: {"name": job} for job in UPLOADS}
    for job, (index, _) in UPLOADS.items():
        assert jobs[job]["needs"] == "build"
        assert jobs[job]["if"] == f"needs.build.outputs.index == '{index}'"
        assert jobs[job]["runs-on"] == "ubuntu-26.04"
    assert jobs["release"]["needs"] == ["build", "pypi-fylgja-core", "pypi-fylgja-infrahub", "pypi-fylgja-netbox"]
    assert jobs["release"]["if"] == "needs.build.outputs.index == 'pypi'"


def test_each_upload_job_downloads_then_publishes_its_one_wheel() -> None:
    jobs = _workflow()["jobs"]
    # The build job puts each wheel in an artifact of its own, named as its distribution; the check before it has held
    # dist/ to the three wheels at the version, so each pattern finds one wheel.
    artifacts = {step["with"]["name"]: step["with"] for step in _uses("build", "actions/upload-artifact")}
    assert artifacts == {name: {"name": name, "path": f"dist/{package}-*.whl", "if-no-files-found": "error"}
                         for package, name in PACKAGES.items()}
    (pin,) = {step["uses"] for step in _uses("release", "actions/download-artifact")}
    publishers = {step["uses"] for job in UPLOADS for step in _uses(job, "pypa/gh-action-pypi-publish")}
    assert len(publishers) == 1
    for job, (index, name) in UPLOADS.items():
        upload: dict[str, Any] = {"uses": next(iter(publishers))}
        if index == "testpypi":
            upload["with"] = {"repository-url": "https://test.pypi.org/legacy/"}
        assert _steps(job) == [{"uses": pin, "with": {"name": name, "path": "dist/"}}, upload], job
    # No job but these six uploads.
    assert {job for job in jobs if _uses(job, "pypa/gh-action-pypi-publish")} == set(UPLOADS)


def test_the_upload_is_trusted_publishing_with_no_stored_token() -> None:
    text = WORKFLOW.read_text()
    assert not re.search(r"\bsecrets\b", text)
    assert not re.search(r"password|(?<![\w-])token:|workflow_dispatch|pull_request", text)
    # No environment variable or default is given to every job or every step of one.
    assert "env" not in _workflow() and "defaults" not in _workflow()
    for job, spec in _workflow()["jobs"].items():
        assert "env" not in spec and "defaults" not in spec, job
    # GitHub's own token, `github.token`, is given to the release job's `gh` alone, never to an upload job.
    given = [(job, step.get("env")) for job in _workflow()["jobs"] for step in _steps(job)
             if "github.token" in str(step)]
    assert given == [("release", {"GH_TOKEN": "${{ github.token }}"})]


def test_every_action_is_pinned_by_a_commit() -> None:
    text = WORKFLOW.read_text()
    lines = [line.strip() for line in text.splitlines() if re.match(r"\s*(- )?uses:", line)]
    assert len(lines) == sum(1 for job in _workflow()["jobs"] for step in _steps(job) if "uses" in step) >= 9
    for line in lines:
        assert re.fullmatch(r"(- )?uses: [\w.-]+/[\w.-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+", line), line
    # The tooling is the step CI's own runs, at the same commit.
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    (setup,) = _uses("build", "astral-sh/setup-uv")
    assert f"uses: {setup['uses']} #" in ci


def test_the_build_gates_and_checks_before_anything_is_uploaded() -> None:
    steps = _steps("build")
    assert _workflow()["jobs"]["build"]["runs-on"] == "ubuntu-26.04"
    uses = [step.get("uses", "").split("@")[0] for step in steps]
    runs = [step.get("run", "") for step in steps]
    (python,) = [step for step in steps if step.get("uses", "").startswith("actions/setup-python@")]
    assert python["with"] == {"python-version": "3.14"}
    (setup,) = _uses("build", "astral-sh/setup-uv")
    # uv at the root's version, as CI's step has it, and no cache restored into a build that publishes.
    with (ROOT / "pyproject.toml").open("rb") as f:
        uv_version = tomllib.load(f)["tool"]["uv"]["required-version"].removeprefix("==")
    assert setup["with"] == {"version": uv_version, "enable-cache": False}
    order = ["actions/checkout", "actions/setup-python", "astral-sh/setup-uv", "make venv", "make lint", "make test",
             "make wheelcheck", "make wheels", "check", "ancestry", "actions/upload-artifact",
             "actions/upload-artifact", "actions/upload-artifact"]
    found = []
    for i, step in enumerate(steps):
        if step.get("id") == "check":
            found.append("check")
        elif "merge-base" in runs[i]:
            found.append("ancestry")
        else:
            found.append(uses[i] or runs[i])
    assert found == order
    check = steps[found.index("check")]
    assert check["run"] == ('python3 -I scripts/publish.py check --tag "$GITHUB_REF_NAME" --commit "$GITHUB_SHA" '
                            '--dist dist --output "$GITHUB_OUTPUT"')
    ancestry = steps[found.index("ancestry")]
    assert ancestry["if"] == "steps.check.outputs.index == 'pypi'"
    assert ancestry["run"] == 'git merge-base --is-ancestor "$GITHUB_SHA" origin/main'
    # The example's wheel is never built here, so never uploaded; the check refuses a fourth wheel besides.
    assert "orchestrator" not in WORKFLOW.read_text()
    # Nothing but the build job builds: the upload jobs run no command of the tree's.
    for job in UPLOADS:
        assert [step for step in _steps(job) if "run" in step] == []


def test_no_checkout_keeps_credentials() -> None:
    checkouts = [(job, step) for job in _workflow()["jobs"] for step in _steps(job)
                 if step.get("uses", "").startswith("actions/checkout@")]
    assert {job for job, _ in checkouts} == {"build", "release"}
    for job, step in checkouts:
        assert step["with"]["persist-credentials"] is False, job
    build = [step for job, step in checkouts if job == "build"]
    assert build[0]["with"] == {"fetch-depth": 0, "persist-credentials": False}


def test_the_release_is_the_wheels_and_the_changelogs_notes() -> None:
    steps = _steps("release")
    (download,) = _uses("release", "actions/download-artifact")
    assert download["with"] == {"pattern": "fylgja-*", "merge-multiple": True, "path": "dist/"}
    runs = [step["run"] for step in steps if "run" in step]
    assert runs == ['python3 -I scripts/publish.py notes --repository "$GITHUB_REPOSITORY" --tag "$GITHUB_REF_NAME" '
                    "> notes.md",
                    'gh release create "$GITHUB_REF_NAME" dist/*.whl --verify-tag --title "$GITHUB_REF_NAME" '
                    "--notes-file notes.md"]


def test_a_requirement_with_a_marker_is_refused(tmp_path: Path) -> None:
    root = tree(tmp_path / "root")
    dist = tmp_path / "dist"
    three(dist)
    wheel(dist, "fylgja_netbox", "1.0.0rc1",
          requirement="Requires-Dist: fylgja-core>=1.0.0rc1,<2; python_version > '3'\n")
    with pytest.raises(_script().Failure, match=r"fylgja_netbox.*python_version.*not plain") as caught:
        _script().check("v1.0.0rc1", COMMIT, dist, root)
    assert str(caught.value).count("\n") == 0


def test_a_missing_version_file_is_one_line(tmp_path: Path) -> None:
    root = tree(tmp_path / "root")
    (root / "VERSION").unlink()
    three(tmp_path / "dist")
    with pytest.raises(_script().Failure, match=r"VERSION cannot be read") as caught:
        _script().check("v1.0.0rc1", COMMIT, tmp_path / "dist", root)
    assert str(caught.value).count("\n") == 0


def test_a_version_stated_in_two_headings_is_refused(tmp_path: Path) -> None:
    root = tree(tmp_path / "root")
    (root / "CHANGELOG.md").write_text((root / "CHANGELOG.md").read_text() + "\n## 1.0.0rc1 - 2026-11-01\n\nAgain.\n")
    three(tmp_path / "dist")
    with pytest.raises(_script().Failure, match=r"1\.0\.0rc1 .*more than one heading") as caught:
        _script().check("v1.0.0rc1", COMMIT, tmp_path / "dist", root)
    assert str(caught.value).count("\n") == 0


def test_a_malformed_commit_is_said_alone(tmp_path: Path) -> None:
    root = tree(tmp_path / "root")
    three(tmp_path / "dist")
    with pytest.raises(_script().Failure) as caught:
        _script().check("v1.0.0rc1", "abc", tmp_path / "dist", root)
    assert str(caught.value).splitlines() == ["commit 'abc' is not 40 lowercase hex characters"]
