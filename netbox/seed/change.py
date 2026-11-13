"""The seeded change on the development NetBox: a branch built in steps, each step marked as soon as it exists, as the
Infrahub seed's `third-link` is built (D-097).

Run by `make netbox-change` as `core/.venv/bin/python netbox/seed/change.py --branch <name> [--tag] -- <the mark's
command>`, with `local/.env` loaded for `FYLGJA_NETBOX_ADDRESS` and the superuser's `FYLGJA_NETBOX_WRITE_TOKEN`
(D-042), once `make netbox-seed` has made `main` the fixture and the core runs at `FYLGJA_API_ADDRESS`, since a mark's
blueprint is the core's:

- the branch of that name, where one stands, is deleted, and every journal entry on it with it, its marks of an
  earlier build among them: a label is unique within its branch, NetBox reads no branch as it stood earlier, and a
  change is seeded and marked once for each core (D-097), so a change is built again whole and never added to. A branch
  still `new` or `provisioning` is waited for until `ready` first (`box.branched`), since NetBox refuses its `DELETE`;
  one in any other status is refused by its status, nothing deleted. Then the branch is made from `main` and waited
  for until `ready` (`box.branched`);
- each of `STEPS` is written under the branch's header and then marked: the mark's command, the words after `--` with
  `--branch <name> --label <label>`, is run as a child in this environment, its output its own. `make netbox-change`
  gives `scripts/edge_dev.py run --source netbox -- stage mark`, the example's own command under the example's own
  token, which `edge_dev.py` alone reads and this never does. A mark refused stops the change: the branch is left as it
  stands, for reading, and the next run deletes it and builds it again;
- with `--tag`, last, the tag `TAG` is added to the branch's tags, which asks for the rehearsal: refused before
  anything is written where NetBox holds no such tag, which `make netbox-hook` makes.

It prints each step as it is written and as it is marked. Its last line says how the rehearsal is asked: the tag set
on the branch, which the rehearsal takes off; a request lost is not sent again, and setting the tag again asks again.
Exit 0; 1 for a refusal or a failure said on stderr, a mark refused among them; 2 for a command line not understood
or a variable not set.

Run by `core/.venv/bin/python`; `box` and the standard library alone, never httpx itself, `fylgja_core`, a reader, the
example, the hook or a client library of NetBox's: what it shares with the example, it holds by value.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from box import ADDRESS, BRANCHES, TOKEN, Box, BoxError, branch_named, branched

TAG = "fylgja-rehearse"
"""The slug of the tag that asks for a rehearsal: `fylgja_orchestrator.netbox.TAG`, held by value."""

STEPS = (
    ("third-link", "cable", ("n1:ethernet-1/2", "n3:ethernet-1/2")),
    ("n1-address", "address", ("192.0.2.1/24", "n1:ethernet-1/2")),
)
"""The change's steps, in order, each its mark's label, the kind of object it writes and that object: the cable `main`
lacks of `testdata/blueprint/three-node.json`'s links, by its two ends, `<device>:<port>`; then an address in the
documentation range on the port it cabled, by its value and its port. They are `infrahub/seed/stages/`' two edits."""

UNSETTLED = ("new", "provisioning")
"""The statuses of a branch that is waited for until `ready` before its `DELETE`, which NetBox refuses 500 in them
(design/verified-facts.md, "A branch deleted before it is `ready`")."""

INTERFACE = "dcim.interface"

Run = Callable[..., subprocess.CompletedProcess[Any]]


class ChangeError(Exception):
    """A change that cannot be built, or a mark refused, in one sentence."""


def say(line: str, *, err: bool = False) -> None:
    print(f"change: {line}", file=sys.stderr if err else sys.stdout, flush=True)


def branch(
    box: Box,
    name: str,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """The branch `name` made anew from `main` and `ready`, its representation: one of that name deleted first where it
    stands, as the module says, and read gone. A `BoxError` where it cannot be deleted or made."""
    standing = branch_named(box, name)
    if standing is not None:
        status = standing.get("status")
        value = status.get("value") if isinstance(status, dict) else None
        if value in UNSETTLED:
            standing = branched(box, name, clock=clock, sleep=sleep)
        elif value != "ready":
            raise BoxError(
                f"the branch {name} is {value}, and a DELETE of a branch {value} was never read: delete it in NetBox, "
                "or name another branch"
            )
        say(
            f"the branch {name} stands: deleting it, and every journal entry on it, its marks among them, to build it "
            "anew from main"
        )
        box.delete(f"{BRANCHES}{standing['id']}/")
        if branch_named(box, name) is not None:
            raise BoxError(f"the branch {name} still stands after its DELETE")
        say(f"deleted the branch {name}")
    made = branched(box, name, clock=clock, sleep=sleep)
    if not isinstance(made.get("schema_id"), str):
        raise BoxError(f"the branch {name} answered no schema_id")
    say(f"made the branch {name}")
    return made


def port(box: Box, schema_id: str, end: str) -> int:
    """The id of the port `end`, `<device>:<port>`, as the branch whose `schema_id` is given holds it."""
    device_name, _, name = end.partition(":")
    device = box.one("dcim/devices/", branch=schema_id, name=device_name)
    if device is None:
        raise ChangeError(f"the branch holds no device {device_name}: make netbox-seed makes main the fixture")
    found = box.one("dcim/interfaces/", branch=schema_id, device_id=device["id"], name=name)
    if found is None:
        raise ChangeError(f"the branch holds no port {end}: make netbox-seed makes main the fixture")
    return int(found["id"])


def step(box: Box, schema_id: str, label: str) -> str:
    """The step `label` of `STEPS` written under the header of the branch whose `schema_id` is given, and never on
    `main`; what it wrote, said."""
    kinds = {held: (kind, values) for held, kind, values in STEPS}
    if label not in kinds:
        raise ValueError(f"{label} is no step of the change")
    kind, values = kinds[label]
    if kind == "cable":
        a, b = (port(box, schema_id, end) for end in values)
        box.post(
            "dcim/cables/",
            {
                "a_terminations": [{"object_type": INTERFACE, "object_id": a}],
                "b_terminations": [{"object_type": INTERFACE, "object_id": b}],
                "status": "connected",
            },
            branch=schema_id,
        )
        return f"the cable {values[0]} to {values[1]}"
    address, end = values
    box.post(
        "ipam/ip-addresses/",
        {
            "address": address,
            "status": "active",
            "assigned_object_type": INTERFACE,
            "assigned_object_id": port(box, schema_id, end),
        },
        branch=schema_id,
    )
    return f"the address {address} on {end}"


def marked(mark: Sequence[str], name: str, label: str, *, run: Run = subprocess.run) -> None:
    """The step `label` of the branch `name` marked by the mark's command `mark`, `--branch <name> --label <label>`
    appended, run as a child given this environment as it is, its output and its errors its own; any exit but 0 is a
    `ChangeError` naming the step and the exit."""
    done = run([*mark, "--branch", name, "--label", label], check=False)
    if done.returncode != 0:
        raise ChangeError(
            f"the step {label} was written on the branch {name} and its mark exited {done.returncode}: the branch is "
            "left as it stands for reading, and make netbox-change deletes it and builds it again"
        )


def tagged(box: Box, made: Mapping[str, Any], tag: Mapping[str, Any]) -> None:
    """The tag `tag` added to the branch `made`'s tags, each other tag kept."""
    path = f"{BRANCHES}{made['id']}/"
    held = box.get(path)
    tags = [row["id"] for row in (held.get("tags") or [])] if isinstance(held, dict) else []
    box.patch(path, {"tags": [*tags, tag["id"]] if tag["id"] not in tags else tags})


def parser() -> argparse.ArgumentParser:
    made = argparse.ArgumentParser(
        prog="change.py",
        description=(__doc__ or "").splitlines()[0],
        usage="change.py --branch NAME [--tag] -- MARK…",
        epilog="MARK…, after --, is the mark's command: make netbox-change gives the example's stage mark.",
    )
    made.add_argument(
        "--branch",
        required=True,
        metavar="NAME",
        help="the branch to build: a branch of this name is deleted first, with every journal entry on it, its marks "
        "among them, and made anew from main",
    )
    made.add_argument("--tag", action="store_true", help=f"set the tag {TAG} on the branch last: asks for a rehearsal")
    return made


def main(
    argv: Sequence[str],
    *,
    environ: Mapping[str, str] = os.environ,
    box: Box | None = None,
    run: Run = subprocess.run,
) -> int:
    """The change built and marked, as `make netbox-change` runs it; `box` and `run`, NetBox and the mark's command,
    where a test gives them."""
    words = list(argv)
    cut = words.index("--") if "--" in words else len(words)
    mark = words[cut + 1 :]
    try:
        args = parser().parse_args(words[:cut])
    except SystemExit as e:
        return 0 if e.code in (0, None) else 2
    if not mark:
        say("the mark's command is given after --: make netbox-change gives it", err=True)
        return 2
    for name in (ADDRESS, TOKEN):
        if not environ.get(name):
            say(f"{name} is not set: load local/.env first", err=True)
            return 2
    try:
        reach = box if box is not None else Box(environ[ADDRESS], environ[TOKEN])
    except BoxError as e:
        say(f"{e}", err=True)
        return 1
    try:
        tag = reach.one("extras/tags/", slug=TAG) if args.tag else None
        if args.tag and tag is None:
            raise ChangeError(f"NetBox holds no tag {TAG}, so the branch was not built: make netbox-hook makes it")
        made = branch(reach, args.branch)
        for label, _, _ in STEPS:
            say(f"wrote {label} on the branch {args.branch}: {step(reach, made['schema_id'], label)}")
            marked(mark, args.branch, label, run=run)
            say(f"marked {label}")
        if tag is not None:
            tagged(reach, made, tag)
            say(f"set the tag {TAG} on the branch {args.branch}")
    except (BoxError, ChangeError, OSError) as e:
        say(f"{e}", err=True)
        return 1
    finally:
        reach.close()
    lost = "a request lost is not sent again: take the tag off where it stands and set it again to ask again"
    if tag is not None:
        say(f"the tag asks for its rehearsal, which takes it off; {lost}")
    else:
        say(
            f"the branch {args.branch} is built and marked: set the tag {TAG} on it to ask for its rehearsal, as make "
            f"netbox-change NETBOX_TAG=1 does last; {lost}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
