//go:build contract

package checks

import (
	"encoding/json"
	"fmt"
	"io/fs"
	"math/rand"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"strings"
	"testing"
	"time"

	"gopkg.in/yaml.v3"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/stages"
	"github.com/happypathnetworking/fylgja/internal/testsupport"
)

// The checks inside a real Infrahub's pipeline, never a fake (D-017), through a registration
// of the test's own served from the Docker bridge (research R-18), against the API's server
// Infrahub's task workers reach through the Compose override: on the development host, the
// operator's, on the bridge (D-050). The test seeds a throwaway branch and deletes, however it
// ends, the branch with what hangs on it, then its registration with its definitions and query.
// It asks Fylgja for plans alone, so it boots no twin; still, boot none while it runs.
//
//	set -a; . local/.env; set +a; go test -count=1 -tags contract ./internal/checks -run TestChecksInsideInfrahub -v

// The waits, each bounded by what research measured: an import's definitions on main in
// about 21 s, both task workers' fetches about 15 s after it (§1.3, §1.5); a check re-run
// about 20 s after the run-check (§1.5), bounded by fylgja-step's own timeout and a margin.
const (
	importWait    = 3 * time.Minute
	fetchWait     = 15 * time.Second
	userCheckWait = 6 * time.Minute
	checksumWait  = 90 * time.Second
)

// unreached are the glue's sentences for a task worker that reaches no server
// (infrahub/checks/fylgja_api.py: Unreachable, Unset), as on CI's contract job, which runs
// none: there the test proves what it can and skips.
var unreached = []string{"cannot be reached", "is not set in this task worker's environment"}

// TestChecksInsideInfrahub proves fylgja-step as Infrahub runs it (FR-029, R-18): the tree's
// check, imported from a registration of the test's own, runs in the pipeline of a draft
// proposed change; with two marks it concludes success, its message the plan's text with its
// four stages, three steps and the branch point's contract.node.missing; with a mark made
// stale it concludes failure naming stage.artifact.stale and the device. Where the task
// workers reach no server, it says so and skips.
func TestChecksInsideInfrahub(t *testing.T) {
	c, err := testsupport.NewClient()
	if err != nil {
		t.Skipf("contract tests need a running Infrahub: %v", err)
	}
	if _, err := testsupport.BridgeAddress(); err != nil {
		t.Skipf("the checks are served from the Docker bridge, where Infrahub's task workers fetch them, and Docker reports none: %v", err)
	}
	t.Cleanup(func() { nothingLeft(t, c) })

	// 2. The tree's checks and queries, registered under test-only names.
	name := fmt.Sprintf("%s%d", RepositoryPrefix, os.Getpid())
	location, stop, err := testsupport.ServeRepository(scratchRepository(t, name))
	if err != nil {
		t.Fatalf("serving the checks: %v", err)
	}
	t.Cleanup(stop)

	// 3. Registered, imported, and fetched by both task workers before any branch is made:
	// a branch sees the definitions main held at its creation (research §1.5).
	started := time.Now()
	if _, err := c.EnsureReadOnlyRepository(name, location, "main"); err != nil {
		t.Fatalf("registering %s: %v", name, err)
	}
	t.Cleanup(func() {
		if err := c.DeleteRepository(name); err != nil {
			t.Errorf("deleting the registration %s: %v", name, err)
		}
	})
	if _, err := c.AwaitImport(name, importWait); err != nil {
		t.Fatalf("importing %s: %v", name, err)
	}
	awaitRegistration(t, c, name, testDefinitions(t))
	t.Logf("registration %s at %s imported in %.0fs", name, location, time.Since(started).Seconds())
	time.Sleep(fetchWait)

	// 4. A branch made after the import, a draft, and two marks.
	branch := seededBranch(t, c)
	started = time.Now()
	id, err := c.OpenProposedChange(branch, true)
	if err != nil {
		t.Fatalf("opening a proposed change on %s: %v", branch, err)
	}
	t.Logf("draft proposed change %s on %s, its pipeline concluded after %.0fs", id, branch, time.Since(started).Seconds())
	// The draft's creation ran the checks; they conclude after the rest of the pipeline, so
	// a re-run is asked for only once this run has ended and can be told from it.
	created := awaitUserCheck(t, c, id, TestStepCheck)
	reached(t, created)
	if created.Conclusion != "success" {
		t.Errorf("at the draft's creation %s concluded %q, want success: the plan of the branch point and the head:\n%s",
			TestStepCheck, created.Conclusion, created.Message)
	}
	if _, _, err := c.MarkStage(id, "seeded", "", "seeded"); err != nil {
		t.Fatalf("marking seeded: %v", err)
	}
	before := deviceChecksums(t, c, branch)
	if err := c.SeedThirdLink(branch); err != nil {
		t.Fatalf("adding the third link: %v", err)
	}
	awaitMoved(t, c, branch, before, "n1", "n3")
	if _, _, err := c.MarkStage(id, "third-link", "", "third link"); err != nil {
		t.Fatalf("marking third-link: %v", err)
	}

	// 5. The plan passes: the branch point's refusal for want of a network on main excepted.
	step := rerun(t, c, id)
	reached(t, step)
	if step.Conclusion != "success" {
		t.Errorf("%s concluded %q, want success:\n%s", TestStepCheck, step.Conclusion, step.Message)
	}
	if !strings.Contains(step.Message, "(4 stages)") {
		t.Errorf("%s's message does not name four stages:\n%s", TestStepCheck, step.Message)
	}
	for _, label := range []string{stages.LabelBranchPoint, "seeded", "third-link", stages.LabelHead} {
		if !strings.Contains(step.Message, branch+"/"+label+":") {
			t.Errorf("%s's message has no line for stage %s/%s:\n%s", TestStepCheck, branch, label, step.Message)
		}
	}
	if n := len(regexp.MustCompile(`(?m)^step `).FindAllString(step.Message, -1)); n != 3 {
		t.Errorf("%s's message has %d step lines, want 3:\n%s", TestStepCheck, n, step.Message)
	}
	if !strings.Contains(step.Message, findings.RuleContractNodeMissing) {
		t.Errorf("%s's message does not carry the branch point's %s:\n%s", TestStepCheck, findings.RuleContractNodeMissing, step.Message)
	}

	// 6. A mark made stale: an intent change with no generate, then a mark.
	if err := c.SetDeviceRole(branch, "n1", "stale-role"); err != nil {
		t.Fatalf("changing n1's role: %v", err)
	}
	if _, _, err := c.MarkStage(id, "role-stale", "", "n1's role, not rendered"); err != nil {
		t.Fatalf("marking role-stale: %v", err)
	}
	step = rerun(t, c, id)
	reached(t, step)
	if step.Conclusion != "failure" {
		t.Errorf("with a stale mark %s concluded %q, want failure:\n%s", TestStepCheck, step.Conclusion, step.Message)
	}
	stale := regexp.MustCompile(`(?m)^.*` + regexp.QuoteMeta(findings.RuleStageArtifactStale) + `.* n1: .*$`)
	if !stale.MatchString(step.Message) {
		t.Errorf("%s's message names no %s on n1:\n%s", TestStepCheck, findings.RuleStageArtifactStale, step.Message)
	}
}

// repoPath is a path under the repository's root.
func repoPath(elem ...string) string {
	return filepath.Join(append([]string{"..", ".."}, elem...)...)
}

// definition is one check definition as .infrahub.yml declares it.
type definition struct {
	Name      string `yaml:"name"`
	FilePath  string `yaml:"file_path"`
	ClassName string `yaml:"class_name"`
}

// registration is what .infrahub.yml declares of the checks.
type registration struct {
	Queries []struct {
		Name     string `yaml:"name"`
		FilePath string `yaml:"file_path"`
	} `yaml:"queries"`
	CheckDefinitions []definition `yaml:"check_definitions"`
}

// treeRegistration reads the tree's .infrahub.yml.
func treeRegistration(t *testing.T) registration {
	t.Helper()
	raw, err := os.ReadFile(repoPath(".infrahub.yml"))
	if err != nil {
		t.Fatal(err)
	}
	var reg registration
	if err := yaml.Unmarshal(raw, &reg); err != nil {
		t.Fatalf("parsing .infrahub.yml: %v", err)
	}
	return reg
}

// testDefinitions are the test-only names of the checks the tree registers, each refused
// unless TestNames maps it.
func testDefinitions(t *testing.T) []string {
	t.Helper()
	var out []string
	for _, d := range treeRegistration(t).CheckDefinitions {
		renamed, ok := TestNames[d.Name]
		if !ok {
			t.Fatalf(".infrahub.yml registers check %s, which TestNames does not rename", d.Name)
		}
		out = append(out, renamed)
	}
	return out
}

// scratchRepository lays out what the test serves, in a directory named name: the tree's
// infrahub/checks/ and infrahub/queries/, each check's class rewritten to bind TestQuery, and
// a .infrahub.yml of its own declaring that query and the tree's checks under their test-only
// names, the tree's files and classes, so neither the artifact definition nor a name of the
// registration fylgja's is registered twice (research §5.3).
func scratchRepository(t *testing.T, name string) string {
	t.Helper()
	dir := filepath.Join(t.TempDir(), name)
	for _, sub := range []string{"infrahub/checks", "infrahub/queries"} {
		copyTree(t, repoPath(sub), filepath.Join(dir, sub))
	}
	reg := treeRegistration(t)
	queryFile := ""
	for _, q := range reg.Queries {
		if q.Name == Query {
			queryFile = q.FilePath
		}
	}
	if queryFile == "" {
		t.Fatalf(".infrahub.yml registers no query %s", Query)
	}
	binding := regexp.MustCompile(`(?m)^(\s+query = )"` + regexp.QuoteMeta(Query) + `"$`)
	var yml strings.Builder
	fmt.Fprintf(&yml, "---\n# The tree's checks, under test-only names (internal/checks).\nqueries:\n  - name: %s\n    file_path: %s\n",
		TestQuery, queryFile)
	yml.WriteString("check_definitions:\n")
	for _, d := range reg.CheckDefinitions {
		path := filepath.Join(dir, d.FilePath)
		src, err := os.ReadFile(path)
		if err != nil {
			t.Fatalf("check %s: %v", d.Name, err)
		}
		if n := len(binding.FindAllIndex(src, -1)); n != 1 {
			t.Fatalf("check %s: %s binds query %s %d times, want once", d.Name, d.FilePath, Query, n)
		}
		if err := os.WriteFile(path, binding.ReplaceAll(src, []byte(`${1}"`+TestQuery+`"`)), 0o644); err != nil {
			t.Fatal(err)
		}
		fmt.Fprintf(&yml, "  - name: %s\n    file_path: %s\n    class_name: %s\n", TestNames[d.Name], d.FilePath, d.ClassName)
	}
	if err := os.WriteFile(filepath.Join(dir, ".infrahub.yml"), []byte(yml.String()), 0o644); err != nil {
		t.Fatal(err)
	}
	return dir
}

// copyTree copies a directory's regular files, leaving out Python's bytecode caches.
func copyTree(t *testing.T, src, dst string) {
	t.Helper()
	err := fs.WalkDir(os.DirFS(src), ".", func(path string, d fs.DirEntry, err error) error {
		switch {
		case err != nil:
			return err
		case d.IsDir() && d.Name() == "__pycache__":
			return fs.SkipDir
		case d.IsDir():
			return os.MkdirAll(filepath.Join(dst, path), 0o755)
		case !d.Type().IsRegular():
			return nil
		}
		b, err := os.ReadFile(filepath.Join(src, path))
		if err != nil {
			return err
		}
		return os.WriteFile(filepath.Join(dst, path), b, 0o644)
	})
	if err != nil {
		t.Fatalf("copying %s: %v", src, err)
	}
}

// awaitRegistration waits until main holds each of names as a check definition and the query
// TestQuery, failing at once when the registration's import has failed: Infrahub then holds
// none of it (research §5.3).
func awaitRegistration(t *testing.T, c *testsupport.Client, repository string, names []string) {
	t.Helper()
	deadline := time.Now().Add(importWait)
	for {
		defs, err := c.CheckDefinitions()
		if err != nil {
			t.Fatal(err)
		}
		var have []string
		for _, d := range defs {
			if slices.Contains(names, d.Name) {
				have = append(have, fmt.Sprintf("%s (timeout %d)", d.Name, d.Timeout))
			}
		}
		query := countOf(t, c, fmt.Sprintf(`CoreGraphQLQuery(name__value: %q)`, TestQuery))
		if len(have) == len(names) && query == 1 {
			t.Logf("main holds %s and the query %s", strings.Join(have, ", "), TestQuery)
			return
		}
		status := syncStatus(t, c, repository)
		if status == "error-import" || time.Now().After(deadline) {
			t.Fatalf("registration %s is %s: main holds %v of the definitions %v and %d query %s",
				repository, status, have, names, query, TestQuery)
		}
		time.Sleep(2 * time.Second)
	}
}

// syncStatus is a registration's sync_status on main.
func syncStatus(t *testing.T, c *testsupport.Client, repository string) string {
	t.Helper()
	raw, err := c.GraphQL("main", fmt.Sprintf(
		`{ CoreReadOnlyRepository(name__value: %q) { edges { node { sync_status { value } } } } }`, repository))
	if err != nil {
		t.Fatal(err)
	}
	var r struct {
		R struct {
			Edges []struct {
				Node struct {
					SyncStatus struct {
						Value string `json:"value"`
					} `json:"sync_status"`
				} `json:"node"`
			} `json:"edges"`
		} `json:"CoreReadOnlyRepository"`
	}
	if err := json.Unmarshal(raw, &r); err != nil || len(r.R.Edges) != 1 {
		t.Fatalf("reading registration %s: %v (%s)", repository, err, raw)
	}
	return r.R.Edges[0].Node.SyncStatus.Value
}

// countOf is a kind's count on main under a filter, the filter written with the kind.
func countOf(t *testing.T, c *testsupport.Client, filtered string) int {
	t.Helper()
	raw, err := c.GraphQL("main", fmt.Sprintf(`{ %s { count } }`, filtered))
	if err != nil {
		t.Fatal(err)
	}
	var r map[string]struct {
		Count int `json:"count"`
	}
	if err := json.Unmarshal(raw, &r); err != nil || len(r) != 1 {
		t.Fatalf("counting %s: %v (%s)", filtered, err, raw)
	}
	for _, v := range r {
		return v.Count
	}
	return 0
}

// seededBranch makes a branch fylgja-test-ck-<ts>-<n>, loads the schema and seeds the
// three-node fixture with its artifacts rendered. When the test ends it is deleted with what
// hangs on it, stages first, then proposed changes (their comments and validators with them,
// research §1.6), then the branch.
func seededBranch(t *testing.T, c *testsupport.Client) string {
	t.Helper()
	name := fmt.Sprintf("%sck-%d-%d", testsupport.TestBranchPrefix, time.Now().Unix(), rand.Intn(9999))
	if err := c.CreateBranch(name); err != nil {
		t.Fatalf("creating branch: %v", err)
	}
	t.Cleanup(func() {
		if err := c.DeleteTestBranch(name); err != nil {
			t.Errorf("deleting branch %s and what hangs on it: %v", name, err)
		}
	})
	started := time.Now()
	if err := c.LoadSchema(name, repoPath("schema")); err != nil {
		t.Fatalf("loading schema: %v", err)
	}
	if err := c.SeedThreeNode(name); err != nil {
		t.Fatalf("seeding: %v", err)
	}
	t.Logf("branch %s seeded in %.0fs", name, time.Since(started).Seconds())
	return name
}

// awaitUserCheck waits until the proposed change's check name has concluded, its validator
// completed, and returns it. A check Infrahub timed out leaves its validator in_progress, and
// the bound names that.
func awaitUserCheck(t *testing.T, c *testsupport.Client, id, name string) testsupport.UserCheckRow {
	t.Helper()
	deadline := time.Now().Add(userCheckWait)
	for {
		rows, err := c.UserChecksOf(id)
		if err != nil {
			t.Fatal(err)
		}
		for _, r := range rows {
			if r.Name == name && r.ValidatorState == "completed" && r.Conclusion != "" {
				return r
			}
		}
		if time.Now().After(deadline) {
			t.Fatalf("proposed change %s: %s did not conclude within %s; its user checks read %+v", id, name, userCheckWait, rows)
		}
		time.Sleep(5 * time.Second)
	}
}

// rerun re-runs the proposed change's user checks and returns fylgja-test-step's.
func rerun(t *testing.T, c *testsupport.Client, id string) testsupport.UserCheckRow {
	t.Helper()
	started := time.Now()
	rows, err := c.RunUserChecks(id, userCheckWait)
	if err != nil {
		t.Fatalf("re-running the user checks: %v", err)
	}
	for _, r := range rows {
		if r.Name == TestStepCheck {
			t.Logf("%s re-run: %s after %.0fs, message %d characters", r.Name, r.Conclusion, time.Since(started).Seconds(), len(r.Message))
			return r
		}
	}
	t.Fatalf("the re-run's user checks are %+v; %s is not among them: was the branch made before the import?", rows, TestStepCheck)
	return testsupport.UserCheckRow{}
}

// reached skips the test when the check says its task worker reaches no server: CI's
// contract job runs none, and the operator's server on the bridge is what the development
// host's task workers reach (D-050).
func reached(t *testing.T, row testsupport.UserCheckRow) {
	t.Helper()
	for _, s := range unreached {
		if strings.Contains(row.Message, s) {
			t.Skipf("Infrahub's task workers reach no Fylgja server here, as on CI's contract job, which runs none; "+
				"on the development host, start the server on the bridge (CLAUDE.md). %s concluded %s:\n%s",
				row.Name, row.Conclusion, row.Message)
		}
	}
}

// deviceChecksums are each device's device-config checksum on branch, as Infrahub lists it
// now: a device whose artifact is not Ready is not listed.
func deviceChecksums(t *testing.T, c *testsupport.Client, branch string) map[string]string {
	t.Helper()
	raw, err := c.GraphQL(branch, `{ FylgjaDevice { edges { node { name { value }
		... on CoreArtifactTarget { artifacts { edges { node { status { value } checksum { value }
			definition { node { ... on CoreArtifactDefinition { artifact_name { value } } } } } } } } } } } }`)
	if err != nil {
		t.Fatalf("asking Infrahub for the artifacts on %s: %v", branch, err)
	}
	type value struct {
		Value string `json:"value"`
	}
	var r struct {
		D struct {
			Edges []struct {
				Node struct {
					Name      value `json:"name"`
					Artifacts struct {
						Edges []struct {
							Node struct {
								Status     value `json:"status"`
								Checksum   value `json:"checksum"`
								Definition struct {
									Node struct {
										ArtifactName value `json:"artifact_name"`
									} `json:"node"`
								} `json:"definition"`
							} `json:"node"`
						} `json:"edges"`
					} `json:"artifacts"`
				} `json:"node"`
			} `json:"edges"`
		} `json:"FylgjaDevice"`
	}
	if err := json.Unmarshal(raw, &r); err != nil {
		t.Fatal(err)
	}
	out := map[string]string{}
	for _, d := range r.D.Edges {
		for _, a := range d.Node.Artifacts.Edges {
			if a.Node.Definition.Node.ArtifactName.Value == testsupport.ArtifactName && a.Node.Status.Value == "Ready" {
				out[d.Node.Name.Value] = a.Node.Checksum.Value
			}
		}
	}
	return out
}

// awaitMoved waits until each device's checksum differs from before: a generate returns
// before an intent change's rewrite lands, and a mark made earlier would be stale.
func awaitMoved(t *testing.T, c *testsupport.Client, branch string, before map[string]string, devices ...string) {
	t.Helper()
	deadline := time.Now().Add(checksumWait)
	for {
		now := deviceChecksums(t, c, branch)
		moved := true
		for _, d := range devices {
			if now[d] == "" || now[d] == before[d] {
				moved = false
			}
		}
		if moved {
			return
		}
		if time.Now().After(deadline) {
			t.Fatalf("the artifacts of %v on %s did not move from %v within %s: %v", devices, branch, before, checksumWait, now)
		}
		time.Sleep(time.Second)
	}
}

// nothingLeft fails the test when anything of a test's registration remains on main once
// its cleanups have run: a fylgja-test- repository, check definition or the query TestQuery.
func nothingLeft(t *testing.T, c *testsupport.Client) {
	t.Helper()
	raw, err := c.GraphQL("main", `{ CoreReadOnlyRepository { edges { node { name { value } } } } }`)
	if err != nil {
		t.Errorf("reading the registrations after the test: %v", err)
		return
	}
	var r struct {
		R struct {
			Edges []struct {
				Node struct {
					Name struct {
						Value string `json:"value"`
					} `json:"name"`
				} `json:"node"`
			} `json:"edges"`
		} `json:"CoreReadOnlyRepository"`
	}
	if err := json.Unmarshal(raw, &r); err != nil {
		t.Errorf("reading the registrations after the test: %v", err)
		return
	}
	for _, e := range r.R.Edges {
		if strings.HasPrefix(e.Node.Name.Value, testsupport.TestBranchPrefix) {
			t.Errorf("after the test the registration %s remains", e.Node.Name.Value)
		}
	}
	defs, err := c.CheckDefinitions()
	if err != nil {
		t.Errorf("reading the check definitions after the test: %v", err)
		return
	}
	for _, d := range defs {
		if strings.HasPrefix(d.Name, testsupport.TestBranchPrefix) {
			t.Errorf("after the test the check definition %s remains", d.Name)
		}
	}
	if n := countOf(t, c, fmt.Sprintf(`CoreGraphQLQuery(name__value: %q)`, TestQuery)); n != 0 {
		t.Errorf("after the test main holds %d query %s", n, TestQuery)
	}
}
