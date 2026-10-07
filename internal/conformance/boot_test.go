package conformance

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"reflect"
	"slices"
	"strings"
	"sync"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// fakeReader answers the boot half's reads from a table keyed by "<addr> <path>", as a
// node would: an Answer, or an error for the transport. A read the table does not hold
// is an error, so a test sees any read it did not expect as a failure.
type fakeReader struct {
	answers map[string]Answer
	errs    map[string]error

	mu     sync.Mutex
	calls  []string
	probes []wire.Probe
}

func (f *fakeReader) Get(_ context.Context, addr string, probe wire.Probe, path string, _ func(string) (string, bool)) (Answer, error) {
	key := addr + " " + path
	f.mu.Lock()
	f.calls = append(f.calls, key)
	f.probes = append(f.probes, probe)
	f.mu.Unlock()
	if err, ok := f.errs[key]; ok {
		return Answer{}, err
	}
	if a, ok := f.answers[key]; ok {
		return a, nil
	}
	return Answer{}, fmt.Errorf("the fake node has no answer for %s", key)
}

// packageSet finds packages by platform id, as *psp.Registry does.
type packageSet map[string]*psp.PSP

func (s packageSet) LookupID(id string) (*psp.PSP, bool) {
	p, ok := s[id]
	return p, ok
}

// shipped is the embedded SR Linux package, the one the worker runs.
func shipped(t *testing.T) *psp.PSP {
	t.Helper()
	pkgs, err := psp.Embedded()
	if err != nil {
		t.Fatal(err)
	}
	for _, p := range pkgs {
		if p.Platform.ID == "nokia_srlinux" {
			return p
		}
	}
	t.Fatal("no embedded nokia_srlinux package")
	return nil
}

// goldenManifest reads a golden bundle's manifest: the twin as compiled.
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

func recordNode(name, ip, pspID, source string, readyAfterS float64) wire.TwinNode {
	return wire.TwinNode{
		Name: name, Container: "clab-fylgja-" + name, Image: "ghcr.io/nokia/srlinux:24.7.1",
		PSP: wire.PSPRef{ID: pspID, Source: source}, MgmtIPv4: ip, ReadyAfterS: readyAfterS,
		Artifact:  &wire.TwinArtifact{Name: "device-config", ContentType: "text/plain", Checksum: "43e8fd0c2de5f4646f74a51d34742824", Size: 861},
		PushedInS: 1.2,
	}
}

// The three-node twin's addresses, and what a booted twin read on each cabled port's
// neighbour list: the far node, and the far port under the far node's own name.
const (
	a1 = "172.20.20.2:57400"
	a2 = "172.20.20.3:57400"
	a3 = "172.20.20.4:57400"
)

var (
	threeNodeAddr = map[string]string{"n1": a1, "n2": a2, "n3": a3}
	r4            = map[string][2]string{
		"n1 ethernet-1/1": {"n2", "ethernet-1/1"},
		"n1 ethernet-1/2": {"n3", "ethernet-1/2"},
		"n2 ethernet-1/1": {"n1", "ethernet-1/1"},
		"n2 ethernet-1/2": {"n3", "ethernet-1/1"},
		"n3 ethernet-1/1": {"n2", "ethernet-1/2"},
		"n3 ethernet-1/2": {"n1", "ethernet-1/2"},
	}
)

// The paths the shipped package reads, rendered, and the shapes SR Linux answers them in
// (a leaf at the leaf, a subtree at its list entry).
const (
	hostNamePath = "/system/name/host-name"
	versionPath  = "/system/information/version"
	readVersion  = "v24.7.1-330-g38f237abfe"
)

func enabledPath(port string) string {
	return "/interface[name=" + port + "]/admin-state"
}

func discoveringPath(port string) string {
	return "/system/lldp/interface[name=" + port + "]/admin-state"
}

func neighborPath(port string) string {
	return "/system/lldp/interface[name=" + port + "]/neighbor"
}

// leaf is a node's answer as one update at one path, which is how every M6 shape comes
// back: a leaf at the leaf, or a subtree at its list entry.
func leaf(path string, v any) Answer {
	return Answer{Updates: []Update{{Path: path, Value: v}}}
}

// keyedEntries is a node's answer as one update per keyed entry of a requested list,
// which is the shape cEOS answers a list in: each update at the list's
// path plus its own key, each value one entry.
func keyedEntries(listPath, key string, values ...any) Answer {
	var a Answer
	for i, v := range values {
		a.Updates = append(a.Updates, Update{
			Path:  fmt.Sprintf("%s[%s=%d]", strings.TrimPrefix(listPath, "/"), key, i+1),
			Value: v,
		})
	}
	return a
}

func neighbours(port string, entries ...[2]string) Answer {
	list := []any{}
	for i, e := range entries {
		list = append(list, map[string]any{
			"id": fmt.Sprintf("1A:EB:0%d:FF:00:00", i+1), "system-name": e[0], "port-id": e[1], "port-id-type": "INTERFACE_NAME",
		})
	}
	return neighbourValue(port, list)
}

// neighbourValue answers a port's neighbour read with value as its neighbor member, at
// the list entry, as SR Linux answers a subtree.
func neighbourValue(port string, value any) Answer {
	return leaf("srl_nokia-system:system/srl_nokia-lldp:lldp/interface[name="+port+"]", map[string]any{"neighbor": value})
}

// refused is the transport's error for a node nothing answers at, as gnmiGet words it
// (internal/lab/probe_gnmi.go): the path, the address, and the gRPC status.
func refused(path, addr string) error {
	return fmt.Errorf("gNMI Get %s at %s: code=Unavailable msg=%q", path, addr,
		`connection error: desc = "transport: Error while dialing: dial tcp `+addr+`: connect: connection refused"`)
}

// healthyThreeNode answers every read of the three-node twin as a booted twin answered it.
func healthyThreeNode() *fakeReader {
	f := &fakeReader{answers: map[string]Answer{}, errs: map[string]error{}}
	for node, addr := range threeNodeAddr {
		f.answers[addr+" "+hostNamePath] = leaf("srl_nokia-system:system/srl_nokia-system-name:name/host-name", node)
		f.answers[addr+" "+versionPath] = leaf("srl_nokia-system:system/srl_nokia-system-info:information/version", readVersion)
		for _, port := range []string{"ethernet-1/1", "ethernet-1/2"} {
			f.answers[addr+" "+enabledPath(port)] = leaf("srl_nokia-interfaces:interface[name="+port+"]/admin-state", "enable")
			f.answers[addr+" "+discoveringPath(port)] = leaf("srl_nokia-system:system/srl_nokia-lldp:lldp/interface[name="+port+"]/admin-state", "enable")
			f.answers[addr+" "+neighborPath(port)] = neighbours(port, r4[node+" "+port])
		}
	}
	return f
}

// threeNode is the fixture's twin as the boot half reads it: the three-node golden's
// manifest, a record of it that ended ready, and the shipped package.
func threeNode(t *testing.T) (BootInput, *fakeReader) {
	t.Helper()
	reader := healthyThreeNode()
	return BootInput{
		Record: wire.TwinRecord{TwinVersion: "2", Lab: "fylgja", Nodes: []wire.TwinNode{
			recordNode("n1", "172.20.20.2", "nokia_srlinux", "embedded", 15.8),
			recordNode("n2", "172.20.20.3", "nokia_srlinux", "embedded", 15.9),
			recordNode("n3", "172.20.20.4", "nokia_srlinux", "embedded", 16.03),
		}},
		Manifest: goldenManifest(t, "three-node"),
		Packages: packageSet{"nokia_srlinux": shipped(t)},
		Reader:   reader,
		Getenv:   func(string) (string, bool) { return "", false },
	}, reader
}

func passedLine(node, addr, ready string) string {
	return "node " + node + " (" + addr + "): booted; ready after " + ready + "s of 60s; host name " + node +
		"; 2 cabled ports enabled and discovering; 2 neighbours as the bundle's links name them; version " +
		readVersion + " (listed: 24.7); read after the push"
}

func messages(fs []Failure) []string {
	var out []string
	for _, f := range fs {
		out = append(out, f.String())
	}
	return out
}

// The boot half on a faked node and a record built here: a healthy twin passes with each
// node's success line, reading each path once through the package's probe; then every
// wording the boot half gives, each produced
// by one change to the node, the record or the package, and each asserted whole.
func TestBootHalfFaked(t *testing.T) {
	t.Run("healthy", func(t *testing.T) {
		in, reader := threeNode(t)
		reports := Boot(context.Background(), in)
		if len(reports) != 1 || reports[0].Package != "nokia_srlinux" || reports[0].BootHalf != BootHalfTier3 {
			t.Fatalf("reports = %+v, want one for nokia_srlinux, boot half tier 3", reports)
		}
		r := reports[0]
		if len(r.Failures) != 0 {
			t.Errorf("failures on a healthy twin:\n%s", strings.Join(messages(r.Failures), "\n"))
		}
		want := []BootNode{
			{Name: "n1", Addr: a1, Passed: passedLine("n1", a1, "15.8")},
			{Name: "n2", Addr: a2, Passed: passedLine("n2", a2, "15.9")},
			{Name: "n3", Addr: a3, Passed: passedLine("n3", a3, "16.03")},
		}
		if !reflect.DeepEqual(r.Nodes, want) {
			t.Errorf("nodes =\n%+v\nwant\n%+v", r.Nodes, want)
		}
		// Each node: host name, version, and three reads per cabled port. Once each.
		if len(reader.calls) != 3*(2+2*3) {
			t.Errorf("%d reads, want %d: one per path, no retry", len(reader.calls), 3*(2+2*3))
		}
		if dup := duplicates(reader.calls); len(dup) > 0 {
			t.Errorf("paths read more than once: %v", dup)
		}
		for _, p := range reader.probes {
			if p.Encoding != "json_ietf" || p.Port != 57400 || p.UsernameEnv != "FYLGJA_SRLINUX_USERNAME" || p.PasswordEnv != "FYLGJA_SRLINUX_PASSWORD" {
				t.Errorf("a read went by probe %+v, want the package's readiness probe", p)
				break
			}
		}
	})

	neighbourAt := func(addr, port string, entries ...[2]string) func(*BootInput, *fakeReader) {
		return func(_ *BootInput, f *fakeReader) {
			f.answers[addr+" "+neighborPath(port)] = neighbours(port, entries...)
		}
	}
	neighbourIs := func(addr, port string, value any) func(*BootInput, *fakeReader) {
		return func(_ *BootInput, f *fakeReader) {
			f.answers[addr+" "+neighborPath(port)] = neighbourValue(port, value)
		}
	}
	withPackage := func(edit func(p *psp.PSP)) func(*BootInput, *fakeReader) {
		return func(in *BootInput, _ *fakeReader) {
			cp := *shipped(t)
			edit(&cp)
			in.Packages = packageSet{"nokia_srlinux": &cp}
		}
	}
	withRecordNode := func(name string, edit func(n *wire.TwinNode)) func(*BootInput, *fakeReader) {
		return func(in *BootInput, _ *fakeReader) {
			nodes := slices.Clone(in.Record.Nodes)
			for i := range nodes {
				if nodes[i].Name == name {
					edit(&nodes[i])
				}
			}
			in.Record.Nodes = nodes
		}
	}
	const (
		row11 = "checking mapping row n1:ethernet-1/1 (port e1-1, node name ethernet-1/1)"
		link  = " for link n1:ethernet-1/1|n2:ethernet-1/1"
	)

	for _, c := range []struct {
		name   string
		change func(*BootInput, *fakeReader)
		check  string
		node   string // "" for a failure of the package as a whole
		want   string
		reads  int // how many reads the change leaves; 0 means the healthy 24
	}{
		{name: "host name wrong", check: CheckHostName, node: "n2",
			change: func(_ *BootInput, f *fakeReader) {
				f.answers[a2+" "+hostNamePath] = leaf("srl_nokia-system:system/srl_nokia-system-name:name/host-name", "n9")
			},
			want: `node n2 (172.20.20.3:57400): host_name at /system/name/host-name: expected "n2", read "n9"`},
		{name: "host name read nothing", check: CheckHostName, node: "n2",
			change: func(_ *BootInput, f *fakeReader) { f.answers[a2+" "+hostNamePath] = Answer{} },
			want:   `node n2 (172.20.20.3:57400): host_name at /system/name/host-name: expected "n2", read nothing`},
		{name: "host name transport error", check: CheckHostName, node: "n2",
			change: func(_ *BootInput, f *fakeReader) {
				f.errs[a2+" "+hostNamePath] = errors.New(`gNMI Get /system/name/host-name at 172.20.20.3:57400: code=Unauthenticated msg="login refused for [redacted]"`)
			},
			want: `node n2 (172.20.20.3:57400): host_name at /system/name/host-name: gNMI Get /system/name/host-name at 172.20.20.3:57400: code=Unauthenticated msg="login refused for [redacted]"`},
		{name: "port disabled", check: CheckPortEnabled, node: "n1",
			change: func(_ *BootInput, f *fakeReader) {
				f.answers[a1+" "+enabledPath("ethernet-1/2")] = leaf("srl_nokia-interfaces:interface[name=ethernet-1/2]/admin-state", "disable")
			},
			want: `node n1 (172.20.20.2:57400): port_enabled at /interface[name=ethernet-1/2]/admin-state: expected "enable", read "disable"; checking mapping row n1:ethernet-1/2 (port e1-2, node name ethernet-1/2)`},
		{name: "discovering absent", check: CheckPortDiscovering, node: "n1",
			change: func(_ *BootInput, f *fakeReader) { f.answers[a1+" "+discoveringPath("ethernet-1/1")] = Answer{} },
			want:   `node n1 (172.20.20.2:57400): port_discovering at /system/lldp/interface[name=ethernet-1/1]/admin-state: expected "enable", read nothing; ` + row11},
		{name: "neighbour on the wrong far port", check: CheckNeighbor, node: "n1",
			change: neighbourAt(a1, "ethernet-1/1", [2]string{"n2", "ethernet-1/2"}),
			want:   `node n1 (172.20.20.2:57400): neighbor at /system/lldp/interface[name=ethernet-1/1]/neighbor: expected n2 ethernet-1/1, read n2 ethernet-1/2; ` + row11 + link},
		{name: "two neighbours", check: CheckNeighbor, node: "n1",
			change: neighbourAt(a1, "ethernet-1/1", [2]string{"n2", "ethernet-1/1"}, [2]string{"n3", "ethernet-1/1"}),
			want:   `node n1 (172.20.20.2:57400): neighbor at /system/lldp/interface[name=ethernet-1/1]/neighbor: expected n2 ethernet-1/1, read 2 entries: n2 ethernet-1/1, n3 ethernet-1/1; ` + row11 + link},
		{name: "neighbour list empty", check: CheckNeighbor, node: "n1",
			change: neighbourAt(a1, "ethernet-1/1"),
			want:   `node n1 (172.20.20.2:57400): neighbor at /system/lldp/interface[name=ethernet-1/1]/neighbor: expected n2 ethernet-1/1, read nothing; ` + row11 + link},
		{name: "port reads nothing", check: CheckNeighbor, node: "n1",
			change: func(_ *BootInput, f *fakeReader) { f.answers[a1+" "+neighborPath("ethernet-1/1")] = Answer{} },
			want:   `node n1 (172.20.20.2:57400): neighbor at /system/lldp/interface[name=ethernet-1/1]/neighbor: expected n2 ethernet-1/1, read nothing; ` + row11 + link},
		{name: "neighbour not a list", check: CheckNeighbor, node: "n1",
			change: neighbourIs(a1, "ethernet-1/1", map[string]any{"system-name": "n2", "port-id": "ethernet-1/1"}),
			want:   `node n1 (172.20.20.2:57400): neighbor at /system/lldp/interface[name=ethernet-1/1]/neighbor: expected n2 ethernet-1/1, read {"port-id":"ethernet-1/1","system-name":"n2"}, not a list; ` + row11 + link},
		{name: "neighbour without a system name", check: CheckNeighbor, node: "n1",
			change: neighbourIs(a1, "ethernet-1/1", []any{map[string]any{"id": "1A:EB:01:FF:00:00", "port-id": "ethernet-1/1"}}),
			want:   `node n1 (172.20.20.2:57400): neighbor at /system/lldp/interface[name=ethernet-1/1]/neighbor: expected n2 ethernet-1/1, read (no system-name) ethernet-1/1; ` + row11 + link},
		{name: "neighbour without a port id", check: CheckNeighbor, node: "n1",
			change: neighbourIs(a1, "ethernet-1/1", []any{map[string]any{"id": "1A:EB:01:FF:00:00", "system-name": "n2"}}),
			want:   `node n1 (172.20.20.2:57400): neighbor at /system/lldp/interface[name=ethernet-1/1]/neighbor: expected n2 ethernet-1/1, read n2 (no port-id); ` + row11 + link},
		// A cabled row the bundle's links do not name: its neighbour is not read, since
		// there is nothing to expect. Its other two reads add to the healthy 24.
		{name: "no link on a cabled port", check: CheckNeighbor, node: "n1", reads: 24 + 2,
			change: func(in *BootInput, f *fakeReader) {
				port := "e1-3"
				in.Manifest.Mapping = append(in.Manifest.Mapping, compiler.MappingRow{Device: "n1", Interface: "ethernet-1/3",
					Iftype: "physical", Port: &port, Disposition: compiler.DispCabled})
				f.answers[a1+" "+enabledPath("ethernet-1/3")] = leaf("srl_nokia-interfaces:interface[name=ethernet-1/3]/admin-state", "enable")
				f.answers[a1+" "+discoveringPath("ethernet-1/3")] = leaf("srl_nokia-system:system/srl_nokia-lldp:lldp/interface[name=ethernet-1/3]/admin-state", "enable")
			},
			want: `node n1 (172.20.20.2:57400): neighbor at /system/lldp/interface[name=ethernet-1/3]/neighbor: the bundle names no link on port e1-3; checking mapping row n1:ethernet-1/3 (port e1-3, node name ethernet-1/3)`},
		// A link whose far end has no mapping row: n2's ethernet-1/1 row is gone, so n2
		// reads three paths fewer and n1 does not read the neighbour it cannot expect.
		{name: "no mapping row at the far end", check: CheckNeighbor, node: "n1", reads: 24 - 3 - 1,
			change: func(in *BootInput, _ *fakeReader) {
				in.Manifest.Mapping = slices.DeleteFunc(in.Manifest.Mapping, func(m compiler.MappingRow) bool {
					return m.Device == "n2" && m.Interface == "ethernet-1/1"
				})
			},
			want: `node n1 (172.20.20.2:57400): neighbor at /system/lldp/interface[name=ethernet-1/1]/neighbor: the bundle names no mapping row for n2 port e1-1, the far end; ` + row11 + link},
		{name: "port read transport error", check: CheckPortEnabled, node: "n1",
			change: func(_ *BootInput, f *fakeReader) {
				f.errs[a1+" "+enabledPath("ethernet-1/2")] = errors.New(`gNMI Get /interface[name=ethernet-1/2]/admin-state at 172.20.20.2:57400: code=DeadlineExceeded msg="context deadline exceeded"`)
			},
			want: `node n1 (172.20.20.2:57400): port_enabled at /interface[name=ethernet-1/2]/admin-state: gNMI Get /interface[name=ethernet-1/2]/admin-state at 172.20.20.2:57400: code=DeadlineExceeded msg="context deadline exceeded"; checking mapping row n1:ethernet-1/2 (port e1-2, node name ethernet-1/2)`},
		{name: "neighbour read transport error", check: CheckNeighbor, node: "n1",
			change: func(_ *BootInput, f *fakeReader) {
				f.errs[a1+" "+neighborPath("ethernet-1/1")] = errors.New(`gNMI Get /system/lldp/interface[name=ethernet-1/1]/neighbor at 172.20.20.2:57400: code=DeadlineExceeded msg="context deadline exceeded"`)
			},
			want: `node n1 (172.20.20.2:57400): neighbor at /system/lldp/interface[name=ethernet-1/1]/neighbor: gNMI Get /system/lldp/interface[name=ethernet-1/1]/neighbor at 172.20.20.2:57400: code=DeadlineExceeded msg="context deadline exceeded"; ` + row11 + link},
		{name: "version not listed", check: CheckVersion, node: "n3",
			change: func(_ *BootInput, f *fakeReader) {
				f.answers[a3+" "+versionPath] = leaf("srl_nokia-system:system/srl_nokia-system-info:information/version", "v23.10.1-218-ga3fc1bea5a")
			},
			want: `node n3 (172.20.20.4:57400): version at /system/information/version: read "v23.10.1-218-ga3fc1bea5a", which matches none of the package's versions [24.7]`},
		{name: "version read nothing", check: CheckVersion, node: "n3",
			change: func(_ *BootInput, f *fakeReader) { f.answers[a3+" "+versionPath] = Answer{} },
			want:   `node n3 (172.20.20.4:57400): version at /system/information/version: read nothing, which matches none of the package's versions [24.7]`},
		{name: "ready over budget", check: CheckReadiness, node: "n3",
			change: withRecordNode("n3", func(n *wire.TwinNode) { n.ReadyAfterS = 61.5 }),
			want:   `node n3: ready after 61.5s, over the package's readiness budget of 60s`},
		{name: "node not in the record", check: CheckBooted, node: "n3", reads: 2 * 8,
			change: func(in *BootInput, _ *fakeReader) { in.Record.Nodes = in.Record.Nodes[:2] },
			want:   `node n3 is not in the record`},
		{name: "node without an address", check: CheckBooted, node: "n3", reads: 2 * 8,
			change: withRecordNode("n3", func(n *wire.TwinNode) { n.MgmtIPv4 = "" }),
			want:   `node n3 has no address in the record`},
		{name: "node without a container", check: CheckBooted, node: "n3",
			change: withRecordNode("n3", func(n *wire.TwinNode) { n.Container = "" }),
			want:   `node n3 has no container in the record`},
		{name: "package without conformance", check: CheckDeclared, reads: -1,
			change: withPackage(func(p *psp.PSP) { p.Conformance = nil }),
			want:   `package nokia_srlinux declares no conformance block; the boot half cannot read its nodes`},
		{name: "package probe not gNMI", check: CheckDeclared, reads: -1,
			change: withPackage(func(p *psp.PSP) { p.Readiness.Probe = "netconf_get" }),
			want:   `package nokia_srlinux's readiness probe is netconf_get; the boot half reads by gNMI only`},
		{name: "package not loaded", check: CheckDeclared, reads: -1,
			change: func(in *BootInput, _ *fakeReader) { in.Packages = packageSet{} },
			want:   `package nokia_srlinux is not among the packages loaded; the boot half cannot read its nodes`},
	} {
		t.Run(c.name, func(t *testing.T) {
			in, reader := threeNode(t)
			c.change(&in, reader)
			reports := Boot(context.Background(), in)
			if len(reports) != 1 {
				t.Fatalf("%d reports, want 1", len(reports))
			}
			r := reports[0]
			if got := messages(r.Failures); !slices.Equal(got, []string{c.want}) {
				t.Fatalf("failures =\n%s\nwant\n%s", strings.Join(got, "\n"), c.want)
			}
			if f := r.Failures[0]; f.Check != c.check || f.Node != c.node || f.Package != "nokia_srlinux" {
				t.Errorf("failure under check %q, node %q, package %q; want %q, %q, nokia_srlinux", f.Check, f.Node, f.Package, c.check, c.node)
			}
			// The failure is the node's alone: every other node still passes.
			for _, n := range r.Nodes {
				failed := n.Name == c.node || c.node == ""
				if failed == (n.Passed != "") {
					t.Errorf("node %s: success line %q beside a failure on node %q", n.Name, n.Passed, c.node)
				}
			}
			reads := 3 * (2 + 2*3)
			switch {
			case c.reads > 0:
				reads = c.reads
			case c.reads < 0:
				reads = 0
			}
			if len(reader.calls) != reads {
				t.Errorf("%d reads, want %d", len(reader.calls), reads)
			}
		})
	}

	// A node nothing answers at fails every read, each under its own check with the
	// transport's error, in check order: each path is read once, none is skipped and none
	// retried. The other nodes still pass.
	t.Run("unreachable node", func(t *testing.T) {
		in, reader := threeNode(t)
		for key := range reader.answers {
			if path, ok := strings.CutPrefix(key, a3+" "); ok {
				reader.errs[key] = refused(path, a3)
			}
		}
		r := Boot(context.Background(), in)[0]

		const row31, row32 = "mapping row n3:ethernet-1/1 (port e1-1, node name ethernet-1/1)",
			"mapping row n3:ethernet-1/2 (port e1-2, node name ethernet-1/2)"
		const link31, link32 = " for link n2:ethernet-1/2|n3:ethernet-1/1", " for link n1:ethernet-1/2|n3:ethernet-1/2"
		failed := func(check, path, row string) string {
			m := "node n3 (172.20.20.4:57400): " + check + " at " + path + ": gNMI Get " + path +
				` at 172.20.20.4:57400: code=Unavailable msg="connection error: desc = \"transport: Error while dialing: dial tcp 172.20.20.4:57400: connect: connection refused\""`
			if row != "" {
				m += "; checking " + row
			}
			return m
		}
		want := []string{
			failed("host_name", hostNamePath, ""),
			failed("port_enabled", enabledPath("ethernet-1/1"), row31),
			failed("port_enabled", enabledPath("ethernet-1/2"), row32),
			failed("port_discovering", discoveringPath("ethernet-1/1"), row31),
			failed("port_discovering", discoveringPath("ethernet-1/2"), row32),
			failed("neighbor", neighborPath("ethernet-1/1"), row31+link31),
			failed("neighbor", neighborPath("ethernet-1/2"), row32+link32),
			failed("version", versionPath, ""),
		}
		if got := messages(r.Failures); !slices.Equal(got, want) {
			t.Fatalf("failures =\n%s\nwant\n%s", strings.Join(got, "\n"), strings.Join(want, "\n"))
		}
		wantChecks := []string{CheckHostName, CheckPortEnabled, CheckPortEnabled, CheckPortDiscovering,
			CheckPortDiscovering, CheckNeighbor, CheckNeighbor, CheckVersion}
		for i, f := range r.Failures {
			if f.Check != wantChecks[i] || f.Node != "n3" {
				t.Errorf("failure %d under check %q, node %q; want %q, n3", i+1, f.Check, f.Node, wantChecks[i])
			}
		}
		if len(reader.calls) != 3*(2+2*3) {
			t.Errorf("%d reads, want %d: one per path, the unreachable node's included", len(reader.calls), 3*(2+2*3))
		}
		if dup := duplicates(reader.calls); len(dup) > 0 {
			t.Errorf("paths read more than once: %v", dup)
		}
		for _, n := range r.Nodes {
			if (n.Name == "n3") == (n.Passed != "") {
				t.Errorf("node %s: success line %q beside the failures on n3", n.Name, n.Passed)
			}
		}
	})

	t.Run("no push recorded", func(t *testing.T) {
		in, _ := threeNode(t)
		withRecordNode("n1", func(n *wire.TwinNode) { n.Artifact = nil })(&in, nil)
		r := Boot(context.Background(), in)[0]
		if len(r.Failures) != 0 || !strings.HasSuffix(r.Nodes[0].Passed, "; read with no push recorded") {
			t.Errorf("failures %v, n1's line %q; want none, and the line to say no push was recorded", messages(r.Failures), r.Nodes[0].Passed)
		}
	})
}

func duplicates(s []string) []string {
	seen := map[string]bool{}
	var dup []string
	for _, v := range s {
		if seen[v] {
			dup = append(dup, v)
		}
		seen[v] = true
	}
	return dup
}

// On a twin whose platform names its ports otherwise than production (the lossy golden),
// every port path is rendered with the row's node name, and a neighbour's far port is
// expected under the far node's own name: s1 sees c1's Ethernet1/1 as Ethernet1. One
// report per package, in id order. The fake answers only node-name paths, so a read under
// a production name fails.
func TestBootHalfReadsUnderNodeNames(t *testing.T) {
	chassis, err := psp.ParseFile(repo("testdata", "psp", "lossy", "chassisos.yaml"), psp.OriginOverride)
	if err != nil {
		t.Fatal(err)
	}
	chassis.Platform.Versions = []string{"4.32"}
	// Illustrative, as the package is: never read from a node.
	chassis.Conformance = &psp.Conformance{
		HostName: "/system/config/hostname",
		Version:  "/system/state/software-version",
		Port: psp.PortChecks{
			Enabled:     psp.ValueAt{Path: "/interfaces/interface[name={node_name}]/config/enabled", Value: "true"},
			Discovering: psp.ValueAt{Path: "/lldp/interfaces/interface[name={node_name}]/config/enabled", Value: "true"},
			Neighbor:    psp.NeighborAt{Path: "/lldp/interfaces/interface[name={node_name}]/neighbors/neighbor", SystemName: "system-name", PortID: "port-id"},
		},
	}

	const (
		c1 = "172.20.20.2:57400"
		c2 = "172.20.20.3:57400"
		s1 = "172.20.20.4:57400"
	)
	f := &fakeReader{answers: map[string]Answer{}, errs: map[string]error{}}
	chassisNode := func(addr, name string, far map[string][2]string) {
		f.answers[addr+" /system/config/hostname"] = leaf("openconfig-system:system/config/hostname", name)
		f.answers[addr+" /system/state/software-version"] = leaf("openconfig-system:system/state/software-version", "4.32.1F")
		for nodeName, n := range far {
			f.answers[addr+" /interfaces/interface[name="+nodeName+"]/config/enabled"] = leaf("openconfig-interfaces:interfaces/interface[name="+nodeName+"]/config/enabled", true)
			f.answers[addr+" /lldp/interfaces/interface[name="+nodeName+"]/config/enabled"] = leaf("openconfig-lldp:lldp/interfaces/interface[name="+nodeName+"]/config/enabled", true)
			// The subtree comes back at the list entry, two levels above the list.
			f.answers[addr+" /lldp/interfaces/interface[name="+nodeName+"]/neighbors/neighbor"] = leaf(
				"openconfig-lldp:lldp/interfaces/interface[name="+nodeName+"]",
				map[string]any{"neighbors": map[string]any{"neighbor": []any{map[string]any{"system-name": n[0], "port-id": n[1]}}}})
		}
	}
	chassisNode(c1, "c1", map[string][2]string{"Ethernet1": {"s1", "ethernet-1/1"}, "Ethernet49": {"c2", "Ethernet49"}})
	chassisNode(c2, "c2", map[string][2]string{"Ethernet49": {"c1", "Ethernet49"}, "Ethernet1": {"s1", "ethernet-1/2/1"}})
	f.answers[s1+" "+hostNamePath] = leaf("srl_nokia-system:system/srl_nokia-system-name:name/host-name", "s1")
	f.answers[s1+" "+versionPath] = leaf("srl_nokia-system:system/srl_nokia-system-info:information/version", readVersion)
	for port, far := range map[string][2]string{"ethernet-1/1": {"c1", "Ethernet1"}, "ethernet-1/2/1": {"c2", "Ethernet1"}} {
		f.answers[s1+" "+enabledPath(port)] = leaf("srl_nokia-interfaces:interface[name="+port+"]/admin-state", "enable")
		f.answers[s1+" "+discoveringPath(port)] = leaf("srl_nokia-system:system/srl_nokia-lldp:lldp/interface[name="+port+"]/admin-state", "enable")
		f.answers[s1+" "+neighborPath(port)] = neighbours(port, far)
	}

	reports := Boot(context.Background(), BootInput{
		Record: wire.TwinRecord{Nodes: []wire.TwinNode{
			recordNode("s1", "172.20.20.4", "nokia_srlinux", "embedded", 16),
			recordNode("c2", "172.20.20.3", "chassisos", "override", 20.5),
			recordNode("c1", "172.20.20.2", "chassisos", "override", 20.25),
		}},
		Manifest: goldenManifest(t, "lossy"),
		Packages: packageSet{"chassisos": chassis, "nokia_srlinux": shipped(t)},
		Reader:   f,
		Getenv:   func(string) (string, bool) { return "", false },
	})
	if len(reports) != 2 || reports[0].Package != "chassisos" || reports[1].Package != "nokia_srlinux" {
		t.Fatalf("reports for %v, want chassisos then nokia_srlinux", packagesOf(reports))
	}
	var lines []string
	for _, r := range reports {
		if len(r.Failures) != 0 {
			t.Errorf("package %s failed:\n%s", r.Package, strings.Join(messages(r.Failures), "\n"))
		}
		for _, n := range r.Nodes {
			lines = append(lines, n.Passed)
		}
	}
	want := []string{
		"node c1 (172.20.20.2:57400): booted; ready after 20.25s of 60s; host name c1; 2 cabled ports enabled and discovering; 2 neighbours as the bundle's links name them; version 4.32.1F (listed: 4.32); read after the push",
		"node c2 (172.20.20.3:57400): booted; ready after 20.5s of 60s; host name c2; 2 cabled ports enabled and discovering; 2 neighbours as the bundle's links name them; version 4.32.1F (listed: 4.32); read after the push",
		"node s1 (172.20.20.4:57400): booted; ready after 16s of 60s; host name s1; 2 cabled ports enabled and discovering; 2 neighbours as the bundle's links name them; version " + readVersion + " (listed: 24.7); read after the push",
	}
	if !slices.Equal(lines, want) {
		t.Errorf("success lines =\n%s\nwant\n%s", strings.Join(lines, "\n"), strings.Join(want, "\n"))
	}
	if len(f.calls) != 3*(2+2*3) {
		t.Errorf("%d reads, want %d", len(f.calls), 3*(2+2*3))
	}
}

func packagesOf(rs []Report) []string {
	var out []string
	for _, r := range rs {
		out = append(out, r.Package)
	}
	return out
}

// leafAt on the answers a booted node gave: a leaf at the leaf, a subtree at its list
// entry under a module-prefixed update path, and no update; and on the cases the descent
// must refuse rather than guess.
func TestLeafAtOnR3sShapes(t *testing.T) {
	neighbor := []any{map[string]any{"system-name": "n2", "port-id": "ethernet-1/1"}}
	for _, c := range []struct {
		name      string
		answer    Answer
		requested string
		want      any
		ok        bool
	}{
		{"leaf", leaf("srl_nokia-system:system/srl_nokia-system-name:name/host-name", "n1"),
			"/system/name/host-name", "n1", true},
		{"subtree at the list entry", leaf("srl_nokia-system:system/srl_nokia-lldp:lldp/interface[name=ethernet-1/1]",
			map[string]any{"neighbor": neighbor}),
			"/system/lldp/interface[name=ethernet-1/1]/neighbor", neighbor, true},
		{"absent", Answer{}, "/system/lldp/interface[name=ethernet-1/3]/neighbor", nil, false},
		{"member with a module prefix", leaf("srl_nokia-system:system", map[string]any{
			"srl_nokia-system-name:name": map[string]any{"host-name": "n1"}}),
			"/system/name/host-name", "n1", true},
		{"list entry picked by its key", leaf("srl_nokia-system:system/srl_nokia-lldp:lldp", map[string]any{
			"interface": []any{
				map[string]any{"name": "ethernet-1/2", "neighbor": []any{}},
				map[string]any{"name": "ethernet-1/1", "neighbor": neighbor},
			}}),
			"/system/lldp/interface[name=ethernet-1/1]/neighbor", neighbor, true},
		{"another list entry", leaf("srl_nokia-system:system/srl_nokia-lldp:lldp/interface[name=ethernet-1/2]",
			map[string]any{"neighbor": neighbor}),
			"/system/lldp/interface[name=ethernet-1/1]/neighbor", nil, false},
		{"answer deeper than asked", leaf("srl_nokia-system:system/srl_nokia-system-name:name/host-name", "n1"),
			"/system/name", nil, false},
		{"member missing", leaf("srl_nokia-system:system/srl_nokia-lldp:lldp/interface[name=ethernet-1/1]",
			map[string]any{"admin-state": "enable"}),
			"/system/lldp/interface[name=ethernet-1/1]/neighbor", nil, false},
		// Every update is kept, so the descent picks the one that leads to the path and
		// is not stopped by an earlier one about something else.
		{"the second update leads to the path", Answer{Updates: []Update{
			{Path: "srl_nokia-system:system/srl_nokia-lldp:lldp/interface[name=ethernet-1/2]", Value: map[string]any{"neighbor": []any{}}},
			{Path: "srl_nokia-system:system/srl_nokia-lldp:lldp/interface[name=ethernet-1/1]", Value: map[string]any{"neighbor": neighbor}},
		}}, "/system/lldp/interface[name=ethernet-1/1]/neighbor", neighbor, true},
	} {
		got, ok := leafAt(c.answer, c.requested)
		if ok != c.ok || !reflect.DeepEqual(got, c.want) {
			t.Errorf("%s: leafAt = %#v, %t; want %#v, %t", c.name, got, ok, c.want, c.ok)
		}
	}
}

// entriesAt takes a requested list's entries from either shape a node answers a whole
// list in, and says which of the three things it found:
// the entries, something that is not a list, or nothing.
func TestEntriesAtOnBothShapes(t *testing.T) {
	const listPath = "/lldp/interfaces/interface[name=Ethernet1]/neighbors/neighbor"
	srl := map[string]any{"system-name": "s1", "port-id": "ethernet-1/1"}
	eos := map[string]any{"openconfig-lldp:id": "1", "openconfig-lldp:state": map[string]any{"system-name": "s1", "port-id": "ethernet-1/1"}}
	eos2 := map[string]any{"openconfig-lldp:id": "2", "openconfig-lldp:state": map[string]any{"system-name": "e2", "port-id": "Ethernet7"}}

	for _, c := range []struct {
		name    string
		answer  Answer
		want    []any
		value   any
		outcome listOutcome
	}{
		{name: "one update per keyed entry", answer: keyedEntries(listPath, "id", eos, eos2),
			want: []any{eos, eos2}, outcome: listEntries},
		{name: "one update at the list with the entries inside",
			answer:  leaf("lldp/interfaces/interface[name=Ethernet1]/neighbors/neighbor", []any{eos}),
			want:    []any{eos},
			outcome: listEntries},
		{name: "one update at the container above, the list inside",
			answer: leaf("lldp/interfaces/interface[name=Ethernet1]/neighbors",
				map[string]any{"openconfig-lldp:neighbor": []any{eos}}),
			want:    []any{eos},
			outcome: listEntries},
		{name: "one update two containers above, as SR Linux answers a subtree",
			answer: leaf("openconfig-lldp:lldp/interfaces/interface[name=Ethernet1]",
				map[string]any{"neighbors": map[string]any{"neighbor": []any{srl}}}),
			want:    []any{srl},
			outcome: listEntries},
		{name: "a container naming the list, at the list's own path",
			answer: leaf("lldp/interfaces/interface[name=Ethernet1]/neighbors/neighbor",
				map[string]any{"openconfig-lldp:neighbor": []any{eos}}),
			want:    []any{eos},
			outcome: listEntries},
		{name: "an empty list is a list", answer: leaf("lldp/interfaces/interface[name=Ethernet1]/neighbors/neighbor", []any{}),
			outcome: listEntries},
		{name: "no update", answer: Answer{}, outcome: listNothing},
		{name: "another port's entries", answer: keyedEntries("/lldp/interfaces/interface[name=Ethernet2]/neighbors/neighbor", "id", eos),
			outcome: listNothing},
		{name: "not a list", answer: leaf("lldp/interfaces/interface[name=Ethernet1]/neighbors/neighbor", srl),
			value: srl, outcome: listNotAList},
	} {
		t.Run(c.name, func(t *testing.T) {
			entries, value, outcome := entriesAt(c.answer, listPath)
			if outcome != c.outcome {
				t.Fatalf("outcome = %d, want %d", outcome, c.outcome)
			}
			if !reflect.DeepEqual(entries, c.want) {
				t.Errorf("entries = %#v, want %#v", entries, c.want)
			}
			if !reflect.DeepEqual(value, c.value) {
				t.Errorf("value = %#v, want %#v", value, c.value)
			}
		})
	}
}

// eosFacet is a conformance facet for cEOS and eosPackage a package declaring it, built
// here rather than read from psp/arista_eos.yaml, so the reader's tests stand apart from
// the shipped package. Every path and value is one a booted cEOS 4.32.0.2F node answered.
func eosPackage() *psp.PSP {
	plaintext := false
	return &psp.PSP{
		Platform:  psp.Identity{ID: "arista_eos", Vendor: "arista", NOS: "eos", Versions: []string{"4.32"}, DeviceClass: "switch"},
		Path:      "psp/arista_eos.yaml",
		Readiness: psp.Readiness{Probe: psp.ProbeGNMIGet, Path: "/system/state/hostname", Encoding: "json_ietf", Port: 6030, TimeoutS: 90, TLS: &plaintext, Login: psp.Login{UsernameEnv: "FYLGJA_EOS_USERNAME", PasswordEnv: "FYLGJA_EOS_PASSWORD"}},
		Conformance: &psp.Conformance{
			HostName: "/system/state/hostname",
			Version:  "/system/state/software-version",
			Port: psp.PortChecks{
				Enabled: psp.ValueAt{Path: "/interfaces/interface[name={node_name}]/state/admin-status", Value: "UP"},
				// The default is not reported: `enabled` is absent while LLDP runs and
				// false when it is off.
				Discovering: psp.ValueAt{Path: "/lldp/interfaces/interface[name={node_name}]/state/enabled", Value: "true", Absent: "true"},
				Neighbor: psp.NeighborAt{
					Path:       "/lldp/interfaces/interface[name={node_name}]/neighbors/neighbor",
					SystemName: "state/system-name",
					PortID:     "state/port-id",
				},
			},
		},
	}
}

// The mixed twin's addresses and the version cEOS reads.
const (
	eosVersion = "4.32.0.2F-41889544.43202F (engineering build)"
	mixedS1    = "172.20.20.2:57400"
	mixedE1    = "172.20.20.3:6030"
)

// eosPaths are the facet's paths for one port of an EOS node, rendered.
func eosEnabledPath(port string) string {
	return "/interfaces/interface[name=" + port + "]/state/admin-status"
}

func eosDiscoveringPath(port string) string {
	return "/lldp/interfaces/interface[name=" + port + "]/state/enabled"
}

func eosNeighborPath(port string) string {
	return "/lldp/interfaces/interface[name=" + port + "]/neighbors/neighbor"
}

// eosEntry is one neighbour entry as cEOS writes it: the far node and the far port one
// container down, under `state`, with module prefixes on the members.
func eosEntry(id, farNode, farPort string) map[string]any {
	return map[string]any{
		"openconfig-lldp:id": id,
		"openconfig-lldp:state": map[string]any{
			"system-name": farNode, "port-id": farPort, "port-id-type": "INTERFACE_NAME",
		},
	}
}

// mixedTwin is one link of a mixed twin as the boot half reads it: an SR Linux node and a
// cEOS node cabled to each other, the manifest and the record built here. The reader answers each node in its
// own shape: SR Linux one update at the list entry, cEOS one update per keyed entry, and
// nothing at all for a port whose LLDP `enabled` holds its unreported default.
func mixedTwin(t *testing.T) (BootInput, *fakeReader) {
	t.Helper()
	srlPort, eosPort := "e1-1", "eth1"
	srlName, eosName := "ethernet-1/1", "Ethernet1"
	manifest := compiler.Manifest{
		BundleVersion: "3",
		Nodes: []compiler.ManifestNode{
			{Name: "e1", Platform: "arista_eos", PSP: compiler.ManifestPSP{ID: "arista_eos", Source: "embedded"}},
			{Name: "s1", Platform: "nokia_srlinux", PSP: compiler.ManifestPSP{ID: "nokia_srlinux", Source: "embedded"}},
		},
		Mapping: []compiler.MappingRow{
			{Device: "e1", Interface: "Ethernet1", Iftype: "physical", Port: &eosPort, NodeName: &eosName, Disposition: compiler.DispCabled},
			{Device: "s1", Interface: "ethernet-1/1", Iftype: "physical", Port: &srlPort, NodeName: &srlName, Disposition: compiler.DispCabled},
		},
		Links: []compiler.CabledLink{{
			ID: "e1:Ethernet1|s1:ethernet-1/1",
			A:  compiler.NodePort{Node: "e1", Port: eosPort},
			B:  compiler.NodePort{Node: "s1", Port: srlPort},
		}},
	}

	f := &fakeReader{answers: map[string]Answer{}, errs: map[string]error{}}
	// The cEOS node: a leaf at the leaf, the neighbour one update per keyed entry, and
	// LLDP's `enabled` absent while it runs.
	f.answers[mixedE1+" /system/state/hostname"] = leaf("openconfig-system:system/state/hostname", "e1")
	f.answers[mixedE1+" /system/state/software-version"] = leaf("openconfig-system:system/state/software-version", eosVersion)
	f.answers[mixedE1+" "+eosEnabledPath(eosName)] = leaf("openconfig-interfaces:interfaces/interface[name="+eosName+"]/state/admin-status", "UP")
	f.answers[mixedE1+" "+eosDiscoveringPath(eosName)] = Answer{}
	f.answers[mixedE1+" "+eosNeighborPath(eosName)] = keyedEntries(eosNeighborPath(eosName), "id", eosEntry("1", "s1", srlName))
	// The SR Linux node: M6's shapes, naming the far port under cEOS's own name.
	f.answers[mixedS1+" "+hostNamePath] = leaf("srl_nokia-system:system/srl_nokia-system-name:name/host-name", "s1")
	f.answers[mixedS1+" "+versionPath] = leaf("srl_nokia-system:system/srl_nokia-system-info:information/version", readVersion)
	f.answers[mixedS1+" "+enabledPath(srlName)] = leaf("srl_nokia-interfaces:interface[name="+srlName+"]/admin-state", "enable")
	f.answers[mixedS1+" "+discoveringPath(srlName)] = leaf("srl_nokia-system:system/srl_nokia-lldp:lldp/interface[name="+srlName+"]/admin-state", "enable")
	f.answers[mixedS1+" "+neighborPath(srlName)] = neighbours(srlName, [2]string{"e1", eosName})

	return BootInput{
		Record: wire.TwinRecord{TwinVersion: "2", Lab: "fylgja", Nodes: []wire.TwinNode{
			recordNode("e1", "172.20.20.3", "arista_eos", "embedded", 9.3),
			recordNode("s1", "172.20.20.2", "nokia_srlinux", "embedded", 1.1),
		}},
		Manifest: manifest,
		Packages: packageSet{"arista_eos": eosPackage(), "nokia_srlinux": shipped(t)},
		Reader:   f,
		Getenv:   func(string) (string, bool) { return "", false },
	}, f
}

// The boot half on a mixed twin, with each node answering in its own shape: both list
// shapes are read, a facet's
// `absent` stands for the value a node reports nothing for, and each end names the far
// port under the far node's own name. Then every new wording, each from one change to
// what the node answered, asserted whole.
func TestBootHalfOnAMixedTwin(t *testing.T) {
	t.Run("healthy", func(t *testing.T) {
		in, reader := mixedTwin(t)
		reports := Boot(context.Background(), in)
		if len(reports) != 2 || reports[0].Package != "arista_eos" || reports[1].Package != "nokia_srlinux" {
			t.Fatalf("reports for %v, want arista_eos then nokia_srlinux", packagesOf(reports))
		}
		var lines []string
		for _, r := range reports {
			if len(r.Failures) != 0 {
				t.Errorf("package %s failed:\n%s", r.Package, strings.Join(messages(r.Failures), "\n"))
			}
			if r.BootHalf != BootHalfTier3 {
				t.Errorf("package %s boot half = %q, want %q", r.Package, r.BootHalf, BootHalfTier3)
			}
			for _, n := range r.Nodes {
				lines = append(lines, n.Passed)
			}
		}
		want := []string{
			"node e1 (172.20.20.3:6030): booted; ready after 9.3s of 90s; host name e1; 1 cabled port enabled and discovering; 1 neighbour as the bundle's links name them; version " + eosVersion + " (listed: 4.32); read after the push",
			"node s1 (172.20.20.2:57400): booted; ready after 1.1s of 60s; host name s1; 1 cabled port enabled and discovering; 1 neighbour as the bundle's links name them; version " + readVersion + " (listed: 24.7); read after the push",
		}
		if !slices.Equal(lines, want) {
			t.Errorf("success lines =\n%s\nwant\n%s", strings.Join(lines, "\n"), strings.Join(want, "\n"))
		}
		// The EOS node is read plaintext on its own port, the SR Linux node over TLS on
		// its own: the reader shares the probe's dial.
		for _, p := range reader.probes {
			switch p.Port {
			case 6030:
				if p.TLS == nil || *p.TLS || p.UsernameEnv != "FYLGJA_EOS_USERNAME" {
					t.Errorf("an EOS read went by probe %+v, want plaintext with the EOS login", p)
				}
			case 57400:
				if p.TLS != nil || p.UsernameEnv != "FYLGJA_SRLINUX_USERNAME" {
					t.Errorf("an SR Linux read went by probe %+v, want M6's TLS dial with its own login", p)
				}
			default:
				t.Errorf("a read went to port %d, want each package's own", p.Port)
			}
		}
		if len(reader.calls) != 2*(2+3) {
			t.Errorf("%d reads, want %d: one per path, no retry", len(reader.calls), 2*(2+3))
		}
	})

	const (
		eosRow  = "checking mapping row e1:Ethernet1 (port eth1, node name Ethernet1)"
		eosLink = " for link e1:Ethernet1|s1:ethernet-1/1"
	)
	for _, c := range []struct {
		name   string
		change func(*fakeReader)
		check  string
		node   string
		want   string
	}{
		// `absent` is what the node means by nothing; a value it does report and that is
		// not the facet's fails in M6's words.
		{name: "LLDP off on a port", check: CheckPortDiscovering, node: "e1",
			change: func(f *fakeReader) {
				f.answers[mixedE1+" "+eosDiscoveringPath("Ethernet1")] = leaf(
					"openconfig-lldp:lldp/interfaces/interface[name=Ethernet1]/state/enabled", false)
			},
			want: `node e1 (172.20.20.3:6030): port_discovering at /lldp/interfaces/interface[name=Ethernet1]/state/enabled: expected "true", read "false"; ` + eosRow},
		// A relative leaf the entry does not carry is named by the path the facet wrote.
		{name: "a neighbour entry without its relative system name", check: CheckNeighbor, node: "e1",
			change: func(f *fakeReader) {
				f.answers[mixedE1+" "+eosNeighborPath("Ethernet1")] = keyedEntries(eosNeighborPath("Ethernet1"), "id",
					map[string]any{"openconfig-lldp:id": "1", "openconfig-lldp:state": map[string]any{"port-id": "ethernet-1/1"}})
			},
			want: `node e1 (172.20.20.3:6030): neighbor at /lldp/interfaces/interface[name=Ethernet1]/neighbors/neighbor: expected s1 ethernet-1/1, read (no state/system-name) ethernet-1/1; ` + eosRow + eosLink},
		{name: "a neighbour entry without its relative port id", check: CheckNeighbor, node: "e1",
			change: func(f *fakeReader) {
				f.answers[mixedE1+" "+eosNeighborPath("Ethernet1")] = keyedEntries(eosNeighborPath("Ethernet1"), "id",
					map[string]any{"openconfig-lldp:id": "1", "openconfig-lldp:state": map[string]any{"system-name": "s1"}})
			},
			want: `node e1 (172.20.20.3:6030): neighbor at /lldp/interfaces/interface[name=Ethernet1]/neighbors/neighbor: expected s1 ethernet-1/1, read s1 (no state/port-id); ` + eosRow + eosLink},
		// An entry with no `state` container at all: the descent stops at the missing
		// element and names the whole relative path, not half of it.
		{name: "a neighbour entry with the leaves on the entry itself", check: CheckNeighbor, node: "e1",
			change: func(f *fakeReader) {
				f.answers[mixedE1+" "+eosNeighborPath("Ethernet1")] = keyedEntries(eosNeighborPath("Ethernet1"), "id",
					map[string]any{"id": "1", "system-name": "s1", "port-id": "ethernet-1/1"})
			},
			want: `node e1 (172.20.20.3:6030): neighbor at /lldp/interfaces/interface[name=Ethernet1]/neighbors/neighbor: expected s1 ethernet-1/1, read (no state/system-name) (no state/port-id); ` + eosRow + eosLink},
		// Two entries, the shape M6 read one update at, now read one update per entry.
		{name: "two keyed entries", check: CheckNeighbor, node: "e1",
			change: func(f *fakeReader) {
				f.answers[mixedE1+" "+eosNeighborPath("Ethernet1")] = keyedEntries(eosNeighborPath("Ethernet1"), "id",
					eosEntry("1", "s1", "ethernet-1/1"), eosEntry("2", "e2", "Ethernet7"))
			},
			want: `node e1 (172.20.20.3:6030): neighbor at /lldp/interfaces/interface[name=Ethernet1]/neighbors/neighbor: expected s1 ethernet-1/1, read 2 entries: s1 ethernet-1/1, e2 Ethernet7; ` + eosRow + eosLink},
		// A plaintext dial that met a TLS node, or a node that refused it: the
		// transport's error under the check that read it, the password already redacted
		// by the reader.
		{name: "a plaintext transport failure", check: CheckHostName, node: "e1",
			change: func(f *fakeReader) {
				f.errs[mixedE1+" /system/state/hostname"] = errors.New(
					`gNMI Get /system/state/hostname at 172.20.20.3:6030: code=Unavailable msg="connection error: desc = \"transport: authentication handshake failed: tls: first record does not look like a TLS handshake\""`)
			},
			want: `node e1 (172.20.20.3:6030): host_name at /system/state/hostname: gNMI Get /system/state/hostname at 172.20.20.3:6030: code=Unavailable msg="connection error: desc = \"transport: authentication handshake failed: tls: first record does not look like a TLS handshake\""`},
	} {
		t.Run(c.name, func(t *testing.T) {
			in, reader := mixedTwin(t)
			c.change(reader)
			reports := Boot(context.Background(), in)
			var got []string
			for _, r := range reports {
				got = append(got, messages(r.Failures)...)
			}
			if !slices.Equal(got, []string{c.want}) {
				t.Fatalf("failures =\n%s\nwant\n%s", strings.Join(got, "\n"), c.want)
			}
			for _, r := range reports {
				for _, f := range r.Failures {
					if f.Check != c.check || f.Node != c.node || f.Package != "arista_eos" {
						t.Errorf("failure under check %q, node %q, package %q; want %q, %q, arista_eos", f.Check, f.Node, f.Package, c.check, c.node)
					}
				}
				// The failure is that node's alone: the other end still passes.
				for _, n := range r.Nodes {
					if (n.Name == c.node) == (n.Passed != "") {
						t.Errorf("node %s: success line %q beside a failure on node %q", n.Name, n.Passed, c.node)
					}
				}
			}
		})
	}
}
