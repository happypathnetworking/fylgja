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
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// fakeInfrahub answers the three endpoints a read touches — the schema endpoint, GraphQL
// and the object store — in the shapes Infrahub 1.11.2 answers them for a branch holding
// the schema library (017 research §1.6). It is tier 1's stand-in for a branch: every
// refusal and every omission of the read is produced here by the code under test, against
// a schema and a branch no live Infrahub need be made to hold.
//
// Nothing here is Fylgja's own code: the fake speaks Infrahub's wire format, so a change
// to how the read asks is caught as a request the fake cannot answer.
type fakeInfrahub struct {
	t      *testing.T
	branch string

	mu sync.Mutex
	// schema is the /api/schema document: the library's at the pinned commit as Infrahub
	// 1.11.2 loads it (testdata/schema-26336e9.json), which a test may mutate.
	schema map[string]any
	// devices are every DcimDevice on the branch, tagged or not, in Infrahub's order; the
	// Devices query answers those carrying the tag it asks for.
	devices []*fakeDevice
	// cables are every DcimCable on the branch, by id, each reached from its ports'
	// connector.
	cables map[string]*fakeCable
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
	// short, for a cable it names, is the count its connected_endpoints answers in place
	// of the ends it lists.
	short map[string]int
}

// fakeDevice is one DcimDevice: its tags, its platform's name and its manufacturer's (""
// for none, unless EmptyManufacturer serves a manufacturer whose name is empty), its
// physical ports, and the names of its InterfaceVirtuals, which no query of the read can
// reach.
type fakeDevice struct {
	ID, Name, Status       string
	Tags                   []string
	Platform, Manufacturer string
	EmptyManufacturer      bool
	Ports                  []*fakePort
	Virtual                []string
}

// fakePort is one InterfacePhysical: its role and status ("" null), and the id of the
// cable it is an end of ("" uncabled).
type fakePort struct {
	ID, Name, Role, Status, Cable string
}

// fakeCable is one DcimCable: its label ("" none) and its ends, each the id of a port, or
// an endpoint of another kind. Kind, when set, makes it a connector of that kind in place
// of a DcimCable, whose label the Ports query does not select.
type fakeCable struct {
	ID, Label, Kind string
	Ends            []fakeEnd
}

// fakeEnd is one end of a cable: a physical port by its id, or, when Kind is set, an
// endpoint of that kind, which has no name and no device.
type fakeEnd struct {
	Kind, ID string
}

// fakeRequest is one request as the fake saw it: the path, the GraphQL operation when it
// was one, its query text and variables, and the `at` query parameter, decoded, with
// whether it was sent at all.
type fakeRequest struct {
	Path, Operation, At string
	HasAt               bool
	Query               string
	Variables           map[string]any
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

// librarySchema is the schema endpoint's answer for a branch holding the library at the
// pinned commit, trimmed to the kinds the mapping reads (T033; research §5.2), decoded
// afresh so that a test's mutation is its own.
func librarySchema(t *testing.T) map[string]any {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join(repoRoot(t), "internal", "intent", "testdata", "schema-26336e9.json"))
	if err != nil {
		t.Fatal(err)
	}
	var doc map[string]any
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}
	return doc
}

// repoRoot finds the module root from this file's location.
func repoRoot(t *testing.T) string {
	t.Helper()
	_, file, _, _ := runtime.Caller(0)
	return filepath.Join(filepath.Dir(file), "..", "..")
}

// The fixture's scope, as the seed tags its devices (testsupport).
const fixtureTag = "fylgja"

// newFakeInfrahub serves the fixture CTM (testdata/ctm/three-node.json) as branch
// fylgja-fixture, in the library's kinds as the seed writes them: each device tagged
// fylgja on its package's platform and manufacturer, each port physical, the management
// port by its role, each link a cable labelled with its canonical id, and each device's
// artifact Ready, with the object store holding the exact bytes. A read against it
// unchanged is clean and equals the fixture but for the envelope's observed_at.
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
	pairs := packagePairs(t)
	f := &fakeInfrahub{
		t:         t,
		branch:    fixture.Envelope.Branch,
		schema:    librarySchema(t),
		cables:    map[string]*fakeCable{},
		artifacts: map[string][]fakeArtifact{},
		objects:   map[string]fakeObject{},
		requests:  map[string]int{},
	}
	for _, d := range fixture.Devices {
		pair, ok := pairs[d.Platform.Package]
		if !ok {
			t.Fatalf("no package %s to give device %s a platform", d.Platform.Package, d.Name)
		}
		dev := &fakeDevice{ID: "id-" + d.Name, Name: d.Name, Status: "active", Tags: []string{fixtureTag},
			Platform: pair.Platform, Manufacturer: pair.Manufacturer}
		for _, in := range d.Interfaces {
			p := &fakePort{ID: d.Name + ":" + in.Name, Name: in.Name}
			if in.MgmtOnly {
				p.Role = "management"
			}
			if in.Enabled != nil && !*in.Enabled {
				p.Status = "disabled"
			}
			dev.Ports = append(dev.Ports, p)
		}
		f.devices = append(f.devices, dev)

		a := d.Artifact
		id := "storage-" + d.Name
		f.artifacts[d.Name] = []fakeArtifact{{
			Name: a.Name, Status: intent.StatusReady, ContentType: a.ContentType,
			Checksum: a.Checksum, StorageID: id, DefinitionName: a.Name,
		}}
		f.objects[id] = fakeObject{Status: http.StatusOK, Body: []byte(a.Content)}
	}
	for i, l := range fixture.Links {
		ends := make([]string, 0, len(l.Endpoints))
		for _, e := range l.Endpoints {
			ends = append(ends, e.ID())
		}
		f.cable("cable-"+string(rune('a'+i)), l.ID, ends...)
	}
	return f
}

// packagePairs is each package's first manufacturer and platform pair, by its id: the
// shipped packages and every one under testdata/psp/ meant to load, so a fixture's device
// is served on the platform its package matches.
func packagePairs(t *testing.T) map[string]psp.Match {
	t.Helper()
	pkgs, err := psp.Embedded()
	if err != nil {
		t.Fatal(err)
	}
	for _, dir := range []string{"lossy", "heterogeneous"} {
		more, err := psp.FromDir(filepath.Join(repoRoot(t), "testdata", "psp", dir))
		if err != nil {
			t.Fatal(err)
		}
		pkgs = append(pkgs, more...)
	}
	out := map[string]psp.Match{}
	for _, p := range pkgs {
		out[p.Platform.ID] = p.Platform.Matches[0]
	}
	return out
}

// device is the fake's device of that name.
func (f *fakeInfrahub) device(name string) *fakeDevice {
	f.t.Helper()
	for _, d := range f.devices {
		if d.Name == name {
			return d
		}
	}
	f.t.Fatalf("the fake holds no device %s", name)
	return nil
}

// port is the fake's port by id, <device>:<port>, and its device.
func (f *fakeInfrahub) port(id string) (*fakeDevice, *fakePort) {
	for _, d := range f.devices {
		for _, p := range d.Ports {
			if p.ID == id {
				return d, p
			}
		}
	}
	return nil, nil
}

// addDevice adds a device carrying tags, on the pair given, with physical ports by name.
// It lists no artifact: a tagged one needs its own.
func (f *fakeInfrahub) addDevice(name, manufacturer, platform string, tags []string, ports ...string) *fakeDevice {
	d := &fakeDevice{ID: "id-" + name, Name: name, Status: "active", Tags: tags, Platform: platform, Manufacturer: manufacturer}
	for _, p := range ports {
		d.Ports = append(d.Ports, &fakePort{ID: name + ":" + p, Name: p})
	}
	f.devices = append(f.devices, d)
	return d
}

// cable adds a cable labelled label between ports given by id, <device>:<port>, and makes
// it each port's connector; an end given as <kind>#<id> is an endpoint of another kind.
func (f *fakeInfrahub) cable(id, label string, ends ...string) *fakeCable {
	f.t.Helper()
	c := &fakeCable{ID: id, Label: label}
	for _, e := range ends {
		if kind, other, ok := strings.Cut(e, "#"); ok {
			c.Ends = append(c.Ends, fakeEnd{Kind: kind, ID: other})
			continue
		}
		_, p := f.port(e)
		if p == nil {
			f.t.Fatalf("the fake holds no port %s", e)
		}
		p.Cable = id
		c.Ends = append(c.Ends, fakeEnd{ID: e})
	}
	f.cables[id] = c
	return c
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

// graphql is every GraphQL request the fake answered of an operation, in order.
func (f *fakeInfrahub) graphql(operation string) []fakeRequest {
	f.mu.Lock()
	defer f.mu.Unlock()
	var out []fakeRequest
	for _, r := range f.served {
		if r.Operation == operation {
			out = append(out, r)
		}
	}
	return out
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
			OperationName string         `json:"operationName"`
			Query         string         `json:"query"`
			Variables     map[string]any `json:"variables"`
		}
		body, _ := io.ReadAll(r.Body)
		if err := json.Unmarshal(body, &req); err != nil {
			f.t.Errorf("GraphQL request is not JSON: %v", err)
		}
		last := &f.served[len(f.served)-1]
		last.Operation, last.Query, last.Variables = req.OperationName, req.Query, req.Variables
		limit, offset := pageOf(req.Variables)
		switch req.OperationName {
		case "Devices":
			tag, _ := req.Variables["tag"].(string)
			writeJSON(w, http.StatusOK, map[string]any{"data": map[string]any{"DcimDevice": f.devicePage(tag, limit, offset)}})
		case "Ports":
			ids, _ := req.Variables["devices"].([]any)
			writeJSON(w, http.StatusOK, map[string]any{"data": map[string]any{"InterfacePhysical": f.portPage(ids, limit, offset)}})
		default:
			f.t.Errorf("the read sent GraphQL operation %q, which the fake does not know", req.OperationName)
			http.Error(w, "unknown operation", http.StatusTeapot)
		}
	default:
		f.t.Errorf("the read sent %s %s, which the fake does not serve", r.Method, r.URL.Path)
		http.Error(w, "unexpected", http.StatusTeapot)
	}
}

// pageOf is a request's limit and offset.
func pageOf(vars map[string]any) (limit, offset int) {
	l, _ := vars["limit"].(float64)
	o, _ := vars["offset"].(float64)
	return int(l), int(o)
}

// page answers one page of nodes as Infrahub's paginated envelope, with the total count.
func page(nodes []any, limit, offset int) map[string]any {
	total := len(nodes)
	if offset > total {
		offset = total
	}
	end := total
	if limit > 0 && offset+limit < total {
		end = offset + limit
	}
	p := edges(nodes[offset:end])
	p["count"] = total
	return p
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

// nullable is a value that is null when empty.
func nullable(s string) map[string]any {
	if s == "" {
		return value(nil)
	}
	return value(s)
}

func edges(nodes []any) map[string]any {
	out := make([]any, 0, len(nodes))
	for _, n := range nodes {
		out = append(out, map[string]any{"node": n})
	}
	return map[string]any{"edges": out}
}

// devicePage is the Devices answer: every device carrying tag, whatever its status, with
// its platform and manufacturer as far as it has them and its artifacts.
func (f *fakeInfrahub) devicePage(tag string, limit, offset int) map[string]any {
	nodes := []any{}
	for _, d := range f.devices {
		if !slices.Contains(d.Tags, tag) {
			continue
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
		var platform any
		if d.Platform != "" {
			var manufacturer any
			if d.Manufacturer != "" || d.EmptyManufacturer {
				manufacturer = map[string]any{"name": value(d.Manufacturer)}
			}
			platform = map[string]any{"name": value(d.Platform), "manufacturer": map[string]any{"node": manufacturer}}
		}
		nodes = append(nodes, map[string]any{
			"id":        d.ID,
			"name":      value(d.Name),
			"platform":  map[string]any{"node": platform},
			"artifacts": edges(arts),
		})
	}
	return page(nodes, limit, offset)
}

// portPage is the Ports answer: every physical port of the devices whose ids are given,
// each with its cable and every end of it, the device of each physical end by id alone.
func (f *fakeInfrahub) portPage(ids []any, limit, offset int) map[string]any {
	nodes := []any{}
	for _, d := range f.devices {
		if !slices.Contains(ids, any(d.ID)) {
			continue
		}
		for _, p := range d.Ports {
			nodes = append(nodes, map[string]any{
				"id":        p.ID,
				"name":      value(p.Name),
				"role":      nullable(p.Role),
				"status":    nullable(p.Status),
				"device":    map[string]any{"node": map[string]any{"__typename": "DcimDevice", "id": d.ID}},
				"connector": map[string]any{"node": f.connector(p.Cable)},
			})
		}
	}
	return page(nodes, limit, offset)
}

// connector is a port's connector node: null for an uncabled port, else the cable, or the
// connector of another kind, with every end it joins.
func (f *fakeInfrahub) connector(id string) any {
	c, ok := f.cables[id]
	if !ok {
		return nil
	}
	ends := make([]any, 0, len(c.Ends))
	for _, e := range c.Ends {
		if e.Kind != "" {
			ends = append(ends, map[string]any{"__typename": e.Kind, "id": e.ID})
			continue
		}
		d, p := f.port(e.ID)
		ends = append(ends, map[string]any{
			"__typename": "InterfacePhysical",
			"id":         p.ID,
			"name":       value(p.Name),
			"device":     map[string]any{"node": map[string]any{"__typename": "DcimDevice", "id": d.ID}},
		})
	}
	endpoints := edges(ends)
	endpoints["count"] = len(ends)
	if n, ok := f.short[c.ID]; ok {
		endpoints["count"] = n
	}
	if c.Kind != "" {
		return map[string]any{"__typename": c.Kind, "id": c.ID, "connected_endpoints": endpoints}
	}
	return map[string]any{
		"__typename":          "DcimCable",
		"id":                  c.ID,
		"label":               nullable(c.Label),
		"connected_endpoints": endpoints,
	}
}
