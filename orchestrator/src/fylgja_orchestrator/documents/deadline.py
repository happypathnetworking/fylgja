"""A rehearsal's deadline (`internal/rehearsal/deadline.go`): the time a rehearsal of stages
is bounded by, each compiled stage's budgets summed and the destroy once, held to Fylgja's
ceiling of an hour before any run, `rehearsal.deadline.unfit` above it (research R-10).

The budgets are the core's node plans' as the host check plans them (`lab.NodePlans`), read
without the host: a compiled bundle's `manifest.json` names each node's package, a device's
support package by its platform id and a probe's host its probe package by its format, and
each budget is that package's (`image.deploy_timeout_s`, `image.destroy_timeout_s`,
`readiness.timeout_s`, a device's `config.push_timeout_s`, a host's `flow.start_timeout_s`
and `flow.read_timeout_s`). The manifest carries no budget of its own, so the packages are
read here from the files the core compiles with: the shipped `psp/` and `probes/`, then
`FYLGJA_PSP_DIR`'s support packages, which shadow a shipped one of the same id, as the
core's `--psp-dir` does (research §5.16). A node whose package is not found is left out, as
the host check leaves it out of its plan before refusing it.

The mechanism's constants are the core's, each bounding an activity its create and step
children run (`provision.DeadlineMechanism`); a unit test holds them to the Go source.
"""

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

from .findings import REJECTION, Findings

CEILING_S = 3600
"""The longest deadline a rehearsal may have, in seconds: a mechanism constant of Fylgja's,
the operator's patience as the wait's budget is, never a platform's (research R-09)."""

RULE_DEADLINE_UNFIT = "rehearsal.deadline.unfit"
STEP_START = "start"

MANIFEST = "manifest.json"
"""The bundle's file that names each node and its package (`compiler.ManifestFile`)."""

# The roles a stage takes in a rehearsal (rehearsal.schema.json, $defs/stage).
ROLE_REFUSED = "refused"
"""A stage the plan refused: the branch point refused scope.empty, passed over, or a stage
whose refusal refused the rehearsal."""
ROLE_BASELINE = "baseline"
"""The first compiled stage, created and verified."""
ROLE_REHEARSED = "rehearsed"
"""A compiled stage after the baseline, stepped to and verified."""
ROLE_NOT_REACHED = "not_reached"
"""A stage the run did not come to: after one that was not passed, or in a rehearsal
refused before any run."""


@dataclass(frozen=True)
class Mechanism:
    """The mechanism constants that bound each activity a rehearsal's children run, in
    seconds, none a platform's (Constitution II)."""

    check_host: int
    """Bounds the host check: once in a create, twice in a step."""
    stage: int
    """Bounds staging a bundle into the twin directory."""
    record: int
    """Bounds writing the twin's record."""
    plan_teardown: int
    unstage: int
    """These two bound the destroy's two steps around the lab's removal."""
    inspect_twin: int
    """Bounds a step's read of the twin it starts from."""
    readiness_margin: int
    push_margin: int
    verify_margin: int
    """Added to the readiness budget, the push budget and the wait's budget."""
    flows_margin: int
    """Added to the flows' start budget and to their read budget (016)."""
    wait: int
    """A wait's budget: verify's default, which every stage of a rehearsal waits."""


MECHANISM = Mechanism(
    check_host=30, stage=60, record=30, plan_teardown=30, unstage=30, inspect_twin=30,
    readiness_margin=15, push_margin=15, verify_margin=30, flows_margin=15, wait=120,
)
"""The core's: `internal/provision/options.go`'s budgets and margins and
`internal/verify/wait.go`'s `DefaultBudget`."""


@dataclass(frozen=True)
class NodePlan:
    """One node's budgets in seconds, as its package gives them: the deploy, the readiness,
    the push (none for a probe's host) and the destroy, and for a probe's host its flow's
    start and read."""

    name: str
    deploy_timeout_s: int
    timeout_s: int
    push_timeout_s: int
    destroy_timeout_s: int
    host: bool = False
    start_timeout_s: int = 0
    read_timeout_s: int = 0


@dataclass(frozen=True)
class DeadlineStage:
    """One stage as the deadline sums it: the role the rehearsal gives it, and its nodes'
    plans."""

    role: str
    nodes: tuple[NodePlan, ...] = ()


def deadline(m: Mechanism, stages) -> int:
    """The time a rehearsal of stages is bounded by, in seconds: each stage's budgets
    summed, the largest of each over the stage's nodes, and the destroy once (data-model §4
    of 015):

        baseline  = CheckHost + Stage + deploy + (readiness + ReadinessMargin) + (push + PushMargin) + Record
                    + (Wait + VerifyMargin)
        rehearsed = InspectTwin + 2 CheckHost + Stage + deploy + … + (Wait + VerifyMargin)
                    + (start + FlowsMargin) + (read + FlowsMargin), when the stage has a probe's host
        destroy   = PlanTeardown + destroy + Unstage

    A stage of another role is not run and adds nothing; the destroy's budget is the largest
    over every stage counted, since the run may stop at any of them."""
    total = 0
    destroy = 0
    for s in stages:
        b = _budgets(s.nodes)
        build = (m.stage + b["deploy"] + b["readiness"] + m.readiness_margin + b["push"] + m.push_margin + m.record
                 + m.wait + m.verify_margin)
        if s.role == ROLE_BASELINE:
            total += m.check_host + build
        elif s.role == ROLE_REHEARSED:
            total += m.inspect_twin + 2 * m.check_host + build
            if b["flows"]:
                total += b["start"] + m.flows_margin + b["read"] + m.flows_margin
        else:
            continue
        destroy = max(destroy, b["destroy"])
    return total + m.plan_teardown + destroy + m.unstage


def fits(deadline_s: int, ceiling_s: int = CEILING_S) -> bool:
    """Whether a deadline is within the ceiling."""
    return deadline_s <= ceiling_s


def _budgets(nodes) -> dict:
    b = {"deploy": 0, "readiness": 0, "push": 0, "destroy": 0, "flows": False, "start": 0, "read": 0}
    for n in nodes:
        b["deploy"] = max(b["deploy"], n.deploy_timeout_s)
        b["readiness"] = max(b["readiness"], n.timeout_s)
        b["push"] = max(b["push"], n.push_timeout_s)
        b["destroy"] = max(b["destroy"], n.destroy_timeout_s)
        if n.host:
            b["flows"] = True
            b["start"] = max(b["start"], n.start_timeout_s)
            b["read"] = max(b["read"], n.read_timeout_s)
    return b


def go_duration(seconds: int) -> str:
    """A whole number of seconds as Go's `time.Duration.String` writes it: `43m0s`,
    `1h4m0s`, `30s`, `0s`."""
    if seconds == 0:
        return "0s"
    sign = "-" if seconds < 0 else ""
    seconds = abs(seconds)
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    if h:
        return f"{sign}{h}h{m}m{s}s"
    if m:
        return f"{sign}{m}m{s}s"
    return f"{sign}{s}s"


def unfit(branch: str, deadline_s: int, ceiling_s: int = CEILING_S) -> Findings:
    """The refusal of a rehearsal whose stages need more than the ceiling, before any run,
    at start, about the branch, as the server worded it."""
    found = Findings()
    found.add_step(
        REJECTION, STEP_START, RULE_DEADLINE_UNFIT, branch,
        f"the stages need {go_duration(deadline_s)} ({deadline_s}s) to be rehearsed, over the ceiling of "
        f"{go_duration(ceiling_s)} ({ceiling_s}s): no rehearsal is started whose budgets cannot end within it; "
        "rehearse fewer stages",
    )
    return found


# The packages' budgets.

REPOSITORY = Path(__file__).resolve().parents[4]
"""The repository the orchestrator is installed from, whose `psp/` and `probes/` the core
embeds."""

ENV_PSP_SHIPPED = "FYLGJA_PSP_SHIPPED"
ENV_PSP_OVERRIDE = "FYLGJA_PSP_DIR"


@dataclass(frozen=True)
class Budgets:
    """Every package's budgets: the support packages' by platform id, the probe packages'
    by format, each a NodePlan with no name."""

    psp: Mapping[str, NodePlan]
    probes: Mapping[str, NodePlan]


def _read_yaml(path: Path) -> dict:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    return doc if isinstance(doc, dict) else {}


def _int(section, key: str) -> int:
    value = section.get(key) if isinstance(section, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def psp_budgets(doc: dict) -> tuple[str, NodePlan]:
    """A support package's platform id and budgets."""
    image, readiness, config = doc.get("image") or {}, doc.get("readiness") or {}, doc.get("config") or {}
    platform = doc.get("platform") or {}
    return str(platform.get("id") or ""), NodePlan(
        name="", deploy_timeout_s=_int(image, "deploy_timeout_s"), timeout_s=_int(readiness, "timeout_s"),
        push_timeout_s=_int(config, "push_timeout_s"), destroy_timeout_s=_int(image, "destroy_timeout_s"),
    )


def probe_budgets(doc: dict) -> tuple[str, NodePlan]:
    """A probe package's format and budgets."""
    image, readiness, flow = doc.get("image") or {}, doc.get("readiness") or {}, doc.get("flow") or {}
    return str(doc.get("format") or ""), NodePlan(
        name="", deploy_timeout_s=_int(image, "deploy_timeout_s"), timeout_s=_int(readiness, "timeout_s"),
        push_timeout_s=0, destroy_timeout_s=_int(image, "destroy_timeout_s"), host=True,
        start_timeout_s=_int(flow, "start_timeout_s"), read_timeout_s=_int(flow, "read_timeout_s"),
    )


def load_budgets(psp_dirs=None, probe_dirs=None) -> Budgets:
    """The packages' budgets from each directory's `*.yaml` in order, a later package
    shadowing an earlier one of the same id: by default the shipped `psp/`
    (`FYLGJA_PSP_SHIPPED` when set) then `FYLGJA_PSP_DIR` when set, and the shipped
    `probes/`."""
    if psp_dirs is None:
        shipped = os.environ.get(ENV_PSP_SHIPPED, "")
        psp_dirs = [Path(shipped) if shipped else REPOSITORY / "psp"]
        if os.environ.get(ENV_PSP_OVERRIDE):
            psp_dirs.append(Path(os.environ[ENV_PSP_OVERRIDE]))
    if probe_dirs is None:
        probe_dirs = [REPOSITORY / "probes"]
    psp: dict[str, NodePlan] = {}
    for d in psp_dirs:
        for path in sorted(Path(d).glob("*.yaml")):
            pid, plan = psp_budgets(_read_yaml(path))
            if pid:
                psp[pid] = plan
    probes: dict[str, NodePlan] = {}
    for d in probe_dirs:
        for path in sorted(Path(d).glob("*.yaml")):
            fmt, plan = probe_budgets(_read_yaml(path))
            if fmt:
                probes[fmt] = plan
    return Budgets(psp, probes)


def node_plans(files: Mapping[str, bytes], budgets: Budgets) -> tuple[NodePlan, ...]:
    """Each node of a compiled bundle, given as its files (`twin.compile`'s), planned with
    its package's budgets, in the manifest's order: a probe's host by its probe package, a
    device by its support package. A node whose package is not held is left out. A bundle
    with no manifest, or a manifest that is not JSON, is a ValueError naming the file."""
    raw = files.get(MANIFEST)
    if raw is None:
        raise ValueError(f"the bundle has no {MANIFEST}")
    try:
        manifest = json.loads(raw)
    except ValueError as e:
        raise ValueError(f"{MANIFEST}: {e}") from None
    out = []
    for n in manifest.get("nodes") or []:
        probe, psp = n.get("probe"), n.get("psp")
        if probe:
            plan = budgets.probes.get((probe.get("package") or {}).get("id", ""))
        elif psp:
            plan = budgets.psp.get(psp.get("id", ""))
        else:
            raise ValueError(f"the manifest's node {n.get('name')} names neither a support package nor a probe")
        if plan is not None:
            out.append(NodePlan(n["name"], plan.deploy_timeout_s, plan.timeout_s, plan.push_timeout_s,
                                plan.destroy_timeout_s, plan.host, plan.start_timeout_s, plan.read_timeout_s))
    return tuple(out)
