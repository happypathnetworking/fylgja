"""The reader's Nautobot account, `fylgja-reader`, at its least grants, and its token's line in `local/.env`.

Run by `make nautobot-seed` after the seed, as `core/.venv/bin/python nautobot/seed/account.py --env <local/.env>`,
with `local/.env` loaded for `FYLGJA_NAUTOBOT_ADDRESS` and the superuser's `FYLGJA_NAUTOBOT_WRITE_TOKEN` (D-042).
Golden Config runs the setting's query with the rendering account's grants, and an account that cannot see a device's
interfaces got a render of 200 without them (D-118). So the reader holds `GRANTS`: `view` on the twelve types Task 1
read as least for each list a read makes and each render to be the superuser's byte for byte
(design/verified-facts.md, "Nautobot 3.2.8 with Golden Config 3.0.8", "The reader's account and its token"), and a
thirteenth, `view` on `users.token` constrained to the account's own tokens, the one place a key can be asked whose it
is and whether it writes; and a fourteenth, `view` on `extras.staticgroupassociation`, the list of a dynamic group's
stored members, which the reader holds to the group's filter (phase 11's plan 2, Task 7). Its token has writing
disabled, and a render's own write, a moved head, asks no grant.

Each run:

- the user is found by its `username`, or made active with no password; a user found inactive is set active. One
  found a superuser is refused, since no request undoes that, and so is one that a permission outside `GRANTS` names,
  which reaches more than its grants: each is named and nothing is removed. A group that holds the user cannot be
  read, since Nautobot's API shows neither a user's groups nor a group's users (`user_count` alone), so it is not
  refused;
- each grant is found by its name, or made, and brought to exactly its row, its types, its actions, its constraints,
  enabled, and that one user, by one `PATCH` only where it differs;
- the line is kept byte for byte where its key is a token of the reader's own with writing disabled, read by that
  key itself through the thirteenth grant, and the key is none of the superuser's. Else a token is made: a token is
  always the requester's, whoever the request names, so the superuser sets a password on the account, generated here
  and kept nowhere, grants it `add` on `users.token` constrained to its own, and the account posts its own token under
  HTTP Basic with writing disabled. That temporary grant is deleted at once, whatever happened, so that the account
  holds `view` alone at rest.

The line is written last, in one rename: it replaces the last line that holds its name, as a shell reads the file, or
is appended where none does; every other byte is kept and the file left at mode `0600`. A replaced token is not
revoked: only its own account could, and it holds `view` alone. Nautobot not answering, or refusing, is a failure and
the file is left as it was.

It prints one line for each thing it made, set, brought or replaced, and never a value: no token, old or new, no
password and no Basic header is printed or carried by an error. Each is handed to `Box.hide` before the request that
carries it is sent. Exit 0; 1 for a refusal or a failure said on stderr; 2 for a command line not understood, a
variable not set, or a file that is not there.

Run by `core/.venv/bin/python`; httpx and the standard library alone, never `fylgja_core`, a reader, the example or a
client library of Nautobot's.
"""

from __future__ import annotations

import argparse
import base64
import os
import re
import secrets
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from box import ADDRESS, TOKEN, Box, BoxError, where

READER = "fylgja-reader"
"""The reader's account."""

LINE = "FYLGJA_NAUTOBOT_TOKEN"
"""The line of `local/.env` that holds the reader's token."""


@dataclass(frozen=True)
class Grant:
    """One permission of Nautobot's, granted to the reader alone: `constraints` is the object filter it holds, None for
    none."""

    name: str
    object_types: tuple[str, ...]
    actions: tuple[str, ...]
    constraints: Mapping[str, str] | None = None


OWN = {"user": "$user"}
"""A constraint that limits a permission to the objects of the requesting user: a token's owner."""

VIEWS = (
    "dcim.device",
    "dcim.interface",
    "dcim.cable",
    "dcim.platform",
    "dcim.manufacturer",
    "ipam.ipaddress",
    "extras.tag",
    "extras.configcontext",
    "extras.objectchange",
    "extras.gitrepository",
    "extras.dynamicgroup",
    "nautobot_golden_config.goldenconfigsetting",
)
"""The twelve types whose `view` each list a read makes or each render needs, none removable (Task 1, Step 7)."""

GRANTS: tuple[Grant, ...] = (
    *(Grant(f"{READER}-{kind}", (kind,), ("view",)) for kind in VIEWS),
    Grant(f"{READER}-users.token", ("users.token",), ("view",), OWN),
    Grant(f"{READER}-extras.staticgroupassociation", ("extras.staticgroupassociation",), ("view",)),
)
"""The reader's grants, `view` alone, one permission each: the twelve, the account's own tokens, and a dynamic group's
stored members, which Nautobot refused the reader's token under the thirteen (design/verified-facts.md)."""

TEMPORARY = Grant(f"{READER}-token-add", ("users.token",), ("add",), OWN)
"""The grant the account holds while it makes its own token, and never after."""

NAMES = frozenset([*(grant.name for grant in GRANTS), TEMPORARY.name])
"""Every permission `account.py` keeps: a leftover temporary grant is its own, deleted by the next run, and no
stray."""

USERS = "users/users/"
PERMISSIONS = "users/permissions/"
TOKENS = "users/tokens/"

KEY = re.compile(r"[0-9a-f]{40}")
"""A token as Nautobot makes it: 40 lowercase hex characters."""

ASSIGNMENT = re.compile(r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)")
QUOTED = re.compile(r"""\s*(?:"([^"]*)"|'([^']*)')(?:\s+#.*)?""")
COMMENT = re.compile(r"\s#.*")

PURGE = "make nautobot-down PURGE=1, then make nautobot-up, then load local/.env again and run make nautobot-seed"
"""The remedy where Nautobot holds what the run removes nothing of: a superuser or a stray."""

UP = (
    "make nautobot-up starts Nautobot where it is stopped and reads that it is this Nautobot; then load local/.env"
    " again and run make nautobot-seed"
)
"""The remedy where Nautobot answered nothing."""

RELOAD = (
    "load local/.env again, whose FYLGJA_NAUTOBOT_WRITE_TOKEN line make nautobot-up writes, and run make"
    " nautobot-seed; where Nautobot refuses it still, run make nautobot-up, whose image takes the line at every"
    " start, about 112 s on kept volumes, then load local/.env again and run make nautobot-seed"
)
"""The remedy where Nautobot refused the superuser's token."""


class Stray(BoxError):
    """An account's user that reaches more than its grants, which the run removes nothing of; its sentence names
    `PURGE`."""


class Odd(BoxError):
    """An answer of Nautobot's that will not do, the reader's key's among them, which no remedy mends."""


class Declined(BoxError):
    """The account's own request, under its name and password, answered 401 or 403: Nautobot refused the account,
    which says nothing of the superuser's token, so `RELOAD` is not its remedy."""


class Basic(Box):
    """A `Box` that carries a user's name and password as HTTP Basic, which a token of one's own is made under."""

    def __init__(self, address: str, username: str, password: str, *, transport: httpx.BaseTransport | None = None):
        super().__init__(address, "unused", transport=transport)
        header = base64.b64encode(f"{username}:{password}".encode()).decode()
        self._client.headers["Authorization"] = f"Basic {header}"
        self.hide(password, header)


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


def rewritten(data: bytes, name: str, value: str) -> tuple[bytes, str]:
    """`data` with `name=value`: in place of the last line that holds the name, its ending kept, or appended where none
    does; every other byte kept. Answers the bytes and what was done."""
    kept = data.decode().splitlines(keepends=True)
    written = f"{name}={value}"
    at = [number for number, line in enumerate(kept) if (found := assigned(line)) and found[0] == name]
    if at:
        line = kept[at[-1]]
        kept[at[-1]] = written + line[len(line.rstrip("\r\n")) :]
        return "".join(kept).encode(), f"replaced {name}"
    if kept and not kept[-1].endswith(("\n", "\r")):
        kept[-1] += "\n"
    kept.append(written + "\n")
    return "".join(kept).encode(), f"appended {name}"


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


def user(box: Box, done: list[str]) -> str:
    """The id of the reader's user, active, no superuser and named by no permission but `NAMES`: found by its
    `username`, or made with no password."""
    found = box.one(USERS, username=READER)
    if found is None:
        made = box.post(USERS, {"username": READER, "is_active": True})
        if not isinstance(made, dict) or not isinstance(made.get("id"), str):
            raise BoxError(f"POST {where(USERS)} answered no user for {READER}")
        told(done, f"made the user {READER}")
        return str(made["id"])
    if found.get("is_superuser") is True:
        raise Stray(f"the user {READER} is a superuser, which no request of Nautobot's API undoes: {PURGE}")
    strays = [
        f"the permission {row.get('name')}"
        for row in box.listed(PERMISSIONS, users=found["id"])
        if row.get("name") not in NAMES
    ]
    if strays:
        held = " and ".join(strays)
        raise Stray(f"{READER} holds {held}, which reach more than its grants; nothing removed: {PURGE}")
    if found.get("is_active") is not True:
        box.patch(f"{USERS}{found['id']}/", {"is_active": True})
        told(done, f"set the user {READER} active")
    return str(found["id"])


def naming(box: Box) -> dict[str, set[str]]:
    """The user ids each permission's name is held by: Nautobot's permission row does not list its users, but a list of
    permissions is filtered by one."""
    holders: dict[str, set[str]] = {}
    for person in box.listed(USERS):
        for row in box.listed(PERMISSIONS, users=person["id"]):
            holders.setdefault(str(row.get("name")), set()).add(str(person["id"]))
    return holders


def body_of(grant: Grant, holder: str) -> dict[str, Any]:
    return {
        "object_types": list(grant.object_types),
        "actions": list(grant.actions),
        "constraints": dict(grant.constraints) if grant.constraints is not None else None,
        "enabled": True,
        "users": [holder],
    }


def granted(box: Box, grant: Grant, holder: str, holders: Mapping[str, set[str]], done: list[str]) -> None:
    """`grant`, found by its name or made, holding exactly its row's types, actions and constraints, enabled, and
    the one user `holder`: brought by one `PATCH` where one differs."""
    body = body_of(grant, holder)
    found = box.one(PERMISSIONS, name=grant.name)
    if found is None:
        box.post(PERMISSIONS, {"name": grant.name, **body})
        told(done, f"made the permission {grant.name}")
        return
    if (
        sorted(found.get("object_types") or []) != sorted(grant.object_types)
        or sorted(found.get("actions") or []) != sorted(grant.actions)
        or found.get("constraints") != body["constraints"]
        or found.get("enabled") is not True
        or holders.get(grant.name, set()) != {holder}
    ):
        box.patch(f"{PERMISSIONS}{found['id']}/", body)
        told(done, f"brought the permission {grant.name} to its row")


def keeps(box: Box, line: str | None) -> bool:
    """Whether `line`, the file's value, is a token Nautobot holds of the reader with writing disabled: its key read by
    that key through the thirteenth grant, which lists the requester's own tokens alone, and none of the superuser's
    own, since a superuser's token reads the same list. Nautobot's answer names no owner, so the reader's token is made
    with its own name as its `description`, which its owner reads back: a token of another account that is described
    so is not told apart. A key Nautobot refuses as invalid is no key; any other refusal is `Odd`."""
    if line is None or KEY.fullmatch(line) is None:
        return False
    if any(row.get("key") == line for row in box.listed(TOKENS)):
        return False
    reader = box.another(line)
    try:
        rows = reader.listed(TOKENS)
    except BoxError as e:
        if e.status == 401 or (e.status == 403 and "Invalid token" in str(e)):
            return False
        raise Odd(f"the reader's token line was refused: {e}", e.status) from None
    finally:
        reader.close()
    return any(
        row.get("key") == line and row.get("write_enabled") is False and row.get("description") == READER
        for row in rows
    )


def mint(box: Box, holder: str, done: list[str]) -> str:
    """A new token of the reader, write-disabled, made by the account itself: the superuser sets a password, generated
    here and handed to `box.hide`, and grants it `add` on its own tokens; the account posts the token under Basic; the
    grant is deleted, whatever came of it."""
    password = secrets.token_urlsafe(48)
    box.hide(password)
    box.patch(f"{USERS}{holder}/", {"password": password})
    told(done, f"set a password on {READER}, kept nowhere")
    row = box.post(PERMISSIONS, {"name": TEMPORARY.name, **body_of(TEMPORARY, holder)})
    told(done, f"made the permission {TEMPORARY.name}")
    raised: BoxError | None = None
    made: Any = None
    gone: BoxError | None = None
    try:
        basic = Basic(box.address, READER, password, transport=box.transport)
        try:
            made = basic.post(TOKENS, {"write_enabled": False, "description": READER})
        except BoxError as e:
            raised = e
            if e.status in (401, 403):
                raised = Declined(f"the account's own request was refused: {e}", e.status)
        finally:
            basic.close()
    finally:
        try:
            box.delete(f"{PERMISSIONS}{row['id']}/")
        except BoxError as e:
            gone = e
    if gone is not None:
        leftover = (
            f"; the permission {TEMPORARY.name} could not be deleted ({gone}) and stays until the next"
            " make nautobot-seed removes it"
        )
        if raised is not None:
            raise type(raised)(f"{raised}{leftover}", raised.status) from None
        raise Odd(f"the token was made, but {leftover[2:]}", gone.status) from None
    told(done, f"deleted the permission {TEMPORARY.name}")
    if raised is not None:
        raise raised
    key = made.get("key") if isinstance(made, dict) else None
    if isinstance(key, str):
        box.hide(key)
    if not (isinstance(key, str) and KEY.fullmatch(key)) or made.get("write_enabled") is not False:
        raise Odd(f"POST {where(TOKENS)} answered no write-disabled token for {READER}")
    told(done, f"made a token of {READER}")
    return key


def cleared(box: Box, done: list[str]) -> None:
    """The temporary grant, deleted where a run that stopped before its own deletion left it."""
    left = box.one(PERMISSIONS, name=TEMPORARY.name)
    if left is not None:
        box.delete(f"{PERMISSIONS}{left['id']}/")
        told(done, f"deleted the permission {TEMPORARY.name}, left by a run that stopped")


def ensure(env: Path, box: Box) -> list[str]:
    """The account, its grants and its token's line in `env`, as the module says; what was made, set, brought or
    replaced, in order, `[]` where nothing was. A `BoxError` holds no token and no password: the line's value and each
    one made are handed to `box.hide` before any request carries it."""
    data = env.read_bytes()
    done: list[str] = []
    old = held(data, LINE)
    if old:
        box.hide(old)
    holder = user(box, done)
    holders = naming(box)
    for grant in GRANTS:
        granted(box, grant, holder, holders, done)
    cleared(box, done)
    if keeps(box, old):
        return done
    key = mint(box, holder, done)
    new, written = rewritten(data, LINE, key)
    replace_file(env, new)
    told(done, written)
    return done


def remedy(error: BoxError) -> str | None:
    """What to do after `error`: `local/.env` loaded again where Nautobot refused the superuser's token, `make
    nautobot-up` where it answered nothing, and None for a `Stray`, whose sentence names the purge, for an `Odd`, an
    answer that will not do, for a `Declined`, the account's own refusal, and for any other status."""
    if isinstance(error, (Stray, Odd, Declined)):
        return None
    if error.status in (401, 403):
        return RELOAD
    if error.status is None:
        return UP
    return None


def parser() -> argparse.ArgumentParser:
    made = argparse.ArgumentParser(prog="account.py", description=(__doc__ or "").splitlines()[0])
    made.add_argument("--env", type=Path, required=True, help="the local/.env the token's line is written to")
    return made


def main(argv: Sequence[str], *, transport: httpx.BaseTransport | None = None) -> int:
    """The account and its line, as `make nautobot-seed` runs it, over `transport` where a test gives one."""
    try:
        args = parser().parse_args(argv)
    except SystemExit as e:
        return 0 if e.code in (0, None) else 2
    for name in (ADDRESS, TOKEN):
        if not os.environ.get(name):
            say(f"{name} is not set: load local/.env first", err=True)
            return 2
    if not args.env.is_file():
        say(f"{args.env} is not there: run make nautobot-up first", err=True)
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
        say("the account, its grants and its token line are as they should be; nothing written")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
