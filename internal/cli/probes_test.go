package cli

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
)

// probesPath is testdata/probes/<name>, as an operator gives it to --probes.
func probesPath(name string) string {
	return repoPath("testdata", "probes", name)
}

// The five commands that take --probes send it as the argument probes, the path, beside the
// file at that path as the request's one file, its bytes unchanged (FR-005; contracts/api.md,
// "016: probes").
func TestProbesIsSentAsTheOneFile(t *testing.T) {
	path := probesPath("n1-loop.json")
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	out := filepath.Join(t.TempDir(), "x.json")
	for _, args := range [][]string{
		{"intent", "read", "--branch", "b", "--out", out},
		{"intent", "read", "--stage", "change-1/cabled", "--out", out},
		{"twin", "create", "--branch", "b"},
		{"twin", "create", "--stage", "change-1/cabled", "--dry-run"},
		{"twin", "step", "--stage", "change-1/cabled"},
		{"twin", "step"},
		{"stage", "plan", "--branch", "change-1"},
		{"twin", "rehearse", "--branch", "change-1"},
	} {
		t.Run(strings.Join(args, " "), func(t *testing.T) {
			fake := newAPIFake(t, func(w *fakeAnswer, op string, _ api.Request) { w.document(okDocument(op), "") })
			if code, doc, _ := executeClient(t, append(append([]string{}, args...), "--probes", path)...); code != findings.ExitOK {
				t.Fatalf("exit %d, findings %+v", code, doc.Findings)
			}
			seen := fake.seen()
			if len(seen) != 1 || seen[0].op != args[0]+"."+args[1] {
				t.Fatalf("%d requests (%+v), want one of %s.%s", len(seen), seen, args[0], args[1])
			}
			req := seen[0].req
			var sent string
			if err := json.Unmarshal(req.Args["probes"], &sent); err != nil || sent != path {
				t.Errorf("the argument probes is %s; want %q", req.Args["probes"], path)
			}
			if len(req.Files) != 1 || req.Files[0].Path != path || !bytes.Equal(req.Files[0].Data, data) {
				t.Errorf("the request carries %d files; want the declaration alone, under %s", len(req.Files), path)
			}
		})
	}
}

// Beside --snapshot, on twin create and twin step, --probes is sent as the argument with no
// file at all, as --branch beside --snapshot is, so the server's snapshot.flags.conflict
// answers whatever either file holds; neither is read here (FR-006).
func TestProbesBesideASnapshotSendsNoFile(t *testing.T) {
	missing := filepath.Join(t.TempDir(), "none.json")
	for _, args := range [][]string{
		{"twin", "create", "--snapshot", missing, "--probes", missing},
		{"twin", "step", "--snapshot", missing, "--probes", missing},
	} {
		t.Run(args[1], func(t *testing.T) {
			fake := newAPIFake(t, func(w *fakeAnswer, op string, _ api.Request) { w.document(okDocument(op), "") })
			executeClient(t, args...)
			seen := fake.seen()
			if len(seen) != 1 {
				t.Fatalf("%d requests, want 1", len(seen))
			}
			req := seen[0].req
			if _, ok := req.Args["probes"]; !ok || req.Args["snapshot"] == nil || len(req.Files) != 0 {
				t.Errorf("args %s, %d files; want snapshot and probes named, and no file", seen[0].body, len(req.Files))
			}
		})
	}
}

// A --probes file the client cannot read is its own refusal, exit 2, and no request is sent;
// an explicit empty --probes= names no file and is refused the same way.
func TestAnUnreadableProbesFileIsTheClientsRefusal(t *testing.T) {
	missing := filepath.Join(t.TempDir(), "none.json")
	for _, c := range []struct {
		args []string
		says string
	}{
		{[]string{"twin", "create", "--branch", "b", "--probes", missing}, "reading probes: open " + missing},
		{[]string{"intent", "read", "--branch", "b", "--out", "x.json", "--probes", missing}, "reading probes: open " + missing},
		{[]string{"twin", "step", "--probes", missing}, "reading probes: open " + missing},
		{[]string{"stage", "plan", "--branch", "change-1", "--probes="}, "--probes= is empty"},
		{[]string{"twin", "rehearse", "--branch", "change-1", "--probes", missing}, "reading probes: open " + missing},
	} {
		fake := newAPIFake(t, func(w *fakeAnswer, op string, _ api.Request) { w.document(okDocument(op), "") })
		code, doc, _ := executeClient(t, c.args...)
		if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleOperationFailed ||
			!strings.HasPrefix(doc.Findings[0].Message, c.says) {
			t.Errorf("%v: exit %d, findings %+v; want 2, operation.failed beginning %q", c.args, code, doc.Findings, c.says)
		}
		if n := len(fake.seen()); n != 0 {
			t.Errorf("%v: %d requests sent; want none", c.args, n)
		}
	}
}

// twin compile and twin provision have no --probes: the snapshot or the bundle says what it
// carries (FR-006). Each is cobra's unknown flag, exit 2, and no request is sent.
func TestCompileAndProvisionTakeNoProbes(t *testing.T) {
	for _, args := range [][]string{
		{"--json", "twin", "compile", "--snapshot", "s.json", "--out", "b", "--probes", "p.json"},
		{"--json", "twin", "provision", "--probes", "p.json", "b"},
	} {
		awaitIdle(t)
		before := requestsLogged()
		opts := &options{}
		root := &cobra.Command{Use: "fylgja", SilenceUsage: true, SilenceErrors: true}
		root.PersistentFlags().BoolVar(&opts.asJSON, "json", false, "")
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
		if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0].Message != "unknown flag: --probes" {
			t.Errorf("%v: exit %d, findings %+v; want 2, cobra's unknown flag", args, code, doc.Findings)
		}
		awaitIdle(t)
		if got := requestsLogged(); got != before {
			t.Errorf("%v: the server logged %d requests, want none", args, got-before)
		}
	}
}

// Each command's help names the kind as the default source, and says the file replaces it.
func TestProbesHelpNamesTheKind(t *testing.T) {
	opts := &options{}
	for _, c := range []struct {
		cmd  *cobra.Command
		name string
	}{
		{newIntentReadCmd(opts), "intent read"},
		{newTwinCreateCmd(opts), "twin create"},
		{newTwinStepCmd(opts), "twin step"},
		{newStagePlanCmd(opts), "stage plan"},
		{newTwinRehearseCmd(opts), "twin rehearse"},
	} {
		f := c.cmd.Flags().Lookup("probes")
		if f == nil {
			t.Errorf("%s has no --probes", c.name)
			continue
		}
		for _, want := range []string{"FylgjaProbe on the default branch", "in place of"} {
			if !strings.Contains(f.Usage, want) {
				t.Errorf("%s's --probes help %q does not say %q", c.name, f.Usage, want)
			}
		}
	}
	if newStageListCmd(opts).Flags().Lookup("probes") != nil {
		t.Errorf("stage list takes --probes; it reads no intent to take")
	}
}
