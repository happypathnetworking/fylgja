"""The probes: the kind `FylgjaProbe` the reader ships, and its objects read into the blueprint's `probes` where the
reader document asks for them (D-082), over a `FakeSource` of rows built in the tests. A probe an end of which names
no scoped device is omitted; the rest are held to the declaration's rules by the core's own loader, each fault an
error naming the probe; each end's device takes its blueprint name, and the list is sorted by name, so the same rows in
any order give one id."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from fake import (
    DOCUMENT,
    PROBING,
    THREE_NODE_PROBED,
    FakeSource,
    dcim_schema,
    listing,
    probe,
    probed_schema,
    seeded_probe,
    stamp,
    three_node,
)
from fylgja_core import blueprint
from fylgja_core.probes import RULE_ADDRESS_DUPLICATE, RULE_GATEWAY_OUTSIDE, RULE_NAME_DUPLICATE

from fylgja_infrahub import Refused, head, read
from fylgja_infrahub.mapping import RULE_RENAMED
from fylgja_infrahub.probes import FIELDS, KIND, RULE_KIND_ABSENT, RULE_OMIT_OUTSIDE, absent
from fylgja_infrahub.read import Result
from fylgja_infrahub.rows import RULE_INCOMPLETE, Kind, Probe

READER = Path(__file__).resolve().parents[1]
KIND_FILE = READER / "schema" / "fylgja-probe.yml"
BLUEPRINT = json.loads((READER.parents[1] / "formats" / "blueprint-1.schema.json").read_text())["$defs"]
PROBED = json.loads(THREE_NODE_PROBED.read_text())
T = "2026-11-09T10:00:00.000000+00:00"


def probing(*probes: Probe, count: int | None = None) -> FakeSource:
    """`three_node`'s rows on a branch whose schema holds the kind, its probes `probes`, listed under `count` where it
    is given."""
    source = three_node()
    source.held_schema = probed_schema()
    source.held_probes = listing(KIND, list(probes), count)
    return source


def ran(source: FakeSource, document: Any = PROBING) -> Result:
    return read(source, branch="main", at=T, scope="tag:fylgja", document=document)


def rules(result: Result) -> list[tuple[str, str, str | None]]:
    return [(f.rule, f.severity, f.object) for f in result.findings]


def names(result: Result) -> list[str]:
    assert result.blueprint is not None
    return [held["name"] for held in result.blueprint["probes"]]


def test_the_kinds_file_declares_what_the_reader_reads() -> None:
    held = yaml.safe_load(KIND_FILE.read_text())
    assert sorted(held) == ["nodes", "version"]
    (node,) = held["nodes"]
    assert node["namespace"] + node["name"] == KIND
    assert node["branch"] == "agnostic"
    assert (node["order_by"], node["uniqueness_constraints"]) == (["name__value"], [["name__value"]])
    assert "relationships" not in node, "a probe names its devices and has no relationship to one"
    attributes = {attribute["name"]: attribute for attribute in node["attributes"]}
    assert tuple(attributes) == FIELDS
    assert {(a["kind"], a["optional"]) for a in attributes.values()} == {("Text", False)}
    patterns = {name: a.get("parameters", {}).get("regex") for name, a in attributes.items()}
    probe_def = BLUEPRINT["probe"]["properties"]
    assert patterns == {
        "name": probe_def["name"]["pattern"],
        "format": probe_def["format"]["pattern"],
        **{f"{end}_device": None for end in "ab"},
        **{f"{end}_interface": None for end in "ab"},
        **{f"{end}_address": BLUEPRINT["ipv4_prefix"]["pattern"] for end in "ab"},
        **{f"{end}_gateway": BLUEPRINT["ipv4_address"]["pattern"] for end in "ab"},
    }
    assert attributes["format"]["default_value"] == "ping"


def test_a_schema_without_the_kind_is_absent() -> None:
    assert absent(probed_schema(), branch="main") is None
    finding = absent(dcim_schema(), branch="main")
    assert finding is not None
    assert (finding.rule, finding.severity, finding.object) == (RULE_KIND_ABSENT, "error", KIND)
    assert "main" in finding.message and "readers/infrahub/schema/fylgja-probe.yml" in finding.message

    source = three_node()
    source.held_probes = listing(KIND, [seeded_probe()])
    result = ran(source)
    assert result.blueprint is None
    assert rules(result) == [(RULE_KIND_ABSENT, "error", KIND)]
    assert "probes" not in [call[0] for call in source.calls], "a kind the branch lacks is not asked of"


def test_a_schema_whose_kind_lacks_an_attribute_names_it() -> None:
    held = probed_schema()
    kind = held.nodes[KIND]
    lacking = Kind({name: a for name, a in kind.attributes.items() if name != "b_gateway"}, {})
    finding = absent(dataclasses.replace(held, nodes={**held.nodes, KIND: lacking}), branch="main")
    assert finding is not None
    assert (finding.rule, finding.object) == (RULE_KIND_ABSENT, KIND)
    assert "b_gateway" in finding.message
    assert [field for field in FIELDS if field != "b_gateway" and field in finding.message] == []
    assert "readers/infrahub/schema/fylgja-probe.yml" in finding.message


def test_no_probe_is_read_where_the_document_asks_for_none() -> None:
    source = three_node()
    source.held_probes = listing(KIND, [seeded_probe()])
    result = ran(source, DOCUMENT)
    assert result.findings == ()
    assert result.blueprint is not None and result.blueprint["probes"] == []
    assert "probes" not in [call[0] for call in source.calls]
    assert KIND not in source.held_schema.nodes, "a schema without the kind is no fault"


def test_the_probed_rows_read_to_the_probed_fixtures_id() -> None:
    source = probing(seeded_probe())
    result = ran(source)
    assert result.findings == ()
    assert result.blueprint is not None
    assert result.blueprint["probes"] == PROBED["probes"]
    assert blueprint.blueprint_id(result.blueprint) == blueprint.blueprint_id(PROBED)
    assert source.calls[-1] == ("probes", "main", T), "read through the branch at the read's own time"


def sorted_three() -> list[Probe]:
    """Three probes on `n1`'s and `n2`'s uncabled ports, named out of order."""
    return [
        probe("c-probe", ("n2", "ethernet-1/10", "10.2.10.2/24", "10.2.10.1"), ("n2", "ethernet-1/11", "10.2.11.2/24",
              "10.2.11.1")),
        probe("a-probe", ("n1", "ethernet-1/10", "10.1.10.2/24", "10.1.10.1"), ("n1", "ethernet-1/11", "10.1.11.2/24",
              "10.1.11.1")),
        probe("b-probe", ("n1", "ethernet-1/10", "10.1.10.3/24", "10.1.10.1"), ("n2", "ethernet-1/11", "10.2.11.3/24",
              "10.2.11.1")),
    ]


def test_probes_are_sorted_by_name_whatever_the_order_read() -> None:
    first, again = ran(probing(*sorted_three())), ran(probing(*sorted_three()[::-1]))
    assert names(first) == names(again) == ["a-probe", "b-probe", "c-probe"]
    assert first.blueprint is not None and again.blueprint is not None
    assert json.dumps(first.blueprint["probes"]) == json.dumps(again.blueprint["probes"])
    assert blueprint.blueprint_id(first.blueprint) == blueprint.blueprint_id(again.blueprint)


@pytest.mark.parametrize("ends", [("x9", "x9"), ("n1", "x9"), ("x9", "n1")], ids=["both", "b", "a"])
def test_a_probe_of_another_scope_is_omitted(ends: tuple[str, str]) -> None:
    """Its addresses are the seeded probe's, and are never weighed against them."""
    seeded = seeded_probe()
    other = probe("elsewhere", (ends[0], *seeded.a[1:]), (ends[1], *seeded.b[1:]))
    result = ran(probing(seeded, other))
    assert rules(result) == [(RULE_OMIT_OUTSIDE, "info", "elsewhere")]
    assert "main" in result.findings[0].message and T in result.findings[0].message
    assert names(result) == ["n1-loop"]
    assert result.blueprint is not None
    rows = [row for row in result.blueprint["source"]["fidelity"] if row["object"] == "elsewhere"]
    assert [(row["disposition"], row["source"]) for row in rows] == [("omitted", KIND)]
    assert "x9" in rows[0]["reason"]


def test_a_renamed_device_is_named_by_its_label() -> None:
    held = seeded_probe()
    source = probing(dataclasses.replace(held, a=("N1", *held.a[1:]), b=("N1", *held.b[1:])))
    source.held_devices = listing(
        "DcimDevice", [dataclasses.replace(d, name="N1") if d.name == "n1" else d for d in source.held_devices.items]
    )
    result = ran(source)
    assert rules(result) == [(RULE_RENAMED, "info", "N1")]
    assert result.blueprint is not None
    assert [end["device"] for end in result.blueprint["probes"][0]["endpoints"]] == ["n1", "n1"]
    assert result.blueprint["probes"] == PROBED["probes"]


def test_a_probe_naming_its_device_otherwise_than_infrahub_is_of_no_scoped_device() -> None:
    """A probe names its device by its name in Infrahub, compared exactly: `n1` names no device read as `N1`."""
    source = probing(seeded_probe())
    source.held_devices = listing(
        "DcimDevice", [dataclasses.replace(d, name="N1") if d.name == "n1" else d for d in source.held_devices.items]
    )
    result = ran(source)
    assert rules(result) == [(RULE_RENAMED, "info", "N1"), (RULE_OMIT_OUTSIDE, "info", "n1-loop")]
    assert names(result) == []


def test_each_fault_of_the_declaration_is_an_error_naming_the_probe() -> None:
    seeded = seeded_probe()
    on_n2 = ("n2", "ethernet-1/10", "10.2.10.2/24", "10.2.10.1"), ("n2", "ethernet-1/11", "10.2.11.2/24", "10.2.11.1")
    on_n3 = ("n3", "ethernet-1/10", "10.3.10.2/24", "10.3.10.1"), ("n3", "ethernet-1/11", "10.3.11.2/24", "10.3.11.1")
    faulty = [
        seeded,
        probe("dup", *on_n2, id="probe-dup-1"),
        probe("dup", *on_n3, id="probe-dup-2"),
        probe("gateway", ("n2", "ethernet-1/10", "10.2.10.9/24", "10.9.9.1"), ("n3", "ethernet-1/10", "10.3.10.9/24",
              "10.3.10.1")),
        probe("shared", seeded.a, ("n3", "ethernet-1/11", "10.3.11.5/24", "10.3.11.1")),
    ]
    result = ran(probing(*faulty))
    assert rules(result) == [
        (RULE_ADDRESS_DUPLICATE, "error", "shared"),
        (RULE_GATEWAY_OUTSIDE, "error", "gateway"),
        (RULE_NAME_DUPLICATE, "error", "dup"),
    ]
    assert result.blueprint is None
    for finding in result.findings:
        assert "main" in finding.message and T in finding.message


def test_a_probe_the_declaration_refuses_by_its_schema_is_probes_invalid() -> None:
    held = seeded_probe()
    result = ran(probing(dataclasses.replace(held, a=(held.a[0], held.a[1], "10.1.10.2", held.a[3]))))
    assert rules(result) == [("probes.invalid", "error", "n1-loop")]
    assert result.blueprint is None


@pytest.mark.parametrize(
    ("alter", "named"),
    [
        (lambda held: dataclasses.replace(held, format=None), "n1-loop"),
        (lambda held: dataclasses.replace(held, a=(held.a[0], held.a[1], held.a[2], None)), "n1-loop"),
        (lambda held: dataclasses.replace(held, b=(None, *held.b[1:])), "n1-loop"),
        (lambda held: dataclasses.replace(held, name=None), "probe-n1-loop"),
    ],
    ids=["format", "a gateway", "b device", "name, by its id"],
)
def test_an_attribute_infrahub_answers_null_is_probes_invalid(alter: Any, named: str) -> None:
    """`format` reads optional on Infrahub, its default notwithstanding (design/verified-facts.md, "Infrahub 1.11.11"),
    so a null attribute is the declaration's fault, named by the probe, or by its id where its name is null; an end
    whose device is null is no end of another scope."""
    result = ran(probing(alter(seeded_probe())))
    assert rules(result) == [("probes.invalid", "error", named)]
    assert result.blueprint is None


LATE = "2026-11-09T10:00:13.000000+00:00"
"""Later than every write of `three_node`'s."""


def test_head_counts_every_probes_stamp() -> None:
    """A probe is the blueprint's as much as a device, so `head` counts every `FylgjaProbe`'s stamp, read through the
    branch as it stands, whatever devices it names and whatever a document asks (P3-38)."""
    source = probing(seeded_probe())
    assert head(source, branch="main", scope="tag:fylgja") == "2026-11-09T10:00:01.000001+00:00", "no probe stamp"
    elsewhere = stamp(LATE)
    source.held_probe_stamps = listing(KIND, [("probe-n1-loop", stamp()), ("probe-elsewhere", elsewhere)])
    assert head(source, branch="main", scope="tag:fylgja") == "2026-11-09T10:00:13.000001+00:00"
    assert ("probe_stamps", "main", None) in source.calls
    assert source.events_asked[-1][1] == LATE, "the log read down to the latest stamp, a probe's among them"


def test_head_counts_no_probe_where_the_kind_is_absent() -> None:
    source = three_node()
    source.held_probe_stamps = listing(KIND, [("probe-elsewhere", stamp(LATE))])
    assert head(source, branch="main", scope="tag:fylgja") == "2026-11-09T10:00:01.000001+00:00"
    assert "probe_stamps" not in [call[0] for call in source.calls]


def test_head_over_a_short_list_of_probes_stamps_is_refused() -> None:
    source = probing(seeded_probe())
    source.held_probe_stamps = listing(KIND, [("probe-n1-loop", stamp())], count=2)
    with pytest.raises(Refused) as raised:
        head(source, branch="main", scope="tag:fylgja")
    assert [(f.rule, f.object) for f in raised.value.findings] == [(RULE_INCOMPLETE, KIND)]


def test_a_short_list_of_probes_is_incomplete() -> None:
    short = ran(probing(seeded_probe(), count=2))
    assert rules(short) == [(RULE_INCOMPLETE, "error", KIND)]
    assert short.blueprint is None
    assert "counted 2" in short.findings[0].message and T in short.findings[0].message

    twice = ran(probing(seeded_probe(), seeded_probe()))
    assert rules(twice) == [(RULE_INCOMPLETE, "error", KIND)]
    assert twice.blueprint is None
