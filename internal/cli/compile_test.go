package cli

import (
	"bytes"
	"encoding/json"
	"io/fs"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/psp"
	snap "github.com/happypathnetworking/fylgja/internal/snapshot"
)

func repoPath(parts ...string) string {
	return filepath.Join(append([]string{"..", ".."}, parts...)...)
}

// wrappedFixture is testdata/snapshot/<name>.json, a fixture CTM wrapped as a snapshot,
// which compiles to testdata/golden/<name>/ (018).
func wrappedFixture(name string) string {
	return repoPath("testdata", "snapshot", name+".json")
}

// wrappedCTM wraps the bare CTM file at path by hand, as contracts/cli.md tells a hand user
// to (018): {"snapshot_version": "1", "ctm": <the CTM>, "probes": []}, leaving out the
// snapshot_id the server computes and the observed_at it fills from the CTM. The CTM is
// wrapped as its bytes, so a CTM the server refuses is sent as it is. The snapshot is
// written to a temporary file named as the CTM, whose path it returns.
func wrappedCTM(t *testing.T, path string) string {
	t.Helper()
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	wrapped := filepath.Join(t.TempDir(), filepath.Base(path))
	if err := os.WriteFile(wrapped, []byte(`{"snapshot_version": "1", "ctm": `+string(raw)+`, "probes": []}`), 0o644); err != nil {
		t.Fatal(err)
	}
	return wrapped
}

// wrappedCTMOf is wrappedCTM of c, written as ctm.Save writes it.
func wrappedCTMOf(t *testing.T, c *ctm.CTM) string {
	t.Helper()
	in := filepath.Join(t.TempDir(), "edited.ctm.json")
	if err := ctm.Save(c, in); err != nil {
		t.Fatal(err)
	}
	return wrappedCTM(t, in)
}

// runCompileTo runs the command exactly as the CLI does and returns the exit code.
func runCompileTo(t *testing.T, snapshotPath, out string) (int, *findingsDoc) {
	t.Helper()
	return runCompileWith(t, &options{asJSON: true}, snapshotPath, out)
}

// runCompileWith is runCompileTo with the caller's options, such as --psp-dir.
func runCompileWith(t *testing.T, opts *options, snapshotPath, out string) (int, *findingsDoc) {
	t.Helper()
	err := runCompile(opts, &compileFlags{snapshotPath: snapshotPath, out: out})
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
	Operation  string `json:"operation"`
	Status     string `json:"status"`
	SnapshotID string `json:"snapshot_id"`
	BundleID   string `json:"bundle_id"`
	Subject    *struct {
		Snapshot string `json:"snapshot"`
		CTM      string `json:"ctm"`
	} `json:"subject"`
	Verified *struct {
		Model   string                `json:"model"`
		Version string                `json:"version"`
		Kinds   []findings.KindFields `json:"kinds"`
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
	code, doc := runCompileTo(t, wrappedFixture("three-node"), out)
	if code != 0 {
		t.Fatalf("exit %d: %+v", code, doc.Findings)
	}

	s, err := snap.Load(wrappedFixture("three-node"))
	if err != nil {
		t.Fatal(err)
	}
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	want, list := compiler.Compile(s.CTM, nil, reg, nil)
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
// committed golden — the command's own proof that a compile is reproducible. The snapshot's
// id does not move with the CTM's order either (018).
func TestCommandIsDeterministic(t *testing.T) {
	root := t.TempDir()
	_, first := runCompileTo(t, wrappedFixture("three-node"), filepath.Join(root, "b1"))
	_, second := runCompileTo(t, wrappedCTM(t, repoPath("testdata", "ctm", "three-node.shuffled.json")), filepath.Join(root, "b2"))
	if first.BundleID != second.BundleID {
		t.Errorf("bundle_id differs across input order: %s vs %s", first.BundleID, second.BundleID)
	}
	if first.SnapshotID != fixtureSnapshotID || second.SnapshotID != fixtureSnapshotID {
		t.Errorf("snapshot_id %s and %s across input order, want %s for both", first.SnapshotID, second.SnapshotID, fixtureSnapshotID)
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
	if code, doc := runCompileTo(t, wrappedCTM(t, repoPath("testdata", "ctm", "no-mgmt.json")), out); code != 0 {
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
		label, says string
		flags       compileFlags
	}{
		{"no --snapshot", "--snapshot is required", compileFlags{out: "/tmp/x"}},
		{"no --out", "--out is required", compileFlags{snapshotPath: wrappedFixture("three-node")}},
	} {
		t.Run(tc.label, func(t *testing.T) {
			f := tc.flags
			err := runCompile(&options{asJSON: true}, &f)
			var res *result
			if !asResult(err, &res) {
				t.Fatalf("got %v, want a findings result", err)
			}
			if got := res.doc.Status.ExitCode(); got != 2 || len(res.doc.Findings) != 1 || res.doc.Findings[0].Message != tc.says {
				t.Errorf("exit %d, findings %+v; want 2 saying %q", got, res.doc.Findings, tc.says)
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
	out := filepath.Join(t.TempDir(), "b")

	code, doc := runCompileTo(t, wrappedCTMOf(t, c), out)
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
		wrappedCTM(t, repoPath("testdata", "ctm", "defects", "port-collision.json")), out)
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

// An unreadable or malformed snapshot is exit 2 as well: the file could not be
// interpreted, which is a different thing from intent that could be interpreted and was
// wrong. A snapshot that is not JSON, one whose CTM does not decode (a key the CTM does not
// hold, an envelope of M1's contract), and a file the client cannot read are each that. A
// snapshot or a CTM of another version is neither: it is refused under its own rule, exit 1
// (TestCompileReadsASnapshotByItsRules).
func TestUnreadableSnapshotIsAnOperationalFailure(t *testing.T) {
	dir := t.TempDir()
	write := func(name, body string) string {
		path := filepath.Join(dir, name)
		if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
			t.Fatal(err)
		}
		return path
	}
	for _, c := range []struct{ path, says string }{
		{write("not-json.json", `{"snapshot_version":"1",`), "decoding snapshot: "},
		{write("bad.json", `{"snapshot_version":"1","ctm":{"ctm_version":"2","typo":true},"probes":[]}`), "in the snapshot's ctm: "},
		{write("v2.json", `{"snapshot_version":"1","ctm":{"ctm_version":"2","envelope":{"branch":"b",
		  "observed_at":"x","schema_hash":"h","contract_version":"0.2"},"devices":[],"links":[]},"probes":[]}`), "in the snapshot's ctm: "},
		{filepath.Join(dir, "missing.json"), "reading snapshot: open " + filepath.Join(dir, "missing.json") + ": no such file or directory"},
	} {
		t.Run(filepath.Base(c.path), func(t *testing.T) {
			out := filepath.Join(t.TempDir(), "b")
			code, doc := runCompileTo(t, c.path, out)
			if code != 2 || len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleOperationFailed ||
				!strings.HasPrefix(doc.Findings[0].Message, c.says) {
				t.Errorf("exit %d, findings %+v; want 2, operation.failed saying %q", code, doc.Findings, c.says)
			}
			if _, err := os.Stat(out); !os.IsNotExist(err) {
				t.Errorf("something was written to %s", out)
			}
		})
	}
}

// Each wrapped fixture sent through the API comes back as its golden bundle, byte for byte:
// the server's compile is the code path the golden tests run, so the client writes what
// compiler.Compile wrote. The document names the snapshot the file declares, and nothing is
// filed: the state root's snapshots/ stays absent (018, US4 scenario 1).
// The lossy golden compiles with the test-only package beside the embedded ones, as
// internal/compiler's golden test loads it.
func TestWrappedFixturesComeBackAsTheGoldenBundles(t *testing.T) {
	for _, c := range []struct {
		golden, pspDir string
	}{
		{"three-node", ""},
		{"lossy", repoPath("testdata", "psp", "lossy")},
		{"mixed", ""},
	} {
		t.Run(c.golden, func(t *testing.T) {
			paths := useStateRoot(t)
			if c.pspDir != "" {
				usePSPDir(t, c.pspDir)
			}
			golden := repoPath("testdata", "golden", c.golden)
			out := filepath.Join(t.TempDir(), "bundle")
			code, doc := runCompileTo(t, wrappedFixture(c.golden), out)
			if code != findings.ExitOK {
				t.Fatalf("exit %d: %+v", code, doc.Findings)
			}
			sameTree(t, out, golden)
			if want := idOfDir(t, golden); doc.BundleID != want {
				t.Errorf("bundle_id %s, want the golden's %s", doc.BundleID, want)
			}
			s, err := snap.Load(wrappedFixture(c.golden))
			if err != nil {
				t.Fatal(err)
			}
			if doc.SnapshotID != s.ID || doc.Subject == nil || doc.Subject.Snapshot != wrappedFixture(c.golden) || doc.Subject.CTM != "" {
				t.Errorf("snapshot_id %s, subject %+v; want the file's %s, and the file as the snapshot", doc.SnapshotID, doc.Subject, s.ID)
			}
			if _, err := os.Stat(paths.Snapshots); !os.IsNotExist(err) {
				t.Errorf("snapshots/ exists after a compile (%v): twin compile files nothing", err)
			}
		})
	}
}

// A bare CTM wrapped by hand, declaring neither its snapshot_id nor its observed_at,
// compiles: the server computes the one and fills the other, and the snapshot is the one
// the shipped wrap names, since neither is in what its id hashes (US4 scenario 3).
func TestAHandWrappedCTMCompiles(t *testing.T) {
	out := filepath.Join(t.TempDir(), "bundle")
	code, doc := runCompileTo(t, wrappedCTM(t, repoPath("testdata", "ctm", "three-node.json")), out)
	if code != findings.ExitOK || doc.SnapshotID != fixtureSnapshotID || doc.BundleID != fixtureBundleID {
		t.Fatalf("exit %d, snapshot %q, bundle %q, findings %+v; want 0, %s and %s", code, doc.SnapshotID, doc.BundleID,
			doc.Findings, fixtureSnapshotID, fixtureBundleID)
	}
	sameTree(t, out, repoPath("testdata", "golden", "three-node"))
}

// twin compile reads a snapshot and nothing else: a bare CTM, which declares no
// snapshot_version, is snapshot.version.unsupported at the file, and a snapshot wrapping a
// CTM "1" is ctm.version.unsupported at the file, each exit 1 with no step, nothing written
// and no id named (R-03; contracts/cli.md, "018: snapshots").
func TestCompileReadsASnapshotByItsRules(t *testing.T) {
	bare := repoPath("testdata", "ctm", "three-node.json")
	versionOne := wrappedCTM(t, repoPath("testdata", "ctm", "defects", "version-1.json"))
	for _, c := range []struct {
		name, path, rule, message string
	}{
		{"a bare CTM", bare, findings.RuleSnapshotVersionUnsupported,
			`the snapshot declares no snapshot_version; this build reads "1" and "2", and nothing converts one`},
		{"a wrapped CTM 1", versionOne, findings.RuleCTMVersionUnsupported,
			`the CTM declares ctm_version "1"; this build reads "2", and nothing converts one`},
	} {
		t.Run(c.name, func(t *testing.T) {
			out := filepath.Join(t.TempDir(), "b")
			code, doc := runCompileTo(t, c.path, out)
			if code != findings.ExitRejected || len(doc.Findings) != 1 || doc.Findings[0].Rule != c.rule ||
				doc.Findings[0].Object != c.path || doc.Findings[0].Message != c.message {
				t.Errorf("exit %d, findings %+v; want 1, one %s at %s: %s", code, doc.Findings, c.rule, c.path, c.message)
			}
			if doc.SnapshotID != "" || doc.BundleID != "" {
				t.Errorf("a refused snapshot names snapshot %q, bundle %q", doc.SnapshotID, doc.BundleID)
			}
			if _, err := os.Stat(out); !os.IsNotExist(err) {
				t.Errorf("something was written to %s", out)
			}
		})
	}
}

// --ctm is retired (018): cobra answers its own unknown flag, exit 2, and the client sends
// no request, so no server sees it; the help names --snapshot, and how a bare CTM is
// wrapped.
func TestCompileTakesNoCTM(t *testing.T) {
	awaitIdle(t)
	before := requestsLogged()
	opts := &options{}
	root := &cobra.Command{Use: "fylgja", SilenceUsage: true, SilenceErrors: true}
	root.PersistentFlags().BoolVar(&opts.asJSON, "json", false, "")
	root.AddCommand(newTwinCmd(opts))
	// --json comes first: cobra stops reading flags at the unknown one.
	root.SetArgs([]string{"--json", "twin", "compile", "--ctm", repoPath("testdata", "ctm", "three-node.json"),
		"--out", filepath.Join(t.TempDir(), "b")})
	var code int
	out := captureStdout(t, func() {
		cmd, err := root.ExecuteC()
		code = report(opts, cmd, err)
	})
	var doc findings.Document
	if err := json.Unmarshal([]byte(out), &doc); err != nil {
		t.Fatalf("stdout is not one findings document: %v\n%s", err, out)
	}
	if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0].Message != "unknown flag: --ctm" {
		t.Errorf("exit %d, findings %+v; want 2, cobra's unknown flag", code, doc.Findings)
	}
	awaitIdle(t)
	if got := requestsLogged(); got != before {
		t.Errorf("the server logged %d requests, want none", got-before)
	}

	help := &cobra.Command{Use: "fylgja"}
	help.AddCommand(newTwinCmd(&options{}))
	help.SetArgs([]string{"twin", "compile", "--help"})
	text := captureStdout(t, func() {
		if err := help.Execute(); err != nil {
			t.Error(err)
		}
	})
	for _, want := range []string{"--snapshot string", "the snapshot file to compile (required)",
		`{"snapshot_version": "1", "ctm": <the CTM>, "probes": []}`} {
		if !strings.Contains(text, want) {
			t.Errorf("the help does not say %q:\n%s", want, text)
		}
	}
	if strings.Contains(text, "--ctm") {
		t.Errorf("the help names --ctm:\n%s", text)
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

// A CTM whose envelope is not of its contract's forms is refused by twin compile before
// anything is written, exit 1, naming the field (017, T084): a scope that is not
// tag:<name>, a reader's name of another form, and a fidelity row of an unknown
// disposition or with a field left empty would each compile to a manifest
// contracts/manifest.schema.json refuses, and twin provision of it to a record
// twin.schema.json refuses.
func TestCompileRefusesAnEnvelopeOfAnotherForm(t *testing.T) {
	for _, c := range []struct {
		name, object string
		change       func(*ctm.Envelope)
	}{
		{"scope fylgja", "envelope.scope", func(e *ctm.Envelope) { e.Scope = "fylgja" }},
		{"scope tag:", "envelope.scope", func(e *ctm.Envelope) { e.Scope = "tag:" }},
		{"scope tag:a b", "envelope.scope", func(e *ctm.Envelope) { e.Scope = "tag:a b" }},
		{"reader Infrahub DCIM", "envelope.mapping.reader", func(e *ctm.Envelope) { e.Mapping.Reader = "Infrahub DCIM" }},
		{"a row of disposition bogus", "envelope.fidelity[2].disposition", func(e *ctm.Envelope) {
			e.Fidelity = append(e.Fidelity, ctm.FidelityRow{Disposition: "bogus", Object: "c-9", Source: "DcimCable", Reason: "other than two ends (3)"})
		}},
		{"a row with no reason", "envelope.fidelity[2].reason", func(e *ctm.Envelope) {
			e.Fidelity = append(e.Fidelity, ctm.FidelityRow{Disposition: ctm.FidelityOmitted, Object: "c-9", Source: "DcimCable"})
		}},
	} {
		t.Run(c.name, func(t *testing.T) {
			edited, err := ctm.Load(repoPath("testdata", "ctm", "three-node.json"))
			if err != nil {
				t.Fatal(err)
			}
			c.change(&edited.Envelope)
			out := filepath.Join(t.TempDir(), "b")

			code, doc := runCompileTo(t, wrappedCTMOf(t, edited), out)
			if code != findings.ExitRejected || len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleRequiredMissing ||
				doc.Findings[0].Object != c.object || doc.Findings[0].Severity != string(findings.Rejection) {
				t.Errorf("exit %d, findings %+v; want 1 with %s naming %s alone", code, doc.Findings, findings.RuleRequiredMissing, c.object)
			}
			if _, err := os.Stat(out); !os.IsNotExist(err) {
				t.Errorf("something was written to %s", out)
			}
			if doc.BundleID != "" {
				t.Errorf("the document names bundle %s", doc.BundleID)
			}
		})
	}
}
