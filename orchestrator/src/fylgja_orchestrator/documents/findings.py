"""The findings document, `findings 1`, in the core's one shape (`internal/findings`): a
finding is the severity, the rule, the object at fault and the message, the step for a
run's and the file for a package's; a document is the operation, its status, its subject,
the blocks it carries and its findings. The rule identifiers are stable API, so every
module that refuses something files it under the rule the core would, worded as the core
words it (`documents/rules.py` lists them).

Its two renderings are the core's, line for line: the JSON as `Document.WriteJSON` writes
it (Go's `json.MarshalIndent` of the structs, two spaces, a newline), and the text as
`WriteText` writes it (rejections first, then by rule and object, a summary last). Under
`--json` the document goes to stdout and nothing else does; in text its findings go to
stderr, which leaves stdout for the success lines (`Render`). The document is held to
`contracts/findings.schema.json` by `validate`.
"""

import json
import math
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path

REJECTION = "rejection"
"""Prevents any CTM, snapshot or bundle from being written."""

WARNING = "warning"
"""Reported, and prevents nothing."""

INFO = "info"
"""Something worth knowing, such as a recorded omission."""

VERSION = "1"
"""findings_version: every document this module writes."""

# The operations, as contracts/findings.schema.json enumerates them. The orchestrator's are
# intent.read, schema.check, stage.list, stage.plan, twin.create and twin.step from its
# flows, and twin.rehearse (data-model §11); the rest are the core's, whose documents the
# flows carry through.
OP_INTENT_READ = "intent.read"
OP_COMPILE = "twin.compile"
OP_SCHEMA_CHECK = "schema.check"
OP_PSP_VALIDATE = "psp.validate"
OP_TWIN_CREATE = "twin.create"
OP_TWIN_PROVISION = "twin.provision"
OP_TWIN_DESTROY = "twin.destroy"
OP_TWIN_SHOW = "twin.show"
OP_STAGE_LIST = "stage.list"
OP_STAGE_PLAN = "stage.plan"
OP_TWIN_STEP = "twin.step"
OP_TWIN_VERIFY = "twin.verify"
OP_TWIN_REHEARSE = "twin.rehearse"
OP_RUN_READ = "run.read"
OP_RUN_INTERRUPT = "run.interrupt"
OP_TWIN_DIFF = "twin.diff"

OPERATIONS = (
    OP_INTENT_READ, OP_COMPILE, OP_SCHEMA_CHECK, OP_PSP_VALIDATE, OP_TWIN_CREATE, OP_TWIN_PROVISION,
    OP_TWIN_DESTROY, OP_TWIN_SHOW, OP_STAGE_LIST, OP_STAGE_PLAN, OP_TWIN_STEP, OP_TWIN_VERIFY,
    OP_TWIN_REHEARSE, OP_RUN_READ, OP_RUN_INTERRUPT, OP_TWIN_DIFF,
)

# The statuses, each mapped onto the process's exit code (contracts/cli.md).
STATUS_OK = "ok"
STATUS_REJECTED = "rejected"
STATUS_ERROR = "error"
STATUS_FAILED = "failed"
STATUS_UNCLEAN = "unclean"
STATUS_DIVERGED = "diverged"
STATUS_NONCONFORMING = "nonconforming"

EXIT_OK = 0
EXIT_REJECTED = 1
EXIT_ERROR = 2
EXIT_FAILED = 3
EXIT_UNCLEAN = 4
EXIT_NONCONFORMING = 5

_EXITS = {
    STATUS_OK: EXIT_OK,
    STATUS_REJECTED: EXIT_REJECTED,
    STATUS_ERROR: EXIT_ERROR,
    STATUS_FAILED: EXIT_FAILED,
    STATUS_UNCLEAN: EXIT_UNCLEAN,
    STATUS_DIVERGED: EXIT_UNCLEAN,
    STATUS_NONCONFORMING: EXIT_NONCONFORMING,
}

STATUSES = tuple(_EXITS)

# The steps the adapter's findings carry; the enum is the contract's.
STEP_START = "start"
STEP_READ = "read"
STEP_COMPILE = "compile"
STEP_RESOLVE = "resolve"

RULE_OPERATION_FAILED = "operation.failed"
"""The operation did not run (exit 2): the catch-all an error document carries."""


def exit_code(status: str) -> int:
    """The process exit code for a status (`Status.ExitCode`); 0 for one it does not know."""
    return _EXITS.get(status, EXIT_OK)


@dataclass(frozen=True)
class Location:
    """Where in a file a finding about a file points: a package's, never intent's."""

    file: str
    line: int = 0


@dataclass(frozen=True)
class Finding:
    severity: str
    rule: str
    object: str
    message: str
    step: str = ""
    location: Location | None = None

    def to_dict(self) -> dict:
        """The finding as the document carries it, the step and the location left out when
        it has none."""
        out = {"severity": self.severity, "rule": self.rule, "object": self.object, "message": self.message}
        if self.step:
            out["step"] = self.step
        if self.location is not None:
            loc = {"file": self.location.file}
            if self.location.line:
                loc["line"] = self.location.line
            out["location"] = loc
        return out

    @classmethod
    def from_dict(cls, d: dict) -> "Finding":
        loc = d.get("location")
        return cls(d["severity"], d["rule"], d["object"], d["message"], d.get("step", ""),
                   Location(loc["file"], loc.get("line", 0)) if loc else None)

    def text(self) -> str:
        """The finding as WriteText prints it: `<severity> <rule>[ [step <step>]] <where>:
        <message>`, where is the object, or the file (and line) with the object after it."""
        where = self.object
        if self.location is not None:
            where = self.location.file
            if self.location.line > 0:
                where = f"{where}:{self.location.line}"
            if self.object:
                where = f"{where} ({self.object})"
        rule = f"{self.rule} [step {self.step}]" if self.step else self.rule
        return f"{self.severity} {rule} {where}: {self.message}"


_RANK = {REJECTION: 0, WARNING: 1, INFO: 2}


class Findings(list):
    """Findings gathered in one pass, never returned early: whoever fixes intent sees every
    problem at once."""

    def add(self, severity: str, rule: str, object: str, message: str) -> None:
        self.append(Finding(severity, rule, object, message))

    def reject(self, rule: str, object: str, message: str) -> None:
        self.add(REJECTION, rule, object, message)

    def add_step(self, severity: str, step: str, rule: str, object: str, message: str) -> None:
        """A finding of a run's step."""
        self.append(Finding(severity, rule, object, message, step))

    def at_step(self, step: str) -> "Findings":
        """A copy with every finding at step (`List.AtStep`)."""
        return Findings(replace(f, step=step) for f in self)

    @property
    def rejected(self) -> bool:
        """Whether any finding is a rejection: what stops the command."""
        return any(f.severity == REJECTION for f in self)

    def count_of(self, severity: str) -> int:
        """How many findings carry the severity (`List.Count`; list.count keeps its meaning)."""
        return sum(1 for f in self if isinstance(f, Finding) and f.severity == severity)

    def carries(self, rule: str) -> bool:
        """Whether any finding is of the rule."""
        return any(f.rule == rule for f in self)

    def text_lines(self) -> list[str]:
        """Each finding as WriteText prints it, in its order, with no summary (`List.TextLines`):
        rejections first, then warnings, then info, each by rule then object, the order of
        equals kept."""
        ordered = sorted(self, key=lambda f: (_RANK.get(f.severity, 0), f.rule, f.object))
        return [f.text() for f in ordered]


# The document.

SUBJECT_KEYS = ("branch", "at", "ctm", "files", "out", "bundle", "run_id", "stage", "scope", "snapshot")
"""`Subject`'s fields in its struct's order, each left out when empty."""

BLOCK_KEYS = (
    "snapshot_id", "bundle_id", "snapshot_from", "snapshot_to", "bundle_from", "bundle_to", "verified", "twin",
    "cleanup", "dry_run", "show", "stage", "stages", "plan", "step", "verify", "rehearsal",
)
"""What a document carries between its subject and its findings, in `Document`'s order,
each left out when absent: the ids as strings, the blocks as the contract shapes them."""


@dataclass
class Document:
    """The machine-readable result of one operation. `subject` is None when the operation
    names none (written absent) and a dict of SUBJECT_KEYS otherwise; `blocks` holds what
    the document carries by BLOCK_KEYS, the blocks already in the contract's shape."""

    operation: str
    status: str = STATUS_OK
    subject: dict | None = None
    findings: Findings = field(default_factory=Findings)
    blocks: dict = field(default_factory=dict)

    def __post_init__(self):
        self.findings = Findings(self.findings)
        unknown = [k for k in self.blocks if k not in BLOCK_KEYS]
        if unknown:
            raise ValueError(f"a findings document carries no {', '.join(unknown)}")
        if self.subject is not None:
            unknown = [k for k in self.subject if k not in SUBJECT_KEYS]
            if unknown:
                raise ValueError(f"a findings document's subject carries no {', '.join(unknown)}")

    def set(self, key: str, value) -> None:
        """Carries a block or an id, None or "" to carry none."""
        if key not in BLOCK_KEYS:
            raise ValueError(f"a findings document carries no {key}")
        self.blocks[key] = value

    @property
    def exit_code(self) -> int:
        return exit_code(self.status)

    def to_dict(self) -> dict:
        """The document as WriteJSON writes it, its keys in the struct's order."""
        out: dict = {"findings_version": VERSION, "operation": self.operation, "status": self.status}
        if self.subject is not None:
            out["subject"] = {k: self.subject[k] for k in SUBJECT_KEYS if self.subject.get(k) not in (None, "", [])}
        for k in BLOCK_KEYS:
            if self.blocks.get(k) not in (None, ""):
                out[k] = self.blocks[k]
        out["findings"] = [f.to_dict() for f in self.findings]
        return out

    @classmethod
    def from_dict(cls, d: dict) -> "Document":
        """A document as the core or a flow wrote it (`json.Unmarshal` into `Document`)."""
        return cls(
            operation=d["operation"],
            status=d["status"],
            subject=dict(d["subject"]) if d.get("subject") is not None else None,
            findings=Findings(Finding.from_dict(f) for f in d.get("findings") or []),
            blocks={k: d[k] for k in BLOCK_KEYS if k in d},
        )

    def json(self) -> str:
        """WriteJSON: one document, deterministically, a newline after it."""
        return go_json(self.to_dict())

    def text(self) -> str:
        """WriteText: each finding on its line, then the summary when there is any."""
        lines = self.findings.text_lines()
        if self.findings:
            f = self.findings
            lines.append(f"{len(f)} finding(s): {f.count_of(REJECTION)} rejection, "
                         f"{f.count_of(WARNING)} warning, {f.count_of(INFO)} info")
        return "".join(line + "\n" for line in lines)


def new_document(operation: str, subject: dict | None, found=None) -> Document:
    """A document whose status is the findings': rejected when any refuses, ok otherwise
    (`NewDocument`)."""
    found = Findings(found or [])
    return Document(operation, STATUS_REJECTED if found.rejected else STATUS_OK, subject, found)


def error_document(operation: str, subject: dict | None, message: str, step: str = "", object: str = "") -> Document:
    """The operation could not run at all, as distinct from running and rejecting its input:
    operation.failed, about the operation unless object names another, at step when given
    (`ErrorDocument`, and the server's `failAt`)."""
    return Document(operation, STATUS_ERROR, subject,
                    Findings([Finding(REJECTION, RULE_OPERATION_FAILED, object or operation, message, step)]))


def rule_error_document(operation: str, subject: dict | None, rule: str, object: str, message: str,
                        step: str = "") -> Document:
    """An operational failure under a rule of its own rather than operation.failed, such as
    intent.at.precision or a guard's refusal at start (`RuleErrorDocument`)."""
    return Document(operation, STATUS_ERROR, subject, Findings([Finding(REJECTION, rule, object, message, step)]))


def render(doc: Document, stdout, stderr, as_json: bool) -> int:
    """Writes a document in the mode --json selects and returns the exit code: JSON to stdout
    and nothing else, or the findings' text to stderr, stdout left to the success lines
    (`Render`)."""
    if as_json:
        stdout.write(doc.json())
    else:
        stderr.write(doc.text())
    return doc.exit_code


# Go's encoder.

# The characters Go's encoder escapes in a string and json.dumps(ensure_ascii=False) writes
# raw (encoding/json's HTML-safe set), and a lone surrogate, which Go never holds (it decodes
# one as U+FFFD). None can appear outside a string in the encoded text, so the text is
# translated whole, as the snapshot's encoder translates it.
_GO_ESCAPES = str.maketrans(
    {
        "<": "\\u003c",
        ">": "\\u003e",
        "&": "\\u0026",
        "\N{LINE SEPARATOR}": "\\u2028",
        "\N{PARAGRAPH SEPARATOR}": "\\u2029",
        **{chr(c): "\N{REPLACEMENT CHARACTER}" for c in range(0xD800, 0xE000)},
    }
)


def go_float(x: float) -> str:
    """A float as Go's encoder writes it (`floatEncoder`): the shortest digits that
    round-trip, in plain notation from 1e-6 to below 1e21 with no fraction when there is
    none, and otherwise in exponent notation with at least one exponent digit (`1e-7`,
    `1e+21`)."""
    if math.isnan(x) or math.isinf(x):
        raise ValueError(f"json: unsupported value: {x!r}")
    if x == 0:
        return "-0" if math.copysign(1.0, x) < 0 else "0"
    d = Decimal(repr(x))  # the shortest digits that round-trip, as Go's precision -1 gives
    if 1e-6 <= abs(x) < 1e21:
        text = format(d, "f")
        return text.rstrip("0").rstrip(".") if "." in text else text
    sign, digits, exponent = d.as_tuple()
    mantissa = "".join(map(str, digits)).rstrip("0") or "0"
    exp = exponent + len(digits) - 1
    body = mantissa[0] + ("." + mantissa[1:] if len(mantissa) > 1 else "")
    return f"{'-' if sign else ''}{body}e{'-' if exp < 0 else '+'}{abs(exp):02d}".replace("e-0", "e-", 1)


class _Encoder(json.JSONEncoder):
    """json.dumps' pure-Python encoder with Go's floats: the C encoder writes a float by
    float.__repr__ whatever it is told."""

    def iterencode(self, o, _one_shot=False):
        return json.encoder._make_iterencode(
            {}, self.default, json.encoder.py_encode_basestring, " " * self.indent, go_float,
            self.key_separator, self.item_separator, self.sort_keys, self.skipkeys, _one_shot,
        )(o, 0)


def go_json(value) -> str:
    """Go's json.MarshalIndent(value, "", "  ") plus a newline, over dicts already in the
    structs' key order: two spaces, `": "` and `,`, `<`, `>`, `&`, U+2028 and U+2029
    escaped, `[]` and `{}` for an empty list and map, and floats as Go writes them."""
    text = json.dumps(value, indent=2, ensure_ascii=False, cls=_Encoder)
    return text.translate(_GO_ESCAPES) + "\n"


# The contract.

REPOSITORY = Path(__file__).resolve().parents[4]
"""The repository the orchestrator is installed from (the editable install), whose
`contracts/` the document is held to."""

SCHEMA_ID_PREFIX = "https://github.com/happypathnetworking/fylgja/schemas/"


def validate(document: dict, contracts: Path | None = None) -> None:
    """Holds a document to `contracts/findings.schema.json`, the schemas it references
    added under their `$id`s; jsonschema's ValidationError when it does not hold. The
    validator is jsonschema, which the platform's own dependencies carry, imported here
    alone."""
    import jsonschema
    from referencing import Registry, Resource

    directory = contracts or REPOSITORY / "contracts"
    findings_schema = json.loads((directory / "findings.schema.json").read_text())
    registry = Registry()
    for path in sorted(directory.glob("*.schema.json")):
        schema = json.loads(path.read_text())
        if str(schema.get("$id", "")).startswith(SCHEMA_ID_PREFIX):
            registry = registry.with_resource(schema["$id"], Resource.from_contents(schema))
    validator = jsonschema.validators.validator_for(findings_schema)
    validator(findings_schema, registry=registry, format_checker=validator.FORMAT_CHECKER).validate(document)


_SHORT = {"\a": "\\a", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t", "\v": "\\v"}


def quote(value: str) -> str:
    """value as Go's `%q` (strconv.Quote) writes it: double-quoted, the quote and the
    backslash escaped, a printable character kept, a control character by its short form or
    `\\x`, any other unprintable one by `\\u` or `\\U`. Python's `isprintable` is Go's
    `unicode.IsPrint`: letters, marks, numbers, punctuation and symbols, and the ASCII
    space. A lone surrogate, which Go never holds (it decodes one as U+FFFD), is written as
    U+FFFD."""
    out = ['"']
    for ch in value:
        if 0xD800 <= ord(ch) <= 0xDFFF:
            ch = "\N{REPLACEMENT CHARACTER}"
        if ch in ('"', "\\"):
            out.append("\\" + ch)
        elif ch.isprintable():
            out.append(ch)
        elif ch in _SHORT:
            out.append(_SHORT[ch])
        elif ord(ch) < 0x80:
            out.append(f"\\x{ord(ch):02x}")
        elif ord(ch) <= 0xFFFF:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(f"\\U{ord(ch):08x}")
    out.append('"')
    return "".join(out)
