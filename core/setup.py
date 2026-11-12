"""The one build step `pyproject.toml` cannot state: the wheel carries the core's formats as package data.

`formats/` stays the one place a format is changed (D-066); this copies the core's, by the list
`CORE_FORMATS`, into the build directory, never into `src/`, so a checkout keeps reading the
repository's. A format another distribution reads is that distribution's to carry (D-084), so a
format added to `formats/` ships in this wheel only once it is listed here.
"""

from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

FORMATS = Path(__file__).resolve().parent.parent / "formats"
CORE_FORMATS = (
    "api-1.openapi.yaml",
    "blueprint-1.schema.json",
    "bundle-1.schema.json",
    "deployment-1.schema.json",
    "findings-1.schema.json",
    "platform-package-1.schema.json",
    "probe-package-1.schema.json",
    "probes-1.schema.json",
    "problem-1.schema.json",
    "twin-record-1.schema.json",
)


class BuildPy(build_py):
    def run(self) -> None:
        super().run()
        missing = [name for name in CORE_FORMATS if not (FORMATS / name).is_file()]
        if missing:
            raise SystemExit(
                f"no {', '.join(missing)} under {FORMATS}: "
                "the wheel is built from the repository, core/ beside formats/"
            )
        target = Path(self.build_lib) / "fylgja_core" / "formats"
        self.mkpath(str(target))
        for name in CORE_FORMATS:
            self.copy_file(str(FORMATS / name), str(target / name))


setup(cmdclass={"build_py": BuildPy})
