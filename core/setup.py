"""The one build step `pyproject.toml` cannot state: the wheel carries `formats/` as package data.

`formats/` stays the one place a format is changed (D-066); this copies it into the build
directory, never into `src/`, so a checkout keeps reading the repository's.
"""

from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

FORMATS = Path(__file__).resolve().parent.parent / "formats"
PATTERNS = ("*.schema.json", "api-1.openapi.yaml")


class BuildPy(build_py):
    def run(self) -> None:
        super().run()
        found = sorted(path for pattern in PATTERNS for path in FORMATS.glob(pattern))
        if not found:
            raise SystemExit(
                f"no format under {FORMATS}: the wheel is built from the repository, core/ beside formats/"
            )
        target = Path(self.build_lib) / "fylgja_core" / "formats"
        self.mkpath(str(target))
        for path in found:
            self.copy_file(str(path), str(target / path.name))


setup(cmdclass={"build_py": BuildPy})
