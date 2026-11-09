"""Phase 5's kills of a step, a deletion after one and a cancel, on any driver (design/core.md,
phase 6, "The conformance suite"). The twin `cf-skill`, kept on `two-node` by `reads.kill_base`,
steps to `three-node`, a node added, with the core killed at each phase boundary of the step,
`IN_APPLY_S` into its apply, and `CUT_S` into it before a deletion asked at once: each resume
ends the same run `stepped`, every node the dry run keeps at its incarnation (D-050, D-054), and
the deletion removes everything, the node the apply cut short added among it (D-055). The twin
`cf-cancel`, created from `two-node`, has its step to `three-node` cancelled `CUT_S` into the
apply: no rollback (D-029), the twin is left diverged, refuses a new spec, still answers verify,
and is deleted whole.

Each step is read before it is asked: its dry run (`reads.expected`), the twin's incarnations,
its runs and the log's mark, so that "the same run, the only one since" is the scenario's own on
a store that keeps a destroyed twin's runs. What only the runtime's own account shows (the
applies around a kill, the stray apply a kill leaves and a destroy waits for, the node a destroy
removes first) is asserted behind the harness's audits. The tests run in order; each prints what
it took and what it saw (`-s`).
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from conformance.harness import Fylgja, Harness, Resume
from conformance.reads import (
    BLUEPRINT,
    IN_APPLY_S,
    RESTART,
    STEPS,
    Expected,
    apply_ended,
    apply_started,
    assert_events_whole,
    assert_resumed,
    assert_twin_record,
    created,
    expected,
    incarnations,
    kill_base,
    remove,
    resumed_after,
    run_ids,
    runs_since,
    settled,
    settled_ready,
    started,
    stepped_until,
    twin_nodes,
    wait_for,
)
from fylgja_core import schemas

SKILL = "cf-skill"
CANCEL = "cf-cancel"
TWO_NODE = STEPS / "two-node.json"
UNLINKED = STEPS / "three-node-unlinked.json"
KILL_AT = ("compiled", "admitted", "planned", "applied", "ready", "pushed", "verified")
"""Each phase boundary of a step a kill follows: before `applied` a step records its phases in
`last_step.phase` alone, from it on in `phase` too (D-054). A kill lands after the boundary it
follows, not at it (verified-facts.md): the first three phases are recorded within about 50 ms, so
one that follows `compiled` or `admitted` has mostly found the step at `planned`, on both drivers,
and the run ends about 10 ms after `verified`, so one that follows it has found the run ended."""
STEP_PHASES = (*KILL_AT, "flows")
"""A step's phases in order: a resume never starts before the phase a kill followed."""
CUT_S = 5
"""How long after its `apply` started a scenario cuts a step short, by a kill and a deletion or by
a cancel: well inside the apply of the node `three-node` adds."""
ADDED_S = 60.0
"""How long the runtime may take to show the node an apply cut short added."""


def step_asked(fylgja: Fylgja, twin: str, e: Expected) -> None:
    """`twin step <twin> --blueprint three-node --no-wait`, with `--allow-restart` where the dry run
    `e` refuses the step without it, as `reads.walk` steps: exit 0, the spec written."""
    code, _ = fylgja("twin", "step", twin, "--blueprint", str(BLUEPRINT), "--no-wait",
                     *(["--allow-restart"] if e.refused == RESTART else []))
    assert code == 0


# A core killed at each phase boundary of a step, and in its apply.


@pytest.mark.parametrize("phase", KILL_AT)
def test_a_core_killed_at_a_step_phase_resumes_the_same_run_to_stepped(
    harness: Harness, fylgja: Fylgja, caps: dict[str, Any], phase: str
) -> None:
    kill_base(harness, fylgja, caps, SKILL, TWO_NODE)
    e = expected(harness, fylgja, caps, SKILL, BLUEPRINT)
    held, before, since = incarnations(harness, SKILL), run_ids(harness, SKILL), harness.mark()
    began = time.monotonic()
    seen = stepped_until(harness, fylgja, SKILL, BLUEPRINT, phase, allow_restart=e.refused == RESTART)
    killed = time.monotonic()
    back = harness.kill()  # the kill follows the phase's record at once
    served_at = datetime.now(UTC)  # the core serving again after the kill
    after = harness.record(SKILL)
    assert after is not None
    run_id = seen["status"]["last_step"]["run_id"]
    print(f"[conformance] killed at {phase}, {killed - began:.1f}s into the step; serving again {back:.2f}s after "
          f"the kill, the record at phase {after['status'].get('phase')}, last step "
          f"{after['status']['last_step']['outcome']} at {after['status']['last_step']['phase']}", flush=True)
    record = settled_ready(harness, SKILL)
    resumed = time.monotonic() - killed
    events = assert_resumed(harness, fylgja, SKILL, BLUEPRINT, run_id, record, e=e, runs_before=before,
                            incarnations_before=held, since=since)
    applies, point = started(events, "apply"), resumed_after(harness, since, run_id)
    after_applied = KILL_AT.index(phase) >= KILL_AT.index("applied")
    print(f"[conformance] killed at {phase}: resumed after {point or 'nothing (the run had ended)'}, stepped "
          f"{resumed:.1f}s after the kill ({time.monotonic() - began:.1f}s after the step), the same run {run_id}; "
          f"{applies} apply started", flush=True)
    if point is None:
        # Nothing resumed it, by the core's log: allowed only for a run that had ended before the core served
        # again, by its `ended_at` (the core's clock against this host's: one clock locally, and two on the
        # cluster that agreed within about 50 ms, verified-facts.md). A resume the log did not name would end
        # after that, unless only `flows` was left of it. A time taken before the kill would not do: a harness
        # reads before its kill lands, and a step's run ends about 10 ms after `verified` (verified-facts.md).
        ended_at = harness.run(run_id).get("ended_at")
        run_ended = None if ended_at is None else datetime.fromisoformat(ended_at)
        if run_ended is not None:
            print(f"[conformance] the run ended {(served_at - run_ended).total_seconds():.2f}s before the core served "
                  f"again, {(served_at - timedelta(seconds=back) - run_ended).total_seconds():+.3f}s before the "
                  "kill's own moment", flush=True)
        over = run_ended is not None and run_ended < served_at
        assert over, f"the core's log names no resume of the run {run_id}, which had not ended when the core served"
    else:
        # A resume never starts before the phase the kill followed: the record moved first.
        assert point in STEP_PHASES and STEP_PHASES.index(point) >= STEP_PHASES.index(phase), point
    if after_applied:
        # The apply ended before the kill: nothing is applied again.
        assert applies == 1, f"{applies} apply started after {phase} was recorded"
    else:
        # Before `applied` the kill may land before the apply began (one apply), or in it: the resume
        # applies again (two).
        assert 1 <= applies <= 2, f"{applies} apply started"
    harness.audit_resume(SKILL, since, Resume("step", applies, after_applied, in_apply=False))


def test_a_core_killed_in_a_steps_apply_resumes_the_same_run_to_stepped(
    harness: Harness, fylgja: Fylgja, caps: dict[str, Any]
) -> None:
    """Killed `IN_APPLY_S` into the step's apply, read just before the kill as started and not
    ended: the resume applies the step again and ends the same run `stepped`."""
    kill_base(harness, fylgja, caps, SKILL, TWO_NODE)
    e = expected(harness, fylgja, caps, SKILL, BLUEPRINT)
    held, before, since = incarnations(harness, SKILL), run_ids(harness, SKILL), harness.mark()
    step_asked(fylgja, SKILL, e)
    run_id = apply_started(harness, SKILL, "step", before)
    applying = time.monotonic()
    time.sleep(IN_APPLY_S)
    assert not apply_ended(harness, run_id), f"the apply ended within {IN_APPLY_S}s"
    killed = time.monotonic()
    back = harness.kill()
    record = settled_ready(harness, SKILL)
    resumed = time.monotonic() - killed
    events = assert_resumed(harness, fylgja, SKILL, BLUEPRINT, run_id, record, e=e, runs_before=before,
                            incarnations_before=held, since=since)
    applies, verdict = started(events, "apply"), harness.run(run_id)["verdict"]
    # Two applies on either kind of driver, for a reason the capabilities name: a driver that declares
    # `reapply` applies again, which finishes the apply cut short (D-068); one that does not first probes
    # its nodes, finds each answering, and then applies again plainly (D-050). The print says which.
    why = ("the driver applies again (reapply, D-068)" if caps["reapply"]
           else "the resume probes the nodes, each answering, and applies again plainly (D-050)")
    print(f"[conformance] killed {killed - applying:.1f}s into the step's apply, serving again {back:.2f}s after the "
          f"kill: stepped {resumed:.1f}s after the kill, the same run {run_id}; {applies} apply started: {why}",
          flush=True)
    assert applies == 2, f"{applies} apply started"
    assert not [f for f in verdict["findings"] if f["rule"] == "step.node.silent"], verdict["findings"]
    harness.audit_resume(SKILL, since, Resume("step", applies, after_applied=False, in_apply=True))


# A deletion right after a kill in a step's apply.


def test_a_deletion_right_after_a_kill_in_a_steps_apply_leaves_nothing(
    harness: Harness, fylgja: Fylgja, caps: dict[str, Any]
) -> None:
    """The twin's deletion asked at once after the core is killed `CUT_S` into a step's apply: the
    step is cancelled, `diverged` since its apply had begun, and the destroy removes everything,
    the node the apply cut short added among it, which the deployment it destroys does not name."""
    try:
        kill_base(harness, fylgja, caps, SKILL, TWO_NODE)
        e = expected(harness, fylgja, caps, SKILL, BLUEPRINT)
        before, since = run_ids(harness, SKILL), harness.mark()
        step_asked(fylgja, SKILL, e)
        run_id = apply_started(harness, SKILL, "step", before)
        time.sleep(CUT_S)
        assert not apply_ended(harness, run_id), f"the apply ended within {CUT_S}s"
        killed = time.monotonic()
        back = harness.kill()
        began = time.monotonic()
        code, out = fylgja("twin", "destroy", SKILL)
        print(f"[conformance] deleted {began - killed:.1f}s after a kill {CUT_S}s into the step's apply, serving "
              f"again {back:.2f}s after the kill: gone {time.monotonic() - began:.1f}s after it was asked", flush=True)
        # Held as a bool: the CLI's output lists node addresses, and is never printed.
        said_deleted = f"twin {SKILL} deleted" in out
        assert code == 0 and said_deleted, code
        assert harness.record(SKILL) is None
        made = runs_since(harness, SKILL, before)  # newest first
        assert [r["operation"] for r in made] == ["destroy", "step"] and made[1]["id"] == run_id, \
            [(r["operation"], r["id"]) for r in made]
        destroy, step_run = made
        for run in made:
            assert "verdict" in run, run
            assert list(schemas.validator("findings-1").iter_errors(run["verdict"])) == [], run["verdict"]
            assert_events_whole(harness.events(run["id"]))
        print(f"[conformance] the step run: {step_run['verdict']['status']} "
              f"{[(f['rule'], f.get('object')) for f in step_run['verdict']['findings']]}; the destroy run: "
              f"{destroy['verdict']['status']}", flush=True)
        assert (destroy["verdict"]["status"], step_run["verdict"]["status"]) == ("ok", "diverged")
        harness.audit_destroy(SKILL, since, unnamed=tuple(e.added), stray=True)
        assert harness.leftovers(SKILL) == []
    finally:
        remove(harness, SKILL)


# A step cancelled in its apply: diverged, and then deleted whole.


def test_a_step_cancelled_in_its_apply_ends_diverged_and_the_twin_is_then_deleted_whole(
    harness: Harness, fylgja: Fylgja, caps: dict[str, Any]
) -> None:
    try:
        base = created(harness, fylgja, CANCEL, TWO_NODE, twin_nodes(TWO_NODE))["status"]
        e = expected(harness, fylgja, caps, CANCEL, BLUEPRINT)
        before, since = run_ids(harness, CANCEL), harness.mark()
        step_asked(fylgja, CANCEL, e)
        run_id = apply_started(harness, CANCEL, "step", before)
        time.sleep(CUT_S)
        assert not apply_ended(harness, run_id), f"the apply ended within {CUT_S}s"

        began = time.monotonic()
        asked = harness.client().post(f"/v1/runs/{run_id}/cancel")
        assert asked.status_code == 202, asked.text

        def ended_run() -> dict[str, Any] | None:
            run = harness.run(run_id)
            return run if run["state"] == "ended" else None

        run = wait_for(ended_run, "the cancelled step's end", every_s=0.1)
        print(f"[conformance] cancelled {CUT_S}s into the step's apply: the run ended {time.monotonic() - began:.2f}s "
              "after the cancel was asked", flush=True)
        assert_events_whole(harness.events(run_id))
        verdict = run["verdict"]
        assert list(schemas.validator("findings-1").iter_errors(verdict)) == [], verdict
        print(f"[conformance] the step's verdict: {verdict['status']} "
              f"{[(f['rule'], f.get('object'), f['message']) for f in verdict['findings']]}", flush=True)
        diverged = [f for f in verdict["findings"] if f["rule"] == "step.diverged"]
        assert verdict["status"] == "diverged" and len(diverged) == 1, verdict
        assert "cancelled during apply" in diverged[0]["message"], diverged[0]

        record = wait_for(lambda: r if (r := harness.record(CANCEL)) is not None and settled(r) else None,
                          f"{CANCEL} settled")
        assert_twin_record(record)
        status = record["status"]
        conditions = {c["type"]: (c["status"], c.get("reason")) for c in status["conditions"]}
        assert conditions["Diverged"] == ("True", "step.diverged"), conditions
        assert conditions["Ready"] == ("False", "step.diverged"), conditions
        last = status["last_step"]
        assert (last["outcome"], last["run_id"]) == ("diverged", run_id), last
        # Cut short before `applied`: the record describes the twin it ran, its deployment the old one.
        assert last["phase"] == "planned" and status["bundle_id"] == base["bundle_id"], last
        assert status["deployment_id"] == base["deployment_id"]
        print(f"[conformance] the record: Diverged {conditions['Diverged']}, Ready {conditions['Ready']}, last step "
              f"{last['outcome']} at {last['phase']}", flush=True)

        # A diverged twin accepts only deletion: a new spec is refused.
        filed = harness.client().post("/v1/blueprints", json=json.loads(UNLINKED.read_text()))
        assert filed.status_code in (200, 201), filed.text
        refused = harness.client().put(f"/v1/twins/{CANCEL}", json={"spec": {"blueprint_id": filed.json()["id"]}})
        print(f"[conformance] a PUT of {UNLINKED.stem}: {refused.status_code} {refused.json().get('rule')}", flush=True)
        assert refused.status_code == 409 and refused.json()["rule"] == "twin.diverged", refused.text

        # Verify still answers, against the bundle the record names, the one the twin ran (D-054).
        code, out = fylgja("twin", "verify", CANCEL, "--json")
        assert out.strip(), f"twin verify {CANCEL} printed nothing: exit {code}"
        answer = json.loads(out)
        print(f"[conformance] twin verify of the diverged twin: exit {code}, {answer['status']} "
              f"{answer.get('counts')}, findings {[(f['rule'], f.get('object')) for f in answer['findings']]}",
              flush=True)
        assert (code, answer["status"]) in ((0, "ok"), (1, "nonconforming")), (code, answer["status"])
        assert answer["subject"]["bundle_id"] == base["bundle_id"]

        # The deletion removes everything, the node the apply cut short added among it.
        wait_for(lambda: True if e.added <= set(harness.nodes(CANCEL)) else None,
                 f"{sorted(e.added)} in the runtime the destroy is asked of", timeout_s=ADDED_S)
        began = time.monotonic()
        code, out = fylgja("twin", "destroy", CANCEL)
        print(f"[conformance] the diverged twin destroyed in {time.monotonic() - began:.1f}s", flush=True)
        # Held as a bool: the CLI's output lists node addresses, and is never printed.
        said_deleted = f"twin {CANCEL} deleted" in out
        assert code == 0 and said_deleted, code
        assert harness.record(CANCEL) is None
        destroy = runs_since(harness, CANCEL, before)[0]
        assert "verdict" in destroy and (destroy["operation"], destroy["verdict"]["status"]) == ("destroy", "ok"), \
            destroy
        harness.audit_destroy(CANCEL, since, unnamed=tuple(e.added))
        assert harness.leftovers(CANCEL) == []
    finally:
        remove(harness, CANCEL)
