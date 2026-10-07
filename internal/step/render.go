package step

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"
)

// Pair is one step as `waypoint plan` reports it: the two waypoints it joins, and either
// the step between their bundles or why none was computed. The text and the JSON are both
// rendered from it, so the two cannot disagree.
type Pair struct {
	// From and To are the two waypoint references, demo/1 and demo/2.
	From, To string
	// FromID and ToID are each side's bundle_id, empty for a side that did not compile.
	FromID, ToID string
	// Step is the difference, nil when it was not computed.
	Step *Step
	// Why says why no step was computed, e.g. "demo/5 was refused"; empty when Step is set.
	Why string
}

// Between is the step from one waypoint's bundle to the next's.
func Between(from, to string, s Step) Pair {
	return Pair{From: from, To: to, FromID: s.From, ToID: s.To, Step: &s}
}

// NotComputed is a pair with no step, because one side or both did not compile. why is
// what the text puts in parentheses and the JSON in not_computed.
func NotComputed(from, to, fromID, toID, why string) Pair {
	return Pair{From: from, To: to, FromID: fromID, ToID: toID, Why: why}
}

// Text is the block `waypoint plan` prints for the pair, with no trailing newline
// (contracts/cli.md):
//
//	step demo/1 → demo/2 (35aea06f… → 9c2d01e7…):
//	  nodes: +n4; ~n1 (bootstrap, mapping)
//	  links: +n1:e1-3 — n4:e1-1
//	  artifacts: n1 device-config 43e8fd0c… → 9a0177b2…; n4 device-config added
//	step demo/2 → demo/3 (9c2d01e7… → 51f0aa93…): unchanged; the ids differ by provenance alone
//	step demo/3 → demo/5 (51f0aa93… → —): not computed (demo/5 was refused)
//
// Ids and checksums are shortened to eight characters; the JSON carries them whole. No
// line quotes an artifact or a bootstrap: the step holds none of their bytes.
func (p Pair) Text() string {
	head := fmt.Sprintf("step %s → %s (%s → %s):", p.From, p.To, short(p.FromID), short(p.ToID))
	s := p.Step
	switch {
	case s == nil:
		return head + " not computed (" + p.Why + ")"
	case s.Unchanged && s.From == s.To:
		return head + " unchanged; the two are one bundle"
	case s.Unchanged:
		return head + " unchanged; the ids differ by provenance alone"
	}
	return strings.Join([]string{
		head,
		"  nodes: " + orUnchanged(nodeParts(s)),
		"  links: " + orUnchanged(linkParts(s)),
		"  artifacts: " + orUnchanged(artifactParts(s)),
	}, "\n")
}

func nodeParts(s *Step) []string {
	var out []string
	for _, n := range s.NodesAdded {
		out = append(out, "+"+n)
	}
	for _, n := range s.NodesRemoved {
		out = append(out, "-"+n)
	}
	for _, c := range s.NodesChanged {
		out = append(out, fmt.Sprintf("~%s (%s)", c.Node, strings.Join(c.Reasons, ", ")))
	}
	return out
}

func linkParts(s *Step) []string {
	var out []string
	for _, l := range s.LinksAdded {
		out = append(out, "+"+linkText(l))
	}
	for _, l := range s.LinksRemoved {
		out = append(out, "-"+linkText(l))
	}
	return out
}

func linkText(l LinkRef) string {
	return fmt.Sprintf("%s:%s — %s:%s", l.A.Node, l.A.Port, l.B.Node, l.B.Port)
}

// artifactParts names every artifact that differs, sorted by node: a changed one with both
// checksums, one that came or went with its node as added or removed.
func artifactParts(s *Step) []string {
	type part struct{ node, text string }
	var parts []part
	for _, a := range s.ArtifactsChanged {
		parts = append(parts, part{a.Node, fmt.Sprintf("%s %s %s → %s", a.Node, a.Name, short(a.From), short(a.To))})
	}
	for _, a := range s.ArtifactsAdded {
		parts = append(parts, part{a.Node, a.Node + " " + a.Name + " added"})
	}
	for _, a := range s.ArtifactsRemoved {
		parts = append(parts, part{a.Node, a.Node + " " + a.Name + " removed"})
	}
	// Each node is in one of the three lists at most, so ordering by node is total.
	sort.Slice(parts, func(i, j int) bool { return parts[i].node < parts[j].node })
	out := make([]string, len(parts))
	for i, p := range parts {
		out[i] = p.text
	}
	return out
}

func orUnchanged(parts []string) string {
	if len(parts) == 0 {
		return "unchanged"
	}
	return strings.Join(parts, "; ")
}

// short is the first eight characters of an id or a checksum and an ellipsis, as the text
// prints them; a side with no bundle is a dash.
func short(s string) string {
	switch {
	case s == "":
		return "—"
	case len(s) > 8:
		return s[:8] + "…"
	}
	return s
}

// The JSON shape of a pair: waypoints.schema.json's $defs/step. Every list is present,
// [] when empty.
type (
	pairJSON struct {
		From         string         `json:"from"`
		To           string         `json:"to"`
		FromBundleID *string        `json:"from_bundle_id"`
		ToBundleID   *string        `json:"to_bundle_id"`
		Computed     bool           `json:"computed"`
		NotComputed  string         `json:"not_computed,omitempty"`
		Unchanged    *bool          `json:"unchanged,omitempty"`
		Nodes        *nodesJSON     `json:"nodes,omitempty"`
		Links        *linksJSON     `json:"links,omitempty"`
		Artifacts    *artifactsJSON `json:"artifacts,omitempty"`
	}
	nodesJSON struct {
		Added   []string         `json:"added"`
		Removed []string         `json:"removed"`
		Changed []nodeChangeJSON `json:"changed"`
	}
	nodeChangeJSON struct {
		Node    string   `json:"node"`
		Reasons []string `json:"reasons"`
	}
	linksJSON struct {
		Added   []linkJSON `json:"added"`
		Removed []linkJSON `json:"removed"`
	}
	linkJSON struct {
		ID string       `json:"id"`
		A  nodePortJSON `json:"a"`
		B  nodePortJSON `json:"b"`
	}
	nodePortJSON struct {
		Node string `json:"node"`
		Port string `json:"port"`
	}
	artifactsJSON struct {
		Changed []artifactJSON `json:"changed"`
	}
	artifactJSON struct {
		Node string `json:"node"`
		Name string `json:"name"`
		From string `json:"from"`
		To   string `json:"to"`
	}
)

// MarshalJSON writes the pair as waypoints.schema.json's step: the checksums whole, an
// added or removed node's artifact left to the node, as the contract has it.
func (p Pair) MarshalJSON() ([]byte, error) {
	out := pairJSON{From: p.From, To: p.To, FromBundleID: idOrNull(p.FromID), ToBundleID: idOrNull(p.ToID)}
	s := p.Step
	if s == nil {
		out.NotComputed = p.Why
		return json.Marshal(out)
	}
	unchanged := s.Unchanged
	out.Computed, out.Unchanged = true, &unchanged

	nodes := &nodesJSON{Added: orEmpty(s.NodesAdded), Removed: orEmpty(s.NodesRemoved), Changed: []nodeChangeJSON{}}
	for _, c := range s.NodesChanged {
		nodes.Changed = append(nodes.Changed, nodeChangeJSON(c))
	}
	links := &linksJSON{Added: linksJSONOf(s.LinksAdded), Removed: linksJSONOf(s.LinksRemoved)}
	artifacts := &artifactsJSON{Changed: []artifactJSON{}}
	for _, a := range s.ArtifactsChanged {
		artifacts.Changed = append(artifacts.Changed, artifactJSON(a))
	}
	out.Nodes, out.Links, out.Artifacts = nodes, links, artifacts
	return json.Marshal(out)
}

func linksJSONOf(links []LinkRef) []linkJSON {
	out := []linkJSON{}
	for _, l := range links {
		out = append(out, linkJSON{ID: l.ID, A: nodePortJSON(l.A), B: nodePortJSON(l.B)})
	}
	return out
}

func idOrNull(id string) *string {
	if id == "" {
		return nil
	}
	return &id
}

func orEmpty(xs []string) []string {
	if xs == nil {
		return []string{}
	}
	return xs
}
