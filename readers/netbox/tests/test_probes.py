"""The probes (D-095): the probe declaration that the configuration context the reader document names holds, read
inside the bracket, held to the declaration's rules by the core's own loader, and put into the blueprint, or the
findings that refused it. Over rows built in the tests and `FakeSource`, never NetBox's answers (D-034)."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import pytest
from fake import DOCUMENT, PROBED, PROBING, FakeSource, listing, seeded_context, three_node
from fylgja_core import blueprint

from fylgja_netbox import NetBoxError, Result, probes, read
from fylgja_netbox.rows import Branch, Change, Context
from fylgja_netbox.transport import QUOTED

SCOPE = "tag:fylgja"
BRANCH = Branch(7, "b", "p9d46y7z", "ready", "2026-11-12T16:30:00.115200Z")
FIXTURE = json.loads(PROBED.read_text())
FIXTURE_ID = blueprint.blueprint_id(FIXTURE)
SEEDED = FIXTURE["probes"][0]

N2_LOOP = {
    "name": "n2-loop",
    "format": "ping",
    "endpoints": [
        {"device": "n2", "interface": "ethernet-1/10", "address": "192.0.2.2/24", "gateway": "192.0.2.1"},
        {"device": "n2", "interface": "ethernet-1/11", "address": "198.51.100.2/24", "gateway": "198.51.100.1"},
    ],
}
"""A second probe, of the documentation ranges, on a device of the scope."""


def done(conn: FakeSource, *, branch: str | None = None) -> Result:
    return read(conn, branch=branch, scope=SCOPE, document=PROBING)


def rules(result: Result) -> list[tuple[str, str | None]]:
    return [(finding.rule, finding.object) for finding in result.findings]


def errors(result: Result) -> list[tuple[str, str | None]]:
    return [(finding.rule, finding.object) for finding in result.findings if finding.severity == "error"]


def called(conn: FakeSource) -> list[str]:
    return [name for name, _ in conn.calls]


def declaring(*held: dict[str, Any], version: str = "1") -> Context:
    """The seeded context, its data declaring `held`."""
    return replace(seeded_context(), data={"probes_version": version, "probes": list(held)})


def holding(context: Context, *, count: int | None = None) -> FakeSource:
    conn = three_node()
    conn.held_contexts = listing("extras.configcontext", [context], count)
    return conn


def copied(probe: dict[str, Any], **changes: Any) -> dict[str, Any]:
    held: dict[str, Any] = json.loads(json.dumps(probe))
    held.update(changes)
    return held


def at(probe: dict[str, Any], end: int, **changes: str) -> dict[str, Any]:
    """`probe` with the members `changes` of its endpoint `end` changed."""
    held = copied(probe)
    held["endpoints"][end].update(changes)
    return held


def test_the_seeded_context_reads_to_the_fixtures_probe() -> None:
    conn = three_node()
    result = done(conn)
    assert result.findings == ()
    assert result.blueprint is not None
    assert blueprint.validate(result.blueprint) == []
    assert result.blueprint["probes"] == FIXTURE["probes"]
    assert blueprint.blueprint_id(result.blueprint) == FIXTURE_ID
    assert ("contexts", None) in conn.calls


def test_a_document_naming_no_context_asks_nothing() -> None:
    conn = three_node()
    result = read(conn, branch=None, scope=SCOPE, document=DOCUMENT)
    assert result.blueprint is not None and result.blueprint["probes"] == []
    assert "contexts" not in called(conn)

    conn = three_node()
    conn.held_contexts = listing("extras.configcontext", [])
    assert read(conn, branch=None, scope=SCOPE, document=DOCUMENT).findings == ()


def test_the_context_is_read_inside_the_bracket_under_the_branchs_header() -> None:
    conn = three_node()
    conn.held_branches = listing("netbox_branching.branch", [BRANCH])
    conn.latests = [7]
    conn.counts = [5]
    assert done(conn, branch="b").blueprint is not None
    names = called(conn)
    assert names[:8] == ["branches", "latest", "counted", "tags", "devices", "platforms", "ports", "cables"]
    assert names[8:12] == ["contexts", "render", "render", "render"]
    assert names[12:] == ["branches", "latest", "counted"]
    assert ("contexts", "b") in conn.calls


def test_a_context_netbox_lacks_is_refused() -> None:
    conn = three_node()
    conn.held_contexts = listing("extras.configcontext", [])
    conn.held_branches = listing("netbox_branching.branch", [BRANCH])
    result = done(conn, branch="b")
    assert rules(result) == [("probe.context.absent", "fylgja-probes")]
    assert "branch b" in result.findings[0].message
    assert result.blueprint is None
    assert conn.rendered == [1, 2, 3], "every rule is judged in one pass"

    on_main = done(holding(replace(seeded_context(), name="fylgja-other")))
    assert rules(on_main) == [("probe.context.absent", "fylgja-probes")]
    assert "main" in on_main.findings[0].message


def test_an_active_context_is_refused() -> None:
    active = replace(seeded_context(), active=True)
    result = done(holding(active))
    assert rules(result) == [("probe.context.active", "fylgja-probes")]
    assert "main" in result.findings[0].message
    assert result.blueprint is None
    assert probes.select(listing("extras.configcontext", [active]), "fylgja-probes", branch=None) == result.findings[0]


def test_a_probe_outside_the_scope_is_omitted() -> None:
    far = at(copied(N2_LOOP, name="far"), 1, device="n9")
    result = done(holding(declaring(SEEDED, far)))
    assert rules(result) == [("omit.probe.outside_scope", "far")]
    assert result.findings[0].severity == "info"
    assert "n9" in result.findings[0].message and "main" in result.findings[0].message
    assert result.blueprint is not None
    assert result.blueprint["probes"] == [SEEDED]
    assert blueprint.blueprint_id(result.blueprint) == FIXTURE_ID
    rows = [row for row in result.blueprint["source"]["fidelity"] if row["object"] == "far"]
    assert rows == [
        {
            "disposition": "omitted",
            "object": "far",
            "source": "extras.configcontext",
            "reason": "an end on the device n9, which is no device of the scope",
        }
    ]
    fidelity = result.blueprint["source"]["fidelity"]
    assert fidelity == sorted(fidelity, key=lambda r: (r["disposition"], r["object"], r["source"], r["reason"]))


def renamed(context: Context) -> FakeSource:
    """`three_node`'s rows holding `context`, `n1` named `N1` in NetBox."""
    conn = holding(context)
    devices = list(conn.held_devices.items)
    devices[0] = replace(devices[0], name="N1")
    conn.held_devices = listing("dcim.device", devices)
    return conn


def test_a_probe_follows_a_renamed_device() -> None:
    result = done(renamed(declaring(at(at(SEEDED, 0, device="N1"), 1, device="N1"))))
    assert rules(result) == [("device.name.renamed", "N1")]
    assert result.blueprint is not None
    assert result.blueprint["probes"] == [SEEDED]
    assert blueprint.blueprint_id(result.blueprint) == FIXTURE_ID

    # Compared exactly: the device's blueprint name is no name of NetBox's.
    result = done(renamed(seeded_context()))
    assert rules(result) == [("device.name.renamed", "N1"), ("omit.probe.outside_scope", "n1-loop")]
    assert result.blueprint is not None and result.blueprint["probes"] == []


FAULTS: list[tuple[str, Callable[[], Any], list[tuple[str, str]]]] = [
    (
        "another version",
        lambda: {"probes_version": "2", "probes": [SEEDED]},
        [("probes.version.unsupported", "fylgja-probes")],
    ),
    (
        "another version, a probe outside the scope",
        lambda: {"probes_version": "2", "probes": [at(SEEDED, 1, device="n9")]},
        [("probes.version.unsupported", "fylgja-probes")],
    ),
    ("a list", lambda: [SEEDED], [("probes.invalid", "fylgja-probes")]),
    (
        "an address with no prefix",
        lambda: {"probes_version": "1", "probes": [at(SEEDED, 0, address="10.1.10.2")]},
        [("probes.invalid", "n1-loop")],
    ),
    (
        "two probes of one name",
        lambda: {"probes_version": "1", "probes": [SEEDED, copied(N2_LOOP, name="n1-loop")]},
        [("probe.name.duplicate", "n1-loop")],
    ),
    (
        "a gateway outside its prefix",
        lambda: {"probes_version": "1", "probes": [at(SEEDED, 1, gateway="10.1.12.1")]},
        [("probe.gateway.outside", "n1-loop")],
    ),
    (
        "one address twice",
        lambda: {
            "probes_version": "1",
            "probes": [SEEDED, at(N2_LOOP, 0, address="10.1.10.2/24", gateway="10.1.10.1")],
        },
        [("probe.address.duplicate", "n2-loop")],
    ),
]


@pytest.mark.parametrize(("data", "found"), [(data, found) for _, data, found in FAULTS], ids=[n for n, *_ in FAULTS])
def test_each_fault_of_the_declaration_is_its_rule(data: Callable[[], Any], found: list[tuple[str, str]]) -> None:
    result = done(holding(replace(seeded_context(), data=data())))
    assert rules(result) == found
    assert result.blueprint is None
    for finding in result.findings:
        assert "main" in finding.message and "fylgja-probes" in finding.message


def test_every_fault_is_filed_in_one_pass_and_no_probe_given() -> None:
    context = declaring(
        at(SEEDED, 1, gateway="10.1.12.1"),
        copied(N2_LOOP, name="n1-loop"),
        at(at(N2_LOOP, 0, address="10.1.10.2/24", gateway="10.1.10.1"), 1, address="198.51.100.3/24"),
        at(copied(N2_LOOP, name="far"), 0, device="n9"),
    )
    conn = holding(context)
    conn.renders[3] = replace(conn.renders[3], status=500, body=b"UndefinedError")
    result = done(conn)
    assert sorted(rules(result)) == [
        ("omit.probe.outside_scope", "far"),
        ("probe.address.duplicate", "n2-loop"),
        ("probe.gateway.outside", "n1-loop"),
        ("probe.name.duplicate", "n1-loop"),
        ("render.failed", "n3"),
    ]
    assert result.blueprint is None
    built, omitted, found = probes.build(context, {"n1": "n1", "n2": "n2", "n3": "n3"}, branch=None)
    assert built == []
    assert [row["object"] for row in omitted] == ["far"]
    assert {finding.rule for finding in found} >= {"probe.name.duplicate", "probe.gateway.outside"}


def test_probes_in_any_order_give_one_id() -> None:
    first = done(holding(declaring(SEEDED, N2_LOOP)))
    second = done(holding(declaring(N2_LOOP, SEEDED)))
    assert first.blueprint is not None and second.blueprint is not None
    assert [probe["name"] for probe in first.blueprint["probes"]] == ["n1-loop", "n2-loop"]
    assert first.blueprint["probes"] == second.blueprint["probes"]
    assert blueprint.blueprint_id(first.blueprint) == blueprint.blueprint_id(second.blueprint)

    far = at(copied(N2_LOOP, name="far"), 0, device="n9")
    faulted = [at(SEEDED, 1, gateway="10.1.12.1"), copied(N2_LOOP, name="n1-loop"), far]
    one, other = done(holding(declaring(*faulted))), done(holding(declaring(*reversed(faulted))))
    assert one.findings == other.findings


def test_a_context_not_listed_whole_is_incomplete() -> None:
    conn = holding(seeded_context(), count=2)
    result = done(conn)
    assert rules(result) == [("read.incomplete", "extras.configcontext")]
    assert result.blueprint is None
    assert "render" not in called(conn)
    assert called(conn)[-1] == "latest", "the close was not taken"


def test_a_context_edited_during_a_read_is_moved() -> None:
    conn = three_node()
    conn.latests = [7, 9]
    conn.counts = [5]
    conn.changed = (Change(8, "extras.configcontext"), Change(9, "extras.journalentry"))
    result = done(conn)
    assert rules(result) == [("read.moved", "main")]
    assert "extras.configcontext" in result.findings[0].message
    assert result.blueprint is None


def test_a_probe_on_a_device_the_mapping_could_not_name_is_omitted() -> None:
    """A device whose name makes no label has no blueprint name, so a probe on it can be placed nowhere: it is omitted
    beside the device's own refusal, and the read judges both."""
    conn = three_node()
    devices = list(conn.held_devices.items)
    devices[0] = replace(devices[0], name="***")
    conn.held_devices = listing("dcim.device", devices)
    conn.held_contexts = listing("extras.configcontext", [declaring(at(at(SEEDED, 0, device="***"), 1, device="***"))])
    result = done(conn)
    assert rules(result) == [("device.name.unmappable", "***"), ("omit.probe.outside_scope", "n1-loop")]
    assert result.blueprint is None


def test_two_contexts_of_the_name_are_refused() -> None:
    """NetBox's source holds a context's name unique, read and not run, and the read does not rely on it: a name that
    answers two rows is NetBox's error, raised before a probe is built on the first."""
    conn = three_node()
    conn.held_contexts = listing("extras.configcontext", [seeded_context(), replace(seeded_context(), id=2)])
    with pytest.raises(NetBoxError) as raised:
        done(conn)
    assert raised.value.status == 200
    for said in ("extras.configcontext", "main", "2 rows", "fylgja-probes"):
        assert said in str(raised.value)
    assert "render" not in called(conn)


def test_the_loaders_words_are_cut() -> None:
    """The loader's detail quotes the value at fault, which the data may hold at any length: a finding quotes
    the transport's `QUOTED` characters of it, as it quotes NetBox's words."""
    result = done(holding(declaring(at(SEEDED, 0, address="1" * 1000))))
    assert errors(result) == [("probes.invalid", "n1-loop")]
    message = result.findings[0].message
    assert "1" * (QUOTED + 1) not in message
    assert "1" * 100 in message
    assert len(message) < QUOTED + 200
