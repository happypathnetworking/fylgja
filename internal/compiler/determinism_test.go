package compiler

import (
	"bytes"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/bundle"
)

// sameBundle compares two compiles file by file, in both directions: a file that
// appeared in one and not the other is as much a difference as a byte that moved.
func sameBundle(t *testing.T, label string, a, b map[string][]byte) {
	t.Helper()
	for name, want := range a {
		got, ok := b[name]
		if !ok {
			t.Errorf("%s: %s missing from the second bundle", label, name)
			continue
		}
		if !bytes.Equal(want, got) {
			t.Errorf("%s: %s differs:\n--- first\n%s\n--- second\n%s", label, name, want, got)
		}
	}
	for name := range b {
		if _, ok := a[name]; !ok {
			t.Errorf("%s: %s appeared only in the second bundle", label, name)
		}
	}
}

// Identical intent must yield byte-identical bundles and one id.
// Determinism is what makes a bundle diffable, and what lets M2 trust that
// redeploying the same intent redeploys the same twin.
func TestCompileIsDeterministic(t *testing.T) {
	first := compileFixture(t, "testdata/ctm/three-node.json")
	second := compileFixture(t, "testdata/ctm/three-node.json")
	sameBundle(t, "two compiles of identical input", first, second)
	if bundle.ID(first) != bundle.ID(second) {
		t.Errorf("two compiles of identical input produced different ids: %s vs %s",
			bundle.ID(first), bundle.ID(second))
	}
}

// Ordering must come from normalization, not from the order intent happened to arrive
// in. The shuffled fixture holds the same topology with devices, interfaces, links and
// endpoints deliberately disordered on disk.
func TestCompileIgnoresInputOrder(t *testing.T) {
	ordered := compileFixture(t, "testdata/ctm/three-node.json")
	shuffled := compileFixture(t, "testdata/ctm/three-node.shuffled.json")
	sameBundle(t, "input order", ordered, shuffled)
	if bundle.ID(ordered) != bundle.ID(shuffled) {
		t.Errorf("input order changed the bundle id: %s vs %s", bundle.ID(ordered), bundle.ID(shuffled))
	}
}

// The lossy fixture decides sharing, the lossy record and the omissions from groups of
// interfaces, and a group built in the order intent listed it would name another holder
// or another reason: the rules are the package's slice and the groups are built in name
// order.
func TestLossyCompileIgnoresInputOrder(t *testing.T) {
	ordered := compileLossyFixture(t, "testdata/ctm/lossy.json")
	shuffled := compileLossyFixture(t, "testdata/ctm/lossy.shuffled.json")
	sameBundle(t, "input order", ordered, shuffled)
	if bundle.ID(ordered) != bundle.ID(shuffled) {
		t.Errorf("input order changed the bundle id: %s vs %s", bundle.ID(ordered), bundle.ID(shuffled))
	}
}

// The mixed fixture is two platforms in one bundle, and the order intent arrived in must
// decide nothing about it: the shuffled copy holds the same devices, interfaces, links and
// endpoints in another order on disk, and compiles byte for byte the same (Constitution
// V). Two packages make this stricter than the single-platform case — the
// forwarding object, the approximations and the nodes are gathered per device — so a map
// iterated rather than sorted somewhere would show up here.
func TestMixedCompileIgnoresInputOrder(t *testing.T) {
	ordered := compileFixture(t, "testdata/ctm/mixed.json")
	shuffled := compileFixture(t, "testdata/ctm/mixed.shuffled.json")
	sameBundle(t, "input order", ordered, shuffled)
	if bundle.ID(ordered) != bundle.ID(shuffled) {
		t.Errorf("input order changed the bundle id: %s vs %s", bundle.ID(ordered), bundle.ID(shuffled))
	}
	if id := bundle.ID(shuffled); id != goldenMixedID {
		t.Errorf("the shuffled mixed fixture compiled to %s, want the golden's %s", id, goldenMixedID)
	}
}

// The three-node fixture must compile well inside five seconds. The budget is
// generous on purpose: this guards against an accidental quadratic in mapping or
// ordering, not against ordinary slowness.
func TestCompileIsFast(t *testing.T) {
	const budget = 5 * time.Second
	start := time.Now()
	compileFixture(t, "testdata/ctm/three-node.json")
	if elapsed := time.Since(start); elapsed > budget {
		t.Errorf("compiling the three-node fixture took %s, budget is %s", elapsed, budget)
	}
}
