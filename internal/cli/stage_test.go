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

// intent read --out writes exactly the bytes of the CTM the server sent, and nothing beside
// them.
func TestIntentReadWritesTheCTMTheServerSent(t *testing.T) {
	newFakeInfrahub(t).start()
	dir := t.TempDir()
	out := filepath.Join(dir, "ctm.json")
	m := markServed()

	run := oneMode(t, false, func(opts *options) error { return readFixture(opts, out) })
	if run.code != findings.ExitOK {
		t.Fatalf("exit %d\nstderr: %s", run.code, run.stderr)
	}
	frames := filesFramesSince(t, m)
	if len(frames) != 1 || len(frames[0]) != 1 || frames[0][0].Path != "ctm.json" {
		t.Fatalf("the server sent files frames %+v, want one carrying ctm.json alone", frames)
	}
	got, err := os.ReadFile(out)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(got, frames[0][0].Data) {
		t.Errorf("--out holds %d bytes that are not the %d the server sent", len(got), len(frames[0][0].Data))
	}
	if _, err := ctm.Unmarshal(got); err != nil {
		t.Errorf("--out is not a CTM: %v", err)
	}
	if entries := entriesOf(t, dir); !slices.Equal(entries, []string{"ctm.json"}) {
		t.Errorf("--out's directory holds %v, want ctm.json alone", entries)
	}
	if !strings.Contains(run.stdout, out) {
		t.Errorf("stdout %q does not carry the summary line naming %s", run.stdout, out)
	}
}

// An answer cut inside its files frame writes nothing: a CTM already at --out is left as it
// was, and no temporary file is left beside it.
func TestIntentReadCutInsideTheCTMWritesNothing(t *testing.T) {
	line, err := json.Marshal(api.Frame{Files: []api.File{{Path: "ctm.json", Data: bytes.Repeat([]byte("{}\n"), 4096)}}})
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
	out := filepath.Join(dir, "ctm.json")
	earlier := []byte("the CTM an earlier read wrote\n")
	writeFile(t, out, string(earlier))

	text, asJSON := runBothModes(t, func(opts *options) error { return readFixture(opts, out) })
	for _, run := range []clientRun{text, asJSON} {
		if run.code != findings.ExitError || !strings.Contains(run.stdout+run.stderr, findings.RuleAPIUnreachable) {
			t.Errorf("exit %d\nstdout: %s\nstderr: %s\nwant 2 with %s", run.code, run.stdout, run.stderr, findings.RuleAPIUnreachable)
		}
	}
	if got, _ := os.ReadFile(out); !bytes.Equal(got, earlier) {
		t.Errorf("--out now holds %q, want the earlier CTM unchanged", got)
	}
	if entries := entriesOf(t, dir); !slices.Equal(entries, []string{"ctm.json"}) {
		t.Errorf("--out's directory holds %v, want ctm.json alone", entries)
	}
}

// A read the server refuses sends no CTM, and the client writes nothing.
func TestIntentReadRefusedWritesNothing(t *testing.T) {
	f := newFakeInfrahub(t)
	f.branches = map[string]*ctm.CTM{"refused": &f.fixture}
	f.contractless = map[string]bool{"refused": true}
	f.start()
	out := filepath.Join(t.TempDir(), "ctm.json")
	m := markServed()

	run := oneMode(t, true, func(opts *options) error {
		return runRead(context.Background(), opts, &readFlags{branch: "refused", out: out})
	})
	if run.code != findings.ExitRejected || !carriesRule(run.doc.Findings, findings.RuleContractNodeMissing) {
		t.Fatalf("exit %d, findings %+v; want 1 with %s", run.code, run.doc.Findings, findings.RuleContractNodeMissing)
	}
	if frames := filesFramesSince(t, m); len(frames) != 0 {
		t.Errorf("the server sent %d files frames for a refused read", len(frames))
	}
	if _, err := os.Stat(out); !os.IsNotExist(err) {
		t.Errorf("a refused read left %s: %v", out, err)
	}
}

// A CTM the client cannot write ends the read with M12's operation.failed, "writing CTM: …",
// under the subject the server's document names, and the summary line after the files frame
// is not printed.
func TestIntentReadUnwritableOutIsTheClientsOwnFailure(t *testing.T) {
	newFakeInfrahub(t).start()
	out := filepath.Join(t.TempDir(), "absent", "ctm.json")

	text, asJSON := runBothModes(t, func(opts *options) error { return readFixture(opts, out) })
	if text.code != findings.ExitError || text.stdout != "" || !strings.Contains(text.stderr, "writing CTM: ") {
		t.Errorf("text: exit %d, stdout %q, stderr %q; want 2, nothing on stdout and writing CTM on stderr", text.code, text.stdout, text.stderr)
	}
	doc := asJSON.doc
	if asJSON.code != findings.ExitError || doc.Operation != findings.OpIntentRead || len(doc.Findings) != 1 {
		t.Fatalf("--json: exit %d, document %+v; want 2 from intent.read with one finding", asJSON.code, doc)
	}
	prefix := "writing CTM: open " + filepath.Join(filepath.Dir(out), ".fylgja-ctm-")
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
	ctmPath := repoPath("testdata", "ctm", "three-node.json")
	c, err := ctm.Load(ctmPath)
	if err != nil {
		t.Fatal(err)
	}
	out := t.TempDir()
	writeFile(t, filepath.Join(out, "keep.txt"), "the operator's\n")

	text, asJSON := runBothModes(t, func(opts *options) error {
		return runCompile(opts, &compileFlags{ctmPath: ctmPath, out: out})
	})
	message := "output directory " + out + " is not empty"
	if text.code != findings.ExitError || text.stdout != "" || !strings.Contains(text.stderr, message) ||
		strings.Contains(text.stderr, "bundle_id") || strings.Contains(text.stderr, "wrote bundle") {
		t.Errorf("text: exit %d, stdout %q, stderr %q; want 2, nothing on stdout and %q alone on stderr", text.code, text.stdout, text.stderr, message)
	}
	want := findings.ErrorDocument(findings.OpCompile,
		&findings.Subject{CTM: ctmPath, Out: out, Branch: c.Envelope.Branch, At: c.Envelope.At}, message)
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
	before := len(requestOutcomes(findings.OpPSPValidate))

	code, doc := runPSPDoc(t, multi, missing)
	want := "open " + missing + ": no such file or directory"
	if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleOperationFailed ||
		doc.Findings[0].Message != want {
		t.Errorf("exit %d, findings %+v; want 2 with operation.failed saying %q", code, doc.Findings, want)
	}
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

	code, doc := runCompileTo(t, repoPath("testdata", "ctm", "three-node.json"), filepath.Join(t.TempDir(), "bundle"))
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

// waypoint list, waypoint plan, twin step and twin show do their work in the API's server,
// and their help no longer says the command needs Infrahub alone, or Infrahub and the bundle
// store, or does its work here, or runs on the lab host.
func TestWorkHelpTextsNameTheServer(t *testing.T) {
	opts := &options{}
	for _, c := range []struct {
		cmd        *cobra.Command
		gone, said []string
	}{
		{newWaypointListCmd(opts), []string{"Needs Infrahub and nothing else"},
			[]string{"The API's server reads them, and needs Infrahub and nothing else for it."}},
		{newWaypointPlanCmd(opts), []string{"Needs Infrahub and the bundle store"},
			[]string{"The API's server reads, compiles and files them in its bundle store, and needs Infrahub and the store for it"}},
		{newTwinStepCmd(opts), []string{"compiled and filed here"},
			[]string{"The API's server resolves, reads, compiles and files the target;"}},
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
