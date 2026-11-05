"""Phase 4's done criterion (design/core.md, "Phase 4"): the `three-node` fixture end to end
through API 1 and the thin CLI, on the local containerlab driver, with the server killed at
every phase boundary of a create, during the deploy and during a destroy, and resumed each time
to the state asked for; and a deletion asked during the deploy.

The harness is `e2e.py`'s, shared with the step module: `fylgja-core-server` as a subprocess
over a store in a temporary directory, with a token it makes for the principal `e2e`, and
`restart()` killing it with SIGKILL and starting it again the same way; the CLI in-process
through `cli.main`, each call within a deadline. The tests run in order and share the server;
each prints what it took and what it saw, and removes its twin however it ends. At the module's
end every twin left is destroyed through the API, and any twin whose lab is still on the host is
torn down by containerlab, so the host is left clean whatever happened; the module fails if it
is not.

No assertion here shows a secret when it fails: the token and the environment the server is
started with (every node login) are kept out of `Core`'s repr and out of every frame's
arguments, and the log checks report line numbers, never lines.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from e2e import (
    BLUEPRINT,
    CLEAN,
    DEADLINE_S,
    NEEDS_LOGINS,
    NODES,
    ROOT,
    Core,
    Fylgja,
    assert_events_whole,
    assert_log_clean,
    cli,
    containerlab_processes,
    created_until,
    gone,
    leftovers,
    ready,
    reconfigures,
    remove,
    serve,
    settled_ready,
    started,
    wait_for,
)

from fylgja_core import node_http, platform_package, schemas
from fylgja_core.credentials import Provider
from fylgja_core.push import post

SRLINUX = platform_package.load(ROOT / "psp" / "nokia_srlinux.yaml")
KILL_AT = ("compiled", "admitted", "planned", "applied", "ready", "pushed")
CREATE_PHASES = {"compile", "admit", "plan", "apply", "ready", "push"}
TWINS = ("e2e", "e2e-kill", "e2e-kill2", "e2e-kill3", "e2e-del")
"""Every twin the module makes, for the teardown's last look at the host."""

pytestmark = NEEDS_LOGINS


@pytest.fixture(scope="module")
def core(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Core]:
    yield from serve(tmp_path_factory, TWINS)


@pytest.fixture
def fylgja(core: Core, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> Fylgja:
    return cli(core, monkeypatch, capsys)


def host_name(address: str) -> str:
    """The node's host name, read through its own push transport: a JSON-RPC `cli` request."""
    body = {"jsonrpc": "2.0", "id": 1, "method": "cli",
            "params": {"commands": ["info from running / system name host-name"], "output-format": "text"}}
    credential = Provider(os.environ).login(SRLINUX.credentials)  # its repr hides the password

    async def ask() -> dict[str, Any]:
        async with node_http.client() as client:
            url = node_http.url(address, SRLINUX.push.port, "/jsonrpc")
            return await post(client, url, body, credential, timeout_s=SRLINUX.push.timeout_s)

    answer = asyncio.run(ask())
    assert "error" not in answer, answer
    entries = answer["result"]
    print(f"[e2e] {address}'s answer: a {type(entries).__name__} of {[type(e).__name__ for e in entries]}: "
          f"{entries!r:.120}", flush=True)
    text = "\n".join(e if isinstance(e, str) else json.dumps(e) for e in entries)
    found = re.search(r"host-name (\S+)", text)
    assert found, entries
    return found.group(1)




# 1 and 2: create, show, destroy.


def test_a_twin_is_created_and_each_node_answers_with_its_own_host_name(
    core: Core, fylgja: Fylgja
) -> None:
    began = time.monotonic()
    code, _ = fylgja("twin", "create", "e2e", "--blueprint", str(BLUEPRINT))
    elapsed = time.monotonic() - began
    print(f"\n[e2e] create, end to end: {elapsed:.1f}s", flush=True)
    assert code == 0 and elapsed < DEADLINE_S

    code, out = fylgja("twin", "show", "e2e", "--json")
    record = json.loads(out)
    assert code == 0 and list(schemas.validator("twin-record-1").iter_errors(record)) == []
    status = record["status"]
    assert ready(record) and status["observed_generation"] == record["generation"] == 1
    assert [n["name"] for n in status["nodes"]] == list(NODES)
    assert all(n["holds"] == status["bundle_id"] for n in status["nodes"])
    names = {n["name"]: host_name(n["address"]) for n in status["nodes"]}
    print(f"[e2e] host names through each node's push transport: {names}", flush=True)
    assert names == {n: n for n in NODES}

    (run,) = core.runs("e2e")
    code, out = fylgja("run", "get", run["id"], "--json")
    assert code == 0 and json.loads(out)["verdict"]["status"] == "ok"
    events = core.events(run["id"])
    assert_events_whole(events)
    assert {e["phase"] for e in events} == CREATE_PHASES
    timings: dict[str, float] = {}
    for e in events:
        if e["outcome"] == "done":  # a phase's, or each node's in `ready` and `push`, summed
            timings[e["phase"]] = timings.get(e["phase"], 0.0) + e["duration_s"]
    print(f"[e2e] the create's phases: {', '.join(f'{p} {s:.2f}s' for p, s in timings.items())}", flush=True)


def test_the_twin_is_destroyed_and_nothing_is_left(core: Core, fylgja: Fylgja) -> None:
    try:
        code, out = fylgja("twin", "destroy", "e2e")
        assert code == 0 and "twin e2e deleted" in out
        assert core.record("e2e") is None
        assert leftovers("e2e") == CLEAN
        assert not [line for line in Path("/etc/hosts").read_text().splitlines() if "clab-e2e-" in line]
        destroy = core.runs("e2e")[0]
        assert (destroy["operation"], destroy["verdict"]["status"]) == ("destroy", "ok")
    finally:
        remove(core, "e2e")


# 3: a kill at every phase boundary of a create.


@pytest.mark.parametrize("phase", KILL_AT)
def test_a_server_killed_at_a_create_phase_resumes_the_same_run_to_ready(
    core: Core, fylgja: Fylgja, phase: str
) -> None:
    twin = "e2e-kill"
    try:
        since = core.stderr.stat().st_size
        began = time.monotonic()
        seen = created_until(core, fylgja, twin, phase)
        core.restart()  # the kill follows the phase's record at once
        after = core.record(twin)
        assert after is not None
        assert seen["status"].get("phase") == phase
        print(f"[e2e] killed at {phase}, {time.monotonic() - began:.1f}s in; the record read "
              f"{after['status'].get('phase')} after the restart", flush=True)

        record = settled_ready(core, twin)
        took = time.monotonic() - began
        creates = [r for r in core.runs(twin) if r["operation"] == "create"]  # newest first
        run_id = seen["status"]["run_id"]  # the run the record named when it was killed
        assert creates[0]["id"] == run_id, "the resume made a second create run"
        assert all(r["state"] == "ended" for r in creates)
        assert creates[0]["verdict"]["status"] == "ok", creates[0]["verdict"]
        events = core.events(run_id)
        assert_events_whole(events)
        applies, deployed, remade = started(events, "apply"), core.deploys(since, twin), reconfigures(core, since, twin)
        print(f"[e2e] killed at {phase}: Ready {took:.1f}s after the create, the same run {run_id}, "
              f"{applies} apply started, {len(deployed)} deploy, {remade} --reconfigure", flush=True)
        assert remade == 0, "a --reconfigure deploy"
        assert len(deployed) == 1, "a second deploy"
        if KILL_AT.index(phase) >= KILL_AT.index("applied"):
            assert applies == 1, f"an apply started after {phase} was recorded"
        else:
            assert 1 <= applies <= 2
        assert [n["name"] for n in record["status"]["nodes"]] == list(NODES)

        code, _ = fylgja("twin", "destroy", twin)
        assert code == 0
        assert leftovers(twin) == CLEAN
    finally:
        remove(core, twin)


def test_a_server_killed_during_the_deploy_resumes_the_same_run_to_ready(
    core: Core, fylgja: Fylgja
) -> None:
    """The longest window a kill lands in, between `planned` and `applied`: containerlab's deploy,
    which runs in a session of its own and so outlives the server killed under it, and runs to
    completion since its output goes to a file and not to a pipe the server held (D-056)."""
    twin = "e2e-kill3"
    try:
        since = core.stderr.stat().st_size
        code, _ = fylgja("twin", "create", twin, "--blueprint", str(BLUEPRINT), "--no-wait")
        assert code == 0
        began = time.monotonic()
        wait_for(lambda: True if core.deploys(since, twin) else None, "the deploy", every_s=0.1)
        time.sleep(10)
        after_kill = core.stderr.stat().st_size
        core.restart()
        record = settled_ready(core, twin)
        took = time.monotonic() - began
        # D-056: the orphaned deploy runs to completion and writes the hosts block and the ssh config
        # last; the resume, every node answering, ran no deploy of its own that could have written them.
        wait_for(lambda: None if containerlab_processes(f"/{twin}/") else True, "the orphaned deploy's end",
                 timeout_s=120, every_s=0.5)
        resumed = core.deploys(after_kill, twin)
        assert not resumed, resumed
        left = leftovers(twin)
        assert left["ssh_config"] and f"###### CLAB-{twin}-START ######" in [li.strip() for li in left["hosts"]], left
        (run,) = [r for r in core.runs(twin) if r["operation"] == "create"]
        assert run["verdict"]["status"] == "ok", run["verdict"]
        events = core.events(run["id"])
        assert_events_whole(events)
        print(f"[e2e] killed 10s into the deploy: Ready {took:.1f}s after the create, {started(events, 'apply')} "
              f"apply started; the resume's deploys: {len(resumed)}", flush=True)
        assert started(events, "apply") <= 2 and [n["name"] for n in record["status"]["nodes"]] == list(NODES)
        code, _ = fylgja("twin", "destroy", twin)
        assert code == 0
        assert leftovers(twin) == CLEAN
    finally:
        remove(core, twin)


# 4: a kill during a destroy, and a deletion during the deploy.


def test_a_server_killed_during_a_destroy_resumes_it_and_nothing_is_left(
    core: Core, fylgja: Fylgja
) -> None:
    twin = "e2e-kill2"
    try:
        code, _ = fylgja("twin", "create", twin, "--blueprint", str(BLUEPRINT))
        assert code == 0
        code, _ = fylgja("twin", "destroy", twin, "--no-wait")
        assert code == 0
        began = time.monotonic()
        wait_for(lambda: True if any(r["operation"] == "destroy" for r in core.runs(twin)) else None,
                 "the destroy run", every_s=0.05)
        core.restart()
        wait_for(lambda: gone(core, twin), f"{twin} gone")
        print(f"[e2e] killed during the destroy: gone {time.monotonic() - began:.1f}s after it was asked", flush=True)
        destroy = next(r for r in core.runs(twin) if r["operation"] == "destroy")
        assert destroy["verdict"]["status"] == "ok"
        assert leftovers(twin) == CLEAN
    finally:
        remove(core, twin)


def test_a_delete_during_the_deploy_cancels_the_create_and_leaves_nothing(
    core: Core, fylgja: Fylgja
) -> None:
    twin = "e2e-del"
    try:
        since = core.stderr.stat().st_size
        code, _ = fylgja("twin", "create", twin, "--blueprint", str(BLUEPRINT), "--no-wait")
        assert code == 0
        wait_for(lambda: True if containerlab_processes(f"/{twin}/") else None, "the deploy's process", every_s=0.1)
        deploying = time.monotonic()
        assert core.deploys(since, twin)
        # Asked once the deploy has made its containers, so the cancel leaves a partial lab to tear down.
        wait_for(lambda: True if leftovers(twin)["containers"] else None, "the deploy's containers", every_s=0.2)
        assert containerlab_processes(f"/{twin}/"), "the deploy ended before the deletion was asked"
        began = time.monotonic()
        code, out = fylgja("twin", "destroy", twin)
        print(f"[e2e] deleted {began - deploying:.1f}s into the deploy, its containers made: gone "
              f"{time.monotonic() - began:.1f}s after it was asked", flush=True)
        assert code == 0 and f"twin {twin} deleted" in out
        destroy, create = core.runs(twin)
        assert (create["operation"], create["verdict"]["status"]) == ("create", "failed"), create["verdict"]
        assert [f["rule"] for f in create["verdict"]["findings"]] == ["run.cancelled"]
        assert (destroy["operation"], destroy["verdict"]["status"]) == ("destroy", "ok"), destroy["verdict"]
        assert leftovers(twin) == CLEAN
        assert containerlab_processes() == [], "a containerlab process is left"
    finally:
        remove(core, twin)


# 5: the server's log.


def test_every_line_the_server_logged_is_json_and_holds_no_secret(core: Core) -> None:
    assert_log_clean(core)
