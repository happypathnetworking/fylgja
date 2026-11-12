"""The example's Infrahub account, `fylgja-orchestrator`, and its token's line in `local/.env`.

Run by `make orchestrator-env` as `core/.venv/bin/python infrahub/seed/account.py --env <local/.env> --ctl
<infrahubctl>`, with `local/.env` loaded; no part of the seed. The example posts its report under an account of its
own (D-085), whose one role, in one group, holds four permissions: `object:Core:ChangeThread:create:allow_default`
and `object:Core:ThreadComment:create:allow_default`, which a thread and its comments take;
`global:edit_default_branch:allow_default`, since both are written on `main`; and the instance's own
`object:*:*:view:allow_all`, since the three alone read nothing, every kind refused 403, and a view of every kind on
`main` alone does not read the proposed change's branch (design/verified-facts.md, "Infrahub 1.11.11"; P5-27).

Every run reads the role and brings it to exactly the four permissions, made where absent, the ones it lacks added and
any other taken off, and reads the group and makes it again where it lacks the role or the account, each with a mutation
only where it differs: a valid token on a role of three, or in a group without the role, reads nothing (P5-36, P5-38,
P5-40). A token line is checked before it is trusted: `make infrahub-down PURGE=1` keeps `local/.env`, so a token made
on the purged instance is dead on the next (plan 0, reconciled 21). Where the file holds a `TOKEN_LINE` whose token
`AccountProfile` answers as the account's, nothing more is made and the file is left byte for byte. Where it holds none,
or one Infrahub refuses (HTTP 401) or answers as another account's, the group and the account are made where absent, the
account given a new generated password where it is held, and the account logs in and makes a token, which is checked the
same way; the line is then appended, or replaces the one there, and every other line of the file is kept. A replaced
token is not revoked: a refused one is dead already, and a live one of another account is its owner's to revoke.
Infrahub not answering the check is a failure, never a refusal, and the file is left as it was. A file wider than mode
`0600` is set to it, as `make infrahub-up` sets `local/.env`.

The admin's writes go through `hub.connect`'s writer, `FYLGJA_INFRAHUB_WRITE_TOKEN`; the login, the token's create and
each check through an `httpx.Client` of this script's own (P5-16). It prints the names of what it made and never a
value: the password is generated, sent to Infrahub and kept nowhere, and neither the old token nor the new one is
printed, logged or carried by an error. Exit 0; 1 for a refusal or a failure said on stderr; 2 for a command line not
understood, a variable not set, or a file that is not there.
"""

from __future__ import annotations

import argparse
import os
import re
import secrets
import ssl
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from hub import ADDRESS, CA, Hub, HubError, Run, connect

ACCOUNT = "fylgja-orchestrator"
"""The example's account, and the name of its role and its group."""

TOKEN_LINE = "FYLGJA_ORCHESTRATOR_INFRAHUB_TOKEN"
"""The line of `local/.env` that holds the account's token, which the example's runner is given."""

TIMEOUT = httpx.Timeout(30.0, connect=5.0)
"""This script's own requests: the login, the token's create and each check."""

ASSIGNMENT = re.compile(r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)")
QUOTED = re.compile(r"""\s*(?:"([^"]*)"|'([^']*)')(?:\s+#.*)?""")
COMMENT = re.compile(r"\s#.*")


@dataclass(frozen=True)
class Permission:
    """One permission of the role: an object permission where `namespace` is given, else a global one; `decision` 2
    is `allow_default` and 6 `allow_all`."""

    identifier: str
    action: str
    decision: int
    namespace: str = ""
    name: str = ""

    @property
    def root(self) -> str:
        return "CoreObjectPermission" if self.namespace else "CoreGlobalPermission"

    def fields(self, form: str) -> str:
        """The permission's fields as literals, `form` naming each field: `{}__value` a filter's, `{}` a create's."""
        values: list[tuple[str, str]] = []
        if self.namespace:
            values += [("namespace", f'"{self.namespace}"'), ("name", f'"{self.name}"')]
        values += [("action", f'"{self.action}"'), ("decision", str(self.decision))]
        if form == "filter":
            return ", ".join(f"{field}__value: {value}" for field, value in values)
        return ", ".join(f"{field}: {{value: {value}}}" for field, value in values)


PERMISSIONS = (
    Permission("object:Core:ChangeThread:create:allow_default", "create", 2, "Core", "ChangeThread"),
    Permission("object:Core:ThreadComment:create:allow_default", "create", 2, "Core", "ThreadComment"),
    Permission("global:edit_default_branch:allow_default", "edit_default_branch", 2),
    Permission("object:*:*:view:allow_all", "view", 6, "*", "*"),
)
"""The role's four permissions, in order (D-085; P5-27). The last is the instance's own, made at its first start."""

ROLE_READ = (
    "query ($name: String!) { CoreAccountRole(name__value: $name) { count edges { node { id "
    "permissions { count edges { node { id } } } } } } }"
)
ROLE_UPDATE = (
    "mutation ($id: String!, $permissions: [RelatedNodeInput]) { CoreAccountRoleUpdate(data: {id: $id, "
    "permissions: $permissions}) { ok } }"
)
ROLE_CREATE = (
    "mutation ($name: String!, $permissions: [RelatedNodeInput]) { CoreAccountRoleCreate(data: {name: {value: $name}, "
    "permissions: $permissions}) { ok object { id } } }"
)
ACCOUNT_READ = "query ($name: String!) { CoreAccount(name__value: $name) { count edges { node { id } } } }"
ACCOUNT_CREATE = (
    "mutation ($name: String!, $password: String!) { CoreAccountCreate(data: {name: {value: $name}, password: {value: "
    "$password}}) { ok object { id } } }"
)
ACCOUNT_UPDATE = (
    "mutation ($id: String!, $password: String!) { CoreAccountUpdate(data: {id: $id, password: {value: $password}}) "
    "{ ok } }"
)
GROUP_READ = (
    "query ($name: String!) { CoreAccountGroup(name__value: $name) { count edges { node { id "
    "roles { count edges { node { id } } } members { count edges { node { id } } } } } } }"
)
GROUP_CREATE = (
    "mutation ($name: String!, $role: String!, $account: String!) { CoreAccountGroupCreate(data: {name: {value: "
    "$name}, roles: [{id: $role}], members: [{id: $account}]}) { ok object { id } } }"
)
GROUP_DELETE = "mutation ($id: String!) { CoreAccountGroupDelete(data: {id: $id}) { ok } }"
PROFILE = "query { AccountProfile { name { value } } }"
TOKEN_CREATE = (
    "mutation ($name: String!) { InfrahubAccountTokenCreate(data: {name: $name}) { ok object { token { value } } } }"
)


class AccountError(Exception):
    """A request, an answer or a file that failed, said in one sentence that holds no value."""


def say(line: str) -> None:
    print(f"account: {line}", flush=True)


def scrubbed(text: str, *values: str) -> str:
    """`text` with each of `values` replaced, so that no error carries one."""
    for value in values:
        if value:
            text = text.replace(value, "<value>")
    return text


def nodes(hub: Hub, query: str, root: str, variables: Mapping[str, object] | None = None) -> list[dict[str, Any]]:
    """The nodes `root` answers to `query` on `main`; an answer of another shape is an `AccountError` naming `root`."""
    answer = hub.gql("main", query, variables)
    try:
        held = [edge["node"] for edge in answer[root]["edges"]]
        if not all(isinstance(node, dict) and "id" in node for node in held):
            raise TypeError(root)
    except (KeyError, TypeError):
        raise AccountError(f"{root} answered in a shape not of its query") from None
    return held


def ids_of(node: Mapping[str, Any], field: str, root: str) -> list[str]:
    """The ids of `node`'s relationship `field`; an answer of another shape is an `AccountError` naming `root`."""
    try:
        return [str(edge["node"]["id"]) for edge in node[field]["edges"]]
    except (KeyError, TypeError):
        raise AccountError(f"{root} answered in a shape not of its query") from None


def found(hub: Hub, query: str, root: str, variables: Mapping[str, object] | None = None) -> str | None:
    """The id of the one node `root` answers to `query` on `main`, or None where it answers none."""
    held = nodes(hub, query, root, variables)
    return str(held[0]["id"]) if held else None


def created(hub: Hub, query: str, root: str, variables: Mapping[str, object] | None = None) -> str:
    """The id of the node `query` makes on `main`; an answer with no `ok` is an `AccountError` naming `root`."""
    answer = hub.gql("main", query, variables).get(root)
    if not (isinstance(answer, dict) and answer.get("ok") is True and isinstance(answer.get("object"), dict)):
        raise AccountError(f"{root} answered no ok")
    return str(answer["object"]["id"])


def done(hub: Hub, query: str, root: str, variables: Mapping[str, object]) -> None:
    """`query` sent on `main`; an answer with no `ok` is an `AccountError` naming `root`."""
    answer = hub.gql("main", query, variables).get(root)
    if not (isinstance(answer, dict) and answer.get("ok") is True):
        raise AccountError(f"{root} answered no ok")


def permission(hub: Hub, wanted: Permission, made: list[str]) -> str:
    """The id of `wanted`, made where Infrahub holds none."""
    read = f"query {{ {wanted.root}({wanted.fields('filter')}) {{ count edges {{ node {{ id }} }} }} }}"
    held = found(hub, read, wanted.root)
    if held is not None:
        return held
    create = f"mutation {{ {wanted.root}Create(data: {{{wanted.fields('create')}}}) {{ ok object {{ id }} }} }}"
    made.append(f"the permission {wanted.identifier}")
    return created(hub, create, f"{wanted.root}Create")


def role(hub: Hub, made: list[str]) -> str:
    """The role's id, the role holding exactly the four permissions: made where absent, and set to them where it holds
    others, by a mutation only where it differs."""
    wanted = [permission(hub, each, made) for each in PERMISSIONS]
    held = nodes(hub, ROLE_READ, "CoreAccountRole", {"name": ACCOUNT})
    variables: dict[str, object] = {"permissions": [{"id": each} for each in wanted]}
    if not held:
        made.append(f"the role {ACCOUNT}")
        return created(hub, ROLE_CREATE, "CoreAccountRoleCreate", variables | {"name": ACCOUNT})
    node = held[0]
    if sorted(ids_of(node, "permissions", "CoreAccountRole")) != sorted(wanted):
        done(hub, ROLE_UPDATE, "CoreAccountRoleUpdate", variables | {"id": str(node["id"])})
        say(f"set the role {ACCOUNT} to its four permissions")
    return str(node["id"])


def account(hub: Hub, password: str, made: list[str]) -> str:
    """The account's id, its password set to `password`: the account made where absent, else updated."""
    held = found(hub, ACCOUNT_READ, "CoreAccount", {"name": ACCOUNT})
    if held is None:
        made.append(f"the account {ACCOUNT}")
        return created(hub, ACCOUNT_CREATE, "CoreAccountCreate", {"name": ACCOUNT, "password": password})
    done(hub, ACCOUNT_UPDATE, "CoreAccountUpdate", {"id": held, "password": password})
    made.append(f"a new password of the account {ACCOUNT}")
    return held


def group(hub: Hub, role: str, member: str, made: list[str]) -> None:
    """The group holding the role `role` and the account `member`: made where absent, and made again where it holds
    another role or lacks the account, as after the account was deleted and made again."""
    held = nodes(hub, GROUP_READ, "CoreAccountGroup", {"name": ACCOUNT})
    if held:
        node = held[0]
        roles = ids_of(node, "roles", "CoreAccountGroup")
        members = ids_of(node, "members", "CoreAccountGroup")
        if roles == [role] and member in members:
            return
        done(hub, GROUP_DELETE, "CoreAccountGroupDelete", {"id": str(node["id"])})
    made.append(f"the group {ACCOUNT}")
    created(hub, GROUP_CREATE, "CoreAccountGroupCreate", {"name": ACCOUNT, "role": role, "account": member})


def client(environ: Mapping[str, str], transport: httpx.BaseTransport | None) -> httpx.Client:
    """This script's own client of Infrahub, at `FYLGJA_INFRAHUB_ADDRESS`, verified as `hub.connect` verifies, with
    no credential of its own: each request carries the one it is sent with."""
    verify: ssl.SSLContext | bool = True
    ca = environ.get(CA, "")
    if ca:
        try:
            verify = ssl.create_default_context(cafile=ca)
        except (OSError, ssl.SSLError) as e:
            raise AccountError(f"{CA} does not load: {e}") from None
    return httpx.Client(
        base_url=environ[ADDRESS], transport=transport, verify=verify, timeout=TIMEOUT, trust_env=False
    )


def ask(own: httpx.Client, path: str, body: object, headers: Mapping[str, str], *values: str) -> httpx.Response:
    """One POST of this script's own; a failure to be answered is an `AccountError` with `values` scrubbed."""
    failure = ""
    try:
        return own.post(path, json=body, headers=dict(headers))
    except httpx.HTTPError as e:
        failure = scrubbed(f"POST {path} was not answered by {own.base_url}: {type(e).__name__}: {e}", *values)
    raise AccountError(failure)


def holder(own: httpx.Client, token: str) -> str | None:
    """The account Infrahub answers `token` as, by `AccountProfile`, or None where it refuses the token (HTTP 401) or
    the token is none a header can carry. Any other answer is an `AccountError`."""
    if not token or not all("!" <= character <= "~" for character in token):
        return None
    response = ask(own, "/graphql/main", {"query": PROFILE}, {"X-INFRAHUB-KEY": token}, token)
    if response.status_code == 401:
        return None
    try:
        name = response.json()["data"]["AccountProfile"]["name"]["value"]
    except (ValueError, KeyError, TypeError):
        name = None
    if response.status_code != 200 or not isinstance(name, str):
        raise AccountError(f"AccountProfile answered HTTP {response.status_code} with no account's name")
    return name


def login(own: httpx.Client, password: str) -> str:
    """A new token of the account: its login with `password`, then `InfrahubAccountTokenCreate` with the login's
    bearer, named `fylgja-orchestrator-<8 hex>`."""
    response = ask(own, "/api/auth/login", {"username": ACCOUNT, "password": password}, {}, password)
    bearer = ""
    if response.status_code == 200:
        try:
            bearer = str(response.json()["access_token"])
        except (ValueError, KeyError, TypeError):
            bearer = ""
    if not bearer:
        raise AccountError(f"the login of {ACCOUNT} answered HTTP {response.status_code} with no access token")
    name = f"{ACCOUNT}-{secrets.token_hex(4)}"
    body = {"query": TOKEN_CREATE, "variables": {"name": name}}
    response = ask(own, "/graphql/main", body, {"Authorization": f"Bearer {bearer}"}, bearer, password)
    token: Any = None
    try:
        token = response.json()["data"]["InfrahubAccountTokenCreate"]["object"]["token"]["value"]
    except (ValueError, KeyError, TypeError):
        token = None
    if response.status_code != 200 or not isinstance(token, str) or not token:
        raise AccountError(f"InfrahubAccountTokenCreate answered HTTP {response.status_code} with no token")
    return token


def value(line: str) -> str | None:
    """The value of `line` where it assigns `TOKEN_LINE`, as a shell reads it: a quoted value what its quotes hold,
    an unquoted one up to a `#` beginning a word, its spaces trimmed. None for any other line."""
    assigned = ASSIGNMENT.fullmatch(line.strip())
    if not assigned or assigned[1] != TOKEN_LINE:
        return None
    quoted = QUOTED.fullmatch(assigned[2])
    if quoted:
        return quoted[1] if quoted[1] is not None else quoted[2]
    return COMMENT.sub("", assigned[2]).strip()


def rewrite(path: Path, held: bytes, token: str) -> str:
    """`path` with the one line `TOKEN_LINE=<token>`: in place of the first such line, every other dropped, or
    appended where there is none; every other byte kept, written beside it at mode 0600 and renamed over it. Answers
    what was done: `replaced` or `appended`."""
    lines = held.decode().splitlines(keepends=True)
    new = f"{TOKEN_LINE}={token}\n"
    at = [index for index, line in enumerate(lines) if value(line) is not None]
    if at:
        ending = lines[at[0]][len(lines[at[0]].rstrip("\r\n")) :] or "\n"
        lines[at[0]] = new.rstrip("\n") + ending
        lines = [line for index, line in enumerate(lines) if index not in at[1:]]
        what = "replaced"
    else:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(new)
        what = "appended"
    part = path.with_name(f".{path.name}.part")
    part.unlink(missing_ok=True)
    descriptor = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as out:
            out.write("".join(lines).encode())
        part.replace(path)
    finally:
        part.unlink(missing_ok=True)
    return what


def ensure(env: Path, hub: Hub, own: httpx.Client) -> None:
    """The account and its token's line in `env`, as the module says."""
    mode = env.stat().st_mode & 0o7777
    if mode & 0o177:
        env.chmod(0o600)
        say(f"{env} was mode {mode:04o}: set to 0600")
    held = env.read_bytes()
    tokens = [token for token in (value(line) for line in held.decode().splitlines()) if token is not None]
    made: list[str] = []
    owner = holder(own, tokens[-1]) if tokens else None
    if owner == ACCOUNT:
        member = found(hub, ACCOUNT_READ, "CoreAccount", {"name": ACCOUNT})
        if member is None:
            raise AccountError(f"{ACCOUNT} answers its token and is not listed")
        group(hub, role(hub, made), member, made)
        if made:
            say(f"made {', '.join(made)}")
        say(f"{TOKEN_LINE} in {env} is accepted by Infrahub: nothing more to do")
        return
    if tokens:
        why = "refused by Infrahub" if owner is None else "another account's"
        say(f"{TOKEN_LINE} in {env} is {why}: making the account's token again")
    password = secrets.token_urlsafe(24)
    try:
        member_role = role(hub, made)
        member = account(hub, password, made)
        group(hub, member_role, member, made)
    except HubError as e:
        raise AccountError(scrubbed(str(e), password)) from None
    token = login(own, password)
    if holder(own, token) != ACCOUNT:
        raise AccountError(f"Infrahub does not answer the new token as {ACCOUNT}'s; {env} is left as it was")
    made.append("a token")
    say(f"made {', '.join(made)}")
    say(f"{rewrite(env, held, token)} {TOKEN_LINE} in {env}")


def parser() -> argparse.ArgumentParser:
    made = argparse.ArgumentParser(prog="account.py", description=(__doc__ or "").splitlines()[0])
    made.add_argument("--env", type=Path, required=True, help="the local/.env the token's line is written to")
    made.add_argument("--ctl", type=Path, required=True, help="infrahubctl, in a venv of its own")
    return made


def main(
    argv: Sequence[str], *, transport: httpx.BaseTransport | None = None, run: Run = subprocess.run
) -> int:
    """The account and its token's line, as `make orchestrator-env` runs it."""
    try:
        args = parser().parse_args(argv)
    except SystemExit as e:
        return 0 if e.code in (0, None) else 2
    if not args.env.is_file():
        print(f"account: {args.env} is not there: run make infrahub-up first", file=sys.stderr)
        return 2
    try:
        hub = connect(os.environ, ctl=args.ctl, transport=transport, run=run)
    except HubError as e:
        print(f"account: {e}", file=sys.stderr)
        return 2
    try:
        with client(os.environ, transport) as own:
            ensure(args.env, hub, own)
    except (AccountError, HubError, OSError) as e:
        print(f"account: {e}", file=sys.stderr)
        return 1
    finally:
        hub.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
