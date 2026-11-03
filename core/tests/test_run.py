from fylgja_core import documents, schemas
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
