package conformance

import "testing"

func TestVersionMatches(t *testing.T) {
	for _, tc := range []struct {
		read   string
		listed []string
		want   string
		ok     bool
	}{
		// What SR Linux 24.7.1 reports.
		{"v24.7.1-330-g38f237abfe", []string{"24.7"}, "24.7", true},
		{"24.7", []string{"24.7"}, "24.7", true},
		{"24.7-rc1", []string{"24.7"}, "24.7", true},
		// A listed version names a release line, not a prefix of a longer number.
		{"24.71", []string{"24.7"}, "", false},
		{"v24.71.1", []string{"24.7"}, "", false},
		// One leading v, no more.
		{"vv24.7", []string{"24.7"}, "", false},
		// The first listed version that matches is named.
		{"v24.10.1", []string{"24.7", "24.10"}, "24.10", true},
		{"v24.7.1", nil, "", false},
		{"v24.7.1", []string{""}, "", false},
		{"", []string{"24.7"}, "", false},
	} {
		got, ok := VersionMatches(tc.read, tc.listed)
		if got != tc.want || ok != tc.ok {
			t.Errorf("VersionMatches(%q, %q) = %q, %v; want %q, %v", tc.read, tc.listed, got, ok, tc.want, tc.ok)
		}
	}
}
