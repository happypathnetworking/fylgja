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

	"github.com/happypathnetworking/fylgja/internal/ctm"
)

// fakeStamps is a branch's IntentStamps as Infrahub's GraphQL answers it, paged, and
// what it was asked.
type fakeStamps struct {
	branch  string
	devices []map[string]any
	links   []map[string]any

	mu      sync.Mutex
	queries []string // each request's raw query string
	offsets []int
}

func (f *fakeStamps) serve(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost || r.URL.Path != "/graphql/"+f.branch {
		http.NotFound(w, r)
		return
	}
	var req struct {
		OperationName string `json:"operationName"`
		Variables     struct {
			Limit, Offset int
		} `json:"variables"`
	}
	body, _ := io.ReadAll(r.Body)
	_ = json.Unmarshal(body, &req)
	if req.OperationName != "IntentStamps" {
		http.Error(w, "unknown operation "+req.OperationName, http.StatusTeapot)
		return
	}
	f.mu.Lock()
	f.queries = append(f.queries, r.URL.RawQuery)
	f.offsets = append(f.offsets, req.Variables.Offset)
	f.mu.Unlock()
	_ = json.NewEncoder(w).Encode(map[string]any{"data": map[string]any{
		"FylgjaDevice": stagePage(f.devices, req.Variables.Limit, req.Variables.Offset),
		"FylgjaLink":   stagePage(f.links, req.Variables.Limit, req.Variables.Offset),
	}})
}

func (f *fakeStamps) read(t *testing.T, at string) (Stamps, error) {
	t.Helper()
	srv := httptest.NewServer(http.HandlerFunc(f.serve))
	t.Cleanup(srv.Close)
	return New(Config{Address: srv.URL, Token: "sentinel-token", Branch: f.branch, At: at}).Stamps(ctx10s(t))
}

// stamp is one attribute's or edge's metadata; "" is Infrahub's null.
func stamp(s string) any {
	if s == "" {
		return nil
	}
	return s
}

func valueOf(v any) map[string]any { return map[string]any{"value": v} }

func stampAttr(s string) map[string]any { return map[string]any{"updated_at": stamp(s)} }

func stampEdge(s string) map[string]any {
	return map[string]any{"properties": map[string]any{"updated_at": stamp(s)}}
}

// platformNode is a platform whose vendor, nos and version carry one stamp, its model
// none.
func platformNode(vendor, nos, version, s string) map[string]any {
	attr := func(v string) map[string]any { return map[string]any{"value": v, "updated_at": stamp(s)} }
	return map[string]any{"__typename": "NetworkPlatform",
		"vendor": attr(vendor), "nos": attr(nos), "version": attr(version), "model": valueOf(nil)}
}

// stampedDevice is a device whose name, role, site and platform edge carry one stamp, on
// the fixture's platform, with the interfaces and artifacts given.
func stampedDevice(name, s string, interfaces []map[string]any, artifacts ...map[string]any) map[string]any {
	platform := stampEdge(s)
	platform["node"] = platformNode("nokia", "srlinux", "24.7", stampPlatform)
	var artifactEdges []map[string]any
	for _, a := range artifacts {
		artifactEdges = append(artifactEdges, map[string]any{"node": a})
	}
	return map[string]any{
		"__typename": "NetworkDevice",
		"id":         "dev-" + name,
		"name":       map[string]any{"value": name, "updated_at": stamp(s)},
		"role":       stampAttr(s),
		"site":       stampAttr(s),
		"platform":   platform,
		"interfaces": map[string]any{"edges": interfaces},
		"artifacts":  map[string]any{"edges": artifactEdges},
	}
}

// stampedInterface is one interface edge: the device's edge to it, its four attributes
// on one stamp, its link edge and its parent edge.
func stampedInterface(edge, attrs, link, parent string) map[string]any {
	e := stampEdge(edge)
	e["node"] = map[string]any{
		"__typename": "NetworkInterface",
		"name":       map[string]any{"value": "ethernet-1/1", "updated_at": stamp(attrs)},
		"iftype":     stampAttr(attrs),
		"mgmt_only":  stampAttr(attrs),
		"enabled":    stampAttr(attrs),
		"link":       stampEdge(link),
		"parent":     stampEdge(parent),
	}
	return e
}

func stampedArtifact(name, checksumStamp string) map[string]any {
	return map[string]any{
		"name":     valueOf(name),
		"checksum": map[string]any{"value": "43e8fd0c2de5f4646f74a51d34742824", "updated_at": stamp(checksumStamp)},
	}
}

// stampedLink is a link between two devices, each endpoint edge on its own stamp.
func stampedLink(a, aStamp, b, bStamp string) map[string]any {
	endpoint := func(device, s string) map[string]any {
		e := stampEdge(s)
		e["node"] = map[string]any{"__typename": "NetworkInterface",
			"device": map[string]any{"node": map[string]any{"__typename": "NetworkDevice", "name": valueOf(device)}}}
		return e
	}
	return map[string]any{"__typename": "NetworkLink",
		"endpoints": map[string]any{"edges": []map[string]any{endpoint(a, aStamp), endpoint(b, bStamp)}}}
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
	f := &fakeStamps{branch: "change-1",
		devices: []map[string]any{
			stampedDevice("n1", stampDevices, []map[string]any{stampedInterface(stampInterfaces, stampInterfaces, stampCabling, "")}),
			// 06:48:01+01:00 is 05:48:01Z: lexically the latest string, not the latest instant.
			stampedDevice("n2", "2026-10-08T06:48:01.000000+01:00", nil),
		},
		links: []map[string]any{stampedLink("n1", "2026-10-08T05:48:03.9Z", "n2", stampCabling)},
	}
	got, err := f.read(t, "")
	if err != nil {
		t.Fatal(err)
	}
	if got.Latest != "2026-10-08T05:48:03.9Z" {
		t.Errorf("Latest = %q, want the Z endpoint stamp, the latest instant, verbatim", got.Latest)
	}
	if got.Devices["n2"].Intent != "2026-10-08T05:48:03.9Z" {
		t.Errorf("n2's intent = %q: the link's endpoint edges are its intent too", got.Devices["n2"].Intent)
	}
}

// Each device's intent is the latest of its own stamps alone, and its platform is the one
// the read would project, so the registry can pick its package.
func TestStampsPerDevice(t *testing.T) {
	const roleEdit = "2026-10-16T19:35:50.104332+00:00"
	n2 := stampedDevice("n2", stampDevices, []map[string]any{stampedInterface(stampInterfaces, stampInterfaces, "", "")})
	n2["role"] = stampAttr(roleEdit)
	f := &fakeStamps{branch: "change-1", devices: []map[string]any{
		stampedDevice("n1", stampDevices, []map[string]any{stampedInterface(stampInterfaces, stampInterfaces, "", "")}),
		n2,
		stampedDevice("n3", stampDevices, nil),
	}}
	got, err := f.read(t, "")
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]string{"n1": stampInterfaces, "n2": roleEdit, "n3": stampDevices}
	for name, intent := range want {
		if got.Devices[name].Intent != intent {
			t.Errorf("%s's intent = %q, want %q", name, got.Devices[name].Intent, intent)
		}
	}
	if len(got.Devices) != 3 {
		t.Errorf("%d devices, want 3", len(got.Devices))
	}
	if p := got.Devices["n1"].Platform; p != (ctm.Platform{Vendor: "nokia", NOS: "srlinux", Version: "24.7"}) {
		t.Errorf("n1's platform = %+v", p)
	}
	if got.Latest != roleEdit {
		t.Errorf("Latest = %q, want %q", got.Latest, roleEdit)
	}
}

// Each device keeps its own id and its interfaces' ids, in the order read, by which an
// intent event names it (D-048): a link's endpoints name no third device's.
func TestStampsIDs(t *testing.T) {
	withID := func(e map[string]any, id string) map[string]any {
		e["node"].(map[string]any)["id"] = id
		return e
	}
	f := &fakeStamps{branch: "change-1", devices: []map[string]any{
		stampedDevice("n1", stampDevices, []map[string]any{
			withID(stampedInterface(stampInterfaces, stampInterfaces, "", ""), "if-n1-e1"),
			withID(stampedInterface(stampInterfaces, stampInterfaces, "", ""), "if-n1-e2"),
		}),
		stampedDevice("n2", stampDevices, nil),
	}, links: []map[string]any{stampedLink("n1", stampCabling, "n2", stampCabling)}}
	got, err := f.read(t, "")
	if err != nil {
		t.Fatal(err)
	}
	if ids := got.Devices["n1"].IDs; !slices.Equal(ids, []string{"dev-n1", "if-n1-e1", "if-n1-e2"}) {
		t.Errorf("n1's ids = %v", ids)
	}
	if ids := got.Devices["n2"].IDs; !slices.Equal(ids, []string{"dev-n2"}) {
		t.Errorf("n2's ids = %v", ids)
	}
}

// Every edge and attribute the query selects is a stamp of the device's intent: the
// interface's edge, each of its attributes, its link edge and its parent edge each move
// it alone. An unset relationship's edge stamp is null, and skipped.
func TestStampsCountEveryEdgeAndSkipANull(t *testing.T) {
	const later = "2026-10-16T19:00:00.000001+00:00"
	for _, tc := range []struct {
		name  string
		iface map[string]any
		want  string
	}{
		{"the interface's edge", stampedInterface(later, stampInterfaces, stampCabling, ""), later},
		{"its attributes", stampedInterface(stampInterfaces, later, stampCabling, ""), later},
		{"its link edge", stampedInterface(stampInterfaces, stampInterfaces, later, ""), later},
		{"its parent edge", stampedInterface(stampInterfaces, stampInterfaces, stampCabling, later), later},
		{"a null link and parent", stampedInterface(stampInterfaces, stampInterfaces, "", ""), stampInterfaces},
	} {
		t.Run(tc.name, func(t *testing.T) {
			device := stampedDevice("n1", stampDevices, []map[string]any{tc.iface})
			device["platform"].(map[string]any)["properties"] = map[string]any{"updated_at": nil}
			f := &fakeStamps{branch: "change-1", devices: []map[string]any{device}}
			got, err := f.read(t, "")
			if err != nil {
				t.Fatal(err)
			}
			if got.Devices["n1"].Intent != tc.want {
				t.Errorf("intent = %q, want %q", got.Devices["n1"].Intent, tc.want)
			}
		})
	}
}

// A platform's vendor, nos and version reach every device on it, through its artifact and
// its package (R-07): a version edited after every other stamp moves the intent of each
// device on that platform and Latest, and of no device on another platform. model reaches
// neither and is not stamped, and a null stamp is skipped.
func TestStampsPlatform(t *testing.T) {
	const edited = "2026-10-17T08:00:00.000001+00:00"
	srlinux := platformNode("nokia", "srlinux", "24.7", stampPlatform)
	srlinux["version"] = map[string]any{"value": "24.10", "updated_at": edited}
	eos := platformNode("arista", "eos", "4.32", "")
	eos["model"] = map[string]any{"value": "ceos", "updated_at": "2026-10-17T09:00:00.000000+00:00"}
	on := func(device, platform map[string]any) map[string]any {
		device["platform"].(map[string]any)["node"] = platform
		return device
	}
	f := &fakeStamps{branch: "change-1", devices: []map[string]any{
		on(stampedDevice("n1", stampDevices, nil, stampedArtifact("device-config", stampArtifacts)), srlinux),
		on(stampedDevice("n2", stampDevices, nil, stampedArtifact("device-config", stampArtifacts)), eos),
		on(stampedDevice("n3", stampDevices, nil, stampedArtifact("device-config", stampArtifacts)), srlinux),
	}}
	got, err := f.read(t, "")
	if err != nil {
		t.Fatal(err)
	}
	for name, want := range map[string]string{"n1": edited, "n2": stampDevices, "n3": edited} {
		if got.Devices[name].Intent != want {
			t.Errorf("%s's intent = %q, want %q", name, got.Devices[name].Intent, want)
		}
	}
	if got.Latest != edited {
		t.Errorf("Latest = %q, want the platform's version %q", got.Latest, edited)
	}
	if p := got.Devices["n1"].Platform; p != (ctm.Platform{Vendor: "nokia", NOS: "srlinux", Version: "24.10"}) {
		t.Errorf("n1's platform = %+v", p)
	}
	if p := got.Devices["n2"].Platform; p != (ctm.Platform{Vendor: "arista", NOS: "eos", Version: "4.32", Model: "ceos"}) {
		t.Errorf("n2's platform = %+v", p)
	}
}

// A link's endpoint edges are the intent of both the devices it joins, and of no third:
// a re-cabling of n1 and n2 names neither n3 nor anything n3 holds.
func TestStampsLinkEndpointsNameBothDevicesAndNoThird(t *testing.T) {
	const recabled = "2026-10-16T19:41:12.000300+00:00"
	f := &fakeStamps{branch: "change-1",
		devices: []map[string]any{
			stampedDevice("n1", stampDevices, nil),
			stampedDevice("n2", stampDevices, nil),
			stampedDevice("n3", stampDevices, nil),
		},
		links: []map[string]any{
			stampedLink("n1", recabled, "n2", stampCabling),
			stampedLink("n2", stampCabling, "n3", stampCabling),
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

// An artifact's checksum stamp is the artifact's and the branch's latest, never the
// device's intent: a generate that moves it does not make the device's intent newer.
func TestStampsArtifactChecksum(t *testing.T) {
	f := &fakeStamps{branch: "change-1", devices: []map[string]any{
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

// Devices and links are paged together until both are read: 150 devices are two pages,
// and every one is read.
func TestStampsReadsEveryPage(t *testing.T) {
	var devices []map[string]any
	for i := range 150 {
		devices = append(devices, stampedDevice(fmt.Sprintf("n%03d", i), stampDevices, nil))
	}
	devices[149]["site"] = stampAttr(stampArtifacts)
	f := &fakeStamps{branch: "change-1", devices: devices,
		links: []map[string]any{stampedLink("n000", stampCabling, "n001", stampCabling)}}
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
	if got.Latest != stampArtifacts {
		t.Errorf("Latest = %q: the second page's stamp was not read", got.Latest)
	}
}

// A pinned read sends its `at` verbatim and URL encoded on every page, and an unpinned
// one sends none (Constitution VI).
func TestStampsPinnedOnEveryPage(t *testing.T) {
	const at = "2026-10-08T05:48:38.544483+00:00"
	var devices []map[string]any
	for i := range 101 {
		devices = append(devices, stampedDevice(fmt.Sprintf("n%03d", i), stampDevices, nil))
	}
	f := &fakeStamps{branch: "change-1", devices: devices}
	if _, err := f.read(t, at); err != nil {
		t.Fatal(err)
	}
	if len(f.queries) != 2 {
		t.Fatalf("%d pages, want 2", len(f.queries))
	}
	for i, q := range f.queries {
		if q != "at="+url.QueryEscape(at) {
			t.Errorf("page %d sent %q, want at= the instant URL encoded", i, q)
		}
		if v, _ := url.ParseQuery(q); v.Get("at") != at {
			t.Errorf("page %d's at decoded to %q, want %q", i, v.Get("at"), at)
		}
	}

	f.queries = nil
	if _, err := f.read(t, ""); err != nil {
		t.Fatal(err)
	}
	for i, q := range f.queries {
		if q != "" {
			t.Errorf("unpinned page %d sent %q", i, q)
		}
	}
}

// A stamp that is not a time is an error naming it, the branch and the instant, and
// never the credential.
func TestStampsRefuseAStampThatIsNotATime(t *testing.T) {
	f := &fakeStamps{branch: "change-1", devices: []map[string]any{stampedDevice("n1", "yesterday", nil)}}
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
