package cli

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

// A CTM of another version is refused before any rule runs, ctm.version.unsupported at
// the file the operator gave, naming both versions, with no step, and nothing is written:
// every other finding would be about a format this build does not read, and nothing
// converts one (017; FR-028). A CTM "2" carries no contract version; its own version is
// the contract's (D-057). The file is a CTM "1" as the last build of that format wrote it.
func TestAnotherCTMVersionIsRefusedBeforeValidation(t *testing.T) {
	path := repoPath("testdata", "ctm", "defects", "version-1.json")
	out := filepath.Join(t.TempDir(), "b")
	code, doc := runCompileTo(t, path, out)
	if code != findings.ExitRejected || doc.Status != string(findings.StatusRejected) {
		t.Fatalf("exit %d, status %s; want %d, rejected", code, doc.Status, findings.ExitRejected)
	}
	const message = `the CTM declares ctm_version "1"; this build reads "2", and nothing converts one`
	if len(doc.Findings) != 1 || doc.Findings[0].Severity != string(findings.Rejection) ||
		doc.Findings[0].Rule != findings.RuleCTMVersionUnsupported || doc.Findings[0].Object != path ||
		doc.Findings[0].Message != message || doc.Findings[0].Location != nil {
		t.Errorf("findings %+v, want one %s at %s: %s", doc.Findings, findings.RuleCTMVersionUnsupported, path, message)
	}
	if _, err := os.Stat(out); !os.IsNotExist(err) {
		t.Errorf("a refused compile wrote something to %s", out)
	}
}

// A CTM that leaves out its version or its fidelity list, both required of a file, is
// refused by twin compile before anything is written, exit 1, naming the field, with no
// bundle_id (017, T090): no ctm_version is ctm.version.unsupported at the file, naming
// "2", as a "1" is; no envelope.fidelity, or a null one, is data.required.missing at the
// field, as an empty envelope field is, since [] would say the reader approximated and
// omitted nothing. No links, or a device's interfaces left out, is refused alike, the
// device named by its place in the file (T095): filled with [], either would compile as a
// twin with no cable or a node with no port.
func TestCompileRefusesACTMLeavingOutARequiredField(t *testing.T) {
	for _, c := range []struct {
		name, rule, object, message string
		change                      func(map[string]any)
	}{
		{"no ctm_version", findings.RuleCTMVersionUnsupported, "",
			`the CTM declares no ctm_version; this build reads "2", and nothing converts one`,
			func(m map[string]any) { delete(m, "ctm_version") }},
		{"no envelope.fidelity", findings.RuleRequiredMissing, "envelope.fidelity", "",
			func(m map[string]any) { delete(m["envelope"].(map[string]any), "fidelity") }},
		{"a null envelope.fidelity", findings.RuleRequiredMissing, "envelope.fidelity", "",
			func(m map[string]any) { m["envelope"].(map[string]any)["fidelity"] = nil }},
		{"no links", findings.RuleRequiredMissing, "links", "",
			func(m map[string]any) { delete(m, "links") }},
		{"a null links", findings.RuleRequiredMissing, "links", "",
			func(m map[string]any) { m["links"] = nil }},
		{"a device's interfaces left out", findings.RuleRequiredMissing, "devices[1].interfaces", "",
			func(m map[string]any) { delete(m["devices"].([]any)[1].(map[string]any), "interfaces") }},
	} {
		t.Run(c.name, func(t *testing.T) {
			b, err := os.ReadFile(repoPath("testdata", "ctm", "three-node.json"))
			if err != nil {
				t.Fatal(err)
			}
			var m map[string]any
			if err := json.Unmarshal(b, &m); err != nil {
				t.Fatal(err)
			}
			c.change(m)
			if b, err = json.Marshal(m); err != nil {
				t.Fatal(err)
			}
			dir := t.TempDir()
			in, out := filepath.Join(dir, "edited.ctm.json"), filepath.Join(dir, "b")
			if err := os.WriteFile(in, b, 0o644); err != nil {
				t.Fatal(err)
			}
			object := c.object
			if object == "" {
				object = in
			}

			code, doc := runCompileTo(t, in, out)
			if code != findings.ExitRejected || len(doc.Findings) != 1 || doc.Findings[0].Rule != c.rule ||
				doc.Findings[0].Object != object || doc.Findings[0].Severity != string(findings.Rejection) ||
				doc.Findings[0].Location != nil {
				t.Fatalf("exit %d, findings %+v; want 1 with %s naming %s alone", code, doc.Findings, c.rule, object)
			}
			if c.message != "" && doc.Findings[0].Message != c.message {
				t.Errorf("message %q, want %q", doc.Findings[0].Message, c.message)
			}
			if c.rule == findings.RuleRequiredMissing && !strings.HasPrefix(doc.Findings[0].Message, c.object+", ") {
				t.Errorf("message %q does not name %s", doc.Findings[0].Message, c.object)
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

// The document is the contract, so the success shape is asserted through it: one
// document, the operation named, a 64-hex bundle_id, no findings (contracts/cli.md).
func TestSuccessDocumentCarriesTheBundleID(t *testing.T) {
	out := filepath.Join(t.TempDir(), "b")
	code, doc := runCompileTo(t, repoPath("testdata", "ctm", "three-node.json"), out)
	if code != 0 {
		t.Fatalf("exit %d: %+v", code, doc.Findings)
	}
	if doc.Operation != findings.OpCompile {
		t.Errorf("operation = %q, want %q", doc.Operation, findings.OpCompile)
	}
	if doc.Status != "ok" {
		t.Errorf("status = %q, want ok", doc.Status)
	}
	if len(doc.BundleID) != 64 {
		t.Errorf("bundle_id = %q, want 64 hex characters", doc.BundleID)
	}
	if len(doc.Findings) != 0 {
		t.Errorf("a clean compile reported findings: %+v", doc.Findings)
	}
}

// A compile that records omissions still succeeds: they are info findings, not
// rejections, and the bundle is written.
func TestOmissionsAreReportedButDoNotFail(t *testing.T) {
	out := filepath.Join(t.TempDir(), "b")
	code, doc := runCompileTo(t, repoPath("testdata", "ctm", "mgmt-link.json"), out)
	if code != 0 {
		t.Fatalf("exit %d, want 0: %+v", code, doc.Findings)
	}
	var infos int
	for _, f := range doc.Findings {
		if f.Severity != string(findings.Info) {
			t.Errorf("finding %s is %s, want info", f.Rule, f.Severity)
		}
		infos++
	}
	if infos == 0 {
		t.Error("the omission was not reported in the findings document")
	}
	if _, err := os.Stat(filepath.Join(out, "manifest.json")); err != nil {
		t.Errorf("a compile with omissions wrote no bundle: %v", err)
	}
}

// Text mode keeps stdout for the success lines and stderr for findings, and the
// bundle_id is on stdout where a shell can capture it (contracts/cli.md).
func TestTextModePrintsTheBundleIDOnStdout(t *testing.T) {
	out := filepath.Join(t.TempDir(), "b")
	stdout := captureStdout(t, func() {
		opts := &options{}
		if err := runCompile(opts, &compileFlags{
			ctmPath: repoPath("testdata", "ctm", "three-node.json"), out: out,
		}); err != nil {
			var res *result
			if !asResult(err, &res) || res.doc.Status != findings.StatusOK {
				t.Fatalf("compile failed: %v", err)
			}
		}
	})
	if !strings.Contains(stdout, "wrote bundle to "+out+" (3 nodes, 3 links)") {
		t.Errorf("stdout does not carry the success line:\n%s", stdout)
	}
	if !strings.Contains(stdout, "bundle_id ") {
		t.Errorf("stdout does not carry the bundle id:\n%s", stdout)
	}
}

// captureStdout redirects os.Stdout for the duration of fn. The note helper writes
// straight to it, which is the behaviour under test.
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
