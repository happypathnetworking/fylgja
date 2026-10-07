package validate

import (
	"encoding/json"
	"maps"
	"os"
	"path/filepath"
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
	list := Validate(c, reg)
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
	if list := Validate(c, reg); list.Rejected() {
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
		{"defects/iftype-unimplemented.json", findings.RuleIftypeUnimplemented},
		{"defects/platform-unsupported.json", findings.RulePlatformUnsupported},
		{"defects/device-duplicate.json", findings.RuleDeviceNameDuplicate},
		{"defects/link-one-endpoint.json", findings.RuleLinkEndpointsCount},
		{"defects/mgmt-only-loopback.json", findings.RuleMgmtOnlyIftype},
		{"defects/link-endpoint-loopback.json", findings.RuleLinkEndpointIftype},
	}
	for _, tc := range cases {
		t.Run(tc.fixture, func(t *testing.T) {
			c, reg := load(t, tc.fixture)
			list := Validate(c, reg)
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
// useful if each report points at the thing to fix. These five pairs are the fixture's
// five defects, each pointing at its object.
func TestAllDefectsReportedInOnePass(t *testing.T) {
	c, reg := load(t, "defects/five.json")
	list := Validate(c, reg)

	want := map[string]string{
		findings.RuleDeviceNameDuplicate: "n1",
		findings.RuleIftypeUnimplemented: "n1:lo0",
		findings.RuleMgmtOnlyIftype:      "n3:lo0",
		findings.RuleLinkEndpointsCount:  "n1:ethernet-1/1|n2:ethernet-1/1",
		findings.RulePlatformUnsupported: "n2",
	}
	got := map[string]string{}
	for _, f := range list {
		got[f.Rule] = f.Object
	}
	for rule, object := range want {
		switch actual, ok := got[rule]; {
		case !ok:
			t.Errorf("rule %s missing from a single pass; got %v", rule, got)
		case actual != object:
			t.Errorf("rule %s names %q, want %q", rule, actual, object)
		}
	}
	if len(got) != len(want) {
		t.Errorf("got %d distinct rules, want %d: %v", len(got), len(want), got)
	}
	if len(list) != len(want) {
		t.Errorf("got %d findings, want exactly %d, one per defect: %v", len(list), len(want), list)
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
			if list := Validate(c, reg); list.Rejected() {
				t.Errorf("%s should validate: omissions are recorded, not fatal; got %v", name, list)
			}
		})
	}
}

// A required attribute left unpopulated must name both the object and what is missing,
// so the fix is obvious from the report alone.
func TestRequiredAttributeMissingIsNamed(t *testing.T) {
	c, reg := load(t, "defects/required-missing.json")
	list := Validate(c, reg)
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
			if !strings.Contains(f.Message, "platform") {
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
	n1.Interfaces = append(n1.Interfaces, ctm.Interface{Iftype: ctm.IftypePhysical})

	list := Validate(c, reg)
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
	for _, f := range Validate(c, reg) {
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
		Branch:          "fylgja-fixture",
		ObservedAt:      "2026-09-08T12:00:00.000000Z",
		SchemaHash:      "fixture",
		ContractVersion: "0.2",
	}
	for _, tc := range []struct {
		field string
		blank func(*ctm.Envelope)
	}{
		{"envelope.branch", func(e *ctm.Envelope) { e.Branch = "" }},
		{"envelope.observed_at", func(e *ctm.Envelope) { e.ObservedAt = "" }},
		{"envelope.schema_hash", func(e *ctm.Envelope) { e.SchemaHash = "" }},
		{"envelope.contract_version", func(e *ctm.Envelope) { e.ContractVersion = "" }},
	} {
		t.Run(tc.field, func(t *testing.T) {
			env := full
			tc.blank(&env)
			c, _ := load(t, "three-node.json")
			c.Envelope = env
			list := Validate(c, registry(t))
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
	for _, f := range Validate(c, reg) {
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
				Branch:          "fylgja-fixture",
				At:              tc.at,
				ObservedAt:      "2026-09-08T12:00:00.000000Z",
				SchemaHash:      "fixture",
				ContractVersion: "0.2",
			}}
			list := Validate(c, registry(t))
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
	if list := Validate(c, reg); list.Rejected() {
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
			Branch:          "fylgja-fixture",
			ObservedAt:      "2026-09-08T12:00:00.000000Z",
			SchemaHash:      "fixture",
			ContractVersion: ctm.ContractVersion,
		},
		Devices: []ctm.Device{
			{
				Name:       "n1",
				Platform:   ctm.Platform{Vendor: "nokia", NOS: "srlinux"},
				Interfaces: []ctm.Interface{{Name: "ethernet-1/1", Iftype: ctm.IftypePhysical}},
				Artifact:   artifact("n1"),
			},
			{
				Name:       "n2",
				Platform:   ctm.Platform{Vendor: "acme", NOS: "acme_os"},
				Interfaces: []ctm.Interface{{Name: "ethernet-1/1", Iftype: ctm.IftypePhysical}},
				Artifact:   artifact("n2"),
			},
		},
	}

	if list := Validate(c, reg); list.Rejected() {
		t.Errorf("validation refused a twin whose platforms forward differently: %v", list)
	}

	files, list := compiler.Compile(c, reg)
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
