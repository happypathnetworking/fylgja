package cli

import (
	"bytes"
	"encoding/json"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

func repoPath(parts ...string) string {
	return filepath.Join(append([]string{"..", ".."}, parts...)...)
}

// runCompileTo runs the command exactly as the CLI does and returns the exit code.
func runCompileTo(t *testing.T, ctmPath, out string) (int, *findingsDoc) {
	t.Helper()
	return runCompileWith(t, &options{asJSON: true}, ctmPath, out)
}

// runCompileWith is runCompileTo with the caller's options, such as --psp-dir.
func runCompileWith(t *testing.T, opts *options, ctmPath, out string) (int, *findingsDoc) {
	t.Helper()
	err := runCompile(opts, &compileFlags{ctmPath: ctmPath, out: out})
	var res *result
	if !asResult(err, &res) {
		t.Fatalf("runCompile returned %v, want a findings result", err)
	}
	b, mErr := json.Marshal(res.doc)
	if mErr != nil {
		t.Fatal(mErr)
	}
	var doc findingsDoc
	if err := json.Unmarshal(b, &doc); err != nil {
		t.Fatal(err)
	}
	return res.doc.Status.ExitCode(), &doc
}

// findingsDoc is the document as a consumer reads it, rather than as the program
// builds it: asserting on the serialized shape is what makes these tests about the
// contract instead of about the struct.
type findingsDoc struct {
	Operation string `json:"operation"`
	Status    string `json:"status"`
	BundleID  string `json:"bundle_id"`
	Verified  *struct {
		ContractVersion string `json:"contract_version"`
		Generics        []struct {
			Generic string   `json:"generic"`
			Kinds   []string `json:"kinds"`
		} `json:"generics"`
	} `json:"verified"`
	Findings []struct {
		Severity string `json:"severity"`
		Rule     string `json:"rule"`
		Object   string `json:"object"`
		Message  string `json:"message"`
		// Support-package findings point into a file; intent findings do not
		// carry one at all, so the field is a pointer.
		Location *struct {
			File string `json:"file"`
			Line int    `json:"line"`
		} `json:"location"`
	} `json:"findings"`
}

func asResult(err error, target **result) bool {
	res, ok := err.(*result)
	if ok {
		*target = res
	}
	return ok
}

// `twin compile` must run the identical function the golden test runs, or the golden
// test stops being evidence about the command (Constitution V). Comparing the
// bytes on disk with the bytes compiler.Compile returns is what proves there is no
// second path.
func TestCommandAndGoldenShareTheCompilerPath(t *testing.T) {
	out := filepath.Join(t.TempDir(), "b")
	code, doc := runCompileTo(t, repoPath("testdata", "ctm", "three-node.json"), out)
	if code != 0 {
		t.Fatalf("exit %d: %+v", code, doc.Findings)
	}

	c, err := ctm.Load(repoPath("testdata", "ctm", "three-node.json"))
	if err != nil {
		t.Fatal(err)
	}
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	want, list := compiler.Compile(c, reg)
	if list.Rejected() {
		t.Fatalf("the fixture was rejected: %v", list)
	}

	for name, content := range want {
		got, err := os.ReadFile(filepath.Join(out, filepath.FromSlash(name)))
		if err != nil {
			t.Errorf("reading %s: %v", name, err)
			continue
		}
		if string(got) != string(content) {
			t.Errorf("%s written by the command differs from compiler.Compile", name)
		}
	}

	// And the id the command printed is the id of what it wrote.
	if doc.BundleID != bundle.ID(want) {
		t.Errorf("printed bundle_id %s, want %s", doc.BundleID, bundle.ID(want))
	}
	fromDir, err := bundle.IDOfDir(out)
	if err != nil {
		t.Fatal(err)
	}
	if doc.BundleID != fromDir {
		t.Errorf("printed bundle_id %s, directory hashes to %s", doc.BundleID, fromDir)
	}
}

// Compiling the same CTM twice must give the same id, and the bundle must match the
// committed golden — the command's own proof that a compile is reproducible.
func TestCommandIsDeterministic(t *testing.T) {
	root := t.TempDir()
	_, first := runCompileTo(t, repoPath("testdata", "ctm", "three-node.json"), filepath.Join(root, "b1"))
	_, second := runCompileTo(t, repoPath("testdata", "ctm", "three-node.shuffled.json"), filepath.Join(root, "b2"))
	if first.BundleID != second.BundleID {
		t.Errorf("bundle_id differs across input order: %s vs %s", first.BundleID, second.BundleID)
	}
	golden, err := bundle.IDOfDir(repoPath("testdata", "golden", "three-node"))
	if err != nil {
		t.Fatal(err)
	}
	if first.BundleID != golden {
		t.Errorf("the command's bundle_id %s does not match the golden bundle %s", first.BundleID, golden)
	}
}

// containerlab gives every node a management connection whether or not intent flags a
// mgmt_only interface, so the manifest records the platform's management port for
// every node — including a device with no interfaces at all.
func TestEveryNodeGetsTheManagementPort(t *testing.T) {
	out := filepath.Join(t.TempDir(), "b")
	if code, doc := runCompileTo(t, repoPath("testdata", "ctm", "no-mgmt.json"), out); code != 0 {
		t.Fatalf("exit %d: %+v", code, doc.Findings)
	}
	b, err := os.ReadFile(filepath.Join(out, compiler.ManifestFile))
	if err != nil {
		t.Fatal(err)
	}
	var m compiler.Manifest
	if err := json.Unmarshal(b, &m); err != nil {
		t.Fatal(err)
	}
	if len(m.Nodes) == 0 {
		t.Fatal("no nodes in the manifest")
	}
	byName := map[string]compiler.ManifestNode{}
	for _, n := range m.Nodes {
		if n.ManagementPort == "" {
			t.Errorf("node %s has no management port", n.Name)
		}
		byName[n.Name] = n
	}
	// n2 has data ports but no mgmt_only interface; n4 has no interfaces at all.
	for _, name := range []string{"n2", "n4"} {
		n, ok := byName[name]
		if !ok {
			t.Fatalf("node %s is missing from the manifest", name)
		}
		if n.ManagementPort != "mgmt0" {
			t.Errorf("node %s management port = %q, want the platform's mgmt0", name, n.ManagementPort)
		}
	}
}

// Flags the compiler cannot run without are operational failures, not rejections:
// nothing was validated, so there is nothing to report findings about.
func TestMissingFlagsAreOperationalFailures(t *testing.T) {
	for _, tc := range []struct {
		label string
		flags compileFlags
	}{
		{"no --ctm", compileFlags{out: "/tmp/x"}},
		{"no --out", compileFlags{ctmPath: repoPath("testdata", "ctm", "three-node.json")}},
	} {
		t.Run(tc.label, func(t *testing.T) {
			f := tc.flags
			err := runCompile(&options{asJSON: true}, &f)
			var res *result
			if !asResult(err, &res) {
				t.Fatalf("got %v, want a findings result", err)
			}
			if got := res.doc.Status.ExitCode(); got != 2 {
				t.Errorf("exit %d, want 2", got)
			}
		})
	}
}

// An artifact named as the package's startup_format was written over the node's
// bootstrap, and `twin compile` exited 0 with a bundle whose n1 would boot on
// intent-derived content. It is refused as artifact.missing, exit 1,
// and nothing is written.
func TestCompileRefusesAnArtifactNotNamedAsItsPackageNamesIt(t *testing.T) {
	c, err := ctm.Load(repoPath("testdata", "ctm", "three-node.json"))
	if err != nil {
		t.Fatal(err)
	}
	for i := range c.Devices {
		if c.Devices[i].Name == "n1" {
			c.Devices[i].Artifact.Name = "cli"
		}
	}
	dir := t.TempDir()
	in := filepath.Join(dir, "renamed.ctm.json")
	if err := ctm.Save(c, in); err != nil {
		t.Fatal(err)
	}
	out := filepath.Join(dir, "b")

	code, doc := runCompileTo(t, in, out)
	if code != 1 {
		t.Errorf("exit %d, want 1", code)
	}
	if _, err := os.Stat(out); !os.IsNotExist(err) {
		t.Errorf("something was written to %s", out)
	}
	if doc.BundleID != "" {
		t.Errorf("the document names bundle %s", doc.BundleID)
	}
	var named []string
	for _, f := range doc.Findings {
		if f.Rule == findings.RuleArtifactMissing {
			named = append(named, f.Object)
		}
	}
	if strings.Join(named, ",") != "n1" {
		t.Errorf("artifact.missing names %v, want n1 once; findings: %+v", named, doc.Findings)
	}
}

// Two cabled interfaces of one device that the design-case package renders to one port
// are refused through the command as the package's --psp-dir gives it: exit 1, the
// collision naming the port and both interfaces with their rules, and nothing written.
// The other mapping refusals are worded by the
// same function; TestMappingRefusalsAreWordedAlike holds them to it.
func TestCompileRefusesAPortCollision(t *testing.T) {
	out := filepath.Join(t.TempDir(), "b")
	usePSPDir(t, repoPath("testdata", "psp", "lossy"))
	code, doc := runCompileWith(t, &options{asJSON: true},
		repoPath("testdata", "ctm", "defects", "port-collision.json"), out)
	if code != 1 {
		t.Errorf("exit %d, want 1", code)
	}
	if _, err := os.Stat(out); !os.IsNotExist(err) {
		t.Errorf("something was written to %s", out)
	}
	if doc.BundleID != "" {
		t.Errorf("the document names bundle %s", doc.BundleID)
	}
	const want = "port eth1 on c1 would be cabled twice: Ethernet1/1 (rule front) and Ethernet2/1 (rule linecard) both land on it; a bundle whose links cable one port twice is never produced"
	if len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleInterfacePortCollision ||
		doc.Findings[0].Object != "c1:eth1" || doc.Findings[0].Message != want {
		t.Errorf("findings %+v\nwant one %s naming c1:eth1: %s", doc.Findings, findings.RuleInterfacePortCollision, want)
	}
}

// An unreadable or malformed CTM is exit 2 as well: the file could not be interpreted,
// which is a different thing from intent that could be interpreted and was wrong.
func TestUnreadableCTMIsAnOperationalFailure(t *testing.T) {
	dir := t.TempDir()
	bad := filepath.Join(dir, "bad.json")
	if err := os.WriteFile(bad, []byte(`{"ctm_version":"1","typo":true}`), 0o644); err != nil {
		t.Fatal(err)
	}
	wrongVersion := filepath.Join(dir, "v2.json")
	if err := os.WriteFile(wrongVersion, []byte(`{"ctm_version":"2","envelope":{"branch":"b",
	  "observed_at":"x","schema_hash":"h","contract_version":"0.2"},"devices":[],"links":[]}`), 0o644); err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{bad, wrongVersion, filepath.Join(dir, "missing.json")} {
		t.Run(filepath.Base(path), func(t *testing.T) {
			out := filepath.Join(t.TempDir(), "b")
			code, _ := runCompileTo(t, path, out)
			if code != 2 {
				t.Errorf("exit %d, want 2", code)
			}
			if _, err := os.Stat(out); !os.IsNotExist(err) {
				t.Errorf("something was written to %s", out)
			}
		})
	}
}

// A golden CTM sent through the API comes back as its golden bundle, byte for byte: the
// server's compile is the code path the golden tests run, so the client writes what
// compiler.Compile wrote.
// The lossy golden compiles with the test-only package beside the embedded ones, as
// internal/compiler's golden test loads it.
func TestGoldenCTMsComeBackAsTheGoldenBundles(t *testing.T) {
	for _, c := range []struct {
		golden, ctm, pspDir string
	}{
		{"three-node", "three-node.json", ""},
		{"lossy", "lossy.json", repoPath("testdata", "psp", "lossy")},
		{"mixed", "mixed.json", ""},
	} {
		t.Run(c.golden, func(t *testing.T) {
			if c.pspDir != "" {
				usePSPDir(t, c.pspDir)
			}
			golden := repoPath("testdata", "golden", c.golden)
			out := filepath.Join(t.TempDir(), "bundle")
			code, doc := runCompileTo(t, repoPath("testdata", "ctm", c.ctm), out)
			if code != findings.ExitOK {
				t.Fatalf("exit %d: %+v", code, doc.Findings)
			}
			sameTree(t, out, golden)
			if want := idOfDir(t, golden); doc.BundleID != want {
				t.Errorf("bundle_id %s, want the golden's %s", doc.BundleID, want)
			}
		})
	}
}

// sameTree holds got to want as diff -r does: the same entries, each of the same kind, and
// every regular file's bytes equal, read from both sides.
func sameTree(t *testing.T, got, want string) {
	t.Helper()
	gotTree, wantTree := treeOf(t, got), treeOf(t, want)
	for name, w := range wantTree {
		g, ok := gotTree[name]
		switch {
		case !ok:
			t.Errorf("only in %s: %s", want, name)
		case g.dir != w.dir:
			t.Errorf("%s is a directory on one side and a file on the other", name)
		case !bytes.Equal(g.data, w.data):
			t.Errorf("%s differs:\n--- got\n%s\n--- want\n%s", name, g.data, w.data)
		}
	}
	for name := range gotTree {
		if _, ok := wantTree[name]; !ok {
			t.Errorf("only in %s: %s", got, name)
		}
	}
	if len(wantTree) == 0 {
		t.Fatalf("%s holds nothing, so the comparison proves nothing", want)
	}
}

// treeEntry is one entry under a directory: a directory, or a regular file and its bytes.
type treeEntry struct {
	dir  bool
	data []byte
}

// treeOf is every entry under root by its slash-separated path; anything that is neither a
// directory nor a regular file fails the test.
func treeOf(t *testing.T, root string) map[string]treeEntry {
	t.Helper()
	entries := map[string]treeEntry{}
	err := filepath.WalkDir(root, func(p string, d fs.DirEntry, err error) error {
		if err != nil || p == root {
			return err
		}
		rel, err := filepath.Rel(root, p)
		if err != nil {
			return err
		}
		switch {
		case d.IsDir():
			entries[filepath.ToSlash(rel)] = treeEntry{dir: true}
		case d.Type().IsRegular():
			b, err := os.ReadFile(p)
			if err != nil {
				return err
			}
			entries[filepath.ToSlash(rel)] = treeEntry{data: b}
		default:
			t.Errorf("%s is neither a directory nor a regular file", p)
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	return entries
}
