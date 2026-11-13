"""The rehearsal of a change (D-086): its stages built in order on one twin, named from the change and the run, and the
rehearsal 1 document that says what each came to there, from which the report is rendered and posted (D-087).

A rehearsal deletes the change's twins first, so the newest stands; plans every stage; looks at each distinct
bundle with a dry run, as the twin it would make, before anything is created; creates the baseline, the first stage
that builds, and settles it by asking verify again until it holds or a budget passes, what still fails then being
failing before the change; steps to each later stage, restarts allowed, and verifies it, a failure the baseline did
not have being the change's, stopping at the first stage that fails; and destroys its twin on every path. Every
outcome is one finding of `rules`, whose rule fixes the status, and the library branches on a rule, a status or a
member, never on a message.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from fylgja_core import findings
from fylgja_core.client import Client, FollowError, ProblemError, TransportError, UnsupportedVersion
from fylgja_core.findings import Finding, Verdict

from fylgja_orchestrator.rehearsal import planning, rules
from fylgja_orchestrator.rehearsal.documents import finding
from fylgja_orchestrator.rehearsal.names import twin_name, twin_prefix
from fylgja_orchestrator.rehearsal.planning import stamp
from fylgja_orchestrator.rehearsal.report import headline, render
from fylgja_orchestrator.rehearsal.source import Change, ChangeSource

# Seconds between two verifies of the settle, the core's own verify poll.
SETTLE_POLL_S = 5.0
# Seconds before a stage's verify is asked once more, where every failure the baseline did not have is a node unread:
# a node's Service a step kept can be without its endpoint for a second or two (CONTRIBUTING.md, the walk).
VERIFY_AGAIN_S = 5.0
# Seconds a twin whose deletion was asked is read for until it is gone, and between two reads.
GONE_S = 120.0
GONE_POLL_S = 2.0

# The core's rules the rehearsal branches on.
CANCELLED = "run.cancelled"
DIVERGED = "step.diverged"
UNREAD_NODE = "verify.node.unread"
NO_ROOM = "admission.capacity"
NO_IMAGE = "admission.image.absent"
REFUSED_BUILDS = ("plan.rejected", "bundle.rejected")
# The problems of a call naming the rehearsal's twin that say it was deleted under the rehearsal.
TWIN_GONE = ("twin.not_found", "twin.deleting", "twin.conflict")
# The refusals of a run of the runtime's set-up, beside the room and an image, as a dry run's are.
SET_UP = ("admission.", "credential.")
# The statuses of a problem that refuse the token.
TOKEN = (401, 403)
# The causes after which nothing can be read of the core, so a deletion is asked once and not waited for.
UNREAD = (rules.CORE_UNREACHABLE, rules.CORE_REFUSED)


@dataclass(frozen=True)
class Limits:
    """A rehearsal's two bounds, in seconds on its clock: the settle's budget, and the rehearsal's one time limit."""

    settle_s: float = 180.0
    limit_s: float = 3600.0


class _Ended(Exception):
    """The rehearsal concluded before its end: the finding that is its cause."""

    def __init__(self, cause: dict[str, Any]) -> None:
        super().__init__(cause["rule"])
        self.cause = cause


class _Limit(Exception):
    """The rehearsal's time limit passed."""


def rehearse(
    source: ChangeSource,
    core: Client,
    ref: str,
    scope: str,
    *,
    run_id: str,
    limits: Limits,
    progress: Callable[[str], None] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], str] = stamp,
) -> dict[str, Any]:
    """The rehearsal of the change `ref` names, every stage read under `scope`, on the twin `run_id` names with it: its
    rehearsal 1 document, once its report is posted. What the source's `change` raises is raised, before anything else
    is asked. `clock` and `sleep` are every clock the rehearsal reads and every wait it makes; `now` stamps when the
    stages were read; `progress` is given a plain line an event.

    Three things bend D-085 and D-086 for this core:

    - **The time limit, and a watch.** No call of the client takes a timeout, and `follow` takes no bound. So
      `limits.limit_s` is a deadline on `clock`, checked before every call on the core and the source, in every wait of
      the rehearsal's own, and at every phase `follow` reports. A plain call is bounded by the client's own 30 s and a
      verify by its 300 s read. The limit cannot fire between two phases `follow` reports, or on a watch that reports
      none: there the rehearsal is bounded by whoever runs it, a deployment's own timeout or Ctrl-C, either of which
      arrives as a `BaseException`. That asks the twin's deletion, waits for nothing, posts nothing and is raised
      again: the caller concludes stopped, since no document is written (D-085).
    - **A deletion is read to its end, not followed.** This core retries a failed destroy for ever and files no
      `unclean`, so a deletion ends no run that could be followed. The rehearsal asks it, then reads the twin until it
      is not found, at once and then after each `GONE_POLL_S` while less than `GONE_S` has passed: for each twin it
      reclaims, and for its own at its end, which one still there then leaves named in the report.
    - **The clean-up is one request.** API 1's deletion marks the run in flight cancelling itself, so the cancel and
      the deletion D-085 names are the one call, which answers at once.

    And what the example leaves out (D-086): any reclaim beyond the twin's name; a deadline computed from the
    packages; a retry on a busy runtime, a refusal for room ending the rehearsal not rehearsed, its remedy asking
    again; a bound on how many rehearsals run at once; and loss across a step."""
    started = clock()
    change = source.change(ref)
    rehearsal = _Rehearsal(source, core, change, scope, run_id, limits, progress or _unsaid, clock, sleep, now, started)
    try:
        rehearsal.carry()
        rehearsal.destroy()
    except BaseException:
        rehearsal.abandon()
        raise
    document = rehearsal.document(clock() - started)
    # Rendered outside the post's guard: a fault of the renderer's own is raised, not said of the source.
    report = render(document, limit=source.comment_limit)
    try:
        source.post(change, report)
    except Exception as e:
        document["findings"].append(_said(rules.REPORT_UNPOSTED, f"The report could not be posted on {change.where} "
                                                                 f"({type(e).__name__}); the status stands."))
        rehearsal.say("report: not posted")
    else:
        rehearsal.say("report: posted")
    return document


def _unsaid(line: str) -> None:
    """The progress of a rehearsal no one is told of."""


class _Rehearsal:
    """One rehearsal as it goes, and what it has met so far: the document it ends in is made of it."""

    def __init__(
        self,
        source: ChangeSource,
        core: Client,
        change: Change,
        scope: str,
        run_id: str,
        limits: Limits,
        say: Callable[[str], None],
        clock: Callable[[], float],
        sleep: Callable[[float], None],
        now: Callable[[], str],
        started: float,
    ) -> None:
        self.source, self.core, self.change, self.scope = source, core, change, scope
        self.run_id, self.limits = run_id, limits
        self.say, self.clock, self.sleep, self.now = say, clock, sleep, now
        self.started = started
        self.twin = twin_name(change, run_id)
        self.plan: dict[str, Any] | None = None
        self.stages: list[dict[str, Any]] = []
        self.already_failing: list[dict[str, Any]] = []
        self.room: list[str] | None = None
        self.reclaimed: list[str] = []
        self.warnings: list[dict[str, Any]] = []
        self.cause: dict[str, Any] | None = None
        # The findings of the baseline's last settle verdict, by rule and object: a later failure is the change's only
        # where none of them has its rule and object.
        self.baseline: set[tuple[str, str | None]] = set()
        # Whether the twin's create was asked, after which every path deletes it.
        self.asked = False
        # The stage in progress, by its number and its label, for a cause's sentence.
        self.at: tuple[int, str] | None = None
        # How one asks for the rehearsal again, in the source's words, lowered as the end of a cause's sentence; the
        # whole sentence is `source.again`.
        self.again_clause = rules.clause(source.again)

    # The path.

    def carry(self) -> None:
        """Reclaim, plan, look, create and settle, step and verify, until the last stage or a cause."""
        try:
            self._reclaim()
            built = self._planned()
            self._look(built)
            self._baseline(*built[0])
            self._steps(built)
        except _Ended as e:
            self.cause = e.cause
        except _Limit:
            at = f" at stage {self.at[0]}, {self.at[1]}," if self.at else ""
            self.cause = _said(rules.LIMIT_PASSED, f"The rehearsal passed its time limit of {self.limits.limit_s:g} s"
                                                   f"{at} and was stopped. Nothing is said about the change: "
                                                   f"{self.again_clause}, or raise the limit.")
        except ProblemError as e:
            self.cause = self._refused(e, own=True)
        except TransportError as e:
            self.cause = _said(rules.CORE_UNREACHABLE, f"The core did not answer: {str(e).removesuffix('.')}. Check "
                                                       "that it runs and that FYLGJA_API_ADDRESS names it, then "
                                                       f"{self.again_clause}.")
        except (FollowError, UnsupportedVersion) as e:
            self.cause = _said(rules.CORE_UNREACHABLE, "The core answered, but not as this library expects: "
                                                       f"{str(e).removesuffix('.')}. Check the core's version against "
                                                       f"this library's, then {self.again_clause}.")

    def _reclaim(self) -> None:
        """Every twin of the change's asked deleted, then read until it is gone: the newest rehearsal of a change is
        the one that stands. One under this rehearsal's own name is deleted too, since nothing is this rehearsal's
        yet: it is an earlier try of the same run's, which its create would otherwise meet for ever. One still there
        after `GONE_S` is the cause: this rehearsal does not start."""
        prefix = twin_prefix(self.change)
        self._check()
        listed = self.core.list_twins()
        earlier = [twin["name"] for twin in listed if twin["name"].startswith(prefix)]
        for name in [name for name in earlier if self._delete(name)]:
            if not self._gone(name, limited=True):
                raise _Ended(_said(rules.TWIN_HELD, f"An earlier rehearsal's twin, {name}, was not removed within "
                                                    f"{GONE_S:g} s, so this rehearsal did not start. Remove it with "
                                                    f"fylgja-core twin destroy {name}, then {self.again_clause}."))
            self.reclaimed.append(name)
            self.warnings.append(_said(rules.TWIN_RECLAIMED, f"The twin {name}, left by an earlier rehearsal of this "
                                                             "change, was removed before this one started."))
            self.say(f"reclaim: {name} deleted")

    def _delete(self, name: str) -> bool:
        """An earlier twin's deletion asked: whether it was there to delete."""
        self._check()
        try:
            self.core.delete_twin(name)
        except ProblemError as e:
            if e.status == 404:
                return False
            raise _Ended(self._refused(e, own=False)) from e
        return True

    def _planned(self) -> list[tuple[int, dict[str, Any]]]:
        """The change's plan, every stage read, filed, built and diffed: each stage that built, by its number. A plan
        refused or with nothing to build concludes with the plan's own finding, and one not finished with its fault,
        whose sentence names no stage: none is in progress on the twin while the stages are read."""
        self.plan, fault = planning.read(self.source, self.core, self.change, self.scope, now=self.now,
                                         progress=self.say, before=self._check)
        entries: list[dict[str, Any]] = self.plan["stages"]
        self.stages = [{"result": "empty" if entry["outcome"] == "empty" else "not_reached"} for entry in entries]
        if fault is not None:
            if isinstance(fault, (_Limit, ProblemError, TransportError, UnsupportedVersion)):
                raise fault
            raise _Ended(_said(rules.SOURCE_FAILED, f"The change's stages could not be read from its source "
                                                    f"({type(fault).__name__}). Check that the source answers, then "
                                                    f"{self.again_clause}."))
        if self.plan["status"] in ("refused", "empty"):
            for k, entry in enumerate(entries, 1):
                if entry["outcome"] == "refused":
                    errors = [f for f in entry.get("findings", []) if f["severity"] == "error"]
                    self.stages[k - 1] = {"result": "failed", "failures": errors}
            raise _Ended(dict(self.plan["findings"][0]))
        return [(k, entry) for k, entry in enumerate(entries, 1) if entry["outcome"] == "built"]

    def _look(self, built: Sequence[tuple[int, Mapping[str, Any]]]) -> None:
        """A dry run of each distinct bundle of the stages that built, in order, as the twin it would make: what the
        runtime refuses to make is refused before anything is created. The stage in progress is the baseline
        throughout, the first the twin would reach, so the limit passing here is said of it, as the heading says it;
        a refusal is said of the stage it refuses."""
        self.at = (built[0][0], built[0][1]["label"])
        looked: set[str] = set()
        for k, entry in built:
            if entry["bundle_id"] in looked:
                continue
            looked.add(entry["bundle_id"])
            label = entry["label"]
            self._check()
            try:
                self.core.apply_twin(self.twin, {"bundle_id": entry["bundle_id"]}, if_none_match="*", dry_run=True)
            except ProblemError as e:
                if e.status != 422:
                    raise
                self.say(f"look: stage {k}, {label}: refused ({e.problem.rule})")
                raise _Ended(self._unfit(k, label, e)) from e
            self.say(f"look: stage {k}, {label}: fits")

    def _unfit(self, k: int, label: str, e: ProblemError) -> dict[str, Any]:
        """The cause a dry run's refusal of stage `k` gives: no room, an image absent, a bundle the runtime cannot
        build, which fails the stage, or the runtime's set-up."""
        found = [_found(f) for f in e.problem.findings or ()]
        rule = e.problem.rule
        if rule == NO_ROOM:
            return self._no_room(found[0]["message"] if found else e.problem.detail or e.problem.title, at=(k, label))
        if rule == NO_IMAGE:
            return self._absent(found[0]["message"] if found else e.problem.detail or e.problem.title)
        if rule in REFUSED_BUILDS:
            failures = [f for f in found if f["severity"] == "error"] or found
            self.stages[k - 1] = {"result": "failed", "failures": failures}
            return _said(rules.STAGE_FAILED, f"The runtime cannot build stage {k}, {label}{_first(failures)}.")
        return self._set_up(found or [finding(rule, "error", e.problem.detail or e.problem.title)], at=(k, label))

    def _baseline(self, k: int, entry: Mapping[str, Any]) -> None:
        """The twin created at the baseline, stage `k`, its run followed, then settled: verify asked again until it
        holds or `limits.settle_s` passes, what still fails then failing before the change."""
        label = entry["label"]
        self.at = (k, label)
        self.say(f"create: stage {k}, {label}, as {self.twin}")
        began = self.clock()
        self._check()
        self.asked = True
        record, _ = self.core.apply_twin(self.twin, {"bundle_id": entry["bundle_id"]}, if_none_match="*")
        run, verdict = self._followed(record, ("create",))
        if CANCELLED in {f.rule for f in verdict.findings}:
            raise _Ended(self._cancelled(run["operation"]))
        if verdict.status != "ok":
            refused = self._refused_run(verdict) if verdict.status == "rejected" else None
            if refused is not None:
                raise _Ended(refused)
            failures = _errors(verdict.findings)
            self.stages[k - 1] = {"result": "failed", "failures": failures, "run_id": run["id"],
                                  "took_s": self.clock() - began}
            raise _Ended(_said(rules.BASELINE_FAILED, f"The baseline, stage {k}, {label}, could not be created"
                                                      f"{_first(failures)}. Nothing is said about the stages after "
                                                      "it."))
        stage: dict[str, Any] = {"result": "created", "run_id": run["id"]}
        first = self.clock()
        verdict = self._settled(first)
        while verdict.status != "ok" and self.clock() - first < self.limits.settle_s:
            self._wait(SETTLE_POLL_S)
            verdict = self._settled(first)
        self.baseline = {(f.rule, f.object) for f in verdict.findings}
        if verdict.status != "ok":
            self.already_failing = _errors(verdict.findings)
            stage["wait"] = {"budget_s": int(self.limits.settle_s), "after_s": self.clock() - first}
        self.stages[k - 1] = stage | _counts(verdict) | {"took_s": self.clock() - began}

    def _settled(self, first: float) -> Verdict:
        """One verify of the settle, which began at `first`, said."""
        verdict = self._verify()
        self.say(f"settle: verify {verdict.status}, {self.clock() - first:g}s of {self.limits.settle_s:g}s")
        return verdict

    def _steps(self, built: Sequence[tuple[int, Mapping[str, Any]]]) -> None:
        """Each stage after the baseline that built, in order: skipped where its bundle is the one before on a twin
        that is Ready, else stepped and verified, the first that fails ending the rehearsal there."""
        (k, base), *later = built
        if not later:
            self.warnings.append(_said(rules.STEPS_NONE, f"Only stage {k}, {base['label']}, builds, so the twin was "
                                                         "created and verified there and no step was rehearsed."))
            return
        previous = base["bundle_id"]
        for k, entry in later:
            self.at = (k, entry["label"])
            if entry["bundle_id"] == previous and self._ready():
                self.stages[k - 1] = {"result": "skipped"}
                self.say(f"skip: stage {k}, {entry['label']}: unchanged")
                continue
            self._step(k, entry)
            previous = entry["bundle_id"]
        self.at = None

    def _ready(self) -> bool:
        """Whether the twin's `Ready` condition reads `True`."""
        self._check()
        record, _ = self.core.get_twin(self.twin)
        return any(c["type"] == "Ready" and c["status"] == "True" for c in record["status"]["conditions"])

    def _step(self, k: int, entry: Mapping[str, Any]) -> None:
        """The twin stepped to stage `k`, restarts allowed, the run its write started followed, then verified: a
        failure the baseline did not have fails the stage, a node unread among them alone asked once more first."""
        label = entry["label"]
        self.say(f"step: stage {k}, {label}")
        began = self.clock()
        self._check()
        record, _ = self.core.apply_twin(self.twin, {"bundle_id": entry["bundle_id"], "allow_restart": True},
                                         if_match="*")
        stage: dict[str, Any] = {"result": "passed"}
        # A spec the twin already has is written by no one: no run started, and `follow` would answer the last.
        if record["status"]["observed_generation"] != record["generation"]:
            run, verdict = self._followed(record, ("step", "create"))
            stage["run_id"] = run["id"]
            if verdict.wait is not None and verdict.wait.outcome == "expired":
                stage["wait"] = {"budget_s": verdict.wait.budget_s, "after_s": verdict.wait.after_s}
            if verdict.status != "ok":
                raise _Ended(self._step_failed(k, label, run, verdict, stage | {"took_s": self.clock() - began}))
        verdict = self._verified(k, label)
        new = self._new(verdict)
        if new and all(f["rule"] == UNREAD_NODE for f in new):
            self._wait(VERIFY_AGAIN_S)
            verdict = self._verified(k, label)
            new = self._new(verdict)
        stage |= _counts(verdict) | {"took_s": self.clock() - began}
        if new:
            self.stages[k - 1] = stage | {"result": "failed", "failures": new}
            many = "failure" if len(new) == 1 else "failures"
            raise _Ended(_said(rules.STAGE_FAILED, f"Verify found {len(new)} {many} at stage {k}, {label}, that the "
                                                   f"baseline did not have, the first {rules.quote(new[0])}."))
        self.stages[k - 1] = stage

    def _step_failed(
        self, k: int, label: str, run: Mapping[str, Any], verdict: Verdict, stage: dict[str, Any]
    ) -> dict[str, Any]:
        """The cause of a step's run that did not end `ok`: cancelled by another client, before its apply began
        (`failed` with `run.cancelled`) or after it (`diverged` with `step.diverged` its only error, which the core
        files for that cancel alone); refused for the runtime's room, an image or its set-up, as a create is; or else
        the stage failed, its failures the run's errors but `step.diverged`, which the sentence says in words."""
        errors = _errors(verdict.findings)
        if verdict.status == "failed" and CANCELLED in {f.rule for f in verdict.findings}:
            return self._cancelled(run["operation"])
        if verdict.status == "diverged" and {f["rule"] for f in errors} == {DIVERGED}:
            return self._cancelled(run["operation"], diverged=True)
        refused = self._refused_run(verdict) if verdict.status == "rejected" else None
        if refused is not None:
            return refused
        failures = [f for f in errors if f["rule"] != DIVERGED]
        self.stages[k - 1] = stage | {"result": "failed", "failures": failures}
        if verdict.status == "diverged":
            return _said(rules.STAGE_FAILED, f"The step to stage {k}, {label}, failed and left the twin diverged"
                                             f"{_first(failures)}.")
        return _said(rules.STAGE_FAILED, f"The core refused the step to stage {k}, {label}{_first(failures)}.")

    def _verified(self, k: int, label: str) -> Verdict:
        """One verify of stage `k`, said."""
        verdict = self._verify()
        counts = verdict.counts
        held, failed = (counts.held, counts.failed) if counts is not None else (0, 0)
        self.say(f"verify: stage {k}, {label}: {held} hold, {failed} fail")
        return verdict

    def _new(self, verdict: Verdict) -> list[dict[str, Any]]:
        """Verify's errors whose rule and object no finding of the baseline's last settle verdict has."""
        return _errors(f for f in verdict.findings if (f.rule, f.object) not in self.baseline)

    # The core's answers.

    def _followed(self, record: Mapping[str, Any], operations: Sequence[str]) -> tuple[dict[str, Any], Verdict]:
        """The run a write of the twin's spec started, followed to its end, and its verdict; the twin gone meanwhile
        is the cause, whatever the run's verdict."""
        self._check()
        followed = self.core.follow(record, operations, progress=self._phase)
        if followed.gone:
            raise _Ended(self._deleted())
        return followed.run, findings.decode(followed.run["verdict"])

    def _phase(self, line: str) -> None:
        """A phase `follow` reports, said, then the limit checked."""
        self.say(line)
        self._check()

    def _verify(self) -> Verdict:
        self._check()
        return findings.decode(self.core.verify_twin(self.twin))

    def _refused_run(self, verdict: Verdict) -> dict[str, Any] | None:
        """The cause a create's or a step's run `rejected` gives where its refusal is the runtime's, as a dry run's
        would be: no room, an image absent, or its set-up; None for any other."""
        for f in verdict.findings:
            if f.severity != "error":
                continue
            if f.rule == NO_ROOM:
                return self._no_room(f.message)
            if f.rule == NO_IMAGE:
                return self._absent(f.message)
            if f.rule.startswith(SET_UP):
                return self._set_up([_found(f)])
        return None

    def _no_room(self, message: str, *, at: tuple[int, str] | None = None) -> dict[str, Any]:
        """`rehearsal.capacity` with the core's own message, of the stage `at` or else the one in progress, and the
        room read now, for the report; a reading that fails leaves the room unsaid, the cause as it is."""
        try:
            reading = self.core.capacity()
        except (ProblemError, TransportError):
            pass
        else:
            self.room = _room(reading)
        return _said(rules.CAPACITY, f"The runtime has no room for the twin{self._of(at=at)}: {message} Nothing is "
                                     f"wrong with the change: {self.again_clause} when the runtime has room.")

    def _absent(self, message: str) -> dict[str, Any]:
        """`rehearsal.image.absent`, with the core's own message."""
        return _said(rules.IMAGE_ABSENT, f"An image the twin needs is not on the runtime: {message} Import it there, "
                                         f"then {self.again_clause}.")

    def _set_up(self, failures: Sequence[Mapping[str, Any]], *, at: tuple[int, str] | None = None) -> dict[str, Any]:
        """`rehearsal.admission.refused`, of the stage `at` or else the one in progress."""
        return _said(rules.ADMISSION_REFUSED, f"The runtime refused the twin{self._of(at=at)}{_first(failures)}. That "
                                              "is the runtime's set-up, not the change: correct it, then "
                                              f"{self.again_clause}.")

    def _cancelled(self, operation: str, *, diverged: bool = False) -> dict[str, Any]:
        """`rehearsal.run.cancelled`; `diverged`, of a step cancelled after its apply began, which left the twin
        diverged."""
        after = " after its apply began, which left the twin diverged," if diverged else ","
        return _said(rules.RUN_CANCELLED, f"The {operation} run of the twin was cancelled by another client{after} so "
                                          f"the rehearsal stopped{self._of('at')}. {self.source.again}")

    def _deleted(self) -> dict[str, Any]:
        return _said(rules.TWIN_DELETED, f"The twin {self.twin} was deleted while the rehearsal ran, by a newer "
                                         f"rehearsal of this change or by hand, so it stopped{self._of('at')}. The "
                                         "newer rehearsal's report stands.")

    def _refused(self, e: ProblemError, *, own: bool) -> dict[str, Any]:
        """The cause a refusal of the core's gives: on a call naming the rehearsal's twin (`own`), the twin deleted
        under it where the refusal says so; the token refused; or a request the rehearsal needs refused."""
        rule = e.problem.rule
        if own and rule in TWIN_GONE:
            return self._deleted()
        if e.status in TOKEN:
            return _said(rules.CORE_REFUSED, f"The core refused the token ({rule}). Put a token whose hash the core's "
                                             f"token file holds in FYLGJA_API_TOKEN, then {self.again_clause}.")
        detail = e.problem.detail or e.problem.title
        detail = detail if detail.endswith(".") else f"{detail}."
        return _said(rules.CORE_REFUSED, f"The core refused a request the rehearsal needs: {e.status} {rule}: {detail} "
                                         f"Read the core's log, then {self.again_clause}.")

    def _of(self, word: str = "of", *, at: tuple[int, str] | None = None) -> str:
        """The stage `at`, or else the one in progress, as a sentence names it, `of stage <k>, <label>`; nothing where
        none is."""
        at = at or self.at
        return f" {word} stage {at[0]}, {at[1]}" if at else ""

    # The waits.

    def _check(self) -> None:
        """`_Limit` once `limits.limit_s` has passed on the clock since the rehearsal began."""
        if self.clock() - self.started >= self.limits.limit_s:
            raise _Limit()

    def _wait(self, seconds: float) -> None:
        """A wait of the rehearsal's own, the limit checked ahead of it."""
        self._check()
        self.sleep(seconds)

    def _gone(self, name: str, *, limited: bool) -> bool:
        """Whether the twin `name`, its deletion asked, is gone: read at once, then after each `GONE_POLL_S` while
        less than `GONE_S` has passed; `limited`, the limit checked before each read and each wait."""
        first = self.clock()
        while True:
            if limited:
                self._check()
            try:
                self.core.get_twin(name)
            except ProblemError as e:
                if e.status == 404:
                    return True
                raise
            if self.clock() - first >= GONE_S:
                return False
            if limited:
                self._check()
            self.sleep(GONE_POLL_S)

    # The end.

    def destroy(self) -> None:
        """The twin's deletion asked, once its create was, and read until it is gone; asked alone after the core did
        not answer or refused, since nothing can then be read. A twin left is a warning, which changes no status."""
        if not self.asked:
            return
        try:
            self.core.delete_twin(self.twin)
        except ProblemError as e:
            if e.status == 404:
                self.say(f"destroy: {self.twin} gone")
            else:
                self.warnings.append(self._left("not asked"))
            return
        except TransportError:
            self.warnings.append(self._left("not asked"))
            return
        self.say(f"destroy: {self.twin} asked")
        if self.cause is not None and self.cause["rule"] in UNREAD:
            self.warnings.append(self._left("asked"))
            return
        try:
            gone = self._gone(self.twin, limited=False)
        except (ProblemError, TransportError):
            self.warnings.append(self._left("asked"))
            return
        if gone:
            self.say(f"destroy: {self.twin} gone")
        else:
            self.warnings.append(self._left("waited"))

    def abandon(self) -> None:
        """The twin's deletion asked, once its create was, and waited for by nothing: the rehearsal is being ended by
        whoever runs it. What the call raises of the core's is not its concern."""
        if not self.asked:
            return
        with contextlib.suppress(ProblemError, TransportError):
            self.core.delete_twin(self.twin)

    def _left(self, how: str) -> dict[str, Any]:
        """`rehearsal.twin.left`: its deletion waited for and the twin still there, asked alone, or not asked."""
        twin = self.twin
        if how == "waited":
            message = (f"The twin {twin} was not removed within {GONE_S:g} s: read it with fylgja-core twin show "
                       f"{twin}, and remove it with fylgja-core twin destroy {twin}.")
        elif how == "asked":
            message = (f"The twin {twin}'s deletion was asked and not waited for: fylgja-core twin show {twin} says "
                       "whether it is gone.")
        else:
            message = (f"The twin {twin} may still be there: remove it with fylgja-core twin destroy {twin} once the "
                       "core answers.")
        return _said(rules.TWIN_LEFT, message)

    def document(self, took_s: float) -> dict[str, Any]:
        """The rehearsal 1 document of what the rehearsal met: its status and its headline given by its cause."""
        doc: dict[str, Any] = {
            "rehearsal_version": "1",
            "status": rules.STATUS[self.cause["rule"]] if self.cause is not None else "passed",
            "headline": "",
            "plan": self.plan,
            "twin": self.twin,
            "run_id": self.run_id,
            "took_s": took_s,
            "stages": self.stages,
            "already_failing": self.already_failing,
            "reclaimed": self.reclaimed,
            "findings": [*([self.cause] if self.cause is not None else []), *self.warnings],
        }
        if self.room is not None:
            doc["room"] = self.room
        doc["headline"] = headline(doc)
        return doc


def _said(rule: str, message: str) -> dict[str, Any]:
    """One of the rehearsal's own findings, at its rule's severity."""
    return finding(rule, rules.SEVERITY[rule], message)


def _first(failures: Sequence[Mapping[str, Any]]) -> str:
    """`: <the first failure quoted>`, as a cause's sentence gives it; nothing where there is none."""
    return f": {rules.quote(failures[0])}" if failures else ""


def _found(f: Finding) -> dict[str, Any]:
    return finding(f.rule, f.severity, f.message, f.object)


def _errors(found: Iterable[Finding]) -> list[dict[str, Any]]:
    """The errors among `found`, as the document holds a finding."""
    return [_found(f) for f in found if f.severity == "error"]


def _counts(verdict: Verdict) -> dict[str, Any]:
    """A verify's counts as a stage holds them; nothing where the verdict has none."""
    counts = verdict.counts
    if counts is None:
        return {}
    return {"counts": {"held": counts.held, "failed": counts.failed, "skipped": counts.skipped}}


def _room(reading: Mapping[str, Any]) -> list[str]:
    """The capacity read, in words: a line a host, then what is pending."""
    lines = [f"{host['name']}: {host['cpu']['free']:g} of {host['cpu']['total']:g} CPUs and "
             f"{host['memory_mb']['free']} of {host['memory_mb']['total']} MiB free" for host in reading["hosts"]]
    pending = reading["pending"]
    lines.append(f"pending: {pending['nodes']} nodes, {pending['cpu']:g} CPUs, {pending['memory_mb']} MiB")
    return lines
