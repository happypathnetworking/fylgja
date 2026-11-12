"""The one build step `pyproject.toml` cannot state: the wheel carries the example's formats as package data.

`formats/` stays the one place a format is changed (D-066); this copies the example's, by the list
`ORCHESTRATOR_FORMATS`, into the build directory, never into `src/`, so a checkout keeps reading the
repository's. The core's formats are the core's wheel's to carry (D-084), so this list names none of
them. An empty list copies nothing.
"""

from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

FORMATS = Path(__file__).resolve().parent.parent / "formats"
ORCHESTRATOR_FORMATS = ("plan-1.schema.json", "rehearsal-1.schema.json")


class BuildPy(build_py):
    def run(self) -> None:
        super().run()
        missing = [name for name in ORCHESTRATOR_FORMATS if not (FORMATS / name).is_file()]
        if missing:
            raise SystemExit(
                f"no {', '.join(missing)} under {FORMATS}: "
                "the wheel is built from the repository, orchestrator/ beside formats/"
            )
        target = Path(self.build_lib) / "fylgja_orchestrator" / "formats"
        self.mkpath(str(target))
        for name in ORCHESTRATOR_FORMATS:
            self.copy_file(str(FORMATS / name), str(target / name))


setup(cmdclass={"build_py": BuildPy})
