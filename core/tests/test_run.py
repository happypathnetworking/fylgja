from fylgja_core import documents, run, schemas, ulid
from fylgja_core.findings import Subject, Verdict
from fylgja_core.run import Event, Run

RUN = Run(
    id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
    twin="three-node",
    operation="create",
    state="queued",
    principal="jgilby",
    created_at="2026-11-03T10:00:00.000000Z",
)


def test_a_run_encodes_to_the_apis_run_and_decodes_back() -> None:
    doc = documents.encode(RUN)
    assert schemas.api_validator("Run").is_valid(doc), list(schemas.api_validator("Run").iter_errors(doc))
    assert "ended_at" not in doc and "verdict" not in doc
    assert documents.decode(Run, doc) == RUN


def test_an_event_encodes_to_the_apis_event() -> None:
    e = Event(seq=1, at="2026-11-03T10:00:00.000000Z", phase="compile", outcome="started")
    doc = documents.encode(e)
    assert schemas.api_validator("Event").is_valid(doc)
    assert doc == {"seq": 1, "at": e.at, "phase": "compile", "outcome": "started"}
    ended = Event(seq=2, at=e.at, phase="push", outcome="failed", node="n1", duration_s=1.5, rule="push.refused")
    assert schemas.api_validator("Event").is_valid(documents.encode(ended))


def test_queued_makes_a_valid_run_with_a_new_ulid() -> None:
    made = run.queued("three-node", "step", "jgilby")
    assert ulid.PATTERN.match(made.id)
    assert (made.twin, made.operation, made.state, made.principal) == ("three-node", "step", "queued", "jgilby")
    assert made.ended_at is None and made.verdict is None
    doc = documents.encode(made)
    assert schemas.api_validator("Run").is_valid(doc), list(schemas.api_validator("Run").iter_errors(doc))
    assert run.queued("three-node", "step", "jgilby").id != made.id


def test_ended_sets_the_state_the_time_and_the_verdict() -> None:
    verdict = Verdict(operation="create", status="ok", subject=Subject(twin="three-node"), findings=())
    done = run.ended(run.queued("three-node", "create", "jgilby"), verdict)
    assert done.state == "ended" and done.verdict == verdict and done.ended_at is not None
    doc = documents.encode(done)
    assert schemas.api_validator("Run").is_valid(doc), list(schemas.api_validator("Run").iter_errors(doc))
