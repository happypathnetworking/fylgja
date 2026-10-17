package intent

import (
	"context"
	"fmt"
	"time"

	"github.com/happypathnetworking/fylgja/internal/ctm"
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

// intentFields are the fields of each of Fylgja's generics whose writes are a device's
// intent: exactly those the stamps read folds into one, the ones that reach the artifact
// or the bundle (IntentStamps; research R-07, T076), an interface's device beside its
// device's interfaces, the one edge seen from each end. Infrahub gives every generic its
// own memberships and profiles, and a device kind its artifacts; an update of those alone
// is Infrahub's churn and never intent (D-048): a query group's membership of every
// device is rewritten seconds after each generation, after its checksum.
var intentFields = map[string][]string{
	ctm.DeviceGeneric: {"name", "role", "site", "platform", "interfaces"},
	"FylgjaInterface": {"name", "iftype", "mgmt_only", "enabled", "link", "parent", "device"},
	"FylgjaLink":      {"endpoints"},
	"FylgjaPlatform":  {"vendor", "nos", "version"},
}

// Event is one write the branch's event log records that is intent's (D-048): its primary
// node's kind implements one of Fylgja's generics on the branch, and it created or deleted
// that node or changed one of intentFields. A removal moves no stamp the stamps read
// selects (research §8.17); its event is how the head and the staleness rule see it.
// Every field is as Infrahub returned it.
type Event struct {
	// Name is Infrahub's name for the event: infrahub.node.deleted.
	Name string
	// OccurredAt is when Infrahub recorded it, verbatim: 2026-10-17T13:55:09.031152+00:00.
	OccurredAt string
	// Kind is the primary node's concrete kind, read only to be mapped to a generic and to
	// be named in a message, never queried (Constitution III).
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
// when it is a node's own write (a NodeMutatedEvent) whose primary node's kind is in the
// used_by of one of ctm.RequiredGenerics in the branch's schema, as conformance maps a
// kind, whatever the event's level, and it created or deleted the node or changed one of
// the fields intentFields gives that generic. The schema is read once, and only when an
// event is to be mapped.
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
	var kinds map[string]map[string]bool
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
			if kinds == nil {
				if kinds, err = r.intentKinds(ctx, branch); err != nil {
					return nil, err
				}
			}
			fields := kinds[primary.GetKind()]
			if fields == nil || !changesIntent(mutated, fields) {
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
// an update naming one of fields among the attributes or relationships it changed.
func changesIntent(e *IntentEventsInfrahubEventEventsEdgesEventNodesNodeNodeMutatedEvent, fields map[string]bool) bool {
	switch e.GetEvent() {
	case eventNodeCreated, eventNodeDeleted:
		return true
	}
	for _, a := range e.GetAttributes() {
		if fields[a.GetName()] {
			return true
		}
	}
	for _, rel := range e.GetRelationships() {
		if fields[rel.GetName()] {
			return true
		}
	}
	return false
}

// intentKinds maps every concrete kind on the branch that implements one of Fylgja's
// generics to the fields intentFields gives the generics it implements, from the branch's
// schema endpoint as conformance reads it.
func (r *StageReader) intentKinds(ctx context.Context, branch string) (map[string]map[string]bool, error) {
	info, err := New(Config{Address: r.address, Token: r.token, Branch: branch}).SchemaInfo(ctx)
	if err != nil {
		return nil, err
	}
	kinds := map[string]map[string]bool{}
	for _, generic := range ctm.RequiredGenerics {
		for _, kind := range info.UsedBy[generic] {
			if kinds[kind] == nil {
				kinds[kind] = map[string]bool{}
			}
			for _, f := range intentFields[generic] {
				kinds[kind][f] = true
			}
		}
	}
	return kinds, nil
}
