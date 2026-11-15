"""The core's image as the tree states it (D-062): the build context is an allow-list, so nothing
under `local/` can reach a layer, and the `Dockerfile` copies from the context nothing else; both
stages are one base pinned by digest; uv comes into the build stage alone, from its image pinned by
digest, and the image installs the wheel with its `server` extra (D-084) by uv, so the image holds no uv and
its venv no pip; it runs as a user that is not root, takes no build argument, and never runs Python optimised, which
strips the `assert` inside asyncio that a lost Lease's cut rests on (verified-facts.md, uvicorn
0.54.0). `make imagecheck` builds and runs it."""

from __future__ import annotations

import json
import re
import shlex
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# What the build context may hold: the wheel's sources, beside the formats it carries (core/setup.py reads
# ../formats), and the packages the image serves.
ALLOWED = ["core/pyproject.toml", "core/setup.py", "core/src", "formats", "psp", "probes"]

_DIGEST = re.compile(r"@sha256:([0-9a-f]{64})(?:\s|$)")
_UV_IMAGE = re.compile(r"ghcr\.io/astral-sh/uv:([0-9.]+)@sha256:[0-9a-f]{64}")
_OPTIMISED = re.compile(r"-[A-Za-z]*O[A-Za-z]*")  # -O, -OO, or -O among other short options


def _patterns() -> list[str]:
    """`.dockerignore`'s patterns in order, blank lines and comments left out."""
    lines = (ROOT / ".dockerignore").read_text().splitlines()
    return [s for s in (line.strip() for line in lines) if s and not s.startswith("#")]


def _instructions() -> list[tuple[str, str]]:
    """The `Dockerfile`'s instructions in order, each its keyword upper-cased and its arguments,
    a continued line joined to the next and comments left out."""
    found: list[tuple[str, str]] = []
    pending = ""
    for line in (ROOT / "Dockerfile").read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.endswith("\\"):
            pending += stripped[:-1] + " "
            continue
        keyword, *args = (pending + stripped).split(None, 1)
        found.append((keyword.upper(), args[0].strip() if args else ""))
        pending = ""
    assert not pending, "the Dockerfile ends inside a continued line"
    return found


def _words(args: str) -> list[str]:
    """An instruction's arguments: its JSON array, or its words."""
    return [str(w) for w in json.loads(args)] if args.startswith("[") else shlex.split(args)


def _copy(args: str) -> tuple[list[str], list[str]]:
    """A `COPY`'s flags and its sources, the last word, its destination, left out."""
    flags: list[str] = []
    while args.startswith("--"):
        flag, _, args = args.partition(" ")
        flags.append(flag)
        args = args.lstrip()
    return flags, _words(args)[:-1]


def _final_stage() -> list[tuple[str, str]]:
    found = _instructions()
    last = max(i for i, (keyword, _) in enumerate(found) if keyword == "FROM")
    return found[last + 1 :]


def test_the_context_is_an_allow_list() -> None:
    patterns = _patterns()
    assert patterns[0] == "*"
    assert [p[1:] for p in patterns if p.startswith("!")] == ALLOWED
    # What a checkout holds, ignored, under an allowed path: each __pycache__ and core/src's egg-info.
    last = max(i for i, p in enumerate(patterns) if p.startswith("!"))
    assert {"**/__pycache__", "**/*.egg-info"} <= set(patterns[last + 1 :])


def test_the_dockerfile_copies_from_the_context_only_what_it_allows() -> None:
    sources = [
        source
        for keyword, args in _instructions()
        if keyword == "COPY"
        for flags, copied in [_copy(args)]
        if not any(f.startswith("--from=") for f in flags)
        for source in copied
    ]
    assert sources, "no COPY from the context"
    assert [s for s in sources if s not in ALLOWED] == []
    added = [source for keyword, args in _instructions() if keyword == "ADD" for source in _copy(args)[1]]
    assert [s for s in added if "://" not in s and not s.startswith("git@")] == [], "an ADD from the context"


def test_both_stages_are_one_base_pinned_by_digest() -> None:
    bases = [args for keyword, args in _instructions() if keyword == "FROM"]
    assert len(bases) == 2
    digests = [_DIGEST.search(base) for base in bases]
    assert all(digests), f"a FROM without @sha256:<64 hex>: {bases}"
    assert len({d.group(1) for d in digests if d}) == 1


def test_the_image_installs_the_wheel_with_the_server_extra() -> None:
    runs = [args for keyword, args in _instructions() if keyword == "RUN"]
    installs = [args for args in runs if "uv pip install" in args]
    assert len(installs) == 1, installs
    for needle in ("[server]", "--compile-bytecode", "--python /opt/fylgja/venv/bin/python"):
        assert needle in installs[0], needle
    # No pip, and no venv made but by uv: a `pip` not after `uv `, a `-m pip` or a `-m venv`.
    assert [r for r in runs if re.search(r"(?<!uv )pip (install|wheel)|-m pip|-m venv", r)] == []


def test_uv_comes_from_its_image_pinned_by_digest_into_the_build_stage_alone() -> None:
    found = _instructions()
    last = max(i for i, (keyword, _) in enumerate(found) if keyword == "FROM")

    def stage_sources(part: list[tuple[str, str]]) -> list[str]:
        return [
            flag[len("--from=") :]
            for keyword, args in part
            if keyword == "COPY"
            for flag in _copy(args)[0]
            if flag.startswith("--from=")
        ]

    root = tomllib.loads((ROOT / "pyproject.toml").read_text())
    version = root["tool"]["uv"]["required-version"].removeprefix("==")
    stages = {
        args.split()[-1] for keyword, args in found if keyword == "FROM" and " AS " in args.upper()
    }
    assert stages == {"build"}
    external = [s for s in stage_sources(found[:last]) if s not in stages]
    assert len(external) == 1, external
    match = _UV_IMAGE.fullmatch(external[0])
    assert match, external
    assert match.group(1) == version
    assert set(stage_sources(found[last + 1 :])) == {"build"}


def test_the_final_stage_copies_from_build_the_venv_alone() -> None:
    """So a uv (or a pip) copied there, from the build stage, fails."""
    from_build = [
        source
        for keyword, args in _final_stage()
        if keyword == "COPY" and "--from=build" in _copy(args)[0]
        for source in _copy(args)[1]
    ]
    assert from_build == ["/opt/fylgja/venv"]


def test_the_image_runs_as_a_user_that_is_not_root() -> None:
    users = [args for keyword, args in _final_stage() if keyword == "USER"]
    assert users, "the final stage sets no USER"
    assert users[-1].partition(":")[0] not in ("0", "root")


def test_the_image_takes_no_build_argument() -> None:
    assert [args for keyword, args in _instructions() if keyword == "ARG"] == []


def test_the_image_never_runs_python_optimised() -> None:
    found = _instructions()
    assert [args for keyword, args in found if keyword == "ENV" and "PYTHONOPTIMIZE" in args] == []
    run = [w for keyword, args in found if keyword in ("ENTRYPOINT", "CMD") for w in _words(args)]
    assert run, "no ENTRYPOINT or CMD"
    assert [w for w in run if _OPTIMISED.fullmatch(w)] == []
