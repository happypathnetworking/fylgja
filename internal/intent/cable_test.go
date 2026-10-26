package intent_test

import (
	"reflect"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
)

// addPorts gives a fixture device more physical ports, uncabled.
func (f *fakeInfrahub) addPorts(device string, names ...string) {
	d := f.device(device)
	for _, n := range names {
		d.Ports = append(d.Ports, &fakePort{ID: device + ":" + n, Name: n})
	}
}

// The fixed rows every read of this reader writes (mapping.md §5).
var fixedRows = []ctm.FidelityRow{
	{Disposition: "approximated", Object: "interface.enabled", Source: "InterfacePhysical.status",
		Reason: "a port is enabled unless its status is disabled; the library's status is not an admin state"},
	{Disposition: "approximated", Object: "interface.mgmt_only", Source: "InterfacePhysical.role",
		Reason: "the management port is the port whose role is management; the library has no management-only flag"},
}

// platformRow is the third fixed row, after every omitted cable whose object sorts first.
var platformRow = ctm.FidelityRow{Disposition: "omitted", Object: "platform.version", Source: "DcimPlatform",
	Reason: "the library's platform carries no version"}

// A cable the mapping cannot place is omitted and never refuses the read (US2 scenarios 2
// and 3; FR-006): three ends, one end, an end on a device outside the scope, and an end
// that is not a physical port, a console port or a virtual interface carrying a cable (the
// spec's edge case: the interface is not read, and its cable is omitted naming its kind).
// Each is an info finding naming the cable, its reason and
// every end it can name, and a fidelity row with the same reason; its ports stay in the
// CTM, cabled to nothing. A cable with no label is named by its id. The three fixture
// cables, each reached from both its ends, are three links.
func TestCablesTheReadCannotPlace(t *testing.T) {
	f := newFakeInfrahub(t)
	f.addPorts("n1", "ethernet-1/3", "ethernet-1/4", "ethernet-1/5")
	f.addPorts("n2", "ethernet-1/3", "ethernet-1/4")
	f.addPorts("n3", "ethernet-1/3", "ethernet-1/4")
	f.addDevice("cs1", "Opengear", "Console OS", nil, "port1")
	f.cable("cable-three", "c-three", "n1:ethernet-1/3", "n2:ethernet-1/3", "n3:ethernet-1/3")
	f.cable("cable-one", "c-one", "n1:ethernet-1/4")
	f.cable("cable-out", "c-out", "n1:ethernet-1/5", "cs1:port1")
	f.cable("cable-console", "", "n2:ethernet-1/4", "DcimConsolePort#cp-7")
	f.cable("cable-virtual", "c-virtual", "n3:ethernet-1/4", "InterfaceVirtual#vi-lo0")

	c, list, err := readFake(t, f)

	if err != nil {
		t.Fatal(err)
	}
	if list.Rejected() || c == nil {
		t.Fatalf("findings %v; a cable refused the read", list)
	}
	want := findings.List{
		{Severity: findings.Info, Rule: findings.RuleOmitCableEnds, Object: "c-one",
			Message: "cable c-one is omitted: other than two ends (1); its ends are n1:ethernet-1/4"},
		{Severity: findings.Info, Rule: findings.RuleOmitCableOutsideScope, Object: "c-out",
			Message: "cable c-out is omitted: an end outside the scope (id-cs1:port1); its ends are id-cs1:port1, n1:ethernet-1/5"},
		{Severity: findings.Info, Rule: findings.RuleOmitCableEnds, Object: "c-three",
			Message: "cable c-three is omitted: other than two ends (3); its ends are n1:ethernet-1/3, n2:ethernet-1/3, n3:ethernet-1/3"},
		{Severity: findings.Info, Rule: findings.RuleOmitCableEndpoint, Object: "c-virtual",
			Message: "cable c-virtual is omitted: an end not on a physical port (InterfaceVirtual); its ends are n3:ethernet-1/4"},
		{Severity: findings.Info, Rule: findings.RuleOmitCableEndpoint, Object: "cable-console",
			Message: "cable cable-console is omitted: an end not on a physical port (DcimConsolePort); its ends are n2:ethernet-1/4"},
	}
	if !reflect.DeepEqual(list, want) {
		t.Errorf("findings\n%v\nwant\n%v", list, want)
	}
	rows := append(append([]ctm.FidelityRow{}, fixedRows...),
		ctm.FidelityRow{Disposition: "omitted", Object: "c-one", Source: "DcimCable", Reason: "other than two ends (1)"},
		ctm.FidelityRow{Disposition: "omitted", Object: "c-out", Source: "DcimCable", Reason: "an end outside the scope (id-cs1:port1)"},
		ctm.FidelityRow{Disposition: "omitted", Object: "c-three", Source: "DcimCable", Reason: "other than two ends (3)"},
		ctm.FidelityRow{Disposition: "omitted", Object: "c-virtual", Source: "DcimCable", Reason: "an end not on a physical port (InterfaceVirtual)"},
		ctm.FidelityRow{Disposition: "omitted", Object: "cable-console", Source: "DcimCable", Reason: "an end not on a physical port (DcimConsolePort)"},
		platformRow,
	)
	if !reflect.DeepEqual(c.Envelope.Fidelity, rows) {
		t.Errorf("fidelity\n%+v\nwant\n%+v", c.Envelope.Fidelity, rows)
	}
	if len(c.Links) != 3 {
		t.Errorf("links %+v; want the fixture's three alone", c.Links)
	}
	for _, port := range []struct{ device, name string }{{"n1", "ethernet-1/3"}, {"n1", "ethernet-1/5"}, {"n2", "ethernet-1/4"}, {"n3", "ethernet-1/3"}, {"n3", "ethernet-1/4"}} {
		if in := c.Device(port.device).Interface(port.name); in == nil || in.Link != "" {
			t.Errorf("%s:%s is %+v; want it read, linked to nothing", port.device, port.name, in)
		}
	}
	if c.Device("cs1") != nil {
		t.Error("the device outside the scope was read")
	}
	if n := intent.Summarize(c).CablesOmitted; n != 5 {
		t.Errorf("CablesOmitted %d, want 5", n)
	}
	for _, d := range c.Devices {
		if d.Interface("lo0") != nil {
			t.Errorf("%s reads the virtual interface lo0", d.Name)
		}
	}
}

// A connector that is not a DcimCable, a kind of the operator's own inheriting
// DcimConnector, which conformance allows (FR-012), is never a link, even between two
// physical ports in the scope: it is omitted under its own reason, an info finding naming
// it by its id, since the read selects a label on a DcimCable alone, with its kind and its
// ends, and a fidelity row whose source is its kind (FR-006; T096). Its ports stay in the
// CTM, cabled to nothing, and the read's success line counts it among the cables omitted.
func TestAConnectorThatIsNotACableIsOmitted(t *testing.T) {
	f := newFakeInfrahub(t)
	f.addPorts("n1", "ethernet-1/3")
	f.addPorts("n2", "ethernet-1/3")
	f.cable("jumper-1", "j-1", "n1:ethernet-1/3", "n2:ethernet-1/3").Kind = "AcmeJumper"

	c, list, err := readFake(t, f)

	if err != nil {
		t.Fatal(err)
	}
	if list.Rejected() || c == nil {
		t.Fatalf("findings %v; the connector refused the read", list)
	}
	want := findings.List{{Severity: findings.Info, Rule: findings.RuleOmitCableKind, Object: "jumper-1",
		Message: "connector jumper-1 is omitted: a connector that is not a DcimCable (AcmeJumper); its ends are n1:ethernet-1/3, n2:ethernet-1/3"}}
	if !reflect.DeepEqual(list, want) {
		t.Errorf("findings\n%v\nwant\n%v", list, want)
	}
	rows := append(append([]ctm.FidelityRow{}, fixedRows...),
		ctm.FidelityRow{Disposition: "omitted", Object: "jumper-1", Source: "AcmeJumper", Reason: "a connector that is not a DcimCable (AcmeJumper)"},
		platformRow,
	)
	if !reflect.DeepEqual(c.Envelope.Fidelity, rows) {
		t.Errorf("fidelity\n%+v\nwant\n%+v", c.Envelope.Fidelity, rows)
	}
	if len(c.Links) != 3 {
		t.Errorf("links %+v; want the fixture's three alone", c.Links)
	}
	for _, d := range []string{"n1", "n2"} {
		if in := c.Device(d).Interface("ethernet-1/3"); in == nil || in.Link != "" {
			t.Errorf("%s:ethernet-1/3 is %+v; want it read, linked to nothing", d, in)
		}
	}
	if n := intent.Summarize(c).CablesOmitted; n != 1 {
		t.Errorf("CablesOmitted %d, want 1", n)
	}
}

// The first reason that applies is the one given, in R-05's order: the connector's kind
// (T096), then its ends, then the kind of an end, then the scope. A cable reached from
// several ports in the scope is judged once. A cable none of whose ends is in the scope is
// reached from no port read, and is not read.
func TestACableIsJudgedOnceByTheFirstReason(t *testing.T) {
	cases := []struct {
		name string
		// kind is the connector's, "" a DcimCable.
		kind string
		ends []string
		rule string
	}{
		{"three ends, one outside", "", []string{"n1:ethernet-1/3", "n2:ethernet-1/3", "cs1:port1"}, findings.RuleOmitCableEnds},
		{"three ends, one a console port", "", []string{"n1:ethernet-1/3", "n2:ethernet-1/3", "DcimConsolePort#cp-7"}, findings.RuleOmitCableEnds},
		{"an end a console port, reached from the other", "", []string{"n1:ethernet-1/3", "DcimConsolePort#cp-7"}, findings.RuleOmitCableEndpoint},
		{"an end outside, reached from the other", "", []string{"n1:ethernet-1/3", "cs1:port1"}, findings.RuleOmitCableOutsideScope},
		{"no end", "", nil, findings.RuleOmitCableEnds},
		{"another kind, three ends, one a console port, one outside", "AcmeJumper",
			[]string{"n1:ethernet-1/3", "DcimConsolePort#cp-7", "cs1:port1"}, findings.RuleOmitCableKind},
		{"another kind, two physical ends in the scope", "AcmeJumper", []string{"n1:ethernet-1/3", "n2:ethernet-1/3"}, findings.RuleOmitCableKind},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			f := newFakeInfrahub(t)
			f.addPorts("n1", "ethernet-1/3")
			f.addPorts("n2", "ethernet-1/3")
			f.addDevice("cs1", "Opengear", "Console OS", nil, "port1")
			f.cable("cable-x", "c-x", tc.ends...).Kind = tc.kind
			if tc.ends == nil {
				// A cable with no end is reached from no port; it is the port's connector
				// all the same when Infrahub still names it there.
				_, p := f.port("n1:ethernet-1/3")
				p.Cable = "cable-x"
			}

			c, list, err := readFake(t, f)

			if err != nil {
				t.Fatal(err)
			}
			// A connector of another kind has no label the read selects: its id names it.
			object := "c-x"
			if tc.kind != "" {
				object = "cable-x"
			}
			if c == nil || len(list) != 1 || list[0].Rule != tc.rule || list[0].Object != object {
				t.Errorf("findings %v; want one, %s of %s", list, tc.rule, object)
			}
		})
	}
}

// A cable between two management ports of devices in the scope is a link like any other:
// it reaches the CTM, and the compiler omits it as it does today (US2 scenario 4; FR-007).
func TestManagementCableReachesTheCTM(t *testing.T) {
	f := newFakeInfrahub(t)
	f.cable("cable-mgmt", "n1:mgmt0|n2:mgmt0", "n1:mgmt0", "n2:mgmt0")

	c, list, err := readFake(t, f)

	if err != nil {
		t.Fatal(err)
	}
	if list.Rejected() || c == nil {
		t.Fatalf("findings %v; want a clean read", list)
	}
	const id = "n1:mgmt0|n2:mgmt0"
	var link *ctm.Link
	for i := range c.Links {
		if c.Links[i].ID == id {
			link = &c.Links[i]
		}
	}
	if link == nil || len(c.Links) != 4 {
		t.Fatalf("links %+v; want the fixture's three and %s", c.Links, id)
	}
	for _, d := range []string{"n1", "n2"} {
		if mgmt := c.Device(d).Interface("mgmt0"); !mgmt.MgmtOnly || mgmt.Link != id {
			t.Errorf("%s:mgmt0 %+v; want the management port, linked to %s", d, mgmt, id)
		}
	}
	if n := intent.Summarize(c).CablesOmitted; n != 0 {
		t.Errorf("CablesOmitted %d, want none", n)
	}
}

// A cable that counts two ends and lists fewer, an end Infrahub would not give, is not two
// ends either: omitted, never a link with a missing end.
func TestACableListingFewerEndsThanItCountsIsOmitted(t *testing.T) {
	f := newFakeInfrahub(t)
	f.addPorts("n1", "ethernet-1/3")
	f.cable("cable-short", "c-short", "n1:ethernet-1/3")
	f.short = map[string]int{"cable-short": 2}

	c, list, err := readFake(t, f)

	if err != nil {
		t.Fatal(err)
	}
	want := findings.Finding{Severity: findings.Info, Rule: findings.RuleOmitCableEnds, Object: "c-short",
		Message: "cable c-short is omitted: other than two ends (1 listed of 2); its ends are n1:ethernet-1/3"}
	if c == nil || len(list) != 1 || list[0] != want || len(c.Links) != 3 {
		t.Errorf("findings %v, CTM %v; want exactly %+v and the fixture's three links", list, c != nil, want)
	}
}
