//go:build contract

package intent

import (
	"context"
	"os"
	"path/filepath"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/ctm"
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
// that nothing was wrong: the contract version, and each generic with the kinds
// implementing it by name.
func TestConformanceOnTheFixtureBranch(t *testing.T) {
	harness(t)
	conf, list := conformance(t, testsupport.FixtureBranch)
	if list.Rejected() {
		t.Fatalf("the fixture branch must conform, got %v", list)
	}
	if conf.Version != ctm.ContractVersion {
		t.Errorf("contract version = %q, want %q", conf.Version, ctm.ContractVersion)
	}
	// Each required generic, then the artifact target's row (M5).
	if len(conf.Generics) != len(ctm.RequiredGenerics)+1 {
		t.Fatalf("reported %d generics, want %d", len(conf.Generics), len(ctm.RequiredGenerics)+1)
	}
	if last := conf.Generics[len(conf.Generics)-1]; last.Generic != ctm.ArtifactTargetGeneric {
		t.Errorf("last row is %s, want %s", last.Generic, ctm.ArtifactTargetGeneric)
	}
	for _, g := range conf.Generics {
		if len(g.Kinds) == 0 {
			t.Errorf("generic %s reports no implementing kinds", g.Generic)
		}
		for _, k := range g.Kinds {
			// Naming the kind is the point: an operator has to see which of their own
			// kinds satisfies the contract, and a count cannot tell them.
			if k == "" {
				t.Errorf("generic %s reports an unnamed kind", g.Generic)
			}
		}
	}
	if conf.SchemaHash == "" {
		t.Error("no schema hash recorded")
	}
}

// A branch declaring a contract version this build does not understand is rejected
// before anything else is read, and the finding names both versions. Nothing else is
// reported: findings about a model Fylgja cannot interpret would mislead rather than help.
func TestContractVersionMismatchIsReportedAlone(t *testing.T) {
	c, branch := throwaway(t, "conf")
	if err := c.LoadSchema(branch, filepath.Join(repoRoot(), "schema")); err != nil {
		t.Fatalf("loading schema: %v", err)
	}
	const wrong = "9.9"
	if err := c.SeedContractVersion(branch, wrong); err != nil {
		t.Fatalf("seeding the contract: %v", err)
	}

	_, list := conformance(t, branch)
	if len(list) != 1 {
		t.Fatalf("expected exactly one finding, got %d: %v", len(list), list)
	}
	f := list[0]
	if f.Rule != findings.RuleContractVersionMismatch {
		t.Errorf("rule = %s, want %s", f.Rule, findings.RuleContractVersionMismatch)
	}
	for _, want := range []string{wrong, ctm.ContractVersion} {
		if !strings.Contains(f.Message, want) {
			t.Errorf("message does not name version %q: %s", want, f.Message)
		}
	}
	if f.Object != branch {
		t.Errorf("finding names %q, want the branch", f.Object)
	}
}

// Contract 0.2, against Infrahub: a kind that implements FylgjaDevice without
// inheriting CoreArtifactTarget is named by the check, and the reference NetworkDevice,
// which inherits both, is not. The kind is added by an additive schema load onto a
// throwaway branch that already carries the reference schema from main — the direction
// verified against Infrahub 1.11.2; removing an inherited interface by a load was never
// verified, so this does not rely on it.
//
// Two tier-2 tests were retired here at M5, TestBranchWithoutTheSchemaNamesEveryGeneric
// and TestUnimplementedGenericsAreNamed: with the schema on main no branch can be bare, so
// they had no live oracle. What they proved is tier 1's, against a faked schema
// (conformance_test.go).
func TestDeviceKindWithoutTheArtifactTargetIsNamed(t *testing.T) {
	c, branch := throwaway(t, "bare-kind")
	if err := c.SeedContractVersion(branch, ctm.ContractVersion); err != nil {
		t.Fatalf("seeding the contract: %v", err)
	}
	dir := t.TempDir()
	const bare = `---
version: "1.0"
nodes:
  - name: DeviceBare
    namespace: Network
    description: "A device kind that is no artifact target, for Fylgja's contract test."
    inherit_from: [FylgjaDevice]
`
	if err := os.WriteFile(filepath.Join(dir, "bare.yaml"), []byte(bare), 0o644); err != nil {
		t.Fatal(err)
	}
	if err := c.LoadSchema(branch, dir); err != nil {
		t.Fatalf("loading the bare kind: %v", err)
	}

	// The load rebuilds the branch schema asynchronously (CLAUDE.md): poll until the
	// schema endpoint lists the new kind as an implementer, then check once more.
	const kind = "NetworkDeviceBare"
	var conf *Conformance
	var list findings.List
	for deadline := time.Now().Add(90 * time.Second); ; {
		conf, list = conformance(t, branch)
		if slices.Contains(conf.Generics[0].Kinds, kind) {
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("%s never implemented %s on %s: %+v", kind, ctm.DeviceGeneric, branch, conf.Generics)
		}
		time.Sleep(time.Second)
	}

	want := findings.Finding{
		Severity: findings.Rejection,
		Rule:     findings.RuleSchemaArtifactTargetMissing,
		Object:   kind,
		Message: "kind NetworkDeviceBare implements FylgjaDevice but does not inherit CoreArtifactTarget, " +
			"so its devices can carry no configuration artifact",
	}
	if len(list) != 1 || list[0] != want {
		t.Fatalf("findings %+v, want exactly %+v", list, want)
	}
	last := conf.Generics[len(conf.Generics)-1]
	if last.Generic != ctm.ArtifactTargetGeneric || !slices.Contains(last.Kinds, "NetworkDevice") || slices.Contains(last.Kinds, kind) {
		t.Errorf("artifact target row %+v, want NetworkDevice and not %s", last, kind)
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
