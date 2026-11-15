#!/usr/bin/env python3
"""Build the core's wheel from `core/` and `formats/` and install it outside the tree twice: with the
`server` extra, and alone at the floors of the base's ranges.

Run from the repository root: `python3 -I scripts/wheelcheck.py`, or `make wheelcheck` (D-066,
D-084). Everything happens in one temporary directory, so the tree is left as it was; uv builds and installs
from directories outside the tree, so no workspace or lock reaches what it checks (D-108), and a host
with no `uv` on the PATH is told so before anything is made. Needs the
network, for the build's requirements and the wheel's dependencies. Each build's copy of the tree holds
`VERSION` at its root beside `formats/`, as each `setup.py` reads it, and each wheel's `METADATA` says
`VERSION`'s version (D-106). Each wheel is built at the tree's commit, `tree_commit`, which the build is given as
`FYLGJA_BUILD_COMMIT` (the copy holds no `.git`), and holds it as `<package>/COMMIT`; and each installed command's
`--version` is `<program> <version> (commit <commit>)`, one line. The core's check, `check`:

1. **The wheel.** It is built from a copy of `core/`, `formats/`, `psp/` and `probes/` (their READMEs among them)
   whose `formats/` is first given `other-1.schema.json`, a schema no list names, as a format another distribution
   reads would be there; its `fylgja_core/formats/` holds the core's formats, `CORE_FORMATS` in `core/setup.py`,
   and no other, and its `fylgja_core/shipped/` holds, under `CORE_PACKAGES`' names, exactly the YAML git tracks in
   the tree's `psp/` and `probes/`, byte for byte, and no README (D-106).
2. **With the extra**, `uv pip install "<wheel>[server]"` in an empty environment: the formats the package
   reads are its own, outside the tree; `three-node.json` validates and `{}` does not; API 1's
   `Created` reads; and `fylgja-core --help` and `fylgja-core-server --help` exit 0, the second
   once the server's modules have imported, since the server's own parser answers it. Then `fylgja-core-server`
   is started from that environment with `FYLGJA_STORE`, `FYLGJA_TOKENS` (a token this script makes, never prints and
   hashes by the installed `auth.hash_token`), `FYLGJA_LISTEN` on a free loopback port and no `FYLGJA_PACKAGES`, a stub
   `docker` that prints nothing and exits 0 first on `PATH`, so no Docker is needed: `GET /v1/version` answers within
   `START_S` seconds with the build the wheel holds, `three-node.json` is filed and its bundle built, 201, which only
   the shipped `nokia_srlinux` and `ping` make possible, and SIGTERM ends it with 143 within `STOP_S` seconds.
3. **Alone, at its floors**, in a second empty environment: `uv pip install --constraints <file> <wheel>`,
   the file one `name==floor` line a base library, the floors of `core/pyproject.toml`'s ranges.
   There each of the four is installed at its floor; no other library the wheel names for the
   `server` extra is installed; the base's seventeen modules import (`BASE_MODULES`); the fixture
   validates; the client follows a create, over a fake transport answering the version, one
   watch stream of a settling record and an ended run, to that run, the twin not gone; then
   `fylgja-core --help` exits 0, and `fylgja-core-server` exits 2 with one line on stderr whose
   `rule` is `server.extra.missing`.

The reader's check, `check_reader`, follows it in directories of its own, under `reader/` in the
same temporary directory:

1. **Its wheel.** It is built once, by `build_reader`, with `uv build --wheel` from a copy of
   `readers/infrahub/` and `formats/` at their places, as `readers/infrahub/setup.py` finds
   `formats/` two directories up; its `METADATA` names `fylgja-core` once, its specifiers
   `>=<VERSION>` and `<` the next major (`requires_core`); its `fylgja_infrahub/formats/` holds
   the format of the reader's document, `READER_FORMATS`, and no other, its
   `fylgja_infrahub/queries/` the tree's GraphQL documents, of which there is at least one, and
   no other, and the package carries `py.typed`.
2. **Beside the base alone**, `uv pip install <the core's wheel> <its wheel>` in an empty environment, the
   core with no extra: `PROBE_READER`, run outside the tree, finds the format the package reads
   beside it and not in the tree; the seed's `reader.yaml` decodes; `schema.COMMIT` is the tree's
   `infrahub/schema/dcim/COMMIT`; and once the command's module has imported, no module of the
   server's libraries, Prefect, Infrahub's SDK or the example (`NOT_BESIDE_READER`) is loaded, or
   installed.
   Then `fylgja-infrahub --help` exits 0.

The NetBox reader's check, `check_netbox_reader`, follows it in directories of its own, under
`netbox-reader/` in the same temporary directory:

1. **Its wheel.** It is built once, by `build_netbox_reader`, with `uv build --wheel` from a
   copy of `readers/netbox/` and `formats/` at their places, as `readers/netbox/setup.py` finds
   `formats/` two directories up; it requires the core as the Infrahub reader's does; its
   `fylgja_netbox/formats/` holds the format of the reader's document, `NETBOX_READER_FORMATS`,
   and no other, and the package carries `py.typed`.
2. **Beside the base alone**, in an empty environment of its own: the core's base libraries from the
   index, then `uv pip install --no-index --find-links <dir> fylgja-netbox==<VERSION>`, the directory
   holding the core's wheel and its own and nothing else, with no pre-release flag, so the reader's
   requirement takes the candidate's core; the core with no extra: `PROBE_NETBOX_READER`, run
   outside the tree, finds the format the package reads beside it and not in the tree; a copy of
   the seed's `netbox/seed/reader.yaml` decodes, its probes the context `fylgja-probes`; the
   mapping is `netbox-dcim`; and once the command's module has imported, no module of the server's
   libraries, Prefect, Infrahub's SDK, NetBox's client library, the Infrahub reader or the example
   (`NOT_BESIDE_NETBOX_READER`) is loaded, or installed. Then `fylgja-netbox --help` exits 0, and
   `fylgja-netbox check`, given an address and no token, exits 2 with the one line that names the
   token's variable, printing nothing on stdout and not the address.

The example orchestrator's check, `check_orchestrator`, follows them in directories of its own,
under `orchestrator/` in the same temporary directory:

1. **Its wheel.** It is built by `uv build --wheel` from a copy of `orchestrator/` and
   `formats/` side by side, as `orchestrator/setup.py` finds `formats/`; its
   `fylgja_orchestrator/formats/` holds the formats of the example's two documents,
   `ORCHESTRATOR_FORMATS`, and no other, its `fylgja_orchestrator/infrahub/queries/` the tree's
   GraphQL documents of the change source, of which there is at least one, and no other, and the
   package carries `py.typed`.
2. **Beside the base and the two readers**, `uv pip install <the core's wheel> <the reader's wheel>
   <the NetBox reader's wheel> <its wheel>` in an empty environment, the core with no extra and the
   readers' wheels `build_reader`'s and `build_netbox_reader`'s, since the example's two change
   sources read through them: `PROBE_ORCHESTRATOR`, run outside the tree, finds the formats the
   package reads beside it and not in the tree; a plan 1 and a rehearsal 1 document validate,
   the second's `plan` held to the wheel's own plan 1, and `{}` does not; the rehearsal
   library's entry points import; no module of the server's libraries, either reader or Prefect
   (`NOT_BESIDE`) is loaded then, and none of the server's libraries that Prefect does not bring
   (`NOT_INSTALLED`) is installed; and then the Infrahub change source imports and reads each of
   its GraphQL documents from the installed package, outside the tree, and the NetBox change
   source imports; each change source loads nothing of the other or of its reader (`CROSSED`),
   the NetBox one judged once the Infrahub one's modules and its reader's are dropped from
   `sys.modules`, so that an import of either is made again and seen. In a fresh interpreter
   there, `PROBE_EDGE` imports the command's module and finds nothing of the server's libraries
   or Prefect (`NOT_BESIDE_EDGE`) loaded; then `fylgja-orchestrator --help` and
   `fylgja-orchestrator stage mark --help` exit 0.

`main` prints a line a check. Exit 0 when each passes; 1 with the reason on stderr otherwise.
"""

import ast
import email.message
import email.parser
import functools
import http.client
import json
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# The one version every distribution is built at (D-106), copied beside each build's copy of the tree, as `formats/` is.
VERSION = ROOT / "VERSION"
# What the builds read at the root: the version, the licence the three published wheels carry, and the core's long
# description.
ROOT_FILES = ("VERSION", "LICENSE", "README.md")
# The metadata every published wheel states (D-106): the project's repository and what hangs off it, the classifiers
# (the core's alone adds its operating system), and the expression setuptools writes for `license = "Apache-2.0"`.
REPOSITORY = "https://github.com/happypathnetworking/fylgja"
CLASSIFIERS = (
    "Development Status :: 5 - Production/Stable",
    "Environment :: Console",
    "Intended Audience :: System Administrators",
    "Intended Audience :: Telecommunications Industry",
    "Programming Language :: Python :: 3 :: Only",
    "Programming Language :: Python :: 3.14",
    "Topic :: System :: Networking",
    "Typing :: Typed",
)
CORE_CLASSIFIER = "Operating System :: POSIX :: Linux"
PRIVATE_CLASSIFIER = "Private :: Do Not Upload"
# The variable the builds read the commit they are made at from (each `setup.py`).
COMMIT_VARIABLE = "FYLGJA_BUILD_COMMIT"
PREFIX = "fylgja_core/formats/"
SHIPPED_PREFIX = "fylgja_core/shipped/"
# The server's start, and its stop on SIGTERM: the seconds each may take (D-106, D-062).
START_S = 30
STOP_S = 10
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
    "release",
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
from fylgja_core import packages
shipped = packages.shipped()
want = (here.parent / "shipped" / "psp", here.parent / "shipped" / "probes")
assert shipped == want, f"packages.shipped() is {shipped}, not {want}"
assert not any(root in d.parents for d in shipped), f"shipped() {shipped} is under the tree {root}"
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
# core's `server` extra in full, Prefect, Infrahub's SDK and the example, each a module or package, spelled as the
# reader's import test spells them (`readers/infrahub/tests/test_boundary.py`'s `FORBIDDEN`), so the check refuses what
# that test does; `core/tests/test_wheelcheck.py` holds the two to each other.
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
    "fylgja_orchestrator",
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

# The format the NetBox reader's wheel carries under `fylgja_netbox/formats/`, that of its one document, and no other:
# stated here and not read from `readers/netbox/setup.py`, so a list emptied or widened there fails the check.
NETBOX_READER_FORMATS = ("netbox-reader-1.schema.json",)
NETBOX_READER_PREFIX = "fylgja_netbox/formats/"
NETBOX_READER_TYPED = "fylgja_netbox/py.typed"
# The seed's reader document, which the installed reader decodes from a copy outside the tree, and the configuration
# context it names for the probes; the mapping the reader names in a blueprint's source.
NETBOX_READER_DOCUMENT = ROOT / "netbox" / "seed" / "reader.yaml"
NETBOX_PROBES = "fylgja-probes"
NETBOX_MAPPING = "netbox-dcim"
# The command's two variables: an address it is given, a reserved name that is never reached, and the token it is not.
NETBOX_ADDRESS = ("FYLGJA_NETBOX_ADDRESS", "http://netbox.example:8800")
NETBOX_TOKEN = "FYLGJA_NETBOX_TOKEN"
# What the NetBox reader's command never loads beside the base alone, and what is not installed there: the Infrahub
# reader's list, the example among it, with NetBox's client library and the Infrahub reader, as the reader's import
# test forbids them (`readers/netbox/tests/test_boundary.py`'s `FORBIDDEN`); `core/tests/test_wheelcheck.py` holds the
# two to each other.
NOT_BESIDE_NETBOX_READER = (*NOT_BESIDE_READER, "pynetbox", "fylgja_infrahub")

# Run beside the base alone, given the tree's root, a copy of the seed's reader document, the probes' context, the
# mapping and then `NOT_BESIDE_NETBOX_READER`: the reader's format, outside the tree; the document decoded; the
# mapping's name; and nothing of `NOT_BESIDE_NETBOX_READER` loaded once the command's module has imported, or
# installed. A dotted name is judged whole, as `PROBE_READER` judges one.
PROBE_NETBOX_READER = r"""
import importlib.util
import sys
from pathlib import Path

import fylgja_netbox
from fylgja_core import schemas

root, reader, probes, mapping, absent = Path(sys.argv[1]).resolve(), Path(sys.argv[2]), *sys.argv[3:5], sys.argv[5:]
here = Path(fylgja_netbox.__file__).resolve().parent / "formats"
found = schemas.formats_dir("fylgja_netbox")
assert found == here, f"formats_dir('fylgja_netbox') is {found}, not {here}"
assert root not in found.parents, f"formats_dir('fylgja_netbox') {found} is under the tree {root}"
assert root not in reader.resolve().parents, f"the reader document {reader} is under the tree {root}"

from fylgja_netbox import document
import fylgja_netbox.mapping

decoded = document.load(reader)
assert isinstance(decoded, document.ReaderDocument), f"{reader.name} decodes to {decoded!r}"
assert decoded.probes == probes, f"{reader.name}'s probes are {decoded.probes!r}, not {probes!r}"
assert fylgja_netbox.mapping.READER == mapping, f"fylgja_netbox.mapping.READER is {fylgja_netbox.mapping.READER!r}"

import fylgja_netbox.cli

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
# What the example's rehearsal library never loads beside the base and the two readers: the libraries of the core's
# `server` extra, either reader and Prefect, each a module or package; of those, what the command's module never loads,
# all but the two readers, which the change sources it opens read through; and what is not installed there, the
# server's libraries that Prefect does not bring: Prefect 3.9.2 brings starlette and uvicorn (verified-facts.md,
# "Prefect 3.9.2"). A dotted name is judged whole, as `PROBE_READER` judges one.
READERS = ("fylgja_infrahub", "fylgja_netbox")
NOT_BESIDE = ("starlette", "uvicorn", "grpc", "google.protobuf", "httpx2", "lightkube", "msgspec", "pygnmi", "prefect",
              *READERS)
NOT_BESIDE_EDGE = tuple(name for name in NOT_BESIDE if name not in READERS)
NOT_INSTALLED = ("grpc", "google.protobuf", "httpx2", "lightkube", "msgspec", "pygnmi")
# What each change source, by its package under `fylgja_orchestrator`, never loads: the other source and its reader.
# `orchestrator/tests/test_boundary_edge.py` holds the same of what each names, and `core/tests/test_wheelcheck.py`
# holds the two tuples equal.
CROSSED = (
    ("infrahub", ("fylgja_netbox", "fylgja_orchestrator.netbox")),
    ("netbox", ("fylgja_infrahub", "fylgja_orchestrator.infrahub")),
)

# Run beside the base and the two readers, given the tree's root and then a JSON object of `NOT_BESIDE`,
# `NOT_INSTALLED` and `CROSSED`: the example's formats, outside the tree; its two documents validated; its rehearsal
# library imported; nothing of `NOT_BESIDE` loaded, and nothing of `NOT_INSTALLED` installed; then the Infrahub change
# source imported, with nothing of what `CROSSED` gives it loaded, and each of its GraphQL documents read from the
# installed package, outside the tree; then, the Infrahub source's modules and its reader's dropped from
# `sys.modules`, the NetBox change source imported, with nothing of what `CROSSED` gives it loaded again.
PROBE_ORCHESTRATOR = r"""
import importlib.util
import json
import sys
from pathlib import Path

import fylgja_orchestrator
from fylgja_core import schemas

root, given = Path(sys.argv[1]).resolve(), json.loads(sys.argv[2])
crossed = dict(given["crossed"])


def under(name, roots):
    return any(name == root or name.startswith(f"{root}.") for root in roots)

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
assert not installed, f"installed beside the base and the two readers: {installed}"

# Only now, the rehearsal's loads judged: the Infrahub change source imports its reader, and reads each of its GraphQL
# documents from the installed wheel's package data, each naming its operation.
from fylgja_orchestrator.infrahub import transport

assert "fylgja_infrahub" in sys.modules, "the Infrahub change source loaded no fylgja_infrahub: the probe is blind"
loaded = sorted(m for m in sys.modules if under(m, crossed["infrahub"]))
assert not loaded, f"loaded by the Infrahub change source: {loaded}"

queries = Path(transport.__file__).resolve().parent / "queries"
assert root not in queries.parents, f"the Infrahub change source's queries {queries} are under the tree {root}"
names = sorted(path.stem for path in queries.glob("*.gql"))
assert names, f"no *.gql under {queries}"
for name in names:
    text, operation = transport._document(name)
    assert operation and operation in text, f"queries/{name}.gql names no operation"

# And the NetBox change source, which imports its reader, from the installed package, outside the tree: the Infrahub
# source's modules and its reader's dropped first, so that an import of either is made again and seen.
for name in [m for m in sys.modules if under(m, crossed["netbox"])]:
    del sys.modules[name]
import fylgja_orchestrator.netbox

assert "fylgja_netbox" in sys.modules, "the NetBox change source loaded no fylgja_netbox: the probe is blind"
loaded = sorted(m for m in sys.modules if under(m, crossed["netbox"]))
assert not loaded, f"loaded by the NetBox change source: {loaded}"

here = Path(fylgja_orchestrator.netbox.__file__).resolve()
assert root not in here.parents, f"the NetBox change source {here} is under the tree {root}"
assert fylgja_orchestrator.netbox.NetBoxSource.comment_limit is None, "the NetBox change source bounds its report"
"""

# Run in a fresh interpreter beside the base and the two readers, given `NOT_BESIDE_EDGE` as one JSON list: the
# command's module imported, and nothing of the list loaded, Prefect among it, since a command calls the library in its
# own process (D-085).
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


def core_packages(setup: Path = ROOT / "core" / "setup.py") -> tuple[str, ...]:
    """The directories whose YAML the core's wheel carries, `CORE_PACKAGES` in `setup`, read by `ast` as
    `core_formats` reads its list."""
    try:
        module = ast.parse(setup.read_text(), str(setup))
    except (OSError, SyntaxError) as e:
        raise Failure(f"{setup} cannot be read: {e}") from e
    assigned = [
        statement.value
        for statement in module.body
        if isinstance(statement, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "CORE_PACKAGES" for target in statement.targets)
    ]
    if not assigned:
        raise Failure(f"{setup} assigns no CORE_PACKAGES")
    try:
        found = ast.literal_eval(assigned[-1])
    except (ValueError, TypeError) as e:
        raise Failure(f"{setup}'s CORE_PACKAGES is no literal: {e}") from e
    if not isinstance(found, tuple) or not all(isinstance(name, str) for name in found):
        raise Failure(f"{setup}'s CORE_PACKAGES is no tuple of strings: {found!r}")
    return found


def tracked_packages(names: tuple[str, ...], root: Path = ROOT) -> dict[str, bytes]:
    """The YAML git tracks directly under each of `names` in `root`, by its path from `root`, and its bytes."""
    try:
        done = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--", *(f"{n}/*.yaml" for n in names)],
                              capture_output=True, text=True, check=False)
    except OSError as e:
        raise Failure(f"git cannot be run: {e}") from e
    if done.returncode != 0:
        raise Failure(f"git ls-files exited {done.returncode}:\n{done.stderr}")
    found = {path: (root / path).read_bytes() for path in filter(None, done.stdout.split("\0"))
             if path.count("/") == 1}
    if not found:
        raise Failure(f"git tracks no YAML under {', '.join(names)}: the comparison would pass vacuously")
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


def tree_version(path: Path = VERSION) -> str:
    """The tree's version, the one line of `path` stripped; `Failure` naming the file where it is not one line."""
    try:
        lines = path.read_text().splitlines()
    except OSError as e:
        raise Failure(f"{path} cannot be read: {e.strerror or e}") from e
    if len(lines) != 1 or not lines[0].strip():
        raise Failure(f"{path} is not one line holding the version")
    return lines[0].strip()


def metadata(wheel: Path) -> email.message.Message:
    """The wheel's `*.dist-info/METADATA`, parsed; `Failure` where it holds none, or more than one."""
    with zipfile.ZipFile(wheel) as archive:
        names = [n for n in archive.namelist() if n.count("/") == 1 and n.endswith(".dist-info/METADATA")]
        if len(names) != 1:
            raise Failure(f"{wheel.name} holds {len(names)} METADATA, not one")
        return email.parser.Parser().parsestr(archive.read(names[0]).decode())


def versioned(wheel: Path, version: str) -> None:
    """Nothing, once the wheel's `METADATA` says `Version: <version>`; `Failure` naming both otherwise."""
    said = metadata(wheel)["Version"]
    if said != version:
        raise Failure(f"{wheel.name} is version {said}, and VERSION says {version}")


def base_requirements(wheel: Path) -> list[str]:
    """The wheel's `Requires-Dist` entries that carry no marker: the core's base libraries, at their ranges."""
    return [entry for entry in metadata(wheel).get_all("Requires-Dist", []) if ";" not in entry]


def requires_core(wheel: Path, version: str) -> None:
    """Nothing, once the reader's wheel names `fylgja-core` in exactly one `Requires-Dist`, with no marker, whose
    specifiers, taken as a set, are `>=<version>` and `<` the next major (D-106); `Failure` naming the wheel and what
    it should say otherwise."""
    expected = {f">={version}", f"<{int(version.split('.')[0]) + 1}"}
    found = [
        entry
        for entry in metadata(wheel).get_all("Requires-Dist", [])
        if re.match(r"fylgja[-_.]core(?![A-Za-z0-9_.-])", entry, re.IGNORECASE)
    ]
    specifiers = None
    if len(found) == 1 and ";" not in found[0]:
        written = re.sub(r"\s+", "", found[0])[len("fylgja-core"):].strip("()")
        specifiers = set(written.split(",")) if written else set()
    if specifiers != expected:
        raise Failure(f"{wheel.name} requires the core as {found}, not once as {','.join(sorted(expected))}")


@functools.cache
def tree_commit() -> str:
    """The tree's commit as `Makefile`'s `COMMIT` and each `setup.py` read it: git's HEAD at `ROOT`, `-dirty` after it
    where `git status --porcelain` prints anything; `unknown` where git cannot say. Worked out once, so the builds and
    the checks of one run agree whatever changes in the tree meanwhile."""
    outputs = []
    for argv in (["rev-parse", "HEAD"], ["status", "--porcelain"]):
        try:
            done = subprocess.run(["git", "-C", str(ROOT), *argv], capture_output=True, text=True, check=False)
        except OSError:
            return "unknown"
        if done.returncode != 0:
            return "unknown"
        outputs.append(done.stdout.strip())
    head, status = outputs
    return head + ("-dirty" if status else "") if re.fullmatch(r"[0-9a-f]{40}", head) else "unknown"


def held_commit(wheel: Path, package: str, commit: str) -> None:
    """Nothing, once the wheel holds `<package>/COMMIT` saying `commit` on one line; `Failure` naming the wheel and the
    file otherwise."""
    with zipfile.ZipFile(wheel) as archive:
        try:
            said = archive.read(f"{package}/COMMIT").decode()
        except KeyError:
            raise Failure(f"{wheel.name} holds no {package}/COMMIT") from None
    if said != commit + "\n":
        raise Failure(f"{wheel.name}'s {package}/COMMIT says {said.strip()!r}, and the tree is at {commit}")


def published_metadata(wheel: Path, documentation: str, core: bool = False) -> None:
    """Nothing, once the published wheel's `METADATA` says `License-Expression: Apache-2.0`, no `License-File` and no
    licence classifier, the three `Project-URL`s with `documentation` as the documentation's, exactly `CLASSIFIERS`
    (and the core's operating system where `core`), and no author, maintainer or contact; where `core`, also
    `Description-Content-Type: text/markdown` and a description that is the root `README.md`; `Failure` naming the
    wheel and each difference otherwise."""
    found = metadata(wheel)
    problems: list[str] = []
    if found.get_all("License-Expression") != ["Apache-2.0"]:
        problems.append(f"License-Expression is {found.get_all('License-Expression')}, not ['Apache-2.0']")
    urls = sorted(found.get_all("Project-URL", []))
    expected_urls = sorted([f"Repository, {REPOSITORY}", f"Changelog, {REPOSITORY}/blob/main/CHANGELOG.md",
                            f"Documentation, {REPOSITORY}/{documentation}"])
    if urls != expected_urls:
        problems.append(f"Project-URL is {urls}, not {expected_urls}")
    classifiers = sorted(found.get_all("Classifier", []))
    expected_classifiers = sorted([*CLASSIFIERS, *([CORE_CLASSIFIER] if core else [])])
    if classifiers != expected_classifiers:
        problems.append(f"Classifier is {classifiers}, not {expected_classifiers}")
    for field in ("Author", "Author-email", "Maintainer", "Maintainer-email", "License-File", "License"):
        if found.get_all(field):
            problems.append(f"{field} is {found.get_all(field)}, and the wheel states none")
    if core:
        if found.get_all("Description-Content-Type") != ["text/markdown"]:
            problems.append(f"Description-Content-Type is {found.get_all('Description-Content-Type')}, "
                            "not ['text/markdown']")
        if str(found.get_payload()).strip() != (ROOT / "README.md").read_text().strip():
            problems.append("the description is not the root README.md")
    if problems:
        raise Failure(f"{wheel.name}'s METADATA differs from the metadata of D-106:\n" + "\n".join(problems))


def private_metadata(wheel: Path) -> None:
    """Nothing, once the example's wheel is marked `Classifier: Private :: Do Not Upload`, the one classifier it holds,
    so that PyPI refuses it (D-106), and holds no `Project-URL`; `Failure` otherwise."""
    found = metadata(wheel)
    if found.get_all("Classifier") != [PRIVATE_CLASSIFIER]:
        raise Failure(f"{wheel.name} holds the classifiers {found.get_all('Classifier')}, "
                      f"not [{PRIVATE_CLASSIFIER!r}]: it could be uploaded")
    if found.get_all("Project-URL") or found.get_all("Author") or found.get_all("Author-email"):
        raise Failure(f"{wheel.name} states a project URL or an author, and the example states neither")


def held_licence(wheel: Path, package: str, expected: bool = True) -> None:
    """Nothing, once the wheel holds `<package>/LICENSE`, the root `LICENSE`'s bytes (or, where `expected` is false,
    holds no file of that name); `Failure` naming the wheel and the file otherwise."""
    with zipfile.ZipFile(wheel) as archive:
        try:
            held = archive.read(f"{package}/LICENSE")
        except KeyError:
            held = None
    if expected and held is None:
        raise Failure(f"{wheel.name} holds no {package}/LICENSE")
    if expected and held != (ROOT / "LICENSE").read_bytes():
        raise Failure(f"{wheel.name}'s {package}/LICENSE is not the root LICENSE's bytes")
    if not expected and held is not None:
        raise Failure(f"{wheel.name} holds {package}/LICENSE, and the example carries none")


def answers_version(command: Path, program: str, version: str, commit: str, cwd: Path) -> None:
    """Nothing, once `command --version` exits 0 printing exactly `<program> <version> (commit <commit>)` and a newline
    on stdout; `Failure` with what it printed otherwise."""
    done = exits([str(command), "--version"], cwd, 0)
    expected = f"{program} {version} (commit {commit})\n"
    if done.stdout != expected or done.stderr:
        raise Failure(f"{command.name} --version printed {done.stdout!r} on stdout and {done.stderr!r} on stderr, "
                      f"not {expected!r}")


def run(argv: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    """`argv` run in `cwd`, in `env` where it is given, which must exit 0; `Failure` with what it printed otherwise."""
    exits(argv, cwd, 0, env)


def exits(
    argv: list[str], cwd: Path, status: int, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """`argv` run in `cwd`, in `env` where it is given and else in this process's environment, which must exit
    `status`: what it printed, or `Failure` with that otherwise."""
    try:
        done = subprocess.run(argv, cwd=cwd, env=env, capture_output=True, text=True, check=False)
    except OSError as e:
        raise Failure(f"{argv[0]} cannot be run: {e}") from e
    if done.returncode != status:
        raise Failure(f"{' '.join(argv[:4])} ... exited {done.returncode}, not {status}:\n{done.stdout}{done.stderr}")
    return done


def uv() -> str:
    """The `uv` on the PATH, which must be the version the root `pyproject.toml` requires: every call of this check runs
    outside the tree, where uv never reads that. `Failure` in one line where there is none or it is another, before
    anything is made."""
    found = shutil.which("uv")
    if found is None:
        raise Failure('uv is not on the PATH: the wheel check builds and installs by it (CONTRIBUTING.md, "Tooling")')
    required = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["uv"]["required-version"].removeprefix("==")
    try:
        said = subprocess.run([found, "--version"], capture_output=True, text=True, check=False).stdout.split()
    except OSError as e:
        raise Failure(f"{found} cannot be run: {e}") from e
    version = said[1] if len(said) > 1 else "unreadable"
    if version != required:
        raise Failure(f"uv {version} is on the PATH, and the root pyproject.toml requires uv {required}")
    return found


def venv(path: Path) -> Path:
    """An empty environment made at `path` by uv, over this interpreter, outside any project: its `bin/`."""
    run([uv(), "venv", "--no-project", "--no-python-downloads", "--python", sys.executable, str(path)], path.parent)
    return path / "bin"


def wheel(source: Path, dist: Path) -> None:
    """The one wheel of the distribution at `source`, built by `uv build` into `dist`, from `dist`'s parent, at the
    tree's commit: the build is given `FYLGJA_BUILD_COMMIT`, whatever this process's environment holds, since the copy
    it builds from holds no `.git`; where the tree's commit is `unknown` it is given none, and the build says so."""
    env = {k: v for k, v in os.environ.items() if k != COMMIT_VARIABLE}
    if tree_commit() != "unknown":
        env[COMMIT_VARIABLE] = tree_commit()
    run([uv(), "build", "--wheel", "--no-python-downloads", "--python", sys.executable, "--out-dir", str(dist),
         str(source)], dist.parent, env)


def install(env: Path, *requirements: str, constraints: Path | None = None, find_links: Path | None = None) -> None:
    """`requirements` installed by `uv pip` into the environment whose `bin/` is `env`, held to the `name==version`
    lines of `constraints` where it is given, and from the directory `find_links` alone, no index, where that is given;
    from `env`'s grandparent."""
    run([uv(), "pip", "install", "--python", str(env / "python"),
         *(["--constraints", str(constraints)] if constraints else []),
         *(["--no-index", "--find-links", str(find_links)] if find_links else []), *requirements], env.parent.parent)


def copy_root_files(src: Path) -> None:
    """`ROOT_FILES` copied to the root of a build's copy of the tree, where each `setup.py` reads them (`../VERSION`,
    `../LICENSE`, `../README.md`)."""
    for name in ROOT_FILES:
        shutil.copyfile(ROOT / name, src / name)


def build(tmp: Path) -> Path:
    """The core's one wheel, built by `uv build --wheel` from a copy of `core/` and `formats/`
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
        copy_root_files(src)
        for name in core_packages():
            shutil.copytree(ROOT / name, src / name)
        planted = {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"}
        (src / "formats" / PLANTED).write_text(json.dumps(planted) + "\n")
        wheel(src / "core", dist)
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


def shipped(wheel: Path) -> int:
    """How many package files the wheel carries under `fylgja_core/shipped/`, once they are the YAML git tracks in the
    tree's `CORE_PACKAGES` directories, byte for byte, and no other file: no README."""
    with zipfile.ZipFile(wheel) as archive:
        carried = {n[len(SHIPPED_PREFIX):]: archive.read(n) for n in archive.namelist()
                   if n.startswith(SHIPPED_PREFIX) and not n.endswith("/")}
    tree = tracked_packages(core_packages())
    problems = [f"missing from the wheel: {n}" for n in sorted(tree.keys() - carried.keys())]
    problems += [f"extra in the wheel: {n}" for n in sorted(carried.keys() - tree.keys())]
    problems += [f"differs from the tree's: {n}" for n in sorted(tree.keys() & carried.keys()) if tree[n] != carried[n]]
    if problems:
        raise Failure("the wheel's shipped packages differ from the YAML git tracks in " + ", ".join(core_packages())
                      + ":\n" + "\n".join(problems))
    return len(carried)


def stub_docker(directory: Path) -> Path:
    """A `docker` that prints nothing and exits 0, in `directory`, which goes first on the server's `PATH`: the local
    driver asks the host's docker at start, and this check needs none."""
    stub = directory / "docker"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)
    return directory


# Requests to the server on loopback go by no proxy, whatever the environment's `*_proxy` say.
DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def answers(url: str, token: str, body: bytes | None = None) -> tuple[int, bytes]:
    """The status and body of `url`, a GET or, given `body`, a JSON POST, with the bearer token, by no proxy."""
    request = urllib.request.Request(url, data=body, headers={"Authorization": f"Bearer {token}",
                                                              "Content-Type": "application/json"})
    try:
        with DIRECT.open(request, timeout=10) as reply:
            return reply.status, reply.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def serve(tmp: Path, env: Path, build: str) -> float:
    """`fylgja-core-server`, started from the environment `env` with no `FYLGJA_PACKAGES`: the seconds to its first
    answer of `GET /v1/version`, which must come within `START_S` and say `build`; `three-node.json` filed and its
    bundle built, 201; and SIGTERM ending it with 143 within `STOP_S`. The token is made here, hashed by the installed
    `auth.hash_token`, handed to it by stdin, written as its hash alone and printed nowhere. The server is started
    with no `FYLGJA_*` or `PYTHON*` variable of this process; an answer other than 200 fails at once, naming it, and
    a failure ends the server and waits on it."""
    token = secrets.token_urlsafe(24)
    hashing = "import sys; from fylgja_core.server import auth; print(auth.hash_token(sys.stdin.read()))"
    hashed = subprocess.run([str(env / "python"), "-I", "-c", hashing], input=token, capture_output=True, text=True,
                            check=False)
    if hashed.returncode != 0 or not re.fullmatch(r"[0-9a-f]{64}\n", hashed.stdout):
        raise Failure("the installed fylgja_core.server.auth.hash_token did not hash a token: "
                      + hashed.stderr.replace(token, "<token>"))
    root = tmp / "serve"
    root.mkdir()
    tokens = root / "tokens"
    tokens.write_text(f"{hashed.stdout.strip()} wheelcheck\n")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    environment = {k: v for k, v in os.environ.items() if not k.startswith(("FYLGJA_", "PYTHON"))}
    (root / "bin").mkdir()
    environment["PATH"] = f"{stub_docker(root / 'bin')}:{os.environ.get('PATH', os.defpath)}"
    environment.update(FYLGJA_STORE=str(root / "store"), FYLGJA_TOKENS=str(tokens),
                       FYLGJA_LISTEN=f"127.0.0.1:{port}")
    base = f"http://127.0.0.1:{port}"
    started = time.monotonic()
    log = root / "server.log"
    with log.open("w") as sink:
        server = subprocess.Popen([str(env / "fylgja-core-server")], cwd=root, env=environment,
                                  stdin=subprocess.DEVNULL, stdout=sink, stderr=subprocess.STDOUT, text=True)
    try:
        took = -1.0
        while True:
            if server.poll() is not None:
                raise Failure(f"fylgja-core-server with no FYLGJA_PACKAGES exited {server.returncode} before it "
                              f"answered:\n{log.read_text()}".replace(token, "<token>"))
            try:
                status, body = answers(f"{base}/v1/version", token)
            except (OSError, http.client.HTTPException):
                pass
            else:
                if status != 200:
                    raise Failure(f"GET /v1/version answered {status}, not 200:\n"
                                  + body.decode(errors="replace").replace(token, "<token>"))
                took = time.monotonic() - started
                break
            if time.monotonic() - started > START_S:
                raise Failure(f"fylgja-core-server gave no answer to GET /v1/version within {START_S} s")
            time.sleep(0.1)
        said = json.loads(body).get("build")
        if said != build:
            raise Failure(f"GET /v1/version says the build {said!r}, and the wheel holds {build!r}")
        status, body = answers(f"{base}/v1/blueprints", token, FIXTURE.read_bytes())
        if status not in (200, 201):
            raise Failure(f"filing {FIXTURE.name} answered {status}, not 201:\n{body.decode(errors='replace')}")
        blueprint_id = json.loads(body)["id"]
        status, body = answers(f"{base}/v1/bundles", token, json.dumps({"blueprint_id": blueprint_id}).encode())
        if status != 201:
            raise Failure(f"building {FIXTURE.name}'s bundle answered {status}, not 201: the shipped packages did "
                          f"not load\n{body.decode(errors='replace')}")
        server.send_signal(signal.SIGTERM)
        try:
            server.wait(timeout=STOP_S)
        except subprocess.TimeoutExpired:
            raise Failure(f"fylgja-core-server did not end within {STOP_S} s of SIGTERM") from None
        if server.returncode != 143:
            raise Failure(f"fylgja-core-server ended {server.returncode} on SIGTERM, not 143")
        return took
    finally:
        if server.poll() is None:
            server.kill()
            server.wait()


def with_server(tmp: Path, wheel: Path) -> float:
    """The wheel with its `server` extra, in an empty venv: `PROBE`, each console script's `--help` and `--version`,
    and the server started there with no `FYLGJA_PACKAGES` (`serve`): the seconds it took to answer."""
    env = venv(tmp / "venv-server")
    install(env, f"{wheel}[server]")
    run([str(env / "python"), "-I", "-c", PROBE, str(FIXTURE), str(ROOT)], tmp)
    run([str(env / "fylgja-core"), "--help"], tmp)
    run([str(env / "fylgja-core-server"), "--help"], tmp)
    for program in ("fylgja-core", "fylgja-core-server"):
        answers_version(env / program, program, tree_version(), tree_commit(), tmp)
    return serve(tmp, env, f"{tree_version()} (commit {tree_commit()})")


def alone(tmp: Path, wheel: Path, found: dict[str, str]) -> None:
    """The wheel alone, each base library at its floor in `found`, in an empty venv: `PROBE_ALONE`,
    the CLI's `--help`, and the server's refusal in one line."""
    constraints = tmp / "floors.txt"
    constraints.write_text("".join(f"{name}=={floor}\n" for name, floor in found.items()))
    env = venv(tmp / "venv-alone")
    install(env, str(wheel), constraints=constraints)
    given = {"floors": found, "modules": list(BASE_MODULES), "fixture": str(FIXTURE)}
    run([str(env / "python"), "-I", "-c", PROBE_ALONE, json.dumps(given)], tmp)
    run([str(env / "fylgja-core"), "--help"], tmp)
    answers_version(env / "fylgja-core", "fylgja-core", tree_version(), tree_commit(), tmp)
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
    versioned(wheel, tree_version())
    held_commit(wheel, "fylgja_core", tree_commit())
    published_metadata(wheel, "tree/main/docs", core=True)
    held_licence(wheel, "fylgja_core")
    count = carried(wheel)
    kept = shipped(wheel)
    took = with_server(tmp, wheel)
    alone(tmp, wheel, found)
    at = ", ".join(f"{name} {floor}" for name, floor in found.items())
    return (f"wheelcheck: {wheel.name} is built at {tree_commit()}, states Apache-2.0, the project's URLs and "
            f"classifiers, no author and the README as its description, holds the licence's text, and carries the "
            f"core's {count} formats and no "
            f"other, and {kept} package files, the tracked YAML of {' and '.join(f'{n}/' for n in core_packages())} "
            f"and no other; started with no FYLGJA_PACKAGES it answered in {took:.1f} s, built {FIXTURE.name}'s "
            "bundle and ended 143 on SIGTERM; fylgja-core and fylgja-core-server answer --version with it; with "
            f"[server] it validates {FIXTURE.name} outside the tree and the server imports; alone at its floors "
            f"({at}) the base imports, follows a run and refuses to serve")


def build_reader(tmp: Path) -> Path:
    """The reader's one wheel, built by `uv build --wheel` from a copy of `readers/infrahub/` and `formats/` at their
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
        copy_root_files(src)
        wheel(src / "readers" / "infrahub", dist)
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
    installed beside `core_wheel`, the core with no extra, in an empty environment of its own,
    where `PROBE_READER` runs outside the tree and `fylgja-infrahub --help` exits 0."""
    wheel = build_reader(tmp)
    version = tree_version()
    versioned(wheel, version)
    requires_core(wheel, version)
    held_commit(wheel, "fylgja_infrahub", tree_commit())
    published_metadata(wheel, "tree/main/readers/infrahub")
    held_licence(wheel, "fylgja_infrahub")
    queries = carried_by_reader(wheel)
    commit = DCIM_COMMIT.read_text().strip()
    env = venv(tmp / "reader" / "venv")
    install(env, str(core_wheel), str(wheel))
    run([str(env / "python"), "-I", "-c", PROBE_READER, str(ROOT), str(READER_DOCUMENT), commit, *NOT_BESIDE_READER],
        tmp)
    run([str(env / "fylgja-infrahub"), "--help"], tmp)
    answers_version(env / "fylgja-infrahub", "fylgja-infrahub", version, tree_commit(), tmp)
    return (f"wheelcheck: {wheel.name} requires the core at {version} within the major; it states the "
            f"project's metadata and holds the licence's text; it carries the reader's "
            f"{len(READER_FORMATS)} format and no other, and its "
            f"{queries} GraphQL documents; beside {core_wheel.name} alone it decodes {READER_DOCUMENT.name} outside "
            "the tree, its command imports with nothing of the server, Prefect, Infrahub's SDK or the example, and "
            "answers --help and --version")


def build_netbox_reader(tmp: Path) -> Path:
    """The NetBox reader's one wheel, built by `uv build --wheel` from a copy of `readers/netbox/` and `formats/` at
    their places under `tmp/netbox-reader/src`, as `readers/netbox/setup.py` finds `formats/` two directories up. Built
    once: called again with the same `tmp`, it answers the wheel already there."""
    here = tmp / "netbox-reader"
    src, dist = here / "src", here / "dist"
    if not dist.is_dir():
        shutil.copytree(
            ROOT / "readers" / "netbox",
            src / "readers" / "netbox",
            ignore=shutil.ignore_patterns(".venv", "tests", "build", "*.egg-info", "__pycache__", ".*_cache"),
        )
        shutil.copytree(ROOT / "formats", src / "formats")
        copy_root_files(src)
        wheel(src / "readers" / "netbox", dist)
    wheels = sorted(dist.glob("*.whl"))
    if len(wheels) != 1:
        raise Failure(f"expected one wheel in {dist}, found {[w.name for w in wheels]}")
    return wheels[0]


def carried_by_netbox_reader(wheel: Path) -> None:
    """Nothing, once the NetBox reader's wheel carries under `NETBOX_READER_PREFIX` exactly `NETBOX_READER_FORMATS`,
    and `NETBOX_READER_TYPED`; `Failure` otherwise."""
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
    prefix = NETBOX_READER_PREFIX
    found = {n[len(prefix) :] for n in names if n.startswith(prefix) and not n.endswith("/")}
    expected = set(NETBOX_READER_FORMATS)
    listed = "NETBOX_READER_FORMATS in scripts/wheelcheck.py"
    problems = [f"missing from the wheel: {prefix}{n} ({listed})" for n in sorted(expected - found)]
    problems += [f"extra in the wheel: {prefix}{n} ({listed})" for n in sorted(found - expected)]
    if NETBOX_READER_TYPED not in names:
        problems.append(f"missing from the wheel: {NETBOX_READER_TYPED}")
    if problems:
        raise Failure(f"{wheel.name} does not carry the NetBox reader's format and py.typed, and no other:\n"
                      + "\n".join(problems))


def refused_without_token(command: Path, tmp: Path) -> None:
    """`command check`, given an address and no token, in this process's environment with every `FYLGJA_NETBOX_`
    variable taken out: it exits 2, prints nothing on stdout, and on stderr the one line that names the token's
    variable, so not the address; `Failure` otherwise."""
    name, address = NETBOX_ADDRESS
    env = {k: v for k, v in os.environ.items() if not k.startswith("FYLGJA_NETBOX_")} | {name: address}
    done = exits([str(command), "check"], tmp, 2, env)
    expected = f"{NETBOX_TOKEN} is not set\n"
    if done.stdout or done.stderr != expected:
        raise Failure(f"{command.name} check with no token exited 2, but did not print {expected!r} alone on stderr:\n"
                      f"{done.stdout}{done.stderr}")


def check_netbox_reader(tmp: Path, core_wheel: Path) -> str:
    """The NetBox reader's check, under `tmp/netbox-reader`: its wheel, from `build_netbox_reader`, its version and its
    requirement of the core, and what it carries; then, in an empty venv of its own, the core's base libraries from the
    index and `fylgja-netbox==<VERSION>` by name from a directory of `core_wheel` and its wheel alone, no index, so the
    core with no extra,
    where `PROBE_NETBOX_READER` runs outside the tree over a copy of the seed's reader document,
    `fylgja-netbox --help` exits 0 and `fylgja-netbox check` with no token is refused, naming the variable."""
    wheel = build_netbox_reader(tmp)
    version = tree_version()
    versioned(wheel, version)
    requires_core(wheel, version)
    held_commit(wheel, "fylgja_netbox", tree_commit())
    published_metadata(wheel, "tree/main/readers/netbox")
    held_licence(wheel, "fylgja_netbox")
    carried_by_netbox_reader(wheel)
    here = tmp / "netbox-reader"
    reader = here / NETBOX_READER_DOCUMENT.name
    shutil.copyfile(NETBOX_READER_DOCUMENT, reader)
    links = here / "links"
    links.mkdir()
    shutil.copyfile(core_wheel, links / core_wheel.name)
    shutil.copyfile(wheel, links / wheel.name)
    env = venv(here / "venv")
    install(env, *base_requirements(core_wheel))
    install(env, f"fylgja-netbox=={version}", find_links=links)
    run([str(env / "python"), "-I", "-c", PROBE_NETBOX_READER, str(ROOT), str(reader), NETBOX_PROBES, NETBOX_MAPPING,
         *NOT_BESIDE_NETBOX_READER], tmp)
    run([str(env / "fylgja-netbox"), "--help"], tmp)
    answers_version(env / "fylgja-netbox", "fylgja-netbox", version, tree_commit(), tmp)
    refused_without_token(env / "fylgja-netbox", tmp)
    return (f"wheelcheck: {wheel.name} requires the core at {version} within the major, states the "
            f"project's metadata and holds the licence's text, and fylgja-netbox=={version} "
            "installs by name from a directory of the two wheels and no index, with no pre-release flag; it carries "
            f"the NetBox reader's {len(NETBOX_READER_FORMATS)} format and no other; beside {core_wheel.name} alone it "
            f"decodes {NETBOX_READER_DOCUMENT.name} outside the tree, its command "
            "imports with nothing of the server, Prefect, a client library of Infrahub's or NetBox's, the Infrahub "
            "reader or the example, answers --help and --version, and refuses a check without a token, naming the "
            "variable")


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
    `formats/`, and what it carries; then the wheel installed beside `core_wheel`, the core with no extra, and the two
    readers' wheels from `build_reader` and `build_netbox_reader`, which the example depends on, in an empty venv,
    where `PROBE_ORCHESTRATOR` and then `PROBE_EDGE` run outside the tree, and the command answers `--help`, and its
    `stage mark` too."""
    here = tmp / "orchestrator"
    src, dist = here / "src", here / "dist"
    shutil.copytree(
        ROOT / "orchestrator",
        src / "orchestrator",
        ignore=shutil.ignore_patterns(".venv", "tests", "build", "*.egg-info", "__pycache__", ".*_cache"),
    )
    shutil.copytree(ROOT / "formats", src / "formats")
    copy_root_files(src)
    wheel(src / "orchestrator", dist)
    wheels = sorted(dist.glob("*.whl"))
    if len(wheels) != 1:
        raise Failure(f"expected one wheel in {dist}, found {[w.name for w in wheels]}")
    built = wheels[0]
    versioned(built, tree_version())
    held_commit(built, "fylgja_orchestrator", tree_commit())
    private_metadata(built)
    held_licence(built, "fylgja_orchestrator", expected=False)
    queries = carried_by_example(built)
    reader, netbox_reader = build_reader(tmp), build_netbox_reader(tmp)
    env = venv(here / "venv")
    install(env, str(core_wheel), str(reader), str(netbox_reader), str(built))
    given = {"not_loaded": list(NOT_BESIDE), "not_installed": list(NOT_INSTALLED), "crossed": list(CROSSED)}
    run([str(env / "python"), "-I", "-c", PROBE_ORCHESTRATOR, str(ROOT), json.dumps(given)], tmp)
    run([str(env / "python"), "-I", "-c", PROBE_EDGE, json.dumps(list(NOT_BESIDE_EDGE))], tmp)
    run([str(env / "fylgja-orchestrator"), "--help"], tmp)
    answers_version(env / "fylgja-orchestrator", "fylgja-orchestrator", tree_version(), tree_commit(), tmp)
    run([str(env / "fylgja-orchestrator"), "stage", "mark", "--help"], tmp)
    return (f"wheelcheck: {built.name} is marked {PRIVATE_CLASSIFIER!r} and carries no licence file; it carries the "
            f"example's {len(ORCHESTRATOR_FORMATS)} formats and no other, and "
            f"its {queries} GraphQL documents; beside {core_wheel.name}, {reader.name} and {netbox_reader.name} alone "
            "it validates a plan and a rehearsal outside the tree, its rehearsal library imports with nothing of the "
            "server, either reader or Prefect, both change sources import, each with nothing of the other or its "
            "reader, its command's module with nothing of the server or Prefect, and fylgja-orchestrator answers "
            "--help, stage mark --help and --version")


def main() -> int:
    try:
        uv()
    except Failure as failure:
        print(f"wheelcheck: {failure}", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory(prefix="fylgja-wheelcheck-") as name:
        tmp = Path(name)
        try:
            print(check(tmp))
            print(check_reader(tmp, build(tmp)))
            print(check_netbox_reader(tmp, build(tmp)))
            print(check_orchestrator(tmp, build(tmp)))
        except Failure as failure:
            print(f"wheelcheck: {failure}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
