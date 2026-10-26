//go:build contract

package intent

import (
	"context"
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
// fields. It holds the library once T060 re-seeds it.
//
// Three tests left at 017's T036, with the generics' conformance:
// TestContractVersionMismatchIsReportedAlone (the contract version is the bridged read's
// to check until T039, and its rule goes at T042) and
// TestDeviceKindWithoutTheArtifactTargetIsNamed (schema.artifact_target.missing went with
// the generics). The library's refusals are tier 1's (conformance_test.go), and T044's
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
