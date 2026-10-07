package waypoint

import (
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"

	"gopkg.in/yaml.v3"
)

// Every shape of a reference: one parses, and each other shape is refused naming the form.
func TestParseRef(t *testing.T) {
	got, err := ParseRef("demo/2")
	if err != nil {
		t.Fatalf("demo/2: %v", err)
	}
	if got != (Ref{Series: "demo", Sequence: 2}) || got.String() != "demo/2" {
		t.Errorf("demo/2 parsed to %+v (%s)", got, got)
	}
	if got, err := ParseRef("fylgja-test-wp-1790611429/12"); err != nil || got.Sequence != 12 {
		t.Errorf("a test series with a two-digit sequence: %+v, %v", got, err)
	}

	for _, s := range []string{
		"demo",    // no sequence
		"demo/",   // an empty sequence
		"/2",      // an empty series
		"demo/02", // a leading zero: demo/2 and demo/02 would name one waypoint two ways
		"demo/0",  // below the kind's floor
		"demo/-1", // a sign
		"demo/+1",
		"de mo/2",                      // whitespace in the series
		"demo/2 ",                      // trailing whitespace
		" demo/2",                      // leading whitespace
		"a/b/2",                        // a "/" in the series
		"demo/2.0",                     // not an integer
		"demo/99999999999999999999999", // not an int
		"",
	} {
		_, err := ParseRef(s)
		if err == nil {
			t.Errorf("%q parsed; want waypoint.ref.invalid", s)
			continue
		}
		want := `--waypoint "` + s + `" is not a waypoint reference: expected <series>/<sequence>, ` +
			`a series with no "/" and no whitespace and a positive integer`
		if err.Error() != want {
			t.Errorf("%q: message\n  %s\nwant\n  %s", s, err, want)
		}
	}
}

// --series on waypoint list and waypoint plan is a series as a reference names one, refused
// in the reference's shape, naming a series' form (contracts/cli.md).
func TestCheckSeries(t *testing.T) {
	for _, s := range []string{"demo", "fylgja-test-wp-1790611429", "a.b-c_d"} {
		if err := CheckSeries(s); err != nil {
			t.Errorf("%q: %v", s, err)
		}
	}
	for _, s := range []string{"", "a b", "a/b", " demo", "demo ", "demo/2", "de\tmo"} {
		err := CheckSeries(s)
		want := `--series ` + strconv.Quote(s) + ` is not a waypoint series: expected a series with no "/" and no whitespace`
		if err == nil || err.Error() != want {
			t.Errorf("%q: %v; want %s", s, err, want)
		}
	}
}

// The command line refuses exactly the series the kind refuses at write: SeriesPattern is
// the regex schema/fylgja-waypoint.yaml gives the series attribute, read from the file.
func TestSeriesPatternIsTheSchemaRegex(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join("..", "..", "schema", "fylgja-waypoint.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	var doc struct {
		Nodes []struct {
			Name       string `yaml:"name"`
			Namespace  string `yaml:"namespace"`
			Attributes []struct {
				Name       string `yaml:"name"`
				Parameters struct {
					Regex    string `yaml:"regex"`
					MinValue *int   `yaml:"min_value"`
				} `yaml:"parameters"`
			} `yaml:"attributes"`
		} `yaml:"nodes"`
	}
	if err := yaml.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}
	var regex string
	var floor *int
	for _, n := range doc.Nodes {
		if n.Namespace+n.Name != "FylgjaWaypoint" {
			continue
		}
		for _, a := range n.Attributes {
			switch a.Name {
			case "series":
				regex = a.Parameters.Regex
			case "sequence":
				floor = a.Parameters.MinValue
			}
		}
	}
	if regex != SeriesPattern {
		t.Errorf("the schema's series regex is %q; SeriesPattern is %q", regex, SeriesPattern)
	}
	// The sequence pattern has no zero and no sign, which is the schema's floor of 1.
	if floor == nil || *floor != 1 || !strings.HasPrefix(SequencePattern, "^[1-9]") {
		t.Errorf("the schema's sequence floor is %v; SequencePattern %q must admit exactly the integers from 1", floor, SequencePattern)
	}
}
