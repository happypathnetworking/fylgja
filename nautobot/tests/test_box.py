"""`nautobot/seed/box.py`: the one transport everything that seeds the development Nautobot goes through.

Nautobot is `httpx.MockTransport`: nothing here opens a socket or starts a process. The tokens are values of the tests'
own.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

import box
import httpx
import pytest
from box import Box, BoxError

HOST = "nautobot.example"
ADDRESS = f"http://{HOST}"
TOKEN = "t0k3n"
SECRET = "0123456789abcdef0123456789abcdef01234567"
"""A token of Nautobot's shape, forty hex digits, that no sentence `box.py` writes may hold a part of."""

SITE = {"name": "lab"}

Handler = Callable[[httpx.Request], httpx.Response]


def holds_part(text: str) -> bool:
    """Whether `text` holds any eight characters in a row of `SECRET`."""
    return any(SECRET[at : at + 8] in text for at in range(len(SECRET) - 7))


def over(handler: Handler, token: str = TOKEN) -> tuple[Box, list[httpx.Request]]:
    """A `Box` over `handler`, and every request it was sent, in order."""
    seen: list[httpx.Request] = []

    def keep(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return Box(ADDRESS, token, transport=httpx.MockTransport(keep)), seen


def page(rows: list[dict[str, Any]], count: int | None = None, more: bool = False) -> httpx.Response:
    """One page of a REST list, as Nautobot answers it: `count`, `next`, `previous` and `results`."""
    following = f"{ADDRESS}/api/next/" if more else None
    total = len(rows) if count is None else count
    return httpx.Response(200, json={"count": total, "next": following, "previous": None, "results": rows})


def sent(request: httpx.Request) -> object:
    return json.loads(request.content) if request.content else None


def test_a_request_is_under_api_with_the_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE" or request.url.path == "/api/extras/empty/":
            return httpx.Response(204)
        return httpx.Response(200 if request.method != "POST" else 201, json={"id": "u-1", "name": "n1"})

    made, seen = over(handler)
    assert made.get("dcim/devices/", name="n1") == {"id": "u-1", "name": "n1"}
    assert made.post("extras/tags/", SITE) == {"id": "u-1", "name": "n1"}
    assert made.patch("extras/tags/u-1/", {"description": "x"}) == {"id": "u-1", "name": "n1"}
    made.delete("extras/tags/u-1/")
    assert made.get("extras/empty/") is None
    plain, posted, patched, deleted, _ = seen

    for request in seen:
        assert request.url.host == HOST
        assert request.headers["Authorization"] == f"Token {TOKEN}"
        assert request.headers["Accept"] == "application/json"
    assert plain.method == "GET"
    assert plain.url.path == "/api/dcim/devices/"
    assert str(plain.url.query, "ascii") == "name=n1"
    assert (posted.method, posted.url.path, sent(posted)) == ("POST", "/api/extras/tags/", SITE)
    assert (patched.method, patched.url.path, sent(patched)) == ("PATCH", "/api/extras/tags/u-1/", {"description": "x"})
    assert (deleted.method, deleted.url.path, sent(deleted)) == ("DELETE", "/api/extras/tags/u-1/", None)


def test_a_box_is_made_with_no_request_and_names_no_token() -> None:
    made, seen = over(lambda request: httpx.Response(200), SECRET)
    assert seen == []
    assert not holds_part(repr(made))
    made.close()


DEVICES = [{"id": "a", "name": "n1"}, {"id": "b", "name": "n2"}, {"id": "c", "name": "n3"}]


def test_listed_reads_every_page_and_is_held_to_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(box, "PAGE", 2)

    def whole(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params["offset"])
        rows = DEVICES[offset : offset + int(request.url.params["limit"])]
        return page(rows, 3, more=offset + len(rows) < 3)

    made, seen = over(whole)
    assert made.listed("dcim/devices/", tags="fylgja") == DEVICES
    assert [dict(request.url.params) for request in seen] == [
        {"tags": "fylgja", "limit": "2", "offset": "0"},
        {"tags": "fylgja", "limit": "2", "offset": "2"},
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
    made, seen = over(lambda request: page([{"id": "u-4", **SITE}]))
    assert made.ensure("extras/tags/", {"name": "lab"}, SITE) == {"id": "u-4", **SITE}
    assert [request.method for request in seen] == ["GET"]
    assert made.ensured == [("found", "extras/tags/", "u-4")]

    def empty(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json={"id": "u-5", **SITE})
        return page([])

    made, seen = over(empty)
    assert made.ensure("extras/tags/", {"name": "lab"}, SITE) == {"id": "u-5", **SITE}
    assert [request.method for request in seen] == ["GET", "POST"]
    assert sent(seen[1]) == SITE
    assert made.ensured == [("made", "extras/tags/", "u-5")]

    made, seen = over(lambda request: page([{"id": "u-4", **SITE}, {"id": "u-6", **SITE}]))
    with pytest.raises(BoxError):
        made.ensure("extras/tags/", {"name": "lab"}, SITE)
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
        (answered(403, json={"detail": "Invalid token"}), 403, ["HTTP 403", "Invalid token"]),
        (answered(400, json={"name": [f"{SECRET} is not valid"]}), 400, ["HTTP 400", "is not valid"]),
        (answered(400, text="x" * 290 + SECRET + " and the rest"), 400, ["HTTP 400", "x" * 200]),
        (answered(500, text="Internal Server Error"), 500, ["HTTP 500", "Internal Server Error"]),
        (unreachable, None, ["ConnectError", "Connection refused"]),
    ],
    ids=["403-refused-token", "400-echoes-it", "400-across-the-cut", "500-text", "connect-error"],
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
    password = "p4ssw0rd-0f-the-test5-0wn"
    made, _ = over(answered(400, text="x" * 270 + password + " short"), SECRET)
    made.hide(password)
    with pytest.raises(BoxError) as raised:
        made.post("users/users/", {"username": "u", "password": password})
    sentence = str(raised.value)
    assert sentence.endswith("x" * 10 + box.HIDDEN + " short")
    assert [password[at : at + 5] for at in range(len(password) - 4) if password[at : at + 5] in sentence] == []


@pytest.mark.parametrize("location", [f"{ADDRESS}/api/dcim/cables/5/", None], ids=["to a path", "to nowhere"])
def test_a_redirect_is_no_success(location: str | None) -> None:
    headers = {"Location": location} if location is not None else {}
    made, _ = over(lambda request: httpx.Response(301, headers=headers))
    with pytest.raises(BoxError) as raised:
        made.delete("dcim/cables/5")
    went = "a redirect to /api/dcim/cables/5/" if location is not None else "a redirect with no Location"
    assert raised.value.status == 301
    assert str(raised.value) == f"DELETE /api/dcim/cables/5 answered HTTP 301: {went}"


def test_a_token_a_header_cannot_carry_is_refused_naming_no_part_of_it() -> None:
    for token in (SECRET + "\n", SECRET + " ", SECRET.replace("3", "é")):
        with pytest.raises(BoxError) as raised:
            over(lambda request: httpx.Response(200), token)
        assert raised.value.status is None
        assert not holds_part(repr(raised.value))


def test_another_is_a_box_of_the_same_address_and_transport_with_its_own_token() -> None:
    box_, seen = over(lambda request: httpx.Response(200, json={}))
    other = box_.another(SECRET)
    other.get("status/")
    assert (other.address, other.transport is box_.transport) == (ADDRESS, True)
    assert seen[0].headers["Authorization"] == f"Token {SECRET}"
