package intent

import (
	"fmt"
	"regexp"
)

// MaxAtFractionDigits is the precision Infrahub honours in an `at`: microseconds.
// Verified against Infrahub 1.11.2 — one to six fractional digits are honoured
// exactly, a seventh and later digit is truncated rather than rounded.
const MaxAtFractionDigits = 6

// atFraction captures the fractional-seconds digits of an instant, and nothing else.
// The rest of the format is deliberately left to Infrahub, which accepts more forms
// than Go's RFC 3339 parser does: Fylgja checks only what it has verified.
var atFraction = regexp.MustCompile(`\.([0-9]+)`)

// CheckAtPrecision rejects an `at` finer than Infrahub honours, before any query is
// sent.
//
// Infrahub truncates past the microsecond, so a finer value would be recorded in the
// envelope as an instant Infrahub never answered for — the read would claim a
// precision it does not have. Truncating locally was rejected too: the operator's
// `at` is recorded verbatim, so a silently coarsened value would no longer
// match what they asked for. The honest answer is to refuse and say why.
//
// Returns an empty message when the value is acceptable.
func CheckAtPrecision(at string) string {
	digits := AtFractionDigits(at)
	if digits <= MaxAtFractionDigits {
		return ""
	}
	return fmt.Sprintf(
		"at %s carries %d fractional digits; Infrahub honours at most %d (microseconds). Re-run with a coarser --at.",
		at, digits, MaxAtFractionDigits)
}

// AtFractionDigits counts the fractional-seconds digits of an instant, 0 when it carries
// none. CheckAtPrecision's measure, shared with the waypoint resolution, which refuses a
// written at under the same rule in its own words (M10).
func AtFractionDigits(at string) int {
	m := atFraction.FindStringSubmatch(at)
	if m == nil {
		return 0
	}
	return len(m[1])
}
