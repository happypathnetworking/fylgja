package conformance

import (
	"os"
	"path/filepath"
	"reflect"
	"slices"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/psp"
)

// repo resolves a path from the module root to one this test can open: `go test` runs
// in internal/conformance, and the embedded registry's paths (psp/nokia_srlinux.yaml)
// are the module root's, unreadable from here.
func repo(parts ...string) string {
	abs, err := filepath.Abs(filepath.Join(append([]string{"..", ".."}, parts...)...))
	if err != nil {
		panic(err)
	}
	return abs
}

// packagesMeantToLoad reads, from disk, every package the tree means to load: the
// shipped ones, the heterogeneous test packages and the design-case package. Never the
// defect fixtures: they keep TestDefectsAreNamed, each failing under its named rule.
func packagesMeantToLoad(t *testing.T) []*psp.PSP {
	t.Helper()
	var out []*psp.PSP
	for _, glob := range []struct{ dir, origin string }{
		{"psp", psp.OriginEmbedded},
		{filepath.Join("testdata", "psp", "heterogeneous"), psp.OriginOverride},
		{filepath.Join("testdata", "psp", "lossy"), psp.OriginOverride},
	} {
		paths, err := filepath.Glob(filepath.Join(repo(glob.dir), "*.yaml"))
		if err != nil {
			t.Fatal(err)
		}
		for _, path := range paths {
			p, err := psp.ParseFile(path, glob.origin)
			if err != nil {
				t.Fatalf("%s: %v", path, err)
			}
			out = append(out, p)
		}
	}
	return out
}

// The pure half passes on every package meant to load, one subtest per package
// per check, each failure named by package, check and both values.
func TestPureHalf(t *testing.T) {
	pkgs := packagesMeantToLoad(t)
	// An emptied glob must not pass: the shipped package, fastos, slowos and chassisos.
	if len(pkgs) < 4 {
		t.Fatalf("found %d packages meant to load, want at least 4; the pure half would prove nothing", len(pkgs))
	}

	// The pure half checks what the binary ships: the shipped files read here are the
	// packages the embedded registry carries.
	embedded, err := psp.Embedded()
	if err != nil {
		t.Fatal(err)
	}
	for _, e := range embedded {
		i := slices.IndexFunc(pkgs, func(p *psp.PSP) bool { return p.Path == repo(e.Path) })
		if i < 0 {
			t.Errorf("embedded package %s was not read from disk", e.Path)
			continue
		}
		disk := *pkgs[i]
		disk.Path = e.Path
		if !reflect.DeepEqual(&disk, e) {
			t.Errorf("%s on disk differs from the package the binary embeds", e.Path)
		}
	}

	for _, p := range pkgs {
		report := Pure(p)
		t.Run(p.Platform.ID, func(t *testing.T) {
			for _, note := range report.Notes {
				t.Log(note)
			}
			for _, check := range PureChecks {
				t.Run(check, func(t *testing.T) {
					for _, f := range report.Of(check) {
						t.Error(f.String())
					}
				})
			}
		})
	}
}

// shippedCopy writes the shipped package with some text replaced to a file of its own,
// so every check, validation included, reads what the test changed.
func shippedCopy(t *testing.T, replace ...string) *psp.PSP {
	t.Helper()
	return editedCopy(t, repo("psp", "nokia_srlinux.yaml"), replace...)
}

// chassisCopy is shippedCopy for the design-case package.
func chassisCopy(t *testing.T, replace ...string) *psp.PSP {
	t.Helper()
	return editedCopy(t, repo("testdata", "psp", "lossy", "chassisos.yaml"), replace...)
}

// editedCopy writes the package at src with each pair of replace's texts replaced, the
// first occurrence of each, to a file of the same name of its own, and loads it.
func editedCopy(t *testing.T, src string, replace ...string) *psp.PSP {
	t.Helper()
	b, err := os.ReadFile(src)
	if err != nil {
		t.Fatal(err)
	}
	text := string(b)
	for i := 0; i < len(replace); i += 2 {
		if !strings.Contains(text, replace[i]) {
			t.Fatalf("%s no longer holds %q", src, replace[i])
		}
		text = strings.Replace(text, replace[i], replace[i+1], 1)
	}
	path := filepath.Join(t.TempDir(), filepath.Base(src))
	if err := os.WriteFile(path, []byte(text), 0o644); err != nil {
		t.Fatal(err)
	}
	p, err := psp.ParseFile(path, psp.OriginOverride)
	if err != nil {
		t.Fatal(err)
	}
	return p
}

// A package that disagrees with itself fails naming the package, the check and both
// values, every failure in one run: a declaration naming the wrong port; a
// non-lossy rule whose port pattern cannot be parsed back (its placeholders abut, so
// e1-149 parses as {sub}=14, {port}=9); and a bootstrap line with a placeholder nothing
// renders. The wrong port fails the round trip as well, since the inverse is taken from
// the declared port, and that failure is true too.
func TestPureHalfNamesADisagreement(t *testing.T) {
	p := shippedCopy(t,
		"{ production: ethernet-1/1, rule: ethernet, port: e1-1,", "{ production: ethernet-1/1, rule: ethernet, port: e1-9,",
		`port: "e{slot}-{port}-{sub}"`, `port: "e{slot}-{sub}{port}"`,
		"port: e1-49-1,", "port: e1-149,",
		`    - "set / system lldp admin-state enable"`, `    - "set / system lldp admin-state enable"`+"\n"+`    - "set / interface {interface} description {bogus}"`,
	)
	report := Pure(p)
	var got []string
	for _, f := range report.Failures {
		got = append(got, f.String())
	}
	prefix := "package nokia_srlinux (" + p.Path + "): "
	want := []string{
		prefix + "declared_mapping: ethernet-1/1: declared rule ethernet, port e1-9, node name ethernet-1/1, lossy false, produced rule ethernet, port e1-1, node name ethernet-1/1, lossy false",
		prefix + "round_trip: ethernet-1/1: declared production ethernet-1/1, produced inverse of port e1-9 under rule ethernet: ethernet-1/9",
		prefix + "round_trip: ethernet-1/49/1: declared production ethernet-1/49/1, produced inverse of port e1-149 under rule breakout: ethernet-1/9/14",
		prefix + `bootstrap_renders: ethernet-1/1: declared line "set / interface {interface} description {bogus}", produced "set / interface ethernet-1/1 description {bogus}", a placeholder left unrendered`,
	}
	if !slices.Equal(got, want) {
		t.Errorf("failures:\n got  %s\n want %s", strings.Join(got, "\n      "), strings.Join(want, "\n      "))
	}
}

// The declarations a profile does not bear out, each worded as the pure half words it,
// every failure of a package from one run. On the shipped package:
// an unmappable declaration whose outcome is the other one (no_rule for a name the
// ethernet rule matches out of range), one declared out of range that the rule maps, and
// a declared port its rule's port pattern cannot parse back. On the design case: a lossy
// declaration whose port its rule does not render from its production name, so the set
// the port inverts to does not hold that name. The port edits fail declared_mapping as
// well, and those failures are true too.
func TestPureHalfNamesWhatTheProfileDoesNotBearOut(t *testing.T) {
	for _, c := range []struct {
		name string
		p    *psp.PSP
		want []string
	}{
		{name: "nokia_srlinux", p: shippedCopy(t,
			"{ production: ethernet-1/1, rule: ethernet, port: e1-1, node_name: ethernet-1/1 }", "{ production: ethernet-1/1, rule: ethernet, unmappable: out_of_range }",
			"{ production: ethernet-1/58, rule: ethernet, port: e1-58,", "{ production: ethernet-1/58, rule: ethernet, port: ethernet-1/58,",
			"{ production: ethernet-1/59, rule: ethernet, unmappable: out_of_range }", "{ production: ethernet-1/59, unmappable: no_rule }",
		), want: []string{
			"declared_mapping: ethernet-1/1: declared out_of_range under rule ethernet, produced rule ethernet, port e1-1, node name ethernet-1/1, lossy false",
			"declared_mapping: ethernet-1/58: declared rule ethernet, port ethernet-1/58, node name ethernet-1/58, lossy false, produced rule ethernet, port e1-58, node name ethernet-1/58, lossy false",
			`round_trip: ethernet-1/58: declared production ethernet-1/58, produced inverse of port ethernet-1/58 under rule ethernet: nothing; the port does not parse under "e{slot}-{port}"`,
			"declared_mapping: ethernet-1/59: declared no_rule, produced out_of_range under rule ethernet",
		}},
		{name: "chassisos", p: chassisCopy(t,
			"{ production: Ethernet2/1, rule: linecard, port: eth1,", "{ production: Ethernet2/1, rule: linecard, port: eth2,",
		), want: []string{
			"declared_mapping: Ethernet2/1: declared rule linecard, port eth2, node name Ethernet1, lossy true, produced rule linecard, port eth1, node name Ethernet1, lossy true",
			"round_trip: Ethernet2/1: declared production Ethernet2/1, produced inverse of port eth2 under rule linecard: a set that does not contain it",
		}},
	} {
		t.Run(c.name, func(t *testing.T) {
			var got []string
			for _, f := range Pure(c.p).Failures {
				got = append(got, f.String())
			}
			prefix := "package " + c.name + " (" + c.p.Path + "): "
			var want []string
			for _, w := range c.want {
				want = append(want, prefix+w)
			}
			if !slices.Equal(got, want) {
				t.Errorf("failures:\n got  %s\n want %s", strings.Join(got, "\n      "), strings.Join(want, "\n      "))
			}
		})
	}
}

// A package whose file cannot be read fails validates naming the path; it is never
// skipped. The embedded registry's own paths are the module root's, and fail so from
// here, which is why TestPureHalf reads the files from disk.
func TestPureHalfFailsAPackageItCannotRead(t *testing.T) {
	embedded, err := psp.Embedded()
	if err != nil {
		t.Fatal(err)
	}
	for _, p := range []*psp.PSP{embedded[0], {Platform: embedded[0].Platform, Interfaces: embedded[0].Interfaces}} {
		fails := Pure(p).Of(CheckValidates)
		if len(fails) != 1 || !strings.Contains(fails[0].Produced, "nothing:") {
			t.Errorf("path %q: validates failures %v, want one naming why nothing was read", p.Path, fails)
		}
	}
}

// validates is `psp validate` on the file: a rejection there is a failure naming the rule.
func TestPureHalfValidatesTheFile(t *testing.T) {
	p := shippedCopy(t, "- name: breakout", "- name: ethernet")
	fails := Pure(p).Of(CheckValidates)
	const want = `psp.rule.name: rules 1 and 2 are both named "ethernet"; names are unique in the profile`
	if len(fails) != 1 || !strings.Contains(fails[0].Produced, want) {
		t.Errorf("validates failures %v, want one naming %s", fails, want)
	}
}

// link_change is stated, and is one of the two values format 0.6 knows. Both shipped
// packages pass, each with the value measured on its booted node; a copy
// with the field removed and one declaring a third value each fail naming the package,
// the check and both values. Validation refuses both copies as well, so the assertion is
// on this check's failures alone.
func TestPureHalfLinkChange(t *testing.T) {
	for file, want := range map[string]string{"nokia_srlinux.yaml": psp.LinkChangeLive, "arista_eos.yaml": psp.LinkChangeRestart} {
		p, err := psp.ParseFile(repo("psp", file), psp.OriginEmbedded)
		if err != nil {
			t.Fatal(err)
		}
		if p.Fidelity.LinkChange != want {
			t.Errorf("%s declares link_change %q, want %q", file, p.Fidelity.LinkChange, want)
		}
		if fails := Pure(p).Of(CheckLinkChange); len(fails) != 0 {
			t.Errorf("%s fails link_change: %v", file, fails)
		}
	}

	const line = "  link_change: live                   # a link added or removed is re-cabled with no lifecycle action and the push is kept; a changed .cli is not applied, which the replace's bootstrap covers\n"
	for _, tc := range []struct {
		name, replacement, declared string
	}{
		{"missing", "", "nothing"},
		{"reboot", "  link_change: reboot\n", "reboot"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			p := shippedCopy(t, line, tc.replacement)
			fails := Pure(p).Of(CheckLinkChange)
			want := "package nokia_srlinux (" + p.Path + "): link_change: declared " + tc.declared +
				", produced not one of restart, live"
			if len(fails) != 1 || fails[0].String() != want {
				t.Errorf("link_change failures %v, want exactly:\n  %s", fails, want)
			}
		})
	}
}

// Information, never failures: a declared name a later rule would also match, a
// placeholder without a range, and what the boot half can say of the package.
func TestPureHalfNotes(t *testing.T) {
	chassis, err := psp.ParseFile(repo("testdata", "psp", "lossy", "chassisos.yaml"), psp.OriginOverride)
	if err != nil {
		t.Fatal(err)
	}
	report := Pure(chassis)
	if len(report.Failures) != 0 {
		t.Fatalf("chassisos fails the pure half: %v", report.Failures)
	}
	for _, want := range []string{
		`package chassisos: mapping "Ethernet1/1" is decided by rule front; later rule linecard ("Ethernet{slot}/{port}") would also match it, so the order carries weight`,
		"package chassisos: boot half: not declared (no conformance block)",
	} {
		if !slices.Contains(report.Notes, want) {
			t.Errorf("notes lack %q:\n%s", want, strings.Join(report.Notes, "\n"))
		}
	}
	if report.BootHalf != BootHalfNotDeclared {
		t.Errorf("chassisos boot half = %q, want %q", report.BootHalf, BootHalfNotDeclared)
	}

	shipped := Pure(shippedCopy(t, "ranges: { slot: [1, 1], port: [1, 58], sub: [1, 4] }", "ranges: { port: [1, 58], sub: [1, 4] }"))
	if len(shipped.Failures) != 0 {
		t.Fatalf("a range left out made the package fail: %v", shipped.Failures)
	}
	for _, want := range []string{
		"package nokia_srlinux: rule breakout declares no range for {slot}; it accepts any value there",
		"package nokia_srlinux: boot half: tier 3",
	} {
		if !slices.Contains(shipped.Notes, want) {
			t.Errorf("notes lack %q:\n%s", want, strings.Join(shipped.Notes, "\n"))
		}
	}
}

// The shipped EOS package passes every check of the pure half, for every declaration it
// makes, and says nothing else. The notes are the
// whole of what the suite has to say about it: no rule of the profile matches a name an
// earlier one decides, because "Ethernet{port}" never fits a name with a "/" in it, and
// every placeholder a rule captures carries a range, so the two information lines the
// pure half can emit are both absent. What is left is where the other half runs.
//
// The declarations are counted by kind rather than listed, so the test says what the
// suite exercised: a mapped name under each of the three data rules, both kinds of
// unmappable outcome, and management. A package that declared one trivial mapping would
// pass Pure and fail here.
func TestPureHalfOnTheShippedEOSPackage(t *testing.T) {
	p, err := psp.ParseFile(repo("psp", "arista_eos.yaml"), psp.OriginEmbedded)
	if err != nil {
		t.Fatalf("the shipped EOS package did not load: %v", err)
	}
	report := Pure(p)
	for _, f := range report.Failures {
		t.Error(f.String())
	}
	if want := []string{"package arista_eos: boot half: tier 3"}; !slices.Equal(report.Notes, want) {
		t.Errorf("notes:\n got  %q\n want %q", report.Notes, want)
	}
	if report.BootHalf != BootHalfTier3 {
		t.Errorf("boot half = %q, want %q", report.BootHalf, BootHalfTier3)
	}

	byRule := map[string]int{}
	unmappable := map[string]int{}
	for _, d := range p.Interfaces.Mappings {
		if d.Unmappable != "" {
			unmappable[d.Unmappable]++
			continue
		}
		byRule[d.Rule]++
	}
	for _, rule := range []string{"ethernet", "modular", "breakout", "management"} {
		if byRule[rule] == 0 {
			t.Errorf("no declared mapping is decided by rule %s; the pure half proves nothing about it", rule)
		}
	}
	for _, kind := range []string{psp.UnmappableNoRule, psp.UnmappableOutOfRange} {
		if unmappable[kind] == 0 {
			t.Errorf("no declaration expects %s; the pure half proves nothing about it", kind)
		}
	}
}
