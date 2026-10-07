package fylgja

import (
	"io/fs"
	"slices"
	"strings"
	"testing"
)

// The waypoint kind ships in the binary beside the contract (M10): the schema/*.yaml
// glob takes it, and the file
// embedded is the kind the waypoint reader checks for.
func TestTheWaypointKindIsEmbedded(t *testing.T) {
	names, err := fs.Glob(Data, "schema/*.yaml")
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"schema/fylgja-generics.yaml", "schema/reference.yaml", "schema/fylgja-waypoint.yaml"} {
		if !slices.Contains(names, want) {
			t.Errorf("the embedded schema files are %v; %s is not among them", names, want)
		}
	}
	raw, err := Data.ReadFile("schema/fylgja-waypoint.yaml")
	if err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"name: Waypoint", "namespace: Fylgja", "branch: agnostic", "name: as_of"} {
		if !strings.Contains(string(raw), want) {
			t.Errorf("the embedded schema/fylgja-waypoint.yaml carries no %q", want)
		}
	}
}
