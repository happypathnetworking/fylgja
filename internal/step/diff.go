// Package step is the difference between two compiled bundles: what a twin built from one
// would have to become to be a twin built from the other (M10). `waypoint plan` prints it
// between consecutive
// waypoints of a series; M11 applies it.
//
// Diff is a pure function, as the compiler is: two bundles in memory in, a Step out, no
// file, network or clock. A test in the compiler's shape holds the import
// boundary. It reads each side's manifest and the bootstrap files the manifest names, and
// nothing else: an artifact is compared by the checksum its manifest entry carries, never
// by its bytes, and no byte of an artifact or a bootstrap reaches the result.
//
// Provenance is excluded entirely. The at is hashed into bundle_id with everything else,
// so two waypoints never share an id even when nothing they seal differs.
// The step compares content, and the ids are printed beside it.
package step

import (
	"encoding/json"
	"fmt"
	"sort"

	"github.com/happypathnetworking/fylgja/internal/compiler"
)

// manifestFile is the one file of a bundle that describes the rest.
const manifestFile = "manifest.json"

// Bundle is a compiled bundle in memory: its identity and its files, as stage.Compile
// returns them and as bundle.Fetch would read them back. The step never reads disk.
type Bundle struct {
	ID    string
	Files map[string][]byte
}

// Why a node present on both sides changed (waypoints.schema.json, $defs/step). Listed in
// this order, which is also their sort order.
const (
	ReasonBootstrap = "bootstrap" // the node's bootstrap file's bytes differ
	ReasonImage     = "image"
	ReasonMapping   = "mapping" // one of the node's interfaces maps to another port, node name, type or management flag, or one was added or removed
	ReasonPlatform  = "platform"
	ReasonPSP       = "psp" // the support package's id
)

// Step is what differs between two bundles, provenance excluded. Every list is sorted, so
// the same two bundles give the same Step from any file-map order.
type Step struct {
	// From and To are the two bundle ids.
	From, To string
	// Unchanged is every list below empty: the two bundles differ in provenance alone, or
	// not at all. A mapping row's enabled is not compared: intent's
	// disabling reaches the node through the artifact, whose checksum ArtifactsChanged
	// compares, so two bundles that differ in a row's enabled alone are Unchanged.
	Unchanged bool

	NodesAdded   []string
	NodesRemoved []string
	NodesChanged []NodeChange

	// A link is its ends: one whose id or either end differs is removed and added, never
	// changed.
	LinksAdded   []LinkRef
	LinksRemoved []LinkRef

	// ArtifactsChanged is every node on both sides whose artifact checksum differs.
	ArtifactsChanged []ArtifactChange
	// ArtifactsAdded and ArtifactsRemoved are the artifacts that come and go with a node
	// (or, in a bundle this build did not write, a node that gained or lost one). The text
	// names them; the JSON leaves them to the node, as the contract does.
	ArtifactsAdded   []ArtifactRef
	ArtifactsRemoved []ArtifactRef
}

// NodeChange is one node on both sides that differs, and why.
type NodeChange struct {
	Node    string
	Reasons []string // sorted, each once
}

// LinkRef is one cabled link as the manifest carries it: its canonical id (D-011) and its
// two ends by node and containerlab port.
type LinkRef struct {
	ID   string
	A, B NodePort
}

// NodePort is one end of a link.
type NodePort struct {
	Node, Port string
}

// ArtifactChange is one node's artifact on both sides, by name and both checksums.
type ArtifactChange struct {
	Node, Name string
	From, To   string // checksums
}

// ArtifactRef is an artifact that came or went with its node, by name.
type ArtifactRef struct {
	Node, Name string
}

// side is one bundle as the diff reads it.
type side struct {
	// nodes by name, their mapping rows by interface, and their bootstrap bytes.
	nodes     map[string]compiler.ManifestNode
	mapping   map[string]map[string]mappingKey
	bootstrap map[string][]byte
	links     map[LinkRef]bool
}

// mappingKey is what the step compares of one interface's mapping row.
// The disposition is not in it: whether an interface is cabled is the links' to say.
type mappingKey struct {
	port, nodeName string
	hasPort        bool
	hasNodeName    bool
	iftype         string
	mgmtOnly       bool
}

// Diff is the step from bundle a to bundle b. A side whose manifest is absent or does
// not parse, is of a bundle version this build does not write, or names a bootstrap file
// the bundle lacks, is an error naming the side and the file; it cannot happen to a
// bundle stage.Compile produced.
func Diff(a, b Bundle) (Step, error) {
	from, err := read("from", a)
	if err != nil {
		return Step{}, err
	}
	to, err := read("to", b)
	if err != nil {
		return Step{}, err
	}

	s := Step{From: a.ID, To: b.ID}
	for _, name := range sortedKeys(to.nodes) {
		if _, ok := from.nodes[name]; !ok {
			s.NodesAdded = append(s.NodesAdded, name)
			if art := to.nodes[name].Artifact; art != nil {
				s.ArtifactsAdded = append(s.ArtifactsAdded, ArtifactRef{Node: name, Name: art.Name})
			}
		}
	}
	for _, name := range sortedKeys(from.nodes) {
		was := from.nodes[name]
		now, ok := to.nodes[name]
		if !ok {
			s.NodesRemoved = append(s.NodesRemoved, name)
			if was.Artifact != nil {
				s.ArtifactsRemoved = append(s.ArtifactsRemoved, ArtifactRef{Node: name, Name: was.Artifact.Name})
			}
			continue
		}
		if reasons := nodeReasons(from, to, name); len(reasons) > 0 {
			s.NodesChanged = append(s.NodesChanged, NodeChange{Node: name, Reasons: reasons})
		}
		switch {
		case was.Artifact != nil && now.Artifact != nil:
			if was.Artifact.Checksum != now.Artifact.Checksum {
				s.ArtifactsChanged = append(s.ArtifactsChanged, ArtifactChange{Node: name, Name: now.Artifact.Name,
					From: was.Artifact.Checksum, To: now.Artifact.Checksum})
			}
		case now.Artifact != nil:
			s.ArtifactsAdded = append(s.ArtifactsAdded, ArtifactRef{Node: name, Name: now.Artifact.Name})
		case was.Artifact != nil:
			s.ArtifactsRemoved = append(s.ArtifactsRemoved, ArtifactRef{Node: name, Name: was.Artifact.Name})
		}
	}
	s.LinksAdded = linksOnlyIn(to, from)
	s.LinksRemoved = linksOnlyIn(from, to)
	sortArtifacts(s.ArtifactsAdded)
	sortArtifacts(s.ArtifactsRemoved)

	s.Unchanged = len(s.NodesAdded) == 0 && len(s.NodesRemoved) == 0 && len(s.NodesChanged) == 0 &&
		len(s.LinksAdded) == 0 && len(s.LinksRemoved) == 0 &&
		len(s.ArtifactsChanged) == 0 && len(s.ArtifactsAdded) == 0 && len(s.ArtifactsRemoved) == 0
	return s, nil
}

// read parses one side's manifest and gathers what the step compares.
func read(which string, b Bundle) (*side, error) {
	fail := func(file, format string, args ...any) error {
		return fmt.Errorf("the %s bundle %s: %s: %s", which, b.ID, file, fmt.Sprintf(format, args...))
	}
	raw, ok := b.Files[manifestFile]
	if !ok {
		return nil, fail(manifestFile, "not in the bundle")
	}
	s := &side{nodes: map[string]compiler.ManifestNode{}, mapping: map[string]map[string]mappingKey{},
		bootstrap: map[string][]byte{}, links: map[LinkRef]bool{}}
	var m compiler.Manifest
	if err := json.Unmarshal(raw, &m); err != nil {
		return nil, fail(manifestFile, "does not parse: %v", err)
	}
	if v := m.BundleVersion; v != compiler.BundleVersion {
		return nil, fail(manifestFile, "is bundle version %q; this build compares %q", v, compiler.BundleVersion)
	}
	for _, n := range m.Nodes {
		if _, dup := s.nodes[n.Name]; dup {
			return nil, fail(manifestFile, "names node %s twice", n.Name)
		}
		s.nodes[n.Name] = n
		file := n.Bootstrap.File
		if file == "" {
			return nil, fail(manifestFile, "names no bootstrap file for node %s", n.Name)
		}
		body, ok := b.Files[file]
		if !ok {
			return nil, fail(file, "named as node %s's bootstrap, is not in the bundle", n.Name)
		}
		s.bootstrap[n.Name] = body
	}
	for _, r := range m.Mapping {
		rows := s.mapping[r.Device]
		if rows == nil {
			rows = map[string]mappingKey{}
			s.mapping[r.Device] = rows
		}
		k := mappingKey{iftype: r.Iftype, mgmtOnly: r.MgmtOnly}
		if r.Port != nil {
			k.port, k.hasPort = *r.Port, true
		}
		if r.NodeName != nil {
			k.nodeName, k.hasNodeName = *r.NodeName, true
		}
		rows[r.Interface] = k
	}
	for _, l := range m.Links {
		s.links[LinkRef{ID: l.ID, A: NodePort{Node: l.A.Node, Port: l.A.Port}, B: NodePort{Node: l.B.Node, Port: l.B.Port}}] = true
	}
	return s, nil
}

// nodeReasons is why a node on both sides differs, sorted; none when it does not.
func nodeReasons(from, to *side, name string) []string {
	was, now := from.nodes[name], to.nodes[name]
	var reasons []string
	if string(from.bootstrap[name]) != string(to.bootstrap[name]) {
		reasons = append(reasons, ReasonBootstrap)
	}
	if was.Image != now.Image {
		reasons = append(reasons, ReasonImage)
	}
	if !sameMapping(from.mapping[name], to.mapping[name]) {
		reasons = append(reasons, ReasonMapping)
	}
	if was.Platform != now.Platform {
		reasons = append(reasons, ReasonPlatform)
	}
	if was.PSP.ID != now.PSP.ID {
		reasons = append(reasons, ReasonPSP)
	}
	sort.Strings(reasons)
	return reasons
}

// sameMapping is whether a node's interfaces map alike on both sides: the same interfaces,
// each to the same port, node name, type and management flag.
func sameMapping(a, b map[string]mappingKey) bool {
	if len(a) != len(b) {
		return false
	}
	for iface, k := range a {
		if other, ok := b[iface]; !ok || other != k {
			return false
		}
	}
	return true
}

// linksOnlyIn is every link of one side the other lacks, sorted by id and then by ends.
func linksOnlyIn(this, other *side) []LinkRef {
	var out []LinkRef
	for l := range this.links {
		if !other.links[l] {
			out = append(out, l)
		}
	}
	sort.Slice(out, func(i, j int) bool {
		a, b := out[i], out[j]
		if a.ID != b.ID {
			return a.ID < b.ID
		}
		if a.A != b.A {
			return portLess(a.A, b.A)
		}
		return portLess(a.B, b.B)
	})
	return out
}

func portLess(a, b NodePort) bool {
	if a.Node != b.Node {
		return a.Node < b.Node
	}
	return a.Port < b.Port
}

func sortArtifacts(refs []ArtifactRef) {
	sort.Slice(refs, func(i, j int) bool { return refs[i].Node < refs[j].Node })
}

func sortedKeys[V any](m map[string]V) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}
