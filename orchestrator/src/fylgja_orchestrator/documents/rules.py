"""Every rule the adapter and the orchestrator file (data-model §11), as data: the identifier,
the severity, the exit the finding gives its document, the steps it is filed at and when it
fires, worded as `internal/findings/finding.go` words it. Identifiers are stable API: tests
and reports name them, so a rule is added here before any module files it, and none is
renamed.

`core` says whether the core keeps the identifier once the Go reader goes (T035): the
adapter files the core's own rules for what the core would have refused alike (the CTM's
intrinsic rules, the read's artifact and platform rules, a probe declaration's, a
snapshot's), and the orchestrator owns the rest, the core's retired rules with their wording
and the four of its own (`record.twin.stale`, `step.target.required`,
`rehearsal.report.unposted`, `platform.unreachable`). The four `api.*` rules are the
core's client's, which the orchestrator's client of the core (`core.py`) files in the
core's words.
"""

from dataclasses import dataclass

from .findings import INFO, REJECTION, WARNING


@dataclass(frozen=True)
class Rule:
    id: str
    severity: str
    exit: int
    steps: tuple[str, ...]
    wording: str
    core: bool


def _r(id, severity, exit, steps, wording, core=False) -> Rule:
    return Rule(id, severity, exit, tuple(steps.split()) if steps else (), wording, core)


RULES: tuple[Rule, ...] = (
    # The operation could not run.
    _r("operation.failed", REJECTION, 2, "", "the operation did not run: Infrahub unreachable, the credential "
       "refused, a file that could not be read or written; the object is the operation, or the step's", core=True),

    # The scope (017).
    _r("scope.invalid", REJECTION, 2, "start", "the value given; --scope is not tag:<name>, an empty value included; "
       "before any connection, after --branch's and --stage's guards"),
    _r("scope.unset", REJECTION, 2, "start", "FYLGJA_DEFAULT_SCOPE; no --scope and no default; before any connection"),
    _r("scope.empty", REJECTION, 1, "read resolve", "the scope; the device query answered 0 on the branch at the at, "
       "or the head's stamps selected no device and no intent event names its at"),

    # Conformance (017), at read; none on schema.check.
    _r("schema.kind.missing", REJECTION, 1, "read resolve", "the kind; the branch's schema lacks a kind the mapping "
       "reads"),
    _r("schema.field.missing", REJECTION, 1, "read resolve", "<kind>.<field>; the kind lacks a field the "
       "mapping reads"),
    _r("schema.field.mismatch", REJECTION, 1, "read resolve", "<kind>.<field>; the field's kind, cardinality, peer or "
       "optionality is not the table's, naming both"),
    _r("schema.choice.missing", REJECTION, 1, "read resolve", "<kind>.<field>; the dropdown lacks management (role) "
       "or disabled (status)"),
    _r("schema.used_by.missing", REJECTION, 1, "read resolve", "the generic; the generic is not implemented by the "
       "kind the mapping expects"),

    # The read (M1, M5, 017), and the CTM's intrinsic rules the read holds it to.
    _r("intent.at.precision", REJECTION, 2, "resolve", "the at; --at, or a stage's as_of, carries more fractional "
       "digits than Infrahub honours, refused before any query; status error"),
    _r("platform.missing", REJECTION, 1, "read", "the device; no platform, or a platform with no manufacturer, naming "
       "what the device carries", core=True),
    _r("platform.unmatched", REJECTION, 1, "read", "the device; no package matches the pair exactly, naming the pair "
       "and every package's pairs", core=True),
    _r("omit.cable.ends", INFO, 0, "read", "the cable; it has other than two ends", core=True),
    _r("omit.cable.endpoint", INFO, 0, "read", "the cable; an end is not on a physical port", core=True),
    _r("omit.cable.outside_scope", INFO, 0, "read", "the cable; an end is outside the scope", core=True),
    _r("omit.cable.kind", INFO, 0, "read", "the connector; it is not a DcimCable, naming its kind", core=True),
    _r("artifact.missing", REJECTION, 1, "read", "the device; no artifact of the package's name on it, at the at when "
       "pinned", core=True),
    _r("artifact.ambiguous", REJECTION, 1, "read", "the device; more than one artifact of that name, naming the count "
       "and each checksum", core=True),
    _r("artifact.not_ready", REJECTION, 1, "read", "the device; its status is not Ready, or there is no storage object "
       "yet, naming the state and that Fylgja never regenerates", core=True),
    _r("artifact.content_type.unsupported", REJECTION, 1, "read", "the device; the content type is not one the package "
       "accepts, or the bytes are not text", core=True),
    _r("artifact.content.unavailable", REJECTION, 1, "read", "the device; the storage object of the listed id is not "
       "served, naming the at when pinned", core=True),
    _r("artifact.checksum.mismatch", REJECTION, 1, "read", "the device; the MD5 of the bytes is not Infrahub's "
       "checksum, naming both", core=True),
    _r("data.required.missing", REJECTION, 1, "read", "the field; a field the CTM requires is empty", core=True),
    _r("device.name.duplicate", REJECTION, 1, "read", "the device; two devices share the name", core=True),
    _r("link.endpoints.count", REJECTION, 1, "read", "the link; it has other than two endpoints", core=True),
    _r("link.endpoints.same_device", REJECTION, 1, "read", "the link; both endpoints are on one device", core=True),
    _r("ctm.devices.empty", REJECTION, 1, "read", "the branch; the CTM has no devices, almost always a wrong at",
       core=True),
    _r("psp.identity.duplicate", REJECTION, 1, "verify", "the package path; two packages name one id", core=True),
    _r("psp.matches.duplicate", REJECTION, 1, "verify", "the package path; two packages name one pair, naming both "
       "packages and the pair", core=True),

    # The probes (016): the declaration's rules, at start for a --probes file, at resolve for
    # the kind's.
    _r("probe.kind.absent", REJECTION, 1, "resolve", "FylgjaProbe; the default branch's schema lacks the kind or an "
       "attribute this build reads, naming schema/fylgja-probe.yaml; only when the kind's read is asked for"),
    _r("probes.version.unsupported", REJECTION, 1, "start resolve", "the file; probes_version is not \"1\", or absent, "
       "naming the version read, or that none was, and \"1\""),
    _r("probes.invalid", REJECTION, 1, "start resolve", "the file or probes[<i>].<field>; the document is not an "
       "object, holds an unknown key, lacks a field, or a probe has other than two endpoints"),
    _r("probe.name.invalid", REJECTION, 1, "start resolve", "the probe; its name is not ^[a-z0-9][a-z0-9-]{0,23}$, "
       "naming the name read", core=True),
    _r("probe.name.duplicate", REJECTION, 1, "start resolve", "the probe; two or more probes share the name, naming "
       "each position", core=True),
    _r("probe.address.invalid", REJECTION, 1, "start resolve", "<probe>/<a|b>.address; not an address with a prefix "
       "length", core=True),
    _r("probe.gateway.invalid", REJECTION, 1, "start resolve", "<probe>/<a|b>.gateway; not an address, or one carrying "
       "a prefix length", core=True),
    _r("probe.gateway.outside", REJECTION, 1, "start resolve", "<probe>/<a|b>.gateway; the gateway is not within the "
       "address's prefix", core=True),
    _r("probe.family.mixed", REJECTION, 1, "start resolve", "the probe; its four addresses are not of one family, "
       "naming each family read", core=True),
    _r("probe.address.duplicate", REJECTION, 1, "start resolve", "<probe>/<a|b>.address; two endpoints of the list "
       "share one host address, naming both probes", core=True),
    _r("probe.format.unknown", REJECTION, 1, "start resolve compile", "<probe>; no loaded probe package declares the "
       "format, naming the formats loaded", core=True),

    # The snapshot (018), as the core files a snapshot it is sent.
    _r("snapshot.invalid", REJECTION, 1, "resolve", "the field, or the file; the outer shape is not version 2's",
       core=True),
    _r("snapshot.version.unsupported", REJECTION, 1, "resolve", "the file; snapshot_version is neither \"1\" nor "
       "\"2\", or absent", core=True),
    _r("snapshot.id.mismatch", REJECTION, 1, "resolve compile", "the file, or the store path; a declared snapshot_id "
       "is not what the body hashes to, naming both", core=True),
    _r("snapshot.flags.conflict", REJECTION, 2, "start", "the flag; --snapshot beside --branch, --stage, --at or "
       "--scope, the first found in that order, before any connection, or --probes beside --snapshot"),

    # The stages (014; D-045 to D-048).
    _r("stage.ref.invalid", REJECTION, 2, "start", "the text given; --stage is not <branch>/<label>, or stage "
       "list's or stage plan's --branch is not a branch"),
    _r("stage.flags.conflict", REJECTION, 2, "start", "the conflicting flag; --stage beside --branch or --at, the "
       "first found in that order"),
    _r("stage.kind.absent", REJECTION, 1, "resolve", "FylgjaStage; the default branch's schema lacks the kind, an "
       "attribute or the relationship this build reads, or CoreProposedChange lacks the extension, naming "
       "schema/fylgja-stage.yaml"),
    _r("stage.unknown", REJECTION, 1, "resolve", "the branch or <branch>/<label>; no open proposed change has the "
       "source branch, the branch is gone (in stage list a warning), or the proposed change has no stage of the label"),
    _r("stage.duplicate", REJECTION, 1, "resolve", "<branch>/<label>; two or more marks of one proposed change share "
       "the label, naming every id and choosing none"),
    _r("stage.at.unresolved", REJECTION, 1, "resolve", "<branch>/<label>; a given as_of later than the clock, or a "
       "stage with no stamp at all to name its at (in stage list a warning, the row listed with no at)"),
    _r("stage.at.before_branch_point", REJECTION, 1, "resolve", "<branch>/<label>; the stage's at is before the "
       "branch's branched_from, saying a rebase did it when the branch was created before the at"),
    _r("stage.label.reserved", REJECTION, 1, "resolve", "<branch>/<label>; a mark is labelled head or branch-point, "
       "which name the derived stages"),
    _r("stage.artifact.stale", REJECTION, 1, "resolve", "the device; at the stage's at, the device's intent is newer "
       "than its generation stamp (D-046, D-048), naming both remedies"),
    _r("stage.orphaned", WARNING, 0, "", "the stage's id; a stage its proposed change no longer names, removed "
       "from its fylgja_stages (D-047)"),
    _r("stage.main.moved", WARNING, 0, "resolve", "the branch; main's latest stamp is later than the branch's "
       "branched_from, and nothing is refused"),
    _r("stage.twin.moved", WARNING, 0, "", "the record's <branch>/<label>; the record's stage no longer resolves to "
       "the record's (branch, at), or is gone"),

    # The step's target (M11, 014, 019).
    _r("step.target.unknown", REJECTION, 1, "resolve", "the record's stage or the reference; the record's label is "
       "gone, no stage follows it, or the proposed change has not the one given; the core keeps it for twin step's "
       "--snapshot", core=True),
    _r("step.target.current", REJECTION, 1, "resolve", "the reference; the target resolves to the record's own "
       "(branch, at)"),
    _r("step.stage.skipped", WARNING, 0, "resolve", "the target; the proposed change has marks strictly between the "
       "record's stage and the target, either direction"),

    # The rehearsal (015; D-051).
    _r("rehearsal.deadline.unfit", REJECTION, 1, "start", "the branch; the stages' budgets summed exceed the ceiling, "
       "naming the time the stages need and the ceiling"),
    _r("rehearsal.twin.reclaimed", WARNING, 0, "destroy", "the dead rehearsal's run id; the twin of a rehearsal whose "
       "run was no longer running was destroyed before the start, naming what was removed"),
    _r("rehearsal.steps.none", WARNING, 0, "resolve", "the one compiled stage's <branch>/<label>; it was built, "
       "verified and destroyed, and no step was rehearsed"),
    _r("rehearsal.stage.failed", REJECTION, 5, "observe", "the stage's <branch>/<label>; the step diverged, naming the "
       "phase and the nodes landed and not, or its wait holds a finding the baseline's did not; status nonconforming"),
    _r("rehearsal.stage.error", REJECTION, 2, "", "the stage's <branch>/<label>; its step could not run, was rejected "
       "by its locks or cancelled before its stage, or its wait could not complete; at the step reached"),
    _r("rehearsal.baseline.failed", REJECTION, 3, "provision", "the baseline's <branch>/<label>; the baseline could "
       "not be built; status failed"),
    _r("rehearsal.deadline.cut", REJECTION, 2, "", "the <branch>/<label> of the stage in progress; the deadline "
       "passed, naming each finished stage's time and the deadline; at the step reached"),
    _r("rehearsal.stage.moved", WARNING, 0, "resolve", "the stage's <branch>/<label>; after the run, a rehearsed stage "
       "no longer resolves to the (branch, at) it was rehearsed at, or is gone"),
    _r("rehearsal.change.closed", WARNING, 0, "resolve", "the branch; after the run, the proposed change is no longer "
       "open"),

    # The orchestrator's own (020; research R-09, R-11, R-19).
    _r("record.twin.stale", INFO, 0, "", "the record; the orchestrator's twin.json names a snapshot twin show's record "
       "does not, so it is not trusted: stage list marks no twin row"),
    _r("step.target.required", REJECTION, 1, "start", "--stage; twin step without --stage while the record is not "
       "trusted, so there is no stage to take the next of"),
    _r("rehearsal.report.unposted", WARNING, 0, "", "the proposed change's id; the rehearsal's report could not be "
       "posted as a thread on it, and the status is kept"),
    _r("platform.unreachable", REJECTION, 2, "", "PREFECT_API_URL's address; the orchestrator's platform did not "
       "answer; status error"),

    # The core's client's (M13), as the orchestrator's client of the core files them.
    _r("api.unreachable", REJECTION, 2, "", "the address; nothing answers there, the answer is not the API's, or it "
       "ended before its document; status error", core=True),
    _r("api.token.refused", REJECTION, 2, "", "FYLGJA_API_TOKEN when it is unset or unsendable, else the address that "
       "answered 401; status error", core=True),
    _r("api.version.unknown", REJECTION, 2, "", "the address; it answered 404 naming the versions it serves, none of "
       "them this client's; status error", core=True),
    _r("api.transfer.too_large", REJECTION, 2, "", "the operation; a request over the server's bound (413), or a frame "
       "of the answer over the client's; status error", core=True),
)

BY_ID: dict[str, Rule] = {r.id: r for r in RULES}

ORCHESTRATOR_OWN = ("record.twin.stale", "step.target.required", "rehearsal.report.unposted", "platform.unreachable")
"""The identifiers no core build ever filed: the orchestrator's own (data-model §11)."""


def rule(id: str) -> Rule:
    """The rule of an identifier; KeyError for one this table does not hold."""
    return BY_ID[id]
