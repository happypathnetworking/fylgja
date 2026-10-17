package fylgja

import (
	"io/fs"
	"slices"
	"strings"
	"testing"
)

// The stage kind ships in the binary beside the contract (D-045): the schema/*.yaml glob
// takes it, and the file embedded is the kind, its label's pattern and its extension of
// the proposed change that --stage, stage list and stage plan read.
func TestTheStageKindIsEmbedded(t *testing.T) {
	names, err := fs.Glob(Data, "schema/*.yaml")
	if err != nil {
		t.Fatal(err)
	}
	if !slices.Contains(names, "schema/fylgja-stage.yaml") {
		t.Errorf("the embedded schema files are %v; schema/fylgja-stage.yaml is not among them", names)
	}
	raw, err := Data.ReadFile("schema/fylgja-stage.yaml")
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"name: Stage", "namespace: Fylgja", "branch: agnostic", "name: as_of",
		"name: description", `regex: "^[^/\\s]+$"`, "kind: CoreProposedChange", "name: fylgja_stages"} {
		if !strings.Contains(string(raw), want) {
			t.Errorf("the embedded schema/fylgja-stage.yaml carries no %q", want)
		}
	}
}
