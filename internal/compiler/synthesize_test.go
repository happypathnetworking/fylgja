package compiler

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/probe"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// probeRegistry is the embedded probe packages, as a server without --psp-dir loads them.
func probeRegistry(t *testing.T) *probe.Registry {
	t.Helper()
	r, err := probe.Load("")
	if err != nil {
		t.Fatal(err)
	}
	return r
}

// declared is testdata/probes/<name>.json's probes, read as the server reads a file.
func declared(t *testing.T, name string) []probe.Probe {
	t.Helper()
	path := filepath.Join("..", "..", "testdata", "probes", name+".json")
	b, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	d, list := probe.Parse(b, path)
	if list.Rejected() {
		t.Fatalf("%s: %v", path, list)
	}
	return d.Probes
}

// probedThreeNode is the three-node fixture with two probe-ready ports on each device,
// ethernet-1/10 and ethernet-1/11, uncabled and not mgmt_only, as the fixture's seed will
// write them (research R-19), normalized.
func probedThreeNode(t *testing.T) *ctm.CTM {
	t.Helper()
	c := loadFixture(t, "testdata/ctm/three-node.json")
	for i := range c.Devices {
		for _, name := range []string{"ethernet-1/10", "ethernet-1/11"} {
			c.Devices[i].Interfaces = append(c.Devices[i].Interfaces, ctm.Interface{Name: name})
		}
	}
	ctm.Normalize(c)
	return c
}

// loop is one probe of the two endpoints given, each "device:interface", with distinct
// addresses in 10.9.<n>.0/24.
func loop(name, a, b string) probe.Probe {
	p := probe.Probe{Name: name, Format: "ping"}
	for j, end := range []string{a, b} {
		device, iface, _ := strings.Cut(end, ":")
		net := "10.9." + string(rune('1'+j)) + "."
		p.Endpoints[j] = probe.Endpoint{Device: device, Interface: iface, Address: net + "2/24", Gateway: net + "1"}
	}
	return p
}

func marshalCTM(t *testing.T, c *ctm.CTM) []byte {
	t.Helper()
	b, err := ctm.Marshal(c)
	if err != nil {
		t.Fatal(err)
	}
	return b
}

// A probe's two endpoints on one device (R-03): one host each, <probe>-a and <probe>-b, of
// the probe's format, with one port, the package's host.interface, on a synthesized link to
// the endpoint's interface, whose link is set; the host, its port and the link synthesized;
// the input untouched.
func TestPlaceProbesPlacesEachEndpoint(t *testing.T) {
	c := probedThreeNode(t)
	before := marshalCTM(t, c)
	placed, hosts, list := PlaceProbes(c, declared(t, "n1-loop"), probeRegistry(t))
	if len(list) != 0 {
		t.Fatalf("findings %v, want none", list)
	}
	if after := marshalCTM(t, c); !bytes.Equal(before, after) {
		t.Errorf("PlaceProbes changed its input:\n%s", after)
	}
	if len(placed.Devices) != len(c.Devices)+2 || len(placed.Links) != len(c.Links)+2 {
		t.Fatalf("placed %d devices and %d links, want %d and %d",
			len(placed.Devices), len(placed.Links), len(c.Devices)+2, len(c.Links)+2)
	}

	pkg, _ := probeRegistry(t).Lookup("ping")
	for _, want := range []Host{
		{Node: "n1-loop-a", Probe: "n1-loop", Endpoint: "a", Device: "n1", Interface: "ethernet-1/10", Port: pkg.Host.Interface,
			Address: "10.1.10.2/24", Gateway: "10.1.10.1", FarAddress: "10.1.11.2"},
		{Node: "n1-loop-b", Probe: "n1-loop", Endpoint: "b", Device: "n1", Interface: "ethernet-1/11", Port: pkg.Host.Interface,
			Address: "10.1.11.2/24", Gateway: "10.1.11.1", FarAddress: "10.1.10.2"},
	} {
		got, ok := hosts[want.Node]
		if !ok {
			t.Fatalf("no host %s in %v", want.Node, hosts)
		}
		if got.Package == nil || got.Package.Format != "ping" {
			t.Errorf("host %s's package is %+v, want the ping package", want.Node, got.Package)
		}
		got.Package = nil
		if got != want {
			t.Errorf("host %+v, want %+v", got, want)
		}

		id := ctm.CanonicalLinkID(ctm.Endpoint{Device: want.Node, Interface: want.Port},
			ctm.Endpoint{Device: want.Device, Interface: want.Interface})
		d := placed.Device(want.Node)
		if d == nil {
			t.Fatalf("no device %s in the placed CTM", want.Node)
		}
		wantDevice := ctm.Device{Name: want.Node, Platform: ctm.Platform{Package: "ping"},
			Interfaces: []ctm.Interface{{Name: want.Port, Enabled: d.Interfaces[0].Enabled, Link: id, Provenance: ctm.ProvenanceSynthesized}},
			Provenance: ctm.ProvenanceSynthesized}
		if !reflect.DeepEqual(*d, wantDevice) || !d.Interfaces[0].IsEnabled() {
			t.Errorf("host device %+v, want %+v, enabled", *d, wantDevice)
		}
		if port := placed.Device(want.Device).Interface(want.Interface); port.Link != id || port.Provenance != ctm.ProvenanceIntent {
			t.Errorf("%s:%s carries link %q under %s, want %q under intent: the port is intent's, its cable the host's",
				want.Device, want.Interface, port.Link, port.Provenance, id)
		}
		var link *ctm.Link
		for i := range placed.Links {
			if placed.Links[i].ID == id {
				link = &placed.Links[i]
			}
		}
		if link == nil || link.Provenance != ctm.ProvenanceSynthesized || len(link.Endpoints) != 2 {
			t.Errorf("link %s is %+v, want a synthesized link of two endpoints", id, link)
		}
	}
	// Intent's own objects keep intent.
	for _, d := range placed.Devices {
		if _, host := hosts[d.Name]; !host && d.Provenance != ctm.ProvenanceIntent {
			t.Errorf("device %s is %s, want intent", d.Name, d.Provenance)
		}
	}
	if list := LinkTerminations(placed); len(list) != 0 {
		t.Errorf("the placed CTM's links and interfaces disagree: %v", list)
	}
}

// A probe across two devices places each host on its own device.
func TestPlaceProbesAcrossTwoDevices(t *testing.T) {
	_, hosts, list := PlaceProbes(probedThreeNode(t), []probe.Probe{loop("n2-n3", "n2:ethernet-1/10", "n3:ethernet-1/11")},
		probeRegistry(t))
	if len(list) != 0 {
		t.Fatalf("findings %v, want none", list)
	}
	if a, b := hosts["n2-n3-a"], hosts["n2-n3-b"]; a.Device != "n2" || b.Device != "n3" ||
		a.FarAddress != "10.9.2.2" || b.FarAddress != "10.9.1.2" {
		t.Errorf("hosts %+v and %+v, want n2's and n3's, each reaching the other", a, b)
	}
}

// The probes are placed in name order whatever order they are declared in, so a shuffled
// declaration places, and compiles, alike.
func TestPlaceProbesIgnoresTheDeclarationsOrder(t *testing.T) {
	decls := append(declared(t, "n1-loop"), declared(t, "n2-loop")...)
	shuffled := []probe.Probe{decls[1], decls[0]}
	first, _, _ := PlaceProbes(probedThreeNode(t), decls, probeRegistry(t))
	second, _, _ := PlaceProbes(probedThreeNode(t), shuffled, probeRegistry(t))
	if !bytes.Equal(marshalCTM(t, first), marshalCTM(t, second)) {
		t.Error("the declaration's order changed the placed CTM")
	}
	a, b := compileProbed(t, probedThreeNode(t), decls), compileProbed(t, probedThreeNode(t), shuffled)
	sameBundle(t, "the declaration's order", a.files, b.files)
}

// Each placement refusal (R-09, data-model §12), one case each: the probe and the endpoint
// named, the cause in the message, and nothing placed.
func TestPlacementRefusals(t *testing.T) {
	ok := loop("p", "n1:ethernet-1/10", "n1:ethernet-1/11")
	for _, c := range []struct {
		name   string
		decls  []probe.Probe
		rule   string
		object string
		says   []string
	}{
		{"device not in the snapshot", []probe.Probe{loop("p", "n9:ethernet-1/10", "n1:ethernet-1/11")},
			findings.RuleProbeDeviceUnknown, "p/a", []string{`device "n9" is not in the snapshot`}},
		{"interface the device lacks", []probe.Probe{loop("p", "n1:ethernet-1/10", "n1:ethernet-1/99")},
			findings.RuleProbeInterfaceUnknown, "p/b", []string{`device n1 has no interface "ethernet-1/99"`}},
		{"interface intent cables", []probe.Probe{loop("p", "n1:ethernet-1/10", "n1:ethernet-1/1")},
			findings.RuleProbeInterfaceCabled, "p/b",
			[]string{"interface n1:ethernet-1/1 is cabled (n1:ethernet-1/1|n2:ethernet-1/1); a probe takes an uncabled port that is not mgmt_only"}},
		{"interface mgmt_only", []probe.Probe{loop("p", "n1:mgmt0", "n1:ethernet-1/11")},
			findings.RuleProbeInterfaceMgmtOnly, "p/a", []string{"interface n1:mgmt0 is mgmt_only"}},
		{"port another probe took", []probe.Probe{ok, loop("q", "n2:ethernet-1/10", "n1:ethernet-1/11")},
			findings.RuleProbePortTaken, "q/b", []string{"interface n1:ethernet-1/11 is taken by probe p endpoint b"}},
		{"format no package declares", []probe.Probe{func() probe.Probe { p := ok; p.Format = "twamp"; return p }()},
			findings.RuleProbeFormatUnknown, "p", []string{`format "twamp"`, "the formats loaded are ping"}},
		{"host named as a device", []probe.Probe{loop("n2", "n1:ethernet-1/10", "n1:ethernet-1/11")},
			findings.RuleProbeHostCollision, "n2/a", nil},
	} {
		t.Run(c.name, func(t *testing.T) {
			if c.name == "host named as a device" {
				// A device named as a host would be: n2-a, beside the probe n2.
				cm := probedThreeNode(t)
				cm.Devices[1].Name = "n2-a"
				c.says = []string{"host n2-a, this endpoint's node, is the name of a device or of another host"}
				assertRefused(t, cm, c.decls, c.rule, c.object, c.says)
				return
			}
			assertRefused(t, probedThreeNode(t), c.decls, c.rule, c.object, c.says)
		})
	}
}

func assertRefused(t *testing.T, c *ctm.CTM, decls []probe.Probe, rule, object string, says []string) {
	t.Helper()
	placed, hosts, list := PlaceProbes(c, decls, probeRegistry(t))
	if placed != nil || hosts != nil {
		t.Errorf("a refused placement placed %d hosts", len(hosts))
	}
	for _, f := range list {
		if f.Rule != rule {
			continue
		}
		if f.Severity != findings.Rejection || f.Object != object {
			t.Errorf("%s is a %s at %q, want a rejection at %q", rule, f.Severity, f.Object, object)
		}
		for _, s := range says {
			if !strings.Contains(f.Message, s) {
				t.Errorf("%s says %q, want it to say %q", rule, f.Message, s)
			}
		}
		return
	}
	t.Errorf("no %s among %v", rule, list)
}

// Every refusal is found in one pass, then nothing is placed: a stage that breaks two
// probes names both.
func TestEveryPlacementRefusalInOnePass(t *testing.T) {
	_, _, list := PlaceProbes(probedThreeNode(t), []probe.Probe{
		loop("p", "n1:ethernet-1/1", "n1:ethernet-1/11"),
		loop("q", "n9:ethernet-1/10", "n2:mgmt0"),
	}, probeRegistry(t))
	var got []string
	for _, f := range list {
		got = append(got, f.Object+" "+f.Rule)
	}
	want := []string{"p/a probe.interface.cabled", "q/a probe.device.unknown", "q/b probe.interface.mgmt_only"}
	if !slices.Equal(got, want) {
		t.Errorf("refusals %v, want %v", got, want)
	}
}

// probedBundle is a compiled snapshot with probes and its manifest.
type probedBundle struct {
	files map[string][]byte
	m     Manifest
}

func compileProbed(t *testing.T, c *ctm.CTM, decls []probe.Probe) probedBundle {
	t.Helper()
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	files, list := Compile(c, decls, reg, probeRegistry(t))
	if list.Rejected() {
		t.Fatalf("refused: %v", list)
	}
	var m Manifest
	if err := json.Unmarshal(files[ManifestFile], &m); err != nil {
		t.Fatal(err)
	}
	return probedBundle{files: files, m: m}
}

func (b probedBundle) node(t *testing.T, name string) ManifestNode {
	t.Helper()
	for _, n := range b.m.Nodes {
		if n.Name == name {
			return n
		}
	}
	t.Fatalf("no node %s in the manifest", name)
	return ManifestNode{}
}

// A probed snapshot compiles to bundle 6 with its hosts (R-10, R-11): each host a node of
// its package's kind and image whose exec lines are the package's host.address and
// host.route rendered, with no startup-config and no configs file; in the manifest a node
// with its probe and a null platform, psp, artifact and bootstrap; the probe in probes[];
// both hosts in fidelity.synthesized.
func TestCompileAProbedSnapshot(t *testing.T) {
	b := compileProbed(t, probedThreeNode(t), declared(t, "n1-loop"))
	pkg, _ := probeRegistry(t).Lookup("ping")

	topo := string(b.files[TopologyFile])
	for _, want := range []string{
		"    n1-loop-a:\n      kind: " + pkg.Image.ClabKind + "\n      image: " + pkg.Image.Ref + "\n      exec:\n" +
			"        - ip addr add 10.1.10.2/24 dev eth1\n        - ip route add 10.1.11.2/32 via 10.1.10.1 dev eth1\n",
		"    n1-loop-b:\n      kind: " + pkg.Image.ClabKind + "\n      image: " + pkg.Image.Ref + "\n      exec:\n" +
			"        - ip addr add 10.1.11.2/24 dev eth1\n        - ip route add 10.1.10.2/32 via 10.1.11.1 dev eth1\n",
		`- endpoints: ["n1-loop-a:eth1", "n1:e1-10"]`,
	} {
		if !strings.Contains(topo, want) {
			t.Errorf("the topology does not hold\n%s\nin\n%s", want, topo)
		}
	}
	for name := range b.files {
		if strings.Contains(name, "n1-loop") {
			t.Errorf("the bundle carries %s; a host has no configs file", name)
		}
	}

	host := b.node(t, "n1-loop-a")
	want := ManifestNode{Name: "n1-loop-a", Provenance: ProvenanceSynthesized,
		Probe:          &ManifestProbe{Name: "n1-loop", Endpoint: "a", Format: "ping", Package: ManifestPSP{ID: "ping", Source: probe.OriginEmbedded}},
		Image:          pkg.Image.Ref,
		ManagementPort: "eth0"}
	if !reflect.DeepEqual(host, want) {
		t.Errorf("host node %+v, want %+v", host, want)
	}
	if n1 := b.node(t, "n1"); n1.Provenance != "" || n1.Probe != nil || n1.PSP == nil || n1.Artifact == nil || n1.Bootstrap == nil {
		t.Errorf("device node %+v, want intent's, with its package, artifact and bootstrap", n1)
	}
	for _, field := range []string{`"platform": null`, `"psp": null`, `"artifact": null`, `"bootstrap": null`} {
		if bytes.Count(b.files[ManifestFile], []byte(field)) != 2 {
			t.Errorf("the manifest does not write %s once per host", field)
		}
	}

	wantEntry := ManifestProbeEntry{Name: "n1-loop", Format: "ping", Package: ManifestPSP{ID: "ping", Source: probe.OriginEmbedded},
		Hosts: [2]ProbeHost{
			{Endpoint: "a", Node: "n1-loop-a", Device: "n1", Interface: "ethernet-1/10", Port: "eth1", Address: "10.1.10.2/24", Gateway: "10.1.10.1"},
			{Endpoint: "b", Node: "n1-loop-b", Device: "n1", Interface: "ethernet-1/11", Port: "eth1", Address: "10.1.11.2/24", Gateway: "10.1.11.1"},
		},
		Fidelity: ProbeFidelity{Forwarding: pkg.Fidelity.Forwarding, Timing: pkg.Fidelity.Timing}}
	if !reflect.DeepEqual(b.m.Probes, []ManifestProbeEntry{wantEntry}) {
		t.Errorf("probes %+v, want %+v", b.m.Probes, wantEntry)
	}
	if !slices.Equal(b.m.Fidelity.Synthesized, []string{"n1-loop-a", "n1-loop-b"}) {
		t.Errorf("fidelity.synthesized %v, want both hosts", b.m.Fidelity.Synthesized)
	}
	if _, ok := b.m.Fidelity.ProductionForwarding["ping"]; ok {
		t.Error("production_forwarding names the probe format: it is per platform package, and a host has none")
	}
}

// A snapshot with no probes compiles alike with the probe registry or without it, and the
// bundle id moves with the hosts (FR-012).
func TestTheBundleIDMovesWithTheHosts(t *testing.T) {
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	without, _ := Compile(probedThreeNode(t), nil, reg, nil)
	with, _ := Compile(probedThreeNode(t), []probe.Probe{}, reg, probeRegistry(t))
	sameBundle(t, "the probe registry beside no probe", without, with)

	one := compileProbed(t, probedThreeNode(t), declared(t, "n1-loop"))
	moved := declared(t, "n1-loop")
	moved[0].Endpoints[0].Address = "10.1.10.3/24"
	other := compileProbed(t, probedThreeNode(t), moved)
	if bundle.ID(without) == bundle.ID(one.files) || bundle.ID(one.files) == bundle.ID(other.files) {
		t.Error("the bundle id did not move with a probe or with a host's address")
	}
}
