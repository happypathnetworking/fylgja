package conformance

import "strings"

// VersionMatches reports which of a package's listed versions the version a node reports
// is, if any. One leading "v" is stripped from what was
// read; a listed version L matches when the rest is L, or begins with L followed by "."
// or "-". So "24.7" matches the "v24.7.1-330-g38f237abfe" SR Linux 24.7.1 reports, and
// not "24.71": a listed version names a release line, never a prefix of a longer number.
func VersionMatches(read string, listed []string) (string, bool) {
	rest := strings.TrimPrefix(read, "v")
	for _, l := range listed {
		if l == "" {
			continue
		}
		if rest == l || strings.HasPrefix(rest, l+".") || strings.HasPrefix(rest, l+"-") {
			return l, true
		}
	}
	return "", false
}
