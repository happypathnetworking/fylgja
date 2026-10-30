package fylgja

import (
	"os"
	"regexp"
	"slices"
	"strconv"
	"strings"
	"testing"

	"gopkg.in/yaml.v3"
)

// checkTimeouts is each check definition .infrahub.yml registers, with the timeout its class
// sets (contracts/checks.md): Infrahub makes the class's timeout the check's task timeout at
// import, and a check it times out leaves its validator in_progress (research §1.4).
// fylgja-twin's is the rehearsal's ceiling plus 660 s, which the orchestrator's
// test_checks_glue.py and test_rehearse.py hold against the flow's timeout and the ceiling
// (R-09; internal/rehearsal's TestTheTwinCheckOutlastsItsRehearsal did until 020's T035).
var checkTimeouts = map[string]int{
	"fylgja-step": 300,
	"fylgja-twin": 4260,
}

// checkQuery is the query every check's class binds: the cheap read the SDK requires.
const checkQuery = "fylgja_branch"

// .infrahub.yml registers each check as the OpsMill skill and contracts/checks.md give its
// shape: a file that defines the class it names as an InfrahubCheck, the class binding the
// registered query fylgja_branch by its query attribute and setting its timeout, and a
// global definition, with no query, targets or parameters key, which the SDK's
// configuration model would refuse or the pipeline would scope. A mistake here passes every
// other tier-1 test and fails only once Infrahub imports the registration.
func TestInfrahubYAMLRegistersTheChecks(t *testing.T) {
	raw, err := os.ReadFile(".infrahub.yml")
	if err != nil {
		t.Fatal(err)
	}
	var cfg struct {
		Queries []struct {
			Name     string `yaml:"name"`
			FilePath string `yaml:"file_path"`
		} `yaml:"queries"`
		CheckDefinitions []map[string]any `yaml:"check_definitions"`
	}
	if err := yaml.Unmarshal(raw, &cfg); err != nil {
		t.Fatalf("parsing .infrahub.yml: %v", err)
	}

	var queries []string
	for _, q := range cfg.Queries {
		queries = append(queries, q.Name)
		if _, err := os.Stat(q.FilePath); err != nil {
			t.Errorf("query %s: its file %s: %v", q.Name, q.FilePath, err)
		}
	}
	if !slices.Contains(queries, checkQuery) {
		t.Errorf("the queries are %v; %s, which every check's class binds, is not among them", queries, checkQuery)
	}

	var names []string
	for _, def := range cfg.CheckDefinitions {
		name, _ := def["name"].(string)
		names = append(names, name)
		for _, key := range []string{"query", "targets", "parameters"} {
			if _, ok := def[key]; ok {
				t.Errorf("check %s carries %q: a check is global, and binds its query through its class", name, key)
			}
		}
		file, _ := def["file_path"].(string)
		class, _ := def["class_name"].(string)
		if file == "" || class == "" {
			t.Errorf("check %s names file %q and class %q; want both", name, file, class)
			continue
		}
		src, err := os.ReadFile(file)
		if err != nil {
			t.Errorf("check %s: its file: %v", name, err)
			continue
		}
		body, ok := classBody(string(src), class)
		if !ok {
			t.Errorf("check %s: %s defines no class %s(InfrahubCheck)", name, file, class)
			continue
		}
		if !regexp.MustCompile(`(?m)^\s+query = "` + checkQuery + `"$`).MatchString(body) {
			t.Errorf("check %s: class %s does not set query = %q", name, class, checkQuery)
		}
		want, known := checkTimeouts[name]
		if !known {
			t.Errorf("check %s is registered, and this test names no timeout for it", name)
			continue
		}
		m := regexp.MustCompile(`(?m)^\s+timeout = (\d+)$`).FindStringSubmatch(body)
		if m == nil {
			t.Errorf("check %s: class %s sets no timeout, so Infrahub would cut it at the SDK's 60 s", name, class)
			continue
		}
		if got, _ := strconv.Atoi(m[1]); got != want {
			t.Errorf("check %s: class %s sets timeout %d, want %d", name, class, got, want)
		}
	}
	for name := range checkTimeouts {
		if !slices.Contains(names, name) {
			t.Errorf("the check definitions are %v; %s is not among them", names, name)
		}
	}
}

// classBody is the body of the top-level class name in a Python source, when the source
// defines it as an InfrahubCheck: its lines up to the next top-level statement.
func classBody(src, name string) (string, bool) {
	header := "class " + name + "(InfrahubCheck):"
	var body []string
	in := false
	for line := range strings.SplitSeq(src, "\n") {
		switch {
		case line == header:
			in = true
		case in && line != "" && !strings.HasPrefix(line, " ") && !strings.HasPrefix(line, "\t"):
			return strings.Join(body, "\n"), true
		case in:
			body = append(body, line)
		}
	}
	return strings.Join(body, "\n"), in
}
