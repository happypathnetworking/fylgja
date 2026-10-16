package stages

import (
	"strconv"
	"testing"

	"gopkg.in/yaml.v3"

	"github.com/happypathnetworking/fylgja"
)

// Every shape of a reference: one parses, split at its first "/", and each other shape is
// refused naming the form.
func TestParseRef(t *testing.T) {
	for s, want := range map[string]Ref{
		"change-1/cabled":                 {Branch: "change-1", Label: "cabled"},
		"change-1/head":                   {Branch: "change-1", Label: LabelHead},
		"change-1/branch-point":           {Branch: "change-1", Label: LabelBranchPoint},
		"fylgja-test-st-1790611429/a.b_c": {Branch: "fylgja-test-st-1790611429", Label: "a.b_c"},
	} {
		got, err := ParseRef(s)
		if err != nil {
			t.Errorf("%s: %v", s, err)
			continue
		}
		if got != want || got.String() != s {
			t.Errorf("%s parsed to %+v (%s)", s, got, got)
		}
	}

	for _, s := range []string{
		"change-1",         // no "/"
		"change-1/",        // an empty label
		"/cabled",          // an empty branch
		"/",                // both empty
		"a/b/c",            // a second "/" goes to the label, whose pattern refuses it
		"a b/c",            // whitespace in the branch
		"a/b c",            // whitespace in the label
		"change-1/cabled ", // trailing whitespace
		" change-1/cabled", // leading whitespace
		"a\t/b",
		"",
	} {
		_, err := ParseRef(s)
		if err == nil {
			t.Errorf("%q parsed; want stage.ref.invalid", s)
			continue
		}
		want := `--stage ` + strconv.Quote(s) + ` is not a stage reference: expected <branch>/<label>, ` +
			`a branch with no "/" and no whitespace and a label with neither`
		if err.Error() != want {
			t.Errorf("%q: message\n  %s\nwant\n  %s", s, err, want)
		}
	}
}

// The derived stages are the two reserved labels, and nothing else.
func TestDerived(t *testing.T) {
	for label, want := range map[string]bool{LabelBranchPoint: true, LabelHead: true, "cabled": false,
		"Head": false, "branch_point": false} {
		if got := (Ref{Branch: "b", Label: label}).Derived(); got != want {
			t.Errorf("%s derived: %v, want %v", label, got, want)
		}
	}
}

// --branch on stage list and stage plan is a branch as a reference names one, refused in
// the reference's shape, naming a branch's form.
func TestCheckBranch(t *testing.T) {
	for _, s := range []string{"change-1", "fylgja-test-st-1790611429", "a.b-c_d"} {
		if err := CheckBranch(s); err != nil {
			t.Errorf("%q: %v", s, err)
		}
	}
	for _, s := range []string{"", "a b", "a/b", " b", "b ", "b/head", "b\tc"} {
		err := CheckBranch(s)
		want := `--branch ` + strconv.Quote(s) + ` is not a branch: expected a branch with no "/" and no whitespace`
		if err == nil || err.Error() != want {
			t.Errorf("%q: %v; want %s", s, err, want)
		}
	}
}

// The command line refuses exactly the labels the kind refuses at write: LabelPattern is
// the regex the embedded schema/fylgja-stage.yaml gives the label attribute.
func TestLabelPatternEqualsTheKinds(t *testing.T) {
	raw, err := fylgja.Data.ReadFile("schema/fylgja-stage.yaml")
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
					Regex string `yaml:"regex"`
				} `yaml:"parameters"`
			} `yaml:"attributes"`
		} `yaml:"nodes"`
	}
	if err := yaml.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}
	var regex string
	for _, n := range doc.Nodes {
		if n.Namespace+n.Name != "FylgjaStage" {
			continue
		}
		for _, a := range n.Attributes {
			if a.Name == "label" {
				regex = a.Parameters.Regex
			}
		}
	}
	if regex != LabelPattern {
		t.Errorf("the schema's label regex is %q; LabelPattern is %q", regex, LabelPattern)
	}
	// A branch is held to the same pattern, so <branch>/<label> splits at its first "/"
	// without ambiguity.
	if BranchPattern != LabelPattern {
		t.Errorf("BranchPattern %q differs from LabelPattern %q", BranchPattern, LabelPattern)
	}
}
