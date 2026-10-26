//go:build contract

package server

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"math/rand"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/rehearsal"
	"github.com/happypathnetworking/fylgja/internal/stages"
	"github.com/happypathnetworking/fylgja/internal/testsupport"
)

// twin rehearse against a real Infrahub, never a fake (D-017), through a server in the
// test's process whose workflow service, containerlab and node reader each fail the test
// if reached (handlerServer). Each test seeds a throwaway branch of its own and deletes,
// when it ends, its stages, its proposed changes and the branch, in that order, unless the
// test deleted them itself. Boot no twin while they run.
//
//	set -a; . local/.env; set +a; go test -count=1 -tags contract ./internal/server -run TestRehearse -v

// rehearseDevices are the three-node fixture's devices, which the seed renders.
var rehearseDevices = []string{"n1", "n2", "n3"}

// creationChecksWait bounds a creation's user checks, as internal/checks bounds them: the
// validators appeared 43–54 s after a creation, and fylgja-step concluded in 30 s and
// fylgja-twin's skip in 18 s (research §5.6).
const creationChecksWait = 6 * time.Minute

// contractClient returns a write-capable client, skipping when no Infrahub is configured.
func contractClient(t *testing.T) *testsupport.Client {
	t.Helper()
	c, err := testsupport.NewClient()
	if err != nil {
		t.Skipf("contract tests need a running Infrahub: %v", err)
	}
	return c
}

// seededBranch makes a branch fylgja-test-rh-<ts>-<n>, loads the schema and seeds the
// three-node fixture with its artifacts rendered. When the test ends, a branch still there
// is deleted with what hangs on it; then neither it nor a proposed change from it may be
// left. The durable fylgja-fixture branch is never written.
func seededBranch(t *testing.T, c *testsupport.Client) string {
	t.Helper()
	name := fmt.Sprintf("%srh-%d-%d", testsupport.TestBranchPrefix, time.Now().Unix(), rand.Intn(9999))
	if err := c.CreateBranch(name); err != nil {
		t.Fatalf("creating branch: %v", err)
	}
	t.Cleanup(func() {
		exists, err := c.BranchExists(name)
		if err != nil {
			t.Errorf("reading branch %s before deleting it: %v", name, err)
			return
		}
		if exists {
			stages, proposed, err := c.DeleteTestBranchCounting(name)
			if err != nil {
				t.Errorf("could not delete branch %s and what hangs on it (%d stage(s), %d proposed change(s) deleted): %v",
					name, stages, proposed, err)
				return
			}
			t.Logf("deleted %d stage(s), %d proposed change(s), branch %s", stages, proposed, name)
		}
		if exists, err := c.BranchExists(name); err != nil || exists {
			t.Errorf("after the test branch %s exists: %t (%v)", name, exists, err)
		}
		if left, err := c.ProposedChangesOf(name); err != nil || len(left) != 0 {
			t.Errorf("after the test the proposed changes on %s are %+v (%v); want none", name, left, err)
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

// answer sends req to op and returns the answer's out text, the files it carried and its
// document, as handled does with the files kept.
func answer(t *testing.T, srv *httptest.Server, op string, req api.Request) (string, []api.File, *findings.Document) {
	t.Helper()
	body, err := api.EncodeRequest(req)
	if err != nil {
		t.Fatal(err)
	}
	resp, raw := post(t, nil, srv.URL+api.Path(op), testToken, string(body), nil)
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("%s: status %d: %s", op, resp.StatusCode, raw)
	}
	var out strings.Builder
	var files []api.File
	var doc *findings.Document
	for _, line := range answerLines(t, raw) {
		f := frameOf(t, line)
		out.WriteString(f.Out)
		files = append(files, f.Files...)
		if f.Kind() == api.KindDocument {
			doc = &findings.Document{}
			if err := json.Unmarshal(f.Document, doc); err != nil {
				t.Fatalf("%s: the document: %v", op, err)
			}
		}
	}
	if doc == nil {
		t.Fatalf("%s: no document in %s", op, raw)
	}
	return out.String(), files, doc
}

// stringArgs are a request's arguments, each a string.
func stringArgs(kv ...string) map[string]json.RawMessage {
	args := map[string]json.RawMessage{}
	for i := 0; i+1 < len(kv); i += 2 {
		b, _ := json.Marshal(kv[i+1])
		args[kv[i]] = b
	}
	return args
}

// rejectionsOf are a list's rejections of rule, by object, in order.
func rejectionsOf(list findings.List, rule string) []string {
	var out []string
	for _, f := range list {
		if f.Severity == findings.Rejection && f.Rule == rule {
			out = append(out, f.Object)
		}
	}
	return out
}

// A rehearsal the plan refuses dials nothing (contracts/rehearse-command.md, step 2): on a
// seeded branch with a draft, the mark seeded, then an intent change with no generate and a
// mark after it, twin.rehearse is refused with the plan's findings, stage.artifact.stale on
// each device the change moved, rejected, exit 1. The workflow service is never dialled, no
// host tool runs and no node is read (handlerServer fails the test at each), and no twin
// directory is made.
func TestRehearseRefusesBeforeAnyRun(t *testing.T) {
	c := contractClient(t)
	paths := useStateRoot(t)
	branch := seededBranch(t, c)
	started := time.Now()
	id, err := c.OpenProposedChange(branch, true)
	if err != nil {
		t.Fatalf("opening a proposed change on %s: %v", branch, err)
	}
	t.Logf("proposed change %s on %s, its pipeline concluded after %.0fs", id, branch, time.Since(started).Seconds())
	if _, _, err := c.MarkStage(id, "seeded", "", "seeded"); err != nil {
		t.Fatalf("marking seeded: %v", err)
	}
	for _, d := range rehearseDevices {
		if err := c.SetDeviceDescription(branch, d, "stale-description"); err != nil {
			t.Fatal(err)
		}
	}
	if _, _, err := c.MarkStage(id, "description-stale", "", "the description, not rendered"); err != nil {
		t.Fatalf("marking description-stale: %v", err)
	}

	srv := handlerServer(t)
	started = time.Now()
	out, _, doc := answer(t, srv, findings.OpTwinRehearse, api.Request{Render: api.RenderText, Args: stringArgs("branch", branch)})
	t.Logf("twin.rehearse refused in %.1fs", time.Since(started).Seconds())

	if doc.Status != findings.StatusRejected || doc.Status.ExitCode() != 1 {
		t.Errorf("status %s, exit %d; want rejected, exit 1", doc.Status, doc.Status.ExitCode())
	}
	if got := rejectionsOf(doc.Findings, findings.RuleStageArtifactStale); len(got) < len(rehearseDevices) ||
		!slices.Equal(got[:len(rehearseDevices)], rehearseDevices) {
		t.Errorf("stage.artifact.stale names %v; want %v first", got, rehearseDevices)
	}
	block := doc.Rehearsal
	if block == nil {
		t.Fatalf("the refusal carries no rehearsal block: %+v", doc)
	}
	if block.ProposedChange.ID != id || block.Run != nil || block.Destroy != nil || block.Baseline != nil {
		t.Errorf("the block names proposed change %s, run %+v, destroy %+v, baseline %+v; want %s and no run, destroy or baseline",
			block.ProposedChange.ID, block.Run, block.Destroy, block.Baseline, id)
	}
	var labels []string
	for _, st := range block.Stages {
		labels = append(labels, st.Label)
		if st.Label != "description-stale" {
			continue
		}
		if st.Role != rehearsal.RoleRefused || !slices.Equal(rejectionsOf(st.Findings, findings.RuleStageArtifactStale), rehearseDevices) {
			t.Errorf("description-stale is %s with %+v; want refused, stage.artifact.stale on %v", st.Role, st.Findings, rehearseDevices)
		}
	}
	if want := []string{stages.LabelBranchPoint, "seeded", "description-stale", stages.LabelHead}; !slices.Equal(labels, want) {
		t.Errorf("the block's stages are %v, want %v", labels, want)
	}
	if want := fmt.Sprintf("%s/description-stale: refused (%s)", branch, findings.RuleStageArtifactStale); !strings.Contains(out, want) {
		t.Errorf("the text does not say %q:\n%s", want, out)
	}
	if _, err := os.Stat(paths.Twin); !errors.Is(err, os.ErrNotExist) {
		t.Errorf("the refusal left a twin directory at %s (%v)", paths.Twin, err)
	}
}

// fixtureTool builds cmd/fylgja-fixture into the test's directory, so its flags are run as
// an operator and tier 3 run them.
func fixtureTool(t *testing.T) string {
	t.Helper()
	gobin, err := exec.LookPath("go")
	if err != nil {
		t.Fatalf("building the fixture tool needs go on the PATH: %v", err)
	}
	bin := filepath.Join(t.TempDir(), "fylgja-fixture")
	cmd := exec.Command(gobin, "build", "-tags", "fixture", "-o", bin, "./cmd/fylgja-fixture")
	cmd.Dir = repoPath()
	if out, err := cmd.CombinedOutput(); err != nil {
		t.Fatalf("building the fixture tool: %v\n%s", err, out)
	}
	return bin
}

// deviceChecksums are each device's device-config checksum on branch, as Infrahub lists it
// now: a device whose artifact is not Ready is not listed.
func deviceChecksums(t *testing.T, c *testsupport.Client, branch string) map[string]string {
	t.Helper()
	raw, err := c.GraphQL(branch, `{ DcimDevice { edges { node { name { value }
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
		} `json:"DcimDevice"`
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

// T039's flags as a rehearsal's composition runs them (contracts/fixture-tool.md), each
// printing its line exactly: -propose opens a draft, -ready makes it ready, -add-interface
// writes one uncabled physical port, active, which -generate renders on n1 alone, where the
// read warns artifact.interface.unrepresented for the port the compile omits
// omit.interface.unmappable (research R-14), -run-checks user returns at once with no user
// check on a branch that sees no definition, and -delete takes the proposed change with the
// branch. The read and the compile go through the server, which dials nothing.
func TestRehearseComposedByTheFixtureTool(t *testing.T) {
	c := contractClient(t)
	useStateRoot(t)
	tool := fixtureTool(t)
	branch := seededBranch(t, c)
	fixture := func(args ...string) string {
		t.Helper()
		cmd := exec.Command(tool, append([]string{"-branch", branch}, args...)...)
		cmd.Dir = repoPath()
		var stdout, stderr bytes.Buffer
		cmd.Stdout, cmd.Stderr = &stdout, &stderr
		started := time.Now()
		if err := cmd.Run(); err != nil {
			t.Fatalf("fylgja-fixture %s: %v\n%s", strings.Join(args, " "), err, stderr.String())
		}
		t.Logf("fylgja-fixture %s: %.1fs: %s", strings.Join(args, " "), time.Since(started).Seconds(), strings.TrimSpace(stdout.String()))
		return stdout.String()
	}

	out := fixture("-propose")
	pcs, err := c.ProposedChangesOf(branch)
	if err != nil || len(pcs) != 1 || !pcs[0].Draft {
		t.Fatalf("after -propose the proposed changes on %s are %+v (%v); want one draft", branch, pcs, err)
	}
	id := pcs[0].ID
	if want := fmt.Sprintf("proposed change %s opened on %s, draft; ", id, branch); !strings.HasPrefix(out, want) {
		t.Errorf("-propose printed %q; want it to begin %q", out, want)
	}

	// With a check registered on main, the creation's fylgja-twin may not have read the
	// proposed change when -propose returns; marked ready before it does, it would rehearse
	// it on a twin, which tier 2 never boots (research §5.6). So -ready waits for the
	// creation's user checks to conclude on the draft.
	started := time.Now()
	rows, err := c.AwaitUserChecks(id, creationChecksWait)
	if err != nil {
		t.Fatalf("awaiting the creation's user checks before -ready: %v", err)
	}
	t.Logf("the creation's user checks concluded on the draft after %.0fs: %d check(s)", time.Since(started).Seconds(), len(rows))

	if out, want := fixture("-ready"), fmt.Sprintf("proposed change %s on %s marked ready for review\n", id, branch); out != want {
		t.Errorf("-ready printed %q, want %q", out, want)
	}
	if pcs, err := c.ProposedChangesOf(branch); err != nil || len(pcs) != 1 || pcs[0].Draft || pcs[0].State != "open" {
		t.Errorf("after -ready the proposed changes on %s are %+v (%v); want one open, is_draft false", branch, pcs, err)
	}

	const port = "ethernet-1/99"
	before := deviceChecksums(t, c, branch)
	if out, want := fixture("-add-interface", "n1:"+port),
		fmt.Sprintf("interface %s added on n1 on %s: physical, active, no cable; -generate renders it\n", port, branch); out != want {
		t.Errorf("-add-interface printed %q, want %q", out, want)
	}
	raw, err := c.GraphQL(branch, fmt.Sprintf(`{ InterfacePhysical(device__name__value: "n1", name__value: %q) { edges { node {
		status { value } role { value } connector { node { id } } } } } }`, port))
	if err != nil {
		t.Fatal(err)
	}
	if got := string(raw); !strings.Contains(got, `"status":{"value":"active"}`) || !strings.Contains(got, `"role":{"value":null}`) ||
		!strings.Contains(got, `"connector":{"node":null}`) || strings.Count(got, `"status"`) != 1 {
		t.Errorf("n1:%s reads %s; want one physical port, active, not management, with no cable", port, got)
	}
	if after := deviceChecksums(t, c, branch); after["n1"] != before["n1"] {
		t.Errorf("-add-interface moved n1's checksum %s → %s; it renders nothing", before["n1"], after["n1"])
	}

	if out, want := fixture("-generate"), fmt.Sprintf("artifacts rendered and Ready on %s\n", branch); out != want {
		t.Errorf("-generate printed %q, want %q", out, want)
	}
	deadline := time.Now().Add(90 * time.Second)
	after := deviceChecksums(t, c, branch)
	for after["n1"] == before["n1"] && time.Now().Before(deadline) {
		time.Sleep(time.Second)
		after = deviceChecksums(t, c, branch)
	}
	if after["n1"] == "" || after["n1"] == before["n1"] {
		t.Fatalf("n1's checksum did not move after -generate: %s → %s", before["n1"], after["n1"])
	}
	for _, d := range []string{"n2", "n3"} {
		if after[d] != before[d] {
			t.Errorf("%s's checksum moved %s → %s; only n1 gained a port", d, before[d], after[d])
		}
	}

	srv := handlerServer(t)
	object := "n1:" + port
	_, files, doc := answer(t, srv, findings.OpIntentRead, api.Request{Render: api.RenderText, Args: stringArgs("branch", branch, "out", "ctm.json")})
	if doc.Status.ExitCode() != 0 || len(files) != 1 {
		t.Fatalf("intent.read: exit %d, %d file(s), findings %+v; want exit 0 and the CTM", doc.Status.ExitCode(), len(files), doc.Findings)
	}
	var warned bool
	for _, f := range doc.Findings {
		if f.Rule == findings.RuleArtifactInterfaceUnrepresented && f.Object == object {
			warned = f.Severity == findings.Warning && strings.Contains(f.Message, findings.RuleOmitInterfaceUnmappable)
		}
	}
	if !warned {
		t.Errorf("intent.read's findings %+v; want the warning %s on %s naming %s", doc.Findings,
			findings.RuleArtifactInterfaceUnrepresented, object, findings.RuleOmitInterfaceUnmappable)
	}
	_, _, doc = answer(t, srv, findings.OpCompile, api.Request{Render: api.RenderText,
		Args: stringArgs("ctm", "ctm.json", "out", "bundle"), Files: []api.File{{Path: "ctm.json", Data: files[0].Data}}})
	var omitted bool
	for _, f := range doc.Findings {
		if f.Rule == findings.RuleOmitInterfaceUnmappable && f.Object == object {
			omitted = true
		}
	}
	if doc.Status.ExitCode() != 0 || !omitted {
		t.Errorf("twin.compile: exit %d, findings %+v; want exit 0 and %s on %s", doc.Status.ExitCode(), doc.Findings,
			findings.RuleOmitInterfaceUnmappable, object)
	}

	// With a check registered on main, a user run would have fylgja-twin rehearse this ready
	// proposed change on a twin, which tier 2 never boots: the checks' own test runs them.
	if defs, err := c.CheckDefinitions(); err != nil {
		t.Fatal(err)
	} else if len(defs) != 0 {
		t.Logf("main holds the check definitions %+v: -run-checks user is not run here", defs)
	} else {
		started = time.Now()
		if out, want := fixture("-run-checks", "user"),
			fmt.Sprintf("no user check ran on proposed change %s on %s: the branch sees no check definition of a registered repository\n", id, branch); out != want {
			t.Errorf("-run-checks user printed %q, want %q", out, want)
		}
		if took := time.Since(started); took > 30*time.Second {
			t.Errorf("-run-checks user took %s with no check to wait for", took)
		}
		if rows, err := c.UserChecksOf(id); err != nil || len(rows) != 0 {
			t.Errorf("after -run-checks user the user checks are %+v (%v); want none", rows, err)
		}
	}

	if out, want := fixture("-delete"), fmt.Sprintf("deleted 0 stages, 1 proposed change, branch %s\n", branch); out != want {
		t.Errorf("-delete printed %q, want %q", out, want)
	}
	if exists, err := c.BranchExists(branch); err != nil || exists {
		t.Errorf("after -delete branch %s exists: %t (%v)", branch, exists, err)
	}
}
