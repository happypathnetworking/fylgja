"""The trigger that asks the edge's Prefect for a rehearsal: the tag `fylgja-rehearse`, a webhook to Prefect's API and
the event rule between them, on the development NetBox (D-097).

Run by `make netbox-hook` as `core/.venv/bin/python netbox/seed/hook.py --prefect <Prefect's API>`, the API what
`scripts/edge_dev.py api` prints, with `local/.env` loaded for `FYLGJA_NETBOX_ADDRESS`, the superuser's
`FYLGJA_NETBOX_WRITE_TOKEN` and the basic auth `FYLGJA_ORCHESTRATOR_AUTH` (D-042), once
`make orchestrator-serve SOURCE=netbox` serves:

- the id of the deployment `twin-rehearse/main` is read from Prefect with the basic auth. A deployment's id is another
  once Prefect's home is new, and a webhook naming an old id is answered 404 and starts nothing
  (design/verified-facts.md, "Prefect 3.9.2"), so this is run again after every new home;
- the tag `TAG`, limited to branches; the webhook `NAME`, a `POST` to `http://<receiver>/api/deployments/<id>/
  create_flow_run`, `--receiver` the address NetBox's worker reaches Prefect at, of `BODY`, the branch's name as the
  flow's one parameter, with the basic auth's header line; and the event rule `NAME` on a branch's update while it
  carries the tag, enabled, its action the webhook: each found by its name or made. Of one found, each member this
  writes is compared with what stands, a choice by its value and a list as a set, the header in memory, and only the
  members that differ are written again, in one `PATCH`: a run that finds the trigger as it should be sends no write.
  They are the installed trigger, and are left: setting the tag on a branch asks for its rehearsal, once a setting.

Each request to NetBox is the superuser's: neither account may list a webhook or an event rule, or read one by its
id. Both read `main`'s changelog, though, and its rows of a webhook hold `additional_headers` as written, unmasked,
and `secret` too, which this sets none of, so the basic auth this installs is read there by the reader's account and
the example's, as read for their grants, which have no constraint (design/verified-facts.md, "NetBox 4.7.5 with
netbox-branching 1.2.3"). The rows outlive the webhook, so a value once written stays readable until that changelog's
own pruning, or a purge of the instance, removes its rows; replacing the auth removes no row, and the old value stays
readable there and only stops opening Prefect. The example accepts this as a known limit: it is a demonstration, whose
secrets sit together on a development host. Restricting who may view the changelog is by itself no remedy, since both
accounts must keep that view. A deployment that shares its NetBox puts a receiver of its own between NetBox and
Prefect, so that Prefect's credential never enters NetBox, though whatever that receiver is sent, a header or a
`secret`, the same rows hold; or it gives grants that hide the webhook's rows from the accounts that need the
changelog, which was not read (docs/integrating.md, "Credentials"). The basic auth, its base64
and the header line are handed to `Box.hide` before any request that carries them, so that a refusal echoing one has
it replaced before NetBox's words are cut; no error is chained to the httpx exception it came from, which carries its
request's headers.

It prints one line for each thing it made, and one for each it wrote again naming the members it wrote, then the
deployment the webhook starts; that nothing was made or changed only where nothing was; and never the auth or the
header. Exit 0; 1 for a refusal or a failure said on stderr; 2 for a command line not understood or a variable not
set.

Run by `core/.venv/bin/python`; httpx, `box` and the standard library alone, never `fylgja_core`, a reader, the
example or a client library of NetBox's or of Prefect's: what it shares with the example, it holds by value.
"""

from __future__ import annotations

import argparse
import base64
import os
import re
import sys
import uuid
from collections.abc import Mapping, Sequence
from typing import Any, TypeGuard

import httpx
from box import ADDRESS, TOKEN, Box, BoxError

TAG = "fylgja-rehearse"
"""The tag that asks for a rehearsal, its name and its slug: `fylgja_orchestrator.netbox.TAG`, held by value."""

NAME = "fylgja-rehearse"
"""The webhook's name and the event rule's."""

RECEIVER = "host.docker.internal:4200"
"""Where NetBox's worker reaches the edge's Prefect: the name `netbox/dev/compose.override.yml` gives the development
host, and the port `make prefect-up` serves on."""

FLOW = "twin-rehearse"
DEPLOYMENT = "main"
"""The flow and the deployment a tag starts: `fylgja_orchestrator.edge.flows`' `TWIN_REHEARSE` and `DEPLOYMENT`, held
by value."""

BODY = '{"parameters": {"branch": {{ data.name | tojson }}}}'
"""The webhook's body, which NetBox renders with the branch as `data`: the flow's one parameter, the branch's name,
written as a JSON string by Jinja2's `tojson`, so that a name holding `"` or `\\`, which the plugin takes, is sent as
it is (design/verified-facts.md, "A branch's name in a webhook's body")."""

CONDITIONS = {"and": [{"attr": "tags.slug", "value": TAG, "op": "contains"}]}
"""The rule's conditions: a branch's update sends the webhook only while the branch carries the tag."""

AUTH = "FYLGJA_ORCHESTRATOR_AUTH"
"""The basic auth Prefect's server and its clients share, `user:password`."""

BRANCH = "netbox_branching.branch"
EVENT = "object_updated"
JSON = "application/json"
WEBHOOK = "extras.webhook"

TAGS = "extras/tags/"
WEBHOOKS = "extras/webhooks/"
RULES = "extras/event-rules/"

BASIC = "Authorization: Basic "

TIMEOUT = httpx.Timeout(30.0, connect=5.0)
"""Each request to Prefect: 30 s, 5 s to connect, as the example's own requests are given."""

HOST_PORT = re.compile(r"[A-Za-z0-9.-]+:[0-9]{1,5}")

AGAIN = "run make netbox-hook again after every new Prefect home, since the deployment's id is then another"


class HookError(Exception):
    """Prefect not answering, or answering no deployment, in one sentence that holds no part of the auth."""


def say(line: str, *, err: bool = False) -> None:
    print(f"hook: {line}", file=sys.stderr if err else sys.stdout, flush=True)


def header(auth: str) -> str:
    """The header line that carries the basic auth `auth`, `user:password`, as NetBox's webhook sends it."""
    return BASIC + base64.b64encode(auth.encode()).decode()


def deployment_id(prefect: str, auth: str, *, transport: httpx.BaseTransport | None = None) -> str:
    """The id of `FLOW`/`DEPLOYMENT` at Prefect's API `prefect`, read with the basic auth `auth`; a `HookError` where
    Prefect does not answer, does not serve it, refuses the auth or answers no id."""
    path = f"{prefect.rstrip('/')}/deployments/name/{FLOW}/{DEPLOYMENT}"
    failure: str | None = None
    try:
        with httpx.Client(transport=transport, timeout=TIMEOUT, trust_env=False) as client:
            response = client.get(path, headers={"Authorization": header(auth).removeprefix("Authorization: ")})
    except httpx.HTTPError as e:
        failure = f"Prefect did not answer at {prefect}: {type(e).__name__}: {e}; make prefect-up first"
    if failure is not None:
        raise HookError(failure)
    if response.status_code == 404:
        raise HookError(f"{FLOW}/{DEPLOYMENT} is not served at {prefect}: make orchestrator-serve SOURCE=netbox first")
    if response.status_code == 401:
        raise HookError(
            f"Prefect at {prefect} refused the basic auth {AUTH}: load local/.env again, whose line make "
            "orchestrator-env writes and make prefect-up gives the server"
        )
    if not 200 <= response.status_code <= 299:
        raise HookError(f"GET {path} answered HTTP {response.status_code}")
    try:
        answer: Any = response.json()
        return str(uuid.UUID(answer["id"]))
    except (ValueError, TypeError, KeyError, AttributeError):
        failure = f"GET {path} answered no deployment's id"
    raise HookError(failure)


def ensure(box: Box, *, receiver: str, deployment: str, auth: str) -> list[str]:
    """The tag, the webhook to `receiver` naming `deployment` with the basic auth `auth`, and the rule, as the module
    says; what was made or changed, in order, `[]` where nothing was. A `BoxError` holds no part of the auth: it, its
    base64 and its header line are handed to `box.hide` before any request."""
    line = header(auth)
    box.hide(auth, line, line.removeprefix(BASIC))
    address = f"http://{receiver}/api/deployments/{deployment}/create_flow_run"
    done: list[str] = []

    found(box, TAGS, "tag", {"name": TAG, "slug": TAG, "object_types": [BRANCH]}, done)
    webhook = found(
        box,
        WEBHOOKS,
        "webhook",
        {
            "name": NAME,
            "payload_url": address,
            "http_method": "POST",
            "http_content_type": JSON,
            "additional_headers": line,
            "body_template": BODY,
        },
        done,
    )
    found(
        box,
        RULES,
        "event rule",
        {
            "name": NAME,
            "object_types": [BRANCH],
            "event_types": [EVENT],
            "enabled": True,
            "conditions": CONDITIONS,
            "action_type": "webhook",
            "action_object_type": WEBHOOK,
            "action_object_id": webhook["id"],
        },
        done,
    )
    return done


def found(box: Box, path: str, what: str, body: Mapping[str, Any], done: list[str]) -> dict[str, Any]:
    """The object of `path` named `body`'s `name`, made of `body` where none is; of one found, the members of `body`
    that differ from what stands (`same`) written again in one `PATCH`, and nothing where none does. What was made or
    written is added to `done`, a member by its name and never its value."""
    row = box.ensure(path, {"name": body["name"]}, body)
    if box.ensured[-1][0] == "made":
        done.append(f"made the {what} {body['name']}")
        return row
    differ = {member: value for member, value in body.items() if not same(row.get(member), value)}
    if differ:
        box.patch(f"{path}{row['id']}/", differ)
        done.append(f"wrote the {what} {body['name']}'s {joined(list(differ))} anew")
    return row


def same(standing: object, written: object) -> bool:
    """Whether the member as NetBox answers it, `standing`, is what this writes: a choice NetBox answers as a row of
    its value and its label by its value, and a list of names as a set, since NetBox may order one otherwise than it
    was written."""
    if isinstance(standing, dict) and set(standing) == {"value", "label"} and not isinstance(written, dict):
        standing = standing["value"]
    if names(standing) and names(written):
        return set(standing) == set(written) and len(standing) == len(written)
    return standing == written


def names(value: object) -> TypeGuard[list[str]]:
    return isinstance(value, list) and all(isinstance(member, str) for member in value)


def joined(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def parser() -> argparse.ArgumentParser:
    made = argparse.ArgumentParser(
        prog="hook.py",
        description=(__doc__ or "").splitlines()[0],
        epilog=f"The webhook names the deployment's id: {AGAIN}.",
    )
    made.add_argument("--prefect", required=True, metavar="URL", help="Prefect's API as the host reaches it")
    made.add_argument(
        "--receiver",
        default=RECEIVER,
        metavar="HOST:PORT",
        help=f"where NetBox's worker reaches Prefect; {RECEIVER} where not given",
    )
    return made


def understood(args: argparse.Namespace) -> str | None:
    """Why the command line is not understood, None where it is. A `--prefect` holding an `@`, as a login does, is
    refused first and by the argument's name alone, since the value may hold a password: the basic auth is
    `FYLGJA_ORCHESTRATOR_AUTH`'s."""
    if "@" in args.prefect:
        return (
            "--prefect holds an @, as a login does: give Prefect's API with no login, as scripts/edge_dev.py api "
            f"prints it; the basic auth is read from {AUTH}"
        )
    try:
        prefect = httpx.URL(args.prefect)
    except httpx.InvalidURL:
        prefect = None
    if prefect is None or prefect.scheme not in ("http", "https") or not prefect.host:
        return f"--prefect {args.prefect} is not Prefect's API, an http URL as scripts/edge_dev.py api prints it"
    if not HOST_PORT.fullmatch(args.receiver):
        return f"--receiver {args.receiver} is not HOST:PORT"
    return None


def main(
    argv: Sequence[str],
    *,
    environ: Mapping[str, str] = os.environ,
    box: Box | None = None,
    transport: httpx.BaseTransport | None = None,
) -> int:
    """The trigger installed, as `make netbox-hook` runs it; `box` and `transport`, NetBox's and Prefect's, where a
    test gives them."""
    try:
        args = parser().parse_args(argv)
    except SystemExit as e:
        return 0 if e.code in (0, None) else 2
    refused = understood(args)
    if refused is not None:
        say(refused, err=True)
        return 2
    for name in (ADDRESS, TOKEN):
        if not environ.get(name):
            say(f"{name} is not set: load local/.env first", err=True)
            return 2
    auth = environ.get(AUTH, "")
    if not auth:
        say(f"{AUTH} is not set: run make orchestrator-env SOURCE=netbox and load local/.env", err=True)
        return 2
    try:
        deployment = deployment_id(args.prefect, auth, transport=transport)
    except HookError as e:
        say(f"{e}", err=True)
        return 1
    try:
        reach = box if box is not None else Box(environ[ADDRESS], environ[TOKEN])
    except BoxError as e:
        say(f"{e}", err=True)
        return 1
    try:
        done = ensure(reach, receiver=args.receiver, deployment=deployment, auth=auth)
    except BoxError as e:
        say(f"{e}", err=True)
        return 1
    finally:
        reach.close()
    for line in done or [f"the tag, the webhook and the event rule {NAME} stand; nothing made or changed"]:
        say(line)
    say(f"the webhook {NAME} starts {FLOW}/{DEPLOYMENT}, deployment {deployment}, at {args.receiver}; {AGAIN}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
