package compiler

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

func srlinux(t *testing.T) *psp.PSP {
	t.Helper()
	r, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	p, ok := r.Lookup("srlinux")
	if !ok {
		t.Fatal("srlinux support package not registered")
	}
	return p
}

// srlinuxProfile is the shipped package's profile, as the compiler builds it.
func srlinuxProfile(t *testing.T) (*psp.Profile, string) {
	t.Helper()
	p := srlinux(t)
	prof, err := psp.NewProfile(p)
	if err != nil {
		t.Fatal(err)
	}
	return prof, p.Platform.ID
}

// The shipped profile maps SR Linux as M1's patterns did, through SurveyDevice: one row
// per interface, the port where one exists, an omission for a name a rule matched out of
// range, and a refusal for a name no rule matches.
func TestMap(t *testing.T) {
	prof, id := srlinuxProfile(t)
	cases := []struct {
		name     string
		in       ctm.Interface
		wantPort string
		wantDisp Disposition
		refusal  string // the rule of the one refusal expected, if any
	}{
		{"one-to-one", ctm.Interface{Name: "ethernet-1/1", Iftype: ctm.IftypePhysical}, "e1-1", DispConfiguredNotCabled, ""},
		{"double digits", ctm.Interface{Name: "ethernet-1/49", Iftype: ctm.IftypePhysical}, "e1-49", DispConfiguredNotCabled, ""},
		{"the bound's end", ctm.Interface{Name: "ethernet-1/58", Iftype: ctm.IftypePhysical}, "e1-58", DispConfiguredNotCabled, ""},
		{"cabled", ctm.Interface{Name: "ethernet-1/2", Iftype: ctm.IftypePhysical, Link: "n1:ethernet-1/2|n2:ethernet-1/2"}, "e1-2", DispCabled, ""},
		{"breakout child", ctm.Interface{Name: "ethernet-1/1/1", Iftype: ctm.IftypePhysical}, "e1-1-1", DispConfiguredNotCabled, ""},
		{"management bypasses patterns", ctm.Interface{Name: "mgmt0", Iftype: ctm.IftypePhysical, MgmtOnly: true}, "mgmt0", DispManagement, ""},
		{"management name need not match a pattern", ctm.Interface{Name: "anything", Iftype: ctm.IftypePhysical, MgmtOnly: true}, "mgmt0", DispManagement, ""},
		{"loopback has no port", ctm.Interface{Name: "lo0", Iftype: ctm.IftypeLoopback}, "", DispConfiguredNotCabled, ""},
		{"foreign naming matches no rule", ctm.Interface{Name: "Ethernet1", Iftype: ctm.IftypePhysical}, "", DispOmitted, findings.RuleInterfaceRuleUnmatched},
		{"partial name matches no rule", ctm.Interface{Name: "ethernet-1", Iftype: ctm.IftypePhysical}, "", DispOmitted, findings.RuleInterfaceRuleUnmatched},
		// The image has one slot and 58 front ports: M1's patterns mapped
		// these onto ports the node does not have.
		{"another slot is out of range", ctm.Interface{Name: "ethernet-3/7", Iftype: ctm.IftypePhysical}, "", DispOmitted, ""},
		{"past the last port is out of range", ctm.Interface{Name: "ethernet-1/59", Iftype: ctm.IftypePhysical}, "", DispOmitted, ""},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			s := SurveyDevice(ctm.Device{Name: "n1", Interfaces: []ctm.Interface{c.in}}, prof, id)
			if s.Err != nil || len(s.Rows) != 1 {
				t.Fatalf("survey = %+v", s)
			}
			if c.refusal != "" {
				if len(s.Refusals) != 1 || s.Refusals[0].Rule != c.refusal || len(s.Omissions) != 0 {
					t.Errorf("refusals %+v, omissions %+v; want one %s and no omission", s.Refusals, s.Omissions, c.refusal)
				}
				return
			}
			if len(s.Refusals) != 0 {
				t.Fatalf("survey = %+v", s)
			}
			r := s.Rows[0]
			var port string
			if r.Port != nil {
				port = *r.Port
			}
			if port != c.wantPort || r.Disposition != c.wantDisp {
				t.Errorf("%q = (%q, %s), want (%q, %s)", c.in.Name, port, r.Disposition, c.wantPort, c.wantDisp)
			}
			if (r.Disposition == DispOmitted) != (len(s.Omissions) == 1) {
				t.Errorf("omissions %+v for disposition %s", s.Omissions, r.Disposition)
			}
		})
	}
}

// An unhandled iftype is the survey's error, and the survey carries on past it so
// validation still hears every other interface.
func TestSurveyNamesAnUnhandledIftypeAndCarriesOn(t *testing.T) {
	prof, id := srlinuxProfile(t)
	s := SurveyDevice(ctm.Device{Name: "n1", Interfaces: []ctm.Interface{
		{Name: "ae1", Iftype: "lag"},
		{Name: "Ethernet99", Iftype: ctm.IftypePhysical, Link: "n1:Ethernet99|n2:ethernet-1/1"},
	}}, prof, id)
	if s.Err == nil {
		t.Error("an unhandled iftype produced no error")
	}
	if len(s.Refusals) != 1 || s.Refusals[0].Object != "n1:Ethernet99" {
		t.Errorf("refusals %+v, want the linked unmappable interface after the unhandled one", s.Refusals)
	}
}

// The profile's data rules must not overlap on SR Linux: the one-to-one rule must not
// swallow a breakout name, or a breakout child would silently map onto its parent's
// port. With [^/]+ placeholders their matches are disjoint, so their order in the
// package cannot change what either maps.
func TestPatternsDoNotOverlap(t *testing.T) {
	prof, _ := srlinuxProfile(t)
	var data []psp.Rule
	for _, r := range prof.Rules() {
		if !r.Management {
			data = append(data, r)
		}
	}
	for _, name := range []string{"ethernet-1/1", "ethernet-1/1/1"} {
		var fit []string
		for _, r := range data {
			pat, err := psp.CompilePattern(r.Match)
			if err != nil {
				t.Fatal(err)
			}
			if pat.Match(name) != nil {
				fit = append(fit, r.Name)
			}
		}
		if len(fit) != 1 {
			t.Errorf("%s fits rules %v; exactly one must", name, fit)
		}
	}
}

func TestPlaceholders(t *testing.T) {
	got := psp.Placeholders("ethernet-{slot}/{port}/{sub}")
	want := []string{"port", "slot", "sub"}
	if len(got) != len(want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("got %v, want %v", got, want)
		}
	}
}

func TestRenderReportsMissingPlaceholder(t *testing.T) {
	if _, err := psp.Render("e{slot}-{port}", map[string]string{"slot": "1"}); err == nil {
		t.Error("expected an error when a placeholder has no captured value")
	}
}

// A port intent disables reaches the bundle on its mapping row alone: the row says
// false, every other row says true, and the port is still
// cabled, its link still in links[], and the topology, every bootstrap and every configs
// file byte for byte what the unedited intent compiles to. The bootstrap still enables
// the port, and intent's disabling reaches the node through the artifact alone.
func TestIntentDisabledPortReachesTheMappingRowAlone(t *testing.T) {
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	const device, iface = "n1", "ethernet-1/2"
	plain := loadFixture(t, "testdata/ctm/three-node.json")
	edited := loadFixture(t, "testdata/ctm/three-node.json")
	disabled, found := false, false
	for d := range edited.Devices {
		for i, in := range edited.Devices[d].Interfaces {
			if edited.Devices[d].Name == device && in.Name == iface {
				edited.Devices[d].Interfaces[i].Enabled, found = &disabled, true
			}
		}
	}
	if !found {
		t.Fatalf("the fixture has no %s:%s; the test proves nothing", device, iface)
	}
	want, list := Compile(plain, reg)
	if list.Rejected() {
		t.Fatalf("the unedited fixture was rejected: %v", list)
	}
	got, list := Compile(edited, reg)
	if list.Rejected() {
		t.Fatalf("a port intent disables was rejected: %v", list)
	}

	if len(got) != len(want) {
		t.Errorf("the edited intent compiles to %d files, the unedited to %d", len(got), len(want))
	}
	for name, w := range want {
		if name == ManifestFile {
			continue
		}
		if !bytes.Equal(got[name], w) {
			t.Errorf("%s moved with intent's enabled; only the manifest's mapping row may:\n--- got\n%s\n--- want\n%s", name, got[name], w)
		}
	}

	var m, unedited Manifest
	if err := json.Unmarshal(got[ManifestFile], &m); err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(want[ManifestFile], &unedited); err != nil {
		t.Fatal(err)
	}
	for _, r := range m.Mapping {
		wantEnabled := r.Device != device || r.Interface != iface
		if r.Enabled == nil || *r.Enabled != wantEnabled || r.IsEnabled() != wantEnabled {
			t.Errorf("row %s:%s enabled %v (IsEnabled %t), want written %t", r.Device, r.Interface, r.Enabled, r.IsEnabled(), wantEnabled)
		}
		if !wantEnabled && (r.Disposition != DispCabled || r.Port == nil || *r.Port != "e1-2") {
			t.Errorf("row %s:%s is %s on %v; a port intent disables is still cabled on e1-2", r.Device, r.Interface, r.Disposition, r.Port)
		}
	}
	if n := bytes.Count(got[ManifestFile], []byte(`"enabled": false`)); n != 1 {
		t.Errorf(`the manifest carries "enabled": false %d times, want once`, n)
	}
	// Everything else in the manifest is the unedited intent's: put the row back, and
	// the two decode equal.
	for i, r := range m.Mapping {
		if r.Device == device && r.Interface == iface {
			enabled := true
			m.Mapping[i].Enabled = &enabled
		}
	}
	if !reflect.DeepEqual(m, unedited) {
		t.Errorf("the manifest differs from the unedited intent's beyond the row's enabled:\n%+v\n%+v", m, unedited)
	}
}

// A row read from a "3" manifest carries no key, and reads enabled: the CTM's own
// default.
// Every reader of a staged "3" bundle goes through this.
func TestMappingRowWithoutEnabledIsEnabled(t *testing.T) {
	no, yes := false, true
	for _, c := range []struct {
		name    string
		enabled *bool
		want    bool
	}{{"no key", nil, true}, {"false", &no, false}, {"true", &yes, true}} {
		if got := (MappingRow{Enabled: c.enabled}).IsEnabled(); got != c.want {
			t.Errorf("%s: IsEnabled = %t, want %t", c.name, got, c.want)
		}
	}

	// The three-node golden's manifest with every row's key removed, as a "3" manifest
	// is written.
	raw, err := os.ReadFile(filepath.Join("..", "..", "testdata", "golden", "three-node", ManifestFile))
	if err != nil {
		t.Fatal(err)
	}
	var doc map[string]any
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}
	doc["bundle_version"] = "3"
	for _, r := range doc["mapping"].([]any) {
		delete(r.(map[string]any), "enabled")
	}
	old, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(old, []byte(`"enabled"`)) {
		t.Fatal(`the edited manifest still carries "enabled"; the test proves nothing`)
	}
	var m Manifest
	if err := json.Unmarshal(old, &m); err != nil {
		t.Fatal(err)
	}
	if len(m.Mapping) == 0 {
		t.Fatal("the manifest has no mapping rows; the test proves nothing")
	}
	for _, r := range m.Mapping {
		if r.Enabled != nil || !r.IsEnabled() {
			t.Errorf("row %s:%s of a manifest without the key reads enabled %v, IsEnabled %t; want nil and true", r.Device, r.Interface, r.Enabled, r.IsEnabled())
		}
	}
}
