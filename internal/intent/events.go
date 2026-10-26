package intent

import (
	"context"
	"fmt"
	"time"
)

// eventPageSize is InfrahubEvent's own limit: Infrahub refuses a larger one (research
// §8.18).
const eventPageSize = 50

// The two events that are always intent's when their node's kind is: a node of intent
// created or deleted. An update is intent's only by the fields it changed.
const (
	eventNodeCreated = "infrahub.node.created"
	eventNodeDeleted = "infrahub.node.deleted"
)

// intentGenerics are the library's generics whose implementers' writes are intent's: the
// kinds the stamps read (017 research R-10), each found on the branch through its schema's
// used_by, so an implementer of the operator's own counts as the library's do.
var intentGenerics = []string{"DcimGenericDevice", "DcimInterface", "DcimConnector"}

// intentNodes are the concrete kinds the stamps read beside the generics' implementers.
var intentNodes = []string{"DcimPlatform", "OrganizationManufacturer"}

// churnRelationships are Infrahub's own relationships on every node, whose writes alone
// are churn and never intent (D-048): a query group's membership of every node the
// template's query read is rewritten seconds after each generation, after its checksum;
// an artifact's creation adds one on its device.
var churnRelationships = map[string]bool{
	"member_of_groups":     true,
	"subscriber_of_groups": true,
	"artifacts":            true,
	"profiles":             true,
	"object_template":      true,
}

// Event is one write the branch's event log records that is intent's (D-048): its primary
// node's kind is one the stamps read on the branch, and it created or deleted that node, or
// changed an attribute or a relationship that is not Infrahub's churn. A removal moves no
// stamp the stamps read selects (research §8.17); its event is how the head and the
// staleness rule see it. Every field is as Infrahub returned it.
type Event struct {
	// Name is Infrahub's name for the event: infrahub.node.deleted.
	Name string
	// OccurredAt is when Infrahub recorded it, verbatim: 2026-10-17T13:55:09.031152+00:00.
	OccurredAt string
	// Kind is the primary node's concrete kind, read only to be mapped to a kind the
	// stamps read and to be named in a message, never queried.
	Kind string
	// Nodes are the ids the event names: its primary node's, then each peer of its
	// relationships, a removed one included.
	Nodes []string
}

// Names reports whether the event names any of ids, as its primary node or a peer.
func (e Event) Names(ids []string) bool {
	for _, n := range e.Nodes {
		for _, id := range ids {
			if n == id {
				return true
			}
		}
	}
	return false
}

// IntentEvents reads the branch's events through InfrahubEvent, bounded to the branch
// and to since (its branched_from, verbatim, so an earlier branch of the same name is not
// read), newest first, pinned to nothing, and returns those that are intent's and occurred
// after after, newest first. Paging stops at the first page that reaches an event no later
// than after; an empty after reads every page since since. Infrahub's own churn (query
// groups, artifacts, memberships, the stage kind) is never intent: an event is intent's
// when it is a node's own write (a NodeMutatedEvent) with a primary node whose kind is one
// intentKinds maps, whatever the event's level, and it created or deleted the node or
// changed an attribute or a relationship but churnRelationships. An event with no primary
// node is skipped. The schema is read once, and only when an event is to be mapped.
//
// An event Infrahub records while the pages are read shifts the later pages by one, so an
// event can come back twice and none is missed; a caller takes the latest or asks whether
// one names a device, which a repeat does not change.
func (r *StageReader) IntentEvents(ctx context.Context, branch, since, after string) ([]Event, error) {
	what := "reading the event log of branch " + branch
	var floor time.Time
	if after != "" {
		t, err := parseStamp(after)
		if err != nil {
			return nil, fmt.Errorf("%s %s: %w", what, stagesWhere, err)
		}
		floor = t
	}
	var kinds map[string]bool
	var out []Event
	for offset := 0; ; offset += eventPageSize {
		resp, err := IntentEvents(ctx, r.gql, branch, since, eventPageSize, offset)
		if err != nil {
			return nil, r.wrap(err, what, "")
		}
		page := resp.GetInfrahubEvent()
		edges := page.GetEdges()
		done := len(edges) == 0 || offset+len(edges) >= page.GetCount()
		for _, edge := range edges {
			n := edge.GetNode()
			if n == nil {
				continue
			}
			at, err := parseStamp(n.GetOccurred_at())
			if err != nil {
				return nil, fmt.Errorf("%s %s: %w", what, stagesWhere, err)
			}
			if after != "" && !at.After(floor) {
				done = true
				break
			}
			mutated, ok := n.(*IntentEventsInfrahubEventEventsEdgesEventNodesNodeNodeMutatedEvent)
			if !ok {
				continue // an artifact's, a group's or a branch's own event: no node's write
			}
			primary := mutated.GetPrimary_node()
			if primary.GetId() == "" {
				continue // no primary node: a schema's update names none (research §1.8)
			}
			if kinds == nil {
				if kinds, err = r.intentKinds(ctx, branch); err != nil {
					return nil, err
				}
			}
			if !kinds[primary.GetKind()] || !changesIntent(mutated) {
				continue
			}
			ev := Event{Name: mutated.GetEvent(), OccurredAt: mutated.GetOccurred_at(), Kind: primary.GetKind(),
				Nodes: []string{primary.GetId()}}
			for _, rel := range mutated.GetRelationships() {
				peer := rel.GetPeer()
				ev.Nodes = append(ev.Nodes, peer.GetId())
			}
			out = append(out, ev)
		}
		if done {
			return out, nil
		}
	}
}

// changesIntent reports whether a node's write is intent's: its creation or deletion, or
// an update naming any attribute, or any relationship but Infrahub's churn.
func changesIntent(e *IntentEventsInfrahubEventEventsEdgesEventNodesNodeNodeMutatedEvent) bool {
	switch e.GetEvent() {
	case eventNodeCreated, eventNodeDeleted:
		return true
	}
	if len(e.GetAttributes()) > 0 {
		return true
	}
	for _, rel := range e.GetRelationships() {
		if !churnRelationships[rel.GetName()] {
			return true
		}
	}
	return false
}

// intentKinds is every concrete kind on the branch the stamps read: each implementer of
// intentGenerics, from the branch's schema endpoint as conformance reads it, and
// intentNodes.
func (r *StageReader) intentKinds(ctx context.Context, branch string) (map[string]bool, error) {
	info, err := New(Config{Address: r.address, Token: r.token, Branch: branch}).SchemaInfo(ctx)
	if err != nil {
		return nil, err
	}
	kinds := map[string]bool{}
	for _, generic := range intentGenerics {
		for _, kind := range info.UsedBy[generic] {
			kinds[kind] = true
		}
	}
	for _, kind := range intentNodes {
		kinds[kind] = true
	}
	return kinds, nil
}
