package intent

import "github.com/happypathnetworking/fylgja/internal/ctm"

// The mapping's conformance table (specs/017-dcim-reader/contracts/mapping.md §3): every
// kind the Infrahub reader reads, with every field it reads, as the pinned commit of the
// schema library has them. This file is the one place in the reader that knows the
// library's kinds; conformance compares a branch's schema with it, field by field
// (CheckConformance), and names the commit in every finding.
//
// The table is what Infrahub 1.11.2's schema endpoint answered for the commit's six files
// (research §1.3), not their YAML's text: an attribute with a default reads optional
// whatever its file says, so a field the mapping does not require is never held to its
// optionality. Nothing beyond the table is checked, so a branch may carry any kind or
// field of its own beside it (FR-012).

// LibraryModel and LibraryVersion name the model the table was written against: the
// envelope's mapping, and the commit every conformance finding names.
const (
	LibraryModel   = ctm.ModelSchemaLibrary
	LibraryVersion = ctm.ModelVersion
)

// KindTable is one kind the mapping reads, with the attributes and relationships it reads.
// Generic marks a generic the mapping reads a field of through its GraphQL interface,
// outside any inline fragment, so the field must be the generic's and not only an
// implementer's. A generic absent is named by its used_by (LibraryUsedBy), never here.
type KindTable struct {
	Kind          string
	Generic       bool
	Attributes    []AttributeWant
	Relationships []RelationshipWant
}

// AttributeWant is one attribute as the mapping reads it: its kind (Text, Dropdown, …);
// whether the mapping requires it, so that the branch must read optional false; and, for
// a dropdown, the choices the mapping reads, which the branch's must include.
type AttributeWant struct {
	Name     string
	Kind     string
	Required bool
	Choices  []string
}

// RelationshipWant is one relationship as the mapping reads it: its peer, its kind
// (Attribute, Component, Parent, Generic), its cardinality, and whether the mapping
// requires it.
type RelationshipWant struct {
	Name        string
	Peer        string
	Kind        string
	Cardinality string
	Required    bool
}

// UsedByWant is a generic the mapping reaches a kind through, and the kind the generic's
// used_by must name: a port's device is a DcimGenericDevice, its connector a
// DcimConnector, a cable's ends DcimEndpoints.
type UsedByWant struct {
	Generic, Implementer string
}

// Fields names the table's fields, attributes first, in the table's order: what
// `schema check` says it verified of the kind.
func (k KindTable) Fields() []string {
	out := make([]string, 0, len(k.Attributes)+len(k.Relationships))
	for _, a := range k.Attributes {
		out = append(out, a.Name)
	}
	for _, r := range k.Relationships {
		out = append(out, r.Name)
	}
	return out
}

// LibraryTables are the five kinds the mapping reads, and the one generic it reads a field
// of, in the order `schema check` names them.
var LibraryTables = []KindTable{
	{
		Kind:       "DcimDevice",
		Attributes: []AttributeWant{{Name: "name", Kind: "Text", Required: true}},
		Relationships: []RelationshipWant{
			{Name: "tags", Peer: "BuiltinTag", Kind: "Attribute", Cardinality: "many"},
			{Name: "platform", Peer: "DcimPlatform", Kind: "Attribute", Cardinality: "one"},
			{Name: "interfaces", Peer: "DcimInterface", Kind: "Component", Cardinality: "many"},
			// From CoreArtifactTarget: the device's configuration is one of these.
			{Name: "artifacts", Peer: "CoreArtifact", Kind: "Generic", Cardinality: "many"},
		},
	},
	{
		Kind:       "DcimPlatform",
		Attributes: []AttributeWant{{Name: "name", Kind: "Text", Required: true}},
		Relationships: []RelationshipWant{
			{Name: "manufacturer", Peer: "OrganizationManufacturer", Kind: "Attribute", Cardinality: "one"},
		},
	},
	{
		Kind:       "OrganizationManufacturer",
		Attributes: []AttributeWant{{Name: "name", Kind: "Text", Required: true}},
	},
	{
		Kind: "InterfacePhysical",
		Attributes: []AttributeWant{
			{Name: "name", Kind: "Text", Required: true},
			{Name: "role", Kind: "Dropdown", Choices: []string{"management"}},
			{Name: "status", Kind: "Dropdown", Choices: []string{"disabled"}},
		},
		Relationships: []RelationshipWant{
			{Name: "device", Peer: "DcimGenericDevice", Kind: "Parent", Cardinality: "one", Required: true},
			{Name: "connector", Peer: "DcimConnector", Kind: "Attribute", Cardinality: "one"},
		},
	},
	{
		Kind: "DcimCable",
		// The Ports query selects the label, which names every cable the read omits.
		Attributes: []AttributeWant{{Name: "label", Kind: "Text"}},
		Relationships: []RelationshipWant{
			{Name: "connected_endpoints", Peer: "DcimEndpoint", Kind: "Attribute", Cardinality: "many"},
		},
	},
	{
		// The Ports query selects a port's connector's connected_endpoints on the generic,
		// outside the DcimCable fragment, so DcimCable declaring it alone does not serve.
		Kind:    "DcimConnector",
		Generic: true,
		Relationships: []RelationshipWant{
			{Name: "connected_endpoints", Peer: "DcimEndpoint", Kind: "Attribute", Cardinality: "many"},
		},
	},
}

// LibraryUsedBy are the implementers the mapping relies on.
var LibraryUsedBy = []UsedByWant{
	{Generic: "DcimGenericDevice", Implementer: "DcimDevice"},
	{Generic: "DcimInterface", Implementer: "InterfacePhysical"},
	{Generic: "DcimEndpoint", Implementer: "InterfacePhysical"},
	{Generic: "DcimConnector", Implementer: "DcimCable"},
}
