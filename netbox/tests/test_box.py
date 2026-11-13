"""`netbox/seed/box.py`: the one transport everything that seeds the development NetBox goes through.

NetBox is `httpx.MockTransport` and the clock a fake: nothing here opens a socket or starts a process. The tokens are
values of the tests' own.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

import box
import httpx
import pytest
from box import Box, BoxError, branch_named, branched, query

HOST = "netbox.example"
ADDRESS = f"http://{HOST}"
TOKEN = "nbt_k.t"
SECRET = "nbt_abcdefghijkl.s3cr3ts3cr3t"
"""A token of NetBox's v2 shape, `nbt_<key>.<token>`, that no sentence `box.py` writes may hold a half of."""
HALVES = ("abcdefghijkl", "s3cr3ts3cr3t")
BRANCHES = "/api/plugins/branching/branches/"


def holds_part(text: str) -> bool:
    """Whether `text` holds any five characters in a row of either half of `SECRET`."""
    return any(half[at : at + 5] in text for half in HALVES for at in range(len(half) - 4))


SITE = {"name": "lab", "slug": "lab"}

Handler = Callable[[httpx.Request], httpx.Response]


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


def over(handler: Handler, token: str = TOKEN) -> tuple[Box, list[httpx.Request]]:
    """A `Box` over `handler`, and every request it was sent, in order."""
    seen: list[httpx.Request] = []

    def keep(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return Box(ADDRESS, token, transport=httpx.MockTransport(keep)), seen


def page(rows: list[dict[str, Any]], count: int | None = None, more: bool = False) -> httpx.Response:
    """One page of a REST list, as NetBox answers it: `count`, `next`, `previous` and `results`."""
    following = f"{ADDRESS}/api/next/" if more else None
    total = len(rows) if count is None else count
    return httpx.Response(200, json={"count": total, "next": following, "previous": None, "results": rows})


def sent(request: httpx.Request) -> object:
    return json.loads(request.content) if request.content else None


def test_a_request_is_under_api_with_the_bearer_and_the_branchs_header() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE" or request.url.path == "/api/extras/empty/":
            return httpx.Response(204)
        return httpx.Response(200 if request.method != "POST" else 201, json={"id": 7, "name": "n1"})

    made, seen = over(handler)
    assert made.get("dcim/devices/", name="n1") == {"id": 7, "name": "n1"}
    assert made.get("dcim/devices/", branch="p9d46y7z", name="n1") == {"id": 7, "name": "n1"}
    assert made.post("dcim/sites/", SITE, branch="p9d46y7z") == {"id": 7, "name": "n1"}
    assert made.patch("dcim/sites/7/", {"description": "x"}, branch="p9d46y7z") == {"id": 7, "name": "n1"}
    made.delete("dcim/sites/7/", branch="p9d46y7z")
    assert made.get("extras/empty/") is None
    plain, under, posted, patched, deleted, _ = seen

    for request in seen:
        assert request.url.host == HOST
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"
        assert request.headers["Accept"] == "application/json"
    assert plain.method == "GET"
    assert plain.url.path == "/api/dcim/devices/"
    assert str(plain.url.query, "ascii") == "name=n1"
    assert "X-NetBox-Branch" not in plain.headers
    for request in (under, posted, patched, deleted):
        assert request.headers["X-NetBox-Branch"] == "p9d46y7z"
    assert (posted.method, posted.url.path, sent(posted)) == ("POST", "/api/dcim/sites/", SITE)
    assert (patched.method, patched.url.path, sent(patched)) == ("PATCH", "/api/dcim/sites/7/", {"description": "x"})
    assert (deleted.method, deleted.url.path, sent(deleted)) == ("DELETE", "/api/dcim/sites/7/", None)


def test_a_box_is_made_with_no_request_and_names_no_token() -> None:
    made, seen = over(lambda request: httpx.Response(200), SECRET)
    assert seen == []
    assert not holds_part(repr(made))
    made.close()


DEVICES = [{"id": 1, "name": "n1"}, {"id": 2, "name": "n2"}, {"id": 3, "name": "n3"}]


def test_listed_reads_every_page_and_is_held_to_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(box, "PAGE", 2)

    def whole(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params["offset"])
        rows = DEVICES[offset : offset + int(request.url.params["limit"])]
        return page(rows, 3, more=offset + len(rows) < 3)

    made, seen = over(whole)
    assert made.listed("dcim/devices/", tag="fylgja") == DEVICES
    assert [dict(request.url.params) for request in seen] == [
        {"tag": "fylgja", "limit": "2", "offset": "0"},
        {"tag": "fylgja", "limit": "2", "offset": "2"},
    ]

    def short(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params["offset"])
        return page(DEVICES[:2] if offset == 0 else [], 3, more=offset == 0)

    made, _ = over(short)
    with pytest.raises(BoxError) as raised:
        made.listed("dcim/devices/")
    assert "/api/dcim/devices/" in str(raised.value)
    assert "2" in str(raised.value) and "3" in str(raised.value)

    counts: Iterator[int] = iter([3, 4])

    def moving(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params["offset"])
        return page(DEVICES[offset : offset + 2], next(counts), more=True)

    made, _ = over(moving)
    with pytest.raises(BoxError) as raised:
        made.listed("dcim/devices/")
    assert "/api/dcim/devices/" in str(raised.value)
    assert "3" in str(raised.value) and "4" in str(raised.value)


@pytest.mark.parametrize(("rows", "found"), [([], None), (DEVICES[:1], DEVICES[0])], ids=["none", "one"])
def test_one_is_none_one_or_refused(rows: list[dict[str, Any]], found: dict[str, Any] | None) -> None:
    made, seen = over(lambda request: page(rows))
    assert made.one("dcim/devices/", name="n1") == found
    [request] = seen
    assert request.url.params["name"] == "n1"

    made, _ = over(lambda request: page(DEVICES[:2]))
    with pytest.raises(BoxError) as raised:
        made.one("dcim/devices/", name="n1")
    assert "name=n1" in str(raised.value)
    assert "2" in str(raised.value)


def test_ensure_finds_before_it_makes_and_records_which() -> None:
    made, seen = over(lambda request: page([{"id": 4, **SITE}]))
    assert made.ensure("dcim/sites/", {"name": "lab"}, SITE) == {"id": 4, **SITE}
    assert [request.method for request in seen] == ["GET"]
    assert made.ensured == [("found", "dcim/sites/", 4)]

    def empty(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json={"id": 5, **SITE})
        return page([])

    made, seen = over(empty)
    assert made.ensure("dcim/sites/", {"name": "lab"}, SITE, branch="p9d46y7z") == {"id": 5, **SITE}
    assert [request.method for request in seen] == ["GET", "POST"]
    assert [request.headers["X-NetBox-Branch"] for request in seen] == ["p9d46y7z", "p9d46y7z"]
    assert sent(seen[1]) == SITE
    assert made.ensured == [("made", "dcim/sites/", 5)]

    made, seen = over(lambda request: page([{"id": 4, **SITE}, {"id": 6, **SITE}]))
    with pytest.raises(BoxError):
        made.ensure("dcim/sites/", {"name": "lab"}, SITE)
    assert [request.method for request in seen] == ["GET"]
    assert made.ensured == []


def answered(status: int, **content: Any) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, **content)

    return handler


def unreachable(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("[Errno 111] Connection refused", request=request)


@pytest.mark.parametrize(
    ("handler", "status", "words"),
    [
        (answered(403, json={"detail": "Invalid v2 token"}), 403, ["HTTP 403", "Invalid v2 token"]),
        (answered(400, json={"token": [f"{SECRET} is not a valid key"]}), 400, ["HTTP 400", "is not a valid key"]),
        (answered(400, text="x" * 290 + SECRET + " and the rest"), 400, ["HTTP 400", "x" * 200]),
        (answered(500, text="Internal Server Error"), 500, ["HTTP 500", "Internal Server Error"]),
        (unreachable, None, ["ConnectError", "Connection refused"]),
    ],
    ids=["403-dead-token", "400-echoes-it", "400-across-the-cut", "500-text", "connect-error"],
)
def test_no_failure_holds_the_token(handler: Handler, status: int | None, words: list[str]) -> None:
    """None is chained to an httpx exception: one carries its request, whose headers hold the token."""
    made, _ = over(handler, SECRET)
    with pytest.raises(BoxError) as raised:
        made.get("dcim/devices/", name="n1")
    error = raised.value
    assert error.status == status
    for text in (str(error), repr(error), repr(error.__cause__), repr(error.__context__)):
        assert not holds_part(text)
    assert error.__cause__ is None
    assert error.__context__ is None
    sentence = str(error)
    assert "\n" not in sentence
    assert sentence.startswith("GET /api/dcim/devices/ ")
    assert [word for word in words if word not in sentence] == []
    assert len(sentence) < 400


def test_a_value_handed_to_hide_is_replaced_before_the_cut() -> None:
    """A secret a request carries, echoed across the 300th character of NetBox's words (here the second's half, at
    296 to 311), is replaced whole, as the token is; each half of one of the v2 shape too, and a part shorter than
    `HALF` is left."""
    password = "p4ssw0rd-0f-the-test5-0wn"
    other = "nbt_mnopqrstuvwx.0th3r0th3r0th3r"
    made, _ = over(answered(400, text="x" * 270 + password + " " + other.split(".")[1] + " short"), SECRET)
    made.hide(password, other, "short")
    with pytest.raises(BoxError) as raised:
        made.post("users/users/", {"username": "u", "password": password})
    sentence = str(raised.value)
    assert sentence.endswith("x" * 10 + box.HIDDEN + " " + box.HIDDEN + " short")
    for value in (password, "0th3r0th3r0th3r"):
        assert [value[at : at + 5] for at in range(len(value) - 4) if value[at : at + 5] in sentence] == []


def test_a_secret_is_replaced_as_json_writes_it_too() -> None:
    """A refusal with no `detail` is NetBox's body as `json.dumps` writes it, which escapes a quote, a backslash and a
    character outside ASCII: a secret handed to `hide` is replaced in that form as well as its own."""
    secret = 'pa"ss\\w\u00f6rd-0f-the-test5-0wn'
    made, _ = over(answered(400, json={"password": [f"{secret} is not allowed"]}), SECRET)
    made.hide(secret)
    with pytest.raises(BoxError) as raised:
        made.post("users/users/", {"username": "u", "password": secret})
    sentence = str(raised.value)
    assert box.HIDDEN in sentence and "is not allowed" in sentence
    for form in (secret, json.dumps(secret)[1:-1]):
        assert [form[at : at + 5] for at in range(len(form) - 4) if form[at : at + 5] in sentence] == []


@pytest.mark.parametrize("location", [f"{ADDRESS}/api/dcim/cables/5/", None], ids=["to a path", "to nowhere"])
def test_a_redirect_is_no_success(location: str | None) -> None:
    """httpx follows no redirect, so a 301, as Django answers a path without its trailing slash, would be a `DELETE`
    or a `POST` that did nothing and said nothing: it is a `BoxError` of its status, naming the `Location`'s path
    where it has one and never its host."""
    headers = {"Location": location} if location is not None else {}
    made, seen = over(lambda request: httpx.Response(301, headers=headers))
    with pytest.raises(BoxError) as deleted:
        made.delete("dcim/cables/5")
    with pytest.raises(BoxError) as posted:
        made.post("extras/webhooks", {"name": "w"})
    assert [request.method for request in seen] == ["DELETE", "POST"]
    went = "a redirect to /api/dcim/cables/5/" if location is not None else "a redirect with no Location"
    for raised, asked in ((deleted, "DELETE /api/dcim/cables/5"), (posted, "POST /api/extras/webhooks")):
        assert raised.value.status == 301
        assert str(raised.value) == f"{asked} answered HTTP 301: {went}"
        assert HOST not in str(raised.value)


def test_a_token_a_header_cannot_carry_is_refused_naming_no_part_of_it() -> None:
    for token in (SECRET + "\n", SECRET + " ", SECRET.replace("s3", "sé")):
        with pytest.raises(BoxError) as raised:
            over(lambda request: httpx.Response(200), token)
        assert raised.value.status is None
        assert not holds_part(repr(raised.value))


def branch(status: str, *, id: int = 9, name: str = "fylgja-contract-0a1b2c3d") -> dict[str, Any]:
    return {"id": id, "name": name, "schema_id": "p9d46y7z", "status": {"value": status, "label": status.title()}}


def test_branched_makes_the_branch_once_and_waits_for_ready() -> None:
    name = "fylgja-contract-0a1b2c3d"
    readings = iter(["provisioning", "ready"])

    def making(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json=branch("new"))
        if request.url.path == BRANCHES:
            return page([])
        return httpx.Response(200, json=branch(next(readings)))

    made, seen = over(making)
    clock = Clock()
    assert branched(made, name, clock=clock, sleep=clock.sleep) == branch("ready")
    assert [(request.method, request.url.path) for request in seen] == [
        ("GET", BRANCHES),
        ("POST", BRANCHES),
        ("GET", f"{BRANCHES}9/"),
        ("GET", f"{BRANCHES}9/"),
    ]
    assert seen[0].url.params["name"] == name
    assert sent(seen[1]) == {"name": name}
    assert clock.slept == [1.0, 1.0]

    made, seen = over(lambda request: page([branch("ready")]))
    clock = Clock()
    assert branched(made, name, clock=clock, sleep=clock.sleep) == branch("ready")
    assert [request.method for request in seen] == ["GET"]
    assert clock.slept == []

    made, _ = over(lambda request: page([branch("failed")]))
    clock = Clock()
    with pytest.raises(BoxError) as raised:
        branched(made, name, clock=clock, sleep=clock.sleep)
    assert name in str(raised.value) and "failed" in str(raised.value)
    assert clock.slept == []

    def never(request: httpx.Request) -> httpx.Response:
        if request.url.path == BRANCHES:
            return page([branch("new")])
        return httpx.Response(200, json=branch("provisioning"))

    made, _ = over(never)
    clock = Clock()
    with pytest.raises(BoxError) as raised:
        branched(made, name, clock=clock, sleep=clock.sleep)
    assert name in str(raised.value) and "provisioning" in str(raised.value) and "120 s" in str(raised.value)
    assert clock.now >= 120
    assert sum(clock.slept) <= 120


def test_a_branch_answered_for_another_name_is_refused_naming_both() -> None:
    """`?name=` answered the branch of that name alone on the instance (design/verified-facts.md); were it to answer
    another, the seed would wait for, write to or delete a branch it never asked for."""
    name = "fylgja-contract-0a1b2c3d"
    made, seen = over(lambda request: page([branch("ready", name="third-link")]))
    with pytest.raises(BoxError) as raised:
        branch_named(made, name)
    assert name in str(raised.value) and "third-link" in str(raised.value)
    clock = Clock()
    with pytest.raises(BoxError):
        branched(made, name, clock=clock, sleep=clock.sleep)
    assert [request.method for request in seen] == ["GET", "GET"]

    made, _ = over(lambda request: page([branch("ready", name=name)]))
    assert branch_named(made, name) == branch("ready", name=name)
    made, _ = over(lambda request: page([]))
    assert branch_named(made, name) is None


def test_the_client_is_given_the_request_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """httpx's own default of 5 s is named nowhere in the tree; the seed's is `TIMEOUT_S`."""
    made: list[dict[str, Any]] = []
    real = httpx.Client

    def client(**kwargs: Any) -> httpx.Client:
        made.append(kwargs)
        return real(transport=httpx.MockTransport(lambda request: httpx.Response(200)))

    monkeypatch.setattr(httpx, "Client", client)
    Box(ADDRESS, TOKEN)
    [kwargs] = made
    assert box.TIMEOUT_S == 30.0
    assert kwargs["timeout"] == box.TIMEOUT_S
    assert kwargs["trust_env"] is False


def test_a_query_is_netboxs_text_and_none_is_refused_before_any_request() -> None:
    assert list(query({"enabled": True, "mgmt_only": False, "id": [1, "2"], "limit": 3}).multi_items()) == [
        ("enabled", "true"),
        ("mgmt_only", "false"),
        ("id", "1"),
        ("id", "2"),
        ("limit", "3"),
    ]
    for params in ({"name": None}, {"name": ["n1", None]}):
        with pytest.raises(ValueError, match="name"):
            query(params)
    made, seen = over(lambda request: page([]))
    with pytest.raises(ValueError, match="name"):
        made.get("dcim/devices/", name=None)
    assert seen == []
