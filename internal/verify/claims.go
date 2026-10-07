package verify

import (
	"cmp"
	"slices"

	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// Claim is the record's claim of what one node holds, against the staged bundle.
// It is twin.json's, never read from the node and never waited
// on: a node's running configuration is not compared with intent, and the report
// says so where it shows the claim.
type Claim struct {
	Node string
	// Holds is the bundle the record says the node holds: nodes[].holds, nil where the
	// record writes null (containerlab restarted, recreated or created the node and no
	// push landed). A record before 4 names no bundle per node, and its claim
	// is the record's bundle_id, as twin show shows it.
	Holds   *string
	Staged  string // the staged bundle's id
	Outcome string // Held or Failed
	// Unnamed says the record does not name the node at all, though the staged bundle
	// does: a step between its reconcile and its record, which created the node. The
	// claim is Failed, holding nothing.
	Unnamed bool
}

// Claims gives one claim per node of the record, and one per node of the staged bundle the
// record does not name, in name order: Held when the bundle the record says the node holds
// is the staged one, Failed otherwise, the previous bundle, none, or no node at all. named
// is the staged manifest's nodes.
//
// Whether the record names a bundle per node is told as twin show tells it: a record of
// version 4 or later always carries a state, and one before carries none, and no holds
// either (lab.ReadRecord).
func Claims(rec wire.TwinRecord, staged string, named []string) []Claim {
	holdsNamed := rec.State != ""
	out := make([]Claim, 0, len(rec.Nodes))
	recorded := map[string]bool{}
	for _, n := range rec.Nodes {
		recorded[n.Name] = true
		c := Claim{Node: n.Name, Holds: n.Holds, Staged: staged, Outcome: Failed}
		if !holdsNamed {
			id := rec.BundleID
			c.Holds = &id
		}
		if c.Holds != nil {
			id := *c.Holds
			c.Holds = &id
			if id == staged {
				c.Outcome = Held
			}
		}
		out = append(out, c)
	}
	for _, name := range named {
		if !recorded[name] {
			recorded[name] = true
			out = append(out, Claim{Node: name, Staged: staged, Outcome: Failed, Unnamed: true})
		}
	}
	slices.SortFunc(out, func(a, b Claim) int { return cmp.Compare(a.Node, b.Node) })
	return out
}
