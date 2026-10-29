package compiler

import (
	"bytes"
	"encoding/json"
	"reflect"
	"slices"
	"testing"
	"time"

	"github.com/happypathnetworking/fylgja/internal/bundle"
	"github.com/happypathnetworking/fylgja/internal/ctm"
	"github.com/happypathnetworking/fylgja/internal/probe"
	"github.com/happypathnetworking/fylgja/internal/psp"
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

// Two fidelity rows that tie on (disposition, object), as two omissions of one cable for
// different reasons would, are ordered by source, then reason: either order of arrival
// gives one manifest and one bundle_id (Constitution V; T092). The Infrahub reader cannot
// write such a tie, DcimCable.label being unique; a hand-written CTM or a later reader can.
func TestTiedFidelityRowsIgnoreInputOrder(t *testing.T) {
	reg, err := psp.Load("")
	if err != nil {
		t.Fatal(err)
	}
	ends := ctm.FidelityRow{Disposition: ctm.FidelityOmitted, Object: "c-9", Source: "DcimCable", Reason: "other than two ends (3)"}
	port := ctm.FidelityRow{Disposition: ctm.FidelityOmitted, Object: "c-9", Source: "DcimCable", Reason: "an end not on a physical port (DcimConsolePort)"}
	other := ctm.FidelityRow{Disposition: ctm.FidelityOmitted, Object: "c-9", Source: "AcmeCable", Reason: "other than two ends (3)"}
	compileWith := func(rows ...ctm.FidelityRow) map[string][]byte {
		t.Helper()
		c := loadFixture(t, "testdata/ctm/three-node.json")
		c.Envelope.Fidelity = append(c.Envelope.Fidelity, rows...)
		files, list := Compile(c, nil, reg, nil)
		if list.Rejected() {
			t.Fatalf("refused: %v", list)
		}
		return files
	}

	first := compileWith(ends, port, other)
	second := compileWith(other, port, ends)
	sameBundle(t, "the tied rows' order", first, second)
	if bundle.ID(first) != bundle.ID(second) {
		t.Errorf("the tied rows' order changed the bundle id: %s vs %s", bundle.ID(first), bundle.ID(second))
	}

	var m Manifest
	if err := json.Unmarshal(first[ManifestFile], &m); err != nil {
		t.Fatal(err)
	}
	var tied []ctm.FidelityRow
	for _, r := range m.Fidelity.Read {
		if r.Object == "c-9" {
			tied = append(tied, r)
		}
	}
	if want := []ctm.FidelityRow{other, port, ends}; !reflect.DeepEqual(tied, want) {
		t.Errorf("the tied rows read %+v, want them by source, then reason: %+v", tied, want)
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

// A probed snapshot compiles to the same bytes whatever order its devices, its interfaces
// and its probes arrive in (016).
func TestAProbedCompileIsDeterministic(t *testing.T) {
	decls := append(declared(t, "n1-loop"), declared(t, "n2-loop")...)
	first := compileProbed(t, probedThreeNode(t), decls)

	shuffled := probedThreeNode(t)
	slices.Reverse(shuffled.Devices)
	for i := range shuffled.Devices {
		slices.Reverse(shuffled.Devices[i].Interfaces)
	}
	slices.Reverse(shuffled.Links)
	second := compileProbed(t, shuffled, []probe.Probe{decls[1], decls[0]})
	sameBundle(t, "a shuffled probed snapshot", first.files, second.files)
}
