#!/usr/bin/env python3
"""Run the core's image `make image` built, and check what the tree cannot read of it (D-062).

Run from the repository root: `python3 -I scripts/imagecheck.py <image>:<tag>`, or `make
imagecheck`, which builds the image first. Each container is run with `--rm` and `--pull never`,
so a tag not on the host fails here and is never pulled, and each `docker` command's status is
read directly. The image:

- runs as the user 10001 (`id -u`);
- given only `FYLGJA_STORE=/tmp/store` and `FYLGJA_TOKENS=/nonexistent`, exits 2 with one ERROR
  line on stderr, JSON, whose `variable` is `FYLGJA_TOKENS`: its entry point is
  `fylgja-core-server`, which opened its store under `/tmp` as that user and loaded the packages
  inside against the wheel's formats before the token file stopped it;
- carries the core's formats, those `core/setup.py` copies by its list `CORE_FORMATS`, equal to
  the tree's by name and by bytes, and `schemas.formats_dir()` reads them there, so no stale
  build directory shipped one since removed and no other distribution's format in `formats/`
  shipped;
- holds, in its copies of the tree's `psp/` and `probes/` (the `Dockerfile` copies each whole),
  the files git tracks there and no other, by path (`find -type f` against `git ls-files`): a
  file git ignores under a directory the context allows (an editor's `*.swp` or `*~`, a nested
  `local/`) reaches the context with no `-dirty` tag to say so, and fails here. The tree's other
  allowed paths reach the image only through the wheel, whose formats are the bullet above's.

Exit 0, the tag checked the last line printed; 1 with the reason on stderr otherwise.
"""

from __future__ import annotations

import ast
import base64
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COPIES = {"psp": "/opt/fylgja/psp", "probes": "/opt/fylgja/probes"}  # the Dockerfile's whole copies of the tree's
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


def docker(argv: list[str], status: int = 0) -> subprocess.CompletedProcess[str]:
    """`docker` with `argv`, which must exit `status`."""
    try:
        done = subprocess.run(["docker", *argv], capture_output=True, text=True, check=False)
    except OSError as e:
        raise Failure(f"docker cannot be run: {e}") from e
    if done.returncode != status:
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


def differ(carried: set[str], tracked: set[str]) -> list[str]:
    """Each path the image's copies and git's tracked files do not share, named by where it is."""
    return ([f"in the image, not tracked by git: {path}" for path in sorted(carried - tracked)]
            + [f"tracked by git, not in the image: {path}" for path in sorted(tracked - carried)])


def check_copies(image: str) -> int:
    """How many files the image's copies of the tree's directories hold, once they are the ones
    git tracks there."""
    done = docker([*RUN, "--entrypoint", "find", image, *COPIES.values(), "-type", "f", "-print0"])
    carried: set[str] = set()
    for path in filter(None, done.stdout.split("\0")):
        named = [f"{tree}{path[len(inside):]}" for tree, inside in COPIES.items() if path.startswith(f"{inside}/")]
        if not named:
            raise Failure(f"find printed a path outside the image's copies: {path}")
        carried.add(named[0])
    problems = differ(carried, tracked(list(COPIES)))
    if problems:
        raise Failure("the image's copies of the tree differ from git's tracked files:\n" + "\n".join(problems))
    return len(carried)


def main(argv: list[str]) -> int:
    if len(argv) != 2 or ":" not in argv[1]:
        print("usage: imagecheck.py <image>:<tag>", file=sys.stderr)
        return 1
    image = argv[1]
    try:
        check_user(image)
        refusal = check_start(image)
        count = check_formats(image)
        copied = check_copies(image)
    except Failure as failure:
        print(f"imagecheck: {failure}", file=sys.stderr)
        return 1
    print(f"imagecheck: {image} runs as {USER}")
    print(f"imagecheck: given no token file it exits 2 naming {REFUSED}: {refusal}")
    print(f"imagecheck: it carries the core's {count} formats, formats/'s byte for byte, and reads them there")
    print(f"imagecheck: its copies of {' and '.join(f'{tree}/' for tree in COPIES)} hold git's {copied} tracked "
          "files there, and no other")
    print(image.rpartition(":")[2])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
