"""`netbox/seed/change.py`: the seeded change, a branch built in steps and marked at each.

NetBox is `fake.FakeNetBox` over a `main` the seed has filled, the mark's command a recorder of this file's and the
clock a fake: nothing here opens a socket or starts a process. The tokens are values of the tests' own.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import change
import httpx
import pytest
import seed
from box import ADDRESS as ADDRESS_NAME
from box import BRANCH_WAIT_S, Box, BoxError
from box import TOKEN as TOKEN_NAME
from fake import ADDRESS, FakeNetBox

SEED = Path(__file__).resolve().parents[1] / "seed"
TOKEN = "nbt_k.t"
NAME = "third-link"
TAG = "fylgja-rehearse"
BRANCHES = "plugins/branching/branches/"
CABLES, ADDRESSES, TAGS = "dcim/cables/", "ipam/ip-addresses/", "extras/tags/"

MARK = [
    "python3",
    "-I",
    "scripts/edge_dev.py",
    "run",
    "--source",
    "netbox",
    "--local",
    "/srv/example/fylgja-core/local",
    "--main",
    "/srv/example/fylgja-core",
    "--",
    "stage",
    "mark",
]
"""The mark's command as `make netbox-change` gives it, after the first `--`."""


class Clock:
    """A clock that moves only when its `sleep` is called."""

    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


class Child:
    """The mark's command: each run kept with how many requests NetBox had been sent before it, answered `exits`' next
    status, 0 where none is left."""

    def __init__(self, fake: FakeNetBox, *exits: int) -> None:
        self.fake = fake
        self.exits = list(exits)
        self.runs: list[tuple[list[str], int, dict[str, Any]]] = []

    def __call__(self, argv: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.runs.append((list(argv), len(self.fake.requests), kwargs))
        return subprocess.CompletedProcess(list(argv), self.exits.pop(0) if self.exits else 0)


def over(fake: FakeNetBox) -> Box:
    return Box(ADDRESS, TOKEN, transport=httpx.MockTransport(fake))


def seeded() -> FakeNetBox:
    """A fake whose `main` the seed has filled, its requests forgotten."""
    fake = FakeNetBox()
    seed.seed(over(fake), SEED)
    fake.requests.clear()
    return fake


def environ() -> dict[str, str]:
    return {ADDRESS_NAME: ADDRESS, TOKEN_NAME: TOKEN}


def run(
    fake: FakeNetBox, child: Child, capsys: pytest.CaptureFixture[str], *flags: str
) -> tuple[int, str, str]:
    code = change.main(["--branch", NAME, *flags, "--", *MARK], environ=environ(), box=over(fake), run=child)
    out, err = capsys.readouterr()
    return code, out, err


def writes(fake: FakeNetBox) -> list[tuple[str, str, str | None]]:
    """Each request that is not a `GET`: its method, its path under `/api/` and the branch header it carried."""
    return [
        (request.method, request.url.path.removeprefix("/api/"), request.headers.get("X-NetBox-Branch"))
        for request in fake.requests
        if request.method != "GET"
    ]


def the_branch(fake: FakeNetBox) -> dict[str, Any]:
    [made] = fake.objects[BRANCHES].values()
    return made


def test_the_steps_are_the_infrahub_seeds_two() -> None:
    """The cable `main` lacks of `testdata/blueprint/three-node.json`'s links, and an address in the documentation
    range on the port it cabled (`infrahub/seed/stages/`)."""
    assert change.STEPS == (
        ("third-link", "cable", ("n1:ethernet-1/2", "n3:ethernet-1/2")),
        ("n1-address", "address", ("192.0.2.1/24", "n1:ethernet-1/2")),
    )
    assert change.TAG == TAG


def test_a_branch_of_the_name_is_deleted_and_made_anew_before_any_step(capsys: pytest.CaptureFixture[str]) -> None:
    """A second build of the change: the branch an earlier one left, its marks with it, is deleted before the branch
    is made again from `main`, so that no label is ever taken twice and no mark of an earlier build stands."""
    fake = seeded()
    old = fake.add(BRANCHES, {"name": NAME})
    fake.add(CABLES, {"a_terminations": [], "b_terminations": [], "status": "connected"}, branch=old["schema_id"])
    child = Child(fake)
    code, out, err = run(fake, child, capsys)
    assert (code, err) == (0, "")

    new = the_branch(fake)
    assert new["id"] != old["id"] and new["name"] == NAME
    assert old["schema_id"] not in fake.branched
    assert writes(fake)[:2] == [("DELETE", f"{BRANCHES}{old['id']}/", None), ("POST", BRANCHES, None)]
    first_step = next(at for at, request in enumerate(fake.requests) if request.url.path == f"/api/{CABLES}")
    made_at = next(at for at, request in enumerate(fake.requests) if request.method == "POST")
    assert made_at < first_step < child.runs[0][1]
    said = out.splitlines()
    assert said[:3] == [
        f"change: the branch {NAME} stands: deleting it, and every journal entry on it, its marks among them, to build "
        "it anew from main",
        f"change: deleted the branch {NAME}",
        f"change: made the branch {NAME}",
    ]


def test_the_branch_is_said_deleted_before_its_delete_is_sent(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """What is about to be deleted is said before the `DELETE` is sent, and that it was deleted after: a run stopped
    between the two has said what it was doing."""
    fake = seeded()
    old = fake.add(BRANCHES, {"name": NAME})
    events: list[str] = []
    said = change.say

    def say(line: str, *, err: bool = False) -> None:
        events.append(line)
        said(line, err=err)

    monkeypatch.setattr(change, "say", say)

    def heard(request: httpx.Request) -> httpx.Response:
        events.append(f"{request.method} {request.url.path.removeprefix('/api/')}")
        return fake(request)

    change.branch(Box(ADDRESS, TOKEN, transport=httpx.MockTransport(heard)), NAME, clock=Clock(), sleep=Clock().sleep)
    capsys.readouterr()
    warned = next(at for at, event in enumerate(events) if event.startswith(f"the branch {NAME} stands: deleting it"))
    deleted = events.index(f"DELETE {BRANCHES}{old['id']}/")
    assert warned < deleted < events.index(f"deleted the branch {NAME}")


def test_the_help_says_a_branch_of_the_name_is_deleted(capsys: pytest.CaptureFixture[str]) -> None:
    assert change.main(["--help"], environ=environ(), run=Child(FakeNetBox())) == 0
    out = " ".join(capsys.readouterr().out.split())
    assert "a branch of this name is deleted first" in out and "every journal entry on it" in out


def test_a_branch_still_provisioning_is_waited_ready_before_its_delete() -> None:
    """NetBox refuses the `DELETE` of a branch still provisioning (design/verified-facts.md, "A branch deleted before
    it is `ready`"): it is waited for through `box.branched`, at its bound, and deleted once `ready`."""
    fake = seeded()
    old = fake.add(BRANCHES, {"name": NAME, "status": "provisioning"})
    clock = Clock()
    made = change.branch(over(fake), NAME, clock=clock, sleep=clock.sleep)
    assert made["id"] != old["id"] and made["status"] == {"value": "ready"}
    assert [(r.method, r.url.path.removeprefix("/api/")) for r in fake.requests][:4] == [
        ("GET", BRANCHES),
        ("GET", BRANCHES),
        ("GET", f"{BRANCHES}{old['id']}/"),
        ("DELETE", f"{BRANCHES}{old['id']}/"),
    ]
    assert clock.slept == [1.0]


@pytest.mark.parametrize("status", ["merged", "failed"])
def test_a_branch_netbox_was_not_read_deleting_is_refused_by_its_status(
    status: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Refused before anything is said of a delete, since nothing is deleted."""
    fake = seeded()
    fake.add(BRANCHES, {"name": NAME, "status": status})
    clock = Clock()
    with pytest.raises(BoxError) as raised:
        change.branch(over(fake), NAME, clock=clock, sleep=clock.sleep)
    assert NAME in str(raised.value) and status in str(raised.value)
    assert writes(fake) == [] and clock.slept == []
    assert "delet" not in capsys.readouterr().out


def test_a_branch_that_never_reads_ready_is_refused_at_the_bound_and_not_deleted(
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = seeded()
    old = fake.add(BRANCHES, {"name": NAME, "status": "provisioning"})

    def stuck(request: httpx.Request) -> httpx.Response:
        fake.objects[BRANCHES][old["id"]]["status"] = "new"
        return fake(request)

    clock = Clock()
    with pytest.raises(BoxError) as raised:
        change.branch(Box(ADDRESS, TOKEN, transport=httpx.MockTransport(stuck)), NAME, clock=clock, sleep=clock.sleep)
    assert "provisioning" in str(raised.value)
    assert writes(fake) == [] and sum(clock.slept) == BRANCH_WAIT_S
    assert "delet" not in capsys.readouterr().out


def test_each_step_is_written_under_the_branchs_header_then_marked(capsys: pytest.CaptureFixture[str]) -> None:
    fake = seeded()
    cables, addresses = len(fake.rows(CABLES)), len(fake.rows(ADDRESSES))
    child = Child(fake)
    code, out, err = run(fake, child, capsys)
    assert (code, err) == (0, "")

    schema = the_branch(fake)["schema_id"]
    assert writes(fake) == [("POST", BRANCHES, None), ("POST", CABLES, schema), ("POST", ADDRESSES, schema)]
    n1, n3 = fake.port("n1", "ethernet-1/2")["id"], fake.port("n3", "ethernet-1/2")["id"]
    [cable] = fake.branched[schema][CABLES].values()
    assert [end["object_id"] for end in cable["a_terminations"] + cable["b_terminations"]] == [n1, n3]
    [address] = fake.branched[schema][ADDRESSES].values()
    assert (address["address"], address["assigned_object_type"], address["assigned_object_id"]) == (
        "192.0.2.1/24",
        "dcim.interface",
        n1,
    )
    assert (len(fake.rows(CABLES)), len(fake.rows(ADDRESSES))) == (cables, addresses)

    assert [argv for argv, _, _ in child.runs] == [
        [*MARK, "--branch", NAME, "--label", "third-link"],
        [*MARK, "--branch", NAME, "--label", "n1-address"],
    ]
    cabled = next(at for at, request in enumerate(fake.requests) if request.url.path == f"/api/{CABLES}")
    addressed = next(at for at, request in enumerate(fake.requests) if request.url.path == f"/api/{ADDRESSES}")
    assert cabled < child.runs[0][1] <= addressed < child.runs[1][1]
    assert all("env" not in kwargs and "stderr" not in kwargs for _, _, kwargs in child.runs)
    assert out.splitlines()[1:5] == [
        f"change: wrote third-link on the branch {NAME}: the cable n1:ethernet-1/2 to n3:ethernet-1/2",
        "change: marked third-link",
        f"change: wrote n1-address on the branch {NAME}: the address 192.0.2.1/24 on n1:ethernet-1/2",
        "change: marked n1-address",
    ]


def test_a_mark_refused_stops_the_change_and_names_the_step(capsys: pytest.CaptureFixture[str]) -> None:
    fake = seeded()
    fake.add(TAGS, {"name": TAG, "slug": TAG, "object_types": ["netbox_branching.branch"]})
    child = Child(fake, 1)
    code, out, err = run(fake, child, capsys, "--tag")
    assert code == 1
    [line] = err.splitlines()
    assert "third-link" in line and "exited 1" in line and "make netbox-change" in line
    assert len(child.runs) == 1
    schema = the_branch(fake)["schema_id"]
    assert writes(fake) == [("POST", BRANCHES, None), ("POST", CABLES, schema)]
    assert "change: marked third-link" not in out


def test_the_tag_is_set_last_and_only_by_the_flag(capsys: pytest.CaptureFixture[str]) -> None:
    fake = seeded()
    tag = fake.add(TAGS, {"name": TAG, "slug": TAG, "object_types": ["netbox_branching.branch"]})
    code, out, _ = run(fake, Child(fake), capsys)
    assert code == 0
    assert the_branch(fake)["tags"] == []
    assert not any(method == "PATCH" for method, _, _ in writes(fake))
    assert f"set the tag {TAG} on it to ask for its rehearsal" in out.splitlines()[-1]

    fake.requests.clear()
    child = Child(fake)
    code, out, _ = run(fake, child, capsys, "--tag")
    assert code == 0
    made = the_branch(fake)
    assert made["tags"] == [tag["id"]]
    assert writes(fake)[-1] == ("PATCH", f"{BRANCHES}{made['id']}/", None)
    assert fake.sent("PATCH") == [(f"{BRANCHES}{made['id']}/", {"tags": [tag["id"]]})]
    assert child.runs[-1][1] < len(fake.requests) - 1
    said = out.splitlines()
    assert said[-2] == f"change: set the tag {TAG} on the branch {NAME}"
    assert "asks for its rehearsal" in said[-1] and "set it again" in said[-1]


def test_the_tag_netbox_does_not_hold_is_refused_in_one_line_before_anything(
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake = seeded()
    child = Child(fake)
    code, out, err = run(fake, child, capsys, "--tag")
    assert (code, out) == (1, "")
    [line] = err.splitlines()
    assert TAG in line and "make netbox-hook" in line
    assert writes(fake) == [] and child.runs == []


@pytest.mark.parametrize(
    "argv",
    [["--branch", NAME], ["--branch", NAME, "--"], ["--", *MARK], ["--branch", NAME, "--colour", "--", *MARK]],
    ids=["no mark", "an empty mark", "no branch", "a flag not understood"],
)
def test_a_command_line_not_understood_is_exit_2(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    fake = seeded()
    child = Child(fake)
    assert change.main(argv, environ=environ(), box=over(fake), run=child) == 2
    assert fake.requests == [] and child.runs == []


@pytest.mark.parametrize("name", [ADDRESS_NAME, TOKEN_NAME])
def test_a_variable_not_set_is_exit_2_naming_it(name: str, capsys: pytest.CaptureFixture[str]) -> None:
    fake = seeded()
    given = {key: value for key, value in environ().items() if key != name}
    assert change.main(["--branch", NAME, "--", *MARK], environ=given, box=over(fake), run=Child(fake)) == 2
    assert name in capsys.readouterr().err
    assert fake.requests == []


def test_the_change_imports_the_standard_library_and_box_alone() -> None:
    """It runs alone beside `box.py`: not httpx, nothing of Fylgja's packages, and neither the hook nor the seed. It
    marks a step by running the example's own command, and holds the tag's slug by value
    (`orchestrator/tests/test_dev_plumbing.py` holds it equal)."""
    tree = ast.parse((SEED / "change.py").read_text())
    nodes = list(ast.walk(tree))
    named = {alias.name.split(".")[0] for node in nodes if isinstance(node, ast.Import) for alias in node.names}
    named |= {str(node.module).split(".")[0] for node in nodes if isinstance(node, ast.ImportFrom) and node.level == 0}
    assert named - set(sys.stdlib_module_names) == {"box"}
