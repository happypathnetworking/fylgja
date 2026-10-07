package psp

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"reflect"
	"regexp"
	"slices"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

func repo(parts ...string) string {
	return filepath.Join(append([]string{"..", ".."}, parts...)...)
}

func rulesIn(list findings.List) map[string]int {
	out := map[string]int{}
	for _, f := range list {
		out[f.Rule]++
	}
	return out
}

// Every shipped package must validate cleanly, offline, and be one the binary carries.
// If one does not validate, every twin built with it is suspect; if one is on disk but
// not embedded, a build would ship a platform it cannot support and say nothing.
//
// The files are found by the glob psp.Embedded() reads, so a package added to psp/ is
// held to this without a line changing here, and the two sides are compared by name: a
// file the binary does not carry, or a carried package with no file, fails.
//
// They are validated in one call, so checkDuplicateIdentity sees them together: two
// shipped packages claiming one platform would otherwise pass one at a time.
func TestShippedPackagesAreValidAndEmbedded(t *testing.T) {
	paths, err := filepath.Glob(repo("psp", "*.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	if len(paths) < 2 {
		t.Fatalf("found %d shipped packages, want the SR Linux and EOS ones at least", len(paths))
	}
	if list := Validate(paths); list.Rejected() {
		t.Errorf("every shipped package must validate: %v", list)
	}

	embedded, err := Embedded()
	if err != nil {
		t.Fatal(err)
	}
	var carried, onDisk, ids []string
	for _, p := range embedded {
		carried = append(carried, filepath.Base(p.Path))
		ids = append(ids, p.Platform.ID)
	}
	for _, path := range paths {
		onDisk = append(onDisk, filepath.Base(path))
	}
	slices.Sort(carried)
	slices.Sort(onDisk)
	slices.Sort(ids)
	if !slices.Equal(carried, onDisk) {
		t.Errorf("the binary carries %v, psp/ holds %v; one glob reads both", carried, onDisk)
	}
	// Named, so a shipped package deleted, renamed or given another id fails here
	// rather than leaving both sides equally empty.
	for _, id := range []string{"arista_eos", "nokia_srlinux"} {
		if !slices.Contains(ids, id) {
			t.Errorf("the binary carries no package for platform %s; it carries %v", id, ids)
		}
	}

	// A shipped package states what was measured, so a marker left where a
	// value is still to be verified must never reach a release.
	for _, path := range paths {
		raw, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		if bytes.Contains(raw, []byte("# verify")) {
			t.Errorf("%s still carries a `# verify` marker", filepath.Base(path))
		}
	}
}

// Each defect must be reported by the rule that names it, with a file location: a
// platform author needs to know which file and which rule.
func TestDefectsAreNamed(t *testing.T) {
	cases := []struct {
		fixture string
		rule    string
		// messages, where given, are every finding the fixture raises, word for word:
		// a fixture that passed validation before its rule existed must fail with that
		// rule alone.
		messages []string
		// messagesOfRule limits that comparison to the findings of the rule under
		// test. A declaration the JSON schema refuses too draws psp.schema findings
		// whose wording is the schema library's, not ours; the named rule is what
		// says to a platform author what the declaration is for.
		messagesOfRule bool
	}{
		// Format 0.4's mapping profile. Each fixture is the
		// shipped package with one change.
		{"rule-name-missing", findings.RulePSPRuleName, nil, false},
		{"rule-name-duplicate", findings.RulePSPRuleName, nil, false},
		{"placeholders-disagree", findings.RulePSPPatternsPlaceholders, nil, false},
		{"node-name-placeholders", findings.RulePSPPatternsPlaceholders, nil, false},
		{"lossy-undeclared", findings.RulePSPPatternsPlaceholders, nil, false},
		{"lossy-overdeclared", findings.RulePSPPatternsPlaceholders, nil, false},
		{"range-unknown-placeholder", findings.RulePSPPatternsPlaceholders, nil, false},
		{"breakout-parent-placeholders", findings.RulePSPPatternsBreakout, nil, false},
		{"breakout-parent-is-match", findings.RulePSPPatternsBreakout, nil, false},
		{"management-rule-missing", findings.RulePSPManagementRule, nil, false},
		{"management-rule-twice", findings.RulePSPManagementRule, nil, false},
		{"management-rule-with-match", findings.RulePSPManagementRule, nil, false},
		{"management-collides", findings.RulePSPManagementCollides, nil, false},
		// A data rule that can render the management port or node name. Both fixtures
		// passed validation before psp.management.collides existed. The second is chassisos,
		// not the shipped package, and front and linecard both render its name.
		{"management-port-reachable", findings.RulePSPManagementCollides, []string{
			`management port "e1-1" is also rendered by rule "ethernet" (port "e{slot}-{port}", {slot} = 1, {port} = 1); one port would mean two things`,
		}, false},
		{"management-node-name-reachable", findings.RulePSPManagementCollides, []string{
			`management node name "Ethernet1" is also rendered by rule "front" (node_name "Ethernet{port}", {port} = 1); one name would mean two things`,
			`management node name "Ethernet1" is also rendered by rule "linecard" (node_name "Ethernet{port}", {port} = 1); one name would mean two things`,
		}, false},
		{"mappings-missing", findings.RulePSPMappingsInvalid, nil, false},
		{"mappings-unknown-rule", findings.RulePSPMappingsInvalid, nil, false},
		// The other two causes of psp.mappings.invalid. Both are refused by the schema
		// as well, so the message is asserted among the rule's own findings.
		{"mappings-port-and-unmappable", findings.RulePSPMappingsInvalid, []string{
			`mapping 6 ("Ethernet99") declares both a port and unmappable: no_rule; a declaration is one or the other`,
		}, true},
		{"mappings-mapped-incomplete", findings.RulePSPMappingsInvalid, []string{
			`mapping 1 ("ethernet-1/1") is a mapped declaration without rule, node_name; it needs rule, port and node_name`,
		}, true},
		// A management rule's port or node name is literal, because the rule captures
		// nothing to substitute. The schema permits the value, so this rule is the
		// only thing that refuses it.
		{"management-port-placeholders", findings.RulePSPPatternsPlaceholders, []string{
			`rule "management": port "mgmt{slot}" uses {slot} but the management rule captures nothing; its port and node name are literal`,
		}, false},
		{"facet-missing", findings.RulePSPSchema, nil, false},
		{"version-unknown", findings.RulePSPVersionUnknown, nil, false},
		{"no-encoding", findings.RulePSPReadinessEncoding, nil, false},

		// Format 0.3's config block. Each fixture is the shipped
		// package with one field changed, so the rule under test is the only thing
		// the validator can be reacting to.
		{"config-artifact-name", findings.RulePSPConfigArtifactName, nil, false},
		// The contract names the rule for both triggers: the collision and the
		// pattern. The schema refuses the value too; the rule says what the name is for.
		{"config-artifact-name-pattern", findings.RulePSPConfigArtifactName, nil, false},
		{"config-content-type", findings.RulePSPConfigContentType, nil, false},
		{"config-delivery", findings.RulePSPConfigDeliveryUnimplemented, nil, false},
		{"config-push-missing", findings.RulePSPConfigPushMissing, nil, false},
		// Reworded by format 0.6: D-033's replace loads the baseline
		// into a candidate, which an implicit commit has none of.
		{"config-replace-implicit", findings.RulePSPConfigPushMissing, []string{
			"mode is replace with commit implicit; the reset loads the baseline into a candidate and commits it, which an implicit commit has none of, so no command list is defined for this pair",
		}, false},
		// mode is required with no default; the schema itself refuses its
		// absence, and no consistency rule needs to.
		{"config-mode-missing", findings.RulePSPSchema, nil, false},
		{"version-0-5", findings.RulePSPVersionUnknown, nil, false},
		// M5's shipped package as it was: 0.3's retired fields fail the strict decoder,
		// and the version is still named.
		{"version-0-3-m5", findings.RulePSPVersionUnknown, nil, false},

		// Format 0.5's additive fields (contracts/cli.md). Each
		// fixture is the shipped package with one change.
		//
		// bootstrap_via: push with mode replace was refused here until format 0.6, when
		// replace was M5's `delete /`; D-033's replace resets before the bootstrap is sent,
		// so the pair is the shipped EOS package's and its fixture is retired
		// (TestValidateRetiredClauseNoLongerFires). What is left of the rule is the
		// pairing that cannot mean anything: a delivery with no configuration lines to
		// send the bootstrap's through. The delivery rule fires beside it, so the
		// comparison is limited to this rule's own findings.
		{"bootstrap-via-no-lines", findings.RulePSPConfigBootstrapVia, []string{
			`bootstrap_via is push but delivery "netconf" carries no configuration lines; only json_rpc and eapi do`,
		}, true},
		// readiness.tls is a boolean and the schema is what refuses anything else; no
		// consistency rule needs to, as with mode above.
		{"tls-not-boolean", findings.RulePSPSchema, []string{
			"at '/readiness/tls': got string, want boolean",
		}, false},
		// eapi is the second implemented mechanism, so it needs a push block as
		// json_rpc does. The schema's conditional required refuses it too.
		{"eapi-without-push", findings.RulePSPConfigPushMissing, []string{
			"delivery is eapi but no push block says how to reach the node",
		}, true},

		// Format 0.6's one required field (contracts/cli.md). Each
		// fixture is the shipped package with one change, and the schema is what refuses
		// it, as with mode and tls above.
		{"fidelity-link-change-missing", findings.RulePSPSchema, []string{
			"at '/fidelity': missing property 'link_change'",
		}, false},
		{"fidelity-link-change-value", findings.RulePSPSchema, []string{
			"at '/fidelity/link_change': value must be one of 'restart', 'live'",
		}, false},
		// M10's shipped SR Linux package byte for byte (PSP 0.5, mode: merge, no link_change),
		// what an upgraded host still has in its override directory: refused by version,
		// beside the schema's finding for the field it lacks (M6's rule: a real old
		// package, never a synthetic one; TestM10ShippedPackageIsVersionUnknown).
		{"version-0-5-m10", findings.RulePSPVersionUnknown, []string{
			`package declares format version "0.5", this build understands "0.6"`,
		}, true},
	}
	for _, tc := range cases {
		t.Run(tc.fixture, func(t *testing.T) {
			path := repo("testdata", "psp", "defects", tc.fixture+".yaml")
			list := Validate([]string{path})
			if !list.Rejected() {
				t.Fatalf("expected a rejection, got %v", list)
			}
			if rulesIn(list)[tc.rule] == 0 {
				t.Errorf("expected rule %s, got %v", tc.rule, rulesIn(list))
			}
			if tc.messages != nil {
				var got []string
				for _, f := range list {
					if f.Rule != tc.rule {
						if !tc.messagesOfRule {
							t.Errorf("unexpected %s beside %s: %s", f.Rule, tc.rule, f.Message)
						}
						continue
					}
					got = append(got, f.Message)
				}
				if !slices.Equal(got, tc.messages) {
					t.Errorf("messages:\n got  %q\n want %q", got, tc.messages)
				}
			}
			for _, f := range list {
				if f.Location == nil || f.Location.File != path {
					t.Errorf("finding %s carries no file location", f.Rule)
				}
			}
		})
	}
}

// Implausible values are warnings, not rejections: a platform author may know
// something the validator does not, and a surprising package should not be unusable.
func TestImplausibleValuesAreWarnings(t *testing.T) {
	list := Validate([]string{repo("testdata", "psp", "defects", "implausible-resources.yaml")})
	rules := rulesIn(list)
	if rules[findings.RulePSPResourcesImplausible] == 0 || rules[findings.RulePSPReadinessImplausible] == 0 {
		t.Fatalf("expected implausibility warnings, got %v", rules)
	}
	for _, f := range list {
		if f.Rule == findings.RulePSPResourcesImplausible || f.Rule == findings.RulePSPReadinessImplausible {
			if f.Severity != findings.Warning {
				t.Errorf("%s has severity %s, want warning", f.Rule, f.Severity)
			}
		}
	}
}

// VM packaging is not a defect. It is a note, so the hardware virtualization
// requirement surfaces here rather than at deploy time on a host that lacks it.
func TestVMPackagingIsANoteNotADefect(t *testing.T) {
	list := Validate([]string{repo("testdata", "psp", "defects", "vrnetlab.yaml")})
	if list.Rejected() {
		t.Errorf("VM packaging must not be a rejection: %v", list)
	}
	var found bool
	for _, f := range list {
		if f.Rule == findings.RulePSPAcquisitionKVM {
			found = true
			if f.Severity != findings.Info {
				t.Errorf("severity = %s, want info", f.Severity)
			}
		}
	}
	if !found {
		t.Error("VM packaging produced no note at all")
	}
}

// All findings in one pass.
func TestAllDefectsReportedInOnePass(t *testing.T) {
	list := Validate([]string{repo("testdata", "psp", "defects", "several.yaml")})
	for _, want := range []string{
		findings.RulePSPPatternsPlaceholders,
		findings.RulePSPManagementCollides,
		findings.RulePSPVersionUnknown,
	} {
		if rulesIn(list)[want] == 0 {
			t.Errorf("rule %s missing from a single pass; got %v", want, rulesIn(list))
		}
	}
}

// Two packages claiming the same platform is a cross-file defect, which is why
// validation accepts a set of files rather than one at a time.
func TestDuplicateIdentityAcrossFiles(t *testing.T) {
	list := Validate([]string{
		repo("psp", "nokia_srlinux.yaml"),
		repo("testdata", "psp", "defects", "duplicate-identity.yaml"),
	})
	if rulesIn(list)[findings.RulePSPIdentityDuplicate] == 0 {
		t.Errorf("duplicate platform identity not reported: %v", list)
	}
	// Each file on its own is fine; only the pair is a problem.
	if Validate([]string{repo("testdata", "psp", "defects", "duplicate-identity.yaml")}).Rejected() {
		t.Error("a single copy should validate on its own")
	}
	// The fixture's whole purpose is to be the shipped package under another path. If it
	// drifts from the shipped file — as it did once, keeping a line the package had
	// dropped — the duplicate-identity test would still pass while asserting something
	// weaker than it claims.
	shipped, err := os.ReadFile(repo("psp", "nokia_srlinux.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	copied, err := os.ReadFile(repo("testdata", "psp", "defects", "duplicate-identity.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(shipped, copied) {
		t.Error("duplicate-identity.yaml must be byte-identical to psp/nokia_srlinux.yaml")
	}
}

// A package that was valid at the previous format is not valid at this one, and the
// message has to say so by version rather than as a missing field: "declares 0.5, this
// build understands 0.6" is what an operator can act on.
//
// version-0-5.yaml is the shipped package with its version line alone moved back, so
// every other field is present and the only thing the validator can object to is the
// version. That is what makes the "not as a missing field" assertion below mean
// something. It was version-0-3.yaml until M7 moved the format to 0.5, and
// version-0-4.yaml until M11 moved it to 0.6; the fixture is renamed with each bump,
// and its previous-version value is always one behind this build.
func TestPreviousFormatPackageIsVersionUnknown(t *testing.T) {
	path := repo("testdata", "psp", "defects", "version-0-5.yaml")
	shipped, err := os.ReadFile(repo("psp", "nokia_srlinux.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	fixture, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	want := bytes.Replace(shipped, []byte(`psp_version: "`+FormatVersion+`"`), []byte(`psp_version: "0.5"`), 1)
	if !bytes.Equal(fixture, want) {
		t.Error("version-0-5.yaml must be psp/nokia_srlinux.yaml with its version line alone changed; " +
			"otherwise this test reports a missing field as a version problem")
	}

	list := Validate([]string{path})
	if rulesIn(list)[findings.RulePSPVersionUnknown] == 0 {
		t.Fatalf("expected %s, got %v", findings.RulePSPVersionUnknown, list)
	}
	for _, f := range list {
		if f.Rule == findings.RulePSPVersionUnknown &&
			!bytes.Contains([]byte(f.Message), []byte(`declares format version "0.5", this build understands "0.6"`)) {
			t.Errorf("the message must name both versions, got %q", f.Message)
		}
		// The schema may also refuse the version value; it must not report a missing field.
		if f.Rule == findings.RulePSPSchema && f.Object != "/psp_version" {
			t.Errorf("a 0.5 package reported a schema finding beyond its version: %s %s", f.Object, f.Message)
		}
	}
}

// version-0-3-m5.yaml is M5's shipped SR Linux package byte for byte (PSP 0.3): what an
// upgraded host still has in its override
// directory. Unlike version-0-5.yaml it carries 0.3's retired interface fields, which the
// strict decoder refuses, so the version must be named even when the package does not
// decode. Before that was fixed it drew three psp.schema findings and no version. The
// schema's findings about the fields stand beside it.
func TestPreviousFormatShippedPackageIsVersionUnknown(t *testing.T) {
	path := repo("testdata", "psp", "defects", "version-0-3-m5.yaml")
	list := Validate([]string{path})
	var got []string
	for _, f := range list {
		if f.Rule == findings.RulePSPVersionUnknown {
			got = append(got, f.Object+": "+f.Message)
		}
	}
	want := []string{`nokia_srlinux: package declares format version "0.3", this build understands "0.6"`}
	if !slices.Equal(got, want) {
		t.Errorf("%s findings:\n got  %q\n want %q\nall: %v", findings.RulePSPVersionUnknown, got, want, list)
	}
}

// version-0-5-m10.yaml is M10's shipped SR Linux package byte for byte (PSP 0.5, mode:
// merge, no link_change), which an upgraded host may still hold in its override
// directory. It decodes, since format 0.6 retired no field, so what it lacks is said
// twice: by version, and by the schema for the one field 0.6 requires. Neither is
// allowed to hide the other.
func TestM10ShippedPackageIsVersionUnknown(t *testing.T) {
	path := repo("testdata", "psp", "defects", "version-0-5-m10.yaml")
	list := Validate([]string{path})
	var version, schema []string
	for _, f := range list {
		switch f.Rule {
		case findings.RulePSPVersionUnknown:
			version = append(version, f.Object+": "+f.Message)
		case findings.RulePSPSchema:
			schema = append(schema, f.Message)
		default:
			t.Errorf("unexpected %s: %s", f.Rule, f.Message)
		}
	}
	if want := []string{`nokia_srlinux: package declares format version "0.5", this build understands "0.6"`}; !slices.Equal(version, want) {
		t.Errorf("%s findings:\n got  %q\n want %q", findings.RulePSPVersionUnknown, version, want)
	}
	if !slices.Contains(schema, "at '/fidelity': missing property 'link_change'") {
		t.Errorf("%s findings %q do not name the missing fidelity.link_change", findings.RulePSPSchema, schema)
	}
	// The fixture is M10's package and not this build's: it is on merge, and has no
	// link_change at all, so it cannot have been regenerated from psp/ by mistake.
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(raw, []byte(`psp_version: "0.5"`)) || !bytes.Contains(raw, []byte("  mode: merge ")) ||
		bytes.Contains(raw, []byte("link_change")) {
		t.Error("version-0-5-m10.yaml must be M10's shipped SR Linux package byte for byte: PSP 0.5, mode: merge, no link_change")
	}
}

// Format 0.5 refused bootstrap_via: push beside mode: replace, because replace was then
// M5's `delete /` and would have removed the bootstrap the same request had just sent.
// D-033's replace resets to the baseline before the bootstrap is sent, so 0.6 retires the
// clause, and the shipped EOS package is exactly this pair. The
// package here is the shipped SR Linux one with bootstrap_via: push added, so the pair is
// the only thing that differs from a package that validates; the EOS package is checked
// beside it, so the clause cannot come back unnoticed for either.
func TestValidateRetiredClauseNoLongerFires(t *testing.T) {
	shipped, err := os.ReadFile(repo("psp", "nokia_srlinux.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	const anchor = "  mode: replace "
	if !bytes.Contains(shipped, []byte(anchor)) {
		t.Fatalf("the shipped SR Linux package no longer declares %q; this test needs a package on replace", anchor)
	}
	pkg := bytes.Replace(shipped, []byte(anchor), []byte("  bootstrap_via: push\n"+anchor), 1)
	path := filepath.Join(t.TempDir(), "nokia_srlinux.yaml")
	if err := os.WriteFile(path, pkg, 0o644); err != nil {
		t.Fatal(err)
	}
	p, err := ParseFile(path, OriginOverride)
	if err != nil {
		t.Fatalf("the package did not load: %v", err)
	}
	if p.Config.BootstrapVia != BootstrapViaPush || p.Config.Mode != ModeReplace {
		t.Fatalf("bootstrap_via/mode = %s/%s, want push/replace", p.Config.BootstrapVia, p.Config.Mode)
	}
	for _, check := range []string{path, repo("psp", "arista_eos.yaml")} {
		list := Validate([]string{check})
		for _, f := range list {
			if f.Rule == findings.RulePSPConfigBootstrapVia {
				t.Errorf("%s: %s fired on bootstrap_via push with mode replace: %s", filepath.Base(check), f.Rule, f.Message)
			}
		}
		if list.Rejected() {
			t.Errorf("%s: the pair must validate: %v", filepath.Base(check), list)
		}
	}
}

// The two consistency clauses format 0.6 keeps hold only of the pairs they name: the
// refusal of an implicit commit is replace's alone, since merge without a candidate has a
// command list, and the refusal of a delivery with no configuration lines is bootstrap_via
// push's alone, since a bootstrap written to the startup-config sends nothing through it.
// Each package here is one line away from a package of its tier-1 corpus.
func TestConsistencyClausesKeepTheirScope(t *testing.T) {
	// edited is the package at from with old replaced by new, once, written to a file of
	// its own.
	edited := func(t *testing.T, from, old, new string) string {
		t.Helper()
		raw, err := os.ReadFile(from)
		if err != nil {
			t.Fatal(err)
		}
		if !bytes.Contains(raw, []byte(old)) {
			t.Fatalf("%s no longer carries %q; this test edits that line", filepath.Base(from), old)
		}
		path := filepath.Join(t.TempDir(), filepath.Base(from))
		if err := os.WriteFile(path, bytes.Replace(raw, []byte(old), []byte(new), 1), 0o644); err != nil {
			t.Fatal(err)
		}
		return path
	}

	t.Run("merge with an implicit commit", func(t *testing.T) {
		path := edited(t, repo("testdata", "psp", "lossy", "chassisos.yaml"), "  commit: explicit", "  commit: implicit")
		p, err := ParseFile(path, OriginOverride)
		if err != nil {
			t.Fatalf("the package did not load: %v", err)
		}
		if p.Config.Mode != ModeMerge || p.Config.Commit != CommitImplicit {
			t.Fatalf("mode/commit = %s/%s, want merge/implicit", p.Config.Mode, p.Config.Commit)
		}
		if list := Validate([]string{path}); len(list) != 0 {
			t.Errorf("merge with commit implicit must validate clean, as the package does with commit explicit: %v", list)
		}
	})

	t.Run("a startup-config bootstrap beside a delivery with no lines", func(t *testing.T) {
		const anchor = "  mode: merge "
		path := edited(t, repo("testdata", "psp", "defects", "config-delivery.yaml"), anchor,
			"  bootstrap_via: "+BootstrapViaStartupConfig+"\n"+anchor)
		list := Validate([]string{path})
		rules := rulesIn(list)
		if rules[findings.RulePSPConfigDeliveryUnimplemented] != 1 {
			t.Errorf("findings %v, want the delivery refused once", list)
		}
		if n := rules[findings.RulePSPConfigBootstrapVia]; n != 0 {
			t.Errorf("%s fired %d times on bootstrap_via %s, which sends nothing through the delivery: %v",
				findings.RulePSPConfigBootstrapVia, n, BootstrapViaStartupConfig, list)
		}
	})
}

// The shipped package's 0.3 fields are the values M5 measured on a booted node, not
// whatever happens to be in the file: a budget or an artifact name that drifts silently
// is a twin configured from the wrong artifact, or a push cut short.
func TestShippedPackageCarriesTheMeasured03Values(t *testing.T) {
	p, err := ParseFile(repo("psp", "nokia_srlinux.yaml"), OriginEmbedded)
	if err != nil {
		t.Fatalf("the shipped SR Linux package did not load: %v", err)
	}
	c := p.Config
	if c.ArtifactName != "device-config" {
		t.Errorf("artifact_name = %q, want device-config (the definition srlinux_device_config renders under it)", c.ArtifactName)
	}
	if len(c.ArtifactContentTypes) != 1 || c.ArtifactContentTypes[0] != "text/plain" {
		t.Errorf("artifact_content_types = %v, want [text/plain] (the definition's content type)", c.ArtifactContentTypes)
	}
	if c.Mode != ModeReplace {
		t.Errorf("mode = %q, want replace: D-033's load startup, bootstrap, artifact, diff flat, commit now; M5's `delete /` replace, which took the probe node dark, is gone", c.Mode)
	}
	if p.Fidelity.LinkChange != LinkChangeLive {
		t.Errorf("link_change = %q, want live: a link change re-cables the node with no lifecycle action and its push is kept", p.Fidelity.LinkChange)
	}
	if c.PushTimeoutS != 30 {
		t.Errorf("push_timeout_s = %d, want 30 (0.70s measured, x40 for a stalled node)", c.PushTimeoutS)
	}
	if c.Push == nil {
		t.Fatal("the shipped package declares delivery json_rpc, so it must carry a push block")
	}
	if c.Push.Scheme != "https" || c.Push.Port != 443 {
		t.Errorf("push = %s:%d, want https:443 (containerlab enables the JSON-RPC server on both)", c.Push.Scheme, c.Push.Port)
	}
	// The push login may name the probe's variables, and here it does: one node, one
	// account. Names, never values (Constitution X).
	if c.Push.Login != p.Readiness.Login {
		t.Errorf("push login = %+v, readiness login = %+v; the shipped package reuses the probe's variables", c.Push.Login, p.Readiness.Login)
	}
}

// The shipped profile is the one a booted node bore out, not whatever happens to be in the
// file: the ranges are the ports the booted image has (slot 1, ports 1 to 58), and the versions are the ones a boot read.
// A drift here would omit a port the node has, or claim a version nothing verified.
func TestShippedProfileIsR2s(t *testing.T) {
	path := repo("psp", "nokia_srlinux.yaml")
	p, err := ParseFile(path, OriginEmbedded)
	if err != nil {
		t.Fatalf("the shipped SR Linux package did not load: %v", err)
	}
	want := []Rule{
		{Name: "ethernet", Match: "ethernet-{slot}/{port}", Ranges: map[string][2]int{"slot": {1, 1}, "port": {1, 58}},
			Port: "e{slot}-{port}", NodeName: "ethernet-{slot}/{port}"},
		{Name: "breakout", Match: "ethernet-{slot}/{port}/{sub}",
			Ranges: map[string][2]int{"slot": {1, 1}, "port": {1, 58}, "sub": {1, 4}},
			Port:   "e{slot}-{port}-{sub}", NodeName: "ethernet-{slot}/{port}/{sub}",
			Breakout: &Breakout{Parent: "ethernet-{slot}/{port}"}},
		{Name: "management", Management: true, Port: "mgmt0", NodeName: "mgmt0"},
	}
	if !reflect.DeepEqual(p.Interfaces.Rules, want) {
		t.Errorf("rules = %+v\nwant    %+v", p.Interfaces.Rules, want)
	}
	if !reflect.DeepEqual(p.Platform.Versions, []string{"24.7"}) {
		t.Errorf("versions = %v, want [24.7] (24.3 is booted by no image here)", p.Platform.Versions)
	}
	if p.Conformance == nil {
		t.Error("the shipped package declares no conformance block; its boot half could never pass")
	}
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(raw, []byte("# verify")) {
		t.Error("the shipped package still carries a `# verify` marker")
	}
}

// An artifact_name outside its pattern is refused under the rule the contract names,
// psp.config.artifact_name, not only by the schema (contracts/cli.md). The
// message names the value and the pattern, so a platform author can act on it.
//
// The pattern the rule matches is one string with the schema's, or the two would
// drift: a name the schema refuses that the rule accepts, or the reverse.
func TestArtifactNamePatternIsNamedAndMatchesTheSchema(t *testing.T) {
	schemaBytes, err := SchemaBytes()
	if err != nil {
		t.Fatal(err)
	}
	var schema struct {
		Properties struct {
			Config struct {
				Properties struct {
					ArtifactName struct {
						Pattern string `json:"pattern"`
					} `json:"artifact_name"`
				} `json:"properties"`
			} `json:"config"`
		} `json:"properties"`
	}
	if err := json.Unmarshal(schemaBytes, &schema); err != nil {
		t.Fatal(err)
	}
	if got := schema.Properties.Config.Properties.ArtifactName.Pattern; got != artifactNamePattern {
		t.Errorf("psp.schema.json's artifact_name pattern is %q, the rule matches %q; keep them one string", got, artifactNamePattern)
	}

	path := repo("testdata", "psp", "defects", "config-artifact-name-pattern.yaml")
	shipped, err := os.ReadFile(repo("psp", "nokia_srlinux.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	fixture, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	want := bytes.Replace(shipped, []byte(`artifact_name: device-config `), []byte(`artifact_name: "Device Config" `), 1)
	if !bytes.Equal(fixture, want) {
		t.Error("config-artifact-name-pattern.yaml must be psp/nokia_srlinux.yaml with its artifact_name alone changed")
	}

	list := Validate([]string{path})
	var named bool
	for _, f := range list {
		if f.Rule != findings.RulePSPConfigArtifactName {
			continue
		}
		named = true
		for _, part := range []string{`"Device Config"`, artifactNamePattern} {
			if !strings.Contains(f.Message, part) {
				t.Errorf("message %q does not name %s", f.Message, part)
			}
		}
		if f.Severity != findings.Rejection || f.Object != path {
			t.Errorf("finding %+v, want a rejection whose object is the package path", f)
		}
	}
	if !named {
		t.Errorf("expected %s, got %v", findings.RulePSPConfigArtifactName, rulesIn(list))
	}
}

// The synthetic packages the heterogeneous tests load must be valid in their own
// right, alone and together, or those tests would be exercising a refusal.
func TestHeterogeneousPackagesAreValid(t *testing.T) {
	list := Validate([]string{
		repo("testdata", "psp", "heterogeneous", "fastos.yaml"),
		repo("testdata", "psp", "heterogeneous", "slowos.yaml"),
	})
	if len(list) != 0 {
		t.Errorf("heterogeneous test packages must validate clean: %v", list)
	}
}

// The design-case package proves the format on a lossy platform Fylgja cannot boot: it
// must load clean, carry every kind of rule the format has, and never be one the binary
// ships.
func TestDesignCasePackageIsValid(t *testing.T) {
	path := repo("testdata", "psp", "lossy", "chassisos.yaml")
	if list := Validate([]string{path}); len(list) != 0 {
		t.Errorf("the design-case package must validate clean: %v", list)
	}
	p, err := ParseFile(path, OriginOverride)
	if err != nil {
		t.Fatal(err)
	}
	var got []string
	for _, r := range p.Interfaces.Rules {
		got = append(got, fmt.Sprintf("%s lossy=%t breakout=%t management=%t", r.Name, r.Lossy, r.Breakout != nil, r.Management))
	}
	want := []string{
		"front lossy=false breakout=false management=false",
		"linecard lossy=true breakout=false management=false",
		"breakout lossy=true breakout=true management=false",
		"management lossy=false breakout=false management=true",
	}
	if !slices.Equal(got, want) {
		t.Errorf("rules:\n%s\nwant:\n%s", strings.Join(got, "\n"), strings.Join(want, "\n"))
	}
	if p.Conformance != nil {
		t.Error("the design-case package declares a conformance block; it never boots, so the boot half has nothing to read")
	}
	shipped, err := Embedded()
	if err != nil {
		t.Fatal(err)
	}
	for _, s := range shipped {
		if s.Platform.ID == p.Platform.ID {
			t.Errorf("%s is embedded in the binary; the design-case package is test data only", s.Platform.ID)
		}
	}
}

func TestUnreadableFileIsReported(t *testing.T) {
	list := Validate([]string{repo("testdata", "psp", "defects", "no-such-file.yaml")})
	if !list.Rejected() {
		t.Error("a missing file must be reported")
	}
}

func TestNotAnObjectIsReported(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "list.yaml")
	if err := os.WriteFile(path, []byte("- one\n- two\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	list := Validate([]string{path})
	if !list.Rejected() {
		t.Error("a file that is not a single package object must be reported")
	}
}

// The shipped EOS package is what M7 measured on a booted node, not whatever
// happens to be in the file. Each value below was read from a booted cEOS node or timed
// against one, and a drift in any of them is a twin that boots wrong, never boots, or
// never takes its configuration: a range that omits a port the node has, a budget below
// what a deploy takes, a TLS dial the node's plaintext gRPC transport refuses, or a
// bootstrap named in the topology, which on this kind replaces the node's whole
// configuration and takes its management plane with it.
func TestShippedEOSPackageCarriesWhatTheResearchMeasured(t *testing.T) {
	p, err := ParseFile(repo("psp", "arista_eos.yaml"), OriginEmbedded)
	if err != nil {
		t.Fatalf("the shipped EOS package did not load: %v", err)
	}

	// Identity and image. account_gated is what makes the host check verify
	// the image is present rather than let a deploy try to pull it from a registry.
	if !reflect.DeepEqual(p.Platform.Versions, []string{"4.32"}) {
		t.Errorf("versions = %v, want [4.32] (what gNMI and `show version` read)", p.Platform.Versions)
	}
	if p.Platform.DeviceClass != ClassSwitch {
		t.Errorf("device_class = %q, want switch (modelName cEOSLab)", p.Platform.DeviceClass)
	}
	if p.Image.ClabKind != "ceos" || p.Image.Ref != "ceos:4.32.0.2F" {
		t.Errorf("image = %s / %s, want ceos / ceos:4.32.0.2F", p.Image.ClabKind, p.Image.Ref)
	}
	if p.Image.Acquisition != AcquisitionAccountGated {
		t.Errorf("acquisition = %q, want account_gated; the image is imported by hand and must never be pulled", p.Image.Acquisition)
	}
	if p.Image.Resources.MemoryMB != 1536 {
		t.Errorf("memory_mb = %d, want 1536 (889-1541 MiB measured over four labs)", p.Image.Resources.MemoryMB)
	}
	if p.Image.DeployTimeoutS != 300 || p.Image.DestroyTimeoutS != 60 {
		t.Errorf("deploy/destroy budgets = %d/%d, want 300/60 (95.5s and 2.08s measured)",
			p.Image.DeployTimeoutS, p.Image.DestroyTimeoutS)
	}

	// Readiness. tls must be an explicit false: nil means TLS, and this node's
	// gRPC transport carries no SSL profile, so a TLS dial never completes a handshake.
	if p.Readiness.Probe != ProbeGNMIGet || p.Readiness.Port != 6030 || p.Readiness.Encoding != "json_ietf" {
		t.Errorf("readiness = %s on %d, %s; want gnmi_get on 6030, json_ietf",
			p.Readiness.Probe, p.Readiness.Port, p.Readiness.Encoding)
	}
	if p.Readiness.TLS == nil || *p.Readiness.TLS {
		t.Error("readiness.tls must be an explicit false; the node's transport grpc default has no SSL profile and refuses a TLS handshake")
	}
	if p.Readiness.TimeoutS != 90 {
		t.Errorf("readiness timeout_s = %d, want 90 (9.3s measured after the deploy returned)", p.Readiness.TimeoutS)
	}
	if p.Readiness.Login.UsernameEnv != "FYLGJA_EOS_USERNAME" || p.Readiness.Login.PasswordEnv != "FYLGJA_EOS_PASSWORD" {
		t.Errorf("readiness login = %+v, want the FYLGJA_EOS_* pair, so one worker carries both platforms' logins", p.Readiness.Login)
	}

	// Config and bootstrap.
	c := p.Config
	if c.Delivery != DeliveryEAPI || c.Commit != CommitExplicit || c.Mode != ModeReplace {
		t.Errorf("delivery/commit/mode = %s/%s/%s, want eapi/explicit/replace; a session per attempt is the atomic one, reset to the baseline by D-033's pair",
			c.Delivery, c.Commit, c.Mode)
	}
	if p.Fidelity.LinkChange != LinkChangeRestart {
		t.Errorf("link_change = %q, want restart: a link change restarts the node in place and it returns on its startup configuration, its push lost", p.Fidelity.LinkChange)
	}
	if c.ArtifactName != "device-config" {
		t.Errorf("artifact_name = %q, want device-config (one definition renders EOS text for an eos device)", c.ArtifactName)
	}
	if c.PushTimeoutS != 30 {
		t.Errorf("push_timeout_s = %d, want 30 (0.63s measured for a fourteen-command request)", c.PushTimeoutS)
	}
	if c.Push == nil {
		t.Fatal("delivery is eapi, so the package must carry a push block")
	}
	if c.Push.Scheme != "https" || c.Push.Port != 443 {
		t.Errorf("push = %s:%d, want https:443; HTTP on 80 is shut", c.Push.Scheme, c.Push.Port)
	}
	if c.Push.Login != p.Readiness.Login {
		t.Errorf("push login = %+v, readiness login = %+v; one node, one account", c.Push.Login, p.Readiness.Login)
	}
	if c.BootstrapVia != BootstrapViaPush {
		t.Errorf("bootstrap_via = %q, want push; naming a startup-config in the topology replaces this kind's whole configuration, and the node loses its management plane", c.BootstrapVia)
	}
	// The header of the bootstrap file is sent to this node as a command, because the
	// bootstrap reaches it through the push, and this node reads `!` as a comment and
	// refuses `#` at token 0. A package that named no marker would mean `#`.
	if c.CommentPrefix != "!" {
		t.Errorf("comment_prefix = %q, want \"!\"; `#` is refused as a command on this platform", c.CommentPrefix)
	}
	if want := []string{"hostname {node}"}; !reflect.DeepEqual(c.Bootstrap, want) {
		t.Errorf("bootstrap = %q, want %q; every port is up and LLDP runs before Fylgja touches the node, so the hostname is the one line left to write", c.Bootstrap, want)
	}

	// The profile: one rule per name shape, none lossy, and each range a bound a
	// boot established.
	want := []Rule{
		{Name: "ethernet", Match: "Ethernet{port}", Ranges: map[string][2]int{"port": {1, 511}},
			Port: "eth{port}", NodeName: "Ethernet{port}"},
		{Name: "modular", Match: "Ethernet{slot}/{port}", Ranges: map[string][2]int{"slot": {1, 100}, "port": {1, 256}},
			Port: "eth{slot}_{port}", NodeName: "Ethernet{slot}/{port}"},
		{Name: "breakout", Match: "Ethernet{slot}/{port}/{sub}",
			Ranges: map[string][2]int{"slot": {1, 100}, "port": {1, 256}, "sub": {1, 64}},
			Port:   "eth{slot}_{port}_{sub}", NodeName: "Ethernet{slot}/{port}/{sub}",
			Breakout: &Breakout{Parent: "Ethernet{slot}/{port}"}},
		{Name: "management", Management: true, Port: "eth0", NodeName: "Management0"},
	}
	if !reflect.DeepEqual(p.Interfaces.Rules, want) {
		t.Errorf("rules = %+v\nwant    %+v", p.Interfaces.Rules, want)
	}

	// The facet the boot half reads by. The neighbour leaves are relative paths one
	// container below the entry, which is where this model puts them.
	if p.Conformance == nil {
		t.Fatal("the shipped EOS package declares no conformance block; its boot half could never pass")
	}
	n := p.Conformance.Port.Neighbor
	if n.SystemName != "state/system-name" || n.PortID != "state/port-id" {
		t.Errorf("neighbour leaves = %s / %s, want state/system-name / state/port-id", n.SystemName, n.PortID)
	}
	if got := p.Conformance.Port.Discovering.Absent; got != "true" {
		t.Errorf("discovering.absent = %q, want \"true\"; the leaf is not reported while LLDP runs, so nothing read is the default", got)
	}
}

// A package that asks readiness to wait for the push transport and declares no push is
// refused: there is no endpoint to wait on (D-029).
func TestAwaitPushTransportWithoutAPush(t *testing.T) {
	list := Validate([]string{repo("testdata", "psp", "defects", "readiness-await-push-no-push.yaml")})
	want := "support package arista_eos sets readiness.await_push_transport and declares no config.push: " +
		"there is no endpoint for readiness to wait on"
	var got []string
	for _, f := range list {
		if f.Rule == findings.RulePSPReadinessAwaitPushTransport {
			got = append(got, f.Message)
			if f.Severity != findings.Rejection {
				t.Errorf("finding %+v, want a rejection", f)
			}
		}
	}
	if len(got) != 1 || got[0] != want {
		t.Errorf("%s findings = %q, want exactly one:\n  %q", findings.RulePSPReadinessAwaitPushTransport, got, want)
	}
}

// fylgja serve validates the bytes a client sent, under the paths the operator gave (M13).
// So every defect fixture and both shipped packages give,
// from their bytes, exactly the list Validate gives from their files, alone and as one set.
func TestValidateFilesIsValidateOverTheBytes(t *testing.T) {
	shipped, err := filepath.Glob(repo("psp", "*.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	defects, err := filepath.Glob(repo("testdata", "psp", "defects", "*.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	paths := append(shipped, defects...)
	if len(shipped) < 2 || len(defects) == 0 {
		t.Fatalf("found %d shipped packages and %d defects; the test is reading the wrong place", len(shipped), len(defects))
	}
	files := make([]File, 0, len(paths))
	for _, path := range paths {
		data, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		files = append(files, File{Path: path, Data: data})
		got, want := settled(ValidateFiles([]File{{Path: path, Data: data}})), settled(Validate([]string{path}))
		if !reflect.DeepEqual(got, want) {
			t.Errorf("%s: ValidateFiles gives\n%v\nValidate gives\n%v", path, got, want)
		}
	}
	if got, want := settled(ValidateFiles(files)), settled(Validate(paths)); !reflect.DeepEqual(got, want) {
		t.Errorf("the whole set: ValidateFiles gives %d findings, Validate %d\n%v\n%v", len(got), len(want), got, want)
	}
}

// additionalProperties is the schema library's sentence for keys a package may not carry.
// It names them in map order, so Validate run twice over one file can word that finding two
// ways (M12's behaviour, seen while writing the test above).
var additionalProperties = regexp.MustCompile(`additional properties (.+) not allowed`)

// settled is the list with each additionalProperties sentence's names sorted, so two lists
// compare by what they say rather than by the order a map gave.
func settled(list findings.List) findings.List {
	out := make(findings.List, len(list))
	for i, f := range list {
		if m := additionalProperties.FindStringSubmatchIndex(f.Message); m != nil {
			names := strings.Split(f.Message[m[2]:m[3]], ", ")
			slices.Sort(names)
			f.Message = f.Message[:m[2]] + strings.Join(names, ", ") + f.Message[m[3]:]
		}
		out[i] = f
	}
	return out
}

// Two packages that claim one platform are refused as a set, named by the paths given and
// by nothing on disk: no file is at either path.
func TestValidateFilesNamesThePathsGiven(t *testing.T) {
	srl, err := os.ReadFile(repo("psp", "nokia_srlinux.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	first, second := filepath.Join("site", "one.yaml"), filepath.Join("site", "two.yaml")
	list := ValidateFiles([]File{{Path: first, Data: srl}, {Path: second, Data: srl}})
	if len(list) != 1 {
		t.Fatalf("want one finding, got %v", list)
	}
	f := list[0]
	if f.Rule != findings.RulePSPIdentityDuplicate || f.Location == nil || f.Location.File != second ||
		f.Message != fmt.Sprintf("platform %q is already declared by %s", "nokia_srlinux", first) {
		t.Errorf("want %s at %s naming %s, got %+v (location %+v)", findings.RulePSPIdentityDuplicate, second, first, f, f.Location)
	}
	if list := ValidateFiles([]File{{Path: first, Data: srl}}); len(list) != 0 {
		t.Errorf("one copy alone validates, got %v", list)
	}
}
