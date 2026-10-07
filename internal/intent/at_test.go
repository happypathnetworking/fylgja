package intent

import (
	"strconv"
	"strings"
	"testing"
)

// Infrahub honours an `at` to the microsecond and truncates beyond it.
// One to six fractional digits pass; seven or more are refused before any query, so
// the envelope never records an instant Infrahub did not answer for.
func TestAtPrecisionGuard(t *testing.T) {
	for _, tc := range []struct {
		at      string
		digits  int
		refused bool
	}{
		{at: "", refused: false},
		{at: "2026-09-08T19:37:02Z", refused: false},
		{at: "2026-09-08T19:37:02.1Z", refused: false},
		{at: "2026-09-08T19:37:02.12Z", refused: false},
		{at: "2026-09-08T19:37:02.123Z", refused: false},
		{at: "2026-09-08T19:37:02.1234Z", refused: false},
		{at: "2026-09-08T19:37:02.12345Z", refused: false},
		{at: "2026-09-08T19:37:02.123456Z", refused: false},
		{at: "2026-09-08T19:37:02.1234567Z", digits: 7, refused: true},
		{at: "2026-09-08T19:37:02.123456789Z", digits: 9, refused: true},
	} {
		msg := CheckAtPrecision(tc.at)
		if tc.refused && msg == "" {
			t.Errorf("at %q: expected a refusal", tc.at)
			continue
		}
		if !tc.refused {
			if msg != "" {
				t.Errorf("at %q: unexpected refusal: %s", tc.at, msg)
			}
			continue
		}
		// The message has to tell the operator what to do about it, which means
		// naming the value, its precision, and the precision Infrahub honours.
		for _, want := range []string{tc.at, "fractional digits", "microseconds"} {
			if !strings.Contains(msg, want) {
				t.Errorf("at %q: message does not mention %q: %s", tc.at, want, msg)
			}
		}
		if !strings.Contains(msg, strconv.Itoa(tc.digits)) {
			t.Errorf("at %q: message does not name the digit count %d: %s", tc.at, tc.digits, msg)
		}
	}
}

// A timezone offset is not a fractional second. The guard inspects only the fraction
// and leaves the rest of the format to Infrahub, which accepts more forms than Go's
// RFC 3339 parser.
func TestAtPrecisionIgnoresTheRestOfTheFormat(t *testing.T) {
	for _, at := range []string{
		"2026-09-08T19:37:02+00:00",
		"2026-09-08T19:37:02.123456+02:00",
		"yesterday",
	} {
		if msg := CheckAtPrecision(at); msg != "" {
			t.Errorf("at %q: the precision guard should not judge this: %s", at, msg)
		}
	}
}

// The `at` reaches Infrahub as a URL query parameter, verbatim and encoded — and is
// absent from the URL entirely when the operator supplied none.
func TestEndpointEncodesAt(t *testing.T) {
	cfg := Config{Address: "http://h:8000", Branch: "my-branch", At: "2026-09-08T18:00:00+00:00"}
	got := cfg.endpoint()
	// An unencoded "+" is read as a space and rejected by Infrahub.
	if strings.Contains(got, "+00:00") {
		t.Errorf("endpoint leaves the timezone offset unencoded: %s", got)
	}
	if !strings.Contains(got, "%2B00%3A00") {
		t.Errorf("endpoint does not URL-encode the instant: %s", got)
	}
	if !strings.HasPrefix(got, "http://h:8000/graphql/my-branch?at=") {
		t.Errorf("unexpected endpoint: %s", got)
	}

	bare := Config{Address: "http://h:8000", Branch: "my-branch"}.endpoint()
	if strings.Contains(bare, "at=") || strings.Contains(bare, "?") {
		t.Errorf("no at was supplied, so none may be sent: %s", bare)
	}
	if bare != "http://h:8000/graphql/my-branch" {
		t.Errorf("unexpected endpoint: %s", bare)
	}
}
