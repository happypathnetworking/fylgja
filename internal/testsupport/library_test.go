//go:build contract || fixture

package testsupport

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"sync"
	"testing"
)

// The library's kinds at the pinned commit, every node and generic its six files define:
// what -prepare-main's gate looks for on main (R-13).
var pinnedLibraryKinds = []string{
	"DcimCable", "DcimConnector", "DcimDevice", "DcimDeviceType", "DcimEndpoint", "DcimGenericDevice",
	"DcimInterface", "DcimPhysicalDevice", "DcimPlatform", "InterfaceHasSubInterface", "InterfaceLayer2",
	"InterfaceLayer3", "InterfacePhysical", "InterfaceVirtual", "IpamIPAddress", "IpamPrefix", "IpamPrefixScope",
	"IpamVLANGroupScope", "LocationCountry", "LocationGeneric", "LocationHosting", "LocationMetro",
	"LocationRegion", "LocationSite", "OrganizationGeneric", "OrganizationManufacturer", "OrganizationProvider",
}

func TestLibraryKindsAreWhatTheVendoredFilesDefine(t *testing.T) {
	kinds, err := LibraryKinds(filepath.Join("..", "..", "schema"))
	if err != nil {
		t.Fatal(err)
	}
	if !reflect.DeepEqual(kinds, pinnedLibraryKinds) {
		t.Errorf("the library's kinds:\n got %v\nwant %v", kinds, pinnedLibraryKinds)
	}
	for _, k := range kinds {
		if k == "FylgjaStage" {
			t.Errorf("the stage kind is Fylgja's, not the library's: %v", kinds)
		}
	}
}

func TestLibraryKindsSkipWhatAFileRemoves(t *testing.T) {
	dir := t.TempDir()
	if err := os.Mkdir(filepath.Join(dir, LibraryDir), 0o755); err != nil {
		t.Fatal(err)
	}
	if _, err := LibraryKinds(dir); err == nil || !strings.Contains(err.Error(), "holds no file of the schema library") {
		t.Errorf("an empty %s/: got %v, want a refusal naming it", LibraryDir, err)
	}
	doc := `version: "1.0"
generics:
  - name: Generic
    namespace: Test
nodes:
  - name: Kept
    namespace: Test
  - name: Gone
    namespace: Test
    state: absent
`
	if err := os.WriteFile(filepath.Join(dir, LibraryDir, "test.yml"), []byte(doc), 0o644); err != nil {
		t.Fatal(err)
	}
	// A file beside dcim/ is the stage kind's, never the library's.
	if err := os.WriteFile(filepath.Join(dir, "own.yaml"), []byte("nodes:\n  - name: Own\n    namespace: Test\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	kinds, err := LibraryKinds(dir)
	if err != nil {
		t.Fatal(err)
	}
	if want := []string{"TestGeneric", "TestKept"}; !reflect.DeepEqual(kinds, want) {
		t.Errorf("got %v, want %v", kinds, want)
	}
}

// fakeSchemaInfrahub answers the schema endpoint with the kinds given, the schema load with
// the two hashes given, and GraphQL's Mutation type with every Create mutation asked of
// it, recording each request's method and path.
type fakeSchemaInfrahub struct {
	nodes, generics []string
	hash, previous  string

	mu       sync.Mutex
	requests []string
	loaded   [][]any
}

func (f *fakeSchemaInfrahub) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	f.requests = append(f.requests, r.Method+" "+r.URL.Path+"?"+r.URL.RawQuery)
	f.mu.Unlock()
	if r.Header.Get("X-INFRAHUB-KEY") != "the-token" {
		http.Error(w, "no token", http.StatusUnauthorized)
		return
	}
	switch {
	case r.Method == http.MethodGet && r.URL.Path == "/api/schema":
		kinds := func(names []string) []map[string]string {
			out := []map[string]string{}
			for _, n := range names {
				out = append(out, map[string]string{"kind": n})
			}
			return out
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"main": "h", "nodes": kinds(f.nodes), "generics": kinds(f.generics)})
	case r.Method == http.MethodPost && r.URL.Path == "/api/schema/load":
		var body struct {
			Schemas []any `json:"schemas"`
		}
		_ = json.NewDecoder(r.Body).Decode(&body)
		f.mu.Lock()
		f.loaded = append(f.loaded, body.Schemas)
		f.mu.Unlock()
		_ = json.NewEncoder(w).Encode(map[string]any{"hash": f.hash, "previous_hash": f.previous, "diff": map[string]any{}})
	case r.Method == http.MethodPost && strings.HasPrefix(r.URL.Path, "/graphql/"):
		// Every Create mutation exists: the wait ends at its first poll.
		fields := []map[string]string{}
		for _, k := range pinnedLibraryKinds {
			fields = append(fields, map[string]string{"name": k + "Create"})
		}
		fields = append(fields, map[string]string{"name": "FylgjaStageCreate"})
		_ = json.NewEncoder(w).Encode(map[string]any{"data": map[string]any{"__type": map[string]any{"fields": fields}}})
	default:
		http.Error(w, "unexpected", http.StatusNotFound)
	}
}

func (f *fakeSchemaInfrahub) writes() []string {
	f.mu.Lock()
	defer f.mu.Unlock()
	var out []string
	for _, r := range f.requests {
		if strings.HasPrefix(r, http.MethodPost+" /api/schema/load") {
			out = append(out, r)
		}
	}
	return out
}

func fakeClient(t *testing.T, f *fakeSchemaInfrahub) *Client {
	t.Helper()
	srv := httptest.NewServer(f)
	t.Cleanup(srv.Close)
	return &Client{Address: srv.URL, Token: "the-token", HTTP: srv.Client()}
}

func TestKindsHeldReadsTheBranchsSchema(t *testing.T) {
	f := &fakeSchemaInfrahub{nodes: []string{"DcimDevice", "NetworkDevice"}, generics: []string{"DcimInterface", "CoreNode"}}
	c := fakeClient(t, f)
	held, err := c.KindsHeld("fylgja-test-x", []string{"DcimInterface", "DcimCable", "DcimDevice"})
	if err != nil {
		t.Fatal(err)
	}
	if want := []string{"DcimDevice", "DcimInterface"}; !reflect.DeepEqual(held, want) {
		t.Errorf("held: got %v, want %v", held, want)
	}
	if got := f.requests; len(got) != 1 || got[0] != "GET /api/schema?branch=fylgja-test-x" {
		t.Errorf("requests: %v, want the schema endpoint's one read", got)
	}
}

func TestKindsHeldRefusesAnAnswerThatIsNotTheSchema(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// A proxy that quotes the request's own header back.
		http.Error(w, "refused: "+r.Header.Get("X-INFRAHUB-KEY"), http.StatusInternalServerError)
	}))
	defer srv.Close()
	c := &Client{Address: srv.URL, Token: "the-token", HTTP: srv.Client()}
	_, err := c.KindsHeld("main", pinnedLibraryKinds)
	if err == nil || !strings.Contains(err.Error(), "HTTP 500") {
		t.Fatalf("got %v, want the status named", err)
	}
	if strings.Contains(err.Error(), "the-token") {
		t.Errorf("the token reached the error: %v", err)
	}
}

func TestLoadLibraryRefusesAMainHoldingAnyOfItsKinds(t *testing.T) {
	f := &fakeSchemaInfrahub{nodes: []string{"DcimDevice", "FylgjaStage"}, generics: []string{"DcimConnector"}}
	c := fakeClient(t, f)
	files, err := c.LoadLibrary("main", filepath.Join("..", "..", "schema"))
	var held *LibraryHeldError
	if !errors.As(err, &held) {
		t.Fatalf("got %v, want a *LibraryHeldError", err)
	}
	if files != 0 {
		t.Errorf("files: %d, want 0", files)
	}
	const want = "main holds 2 of the schema library's kinds (DcimConnector, DcimDevice): -prepare-main is the " +
		"development host's and CI's tool, which loads the library on an empty main alone; a main that already " +
		"holds the library is yours, and fylgja schema check says whether it is the one the reader reads"
	if err.Error() != want {
		t.Errorf("the refusal:\n got %s\nwant %s", err, want)
	}
	if w := f.writes(); len(w) != 0 {
		t.Errorf("the refusal wrote: %v", w)
	}
}

func TestLoadLibraryLoadsTheSixFilesInOneRequestOnAnEmptyMain(t *testing.T) {
	f := &fakeSchemaInfrahub{nodes: []string{"FylgjaStage", "CoreArtifact"}, generics: []string{"CoreArtifactTarget"},
		hash: "after", previous: "before"}
	c := fakeClient(t, f)
	files, err := c.LoadLibrary("main", filepath.Join("..", "..", "schema"))
	if err != nil {
		t.Fatal(err)
	}
	if files != 6 {
		t.Errorf("files: %d, want 6", files)
	}
	if w := f.writes(); len(w) != 1 || w[0] != "POST /api/schema/load?branch=main" {
		t.Errorf("writes: %v, want one load on main", w)
	}
	if len(f.loaded) != 1 || len(f.loaded[0]) != 6 {
		t.Errorf("loaded: %d request(s), want one of 6 files", len(f.loaded))
	}
	if f.requests[0] != "GET /api/schema?branch=main" {
		t.Errorf("first request: %s, want the gate's read", f.requests[0])
	}
}

func TestLoadOwnSchemaSaysWhetherTheStageKindMoved(t *testing.T) {
	for _, tc := range []struct {
		name, hash, previous string
		loaded               bool
	}{
		{"the hash moved", "after", "before", true},
		{"the hash held", "same", "same", false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			f := &fakeSchemaInfrahub{hash: tc.hash, previous: tc.previous}
			c := fakeClient(t, f)
			loaded, err := c.LoadOwnSchema("main", filepath.Join("..", "..", "schema"))
			if err != nil {
				t.Fatal(err)
			}
			if loaded != tc.loaded {
				t.Errorf("loaded: %v, want %v", loaded, tc.loaded)
			}
			if len(f.loaded) != 1 || len(f.loaded[0]) != 1 {
				t.Errorf("loaded: %v, want one request of the stage kind alone", f.loaded)
			}
		})
	}
}
