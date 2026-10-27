package cli

import (
	"path/filepath"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/findings"
)

// M2 adds to the findings document; it removes nothing. Documents M1's commands produce
// still satisfy M1's own contract where they name no snapshot. From 018 twin compile reads a
// snapshot and names it, in subject.snapshot and, once compiled, snapshot_id, which M1's
// contract, closed to keys it does not hold, forbids: such a document is 018's, held to the
// current contract, as a create's naming one is (namesSnapshot).
func TestM1DocumentsStillSatisfyM1Schema(t *testing.T) {
	m1 := contractPath("001-read-compile", "findings.schema.json")
	compileDoc := func(snapshotPath string) *findings.Document {
		var res *result
		err := runCompile(&options{asJSON: true}, &compileFlags{snapshotPath: snapshotPath, out: filepath.Join(t.TempDir(), "bundle")})
		if !asResult(err, &res) {
			t.Fatalf("runCompile returned %v, want a findings result", err)
		}
		return res.doc
	}
	for _, c := range []struct {
		name     string
		doc      *findings.Document
		snapshot bool
	}{
		{"twin compile ok", compileDoc(wrappedFixture("three-node")), true},
		{"twin compile rejected", compileDoc(wrappedCTM(t, repoPath("testdata", "ctm", "defects", "five.json"))), true},
		{"twin compile error", compileDoc(""), false},
		{"intent read error", findings.ErrorDocument(findings.OpIntentRead, &findings.Subject{Branch: "fylgja-fixture"}, "unreachable"), false},
	} {
		t.Run(c.name, func(t *testing.T) {
			if got := namesSnapshot(t, c.doc); got != c.snapshot {
				t.Fatalf("the document names a snapshot: %t, want %t", got, c.snapshot)
			}
			if c.snapshot {
				validateM10Document(t, c.doc)
				return
			}
			validateDocument(t, m1, c.doc)
		})
	}
}
