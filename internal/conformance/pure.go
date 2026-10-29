// Package conformance is the conformance suite: what "supported" means for a platform
// support package, checked rather than asserted (Constitution II; D-016, D-017, D-018).
//
// The suite is `go test`, in two halves. The pure half (this file) runs in tier 1 on
// every package meant to load and needs no infrastructure: the package validates, maps
// the production names it declares to the ports and node names it declares, inverts
// them, and renders its bootstrap; and each probe package (016) validates and renders its
// templates. The boot half reads a ready twin's nodes and runs in
// tier 3, inside scripts/e2e.sh's run; it boots nothing itself. The readers it reads them
// through are internal/verify's, product code that twin verify and the step's wait share
// with it (D-037); the checks and their wording are
// the suite's.
//
// No product code imports this package: the compiler stays pure, and the CLI and the
// worker know nothing of the suite (plan, Structure Decision; TestProductDoesNotImportConformance).
// Its verdicts are test results and a row in psp/README.md, never findings.
package conformance

import (
	"fmt"
	"maps"
	"os"
	"slices"
	"strconv"
	"strings"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/probe"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// The pure half's checks, in the order they run.
const (
	CheckValidates = "validates"
	// CheckLinkChange holds the package to declaring what containerlab's reconcile does
	// to a node of its kind on a link change, one of the two values format 0.6 knows. The
	// value is fidelity the package asserts and each step
	// measures; the pure half checks only that it is stated.
	CheckLinkChange = "link_change"
	// CheckMatches holds the package to naming at least one manufacturer and platform pair
	// with both names (format 0.7): a reader picks a device's package by those names, so a
	// package with none could never be read. SharedMatches holds a set of packages, under
	// the same check, to naming no pair twice.
	CheckMatches          = "matches"
	CheckDeclaredMapping  = "declared_mapping"
	CheckRoundTrip        = "round_trip"
	CheckBootstrapRenders = "bootstrap_renders"
	// CheckProbePackage holds a probe package (016, R-08), not a platform's, to the format:
	// it validates as the probe registry validates an override, and every template renders
	// for a host with nothing left in braces. CheckProbes runs it over a set of probe
	// packages; it is not one of PureChecks, which Pure runs on each platform package.
	CheckProbePackage = "probe_package"
)

// PureChecks lists the pure half's checks, so a test can run one subtest per check
// whether or not it failed.
var PureChecks = []string{CheckValidates, CheckLinkChange, CheckMatches, CheckDeclaredMapping, CheckRoundTrip, CheckBootstrapRenders}

// What the boot half says of a package, in its report and its note.
const (
	BootHalfNotDeclared = "not declared (no conformance block)"
	BootHalfTier3       = "tier 3"
)

// bootstrapNode is the node name the pure half renders {node} with: any fixed name will
// do, since the check is that nothing is left unrendered.
const bootstrapNode = "n1"

// Report is what one half of the suite found of one package.
type Report struct {
	Package string // the platform id
	Path    string // the file the package was read from
	// Failures are every failure of every check, none stopping the run.
	Failures []Failure
	// Notes are information, never failures: an order that carries weight, a
	// placeholder without a range, and what the boot half can say of the package.
	Notes []string
	// BootHalf is BootHalfNotDeclared or BootHalfTier3.
	BootHalf string
	// Nodes are the boot half's nodes of this package, in name order; empty in the pure
	// half.
	Nodes []BootNode
}

// Failure is one check that did not hold, naming the package, the check and both values.
// The pure half's Package and Path are its report's, carried so a failure reads
// alone.
type Failure struct {
	Package, Path string
	Check         string
	// Production is the declared production name the check was holding the package to;
	// empty for a check of the whole package.
	Production string
	// Declared and Produced are what the package said and what it gave.
	Declared, Produced string

	// Node is the node the boot half was reading; empty in the pure half, and for a
	// boot-half failure of the package as a whole.
	Node string
	// Message is a boot-half failure, whole, as the boot half words it;
	// empty in the pure half, whose String assembles the message from the fields above.
	Message string
}

// String gives the failure as the suite words it. The pure half's:
// package <id> (<path>): <check>: <production>: declared <…>, produced <…>; the boot
// half's is its Message.
func (f Failure) String() string {
	if f.Message != "" {
		return f.Message
	}
	subject := ""
	if f.Production != "" {
		subject = f.Production + ": "
	}
	return fmt.Sprintf("package %s (%s): %s: %sdeclared %s, produced %s",
		f.Package, f.Path, f.Check, subject, f.Declared, f.Produced)
}

// Of returns the report's failures under one check.
func (r Report) Of(check string) []Failure {
	var out []Failure
	for _, f := range r.Failures {
		if f.Check == check {
			out = append(out, f)
		}
	}
	return out
}

// Pure runs the pure half on one package: it validates as `psp
// validate` validates the file it was read from; it states its link_change and names a
// manufacturer and platform pair; each declared mapping gives what it declares; each mapped declaration inverts from its port; and every bootstrap line
// renders with nothing left in braces. Every failure is collected; none stops the run.
//
// Nothing here knows which platform it holds: the expectations are the package's own
// declared mappings, so the suite carries no per-platform code (Constitution II).
func Pure(p *psp.PSP) Report {
	r := Report{Package: p.Platform.ID, Path: p.Path}
	fail := func(check, production, declared, produced string) {
		r.Failures = append(r.Failures, Failure{Package: r.Package, Path: r.Path, Check: check,
			Production: production, Declared: declared, Produced: produced})
	}

	validates(p, fail)
	linkChange(p, fail)
	matches(p, fail)

	rules := map[string]psp.Rule{}
	for _, rule := range p.Interfaces.Rules {
		rules[rule.Name] = rule
	}
	prof, err := psp.NewProfile(p)
	if err != nil {
		for _, check := range []string{CheckDeclaredMapping, CheckRoundTrip} {
			fail(check, "", "a profile that builds", err.Error())
		}
	} else {
		for _, d := range p.Interfaces.Mappings {
			declaredMapping(prof, rules, d, fail)
			roundTrip(prof, rules, d, fail)
		}
		r.Notes = append(r.Notes, laterRuleNotes(p, prof)...)
	}
	bootstrapRenders(p, rules, fail)

	for _, rule := range p.Interfaces.Rules {
		if rule.Management {
			continue
		}
		for _, ph := range psp.Placeholders(rule.Match) {
			if _, ok := rule.Ranges[ph]; !ok {
				r.Notes = append(r.Notes, fmt.Sprintf("package %s: rule %s declares no range for {%s}; it accepts any value there",
					r.Package, rule.Name, ph))
			}
		}
	}

	r.BootHalf = BootHalfNotDeclared
	if p.Conformance != nil {
		r.BootHalf = BootHalfTier3
	}
	r.Notes = append(r.Notes, fmt.Sprintf("package %s: boot half: %s", r.Package, r.BootHalf))
	return r
}

type failFunc func(check, production, declared, produced string)

// validates holds the package to `psp validate` on the file it was read from, every
// psp.* rule. A package with no path, or one whose file cannot be read, fails naming
// the path rather than being skipped: the pure half checks what a file says.
func validates(p *psp.PSP, fail failFunc) {
	const declared = "no rejection from psp validate"
	if p.Path == "" {
		fail(CheckValidates, "", declared, "nothing: the package names no file it was read from")
		return
	}
	if _, err := os.Stat(p.Path); err != nil {
		fail(CheckValidates, "", declared, fmt.Sprintf("nothing: %s cannot be read: %v", p.Path, err))
		return
	}
	var rejected []string
	for _, f := range psp.Validate([]string{p.Path}) {
		if f.Severity == findings.Rejection {
			rejected = append(rejected, f.Rule+": "+f.Message)
		}
	}
	if len(rejected) > 0 {
		fail(CheckValidates, "", declared, strings.Join(rejected, "; "))
	}
}

// linkChange holds the package's fidelity.link_change to one of the values the format
// knows. A package that states none, or another, says nothing a step can compare
// containerlab's plan with.
func linkChange(p *psp.PSP, fail failFunc) {
	switch p.Fidelity.LinkChange {
	case psp.LinkChangeRestart, psp.LinkChangeLive:
		return
	}
	declared := p.Fidelity.LinkChange
	if declared == "" {
		declared = "nothing"
	}
	fail(CheckLinkChange, "", declared,
		fmt.Sprintf("not one of %s, %s", psp.LinkChangeRestart, psp.LinkChangeLive))
}

// matches holds the package to at least one manufacturer and platform pair whose two names
// are both given; a pair with an empty name matches no device, so it counts as declared and
// never as produced.
func matches(p *psp.PSP, fail failFunc) {
	for _, m := range p.Platform.Matches {
		if m.Manufacturer != "" && m.Platform != "" {
			return
		}
	}
	n := len(p.Platform.Matches)
	declared := fmt.Sprintf("%d pairs", n)
	if n == 1 {
		declared = "1 pair"
	}
	fail(CheckMatches, "", declared, "none")
}

// SharedMatches holds a set of packages to naming each manufacturer and platform pair once:
// two packages naming one pair would leave a device of it with two packages. Each failure
// names the package that repeats the pair, the pair, and the package that named it first;
// a pair named twice in one package is that package's own, and no failure.
func SharedMatches(pkgs []*psp.PSP) []Failure {
	first := map[psp.Match]*psp.PSP{}
	var out []Failure
	for _, p := range pkgs {
		for _, m := range p.Platform.Matches {
			prior, dup := first[m]
			if !dup {
				first[m] = p
				continue
			}
			if prior == p {
				continue
			}
			out = append(out, Failure{Package: p.Platform.ID, Path: p.Path, Check: CheckMatches, Declared: m.String(),
				Produced: fmt.Sprintf("the pair package %s (%s) declares", prior.Platform.ID, prior.Path)})
		}
	}
	return out
}

// declaredMapping holds one declaration to what the profile makes of its production
// name. A declaration naming the management rule is applied as the
// mgmt_only interface it describes.
func declaredMapping(prof *psp.Profile, rules map[string]psp.Rule, d psp.DeclaredMapping, fail failFunc) {
	out := prof.Apply(d.Production, rules[d.Rule].Management)
	var declared string
	switch d.Unmappable {
	case psp.UnmappableNoRule:
		declared = "no_rule"
	case psp.UnmappableOutOfRange:
		declared = "out_of_range under rule " + d.Rule
	default:
		declared = mapped(d.Rule, d.Port, d.NodeName, d.Lossy)
	}
	if produced := describe(out); produced != declared {
		fail(CheckDeclaredMapping, d.Production, declared, produced)
	}
}

// describe words an outcome as a declaration of it would read.
func describe(out psp.Outcome) string {
	switch out.Kind {
	case psp.Mapped:
		return mapped(out.Rule, out.Port, out.NodeName, out.Lossy)
	case psp.OutOfRange:
		return fmt.Sprintf("out_of_range under rule %s", out.Rule)
	}
	return "no_rule"
}

func mapped(rule, port, nodeName string, lossy bool) string {
	return fmt.Sprintf("rule %s, port %s, node name %s, lossy %t", rule, port, nodeName, lossy)
}

// roundTrip inverts a mapped declaration from its port: a rule that loses
// nothing gives back exactly the production name; a lossy one gives a set, which must
// contain it. The management declaration is left out: mgmt_only decides it, not its
// name, so there is no name to give back (D-003).
func roundTrip(prof *psp.Profile, rules map[string]psp.Rule, d psp.DeclaredMapping, fail failFunc) {
	if d.Unmappable != "" {
		return
	}
	rule, ok := rules[d.Rule]
	if !ok {
		fail(CheckRoundTrip, d.Production, "production "+d.Production,
			fmt.Sprintf("nothing: rule %s is not in the profile", d.Rule))
		return
	}
	if rule.Management {
		return
	}
	inverse := fmt.Sprintf("inverse of port %s under rule %s: ", d.Port, d.Rule)
	if rule.Lossy {
		if !prof.Contains(d.Rule, d.Port, d.Production) {
			fail(CheckRoundTrip, d.Production, "production "+d.Production, inverse+"a set that does not contain it")
		}
		return
	}
	pat, err := psp.CompilePattern(rule.Port)
	if err != nil {
		fail(CheckRoundTrip, d.Production, "production "+d.Production, inverse+err.Error())
		return
	}
	values := pat.Match(d.Port)
	if values == nil {
		fail(CheckRoundTrip, d.Production, "production "+d.Production,
			fmt.Sprintf("%snothing; the port does not parse under %q", inverse, rule.Port))
		return
	}
	back, err := psp.Render(rule.Match, values)
	if err != nil {
		fail(CheckRoundTrip, d.Production, "production "+d.Production, inverse+err.Error())
		return
	}
	if back != d.Production {
		fail(CheckRoundTrip, d.Production, "production "+d.Production, inverse+back)
	}
}

// bootstrapRenders renders every bootstrap line as the compiler does for each mapped,
// non-management declaration, as though the node had that port cabled: {node} a fixed
// name, {port} and {interface} the declaration's port and node name. A line left with a
// placeholder is named once, with the first declaration that exposed it.
func bootstrapRenders(p *psp.PSP, rules map[string]psp.Rule, fail failFunc) {
	named := map[string]bool{}
	for _, d := range p.Interfaces.Mappings {
		if d.Unmappable != "" || rules[d.Rule].Management {
			continue
		}
		// One pass, so a substituted name is never itself re-substituted, as the
		// compiler's renderBootstrap does it.
		r := strings.NewReplacer("{node}", bootstrapNode, "{port}", d.Port, "{interface}", d.NodeName)
		for _, line := range p.Config.Bootstrap {
			out := r.Replace(line)
			if !strings.Contains(out, "{") || named[line] {
				continue
			}
			named[line] = true
			fail(CheckBootstrapRenders, d.Production, fmt.Sprintf("line %q", line),
				fmt.Sprintf("%q, a placeholder left unrendered", out))
		}
	}
}

// laterRuleNotes names each declared production name a later data rule would also
// match: the first rule to match decides, so the package's order carries weight there.
// Information, never a failure.
func laterRuleNotes(p *psp.PSP, prof *psp.Profile) []string {
	var data []psp.Rule
	for _, r := range prof.Rules() {
		if !r.Management {
			data = append(data, r)
		}
	}
	management := map[string]bool{}
	for _, r := range p.Interfaces.Rules {
		management[r.Name] = r.Management
	}
	var notes []string
	for _, d := range p.Interfaces.Mappings {
		if management[d.Rule] {
			continue // decided by mgmt_only, never by name
		}
		out := prof.Apply(d.Production, false)
		decided := slices.IndexFunc(data, func(r psp.Rule) bool { return r.Name == out.Rule })
		if out.Kind == psp.NoRule || decided < 0 {
			continue
		}
		for _, later := range data[decided+1:] {
			pat, err := psp.CompilePattern(later.Match)
			if err != nil || pat.Match(d.Production) == nil {
				continue
			}
			notes = append(notes, fmt.Sprintf(
				"package %s: mapping %q is decided by rule %s; later rule %s (%q) would also match it, so the order carries weight",
				p.Platform.ID, d.Production, out.Rule, later.Name, later.Match))
		}
	}
	return notes
}

// probeSample is what CheckProbes renders a probe package's templates for: a host on a
// documentation /31 (RFC 5737), its gateway the device's end, and the far host's address.
// Any values do, since the check is that every placeholder renders and none is left over.
var probeSample = map[string]string{
	probe.PlaceAddress:    "192.0.2.1/31",
	probe.PlaceGateway:    "192.0.2.0",
	probe.PlaceFarAddress: "198.51.100.1",
}

// CheckProbes runs the probe package check on each package (016, R-08): it validates as
// the probe registry validates an override, every probe.package.* rule; and each of its
// templates (the two exec lines, the readiness command and its expectation, the flow's and
// the burst's command) renders for a host from its own field's placeholders with nothing
// left in braces. Every failure is
// collected, named by the package's format, its file, the template's field and both
// values; none stops the run. Nothing here knows which format it holds.
func CheckProbes(pkgs []*probe.Package) []Failure {
	var out []Failure
	for _, p := range pkgs {
		fail := func(field, declared, produced string) {
			out = append(out, Failure{Package: p.Format, Path: p.Path, Check: CheckProbePackage,
				Production: field, Declared: declared, Produced: produced})
		}
		probeValidates(p, fail)
		values := maps.Clone(probeSample)
		values[probe.PlaceInterface] = p.Host.Interface
		values[probe.PlaceInterval] = strconv.FormatFloat(p.Flow.IntervalS, 'f', -1, 64)
		values[probe.PlaceCount] = strconv.Itoa(p.Burst.Count)
		values[probe.PlaceWait] = strconv.Itoa(p.Burst.WaitS)
		for _, t := range p.Templates() {
			const declared = "every placeholder rendered"
			// Each template is rendered with its own field's placeholders alone, as the
			// compiler, the host check and verify render it.
			own := map[string]string{}
			for _, place := range t.Places {
				own[place] = values[place]
			}
			args, err := probe.Render(t.Args, own)
			if err != nil {
				fail(t.Field, declared, err.Error())
				continue
			}
			if line := strings.Join(args, " "); strings.ContainsAny(line, "{}") {
				fail(t.Field, declared, line)
			}
		}
	}
	return out
}

// probeValidates holds a probe package to the probe registry's validation of the file it
// was read from. A package with no path, or one whose file cannot be read, fails naming the
// path, as a platform package does.
func probeValidates(p *probe.Package, fail func(field, declared, produced string)) {
	const declared = "no rejection from the probe package's validation"
	if p.Path == "" {
		fail("", declared, "nothing: the package names no file it was read from")
		return
	}
	if _, err := os.Stat(p.Path); err != nil {
		fail("", declared, fmt.Sprintf("nothing: %s cannot be read: %v", p.Path, err))
		return
	}
	var rejected []string
	for _, f := range probe.ValidatePackages([]string{p.Path}) {
		if f.Severity == findings.Rejection {
			rejected = append(rejected, f.Rule+": "+f.Message)
		}
	}
	if len(rejected) > 0 {
		fail("", declared, strings.Join(rejected, "; "))
	}
}
