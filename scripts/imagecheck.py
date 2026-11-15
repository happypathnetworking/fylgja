#!/usr/bin/env python3
"""Run the core's image `make image` built, and check what the tree cannot read of it (D-062).

Run from the repository root: `python3 -I scripts/imagecheck.py <image>:<tag>`, or `make
imagecheck`, which builds the image first. Each container is run with `--rm` and `--pull never`,
so a tag not on the host fails here and is never pulled, and each `docker` command's status is
read directly. The image:

- runs as the user 10001 (`id -u`);
- given only `FYLGJA_STORE=/tmp/store` and `FYLGJA_TOKENS=/nonexistent`, exits 2 with one ERROR
  line on stderr, JSON, whose `variable` is `FYLGJA_TOKENS`: its entry point is
  `fylgja-core-server`, which opened its store under `/tmp` as that user and loaded the shipped packages, with
  `FYLGJA_PACKAGES` unset, against the wheel's formats before the token file stopped it;
- carries the core's formats, those `core/setup.py` copies by its list `CORE_FORMATS`, equal to
  the tree's by name and by bytes, and `schemas.formats_dir()` reads them there, so no stale
  build directory shipped one since removed and no other distribution's format in `formats/`
  shipped;
- carries the platform and probe packages in its wheel (D-106), not in copies of its own: it has no `/opt/fylgja/psp`
  or `/opt/fylgja/probes`, `FYLGJA_PACKAGES` is in no `Config.Env`, and `packages.shipped()` answers
  `fylgja_core/shipped/psp` and `fylgja_core/shipped/probes` under the installed package, holding the YAML git tracks
  in the tree's `psp/` and `probes/`, by name and by bytes, and no other file (`git ls-files`): a file git ignores
  under a directory the context allows (an editor's `*.swp` or `*~`) reaches the context with no `-dirty` tag to say
  so, and fails here; and its wheel's `fylgja_core/LICENSE` is the root's `LICENSE`;

- answers `fylgja-core --version` and `fylgja-core-server --version` with the tree's version, `VERSION`, and a commit
  that begins with the tag's twelve characters and has `-dirty` exactly where the tag has it: the image's build stage
  was given the commit as `FYLGJA_BUILD_COMMIT` (D-106), since its context holds no `.git`;

Exit 0, the tag checked the last line printed; 1 with the reason on stderr otherwise.
"""

from __future__ import annotations

import ast
import base64
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIRS = ("psp", "probes")  # the tree's directories of packages, each the wheel's `shipped/<name>`
GONE = ("/opt/fylgja/psp", "/opt/fylgja/probes")  # the image's own copies, which it no longer has
VARIABLE = "FYLGJA_PACKAGES"
USER = "10001"
REFUSED = "FYLGJA_TOKENS"
RUN = ["run", "--rm", "--pull", "never"]

# Run inside the image: where the package's formats are, where `schemas` reads them, and their bytes.
PROBE = """
import base64, json
from pathlib import Path
import fylgja_core
from fylgja_core import schemas
here = Path(fylgja_core.__file__).resolve().parent / "formats"
files = {p.name: base64.b64encode(p.read_bytes()).decode() for p in sorted(here.iterdir()) if p.is_file()}
print(json.dumps({"here": str(here), "read": str(schemas.formats_dir()), "files": files}))
"""


# Run inside the image: where `packages.shipped()` answers, the files under each directory, by path and bytes, and the
# bytes of the installed package's `LICENSE` (null where it has none).
PROBE_PACKAGES = """
import base64, json
from pathlib import Path
import fylgja_core
from fylgja_core import packages
here = Path(fylgja_core.__file__).resolve().parent / "shipped"
found = packages.shipped()
files = {f"{d.name}/{p.name}": base64.b64encode(p.read_bytes()).decode()
         for d in found for p in sorted(d.rglob("*")) if p.is_file()}
licence = here.parent / "LICENSE"
held = base64.b64encode(licence.read_bytes()).decode() if licence.is_file() else None
print(json.dumps({"here": str(here), "found": [str(d) for d in found], "files": files, "licence": held}))
"""


class Failure(Exception):
    pass


def core_formats(setup: Path = ROOT / "core" / "setup.py") -> tuple[str, ...]:
    """The core's formats, `CORE_FORMATS` in `setup`, read by `ast` from its assignment there and
    never by import, since the file runs `setup()`. `scripts/wheelcheck.py` holds a copy, since `-I`
    gives a script no sibling to import, and `core/tests/test_core_formats.py` holds the two alike."""
    try:
        module = ast.parse(setup.read_text(), str(setup))
    except (OSError, SyntaxError) as e:
        raise Failure(f"{setup} cannot be read: {e}") from e
    assigned = [
        statement.value
        for statement in module.body
        if isinstance(statement, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "CORE_FORMATS" for target in statement.targets)
    ]
    if not assigned:
        raise Failure(f"{setup} assigns no CORE_FORMATS")
    try:
        found = ast.literal_eval(assigned[-1])
    except (ValueError, TypeError) as e:
        raise Failure(f"{setup}'s CORE_FORMATS is no literal: {e}") from e
    if not isinstance(found, tuple) or not all(isinstance(name, str) for name in found):
        raise Failure(f"{setup}'s CORE_FORMATS is no tuple of strings: {found!r}")
    return found


def docker(argv: list[str], status: int | None = 0) -> subprocess.CompletedProcess[str]:
    """`docker` with `argv`, which must exit `status`; any status where that is `None`."""
    try:
        done = subprocess.run(["docker", *argv], capture_output=True, text=True, check=False)
    except OSError as e:
        raise Failure(f"docker cannot be run: {e}") from e
    if status is not None and done.returncode != status:
        command = " ".join(argv[:6])
        raise Failure(f"docker {command} ... exited {done.returncode}, not {status}:\n{done.stdout}{done.stderr}")
    return done


def check_user(image: str) -> None:
    uid = docker([*RUN, "--entrypoint", "id", image, "-u"]).stdout.strip()
    if uid != USER:
        raise Failure(f"the image runs as {uid!r}, not {USER}")


def check_start(image: str) -> str:
    """The refusal's message, once its run exited 2 and its one ERROR line named `REFUSED`."""
    done = docker([*RUN, "-e", "FYLGJA_STORE=/tmp/store", "-e", f"{REFUSED}=/nonexistent", image], status=2)
    lines: list[dict[str, object]] = []
    for line in filter(str.strip, done.stderr.splitlines()):
        try:
            parsed = json.loads(line)
        except ValueError:
            parsed = None
        if not isinstance(parsed, dict):
            raise Failure(f"a line on stderr is not a JSON object:\n{line}")
        lines.append(parsed)
    errors = [line for line in lines if line.get("level") == "ERROR"]
    if len(errors) != 1 or errors[0].get("variable") != REFUSED:
        raise Failure(f"expected one ERROR line naming {REFUSED}, got:\n{done.stderr}")
    return str(errors[0].get("message"))


def check_formats(image: str) -> int:
    """How many formats the image carries, once they are the tree's."""
    done = docker([*RUN, "--entrypoint", "python", image, "-I", "-c", PROBE])
    try:
        found = json.loads(done.stdout)
    except ValueError as e:
        raise Failure(f"the probe of the image's formats printed no JSON:\n{done.stdout}{done.stderr}") from e
    if found["read"] != found["here"]:
        raise Failure(f"schemas.formats_dir() is {found['read']}, not the package's {found['here']}")
    carried = {name: base64.b64decode(data) for name, data in found["files"].items()}
    try:
        tree = {name: (ROOT / "formats" / name).read_bytes() for name in core_formats()}
    except OSError as e:
        raise Failure(f"a format CORE_FORMATS lists cannot be read from formats/: {e}") from e
    problems = [f"missing from the image: {n}" for n in sorted(tree.keys() - carried.keys())]
    problems += [f"extra in the image: {n}" for n in sorted(carried.keys() - tree.keys())]
    problems += [f"differs from formats/: {n}" for n in sorted(tree.keys() & carried.keys()) if tree[n] != carried[n]]
    if problems:
        raise Failure("the image's formats differ from CORE_FORMATS in core/setup.py, read from formats/:\n"
                      + "\n".join(problems))
    return len(carried)


def tracked(paths: list[str]) -> set[str]:
    """The files git tracks under `paths`, relative to the repository's root."""
    try:
        done = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--", *paths], capture_output=True,
                              text=True, check=False)
    except OSError as e:
        raise Failure(f"git cannot be run: {e}") from e
    if done.returncode != 0:
        raise Failure(f"git ls-files exited {done.returncode}:\n{done.stderr}")
    return set(filter(None, done.stdout.split("\0")))


def check_packages(image: str) -> int:
    """How many package files the image carries, once it has no copies of its own (`test -e` exiting 1; any other
    status but 0 a failure, never taken as absent), sets no `FYLGJA_PACKAGES`, its `packages.shipped()` holds the
    tree's tracked YAML of `psp/` and `probes/`, by name and by bytes, and no other, and its wheel's
    `fylgja_core/LICENSE` is the root's `LICENSE`."""
    inspected = docker(["image", "inspect", "--format", "{{json .Config.Env}}", image]).stdout
    try:
        environment = json.loads(inspected)
    except ValueError as e:
        raise Failure(f"docker image inspect printed no JSON for Config.Env:\n{inspected}") from e
    if not isinstance(environment, list):
        environment = []
    if any(str(entry).split("=", 1)[0] == VARIABLE for entry in environment):
        raise Failure(f"the image sets {VARIABLE}: its packages are the wheel's, with the variable unset")
    for path in GONE:
        tested = docker([*RUN, "--entrypoint", "test", image, "-e", path], status=None)
        if tested.returncode == 0:
            raise Failure(f"the image still holds its own copy, {path}")
        if tested.returncode != 1:
            raise Failure(f"test -e {path} in the image exited {tested.returncode}, neither 0 nor 1:\n"
                          f"{tested.stdout}{tested.stderr}")
    done = docker([*RUN, "--entrypoint", "python", image, "-I", "-c", PROBE_PACKAGES])
    try:
        found = json.loads(done.stdout)
    except ValueError as e:
        raise Failure(f"the probe of the image's packages printed no JSON:\n{done.stdout}{done.stderr}") from e
    expected = [f"{found['here']}/{name}" for name in PACKAGE_DIRS]
    if found["found"] != expected:
        raise Failure(f"packages.shipped() is {found['found']}, not {expected}")
    carried = {name: base64.b64decode(data) for name, data in found["files"].items()}
    names = tracked([f"{name}/*.yaml" for name in PACKAGE_DIRS])
    try:
        tree = {name: (ROOT / name).read_bytes() for name in names}
    except OSError as e:
        raise Failure(f"a tracked package cannot be read: {e}") from e
    if not tree:
        raise Failure("git tracks no YAML under psp/ or probes/: the comparison would pass vacuously")
    problems = [f"missing from the image: {n}" for n in sorted(tree.keys() - carried.keys())]
    problems += [f"extra in the image: {n}" for n in sorted(carried.keys() - tree.keys())]
    problems += [f"differs from the tree's: {n}" for n in sorted(tree.keys() & carried.keys()) if tree[n] != carried[n]]
    if problems:
        raise Failure("the image's packages differ from git's tracked YAML of psp/ and probes/:\n"
                      + "\n".join(problems))
    if found.get("licence") is None:
        raise Failure("the image's fylgja_core holds no LICENSE")
    if base64.b64decode(found["licence"]) != (ROOT / "LICENSE").read_bytes():
        raise Failure("the image's fylgja_core/LICENSE is not the root's LICENSE")
    return len(carried)


def parse_build(program: str, said: str, version: str, tag: str) -> str:
    """The commit `said`, the stdout of `<program> --version`, names, once it is exactly `<program> <version> (commit
    <40 hex>[-dirty])` and a newline and is the tag's: its first twelve characters are the tag's, and `-dirty` ends
    both or neither. `Failure` otherwise."""
    wanted = re.fullmatch(r"([0-9a-f]{12})(-dirty)?", tag)
    if wanted is None:
        raise Failure(f"the tag {tag!r} is not twelve hexadecimal digits and `-dirty` or nothing")
    read = re.fullmatch(rf"{re.escape(program)} {re.escape(version)} \(commit ([0-9a-f]{{40}})(-dirty)?\)\n", said)
    if read is None:
        raise Failure(f"{program} --version printed {said!r}, not '{program} {version} (commit <40 hex>[-dirty])'")
    if read.group(1)[:12] != wanted.group(1) or read.group(2) != wanted.group(2):
        raise Failure(f"{program} --version names the commit {read.group(1)}{read.group(2) or ''}, and the tag "
                      f"{tag} is another")
    return read.group(1) + (read.group(2) or "")


def check_build(image: str) -> str:
    """The commit both commands of the image answer `--version` with, once each prints the tree's version and the
    commit `parse_build` holds to the tag."""
    tag = image.rpartition(":")[2]
    try:
        version = (ROOT / "VERSION").read_text().strip()
    except OSError as e:
        raise Failure(f"VERSION cannot be read: {e}") from e
    found = ""
    for program in ("fylgja-core", "fylgja-core-server"):
        found = parse_build(program, docker([*RUN, "--entrypoint", program, image, "--version"]).stdout, version, tag)
    return found


def main(argv: list[str]) -> int:
    if len(argv) != 2 or ":" not in argv[1]:
        print("usage: imagecheck.py <image>:<tag>", file=sys.stderr)
        return 1
    image = argv[1]
    try:
        check_user(image)
        refusal = check_start(image)
        count = check_formats(image)
        carried = check_packages(image)
        built = check_build(image)
    except Failure as failure:
        print(f"imagecheck: {failure}", file=sys.stderr)
        return 1
    print(f"imagecheck: {image} runs as {USER}")
    print(f"imagecheck: given no token file it exits 2 naming {REFUSED}: {refusal}")
    print(f"imagecheck: it carries the core's {count} formats, formats/'s byte for byte, and reads them there")
    print(f"imagecheck: it has no copies of psp/ or probes/ and sets no {VARIABLE}; its wheel's shipped packages "
          f"are git's {carried} tracked YAML files there, byte for byte, and no other, and its "
          "fylgja_core/LICENSE is the root's")
    print(f"imagecheck: fylgja-core and fylgja-core-server answer --version with the tree's version and the commit "
          f"{built}, the tag's")
    print(image.rpartition(":")[2])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
