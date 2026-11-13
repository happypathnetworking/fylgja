"""`netbox/seed/hook.py`: the tag, the webhook and the event rule that ask the edge's Prefect for a rehearsal.

NetBox is `fake.FakeNetBox` and Prefect an `httpx.MockTransport` handler of this file's: nothing here opens a socket
or starts a process. The tokens and the basic auth are values of the tests' own. No value of the auth or of its header
is compared inside an assert, whose message would print it: each is compared first and the assert given the answer
alone (`same`), as `core/tests/test_config.py` does. Every URL is built from its parts, since no file under `netbox/`
writes one with its host (`test_tree.py`).
"""

from __future__ import annotations

import ast
import base64
import json
import sys
from pathlib import Path
from typing import Any

import hook
import httpx
import pytest
from box import ADDRESS as ADDRESS_NAME
from box import TOKEN as TOKEN_NAME
from box import WORDS, Box, BoxError
from fake import ADDRESS, FakeNetBox

HOST = "host.docker.internal"
"""The name NetBox's worker reaches the development host by (`netbox/dev/compose.override.yml`)."""

PREFECT_HOST = "prefect.example:4200"
PREFECT = f"http://{PREFECT_HOST}/api"
"""Prefect's API as `scripts/edge_dev.py api` prints it, at a name of the tests'."""

TOKEN = "nbt_k.t"
AUTH = "QXZWV:KJVTRQPZMXWYBNLKGHDF"
"""A basic auth of the tests', `user:password`, of capitals that no sentence of the hook's holds five of in a row."""
AUTH_AGAIN = "VWXQZ:PLMKOJNHUBYGTVRCFXDZ"

DEPLOYMENT = "0b9d8c1e-4f6a-4c2b-9d3e-7a1b2c3d4e5f"
DEPLOYMENT_AGAIN = "5e4d3c2b-1a0f-4e9d-8c7b-6a5f4e3d2c1b"

NAME = "fylgja-rehearse"
BRANCH = "netbox_branching.branch"
TAGS, WEBHOOKS, RULES = "extras/tags/", "extras/webhooks/", "extras/event-rules/"

SEED = Path(__file__).resolve().parents[1] / "seed"


def same(a: object, b: object) -> bool:
    """`a == b` as a bool, so that a failure shows neither."""
    return a == b


def encoded(auth: str) -> str:
    return base64.b64encode(auth.encode()).decode()


def runs(text: str, *secrets: str) -> list[str]:
    """Each run of five characters of any of `secrets` that `text` holds; `[]` where it holds none."""
    return [secret[at : at + 5] for secret in secrets for at in range(len(secret) - 4) if secret[at : at + 5] in text]


class Prefect:
    """Prefect's API as the hook reads it: the deployment `twin-rehearse/main` by its name, answered `deployment`, or
    the status `status` with Prefect's own words, every request kept."""

    def __init__(self, deployment: str = DEPLOYMENT, status: int = 200) -> None:
        self.deployment = deployment
        self.status = status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.url.path == "/api/deployments/name/twin-rehearse/main", request.url.path
        if self.status == 404:
            return httpx.Response(404, json={"detail": "Deployment not found"})
        if self.status == 401:
            return httpx.Response(401, json={"exception_message": "Unauthorized"})
        return httpx.Response(200, json={"id": self.deployment, "name": "main", "status": "READY"})


def unanswered(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("[Errno 111] Connection refused", request=request)


def environ(auth: str = AUTH) -> dict[str, str]:
    return {ADDRESS_NAME: ADDRESS, TOKEN_NAME: TOKEN, "FYLGJA_ORCHESTRATOR_AUTH": auth}


def over(handler: Any) -> Box:
    return Box(ADDRESS, TOKEN, transport=httpx.MockTransport(handler))


def run(
    fake: Any,
    prefect: Any,
    capsys: pytest.CaptureFixture[str],
    *,
    auth: str = AUTH,
    argv: list[str] | None = None,
) -> tuple[int, str, str]:
    code = hook.main(
        argv if argv is not None else ["--prefect", PREFECT],
        environ=environ(auth),
        box=over(fake),
        transport=httpx.MockTransport(prefect),
    )
    out, err = capsys.readouterr()
    return code, out, err


def test_the_values_are_the_triggers_as_read() -> None:
    """The webhook as it was read starting a run (design/verified-facts.md, "NetBox 4.7.5 with netbox-branching
    1.2.3"), its body writing the branch's name by Jinja2's `tojson`, and the rule held to the tag by its slug."""
    assert hook.TAG == hook.NAME == NAME
    assert hook.RECEIVER.split(":") == [HOST, "4200"]
    assert (hook.FLOW, hook.DEPLOYMENT) == ("twin-rehearse", "main")
    assert hook.BODY == '{"parameters": {"branch": {{ data.name | tojson }}}}'
    assert hook.CONDITIONS == {"and": [{"attr": "tags.slug", "value": NAME, "op": "contains"}]}


def test_the_three_are_made_by_name_and_the_webhook_holds_the_deployments_id(
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake, prefect = FakeNetBox(), Prefect()
    code, out, err = run(fake, prefect, capsys)
    assert (code, err) == (0, "")

    [tag] = fake.rows(TAGS)
    assert (tag["name"], tag["slug"], tag["object_types"]) == (NAME, NAME, [BRANCH])
    [webhook] = fake.rows(WEBHOOKS)
    assert webhook["name"] == NAME
    assert webhook["payload_url"] == f"http://{HOST}:4200/api/deployments/{DEPLOYMENT}/create_flow_run"
    assert (webhook["http_method"], webhook["http_content_type"]) == ("POST", "application/json")
    assert webhook["body_template"] == hook.BODY
    assert same(webhook["additional_headers"], f"Authorization: Basic {encoded(AUTH)}")
    [rule] = fake.rows(RULES)
    assert rule["name"] == NAME
    assert (rule["object_types"], rule["event_types"]) == ([BRANCH], ["object_updated"])
    assert rule["enabled"] is True
    assert rule["conditions"] == hook.CONDITIONS
    assert (rule["action_type"], rule["action_object_type"], rule["action_object_id"]) == (
        "webhook",
        "extras.webhook",
        webhook["id"],
    )

    looked = [(path, query) for path, query in looked_up(fake)]
    assert looked == [(TAGS, {"name": NAME}), (WEBHOOKS, {"name": NAME}), (RULES, {"name": NAME})]
    [asked] = prefect.requests
    assert asked.method == "GET"
    assert same(asked.headers["Authorization"], f"Basic {encoded(AUTH)}")
    assert out.splitlines()[:3] == [
        f"hook: made the tag {NAME}",
        f"hook: made the webhook {NAME}",
        f"hook: made the event rule {NAME}",
    ]
    [last] = out.splitlines()[3:]
    assert f"twin-rehearse/main, deployment {DEPLOYMENT}" in last
    assert "make netbox-hook again" in last and "home" in last


def looked_up(fake: FakeNetBox) -> list[tuple[str, dict[str, str]]]:
    """Each list the hook read, by its path and its query less the page's."""
    return [
        (
            request.url.path.removeprefix("/api/"),
            {name: value for name, value in request.url.params.items() if name not in ("limit", "offset")},
        )
        for request in fake.requests
        if request.method == "GET"
    ]


def test_a_second_run_makes_nothing_and_writes_the_address_and_the_header_again(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Prefect's home new and the auth another: the one webhook is given the new id and the new header, by one
    `PATCH` of those two members, and the tag and the rule are found. A third run, with nothing new, sends no write,
    since a `PATCH` that changes nothing is a write all the same, and says nothing was made or changed."""
    fake = FakeNetBox()
    assert run(fake, Prefect(), capsys)[0] == 0
    fake.requests.clear()

    code, out, err = run(fake, Prefect(DEPLOYMENT_AGAIN), capsys, auth=AUTH_AGAIN)
    assert (code, err) == (0, "")
    [webhook] = fake.rows(WEBHOOKS)
    assert webhook["payload_url"] == f"http://{HOST}:4200/api/deployments/{DEPLOYMENT_AGAIN}/create_flow_run"
    assert same(webhook["additional_headers"], f"Authorization: Basic {encoded(AUTH_AGAIN)}")
    assert len(fake.rows(TAGS)) == len(fake.rows(RULES)) == 1
    assert fake.writes() == [f"PATCH /api/{WEBHOOKS}{webhook['id']}/"]
    assert [(path, set(body)) for path, body in fake.sent("PATCH")] == [
        (f"{WEBHOOKS}{webhook['id']}/", {"payload_url", "additional_headers"})
    ]
    said = out.splitlines()
    assert not any("made" in line for line in said)
    assert said[0] == f"hook: wrote the webhook {NAME}'s payload_url and additional_headers anew"

    fake.requests.clear()
    code, out, _ = run(fake, Prefect(DEPLOYMENT_AGAIN), capsys, auth=AUTH_AGAIN)
    assert code == 0
    assert fake.writes() == []
    assert out.splitlines()[0] == f"hook: the tag, the webhook and the event rule {NAME} stand; nothing made or changed"


def test_a_rule_found_naming_another_action_is_written_to_name_the_webhook(capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeNetBox()
    assert run(fake, Prefect(), capsys)[0] == 0
    [rule] = fake.rows(RULES)
    fake.objects[RULES][rule["id"]]["action_object_id"] = 99
    code, out, _ = run(fake, Prefect(), capsys)
    [webhook] = fake.rows(WEBHOOKS)
    assert code == 0
    assert fake.rows(RULES)[0]["action_object_id"] == webhook["id"]
    assert fake.sent("PATCH") == [(f"{RULES}{rule['id']}/", {"action_object_id": webhook["id"]})]
    assert f"hook: wrote the event rule {NAME}'s action_object_id anew" in out.splitlines()


def installed(capsys: pytest.CaptureFixture[str]) -> FakeNetBox:
    """A fake on which a first run has installed the trigger, its requests forgotten."""
    fake = FakeNetBox()
    assert run(fake, Prefect(), capsys)[0] == 0
    fake.requests.clear()
    return fake


def test_everything_as_it_should_be_sends_no_write(capsys: pytest.CaptureFixture[str]) -> None:
    """NetBox answers a rule's `action_type` as a row of its value and label, and may order a list otherwise than it
    was written: each is held as it is meant, so the trigger as installed is found as it should be."""
    fake = installed(capsys)
    [rule] = fake.rows(RULES)
    held = fake.objects[RULES][rule["id"]]
    held["action_type"] = {"value": "webhook", "label": "Webhook"}
    held["object_types"] = list(reversed(held["object_types"]))
    code, out, err = run(fake, Prefect(), capsys)
    assert (code, err) == (0, "")
    assert fake.writes() == []
    assert out.splitlines()[0] == f"hook: the tag, the webhook and the event rule {NAME} stand; nothing made or changed"


@pytest.mark.parametrize(
    ("standing", "written", "held"),
    [
        (["dcim.device", "netbox_branching.branch"], ["netbox_branching.branch", "dcim.device"], True),
        (["dcim.device", "netbox_branching.branch"], ["dcim.device", "netbox_branching.branch"], True),
        (["dcim.device", "netbox_branching.branch"], ["netbox_branching.branch"], False),
        (["netbox_branching.branch"], ["dcim.device", "netbox_branching.branch"], False),
        (["dcim.device", "dcim.device"], ["dcim.device", "netbox_branching.branch"], False),
        (["dcim.device", "netbox_branching.branch"], ["dcim.device", "ipam.vlan"], False),
    ],
    ids=["two in another order", "two in order", "one of the two", "two of one", "one twice", "another of two"],
)
def test_a_list_of_two_is_held_as_a_set(standing: list[str], written: list[str], held: bool) -> None:
    """NetBox may answer a list of names in another order than it was written (design/verified-facts.md, "A
    permission answers `object_types` in an order of its own"): two names in either order are the same, and a list
    that lacks one, holds one twice or holds another is not."""
    assert hook.same(standing, written) is held


@pytest.mark.parametrize(
    ("path", "what", "member", "standing"),
    [
        (RULES, "event rule", "enabled", False),
        (RULES, "event rule", "conditions", {"and": [{"attr": "tags.slug", "value": "other", "op": "contains"}]}),
        (RULES, "event rule", "event_types", ["object_created", "object_updated"]),
        (RULES, "event rule", "object_types", ["dcim.device"]),
        (RULES, "event rule", "action_type", {"value": "script", "label": "Script"}),
        (WEBHOOKS, "webhook", "http_method", "PUT"),
        (WEBHOOKS, "webhook", "http_content_type", "application/x-www-form-urlencoded"),
        (WEBHOOKS, "webhook", "body_template", '{"branch": "{{ data.name }}"}'),
        (TAGS, "tag", "object_types", ["dcim.device", "netbox_branching.branch"]),
        (TAGS, "tag", "object_types", []),
    ],
    ids=[
        "a disabled rule",
        "other conditions",
        "other event types",
        "other object types",
        "another action type",
        "another method",
        "another content type",
        "another body template",
        "a tag not limited to branches",
        "a tag of every type",
    ],
)
def test_a_member_found_otherwise_is_written_back_alone_and_said(
    path: str, what: str, member: str, standing: object, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = installed(capsys)
    [row] = fake.rows(path)
    wanted = fake.objects[path][row["id"]][member]
    fake.objects[path][row["id"]][member] = standing
    code, out, err = run(fake, Prefect(), capsys)
    assert (code, err) == (0, "")
    assert fake.sent("PATCH") == [(f"{path}{row['id']}/", {member: wanted})]
    assert fake.objects[path][row["id"]][member] == wanted
    assert out.splitlines()[0] == f"hook: wrote the {what} {NAME}'s {member} anew"
    assert not any("nothing made or changed" in line for line in out.splitlines())


def test_the_header_is_basic_auth_and_is_never_printed(capsys: pytest.CaptureFixture[str]) -> None:
    assert hook.header("fylgja:pw") == "Authorization: Basic " + base64.b64encode(b"fylgja:pw").decode()
    code, out, err = run(FakeNetBox(), Prefect(), capsys)
    assert code == 0
    held = runs(out + err, AUTH, encoded(AUTH))
    assert held == []


@pytest.mark.parametrize(
    ("prefect", "said"),
    [
        (
            Prefect(status=404),
            f"twin-rehearse/main is not served at {PREFECT}: make orchestrator-serve SOURCE=netbox first",
        ),
        (Prefect(status=401), "FYLGJA_ORCHESTRATOR_AUTH"),
        (unanswered, "make prefect-up"),
    ],
    ids=["not served", "auth refused", "no answer"],
)
def test_a_deployment_not_served_or_a_refused_auth_is_one_line_and_writes_nothing(
    prefect: Any, said: str, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeNetBox()
    code, out, err = run(fake, prefect, capsys)
    assert (code, out) == (1, "")
    [line] = err.splitlines()
    assert said in line
    assert fake.requests == []
    held = runs(err, AUTH, encoded(AUTH))
    assert held == []


def test_the_auth_echoed_across_the_cut_is_hidden_whole(capsys: pytest.CaptureFixture[str]) -> None:
    """NetBox's words are cut at `box.WORDS` characters: a 400 that echoes the webhook's create puts its header across
    the 300th character, and the hook hands the auth, its base64 and the header line to `Box.hide` before the request,
    so that no part of any is left in the error, its `repr`, its cause, stdout or stderr."""
    behind = FakeNetBox()
    echoed: list[str] = []

    def echoing(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == f"/api/{WEBHOOKS}":
            sent = request.content.decode()
            at = sent.index(encoded(AUTH))
            detail = "." * (WORDS - at - len(encoded(AUTH)) // 2) + sent
            start = detail.index(encoded(AUTH))
            assert start < WORDS < start + len(encoded(AUTH))
            echoed.append(detail)
            return httpx.Response(400, json={"detail": detail})
        return behind(request)

    code, out, err = run(echoing, Prefect(), capsys)
    assert code == 1 and "HTTP 400" in err
    with pytest.raises(BoxError) as raised:
        hook.ensure(over(echoing), receiver=hook.RECEIVER, deployment=DEPLOYMENT, auth=AUTH)
    assert len(echoed) == 2
    error = raised.value
    texts = [out, err, str(error), repr(error), str(error.__cause__), str(error.__context__)]
    held = runs(" ".join(texts), AUTH, encoded(AUTH))
    assert held == []


def test_the_auth_echoed_across_the_cut_of_a_patch_is_hidden_whole(capsys: pytest.CaptureFixture[str]) -> None:
    """As for the create: the webhook found with another header is given the new one by a `PATCH`, and a 400 that
    echoes it across the 300th character leaves no part of the new auth, or of its base64, anywhere."""
    behind = FakeNetBox()
    assert run(behind, Prefect(), capsys)[0] == 0
    echoed: list[str] = []

    def echoing(request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH" and request.url.path.startswith(f"/api/{WEBHOOKS}"):
            sent = request.content.decode()
            at = sent.index(encoded(AUTH_AGAIN))
            detail = "." * (WORDS - at - len(encoded(AUTH_AGAIN)) // 2) + sent
            start = detail.index(encoded(AUTH_AGAIN))
            assert start < WORDS < start + len(encoded(AUTH_AGAIN))
            echoed.append(detail)
            return httpx.Response(400, json={"detail": detail})
        return behind(request)

    code, out, err = run(echoing, Prefect(), capsys, auth=AUTH_AGAIN)
    assert code == 1 and "HTTP 400" in err
    with pytest.raises(BoxError) as raised:
        hook.ensure(over(echoing), receiver=hook.RECEIVER, deployment=DEPLOYMENT, auth=AUTH_AGAIN)
    assert len(echoed) == 2
    error = raised.value
    texts = [out, err, str(error), repr(error), str(error.__cause__), str(error.__context__)]
    held = runs(" ".join(texts), AUTH_AGAIN, encoded(AUTH_AGAIN))
    assert held == []


@pytest.mark.parametrize("name", [ADDRESS_NAME, TOKEN_NAME, "FYLGJA_ORCHESTRATOR_AUTH"])
def test_a_variable_not_set_is_exit_2_naming_it(name: str, capsys: pytest.CaptureFixture[str]) -> None:
    fake, prefect = FakeNetBox(), Prefect()
    given = {key: value for key, value in environ().items() if key != name}
    code = hook.main(["--prefect", PREFECT], environ=given, box=over(fake), transport=httpx.MockTransport(prefect))
    _, err = capsys.readouterr()
    assert code == 2 and name in err
    assert fake.requests == [] and prefect.requests == []


@pytest.mark.parametrize(
    "argv",
    [[], ["--prefect", "prefect.example:4200"], ["--prefect", PREFECT, "--receiver", "no-port"]],
    ids=["no prefect", "no scheme", "a receiver with no port"],
)
def test_a_command_line_not_understood_is_exit_2(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    fake, prefect = FakeNetBox(), Prefect()
    code, _, _ = run(fake, prefect, capsys, argv=argv)
    assert code == 2
    assert fake.requests == [] and prefect.requests == []


LOGIN = "fylgja:QXZWVKJVTRQ"
"""A login of the tests', `user:password`, given in `--prefect` where none belongs."""


@pytest.mark.parametrize(
    "prefect",
    [
        f"http://{LOGIN}@{PREFECT_HOST}/api",
        f"{LOGIN}@{PREFECT_HOST}/api",
        f"http://{LOGIN.partition(':')[2]}@{PREFECT_HOST}/api",
    ],
    ids=["a login", "a login and no scheme", "a user alone"],
)
def test_a_prefect_holding_a_login_is_refused_naming_the_argument_alone(
    prefect: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """The basic auth is read from `FYLGJA_ORCHESTRATOR_AUTH` alone: an API given with a login in it is refused before
    anything is sent or said, and no part of the value is printed, since it may be a password."""
    fake, given = FakeNetBox(), Prefect()
    code, out, err = run(fake, given, capsys, argv=["--prefect", prefect])
    assert (code, out) == (2, "")
    [line] = err.splitlines()
    assert "--prefect" in line and "login" in line
    held = runs(out + err, LOGIN)
    assert held == []
    assert fake.requests == [] and given.requests == []


def test_the_receiver_is_the_address_the_webhook_names(capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeNetBox()
    elsewhere = "192.0.2.1:14200"
    code, _, _ = run(fake, Prefect(), capsys, argv=["--prefect", PREFECT, "--receiver", elsewhere])
    assert code == 0
    [webhook] = fake.rows(WEBHOOKS)
    assert webhook["payload_url"] == f"http://{elsewhere}/api/deployments/{DEPLOYMENT}/create_flow_run"


def test_the_hook_imports_the_standard_library_box_and_httpx_alone() -> None:
    """It runs alone beside `box.py`: nothing of Fylgja's packages, and neither the seed, the accounts nor the change.
    What it shares with the example it holds by value (`orchestrator/tests/test_dev_plumbing.py` holds them equal)."""
    tree = ast.parse((SEED / "hook.py").read_text())
    nodes = list(ast.walk(tree))
    named = {alias.name.split(".")[0] for node in nodes if isinstance(node, ast.Import) for alias in node.names}
    named |= {str(node.module).split(".")[0] for node in nodes if isinstance(node, ast.ImportFrom) and node.level == 0}
    assert named - set(sys.stdlib_module_names) == {"box", "httpx"}


@pytest.mark.parametrize(
    ("name", "sent"),
    [
        ("third-link", '"third-link"'),
        ('p9-read-q"x', '"p9-read-q\\"x"'),
        ("p9-read-b\\x", '"p9-read-b\\\\x"'),
        ("p9-read-s'<&>", '"p9-read-s\\u0027\\u003c\\u0026\\u003e"'),
    ],
    ids=["a plain name", "a quote", "a backslash", "an apostrophe and brackets"],
)
def test_a_body_netbox_sends_is_the_parameters_prefect_reads(name: str, sent: str) -> None:
    """The body template, with `{{ data.name | tojson }}` written as NetBox's worker sent it for a branch of each name
    (design/verified-facts.md, "A branch's name in a webhook's body"), is the one parameter of `twin-rehearse`, the
    name as it is: a quote or a backslash in it closes no string of the body's."""
    assert json.loads(sent) == name
    assert json.loads(hook.BODY.replace("{{ data.name | tojson }}", sent)) == {"parameters": {"branch": name}}
