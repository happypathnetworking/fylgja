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
// schema, the reference kinds implementing Fylgja's generics; it records what it was
// asked.
type fakeEvents struct {
	events []map[string]any

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
		generic := func(kind, usedBy string) map[string]any {
			return map[string]any{"kind": kind, "used_by": []string{usedBy}}
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"main": "e43a1cde", "generics": []any{
			generic("FylgjaDevice", "NetworkDevice"), generic("FylgjaInterface", "NetworkInterface"),
			generic("FylgjaLink", "NetworkLink"), generic("FylgjaPlatform", "NetworkPlatform"),
			generic("CoreGroup", "CoreGraphQLQueryGroup"), generic("CoreArtifactTarget", "NetworkDevice"),
		}, "nodes": []any{map[string]any{"kind": "NetworkDevice"}, map[string]any{"kind": StageKind}}})
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

// The log of research §8.18's branch, newest first: the regenerate's churn, the link's
// deletion with its child events, the generation's churn, the seed. Only a node's own
// write of a kind implementing Fylgja's generics is intent, at any level, and of an update
// only one changing a field the stamps fold into a device's intent: the query groups'
// memberships Infrahub rewrites on every device after each generation, a device's
// artifacts, an interface's addresses, a platform's model and the stage kind are not.
// Each names its primary node and every peer.
func TestIntentEventsMapsKinds(t *testing.T) {
	f := &fakeEvents{events: []map[string]any{
		mutated("infrahub.node.updated", "2026-10-17T13:55:32.691250+00:00", "NetworkDevice", "dev-n1", nil,
			rel{"member_of_groups", "g-1"}),
		other("ArtifactEvent", "infrahub.artifact.updated", "2026-10-17T13:55:29.770104+00:00", "CoreArtifact", "a-1"),
		mutated("infrahub.node.updated", "2026-10-17T13:55:29.617911+00:00", "CoreArtifact", "a-1", []string{"storage_id", "checksum"}),
		mutated("infrahub.node.updated", "2026-10-17T13:55:20.000000+00:00", "NetworkInterface", "if-n3", nil,
			rel{"addresses", "ip-1"}),
		mutated("infrahub.node.updated", "2026-10-17T13:55:19.000000+00:00", "NetworkPlatform", "p-1", []string{"model"}),
		mutated("infrahub.node.updated", "2026-10-17T13:55:18.000000+00:00", StageKind, "st-1", []string{"label"}),
		other("GroupEvent", "infrahub.group.member_removed", "2026-10-17T13:55:09.051000+00:00", "CoreGraphQLQueryGroup", "g-1"),
		mutated("infrahub.node.updated", "2026-10-17T13:55:09.049000+00:00", "CoreGraphQLQueryGroup", "g-1", nil,
			rel{"members", "link-1"}),
		mutated("infrahub.node.updated", "2026-10-17T13:55:09.044135+00:00", "NetworkInterface", "if-n2", nil,
			rel{"link", "link-1"}),
		mutated("infrahub.node.updated", "2026-10-17T13:55:09.042677+00:00", "NetworkInterface", "if-n1", nil,
			rel{"link", "link-1"}),
		mutated("infrahub.node.deleted", eventDeleted, "NetworkLink", "link-1", nil,
			rel{"endpoints", "if-n1"}, rel{"endpoints", "if-n2"}, rel{"member_of_groups", "g-1"}),
		mutated("infrahub.node.updated", "2026-10-17T13:54:27.731070+00:00", "NetworkDevice", "dev-n1", nil,
			rel{"member_of_groups", "g-1"}),
		mutated("infrahub.node.updated", "2026-10-17T13:54:22.418356+00:00", "NetworkDevice", "dev-n1", nil,
			rel{"artifacts", "a-1"}),
		mutated("infrahub.node.updated", "2026-10-17T13:54:20.000000+00:00", "NetworkDevice", "dev-n2", []string{"role"}),
		mutated("infrahub.node.updated", "2026-10-17T13:54:16.685919+00:00", "NetworkInterface", "if-n1", nil,
			rel{"link", "link-1"}),
		mutated("infrahub.node.created", "2026-10-17T13:54:16.683012+00:00", "NetworkLink", "link-1",
			[]string{"human_friendly_id", "display_label"}, rel{"endpoints", "if-n1"}, rel{"endpoints", "if-n2"}),
		mutated("infrahub.node.updated", "2026-10-17T13:54:15.360731+00:00", "NetworkDevice", "dev-n1", nil,
			rel{"interfaces", "if-n1"}),
		other("BranchCreatedEvent", "infrahub.branch.created", "2026-10-17T13:54:10.452400+00:00", "", ""),
	}}
	got, err := f.reader(t).IntentEvents(t.Context(), "change-1", eventBranched, "")
	if err != nil {
		t.Fatal(err)
	}
	want := []Event{
		{Name: "infrahub.node.updated", OccurredAt: "2026-10-17T13:55:09.044135+00:00", Kind: "NetworkInterface", Nodes: []string{"if-n2", "link-1"}},
		{Name: "infrahub.node.updated", OccurredAt: "2026-10-17T13:55:09.042677+00:00", Kind: "NetworkInterface", Nodes: []string{"if-n1", "link-1"}},
		{Name: "infrahub.node.deleted", OccurredAt: eventDeleted, Kind: "NetworkLink", Nodes: []string{"link-1", "if-n1", "if-n2", "g-1"}},
		{Name: "infrahub.node.updated", OccurredAt: "2026-10-17T13:54:20.000000+00:00", Kind: "NetworkDevice", Nodes: []string{"dev-n2"}},
		{Name: "infrahub.node.updated", OccurredAt: "2026-10-17T13:54:16.685919+00:00", Kind: "NetworkInterface", Nodes: []string{"if-n1", "link-1"}},
		{Name: "infrahub.node.created", OccurredAt: "2026-10-17T13:54:16.683012+00:00", Kind: "NetworkLink", Nodes: []string{"link-1", "if-n1", "if-n2"}},
		{Name: "infrahub.node.updated", OccurredAt: "2026-10-17T13:54:15.360731+00:00", Kind: "NetworkDevice", Nodes: []string{"dev-n1", "if-n1"}},
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("events\n  %+v\nwant\n  %+v", got, want)
	}
	if !got[2].Names([]string{"dev-n1", "if-n1"}) || got[2].Names([]string{"dev-n3", "if-n3"}) {
		t.Errorf("the delete names %v", got[2].Nodes)
	}
	if !reflect.DeepEqual(f.schemas, []string{"change-1"}) {
		t.Errorf("schema reads %v; want the branch's, once", f.schemas)
	}
	if len(f.pages) != 1 || f.pages[0]["branch"] != "change-1" || f.pages[0]["since"] != eventBranched ||
		f.pages[0]["limit"] != float64(eventPageSize) || f.pages[0]["offset"] != float64(0) {
		t.Errorf("pages %v", f.pages)
	}
}

// The pages stop at the first event no later than after, which none of the events
// returned is; an empty after reads every page, fifty at a time.
func TestIntentEventsPagesToTheBound(t *testing.T) {
	var events []map[string]any
	for i := range 120 {
		// Newest first: 13:55:59.000119 down to 13:55:59.000000.
		events = append(events, mutated("infrahub.node.updated", fmt.Sprintf("2026-10-17T13:55:59.%06d+00:00", 119-i),
			"NetworkInterface", fmt.Sprintf("if-%d", 119-i), []string{"enabled"}))
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
		mutated("infrahub.node.updated", "2026-10-17T13:54:00.000000+00:00", "NetworkInterface", "if-1", []string{"enabled"}),
	}}
	got, err := f.reader(t).IntentEvents(t.Context(), "change-1", eventBranched, eventDeleted)
	if err != nil || got != nil || len(f.pages) != 1 || f.schemas != nil {
		t.Errorf("quiet: %v %v, %d pages, schemas %v", got, err, len(f.pages), f.schemas)
	}
	if _, err := f.reader(t).IntentEvents(t.Context(), "change-1", eventBranched, "not a time"); err == nil {
		t.Error("a bound that is not a time was accepted")
	}
	f = &fakeEvents{events: []map[string]any{mutated("infrahub.node.updated", "yesterday", "NetworkInterface", "if-1", []string{"enabled"})}}
	_, err = f.reader(t).IntentEvents(t.Context(), "change-1", eventBranched, "")
	if err == nil || !strings.Contains(err.Error(), `"yesterday"`) || strings.Contains(err.Error(), "secret-token") {
		t.Errorf("a stamp that is not a time: %v", err)
	}
}
