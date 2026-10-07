package cli

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
)

// ctmWithContractVersion writes three-node.json with a different contract version and
// nothing else changed, so the only thing the compiler can object to is the version.
func ctmWithContractVersion(t *testing.T, version string) string {
	t.Helper()
	b, err := os.ReadFile(repoPath("testdata", "ctm", "three-node.json"))
	if err != nil {
		t.Fatal(err)
	}
	out := strings.Replace(string(b),
		`"contract_version": "`+ctm.ContractVersion+`"`,
		`"contract_version": "`+version+`"`, 1)
	if out == string(b) {
		t.Fatalf("could not rewrite the contract version in the fixture")
	}
	path := filepath.Join(t.TempDir(), "other-contract.json")
	if err := os.WriteFile(path, []byte(out), 0o644); err != nil {
		t.Fatal(err)
	}
	return path
}

// A CTM conforming to a contract this build does not understand is rejected by that
// rule alone, naming both versions. Reporting it beside other findings would dress up
// noise as detail: every other rule would be judging a model Fylgja cannot interpret.
func TestContractVersionMismatchIsReportedAlone(t *testing.T) {
	path := ctmWithContractVersion(t, "9.9")
	out := filepath.Join(t.TempDir(), "b")

	code, doc := runCompileTo(t, path, out)
	if code != 1 {
		t.Fatalf("exit %d, want 1 (a rejection)", code)
	}
	if len(doc.Findings) != 1 {
		t.Fatalf("got %d findings, want exactly 1:\n%+v", len(doc.Findings), doc.Findings)
	}
	f := doc.Findings[0]
	if f.Rule != findings.RuleContractVersionMismatch {
		t.Errorf("rule = %q, want %q", f.Rule, findings.RuleContractVersionMismatch)
	}
	if f.Severity != string(findings.Rejection) {
		t.Errorf("severity = %q, want a rejection", f.Severity)
	}
	for _, want := range []string{"9.9", ctm.ContractVersion} {
		if !strings.Contains(f.Message, want) {
			t.Errorf("message %q does not name %q", f.Message, want)
		}
	}
	if _, err := os.Stat(out); !os.IsNotExist(err) {
		t.Errorf("a rejected compile wrote something to %s", out)
	}
}

// The check runs before validate.Validate, not inside it: a CTM that is both on the
// wrong contract and full of other defects reports the version and nothing else.
func TestContractVersionIsCheckedBeforeValidation(t *testing.T) {
	b, err := os.ReadFile(repoPath("testdata", "ctm", "defects", "five.json"))
	if err != nil {
		t.Fatal(err)
	}
	out := strings.Replace(string(b),
		`"contract_version": "`+ctm.ContractVersion+`"`, `"contract_version": "9.9"`, 1)
	path := filepath.Join(t.TempDir(), "five-other-contract.json")
	if err := os.WriteFile(path, []byte(out), 0o644); err != nil {
		t.Fatal(err)
	}

	code, doc := runCompileTo(t, path, filepath.Join(t.TempDir(), "b"))
	if code != 1 {
		t.Fatalf("exit %d, want 1", code)
	}
	if len(doc.Findings) != 1 || doc.Findings[0].Rule != findings.RuleContractVersionMismatch {
		t.Errorf("a CTM on the wrong contract reported %d findings; validation ran anyway:\n%+v",
			len(doc.Findings), doc.Findings)
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
