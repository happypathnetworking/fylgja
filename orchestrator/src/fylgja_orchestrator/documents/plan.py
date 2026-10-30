"""A proposed change's plan (`internal/stages/plan.go`), the `plan` block of `stage.plan`'s
document (`contracts/stages.schema.json`, `$defs/plan`) and its text, as `fylgja stage plan`
printed them (`internal/server/stages.go`'s `runStagePlan` and `printPlanned`, and
`internal/step/render.go`'s `Pair`).

Each stage is planned as far as it goes, resolved, read, its snapshot filed, compiled and
its bundle filed, by the flow that drives the adapter and the core; this module holds what
the flow fills (`PlanStage`), the step between two consecutive stages (`Pair`), built from
the core's `twin.diff` answer between their snapshots, whose names it gives the two stages'
references, and the block and the text rendered from them. The `twin.diff` step carries an
artifact that came or went with its node under the node alone (the contract's
`artifacts.changed` is nodes on both sides); the text and the rehearsal's drawing name it,
so `artifacts_moved` reads it from the two bundles' manifests, as `step.Diff` did.
"""

import json
from dataclasses import dataclass, field

from .findings import REJECTION, RULE_OPERATION_FAILED, Finding, Findings, new_document
from .stages import heading, resolution

OP_STAGE_PLAN = "stage.plan"

# How far one planned stage got.
PLAN_COMPILED = "compiled"
"""Resolved, read, compiled and filed."""
PLAN_REFUSED = "refused"
"""Refused at resolution, read, compile or filing, under a rule of its own."""
PLAN_FAILED = "failed"
"""Its resolution, read, compile or filing could not run (operation.failed)."""


def short(s: str) -> str:
    """The first eight characters of an id or a checksum and an ellipsis, as the text prints
    them; a side with no bundle is a dash."""
    if s == "":
        return "—"
    return s[:8] + "…" if len(s) > 8 else s


@dataclass
class StepDiff:
    """The step between two bundles (`step.Step`): the nodes added, removed and changed with
    their reasons, the links added and removed, and the artifacts changed, added and removed,
    by name and checksum alone. A link is `{"id", "a": {"node", "port"}, "b": {…}}`, an
    artifact changed `{"node", "name", "from", "to"}`, one added or removed `{"node",
    "name"}`."""

    unchanged: bool = False
    nodes_added: list = field(default_factory=list)
    nodes_removed: list = field(default_factory=list)
    nodes_changed: list = field(default_factory=list)
    links_added: list = field(default_factory=list)
    links_removed: list = field(default_factory=list)
    artifacts_changed: list = field(default_factory=list)
    artifacts_added: list = field(default_factory=list)
    artifacts_removed: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict, added=(), removed=()) -> "StepDiff":
        """The step of a computed pair as the contract carries it, the artifacts that came
        and went with their nodes given apart, since the contract leaves them to the node."""
        nodes, links = d.get("nodes") or {}, d.get("links") or {}
        return cls(
            unchanged=bool(d.get("unchanged")),
            nodes_added=list(nodes.get("added") or []),
            nodes_removed=list(nodes.get("removed") or []),
            nodes_changed=[{"node": c["node"], "reasons": list(c["reasons"])} for c in nodes.get("changed") or []],
            links_added=list(links.get("added") or []),
            links_removed=list(links.get("removed") or []),
            artifacts_changed=list((d.get("artifacts") or {}).get("changed") or []),
            artifacts_added=list(added),
            artifacts_removed=list(removed),
        )


@dataclass
class Pair:
    """One step as `stage plan` reports it (`step.Pair`): the two stages it joins, each
    side's bundle id ("" for a side that did not compile), and either the step between their
    bundles or why none was computed. The text and the JSON are both rendered from it."""

    from_: str
    to: str
    from_id: str = ""
    to_id: str = ""
    step: StepDiff | None = None
    why: str = ""

    @classmethod
    def between(cls, from_: str, to: str, from_id: str, to_id: str, step: StepDiff) -> "Pair":
        return cls(from_, to, from_id, to_id, step)

    @classmethod
    def not_computed(cls, from_: str, to: str, from_id: str, to_id: str, why: str) -> "Pair":
        return cls(from_, to, from_id, to_id, None, why)

    @classmethod
    def from_dict(cls, d: dict, added=(), removed=()) -> "Pair":
        """A pair as the contract carries it (`$defs/step`): a plan's step, or `twin.diff`'s
        and `twin.step`'s dry run's."""
        step = StepDiff.from_dict(d, added, removed) if d.get("computed") else None
        return cls(d["from"], d["to"], d.get("from_bundle_id") or "", d.get("to_bundle_id") or "", step,
                   d.get("not_computed", ""))

    def to_dict(self) -> dict:
        """The pair as `stages.schema.json`'s step (`Pair.MarshalJSON`): the checksums whole,
        every list present, an added or removed node's artifact left to the node."""
        out = {"from": self.from_, "to": self.to, "from_bundle_id": self.from_id or None,
               "to_bundle_id": self.to_id or None, "computed": self.step is not None}
        s = self.step
        if s is None:
            if self.why:
                out["not_computed"] = self.why
            return out
        out["unchanged"] = s.unchanged
        out["nodes"] = {"added": list(s.nodes_added), "removed": list(s.nodes_removed),
                        "changed": [{"node": c["node"], "reasons": list(c["reasons"])} for c in s.nodes_changed]}
        out["links"] = {"added": [_link_dict(link) for link in s.links_added],
                        "removed": [_link_dict(link) for link in s.links_removed]}
        out["artifacts"] = {"changed": [{"node": a["node"], "name": a["name"], "from": a["from"], "to": a["to"]}
                                        for a in s.artifacts_changed]}
        return out

    def text(self) -> str:
        """The block `stage plan` prints for the pair, with no trailing newline
        (`Pair.Text`):

            step change-1/branch-point → change-1/seeded (— → 35aea06f…): not computed
              (change-1/branch-point was refused)
            step change-1/seeded → change-1/third-link (35aea06f… → 9c2d01e7…):
              nodes: +n4; ~n1 (bootstrap, mapping)
              links: +n1:e1-3 — n4:e1-1
              artifacts: n1 device-config 43e8fd0c… → 9a0177b2…; n4 device-config added
            step change-1/third-link → change-1/head (9c2d01e7… → 51f0aa93…): unchanged; the ids
              differ by provenance alone

        (each a line of its own, wrapped here).
        """
        head = f"step {self.from_} → {self.to} ({short(self.from_id)} → {short(self.to_id)}):"
        s = self.step
        if s is None:
            return f"{head} not computed ({self.why})"
        if s.unchanged and self.from_id == self.to_id:
            return f"{head} unchanged; the two are one bundle"
        if s.unchanged:
            return f"{head} unchanged; the ids differ by provenance alone"
        return "\n".join([
            head,
            "  nodes: " + _or_unchanged(_node_parts(s)),
            "  links: " + _or_unchanged(_link_parts(s)),
            "  artifacts: " + _or_unchanged(_artifact_parts(s)),
        ])


def _link_dict(link: dict) -> dict:
    return {"id": link["id"], "a": {"node": link["a"]["node"], "port": link["a"]["port"]},
            "b": {"node": link["b"]["node"], "port": link["b"]["port"]}}


def link_text(link: dict) -> str:
    return f"{link['a']['node']}:{link['a']['port']} — {link['b']['node']}:{link['b']['port']}"


def _node_parts(s: StepDiff) -> list[str]:
    out = ["+" + n for n in s.nodes_added]
    out += ["-" + n for n in s.nodes_removed]
    out += [f"~{c['node']} ({', '.join(c['reasons'])})" for c in s.nodes_changed]
    return out


def _link_parts(s: StepDiff) -> list[str]:
    return ["+" + link_text(link) for link in s.links_added] + ["-" + link_text(link) for link in s.links_removed]


def _artifact_parts(s: StepDiff) -> list[str]:
    """Every artifact that differs, sorted by node: a changed one with both checksums, one
    that came or went with its node as added or removed."""
    parts = [(a["node"], f"{a['node']} {a['name']} {short(a['from'])} → {short(a['to'])}") for a in s.artifacts_changed]
    parts += [(a["node"], f"{a['node']} {a['name']} added") for a in s.artifacts_added]
    parts += [(a["node"], f"{a['node']} {a['name']} removed") for a in s.artifacts_removed]
    parts.sort(key=lambda p: p[0])
    return [text for _, text in parts]


def _or_unchanged(parts: list[str]) -> str:
    return "; ".join(parts) if parts else "unchanged"


def _manifest_artifacts(manifest) -> dict:
    """Each node of a manifest (its bytes or its document) with its artifact's name, None for
    a node with none."""
    if isinstance(manifest, bytes | str):
        manifest = json.loads(manifest)
    return {n["name"]: (n.get("artifact") or {}).get("name") for n in manifest.get("nodes") or []}


def artifacts_moved(from_manifest, to_manifest) -> tuple[list, list]:
    """The artifacts that came and went between two bundles, from their manifests, as
    `step.Diff` lists them: an added node's artifact and one a node kept gained, then a
    removed node's and one a node kept lost, each `{"node", "name"}`, sorted by node."""
    was, now = _manifest_artifacts(from_manifest), _manifest_artifacts(to_manifest)
    added = [{"node": n, "name": now[n]} for n in sorted(now) if now[n] and (n not in was or not was[n])]
    removed = [{"node": n, "name": was[n]} for n in sorted(was) if was[n] and (n not in now or not now[n])]
    return added, removed


@dataclass
class PlanStage:
    """One stage of a plan, as far as it got (`stages.PlanStage`): its reference, label,
    description and at's source in every case; the branch and the at once it resolved; what
    its read holds once the read returned intent (`read`, the document's counts, and
    `packages`, the devices by package as `(id, count)` in the packages' order); its snapshot
    once filed; its bundle once compiled and filed; when its read began; its findings, each
    at its step; and how far it got, with the first rejection's rule when it did not
    compile."""

    ref: str
    label: str
    description: str = ""
    at_source: str = ""
    branch: str = ""
    at: str = ""
    read: dict | None = None
    packages: list = field(default_factory=list)
    snapshot_id: str = ""
    bundle_id: str = ""
    observed_at: str = ""
    findings: Findings = field(default_factory=Findings)
    status: str = ""
    rule: str = ""

    def __post_init__(self):
        self.findings = Findings(self.findings)

    @property
    def resolved(self) -> bool:
        return bool(self.at)

    def stop(self, found) -> "PlanStage":
        """Ends the stage with found (`build`'s `stop`): refused, under the first
        rejection's rule, or failed when that rule is operation.failed."""
        self.findings.extend(found)
        self.status = PLAN_REFUSED
        for f in self.findings:
            if f.severity == REJECTION:
                self.rule = f.rule
                if f.rule == RULE_OPERATION_FAILED:
                    self.status = PLAN_FAILED
                break
        return self

    def block(self) -> dict:
        """The stage as the plan block carries it (`$defs/plan_stage`)."""
        out = {"ref": self.ref, "label": self.label, "description": self.description, "at_source": self.at_source}
        if self.branch:
            out["branch"] = self.branch
        if self.at:
            out["at"] = self.at
        out["snapshot_id"] = self.snapshot_id or None
        out["bundle_id"] = self.bundle_id or None
        out["read"] = dict(self.read) if self.read is not None else None
        out["findings"] = [f.to_dict() for f in self.findings]
        return out

    @classmethod
    def from_block(cls, b: dict, packages=()) -> "PlanStage":
        """A stage as the plan block carries it, its packages given apart, since the block
        counts devices alone; its status and rule read from its ids and findings."""
        st = cls(ref=b["ref"], label=b["label"], description=b.get("description", ""), at_source=b["at_source"],
                 branch=b.get("branch", ""), at=b.get("at", ""), read=b.get("read"), packages=list(packages),
                 snapshot_id=b.get("snapshot_id") or "", bundle_id=b.get("bundle_id") or "")
        found = Findings(Finding.from_dict(f) for f in b.get("findings") or [])
        if st.bundle_id:
            st.findings, st.status = found, PLAN_COMPILED
        else:
            st.stop(found)
        return st

    def lines(self) -> list[str]:
        """The stage as `stage plan` prints it (`printPlanned`): its resolution, snapshot_id,
        bundle_id and what its read holds when it compiled, and otherwise one line naming how
        far it got and the first rejection's rule; then its findings under it, indented."""
        if self.status != PLAN_COMPILED:
            why = f"{self.status} ({self.rule})" if self.rule else self.status
            out = [f"{self.ref}: {why}"]
        else:
            out = [
                f"{self.ref}: " + resolution({"branch": self.branch, "at": self.at, "at_source": self.at_source,
                                              "description": self.description}),
                f"  snapshot_id {self.snapshot_id}",
                f"  bundle_id {self.bundle_id}",
                f"  read: {read_counts(self.read or {}, self.packages)}",
            ]
        return out + ["  " + line for line in self.findings.text_lines()]


def read_counts(read: dict, packages) -> str:
    """What a read holds, as `intent read` and `stage plan` print it (`readCounts`): `3
    devices (nokia_srlinux 3), 15 interfaces, 3 links, 3 artifacts, 0 lossy mappings, 0
    shared ports`."""
    devices = f"{read.get('devices', 0)} devices"
    if packages:
        devices += " (" + ", ".join(f"{pid} {n}" for pid, n in packages) + ")"
    return (f"{devices}, {read.get('interfaces', 0)} interfaces, {read.get('links', 0)} links, "
            f"{read.get('artifacts', 0)} artifacts, {read.get('lossy_mappings', 0)} lossy mappings, "
            f"{read.get('shared_ports', 0)} shared ports")


def pair_of(a: PlanStage, b: PlanStage, step: StepDiff | None = None) -> Pair:
    """The step between two consecutive stages (`pairOf`): the step the core's `twin.diff`
    computed between their snapshots when both compiled, or why none was computed, naming
    the side or sides refused."""
    if a.bundle_id and b.bundle_id:
        if step is None:
            raise ValueError(f"the step {a.ref} → {b.ref}: both sides compiled and no step was given")
        return Pair.between(a.ref, b.ref, a.bundle_id, b.bundle_id, step)
    refused = [s.ref for s in (a, b) if not s.bundle_id]
    why = refused[0] + " was refused" if len(refused) == 1 else " and ".join(refused) + " were refused"
    return Pair.not_computed(a.ref, b.ref, a.bundle_id, b.bundle_id, why)


def step_of_diff(document: dict, from_manifest=None, to_manifest=None) -> StepDiff | None:
    """The step of the core's `twin.diff` answer, its `step` block as a StepDiff, the
    artifacts that came and went read from the two manifests when given; None when the
    answer carries no computed step."""
    block = document.get("step")
    if not block or not block.get("computed"):
        return None
    added, removed = ([], []) if from_manifest is None or to_manifest is None else \
        artifacts_moved(from_manifest, to_manifest)
    return StepDiff.from_dict(block, added, removed)


@dataclass
class PlanResult:
    """What `stage plan` reports (`stages.PlanResult`): the branch asked for, the proposed
    change planned (`{"id", "name", "branch", "draft"}`, None when the plan was refused
    before it was found) and its destination, the stages in order, the steps between them
    and the document's findings: a refusal of the whole plan, or every stage's in order."""

    branch: str
    proposed_change: dict | None = None
    destination: str = ""
    stages: list = field(default_factory=list)
    steps: list = field(default_factory=list)
    findings: Findings = field(default_factory=Findings)

    def __post_init__(self):
        self.findings = Findings(self.findings)

    def add(self, stage: PlanStage, step: StepDiff | None = None) -> Pair | None:
        """Appends a planned stage, and the step from the stage before it, which is returned
        (`Plan`'s loop): none for the first."""
        pair = None
        if self.stages:
            pair = pair_of(self.stages[-1], stage, step)
            self.steps.append(pair)
        self.stages.append(stage)
        self.findings.extend(stage.findings)
        return pair

    def block(self) -> dict | None:
        """The plan as `stage plan`'s document carries it (`$defs/plan`), or None for a plan
        refused before its proposed change was found, which has no stages."""
        if self.proposed_change is None or not self.stages:
            return None
        pc = self.proposed_change
        return {"branch": self.branch,
                "proposed_change": {"id": pc["id"], "name": pc["name"], "branch": pc["branch"],
                                    "draft": bool(pc.get("draft"))},
                "stages": [s.block() for s in self.stages], "steps": [p.to_dict() for p in self.steps]}

    def document(self, scope: str):
        """The findings document `stage plan` ends with: its status the findings', its subject
        the scope, its block the plan's."""
        doc = new_document(OP_STAGE_PLAN, {"scope": scope}, self.findings)
        doc.set("plan", self.block())
        return doc

    def lines(self, scope: str) -> list[str]:
        """The plan's text on stdout, as each part is known: the heading once the proposed
        change is found, then each stage, the step into it printed before it."""
        if self.proposed_change is None:
            return []
        out = [heading(self.proposed_change, len(self.stages), self.destination, scope)]
        for i, stage in enumerate(self.stages):
            if i > 0:
                out.append(self.steps[i - 1].text())
            out.extend(stage.lines())
        return out

    def text(self, scope: str) -> str:
        """The plan's text as stdout carries it, each line ended."""
        return "".join(line + "\n" for line in self.lines(scope))
