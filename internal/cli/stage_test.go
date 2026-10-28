package cli

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	snap "github.com/happypathnetworking/fylgja/internal/snapshot"
)

// The stage commands' files through the API. The server reads, compiles and validates; the
// client
// writes what an answer's files frame carries, whole or not at all, and reads what it sends.
// The packages a command is checked against are the server's, but the package psp validate
// is sent is checked on its own.

// filesFramesSince is every files frame the harness's server wrote after m, decoded.
func filesFramesSince(t *testing.T, m servedMark) [][]api.File {
	t.Helper()
	wire, _ := m.since(t)
	var frames [][]api.File
	for _, line := range strings.Split(wire, "\n") {
		if !strings.HasPrefix(line, "{") {
			continue
		}
		var f api.Frame
		if err := json.Unmarshal([]byte(line), &f); err != nil {
			continue
		}
		if f.Kind() == api.KindFiles {
			frames = append(frames, f.Files)
		}
	}
	return frames
}

func readFixture(opts *options, out string) error {
	return runRead(context.Background(), opts, &readFlags{branch: "fylgja-fixture", out: out})
}

// intent read --out writes exactly the bytes of the snapshot the server sent (018: the CTM
// before it), and nothing beside them.
func TestIntentReadWritesTheSnapshotTheServerSent(t *testing.T) {
	useStateRoot(t)
	newFakeInfrahub(t).start()
	dir := t.TempDir()
	out := filepath.Join(dir, "snapshot.json")
	m := markServed()

	run := oneMode(t, false, func(opts *options) error { return readFixture(opts, out) })
	if run.code != findings.ExitOK {
		t.Fatalf("exit %d\nstderr: %s", run.code, run.stderr)
	}
	frames := filesFramesSince(t, m)
	if len(frames) != 1 || len(frames[0]) != 1 || frames[0][0].Path != "snapshot.json" {
		t.Fatalf("the server sent files frames %+v, want one carrying snapshot.json alone", frames)
	}
	got, err := os.ReadFile(out)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, frames[0][0].Data) {
		t.Errorf("--out holds %d bytes that are not the %d the server sent", len(got), len(frames[0][0].Data))
	}
	if _, err := snap.Unmarshal(got); err != nil {
		t.Errorf("--out is not a snapshot: %v", err)
	}
	if entries := entriesOf(t, dir); !slices.Equal(entries, []string{"snapshot.json"}) {
		t.Errorf("--out's directory holds %v, want snapshot.json alone", entries)
	}
	if !strings.Contains(run.stdout, out) {
		t.Errorf("stdout %q does not carry the summary line naming %s", run.stdout, out)
	}
}

// An answer cut inside its files frame writes nothing: a snapshot already at --out is left
// as it was, and no temporary file is left beside it.
func TestIntentReadCutInsideTheSnapshotWritesNothing(t *testing.T) {
	line, err := json.Marshal(api.Frame{Files: []api.File{{Path: "snapshot.json", Data: bytes.Repeat([]byte("{}\n"), 4096)}}})
	if err != nil {
		t.Fatal(err)
	}
	stubAPI(t, func(w http.ResponseWriter, r *http.Request) {
		answerHeaders(w)
		_, _ = w.Write(line[:len(line)/2])
		w.(http.Flusher).Flush()
		dropConnection(t, w)
	})
	dir := t.TempDir()
	out := filepath.Join(dir, "snapshot.json")
	earlier := []byte("the snapshot an earlier read wrote\n")
	writeFile(t, out, string(earlier))

	text, asJSON := runBothModes(t, func(opts *options) error { return readFixture(opts, out) })
	for _, run := range []clientRun{text, asJSON} {
		if run.code != findings.ExitError || !strings.Contains(run.stdout+run.stderr, findings.RuleAPIUnreachable) {
			t.Errorf("exit %d\nstdout: %s\nstderr: %s\nwant 2 with %s", run.code, run.stdout, run.stderr, findings.RuleAPIUnreachable)
		}
	}
	if got, _ := os.ReadFile(out); !bytes.Equal(got, earlier) {
		t.Errorf("--out now holds %q, want the earlier snapshot unchanged", got)
	}
	if entries := entriesOf(t, dir); !slices.Equal(entries, []string{"snapshot.json"}) {
		t.Errorf("--out's directory holds %v, want snapshot.json alone", entries)
	}
}

// A read the server refuses sends no snapshot and files none, and the client writes
// nothing.
func TestIntentReadRefusedWritesNothing(t *testing.T) {
	paths := useStateRoot(t)
	f := newFakeInfrahub(t)
	f.branches = map[string]*ctm.CTM{"refused": &f.fixture}
	f.untagged = map[string]bool{"refused": true}
	f.start()
	out := filepath.Join(t.TempDir(), "snapshot.json")
	m := markServed()

	run := oneMode(t, true, func(opts *options) error {
		return runRead(context.Background(), opts, &readFlags{branch: "refused", out: out})
	})
	if run.code != findings.ExitRejected || !carriesRule(run.doc.Findings, findings.RuleScopeEmpty) {
		t.Fatalf("exit %d, findings %+v; want 1 with %s", run.code, run.doc.Findings, findings.RuleScopeEmpty)
	}
	if frames := filesFramesSince(t, m); len(frames) != 0 {
		t.Errorf("the server sent %d files frames for a refused read", len(frames))
	}
	if _, err := os.Stat(out); !os.IsNotExist(err) {
		t.Errorf("a refused read left %s: %v", out, err)
	}
	if got := filedSnapshots(t, paths); len(got) != 0 {
		t.Errorf("a refused read filed %v", got)
	}
}

// A snapshot the client cannot write ends the read with M12's operation.failed, "writing
// snapshot: …" (018: "writing CTM: …" before it), under the subject the server's document
// names, and the summary line after the files frame is not printed.
func TestIntentReadUnwritableOutIsTheClientsOwnFailure(t *testing.T) {
	useStateRoot(t)
	newFakeInfrahub(t).start()
	out := filepath.Join(t.TempDir(), "absent", "snapshot.json")

	text, asJSON := runBothModes(t, func(opts *options) error { return readFixture(opts, out) })
	if text.code != findings.ExitError || text.stdout != "" || !strings.Contains(text.stderr, "writing snapshot: ") {
		t.Errorf("text: exit %d, stdout %q, stderr %q; want 2, nothing on stdout and writing snapshot on stderr", text.code, text.stdout, text.stderr)
	}
	doc := asJSON.doc
	if asJSON.code != findings.ExitError || doc.Operation != findings.OpIntentRead || len(doc.Findings) != 1 {
		t.Fatalf("--json: exit %d, document %+v; want 2 from intent.read with one finding", asJSON.code, doc)
	}
	prefix := "writing snapshot: open " + filepath.Join(filepath.Dir(out), ".fylgja-snapshot-")
	if f := doc.Findings[0]; f.Rule != findings.RuleOperationFailed || f.Object != findings.OpIntentRead ||
		!strings.HasPrefix(f.Message, prefix) || !strings.HasSuffix(f.Message, ": no such file or directory") {
		t.Errorf("finding %+v, want operation.failed on intent.read saying %s…: no such file or directory", f, prefix)
	}
	if doc.Subject == nil || doc.Subject.Branch != "fylgja-fixture" || doc.Subject.Out != out {
		t.Errorf("subject %+v, want the branch and --out", doc.Subject)
	}
	if _, err := os.Stat(filepath.Dir(out)); !os.IsNotExist(err) {
		t.Errorf("the client made --out's directory: %v", err)
	}
}

// twin compile into a directory that holds something is M12's "output directory <dir> is not
// empty", under the compile's subject, with nothing else printed and the directory left as
// it was.
func TestCompileIntoANonEmptyDirectory(t *testing.T) {
	snapshotPath := wrappedFixture("three-node")
	c, err := ctm.Load(repoPath("testdata", "ctm", "three-node.json"))
	if err != nil {
		t.Fatal(err)
	}
	out := t.TempDir()
	writeFile(t, filepath.Join(out, "keep.txt"), "the operator's\n")

	text, asJSON := runBothModes(t, func(opts *options) error {
		return runCompile(opts, &compileFlags{snapshotPath: snapshotPath, out: out})
	})
	message := "output directory " + out + " is not empty"
	if text.code != findings.ExitError || text.stdout != "" || !strings.Contains(text.stderr, message) ||
		strings.Contains(text.stderr, "bundle_id") || strings.Contains(text.stderr, "wrote bundle") {
		t.Errorf("text: exit %d, stdout %q, stderr %q; want 2, nothing on stdout and %q alone on stderr", text.code, text.stdout, text.stderr, message)
	}
	want := findings.ErrorDocument(findings.OpCompile,
		&findings.Subject{Snapshot: snapshotPath, Out: out, Branch: c.Envelope.Branch, At: c.Envelope.At}, message)
	if asJSON.code != findings.ExitError || !sameJSON(t, asJSON.doc, want) {
		t.Errorf("--json: exit %d, document %+v\nwant 2 and %+v", asJSON.code, asJSON.doc, want)
	}
	if entries := entriesOf(t, out); !slices.Equal(entries, []string{"keep.txt"}) {
		t.Errorf("--out holds %v, want keep.txt alone", entries)
	}
}

// sameJSON reports whether two documents marshal to the same bytes.
func sameJSON(t *testing.T, a, b *findings.Document) bool {
	t.Helper()
	x, err := json.Marshal(a)
	if err != nil {
		t.Fatal(err)
	}
	y, err := json.Marshal(b)
	if err != nil {
		t.Fatal(err)
	}
	return bytes.Equal(x, y)
}

// Several packages are validated as a set, and every finding names the path the operator
// gave, relative or absolute, as M12's did.
func TestPSPValidateNamesEachPathAsGiven(t *testing.T) {
	shipped := repoPath("psp", "nokia_srlinux.yaml")
	copied := filepath.Join(t.TempDir(), "srlinux-again.yaml")
	b, err := os.ReadFile(shipped)
	if err != nil {
		t.Fatal(err)
	}
	writeFile(t, copied, string(b))
	defect := defectPath("no-encoding.yaml")

	code, doc := runPSPDoc(t, shipped, copied, defect)
	if code != findings.ExitRejected {
		t.Fatalf("exit %d, want 1: %+v", code, doc.Findings)
	}
	named := map[string][]string{}
	var duplicate []string
	for _, f := range doc.Findings {
		if f.Location == nil {
			t.Errorf("%s names no file: %s", f.Rule, f.Message)
			continue
		}
		named[f.Location.File] = append(named[f.Location.File], f.Rule)
		if f.Rule == findings.RulePSPIdentityDuplicate {
			duplicate = append(duplicate, f.Location.File+": "+f.Message)
		}
	}
	for file := range named {
		if file != shipped && file != copied && file != defect {
			t.Errorf("a finding names %s, which is none of the paths given", file)
		}
	}
	// The defect fixture is the shipped package with one line changed, so it and the copy
	// are each a duplicate of the first, named as given.
	declared := `: platform "nokia_srlinux" is already declared by ` + shipped
	want := []string{copied + declared, defect + declared}
	if !slices.Equal(duplicate, want) {
		t.Errorf("%s findings %q, want %q: the set was not validated together", findings.RulePSPIdentityDuplicate, duplicate, want)
	}
	if len(named[defect]) == 0 {
		t.Errorf("the defect fixture %s drew no finding", defect)
	}
}

// Among several files, one the client cannot read is reported before another's second YAML
// document, since the client reads every file before the server sees any: M12 read and
// checked each in turn, and reported the second document first.
// Nothing is sent.
func TestPSPValidateReportsAnUnreadableFileFirst(t *testing.T) {
	shipped, err := os.ReadFile(repoPath("psp", "nokia_srlinux.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	multi := filepath.Join(t.TempDir(), "two-documents.yaml")
	writeFile(t, multi, string(shipped)+"\n---\n"+string(shipped))
	missing := filepath.Join(t.TempDir(), "absent.yaml")
	awaitIdle(t)
	before := len(requestOutcomes(findings.OpPSPValidate))

	code, doc := runPSPDoc(t, multi, missing)
	want := "open " + missing + ": no such file or directory"
	if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleOperationFailed ||
		doc.Findings[0].Message != want {
		t.Errorf("exit %d, findings %+v; want 2 with operation.failed saying %q", code, doc.Findings, want)
	}
	awaitIdle(t)
	if got := requestOutcomes(findings.OpPSPValidate); len(got) != before {
		t.Errorf("the server served %v, want no request", got[before:])
	}

	// The second document alone is still the server's refusal, in M12's words.
	code, doc = runPSPDoc(t, multi)
	want = multi + ": a support package file must hold exactly one YAML document"
	if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0].Message != want {
		t.Errorf("exit %d, findings %+v; want 2 saying %q", code, doc.Findings, want)
	}
}

// The package psp validate is sent is checked on its own: the server's override directory,
// whatever it holds, is neither added to the set nor loaded. The same directory refuses a
// compile, so the server was given it.
func TestPSPValidateChecksThePackageSentAlone(t *testing.T) {
	shipped := repoPath("psp", "nokia_srlinux.yaml")
	b, err := os.ReadFile(shipped)
	if err != nil {
		t.Fatal(err)
	}
	override := t.TempDir()
	writeFile(t, filepath.Join(override, "nokia_srlinux.yaml"), string(b))
	writeFile(t, filepath.Join(override, "broken.yaml"), "platform: [not a package\n")
	usePSPDir(t, override)

	run := oneMode(t, false, func(opts *options) error { return runPSPValidate(opts, []string{shipped}) })
	if run.code != findings.ExitOK || run.stdout != shipped+": valid\n" {
		t.Errorf("exit %d, stdout %q, stderr %q; want 0 and %s valid", run.code, run.stdout, run.stderr, shipped)
	}

	code, doc := runCompileTo(t, wrappedFixture("three-node"), filepath.Join(t.TempDir(), "bundle"))
	if code != findings.ExitRejected || len(doc.Findings) == 0 || !strings.HasPrefix(doc.Findings[0].Rule, "psp.") {
		t.Errorf("a compile against the same server: exit %d, findings %+v; want 1 with the override's psp findings", code, doc.Findings)
	}
}

// psp validate and twin compile are checked by the API's server and need neither Infrahub
// nor the workflow service; their help no longer says they read no network or are entirely
// local, which the API made false.
func TestStageHelpTextsNameTheServer(t *testing.T) {
	opts := &options{}
	for _, cmd := range []*cobra.Command{newTwinCompileCmd(opts), newPSPValidateCmd(opts)} {
		long := strings.Join(strings.Fields(cmd.Long), " ")
		for _, gone := range []string{"no network", "Reads no network", "Entirely local", "entirely local"} {
			if strings.Contains(long, gone) {
				t.Errorf("%s's help still says %q:\n%s", cmd.Name(), gone, cmd.Long)
			}
		}
		for _, said := range []string{"The API's server", "neither Infrahub nor the workflow service"} {
			if !strings.Contains(long, said) {
				t.Errorf("%s's help does not say %q:\n%s", cmd.Name(), said, cmd.Long)
			}
		}
	}
}

// stage plan, twin step and twin rehearse say that the API's server takes each stage's
// snapshot and files it beside its bundle, as twin create's help does since T065, and stage
// plan no longer files a CTM beside each bundle (018: FR-008, FR-011, FR-012, FR-014); twin
// step's names --snapshot, a snapshot of any branch, compiled with no read (019). The
// whole help is read, flags included, its whitespace folded so no line break is pinned.
func TestStageHelpsNameTheServersTake(t *testing.T) {
	for _, c := range []struct {
		args       []string
		said, gone []string
	}{
		{[]string{"stage", "plan", "--help"}, []string{
			"The API's server resolves each stage, reads it, takes the snapshot of what it read and files it in its " +
				"snapshot store, compiles it and files the bundle in its bundle store,",
			"prints the stage's snapshot_id above its bundle_id.",
		}, []string{"its CTM", "reads, compiles and files them"}},
		{[]string{"twin", "step", "--help"}, []string{
			"The API's server resolves the target, reads it, takes the snapshot of what it read, compiles it and " +
				"files the snapshot and the bundle, as stage plan builds a stage;",
			"resolve and read the target, take and file its snapshot, compile and file its bundle, check the host " +
				"and read containerlab's plan; start no run",
			// 019: --snapshot, a snapshot of any branch, which the server compiles with no read.
			"or to a snapshot of any branch, the one --snapshot names.",
			"--snapshot <id|file> names one its store holds by its id, or a snapshot file sent from here, which it files, " +
				"and it compiles that and files the bundle, reading no branch.",
			"--snapshot string the snapshot to step to, <id|file>, a snapshot of any branch:",
			"start no run (with --snapshot, nothing is read)",
		}, []string{"resolves, reads, compiles and files the target", "resolve, read, compile and file the target",
			"Take the stage twin"}},
		{[]string{"twin", "rehearse", "--help"}, []string{
			"The API's server builds every stage first, as stage plan does: it resolves the stage, reads it, takes " +
				"the snapshot of what it read, compiles it and files the snapshot and the bundle,",
		}, []string{"resolves, reads, compiles and files every stage"}},
	} {
		t.Run(strings.Join(c.args[:2], " "), func(t *testing.T) {
			root := &cobra.Command{Use: "fylgja"}
			opts := &options{}
			root.AddCommand(newTwinCmd(opts), newStageCmd(opts))
			root.SetArgs(c.args)
			text := strings.Join(strings.Fields(captureStdout(t, func() {
				if err := root.Execute(); err != nil {
					t.Error(err)
				}
			})), " ")
			for _, want := range c.said {
				if !strings.Contains(text, want) {
					t.Errorf("the help does not say %q:\n%s", want, text)
				}
			}
			for _, gone := range c.gone {
				if strings.Contains(text, gone) {
					t.Errorf("the help still says %q:\n%s", gone, text)
				}
			}
		})
	}
}

// stage list, stage plan, twin step and twin show do their work in the API's server,
// and their help no longer says the command needs Infrahub alone, or Infrahub and the bundle
// store, or does its work here, or runs on the lab host.
func TestWorkHelpTextsNameTheServer(t *testing.T) {
	opts := &options{}
	for _, c := range []struct {
		cmd        *cobra.Command
		gone, said []string
	}{
		{newStageListCmd(opts), []string{"Needs Infrahub and nothing else"},
			[]string{"The API's server reads them, and needs Infrahub and nothing else for it."}},
		{newStagePlanCmd(opts), []string{"Needs Infrahub and the bundle store"},
			[]string{"The server needs Infrahub and its two stores for it"}},
		{newTwinStepCmd(opts), []string{"compiled and filed here"},
			[]string{"The API's server resolves the target, reads it,"}},
		{newTwinShowCmd(opts), []string{"Runs on the lab host"},
			[]string{"The API's server reports it from the lab host, needs no worker, and changes nothing."}},
	} {
		long := strings.Join(strings.Fields(c.cmd.Long), " ")
		for _, gone := range c.gone {
			if strings.Contains(long, gone) {
				t.Errorf("%s's help still says %q:\n%s", c.cmd.Name(), gone, c.cmd.Long)
			}
		}
		for _, said := range c.said {
			if !strings.Contains(long, said) {
				t.Errorf("%s's help does not say %q:\n%s", c.cmd.Name(), said, c.cmd.Long)
			}
		}
	}
}
