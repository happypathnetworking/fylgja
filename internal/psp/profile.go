package psp

import (
	"fmt"
	"strings"
)

// Profile is a package's mapping profile compiled for use: every rule's patterns
// compiled once, the rules kept in the package's order.
//
// This code branches on what a rule says and on nothing a package is (Constitution II):
// which platform a profile belongs to is invisible here, so a lossy platform is a data
// change, never a code change.
type Profile struct {
	// rules are the data rules in the package's order: a slice, never a map, because the
	// first rule whose match fits a name decides it.
	rules []compiledRule
	mgmt  Rule
	all   []Rule
}

type compiledRule struct {
	rule  Rule
	match *Pattern
	// order is the match's placeholders in the order they appear, for naming the first
	// one out of range.
	order []string
}

// OutcomeKind is what applying the profile to one production name decided.
type OutcomeKind int

const (
	// Mapped: a rule matched with every value in range, and rendered a port.
	Mapped OutcomeKind = iota + 1
	// OutOfRange: a rule matched, but a captured value lies outside its range. The name
	// is decided by that rule and not passed to a later one.
	OutOfRange
	// NoRule: no rule's match fits the name.
	NoRule
)

func (k OutcomeKind) String() string {
	switch k {
	case Mapped:
		return "mapped"
	case OutOfRange:
		return "out of range"
	case NoRule:
		return "no rule"
	}
	return fmt.Sprintf("OutcomeKind(%d)", int(k))
}

// Outcome is what the profile decided for one production name.
type Outcome struct {
	Kind OutcomeKind
	// Rule is the deciding rule's name (Mapped, OutOfRange).
	Rule string
	// Port and NodeName are rendered (Mapped).
	Port, NodeName string
	// Lossy is the deciding rule's (Mapped).
	Lossy bool
	// Parent is the parent's production name when the rule is a breakout rule (Mapped).
	Parent string
	// Placeholder, Value and Range say what fell outside (OutOfRange): the first
	// placeholder, in the rule's match order, whose value is outside its range.
	Placeholder, Value string
	Range              [2]int
	// Tried lists every data rule's name in order (NoRule); the management rule is
	// never tried by name.
	Tried []string
}

// NewProfile compiles a package's rules. A package that loaded has passed validation,
// so an error here means a caller built a PSP by hand and skipped it: a pattern that
// does not compile, a rendered pattern using a placeholder its match does not capture,
// a count of management rules other than one, or a data rule that can render the
// management port or node name.
func NewProfile(p *PSP) (*Profile, error) {
	prof := &Profile{all: append([]Rule(nil), p.Interfaces.Rules...)}
	var mgmts int
	for i, r := range p.Interfaces.Rules {
		label := ruleLabel(i, r)
		if r.Management {
			mgmts++
			prof.mgmt = r
			for _, pat := range []string{r.Port, r.NodeName} {
				if ph := Placeholders(pat); len(ph) > 0 {
					return nil, fmt.Errorf("platform %s: %s: the management rule captures nothing, but %q uses %s",
						p.Platform.ID, label, pat, braceSet(ph))
				}
			}
			continue
		}
		match, err := CompilePattern(r.Match)
		if err != nil {
			return nil, fmt.Errorf("platform %s: %s: match: %w", p.Platform.ID, label, err)
		}
		captured := Placeholders(r.Match)
		rendered := map[string]string{"port": r.Port, "node_name": r.NodeName}
		if r.Breakout != nil {
			rendered["breakout.parent"] = r.Breakout.Parent
		}
		for _, field := range []string{"port", "node_name", "breakout.parent"} {
			pat, ok := rendered[field]
			if !ok {
				continue
			}
			if _, err := CompilePattern(pat); err != nil {
				return nil, fmt.Errorf("platform %s: %s: %s: %w", p.Platform.ID, label, field, err)
			}
			if extra := minus(Placeholders(pat), captured); len(extra) > 0 {
				return nil, fmt.Errorf("platform %s: %s: %s %q uses %s, which match %q does not capture",
					p.Platform.ID, label, field, pat, braceSet(extra), r.Match)
			}
		}
		prof.rules = append(prof.rules, compiledRule{rule: r, match: match, order: placeholderOrder(r.Match)})
	}
	if mgmts != 1 {
		return nil, fmt.Errorf("platform %s: the profile has %d management rules; exactly one is required", p.Platform.ID, mgmts)
	}
	if collides := managementRenders(prof.mgmt, p.Interfaces.Rules); len(collides) > 0 {
		return nil, fmt.Errorf("platform %s: %s", p.Platform.ID, strings.Join(collides, "; "))
	}
	return prof, nil
}

// Apply decides one production name. A mgmt_only interface is Mapped by the management
// rule whatever it is called: mgmt_only is the authority, the profile only names the
// port (D-003). Any other name is tried against the data rules in order, and the
// first whose match fits decides it, in range or out of it: a match is never passed to
// a later rule.
func (p *Profile) Apply(name string, mgmtOnly bool) Outcome {
	if mgmtOnly {
		return Outcome{Kind: Mapped, Rule: p.mgmt.Name, Port: p.mgmt.Port, NodeName: p.mgmt.NodeName}
	}
	for _, cr := range p.rules {
		vals := cr.match.Match(name)
		if vals == nil {
			continue
		}
		r := cr.rule
		for _, ph := range cr.order {
			if rng, ok := r.Ranges[ph]; ok && !inRange(vals[ph], rng) {
				return Outcome{Kind: OutOfRange, Rule: r.Name, Placeholder: ph, Value: vals[ph], Range: rng}
			}
		}
		out := Outcome{Kind: Mapped, Rule: r.Name, Lossy: r.Lossy}
		// NewProfile checked that every rendered pattern uses only captured
		// placeholders, so none of these can fail.
		out.Port, _ = Render(r.Port, vals)
		out.NodeName, _ = Render(r.NodeName, vals)
		if r.Breakout != nil {
			out.Parent, _ = Render(r.Breakout.Parent, vals)
		}
		return out
	}
	tried := make([]string, 0, len(p.rules))
	for _, cr := range p.rules {
		tried = append(tried, cr.rule.Name)
	}
	return Outcome{Kind: NoRule, Tried: tried}
}

// ManagementPort is the node's management port: the management rule's port, which the
// manifest records as each node's management_port. Every node has one, whether or not
// intent flags an interface mgmt_only.
func (p *Profile) ManagementPort() string { return p.mgmt.Port }

// Contains reports whether a production name lies in the named rule's preimage of a
// port: the name matches the rule, its captured values lie in their ranges (the dropped
// ones included), and its kept values render the port. A membership test, never an
// enumeration: the round trip of the conformance suite's pure half asks it of one name.
// The management rule contains nothing by name.
func (p *Profile) Contains(rule, port, production string) bool {
	for _, cr := range p.rules {
		if cr.rule.Name != rule {
			continue
		}
		vals := cr.match.Match(production)
		if vals == nil {
			return false
		}
		for ph, rng := range cr.rule.Ranges {
			if v, ok := vals[ph]; ok && !inRange(v, rng) {
				return false
			}
		}
		got, err := Render(cr.rule.Port, vals)
		return err == nil && got == port
	}
	return false
}

// Rules returns the package's rules, management included, in the package's order.
func (p *Profile) Rules() []Rule { return append([]Rule(nil), p.all...) }

// PlaceholderValue is the value one placeholder takes when a pattern renders a name.
type PlaceholderValue struct {
	Placeholder, Value string
}

// RendersWithin reports whether a rule's rendered pattern (its port or node_name) gives
// name for some values inside the rule's ranges, and returns the values it takes, in the
// pattern's order. The membership test Contains makes, asked of what a rule renders
// rather than what it matches: a placeholder with no range accepts anything.
//
// Every parse of the name is tried, not only the one a regular expression settles on:
// the question is whether any production name renders here, and a pattern whose
// placeholders abut (`eth{slot}{port}`) parses a name more than one way.
func RendersWithin(pattern string, ranges map[string][2]int, name string) ([]PlaceholderValue, bool) {
	var segs []patternSeg
	last := 0
	for _, loc := range placeholderRE.FindAllStringSubmatchIndex(pattern, -1) {
		if loc[0] > last {
			segs = append(segs, patternSeg{literal: pattern[last:loc[0]]})
		}
		segs = append(segs, patternSeg{placeholder: pattern[loc[2]:loc[3]]})
		last = loc[1]
	}
	if last < len(pattern) {
		segs = append(segs, patternSeg{literal: pattern[last:]})
	}
	got := map[string]string{}
	if !assign(segs, name, ranges, got) {
		return nil, false
	}
	values := make([]PlaceholderValue, 0, len(got))
	for _, ph := range placeholderOrder(pattern) {
		values = append(values, PlaceholderValue{ph, got[ph]})
	}
	return values, true
}

// patternSeg is one piece of a naming pattern: literal text or a placeholder.
type patternSeg struct {
	literal, placeholder string
}

// assign finds values for the remaining pieces of a pattern that render rest, each
// placeholder one path segment ([^/]+, as CompilePattern captures it) inside its range,
// and a placeholder used twice taking one value.
func assign(segs []patternSeg, rest string, ranges map[string][2]int, got map[string]string) bool {
	if len(segs) == 0 {
		return rest == ""
	}
	s := segs[0]
	if s.placeholder == "" {
		return strings.HasPrefix(rest, s.literal) && assign(segs[1:], rest[len(s.literal):], ranges, got)
	}
	if v, ok := got[s.placeholder]; ok {
		return strings.HasPrefix(rest, v) && assign(segs[1:], rest[len(v):], ranges, got)
	}
	for n := 1; n <= len(rest) && rest[n-1] != '/'; n++ {
		v := rest[:n]
		if rng, ok := ranges[s.placeholder]; ok && !inRange(v, rng) {
			continue
		}
		got[s.placeholder] = v
		if assign(segs[1:], rest[n:], ranges, got) {
			return true
		}
		delete(got, s.placeholder)
	}
	return false
}

// managementRenders names every data rule that can render the management rule's port or
// node name, each worded as psp.management.collides words it (contracts/cli.md). With
// both refused when a package loads, no interface of any intent lands on the management
// port or takes its node name, so the survey never meets the case.
func managementRenders(mgmt Rule, rules []Rule) []string {
	var out []string
	for i, r := range rules {
		if r.Management || r.Match == "" {
			continue
		}
		for _, f := range []struct{ field, pattern, name, what, noun string }{
			{"port", r.Port, mgmt.Port, "port", "port"},
			{"node_name", r.NodeName, mgmt.NodeName, "node name", "name"},
		} {
			if f.name == "" || f.pattern == "" {
				continue
			}
			values, ok := RendersWithin(f.pattern, r.Ranges, f.name)
			if !ok {
				continue
			}
			var took strings.Builder
			for _, v := range values {
				fmt.Fprintf(&took, ", {%s} = %s", v.Placeholder, v.Value)
			}
			out = append(out, fmt.Sprintf("management %s %q is also rendered by %s (%s %q%s); one %s would mean two things",
				f.what, f.name, ruleLabel(i, r), f.field, f.pattern, took.String(), f.noun))
		}
	}
	return out
}

// ruleLabel names a rule for a message: by name, or by position when it has none.
func ruleLabel(i int, r Rule) string {
	if r.Name == "" {
		return fmt.Sprintf("rule %d", i+1)
	}
	return fmt.Sprintf("rule %q", r.Name)
}

// braceSet writes placeholder names as a message shows them: {a, b}.
func braceSet(names []string) string {
	return "{" + strings.Join(names, ", ") + "}"
}

// minus returns the members of a not in b, in a's order.
func minus(a, b []string) []string {
	in := map[string]bool{}
	for _, x := range b {
		in[x] = true
	}
	var out []string
	for _, x := range a {
		if !in[x] {
			out = append(out, x)
		}
	}
	return out
}
