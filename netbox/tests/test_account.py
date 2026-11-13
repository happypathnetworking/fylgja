"""`netbox/seed/account.py`: the reader's and the example's NetBox accounts, `fylgja-reader` and
`fylgja-orchestrator`, their grants, and their tokens' lines in `local/.env`, each checked before it is trusted.

NetBox is `fake.FakeNetBox`, an `httpx.MockTransport` handler, and `local/.env` a file under `tmp_path`: nothing here
opens a socket or starts a process. The tokens are values of the tests' own and the fake's. No value of a token or a
password is compared inside an assert, whose message would print it: each is compared first and the assert given the
answer alone (as `infrahub/tests/test_account.py` does).
"""

from __future__ import annotations

import json
import secrets
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

import account
import httpx
import pytest
import seed
from account import GRANTS, LINES, ORCHESTRATOR, READER, Grant
from box import ADDRESS as ADDRESS_NAME
from box import TOKEN as TOKEN_NAME
from box import WORDS, Box, BoxError
from fake import ADDRESS, FakeNetBox

SECRET = "nbt_abcdefghijkl.s3cr3ts3cr3ts3cr3t"
"""The superuser's token, of NetBox's v2 shape, `nbt_<key>.<token>`, that nothing printed or raised may hold a part
of."""
HALVES = ("abcdefghijkl", "s3cr3ts3cr3ts3cr3t")

OTHER = f"# the developer's own\nexport FYLGJA_NETBOX_ADDRESS={ADDRESS}\nFYLGJA_ELSE='kept' # a note\n".encode()
"""Three lines of `local/.env` that are none of the accounts': each is kept byte for byte."""

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

TOKENS = "users/tokens/"
PERMISSIONS = "users/permissions/"
USERS = "users/users/"

FIRST = [
    USERS,
    PERMISSIONS,
    PERMISSIONS,
    TOKENS,
    USERS,
    PERMISSIONS,
    PERMISSIONS,
    PERMISSIONS,
    PERMISSIONS,
    TOKENS,
]
"""The creates of a first run over an empty NetBox: each account's user, its grants and its token, the reader's
first."""

Handler = Callable[[httpx.Request], httpx.Response]


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


def user_id(fake: FakeNetBox, name: str) -> int:
    found: int = fake.held(USERS, username=name)["id"]
    return found


def presented(row: dict[str, Any]) -> str:
    """A token row of the fake's, as `local/.env` holds it."""
    return f"nbt_{row['key']}.{row['token']}"


def tokens_of(fake: FakeNetBox, name: str) -> list[str]:
    """Each token the fake holds of the account `name`, as presented, in the order made."""
    number = user_id(fake, name)
    return [presented(row) for row in fake.objects.get(TOKENS, {}).values() if row["user"] == number]


def passwords(fake: FakeNetBox) -> list[str]:
    return [str(body["password"]) for path, body in fake.sent("POST") if path == USERS and body.get("password")]


def seeded(tmp_path: Path) -> tuple[FakeNetBox, Path]:
    """A fake and a file over which a first run has made everything, the fake's requests forgotten."""
    fake = FakeNetBox()
    env = env_file(tmp_path)
    account.ensure(env, over(fake))
    fake.requests.clear()
    return fake, env


def holds_part(text: str, *values: str) -> bool:
    """Whether `text` holds any eight characters in a row of a half of `SECRET` or of `values`, or of a half of a
    value `nbt_<key>.<token>`."""
    held = [*HALVES]
    for value in values:
        held += [value, *value.removeprefix("nbt_").split(".")]
    return any(part[at : at + 8] in text for part in held for at in range(max(len(part) - 7, 1)))


def test_the_accounts_their_lines_and_their_grants_are_the_table() -> None:
    assert LINES == {READER: "FYLGJA_NETBOX_TOKEN", ORCHESTRATOR: "FYLGJA_ORCHESTRATOR_NETBOX_TOKEN"}
    assert (READER, ORCHESTRATOR) == ("fylgja-reader", "fylgja-orchestrator")
    assert list(GRANTS) == [READER, ORCHESTRATOR]
    assert GRANTS[READER] == (
        Grant("fylgja-reader", READS, ("view",)),
        Grant("fylgja-reader-render", ("dcim.device",), ("view", "render_config")),
    )
    assert GRANTS[ORCHESTRATOR] == (
        Grant("fylgja-orchestrator", READS, ("view",)),
        Grant("fylgja-orchestrator-render", ("dcim.device",), ("view", "render_config")),
        Grant("fylgja-orchestrator-journal", ("extras.journalentry",), ("view", "add")),
        Grant("fylgja-orchestrator-branch", ("netbox_branching.branch",), ("view", "change")),
    )
    every = [grant for grants in GRANTS.values() for grant in grants]
    assert all("delete" not in grant.actions for grant in every)
    assert all(not {"add", "change"} & set(grant.actions) for grant in GRANTS[READER])
    assert len({grant.name for grant in every}) == len(every)
    assert all(grant.name.startswith(name) for name, grants in GRANTS.items() for grant in grants)

    def rows(grants: tuple[Grant, ...]) -> set[tuple[frozenset[str], frozenset[str]]]:
        return {(frozenset(grant.object_types), frozenset(grant.actions)) for grant in grants}

    assert rows(GRANTS[READER]) <= rows(GRANTS[ORCHESTRATOR])


def test_the_fake_answers_users_permissions_and_tokens_as_netbox_does() -> None:
    """The rules the fake keeps of users, permissions and tokens (design/verified-facts.md, "NetBox 4.7.5 with
    netbox-branching 1.2.3"): a user made only with a password and answered with none; a token's secret answered by
    its create alone; a permission's `users` and a token's `user` as rows; `is_superuser` a filter."""
    fake = FakeNetBox()
    box = over(fake)
    with pytest.raises(BoxError) as refused:
        box.post(USERS, {"username": "u"})
    assert refused.value.status == 400
    made = box.post(USERS, {"username": "u", "password": "p4ssw0rd-p4ssw0rd", "is_active": True})
    assert "password" not in made and "is_superuser" not in made and made["is_active"] is True
    fake.add(USERS, {"username": "admin", "password": "x", "is_superuser": True})
    assert [row["username"] for row in box.listed(USERS, is_superuser=True)] == ["admin"]
    assert [row["username"] for row in box.listed(USERS, username="u", is_superuser=False)] == ["u"]

    token = box.post(TOKENS, {"user": made["id"]})
    assert len(token["key"]) == 12 and len(token["token"]) == 40
    assert token["user"] == {"id": made["id"], "username": "u"}
    [listed] = box.listed(TOKENS, key=token["key"])
    assert listed["token"] is None and listed["user"]["username"] == "u"
    assert box.listed(TOKENS, user_id=made["id"]) == [listed]
    assert box.listed(TOKENS, key="000000000000") == []

    grant = box.post(PERMISSIONS, {"name": "g", "object_types": ["dcim.device"], "actions": ["view"], "users": [1]})
    assert grant["users"] == [{"id": made["id"], "username": "u"}]
    assert box.one(PERMISSIONS, name="g") == grant
    group = fake.add("users/groups/", {"name": "a-group"})
    fake.held(USERS, username="u")["groups"] = [group["id"]]
    [row] = box.listed(USERS, username="u")
    assert row["groups"] == [{"id": group["id"], "name": "a-group"}]
    assert row["permissions"] == [{"id": grant["id"], "name": "g"}]


def test_a_first_run_makes_each_account_its_grants_and_its_token_and_writes_two_lines(tmp_path: Path) -> None:
    fake = FakeNetBox()
    env = env_file(tmp_path)
    env.chmod(0o644)
    made = account.ensure(env, over(fake))

    posted = fake.sent("POST")
    assert [path for path, _ in posted] == FIRST
    assert fake.sent("PATCH") == [] and fake.sent("DELETE") == []
    reader, orchestrator = user_id(fake, READER), user_id(fake, ORCHESTRATOR)
    users = [body for path, body in posted if path == USERS]
    assert [{k: v for k, v in body.items() if k != "password"} for body in users] == [
        {"username": READER, "is_active": True},
        {"username": ORCHESTRATOR, "is_active": True},
    ]
    sent = passwords(fake)
    assert len(sent) == 2 and len(set(sent)) == 2 and all(len(password) >= 32 for password in sent)
    assert [body for path, body in posted if path == PERMISSIONS] == [
        {"name": grant.name, "object_types": list(grant.object_types), "actions": list(grant.actions), "users": [who]}
        for name, who in ((READER, reader), (ORCHESTRATOR, orchestrator))
        for grant in GRANTS[name]
    ]
    assert [body for path, body in posted if path == TOKENS] == [{"user": reader}, {"user": orchestrator}]

    data = env.read_bytes()
    assert data.startswith(OTHER)
    [reads], [writes] = tokens_of(fake, READER), tokens_of(fake, ORCHESTRATOR)
    same = data[len(OTHER) :] == f"FYLGJA_NETBOX_TOKEN={reads}\nFYLGJA_ORCHESTRATOR_NETBOX_TOKEN={writes}\n".encode()
    assert same
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert made == [
        "made the user fylgja-reader",
        "made the permission fylgja-reader",
        "made the permission fylgja-reader-render",
        "made a token of fylgja-reader",
        "made the user fylgja-orchestrator",
        "made the permission fylgja-orchestrator",
        "made the permission fylgja-orchestrator-render",
        "made the permission fylgja-orchestrator-journal",
        "made the permission fylgja-orchestrator-branch",
        "made a token of fylgja-orchestrator",
        "appended FYLGJA_NETBOX_TOKEN",
        "appended FYLGJA_ORCHESTRATOR_NETBOX_TOKEN",
    ]
    assert list(tmp_path.iterdir()) == [env]


def test_a_line_netbox_still_takes_is_kept_byte_for_byte(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fake, env = seeded(tmp_path)
    before = env.read_bytes()
    assert account.ensure(env, over(fake)) == []
    assert fake.writes() == []
    assert env.read_bytes() == before

    fake.requests.clear()
    capsys.readouterr()
    code, out, err = run(fake, env, capsys)
    assert (code, err) == (0, "")
    assert out == "account: every account, grant and token line is as it should be; nothing written\n"
    assert fake.writes() == []
    assert env.read_bytes() == before


def lines_of(env: Path) -> list[bytes]:
    return env.read_bytes().splitlines(keepends=True)


@pytest.mark.parametrize("case", ["gone", "not a token", "the other account's", "held twice"])
def test_a_dead_line_and_another_accounts_are_replaced_and_every_other_line_kept(case: str, tmp_path: Path) -> None:
    fake, env = seeded(tmp_path)
    [reads], [writes] = tokens_of(fake, READER), tokens_of(fake, ORCHESTRATOR)
    other = OTHER.splitlines(keepends=True)
    held = f"FYLGJA_NETBOX_TOKEN={reads}\n".encode()
    if case == "gone":
        [row] = [row for row in fake.objects[TOKENS].values() if presented(row) == reads]
        del fake.objects[TOKENS][row["id"]]
    elif case == "not a token":
        held = b"FYLGJA_NETBOX_TOKEN=not-a-token\n"
    elif case == "the other account's":
        held = f"FYLGJA_NETBOX_TOKEN={writes}\n".encode()
    before = [other[0], held, other[1], f"FYLGJA_ORCHESTRATOR_NETBOX_TOKEN={writes}\n".encode(), other[2]]
    at = 1
    if case == "held twice":
        before += [b"FYLGJA_NETBOX_TOKEN=nbt_000000000000.dead # and the last\n"]
        at = 5
    env.write_bytes(b"".join(before))

    made = account.ensure(env, over(fake))
    assert fake.sent("POST") == [(TOKENS, {"user": user_id(fake, READER)})]
    assert fake.sent("PATCH") == [] and fake.sent("DELETE") == []
    new = tokens_of(fake, READER)[-1]
    after = lines_of(env)
    expected = [*before[:at], f"FYLGJA_NETBOX_TOKEN={new}\n".encode(), *before[at + 1 :]]
    same = after == expected
    assert same
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert made == ["made a token of fylgja-reader", "replaced FYLGJA_NETBOX_TOKEN"]


@pytest.mark.parametrize(
    "case", ["delete among its actions", "dcim.site among its types", "a second user", "its types in another order"]
)
def test_a_grant_is_brought_to_exactly_its_row(case: str, tmp_path: Path) -> None:
    fake, env = seeded(tmp_path)
    grant = fake.held(PERMISSIONS, name="fylgja-reader")
    reader = user_id(fake, READER)
    if case == "delete among its actions":
        grant["actions"] = [*grant["actions"], "delete"]
    elif case == "dcim.site among its types":
        grant["object_types"] = [*grant["object_types"], "dcim.site"]
    elif case == "a second user":
        grant["users"] = [reader, user_id(fake, ORCHESTRATOR)]
    else:
        grant["object_types"] = list(reversed(grant["object_types"]))
    before = env.read_bytes()

    made = account.ensure(env, over(fake))
    assert fake.sent("POST") == [] and fake.sent("DELETE") == []
    assert env.read_bytes() == before
    [row] = [each for each in GRANTS[READER] if each.name == "fylgja-reader"]
    if case == "its types in another order":
        assert fake.sent("PATCH") == []
        assert made == []
        return
    body = {"object_types": list(row.object_types), "actions": list(row.actions), "users": [reader]}
    assert fake.sent("PATCH") == [(f"{PERMISSIONS}{grant['id']}/", body)]
    assert made == ["brought the permission fylgja-reader to its row"]
    kept = fake.held(PERMISSIONS, name="fylgja-reader")
    assert {name: kept[name] for name in body} == body


def test_a_found_user_is_set_active_and_a_superuser_is_refused(tmp_path: Path) -> None:
    fake, env = seeded(tmp_path)
    before = env.read_bytes()
    fake.held(USERS, username=READER)["is_active"] = False
    assert account.ensure(env, over(fake)) == ["set the user fylgja-reader active"]
    assert fake.sent("PATCH") == [(f"{USERS}{user_id(fake, READER)}/", {"is_active": True})]

    fake.requests.clear()
    fake.held(USERS, username=ORCHESTRATOR)["is_superuser"] = True
    with pytest.raises(BoxError, match=r"fylgja-orchestrator is a superuser.*make netbox-down PURGE=1"):
        account.ensure(env, over(fake))
    assert fake.writes() == []
    assert env.read_bytes() == before


def failing(fake: FakeNetBox, at: int) -> Handler:
    """`fake`, but for its request numbered `at`, counted from 1, which is never answered."""
    count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        if count == at:
            raise httpx.ConnectError("connection refused", request=request)
        return fake(request)

    return handler


def prepared(tmp_path: Path, replacing: bool) -> tuple[FakeNetBox, Path]:
    """A fake and a file for a first run, or for a run that replaces the reader's line, its token gone."""
    if not replacing:
        return FakeNetBox(), env_file(tmp_path)
    fake, env = seeded(tmp_path)
    [row] = [row for row in fake.objects[TOKENS].values() if row["user"] == user_id(fake, READER)]
    del fake.objects[TOKENS][row["id"]]
    return fake, env


@pytest.mark.parametrize("replacing", [False, True], ids=["a first run", "a run that replaces a line"])
def test_netbox_not_answering_leaves_the_file_as_it_was(
    replacing: bool, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Each request of the run, in turn, is not answered."""
    fake, env = prepared(tmp_path, replacing)
    account.ensure(env, over(fake))
    total = len(fake.requests)
    assert total > len(FIRST)
    for at in range(1, total + 1):
        fake, env = prepared(tmp_path, replacing)
        before = env.read_bytes()
        code, _, err = run(failing(fake, at), env, capsys)
        assert code == 1, at
        assert "was not answered" in err, at
        assert env.read_bytes() == before, at
        assert list(tmp_path.iterdir()) == [env], at


def test_nothing_printed_or_raised_holds_a_token_or_the_password(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeNetBox()
    code, out, err = run(fake, env_file(tmp_path), capsys)
    assert (code, err) == (0, "")
    answered = [presented(row) for row in fake.objects[TOKENS].values()]
    assert len(answered) == 2
    assert not holds_part(out, *answered, *passwords(fake))

    counted = FakeNetBox()
    account.ensure(env_file(tmp_path), over(counted))
    creates = [number for number, request in enumerate(counted.requests, 1) if request.method == "POST"]
    second = [at for at in creates if counted.requests[at - 1].url.path == f"/api/{TOKENS}"][-1]

    fake = FakeNetBox()
    fake.refused[second] = 403
    env = env_file(tmp_path)
    code, out, err = run(fake, env, capsys)
    assert code == 1 and "HTTP 403" in err
    answered = [presented(row) for row in fake.objects[TOKENS].values()]
    assert len(answered) == 1
    assert not holds_part(out + err, *answered, *passwords(fake))
    assert env.read_bytes() == OTHER

    fake = FakeNetBox()
    fake.refused[second] = 403
    with pytest.raises(BoxError) as raised:
        account.ensure(env_file(tmp_path), over(fake))
    assert raised.value.status == 403
    answered = [presented(row) for row in fake.objects[TOKENS].values()]
    assert not holds_part(f"{raised.value} {raised.value!r}", *answered, *passwords(fake))

    seen: list[httpx.Request] = []
    behind = FakeNetBox()

    def echoing(request: httpx.Request) -> httpx.Response:
        """NetBox refusing a user's create with a body that echoes the request's, its password among it."""
        seen.append(request)
        if request.method == "POST" and request.url.path == f"/api/{USERS}":
            return httpx.Response(400, json={"password": [json.loads(request.content)["password"]]})
        return behind(request)

    def sent() -> list[str]:
        return [
            json.loads(request.content)["password"]
            for request in seen
            if request.method == "POST" and request.url.path == f"/api/{USERS}"
        ]

    code, out, err = run(echoing, env_file(tmp_path), capsys)
    assert code == 1 and "HTTP 400" in err
    assert len(sent()) == 1
    assert not holds_part(out + err, *sent())
    with pytest.raises(BoxError) as raised:
        account.ensure(env_file(tmp_path), over(echoing))
    assert len(sent()) == 2
    assert not holds_part(f"{raised.value} {raised.value!r}", *sent())


def test_a_variable_not_set_or_a_file_not_there_is_exit_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeNetBox()
    env = env_file(tmp_path)
    assert account.main([], transport=httpx.MockTransport(fake)) == 2
    assert account.main(["--env", str(env), "--other"], transport=httpx.MockTransport(fake)) == 2
    capsys.readouterr()

    code, out, err = run(fake, tmp_path / "absent", capsys)
    assert code == 2 and out == ""
    assert str(tmp_path / "absent") in err and "make netbox-up" in err
    assert not (tmp_path / "absent").exists()

    for name in (ADDRESS_NAME, TOKEN_NAME):
        with monkeypatch.context() as patched:
            patched.delenv(name)
            code, out, err = run(fake, env, capsys)
        assert code == 2 and out == ""
        assert name in err and "load local/.env" in err
    assert fake.requests == []
    assert env.read_bytes() == OTHER


def runs(text: str, *values: str) -> list[str]:
    """Each run of five characters of `values` that `text` holds."""
    return [value[at : at + 5] for value in values for at in range(len(value) - 4) if value[at : at + 5] in text]


@pytest.mark.parametrize("echoed", ["the password", "a line's key"])
def test_a_secret_echoed_across_the_cut_is_hidden_whole(
    echoed: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """NetBox's words are cut at `box.WORDS` characters: a secret that runs across the cut is hidden before it, so
    that no prefix of it is left. The password is sent in a user's create, and a line's key in the token lookup's
    query; a 400 that echoes either puts it across the 300th character."""
    key, half = secrets.token_hex(6), secrets.token_hex(20)
    line = f"nbt_{key}.{half}"
    sent: list[str] = []
    behind = FakeNetBox()

    def echoing(request: httpx.Request) -> httpx.Response:
        if echoed == "the password" and request.method == "POST" and request.url.path == f"/api/{USERS}":
            password = json.loads(request.content)["password"]
            sent.append(password)
            body = {"password": ["." * (WORDS - len('{"password": ["') - 20) + password]}
            assert json.dumps(body).index(password) < WORDS < json.dumps(body).index(password) + len(password)
            return httpx.Response(400, json=body)
        if echoed == "a line's key" and request.url.path == f"/api/{TOKENS}" and "key" in request.url.params:
            sent.append(request.url.params["key"])
            body = {"key": ["." * (WORDS - len('{"key": ["') - 6) + request.url.params["key"]]}
            return httpx.Response(400, json=body)
        return behind(request)

    data = OTHER + f"FYLGJA_NETBOX_TOKEN={line}\n".encode()
    code, out, err = run(echoing, env_file(tmp_path, data), capsys)
    assert code == 1 and "HTTP 400" in err
    with pytest.raises(BoxError) as raised:
        account.ensure(env_file(tmp_path, data), over(echoing))
    assert len(sent) == 2
    if echoed == "a line's key":
        assert sent == [key, key]
    error = raised.value
    texts = [out, err, str(error), repr(error), str(error.__cause__), str(error.__context__)]
    held = runs(" ".join(texts), *sent, half)
    assert held == []
    assert env_file(tmp_path, data).read_bytes() == data


@pytest.mark.parametrize("stray", ["a group", "a permission of another name"])
def test_an_account_holding_more_than_its_grants_is_refused_naming_each(
    stray: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Refused, exit 1, naming the stray and the purge; nothing is removed, no write is sent and the file is left as
    it was, its reader's line dead among it."""
    fake, env = seeded(tmp_path)
    reader = fake.held(USERS, username=READER)
    if stray == "a group":
        reader["groups"] = [fake.add("users/groups/", {"name": "a-stray-group"})["id"]]
        named = "the group a-stray-group"
    else:
        fake.add(PERMISSIONS, {"name": "a-stray-grant", "object_types": ["dcim.site"], "actions": ["add"],
                               "users": [reader["id"]]})
        named = "the permission a-stray-grant"
    [row] = [row for row in fake.objects[TOKENS].values() if row["user"] == reader["id"]]
    del fake.objects[TOKENS][row["id"]]
    before = env.read_bytes()

    capsys.readouterr()
    code, out, err = run(fake, env, capsys)
    assert code == 1 and out == ""
    assert f"fylgja-reader holds {named}" in err and "make netbox-down PURGE=1" in err
    with pytest.raises(BoxError, match=named):
        account.ensure(env, over(fake))
    assert fake.writes() == []
    assert env.read_bytes() == before


PURGE = "make netbox-down PURGE=1, then make netbox-up, then load local/.env again and run make netbox-seed"
"""The purge as the accounts say it, with `local/.env` loaded again before the seed: `make netbox-up` replaces the
write token's line after a purge."""


def another_users_token(fake: FakeNetBox) -> Handler:
    """`fake`, but a token's create answers the token as another user's."""

    def handler(request: httpx.Request) -> httpx.Response:
        response = fake(request)
        if request.method == "POST" and request.url.path == f"/api/{TOKENS}":
            body = json.loads(response.content)
            body["user"] = {**body["user"], "id": body["user"]["id"] + 1000}
            return httpx.Response(response.status_code, json=body)
        return response

    return handler


@pytest.mark.parametrize("kind", ["not answered", "401", "403", "500", "a stray", "another user's token"])
def test_the_remedy_is_said_for_what_failed(kind: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The purge only where NetBox holds what the run removes nothing of, a stray; `make netbox-up` where NetBox did
    not answer; `local/.env` loaded again where NetBox refused the write token, then `make netbox-up`, which provisions
    a refused token again, and the purge named only as what remains; and nothing where no remedy is known, a token
    NetBox answered as another user's among them."""
    if kind == "a stray":
        fake, env = seeded(tmp_path)
        fake.held(USERS, username=READER)["groups"] = [fake.add("users/groups/", {"name": "a-stray-group"})["id"]]
        handler: Handler = fake
    elif kind == "another user's token":
        fake, env = FakeNetBox(), env_file(tmp_path)
        handler = another_users_token(fake)
    else:
        fake, env = FakeNetBox(), env_file(tmp_path)
        handler = failing(fake, 1) if kind == "not answered" else fake
        if kind != "not answered":
            fake.refused[1] = int(kind)
    capsys.readouterr()
    code, out, err = run(handler, env, capsys)
    assert code == 1 and (out == "") is (kind != "another user's token")
    said = err.splitlines()
    if kind == "a stray":
        assert len(said) == 1 and said[0].endswith(f"nothing is removed: {PURGE}"), said
    elif kind == "not answered":
        assert said[-1].startswith("account: make netbox-up "), said
        assert "PURGE=1" not in err
    elif kind in ("401", "403"):
        assert said[-1].startswith("account: load local/.env again"), said
        assert said[-1].endswith(f"only where NetBox refuses it after that, {PURGE}"), said
        reload, up, purge = (said[-1].index(words) for words in ("load local/.env", "run make netbox-up", "PURGE=1"))
        assert reload < up < purge, said
        assert "provisions a refused token again without a purge" in said[-1], said
        assert err.count("PURGE=1") == 1
    else:
        assert len(said) == 1, said
        assert "PURGE=1" not in err and "make netbox-up" not in err and "local/.env" not in err
    if kind == "another user's token":
        assert "a token of another user" in said[0], said
        assert env.read_bytes() == OTHER


def test_the_accounts_remedies_are_the_seeds() -> None:
    """Each script runs alone and imports neither the other nor a module beside `box.py`, so each holds its own words
    for the remedies `make netbox-seed` prints; they are held equal here."""
    assert (account.PURGE, account.UP, account.RELOAD) == (seed.PURGE, seed.UP, seed.RELOAD)
