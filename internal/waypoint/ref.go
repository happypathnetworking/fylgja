// Package waypoint names a pinned intent reference by a waypoint the operator wrote in
// Infrahub: the reference syntax, its resolution to a (branch, at), and the list and
// plan of a series (M10).
//
// A waypoint is read, never written: the product's every request to Infrahub is a query
// (Constitution III). It resolves in the CLI, before any run starts, and the run it
// starts is M2–M7's pinned create; nothing of the waypoint enters a CTM or a bundle.
package waypoint

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"
)

// The reference syntax <series>/<sequence>.
const (
	// SeriesPattern is a series: no "/" and no whitespace. It equals the regex the kind
	// enforces at write (schema/fylgja-waypoint.yaml), and a test holds the two equal, so
	// the command line refuses exactly what Infrahub would.
	SeriesPattern = `^[^/\s]+$`
	// SequencePattern is a positive decimal integer with no sign and no leading zero, so
	// demo/01 and demo/1 cannot name one waypoint two ways.
	SequencePattern = `^[1-9][0-9]*$`
	// SeriesForm is how a refusal names a series, the same words in Form and in the
	// refusal of a --series.
	SeriesForm = `a series with no "/" and no whitespace`
	// Form is how a refusal names the syntax, the same words wherever a reference is
	// refused.
	Form = `<series>/<sequence>, ` + SeriesForm + ` and a positive integer`
)

var (
	seriesRE   = regexp.MustCompile(SeriesPattern)
	sequenceRE = regexp.MustCompile(SequencePattern)
)

// Ref names one waypoint.
type Ref struct {
	Series   string
	Sequence int
}

// String is the reference as an operator writes it: demo/2.
func (r Ref) String() string { return r.Series + "/" + strconv.Itoa(r.Sequence) }

// ParseRef reads --waypoint's value. Anything but exactly one series, one "/" and one
// sequence is refused with contracts/cli.md's waypoint.ref.invalid sentence, which names
// the form; the caller files it before any connection.
func ParseRef(s string) (Ref, error) {
	series, sequence, ok := strings.Cut(s, "/")
	if ok && seriesRE.MatchString(series) && sequenceRE.MatchString(sequence) {
		// The pattern admits only digits; a value too large for an int is refused as
		// what it is, not a waypoint anyone wrote.
		if n, err := strconv.Atoi(sequence); err == nil {
			return Ref{Series: series, Sequence: n}, nil
		}
	}
	return Ref{}, fmt.Errorf("--waypoint %q is not a waypoint reference: expected %s", s, Form)
}

// CheckSeries reads --series' value on waypoint list and waypoint plan: a series as the
// reference names one. Anything else is refused in the shape of ParseRef's sentence,
// naming the form of a series; the caller files it as waypoint.ref.invalid before any
// connection (contracts/cli.md).
func CheckSeries(s string) error {
	if seriesRE.MatchString(s) {
		return nil
	}
	return fmt.Errorf("--series %q is not a waypoint series: expected %s", s, SeriesForm)
}
