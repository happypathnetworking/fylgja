"""The Nornir inventory of a twin: one host per device node of the bundle at the record's management address, its
login the package's credential read from the environment, its connection scrapli over asyncssh with the on_open that
answers SR Linux's cursor-position query."""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import pytest

from fylgja_orchestrator.nornir import inventory
from fylgja_orchestrator.nornir.inventory import SCRAPLI_PLATFORM, TwinInventory, hosts

ROOT = Path(__file__).resolve().parents[3]

RECORD = {
    "status": {
        "nodes": [
            {"name": "n1", "handle": "clab-n1", "address": "192.0.2.11"},
            {"name": "n2", "handle": "clab-n2", "address": "192.0.2.12"},
            {"name": "n1-loop-a", "handle": "clab-n1-loop-a", "address": "192.0.2.21"},
        ]
    }
}
BUNDLE = {
    "nodes": [{"name": "n1", "platform": "nokia_srlinux"}, {"name": "n2", "platform": "nokia_srlinux"}],
    "links": [{"a": {"device": "n1", "interface": "ethernet-1/1"}, "b": {"device": "n2", "interface": "ethernet-1/1"}}],
}
ENV = {"FYLGJA_CREDENTIAL_SRLINUX_USERNAME": "admin", "FYLGJA_CREDENTIAL_SRLINUX_PASSWORD": "s3cret"}


def test_one_host_per_device_node_at_its_address() -> None:
    found = hosts(RECORD, BUNDLE, ROOT / "psp", ENV)
    assert sorted(found) == ["n1", "n2"]
    assert found["n1"].hostname == "192.0.2.11"


def test_the_login_is_the_packages_credential_read_from_the_environment() -> None:
    h = hosts(RECORD, BUNDLE, ROOT / "psp", ENV)["n1"]
    assert (h.username, h.password) == ("admin", "s3cret")
    assert "s3cret" not in repr(h)  # Nornir's Host repr is its name; this pins that no one changes it


def test_the_connection_is_scrapli_over_asyncssh_with_strict_keys_off() -> None:
    h = hosts(RECORD, BUNDLE, ROOT / "psp", ENV)["n1"]
    assert h.platform == SCRAPLI_PLATFORM["nokia_srlinux"] == "nokia_srlinux"
    extras = h.connection_options["scrapli"].extras
    assert extras is not None
    assert extras["transport"] == "asyncssh" and extras["auth_strict_key"] is False
    assert extras["timeout_ops"] == 30
    assert extras["on_open"] is inventory.on_open


def test_on_open_answers_the_cursor_query_before_the_platforms_own(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[object] = []

    class Channel:
        def write(self, channel_input: str) -> None:
            calls.append(channel_input)

    class Conn:
        channel = Channel()

    async def platform(conn: object) -> None:
        calls.append("platform")

    monkeypatch.setattr(inventory, "default_async_on_open", platform)
    asyncio.run(inventory.on_open(Conn()))  # type: ignore[arg-type]
    assert calls == ["\x1b[80;256R", "platform"]


def test_the_plugin_declares_asyncio_and_loads_the_same_hosts() -> None:
    plugin = TwinInventory(RECORD, BUNDLE, ROOT / "psp", ENV)
    assert plugin.get_capabilities() == frozenset({"asyncio"})
    assert inspect.iscoroutinefunction(plugin.aload)
    loaded = asyncio.run(plugin.aload())
    assert sorted(loaded.hosts) == ["n1", "n2"]


def test_register_is_idempotent() -> None:
    inventory.register()
    inventory.register()


def test_ainit_nornir_loads_the_registered_plugin_by_name() -> None:
    from nornir import AInitNornir

    inventory.register()
    options = {"record": RECORD, "bundle": BUNDLE, "packages_dir": ROOT / "psp", "environ": ENV}

    async def init() -> list[str]:
        nr = await AInitNornir(
            inventory={"plugin": inventory.PLUGIN, "options": options},
            runner={"plugin": "asyncio", "options": {"num_workers": 2}},
            logging={"enabled": False},
        )
        return sorted(nr.inventory.hosts)

    assert asyncio.run(init()) == ["n1", "n2"]
