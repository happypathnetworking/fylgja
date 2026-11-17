"""A Nornir inventory of a twin: one host per device node of the bundle, at the management address the twin's record
gives the node (formats/twin-record-1.schema.json, `status.nodes`), its login the credential its platform package
names, read from the variables the core's credential provider reads, and its connection scrapli over asyncssh.

The record's probe hosts are not the bundle's nodes, so they are no hosts. A password is a host's field alone: Nornir's
`Host` repr is its name, and nothing here logs or prints one.

SR Linux's CLI asks the terminal for its cursor position and prints no prompt until it is answered, and scrapli's
asyncssh transport answers nothing (design/verified-facts.md, SR Linux, "OSPF point-to-point on /31s"); `on_open`
writes the answer before the platform's own on_open, and the connection's extras name it."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from nornir.core.inventory import ConnectionOptions, Defaults, Groups, Host, Hosts, Inventory
from nornir.core.plugins.inventory import CapabilityInventoryPluginRegister, InventoryCapability
from scrapli.driver import AsyncNetworkDriver
from scrapli_community.nokia.srlinux.async_driver import default_async_on_open

PLUGIN = "fylgja-twin"
# A platform package's id, the bundle node's `platform`, to the scrapli platform that drives it.
SCRAPLI_PLATFORM: dict[str, str] = {"nokia_srlinux": "nokia_srlinux"}
# The answer to the CLI's cursor-position query, `ESC[6n`: row 80, column 256.
CURSOR = "\x1b[80;256R"
TIMEOUT_OPS_S = 30


async def on_open(conn: AsyncNetworkDriver) -> None:
    """Answer SR Linux's cursor-position query, then open as the platform does."""
    conn.channel.write(channel_input=CURSOR)
    await default_async_on_open(conn)


def _login(packages_dir: Path, platform: str, environ: Mapping[str, str]) -> tuple[str, str]:
    """The username and password of the credential the platform package `platform` names."""
    package = yaml.safe_load((packages_dir / f"{platform}.yaml").read_text())
    name = str(package["credentials"]).upper().replace("-", "_")
    values = []
    for part in ("USERNAME", "PASSWORD"):
        variable = f"FYLGJA_CREDENTIAL_{name}_{part}"
        if not environ.get(variable):
            raise KeyError(f"{variable} is not set")
        values.append(environ[variable])
    return values[0], values[1]


def hosts(
    record: Mapping[str, Any], bundle: Mapping[str, Any], packages_dir: Path, environ: Mapping[str, str]
) -> Hosts:
    """One host per device node of `bundle`, at the address `record` gives it; a node with no address yet is none."""
    addresses = {node["name"]: node.get("address") for node in record["status"]["nodes"]}
    found = Hosts()
    for node in bundle["nodes"]:
        name, platform = node["name"], node["platform"]
        address = addresses.get(name)
        if not address:
            continue
        username, password = _login(packages_dir, platform, environ)
        extras = {"transport": "asyncssh", "auth_strict_key": False, "timeout_ops": TIMEOUT_OPS_S, "on_open": on_open}
        found[name] = Host(
            name=name,
            hostname=address,
            username=username,
            password=password,
            platform=SCRAPLI_PLATFORM[platform],
            data={"package": platform},
            connection_options={"scrapli": ConnectionOptions(extras=extras)},
        )
    return found


class TwinInventory:
    """The capability inventory plugin: the hosts of `hosts`, loaded on the asyncio runner."""

    def __init__(
        self, record: Mapping[str, Any], bundle: Mapping[str, Any], packages_dir: Path, environ: Mapping[str, str]
    ) -> None:
        self.record, self.bundle, self.packages_dir, self.environ = record, bundle, packages_dir, environ

    def get_capabilities(self) -> frozenset[InventoryCapability]:
        return frozenset({"asyncio"})

    async def aload(self) -> Inventory:
        return Inventory(
            hosts=hosts(self.record, self.bundle, self.packages_dir, self.environ), groups=Groups(), defaults=Defaults()
        )


def register() -> None:
    """Register `TwinInventory` as `PLUGIN`; the register itself ignores a second registration of the same class."""
    CapabilityInventoryPluginRegister.register(PLUGIN, TwinInventory)
