"""What the live tier reads of this host: shared by the modules of `tests/live` and the
conformance suite's local harness (`tests/conformance/harness/local.py`). The fixtures' constants are
the suite's (`conformance.reads`), named here again for the modules of `tests/live`.

The host's readings are a twin's leftovers (its containers by label, its lines of /etc/hosts,
its ssh config and its management network), the `containerlab` processes running, and the
`docker events` processes a parent follows, the local driver's follower (D-058), ended through
pidfds. `clean_up_by_hand` tears down what the host still holds of a twin with containerlab
itself, for a teardown whose destroy through the API left something.
"""

from __future__ import annotations

import contextlib
import os
import select
import signal
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest
from conformance.reads import BLUEPRINT as BLUEPRINT
from conformance.reads import NODES as NODES
from conformance.reads import ROOT as ROOT

NEEDS_LOGINS = pytest.mark.skipif(
    not os.environ.get("FYLGJA_CREDENTIAL_SRLINUX_USERNAME"),
    reason="the live tier reads the node logins from the environment: load local/.env first "
    "(set -a; . local/.env; set +a)",
)
"""Each module's `pytestmark`."""


def followers(parent: int) -> list[int]:
    """The pids of the `docker events` processes whose parent is `parent`: the local driver's
    follower (D-058), in a server or in this process. A zombie, whose command line reads empty, is
    passed over."""
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            ppid = int((entry / "stat").read_text().rpartition(")")[2].split()[1])
            if ppid != parent:
                continue
            argv = (entry / "cmdline").read_bytes().split(b"\0")
        except (OSError, IndexError, ValueError):
            continue
        if Path(argv[0].decode(errors="replace")).name == "docker" and argv[1:2] == [b"events"]:
            found.append(int(entry.name))
    return sorted(found)


def ended(pidfd: int, timeout_s: float = 0.0) -> bool:
    """Whether the process `pidfd` refers to has exited, waiting at most `timeout_s` for it."""
    poller = select.poll()
    poller.register(pidfd, select.POLLIN)
    return bool(poller.poll(int(timeout_s * 1000)))


def containerlab_processes(needle: str = "") -> list[int]:
    """The pids of the `containerlab` processes whose command line holds `needle`."""
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            argv = (entry / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        if argv and Path(argv[0].decode(errors="replace")).name == "containerlab" and needle in " ".join(
            a.decode(errors="replace") for a in argv
        ):
            found.append(int(entry.name))
    return found


def docker(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=60, check=False)


def leftovers(twin: str, nodes: Iterable[str] | None = NODES) -> dict[str, Any]:
    """What the host holds of `twin`: its containers by label, its lines of /etc/hosts (its block's
    markers, and the names of `nodes` exactly, or with None every name `clab-<twin>-…`, which
    holds only where no other twin's name begins with the twin's), its ssh config and its
    management network."""
    names = docker("ps", "-a", "--filter", f"label=containerlab={twin}", "--format", "{{.Names}}").stdout.split()
    hosts = Path("/etc/hosts").read_text(errors="replace").splitlines()
    marked = {f"###### CLAB-{twin}-START ######", f"###### CLAB-{twin}-END ######"}
    if nodes is None:
        def named(line: str) -> bool:
            return any(name.startswith(f"clab-{twin}-") for name in line.split()[1:])
    else:
        exact = {f"clab-{twin}-{node}" for node in nodes}

        def named(line: str) -> bool:
            return bool(exact & set(line.split()[1:]))
    lines = [line for line in hosts if line.strip() in marked or named(line)]
    return {
        "containers": names,
        "hosts": lines,
        "ssh_config": Path(f"/etc/ssh/ssh_config.d/clab-{twin}.conf").exists(),
        "network": docker("network", "inspect", f"clab-{twin}").returncode == 0,
    }


CLEAN = {"containers": [], "hosts": [], "ssh_config": False, "network": False}


def clean_up_by_hand(store: Path, twin: str, nodes: Iterable[str] | None = NODES) -> None:
    """Tear down whatever the host still holds of `twin`, a twin of the store `store` (the local
    driver's root), with containerlab itself: its stray commands killed, its lab destroyed by its
    topology (or its name), any container of the lab left removed with `docker`, its network
    removed."""
    topology = store / "containerlab" / twin / "topology.clab.yml"
    for pid in containerlab_processes(f"/{twin}/"):
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
    command = (["containerlab", "destroy", "-t", str(topology), "--cleanup"] if topology.exists()
               else ["containerlab", "destroy", "--name", twin, "--cleanup"])
    destroyed = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    # containerlab's destroy removes only the nodes the topology names (verified-facts.md, 0.81.0).
    for name in docker("ps", "-a", "--filter", f"label=containerlab={twin}", "--format", "{{.Names}}").stdout.split():
        docker("rm", "-f", name)
    docker("network", "rm", f"clab-{twin}")
    print(f"\n[host] teardown: {' '.join(command[:3])}… for {twin}: status {destroyed.returncode}; "
          f"left {leftovers(twin, nodes)}", flush=True)
