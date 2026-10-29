package probe

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"

	"github.com/santhosh-tekuri/jsonschema/v6"
	"gopkg.in/yaml.v3"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

// declarationSchema compiles the current contract, contracts/probes.schema.json.
func declarationSchema(t *testing.T) *jsonschema.Schema {
	t.Helper()
	path := repoPath("contracts", "probes.schema.json")
	f, err := os.Open(path)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = f.Close() }()
	doc, err := jsonschema.UnmarshalJSON(f)
	if err != nil {
		t.Fatalf("parsing %s: %v", path, err)
	}
	id := doc.(map[string]any)["$id"].(string)
	if id != "https://github.com/happypathnetworking/fylgja/contracts/probes/v"+Version {
		t.Errorf("the contract's $id is %s; it names this repository and the version %s", id, Version)
	}
	c := jsonschema.NewCompiler()
	if err := c.AddResource(id, doc); err != nil {
		t.Fatal(err)
	}
	s, err := c.Compile(id)
	if err != nil {
		t.Fatalf("compiling probes.schema.json (a consumer could not load this schema): %v", err)
	}
	return s
}

func schemaAccepts(t *testing.T, s *jsonschema.Schema, b []byte) error {
	t.Helper()
	v, err := jsonschema.UnmarshalJSON(bytes.NewReader(b))
	if err != nil {
		t.Fatalf("parsing: %v", err)
	}
	return s.Validate(v)
}

// The reader's verdict on a file: refused or not, by Parse, then by Validate against the
// loaded formats, as the server reads a --probes file.
func readerRefuses(t *testing.T, raw []byte, name string) (bool, findings.List) {
	t.Helper()
	reg, err := Load("")
	if err != nil {
		t.Fatal(err)
	}
	d, list := Parse(raw, name)
	if list.Rejected() {
		return true, list
	}
	list = append(list, Validate(d.Probes, reg.Formats(), nil)...)
	return list.Rejected(), list
}

// acrossFields are the rules that read across fields or across the list, which a JSON
// Schema cannot say: the schema accepts their files, the reader refuses them, and the
// contract's description names each.
var acrossFields = map[string]bool{
	findings.RuleProbeNameDuplicate:    true,
	findings.RuleProbeGatewayOutside:   true,
	findings.RuleProbeFamilyMixed:      true,
	findings.RuleProbeAddressDuplicate: true,
}

// The contract and the reader hold one verdict per file: the three declarations tier 1
// reads pass both; each invalid file, named by its rule, is refused by the reader under that
// rule, and by the schema too unless the rule reads across fields, which the description
// says.
func TestTheDeclarationContractAndTheReaderAgree(t *testing.T) {
	schema := declarationSchema(t)
	for _, name := range []string{"n1-loop.json", "n2-loop.json", "e1-loop.json"} {
		t.Run(name, func(t *testing.T) {
			raw := readFixture(t, "testdata", "probes", name)
			if err := schemaAccepts(t, schema, raw); err != nil {
				t.Errorf("the schema refuses %s:\n%v", name, err)
			}
			if refused, list := readerRefuses(t, raw, name); refused {
				t.Errorf("the reader refuses %s: %v", name, list)
			}
		})
	}

	invalid, err := filepath.Glob(repoPath("testdata", "probes", "invalid", "*.json"))
	if err != nil {
		t.Fatal(err)
	}
	if len(invalid) != 10 {
		t.Errorf("%d invalid declarations, want one per rule of the read: %v", len(invalid), invalid)
	}
	raw, err := os.ReadFile(repoPath("contracts", "probes.schema.json"))
	if err != nil {
		t.Fatal(err)
	}

	// An empty file is no JSON document, so no instance of the schema: the reader takes it as
	// declaring none, and the description says so.
	t.Run("none.json", func(t *testing.T) {
		if refused, list := readerRefuses(t, readFixture(t, "testdata", "probes", "none.json"), "none.json"); refused {
			t.Errorf("the reader refuses an empty file: %v", list)
		}
		if !strings.Contains(string(raw), "A --probes file that is empty, or of whitespace alone") {
			t.Errorf("the contract's description does not say what an empty file declares")
		}
	})
	for _, path := range invalid {
		rule := strings.TrimSuffix(filepath.Base(path), ".json")
		t.Run(rule, func(t *testing.T) {
			b, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			refused, list := readerRefuses(t, b, filepath.Base(path))
			if !refused {
				t.Fatalf("the reader accepts %s", path)
			}
			ruled := false
			for _, f := range list {
				ruled = ruled || f.Rule == rule
			}
			if !ruled {
				t.Errorf("the reader refuses %s under %v, not %s", path, list, rule)
			}
			schemaErr := schemaAccepts(t, schema, b)
			switch {
			case acrossFields[rule] && schemaErr != nil:
				t.Errorf("the schema refuses %s, which reads across fields; the reader alone holds it:\n%v", path, schemaErr)
			case acrossFields[rule] && !strings.Contains(string(raw), rule):
				t.Errorf("the contract's description does not name %s, which the schema cannot say", rule)
			case !acrossFields[rule] && schemaErr == nil:
				t.Errorf("the schema accepts %s, which the reader refuses under %s", path, rule)
			}
		})
	}
}

// A declaration Fylgja writes back, inside a snapshot or by marshalling a Declaration, is
// one the contract accepts.
func TestAWrittenDeclarationSatisfiesTheContract(t *testing.T) {
	d, list := Parse(readFixture(t, "testdata", "probes", "n1-loop.json"), "n1-loop.json")
	if list.Rejected() {
		t.Fatal(list)
	}
	b, err := json.Marshal(d)
	if err != nil {
		t.Fatal(err)
	}
	if err := schemaAccepts(t, declarationSchema(t), b); err != nil {
		t.Errorf("a marshalled declaration does not satisfy probes.schema.json:\n%v\n%s", err, b)
	}
}

// The kind says what the declaration says (R-07): schema/fylgja-probe.yaml's name regex is
// NamePattern, its address and gateway regexes are the contract's patterns, its format
// choices are the shipped packages' formats, and its ten attributes are the element's
// fields renamed, a_ and b_ for the two endpoints.
func TestTheKindSaysWhatTheDeclarationSays(t *testing.T) {
	var kind struct {
		Nodes []struct {
			Name, Namespace, Branch string
			Attributes              []struct {
				Name       string
				Kind       string
				Optional   bool
				Parameters struct{ Regex string }
				Choices    []struct{ Name string }
			}
		}
	}
	if err := yaml.Unmarshal(readFixture(t, "schema", "fylgja-probe.yaml"), &kind); err != nil {
		t.Fatal(err)
	}
	if len(kind.Nodes) != 1 || kind.Nodes[0].Namespace+kind.Nodes[0].Name != "FylgjaProbe" || kind.Nodes[0].Branch != "agnostic" {
		t.Fatalf("the kind file holds %+v, want FylgjaProbe alone, branch agnostic", kind.Nodes)
	}
	var contract struct {
		Defs struct {
			Endpoint struct {
				Properties map[string]struct{ Pattern string }
			}
		} `json:"$defs"`
	}
	if err := json.Unmarshal(readFixture(t, "contracts", "probes.schema.json"), &contract); err != nil {
		t.Fatal(err)
	}
	reg, err := Load("")
	if err != nil {
		t.Fatal(err)
	}
	attrs := map[string]int{}
	for i, a := range kind.Nodes[0].Attributes {
		attrs[a.Name] = i
	}
	wantRegex := map[string]string{"name": NamePattern.String()}
	for _, end := range Ends {
		wantRegex[end+"_address"] = contract.Defs.Endpoint.Properties["address"].Pattern
		wantRegex[end+"_gateway"] = contract.Defs.Endpoint.Properties["gateway"].Pattern
		wantRegex[end+"_device"] = ""
		wantRegex[end+"_interface"] = ""
	}
	for name, regex := range wantRegex {
		i, ok := attrs[name]
		if !ok {
			t.Errorf("the kind has no attribute %s", name)
			continue
		}
		a := kind.Nodes[0].Attributes[i]
		if a.Kind != "Text" || a.Optional || a.Parameters.Regex != regex {
			t.Errorf("attribute %s: kind %s, optional %v, regex %q; want Text, required, regex %q", name, a.Kind, a.Optional, a.Parameters.Regex, regex)
		}
	}
	format := kind.Nodes[0].Attributes[attrs["format"]]
	var choices []string
	for _, c := range format.Choices {
		choices = append(choices, c.Name)
	}
	if format.Kind != "Dropdown" || !slices.Equal(choices, reg.Formats()) {
		t.Errorf("format: kind %s, choices %v; want a Dropdown of the shipped formats %v", format.Kind, choices, reg.Formats())
	}
	if len(attrs) != 11 {
		t.Errorf("the kind has %d attributes, want the ten an element maps to and description", len(attrs))
	}
}
