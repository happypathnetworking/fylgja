package verify

import (
	"context"
	"encoding/json"
	"fmt"
	"maps"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// repo is a path from the repository root.
func repo(parts ...string) string {
	return filepath.Join(append([]string{"..", ".."}, parts...)...)
}

// fakeReader answers each read from a table keyed by "<addr> <path>", as a node would, in
// the suite's shape (internal/conformance/boot_test.go): the n-th read of a key gets the
// n-th answer of its sequence, the last repeating, so a test can make a node settle late;
// an error is the transport's. A read the table does not hold is an error, so a test sees
// any read it did not expect. A read under a context that has ended fails, as a real one
// does.
type fakeReader struct {
	answers map[string][]Answer
	errs    map[string]error
	// onGet runs before each answer: a test's clock moves, or its context is cancelled.
	onGet func()

	mu     sync.Mutex
	calls  []string
	probes map[string]wire.Probe // the probe each address was read over
	reads  map[string]int
}

func newReader() *fakeReader {
	return &fakeReader{answers: map[string][]Answer{}, errs: map[string]error{}}
}

func (f *fakeReader) Get(ctx context.Context, addr string, probe wire.Probe, path string, _ func(string) (string, bool)) (Answer, error) {
	if f.onGet != nil {
		f.onGet()
	}
	key := addr + " " + path
	// A context that has ended is answered as a real reader answers it, after onGet, which
	// may have ended it.
	if err := ctx.Err(); err != nil {
		f.mu.Lock()
		f.calls = append(f.calls, key)
		f.mu.Unlock()
		return Answer{}, fmt.Errorf("gNMI Get %s at %s: code=Canceled msg=%q", path, addr, err)
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	f.calls = append(f.calls, key)
	if f.probes == nil {
		f.probes, f.reads = map[string]wire.Probe{}, map[string]int{}
	}
	f.probes[addr] = probe
	n := f.reads[key]
	f.reads[key]++
	if err, ok := f.errs[key]; ok {
		return Answer{}, err
	}
	seq, ok := f.answers[key]
	if !ok || len(seq) == 0 {
		return Answer{}, fmt.Errorf("the fake node has no answer for %s", key)
	}
	return seq[min(n, len(seq)-1)], nil
}

// set answers a key with one answer, or a sequence of them.
func (f *fakeReader) set(addr, path string, answers ...Answer) {
	f.answers[addr+" "+path] = answers
}

// packageSet finds packages by platform id, as *psp.Registry does.
type packageSet map[string]*psp.PSP

func (s packageSet) LookupID(id string) (*psp.PSP, bool) {
	p, ok := s[id]
	return p, ok
}

// shippedPackages are the two shipped packages, loaded from psp/.
func shippedPackages(t *testing.T) packageSet {
	t.Helper()
	pkgs, err := psp.FromDir(repo("psp"))
	if err != nil {
		t.Fatal(err)
	}
	set := packageSet{}
	for _, p := range pkgs {
		set[p.Platform.ID] = p
	}
	for _, id := range []string{srlinux, eos} {
		if set[id] == nil || set[id].Conformance == nil {
			t.Fatalf("psp/ has no %s package with a conformance facet", id)
		}
	}
	return set
}

const (
	srlinux = "nokia_srlinux"
	eos     = "arista_eos"
)

// goldenManifest reads a golden bundle's manifest, and goldenID its identity.
func goldenManifest(t *testing.T, name string) compiler.Manifest {
	t.Helper()
	b, err := os.ReadFile(repo("testdata", "golden", name, "manifest.json"))
	if err != nil {
		t.Fatal(err)
	}
	var m compiler.Manifest
	if err := json.Unmarshal(b, &m); err != nil {
		t.Fatal(err)
	}
	return m
}

func goldenID(t *testing.T, name string) string {
	t.Helper()
	id, err := bundle.IDOfDir(repo("testdata", "golden", name))
	if err != nil {
		t.Fatal(err)
	}
	return id
}

// The fake environment: both logins set, the password a sentinel no output may carry.
const fakePassword = "sentinel-password-value"

func fakeEnv(name string) (string, bool) {
	switch name {
	case "FYLGJA_SRLINUX_USERNAME", "FYLGJA_EOS_USERNAME":
		return "admin", true
	case "FYLGJA_SRLINUX_PASSWORD", "FYLGJA_EOS_PASSWORD":
		return fakePassword, true
	}
	return "", false
}

// ready is a version 4 record of a ready twin of the staged bundle: each node at its
// address, holding the staged bundle.
func ready(staged string, ips map[string]string) wire.TwinRecord {
	rec := wire.TwinRecord{TwinVersion: "4", Lab: "fylgja", BundleID: staged, Source: "intent", State: wire.StateReady}
	for _, name := range sortedKeys(ips) {
		id := staged
		rec.Nodes = append(rec.Nodes, wire.TwinNode{Name: name, Container: "clab-fylgja-" + name, MgmtIPv4: ips[name], Holds: &id})
	}
	return rec
}

// labOf is containerlab's report of the same nodes.
func labOf(ips map[string]string) []wire.LabNode {
	var out []wire.LabNode
	for _, name := range sortedKeys(ips) {
		out = append(out, wire.LabNode{Name: name, Container: "clab-fylgja-" + name, State: "running", MgmtIPv4: ips[name]})
	}
	return out
}

func sortedKeys(m map[string]string) []string {
	return slices.Sorted(maps.Keys(m))
}

// The three-node twin: SR Linux nodes at the addresses tier 3 has given them, and what a
// booted twin read on each cabled port's neighbour list.
var (
	threeNodeIP = map[string]string{"n1": "172.20.20.2", "n2": "172.20.20.3", "n3": "172.20.20.4"}
	r4          = map[string][2]string{
		"n1 ethernet-1/1": {"n2", "ethernet-1/1"},
		"n1 ethernet-1/2": {"n3", "ethernet-1/2"},
		"n2 ethernet-1/1": {"n1", "ethernet-1/1"},
		"n2 ethernet-1/2": {"n3", "ethernet-1/1"},
		"n3 ethernet-1/1": {"n2", "ethernet-1/2"},
		"n3 ethernet-1/2": {"n1", "ethernet-1/2"},
	}
)

// SR Linux's paths, rendered, and the shapes it answers them in (a leaf at the leaf, a
// subtree at its list entry).
const srlHostName = "/system/name/host-name"

func srlEnabled(port string) string  { return "/interface[name=" + port + "]/admin-state" }
func srlNeighbor(port string) string { return "/system/lldp/interface[name=" + port + "]/neighbor" }

func srl(ip string) string { return ip + ":57400" }

func answerAt(path string, v any) Answer {
	return Answer{Updates: []Update{{Path: path, Value: v}}}
}

func srlHostNameIs(name string) Answer {
	return answerAt("srl_nokia-system:system/srl_nokia-system-name:name/host-name", name)
}

func srlEnabledIs(port, v string) Answer {
	return answerAt("srl_nokia-interfaces:interface[name="+port+"]/admin-state", v)
}

// srlNeighbours answers a port's neighbour read at the list entry, as SR Linux answers a
// subtree, with value as its neighbor member.
func srlNeighbours(port string, value any) Answer {
	return answerAt("srl_nokia-system:system/srl_nokia-lldp:lldp/interface[name="+port+"]", map[string]any{"neighbor": value})
}

func srlEntries(entries ...[2]string) []any {
	list := []any{}
	for i, e := range entries {
		list = append(list, map[string]any{"id": fmt.Sprintf("1A:EB:0%d:FF:00:00", i+1), "system-name": e[0], "port-id": e[1]})
	}
	return list
}

// healthyThreeNode answers every read of the three-node twin as a booted twin answered it.
func healthyThreeNode() *fakeReader {
	f := newReader()
	for node, ip := range threeNodeIP {
		f.set(srl(ip), srlHostName, srlHostNameIs(node))
		for _, port := range []string{"ethernet-1/1", "ethernet-1/2"} {
			f.set(srl(ip), srlEnabled(port), srlEnabledIs(port, "enable"))
			f.set(srl(ip), srlNeighbor(port), srlNeighbours(port, srlEntries(r4[node+" "+port])))
		}
	}
	return f
}

// threeNode is the three-node golden twin, ready and healthy, as one read takes it.
func threeNode(t *testing.T) (Input, *fakeReader) {
	t.Helper()
	staged := goldenID(t, "three-node")
	f := healthyThreeNode()
	return Input{
		Manifest: goldenManifest(t, "three-node"), StagedID: staged, Record: ready(staged, threeNodeIP),
		Lab: labOf(threeNodeIP), Packages: shippedPackages(t), Reader: f, Getenv: fakeEnv,
	}, f
}

// The mixed golden twin: s1 is SR Linux, e1 and e2 cEOS, cabled as the golden's links name
// them (e1:Ethernet1|s1:ethernet-1/1, e1:Ethernet2/1|e2:Ethernet1,
// e2:Ethernet3/1/1|s1:ethernet-1/2).
var mixedIP = map[string]string{"s1": "172.20.20.2", "e1": "172.20.20.3", "e2": "172.20.20.4"}

const eosHostName = "/system/state/hostname"

func eosEnabled(port string) string {
	return "/interfaces/interface[name=" + port + "]/state/admin-status"
}

func eosNeighbor(port string) string {
	return "/lldp/interfaces/interface[name=" + port + "]/neighbors/neighbor"
}

func eosAddr(ip string) string { return ip + ":6030" }

// eosEntries answers a neighbour list as cEOS does: one update per keyed
// entry, the far node and port one container below it.
func eosEntries(port string, entries ...[2]string) Answer {
	var a Answer
	for i, e := range entries {
		a.Updates = append(a.Updates, Update{
			Path: fmt.Sprintf("%s[id=%d]", strings.TrimPrefix(eosNeighbor(port), "/"), i+1),
			Value: map[string]any{"openconfig-lldp:id": fmt.Sprint(i + 1),
				"openconfig-lldp:state": map[string]any{"system-name": e[0], "port-id": e[1]}},
		})
	}
	return a
}

func healthyMixed() *fakeReader {
	f := newReader()
	s1, e1, e2 := srl(mixedIP["s1"]), eosAddr(mixedIP["e1"]), eosAddr(mixedIP["e2"])
	f.set(s1, srlHostName, srlHostNameIs("s1"))
	for port, far := range map[string][2]string{"ethernet-1/1": {"e1", "Ethernet1"}, "ethernet-1/2": {"e2", "Ethernet3/1/1"}} {
		f.set(s1, srlEnabled(port), srlEnabledIs(port, "enable"))
		f.set(s1, srlNeighbor(port), srlNeighbours(port, srlEntries(far)))
	}
	for addr, node := range map[string]string{e1: "e1", e2: "e2"} {
		f.set(addr, eosHostName, answerAt("openconfig-system:system/state/hostname", node))
	}
	for _, p := range []struct {
		addr, port string
		far        [2]string
	}{
		{e1, "Ethernet1", [2]string{"s1", "ethernet-1/1"}},
		{e1, "Ethernet2/1", [2]string{"e2", "Ethernet1"}},
		{e2, "Ethernet1", [2]string{"e1", "Ethernet2/1"}},
		{e2, "Ethernet3/1/1", [2]string{"s1", "ethernet-1/2"}},
	} {
		f.set(p.addr, eosEnabled(p.port), answerAt("openconfig-interfaces:interfaces/interface[name="+p.port+"]/state/admin-status", "UP"))
		f.set(p.addr, eosNeighbor(p.port), eosEntries(p.port, p.far))
	}
	return f
}

func mixed(t *testing.T) (Input, *fakeReader) {
	t.Helper()
	staged := goldenID(t, "mixed")
	f := healthyMixed()
	return Input{
		Manifest: goldenManifest(t, "mixed"), StagedID: staged, Record: ready(staged, mixedIP),
		Lab: labOf(mixedIP), Packages: shippedPackages(t), Reader: f, Getenv: fakeEnv,
	}, f
}

// disable sets one mapping row's enabled to false, as bundle 4 writes a port intent
// disables.
func disable(t *testing.T, m compiler.Manifest, device, iface string) compiler.Manifest {
	t.Helper()
	m.Mapping = append([]compiler.MappingRow(nil), m.Mapping...)
	for i, r := range m.Mapping {
		if r.Device == device && r.Interface == iface {
			off := false
			m.Mapping[i].Enabled = &off
			return m
		}
	}
	t.Fatalf("no mapping row %s:%s", device, iface)
	return m
}
