"""The commands that take one twin to a stage of a change (D-085, D-086): `create` makes it at a stage, `step` takes it
to another, by default the one after the stage its record says it stands at, and `stage_list` names the change's
stages and the twins that stand at them. A record a twin says where it stands, trusted only while its blueprint id is
the twin's; a target the command cannot name, or the twin's spec already, is refused with no run. Held to the core's
own server on its fake runtime, over a fake change source."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fylgja_core.client import ProblemError
from fylgja_core.findings import Finding
from harness import Served, wait_for
from sources import BLUEPRINTS, CHANGE, FIVE, SCOPE, FakeSource, refused

from fylgja_orchestrator.rehearsal import create, record, stage_list, step
from fylgja_orchestrator.rehearsal.record import Record

NOW = "2026-11-09T10:15:11Z"
LATER = "2026-11-09T10:20:00Z"
STALE = Finding(rule="artifact.stale", severity="error", object="n1",
                message="n1's configuration is older than its intent.")
STAGES = tuple(stage for stage, _ in FIVE)


def now() -> str:
    return NOW


def later() -> str:
    return LATER


def records(tmp_path: Path) -> Path:
    """The records' root, apart from the store's directory."""
    return tmp_path / "records"


def twin_of(served: Served, name: str = "demo") -> dict[str, Any]:
    record, _ = served.other.get_twin(name)
    return record


def ready(twin: dict[str, Any]) -> bool:
    return any(c["type"] == "Ready" and c["status"] == "True" for c in twin["status"]["conditions"])


def operations(served: Served, twin: str = "demo") -> list[str]:
    """The operations of the twin's runs, newest first."""
    return [r["operation"] for r in served.other.list_runs(twin=twin)]


def said(made_findings: tuple[Finding, ...]) -> list[tuple[str, str, str | None]]:
    return [(f.rule, f.severity, f.object) for f in made_findings]


def test_a_twin_is_created_at_a_stage_and_its_record_written(served: Served, tmp_path: Path) -> None:
    source, lines = FakeSource(CHANGE, FIVE), list[str]()
    made = create(source, served.client, CHANGE.ref, SCOPE, twin="demo", root=records(tmp_path), now=now,
                  progress=lines.append)
    assert (made.twin, made.stage, made.findings) == ("demo", STAGES[1], ())
    assert made.run is not None
    assert (made.run["operation"], made.run["verdict"]["status"]) == ("create", "ok")
    twin = twin_of(served)
    assert ready(twin) and twin["status"]["blueprint_id"] == made.blueprint_id
    assert record.read(records(tmp_path), "demo") == Record("demo", CHANGE.id, CHANGE.ref, SCOPE, "seeded",
                                                             twin["status"]["blueprint_id"], NOW)
    assert source.reads == ["branch-point", "seeded"]
    assert lines[0] == "create: stage 2, seeded, as demo"
    assert lines[1:] and all(line.startswith("demo: ") for line in lines[1:])


def test_a_twin_is_stepped_to_the_next_stage_by_default(served: Served, tmp_path: Path) -> None:
    source, root = FakeSource(CHANGE, FIVE), records(tmp_path)
    create(source, served.client, CHANGE.ref, SCOPE, twin="demo", root=root, now=now)
    lines: list[str] = []
    made = step(source, served.client, CHANGE.ref, SCOPE, twin="demo", root=root, now=now, progress=lines.append)
    assert (made.stage, made.findings) == (STAGES[2], ())
    assert made.run is not None
    assert (made.run["operation"], made.run["verdict"]["status"]) == ("step", "ok")
    twin = twin_of(served)
    assert twin["status"]["blueprint_id"] == made.blueprint_id
    assert twin["spec"]["allow_restart"] is False
    moved = record.read(root, "demo")
    assert moved is not None and (moved.label, moved.blueprint_id) == ("third-node", made.blueprint_id)
    assert lines[0] == "step: stage 3, third-node"

    made = step(source, served.client, CHANGE.ref, SCOPE, twin="demo", stage="head", allow_restart=True, root=root,
                now=now)
    assert (made.stage, made.findings) == (STAGES[4], ())
    assert made.run is not None
    assert (made.run["operation"], made.run["verdict"]["status"]) == ("step", "ok")
    twin = twin_of(served)
    assert twin["status"]["blueprint_id"] == made.blueprint_id and twin["spec"]["allow_restart"] is True
    moved = record.read(root, "demo")
    assert moved is not None and (moved.label, moved.blueprint_id) == ("head", made.blueprint_id)
    assert operations(served) == ["step", "step", "create"]


def test_a_step_with_no_stage_and_no_trusted_record_is_refused(served: Served, tmp_path: Path) -> None:
    source, root = FakeSource(CHANGE, FIVE), records(tmp_path)
    create(source, served.client, CHANGE.ref, SCOPE, twin="demo", root=root, now=now)
    written = record.read(root, "demo")
    # Another client steps the twin behind its record.
    behind = served.other.put_blueprint(json.loads((BLUEPRINTS / "steps" / "three-node-unlinked.json").read_text()))
    answered, _ = served.other.apply_twin("demo", {"blueprint_id": behind}, if_match="*")
    assert served.other.follow(answered, ("step", "create")).run["verdict"]["status"] == "ok"

    made = step(source, served.client, CHANGE.ref, SCOPE, twin="demo", root=root, now=now)
    assert (made.stage, made.blueprint_id, made.run) == (None, None, None)
    assert said(made.findings) == [("step.target.required", "error", "demo"), ("record.twin.stale", "info", "demo")]
    assert "seeded" in made.findings[1].message
    assert operations(served) == ["step", "create"]
    assert record.read(root, "demo") == written

    made = step(source, served.client, CHANGE.ref, SCOPE, twin="demo", root=tmp_path / "none", now=now)
    assert made.run is None and said(made.findings) == [("step.target.required", "error", "demo")]
    assert operations(served) == ["step", "create"]


def test_a_step_past_the_last_stage_is_refused(served: Served, tmp_path: Path) -> None:
    source, root = FakeSource(CHANGE, FIVE), records(tmp_path)
    create(source, served.client, CHANGE.ref, SCOPE, twin="demo", stage="head", root=root, now=now)
    made = step(source, served.client, CHANGE.ref, SCOPE, twin="demo", root=root, now=now)
    assert (made.stage, made.run) == (None, None)
    assert said(made.findings) == [("step.target.unknown", "error", "demo")]
    made = step(source, served.client, CHANGE.ref, SCOPE, twin="demo", stage="nowhere", root=root, now=now)
    assert (made.stage, made.run) == (None, None)
    assert said(made.findings) == [("step.target.unknown", "error", "demo")]
    assert "nowhere" in made.findings[0].message
    assert source.reads == ["head"]
    assert operations(served) == ["create"]


def test_a_step_to_the_stage_the_twin_stands_at_starts_no_run(served: Served, tmp_path: Path) -> None:
    source, root = FakeSource(CHANGE, FIVE), records(tmp_path)
    created = create(source, served.client, CHANGE.ref, SCOPE, twin="demo", root=root, now=now)
    assert created.blueprint_id is not None
    made = step(source, served.client, CHANGE.ref, SCOPE, twin="demo", stage="seeded", root=root, now=later)
    assert (made.stage, made.blueprint_id, made.run) == (STAGES[1], created.blueprint_id, None)
    assert said(made.findings) == [("step.target.current", "info", "demo")]
    assert operations(served) == ["create"]
    # The twin runs that stage's blueprint, so its record is written again.
    assert record.read(root, "demo") == Record("demo", CHANGE.id, CHANGE.ref, SCOPE, "seeded", created.blueprint_id,
                                               LATER)


def test_a_default_step_to_a_stage_the_twin_runs_already_moves_its_record_on(served: Served, tmp_path: Path) -> None:
    source, root = FakeSource(CHANGE, FIVE), records(tmp_path)
    create(source, served.client, CHANGE.ref, SCOPE, twin="demo", root=root, now=now)
    stepped = step(source, served.client, CHANGE.ref, SCOPE, twin="demo", stage="third-link", root=root, now=now)
    assert stepped.run is not None and stepped.run["verdict"]["status"] == "ok"
    assert stepped.blueprint_id is not None

    # `head` is the blueprint of `third-link`: the step starts no run, and the record moves on to it.
    made = step(source, served.client, CHANGE.ref, SCOPE, twin="demo", root=root, now=later)
    assert (made.stage, made.blueprint_id, made.run) == (STAGES[4], stepped.blueprint_id, None)
    assert said(made.findings) == [("step.target.current", "info", "demo")]
    assert record.read(root, "demo") == Record("demo", CHANGE.id, CHANGE.ref, SCOPE, "head", stepped.blueprint_id,
                                               LATER)

    made = step(source, served.client, CHANGE.ref, SCOPE, twin="demo", root=root, now=later)
    assert (made.stage, made.run) == (None, None)
    assert said(made.findings) == [("step.target.unknown", "error", "demo")]
    assert "the last of" in made.findings[0].message
    assert operations(served) == ["step", "create"]


def test_a_stage_the_source_refuses_creates_nothing(served: Served, tmp_path: Path) -> None:
    source, root = FakeSource(CHANGE, [*FIVE[:2], refused("third-node", STALE), *FIVE[3:]]), records(tmp_path)
    made = create(source, served.client, CHANGE.ref, SCOPE, twin="demo", stage="third-node", root=root, now=now)
    assert (made.stage, made.blueprint_id, made.run, made.findings) == (STAGES[2], None, None, (STALE,))
    made = create(source, served.client, CHANGE.ref, SCOPE, twin="demo", stage="branch-point", root=root, now=now)
    assert (made.stage, made.run) == (STAGES[0], None)
    assert [f.rule for f in made.findings] == ["scope.empty"]
    assert source.reads == ["third-node", "branch-point"]
    assert served.other.list_twins() == [] and not root.exists()


def test_the_stages_are_listed_with_the_twins_that_stand_at_them(served: Served, tmp_path: Path) -> None:
    source, root = FakeSource(CHANGE, FIVE), records(tmp_path)
    create(source, served.client, CHANGE.ref, SCOPE, twin="demo", root=root, now=now)
    step(source, served.client, CHANGE.ref, SCOPE, twin="demo", root=root, now=now)
    # Another change's record, of a twin the core has not: neither listed nor read.
    record.write(root, Record("elsewhere", "pc-2", "other", SCOPE, "head", "c" * 64, NOW))
    reads = list(source.reads)

    listed = stage_list(source, served.client, CHANGE.ref, root=root)
    assert (listed.change, listed.stages) == (CHANGE, STAGES)
    assert (listed.at, listed.stale) == ({"demo": "third-node"}, ())
    assert source.reads == reads

    served.other.delete_twin("demo")

    def gone() -> bool | None:
        try:
            served.other.get_twin("demo")
        except ProblemError as e:
            if e.status == 404:
                return True
            raise
        return None

    wait_for(gone)
    listed = stage_list(source, served.client, CHANGE.ref, root=root)
    assert (listed.at, listed.stale) == ({}, ("demo",))
