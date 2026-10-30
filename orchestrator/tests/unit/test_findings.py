"""The findings document held to the core's (`internal/findings`): one document of each
operation, transcribed by hand from the Go tests that build them (`tests/data/findings/`,
each naming its test), rendered to the bytes `WriteJSON` writes and the lines `WriteText`
prints, with its exit, and valid under `contracts/findings.schema.json`; and the three
documents captured from the Go build (`tests/golden/`: stage list's, stage plan's and the
rehearsal's), decoded and written again to their bytes, their findings to the text the Go
CLI printed on stderr. The rules' table (`documents/rules.py`) is held to the contract's
pattern, to every identifier the adapter files, and to the core's identifiers."""

import json
import re
from pathlib import Path

import jsonschema
import pytest

from fylgja_orchestrator.adapters.infrahub import (
    client,
    packages,
    probes,
    read,
    schema,
    snapshot,
    stage_reader,
    stages,
    stamps,
    validate,
)
from fylgja_orchestrator import core, record
from fylgja_orchestrator.adapters.infrahub import __main__ as adapter
from fylgja_orchestrator.documents import findings, rules
from fylgja_orchestrator.documents.findings import (
    INFO,
    REJECTION,
    WARNING,
    Document,
    Finding,
    Findings,
    Location,
    go_float,
    go_json,
)

from .conftest import DATA

REPO = Path(__file__).resolve().parents[3]
GOLDEN = REPO / "orchestrator" / "tests" / "golden"
CASES = sorted((DATA / "findings").glob("*.json"))
CONTRACT = json.loads((REPO / "contracts" / "findings.schema.json").read_text())


def case(path):
    return json.loads(path.read_text())


# The documents of each operation.


def test_the_cases_cover_every_operation():
    ops = {case(p)["document"]["operation"] for p in CASES}
    assert ops == set(findings.OPERATIONS) == set(CONTRACT["properties"]["operation"]["enum"])


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.stem)
def test_a_document_renders_as_the_cores(path):
    """Decoded and written again, the document is its JSON byte for byte, as WriteJSON
    writes it; its text is WriteText's; its exit its status's; and it is the contract's."""
    c = case(path)
    doc = Document.from_dict(c["document"])
    assert doc.json() == json.dumps(c["document"], indent=2, ensure_ascii=False).translate(
        findings._GO_ESCAPES) + "\n"
    assert doc.to_dict() == c["document"]
    assert doc.text() == c["text"]
    assert doc.exit_code == c["exit"]
    findings.validate(doc.to_dict())


@pytest.mark.parametrize("name,stderr", [
    ("stages.json", None),
    ("stages-with-twin.json", None),
    ("plan.json", "plan.stderr.txt"),
    ("rehearsal.json", "rehearsal.stderr.txt"),
])
def test_the_goldens_are_written_again_to_their_bytes(name, stderr):
    """The Go build's documents (tests/golden/README.md), floats and escapes among them:
    decoded and written again they are the bytes the Go CLI printed, and their findings the
    text it printed on stderr (stage list printed none)."""
    raw = (GOLDEN / name).read_text()
    doc = Document.from_dict(json.loads(raw))
    # The README's one edit to the captured bytes: the state root typed in as <state-root>,
    # which Go's encoder would have escaped had it written it.
    assert doc.json().replace("\\u003cstate-root\\u003e", "<state-root>") == raw
    assert doc.text() == ((GOLDEN / stderr).read_text() if stderr else "")
    findings.validate(doc.to_dict())


def test_text_renders_rejections_first_and_the_summary_last():
    """TestTextRenderingPutsRejectionsFirstAndSummaryLast: the operator reads the top of the
    output, so a rejection is never buried under info."""
    doc = findings.new_document(findings.OP_COMPILE, None, [
        Finding(INFO, "omit.mgmt.extra", "n1:mgmt1", "one management connection per node"),
        Finding(REJECTION, "link.endpoints.count", "n1:e1|n2:e1", "link has 1 endpoint"),
        Finding(WARNING, "psp.resources.implausible", "nokia_srlinux", "implausible"),
    ])
    lines = doc.text().splitlines()
    assert len(lines) == 4 and lines[0].startswith("rejection ")
    assert lines[3] == "3 finding(s): 1 rejection, 1 warning, 1 info"
    assert doc.status == findings.STATUS_REJECTED


def test_render_routes_by_flag():
    """TestRenderRoutesByFlag: under --json one document on stdout and nothing on stderr; in
    text the findings on stderr and nothing on stdout, which the success lines own."""
    import io

    doc = findings.new_document(findings.OP_COMPILE, None,
                                [Finding(REJECTION, "ctm.devices.empty", "fylgja-fixture", "no devices")])
    out, err = io.StringIO(), io.StringIO()
    assert findings.render(doc, out, err, True) == findings.EXIT_REJECTED
    assert err.getvalue() == "" and json.loads(out.getvalue())["status"] == "rejected"
    out, err = io.StringIO(), io.StringIO()
    assert findings.render(doc, out, err, False) == findings.EXIT_REJECTED
    assert out.getvalue() == "" and "ctm.devices.empty" in err.getvalue()


def test_exit_codes():
    """TestExitCodes: seven statuses, six exit codes, one table (contracts/cli.md)."""
    assert {s: findings.exit_code(s) for s in findings.STATUSES} == {
        "ok": 0, "rejected": 1, "error": 2, "failed": 3, "unclean": 4, "diverged": 4, "nonconforming": 5}
    assert set(findings.STATUSES) == set(CONTRACT["properties"]["status"]["enum"])


def test_the_steps_are_the_contracts():
    enum = CONTRACT["properties"]["findings"]["items"]["properties"]["step"]["enum"]
    for step in (findings.STEP_START, findings.STEP_READ, findings.STEP_COMPILE, findings.STEP_RESOLVE):
        assert step in enum


def test_error_documents():
    """ErrorDocument, the server's failAt and RuleErrorDocument: status error, one rejection,
    about the operation unless an object is named."""
    d = findings.error_document(findings.OP_INTENT_READ, {"branch": "b"}, "--out is required")
    assert d.to_dict()["findings"] == [{"severity": "rejection", "rule": "operation.failed", "object": "intent.read",
                                        "message": "--out is required"}]
    assert d.exit_code == 2
    d = findings.error_document(findings.OP_STAGE_LIST, None, "x", "resolve", "stage.list")
    assert "subject" not in d.to_dict() and d.findings[0].step == "resolve"
    d = findings.rule_error_document(findings.OP_STAGE_LIST, None, "scope.unset", "FYLGJA_DEFAULT_SCOPE", "m", "start")
    assert (d.status, d.findings[0].rule, d.findings[0].step) == ("error", "scope.unset", "start")


def test_a_document_carries_nothing_the_contract_does_not():
    with pytest.raises(ValueError):
        Document(findings.OP_INTENT_READ, blocks={"ctm": {}})
    with pytest.raises(ValueError):
        Document(findings.OP_INTENT_READ, subject={"probes": "p.json"})
    d = Document(findings.OP_INTENT_READ, subject={})
    with pytest.raises(ValueError):
        d.set("following", {})
    # An empty subject is written as {}, an absent one not at all; an empty field is left out.
    assert d.to_dict()["subject"] == {}
    d.subject = {"branch": "b", "at": "", "files": []}
    assert d.to_dict()["subject"] == {"branch": "b"}


def test_a_finding_keeps_its_location_at_a_step():
    f = Findings([Finding(WARNING, "psp.schema", "x", "m", location=Location("psp/x.yaml", 3))]).at_step("verify")
    assert f[0].location == Location("psp/x.yaml", 3) and f[0].step == "verify"
    assert f[0].text() == "warning psp.schema [step verify] psp/x.yaml:3 (x): m"


@pytest.mark.parametrize("x,want", [
    (74.5, "74.5"), (100.0, "100"), (0.0, "0"), (-0.0, "-0"), (1e-06, "0.000001"), (1e-07, "1e-7"),
    (1.5e22, "1.5e+22"), (1e21, "1e+21"), (1e20, "100000000000000000000"), (0.1, "0.1"), (2.5e-10, "2.5e-10"),
    (123456789.125, "123456789.125"), (-3.0, "-3"),
])
def test_floats_are_written_as_go_writes_them(x, want):
    """encoding/json's floatEncoder: the shortest digits, plain from 1e-6 to below 1e21,
    else an exponent with Go's cleaned form."""
    assert go_float(x) == want


def test_go_json_escapes_as_go_does():
    assert go_json({"a": "<&>  é", "b": [], "c": {}, "d": [1.0]}) == (
        '{\n  "a": "\\u003c\\u0026\\u003e\\u2028\\u2029é",\n  "b": [],\n  "c": {},\n  "d": [\n    1\n  ]\n}\n')


def test_quote_is_gos_percent_q():
    assert findings.quote('a "b" \\ \n\t\x01é​') == '"a \\"b\\" \\\\ \\n\\t\\x01é\\u200b"'


# The rules.


RULE_PATTERN = re.compile(CONTRACT["properties"]["findings"]["items"]["properties"]["rule"]["pattern"])


def test_every_rule_matches_the_contracts_pattern():
    """TestEveryRuleMatchesTheContractPattern: read from the schema, not copied."""
    for r in rules.RULES:
        assert RULE_PATTERN.search(r.id), r.id


def test_rule_identifiers_are_distinct():
    ids = [r.id for r in rules.RULES]
    assert len(ids) == len(set(ids))


def test_every_rule_is_whole():
    steps = set(CONTRACT["properties"]["findings"]["items"]["properties"]["step"]["enum"])
    for r in rules.RULES:
        assert r.severity in (REJECTION, WARNING, INFO), r.id
        assert r.exit in (0, 1, 2, 3, 4, 5), r.id
        assert (r.exit == 0) == (r.severity != REJECTION), r.id
        assert set(r.steps) <= steps, r.id
        assert r.wording, r.id


def _declared_rules(*modules):
    """Every RULE_* constant of the modules: the identifiers they file."""
    return {getattr(m, n) for m in modules for n in dir(m) if n.startswith("RULE_")}


def test_every_rule_the_adapter_files_is_in_the_table():
    """Each identifier a module of the adapter or the documents names is listed, so a rule is
    added to the table before any module files it."""
    filed = _declared_rules(client, packages, probes, read, schema, snapshot, stage_reader, stages, stamps, validate,
                            adapter, findings, core, record)
    # snapshot.py raises its refusals by identifier, as the core files them.
    filed |= {"snapshot.invalid", "snapshot.version.unsupported", "snapshot.id.mismatch"}
    assert filed <= set(rules.BY_ID), sorted(filed - set(rules.BY_ID))


def _core_rules():
    """The identifiers `internal/findings/finding.go` declares today."""
    text = (REPO / "internal" / "findings" / "finding.go").read_text()
    return set(re.findall(r'^\s*Rule\w+\s*=\s*"([^"]+)"', text, re.M))


def test_the_cores_rules_are_the_cores():
    """A rule the core keeps is one it declares; the orchestrator's own four it never did; and
    the retired rules it declares no more since the Go reader went (T035), as its
    `TestTheOrchestratorsRulesAreRetired` holds from the other side."""
    core = _core_rules()
    assert {r.id for r in rules.RULES if r.core} <= core
    assert set(rules.ORCHESTRATOR_OWN) <= set(rules.BY_ID)
    assert not set(rules.ORCHESTRATOR_OWN) & core
    retired = {r.id for r in rules.RULES if not r.core} - set(rules.ORCHESTRATOR_OWN)
    assert not retired & core, sorted(retired & core)


def test_the_retired_rules_are_data_models():
    """data-model §11's retired families are the orchestrator's: every scope.*, stage.* but
    M2's stage.failed, rehearsal.*, schema.* and probes.* rule, with intent.at.precision,
    probe.kind.absent, snapshot.flags.conflict, step.target.current and step.stage.skipped;
    and the core declares none of them but stage.failed (T035)."""
    owned = {r.id for r in rules.RULES if not r.core} - set(rules.ORCHESTRATOR_OWN)
    families = ("scope.", "stage.", "rehearsal.", "schema.", "probes.")
    singles = {"intent.at.precision", "probe.kind.absent", "snapshot.flags.conflict", "step.target.current",
               "step.stage.skipped"}
    assert {r for r in owned if not r.startswith(families)} == singles
    assert len(owned) == 36
    core = _core_rules()
    assert {r for r in core if r.startswith(families)} == {"stage.failed"}


def test_a_rules_document_validates():
    """A finding of each rule, in a document of its exit's status, is the contract's."""
    status = {0: "ok", 1: "rejected", 2: "error", 3: "failed", 4: "unclean", 5: "nonconforming"}
    for r in rules.RULES:
        f = Finding(r.severity, r.id, "x", r.wording, r.steps[0] if r.steps else "")
        doc = Document(findings.OP_INTENT_READ, status[r.exit], None, Findings([f]))
        try:
            findings.validate(doc.to_dict())
        except jsonschema.ValidationError as e:  # pragma: no cover - the message is the point
            pytest.fail(f"{r.id}: {e.message}")
