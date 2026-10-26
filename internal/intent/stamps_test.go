package intent

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"slices"
	"strings"
	"sync"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/psp"
)

// fakeStamps is a branch's IntentStamps and PortStamps as Infrahub's GraphQL answers
// them, paged, and what it was asked. Each device is an edge of the device root, its
// node_metadata beside its node, and each port a node of the physical root; the devices
// are served to the scope's tag alone, the ports to the device ids asked for.
type fakeStamps struct {
	branch  string
	tag     string
	devices []map[string]any
	ports   []map[string]any

	mu      sync.Mutex
	queries []string // each request's operation and raw query string
	offsets []int    // each IntentStamps page's offset
	asked   [][]any  // each PortStamps request's device ids
}

func (f *fakeStamps) serve(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost || r.URL.Path != "/graphql/"+f.branch {
		http.NotFound(w, r)
		return
	}
	var req struct {
		OperationName string `json:"operationName"`
		Query         string `json:"query"`
		Variables     struct {
			Tag           string
			Devices       []any
			Limit, Offset int
		} `json:"variables"`
	}
	body, _ := io.ReadAll(r.Body)
	_ = json.Unmarshal(body, &req)
	f.mu.Lock()
	f.queries = append(f.queries, req.OperationName+" "+r.URL.RawQuery)
	f.mu.Unlock()
	switch req.OperationName {
	case "IntentStamps":
		f.mu.Lock()
		f.offsets = append(f.offsets, req.Variables.Offset)
		f.mu.Unlock()
		var devices []map[string]any
		if req.Variables.Tag == f.tag {
			devices = f.devices
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"data": map[string]any{
			"DcimDevice": edgePage(devices, req.Variables.Limit, req.Variables.Offset)}})
	case "PortStamps":
		f.mu.Lock()
		f.asked = append(f.asked, req.Variables.Devices)
		f.mu.Unlock()
		// Infrahub refuses a page holding an uncabled port's connector stamp, so the query
		// asks for cabled ports alone, as this fake serves them.
		if !strings.Contains(req.Query, "connector__isnull: false") {
			http.Error(w, "an uncabled port's connector.node_metadata is null in a non-null field", http.StatusTeapot)
			return
		}
		var ports []map[string]any
		for _, p := range f.ports {
			owner := p["device"].(map[string]any)["node"].(map[string]any)["id"]
			if p["connector"].(map[string]any)["node"] != nil && slices.Contains(req.Variables.Devices, owner) {
				ports = append(ports, map[string]any{"node": p})
			}
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"data": map[string]any{
			"InterfacePhysical": edgePage(ports, req.Variables.Limit, req.Variables.Offset)}})
	default:
		http.Error(w, "unknown operation "+req.OperationName, http.StatusTeapot)
	}
}

func (f *fakeStamps) read(t *testing.T, at string) (Stamps, error) {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(f.serve))
	t.Cleanup(srv.Close)
	return New(Config{Address: srv.URL, Token: "sentinel-token", Branch: f.branch, At: at, Scope: "fylgja"}).Stamps(ctx10s(t))
}

// edgePage is one page of edges, each as given.
func edgePage(edges []map[string]any, limit, offset int) map[string]any {
	end := min(offset+limit, len(edges))
	page := []map[string]any{}
	page = append(page, edges[min(offset, len(edges)):end]...)
	return map[string]any{"count": len(edges), "edges": page}
}

// meta is an edge wrapper's node_metadata; "" is Infrahub's null.
func meta(s string) map[string]any {
	if s == "" {
		return map[string]any{"updated_at": nil}
	}
	return map[string]any{"updated_at": s}
}

func valueOf(v any) map[string]any { return map[string]any{"value": v} }

// stampedDevice is a device's edge: its own stamp, on Nokia's SR Linux with the platform
// and the manufacturer stamped at stampPlatform, with the interfaces and artifacts given.
// Its id is dev-<name>, its platform's platform-srlinux, its manufacturer's
// manufacturer-nokia.
func stampedDevice(name, s string, interfaces []map[string]any, artifacts ...map[string]any) map[string]any {
	var artifactEdges []map[string]any
	for _, a := range artifacts {
		artifactEdges = append(artifactEdges, map[string]any{"node": a})
	}
	return map[string]any{
		"node_metadata": meta(s),
		"node": map[string]any{
			"__typename": "DcimDevice",
			"id":         "dev-" + name,
			"name":       valueOf(name),
			"platform":   stampedPlatform("platform-srlinux", "SR Linux", stampPlatform, "manufacturer-nokia", "Nokia", stampPlatform),
			"interfaces": map[string]any{"edges": interfaces},
			"artifacts":  map[string]any{"edges": artifactEdges},
		},
	}
}

// stampedPlatform is a device's platform edge, its manufacturer's within it.
func stampedPlatform(id, name, s, manufacturerID, manufacturer, ms string) map[string]any {
	return map[string]any{
		"node_metadata": meta(s),
		"node": map[string]any{
			"id":   id,
			"name": valueOf(name),
			"manufacturer": map[string]any{
				"node_metadata": meta(ms),
				"node":          map[string]any{"id": manufacturerID, "name": valueOf(manufacturer)},
			},
		},
	}
}

// onPlatform puts a device on a platform edge of its own.
func onPlatform(device, platform map[string]any) map[string]any {
	device["node"].(map[string]any)["platform"] = platform
	return device
}

// stampedInterface is one interface edge of a device, of either kind.
func stampedInterface(typename, id, s string) map[string]any {
	return map[string]any{"node_metadata": meta(s), "node": map[string]any{"__typename": typename, "id": id}}
}

func stampedArtifact(name, checksumStamp string) map[string]any {
	var at any
	if checksumStamp != "" {
		at = checksumStamp
	}
	return map[string]any{
		"name":     valueOf(name),
		"checksum": map[string]any{"value": "43e8fd0c2de5f4646f74a51d34742824", "updated_at": at},
	}
}

// stampedPort is a physical port of a device, cabled when cable is not "".
func stampedPort(device, cable, s string) map[string]any {
	connector := map[string]any{"node_metadata": meta(""), "node": nil}
	if cable != "" {
		connector = map[string]any{"node_metadata": meta(s), "node": map[string]any{"__typename": "DcimCable", "id": cable}}
	}
	return map[string]any{
		"device":    map[string]any{"node": map[string]any{"__typename": "DcimDevice", "id": "dev-" + device}},
		"connector": connector,
	}
}

// The fixture's own stamps (research §6.6, §8.16): its one platform written first, the
// devices after, interfaces after them, the cabling after that, the artifacts' checksums
// last.
const (
	stampPlatform   = "2026-10-08T05:47:56.812998+00:00"
	stampDevices    = "2026-10-08T05:47:58.232738+00:00"
	stampInterfaces = "2026-10-08T05:48:00.978841+00:00"
	stampCabling    = "2026-10-08T05:48:03.562937+00:00"
	stampArtifacts  = "2026-10-08T05:48:38.544482+00:00"
)

// Latest is the latest instant the read returned, compared as times rather than as
// strings, and kept verbatim: a stamp in another offset that sorts after it as text but
// names an earlier instant does not win, and a Z stamp that is later does.
func TestStampsLatest(t *testing.T) {
	f := &fakeStamps{branch: "change-1", tag: "fylgja",
		devices: []map[string]any{
			stampedDevice("n1", stampDevices, []map[string]any{stampedInterface("InterfacePhysical", "if-n1-e1", stampInterfaces)}),
			// 06:48:01+01:00 is 05:48:01Z: lexically the latest string, not the latest instant.
			stampedDevice("n2", "2026-10-08T06:48:01.000000+01:00", nil),
		},
		ports: []map[string]any{stampedPort("n1", "cable-1", "2026-10-08T05:48:03.9Z"), stampedPort("n2", "cable-1", "2026-10-08T05:48:03.9Z")},
	}
	got, err := f.read(t, "")
	if err != nil {
		t.Fatal(err)
	}
	if got.Latest != "2026-10-08T05:48:03.9Z" {
		t.Errorf("Latest = %q, want the Z cable stamp, the latest instant, verbatim", got.Latest)
	}
	if got.Devices["n2"].Intent != "2026-10-08T05:48:03.9Z" {
		t.Errorf("n2's intent = %q: its cable is its intent too", got.Devices["n2"].Intent)
	}
}

// Each of the five sources of a device's intent moves its stamp alone (FR-023): the device,
// an interface of either kind, its platform, its platform's manufacturer and the cable one
// of its ports is an end of. n2, beside it on its own platform, keeps its own.
func TestStampsEachSourceMovesTheDevice(t *testing.T) {
	const later = "2026-10-16T19:00:00.000001+00:00"
	for _, tc := range []struct {
		name string
		edit func(n1 map[string]any, ports []map[string]any)
	}{
		{"the device", func(n1 map[string]any, _ []map[string]any) { n1["node_metadata"] = meta(later) }},
		{"a physical interface", func(n1 map[string]any, _ []map[string]any) {
			n1["node"].(map[string]any)["interfaces"].(map[string]any)["edges"].([]map[string]any)[0]["node_metadata"] = meta(later)
		}},
		{"a virtual interface", func(n1 map[string]any, _ []map[string]any) {
			n1["node"].(map[string]any)["interfaces"].(map[string]any)["edges"].([]map[string]any)[1]["node_metadata"] = meta(later)
		}},
		{"its platform", func(n1 map[string]any, _ []map[string]any) {
			n1["node"].(map[string]any)["platform"].(map[string]any)["node_metadata"] = meta(later)
		}},
		{"its manufacturer", func(n1 map[string]any, _ []map[string]any) {
			platform := n1["node"].(map[string]any)["platform"].(map[string]any)["node"].(map[string]any)
			platform["manufacturer"].(map[string]any)["node_metadata"] = meta(later)
		}},
		{"its cable", func(_ map[string]any, ports []map[string]any) {
			ports[0]["connector"].(map[string]any)["node_metadata"] = meta(later)
		}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			n1 := stampedDevice("n1", stampDevices, []map[string]any{
				stampedInterface("InterfacePhysical", "if-n1-e1", stampInterfaces),
				stampedInterface("InterfaceVirtual", "if-n1-lo0", stampInterfaces),
			})
			n2 := onPlatform(stampedDevice("n2", stampDevices, nil),
				stampedPlatform("platform-eos", "EOS", stampPlatform, "manufacturer-arista", "Arista", stampPlatform))
			ports := []map[string]any{stampedPort("n1", "cable-out", stampCabling), stampedPort("n2", "", "")}
			tc.edit(n1, ports)
			f := &fakeStamps{branch: "change-1", tag: "fylgja", devices: []map[string]any{n1, n2}, ports: ports}
			got, err := f.read(t, "")
			if err != nil {
				t.Fatal(err)
			}
			if got.Devices["n1"].Intent != later {
				t.Errorf("n1's intent = %q, want %q", got.Devices["n1"].Intent, later)
			}
			if got.Devices["n2"].Intent != stampDevices {
				t.Errorf("n2's intent = %q, want its own %q", got.Devices["n2"].Intent, stampDevices)
			}
			if got.Latest != later {
				t.Errorf("Latest = %q, want %q", got.Latest, later)
			}
		})
	}
}

// A cable is the intent of the device of each of its ends in the scope, and of no third:
// a re-cabling of n1 and n2 moves both, and neither n3 nor anything n3 holds.
func TestStampsCableMovesBothDevicesAndNoThird(t *testing.T) {
	const recabled = "2026-10-16T19:41:12.000300+00:00"
	f := &fakeStamps{branch: "change-1", tag: "fylgja",
		devices: []map[string]any{
			stampedDevice("n1", stampDevices, nil),
			stampedDevice("n2", stampDevices, nil),
			stampedDevice("n3", stampDevices, nil),
		},
		ports: []map[string]any{
			stampedPort("n1", "cable-12", recabled), stampedPort("n2", "cable-12", recabled),
			stampedPort("n2", "cable-23", stampCabling), stampedPort("n3", "cable-23", stampCabling),
		},
	}
	got, err := f.read(t, "")
	if err != nil {
		t.Fatal(err)
	}
	for name, want := range map[string]string{"n1": recabled, "n2": recabled, "n3": stampCabling} {
		if got.Devices[name].Intent != want {
			t.Errorf("%s's intent = %q, want %q", name, got.Devices[name].Intent, want)
		}
	}
}

// A null stamp is skipped wherever it is: a device's own, a platform's, a manufacturer's,
// an interface's, an uncabled port's connector.
func TestStampsSkipANull(t *testing.T) {
	n1 := onPlatform(stampedDevice("n1", "", []map[string]any{stampedInterface("InterfacePhysical", "if-n1-e1", "")}),
		stampedPlatform("platform-srlinux", "SR Linux", "", "manufacturer-nokia", "Nokia", ""))
	f := &fakeStamps{branch: "change-1", tag: "fylgja",
		devices: []map[string]any{n1, stampedDevice("n2", stampDevices, nil)},
		ports:   []map[string]any{stampedPort("n1", "", ""), stampedPort("n1", "cable-1", "")}}
	got, err := f.read(t, "")
	if err != nil {
		t.Fatal(err)
	}
	if got.Devices["n1"].Intent != "" {
		t.Errorf("n1's intent = %q, want none", got.Devices["n1"].Intent)
	}
	if got.Latest != stampDevices {
		t.Errorf("Latest = %q, want n2's %q", got.Latest, stampDevices)
	}
}

// Each device keeps its pair, by which the registry picks its package, and the ids an
// intent event names it by, in the order read (D-048): its own, its platform's, its
// manufacturer's, each interface's of both kinds, then each cable's once. A device with no
// platform, or a platform with no manufacturer, has "" where it has none.
func TestStampsMatchAndIDs(t *testing.T) {
	bare := stampedDevice("n2", stampDevices, nil)
	bare["node"].(map[string]any)["platform"] = map[string]any{"node_metadata": meta(""), "node": nil}
	orphan := onPlatform(stampedDevice("n3", stampDevices, nil), map[string]any{"node_metadata": meta(stampPlatform),
		"node": map[string]any{"id": "platform-orphan", "name": valueOf("Orphan OS"),
			"manufacturer": map[string]any{"node_metadata": meta(""), "node": nil}}})
	f := &fakeStamps{branch: "change-1", tag: "fylgja",
		devices: []map[string]any{
			stampedDevice("n1", stampDevices, []map[string]any{
				stampedInterface("InterfacePhysical", "if-n1-e1", stampInterfaces),
				stampedInterface("InterfacePhysical", "if-n1-e2", stampInterfaces),
				stampedInterface("InterfaceVirtual", "if-n1-lo0", stampInterfaces),
			}),
			bare, orphan,
		},
		// A cable with both ends on n1 is n1's once.
		ports: []map[string]any{stampedPort("n1", "cable-loop", stampCabling), stampedPort("n1", "cable-loop", stampCabling)},
	}
	got, err := f.read(t, "")
	if err != nil {
		t.Fatal(err)
	}
	if ids := got.Devices["n1"].IDs; !slices.Equal(ids, []string{
		"dev-n1", "platform-srlinux", "manufacturer-nokia", "if-n1-e1", "if-n1-e2", "if-n1-lo0", "cable-loop"}) {
		t.Errorf("n1's ids = %v", ids)
	}
	for name, want := range map[string]psp.Match{
		"n1": {Manufacturer: "Nokia", Platform: "SR Linux"},
		"n2": {},
		"n3": {Platform: "Orphan OS"},
	} {
		if got.Devices[name].Match != want {
			t.Errorf("%s's pair = %+v, want %+v", name, got.Devices[name].Match, want)
		}
	}
	if ids := got.Devices["n2"].IDs; !slices.Equal(ids, []string{"dev-n2"}) {
		t.Errorf("n2's ids = %v", ids)
	}
	if ids := got.Devices["n3"].IDs; !slices.Equal(ids, []string{"dev-n3", "platform-orphan"}) {
		t.Errorf("n3's ids = %v", ids)
	}
}

// An artifact's checksum stamp is the artifact's and the branch's latest, never the
// device's intent: a generate that moves it does not make the device's intent newer.
func TestStampsArtifactChecksum(t *testing.T) {
	f := &fakeStamps{branch: "change-1", tag: "fylgja", devices: []map[string]any{
		stampedDevice("n1", stampDevices, nil, stampedArtifact("device-config", stampArtifacts), stampedArtifact("unrendered", "")),
		stampedDevice("n2", stampDevices, nil),
	}}
	got, err := f.read(t, "")
	if err != nil {
		t.Fatal(err)
	}
	if got.Latest != stampArtifacts {
		t.Errorf("Latest = %q, want the checksum's %q", got.Latest, stampArtifacts)
	}
	n1 := got.Devices["n1"]
	if n1.Intent != stampDevices {
		t.Errorf("n1's intent = %q, want %q: a checksum is not intent", n1.Intent, stampDevices)
	}
	want := map[string]string{"device-config": stampArtifacts, "unrendered": ""}
	if len(n1.Artifacts) != len(want) {
		t.Errorf("n1's artifacts = %v, want %v", n1.Artifacts, want)
	}
	for name, s := range want {
		if got, ok := n1.Artifacts[name]; !ok || got != s {
			t.Errorf("n1's artifact %s = %q (%v), want %q", name, got, ok, s)
		}
	}
	if len(got.Devices["n2"].Artifacts) != 0 {
		t.Errorf("n2 has no artifact, got %v", got.Devices["n2"].Artifacts)
	}
}

// The devices are read under the scope's tag alone: a scope that selects none reads no
// device and asks for no port.
func TestStampsReadUnderTheScope(t *testing.T) {
	f := &fakeStamps{branch: "change-1", tag: "other", devices: []map[string]any{stampedDevice("n1", stampDevices, nil)},
		ports: []map[string]any{stampedPort("n1", "cable-1", stampCabling)}}
	got, err := f.read(t, "")
	if err != nil {
		t.Fatal(err)
	}
	if len(got.Devices) != 0 || got.Latest != "" {
		t.Errorf("read %+v under a tag no device carries", got)
	}
	if len(f.asked) != 0 {
		t.Errorf("ports asked for %v with no device read", f.asked)
	}
}

// The devices are paged until every one is read, and their ports are asked for by a
// hundred device ids at a time: 150 devices are two pages of each.
func TestStampsReadsEveryPage(t *testing.T) {
	var devices, ports []map[string]any
	for i := range 150 {
		name := fmt.Sprintf("n%03d", i)
		devices = append(devices, stampedDevice(name, stampDevices, nil))
		ports = append(ports, stampedPort(name, "", ""))
	}
	devices[149]["node_metadata"] = meta(stampArtifacts)
	ports[0] = stampedPort("n000", "cable-1", stampCabling)
	f := &fakeStamps{branch: "change-1", tag: "fylgja", devices: devices, ports: ports}
	got, err := f.read(t, "")
	if err != nil {
		t.Fatal(err)
	}
	if len(got.Devices) != 150 {
		t.Errorf("%d devices, want 150", len(got.Devices))
	}
	if !slices.Equal(f.offsets, []int{0, pageSize}) {
		t.Errorf("pages requested at offsets %v, want [0 %d]", f.offsets, pageSize)
	}
	if len(f.asked) != 2 || len(f.asked[0]) != pageSize || len(f.asked[1]) != 50 {
		t.Errorf("ports asked for by %d requests", len(f.asked))
	}
	if got.Latest != stampArtifacts {
		t.Errorf("Latest = %q: the second page's stamp was not read", got.Latest)
	}
	if got.Devices["n000"].Intent != stampCabling {
		t.Errorf("n000's intent = %q: its cable was not read", got.Devices["n000"].Intent)
	}
}

// A pinned read sends its `at` verbatim and URL encoded on every page of both operations,
// and an unpinned one sends none (Constitution VI).
func TestStampsPinnedOnEveryPage(t *testing.T) {
	const at = "2026-10-08T05:48:38.544483+00:00"
	var devices []map[string]any
	for i := range 101 {
		devices = append(devices, stampedDevice(fmt.Sprintf("n%03d", i), stampDevices, nil))
	}
	f := &fakeStamps{branch: "change-1", tag: "fylgja", devices: devices}
	if _, err := f.read(t, at); err != nil {
		t.Fatal(err)
	}
	if want := []string{"IntentStamps", "IntentStamps", "PortStamps", "PortStamps"}; len(f.queries) != len(want) {
		t.Fatalf("requests %v, want %v", f.queries, want)
	}
	for i, q := range f.queries {
		op, raw, _ := strings.Cut(q, " ")
		if raw != "at="+url.QueryEscape(at) {
			t.Errorf("request %d (%s) sent %q, want at= the instant URL encoded", i, op, raw)
		}
		if v, _ := url.ParseQuery(raw); v.Get("at") != at {
			t.Errorf("request %d's at decoded to %q, want %q", i, v.Get("at"), at)
		}
	}

	f.queries = nil
	if _, err := f.read(t, ""); err != nil {
		t.Fatal(err)
	}
	for i, q := range f.queries {
		if _, raw, _ := strings.Cut(q, " "); raw != "" {
			t.Errorf("unpinned request %d sent %q", i, raw)
		}
	}
}

// A stamp that is not a time is an error naming it, the branch and the instant, and
// never the credential.
func TestStampsRefuseAStampThatIsNotATime(t *testing.T) {
	f := &fakeStamps{branch: "change-1", tag: "fylgja", devices: []map[string]any{stampedDevice("n1", "yesterday", nil)}}
	_, err := f.read(t, "2026-10-08T05:48:38.544483+00:00")
	if err == nil {
		t.Fatal("want an error")
	}
	for _, want := range []string{`"yesterday"`, "branch change-1", "at 2026-10-08T05:48:38.544483+00:00"} {
		if !strings.Contains(err.Error(), want) {
			t.Errorf("error %q does not carry %s", err, want)
		}
	}
	if strings.Contains(err.Error(), "sentinel-token") {
		t.Errorf("the credential reached the error: %v", err)
	}
}
