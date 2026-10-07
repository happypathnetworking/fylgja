package psp

import (
	"fmt"
	"regexp"
	"sort"
	"strconv"
	"strings"
)

// placeholderRE finds {name} placeholders in an interface naming pattern.
var placeholderRE = regexp.MustCompile(`\{([a-z_][a-z0-9_]*)\}`)

// Placeholders returns the placeholder names used by a pattern, sorted and deduplicated.
// It serves each pattern a rule carries: its match, port, node_name and breakout.parent.
// Validation and the profile compare them: a rendered pattern that
// uses a placeholder match does not capture has no value to render, and the placeholders
// port drops from match are what makes a rule lossy. Either is a defect in the package
// rather than in any particular interface.
func Placeholders(pattern string) []string {
	seen := map[string]bool{}
	for _, m := range placeholderRE.FindAllStringSubmatch(pattern, -1) {
		seen[m[1]] = true
	}
	out := make([]string, 0, len(seen))
	for k := range seen {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

// Pattern is a compiled interface naming pattern: it matches production names on one
// side and renders node port names on the other.
type Pattern struct {
	re *regexp.Regexp
}

// CompilePattern turns a naming pattern into a matcher. Placeholders capture one path
// segment each, so "ethernet-{slot}/{port}" cannot swallow a breakout child name.
func CompilePattern(pattern string) (*Pattern, error) {
	if pattern == "" {
		return nil, fmt.Errorf("empty naming pattern")
	}
	var b strings.Builder
	b.WriteString("^")
	last := 0
	for _, loc := range placeholderRE.FindAllStringSubmatchIndex(pattern, -1) {
		b.WriteString(regexp.QuoteMeta(pattern[last:loc[0]]))
		name := pattern[loc[2]:loc[3]]
		b.WriteString("(?P<" + name + ">[^/]+)")
		last = loc[1]
	}
	b.WriteString(regexp.QuoteMeta(pattern[last:]))
	b.WriteString("$")
	re, err := regexp.Compile(b.String())
	if err != nil {
		return nil, fmt.Errorf("naming pattern %q: %w", pattern, err)
	}
	return &Pattern{re: re}, nil
}

// Match returns the captured placeholder values, or nil when the name does not match.
func (p *Pattern) Match(name string) map[string]string {
	m := p.re.FindStringSubmatch(name)
	if m == nil {
		return nil
	}
	out := map[string]string{}
	for i, n := range p.re.SubexpNames() {
		if n != "" {
			out[n] = m[i]
		}
	}
	return out
}

// Render substitutes captured values into a pattern, producing a name. It fails when a
// placeholder has no captured value, which means the two sides of the mapping disagree.
func Render(pattern string, values map[string]string) (string, error) {
	var missing []string
	out := placeholderRE.ReplaceAllStringFunc(pattern, func(tok string) string {
		name := tok[1 : len(tok)-1]
		v, ok := values[name]
		if !ok {
			missing = append(missing, name)
			return tok
		}
		return v
	})
	if len(missing) > 0 {
		sort.Strings(missing)
		return "", fmt.Errorf("pattern %q has no value for %s", pattern, strings.Join(missing, ", "))
	}
	return out, nil
}

// placeholderOrder returns a pattern's placeholders in the order they appear, each
// once. The profile names the first out-of-range placeholder in its rule's match order,
// which the sorted Placeholders cannot say.
func placeholderOrder(pattern string) []string {
	seen := map[string]bool{}
	var out []string
	for _, m := range placeholderRE.FindAllStringSubmatch(pattern, -1) {
		if !seen[m[1]] {
			seen[m[1]] = true
			out = append(out, m[1])
		}
	}
	return out
}

// inRange reports whether a captured value lies in a declared range [min, max],
// inclusive. Only a decimal integer can: a value that is not one (a letter, a sign, an
// empty string, a number too large to parse) is outside, because a range bounds ports
// the node has, and no port is named by anything else.
func inRange(value string, r [2]int) bool {
	if value == "" {
		return false
	}
	for _, c := range value {
		if c < '0' || c > '9' {
			return false
		}
	}
	n, err := strconv.Atoi(value)
	if err != nil {
		return false
	}
	return n >= r[0] && n <= r[1]
}
