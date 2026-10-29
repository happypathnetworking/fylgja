"""The CTM's intrinsic rules against the core's (`internal/validate`'s Intrinsic): every
CTM under tests/data/ctm/ refused word for word as Go refuses it, by the findings Go writes
beside them (intrinsic.json, `go test ./internal/validate -run
TestTheOrchestratorsIntrinsicCases -update`), and the Go tests' own cases carried over."""

import copy
import json
from pathlib import Path

import pytest

from fylgja_orchestrator.adapters.infrahub import validate
from fylgja_orchestrator.documents.findings import REJECTION, Finding, quote

DATA = Path(__file__).resolve().parents[1] / "data" / "ctm"
REPO = Path(__file__).resolve().parents[3]
EXPECTED = json.loads((DATA / "intrinsic.json").read_text())

N1N2 = "n1:ethernet-1/1|n2:ethernet-1/1"
N2N3 = "n2:ethernet-1/2|n3:ethernet-1/1"
N1N3 = "n1:ethernet-1/1|n3:ethernet-1/3"
RULE = "an interface names the one link it terminates"


def load(name):
    return json.loads((DATA / name).read_text())


def rejection(rule, obj, message):
    return Finding(REJECTION, rule, obj, message)


def as_dicts(found):
    return [{"severity": f.severity, "rule": f.rule, "object": f.object, "message": f.message} for f in found]


def test_every_ctm_has_go_s_findings():
    on_disk = {p.relative_to(DATA).as_posix() for p in DATA.rglob("*.json")} - {"intrinsic.json"}
    assert on_disk == set(EXPECTED)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_intrinsic_is_go_s_word_for_word(name):
    assert as_dicts(validate.intrinsic(load(name))) == EXPECTED[name]


@pytest.mark.parametrize("name", [n for n in sorted(EXPECTED) if not n.startswith("cases/")])
def test_each_copy_is_the_repositorys_fixture(name):
    # A fixture that moves under testdata/ctm/ is copied again, and intrinsic.json rewritten.
    assert (DATA / name).read_bytes() == (REPO / "testdata" / "ctm" / name).read_bytes()


# internal/validate's TestIntrinsicRefusesWhatNeedsNoPackage: the defects a rule here
# refuses, under the rule and object Validate gives them, and none of those whose fault
# needs a package.
INTRINSIC_DEFECTS = {
    "device-duplicate.json": ("device.name.duplicate", "n1"),
    "devices-empty.json": ("ctm.devices.empty", "fylgja-fixture"),
    "link-one-endpoint.json": ("link.endpoints.count", "n1:ethernet-1/1|n2:ethernet-1/1"),
    "link-same-device.json": ("link.endpoints.same_device", "n1:ethernet-1/1|n1:ethernet-1/2"),
    "required-missing.json": ("data.required.missing", "envelope.schema_hash"),
}
PACKAGE_DEFECTS = [
    "platform-unsupported.json",
    "port-collision.json",
    "breakout-parent-cabled.json",
    "rule-unmatched.json",
    "unmappable-linked-range.json",
    "unmappable-linked-unmatched.json",
]


@pytest.mark.parametrize("fixture", sorted(INTRINSIC_DEFECTS))
def test_intrinsic_refuses_what_needs_no_package(fixture):
    ctm = load(f"defects/{fixture}")
    rule, obj = INTRINSIC_DEFECTS[fixture]
    at = ctm["envelope"].get("at", "")
    found = validate.intrinsic(ctm)
    assert found.rejected
    assert any(f.rule == rule and f.object in (obj, f"{obj}@{at}") for f in found), found


@pytest.mark.parametrize("fixture", PACKAGE_DEFECTS)
def test_intrinsic_leaves_a_package_s_fault_to_the_compile(fixture):
    assert not validate.intrinsic(load(f"defects/{fixture}")).rejected


@pytest.mark.parametrize("name", ["three-node.json", "lossy.json", "mixed.json"])
def test_a_fixture_that_compiles_passes(name):
    assert list(validate.intrinsic(load(name))) == []


def test_all_five_defects_come_in_one_pass():
    rules = {f.rule for f in validate.intrinsic(load("defects/five.json"))}
    assert {"device.name.duplicate", "link.endpoints.count", "link.endpoints.same_device"} <= rules


def test_a_nameless_interface_is_named_on_any_platform():
    ctm = load("three-node.json")
    n1 = ctm["devices"][0]
    n1["platform"]["package"] = "no_such_package"
    next(i for i in n1["interfaces"] if not i.get("link"))["name"] = ""
    assert list(validate.intrinsic(ctm)) == [rejection("data.required.missing", "n1", "an interface has no name")]


# internal/validate's envelopeCases: each change to three-node's envelope, the one finding
# it is refused with, or none.
ENVELOPE_CASES = [
    ("scope fylgja", lambda e: e.update(scope="fylgja"), "envelope.scope",
     'the scope intent was read under is "fylgja", which is not a scope: '
     "the accepted form is tag:<name>, the literal tag: and one word"),
    ("scope tag:", lambda e: e.update(scope="tag:"), "envelope.scope",
     'the scope intent was read under is "tag:", which is not a scope: '
     "the accepted form is tag:<name>, the literal tag: and one word"),
    ("scope tag:a b", lambda e: e.update(scope="tag:a b"), "envelope.scope",
     'the scope intent was read under is "tag:a b", which is not a scope: '
     "the accepted form is tag:<name>, the literal tag: and one word"),
    ("scope group:x", lambda e: e.update(scope="group:x"), "envelope.scope",
     'the scope intent was read under is "group:x", which is not a scope: '
     "the accepted form is tag:<name>, the literal tag: and one word"),
    ("reader Infrahub DCIM", lambda e: e["mapping"].update(reader="Infrahub DCIM"), "envelope.mapping.reader",
     'the reader that mapped intent is named "Infrahub DCIM", which is not a reader\'s name: '
     "lowercase letters, digits and hyphens, beginning with a letter or a digit"),
    ("reader -dcim", lambda e: e["mapping"].update(reader="-dcim"), "envelope.mapping.reader",
     'the reader that mapped intent is named "-dcim", which is not a reader\'s name: '
     "lowercase letters, digits and hyphens, beginning with a letter or a digit"),
    ("a row of disposition bogus",
     lambda e: e["fidelity"].append(
         {"disposition": "bogus", "object": "c-9", "source": "DcimCable", "reason": "other than two ends (3)"}),
     "envelope.fidelity[2].disposition",
     'fidelity row 2 (c-9) has disposition "bogus": a row is approximated or omitted'),
    ("a row with no reason",
     lambda e: e["fidelity"].append({"disposition": "omitted", "object": "c-9", "source": "DcimCable", "reason": ""}),
     "envelope.fidelity[2].reason", "fidelity row 2 (c-9) records no reason"),
    ("a row with no source",
     lambda e: e["fidelity"].append(
         {"disposition": "omitted", "object": "c-9", "source": "", "reason": "other than two ends (3)"}),
     "envelope.fidelity[2].source", "fidelity row 2 (c-9) records no source"),
    ("a row with no object",
     lambda e: e["fidelity"].append(
         {"disposition": "approximated", "object": "", "source": "InterfacePhysical.role", "reason": "a reason"}),
     "envelope.fidelity[0].object", "fidelity row 0 records no object"),
    ("scope tag:other", lambda e: e.update(scope="tag:other"), "", ""),
    ("scope tag:a-b_c.d", lambda e: e.update(scope="tag:a-b_c.d"), "", ""),
    ("reader netbox-dcim", lambda e: e["mapping"].update(reader="netbox-dcim"), "", ""),
    ("reader 0", lambda e: e["mapping"].update(reader="0"), "", ""),
    ("no fidelity row", lambda e: e.update(fidelity=None), "", ""),
    ("an omitted cable",
     lambda e: e["fidelity"].append(
         {"disposition": "omitted", "object": "c-9", "source": "DcimCable", "reason": "other than two ends (3)"}),
     "", ""),
]


@pytest.mark.parametrize("name,change,obj,message", ENVELOPE_CASES, ids=[c[0] for c in ENVELOPE_CASES])
def test_envelope_forms_are_held(name, change, obj, message):
    ctm = load("three-node.json")
    change(ctm["envelope"])
    found = list(validate.intrinsic(ctm))
    assert found == ([rejection("data.required.missing", obj, message)] if obj else [])


@pytest.mark.parametrize("field", ["scope", "reader"])
def test_an_empty_envelope_field_is_named_once(field):
    ctm = load("three-node.json")
    if field == "scope":
        ctm["envelope"]["scope"] = ""
    else:
        ctm["envelope"]["mapping"]["reader"] = ""
    found = validate.intrinsic(ctm)
    assert len(found) == 1 and found[0].message.endswith("is not recorded")


@pytest.mark.parametrize(
    "field",
    ["branch", "observed_at", "schema_hash", "scope", "mapping.reader", "mapping.model", "mapping.version"],
)
def test_envelope_required_fields_are_named(field):
    ctm = load("three-node.json")
    *path, key = field.split(".")
    target = ctm["envelope"]
    for p in path:
        target = target[p]
    target[key] = ""
    assert any(f.rule == "data.required.missing" and f.object == f"envelope.{field}" for f in validate.intrinsic(ctm))


def test_the_envelope_does_not_require_at():
    ctm = load("three-node.json")
    del ctm["envelope"]["at"]
    assert list(validate.intrinsic(ctm)) == []


@pytest.mark.parametrize("at", ["", "2026-09-08T12:00:00Z"])
def test_an_empty_ctm_is_refused_naming_the_reference(at):
    ctm = load("three-node.json")
    ctm["devices"], ctm["links"] = [], []
    ctm["envelope"]["at"] = at
    obj = "fylgja-fixture" + (f"@{at}" if at else "")
    where = 'branch "fylgja-fixture"' + (f" at {at}" if at else "")
    assert list(validate.intrinsic(ctm)) == [
        rejection(
            "ctm.devices.empty",
            obj,
            f"no devices in intent for {where}; a twin of nothing cannot be built and has no fidelity to report",
        )
    ]


def _add_n3_port(link):
    def change(ctm):
        n3 = next(d for d in ctm["devices"] if d["name"] == "n3")
        n3["interfaces"].append({"name": "ethernet-1/3", "mgmt_only": False, "link": link})

    return change


def _n2_e1(link):
    def change(ctm):
        n2 = next(d for d in ctm["devices"] if d["name"] == "n2")
        port = next(i for i in n2["interfaces"] if i["name"] == "ethernet-1/1")
        port["link"] = link

    return change


def _two_on_one(ctm):
    _add_n3_port(N1N3)(ctm)
    ctm["links"].append(
        {"id": N1N3, "endpoints": [{"device": "n1", "interface": "ethernet-1/1"},
                                   {"device": "n3", "interface": "ethernet-1/3"}]}
    )


# internal/validate's TestLinkFieldsAndLinksAgree.
LINK_CASES = [
    ("an interface two links end on", _two_on_one, "n1:ethernet-1/1",
     f"n1:ethernet-1/1 is an endpoint of 2 links ({N1N2}, {N1N3}); {RULE}"
     ", and a bundle whose links cable one port twice is never produced"),
    ("a link ending on an interface carrying no link", _n2_e1(""), N1N2,
     f"endpoint n2:ethernet-1/1 carries no link; {RULE}"
     ", and a bundle that cables a port its mapping calls configured-not-cabled is never produced"),
    ("a link ending on an interface carrying another link", _n2_e1(N2N3), N1N2,
     f'endpoint n2:ethernet-1/1 carries link "{N2N3}"; {RULE}'),
    ("an interface carrying a link not in intent", _add_n3_port(N1N3), "n3:ethernet-1/3",
     f'n3:ethernet-1/3 carries link "{N1N3}", which is not in intent; {RULE}'
     ", and a bundle that calls a port cabled with no cable on it is never produced"),
    ("an interface carrying a link that ends elsewhere", _add_n3_port(N1N2), "n3:ethernet-1/3",
     f'n3:ethernet-1/3 carries link "{N1N2}", which does not end on it; {RULE}'
     ", and a bundle that calls a port cabled with no cable on it is never produced"),
]


@pytest.mark.parametrize("name,change,obj,message", LINK_CASES, ids=[c[0] for c in LINK_CASES])
def test_link_fields_and_links_agree(name, change, obj, message):
    ctm = load("three-node.json")
    change(ctm)
    assert list(validate.intrinsic(ctm)) == [rejection("data.required.missing", obj, message)]


def test_intrinsic_normalizes_in_place_and_reads_a_shuffled_ctm_alike():
    shuffled, fixture = load("three-node.shuffled.json"), load("three-node.json")
    assert list(validate.intrinsic(shuffled)) == []
    assert [d["name"] for d in shuffled["devices"]] == [d["name"] for d in fixture["devices"]]


@pytest.mark.parametrize(
    "value,want",
    [
        ("fylgja", '"fylgja"'),
        ('a"b\\c', '"a\\"b\\\\c"'),
        ("\t\n\x01\x7f", '"\\t\\n\\x01\\x7f"'),
        ("é😀", '"é😀"'),
        ("  ​", '"\\u2028\\u00a0\\u200b"'),
    ],
)
def test_quote_is_go_s_percent_q(value, want):
    assert quote(value) == want


def test_a_ctm_is_not_copied():
    ctm = load("three-node.shuffled.json")
    before = copy.deepcopy(ctm)
    validate.intrinsic(ctm)
    assert ctm != before
