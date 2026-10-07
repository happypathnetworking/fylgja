package verify

import (
	"cmp"
	"fmt"
	"slices"
	"strings"

	"github.com/happypathnetworking/fylgja/internal/compiler"
)

// The assertion kinds: what one assertion holds a node to.
const (
	KindHostName    = "host_name"    // the node's host name is its node name
	KindPortEnabled = "port_enabled" // a cabled port intent enables is enabled, as the facet declares enabled
	KindNeighbor    = "neighbor"     // one end of a link sees the far node and the far port by the far node's own name
)

// What came of one assertion (contracts/verify.schema.json).
const (
	Held    = "held"    // the value read is the value expected
	Failed  = "failed"  // a value was read, and differs
	Absent  = "absent"  // nothing was read, and the facet declares no meaning for absence
	Unread  = "unread"  // the read failed at the transport, or the node could not be read at all
	Skipped = "skipped" // not asserted: a port intent disables, or a link end on one
)

// Assertion is one observable fact of one node that intent implies, derived from the
// staged bundle's manifest, and once read, what came of it. Derive fills
// what the manifest says; Read fills the path and the expected value from the node's
// package's conformance facet, and the outcome from what the node answered.
type Assertion struct {
	Kind     string
	Node     string
	Port     string // the production name; "" for host_name
	NodeName string // the node's own name for the port; "" for host_name
	Link     string // the link id; "" except for neighbor
	// End is which end of Link the assertion is: "a" or "b", as the manifest's link names
	// them; "" except for neighbor.
	End string
	// Path is the facet's path with {node_name} rendered; "" until the package is known.
	Path string
	// Expected is host_name: the node name; port_enabled: the facet's enabled value;
	// neighbor: "<far node> <far node name>".
	Expected         string
	FarNode, FarPort string // neighbor: the far end, the port under the far node's own name
	Outcome          string
	// Read is what was read, as Text gives it: for neighbor the one entry
	// ("e1 Ethernet4"), the entries counted ("2 entries: e1 Ethernet3, e1 Ethernet4") or
	// the value that is not a list ("{"x":1}, not a list"). Meaningful only when Outcome is
	// Held or Failed: a node may read an empty string.
	Read string
	// Seen is every neighbour entry a neighbor assertion read, far node and far port each
	// as the facet's leaves give them; nil when nothing was read.
	Seen []Neighbour
	// Error is an Unread assertion's reason: the transport error, redacted, or why the
	// node could not be read at all.
	Error string
	// Reason is a Skipped assertion's: why it was not asserted.
	Reason string
}

// Neighbour is one entry of a neighbour list as a neighbor assertion read it.
type Neighbour struct {
	Node, Port string
}

func (n Neighbour) String() string { return n.Node + " " + n.Port }

// Derive builds every assertion the staged bundle's manifest implies, in node order, and
// within a node its host name, then each cabled port's
// state, then each cabled port's neighbour, in the manifest's row order. It is pure: no
// package and no path yet, which the read fills from the node's facet.
//
// A cabled row whose intent disables the port is skipped, and so is each end of the link
// on it, since a disabled port forms no adjacency for either end to see. The
// manifest's other omissions are never assertions: discovering and the version are the
// suite's, and an uncabled or omitted interface has no port on the twin
// (D-022: the omissions are the report's context, not its findings).
//
// An error names what the compiler never emits: a link end with no cabled
// row, or a cabled row on a port no link names. It is a *ManifestError.
func Derive(m compiler.Manifest) ([]Assertion, error) {
	type at struct{ node, port string }
	rows := map[at]compiler.MappingRow{}
	for _, r := range m.Mapping {
		if r.Disposition == compiler.DispCabled && r.Port != nil {
			rows[at{r.Device, *r.Port}] = r
		}
	}

	// The link on each cabled port, and the row at its far end.
	type end struct {
		link, side string
		far        compiler.MappingRow
		skip       string // the link's skip reason, "" when both ends are enabled
	}
	ends := map[at]end{}
	links := slices.SortedFunc(slices.Values(m.Links), func(a, b compiler.CabledLink) int { return cmp.Compare(a.ID, b.ID) })
	for _, l := range links {
		a, okA := rows[at{l.A.Node, l.A.Port}]
		b, okB := rows[at{l.B.Node, l.B.Port}]
		for _, e := range []struct {
			p  compiler.NodePort
			ok bool
		}{{l.A, okA}, {l.B, okB}} {
			if !e.ok {
				return nil, &ManifestError{Object: l.ID,
					Message: fmt.Sprintf("link %s names %s port %s, which has no cabled mapping row", l.ID, e.p.Node, e.p.Port)}
			}
		}
		var disabled []string
		for _, r := range []compiler.MappingRow{a, b} {
			if !r.IsEnabled() {
				disabled = append(disabled, r.Device+":"+r.Interface)
			}
		}
		skip := ""
		if len(disabled) > 0 {
			skip = fmt.Sprintf("link %s is not asserted: intent disables %s", l.ID, strings.Join(disabled, " and "))
		}
		ends[at{l.A.Node, l.A.Port}] = end{link: l.ID, side: "a", far: b, skip: skip}
		ends[at{l.B.Node, l.B.Port}] = end{link: l.ID, side: "b", far: a, skip: skip}
	}

	cabled := map[string][]compiler.MappingRow{}
	for _, r := range m.Mapping {
		if r.Disposition != compiler.DispCabled || r.Port == nil {
			continue
		}
		if _, linked := ends[at{r.Device, *r.Port}]; !linked {
			return nil, &ManifestError{Object: r.Device + ":" + r.Interface,
				Message: fmt.Sprintf("%s:%s is cabled on port %s, which no link names", r.Device, r.Interface, *r.Port)}
		}
		cabled[r.Device] = append(cabled[r.Device], r)
	}

	nodes := slices.SortedFunc(slices.Values(m.Nodes), func(a, b compiler.ManifestNode) int { return cmp.Compare(a.Name, b.Name) })
	var out []Assertion
	for _, n := range nodes {
		out = append(out, Assertion{Kind: KindHostName, Node: n.Name, Expected: n.Name})
		for _, r := range cabled[n.Name] {
			a := Assertion{Kind: KindPortEnabled, Node: n.Name, Port: r.Interface, NodeName: NodeName(r)}
			if !r.IsEnabled() {
				a.Outcome, a.Reason = Skipped, fmt.Sprintf("intent disables %s:%s", r.Device, r.Interface)
			}
			out = append(out, a)
		}
		for _, r := range cabled[n.Name] {
			e := ends[at{r.Device, *r.Port}]
			a := Assertion{Kind: KindNeighbor, Node: n.Name, Port: r.Interface, NodeName: NodeName(r),
				Link: e.link, End: e.side, FarNode: e.far.Device, FarPort: NodeName(e.far)}
			a.Expected = a.FarNode + " " + a.FarPort
			if e.skip != "" {
				a.Outcome, a.Reason = Skipped, e.skip
			}
			out = append(out, a)
		}
	}
	return out, nil
}

// ManifestError is a staged manifest the compiler never emits: Object is what
// it names wrongly, the link id or the row as <device>:<interface>, which twin verify's
// operation.failed carries as its object (contracts/cli.md).
type ManifestError struct {
	Object  string
	Message string
}

func (e *ManifestError) Error() string { return e.Message }
