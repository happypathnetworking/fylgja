"""The OSPF adjacency check: every device node of the bundle is an expected speaker, and every end of every link of the
bundle must hold a neighbour in state `full` (docs/superpowers/specs/2026-11-16-nornir-ospf-check-design.md, 6).

Each device is read twice over Nornir's asyncio runner, `COMMANDS`: the instance's oper-state, then the adjacencies.
The adjacency read answers `{}` both for a node with no OSPF and for one with no neighbour, so the first read tells
them apart (design/verified-facts.md, SR Linux, "OSPF point-to-point on /31s"). The read polls, since an adjacency
forms after the push and the step's verify waits for LLDP alone, and the last round's failures are the judgement.

The rules are the check's own, a `RULE_*` constant each, catalogued in orchestrator/rules.md, "Findings: the OSPF
check"; every one is an error. Nothing here logs or says a login."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nornir import AInitNornir
from nornir_scrapli.async_tasks import send_commands

from fylgja_orchestrator.nornir import inventory
from fylgja_orchestrator.rehearsal import StageCheck
from fylgja_orchestrator.rehearsal.documents import finding

RULE_NOT_FULL = "ospf.adjacency.not_full"
RULE_ABSENT = "ospf.instance.absent"
RULE_UNREAD = "ospf.node.unread"
RULE_NO_LINKS = "ospf.links.none"
SEVERITY: dict[str, str] = {rule: "error" for rule in (RULE_NOT_FULL, RULE_ABSENT, RULE_UNREAD, RULE_NO_LINKS)}

_STATE = "info from state network-instance default protocols ospf instance main"
COMMANDS: tuple[str, str] = (
    f"{_STATE} oper-state | as json",
    f"{_STATE} area * interface * neighbor * adjacency-state | as json",
)
FULL = "full"
POLL_S = 5.0


@dataclass(frozen=True)
class Unread:
    """A host whose read failed, timed out or was cancelled, with the reason its result gave."""

    reason: str


Answer = dict[str, str] | None | Unread


def expected(bundle: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Every link end of `bundle`, `(device, interface)`, both ends of each link, sorted."""
    return sorted((link[side]["device"], link[side]["interface"]) for link in bundle["links"] for side in ("a", "b"))


def _instances(text: str) -> list[dict[str, Any]]:
    """The OSPF instances of the default network-instance in one of SR Linux's JSON answers."""
    found = []
    for network in json.loads(text).get("network-instance", []):
        found.extend(network.get("protocols", {}).get("ospf", {}).get("instance", []))
    return found


def parse(oper_text: str, adjacency_text: str) -> dict[str, str] | None:
    """Interface → adjacency state from a device's two answers, the subinterface's `.0` dropped; `None` where the
    oper-state answer holds no instance. A port with more than one neighbour gives the state of one short of full,
    if any is."""
    if not _instances(oper_text):
        return None
    states: dict[str, str] = {}
    for instance in _instances(adjacency_text):
        for area in instance.get("area", []):
            for port in area.get("interface", []):
                name = str(port["interface-name"]).removesuffix(".0")
                for neighbour in port.get("neighbor", []):
                    state = str(neighbour.get("adjacency-state", "unknown"))
                    if states.get(name, FULL) == FULL:
                        states[name] = state
    return states


def judge(
    ends: Sequence[tuple[str, str]], devices: Iterable[str], answers: Mapping[str, Answer]
) -> list[dict[str, Any]]:
    """The failures of one round, sorted by object, the bundle's own (no object) first: one a device that runs no
    instance or was not read, its ends then not filed again; one a link end short of full; and one where there is no
    link at all."""
    failures: list[dict[str, Any]] = []
    if not ends:
        failures.append(
            finding(RULE_NO_LINKS, "error", "The bundle has no link, so there is no adjacency to judge.")
        )
    silent = set()
    for device in sorted(set(devices) | {device for device, _ in ends}):
        answer = answers.get(device, Unread("no result"))
        if isinstance(answer, Unread):
            silent.add(device)
            failures.append(
                finding(RULE_UNREAD, "error", f"{device}'s OSPF state could not be read: {answer.reason}.", device)
            )
        elif answer is None:
            silent.add(device)
            failures.append(finding(RULE_ABSENT, "error", f"{device} runs no OSPF instance.", device))
    for device, interface in ends:
        if device in silent:
            continue
        states = answers[device]
        assert isinstance(states, dict)
        state = states.get(interface)
        if state == FULL:
            continue
        message = (
            f"{device} has no neighbour on {interface}, where OSPF should be full."
            if state is None
            else f"{device}'s OSPF neighbour on {interface} is {state}, not full."
        )
        failures.append(finding(RULE_NOT_FULL, "error", message, f"{device}:{interface}"))
    return sorted(failures, key=lambda f: f.get("object", ""))


def _reason(e: BaseException) -> str:
    """An exception as a finding says it: its type, and its text where it has one; neither holds a login."""
    return f"{type(e).__name__}: {e}" if str(e) else type(e).__name__


def answered(result: Mapping[str, Any]) -> dict[str, Answer]:
    """Each host's two answers of one round, parsed: `Unread` where its result failed, timed out or was cancelled, or
    where an answer does not parse as SR Linux's JSON."""
    answers: dict[str, Answer] = {}
    for host, multi in result.items():
        if multi.failed:
            answers[host] = Unread(_reason(multi.exception) if multi.exception else "the device answered an error")
            continue
        # nornir_scrapli's Result subclass sets it; Nornir's Result type does not declare it.
        responses = multi[0].scrapli_response
        try:
            answers[host] = parse(responses[0].result, responses[1].result)
        except (ValueError, KeyError, TypeError, AttributeError, IndexError) as e:
            answers[host] = Unread(_reason(e))
    return answers


async def adjacencies(
    record: Mapping[str, Any],
    bundle: Mapping[str, Any],
    packages_dir: Path,
    environ: Mapping[str, str],
    *,
    timeout_s: float,
    poll_s: float = POLL_S,
    say: Callable[[str], None] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> list[dict[str, Any]]:
    """Read every device's OSPF state until every link end is full or `timeout_s` has passed; the last round's
    failures. Connections stay open across rounds and are closed at the end, failed hosts' included."""
    inventory.register()
    options = {"record": record, "bundle": bundle, "packages_dir": packages_dir, "environ": environ}
    runner = {"num_workers": 20, "per_host_timeout": poll_s * 4, "timeout": timeout_s}
    nr = await AInitNornir(
        inventory={"plugin": inventory.PLUGIN, "options": options},
        runner={"plugin": "asyncio", "options": runner},
        logging={"enabled": False},
    )
    ends, devices = expected(bundle), [node["name"] for node in bundle["nodes"]]
    started = clock()
    try:
        while True:
            result = await nr.arun(task=send_commands, commands=list(COMMANDS), on_failed=True)
            failures = judge(ends, devices, answered(result))
            short = {f["object"] for f in failures if f["rule"] == RULE_NOT_FULL}
            silent = {f.get("object") for f in failures if f["rule"] in (RULE_UNREAD, RULE_ABSENT)}
            full = sum(1 for device, port in ends if f"{device}:{port}" not in short and device not in silent)
            if say is not None:
                say(f"ospf: {full} of {len(ends)} link ends full")
            if not failures or clock() - started >= timeout_s:
                return failures
            await sleep(poll_s)
    finally:
        await nr.aclose_connections(on_good=True, on_failed=True)


def check(packages_dir: Path, environ: Mapping[str, str], *, say: Callable[[str], None] | None = None) -> StageCheck:
    """The rehearsal's stage check: `(record, bundle, timeout_s) -> failures`, the poll run to its end."""

    def run(record: Mapping[str, Any], bundle: Mapping[str, Any], timeout_s: float) -> list[dict[str, Any]]:
        try:
            return asyncio.run(adjacencies(record, bundle, packages_dir, environ, timeout_s=timeout_s, say=say))
        except Exception as e:
            # A check that cannot run (a login not set, a package not found, Nornir refusing the inventory) fails
            # every device as unread, so that the rehearsal ends in its document.
            devices = [node["name"] for node in bundle["nodes"]]
            unread = Unread(f"the check could not run: {_reason(e)}")
            return judge(expected(bundle), devices, dict.fromkeys(devices, unread))

    return run
