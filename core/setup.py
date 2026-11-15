"""The build steps `pyproject.toml` cannot state: the distribution's version, and the wheel carries the core's
formats as package data.

`VERSION` at the root is the one place the version is written, read by every distribution's build (D-106):
setuptools reads no file outside a project, so `version()` reads it and passes it to `setup()`.

`formats/` stays the one place a format is changed (D-066); this copies the core's, by the list
`CORE_FORMATS`, into the build directory, never into `src/`, so a checkout keeps reading the
repository's. A format another distribution reads is that distribution's to carry (D-084), so a
format added to `formats/` ships in this wheel only once it is listed here.
"""

from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

ROOT = Path(__file__).resolve().parent.parent
FORMATS = ROOT / "formats"
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


setup(version=version(), cmdclass={"build_py": BuildPy})
