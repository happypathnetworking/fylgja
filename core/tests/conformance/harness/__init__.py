"""The conformance suite's harnesses (design/core.md, phase 6, "The conformance suite"): what a
scenario needs of a core and of the runtime under it, said once as `Harness`, and one harness
a driver, made by `make` from the driver's name: `LocalHarness` (`local.py`) the containerlab
driver's, `ClusterHarness` (`cluster.py`) the clabernetes driver's.

A scenario reads the API, the CLI, the nodes' own answers at the record's addresses and the
harness, and nothing else: what a driver can do comes from `GET /v1/drivers`' capabilities, and
what only a runtime's own account shows (a deploy count, a `--reconfigure`, the hosts block a
deploy cut short still writes, D-056) is asserted behind the harness's `audit_*` calls, given the
neutral facts a scenario has. This is the one package of the suite that names a runtime
(`test_conformance_scenarios.py` holds the rest to it).

No assertion here shows a secret when it fails: the token and the environment the core is
started with (every node login) are kept out of each harness's repr and out of every frame's
arguments, and the log checks report line numbers, never lines. The cluster's harness reads the
environment inside `over` alone, and a variable it lacks is one line naming it.
"""

from __future__ import annotations

import abc
import os
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

import httpx
import pytest

from conformance.reads import DEADLINE_S
from fylgja_core import cli as thin_cli

MARKERS = {"containerlab": "live", "clabernetes": "cluster"}
"""Each driver a harness is made for, by its name, with the marker its run is selected by."""
DRIVER_VARIABLE = "FYLGJA_CONFORMANCE_DRIVER"
DEFAULT_DRIVER = "containerlab"
RESYNC_S = 3600
"""The local core's resync (`FYLGJA_RESYNC_S`): an hour, so no pass a scenario reads was started
by it."""

type Fylgja = Callable[..., tuple[int, str]]
"""The CLI in-process (`Harness.cli`): its exit code and its stdout."""
type Mark = int
"""A place in the core's log, `Harness.mark()`: the lines after it are `log()[mark:]`."""


@dataclass(frozen=True)
class Resume:
    """What a scenario knows of the kill whose resume it audits: the run's operation, how many
    `apply` phases its events show started, whether the kill followed `applied`, and whether it
    landed in an apply."""

    operation: Literal["create", "step"]
    applies: int
    after_applied: bool
    in_apply: bool


class Harness(Protocol):
    """A core and the runtime under it, as a scenario drives and reads them."""

    @property
    def address(self) -> str:
        """The API's address, for the CLI."""
        ...

    def start(self) -> None:
        """The core serves (`GET /v1/version` answers 200 within 60 s), and resyncs no sooner
        than every 3600 s."""
        ...

    def kill(self) -> float:
        """The core dies as its host or its pod would lose it; returns once it serves again, with
        the seconds that took."""
        ...

    def close(self, twins: Iterable[str]) -> None:
        """Each of `twins` removed through the API, then by the runtime's own means if anything of
        it is still there; the session failed if anything is left by its label."""
        ...

    def client(self) -> httpx.Client:
        """An HTTP client of the API, the token in its headers."""
        ...

    def cli(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> Fylgja:
        """The thin CLI in-process, pointed at the core."""
        ...

    def record(self, twin: str) -> dict[str, Any] | None:
        ...

    def runs(self, twin: str) -> list[dict[str, Any]]:
        ...

    def run(self, run_id: str) -> dict[str, Any]:
        ...

    def events(self, run_id: str) -> list[dict[str, Any]]:
        ...

    def nodes(self, twin: str) -> dict[str, str]:
        """Each node the runtime holds of the twin, with its incarnation as the runtime says it;
        `{}` when it holds none."""
        ...

    def hosts(self, twin: str) -> dict[str, str]:
        """Each node the runtime holds of the twin, with the host it runs on as the runtime says
        it; a node not yet placed on a host is left out, and `{}` when it holds none."""
        ...

    def many(self) -> int:
        """How many twins of three nodes the many-twins scenario creates together: the runtime's
        room for them, and more that do not fit being the scenario's `BIG` twin's."""
        ...

    def twins(self) -> set[str]:
        """Every twin the runtime holds anything of, by the twin label."""
        ...

    def leftovers(self, twin: str) -> list[str]:
        """What the runtime still holds of `twin`, each a short description."""
        ...

    def replace_node(self, twin: str, node: str) -> None:
        """The node returns as another incarnation, behind the core's back; returns once
        `nodes(twin)[node]` has moved."""
        ...

    def stop_node(self, twin: str, node: str) -> None:
        """The node stops, and stays stopped."""
        ...

    def reach(self, frm: tuple[str, str] | None, to: tuple[str, str], port: int) -> dict[str, bool]:
        """Whether a TCP connection to `port` of the node `to` (a twin and a node) is accepted, by
        each path the runtime gives that node, from inside the node `frm`, or with None from a
        place of no twin; the source has run 15 s or more."""
        ...

    def log(self) -> list[str]:
        """Every line the core has logged in this session, across kills."""
        ...

    def mark(self) -> Mark:
        """`len(log())`."""
        ...

    def secrets(self) -> Mapping[str, str]:
        """By variable name, each value no log line may hold."""
        ...

    def audit_apply(self, twin: str, since: Mark, applies: int) -> None:
        """What only the runtime's account shows of the applies after `since`, of which the run's
        events show `applies` started."""
        ...

    def audit_resume(self, twin: str, since: Mark, resume: Resume) -> None:
        """What only the runtime's account shows of a run resumed after the last kill, `since`
        taken before the run's write."""
        ...

    def audit_destroy(self, twin: str, since: Mark, unnamed: Sequence[str] = (), stray: bool = False) -> None:
        """What only the runtime's account shows of a destroy after `since`: each node of
        `unnamed`, which the deployment destroyed does not name, removed first; a deploy left
        running waited for, by `stray`; and nothing of it running after."""
        ...


def make(driver: str, tmp: pytest.TempPathFactory) -> Harness:
    """The harness of `driver`, over the environment as it is now. Nothing is started and
    nothing is written: `start` does that."""
    if driver == "containerlab":
        return LocalHarness.over(os.environ, tmp)
    if driver == "clabernetes":
        return ClusterHarness.over()
    raise ValueError(f"no conformance harness for {driver!r}: the drivers are {' and '.join(MARKERS)}")


class _Api(abc.ABC):
    """The API's reads and the CLI in-process, over `client()` and `address`: written once for
    every harness."""

    @property
    @abc.abstractmethod
    def address(self) -> str: ...

    @abc.abstractmethod
    def client(self) -> httpx.Client: ...

    @abc.abstractmethod
    def _token(self) -> str:
        """The API token the CLI is given."""

    def _ca(self) -> Path | None:
        """The CA file the CLI verifies the core's certificate against; None where it serves plain
        HTTP."""
        return None

    def cli(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> Fylgja:
        """The thin CLI in-process, within `DEADLINE_S`: its exit code and its stdout, timed and
        printed. It runs on a thread of its own, so that a command that never ends fails the
        test. Its environment names the core's address, the token and the CA, or no CA."""
        monkeypatch.setenv("FYLGJA_API_ADDRESS", self.address)
        monkeypatch.setenv("FYLGJA_API_TOKEN", self._token())
        ca = self._ca()
        if ca is None:
            monkeypatch.delenv("FYLGJA_API_CA", raising=False)
        else:
            monkeypatch.setenv("FYLGJA_API_CA", str(ca))

        def run(*args: str) -> tuple[int, str]:
            earlier = capsys.readouterr()  # what the test printed since: shown, and kept out of this command's stdout
            with capsys.disabled():
                print(earlier.out, end="", flush=True)
            began = time.monotonic()
            answer: list[int] = []
            raised: list[BaseException] = []

            def call() -> None:
                try:
                    answer.append(thin_cli.main(list(args)))
                except BaseException as e:  # SystemExit too: kept for the test's thread to report
                    raised.append(e)

            worker = threading.Thread(target=call, daemon=True)
            worker.start()
            worker.join(DEADLINE_S)
            out, err = capsys.readouterr()
            leaked = self._token() in out or self._token() in err
            with capsys.disabled():
                status = (f"exit {answer[0]}" if answer else f"raised {type(raised[0]).__name__}" if raised
                          else "no exit")
                print(f"\n[conformance] fylgja-core {' '.join(args)}: {status} in {time.monotonic() - began:.1f}s",
                      flush=True)
                if not leaked and answer and answer[0] != 0:
                    print(err, flush=True)
            assert not leaked, "the CLI's output holds the token"
            if raised:  # its type alone: the message of an exception that escaped the CLI's own guard is not shown
                exited = raised[0].code if isinstance(raised[0], SystemExit) else None
                code = f" ({exited})" if isinstance(exited, int) else ""  # a status alone, never a text payload
                pytest.fail(f"fylgja-core {' '.join(args[:2])} raised {type(raised[0]).__name__}{code}")
            assert answer, f"fylgja-core {' '.join(args[:2])} did not end within {DEADLINE_S:g}s"
            return answer[0], out

        return run

    def record(self, twin: str) -> dict[str, Any] | None:
        """The twin's record, or None once it is gone."""
        r = self.client().get(f"/v1/twins/{twin}")
        if r.status_code == 404:
            return None
        assert r.status_code == 200, r.text
        doc: dict[str, Any] = r.json()
        return doc

    def runs(self, twin: str) -> list[dict[str, Any]]:
        """The twin's runs, newest first."""
        r = self.client().get("/v1/runs", params={"twin": twin})
        assert r.status_code == 200, r.text
        found: list[dict[str, Any]] = r.json()["runs"]
        return found

    def run(self, run_id: str) -> dict[str, Any]:
        r = self.client().get(f"/v1/runs/{run_id}")
        assert r.status_code == 200, r.text
        doc: dict[str, Any] = r.json()
        return doc

    def events(self, run_id: str) -> list[dict[str, Any]]:
        r = self.client().get(f"/v1/runs/{run_id}/events")
        assert r.status_code == 200, r.text
        found: list[dict[str, Any]] = r.json()["events"]
        return found


# Each harness, imported once what it builds on is defined above. `PROBE_LABEL` and
# `_probe_manifests` are the pure tier's (`test_conformance_scenarios.py`).
from conformance.harness.cluster import PROBE_LABEL as PROBE_LABEL  # noqa: E402
from conformance.harness.cluster import ClusterHarness  # noqa: E402
from conformance.harness.cluster import _probe_manifests as _probe_manifests  # noqa: E402
from conformance.harness.local import LocalHarness  # noqa: E402
