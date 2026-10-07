package compiler

import (
	"encoding/json"
	"maps"
	"slices"
	"strings"
	"testing"

	"gopkg.in/yaml.v3"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// The mixed twin, asserted by name. One
// bundle, three nodes, two shipped packages: the golden holds its bytes, and this says
// what each of them means, so a regenerated golden that moved a decision fails here even
// when it matches itself — as the lossy case's does.
//
// Every per-node value below comes from that node's own package. Nothing in the compiler
// knows which package it is holding: the ports and node names are its profile's, the
// absent startup-config and the manifest's `via` are its config.bootstrap_via, the image
// and the kind are its image block, and the forwarding entry is its fidelity. That is
// what makes a second platform a file under psp/ and nothing else (Constitution II).

type mixedBundle struct {
	files map[string][]byte
	m     Manifest
}

func compileMixed(t *testing.T) mixedBundle {
	t.Helper()
	files := compileFixture(t, "testdata/ctm/mixed.json")
	var m Manifest
	if err := json.Unmarshal(files[ManifestFile], &m); err != nil {
		t.Fatal(err)
	}
	return mixedBundle{files: files, m: m}
}

func (b mixedBundle) node(t *testing.T, name string) ManifestNode {
	t.Helper()
	for _, n := range b.m.Nodes {
		if n.Name == name {
			return n
		}
	}
	t.Fatalf("no manifest node %s", name)
	return ManifestNode{}
}

func (b mixedBundle) mappingRow(t *testing.T, object string) MappingRow {
	t.Helper()
	for _, r := range b.m.Mapping {
		if r.Device+":"+r.Interface == object {
			return r
		}
	}
	t.Fatalf("no mapping row for %s", object)
	return MappingRow{}
}

// TestGoldenMixed holds the mixed bundle's bytes; the tests below say what they mean.
func TestGoldenMixed(t *testing.T) {
	files := compileFixture(t, "testdata/ctm/mixed.json")
	if !checkGolden(t, "mixed", files) {
		return
	}
	if id := bundle.ID(files); id != goldenMixedID {
		t.Errorf("bundle_id = %s, want %s", id, goldenMixedID)
	}
	checkInvariants(t, "testdata/ctm/mixed.json", files)
}

// Each node is deployed as its own package says: its image under its container kind, and
// a startup-config named in the topology only where the package applies the bootstrap
// that way. A node whose package says `push` has none, because on such a kind the file
// would be the whole configuration rather than an overlay; the manifest still names
// the file and says who applies it, which is the only way a reader of the topology alone
// could tell that node from one with no bootstrap at all.
func TestMixedTopologyNamesAStartupConfigOnlyWhereTheBootstrapIsApplied(t *testing.T) {
	b := compileMixed(t)
	var topo struct {
		Name     string `yaml:"name"`
		Topology struct {
			Nodes map[string]struct {
				Kind          string `yaml:"kind"`
				Image         string `yaml:"image"`
				StartupConfig string `yaml:"startup-config"`
			} `yaml:"nodes"`
		} `yaml:"topology"`
	}
	if err := yaml.Unmarshal(b.files[TopologyFile], &topo); err != nil {
		t.Fatal(err)
	}
	if topo.Name != LabName {
		t.Errorf("topology names the lab %q, want %q", topo.Name, LabName)
	}
	for name, want := range map[string]struct{ kind, image, startup string }{
		"e1": {"ceos", "ceos:4.32.0.2F", ""},
		"e2": {"ceos", "ceos:4.32.0.2F", ""},
		"s1": {"nokia_srlinux", "ghcr.io/nokia/srlinux:24.7.1", "configs/s1.cli"},
	} {
		got := topo.Topology.Nodes[name]
		if got.Kind != want.kind || got.Image != want.image || got.StartupConfig != want.startup {
			t.Errorf("topology node %s = kind %s, image %s, startup-config %q; want %s, %s, %q",
				name, got.Kind, got.Image, got.StartupConfig, want.kind, want.image, want.startup)
		}
	}
}

// The manifest carries each node's package, image and bootstrap, both `via` values among
// them: one bundle, two answers, neither asserted over the other's nodes.
func TestMixedManifestCarriesEachNodesOwnPackage(t *testing.T) {
	b := compileMixed(t)
	for _, c := range []struct {
		node, pspID, image, via string
	}{
		{"e1", "arista_eos", "ceos:4.32.0.2F", psp.BootstrapViaPush},
		{"e2", "arista_eos", "ceos:4.32.0.2F", psp.BootstrapViaPush},
		{"s1", "nokia_srlinux", "ghcr.io/nokia/srlinux:24.7.1", psp.BootstrapViaStartupConfig},
	} {
		n := b.node(t, c.node)
		if n.PSP.ID != c.pspID || n.PSP.Source != psp.OriginEmbedded || n.Image != c.image {
			t.Errorf("node %s psp %+v image %s, want %s (embedded) and %s", c.node, n.PSP, n.Image, c.pspID, c.image)
		}
		if n.Bootstrap.Via != c.via || n.Bootstrap.File != "configs/"+c.node+".cli" {
			t.Errorf("node %s bootstrap %+v, want configs/%s.cli via %s", c.node, n.Bootstrap, c.node, c.via)
		}
	}
	vias := map[string]bool{}
	for _, n := range b.m.Nodes {
		vias[n.Bootstrap.Via] = true
	}
	if len(vias) != 2 {
		t.Errorf("the bundle's nodes use %v; a mixed twin carries both bootstrap routes", vias)
	}
}

// Each node's bootstrap file is its own package's lines under its own comment marker, and
// nothing from intent (Constitution IV). The marker is load-bearing on a package that
// sends its bootstrap through the push: every line of the file is sent as a command, and
// a node that reads `!` as a comment refuses `#` at token 0.
func TestMixedBootstrapIsEachPackagesOwn(t *testing.T) {
	b := compileMixed(t)
	for node, want := range map[string]string{
		"e1": "! Generated by Fylgja: platform bootstrap only, nothing from intent.\nhostname e1\n",
		"e2": "! Generated by Fylgja: platform bootstrap only, nothing from intent.\nhostname e2\n",
		"s1": "# Generated by Fylgja: platform bootstrap only, nothing from intent.\n" +
			"set / system name host-name s1\n" +
			"set / interface ethernet-1/1 admin-state enable\n" +
			"set / interface ethernet-1/2 admin-state enable\n" +
			"set / system lldp admin-state enable\n",
	} {
		if got := string(b.files["configs/"+node+".cli"]); got != want {
			t.Errorf("configs/%s.cli:\n got  %q\n want %q", node, got, want)
		}
	}
}

// Three links, one of each kind this fixture is built to exercise: across the two
// platforms on a plain port, between two nodes of the second platform on a modular port,
// and across the platforms again on a breakout lane. Each end is the port its own
// profile rendered, never the production name.
func TestMixedLinksCableEachEndAsItsProfileRendersIt(t *testing.T) {
	b := compileMixed(t)
	want := []CabledLink{
		{ID: "e1:Ethernet1|s1:ethernet-1/1", A: NodePort{Node: "e1", Port: "eth1"}, B: NodePort{Node: "s1", Port: "e1-1"}},
		{ID: "e1:Ethernet2/1|e2:Ethernet1", A: NodePort{Node: "e1", Port: "eth2_1"}, B: NodePort{Node: "e2", Port: "eth1"}},
		{ID: "e2:Ethernet3/1/1|s1:ethernet-1/2", A: NodePort{Node: "e2", Port: "eth3_1_1"}, B: NodePort{Node: "s1", Port: "e1-2"}},
	}
	if len(b.m.Links) != len(want) {
		t.Fatalf("cabled %d links, want %d", len(b.m.Links), len(want))
	}
	for i, l := range want {
		if b.m.Links[i] != l {
			t.Errorf("link %d = %+v, want %+v", i, b.m.Links[i], l)
		}
	}
}

// Every row carries the node's own name for its port, and a row the twin gives no port
// carries null — on both platforms, whatever each calls its loopback (bundle "3"; D-025).
func TestMixedRowsCarryEveryNodeName(t *testing.T) {
	b := compileMixed(t)
	for object, want := range map[string]string{
		"e1:Ethernet1":     `port eth1 node_name "Ethernet1" cabled`,
		"e1:Ethernet2/1":   `port eth2_1 node_name "Ethernet2/1" cabled`,
		"e1:Loopback0":     `port null node_name null configured-not-cabled`,
		"e1:Management1":   `port eth0 node_name "Management0" management`,
		"e2:Ethernet3/1/1": `port eth3_1_1 node_name "Ethernet3/1/1" cabled`,
		"e2:Loopback0":     `port null node_name null configured-not-cabled`,
		"s1:ethernet-1/1":  `port e1-1 node_name "ethernet-1/1" cabled`,
		"s1:lo0":           `port null node_name null configured-not-cabled`,
		"s1:mgmt0":         `port mgmt0 node_name "mgmt0" management`,
	} {
		if got := describe(b.mappingRow(t, object)); got != want {
			t.Errorf("%s: %s, want %s", object, got, want)
		}
	}
}

// The fidelity manifest states one forwarding answer per package and attributes each,
// which is what the bundle "3" bump was for: before it, a twin whose platforms disagreed
// was refused outright rather than carry both (D-025). Nothing here is lossy: neither
// profile drops anything, and the list is present and empty.
func TestMixedFidelityCarriesBothPlatforms(t *testing.T) {
	b := compileMixed(t)
	want := map[string]string{"arista_eos": "hardware", "nokia_srlinux": "hardware"}
	if !maps.Equal(b.m.Fidelity.ProductionForwarding, want) {
		t.Errorf("production_forwarding = %v, want %v", b.m.Fidelity.ProductionForwarding, want)
	}
	if len(b.m.Fidelity.Lossy) != 0 {
		t.Errorf("fidelity.lossy = %v, want empty", b.m.Fidelity.Lossy)
	}
	if len(b.m.Omissions) != 0 || len(b.m.Fidelity.Omitted) != 0 {
		t.Errorf("omissions %v and fidelity.omitted %v, want neither: every interface is represented",
			b.m.Omissions, b.m.Fidelity.Omitted)
	}
	// Every approximation is attributed to the package that asserts it, so two platforms
	// making the same claim both appear.
	platforms := map[string]int{}
	for _, a := range b.m.Fidelity.Approximations {
		for _, id := range []string{"arista_eos", "nokia_srlinux"} {
			if len(a) > len(id) && a[:len(id)+2] == id+": " {
				platforms[id]++
			}
		}
	}
	if platforms["arista_eos"] == 0 || platforms["nokia_srlinux"] == 0 {
		t.Errorf("approximations %v are not attributed to both packages", b.m.Fidelity.Approximations)
	}
}

// Each node's artifact reaches the bundle unchanged, under the name its own package gives
// it: one artifact name serves both platforms here, and the bytes are each device's own
// (M5, D-028).
func TestMixedArtifactsReachTheBundleUnchanged(t *testing.T) {
	b := compileMixed(t)
	c := loadFixture(t, "testdata/ctm/mixed.json")
	for _, d := range c.Devices {
		file := "configs/" + d.Name + ".device-config"
		if got := string(b.files[file]); got != d.Artifact.Content {
			t.Errorf("%s:\n got  %q\n want %q", file, got, d.Artifact.Content)
		}
		a := b.node(t, d.Name).Artifact
		if a == nil || a.Name != d.Artifact.Name || a.Checksum != d.Artifact.Checksum ||
			a.Size != len(d.Artifact.Content) || a.File != file {
			t.Errorf("node %s artifact entry %+v, want %s at %s with checksum %s and size %d",
				d.Name, a, d.Artifact.Name, file, d.Artifact.Checksum, len(d.Artifact.Content))
		}
	}
}

// What a mixed read tells the operator about the artifacts, and all it tells them.
// Every production name in this intent is a name its node carries, with one
// exception on each node of the second platform: the management interface, which intent
// calls Management1 and whose port the twin's node calls Management0, because the rule
// applies to whatever interface intent marked out-of-band rather than to a name (D-003).
// The artifact names it in the comment line the template writes for it, so the warning is
// true and the line is pushed as production wrote it — Fylgja configures no management
// (D-009). Nothing else warns: no interface is omitted and no data port is renamed.
func TestMixedWarnsOnlyAboutTheManagementNames(t *testing.T) {
	files, list := Compile(loadFixture(t, "testdata/ctm/mixed.json"), embeddedRegistry(t))
	if list.Rejected() || files == nil {
		t.Fatalf("the mixed fixture was refused: %v", list)
	}
	const message = "artifact device-config names interface Management1 at line 12, " +
		"which the node calls Management0; the line is pushed as production wrote it"
	var got []string
	for _, f := range list {
		got = append(got, string(f.Severity)+" "+f.Rule+" "+f.Object+": "+f.Message)
	}
	want := []string{
		"warning " + findings.RuleArtifactInterfaceUnrepresented + " e1:Management1: " + message,
		"warning " + findings.RuleArtifactInterfaceUnrepresented + " e2:Management1: " + message,
	}
	if !slices.Equal(got, want) {
		t.Errorf("the mixed compile reported\n%s\nwant\n%s", strings.Join(got, "\n"), strings.Join(want, "\n"))
	}
}

// embeddedRegistry is the shipped packages alone, as every command loads them.
func embeddedRegistry(t *testing.T) *psp.Registry {
	t.Helper()
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	return reg
}
