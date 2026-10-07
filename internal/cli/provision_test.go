package cli

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io/fs"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/compiler"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/lab"
	"github.com/happypathnetworking/fylgja/internal/lab/wire"
	"github.com/happypathnetworking/fylgja/internal/provision"
)

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

func writeFile(t *testing.T, path, content string) {
	t.Helper()
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

// Each bundle refusal exits 1 under its own identifier, at step verify, before any run is
// started or anything is filed (contracts/cli.md, provision steps 1–4).
func TestProvisionRefusesABundleBeforeDialling(t *testing.T) {
	for _, c := range []struct {
		name    string
		rule    string
		prepare func(t *testing.T, paths lab.Paths) (dir, object string)
	}{
		{"not a bundle", findings.RuleBundleInvalid, func(t *testing.T, _ lab.Paths) (string, string) {
			dir := copyGoldenBundle(t, "b")
			if err := os.Remove(filepath.Join(dir, "manifest.json")); err != nil {
				t.Fatal(err)
			}
			return dir, dir
		}},
		{"a format this build does not deploy", findings.RuleBundleVersionUnsupported, func(t *testing.T, _ lab.Paths) (string, string) {
			dir := copyGoldenBundle(t, "b")
			path := filepath.Join(dir, "manifest.json")
			b, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			// M4's format: no configuration file, no artifact entry.
			writeFile(t, path, strings.Replace(string(b),
				`"bundle_version": "`+compiler.BundleVersion+`"`, `"bundle_version": "1"`, 1))
			return dir, dir
		}},
		// M6's format: every node has its artifact, but nothing says how each node's
		// bootstrap reaches it, so a node whose package pushes its bootstrap would boot
		// with containerlab's default alone. Refused before any run starts, as "1" is.
		{"a bundle from M6's format", findings.RuleBundleVersionUnsupported, func(t *testing.T, _ lab.Paths) (string, string) {
			dir := copyGoldenBundle(t, "b")
			path := filepath.Join(dir, "manifest.json")
			b, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			writeFile(t, path, strings.Replace(string(b),
				`"bundle_version": "`+compiler.BundleVersion+`"`, `"bundle_version": "2"`, 1))
			return dir, dir
		}},
		// M11's format: deployable as M11 deployed it, but its mapping rows say nothing of
		// which ports intent disables, so a twin staged from it would have verify assert
		// them. Refused before any run starts, as "2" is (contracts/cli.md,
		// twin provision).
		{"a bundle from M11's format", findings.RuleBundleVersionUnsupported, func(t *testing.T, _ lab.Paths) (string, string) {
			dir := copyGoldenBundle(t, "b")
			path := filepath.Join(dir, "manifest.json")
			b, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			writeFile(t, path, strings.Replace(string(b),
				`"bundle_version": "`+compiler.BundleVersion+`"`, `"bundle_version": "3"`, 1))
			return dir, dir
		}},
		// A manifest of this build's format promises a bootstrap entry for every node, and
		// the run reads the file from it.
		{"a manifest naming no bootstrap for a node", findings.RuleBundleInvalid, func(t *testing.T, _ lab.Paths) (string, string) {
			dir := copyGoldenBundle(t, "b")
			path := filepath.Join(dir, "manifest.json")
			b, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			var m map[string]any
			if err := json.Unmarshal(b, &m); err != nil {
				t.Fatal(err)
			}
			delete(m["nodes"].([]any)[1].(map[string]any), "bootstrap")
			out, err := json.MarshalIndent(m, "", "  ")
			if err != nil {
				t.Fatal(err)
			}
			writeFile(t, path, string(out)+"\n")
			return dir, dir
		}},
		{"a manifest naming a bootstrap file the bundle lacks", findings.RuleBundleInvalid, func(t *testing.T, _ lab.Paths) (string, string) {
			dir := copyGoldenBundle(t, "b")
			if err := os.Remove(filepath.Join(dir, "configs", "n3.cli")); err != nil {
				t.Fatal(err)
			}
			return dir, dir
		}},
		// A "2" manifest that names no artifact for a node, or a file the bundle lacks, is
		// refused here rather than at the push step, a minute and a teardown later.
		{"a manifest naming no artifact for a node", findings.RuleBundleInvalid, func(t *testing.T, _ lab.Paths) (string, string) {
			dir := copyGoldenBundle(t, "b")
			path := filepath.Join(dir, "manifest.json")
			b, err := os.ReadFile(path)
			if err != nil {
				t.Fatal(err)
			}
			var m map[string]any
			if err := json.Unmarshal(b, &m); err != nil {
				t.Fatal(err)
			}
			delete(m["nodes"].([]any)[1].(map[string]any), "artifact")
			out, err := json.MarshalIndent(m, "", "  ")
			if err != nil {
				t.Fatal(err)
			}
			writeFile(t, path, string(out)+"\n")
			return dir, dir
		}},
		{"a manifest naming an artifact file the bundle lacks", findings.RuleBundleInvalid, func(t *testing.T, _ lab.Paths) (string, string) {
			dir := copyGoldenBundle(t, "b")
			if err := os.Remove(filepath.Join(dir, "configs", "n3.device-config")); err != nil {
				t.Fatal(err)
			}
			return dir, dir
		}},
		// A manifest whose entry does not describe its artifact's bytes is refused here,
		// not filed under the id its bytes hash to and failed at the push step after a
		// deploy.
		{"a manifest whose artifact checksum is not the file's", findings.RuleBundleInvalid, func(t *testing.T, _ lab.Paths) (string, string) {
			dir := copyGoldenBundle(t, "b")
			editManifestEntry(t, dir, 0, "checksum", strings.Repeat("0", 32))
			return dir, dir
		}},
		{"a manifest whose artifact size is not the file's", findings.RuleBundleInvalid, func(t *testing.T, _ lab.Paths) (string, string) {
			dir := copyGoldenBundle(t, "b")
			editManifestEntry(t, dir, 2, "size", 860)
			return dir, dir
		}},
		{"bytes altered since compiled", findings.RuleBundleIDMismatch, func(t *testing.T, _ lab.Paths) (string, string) {
			dir := copyGoldenBundle(t, fixtureBundleID)
			writeFile(t, filepath.Join(dir, "configs", "n1.cli"), "altered\n")
			return dir, dir
		}},
		{"a corrupt entry in the store", findings.RuleBundleIDMismatch, func(t *testing.T, paths lab.Paths) (string, string) {
			entry := filepath.Join(paths.Bundles, fixtureBundleID)
			if err := os.MkdirAll(paths.Bundles, 0o755); err != nil {
				t.Fatal(err)
			}
			if err := os.Rename(copyGoldenBundle(t, "entry"), entry); err != nil {
				t.Fatal(err)
			}
			writeFile(t, filepath.Join(entry, "configs", "n3.cli"), "corrupted in the store\n")
			return copyGoldenBundle(t, "b"), entry
		}},
	} {
		t.Run(c.name, func(t *testing.T) {
			paths := useStateRoot(t)
			useService(t, nil)
			dir, object := c.prepare(t, paths)
			storeBefore := entriesOf(t, paths.Bundles)

			err := runTwinProvision(context.Background(), &options{asJSON: true}, &provisionFlags{}, dir)
			code, doc := exitOf(t, err)
			if code != findings.ExitRejected || len(doc.Findings) != 1 {
				t.Fatalf("exit %d, findings %+v; want 1 with one finding", code, doc.Findings)
			}
			if f := doc.Findings[0]; f.Rule != c.rule || f.Step != findings.StepVerify || f.Object != object {
				t.Errorf("finding %+v, want %s at step verify on %s", f, c.rule, object)
			}
			if doc.Operation != findings.OpTwinProvision || doc.Subject.Bundle != dir {
				t.Errorf("document %+v, want twin.provision naming the directory as given", doc)
			}
			if after := entriesOf(t, paths.Bundles); strings.Join(after, ",") != strings.Join(storeBefore, ",") {
				t.Errorf("the store went from %v to %v, want nothing filed", storeBefore, after)
			}
			validateM2Document(t, doc)
		})
	}
}

// The corrupt store entry's message says what the entry hashes to and what it should.
func TestProvisionAlteredBundleNamesTheComputedIdentity(t *testing.T) {
	useStateRoot(t)
	useService(t, nil)
	dir := copyGoldenBundle(t, fixtureBundleID)
	writeFile(t, filepath.Join(dir, "configs", "n2.cli"), "altered\n")
	computed := idOfDir(t, dir)

	_, doc := exitOf(t, runTwinProvision(context.Background(), &options{asJSON: true}, &provisionFlags{}, dir))
	if msg := doc.Findings[0].Message; !strings.Contains(msg, computed) {
		t.Errorf("message %q does not name the identity the bytes hash to, %s", msg, computed)
	}
}

// A directory that is not there was never examined: exit 2, operation.failed.
func TestProvisionMissingDirectoryIsOperationFailed(t *testing.T) {
	useStateRoot(t)
	useService(t, nil)
	err := runTwinProvision(context.Background(), &options{asJSON: true}, &provisionFlags{},
		filepath.Join(t.TempDir(), "absent"))
	code, doc := exitOf(t, err)
	if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleOperationFailed {
		t.Errorf("exit %d, findings %+v; want 2 with %s", code, doc.Findings, findings.RuleOperationFailed)
	}
}

// A valid bundle is filed once, however many times it is provisioned, and the run is given
// the stored copy's absolute path.
func TestProvisionFilesOnceAndSendsTheStoredPath(t *testing.T) {
	paths := useStateRoot(t)
	svc := &fakeService{runID: "run-1", result: readyResult()}
	useService(t, svc)
	useInterrupts(t)
	dir := copyGoldenBundle(t, "b")

	for range 2 {
		code, doc := exitOf(t, runTwinProvision(context.Background(), &options{asJSON: true}, &provisionFlags{}, dir))
		if code != findings.ExitOK || doc.Operation != findings.OpTwinProvision || doc.Twin == nil {
			t.Fatalf("exit %d, document %+v; want 0 from twin.provision with a twin block", code, doc)
		}
		validateM5Document(t, doc) // the twin block names artifacts (M5)
	}

	if got := entriesOf(t, paths.Bundles); len(got) != 1 || got[0] != fixtureBundleID {
		t.Errorf("store holds %v, want the one entry %s", got, fixtureBundleID)
	}
	want := filepath.Join(paths.Bundles, fixtureBundleID)
	if len(svc.started) != 2 {
		t.Fatalf("runs started: %d, want 2", len(svc.started))
	}
	for _, in := range svc.started {
		if in.Source != wire.SourceBundle || in.BundleID != fixtureBundleID || in.BundlePath != want || !filepath.IsAbs(in.BundlePath) {
			t.Errorf("run input %+v, want source bundle, %s at %s", in, fixtureBundleID, want)
		}
		if in.Branch != "" || in.At != "" {
			t.Errorf("run input %+v names intent; a bundle run has none", in)
		}
	}
}

// No service and no worker are exit 2 under their own identifiers, not a wait. The
// bundle is filed by then, as it would be for any start.
func TestProvisionStartRefusals(t *testing.T) {
	for _, c := range startRefusals() {
		t.Run(c.name, func(t *testing.T) {
			useStateRoot(t)
			c.use(t)
			err := runTwinProvision(context.Background(), &options{asJSON: true}, &provisionFlags{}, copyGoldenBundle(t, "b"))
			wantStartRefusal(t, err, c.rule)
		})
	}
}

// There is one bundle to provision: no argument, or two, is exit 2 and nothing is dialled.
func TestProvisionTakesExactlyOneDirectory(t *testing.T) {
	useService(t, nil)
	for _, args := range [][]string{{"twin", "provision"}, {"twin", "provision", "a", "b"}} {
		opts := &options{asJSON: true}
		root := &cobra.Command{Use: "fylgja", SilenceUsage: true, SilenceErrors: true}
		root.AddCommand(newTwinCmd(opts))
		root.SetArgs(args)
		var code int
		out := captureStdout(t, func() {
			cmd, err := root.ExecuteC()
			code = report(opts, cmd, err)
		})
		var doc findings.Document
		if err := json.Unmarshal([]byte(out), &doc); err != nil {
			t.Fatalf("%v: stdout is not one findings document: %v\n%s", args, err, out)
		}
		if code != findings.ExitError || doc.Operation != findings.OpTwinProvision {
			t.Errorf("%v: exit %d, operation %q; want 2 from twin.provision", args, code, doc.Operation)
		}
	}
}

// editManifestEntry sets one field of the nth node's artifact entry in dir's manifest,
// as a generic document, so a test can misdescribe one file without naming the
// compiler's types.
func editManifestEntry(t *testing.T, dir string, node int, field string, value any) {
	t.Helper()
	path := filepath.Join(dir, "manifest.json")
	b, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	var m map[string]any
	if err := json.Unmarshal(b, &m); err != nil {
		t.Fatal(err)
	}
	m["nodes"].([]any)[node].(map[string]any)["artifact"].(map[string]any)[field] = value
	out, err := json.MarshalIndent(m, "", "  ")
	if err != nil {
		t.Fatal(err)
	}
	writeFile(t, path, string(out)+"\n")
}

func idOfDir(t *testing.T, dir string) string {
	t.Helper()
	id, err := bundle.IDOfDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	return id
}

// entriesOf lists a directory's entries by name, or none when it does not exist.
func entriesOf(t *testing.T, dir string) []string {
	t.Helper()
	list, err := os.ReadDir(dir)
	if os.IsNotExist(err) {
		return nil
	}
	if err != nil {
		t.Fatal(err)
	}
	names := make([]string, len(list))
	for i, e := range list {
		names[i] = e.Name()
	}
	return names
}

// A provisioned twin never follows: its run stops any following inside itself, the command
// stops none, and a run that could not stop it is exit 2 (contracts/cli.md, twin provision).
func TestProvisionNotFollowing(t *testing.T) {
	t.Run("ready", func(t *testing.T) {
		useStateRoot(t)
		res := readyResult()
		res.Twin.Source = wire.SourceBundle
		svc := &fakeService{runID: "run-1", result: res}
		useService(t, svc)
		useInterrupts(t)

		var err error
		out := captureStdout(t, func() {
			err = runTwinProvision(context.Background(), &options{}, &provisionFlags{}, copyGoldenBundle(t, "b"))
		})
		if code, doc := exitOf(t, err); code != findings.ExitOK {
			t.Fatalf("exit %d, findings %+v; want 0", code, doc.Findings)
		}
		if len(svc.started) != 1 || svc.started[0].Follow != nil || !svc.started[0].StopFollowing {
			t.Errorf("started %+v, want one run with no follow and stop_following", svc.started)
		}
		if slices.Contains(svc.calls, "StopFollowing") {
			t.Errorf("calls %v: the command stopped following itself", svc.calls)
		}
		if want := "twin directory /abs/local/twin\nnot following (provisioned from a bundle)\n"; !strings.HasSuffix(out, want) {
			t.Errorf("stdout:\n%s\nwant it to end:\n%s", out, want)
		}
	})

	t.Run("follow.stop.failed", func(t *testing.T) {
		useStateRoot(t)
		svc := &fakeService{runID: "run-1", result: provision.ProvisionResult{
			Outcome: provision.OutcomeError, Step: findings.StepFollow, BundleID: fixtureBundleID,
			Findings: findings.List{{Severity: findings.Rejection, Rule: findings.RuleFollowStopFailed, Object: provision.FollowScheduleID,
				Step: findings.StepFollow, Message: provision.FollowStopFailedMessage(errors.New("permission denied"), "staged")}},
			Cleanup: provision.CleanupResult{Teardown: provision.CleanupSkipped, Unstage: provision.CleanupSkipped},
		}}
		useService(t, svc)
		useInterrupts(t)

		code, doc := exitOf(t, runTwinProvision(context.Background(), &options{asJSON: true}, &provisionFlags{}, copyGoldenBundle(t, "b")))
		if code != findings.ExitError || !carriesRule(doc.Findings, findings.RuleFollowStopFailed) {
			t.Errorf("exit %d, findings %+v; want 2 with follow.stop.failed", code, doc.Findings)
		}
		if slices.Contains(svc.calls, "StopFollowing") {
			t.Errorf("calls %v: the command stopped following itself", svc.calls)
		}
		validateM4Document(t, doc)
	})
}

// uploadsIn lists the scratch copies of uploaded bundles under the store's root: every
// request's is removed on every exit.
func uploadsIn(t *testing.T, bundles string) []string {
	t.Helper()
	var left []string
	for _, name := range entriesOf(t, bundles) {
		if strings.HasPrefix(name, ".fylgja-upload-") {
			left = append(left, name)
		}
	}
	return left
}

// wantNoScratchNamed fails when the document names the server's scratch copy anywhere: every
// refusal names the directory the operator gave.
func wantNoScratchNamed(t *testing.T, doc *findings.Document, paths lab.Paths) {
	t.Helper()
	b, err := json.Marshal(doc)
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(b), ".fylgja-upload-") {
		t.Errorf("the document names the server's scratch copy:\n%s", b)
	}
	if doc.Subject == nil || doc.Subject.Bundle == "" || strings.HasPrefix(doc.Subject.Bundle, paths.Bundles) {
		t.Errorf("subject %+v, want the directory as given", doc.Subject)
	}
}

// The bundle a client sends is written into a scratch copy under the store, verified and
// filed from there under the id its bytes hash to, and the run deploys the filed copy. The
// scratch copy is gone after a success and after every refusal, and no refusal names it.
func TestProvisionFilesTheUploadAndRemovesItsScratchCopy(t *testing.T) {
	t.Run("a success", func(t *testing.T) {
		paths := useStateRoot(t)
		svc := &fakeService{runID: "run-1", result: readyResult()}
		useService(t, svc)
		useInterrupts(t)
		// A bundle of its own, so its id is not one the store could hold already.
		dir := copyGoldenBundle(t, "b")
		writeFile(t, filepath.Join(dir, "notes.txt"), "a file of the operator's beside the bundle\n")
		id := idOfDir(t, dir)
		if id == fixtureBundleID {
			t.Fatal("the bundle hashes to the golden's id, so filing it proves nothing")
		}

		code, doc := exitOf(t, runTwinProvision(context.Background(), &options{asJSON: true}, &provisionFlags{}, dir))
		if code != findings.ExitOK {
			t.Fatalf("exit %d, findings %+v; want 0", code, doc.Findings)
		}
		filed := filepath.Join(paths.Bundles, id)
		sameTree(t, filed, dir)
		if len(svc.started) != 1 || svc.started[0].BundlePath != filed || svc.started[0].BundleID != id {
			t.Errorf("runs started %+v, want one deploying %s", svc.started, filed)
		}
		if left := uploadsIn(t, paths.Bundles); len(left) != 0 {
			t.Errorf("the store's root holds %v after a success", left)
		}
		wantNoScratchNamed(t, doc, paths)
	})

	for _, c := range []struct {
		name string
		// prepare returns the directory the operator gives.
		prepare func(t *testing.T, paths lab.Paths) string
		code    int
		rule    string
		// message is the finding's message, or its beginning when prefix is set.
		message func(dir string) string
		prefix  bool
	}{
		{"a refusal by verify", func(t *testing.T, _ lab.Paths) string {
			dir := copyGoldenBundle(t, "b")
			if err := os.Remove(filepath.Join(dir, "manifest.json")); err != nil {
				t.Fatal(err)
			}
			return dir
		}, findings.ExitRejected, findings.RuleBundleInvalid,
			func(dir string) string { return dir + " is not a bundle: no manifest.json" }, false},
		{"a directory claiming an id its bytes do not hash to", func(t *testing.T, _ lab.Paths) string {
			dir := copyGoldenBundle(t, fixtureBundleID)
			writeFile(t, filepath.Join(dir, "configs", "n1.cli"), "altered\n")
			return dir
		}, findings.ExitRejected, findings.RuleBundleIDMismatch,
			func(dir string) string {
				return dir + " hashes to " + bundleIDOf(dir) + ", not " + fixtureBundleID
			}, false},
		{"a store that cannot file it", func(t *testing.T, paths lab.Paths) string {
			if os.Geteuid() == 0 {
				t.Skip("root reads a directory whatever its mode")
			}
			// An entry for the bundle's id that cannot be read: the store can neither
			// re-verify it nor file another beside it.
			entry := filepath.Join(paths.Bundles, fixtureBundleID)
			if err := os.MkdirAll(entry, 0o755); err != nil {
				t.Fatal(err)
			}
			if err := os.Chmod(entry, 0); err != nil {
				t.Fatal(err)
			}
			t.Cleanup(func() { _ = os.Chmod(entry, 0o755) })
			return copyGoldenBundle(t, "b")
		}, findings.ExitError, findings.RuleOperationFailed,
			func(dir string) string { return "filing " + dir + " in the bundle store: " }, true},
	} {
		t.Run(c.name, func(t *testing.T) {
			paths := useStateRoot(t)
			useService(t, nil)
			dir := c.prepare(t, paths)
			want := c.message(dir)

			code, doc := exitOf(t, runTwinProvision(context.Background(), &options{asJSON: true}, &provisionFlags{}, dir))
			if code != c.code || len(doc.Findings) != 1 {
				t.Fatalf("exit %d, findings %+v; want %d with one finding", code, doc.Findings, c.code)
			}
			f := doc.Findings[0]
			if f.Rule != c.rule || f.Step != findings.StepVerify || f.Object != dir {
				t.Errorf("finding %+v, want %s at step verify on %s", f, c.rule, dir)
			}
			if c.prefix && !strings.HasPrefix(f.Message, want) || !c.prefix && f.Message != want {
				t.Errorf("message %q, want %q", f.Message, want)
			}
			if left := uploadsIn(t, paths.Bundles); len(left) != 0 {
				t.Errorf("the store's root holds %v after %s", left, c.name)
			}
			wantNoScratchNamed(t, doc, paths)
		})
	}
}

// The upload's scratch copy is gone before the run is started, not when the request ends:
// fylgja serve stopped while it follows the run exits without running the handler's defers,
// which would leave the copy under the store at every restart.
func TestProvisionRemovesItsScratchCopyBeforeTheStart(t *testing.T) {
	paths := useStateRoot(t)
	svc := &uploadsAtStart{fakeService: &fakeService{runID: "run-1", result: readyResult()}, bundles: paths.Bundles}
	useService(t, svc)
	useInterrupts(t)

	code, doc := exitOf(t, runTwinProvision(context.Background(), &options{asJSON: true}, &provisionFlags{},
		copyGoldenBundle(t, "b")))
	if code != findings.ExitOK {
		t.Fatalf("exit %d, findings %+v; want 0", code, doc.Findings)
	}
	svc.mu.Lock()
	defer svc.mu.Unlock()
	if !svc.reached {
		t.Fatal("the run was never started")
	}
	if svc.listErr != nil || len(svc.left) != 0 {
		t.Errorf("the store's root held %v (%v) when the run was started, want no scratch copy", svc.left, svc.listErr)
	}
}

// uploadsAtStart is the fake service, which lists the scratch copies under the store's root
// when the run is started.
type uploadsAtStart struct {
	*fakeService
	bundles string
	reached bool
	left    []string
	listErr error
}

func (u *uploadsAtStart) StartProvision(ctx context.Context, in provision.ProvisionInput) (string, error) {
	entries, err := os.ReadDir(u.bundles)
	u.mu.Lock()
	u.reached, u.listErr = true, err
	for _, e := range entries {
		if strings.HasPrefix(e.Name(), ".fylgja-upload-") {
			u.left = append(u.left, e.Name())
		}
	}
	u.mu.Unlock()
	return u.fakeService.StartProvision(ctx, in)
}

// A store the server cannot write does not stop the verify: the upload's scratch copy is
// made beside the system's temporary files instead, so a bad bundle is refused as such, exit
// 1, as M12 refused it whatever the store, and a good one fails at filing, exit 2, naming the
// directory as given and never the scratch copy. The copy is gone either way.
func TestProvisionOverAReadOnlyStore(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("root writes a directory whatever its mode")
	}
	readOnly := func(t *testing.T) (lab.Paths, string) {
		t.Helper()
		paths := useStateRoot(t)
		if err := os.MkdirAll(paths.Bundles, 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.Chmod(paths.Bundles, 0o555); err != nil {
			t.Fatal(err)
		}
		t.Cleanup(func() { _ = os.Chmod(paths.Bundles, 0o755) })
		tmp := t.TempDir()
		t.Setenv("TMPDIR", tmp)
		useService(t, nil)
		return paths, tmp
	}

	for _, c := range []struct {
		name    string
		prepare func(t *testing.T) string
		code    int
		rule    string
		message func(dir string) string
		prefix  bool
	}{
		{"a bad bundle", func(t *testing.T) string {
			dir := copyGoldenBundle(t, "b")
			if err := os.Remove(filepath.Join(dir, "manifest.json")); err != nil {
				t.Fatal(err)
			}
			return dir
		}, findings.ExitRejected, findings.RuleBundleInvalid,
			func(dir string) string { return dir + " is not a bundle: no manifest.json" }, false},
		{"a bundle claiming an id its bytes do not hash to", func(t *testing.T) string {
			dir := copyGoldenBundle(t, fixtureBundleID)
			writeFile(t, filepath.Join(dir, "configs", "n1.cli"), "altered\n")
			return dir
		}, findings.ExitRejected, findings.RuleBundleIDMismatch,
			func(dir string) string { return dir + " hashes to " + bundleIDOf(dir) + ", not " + fixtureBundleID }, false},
		{"a good bundle", func(t *testing.T) string { return copyGoldenBundle(t, "b") },
			findings.ExitError, findings.RuleOperationFailed,
			func(dir string) string { return "filing " + dir + " in the bundle store: " }, true},
	} {
		t.Run(c.name, func(t *testing.T) {
			paths, tmp := readOnly(t)
			dir := c.prepare(t)
			want := c.message(dir)

			code, doc := exitOf(t, runTwinProvision(context.Background(), &options{asJSON: true}, &provisionFlags{}, dir))
			if code != c.code || len(doc.Findings) != 1 {
				t.Fatalf("exit %d, findings %+v; want %d with one finding", code, doc.Findings, c.code)
			}
			f := doc.Findings[0]
			if f.Rule != c.rule || f.Step != findings.StepVerify || f.Object != dir {
				t.Errorf("finding %+v, want %s at step verify on %s", f, c.rule, dir)
			}
			if c.prefix && !strings.HasPrefix(f.Message, want) || !c.prefix && f.Message != want {
				t.Errorf("message %q, want %q", f.Message, want)
			}
			wantNoScratchNamed(t, doc, paths)
			if left := uploadsIn(t, tmp); len(left) != 0 {
				t.Errorf("the temporary directory holds %v after %s", left, c.name)
			}
			if got := entriesOf(t, paths.Bundles); len(got) != 0 {
				t.Errorf("the read-only store holds %v", got)
			}
		})
	}
}

// bundleIDOf is the id dir's bytes hash to, for a message built before the test can fail.
func bundleIDOf(dir string) string {
	id, err := bundle.IDOfDir(dir)
	if err != nil {
		return "(" + err.Error() + ")"
	}
	return id
}

// A bundle directory crosses as its regular files alone, each under its path inside it: a
// sub-directory is not an entry of its own and a symlink is not sent, as the bundle's
// identity hashes regular files alone. So a bundle beside both is filed under its own id,
// holding nothing more.
func TestProvisionSendsTheBundlesRegularFilesAlone(t *testing.T) {
	dirWithExtras := func(t *testing.T) string {
		t.Helper()
		dir := copyGoldenBundle(t, "b")
		for _, sub := range []string{"empty", filepath.Join("configs", "nested")} {
			if err := os.MkdirAll(filepath.Join(dir, sub), 0o755); err != nil {
				t.Fatal(err)
			}
		}
		outside := filepath.Join(t.TempDir(), "outside.yml")
		writeFile(t, outside, "a file outside the bundle\n")
		for link, target := range map[string]string{
			"link.yml":                           outside,
			filepath.Join("configs", "n1-again"): filepath.Join(dir, "configs", "n1.cli"),
		} {
			if err := os.Symlink(target, filepath.Join(dir, link)); err != nil {
				t.Fatal(err)
			}
		}
		return dir
	}
	golden := treeOf(t, repoPath("testdata", "golden", "three-node"))
	var want []string
	for name, e := range golden {
		if !e.dir {
			want = append(want, name)
		}
	}
	slices.Sort(want)

	t.Run("what is sent", func(t *testing.T) {
		fake := newAPIFake(t, func(w *fakeAnswer, op string, _ api.Request) { w.document(okDocument(op), "") })
		printedBy(t, func() {
			_ = runTwinProvision(context.Background(), &options{asJSON: true}, &provisionFlags{}, dirWithExtras(t))
		})
		seen := fake.seen()
		if len(seen) != 1 {
			t.Fatalf("%d requests, want 1", len(seen))
		}
		var sent []string
		for _, f := range seen[0].req.Files {
			sent = append(sent, f.Path)
			if g, ok := golden[f.Path]; !ok || !bytes.Equal(g.data, f.Data) {
				t.Errorf("%s was sent with bytes that are not the golden's", f.Path)
			}
		}
		if !slices.Equal(sent, want) {
			t.Errorf("sent %v, want the golden's files %v", sent, want)
		}
	})

	t.Run("what is filed", func(t *testing.T) {
		paths := useStateRoot(t)
		svc := &fakeService{runID: "run-1", result: readyResult()}
		useService(t, svc)
		useInterrupts(t)
		code, doc := exitOf(t, runTwinProvision(context.Background(), &options{asJSON: true}, &provisionFlags{}, dirWithExtras(t)))
		if code != findings.ExitOK {
			t.Fatalf("exit %d, findings %+v; want 0", code, doc.Findings)
		}
		if len(svc.started) != 1 || svc.started[0].BundleID != fixtureBundleID {
			t.Errorf("runs started %+v, want one of the golden's id", svc.started)
		}
		if got := entriesOf(t, paths.Bundles); !slices.Equal(got, []string{fixtureBundleID}) {
			t.Errorf("the store holds %v, want the golden's id alone", got)
		}
		sameTree(t, filepath.Join(paths.Bundles, fixtureBundleID), repoPath("testdata", "golden", "three-node"))
	})
}

// A path in the bundle directory that is not a regular file is not sent, so the server
// answers as for a bundle without it: a topology file that is an empty directory or a
// symlink is "no topology.clab.yml", where M12 said "topology.clab.yml is not a file" or
// read through the link. A directory holding a file still arrives as one,
// since its file is sent, and keeps M12's words.
func TestProvisionTopologyThatIsNotAFile(t *testing.T) {
	for _, c := range []struct {
		name    string
		replace func(t *testing.T, topology string)
		reason  string
	}{
		{"an empty directory", func(t *testing.T, topology string) {
			if err := os.Mkdir(topology, 0o755); err != nil {
				t.Fatal(err)
			}
		}, "no topology.clab.yml"},
		{"a symlink to a topology file", func(t *testing.T, topology string) {
			target, err := filepath.Abs(repoPath("testdata", "golden", "three-node", "topology.clab.yml"))
			if err != nil {
				t.Fatal(err)
			}
			if err := os.Symlink(target, topology); err != nil {
				t.Fatal(err)
			}
		}, "no topology.clab.yml"},
		{"a directory holding a file", func(t *testing.T, topology string) {
			if err := os.Mkdir(topology, 0o755); err != nil {
				t.Fatal(err)
			}
			writeFile(t, filepath.Join(topology, "inside.yml"), "name: fylgja\n")
		}, "topology.clab.yml is not a file"},
	} {
		t.Run(c.name, func(t *testing.T) {
			paths := useStateRoot(t)
			useService(t, nil)
			dir := copyGoldenBundle(t, "b")
			topology := filepath.Join(dir, "topology.clab.yml")
			if err := os.Remove(topology); err != nil {
				t.Fatal(err)
			}
			c.replace(t, topology)

			code, doc := exitOf(t, runTwinProvision(context.Background(), &options{asJSON: true}, &provisionFlags{}, dir))
			want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleBundleInvalid, Object: dir,
				Step: findings.StepVerify, Message: dir + " is not a bundle: " + c.reason}
			if code != findings.ExitRejected || len(doc.Findings) != 1 || doc.Findings[0] != want {
				t.Errorf("exit %d, findings %+v; want 1 with %+v alone", code, doc.Findings, want)
			}
			if got := entriesOf(t, paths.Bundles); len(got) != 0 {
				t.Errorf("the store's root holds %v, want nothing filed", got)
			}
		})
	}
}

// A file in the bundle directory that cannot be read is the client's own failure, at step
// verify, naming the directory, worded "reading <file>: …" whichever file it is, and nothing
// is sent.
func TestProvisionUnreadableFileInTheBundle(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("root reads a file whatever its mode")
	}
	// M12 worded each differently: "reading manifest.json: …", a bare "open …" for the topology
	// and a bootstrap file, and "reading <artifact file>: …".
	for _, name := range []string{"manifest.json", "topology.clab.yml", "configs/n1.cli", "configs/n1.device-config"} {
		t.Run(name, func(t *testing.T) {
			useStateRoot(t)
			useService(t, nil)
			dir := copyGoldenBundle(t, "b")
			path := filepath.Join(dir, filepath.FromSlash(name))
			if err := os.Chmod(path, 0); err != nil {
				t.Fatal(err)
			}
			before := len(requestOutcomes(findings.OpTwinProvision))

			code, doc := exitOf(t, runTwinProvision(context.Background(), &options{asJSON: true}, &provisionFlags{}, dir))
			want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleOperationFailed, Object: dir,
				Step: findings.StepVerify, Message: "reading " + name + ": open " + path + ": permission denied"}
			if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0] != want {
				t.Errorf("exit %d, findings %+v; want 2 with %+v alone", code, doc.Findings, want)
			}
			if doc.Subject == nil || doc.Subject.Bundle != dir {
				t.Errorf("subject %+v, want the directory as given", doc.Subject)
			}
			if got := requestOutcomes(findings.OpTwinProvision); len(got) != before {
				t.Errorf("the server served %v, want no request", got[before:])
			}
		})
	}
}

// A directory inside the bundle that cannot be listed is not sent, so the server refuses the
// bundle for what it lacks, as M12's verify did, exit 1: M12 read a file it could not reach
// as one not in the bundle (M12's binary gave these words on the same directory).
func TestProvisionUnlistableDirectoryInTheBundle(t *testing.T) {
	if os.Geteuid() == 0 {
		t.Skip("root lists a directory whatever its mode")
	}
	paths := useStateRoot(t)
	useService(t, nil)
	dir := copyGoldenBundle(t, "b")
	configs := filepath.Join(dir, "configs")
	if err := os.Chmod(configs, 0); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = os.Chmod(configs, 0o755) })

	code, doc := exitOf(t, runTwinProvision(context.Background(), &options{asJSON: true}, &provisionFlags{}, dir))
	want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleBundleInvalid, Object: dir,
		Step: findings.StepVerify,
		Message: dir + " is not a bundle: manifest.json names artifact file configs/n1.device-config for node n1, " +
			"which is not in the bundle"}
	if code != findings.ExitRejected || len(doc.Findings) != 1 || doc.Findings[0] != want {
		t.Errorf("exit %d, findings %+v; want 1 with %+v alone", code, doc.Findings, want)
	}
	if got := entriesOf(t, paths.Bundles); len(got) != 0 {
		t.Errorf("the store holds %v, want nothing filed", got)
	}
}

// A symlink given as the bundle directory is followed: the client sends the directory it
// names, whole, and the server files it under its own id and deploys it, naming the link as
// given. A link whose name is the bundle's id still claims that id. M12
// hashed nothing through the link, and filed an empty bundle.
func TestProvisionFollowsASymlinkedBundleDirectory(t *testing.T) {
	for _, name := range []string{"link", fixtureBundleID} {
		t.Run(name, func(t *testing.T) {
			paths := useStateRoot(t)
			svc := &fakeService{runID: "run-1", result: readyResult()}
			useService(t, svc)
			useInterrupts(t)
			target := copyGoldenBundle(t, "b")
			link := filepath.Join(t.TempDir(), name)
			if err := os.Symlink(target, link); err != nil {
				t.Fatal(err)
			}

			code, doc := exitOf(t, runTwinProvision(context.Background(), &options{asJSON: true}, &provisionFlags{}, link))
			if code != findings.ExitOK {
				t.Fatalf("exit %d, findings %+v; want 0", code, doc.Findings)
			}
			if doc.Subject == nil || doc.Subject.Bundle != link {
				t.Errorf("subject %+v, want the link as given", doc.Subject)
			}
			filed := filepath.Join(paths.Bundles, fixtureBundleID)
			sameTree(t, filed, target)
			if len(svc.started) != 1 || svc.started[0].BundleID != fixtureBundleID || svc.started[0].BundlePath != filed {
				t.Errorf("runs started %+v, want one deploying %s", svc.started, filed)
			}
		})
	}
}

// paddedBundle is a copy of the golden bundle with one more file, padding.bin, sized so the
// request twin provision sends for it under --json is over the server's bound by less than
// one base64 group, or under it by less than one, as over says. The size is found from the
// request with the file empty, since base64 takes every 3 bytes to 4.
func paddedBundle(t *testing.T, over bool) string {
	t.Helper()
	dir := copyGoldenBundle(t, "b")
	padding := filepath.Join(dir, "padding.bin")
	writeFile(t, padding, "")
	files, err := readBundle(dir)
	if err != nil {
		t.Fatal(err)
	}
	arg, err := json.Marshal(dir)
	if err != nil {
		t.Fatal(err)
	}
	body, err := api.EncodeRequest(api.Request{Render: api.RenderJSON, Args: map[string]json.RawMessage{"bundle": arg}, Files: files})
	if err != nil {
		t.Fatal(err)
	}
	groups := (api.MaxRequestBytes - 1 - int64(len(body))) / 4
	if over {
		groups = (api.MaxRequestBytes-int64(len(body)))/4 + 1
	}
	if err := os.WriteFile(padding, make([]byte, groups*3), 0o644); err != nil {
		t.Fatal(err)
	}
	if size := int64(len(body)) + groups*4; over != (size > api.MaxRequestBytes) || size < api.MaxRequestBytes-4 || size > api.MaxRequestBytes+4 {
		t.Fatalf("the request is %d bytes, not just %s the bound of %d", size, map[bool]string{true: "over", false: "under"}[over], api.MaxRequestBytes)
	}
	return dir
}

// A bundle whose request is over the server's bound is refused by the server before
// anything is read or filed, which the client reports under api.transfer.too_large in the
// server's words; one just under it is filed. One mode each: both modes' wording is
// TestTheClientsOwnFailures'.
func TestProvisionTransferBound(t *testing.T) {
	t.Run("just over", func(t *testing.T) {
		paths := useStateRoot(t)
		useService(t, nil)
		dir := paddedBundle(t, true)
		before := len(requestOutcomes(findings.OpTwinProvision))

		code, doc := exitOf(t, runTwinProvision(context.Background(), &options{asJSON: true}, &provisionFlags{}, dir))
		want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleAPITransferTooLarge, Object: findings.OpTwinProvision,
			Message: "the request is larger than this server's transfer bound of 33554432 bytes (32 MiB); nothing was read or filed"}
		if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0] != want {
			t.Errorf("exit %d, findings %+v; want 2 with %+v alone", code, doc.Findings, want)
		}
		if got := servedAfter(t, findings.OpTwinProvision, before); got != "too_large" {
			t.Errorf("the server logged %s, want too_large", got)
		}
		if got := entriesOf(t, paths.Bundles); len(got) != 0 {
			t.Errorf("the store's root holds %v, want nothing filed and no scratch copy", got)
		}
	})

	t.Run("just under", func(t *testing.T) {
		paths := useStateRoot(t)
		svc := &fakeService{runID: "run-1", result: readyResult()}
		useService(t, svc)
		useInterrupts(t)
		dir := paddedBundle(t, false)
		before := len(requestOutcomes(findings.OpTwinProvision))

		code, doc := exitOf(t, runTwinProvision(context.Background(), &options{asJSON: true}, &provisionFlags{}, dir))
		if code != findings.ExitOK {
			t.Fatalf("exit %d, findings %+v; want 0", code, doc.Findings)
		}
		if got := servedAfter(t, findings.OpTwinProvision, before); got != string(findings.StatusOK) {
			t.Errorf("the server logged %s, want ok", got)
		}
		// The bundle is filed under one id, the run deploys it, and it holds the bytes sent.
		// The id is the store's to compute: the test does not hash 24 MiB once more.
		filed := entriesOf(t, paths.Bundles)
		if len(filed) != 1 || !bundle.IsID(filed[0]) || filed[0] == fixtureBundleID {
			t.Fatalf("the store's root holds %v, want the padded bundle's id alone", filed)
		}
		sameTree(t, filepath.Join(paths.Bundles, filed[0]), dir)
		if len(svc.started) != 1 || svc.started[0].BundleID != filed[0] {
			t.Errorf("runs started %+v, want one of %s", svc.started, filed[0])
		}
	})
}
