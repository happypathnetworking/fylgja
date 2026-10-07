package conformance

import (
	"cmp"
	"context"
	"fmt"
	"maps"
	"net"
	"slices"
	"strconv"
	"strings"

	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/verify"
)

// The boot half's checks, in the order they run on a node.
const (
	CheckDeclared        = "declared"
	CheckBooted          = "booted"
	CheckReadiness       = "readiness"
	CheckHostName        = "host_name"
	CheckPortEnabled     = "port_enabled"
	CheckPortDiscovering = "port_discovering"
	CheckNeighbor        = "neighbor"
	CheckVersion         = "version"
)

// BootChecks lists the boot half's checks, so a test can run one subtest per node per
// check whether or not it failed.
var BootChecks = []string{CheckDeclared, CheckBooted, CheckReadiness, CheckHostName,
	CheckPortEnabled, CheckPortDiscovering, CheckNeighbor, CheckVersion}

// The readers are internal/verify's, which twin verify and the step's wait share with the
// boot half (D-037): an answer, its updates, a reader and the packages are verify's types
// under the names the suite has always used, so its tests and every wording the boot half
// gives are unchanged by the move.
// lab.GNMIReader satisfies Reader directly. One call is one read: the boot half retries
// nothing.
type (
	Update   = verify.Update
	Answer   = verify.Answer
	Reader   = verify.Reader
	Packages = verify.Packages
)

// The descent the suite's tests hold to the answers a booted SR Linux and cEOS node give,
// under the names they always used: verify's, unchanged in behaviour.
type listOutcome = verify.ListOutcome

const (
	listNothing  = verify.ListNothing
	listEntries  = verify.ListEntries
	listNotAList = verify.ListNotAList
)

var (
	leafAt    = verify.LeafAt
	entriesAt = verify.EntriesAt
)

// BootInput is a ready twin as the boot half reads it: the record the run wrote last,
// the staged bundle's manifest, the packages loaded as the worker loads them, a reader
// and the environment the logins are read from.
type BootInput struct {
	Record   wire.TwinRecord
	Manifest compiler.Manifest
	Packages Packages
	Reader   Reader
	Getenv   func(string) (string, bool)
}

// BootNode is one node of the twin the boot half held to its checks, read or not. Addr
// is set when it was read; Passed is its success line, set
// only when every check on the node held.
type BootNode struct {
	Name, Addr string
	Passed     string
}

// Boot runs the boot half on a ready twin: one report per package of
// the twin, in platform id order. The nodes are the manifest's, the twin as compiled,
// each held to the record the run wrote; a report's failures are per node, in node name
// order, after any failure of the package as a whole (Node empty). It boots, pushes and
// changes nothing, reads each path once and retries nothing.
//
// Every expectation is the package's own data or the bundle's: the paths and values are
// the conformance facet's, the port names the mapping rows', the far ends the links'.
// Nothing here knows which platform it reads (Constitution II).
func Boot(ctx context.Context, in BootInput) []Report {
	recorded := map[string]wire.TwinNode{}
	for _, n := range in.Record.Nodes {
		recorded[n.Name] = n
	}
	byPackage := map[string][]compiler.ManifestNode{}
	for _, n := range in.Manifest.Nodes {
		byPackage[n.PSP.ID] = append(byPackage[n.PSP.ID], n)
	}

	var reports []Report
	for _, id := range slices.Sorted(maps.Keys(byPackage)) {
		nodes := slices.SortedFunc(slices.Values(byPackage[id]), func(a, b compiler.ManifestNode) int {
			return cmp.Compare(a.Name, b.Name)
		})
		reports = append(reports, bootPackage(ctx, in, id, nodes, recorded))
	}
	return reports
}

// bootPackage holds one package's nodes to the boot half's checks.
func bootPackage(ctx context.Context, in BootInput, id string, nodes []compiler.ManifestNode, recorded map[string]wire.TwinNode) Report {
	r := Report{Package: id, BootHalf: BootHalfNotDeclared}
	fail := func(node, check, message string) {
		r.Failures = append(r.Failures, Failure{Package: r.Package, Path: r.Path, Check: check, Node: node, Message: message})
	}

	p, found := in.Packages.LookupID(id)
	readable := found
	switch {
	case !found:
		fail("", CheckDeclared, fmt.Sprintf("package %s is not among the packages loaded; the boot half cannot read its nodes", id))
	default:
		r.Path = p.Path
		if p.Conformance == nil {
			fail("", CheckDeclared, fmt.Sprintf("package %s declares no conformance block; the boot half cannot read its nodes", id))
			readable = false
		} else {
			r.BootHalf = BootHalfTier3
		}
		if probe := p.Readiness.Probe; probe != psp.ProbeGNMIGet && probe != psp.ProbeGNMISubscribe {
			fail("", CheckDeclared, fmt.Sprintf("package %s's readiness probe is %s; the boot half reads by gNMI only", id, probe))
			readable = false
		}
	}

	for _, mn := range nodes {
		name := mn.Name
		rec, inRecord := recorded[name]
		if !inRecord {
			fail(name, CheckBooted, fmt.Sprintf("node %s is not in the record", name))
			r.Nodes = append(r.Nodes, BootNode{Name: name})
			continue
		}
		before := len(r.Failures)
		if rec.Container == "" {
			fail(name, CheckBooted, fmt.Sprintf("node %s has no container in the record", name))
		}
		if rec.MgmtIPv4 == "" {
			fail(name, CheckBooted, fmt.Sprintf("node %s has no address in the record", name))
		}
		if found && rec.ReadyAfterS > float64(p.Readiness.TimeoutS) {
			fail(name, CheckReadiness, fmt.Sprintf("node %s: ready after %ss, over the package's readiness budget of %ds",
				name, seconds(rec.ReadyAfterS), p.Readiness.TimeoutS))
		}
		if !readable || rec.MgmtIPv4 == "" {
			r.Nodes = append(r.Nodes, BootNode{Name: name})
			continue
		}

		n := nodeReader{ctx: ctx, in: in, p: p, name: name,
			addr: net.JoinHostPort(rec.MgmtIPv4, strconv.Itoa(p.Readiness.PortOrDefault())), fail: fail}
		hostName, version, listed, ports := n.read()
		node := BootNode{Name: name, Addr: n.addr}
		if len(r.Failures) == before {
			pushed := "read after the push"
			if rec.Artifact == nil {
				pushed = "read with no push recorded"
			}
			node.Passed = fmt.Sprintf("node %s (%s): booted; ready after %ss of %ds; host name %s; %s enabled and discovering; %s as the bundle's links name them; version %s (listed: %s); %s",
				name, n.addr, seconds(rec.ReadyAfterS), p.Readiness.TimeoutS, hostName,
				count(ports, "cabled port", "cabled ports"), count(ports, "neighbour", "neighbours"), version, listed, pushed)
		}
		r.Nodes = append(r.Nodes, node)
	}
	return r
}

// nodeReader reads one booted node by its package's conformance facet.
type nodeReader struct {
	ctx        context.Context
	in         BootInput
	p          *psp.PSP
	name, addr string
	fail       func(node, check, message string)
}

// read runs the node's reads in check order and returns what the success line names:
// the host name and version read, the listed version it matched, and the cabled ports.
func (n nodeReader) read() (hostName, version, listed string, ports int) {
	c := n.p.Conformance

	switch v, got := n.value(CheckHostName, c.HostName, ""); got {
	case readValue:
		hostName = verify.Text(v)
		if hostName != n.name {
			n.failAt(CheckHostName, c.HostName, fmt.Sprintf("expected %q, read %q", n.name, hostName), "")
		}
	case readNothing:
		n.failAt(CheckHostName, c.HostName, fmt.Sprintf("expected %q, read nothing", n.name), "")
	}

	rows := n.cabledRows()
	for _, check := range []struct {
		name string
		at   psp.ValueAt
	}{{CheckPortEnabled, c.Port.Enabled}, {CheckPortDiscovering, c.Port.Discovering}} {
		for _, row := range rows {
			path := strings.ReplaceAll(check.at.Path, "{node_name}", verify.NodeName(row))
			v, got := n.value(check.name, path, describeRow(row))
			// A facet that declares what the node means by reporting nothing reads that
			// value instead of failing: a model that omits a default reports no update
			// while the default holds. Without `absent`, nothing read
			// fails as it did in M6.
			if got == readNothing && check.at.Absent != "" {
				v, got = check.at.Absent, readValue
			}
			switch {
			case got == readValue && verify.Text(v) != check.at.Value:
				n.failAt(check.name, path, fmt.Sprintf("expected %q, read %q", check.at.Value, verify.Text(v)), describeRow(row))
			case got == readNothing:
				n.failAt(check.name, path, fmt.Sprintf("expected %q, read nothing", check.at.Value), describeRow(row))
			}
		}
	}
	for _, row := range rows {
		n.neighbor(c.Port.Neighbor, row)
	}

	listedText := "[" + strings.Join(n.p.Platform.Versions, ", ") + "]"
	switch v, got := n.value(CheckVersion, c.Version, ""); got {
	case readValue:
		version = verify.Text(v)
		if l, matched := VersionMatches(version, n.p.Platform.Versions); matched {
			listed = l
		} else {
			n.failAt(CheckVersion, c.Version, fmt.Sprintf("read %q, which matches none of the package's versions %s", version, listedText), "")
		}
	case readNothing:
		n.failAt(CheckVersion, c.Version, "read nothing, which matches none of the package's versions "+listedText, "")
	}
	return hostName, version, listed, len(rows)
}

// What one read gave.
type readOutcome int

const (
	readValue   readOutcome = iota // a value at the path
	readNothing                    // an answer with nothing at the path (an absent value is not an error)
	readFailed                     // the read failed, and value has reported it under its check
)

// get reads one path. A failed read is reported here, under check and with row, so the
// caller words only what the node answered; ok is false when the read failed.
func (n nodeReader) get(check, path, row string) (Answer, bool) {
	a, err := n.in.Reader.Get(n.ctx, n.addr, verify.ReadinessProbe(n.p), path, n.in.Getenv)
	if err != nil {
		n.failAt(check, path, err.Error(), row)
		return Answer{}, false
	}
	return a, true
}

// value reads one path and descends the answer to it.
func (n nodeReader) value(check, path, row string) (any, readOutcome) {
	a, ok := n.get(check, path, row)
	if !ok {
		return nil, readFailed
	}
	if v, ok := verify.LeafAt(a, path); ok {
		return v, readValue
	}
	return nil, readNothing
}

// failAt words a failed read:
// node <n> (<addr>): <check> at <path>: <what>[; checking mapping row …].
func (n nodeReader) failAt(check, path, what, row string) {
	msg := fmt.Sprintf("node %s (%s): %s at %s: %s", n.name, n.addr, check, path, what)
	if row != "" {
		msg += "; checking " + row
	}
	n.fail(n.name, check, msg)
}

// neighbor holds one cabled port's neighbour list to the link the bundle names on it:
// exactly one entry, naming the far node and the far port under the far node's own name.
func (n nodeReader) neighbor(at psp.NeighborAt, row compiler.MappingRow) {
	path := strings.ReplaceAll(at.Path, "{node_name}", verify.NodeName(row))
	link, far, farRow, ok := n.farSide(row)
	if !ok {
		n.failAt(CheckNeighbor, path, fmt.Sprintf("the bundle names no link on port %s", *row.Port), describeRow(row))
		return
	}
	where := describeRow(row) + " for link " + link.ID
	if farRow == nil {
		n.failAt(CheckNeighbor, path, fmt.Sprintf("the bundle names no mapping row for %s port %s, the far end", far.Node, far.Port), where)
		return
	}
	want := far.Node + " " + verify.NodeName(*farRow)

	a, ok := n.get(CheckNeighbor, path, where)
	if !ok {
		return
	}
	list, value, outcome := verify.EntriesAt(a, path)
	switch outcome {
	case verify.ListNothing:
		n.failAt(CheckNeighbor, path, fmt.Sprintf("expected %s, read nothing", want), where)
		return
	case verify.ListNotAList:
		n.failAt(CheckNeighbor, path, fmt.Sprintf("expected %s, read %s, not a list", want, verify.Text(value)), where)
		return
	}
	var entries []string
	for _, e := range list {
		entry, _ := e.(map[string]any)
		entries = append(entries, verify.EntryLeaf(entry, at.SystemName)+" "+verify.EntryLeaf(entry, at.PortID))
	}
	switch {
	case len(entries) == 1 && entries[0] == want:
	case len(entries) == 0:
		n.failAt(CheckNeighbor, path, fmt.Sprintf("expected %s, read nothing", want), where)
	case len(entries) == 1:
		n.failAt(CheckNeighbor, path, fmt.Sprintf("expected %s, read %s", want, entries[0]), where)
	default:
		n.failAt(CheckNeighbor, path, fmt.Sprintf("expected %s, read %d entries: %s", want, len(entries), strings.Join(entries, ", ")), where)
	}
}

// farSide finds the manifest's link on this row's port and the mapping row at its far
// end. The far row is nil when the bundle names none.
func (n nodeReader) farSide(row compiler.MappingRow) (compiler.CabledLink, compiler.NodePort, *compiler.MappingRow, bool) {
	here := compiler.NodePort{Node: row.Device, Port: *row.Port}
	for _, l := range n.in.Manifest.Links {
		var far compiler.NodePort
		switch here {
		case l.A:
			far = l.B
		case l.B:
			far = l.A
		default:
			continue
		}
		for i, m := range n.in.Manifest.Mapping {
			if m.Device == far.Node && m.Port != nil && *m.Port == far.Port && m.Disposition == compiler.DispCabled {
				return l, far, &n.in.Manifest.Mapping[i], true
			}
		}
		return l, far, nil, true
	}
	return compiler.CabledLink{}, compiler.NodePort{}, nil, false
}

// cabledRows are the node's cabled mapping rows, in the manifest's order.
func (n nodeReader) cabledRows() []compiler.MappingRow {
	var rows []compiler.MappingRow
	for _, m := range n.in.Manifest.Mapping {
		if m.Device == n.name && m.Disposition == compiler.DispCabled && m.Port != nil {
			rows = append(rows, m)
		}
	}
	return rows
}

// describeRow names a mapping row as the failures do: mapping row <d>:<interface>
// (port <p>, node name <nn>).
func describeRow(row compiler.MappingRow) string {
	return fmt.Sprintf("mapping row %s:%s (port %s, node name %s)", row.Device, row.Interface, *row.Port, verify.NodeName(row))
}

// seconds writes a duration in seconds as the record holds it, without trailing zeros.
func seconds(s float64) string {
	return strconv.FormatFloat(s, 'f', -1, 64)
}

func count(k int, one, many string) string {
	if k == 1 {
		return "1 " + one
	}
	return fmt.Sprintf("%d %s", k, many)
}
