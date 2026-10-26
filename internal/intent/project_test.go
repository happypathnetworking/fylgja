package intent_test

import (
	"encoding/json"
	"fmt"
	"net/http"
	"path/filepath"
	"reflect"
	"regexp"
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

// The device's own role, status and device type are never read (FR-010): the Devices
// operation selects none of them on the DcimDevice node, which the never-list above cannot
// say, since the Ports operation reads a port's role and status and an artifact's status
// is selected inside the device's artifacts. The device's own fields are the top level of
// DcimDevice.edges.node's selection, ArtifactFields' spread expanded to its top level.
func TestDevicesReadsNotTheDevicesRoleStatusOrType(t *testing.T) {
	f := newFakeInfrahub(t)
	if _, list, err := readFake(t, f); err != nil || list.Rejected() {
		t.Fatalf("findings %v, %v; want a clean read", list, err)
	}
	devices := f.graphql("Devices")
	if len(devices) == 0 {
		t.Fatal("no Devices operation was sent")
	}
	for _, r := range devices {
		fields := deviceFields(t, r.Query)
		for _, want := range []string{"id", "name", "platform", "artifacts"} {
			if !slices.Contains(fields, want) {
				t.Fatalf("the device's fields %v lack %q; the walk is reading the wrong selection", fields, want)
			}
		}
		for _, never := range []string{"role", "status", "device_type"} {
			if slices.Contains(fields, never) {
				t.Errorf("the Devices operation selects the device's %q (fields %v), which the mapping never reads", never, fields)
			}
		}
	}
}

// deviceFields is the names a Devices query selects on the DcimDevice node itself: the top
// level of DcimDevice.edges.node's selection set, each fragment spread's and inline
// fragment's own top level included, every argument list and deeper selection skipped.
func deviceFields(t *testing.T, query string) []string {
	t.Helper()
	tokens := regexp.MustCompile(`\.\.\.|[A-Za-z_][A-Za-z0-9_]*|[{}()]`).FindAllString(query, -1)
	closeOf := func(i int) int {
		depth := 0
		for j := i; j < len(tokens); j++ {
			switch tokens[j] {
			case "{", "(":
				depth++
			case "}", ")":
				if depth--; depth == 0 {
					return j
				}
			}
		}
		t.Fatalf("unbalanced query:\n%s", query)
		return 0
	}
	// setOf is the index of the "{" opening the selection of the field at i, past its
	// arguments.
	setOf := func(i int) int {
		j := i + 1
		if tokens[j] == "(" {
			j = closeOf(j) + 1
		}
		if tokens[j] != "{" {
			t.Fatalf("%s selects nothing in:\n%s", tokens[i], query)
		}
		return j
	}
	fragment := func(name string) int {
		for k := 0; k+4 < len(tokens); k++ {
			if tokens[k] == "fragment" && tokens[k+1] == name {
				return k + 4
			}
		}
		t.Fatalf("no fragment %s in:\n%s", name, query)
		return 0
	}
	var top func(open int) []string
	top = func(open int) []string {
		var out []string
		end := closeOf(open)
		for j := open + 1; j < end; j++ {
			switch tok := tokens[j]; {
			case tok == "(" || tok == "{":
				j = closeOf(j)
			case tok == "..." && tokens[j+1] == "on":
				out = append(out, top(j+3)...)
				j = closeOf(j + 3)
			case tok == "...":
				out = append(out, top(fragment(tokens[j+1]))...)
				j++
			default:
				out = append(out, tok)
			}
		}
		return out
	}
	// child is the "{" opening the selection of the field name at the top level of open's.
	child := func(open int, name string) int {
		depth := 0
		for j := open + 1; j < closeOf(open); j++ {
			switch tokens[j] {
			case "{", "(":
				depth++
			case "}", ")":
				depth--
			default:
				if depth == 0 && tokens[j] == name {
					return setOf(j)
				}
			}
		}
		t.Fatalf("no %s in:\n%s", name, query)
		return 0
	}
	root := slices.Index(tokens, "DcimDevice")
	if root < 0 {
		t.Fatalf("no DcimDevice in:\n%s", query)
	}
	return top(child(child(setOf(root), "edges"), "node"))
}

// A device with two management ports (spec Edge Cases): the read marks both mgmt_only, each
// port's role being management, and the compile keeps the first by name and omits the
// second by name, omit.mgmt.extra, as the compiler's
// TestSecondManagementPortIsOmittedAndRecorded holds for a hand-built CTM (FR-004).
func TestReadOfTwoManagementPortsCompilesOne(t *testing.T) {
	f := newFakeInfrahub(t)
	n1 := f.device("n1")
	n1.Ports = append(n1.Ports, &fakePort{ID: "n1:mgmt1", Name: "mgmt1", Role: "management"})

	c, list, err := readFake(t, f)

	if err != nil {
		t.Fatal(err)
	}
	if list.Rejected() || c == nil {
		t.Fatalf("findings %v; want a clean read", list)
	}
	for _, name := range []string{"mgmt0", "mgmt1"} {
		if in := c.Device("n1").Interface(name); in == nil || !in.MgmtOnly {
			t.Errorf("n1's %s %+v; want it read mgmt_only", name, in)
		}
	}
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	files, id, list := stage.Compile(c, reg)
	if files == nil || id == "" || list.Rejected() {
		t.Fatalf("the compile refused: %v", list)
	}
	var extra []findings.Finding
	for _, f := range list {
		if f.Rule == findings.RuleOmitMgmtExtra {
			extra = append(extra, f)
		}
	}
	want := findings.Finding{Severity: findings.Info, Rule: findings.RuleOmitMgmtExtra, Object: "n1:mgmt1",
		Message: "one management connection per node"}
	if len(extra) != 1 || extra[0].Severity != want.Severity || extra[0].Object != want.Object || extra[0].Message != want.Message {
		t.Errorf("omit.mgmt.extra findings %+v; want one, %+v", extra, want)
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
// spacing included, and a manufacturer whose name is empty among them, told from none
// (T115). None of them is also refused for its artifact, and the read is not otherwise cut
// short: a fourth device's artifact is still checked in the same pass.
func TestReadRefusesEveryDeviceWithoutAPackage(t *testing.T) {
	f := newFakeInfrahub(t)
	n1, n2, n3 := f.device("n1"), f.device("n2"), f.device("n3")
	n1.Manufacturer, n1.Platform = "nokia", "SR-Linux"
	n2.Manufacturer, n2.Platform = "", ""
	n3.Manufacturer, n3.Platform = "", "Orphan OS"
	f.addDevice("n4", "Nokia", "SR Linux", []string{fixtureTag})
	f.addDevice("n5", "", "SR Linux", []string{fixtureTag}).EmptyManufacturer = true

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
		{Severity: findings.Rejection, Rule: findings.RulePlatformUnmatched, Object: "n5",
			Message: `device n5: manufacturer "", platform "SR Linux"; the packages match: arista_eos [Arista / EOS], nokia_srlinux [Nokia / SR Linux]`},
		{Severity: findings.Rejection, Rule: findings.RuleArtifactMissing, Object: "n4",
			Message: "device n4 has no artifact named device-config on branch fylgja-fixture"},
	}
	if !reflect.DeepEqual(list, want) {
		t.Errorf("findings\n%v\nwant\n%v", list, want)
	}
	for _, d := range []string{"n1", "n2", "n3", "n5"} {
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
