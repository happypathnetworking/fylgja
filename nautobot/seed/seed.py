"""The fixture network on the development Nautobot, its templates in the repository the `git` service serves, and
Golden Config's installed `Default Settings` pointed at both.

Run by `make nautobot-seed` as `core/.venv/bin/python nautobot/seed/seed.py --files nautobot/seed --git
<local>/nautobot/git`, with `local/.env` loaded for `FYLGJA_NAUTOBOT_ADDRESS` and the superuser's
`FYLGJA_NAUTOBOT_WRITE_TOKEN` (CONTRIBUTING.md, D-042):

- first the templates: `files`/`templates/` written as one tree into `--git`/`templates.git`, the bare repository
  made where it is absent, and committed onto `main` only where that tree is not `main`'s, so that a template changed
  reaches Nautobot as a push and a second seed commits nothing;
- then every object `files`/`main.yaml` says, found by its name, a device type by its model, an interface by its
  device and its name, a prefix and an address by their values in the namespace `Global`, an address's assignment
  by the address and the interface, and a cable by its ends' rows; or made, in the order a later one needs an earlier
  one's id: the manufacturer, the platform, the device type, the location type, the location, the role, the tag, the
  devices, their interfaces, the prefixes, the addresses and their assignments, the cables, the configuration
  context of the probes, inactive, so that no device's context takes it, the repository and the query
  `files`/`sotagg.graphql`. A status is given by its name, and each address's prefix is derived from the address
  here, never written in a file;
- of an object found, the query's text, the repository's remote and branch, and the context's data and state are
  written again where they differ, and nothing else of it is touched;
- the installed `Default Settings`, found by its slug, is pointed at the repository, the path template and the
  query where it is not, and its dynamic group given the fixture's filter where it holds another; the group is then
  saved with its filter where its stored members are not the tagged devices, since Nautobot stores them, and refused
  naming the group where they still differ;
- then Nautobot is read back, the devices tagged `TAG` with their platform, ports, addresses and cables, the setting
  and its group's members, and the context, and each difference from the fixture is said. Nothing is ever deleted:
  `make nautobot-down PURGE=1` and the two targets after it make Nautobot the fixture again;
- last, each tagged device is rendered once by Golden Config with the superuser's token, which fetches the head a
  push moved, so that the first read after a seed is not refused for it, and each render is held to
  `testdata/blueprint/three-node.json`'s configuration for the device, its first line aside.

It prints one line an object, `made` or `found` and its path, and one for the templates' commit. Exit 0; 1 for a
refusal, a failure of Nautobot's or of git's, or a difference, each said on stderr with the purge; 2 for a command
line not understood, a file not read or a variable not set.

Run by `core/.venv/bin/python`; httpx, PyYAML, the standard library and `git` as a child alone, never `fylgja_core`, a
reader, the example or a client library of Nautobot's.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

import httpx
import yaml
from box import ADDRESS, TOKEN, Box, BoxError, where

FIXTURE = "main.yaml"
"""The fixture network, under `--files`: the one file that holds its addresses and the repository's remote."""

TEMPLATES = "templates"
"""The directory under `--files` whose files are the repository's tree, each named as the path template names it."""

QUERY = "sotagg.graphql"
"""The GraphQL query Golden Config renders each device's data with, under `--files`."""

REPOSITORY = "templates.git"
"""The bare repository under `--git`, the directory the `git` service serves."""

TAG = "fylgja"
"""The tag whose devices are the scope."""

SCOPE = "tag:fylgja"
"""The scope the seeded network is read in: the devices tagged `TAG`."""

NETWORK = Path(__file__).resolve().parents[2] / "testdata" / "blueprint" / "three-node.json"
"""The blueprint whose configuration each render is held to, found from this file's own path."""

PURGE = "make nautobot-down PURGE=1, then make nautobot-up, then make nautobot-seed"
"""The remedy, since the seed deletes nothing: Nautobot made empty, then the fixture again."""

ACTIVE = "Active"
CONNECTED = "Connected"
NAMESPACE = "Global"
DEVICE = "dcim.device"
INTERFACE = "dcim.interface"
PROVIDES = ["nautobot_golden_config.jinjatemplate"]
"""What the repository provides Golden Config: its Jinja templates."""

SETTINGS = "plugins/golden-config/golden-config-settings/"
GROUPS = "extras/dynamic-groups/"
RENDER = "plugins/golden-config/generate-intended-config/"
CABLES = "dcim/cables/"

IDENTITY = ["-c", "user.name=fylgja-seed", "-c", "user.email=seed@fylgja.example"]
"""The commit's author and committer, given on its command line, so that no configuration of the host's is needed."""

MESSAGE = "The templates of nautobot/seed/templates/, as make nautobot-seed commits them"


class Git(Protocol):
    """`git` run with `argv` after its name and `stdin` as its input, answering its stdout; a
    `subprocess.CalledProcessError` where it fails."""

    def __call__(self, argv: Sequence[str], stdin: str = "", /) -> str: ...


def command(argv: Sequence[str], stdin: str = "", /) -> str:
    """The host's `git`, as `Git` says."""
    done = subprocess.run(["git", *argv], input=stdin, capture_output=True, text=True, check=True)
    return done.stdout


def say(line: str, *, err: bool = False) -> None:
    print(f"seed: {line}" if err else line, file=sys.stderr if err else sys.stdout, flush=True)


def load(files: Path) -> dict[str, Any]:
    """The fixture network `files`/`FIXTURE`."""
    loaded = yaml.safe_load((files / FIXTURE).read_text())
    if not isinstance(loaded, dict):
        raise ValueError(f"{files / FIXTURE} holds no mapping")
    return loaded


def configurations(path: Path = NETWORK) -> dict[str, str]:
    """The blueprint's configuration of each device, by its name."""
    network = json.loads(path.read_text())["network"]
    return {str(device["name"]): str(device["config"]) for device in network["devices"]}


def templates(git: Git, served: Path, files: Path) -> str | None:
    """`files`/`TEMPLATES` committed onto `main` of `served`/`REPOSITORY`, the bare repository made where it is
    absent, and the repository made servable over plain HTTP; the commit made, or None where the tree is `main`'s
    already and nothing is written."""
    repository = served / REPOSITORY
    if not repository.exists():
        git(["init", "--bare", "--initial-branch=main", str(repository)])
    at = ["--git-dir", str(repository)]
    entries = []
    for path in sorted((files / TEMPLATES).iterdir()):
        if path.is_file():
            blob = git([*at, "hash-object", "-w", str(path)]).strip()
            entries.append(f"100644 blob {blob}\t{path.name}\n")
    tree = git([*at, "mktree"], "".join(entries)).strip()
    head = git([*at, "for-each-ref", "--format=%(objectname) %(tree)", "refs/heads/main"]).split()
    if head and head[1] == tree:
        return None
    parent = ["-p", head[0]] if head else []
    commit = git([*IDENTITY, *at, "commit-tree", "--no-gpg-sign", tree, *parent, "-m", MESSAGE]).strip()
    git([*at, "update-ref", "refs/heads/main", commit])
    git([*at, "update-server-info"])
    return commit


def standing(row: Mapping[str, Any], name: str) -> object:
    """The member `name` of `row` as it is compared to what a body sends: a related object, which Nautobot answers as
    `{id, object_type, url}` and is sent as its id, by its id."""
    value = row.get(name)
    return value.get("id") if isinstance(value, dict) and "object_type" in value else value


def ensured(
    box: Box,
    path: str,
    lookup: Mapping[str, object],
    body: Mapping[str, object],
    kept: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """The row `box.ensure` finds or makes; of a row found, the members of `kept` that differ written again in one
    `PATCH`, and nothing else of it."""
    row = box.ensure(path, lookup, body)
    if kept and box.ensured[-1][0] == "found":
        differ = {name: value for name, value in kept.items() if standing(row, name) != value}
        if differ:
            box.patch(f"{path}{row['id']}/", differ)
    return row


def end(text: str) -> tuple[str, str]:
    """A cable's end, `<device>:<port>`, as its device and its port."""
    device, _, port = text.partition(":")
    return device, port


def related(row: Mapping[str, Any], name: str) -> str | None:
    """The id of the object `row`'s member `name` refers to, None where it refers to none."""
    value = row.get(name)
    return str(value["id"]) if isinstance(value, dict) and value.get("id") else None


def found(box: Box, path: str, **lookup: object) -> dict[str, Any]:
    """The one row at `path` that `lookup` matches, recorded as found; a `BoxError` where there is none, since the
    seed makes no object of what Nautobot installs."""
    row = box.one(path, **lookup)
    if row is None:
        named = ", ".join(f"{name} {value}" for name, value in lookup.items())
        raise BoxError(f"Nautobot holds no {where(path)} of the {named}, which it installs")
    box.ensured.append(("found", path, str(row["id"])))
    return row


def seed(box: Box, files: Path) -> None:
    """The fixture `files`/`FIXTURE` on Nautobot, found or made, and the installed setting pointed at it; a
    `BoxError` where Nautobot refuses, or where the setting's group's members are not the tagged devices after it is
    saved again."""
    fixture = load(files)
    text = (files / QUERY).read_text().strip()
    namespace = found(box, "ipam/namespaces/", name=NAMESPACE)["id"]

    manufacturer = ensured(
        box, "dcim/manufacturers/", {"name": fixture["manufacturer"]["name"]}, fixture["manufacturer"]
    )
    platform = ensured(
        box,
        "dcim/platforms/",
        {"name": fixture["platform"]["name"]},
        {**fixture["platform"], "manufacturer": manufacturer["id"]},
    )
    device_type = ensured(
        box,
        "dcim/device-types/",
        {"model": fixture["device_type"]["model"]},
        {**fixture["device_type"], "manufacturer": manufacturer["id"]},
    )
    location_type = ensured(
        box,
        "dcim/location-types/",
        {"name": fixture["location_type"]["name"]},
        {**fixture["location_type"], "content_types": [DEVICE]},
    )
    location = ensured(
        box,
        "dcim/locations/",
        {"name": fixture["location"]["name"]},
        {**fixture["location"], "location_type": location_type["id"], "status": ACTIVE},
    )
    role = ensured(
        box, "extras/roles/", {"name": fixture["role"]["name"]}, {**fixture["role"], "content_types": [DEVICE]}
    )
    tag = ensured(box, "extras/tags/", {"name": fixture["tag"]["name"]}, {**fixture["tag"], "content_types": [DEVICE]})

    devices: dict[str, dict[str, Any]] = {}
    for device in fixture["devices"]:
        devices[device["name"]] = ensured(
            box,
            "dcim/devices/",
            {"name": device["name"]},
            {
                "name": device["name"],
                "status": ACTIVE,
                "role": role["id"],
                "device_type": device_type["id"],
                "location": location["id"],
                "platform": platform["id"],
                "tags": [tag["id"]],
                "comments": device["comments"],
            },
        )
    ports: dict[tuple[str, str], dict[str, Any]] = {}
    for device in fixture["devices"]:
        number = devices[device["name"]]["id"]
        for port in device["interfaces"]:
            ports[(device["name"], port["name"])] = ensured(
                box,
                "dcim/interfaces/",
                {"device_id": number, "name": port["name"]},
                {
                    "device": number,
                    "name": port["name"],
                    "type": port["type"],
                    "mgmt_only": port["mgmt_only"],
                    "enabled": True,
                    "status": ACTIVE,
                },
            )
    for device in fixture["devices"]:
        for port in device["interfaces"]:
            for address in port["addresses"]:
                network = str(ipaddress.ip_interface(address).network)
                prefix = ensured(
                    box,
                    "ipam/prefixes/",
                    {"prefix": network, "namespace": namespace},
                    {"prefix": network, "namespace": namespace, "type": "network", "status": ACTIVE},
                )
                held = ensured(
                    box,
                    "ipam/ip-addresses/",
                    {"address": address, "namespace": namespace},
                    {
                        "address": address,
                        "namespace": namespace,
                        "parent": prefix["id"],
                        "type": "host",
                        "status": ACTIVE,
                    },
                )
                assignment = {"ip_address": held["id"], "interface": ports[(device["name"], port["name"])]["id"]}
                ensured(box, "ipam/ip-address-to-interface/", assignment, assignment)

    for a, b in (map(end, cable) for cable in fixture["cables"]):
        cable(box, ports[a], ports[b])

    probes = fixture["probes"]
    ensured(
        box,
        "extras/config-contexts/",
        {"name": probes["name"]},
        {"name": probes["name"], "data": probes["data"], "is_active": False},
        {"data": probes["data"], "is_active": False},
    )
    source = fixture["repository"]
    repository = ensured(
        box,
        "extras/git-repositories/",
        {"name": source["name"]},
        {**source, "provided_contents": PROVIDES},
        {"remote_url": source["remote_url"], "branch": source["branch"]},
    )
    query = ensured(
        box,
        "extras/graphql-queries/",
        {"name": fixture["query"]},
        {"name": fixture["query"], "query": text},
        {"query": text},
    )

    wanted = fixture["setting"]
    setting = found(box, SETTINGS, slug=wanted["slug"])
    points = {"jinja_repository": repository["id"], "jinja_path_template": wanted["path"], "sot_agg_query": query["id"]}
    differ = {name: value for name, value in points.items() if standing(setting, name) != value}
    if differ:
        box.patch(f"{SETTINGS}{setting['id']}/", differ)
    number = related(setting, "dynamic_group")
    if number is None:
        raise BoxError(f"the Golden Config setting {setting.get('name')} names no dynamic group")
    group = box.get(f"{GROUPS}{number}/")
    box.ensured.append(("found", GROUPS, number))
    saved = False
    if group.get("filter") != wanted["filter"]:
        box.patch(f"{GROUPS}{number}/", {"filter": wanted["filter"]})
        saved = True
    tagged = {str(row["id"]) for row in box.listed("dcim/devices/", tags=TAG)}
    members = {str(row["id"]) for row in box.listed(f"{GROUPS}{number}/members/")}
    if members != tagged and not saved:
        box.patch(f"{GROUPS}{number}/", {"filter": wanted["filter"]})
        members = {str(row["id"]) for row in box.listed(f"{GROUPS}{number}/members/")}
    if members != tagged:
        raise BoxError(
            f"the dynamic group {group.get('name')} holds {len(members)} members, saved again, where {len(tagged)}"
            f" devices are tagged {TAG}"
        )


def cable(box: Box, a: Mapping[str, Any], b: Mapping[str, Any]) -> None:
    """The cable between the interfaces `a` and `b`, as rows of them read before it: found where each names it and
    `a`'s peer is `b`, made where neither is cabled, and otherwise left for `differences` to name, since a port cabled
    elsewhere is not the fixture and the seed deletes nothing."""
    held_a, held_b = related(a, "cable"), related(b, "cable")
    if held_a is None and held_b is None:
        made = box.post(
            CABLES,
            {
                "termination_a_type": INTERFACE,
                "termination_a_id": a["id"],
                "termination_b_type": INTERFACE,
                "termination_b_id": b["id"],
                "status": CONNECTED,
            },
        )
        if not isinstance(made, dict) or not made.get("id"):
            raise BoxError(f"POST {where(CABLES)} answered no object")
        box.ensured.append(("made", CABLES, str(made["id"])))
    elif held_a == held_b and related(a, "cable_peer") == b["id"]:
        box.ensured.append(("found", CABLES, str(held_a)))


def joined(ends: frozenset[str]) -> str:
    return " to ".join(sorted(ends))


def differences(box: Box, fixture: Mapping[str, Any]) -> list[str]:
    """How Nautobot differs from `fixture`, each difference one sentence: the devices tagged `TAG`, their platform,
    each one's interfaces with `mgmt_only` and `enabled`, the addresses on them, the cables among them as pairs of
    ends, the setting with its group's filter and members, the repository, the query and the probes' context. `[]`
    where Nautobot is the fixture."""
    said: list[str] = []
    wanted = {device["name"]: device for device in fixture["devices"]}
    rows: dict[str, list[dict[str, Any]]] = {}
    tagged = box.listed("dcim/devices/", tags=TAG)
    for row in tagged:
        rows.setdefault(str(row.get("name")), []).append(row)
    for name in sorted(wanted.keys() - rows.keys()):
        said.append(f"Nautobot holds no device {name} tagged {TAG}")
    for name in sorted(rows.keys() - wanted.keys()):
        said.append(f"Nautobot holds the device {name} tagged {TAG}, which the fixture does not")
    for name in sorted(name for name, held in rows.items() if len(held) > 1):
        said.append(f"Nautobot holds {len(rows[name])} devices named {name} tagged {TAG}")

    platform = box.one("dcim/platforms/", name=fixture["platform"]["name"])
    if platform is None:
        said.append(f"Nautobot holds no platform {fixture['platform']['name']}")
    names: dict[str, str] = {}
    expected: set[tuple[str, str, str]] = set()
    for name in sorted(wanted.keys() & rows.keys()):
        device = rows[name][0]
        if platform is not None and related(device, "platform") != platform["id"]:
            said.append(f"the device {name} is not on the platform {platform.get('name')}, the fixture's")
        ports = {str(row.get("name")): row for row in box.listed("dcim/interfaces/", device_id=device["id"])}
        names.update({str(row["id"]): f"{name} {port}" for port, row in ports.items()})
        fixed = {port["name"]: port for port in wanted[name]["interfaces"]}
        for port in sorted(fixed.keys() - ports.keys()):
            said.append(f"Nautobot holds no port {name} {port}")
        for port in sorted(ports.keys() - fixed.keys()):
            said.append(f"Nautobot holds the port {name} {port}, which the fixture does not")
        for port in sorted(fixed.keys() & ports.keys()):
            held, fixed_mgmt = ports[port].get("mgmt_only"), fixed[port]["mgmt_only"]
            if held is not fixed_mgmt:
                said.append(f"the port {name} {port} has mgmt_only {held}, where the fixture has {fixed_mgmt}")
            if ports[port].get("enabled") is not True:
                said.append(f"the port {name} {port} is not enabled, where the fixture enables it")
            expected.update((name, port, address) for address in fixed[port]["addresses"])

    values = {str(row["id"]): str(row.get("address")) for row in box.listed("ipam/ip-addresses/")}
    addresses: set[tuple[str, str, str]] = set()
    for row in box.listed("ipam/ip-address-to-interface/"):
        on = names.get(str(related(row, "interface")))
        if on is not None:
            owner, _, interface = on.partition(" ")
            addresses.add((owner, interface, values.get(str(related(row, "ip_address")), "an address unlisted")))
    for name, port, address in sorted(expected - addresses):
        said.append(f"Nautobot holds no address {address} on {name} {port}")
    for name, port, address in sorted(addresses - expected):
        said.append(f"Nautobot holds the address {address} on {name} {port}, which the fixture does not")

    cables: dict[str, frozenset[str]] = {}
    for name in sorted(wanted.keys() & rows.keys()):
        for row in box.listed(CABLES, device_id=rows[name][0]["id"]):
            cables[str(row["id"])] = frozenset(
                termination(box, names, row, side).replace(" ", ":", 1) for side in ("a", "b")
            )
    fixed_cables = {frozenset(cable) for cable in fixture["cables"]}
    held_cables = list(cables.values())
    for ends in sorted(fixed_cables - set(held_cables), key=joined):
        said.append(f"Nautobot holds no cable {joined(ends)}")
    for ends in sorted(set(held_cables) - fixed_cables, key=joined):
        said.append(f"Nautobot holds the cable {joined(ends)}, which the fixture does not")
    for ends in sorted(set(held_cables), key=joined):
        if (count := held_cables.count(ends)) > 1:
            said.append(f"Nautobot holds {count} cables {joined(ends)}, where the fixture holds one at most")

    said.extend(pointed(box, fixture, {str(row["id"]) for row in tagged}))
    return said


def termination(box: Box, names: Mapping[str, str], row: Mapping[str, Any], side: str) -> str:
    """One end of the cable `row`, as `<device> <port>`: from `names` where it is a port of a device read, else read
    by its id."""
    kind, number = row.get(f"termination_{side}_type"), str(row.get(f"termination_{side}_id"))
    if number in names:
        return names[number]
    if kind != INTERFACE:
        return f"{kind} {number}"
    port = box.get(f"dcim/interfaces/{number}/")
    device = box.get(f"dcim/devices/{related(port, 'device')}/")
    return f"{device.get('name')} {port.get('name')}"


def pointed(box: Box, fixture: Mapping[str, Any], tagged: set[str]) -> list[str]:
    """How the setting, its group, the repository, the query and the probes' context differ from `fixture`, each one
    sentence."""
    said: list[str] = []
    source = fixture["repository"]
    repository = box.one("extras/git-repositories/", name=source["name"])
    if repository is None:
        said.append(f"Nautobot holds no Git repository {source['name']}")
    else:
        for member in ("remote_url", "branch"):
            if repository.get(member) != source[member]:
                said.append(f"the Git repository {source['name']}'s {member} is not the fixture's {source[member]}")
    query = box.one("extras/graphql-queries/", name=fixture["query"])
    if query is None:
        said.append(f"Nautobot holds no GraphQL query {fixture['query']}")

    wanted = fixture["setting"]
    setting = box.one(SETTINGS, slug=wanted["slug"])
    if setting is None:
        said.append(f"Nautobot holds no Golden Config setting of the slug {wanted['slug']}")
    else:
        name = setting.get("name")
        if repository is not None and related(setting, "jinja_repository") != repository["id"]:
            said.append(f"the Golden Config setting {name} names another repository than {source['name']}")
        if setting.get("jinja_path_template") != wanted["path"]:
            said.append(f"the Golden Config setting {name}'s path template is not {wanted['path']}")
        if query is not None and related(setting, "sot_agg_query") != query["id"]:
            said.append(f"the Golden Config setting {name} names another query than {fixture['query']}")
        number = related(setting, "dynamic_group")
        if number is None:
            said.append(f"the Golden Config setting {name} names no dynamic group")
        else:
            group = box.get(f"{GROUPS}{number}/")
            if group.get("filter") != wanted["filter"]:
                said.append(f"the dynamic group {group.get('name')}'s filter is not {json.dumps(wanted['filter'])}")
            members = {str(row["id"]) for row in box.listed(f"{GROUPS}{number}/members/")}
            if members != tagged:
                said.append(
                    f"the dynamic group {group.get('name')} holds {len(members)} members, where {len(tagged)}"
                    f" devices are tagged {TAG}"
                )

    probes = fixture["probes"]
    context = box.one("extras/config-contexts/", name=probes["name"])
    if context is None:
        said.append(f"Nautobot holds no configuration context {probes['name']}")
    else:
        if context.get("is_active") is not False:
            said.append(f"the configuration context {probes['name']} is active, where the fixture's is inactive")
        if context.get("data") != probes["data"]:
            said.append(f"the configuration context {probes['name']}'s data is not the fixture's probes")
    return said


def renders(box: Box, network: Mapping[str, str]) -> list[str]:
    """Each device tagged `TAG` rendered once by Golden Config, in the order of its name, and held to `network`'s
    configuration for it, its first line aside: each difference, refusal or answer that is no render one sentence
    naming the device. `[]` where each renders its configuration."""
    said: list[str] = []
    for row in sorted(box.listed("dcim/devices/", tags=TAG), key=lambda row: str(row.get("name"))):
        name = str(row.get("name"))
        try:
            answer = box.get(RENDER, device_id=row["id"])
        except BoxError as e:
            said.append(f"the render of {name} was refused: {e}")
            continue
        text = answer.get("intended_config") if isinstance(answer, dict) else None
        if not isinstance(text, str):
            said.append(f"the render of {name} answered no intended_config")
            continue
        if name not in network:
            said.append(f"the device {name} has no configuration in {NETWORK.name}")
            continue
        got, want = text.split("\n"), network[name].split("\n")
        for number in range(1, max(len(got), len(want))):
            line = got[number] if number < len(got) else None
            fixed = want[number] if number < len(want) else None
            if line != fixed:
                said.append(
                    f"the render of {name} differs from {NETWORK.name}'s configuration at its line {number + 1}:"
                    f" {json.dumps(line)}, where the blueprint holds {json.dumps(fixed)}"
                )
                break
    return said


def failed(error: subprocess.CalledProcessError) -> str:
    """A git command that failed, by its command line, its status and its words."""
    argv = error.cmd if isinstance(error.cmd, (list, tuple)) else [str(error.cmd)]
    words = " ".join(str(error.stderr or "").split()) or "no words"
    return f"{' '.join(str(part) for part in argv)} exited {error.returncode}: {words}"


def parser() -> argparse.ArgumentParser:
    made = argparse.ArgumentParser(
        prog="seed.py", description="The fixture network, its templates and Golden Config's setting on Nautobot."
    )
    made.add_argument("--files", type=Path, required=True, help="nautobot/seed: main.yaml, templates/, sotagg.graphql")
    made.add_argument("--git", type=Path, required=True, help="the directory the git service serves")
    return made


def main(
    argv: Sequence[str], *, transport: httpx.BaseTransport | None = None, git: Git | None = None
) -> int:
    """The seed run whole, as `make nautobot-seed` runs it, over `transport` and `git` where a test gives them."""
    try:
        args = parser().parse_args(argv)
    except SystemExit as e:
        return 0 if e.code in (0, None) else 2
    for name in (ADDRESS, TOKEN):
        if not os.environ.get(name):
            say(f"{name} is not set: load local/.env first", err=True)
            return 2
    try:
        fixture = load(args.files)
        network = configurations()
    except (OSError, ValueError, KeyError, yaml.YAMLError) as e:
        say(f"--files {args.files}: {e}", err=True)
        return 2
    try:
        commit = templates(git or command, args.git, args.files)
    except subprocess.CalledProcessError as e:
        say(failed(e), err=True)
        say(f"the seed deletes nothing: {PURGE}", err=True)
        return 1
    except OSError as e:
        say(f"git: {e}", err=True)
        return 1
    say(f"made {REPOSITORY} {commit}" if commit is not None else f"found {REPOSITORY}")
    try:
        box = Box(os.environ[ADDRESS], os.environ[TOKEN], transport=transport)
    except BoxError as e:
        say(f"{e}", err=True)
        return 1
    try:
        try:
            seed(box, args.files)
            said = differences(box, fixture)
        finally:
            for what, path, number in box.ensured:
                say(f"{what} {where(path)}{number}/")
        if not said:
            said = renders(box, network)
    except BoxError as e:
        say(f"{e}", err=True)
        say(f"the seed deletes nothing: {PURGE}", err=True)
        return 1
    except OSError as e:
        say(f"{e}", err=True)
        return 1
    finally:
        box.close()
    if said:
        for sentence in said:
            say(sentence, err=True)
        say(f"Nautobot is not the fixture, and the seed deletes nothing: {PURGE}", err=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
