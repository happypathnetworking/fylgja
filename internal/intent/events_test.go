package intent

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"sync"
	"testing"
)

// fakeEvents is Infrahub's event log for one branch, newest first, and the branch's
// schema, the library's kinds implementing its generics; it records what it was asked.
type fakeEvents struct {
	events []map[string]any
	// extra are implementers of the operator's own beside the library's, kind to generic.
	extra map[string]string

	mu      sync.Mutex
	schemas []string         // the branch of each schema read
	pages   []map[string]any // the variables of each page read
}

func (f *fakeEvents) serve(w http.ResponseWriter, r *http.Request) {
	switch {
	case r.Method == http.MethodGet && r.URL.Path == "/api/schema":
		f.mu.Lock()
		f.schemas = append(f.schemas, r.URL.Query().Get("branch"))
		f.mu.Unlock()
		generic := func(kind string, usedBy ...string) map[string]any {
			for k, g := range f.extra {
				if g == kind {
					usedBy = append(usedBy, k)
				}
			}
			return map[string]any{"kind": kind, "used_by": usedBy}
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"main": "908871c3", "generics": []any{
			generic("DcimGenericDevice", "DcimDevice"),
			generic("DcimInterface", "InterfacePhysical", "InterfaceVirtual"),
			generic("DcimEndpoint", "InterfacePhysical"), generic("DcimConnector", "DcimCable"),
			generic("CoreGroup", "CoreGraphQLQueryGroup"), generic("CoreArtifactTarget", "DcimDevice"),
		}, "nodes": []any{
			map[string]any{"kind": "DcimDevice"}, map[string]any{"kind": "DcimPlatform"},
			map[string]any{"kind": "OrganizationManufacturer"}, map[string]any{"kind": "BuiltinTag"},
			map[string]any{"kind": StageKind},
		}})
	case r.Method == http.MethodPost && r.URL.Path == "/graphql":
		var req struct {
			OperationName string         `json:"operationName"`
			Query         string         `json:"query"`
			Variables     map[string]any `json:"variables"`
		}
		body, _ := io.ReadAll(r.Body)
		_ = json.Unmarshal(body, &req)
		if req.OperationName != "IntentEvents" {
			http.Error(w, "unknown operation "+req.OperationName, http.StatusTeapot)
			return
		}
		f.mu.Lock()
		f.pages = append(f.pages, req.Variables)
		f.mu.Unlock()
		limit, _ := req.Variables["limit"].(float64)
		offset, _ := req.Variables["offset"].(float64)
		edges := []any{}
		for i := int(offset); i < len(f.events) && i < int(offset+limit); i++ {
			edges = append(edges, map[string]any{"node": f.events[i]})
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"data": map[string]any{"InfrahubEvent": map[string]any{
			"count": len(f.events), "edges": edges}}})
	default:
		http.NotFound(w, r)
	}
}

func (f *fakeEvents) reader(t *testing.T) *StageReader {
	srv := httptest.NewServer(http.HandlerFunc(f.serve))
	t.Cleanup(srv.Close)
	return NewStageReader(srv.URL, "secret-token")
}

// rel is one relationship an event says changed: its name and its peer's id.
type rel struct{ name, peer string }

// mutated is a NodeMutatedEvent of the log: a node's own write, with the attributes and
// relationships it changed.
func mutated(name, at, kind, id string, attrs []string, rels ...rel) map[string]any {
	attributes, relationships := []any{}, []any{}
	for _, a := range attrs {
		attributes = append(attributes, map[string]any{"name": a})
	}
	for _, r := range rels {
		relationships = append(relationships, map[string]any{"name": r.name, "peer": map[string]any{"id": r.peer}})
	}
	return map[string]any{"__typename": "NodeMutatedEvent", "event": name, "occurred_at": at,
		"primary_node": map[string]any{"id": id, "kind": kind}, "attributes": attributes, "relationships": relationships}
}

// other is an event of another type, which records no node's write: an artifact's, a
// group's, a branch's (kind "" names no node).
func other(typename, name, at, kind, id string) map[string]any {
	n := map[string]any{"__typename": typename, "event": name, "occurred_at": at, "primary_node": nil}
	if kind != "" {
		n["primary_node"] = map[string]any{"id": id, "kind": kind}
	}
	return n
}

const (
	eventBranched = "2026-10-17T13:54:10.452384Z"
	eventDeleted  = "2026-10-17T13:55:09.031152+00:00"
)

// The log of a branch over the library's kinds, newest first (research §1.8, §8.18): the
// regenerate's churn, a cable re-ended with its child event on the former port, a tag added
// and removed, the generation's churn, the seed. Only a node's own write of a kind the
// stamps read is intent, at any level: the device, an interface of either kind, a cable, a
// platform and a manufacturer. Of an update, one changing any attribute or any relationship
// but Infrahub's churn: the query groups' memberships Infrahub rewrites on every node after
// each generation, a device's artifacts, a profile. A tag's own write, an artifact's, a
// group's, the stage kind's and an event with no primary node are not intent. A creation
// or a deletion is, whatever it names: one naming no attribute and only a query group's
// membership among them. Each names its primary node and every peer.
func TestIntentEventsMapsKinds(t *testing.T) {
	f := &fakeEvents{events: []map[string]any{
		mutated("infrahub.node.updated", "2026-10-17T13:55:32.691250+00:00", "DcimDevice", "dev-n1", nil,
			rel{"member_of_groups", "g-1"}),
		mutated("infrahub.node.updated", "2026-10-17T13:55:32.500000+00:00", "InterfaceVirtual", "if-n1-lo0", nil,
			rel{"member_of_groups", "g-1"}, rel{"subscriber_of_groups", "g-2"}),
		other("ArtifactEvent", "infrahub.artifact.updated", "2026-10-17T13:55:29.770104+00:00", "CoreArtifact", "a-1"),
		mutated("infrahub.node.updated", "2026-10-17T13:55:29.617911+00:00", "CoreArtifact", "a-1", []string{"storage_id", "checksum"}),
		mutated("infrahub.node.updated", "2026-10-17T13:55:21.000000+00:00", "DcimDevice", "dev-n2", nil,
			rel{"profiles", "prof-1"}, rel{"object_template", "tpl-1"}),
		mutated("infrahub.node.updated", "2026-10-17T13:55:18.000000+00:00", StageKind, "st-1", []string{"label"}),
		mutated("infrahub.node.updated", "2026-10-17T13:55:17.000000+00:00", "BuiltinTag", "tag-1", []string{"description"}),
		// infrahub.schema.updated names no primary node, as a standard event and as a
		// mutated one alike.
		other("StandardEvent", "infrahub.schema.updated", "2026-10-17T13:55:16.000000+00:00", "", ""),
		{"__typename": "NodeMutatedEvent", "event": "infrahub.schema.updated", "occurred_at": "2026-10-17T13:55:15.000000+00:00",
			"primary_node": nil, "attributes": []any{}, "relationships": []any{map[string]any{"name": "nodes", "peer": map[string]any{"id": "x"}}}},
		// A tag removed, then added: the device's tags edge, both ways.
		mutated("infrahub.node.updated", "2026-10-17T13:55:12.000000+00:00", "DcimDevice", "dev-n3", nil, rel{"tags", "tag-1"}),
		mutated("infrahub.node.updated", "2026-10-17T13:55:11.000000+00:00", "DcimDevice", "dev-n3", nil, rel{"tags", "tag-1"}),
		other("GroupEvent", "infrahub.group.member_removed", "2026-10-17T13:55:09.051000+00:00", "CoreGraphQLQueryGroup", "g-1"),
		mutated("infrahub.node.updated", "2026-10-17T13:55:09.049000+00:00", "CoreGraphQLQueryGroup", "g-1", nil,
			rel{"members", "cable-12"}),
		// The cable re-ended to n1's end alone, and the former port's own event.
		mutated("infrahub.node.updated", "2026-10-17T13:55:09.034000+00:00", "InterfacePhysical", "if-n2-e1", nil,
			rel{"connector", "cable-12"}),
		mutated("infrahub.node.updated", "2026-10-17T13:55:09.031152+00:00", "DcimCable", "cable-12", nil,
			rel{"connected_endpoints", "if-n2-e1"}),
		mutated("infrahub.node.updated", "2026-10-17T13:54:30.000000+00:00", "OrganizationManufacturer", "mf-1", []string{"description"}),
		mutated("infrahub.node.updated", "2026-10-17T13:54:29.000000+00:00", "DcimPlatform", "pf-1", []string{"description"}),
		mutated("infrahub.node.updated", "2026-10-17T13:54:27.731070+00:00", "DcimDevice", "dev-n1", nil,
			rel{"member_of_groups", "g-1"}),
		mutated("infrahub.node.updated", "2026-10-17T13:54:22.418356+00:00", "DcimDevice", "dev-n1", nil,
			rel{"artifacts", "a-1"}),
		mutated("infrahub.node.updated", "2026-10-17T13:54:20.000000+00:00", "DcimDevice", "dev-n2", []string{"serial"}),
		// A port created, then deleted, each event naming no attribute and only a query
		// group's membership: a creation or a deletion is intent by its event alone, whatever
		// it names (contracts/mapping.md §6).
		mutated("infrahub.node.deleted", "2026-10-17T13:54:19.000000+00:00", "InterfacePhysical", "if-n3-e2", nil,
			rel{"member_of_groups", "g-1"}),
		mutated("infrahub.node.created", "2026-10-17T13:54:18.000000+00:00", "InterfacePhysical", "if-n3-e2", nil,
			rel{"member_of_groups", "g-1"}),
		mutated("infrahub.node.created", "2026-10-17T13:54:16.683012+00:00", "DcimCable", "cable-12",
			[]string{"human_friendly_id", "display_label"}, rel{"connected_endpoints", "if-n1-e1"}, rel{"connected_endpoints", "if-n2-e1"}),
		mutated("infrahub.node.created", "2026-10-17T13:54:15.360731+00:00", "InterfaceVirtual", "if-n1-lo0",
			[]string{"name"}, rel{"device", "dev-n1"}),
		other("BranchCreatedEvent", "infrahub.branch.created", "2026-10-17T13:54:10.452400+00:00", "", ""),
	}}
	got, err := f.reader(t).IntentEvents(t.Context(), "change-1", eventBranched, "")
	if err != nil {
		t.Fatal(err)
	}
	want := []Event{
		{Name: "infrahub.node.updated", OccurredAt: "2026-10-17T13:55:12.000000+00:00", Kind: "DcimDevice", Nodes: []string{"dev-n3", "tag-1"}},
		{Name: "infrahub.node.updated", OccurredAt: "2026-10-17T13:55:11.000000+00:00", Kind: "DcimDevice", Nodes: []string{"dev-n3", "tag-1"}},
		{Name: "infrahub.node.updated", OccurredAt: "2026-10-17T13:55:09.034000+00:00", Kind: "InterfacePhysical", Nodes: []string{"if-n2-e1", "cable-12"}},
		{Name: "infrahub.node.updated", OccurredAt: eventDeleted, Kind: "DcimCable", Nodes: []string{"cable-12", "if-n2-e1"}},
		{Name: "infrahub.node.updated", OccurredAt: "2026-10-17T13:54:30.000000+00:00", Kind: "OrganizationManufacturer", Nodes: []string{"mf-1"}},
		{Name: "infrahub.node.updated", OccurredAt: "2026-10-17T13:54:29.000000+00:00", Kind: "DcimPlatform", Nodes: []string{"pf-1"}},
		{Name: "infrahub.node.updated", OccurredAt: "2026-10-17T13:54:20.000000+00:00", Kind: "DcimDevice", Nodes: []string{"dev-n2"}},
		{Name: "infrahub.node.deleted", OccurredAt: "2026-10-17T13:54:19.000000+00:00", Kind: "InterfacePhysical", Nodes: []string{"if-n3-e2", "g-1"}},
		{Name: "infrahub.node.created", OccurredAt: "2026-10-17T13:54:18.000000+00:00", Kind: "InterfacePhysical", Nodes: []string{"if-n3-e2", "g-1"}},
		{Name: "infrahub.node.created", OccurredAt: "2026-10-17T13:54:16.683012+00:00", Kind: "DcimCable", Nodes: []string{"cable-12", "if-n1-e1", "if-n2-e1"}},
		{Name: "infrahub.node.created", OccurredAt: "2026-10-17T13:54:15.360731+00:00", Kind: "InterfaceVirtual", Nodes: []string{"if-n1-lo0", "dev-n1"}},
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("events\n  %+v\nwant\n  %+v", got, want)
	}
	// The re-ended cable's event names its former port, and so counts for that port's
	// device, n2, and the port's own event does too; neither names n3.
	n2 := []string{"dev-n2", "if-n2-e1"}
	if !got[3].Names(n2) || !got[2].Names(n2) || got[3].Names([]string{"dev-n3", "if-n3-e1"}) {
		t.Errorf("the re-ending names %v and %v", got[3].Nodes, got[2].Nodes)
	}
	if !reflect.DeepEqual(f.schemas, []string{"change-1"}) {
		t.Errorf("schema reads %v; want the branch's, once", f.schemas)
	}
	if len(f.pages) != 1 || f.pages[0]["branch"] != "change-1" || f.pages[0]["since"] != eventBranched ||
		f.pages[0]["limit"] != float64(eventPageSize) || f.pages[0]["offset"] != float64(0) {
		t.Errorf("pages %v", f.pages)
	}
}

// An implementer of the operator's own, found through the branch schema's used_by, is
// intent's as the library's are; a kind that implements none is not.
func TestIntentEventsMapAnImplementerOfTheOperatorsOwn(t *testing.T) {
	f := &fakeEvents{events: []map[string]any{
		mutated("infrahub.node.updated", "2026-10-17T13:55:02.000000+00:00", "AcmeWidget", "w-1", []string{"name"}),
		mutated("infrahub.node.updated", "2026-10-17T13:55:01.000000+00:00", "InterfaceLag", "lag-1", []string{"name"}),
	}}
	f.extra = map[string]string{"InterfaceLag": "DcimInterface"}
	got, err := f.reader(t).IntentEvents(t.Context(), "change-1", eventBranched, "")
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 1 || got[0].Kind != "InterfaceLag" {
		t.Errorf("events %+v; want InterfaceLag's alone", got)
	}
}

// The pages stop at the first event no later than after, which none of the events
// returned is; an empty after reads every page, fifty at a time.
func TestIntentEventsPagesToTheBound(t *testing.T) {
	var events []map[string]any
	for i := range 120 {
		// Newest first: 13:55:59.000119 down to 13:55:59.000000.
		events = append(events, mutated("infrahub.node.updated", fmt.Sprintf("2026-10-17T13:55:59.%06d+00:00", 119-i),
			"InterfacePhysical", fmt.Sprintf("if-%d", 119-i), []string{"status"}))
	}
	f := &fakeEvents{events: events}
	r := f.reader(t)
	got, err := r.IntentEvents(t.Context(), "change-1", eventBranched, "")
	if err != nil || len(got) != 120 || len(f.pages) != 3 {
		t.Fatalf("every page: %d events, %d pages, %v", len(got), len(f.pages), err)
	}
	f.pages = nil
	got, err = r.IntentEvents(t.Context(), "change-1", eventBranched, "2026-10-17T13:55:59.000060+00:00")
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 59 || got[0].OccurredAt != "2026-10-17T13:55:59.000119+00:00" ||
		got[58].OccurredAt != "2026-10-17T13:55:59.000061+00:00" {
		t.Errorf("bounded: %d events, %v … %v", len(got), got[0], got[len(got)-1])
	}
	if len(f.pages) != 2 {
		t.Errorf("bounded: %d pages read, want the two that reach the bound", len(f.pages))
	}
}

// A log with nothing after the bound reads one page and no schema; a stamp that is not a
// time is refused, and nothing the reader returns carries the credential.
func TestIntentEventsQuietAndRefused(t *testing.T) {
	f := &fakeEvents{events: []map[string]any{
		mutated("infrahub.node.updated", "2026-10-17T13:54:00.000000+00:00", "InterfacePhysical", "if-1", []string{"status"}),
	}}
	got, err := f.reader(t).IntentEvents(t.Context(), "change-1", eventBranched, eventDeleted)
	if err != nil || got != nil || len(f.pages) != 1 || f.schemas != nil {
		t.Errorf("quiet: %v %v, %d pages, schemas %v", got, err, len(f.pages), f.schemas)
	}
	if _, err := f.reader(t).IntentEvents(t.Context(), "change-1", eventBranched, "not a time"); err == nil {
		t.Error("a bound that is not a time was accepted")
	}
	f = &fakeEvents{events: []map[string]any{mutated("infrahub.node.updated", "yesterday", "InterfacePhysical", "if-1", []string{"status"})}}
	_, err = f.reader(t).IntentEvents(t.Context(), "change-1", eventBranched, "")
	if err == nil || !strings.Contains(err.Error(), `"yesterday"`) || strings.Contains(err.Error(), "secret-token") {
		t.Errorf("a stamp that is not a time: %v", err)
	}
}
