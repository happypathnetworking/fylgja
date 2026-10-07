package cli

import (
	"bytes"
	"crypto/md5"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"slices"
	"sort"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/intent"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
)

// The series waypoint list and waypoint plan are tried on. Every
// at is in the past, so no clock refuses one. demo is contracts/cli.md's shape: two times of
// the fixture branch, then change-1, the fixture with its last link removed and every
// artifact unchanged. mid holds a waypoint refused at resolution and one whose branch is
// gone between two that compile. back runs backwards in time.
const (
	demo1At     = "2026-09-01T09:00:00.000000+00:00"
	demo3At     = "2026-09-21T15:20:44.000000+00:00"
	lessLink    = "change-1"
	midNineAt   = "2026-09-02T12:00:00.123456789Z"
	midGoneAt   = "2026-09-03T00:00:00.000000+00:00"
	backFirstAt = "2026-09-20T00:00:00Z"
)

func seriesInfrahub(t *testing.T) *fakeInfrahub {
	t.Helper()
	f := newFakeInfrahub(t)
	f.branches = map[string]*ctm.CTM{lessLink: withoutLastLink(t, lessLink)}
	// Listed out of order: the commands sort.
	f.waypoint("wp-demo-3", "demo", 3, lessLink, demo3At, "", "after the second")
	f.waypoint("wp-mid-4", "mid", 4, "fylgja-fixture", demoWrittenAt, fixtureAt, "")
	f.waypoint("wp-demo-1", "demo", 1, "fylgja-fixture", demo1At, "", "before the change")
	f.waypoint("wp-back-2", "back", 2, "fylgja-fixture", demoWrittenAt, fixtureAt, "")
	f.waypoint("wp-mid-1", "mid", 1, "fylgja-fixture", "2026-09-02T00:00:00.000000+00:00", "", "")
	f.waypoint("wp-demo-2", "demo", 2, "fylgja-fixture", demoWrittenAt, fixtureAt, "after the first cut-over")
	f.waypoint("wp-mid-2", "mid", 2, "fylgja-fixture", demoWrittenAt, midNineAt, "")
	f.waypoint("wp-mid-3", "mid", 3, "gone", midGoneAt, "", "")
	f.waypoint("wp-back-1", "back", 1, "fylgja-fixture", demoWrittenAt, backFirstAt, "")
	return f
}

// withoutLastLink is the fixture read from branch name with its last link, n2:ethernet-1/2 —
// n3:ethernet-1/1, removed at both ends: a topology change no artifact follows (D-028's
// trap).
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

// runWaypoint runs `fylgja waypoint <args>` through the command line, as an operator would,
// and returns its exit status and what it wrote on stdout and stderr.
func runWaypoint(t *testing.T, args ...string) (code int, stdout, stderr string) {
	t.Helper()
	opts := &options{}
	root := &cobra.Command{Use: "fylgja", SilenceUsage: true, SilenceErrors: true}
	root.PersistentFlags().BoolVar(&opts.asJSON, "json", false, "")
	root.AddCommand(newWaypointCmd(opts))
	root.SetArgs(append([]string{"waypoint"}, args...))
	stderr = captureStderr(t, func() {
		stdout = captureStdout(t, func() {
			cmd, err := root.ExecuteC()
			code = report(opts, cmd, err)
		})
	})
	return code, stdout, stderr
}

// waypointDoc is runWaypoint under --json: the one findings document on stdout, which must
// satisfy this feature's contracts, and nothing on stderr.
func waypointDoc(t *testing.T, args ...string) (int, *findings.Document, string) {
	t.Helper()
	code, stdout, stderr := runWaypoint(t, append(args, "--json")...)
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

// contentLines is every line of configuration the plan must never quote: each line of ten
// characters or more of every artifact the fake serves and of every bootstrap filed in the
// store, and the marker (the marker proof's shape).
func contentLines(t *testing.T, f *fakeInfrahub, bundles string) []string {
	t.Helper()
	lines := []string{marker}
	add := func(text string) {
		for _, l := range strings.Split(text, "\n") {
			if l = strings.TrimSpace(l); len(l) >= 10 {
				lines = append(lines, l)
			}
		}
	}
	for _, d := range f.fixture.Devices {
		add(d.Artifact.Content)
	}
	boots, err := filepath.Glob(filepath.Join(bundles, "*", "configs", "*.cli"))
	if err != nil {
		t.Fatal(err)
	}
	if len(boots) == 0 {
		t.Fatalf("no bootstrap filed under %s", bundles)
	}
	for _, b := range boots {
		raw, err := os.ReadFile(b)
		if err != nil {
			t.Fatal(err)
		}
		add(string(raw))
	}
	return lines
}

// mustQuoteNoContent fails when any output carries a line of configuration or the
// credential.
func mustQuoteNoContent(t *testing.T, lines []string, outputs ...string) {
	t.Helper()
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

// storedBundles is the ids the store holds, each with its CTM beside it.
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
			if _, err := os.Stat(filepath.Join(bundles, e.Name()+".ctm.json")); err != nil {
				t.Errorf("bundle %s is filed with no CTM beside it: %v", e.Name(), err)
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

// branchReads is what a command asked of Infrahub beyond the default branch's schema and
// waypoints, which every listing asks: a branch's schema, GraphQL or an artifact.
func branchReads(f *fakeInfrahub) []fakeRequest {
	var out []fakeRequest
	for _, r := range f.requests() {
		if r.Query != "" || strings.HasPrefix(r.Path, "/graphql/") || strings.HasPrefix(r.Path, "/api/storage/") {
			out = append(out, r)
		}
	}
	return out
}

// Every waypoint, listed by series then sequence with the reference each resolves to and
// where its at came from, each series' columns aligned; the future and nine-digit ats shown
// as written, refused nowhere; a series running backwards warned of, exit 0. No branch is
// read and no workflow service dialled.
func TestWaypointList(t *testing.T) {
	useStateRoot(t)
	useService(t, nil)
	f := seriesInfrahub(t)
	// A two-digit sequence: the references of one series pad to the longest.
	f.waypoint("wp-mid-12", "mid", 12, "fylgja-fixture", demoWrittenAt, fixtureAt, "twelfth")
	f.start()

	code, stdout, stderr := runWaypoint(t, "list")
	want := strings.Join([]string{
		"series back (2 waypoints)",
		`  back/1  branch fylgja-fixture  at 2026-09-20T00:00:00Z (given)  ""`,
		`  back/2  branch fylgja-fixture  at 2026-09-08T12:00:00Z (given)  ""`,
		"series demo (3 waypoints)",
		`  demo/1  branch fylgja-fixture  at 2026-09-01T09:00:00.000000+00:00 (written)  "before the change"`,
		`  demo/2  branch fylgja-fixture  at 2026-09-08T12:00:00Z (given)  "after the first cut-over"`,
		`  demo/3  branch change-1        at 2026-09-21T15:20:44.000000+00:00 (written)  "after the second"`,
		"series mid (5 waypoints)",
		`  mid/1   branch fylgja-fixture  at 2026-09-02T00:00:00.000000+00:00 (written)  ""`,
		`  mid/2   branch fylgja-fixture  at 2026-09-02T12:00:00.123456789Z (given)  ""`,
		`  mid/3   branch gone            at 2026-09-03T00:00:00.000000+00:00 (written)  ""`,
		`  mid/4   branch fylgja-fixture  at 2026-09-08T12:00:00Z (given)  ""`,
		`  mid/12  branch fylgja-fixture  at 2026-09-08T12:00:00Z (given)  "twelfth"`,
	}, "\n") + "\n"
	if code != findings.ExitOK || stdout != want {
		t.Errorf("exit %d, stdout\n%s\nwant 0 and\n%s", code, stdout, want)
	}
	reversed := "warning waypoint.time.reversed back/2: waypoint back/2 resolves to at 2026-09-08T12:00:00Z, " +
		"earlier than back/1's 2026-09-20T00:00:00Z; the order is the operator's and nothing is refused\n"
	if stderr != reversed+"1 finding(s): 0 rejection, 1 warning, 0 info\n" {
		t.Errorf("stderr\n%s\nwant the one warning", stderr)
	}

	code, doc, raw := waypointDoc(t, "list")
	if code != findings.ExitOK || doc.Operation != findings.OpWaypointList || doc.Status != findings.StatusOK ||
		doc.Subject != nil || doc.Waypoints == nil {
		t.Fatalf("exit %d, document %s", code, raw)
	}
	var refs []string
	for _, w := range doc.Waypoints.Waypoints {
		refs = append(refs, w.Series+"/"+strconv.Itoa(w.Sequence)+" "+w.At+" "+w.AtSource)
		if w.Twin {
			t.Errorf("%s/%d is marked with no record on the host", w.Series, w.Sequence)
		}
	}
	if want := []string{
		"back/1 " + backFirstAt + " given", "back/2 " + fixtureAt + " given",
		"demo/1 " + demo1At + " written", "demo/2 " + fixtureAt + " given", "demo/3 " + demo3At + " written",
		"mid/1 2026-09-02T00:00:00.000000+00:00 written", "mid/2 " + midNineAt + " given",
		"mid/3 " + midGoneAt + " written", "mid/4 " + fixtureAt + " given", "mid/12 " + fixtureAt + " given",
	}; !slices.Equal(refs, want) {
		t.Errorf("rows %v\nwant %v", refs, want)
	}
	if doc.Waypoints.Series != nil || doc.Waypoints.Record != nil || !strings.Contains(raw, `"series": null`) ||
		!strings.Contains(raw, `"record": null`) {
		t.Errorf("an unfiltered listing with no record carries series and record as null: %s", raw)
	}
	if len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleWaypointTimeReversed || doc.Findings[0].Step != "" {
		t.Errorf("findings %+v; want the one time.reversed warning, with no step", doc.Findings)
	}
	if got := branchReads(f); len(got) != 0 {
		t.Errorf("the list read a branch: %+v", got)
	}
	mustCarryNoToken(t, "the list", stdout, stderr, raw)

	// --series lists one series, and names it in the block.
	code, stdout, _ = runWaypoint(t, "list", "--series", "demo")
	if code != findings.ExitOK || !strings.HasPrefix(stdout, "series demo (3 waypoints)\n") || strings.Contains(stdout, "back/") {
		t.Errorf("--series demo: exit %d\n%s", code, stdout)
	}
	_, doc, _ = waypointDoc(t, "list", "--series", "demo")
	if doc.Waypoints.Series == nil || *doc.Waypoints.Series != "demo" || len(doc.Waypoints.Waypoints) != 3 || len(doc.Findings) != 0 {
		t.Errorf("--series demo: %+v, findings %+v", doc.Waypoints, doc.Findings)
	}
}

// planStep is what the plan tests read of a step's JSON (waypoints.schema.json, $defs/step).
type planStep struct {
	Unchanged bool `json:"unchanged"`
	Nodes     struct {
		Changed []struct {
			Node    string   `json:"node"`
			Reasons []string `json:"reasons"`
		} `json:"changed"`
	} `json:"nodes"`
	Links struct {
		Removed []struct {
			ID string `json:"id"`
		} `json:"removed"`
	} `json:"links"`
	Artifacts struct {
		Changed []any `json:"changed"`
	} `json:"artifacts"`
}

// A series planned: each waypoint read at its own reference, compiled and filed, printed as
// it goes with the step between each pair. Two times of one intent are unchanged though the
// ids differ; a link removed with no artifact regenerated reads as exactly that. The second
// waypoint, at the fixture's own at, is the golden bundle. Nothing quotes configuration, and
// no workflow service is dialled.
func TestWaypointPlan(t *testing.T) {
	paths := useStateRoot(t)
	useService(t, nil)
	f := seriesInfrahub(t)
	f.start()

	code, doc, raw := waypointDoc(t, "plan", "--series", "demo")
	if code != findings.ExitOK || doc.Operation != findings.OpWaypointPlan || doc.Status != findings.StatusOK ||
		doc.Plan == nil || len(doc.Plan.Waypoints) != 3 || len(doc.Plan.Steps) != 2 || len(doc.Findings) != 0 {
		t.Fatalf("exit %d, document %s", code, raw)
	}
	var ids []string
	for _, w := range doc.Plan.Waypoints {
		if w.BundleID == nil || w.Read == nil || len(w.Findings) != 0 {
			t.Fatalf("%s/%d did not compile: %s", w.Series, w.Sequence, raw)
		}
		ids = append(ids, *w.BundleID)
	}
	if ids[1] != fixtureBundleID {
		t.Errorf("demo/2, the fixture branch at the fixture's at, compiled to %s; want the golden %s", ids[1], fixtureBundleID)
	}
	if ids[0] == ids[1] || ids[1] == ids[2] {
		t.Errorf("ids %v: two ats of one intent differ by provenance", ids)
	}
	if w := doc.Plan.Waypoints[2]; w.Branch != lessLink || w.At != demo3At || w.AtSource != "written" || w.Read.Links != 2 {
		t.Errorf("demo/3: %+v", w)
	}
	var steps []planStep
	for _, raw := range doc.Plan.Steps {
		var one planStep
		if err := json.Unmarshal(raw, &one); err != nil {
			t.Fatal(err)
		}
		steps = append(steps, one)
	}
	if !steps[0].Unchanged || steps[1].Unchanged {
		t.Errorf("steps %+v: demo/1 → demo/2 is unchanged, demo/2 → demo/3 is not", steps)
	}
	if s := steps[1]; len(s.Links.Removed) != 1 || s.Links.Removed[0].ID != "n2:ethernet-1/2|n3:ethernet-1/1" ||
		len(s.Artifacts.Changed) != 0 || len(s.Nodes.Changed) != 2 || s.Nodes.Changed[0].Node != "n2" ||
		s.Nodes.Changed[1].Node != "n3" || !slices.Equal(s.Nodes.Changed[0].Reasons, []string{"bootstrap"}) {
		t.Errorf("demo/2 → demo/3: %+v; want one link removed, n2 and n3 changed by their bootstraps, no artifact", s)
	}
	if got := storedBundles(t, paths.Bundles); !slices.Equal(got, sortedCopy(ids...)) {
		t.Errorf("the store holds %v; want one bundle per waypoint compiled, %v", got, ids)
	}

	// The text: each waypoint and each step as it is known, the step between the two it
	// joins; the same ids again, since the store already holds them.
	code, stdout, stderr := runWaypoint(t, "plan", "--series", "demo")
	read := "  read: 3 devices (nokia_srlinux 3), 12 interfaces, 3 links, 3 artifacts, 0 lossy mappings, 0 shared ports"
	want := strings.Join([]string{
		"series demo (3 waypoints)",
		`demo/1: branch fylgja-fixture at 2026-09-01T09:00:00.000000+00:00 (written), "before the change"`,
		"  bundle_id " + ids[0],
		read,
		"step demo/1 → demo/2 (" + ids[0][:8] + "… → " + ids[1][:8] + "…): unchanged; the ids differ by provenance alone",
		`demo/2: branch fylgja-fixture at 2026-09-08T12:00:00Z (given), "after the first cut-over"`,
		"  bundle_id " + ids[1],
		read,
		"step demo/2 → demo/3 (" + ids[1][:8] + "… → " + ids[2][:8] + "…):",
		"  nodes: ~n2 (bootstrap); ~n3 (bootstrap)",
		"  links: -n2:e1-2 — n3:e1-1",
		"  artifacts: unchanged",
		`demo/3: branch change-1 at 2026-09-21T15:20:44.000000+00:00 (written), "after the second"`,
		"  bundle_id " + ids[2],
		strings.Replace(read, "3 links", "2 links", 1),
	}, "\n") + "\n"
	if code != findings.ExitOK || stdout != want || stderr != "" {
		t.Errorf("exit %d, stdout\n%s\nstderr %q\nwant 0 and\n%s", code, stdout, stderr, want)
	}
	if got := storedBundles(t, paths.Bundles); len(got) != 3 {
		t.Errorf("a second plan filed %v; the three bundles are reused", got)
	}
	mustQuoteNoContent(t, contentLines(t, f, paths.Bundles), stdout, stderr, raw)
}

// A waypoint refused at resolution, and one whose read cannot run, are reported in place and
// the plan goes on: every step touching either is not computed, naming which was refused, and
// the exit is 1. Only the waypoints that compiled are filed (contracts/cli.md).
func TestWaypointPlanRefusedInTheMiddle(t *testing.T) {
	paths := useStateRoot(t)
	useService(t, nil)
	f := seriesInfrahub(t)
	f.start()

	code, stdout, stderr := runWaypoint(t, "plan", "--series", "mid")
	lines := strings.Split(strings.TrimSuffix(stdout, "\n"), "\n")
	var shown []string
	for _, l := range lines {
		if !strings.HasPrefix(l, "  ") {
			shown = append(shown, regexp.MustCompile(`\([0-9a-f]{8}… → `).ReplaceAllString(
				regexp.MustCompile(` → [0-9a-f]{8}…\)`).ReplaceAllString(l, " → ID)"), "(ID → "))
		}
	}
	want := []string{
		"series mid (4 waypoints)",
		`mid/1: branch fylgja-fixture at 2026-09-02T00:00:00.000000+00:00 (written), ""`,
		"step mid/1 → mid/2 (ID → —): not computed (mid/2 was refused)",
		"mid/2: refused (intent.at.precision)",
		"step mid/2 → mid/3 (— → —): not computed (mid/2 and mid/3 were refused)",
		"mid/3: failed (operation.failed)",
		"step mid/3 → mid/4 (— → ID): not computed (mid/3 was refused)",
		`mid/4: branch fylgja-fixture at 2026-09-08T12:00:00Z (given), ""`,
	}
	if code != findings.ExitRejected || !slices.Equal(shown, want) {
		t.Errorf("exit %d, stdout\n%s\nwant 1 and the lines\n%s", code, stdout, strings.Join(want, "\n"))
	}
	for _, w := range []string{
		"rejection intent.at.precision [step resolve] mid/2: waypoint mid/2: at " + midNineAt + " carries 9 fractional digits",
		"rejection operation.failed [step read] mid/3: ",
	} {
		if !strings.Contains(stderr, w) {
			t.Errorf("stderr lacks %q:\n%s", w, stderr)
		}
	}

	code, doc, raw := waypointDoc(t, "plan", "--series", "mid")
	if code != findings.ExitRejected || doc.Status != findings.StatusRejected || doc.Plan == nil ||
		len(doc.Plan.Waypoints) != 4 || len(doc.Plan.Steps) != 3 {
		t.Fatalf("exit %d, document %s", code, raw)
	}
	var rules []string
	for _, f := range doc.Findings {
		rules = append(rules, f.Object+" "+f.Rule+" "+f.Step)
	}
	if want := []string{"mid/2 intent.at.precision resolve", "mid/3 operation.failed read"}; !slices.Equal(rules, want) {
		t.Errorf("findings %v, want %v", rules, want)
	}
	if mid2 := doc.Plan.Waypoints[1]; mid2.BundleID != nil || mid2.Read != nil || mid2.Branch != "" || len(mid2.Findings) != 1 {
		t.Errorf("mid/2, refused at resolution: %+v", mid2)
	}
	if mid3 := doc.Plan.Waypoints[2]; mid3.BundleID != nil || mid3.Branch != "gone" || mid3.AtSource != "written" || len(mid3.Findings) != 1 {
		t.Errorf("mid/3, resolved and not read: %+v", mid3)
	}
	var compiled []string
	for _, w := range doc.Plan.Waypoints {
		if w.BundleID != nil {
			compiled = append(compiled, *w.BundleID)
		}
	}
	if got := storedBundles(t, paths.Bundles); len(compiled) != 2 || !slices.Equal(got, sortedCopy(compiled...)) {
		t.Errorf("the store holds %v; want the two compiled, %v", got, compiled)
	}
	for _, r := range f.requests() {
		if strings.Contains(r.Query, "123456789") {
			t.Errorf("the refused at was sent: %+v", r)
		}
	}
	mustQuoteNoContent(t, contentLines(t, f, paths.Bundles), stdout, stderr, raw)
}

// A later waypoint whose at is earlier warns and refuses nothing: every waypoint compiles and
// the exit is 0.
func TestWaypointPlanReversedWarns(t *testing.T) {
	useStateRoot(t)
	useService(t, nil)
	f := seriesInfrahub(t)
	f.start()

	code, doc, raw := waypointDoc(t, "plan", "--series", "back")
	if code != findings.ExitOK || doc.Status != findings.StatusOK || len(doc.Findings) != 1 ||
		doc.Findings[0].Rule != findings.RuleWaypointTimeReversed || doc.Findings[0].Object != "back/2" {
		t.Fatalf("exit %d, document %s", code, raw)
	}
	for _, w := range doc.Plan.Waypoints {
		if w.BundleID == nil {
			t.Errorf("%s/%d did not compile: %s", w.Series, w.Sequence, raw)
		}
	}
	if back2 := doc.Plan.Waypoints[1]; len(back2.Findings) != 1 || back2.Findings[0].Rule != findings.RuleWaypointTimeReversed {
		t.Errorf("back/2 carries %+v; want its warning", back2.Findings)
	}
	code, stdout, stderr := runWaypoint(t, "plan", "--series", "back")
	if code != findings.ExitOK || !strings.Contains(stdout, "step back/1 → back/2 (") ||
		!strings.Contains(stderr, "warning waypoint.time.reversed back/2: ") {
		t.Errorf("exit %d\n%s\n%s", code, stdout, stderr)
	}
}

// A series no waypoint has refuses the plan naming the series that exist, with nothing read
// or filed, and lists nothing; the kind absent from the default branch refuses both, with no
// waypoint asked for.
func TestWaypointUnknownSeriesAndKindAbsent(t *testing.T) {
	paths := useStateRoot(t)
	useService(t, nil)
	f := seriesInfrahub(t)
	f.start()

	code, doc, raw := waypointDoc(t, "plan", "--series", "nosuch")
	want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleWaypointUnknown, Object: "nosuch",
		Step: findings.StepResolve, Message: `no waypoint series "nosuch" exists; the series are: back, demo, mid`}
	if code != findings.ExitRejected || len(doc.Findings) != 1 || doc.Findings[0] != want || doc.Plan != nil {
		t.Errorf("exit %d, document %s; want 1 with %+v and no plan block", code, raw, want)
	}
	if got := branchReads(f); len(got) != 0 {
		t.Errorf("an unknown series read %+v", got)
	}
	if got := storedBundles(t, paths.Bundles); len(got) != 0 {
		t.Errorf("an unknown series filed %v", got)
	}
	code, stdout, stderr := runWaypoint(t, "plan", "--series", "nosuch")
	if code != findings.ExitRejected || stdout != "" || !strings.Contains(stderr, want.Message) {
		t.Errorf("text: exit %d, stdout %q, stderr %q", code, stdout, stderr)
	}

	code, stdout, _ = runWaypoint(t, "list", "--series", "nosuch")
	if code != findings.ExitOK || stdout != "series nosuch: no waypoints\n" {
		t.Errorf("list --series nosuch: exit %d, %q", code, stdout)
	}
	code, doc, raw = waypointDoc(t, "list", "--series", "nosuch")
	if code != findings.ExitOK || doc.Waypoints == nil || len(doc.Waypoints.Waypoints) != 0 || !strings.Contains(raw, `"waypoints": []`) {
		t.Errorf("list --series nosuch: exit %d, %s", code, raw)
	}

	empty := newFakeInfrahub(t)
	empty.start()
	if code, stdout, _ := runWaypoint(t, "list"); code != findings.ExitOK || stdout != "no waypoints\n" {
		t.Errorf("an Infrahub with no waypoint: exit %d, %q", code, stdout)
	}
	code, doc, _ = waypointDoc(t, "plan", "--series", "demo")
	if code != findings.ExitRejected || len(doc.Findings) != 1 ||
		doc.Findings[0].Message != `no waypoint series "demo" exists; there are no waypoints` {
		t.Errorf("plan with no waypoint: exit %d, %+v", code, doc.Findings)
	}

	absent := seriesInfrahub(t)
	absent.kind = nil
	absent.start()
	kindWant := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleWaypointKindAbsent, Object: intent.WaypointKind,
		Step: findings.StepResolve, Message: "the default branch's schema has no kind FylgjaWaypoint: load " +
			"schema/fylgja-waypoint.yaml on it; only --waypoint, waypoint list and waypoint plan need it"}
	for _, args := range [][]string{{"list"}, {"list", "--series", "demo"}, {"plan", "--series", "demo"}} {
		code, doc, raw := waypointDoc(t, args...)
		if code != findings.ExitRejected || len(doc.Findings) != 1 || doc.Findings[0] != kindWant ||
			doc.Waypoints != nil || doc.Plan != nil {
			t.Errorf("%v with the kind absent: exit %d, %s", args, code, raw)
		}
	}
	for _, r := range absent.requests() {
		if r.Operation == "Waypoints" || r.Query != "" {
			t.Errorf("with the kind absent the commands asked %+v", r)
		}
	}
}

// The row the host's twin was built from is marked, and a record whose waypoint moved or is
// gone draws waypoint.twin.moved beside it; a record naming none, or one that cannot be read,
// marks nothing and warns of nothing (contracts/cli.md).
func TestWaypointListMarksTheTwin(t *testing.T) {
	paths := useStateRoot(t)
	useService(t, nil)
	f := seriesInfrahub(t)
	f.start()
	record := func(t *testing.T, w *wire.WaypointRef, at string) {
		t.Helper()
		rec := wire.TwinRecord{TwinVersion: lab.TwinVersion, Lab: wire.LabName, BundleID: fixtureBundleID,
			Provenance: wire.Provenance{Branch: "fylgja-fixture", At: at, SchemaHash: "fixture", ContractVersion: "0.2"},
			Source:     wire.SourceIntent, Waypoint: w}
		raw, err := json.Marshal(rec)
		if err != nil {
			t.Fatal(err)
		}
		if err := os.MkdirAll(paths.Twin, 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(paths.TwinJSON, raw, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	demo2 := &wire.WaypointRef{Series: "demo", Sequence: 2, Description: "after the first cut-over", AtSource: "given"}
	marked := func(doc *findings.Document) []string {
		var out []string
		for _, w := range doc.Waypoints.Waypoints {
			if w.Twin {
				out = append(out, w.Series+"/"+strconv.Itoa(w.Sequence))
			}
		}
		return out
	}

	// Built from demo/2 as it still resolves: marked, no warning.
	record(t, demo2, fixtureAt)
	code, doc, raw := waypointDoc(t, "list", "--series", "demo")
	wantRecord := findings.WaypointRecord{Series: "demo", Sequence: 2, Branch: "fylgja-fixture", At: fixtureAt, AtSource: "given"}
	if code != findings.ExitOK || !slices.Equal(marked(doc), []string{"demo/2"}) || doc.Waypoints.Record == nil ||
		*doc.Waypoints.Record != wantRecord || len(doc.Findings) != 0 {
		t.Errorf("exit %d, %s", code, raw)
	}
	_, stdout, _ := runWaypoint(t, "list", "--series", "demo")
	if !strings.Contains(stdout, `  demo/2  branch fylgja-fixture  at 2026-09-08T12:00:00Z (given)  "after the first cut-over"  ← twin`+"\n") ||
		strings.Count(stdout, "← twin") != 1 {
		t.Errorf("the twin's row is not marked alone:\n%s", stdout)
	}
	// Another series' listing shows neither the row nor a warning of it: back's own
	// time.reversed alone.
	if _, doc, _ := waypointDoc(t, "list", "--series", "back"); len(marked(doc)) != 0 || doc.Waypoints.Record == nil ||
		len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleWaypointTimeReversed {
		t.Errorf("list --series back marks %v, findings %+v", marked(doc), doc.Findings)
	}

	// Built from demo/2 when it resolved elsewhere: the row is still marked, and the warning
	// names both references.
	record(t, demo2, "2026-09-07T00:00:00Z")
	code, doc, raw = waypointDoc(t, "list")
	moved := findings.Finding{Severity: findings.Warning, Rule: findings.RuleWaypointTwinMoved, Object: "demo/2",
		Message: "the twin was built from waypoint demo/2 at branch fylgja-fixture, at 2026-09-07T00:00:00Z (given); " +
			"demo/2 now resolves to branch fylgja-fixture, at 2026-09-08T12:00:00Z (given); the twin is pinned to what it was built from"}
	if code != findings.ExitOK || !slices.Equal(marked(doc), []string{"demo/2"}) || !slices.Contains(doc.Findings, moved) {
		t.Errorf("a moved waypoint: exit %d, %s", code, raw)
	}

	// Built from a waypoint since deleted: nothing to mark, and the warning says so.
	record(t, &wire.WaypointRef{Series: "demo", Sequence: 9, AtSource: "written"}, fixtureAt)
	code, doc, raw = waypointDoc(t, "list", "--series", "demo")
	gone := findings.Finding{Severity: findings.Warning, Rule: findings.RuleWaypointTwinMoved, Object: "demo/9",
		Message: "the twin was built from waypoint demo/9 at branch fylgja-fixture, at 2026-09-08T12:00:00Z (written); " +
			"demo/9 no longer exists; the twin is pinned to what it was built from"}
	if code != findings.ExitOK || len(marked(doc)) != 0 || len(doc.Findings) != 1 || doc.Findings[0] != gone {
		t.Errorf("a deleted waypoint: exit %d, %s", code, raw)
	}

	// A record naming no waypoint, and one that cannot be read, mark and warn of nothing.
	record(t, nil, fixtureAt)
	if _, doc, raw := waypointDoc(t, "list"); len(marked(doc)) != 0 || doc.Waypoints.Record != nil ||
		len(doc.Findings) != 1 { // back's time.reversed alone
		t.Errorf("a record naming no waypoint: %s", raw)
	}
	if err := os.WriteFile(paths.TwinJSON, []byte("{not json"), 0o644); err != nil {
		t.Fatal(err)
	}
	if code, doc, raw := waypointDoc(t, "list", "--series", "demo"); code != findings.ExitOK || len(marked(doc)) != 0 ||
		len(doc.Findings) != 0 {
		t.Errorf("an unreadable record: exit %d, %s", code, raw)
	}
}

// Before any connection: a --series that is not a series is waypoint.ref.invalid at step
// start, exit 2, on either verb, an explicitly empty one included; the plan without --series
// is refused as any command's missing required flag. An Infrahub that cannot be reached is
// operation.failed, exit 2, at step resolve, naming no credential (contracts/cli.md).
func TestWaypointRefusedBeforeAnyConnection(t *testing.T) {
	useStateRoot(t)
	useService(t, nil)
	f := seriesInfrahub(t)
	f.start()

	for _, args := range [][]string{
		{"list", "--series", "a b"}, {"plan", "--series", "a b"}, {"list", "--series=a/b"}, {"list", "--series="},
		{"plan", "--series="},
	} {
		series := strings.TrimPrefix(args[len(args)-1], "--series=")
		want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleWaypointRefInvalid, Object: series,
			Step: findings.StepStart, Message: "--series " + strconv.Quote(series) +
				` is not a waypoint series: expected a series with no "/" and no whitespace`}
		code, doc, raw := waypointDoc(t, args...)
		if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0] != want {
			t.Errorf("%v: exit %d, %s; want 2 with %+v", args, code, raw, want)
		}
	}
	code, doc, raw := waypointDoc(t, "plan")
	if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0] != (findings.Finding{
		Severity: findings.Rejection, Rule: findings.RuleOperationFailed, Object: findings.OpWaypointPlan,
		Message: "--series is required"}) {
		t.Errorf("plan with no --series: exit %d, %s", code, raw)
	}
	if got := f.requests(); len(got) != 0 {
		t.Errorf("Infrahub was asked %+v before the flags were refused", got)
	}

	// An unset credential, then an Infrahub that does not answer.
	for _, env := range []struct{ address, token, says string }{
		{"http://127.0.0.1:1", "", intent.EnvToken + " is not set"},
		{"http://127.0.0.1:1", fakeToken, "127.0.0.1:1"},
	} {
		t.Setenv(intent.EnvAddress, env.address)
		t.Setenv(intent.EnvToken, env.token)
		for _, args := range [][]string{{"list"}, {"plan", "--series", "demo"}} {
			code, doc, raw := waypointDoc(t, args...)
			op := "waypoint." + args[0]
			if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleOperationFailed ||
				doc.Findings[0].Step != findings.StepResolve || doc.Findings[0].Object != op ||
				!strings.Contains(doc.Findings[0].Message, env.says) {
				t.Errorf("%v with %q: exit %d, %s", args, env.says, code, raw)
			}
			mustCarryNoToken(t, op, raw)
		}
	}
}

// Each waypoint's findings are printed under its line as the plan goes, indented, in the
// document's text-line shape, as well as with the document's on stderr: two waypoints of
// one branch raise the same device-level warning, and only its place in the plan says whose
// each is. A refused waypoint's are under its refused line.
func TestWaypointPlanPrintsFindingsUnderTheirWaypoint(t *testing.T) {
	useStateRoot(t)
	useService(t, nil)
	f := newFakeInfrahub(t)
	// n1 gains a port beyond the package's range, uncabled, which the twin omits, and its
	// artifact a line naming it: every read of the branch warns of it.
	n1 := &f.fixture.Devices[0]
	n1.Interfaces = append(n1.Interfaces, ctm.Interface{Name: "ethernet-1/99", Iftype: "physical"})
	n1.Artifact.Content += "set / interface ethernet-1/99 admin-state enable\n"
	n1.Artifact.Checksum = fmt.Sprintf("%x", md5.Sum([]byte(n1.Artifact.Content)))
	f.waypoint("wp-warn-1", "warn", 1, "fylgja-fixture", demo1At, "", "")
	f.waypoint("wp-warn-2", "warn", 2, "fylgja-fixture", demoWrittenAt, fixtureAt, "")
	f.waypoint("wp-warn-3", "warn", 3, "fylgja-fixture", demoWrittenAt, midNineAt, "")
	f.start()

	code, doc, raw := waypointDoc(t, "plan", "--series", "warn")
	if code != findings.ExitRejected || doc.Plan == nil || len(doc.Plan.Waypoints) != 3 ||
		doc.Plan.Waypoints[0].BundleID == nil || doc.Plan.Waypoints[1].BundleID == nil {
		t.Fatalf("exit %d, document %s", code, raw)
	}
	id1, id2 := *doc.Plan.Waypoints[0].BundleID, *doc.Plan.Waypoints[1].BundleID

	code, stdout, stderr := runWaypoint(t, "plan", "--series", "warn")
	const omitted = "rule ethernet matched, but {port} is 99, outside its range 1..58; no such port on the node"
	unrepresented := func(step string) string {
		return "  warning artifact.interface.unrepresented [step " + step + "] n1:ethernet-1/99: artifact device-config " +
			"names interface ethernet-1/99 at line 17, which the twin does not represent: omitted (omit.interface.unmappable: " +
			omitted + ")"
	}
	read := "  read: 3 devices (nokia_srlinux 3), 13 interfaces, 3 links, 3 artifacts, 0 lossy mappings, 0 shared ports"
	want := strings.Join([]string{
		"series warn (3 waypoints)",
		`warn/1: branch fylgja-fixture at 2026-09-01T09:00:00.000000+00:00 (written), ""`,
		"  bundle_id " + id1,
		read,
		unrepresented("read"),
		unrepresented("compile"),
		"  info omit.interface.unmappable [step compile] n1:ethernet-1/99: " + omitted,
		"step warn/1 → warn/2 (" + id1[:8] + "… → " + id2[:8] + "…): unchanged; the ids differ by provenance alone",
		`warn/2: branch fylgja-fixture at 2026-09-08T12:00:00Z (given), ""`,
		"  bundle_id " + id2,
		read,
		unrepresented("read"),
		unrepresented("compile"),
		"  info omit.interface.unmappable [step compile] n1:ethernet-1/99: " + omitted,
		"step warn/2 → warn/3 (" + id2[:8] + "… → —): not computed (warn/3 was refused)",
		"warn/3: refused (intent.at.precision)",
		"  rejection intent.at.precision [step resolve] warn/3: waypoint warn/3: at " + midNineAt + " carries 9 fractional " +
			"digits; Infrahub honours at most 6 (microseconds). Write the waypoint's as_of with at most six.",
		"  warning waypoint.time.reversed warn/3: waypoint warn/3 resolves to at " + midNineAt + ", earlier than warn/2's " +
			fixtureAt + "; the order is the operator's and nothing is refused",
	}, "\n") + "\n"
	if code != findings.ExitRejected || stdout != want {
		t.Errorf("exit %d, stdout\n%s\nwant 1 and\n%s", code, stdout, want)
	}
	// The document's rendering on stderr is unchanged: every finding, sorted, naming no
	// waypoint, with the summary.
	var rendered strings.Builder
	if err := findings.NewDocument(findings.OpWaypointPlan, nil, doc.Findings).WriteText(&rendered); err != nil {
		t.Fatal(err)
	}
	if stderr != rendered.String() || !strings.HasSuffix(stderr, "8 finding(s): 1 rejection, 5 warning, 2 info\n") {
		t.Errorf("stderr\n%s\nwant the document's rendering\n%s", stderr, rendered.String())
	}
}

// Beside a diverged record the twin's row is still the record's waypoint, and its mark says
// which waypoint the failed step was going to; the JSON record carries state and towards.
// A ready version 4 record, with no step or after a step that landed, is marked as M10
// marked one, its towards null: a landed step's block names the waypoint the twin is now
// at, and is no diverged twin's target (contracts/cli.md, waypoint list).
func TestWaypointListMarksADivergedTwin(t *testing.T) {
	paths := useStateRoot(t)
	useService(t, nil)
	f := seriesInfrahub(t)
	f.start()
	demo2 := &wire.WaypointRef{Series: "demo", Sequence: 2, Description: "after the first cut-over", AtSource: "given"}
	record := func(t *testing.T, state string, step *wire.StepRecord) {
		t.Helper()
		rec := wire.TwinRecord{TwinVersion: lab.TwinVersion, Lab: wire.LabName, BundleID: fixtureBundleID,
			Provenance: wire.Provenance{Branch: "fylgja-fixture", At: fixtureAt, SchemaHash: "fixture", ContractVersion: "0.2"},
			Source:     wire.SourceIntent, Waypoint: demo2, State: state, Step: step}
		raw, err := json.Marshal(rec)
		if err != nil {
			t.Fatal(err)
		}
		if err := os.MkdirAll(paths.Twin, 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(paths.TwinJSON, raw, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	const row = `  demo/2  branch fylgja-fixture  at 2026-09-08T12:00:00Z (given)  "after the first cut-over"  ← twin`
	phase := findings.StepPush
	record(t, wire.StateDiverged, &wire.StepRecord{Outcome: wire.StepDiverged, Phase: &phase,
		From: wire.StepSide{Waypoint: demo2, BundleID: fixtureBundleID, At: fixtureAt},
		To:   wire.StepSide{Waypoint: &wire.WaypointRef{Series: "demo", Sequence: 3, AtSource: "written"}, BundleID: strings.Repeat("51f0aa93", 8)}})
	_, stdout, _ := runWaypoint(t, "list", "--series", "demo")
	if !strings.Contains(stdout, row+" (diverged towards demo/3)\n") || strings.Count(stdout, "← twin") != 1 {
		t.Errorf("the diverged twin's row is not marked with its target:\n%s", stdout)
	}
	code, doc, raw := waypointDoc(t, "list", "--series", "demo")
	want := findings.WaypointRecord{Series: "demo", Sequence: 2, Branch: "fylgja-fixture", At: fixtureAt, AtSource: "given",
		State: wire.StateDiverged, Towards: &findings.WaypointTowards{Series: "demo", Sequence: 3}}
	if r := doc.Waypoints.Record; code != findings.ExitOK || r == nil || r.State != want.State || r.Towards == nil ||
		*r.Towards != *want.Towards || r.Series != "demo" || r.Sequence != 2 ||
		!strings.Contains(compacted(t, raw), `"state":"diverged","towards":{"series":"demo","sequence":3}`) {
		t.Errorf("exit %d, %s", code, raw)
	}

	// Ready, with no step or after one: the mark is M10's, and the JSON says ready, towards null.
	ready := func(name string) {
		t.Helper()
		_, stdout, _ := runWaypoint(t, "list", "--series", "demo")
		if !strings.Contains(stdout, row+"\n") || strings.Contains(stdout, "diverged") {
			t.Errorf("%s: the row is not marked as M10 marked it:\n%s", name, stdout)
		}
		if _, _, raw := waypointDoc(t, "list", "--series", "demo"); !strings.Contains(compacted(t, raw), `"at_source":"given","state":"ready","towards":null}`) {
			t.Errorf("%s: the record's block: %s", name, raw)
		}
	}
	record(t, wire.StateReady, nil)
	ready("a ready record with no step")

	// A step that landed, demo/1 → demo/2, leaves its step block in the record, whose
	// target is the waypoint the twin is now at: it is no diverged twin's mark.
	demo1 := &wire.WaypointRef{Series: "demo", Sequence: 1, Description: "before the change", AtSource: "written"}
	staged, nodes := showStepTarget(fixtureBundleID, fixtureAt, fixtureArtifacts)
	stepped, err := lab.NewStepRecord(twinOf(t, func(f *lab.RecordFields) {
		f.Provenance.At, f.Waypoint = demo1At, demo1
	}), lab.StepFields{
		Outcome:    wire.StepStepped,
		From:       wire.StepSide{Waypoint: demo1, BundleID: showBundleID, At: demo1At},
		To:         wire.StepSide{Waypoint: demo2, BundleID: fixtureBundleID, At: fixtureAt},
		ObservedAt: "2026-10-02T09:14:01.000000Z", RunID: stepShowRunID, Version: "0.1.0-dev",
		Declared:  map[string]string{"n1": "live", "n2": "live", "n3": "live"},
		Pushed:    []wire.StepPush{{Node: "n1", Reasons: []string{"artifact"}, Outcome: wire.PushLanded}},
		StartedAt: "2026-10-02T09:14:30Z", EndedAt: stepEnded, RecordedAt: time.Date(2026, 10, 2, 9, 15, 41, 0, time.UTC),
		Nodes: nodes, Staged: staged,
	})
	if err != nil {
		t.Fatal(err)
	}
	if stepped.State != wire.StateReady || stepped.Step == nil || stepped.Step.To.Waypoint == nil {
		t.Fatalf("the landed step's record: %+v", stepped)
	}
	writeTwin(t, paths, stepped)
	ready("a ready record after a step")
}

// compacted is a JSON document with its whitespace removed, for matching keys in order.
func compacted(t *testing.T, raw string) string {
	t.Helper()
	var b bytes.Buffer
	if err := json.Compact(&b, []byte(raw)); err != nil {
		t.Fatal(err)
	}
	return b.String()
}
