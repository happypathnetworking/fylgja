"""The build steps `pyproject.toml` cannot state: the distribution's version and commit, and the wheel carries the
reader's formats as package data.

`VERSION` at the root is the one place the version is written, read by every distribution's build (D-106):
setuptools reads no file outside a project, so `version()` reads it and passes it to `setup()`.

`commit()` answers the commit the build is made at, which `BuildPy` writes beside the package's code as `COMMIT`:
`FYLGJA_BUILD_COMMIT` where `make` or the workflow gives it, else git's HEAD here, else `unknown`.

`formats/` stays the one place a format is changed (D-066); this copies the reader's, by the list `READER_FORMATS`,
into the build directory, never into `src/`, so a checkout keeps reading the repository's. The core's formats are the
core's wheel's to carry (D-084), so this list names none of them.
"""

import os
import re
import subprocess
from collections.abc import Mapping
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

ROOT = Path(__file__).resolve().parents[2]
FORMATS = ROOT / "formats"
READER_FORMATS = ("netbox-reader-1.schema.json",)


def version(root: Path = ROOT) -> str:
    """The one line of `root`'s `VERSION`, stripped; `SystemExit` naming the file where it is not one line."""
    path = root / "VERSION"
    try:
        lines = path.read_text().splitlines()
    except OSError as e:
        raise SystemExit(f"{path} cannot be read: {e.strerror or e}") from e
    if len(lines) != 1 or not lines[0].strip():
        raise SystemExit(f"{path} is not one line holding the version")
    return lines[0].strip()


COMMIT_VARIABLE = "FYLGJA_BUILD_COMMIT"
_COMMIT = re.compile(r"[0-9a-f]{40}(-dirty)?")


def commit(environ: Mapping[str, str], where: Path) -> str:
    """The commit this build is made at: `FYLGJA_BUILD_COMMIT` where `make` or the workflow gives it (40 hex digits,
    `-dirty` after them where the tree had changes; any other value stops the build naming the variable alone, never
    the value), else `where`'s HEAD by git, `-dirty` where `git status --porcelain` prints anything, else `unknown`
    (no git, or no repository there)."""
    given = environ.get(COMMIT_VARIABLE)
    if given:
        if not _COMMIT.fullmatch(given):
            raise SystemExit(f"{COMMIT_VARIABLE} is not 40 hexadecimal digits, then -dirty or nothing")
        return given
    try:
        head, status = (
            subprocess.run(["git", "-C", str(where), *argv], capture_output=True, text=True, check=False, timeout=5)
            for argv in (("rev-parse", "HEAD"), ("status", "--porcelain"))
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if head.returncode != 0 or status.returncode != 0 or not _COMMIT.fullmatch(head.stdout.strip()):
        return "unknown"
    return head.stdout.strip() + ("-dirty" if status.stdout.strip() else "")


class BuildPy(build_py):
    def run(self) -> None:
        super().run()
        missing = [name for name in READER_FORMATS if not (FORMATS / name).is_file()]
        if missing:
            raise SystemExit(
                f"no {', '.join(missing)} under {FORMATS}: "
                "the wheel is built from the repository, readers/netbox/ under readers/ beside formats/"
            )
        target = Path(self.build_lib) / "fylgja_netbox" / "formats"
        self.mkpath(str(target))
        for name in READER_FORMATS:
            self.copy_file(str(FORMATS / name), str(target / name))
        # The commit this build is made at, which the package answers `--version` with (fylgja_core.release).
        package = Path(self.build_lib) / "fylgja_netbox"
        self.mkpath(str(package))
        (package / "COMMIT").write_text(commit(os.environ, ROOT) + "\n")


setup(version=version(), cmdclass={"build_py": BuildPy})
