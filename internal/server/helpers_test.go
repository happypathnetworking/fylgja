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

const fixtureBundleID = "23f86a2678a49a324a04ae458703be8252e2e30d6712d6b6094ce1ccd5c2988e"

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
			PSP:      wire.PSPRef{ID: "nokia_srlinux", Source: "embedded"},
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
			Provenance: wire.Provenance{Branch: "fylgja-fixture", SchemaHash: "abc", ContractVersion: "0.2"},
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
// module root's contracts/.
func validateM10Document(t *testing.T, doc *findings.Document) {
	t.Helper()
	validateWithShow(t, currentContract, "M13", doc)
}

// validateWithShow validates doc against feature's findings contract, with the
// blocks' schemas added under their $ids.
func validateWithShow(t *testing.T, feature, milestone string, doc *findings.Document) {
	t.Helper()
	b, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
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

// findingsContract returns feature's findings contract, compiled once.
func findingsContract(t *testing.T, feature string) *jsonschema.Schema {
	t.Helper()
	findingsContracts.Lock()
	defer findingsContracts.Unlock()
	if schema, ok := findingsContracts.byFeature[feature]; ok {
		return schema
	}
	load := func(name string) any {
		f, err := os.Open(contractPath(feature, name))
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
	c := jsonschema.NewCompiler()
	if err := c.AddResource("https://fylgja.dev/schemas/show.schema.json", load("show.schema.json")); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"waypoints.schema.json", "step.schema.json", "verify.schema.json"} {
		if _, err := os.Stat(contractPath(feature, name)); err == nil {
			if err := c.AddResource("https://fylgja.dev/schemas/"+name, load(name)); err != nil {
				t.Fatal(err)
			}
		}
	}
	if err := c.AddResource("findings.schema.json", load("findings.schema.json")); err != nil {
		t.Fatal(err)
	}
	schema, err := c.Compile("findings.schema.json")
	if err != nil {
		t.Fatal(err)
	}
	findingsContracts.byFeature[feature] = schema
	return schema
}
