"""The example's NetBox contract tier's judgments of what it finds on NetBox, over rows a test builds: the installed
webhook held to the trigger `make netbox-hook` installs before the hook module writes it back, and a failed background
task deleted only where the session made it. Nothing here opens a socket."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from contract_netbox import conftest
from contract_netbox.conftest import HOOK, SENDING, Failed, in_turn, trigger_fault

DEPLOYMENT = "8481f7fc-2f3a-4f8c-a990-27526c6fe860"
CREATE = f"/api/deployments/{DEPLOYMENT}/create_flow_run"


def webhook(url: str) -> dict[str, Any]:
    return {"id": 3, "name": "fylgja-rehearse", "payload_url": url}


def test_the_webhook_make_netbox_hook_installs_is_taken() -> None:
    assert HOOK.RECEIVER == "host.docker.internal:4200"
    assert trigger_fault(webhook(f"http://{HOOK.RECEIVER}{CREATE}")) is None


def test_no_webhook_installed_is_taken_and_the_module_deletes_what_it_makes() -> None:
    assert trigger_fault(None) is None


@pytest.mark.parametrize(
    "url",
    [
        f"http://host.docker.internal:45123{CREATE}",
        f"http://192.0.2.1:4200{CREATE}",
        f"https://{HOOK.RECEIVER}{CREATE}",
        f"http://{HOOK.RECEIVER}/api/deployments/not-an-id/create_flow_run",
        f"http://{HOOK.RECEIVER}/api/deployments/{DEPLOYMENT}/",
        f"http://{HOOK.RECEIVER}{CREATE}?x=1",
        "not a URL at all",
    ],
    ids=["a port of a run killed before its end", "another host", "another scheme", "no deployment's id",
         "no create_flow_run", "a query", "no URL"],
)
def test_a_webhook_no_make_netbox_hook_wrote_is_refused_naming_the_repair(url: str) -> None:
    said = trigger_fault(webhook(url))
    assert said is not None
    assert "make netbox-hook" in said and "fylgja-rehearse" in said and HOOK.RECEIVER in said


def test_a_webhook_with_no_address_is_refused() -> None:
    assert trigger_fault({"id": 3, "name": "fylgja-rehearse", "payload_url": None}) is not None


BEGAN = datetime(2026, 11, 13, 4, 0, tzinfo=UTC)


def task(func: str, at: datetime | None) -> dict[str, Any]:
    return {"func_name": func, "created_at": at.isoformat().replace("+00:00", "Z") if at else None}


@pytest.mark.parametrize(
    ("row", "ours"),
    [
        (task(SENDING, BEGAN + timedelta(seconds=3)), True),
        (task(SENDING, BEGAN), True),
        (task(SENDING, BEGAN - timedelta(seconds=1)), False),
        (task("core.jobs.sync", BEGAN + timedelta(seconds=3)), False),
        (task(SENDING, None), False),
    ],
    ids=["a sending since the start", "a sending at the start", "a sending before the start", "another task",
         "a sending of no time"],
)
def test_only_a_sending_made_since_the_session_began_is_the_sessions(row: dict[str, Any], ours: bool) -> None:
    assert Failed(set(), BEGAN).ours(row) is ours


def test_each_step_of_an_end_runs_whatever_the_one_before_it_raised() -> None:
    """The hook module's end: the trigger's write-back, each process's end and each check run in turn, so that one
    failing skips none of the others, and the first failure is raised once all have run."""
    ran: list[str] = []

    def failing(name: str) -> None:
        ran.append(name)
        raise RuntimeError(name)

    with pytest.raises(RuntimeError, match="the write-back"):
        in_turn(lambda: failing("the write-back"), lambda: ran.append("the runner's end"),
                lambda: failing("a check"), lambda: ran.append("the home's removal"))
    assert ran == ["the write-back", "the runner's end", "a check", "the home's removal"]


class Leftover:
    """A writer whose branches list holds one of the tier's: what the session's end reads last."""

    def __init__(self) -> None:
        self.listed_paths: list[str] = []

    def listed(self, path: str, **params: object) -> list[dict[str, Any]]:
        self.listed_paths.append(path)
        return [{"name": "fylgja-contract-0a1b2c3d"}]


class Refused:
    """A `Failed` whose end raises, as a sign-in NetBox refuses would."""

    def ended(self, box: object) -> None:
        raise RuntimeError("the failed tasks could not be read")


def test_the_sessions_end_reads_the_branches_left_whatever_the_failed_tasks_end_raised() -> None:
    box = Leftover()
    with pytest.raises(RuntimeError, match="could not be read"):
        conftest.session_end(Refused(), box)  # type: ignore[arg-type]
    assert box.listed_paths == [conftest.BRANCHES], "the branches were not read after the failed tasks' end raised"
