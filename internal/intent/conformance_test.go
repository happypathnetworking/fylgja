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
	"reflect"
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
	// schema is the /api/schema document: the library's at the pinned commit as Infrahub
	// 1.11.2 loads it (testdata/schema-26336e9.json), which a test may mutate, beside the
	// generics' GraphQL answers the bridged read still asks (017's T037, until T043).
	schema map[string]any
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
	// contractless answers the generics' contract query with no instance, a branch with
	// no network on it, which the bridged read refuses (017's T036, until T050).
	contractless bool
}

// fakeRequest is one request as the fake saw it: the path, the GraphQL operation when it
// was one, and the `at` query parameter, decoded, with whether it was sent at all.
type fakeRequest struct {
	Path, Operation, At string
	HasAt               bool
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
		schema:    librarySchema(t),
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
			instances := []any{map[string]any{"node": map[string]any{"version": value(ctm.ContractVersion)}}}
			if f.contractless {
				instances = []any{}
			}
			writeJSON(w, http.StatusOK, map[string]any{"data": map[string]any{"FylgjaContract": map[string]any{
				"edges": instances,
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

// genericsPlatform is the generics' vendor and nos of a CTM "2" package, as the bridged
// reader (017's T023) reads them back: every CTM fixture's device is served as the
// generics model holds it, each interface a physical one.
func genericsPlatform(pkg string) (vendor, nos string) {
	switch pkg {
	case "nokia_srlinux":
		return "nokia", "srlinux"
	case "arista_eos":
		return "arista", "eos"
	case "chassisos":
		return "example", "chassisos"
	}
	return pkg, pkg
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
			enabled := in.Enabled == nil || *in.Enabled
			ifaces = append(ifaces, map[string]any{
				"__typename": "NetworkInterface",
				"id":         d.Name + ":" + in.Name,
				"name":       value(in.Name),
				"iftype":     value("physical"),
				"mgmt_only":  value(in.MgmtOnly),
				"enabled":    value(enabled),
				"parent":     map[string]any{"node": nil},
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
		vendor, nos := genericsPlatform(d.Platform.Package)
		nodes = append(nodes, map[string]any{
			"__typename": "NetworkDevice",
			"id":         "id-" + d.Name,
			"name":       value(d.Name),
			"role":       value(""),
			"site":       value(""),
			"platform": map[string]any{"node": map[string]any{
				"__typename": "NetworkPlatform",
				"vendor":     value(vendor),
				"nos":        value(nos),
				"version":    value(d.Platform.Version),
				"model":      value(""),
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

// The schema document's mutations, each one a branch's schema could have: a kind, a
// field, a choice or an implementer gone, or a field's property changed.

// schemaList is one of the document's lists: its nodes, its generics, or a node's
// attributes or relationships.
func schemaList(t *testing.T, m map[string]any, key string) []any {
	t.Helper()
	l, ok := m[key].([]any)
	if !ok {
		t.Fatalf("the schema document has no list %s", key)
	}
	return l
}

// entry is the list's member whose key holds name.
func entry(t *testing.T, l []any, key, name string) map[string]any {
	t.Helper()
	for _, e := range l {
		if m := e.(map[string]any); m[key] == name {
			return m
		}
	}
	t.Fatalf("the schema document has no %s %s", key, name)
	return nil
}

// without is l less the member whose key holds name.
func without(l []any, key, name string) []any {
	out := make([]any, 0, len(l))
	for _, e := range l {
		if e.(map[string]any)[key] != name {
			out = append(out, e)
		}
	}
	return out
}

// member is a node's attribute or relationship.
func member(t *testing.T, doc map[string]any, kind, section, name string) map[string]any {
	t.Helper()
	return entry(t, schemaList(t, entry(t, schemaList(t, doc, "nodes"), "kind", kind), section), "name", name)
}

func dropNode(t *testing.T, doc map[string]any, kind string) {
	doc["nodes"] = without(schemaList(t, doc, "nodes"), "kind", kind)
}

func dropMember(t *testing.T, doc map[string]any, kind, section, name string) {
	node := entry(t, schemaList(t, doc, "nodes"), "kind", kind)
	node[section] = without(schemaList(t, node, section), "name", name)
}

func dropChoice(t *testing.T, doc map[string]any, kind, attribute, choice string) {
	attr := member(t, doc, kind, "attributes", attribute)
	attr["choices"] = without(schemaList(t, attr, "choices"), "name", choice)
}

func dropImplementer(t *testing.T, doc map[string]any, generic, kind string) {
	g := entry(t, schemaList(t, doc, "generics"), "kind", generic)
	var kept []any
	for _, k := range schemaList(t, g, "used_by") {
		if k != kind {
			kept = append(kept, k)
		}
	}
	g["used_by"] = kept
}

// The mutations each case below is made of. DcimCable gone takes it out of
// DcimConnector's used_by too, as Infrahub's endpoint would.
var (
	cableGone = func(t *testing.T, doc map[string]any) {
		dropNode(t, doc, "DcimCable")
		dropImplementer(t, doc, "DcimConnector", "DcimCable")
	}
	roleGone           = func(t *testing.T, doc map[string]any) { dropMember(t, doc, "InterfacePhysical", "attributes", "role") }
	platformNameNumber = func(t *testing.T, doc map[string]any) {
		member(t, doc, "DcimPlatform", "attributes", "name")["kind"] = "Number"
	}
	platformManyNet = func(t *testing.T, doc map[string]any) {
		rel := member(t, doc, "DcimDevice", "relationships", "platform")
		rel["cardinality"], rel["peer"] = "many", "NetPlatform"
	}
	deviceNameOptional = func(t *testing.T, doc map[string]any) {
		member(t, doc, "DcimDevice", "attributes", "name")["optional"] = true
	}
	managementGone = func(t *testing.T, doc map[string]any) { dropChoice(t, doc, "InterfacePhysical", "role", "management") }
	disabledGone   = func(t *testing.T, doc map[string]any) { dropChoice(t, doc, "InterfacePhysical", "status", "disabled") }
	endpointGone   = func(t *testing.T, doc map[string]any) { dropImplementer(t, doc, "DcimEndpoint", "InterfacePhysical") }
)

// readsIt is the end of every conformance finding but used_by's: the commit the table was
// written against.
const readsIt = "; the mapping reads it as opsmill/schema-library@26336e9 has it"

// The library at the pinned commit conforms, and the check says what it verified: the
// model and the commit, and each kind with its fields in the table's order. It asks the
// schema endpoint alone, before any data is read.
func TestConformanceOfTheLibrary(t *testing.T) {
	f := newFakeInfrahub(t)

	conf, list := checkConformance(t, f)

	if len(list) != 0 {
		t.Fatalf("the library's schema gave findings: %v", list)
	}
	if conf.Model != "opsmill/schema-library" || conf.Version != "26336e9" || conf.SchemaHash != "18e5f023994de4261ad266e61aac2615" {
		t.Errorf("model %q version %q hash %q, want the library, its commit and the document's hash", conf.Model, conf.Version, conf.SchemaHash)
	}
	want := []findings.KindFields{
		{Kind: "DcimDevice", Fields: []string{"name", "tags", "platform", "interfaces", "artifacts"}},
		{Kind: "DcimPlatform", Fields: []string{"name", "manufacturer"}},
		{Kind: "OrganizationManufacturer", Fields: []string{"name"}},
		{Kind: "InterfacePhysical", Fields: []string{"name", "role", "status", "device", "connector"}},
		{Kind: "DcimCable", Fields: []string{"connected_endpoints"}},
	}
	if !reflect.DeepEqual(conf.Kinds, want) {
		t.Errorf("kinds %+v, want %+v", conf.Kinds, want)
	}
	if v := conf.Verified(); v.Model != conf.Model || v.Version != conf.Version || !reflect.DeepEqual(v.Kinds, want) {
		t.Errorf("verified %+v, want the conformance's model, version and kinds", v)
	}
	if n := f.count("/graphql/" + f.branch); n != 0 {
		t.Errorf("conformance asked GraphQL %d times; it reads the schema endpoint alone", n)
	}
}

// Each kind, field, property, choice or implementer the table names, gone or changed, is
// one rejection naming it and the commit (FR-012; US3 scenario 2). A kind gone is named
// once: neither its fields nor the generic it implemented are named beside it.
func TestConformanceNamesWhatDiffers(t *testing.T) {
	for _, c := range []struct {
		name   string
		mutate func(*testing.T, map[string]any)
		want   findings.Finding
	}{
		{"DcimCable gone", cableGone, findings.Finding{Rule: findings.RuleSchemaKindMissing, Object: "DcimCable",
			Message: "the branch's schema has no kind DcimCable" + readsIt}},
		{"InterfacePhysical.role gone", roleGone, findings.Finding{Rule: findings.RuleSchemaFieldMissing, Object: "InterfacePhysical.role",
			Message: "InterfacePhysical has no attribute role" + readsIt}},
		{"InterfacePhysical.connector gone", func(t *testing.T, doc map[string]any) {
			dropMember(t, doc, "InterfacePhysical", "relationships", "connector")
		}, findings.Finding{Rule: findings.RuleSchemaFieldMissing, Object: "InterfacePhysical.connector",
			Message: "InterfacePhysical has no relationship connector" + readsIt}},
		{"DcimPlatform.name a Number", platformNameNumber, findings.Finding{Rule: findings.RuleSchemaFieldMismatch, Object: "DcimPlatform.name",
			Message: "kind Text, found Number" + readsIt}},
		{"DcimDevice.platform many, to NetPlatform", platformManyNet, findings.Finding{Rule: findings.RuleSchemaFieldMismatch,
			Object: "DcimDevice.platform", Message: "peer DcimPlatform, found NetPlatform; cardinality one, found many" + readsIt}},
		{"DcimDevice.name optional", deviceNameOptional, findings.Finding{Rule: findings.RuleSchemaFieldMismatch, Object: "DcimDevice.name",
			Message: "optional false, found true" + readsIt}},
		{"InterfacePhysical.device optional", func(t *testing.T, doc map[string]any) {
			member(t, doc, "InterfacePhysical", "relationships", "device")["optional"] = true
		}, findings.Finding{Rule: findings.RuleSchemaFieldMismatch, Object: "InterfacePhysical.device",
			Message: "optional false, found true" + readsIt}},
		{"management gone from role", managementGone, findings.Finding{Rule: findings.RuleSchemaChoiceMissing, Object: "InterfacePhysical.role",
			Message: "the dropdown has no choice management" + readsIt}},
		{"disabled gone from status", disabledGone, findings.Finding{Rule: findings.RuleSchemaChoiceMissing, Object: "InterfacePhysical.status",
			Message: "the dropdown has no choice disabled" + readsIt}},
		{"InterfacePhysical gone from DcimEndpoint's used_by", endpointGone, findings.Finding{Rule: findings.RuleSchemaUsedByMissing,
			Object: "DcimEndpoint", Message: "InterfacePhysical does not implement DcimEndpoint; the mapping reads InterfacePhysical " +
				"through it as opsmill/schema-library@26336e9 has it"}},
		{"DcimEndpoint gone", func(t *testing.T, doc map[string]any) {
			doc["generics"] = without(schemaList(t, doc, "generics"), "kind", "DcimEndpoint")
		}, findings.Finding{Rule: findings.RuleSchemaUsedByMissing, Object: "DcimEndpoint",
			Message: "the branch's schema has no generic DcimEndpoint; the mapping reads InterfacePhysical " +
				"through it as opsmill/schema-library@26336e9 has it"}},
		{"InterfacePhysical gone", func(t *testing.T, doc map[string]any) {
			dropNode(t, doc, "InterfacePhysical")
			dropImplementer(t, doc, "DcimInterface", "InterfacePhysical")
			dropImplementer(t, doc, "DcimEndpoint", "InterfacePhysical")
		}, findings.Finding{Rule: findings.RuleSchemaKindMissing, Object: "InterfacePhysical",
			Message: "the branch's schema has no kind InterfacePhysical" + readsIt}},
	} {
		t.Run(c.name, func(t *testing.T) {
			f := newFakeInfrahub(t)
			c.mutate(t, f.schema)

			_, list := checkConformance(t, f)

			c.want.Severity = findings.Rejection
			if len(list) != 1 || list[0] != c.want {
				t.Fatalf("findings %+v, want exactly %+v", list, c.want)
			}
		})
	}
}

// Every difference comes in one pass (SC-004), in the table's order and then the
// generics': an operator setting a branch up needs no second run to see the next one.
func TestConformanceNamesEveryDifferenceInOnePass(t *testing.T) {
	f := newFakeInfrahub(t)
	for _, mutate := range []func(*testing.T, map[string]any){
		cableGone, roleGone, platformNameNumber, platformManyNet, deviceNameOptional, disabledGone, endpointGone,
	} {
		mutate(t, f.schema)
	}

	_, list := checkConformance(t, f)

	type got struct{ rule, object string }
	var rules []got
	for _, fd := range list {
		rules = append(rules, got{fd.Rule, fd.Object})
		if fd.Severity != findings.Rejection || !strings.Contains(fd.Message, "opsmill/schema-library@26336e9") {
			t.Errorf("%s %s: %s %q; every finding is a rejection naming the commit", fd.Rule, fd.Object, fd.Severity, fd.Message)
		}
	}
	want := []got{
		{findings.RuleSchemaFieldMismatch, "DcimDevice.name"},
		{findings.RuleSchemaFieldMismatch, "DcimDevice.platform"},
		{findings.RuleSchemaFieldMismatch, "DcimPlatform.name"},
		{findings.RuleSchemaFieldMissing, "InterfacePhysical.role"},
		{findings.RuleSchemaChoiceMissing, "InterfacePhysical.status"},
		{findings.RuleSchemaKindMissing, "DcimCable"},
		{findings.RuleSchemaUsedByMissing, "DcimEndpoint"},
	}
	if !slices.Equal(rules, want) {
		t.Errorf("findings %v, want %v", rules, want)
	}
}

// What the table does not name is never reported (FR-012; US3 scenario 3): a kind of the
// operator's own, a field they added to a kind the mapping reads, a choice beyond the
// mapping's, an implementer beside the expected one, and an optional field the table
// leaves optional read as required.
func TestConformanceIgnoresWhatTheTableDoesNotName(t *testing.T) {
	f := newFakeInfrahub(t)
	f.schema["nodes"] = append(schemaList(t, f.schema, "nodes"), map[string]any{
		"kind": "AcmeWidget", "attributes": []any{map[string]any{"name": "name", "kind": "Number", "optional": true}},
		"relationships": []any{},
	})
	device := entry(t, schemaList(t, f.schema, "nodes"), "kind", "DcimDevice")
	device["attributes"] = append(schemaList(t, device, "attributes"),
		map[string]any{"name": "acme_asset_tag", "kind": "Text", "optional": false})
	device["relationships"] = append(schemaList(t, device, "relationships"),
		map[string]any{"name": "acme_owner", "peer": "AcmeWidget", "kind": "Attribute", "cardinality": "one", "optional": false})
	role := member(t, f.schema, "InterfacePhysical", "attributes", "role")
	role["choices"] = append(schemaList(t, role, "choices"), map[string]any{"name": "acme_backplane"})
	role["optional"] = false
	member(t, f.schema, "DcimDevice", "relationships", "platform")["optional"] = false
	// Fields the mapping does not read, changed: the reader never reads them (FR-010).
	member(t, f.schema, "DcimDevice", "attributes", "description")["kind"] = "Number"
	dropMember(t, f.schema, "DcimDevice", "attributes", "status")
	g := entry(t, schemaList(t, f.schema, "generics"), "kind", "DcimEndpoint")
	g["used_by"] = append(schemaList(t, g, "used_by"), "AcmeWidget")

	if _, list := checkConformance(t, f); len(list) != 0 {
		t.Errorf("findings %+v, want none: nothing the table names differs", list)
	}
}

// A branch that does not conform refuses the read with the same findings schema check
// gives, before any data is read, and no CTM (US3 scenario 4; FR-011).
func TestReadIsRefusedByConformance(t *testing.T) {
	f := newFakeInfrahub(t)
	cableGone(t, f.schema)
	roleGone(t, f.schema)

	snapshot, list, err := readFake(t, f)

	if err != nil {
		t.Fatal(err)
	}
	if snapshot != nil {
		t.Error("a read refused by conformance produced a CTM")
	}
	if len(list) != 2 || list[0].Object != "InterfacePhysical.role" || list[1].Object != "DcimCable" || !list.Rejected() {
		t.Errorf("findings %+v, want InterfacePhysical.role's and DcimCable's alone", list)
	}
	if n := f.count("/graphql/" + f.branch); n != 0 {
		t.Errorf("a refused read asked GraphQL %d times", n)
	}
}

// The bridge (017's T036, until T050): the read is still the generics', so a conforming
// branch holding no contract instance, main with no network on it above all, is still
// refused contract.node.missing as conformance refused it before, naming the branch, and
// reads nothing more.
func TestBridgedReadRefusesABranchWithNoContract(t *testing.T) {
	f := newFakeInfrahub(t)
	f.contractless = true

	snapshot, list, err := readFake(t, f)

	if err != nil {
		t.Fatal(err)
	}
	want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleContractNodeMissing, Object: f.branch,
		Message: "branch defines FylgjaContract but holds no instance of it"}
	if snapshot != nil || len(list) != 1 || list[0] != want {
		t.Fatalf("CTM %v, findings %+v; want none and exactly %+v", snapshot != nil, list, want)
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	for _, r := range f.served {
		if r.Operation == "Devices" || r.Operation == "Links" {
			t.Errorf("a refused read asked %s", r.Operation)
		}
	}
}
