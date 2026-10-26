package findings

import (
	"encoding/json"
	"strings"
	"testing"
)

// libraryVerified is schema check's success detail as the Infrahub reader writes it for
// a conformant branch (017): the library, its commit, and the mapping's five kinds and the
// generic it reads a field of, with their fields in the table's order (internal/intent/mapping.go, which this package
// cannot import), beside stages when given.
func libraryVerified(stages *StagesVerified) *Verified {
	return &Verified{
		Model:   "opsmill/schema-library",
		Version: "26336e9",
		Kinds: []KindFields{
			{Kind: "DcimDevice", Fields: []string{"name", "tags", "platform", "interfaces", "artifacts"}},
			{Kind: "DcimPlatform", Fields: []string{"name", "manufacturer"}},
			{Kind: "OrganizationManufacturer", Fields: []string{"name"}},
			{Kind: "InterfacePhysical", Fields: []string{"name", "role", "status", "device", "connector"}},
			{Kind: "DcimCable", Fields: []string{"label", "connected_endpoints"}},
			{Kind: "DcimConnector", Fields: []string{"connected_endpoints"}},
		},
		Stages: stages,
	}
}

// verified is {model, version, kinds: [{kind, fields}], stages} as the current contract
// defines it (017): the generics contract's contract_version and generics are gone, and a
// block naming no kind, or a kind no field, says nothing was verified.
func TestVerifiedIsTheMappingsTable(t *testing.T) {
	schema := compileCurrentFindingsSchema(t)
	doc := NewDocument(OpSchemaCheck, &Subject{Branch: "fylgja-fixture"}, nil)
	doc.Verified = libraryVerified(nil)
	mustValidate(t, schema, doc, "a conformant schema check")
	want := `"verified":{"model":"opsmill/schema-library","version":"26336e9","kinds":[` +
		`{"kind":"DcimDevice","fields":["name","tags","platform","interfaces","artifacts"]},` +
		`{"kind":"DcimPlatform","fields":["name","manufacturer"]},` +
		`{"kind":"OrganizationManufacturer","fields":["name"]},` +
		`{"kind":"InterfacePhysical","fields":["name","role","status","device","connector"]},` +
		`{"kind":"DcimCable","fields":["label","connected_endpoints"]},` +
		`{"kind":"DcimConnector","fields":["connected_endpoints"]}]}`
	if b := string(mustMarshal(t, doc)); !strings.Contains(b, want) {
		t.Errorf("the document does not carry\n%s\n%s", want, b)
	}

	for label, change := range map[string]func(v map[string]any){
		"contract_version":      func(v map[string]any) { v["contract_version"] = "0.2" },
		"generics":              func(v map[string]any) { v["generics"] = []any{} },
		"no model":              func(v map[string]any) { delete(v, "model") },
		"no version":            func(v map[string]any) { delete(v, "version") },
		"no kinds":              func(v map[string]any) { delete(v, "kinds") },
		"no kind in kinds":      func(v map[string]any) { v["kinds"] = []any{} },
		"a kind with no fields": func(v map[string]any) { v["kinds"].([]any)[0].(map[string]any)["fields"] = []any{} },
	} {
		var generic map[string]any
		if err := json.Unmarshal(mustMarshal(t, doc), &generic); err != nil {
			t.Fatal(err)
		}
		change(generic["verified"].(map[string]any))
		if err := schema.Validate(generic); err == nil {
			t.Errorf("verified with %s satisfied the current findings.schema.json", label)
		}
	}
}
