"""The example rehearsals of `internal/rehearsal/report_test.go`, carried over by name: the
example proposed change of 015's `contracts/rehearse-command.md`, change-1, its branch point
refused scope.empty on a main that holds no network, the mark seeded, the marks third-link
and bad-port, and the head, every stage read under the scope tag:fylgja; and the runs of it
each test reads, each as its document's block and status."""

import copy
from dataclasses import dataclass

from fylgja_orchestrator.documents import rehearsal as r
from fylgja_orchestrator.documents.deadline import ROLE_BASELINE, ROLE_REFUSED, ROLE_REHEARSED
from fylgja_orchestrator.documents.findings import REJECTION, Document, Finding, Findings, new_document
from fylgja_orchestrator.documents.plan import Pair, StepDiff

CHANGE = "change-1"
SCOPE = "tag:fylgja"
RESOLVED_AT = "2026-10-17T14:02:11Z"
REHEARSE_RUN = "01a1b2c3-0000-7000-8000-0000000000aa"
PROVISION_RUN = "01a1b2c3-0000-7000-8000-0000000000b1"
STEP_RUN = "01a1b2c3-0000-7000-8000-0000000000c"

SEEDED_ID = "5c" * 32
THIRD_ID = "d0" * 32
BAD_ID = "ba" * 32
HEAD_ID = "cc" * 32

SEEDED_SNAPSHOT = "a1" * 32
THIRD_SNAPSHOT = "a2" * 32
BAD_SNAPSHOT = "a3" * 32
HEAD_SNAPSHOT = "a4" * 32

MARKER = "FYLGJA-MARKER"
"""A checksum no artifact has, standing where a step names an artifact's."""


def F(severity: str, step: str, rule: str, obj: str, message: str) -> Finding:
    return Finding(severity, rule, obj, message, step)


def branch_point() -> r.Stage:
    return r.Stage(ref=CHANGE + "/branch-point", label="branch-point", at_source="branch_point", branch="main",
                   at="2026-10-16T17:20:19.944651+00:00", role=ROLE_REFUSED,
                   findings=[F(REJECTION, "read", "scope.empty", "tag:fylgja",
                               "scope tag:fylgja selects no device on branch main")])


def seeded() -> r.Stage:
    return r.Stage(ref=CHANGE + "/seeded", label="seeded", description="after the link is cabled", at_source="written",
                   branch=CHANGE, at="2026-10-16T17:25:30.118244+00:00", snapshot_id=SEEDED_SNAPSHOT,
                   bundle_id=SEEDED_ID, role=ROLE_BASELINE)


def third_link(role: str) -> r.Stage:
    return r.Stage(ref=CHANGE + "/third-link", label="third-link", description="third link", at_source="given",
                   branch=CHANGE, at="2026-10-16T17:30:00.000000+00:00", snapshot_id=THIRD_SNAPSHOT,
                   bundle_id=THIRD_ID, role=role)


def bad_port(role: str) -> r.Stage:
    """Its description holds what markdown and Mermaid must escape: quotes, angle brackets, a
    pipe and a newline."""
    return r.Stage(ref=CHANGE + "/bad-port", label="bad-port",
                   description='a port <disabled> "by mistake" | n1\nsecond line', at_source="given", branch=CHANGE,
                   at="2026-10-16T17:30:05.000000+00:00", snapshot_id=BAD_SNAPSHOT, bundle_id=BAD_ID, role=role)


def head(role: str) -> r.Stage:
    return r.Stage(ref=CHANGE + "/head", label="head", at_source="head", branch=CHANGE,
                   at="2026-10-16T17:30:11.884302+00:00", snapshot_id=HEAD_SNAPSHOT, bundle_id=HEAD_ID, role=role)


def input_of(deadline_s: int, *stages: r.Stage) -> r.Input:
    return r.Input(proposed_change={"id": "18df5c2e-0000-4000-8000-000000000001", "name": "third link",
                                    "branch": CHANGE, "draft": True},
                   resolved_at=RESOLVED_AT, scope=SCOPE, deadline_s=deadline_s, ceiling_s=3600, stages=list(stages))


def counts(ports: int, failed: int) -> dict:
    """A three-node twin's last read: a host name per node, ports and neighbours each, every
    one held but failed of the neighbours."""
    return {
        "host_name": {"held": 3, "failed": 0, "unread": 0},
        "port_enabled": {"held": ports, "failed": 0, "skipped": 0, "unread": 0},
        "neighbor": {"held": ports - failed, "failed": failed, "skipped": 0, "unread": 0},
        "burst": {"held": 0, "failed": 0},
        "record": {"held": 3, "failed": 0},
    }


def probed_counts(ports: int, failed: int, burst_failed: bool) -> dict:
    """A probed three-node twin's last read: counts' beside one burst, held, or failed."""
    c = counts(ports, failed)
    c["burst"] = {"held": 0, "failed": 1, "unread": 0} if burst_failed else {"held": 1, "failed": 0, "unread": 0}
    return c


def wait(outcome: str, after_s: float, reads: int, *failing: dict) -> dict:
    return {"outcome": outcome, "budget_s": 120, "reads": reads, "after_s": after_s, "from": RESOLVED_AT,
            "ended_at": RESOLVED_AT, "failing": list(failing)}


def run() -> dict:
    return {"workflow_id": "fylgja-rehearse", "run_id": REHEARSE_RUN}


def destroyed() -> dict:
    return {"teardown": "done", "unstage": "done",
            "removed": ["lab fylgja (3 containers)", "twin directory /srv/fylgja/local/twin"], "remaining": []}


def built(w: dict, c: dict, took_s: float) -> r.StageResult:
    """The baseline created, its wait as given."""
    return r.StageResult(ref=CHANGE + "/seeded", verdict=r.VERDICT_BASELINE,
                         provision=r.Provision(r.PROVISION_READY, PROVISION_RUN), wait=w, counts=c, took_s=took_s)


def step_to(ref: str, n: int, outcome: str, whole_s: float, *pushes: dict) -> r.StepRun:
    """A step child into ref, numbered for its run id."""
    push = {p["node"]: p["took_s"] for p in pushes if p.get("took_s") is not None}
    timings = {"whole_s": whole_s}
    if push:
        timings["push"] = push
    return r.StepRun(outcome=outcome, run_id=STEP_RUN + chr(ord("0") + n), pushed=list(pushes), timings=timings)


def landed(node: str, s: float) -> dict:
    return {"node": node, "reasons": ["artifact"], "outcome": "landed", "took_s": s}


BASELINE_FINDING = {"rule": "verify.neighbor", "object": "n1:ethernet-1/2",
                    "message": "node n1 (172.20.20.2): port ethernet-1/2 sees no neighbour at "
                               "/interface[name=ethernet-1/2]; link l1 names n2 ethernet-1/2 at its far end"}
"""The baseline's one finding, which every later wait repeats."""


@dataclass
class Example:
    name: str
    inp: r.Input
    res: r.Result
    status: str

    def block(self) -> dict:
        return r.build(self.inp, self.res)

    def document(self) -> Document:
        """The example's findings document as the flow sends it: the block, its findings, the
        refusal's own finding when no run began, and the run's own run.in_flight when it was
        refused at its baseline's start."""
        b = self.block()
        found = r.findings_of(b)
        subject = {"branch": CHANGE, "scope": SCOPE}
        if self.res.run is None:
            found.append(F(REJECTION, "start", "rehearsal.deadline.unfit", CHANGE,
                           "the stages need 3840s, over the ceiling of 3600s"))
        elif self.res.outcome == r.OUTCOME_REJECTED:
            found.append(F(REJECTION, "provision", "run.in_flight", "fylgja-provision",
                           "the rehearsal's fylgja-provision could not start: a run is already in flight under its id"))
        elif self.res.outcome == "":
            found.append(F(REJECTION, "provision", "operation.failed", "provision", LOST_WHY))
        if self.res.run is not None:
            subject["run_id"] = self.res.run["run_id"]
        doc = new_document("twin.rehearse", subject, found)
        doc.status = self.status
        doc.set("rehearsal", b)
        return doc


def passed_run() -> Example:
    return Example("ok, the branch point refused and the head unchanged",
                   input_of(1980, branch_point(), seeded(), third_link(ROLE_REHEARSED), head(ROLE_REHEARSED)),
                   r.Result(r.OUTCOME_OK, run(), 118.4, [
                       built(wait("settled", 3.2, 2), counts(6, 0), 52.6),
                       r.StageResult(CHANGE + "/third-link", r.VERDICT_PASSED,
                                     step=step_to(CHANGE + "/third-link", 1, "stepped", 4.5, landed("n1", 2.5),
                                                  landed("n3", 2.6)),
                                     wait=wait("settled", 6.1, 4), counts=counts(8, 0), took_s=10.6),
                       r.StageResult(CHANGE + "/head", r.VERDICT_PASSED,
                                     step=step_to(CHANGE + "/head", 2, "unchanged", 0.9),
                                     wait=wait("settled", 1.0, 1), counts=counts(8, 0), took_s=1.9),
                   ], destroyed()),
                   "ok")


def failed_run() -> Example:
    bad = step_to(CHANGE + "/bad-port", 2, "diverged", 29.8,
                  {"node": "n1", "reasons": ["artifact"], "outcome": "refused", "rule": "push.refused", "took_s": 1.1},
                  landed("n3", 2.4))
    bad.phase, bad.step, bad.restarted = "push", "push", ["n3"]
    bad.timings["readiness"] = {"n3": 61.2}
    refused = [F(REJECTION, "push", "push.refused", "n1",
                 "n1 refused artifact device-config (checksum 9a0177b2e8c1d4f5a6b7c8d9e0f1a2b3) at line 12: "
                 "invalid port ethernet-1/99")]
    return Example("nonconforming, a stage diverged at its push",
                   input_of(2610, branch_point(), seeded(), third_link(ROLE_REHEARSED), bad_port(ROLE_REHEARSED),
                            head(ROLE_REHEARSED)),
                   r.Result(r.OUTCOME_STAGE_FAILED, run(), 301.6, [
                       built(wait("expired", 120, 58, BASELINE_FINDING), counts(6, 1), 172.4),
                       r.StageResult(CHANGE + "/third-link", r.VERDICT_PASSED,
                                     step=step_to(CHANGE + "/third-link", 1, "stepped", 4.5, landed("n1", 2.5),
                                                  landed("n3", 2.6)),
                                     wait=wait("expired", 120, 60, BASELINE_FINDING), counts=counts(8, 1),
                                     took_s=124.5),
                       r.StageResult(CHANGE + "/bad-port", r.VERDICT_FAILED, step=bad,
                                     wait=wait("expired", 120, 58, BASELINE_FINDING), counts=counts(8, 1),
                                     findings=refused, took_s=149.8),
                   ], destroyed()),
                   "nonconforming")


def restarted_run() -> Example:
    """passed_run whose step to the third link restarted n3 and recreated n1."""
    e = passed_run()
    e.name = "ok, a step restarted a node and recreated another"
    st = e.res.stages[1].step
    st.restarted, st.recreated, st.timings["whole_s"] = ["n3"], ["n1"], 95.3
    st.timings["readiness"] = {"n1": 70.4, "n3": 61.2}
    return e


def cut_before_readiness_run() -> Example:
    """failed_run cut by the deadline at bad-port: cancelled at phase readiness, having
    restarted n3, before n3 answered and before any push (T094)."""
    e = failed_run()
    e.name, e.status = "error, the deadline cut a step before its restarted node answered", "error"
    e.res.outcome, e.res.used_s = r.OUTCOME_CUT, 2618.2
    bad = e.res.stages[2]
    bad.verdict, bad.wait, bad.counts, bad.findings, bad.took_s = r.VERDICT_ERROR, None, None, Findings(), 2321.3
    st = bad.step
    st.outcome, st.phase, st.step = "cancelled", "readiness", "readiness"
    st.pushed = []
    st.timings.pop("readiness", None)
    st.timings.pop("push", None)
    return e


def cut_at_push_run() -> Example:
    """cut_before_readiness_run cut later, at its push: n3 answered and its push landed, n1's
    not attempted (T094)."""
    e = cut_before_readiness_run()
    e.name = "error, the deadline cut a step at its push"
    st = e.res.stages[2].step
    st.phase, st.step = "push", "push"
    st.pushed = [landed("n3", 2.4), {"node": "n1", "reasons": ["artifact"], "outcome": "not_attempted"}]
    st.timings["readiness"], st.timings["push"] = {"n3": 61.2}, {"n3": 2.4}
    return e


ADDED = {"rule": "verify.neighbor", "object": "n1:ethernet-1/3",
         "message": "node n1 (172.20.20.2): port ethernet-1/3 sees no neighbour"}


def new_finding_run() -> Example:
    return Example("nonconforming, a finding the baseline did not have",
                   input_of(1980, seeded(), third_link(ROLE_REHEARSED), head(ROLE_REHEARSED)),
                   r.Result(r.OUTCOME_STAGE_FAILED, run(), 190.2, [
                       built(wait("settled", 3.2, 2), counts(6, 0), 52.6),
                       r.StageResult(CHANGE + "/third-link", r.VERDICT_FAILED,
                                     step=step_to(CHANGE + "/third-link", 1, "stepped", 4.5, landed("n1", 2.5),
                                                  landed("n3", 2.6)),
                                     wait=wait("expired", 120, 61, ADDED), counts=counts(8, 1),
                                     new_findings=[dict(ADDED)], took_s=124.5),
                   ], destroyed()),
                   "nonconforming")


def cut_run() -> Example:
    cut = step_to(CHANGE + "/third-link", 1, "cancelled", 1861.9)
    cut.phase, cut.step = "readiness", "readiness"
    return Example("error, the deadline cut a step",
                   input_of(1980, seeded(), third_link(ROLE_REHEARSED), head(ROLE_REHEARSED)),
                   r.Result(r.OUTCOME_CUT, run(), 2001.2, [
                       built(wait("settled", 3.2, 2), counts(6, 0), 88.1),
                       r.StageResult(CHANGE + "/third-link", r.VERDICT_ERROR, step=cut, took_s=1861.9),
                   ], destroyed()),
                   "error")


def not_built_run() -> Example:
    timeout = [F(REJECTION, "readiness", "readiness.timeout", "n2", "n2 did not answer its probe within 60s")]
    return Example("failed, the baseline not built",
                   input_of(1980, branch_point(), seeded(), third_link(ROLE_REHEARSED)),
                   r.Result(r.OUTCOME_BASELINE_FAILED, run(), 243.0, [
                       r.StageResult(CHANGE + "/seeded", r.VERDICT_ERROR, findings=timeout, took_s=241.3,
                                     provision=r.Provision("failed", PROVISION_RUN, "readiness",
                                                           {"teardown": "done", "unstage": "done",
                                                            "removed": ["lab fylgja (3 containers)"],
                                                            "remaining": []})),
                   ], {"teardown": "nothing", "unstage": "nothing", "remaining": []}),
                   "failed")


def not_built_error_run() -> Example:
    """not_built_run whose create ended error, a step that could not run (T081)."""
    e = not_built_run()
    e.name, e.status = "error, the baseline's provision could not run", "error"
    e.res.outcome = r.OUTCOME_STAGE_ERROR
    base = e.res.stages[0]
    base.findings = Findings([F(REJECTION, "deploy", "operation.failed", "lab fylgja", "the deploy could not run")])
    base.provision.outcome, base.provision.step = "error", "deploy"
    return e


def unverified_run() -> Example:
    """A baseline built whose wait could not complete: its failing holds the operation.failed
    synthesised, and keeps no baseline findings (T100)."""
    failing = {"rule": "operation.failed", "object": REHEARSE_RUN,
               "message": "activity verify_twin failed: the workflow service did not answer"}
    return Example("error, the baseline built and its wait incomplete",
                   input_of(1980, branch_point(), seeded(), third_link(ROLE_REHEARSED)),
                   r.Result(r.OUTCOME_STAGE_ERROR, run(), 64.0, [
                       r.StageResult(CHANGE + "/seeded", r.VERDICT_ERROR,
                                     provision=r.Provision(r.PROVISION_READY, PROVISION_RUN),
                                     wait={"outcome": "incomplete", "budget_s": 120, "reads": 0, "after_s": 0,
                                           "from": RESOLVED_AT, "ended_at": "", "failing": [failing]},
                                     took_s=61.8),
                   ], destroyed()),
                   "error")


def unclean_run() -> Example:
    e = passed_run()
    e.name, e.status = "unclean, every stage passed and the destroy left the lab", "unclean"
    e.res.destroy = {"teardown": "failed", "unstage": "done", "removed": ["twin directory /srv/fylgja/local/twin"],
                     "remaining": ["lab fylgja (1 container)"]}
    return e


def alone_run() -> Example:
    s = seeded()
    s.findings.append(F("warning", "resolve", "rehearsal.steps.none", s.ref,
                        "one stage compiled: it is built, verified and destroyed, and no step is rehearsed"))
    return Example("ok, one stage alone", input_of(720, s),
                   r.Result(r.OUTCOME_OK, run(), 61.2, [built(wait("settled", 3.2, 2), counts(6, 0), 55.3)],
                            destroyed()),
                   "ok")


def refused_run() -> Example:
    return Example("rejected, the deadline over the ceiling",
                   input_of(3840, seeded(), third_link(ROLE_REHEARSED), bad_port(ROLE_REHEARSED), head(ROLE_REHEARSED)),
                   r.Result(), "rejected")


def held_run() -> Example:
    """A run refused at its baseline's start, another run holding the create's id (T078)."""
    return Example("rejected, the baseline's provision held by another run",
                   input_of(1980, branch_point(), seeded(), third_link(ROLE_REHEARSED)),
                   r.Result(r.OUTCOME_REJECTED, run(), 0.1, [
                       r.StageResult(CHANGE + "/seeded", r.VERDICT_NOT_REACHED),
                       r.StageResult(CHANGE + "/third-link", r.VERDICT_NOT_REACHED),
                   ]),
                   "rejected")


def lost_run() -> Example:
    """A run that started and whose end was not read (T079)."""
    return Example("error, the run's end not read",
                   input_of(1980, branch_point(), seeded(), third_link(ROLE_REHEARSED), head(ROLE_REHEARSED)),
                   r.Result(run=run()), "error")


LOST_WHY = "waiting for run " + REHEARSE_RUN + ": the workflow service did not answer"


def flow_of(probe: str, outcome: str, sent: int, lost: int, gap_s: float) -> dict:
    """One probe's flow across a step, from its a host's container to its b host's."""
    return {"probe": probe, "from": f"clab-fylgja-{probe}-a", "to": f"clab-fylgja-{probe}-b", "outcome": outcome,
            "sent": sent, "lost": lost, "longest_gap_s": gap_s}


def loss_of(*probes: dict) -> dict:
    return {"basis": "container", "probes": list(probes), "added": [], "dropped": []}


def probed_run() -> Example:
    """Three stages, the first created, the second stepped with n1-loop's flow measured, 274
    of 300 lost and a 54.8s gap, the third refused at the compile, its snapshot filed (016)."""
    refused_head = head(ROLE_REFUSED)
    refused_head.bundle_id = ""
    refused_head.findings.append(F(REJECTION, "compile", "platform.unsupported", "n1",
                                   "node n1's platform is supported by no loaded package"))
    return Example("ok, a probe's loss across the step and the head refused at the compile",
                   input_of(2130, seeded(), third_link(ROLE_REHEARSED), refused_head),
                   r.Result(r.OUTCOME_OK, run(), 182.0, [
                       built(wait("settled", 3.2, 2), probed_counts(6, 0, False), 52.6),
                       r.StageResult(CHANGE + "/third-link", r.VERDICT_PASSED,
                                     step=step_to(CHANGE + "/third-link", 1, "stepped", 64.5, landed("n1", 2.5),
                                                  landed("n3", 2.6)),
                                     wait=wait("settled", 6.1, 4), counts=probed_counts(8, 0, False),
                                     loss=loss_of(flow_of("n1-loop", "measured", 300, 274, 54.8)), took_s=70.6),
                   ], destroyed()),
                   "ok")


def examples() -> list[Example]:
    return [passed_run(), failed_run(), new_finding_run(), cut_run(), not_built_run(), unverified_run(),
            unclean_run(), alone_run(), refused_run(), held_run(), lost_run(), probed_run()]


def pairs() -> list[Pair]:
    """The plan's steps between the example's stages: the step into the baseline not
    computed; a link cabled between n1 and n3; bad-port's interface on n1; and the head
    unchanged."""
    cabled = {"id": "l3", "a": {"node": "n1", "port": "e1-3"}, "b": {"node": "n3", "port": "e1-3"}}
    link = StepDiff(links_added=[cabled],
                    nodes_changed=[{"node": "n1", "reasons": ["bootstrap", "mapping"]},
                                   {"node": "n3", "reasons": ["bootstrap", "mapping"]}],
                    artifacts_changed=[{"node": "n1", "name": "device-config", "from": MARKER, "to": MARKER},
                                       {"node": "n3", "name": "device-config", "from": MARKER, "to": MARKER}])
    port = StepDiff(nodes_changed=[{"node": "n1", "reasons": ["mapping"]}],
                    artifacts_changed=[{"node": "n1", "name": "device-config", "from": MARKER, "to": MARKER}])
    return [
        Pair.not_computed(CHANGE + "/branch-point", CHANGE + "/seeded", "", SEEDED_ID,
                          CHANGE + "/branch-point was refused"),
        Pair.between(CHANGE + "/seeded", CHANGE + "/third-link", SEEDED_ID, THIRD_ID, link),
        Pair.between(CHANGE + "/third-link", CHANGE + "/bad-port", THIRD_ID, BAD_ID, port),
        Pair.between(CHANGE + "/third-link", CHANGE + "/head", THIRD_ID, HEAD_ID, StepDiff(unchanged=True)),
        Pair.between(CHANGE + "/bad-port", CHANGE + "/head", BAD_ID, HEAD_ID, StepDiff(unchanged=True)),
    ]


CONTENT_MARKERS = ["FYLGJA-MARKER", "set / interface", "enter candidate private", "commit now", "NokiaSrl1!",
                   "admin:admin"]
"""Strings that would appear in a document only if a byte of artifact content or a
credential had reached it."""


def carries_no_content(label: str, s: str) -> None:
    for m in CONTENT_MARKERS:
        assert m not in s, f"{label} carries {m!r}, which can only have come from content or a credential"


def clone(e: Example) -> Example:
    return copy.deepcopy(e)
