"""The core's client (`core.py`, T023) against a stub HTTP server answering recorded frame
sequences (`tests/data/frames/`, written by the Go server's own test harness): a detached
create then its read to completion, a refusal document, a running read's EOF, a 401, a
refused connection, and the faults `internal/api/client.go` and `internal/cli/failures.go`
word. The token is a sentinel, and no failure, answer or repr carries it."""

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from fylgja_orchestrator import core
from fylgja_orchestrator.core import Core, CoreFailure, File, RunRef
from fylgja_orchestrator.documents import findings

FRAMES = Path(__file__).resolve().parents[1] / "data" / "frames"
TOKEN = "sentinel-core-token"
DETACHED = "01a10000-0000-7000-8000-000000000dp1"


def frames(name: str) -> bytes:
    return (FRAMES / name).read_bytes()


class Stub:
    """A server answering each request with the next of `answers` (status, headers, body),
    keeping each request's path, headers and decoded body."""

    def __init__(self):
        self.answers: list[tuple[int, dict, bytes]] = []
        self.requests: list[dict] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                stub.requests.append({"path": self.path, "headers": dict(self.headers), "body": json.loads(body)})
                status, headers, answer = stub.answers.pop(0)
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(answer)))
                self.end_headers()
                self.wfile.write(answer)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.address = f"127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, args=(0.01,), daemon=True).start()

    def answer(self, body: bytes, status: int = 200, **headers):
        if status == 200 and "api" not in headers:
            headers = {core.HEADER_VERSION: core.VERSION, core.HEADER_BUILD: "test-build", **headers}
        headers.pop("api", None)
        self.answers.append((status, headers, body))

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def stub():
    s = Stub()
    yield s
    s.close()


def client(stub, sleeps=None, **env) -> Core:
    environ = {core.ENV_ADDRESS: stub.address, core.ENV_TOKEN: TOKEN, **env}
    return Core(environ, sleep=(sleeps.append if sleeps is not None else lambda s: None))


def failure(fn) -> CoreFailure:
    with pytest.raises(CoreFailure) as e:
        fn()
    assert TOKEN not in str(e.value) and TOKEN not in e.value.object
    return e.value


# The detached shape.


def test_a_detached_create_then_its_read_to_completion(stub):
    """US4 scenarios 1 and 2: the create answers its identity and run.detached, nothing
    followed; run.read every 2 s answers the run's lines so far and ends by EOF while it
    runs, then the document once it has ended. Each out line is surfaced once, in order, and
    the line naming the run's state never."""
    stub.answer(frames("create-detached.ndjson"))
    stub.answer(frames("read-running.ndjson"))
    stub.answer(frames("read-completed.ndjson"))
    sleeps, printed = [], []
    c = client(stub, sleeps)

    started = c.start(findings.OP_TWIN_CREATE, {"snapshot": "snap.json"}, [File("snap.json", b"{}")], printed.append)
    assert started.run == RunRef("fylgja-provision", DETACHED)
    assert started.start == "fylgja-provision"
    assert started.events == []
    assert started.document.status == "ok"
    assert [f.rule for f in started.document.findings] == ["run.detached"]
    assert started.build == "test-build"
    sent = stub.requests[0]
    assert sent["path"] == "/v1/twin/create"
    assert sent["headers"]["Authorization"] == "Bearer " + TOKEN
    assert sent["body"]["args"] == {"snapshot": "snap.json", "detach": True}
    assert sent["body"]["render"] == "text"
    assert sent["body"]["files"] == [{"path": "snap.json", "data": "e30="}]
    assert len(printed) == 2 and printed[0].startswith("snapshot_id ") and printed[1].startswith("bundle_id ")

    done = c.read(started.run.workflow_id, started.run.run_id, on_out=printed.append)
    assert [r["path"] for r in stub.requests[1:]] == ["/v1/run/read", "/v1/run/read"]
    assert all(r["body"]["args"] == {"workflow_id": "fylgja-provision", "run_id": DETACHED} for r in stub.requests[1:])
    assert all(r["body"]["render"] == "text" for r in stub.requests[1:])
    assert sleeps == [2.0]
    assert done.run == RunRef("fylgja-provision", DETACHED, "completed")
    assert done.document.operation == "run.read" and done.document.status == "failed"
    assert done.document.subject == {"run_id": DETACHED}
    findings.validate(done.document.to_dict())
    lines = printed[2:]
    assert lines == done.out
    assert lines[:6] == ["step host check: begins", "step host check: done in 0.0s", "step stage: begins",
                         "step stage: done in 0.0s", "step deploy: begins", "step deploy: done in 0.0s (1 node)"]
    assert lines[-2:] == ["removed lab fylgja (1 container)", "removed twin directory /t032/twin"]
    assert not any(line.startswith("run fylgja-provision ") for line in lines)
    assert len(done.events) == 14


def test_run_starts_then_reads(stub):
    stub.answer(frames("create-detached.ndjson"))
    stub.answer(frames("read-completed.ndjson"))
    done = client(stub).run(findings.OP_TWIN_CREATE, {"snapshot": "snap.json"})
    assert done.document.operation == "run.read"
    assert [r["path"] for r in stub.requests] == ["/v1/twin/create", "/v1/run/read"]


def test_a_refusal_document_starts_nothing(stub):
    """A run the core refused to start has no identity: its answer is the refusal, and run
    reads nothing."""
    stub.answer(frames("create-refused.ndjson"))
    answer = client(stub).run(findings.OP_TWIN_CREATE, {"dry_run": True})
    assert answer.run is None
    assert answer.document.status == "rejected"
    assert answer.document.findings[0].rule == "run.flags.conflict"
    assert answer.document.exit_code == 1
    assert len(stub.requests) == 1


def test_a_running_reads_eof_is_its_end(stub):
    """A run.read of a running run ends after its events, by EOF, with no document: the
    answer's end, not a cut."""
    stub.answer(frames("read-running.ndjson"))
    answer = client(stub).call(findings.OP_RUN_READ, {"workflow_id": "fylgja-provision"}, render="text")
    assert answer.running
    assert answer.document is None
    assert len(answer.events) == 6
    assert answer.out[0] == f"run fylgja-provision {DETACHED}: running"


def test_an_unknown_run_is_its_document(stub):
    stub.answer(frames("read-unknown.ndjson"))
    answer = client(stub).read("fylgja-step", "r-gone")
    assert answer.document.findings[0].rule == "run.unknown"
    assert answer.document.exit_code == 1


def test_a_detached_destroy_names_its_run(stub):
    """US4 scenario 6: a destroy's detached answer writes the run frame its stream never
    did, after the notices of what it cancelled first."""
    stub.answer(frames("destroy-detached.ndjson"))
    answer = client(stub).start(findings.OP_TWIN_DESTROY)
    assert answer.run == RunRef("fylgja-destroy", "01a10000-0000-7000-8000-000000000dd1")
    assert stub.requests[0]["body"]["args"] == {"detach": True}
    assert "cancelling provisioning run p1; waiting for its cleanup" in answer.out


def test_interrupt_by_identity(stub):
    stub.answer(frames("interrupt-requested.ndjson"))
    doc = client(stub).interrupt("fylgja-provision", DETACHED)
    assert stub.requests[0]["path"] == "/v1/run/interrupt"
    assert stub.requests[0]["body"] == {"args": {"workflow_id": "fylgja-provision", "run_id": DETACHED}}
    assert doc.findings[0].rule == "run.cancel.requested"


def test_the_operations_paths_and_arguments(stub):
    doc = b'{"document":{"findings_version":"1","operation":"x","status":"ok","findings":[]}}\n'
    for _ in range(5):
        stub.answer(doc)
    c = client(stub)
    c.show()
    c.compile("snap.json", [File("snap.json", b"x")])
    c.diff("a" * 64, "snap.json", [File("snap.json", b"x")])
    c.verify("60s")
    c.dry_run(findings.OP_TWIN_CREATE, {"snapshot": "s.json"})
    got = [(r["path"], r["body"].get("args")) for r in stub.requests]
    assert got == [
        ("/v1/twin/show", None),
        ("/v1/twin/compile", {"snapshot": "snap.json"}),
        ("/v1/twin/diff", {"from": "a" * 64, "to": "snap.json"}),
        ("/v1/twin/verify", {"wait": "60s"}),
        ("/v1/twin/create", {"snapshot": "s.json", "dry_run": True}),
    ]


def test_a_compiles_files_are_decoded(stub):
    stub.answer(b'{"files":[{"path":"manifest.json","data":"e30="}]}\n'
                b'{"document":{"findings_version":"1","operation":"twin.compile","status":"ok","findings":[]}}\n')
    answer = client(stub).compile("a" * 64)
    assert answer.files == [File("manifest.json", b"{}")]


# The faults, worded as internal/cli/failures.go words them.


def test_a_401_is_the_token_refused(stub):
    stub.answer(b'{"message":"no"}', status=401)
    f = failure(lambda: client(stub).show())
    assert f.rule == "api.token.refused"
    assert f.object == stub.address
    assert f.message == (f"the API at {stub.address} refused this client's token; FYLGJA_API_TOKEN must be the "
                         "token fylgja serve was started with")
    doc = f.document(findings.OP_TWIN_SHOW)
    assert doc.status == "error" and doc.exit_code == 2
    findings.validate(doc.to_dict())


def test_a_refused_connection_is_unreachable():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    c = Core({core.ENV_ADDRESS: f"127.0.0.1:{port}", core.ENV_TOKEN: TOKEN})
    f = failure(c.show)
    assert f.rule == "api.unreachable"
    assert f.object == f"127.0.0.1:{port}"
    assert f.message.startswith(f"the API at 127.0.0.1:{port} cannot be reached: ")
    assert f.message.endswith("; fylgja serve runs on the lab host")
    assert f.document(findings.OP_TWIN_SHOW).exit_code == 2


@pytest.mark.parametrize(
    "token, words",
    [
        ("", "FYLGJA_API_TOKEN is not set; a client sends the API's token with every request, and nothing was sent"),
        (TOKEN + "\r", "FYLGJA_API_TOKEN holds a character a request header cannot carry, such as a carriage return; "
                       "nothing was sent"),
        (TOKEN + " ", "FYLGJA_API_TOKEN ends in a space or a tab, which a request header cannot carry; nothing was "
                      "sent"),
    ],
)
def test_a_token_that_cannot_be_sent_sends_nothing(stub, token, words):
    f = failure(lambda: client(stub, **{core.ENV_TOKEN: token}).show())
    assert (f.rule, f.object, f.message) == ("api.token.refused", "FYLGJA_API_TOKEN", words)
    assert stub.requests == []


def test_an_answer_cut_before_its_document_names_the_run(stub):
    """A run's answer that ends after its run frame, with no document, says the run goes on."""
    lines = frames("create-detached.ndjson").splitlines(keepends=True)
    stub.answer(b"".join(lines[:-1]))
    f = failure(lambda: client(stub).start(findings.OP_TWIN_CREATE))
    assert f.rule == "api.unreachable"
    assert f.message == (f"the API at {stub.address} stopped answering before the command ended: unexpected EOF; "
                         f"run fylgja-provision {DETACHED} was not cancelled and goes on: fylgja twin show names it")
    stub.answer(b"".join(lines[:3]))
    f = failure(lambda: client(stub).start(findings.OP_TWIN_CREATE))
    assert f.message.endswith("; a run may have been started and was not cancelled: fylgja twin show names it")


def test_a_line_that_is_no_frame_is_a_cut(stub):
    stub.answer(b"not json\n")
    f = failure(lambda: client(stub).show())
    assert f.rule == "api.unreachable"
    assert "a line of the answer is not a frame" in f.message


def test_an_answer_naming_no_version_is_not_the_api(stub):
    stub.answer(b"hello\n", api=None)
    f = failure(lambda: client(stub).show())
    assert f.rule == "api.unreachable"
    assert "what answers there is not the API: its answer names no Fylgja-Api-Version" in f.message


def test_a_404_naming_other_versions(stub):
    stub.answer(b"", status=404, **{core.HEADER_VERSIONS: "2"})
    f = failure(lambda: client(stub).show())
    assert (f.rule, f.message) == ("api.version.unknown",
                                   f"the API at {stub.address} serves version 2; this client speaks version 1")
    stub.answer(b"", status=404, **{core.HEADER_VERSIONS: "1"})
    assert failure(lambda: client(stub).show()).rule == "operation.failed"


def test_413_and_400_carry_the_servers_words(stub):
    stub.answer(b'{"message":"over 32 MiB","limit_bytes":33554432}', status=413)
    f = failure(lambda: client(stub).show())
    assert (f.rule, f.object, f.message) == ("api.transfer.too_large", "twin.show", "over 32 MiB")
    stub.answer(b'{"message":"twin.show takes no argument \\"x\\""}', status=400)
    f = failure(lambda: client(stub).show())
    assert f.rule == "operation.failed"
    assert f.message == f'the API at {stub.address} could not read this request: twin.show takes no argument "x"'


def test_a_frame_over_the_bound(stub):
    stub.answer(b'{"out":"' + b"x" * 200 + b'"}\n')
    c = client(stub)
    c.max_frame_bytes = 64
    f = failure(c.show)
    assert f.rule == "api.transfer.too_large"
    assert "larger than this client's bound of 64 bytes" in f.message


@pytest.mark.parametrize(
    "address, url",
    [
        ("127.0.0.1:7650", "http://127.0.0.1:7650"),
        ("[::1]:7650", "http://[::1]:7650"),
        ("https://proxy.example/fylgja/", "https://proxy.example/fylgja"),
    ],
)
def test_addresses_taken(address, url):
    assert core.base_url(address) == url


@pytest.mark.parametrize(
    "address, shown, words",
    [
        ("lab", "lab", "is not host:port"),
        ("lab:http", "lab:http", "is not host:port"),
        ("lab:7650/x", "lab:7650/x", "is not host:port"),
        ("lab:7650\r", '"lab:7650\\r"', "is not host:port"),
        ("http://u:secret@lab:7650", "http://lab:7650", "names a user or password"),
        ("http://lab:7650/?q=1", "http://lab:7650/?q=1", "is not a URL of a server"),
    ],
)
def test_addresses_refused_before_any_dial(address, shown, words):
    with pytest.raises(CoreFailure) as e:
        core.base_url(address)
    assert e.value.rule == "api.unreachable" and e.value.object == shown
    assert words in e.value.message and "secret" not in e.value.message


def test_the_default_address_and_no_token_in_the_client():
    c = Core({core.ENV_TOKEN: TOKEN})
    assert c.address == "127.0.0.1:7650"
    assert TOKEN not in repr(c) and TOKEN not in str(vars(c).get("address"))
