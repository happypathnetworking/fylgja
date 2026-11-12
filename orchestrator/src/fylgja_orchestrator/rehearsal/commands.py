"""What the example's commands `twin create`, `twin step` and `stage list` call, in the command's own process (D-085):
one twin taken to a stage of a change, and the change's stages listed with the twins that stand at them.

The core's record of a twin names no stage, so each twin a command makes or steps gets a record of the stage it was
taken to (`record`), written once the run ends `ok`, or where a step finds the twin running that stage's blueprint
already and starts no run, and trusted only while its blueprint id is the one the twin runs (D-086). A step with no
stage named goes to the stage after the one a trusted record names. A target a command cannot name is refused with a
finding of `rules` and no run; so is a stage the source gives no blueprint for, with the source's own findings. What
the core refuses or does not answer leaves as the client raised it, for the command to print as the core's thin CLI
does.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from fylgja_core import findings
from fylgja_core.client import Client, ProblemError
from fylgja_core.findings import Finding

from fylgja_orchestrator.rehearsal import record, rules
from fylgja_orchestrator.rehearsal.planning import stamp
from fylgja_orchestrator.rehearsal.record import Record
from fylgja_orchestrator.rehearsal.source import Change, ChangeSource, Read, Stage


@dataclass(frozen=True)
class Made:
    """What a command made of a twin: the twin; the stage it was taken to, None where none could be named; the
    blueprint that stage was filed as, None where it was not filed; the run the write started, ended, its verdict the
    run's own findings, or None where none was started; and the findings beside it, the source's read's and the
    command's own, a refusal's among them."""

    twin: str
    stage: Stage | None
    blueprint_id: str | None
    run: dict[str, Any] | None
    findings: tuple[Finding, ...]


@dataclass(frozen=True)
class Listed:
    """A change's stages in order, `at` the stage's label each twin of the change stands at, by twin, and `stale` the
    twins whose record is the change's and says nothing: the twin runs another blueprint now, or is gone."""

    change: Change
    stages: tuple[Stage, ...]
    at: Mapping[str, str]
    stale: tuple[str, ...]


def create(
    source: ChangeSource,
    core: Client,
    ref: str,
    scope: str,
    *,
    twin: str,
    stage: str | None = None,
    root: Path,
    now: Callable[[], str] = stamp,
    progress: Callable[[str], None] | None = None,
) -> Made:
    """The twin `twin` created at the stage labelled `stage` of the change `ref` names, read under `scope`, or at the
    first stage whose read is not empty: the stage read, its blueprint filed, the twin's create asked and its run
    followed, the record written under `root` once the run ends `ok`. `now` stamps the record; `progress` is given a
    line as the create is asked, and `follow`'s own."""
    change = source.change(ref)
    stages = list(source.stages(change))
    if stage is not None:
        k = _labelled(stages, stage)
        if k is None:
            return _refused(twin, _unknown(f"{change.where} has no stage {stage}.", twin))
        return _taken(source, core, change, scope, twin, stages, k, None, root, now, progress)
    for k, candidate in enumerate(stages, 1):
        got = source.read(candidate, scope)
        if not got.empty:
            return _taken(source, core, change, scope, twin, stages, k, got, root, now, progress)
    return _refused(twin, _unknown(f"No stage of {change.where} selects a device in scope {scope}, so there is none "
                                   "to create the twin at.", twin))


def step(
    source: ChangeSource,
    core: Client,
    ref: str,
    scope: str,
    *,
    twin: str,
    stage: str | None = None,
    allow_restart: bool = False,
    root: Path,
    now: Callable[[], str] = stamp,
    progress: Callable[[str], None] | None = None,
) -> Made:
    """The twin `twin` stepped to the stage labelled `stage` of the change `ref` names, read under `scope`, or to the
    stage after the one its record under `root` names, where that record is the change's and trusted: the stage read,
    its blueprint filed, the twin's spec written over whatever revision it is at, restarts allowed as
    `allow_restart` says, the run followed, and the record written once the run ends `ok`. A spec the twin has
    already starts no run, and the record is written then where the twin runs that stage's blueprint, so a step with
    no stage named goes on past a stage that changes nothing. `now` stamps the record; `progress` is given a line as
    the step is asked, and `follow`'s own."""
    change = source.change(ref)
    stages = list(source.stages(change))
    if stage is not None:
        k = _labelled(stages, stage)
        if k is None:
            return _refused(twin, _unknown(f"{change.where} has no stage {stage}.", twin))
    else:
        known = record.read(root, twin)
        if known is None or known.change_id != change.id:
            return _refused(twin, _required(change, twin))
        current, _ = core.get_twin(twin)
        if not record.trusted(known, current):
            return _refused(twin, _required(change, twin),
                            _said(rules.RECORD_STALE, f"The record of twin {twin} says it stands at stage "
                                                      f"{known.label} of {change.where}, but the twin runs another "
                                                      "blueprint now, so the record is not trusted.", twin))
        at = _labelled(stages, known.label)
        if at is None:
            return _refused(twin, _unknown(f"Twin {twin} stands at stage {known.label}, which {change.where} no "
                                           "longer has: name the stage to step it to.", twin))
        if at == len(stages):
            return _refused(twin, _unknown(f"Twin {twin} stands at stage {known.label}, the last of {change.where}: "
                                           "there is no stage after it.", twin))
        k = at + 1
    return _taken(source, core, change, scope, twin, stages, k, None, root, now, progress, allow_restart=allow_restart)


def stage_list(source: ChangeSource, core: Client, ref: str, *, root: Path) -> Listed:
    """The stages of the change `ref` names, none of them read, and the twins whose record under `root` is that
    change's: each at the stage its record names where the record is trusted, else stale, as one whose twin the core
    has not."""
    change = source.change(ref)
    stages = tuple(source.stages(change))
    at: dict[str, str] = {}
    stale: list[str] = []
    for known in record.listed(root):
        if known.change_id != change.id:
            continue
        try:
            current, _ = core.get_twin(known.twin)
        except ProblemError as e:
            if e.status != 404:
                raise
            stale.append(known.twin)
            continue
        if record.trusted(known, current):
            at[known.twin] = known.label
        else:
            stale.append(known.twin)
    return Listed(change=change, stages=stages, at=at, stale=tuple(stale))


def _taken(
    source: ChangeSource,
    core: Client,
    change: Change,
    scope: str,
    twin: str,
    stages: Sequence[Stage],
    k: int,
    got: Read | None,
    root: Path,
    now: Callable[[], str],
    progress: Callable[[str], None] | None,
    *,
    allow_restart: bool | None = None,
) -> Made:
    """The twin taken to stage `k` of `stages`, its read `got` where it was read already: created where
    `allow_restart` is None, else stepped. A spec the twin has already is written by no one, so no run is followed:
    `follow` would answer the twin's last. The record is written then where the twin runs that stage's blueprint
    already, so a step with no stage named goes on past a stage that changes nothing; where the last run of that spec
    did not end `ok`, the twin runs another, and the record stays where it was."""
    target = stages[k - 1]
    if got is None:
        got = source.read(target, scope)
    if got.empty or got.blueprint is None:
        return Made(twin, target, None, None, got.findings)
    blueprint_id = core.put_blueprint(got.blueprint)
    if allow_restart is None:
        _say(progress, f"create: stage {k}, {target.label}, as {twin}")
        answered, _ = core.apply_twin(twin, {"blueprint_id": blueprint_id}, if_none_match="*")
        operations: tuple[str, ...] = ("create",)
    else:
        _say(progress, f"step: stage {k}, {target.label}")
        answered, _ = core.apply_twin(twin, {"blueprint_id": blueprint_id, "allow_restart": allow_restart},
                                      if_match="*")
        operations = ("step", "create")

    def stands() -> None:
        """The record written: the twin stands at the target."""
        record.write(root, Record(twin=twin, change_id=change.id, ref=change.ref, scope=scope, label=target.label,
                                  blueprint_id=blueprint_id, written_at=now()))

    if answered["status"]["observed_generation"] == answered["generation"]:
        if answered["status"].get("blueprint_id") == blueprint_id:
            stands()
        return Made(twin, target, blueprint_id, None,
                    (*got.findings, _said(rules.TARGET_CURRENT, f"Twin {twin}'s spec is stage {target.label}'s "
                                                                "already, so no run was started.", twin)))
    followed = core.follow(answered, operations, progress=progress)
    if findings.decode(followed.run["verdict"]).status == "ok" and not followed.gone:
        stands()
    return Made(twin, target, blueprint_id, followed.run, got.findings)


def _labelled(stages: Sequence[Stage], label: str) -> int | None:
    """The number of the stage labelled `label` among `stages`, counted from 1; None where none is."""
    return next((k for k, stage in enumerate(stages, 1) if stage.label == label), None)


def _refused(twin: str, *found: Finding) -> Made:
    """A command's refusal of its target: no stage, nothing filed, no run, and why."""
    return Made(twin, None, None, None, found)


def _required(change: Change, twin: str) -> Finding:
    return _said(rules.TARGET_REQUIRED, f"Nothing says which stage of {change.where} twin {twin} stands at, so it "
                                        "cannot be stepped to the next: name the stage to step it to.", twin)


def _unknown(message: str, twin: str) -> Finding:
    return _said(rules.TARGET_UNKNOWN, message, twin)


def _said(rule: str, message: str, twin: str) -> Finding:
    """One of the commands' own findings, about `twin`, at its rule's severity."""
    severity = cast(Literal["error", "warning", "info"], rules.SEVERITY[rule])
    return Finding(rule=rule, severity=severity, object=twin, message=message)


def _say(progress: Callable[[str], None] | None, line: str) -> None:
    if progress is not None:
        progress(line)
