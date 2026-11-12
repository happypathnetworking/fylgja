"""The plan of a change (D-086): each of its stages read from its source under one scope, filed and built by the
core, and diffed against the stage built before it, into a plan 1 document; and what changed, in words, for the
report's table (D-087).

A stage in which the scope selects no device before any stage built is empty, and passed over; the first that builds
is the baseline. One that selects no device after it, that the source gives no blueprint for, that the core refuses
to file or that the compiler refuses, is refused, and ends the plan: the stages after it are never read. A fault
that is no stage's, the core's, the source's or the caller's, stops the plan where it is met, unfinished.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from fylgja_core.client import Client, ProblemError, TransportError, UnsupportedVersion
from fylgja_core.findings import Finding

from fylgja_orchestrator.rehearsal import rules
from fylgja_orchestrator.rehearsal.documents import finding
from fylgja_orchestrator.rehearsal.source import Change, ChangeSource, Stage

# The core's refusals that are a stage's: a blueprint it will not file, and one the compiler will not build.
FILE_REFUSED = 400
BUILD_REFUSED = (422, "bundle.rejected")
# The names a list in words gives before `and <k> more`.
NAMES = 3


class _Stopped(Exception):
    """The fault that stops the plan where it is met, carried out of the stage it met."""

    def __init__(self, fault: Exception) -> None:
        super().__init__(type(fault).__name__)
        self.fault = fault


def stamp() -> str:
    """Now, in RFC 3339, UTC to the second with `Z`: when a change's stages were read."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def plan(
    source: ChangeSource,
    core: Client,
    ref: str,
    scope: str,
    *,
    now: Callable[[], str] = stamp,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """The plan 1 document of the change `ref` names, every stage read under `scope`. What the source's `change`
    raises is raised, as is the fault that stopped the plan."""
    change = source.change(ref)
    doc, fault = read(source, core, change, scope, now=now, progress=progress)
    if fault is not None:
        raise fault
    return doc


def read(
    source: ChangeSource,
    core: Client,
    change: Change,
    scope: str,
    *,
    now: Callable[[], str],
    progress: Callable[[str], None] | None = None,
    before: Callable[[], None] | None = None,
) -> tuple[dict[str, Any], Exception | None]:
    """The plan 1 document of `change`, every stage read under `scope`, and the fault that stopped it, or None.

    A fault is a refusal of the core's that is no stage's, the core unreachable or of another API, an exception of
    the source's, or one `before` raises, which is called ahead of every call on the source and the core: the plan is
    then unfinished, and the stage it met and those after it not read. `now` stamps when the stages were read;
    `progress` is given a line as each stage read concludes."""
    read_at = now()
    fault: Exception | None = None
    try:
        stages = list(_asked(before, source.stages, change))
    except _Stopped as e:
        stages, fault = [], e.fault
    entries: list[dict[str, Any]] = []
    previous: str | None = None  # the bundle of the stage built last
    ended = fault is not None
    for k, stage in enumerate(stages, 1):
        if ended:
            entries.append(_entry(stage, "not_read"))
            continue
        try:
            entry, bundle_id = _staged(source, core, stage, scope, previous, before)
        except _Stopped as e:
            fault, ended = e.fault, True
            entries.append(_entry(stage, "not_read"))
            continue
        entries.append(entry)
        previous = bundle_id or previous
        ended = entry["outcome"] == "refused"
        if progress is not None:
            progress(f"plan: stage {k} of {len(stages)}, {stage.label}: {entry['outcome']}")
    return _concluded(change, scope, read_at, entries, fault), fault


def _staged(
    source: ChangeSource,
    core: Client,
    stage: Stage,
    scope: str,
    previous: str | None,
    before: Callable[[], None] | None,
) -> tuple[dict[str, Any], str | None]:
    """One stage read under `scope`, filed, built and diffed against `previous`, the bundle built before it: its
    entry, and its bundle where it built. A fault leaves as `_Stopped`."""
    got = _asked(before, source.read, stage, scope)
    found = [_finding(f) for f in got.findings]
    if got.empty and previous is None:
        return _entry(stage, "empty", findings=found), None
    if got.empty or got.blueprint is None:
        return _entry(stage, "refused", findings=found), None
    try:
        blueprint_id = _called(before, core.put_blueprint, got.blueprint)
    except ProblemError as e:
        if e.status != FILE_REFUSED:
            raise _Stopped(e) from e
        return _entry(stage, "refused", findings=found + _problem(e)), None
    try:
        built = _called(before, core.build_bundle, blueprint_id)
    except ProblemError as e:
        if (e.status, e.problem.rule) != BUILD_REFUSED:
            raise _Stopped(e) from e
        return _entry(stage, "refused", blueprint_id=blueprint_id, findings=found + _problem(e)), None
    bundle_id: str = built["id"]
    if previous is None:
        changed, unchanged = baseline_words(built["manifest"]), False
    else:
        try:
            diff = _called(before, core.diff_bundles, previous, bundle_id)
        except ProblemError as e:
            raise _Stopped(e) from e
        changed, unchanged = changed_words(diff), bool(diff["unchanged"])
    fidelity = built["fidelity"]
    entry = _entry(stage, "built", blueprint_id=blueprint_id, bundle_id=bundle_id, changed=changed,
                   unchanged=unchanged, findings=found + [dict(f) for f in built["findings"]],
                   omitted=[dict(o) for o in fidelity["omitted"]],
                   approximations=[dict(a) for a in fidelity["approximations"]])
    return entry, bundle_id


def _ahead(before: Callable[[], None] | None) -> None:
    """`before` called, what it raises the fault."""
    if before is None:
        return
    try:
        before()
    except Exception as e:
        raise _Stopped(e) from e


def _asked[T](before: Callable[[], None] | None, call: Callable[..., T], *args: Any) -> T:
    """A call on the source, `before` called ahead of it: whatever it raises is the fault."""
    _ahead(before)
    try:
        return call(*args)
    except Exception as e:
        raise _Stopped(e) from e


def _called[T](before: Callable[[], None] | None, call: Callable[..., T], *args: Any) -> T:
    """A call on the core, `before` called ahead of it: the core unreachable, or of another API, is the fault; its
    refusal is raised for the stage to read."""
    _ahead(before)
    try:
        return call(*args)
    except (TransportError, UnsupportedVersion) as e:
        raise _Stopped(e) from e


def _problem(e: ProblemError) -> list[dict[str, Any]]:
    """The findings of the core's refusal of a stage."""
    return [_finding(f) for f in e.problem.findings or ()]


def _finding(f: Finding) -> dict[str, Any]:
    return finding(f.rule, f.severity, f.message, f.object)


def _entry(stage: Stage, outcome: str, **members: Any) -> dict[str, Any]:
    """A stage of the plan document: its label, its pin in words, its outcome and what the plan made of it."""
    return {"label": stage.label, "where": stage.where, "outcome": outcome, **members}


def _concluded(
    change: Change, scope: str, read_at: str, entries: Sequence[dict[str, Any]], fault: Exception | None
) -> dict[str, Any]:
    """The plan document of `entries`: its status, its headline and its findings, from its stages and the fault."""
    n = len(entries)
    built = [k for k, entry in enumerate(entries, 1) if entry["outcome"] == "built"]
    refused = [k for k, entry in enumerate(entries, 1) if entry["outcome"] == "refused"]
    findings: list[dict[str, Any]] = []
    if fault is not None:
        status, headline = "unfinished", "Plan not finished"
    elif refused:
        k = refused[0]
        label = entries[k - 1]["label"]
        cause = _cause(rules.STAGE_REFUSED, _refused(k, label, entries[k - 1].get("findings", [])), label)
        status, findings = "refused", [cause]
        headline = f"Plan refused at stage {k} of {n}: {label}\n{cause['message']}"
    elif built:
        k = built[0]
        follow = f"{_count(n - k, 'stage')} {'follows' if n - k == 1 else 'follow'} it"
        status = "planned"
        headline = (f"Plan: {len(built)} of {n} stages build\n"
                    f"The baseline is stage {k}, {entries[k - 1]['label']}; {follow}.")
    else:
        cause = _cause(rules.STAGES_NONE, f"No stage of the change selects a device in scope {scope}, so there is "
                                          "nothing to build. Check the scope the checks run with.")
        status, findings = "empty", [cause]
        headline = f"Nothing to plan\n{cause['message']}"
    return {
        "plan_version": "1",
        "status": status,
        "headline": headline,
        "change": {"id": change.id, "where": change.where},
        "scope": scope,
        "read_at": read_at,
        "findings": findings,
        "stages": list(entries),
    }


def _cause(rule: str, message: str, object: str | None = None) -> dict[str, Any]:
    return finding(rule, rules.SEVERITY[rule], message, object)


def _refused(k: int, label: str, found: Sequence[Mapping[str, Any]]) -> str:
    """`stage.refused`'s sentence for stage `k`, quoting its first error, or its first finding where it has none."""
    first = next((f for f in found if f["severity"] == "error"), found[0] if found else None)
    why = f": {rules.quote(first)}" if first is not None else ""
    return f"Stage {k}, {label}, could not be built{why}. Nothing was rehearsed."


def baseline_words(manifest: Mapping[str, Any]) -> str:
    """What the first built stage holds, in words: `baseline: <n> nodes, <m> links`, and its probes where it has
    any."""
    words = f"baseline: {_count(len(manifest['nodes']), 'node')}, {_count(len(manifest['links']), 'link')}"
    probes = len(manifest["probes"])
    return f"{words}, {_count(probes, 'probe')}" if probes else words


def changed_words(diff: Mapping[str, Any]) -> str:
    """What a bundle diff changes, in words: `nothing` where it is unchanged; else its nodes, its links, its probes,
    and the nodes changed in their platform, their configuration and their ports, joined by `; `. A probe in both
    of the diff's lists moved; a node's ports are said only where no added or removed link ends on it."""
    if diff["unchanged"]:
        return "nothing"
    nodes, links, probes = diff["nodes"], diff["links"], diff["probes"]
    parts: list[str] = []
    for how in ("added", "removed"):
        if nodes[how]:
            parts.append(f"{_count(len(nodes[how]), 'node')} {how} ({_names(nodes[how])})")
    for how in ("added", "removed"):
        if links[how]:
            ends = [f"{link['a']['device']} to {link['b']['device']}" for link in links[how]]
            parts.append(f"{_count(len(links[how]), 'link')} {how} ({_names(ends)})")
    moved = [name for name in probes["added"] if name in probes["removed"]]
    parts += [f"probe {name} moved" for name in moved]
    for how in ("added", "removed"):
        rest = [name for name in probes[how] if name not in moved]
        if rest:
            parts.append(f"{_count(len(rest), 'probe')} {how} ({_names(rest)})")
    cabled = {link[end]["device"] for how in ("added", "removed") for link in links[how] for end in ("a", "b")}
    for reason, words in (("platform", "platform of"), ("config", "configuration of"), ("mapping", "ports of")):
        changed = [node["node"] for node in nodes["changed"]
                   if reason in node["reasons"] and not (reason == "mapping" and node["node"] in cabled)]
        if changed:
            parts.append(f"{words} {_names(changed)}")
    return "; ".join(parts)


def _count(n: int, noun: str) -> str:
    """`n` of `noun`, the singular for one."""
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _names(names: Sequence[str]) -> str:
    """A list of names, its first `NAMES` and `and <k> more` where it is longer."""
    if len(names) <= NAMES:
        return ", ".join(names)
    return f"{', '.join(names[:NAMES])} and {len(names) - NAMES} more"
