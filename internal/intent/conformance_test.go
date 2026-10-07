package intent_test

import (
	"crypto/md5"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"slices"
	"strings"
	"sync"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
)

// fakeInfrahub answers the three endpoints a read touches — the schema endpoint, GraphQL
// and the object store — in the shapes Infrahub 1.11.2 answers them,
// from a CTM. It is tier 1's stand-in for a branch: what the retired tier-2 conformance
// proofs showed of a bare branch, and every artifact refusal of the read, is produced here by the code under test, against a schema and a listing no live branch
// can be made to hold.
//
// Nothing here is Fylgja's own code: the fake speaks Infrahub's wire format, so a change
// to how the read asks is caught as a request the fake cannot answer.
type fakeInfrahub struct {
	t      *testing.T
	branch string

	mu sync.Mutex
	// schema is the /api/schema document.
	schema schemaDoc
	// devices and links are served over GraphQL; the device list order is Infrahub's.
	devices []ctm.Device
	links   []ctm.Link
	// artifacts lists each device's artifacts by device name; a device absent from the
	// map lists none.
	artifacts map[string][]fakeArtifact
	// objects serves the object store, by storage id.
	objects map[string]fakeObject
	// requests counts each path served.
	requests map[string]int
	// served lists every request in order, with the `at` it carried, so a pinned read
	// can be shown to have asked for nothing but the branch as of at.
	served []fakeRequest
}

// fakeRequest is one request as the fake saw it: the path, the GraphQL operation when it
// was one, and the `at` query parameter, decoded, with whether it was sent at all.
type fakeRequest struct {
	Path, Operation, At string
	HasAt               bool
}

type schemaDoc struct {
	Main     string          `json:"main"`
	Generics []schemaGeneric `json:"generics"`
	Nodes    []schemaNode    `json:"nodes"`
}

type schemaGeneric struct {
	Kind   string   `json:"kind"`
	UsedBy []string `json:"used_by"`
}

type schemaNode struct {
	Kind string `json:"kind"`
}

// fakeArtifact is one CoreArtifact as the device query lists it.
type fakeArtifact struct {
	Name, Status, ContentType, Checksum, StorageID, DefinitionName string
}

// fakeObject is what the object store answers for one storage id.
type fakeObject struct {
	Status int
	Body   []byte
}

// conformingSchema is the reference schema's answer as it stands on main since M5: each
// generic implemented by its reference kind, the device kind an artifact target, and the
// contract node defined.
func conformingSchema() schemaDoc {
	return schemaDoc{
		Main: "fake-schema-hash",
		Generics: []schemaGeneric{
			{Kind: ctm.DeviceGeneric, UsedBy: []string{"NetworkDevice"}},
			{Kind: "FylgjaInterface", UsedBy: []string{"NetworkInterface"}},
			{Kind: "FylgjaLink", UsedBy: []string{"NetworkLink"}},
			{Kind: "FylgjaPlatform", UsedBy: []string{"NetworkPlatform"}},
			{Kind: ctm.ArtifactTargetGeneric, UsedBy: []string{"NetworkDevice"}},
		},
		Nodes: []schemaNode{{Kind: ctm.ContractKind}, {Kind: "NetworkDevice"}},
	}
}

// generic returns the named generic's row, adding an empty one if absent.
func (s *schemaDoc) generic(kind string) *schemaGeneric {
	for i := range s.Generics {
		if s.Generics[i].Kind == kind {
			return &s.Generics[i]
		}
	}
	s.Generics = append(s.Generics, schemaGeneric{Kind: kind})
	return &s.Generics[len(s.Generics)-1]
}

// repoRoot finds the module root from this file's location.
func repoRoot(t *testing.T) string {
	t.Helper()
	_, file, _, _ := runtime.Caller(0)
	return filepath.Join(filepath.Dir(file), "..", "..")
}

// newFakeInfrahub serves the fixture CTM (testdata/ctm/three-node.json) as branch
// fylgja-fixture: its devices, links and each device's artifact, Ready, with the object
// store holding the exact bytes. A read against it unchanged is clean.
func newFakeInfrahub(t *testing.T) *fakeInfrahub {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join(repoRoot(t), "testdata", "ctm", "three-node.json"))
	if err != nil {
		t.Fatal(err)
	}
	var fixture ctm.CTM
	if err := json.Unmarshal(raw, &fixture); err != nil {
		t.Fatal(err)
	}
	f := &fakeInfrahub{
		t:         t,
		branch:    fixture.Envelope.Branch,
		schema:    conformingSchema(),
		links:     fixture.Links,
		artifacts: map[string][]fakeArtifact{},
		objects:   map[string]fakeObject{},
		requests:  map[string]int{},
	}
	for _, d := range fixture.Devices {
		a := d.Artifact
		d.Artifact = nil
		f.devices = append(f.devices, d)
		id := "storage-" + d.Name
		f.artifacts[d.Name] = []fakeArtifact{{
			Name: a.Name, Status: intent.StatusReady, ContentType: a.ContentType,
			Checksum: a.Checksum, StorageID: id, DefinitionName: a.Name,
		}}
		f.objects[id] = fakeObject{Status: http.StatusOK, Body: []byte(a.Content)}
	}
	return f
}

// start serves the fake and points the process environment at it, as the operator's
// shell would.
func (f *fakeInfrahub) start(token string) *httptest.Server {
	srv := httptest.NewServer(http.HandlerFunc(f.serve))
	f.t.Cleanup(srv.Close)
	f.t.Setenv(intent.EnvAddress, srv.URL)
	f.t.Setenv(intent.EnvToken, token)
	return srv
}

// setContent replaces a device's artifact bytes in the object store and makes the
// listing's checksum theirs, so the change is one Infrahub itself could have made.
func (f *fakeInfrahub) setContent(device string, body []byte) {
	f.mu.Lock()
	defer f.mu.Unlock()
	a := &f.artifacts[device][0]
	a.Checksum = md5Hex(body)
	f.objects[a.StorageID] = fakeObject{Status: http.StatusOK, Body: body}
}

func (f *fakeInfrahub) count(path string) int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.requests[path]
}

func md5Hex(b []byte) string {
	sum := md5.Sum(b) //nolint:gosec // Infrahub's own checksum algorithm
	return hex.EncodeToString(sum[:])
}

func (f *fakeInfrahub) serve(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.requests[r.URL.Path]++
	at, hasAt := r.URL.Query()["at"]
	seen := fakeRequest{Path: r.URL.Path, HasAt: hasAt}
	if hasAt {
		seen.At = strings.Join(at, ",")
	}
	f.served = append(f.served, seen)

	switch {
	case r.Method == http.MethodGet && r.URL.Path == "/api/schema":
		writeJSON(w, http.StatusOK, f.schema)
	case r.Method == http.MethodGet && strings.HasPrefix(r.URL.Path, "/api/storage/object/"):
		obj, ok := f.objects[strings.TrimPrefix(r.URL.Path, "/api/storage/object/")]
		if !ok {
			writeJSON(w, http.StatusNotFound, storageNotFound(strings.TrimPrefix(r.URL.Path, "/api/storage/object/")))
			return
		}
		w.WriteHeader(obj.Status)
		_, _ = w.Write(obj.Body)
	case r.Method == http.MethodPost && r.URL.Path == "/graphql/"+f.branch:
		var req struct {
			OperationName string `json:"operationName"`
		}
		body, _ := io.ReadAll(r.Body)
		if err := json.Unmarshal(body, &req); err != nil {
			f.t.Errorf("GraphQL request is not JSON: %v", err)
		}
		f.served[len(f.served)-1].Operation = req.OperationName
		switch req.OperationName {
		case "ContractVersion":
			writeJSON(w, http.StatusOK, map[string]any{"data": map[string]any{"FylgjaContract": map[string]any{
				"edges": []any{map[string]any{"node": map[string]any{"version": value(ctm.ContractVersion)}}},
			}}})
		case "Devices":
			writeJSON(w, http.StatusOK, map[string]any{"data": map[string]any{"FylgjaDevice": f.devicePage()}})
		case "Links":
			writeJSON(w, http.StatusOK, map[string]any{"data": map[string]any{"FylgjaLink": f.linkPage()}})
		default:
			f.t.Errorf("the read sent GraphQL operation %q, which the fake does not know", req.OperationName)
			http.Error(w, "unknown operation", http.StatusTeapot)
		}
	default:
		f.t.Errorf("the read sent %s %s, which the fake does not serve", r.Method, r.URL.Path)
		http.Error(w, "unexpected", http.StatusTeapot)
	}
}

// storageNotFound is Infrahub 1.11.2's 404 body for a storage id it does not hold
// (verified live).
func storageNotFound(id string) map[string]any {
	return map[string]any{"errors": []map[string]string{{
		"message": "Unable to find the node " + id + " / StorageObject in the database.",
	}}}
}

func writeJSON(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}

func value(v any) map[string]any { return map[string]any{"value": v} }

func edges(nodes []any) map[string]any {
	out := make([]any, 0, len(nodes))
	for _, n := range nodes {
		out = append(out, map[string]any{"node": n})
	}
	return map[string]any{"edges": out}
}

// devicePage is one page holding every device, each as the reference kind NetworkDevice.
func (f *fakeInfrahub) devicePage() map[string]any {
	nodes := make([]any, 0, len(f.devices))
	for _, d := range f.devices {
		ifaces := make([]any, 0, len(d.Interfaces))
		for _, in := range d.Interfaces {
			var link any
			if in.Link != "" {
				link = map[string]any{"__typename": "NetworkLink", "id": in.Link}
			}
			var parent any
			if in.Parent != "" {
				parent = map[string]any{"__typename": "NetworkInterface", "name": value(in.Parent)}
			}
			enabled := in.Enabled == nil || *in.Enabled
			ifaces = append(ifaces, map[string]any{
				"__typename": "NetworkInterface",
				"id":         d.Name + ":" + in.Name,
				"name":       value(in.Name),
				"iftype":     value(in.Iftype),
				"mgmt_only":  value(in.MgmtOnly),
				"enabled":    value(enabled),
				"parent":     map[string]any{"node": parent},
				"addresses":  edges(nil),
				"link":       map[string]any{"node": link},
			})
		}
		arts := make([]any, 0)
		for _, a := range f.artifacts[d.Name] {
			arts = append(arts, map[string]any{
				"name":         value(a.Name),
				"status":       value(a.Status),
				"content_type": value(a.ContentType),
				"checksum":     value(a.Checksum),
				"storage_id":   value(a.StorageID),
				"definition":   map[string]any{"node": map[string]any{"artifact_name": value(a.DefinitionName)}},
			})
		}
		nodes = append(nodes, map[string]any{
			"__typename": "NetworkDevice",
			"id":         "id-" + d.Name,
			"name":       value(d.Name),
			"role":       value(d.Role),
			"site":       value(d.Site),
			"platform": map[string]any{"node": map[string]any{
				"__typename": "NetworkPlatform",
				"vendor":     value(d.Platform.Vendor),
				"nos":        value(d.Platform.NOS),
				"version":    value(d.Platform.Version),
				"model":      value(d.Platform.Model),
			}},
			"interfaces": edges(ifaces),
			"artifacts":  edges(arts),
		})
	}
	page := edges(nodes)
	page["count"] = len(nodes)
	return page
}

func (f *fakeInfrahub) linkPage() map[string]any {
	nodes := make([]any, 0, len(f.links))
	for _, l := range f.links {
		eps := make([]any, 0, len(l.Endpoints))
		for _, e := range l.Endpoints {
			eps = append(eps, map[string]any{
				"__typename": "NetworkInterface",
				"name":       value(e.Interface),
				"device": map[string]any{"node": map[string]any{
					"__typename": "NetworkDevice", "name": value(e.Device),
				}},
			})
		}
		nodes = append(nodes, map[string]any{"__typename": "NetworkLink", "id": l.ID, "endpoints": edges(eps)})
	}
	page := edges(nodes)
	page["count"] = len(nodes)
	return page
}

// checkConformance runs the check against the fake the way `schema check` and every read
// run it.
func checkConformance(t *testing.T, f *fakeInfrahub) (*intent.Conformance, findings.List) {
	t.Helper()
	f.start("sentinel-token")
	cfg, err := intent.FromEnv(f.branch, "")
	if err != nil {
		t.Fatal(err)
	}
	conf, list, err := intent.New(cfg).CheckConformance(t.Context())
	if err != nil {
		t.Fatalf("checking conformance: %v", err)
	}
	return conf, list
}

func ruleCounts(list findings.List) map[string]int {
	out := map[string]int{}
	for _, f := range list {
		out[f.Rule]++
	}
	return out
}

// What TestBranchWithoutTheSchemaNamesEveryGeneric proved against a bare branch, which no
// live branch can be since the schema went on main: the generics defined
// with nothing implementing them and no contract kind give contract.node.missing once,
// naming the branch, and every required generic named unimplemented — all in one pass,
// because there is no rival contract to misread.
func TestConformanceBareBranchNamesEveryGeneric(t *testing.T) {
	f := newFakeInfrahub(t)
	f.schema = schemaDoc{Main: "bare"}
	for _, g := range ctm.RequiredGenerics {
		f.schema.generic(g)
	}

	_, list := checkConformance(t, f)

	n := ruleCounts(list)
	if n[findings.RuleContractNodeMissing] != 1 {
		t.Errorf("%d %s findings, want exactly one: %v", n[findings.RuleContractNodeMissing], findings.RuleContractNodeMissing, list)
	}
	named := map[string]bool{}
	for _, fd := range list {
		switch fd.Rule {
		case findings.RuleContractNodeMissing:
			if fd.Object != f.branch {
				t.Errorf("%s names %q, want the branch %q", fd.Rule, fd.Object, f.branch)
			}
		case findings.RuleGenericUnimplemented:
			named[fd.Object] = true
		default:
			t.Errorf("unexpected finding %s: %s", fd.Rule, fd.Message)
		}
	}
	for _, g := range ctm.RequiredGenerics {
		if !named[g] {
			t.Errorf("generic %s was not named unimplemented; named %v", g, named)
		}
	}
	if len(named) != len(ctm.RequiredGenerics) || n[findings.RuleGenericUnimplemented] != len(ctm.RequiredGenerics) {
		t.Errorf("%d generics named, want %d: %v", n[findings.RuleGenericUnimplemented], len(ctm.RequiredGenerics), list)
	}
	if f.count("/graphql/"+f.branch) != 0 {
		t.Error("the check queried GraphQL on a branch that declares no contract kind")
	}
}

// What TestUnimplementedGenericsAreNamed proved: with the contract in place, a generic
// nothing implements is named, and only that one.
func TestConformanceNamesTheUnimplementedGeneric(t *testing.T) {
	f := newFakeInfrahub(t)
	f.schema.generic("FylgjaLink").UsedBy = nil

	_, list := checkConformance(t, f)

	if len(list) != 1 || list[0].Rule != findings.RuleGenericUnimplemented || list[0].Object != "FylgjaLink" {
		t.Fatalf("findings %v, want one %s naming FylgjaLink", list, findings.RuleGenericUnimplemented)
	}
	if list[0].Severity != findings.Rejection {
		t.Errorf("severity %s, want rejection", list[0].Severity)
	}
}

// Contract 0.2: a kind implementing FylgjaDevice that does not inherit
// CoreArtifactTarget is named, before any data is read, as the one thing to fix — and a
// kind that does is not. CoreArtifactTarget's own other implementers are no concern.
func TestConformanceNamesADeviceKindThatIsNoArtifactTarget(t *testing.T) {
	f := newFakeInfrahub(t)
	f.schema.generic(ctm.DeviceGeneric).UsedBy = []string{"NetworkDeviceBare", "NetworkDevice"}
	f.schema.generic(ctm.ArtifactTargetGeneric).UsedBy = []string{"NetworkDevice", "SomeoneElsesKind"}

	conf, list := checkConformance(t, f)

	want := findings.Finding{
		Severity: findings.Rejection,
		Rule:     findings.RuleSchemaArtifactTargetMissing,
		Object:   "NetworkDeviceBare",
		Message: "kind NetworkDeviceBare implements FylgjaDevice but does not inherit CoreArtifactTarget, " +
			"so its devices can carry no configuration artifact",
	}
	if len(list) != 1 || list[0] != want {
		t.Fatalf("findings %+v, want exactly %+v", list, want)
	}
	if f.count("/graphql/"+f.branch) != 1 {
		t.Errorf("GraphQL was asked %d times; want the contract version alone, before any data is read", f.count("/graphql/"+f.branch))
	}
	last := conf.Generics[len(conf.Generics)-1]
	if last.Generic != ctm.ArtifactTargetGeneric || !slices.Equal(last.Kinds, []string{"NetworkDevice", "SomeoneElsesKind"}) {
		t.Errorf("last row %+v, want %s with its implementers sorted", last, ctm.ArtifactTargetGeneric)
	}
}

// A conforming schema with the target produces neither finding, and the verified block
// lists each required generic in order, then CoreArtifactTarget (contracts/cli.md).
func TestConformanceConformingSchema(t *testing.T) {
	f := newFakeInfrahub(t)

	conf, list := checkConformance(t, f)

	if len(list) != 0 {
		t.Fatalf("a conforming schema gave findings: %v", list)
	}
	if conf.Version != ctm.ContractVersion || conf.SchemaHash != "fake-schema-hash" {
		t.Errorf("version %q hash %q, want %q and the schema's hash", conf.Version, conf.SchemaHash, ctm.ContractVersion)
	}
	var rows []string
	for _, g := range conf.Generics {
		rows = append(rows, g.Generic)
		if len(g.Kinds) == 0 {
			t.Errorf("row %s names no kind", g.Generic)
		}
	}
	if want := append(slices.Clone(ctm.RequiredGenerics), ctm.ArtifactTargetGeneric); !slices.Equal(rows, want) {
		t.Errorf("rows %v, want %v", rows, want)
	}
}
