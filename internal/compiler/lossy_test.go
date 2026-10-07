package compiler

import (
	"encoding/json"
	"fmt"
	"reflect"
	"sort"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/findings"
)

// The lossy design case asserted by name. The golden holds
// the bundle's bytes; this says what each byte means, so a regenerated golden that moved
// a decision fails here even when it matches itself.

type lossyBundle struct {
	files map[string][]byte
	m     Manifest
}

func compileLossy(t *testing.T) lossyBundle {
	t.Helper()
	files := compileLossyFixture(t, "testdata/ctm/lossy.json")
	var m Manifest
	if err := json.Unmarshal(files[ManifestFile], &m); err != nil {
		t.Fatal(err)
	}
	return lossyBundle{files: files, m: m}
}

func (b lossyBundle) row(t *testing.T, object string) MappingRow {
	t.Helper()
	for _, r := range b.m.Mapping {
		if r.Device+":"+r.Interface == object {
			return r
		}
	}
	t.Fatalf("no mapping row for %s", object)
	return MappingRow{}
}

func (b lossyBundle) omission(object string) (Omission, bool) {
	for _, o := range b.m.Omissions {
		if o.Object == object {
			return o, true
		}
	}
	return Omission{}, false
}

func (b lossyBundle) entry(object string) (LossyMapping, bool) {
	for _, e := range b.m.Fidelity.Lossy {
		if e.Device+":"+e.Interface == object {
			return e, true
		}
	}
	return LossyMapping{}, false
}

// describe renders a row as the tests compare it: port, node name and disposition. Both
// port and node name are null on a row the twin gives no port, and from bundle "3" a row
// with a port always carries a node name, equal to the production name where the
// platform keeps it.
func describe(r MappingRow) string {
	port, name := "null", "null"
	if r.Port != nil {
		port = *r.Port
	}
	if r.NodeName != nil {
		name = fmt.Sprintf("%q", *r.NodeName)
	}
	return fmt.Sprintf("port %s node_name %s %s", port, name, r.Disposition)
}

func (b lossyBundle) wantRow(t *testing.T, object, want string) {
	t.Helper()
	if got := describe(b.row(t, object)); got != want {
		t.Errorf("%s: %s, want %s", object, got, want)
	}
}

func (b lossyBundle) wantEntry(t *testing.T, object string, want LossyMapping) {
	t.Helper()
	got, ok := b.entry(object)
	if !ok {
		t.Errorf("%s has no fidelity.lossy entry; want %+v", object, want)
		return
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("%s's fidelity.lossy entry:\n got %+v\nwant %+v", object, got, want)
	}
}

func (b lossyBundle) wantNoEntry(t *testing.T, object string) {
	t.Helper()
	if e, ok := b.entry(object); ok {
		t.Errorf("%s has a fidelity.lossy entry %+v; nothing about it is lossy or shared", object, e)
	}
}

func (b lossyBundle) wantOmission(t *testing.T, object, rule, reason string) {
	t.Helper()
	o, ok := b.omission(object)
	if !ok {
		t.Errorf("%s has no omission; want %s", object, rule)
		return
	}
	if o.Rule != rule || o.Reason != reason {
		t.Errorf("%s omitted as %s: %q\nwant %s: %q", object, o.Rule, o.Reason, rule, reason)
	}
}

func TestLossyBundleIsTheGolden(t *testing.T) {
	if id := bundle.ID(compileLossy(t).files); id != goldenLossyID {
		t.Errorf("bundle_id = %s, want %s", id, goldenLossyID)
	}
}

// One-to-one with a node name that differs from production: the row records it.
func TestLossyOneToOneRenamed(t *testing.T) {
	b := compileLossy(t)
	b.wantRow(t, "c1:Ethernet1/1", `port eth1 node_name "Ethernet1" cabled`)
	// A rule that renames without dropping is not lossy: with nothing sharing its port,
	// the interface is a row with a node name and nothing more.
	b.wantRow(t, "c2:Ethernet1/2", `port eth2 node_name "Ethernet2" configured-not-cabled`)
	b.wantNoEntry(t, "c2:Ethernet1/2")
}

// Many-to-one across two rules, with a cabled holder: Ethernet1/1 (front) holds eth1,
// Ethernet2/1 (linecard, which drops the slot) renders to it and is omitted.
func TestLossySharedPortWithACabledHolder(t *testing.T) {
	b := compileLossy(t)
	b.wantRow(t, "c1:Ethernet2/1", `port null node_name null omitted`)
	b.wantOmission(t, "c1:Ethernet2/1", findings.RuleOmitInterfaceShared,
		"port eth1 is held by cabled Ethernet1/1 (rule front); this interface maps to it under rule linecard and is not represented")
	b.wantEntry(t, "c1:Ethernet1/1", LossyMapping{Device: "c1", Interface: "Ethernet1/1", Port: "eth1", NodeName: "Ethernet1",
		Rule: "front", Lossy: false, Shares: []Share{{Interface: "Ethernet2/1", Rule: "linecard", Cabled: false}}})
	// The omitted member keeps its rendered port in the record.
	b.wantEntry(t, "c1:Ethernet2/1", LossyMapping{Device: "c1", Interface: "Ethernet2/1", Port: "eth1", NodeName: "Ethernet1",
		Rule: "linecard", Lossy: true, Shares: []Share{{Interface: "Ethernet1/1", Rule: "front", Cabled: true}}})
}

// A collapsing breakout with a cabled child: the lanes share the parent's port.
func TestLossyCollapsingBreakoutWithACabledChild(t *testing.T) {
	b := compileLossy(t)
	b.wantRow(t, "c1:Ethernet1/49/1", `port eth49 node_name "Ethernet49" cabled`)
	b.wantRow(t, "c1:Ethernet1/49/2", `port null node_name null omitted`)
	b.wantOmission(t, "c1:Ethernet1/49/2", findings.RuleOmitInterfaceShared,
		"port eth49 is held by cabled Ethernet1/49/1 (rule breakout); this interface maps to it under rule breakout and is not represented")
	b.wantEntry(t, "c1:Ethernet1/49/1", LossyMapping{Device: "c1", Interface: "Ethernet1/49/1", Port: "eth49", NodeName: "Ethernet49",
		Rule: "breakout", Lossy: true, Shares: []Share{{Interface: "Ethernet1/49/2", Rule: "breakout", Cabled: false}}})
	b.wantEntry(t, "c1:Ethernet1/49/2", LossyMapping{Device: "c1", Interface: "Ethernet1/49/2", Port: "eth49", NodeName: "Ethernet49",
		Rule: "breakout", Lossy: true, Shares: []Share{{Interface: "Ethernet1/49/1", Rule: "breakout", Cabled: true}}})
}

// A parent and its children, none cabled, under the collapsing rule: every one keeps
// the port, and the sharing is recorded with no cabled member.
func TestLossySharedPortWithNoCabledMember(t *testing.T) {
	b := compileLossy(t)
	members := map[string]string{"Ethernet1/50": "front", "Ethernet1/50/1": "breakout", "Ethernet1/50/2": "breakout"}
	for name, rule := range members {
		object := "c2:" + name
		b.wantRow(t, object, `port eth50 node_name "Ethernet50" configured-not-cabled`)
		if o, ok := b.omission(object); ok {
			t.Errorf("%s is omitted (%+v); with none cabled every member keeps the port", object, o)
		}
		var shares []Share
		for other, r := range members {
			if other != name {
				shares = append(shares, Share{Interface: other, Rule: r})
			}
		}
		sort.Slice(shares, func(i, j int) bool { return shares[i].Interface < shares[j].Interface })
		b.wantEntry(t, object, LossyMapping{Device: "c2", Interface: name, Port: "eth50", NodeName: "Ethernet50",
			Rule: rule, Lossy: rule == "breakout", Shares: shares})
	}
}

// Many-to-one, cabled, sharing nothing in this intent: the rule is still lossy, so the
// interface is recorded, with empty shares.
func TestLossyRuleRecordedThoughNothingIsShared(t *testing.T) {
	b := compileLossy(t)
	b.wantRow(t, "c2:Ethernet2/1", `port eth1 node_name "Ethernet1" cabled`)
	b.wantEntry(t, "c2:Ethernet2/1", LossyMapping{Device: "c2", Interface: "Ethernet2/1", Port: "eth1", NodeName: "Ethernet1",
		Rule: "linecard", Lossy: true, Shares: []Share{}})
	b.wantEntry(t, "c2:Ethernet1/49/1", LossyMapping{Device: "c2", Interface: "Ethernet1/49/1", Port: "eth49", NodeName: "Ethernet49",
		Rule: "breakout", Lossy: true, Shares: []Share{}})
}

// A name a rule matched out of range, uncabled, is omitted and says which rule and
// which value.
func TestLossyOutOfRangeIsOmittedAndNamed(t *testing.T) {
	b := compileLossy(t)
	b.wantRow(t, "c1:Ethernet1/53", `port null node_name null omitted`)
	b.wantOmission(t, "c1:Ethernet1/53", findings.RuleOmitInterfaceUnmappable,
		"rule front matched, but {port} is 53, outside its range 1..52; no such port on the node")
	b.wantNoEntry(t, "c1:Ethernet1/53")
}

// The management rule applies to the mgmt_only interface whatever it is called, and
// the row carries the node's name for the port.
func TestLossyManagementByAnotherName(t *testing.T) {
	b := compileLossy(t)
	for _, d := range []string{"c1", "c2"} {
		b.wantRow(t, d+":Management1", `port eth0 node_name "Management0" management`)
		b.wantNoEntry(t, d+":Management1")
	}
	for _, n := range b.m.Nodes {
		want := map[string]string{"c1": "eth0", "c2": "eth0", "s1": "mgmt0"}[n.Name]
		if n.ManagementPort != want {
			t.Errorf("node %s management_port %s, want %s", n.Name, n.ManagementPort, want)
		}
	}
}

// SR Linux beside the lossy platform: its node names are its production names, so its
// rows carry none, and a spreading breakout child keeps its lane (e1-2-1).
func TestLossySRLinuxBesideIt(t *testing.T) {
	b := compileLossy(t)
	b.wantRow(t, "s1:ethernet-1/1", `port e1-1 node_name "ethernet-1/1" cabled`)
	b.wantRow(t, "s1:ethernet-1/2/1", `port e1-2-1 node_name "ethernet-1/2/1" cabled`)
	b.wantRow(t, "s1:mgmt0", `port mgmt0 node_name "mgmt0" management`)
	for _, e := range b.m.Fidelity.Lossy {
		if e.Device == "s1" {
			t.Errorf("SR Linux interface %s is in fidelity.lossy; its profile loses nothing", e.Interface)
		}
	}
}

// The record as a whole: one entry per lossy-mapped or shared interface, four on c1 and
// five on c2, sorted, each naming its rule and listing its sharers.
func TestLossyRecordIsComplete(t *testing.T) {
	b := compileLossy(t)
	var got []string
	for _, e := range b.m.Fidelity.Lossy {
		got = append(got, e.Device+":"+e.Interface)
		if e.Rule == "" || e.Shares == nil {
			t.Errorf("entry %+v lacks a rule or a shares list", e)
		}
	}
	want := []string{
		"c1:Ethernet1/1", "c1:Ethernet1/49/1", "c1:Ethernet1/49/2", "c1:Ethernet2/1",
		"c2:Ethernet1/49/1", "c2:Ethernet1/50", "c2:Ethernet1/50/1", "c2:Ethernet1/50/2", "c2:Ethernet2/1",
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("fidelity.lossy lists\n%s\nwant\n%s", strings.Join(got, "\n"), strings.Join(want, "\n"))
	}

	// fidelity.omitted mirrors omissions[], the shared omissions included.
	var objects []string
	for _, o := range b.m.Omissions {
		objects = append(objects, o.Object)
	}
	sort.Strings(objects)
	if !reflect.DeepEqual(objects, b.m.Fidelity.Omitted) {
		t.Errorf("fidelity.omitted %v, omissions name %v", b.m.Fidelity.Omitted, objects)
	}
}

// One row per production interface, and every link cabled on the interfaces that hold
// their ports: after sharing, a cabled interface is never the one omitted.
func TestLossyLinksLandOnHolders(t *testing.T) {
	b := compileLossy(t)
	c := loadFixture(t, "testdata/ctm/lossy.json")
	var interfaces int
	for _, d := range c.Devices {
		interfaces += len(d.Interfaces)
	}
	if len(b.m.Mapping) != interfaces {
		t.Errorf("%d rows for %d interfaces in intent", len(b.m.Mapping), interfaces)
	}
	if len(b.m.Links) != len(c.Links) {
		t.Errorf("cabled %d links, intent has %d", len(b.m.Links), len(c.Links))
	}
	for _, l := range c.Links {
		for _, ep := range l.Endpoints {
			r := b.row(t, ep.ID())
			if r.Disposition != DispCabled || r.Port == nil {
				t.Errorf("link %s lands on %s, which is %s", l.ID, ep.ID(), describe(r))
			}
		}
	}
}

// Bootstrap names each cabled port as the node does: Ethernet1 and Ethernet49
// on c1, never the production name or the endpoint name; SR Linux's own names on s1.
func TestLossyBootstrapNamesTheNodesPorts(t *testing.T) {
	b := compileLossy(t)
	chassis := []string{"interface Ethernet1/", "interface Ethernet2/", "interface eth"}
	for node, c := range map[string]struct{ want, wrong []string }{
		"c1": {[]string{"interface Ethernet1\n", "interface Ethernet49\n"}, chassis},
		"c2": {[]string{"interface Ethernet1\n", "interface Ethernet49\n"}, chassis},
		"s1": {[]string{"set / interface ethernet-1/1 admin-state enable\n", "set / interface ethernet-1/2/1 admin-state enable\n"},
			[]string{"interface e1-"}},
	} {
		got := string(b.files["configs/"+node+".cli"])
		for _, line := range c.want {
			if !strings.Contains(got, line) {
				t.Errorf("%s's bootstrap lacks %q:\n%s", node, line, got)
			}
		}
		for _, wrong := range c.wrong {
			if strings.Contains(got, wrong) {
				t.Errorf("%s's bootstrap names a port by a name the node does not use (%q):\n%s", node, wrong, got)
			}
		}
	}
}
