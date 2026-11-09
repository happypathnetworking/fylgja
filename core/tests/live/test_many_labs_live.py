"""Three twins created together on the local driver (D-074, D-075): `ml-1`, `ml-2` and `ml-3`,
each the `three-node` fixture planned by the driver, their three `apply`s run at once. The deploys
must run one after the other under the driver's lock, and every lab must run. The test prints what
the host showed meanwhile (its load and its established TCP connections, sampled every 2 s) and
asserts nothing about either: the readings go into design/verified-facts.md. Each twin is destroyed
at the end, whatever happened.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from fylgja_core import blueprint, compiler
from fylgja_core.containerlab.driver import DEPLOY_LOG, ContainerlabDriver
from fylgja_core.driver import Allocation, Inspection, Refusal

from .host import CLEAN, NEEDS_LOGINS, leftovers
from .test_containerlab_driver_live import NODES, PLATFORMS, PROBES, ROOT

pytestmark = NEEDS_LOGINS

TWINS = ("ml-1", "ml-2", "ml-3")
SAMPLE_S = 2.0
CLOCK = re.compile(r"\b(\d{2}):(\d{2}):(\d{2})\b")


def established() -> int | None:
    """The established TCP connections on the host, or None where `ss` is absent."""
    if shutil.which("ss") is None:
        return None
    out = subprocess.run(["ss", "-Htn", "state", "established"], capture_output=True, text=True, timeout=30)
    return len(out.stdout.splitlines())


async def sample(readings: list[tuple[float, float, int | None]], stop: asyncio.Event) -> None:
    while not stop.is_set():
        readings.append((time.monotonic(), os.getloadavg()[0], await asyncio.to_thread(established)))
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), SAMPLE_S)


def clock_times(log: Path) -> list[float]:
    """The seconds of the day each line of the deploy's log opens with, for the lines that open with one."""
    found: list[float] = []
    for line in log.read_text(errors="replace").splitlines():
        m = CLOCK.search(line[:40])
        if m:
            h, mi, s = map(int, m.groups())
            found.append(h * 3600 + mi * 60 + s)
    return found


def test_three_labs_applied_at_once_deploy_one_after_the_other_and_all_run(tmp_path: Path) -> None:
    driver = ContainerlabDriver(tmp_path / "driver-live")
    c = compiler.compile(blueprint.load(ROOT / "testdata/blueprint/three-node.json"), PLATFORMS, PROBES)
    allocations: dict[str, Allocation] = {}
    taken: list[Allocation] = []
    for twin in TWINS:
        got = asyncio.run(driver.admit(c.manifest, PLATFORMS, PROBES, twin, taken))
        assert not isinstance(got, Refusal), got
        allocations[twin] = got
        taken.append(got)
    planned = {t: driver.plan(c.manifest, c.id, PLATFORMS, PROBES, t, a) for t, a in allocations.items()}
    readings: list[tuple[float, float, int | None]] = []
    finished: dict[str, float] = {}
    try:
        for twin in TWINS:
            assert leftovers(twin) == CLEAN, f"the host holds {twin} already"

        async def one(twin: str) -> None:
            p = planned[twin]
            await driver.apply(p.deployment, p.files, PLATFORMS, PROBES)
            finished[twin] = time.monotonic()

        async def all_three() -> float:
            stop = asyncio.Event()
            sampler = asyncio.create_task(sample(readings, stop))
            start = time.monotonic()
            try:
                await asyncio.gather(*(one(t) for t in TWINS))
            finally:
                stop.set()
                await sampler
            return start

        start = asyncio.run(all_three())
        total = max(finished.values()) - start
        inspections = {t: asyncio.run(driver.inspect(t)) for t in TWINS}
        for twin, inspection in inspections.items():
            assert isinstance(inspection, Inspection) and inspection.state == "present", (twin, inspection)
            assert [n.name for n in inspection.nodes] == list(NODES) and all(n.running for n in inspection.nodes)
        order = sorted(TWINS, key=lambda t: finished[t])
        ends = [start, *(finished[t] for t in order)]
        print("\n[live] deploys in order: " + ", ".join(
            f"{t} {ends[i + 1] - ends[i]:.1f}s" for i, t in enumerate(order)))
        spans = []
        for twin in order:
            log = driver.root / "containerlab" / twin / DEPLOY_LOG
            times = clock_times(log)
            assert times, log.read_text(errors="replace")[:400]
            spans.append((times[0], times[-1]))
            print(f"[live] {twin} deploy.log first line {times[0]}, last timed line {times[-1]} (seconds of the day)")
        for (_, last), (first, _) in itertools.pairwise(spans):
            assert first >= last, spans  # the clock reads whole seconds: equal is a deploy beginning at once
        mtimes = [(driver.root / "containerlab" / t / DEPLOY_LOG).stat().st_mtime for t in order]
        assert mtimes == sorted(mtimes)
        loads = [load for _, load, _ in readings]
        conns = [n for _, _, n in readings if n is not None]
        print(f"[live] three labs: {total:.1f}s; load max {max(loads):.2f}; "
              f"established max {max(conns) if conns else None}"
              + ("" if conns else " (ss is absent)"))
        print(f"[live] {len(readings)} samples; load {[round(x, 1) for x in loads]}; established {conns}")
    finally:
        for twin in TWINS:
            try:
                p = planned[twin]
                asyncio.run(driver.destroy(p.deployment, p.files, PLATFORMS, PROBES))
            except Exception as e:
                print(f"\n[live] teardown: destroy {twin} failed: {e}")
    for twin in TWINS:
        assert leftovers(twin) == CLEAN, twin
