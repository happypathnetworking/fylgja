#!/usr/bin/env python3
"""Build the core's wheel from `core/` and `formats/` and install it outside the tree twice: with the
`server` extra, and alone at the floors of the base's ranges.

Run from the repository root: `python3 -I scripts/wheelcheck.py`, or `make wheelcheck` (D-066,
D-084). Everything happens in one temporary directory, so the tree is left as it was. Needs the
network, for the build's requirements and the wheel's dependencies. The core's check, `check`:

1. **The wheel.** It is built from a copy of `core/` and `formats/` whose `formats/` is first given
   `other-1.schema.json`, a schema no list names, as a format another distribution reads would be
   there; its `fylgja_core/formats/` holds the core's formats, `CORE_FORMATS` in `core/setup.py`,
   and no other.
2. **With the extra**, `pip install "<wheel>[server]"` in an empty venv: the formats the package
   reads are its own, outside the tree; `three-node.json` validates and `{}` does not; API 1's
   `Created` reads; and `fylgja-core --help` and `fylgja-core-server --help` exit 0, the second
   once the server's modules have imported, since the server's own parser answers it.
3. **Alone, at its floors**, in a second empty venv: `pip install --constraint <file> <wheel>`,
   the file one `name==floor` line a base library, the floors of `core/pyproject.toml`'s ranges.
   There each of the four is installed at its floor; no other library the wheel names for the
   `server` extra is installed; the base's sixteen modules import (`BASE_MODULES`); the fixture
   validates; the client follows a create, over a fake transport answering the version, one
   watch stream of a settling record and an ended run, to that run, the twin not gone; then
   `fylgja-core --help` exits 0, and `fylgja-core-server` exits 2 with one line on stderr whose
   `rule` is `server.extra.missing`.

The reader's check, `check_reader`, follows it in directories of its own, under `reader/` in the
same temporary directory:

1. **Its wheel.** It is built once, by `build_reader`, with `pip wheel --no-deps` from a copy of
   `readers/infrahub/` and `formats/` at their places, as `readers/infrahub/setup.py` finds
   `formats/` two directories up; its `fylgja_infrahub/formats/` holds the format of the reader's
   document, `READER_FORMATS`, and no other, its `fylgja_infrahub/queries/` the tree's GraphQL
   documents, of which there is at least one, and no other, and the package carries `py.typed`.
2. **Beside the base alone**, `pip install <the core's wheel> <its wheel>` in an empty venv, the
   core with no extra: `PROBE_READER`, run outside the tree, finds the format the package reads
   beside it and not in the tree; the seed's `reader.yaml` decodes; `schema.COMMIT` is the tree's
   `infrahub/schema/dcim/COMMIT`; and once the command's module has imported, no module of the
   server's libraries, Prefect or Infrahub's SDK (`NOT_BESIDE_READER`) is loaded, or installed.
   Then `fylgja-infrahub --help` exits 0.

The example orchestrator's check, `check_orchestrator`, follows them in directories of its own,
under `orchestrator/` in the same temporary directory:

1. **Its wheel.** It is built by `pip wheel --no-deps` from a copy of `orchestrator/` and
   `formats/` side by side, as `orchestrator/setup.py` finds `formats/`; its
   `fylgja_orchestrator/formats/` holds the formats of the example's two documents,
   `ORCHESTRATOR_FORMATS`, and no other, its `fylgja_orchestrator/infrahub/queries/` the tree's
   GraphQL documents of the change source, of which there is at least one, and no other, and the
   package carries `py.typed`.
2. **Beside the base and the reader**, `pip install <the core's wheel> <the reader's wheel> <its
   wheel>` in an empty venv, the core with no extra and the reader's wheel `build_reader`'s, since
   the example's change source reads through the reader: `PROBE_ORCHESTRATOR`, run outside the
   tree, finds the formats the package reads beside it and not in the tree; a plan 1 and a
   rehearsal 1 document validate, the second's `plan` held to the wheel's own plan 1, and `{}`
   does not; the rehearsal library's entry points import; no module of the server's
   libraries, the reader or Prefect (`NOT_BESIDE`) is loaded then, and none of the server's
   libraries that Prefect does not bring (`NOT_INSTALLED`) is installed; and then the change
   source imports and reads each of its GraphQL documents from the installed package, outside
   the tree. In a fresh interpreter there, `PROBE_EDGE` imports the command's module and finds
   nothing of the server's libraries or Prefect (`NOT_BESIDE_EDGE`) loaded; then
   `fylgja-orchestrator --help` exits 0.

`main` prints a line a check. Exit 0 when each passes; 1 with the reason on stderr otherwise.
"""

import ast
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREFIX = "fylgja_core/formats/"
FIXTURE = ROOT / "testdata" / "blueprint" / "three-node.json"
# Planted in the copy of `formats/` the wheel is built from: a format no distribution's list names.
PLANTED = "other-1.schema.json"
EXTRA_MISSING = "server.extra.missing"
# The base's modules, each `fylgja_core.<module>`: the model package and the two clients, as
# `core/tests/test_boundary_base.py` lists them (`core/tests/test_wheelcheck.py` holds the two equal).
BASE_MODULES = (
    "blueprint",
    "bundle",
    "cli",
    "client",
    "clock",
    "deployment",
    "documents",
    "findings",
    "platform_package",
    "probe_package",
    "probes",
    "problem",
    "run",
    "schemas",
    "twin_record",
    "ulid",
)
# A base library's entry in `core/pyproject.toml`: its name, its floor and its ceiling.
_RANGE = re.compile(r"([A-Za-z0-9_.-]+)>=([0-9]+(?:\.[0-9]+)*),<([0-9]+)")

# Run with the extra installed: the package's formats, outside the tree, and two of them read.
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

# Run in the base alone, given one JSON object: `floors`, each base library's; `modules`; `fixture`.
PROBE_ALONE = r"""
import importlib
import importlib.metadata as metadata
import json
import re
import sys
from pathlib import Path

given = json.loads(sys.argv[1])


def named(requirement):
    # A requirement's distribution, its name normalised as the packaging specifications do.
    return re.sub(r"[-_.]+", "-", re.match(r"[A-Za-z0-9._-]+", requirement).group()).lower()


for name, floor in given["floors"].items():
    version = metadata.version(name)
    assert version == floor, f"{name} is installed at {version}, not its floor {floor}"
requires = metadata.requires("fylgja-core") or []
base = {named(r) for r in requires if ";" not in r}
assert base == {named(n) for n in given["floors"]}, f"the wheel's base is {sorted(base)}"
extra = {named(r) for r in requires if re.search(r'extra\s*==\s*"server"', r)} - base
assert extra, "the wheel names no library for the extra server"
installed = []
for name in sorted(extra):
    try:
        installed.append(f"{name} {metadata.version(name)}")
    except metadata.PackageNotFoundError:
        pass
assert not installed, f"libraries of the extra server are installed: {installed}"

for module in given["modules"]:
    importlib.import_module(f"fylgja_core.{module}")

import httpx

from fylgja_core import schemas
from fylgja_core.client import Client

fixture = Path(given["fixture"])
assert schemas.validator("blueprint-1").is_valid(json.loads(fixture.read_text())), f"{fixture.name} does not validate"

TWIN, RUN = "three-node", "01JB8Z5Y3V4W6X7Y8Z9A0B1C2D"
written = {"name": TWIN, "revision": 1, "generation": 1, "status": {"observed_generation": 0}}
settled = {"name": TWIN, "revision": 2, "generation": 1,
           "status": {"observed_generation": 1, "phase": "pushed", "run_id": RUN}}
ended = {"id": RUN, "twin": TWIN, "operation": "create", "state": "ended", "verdict": {"status": "ok"}}
asked = []


def handler(request):
    asked.append(request.url.path)
    if request.url.path == "/v1/version":
        return httpx.Response(200, json={"api": "1"})
    if request.url.path == f"/v1/twins/{TWIN}":
        data = json.dumps({"type": "MODIFIED", "object": settled})
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              content=f"event: MODIFIED\ndata: {data}\n\n".encode())
    if request.url.path == f"/v1/runs/{RUN}":
        return httpx.Response(200, json=ended)
    raise AssertionError(f"the follow asked {request.method} {request.url}")


with Client("127.0.0.1:7650", "t", transport=httpx.MockTransport(handler)) as client:
    followed = client.follow(written, ("create",))
assert (followed.record, followed.run, followed.gone) == (settled, ended, False), followed
assert asked == ["/v1/version", f"/v1/twins/{TWIN}", f"/v1/runs/{RUN}"], asked
"""

# The formats the reader's wheel carries under `fylgja_infrahub/formats/`, that of its one document, and no other:
# stated here and not read from `readers/infrahub/setup.py`, so a list emptied or widened there fails the check.
READER_FORMATS = ("infrahub-reader-1.schema.json",)
READER_PREFIX = "fylgja_infrahub/formats/"
READER_QUERIES = "fylgja_infrahub/queries/"
READER_TYPED = "fylgja_infrahub/py.typed"
# The tree's GraphQL documents, each of which the reader's wheel carries under `READER_QUERIES`, and no other.
QUERIES = ROOT / "readers" / "infrahub" / "src" / "fylgja_infrahub" / "queries"
# The seed's reader document, which the installed reader decodes; the DCIM library's commit the reader's table is of.
READER_DOCUMENT = ROOT / "infrahub" / "seed" / "reader.yaml"
DCIM_COMMIT = ROOT / "infrahub" / "schema" / "dcim" / "COMMIT"
# What the reader's command never loads beside the base alone, and what is not installed there: the libraries of the
# core's `server` extra in full, Prefect and Infrahub's SDK, each a module or package, spelled as the reader's import
# test spells them (`readers/infrahub/tests/test_boundary.py`'s `FORBIDDEN`), so the check refuses what that test does.
NOT_BESIDE_READER = (
    "starlette",
    "uvicorn",
    "grpc",
    "google.protobuf",
    "pygnmi",
    "lightkube",
    "msgspec",
    "httpx2",
    "prefect",
    "infrahub_sdk",
)

# Run beside the base alone, given the tree's root, the seed's reader document, the commit and then
# `NOT_BESIDE_READER`: the reader's format, outside the tree; the document decoded; the table's commit the tree's; and
# nothing of `NOT_BESIDE_READER` loaded once the command's module has imported, or installed. A dotted name is judged
# whole, never by its first part: `google.protobuf`, not the namespace `google` another library may hold.
PROBE_READER = r"""
import importlib.util
import sys
from pathlib import Path

import fylgja_infrahub
from fylgja_core import schemas

root, reader, commit, absent = Path(sys.argv[1]).resolve(), Path(sys.argv[2]), sys.argv[3], sys.argv[4:]
here = Path(fylgja_infrahub.__file__).resolve().parent / "formats"
found = schemas.formats_dir("fylgja_infrahub")
assert found == here, f"formats_dir('fylgja_infrahub') is {found}, not {here}"
assert root not in found.parents, f"formats_dir('fylgja_infrahub') {found} is under the tree {root}"

from fylgja_infrahub import document, schema

decoded = document.load(reader)
assert isinstance(decoded, document.ReaderDocument), f"{reader.name} decodes to {decoded!r}"
assert schema.COMMIT == commit, f"fylgja_infrahub.schema.COMMIT is {schema.COMMIT}, not the tree's {commit}"

import fylgja_infrahub.cli

loaded = sorted(m for m in sys.modules if any(m == name or m.startswith(f"{name}.") for name in absent))
assert not loaded, f"loaded beside the base alone: {loaded}"


def present(name):
    # Whether `name` is installed: a missing parent package of a dotted name means it is not.
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


installed = [name for name in absent if present(name)]
assert not installed, f"installed beside the base alone: {installed}"
"""

# The formats the example's wheel carries under `fylgja_orchestrator/formats/`, those of its two documents, and no
# other: stated here and not read from `orchestrator/setup.py`, so a list emptied or widened there fails the check.
ORCHESTRATOR_FORMATS = ("plan-1.schema.json", "rehearsal-1.schema.json")
ORCHESTRATOR_PREFIX = "fylgja_orchestrator/formats/"
ORCHESTRATOR_TYPED = "fylgja_orchestrator/py.typed"
ORCHESTRATOR_QUERIES = "fylgja_orchestrator/infrahub/queries/"
# The tree's GraphQL documents of the change source, each of which the example's wheel carries under
# `ORCHESTRATOR_QUERIES`, and no other.
SOURCE_QUERIES = ROOT / "orchestrator" / "src" / "fylgja_orchestrator" / "infrahub" / "queries"
# What the example's rehearsal library never loads beside the base and the reader: the libraries of the core's `server`
# extra, the reader and Prefect, each a module or package; of those, what the command's module never loads, all but the
# reader, which the change source it opens reads through; and what is not installed there, the server's libraries that
# Prefect does not bring: Prefect 3.9.2 brings starlette and uvicorn (verified-facts.md, "Prefect 3.9.2"). A dotted
# name is judged whole, as `PROBE_READER` judges one.
NOT_BESIDE = ("starlette", "uvicorn", "grpc", "google.protobuf", "httpx2", "lightkube", "msgspec", "pygnmi", "prefect",
              "fylgja_infrahub")
NOT_BESIDE_EDGE = tuple(name for name in NOT_BESIDE if name != "fylgja_infrahub")
NOT_INSTALLED = ("grpc", "google.protobuf", "httpx2", "lightkube", "msgspec", "pygnmi")

# Run beside the base and the reader, given the tree's root and then a JSON object of `NOT_BESIDE` and
# `NOT_INSTALLED`: the example's formats, outside the tree; its two documents validated; its rehearsal library
# imported; nothing of `NOT_BESIDE` loaded, and nothing of `NOT_INSTALLED` installed; then the change source imported
# and each of its GraphQL documents read from the installed package, outside the tree.
PROBE_ORCHESTRATOR = r"""
import importlib.util
import json
import sys
from pathlib import Path

import fylgja_orchestrator
from fylgja_core import schemas

root, given = Path(sys.argv[1]).resolve(), json.loads(sys.argv[2])
here = Path(fylgja_orchestrator.__file__).resolve().parent / "formats"
found = schemas.formats_dir("fylgja_orchestrator")
assert found == here, f"formats_dir('fylgja_orchestrator') is {found}, not {here}"
assert root not in found.parents, f"formats_dir('fylgja_orchestrator') {found} is under the tree {root}"

from fylgja_orchestrator.rehearsal import Limits, create, plan, rehearse, stage_list, step
from fylgja_orchestrator.rehearsal.documents import validate
from fylgja_orchestrator.rehearsal.report import render

planned = {"plan_version": "1", "status": "empty", "headline": "Nothing to plan",
           "change": {"id": "pc-1", "where": "a change"}, "scope": "tag:fylgja", "read_at": "2026-11-09T10:15:11Z",
           "findings": [], "stages": []}
rehearsed = {"rehearsal_version": "1", "status": "not_rehearsed", "headline": "Not rehearsed", "plan": planned,
             "twin": "rh-00000000-00000000", "run_id": "run-1", "took_s": 0, "stages": [], "already_failing": [],
             "reclaimed": [], "findings": []}
assert validate("plan-1", planned) == [], validate("plan-1", planned)
assert validate("rehearsal-1", rehearsed) == [], validate("rehearsal-1", rehearsed)
assert schemas.validator("rehearsal-1", "fylgja_orchestrator").is_valid(rehearsed), "rehearsal-1 refuses a rehearsal"
assert validate("rehearsal-1", {**rehearsed, "plan": {}}) != [], "rehearsal-1 does not hold its plan to plan 1"
assert validate("plan-1", {}) != [], "plan-1 accepts {}"
assert validate("rehearsal-1", {}) != [], "rehearsal-1 accepts {}"

loaded = sorted(m for m in sys.modules if any(m == name or m.startswith(f"{name}.") for name in given["not_loaded"]))
assert not loaded, f"loaded by the rehearsal library: {loaded}"


def present(name):
    # Whether `name` is installed: a missing parent package of a dotted name means it is not.
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


installed = [name for name in given["not_installed"] if present(name)]
assert not installed, f"installed beside the base and the reader: {installed}"

# Only now, the rehearsal's loads judged: the change source imports the reader, and reads each of its GraphQL
# documents from the installed wheel's package data, each naming its operation.
from fylgja_orchestrator.infrahub import transport

queries = Path(transport.__file__).resolve().parent / "queries"
assert root not in queries.parents, f"the change source's queries {queries} are under the tree {root}"
names = sorted(path.stem for path in queries.glob("*.gql"))
assert names, f"no *.gql under {queries}"
for name in names:
    text, operation = transport._document(name)
    assert operation and operation in text, f"queries/{name}.gql names no operation"
"""

# Run in a fresh interpreter beside the base and the reader, given `NOT_BESIDE_EDGE` as one JSON list: the command's
# module imported, and nothing of the list loaded, Prefect among it, since a command calls the library in its own
# process (D-085).
PROBE_EDGE = r"""
import json
import sys

import fylgja_orchestrator.edge.cli

absent = json.loads(sys.argv[1])
loaded = sorted(m for m in sys.modules if any(m == name or m.startswith(f"{name}.") for name in absent))
assert not loaded, f"loaded by the command's module: {loaded}"
"""


class Failure(Exception):
    pass


def core_formats(setup: Path = ROOT / "core" / "setup.py") -> tuple[str, ...]:
    """The core's formats, `CORE_FORMATS` in `setup`, read by `ast` from its assignment there and
    never by import, since the file runs `setup()`. `scripts/imagecheck.py` holds a copy, since `-I`
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


def floors(pyproject: Path = ROOT / "core" / "pyproject.toml") -> dict[str, str]:
    """Each base library's floor, the lower bound of its entry in `pyproject`'s `dependencies`, read
    by `tomllib`; `Failure` naming an entry that is no `name>=floor,<ceiling`."""
    try:
        with pyproject.open("rb") as f:
            entries = tomllib.load(f)["project"]["dependencies"]
    except (OSError, tomllib.TOMLDecodeError, KeyError, TypeError) as e:
        raise Failure(f"{pyproject} gives no dependencies: {e}") from e
    found: dict[str, str] = {}
    for entry in entries:
        match = _RANGE.fullmatch(entry) if isinstance(entry, str) else None
        if match is None:
            raise Failure(f"{pyproject}: the base's entry {entry} is no name>=floor,<ceiling")
        found[match.group(1)] = match.group(2)
    return found


def run(argv: list[str], cwd: Path) -> None:
    """`argv` run in `cwd`, which must exit 0; `Failure` with what it printed otherwise."""
    exits(argv, cwd, 0)


def exits(argv: list[str], cwd: Path, status: int) -> subprocess.CompletedProcess[str]:
    """`argv` run in `cwd`, which must exit `status`: what it printed, or `Failure` with that otherwise."""
    try:
        done = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, check=False)
    except OSError as e:
        raise Failure(f"{argv[0]} cannot be run: {e}") from e
    if done.returncode != status:
        raise Failure(f"{' '.join(argv[:4])} ... exited {done.returncode}, not {status}:\n{done.stdout}{done.stderr}")
    return done


def venv(path: Path) -> Path:
    """An empty venv made at `path`: its `bin/`."""
    run([sys.executable, "-m", "venv", str(path)], path.parent)
    return path / "bin"


def build(tmp: Path) -> Path:
    """The core's one wheel, built by `pip wheel --no-deps` from a copy of `core/` and `formats/`
    under `tmp`, the copy of `formats/` given `PLANTED` first. Built once: called again with the
    same `tmp`, it answers the wheel already there."""
    dist = tmp / "dist"
    if not dist.is_dir():
        src = tmp / "src"
        shutil.copytree(
            ROOT / "core",
            src / "core",
            ignore=shutil.ignore_patterns(".venv", "tests", "build", "*.egg-info", "__pycache__", ".*_cache"),
        )
        shutil.copytree(ROOT / "formats", src / "formats")
        planted = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"}
        (src / "formats" / PLANTED).write_text(json.dumps(planted) + "\n")
        env = venv(tmp / "venv-build")
        run([str(env / "python"), "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(dist), str(src / "core")], tmp)
    wheels = sorted(dist.glob("*.whl"))
    if len(wheels) != 1:
        raise Failure(f"expected one wheel in {dist}, found {[w.name for w in wheels]}")
    return wheels[0]


def carried(wheel: Path) -> int:
    """How many formats the wheel carries, once they are the core's, `CORE_FORMATS`, and no other."""
    with zipfile.ZipFile(wheel) as archive:
        found = {n[len(PREFIX) :] for n in archive.namelist() if n.startswith(PREFIX) and not n.endswith("/")}
    expected = set(core_formats())
    problems = [f"missing from the wheel: {n}" for n in sorted(expected - found)]
    problems += [f"extra in the wheel: {n}" for n in sorted(found - expected)]
    if problems:
        raise Failure("the wheel's formats differ from CORE_FORMATS in core/setup.py:\n" + "\n".join(problems))
    return len(found)


def with_server(tmp: Path, wheel: Path) -> None:
    """The wheel with its `server` extra, in an empty venv: `PROBE`, and each console script's `--help`."""
    env = venv(tmp / "venv-server")
    run([str(env / "python"), "-m", "pip", "install", f"{wheel}[server]"], tmp)
    run([str(env / "python"), "-I", "-c", PROBE, str(FIXTURE), str(ROOT)], tmp)
    run([str(env / "fylgja-core"), "--help"], tmp)
    run([str(env / "fylgja-core-server"), "--help"], tmp)


def alone(tmp: Path, wheel: Path, found: dict[str, str]) -> None:
    """The wheel alone, each base library at its floor in `found`, in an empty venv: `PROBE_ALONE`,
    the CLI's `--help`, and the server's refusal in one line."""
    constraints = tmp / "floors.txt"
    constraints.write_text("".join(f"{name}=={floor}\n" for name, floor in found.items()))
    env = venv(tmp / "venv-alone")
    run([str(env / "python"), "-m", "pip", "install", "--constraint", str(constraints), str(wheel)], tmp)
    given = {"floors": found, "modules": list(BASE_MODULES), "fixture": str(FIXTURE)}
    run([str(env / "python"), "-I", "-c", PROBE_ALONE, json.dumps(given)], tmp)
    run([str(env / "fylgja-core"), "--help"], tmp)
    done = exits([str(env / "fylgja-core-server")], tmp, 2)
    lines = done.stderr.splitlines()
    try:
        line = json.loads(lines[0]) if len(lines) == 1 else None
    except ValueError:
        line = None
    if not isinstance(line, dict) or line.get("rule") != EXTRA_MISSING:
        raise Failure(f"fylgja-core-server alone exited 2, its stderr not one line whose rule is {EXTRA_MISSING}:\n"
                      f"{done.stderr}")


def check(tmp: Path) -> str:
    """The core's check, in `tmp`: the wheel's formats, then the wheel with `[server]`, then alone at its floors."""
    found = floors()
    wheel = build(tmp)
    count = carried(wheel)
    with_server(tmp, wheel)
    alone(tmp, wheel, found)
    at = ", ".join(f"{name} {floor}" for name, floor in found.items())
    return (f"wheelcheck: {wheel.name} carries the core's {count} formats and no other; with [server] it validates "
            f"{FIXTURE.name} outside the tree and the server imports; alone at its floors ({at}) the base imports, "
            "follows a run and refuses to serve")


def build_reader(tmp: Path) -> Path:
    """The reader's one wheel, built by `pip wheel --no-deps` from a copy of `readers/infrahub/` and `formats/` at their
    places under `tmp/reader/src`, as `readers/infrahub/setup.py` finds `formats/` two directories up. Built once:
    called again with the same `tmp`, it answers the wheel already there."""
    here = tmp / "reader"
    src, dist = here / "src", here / "dist"
    if not dist.is_dir():
        shutil.copytree(
            ROOT / "readers" / "infrahub",
            src / "readers" / "infrahub",
            ignore=shutil.ignore_patterns(".venv", "tests", "build", "*.egg-info", "__pycache__", ".*_cache"),
        )
        shutil.copytree(ROOT / "formats", src / "formats")
        env = venv(here / "venv")
        run([str(env / "python"), "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(dist),
             str(src / "readers" / "infrahub")], tmp)
    wheels = sorted(dist.glob("*.whl"))
    if len(wheels) != 1:
        raise Failure(f"expected one wheel in {dist}, found {[w.name for w in wheels]}")
    return wheels[0]


def carried_by_reader(wheel: Path) -> int:
    """How many GraphQL documents the reader's wheel carries, once it carries under `READER_PREFIX` exactly
    `READER_FORMATS`, under `READER_QUERIES` exactly the tree's `*.graphql` in `QUERIES`, and `READER_TYPED`."""
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
    queries = {path.name for path in QUERIES.glob("*.graphql")}
    if not queries:
        raise Failure(f"the tree's {QUERIES.relative_to(ROOT)} holds no *.graphql: the queries' comparison would pass "
                      "vacuously")
    problems: list[str] = []
    for prefix, expected, listed in (
        (READER_PREFIX, set(READER_FORMATS), "READER_FORMATS in scripts/wheelcheck.py"),
        (READER_QUERIES, queries, f"the tree's {QUERIES.relative_to(ROOT)}"),
    ):
        found = {n[len(prefix) :] for n in names if n.startswith(prefix) and not n.endswith("/")}
        problems += [f"missing from the wheel: {prefix}{n} ({listed})" for n in sorted(expected - found)]
        problems += [f"extra in the wheel: {prefix}{n} ({listed})" for n in sorted(found - expected)]
    if READER_TYPED not in names:
        problems.append(f"missing from the wheel: {READER_TYPED}")
    if problems:
        raise Failure(f"{wheel.name} does not carry the reader's format, its GraphQL documents and py.typed, "
                      "and no other:\n" + "\n".join(problems))
    return sum(1 for n in names if n.startswith(READER_QUERIES) and n.endswith(".graphql"))


def check_reader(tmp: Path, core_wheel: Path) -> str:
    """The reader's check, under `tmp/reader`: its wheel, from `build_reader`, and what it carries; then the wheel
    installed beside `core_wheel`, the core with no extra, in the venv it was built in, which the build left empty,
    where `PROBE_READER` runs outside the tree and `fylgja-infrahub --help` exits 0."""
    wheel = build_reader(tmp)
    queries = carried_by_reader(wheel)
    commit = DCIM_COMMIT.read_text().strip()
    env = tmp / "reader" / "venv" / "bin"
    run([str(env / "python"), "-m", "pip", "install", str(core_wheel), str(wheel)], tmp)
    run([str(env / "python"), "-I", "-c", PROBE_READER, str(ROOT), str(READER_DOCUMENT), commit, *NOT_BESIDE_READER],
        tmp)
    run([str(env / "fylgja-infrahub"), "--help"], tmp)
    return (f"wheelcheck: {wheel.name} carries the reader's {len(READER_FORMATS)} format and no other, and its "
            f"{queries} GraphQL documents; beside {core_wheel.name} alone it decodes {READER_DOCUMENT.name} outside "
            "the tree, its command imports with nothing of the server, Prefect or Infrahub's SDK, and answers --help")


def carried_by_example(wheel: Path) -> int:
    """How many GraphQL documents the example's wheel carries, once it carries under `ORCHESTRATOR_PREFIX` exactly
    `ORCHESTRATOR_FORMATS`, under `ORCHESTRATOR_QUERIES` exactly the tree's `*.gql` in `SOURCE_QUERIES`, and
    `ORCHESTRATOR_TYPED`; `Failure` otherwise."""
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
    queries = {path.name for path in SOURCE_QUERIES.glob("*.gql")}
    if not queries:
        raise Failure(f"the tree's {SOURCE_QUERIES.relative_to(ROOT)} holds no *.gql: the queries' comparison would "
                      "pass vacuously")
    problems: list[str] = []
    for prefix, expected, listed in (
        (ORCHESTRATOR_PREFIX, set(ORCHESTRATOR_FORMATS), "ORCHESTRATOR_FORMATS in scripts/wheelcheck.py"),
        (ORCHESTRATOR_QUERIES, queries, f"the tree's {SOURCE_QUERIES.relative_to(ROOT)}"),
    ):
        found = {n[len(prefix) :] for n in names if n.startswith(prefix) and not n.endswith("/")}
        problems += [f"missing from the wheel: {prefix}{n} ({listed})" for n in sorted(expected - found)]
        problems += [f"extra in the wheel: {prefix}{n} ({listed})" for n in sorted(found - expected)]
    if ORCHESTRATOR_TYPED not in names:
        problems.append(f"missing from the wheel: {ORCHESTRATOR_TYPED}")
    if problems:
        raise Failure(f"{wheel.name} does not carry the example's formats, its GraphQL documents and py.typed, and no "
                      "other:\n" + "\n".join(problems))
    return sum(1 for n in names if n.startswith(ORCHESTRATOR_QUERIES) and n.endswith(".gql"))


def check_orchestrator(tmp: Path, core_wheel: Path) -> str:
    """The example orchestrator's check, under `tmp/orchestrator`: its wheel built from a copy of `orchestrator/` and
    `formats/`, and what it carries; then the wheel installed beside `core_wheel`, the core with no extra, and the
    reader's wheel from `build_reader`, which the example depends on, in an empty venv, where `PROBE_ORCHESTRATOR`
    and then `PROBE_EDGE` run outside the tree, and the command answers `--help`."""
    here = tmp / "orchestrator"
    src, dist = here / "src", here / "dist"
    shutil.copytree(
        ROOT / "orchestrator",
        src / "orchestrator",
        ignore=shutil.ignore_patterns(".venv", "tests", "build", "*.egg-info", "__pycache__", ".*_cache"),
    )
    shutil.copytree(ROOT / "formats", src / "formats")
    env = venv(here / "venv")
    run([str(env / "python"), "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(dist), str(src / "orchestrator")],
        tmp)
    wheels = sorted(dist.glob("*.whl"))
    if len(wheels) != 1:
        raise Failure(f"expected one wheel in {dist}, found {[w.name for w in wheels]}")
    wheel = wheels[0]
    queries = carried_by_example(wheel)
    reader = build_reader(tmp)
    run([str(env / "python"), "-m", "pip", "install", str(core_wheel), str(reader), str(wheel)], tmp)
    given = {"not_loaded": list(NOT_BESIDE), "not_installed": list(NOT_INSTALLED)}
    run([str(env / "python"), "-I", "-c", PROBE_ORCHESTRATOR, str(ROOT), json.dumps(given)], tmp)
    run([str(env / "python"), "-I", "-c", PROBE_EDGE, json.dumps(list(NOT_BESIDE_EDGE))], tmp)
    run([str(env / "fylgja-orchestrator"), "--help"], tmp)
    return (f"wheelcheck: {wheel.name} carries the example's {len(ORCHESTRATOR_FORMATS)} formats and no other, and "
            f"its {queries} GraphQL documents; beside {core_wheel.name} and {reader.name} alone it validates a plan "
            "and a rehearsal outside the tree, its rehearsal library imports with nothing of the server, the reader "
            "or Prefect, its command's module with nothing of the server or Prefect, and fylgja-orchestrator "
            "answers --help")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="fylgja-wheelcheck-") as name:
        tmp = Path(name)
        try:
            print(check(tmp))
            print(check_reader(tmp, build(tmp)))
            print(check_orchestrator(tmp, build(tmp)))
        except Failure as failure:
            print(f"wheelcheck: {failure}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
