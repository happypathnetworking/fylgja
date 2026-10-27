package cli

import (
	"encoding/json"
	"os"
	"regexp"
	"slices"
	"sort"
	"strings"
	"testing"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
)

// The stages stage list and stage plan are tried on (014). change-1 is the fixture with its
// last link removed and every artifact unchanged, so its branch point (main, the fixture)
// steps to its marks by that link; cabled's at is given, live's is the time its label was
// written, and both are served out of order, since the commands order them. change-2 is a
// draft holding no mark, and one stage's proposed change is gone.
const (
	lessLink = "change-1"
	cabledAt = "2026-10-16T08:30:00.000000+00:00"
)

func stagesInfrahub(t *testing.T) *fakeInfrahub {
	t.Helper()
	f := newFakeInfrahub(t)
	f.branches[lessLink] = withoutLastLink(t, lessLink)
	f.change("pc-1", lessLink, mark("st-live", "live", "", "the leaf live"), mark("st-cabled", "cabled", cabledAt, "the leaf cabled"))
	f.change("pc-2", "change-2").Draft = true
	f.orphans = []fakeStage{mark("st-old", "old", "", "")}
	return f
}

func withoutLastLink(t *testing.T, name string) *ctm.CTM {
	t.Helper()
	c, err := ctm.Load(repoPath("testdata", "ctm", "three-node.json"))
	if err != nil {
		t.Fatal(err)
	}
	c.Envelope.Branch = name
	gone := c.Links[len(c.Links)-1].ID
	c.Links = c.Links[:len(c.Links)-1]
	for i := range c.Devices {
		for j := range c.Devices[i].Interfaces {
			if c.Devices[i].Interfaces[j].Link == gone {
				c.Devices[i].Interfaces[j].Link = ""
			}
		}
	}
	return c
}

// runStage runs `fylgja stage <args>` through the command line, as an operator would, and
// returns its exit status and what it wrote on stdout and stderr.
func runStage(t *testing.T, args ...string) (code int, stdout, stderr string) {
	t.Helper()
	return runRoot(t, append([]string{"stage"}, args...)...)
}

// runRoot runs `fylgja <args>` with the stage, twin, intent and schema nouns beside each
// other, so a noun that is gone is cobra's own unknown command.
func runRoot(t *testing.T, args ...string) (code int, stdout, stderr string) {
	t.Helper()
	opts := &options{}
	root := &cobra.Command{Use: "fylgja", SilenceUsage: true, SilenceErrors: true}
	root.PersistentFlags().BoolVar(&opts.asJSON, "json", false, "")
	root.AddCommand(newStageCmd(opts), newTwinCmd(opts), newIntentCmd(opts), newSchemaCmd(opts))
	root.SetArgs(args)
	stderr = captureStderr(t, func() {
		stdout = captureStdout(t, func() {
			cmd, err := root.ExecuteC()
			code = report(opts, cmd, err)
		})
	})
	return code, stdout, stderr
}

// stageDoc is runStage under --json: the one findings document on stdout, which must
// satisfy the newest contracts, and nothing on stderr.
func stageDoc(t *testing.T, args ...string) (int, *findings.Document, string) {
	t.Helper()
	code, stdout, stderr := runStage(t, append(args, "--json")...)
	if stderr != "" {
		t.Errorf("%v --json wrote on stderr: %s", args, stderr)
	}
	var doc findings.Document
	if err := json.Unmarshal([]byte(stdout), &doc); err != nil {
		t.Fatalf("%v: stdout is not one findings document: %v\n%s", args, err, stdout)
	}
	validateM10Document(t, &doc)
	return code, &doc, stdout
}

// mustQuoteNoContent fails when any output carries a line of configuration of ten
// characters or more, the marker or the credential.
func mustQuoteNoContent(t *testing.T, f *fakeInfrahub, outputs ...string) {
	t.Helper()
	lines := []string{marker}
	for _, d := range f.fixture.Devices {
		for _, l := range strings.Split(d.Artifact.Content, "\n") {
			if l = strings.TrimSpace(l); len(l) >= 10 {
				lines = append(lines, l)
			}
		}
	}
	for _, out := range outputs {
		if strings.Contains(out, fakeToken) {
			t.Errorf("an output carries the credential:\n%s", out)
		}
		for _, l := range lines {
			if strings.Contains(out, l) {
				t.Errorf("an output quotes configuration %q:\n%s", l, out)
			}
		}
	}
}

var bundleIDRE = regexp.MustCompile(`^[0-9a-f]{64}$`)

// storedBundles is the ids the store holds, none with a CTM beside it: the sidecar is
// retired (018).
func storedBundles(t *testing.T, bundles string) []string {
	t.Helper()
	entries, err := os.ReadDir(bundles)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		t.Fatal(err)
	}
	var ids []string
	for _, e := range entries {
		if e.IsDir() && bundleIDRE.MatchString(e.Name()) {
			ids = append(ids, e.Name())
			if _, err := os.Stat(bundles + "/" + e.Name() + ".ctm.json"); !os.IsNotExist(err) {
				t.Errorf("bundle %s is filed with a CTM beside it (%v); the sidecar is retired", e.Name(), err)
			}
		}
	}
	sort.Strings(ids)
	return ids
}

func sortedCopy(ids ...string) []string {
	out := slices.Clone(ids)
	sort.Strings(out)
	return out
}

// refs is every listed row's reference, in order.
func refs(doc *findings.Document) []string {
	var out []string
	if doc.Stages != nil {
		for _, r := range doc.Stages.Rows {
			out = append(out, r.Ref)
		}
	}
	return out
}

// stage plan reads and compiles each stage in order, files each bundle beside its CTM, and
// prints each stage's resolution and the step between each pair, by checksum and never by
// content: the branch point steps to cabled by the removed link, and the rest are equal.
func TestStagePlan(t *testing.T) {
	paths := useStateRoot(t)
	useService(t, nil)
	f := stagesInfrahub(t)
	f.start()

	code, stdout, stderr := runStage(t, "plan", "--branch", lessLink)
	for _, want := range []string{
		`proposed change "change pc-1" (pc-1) on branch change-1 → main (4 stages)`,
		`change-1/branch-point: main at ` + fakeBranchedFrom + ` (branch point)`,
		`change-1/cabled: branch change-1 at ` + cabledAt + ` (given), "the leaf cabled"`,
		`change-1/head: branch change-1 at ` + fakeHeadAt + ` (head)`,
		"  bundle_id ", "  read: ",
	} {
		if !strings.Contains(stdout+stderr, want) {
			t.Errorf("stage plan lacks %q:\n%s%s", want, stdout, stderr)
		}
	}
	if code != findings.ExitOK {
		t.Errorf("exit %d, want 0:\n%s%s", code, stdout, stderr)
	}

	code, doc, raw := stageDoc(t, "plan", "--branch", lessLink)
	if code != findings.ExitOK || doc.Plan == nil || doc.Plan.Branch != lessLink || doc.Plan.ProposedChange.ID != "pc-1" ||
		len(doc.Plan.Stages) != 4 || len(doc.Plan.Steps) != 3 {
		t.Fatalf("exit %d, %s", code, raw)
	}
	var ids []string
	for _, st := range doc.Plan.Stages {
		if st.BundleID == nil {
			t.Errorf("stage %s compiled to no bundle", st.Ref)
			continue
		}
		if !slices.Contains(ids, *st.BundleID) {
			ids = append(ids, *st.BundleID)
		}
	}
	// Two ats of one intent differ by provenance, so every stage compiles to its own id; the
	// step from the branch point removes the link, and the two after it are unchanged but for
	// provenance.
	if len(ids) != 4 {
		t.Errorf("bundles %v; want one per stage, each at its own at", ids)
	}
	for _, want := range []string{
		"step change-1/branch-point → change-1/cabled (",
		"step change-1/cabled → change-1/live (",
		"step change-1/live → change-1/head (",
	} {
		i := strings.Index(stdout, want)
		if i < 0 {
			t.Errorf("stage plan lacks %q:\n%s", want, stdout)
			continue
		}
		line, _, _ := strings.Cut(stdout[i:], "\n")
		if unchanged := strings.HasSuffix(line, ": unchanged; the ids differ by provenance alone"); unchanged == strings.Contains(want, "branch-point") {
			t.Errorf("%s; want only the step from the branch point to change anything", line)
		}
	}
	if got := storedBundles(t, paths.Bundles); !slices.Equal(got, sortedCopy(ids...)) {
		t.Errorf("the store holds %v; want %v", got, sortedCopy(ids...))
	}
	mustQuoteNoContent(t, f, stdout, stderr, raw)
}

// A stage refused at resolution is reported under its reference with its rule, and the plan
// goes on to the stages after it.
func TestStagePlanRefusedInTheMiddle(t *testing.T) {
	useStateRoot(t)
	useService(t, nil)
	f := stagesInfrahub(t)
	f.changes[0].Stages = append(f.changes[0].Stages, mark("st-late", "late", "2099-01-01T00:00:00.000000+00:00", ""))
	f.start()

	code, stdout, stderr := runStage(t, "plan", "--branch", lessLink)
	if !strings.Contains(stdout+stderr, "change-1/late: refused ("+findings.RuleStageAtUnresolved+")") ||
		!strings.Contains(stdout+stderr, "change-1/head: branch change-1") {
		t.Errorf("exit %d:\n%s%s", code, stdout, stderr)
	}
	_, doc, raw := stageDoc(t, "plan", "--branch", lessLink)
	if doc.Plan == nil || len(doc.Plan.Stages) != 5 || doc.Plan.Stages[3].Ref != "change-1/late" ||
		doc.Plan.Stages[3].BundleID != nil || !carriesRule(doc.Plan.Stages[3].Findings, findings.RuleStageAtUnresolved) ||
		doc.Plan.Stages[4].BundleID == nil {
		t.Errorf("%s", raw)
	}
}

// Before any connection, a --branch that is not a branch is stage.ref.invalid, exit 2 with
// Infrahub never asked (stage plan's are stage_plan_test.go's); the waypoint noun is gone,
// so `fylgja waypoint list` is cobra's unknown command, exit 2.
func TestStageRefusedBeforeAnyConnection(t *testing.T) {
	for _, c := range []struct {
		name string
		args []string
		rule string
	}{
		{"list --branch=", []string{"stage", "list", "--branch="}, findings.RuleStageRefInvalid},
		{"list a spaced branch", []string{"stage", "list", "--branch", "a b"}, findings.RuleStageRefInvalid},
		{"list a reference for a branch", []string{"stage", "list", "--branch", "a/b"}, findings.RuleStageRefInvalid},
	} {
		t.Run(c.name, func(t *testing.T) {
			useStateRoot(t)
			useService(t, nil)
			f := stagesInfrahub(t)
			f.start()

			code, doc := executeStage(t, c.args...)
			if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0].Rule != c.rule {
				t.Errorf("exit %d, findings %+v; want 2 with %s", code, doc.Findings, c.rule)
			}
			if doc.Findings[0].Step != findings.StepStart {
				t.Errorf("step %q, want start", doc.Findings[0].Step)
			}
			if got := f.requests(); len(got) != 0 {
				t.Errorf("Infrahub was asked %+v before the flags were refused", got)
			}
			validateM10Document(t, doc)
		})
	}
	t.Run("waypoint list", func(t *testing.T) {
		useStateRoot(t)
		code, _, stderr := runRoot(t, "waypoint", "list")
		if code != findings.ExitError || !strings.Contains(stderr, `unknown command "waypoint"`) {
			t.Errorf("exit %d, stderr %q; want 2 with cobra's unknown command", code, stderr)
		}
	})
}

// executeStage is runRoot under --json, decoded.
func executeStage(t *testing.T, args ...string) (int, *findings.Document) {
	t.Helper()
	code, stdout, _ := runRoot(t, append(args, "--json")...)
	var doc findings.Document
	if err := json.Unmarshal([]byte(stdout), &doc); err != nil {
		t.Fatalf("%v: stdout is not one findings document: %v\n%s", args, err, stdout)
	}
	return code, &doc
}
