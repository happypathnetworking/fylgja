package validate

import (
	"encoding/json"
	"maps"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

func load(t *testing.T, name string) (*ctm.CTM, *psp.Registry) {
	t.Helper()
	return loadWith(t, name, "")
}

// loadWith loads a fixture with an override directory's packages beside the embedded
// ones, as --psp-dir does.
func loadWith(t *testing.T, name, pspDir string) (*ctm.CTM, *psp.Registry) {
	t.Helper()
	c, err := ctm.Load(filepath.Join("..", "..", "testdata", "ctm", name))
	if err != nil {
		t.Fatal(err)
	}
	reg, err := psp.Load(pspDir)
	if err != nil {
		t.Fatal(err)
	}
	return c, reg
}

func registry(t *testing.T) *psp.Registry {
	t.Helper()
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	return reg
}

func rulesOf(list findings.List) map[string]int {
	out := map[string]int{}
	for _, f := range list {
		out[f.Rule]++
	}
	return out
}

func TestValidFixturePasses(t *testing.T) {
	c, reg := load(t, "three-node.json")
	list := Validate(c, nil, reg, nil)
	if list.Rejected() {
		t.Errorf("the reference fixture must validate cleanly, got %v", list)
	}
}

// An unpinned CTM is as valid as a pinned one: `at` is present iff the operator asked
// for it, and requiring it would refuse every unpinned read.
func TestUnpinnedFixturePasses(t *testing.T) {
	c, reg := load(t, "no-mgmt.json")
	if c.Envelope.At != "" {
		t.Fatalf("no-mgmt.json is meant to be an unpinned fixture, but carries at=%q", c.Envelope.At)
	}
	if list := Validate(c, nil, reg, nil); list.Rejected() {
		t.Errorf("an unpinned CTM must validate; got %v", list)
	}
}

// Each defect must be reported by the rule that names it, so an operator reading a
// report knows what to change.
func TestDefectsAreNamed(t *testing.T) {
	cases := []struct {
		fixture string
		rule    string
	}{
		{"defects/platform-unsupported.json", findings.RulePlatformUnsupported},
		{"defects/device-duplicate.json", findings.RuleDeviceNameDuplicate},
		{"defects/link-one-endpoint.json", findings.RuleLinkEndpointsCount},
		{"defects/link-same-device.json", findings.RuleLinkEndpointsSameDev},
	}
	for _, tc := range cases {
		t.Run(tc.fixture, func(t *testing.T) {
			c, reg := load(t, tc.fixture)
			list := Validate(c, nil, reg, nil)
			if !list.Rejected() {
				t.Fatalf("expected a rejection, got %v", list)
			}
			if rulesOf(list)[tc.rule] == 0 {
				t.Errorf("expected rule %s, got %v", tc.rule, rulesOf(list))
			}
			for _, f := range list {
				if f.Object == "" {
					t.Errorf("finding %s names no object", f.Rule)
				}
			}
		})
	}
}

// Every problem in one pass: an operator should not discover the next defect on the
// next attempt.
//
// The objects are asserted alongside the rules, because "reported in one pass" is only
// useful if each report points at the thing to fix. The fixture carries five defects,
// each pointing at its object; its same-device link also ends on two interfaces another
// link already ends on, so the port each names would be cabled twice, and each is named
// under data.required.missing (LinkTerminations): seven findings, one per fault.
func TestAllDefectsReportedInOnePass(t *testing.T) {
	c, reg := load(t, "defects/five.json")
	list := Validate(c, nil, reg, nil)

	type named struct{ rule, object string }
	want := []named{
		{findings.RuleInterfaceRuleUnmatched, "n1:Ethernet99"},
		{findings.RuleDeviceNameDuplicate, "n1"},
		{findings.RulePlatformUnsupported, "n2"},
		{findings.RuleLinkEndpointsCount, "n1:ethernet-1/1|n2:ethernet-1/1"},
		{findings.RuleLinkEndpointsSameDev, "n3:ethernet-1/1|n3:ethernet-1/2"},
		{findings.RuleRequiredMissing, "n3:ethernet-1/1"},
		{findings.RuleRequiredMissing, "n3:ethernet-1/2"},
	}
	got := make([]named, 0, len(list))
	for _, f := range list {
		got = append(got, named{f.Rule, f.Object})
	}
	if !slices.Equal(got, want) {
		t.Errorf("one pass, one finding per fault:\n got  %v\n want %v\n%v", got, want, list)
	}
}

// A link and the interfaces it ends on name one another (LinkTerminations). Each CTM
// below passed validation before the rule and compiled to a bundle that misdescribes its
// twin: a port cabled twice, a port the topology cables while its row says
// configured-not-cabled, a row saying cabled with no veth. Each is refused under
// data.required.missing, naming the link id and the device:interface, and nothing else in
// the fixture is.
func TestLinkFieldsAndLinksAgree(t *testing.T) {
	const (
		n1n2 = "n1:ethernet-1/1|n2:ethernet-1/1"
		n2n3 = "n2:ethernet-1/2|n3:ethernet-1/1"
		n1n3 = "n1:ethernet-1/1|n3:ethernet-1/3"
		rule = "an interface names the one link it terminates"
	)
	for _, tc := range []struct {
		name   string
		edit   func(c *ctm.CTM)
		object []string
		want   []string
	}{
		{"an interface two links end on", func(c *ctm.CTM) {
			n3 := c.Device("n3")
			n3.Interfaces = append(n3.Interfaces, ctm.Interface{Name: "ethernet-1/3", Link: n1n3})
			c.Links = append(c.Links, ctm.Link{ID: n1n3, Endpoints: []ctm.Endpoint{
				{Device: "n1", Interface: "ethernet-1/1"}, {Device: "n3", Interface: "ethernet-1/3"}}})
		}, []string{"n1:ethernet-1/1"}, []string{
			"n1:ethernet-1/1 is an endpoint of 2 links (" + n1n2 + ", " + n1n3 + "); " + rule +
				", and a bundle whose links cable one port twice is never produced"}},
		{"a link ending on an interface carrying no link", func(c *ctm.CTM) {
			c.Device("n2").Interface("ethernet-1/1").Link = ""
		}, []string{n1n2}, []string{
			"endpoint n2:ethernet-1/1 carries no link; " + rule +
				", and a bundle that cables a port its mapping calls configured-not-cabled is never produced"}},
		{"a link ending on an interface carrying another link", func(c *ctm.CTM) {
			c.Device("n2").Interface("ethernet-1/1").Link = n2n3
		}, []string{n1n2}, []string{
			"endpoint n2:ethernet-1/1 carries link \"" + n2n3 + "\"; " + rule}},
		{"an interface carrying a link not in intent", func(c *ctm.CTM) {
			n3 := c.Device("n3")
			n3.Interfaces = append(n3.Interfaces, ctm.Interface{Name: "ethernet-1/3", Link: n1n3})
		}, []string{"n3:ethernet-1/3"}, []string{
			"n3:ethernet-1/3 carries link \"" + n1n3 + "\", which is not in intent; " + rule +
				", and a bundle that calls a port cabled with no cable on it is never produced"}},
		{"an interface carrying a link that ends elsewhere", func(c *ctm.CTM) {
			n3 := c.Device("n3")
			n3.Interfaces = append(n3.Interfaces, ctm.Interface{Name: "ethernet-1/3", Link: n1n2})
		}, []string{"n3:ethernet-1/3"}, []string{
			"n3:ethernet-1/3 carries link \"" + n1n2 + "\", which does not end on it; " + rule +
				", and a bundle that calls a port cabled with no cable on it is never produced"}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			c, reg := load(t, "three-node.json")
			tc.edit(c)
			list := Validate(c, nil, reg, nil)
			if len(list) != len(tc.want) {
				t.Fatalf("got %d findings, want %d:\n%v", len(list), len(tc.want), list)
			}
			for i, f := range list {
				if f.Severity != findings.Rejection || f.Rule != findings.RuleRequiredMissing ||
					f.Object != tc.object[i] || f.Message != tc.want[i] {
					t.Errorf("finding %d:\n got  %s %s %q %q\n want rejection %s %q %q",
						i, f.Severity, f.Rule, f.Object, f.Message, findings.RuleRequiredMissing, tc.object[i], tc.want[i])
				}
			}
		})
	}
}

// Omissions are not rejections. An out-of-band link, an unlinked name a rule matched
// out of range and a second management port are recorded and compilation continues.
// lossy.json carries the out-of-range name, on the design-case
// platform, and its shared ports are recorded too.
func TestOmissionsDoNotReject(t *testing.T) {
	lossy := filepath.Join("..", "..", "testdata", "psp", "lossy")
	for _, name := range []string{"mgmt-link.json", "lossy.json", "two-mgmt.json"} {
		t.Run(name, func(t *testing.T) {
			c, reg := loadWith(t, name, lossy)
			if list := Validate(c, nil, reg, nil); list.Rejected() {
				t.Errorf("%s should validate: omissions are recorded, not fatal; got %v", name, list)
			}
		})
	}
}

// A required attribute left unpopulated must name both the object and what is missing,
// so the fix is obvious from the report alone. In a CTM "2" the fixture's is the
// envelope's schema hash: a device's package left empty is platform.unsupported, since
// it names no package of the registry.
func TestRequiredAttributeMissingIsNamed(t *testing.T) {
	c, reg := load(t, "defects/required-missing.json")
	list := Validate(c, nil, reg, nil)
	if !list.Rejected() {
		t.Fatalf("expected a rejection, got %v", list)
	}
	var found bool
	for _, f := range list {
		if f.Rule == findings.RuleRequiredMissing {
			found = true
			if f.Object == "" {
				t.Error("the finding names no object")
			}
			if !strings.Contains(f.Message, "schema") {
				t.Errorf("message does not say what is missing: %q", f.Message)
			}
		}
	}
	if !found {
		t.Errorf("expected %s, got %v", findings.RuleRequiredMissing, rulesOf(list))
	}
}

// An interface with no name draws one finding, the one that says so. The profile is
// applied to it like any other, and no rule matches an empty production name, so the
// survey refuses it too — under an object naming no interface, which would be filed
// after every other finding, far from the mistake. M5 reported the missing name alone
// and M6 changes nothing here.
func TestUnnamedInterfaceDrawsOneFinding(t *testing.T) {
	c, reg := load(t, "three-node.json")
	n1 := c.Device("n1")
	n1.Interfaces = append(n1.Interfaces, ctm.Interface{})

	list := Validate(c, nil, reg, nil)
	want := findings.List{{Severity: findings.Rejection, Rule: findings.RuleRequiredMissing,
		Object: "n1", Message: "an interface has no name"}}
	if len(list) != len(want) || list[0].Rule != want[0].Rule || list[0].Object != want[0].Object ||
		list[0].Message != want[0].Message || list[0].Severity != want[0].Severity {
		t.Errorf("findings:\n got  %v\n want %v", list, want)
	}
}

// A production management name that is not flagged mgmt_only is whatever the data rules
// make of it, and nothing more: the profile never infers use from a name (D-003). On the
// design case no data rule matches `Management1`, so the refusal names the rules tried,
// and an operator reading it sees the flag is missing.
func TestUnflaggedManagementNameIsRefusedByTheRulesTried(t *testing.T) {
	c, reg := loadWith(t, "lossy.json", filepath.Join("..", "..", "testdata", "psp", "lossy"))
	c.Device("c1").Interface("Management1").MgmtOnly = false

	var got []findings.Finding
	for _, f := range Validate(c, nil, reg, nil) {
		if f.Object == "c1:Management1" {
			got = append(got, f)
		}
	}
	if len(got) != 1 {
		t.Fatalf("findings on c1:Management1: got %v, want one", got)
	}
	if got[0].Rule != findings.RuleInterfaceRuleUnmatched || got[0].Severity != findings.Rejection {
		t.Errorf("finding = %s/%s, want a %s rejection", got[0].Severity, got[0].Rule, findings.RuleInterfaceRuleUnmatched)
	}
	want := "no rule of the chassisos profile matches this production name " +
		"(tried: front, linecard, breakout); the profile or the intent must be fixed"
	if got[0].Message != want {
		t.Errorf("message:\n got  %q\n want %q", got[0].Message, want)
	}
}

// The envelope is what makes a CTM reproducible. A file missing any of its required
// fields is rejected by the field name, so the report says which one.
func TestEnvelopeRequiredFieldsAreNamed(t *testing.T) {
	full := ctm.Envelope{
		Branch:     "fylgja-fixture",
		ObservedAt: "2026-09-08T12:00:00.000000Z",
		SchemaHash: "fixture",
		Scope:      "tag:fylgja",
		Mapping:    ctm.Mapping{Reader: ctm.ReaderInfrahubDCIM, Model: ctm.ModelSchemaLibrary, Version: ctm.ModelVersion},
	}
	for _, tc := range []struct {
		field string
		blank func(*ctm.Envelope)
	}{
		{"envelope.branch", func(e *ctm.Envelope) { e.Branch = "" }},
		{"envelope.observed_at", func(e *ctm.Envelope) { e.ObservedAt = "" }},
		{"envelope.schema_hash", func(e *ctm.Envelope) { e.SchemaHash = "" }},
		{"envelope.scope", func(e *ctm.Envelope) { e.Scope = "" }},
		{"envelope.mapping.reader", func(e *ctm.Envelope) { e.Mapping.Reader = "" }},
		{"envelope.mapping.model", func(e *ctm.Envelope) { e.Mapping.Model = "" }},
		{"envelope.mapping.version", func(e *ctm.Envelope) { e.Mapping.Version = "" }},
	} {
		t.Run(tc.field, func(t *testing.T) {
			env := full
			tc.blank(&env)
			c, _ := load(t, "three-node.json")
			c.Envelope = env
			list := Validate(c, nil, registry(t), nil)
			var found bool
			for _, f := range list {
				if f.Rule == findings.RuleRequiredMissing && f.Object == tc.field {
					found = true
				}
			}
			if !found {
				t.Errorf("a missing %s must be rejected naming that field; got %v", tc.field, list)
			}
		})
	}
}

// `at` is the one envelope field that is optional, and a rule that demanded it would
// make every unpinned read a rejection.
func TestEnvelopeDoesNotRequireAt(t *testing.T) {
	c, reg := load(t, "three-node.json")
	c.Envelope.At = ""
	for _, f := range Validate(c, nil, reg, nil) {
		if f.Rule == findings.RuleRequiredMissing && strings.Contains(f.Object, "at") {
			t.Errorf("an absent `at` must not be a finding; got %+v", f)
		}
	}
}

// An empty read is rejected rather than written out: it is almost always a wrong `at`,
// and a manifest for zero nodes has no fidelity to report.
// The finding names the branch, and the `at` when there is one, because that pair is
// what the operator has to correct.
func TestEmptyCTMIsRejectedNamingTheReference(t *testing.T) {
	for _, tc := range []struct {
		label string
		at    string
	}{
		{"unpinned", ""},
		{"pinned", "2026-09-08T12:00:00Z"},
	} {
		t.Run(tc.label, func(t *testing.T) {
			c := &ctm.CTM{Envelope: ctm.Envelope{
				Branch:     "fylgja-fixture",
				At:         tc.at,
				ObservedAt: "2026-09-08T12:00:00.000000Z",
				SchemaHash: "fixture",
				Scope:      "tag:fylgja",
				Mapping:    ctm.Mapping{Reader: ctm.ReaderInfrahubDCIM, Model: ctm.ModelSchemaLibrary, Version: ctm.ModelVersion},
			}}
			list := Validate(c, nil, registry(t), nil)
			if !list.Rejected() {
				t.Fatalf("an empty CTM must be rejected; got %v", list)
			}
			var found *findings.Finding
			for i, f := range list {
				if f.Rule == findings.RuleDevicesEmpty {
					found = &list[i]
				}
			}
			if found == nil {
				t.Fatalf("expected %s, got %v", findings.RuleDevicesEmpty, rulesOf(list))
			}
			if !strings.Contains(found.Object, "fylgja-fixture") {
				t.Errorf("the finding does not name the branch: object %q", found.Object)
			}
			if !strings.Contains(found.Message, "fylgja-fixture") {
				t.Errorf("the message does not name the branch: %q", found.Message)
			}
			if tc.at != "" && !strings.Contains(found.Message, tc.at) {
				t.Errorf("a pinned empty read must name the `at`: %q", found.Message)
			}
		})
	}
}

// A device with no mgmt_only interface, and one with no interfaces at all, are both
// legitimate intent — not defects.
func TestSparseDevicesValidate(t *testing.T) {
	c, reg := load(t, "no-mgmt.json")
	if list := Validate(c, nil, reg, nil); list.Rejected() {
		t.Errorf("a device without an out-of-band port is valid intent; got %v", list)
	}
}

// A twin whose two platforms disagree about production forwarding now reads and
// compiles clean, and the manifest asserts each platform's own value.
//
// Until bundle "3" the manifest held one fidelity.production_forwarding for the whole
// bundle, so a second answer had nowhere to go: validation and the compiler both refused
// such a twin as fidelity.forwarding.mixed rather than assert either value over the
// other platform's nodes (D-025, Constitution X). The field is an object keyed by
// platform from "3", so there is nothing left to refuse — the retirement is the
// behaviour change, and this test is what would catch it coming back.
//
// Both halves are asserted here, in one test, because the rule they replace lived in
// both: a validation that passed while the compiler still refused would put `intent
// read` and `twin compile` back out of step, which is the thing M1 settled.
func TestDisagreeingForwardingIsNoLongerRefused(t *testing.T) {
	src, err := os.ReadFile(filepath.Join("..", "..", "psp", "nokia_srlinux.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "nokia_srlinux.yaml"), src, 0o644); err != nil {
		t.Fatal(err)
	}
	// Derived from the shipped package, so the second platform is valid against
	// psp.schema.json without a fixture to maintain; only what makes it a different
	// platform, and its forwarding answer, change.
	second := string(src)
	for from, to := range map[string]string{
		"id: nokia_srlinux":               "id: acme_os",
		"nos: srlinux":                    "nos: acme_os",
		"manufacturer: Nokia":             "manufacturer: Acme",
		"platform: SR Linux":              "platform: AcmeOS",
		"production_forwarding: hardware": "production_forwarding: software",
	} {
		if !strings.Contains(second, from) {
			t.Fatalf("the shipped package no longer contains %q; update this test", from)
		}
		second = strings.Replace(second, from, to, 1)
	}
	if err := os.WriteFile(filepath.Join(dir, "acme_os.yaml"), []byte(second), 0o644); err != nil {
		t.Fatal(err)
	}
	reg, err := psp.Load(dir)
	if err != nil {
		t.Fatal(err)
	}

	artifact := func(device string) *ctm.Artifact {
		content := "# " + device + "\nset / system name host-name " + device + "\n"
		return &ctm.Artifact{
			Name:        "device-config",
			ContentType: "text/plain",
			Checksum:    ctm.ChecksumOf(content),
			Content:     content,
		}
	}
	c := &ctm.CTM{
		CTMVersion: ctm.Version,
		Envelope: ctm.Envelope{
			Branch:     "fylgja-fixture",
			ObservedAt: "2026-09-08T12:00:00.000000Z",
			SchemaHash: "fixture",
			Scope:      "tag:fylgja",
			Mapping:    ctm.Mapping{Reader: ctm.ReaderInfrahubDCIM, Model: ctm.ModelSchemaLibrary, Version: ctm.ModelVersion},
		},
		Devices: []ctm.Device{
			{
				Name:       "n1",
				Platform:   ctm.Platform{Package: "nokia_srlinux"},
				Interfaces: []ctm.Interface{{Name: "ethernet-1/1"}},
				Artifact:   artifact("n1"),
			},
			{
				Name:       "n2",
				Platform:   ctm.Platform{Package: "acme_os"},
				Interfaces: []ctm.Interface{{Name: "ethernet-1/1"}},
				Artifact:   artifact("n2"),
			},
		},
	}

	if list := Validate(c, nil, reg, nil); list.Rejected() {
		t.Errorf("validation refused a twin whose platforms forward differently: %v", list)
	}

	files, list := compiler.Compile(c, nil, reg, nil)
	if list.Rejected() {
		t.Fatalf("the compiler refused it: %v", list)
	}
	var m compiler.Manifest
	if err := json.Unmarshal(files[compiler.ManifestFile], &m); err != nil {
		t.Fatal(err)
	}
	want := map[string]string{"acme_os": "software", "nokia_srlinux": "hardware"}
	if !maps.Equal(m.Fidelity.ProductionForwarding, want) {
		t.Errorf("production_forwarding = %v, want %v", m.Fidelity.ProductionForwarding, want)
	}
}

// A CTM "2" names the package a device's platform matched (017). One the registry lacks,
// or none at all, is platform.unsupported naming the package and the registry's ids, so
// the fix is a package to write or a name to correct.
func TestPlatformUnsupportedNamesThePackageAndTheRegistry(t *testing.T) {
	for pkg, want := range map[string]string{
		"acme_os": `no support package "acme_os"; supported: [arista_eos nokia_srlinux]`,
		"":        "device names no support package; supported: [arista_eos nokia_srlinux]",
	} {
		c, reg := load(t, "three-node.json")
		c.Device("n2").Platform.Package = pkg
		var got []string
		for _, f := range Validate(c, nil, reg, nil) {
			got = append(got, f.Rule+" "+f.Object+": "+f.Message)
		}
		if w := findings.RulePlatformUnsupported + " n2: " + want; len(got) != 1 || got[0] != w {
			t.Errorf("package %q: findings %q, want exactly %q", pkg, got, w)
		}
	}
}
