package cli

import (
	"bytes"
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"

	"github.com/spf13/cobra"

	"github.com/happypathnetworking/fylgja/internal/api"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/probe"
	"github.com/happypathnetworking/fylgja/internal/server"
	snap "github.com/happypathnetworking/fylgja/internal/snapshot"
)

// probesPath is testdata/probes/<name>, as an operator gives it to --probes.
func probesPath(name string) string {
	return repoPath("testdata", "probes", name)
}

// useProbeKind serves the kind's read from kind for the rest of the test.
func useProbeKind(t *testing.T, kind *kindProbes) {
	t.Helper()
	saved := probeKind
	probeKind = func() (server.ProbeReader, error) { return kind, nil }
	t.Cleanup(func() { probeKind = saved })
}

// declaredProbes is the list of the declaration at path.
func declaredProbes(t *testing.T, path string) []probe.Probe {
	t.Helper()
	b, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	d, list := probe.Parse(b, path)
	if d == nil {
		t.Fatalf("%s: %+v", path, list)
	}
	return d.Probes
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

// Through the harness's server the conflict is snapshot.flags.conflict at --probes, exit 2,
// at start, before Infrahub or the kind is asked and before the workflow service is dialled.
func TestProbesBesideASnapshotIsTheServersConflict(t *testing.T) {
	useStateRoot(t)
	infra := newFakeInfrahub(t)
	infra.start()
	kind := &kindProbes{}
	useProbeKind(t, kind)
	dials := countDials(t)
	id := strings.Repeat("a", 64)
	for _, args := range [][]string{
		{"twin", "create", "--snapshot", id, "--probes", probesPath("n1-loop.json")},
		{"twin", "create", "--snapshot", id, "--probes", probesPath("n1-loop.json"), "--dry-run"},
		{"twin", "step", "--snapshot", id, "--probes", probesPath("n1-loop.json")},
	} {
		code, doc, raw := executeClient(t, args...)
		want := findings.Finding{Severity: findings.Rejection, Rule: findings.RuleSnapshotFlagsConflict, Step: findings.StepStart,
			Object: "--probes", Message: "--probes is meaningless with --snapshot: a snapshot carries its own probes, which the " +
				"twin is built with"}
		if code != findings.ExitError || len(doc.Findings) != 1 || doc.Findings[0] != want {
			t.Errorf("%v: exit %d, findings %+v; want 2 and %+v", args, code, doc.Findings, want)
		}
		validateM10Document(t, doc)
		mustCarryNoToken(t, args[1], raw)
	}
	if n := len(infra.requests()); n != 0 {
		t.Errorf("Infrahub was asked %d times", n)
	}
	if kind.reads.Load() != 0 {
		t.Errorf("the kind was read beside a snapshot")
	}
	if n := dials.Load(); n != 0 {
		t.Errorf("the workflow service was dialled %d times", n)
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

// intent read --out writes a snapshot 2 carrying the request's one list (FR-005, SC-006's
// tier-1 half): the file's, replacing the kind's; with no file, the kind's; with neither, [].
// Each document validates against the current findings contract.
func TestIntentReadWritesTheRequestsList(t *testing.T) {
	n1, n2 := declaredProbes(t, probesPath("n1-loop.json")), declaredProbes(t, probesPath("n2-loop.json"))
	for _, c := range []struct {
		name string
		kind []probe.Probe
		file string
		want []probe.Probe
	}{
		{"the file", n2, probesPath("n1-loop.json"), n1},
		{"the kind", n2, "", n2},
		{"neither", nil, "", []probe.Probe{}},
	} {
		t.Run(c.name, func(t *testing.T) {
			useFixtureRead(t)
			kind := &kindProbes{probes: c.kind}
			useProbeKind(t, kind)
			out := filepath.Join(t.TempDir(), "snap.json")
			args := []string{"intent", "read", "--branch", "fylgja-fixture", "--out", out}
			if c.file != "" {
				args = append(args, "--probes", c.file)
			}
			code, doc, _ := executeClient(t, args...)
			if code != findings.ExitOK || len(doc.Findings) != 0 {
				t.Fatalf("exit %d, findings %+v; want 0 and none", code, doc.Findings)
			}
			validateM10Document(t, doc)
			b, err := os.ReadFile(out)
			if err != nil {
				t.Fatal(err)
			}
			s, err := snap.Unmarshal(b)
			if err != nil {
				t.Fatal(err)
			}
			if !strings.Contains(string(b), `"snapshot_version": "2"`) || !reflect.DeepEqual(s.Probes, c.want) {
				t.Errorf("wrote a snapshot carrying %+v:\n%s\nwant a 2 carrying %+v", s.Probes, b, c.want)
			}
			if doc.SnapshotID != s.ID {
				t.Errorf("the document names snapshot %s; the file is %s", doc.SnapshotID, s.ID)
			}
			if reads := kind.reads.Load(); (c.file == "") != (reads == 1) {
				t.Errorf("the kind was read %d times; want once with no file and never with one", reads)
			}
		})
	}
}

// A create that sends a probe file the server's rules refuse is refused at start naming the
// file, before Infrahub is asked or the workflow service dialled.
func TestCreateWithAMalformedProbesFileIsRefusedAtStart(t *testing.T) {
	useStateRoot(t)
	infra := newFakeInfrahub(t)
	infra.start()
	dials := countDials(t)
	path := probesPath(filepath.Join("invalid", "probe.gateway.outside.json"))
	code, doc, _ := executeClient(t, "twin", "create", "--branch", "fylgja-fixture", "--probes", path)
	if code != findings.ExitRejected || len(doc.Findings) == 0 {
		t.Fatalf("exit %d, findings %+v; want 1", code, doc.Findings)
	}
	f := doc.Findings[0]
	if f.Rule != findings.RuleProbeGatewayOutside || f.Step != findings.StepStart || !strings.Contains(f.Message, path) {
		t.Errorf("finding %+v; want probe.gateway.outside at start, naming %s", f, path)
	}
	validateM10Document(t, doc)
	if n := len(infra.requests()); n != 0 {
		t.Errorf("Infrahub was asked %d times", n)
	}
	if n := dials.Load(); n != 0 {
		t.Errorf("the workflow service was dialled %d times", n)
	}
}
