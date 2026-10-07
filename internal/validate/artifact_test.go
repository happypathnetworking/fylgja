package validate

import (
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// fixtureWithout returns the reference fixture with one device's artifact removed, which
// is the shape of a CTM written before M5 or by a read that did not fetch one.
func fixtureWithout(t *testing.T, device string) (*ctm.CTM, *psp.Registry) {
	t.Helper()
	c, reg := load(t, "three-node.json")
	for i := range c.Devices {
		if c.Devices[i].Name == device {
			c.Devices[i].Artifact = nil
			return c, reg
		}
	}
	t.Fatalf("the fixture has no device %q", device)
	return nil, nil
}

// A device that carries no configuration cannot become a node that runs production's,
// and the twin would boot on bootstrap alone without saying so. The refusal names the
// device, so an operator reading it knows whether to read again or to look at Infrahub.
func TestArtifactMissingIsRejected(t *testing.T) {
	c, reg := fixtureWithout(t, "n2")
	list := Validate(c, reg)

	found := onlyFinding(t, list, findings.RuleArtifactMissing)
	if found.Object != "n2" {
		t.Errorf("finding names %q, want the device without an artifact (n2)", found.Object)
	}
	if !strings.Contains(found.Message, "n2") {
		t.Errorf("message does not name the device: %s", found.Message)
	}
	if !list.Rejected() {
		t.Error("a device with no configuration artifact must be a rejection")
	}
}

// Every device without one is named, not the first: an operator fixing a branch sees the
// whole list (Constitution III).
func TestEveryDeviceWithoutAnArtifactIsNamed(t *testing.T) {
	c, reg := load(t, "three-node.json")
	for i := range c.Devices {
		c.Devices[i].Artifact = nil
	}
	var named []string
	for _, f := range Validate(c, reg) {
		if f.Rule == findings.RuleArtifactMissing {
			named = append(named, f.Object)
		}
	}
	if strings.Join(named, ",") != "n1,n2,n3" {
		t.Errorf("named %v, want every device once, in name order", named)
	}
}

// fixtureRenamed returns the reference fixture with one device's artifact renamed, its
// content and checksum untouched: a CTM edited by hand, or written by something other
// than the read, which always carries the package's name.
func fixtureRenamed(t *testing.T, device, name string) (*ctm.CTM, *psp.Registry) {
	t.Helper()
	c, reg := load(t, "three-node.json")
	for i := range c.Devices {
		if c.Devices[i].Name == device {
			c.Devices[i].Artifact.Name = name
			return c, reg
		}
	}
	t.Fatalf("the fixture has no device %q", device)
	return nil, nil
}

// An artifact is a device's configuration only under the name its package gives it, and
// its name becomes a file name in the bundle. Named as the package's startup_format
// (`cli`), it would be written over the node's bootstrap, which is the node's
// startup-config, and the node would boot on intent-derived content (Constitution IV).
// The device has no artifact of the package's name, so it is artifact.missing,
// naming both names; its checksum, which is valid, is not a second
// finding.
func TestAnArtifactNotNamedAsItsPackageNamesItIsMissing(t *testing.T) {
	for _, name := range []string{"cli", "running-config"} {
		t.Run(name, func(t *testing.T) {
			c, reg := fixtureRenamed(t, "n1", name)
			list := Validate(c, reg)

			found := onlyFinding(t, list, findings.RuleArtifactMissing)
			if found.Object != "n1" {
				t.Errorf("finding names %q, want the device whose artifact is misnamed (n1)", found.Object)
			}
			for _, want := range []string{`"n1"`, `"` + name + `"`, `"device-config"`, "nokia_srlinux"} {
				if !strings.Contains(found.Message, want) {
					t.Errorf("message does not name %s: %s", want, found.Message)
				}
			}
			if len(list) != 1 {
				t.Errorf("want the one finding, got %v", list)
			}
		})
	}
}

// The content is what the twin will run, so a checksum that does not describe it means
// the file was edited after it was read, or arrived corrupt. Which is not for Fylgja to
// say, so both values are named and neither is blamed.
func TestChecksumMismatchIsRejected(t *testing.T) {
	c, reg := load(t, "three-node.json")
	recorded := c.Devices[0].Artifact.Checksum
	c.Devices[0].Artifact.Content += "set / system name host-name intruder\n"
	actual := ctm.ChecksumOf(c.Devices[0].Artifact.Content)

	found := onlyFinding(t, Validate(c, reg), findings.RuleArtifactChecksumMismatch)
	if found.Object != "n1" {
		t.Errorf("finding names %q, want n1", found.Object)
	}
	for _, want := range []string{actual, recorded} {
		if !strings.Contains(found.Message, want) {
			t.Errorf("message does not name %s: %s", want, found.Message)
		}
	}
	// The content is configuration, and a finding is printed, logged and pasted into
	// issues. Not one byte of it belongs there (Constitution X).
	if strings.Contains(found.Message, "host-name intruder") {
		t.Errorf("the artifact's content leaked into the finding: %s", found.Message)
	}
}

// Every rejection the compiler can raise is mirrored here, and the two must be
// indistinguishable: an operator must not be able to tell from the message whether
// `intent read` or `twin compile` produced it. M1 settled this for ctm.devices.empty,
// and for fidelity.forwarding.mixed until bundle "3" retired it; the artifact rules
// join them.
//
// The two are separate copies of the wording on purpose — internal/validate imports
// internal/compiler, so nothing can be shared in that direction — which is exactly why
// this test exists.
func TestCompilerAndValidationWordTheArtifactRulesIdentically(t *testing.T) {
	for _, tc := range []struct {
		name string
		rule string
		make func(t *testing.T) (*ctm.CTM, *psp.Registry)
	}{
		{"a device with no artifact", findings.RuleArtifactMissing, func(t *testing.T) (*ctm.CTM, *psp.Registry) {
			return fixtureWithout(t, "n1")
		}},
		{"an artifact not named as its package names it", findings.RuleArtifactMissing,
			func(t *testing.T) (*ctm.CTM, *psp.Registry) {
				return fixtureRenamed(t, "n1", "cli")
			}},
		{"content that is not what its checksum says", findings.RuleArtifactChecksumMismatch,
			func(t *testing.T) (*ctm.CTM, *psp.Registry) {
				c, reg := load(t, "three-node.json")
				c.Devices[0].Artifact.Content += "# edited by hand\n"
				return c, reg
			}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			c, reg := tc.make(t)
			validated := onlyFinding(t, Validate(c, reg), tc.rule)

			// The compiler runs on its own copy, since Compile normalizes in place.
			compiled, regForCompile := tc.make(t)
			_, list := compiler.Compile(compiled, regForCompile)
			guard := onlyFinding(t, list, tc.rule)

			if guard.Message != validated.Message {
				t.Errorf("the compiler and validation disagree about %s:\n  compiler:   %s\n  validation: %s",
					tc.rule, guard.Message, validated.Message)
			}
			if guard.Object != validated.Object || guard.Severity != validated.Severity {
				t.Errorf("the compiler says %s/%s, validation says %s/%s",
					guard.Severity, guard.Object, validated.Severity, validated.Object)
			}
		})
	}
}

// onlyFinding returns the one finding of a rule, failing when there is none or more than
// one. "More than one" matters as much as "none": one fault must name a device once.
func onlyFinding(t *testing.T, list findings.List, rule string) findings.Finding {
	t.Helper()
	var found []findings.Finding
	for _, f := range list {
		if f.Rule == rule {
			found = append(found, f)
		}
	}
	switch len(found) {
	case 0:
		t.Fatalf("no %s finding in %v", rule, list)
	case 1:
		return found[0]
	}
	t.Fatalf("%d %s findings, want one: %v", len(found), rule, found)
	return findings.Finding{}
}

// A device whose platform no package covers carries no artifact — the read selects one by
// the package's artifact_name, and there is no package — and is named once, under
// platform.unsupported, by validation as by the compiler, which reaches its artifact guards
// only with the device's package in hand. Found by tier 2's seeded defects: validation
// named d3 artifact.missing as well, one fault said twice.
func TestAnUnsupportedPlatformIsNotAlsoArtifactMissing(t *testing.T) {
	c, reg := fixtureWithout(t, "n2")
	for i := range c.Devices {
		if c.Devices[i].Name == "n2" {
			c.Devices[i].Platform.NOS = "acme_os"
		}
	}
	for label, list := range map[string]findings.List{
		"validation": Validate(c, reg),
		"compiler":   compileFindings(c, reg),
	} {
		var named []string
		for _, f := range list {
			if f.Object == "n2" {
				named = append(named, f.Rule)
			}
		}
		if len(named) != 1 || named[0] != findings.RulePlatformUnsupported {
			t.Errorf("%s names n2 under %v, want %s alone", label, named, findings.RulePlatformUnsupported)
		}
	}
}

// compileFindings is what the compiler refuses c with, validation skipped.
func compileFindings(c *ctm.CTM, reg *psp.Registry) findings.List {
	_, list := compiler.Compile(c, reg)
	return list
}
