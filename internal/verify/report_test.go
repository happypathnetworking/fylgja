package verify

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/santhosh-tekuri/jsonschema/v6"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// read derives the input's assertions and reads them once.
func read(t *testing.T, in Input) Report {
	t.Helper()
	as, err := Derive(in.Manifest)
	if err != nil {
		t.Fatal(err)
	}
	return Read(context.Background(), in, as)
}

// find is the one assertion of a kind on a node's port ("" for host_name).
func find(t *testing.T, r Report, kind, node, port string) Assertion {
	t.Helper()
	for _, a := range r.Assertions {
		if a.Kind == kind && a.Node == node && a.Port == port {
			return a
		}
	}
	t.Fatalf("no %s assertion on %s:%s", kind, node, port)
	return Assertion{}
}

// outcomes is every assertion's outcome that is not held, by kind, node and port.
func outcomes(r Report) []string {
	var out []string
	for _, a := range r.Assertions {
		if a.Outcome != Held {
			out = append(out, fmt.Sprintf("%s %s:%s %s", a.Kind, a.Node, a.Port, a.Outcome))
		}
	}
	return out
}

// onceEach says each path was read exactly once, and the number of reads.
func onceEach(t *testing.T, f *fakeReader, want int) {
	t.Helper()
	if len(f.calls) != want {
		t.Errorf("%d reads, want %d: %q", len(f.calls), want, f.calls)
	}
	for key, n := range f.reads {
		if n != 1 {
			t.Errorf("%s read %d times, want once", key, n)
		}
	}
}

// A healthy twin holds every assertion: each path read once over each node's own package's
// probe, the record's claims held, nothing extra and nothing unread.
func TestReadHealthy(t *testing.T) {
	t.Run("three-node", func(t *testing.T) {
		in, f := threeNode(t)
		at := time.Date(2026, 10, 3, 18, 0, 0, 0, time.UTC)
		in.Now = func() time.Time { return at }
		r := read(t, in)
		if got := outcomes(r); got != nil {
			t.Errorf("not held: %q", got)
		}
		if !r.Conforms() || !r.AllRead() || r.Unread != nil || r.Extra != nil || !r.ReadAt.Equal(at) {
			t.Errorf("Conforms %v AllRead %v Unread %v Extra %v ReadAt %v", r.Conforms(), r.AllRead(), r.Unread, r.Extra, r.ReadAt)
		}
		onceEach(t, f, 15)
		for _, c := range r.Claims {
			if c.Outcome != Held {
				t.Errorf("claim %+v, want held", c)
			}
		}
		if got := r.Findings(); len(got) != 0 {
			t.Errorf("findings %v, want none", got)
		}
		want := []NodeRead{{"n1", srlinux, "172.20.20.2:57400"}, {"n2", srlinux, "172.20.20.3:57400"}, {"n3", srlinux, "172.20.20.4:57400"}}
		if !reflect.DeepEqual(r.Nodes, want) {
			t.Errorf("Nodes = %+v, want %+v", r.Nodes, want)
		}
		a := find(t, r, KindPortEnabled, "n1", "ethernet-1/2")
		if a.Path != srlEnabled("ethernet-1/2") || a.Expected != "enable" || a.Read != "enable" {
			t.Errorf("port assertion %+v, want the facet's path and value, read enable", a)
		}
		n := find(t, r, KindNeighbor, "n2", "ethernet-1/2")
		if n.Path != srlNeighbor("ethernet-1/2") || n.Read != "n3 ethernet-1/1" || !reflect.DeepEqual(n.Seen, []Neighbour{{"n3", "ethernet-1/1"}}) {
			t.Errorf("neighbour assertion %+v, want n3 ethernet-1/1 seen", n)
		}
	})
	// Each node over its own package's transport: SR Linux by TLS on 57400, cEOS plaintext
	// on 6030, and the far ends of both cross-vendor adjacencies each by its own name.
	t.Run("mixed", func(t *testing.T) {
		in, f := mixed(t)
		r := read(t, in)
		if got := outcomes(r); got != nil || !r.Conforms() || !r.AllRead() {
			t.Errorf("not held: %q", got)
		}
		onceEach(t, f, 15)
		for addr, want := range map[string]struct {
			port int
			tls  bool
		}{"172.20.20.2:57400": {57400, true}, "172.20.20.3:6030": {6030, false}, "172.20.20.4:6030": {6030, false}} {
			p, ok := f.probes[addr]
			if !ok || p.Port != want.port || wire.ProbeTLS(p) != want.tls {
				t.Errorf("%s read over %+v, want port %d, TLS %v", addr, p, want.port, want.tls)
			}
		}
		if p := f.probes["172.20.20.3:6030"]; p.UsernameEnv != "FYLGJA_EOS_USERNAME" || p.PasswordEnv != "FYLGJA_EOS_PASSWORD" {
			t.Errorf("e1's probe login %s/%s, want arista_eos's", p.UsernameEnv, p.PasswordEnv)
		}
	})
}

// Every outcome a read can give, each on a twin otherwise healthy, so the one
// assertion it changes is the only one not held.
func TestReadOutcomes(t *testing.T) {
	n1, n2, n3 := srl(threeNodeIP["n1"]), srl(threeNodeIP["n2"]), srl(threeNodeIP["n3"])
	for _, tc := range []struct {
		name   string
		change func(f *fakeReader)
		want   []string
		read   string // what the one changed assertion read
	}{
		{name: "failed on a wrong value",
			change: func(f *fakeReader) { f.set(n1, srlEnabled("ethernet-1/2"), srlEnabledIs("ethernet-1/2", "disable")) },
			want:   []string{"port_enabled n1:ethernet-1/2 failed"}, read: "disable"},
		{name: "a host name that is another's",
			change: func(f *fakeReader) { f.set(n2, srlHostName, srlHostNameIs("n9")) },
			want:   []string{"host_name n2: failed"}, read: "n9"},
		// SR Linux's facet declares no meaning for absence: no update is absent.
		{name: "absent under a facet that declares no absent value",
			change: func(f *fakeReader) { f.set(n1, srlEnabled("ethernet-1/2"), Answer{}) },
			want:   []string{"port_enabled n1:ethernet-1/2 absent"}},
		{name: "no host name",
			change: func(f *fakeReader) { f.set(n3, srlHostName, Answer{}) },
			want:   []string{"host_name n3: absent"}},
		{name: "no neighbour",
			change: func(f *fakeReader) { f.set(n1, srlNeighbor("ethernet-1/2"), Answer{}) },
			want:   []string{"neighbor n1:ethernet-1/2 absent"}},
		{name: "an empty neighbour list",
			change: func(f *fakeReader) {
				f.set(n1, srlNeighbor("ethernet-1/2"), srlNeighbours("ethernet-1/2", []any{}))
			},
			want: []string{"neighbor n1:ethernet-1/2 absent"}},
		{name: "a far end naming the port differently",
			change: func(f *fakeReader) {
				f.set(n1, srlNeighbor("ethernet-1/1"), srlNeighbours("ethernet-1/1", srlEntries([2]string{"n2", "e1-1"})))
			},
			want: []string{"neighbor n1:ethernet-1/1 failed"}, read: "n2 e1-1"},
		{name: "two entries, one of them the far end",
			change: func(f *fakeReader) {
				f.set(n1, srlNeighbor("ethernet-1/1"), srlNeighbours("ethernet-1/1",
					srlEntries([2]string{"n2", "ethernet-1/1"}, [2]string{"n3", "ethernet-1/1"})))
			},
			want: []string{"neighbor n1:ethernet-1/1 failed"}, read: "2 entries: n2 ethernet-1/1, n3 ethernet-1/1"},
		{name: "a value that is not a list",
			change: func(f *fakeReader) {
				f.set(n1, srlNeighbor("ethernet-1/1"), srlNeighbours("ethernet-1/1", map[string]any{"x": 1}))
			},
			want: []string{"neighbor n1:ethernet-1/1 failed"}, read: `{"x":1}, not a list`},
		{name: "an entry missing a leaf",
			change: func(f *fakeReader) {
				f.set(n1, srlNeighbor("ethernet-1/1"), srlNeighbours("ethernet-1/1", []any{map[string]any{"system-name": "n2"}}))
			},
			want: []string{"neighbor n1:ethernet-1/1 failed"}, read: "n2 (no port-id)"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			in, f := threeNode(t)
			tc.change(f)
			r := read(t, in)
			if got := outcomes(r); !reflect.DeepEqual(got, tc.want) {
				t.Fatalf("not held: %q, want %q", got, tc.want)
			}
			if r.Conforms() || !r.AllRead() {
				t.Errorf("Conforms %v AllRead %v, want false and true", r.Conforms(), r.AllRead())
			}
			onceEach(t, f, 15)
			for _, a := range r.Assertions {
				if a.Outcome != Held && a.Read != tc.read {
					t.Errorf("%s read %q, want %q", describe(a), a.Read, tc.read)
				}
			}
		})
	}
}

// A facet that declares what the node means by reporting nothing reads that value: held
// when it is the value expected. The shipped arista_eos package declares
// one for discovering, which verify never reads, and none for enabled, so its enabled read
// as nothing is absent; a copy declaring enabled's absent value reads it as the value.
func TestReadAbsentUnderADeclaredAbsentValue(t *testing.T) {
	e1 := eosAddr(mixedIP["e1"])
	for _, tc := range []struct {
		name   string
		absent string
		want   []string
		read   string
	}{
		{"the shipped facet", "", []string{"port_enabled e1:Ethernet1 absent"}, ""},
		{"a facet declaring UP", "UP", nil, "UP"},
		{"a facet declaring DOWN", "DOWN", []string{"port_enabled e1:Ethernet1 failed"}, "DOWN"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			in, f := mixed(t)
			f.set(e1, eosEnabled("Ethernet1"), Answer{})
			if tc.absent != "" {
				p := *in.Packages.(packageSet)[eos]
				c := *p.Conformance
				c.Port.Enabled.Absent = tc.absent
				p.Conformance = &c
				in.Packages = packageSet{eos: &p, srlinux: in.Packages.(packageSet)[srlinux]}
			}
			r := read(t, in)
			if got := outcomes(r); !reflect.DeepEqual(got, tc.want) {
				t.Errorf("not held: %q, want %q", got, tc.want)
			}
			if a := find(t, r, KindPortEnabled, "e1", "Ethernet1"); a.Read != tc.read {
				t.Errorf("read %q, want %q", a.Read, tc.read)
			}
		})
	}
}

// A transport error on one path leaves that assertion unread and the node's other paths
// read; an unreachable node is unread at every path; each is one NodeError naming the first
// failed read, and every other node is read.
func TestReadTransportErrors(t *testing.T) {
	n2, n3 := srl(threeNodeIP["n2"]), srl(threeNodeIP["n3"])
	refused := func(path, addr string) error {
		return fmt.Errorf("gNMI Get %s at %s: code=Unavailable msg=%q", path, addr, "connection refused")
	}
	t.Run("one path", func(t *testing.T) {
		in, f := threeNode(t)
		f.errs[n2+" "+srlNeighbor("ethernet-1/1")] = refused(srlNeighbor("ethernet-1/1"), n2)
		r := read(t, in)
		if got, want := outcomes(r), []string{"neighbor n2:ethernet-1/1 unread"}; !reflect.DeepEqual(got, want) {
			t.Errorf("not held: %q, want %q", got, want)
		}
		onceEach(t, f, 15)
		want := []NodeError{{Node: "n2", Addr: n2, Path: srlNeighbor("ethernet-1/1"), Error: refused(srlNeighbor("ethernet-1/1"), n2).Error()}}
		if !reflect.DeepEqual(r.Unread, want) || r.AllRead() || r.Conforms() {
			t.Errorf("Unread = %+v, want %+v", r.Unread, want)
		}
		if a := find(t, r, KindNeighbor, "n2", "ethernet-1/1"); a.Error != want[0].Error {
			t.Errorf("assertion error %q, want the transport's", a.Error)
		}
	})
	t.Run("an unreachable node", func(t *testing.T) {
		in, f := threeNode(t)
		for key := range f.answers {
			if addr, path, _ := strings.Cut(key, " "); addr == n3 {
				f.errs[key] = refused(path, n3)
			}
		}
		r := read(t, in)
		want := []string{"host_name n3: unread", "port_enabled n3:ethernet-1/1 unread", "port_enabled n3:ethernet-1/2 unread",
			"neighbor n3:ethernet-1/1 unread", "neighbor n3:ethernet-1/2 unread"}
		if got := outcomes(r); !reflect.DeepEqual(got, want) {
			t.Errorf("not held: %q, want %q", got, want)
		}
		onceEach(t, f, 15)
		if len(r.Unread) != 1 || r.Unread[0].Node != "n3" || r.Unread[0].Path != srlHostName {
			t.Errorf("Unread = %+v, want n3 once, at its first path", r.Unread)
		}
	})
}

// A read the node did not answer at all (Unanswered: its transport failed) ends that node's
// read: its other paths are not dialled and are unread with that error, so a node that
// accepts no connection costs one attempt per read. A node's refusal of one path still
// leaves its other paths read.
func TestReadStopsDiallingASilentNode(t *testing.T) {
	n2 := srl(threeNodeIP["n2"])
	timedOut := &Unanswered{Err: fmt.Errorf("gNMI Get %s at %s: code=DeadlineExceeded msg=%q", srlHostName, n2, "context deadline exceeded")}
	t.Run("unanswered", func(t *testing.T) {
		in, f := threeNode(t)
		f.errs[n2+" "+srlHostName] = timedOut
		r := read(t, in)
		want := []string{"host_name n2: unread", "port_enabled n2:ethernet-1/1 unread", "port_enabled n2:ethernet-1/2 unread",
			"neighbor n2:ethernet-1/1 unread", "neighbor n2:ethernet-1/2 unread"}
		if got := outcomes(r); !reflect.DeepEqual(got, want) {
			t.Errorf("not held: %q, want %q", got, want)
		}
		onceEach(t, f, 11)
		for _, a := range r.Assertions {
			if a.Node == "n2" && a.Error != timedOut.Error() {
				t.Errorf("%s: error %q, want the unanswered read's", describe(a), a.Error)
			}
		}
		if wantErr := []NodeError{{Node: "n2", Addr: n2, Path: srlHostName, Error: timedOut.Error()}}; !reflect.DeepEqual(r.Unread, wantErr) {
			t.Errorf("Unread = %+v, want %+v", r.Unread, wantErr)
		}
	})
	t.Run("a later path unanswered keeps what was read", func(t *testing.T) {
		in, f := threeNode(t)
		f.errs[n2+" "+srlEnabled("ethernet-1/2")] = timedOut
		r := read(t, in)
		if a := find(t, r, KindHostName, "n2", ""); a.Outcome != Held {
			t.Errorf("n2's host name %s, want held: it was read before the node fell silent", a.Outcome)
		}
		if a := find(t, r, KindNeighbor, "n2", "ethernet-1/2"); a.Outcome != Unread || a.Error != timedOut.Error() {
			t.Errorf("n2's neighbour on ethernet-1/2 %s (%q), want unread with the silent read's error", a.Outcome, a.Error)
		}
		if f.reads[n2+" "+srlNeighbor("ethernet-1/2")] != 0 {
			t.Error("a path after the unanswered read was dialled")
		}
	})
	t.Run("a refusal of one path", func(t *testing.T) {
		in, f := threeNode(t)
		f.errs[n2+" "+srlHostName] = fmt.Errorf("gNMI Get %s at %s: code=NotFound msg=%q", srlHostName, n2, "no such path")
		r := read(t, in)
		if got, want := outcomes(r), []string{"host_name n2: unread"}; !reflect.DeepEqual(got, want) {
			t.Errorf("not held: %q, want %q: the node's other paths are read", got, want)
		}
		onceEach(t, f, 15)
	})
}

// Where a node's address comes from: the record's, else containerlab's; a node with neither
// is unread, and so is one containerlab does not report, each without a read; a node
// containerlab reports that the bundle does not name is listed and asserted nothing of.
// With containerlab not asked, the record's addresses alone are read.
func TestReadAddresses(t *testing.T) {
	n3 := srl(threeNodeIP["n3"])
	t.Run("the record has none: containerlab's", func(t *testing.T) {
		in, f := threeNode(t)
		in.Record.Nodes[2].MgmtIPv4 = ""
		r := read(t, in)
		if !r.Conforms() || r.Nodes[2].Addr != n3 {
			t.Errorf("n3 at %q, not held %q", r.Nodes[2].Addr, outcomes(r))
		}
		onceEach(t, f, 15)
	})
	t.Run("the record's before containerlab's", func(t *testing.T) {
		in, _ := threeNode(t)
		in.Lab[2].MgmtIPv4 = "172.20.20.99"
		if r := read(t, in); !r.Conforms() || r.Nodes[2].Addr != n3 {
			t.Errorf("n3 at %q, want the record's %s", r.Nodes[2].Addr, n3)
		}
	})
	t.Run("no address anywhere", func(t *testing.T) {
		in, f := threeNode(t)
		in.Record.Nodes[2].MgmtIPv4, in.Lab[2].MgmtIPv4 = "", ""
		r := read(t, in)
		unreadN3(t, r, "node n3 has no address in the record or from containerlab")
		onceEach(t, f, 10)
	})
	// containerlab 0.79 reports an exited container's address as N/A, which its inspection
	// cuts to N: an address that is not an IP address is none, and is not dialled.
	t.Run("containerlab's N/A and the record none", func(t *testing.T) {
		in, f := threeNode(t)
		in.Record.Nodes[2].MgmtIPv4, in.Lab[2].MgmtIPv4 = "", "N"
		r := read(t, in)
		unreadN3(t, r, "node n3 has no address in the record or from containerlab")
		onceEach(t, f, 10)
		for _, call := range f.calls {
			if strings.HasPrefix(call, "N:") {
				t.Errorf("read %s, want n3 not dialled", call)
			}
		}
	})
	t.Run("the record's N/A: containerlab's", func(t *testing.T) {
		in, f := threeNode(t)
		in.Record.Nodes[2].MgmtIPv4 = "N"
		if r := read(t, in); !r.Conforms() || r.Nodes[2].Addr != n3 {
			t.Errorf("n3 at %q, not held %q, want containerlab's %s", r.Nodes[2].Addr, outcomes(r), n3)
		}
		onceEach(t, f, 15)
	})
	t.Run("containerlab does not report the node", func(t *testing.T) {
		in, f := threeNode(t)
		in.Lab = in.Lab[:2]
		r := read(t, in)
		unreadN3(t, r, "containerlab does not report node n3, which the staged bundle names; nothing to read")
		onceEach(t, f, 10)
	})
	t.Run("containerlab not asked", func(t *testing.T) {
		in, f := threeNode(t)
		in.Lab = nil
		if r := read(t, in); !r.Conforms() || !r.AllRead() || r.Extra != nil {
			t.Errorf("not held %q, extra %v", outcomes(r), r.Extra)
		}
		onceEach(t, f, 15)
	})
	t.Run("a node the bundle does not name", func(t *testing.T) {
		in, f := threeNode(t)
		in.Lab = append(in.Lab, wire.LabNode{Name: "x1", MgmtIPv4: "172.20.20.9"}, wire.LabNode{Name: "a0", MgmtIPv4: "172.20.20.8"})
		r := read(t, in)
		if !r.Conforms() || !reflect.DeepEqual(r.Extra, []string{"a0", "x1"}) {
			t.Errorf("Extra = %v, not held %q", r.Extra, outcomes(r))
		}
		onceEach(t, f, 15)
	})
}

func unreadN3(t *testing.T, r Report, reason string) {
	t.Helper()
	want := []string{"host_name n3: unread", "port_enabled n3:ethernet-1/1 unread", "port_enabled n3:ethernet-1/2 unread",
		"neighbor n3:ethernet-1/1 unread", "neighbor n3:ethernet-1/2 unread"}
	if got := outcomes(r); !reflect.DeepEqual(got, want) {
		t.Errorf("not held: %q, want %q", got, want)
	}
	if !reflect.DeepEqual(r.Unread, []NodeError{{Node: "n3", Error: reason}}) || r.Nodes[2].Addr != "" {
		t.Errorf("Unread = %+v, n3 at %q, want %q without an address", r.Unread, r.Nodes[2].Addr, reason)
	}
	for _, a := range r.Assertions {
		if a.Node == "n3" && (a.Error != reason || a.Path == "") {
			t.Errorf("%s: error %q path %q, want %q and the facet's path", describe(a), a.Error, a.Path, reason)
		}
	}
	if r.AllRead() || r.Conforms() {
		t.Error("AllRead or Conforms with n3 unread")
	}
}

// A disabled port and both ends of its link are not read and stay skipped; the read still
// conforms, since a skip is not a failure.
func TestReadSkips(t *testing.T) {
	in, f := threeNode(t)
	in.Manifest = disable(t, in.Manifest, "n1", "ethernet-1/2")
	f.set(srl(threeNodeIP["n1"]), srlEnabled("ethernet-1/2"), srlEnabledIs("ethernet-1/2", "disable"))
	r := read(t, in)
	want := []string{"port_enabled n1:ethernet-1/2 skipped", "neighbor n1:ethernet-1/2 skipped", "neighbor n3:ethernet-1/2 skipped"}
	if got := outcomes(r); !reflect.DeepEqual(got, want) {
		t.Errorf("not held: %q, want %q", got, want)
	}
	onceEach(t, f, 12)
	if !r.Conforms() || !r.AllRead() || len(r.Findings()) != 0 {
		t.Errorf("Conforms %v AllRead %v findings %v", r.Conforms(), r.AllRead(), r.Findings())
	}
	if a := find(t, r, KindPortEnabled, "n1", "ethernet-1/2"); a.Path != srlEnabled("ethernet-1/2") || a.Expected != "enable" {
		t.Errorf("skipped assertion %+v, want the facet's path and value still named", a)
	}
}

// A package the read cannot hold a node to leaves that node unread, naming why, and reads
// the rest: twin verify refuses both before any read, so this is the
// read's own lock for a caller that did not.
func TestReadWithoutThePackage(t *testing.T) {
	for _, tc := range []struct {
		name   string
		pkgs   func(packageSet) packageSet
		reason string
	}{
		{"not loaded", func(s packageSet) packageSet { return packageSet{srlinux: s[srlinux]} },
			"support package arista_eos is not among the packages loaded; node e1 cannot be read"},
		{"no conformance facet", func(s packageSet) packageSet {
			p := *s[eos]
			p.Conformance = nil
			return packageSet{srlinux: s[srlinux], eos: &p}
		}, "support package arista_eos declares no conformance block; node e1 cannot be read"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			in, f := mixed(t)
			in.Packages = tc.pkgs(in.Packages.(packageSet))
			r := read(t, in)
			if len(r.Unread) != 2 || r.Unread[0] != (NodeError{Node: "e1", Error: tc.reason}) {
				t.Errorf("Unread = %+v, want e1 and e2 with %q", r.Unread, tc.reason)
			}
			for _, call := range f.calls {
				if !strings.HasPrefix(call, srl(mixedIP["s1"])) {
					t.Errorf("read %s, want s1's paths alone", call)
				}
			}
			if a := find(t, r, KindHostName, "e1", ""); a.Path != "" {
				t.Errorf("e1's path %q, want none without its facet", a.Path)
			}
		})
	}
}

// Read never changes the assertions it is given: a wait reads them again and again from
// Derive's.
func TestReadLeavesItsAssertionsAlone(t *testing.T) {
	in, f := threeNode(t)
	f.set(srl(threeNodeIP["n1"]), srlNeighbor("ethernet-1/1"), Answer{})
	as, err := Derive(in.Manifest)
	if err != nil {
		t.Fatal(err)
	}
	before := slices.Clone(as)
	_ = Read(context.Background(), in, as)
	if !reflect.DeepEqual(as, before) {
		t.Error("Read changed the assertions it was given")
	}
}

// The reader is given the caller's context and the environment, and its error is kept as
// it came: lab.gnmiGet has redacted the login before it returns.
func TestReadKeepsTheReadersError(t *testing.T) {
	in, f := threeNode(t)
	sentinel := errors.New("gNMI Get /system/name/host-name at 172.20.20.2:57400: code=Unauthenticated msg=\"(redacted)\"")
	f.errs[srl(threeNodeIP["n1"])+" "+srlHostName] = sentinel
	r := read(t, in)
	if a := find(t, r, KindHostName, "n1", ""); a.Error != sentinel.Error() {
		t.Errorf("error %q, want the reader's", a.Error)
	}
}

// Every finding a read gives, worded as contracts/cli.md's findings table words it, from the
// code under test: each a rejection at step observe on its object, and none carrying a login,
// the marker or a line of any node's configuration.
func TestFindingsWording(t *testing.T) {
	n1, n2 := srl(threeNodeIP["n1"]), srl(threeNodeIP["n2"])
	const (
		neighbour1 = "/system/lldp/interface[name=ethernet-1/1]/neighbor"
		link1      = "; link n1:ethernet-1/1|n2:ethernet-1/1 names n2 ethernet-1/1 at its far end"
	)
	threeNodeStaged := goldenID(t, "three-node")
	for _, tc := range []struct {
		name               string
		twin               func(t *testing.T) (Input, *fakeReader)
		change             func(in *Input, f *fakeReader)
		rule, object, want string
	}{
		{"a host name that is another's", threeNode,
			func(_ *Input, f *fakeReader) { f.set(n2, srlHostName, srlHostNameIs("n9")) },
			"verify.host_name", "n2",
			`node n2 (172.20.20.3:57400) reports host name "n9" at /system/name/host-name; intent names it n2`},
		{"no host name", threeNode,
			func(_ *Input, f *fakeReader) { f.set(n2, srlHostName, Answer{}) },
			"verify.host_name", "n2",
			`node n2 (172.20.20.3:57400) reports no host name at /system/name/host-name; intent names it n2`},
		{"a port not enabled", threeNode,
			func(_ *Input, f *fakeReader) {
				f.set(n1, srlEnabled("ethernet-1/2"), srlEnabledIs("ethernet-1/2", "disable"))
			},
			"verify.port.enabled", "n1:ethernet-1/2",
			`node n1 (172.20.20.2:57400): port ethernet-1/2 (node name ethernet-1/2) reads "disable" at /interface[name=ethernet-1/2]/admin-state; intent enables it (expected "enable")`},
		{"a port read as nothing", mixed,
			func(_ *Input, f *fakeReader) { f.set(eosAddr(mixedIP["e1"]), eosEnabled("Ethernet1"), Answer{}) },
			"verify.port.enabled", "e1:Ethernet1",
			`node e1 (172.20.20.3:6030): port Ethernet1 (node name Ethernet1) reads nothing at /interfaces/interface[name=Ethernet1]/state/admin-status; intent enables it (expected "UP")`},
		{"no neighbour", threeNode,
			func(_ *Input, f *fakeReader) { f.set(n1, neighbour1, Answer{}) },
			"verify.neighbor", "n1:ethernet-1/1",
			`node n1 (172.20.20.2:57400): port ethernet-1/1 sees no neighbour at ` + neighbour1 + link1},
		{"another neighbour", threeNode,
			func(_ *Input, f *fakeReader) {
				f.set(n1, neighbour1, srlNeighbours("ethernet-1/1", srlEntries([2]string{"n2", "e1-1"})))
			},
			"verify.neighbor", "n1:ethernet-1/1",
			`node n1 (172.20.20.2:57400): port ethernet-1/1 sees n2 e1-1, not n2 ethernet-1/1, at ` + neighbour1 + link1},
		{"two neighbours", threeNode,
			func(_ *Input, f *fakeReader) {
				f.set(n1, neighbour1, srlNeighbours("ethernet-1/1", srlEntries([2]string{"n2", "ethernet-1/1"}, [2]string{"n3", "ethernet-1/1"})))
			},
			"verify.neighbor", "n1:ethernet-1/1",
			`node n1 (172.20.20.2:57400): port ethernet-1/1 sees 2 neighbours (n2 ethernet-1/1, n3 ethernet-1/1), not n2 ethernet-1/1 alone, at ` + neighbour1 + link1},
		{"not a list", threeNode,
			func(_ *Input, f *fakeReader) {
				f.set(n1, neighbour1, srlNeighbours("ethernet-1/1", map[string]any{"x": 1}))
			},
			"verify.neighbor", "n1:ethernet-1/1",
			`node n1 (172.20.20.2:57400): port ethernet-1/1 reads {"x":1}, not a list, at ` + neighbour1 + link1},
		{"the record's previous bundle", threeNode,
			func(in *Input, _ *fakeReader) { prev := previousID; in.Record.Nodes[1].Holds = &prev },
			"verify.record.holds", "n2",
			`the record says node n2 holds bundle 33333333…, not the staged bundle ` + threeNodeStaged[:8] + `…; this is the record's claim (nodes[].holds), not a read`},
		{"the record's null", threeNode,
			func(in *Input, _ *fakeReader) { in.Record.Nodes[1].Holds = nil },
			"verify.record.holds", "n2",
			`the record says node n2 holds no bundle (null): containerlab restarted, recreated or created it and no push landed; the staged bundle is ` + threeNodeStaged[:8] + `…; this is the record's claim, not a read`},
		{"a node the record does not name", threeNode,
			func(in *Input, _ *fakeReader) { in.Record.Nodes = slices.Delete(in.Record.Nodes, 1, 2) },
			"verify.record.holds", "n2",
			`the record does not name node n2, which the staged bundle names; this is the record's claim, not a read`},
		{"an unread node", threeNode,
			func(_ *Input, f *fakeReader) {
				f.errs[n2+" "+srlHostName] = errors.New(`gNMI Get /system/name/host-name at 172.20.20.3:57400: code=Unavailable msg="connection refused"`)
			},
			"operation.failed", "n2",
			`node n2 (172.20.20.3:57400) could not be read: gNMI Get /system/name/host-name at 172.20.20.3:57400: code=Unavailable msg="connection refused" (at /system/name/host-name)`},
		{"a node containerlab does not report", threeNode,
			func(in *Input, _ *fakeReader) { in.Lab = in.Lab[:1] },
			"operation.failed", "n2",
			`containerlab does not report node n2, which the staged bundle names; nothing to read`},
		{"a node with no address", threeNode,
			func(in *Input, _ *fakeReader) { in.Record.Nodes[1].MgmtIPv4, in.Lab[1].MgmtIPv4 = "", "" },
			"operation.failed", "n2",
			`node n2 has no address in the record or from containerlab`},
	} {
		t.Run(tc.name, func(t *testing.T) {
			in, f := tc.twin(t)
			tc.change(&in, f)
			got := read(t, in).Findings()
			var mine []string
			for _, g := range got {
				if g.Object == tc.object {
					mine = append(mine, g.Rule)
					if g.Rule != tc.rule {
						continue
					}
					if g.Severity != "rejection" || g.Step != "observe" || g.Message != tc.want {
						t.Errorf("finding = %+v\nwant a rejection at observe:\n  %s", g, tc.want)
					}
				}
			}
			if !reflect.DeepEqual(mine, []string{tc.rule}) {
				t.Errorf("findings on %s: %q, want %s alone (all: %v)", tc.object, mine, tc.rule, got)
			}
			carriesNothingSecret(t, got.TextLines())
		})
	}
}

// carriesNothingSecret fails a test whose output carries the fake environment's password,
// the seed's marker, or any line of a golden node's configuration or bootstrap.
func carriesNothingSecret(t *testing.T, lines []string) {
	t.Helper()
	text := strings.Join(lines, "\n")
	for _, s := range []string{fakePassword, "FYLGJA-MARKER"} {
		if strings.Contains(text, s) {
			t.Errorf("output carries %q:\n%s", s, text)
		}
	}
	for _, g := range []string{"three-node", "mixed"} {
		for _, file := range configLines(t, g) {
			if strings.Contains(text, file) {
				t.Errorf("output carries the configuration line %q", file)
			}
		}
	}
}

// configLines are every line of a golden's configs files long enough to mean something.
func configLines(t *testing.T, golden string) []string {
	t.Helper()
	paths, err := filepath.Glob(repo("testdata", "golden", golden, "configs", "*"))
	if err != nil || len(paths) == 0 {
		t.Fatalf("no configs in %s: %v", golden, err)
	}
	var out []string
	for _, p := range paths {
		b, err := os.ReadFile(p)
		if err != nil {
			t.Fatal(err)
		}
		for _, l := range strings.Split(string(b), "\n") {
			if l = strings.TrimSpace(l); len(l) >= 12 {
				out = append(out, l)
			}
		}
	}
	return out
}

// The findings come assertions first, in the assertions' order, then the claims, then the
// unread nodes, each in node order.
func TestFindingsOrder(t *testing.T) {
	in, f := threeNode(t)
	n1, n3 := srl(threeNodeIP["n1"]), srl(threeNodeIP["n3"])
	f.set(n3, srlEnabled("ethernet-1/1"), Answer{})
	f.set(n1, srlHostName, srlHostNameIs("x"))
	f.errs[srl(threeNodeIP["n2"])+" "+srlHostName] = errors.New("refused")
	in.Record.Nodes[0].Holds = nil
	var got []string
	for _, g := range read(t, in).Findings() {
		got = append(got, g.Rule+" "+g.Object)
	}
	want := []string{"verify.host_name n1", "verify.port.enabled n3:ethernet-1/1", "verify.record.holds n1", "operation.failed n2"}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("findings %q, want %q", got, want)
	}
}

// The block of a read: every node with its host name and its ports, every link with both
// ends, the claims, the skips port first, the counts, and the document it sits in valid
// against the current contracts with verify.schema.json loaded.
func TestBlock(t *testing.T) {
	schema := compileFindingsSchema(t)
	inFlight := []findings.ShowRun{{WorkflowID: "fylgja-step", RunID: "01a4", Step: "observe"}}

	t.Run("held", func(t *testing.T) {
		in, _ := threeNode(t)
		in.Now = func() time.Time { return time.Date(2026, 10, 3, 18, 0, 0, 500, time.UTC) }
		r := read(t, in)
		b := r.Block(TwinOf(in.Record, in.StagedID), nil, findings.ShowServiceOK, nil)
		doc := document(t, schema, r, b, findings.StatusOK)
		wantCounts := `{"host_name":{"held":3,"failed":0,"unread":0},"port_enabled":{"held":6,"failed":0,"skipped":0,"unread":0},` +
			`"neighbor":{"held":6,"failed":0,"skipped":0,"unread":0},"record":{"held":3,"failed":0}}`
		if got := jsonOf(t, doc["verify"].(map[string]any)["counts"]); got != canon(t, wantCounts) {
			t.Errorf("counts %s\nwant   %s", got, wantCounts)
		}
		v := doc["verify"].(map[string]any)
		if v["read_at"] != "2026-10-03T18:00:00.0000005Z" || v["service"] != "ok" || jsonOf(t, v["in_flight"]) != "[]" ||
			jsonOf(t, v["skipped"]) != "[]" || jsonOf(t, v["extra_nodes"]) != "[]" || v["wait"] != nil {
			t.Errorf("block %s", jsonOf(t, v))
		}
		node := jsonOf(t, v["nodes"].([]any)[0])
		want := `{"node":"n1","psp":"nokia_srlinux","addr":"172.20.20.2:57400","read":true,` +
			`"host_name":{"path":"/system/name/host-name","expected":"n1","outcome":"held","read":"n1"},` +
			`"ports":[{"port":"ethernet-1/1","node_name":"ethernet-1/1","path":"/interface[name=ethernet-1/1]/admin-state","expected":"enable","outcome":"held","read":"enable"},` +
			`{"port":"ethernet-1/2","node_name":"ethernet-1/2","path":"/interface[name=ethernet-1/2]/admin-state","expected":"enable","outcome":"held","read":"enable"}]}`
		if node != canon(t, want) {
			t.Errorf("node n1 %s\nwant       %s", node, want)
		}
		link := jsonOf(t, v["links"].([]any)[2])
		want = `{"id":"n2:ethernet-1/2|n3:ethernet-1/1",` +
			`"a":{"node":"n2","port":"ethernet-1/2","node_name":"ethernet-1/2","path":"/system/lldp/interface[name=ethernet-1/2]/neighbor","expected":{"node":"n3","port":"ethernet-1/1"},"outcome":"held","read":[{"node":"n3","port":"ethernet-1/1"}]},` +
			`"b":{"node":"n3","port":"ethernet-1/1","node_name":"ethernet-1/1","path":"/system/lldp/interface[name=ethernet-1/1]/neighbor","expected":{"node":"n2","port":"ethernet-1/2"},"outcome":"held","read":[{"node":"n2","port":"ethernet-1/2"}]}}`
		if link != canon(t, want) {
			t.Errorf("link %s\nwant %s", link, want)
		}
		twin := jsonOf(t, v["twin"])
		want = `{"bundle_id":"` + in.StagedID + `","waypoint":null,"state":"ready","source":"intent","nodes":3}`
		if twin != canon(t, want) {
			t.Errorf("twin %s\nwant %s", twin, want)
		}
	})
	t.Run("failed and unread", func(t *testing.T) {
		in, f := threeNode(t)
		n1, n2 := srl(threeNodeIP["n1"]), srl(threeNodeIP["n2"])
		f.set(n1, srlEnabled("ethernet-1/2"), srlEnabledIs("ethernet-1/2", "disable"))
		f.set(n1, srlNeighbor("ethernet-1/2"), Answer{})
		f.errs[n2+" "+srlHostName] = errors.New("refused")
		r := read(t, in)
		v := document(t, schema, r, r.Block(TwinOf(in.Record, in.StagedID), inFlight, findings.ShowServiceOK, nil), findings.StatusError)["verify"].(map[string]any)
		wantCounts := `{"host_name":{"held":2,"failed":0,"unread":1},"port_enabled":{"held":5,"failed":1,"skipped":0,"unread":0},` +
			`"neighbor":{"held":5,"failed":1,"skipped":0,"unread":0},"record":{"held":3,"failed":0}}`
		if got := jsonOf(t, v["counts"]); got != canon(t, wantCounts) {
			t.Errorf("counts %s\nwant   %s", got, wantCounts)
		}
		n2Node := v["nodes"].([]any)[1].(map[string]any)
		if n2Node["read"] != false || n2Node["error"] != "refused" ||
			jsonOf(t, n2Node["host_name"]) != canon(t, `{"path":"/system/name/host-name","expected":"n2","outcome":"unread","read":null,"error":"refused"}`) {
			t.Errorf("n2 %s", jsonOf(t, n2Node))
		}
		end := v["links"].([]any)[1].(map[string]any)["a"].(map[string]any)
		if end["outcome"] != "absent" || end["read"] == nil || jsonOf(t, end["read"]) != "[]" {
			t.Errorf("n1's absent end %s", jsonOf(t, end))
		}
		if jsonOf(t, v["in_flight"]) != canon(t, `[{"workflow_id":"fylgja-step","run_id":"01a4","step":"observe"}]`) {
			t.Errorf("in_flight %s", jsonOf(t, v["in_flight"]))
		}
	})
	t.Run("skips", func(t *testing.T) {
		in, _ := threeNode(t)
		in.Manifest = disable(t, in.Manifest, "n1", "ethernet-1/2")
		r := read(t, in)
		v := document(t, schema, r, r.Block(TwinOf(in.Record, in.StagedID), nil, findings.ShowServiceUnreachable, nil), findings.StatusOK)["verify"].(map[string]any)
		want := `[{"node":"n1","port":"ethernet-1/2","reason":"intent disables n1:ethernet-1/2","link":null},` +
			`{"node":"n1","port":"ethernet-1/2","reason":"link n1:ethernet-1/2|n3:ethernet-1/2 is not asserted: intent disables n1:ethernet-1/2","link":"n1:ethernet-1/2|n3:ethernet-1/2"},` +
			`{"node":"n3","port":"ethernet-1/2","reason":"link n1:ethernet-1/2|n3:ethernet-1/2 is not asserted: intent disables n1:ethernet-1/2","link":"n1:ethernet-1/2|n3:ethernet-1/2"}]`
		if got := jsonOf(t, v["skipped"]); got != canon(t, want) {
			t.Errorf("skipped %s\nwant    %s", got, want)
		}
		wantCounts := `{"host_name":{"held":3,"failed":0,"unread":0},"port_enabled":{"held":5,"failed":0,"skipped":1,"unread":0},` +
			`"neighbor":{"held":4,"failed":0,"skipped":2,"unread":0},"record":{"held":3,"failed":0}}`
		if got := jsonOf(t, v["counts"]); got != canon(t, wantCounts) {
			t.Errorf("counts %s\nwant   %s", got, wantCounts)
		}
		if v["service"] != "unreachable" {
			t.Errorf("service %v", v["service"])
		}
		port := jsonOf(t, v["nodes"].([]any)[0].(map[string]any)["ports"].([]any)[1])
		if port != canon(t, `{"port":"ethernet-1/2","node_name":"ethernet-1/2","path":"/interface[name=ethernet-1/2]/admin-state","expected":"enable","outcome":"skipped","read":null,"reason":"intent disables n1:ethernet-1/2"}`) {
			t.Errorf("skipped port %s", port)
		}
	})
	t.Run("diverged, with a wait", func(t *testing.T) {
		in, _ := mixed(t)
		phase, target := "push", in.StagedID
		prev := previousID
		in.Record.State = wire.StateDiverged
		in.Record.BundleID = previousID
		in.Record.Waypoint = &wire.WaypointRef{Series: "demo", Sequence: 1, Description: "first", AtSource: "given"}
		in.Record.Step = &wire.StepRecord{Outcome: wire.StepDiverged, Phase: &phase,
			To:  wire.StepSide{Waypoint: &wire.WaypointRef{Series: "demo", Sequence: 2, Description: "second", AtSource: "written"}, BundleID: target},
			Run: wire.RunRef{WorkflowID: wire.StepWorkflowID, RunID: "01a3"}}
		in.Record.Nodes[0].Holds = &prev // e1 refused its push and holds demo/1
		r := read(t, in)
		wait := &findings.VerifyWait{BudgetS: 20, Reads: 3, Outcome: "settled", AfterS: 2.1}
		doc := document(t, schema, r, r.Block(TwinOf(in.Record, in.StagedID), nil, findings.ShowServiceOK, wait), findings.StatusNonconforming)
		v := doc["verify"].(map[string]any)
		want := `{"bundle_id":"` + target + `","waypoint":{"series":"demo","sequence":1,"description":"first","at_source":"given"},` +
			`"state":"diverged","source":"intent","nodes":3,"diverged":{"towards":{"waypoint":{"series":"demo","sequence":2,"description":"second","at_source":"written"},` +
			`"bundle_id":"` + target + `"},"run":{"workflow_id":"fylgja-step","run_id":"01a3"},"phase":"push"}}`
		if got := jsonOf(t, v["twin"]); got != canon(t, want) {
			t.Errorf("twin %s\nwant %s", got, want)
		}
		want = `[{"node":"e1","holds":"` + previousID + `","staged":"` + target + `","outcome":"failed"},` +
			`{"node":"e2","holds":"` + target + `","staged":"` + target + `","outcome":"held"},` +
			`{"node":"s1","holds":"` + target + `","staged":"` + target + `","outcome":"held"}]`
		if got := jsonOf(t, v["record"]); got != canon(t, want) {
			t.Errorf("record %s\nwant   %s", got, want)
		}
		if got := jsonOf(t, v["wait"]); got != canon(t, `{"budget_s":20,"reads":3,"outcome":"settled","after_s":2.1}`) {
			t.Errorf("wait %s", got)
		}
		if got := jsonOf(t, v["counts"].(map[string]any)["record"]); got != canon(t, `{"held":2,"failed":1}`) {
			t.Errorf("record counts %s", got)
		}
		if doc["findings"].([]any)[0].(map[string]any)["rule"] != "verify.record.holds" {
			t.Errorf("findings %s", jsonOf(t, doc["findings"]))
		}
	})
}

// document builds twin verify's document around a block, validates it against this
// feature's findings schema and returns it decoded.
func document(t *testing.T, schema *jsonschema.Schema, r Report, b *findings.VerifyBlock, status findings.Status) map[string]any {
	t.Helper()
	doc := findings.NewDocument(findings.OpTwinVerify, nil, r.Findings())
	doc.Status, doc.BundleID, doc.Verify = status, b.Twin.BundleID, b
	raw, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	carriesNothingSecret(t, []string{string(raw)})
	v, err := jsonschema.UnmarshalJSON(bytes.NewReader(raw))
	if err != nil {
		t.Fatal(err)
	}
	if err := schema.Validate(v); err != nil {
		t.Fatalf("the document does not satisfy contracts/findings.schema.json: %v\n%s", err, raw)
	}
	var out map[string]any
	if err := json.Unmarshal(raw, &out); err != nil {
		t.Fatal(err)
	}
	return out
}

// compileFindingsSchema compiles the contract's findings schema with the schemas it refers
// to loaded under their $ids, as every reader of a findings document must.
func compileFindingsSchema(t *testing.T) *jsonschema.Schema {
	t.Helper()
	load := func(name string) any {
		f, err := os.Open(repo("contracts", name))
		if err != nil {
			t.Fatal(err)
		}
		defer func() { _ = f.Close() }()
		doc, err := jsonschema.UnmarshalJSON(f)
		if err != nil {
			t.Fatalf("parsing %s: %v", name, err)
		}
		return doc
	}
	c := jsonschema.NewCompiler()
	for _, name := range []string{"show.schema.json", "waypoints.schema.json", "step.schema.json", "verify.schema.json"} {
		if err := c.AddResource("https://fylgja.dev/schemas/"+name, load(name)); err != nil {
			t.Fatal(err)
		}
	}
	if err := c.AddResource("findings.schema.json", load("findings.schema.json")); err != nil {
		t.Fatal(err)
	}
	s, err := c.Compile("findings.schema.json")
	if err != nil {
		t.Fatal(err)
	}
	return s
}

func jsonOf(t *testing.T, v any) string {
	t.Helper()
	b, err := json.Marshal(v)
	if err != nil {
		t.Fatal(err)
	}
	return string(b)
}

// canon is a JSON text with its object keys sorted, as jsonOf writes a decoded document.
func canon(t *testing.T, s string) string {
	t.Helper()
	var v any
	if err := json.Unmarshal([]byte(s), &v); err != nil {
		t.Fatalf("%v: %s", err, s)
	}
	return jsonOf(t, v)
}
