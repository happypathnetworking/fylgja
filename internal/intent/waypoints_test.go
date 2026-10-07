package intent

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"math/rand"
	"net/http"
	"net/http/httptest"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"
)

// fakeWaypoints is an Infrahub holding the waypoint kind (or not) and some waypoints,
// answering the two unnamed endpoints the reader uses and recording what it was asked.
type fakeWaypoints struct {
	// attributes is the kind's attributes on the schema endpoint; nil means the kind is
	// absent from the default branch's schema.
	attributes []string
	nodes      []map[string]any

	mu       sync.Mutex
	requests []*http.Request
	offsets  []int
}

func (f *fakeWaypoints) serve(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	f.requests = append(f.requests, r.Clone(context.Background()))
	f.mu.Unlock()
	switch {
	case r.Method == http.MethodGet && r.URL.Path == "/api/schema":
		nodes := []map[string]any{{"kind": "NetworkDevice", "attributes": []map[string]any{{"name": "name"}}}}
		if f.attributes != nil {
			var attrs []map[string]any
			for _, a := range f.attributes {
				attrs = append(attrs, map[string]any{"name": a})
			}
			nodes = append(nodes, map[string]any{"kind": WaypointKind, "branch": "agnostic", "attributes": attrs})
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"main": "fe9eca98", "nodes": nodes})
	case r.Method == http.MethodPost && r.URL.Path == "/graphql":
		var req struct {
			Variables struct {
				Limit, Offset int
			} `json:"variables"`
		}
		_ = json.NewDecoder(r.Body).Decode(&req)
		f.mu.Lock()
		f.offsets = append(f.offsets, req.Variables.Offset)
		f.mu.Unlock()
		end := min(req.Variables.Offset+req.Variables.Limit, len(f.nodes))
		var edges []map[string]any
		for _, n := range f.nodes[min(req.Variables.Offset, len(f.nodes)):end] {
			edges = append(edges, map[string]any{"node": n})
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"data": map[string]any{
			"FylgjaWaypoint": map[string]any{"count": len(f.nodes), "edges": edges},
		}})
	default:
		http.NotFound(w, r)
	}
}

func (f *fakeWaypoints) reader(t *testing.T) (*WaypointReader, *httptest.Server) {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(f.serve))
	t.Cleanup(srv.Close)
	return NewWaypointReader(srv.URL, "sentinel-token"), srv
}

// waypointNode is one waypoint as Infrahub's GraphQL answers it; at "" is an unwritten
// as_of, which Infrahub answers as null.
func waypointNode(id, series string, sequence int, branch, writtenAt, at, description string) map[string]any {
	var asOf any
	if at != "" {
		asOf = at
	}
	return map[string]any{
		"id":          id,
		"series":      map[string]any{"value": series},
		"sequence":    map[string]any{"value": sequence},
		"branch":      map[string]any{"value": branch, "updated_at": writtenAt},
		"as_of":       map[string]any{"value": asOf},
		"description": map[string]any{"value": description},
	}
}

func ctx10s(t *testing.T) context.Context {
	t.Helper()
	ctx, cancel := context.WithTimeout(t.Context(), 10*time.Second)
	t.Cleanup(cancel)
	return ctx
}

// The kind's presence and shape are read from the schema endpoint before any query, and
// what is missing is named: the kind, or each attribute this build reads that it lacks,
// in WaypointFields' order.
func TestWaypointReaderChecksTheKind(t *testing.T) {
	for _, tc := range []struct {
		name       string
		attributes []string
		missing    []string // nil: present
		absent     bool
		message    string
	}{
		{name: "present", attributes: []string{"description", "as_of", "branch", "sequence", "series"}},
		{name: "absent", absent: true, message: "the default branch's schema has no kind FylgjaWaypoint"},
		{name: "as_of missing", attributes: []string{"series", "sequence", "branch", "description"},
			missing: []string{"as_of"}, message: "kind FylgjaWaypoint on the default branch lacks the attribute as_of, which this build reads"},
		{name: "two missing", attributes: []string{"branch", "description", "sequence"},
			missing: []string{"series", "as_of"}, message: "kind FylgjaWaypoint on the default branch lacks the attributes series, as_of, which this build reads"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			f := &fakeWaypoints{attributes: tc.attributes}
			r, _ := f.reader(t)
			err := r.Check(ctx10s(t))
			if !tc.absent && tc.missing == nil {
				if err != nil {
					t.Fatalf("a kind with every attribute: %v", err)
				}
				return
			}
			var kindErr *WaypointKindError
			if !errors.As(err, &kindErr) {
				t.Fatalf("want a *WaypointKindError, got %v", err)
			}
			if !slices.Equal(kindErr.Missing, tc.missing) {
				t.Errorf("Missing = %v, want %v", kindErr.Missing, tc.missing)
			}
			if err.Error() != tc.message {
				t.Errorf("message = %q, want %q", err, tc.message)
			}
		})
	}
}

// Every page is read and the rows come back sorted by series then sequence, whatever
// order the server answered in.
func TestWaypointReaderListsEveryPageSorted(t *testing.T) {
	var nodes []map[string]any
	for i := range 101 {
		series := []string{"beta", "alpha", "fylgja-test-wp-7"}[i%3]
		nodes = append(nodes, waypointNode(fmt.Sprintf("id-%03d", i), series, i+1, "main",
			"2026-09-28T16:04:52.482130+00:00", "", ""))
	}
	rand.New(rand.NewSource(7)).Shuffle(len(nodes), func(i, j int) { nodes[i], nodes[j] = nodes[j], nodes[i] })
	f := &fakeWaypoints{nodes: nodes}
	r, _ := f.reader(t)

	got, err := r.List(ctx10s(t))
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 101 {
		t.Fatalf("got %d waypoints from two pages, want 101", len(got))
	}
	if !slices.Equal(f.offsets, []int{0, pageSize}) {
		t.Errorf("pages requested at offsets %v, want [0 %d]", f.offsets, pageSize)
	}
	sorted := slices.IsSortedFunc(got, func(a, b Waypoint) int {
		if a.Series != b.Series {
			return strings.Compare(a.Series, b.Series)
		}
		return a.Sequence - b.Sequence
	})
	if !sorted {
		t.Errorf("rows are not sorted by series then sequence: first %s/%d, last %s/%d",
			got[0].Series, got[0].Sequence, got[100].Series, got[100].Sequence)
	}
}

// A written as_of and branch.updated_at are kept character for character, and an
// unwritten as_of is nil (Constitution VI).
func TestWaypointReaderKeepsValuesVerbatim(t *testing.T) {
	f := &fakeWaypoints{nodes: []map[string]any{
		waypointNode("id-1", "demo", 1, "main", "2026-09-28T16:04:52.482130+00:00", "", "before the change"),
		waypointNode("id-2", "demo", 2, "change-1", "2026-09-28T16:05:35.970325+00:00", "2026-09-20T10:00:00.5+02:00", ""),
	}}
	r, _ := f.reader(t)
	got, err := r.List(ctx10s(t))
	if err != nil {
		t.Fatal(err)
	}
	want := []Waypoint{
		{ID: "id-1", Series: "demo", Sequence: 1, Branch: "main", BranchWrittenAt: "2026-09-28T16:04:52.482130+00:00", Description: "before the change"},
		{ID: "id-2", Series: "demo", Sequence: 2, Branch: "change-1", BranchWrittenAt: "2026-09-28T16:05:35.970325+00:00", At: ptr("2026-09-20T10:00:00.5+02:00")},
	}
	for i := range want {
		g, w := got[i], want[i]
		if (g.At == nil) != (w.At == nil) || (g.At != nil && *g.At != *w.At) {
			t.Errorf("row %d At = %v, want %v", i, deref(g.At), deref(w.At))
		}
		g.At, w.At = nil, nil
		if g != w {
			t.Errorf("row %d = %+v, want %+v", i, g, w)
		}
	}
}

// The reader names no branch: the schema endpoint and GraphQL are asked on their unnamed
// paths, with no query string, so the default branch answers whatever it is called.
// The credential goes in the header, as a branch read's does.
func TestWaypointReaderNamesNoBranch(t *testing.T) {
	f := &fakeWaypoints{attributes: WaypointFields,
		nodes: []map[string]any{waypointNode("id-1", "demo", 1, "main", "2026-09-28T16:04:52.482130+00:00", "", "")}}
	r, _ := f.reader(t)
	if err := r.Check(ctx10s(t)); err != nil {
		t.Fatal(err)
	}
	if _, err := r.List(ctx10s(t)); err != nil {
		t.Fatal(err)
	}
	var paths []string
	for _, req := range f.requests {
		paths = append(paths, req.Method+" "+req.URL.Path)
		if req.URL.RawQuery != "" {
			t.Errorf("%s %s carries a query string %q; the reader names no branch and no at", req.Method, req.URL.Path, req.URL.RawQuery)
		}
		if req.Header.Get("X-INFRAHUB-KEY") != "sentinel-token" {
			t.Errorf("%s %s was sent without the credential", req.Method, req.URL.Path)
		}
	}
	if !slices.Equal(paths, []string{"GET /api/schema", "POST /graphql"}) {
		t.Errorf("requests = %v, want exactly GET /api/schema then POST /graphql", paths)
	}
}

// An unreachable Infrahub, a refused credential and a non-200 are errors that carry no
// credential, even from a server that quotes the request's own header back (M1's
// echoing-server shape). A refused credential names the variable to fix.
func TestWaypointReaderKeepsTheCredentialOut(t *testing.T) {
	echo := func(status int) string {
		srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(status)
			_, _ = w.Write([]byte(`{"errors":["rejected key ` + r.Header.Get("X-INFRAHUB-KEY") + `"]}`))
		}))
		t.Cleanup(srv.Close)
		return srv.URL
	}
	closed := httptest.NewServer(http.NotFoundHandler())
	closed.Close()

	for _, tc := range []struct {
		name    string
		address string
		want    string
	}{
		{"401", echo(http.StatusUnauthorized), EnvToken},
		{"403", echo(http.StatusForbidden), EnvToken},
		{"500 quoting the key", echo(http.StatusInternalServerError), "<redacted>"},
		{"unreachable", closed.URL, "(the default branch)"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			r := NewWaypointReader(tc.address, "sentinel-token")
			_, listErr := r.List(ctx10s(t))
			for what, err := range map[string]error{"Check": r.Check(ctx10s(t)), "List": listErr} {
				if err == nil {
					t.Fatalf("%s: want an error", what)
				}
				var kindErr *WaypointKindError
				if errors.As(err, &kindErr) {
					t.Errorf("%s: a transport failure reported as the kind's absence: %v", what, err)
				}
				if strings.Contains(err.Error(), "sentinel-token") {
					t.Errorf("%s: the credential reached the error: %v", what, err)
				}
				if !strings.Contains(err.Error(), tc.want) {
					t.Errorf("%s: error %q does not carry %q", what, err, tc.want)
				}
			}
		})
	}
}

// The reader is built from the variables a branch read uses, and refuses alike when one
// is unset.
func TestWaypointReaderFromEnv(t *testing.T) {
	t.Setenv(EnvAddress, "")
	t.Setenv(EnvToken, "t")
	if _, err := WaypointReaderFromEnv(); err == nil || err.Error() != EnvAddress+" is not set" {
		t.Errorf("address unset: %v", err)
	}
	t.Setenv(EnvAddress, "http://infrahub.invalid/")
	t.Setenv(EnvToken, "")
	if _, err := WaypointReaderFromEnv(); err == nil || err.Error() != EnvToken+" is not set" {
		t.Errorf("token unset: %v", err)
	}
	t.Setenv(EnvToken, "t")
	r, err := WaypointReaderFromEnv()
	if err != nil {
		t.Fatal(err)
	}
	if r.address != "http://infrahub.invalid" {
		t.Errorf("address = %q, want the trailing slash trimmed", r.address)
	}
}

func ptr(s string) *string { return &s }

func deref(s *string) string {
	if s == nil {
		return "<nil>"
	}
	return *s
}
