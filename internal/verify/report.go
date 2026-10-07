package verify

import (
	"cmp"
	"context"
	"errors"
	"fmt"
	"maps"
	"net"
	"slices"
	"strconv"
	"strings"
	"time"

	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// Input is a twin as one read of it needs it: the staged bundle the
// assertions were derived from, the record that names the twin and claims what each node
// holds, containerlab's nodes, the packages that say how each node is read, the reader and
// the environment the logins are read from at the moment of each read.
type Input struct {
	Manifest compiler.Manifest
	StagedID string
	Record   wire.TwinRecord
	// Lab is containerlab's nodes: the addresses the record lacks, and the nodes the bundle
	// does not name. Nil means containerlab was not asked or could not answer, and every
	// node is then read at the record's address alone; an empty list is containerlab
	// reporting no node at all.
	Lab      []wire.LabNode
	Packages Packages
	Reader   Reader
	Getenv   func(string) (string, bool)
	Now      func() time.Time // nil: time.Now
}

// NodeRead is one node the staged manifest names, as the read found it: its package and
// the address it was dialled at, "" when it had none.
type NodeRead struct {
	Node string
	PSP  string
	Addr string
}

// NodeError is one node with an assertion it could not read: the first reason, and the
// path it was reading. A node that could not be read at all has no path, and its reason
// is the whole sentence.
type NodeError struct {
	Node, Addr, Path, Error string
}

// Message words the node's operation.failed as contracts/cli.md's findings table does.
func (e NodeError) Message() string {
	if e.Path == "" {
		return e.Error
	}
	return fmt.Sprintf("node %s (%s) could not be read: %s (at %s)", e.Node, e.Addr, e.Error, e.Path)
}

// Report is one read of the twin: every assertion of Derive with its
// outcome, the record's claims, the nodes containerlab reports that the bundle does not
// name, and one NodeError per node with an unread assertion. It changes nothing, and
// nothing in Fylgja acts on it.
type Report struct {
	ReadAt     time.Time // the read's start
	Nodes      []NodeRead
	Assertions []Assertion
	Claims     []Claim
	Extra      []string
	Unread     []NodeError
}

// Read reads the twin once: node by node in name order,
// each node over its own package's readiness transport, port, encoding and login
// (ReadinessProbe), at the record's address or else containerlab's, each assertion's path
// once, as the node's conformance facet declares it. An address is one only when it parses
// as an IP address (address). Skipped assertions are not read. A
// failed read is Unread, and the first such error is the node's NodeError. A node that
// refused one path is still read at its other paths; one that did not answer at all
// (Unanswered) is dialled no further, and its paths not yet read are Unread with that
// error. assertions is never changed: each read starts from Derive's.
//
// Nothing here knows which platform it reads (Constitution II; D-031): paths, values and
// what an absent value means are the facet's, the far ends the links'.
func Read(ctx context.Context, in Input, assertions []Assertion) Report {
	now := in.Now
	if now == nil {
		now = time.Now
	}
	staged := make([]string, len(in.Manifest.Nodes))
	for i, n := range in.Manifest.Nodes {
		staged[i] = n.Name
	}
	r := Report{ReadAt: now(), Assertions: slices.Clone(assertions), Claims: Claims(in.Record, in.StagedID, staged)}

	recorded := map[string]string{}
	for _, n := range in.Record.Nodes {
		recorded[n.Name] = n.MgmtIPv4
	}
	lab := map[string]wire.LabNode{}
	for _, n := range in.Lab {
		lab[n.Name] = n
	}
	named := map[string]bool{}
	nodes := slices.SortedFunc(slices.Values(in.Manifest.Nodes), func(a, b compiler.ManifestNode) int { return cmp.Compare(a.Name, b.Name) })
	for _, mn := range nodes {
		named[mn.Name] = true
		var mine []int
		for i, a := range r.Assertions {
			if a.Node == mn.Name {
				mine = append(mine, i)
			}
		}
		nr := NodeRead{Node: mn.Name, PSP: mn.PSP.ID}
		p, found := in.Packages.LookupID(mn.PSP.ID)
		reason := ""
		switch {
		// Neither is reached through twin verify or the step's wait, whose packages are
		// checked before any read; both are here so a caller that skipped
		// that check reads no node it cannot hold to a facet.
		case !found:
			reason = fmt.Sprintf("support package %s is not among the packages loaded; node %s cannot be read", mn.PSP.ID, mn.Name)
		case p.Conformance == nil:
			reason = fmt.Sprintf("support package %s declares no conformance block; node %s cannot be read", mn.PSP.ID, mn.Name)
		default:
			for _, i := range mine {
				facet(&r.Assertions[i], p.Conformance)
			}
			ln, reported := lab[mn.Name]
			ip := address(recorded[mn.Name])
			if ip == "" {
				ip = address(ln.MgmtIPv4)
			}
			switch {
			case in.Lab != nil && !reported:
				reason = fmt.Sprintf("containerlab does not report node %s, which the staged bundle names; nothing to read", mn.Name)
			case ip == "":
				reason = fmt.Sprintf("node %s has no address in the record or from containerlab", mn.Name)
			default:
				nr.Addr = net.JoinHostPort(ip, strconv.Itoa(p.Readiness.PortOrDefault()))
			}
		}
		r.Nodes = append(r.Nodes, nr)
		if reason != "" {
			for _, i := range mine {
				if a := &r.Assertions[i]; a.Outcome != Skipped {
					a.Outcome, a.Error = Unread, reason
				}
			}
			r.Unread = append(r.Unread, NodeError{Node: mn.Name, Error: reason})
			continue
		}

		probe := ReadinessProbe(p)
		var (
			first  *NodeError
			silent string // the error of a read the node did not answer at all
		)
		for _, i := range mine {
			a := &r.Assertions[i]
			if a.Outcome == Skipped {
				continue
			}
			if silent != "" {
				a.Outcome, a.Error = Unread, silent
				continue
			}
			answer, err := in.Reader.Get(ctx, nr.Addr, probe, a.Path, in.Getenv)
			if err != nil {
				// The reader's error is the probe's: lab.gnmiGet has redacted the login
				// before it returns.
				a.Outcome, a.Error = Unread, err.Error()
				if first == nil {
					first = &NodeError{Node: mn.Name, Addr: nr.Addr, Path: a.Path, Error: err.Error()}
				}
				if u := (*Unanswered)(nil); errors.As(err, &u) {
					silent = err.Error()
				}
				continue
			}
			judge(a, answer, p.Conformance)
		}
		if first != nil {
			r.Unread = append(r.Unread, *first)
		}
	}

	for _, n := range in.Lab {
		if !named[n.Name] {
			r.Extra = append(r.Extra, n.Name)
		}
	}
	slices.Sort(r.Extra)
	return r
}

// address is s when it parses as an IP address, and "" otherwise. containerlab 0.79
// reports an exited container's address as N/A, which lab's inspection cuts at the slash
// to N, and a step's record built from that inspection carries it: neither is
// dialled, and the node then has no address.
func address(s string) string {
	if net.ParseIP(s) == nil {
		return ""
	}
	return s
}

// facet fills an assertion's path and expected value from the node's conformance facet,
// {node_name} rendering the node's own name for the port. A skipped assertion gets them
// too, so the report says what was not asserted.
func facet(a *Assertion, c *psp.Conformance) {
	render := func(path string) string { return strings.ReplaceAll(path, "{node_name}", a.NodeName) }
	switch a.Kind {
	case KindHostName:
		a.Path = c.HostName
	case KindPortEnabled:
		a.Path, a.Expected = render(c.Port.Enabled.Path), c.Port.Enabled.Value
	case KindNeighbor:
		a.Path = render(c.Port.Neighbor.Path)
	}
}

// judge sets an assertion's outcome from the node's answer.
func judge(a *Assertion, answer Answer, c *psp.Conformance) {
	switch a.Kind {
	case KindHostName:
		v, ok := LeafAt(answer, a.Path)
		leaf(a, v, ok)
	case KindPortEnabled:
		v, ok := LeafAt(answer, a.Path)
		// A facet that declares what the node means by reporting nothing reads that value
		// instead: a model that omits a default reports no update while it holds. Without
		// the declaration, nothing read is absent.
		if !ok && c.Port.Enabled.Absent != "" {
			v, ok = c.Port.Enabled.Absent, true
		}
		leaf(a, v, ok)
	case KindNeighbor:
		neighbour(a, answer, c.Port.Neighbor)
	}
}

// leaf holds a leaf's value to the expected one: equal is Held, another Failed, nothing
// read Absent.
func leaf(a *Assertion, v any, ok bool) {
	if !ok {
		a.Outcome = Absent
		return
	}
	a.Read = Text(v)
	a.Outcome = Failed
	if a.Read == a.Expected {
		a.Outcome = Held
	}
}

// neighbour holds a link end's neighbour list to the link: exactly one entry naming the far
// node and the far port under the far node's own name is Held; no entry, or an empty list,
// Absent; one other entry, two or more, or a value that is not a list, Failed.
func neighbour(a *Assertion, answer Answer, at psp.NeighborAt) {
	list, value, outcome := EntriesAt(answer, a.Path)
	switch outcome {
	case ListNothing:
		a.Outcome = Absent
		return
	case ListNotAList:
		a.Outcome, a.Read = Failed, Text(value)+", not a list"
		return
	}
	for _, e := range list {
		entry, _ := e.(map[string]any)
		a.Seen = append(a.Seen, Neighbour{Node: EntryLeaf(entry, at.SystemName), Port: EntryLeaf(entry, at.PortID)})
	}
	switch len(a.Seen) {
	case 0:
		a.Outcome = Absent
	case 1:
		a.Read, a.Outcome = a.Seen[0].String(), Failed
		if a.Seen[0] == (Neighbour{Node: a.FarNode, Port: a.FarPort}) {
			a.Outcome = Held
		}
	default:
		a.Read, a.Outcome = fmt.Sprintf("%d entries: %s", len(a.Seen), joinSeen(a.Seen)), Failed
	}
}

func joinSeen(seen []Neighbour) string {
	s := make([]string, len(seen))
	for i, n := range seen {
		s[i] = n.String()
	}
	return strings.Join(s, ", ")
}

// Conforms says whether every assertion that was asserted held. The record's claims are
// not counted: they are the record's, not a read, and the wait never waits on them.
func (r Report) Conforms() bool {
	for _, a := range r.Assertions {
		if a.Outcome != Skipped && a.Outcome != Held {
			return false
		}
	}
	return true
}

// AllRead says whether every node was read: no assertion is Unread.
func (r Report) AllRead() bool { return len(r.Unread) == 0 }

// undialled says whether a node was left unread without being dialled: containerlab did
// not report it, or it had no address. (A package that cannot be held to a facet does the
// same, which no caller reaches: twin verify refuses it first, and the step's packages are
// the worker's.)
func (r Report) undialled() bool {
	return slices.ContainsFunc(r.Unread, func(e NodeError) bool { return e.Addr == "" })
}

// Findings words the report as contracts/cli.md's findings table does, each a rejection at
// step observe: one per failed or absent assertion, in the assertions' order; one
// verify.record.holds per claim not held, in node order; and one operation.failed per node
// with an unread assertion, in node order. Held and skipped assertions say nothing. No
// message carries a configuration line, the token or a login: what is
// quoted is a host name, an admin state or a neighbour's name.
func (r Report) Findings() findings.List {
	addr := map[string]string{}
	for _, n := range r.Nodes {
		addr[n.Node] = n.Addr
	}
	var l findings.List
	add := func(rule, object, format string, args ...any) {
		l.AddStep(findings.Rejection, findings.StepObserve, rule, object, fmt.Sprintf(format, args...))
	}
	for _, a := range r.Assertions {
		if a.Outcome != Failed && a.Outcome != Absent {
			continue
		}
		node := fmt.Sprintf("node %s (%s)", a.Node, addr[a.Node])
		switch a.Kind {
		case KindHostName:
			if a.Outcome == Absent {
				add(findings.RuleVerifyHostName, a.Node, "%s reports no host name at %s; intent names it %s", node, a.Path, a.Expected)
			} else {
				add(findings.RuleVerifyHostName, a.Node, "%s reports host name %q at %s; intent names it %s", node, a.Read, a.Path, a.Expected)
			}
		case KindPortEnabled:
			port := fmt.Sprintf("%s: port %s (node name %s)", node, a.Port, a.NodeName)
			read := "nothing"
			if a.Outcome == Failed {
				read = strconv.Quote(a.Read)
			}
			add(findings.RuleVerifyPortEnabled, a.Node+":"+a.Port, "%s reads %s at %s; intent enables it (expected %q)", port, read, a.Path, a.Expected)
		case KindNeighbor:
			port := fmt.Sprintf("%s: port %s", node, a.Port)
			link := fmt.Sprintf("link %s names %s at its far end", a.Link, a.Expected)
			object := a.Node + ":" + a.Port
			switch {
			case a.Outcome == Absent:
				add(findings.RuleVerifyNeighbor, object, "%s sees no neighbour at %s; %s", port, a.Path, link)
			case len(a.Seen) == 0:
				add(findings.RuleVerifyNeighbor, object, "%s reads %s, at %s; %s", port, a.Read, a.Path, link)
			case len(a.Seen) == 1:
				add(findings.RuleVerifyNeighbor, object, "%s sees %s, not %s, at %s; %s", port, a.Read, a.Expected, a.Path, link)
			default:
				add(findings.RuleVerifyNeighbor, object, "%s sees %d neighbours (%s), not %s alone, at %s; %s",
					port, len(a.Seen), joinSeen(a.Seen), a.Expected, a.Path, link)
			}
		}
	}
	for _, c := range r.Claims {
		switch {
		case c.Outcome == Held:
		case c.Unnamed:
			add(findings.RuleVerifyRecordHolds, c.Node, "the record does not name node %s, which the staged bundle names; "+
				"this is the record's claim, not a read", c.Node)
		case c.Holds == nil:
			add(findings.RuleVerifyRecordHolds, c.Node, "the record says node %s holds no bundle (null): containerlab restarted, "+
				"recreated or created it and no push landed; the staged bundle is %s; this is the record's claim, not a read",
				c.Node, short(c.Staged))
		default:
			add(findings.RuleVerifyRecordHolds, c.Node, "the record says node %s holds bundle %s, not the staged bundle %s; "+
				"this is the record's claim (nodes[].holds), not a read", c.Node, short(*c.Holds), short(c.Staged))
		}
	}
	for _, e := range r.Unread {
		add(findings.RuleOperationFailed, e.Node, "%s", e.Message())
	}
	return l
}

// short is a bundle id's first eight characters and an ellipsis, as the step's messages
// print one.
func short(id string) string {
	if len(id) <= 8 {
		return id
	}
	return id[:8] + "…"
}

// TwinInfo is the twin as its record names it, for the block: the staged
// bundle the assertions were derived from, the record's waypoint, state, source and node
// count, and where a diverged twin's step was going.
type TwinInfo struct {
	BundleID string // the staged bundle's
	Waypoint *wire.WaypointRef
	State    string // wire.StateReady or wire.StateDiverged; a record before 4 reads ready
	Source   string
	Nodes    int
	Diverged *Divergence
}

// Divergence is a diverged record's step: the waypoint and bundle it was going to, its run
// and the phase it stopped at.
type Divergence struct {
	Towards       *wire.WaypointRef
	TowardsBundle string
	RunID         string
	Phase         string
}

// TwinOf names the twin from its record and the staged bundle's id.
func TwinOf(rec wire.TwinRecord, staged string) TwinInfo {
	t := TwinInfo{BundleID: staged, Waypoint: rec.Waypoint, State: rec.State, Source: rec.Source, Nodes: len(rec.Nodes)}
	if t.State == "" {
		t.State = wire.StateReady
	}
	if s := rec.Step; rec.State == wire.StateDiverged && s != nil {
		d := &Divergence{Towards: s.To.Waypoint, TowardsBundle: s.To.BundleID, RunID: s.Run.RunID}
		if s.Phase != nil {
			d.Phase = *s.Phase
		}
		t.Diverged = d
	}
	return t
}

// Block builds twin verify's block from the report (contracts/verify.schema.json): the
// twin, each node with its host name and its ports, each
// link with both ends, the claims, the skips (each port's first, then each link end's), the
// nodes the bundle does not name, the counts, the runs in flight and the service as twin
// show reads them, and the wait, nil without --wait.
func (r Report) Block(twin TwinInfo, inFlight []findings.ShowRun, service string, wait *findings.VerifyWait) *findings.VerifyBlock {
	b := &findings.VerifyBlock{
		Twin:       twinBlock(twin),
		ReadAt:     r.ReadAt.UTC().Format(time.RFC3339Nano),
		ExtraNodes: slices.Clone(r.Extra),
		InFlight:   slices.Clone(inFlight),
		Service:    service,
		Wait:       wait,
	}
	unread := map[string]NodeError{}
	for _, e := range r.Unread {
		unread[e.Node] = e
	}
	index := map[string]int{}
	for _, n := range r.Nodes {
		node := findings.VerifyNode{Node: n.Node, PSP: n.PSP, Read: true}
		if n.Addr != "" {
			addr := n.Addr
			node.Addr = &addr
		}
		if e, ok := unread[n.Node]; ok {
			node.Read, node.Error = false, e.Error
		}
		index[n.Node] = len(b.Nodes)
		b.Nodes = append(b.Nodes, node)
	}

	var (
		hostNames, ports, neighbours counter
		links                        = map[string]*findings.VerifyLink{}
		portSkips, linkSkips         []findings.VerifySkip
	)
	for _, a := range r.Assertions {
		i, ok := index[a.Node]
		if !ok {
			continue
		}
		switch a.Kind {
		case KindHostName:
			hostNames.count(a.Outcome)
			b.Nodes[i].HostName = findings.VerifyAssertion{Path: a.Path, Expected: a.Expected, Outcome: a.Outcome,
				Read: readOf(a), Error: a.Error, Reason: a.Reason}
		case KindPortEnabled:
			ports.count(a.Outcome)
			b.Nodes[i].Ports = append(b.Nodes[i].Ports, findings.VerifyPort{Port: a.Port, NodeName: a.NodeName, Path: a.Path,
				Expected: a.Expected, Outcome: a.Outcome, Read: readOf(a), Error: a.Error, Reason: a.Reason})
			if a.Outcome == Skipped {
				portSkips = append(portSkips, findings.VerifySkip{Node: a.Node, Port: a.Port, Reason: a.Reason})
			}
		case KindNeighbor:
			neighbours.count(a.Outcome)
			l := links[a.Link]
			if l == nil {
				l = &findings.VerifyLink{ID: a.Link}
				links[a.Link] = l
			}
			end := findings.VerifyEnd{Node: a.Node, Port: a.Port, NodeName: a.NodeName, Path: a.Path,
				Expected: findings.VerifyNodePort{Node: a.FarNode, Port: a.FarPort}, Outcome: a.Outcome,
				Error: a.Error, Reason: a.Reason}
			for _, n := range a.Seen {
				end.Read = append(end.Read, findings.VerifyNodePort{Node: n.Node, Port: n.Port})
			}
			if a.End == "b" {
				l.B = end
			} else {
				l.A = end
			}
		}
	}
	for _, id := range slices.Sorted(maps.Keys(links)) {
		l := links[id]
		b.Links = append(b.Links, *l)
		for _, e := range []findings.VerifyEnd{l.A, l.B} {
			if e.Outcome == Skipped {
				link := id
				linkSkips = append(linkSkips, findings.VerifySkip{Node: e.Node, Port: e.Port, Reason: e.Reason, Link: &link})
			}
		}
	}
	b.Skipped = append(portSkips, linkSkips...)

	var claims findings.VerifyCount
	for _, c := range r.Claims {
		var holds *string
		if c.Holds != nil {
			h := *c.Holds
			holds = &h
		}
		b.Record = append(b.Record, findings.VerifyClaim{Node: c.Node, Holds: holds, Staged: c.Staged, Outcome: c.Outcome})
		if c.Outcome == Held {
			claims.Held++
		} else {
			claims.Failed++
		}
	}
	b.Counts = findings.VerifyCounts{
		HostName:    hostNames.block(false),
		PortEnabled: ports.block(true),
		Neighbor:    neighbours.block(true),
		Record:      claims,
	}
	return b
}

// readOf is an assertion's read value for the block: nil when nothing was read.
func readOf(a Assertion) *string {
	if a.Outcome != Held && a.Outcome != Failed {
		return nil
	}
	v := a.Read
	return &v
}

// counter counts one kind's assertions by outcome; failed counts absent too.
type counter struct{ held, failed, skipped, unread int }

func (c *counter) count(outcome string) {
	switch outcome {
	case Held:
		c.held++
	case Failed, Absent:
		c.failed++
	case Skipped:
		c.skipped++
	case Unread:
		c.unread++
	}
}

func (c counter) block(skips bool) findings.VerifyCount {
	unread := c.unread
	out := findings.VerifyCount{Held: c.held, Failed: c.failed, Unread: &unread}
	if skips {
		skipped := c.skipped
		out.Skipped = &skipped
	}
	return out
}

func twinBlock(t TwinInfo) findings.VerifyTwin {
	out := findings.VerifyTwin{BundleID: t.BundleID, Waypoint: waypointBlock(t.Waypoint), State: t.State, Source: t.Source, Nodes: t.Nodes}
	if d := t.Diverged; d != nil {
		out.Diverged = &findings.VerifyDiverged{
			Towards: findings.VerifyTowards{Waypoint: waypointBlock(d.Towards), BundleID: d.TowardsBundle},
			Run:     findings.ShowRef{WorkflowID: wire.StepWorkflowID, RunID: d.RunID},
			Phase:   d.Phase,
		}
	}
	return out
}

func waypointBlock(w *wire.WaypointRef) *findings.ShowWaypoint {
	if w == nil {
		return nil
	}
	return &findings.ShowWaypoint{Series: w.Series, Sequence: w.Sequence, Description: w.Description, AtSource: w.AtSource}
}
