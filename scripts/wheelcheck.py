#!/usr/bin/env python3
"""Build the wheel from `core/` and `formats/`, install it outside the tree and validate a fixture.

Run from the repository root: `python3 -I scripts/wheelcheck.py`, or `make wheelcheck`
(D-066). Everything happens in a temporary directory, so the tree is left as it was. Needs
the network, for the build's requirements and the wheel's pinned dependencies. Exit 0 when
the wheel carries every format and validates there, 1 with the reason on stderr otherwise.
"""

import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREFIX = "fylgja_core/formats/"

PROBE = """
import sys
from pathlib import Path

import fylgja_core
from fylgja_core import schemas

fixture, root = Path(sys.argv[1]), Path(sys.argv[2]).resolve()
here = Path(fylgja_core.__file__).resolve().parent / "formats"
found = schemas.formats_dir()
assert found == here, f"formats_dir() is {found}, not {here}"
assert root not in found.parents, f"formats_dir() {found} is under the tree {root}"
blueprint = schemas.validator("blueprint-1")
import json
assert blueprint.is_valid(json.loads(fixture.read_text())), f"{fixture.name} does not validate"
assert not blueprint.is_valid({}), "blueprint-1 accepts {}"
assert schemas.api_validator("Created").is_valid({"id": "a" * 64}), "api-1 Created refuses a valid id"
"""


class Failure(Exception):
    pass


def run(argv: list[str], cwd: Path) -> None:
    done = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise Failure(f"{' '.join(argv[:4])} ... exited {done.returncode}:\n{done.stdout}{done.stderr}")


def check(tmp: Path) -> str:
    src = tmp / "src"
    shutil.copytree(
        ROOT / "core",
        src / "core",
        ignore=shutil.ignore_patterns(".venv", "tests", "build", "*.egg-info", "__pycache__", ".*_cache"),
    )
    shutil.copytree(ROOT / "formats", src / "formats")
    venv = tmp / "venv"
    run([sys.executable, "-m", "venv", str(venv)], tmp)
    python = str(venv / "bin" / "python")
    run([python, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(tmp / "dist"), str(src / "core")], tmp)
    wheels = sorted((tmp / "dist").glob("*.whl"))
    if len(wheels) != 1:
        raise Failure(f"expected one wheel, found {[w.name for w in wheels]}")
    wheel = wheels[0]
    with zipfile.ZipFile(wheel) as archive:
        carried = {n[len(PREFIX) :] for n in archive.namelist() if n.startswith(PREFIX) and not n.endswith("/")}
    expected = {p.name for p in (ROOT / "formats").iterdir() if p.is_file() and p.name != "README.md"}
    problems = [f"missing from the wheel: {n}" for n in sorted(expected - carried)]
    problems += [f"extra in the wheel: {n}" for n in sorted(carried - expected)]
    if problems:
        raise Failure("the wheel's formats differ from formats/:\n" + "\n".join(problems))
    run([python, "-m", "pip", "install", str(wheel)], tmp)
    fixture = ROOT / "testdata" / "blueprint" / "three-node.json"
    run([python, "-I", "-c", PROBE, str(fixture), str(ROOT)], tmp)
    run([str(venv / "bin" / "fylgja-core"), "--help"], tmp)
    return f"wheelcheck: {wheel.name} carries {len(carried)} formats and validates {fixture.name} outside the tree"


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="fylgja-wheelcheck-") as name:
        try:
            print(check(Path(name)))
        except Failure as failure:
            print(f"wheelcheck: {failure}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
