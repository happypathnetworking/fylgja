package cli

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/intent"
)

// fakeInfrahub answers what a command given --waypoint asks of Infrahub, in the shapes
// Infrahub 1.11.2 answers them: the default branch's schema and its waypoints on the
// unnamed endpoints, and the fixture branch's read — its schema,
// GraphQL and the object store — from testdata/ctm/three-node.json, with the fixture's
// schema hash, so a read of it at the fixture's at is the fixture itself; and any other
// branch a test gives it, read the same way from a CTM of the test's. The branch half
// is internal/intent's fake (conformance_test.go) and the waypoint half its
// waypoints_test.go's, which this package cannot import; like them it speaks Infrahub's
// wire format, so a change to how a command asks is caught as a request it cannot answer.
type fakeInfrahub struct {
	t       *testing.T
	fixture ctm.CTM
	// kind is the waypoint kind's attributes on the default branch's schema; nil is the
	// kind absent.
	kind []string
	// defaultStatus, when set, is how the default branch's schema answers instead: an
	// Infrahub that stopped answering there.
	defaultStatus int
	// waypoints are served on the unnamed GraphQL endpoint, as Infrahub answers them.
	waypoints []map[string]any
	// branches are read beside the fixture's, each its own CTM under its own name, with
	// the fixture's schema hash; a device's artifact is served from its branch's CTM, by
	// the branch and the device's name (M11: a step's target renders artifacts of its own).
	branches map[string]*ctm.CTM
	// contractless names branches whose contract node is absent: the read refuses them
	// as contract.node.missing.
	contractless map[string]bool

	mu     sync.Mutex
	served []fakeRequest
}

// fakeRequest is one request as the fake saw it.
type fakeRequest struct {
	Method, Path, Query, Operation string
}

// newFakeInfrahub serves the fixture branch and the waypoint kind with every attribute,
// holding no waypoint.
func newFakeInfrahub(t *testing.T) *fakeInfrahub {
	t.Helper()
	raw, err := os.ReadFile(repoPath("testdata", "ctm", "three-node.json"))
	if err != nil {
		t.Fatal(err)
	}
	f := &fakeInfrahub{t: t, kind: intent.WaypointFields}
	if err := json.Unmarshal(raw, &f.fixture); err != nil {
		t.Fatal(err)
	}
	return f
}

// fakeToken is the credential the fake's callers are given: a sentinel no output may
// carry (Constitution X).
const fakeToken = "sentinel-waypoint-token"

// start serves the fake and points the process environment at it, as the operator's shell
// would.
func (f *fakeInfrahub) start() *httptest.Server {
	srv := httptest.NewServer(http.HandlerFunc(f.serve))
	f.t.Cleanup(srv.Close)
	f.t.Setenv(intent.EnvAddress, srv.URL)
	f.t.Setenv(intent.EnvToken, fakeToken)
	return srv
}

// waypoint adds one waypoint as Infrahub's GraphQL answers it: at "" is an unwritten
// as_of, which Infrahub answers as null, and writtenAt "" a null updated_at on its branch
// attribute, which no Infrahub was seen to answer and the resolution refuses.
func (f *fakeInfrahub) waypoint(id, series string, sequence int, branch, writtenAt, at, description string) {
	var asOf, updatedAt any
	if at != "" {
		asOf = at
	}
	if writtenAt != "" {
		updatedAt = writtenAt
	}
	f.waypoints = append(f.waypoints, map[string]any{
		"id":          id,
		"series":      map[string]any{"value": series},
		"sequence":    map[string]any{"value": sequence},
		"branch":      map[string]any{"value": branch, "updated_at": updatedAt},
		"as_of":       map[string]any{"value": asOf},
		"description": map[string]any{"value": description},
	})
}

// requests is every request served so far.
func (f *fakeInfrahub) requests() []fakeRequest {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]fakeRequest(nil), f.served...)
}

func (f *fakeInfrahub) serve(w http.ResponseWriter, r *http.Request) {
	seen := fakeRequest{Method: r.Method, Path: r.URL.Path, Query: r.URL.RawQuery}
	if r.Method == http.MethodPost {
		var req struct {
			OperationName string `json:"operationName"`
		}
		body, _ := io.ReadAll(r.Body)
		if err := json.Unmarshal(body, &req); err != nil {
			f.t.Errorf("GraphQL request is not JSON: %v", err)
		}
		seen.Operation = req.OperationName
	}
	f.mu.Lock()
	f.served = append(f.served, seen)
	f.mu.Unlock()

	switch {
	case r.Method == http.MethodGet && r.URL.Path == "/api/schema":
		// The default branch's schema carries the waypoint kind or not; a served branch's
		// is the contract's, and a waypoint is never read from it.
		q := r.URL.Query().Get("branch")
		switch _, known := f.branch(q); {
		case q == "" && f.defaultStatus != 0:
			writeFakeJSON(w, f.defaultStatus, map[string]any{"errors": []map[string]string{{"message": "the default branch is unwell"}}})
		case q == "":
			nodes := []map[string]any{{"kind": ctm.ContractKind}}
			if f.kind != nil {
				attrs := make([]map[string]any, 0, len(f.kind))
				for _, a := range f.kind {
					attrs = append(attrs, map[string]any{"name": a})
				}
				nodes = append(nodes, map[string]any{"kind": intent.WaypointKind, "branch": "agnostic", "attributes": attrs})
			}
			writeFakeJSON(w, http.StatusOK, map[string]any{"main": "fe9eca98", "nodes": nodes})
		case known:
			writeFakeJSON(w, http.StatusOK, f.branchSchema())
		default:
			writeFakeJSON(w, http.StatusBadRequest, map[string]any{"errors": []map[string]string{{"message": "Branch: " + q + " not found."}}})
		}
	case r.Method == http.MethodPost && r.URL.Path == "/graphql" && seen.Operation == "Waypoints":
		page := fakeEdges(f.waypoints)
		page["count"] = len(f.waypoints)
		writeFakeJSON(w, http.StatusOK, map[string]any{"data": map[string]any{"FylgjaWaypoint": page}})
	case r.Method == http.MethodPost && f.graphQLBranch(r.URL.Path) != nil:
		c := f.graphQLBranch(r.URL.Path)
		switch seen.Operation {
		case "ContractVersion":
			edges := []any{map[string]any{"node": map[string]any{"version": fakeValue(ctm.ContractVersion)}}}
			if f.contractless[strings.TrimPrefix(r.URL.Path, "/graphql/")] {
				edges = []any{}
			}
			writeFakeJSON(w, http.StatusOK, map[string]any{"data": map[string]any{"FylgjaContract": map[string]any{
				"edges": edges,
			}}})
		case "Devices":
			writeFakeJSON(w, http.StatusOK, map[string]any{"data": map[string]any{
				"FylgjaDevice": devicePage(strings.TrimPrefix(r.URL.Path, "/graphql/"), c)}})
		case "Links":
			writeFakeJSON(w, http.StatusOK, map[string]any{"data": map[string]any{"FylgjaLink": linkPage(c)}})
		default:
			f.t.Errorf("the read sent GraphQL operation %q on %s, which the fake does not know", seen.Operation, r.URL.Path)
			http.Error(w, "unknown operation", http.StatusTeapot)
		}
	case r.Method == http.MethodGet && strings.HasPrefix(r.URL.Path, "/api/storage/object/storage-"):
		branch, name, _ := strings.Cut(strings.TrimPrefix(r.URL.Path, "/api/storage/object/storage-"), "~")
		if c, ok := f.branch(branch); ok {
			for _, d := range c.Devices {
				if d.Name == name {
					_, _ = io.WriteString(w, d.Artifact.Content)
					return
				}
			}
		}
		http.NotFound(w, r)
	default:
		f.t.Errorf("a command sent %s %s, which the fake does not serve", r.Method, r.URL.Path)
		http.Error(w, "unexpected", http.StatusTeapot)
	}
}

// branch is the CTM a branch reads as: the fixture's under its own name, else one of
// branches.
func (f *fakeInfrahub) branch(name string) (*ctm.CTM, bool) {
	if name == f.fixture.Envelope.Branch {
		return &f.fixture, true
	}
	c, ok := f.branches[name]
	return c, ok
}

// graphQLBranch is the CTM a branch's GraphQL endpoint path reads, or nil for a path that
// names no branch the fake serves.
func (f *fakeInfrahub) graphQLBranch(path string) *ctm.CTM {
	name, ok := strings.CutPrefix(path, "/graphql/")
	if !ok {
		return nil
	}
	c, _ := f.branch(name)
	return c
}

// branchSchema is the reference schema as it stands on main since M5, with the fixture's
// schema hash: each generic implemented by its reference kind, the device kind an
// artifact target, and the contract node defined.
func (f *fakeInfrahub) branchSchema() map[string]any {
	generic := func(kind, usedBy string) map[string]any {
		return map[string]any{"kind": kind, "used_by": []string{usedBy}}
	}
	return map[string]any{
		"main": f.fixture.Envelope.SchemaHash,
		"generics": []any{
			generic(ctm.DeviceGeneric, "NetworkDevice"),
			generic("FylgjaInterface", "NetworkInterface"),
			generic("FylgjaLink", "NetworkLink"),
			generic("FylgjaPlatform", "NetworkPlatform"),
			generic(ctm.ArtifactTargetGeneric, "NetworkDevice"),
		},
		"nodes": []any{map[string]any{"kind": ctm.ContractKind}, map[string]any{"kind": "NetworkDevice"}},
	}
}

func writeFakeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func fakeValue(v any) map[string]any { return map[string]any{"value": v} }

func fakeEdges[T any](nodes []T) map[string]any {
	out := make([]any, 0, len(nodes))
	for _, n := range nodes {
		out = append(out, map[string]any{"node": n})
	}
	return map[string]any{"edges": out}
}

// devicePage is one page holding every device of c, read from branch, each as the
// reference kind NetworkDevice with its artifact Ready in the object store under the branch
// and its name.
func devicePage(branch string, c *ctm.CTM) map[string]any {
	nodes := make([]any, 0, len(c.Devices))
	for _, d := range c.Devices {
		ifaces := make([]any, 0, len(d.Interfaces))
		for _, in := range d.Interfaces {
			var link any
			if in.Link != "" {
				link = map[string]any{"__typename": "NetworkLink", "id": in.Link}
			}
			var parent any
			if in.Parent != "" {
				parent = map[string]any{"__typename": "NetworkInterface", "name": fakeValue(in.Parent)}
			}
			ifaces = append(ifaces, map[string]any{
				"__typename": "NetworkInterface",
				"id":         d.Name + ":" + in.Name,
				"name":       fakeValue(in.Name),
				"iftype":     fakeValue(in.Iftype),
				"mgmt_only":  fakeValue(in.MgmtOnly),
				"enabled":    fakeValue(in.Enabled == nil || *in.Enabled),
				"parent":     map[string]any{"node": parent},
				"addresses":  fakeEdges[any](nil),
				"link":       map[string]any{"node": link},
			})
		}
		a := d.Artifact
		nodes = append(nodes, map[string]any{
			"__typename": "NetworkDevice",
			"id":         "id-" + d.Name,
			"name":       fakeValue(d.Name),
			"role":       fakeValue(d.Role),
			"site":       fakeValue(d.Site),
			"platform": map[string]any{"node": map[string]any{
				"__typename": "NetworkPlatform",
				"vendor":     fakeValue(d.Platform.Vendor),
				"nos":        fakeValue(d.Platform.NOS),
				"version":    fakeValue(d.Platform.Version),
				"model":      fakeValue(d.Platform.Model),
			}},
			"interfaces": fakeEdges(ifaces),
			"artifacts": fakeEdges([]any{map[string]any{
				"name":         fakeValue(a.Name),
				"status":       fakeValue(intent.StatusReady),
				"content_type": fakeValue(a.ContentType),
				"checksum":     fakeValue(a.Checksum),
				"storage_id":   fakeValue("storage-" + branch + "~" + d.Name),
				"definition":   map[string]any{"node": map[string]any{"artifact_name": fakeValue(a.Name)}},
			}}),
		})
	}
	page := fakeEdges(nodes)
	page["count"] = len(nodes)
	return page
}

func linkPage(c *ctm.CTM) map[string]any {
	nodes := make([]any, 0, len(c.Links))
	for _, l := range c.Links {
		eps := make([]any, 0, len(l.Endpoints))
		for _, e := range l.Endpoints {
			eps = append(eps, map[string]any{
				"__typename": "NetworkInterface",
				"name":       fakeValue(e.Interface),
				"device": map[string]any{"node": map[string]any{
					"__typename": "NetworkDevice", "name": fakeValue(e.Device),
				}},
			})
		}
		nodes = append(nodes, map[string]any{"__typename": "NetworkLink", "id": l.ID, "endpoints": fakeEdges(eps)})
	}
	page := fakeEdges(nodes)
	page["count"] = len(nodes)
	return page
}
