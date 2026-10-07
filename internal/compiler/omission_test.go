package compiler

import (
	"encoding/json"
	"os"
	"path/filepath"
	"sort"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// manifestOf compiles a fixture with the design-case package beside the embedded ones,
// which changes nothing for a fixture of embedded platforms alone.
func manifestOf(t *testing.T, fixture string) *Manifest {
	t.Helper()
	files := compileLossyFixture(t, "testdata/ctm/"+fixture)
	var m Manifest
	if err := json.Unmarshal(files[ManifestFile], &m); err != nil {
		t.Fatal(err)
	}
	return &m
}

func omissionRules(m *Manifest) map[string]string {
	out := map[string]string{}
	for _, o := range m.Omissions {
		out[o.Rule] = o.Object
	}
	return out
}

// A link landing on an out-of-band port describes the management network, which
// containerlab provides itself. Wiring it would invent topology; dropping it silently
// would be a lie. It is omitted and recorded.
func TestManagementLinkIsOmittedAndRecorded(t *testing.T) {
	m := manifestOf(t, "mgmt-link.json")
	rules := omissionRules(m)
	object, ok := rules[findings.RuleOmitLinkMgmtOnly]
	if !ok {
		t.Fatalf("out-of-band link was not recorded; omissions: %+v", m.Omissions)
	}
	if object != "n1:mgmt0|n2:mgmt0" {
		t.Errorf("omission names %q, want the link id", object)
	}
	if len(m.Omissions) != 1 {
		t.Errorf("got %d omissions, want exactly the one out-of-band link: %+v", len(m.Omissions), m.Omissions)
	}
	for _, o := range m.Omissions {
		if o.Reason != "out-of-band network not modelled" {
			t.Errorf("omission %s reason = %q", o.Rule, o.Reason)
		}
	}
	for _, l := range m.Links {
		if l.A.Port == "mgmt0" || l.B.Port == "mgmt0" {
			t.Errorf("an out-of-band port was cabled: %+v", l)
		}
	}
	// Only the out-of-band link is dropped; the real topology is untouched.
	if len(m.Links) != 3 {
		t.Errorf("cabled %d links, want the 3 data links", len(m.Links))
	}
}

// A name a rule matched out of range, with no link, names a port the node does not
// have: there is nothing of it to build, and it is never dropped without saying so. The
// row is omitted and the reason names the rule, the placeholder, its value and the
// range.
// Its linked counterpart is a refusal, below, so nothing unmappable is silent.
func TestUnmappableUnlinkedIsOmittedAndRecorded(t *testing.T) {
	m := manifestOf(t, "lossy.json")
	const object = "c1:Ethernet1/53"
	var found bool
	for _, o := range m.Omissions {
		if o.Object != object {
			continue
		}
		found = true
		if o.Rule != findings.RuleOmitInterfaceUnmappable {
			t.Errorf("omission rule = %s, want %s", o.Rule, findings.RuleOmitInterfaceUnmappable)
		}
		if want := "rule front matched, but {port} is 53, outside its range 1..52; no such port on the node"; o.Reason != want {
			t.Errorf("omission reason\n got  %q\n want %q", o.Reason, want)
		}
	}
	if !found {
		t.Fatalf("the out-of-range interface was not recorded; omissions: %+v", m.Omissions)
	}
	found = false
	for _, r := range m.Mapping {
		if r.Device+":"+r.Interface == object {
			found = true
			if r.Disposition != DispOmitted {
				t.Errorf("disposition = %s, want omitted", r.Disposition)
			}
			if r.Port != nil {
				t.Errorf("an omitted interface carries port %q", *r.Port)
			}
		}
	}
	if !found {
		t.Error("the out-of-range interface is missing from the mapping table entirely")
	}
}

// The other half of the split: an unmappable name that terminates a link is a refusal,
// never an omission, whether a rule matched it out of range or no rule matched it. The
// survey validation and the compiler share refuses it: validation files the refusal,
// and the compiler reports it as its guard and builds nothing.
func TestUnmappableLinkedIsARejectionNotAnOmission(t *testing.T) {
	for _, tc := range []struct{ fixture, object, message string }{
		{"unmappable-linked-range.json", "n1:ethernet-1/59",
			"rule ethernet matched this production name, but {port} is 59, outside its range 1..58, and it terminates a link"},
		{"unmappable-linked-unmatched.json", "n1:Ethernet99",
			"no rule of the nokia_srlinux profile matches this production name (tried: ethernet, breakout), and it terminates a link"},
	} {
		t.Run(tc.fixture, func(t *testing.T) {
			c := loadFixture(t, "testdata/ctm/defects/"+tc.fixture)
			reg, err := psp.Load("")
			if err != nil {
				t.Fatal(err)
			}
			d := c.Device("n1")
			pkg, _ := reg.Lookup(d.Platform.NOS)
			prof, err := psp.NewProfile(pkg)
			if err != nil {
				t.Fatal(err)
			}
			s := SurveyDevice(*d, prof, pkg.Platform.ID)
			if len(s.Refusals) != 1 || s.Refusals[0].Rule != findings.RuleUnmappableLinked ||
				s.Refusals[0].Object != tc.object || s.Refusals[0].Message != tc.message {
				t.Errorf("refusals %+v\nwant one %s naming %s: %s", s.Refusals, findings.RuleUnmappableLinked, tc.object, tc.message)
			}
			if len(s.Omissions) != 0 {
				t.Errorf("a linked unmappable interface was also omitted: %+v", s.Omissions)
			}

			files, list := Compile(c, reg)
			if files != nil {
				t.Error("the compiler built a bundle around a linked unmappable interface")
			}
			if len(list) != 1 || list[0].Rule != findings.RuleUnmappableLinked || list[0].Message != tc.message {
				t.Errorf("the compiler's guard = %v, want the survey's refusal alone", list)
			}
		})
	}
}

// A name no rule matches is refused even with no link: the profile has a gap or
// intent has a mistake, and omitting it would guess which. M1 omitted it; the fixture
// that proved the omission is now the refusal's.
func TestNoRuleUnlinkedIsARefusal(t *testing.T) {
	c := loadFixture(t, "testdata/ctm/defects/rule-unmatched.json")
	if in := c.Device("n1").Interface("Ethernet99"); in == nil || in.Link != "" {
		t.Fatal("rule-unmatched.json is meant to hold an unlinked n1:Ethernet99")
	}
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	files, list := Compile(c, reg)
	if files != nil {
		t.Error("the compiler built a bundle around a name no rule matches")
	}
	const want = "no rule of the nokia_srlinux profile matches this production name (tried: ethernet, breakout); the profile or the intent must be fixed"
	if len(list) != 1 || list[0].Severity != findings.Rejection || list[0].Rule != findings.RuleInterfaceRuleUnmatched ||
		list[0].Object != "n1:Ethernet99" || list[0].Message != want {
		t.Errorf("findings %v\nwant one rejection %s naming n1:Ethernet99: %s", list, findings.RuleInterfaceRuleUnmatched, want)
	}
}

// A node has one management connection. Intent may describe more than one out-of-band
// port; the rest are recorded rather than invented. The one kept is the first by
// interface name, so the choice does not depend on the order intent arrived in.
func TestSecondManagementPortIsOmittedAndRecorded(t *testing.T) {
	m := manifestOf(t, "two-mgmt.json")
	object, ok := omissionRules(m)[findings.RuleOmitMgmtExtra]
	if !ok {
		t.Fatalf("extra out-of-band port was not recorded; omissions: %+v", m.Omissions)
	}
	for _, o := range m.Omissions {
		if o.Rule == findings.RuleOmitMgmtExtra && o.Reason != "one management connection per node" {
			t.Errorf("omission reason = %q", o.Reason)
		}
	}

	// Which one was kept, and which omitted, is decided by name order.
	var mgmtNames, omittedNames []string
	for _, r := range m.Mapping {
		if r.Device != "n1" || !r.MgmtOnly {
			continue
		}
		switch r.Disposition {
		case DispManagement:
			mgmtNames = append(mgmtNames, r.Interface)
		case DispOmitted:
			omittedNames = append(omittedNames, r.Interface)
		}
	}
	if len(mgmtNames) != 1 {
		t.Fatalf("device n1 has %d management dispositions, want exactly 1: %v", len(mgmtNames), mgmtNames)
	}
	all := append(append([]string{}, mgmtNames...), omittedNames...)
	sorted := append([]string{}, all...)
	sort.Strings(sorted)
	if mgmtNames[0] != sorted[0] {
		t.Errorf("kept %q as the management port; the first out-of-band interface by name is %q",
			mgmtNames[0], sorted[0])
	}
	if object != "n1:"+omittedNames[0] {
		t.Errorf("omission names %q, want n1:%s", object, omittedNames[0])
	}
}

// Every omission appears in the fidelity manifest: it is the only trust signal Fylgja
// has, so nothing may be left out of it (Constitution X).
func TestOmissionsReachTheFidelityManifest(t *testing.T) {
	for _, fixture := range []string{"mgmt-link.json", "lossy.json", "two-mgmt.json"} {
		t.Run(fixture, func(t *testing.T) {
			m := manifestOf(t, fixture)
			if len(m.Omissions) == 0 {
				t.Fatalf("%s: expected an omission", fixture)
			}
			listed := map[string]bool{}
			for _, o := range m.Fidelity.Omitted {
				listed[o] = true
			}
			for _, o := range m.Omissions {
				if !listed[o.Object] {
					t.Errorf("omission %q is absent from the fidelity manifest", o.Object)
				}
				if o.Reason == "" {
					t.Errorf("omission %s gives no reason", o.Rule)
				}
			}
		})
	}
}

// Omissions are sorted by object then rule, so two compiles of the same intent list
// them in the same order and a diff of two manifests shows only real change.
func TestOmissionsAreSorted(t *testing.T) {
	for _, fixture := range []string{"mgmt-link.json", "lossy.json", "two-mgmt.json"} {
		m := manifestOf(t, fixture)
		for i := 1; i < len(m.Omissions); i++ {
			prev, cur := m.Omissions[i-1], m.Omissions[i]
			if prev.Object > cur.Object || (prev.Object == cur.Object && prev.Rule > cur.Rule) {
				t.Errorf("%s: omissions are not sorted by object then rule: %+v", fixture, m.Omissions)
			}
		}
	}
}

// Every omitted interface says so in its mapping row too, so a reader of the mapping
// table never has to cross-reference omissions[] to find out what happened to it.
func TestOmittedInterfacesAreMarkedInTheMapping(t *testing.T) {
	for _, fixture := range []string{"mgmt-link.json", "lossy.json", "two-mgmt.json"} {
		t.Run(fixture, func(t *testing.T) {
			m := manifestOf(t, fixture)
			recorded := map[string]bool{}
			for _, o := range m.Omissions {
				recorded[o.Object] = true
			}
			for _, r := range m.Mapping {
				object := r.Device + ":" + r.Interface
				if r.Disposition == DispOmitted && !recorded[object] {
					t.Errorf("%s is omitted in the mapping with no entry in omissions[]", object)
				}
			}
		})
	}
}

// Every node has a management connection whether or not intent describes one:
// containerlab provides it, so it does not depend on an interface being flagged
// `mgmt_only`. A device with no such interface — or with no interfaces at all — still
// gets the platform's management port.
func TestManagementPortDoesNotDependOnIntent(t *testing.T) {
	m := manifestOf(t, "no-mgmt.json")
	for _, n := range m.Nodes {
		if n.ManagementPort == "" {
			t.Errorf("node %s has no management port", n.Name)
		}
	}
	byName := map[string]ManifestNode{}
	for _, n := range m.Nodes {
		byName[n.Name] = n
	}
	// n2 has data ports but no mgmt_only interface; n4 has no interfaces at all.
	for _, name := range []string{"n2", "n4"} {
		n, ok := byName[name]
		if !ok {
			t.Fatalf("node %s is missing from the manifest", name)
		}
		if n.ManagementPort != "mgmt0" {
			t.Errorf("node %s management port = %q, want the platform's mgmt0", name, n.ManagementPort)
		}
	}
	// A device with no interfaces contributes no mapping rows, and that is not an
	// omission: there was nothing to leave out.
	for _, r := range m.Mapping {
		if r.Device == "n4" {
			t.Errorf("device with no interfaces produced a mapping row: %+v", r)
		}
	}
	for _, o := range m.Omissions {
		if o.Object == "n4" {
			t.Errorf("device with no interfaces was recorded as an omission: %+v", o)
		}
	}
}

// The manifest records which support package built each node and whether it was the
// shipped one, so a twin built with a local override says so rather than looking
// identical to one built from the embedded package.
func TestManifestRecordsOverriddenSupportPackage(t *testing.T) {
	dir := t.TempDir()
	src, err := os.ReadFile(filepath.Join("..", "..", "psp", "nokia_srlinux.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(filepath.Join(dir, "nokia_srlinux.yaml"), src, 0o644); err != nil {
		t.Fatal(err)
	}

	c, err := ctm.Load(filepath.Join("..", "..", "testdata", "ctm", "three-node.json"))
	if err != nil {
		t.Fatal(err)
	}
	reg, err := psp.Load(dir)
	if err != nil {
		t.Fatal(err)
	}
	files, list := Compile(c, reg)
	if list.Rejected() {
		t.Fatalf("the fixture was rejected: %v", list)
	}
	var m Manifest
	if err := json.Unmarshal(files[ManifestFile], &m); err != nil {
		t.Fatal(err)
	}
	for _, n := range m.Nodes {
		if n.PSP.Source != psp.OriginOverride {
			t.Errorf("node %s records psp.source %q, want %q", n.Name, n.PSP.Source, psp.OriginOverride)
		}
	}
}
