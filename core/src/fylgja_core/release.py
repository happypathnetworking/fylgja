"""The build a distribution is: its version and the commit it was made at (D-106). A base module, standard library
alone, so each command of the five and the server can answer `--version` and `GET /v1/version`'s `build` from one place.

Where the package is found says which tree it is:

- A **wheel's**: its directory holds `COMMIT`, written by the build (`FYLGJA_BUILD_COMMIT`, else git, else `unknown`).
  The version is its distribution's metadata and the commit that file.
- A **checkout's**: its directory is under a `src/` with an ancestor holding `VERSION`. The version is that file, read
  now, never the editable install's metadata, which goes stale where `VERSION` changes; the commit is `git rev-parse
  HEAD` there, with `-dirty` where `git status --porcelain` prints anything, and `unknown` where git fails, is absent or
  takes longer than `GIT_TIMEOUT_S`.
- **Any other**: the metadata, and `unknown`.

`build` is `<version> (commit <commit>)`, the one form every surface shows.
"""

from __future__ import annotations

import argparse
import functools
import importlib.metadata
import importlib.util
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

VERSION_FILE = "VERSION"
COMMIT_FILE = "COMMIT"
UNKNOWN = "unknown"
GIT_TIMEOUT_S = 5


def _directory(package: str) -> Path | None:
    """The directory of `package`, found without importing it; None where it is not found."""
    try:
        spec = importlib.util.find_spec(package)
    except (ImportError, ValueError):
        return None
    if spec is None or not spec.submodule_search_locations:
        return None
    locations = list(spec.submodule_search_locations)
    return Path(locations[0]).resolve() if locations else None


def _checkout(directory: Path | None) -> Path | None:
    """The root of the checkout `directory` is under `src/` of: its nearest ancestor holding `VERSION`; None where
    `directory` is not under a `src/` or no ancestor holds one."""
    if directory is None or directory.parent.name != "src":
        return None
    return next((a for a in directory.parents if (a / VERSION_FILE).is_file()), None)


def _line(path: Path) -> str | None:
    """The first line of `path`, stripped; None where it cannot be read or is empty."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return None
    return lines[0].strip() or None if lines else None


def _git(root: Path, *argv: str) -> str | None:
    """What `git -C root argv` printed, where it exited 0 in time; None otherwise."""
    try:
        done = subprocess.run(
            ["git", "-C", str(root), *argv], capture_output=True, text=True, check=False, timeout=GIT_TIMEOUT_S
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def _head(root: Path) -> str:
    """The checkout's HEAD, `-dirty` where the tree has changes; `UNKNOWN` where git cannot say."""
    head = _git(root, "rev-parse", "HEAD")
    status = _git(root, "status", "--porcelain")
    if head is None or status is None or not head.strip():
        return UNKNOWN
    return head.strip() + ("-dirty" if status.strip() else "")


def version(distribution: str, package: str) -> str:
    """The version of `distribution`, whose code is `package`: `VERSION` in a checkout, else its metadata, else
    `UNKNOWN`."""
    directory = _directory(package)
    if directory is not None and not (directory / COMMIT_FILE).is_file():
        root = _checkout(directory)
        if root is not None:
            return _line(root / VERSION_FILE) or UNKNOWN
    try:
        return importlib.metadata.version(distribution)
    except importlib.metadata.PackageNotFoundError:
        return UNKNOWN


def commit(package: str) -> str:
    """The commit `package` was built at: its `COMMIT` in a wheel, git's HEAD in a checkout, else `UNKNOWN`."""
    directory = _directory(package)
    if directory is None:
        return UNKNOWN
    if (directory / COMMIT_FILE).is_file():
        return _line(directory / COMMIT_FILE) or UNKNOWN
    root = _checkout(directory)
    return _head(root) if root is not None else UNKNOWN


@functools.cache
def build(distribution: str, package: str) -> str:
    """`<version> (commit <commit>)` of `distribution`, whose code is `package`; worked out once."""
    return f"{version(distribution, package)} (commit {commit(package)})"


class _Version(argparse.Action):
    """`--version`: prints `<prog> <build>` and exits 0, working the build out only when it is given."""

    def __init__(self, option_strings: Sequence[str], dest: str, distribution: str, package: str) -> None:
        super().__init__(option_strings, dest=argparse.SUPPRESS, default=argparse.SUPPRESS, nargs=0,
                         help="print the version and the commit this was built at, and exit")
        self._distribution, self._package = distribution, package

    def __call__(self, parser: argparse.ArgumentParser, namespace: argparse.Namespace, values: Any,
                 option_string: str | None = None) -> None:
        sys.stdout.write(f"{parser.prog} {build(self._distribution, self._package)}\n")
        parser.exit()


def add_version(parser: argparse.ArgumentParser, distribution: str, package: str) -> None:
    """Give `parser` a `--version` that prints `<prog> <build>`, one line on stdout, and exits 0."""
    parser.add_argument("--version", action=_Version, distribution=distribution, package=package)
