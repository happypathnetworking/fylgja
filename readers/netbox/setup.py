"""The build steps `pyproject.toml` cannot state: the distribution's version, and the wheel carries the reader's
formats as package data.

`VERSION` at the root is the one place the version is written, read by every distribution's build (D-106):
setuptools reads no file outside a project, so `version()` reads it and passes it to `setup()`.

`formats/` stays the one place a format is changed (D-066); this copies the reader's, by the list `READER_FORMATS`,
into the build directory, never into `src/`, so a checkout keeps reading the repository's. The core's formats are the
core's wheel's to carry (D-084), so this list names none of them.
"""

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


setup(version=version(), cmdclass={"build_py": BuildPy})
