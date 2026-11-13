"""Every way a rehearsal ends but the main path (D-085, D-086, D-087): a refusal of the runtime's, before anything is
made or once it is, which is not the change's; a bundle the runtime cannot build and a baseline that cannot be
created, which are; a twin left or held; a run cancelled and a twin deleted by another client; the core refusing or
not answering; a source that fails; the time limit; a report that cannot be posted; and any exception the rehearsal
does not conclude from, which asks the twin's deletion and is raised again. Held to the core's own server on its fake
runtime, over a fake change source, on a clock that never waits."""

from __future__ import annotations

import json
import socket
from collections.abc import Callable, Sequence
from typing import Any

import pytest
from fylgja_core.bundle import Manifest
from fylgja_core.client import Client, FollowError, ProblemError, TransportError, UnsupportedVersion
from fylgja_core.driver import Planned, Refusal, Unplannable
from fylgja_core.findings import Finding
from fylgja_core.problem import ProblemDocument
from harness import ALICE, Clock, Served, Wrapped, wait_for
from sources import BLUEPRINTS, CHANGE, FIVE, SCOPE, FakeSource

from fylgja_orchestrator.rehearsal import (
    ChangeSource,
    Limits,
    Read,
    Report,
    Stage,
    documents,
    rehearse,
    rehearsing,
    twin_name,
    twin_prefix,
)

RUN = "run-1"
T = twin_name(CHANGE, RUN)
# Another change's twin, which no rehearsal of CHANGE touches.
UNRELATED = "rh-ffffffff-00000000"
NO_ROOM = "The twin needs 6144 MiB of memory, and the host has 1024 MiB free with 0 MiB pending."
ROOM = ["fake: 8 of 8 CPUs and 16384 of 16384 MiB free", "pending: 0 nodes, 0 CPUs, 0 MiB"]
NO_IMAGE = "No node of the runtime holds the image n1 runs."
TAKEN = "The twin's namespace is taken by another."
SHARED = Finding(rule="interface.port.shared", severity="error", object="n3:ethernet-1/1",
                 message="Port ethernet-1/1 is the runtime port of two cabled interfaces.")
LIMIT = "The rehearsal passed its time limit of 3600 s"
STOPPED = "and was stopped. Nothing is said about the change: run the checks again, or raise the limit."


def told(lines: list[str], at: Callable[[str], None] | None) -> Callable[[str], None]:
    """A rehearsal's `progress`: each line put in `lines`, then given to `at`, the test's lever on the harness."""

    def progress(line: str) -> None:
        lines.append(line)
        if at is not None:
            at(line)

    return progress


def rehearsed(
    served: Served,
    c: Clock,
    lines: list[str],
    stages: Sequence[tuple[Stage, Read | Exception]] = FIVE,
    *,
    at: Callable[[str], None] | None = None,
    core: Client | None = None,
    source: FakeSource | None = None,
) -> tuple[dict[str, Any], FakeSource]:
    """The rehearsal of `CHANGE` over `stages` (or as `source` gives it) as the run `RUN`, on the clock `c`, once its
    document validates, and the source it read and posted to; its progress put in `lines` and given to `at`."""
    source = FakeSource(CHANGE, stages) if source is None else source
    seam: ChangeSource = source  # the fake answers the seam, as mypy reads it
    doc = rehearse(seam, served.client if core is None else core, CHANGE.ref, SCOPE, run_id=RUN, limits=Limits(),
                   progress=told(lines, at), clock=c.now, sleep=c.sleep)
    assert documents.validate("rehearsal-1", doc) == []
    return doc, source


def results(doc: dict[str, Any]) -> list[str]:
    return [stage["result"] for stage in doc["stages"]]


def rules(doc: dict[str, Any]) -> list[str]:
    return [f["rule"] for f in doc["findings"]]


def pairs(found: Sequence[dict[str, Any]]) -> list[tuple[str, str | None]]:
    """Findings by rule and object, as the rehearsal compares them."""
    return [(f["rule"], f.get("object")) for f in found]


def operations(served: Served, twin: str = T) -> list[str]:
    """The operations of the twin's runs, newest first."""
    return [r["operation"] for r in served.other.list_runs(twin=twin)]


def in_order(lines: Sequence[str], expected: Sequence[str]) -> bool:
    """Whether each of `expected` is one of `lines`, each after the one before it."""
    at = 0
    for line in expected:
        if line not in lines[at:]:
            return False
        at = lines.index(line, at) + 1
    return True


def ended(served: Served, twin: str = T) -> list[dict[str, Any]] | None:
    """The twin's runs, newest first, once there is one and each has ended; else None, for `wait_for`."""
    runs = served.other.list_runs(twin=twin)
    return runs if runs and all(r["state"] == "ended" for r in runs) else None


def gone(served: Served, twin: str = T) -> bool | None:
    """True once the twin is not found, else None, for `wait_for`."""
    try:
        served.other.get_twin(twin)
    except ProblemError as e:
        if e.status == 404:
            return True
        raise
    return None


def made(served: Served, name: str) -> None:
    """A twin `name` made by the other client from `two-node` and followed to its create's end."""
    blueprint_id = served.other.put_blueprint(json.loads((BLUEPRINTS / "steps" / "two-node.json").read_text()))
    record, _ = served.other.apply_twin(name, {"blueprint_id": blueprint_id}, if_none_match="*")
    assert served.other.follow(record, ("create",)).run["verdict"]["status"] == "ok"


def untouched(served: Served, name: str = UNRELATED) -> bool:
    """Whether the twin `name` is Ready and has run nothing but its create."""
    record, _ = served.other.get_twin(name)
    ready = any(c["type"] == "Ready" and c["status"] == "True" for c in record["status"]["conditions"])
    return ready and operations(served, name) == ["create"]


def said(report: Report) -> str:
    """Everything a posted report holds, for a test that looks for a value in it."""
    return "\n".join((report.status, report.headline, report.summary, report.detail))


def sentence(doc: dict[str, Any]) -> str:
    """The headline's second line, the cause's sentence."""
    return str(doc["headline"].split("\n")[1])


def heading(doc: dict[str, Any]) -> str:
    return str(doc["headline"].split("\n")[0])


# A refusal of the runtime's: not the change's.


def test_a_look_refused_for_room_is_not_rehearsed_and_shows_the_room(served: Served) -> None:
    c, lines = Clock(), list[str]()
    served.driver.refuse = Refusal("admission.capacity", NO_ROOM)
    doc, source = rehearsed(served, c, lines)
    assert doc["status"] == "not_rehearsed"
    assert doc["headline"] == (
        "Not rehearsed: the runtime has no room\nThe runtime has no room for the twin of stage 2, seeded: The twin "
        "needs 6144 MiB of memory, and the host has 1024 MiB free with 0 MiB pending. Nothing is wrong with the "
        "change: run the checks again when the runtime has room."
    )
    assert doc["room"] == ROOM
    assert rules(doc) == ["rehearsal.capacity"]
    assert results(doc) == ["empty", "not_reached", "not_reached", "not_reached", "not_reached"]
    assert "look: stage 2, seeded: refused (admission.capacity)" in lines
    assert served.other.list_runs(twin=T) == [] and served.other.list_twins() == []
    assert c.slept == []  # nothing retried
    (posted,) = source.posted
    summary = posted.summary.split("\n")
    at = summary.index("**The room when it was refused**")
    assert summary[at + 1:at + 3] == [f"- {line}" for line in ROOM]


def test_the_room_is_left_out_when_it_cannot_be_read(served: Served) -> None:
    c, lines = Clock(), list[str]()
    served.driver.refuse = Refusal("admission.capacity", NO_ROOM)
    served.driver.fail_capacity = True
    doc, source = rehearsed(served, c, lines)
    assert doc["status"] == "not_rehearsed"
    assert doc["headline"].startswith("Not rehearsed: the runtime has no room\nThe runtime has no room for the twin "
                                      f"of stage 2, seeded: {NO_ROOM} Nothing is wrong")
    assert ("capacity",) in served.driver.calls  # read, and refused (503)
    assert "room" not in doc
    (posted,) = source.posted
    assert "The room when it was refused" not in said(posted)


def test_a_create_refused_for_room_after_the_look_passed_is_not_rehearsed(served: Served) -> None:
    c, lines = Clock(), list[str]()

    def at(line: str) -> None:
        if line.startswith("create: "):
            served.driver.refuse = Refusal("admission.capacity", NO_ROOM)

    doc, source = rehearsed(served, c, lines, at=at)
    assert doc["status"] == "not_rehearsed"
    assert rules(doc) == ["rehearsal.capacity"]
    assert sentence(doc) == (f"The runtime has no room for the twin of stage 2, seeded: {NO_ROOM} Nothing is wrong "
                             "with the change: run the checks again when the runtime has room.")
    assert doc["room"] == ROOM
    destroy, create = served.other.list_runs(twin=T)
    assert (destroy["operation"], create["operation"]) == ("destroy", "create")
    assert create["verdict"]["status"] == "rejected"
    assert [f["rule"] for f in create["verdict"]["findings"]] == ["admission.capacity"]
    assert f"destroy: {T} gone" in lines and served.other.list_twins() == []
    assert [p.status for p in source.posted] == ["not_rehearsed"]


@pytest.mark.parametrize(("rule", "message", "cause"), [
    ("admission.image.absent", NO_IMAGE, "rehearsal.image.absent"),
    ("admission.namespace.taken", TAKEN, "rehearsal.admission.refused"),
])
def test_a_create_refused_for_the_runtimes_set_up_is_not_rehearsed(
    served: Served, rule: str, message: str, cause: str
) -> None:
    c, lines = Clock(), list[str]()

    def at(line: str) -> None:
        if line.startswith("create: "):
            served.driver.refuse = Refusal(rule, message)

    doc, _ = rehearsed(served, c, lines, at=at)
    assert doc["status"] == "not_rehearsed"
    assert rules(doc) == [cause]
    assert message.removesuffix(".") in sentence(doc)
    assert "room" not in doc
    assert operations(served) == ["destroy", "create"] and served.other.list_twins() == []


def test_an_absent_image_is_not_rehearsed_and_says_what_to_do(served: Served) -> None:
    c, lines = Clock(), list[str]()
    served.driver.refuse = Refusal("admission.image.absent", NO_IMAGE)
    doc, source = rehearsed(served, c, lines)
    assert doc["status"] == "not_rehearsed"
    assert rules(doc) == ["rehearsal.image.absent"]
    assert doc["headline"] == ("Not rehearsed: an image is absent\nAn image the twin needs is not on the runtime: "
                               f"{NO_IMAGE} Import it there, then run the checks again.")
    assert "room" not in doc and ("capacity",) not in served.driver.calls
    assert served.other.list_runs(twin=T) == []
    assert [p.status for p in source.posted] == ["not_rehearsed"]


def test_any_other_refusal_of_the_look_is_the_runtimes_set_up(served: Served) -> None:
    c, lines = Clock(), list[str]()
    served.driver.refuse = Refusal("admission.namespace.taken", TAKEN)
    doc, _ = rehearsed(served, c, lines)
    assert doc["status"] == "not_rehearsed"
    assert rules(doc) == ["rehearsal.admission.refused"]
    assert doc["headline"] == (
        "Not rehearsed: the runtime refused the twin\nThe runtime refused the twin of stage 2, seeded: "
        f"{T}: The twin's namespace is taken by another (admission.namespace.taken). That is the runtime's set-up, not "
        "the change: correct it, then run the checks again."
    )
    assert "room" not in doc and served.other.list_runs(twin=T) == []


# A failure of the change's.


def test_a_stage_the_driver_cannot_plan_fails_at_that_stage(served: Served, monkeypatch: pytest.MonkeyPatch) -> None:
    c, lines = Clock(), list[str]()
    blueprint_id = served.other.put_blueprint(
        json.loads((BLUEPRINTS / "steps" / "three-node-unlinked.json").read_text()))
    third = served.other.build_bundle(blueprint_id)["id"]
    planned = served.driver.plan

    def plan(manifest: Manifest, bundle_id: str, *args: Any, **kwargs: Any) -> Planned:
        if bundle_id == third:
            raise Unplannable([SHARED])
        return planned(manifest, bundle_id, *args, **kwargs)

    monkeypatch.setattr(served.driver, "plan", plan)
    doc, source = rehearsed(served, c, lines)
    assert doc["status"] == "failed"
    assert heading(doc) == "Rehearsal failed at stage 3 of 5: third-node"
    assert sentence(doc) == ("The runtime cannot build stage 3, third-node: n3:ethernet-1/1: Port ethernet-1/1 is the "
                             "runtime port of two cabled interfaces (interface.port.shared).")
    assert "passed" not in sentence(doc)
    assert rules(doc) == ["rehearsal.stage.failed"]
    assert results(doc) == ["empty", "not_reached", "failed", "not_reached", "not_reached"]
    assert pairs(doc["stages"][2]["failures"]) == [("interface.port.shared", "n3:ethernet-1/1")]
    assert "look: stage 3, third-node: refused (plan.rejected)" in lines
    assert served.other.list_runs(twin=T) == [] and served.other.list_twins() == []
    assert [p.status for p in source.posted] == ["failed"]


def test_a_baseline_that_cannot_be_created_fails_at_the_baseline(served: Served) -> None:
    c, lines = Clock(), list[str]()
    served.pusher.refuse.add("n1")
    doc, source = rehearsed(served, c, lines)
    assert doc["status"] == "failed"
    assert rules(doc) == ["rehearsal.baseline.failed"]
    assert heading(doc) == "Rehearsal failed at stage 2 of 5: seeded"
    assert sentence(doc).startswith("The baseline, stage 2, seeded, could not be created: n1: ")
    assert sentence(doc).endswith("Nothing is said about the stages after it.")
    assert results(doc) == ["empty", "failed", "not_reached", "not_reached", "not_reached"]
    assert pairs(doc["stages"][1]["failures"]) == [("push.refused", "n1")]
    assert operations(served) == ["destroy", "create"]
    assert doc["stages"][1]["run_id"] == served.other.list_runs(twin=T)[1]["id"]
    assert f"destroy: {T} gone" in lines and served.other.list_twins() == []
    assert [p.status for p in source.posted] == ["failed"]


def test_a_create_rejected_for_what_the_look_does_not_map_fails_the_baseline(
    served: Served, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, lines = Clock(), list[str]()

    def plan(*args: Any, **kwargs: Any) -> Planned:
        raise Unplannable([SHARED])

    def at(line: str) -> None:
        if line.startswith("create: "):
            monkeypatch.setattr(served.driver, "plan", plan)

    doc, _ = rehearsed(served, c, lines, at=at)
    assert doc["status"] == "failed"
    assert rules(doc) == ["rehearsal.baseline.failed"]
    (create,) = [r for r in served.other.list_runs(twin=T) if r["operation"] == "create"]
    assert create["verdict"]["status"] == "rejected"
    assert pairs(doc["stages"][1]["failures"]) == [("interface.port.shared", "n3:ethernet-1/1")]
    assert served.other.list_twins() == []


# A twin left, held, or under the rehearsal's own name.


def test_a_destroy_that_leaves_something_keeps_the_status_and_says_what_to_do(served: Served) -> None:
    c, lines = Clock(), list[str]()
    served.driver.fail_destroy = True
    try:
        doc, source = rehearsed(served, c, lines)
    finally:
        served.driver.fail_destroy = False
    assert doc["status"] == "passed"
    assert c.slept.count(2.0) == 60
    (left,) = [f for f in doc["findings"] if f["rule"] == "rehearsal.twin.left"]
    assert left["severity"] == "warning"
    assert sentence(doc).endswith(f"The twin {T} was not removed within 120 s: read it with fylgja-core twin show {T}, "
                                  f"and remove it with fylgja-core twin destroy {T}.")
    assert f"destroy: {T} asked" in lines and f"destroy: {T} gone" not in lines
    assert [p.status for p in source.posted] == ["passed"]


def test_an_earlier_twin_that_cannot_be_removed_ends_it_not_rehearsed(served: Served) -> None:
    c, lines = Clock(), list[str]()
    earlier = twin_prefix(CHANGE) + "00000000"
    made(served, earlier)
    served.driver.fail_destroy = True
    try:
        doc, source = rehearsed(served, c, lines)
    finally:
        served.driver.fail_destroy = False
    assert doc["status"] == "not_rehearsed"
    assert rules(doc) == ["rehearsal.twin.held"]
    assert doc["headline"] == (
        f"Not rehearsed: an earlier twin is still there\nAn earlier rehearsal's twin, {earlier}, was not removed "
        f"within 120 s, so this rehearsal did not start. Remove it with fylgja-core twin destroy {earlier}, then run "
        "the checks again."
    )
    assert c.slept.count(2.0) == 60
    assert (doc["plan"], doc["stages"], doc["reclaimed"]) == (None, [], [])
    assert source.reads == []
    assert not any(call[:2] == ("admit", T) for call in served.driver.calls)
    assert served.other.list_runs(twin=T) == []
    assert [p.status for p in source.posted] == ["not_rehearsed"]


def test_a_twin_under_the_rehearsals_own_name_is_deleted_first(served: Served) -> None:
    c, lines = Clock(), list[str]()
    made(served, T)  # left by an earlier try of the same run
    doc, _ = rehearsed(served, c, lines)
    assert doc["status"] == "passed"
    assert doc["reclaimed"] == [T]
    (warning,) = [f for f in doc["findings"] if f["rule"] == "rehearsal.twin.reclaimed"]
    assert T in warning["message"]
    assert lines.index(f"reclaim: {T} deleted") < lines.index(f"create: stage 2, seeded, as {T}")
    assert operations(served) == ["destroy", "step", "step", "create", "destroy", "create"]
    assert served.other.list_twins() == []


# Another client: a run cancelled, a twin deleted.


def test_a_run_cancelled_by_another_client_stops_the_rehearsal(served: Served) -> None:
    c, lines = Clock(), list[str]()
    served.driver.block = "apply"

    def at(line: str) -> None:
        if line == f"{T}: planned":
            (create,) = served.other.list_runs(twin=T)
            served.other.cancel_run(create["id"])

    doc, source = rehearsed(served, c, lines, at=at)
    assert doc["status"] == "stopped"
    assert rules(doc) == ["rehearsal.run.cancelled"]
    assert doc["headline"] == ("Rehearsal stopped at stage 2 of 5: seeded\nThe create run of the twin was cancelled by "
                               "another client, so the rehearsal stopped at stage 2, seeded. Run the checks again.")
    destroy, create = served.other.list_runs(twin=T)
    assert (destroy["operation"], create["verdict"]["status"]) == ("destroy", "failed")
    assert [f["rule"] for f in create["verdict"]["findings"]] == ["run.cancelled"]
    assert f"destroy: {T} gone" in lines and served.other.list_twins() == []
    assert [p.status for p in source.posted] == ["stopped"]


def test_a_step_cancelled_by_another_client_before_its_apply_stops_the_rehearsal(served: Served) -> None:
    c, lines = Clock(), list[str]()

    def at(line: str) -> None:
        if line == "step: stage 3, third-node":
            served.driver.block = "admit"
        elif line == f"{T}: compiled" and served.driver.block == "admit":
            step, _ = served.other.list_runs(twin=T)
            served.other.cancel_run(step["id"])

    doc, _ = rehearsed(served, c, lines, at=at)
    assert doc["status"] == "stopped"
    assert rules(doc) == ["rehearsal.run.cancelled"]
    assert doc["headline"] == ("Rehearsal stopped at stage 3 of 5: third-node\nThe step run of the twin was cancelled "
                               "by another client, so the rehearsal stopped at stage 3, third-node. Run the checks "
                               "again.")
    assert results(doc) == ["empty", "created", "not_reached", "not_reached", "not_reached"]
    assert operations(served) == ["destroy", "step", "create"] and served.other.list_twins() == []


def test_a_step_cancelled_by_another_client_after_its_apply_began_stops_the_rehearsal(served: Served) -> None:
    c, lines = Clock(), list[str]()

    def at(line: str) -> None:
        if line == "step: stage 3, third-node":
            served.driver.block = "apply"
        elif line == f"{T}: planned" and served.driver.block == "apply":
            step, _ = served.other.list_runs(twin=T)
            served.other.cancel_run(step["id"])

    doc, source = rehearsed(served, c, lines, at=at)
    assert doc["status"] == "stopped"
    assert rules(doc) == ["rehearsal.run.cancelled"]
    assert doc["headline"] == ("Rehearsal stopped at stage 3 of 5: third-node\nThe step run of the twin was cancelled "
                               "by another client after its apply began, which left the twin diverged, so the "
                               "rehearsal stopped at stage 3, third-node. Run the checks again.")
    assert results(doc) == ["empty", "created", "not_reached", "not_reached", "not_reached"]
    destroy, step, _ = served.other.list_runs(twin=T)
    assert (destroy["operation"], step["operation"], step["verdict"]["status"]) == ("destroy", "step", "diverged")
    assert [f["rule"] for f in step["verdict"]["findings"]] == ["step.diverged"]
    assert f"destroy: {T} gone" in lines and served.other.list_twins() == []
    assert [p.status for p in source.posted] == ["stopped"]


def test_a_step_refused_for_the_runtimes_set_up_is_not_rehearsed(served: Served) -> None:
    c, lines = Clock(), list[str]()

    def at(line: str) -> None:
        if line == "step: stage 3, third-node":  # the image gone between the look and the step
            served.driver.refuse = Refusal("admission.image.absent", NO_IMAGE)

    doc, source = rehearsed(served, c, lines, at=at)
    assert doc["status"] == "not_rehearsed"
    assert rules(doc) == ["rehearsal.image.absent"]
    assert doc["headline"] == ("Not rehearsed: an image is absent\nAn image the twin needs is not on the runtime: "
                               f"{NO_IMAGE} Import it there, then run the checks again.")
    assert results(doc) == ["empty", "created", "not_reached", "not_reached", "not_reached"]
    destroy, step, _ = served.other.list_runs(twin=T)
    assert (destroy["operation"], step["operation"], step["verdict"]["status"]) == ("destroy", "step", "rejected")
    assert [f["rule"] for f in step["verdict"]["findings"]] == ["admission.image.absent"]
    assert f"destroy: {T} gone" in lines and served.other.list_twins() == []
    assert [p.status for p in source.posted] == ["not_rehearsed"]


def test_a_twin_deleted_before_a_steps_write_stops_the_rehearsal(served: Served) -> None:
    c, lines = Clock(), list[str]()
    made(served, UNRELATED)

    def at(line: str) -> None:
        if line == "step: stage 3, third-node":
            served.other.delete_twin(T)
            wait_for(lambda: gone(served))

    doc, source = rehearsed(served, c, lines, at=at)
    assert doc["status"] == "stopped"
    assert rules(doc) == ["rehearsal.twin.deleted"]
    assert doc["headline"] == (
        f"Rehearsal stopped at stage 3 of 5: third-node\nThe twin {T} was deleted while the rehearsal ran, by a newer "
        "rehearsal of this change or by hand, so it stopped at stage 3, third-node. The newer rehearsal's report "
        "stands."
    )
    assert results(doc) == ["empty", "created", "not_reached", "not_reached", "not_reached"]
    assert operations(served) == ["destroy", "create"]  # the write was refused (412): no step was run
    assert f"destroy: {T} gone" in lines
    assert untouched(served) and [t["name"] for t in served.other.list_twins()] == [UNRELATED]
    assert [p.status for p in source.posted] == ["stopped"]


def test_a_twin_deleted_during_a_steps_watch_stops_the_rehearsal(served: Served) -> None:
    c, lines = Clock(), list[str]()
    made(served, UNRELATED)

    def at(line: str) -> None:
        if line == "step: stage 3, third-node":
            served.driver.block = "apply"
        elif line == f"{T}: planned" and served.driver.block == "apply":
            served.other.delete_twin(T)

    doc, source = rehearsed(served, c, lines, at=at)
    assert doc["status"] == "stopped"
    assert rules(doc) == ["rehearsal.twin.deleted"]
    assert doc["headline"] == (
        f"Rehearsal stopped at stage 3 of 5: third-node\nThe twin {T} was deleted while the rehearsal ran, by a newer "
        "rehearsal of this change or by hand, so it stopped at stage 3, third-node. The newer rehearsal's report "
        "stands."
    )
    assert results(doc) == ["empty", "created", "not_reached", "not_reached", "not_reached"]
    assert operations(served) == ["destroy", "step", "create"]
    assert untouched(served) and [t["name"] for t in served.other.list_twins()] == [UNRELATED]
    assert [p.status for p in source.posted] == ["stopped"]


def test_a_twin_being_deleted_when_a_step_is_written_stops_the_rehearsal(served: Served) -> None:
    c, lines = Clock(), list[str]()

    def at(line: str) -> None:
        if line == "step: stage 3, third-node":
            served.driver.block = "destroy"  # the twin stays deleting: the write is refused 409 twin.deleting
            served.other.delete_twin(T)

    c.on_sleep = lambda: served.driver.release("destroy")
    doc, _ = rehearsed(served, c, lines, at=at)
    assert doc["status"] == "stopped"
    assert rules(doc) == ["rehearsal.twin.deleted"]
    assert sentence(doc).startswith(f"The twin {T} was deleted while the rehearsal ran")
    assert operations(served) == ["destroy", "create"]
    assert in_order(lines, [f"destroy: {T} asked", f"destroy: {T} gone"])
    assert served.other.list_twins() == []


def test_a_twin_not_found_when_it_is_read_stops_the_rehearsal(served: Served) -> None:
    c, lines = Clock(), list[str]()

    def at(line: str) -> None:
        if line.startswith("verify: stage 4, third-link: "):
            served.other.delete_twin(T)
            wait_for(lambda: gone(served))

    doc, _ = rehearsed(served, c, lines, at=at)  # stage 5's bundle is stage 4's: the twin is read for Ready
    assert doc["status"] == "stopped"
    assert rules(doc) == ["rehearsal.twin.deleted"]
    assert doc["headline"].startswith(f"Rehearsal stopped at stage 5 of 5: head\nThe twin {T} was deleted while the "
                                      "rehearsal ran, by a newer rehearsal of this change or by hand, so it stopped at "
                                      "stage 5, head.")
    assert results(doc) == ["empty", "created", "passed", "passed", "not_reached"]


# The core refusing, or not answering.


def test_a_token_the_core_refuses_is_not_rehearsed_and_says_what_to_do(served: Served) -> None:
    c, lines = Clock(), list[str]()
    with Client(served.address, "not-the-token") as refused:
        doc, source = rehearsed(served, c, lines, core=refused)
    assert doc["status"] == "not_rehearsed"
    assert doc["headline"] == ("Not rehearsed: the core refused the request\nThe core refused the token "
                               "(auth.token.unknown). Put a token whose hash the core's token file holds in "
                               "FYLGJA_API_TOKEN, then run the checks again.")
    assert doc["plan"] is None
    (posted,) = source.posted
    assert all("not-the-token" not in text for text in (json.dumps(doc), said(posted), *lines))
    assert served.other.list_twins() == []


def test_a_request_the_core_refuses_is_not_rehearsed_and_the_deletion_is_asked(served: Served) -> None:
    c, lines = Clock(), list[str]()
    failed = ProblemDocument(type="about:blank", title="Internal Server Error", status=500, rule="server.error",
                             detail="The server could not answer; its log has the fault.")

    def verify_twin(name: str) -> dict[str, Any]:
        raise ProblemError(500, failed)

    doc, _ = rehearsed(served, c, lines, core=Wrapped(served.client, verify_twin=verify_twin))
    assert doc["status"] == "not_rehearsed"
    assert rules(doc) == ["rehearsal.core.refused", "rehearsal.twin.left"]
    assert sentence(doc) == (
        "The core refused a request the rehearsal needs: 500 server.error: The server could not answer; its log has "
        f"the fault. Read the core's log, then run the checks again. The twin {T}'s deletion was asked and not waited "
        f"for: fylgja-core twin show {T} says whether it is gone."
    )
    assert c.slept.count(2.0) == 0
    assert wait_for(lambda: gone(served))


def test_a_core_that_does_not_answer_is_not_rehearsed(served: Served) -> None:
    c, lines = Clock(), list[str]()
    host = served.address.rpartition(":")[0]
    with socket.socket() as closed:  # a loopback port bound, then closed: nothing listens there
        closed.bind((host, 0))
        port = closed.getsockname()[1]
    with Client(f"{host}:{port}", ALICE) as away:
        doc, source = rehearsed(served, c, lines, core=away)
    assert doc["status"] == "not_rehearsed"
    assert rules(doc) == ["rehearsal.core.unreachable"]
    assert heading(doc) == "Not rehearsed: the core could not be used"
    assert sentence(doc).startswith("The core did not answer: ")
    assert sentence(doc).endswith("Check that it runs and that FYLGJA_API_ADDRESS names it, then run the checks again.")
    assert doc["plan"] is None
    assert [p.status for p in source.posted] == ["not_rehearsed"]


def test_a_core_that_stops_answering_in_mid_rehearsal_asks_the_deletion_and_waits_for_nothing(served: Served) -> None:
    c, lines = Clock(), list[str]()

    def verify_twin(name: str) -> dict[str, Any]:
        raise TransportError(f"POST /v1/twins/{name}/verifications failed: ConnectError")

    doc, _ = rehearsed(served, c, lines, core=Wrapped(served.client, verify_twin=verify_twin))
    assert doc["status"] == "not_rehearsed"
    assert rules(doc) == ["rehearsal.core.unreachable", "rehearsal.twin.left"]
    assert sentence(doc) == (
        f"The core did not answer: POST /v1/twins/{T}/verifications failed: ConnectError. Check that it runs and that "
        f"FYLGJA_API_ADDRESS names it, then run the checks again. The twin {T}'s deletion was asked and not waited "
        f"for: fylgja-core twin show {T} says whether it is gone."
    )
    assert c.slept.count(2.0) == 0
    assert f"destroy: {T} asked" in lines and f"destroy: {T} gone" not in lines
    assert wait_for(lambda: gone(served))


def test_a_deletion_that_cannot_be_asked_says_the_twin_may_still_be_there(served: Served) -> None:
    c, lines = Clock(), list[str]()

    def verify_twin(name: str) -> dict[str, Any]:
        raise TransportError(f"POST /v1/twins/{name}/verifications failed: ConnectError")

    def delete_twin(name: str, *, if_match: str | None = None) -> dict[str, Any]:
        raise TransportError(f"DELETE /v1/twins/{name} failed: ConnectError")

    try:
        doc, _ = rehearsed(served, c, lines, core=Wrapped(served.client, verify_twin=verify_twin,
                                                          delete_twin=delete_twin))
    finally:
        served.other.delete_twin(T)
        wait_for(lambda: gone(served))
    assert rules(doc) == ["rehearsal.core.unreachable", "rehearsal.twin.left"]
    assert sentence(doc).endswith(f"The twin {T} may still be there: remove it with fylgja-core twin destroy {T} once "
                                  "the core answers.")
    assert not any(line.startswith("destroy: ") for line in lines)


@pytest.mark.parametrize(("call", "fault"), [
    ("follow", FollowError("the watch of the twin ended before the loop acted on generation 1")),
    ("list_twins", UnsupportedVersion("the server speaks API '2'; this client speaks API 1")),
])
def test_a_watch_that_fails_or_a_core_of_another_api_answered_but_not_as_expected(
    served: Served, call: str, fault: Exception
) -> None:
    c, lines = Clock(), list[str]()

    def failing(*args: Any, **kwargs: Any) -> Any:
        raise fault

    doc, _ = rehearsed(served, c, lines, core=Wrapped(served.client, **{call: failing}))
    assert doc["status"] == "not_rehearsed"
    assert rules(doc)[0] == "rehearsal.core.unreachable"
    assert heading(doc) == "Not rehearsed: the core could not be used"
    assert sentence(doc).startswith(
        f"The core answered, but not as this library expects: {str(fault).removesuffix('.')}. Check the core's "
        "version against this library's, then run the checks again."
    )
    wait_for(lambda: gone(served))


# A source that fails.


def test_a_source_that_fails_is_named_by_its_type_alone(served: Served) -> None:
    c, lines = Clock(), list[str]()
    stages: list[tuple[Stage, Read | Exception]] = [*FIVE[:2], (FIVE[2][0], RuntimeError("token=s3cret")), *FIVE[3:]]
    doc, source = rehearsed(served, c, lines, stages)
    assert doc["status"] == "not_rehearsed"
    assert rules(doc) == ["rehearsal.source.failed"]
    assert doc["headline"] == ("Not rehearsed: the source could not be read\nThe change's stages could not be read "
                               "from its source (RuntimeError). Check that the source answers, then run the checks "
                               "again.")
    assert doc["plan"]["status"] == "unfinished"
    assert [s["outcome"] for s in doc["plan"]["stages"]] == ["empty", "built", "not_read", "not_read", "not_read"]
    assert served.other.list_runs(twin=T) == [] and served.other.list_twins() == []
    (posted,) = source.posted
    assert all("s3cret" not in text for text in (json.dumps(doc), said(posted), *lines))


# The time limit.


def test_the_time_limit_stops_the_rehearsal_between_calls(served: Served) -> None:
    c, lines = Clock(), list[str]()

    def at(line: str) -> None:
        if line == "step: stage 3, third-node":
            c.t += 4000

    doc, source = rehearsed(served, c, lines, at=at)
    assert doc["status"] == "stopped"
    assert rules(doc) == ["rehearsal.limit.passed"]
    assert doc["headline"] == (f"Rehearsal stopped at stage 3 of 5: third-node\n{LIMIT} at stage 3, third-node, "
                               f"{STOPPED}")
    assert results(doc) == ["empty", "created", "not_reached", "not_reached", "not_reached"]
    assert operations(served) == ["destroy", "create"]
    # The deletion asked, then read until gone, the clean-up bounded by GONE_S and not by the limit passed.
    assert in_order(lines, [f"destroy: {T} asked", f"destroy: {T} gone", "report: posted"])
    assert served.other.list_twins() == []
    assert [p.status for p in source.posted] == ["stopped"]


def test_the_time_limit_stops_it_at_a_phase_of_a_watch(served: Served) -> None:
    c, lines = Clock(), list[str]()
    served.driver.block = "apply"

    def at(line: str) -> None:
        if line == f"{T}: planned":
            c.t += 4000

    doc, _ = rehearsed(served, c, lines, at=at)
    assert doc["status"] == "stopped"
    assert rules(doc) == ["rehearsal.limit.passed"]
    assert doc["headline"] == f"Rehearsal stopped at stage 2 of 5: seeded\n{LIMIT} at stage 2, seeded, {STOPPED}"
    # `follow` let its progress raise: the watch ended at the phase, and nothing of it was said after.
    assert lines[lines.index(f"{T}: planned") + 1] == f"destroy: {T} asked"
    assert f"destroy: {T} gone" in lines
    destroy, create = served.other.list_runs(twin=T)
    assert destroy["operation"] == "destroy"
    assert [f["rule"] for f in create["verdict"]["findings"]] == ["run.cancelled"]
    assert served.other.list_twins() == []


def test_the_time_limit_at_the_look_of_a_later_stage_names_the_baseline(served: Served) -> None:
    c, lines = Clock(), list[str]()

    def at(line: str) -> None:
        if line == "look: stage 2, seeded: fits":
            c.t += 4000

    doc, _ = rehearsed(served, c, lines, at=at)
    assert doc["status"] == "stopped"
    assert doc["headline"] == f"Rehearsal stopped at stage 2 of 5: seeded\n{LIMIT} at stage 2, seeded, {STOPPED}"
    assert not any(line.startswith("look: stage 3") for line in lines)
    assert served.other.list_runs(twin=T) == [] and not any(line.startswith("destroy: ") for line in lines)


def test_the_time_limit_during_the_plan_names_no_stage_in_its_sentence(served: Served) -> None:
    c, lines = Clock(), list[str]()

    def at(line: str) -> None:
        if line == "plan: stage 3 of 5, third-node: built":
            c.t += 4000

    doc, _ = rehearsed(served, c, lines, at=at)
    assert doc["status"] == "stopped"
    assert doc["plan"]["status"] == "unfinished"
    assert sentence(doc) == f"{LIMIT} {STOPPED}"
    assert heading(doc) == "Rehearsal stopped"  # no stage is in progress while the stages are read
    assert served.other.list_runs(twin=T) == []


# The report, and the exceptions the rehearsal does not conclude from.


def test_a_report_that_cannot_be_posted_keeps_the_status(served: Served) -> None:
    c, lines = Clock(), list[str]()
    source = FakeSource(CHANGE, FIVE)
    source.fail_post = RuntimeError("s3cret")
    doc, _ = rehearsed(served, c, lines, source=source)
    assert doc["status"] == "passed"
    assert doc["findings"][-1] == documents.finding(
        "rehearsal.report.unposted", "warning",
        'The report could not be posted on Change "third link" (RuntimeError); the status stands.')
    assert lines[-1] == "report: not posted"
    assert source.posted == []
    assert all("s3cret" not in text for text in (json.dumps(doc), *lines))


def test_a_fault_of_the_renderer_is_raised_and_not_blamed_on_the_source(
    served: Served, monkeypatch: pytest.MonkeyPatch
) -> None:
    c, lines = Clock(), list[str]()
    source = FakeSource(CHANGE, FIVE)

    def render(document: dict[str, Any], *, limit: int | None) -> Report:
        raise RuntimeError("the renderer's own fault")

    monkeypatch.setattr(rehearsing, "render", render)
    with pytest.raises(RuntimeError, match="the renderer's own fault"):
        rehearsed(served, c, lines, source=source)
    assert source.posted == []
    assert not any(line.startswith("report: ") for line in lines)
    assert f"destroy: {T} gone" in lines and served.other.list_twins() == []


class Stop(BaseException):
    """An exception of whoever runs the rehearsal, which it does not conclude from."""


@pytest.mark.parametrize("stop", [KeyboardInterrupt, Stop])
def test_any_base_exception_asks_the_deletion_and_is_raised_again(served: Served, stop: type[BaseException]) -> None:
    c, lines = Clock(), list[str]()
    source = FakeSource(CHANGE, FIVE)
    served.driver.block = "apply"

    def at(line: str) -> None:
        if line == f"{T}: planned":
            raise stop()

    with pytest.raises(stop):
        rehearsed(served, c, lines, source=source, at=at)
    assert source.posted == []
    assert not any(line.startswith("destroy: ") for line in lines)  # asked, and waited for by nothing
    assert wait_for(lambda: gone(served))
    destroy, create = wait_for(lambda: ended(served))
    assert (destroy["operation"], create["operation"]) == ("destroy", "create")
    assert create["verdict"]["status"] == "failed"
    assert [f["rule"] for f in create["verdict"]["findings"]] == ["run.cancelled"]


# The source's words.

AGAIN = "Ask once more."


def _cancelled(served: Served, source: FakeSource) -> dict[str, Any]:
    served.driver.block = "apply"

    def at(line: str) -> None:
        if line == f"{T}: planned":
            (create,) = served.other.list_runs(twin=T)
            served.other.cancel_run(create["id"])

    return rehearsed(served, Clock(), [], at=at, source=source)[0]


def _no_room(served: Served, source: FakeSource) -> dict[str, Any]:
    served.driver.refuse = Refusal("admission.capacity", NO_ROOM)
    return rehearsed(served, Clock(), [], source=source)[0]


def _source_fails(served: Served, source: FakeSource) -> dict[str, Any]:
    return rehearsed(served, Clock(), [], source=source)[0]


def _core_away(served: Served, source: FakeSource) -> dict[str, Any]:
    host = served.address.rpartition(":")[0]
    with socket.socket() as closed:  # a loopback port bound, then closed: nothing listens there
        closed.bind((host, 0))
        port = closed.getsockname()[1]
    with Client(f"{host}:{port}", ALICE) as away:
        return rehearsed(served, Clock(), [], core=away, source=source)[0]


def _limit(served: Served, source: FakeSource) -> dict[str, Any]:
    c = Clock()

    def at(line: str) -> None:
        if line == "step: stage 3, third-node":
            c.t += 4000

    return rehearsed(served, c, [], at=at, source=source)[0]


FAILING: list[tuple[Stage, Read | Exception]] = [*FIVE[:2], (FIVE[2][0], RuntimeError("away")), *FIVE[3:]]


@pytest.mark.parametrize(("arranged", "stages", "rule", "ending"), [
    (_cancelled, FIVE, "rehearsal.run.cancelled", " Ask once more."),
    (_no_room, FIVE, "rehearsal.capacity", ": ask once more when the runtime has room."),
    (_source_fails, FAILING, "rehearsal.source.failed", ", then ask once more."),
    (_core_away, FIVE, "rehearsal.core.unreachable", ", then ask once more."),
    (_limit, FIVE, "rehearsal.limit.passed", ": ask once more, or raise the limit."),
], ids=["run cancelled", "no room", "source fails", "core away", "limit"])
def test_each_remedy_is_said_in_the_sources_words(
    served: Served,
    arranged: Callable[[Served, FakeSource], dict[str, Any]],
    stages: Sequence[tuple[Stage, Read | Exception]],
    rule: str,
    ending: str,
) -> None:
    doc = arranged(served, FakeSource(CHANGE, stages, again=AGAIN))
    cause = doc["findings"][0]
    assert cause["rule"] == rule
    assert cause["message"].endswith(ending)
    assert "checks" not in cause["message"]
