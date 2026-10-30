package cli

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

// docOf reads a command's result as a consumer reads the document.
func docOf(t *testing.T, err error) (int, *findingsDoc) {
	t.Helper()
	var res *result
	if !asResult(err, &res) {
		t.Fatalf("command returned %v, want a findings result", err)
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

func invalidOverrideDir(t *testing.T) string {
	t.Helper()
	src, err := os.ReadFile(repoPath("testdata", "psp", "defects", "no-encoding.yaml"))
	if err != nil {
		t.Fatal(err)
	}
	dir := t.TempDir()
	if err := os.WriteFile(filepath.Join(dir, "nokia_srlinux.yaml"), src, 0o644); err != nil {
		t.Fatal(err)
	}
	return dir
}

func carries(doc *findingsDoc, rule string) bool {
	for _, f := range doc.Findings {
		if f.Rule == rule {
			return true
		}
	}
	return false
}

// An override package `psp validate` rejects is refused by the commands that load it,
// as a rejection naming the defect, rather than loaded and failing later under another
// identifier (M2's one behaviour change).
func TestInvalidOverridePackageIsARejection(t *testing.T) {
	dir := invalidOverrideDir(t)

	t.Run("twin compile", func(t *testing.T) {
		out := filepath.Join(t.TempDir(), "b")
		usePSPDir(t, dir)
		err := runCompile(&options{asJSON: true},
			&compileFlags{snapshotPath: wrappedFixture("three-node"), out: out})
		code, doc := docOf(t, err)
		if code != findings.ExitRejected || !carries(doc, findings.RulePSPReadinessEncoding) {
			t.Errorf("exit %d, findings %+v; want 1 with %s", code, doc.Findings, findings.RulePSPReadinessEncoding)
		}
		if _, err := os.Stat(out); !os.IsNotExist(err) {
			t.Errorf("a refused compile wrote %s", out)
		}
	})

}
