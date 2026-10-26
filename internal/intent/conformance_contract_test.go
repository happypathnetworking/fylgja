//go:build contract

package intent

import (
	"context"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/findings"
	"github.com/happypathnetworking/fylgja/internal/testsupport"
)

// conformance runs the check the way `intent read` and `schema check` both run it.
func conformance(t *testing.T, branch string) (*Conformance, findings.List) {
	t.Helper()
	cfg, err := FromEnv(branch, "")
	if err != nil {
		t.Skipf("contract tests need a running Infrahub: %v", err)
	}
	ctx, cancel := context.WithTimeout(t.Context(), 2*time.Minute)
	defer cancel()
	conf, list, err := New(cfg).CheckConformance(ctx)
	if err != nil {
		t.Fatalf("checking conformance: %v", err)
	}
	return conf, list
}

// The fixture branch conforms, and the check says what it verified rather than merely
// that nothing was wrong: the library's commit, and each kind the mapping reads with its
// fields. The library's refusals, field by field, are tier 1's (conformance_test.go);
// TestSchemaCheckNamesAMissingKind proves one live.
func TestConformanceOnTheFixtureBranch(t *testing.T) {
	harness(t)
	conf, list := conformance(t, testsupport.FixtureBranch)
	if list.Rejected() {
		t.Fatalf("the fixture branch must conform, got %v", list)
	}
	if conf.Model != LibraryModel || conf.Version != LibraryVersion {
		t.Errorf("conformance %s@%s, want %s@%s", conf.Model, conf.Version, LibraryModel, LibraryVersion)
	}
	if len(conf.Kinds) != len(LibraryTables) {
		t.Errorf("verified %d kinds, want %d: %+v", len(conf.Kinds), len(LibraryTables), conf.Kinds)
	}
	if conf.SchemaHash == "" {
		t.Error("no schema hash recorded")
	}
}

// The schema endpoint has no time axis, so conformance sends no `at`.
// The hash a read records is therefore the branch's current schema hash, even for a
// pinned read — which is deliberate, and is recorded here so nobody later
// reads it as "the schema as of at".
func TestConformanceSendsNoAt(t *testing.T) {
	harness(t)
	unpinned, _ := conformance(t, testsupport.FixtureBranch)

	cfg, err := FromEnv(testsupport.FixtureBranch, "2026-09-09T00:00:00Z")
	if err != nil {
		t.Skipf("contract tests need a running Infrahub: %v", err)
	}
	ctx, cancel := context.WithTimeout(t.Context(), time.Minute)
	defer cancel()
	info, err := New(cfg).SchemaInfo(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if info.Hash != unpinned.SchemaHash {
		t.Errorf("a pinned read saw schema hash %q, an unpinned read %q; the schema endpoint has no time axis",
			info.Hash, unpinned.SchemaHash)
	}
}

// A branch whose DCIM lacks a kind the mapping reads is refused by name, the message naming
// the library's commit, and nothing else is named (US3; FR-011, FR-012): on a throwaway
// branch holding the library alone, DcimCable removed by a state: absent document. The
// conformance check names it once, though Infrahub also leaves DcimConnector with no
// implementer, and the read refuses the branch on it with no request beyond the schema's.
func TestSchemaCheckNamesAMissingKind(t *testing.T) {
	c, branch := throwaway(t, "nocable")
	if err := c.LoadSchema(branch, filepath.Join(repoRoot(), "schema")); err != nil {
		t.Fatalf("loading schema: %v", err)
	}
	began := time.Now()
	if err := c.LoadSchemaFile(branch, filepath.Join("testdata", "dcim-cable-absent.yaml")); err != nil {
		t.Fatalf("removing DcimCable: %v", err)
	}
	t.Logf("branch %s: DcimCable removed in %s", branch, time.Since(began).Round(100*time.Millisecond))

	_, list := conformance(t, branch)
	if len(list) != 1 {
		t.Fatalf("findings %v; want schema.kind.missing DcimCable alone", list)
	}
	f := list[0]
	if f.Severity != findings.Rejection || f.Rule != findings.RuleSchemaKindMissing || f.Object != "DcimCable" ||
		!strings.HasSuffix(f.Message, "as "+LibraryModel+"@"+LibraryVersion+" has it") {
		t.Errorf("finding %+v; want a rejection %s on DcimCable naming %s@%s", f, findings.RuleSchemaKindMissing, LibraryModel, LibraryVersion)
	}

	got, read, _, err := readUnder(t, branch, "", fixtureScope)
	if err != nil {
		t.Fatalf("reading %s: %v", branch, err)
	}
	if got != nil || !reflect.DeepEqual(read, list) {
		t.Errorf("the read gave a CTM %v and findings %v; want none and the check's %v", got != nil, read, list)
	}
}
