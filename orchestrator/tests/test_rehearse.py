"""The rehearsal of a change (D-086): one twin a rehearsal, named from the change and the run; the change's other twins
deleted first; every stage planned and looked at by a dry run; the baseline created and settled by asking verify
again; each later stage stepped, restarts allowed, and verified, a failure the baseline did not have being the
change's; the twin destroyed on every path; the document written and the report posted (D-087). Held to the core's
own server on its fake runtime, over a fake change source, on a clock that never waits."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from fylgja_core.client import Client
from fylgja_core.findings import Finding
from harness import Clock, Served, Wrapped
from sources import BLUEPRINTS, CHANGE, FIVE, SCOPE, FakeSource, built, empty, refused

from fylgja_orchestrator.rehearsal import (
    ChangeSource,
    Limits,
    Read,
    Stage,
    documents,
    rehearse,
    report,
    twin_name,
    twin_prefix,
)
from fylgja_orchestrator.rehearsal.report import ALREADY, FIDELITY, VERIFIED

RUN = "run-1"
T = twin_name(CHANGE, RUN)
STALE = Finding(rule="artifact.stale", severity="error", object="n1",
                message="n1's configuration is older than its intent.")


def rehearsed(
    served: Served,
    stages: Sequence[tuple[Stage, Read | Exception]],
    c: Clock,
    lines: list[str] | None = None,
    *,
    core: Client | None = None,
    progress: Callable[[str], None] | None = None,
) -> tuple[dict[str, Any], FakeSource]:
    """The rehearsal of `CHANGE` over `stages` as the run `RUN`, on the clock `c`, once its document validates, and the
    source it read and posted to; its progress put in `lines`, or given to `progress`."""
    source = FakeSource(CHANGE, stages)
    told = progress if progress is not None else (lines.append if lines is not None else None)
    seam: ChangeSource = source  # the fake answers the seam, as mypy reads it
    doc = rehearse(seam, served.client if core is None else core, CHANGE.ref, SCOPE, run_id=RUN, limits=Limits(),
                   progress=told, clock=c.now, sleep=c.sleep)
    assert documents.validate("rehearsal-1", doc) == []
    return doc, source


def results(doc: dict[str, Any]) -> list[str]:
    return [stage["result"] for stage in doc["stages"]]


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


def test_a_change_is_rehearsed_stage_by_stage_on_one_twin_and_reported(served: Served) -> None:
    c, lines = Clock(), list[str]()
    doc, source = rehearsed(served, FIVE, c, lines)
    assert doc["status"] == "passed"
    assert doc["headline"] == f"Rehearsal passed: 5 stages\n{VERIFIED}"
    assert results(doc) == ["empty", "created", "passed", "passed", "skipped"]
    stages = doc["stages"]
    assert all(s["counts"]["failed"] == 0 and s["counts"]["held"] > 0 for s in stages[1:4])
    assert "counts" not in stages[4]
    assert (doc["twin"], doc["run_id"], doc["findings"], doc["already_failing"]) == (T, RUN, [], [])
    assert operations(served) == ["destroy", "step", "step", "create"]
    assert [s["run_id"] for s in stages[1:4]] == [r["id"] for r in reversed(served.other.list_runs(twin=T)[1:])]
    assert served.other.list_twins() == [] and served.driver.labs == {}
    (posted,) = source.posted
    assert (posted.status, posted.headline) == ("passed", doc["headline"])
    assert "| 5 | head | nothing | unchanged | not run again |" in posted.summary.split("\n")
    assert posted.summary.endswith(FIDELITY)
    assert posted == report.render(doc, limit=source.comment_limit)
    assert 5.0 not in c.slept
    assert in_order(lines, [f"create: stage 2, seeded, as {T}", "step: stage 3, third-node", "skip: stage 5, head: "
                            "unchanged", f"destroy: {T} gone", "report: posted"])
    assert lines[:5] == [f"plan: stage {k} of 5, {s[0].label}: {'empty' if k == 1 else 'built'}"
                         for k, s in enumerate(FIVE, 1)]
    assert in_order(lines, [f"look: stage {k}, {label}: fits" for k, label in ((2, "seeded"), (3, "third-node"),
                                                                                (4, "third-link"))])
    assert not any(line.startswith("look: stage 5") for line in lines)


def made(served: Served, name: str) -> None:
    """A twin `name` made by the other client from `two-node` and followed to its create's end."""
    blueprint_id = served.other.put_blueprint(json.loads((BLUEPRINTS / "steps" / "two-node.json").read_text()))
    record, _ = served.other.apply_twin(name, {"blueprint_id": blueprint_id}, if_none_match="*")
    assert served.other.follow(record, ("create",)).run["verdict"]["status"] == "ok"


def ready(record: dict[str, Any]) -> bool:
    return any(c["type"] == "Ready" and c["status"] == "True" for c in record["status"]["conditions"])


def test_the_rehearsal_deletes_the_changes_other_twins_first_and_no_other(served: Served) -> None:
    earlier, unrelated = twin_prefix(CHANGE) + "00000000", "rh-ffffffff-00000000"
    made(served, earlier)
    made(served, unrelated)
    c, lines = Clock(), list[str]()
    doc, _ = rehearsed(served, FIVE, c, lines)
    assert doc["status"] == "passed"
    assert doc["reclaimed"] == [earlier]
    (warning,) = [f for f in doc["findings"] if f["rule"] == "rehearsal.twin.reclaimed"]
    assert warning["severity"] == "warning" and earlier in warning["message"]
    assert f"reclaim: {earlier} deleted" in lines
    assert lines.index(f"reclaim: {earlier} deleted") < lines.index(f"create: stage 2, seeded, as {T}")
    (destroyed,) = [r for r in served.other.list_runs(twin=earlier) if r["operation"] == "destroy"]
    (created,) = [r for r in served.other.list_runs(twin=T) if r["operation"] == "create"]
    assert datetime.fromisoformat(destroyed["ended_at"]) < datetime.fromisoformat(created["created_at"])
    record, _ = served.other.get_twin(unrelated)
    assert ready(record) and operations(served, unrelated) == ["create"]
    assert [t["name"] for t in served.other.list_twins()] == [unrelated]


def test_a_plan_refused_fails_at_that_stage_and_makes_no_twin(served: Served) -> None:
    c = Clock()
    doc, source = rehearsed(served, [*FIVE[:2], refused("third-node", STALE), *FIVE[3:]], c)
    assert doc["status"] == "failed"
    assert doc["plan"]["status"] == "refused"
    assert doc["headline"].splitlines() == ["Rehearsal failed at stage 3 of 5: third-node",
                                            doc["plan"]["headline"].splitlines()[1]]
    assert results(doc) == ["empty", "not_reached", "failed", "not_reached", "not_reached"]
    assert pairs(doc["stages"][2]["failures"]) == [("artifact.stale", "n1")]
    assert doc["findings"] == doc["plan"]["findings"]
    (posted,) = source.posted
    assert posted.status == "failed"
    assert served.driver.calls == [] and served.other.list_twins() == []


def test_a_change_with_nothing_to_build_is_not_rehearsed(served: Served) -> None:
    c = Clock()
    doc, source = rehearsed(served, [empty("branch-point"), empty("head")], c)
    assert doc["status"] == "not_rehearsed"
    assert [f["rule"] for f in doc["findings"]] == ["rehearsal.stages.none"]
    assert results(doc) == ["empty", "empty"]
    assert doc["headline"].splitlines()[0] == "Not rehearsed: no stage to build"
    assert [p.status for p in source.posted] == ["not_rehearsed"]
    assert served.driver.calls == []


def test_the_baseline_is_settled_by_asking_verify_again(served: Served) -> None:
    c, lines = Clock(), list[str]()
    served.reader.unreadable.add((T, "n1"))

    def on_sleep() -> None:
        if len(c.slept) == 2:
            served.reader.unreadable.discard((T, "n1"))

    c.on_sleep = on_sleep
    doc, _ = rehearsed(served, FIVE, c, lines)
    assert doc["status"] == "passed"
    assert c.slept[:2] == [5.0, 5.0] and c.slept.count(5.0) == 2
    assert doc["already_failing"] == []
    assert "wait" not in doc["stages"][1] and doc["stages"][1]["counts"]["failed"] == 0
    assert "settle: verify failed, 0s of 180s" in lines
    assert "settle: verify ok, 10s of 180s" in lines


def test_what_the_baseline_never_verifies_is_failing_before_the_change(served: Served) -> None:
    c = Clock()
    served.reader.unreadable.add((T, "n1"))
    doc, source = rehearsed(served, FIVE, c)
    assert c.slept.count(5.0) == 36
    assert pairs(doc["already_failing"]) == [("verify.node.unread", "n1")]
    assert doc["stages"][1]["wait"] == {"budget_s": 180, "after_s": 180.0}
    assert doc["status"] == "passed"
    assert results(doc) == ["empty", "created", "passed", "passed", "skipped"]
    assert doc["headline"].splitlines()[1] == ALREADY
    summary = source.posted[0].summary.split("\n")
    at = summary.index("**Already failing before this change**")
    assert summary[at + 1].startswith("- `verify.node.unread` n1: ")


def test_a_failure_the_baseline_did_not_have_is_the_changes_and_stops_the_rehearsal(served: Served) -> None:
    c = Clock()
    served.reader.unreadable.add((T, "n3"))
    doc, source = rehearsed(served, FIVE, c)
    assert doc["status"] == "failed"
    assert results(doc) == ["empty", "created", "failed", "not_reached", "not_reached"]
    assert pairs(doc["stages"][2]["failures"]) == [("verify.node.unread", "n3")]
    assert doc["stages"][2]["counts"]["failed"] == 0  # a node unread fails no assertion: its own are skipped
    assert c.slept.count(5.0) == 1
    heading, sentence = doc["headline"].splitlines()
    assert heading == "Rehearsal failed at stage 3 of 5: third-node"
    assert sentence.startswith("Verify found 1 failure at stage 3, third-node, that the baseline did not have, the "
                               "first n3: ")
    assert sentence.endswith("Stage 2 passed. Stages 4 and 5 were not reached.")
    assert [f["rule"] for f in doc["findings"]] == ["rehearsal.stage.failed"]
    assert operations(served) == ["destroy", "step", "create"]
    assert served.other.list_twins() == [] and served.driver.labs == {}
    assert source.posted[0].status == "failed"


def test_a_node_unread_once_after_a_step_is_asked_again_and_passes(served: Served) -> None:
    c = Clock()
    served.reader.unreadable.add((T, "n3"))

    def on_sleep() -> None:
        if c.slept[-1] == 5.0:
            served.reader.unreadable.discard((T, "n3"))

    c.on_sleep = on_sleep
    doc, _ = rehearsed(served, FIVE, c)
    assert doc["status"] == "passed"
    assert c.slept.count(5.0) == 1
    third = doc["stages"][2]
    assert third["result"] == "passed" and third["counts"]["failed"] == 0
    assert third["wait"]["budget_s"] == 1 and third["wait"]["after_s"] >= 0  # the step's own wait, which expired
    assert all("wait" not in s for k, s in enumerate(doc["stages"]) if k != 2)


def test_a_failure_is_compared_by_rule_and_object_never_by_message(served: Served) -> None:
    c = Clock()
    at = {"stage": 2}
    # What verify answers at each stage: the baseline's port down, the same port down in other words, and another.
    answers = {
        2: Finding(rule="verify.port.enabled", severity="error", object="n1:ethernet-1/1",
                   message="n1:ethernet-1/1 reports admin state disable."),
        3: Finding(rule="verify.port.enabled", severity="error", object="n1:ethernet-1/1",
                   message="n1:ethernet-1/1 is not enabled, as its intent asks."),
        4: Finding(rule="verify.port.enabled", severity="error", object="n2:ethernet-1/1",
                   message="n2:ethernet-1/1 reports admin state disable."),
    }

    def progress(line: str) -> None:
        if line.startswith("step: stage "):
            at["stage"] = int(line.removeprefix("step: stage ").partition(",")[0])

    def verify_twin(name: str) -> dict[str, Any]:
        verdict = served.client.verify_twin(name)
        f = answers[at["stage"]]
        counts = verdict["counts"] | {"failed": 1}
        return verdict | {"status": "nonconforming", "counts": counts,
                          "findings": [documents.finding(f.rule, f.severity, f.message, f.object)]}

    doc, _ = rehearsed(served, FIVE, c, core=Wrapped(served.client, verify_twin=verify_twin), progress=progress)
    assert doc["status"] == "failed"
    assert pairs(doc["already_failing"]) == [("verify.port.enabled", "n1:ethernet-1/1")]
    assert results(doc) == ["empty", "created", "passed", "failed", "not_reached"]
    assert doc["stages"][3]["failures"] == [documents.finding("verify.port.enabled", "error", answers[4].message,
                                                              "n2:ethernet-1/1")]
    assert c.slept.count(5.0) == 36  # the settle's alone: a port down is not asked again
    assert doc["headline"].splitlines()[0] == "Rehearsal failed at stage 4 of 5: third-link"


def test_a_push_refused_in_a_step_diverges_it_and_fails_the_stage(served: Served) -> None:
    c = Clock()
    served.pusher.refuse.add("n3")
    doc, source = rehearsed(served, FIVE, c)
    assert doc["status"] == "failed"
    assert results(doc) == ["empty", "created", "failed", "not_reached", "not_reached"]
    third = doc["stages"][2]
    assert pairs(third["failures"]) == [("push.refused", "n3")]
    assert "counts" not in third and third["run_id"] == served.other.list_runs(twin=T)[1]["id"]
    assert doc["headline"].splitlines()[1] == (
        "The step to stage 3, third-node, failed and left the twin diverged: n3: At line 1: n3 refused the "
        "configuration (push.refused). Stage 2 passed. Stages 4 and 5 were not reached."
    )
    summary = source.posted[0].summary.split("\n")
    assert "| 3 | third-node | 1 node added (n3); 1 link added (n1 to n3) | **failed** | not run |" in summary
    assert operations(served) == ["destroy", "step", "create"]
    assert served.other.list_twins() == [] and served.driver.labs == {}


def not_ready(served: Served) -> Wrapped:
    """The served client, its `get_twin` answering the twin's own record with its `Ready` condition `False`: the fake
    runtime cannot make a twin not Ready without a run of its own."""

    def get_twin(name: str) -> tuple[dict[str, Any], str]:
        record, etag = served.client.get_twin(name)
        conditions = [c | {"status": "False"} if c["type"] == "Ready" else c for c in record["status"]["conditions"]]
        return record | {"status": record["status"] | {"conditions": conditions}}, etag

    return Wrapped(served.client, get_twin=get_twin)


def test_an_unchanged_stage_is_stepped_when_the_twin_is_not_ready(served: Served) -> None:
    c, lines = Clock(), list[str]()
    doc, _ = rehearsed(served, [FIVE[1], FIVE[1]], c, lines, core=not_ready(served))
    assert doc["status"] == "passed"
    assert results(doc) == ["created", "passed"]
    assert doc["plan"]["stages"][1]["unchanged"] is True
    assert doc["stages"][1]["counts"]["failed"] == 0
    assert operations(served) == ["destroy", "step", "create"]
    assert doc["stages"][1]["run_id"] == served.other.list_runs(twin=T)[1]["id"]
    assert "step: stage 2, seeded" in lines and not any(line.startswith("skip:") for line in lines)


def test_an_unchanged_stage_whose_spec_the_twin_already_has_starts_no_run_and_is_verified(served: Served) -> None:
    c = Clock()
    stages = [FIVE[1], FIVE[2], built("third-node-again", "steps/three-node-unlinked.json")]
    doc, _ = rehearsed(served, stages, c, core=not_ready(served))
    assert doc["status"] == "passed"
    assert results(doc) == ["created", "passed", "passed"]
    assert "run_id" not in doc["stages"][2] and doc["stages"][2]["counts"]["failed"] == 0
    assert operations(served) == ["destroy", "step", "create"]


def test_one_stage_alone_is_created_verified_and_destroyed(served: Served) -> None:
    c = Clock()
    doc, source = rehearsed(served, [FIVE[1]], c)
    assert doc["status"] == "passed"
    assert results(doc) == ["created"]
    (warning,) = doc["findings"]
    assert (warning["rule"], warning["severity"]) == ("rehearsal.steps.none", "warning")
    assert warning["message"] == ("Only stage 1, seeded, builds, so the twin was created and verified there and no "
                                  "step was rehearsed.")
    assert doc["headline"].splitlines() == ["Rehearsal passed: 1 stage", warning["message"]]
    assert operations(served) == ["destroy", "create"]
    assert served.other.list_twins() == [] and [p.status for p in source.posted] == ["passed"]
