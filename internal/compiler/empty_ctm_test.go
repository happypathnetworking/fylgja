package compiler

import (
	"path/filepath"
	"strings"
	"testing"

	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/psp"
)

// A CTM with no devices never reaches the compiler in practice: internal/validate
// rejects it for both `intent read` and `twin compile`. The guard is here for a caller
// that skipped validation, and because a manifest for zero nodes cannot satisfy its own
// contract — fidelity.production_forwarding has no value.
//
// The rule and the wording match internal/validate's, so an operator cannot tell from
// the report which of the two produced it, and neither can drift without this failing.
func TestCompileRejectsAnEmptyCTM(t *testing.T) {
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	for _, tc := range []struct {
		label string
		at    string
	}{
		{"unpinned", ""},
		{"pinned", "2026-09-08T12:00:00Z"},
	} {
		t.Run(tc.label, func(t *testing.T) {
			c := &ctm.CTM{Envelope: ctm.Envelope{
				Branch:          "fylgja-fixture",
				At:              tc.at,
				ObservedAt:      "2026-09-08T12:00:00.000000Z",
				SchemaHash:      "fixture",
				ContractVersion: "0.2",
			}}
			files, list := Compile(c, reg)
			if files != nil {
				t.Errorf("an empty CTM produced %d files; a twin of nothing is not a bundle", len(files))
			}
			if !list.Rejected() {
				t.Fatalf("an empty CTM was not rejected: %v", list)
			}
			if len(list) != 1 || list[0].Rule != findings.RuleDevicesEmpty {
				t.Fatalf("expected exactly one %s, got %v", findings.RuleDevicesEmpty, list)
			}
			if !strings.Contains(list[0].Message, "fylgja-fixture") {
				t.Errorf("the message does not name the branch: %q", list[0].Message)
			}
			if tc.at != "" && !strings.Contains(list[0].Message, tc.at) {
				t.Errorf("a pinned empty read must name the `at`: %q", list[0].Message)
			}
		})
	}
}

// The fixture on disk takes the same path, so the file and the in-memory case cannot
// diverge.
func TestCompileRejectsTheEmptyFixture(t *testing.T) {
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	c, err := ctm.Load(filepath.Join("..", "..", "testdata", "ctm", "defects", "devices-empty.json"))
	if err != nil {
		t.Fatal(err)
	}
	files, list := Compile(c, reg)
	if files != nil {
		t.Errorf("devices-empty.json produced %d files", len(files))
	}
	if len(list) != 1 || list[0].Rule != findings.RuleDevicesEmpty {
		t.Errorf("expected exactly one %s, got %v", findings.RuleDevicesEmpty, list)
	}
}
