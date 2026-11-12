"""The fixture network on the development Infrahub's `main`, and the seeded branch with its two staged edits, each
generated, waited for, timed and marked, and by a flag its proposed change.

Run by `make infrahub-seed` as `core/.venv/bin/python infrahub/seed/seed.py --branch <branch> --files infrahub/seed
--out <seed.json> --ctl <infrahubctl> --schema readers/infrahub/schema/fylgja-probe.yml --schema
infrahub/schema/fylgja-stage.yml [--proposed-change]`, with `local/.env` loaded (CONTRIBUTING.md, D-083):

- `main` is refused where it holds no artifact definition `DEFINITION`, before anything is written: the definition
  comes with this repository's import (`make infrahub-register`);
- each `--schema` file, a kind of which `main` lacks, is loaded on `main` by `infrahubctl` and waited for until `main`
  lists its kinds: the reader's `FylgjaProbe`, which `main/`'s probe is of, and the example's `FylgjaStage`, which
  the marks are of, loaded before the branch is made, since a mark is branch-agnostic and written on `main` (D-088);
- `files`/`main/`'s object files are loaded by `infrahubctl`, one at a time in the order of their names, where
  `main` holds none of the devices they say; they say the whole network, every relationship named by its peer's
  name. Where `main` holds all of those devices, nothing is loaded: a second load left each device in the one group
  its file names, out of the query group Infrahub had joined it to at its first generation (design/verified-facts.md,
  "Infrahub 1.11.11"). A hand edit on `main` is therefore not undone by a seed; a purge and a seed undo it. A `main`
  holding part of them is refused with nothing written;
- the configurations are generated, and waited for until each device of the scope `SCOPE` has its artifact
  `DEFINITION`, `Ready`, and each device the run made shows a checksum that moved;
- what an earlier seed left of the branch is removed: every `FylgjaStage` whose `branch` is its name, and its open
  proposed change, whether or not the branch is listed. A mark names its branch as text and outlives it (D-088), and
  Infrahub deletes a branch with an open proposed change and keeps that proposed change open, naming a branch gone
  (design/verified-facts.md, "Infrahub 1.11.11"), so both go before the branch's delete;
- the branch `--branch` is made anew from `main`, with `sync_with_git: false`: one an earlier seed left is deleted
  first, and the branch is refused where it does not read the definition, since a branch runs what was imported before
  it was made (D-088). A create that fails or goes unanswered within the request's timeout is read for its branch for
  up to `BRANCH_WAIT_S`;
- each of `EDITS`, in order: its object file under `files` loaded on the branch, its configurations generated and
  waited for as above, each device it changes showing a checksum that moved, and its time the reader's `head` of the
  branch, the first instant after its latest write, at which a read meets the edit and its configurations and nothing
  later, once two readings of it `QUIET_S` apart agree (D-082). The seed's time and the reader's are one rule, so
  `seed.json` and a read at its times cannot disagree; `head` is read with the reader's token,
  `FYLGJA_INFRAHUB_TOKEN`, never the writer's, connected before anything is removed or written. A `head` refused
  because a list it read was not whole is read again: just after a generation a page of the event log once answered
  more events than its own count (design/verified-facts.md, "Infrahub 1.11.11"; P3-36). Then the stage is marked: one
  `FylgjaStage` on `main` naming the branch, the stage's label, its time as `as_of`, verbatim, and a description, so
  that the rehearsal reads each stage of the branch between its branch point and its head (D-088);
- with `--proposed-change` (`make infrahub-seed PROPOSED_CHANGE=1`), last, the branch's proposed change into `main`,
  not a draft, named `Rehearse <branch>`. Infrahub runs a proposed change's checks when it is created, so without the
  flag the seed makes none, and the maintainer's opening one is what starts the rehearsal (D-088). Every run makes the
  branch, its marks and, by the flag, its proposed change anew, and leaves no other mark and no other open proposed
  change of that branch;
- `seed.json` at `--out` holds the branch, the scope, each stage's label and time, the marks' labels in order, and the
  proposed change's id and name, or null without the flag. It is removed before anything is written and written whole
  at the end, so a run that fails leaves none.

The wait is for each configuration, not for the call: Infrahub answers the generation before anything is rendered,
and a regeneration rewrites an artifact that read `Ready` before it in place, `Ready` again with a new checksum
(design/verified-facts.md, "Infrahub 1.11.11"; D-082). A failed render ends it at once. Exit 0; 1 for a refusal or a
failure said on stderr; 2 for a command line not understood, `--branch main`, or a variable not set or not of its
form.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import fylgja_infrahub
import httpx
import register
import yaml
from fylgja_infrahub.rows import RULE_INCOMPLETE
from hub import ADDRESS, CA, Hub, HubError, Run, connect, wait_until

TAG = "fylgja"
"""The tag whose devices are the scope."""

SCOPE = "tag:fylgja"
"""The scope the seeded network is read in: the devices tagged `TAG`."""

DEFINITION = "device-config"
"""The artifact definition, and the name of the artifact it makes for each device (`.infrahub.yml`)."""

ARTIFACT_WAIT_S = 180
"""How long a generation's artifacts are read until each is `Ready` and each changed device's checksum has moved. On a
scratch branch a first generation's three read `Ready` 27.9 s after it was asked and a regeneration's had all moved
11.5 s after; the first seed of `main` read them `Ready` 36 s after (design/verified-facts.md, "Infrahub 1.11.11")."""

QUIET_S = 10
"""Seconds apart two readings of a branch's `head` must agree before a stage's time is taken from them. After a
generation, Infrahub's own group writes stamped 2.1 to 7.9 s after the last checksum, and a write's events were first
read 0.49 to 5.92 s after its answer (design/verified-facts.md, "Infrahub 1.11.11")."""

QUIET_WAIT_S = 120
"""How long a branch's `head` is read, every `QUIET_S`, for two readings to agree."""

READER_TOKEN = "FYLGJA_INFRAHUB_TOKEN"
"""The reader's token, which `head` is read with: never the writer's."""

BRANCH_WAIT_S = 120
"""How long a branch is read for, every 2 s, after a `BranchCreate` that failed or went unanswered within `hub.py`'s
request timeout: one create's branch was listed with a `created_at` 75.1 s after the create was sent, a derivation,
past that timeout's 60 s (design/verified-facts.md, "Infrahub 1.11.11")."""


@dataclass(frozen=True)
class Edit:
    """One staged edit of the seeded branch: its label in `seed.json`, its object file under `--files`, and the devices
    whose configuration it changes, each of which the wait sees regenerated."""

    label: str
    file: str
    changes: tuple[str, ...]


EDITS = (
    Edit("third-link", "stages/1-third-link.yml", ("n1", "n3")),
    Edit("n1-address", "stages/2-n1-address.yml", ("n1",)),
)
"""The branch's two edits, in order: the cable between `n1` and `n3` that `main` lacks, after which the network is
`testdata/blueprint/three-node.json`'s; then an address on its `n1` end."""

Head = Callable[[str], str]
"""A branch's `head` by its name: `fylgja_infrahub.head` over the reader's connection, or a test's."""

DEFINITION_READ = "query ($name: String!) { CoreArtifactDefinition(name__value: $name) { edges { node { id } } } }"
BRANCH_READ = "query ($name: String) { Branch(name: $name) { name branched_from } }"
BRANCH_CREATE = (
    "mutation ($name: String!) { BranchCreate(data: {name: $name, sync_with_git: false}, wait_until_completion: true) "
    "{ ok } }"
)
BRANCH_DELETE = "mutation ($name: String!) { BranchDelete(data: {name: $name}, wait_until_completion: true) { ok } }"
MARKS_READ = "query ($branch: String!) { FylgjaStage(branch__value: $branch) { count edges { node { id } } } }"
MARK_DELETE = "mutation ($id: String!) { FylgjaStageDelete(data: {id: $id}) { ok } }"
MARK_CREATE = (
    "mutation ($branch: String!, $label: String!, $at: String!, $description: String!) { FylgjaStageCreate(data: "
    "{branch: {value: $branch}, label: {value: $label}, as_of: {value: $at}, description: {value: $description}}) "
    "{ ok object { id } } }"
)
"""A mark's create. `as_of` is sent as a `String` variable: Infrahub 1.11.11 refuses a `DateTime!` one in that
position, and answers the value as written (design/verified-facts.md, "Infrahub 1.11.11")."""
OPEN_READ = (
    'query ($branch: String!) { CoreProposedChange(source_branch__value: $branch, state__value: "open") '
    "{ count edges { node { id } } } }"
)
PROPOSED_DELETE = "mutation ($id: String!) { CoreProposedChangeDelete(data: {id: $id}) { ok } }"
PROPOSED_CREATE = (
    "mutation ($name: String!, $branch: String!) { CoreProposedChangeCreate(data: {name: {value: $name}, "
    'source_branch: {value: $branch}, destination_branch: {value: "main"}, is_draft: {value: false}}) '
    "{ ok object { id } } }"
)
SCOPE_READ = "query ($tag: String!) { DcimDevice(tags__name__value: $tag) { edges { node { name { value } } } } }"
ARTIFACTS_READ = """
query ($tag: String!, $name: String!) {
  DcimDevice(tags__name__value: $tag) {
    edges {
      node {
        name { value }
        artifacts(name__value: $name) { edges { node { status { value } checksum { value updated_at } } } }
      }
    }
  }
}
"""


def say(line: str) -> None:
    print(f"seed: {line}", flush=True)


@dataclass(frozen=True)
class Artifact:
    """A device's artifact `DEFINITION` as a branch reads it: its status, its checksum, and when Infrahub last wrote
    the checksum (its `updated_at`). The checksum and its stamp are empty where Infrahub holds none yet."""

    status: str
    checksum: str
    stamp: str


class RenderFailed(HubError):
    """A configuration whose render failed: its artifact reads `Error`."""


def definition(hub: Hub, branch: str) -> str | None:
    """The id of the artifact definition `DEFINITION` on `branch`, or None where the branch holds none."""
    edges = hub.gql(branch, DEFINITION_READ, {"name": DEFINITION})["CoreArtifactDefinition"]["edges"]
    return str(edges[0]["node"]["id"]) if edges else None


def scope(hub: Hub, branch: str) -> list[str]:
    """The names of the devices tagged `TAG` on `branch`, sorted."""
    edges = hub.gql(branch, SCOPE_READ, {"tag": TAG})["DcimDevice"]["edges"]
    return sorted(edge["node"]["name"]["value"] for edge in edges)


def artifacts(hub: Hub, branch: str, *, at: str | None = None) -> dict[str, Artifact]:
    """By device name, the artifact `DEFINITION` of each device of the scope that has one, on `branch` at the time
    `at` where it is given. A device holding two is a `HubError`."""
    found: dict[str, Artifact] = {}
    edges = hub.gql(branch, ARTIFACTS_READ, {"tag": TAG, "name": DEFINITION}, at=at)["DcimDevice"]["edges"]
    for edge in edges:
        name = edge["node"]["name"]["value"]
        held = [artifact["node"] for artifact in edge["node"]["artifacts"]["edges"]]
        if len(held) > 1:
            raise HubError(f"{name} holds {len(held)} artifacts {DEFINITION} on {branch}")
        if held:
            checksum = held[0]["checksum"]
            found[name] = Artifact(
                status=held[0]["status"]["value"], checksum=checksum["value"] or "", stamp=checksum["updated_at"] or ""
            )
    return found


def unready(
    before: Mapping[str, Artifact], now: Mapping[str, Artifact], members: Collection[str], changed: Collection[str]
) -> list[str]:
    """Why each of `members` is not yet rendered, in the order of their names: no artifact; a status other than
    `Ready`; or, for a device in `changed`, the checksum it had in `before`. A device in `changed` that had no
    artifact in `before` counts as moved."""
    reasons = []
    for name in sorted(members):
        artifact = now.get(name)
        if artifact is None:
            reasons.append(f"{name}: no artifact")
        elif artifact.status != "Ready":
            reasons.append(f"{name}: {artifact.status}")
        elif name in changed and name in before and before[name].checksum == artifact.checksum:
            reasons.append(f"{name}: not regenerated")
    return reasons


def generate(
    hub: Hub,
    branch: str,
    changed: Collection[str],
    *,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
) -> dict[str, Artifact]:
    """Ask the generation of `branch`'s configurations, and answer its devices' artifacts once each of the scope's is
    `Ready` and each of `changed` has a checksum that moved, within `ARTIFACT_WAIT_S`. An artifact reading `Error`
    ends the wait at once, a `RenderFailed` naming each such device."""
    found = definition(hub, branch)
    if found is None:
        raise HubError(
            f"{branch} holds no artifact definition {DEFINITION}: run make infrahub-register, and make the branch "
            "after its import"
        )
    members = scope(hub, branch)
    if not members:
        raise HubError(f"{branch} holds no device tagged {TAG}: nothing to generate")
    before = artifacts(hub, branch)
    started = clock()
    hub.rest("POST", f"/api/artifact/generate/{found}", params={"branch": branch}, body={"nodes": []})

    def pending(now: dict[str, Artifact]) -> list[str]:
        failed = [name for name in members if name in now and now[name].status == "Error"]
        if failed:
            raise RenderFailed(
                f"the configuration of {', '.join(failed)} failed to render on {branch}: its artifact {DEFINITION} "
                "reads Error; read the generation's task in Infrahub's task log"
            )
        return unready(before, now, members, changed)

    ready = wait_until(
        lambda: artifacts(hub, branch),
        pending,
        what=f"the configurations of {branch}'s devices",
        timeout_s=ARTIFACT_WAIT_S,
        clock=clock,
        sleep=sleep,
    )
    say(f"the configurations of {', '.join(members)} are Ready on {branch}, {clock() - started:.0f} s after the ask")
    return ready


def schemas(
    hub: Hub,
    files: Sequence[Path],
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Each schema file of `files` loaded on `main` by `infrahubctl` where `main` lacks a kind it defines, and waited
    for under `register.SCHEMA_WAIT_S` until `main` lists every kind it defines; a file whose kinds `main` holds is
    sent nothing. A file that defines no kind is a `HubError`. `main`'s kinds are read once, and again only after a
    load."""
    held = register.main_kinds(hub)
    for file in files:
        wanted = sorted(register.file_kinds(file))
        if not wanted:
            raise HubError(f"{file} defines no kind")
        if all(kind in held for kind in wanted):
            say(f"main holds {', '.join(wanted)} of {file.name} already")
            continue
        what = f"the kinds of {file.name} on main"
        loaded = register.load_schema(hub, file, wanted, what=what, clock=clock, sleep=sleep)
        held = loaded.held
        took = loaded.returned_s + loaded.listed_s
        say(f"loaded {file.name} on main: {', '.join(wanted)} listed {took:.0f} s after the load was sent")


def registered(hub: Hub) -> None:
    """A `HubError` where `main` holds no artifact definition `DEFINITION`, which this repository's import makes."""
    if definition(hub, "main") is None:
        raise HubError(f"main holds no artifact definition {DEFINITION}: run make infrahub-register")


def fixture_devices(files: Path) -> list[str]:
    """The names of the devices the object files in `files` say, sorted."""
    names: list[str] = []
    for path in sorted(files.glob("*.yml")):
        for document in yaml.safe_load_all(path.read_text()):
            spec = (document or {}).get("spec") or {}
            if spec.get("kind") == "DcimDevice":
                names += [item["name"] for item in spec.get("data") or []]
    return sorted(names)


def baseline(
    hub: Hub,
    files: Path,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """The fixture network on `main` from the object files in `files`, and its configurations `Ready`."""
    registered(hub)
    wanted = fixture_devices(files)
    held = scope(hub, "main")
    missing = [name for name in wanted if name not in held]
    if held and missing:
        present = [name for name in wanted if name in held]
        holds = (
            f"main holds {', '.join(present)} and lacks {', '.join(missing)} of the fixture's devices"
            if present
            else f"main holds {', '.join(held)} tagged {TAG}, none of them the fixture's devices {', '.join(wanted)}"
        )
        raise HubError(
            f"{holds}: no state this target makes; start from an empty instance with make infrahub-down PURGE=1, "
            "make infrahub-up and make infrahub-register"
        )
    if held:
        say(f"main holds the fixture's devices {', '.join(wanted)} already: loading nothing")
        made: list[str] = []
    else:
        for path in sorted(files.glob("*.yml")):
            hub.ctl("object", "load", str(path), "--branch", "main")
            say(f"loaded {path.name} on main")
        made = scope(hub, "main")
    generate(hub, "main", made, clock=clock, sleep=sleep)


def listed(hub: Hub, name: str) -> dict[str, str] | None:
    """The branch `name` as Infrahub lists it, its `name` and `branched_from`, or None where it is not there."""
    found = [made for made in hub.gql("main", BRANCH_READ, {"name": name})["Branch"] if made["name"] == name]
    return found[0] if found else None


def settled(head: Head, name: str, *, clock: Callable[[], float], sleep: Callable[[float], None]) -> str:
    """`head(name)`, verbatim, once two readings of it `QUIET_S` apart agree: read every `QUIET_S`, within
    `QUIET_WAIT_S`. A `head` refused for lists not whole alone (`read.incomplete`) is a reading that agrees with none,
    and is read again; a lapse then says the last refusal. A refusal of any other rule is raised at once."""
    held: list[tuple[str | None, float]] = []
    refused: list[str] = []

    def read() -> tuple[str | None, float]:
        answered: str | None = None
        try:
            answered = head(name)
        except fylgja_infrahub.Refused as e:
            if not e.findings or any(finding.rule != RULE_INCOMPLETE for finding in e.findings):
                raise
            refused.append(str(e))
        held.append((answered, clock()))
        return held[-1]

    def pending(reading: tuple[str | None, float]) -> list[str]:
        answered, when = reading
        if answered is not None and len(held) > 1 and held[-2][0] == answered and when - held[-2][1] >= QUIET_S:
            return []
        said = f"its head, {answered}, has not read the same {QUIET_S} s on" if answered else "its head was refused"
        return [said, f"the last refusal: {refused[-1]}"] if refused else [said]

    answered, _ = wait_until(
        read,
        pending,
        what=f"{name}'s head standing still for {QUIET_S} s",
        timeout_s=QUIET_WAIT_S,
        poll_s=QUIET_S,
        clock=clock,
        sleep=sleep,
    )
    assert answered is not None, "a refused reading is never one that agrees"
    return answered


def ids(hub: Hub, query: str, root: str, name: str) -> list[str]:
    """The ids `root` answers to `query` for the branch `name` on `main`; an answer holding fewer than its own `count`
    is a `HubError`, since what it leaves out would be left behind."""
    answer = hub.gql("main", query, {"branch": name})[root]
    found = [str(edge["node"]["id"]) for edge in answer["edges"]]
    if answer["count"] != len(found):
        raise HubError(f"{root} of {name} counted {answer['count']} and answered {len(found)}")
    return found


def deleted(hub: Hub, query: str, root: str, node: str, what: str) -> None:
    """Delete the node `node`, by its id, with `query`; an answer with no `ok` is a `HubError` naming `what`."""
    answer = hub.gql("main", query, {"id": node}).get(root)
    if not (isinstance(answer, dict) and answer.get("ok") is True):
        raise HubError(f"deleting {what}, an earlier seed's: {root} answered no ok")


def clear(hub: Hub, name: str) -> None:
    """Remove what an earlier seed left of the branch `name` on `main`, whether or not the branch is listed: every
    `FylgjaStage` naming it, then its open proposed change. A mark outlives its branch (D-088), and a branch deleted
    under an open proposed change leaves it open (design/verified-facts.md, "Infrahub 1.11.11")."""
    marks = ids(hub, MARKS_READ, "FylgjaStage", name)
    for held in marks:
        deleted(hub, MARK_DELETE, "FylgjaStageDelete", held, f"the mark {held} of {name}")
    if marks:
        say(f"removed {len(marks)} marks of {name}, an earlier seed's")
    for change in ids(hub, OPEN_READ, "CoreProposedChange", name):
        deleted(hub, PROPOSED_DELETE, "CoreProposedChangeDelete", change, f"the proposed change {change} of {name}")
        say(f"removed the open proposed change {change} of {name}, an earlier seed's")


def described(edit: Edit) -> str:
    """The description of the mark of `edit`'s stage."""
    return f"the seed's stage {edit.label}: {edit.file} and its configurations"


def mark(hub: Hub, name: str, edit: Edit, at: str) -> None:
    """One `FylgjaStage` on `main` naming the branch `name`, `edit`'s label, `at` as its `as_of`, verbatim, and
    `described(edit)`; an answer with no `ok` is a `HubError`."""
    variables = {"branch": name, "label": edit.label, "at": at, "description": described(edit)}
    answer = hub.gql("main", MARK_CREATE, variables).get("FylgjaStageCreate")
    if not (isinstance(answer, dict) and answer.get("ok") is True):
        raise HubError(f"marking {edit.label} of {name}: FylgjaStageCreate answered no ok")
    say(f"marked {edit.label} of {name} at {at}")


def propose(hub: Hub, name: str) -> dict[str, str]:
    """The branch `name`'s proposed change into `main`, not a draft, named `Rehearse <name>`: its id and name."""
    title = f"Rehearse {name}"
    answer = hub.gql("main", PROPOSED_CREATE, {"name": title, "branch": name}).get("CoreProposedChangeCreate")
    if not (isinstance(answer, dict) and answer.get("ok") is True and isinstance(answer.get("object"), dict)):
        raise HubError(f"proposing {name}: CoreProposedChangeCreate answered no ok")
    made = {"id": str(answer["object"]["id"]), "name": title}
    say(f"made the proposed change {made['id']}, {title}, of {name} into main")
    return made


def remove(hub: Hub, name: str, *, clock: Callable[[], float]) -> None:
    """Delete the branch `name` an earlier seed left; a delete that answers no `ok` is a `HubError` naming it, since
    the branch it leaves would be listed after the create failed and taken for the new one. Its marks and its open
    proposed change are removed before, by `clear`."""
    started = clock()
    answer = hub.gql("main", BRANCH_DELETE, {"name": name}).get("BranchDelete")
    if not (isinstance(answer, dict) and answer.get("ok") is True):
        raise HubError(f"deleting {name}, an earlier seed's: BranchDelete answered no ok")
    say(f"deleted {name}, an earlier seed's, in {clock() - started:.0f} s")


def make(hub: Hub, name: str, *, clock: Callable[[], float], sleep: Callable[[float], None]) -> None:
    """Make the branch `name` from `main`, with `sync_with_git: false`. A create that fails or goes unanswered within
    the request's timeout can make its branch all the same, once 75.1 s after it was sent (design/verified-facts.md,
    "Infrahub 1.11.11"), so the branch is then read for until it is listed, within `BRANCH_WAIT_S`."""
    started = clock()
    failed: str | None = None
    try:
        answer = hub.gql("main", BRANCH_CREATE, {"name": name})["BranchCreate"]
    except HubError as e:
        failed = str(e)
    else:
        if not (isinstance(answer, dict) and answer.get("ok") is True):
            failed = f"BranchCreate answered {answer}"
    if failed is None:
        say(f"made {name} from main in {clock() - started:.0f} s")
        return
    say(f"{name}: its BranchCreate failed ({failed}); reading for the branch")
    wait_until(
        lambda: listed(hub, name),
        lambda made: [] if made else [f"{name} is not listed"],
        what=f"{name}, after its BranchCreate failed ({failed}),",
        timeout_s=BRANCH_WAIT_S,
        clock=clock,
        sleep=sleep,
    )
    say(f"{name} is listed, {clock() - started:.0f} s after its BranchCreate was sent")


def branch(
    hub: Hub,
    name: str,
    files: Path,
    *,
    head: Head,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict[str, str]]:
    """The seeded branch `name` made anew from `main`, an earlier seed's marks and open proposed change of it removed
    first, and each of `EDITS` on it in order: its object file under `files` loaded, its configurations generated and
    waited for until each device it changes shows a checksum that moved, its time `head(name)`, verbatim, once two
    readings of it `QUIET_S` apart agree, and its mark at that time. Answers the stages, each its `label` and its
    `at`, which are the marks'."""
    clear(hub, name)
    if listed(hub, name) is not None:
        remove(hub, name, clock=clock)
    make(hub, name, clock=clock, sleep=sleep)
    if definition(hub, name) is None:
        raise HubError(
            f"{name} holds no artifact definition {DEFINITION}: run make infrahub-register, then make infrahub-seed"
        )
    stages = []
    for edit in EDITS:
        hub.ctl("object", "load", str(files / edit.file), "--branch", name)
        say(f"loaded {edit.file} on {name}")
        generate(hub, name, edit.changes, clock=clock, sleep=sleep)
        at = settled(head, name, clock=clock, sleep=sleep)
        say(f"{edit.label} is read at {at} on {name}")
        mark(hub, name, edit, at)
        stages.append({"label": edit.label, "at": at})
    return stages


def write(
    path: Path,
    branch: str,
    stages: Sequence[Mapping[str, str]],
    *,
    marks: Sequence[str] = (),
    proposed_change: Mapping[str, str] | None = None,
) -> None:
    """`seed.json` at `path`: the branch, the scope, each stage's label and time, in order, the marks' labels, in
    order, and the proposed change's id and name, or null, written beside it and renamed over it, so that no reader
    meets a part of it."""
    record = {
        "branch": branch,
        "scope": SCOPE,
        "stages": [{"label": s["label"], "at": s["at"]} for s in stages],
        "marks": list(marks),
        "proposed_change": {"id": proposed_change["id"], "name": proposed_change["name"]} if proposed_change else None,
    }
    written = path.with_name(f".{path.name}.part")
    written.write_text(json.dumps(record, indent=2) + "\n")
    written.replace(path)


class ReaderUnset(Exception):
    """The reader's connection cannot be made from the environment: a variable not set, or not of its form."""


def reader(transport: httpx.BaseTransport | None) -> fylgja_infrahub.Infrahub:
    """The reader's connection, with the reader's token, `FYLGJA_INFRAHUB_TOKEN`, never the writer's, its version read.
    A variable not set, or not of its form, is `ReaderUnset` naming it; Infrahub refusing the token, or not reached,
    an `InfrahubError`."""
    address, token, ca = (os.environ.get(name, "") for name in (ADDRESS, READER_TOKEN, CA))
    if not token:
        raise ReaderUnset(f"{READER_TOKEN} is not set: each stage's time is the reader's head, read with it")
    try:
        return fylgja_infrahub.connect(address, token, ca=Path(ca) if ca else None, transport=transport)
    except ValueError as e:
        # InvalidAddress, InvalidToken and InvalidCA, each a predicate that repeats nothing.
        raise ReaderUnset(f"the reader's {ADDRESS}, {READER_TOKEN} or {CA}: {e}") from None


def heads(conn: fylgja_infrahub.Infrahub) -> Head:
    """The reader's `head` of a branch by its name, under `SCOPE`, over `conn`."""

    def head(name: str) -> str:
        return fylgja_infrahub.head(conn, branch=name, scope=SCOPE)

    return head


def parser() -> argparse.ArgumentParser:
    made = argparse.ArgumentParser(prog="seed.py", description=(__doc__ or "").splitlines()[0])
    made.add_argument("--branch", required=True, help="the seeded branch, made from main")
    made.add_argument("--files", type=Path, required=True, help="the object files, under main/ and stages/")
    made.add_argument("--out", type=Path, required=True, help="where the seed's record is written")
    made.add_argument("--ctl", type=Path, required=True, help="infrahubctl, in a venv of its own")
    made.add_argument(
        "--schema",
        type=Path,
        action="append",
        default=[],
        metavar="FILE",
        help="a schema file loaded on main where main lacks a kind of it, before the network; repeatable",
    )
    made.add_argument(
        "--proposed-change",
        action="store_true",
        help="make the branch's proposed change into main, not a draft, last; without it the seed makes none",
    )
    return made


def main(
    argv: Sequence[str],
    *,
    transport: httpx.BaseTransport | None = None,
    run: Run = subprocess.run,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    head: Head | None = None,
) -> int:
    """The seed run whole, as `make infrahub-seed` runs it. Each stage's time is `head` of the branch: where it is
    None, the reader's, over a connection the reader makes with `FYLGJA_INFRAHUB_ADDRESS`, `FYLGJA_INFRAHUB_TOKEN` and,
    where set, `FYLGJA_INFRAHUB_CA`; a test gives its own."""
    try:
        args = parser().parse_args(argv)
    except SystemExit as e:
        return 0 if e.code in (0, None) else 2
    if args.branch == "main":
        print("seed: --branch main: the seeded branch is made from main, and is not main", file=sys.stderr)
        return 2
    try:
        hub = connect(os.environ, ctl=args.ctl, transport=transport, run=run)
    except HubError as e:
        print(f"seed: {e}", file=sys.stderr)
        return 2
    conn: fylgja_infrahub.Infrahub | None = None
    if head is None:
        try:
            conn = reader(transport)
        except (ReaderUnset, fylgja_infrahub.InfrahubError) as e:
            print(f"seed: {e}", file=sys.stderr)
            hub.close()
            return 2 if isinstance(e, ReaderUnset) else 1
        head = heads(conn)
    try:
        args.out.unlink(missing_ok=True)
        registered(hub)
        schemas(hub, args.schema, clock=clock, sleep=sleep)
        baseline(hub, args.files / "main", clock=clock, sleep=sleep)
        stages = branch(hub, args.branch, args.files, head=head, clock=clock, sleep=sleep)
        proposed = propose(hub, args.branch) if args.proposed_change else None
        write(args.out, args.branch, stages, marks=[stage["label"] for stage in stages], proposed_change=proposed)
    except (
        HubError,
        fylgja_infrahub.InfrahubError,
        fylgja_infrahub.Refused,
        OSError,
        ValueError,
        yaml.YAMLError,
    ) as e:
        print(f"seed: {e}", file=sys.stderr)
        return 1
    finally:
        hub.close()
        if conn is not None:
            conn.close()
    say(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
