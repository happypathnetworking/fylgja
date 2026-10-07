package cli

import (
	"path/filepath"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

// M2 adds to the findings document; it removes nothing. Documents M1's commands produce
// still satisfy M1's own contract.
func TestM1DocumentsStillSatisfyM1Schema(t *testing.T) {
	m1 := contractPath("001-read-compile", "findings.schema.json")
	compileDoc := func(ctmPath string) *findings.Document {
		var res *result
		err := runCompile(&options{asJSON: true}, &compileFlags{ctmPath: ctmPath, out: filepath.Join(t.TempDir(), "bundle")})
		if !asResult(err, &res) {
			t.Fatalf("runCompile returned %v, want a findings result", err)
		}
		return res.doc
	}
	for name, doc := range map[string]*findings.Document{
		"twin compile ok":       compileDoc(repoPath("testdata", "ctm", "three-node.json")),
		"twin compile rejected": compileDoc(repoPath("testdata", "ctm", "defects", "five.json")),
		"intent read error":     findings.ErrorDocument(findings.OpIntentRead, &findings.Subject{Branch: "fylgja-fixture"}, "unreachable"),
	} {
		t.Run(name, func(t *testing.T) { validateDocument(t, m1, doc) })
	}
}
