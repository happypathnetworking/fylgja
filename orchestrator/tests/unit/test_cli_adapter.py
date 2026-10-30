"""The adapter's three commands (`python -m fylgja_orchestrator.adapters.infrahub read |
stages | schema-check`) on recorded answers, as `fylgja intent read`, `stage list` and
`schema check` answered through the core's server (`internal/server/read.go`, `stages.go`,
`schema.go`): each command's exit, its success lines on stdout, its findings on stderr in
text, its document alone on stdout under --json, valid under the contract; the guards
refused before any request; the stage listing's text and JSON the goldens' bytes; and the
token never printed."""

import io
import json
from datetime import UTC, datetime

import pytest

from fylgja_orchestrator.adapters.infrahub import __main__ as adapter
from fylgja_orchestrator.adapters.infrahub import mapping, snapshot
from fylgja_orchestrator.documents import findings
from fylgja_orchestrator.documents.findings import Findings

from .conftest import ADDRESS, DATA, TOKEN
from .dcim import Dcim
from .test_probes import probe_node, serve_probes, with_probe_kind
from .test_stages import GOLDEN, serve_recorded

SCOPE = "tag:fylgja"
ENVIRON = {"INFRAHUB_ADDRESS": ADDRESS, "INFRAHUB_API_TOKEN": TOKEN, "FYLGJA_DEFAULT_SCOPE": SCOPE}
NO_PROBES = str(DATA / "probes" / "none.json")
STARTUP = f"fylgja-infrahub: reading {ADDRESS} as infrahub-dcim@26336e9, scope {SCOPE}\n"
GOLDEN_BRANCH = "fylgja-test-golden-41263"
GOLDEN_NOW = datetime(2026, 10, 29, 19, 0, tzinfo=UTC)


def run(args, infrahub, environ=None, now=None):
    """One command, its exit, stdout and stderr; the token is never in either."""
    out, err = io.StringIO(), io.StringIO()
    env = adapter.Env(environ=dict(ENVIRON if environ is None else environ), requester=infrahub, now=now)
    code = adapter.main(args, out, err, env)
    assert TOKEN not in out.getvalue() + err.getvalue()
    return code, out.getvalue(), err.getvalue()


def run_json(args, infrahub, environ=None, now=None):
    """One command under --json: stdout is one document, the contract's, whose exit is the
    command's; stderr is no more than the start-up line."""
    code, out, err = run(args + ["--json"], infrahub, environ, now)
    doc = json.loads(out)
    findings.validate(doc)
    assert findings.exit_code(doc["status"]) == code
    assert err in ("", STARTUP)
    return code, doc


@pytest.fixture
def fake(infrahub):
    return Dcim.from_ctm(infrahub)


# read


def test_read_writes_the_snapshot(fake, tmp_path):
    out = tmp_path / "snap.json"
    code, stdout, stderr = run(["read", "--branch", "fylgja-fixture", "--probes", NO_PROBES, "--out", str(out)],
                               fake.infrahub)

    assert code == 0
    taken = snapshot.read(out)
    assert taken["probes"] == [] and taken["snapshot_id"] == snapshot.snapshot_id(taken)
    assert out.read_bytes() == snapshot.marshal(taken)
    schema_hash = fake.infrahub.schema["main"]
    assert stdout == (f"wrote {out}: 3 devices (nokia_srlinux 3), 15 interfaces, 3 links, 3 artifacts "
                      f"(branch fylgja-fixture, scope {SCOPE}, schema {schema_hash}); "
                      f"snapshot {taken['snapshot_id']}\n")
    assert stderr == STARTUP

    out.unlink()
    code, doc = run_json(["read", "--branch", "fylgja-fixture", "--probes", NO_PROBES, "--out", str(out)],
                         fake.infrahub)
    assert code == 0 and doc["snapshot_id"] == taken["snapshot_id"] == snapshot.read(out)["snapshot_id"]
    assert doc["subject"] == {"branch": "fylgja-fixture", "out": str(out), "scope": SCOPE}
    assert doc["findings"] == [] and "stage" not in doc


def test_read_takes_the_kinds_probes(fake, tmp_path):
    """No --probes: the probes declared in FylgjaProbe on the default branch, carried by the
    snapshot."""
    declared = json.loads((DATA / "probes" / "n1-loop.json").read_text())["probes"]
    with_probe_kind(fake.infrahub)
    serve_probes(fake.infrahub, [probe_node(p) for p in declared])
    out = tmp_path / "snap.json"

    code, doc = run_json(["read", "--branch", "fylgja-fixture", "--out", str(out)], fake.infrahub)

    assert code == 0
    assert snapshot.read(out)["probes"] == declared
    assert len(fake.infrahub.served("Probes")) == 1


def test_read_refuses_what_the_kind_cannot_serve(fake, tmp_path):
    out = tmp_path / "snap.json"
    code, doc = run_json(["read", "--branch", "fylgja-fixture", "--out", str(out)], fake.infrahub)

    assert code == 1 and not out.exists()
    assert [(f["rule"], f["object"], f.get("step")) for f in doc["findings"]] == [
        ("probe.kind.absent", "FylgjaProbe", "resolve")]
    assert fake.infrahub.served("Devices") == []


def test_a_refused_read_writes_nothing(fake, tmp_path):
    """A scope selecting no device: scope.empty, exit 1, no file, nothing on stdout, the
    findings on stderr after the start-up line."""
    out = tmp_path / "snap.json"
    code, stdout, stderr = run(["read", "--branch", "fylgja-fixture", "--scope", "tag:nothing", "--probes",
                                NO_PROBES, "--out", str(out)], fake.infrahub)

    assert code == 1 and stdout == "" and not out.exists()
    assert stderr == (
        f"fylgja-infrahub: reading {ADDRESS} as infrahub-dcim@26336e9, scope tag:nothing\n"
        "rejection scope.empty tag:nothing: scope tag:nothing selects no device on branch fylgja-fixture\n"
        "1 finding(s): 1 rejection, 0 warning, 0 info\n")


def test_a_read_that_cannot_be_made_is_an_error(fake, tmp_path):
    out = tmp_path / "snap.json"
    code, doc = run_json(["read", "--branch", "nosuch", "--probes", NO_PROBES, "--out", str(out)], fake.infrahub)

    assert code == 2 and not out.exists()
    [f] = doc["findings"]
    assert (f["rule"], f["object"]) == ("operation.failed", "intent.read")
    assert "nosuch" in f["message"] and "not found" in f["message"]


def test_a_snapshot_that_cannot_be_written_is_an_error(fake, tmp_path):
    out = tmp_path / "absent" / "snap.json"
    code, doc = run_json(["read", "--branch", "fylgja-fixture", "--probes", NO_PROBES, "--out", str(out)],
                         fake.infrahub)

    assert code == 2 and "snapshot_id" not in doc
    [f] = doc["findings"]
    assert f["rule"] == "operation.failed" and f["message"].startswith("writing snapshot: ")


@pytest.mark.parametrize("args,environ,want", [
    (["read", "--out", "x"], None, ("operation.failed", "intent.read", None, "--branch or --stage is required")),
    (["read", "--branch", "b"], None, ("operation.failed", "intent.read", None, "--out is required")),
    (["read", "--stage", "nope", "--out", "x"], None,
     ("stage.ref.invalid", "nope", None, '--stage "nope" is not a stage reference: expected <branch>/<label>, a branch '
      'with no "/" and no whitespace and a label with neither')),
    (["read", "--stage", "b/l", "--branch", "b", "--out", "x"], None,
     ("stage.flags.conflict", "--branch", None,
      "--branch is meaningless with --stage: a stage is a whole pinned reference (branch and at)")),
    (["read", "--stage", "b/l", "--at", "2026-10-29T00:00:00Z", "--out", "x"], None,
     ("stage.flags.conflict", "--at", None,
      "--at is meaningless with --stage: a stage is a whole pinned reference (branch and at)")),
    (["read", "--branch", "b", "--at", "2026-09-14T12:00:00.123456789Z", "--out", "x"], None,
     ("intent.at.precision", "2026-09-14T12:00:00.123456789Z", None, None)),
    (["read", "--branch", "b", "--scope", "fylgja", "--out", "x"], None,
     ("scope.invalid", "fylgja", "start", '--scope "fylgja" is not a scope: the accepted form is tag:<name>, the '
      "literal tag: and one word, the tag every device of the twin carries")),
    (["read", "--branch", "b", "--scope", "", "--out", "x"], None, ("scope.invalid", "", "start", None)),
    (["read", "--branch", "b", "--out", "x"], {"INFRAHUB_ADDRESS": ADDRESS, "INFRAHUB_API_TOKEN": TOKEN},
     ("scope.unset", "FYLGJA_DEFAULT_SCOPE", "start", "no --scope was given and there is no default: name one with "
      "--scope tag:<name>, or set FYLGJA_DEFAULT_SCOPE where the adapter runs")),
    (["read", "--branch", "b", "--out", "x"], {**ENVIRON, "FYLGJA_DEFAULT_SCOPE": "fylgja"},
     ("scope.invalid", "fylgja", "start", None)),
    (["read", "--branch", "b", "--out", "x"], {"FYLGJA_DEFAULT_SCOPE": SCOPE},
     ("operation.failed", "intent.read", None, "INFRAHUB_ADDRESS is not set")),
    (["stages", "--branch", "a b"], None,
     ("stage.ref.invalid", "a b", "start", '--branch "a b" is not a branch: expected a branch with no "/" and no '
      "whitespace")),
    (["stages"], {"INFRAHUB_ADDRESS": ADDRESS, "INFRAHUB_API_TOKEN": TOKEN},
     ("scope.unset", "FYLGJA_DEFAULT_SCOPE", "start", None)),
    (["stages"], {"FYLGJA_DEFAULT_SCOPE": SCOPE}, ("operation.failed", "stage.list", "resolve", None)),
    (["schema-check"], None, ("operation.failed", "schema.check", None, "--branch is required")),
    (["schema-check", "--branch", "b"], {}, ("operation.failed", "schema.check", None, None)),
])
def test_the_guards_refuse_before_any_request(infrahub, args, environ, want):
    """Each refused before anything is dialled, exit 2, in the core's words; nothing written,
    nothing on stdout in text."""
    code, doc = run_json(args, infrahub, environ)
    assert code == 2 and doc["status"] == "error"
    [f] = doc["findings"]
    rule, object, step, message = want
    assert (f["rule"], f["object"], f.get("step")) == (rule, object, step)
    if message is not None:
        assert f["message"] == message
    assert infrahub.requests == []
    code, stdout, stderr = run(args, infrahub, environ)
    assert code == 2 and stdout == "" and f"{rule}" in stderr


def test_a_stage_reference_is_named_once_it_parses(infrahub):
    _, doc = run_json(["read", "--stage", "b/l", "--branch", "b", "--out", "x"], infrahub)
    assert doc["subject"] == {"branch": "b", "out": "x", "stage": "b/l"}


def test_read_a_stage_reads_its_resolved_reference(infrahub, monkeypatch, tmp_path):
    """--stage: resolved first, its line printed, then its (branch, at) read; the document
    names the stage, the subject the reference it resolved to, and the summary the stage."""
    serve_recorded(infrahub, "golden.json")
    taken = snapshot.read(DATA / "snapshot" / "three-node.json")
    reads = []

    def read_snapshot(client, scope, registry, probes=None, observed_at=None, out=None):
        reads.append((client.branch, client.at, scope, probes))
        return taken, Findings()

    monkeypatch.setattr(adapter.reading, "read_snapshot", read_snapshot)
    out = tmp_path / "snap.json"
    args = ["read", "--stage", f"{GOLDEN_BRANCH}/seeded", "--probes", NO_PROBES, "--out", str(out)]
    code, stdout, stderr = run(args, infrahub, now=GOLDEN_NOW)

    at = "2026-10-29T18:11:38.471611+00:00"
    assert code == 0 and reads == [(GOLDEN_BRANCH, at, SCOPE, [])]
    assert snapshot.read(out)["snapshot_id"] == taken["snapshot_id"]
    e = taken["ctm"]["envelope"]
    assert stdout.splitlines() == [
        f'stage {GOLDEN_BRANCH}/seeded: branch {GOLDEN_BRANCH} at {at} (written), "seeded"',
        f"wrote {out}: 3 devices (nokia_srlinux 3), 15 interfaces, 3 links, 3 artifacts (stage {GOLDEN_BRANCH}/seeded: "
        f"branch {e['branch']}, at {e['at']}, scope {e['scope']}, schema {e['schema_hash']}); "
        f"snapshot {taken['snapshot_id']}",
    ]

    code, doc = run_json(args, infrahub, now=GOLDEN_NOW)
    assert doc["subject"] == {"branch": GOLDEN_BRANCH, "at": at, "out": str(out), "stage": f"{GOLDEN_BRANCH}/seeded",
                              "scope": SCOPE}
    row = json.loads((GOLDEN / "stages.json").read_text())["stages"]["rows"][1]
    assert doc["stage"] == {k: v for k, v in row.items() if k != "twin"}
    assert doc["snapshot_id"] == taken["snapshot_id"]


def test_a_refused_stage_reads_nothing(infrahub, monkeypatch, tmp_path):
    serve_recorded(infrahub, "golden.json")
    monkeypatch.setattr(adapter.reading, "read_snapshot", lambda *a, **k: pytest.fail("a refused stage was read"))
    out = tmp_path / "snap.json"

    code, doc = run_json(["read", "--stage", f"{GOLDEN_BRANCH}/nosuch", "--probes", NO_PROBES, "--out", str(out)],
                         infrahub, now=GOLDEN_NOW)

    assert code == 1 and not out.exists() and "stage" not in doc
    assert doc["subject"]["stage"] == f"{GOLDEN_BRANCH}/nosuch"
    # intent read's operations carry no step.
    assert [(f["rule"], f.get("step")) for f in doc["findings"]] == [("stage.unknown", None)]


# stages


def test_stages_is_the_golden(infrahub):
    """The golden's proposed change as Infrahub answered it: the listing's text is
    stages.txt and its document stages.json, byte for byte."""
    serve_recorded(infrahub, "golden.json")

    code, stdout, stderr = run(["stages", "--branch", GOLDEN_BRANCH], infrahub)
    assert (code, stdout, stderr) == (0, (GOLDEN / "stages.txt").read_text(), STARTUP)

    code, stdout, stderr = run(["stages", "--branch", GOLDEN_BRANCH, "--json"], infrahub)
    assert (code, stdout, stderr) == (0, (GOLDEN / "stages.json").read_text(), STARTUP)


def test_stages_with_the_twins_record_is_the_golden(infrahub):
    from fylgja_orchestrator.adapters.infrahub import stages

    serve_recorded(infrahub, "golden.json")
    rec = stages.RecordView(stages.RecordChange("18e3127c-025b-f488-33be-c5158cf576c3", GOLDEN_BRANCH), "seeded",
                            GOLDEN_BRANCH, "2026-10-29T18:11:38.471611+00:00", "written", SCOPE)
    env = adapter.Env(environ=dict(ENVIRON), requester=infrahub)

    answer = adapter.stage_list(GOLDEN_BRANCH, None, env, rec)

    assert answer.doc.json() == (GOLDEN / "stages-with-twin.json").read_text()
    assert "".join(line + "\n" for line in answer.notes) == (GOLDEN / "stages-with-twin.txt").read_text()


def test_stages_without_the_kind_lists_nothing(infrahub):
    code, stdout, stderr = run(["stages"], infrahub)
    assert code == 1 and stdout == ""
    code, doc = run_json(["stages"], infrahub)
    assert code == 1 and "stages" not in doc and doc["subject"] == {"scope": SCOPE}
    assert [(f["rule"], f["object"], f["step"]) for f in doc["findings"]] == [
        ("stage.kind.absent", "FylgjaStage", "resolve")]


def test_stages_with_no_open_proposed_change(infrahub):
    recorded = serve_recorded(infrahub, "golden.json")
    infrahub.default_operations["ProposedChanges"] = lambda *_: {"data": {"CoreProposedChange": {"count": 0,
                                                                                                 "edges": []}}}
    assert "ProposedChanges" in recorded["default"]

    code, stdout, _ = run(["stages", "--branch", "other"], infrahub)
    assert (code, stdout) == (0, "branch other: no open proposed change\n")
    code, stdout, _ = run(["stages"], infrahub)
    assert (code, stdout) == (0, "no open proposed change\n")


def test_stages_when_infrahub_refuses_the_credential(infrahub):
    serve_recorded(infrahub, "golden.json")
    code, doc = run_json(["stages"], infrahub, {**ENVIRON, "INFRAHUB_API_TOKEN": "another-token"})
    assert code == 2
    [f] = doc["findings"]
    assert (f["rule"], f["object"], f["step"]) == ("operation.failed", "stage.list", "resolve")
    assert "another-token" not in json.dumps(doc)


# schema-check


def test_schema_check_names_what_it_verified(infrahub):
    """Conformant: the library's commit and every kind of the table, then the stage kind on the
    default branch, absent from the recorded schema; no object query."""
    code, stdout, stderr = run(["schema-check", "--branch", "fylgja-fixture"], infrahub)

    assert code == 0 and stderr == ""
    kinds = ", ".join(t.kind for t in mapping.TABLES)
    assert stdout.splitlines() == [
        f"conformant with opsmill/schema-library@26336e9: {kinds}",
        "stages: FylgjaStage absent from the default branch (load schema/fylgja-stage.yaml; needed only by --stage, "
        "stage list and stage plan)",
    ]
    assert {r["path"] for r in infrahub.requests} == {"/api/schema"}

    code, doc = run_json(["schema-check", "--branch", "fylgja-fixture"], infrahub)
    assert [k["kind"] for k in doc["verified"]["kinds"]] == [t.kind for t in mapping.TABLES]
    assert doc["verified"]["stages"] == {"kind": "FylgjaStage", "present": False, "missing": [], "extension": False,
                                         "file": "schema/fylgja-stage.yaml"}


def test_schema_check_with_the_stage_kind(infrahub):
    serve_recorded(infrahub, "golden.json")
    infrahub.branches.add("fylgja-fixture")
    code, stdout, _ = run(["schema-check", "--branch", "fylgja-fixture"], infrahub)
    assert code == 0
    assert stdout.splitlines()[1] == "stages: FylgjaStage present on the default branch, with its extension"


def test_schema_check_refuses_a_branch_that_does_not_conform(infrahub):
    infrahub.schema = {**infrahub.schema, "nodes": [n for n in infrahub.schema["nodes"] if n["kind"] != "DcimCable"]}
    code, stdout, _ = run(["schema-check", "--branch", "fylgja-fixture"], infrahub)
    assert code == 1 and stdout == ""
    code, doc = run_json(["schema-check", "--branch", "fylgja-fixture"], infrahub)
    assert "verified" not in doc
    assert ("schema.kind.missing", "DcimCable") in [(f["rule"], f["object"]) for f in doc["findings"]]


def test_schema_check_of_a_missing_branch(infrahub):
    code, doc = run_json(["schema-check", "--branch", "nosuch"], infrahub)
    assert code == 2
    [f] = doc["findings"]
    assert f["rule"] == "operation.failed" and "nosuch" in f["message"]


def test_an_unknown_command_is_refused(infrahub, capsys):
    assert adapter.main(["write"], io.StringIO(), io.StringIO(), adapter.Env(environ={})) == 2
    assert infrahub.requests == []
