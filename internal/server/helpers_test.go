package server

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"io/fs"
	"log/slog"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"sync"
	"testing"

	"github.com/santhosh-tekuri/jsonschema/v6"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
)

// The helpers the tests of a helper need, which moved here with the helper they test from
// M12's cmd/fylgja: each is M12's test helper, its body
// changed only where the seam it set is now a field of the server the helper is called
// through.

const fixtureBundleID = "1b352957aa74ff6e6f944a1b5ccb3b678248c895601f7a3aa66a4f9166d3909a"

// dcimMapping is the mapping a twin.json 8 record's provenance names when the Infrahub
// reader read the schema library's DCIM (017).
var dcimMapping = wire.Mapping{Reader: "infrahub-dcim", Model: "opsmill/schema-library", Version: "26336e9"}

// fixtureArtifacts are the fixture bundle's artifact checksums, by node: what the
// re-created fylgja-fixture branch rendered, 861 bytes each.
var fixtureArtifacts = map[string]string{
	"n1": "43e8fd0c2de5f4646f74a51d34742824",
	"n2": "ecb03029ea805a09c54d2cd6a0e59ac9",
	"n3": "ae0c3a87085839354cbb2ca10f71e487",
}

// helperServer is the server a helper's test calls the helper through: what the test hands
// it (useService, useClab) is what the request the helper serves would read.
var helperServer = func() *Server {
	s := New("")
	s.Log = slog.New(slog.NewTextHandler(io.Discard, nil))
	return s
}()

// testOptions are the options of a request a helper serves, under render text, or json when
// asJSON, as M12's tests built &options{} and &options{asJSON: true}. Their frames' text is
// printed on the process's stdout and stderr as each is written, where M12's helpers
// printed it, so the tests capture it as they did.
func testOptions(t *testing.T, asJSON bool) *options {
	t.Helper()
	render := api.RenderText
	if asJSON {
		render = api.RenderJSON
	}
	c := helperServer.newCall(context.Background(), "test", api.Request{Render: render}, newFrames(processStreams{}, nil), nil)
	return c.options()
}

// processStreams prints each frame's out text on stdout and its err text on stderr.
type processStreams struct{}

func (processStreams) Write(p []byte) (int, error) {
	var f api.Frame
	if err := json.Unmarshal(p, &f); err != nil {
		return 0, err
	}
	_, _ = io.WriteString(os.Stdout, f.Out)
	_, _ = io.WriteString(os.Stderr, f.Err)
	return len(p), nil
}

func repoPath(parts ...string) string {
	return filepath.Join(append([]string{"..", ".."}, parts...)...)
}

func asResult(err error, target **result) bool {
	res, ok := err.(*result)
	if ok {
		*target = res
	}
	return ok
}

func exitOf(t *testing.T, err error) (int, *findings.Document) {
	t.Helper()
	var res *result
	if !asResult(err, &res) {
		t.Fatalf("command returned %v, want a findings result", err)
	}
	return res.doc.Status.ExitCode(), res.doc
}

func captureStdout(t *testing.T, fn func()) string {
	t.Helper()
	r, w, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	saved := os.Stdout
	os.Stdout = w
	done := make(chan string)
	go func() {
		var b strings.Builder
		buf := make([]byte, 4096)
		for {
			n, err := r.Read(buf)
			b.Write(buf[:n])
			if err != nil {
				break
			}
		}
		done <- b.String()
	}()
	fn()
	os.Stdout = saved
	_ = w.Close()
	out := <-done
	_ = r.Close()
	return out
}

// useService makes svc what the helpers dial; nil makes dialling fail the test.
func useService(t *testing.T, svc provision.Service) {
	t.Helper()
	saved := helperServer.Dial
	t.Cleanup(func() { helperServer.Dial = saved })
	helperServer.Dial = func(context.Context, *slog.Logger) (provision.Service, error) {
		if svc == nil {
			t.Error("the command dialled the workflow service")
			return nil, context.Canceled
		}
		return svc, nil
	}
}

// fakeClab answers the host's two tools with the output the real ones printed and
// records what it was asked. A docker call is answered from images, the
// references the host is pretending to hold; every other call gets stdout.
type fakeClab struct {
	stdout []byte
	images map[string]bool
	calls  [][]string
}

func (f *fakeClab) Run(_ context.Context, _ []string, args ...string) ([]byte, []byte, int, error) {
	f.calls = append(f.calls, args)
	if args[0] == "docker" {
		ref := args[len(args)-1]
		if f.images[ref] {
			return []byte("sha256:58c3600aacc0c1bd385817e8028fb12f2abb850136ccd9791cec846da82633d4\n"), nil, 0, nil
		}
		return nil, []byte("Error response from daemon: No such image: " + ref + "\n"), 1, nil
	}
	return f.stdout, nil, 0, nil
}

// useClab makes the dry run's containerlab answer with a recording from internal/lab.
func useClab(t *testing.T, recording string) *fakeClab {
	t.Helper()
	b, err := os.ReadFile(repoPath("internal", "lab", "testdata", recording))
	if err != nil {
		t.Fatal(err)
	}
	f := &fakeClab{stdout: b}
	saved := helperServer.Runner
	t.Cleanup(func() { helperServer.Runner = saved })
	helperServer.Runner = f
	return f
}

// dryRunEnv is the CLI's environment for a dry run: the probe login exported, no host
// budget.
func dryRunEnv(t *testing.T) {
	t.Helper()
	t.Setenv("FYLGJA_SRLINUX_USERNAME", "admin")
	t.Setenv("FYLGJA_SRLINUX_PASSWORD", "not-the-real-one")
	t.Setenv(lab.EnvHostMemoryMB, "")
}

// useStateRoot points the state root at a fresh directory for the test.
func useStateRoot(t *testing.T) lab.Paths {
	t.Helper()
	root := t.TempDir()
	t.Setenv(lab.EnvStateRoot, root)
	return lab.PathsAt(root)
}

// copyGoldenBundle copies the golden bundle into a directory named name.
func copyGoldenBundle(t *testing.T, name string) string {
	t.Helper()
	return copyGoldenBundleOf(t, "three-node", name)
}

// copyGoldenBundleOf copies testdata/golden/<golden> into a directory named name.
func copyGoldenBundleOf(t *testing.T, golden, name string) string {
	t.Helper()
	dst := filepath.Join(t.TempDir(), name)
	src := repoPath("testdata", "golden", golden)
	err := filepath.WalkDir(src, func(p string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		rel, err := filepath.Rel(src, p)
		if err != nil {
			return err
		}
		target := filepath.Join(dst, rel)
		if d.IsDir() {
			return os.MkdirAll(target, 0o755)
		}
		b, err := os.ReadFile(p)
		if err != nil {
			return err
		}
		return os.WriteFile(target, b, 0o644)
	})
	if err != nil {
		t.Fatal(err)
	}
	return dst
}

func readyResult() provision.ProvisionResult {
	observed := "2026-09-15T14:22:12.000000Z"
	var nodes []wire.TwinNode
	for i, name := range []string{"n1", "n2", "n3"} {
		nodes = append(nodes, wire.TwinNode{
			Name: name, Container: "clab-fylgja-" + name, Image: "ghcr.io/nokia/srlinux:24.7.1",
			PSP:      &wire.PSPRef{ID: "nokia_srlinux", Source: "embedded"},
			MgmtIPv4: "172.20.20." + string(rune('2'+i)), ReadyAfterS: 0.9,
			Artifact:  &wire.TwinArtifact{Name: "device-config", ContentType: "text/plain", Checksum: fixtureArtifacts[name], Size: 861},
			PushedInS: 0.7,
		})
	}
	return provision.ProvisionResult{
		Outcome:    provision.OutcomeReady,
		BundleID:   fixtureBundleID,
		ObservedAt: observed,
		TwinDir:    "/abs/local/twin",
		Findings:   findings.List{},
		Twin: &wire.TwinRecord{
			TwinVersion: "2", Lab: "fylgja", BundleID: fixtureBundleID,
			Provenance: wire.Provenance{Branch: "fylgja-fixture", SchemaHash: "abc", Scope: "tag:fylgja", Mapping: dcimMapping},
			ObservedAt: &observed, Source: wire.SourceIntent,
			Run:           wire.RunRef{WorkflowID: provision.WorkflowProvision, RunID: "run-1"},
			ProvisionedBy: wire.ProvisionedBy{Version: "0.1.0-dev"},
			RecordedAt:    "2026-09-15T14:22:53Z",
			Nodes:         nodes,
		},
		Cleanup: provision.CleanupResult{Teardown: provision.CleanupSkipped, Unstage: provision.CleanupSkipped},
	}
}

// validateM5Document validates a document against M5's findings contract.
func validateM5Document(t *testing.T, doc *findings.Document) {
	t.Helper()
	validateWithShow(t, "005-configuration", "M5", doc)
}

// validateM6Document validates a document against M6's findings contract.
func validateM6Document(t *testing.T, doc *findings.Document) {
	t.Helper()
	validateWithShow(t, "006-psp-lossy-mapping", "M6", doc)
}

// validateM10Document validates a document against the newest findings contract, under the
// module root's contracts/. 018 is additive: a document that names no snapshot is 017's too,
// so it is also validated against 017's frozen copy, the null snapshot ids taken out
// (as017Contract). 019 removes following: a document of this build is 018's too, as built,
// so it is also validated against 018's frozen copy. 016 moves the step, verify, rehearsal
// and findings contracts on: a document of this build is 019's as built, a null step loss
// taken out (withoutNullLoss), so it is also validated against 019's frozen copy; one whose
// step carries a loss is 016's alone, and is read against no earlier copy.
func validateM10Document(t *testing.T, doc *findings.Document) {
	t.Helper()
	validateWithShow(t, currentContract, "M13", doc)
	// A step document carrying a loss its flows read is 016's, which no earlier contract
	// accepts, as is a rehearsal whose stage carries one.
	if doc.Step != nil && doc.Step.Loss != nil {
		return
	}
	if r := doc.Rehearsal; r != nil && slices.ContainsFunc(r.Stages, func(s findings.RehearsalStage) bool { return s.Loss != nil }) {
		return
	}
	validateWithShow(t, contract019, "019", doc)
	validateWithShow(t, contract018, "018", doc)
	if !namesSnapshot(t, doc) {
		validateWithShow(t, contract017, "017", doc)
	}
}

// contract017 is the feature argument that names 017's copies of the findings contract and
// the four blocks 018 moves, frozen under testdata/contracts/017-dcim-reader/.
const contract017 = "017-dcim-reader"

// contract018 is the feature argument that names 018's copies of the findings contract and
// the show block, the two 019 moves, frozen under testdata/contracts/018-snapshots/.
const contract018 = "018-snapshots"

// contract019 is the feature argument that names 019's copies of the findings contract and
// the step, verify and rehearsal blocks, the four 016 moves, frozen under
// testdata/contracts/019-following-removed/.
const contract019 = "019-following-removed"

// namesSnapshot says whether doc names a snapshot anywhere 018 puts one: such a document is
// 018's, which no earlier contract accepts.
func namesSnapshot(t *testing.T, doc *findings.Document) bool {
	t.Helper()
	b, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	return strings.Contains(string(b), `"snapshot_id":"`) || strings.Contains(string(b), `"snapshot":"`)
}

// dropNullSnapshots removes the snapshot ids 018 writes as null where a block names none:
// the show record's, each plan stage's and each rehearsal stage's. Every contract before
// 018's forbids the key, and from 018 each is always written. An id that is set is left, so
// an earlier contract still refuses a document naming a snapshot.
func dropNullSnapshots(generic map[string]any) {
	dropNull := func(m any) {
		if o, ok := m.(map[string]any); ok {
			if v, ok := o["snapshot_id"]; ok && v == nil {
				delete(o, "snapshot_id")
			}
		}
	}
	if show, ok := generic["show"].(map[string]any); ok {
		dropNull(show["record"])
	}
	for _, block := range []string{"plan", "rehearsal"} {
		if b, ok := generic[block].(map[string]any); ok {
			stages, _ := b["stages"].([]any)
			for _, st := range stages {
				dropNull(st)
			}
		}
	}
}

// withoutNullLoss is b, a document marshalled, with its step block's loss taken out when it
// is null, as the dry run and a run closed before its flows write it (016), and each
// rehearsal stage's, null on every stage whose step read no flow: every contract before
// 016's forbids the key, and from 016 it is always written.
func withoutNullLoss(t *testing.T, b []byte) []byte {
	t.Helper()
	var generic map[string]any
	if err := json.Unmarshal(b, &generic); err != nil {
		t.Fatal(err)
	}
	dropNull := func(m any) {
		if o, ok := m.(map[string]any); ok {
			if v, ok := o["loss"]; ok && v == nil {
				delete(o, "loss")
			}
		}
	}
	dropNull(generic["step"])
	if r, ok := generic["rehearsal"].(map[string]any); ok {
		stages, _ := r["stages"].([]any)
		for _, st := range stages {
			dropNull(st)
		}
	}
	out, err := json.Marshal(generic)
	if err != nil {
		t.Fatal(err)
	}
	return out
}

// as017Contract is doc as 017's contract reads it, marshalled: the null snapshot ids taken
// out, and nothing else.
func as017Contract(t *testing.T, doc *findings.Document) []byte {
	t.Helper()
	b, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	var generic map[string]any
	if err := json.Unmarshal(b, &generic); err != nil {
		t.Fatal(err)
	}
	dropNullSnapshots(generic)
	if b, err = json.Marshal(generic); err != nil {
		t.Fatal(err)
	}
	return b
}

// validateWithShow validates doc against feature's findings contract, with the
// blocks' schemas added under their $ids; 017's reads it as as017Contract gives it.
func validateWithShow(t *testing.T, feature, milestone string, doc *findings.Document) {
	t.Helper()
	b, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	if feature == contract017 {
		b = as017Contract(t, doc)
	}
	if feature != currentContract {
		b = withoutNullLoss(t, b)
	}
	v, err := jsonschema.UnmarshalJSON(bytes.NewReader(b))
	if err != nil {
		t.Fatal(err)
	}
	if err := findingsContract(t, feature).Validate(v); err != nil {
		t.Errorf("document does not satisfy %s's findings contract:\n%v\n%s", milestone, err, b)
	}
}

var findingsContracts = struct {
	sync.Mutex
	byFeature map[string]*jsonschema.Schema
}{byFeature: map[string]*jsonschema.Schema{}}

// currentContract is the feature argument that names the module root's contracts/, which
// holds the current contract. Any other names an older feature's frozen copy, under this
// package's testdata/contracts/<feature>/.
const currentContract = ""

// contractPath is where feature's copy of the contract file name is read.
func contractPath(feature, name string) string {
	if feature == currentContract {
		return repoPath("contracts", name)
	}
	return filepath.Join("testdata", "contracts", feature, name)
}

// laterContract is the next later frozen feature's copy of the block name, or the current
// one when no later copy holds it.
func laterContract(t *testing.T, feature, name string) string {
	t.Helper()
	dirs, err := os.ReadDir(filepath.Join("testdata", "contracts"))
	if err != nil {
		t.Fatal(err)
	}
	for _, d := range dirs {
		if d.Name() <= feature {
			continue
		}
		if path := contractPath(d.Name(), name); fileExists(path) {
			return path
		}
	}
	return contractPath(currentContract, name)
}

func fileExists(path string) bool {
	_, err := os.Stat(path)
	return err == nil
}

// findingsContract returns feature's findings contract, compiled once.
func findingsContract(t *testing.T, feature string) *jsonschema.Schema {
	t.Helper()
	findingsContracts.Lock()
	defer findingsContracts.Unlock()
	if schema, ok := findingsContracts.byFeature[feature]; ok {
		return schema
	}
	load := func(path string) any {
		f, err := os.Open(path)
		if err != nil {
			t.Fatal(err)
		}
		defer func() { _ = f.Close() }()
		v, err := jsonschema.UnmarshalJSON(f)
		if err != nil {
			t.Fatal(err)
		}
		return v
	}
	refers, err := os.ReadFile(contractPath(feature, "findings.schema.json"))
	if err != nil {
		t.Fatal(err)
	}
	c := jsonschema.NewCompiler()
	for _, name := range []string{"show.schema.json", "stages.schema.json", "step.schema.json", "verify.schema.json", "rehearsal.schema.json"} {
		path := contractPath(feature, name)
		if _, err := os.Stat(path); err != nil {
			// A block the feature's contract refers to but its directory does not hold had not
			// moved since the feature: 017's verify.schema.json, which 018 does not move, and
			// 018's stages, step, verify and rehearsal blocks, which 019 does not freeze, and
			// 019's show and stages blocks, which 016 does not move. It is read from the next
			// later frozen copy, which holds it as the feature left it, and from the current
			// contract only when no later copy holds it.
			if feature == currentContract || !strings.Contains(string(refers), "/schemas/"+name) {
				continue
			}
			path = laterContract(t, feature, name)
		}
		if err := c.AddResource("https://github.com/happypathnetworking/fylgja/schemas/"+name, load(path)); err != nil {
			t.Fatal(err)
		}
	}
	if err := c.AddResource("findings.schema.json", load(contractPath(feature, "findings.schema.json"))); err != nil {
		t.Fatal(err)
	}
	schema, err := c.Compile("findings.schema.json")
	if err != nil {
		t.Fatal(err)
	}
	findingsContracts.byFeature[feature] = schema
	return schema
}
