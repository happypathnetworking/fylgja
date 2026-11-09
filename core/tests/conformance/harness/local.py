"""`LocalHarness` is the containerlab driver's: `fylgja-core-server` as a subprocess over a store
in a temporary directory, with a token it makes for the principal `conformance`, the node logins
from the environment and its resync an hour away; killed with SIGKILL and started again the same
way; its runtime read through Docker, /etc/hosts and /proc, and a node replaced or stopped
behind the core's back by containerlab's own `stop --node` and `start --node`, which keep the
node's links. The server's loop follows `docker events` (D-058), in a session of its own, which
a SIGKILL leaves running until the next event it prints (verified-facts.md): the harness holds a
pidfd of each server's follower, taken while the server is its parent, and ends it after each
kill, so no other process is ever reached; one the last server's stop leaves fails the session.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from secrets import token_urlsafe
from typing import Any

import httpx
import pytest
from live import host

from conformance.harness import RESYNC_S, Mark, Resume, _Api
from conformance.reads import ROOT, remove, wait_for
from fylgja_core.capacity import LOCAL_HOST
from fylgja_core.containerlab import cli as clab_cli
from fylgja_core.containerlab.plan import TOPOLOGY
from fylgja_core.server import auth

SERVER = Path(sys.executable).parent / "fylgja-core-server"
STEP_WAIT_S = 90
"""The local core's step wait (`FYLGJA_STEP_WAIT_S`), half its default: a step whose verify never
holds ends `stepped` with `step.wait.expired` within the suite's deadline."""
STRAYS_S = 300.0
"""How long the processes running at a kill may run on: a deploy cut short runs to completion
(D-056), about as long as a whole deploy."""
GONE_S = 120.0
"""How long a destroy's processes may take to end once its run has."""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


@dataclass(frozen=True)
class _Kill:
    """A kill the local harness made: the log's mark, the wall clock and the monotonic clock just
    before it, and the `containerlab` processes running then."""

    mark: Mark
    at: datetime
    monotonic: float
    pids: tuple[int, ...]


@dataclass(eq=False)
class LocalHarness(_Api):
    """The containerlab driver's harness: the server as a subprocess, and the host read through
    `live.host`. The environment it is started with, which holds every node login, and the token
    are no part of its repr. `followers` holds a pidfd of each `docker events` the running server
    follows; `orphans` counts those a kill left and the harness ended, and `strays` those the last
    stop left running."""

    tmp: pytest.TempPathFactory = field(repr=False)
    env: dict[str, str] = field(repr=False)
    token: str = field(repr=False)
    here: Path | None = None
    port: int | None = None
    process: subprocess.Popen[bytes] | None = field(default=None, repr=False)
    starts: list[float] = field(default_factory=list)
    kills: list[_Kill] = field(default_factory=list, repr=False)
    http: httpx.Client | None = field(default=None, repr=False)
    followers: list[int] = field(default_factory=list, repr=False)
    orphans: int = 0
    strays: int = 0

    @classmethod
    def over(cls, environ: Mapping[str, str], tmp: pytest.TempPathFactory) -> LocalHarness:
        """The harness over `environ`: the server's environment is it without its `FYLGJA_`
        settings, the node logins kept, and the core's own settings; the store, the token's file
        and the port are the first start's."""
        env = {name: value for name, value in environ.items() if not name.startswith("FYLGJA_")}
        env.update({name: value for name, value in environ.items() if name.startswith("FYLGJA_CREDENTIAL_")})
        env.update({
            "FYLGJA_DRIVER": "containerlab",
            "FYLGJA_PACKAGES": f"{ROOT / 'psp'}:{ROOT / 'probes'}",
            "FYLGJA_STEP_WAIT_S": str(STEP_WAIT_S),
            "FYLGJA_RESYNC_S": str(RESYNC_S),
        })
        return cls(tmp=tmp, env=env, token=token_urlsafe(24))

    @property
    def address(self) -> str:
        assert self.port is not None, "the core was never started"
        return f"127.0.0.1:{self.port}"

    @property
    def store(self) -> Path:
        return Path(self.env["FYLGJA_STORE"])

    @property
    def stderr(self) -> Path:
        """The server's log, every start's appended."""
        assert self.here is not None, "the core was never started"
        return self.here / "server.stderr"

    def _token(self) -> str:
        return self.token

    def client(self) -> httpx.Client:
        assert self.http is not None, "the core was never started"
        return self.http

    # The core.

    def _prepare(self) -> None:
        """The session's store directory, the token's file for the principal `conformance`, and the
        port the core listens on."""
        here = self.tmp.mktemp("conformance")
        (here / "tokens").write_text(f"# the conformance suite\n{auth.hash_token(self.token)} conformance\n")
        self.port = _free_port()
        self.env.update({
            "FYLGJA_STORE": str(here / "store"),
            "FYLGJA_LISTEN": f"127.0.0.1:{self.port}",
            "FYLGJA_TOKENS": str(here / "tokens"),
        })
        self.here = here

    def start(self) -> None:
        if self.here is None:
            self._prepare()
        began = time.monotonic()
        with self.stderr.open("ab") as err:
            try:
                self.process = subprocess.Popen([str(SERVER)], env=self.env, stdout=subprocess.DEVNULL, stderr=err)
            except OSError as e:  # raised afresh, so that no frame shown holds the environment
                raise RuntimeError(f"fylgja-core-server did not start: {e.strerror}") from None
        if self.http is not None:
            self.http.close()
        # The token rides in the client's own headers, never in a call's arguments.
        self.http = httpx.Client(base_url=f"http://{self.address}", headers={"Authorization": f"Bearer {self.token}"},
                                 timeout=30.0, trust_env=False)
        wait_for(self._answers, "the core's first answer", timeout_s=60, every_s=0.05)
        self.starts.append(time.monotonic() - began)
        self._hold_followers()

    def _answers(self) -> bool | None:
        assert self.running(), "the core exited"
        try:
            answer = httpx.get(f"http://{self.address}/v1/version", timeout=1.0, trust_env=False)
        except httpx.TransportError:
            return None
        return True if answer.status_code == 200 else None

    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def _hold_followers(self, wait: bool = True) -> None:
        """A pidfd of each `docker events` the server follows, taken while the server is its parent:
        a kill reparents it, and a pid alone could name another process by then. The server starts
        its follower as its loop starts (D-058), and with `wait` one is waited for; without, those
        running now are held, none perhaps, when the server's follower is between two streams."""
        assert self.process is not None
        server = self.process.pid
        pids = (wait_for(lambda: host.followers(server) or None, "the core's docker events", timeout_s=10,
                         every_s=0.05)
                if wait else host.followers(server))
        for fd in self.followers:
            os.close(fd)
        self.followers = []
        for pid in pids:
            try:
                fd = os.pidfd_open(pid)
            except ProcessLookupError:
                continue
            if pid in host.followers(server):  # still the server's: not a pid reused since the scan
                self.followers.append(fd)
            else:
                os.close(fd)

    def _end_followers(self) -> int:
        """End each follower `followers` holds that still runs, with SIGKILL through its pidfd, wait
        for it to exit, and release them all, whatever happened: how many it ended. One that
        outlives its SIGKILL fails the test, once every pidfd is closed."""
        killed, outlived = 0, 0
        held, self.followers = self.followers, []
        try:
            for fd in held:
                if not host.ended(fd):
                    with contextlib.suppress(ProcessLookupError):
                        signal.pidfd_send_signal(fd, signal.SIGKILL)
                        killed += 1
                    if not host.ended(fd, timeout_s=10):
                        outlived += 1
        finally:
            for fd in held:
                os.close(fd)
        assert not outlived, f"{outlived} docker events outlived its SIGKILL"
        return killed

    def kill(self) -> float:
        """SIGKILL, as a host losing the process would, then a start the same way: the seconds from
        the kill to the core's first answer. The kill's mark, its wall time and the `containerlab`
        processes running at it are kept for `audit_resume`. The killed server's `docker events`,
        which would run on until the next event it prints, is ended between the two. Nothing is
        read before the kill but the log and /proc, unless the follower restarted since the
        server's start, so the kill lands where its caller timed it."""
        assert self.process is not None, "the core was never started"
        if not self.followers or any(host.ended(fd) for fd in self.followers):
            self._hold_followers()
        kill = _Kill(mark=self.mark(), at=datetime.now(UTC), monotonic=time.monotonic(),
                     pids=tuple(host.containerlab_processes()))
        self.process.send_signal(signal.SIGKILL)
        self.process.wait(timeout=30)
        self.kills.append(kill)
        self.orphans += self._end_followers()
        self.start()
        return time.monotonic() - kill.monotonic

    def _stop(self) -> None:
        """SIGTERM, and the server's own stop ends its `docker events`: one still running 10 s
        after the server exited is counted in `strays`, and ended. A follower that restarted since
        the server's start is held again first, as `kill` holds it, so it is counted too."""
        if self.http is not None:
            self.http.close()
        if self.running():
            assert self.process is not None
            if not self.followers or any(host.ended(fd) for fd in self.followers):
                self._hold_followers(wait=False)
            self.process.send_signal(signal.SIGTERM)
            try:
                self.process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.strays += sum(1 for fd in self.followers if not host.ended(fd, timeout_s=10))
        self._end_followers()

    def close(self, twins: Iterable[str]) -> None:
        """Each of `twins` destroyed through the API if it is still there, the core started again if
        it is down; then the core stopped, and any twin the host still holds torn down by
        containerlab itself. The session fails if the host still holds any of them, a
        `containerlab` process runs, or the last stop left a `docker events`."""
        twins = tuple(twins)
        if self.here is None:
            return
        try:
            if not self.running():
                self.start()
            for twin in twins:
                remove(self, twin)
        finally:
            self._stop()
            for twin in twins:
                if self.leftovers(twin):
                    host.clean_up_by_hand(self.store, twin, None)
            print(f"\n[conformance] core starts: {', '.join(f'{s:.2f}s' for s in self.starts)}; its log: "
                  f"{self.stderr}; docker events a kill left, ended by the harness: {self.orphans}; left by the last "
                  f"stop: {self.strays}", flush=True)
            dirty = {twin: left for twin in twins if (left := self.leftovers(twin))}
            running = host.containerlab_processes()
            if dirty or running or self.strays:
                pytest.fail(f"the teardown left the host dirty: {dirty}, containerlab processes {running}, "
                            f"docker events the core's stop left {self.strays}", pytrace=False)

    # The runtime.

    def nodes(self, twin: str) -> dict[str, str]:
        """Each container of the twin's lab by its node name, with its `State.StartedAt`, the
        incarnation the driver writes (verified-facts.md), whether it runs or not."""
        listed = host.docker("ps", "-a", "--filter", f"label=containerlab={twin}", "--format", "{{.Names}}")
        names = listed.stdout.split()
        if not names:
            return {}
        shown = host.docker("inspect", "--format", '{{index .Config.Labels "clab-node-name"}} {{.State.StartedAt}}',
                            *names)
        assert shown.returncode == 0, shown.stderr
        found = {}
        for line in shown.stdout.splitlines():
            node, started_at = line.split()
            found[node] = started_at
        return found

    def hosts(self, twin: str) -> dict[str, str]:
        """Each node `nodes(twin)` lists on the one host the driver runs on."""
        return dict.fromkeys(self.nodes(twin), LOCAL_HOST)

    def many(self) -> int:
        """Three twins of three nodes: nine SR Linux nodes within the local host's room."""
        return 3

    def twins(self) -> set[str]:
        """The `fylgja.twin` label of every container on the host, which each of the driver's
        containers carries (the topology's default labels, verified-facts.md)."""
        shown = host.docker("ps", "-a", "--filter", "label=fylgja.twin", "--format", '{{.Label "fylgja.twin"}}')
        assert shown.returncode == 0, shown.stderr
        return {line for line in shown.stdout.splitlines() if line}

    def leftovers(self, twin: str) -> list[str]:
        """What the host holds of `twin`: its containers, its lines of /etc/hosts (by what they
        name, never their address), its ssh config, its management network and the `containerlab`
        processes naming it."""
        left = host.leftovers(twin, None)
        found = [f"container {name}" for name in left["containers"]]
        found += [f"/etc/hosts: {line.strip() if line.lstrip().startswith('#') else ' '.join(line.split()[1:])}"
                  for line in left["hosts"]]
        if left["ssh_config"]:
            found.append(f"/etc/ssh/ssh_config.d/clab-{twin}.conf")
        if left["network"]:
            found.append(f"network clab-{twin}")
        found += [f"containerlab process {pid}" for pid in host.containerlab_processes(f"/{twin}/")]
        return found

    def _node_command(self, verb: str, twin: str, node: str) -> None:
        """`containerlab <verb> --node <node>` on the twin's topology, from its directory and with
        the environment the driver gives its commands (`cli.environment`), as the live tier runs
        it: timed and printed, and a status other than 0 fails the test, with its stderr's last
        line, where containerlab writes its error."""
        directory = self.store / "containerlab" / twin
        began = time.monotonic()
        done = subprocess.run(["containerlab", verb, "--node", node, "-t", str(directory / TOPOLOGY)],
                              capture_output=True, text=True, timeout=300, env=clab_cli.environment(os.environ),
                              cwd=directory, check=False)
        print(f"\n[conformance] containerlab {verb} --node {node} of {twin}: status {done.returncode} in "
              f"{time.monotonic() - began:.2f}s", flush=True)
        assert done.returncode == 0, \
            f"containerlab {verb} --node {node} exited {done.returncode}: {done.stderr.strip().splitlines()[-1:]}"

    def replace_node(self, twin: str, node: str) -> None:
        """`containerlab stop --node`, then `start --node`, until Docker's `StartedAt` of the node,
        its incarnation, has moved: the node returns with its links, which `start --node` keeps
        where `docker start` loses them (verified-facts.md, "`containerlab start --node n3` keeps
        the node's links"). Never `docker stop` and `docker start`."""
        was = self.nodes(twin).get(node)
        assert was is not None, f"the runtime holds no {node} of {twin}"
        self._node_command("stop", twin, node)
        self._node_command("start", twin, node)
        wait_for(lambda: True if self.nodes(twin).get(node) not in (None, was) else None,
                 f"{node}'s new StartedAt", timeout_s=60, every_s=0.2)

    def stop_node(self, twin: str, node: str) -> None:
        """`containerlab stop --node`, its links kept; an SR Linux node stays stopped, its restart
        policy `no` (verified-facts.md, "A node that Docker starts again by itself")."""
        self._node_command("stop", twin, node)

    def reach(self, frm: tuple[str, str] | None, to: tuple[str, str], port: int) -> dict[str, bool]:
        raise NotImplementedError("the local runtime keeps twins apart by names alone (isolation `names`): no path "
                                  "of one twin is closed to another, so there is nothing to read")

    # The core's log.

    def log(self) -> list[str]:
        """The server's stderr, every start's: a last line not yet ended by its newline is not one
        yet."""
        if self.here is None or not self.stderr.exists():
            return []
        return self.stderr.read_text(errors="replace").split("\n")[:-1]

    def mark(self) -> Mark:
        return len(self.log())

    def secrets(self) -> Mapping[str, str]:
        """The token, and each node's password the core was given."""
        passwords = {name: value for name, value in self.env.items()
                     if name.startswith("FYLGJA_CREDENTIAL_") and name.endswith("_PASSWORD")}
        return {"FYLGJA_API_TOKEN": self.token, **passwords}

    # The audits: what only containerlab's account shows, from the deploy lines the core logged.

    def _said(self, since: Mark) -> list[dict[str, Any]]:
        """The core's log lines after the mark `since`, each a JSON object with a message; a line that
        is none is passed over (`assert_log_clean` names it)."""
        found = []
        for line in self.log()[since:]:
            try:
                doc = json.loads(line)
            except ValueError:
                continue
            if isinstance(doc, dict) and isinstance(doc.get("message"), str):
                found.append(doc)
        return found

    def _deploys(self, twin: str, since: Mark) -> list[str]:
        """The `containerlab deploy` command lines of `twin` the core logged after `since`."""
        return [d["message"] for d in self._said(since)
                if "containerlab deploy" in d["message"] and f"/{twin}/" in d["message"]]

    def _last_kill(self, since: Mark) -> _Kill:
        assert self.kills and self.kills[-1].mark >= since, "no kill after the mark the audit was given"
        return self.kills[-1]

    def _outlived(self, kill: _Kill) -> float | None:
        """How long the `containerlab` processes running at `kill` ran on after it, waited for up to
        `STRAYS_S`; None when there were none."""
        if not kill.pids:
            return None

        def ended_at() -> float | None:
            return None if any(Path(f"/proc/{pid}").exists() for pid in kill.pids) else time.monotonic()

        return wait_for(ended_at, "the end of the containerlab processes running at the kill", timeout_s=STRAYS_S,
                        every_s=0.1) - kill.monotonic

    def _stray_wait(self, twin: str, since: Mark) -> float | None:
        """The seconds the driver waited on a stray deploy of `twin` after `since`: from its line
        saying it waits to the deploy that followed; None when it never waited."""
        said = self._said(since)
        waits = [i for i, d in enumerate(said) if "a stray deploy" in d["message"] and f" {twin}:" in d["message"]]
        if not waits:
            return None
        after = next((d for d in said[waits[0]:]
                      if "containerlab deploy" in d["message"] and f"/{twin}/" in d["message"]), None)
        assert after is not None, f"the driver logged a wait on a stray deploy of {twin}, and no deploy after it"
        began, ended_at = (datetime.fromisoformat(d["time"]) for d in (said[waits[0]], after))
        return (ended_at - began).total_seconds()

    def _started_after(self, twin: str, kill: _Kill) -> str:
        """Each node's start, its incarnation read as a time, from the kill: a reading, printed."""
        record = self.record(twin)
        if record is None:
            return "no record"
        seconds = []
        for node in record["status"]["nodes"]:
            try:  # Docker's nanoseconds, cut to the microseconds `datetime` reads
                at = datetime.fromisoformat(re.sub(r"(\.\d{6})\d+", r"\1", node["incarnation"]))
            except (KeyError, TypeError, ValueError):
                seconds.append(f"{node['name']} unread")
                continue
            seconds.append(f"{node['name']} {(at - kill.at).total_seconds():+.1f}s")
        return ", ".join(seconds)

    def audit_apply(self, twin: str, since: Mark, applies: int) -> None:
        """No deploy of `twin` after `since` is a `--reconfigure`, and there is one for each apply."""
        deploys = self._deploys(twin, since)
        remade = sum(1 for line in deploys if "--reconfigure" in line)
        print(f"[conformance] {twin}: {applies} apply started, {len(deploys)} deploy, {remade} --reconfigure",
              flush=True)
        assert remade == 0, "a --reconfigure deploy"
        assert len(deploys) == applies, f"{len(deploys)} deploys for {applies} applies"

    def audit_resume(self, twin: str, since: Mark, resume: Resume) -> None:
        """The deploys of `twin` after `since`, around the last kill: none a `--reconfigure`. A
        create killed at a phase boundary deployed once, whatever the phase; one killed in its
        apply deployed nothing after the kill, the deploy cut short having run to completion and
        written the hosts block and the ssh config itself (D-056). A step resumed after `applied`
        deployed once and waited on no stray deploy; one killed in its apply deployed twice; one
        killed before `applied` deployed once for each apply at most, and waited on a stray deploy
        only where it applied twice and deployed twice."""
        kill = self._last_kill(since)
        deploys = self._deploys(twin, since)
        remade = sum(1 for line in deploys if "--reconfigure" in line)
        if resume.operation == "create":
            if resume.in_apply:
                ran_on = self._outlived(kill)
                resumed = self._deploys(twin, kill.mark)
                left = host.leftovers(twin, None)
                print(f"[conformance] {twin}, killed in its apply: the processes running at the kill "
                      f"{'none' if ran_on is None else f'ran on {ran_on:.1f}s'}; {len(deploys)} deploy, "
                      f"{len(resumed)} of them the resume's, {remade} --reconfigure", flush=True)
                assert remade == 0, "a --reconfigure deploy"
                assert not resumed, f"the resume deployed {len(resumed)} time(s)"
                marker = f"###### CLAB-{twin}-START ######"
                assert left["ssh_config"] and marker in [line.strip() for line in left["hosts"]], \
                    "the deploy cut short left no hosts block or no ssh config (D-056)"
            else:
                print(f"[conformance] {twin}, killed at a phase boundary: {len(deploys)} deploy, {remade} "
                      "--reconfigure", flush=True)
                assert remade == 0, "a --reconfigure deploy"
                assert len(deploys) == 1, f"{len(deploys)} deploys"
            return
        ran_on = self._outlived(kill)
        waited = self._stray_wait(twin, since)
        print(f"[conformance] {twin}'s step: {resume.applies} apply started, {len(deploys)} deploy, {remade} "
              f"--reconfigure; a deploy running at the kill: {'none' if ran_on is None else f'ran on {ran_on:.1f}s'}; "
              f"the driver waited for it {'no' if waited is None else f'{waited:.1f}s'}; the nodes started, from "
              f"the kill: {self._started_after(twin, kill)}", flush=True)
        assert remade == 0, "a --reconfigure deploy"
        if resume.after_applied:
            assert len(deploys) == 1 and waited is None, (len(deploys), waited)
        elif resume.in_apply:
            assert len(deploys) == 2, f"{len(deploys)} deploys"
        else:
            assert 1 <= len(deploys) <= resume.applies, (resume.applies, len(deploys))
            assert waited is None or (resume.applies, len(deploys)) == (2, 2), (resume.applies, len(deploys), waited)

    def audit_destroy(self, twin: str, since: Mark, unnamed: Sequence[str] = (), stray: bool = False) -> None:
        """The destroy of `twin` after `since`, by the core's log: no deploy of the twin after
        `since` a `--reconfigure`; each node of `unnamed` removed before `containerlab destroy`
        (D-055); a wait on a stray deploy before the first removal, or the destroy where none is
        removed, exactly where `stray`; then no `containerlab` process naming the twin within
        `GONE_S`."""
        said = [d["message"] for d in self._said(since)]
        for message in said:
            if twin in message and any(k in message for k in ("stray", "destroy", "deploy", "removed")):
                print(f"[conformance]   {message[:160]}", flush=True)
        assert not any("--reconfigure" in line for line in self._deploys(twin, since)), "a --reconfigure deploy"
        destroyed = next((i for i, m in enumerate(said) if m.startswith("containerlab destroy") and f"/{twin}/" in m),
                         None)
        waited = next((i for i, m in enumerate(said) if m.startswith(f"destroy {twin}: a stray deploy")), None)
        assert destroyed is not None, f"no containerlab destroy of {twin}"
        removals = []
        for node in unnamed:
            removed = next((i for i, m in enumerate(said) if m.startswith(f"destroy {twin}: removed {node},")), None)
            assert removed is not None and removed < destroyed, f"{node} was not removed before the destroy"
            removals.append(removed)
        if stray:
            assert waited is not None, "the destroy did not wait for the stray deploy"
            assert waited < min(removals, default=destroyed), "the destroy waited for the stray deploy too late"
        else:
            assert waited is None, "the destroy waited for a stray deploy"
        wait_for(lambda: None if host.containerlab_processes(f"/{twin}/") else True,
                 f"the end of {twin}'s containerlab processes", timeout_s=GONE_S)
