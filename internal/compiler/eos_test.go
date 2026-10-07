// An external test package: internal/validate imports the compiler, so a test that runs
// both callers on one intent cannot live inside it.
package compiler_test

import (
	"encoding/json"
	"maps"
	"strings"
	"testing"

	"gopkg.in/yaml.v3"

	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/psp"
	"github.com/happypathnetworking/fylgja/internal/validate"
)

// embeddedRegistry is the shipped packages alone, as every command loads them without
// --psp-dir: the EOS package is one of them from M7 on, so nothing has to be overridden
// for an EOS twin to compile.
func embeddedRegistry(t *testing.T) *psp.Registry {
	t.Helper()
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	if _, ok := reg.Lookup("eos"); !ok {
		t.Fatalf("no shipped package answers for nos eos; platforms: %v", reg.Platforms())
	}
	return reg
}

// eosArtifact is what Infrahub renders for an EOS device, in the shape the template
// gives it: `!` comments, since `#` is not a comment on this platform. The bytes matter
// only in that the compiler writes them unchanged and the manifest records their hash.
func eosArtifact(device string) *ctm.Artifact {
	content := "! fylgja\nhostname " + device + "\n"
	return &ctm.Artifact{
		Name:        "device-config",
		ContentType: "text/plain",
		Checksum:    ctm.ChecksumOf(content),
		Content:     content,
	}
}

// eosOnlyCTM is two EOS devices and one link between them: e1 carries a name of each of
// the profile's three data shapes plus its management interface, e2 the far end and a
// loopback no rule matches. Built here rather than kept on disk, because nothing about
// it is a fixture anyone else reads: it tests the EOS package on its own, and the mixed
// twin, which does have a golden, tests two platforms in one twin.
func eosOnlyCTM() *ctm.CTM {
	return &ctm.CTM{
		CTMVersion: ctm.Version,
		Envelope: ctm.Envelope{
			Branch:          "fylgja-fixture",
			ObservedAt:      "2026-09-20T12:00:00.000000Z",
			SchemaHash:      "fixture",
			ContractVersion: ctm.ContractVersion,
		},
		Devices: []ctm.Device{
			{
				Name:     "e1",
				Platform: ctm.Platform{Vendor: "arista", NOS: "eos", Version: "4.32"},
				Interfaces: []ctm.Interface{
					{Name: "Ethernet1", Iftype: ctm.IftypePhysical, Link: "e1-e2"},
					{Name: "Ethernet2/1", Iftype: ctm.IftypePhysical},
					{Name: "Ethernet3/1/1", Iftype: ctm.IftypePhysical},
					{Name: "Management1", Iftype: ctm.IftypePhysical, MgmtOnly: true},
				},
				Artifact: eosArtifact("e1"),
			},
			{
				Name:     "e2",
				Platform: ctm.Platform{Vendor: "arista", NOS: "eos", Version: "4.32"},
				Interfaces: []ctm.Interface{
					{Name: "Ethernet1", Iftype: ctm.IftypePhysical, Link: "e1-e2"},
					{Name: "Loopback0", Iftype: ctm.IftypeLoopback},
					{Name: "Management1", Iftype: ctm.IftypePhysical, MgmtOnly: true},
				},
				Artifact: eosArtifact("e2"),
			},
		},
		Links: []ctm.Link{
			{ID: "e1-e2", Endpoints: []ctm.Endpoint{
				{Device: "e1", Interface: "Ethernet1"},
				{Device: "e2", Interface: "Ethernet1"},
			}},
		},
	}
}

// A twin of EOS devices alone compiles from the shipped package, and every part of the
// bundle that the second platform touches says what the package says.
//
// Nothing here is EOS-specific in the compiler: the ports and node names come from the
// profile's rules, the absent startup-config and the manifest's `via` come from
// config.bootstrap_via, and the forwarding entry comes from the package's fidelity. A
// second platform is data, and this test is what says so.
func TestEOSOnlyTwinCompilesFromTheShippedPackage(t *testing.T) {
	reg := embeddedRegistry(t)
	files, list := compiler.Compile(eosOnlyCTM(), reg)
	if list.Rejected() {
		t.Fatalf("an EOS-only twin was refused: %v", list)
	}
	if files == nil {
		t.Fatal("no files returned")
	}

	var m compiler.Manifest
	if err := json.Unmarshal(files[compiler.ManifestFile], &m); err != nil {
		t.Fatal(err)
	}

	// Every production name of e1 landed on the port and the node name its rule
	// renders.
	// The three data shapes keep the production name, since the node carries it
	// unchanged; management is the one row where the two differ, because the rule
	// applies to whatever interface intent marked mgmt_only (D-003).
	type row struct{ port, nodeName, disposition string }
	got := map[string]row{}
	for _, r := range m.Mapping {
		if r.Device != "e1" {
			continue
		}
		got[r.Interface] = row{deref(r.Port), deref(r.NodeName), string(r.Disposition)}
	}
	want := map[string]row{
		"Ethernet1":     {"eth1", "Ethernet1", "cabled"},
		"Ethernet2/1":   {"eth2_1", "Ethernet2/1", "configured-not-cabled"},
		"Ethernet3/1/1": {"eth3_1_1", "Ethernet3/1/1", "configured-not-cabled"},
		"Management1":   {"eth0", "Management0", "management"},
	}
	if !maps.Equal(got, want) {
		t.Errorf("e1's rows:\n got  %v\n want %v", got, want)
	}

	// The bootstrap is the one line the package declares, under the generated header:
	// every Ethernet port is up and LLDP runs before Fylgja touches the node, so there
	// is nothing per-port to write.
	//
	// The header is written under the package's own comment marker, and that matters
	// here rather than being cosmetic: this package's bootstrap reaches the node through
	// the push, so every line of this file is sent as a command, and this node reads
	// `!` as a comment and refuses `#` at token 0. A `#` here would be refused at
	// bootstrap line 1, and under an atomic commit nothing would land.
	const wantBootstrap = "! Generated by Fylgja: platform bootstrap only, nothing from intent.\nhostname e1\n"
	if got := string(files["configs/e1.cli"]); got != wantBootstrap {
		t.Errorf("configs/e1.cli:\n got  %q\n want %q", got, wantBootstrap)
	}
	if strings.Contains(string(files["configs/e1.cli"]), "#") {
		t.Error("the bootstrap file carries a `#`, which this platform's node refuses as a command")
	}

	// The topology names no startup-config for either node: on this kind such a file is
	// the whole configuration, so naming one would take the node's management plane with
	// it. The manifest says where the file is and who applies it, which is the only
	// way a reader of the topology alone could tell this from a node with no bootstrap.
	var topo struct {
		Topology struct {
			Nodes map[string]struct {
				Kind          string `yaml:"kind"`
				Image         string `yaml:"image"`
				StartupConfig string `yaml:"startup-config"`
			} `yaml:"nodes"`
		} `yaml:"topology"`
	}
	if err := yaml.Unmarshal(files[compiler.TopologyFile], &topo); err != nil {
		t.Fatal(err)
	}
	for name, node := range topo.Topology.Nodes {
		if node.StartupConfig != "" {
			t.Errorf("topology node %s carries startup-config %q; an EOS node's bootstrap reaches it through the push", name, node.StartupConfig)
		}
		if node.Kind != "ceos" || node.Image != "ceos:4.32.0.2F" {
			t.Errorf("topology node %s = %s / %s, want ceos / ceos:4.32.0.2F", name, node.Kind, node.Image)
		}
	}
	for _, n := range m.Nodes {
		if n.Bootstrap.Via != psp.BootstrapViaPush || n.Bootstrap.File != "configs/"+n.Name+".cli" {
			t.Errorf("node %s bootstrap = %+v, want configs/%s.cli via push", n.Name, n.Bootstrap, n.Name)
		}
		if n.PSP.ID != "arista_eos" || n.PSP.Source != psp.OriginEmbedded {
			t.Errorf("node %s psp = %+v, want arista_eos, embedded", n.Name, n.PSP)
		}
	}

	// One entry, this platform's own: the field is keyed by platform id from bundle "3",
	// so a one-platform bundle says whose claim it is rather than asserting a bare value.
	if wantFwd := map[string]string{"arista_eos": "hardware"}; !maps.Equal(m.Fidelity.ProductionForwarding, wantFwd) {
		t.Errorf("production_forwarding = %v, want %v", m.Fidelity.ProductionForwarding, wantFwd)
	}
	// Nothing on this platform is lossy and no port is shared, and the list is
	// present and empty rather than absent, as bundle "3" emits every list.
	if len(m.Fidelity.Lossy) != 0 {
		t.Errorf("fidelity.lossy = %v, want empty; no rule of this profile drops anything", m.Fidelity.Lossy)
	}

	// The same intent reads clean: validation and the compiler share SurveyDevice, so a
	// CTM the compiler builds must be one a read would have written.
	if read := validate.Validate(eosOnlyCTM(), reg); read.Rejected() {
		t.Errorf("the compiler built a bundle from intent validation refuses: %v", read)
	}
}

// deref reads a nullable manifest string, so a nil (the node has no name for this) is
// visible in a failure rather than printed as an address.
func deref(s *string) string {
	if s == nil {
		return "<null>"
	}
	return *s
}

// The bundle's configuration file carries the artifact's bytes unchanged, under the name
// the package gives it, and the manifest records what they hash to (M5, D-028). An EOS
// artifact's comments are `!`, which is the template's business and not the compiler's:
// the compiler neither reads nor rewrites a byte of it.
func TestEOSArtifactReachesTheBundleUnchanged(t *testing.T) {
	c := eosOnlyCTM()
	files, list := compiler.Compile(c, embeddedRegistry(t))
	if list.Rejected() {
		t.Fatalf("an EOS-only twin was refused: %v", list)
	}
	want := c.Devices[0].Artifact
	if got := string(files["configs/e1.device-config"]); got != want.Content {
		t.Errorf("configs/e1.device-config:\n got  %q\n want %q", got, want.Content)
	}
	if strings.Contains(string(files["configs/e1.device-config"]), "#") {
		t.Error("the compiler rewrote the artifact's comment marker; it copies the bytes and nothing else")
	}

	var m compiler.Manifest
	if err := json.Unmarshal(files[compiler.ManifestFile], &m); err != nil {
		t.Fatal(err)
	}
	for _, n := range m.Nodes {
		if n.Artifact == nil {
			t.Fatalf("node %s carries no artifact entry", n.Name)
		}
		if n.Artifact.Name != "device-config" || n.Artifact.File != "configs/"+n.Name+".device-config" {
			t.Errorf("node %s artifact = %+v, want device-config at configs/%s.device-config", n.Name, n.Artifact, n.Name)
		}
	}
	if m.Nodes[0].Artifact.Checksum != want.Checksum || m.Nodes[0].Artifact.Size != len(want.Content) {
		t.Errorf("e1's artifact entry = %+v, want checksum %s and size %d", m.Nodes[0].Artifact, want.Checksum, len(want.Content))
	}
}
