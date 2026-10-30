"""Conformance against the core's (`internal/intent`'s conformance_test.go), on the recorded
`GET /api/schema` answer for the library at 26336e9 (tests/data/schema/, copied from
internal/intent/testdata/ and held to it until the Go reader went, T035), each case a change
to it a branch's schema could have."""

from pathlib import Path

import pytest

from fylgja_orchestrator.adapters.infrahub import mapping, schema
from fylgja_orchestrator.documents.findings import REJECTION

DATA = Path(__file__).resolve().parents[1] / "data" / "schema"

READS_IT = "; the mapping reads it as opsmill/schema-library@26336e9 has it"


def entry(items, key, name):
    return next(e for e in items if e.get(key) == name)


def without(items, key, name):
    return [e for e in items if e.get(key) != name]


def member(doc, kind, section, name):
    return entry(entry(doc["nodes"], "kind", kind)[section], "name", name)


def generic_member(doc, generic, section, name):
    return entry(entry(doc["generics"], "kind", generic)[section], "name", name)


def drop_node(doc, kind):
    doc["nodes"] = without(doc["nodes"], "kind", kind)


def drop_member(doc, kind, section, name):
    node = entry(doc["nodes"], "kind", kind)
    node[section] = without(node[section], "name", name)


def drop_choice(doc, kind, attribute, choice):
    attr = member(doc, kind, "attributes", attribute)
    attr["choices"] = without(attr["choices"], "name", choice)


def drop_implementer(doc, generic, kind):
    g = entry(doc["generics"], "kind", generic)
    g["used_by"] = [k for k in g["used_by"] if k != kind]


def drop_generic(doc, generic):
    doc["generics"] = without(doc["generics"], "kind", generic)


def cable_gone(doc):
    drop_node(doc, "DcimCable")
    drop_implementer(doc, "DcimConnector", "DcimCable")


def role_gone(doc):
    drop_member(doc, "InterfacePhysical", "attributes", "role")


def platform_name_number(doc):
    member(doc, "DcimPlatform", "attributes", "name")["kind"] = "Number"


def platform_many_net(doc):
    rel = member(doc, "DcimDevice", "relationships", "platform")
    rel["cardinality"], rel["peer"] = "many", "NetPlatform"


def device_name_optional(doc):
    member(doc, "DcimDevice", "attributes", "name")["optional"] = True


def disabled_gone(doc):
    drop_choice(doc, "InterfacePhysical", "status", "disabled")


def endpoint_gone(doc):
    drop_implementer(doc, "DcimEndpoint", "InterfacePhysical")


def cable_label_gone(doc):
    drop_member(doc, "DcimCable", "attributes", "label")


def cable_label_number(doc):
    member(doc, "DcimCable", "attributes", "label")["kind"] = "Number"


def connector_endpoints_moved(doc):
    g = entry(doc["generics"], "kind", "DcimConnector")
    g["relationships"] = without(g["relationships"], "name", "connected_endpoints")
    member(doc, "DcimCable", "relationships", "connected_endpoints")["inherited"] = False


def connector_endpoints_to_interfaces(doc):
    generic_member(doc, "DcimConnector", "relationships", "connected_endpoints")["peer"] = "DcimInterface"


def connector_endpoints_one(doc):
    generic_member(doc, "DcimConnector", "relationships", "connected_endpoints")["cardinality"] = "one"


def interface_physical_gone(doc):
    drop_node(doc, "InterfacePhysical")
    drop_implementer(doc, "DcimInterface", "InterfacePhysical")
    drop_implementer(doc, "DcimEndpoint", "InterfacePhysical")


def check(client):
    return schema.check_conformance(client)


def test_the_table_is_the_core_s():
    assert [(k.kind, k.fields()) for k in mapping.TABLES] == [
        ("DcimDevice", ["name", "tags", "platform", "interfaces", "artifacts"]),
        ("DcimPlatform", ["name", "manufacturer"]),
        ("OrganizationManufacturer", ["name"]),
        ("InterfacePhysical", ["name", "role", "status", "device", "connector"]),
        ("DcimCable", ["label", "connected_endpoints"]),
        ("DcimConnector", ["connected_endpoints"]),
    ]
    assert (mapping.READER, mapping.MODEL, mapping.VERSION) == ("infrahub-dcim", "opsmill/schema-library", "26336e9")


def test_conformance_of_the_library(infrahub, client_for):
    conf, found = check(client_for())
    assert list(found) == []
    assert (conf.model, conf.version, conf.schema_hash) == (
        "opsmill/schema-library",
        "26336e9",
        "18e5f023994de4261ad266e61aac2615",
    )
    assert conf.verified() == {
        "model": "opsmill/schema-library",
        "version": "26336e9",
        "kinds": [{"kind": k.kind, "fields": k.fields()} for k in mapping.TABLES],
    }
    assert infrahub.count("/graphql/fylgja-fixture") == 0
    assert infrahub.count("/api/schema") == 1


CASES = [
    ("DcimCable gone", cable_gone, "schema.kind.missing", "DcimCable",
     "the branch's schema has no kind DcimCable" + READS_IT),
    ("InterfacePhysical.role gone", role_gone, "schema.field.missing", "InterfacePhysical.role",
     "InterfacePhysical has no attribute role" + READS_IT),
    ("InterfacePhysical.connector gone", lambda d: drop_member(d, "InterfacePhysical", "relationships", "connector"),
     "schema.field.missing", "InterfacePhysical.connector",
     "InterfacePhysical has no relationship connector" + READS_IT),
    ("DcimPlatform.name a Number", platform_name_number, "schema.field.mismatch", "DcimPlatform.name",
     "kind Text, found Number" + READS_IT),
    ("DcimDevice.platform many, to NetPlatform", platform_many_net, "schema.field.mismatch", "DcimDevice.platform",
     "peer DcimPlatform, found NetPlatform; cardinality one, found many" + READS_IT),
    ("DcimDevice.name optional", device_name_optional, "schema.field.mismatch", "DcimDevice.name",
     "optional false, found true" + READS_IT),
    ("InterfacePhysical.device optional",
     lambda d: member(d, "InterfacePhysical", "relationships", "device").update(optional=True),
     "schema.field.mismatch", "InterfacePhysical.device", "optional false, found true" + READS_IT),
    ("management gone from role", lambda d: drop_choice(d, "InterfacePhysical", "role", "management"),
     "schema.choice.missing", "InterfacePhysical.role", "the dropdown has no choice management" + READS_IT),
    ("disabled gone from status", disabled_gone, "schema.choice.missing", "InterfacePhysical.status",
     "the dropdown has no choice disabled" + READS_IT),
    ("InterfacePhysical gone from DcimEndpoint's used_by", endpoint_gone, "schema.used_by.missing", "DcimEndpoint",
     "InterfacePhysical does not implement DcimEndpoint; the mapping reads InterfacePhysical "
     "through it as opsmill/schema-library@26336e9 has it"),
    ("DcimEndpoint gone", lambda d: drop_generic(d, "DcimEndpoint"), "schema.used_by.missing", "DcimEndpoint",
     "the branch's schema has no generic DcimEndpoint; the mapping reads InterfacePhysical "
     "through it as opsmill/schema-library@26336e9 has it"),
    ("DcimCable.label gone", cable_label_gone, "schema.field.missing", "DcimCable.label",
     "DcimCable has no attribute label" + READS_IT),
    ("DcimCable.label a Number", cable_label_number, "schema.field.mismatch", "DcimCable.label",
     "kind Text, found Number" + READS_IT),
    ("DcimConnector.connected_endpoints moved to DcimCable", connector_endpoints_moved, "schema.field.missing",
     "DcimConnector.connected_endpoints", "DcimConnector has no relationship connected_endpoints" + READS_IT),
    ("DcimConnector.connected_endpoints to DcimInterface", connector_endpoints_to_interfaces,
     "schema.field.mismatch", "DcimConnector.connected_endpoints", "peer DcimEndpoint, found DcimInterface" + READS_IT),
    ("DcimConnector.connected_endpoints of one", connector_endpoints_one, "schema.field.mismatch",
     "DcimConnector.connected_endpoints", "cardinality many, found one" + READS_IT),
    # The generic gone is its used_by's one finding, never its field named beside it.
    ("DcimConnector gone", lambda d: drop_generic(d, "DcimConnector"), "schema.used_by.missing", "DcimConnector",
     "the branch's schema has no generic DcimConnector; the mapping reads DcimCable "
     "through it as opsmill/schema-library@26336e9 has it"),
    ("InterfacePhysical gone", interface_physical_gone, "schema.kind.missing", "InterfacePhysical",
     "the branch's schema has no kind InterfacePhysical" + READS_IT),
]


@pytest.mark.parametrize("name,mutate,rule,obj,message", CASES, ids=[c[0] for c in CASES])
def test_conformance_names_what_differs(infrahub, client_for, name, mutate, rule, obj, message):
    mutate(infrahub.schema)
    _, found = check(client_for())
    assert [(f.severity, f.rule, f.object, f.message) for f in found] == [(REJECTION, rule, obj, message)]


def test_conformance_names_every_difference_in_one_pass(infrahub, client_for):
    for mutate in (cable_gone, role_gone, platform_name_number, platform_many_net, device_name_optional,
                   disabled_gone, endpoint_gone):
        mutate(infrahub.schema)
    _, found = check(client_for())
    assert [(f.rule, f.object) for f in found] == [
        ("schema.field.mismatch", "DcimDevice.name"),
        ("schema.field.mismatch", "DcimDevice.platform"),
        ("schema.field.mismatch", "DcimPlatform.name"),
        ("schema.field.missing", "InterfacePhysical.role"),
        ("schema.choice.missing", "InterfacePhysical.status"),
        ("schema.kind.missing", "DcimCable"),
        ("schema.used_by.missing", "DcimEndpoint"),
    ]
    assert all(f.severity == REJECTION and "opsmill/schema-library@26336e9" in f.message for f in found)


def test_conformance_ignores_what_the_table_does_not_name(infrahub, client_for):
    doc = infrahub.schema
    doc["nodes"].append({"kind": "AcmeWidget", "attributes": [{"name": "name", "kind": "Number", "optional": True}],
                         "relationships": []})
    device = entry(doc["nodes"], "kind", "DcimDevice")
    device["attributes"].append({"name": "acme_asset_tag", "kind": "Text", "optional": False})
    device["relationships"].append(
        {"name": "acme_owner", "peer": "AcmeWidget", "kind": "Attribute", "cardinality": "one", "optional": False})
    role = member(doc, "InterfacePhysical", "attributes", "role")
    role["choices"].append({"name": "acme_backplane"})
    role["optional"] = False
    member(doc, "DcimDevice", "relationships", "platform")["optional"] = False
    member(doc, "DcimDevice", "attributes", "description")["kind"] = "Number"
    drop_member(doc, "DcimDevice", "attributes", "status")
    entry(doc["generics"], "kind", "DcimEndpoint")["used_by"].append("AcmeWidget")
    _, found = check(client_for())
    assert list(found) == []


def test_a_conformance_error_names_the_branch_the_commit_and_each_finding(infrahub, client_for):
    cable_gone(infrahub.schema)
    role_gone(infrahub.schema)
    _, found = check(client_for())
    error = schema.ConformanceError("b1", found)
    assert str(error) == (
        "branch b1 does not conform to opsmill/schema-library@26336e9: "
        "schema.field.missing InterfacePhysical.role, schema.kind.missing DcimCable"
    )


def test_implementers_are_sorted(infrahub, client_for):
    info = schema.schema_info(client_for())
    assert info.implementers("DcimInterface") == ["InterfacePhysical", "InterfaceVirtual"]
    assert info.implementers("NoSuchGeneric") == []
    assert info.hash == "18e5f023994de4261ad266e61aac2615"
