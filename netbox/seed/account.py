"""The reader's and the example's NetBox accounts, `fylgja-reader` and `fylgja-orchestrator`, at their least
permissions, and their tokens' lines in `local/.env`.

Run by `make netbox-seed` after the seed, as `core/.venv/bin/python netbox/seed/account.py --env <local/.env>`, with
`local/.env` loaded for `FYLGJA_NETBOX_ADDRESS` and the superuser's `FYLGJA_NETBOX_WRITE_TOKEN` (D-042). The reader
writes nothing to NetBox, and the example's writes are a journal entry on a branch and the branch's tags (D-095,
D-097), so each runs under an account of its own, no superuser, granted what was read as least for those on the
running instance (design/verified-facts.md, "NetBox 4.7.5 with netbox-branching 1.2.3"), `GRANTS`: the reader's
`view` of each type a read lists, under a branch's header too, which asks no grant of its own, and `view` with
`render_config` on `dcim.device` for a render; the example's the same, with `view` and `add` on
`extras.journalentry`, any object's journal and not a branch's alone, and `view` and `change` on
`netbox_branching.branch`, which writes any member of a branch, its tags among them, and is all the plugin's source
asks of a stuck branch's `recover`, read in the source and not run.

Each run, for each account in turn:

- its user is found by its `username`, or made active with a password, which NetBox requires: generated, sent and
  kept nowhere. A user found inactive is set active. One found a superuser is refused, since no request of the API
  undoes that, and so is one whose row holds a group, or a permission that is none of `GRANTS`, either of which
  reaches more than its grants: each is named, and nothing is removed;
- each of its grants is found by its name, or made, naming that one user; one found is brought to exactly its row's
  `object_types` and `actions` and that one user, by one `PATCH` only where it differs;
- its line is kept where the superuser reads exactly one token of the line's key and that token is the account's: a
  purge keeps `local/.env`, and a new instance holds no token of an old key. Else a token is made for the account by
  the superuser, which NetBox answers once, and is presented as `nbt_<key>.<token>`.

The lines are written last, in one rename: each replaces the last line that holds its name, as a shell reads the
file, or is appended where none does; every other byte is kept and the file left at mode `0600`. A replaced token is
not revoked: a dead one is gone already, and a live one of the other account's is that account's. NetBox not
answering, or refusing, is a failure, said with the remedy for what failed where one is known (`remedy`), and the
file is left as it was.

It prints one line for each thing it made, set or replaced, and never a value: no token, old or new, and no
password is printed or carried by an error. Each is handed to `Box.hide` before the request that carries it is sent,
so that a refusal echoing it has it replaced before NetBox's words are cut. Exit 0; 1 for a refusal or a failure
said on stderr; 2 for a command line not understood, a variable not set, or a file that is not there.

Run by `core/.venv/bin/python`; httpx and the standard library alone, never `fylgja_core`, a reader, the example or a
client library of NetBox's.
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import httpx
from box import ADDRESS, TOKEN, Box, BoxError, Unfit, where

READER = "fylgja-reader"
"""The reader's account."""

ORCHESTRATOR = "fylgja-orchestrator"
"""The example orchestrator's account."""

LINES = MappingProxyType({READER: "FYLGJA_NETBOX_TOKEN", ORCHESTRATOR: "FYLGJA_ORCHESTRATOR_NETBOX_TOKEN"})
"""The line of `local/.env` that holds each account's token."""


@dataclass(frozen=True)
class Grant:
    """One permission of NetBox's, granted to one account alone."""

    name: str
    object_types: tuple[str, ...]
    actions: tuple[str, ...]


READS = (
    "dcim.device",
    "dcim.interface",
    "dcim.cable",
    "dcim.platform",
    "dcim.manufacturer",
    "extras.tag",
    "extras.configcontext",
    "core.objectchange",
    "netbox_branching.branch",
)
"""The types a read lists, each of which NetBox refuses 403 without `view` on it."""

RENDER = ("dcim.device",)
"""A render is 404 without both `view` and `render_config` on the device."""

GRANTS: Mapping[str, tuple[Grant, ...]] = MappingProxyType(
    {
        READER: (
            Grant("fylgja-reader", READS, ("view",)),
            Grant("fylgja-reader-render", RENDER, ("view", "render_config")),
        ),
        ORCHESTRATOR: (
            Grant("fylgja-orchestrator", READS, ("view",)),
            Grant("fylgja-orchestrator-render", RENDER, ("view", "render_config")),
            Grant("fylgja-orchestrator-journal", ("extras.journalentry",), ("view", "add")),
            Grant("fylgja-orchestrator-branch", ("netbox_branching.branch",), ("view", "change")),
        ),
    }
)
"""Each account's grants, the reader's first: the example reads through the reader with its own token, so it holds
the reader's rows under names of its own, and beside them a journal entry's and a branch's."""

USERS = "users/users/"
PERMISSIONS = "users/permissions/"
TOKENS = "users/tokens/"

PURGE = "make netbox-down PURGE=1, then make netbox-up, then load local/.env again and run make netbox-seed"
"""The remedy where NetBox holds what the run removes nothing of, a superuser or a stray, as `seed.py` says it.
`make netbox-up` replaces the write token's line after a purge, so a shell loaded before it holds a token the new
instance refuses."""

UP = (
    "make netbox-up starts NetBox where it is stopped and reads that it is this NetBox; then load local/.env again"
    " and run make netbox-seed"
)
"""The remedy where NetBox answered nothing, or nothing a NetBox would, as `seed.py` says it."""

RELOAD = (
    "load local/.env again, whose FYLGJA_NETBOX_WRITE_TOKEN line make netbox-up writes, and run make netbox-seed;"
    " where NetBox refuses it still, run make netbox-up, which provisions a refused token again without a purge, about"
    " 74 s on kept volumes, then load local/.env again and run make netbox-seed; only where NetBox refuses it after"
    f" that, {PURGE}"
)
"""The remedy where NetBox refused the write token, 401 or 403, as `seed.py` says it."""

NAMES = frozenset(grant.name for grants in GRANTS.values() for grant in grants)
"""Every grant `account.py` keeps. One of another account's that names this user is brought to its own account
alone by the same run, so it is no stray."""

FORM = re.compile(r"nbt_([A-Za-z0-9]+)\.([A-Za-z0-9]+)")
"""A token as NetBox presents it, `nbt_<key>.<token>`."""

ASSIGNMENT = re.compile(r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)")
QUOTED = re.compile(r"""\s*(?:"([^"]*)"|'([^']*)')(?:\s+#.*)?""")
COMMENT = re.compile(r"\s#.*")


class Stray(BoxError):
    """An account's user that reaches more than its grants, which the run removes nothing of; its sentence names
    `PURGE`."""


def say(line: str, *, err: bool = False) -> None:
    print(f"account: {line}", file=sys.stderr if err else sys.stdout, flush=True)


def assigned(line: str) -> tuple[str, str] | None:
    """The name `line` assigns and its value as a shell reads it: a quoted value what its quotes hold, an unquoted
    one up to a `#` beginning a word, its spaces trimmed. None for a line that assigns nothing."""
    found = ASSIGNMENT.fullmatch(line.strip())
    if not found:
        return None
    quoted = QUOTED.fullmatch(found[2])
    if quoted:
        return found[1], quoted[1] if quoted[1] is not None else quoted[2]
    return found[1], COMMENT.sub("", found[2]).strip()


def held(data: bytes, name: str) -> str | None:
    """The value the file's bytes `data` hold for `name`, its last line where several do, as a shell takes it."""
    value = None
    for line in data.decode().splitlines():
        found = assigned(line)
        if found is not None and found[0] == name:
            value = found[1]
    return value


def rewritten(data: bytes, lines: Mapping[str, str]) -> tuple[bytes, list[str]]:
    """`data` with `NAME=value` for each of `lines`: in place of the last line that holds the name, its ending kept,
    or appended where none does; every other byte kept. Answers the bytes and what was done to each name."""
    kept = data.decode().splitlines(keepends=True)
    done: list[str] = []
    for name, value in lines.items():
        written = f"{name}={value}"
        at = [number for number, line in enumerate(kept) if (found := assigned(line)) and found[0] == name]
        if at:
            line = kept[at[-1]]
            kept[at[-1]] = written + line[len(line.rstrip("\r\n")) :]
            done.append(f"replaced {name}")
        else:
            if kept and not kept[-1].endswith(("\n", "\r")):
                kept[-1] += "\n"
            kept.append(written + "\n")
            done.append(f"appended {name}")
    return "".join(kept).encode(), done


def replace_file(path: Path, data: bytes) -> None:
    """`path` written whole through a new file of mode 0600 beside it and a rename."""
    part = path.with_name(f".{path.name}.part")
    part.unlink(missing_ok=True)
    descriptor = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as out:
            out.write(data)
        part.replace(path)
    finally:
        part.unlink(missing_ok=True)


def told(done: list[str], line: str) -> None:
    done.append(line)
    say(line)


def user(box: Box, name: str, done: list[str]) -> int:
    """The id of the user `name`, active, no superuser and holding no more than its grants: found by its `username`,
    or made with a password generated here, handed to `box.hide` and kept nowhere else."""
    found = box.one(USERS, username=name)
    if found is None:
        password = secrets.token_urlsafe(32)
        box.hide(password)
        made = box.post(USERS, {"username": name, "password": password, "is_active": True})
        if not isinstance(made, dict) or not isinstance(made.get("id"), int):
            raise BoxError(f"POST {where(USERS)} answered no user for {name}")
        told(done, f"made the user {name}")
        return int(made["id"])
    if box.listed(USERS, username=name, is_superuser=True):
        raise Stray(f"the user {name} is a superuser, which no request of NetBox's API undoes: {PURGE}")
    strays = [f"the group {row.get('name')}" for row in found.get("groups") or []]
    strays += [
        f"the permission {row.get('name')}" for row in found.get("permissions") or [] if row.get("name") not in NAMES
    ]
    if strays:
        held = " and ".join(strays)
        raise Stray(f"{name} holds {held}, which reach more than its grants; nothing is removed: {PURGE}")
    if found.get("is_active") is not True:
        box.patch(f"{USERS}{found['id']}/", {"is_active": True})
        told(done, f"set the user {name} active")
    return int(found["id"])


def granted(box: Box, grant: Grant, holder: int, done: list[str]) -> None:
    """`grant`, found by its name or made, holding exactly its row's types and actions and the one user `holder`.
    Of one found, its types, its actions and its users are compared and nothing else: its `enabled`, its
    `constraints` and its `groups` are not, so one disabled, constrained or naming a group by hand is left as it
    is."""
    body = {"object_types": list(grant.object_types), "actions": list(grant.actions), "users": [holder]}
    found = box.one(PERMISSIONS, name=grant.name)
    if found is None:
        box.post(PERMISSIONS, {"name": grant.name, **body})
        told(done, f"made the permission {grant.name}")
        return
    users = [row.get("id") if isinstance(row, dict) else row for row in found.get("users") or []]
    if (
        sorted(found.get("object_types") or []) != sorted(grant.object_types)
        or sorted(found.get("actions") or []) != sorted(grant.actions)
        or users != [holder]
    ):
        box.patch(f"{PERMISSIONS}{found['id']}/", body)
        told(done, f"brought the permission {grant.name} to its row")


def holds(box: Box, token: str | None, holder: int) -> bool:
    """Whether `token` is one NetBox holds of the user `holder`: exactly one token of its key, and that one the
    user's."""
    found = FORM.fullmatch(token) if token is not None else None
    if found is None:
        return False
    rows = box.listed(TOKENS, key=found[1])
    return len(rows) == 1 and (rows[0].get("user") or {}).get("id") == holder


def token(box: Box, name: str, holder: int, done: list[str]) -> str:
    """A new token of the user `holder`, made by the superuser and presented as `nbt_<key>.<token>`, handed to
    `box.hide` as soon as it is answered."""
    made: Any = box.post(TOKENS, {"user": holder})
    key = made.get("key") if isinstance(made, dict) else None
    value = made.get("token") if isinstance(made, dict) else None
    presented = f"nbt_{key}.{value}"
    box.hide(presented)
    if not (isinstance(key, str) and isinstance(value, str) and FORM.fullmatch(presented)):
        raise BoxError(f"POST {where(TOKENS)} answered no token for {name}")
    if not isinstance(made.get("user"), dict) or made["user"].get("id") != holder:
        raise Unfit(f"POST {where(TOKENS)} answered a token of another user than {name}")
    told(done, f"made a token of {name}")
    return presented


def ensure(env: Path, box: Box) -> list[str]:
    """Each account, its grants and its token's line in `env`, as the module says; what was made, set, brought to its
    row or replaced, in order, `[]` where nothing was. A `BoxError` holds no token and no password: each line's
    value is handed to `box.hide` before any request."""
    data = env.read_bytes()
    done: list[str] = []
    lines: dict[str, str] = {}
    olds = {line: held(data, line) for line in LINES.values()}
    box.hide(*(old for old in olds.values() if old is not None))
    for name, grants in GRANTS.items():
        holder = user(box, name, done)
        for grant in grants:
            granted(box, grant, holder, done)
        if not holds(box, olds[LINES[name]], holder):
            lines[LINES[name]] = token(box, name, holder, done)
    if lines:
        new, written = rewritten(data, lines)
        replace_file(env, new)
        for line in written:
            told(done, line)
    return done


def remedy(error: BoxError) -> str | None:
    """What to do after `error`, said for what failed, as `seed.py`'s `remedy` says it: `local/.env` loaded again
    where NetBox refused the write token, `make netbox-up` where NetBox answered no status, and None for a `Stray`,
    whose sentence names the purge, for an `Unfit`, an answer of NetBox's own that will not do, a token of another
    user among them, and for any other status, where no remedy is known."""
    if isinstance(error, (Stray, Unfit)):
        return None
    if error.status in (401, 403):
        return RELOAD
    if error.status is None:
        return UP
    return None


def parser() -> argparse.ArgumentParser:
    made = argparse.ArgumentParser(prog="account.py", description=(__doc__ or "").splitlines()[0])
    made.add_argument("--env", type=Path, required=True, help="the local/.env the tokens' lines are written to")
    return made


def main(argv: Sequence[str], *, transport: httpx.BaseTransport | None = None) -> int:
    """The accounts and their lines, as `make netbox-seed` runs it, over `transport` where a test gives one."""
    try:
        args = parser().parse_args(argv)
    except SystemExit as e:
        return 0 if e.code in (0, None) else 2
    for name in (ADDRESS, TOKEN):
        if not os.environ.get(name):
            say(f"{name} is not set: load local/.env first", err=True)
            return 2
    if not args.env.is_file():
        say(f"{args.env} is not there: run make netbox-up first", err=True)
        return 2
    try:
        box = Box(os.environ[ADDRESS], os.environ[TOKEN], transport=transport)
    except BoxError as e:
        say(f"{e}", err=True)
        return 1
    try:
        done = ensure(args.env, box)
    except BoxError as e:
        say(f"{e}", err=True)
        if (said := remedy(e)) is not None:
            say(said, err=True)
        return 1
    except (OSError, ValueError) as e:
        say(f"{e}", err=True)
        return 1
    finally:
        box.close()
    if not done:
        say("every account, grant and token line is as it should be; nothing written")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
