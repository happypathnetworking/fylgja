package cli

import (
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
