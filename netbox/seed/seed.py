"""The fixture network on the development NetBox's `main`, its configuration template and the probes' context.

Run by `make netbox-seed` as `core/.venv/bin/python netbox/seed/seed.py --files netbox/seed`, with `local/.env`
loaded for `FYLGJA_NETBOX_ADDRESS` and the superuser's `FYLGJA_NETBOX_WRITE_TOKEN` (CONTRIBUTING.md, D-042):

- every object `files`/`main.yaml` says is found on `main` by its name, a device type by its model, an interface by
  its device and its name, an address by its value and its interface, and a cable by its first end; or made, in the
  order a later one needs an earlier one's id: the manufacturer, the template `files`/`template.j2`, the platform
  naming both, the device type, the site, the role, the tag, the devices, their interfaces, the addresses on them,
  the cables, and last the configuration context of the probes, inactive, so that no device's rendered context takes
  it;
- of an object found, the template's code, the platform's template, and the context's data and state are written
  again where they differ, and nothing else of it is touched. NetBox keeps a template's code with its surrounding
  whitespace stripped (design/verified-facts.md, "NetBox 4.7.5 with netbox-branching 1.2.3"), so the code is sent
  and compared stripped, and a second seed writes nothing;
- a port of the fixture's cables that is cabled to another port than the fixture's is refused, naming both, before
  any cable is made;
- then `main` is read back, the devices tagged `TAG` with their ports, addresses and cables, and each difference from
  the fixture is said: a cable or an address that a merged change left, a device tagged by hand. Nothing is ever
  deleted: `make netbox-down PURGE=1` and the two targets after it, `local/.env` loaded again before the seed, make
  `main` the fixture again.

It prints one line an object, `made` or `found` and its path. Exit 0; 1 for a refusal, a failure or a difference,
each said on stderr with the remedy for what failed where one is known (`remedy`); 2 for a command line not
understood or a variable not set.

Run by `core/.venv/bin/python`; httpx, PyYAML and the standard library alone, never `fylgja_core`, a reader, the
example or a client library of NetBox's.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx
import yaml
from box import ADDRESS, TOKEN, Box, BoxError, Unfit, where

FIXTURE = "main.yaml"
"""The fixture network, under `--files`: the one file that holds its addresses."""

TEMPLATE = "template.j2"
"""The configuration template NetBox renders each device with, under `--files`."""

TAG = "fylgja"
"""The tag whose devices are the scope."""

SCOPE = "tag:fylgja"
"""The scope the seeded network is read in: the devices tagged `TAG`."""

PURGE = "make netbox-down PURGE=1, then make netbox-up, then load local/.env again and run make netbox-seed"
"""The remedy where `main` is the matter, since the seed deletes nothing. `make netbox-up` replaces the write token's
line after a purge, so a shell loaded before it holds a token the new instance refuses."""

UP = (
    "make netbox-up starts NetBox where it is stopped and reads that it is this NetBox; then load local/.env again"
    " and run make netbox-seed"
)
"""The remedy where NetBox answered nothing, or nothing a NetBox would: `main` is not the matter."""

RELOAD = (
    "load local/.env again, whose FYLGJA_NETBOX_WRITE_TOKEN line make netbox-up writes, and run make netbox-seed;"
    " where NetBox refuses it still, run make netbox-up, which provisions a refused token again without a purge, about"
    " 74 s on kept volumes, then load local/.env again and run make netbox-seed; only where NetBox refuses it after"
    f" that, {PURGE}"
)
"""The remedy where NetBox refused the write token, 401 or 403: the superuser's token is refused nothing, so the one
sent is not the superuser's NetBox holds, as a shell loaded before `make netbox-up` wrote the line again holds. Where
the line loaded is refused too, `make netbox-up` provisions the token again and writes its line, with no purge
(CONTRIBUTING.md, "make netbox-up"), so the purge is named only as what remains."""

INTERFACE = "dcim.interface"

RELATED = ("config_template",)
"""The members the seed writes again that name another object: NetBox answers each as a row, and is sent its id."""


class NotFixture(BoxError):
    """`main` refused for what it holds, which the seed deletes nothing of: a fixture port cabled elsewhere."""


def say(line: str, *, err: bool = False) -> None:
    print(f"seed: {line}" if err else line, file=sys.stderr if err else sys.stdout, flush=True)


def load(files: Path) -> dict[str, Any]:
    """The fixture network `files`/`FIXTURE`."""
    loaded = yaml.safe_load((files / FIXTURE).read_text())
    if not isinstance(loaded, dict):
        raise ValueError(f"{files / FIXTURE} holds no mapping")
    return loaded


def end(text: str) -> tuple[str, str]:
    """A cable's end, `<device>:<port>`, as its device and its port."""
    device, _, port = text.partition(":")
    return device, port


def named(row: Mapping[str, Any]) -> str:
    """A port, as a row of NetBox's refers to it, as its device and its name."""
    device = row.get("device") or {}
    return f"{device.get('name')} {row.get('name')}"


def standing(row: Mapping[str, Any], name: str) -> object:
    """The member `name` of `row` as it is compared to what a body sends: a related object, which NetBox answers as a
    row of it and is sent as its id, by its id."""
    value = row.get(name)
    return value.get("id") if name in RELATED and isinstance(value, dict) else value


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


def seed(box: Box, files: Path) -> None:
    """The fixture `files`/`FIXTURE` on `main`, found or made; a `BoxError` where NetBox refuses, and a `NotFixture`
    where a fixture port is cabled elsewhere."""
    fixture = load(files)
    code = (files / TEMPLATE).read_text().strip()

    manufacturer = ensured(
        box, "dcim/manufacturers/", {"name": fixture["manufacturer"]["name"]}, fixture["manufacturer"]
    )
    template = ensured(
        box,
        "extras/config-templates/",
        {"name": fixture["template"]},
        {"name": fixture["template"], "template_code": code},
        {"template_code": code},
    )
    platform = ensured(
        box,
        "dcim/platforms/",
        {"name": fixture["platform"]["name"]},
        {**fixture["platform"], "manufacturer": manufacturer["id"], "config_template": template["id"]},
        {"config_template": template["id"]},
    )
    device_type = ensured(
        box,
        "dcim/device-types/",
        {"model": fixture["device_type"]["model"]},
        {**fixture["device_type"], "manufacturer": manufacturer["id"]},
    )
    site = ensured(box, "dcim/sites/", {"name": fixture["site"]["name"]}, {**fixture["site"], "status": "active"})
    role = ensured(box, "dcim/device-roles/", {"name": fixture["role"]["name"]}, fixture["role"])
    tag = ensured(box, "extras/tags/", {"name": fixture["tag"]["name"]}, fixture["tag"])

    devices: dict[str, dict[str, Any]] = {}
    for device in fixture["devices"]:
        devices[device["name"]] = ensured(
            box,
            "dcim/devices/",
            {"name": device["name"]},
            {
                "name": device["name"],
                "device_type": device_type["id"],
                "role": role["id"],
                "site": site["id"],
                "platform": platform["id"],
                "status": "active",
                "tags": [tag["id"]],
                "description": device["description"],
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
                },
            )
    for device in fixture["devices"]:
        for port in device["interfaces"]:
            number = ports[(device["name"], port["name"])]["id"]
            for address in port["addresses"]:
                ensured(
                    box,
                    "ipam/ip-addresses/",
                    {"address": address, "interface_id": number},
                    {
                        "address": address,
                        "status": "active",
                        "assigned_object_type": INTERFACE,
                        "assigned_object_id": number,
                    },
                )

    cables = [(end(a), end(b)) for a, b in fixture["cables"]]
    for a, b in cables:
        for here, there in ((a, b), (b, a)):
            row = ports[here]
            peers = [named(peer) for peer in row.get("link_peers") or []]
            if row.get("cable") is not None and peers != [" ".join(there)]:
                far = " and ".join(peers) or "no port"
                raise NotFixture(
                    f"{' '.join(here)} is cabled to {far} on main, where the fixture cables it to {' '.join(there)}"
                )
    for a, b in cables:
        ensured(
            box,
            "dcim/cables/",
            {"interface_id": ports[a]["id"]},
            {
                "a_terminations": [{"object_type": INTERFACE, "object_id": ports[a]["id"]}],
                "b_terminations": [{"object_type": INTERFACE, "object_id": ports[b]["id"]}],
                "status": "connected",
            },
        )

    probes = fixture["probes"]
    ensured(
        box,
        "extras/config-contexts/",
        {"name": probes["name"]},
        {"name": probes["name"], "data": probes["data"], "is_active": False},
        {"data": probes["data"], "is_active": False},
    )


def cabled(row: Mapping[str, Any]) -> frozenset[str]:
    """A cable's ends, each `<device>:<port>`, as NetBox's row of the cable names them."""
    terminations = [*(row.get("a_terminations") or []), *(row.get("b_terminations") or [])]
    found = set()
    for termination in terminations:
        held = termination.get("object") or {}
        found.add(f"{(held.get('device') or {}).get('name')}:{held.get('name')}")
    return frozenset(found)


def joined(ends: frozenset[str]) -> str:
    return " to ".join(sorted(ends))


def differences(box: Box, fixture: Mapping[str, Any]) -> list[str]:
    """How `main` differs from `fixture`, each difference one sentence: the devices tagged `TAG`, their platform, each
    one's interfaces with `mgmt_only` and `enabled`, the addresses on them, and the cables among them as pairs of
    ends. `[]` where `main` is the fixture."""
    found: list[str] = []
    wanted = {device["name"]: device for device in fixture["devices"]}
    rows: dict[str, list[dict[str, Any]]] = {}
    for row in box.listed("dcim/devices/", tag=TAG):
        rows.setdefault(str(row.get("name")), []).append(row)
    for name in sorted(wanted.keys() - rows.keys()):
        found.append(f"main holds no device {name} tagged {TAG}")
    for name in sorted(rows.keys() - wanted.keys()):
        found.append(f"main holds the device {name} tagged {TAG}, which the fixture does not")
    for name in sorted(name for name, held in rows.items() if len(held) > 1):
        found.append(f"main holds {len(rows[name])} devices named {name} tagged {TAG}")

    platform = fixture["platform"]["name"]
    addresses: set[tuple[str, str, str]] = set()
    expected: set[tuple[str, str, str]] = set()
    cables: dict[int, frozenset[str]] = {}
    for name in sorted(wanted.keys() & rows.keys()):
        device = rows[name][0]
        on = (device.get("platform") or {}).get("name")
        if on != platform:
            found.append(f"the device {name} is on the platform {on}, where the fixture's is {platform}")
        ports = {str(row.get("name")): row for row in box.listed("dcim/interfaces/", device_id=device["id"])}
        fixed = {port["name"]: port for port in wanted[name]["interfaces"]}
        for port in sorted(fixed.keys() - ports.keys()):
            found.append(f"main holds no port {name} {port}")
        for port in sorted(ports.keys() - fixed.keys()):
            found.append(f"main holds the port {name} {port}, which the fixture does not")
        for port in sorted(fixed.keys() & ports.keys()):
            held, fixed_mgmt = ports[port].get("mgmt_only"), fixed[port]["mgmt_only"]
            if held is not fixed_mgmt:
                found.append(f"the port {name} {port} has mgmt_only {held}, where the fixture has {fixed_mgmt}")
            if ports[port].get("enabled") is not True:
                found.append(f"the port {name} {port} is not enabled, where the fixture enables it")
            expected.update((name, port, address) for address in fixed[port]["addresses"])
        for row in box.listed("ipam/ip-addresses/", device_id=device["id"]):
            held = row.get("assigned_object") or {}
            addresses.add((name, str(held.get("name")), str(row.get("address"))))
        for row in box.listed("dcim/cables/", device_id=device["id"]):
            cables[int(row["id"])] = cabled(row)

    for name, port, address in sorted(expected - addresses):
        found.append(f"main holds no address {address} on {name} {port}")
    for name, port, address in sorted(addresses - expected):
        found.append(f"main holds the address {address} on {name} {port}, which the fixture does not")
    fixed_cables = {frozenset(cable) for cable in fixture["cables"]}
    held_cables = set(cables.values())
    for ends in sorted(fixed_cables - held_cables, key=joined):
        found.append(f"main holds no cable {joined(ends)}")
    for ends in sorted(held_cables - fixed_cables, key=joined):
        found.append(f"main holds the cable {joined(ends)}, which the fixture does not")
    for ends in sorted(held_cables, key=joined):
        count = sum(1 for held in cables.values() if held == ends)
        if count > 1:
            found.append(f"main holds {count} cables {joined(ends)}, where the fixture holds one at most")
    return found


def remedy(error: BoxError) -> str | None:
    """What to do after `error`, said for what failed: the purge where `main` is the matter, `local/.env` loaded again
    where NetBox refused the write token, `make netbox-up` where NetBox answered no status, and None for an `Unfit`,
    an answer of NetBox's own that will not do, and for any other status, where no remedy is known."""
    if isinstance(error, NotFixture):
        return f"main is not the fixture, and the seed deletes nothing: {PURGE}"
    if isinstance(error, Unfit):
        return None
    if error.status in (401, 403):
        return RELOAD
    if error.status is None:
        return UP
    return None


def parser() -> argparse.ArgumentParser:
    made = argparse.ArgumentParser(prog="seed.py", description="The fixture network on the development NetBox's main.")
    made.add_argument("--files", type=Path, required=True, help="netbox/seed: main.yaml and template.j2")
    return made


def main(argv: Sequence[str], *, transport: httpx.BaseTransport | None = None) -> int:
    """The seed run whole, as `make netbox-seed` runs it, over `transport` where a test gives one."""
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
    except (OSError, ValueError, yaml.YAMLError) as e:
        say(f"--files {args.files}: {e}", err=True)
        return 2
    try:
        box = Box(os.environ[ADDRESS], os.environ[TOKEN], transport=transport)
    except BoxError as e:
        say(f"{e}", err=True)
        return 1
    try:
        try:
            seed(box, args.files)
            found = differences(box, fixture)
        finally:
            for what, path, number in box.ensured:
                say(f"{what} {where(path)}{number}/")
    except BoxError as e:
        say(f"{e}", err=True)
        if (said := remedy(e)) is not None:
            say(said, err=True)
        return 1
    except OSError as e:
        say(f"{e}", err=True)
        return 1
    finally:
        box.close()
    if found:
        for sentence in found:
            say(sentence, err=True)
        say(f"main is not the fixture, and the seed deletes nothing: {PURGE}", err=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
