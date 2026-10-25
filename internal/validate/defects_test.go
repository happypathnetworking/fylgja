package validate

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// Every single-defect fixture, the rule it must produce, and the object that rule must
// name. An operator reading a report has to be able to go straight to the thing that
// is wrong, so naming the object is as much the contract as naming the rule.
//
// The table is exhaustive over testdata/ctm/defects/ except five.json, which carries
// five defects at once and belongs to TestAllDefectsReportedInOnePass, and
// version-1.json, a CTM "1" no rule here reads, which ctm.Unmarshal refuses
// (TestVersion1IsRefused). A fixture added to that directory without a row here fails
// TestEveryDefectFixtureIsCovered.
var singleDefects = []struct {
	fixture string
	rule    string
	object  string
}{
	{"device-duplicate.json", findings.RuleDeviceNameDuplicate, "n1"},
	{"devices-empty.json", findings.RuleDevicesEmpty, "fylgja-fixture"},
	{"link-one-endpoint.json", findings.RuleLinkEndpointsCount, "n1:ethernet-1/1|n2:ethernet-1/1"},
	{"link-same-device.json", findings.RuleLinkEndpointsSameDev, "n1:ethernet-1/1|n1:ethernet-1/2"},
	{"platform-unsupported.json", findings.RulePlatformUnsupported, "n2"},
	{"required-missing.json", findings.RuleRequiredMissing, "envelope.schema_hash"},

	// What the mapping profile cannot map. port-collision.json is
	// on the design-case platform; the others are SR Linux's.
	{"port-collision.json", findings.RuleInterfacePortCollision, "c1:eth1"},
	{"breakout-parent-cabled.json", findings.RuleInterfaceBreakoutParentCabled, "n1:ethernet-1/1"},
	{"rule-unmatched.json", findings.RuleInterfaceRuleUnmatched, "n1:Ethernet99"},
	{"unmappable-linked-range.json", findings.RuleUnmappableLinked, "n1:ethernet-1/59"},
	{"unmappable-linked-unmatched.json", findings.RuleUnmappableLinked, "n1:Ethernet99"},
}

// designCase names the fixtures whose devices are on the design-case platform, which is
// never embedded: they load testdata/psp/lossy/ beside the shipped packages, as
// --psp-dir would.
var designCase = map[string]bool{"port-collision.json": true}

// loadDefect loads a defect fixture with the registry it is meant for.
func loadDefect(t *testing.T, fixture string) (*ctm.CTM, *psp.Registry) {
	t.Helper()
	if designCase[fixture] {
		return loadWith(t, "defects/"+fixture, filepath.Join("..", "..", "testdata", "psp", "lossy"))
	}
	return load(t, "defects/"+fixture)
}

func TestSingleDefectFixtures(t *testing.T) {
	for _, tc := range singleDefects {
		t.Run(tc.fixture, func(t *testing.T) {
			c, reg := loadDefect(t, tc.fixture)
			list := Validate(c, reg)
			if !list.Rejected() {
				t.Fatalf("expected a rejection, got %v", list)
			}

			var matched bool
			for _, f := range list {
				if f.Rule != tc.rule {
					continue
				}
				if f.Object == tc.object || strings.HasPrefix(f.Object, tc.object+"@") {
					matched = true
				}
			}
			if !matched {
				t.Errorf("expected %s naming %q; got %v", tc.rule, tc.object, list)
			}

			// Every finding names something and says something, whichever rule fired.
			for _, f := range list {
				if f.Object == "" {
					t.Errorf("finding %s names no object", f.Rule)
				}
				if f.Message == "" {
					t.Errorf("finding %s on %s gives no message", f.Rule, f.Object)
				}
			}
		})
	}
}

// A defect fixture with no row above would be a file nobody asserts anything about.
func TestEveryDefectFixtureIsCovered(t *testing.T) {
	covered := map[string]bool{
		"five.json":      true, // covered by TestAllDefectsReportedInOnePass
		"version-1.json": true, // covered by internal/ctm's TestVersion1IsRefused
	}
	for _, tc := range singleDefects {
		covered[tc.fixture] = true
	}
	entries, err := os.ReadDir(filepath.Join("..", "..", "testdata", "ctm", "defects"))
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".json") {
			continue
		}
		if !covered[e.Name()] {
			t.Errorf("testdata/ctm/defects/%s has no row in singleDefects: "+
				"a defect fixture nothing asserts on is a fixture that has stopped testing anything", e.Name())
		}
	}
}

// An unmappable production name splits by why it is unmappable. A
// name a rule matched out of range names a port the node does not have: with no link
// there is nothing to lose and the compiler records an omission; with one, the twin
// would silently lose a connection, so it is refused. A name no rule matches is refused
// linked or not: the profile has a gap or intent has a mistake, and omitting it would
// guess which. The split is asserted rather than assumed, because getting it wrong gives
// a twin that looks right and is wired differently from the network.
func TestUnmappableNameSplitsByCause(t *testing.T) {
	has := func(list findings.List, rule, object string) bool {
		for _, f := range list {
			if f.Rule == rule && f.Object == object {
				return true
			}
		}
		return false
	}

	t.Run("out of range and linked is a rejection", func(t *testing.T) {
		c, reg := load(t, "defects/unmappable-linked-range.json")
		if list := Validate(c, reg); !has(list, findings.RuleUnmappableLinked, "n1:ethernet-1/59") {
			t.Errorf("want %s naming n1:ethernet-1/59; got %v", findings.RuleUnmappableLinked, list)
		}
	})

	t.Run("out of range and unlinked is not", func(t *testing.T) {
		c, reg := load(t, "defects/unmappable-linked-range.json")
		// Unplug the link: the name is still matched out of range, and nothing is lost.
		c.Links = nil
		for i := range c.Devices {
			for j := range c.Devices[i].Interfaces {
				c.Devices[i].Interfaces[j].Link = ""
			}
		}
		if list := Validate(c, reg); list.Rejected() {
			t.Errorf("an unlinked out-of-range name must not reject; the compiler records it: %v", list)
		}
	})

	t.Run("no rule and linked is a rejection", func(t *testing.T) {
		c, reg := load(t, "defects/unmappable-linked-unmatched.json")
		if list := Validate(c, reg); !has(list, findings.RuleUnmappableLinked, "n1:Ethernet99") {
			t.Errorf("want %s naming n1:Ethernet99; got %v", findings.RuleUnmappableLinked, list)
		}
	})

	t.Run("no rule and unlinked is a rejection too", func(t *testing.T) {
		c, reg := load(t, "defects/rule-unmatched.json")
		if in := c.Device("n1").Interface("Ethernet99"); in == nil || in.Link != "" {
			t.Fatal("rule-unmatched.json is meant to hold an unlinked n1:Ethernet99")
		}
		list := Validate(c, reg)
		if !has(list, findings.RuleInterfaceRuleUnmatched, "n1:Ethernet99") {
			t.Errorf("want %s naming n1:Ethernet99; got %v", findings.RuleInterfaceRuleUnmatched, list)
		}
		if has(list, findings.RuleUnmappableLinked, "n1:Ethernet99") {
			t.Errorf("an unlinked name was called linked: %v", list)
		}
	})
}
