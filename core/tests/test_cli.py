"""The thin CLI, fylgja-core (D-026), against the fake API 1 server: each command's requests
(the fake holds each to the OpenAPI document), its text and its --json output (each document
held to its schema), and its exit code: 0 ok, 1 a negative verdict, 2 a problem, a transport
failure or a usage failure, 3 a twin left dirty. No output ever holds the token. An https://
address is verified against the CA file FYLGJA_API_CA names, over a real server."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
import tls
import yaml
from fake_api import (
    ADDRESS,
    AT,
    BLUEPRINT,
    BLUEPRINT_FILE,
    BLUEPRINT_ID,
    BUNDLE,
    BUNDLE_ID,
    CAPACITY,
    COMPILE_RESULT,
    DESTROY_RUN_ID,
    ENDED_AT,
    EVENTS,
    MANIFEST,
    NOT_HELD,
    PUSH_REFUSED,
    RESTART_REQUIRED,
    RUN_ID,
    STEP_TO,
    TOKEN,
    TWIN,
    UNTRUSTED,
    VERSION,
    FakeAPI,
    application,
    check_component,
    cut,
    event_stream,
    last_step,
    ok,
    record,
    refuse,
    run,
    step_plan,
    unreachable,
    untrusted,
    verification,
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
    "Stepping: False",
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
    monkeypatch.delenv("FYLGJA_API_CA", raising=False)


def fylgja(capsys: pytest.CaptureFixture[str], api: FakeAPI | None, *argv: str) -> Result:
    """Run the CLI against `api` and capture what it wrote; the token is in neither stream, and
    every request and answer held to the OpenAPI document. A watch reconnects without waiting."""
    code = cli.main(list(argv), transport=api.transport if api is not None else None, sleep=lambda s: None)
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


BAD_CA = "FYLGJA_API_CA names no file of CA certificates that can be read"
NO_CA = "FYLGJA_API_CA names the CA file an https:// address is verified against"


def test_an_address_a_token_and_a_ca_file_are_refused_in_one_pass(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FYLGJA_API_ADDRESS", "a b:80")
    monkeypatch.setenv("FYLGJA_API_TOKEN", "sekrit\n")
    monkeypatch.setenv("FYLGJA_API_CA", str(tmp_path / "missing.pem"))
    r = fylgja(capsys, FakeAPI(), "twin", "list")
    assert (r.code, r.err.splitlines()) == (
        2, ["FYLGJA_API_ADDRESS is not an http(s):// URL or host:port", BAD_TOKEN, BAD_CA])


@pytest.mark.parametrize("fault", ["missing", "prose"])
def test_a_ca_file_that_cannot_be_read_exits_2_naming_the_variable_before_any_request(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fault: str
) -> None:
    ca = tmp_path / "ca.pem"
    if fault == "prose":
        ca.write_text("sekrit prose, and no certificate\n")
    monkeypatch.setenv("FYLGJA_API_CA", str(ca))
    api = FakeAPI()
    r = fylgja(capsys, api, "twin", "list")
    assert r == Result(2, "", f"{BAD_CA}\n")
    assert api.requests == []


def test_an_empty_ca_file_is_not_set(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    # `set -a; . local/.env` sets the variable empty where .env.example's line is left so.
    monkeypatch.setenv("FYLGJA_API_CA", "")
    api = FakeAPI().on("GET", "/v1/twins", ok({"twins": []}))
    assert fylgja(capsys, api, "twin", "list") == Result(0, "no twins\n", "")


def test_an_https_address_is_verified_against_the_ca_file_fylgja_api_ca_names(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cert, key = tls.pair(tmp_path / "tls")
    with tls.served(application({"/v1/twins": {"twins": [READY]}}), (cert, key)) as port:
        address = f"https://127.0.0.1:{port}"
        monkeypatch.setenv("FYLGJA_API_ADDRESS", address)
        # Without it, a call and a watch alike: one line saying the certificate is not trusted, one naming the variable.
        said = f"GET {address}/v1/version failed: the server's certificate is not trusted: {UNTRUSTED}\n{NO_CA}\n"
        assert fylgja(capsys, None, "twin", "list") == Result(2, "", said)
        assert fylgja(capsys, None, "run", "watch", RUN_ID) == Result(2, "", said)
        monkeypatch.setenv("FYLGJA_API_CA", str(cert))
        r = fylgja(capsys, None, "twin", "list")
    assert r == Result(0, "three-node: generation 1, observed 1, Ready True, phase pushed\n", "")


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["twin"],
        ["bogus", "list"],
        ["twin", "create", TWIN],
        ["twin", "create", TWIN, "--blueprint", "bp.json", "--bundle", BUNDLE_ID],
        ["twin", "step", TWIN],
        ["twin", "step", TWIN, "--bundle", BUNDLE_ID, "--driver", "containerlab"],
        ["twin", "step", TWIN, "--bundle", BUNDLE_ID, "--dry-run", "--no-wait"],
        ["run", "watch"],
        ["twin", "show", TWIN, "--frobnicate"],
    ],
    ids=["nothing", "no-verb", "no-such-noun", "no-source", "two-sources", "step-no-source", "step-driver",
         "step-dry-run-no-wait", "no-id", "unknown-option"],
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
        "Stepping: False",
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


# capacity show.


def test_capacity_show_renders_a_line_per_host_then_pending_and_twins(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeAPI().on("GET", "/v1/capacity", ok(CAPACITY))
    r = fylgja(capsys, api, "capacity", "show")
    assert (r.code, r.lines()) == (0, [
        "host: cpu 10 of 10 free, memory 25907 of 31065 MiB free",
        "pending: 0 nodes, 0 CPU, 0 MiB",
        "twins: 0",
    ])
    r = fylgja(capsys, api, "capacity", "show", "--json")
    assert (r.code, r.json()) == (0, CAPACITY)


def test_capacity_show_with_no_host_prints_pending_and_twins_alone(capsys: pytest.CaptureFixture[str]) -> None:
    doc = {**CAPACITY, "hosts": [], "pending": {"nodes": 3, "cpu": 1.5, "memory_mb": 6144}, "twins": 2}
    api = FakeAPI().on("GET", "/v1/capacity", ok(doc))
    r = fylgja(capsys, api, "capacity", "show")
    assert (r.code, r.lines()) == (0, ["pending: 3 nodes, 1.5 CPU, 6144 MiB", "twins: 2"])


def test_capacity_show_on_a_503_exits_2_with_the_problems_lines(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeAPI().on("GET", "/v1/capacity", refuse(503, "capacity.unread", "The runtime cannot be read."))
    r = fylgja(capsys, api, "capacity", "show")
    assert (r.code, r.out, r.err) == (2, "", "503 capacity.unread: The runtime cannot be read.\n")


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
                           f"GET {RUN_PATH}/events", f"GET {RUN_PATH}"]


def test_the_cli_keeps_no_copy_of_the_following() -> None:
    # Following a write to its verdict is the client library's `follow` (D-084).
    assert [name for name in ("Settled", "_settle", "_phase", "_run_of", "_ended") if hasattr(cli, name)] == []
    assert "watch_twin" not in Path(cli.__file__).read_text()


def test_a_twin_with_no_run_to_follow_exits_2_saying_so(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeAPI()
    api.on("PUT", TWIN_PATH, ok(record(), 201, CREATED))
    api.on("GET", TWIN_PATH, watch(READY))
    api.on("GET", "/v1/runs", ok({"runs": [run("destroy", run_id=DESTROY_RUN_ID)]}))
    r = fylgja(capsys, api, "twin", "create", TWIN, "--bundle", BUNDLE_ID, "--driver", "containerlab")
    assert r == Result(2, "", "twin three-node has no create run\n")


def test_a_twin_deleted_while_it_is_created_exits_by_the_create_runs_verdict(
    capsys: pytest.CaptureFixture[str],
) -> None:
    api = creating(FakeAPI(), record(2, 2, 1, deleting=True, run_id=RUN_ID), deleted=True, status="failed")
    r = fylgja(capsys, api, "twin", "create", TWIN, "--bundle", BUNDLE_ID, "--driver", "containerlab")
    assert r.code == 1
    assert r.lines()[1] == f"deletion requested at {ENDED_AT}"


COMPILED = record(2, 1, 0, phase="compiled", run_id=RUN_ID)


def test_a_waiting_create_rides_through_a_server_gone_between_two_streams(capsys: pytest.CaptureFixture[str]) -> None:
    api = creating(FakeAPI()).on("GET", TWIN_PATH, watch(COMPILED), unreachable, watch(READY))
    r = fylgja(capsys, api, "twin", "create", TWIN, "--bundle", BUNDLE_ID, "--driver", "containerlab")
    assert r.code == 0 and r.lines()[-1] == "verdict: ok"
    # Said once, at the first early end: the stream's, then a server refusing the connection.
    assert r.err.splitlines() == ["three-node: compiled",
                                  f"GET http://127.0.0.1:7650{TWIN_PATH} ended before its end; reconnecting"]
    assert api.calls() == [f"PUT {TWIN_PATH}"] + [f"GET {TWIN_PATH}"] * 3 + [f"GET {RUN_PATH}"]
    api = creating(FakeAPI()).on("GET", TWIN_PATH, watch(COMPILED), unreachable, watch(READY))
    r = fylgja(capsys, api, "--json", "twin", "create", TWIN, "--bundle", BUNDLE_ID, "--driver", "containerlab")
    assert (r.code, r.json(), r.err) == (0, run(), "")


def test_a_watch_never_resumed_exits_2_naming_the_call(capsys: pytest.CaptureFixture[str]) -> None:
    api = creating(FakeAPI()).on("GET", TWIN_PATH, watch(COMPILED), watch())
    r = fylgja(capsys, api, "twin", "create", TWIN, "--bundle", BUNDLE_ID, "--driver", "containerlab")
    assert (r.code, r.out) == (2, "")
    assert r.err.splitlines()[-1] == (f"GET http://127.0.0.1:7650{TWIN_PATH} ended before its end; "
                                      "not resumed after 15 reconnects")
    assert api.calls() == [f"PUT {TWIN_PATH}"] + [f"GET {TWIN_PATH}"] * 16


def test_a_waiting_create_whose_watch_reconnects_to_a_certificate_not_trusted_exits_2_naming_fylgja_api_ca(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FYLGJA_API_ADDRESS", "https://core.example")
    api = creating(FakeAPI()).on("GET", TWIN_PATH, watch(COMPILED), untrusted)
    r = fylgja(capsys, api, "twin", "create", TWIN, "--bundle", BUNDLE_ID, "--driver", "containerlab")
    assert (r.code, r.out) == (2, "")
    assert r.err.splitlines() == [
        "three-node: compiled",
        f"GET https://core.example{TWIN_PATH} ended before its end; reconnecting",
        f"GET https://core.example{TWIN_PATH} failed: the server's certificate is not trusted: {UNTRUSTED}",
        NO_CA,
    ]
    assert api.calls() == [f"PUT {TWIN_PATH}"] + [f"GET {TWIN_PATH}"] * 2  # not opened again after it


def test_a_twin_gone_between_two_streams_of_a_waiting_create_is_the_servers_refusal(
    capsys: pytest.CaptureFixture[str],
) -> None:
    api = creating(FakeAPI()).on("GET", TWIN_PATH, cut("WatchEvent", [("MODIFIED", None, {"type": "MODIFIED",
                                                                                            "object": COMPILED})]),
                                 refuse(404, "twin.not_found", "No twin is named three-node."))
    r = fylgja(capsys, api, "twin", "create", TWIN, "--bundle", BUNDLE_ID, "--driver", "containerlab")
    assert (r.code, r.out) == (2, "")
    assert r.err.splitlines()[-1] == "404 twin.not_found: No twin is named three-node."


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


# twin step.

STEPPED = record(9, 2, 2, phase="flows", ready=("True", "twin.ready"), nodes=True, last_step=last_step())
STEP_LINE = f"last step: stepped {BUNDLE_ID[:12]} -> {STEP_TO[:12]} at flows"


def stepping(api: FakeAPI, *records: dict[str, Any], status: str = "ok") -> FakeAPI:
    """A step of the three-node twin: the record its new spec answered, its watch, and its step run."""
    found = [PUSH_REFUSED] if status != "ok" else []
    return (
        api.on("PUT", TWIN_PATH, ok(record(5, 2, 1, phase="pushed", ready=("True", "twin.ready"), nodes=True),
                                    headers={"ETag": '"5"'}))
        .on("GET", TWIN_PATH, watch(*records))
        .on("GET", RUN_PATH, ok(run("step", status=status, findings=found)))
    )


def test_twin_step_files_the_blueprint_writes_the_spec_of_a_twin_that_exists_and_waits(
    capsys: pytest.CaptureFixture[str],
) -> None:
    api = FakeAPI()
    api.on("POST", "/v1/blueprints", ok({"id": BLUEPRINT_ID}))
    running = record(6, 2, 1, phase="pushed", ready=("False", "twin.stepping"), nodes=True, run_id=RUN_ID,
                     last_step=last_step("running", "planned"))
    stepping(api, running, record(7, 2, 1, phase="applied", ready=("False", "twin.stepping"), nodes=True,
                                  run_id=RUN_ID, last_step=last_step("running", "applied")),
             record(8, 2, 1, phase="flows", ready=("False", "twin.stepping"), nodes=True, run_id=RUN_ID,
                    last_step=last_step("running", "flows")), STEPPED)
    r = fylgja(capsys, api, "twin", "step", TWIN, "--blueprint", str(BLUEPRINT_FILE))
    assert r.code == 0
    assert api.calls() == ["POST /v1/blueprints", f"PUT {TWIN_PATH}", f"GET {TWIN_PATH}", f"GET {RUN_PATH}"]
    put = api.last("PUT", TWIN_PATH)
    # A partial spec with no driver, of a twin that exists: If-Match * refuses to create one.
    assert put.headers["if-match"] == "*" and "if-none-match" not in put.headers
    assert json.loads(put.content) == {"spec": {"blueprint_id": BLUEPRINT_ID}}
    assert put.url.params.multi_items() == []
    assert api.last("GET", TWIN_PATH).url.params.multi_items() == [("watch", "true"), ("since_revision", "5")]
    assert r.lines() == [
        "twin three-node: generation 2, observed 2",
        "Ready: True (twin.ready)",
        "Stepping: False",
        "phase: flows",
        f"bundle: {BUNDLE_ID}",
        STEP_LINE,
        "nodes:",
        "  n1 172.20.1.11",
        "  n2 172.20.1.12 via bastion.example",
        "  n3 no address yet",
        f"run {RUN_ID}: step of twin three-node, ended",
        f"asked by alice at {AT}, ended at {ENDED_AT}",
        "verdict: ok",
    ]
    # Until applied a step records its phases in last_step alone, the record's phase still the running twin's; the
    # record that settles the run prints no phase.
    assert r.err.splitlines() == ["three-node: planned", "three-node: applied", "three-node: flows"]


@pytest.mark.parametrize(("status", "code"), [("ok", 0), ("rejected", 1), ("failed", 1), ("diverged", 3)])
def test_twin_steps_exit_code_is_its_runs_verdict(capsys: pytest.CaptureFixture[str], status: str, code: int) -> None:
    if status == "rejected":  # refused after planned: the record never moved past the running twin's phase
        running = record(6, 2, 1, phase="flows", ready=("False", "twin.stepping"), nodes=True, run_id=RUN_ID,
                         last_step=last_step("running", "planned"))
        ended = record(9, 2, 2, phase="flows", ready=("False", "step.restart.required"), nodes=True,
                       last_step=last_step("rejected", "planned"))
    else:
        running = record(6, 2, 1, phase="applied", ready=("False", "twin.stepping"), nodes=True, run_id=RUN_ID,
                         last_step=last_step("running", "applied"))
        ended = record(9, 2, 2, phase="pushed", ready=("False", "step.diverged"), nodes=True,
                       diverged="step.diverged", last_step=last_step("diverged", "applied"))
    api = stepping(FakeAPI(), running, ended, status=status)
    r = fylgja(capsys, api, "twin", "step", TWIN, "--bundle", STEP_TO, "--allow-restart")
    assert r.code == code
    assert json.loads(api.last("PUT", TWIN_PATH).content) == {"spec": {"bundle_id": STEP_TO, "allow_restart": True}}
    assert r.lines()[-1 if status == "ok" else -2] == f"verdict: {status}"
    if status == "rejected":
        assert r.lines()[1:3] == ["Ready: False (step.restart.required)", "Stepping: False"]
        assert f"last step: rejected {BUNDLE_ID[:12]} -> {STEP_TO[:12]} at planned" in r.lines()
        # The settling record's phase is the running twin's, `flows`, which this run never reached: no line says it.
        assert r.err.splitlines() == ["three-node: planned"]
        return
    assert r.lines()[1:4] == ["Ready: False (step.diverged)", "Stepping: False", "Diverged: True (step.diverged)"]
    assert f"last step: diverged {BUNDLE_ID[:12]} -> {STEP_TO[:12]} at applied" in r.lines()
    assert r.err.splitlines() == ["three-node: applied"]


def test_twin_step_waits_for_the_create_a_twin_whose_create_never_applied_runs_again(
    capsys: pytest.CaptureFixture[str],
) -> None:
    api = stepping(FakeAPI(), record(8, 2, 2, phase="pushed", ready=("True", "twin.ready"), nodes=True))
    api.on("GET", "/v1/runs", ok({"runs": [run(), run("destroy", run_id=DESTROY_RUN_ID)]}))
    r = fylgja(capsys, api, "twin", "step", TWIN, "--bundle", BUNDLE_ID)
    assert r.code == 0 and f"run {RUN_ID}: create of twin three-node, ended" in r.lines()
    assert api.calls() == [f"PUT {TWIN_PATH}", f"GET {TWIN_PATH}", "GET /v1/runs"]


def test_twin_step_of_the_spec_the_twin_has_starts_no_run_and_waits_for_none(
    capsys: pytest.CaptureFixture[str],
) -> None:
    api = FakeAPI().on("PUT", TWIN_PATH, ok(STEPPED, headers={"ETag": '"9"'}))
    r = fylgja(capsys, api, "twin", "step", TWIN, "--bundle", STEP_TO)
    assert (r.code, r.lines()[-1]) == (0, "the twin's spec is this already: no run started")
    assert STEP_LINE in r.lines() and api.calls() == [f"PUT {TWIN_PATH}"]


def test_twin_step_no_wait_writes_the_spec_and_prints_the_record(capsys: pytest.CaptureFixture[str]) -> None:
    api = stepping(FakeAPI(), STEPPED)
    r = fylgja(capsys, api, "--json", "twin", "step", TWIN, "--bundle", STEP_TO, "--no-wait")
    assert (r.code, r.json()["generation"]) == (0, 2)
    assert api.calls() == [f"PUT {TWIN_PATH}"]


@pytest.mark.parametrize(("status", "code"), [("ok", 0), ("rejected", 1)])
def test_twin_step_dry_run_prints_the_plan_and_each_change_and_exits_by_its_verdict(
    capsys: pytest.CaptureFixture[str], status: str, code: int
) -> None:
    api = FakeAPI().on("PUT", TWIN_PATH, ok(step_plan(status)))
    r = fylgja(capsys, api, "twin", "step", TWIN, "--bundle", STEP_TO, "--dry-run")
    assert r.code == code
    assert api.calls() == [f"PUT {TWIN_PATH}"]
    put = api.last("PUT", TWIN_PATH)
    assert put.url.params.multi_items() == [("dry_run", "true")] and put.headers["if-match"] == "*"
    found = [f"  error step.restart.required n3: {RESTART_REQUIRED['message']}"] if status != "ok" else []
    assert r.lines() == [
        f"deployment: {step_plan()['deployment']['id']}",
        f"verdict: {status}",
        *found,
        "changes:",
        "  n1: kept",
        "  n2: recabled (links)",
        "  n3: recreated (image, links)",
        "  link added: n2:e1-2 -- n3:eth1",
        "  link removed: n2:e1-2 -- n3:e1-1",
    ]
    r = fylgja(capsys, api, "--json", "twin", "step", TWIN, "--bundle", STEP_TO, "--dry-run")
    assert (r.code, r.json()) == (code, step_plan(status))


def test_twin_step_of_a_diverged_twin_is_the_servers_refusal(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeAPI().on("PUT", TWIN_PATH, refuse(409, "twin.diverged",
                                                "Twin three-node is diverged; it accepts only deletion."))
    r = fylgja(capsys, api, "twin", "step", TWIN, "--bundle", STEP_TO)
    assert (r.code, r.err) == (2, "409 twin.diverged: Twin three-node is diverged; it accepts only deletion.\n")


def test_twin_show_names_a_diverged_twins_conditions_and_its_last_step(capsys: pytest.CaptureFixture[str]) -> None:
    doc = record(9, 2, 2, ready=("False", "step.diverged"), diverged="step.diverged",
                 last_step=last_step("diverged", "pushed"))
    api = FakeAPI().on("GET", TWIN_PATH, ok(doc, headers={"ETag": '"9"'}))
    assert fylgja(capsys, api, "twin", "show", TWIN).lines() == [
        "twin three-node: generation 2, observed 2",
        "Ready: False (step.diverged)",
        "Stepping: False",
        "Diverged: True (step.diverged)",
        "phase: none",
        "bundle: none",
        f"last step: diverged {BUNDLE_ID[:12]} -> {STEP_TO[:12]} at pushed",
        "nodes: none",
    ]


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


def test_twin_destroy_whose_watch_is_cut_and_then_answered_404_reads_the_destroy_run(
    capsys: pytest.CaptureFixture[str],
) -> None:
    destroyed = record(6, 2, 1, deleting=True, phase="destroyed", run_id=DESTROY_RUN_ID)
    api = destroying(FakeAPI(), status="unclean")
    api.on("GET", TWIN_PATH, cut("WatchEvent", [("MODIFIED", None, {"type": "MODIFIED", "object": destroyed})]),
           refuse(404, "twin.not_found", "No twin is named three-node."))
    r = fylgja(capsys, api, "twin", "destroy", TWIN)
    assert (r.code, r.lines()[0], r.lines()[-2]) == (3, "twin three-node deleted", "verdict: unclean")
    assert r.err.splitlines() == ["three-node: destroyed",
                                  f"GET http://127.0.0.1:7650{TWIN_PATH} failed: connection reset; reconnecting"]
    assert api.calls() == [f"DELETE {TWIN_PATH}", f"GET {TWIN_PATH}", f"GET {TWIN_PATH}", f"GET {DESTROY_PATH}"]


def test_twin_destroy_gone_between_two_streams_prints_the_destroy_run_and_no_record_it_saw(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The deletion's answer names the twin's last run, a create; the record the loop wrote next names the destroy run.
    destroyed = record(6, 2, 1, deleting=True, phase="destroyed", run_id=DESTROY_RUN_ID)
    unclean = run("destroy", status="unclean", findings=[PUSH_REFUSED], run_id=DESTROY_RUN_ID)
    streamed = cut("WatchEvent", [("MODIFIED", None, {"type": "MODIFIED", "object": destroyed})])
    gone = refuse(404, "twin.not_found", "No twin is named three-node.")

    def api() -> FakeAPI:
        return (destroying(FakeAPI(), run_id=RUN_ID, status="unclean").on("GET", TWIN_PATH, streamed, gone)
                .on("GET", RUN_PATH, ok(run())).on("GET", "/v1/runs", ok({"runs": [unclean, run()]})))

    served = api()
    r = fylgja(capsys, served, "twin", "destroy", TWIN)
    assert r.code == 3
    assert served.calls() == [f"DELETE {TWIN_PATH}", f"GET {TWIN_PATH}", f"GET {TWIN_PATH}", f"GET {DESTROY_PATH}"]
    assert r.lines() == [
        "twin three-node deleted",
        f"run {DESTROY_RUN_ID}: destroy of twin three-node, ended",
        f"asked by alice at {AT}, ended at {ENDED_AT}",
        "verdict: unclean",
        "  error push.refused n1: The node refused the configuration: commit failed.",
    ]
    assert r.err.splitlines() == ["three-node: destroyed",
                                  f"GET http://127.0.0.1:7650{TWIN_PATH} failed: connection reset; reconnecting"]
    r = fylgja(capsys, api(), "--json", "twin", "destroy", TWIN)
    assert (r.code, r.json(), r.err) == (3, unclean, "")


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
        "Stepping: False",
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


def test_run_get_names_a_restore_by_its_operation(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeAPI().on("GET", RUN_PATH, ok(run(operation="restore")))
    r = fylgja(capsys, api, "run", "get", RUN_ID)
    assert (r.code, r.lines()[:3]) == (0, [f"run {RUN_ID}: restore of twin three-node, ended",
                                           f"asked by alice at {AT}, ended at {ENDED_AT}", "verdict: ok"])


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
        "  findings.version.unsupported at /findings_version: version '2'; only version 1 is read",
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
    # The stream, then the page that says the run has ended.
    assert api.calls() == [f"GET {RUN_PATH}/events", f"GET {RUN_PATH}/events", f"GET {RUN_PATH}"]
    stream, page = (r.headers["accept"] for r in api.requests if r.url.path == f"{RUN_PATH}/events")
    assert (stream, page) == ("text/event-stream", "application/json, application/problem+json")
    r = fylgja(capsys, api, "--json", "run", "watch", RUN_ID)
    assert (r.code, r.json()) == (1, EVENTS)
    for doc in r.json():
        check_component("Event", doc)


def test_run_watch_rides_through_a_cut_printing_each_event_once(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeAPI()
    api.on("GET", f"{RUN_PATH}/events", cut("Event", [(None, str(e["seq"]), e) for e in EVENTS[:2]]),
           event_stream(*EVENTS[2:]))
    api.on("GET", RUN_PATH, ok(run(status="failed", findings=[PUSH_REFUSED])))
    r = fylgja(capsys, api, "run", "watch", RUN_ID)
    assert (r.code, r.lines()) == (1, [
        f"1 {AT} compile started",
        f"2 {AT} compile done 0.25s",
        f"3 {ENDED_AT} push failed n1 1.5s push.refused",
        "verdict: failed",
        "  error push.refused n1: The node refused the configuration: commit failed.",
    ])
    assert r.err == f"GET http://127.0.0.1:7650{RUN_PATH}/events failed: connection reset; reconnecting\n"
    assert api.calls() == [f"GET {RUN_PATH}/events"] * 3 + [f"GET {RUN_PATH}"]
    assert api.last("GET", f"{RUN_PATH}/events").url.params.multi_items() == [("after", "3")]


def test_run_watch_of_a_run_with_no_verdict_exits_2_saying_so(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeAPI()
    api.on("GET", f"{RUN_PATH}/events", event_stream(*EVENTS))
    api.on("GET", RUN_PATH, ok(run(state="running")))
    r = fylgja(capsys, api, "run", "watch", RUN_ID)
    assert r.code == 2
    assert r.err.splitlines()[-1] == f"run {RUN_ID} is running, with no verdict"
    r = fylgja(capsys, api, "--json", "run", "watch", RUN_ID)
    assert (r.code, r.out, r.err) == (2, "", f"run {RUN_ID} is running, with no verdict\n")


def test_run_watch_json_of_a_verdict_of_another_findings_version_prints_the_events_and_exits_2(
    capsys: pytest.CaptureFixture[str],
) -> None:
    events = event_stream(*EVENTS)

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/version":
            return httpx.Response(200, json=VERSION)
        if request.url.path == f"{RUN_PATH}/events":
            return events(request)
        doc = run()
        doc["verdict"]["findings_version"] = "2"
        return httpx.Response(200, json=doc)

    code = cli.main(["--json", "run", "watch", RUN_ID], transport=httpx.MockTransport(handle))
    captured = capsys.readouterr()
    assert (code, json.loads(captured.out), captured.err.splitlines()) == (2, EVENTS, [
        f"run {RUN_ID}'s verdict is no findings 1 document:",
        "  findings.version.unsupported at /findings_version: version '2'; only version 1 is read",
    ])


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


def _diff(**changes: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {"from": BUNDLE_ID, "to": "b" * 64, "unchanged": False,
                           "nodes": {"added": [], "removed": [], "changed": []},
                           "links": {"added": [], "removed": []}, "probes": {"added": [], "removed": []}}
    for key, value in changes.items():
        doc[key] = {**doc[key], **value} if isinstance(value, dict) else value
    return doc


def test_bundle_diff_of_an_unchanged_pair_says_so(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeAPI().on("GET", f"/v1/bundles/{BUNDLE_ID}/diff/{'b' * 64}", ok(_diff(unchanged=True)))
    r = fylgja(capsys, api, "bundle", "diff", BUNDLE_ID, "b" * 64)
    assert (r.code, r.lines()) == (0, [f"diff {BUNDLE_ID} -> {'b' * 64}: unchanged"])


def test_bundle_diff_of_a_changed_pair_lists_each_change(capsys: pytest.CaptureFixture[str]) -> None:
    link = {"a": {"device": "n1", "interface": "ethernet-1/1"}, "b": {"device": "n2", "interface": "ethernet-1/1"}}
    other = {"a": {"device": "n2", "interface": "ethernet-1/2"}, "b": {"device": "n3", "interface": "ethernet-1/1"}}
    doc = _diff(nodes={"added": ["n4"], "removed": ["n3", "n5"],
                       "changed": [{"node": "n1", "reasons": ["mapping", "config"]}]},
                links={"added": [link], "removed": [link, other]},
                probes={"added": ["p1"], "removed": ["p2"]})
    api = FakeAPI().on("GET", f"/v1/bundles/{BUNDLE_ID}/diff/{'b' * 64}", ok(doc))
    r = fylgja(capsys, api, "bundle", "diff", BUNDLE_ID, "b" * 64)
    assert (r.code, r.lines()) == (0, [
        f"diff {BUNDLE_ID} -> {'b' * 64}",
        "nodes added: n4",
        "nodes removed: n3, n5",
        "node n1 changed: mapping, config",
        "links added: n1:ethernet-1/1 -- n2:ethernet-1/1",
        "links removed: n1:ethernet-1/1 -- n2:ethernet-1/1",
        "links removed: n2:ethernet-1/2 -- n3:ethernet-1/1",
        "probes added: p1",
        "probes removed: p2",
    ])
    r = fylgja(capsys, api, "--json", "bundle", "diff", BUNDLE_ID, "b" * 64)
    assert (r.code, r.json()) == (0, doc)


def test_bundle_get_names_the_nodes_that_carry_no_configuration(capsys: pytest.CaptureFixture[str]) -> None:
    nodes = [{k: v for k, v in n.items() if k != "config"} if n["name"] == "n2" else n
             for n in MANIFEST["nodes"]]
    doc = {"id": BUNDLE_ID, "manifest": {**MANIFEST, "nodes": nodes}}
    api = FakeAPI().on("GET", f"/v1/bundles/{BUNDLE_ID}", ok(doc))
    r = fylgja(capsys, api, "bundle", "get", BUNDLE_ID)
    assert (r.code, r.lines()) == (0, [
        f"bundle {BUNDLE_ID}",
        f"blueprint: {BLUEPRINT_ID}",
        "nodes: n1 (nokia_srlinux), n2 (nokia_srlinux), n3 (nokia_srlinux)",
        "unmanaged: n2",
        "links: 3, probes: 0",
    ])
    api = FakeAPI().on("GET", f"/v1/bundles/{BUNDLE_ID}", ok(BUNDLE))
    r = fylgja(capsys, api, "bundle", "get", BUNDLE_ID)
    assert not any(line.startswith("unmanaged") for line in r.lines())


# twin verify.


def test_twin_verify_ok_prints_the_counts_and_exits_0(capsys: pytest.CaptureFixture[str]) -> None:
    doc = verification("ok", counts=(7, 0, 0))
    api = FakeAPI().on("POST", f"{TWIN_PATH}/verifications", ok(doc))
    r = fylgja(capsys, api, "twin", "verify", TWIN)
    assert (r.code, r.err, r.lines()) == (0, "", ["verdict: ok", "  held 7, failed 0, skipped 0"])
    assert api.calls() == [f"POST {TWIN_PATH}/verifications"]
    assert fylgja(capsys, api, "twin", "verify", TWIN, "--json").json() == doc


def test_twin_verify_nonconforming_prints_the_findings_and_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeAPI().on("POST", f"{TWIN_PATH}/verifications",
                       ok(verification("nonconforming", [NOT_HELD], (6, 1, 0))))
    r = fylgja(capsys, api, "twin", "verify", TWIN)
    assert (r.code, r.err) == (1, "")
    assert r.lines()[:2] == ["verdict: nonconforming", "  held 6, failed 1, skipped 0"]
    assert "verify.host_name" in r.lines()[2] and "n1" in r.lines()[2] and len(r.lines()) == 3


def test_twin_verify_failed_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    unread = {"rule": "verify.node.unread", "severity": "error", "object": "n1", "message": "No answer from n1."}
    api = FakeAPI().on("POST", f"{TWIN_PATH}/verifications", ok(verification("failed", [unread], (5, 1, 1))))
    r = fylgja(capsys, api, "twin", "verify", TWIN)
    assert (r.code, r.lines()[0]) == (1, "verdict: failed")


def test_twin_verify_of_a_twin_not_running_is_a_problem_exit_2(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeAPI().on("POST", f"{TWIN_PATH}/verifications",
                       refuse(409, "twin.not_running", f"Twin {TWIN} has no applied deployment to read."))
    assert fylgja(capsys, api, "twin", "verify", TWIN) == Result(
        2, "", f"409 twin.not_running: Twin {TWIN} has no applied deployment to read.\n")
