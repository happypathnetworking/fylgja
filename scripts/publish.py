#!/usr/bin/env python3
"""The publish check (D-106): holds the tag, `VERSION`, `CHANGELOG.md`'s head and the three wheels in `dist/` to one
another before anything is uploaded, since a version uploaded can never be uploaded again.

Run as `python3 -I scripts/publish.py`, standard library alone. It performs no upload, tag or push, and contacts no
network: it checks and prints.

    check --tag T --commit C --dist D [--output F]   prints `index=<pypi|testpypi>` (and appends it to F), exit 0
    notes                                            prints the changelog's head section's body

A `Failure` is its lines on stderr, exit 1: `check` names every fault in one pass.
"""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from datetime import date
from email.parser import Parser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# The three published distributions: each wheel's prefix is the package that holds its COMMIT, and its project name.
NAMES = {"fylgja_core": "fylgja-core", "fylgja_infrahub": "fylgja-infrahub", "fylgja_netbox": "fylgja-netbox"}
RELEASE = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")
CANDIDATE = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)rc[1-9]\d*")
HEADING = re.compile(r"^## (\S+) - (unreleased|\d{4}-\d{2}-\d{2})$")
COMMIT = re.compile(r"[0-9a-f]{40}")


class Failure(Exception):
    """One or more faults, one to a line."""

    def __init__(self, *lines: str) -> None:
        super().__init__("\n".join(lines))
        self.lines = list(lines)


def index(version: str) -> str:
    """The index a version is uploaded to: `pypi` for X.Y.Z, `testpypi` for X.Y.ZrcN, else a `Failure`."""
    if RELEASE.fullmatch(version):
        return "pypi"
    if CANDIDATE.fullmatch(version):
        return "testpypi"
    raise Failure(f"version {version!r} is neither X.Y.Z nor X.Y.ZrcN: no index takes it")


def head(changelog: str) -> tuple[str, str]:
    """The first `## ` heading's version and date (`unreleased` or `YYYY-MM-DD`); a `Failure` where there is none or
    it is not of the form `## <version> - <date>`."""
    for line in changelog.splitlines():
        if line.startswith("## "):
            found = HEADING.match(line)
            if found is None:
                raise Failure(f"CHANGELOG.md: the first heading {line!r} is not '## <version> - <date or unreleased>'")
            if found.group(2) != "unreleased":
                try:
                    date.fromisoformat(found.group(2))
                except ValueError:
                    raise Failure(f"CHANGELOG.md: the first heading's date {found.group(2)} is no date") from None
            return found.group(1), found.group(2)
    raise Failure("CHANGELOG.md holds no '## ' heading")


def notes(root: Path = ROOT) -> str:
    """The body of the changelog's head section: what follows its heading up to the next `## ` heading."""
    text = (root / "CHANGELOG.md").read_text()
    head(text)
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("## ")) + 1
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
    return "\n".join(lines[start:end]).strip("\n") + "\n"


def _requirements(requires: list[str]) -> list[str]:
    """The entries of `requires` that name `fylgja-core`."""
    return [e for e in requires if re.match(r"\s*fylgja[-_.]core(?![\w.-])", e, re.I)]


def _wheel(path: Path, package: str, version: str, commit: str | None) -> list[str]:
    """What is wrong with one wheel: its metadata's name and version, its reader's floor and its commit."""
    faults = []
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            metas = [n for n in names if n.count("/") == 1 and n.endswith(".dist-info/METADATA")]
            if len(metas) != 1:
                return [f"{path.name}: holds {len(metas)} METADATA files, not one"]
            meta = Parser().parsestr(z.read(metas[0]).decode())
            commit_file = f"{package}/COMMIT"
            held = z.read(commit_file).decode().strip() if commit_file in names else None
    except (zipfile.BadZipFile, OSError) as e:
        return [f"{path.name}: is not a readable wheel ({e})"]
    if meta.get("Name") != NAMES[package]:
        faults.append(f"{path.name}: METADATA Name is {meta.get('Name')!r}, not {NAMES[package]!r}")
    if meta.get("Version") != version:
        faults.append(f"{path.name}: METADATA Version is {meta.get('Version')!r}, not {version!r}")
    if package != "fylgja_core":
        want = {f">={version}", f"<{int(version.split('.')[0]) + 1}"}
        found = _requirements(meta.get_all("Requires-Dist") or [])
        if len(found) != 1:
            faults.append(f"{path.name}: requires fylgja-core {len(found)} times, not once")
        elif ";" in found[0]:
            faults.append(f"{path.name}: the requirement {found[0]!r} is not plain: it carries a marker")
        else:
            got = {x for x in re.sub(r"[\s()]", "", found[0])[len("fylgja-core"):].split(",") if x}
            if got != want:
                faults.append(f"{path.name}: requires fylgja-core {sorted(got)}, not {sorted(want)}")
    if held is None:
        faults.append(f"{path.name}: holds no {package}/COMMIT")
    elif commit is not None and held != commit:
        faults.append(f"{path.name}: {package}/COMMIT is {held!r}, not {commit!r}")
    return faults


def check(tag: str, commit: str, dist: Path, root: Path = ROOT) -> str:
    """Every fault in one `Failure`, one to a line; else the index the version is uploaded to."""
    faults: list[str] = []
    try:
        version = (root / "VERSION").read_text().strip()
    except OSError as e:
        raise Failure(f"{root / 'VERSION'} cannot be read: {e.strerror or e}") from e
    result = ""
    if tag != "v" + version:
        faults.append(f"tag {tag!r} is not 'v' and VERSION ({'v' + version!r})")
    try:
        result = index(version)
    except Failure as e:
        faults.extend(e.lines)
    well_formed = COMMIT.fullmatch(commit) is not None
    if not well_formed:
        faults.append(f"commit {commit!r} is not 40 lowercase hex characters")
    try:
        text = (root / "CHANGELOG.md").read_text()
        changelog_version, date = head(text)
        stated = [m.group(1) for line in text.splitlines() if (m := HEADING.match(line))]
        if stated.count(version) > 1:
            faults.append(f"CHANGELOG.md states {version} in more than one heading")
        if changelog_version != version:
            faults.append(f"CHANGELOG.md's head is {changelog_version}, not VERSION's {version}")
        elif date == "unreleased":
            faults.append(f"CHANGELOG.md's head {version} is unreleased: the tagging commit dates it")
    except Failure as e:
        faults.extend(e.lines)
    except OSError as e:
        faults.append(f"CHANGELOG.md cannot be read: {e.strerror or e}")
    expected = {f"{package}-{version}-py3-none-any.whl": package for package in NAMES}
    present = sorted(p.name for p in dist.iterdir()) if dist.is_dir() else []
    if not dist.is_dir():
        faults.append(f"{dist} is not a directory")
    for name in present:
        if name not in expected:
            faults.append(f"{dist.name}/{name}: is none of the three wheels at {version}")
    for name, package in expected.items():
        if name not in present:
            faults.append(f"{dist.name}/{name}: is missing ({package})")
        else:
            faults.extend(_wheel(dist / name, package, version, commit if well_formed else None))
    if faults:
        raise Failure(*faults)
    return result


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="publish.py", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    one = sub.add_parser("check", help="hold the tag, VERSION, the changelog and the wheels to one another")
    one.add_argument("--tag", required=True)
    one.add_argument("--commit", required=True)
    one.add_argument("--dist", required=True, type=Path)
    one.add_argument("--output", type=Path, help="a file the line index=<index> is appended to")
    sub.add_parser("notes", help="print the changelog's head section's body")
    args = parser.parse_args(argv)
    try:
        if args.command == "notes":
            sys.stdout.write(notes(ROOT))
            return 0
        line = f"index={check(args.tag, args.commit, args.dist, ROOT)}\n"
        if args.output is not None:
            with args.output.open("a") as f:
                f.write(line)
        sys.stdout.write(line)
        return 0
    except Failure as e:
        for fault in e.lines:
            print(fault, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
