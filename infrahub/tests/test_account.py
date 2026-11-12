"""`infrahub/seed/account.py`: the example's Infrahub account `fylgja-orchestrator`, its role of four permissions and
its group, and its token's line in `local/.env`, checked before it is trusted.

Infrahub is a fake behind `httpx.MockTransport`: the admin's GraphQL by the writer's token, a login, a token made with
a login's bearer, and `AccountProfile` answered to an account's token or refused 401 where the token is none or its
account is gone (design/verified-facts.md, "Infrahub 1.11.11"). Nothing here opens a socket or starts a process. No
value of a token or a password is compared inside an assert, whose message would print it: each is compared first
and the assert given the answer alone (as `core/tests/test_config.py`'s `same()`).
"""

from __future__ import annotations

import itertools
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

import account
import httpx
import pytest

HOST = "infrahub.example"
ADDRESS = f"http://{HOST}"
ADMIN = "an-admin-token"
CTL = Path("/opt/example/bin/infrahubctl")
LINE = "FYLGJA_ORCHESTRATOR_INFRAHUB_TOKEN"
VIEW_ALL = ("object", "*", "*", "view", 6)
"""The instance's own permission `object:*:*:view:allow_all`, there from its first start."""


@pytest.fixture(autouse=True)
def environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test starts from an environment of its own, `PATH` and the writer's two names alone, so none holds the
    developer's (a shell may have `local/.env` loaded)."""
    path = os.environ.get("PATH", "")
    for name in list(os.environ):
        if name != "PYTEST_CURRENT_TEST":
            monkeypatch.delenv(name)
    monkeypatch.setenv("PATH", path)
    monkeypatch.setenv("FYLGJA_INFRAHUB_ADDRESS", ADDRESS)
    monkeypatch.setenv("FYLGJA_INFRAHUB_WRITE_TOKEN", ADMIN)


def literals(query: str) -> dict[str, str]:
    """The literal arguments of `query`, a filter's `name__value: x` and a create's `name: {value: x}`, by name."""
    found = re.findall(r'(\w+?)(?:__value)?: (?:\{value: )?(?:"([^"]*)"|(\d+))', query)
    return {name: text or number for name, text, number in found}


class Infrahub:
    """Infrahub as `account.py` meets it. `accounts` by name hold an id and a password, `roles` and `groups` by name
    their ids and members, `permissions` each its kind, namespace, name, action and decision with its id; `tokens`
    name each live token's account. A token whose account is deleted is refused 401, as one that is no token.
    `mutations` keeps each mutation's root in order, the admin's and the bearer's. A root in `misshapen` answers a
    body of another shape than its query's."""

    def __init__(self, *, account_held: bool = False, misshapen: str = "") -> None:
        self.misshapen = misshapen
        self.ids = itertools.count(1)
        self.permissions: dict[tuple[str, str, str, str, int], str] = {VIEW_ALL: self.new("perm")}
        self.roles: dict[str, dict[str, Any]] = {}
        self.groups: dict[str, dict[str, Any]] = {}
        self.accounts: dict[str, dict[str, str]] = {}
        self.tokens: dict[str, str] = {}
        self.bearers: dict[str, str] = {}
        self.mutations: list[str] = []
        self.logins: list[str] = []
        if account_held:
            self.accounts["fylgja-orchestrator"] = {"id": self.new("account"), "password": "a-lost-password"}

    def new(self, prefix: str) -> str:
        return f"{prefix}-{next(self.ids)}"

    def issue(self, name: str) -> str:
        """A token of the account `name`, as Infrahub makes one: 36 characters."""
        made = f"{next(self.ids):08d}-0000-4000-8000-{name[:12]:>012}".replace(" ", "0")
        self.tokens[made] = name
        return made

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/login":
            body = json.loads(request.content)
            held = self.accounts.get(body["username"])
            if held is None or held["password"] != body["password"]:
                return httpx.Response(401, json={"detail": "Incorrect username or password"})
            self.logins.append(body["username"])
            bearer = self.new("jwt")
            self.bearers[bearer] = body["username"]
            return httpx.Response(200, json={"access_token": bearer, "refresh_token": self.new("refresh")})
        assert request.url.path == "/graphql/main"
        query = json.loads(request.content)["query"]
        variables = json.loads(request.content).get("variables") or {}
        [root] = re.findall(r"^\s*(?:query|mutation)[^{]*\{\s*(\w+)", query)
        key = request.headers.get("x-infrahub-key")
        if key == ADMIN:
            if query.lstrip().startswith("mutation"):
                self.mutations.append(root)
            answer: dict[str, Any] = getattr(self, root)(query, variables)
            if root == self.misshapen:
                answer = {"count": 1}
            return httpx.Response(200, json={"data": {root: answer}})
        if key is not None:
            name = self.tokens.get(key)
            if name is None or name not in self.accounts:
                errors = [{"message": "Invalid token", "extensions": {"code": "AUTHENTICATION_REQUIRED"}}]
                return httpx.Response(401, json={"data": None, "errors": errors})
            assert root == "AccountProfile"
            return httpx.Response(200, json={"data": {"AccountProfile": {"name": {"value": name}}}})
        bearer = request.headers["authorization"].removeprefix("Bearer ")
        assert root == "InfrahubAccountTokenCreate"
        self.mutations.append(root)
        token = self.issue(self.bearers[bearer])
        return httpx.Response(200, json={"data": {root: {"ok": True, "object": {"token": {"value": token}}}}})

    def permission_key(self, kind: str, query: str) -> tuple[str, str, str, str, int]:
        held = literals(query)
        return (kind, held.get("namespace", ""), held.get("name", ""), held["action"], int(held["decision"]))

    def edges(self, *ids: str) -> dict[str, Any]:
        return {"count": len(ids), "edges": [{"node": {"id": found}} for found in ids]}

    def CoreObjectPermission(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        held = self.permissions.get(self.permission_key("object", query))
        return self.edges(*([held] if held else []))

    def CoreGlobalPermission(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        held = self.permissions.get(self.permission_key("global", query))
        return self.edges(*([held] if held else []))

    def CoreObjectPermissionCreate(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        made = self.permissions[self.permission_key("object", query)] = self.new("perm")
        return {"ok": True, "object": {"id": made}}

    def CoreGlobalPermissionCreate(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        made = self.permissions[self.permission_key("global", query)] = self.new("perm")
        return {"ok": True, "object": {"id": made}}

    def CoreAccountRole(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        held = self.roles.get(variables["name"])
        if held is None:
            return {"count": 0, "edges": []}
        return {"count": 1, "edges": [{"node": {"id": held["id"], "permissions": self.edges(*held["permissions"])}}]}

    def CoreAccountRoleUpdate(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        [held] = [held for held in self.roles.values() if held["id"] == variables["id"]]
        held["permissions"] = [found["id"] for found in variables["permissions"]]
        return {"ok": True}

    def CoreAccountRoleCreate(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        made = {"id": self.new("role"), "permissions": [found["id"] for found in variables["permissions"]]}
        self.roles[variables["name"]] = made
        return {"ok": True, "object": {"id": made["id"]}}

    def CoreAccount(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        held = self.accounts.get(variables["name"])
        return self.edges(*([held["id"]] if held else []))

    def CoreAccountCreate(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        made = {"id": self.new("account"), "password": variables["password"]}
        self.accounts[variables["name"]] = made
        return {"ok": True, "object": {"id": made["id"]}}

    def CoreAccountUpdate(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        [held] = [held for held in self.accounts.values() if held["id"] == variables["id"]]
        held["password"] = variables["password"]
        return {"ok": True}

    def CoreAccountGroup(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        held = self.groups.get(variables["name"])
        if held is None:
            return {"count": 0, "edges": []}
        live = [member for member in held["members"] if member in {a["id"] for a in self.accounts.values()}]
        node = {
            "id": held["id"],
            "roles": self.edges(*held["roles"]),
            "members": self.edges(*live),
        }
        return {"count": 1, "edges": [{"node": node}]}

    def CoreAccountGroupCreate(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        made = {"id": self.new("group"), "roles": [variables["role"]], "members": [variables["account"]]}
        self.groups[variables["name"]] = made
        return {"ok": True, "object": {"id": made["id"]}}

    def CoreAccountGroupDelete(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        self.groups = {name: held for name, held in self.groups.items() if held["id"] != variables["id"]}
        return {"ok": True}

    def delete_account(self, name: str) -> None:
        """The account deleted through the API: its tokens are refused from then on."""
        del self.accounts[name]


def run(infrahub: Infrahub, env: Path) -> int:
    return account.main(["--env", str(env), "--ctl", str(CTL)], transport=httpx.MockTransport(infrahub))


def written(path: Path, text: str) -> Path:
    path.write_text(text)
    path.chmod(0o600)
    return path


def token_lines(path: Path) -> list[str]:
    return [line for line in path.read_text().splitlines() if line.startswith(f"{LINE}=")]


WANTED = [
    ("object", "Core", "ChangeThread", "create", 2),
    ("object", "Core", "ThreadComment", "create", 2),
    ("global", "", "", "edit_default_branch", 2),
    VIEW_ALL,
]
"""The role's four permissions, in order, by the fake's keys."""


def told(capsys: pytest.CaptureFixture[str], *values: str) -> tuple[str, bool]:
    """What the run printed, out and err, and whether any of `values` is in it, worked out outside an assert."""
    captured = capsys.readouterr()
    said = captured.out + captured.err
    return said, any(value in said for value in values)


def test_a_file_with_no_line_gains_one(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    env = written(tmp_path / ".env", f"FYLGJA_INFRAHUB_ADDRESS={ADDRESS}\nFYLGJA_API_TOKEN=abc\n")
    before = env.read_bytes()
    infrahub = Infrahub()
    assert run(infrahub, env) == 0
    [line] = token_lines(env)
    token = line.split("=", 1)[1]
    owner = infrahub.tokens.get(token)
    assert owner == "fylgja-orchestrator"
    kept = env.read_bytes().startswith(before)
    assert kept, "a byte before the new line changed"
    assert len(env.read_text().splitlines()) == 3
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    # The four permissions, the instance's view of every kind among them, in one role of one group.
    [role] = infrahub.roles.values()
    assert role["permissions"] == [infrahub.permissions[key] for key in WANTED]
    [group] = infrahub.groups.values()
    assert (group["roles"], group["members"]) == ([role["id"]], [infrahub.accounts["fylgja-orchestrator"]["id"]])
    password = infrahub.accounts["fylgja-orchestrator"]["password"]
    said, leaked = told(capsys, token, password)
    assert not leaked, "a value was printed"
    assert "the account fylgja-orchestrator" in said
    assert f"appended {LINE}" in said
    assert "object:Core:ChangeThread:create:allow_default" in said


def test_a_line_infrahub_accepts_is_left_byte_for_byte(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    env = written(tmp_path / ".env", "A=1\n")
    infrahub = Infrahub()
    assert run(infrahub, env) == 0
    capsys.readouterr()
    before, made = env.read_bytes(), list(infrahub.mutations)
    assert run(infrahub, env) == 0
    same = env.read_bytes() == before
    assert same, "the file changed"
    assert infrahub.mutations == made, "no mutation sent: the role holds the four already"
    said, _ = told(capsys)
    assert "made" not in said
    assert f"{LINE} in {env} is accepted" in said


@pytest.mark.parametrize("held", [True, False], ids=["account-held", "account-deleted"])
def test_a_line_infrahub_refuses_is_replaced_and_every_other_line_untouched(
    held: bool, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A purge keeps `local/.env`, so a token made on the purged instance is dead on the next (plan 0, reconciled 21).
    Where the account is held, the admin sets it a new password, it logs in and makes a token, and it is kept; where
    it was deleted, it is made again and put in its group again (P5-16)."""
    infrahub = Infrahub()
    env = written(tmp_path / ".env", "A=1\n")
    assert run(infrahub, env) == 0
    [old_line] = token_lines(env)
    old = old_line.split("=", 1)[1]
    around = f"# a note\nFYLGJA_INFRAHUB_ADDRESS={ADDRESS}\n{old_line}\nB='two words'\n"
    env = written(env, around)
    if held:
        kept = infrahub.accounts["fylgja-orchestrator"]["id"]
        del infrahub.tokens[old]  # the instance purged and made again: the account is there, its token is not
    else:
        infrahub.delete_account("fylgja-orchestrator")
    capsys.readouterr()
    infrahub.mutations.clear()
    assert run(infrahub, env) == 0

    [new_line] = token_lines(env)
    new = new_line.split("=", 1)[1]
    replaced = new != old
    owner = infrahub.tokens.get(new)
    assert replaced
    assert owner == "fylgja-orchestrator"
    kept_around = env.read_text() == around.replace(old_line, new_line)
    assert kept_around, "a line around the token's changed"
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    if held:
        assert infrahub.accounts["fylgja-orchestrator"]["id"] == kept
        assert "CoreAccountUpdate" in infrahub.mutations
        assert "CoreAccountCreate" not in infrahub.mutations
    else:
        assert "CoreAccountCreate" in infrahub.mutations
        [group] = infrahub.groups.values()
        assert group["members"] == [infrahub.accounts["fylgja-orchestrator"]["id"]]
    password = infrahub.accounts["fylgja-orchestrator"]["password"]
    said, leaked = told(capsys, old, new, password)
    assert not leaked, "a value was printed"
    assert f"replaced {LINE}" in said


def test_the_line_is_never_trusted_on_a_failure_to_ask(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Infrahub not answering the check is no refusal: nothing is made and the file is left as it was."""
    env = written(tmp_path / ".env", f"{LINE}=00000000-0000-4000-8000-000000000000\n")
    before = env.read_bytes()

    def away(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    assert account.main(["--env", str(env), "--ctl", str(CTL)], transport=httpx.MockTransport(away)) == 1
    same = env.read_bytes() == before
    assert same, "the file changed"
    said, leaked = told(capsys, "00000000-0000-4000-8000-000000000000", ADMIN)
    assert not leaked, "a value was printed"
    assert f"was not answered by {ADDRESS}" in said


def test_a_file_that_is_not_there_or_a_variable_not_set_is_exit_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert account.main(["--env", str(tmp_path / "absent"), "--ctl", str(CTL)]) == 2
    assert "absent" in capsys.readouterr().err
    monkeypatch.delenv("FYLGJA_INFRAHUB_WRITE_TOKEN")
    assert account.main(["--env", str(written(tmp_path / ".env", "")), "--ctl", str(CTL)]) == 2
    assert "FYLGJA_INFRAHUB_WRITE_TOKEN is not set" in capsys.readouterr().err
    assert account.main([]) == 2


def test_a_held_role_is_brought_to_exactly_the_four_permissions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A role left holding three of the four and one other reads nothing a rehearsal needs and may do more than it
    should: it is set to the four, and kept (P5-36)."""
    infrahub = Infrahub()
    stray = infrahub.permissions[("object", "Dcim", "Device", "update", 6)] = infrahub.new("perm")
    three = [infrahub.permissions.setdefault(key, infrahub.new("perm")) for key in WANTED[:3]]
    infrahub.roles["fylgja-orchestrator"] = {"id": "role-held", "permissions": [*three, stray]}
    env = written(tmp_path / ".env", "A=1\n")
    assert run(infrahub, env) == 0
    assert infrahub.roles["fylgja-orchestrator"]["permissions"] == [infrahub.permissions[key] for key in WANTED]
    assert infrahub.roles["fylgja-orchestrator"]["id"] == "role-held"
    assert "CoreAccountRoleUpdate" in infrahub.mutations
    assert "CoreAccountRoleCreate" not in infrahub.mutations
    assert "set the role fylgja-orchestrator to its four permissions" in told(capsys)[0]


def test_an_accepted_line_on_a_role_of_three_mends_the_role_alone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A valid token on a role of three reads nothing, so the role is read on the accepted path too, and the one
    mutation sent is its update (P5-38)."""
    infrahub = Infrahub()
    env = written(tmp_path / ".env", "A=1\n")
    assert run(infrahub, env) == 0
    infrahub.roles["fylgja-orchestrator"]["permissions"] = infrahub.roles["fylgja-orchestrator"]["permissions"][:3]
    before = env.read_bytes()
    infrahub.mutations.clear()
    capsys.readouterr()
    assert run(infrahub, env) == 0
    same = env.read_bytes() == before
    assert same, "the file changed"
    assert infrahub.mutations == ["CoreAccountRoleUpdate"]
    assert infrahub.roles["fylgja-orchestrator"]["permissions"] == [infrahub.permissions[key] for key in WANTED]
    said = told(capsys)[0]
    assert "set the role fylgja-orchestrator to its four permissions" in said
    assert f"{LINE} in {env} is accepted" in said


def test_a_line_holding_another_accounts_live_token_is_replaced(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A token Infrahub answers as another account's is not the example's: the line is replaced, and the other
    token, its owner's to revoke, is left live."""
    infrahub = Infrahub()
    infrahub.accounts["someone"] = {"id": infrahub.new("account"), "password": "theirs"}
    theirs = infrahub.issue("someone")
    env = written(tmp_path / ".env", f"A=1\n{LINE}={theirs}\nB=2\n")
    assert run(infrahub, env) == 0
    [line] = token_lines(env)
    token = line.split("=", 1)[1]
    owner, left_live = infrahub.tokens.get(token), infrahub.tokens.get(theirs) == "someone"
    assert owner == "fylgja-orchestrator"
    assert left_live
    lines = env.read_text().splitlines()
    around = (lines[0], lines[2], len(lines)) == ("A=1", "B=2", 3)
    assert around, "a line around the token's changed"
    said, leaked = told(capsys, theirs, token)
    assert not leaked, "a value was printed"
    assert f"{LINE} in {env} is another account's" in said


def test_two_token_lines_are_collapsed_into_one_where_the_first_stood(tmp_path: Path) -> None:
    infrahub = Infrahub()
    dead = ("00000000-0000-4000-8000-000000000001", "00000000-0000-4000-8000-000000000002")
    env = written(tmp_path / ".env", f"A=1\n{LINE}={dead[0]}\nB=2\nexport {LINE}='{dead[1]}'\nC=3\n")
    assert run(infrahub, env) == 0
    lines = env.read_text().splitlines()
    assert [line.split("=", 1)[0] for line in lines] == ["A", LINE, "B", "C"]
    owner = infrahub.tokens.get(lines[1].split("=", 1)[1])
    assert owner == "fylgja-orchestrator"


@pytest.mark.parametrize(
    ("line", "held"),
    [
        (f"{LINE}=abc", "abc"),
        (f"export {LINE}=abc", "abc"),
        (f'{LINE}="abc"', "abc"),
        (f"{LINE}='abc' # a note", "abc"),
        (f"{LINE}=abc # a note", "abc"),
        (f"  {LINE}=abc  ", "abc"),
        (f"{LINE}=", ""),
        (f"# {LINE}=abc", None),
        (f"{LINE}_OTHER=abc", None),
        ("A=abc", None),
    ],
)
def test_a_line_is_read_as_a_shell_reads_it(line: str, held: str | None) -> None:
    assert account.value(line) == held


def test_an_answer_of_another_shape_is_one_sentence(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for root in ("CoreAccountRole", "CoreAccountGroup", "CoreObjectPermission"):
        env = written(tmp_path / ".env", "A=1\n")
        assert run(Infrahub(misshapen=root), env) == 1
        captured = capsys.readouterr()
        assert captured.err == f"account: {root} answered in a shape not of its query\n"
        assert "Traceback" not in captured.out + captured.err


def test_a_file_wider_than_0600_is_set_to_it(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    infrahub = Infrahub()
    env = written(tmp_path / ".env", "A=1\n")
    env.chmod(0o644)
    assert run(infrahub, env) == 0
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    env.chmod(0o640)
    assert run(infrahub, env) == 0, "the accepted path too"
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert f"{env} was mode 0640: set to 0600" in told(capsys)[0]


def test_an_accepted_line_whose_group_lacks_the_role_mends_the_group_alone(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A group without the role, or without the account, leaves a valid token reading nothing, so the accepted path
    reads the group too and makes it again where it differs (P5-40)."""
    infrahub = Infrahub()
    env = written(tmp_path / ".env", "A=1\n")
    assert run(infrahub, env) == 0
    infrahub.groups["fylgja-orchestrator"]["roles"] = []
    before = env.read_bytes()
    infrahub.mutations.clear()
    capsys.readouterr()
    assert run(infrahub, env) == 0
    same = env.read_bytes() == before
    assert same, "the file changed"
    assert infrahub.mutations == ["CoreAccountGroupDelete", "CoreAccountGroupCreate"]
    [group] = infrahub.groups.values()
    role, member = infrahub.roles["fylgja-orchestrator"]["id"], infrahub.accounts["fylgja-orchestrator"]["id"]
    assert (group["roles"], group["members"]) == ([role], [member])
    said = told(capsys)[0]
    assert "made the group fylgja-orchestrator" in said
    assert f"{LINE} in {env} is accepted" in said
