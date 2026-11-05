"""The gNMI reader: one Get of the conformance paths through pygnmi, faked here; never the network."""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess
import sys
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import grpc
import pytest
from pygnmi.client import gNMIException

from fylgja_core import gnmi, platform_package
from fylgja_core.credentials import Credential

PSP = Path(__file__).resolve().parents[2] / "psp"
SRLINUX = platform_package.load(PSP / "nokia_srlinux.yaml")
EOS = platform_package.load(PSP / "arista_eos.yaml")
CRED = Credential(username="admin", password="s3cret")

P1 = "/system/information"
P2 = "/interface[name=ethernet-1/1]/state"


@pytest.fixture(autouse=True)
def reads_end() -> Iterator[None]:
    """Every test's read threads end with it: a node still being read would be unreadable to the next test."""
    yield
    deadline = time.monotonic() + 10
    while gnmi._READING and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not gnmi._READING, "a read thread outlived its test"


class FakeClient:
    """A stand-in for `gNMIclient`: records its construction and answers `get` from a canned reply."""

    def __init__(self, reply: dict[str, Any] | Exception) -> None:
        self.reply = reply
        self.kwargs: dict[str, Any] = {}
        self.get_kwargs: dict[str, Any] = {}

    def factory(self, **kwargs: Any) -> FakeClient:
        self.kwargs = kwargs
        return self

    def __enter__(self) -> FakeClient:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def get(self, **kwargs: Any) -> dict[str, Any]:
        self.get_kwargs = kwargs
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def notification(*updates: tuple[str, Any], prefix: str = "") -> dict[str, Any]:
    return {"notification": [{"timestamp": 1, "prefix": prefix, "update": [{"path": p, "val": v} for p, v in updates]}]}


def read(fake: FakeClient, monkeypatch: pytest.MonkeyPatch, package: platform_package.PlatformPackage = SRLINUX) -> Any:
    monkeypatch.setattr(gnmi, "gNMIclient", fake.factory)
    return asyncio.run(gnmi.get("10.0.0.5", package, CRED, [P1, P2]))


def test_get_answers_each_path_asked_and_decodes_val(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeClient(
        notification(("system/information", {"version": "v1"}), ("interface[name=ethernet-1/1]/state", {"up": True}))
    )
    assert read(fake, monkeypatch) == {P1: {"version": "v1"}, P2: {"up": True}}
    assert fake.get_kwargs == {"path": [P1, P2], "encoding": "json_ietf"}


def test_get_matches_by_the_normalised_path_whatever_the_order(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeClient(
        notification(("/interface[name=ethernet-1/1]/state/", 2), ("/system/information", 1))
    )
    assert read(fake, monkeypatch) == {P1: 1, P2: 2}


def test_updates_at_no_path_asked_answer_nothing_whatever_their_count(monkeypatch: pytest.MonkeyPatch) -> None:
    # No positional reading: as many updates as paths, at other paths, are not the paths asked.
    fake = FakeClient(notification(("a", 1), ("b", 2)))
    assert read(fake, monkeypatch) == {}


def test_get_joins_the_notification_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeClient(notification(("information", 1), ("interface[name=ethernet-1/1]/state", 2), prefix="system"))
    assert read(fake, monkeypatch) == {P1: 1}


def test_get_leaves_an_unreported_path_out(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeClient(notification(("system/information", 1)))
    assert read(fake, monkeypatch) == {P1: 1}


def test_get_answers_nothing_for_an_empty_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    assert read(FakeClient({"notification": [{"timestamp": 1}]}), monkeypatch) == {}


@pytest.mark.parametrize(("package", "tls"), [(SRLINUX, True), (EOS, False)], ids=["srlinux", "eos"])
def test_get_sets_tls_options_and_target_by_the_package(
    monkeypatch: pytest.MonkeyPatch, package: platform_package.PlatformPackage, tls: bool
) -> None:
    fake = FakeClient(notification())
    read(fake, monkeypatch, package)
    assert package.gnmi.tls is tls
    assert fake.kwargs == {
        "target": ("10.0.0.5", package.gnmi.port),
        "username": "admin",
        "password": "s3cret",
        "insecure": not tls,
        "skip_verify": tls,
        "gnmi_timeout": gnmi.GNMI_TIMEOUT_S,
    }


class FakeRpcError(grpc.RpcError):  # type: ignore[misc]  # grpcio ships no stubs
    def code(self) -> grpc.StatusCode:
        return grpc.StatusCode.UNAVAILABLE

    def details(self) -> str:
        return "leaks s3cret"


def test_an_rpc_error_is_unreadable_naming_where_and_the_status_never_the_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(gnmi.Unreadable) as caught:
        read(FakeClient(FakeRpcError()), monkeypatch)
    assert caught.value.rule == "verify.node.unread"
    message = str(caught.value)
    assert "10.0.0.5:" + str(SRLINUX.gnmi.port) in message
    assert "UNAVAILABLE" in message
    assert "s3cret" not in message
    assert "s3cret" not in repr(caught.value)


def test_a_wrapped_rpc_error_reports_the_status_of_the_original(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(gnmi.Unreadable) as caught:
        read(FakeClient(gNMIException("failed s3cret", FakeRpcError())), monkeypatch)
    assert "UNAVAILABLE" in str(caught.value)
    assert "s3cret" not in str(caught.value)


def test_any_other_error_is_unreadable_by_its_type(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(gnmi.Unreadable) as caught:
        read(FakeClient(ConnectionRefusedError("s3cret")), monkeypatch)
    assert "ConnectionRefusedError" in str(caught.value)
    assert "s3cret" not in str(caught.value)


def test_an_ipv6_address_is_bracketed_in_the_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gnmi, "gNMIclient", FakeClient(TimeoutError()).factory)
    with pytest.raises(gnmi.Unreadable, match=r"\[fd00::5\]:"):
        asyncio.run(gnmi.get("fd00::5", SRLINUX, CRED, [P1]))


@pytest.mark.parametrize(
    ("value", "subpath", "expected"),
    [
        ({"state": {"system-name": "n2"}}, "state/system-name", "n2"),
        ({"system-name": "n2"}, "system-name", "n2"),
        ({"system-name": "n2"}, "state/system-name", None),
        ([{"state": {"system-name": "n2"}}], "state/system-name", "n2"),
        ([{"a": 1}, {"a": 2}], "a", None),
        ([], "a", None),
        ("scalar", "a", None),
        (None, "a", None),
        ({"openconfig-lldp:state": {"system-name": "s1"}}, "state/system-name", "s1"),
        ({"a:x": 1, "b:x": 2}, "x", None),
        ({"x": 1, "b:x": 2}, "x", 1),
    ],
    ids=["ceos", "srlinux-flat", "absent", "one-element-list", "two-elements", "empty-list", "scalar", "none",
         "ceos-prefixed", "two-modules", "unprefixed-first"],
)
def test_leaf(value: Any, subpath: str, expected: Any) -> None:
    assert gnmi.leaf(value, subpath) == expected


# The answers the nodes gave live, trimmed to the members verify reads (verified-facts.md,
# "gNMI" under SR Linux 24.7.1 and cEOS 4.32.0.2F).


def note(*updates: tuple[str, Any]) -> dict[str, Any]:
    """One notification as pygnmi 0.8.15 decodes it: no prefix, and no `update` member when
    the node has no value at the path."""
    found: dict[str, Any] = {"alias": None, "atomic": False, "prefix": None, "timestamp": 1}
    if updates:
        found["update"] = [{"path": p, "val": v} for p, v in updates]
    return found


SRL_HOST = "/system/name/host-name"
SRL_ENABLED = "/interface[name=ethernet-1/1]/admin-state"
SRL_NEIGHBOR = "/system/lldp/interface[name=ethernet-1/1]/neighbor"
SRL_TO_HOST = "/system/lldp/interface[name=ethernet-1/10]/neighbor"
SRL_ENTRY = {"chassis-id": "1A:BF:03:FF:00:00", "id": "1A:BF:03:FF:00:00", "port-id": "ethernet-1/1",
             "port-id-type": "INTERFACE_NAME", "system-name": "n2"}
SRL_REPLY = {"notification": [
    note(("srl_nokia-system:system/srl_nokia-system-name:name/host-name", "n1")),
    note(("srl_nokia-interfaces:interface[name=ethernet-1/1]/admin-state", "enable")),
    note(("srl_nokia-system:system/srl_nokia-lldp:lldp/interface[name=ethernet-1/1]", {"neighbor": [SRL_ENTRY]})),
    note(),  # a port cabled to a probe host, which speaks no LLDP
]}

EOS_HOST = "/system/state/hostname"
EOS_ENABLED = "/interfaces/interface[name=Ethernet1]/state/admin-status"
EOS_NEIGHBOR = "/lldp/interfaces/interface[name=Ethernet1]/neighbors/neighbor"
EOS_ENTRY_PATH = "lldp/interfaces/interface[name=Ethernet1]/neighbors/neighbor[id=1]"


def eos_entry(system_name: str, port_id: str, at: str = "1") -> dict[str, Any]:
    return {"openconfig-lldp:id": at, "openconfig-lldp:state": {
        "arista-lldp-augments:last-update-time": "1793777860", "chassis-id": "1a:c8:02:ff:00:00", "id": at,
        "port-id": port_id, "port-id-type": "INTERFACE_NAME", "system-name": system_name}}


EOS_REPLY = {"notification": [
    note(("system/state/hostname", "leaf-01")),
    note(("interfaces/interface[name=Ethernet1]/state/admin-status", "UP")),
    note((EOS_ENTRY_PATH, eos_entry("s1", "ethernet-1/1"))),
]}


def answer(reply: dict[str, Any], asked: list[str], monkeypatch: pytest.MonkeyPatch,
           package: platform_package.PlatformPackage = SRLINUX) -> Any:
    monkeypatch.setattr(gnmi, "gNMIclient", FakeClient(reply).factory)
    return asyncio.run(gnmi.get("10.0.0.5", package, CRED, asked))


def test_srlinux_s_answer_is_matched_with_its_module_prefixes_stripped_and_its_list_read_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked = [SRL_HOST, SRL_ENABLED, SRL_NEIGHBOR, SRL_TO_HOST]
    got = answer(SRL_REPLY, asked, monkeypatch)
    # The neighbour list came at the entry above the path asked, in `{"neighbor": [...]}`.
    assert got == {SRL_HOST: "n1", SRL_ENABLED: "enable", SRL_NEIGHBOR: [SRL_ENTRY]}
    assert gnmi.leaf(got[SRL_NEIGHBOR], SRLINUX.conformance.port.neighbor.system_name) == "n2"
    assert gnmi.leaf(got[SRL_NEIGHBOR], SRLINUX.conformance.port.neighbor.port_id) == "ethernet-1/1"


def test_ceos_s_list_is_collected_from_its_entries_their_members_left_as_answered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    got = answer(EOS_REPLY, [EOS_HOST, EOS_ENABLED, EOS_NEIGHBOR], monkeypatch, EOS)
    assert got == {EOS_HOST: "leaf-01", EOS_ENABLED: "UP", EOS_NEIGHBOR: [eos_entry("s1", "ethernet-1/1")]}
    assert gnmi.leaf(got[EOS_NEIGHBOR], EOS.conformance.port.neighbor.system_name) == "s1"
    assert gnmi.leaf(got[EOS_NEIGHBOR], EOS.conformance.port.neighbor.port_id) == "ethernet-1/1"


def test_two_entries_answered_are_two_entries_in_the_node_s_order(monkeypatch: pytest.MonkeyPatch) -> None:
    second = EOS_ENTRY_PATH.replace("[id=1]", "[id=2]")
    reply = {"notification": [note((EOS_ENTRY_PATH, eos_entry("s1", "ethernet-1/1")),
                                   (second, eos_entry("e2", "Ethernet1", "2")))]}
    got = answer(reply, [EOS_NEIGHBOR], monkeypatch, EOS)
    assert got == {EOS_NEIGHBOR: [eos_entry("s1", "ethernet-1/1"), eos_entry("e2", "Ethernet1", "2")]}
    assert gnmi.leaf(got[EOS_NEIGHBOR], "state/system-name") is None  # two neighbours: no one name


def test_updates_deeper_than_an_entry_are_collected_into_it_with_its_key(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = {"notification": [note((f"{EOS_ENTRY_PATH}/state/system-name", "s1"),
                                   (f"{EOS_ENTRY_PATH}/state/port-id", "ethernet-1/1"))]}
    got = answer(reply, [EOS_NEIGHBOR], monkeypatch, EOS)
    assert got == {EOS_NEIGHBOR: [{"state": {"system-name": "s1", "port-id": "ethernet-1/1"}, "id": "1"}]}


def test_an_update_above_a_path_reads_down_to_it_and_its_keyed_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    lldp = {"interface": [{"name": "ethernet-1/1", "neighbor": [SRL_ENTRY]}, {"name": "ethernet-1/2", "neighbor": []}]}
    reply = {"notification": [note(("srl_nokia-system:system/srl_nokia-lldp:lldp", lldp))]}
    other = SRL_NEIGHBOR.replace("1/1", "1/2")
    missing = SRL_NEIGHBOR.replace("1/1", "1/3")
    assert answer(reply, [SRL_NEIGHBOR, other, missing], monkeypatch) == {SRL_NEIGHBOR: [SRL_ENTRY], other: []}


def test_an_update_above_a_path_it_does_not_hold_leaves_the_path_out(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = {"notification": [
        note(("srl_nokia-system:system/srl_nokia-lldp:lldp/interface[name=ethernet-1/1]", {"admin-state": "enable"})),
        note(("srl_nokia-system:system/srl_nokia-system-name:name/host-name", "n1"))]}
    assert answer(reply, [SRL_NEIGHBOR, SRL_HOST], monkeypatch) == {SRL_HOST: "n1"}


def test_an_entry_of_another_key_is_not_the_path_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = {"notification": [note(("interfaces/interface[name=Ethernet2]/state/admin-status", "UP"),
                                   ("system/state/hostname", "e1"))]}
    assert answer(reply, [EOS_ENABLED, EOS_HOST], monkeypatch, EOS) == {EOS_HOST: "e1"}


@pytest.mark.parametrize(("package", "asked"), [
    (SRLINUX, [SRL_NEIGHBOR.replace("1/1", "1/3"), SRL_ENABLED.replace("1/1", "1/99")]),
    (EOS, [EOS_NEIGHBOR.replace("Ethernet1", "Ethernet10"), EOS_ENABLED.replace("Ethernet1", "Ethernet99")]),
], ids=["srlinux", "eos"])
def test_an_absent_value_is_a_notification_with_no_update_and_left_out(
    monkeypatch: pytest.MonkeyPatch, package: platform_package.PlatformPackage, asked: list[str]
) -> None:
    assert answer({"notification": [note(), note()]}, asked, monkeypatch, package) == {}


def test_pygnmi_s_own_log_reaches_neither_stream_nor_the_root(capsys: pytest.CaptureFixture[str]) -> None:
    log = logging.getLogger("pygnmi.client")
    assert not log.propagate
    assert not any(type(h) is logging.StreamHandler for h in log.handlers)  # pygnmi's own, to stdout
    log.critical("GRPC ERROR Host: 10.0.0.5:57400, Error: s3cret")
    assert capsys.readouterr() == ("", "")


class StuckClient(FakeClient):
    """A client whose Get answers only once released, as a node that never answers holds it."""

    def __init__(self) -> None:
        super().__init__({})
        self.release = threading.Event()

    def get(self, **kwargs: Any) -> dict[str, Any]:
        self.release.wait(timeout=10)
        return {}


def test_a_read_that_never_ends_is_unreadable_within_its_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    stuck = StuckClient()
    monkeypatch.setattr(gnmi, "gNMIclient", stuck.factory)

    async def read() -> None:
        try:
            await gnmi.get("10.0.0.5", SRLINUX, CRED, [P1], timeout_s=0.2)
        finally:
            stuck.release.set()  # let the thread end, so the loop can close

    start = time.monotonic()
    with pytest.raises(gnmi.Unreadable, match="TimeoutError"):
        asyncio.run(read())
    assert time.monotonic() - start < 5


def test_a_stuck_read_delays_no_other_node_s_read_and_takes_none_of_the_loop_s_threads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stuck, answering = StuckClient(), FakeClient(notification((P1, 1)))

    def factory(**kwargs: Any) -> FakeClient:
        return (stuck if kwargs["target"][0] == "10.0.0.5" else answering).factory(**kwargs)

    monkeypatch.setattr(gnmi, "gNMIclient", factory)

    async def reads() -> tuple[Any, float]:
        # One thread in the loop's own executor: a read held on it would hold the next read too.
        asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=1))
        held = asyncio.ensure_future(gnmi.get("10.0.0.5", SRLINUX, CRED, [P1], timeout_s=5))
        try:
            await asyncio.sleep(0.05)  # the stuck read is in its thread
            start = time.monotonic()
            answer = await gnmi.get("10.0.0.6", SRLINUX, CRED, [P1], timeout_s=1)
            return answer, time.monotonic() - start
        finally:
            stuck.release.set()
            await asyncio.gather(held, return_exceptions=True)

    answer, took = asyncio.run(reads())
    assert answer == {P1: 1} and took < 1


def test_a_read_abandoned_at_its_budget_does_not_hold_the_loop_s_close(monkeypatch: pytest.MonkeyPatch) -> None:
    stuck = StuckClient()
    monkeypatch.setattr(gnmi, "gNMIclient", stuck.factory)
    try:
        start = time.monotonic()
        with pytest.raises(gnmi.Unreadable, match="TimeoutError"):
            asyncio.run(gnmi.get("10.0.0.5", SRLINUX, CRED, [P1], timeout_s=0.05))
        assert time.monotonic() - start < 1  # the loop closed with the read still held in its thread
        assert "10.0.0.5" in gnmi._READING
    finally:
        stuck.release.set()


def test_a_node_whose_last_read_still_runs_is_unreadable_at_once_until_that_read_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stuck = StuckClient()
    monkeypatch.setattr(gnmi, "gNMIclient", stuck.factory)

    async def reads() -> float:
        with pytest.raises(gnmi.Unreadable, match="TimeoutError"):
            await gnmi.get("10.0.0.5", SRLINUX, CRED, [P1], timeout_s=0.05)  # abandoned: its thread runs on
        start = time.monotonic()
        with pytest.raises(gnmi.Unreadable, match=re.escape("10.0.0.5:57400 unreadable over gNMI: a read of this "
                                                            "node is still running")):
            await gnmi.get("10.0.0.5", SRLINUX, CRED, [P1], timeout_s=5)
        return time.monotonic() - start

    try:
        assert asyncio.run(reads()) < 0.1
    finally:
        stuck.release.set()
    deadline = time.monotonic() + 5
    while gnmi._READING and time.monotonic() < deadline:  # the stuck read returns, and frees the node
        time.sleep(0.01)
    monkeypatch.setattr(gnmi, "gNMIclient", FakeClient(notification((P1, 1))).factory)
    assert asyncio.run(gnmi.get("10.0.0.5", SRLINUX, CRED, [P1], timeout_s=1)) == {P1: 1}


def test_a_read_finding_every_thread_busy_waits_out_its_budget_and_a_returned_read_frees_its_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stuck, answering = StuckClient(), FakeClient(notification((P1, 1)))

    def factory(**kwargs: Any) -> FakeClient:
        return (answering if kwargs["target"][0] == "10.0.0.7" else stuck).factory(**kwargs)

    monkeypatch.setattr(gnmi, "gNMIclient", factory)
    monkeypatch.setattr(gnmi, "_SLOTS", threading.BoundedSemaphore(2))

    async def reads() -> float:
        for address in ("10.0.0.5", "10.0.0.6"):  # both threads held by nodes that never answer
            with pytest.raises(gnmi.Unreadable, match="TimeoutError"):
                await gnmi.get(address, SRLINUX, CRED, [P1], timeout_s=0.05)
        start = time.monotonic()
        busy = re.escape("10.0.0.7:57400 unreadable over gNMI: no read thread free")
        with pytest.raises(gnmi.Unreadable, match=busy):
            await gnmi.get("10.0.0.7", SRLINUX, CRED, [P1], timeout_s=0.2)
        return time.monotonic() - start

    try:
        assert 0.2 <= asyncio.run(reads()) < 1
        assert "10.0.0.7" not in gnmi._READING  # a read that never had a thread holds no node
    finally:
        stuck.release.set()

    async def again() -> dict[str, Any]:  # the stuck reads return: their threads are free again
        return await gnmi.get("10.0.0.7", SRLINUX, CRED, [P1], timeout_s=2)

    assert asyncio.run(again()) == {P1: 1}


EXITS = """
import asyncio, sys, threading
from pathlib import Path
from fylgja_core import gnmi, platform_package
from fylgja_core.credentials import Credential

class Stuck:
    def __init__(self, **kwargs): pass
    def __enter__(self): return self
    def __exit__(self, *exc): return None
    def get(self, **kwargs):
        threading.Event().wait(60)  # a node that never answers
        return {}

gnmi.gNMIclient = Stuck
package = platform_package.load(Path(sys.argv[1]))
try:
    asyncio.run(gnmi.get("10.0.0.5", package, Credential(username="u", password="p"), ["/x"], timeout_s=0.05))
except gnmi.Unreadable as e:
    print(e.what)
"""


def test_a_read_abandoned_at_its_budget_does_not_hold_the_interpreter_s_exit() -> None:
    start = time.monotonic()
    done = subprocess.run([sys.executable, "-c", EXITS, str(PSP / "nokia_srlinux.yaml")], capture_output=True,
                          text=True, timeout=30, check=False)
    assert (done.returncode, done.stdout, done.stderr) == (0, "TimeoutError\n", "")
    assert time.monotonic() - start < 15  # the process's start-up, not the read's 60 s


@pytest.mark.parametrize("held", [{"admin-state": "enable"}, {}], ids=["another-member", "empty"])
def test_one_path_asked_and_one_update_above_it_without_the_member_is_left_out(
    monkeypatch: pytest.MonkeyPatch, held: dict[str, Any]
) -> None:
    reply = {"notification": [note(("srl_nokia-system:system/srl_nokia-lldp:lldp/interface[name=ethernet-1/1]", held))]}
    assert answer(reply, [SRL_NEIGHBOR], monkeypatch) == {}


VRFS = {"vrf": [{"name": "my vrf", "type": "default"}, {"name": "myvrf", "type": "ip-vrf"}]}


@pytest.mark.parametrize("asked", ["/system/vrf[name=my vrf]/type", '/system/vrf[name="my vrf"]/type',
                                   "/system/vrf[name='my vrf']/type", "/system/vrf[ name = my vrf ]/type"],
                         ids=["bare", "double-quoted", "single-quoted", "spaced"])
def test_a_key_value_with_a_space_is_compared_like_with_like(monkeypatch: pytest.MonkeyPatch, asked: str) -> None:
    above = {"notification": [note(("srl_nokia-system:system", VRFS))]}
    assert answer(above, [asked], monkeypatch) == {asked: "default"}
    at = {"notification": [note(("srl_nokia-system:system/vrf[name=my vrf]/type", "default"),
                                ("srl_nokia-system:system/vrf[name=myvrf]/type", "ip-vrf"))]}
    assert answer(at, [asked], monkeypatch) == {asked: "default"}


@pytest.mark.parametrize("updates", [
    ((EOS_ENTRY_PATH.removesuffix("[id=1]"), {}), (EOS_ENTRY_PATH, eos_entry("s1", "ethernet-1/1"))),
    ((EOS_ENTRY_PATH, eos_entry("s1", "ethernet-1/1")), (f"{EOS_ENTRY_PATH.removesuffix('[id=1]')}/state", {})),
], ids=["an-object-then-an-entry", "an-entry-then-an-unkeyed-child"])
def test_an_answer_the_reader_cannot_map_is_unreadable(
    monkeypatch: pytest.MonkeyPatch, updates: tuple[tuple[str, Any], ...]
) -> None:
    with pytest.raises(gnmi.Unreadable, match=r"the answer could not be read \((AttributeError|TypeError)\)"):
        answer({"notification": [note(*updates)]}, [EOS_NEIGHBOR], monkeypatch, EOS)
