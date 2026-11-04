"""The thin CLI, fylgja-core (D-026), against the fake API 1 server: each command's requests
(the fake holds each to the OpenAPI document), its text and its --json output (each document
held to its schema), and its exit code: 0 ok, 1 a negative verdict, 2 a problem, a transport
failure or a usage failure, 3 a twin left dirty. No output ever holds the token."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from fake_api import (
    ADDRESS,
    AT,
    BLUEPRINT,
    BLUEPRINT_FILE,
    BLUEPRINT_ID,
    BUNDLE,
    BUNDLE_ID,
    COMPILE_RESULT,
    DESTROY_RUN_ID,
    ENDED_AT,
    EVENTS,
    PUSH_REFUSED,
    RUN_ID,
    TOKEN,
    TWIN,
    VERSION,
    FakeAPI,
    check_component,
    event_stream,
    ok,
    record,
    refuse,
    run,
    unreachable,
    watch,
)

from fylgja_core import cli, schemas
from fylgja_core.findings import Finding

TWIN_PATH = f"/v1/twins/{TWIN}"
RUN_PATH = f"/v1/runs/{RUN_ID}"
DESTROY_PATH = f"/v1/runs/{DESTROY_RUN_ID}"
CREATED = {"Location": TWIN_PATH, "ETag": '"1"'}
READY = record(4, 1, 1, phase="pushed", ready=("True", None), nodes=True)
TWIN_TEXT = [
    "twin three-node: generation 1, observed 1",
    "Ready: True",
    "phase: pushed",
    f"bundle: {BUNDLE_ID}",
    "nodes:",
    "  n1 172.20.1.11",
    "  n2 172.20.1.12 via bastion.example",
    "  n3 no address yet",
]


@dataclass(frozen=True)
class Result:
    code: int
    out: str
    err: str

    def json(self) -> Any:
        return json.loads(self.out)

    def lines(self) -> list[str]:
        return self.out.splitlines()


@pytest.fixture(autouse=True)
def environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FYLGJA_API_ADDRESS", ADDRESS)
    monkeypatch.setenv("FYLGJA_API_TOKEN", TOKEN)


def fylgja(capsys: pytest.CaptureFixture[str], api: FakeAPI | None, *argv: str) -> Result:
    """Run the CLI against `api` and capture what it wrote; the token is in neither stream, and
    every request and answer held to the OpenAPI document."""
    code = cli.main(list(argv), transport=api.transport if api is not None else None)
    captured = capsys.readouterr()
    assert api is None or api.failures == [], api.failures
    assert TOKEN not in captured.out and TOKEN not in captured.err
    return Result(code, captured.out, captured.err)


def write_blueprint(tmp_path: Path, doc: Any, name: str = "bp.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(doc) if name.endswith(".json") else yaml.safe_dump(doc))
    return path


# The environment and the command line.


@pytest.mark.parametrize(
    ("unset", "lines"),
    [
        (["FYLGJA_API_TOKEN"], ["FYLGJA_API_TOKEN is not set"]),
        (["FYLGJA_API_ADDRESS"], ["FYLGJA_API_ADDRESS is not set"]),
        (["FYLGJA_API_ADDRESS", "FYLGJA_API_TOKEN"], ["FYLGJA_API_ADDRESS is not set", "FYLGJA_API_TOKEN is not set"]),
    ],
)
def test_a_variable_not_set_is_named_and_exits_2_before_any_request(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, unset: list[str], lines: list[str]
) -> None:
    for name in unset:
        monkeypatch.delenv(name)
    api = FakeAPI()
    r = fylgja(capsys, api, "twin", "list")
    assert (r.code, r.out, r.err.splitlines()) == (2, "", lines)
    assert api.requests == []


def test_an_empty_token_is_not_set(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FYLGJA_API_TOKEN", "")
    assert fylgja(capsys, FakeAPI(), "twin", "list") == Result(2, "", "FYLGJA_API_TOKEN is not set\n")


@pytest.mark.parametrize(
    ("address", "line"),
    [
        ("https://admin:s3cret@core.example",
         "FYLGJA_API_ADDRESS holds a login; the client's one credential is its token"),
        ("a b:80", "FYLGJA_API_ADDRESS is not an http(s):// URL or host:port"),
        ("http://[::1", "FYLGJA_API_ADDRESS is not an http(s):// URL or host:port"),
        ("http://core.example:x", "FYLGJA_API_ADDRESS is not an http(s):// URL or host:port"),
    ],
    ids=["login", "space", "unclosed", "port"],
)
def test_an_address_that_is_not_one_exits_2_without_repeating_it(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, address: str, line: str
) -> None:
    monkeypatch.setenv("FYLGJA_API_ADDRESS", address)
    api = FakeAPI()
    assert fylgja(capsys, api, "twin", "list") == Result(2, "", f"{line}\n")
    assert api.requests == []


BAD_TOKEN = "FYLGJA_API_TOKEN is not an RFC 6750 bearer token: letters, digits and -._~+/ with trailing ="


@pytest.mark.parametrize(
    "token",
    ["sekrit\r\nX-Evil: 1", "sekrit\r", "sekrit\n", "sekrit-t\u00f6k\u00e9n", "sekrit with space"],
    ids=["crlf", "cr", "lf", "non-ascii", "space"],
)
def test_a_token_that_is_no_bearer_token_exits_2_and_no_part_of_it_is_shown(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, token: str
) -> None:
    # A NUL cannot be in the environment; the client refuses one (test_client.py).
    monkeypatch.setenv("FYLGJA_API_TOKEN", token)
    api = FakeAPI()
    r = fylgja(capsys, api, "--json", "twin", "create", TWIN, "--bundle", BUNDLE_ID)
    assert r == Result(2, "", f"{BAD_TOKEN}\n")
    assert "sekrit" not in r.out + r.err and api.requests == []


def test_an_address_and_a_token_are_both_refused_in_one_pass(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FYLGJA_API_ADDRESS", "a b:80")
    monkeypatch.setenv("FYLGJA_API_TOKEN", "sekrit\n")
    r = fylgja(capsys, FakeAPI(), "twin", "list")
    assert (r.code, r.err.splitlines()) == (2, ["FYLGJA_API_ADDRESS is not an http(s):// URL or host:port", BAD_TOKEN])


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["twin"],
        ["bogus", "list"],
        ["twin", "create", TWIN],
        ["twin", "create", TWIN, "--blueprint", "bp.json", "--bundle", BUNDLE_ID],
        ["run", "watch"],
        ["twin", "show", TWIN, "--frobnicate"],
    ],
    ids=["nothing", "no-verb", "no-such-noun", "no-source", "two-sources", "no-id", "unknown-option"],
)
def test_a_usage_error_exits_2_with_the_usage(capsys: pytest.CaptureFixture[str], argv: list[str]) -> None:
    api = FakeAPI()
    r = fylgja(capsys, api, *argv)
    assert (r.code, r.out) == (2, "")
    assert "usage: fylgja-core" in r.err
    assert api.requests == []


def test_help_exits_0(capsys: pytest.CaptureFixture[str]) -> None:
    r = fylgja(capsys, None, "twin", "create", "--help")
    assert r.code == 0 and "usage: fylgja-core twin create" in r.out and "--no-wait" in r.out


# Problems, transport failures and a server of another API.


def test_a_problem_exits_2_with_its_status_rule_and_detail(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeAPI().on("GET", TWIN_PATH, refuse(401, "auth.token.unknown", "No principal holds the token."))
    r = fylgja(capsys, api, "twin", "show", TWIN)
    assert (r.code, r.out, r.err) == (2, "", "401 auth.token.unknown: No principal holds the token.\n")


def test_a_problems_findings_are_listed_and_json_prints_its_document(capsys: pytest.CaptureFixture[str]) -> None:
    faults = [Finding(rule="platform.unsupported", severity="error", object="n1", message="No such platform."),
              Finding(rule="config.missing", severity="error", message="The configuration is empty.")]
    api = FakeAPI().on("POST", "/v1/bundles", refuse(422, "bundle.rejected", "The blueprint does not compile.", faults))
    r = fylgja(capsys, api, "bundle", "build", BLUEPRINT_ID)
    assert (r.code, r.out) == (2, "")
    assert r.err.splitlines() == [
        "422 bundle.rejected: The blueprint does not compile.",
        "  error platform.unsupported n1: No such platform.",
        "  error config.missing: The configuration is empty.",
    ]
    r = fylgja(capsys, api, "--json", "bundle", "build", BLUEPRINT_ID)
    assert r.code == 2
    doc = r.json()
    assert list(schemas.validator("problem-1").iter_errors(doc)) == []
    assert (doc["status"], doc["rule"], doc["instance"], len(doc["findings"])) == (422, "bundle.rejected",
                                                                                  "/v1/bundles", 2)
    assert r.err.splitlines()[0] == "422 bundle.rejected: The blueprint does not compile."


def test_an_unreachable_server_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeAPI().on("GET", "/v1/version", unreachable)
    r = fylgja(capsys, api, "twin", "list")
    assert (r.code, r.out) == (2, "")
    assert r.err == "GET http://127.0.0.1:7650/v1/version failed: [Errno 111] Connection refused\n"


def test_anything_unforeseen_is_one_line_exit_2_and_never_the_token(capsys: pytest.CaptureFixture[str]) -> None:
    def boom(request: httpx.Request) -> httpx.Response:
        raise RuntimeError(f"boom while holding {TOKEN}")

    code = cli.main(["twin", "list"], transport=httpx.MockTransport(boom))
    assert (code, capsys.readouterr().err) == (2, "RuntimeError: boom while holding <token>\n")


def test_an_interrupt_exits_2_quietly(capsys: pytest.CaptureFixture[str]) -> None:
    def interrupted(request: httpx.Request) -> httpx.Response:
        raise KeyboardInterrupt

    code = cli.main(["twin", "list"], transport=httpx.MockTransport(interrupted))
    assert (code, *capsys.readouterr()) == (2, "", "")


def test_a_server_of_another_api_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={**VERSION, "api": "2"})

    code = cli.main(["twin", "list"], transport=httpx.MockTransport(handle))
    assert (code, capsys.readouterr().err) == (2, "the server speaks API '2'; this client speaks API 1\n")


# twin show and twin list.


def test_twin_show_renders_the_record(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeAPI().on("GET", TWIN_PATH, ok(READY, headers={"ETag": '"4"'}))
    r = fylgja(capsys, api, "twin", "show", TWIN)
    assert (r.code, r.lines(), r.err) == (0, TWIN_TEXT, "")
    assert api.calls() == [f"GET {TWIN_PATH}"]


def test_twin_show_names_the_ready_reason_the_run_and_a_deletion(capsys: pytest.CaptureFixture[str]) -> None:
    doc = record(5, 2, 1, ready=("False", "readiness.timeout"), run_id=DESTROY_RUN_ID, deleting=True)
    api = FakeAPI().on("GET", TWIN_PATH, ok(doc, headers={"ETag": '"5"'}))
    assert fylgja(capsys, api, "twin", "show", TWIN).lines() == [
        "twin three-node: generation 2, observed 1",
        f"deletion requested at {ENDED_AT}",
        "Ready: False (readiness.timeout)",
        "phase: none",
        "bundle: none",
        f"run: {DESTROY_RUN_ID}",
        "nodes: none",
    ]
    api.on("GET", TWIN_PATH, ok(record(), headers={"ETag": '"1"'}))
    assert fylgja(capsys, api, "twin", "show", TWIN).lines()[1] == "Ready: not reported"


@pytest.mark.parametrize("argv", [["--json", "twin", "show", TWIN], ["twin", "show", TWIN, "--json"]],
                         ids=["before", "after"])
def test_twin_show_json_prints_the_record(capsys: pytest.CaptureFixture[str], argv: list[str]) -> None:
    api = FakeAPI().on("GET", TWIN_PATH, ok(READY, headers={"ETag": '"4"'}))
    r = fylgja(capsys, api, *argv)
    assert (r.code, r.json(), r.err) == (0, READY, "")
    assert list(schemas.validator("twin-record-1").iter_errors(r.json())) == []


def test_twin_list_renders_a_line_per_twin_and_json_the_records(capsys: pytest.CaptureFixture[str]) -> None:
    other = {**record(), "name": "two-node"}
    api = FakeAPI().on("GET", "/v1/twins", ok({"twins": [READY, other]}))
    r = fylgja(capsys, api, "twin", "list")
    assert (r.code, r.lines()) == (0, [
        "three-node: generation 1, observed 1, Ready True, phase pushed",
        "two-node: generation 1, observed 0, Ready not reported, phase none",
    ])
    r = fylgja(capsys, api, "twin", "list", "--json")
    assert (r.code, r.json()) == (0, [READY, other])
    assert all(list(schemas.validator("twin-record-1").iter_errors(doc)) == [] for doc in r.json())
    api.on("GET", "/v1/twins", ok({"twins": []}))
    assert fylgja(capsys, api, "twin", "list").lines() == ["no twins"]


# twin create.


def creating(api: FakeAPI, *records: dict[str, Any], status: str = "ok", deleted: bool = False) -> FakeAPI:
    """A create of the three-node twin: the record answered, its watch, and its run."""
    found = [PUSH_REFUSED] if status != "ok" else []
    return (
        api.on("PUT", TWIN_PATH, ok(record(run_id=RUN_ID), 201, CREATED))
        .on("GET", TWIN_PATH, watch(*records, deleted=deleted))
        .on("GET", RUN_PATH, ok(run(status=status, findings=found)))
    )


def test_twin_create_files_the_blueprint_writes_the_spec_create_only_and_waits(
    capsys: pytest.CaptureFixture[str],
) -> None:
    api = FakeAPI()
    api.on("POST", "/v1/blueprints", ok({"id": BLUEPRINT_ID}, 201, {"Location": f"/v1/blueprints/{BLUEPRINT_ID}"}))
    creating(api, record(2, 1, 0, phase="compiled", run_id=RUN_ID), record(3, 1, 0, phase="pushed", run_id=RUN_ID),
             READY)
    r = fylgja(capsys, api, "twin", "create", TWIN, "--blueprint", str(BLUEPRINT_FILE))
    assert r.code == 0
    assert api.calls() == ["POST /v1/blueprints", f"PUT {TWIN_PATH}", f"GET {TWIN_PATH}", f"GET {RUN_PATH}"]
    assert json.loads(api.last("POST", "/v1/blueprints").content) == BLUEPRINT
    put = api.last("PUT", TWIN_PATH)
    assert put.headers["if-none-match"] == "*" and "if-match" not in put.headers
    # A partial spec: the server fills the driver and allow_restart.
    assert json.loads(put.content) == {"spec": {"blueprint_id": BLUEPRINT_ID}}
    watched = api.last("GET", TWIN_PATH)
    assert watched.url.params.multi_items() == [("watch", "true"), ("since_revision", "1")]
    assert r.lines() == [*TWIN_TEXT, f"run {RUN_ID}: create of twin three-node, ended",
                         f"asked by alice at {AT}, ended at {ENDED_AT}", "verdict: ok"]
    assert r.err.splitlines() == ["three-node: compiled", "three-node: pushed"]


@pytest.mark.parametrize(
    ("status", "code"),
    [("ok", 0), ("rejected", 1), ("failed", 1), ("nonconforming", 1), ("unclean", 3), ("diverged", 3)],
)
def test_twin_creates_exit_code_is_its_runs_verdict(capsys: pytest.CaptureFixture[str], status: str, code: int) -> None:
    api = creating(FakeAPI(), record(2, 1, 1, ready=("False", "push.refused"), run_id=RUN_ID), status=status)
    r = fylgja(capsys, api, "twin", "create", TWIN, "--bundle", BUNDLE_ID, "--driver", "containerlab")
    assert r.code == code
    assert api.calls() == [f"PUT {TWIN_PATH}", f"GET {TWIN_PATH}", f"GET {RUN_PATH}"]
    assert json.loads(api.last("PUT", TWIN_PATH).content) == {"spec": {"bundle_id": BUNDLE_ID,
                                                                       "driver": "containerlab"}}
    assert r.lines()[-1 if status == "ok" else -2] == f"verdict: {status}"
    if status != "ok":
        assert r.lines()[-1] == "  error push.refused n1: The node refused the configuration: commit failed."


def test_twin_create_json_prints_the_run(capsys: pytest.CaptureFixture[str]) -> None:
    api = creating(FakeAPI(), READY, status="failed")
    r = fylgja(capsys, api, "--json", "twin", "create", TWIN, "--bundle", BUNDLE_ID, "--driver", "containerlab")
    assert (r.code, r.json(), r.err) == (1, run(status="failed", findings=[PUSH_REFUSED]), "")
    check_component("Run", r.json())


def test_twin_create_no_wait_writes_the_spec_and_prints_the_record(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeAPI().on("PUT", TWIN_PATH, ok(record(run_id=RUN_ID), 201, CREATED))
    argv = ["twin", "create", TWIN, "--bundle", BUNDLE_ID, "--driver", "clabernetes", "--allow-restart", "--no-wait"]
    r = fylgja(capsys, api, *argv)
    assert r.code == 0 and r.lines()[0] == "twin three-node: generation 1, observed 0"
    assert api.calls() == [f"PUT {TWIN_PATH}"]
    assert json.loads(api.last("PUT", TWIN_PATH).content) == {"spec": {"bundle_id": BUNDLE_ID, "driver": "clabernetes",
                                                                       "allow_restart": True}}
    r = fylgja(capsys, api, "--json", *argv)
    assert (r.code, r.json()) == (0, record(run_id=RUN_ID))


def test_twin_create_reads_the_newest_create_run_when_no_record_named_it(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeAPI()
    api.on("PUT", TWIN_PATH, ok(record(), 201, CREATED))
    api.on("GET", TWIN_PATH, watch(READY))
    older = run("destroy", run_id=DESTROY_RUN_ID)
    api.on("GET", "/v1/runs", ok({"runs": [run("destroy", run_id="01JB8ZZZZV4W6X7Y8Z9A0B1C2F"), run(), older]}))
    r = fylgja(capsys, api, "twin", "create", TWIN, "--bundle", BUNDLE_ID, "--driver", "containerlab")
    assert r.code == 0
    assert api.calls() == [f"PUT {TWIN_PATH}", f"GET {TWIN_PATH}", "GET /v1/runs"]
    assert api.last("GET", "/v1/runs").url.params.multi_items() == [("twin", TWIN)]


def test_twin_create_follows_a_run_not_yet_ended_to_its_verdict(capsys: pytest.CaptureFixture[str]) -> None:
    api = creating(FakeAPI(), READY)
    api.on("GET", RUN_PATH, ok(run(state="running")), ok(run(status="unclean", findings=[PUSH_REFUSED])))
    api.on("GET", f"{RUN_PATH}/events", event_stream(*EVENTS))
    r = fylgja(capsys, api, "twin", "create", TWIN, "--bundle", BUNDLE_ID, "--driver", "containerlab")
    assert r.code == 3
    assert api.calls() == [f"PUT {TWIN_PATH}", f"GET {TWIN_PATH}", f"GET {RUN_PATH}", f"GET {RUN_PATH}/events",
                           f"GET {RUN_PATH}"]


def test_a_twin_deleted_while_it_is_created_exits_by_the_create_runs_verdict(
    capsys: pytest.CaptureFixture[str],
) -> None:
    api = creating(FakeAPI(), record(2, 2, 1, deleting=True, run_id=RUN_ID), deleted=True, status="failed")
    r = fylgja(capsys, api, "twin", "create", TWIN, "--bundle", BUNDLE_ID, "--driver", "containerlab")
    assert r.code == 1
    assert r.lines()[1] == f"deletion requested at {ENDED_AT}"


def test_a_watch_that_ends_before_the_twin_settles_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    api = creating(FakeAPI(), record(2, 1, 0, phase="compiled", run_id=RUN_ID))
    r = fylgja(capsys, api, "twin", "create", TWIN, "--bundle", BUNDLE_ID, "--driver", "containerlab")
    assert (r.code, r.out) == (2, "")
    assert r.err.splitlines()[-1] == "the watch of twin three-node ended before the loop acted on generation 1"
    assert api.calls() == [f"PUT {TWIN_PATH}", f"GET {TWIN_PATH}"]


def test_a_twin_that_exists_is_the_servers_refusal(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeAPI().on("PUT", TWIN_PATH, refuse(412, "twin.exists", "A twin named three-node exists."))
    r = fylgja(capsys, api, "twin", "create", TWIN, "--bundle", BUNDLE_ID, "--driver", "containerlab")
    assert (r.code, r.err) == (2, "412 twin.exists: A twin named three-node exists.\n")


def test_a_blueprint_file_the_loader_refuses_exits_2_with_every_problem_and_sends_nothing(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    doc = json.loads(json.dumps(BLUEPRINT))
    doc["network"]["devices"].reverse()
    doc["probes"] = "none"
    path = write_blueprint(tmp_path, doc)
    api = FakeAPI()
    r = fylgja(capsys, api, "twin", "create", TWIN, "--blueprint", str(path))
    assert (r.code, r.out) == (2, "")
    assert r.err.splitlines() == [f"{path} is not a valid blueprint:",
                                  "  blueprint.invalid at /probes: 'none' is not of type 'array'"]
    assert api.requests == []
    doc["probes"] = []
    path = write_blueprint(tmp_path, doc)
    r = fylgja(capsys, api, "blueprint", "push", str(path))
    assert r.code == 2 and r.err.splitlines()[0] == f"{path} is not a valid blueprint:"
    assert all(line.startswith("  blueprint.unsorted at /network/") for line in r.err.splitlines()[1:])
    assert api.requests == []


def test_a_blueprint_file_that_cannot_be_read_exits_2(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    r = fylgja(capsys, FakeAPI(), "blueprint", "push", str(missing))
    assert (r.code, r.err) == (2, f"{missing}: No such file or directory\n")
    garbage = tmp_path / "garbage.json"
    garbage.write_text("{not json")
    r = fylgja(capsys, FakeAPI(), "blueprint", "push", str(garbage))
    assert r.code == 2 and r.err.startswith(f"{garbage} is not a document: ")


# twin destroy.


def destroying(api: FakeAPI, run_id: str = DESTROY_RUN_ID, status: str = "ok") -> FakeAPI:
    deleting = record(5, 2, 1, deleting=True, run_id=run_id)
    found = [PUSH_REFUSED] if status != "ok" else []
    return (
        api.on("DELETE", TWIN_PATH, ok(deleting, 202))
        .on("GET", TWIN_PATH, watch(record(6, 2, 1, deleting=True, phase="destroyed", run_id=DESTROY_RUN_ID),
                                    deleted=True))
        .on("GET", DESTROY_PATH, ok(run("destroy", status=status, findings=found, run_id=DESTROY_RUN_ID)))
    )


def test_twin_destroy_deletes_waits_for_deleted_and_exits_by_the_destroy_run(
    capsys: pytest.CaptureFixture[str],
) -> None:
    api = destroying(FakeAPI())
    r = fylgja(capsys, api, "twin", "destroy", TWIN)
    assert r.code == 0
    assert api.calls() == [f"DELETE {TWIN_PATH}", f"GET {TWIN_PATH}", f"GET {DESTROY_PATH}"]
    assert "if-match" not in api.last("DELETE", TWIN_PATH).headers
    assert api.last("GET", TWIN_PATH).url.params.multi_items() == [("watch", "true"), ("since_revision", "5")]
    assert r.lines() == ["twin three-node deleted", f"run {DESTROY_RUN_ID}: destroy of twin three-node, ended",
                         f"asked by alice at {AT}, ended at {ENDED_AT}", "verdict: ok"]
    assert r.err == "three-node: destroyed\n"


@pytest.mark.parametrize(("status", "code"), [("ok", 0), ("failed", 1), ("unclean", 3)])
def test_twin_destroys_exit_code_is_its_runs_verdict(
    capsys: pytest.CaptureFixture[str], status: str, code: int
) -> None:
    r = fylgja(capsys, destroying(FakeAPI(), status=status), "--json", "twin", "destroy", TWIN)
    assert r.code == code
    assert r.json() == run("destroy", status=status, run_id=DESTROY_RUN_ID,
                           findings=[PUSH_REFUSED] if status != "ok" else [])


def test_twin_destroy_of_a_twin_already_gone_reads_the_destroy_run(capsys: pytest.CaptureFixture[str]) -> None:
    api = destroying(FakeAPI()).on("GET", TWIN_PATH, refuse(404, "twin.not_found", "No twin is named three-node."))
    r = fylgja(capsys, api, "twin", "destroy", TWIN)
    assert (r.code, r.err, r.lines()[0]) == (0, "", "twin three-node deleted")
    assert api.calls() == [f"DELETE {TWIN_PATH}", f"GET {TWIN_PATH}", f"GET {DESTROY_PATH}"]


def test_twin_destroy_whose_teardown_kept_the_record_shows_it_and_does_not_say_deleted(
    capsys: pytest.CaptureFixture[str],
) -> None:
    kept = record(6, 2, 2, deleting=True, ready=("False", "destroy.failed"), run_id=DESTROY_RUN_ID)
    api = destroying(FakeAPI(), status="unclean").on("GET", TWIN_PATH, watch(kept))
    r = fylgja(capsys, api, "twin", "destroy", TWIN)
    assert r.code == 3 and "deleted" not in r.out
    assert r.lines() == [
        "twin three-node: generation 2, observed 2",
        f"deletion requested at {ENDED_AT}",
        "Ready: False (destroy.failed)",
        "phase: none",
        "bundle: none",
        f"run: {DESTROY_RUN_ID}",
        "nodes: none",
        f"run {DESTROY_RUN_ID}: destroy of twin three-node, ended",
        f"asked by alice at {AT}, ended at {ENDED_AT}",
        "verdict: unclean",
        "  error push.refused n1: The node refused the configuration: commit failed.",
    ]


def test_twin_destroy_during_a_create_finds_the_destroy_run_among_the_twins(
    capsys: pytest.CaptureFixture[str],
) -> None:
    api = destroying(FakeAPI(), run_id=RUN_ID)
    api.on("GET", TWIN_PATH, watch(record(6, 2, 1, deleting=True, run_id=RUN_ID), deleted=True))
    api.on("GET", RUN_PATH, ok(run(status="failed", findings=[PUSH_REFUSED])))
    api.on("GET", "/v1/runs", ok({"runs": [run("destroy", run_id=DESTROY_RUN_ID), run(status="failed")]}))
    r = fylgja(capsys, api, "twin", "destroy", TWIN)
    assert r.code == 0
    assert api.calls() == [f"DELETE {TWIN_PATH}", f"GET {TWIN_PATH}", f"GET {RUN_PATH}", "GET /v1/runs"]


def test_twin_destroy_no_wait_prints_the_record(capsys: pytest.CaptureFixture[str]) -> None:
    api = destroying(FakeAPI())
    r = fylgja(capsys, api, "twin", "destroy", TWIN, "--no-wait", "--json")
    assert (r.code, r.json()) == (0, record(5, 2, 1, deleting=True, run_id=DESTROY_RUN_ID))
    assert api.calls() == [f"DELETE {TWIN_PATH}"]


def test_twin_destroy_of_no_twin_is_the_servers_refusal(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeAPI().on("DELETE", TWIN_PATH, refuse(404, "twin.not_found", "No twin is named three-node."))
    assert fylgja(capsys, api, "twin", "destroy", TWIN) == Result(2, "", "404 twin.not_found: No twin is named "
                                                                         "three-node.\n")


# Runs.


def test_run_get_renders_the_run_and_its_verdict(capsys: pytest.CaptureFixture[str]) -> None:
    failed = run(status="failed", findings=[PUSH_REFUSED])
    api = FakeAPI().on("GET", RUN_PATH, ok(failed))
    r = fylgja(capsys, api, "run", "get", RUN_ID)
    assert (r.code, r.lines()) == (0, [
        f"run {RUN_ID}: create of twin three-node, ended",
        f"asked by alice at {AT}, ended at {ENDED_AT}",
        "verdict: failed",
        "  error push.refused n1: The node refused the configuration: commit failed.",
    ])
    r = fylgja(capsys, api, "run", "get", RUN_ID, "--json")
    assert (r.code, r.json()) == (0, failed)
    check_component("Run", r.json())


def test_run_get_of_a_run_in_flight_has_no_verdict(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeAPI().on("GET", RUN_PATH, ok(run(state="running")))
    assert fylgja(capsys, api, "run", "get", RUN_ID).lines() == [
        f"run {RUN_ID}: create of twin three-node, running", f"asked by alice at {AT}"]


def test_a_verdict_of_another_findings_version_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/version":
            return httpx.Response(200, json=VERSION)
        doc = run()
        doc["verdict"]["findings_version"] = "2"
        return httpx.Response(200, json=doc)

    code = cli.main(["run", "get", RUN_ID], transport=httpx.MockTransport(handle))
    assert (code, capsys.readouterr().err.splitlines()) == (2, [
        f"run {RUN_ID}'s verdict is no findings 1 document:",
        "  findings.version.unsupported at /findings_version: version '2'; this core reads 1",
    ])


def test_run_cancel_asks_and_prints_the_run_cancelling(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeAPI().on("POST", f"{RUN_PATH}/cancel", ok(run(state="cancelling"), 202))
    r = fylgja(capsys, api, "run", "cancel", RUN_ID)
    assert (r.code, r.lines()[0]) == (0, f"run {RUN_ID}: create of twin three-node, cancelling")
    assert api.calls() == [f"POST {RUN_PATH}/cancel"]
    api.on("POST", f"{RUN_PATH}/cancel", refuse(409, "run.ended", "The run has ended."))
    assert fylgja(capsys, api, "run", "cancel", RUN_ID) == Result(2, "", "409 run.ended: The run has ended.\n")


def test_run_watch_prints_each_event_and_exits_by_the_verdict(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeAPI()
    api.on("GET", f"{RUN_PATH}/events", event_stream(*EVENTS))
    api.on("GET", RUN_PATH, ok(run(status="failed", findings=[PUSH_REFUSED])))
    r = fylgja(capsys, api, "run", "watch", RUN_ID)
    assert (r.code, r.lines()) == (1, [
        f"1 {AT} compile started",
        f"2 {AT} compile done 0.25s",
        f"3 {ENDED_AT} push failed n1 1.5s push.refused",
        "verdict: failed",
        "  error push.refused n1: The node refused the configuration: commit failed.",
    ])
    assert api.calls() == [f"GET {RUN_PATH}/events", f"GET {RUN_PATH}"]
    assert api.last("GET", f"{RUN_PATH}/events").headers["accept"] == "text/event-stream"
    r = fylgja(capsys, api, "--json", "run", "watch", RUN_ID)
    assert (r.code, r.json()) == (1, EVENTS)
    for doc in r.json():
        check_component("Event", doc)


# Blueprints and bundles.


@pytest.mark.parametrize("name", ["bp.json", "bp.yaml"])
def test_blueprint_push_files_the_document_and_prints_its_id(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, name: str
) -> None:
    api = FakeAPI().on("POST", "/v1/blueprints", ok({"id": BLUEPRINT_ID}))
    path = write_blueprint(tmp_path, BLUEPRINT, name)
    r = fylgja(capsys, api, "blueprint", "push", str(path))
    assert (r.code, r.lines()) == (0, [f"blueprint {BLUEPRINT_ID}"])
    assert json.loads(api.last("POST", "/v1/blueprints").content) == BLUEPRINT
    r = fylgja(capsys, api, "blueprint", "push", str(path), "--json")
    assert (r.code, r.json()) == (0, {"id": BLUEPRINT_ID})
    check_component("Created", r.json())


def test_bundle_build_compiles_a_filed_blueprint(capsys: pytest.CaptureFixture[str]) -> None:
    result = {**COMPILE_RESULT, "findings": [{"rule": "omit.interface.unmappable", "severity": "warning",
                                              "object": "n1:ethernet-1/9", "message": "No such port."}]}
    api = FakeAPI().on("POST", "/v1/bundles", ok(result, 201, {"Location": f"/v1/bundles/{BUNDLE_ID}"}))
    r = fylgja(capsys, api, "bundle", "build", BLUEPRINT_ID)
    assert (r.code, r.lines()) == (0, [
        f"bundle {BUNDLE_ID}",
        f"blueprint: {BLUEPRINT_ID}",
        "nodes: n1 (nokia_srlinux), n2 (nokia_srlinux), n3 (nokia_srlinux)",
        "links: 3, probes: 0",
        "fidelity: 3 approximations, 0 omitted, 0 synthesized",
        "  warning omit.interface.unmappable n1:ethernet-1/9: No such port.",
    ])
    assert json.loads(api.last("POST", "/v1/bundles").content) == {"blueprint_id": BLUEPRINT_ID}
    r = fylgja(capsys, api, "--json", "bundle", "build", BLUEPRINT_ID)
    assert (r.code, r.json()) == (0, result)
    check_component("CompileResult", r.json())


def test_bundle_get_renders_the_manifest(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeAPI().on("GET", f"/v1/bundles/{BUNDLE_ID}", ok(BUNDLE))
    r = fylgja(capsys, api, "bundle", "get", BUNDLE_ID)
    assert (r.code, r.lines()) == (0, [
        f"bundle {BUNDLE_ID}",
        f"blueprint: {BLUEPRINT_ID}",
        "nodes: n1 (nokia_srlinux), n2 (nokia_srlinux), n3 (nokia_srlinux)",
        "links: 3, probes: 0",
    ])
    r = fylgja(capsys, api, "bundle", "get", BUNDLE_ID, "--json")
    assert (r.code, r.json()) == (0, BUNDLE)
    assert list(schemas.validator("bundle-1").iter_errors(r.json()["manifest"])) == []
