package intent_test

import (
	"reflect"
	"slices"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
)

// checkConformance runs the check against the fake the way `schema check` and every read
// run it.
func checkConformance(t *testing.T, f *fakeInfrahub) (*intent.Conformance, findings.List) {
	t.Helper()
	f.start("sentinel-token")
	cfg, err := intent.FromEnv(f.branch, "")
	if err != nil {
		t.Fatal(err)
	}
	conf, list, err := intent.New(cfg).CheckConformance(t.Context())
	if err != nil {
		t.Fatalf("checking conformance: %v", err)
	}
	return conf, list
}

// The schema document's mutations, each one a branch's schema could have: a kind, a
// field, a choice or an implementer gone, or a field's property changed.

// schemaList is one of the document's lists: its nodes, its generics, or a node's
// attributes or relationships.
func schemaList(t *testing.T, m map[string]any, key string) []any {
	t.Helper()
	l, ok := m[key].([]any)
	if !ok {
		t.Fatalf("the schema document has no list %s", key)
	}
	return l
}

// entry is the list's member whose key holds name.
func entry(t *testing.T, l []any, key, name string) map[string]any {
	t.Helper()
	for _, e := range l {
		if m := e.(map[string]any); m[key] == name {
			return m
		}
	}
	t.Fatalf("the schema document has no %s %s", key, name)
	return nil
}

// without is l less the member whose key holds name.
func without(l []any, key, name string) []any {
	out := make([]any, 0, len(l))
	for _, e := range l {
		if e.(map[string]any)[key] != name {
			out = append(out, e)
		}
	}
	return out
}

// member is a node's attribute or relationship.
func member(t *testing.T, doc map[string]any, kind, section, name string) map[string]any {
	t.Helper()
	return entry(t, schemaList(t, entry(t, schemaList(t, doc, "nodes"), "kind", kind), section), "name", name)
}

func dropNode(t *testing.T, doc map[string]any, kind string) {
	doc["nodes"] = without(schemaList(t, doc, "nodes"), "kind", kind)
}

func dropMember(t *testing.T, doc map[string]any, kind, section, name string) {
	node := entry(t, schemaList(t, doc, "nodes"), "kind", kind)
	node[section] = without(schemaList(t, node, section), "name", name)
}

func dropChoice(t *testing.T, doc map[string]any, kind, attribute, choice string) {
	attr := member(t, doc, kind, "attributes", attribute)
	attr["choices"] = without(schemaList(t, attr, "choices"), "name", choice)
}

func dropImplementer(t *testing.T, doc map[string]any, generic, kind string) {
	g := entry(t, schemaList(t, doc, "generics"), "kind", generic)
	var kept []any
	for _, k := range schemaList(t, g, "used_by") {
		if k != kind {
			kept = append(kept, k)
		}
	}
	g["used_by"] = kept
}

// The mutations each case below is made of. DcimCable gone takes it out of
// DcimConnector's used_by too, as Infrahub's endpoint would.
var (
	cableGone = func(t *testing.T, doc map[string]any) {
		dropNode(t, doc, "DcimCable")
		dropImplementer(t, doc, "DcimConnector", "DcimCable")
	}
	roleGone           = func(t *testing.T, doc map[string]any) { dropMember(t, doc, "InterfacePhysical", "attributes", "role") }
	platformNameNumber = func(t *testing.T, doc map[string]any) {
		member(t, doc, "DcimPlatform", "attributes", "name")["kind"] = "Number"
	}
	platformManyNet = func(t *testing.T, doc map[string]any) {
		rel := member(t, doc, "DcimDevice", "relationships", "platform")
		rel["cardinality"], rel["peer"] = "many", "NetPlatform"
	}
	deviceNameOptional = func(t *testing.T, doc map[string]any) {
		member(t, doc, "DcimDevice", "attributes", "name")["optional"] = true
	}
	managementGone = func(t *testing.T, doc map[string]any) { dropChoice(t, doc, "InterfacePhysical", "role", "management") }
	disabledGone   = func(t *testing.T, doc map[string]any) { dropChoice(t, doc, "InterfacePhysical", "status", "disabled") }
	endpointGone   = func(t *testing.T, doc map[string]any) { dropImplementer(t, doc, "DcimEndpoint", "InterfacePhysical") }
	// The cable's label names every cable the read omits (contracts/mapping.md §4), so the
	// Ports query selects it.
	cableLabelGone   = func(t *testing.T, doc map[string]any) { dropMember(t, doc, "DcimCable", "attributes", "label") }
	cableLabelNumber = func(t *testing.T, doc map[string]any) {
		member(t, doc, "DcimCable", "attributes", "label")["kind"] = "Number"
	}
)

// readsIt is the end of every conformance finding but used_by's: the commit the table was
// written against.
const readsIt = "; the mapping reads it as opsmill/schema-library@26336e9 has it"

// The library at the pinned commit conforms, and the check says what it verified: the
// model and the commit, and each kind with its fields in the table's order. It asks the
// schema endpoint alone, before any data is read.
func TestConformanceOfTheLibrary(t *testing.T) {
	f := newFakeInfrahub(t)

	conf, list := checkConformance(t, f)

	if len(list) != 0 {
		t.Fatalf("the library's schema gave findings: %v", list)
	}
	if conf.Model != "opsmill/schema-library" || conf.Version != "26336e9" || conf.SchemaHash != "18e5f023994de4261ad266e61aac2615" {
		t.Errorf("model %q version %q hash %q, want the library, its commit and the document's hash", conf.Model, conf.Version, conf.SchemaHash)
	}
	want := []findings.KindFields{
		{Kind: "DcimDevice", Fields: []string{"name", "tags", "platform", "interfaces", "artifacts"}},
		{Kind: "DcimPlatform", Fields: []string{"name", "manufacturer"}},
		{Kind: "OrganizationManufacturer", Fields: []string{"name"}},
		{Kind: "InterfacePhysical", Fields: []string{"name", "role", "status", "device", "connector"}},
		{Kind: "DcimCable", Fields: []string{"label", "connected_endpoints"}},
	}
	if !reflect.DeepEqual(conf.Kinds, want) {
		t.Errorf("kinds %+v, want %+v", conf.Kinds, want)
	}
	if v := conf.Verified(); v.Model != conf.Model || v.Version != conf.Version || !reflect.DeepEqual(v.Kinds, want) {
		t.Errorf("verified %+v, want the conformance's model, version and kinds", v)
	}
	if n := f.count("/graphql/" + f.branch); n != 0 {
		t.Errorf("conformance asked GraphQL %d times; it reads the schema endpoint alone", n)
	}
}

// Each kind, field, property, choice or implementer the table names, gone or changed, is
// one rejection naming it and the commit (FR-012; US3 scenario 2). A kind gone is named
// once: neither its fields nor the generic it implemented are named beside it.
func TestConformanceNamesWhatDiffers(t *testing.T) {
	for _, c := range []struct {
		name   string
		mutate func(*testing.T, map[string]any)
		want   findings.Finding
	}{
		{"DcimCable gone", cableGone, findings.Finding{Rule: findings.RuleSchemaKindMissing, Object: "DcimCable",
			Message: "the branch's schema has no kind DcimCable" + readsIt}},
		{"InterfacePhysical.role gone", roleGone, findings.Finding{Rule: findings.RuleSchemaFieldMissing, Object: "InterfacePhysical.role",
			Message: "InterfacePhysical has no attribute role" + readsIt}},
		{"InterfacePhysical.connector gone", func(t *testing.T, doc map[string]any) {
			dropMember(t, doc, "InterfacePhysical", "relationships", "connector")
		}, findings.Finding{Rule: findings.RuleSchemaFieldMissing, Object: "InterfacePhysical.connector",
			Message: "InterfacePhysical has no relationship connector" + readsIt}},
		{"DcimPlatform.name a Number", platformNameNumber, findings.Finding{Rule: findings.RuleSchemaFieldMismatch, Object: "DcimPlatform.name",
			Message: "kind Text, found Number" + readsIt}},
		{"DcimDevice.platform many, to NetPlatform", platformManyNet, findings.Finding{Rule: findings.RuleSchemaFieldMismatch,
			Object: "DcimDevice.platform", Message: "peer DcimPlatform, found NetPlatform; cardinality one, found many" + readsIt}},
		{"DcimDevice.name optional", deviceNameOptional, findings.Finding{Rule: findings.RuleSchemaFieldMismatch, Object: "DcimDevice.name",
			Message: "optional false, found true" + readsIt}},
		{"InterfacePhysical.device optional", func(t *testing.T, doc map[string]any) {
			member(t, doc, "InterfacePhysical", "relationships", "device")["optional"] = true
		}, findings.Finding{Rule: findings.RuleSchemaFieldMismatch, Object: "InterfacePhysical.device",
			Message: "optional false, found true" + readsIt}},
		{"management gone from role", managementGone, findings.Finding{Rule: findings.RuleSchemaChoiceMissing, Object: "InterfacePhysical.role",
			Message: "the dropdown has no choice management" + readsIt}},
		{"disabled gone from status", disabledGone, findings.Finding{Rule: findings.RuleSchemaChoiceMissing, Object: "InterfacePhysical.status",
			Message: "the dropdown has no choice disabled" + readsIt}},
		{"InterfacePhysical gone from DcimEndpoint's used_by", endpointGone, findings.Finding{Rule: findings.RuleSchemaUsedByMissing,
			Object: "DcimEndpoint", Message: "InterfacePhysical does not implement DcimEndpoint; the mapping reads InterfacePhysical " +
				"through it as opsmill/schema-library@26336e9 has it"}},
		{"DcimEndpoint gone", func(t *testing.T, doc map[string]any) {
			doc["generics"] = without(schemaList(t, doc, "generics"), "kind", "DcimEndpoint")
		}, findings.Finding{Rule: findings.RuleSchemaUsedByMissing, Object: "DcimEndpoint",
			Message: "the branch's schema has no generic DcimEndpoint; the mapping reads InterfacePhysical " +
				"through it as opsmill/schema-library@26336e9 has it"}},
		{"DcimCable.label gone", cableLabelGone, findings.Finding{Rule: findings.RuleSchemaFieldMissing, Object: "DcimCable.label",
			Message: "DcimCable has no attribute label" + readsIt}},
		{"DcimCable.label a Number", cableLabelNumber, findings.Finding{Rule: findings.RuleSchemaFieldMismatch, Object: "DcimCable.label",
			Message: "kind Text, found Number" + readsIt}},
		{"InterfacePhysical gone", func(t *testing.T, doc map[string]any) {
			dropNode(t, doc, "InterfacePhysical")
			dropImplementer(t, doc, "DcimInterface", "InterfacePhysical")
			dropImplementer(t, doc, "DcimEndpoint", "InterfacePhysical")
		}, findings.Finding{Rule: findings.RuleSchemaKindMissing, Object: "InterfacePhysical",
			Message: "the branch's schema has no kind InterfacePhysical" + readsIt}},
	} {
		t.Run(c.name, func(t *testing.T) {
			f := newFakeInfrahub(t)
			c.mutate(t, f.schema)

			_, list := checkConformance(t, f)

			c.want.Severity = findings.Rejection
			if len(list) != 1 || list[0] != c.want {
				t.Fatalf("findings %+v, want exactly %+v", list, c.want)
			}
		})
	}
}

// Every difference comes in one pass (SC-004), in the table's order and then the
// generics': an operator setting a branch up needs no second run to see the next one.
func TestConformanceNamesEveryDifferenceInOnePass(t *testing.T) {
	f := newFakeInfrahub(t)
	for _, mutate := range []func(*testing.T, map[string]any){
		cableGone, roleGone, platformNameNumber, platformManyNet, deviceNameOptional, disabledGone, endpointGone,
	} {
		mutate(t, f.schema)
	}

	_, list := checkConformance(t, f)

	type got struct{ rule, object string }
	var rules []got
	for _, fd := range list {
		rules = append(rules, got{fd.Rule, fd.Object})
		if fd.Severity != findings.Rejection || !strings.Contains(fd.Message, "opsmill/schema-library@26336e9") {
			t.Errorf("%s %s: %s %q; every finding is a rejection naming the commit", fd.Rule, fd.Object, fd.Severity, fd.Message)
		}
	}
	want := []got{
		{findings.RuleSchemaFieldMismatch, "DcimDevice.name"},
		{findings.RuleSchemaFieldMismatch, "DcimDevice.platform"},
		{findings.RuleSchemaFieldMismatch, "DcimPlatform.name"},
		{findings.RuleSchemaFieldMissing, "InterfacePhysical.role"},
		{findings.RuleSchemaChoiceMissing, "InterfacePhysical.status"},
		{findings.RuleSchemaKindMissing, "DcimCable"},
		{findings.RuleSchemaUsedByMissing, "DcimEndpoint"},
	}
	if !slices.Equal(rules, want) {
		t.Errorf("findings %v, want %v", rules, want)
	}
}

// What the table does not name is never reported (FR-012; US3 scenario 3): a kind of the
// operator's own, a field they added to a kind the mapping reads, a choice beyond the
// mapping's, an implementer beside the expected one, and an optional field the table
// leaves optional read as required.
func TestConformanceIgnoresWhatTheTableDoesNotName(t *testing.T) {
	f := newFakeInfrahub(t)
	f.schema["nodes"] = append(schemaList(t, f.schema, "nodes"), map[string]any{
		"kind": "AcmeWidget", "attributes": []any{map[string]any{"name": "name", "kind": "Number", "optional": true}},
		"relationships": []any{},
	})
	device := entry(t, schemaList(t, f.schema, "nodes"), "kind", "DcimDevice")
	device["attributes"] = append(schemaList(t, device, "attributes"),
		map[string]any{"name": "acme_asset_tag", "kind": "Text", "optional": false})
	device["relationships"] = append(schemaList(t, device, "relationships"),
		map[string]any{"name": "acme_owner", "peer": "AcmeWidget", "kind": "Attribute", "cardinality": "one", "optional": false})
	role := member(t, f.schema, "InterfacePhysical", "attributes", "role")
	role["choices"] = append(schemaList(t, role, "choices"), map[string]any{"name": "acme_backplane"})
	role["optional"] = false
	member(t, f.schema, "DcimDevice", "relationships", "platform")["optional"] = false
	// Fields the mapping does not read, changed: the reader never reads them (FR-010).
	member(t, f.schema, "DcimDevice", "attributes", "description")["kind"] = "Number"
	dropMember(t, f.schema, "DcimDevice", "attributes", "status")
	g := entry(t, schemaList(t, f.schema, "generics"), "kind", "DcimEndpoint")
	g["used_by"] = append(schemaList(t, g, "used_by"), "AcmeWidget")

	if _, list := checkConformance(t, f); len(list) != 0 {
		t.Errorf("findings %+v, want none: nothing the table names differs", list)
	}
}

// A branch that does not conform refuses the read with the same findings schema check
// gives, before any data is read, and no CTM (US3 scenario 4; FR-011).
func TestReadIsRefusedByConformance(t *testing.T) {
	f := newFakeInfrahub(t)
	cableGone(t, f.schema)
	roleGone(t, f.schema)

	snapshot, list, err := readFake(t, f)

	if err != nil {
		t.Fatal(err)
	}
	if snapshot != nil {
		t.Error("a read refused by conformance produced a CTM")
	}
	if len(list) != 2 || list[0].Object != "InterfacePhysical.role" || list[1].Object != "DcimCable" || !list.Rejected() {
		t.Errorf("findings %+v, want InterfacePhysical.role's and DcimCable's alone", list)
	}
	if n := f.count("/graphql/" + f.branch); n != 0 {
		t.Errorf("a refused read asked GraphQL %d times", n)
	}
}

// A branch whose DcimCable lacks the label the Ports query selects is refused by
// conformance before any query, where the query would have failed naming nothing of the
// table; the label of another kind likewise (FR-012; US3 scenario 4).
func TestReadIsRefusedWithoutTheCablesLabel(t *testing.T) {
	for _, mutate := range []func(*testing.T, map[string]any){cableLabelGone, cableLabelNumber} {
		f := newFakeInfrahub(t)
		mutate(t, f.schema)

		snapshot, list, err := readFake(t, f)

		if err != nil {
			t.Fatal(err)
		}
		if snapshot != nil || len(list) != 1 || list[0].Object != "DcimCable.label" || !list.Rejected() {
			t.Errorf("CTM %v, findings %+v; want no CTM and DcimCable.label's finding alone", snapshot != nil, list)
		}
		if n := f.count("/graphql/" + f.branch); n != 0 {
			t.Errorf("a refused read asked GraphQL %d times; the Ports query above all must not be sent", n)
		}
	}
}
