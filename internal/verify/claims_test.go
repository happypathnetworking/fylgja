package verify

import (
	"reflect"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

var (
	stagedID   = strings.Repeat("e", 64)
	previousID = strings.Repeat("3", 64)
)

func claimsOf(cs []Claim) []string {
	out := make([]string, len(cs))
	for i, c := range cs {
		holds := "null"
		if c.Holds != nil {
			holds = *c.Holds
		}
		out[i] = c.Node + " holds " + holds[:min(len(holds), 4)] + " against " + c.Staged[:4] + ": " + c.Outcome
	}
	return out
}

// One claim per record node, in name order: held when the node holds the staged bundle,
// failed when it holds the previous one or none.
func TestClaims(t *testing.T) {
	prev, staged := previousID, stagedID
	rec := wire.TwinRecord{TwinVersion: "4", BundleID: staged, State: wire.StateDiverged, Nodes: []wire.TwinNode{
		{Name: "s1", Holds: &staged},
		{Name: "e2", Holds: nil},
		{Name: "e1", Holds: &prev},
	}}
	got := Claims(rec, staged, nil)
	want := []string{
		"e1 holds 3333 against eeee: failed",
		"e2 holds null against eeee: failed",
		"s1 holds eeee against eeee: held",
	}
	if !reflect.DeepEqual(claimsOf(got), want) {
		t.Errorf("Claims = %q, want %q", claimsOf(got), want)
	}
	// The claim's holds is a copy: nothing the report does to it reaches the record.
	*got[2].Holds = "changed"
	if *rec.Nodes[0].Holds != staged {
		t.Errorf("the record's holds moved with the claim's: %q", *rec.Nodes[0].Holds)
	}
}

// A record before 4 names no bundle per node, and every claim is the record's bundle_id, as
// twin show shows it: held when that is the staged bundle, failed when it is not.
func TestClaimsOfARecordBefore4(t *testing.T) {
	for _, tc := range []struct {
		name, bundleID, want string
	}{
		{"held", stagedID, "held"},
		{"not held", previousID, "failed"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			rec := wire.TwinRecord{TwinVersion: "3", BundleID: tc.bundleID, Nodes: []wire.TwinNode{{Name: "n2"}, {Name: "n1"}}}
			got := Claims(rec, stagedID, nil)
			for i, name := range []string{"n1", "n2"} {
				c := got[i]
				if c.Node != name || c.Holds == nil || *c.Holds != tc.bundleID || c.Staged != stagedID || c.Outcome != tc.want {
					t.Errorf("claim %d = %+v (holds %v), want %s holding the record's bundle_id: %s", i, c, c.Holds, name, tc.want)
				}
			}
		})
	}
}

// A node the staged bundle names that the record does not is given a failed claim holding
// nothing, in name order among the record's: a step between its reconcile and its record,
// which created the node. A record node the bundle does not name keeps its
// claim.
func TestClaimsOfANodeTheRecordDoesNotName(t *testing.T) {
	staged := stagedID
	rec := wire.TwinRecord{TwinVersion: "5", BundleID: staged, State: wire.StateReady, Nodes: []wire.TwinNode{
		{Name: "n3", Holds: &staged},
		{Name: "n1", Holds: &staged},
		{Name: "x9", Holds: &staged},
	}}
	got := Claims(rec, staged, []string{"n1", "n4", "n3", "n2"})
	want := []string{
		"n1 holds eeee against eeee: held",
		"n2 holds null against eeee: failed",
		"n3 holds eeee against eeee: held",
		"n4 holds null against eeee: failed",
		"x9 holds eeee against eeee: held",
	}
	if !reflect.DeepEqual(claimsOf(got), want) {
		t.Errorf("Claims = %q, want %q", claimsOf(got), want)
	}
	for _, c := range got {
		if unnamed := c.Node == "n2" || c.Node == "n4"; c.Unnamed != unnamed {
			t.Errorf("%s: unnamed %t, want %t", c.Node, c.Unnamed, unnamed)
		}
	}
}
