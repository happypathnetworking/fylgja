"""`nautobot/seed/account.py`: the reader's account, its grants, and its token's line in `local/.env`, checked before it
is trusted.

Nautobot is `FakeAccounts`, `fake.FakeNautobot` with the users, permissions and tokens of its REST API kept as
Nautobot answers them (a permission's row names no user, a list of permissions is filtered by one; a token is the
requester's whoever a request names; a user makes a token under Basic only with `add` on it), and `local/.env` a file
under `tmp_path`: nothing here opens a socket or starts a process. The tokens and the password are values of the
tests' own and the fake's. No value is compared inside an assert, whose message would print it: each is compared first
and the assert given the answer alone.
"""

from __future__ import annotations

import base64
import json
import secrets
import stat
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import account
import httpx
import pytest
from account import GRANTS, LINE, NAMES, READER, TEMPORARY, Grant
from box import ADDRESS as ADDRESS_NAME
from box import TOKEN as TOKEN_NAME
from box import Box, BoxError
from fake import ADDRESS, FakeNautobot

SECRET = "5ec4e7a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6"
"""The superuser's token, which nothing printed or raised may hold a part of."""

OTHER = f"# the developer's own\nexport FYLGJA_NAUTOBOT_ADDRESS={ADDRESS}\nFYLGJA_ELSE='kept' # a note\n".encode()
"""Three lines of `local/.env` that are none of the account's: each is kept byte for byte."""

USERS = "users/users/"
PERMISSIONS = "users/permissions/"
TOKENS = "users/tokens/"

LEAST = (
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
"""Task 1, Step 7's twelve least `view` grants, written out here so that the module's tuple is held to them."""

Handler = Callable[[httpx.Request], httpx.Response]


class FakeAccounts(FakeNautobot):
    """Nautobot's `users/` API over the fake: the superuser `admin`, holding `SECRET`, and whatever a test adds."""

    def __init__(self) -> None:
        super().__init__()
        self.people: dict[str, dict[str, Any]] = {}
        self.perms: dict[str, dict[str, Any]] = {}
        self.keys: dict[str, dict[str, Any]] = {}
        self.admin = self.person("admin", superuser=True)
        self.key(self.admin["id"], SECRET, True)

    def person(self, name: str, *, superuser: bool = False, active: bool = True) -> dict[str, Any]:
        row: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "username": name,
            "is_superuser": superuser,
            "is_active": active,
        }
        self.people[row["id"]] = row
        return row

    def key(self, owner: str, value: str, writes: bool) -> dict[str, Any]:
        row: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "key": value,
            "write_enabled": writes,
            "user": owner,
            "description": "",
        }
        self.keys[row["id"]] = row
        return row

    def permit(self, name: str, types: list[str], actions: list[str], users: list[str], **more: Any) -> dict[str, Any]:
        row: dict[str, Any] = {
            "id": str(uuid.uuid4()),
            "name": name,
            "object_types": types,
            "actions": actions,
            "users": users,
            "enabled": True,
            "constraints": None,
            **more,
        }
        self.perms[row["id"]] = row
        return row

    def reader(self) -> dict[str, Any]:
        [found] = [row for row in self.people.values() if row["username"] == READER]
        return found

    def keys_of(self, owner: dict[str, Any]) -> list[str]:
        return [row["key"] for row in self.keys.values() if row["user"] == owner["id"]]

    def named(self, name: str) -> list[dict[str, Any]]:
        return [row for row in self.perms.values() if row["name"] == name]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/")
        if not path.startswith("users/"):
            return super().__call__(request)
        self.requests.append(request)
        if len(self.requests) in self.refused:
            detail = f"refused {request.headers.get('Authorization', '')}"
            return httpx.Response(self.refused[len(self.requests)], json={"detail": detail})
        who = self.requester(request)
        if isinstance(who, httpx.Response):
            return who
        body: Any = json.loads(request.content) if request.content else None
        parts = path.strip("/").split("/")
        number = parts[2] if len(parts) > 2 else None
        collection = "/".join(parts[:2]) + "/"
        if collection == USERS:
            return self.users(request, who, number, body)
        if collection == PERMISSIONS:
            return self.permissions(request, who, number, body)
        assert collection == TOKENS, f"the fake answers no {request.method} {path}"
        return self.tokens(request, who, body)

    def requester(self, request: httpx.Request) -> dict[str, Any] | httpx.Response:
        head = request.headers.get("Authorization", "")
        if head.startswith("Token "):
            for row in self.keys.values():
                if row["key"] == head.removeprefix("Token "):
                    return self.people[row["user"]]
            return httpx.Response(403, json={"detail": "Invalid token"})
        if head.startswith("Basic "):
            name, _, password = base64.b64decode(head.removeprefix("Basic ")).decode().partition(":")
            for row in self.people.values():
                if row["username"] == name and row.get("password") == password and row["is_active"]:
                    return row
        return httpx.Response(401, json={"detail": "Invalid username/password"})

    def allowed(self, who: dict[str, Any], action: str, kind: str, owner: str | None = None) -> bool:
        if who["is_superuser"]:
            return True
        for row in self.perms.values():
            holds = who["id"] in row["users"] and row["enabled"]
            holds = holds and action in row["actions"] and kind in row["object_types"]
            own = row["constraints"] == {"user": "$user"} and owner == who["id"]
            if holds and (row["constraints"] in (None, {}) or own):
                return True
        return False

    def denied(self) -> httpx.Response:
        return httpx.Response(403, json={"detail": "You do not have permission to perform this action."})

    def listing(self, request: httpx.Request, rows: list[dict[str, Any]]) -> httpx.Response:
        params = request.url.params
        limit, offset = int(params.get("limit", 50)), int(params.get("offset", 0))
        following = f"{ADDRESS}/api/next/" if offset + limit < len(rows) else None
        shown = rows[offset : offset + limit]
        return httpx.Response(200, json={"count": len(rows), "next": following, "previous": None, "results": shown})

    def users(self, request: httpx.Request, who: dict[str, Any], number: str | None, body: Any) -> httpx.Response:
        assert who["is_superuser"], "the fake lets the superuser alone at users"
        shown = hiding("password")
        if request.method == "GET":
            rows = list(self.people.values())
            for name, value in request.url.params.multi_items():
                if name not in ("limit", "offset"):
                    assert name == "username", f"the fake knows no filter {name} of users"
                    rows = [row for row in rows if row["username"] == value]
            return self.listing(request, [shown(row) for row in rows])
        if request.method == "POST":
            row = self.person(body["username"], active=body.get("is_active", True))
            return httpx.Response(201, json=shown(row))
        assert request.method == "PATCH" and number is not None
        self.people[number].update(body)
        return httpx.Response(200, json=shown(self.people[number]))

    def permissions(self, request: httpx.Request, who: dict[str, Any], number: str | None, body: Any) -> httpx.Response:
        assert who["is_superuser"], "the fake lets the superuser alone at permissions"
        shown = hiding("users")
        if request.method == "GET":
            rows = list(self.perms.values())
            for name, value in request.url.params.multi_items():
                if name == "name":
                    rows = [row for row in rows if row["name"] == value]
                elif name == "users":
                    rows = [row for row in rows if value in row["users"]]
                else:
                    assert name in ("limit", "offset"), f"the fake knows no filter {name} of permissions"
            return self.listing(request, [shown(row) for row in rows])
        if request.method == "POST":
            row = self.permit(
                body["name"],
                body["object_types"],
                body["actions"],
                body.get("users", []),
                constraints=body.get("constraints"),
                enabled=body.get("enabled", True),
            )
            return httpx.Response(201, json=shown(row))
        assert number is not None
        if request.method == "DELETE":
            del self.perms[number]
            return httpx.Response(204)
        assert request.method == "PATCH"
        for member, value in body.items():
            self.perms[number][member] = value
        return httpx.Response(200, json=shown(self.perms[number]))

    def tokens(self, request: httpx.Request, who: dict[str, Any], body: Any) -> httpx.Response:
        shown = hiding("user")
        mine = [row for row in self.keys.values() if row["user"] == who["id"]]
        if request.method == "GET":
            if not self.allowed(who, "view", "users.token", who["id"]):
                return self.denied()
            return self.listing(request, [shown(row) for row in mine])
        assert request.method == "POST"
        if not self.allowed(who, "add", "users.token", who["id"]):
            return self.denied()
        made = self.key(who["id"], secrets.token_hex(20), body.get("write_enabled", True))
        made["description"] = body.get("description", "")
        return httpx.Response(201, json=shown(made))


def hiding(member: str) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """A function that answers a row without its `member`, as Nautobot's serializer leaves it out."""

    def shown(row: dict[str, Any]) -> dict[str, Any]:
        return {name: value for name, value in row.items() if name != member}

    return shown


@pytest.fixture(autouse=True)
def environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ADDRESS_NAME, ADDRESS)
    monkeypatch.setenv(TOKEN_NAME, SECRET)


def over(handler: Handler) -> Box:
    return Box(ADDRESS, SECRET, transport=httpx.MockTransport(handler))


def env_file(tmp_path: Path, data: bytes = OTHER) -> Path:
    path = tmp_path / ".env"
    path.write_bytes(data)
    path.chmod(0o600)
    return path


def run(handler: Handler, env: Path, capsys: pytest.CaptureFixture[str]) -> tuple[int, str, str]:
    code = account.main(["--env", str(env)], transport=httpx.MockTransport(handler))
    out, err = capsys.readouterr()
    return code, out, err


def passwords(fake: FakeAccounts) -> list[str]:
    return [str(body["password"]) for path, body in fake.sent("PATCH") if path.startswith(USERS) and "password" in body]


def seeded(tmp_path: Path) -> tuple[FakeAccounts, Path]:
    """A fake and a file over which a first run has made everything, the fake's requests forgotten."""
    fake = FakeAccounts()
    env = env_file(tmp_path)
    account.ensure(env, over(fake))
    fake.requests.clear()
    return fake, env


def line_of(env: Path) -> str:
    found = account.held(env.read_bytes(), LINE)
    assert found is not None
    return found


def test_the_grants_are_view_alone_and_name_the_reader() -> None:
    grants = {grant.name: grant for grant in GRANTS}
    assert len(grants) == len(GRANTS) == 14
    assert {kind for grant in GRANTS for kind in grant.object_types} == {
        *LEAST,
        "users.token",
        "extras.staticgroupassociation",
    }
    assert all(grant.actions == ("view",) for grant in GRANTS)
    assert all(grant.name.startswith(f"{READER}-") for grant in GRANTS)
    assert [grant.name for grant in GRANTS if grant.constraints is not None] == [f"{READER}-users.token"]
    assert grants[f"{READER}-users.token"].constraints == {"user": "$user"}
    assert (TEMPORARY.actions, TEMPORARY.constraints) == (("add",), {"user": "$user"})
    assert TEMPORARY.name in NAMES
    assert TEMPORARY not in GRANTS


def test_a_first_run_makes_the_account_its_grants_and_a_write_disabled_token_and_writes_its_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeAccounts()
    env = env_file(tmp_path)
    code, out, err = run(fake, env, capsys)
    assert (code, err) == (0, "")
    reader = fake.reader()
    assert (reader["is_superuser"], reader["is_active"]) == (False, True)
    rows = [row for row in fake.perms.values() if reader["id"] in row["users"]]
    assert sorted(row["name"] for row in rows) == sorted(grant.name for grant in GRANTS)
    assert all(row["actions"] == ["view"] and row["users"] == [reader["id"]] for row in rows)
    [mine] = [row for row in fake.keys.values() if row["user"] == reader["id"]]
    assert mine["write_enabled"] is False
    after = env.read_bytes()
    assert after.startswith(OTHER)
    assert after[len(OTHER) :] == f"{LINE}={mine['key']}\n".encode()
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert "made the user fylgja-reader" in out
    assert f"appended {LINE}" in out
    assert not [row for row in fake.perms.values() if row["name"] == TEMPORARY.name]


def test_the_account_makes_its_own_token_under_basic_and_holds_view_alone_at_rest(tmp_path: Path) -> None:
    fake = FakeAccounts()
    account.ensure(env_file(tmp_path), over(fake))
    posts = [request for request in fake.requests if request.method == "POST" and request.url.path.endswith("tokens/")]
    [post] = posts
    assert post.headers["Authorization"].startswith("Basic ")
    assert json.loads(post.content)["write_enabled"] is False
    assert [request.method for request in fake.requests if TEMPORARY.name in request.content.decode()] == ["POST"]
    assert fake.named(TEMPORARY.name) == []
    reader = fake.reader()
    actions = {action for row in fake.perms.values() if reader["id"] in row["users"] for action in row["actions"]}
    assert actions == {"view"}


def test_a_line_nautobot_still_takes_is_kept_byte_for_byte(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fake, env = seeded(tmp_path)
    before = env.read_bytes()
    code, out, err = run(fake, env, capsys)
    assert (code, err) == (0, "")
    assert env.read_bytes() == before
    assert "nothing written" in out
    assert fake.writes() == []
    quoted = f'{LINE}="{line_of(env)}" # kept\n'.encode()
    env.write_bytes(before.replace(f"{LINE}={line_of(env)}\n".encode(), quoted))
    assert run(fake, env, capsys)[0] == 0
    assert env.read_bytes().endswith(quoted)
    assert fake.writes() == []


@pytest.mark.parametrize("kind", ["absent", "dead", "writes", "another account's", "the superuser's", "malformed"])
def test_a_dead_line_a_write_enabled_one_and_another_accounts_are_replaced(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], kind: str
) -> None:
    fake, env = seeded(tmp_path)
    old = line_of(env)
    reader = fake.reader()
    other = fake.person("someone")
    fake.permit("someone-tokens", ["users.token"], ["view"], [other["id"]], constraints={"user": "$user"})
    if kind == "absent":
        env.write_bytes(OTHER)
        wanted = None
    elif kind == "dead":
        wanted = secrets.token_hex(20)
    elif kind == "writes":
        wanted = fake.key(reader["id"], secrets.token_hex(20), True)["key"]
    elif kind == "another account's":
        wanted = fake.key(other["id"], secrets.token_hex(20), False)["key"]
    elif kind == "the superuser's":
        wanted = fake.key(fake.admin["id"], secrets.token_hex(20), False)["key"]
    else:
        wanted = "not-a-token"
    if wanted is not None:
        env.write_bytes(OTHER + f"{LINE}={wanted}\n".encode())
    before = len(fake.keys_of(reader))
    code, out, err = run(fake, env, capsys)
    assert (code, err) == (0, "")
    new = line_of(env)
    assert (new == wanted, new == old) == (False, False)
    assert new in fake.keys_of(reader)
    assert len(fake.keys_of(reader)) == before + 1
    assert env.read_bytes().startswith(OTHER)
    assert f"{'appended' if kind == 'absent' else 'replaced'} {LINE}" in out
    assert [row["write_enabled"] for row in fake.keys.values() if row["key"] == new] == [False]


def test_a_grant_is_brought_to_exactly_its_row(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fake, env = seeded(tmp_path)
    reader = fake.reader()
    second = fake.person("second")
    [device] = fake.named(f"{READER}-dcim.device")
    [tag] = fake.named(f"{READER}-extras.tag")
    [token] = fake.named(f"{READER}-users.token")
    [cable] = fake.named(f"{READER}-dcim.cable")
    device["actions"] = ["view", "change"]
    tag["object_types"] = ["extras.tag", "dcim.site"]
    token["users"] = [reader["id"], second["id"]]
    cable["constraints"] = {"name": "n1"}
    fake.requests.clear()
    code, out, err = run(fake, env, capsys)
    assert (code, err) == (0, "")
    patched = [path for path, _ in fake.sent("PATCH")]
    assert sorted(patched) == sorted(f"{PERMISSIONS}{row['id']}/" for row in (device, tag, token, cable))
    assert device["actions"] == ["view"] and tag["object_types"] == ["extras.tag"]
    assert token["users"] == [reader["id"]] and cable["constraints"] is None
    assert out.count("brought the permission") == 4
    fake.requests.clear()
    assert run(fake, env, capsys)[0] == 0
    assert fake.sent("PATCH") == []

    [interface] = fake.named(f"{READER}-dcim.interface")
    interface["enabled"] = False
    fake.requests.clear()
    assert run(fake, env, capsys)[0] == 0
    assert len(fake.sent("PATCH")) == 1 and interface["enabled"] is True


def test_another_permission_or_a_group_is_refused_and_nothing_removed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake, env = seeded(tmp_path)
    reader = fake.reader()
    stray = fake.permit("someone-else", ["dcim.device"], ["view", "change"], [reader["id"]])
    before = env.read_bytes()
    fake.requests.clear()
    code, _out, err = run(fake, env, capsys)
    assert code == 1
    assert "someone-else" in err and "nothing removed" in err and "make nautobot-down PURGE=1" in err
    assert fake.writes() == [] and stray["id"] in fake.perms and env.read_bytes() == before

    del fake.perms[stray["id"]]
    fake.people[reader["id"]]["is_superuser"] = True
    fake.requests.clear()
    code, _out, err = run(fake, env, capsys)
    assert code == 1 and "superuser" in err and fake.writes() == [] and env.read_bytes() == before


def test_a_user_found_inactive_is_set_active(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fake, env = seeded(tmp_path)
    fake.reader()["is_active"] = False
    fake.requests.clear()
    assert run(fake, env, capsys)[0] == 0
    assert fake.reader()["is_active"] is True
    assert [path for path, _ in fake.sent("PATCH")] == [f"{USERS}{fake.reader()['id']}/"]


def test_nautobot_not_answering_leaves_the_file_as_it_was(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    def silent(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    env = env_file(tmp_path)
    code, _out, err = run(silent, env, capsys)
    assert code == 1 and env.read_bytes() == OTHER
    assert "make nautobot-up" in err
    fake = FakeAccounts()
    count = len(fake.requests)
    account.ensure(env_file(tmp_path), over(fake))
    total = len(fake.requests) - count
    [gone] = [at for at, request in enumerate(fake.requests, 1) if request.method == "DELETE"]
    for step in range(1, total + 1):
        again = FakeAccounts()
        again.refused[step] = 500
        env = env_file(tmp_path)
        code, _out, err = run(again, env, capsys)
        assert code == 1, step
        assert env.read_bytes() == OTHER, step
        assert bool(again.named(TEMPORARY.name)) == (step == gone), step
        again.refused.clear()
        assert run(again, env, capsys)[0] == 0, step
        assert not again.named(TEMPORARY.name), step


def test_nothing_printed_or_raised_holds_a_token_or_a_password(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    probe = FakeAccounts()
    account.ensure(env_file(tmp_path), over(probe))
    total = len(probe.requests)
    for step in [0, *range(1, total + 1)]:
        fake = FakeAccounts()
        if step:
            fake.refused[step] = 403
        old = secrets.token_hex(20)
        fake.key(fake.admin["id"], old, False)
        env = env_file(tmp_path, OTHER + f"{LINE}={old}\n".encode())
        code, out, err = run(fake, env, capsys)
        said = out + err
        secretly = [SECRET, old, *passwords(fake)]
        secretly += [row["key"] for row in fake.keys.values() if row["user"] != fake.admin["id"]]
        secretly += [
            request.headers["Authorization"].removeprefix("Basic ")
            for request in fake.requests
            if request.headers["Authorization"].startswith("Basic ")
        ]
        leaked = [value for value in secretly if value and value in said]
        assert leaked == [], (step, code)
    # A failure of the box itself, raised and not printed, holds none of them either.
    fake = FakeAccounts()
    fake.refused[total - 1] = 403
    box = over(fake)
    with pytest.raises(BoxError) as caught:
        account.ensure(env_file(tmp_path), box)
    text = str(caught.value)
    assert [value for value in [SECRET, *passwords(fake)] if value in text] == []


def test_a_variable_not_set_or_a_file_not_there_is_exit_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeAccounts()
    missing = tmp_path / "nope"
    code, _out, err = run(fake, missing, capsys)
    assert (code, "is not there" in err) == (2, True)
    env = env_file(tmp_path)
    for name in (ADDRESS_NAME, TOKEN_NAME):
        monkeypatch.delenv(name)
        code, _out, err = run(fake, env, capsys)
        assert (code, name in err, env.read_bytes()) == (2, True, OTHER)
        monkeypatch.setenv(name, ADDRESS if name == ADDRESS_NAME else SECRET)
    assert account.main(["--nope"]) == 2
    assert fake.requests == []


def test_a_grant_is_a_frozen_row() -> None:
    grant = Grant("g", ("dcim.device",), ("view",))
    with pytest.raises(AttributeError):
        grant.name = "h"  # type: ignore[misc]
    assert grant.constraints is None


def test_the_mints_error_is_the_one_raised_and_names_the_leftover_grant(tmp_path: Path) -> None:
    probe = FakeAccounts()
    account.ensure(env_file(tmp_path), over(probe))
    [gone] = [at for at, request in enumerate(probe.requests, 1) if request.method == "DELETE"]
    posted = gone - 1
    assert probe.requests[posted - 1].url.path.endswith("users/tokens/")

    both = FakeAccounts()
    both.refused = {posted: 403, gone: 500}
    with pytest.raises(BoxError) as caught:
        account.ensure(env_file(tmp_path), over(both))
    text = str(caught.value)
    assert caught.value.status == 403
    assert "HTTP 403" in text and "make nautobot-seed" in text and TEMPORARY.name in text
    assert both.named(TEMPORARY.name)
    secretly = [SECRET, *passwords(both)]
    secretly += [r.headers["Authorization"].removeprefix("Basic ") for r in both.requests[posted - 1 : posted]]
    assert [value for value in secretly if value in text] == []

    only = FakeAccounts()
    only.refused = {gone: 500}
    with pytest.raises(BoxError) as caught:
        account.ensure(env_file(tmp_path), over(only))
    assert "make nautobot-seed" in str(caught.value) and TEMPORARY.name in str(caught.value)
    assert only.named(TEMPORARY.name)
    assert [value for value in [SECRET, *passwords(only)] if value in str(caught.value)] == []


def test_the_accounts_own_refusal_is_not_met_with_the_superusers_remedy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A 403 of the account's own Basic POST says nothing of the superuser's token, which the run still held."""
    probe = FakeAccounts()
    account.ensure(env_file(tmp_path), over(probe))
    [gone] = [at for at, request in enumerate(probe.requests, 1) if request.method == "DELETE"]
    posted = gone - 1
    for status in (401, 403):
        fake = FakeAccounts()
        fake.refused[posted] = status
        code, _out, err = run(fake, env_file(tmp_path), capsys)
        assert code == 1
        assert f"HTTP {status}" in err
        assert account.RELOAD not in err
        assert not fake.named(TEMPORARY.name)
    # The superuser's own refusal, on a request that is the superuser's, keeps its remedy.
    fake = FakeAccounts()
    fake.refused[1] = 403
    code, _out, err = run(fake, env_file(tmp_path), capsys)
    assert (code, account.RELOAD in err) == (1, True)


def test_the_temporary_grant_is_deleted_whatever_the_account_step_raises(tmp_path: Path) -> None:
    """An exception that is no `BoxError`, out of the Basic step, still finds the grant deleted, and is the one
    raised."""
    probe = FakeAccounts()
    account.ensure(env_file(tmp_path), over(probe))
    [gone] = [at for at, request in enumerate(probe.requests, 1) if request.method == "DELETE"]
    posted = gone - 1

    fake = FakeAccounts()

    def handler(request: httpx.Request) -> httpx.Response:
        if len(fake.requests) + 1 == posted:
            fake.requests.append(request)
            raise RuntimeError("the transport broke")
        return fake(request)

    box = Box(ADDRESS, SECRET, transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="the transport broke"):
        account.ensure(env_file(tmp_path), box)
    assert fake.named(TEMPORARY.name) == []
