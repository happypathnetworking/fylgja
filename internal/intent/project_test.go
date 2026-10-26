package intent_test

import (
	"encoding/json"
	"fmt"
	"net/http"
	"path/filepath"
	"reflect"
	"slices"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/stage"
)

// fixtureCTM is testdata/ctm/three-node.json, normalized.
func fixtureCTM(t *testing.T) *ctm.CTM {
	t.Helper()
	c, err := ctm.Load(filepath.Join(repoRoot(t), "testdata", "ctm", "three-node.json"))
	if err != nil {
		t.Fatal(err)
	}
	return c
}

// readScope runs stage.Read against the fake under scope, as a request naming it would.
func readScope(t *testing.T, f *fakeInfrahub, scope string) (*ctm.CTM, findings.List, error) {
	t.Helper()
	f.start(token)
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	return stage.Read(t.Context(), f.branch, "", scope, reg, "2026-09-18T00:00:00.000000Z")
}

// addReadyArtifact gives a device its configuration, Ready, its bytes in the object store.
func (f *fakeInfrahub) addReadyArtifact(device string) {
	body := sentinelContent(device)
	id := "storage-" + device
	f.artifacts[device] = []fakeArtifact{{Name: "device-config", Status: intent.StatusReady, ContentType: "text/plain",
		Checksum: md5Hex(body), StorageID: id, DefinitionName: "device-config"}}
	f.objects[id] = fakeObject{Status: http.StatusOK, Body: body}
}

// The three-node fixture, seeded in the library's kinds, reads to
// testdata/ctm/three-node.json in everything but the envelope's instant and hash: each
// device by its tag, each port physical, each cable a link, the platform the package its
// pair matches, and the envelope's scope, mapping and three fidelity rows the fixture's
// (US1 scenario 1). The devices are asked for by the scope's tag with no status filter,
// and the ports by the ids of the devices read and no others.
func TestReadIsTheFixture(t *testing.T) {
	f := newFakeInfrahub(t)

	c, list, err := readFake(t, f)

	if err != nil {
		t.Fatal(err)
	}
	if len(list) != 0 || c == nil {
		t.Fatalf("findings %v; want a clean read", list)
	}
	want := fixtureCTM(t)
	if !reflect.DeepEqual(c.Devices, want.Devices) {
		got, _ := json.MarshalIndent(c.Devices, "", "  ")
		t.Errorf("devices differ from the fixture's:\n%s", got)
	}
	if !reflect.DeepEqual(c.Links, want.Links) {
		t.Errorf("links %+v, want the fixture's %+v", c.Links, want.Links)
	}
	e, w := c.Envelope, want.Envelope
	if e.Branch != w.Branch || e.Scope != "tag:fylgja" || e.Mapping != w.Mapping || !reflect.DeepEqual(e.Fidelity, w.Fidelity) {
		t.Errorf("envelope %+v; want branch, scope, mapping and fidelity as the fixture's %+v", e, w)
	}
	if e.Mapping != (ctm.Mapping{Reader: "infrahub-dcim", Model: "opsmill/schema-library", Version: "26336e9"}) || len(e.Fidelity) != 3 {
		t.Errorf("mapping %+v, %d fidelity rows; want the library's and three", e.Mapping, len(e.Fidelity))
	}

	devices := f.graphql("Devices")
	if len(devices) != 1 || devices[0].Variables["tag"] != "fylgja" ||
		!strings.Contains(devices[0].Query, "DcimDevice(tags__name__value: $tag, limit: $limit, offset: $offset) {") {
		t.Errorf("the device query %+v; want one, by the tag fylgja and no status filter", devices)
	}
	ports := f.graphql("Ports")
	if len(ports) != 1 || !reflect.DeepEqual(ports[0].Variables["devices"], []any{"id-n1", "id-n2", "id-n3"}) ||
		!strings.Contains(ports[0].Query, "InterfacePhysical(device__ids: $devices, limit: $limit, offset: $offset) {") {
		t.Errorf("the port query %+v; want one, by the three devices' ids", ports)
	}
}

// A read asks for nothing outside its scope and nothing the mapping does not name: an
// untagged console server, a device tagged otherwise, and a tagged device's virtual
// interfaces and addresses are never requested or read (US1 scenario 3; FR-002, FR-003,
// FR-010). The device query reads no interfaces, and the port query is the physical root,
// filtered by the ids of the devices read.
func TestReadAsksForNothingOutsideItsScope(t *testing.T) {
	f := newFakeInfrahub(t)
	f.addDevice("cs1", "Opengear", "Console OS", nil, "port1")
	f.addDevice("o1", "Nokia", "SR Linux", []string{"other"}, "ethernet-1/1")
	f.device("n1").Virtual = []string{"lo0", "irb0"}

	c, list, err := readFake(t, f)

	if err != nil {
		t.Fatal(err)
	}
	if list.Rejected() || c == nil {
		t.Fatalf("findings %v; want a clean read", list)
	}
	if c.Device("cs1") != nil || c.Device("o1") != nil {
		t.Error("a device outside the scope was read")
	}
	if n1 := c.Device("n1"); n1.Interface("lo0") != nil || n1.Interface("irb0") != nil || len(n1.Interfaces) != 3 {
		t.Errorf("n1's interfaces %+v; want its three ports alone", n1.Interfaces)
	}
	ports := f.graphql("Ports")
	if len(ports) != 1 || slices.Contains(ports[0].Variables["devices"].([]any), any("id-cs1")) ||
		slices.Contains(ports[0].Variables["devices"].([]any), any("id-o1")) {
		t.Errorf("the port query %+v asked for a device outside the scope", ports)
	}
	for _, r := range append(f.graphql("Devices"), ports...) {
		for _, never := range []string{"InterfaceVirtual", "interfaces", "address", "description", "location", "serial", "site"} {
			if strings.Contains(r.Query, never) {
				t.Errorf("operation %s asks for %q, which the mapping never reads", r.Operation, never)
			}
		}
	}
}

// A port is the management port by its role, and enabled unless its status is disabled; a
// device's own status is never a filter, so a device under maintenance is read; and a
// device with no physical interface is a device with no port (FR-002, FR-004, FR-005).
func TestReadProjectsEachPort(t *testing.T) {
	f := newFakeInfrahub(t)
	_, p := f.port("n2:ethernet-1/2")
	p.Status = "disabled"
	_, p = f.port("n3:ethernet-1/1")
	p.Status = "maintenance"
	f.device("n2").Status = "maintenance"
	f.addDevice("n4", "Nokia", "SR Linux", []string{fixtureTag})
	f.addReadyArtifact("n4")

	c, list, err := readFake(t, f)

	if err != nil {
		t.Fatal(err)
	}
	if list.Rejected() || c == nil {
		t.Fatalf("findings %v; want a clean read", list)
	}
	enabled := func(device, port string) bool { return *c.Device(device).Interface(port).Enabled }
	if enabled("n2", "ethernet-1/2") || !enabled("n3", "ethernet-1/1") || !enabled("n1", "ethernet-1/1") {
		t.Error("a port's enabled is not its status other than disabled")
	}
	if mgmt := c.Device("n1").Interface("mgmt0"); !mgmt.MgmtOnly || c.Device("n1").Interface("ethernet-1/1").MgmtOnly {
		t.Error("the management port is not the port whose role is management")
	}
	if c.Device("n2") == nil {
		t.Error("a device under maintenance was not read")
	}
	if n4 := c.Device("n4"); n4 == nil || len(n4.Interfaces) != 0 || n4.Platform.Package != "nokia_srlinux" || n4.Artifact == nil {
		t.Errorf("n4 %+v; want it read with no port, its package and its artifact", n4)
	}
}

// A tagged device whose platform no package can be chosen for refuses the read, each one
// in one pass and in name order, with no CTM (US2 scenario 5; FR-014): no platform, a
// platform with no manufacturer, and a pair no package names exactly, its letter case and
// spacing included. None of them is also refused for its artifact, and the read is not
// otherwise cut short: a fourth device's artifact is still checked in the same pass.
func TestReadRefusesEveryDeviceWithoutAPackage(t *testing.T) {
	f := newFakeInfrahub(t)
	n1, n2, n3 := f.device("n1"), f.device("n2"), f.device("n3")
	n1.Manufacturer, n1.Platform = "nokia", "SR-Linux"
	n2.Manufacturer, n2.Platform = "", ""
	n3.Manufacturer, n3.Platform = "", "Orphan OS"
	f.addDevice("n4", "Nokia", "SR Linux", []string{fixtureTag})

	c, list, err := readFake(t, f)

	if err != nil {
		t.Fatal(err)
	}
	if c != nil {
		t.Error("a read refused for its platforms produced a CTM")
	}
	want := findings.List{
		{Severity: findings.Rejection, Rule: findings.RulePlatformUnmatched, Object: "n1",
			Message: `device n1: manufacturer "nokia", platform "SR-Linux"; the packages match: arista_eos [Arista / EOS], nokia_srlinux [Nokia / SR Linux]`},
		{Severity: findings.Rejection, Rule: findings.RulePlatformMissing, Object: "n2",
			Message: "device n2 carries no platform; its support package is the one whose matches name its platform and manufacturer"},
		{Severity: findings.Rejection, Rule: findings.RulePlatformMissing, Object: "n3",
			Message: `device n3 carries platform "Orphan OS" with no manufacturer; its support package is the one whose matches name both`},
		{Severity: findings.Rejection, Rule: findings.RuleArtifactMissing, Object: "n4",
			Message: "device n4 has no artifact named device-config on branch fylgja-fixture"},
	}
	if !reflect.DeepEqual(list, want) {
		t.Errorf("findings\n%v\nwant\n%v", list, want)
	}
	for _, d := range []string{"n1", "n2", "n3"} {
		if n := f.count("/api/storage/object/storage-" + d); n != 0 {
			t.Errorf("device %s, refused for its platform, had its artifact fetched", d)
		}
	}
}

// A scope that selects no device refuses the read with one finding naming the scope and
// the branch, and asks for no port (FR-015).
func TestScopeSelectingNothingIsRefused(t *testing.T) {
	f := newFakeInfrahub(t)

	c, list, err := readScope(t, f, "tag:nothing")

	if err != nil {
		t.Fatal(err)
	}
	want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleScopeEmpty, Object: "tag:nothing",
		Message: "scope tag:nothing selects no device on branch fylgja-fixture"}
	if c != nil || len(list) != 1 || list[0] != want {
		t.Fatalf("CTM %v, findings %+v; want none and exactly %+v", c != nil, list, want)
	}
	if devices := f.graphql("Devices"); len(devices) != 1 || devices[0].Variables["tag"] != "nothing" {
		t.Errorf("the device query %+v; want one, by the tag nothing", devices)
	}
	if n := len(f.graphql("Ports")); n != 0 {
		t.Errorf("a scope selecting nothing asked for ports %d times", n)
	}
}

// Devices and ports are paged by a hundred, and ports are asked for a hundred devices'
// ids at a time: a scope of 150 devices with two ports each reads every device and every
// port, the first hundred devices' 200 ports in two pages.
func TestReadPagesDevicesAndPorts(t *testing.T) {
	f := newFakeInfrahub(t)
	f.devices, f.cables, f.artifacts, f.objects = nil, map[string]*fakeCable{}, map[string][]fakeArtifact{}, map[string]fakeObject{}
	for i := range 150 {
		name := fmt.Sprintf("d%03d", i)
		f.addDevice(name, "Nokia", "SR Linux", []string{fixtureTag}, "ethernet-1/1", "ethernet-1/2")
		f.addReadyArtifact(name)
	}

	c, list, err := readFake(t, f)

	if err != nil {
		t.Fatal(err)
	}
	if list.Rejected() || c == nil || len(c.Devices) != 150 {
		t.Fatalf("findings %v, CTM of %d devices; want 150 read clean", list, len(c.Devices))
	}
	for _, d := range c.Devices {
		if len(d.Interfaces) != 2 {
			t.Errorf("device %s read with %d ports, want 2", d.Name, len(d.Interfaces))
		}
	}
	ports := f.graphql("Ports")
	if len(ports) != 3 {
		t.Fatalf("%d port queries; want two pages for the first hundred devices' ids and one for the rest", len(ports))
	}
	if n := len(ports[0].Variables["devices"].([]any)); n != 100 || ports[1].Variables["offset"] != float64(100) {
		t.Errorf("the first port queries %+v; want a hundred ids, then their second page", ports[:2])
	}
	if n := len(ports[2].Variables["devices"].([]any)); n != 50 {
		t.Errorf("the last port query asked for %d devices' ids, want 50", n)
	}
	if n := len(f.graphql("Devices")); n != 2 {
		t.Errorf("%d device queries, want two pages", n)
	}
}
