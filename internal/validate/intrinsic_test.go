package validate

import (
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

// The rules that read no package refuse each defect fixture of theirs under the rule and
// object Validate gives it, and refuse none of the fixtures whose fault needs a package:
// the server files such a file, then the compile refuses it, as a read's take is filed
// (018, T082).
func TestIntrinsicRefusesWhatNeedsNoPackage(t *testing.T) {
	intrinsic := map[string]bool{
		"device-duplicate.json":  true,
		"devices-empty.json":     true,
		"link-one-endpoint.json": true,
		"link-same-device.json":  true,
		"required-missing.json":  true,
	}
	for _, tc := range singleDefects {
		t.Run(tc.fixture, func(t *testing.T) {
			c, _ := loadDefect(t, tc.fixture)
			list := Intrinsic(c)
			if !intrinsic[tc.fixture] {
				if list.Rejected() {
					t.Errorf("Intrinsic refused a fault that needs the packages: %v", list)
				}
				return
			}
			var matched bool
			for _, f := range list {
				if f.Rule == tc.rule && (f.Object == tc.object || f.Object == tc.object+"@"+c.Envelope.At) {
					matched = true
				}
			}
			if !matched {
				t.Errorf("expected %s naming %q; got %v", tc.rule, tc.object, list)
			}
		})
	}
	for _, name := range []string{"three-node.json", "lossy.json", "mixed.json"} {
		c, _ := load(t, name)
		if list := Intrinsic(c); list.Rejected() {
			t.Errorf("%s: Intrinsic refused a fixture that compiles: %v", name, list)
		}
	}
}

// Every rejection Intrinsic makes is a finding Validate makes of the same CTM, word for
// word and in Validate's order, so a file refused before it is filed reads as the compile
// would have refused it.
func TestIntrinsicIsValidatesOwnWords(t *testing.T) {
	for _, fixture := range append([]string{"five.json"}, fixtures(singleDefects)...) {
		t.Run(fixture, func(t *testing.T) {
			c, reg := loadDefect(t, fixture)
			full := Validate(c, nil, reg, nil)
			i := 0
			for _, f := range Intrinsic(c) {
				if f.Severity != findings.Rejection {
					continue
				}
				for i < len(full) && full[i] != f {
					i++
				}
				if i == len(full) {
					t.Errorf("Intrinsic's %+v is not among Validate's findings, in order: %v", f, full)
					return
				}
				i++
			}
		})
	}
}

// A nameless interface is refused on a device whose package the registry lacks too, where
// Validate names the platform alone: the CTM's fault, whatever the platform.
func TestIntrinsicNamesANamelessInterfaceOnAnyPlatform(t *testing.T) {
	c, reg := load(t, "three-node.json")
	d := &c.Devices[0]
	d.Platform.Package = "no_such_package"
	// An interface no link names, so the name's absence is the one fault.
	unlinked := -1
	for i, in := range d.Interfaces {
		if in.Link == "" {
			unlinked = i
		}
	}
	if unlinked < 0 {
		t.Fatalf("%s has no interface without a link", d.Name)
	}
	d.Interfaces[unlinked].Name = ""

	want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleRequiredMissing, Object: d.Name,
		Message: "an interface has no name"}
	list := Intrinsic(c)
	if len(list) != 1 || list[0] != want {
		t.Errorf("Intrinsic = %v; want only %+v", list, want)
	}
	for _, f := range Validate(c, nil, reg, nil) {
		if f == want {
			t.Errorf("Validate named the interface on a device whose package it lacks: %v", f)
		}
	}
}

func fixtures(rows []struct {
	fixture string
	rule    string
	object  string
}) []string {
	var out []string
	for _, r := range rows {
		out = append(out, r.fixture)
	}
	return out
}
